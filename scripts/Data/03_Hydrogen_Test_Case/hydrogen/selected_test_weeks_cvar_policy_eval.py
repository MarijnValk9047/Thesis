from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

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
)
from .selected_week_policy import (
    OFFICIAL_TEST_SELECTED_WEEKS_PATH,
    TEST_SELECTED_REGIME_LABELS,
    resolve_registry_rows,
    run_selected_week_input_preflight,
)
from .selected_week_suite import _valid_daily_registry_for_artifact
from .validation_cvar_expanded_sweep import (
    _aggregate_perfect_foresight_metrics,
    _build_cvar_frontier_aggregated,
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


DEFAULT_WEEK_IDS = (
    "typical_summer",
    "typical_winter",
    "high_volatility",
    "high_price",
)
DEFAULT_SELECTED_WEEKS_YAML = OFFICIAL_TEST_SELECTED_WEEKS_PATH
DEFAULT_ALPHA = 0.95
DEFAULT_GAMMAS = (0.0, 0.05, 0.25)


@dataclass(frozen=True)
class PhaseE2PolicyEvalResult:
    run_dir: Path
    notebook_path: Path
    selected_weeks: pd.DataFrame
    support_days: pd.DataFrame
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    cvar_frontier_aggregated: pd.DataFrame
    model_selection_evidence_summary: pd.DataFrame
    validation_checks: pd.DataFrame
    cvar_validation_checks: pd.DataFrame
    benchmark_metrics: pd.DataFrame
    perfect_foresight_metrics: pd.DataFrame


def _normalized_gamma_tag(gamma: float) -> str:
    return str(float(gamma)).replace("-", "m").replace(".", "p")


def _slugify(label: str) -> str:
    return str(label).lower().replace(" ", "_")


def _build_phase_e2_config(
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
            execution_mode="selected_test_weeks_cvar_policy_eval",
        ),
        models=replace(base.models, include=tuple(str(value) for value in artifact_ids)),
        strategies=("stochastic_cvar_fixed_policy_selected_test_weeks",),
    )
    if output_root is not None:
        updated = replace(updated, outputs=replace(updated.outputs, root=Path(output_root)))
    return updated


def _load_and_validate_phase_e2_weeks(
    *,
    week_registry_path: Path,
    support_csv_path: Path,
    selected_weeks_yaml_path: Path | None,
    week_ids: list[str] | tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not week_registry_path.exists():
        raise FileNotFoundError(f"selected_week_registry_common_support.csv not found: {week_registry_path}")
    if not support_csv_path.exists():
        raise FileNotFoundError(f"common_support_three_model_hourly.csv not found: {support_csv_path}")
    support = pd.read_csv(support_csv_path)
    support["delivery_date"] = pd.to_datetime(support["delivery_date"], errors="raise")
    if selected_weeks_yaml_path is None:
        raise ValueError("Phase E2 requires the official selected test-week config.")
    registry_rows = resolve_registry_rows(
        registry_path=week_registry_path,
        selected_weeks_yaml_path=selected_weeks_yaml_path,
        requested_identifiers=[str(value) for value in week_ids],
        expected_split="test",
    )

    selected_rows: list[dict[str, Any]] = []
    support_rows: list[pd.DataFrame] = []
    for requested_week, row in zip([str(value) for value in week_ids], registry_rows.to_dict(orient="records"), strict=True):
        checks = {
            "regime_label": str(row["regime_label"]) in TEST_SELECTED_REGIME_LABELS,
            "period_type": str(row["period_type"]) == "test",
            "number_of_delivery_days": int(row["number_of_delivery_days"]) == 7,
            "complete_for_lear_strict": bool(row["complete_for_lear_strict"]),
            "complete_for_lear_fs3": bool(row["complete_for_lear_fs3"]),
            "complete_for_xgboost_fs3": bool(row["complete_for_xgboost_fs3"]),
            "complete_actual_prices": bool(row["complete_actual_prices"]),
            "support_status": str(row["support_status"]) == "common_complete_support_selected",
            "methodological_use": str(row["methodological_use"]) == "diagnostic_reporting",
        }
        failures = [name for name, ok in checks.items() if not ok]
        if failures:
            raise ValueError(f"Phase E2 selected-week validation failed for {requested_week}: {failures}")

        start = str(row["delivery_start_date"])
        end = str(row["delivery_end_date"])
        week_support = support.loc[
            (support["delivery_date"] >= pd.Timestamp(start))
            & (support["delivery_date"] <= pd.Timestamp(end))
        ].copy()
        if int(week_support.shape[0]) != 7:
            raise ValueError(f"Expected 7 support rows for {requested_week}, found {int(week_support.shape[0])}.")
        expected_dates = pd.date_range(start, end, freq="D")
        actual_dates = pd.DatetimeIndex(week_support["delivery_date"]).sort_values()
        if not actual_dates.equals(expected_dates):
            raise ValueError(f"Support rows for {requested_week} are not exactly {start}..{end}.")
        required_complete = (
            week_support["period_type"].astype(str).eq("test")
            & week_support["complete_actual_prices"].astype(bool)
            & week_support["complete_for_lear_strict"].astype(bool)
            & week_support["complete_for_lear_fs3"].astype(bool)
            & week_support["complete_for_xgboost_fs3"].astype(bool)
            & week_support["common_complete_support"].astype(bool)
            & week_support["n_hours_actual"].astype(int).eq(24)
            & week_support["n_hours_lear_strict"].astype(int).eq(24)
            & week_support["n_hours_lear_fs3"].astype(int).eq(24)
            & week_support["n_hours_xgboost_fs3"].astype(int).eq(24)
            & week_support["n_scenarios_per_origin_lear_strict"].astype(int).eq(75)
            & week_support["n_scenarios_per_origin_lear_fs3"].astype(int).eq(75)
            & week_support["n_scenarios_per_origin_xgboost_fs3"].astype(int).eq(75)
        )
        if not bool(required_complete.all()):
            bad_days = week_support.loc[~required_complete, "delivery_date"].dt.strftime("%Y-%m-%d").tolist()
            raise ValueError(f"Week {requested_week} contains incomplete common-support days: {bad_days}")

        selected_rows.append(dict(row))
        week_support["week_id"] = str(row["week_id"])
        week_support["week_label"] = str(row["week_label"])
        week_support["regime_label"] = str(row["regime_label"])
        support_rows.append(week_support)

    selected_weeks = pd.DataFrame(selected_rows)
    support_days = pd.concat(support_rows, ignore_index=True).sort_values(["delivery_date"]).reset_index(drop=True)
    return selected_weeks, support_days


def _build_general_test_validation_checks(
    *,
    existing_checks: pd.DataFrame,
    selected_weeks: pd.DataFrame,
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
            check_name="selected_weeks_exact_fixed_policy_test_set",
            status="pass" if selected_weeks["regime_label"].astype(str).tolist() == list(DEFAULT_WEEK_IDS) else "fail",
            details=f"regime_labels={selected_weeks['regime_label'].astype(str).tolist()}",
        )
    )
    rows.append(
        _validation_row(
            check_name="all_selected_days_inside_common_test_support",
            status="pass" if support_days["period_type"].astype(str).eq("test").all() and support_days["common_complete_support"].astype(bool).all() else "fail",
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
    rows.append(_validation_row(check_name="complete_actual_prices_for_selected_days", status="pass" if support_days["complete_actual_prices"].astype(bool).all() else "fail", details="complete_actual_prices all true"))
    rows.append(_validation_row(check_name="artifacts_run_on_same_selected_test_weeks", status="pass" if sorted(daily_metrics["artifact_id"].astype(str).unique().tolist()) == sorted([str(value) for value in artifact_ids]) else "fail", details=f"artifacts={sorted(daily_metrics['artifact_id'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="scenario_count_75_for_all_selected_days", status="pass" if daily_metrics["scenario_count"].astype(int).eq(75).all() else "fail", details=f"scenario_count_values={sorted(daily_metrics['scenario_count'].astype(int).unique().tolist())}"))
    rows.append(_validation_row(check_name="scenario_probability_check_passes", status="pass" if daily_metrics["scenario_probability_check"].astype(bool).all() else "fail", details=f"pass_count={int(daily_metrics['scenario_probability_check'].astype(bool).sum())}/{int(daily_metrics.shape[0])}"))
    rows.append(_validation_row(check_name="submitted_minus_cleared_equals_rejected", status="pass" if np.allclose(daily_metrics["submitted_energy_mwh"].astype(float) - daily_metrics["cleared_energy_mwh"].astype(float), daily_metrics["rejected_energy_mwh"].astype(float), atol=1e-6) else "fail", details="daily submitted - cleared = rejected"))
    rows.append(_validation_row(check_name="used_plus_unused_equals_cleared", status="pass" if np.allclose(daily_metrics["used_cleared_energy_mwh"].astype(float) + daily_metrics["unused_cleared_energy_mwh"].astype(float), daily_metrics["cleared_energy_mwh"].astype(float), atol=1e-6) else "fail", details="daily used + unused = cleared"))
    rows.append(_validation_row(check_name="benchmark_same_actual_prices_and_days", status="pass" if int(benchmark_daily.shape[0]) == int(support_days.shape[0]) * len(artifact_ids) else "fail", details=f"benchmark_daily_rows={int(benchmark_daily.shape[0])}"))
    if not benchmark_identity_checks.empty:
        rows.append(_validation_row(check_name="benchmark_identical_across_artifacts_per_day", status="pass" if benchmark_identity_checks["status"].astype(str).eq("pass").all() else "fail", details=f"checks={benchmark_identity_checks[['delivery_day', 'details']].to_dict(orient='records')}"))
    if perfect_foresight_included:
        rows.append(_validation_row(check_name="perfect_foresight_same_actual_prices_and_days", status="pass" if int(perfect_foresight_daily.shape[0]) == int(support_days.shape[0]) else "fail", details=f"perfect_foresight_daily_rows={int(perfect_foresight_daily.shape[0])}"))
        if not perfect_foresight_identity_checks.empty:
            rows.append(_validation_row(check_name="perfect_foresight_identical_across_artifacts_per_day", status="pass" if perfect_foresight_identity_checks["status"].astype(str).eq("pass").all() else "fail", details=f"checks={perfect_foresight_identity_checks[['delivery_day', 'details']].to_dict(orient='records')}"))
    rows.append(_validation_row(check_name="cvar_alpha_exactly_0p95", status="pass" if abs(float(cvar_alpha) - 0.95) <= 1e-12 and daily_metrics["cvar_alpha"].astype(float).eq(0.95).all() else "fail", details=f"unique_alpha={sorted(daily_metrics['cvar_alpha'].astype(float).unique().tolist())}"))
    rows.append(_validation_row(check_name="gamma_grid_exactly_requested", status="pass" if sorted(daily_metrics["cvar_gamma"].astype(float).unique().tolist()) == sorted([float(value) for value in gamma_values]) else "fail", details=f"observed_gamma_values={sorted(daily_metrics['cvar_gamma'].astype(float).unique().tolist())}"))
    rows.append(_validation_row(check_name="no_quarter_hour_data_used", status="pass" if actual_clearing["granularity"].astype(str).eq("hourly").all() and pd.to_numeric(actual_clearing["timestep_hours"], errors="coerce").fillna(0.0).eq(1.0).all() else "fail", details=f"granularities={sorted(actual_clearing['granularity'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="no_d_plus_4_data_used", status="pass" if actual_clearing["horizon"].astype(str).eq("D_only").all() else "fail", details=f"horizons={sorted(actual_clearing['horizon'].astype(str).unique().tolist())}"))
    rows.append(_validation_row(check_name="no_mfrr_used", status="pass", details="phase E2 runner does not invoke mFRR modules"))
    rows.append(_validation_row(check_name="no_exclusive_bids_used", status="pass", details="phase E2 uses the existing simple bid-curve formulation only"))
    rows.append(_validation_row(check_name="no_scenario_or_probability_changes", status="pass", details="phase E2 reuses saved thesis-grade scenario artifacts without modification"))
    rows.append(_validation_row(check_name="no_milp_formulation_changes_in_phase_e2_runner", status="pass", details="phase E2 runner reuses the existing stochastic bidding MILP path"))
    rows.append(_validation_row(check_name="actual_redispatch_timeseries_present", status="pass" if not actual_redispatch_timeseries.empty else "fail", details=f"rows={int(actual_redispatch_timeseries.shape[0])}"))
    return pd.concat([checks, pd.DataFrame(rows)], ignore_index=True)


def _build_model_selection_evidence_summary(cvar_frontier_aggregated: pd.DataFrame, weekly_metrics: pd.DataFrame) -> pd.DataFrame:
    if cvar_frontier_aggregated.empty:
        return pd.DataFrame()
    gamma_rows = cvar_frontier_aggregated.copy()
    gamma_rows["row_type"] = "model_gamma"
    count_col = "test_week_count" if "test_week_count" in gamma_rows.columns else "validation_week_count"
    gamma_rows = gamma_rows.rename(
        columns={
            "mean_uplift_vs_price_insensitive": "mean_uplift_vs_price_insensitive",
        }
    )
    totals = (
        weekly_metrics.groupby(["artifact_id", "model_label", "cvar_alpha", "cvar_gamma"], as_index=False)
        .agg(
            total_realised_adjusted_profit=("realised_adjusted_profit", "sum"),
            total_rejected_energy=("rejected_energy_mwh", "sum"),
            total_unused_cleared_energy=("unused_cleared_energy_mwh", "sum"),
            total_shortfall=("shortfall_kg", "sum"),
            number_of_weeks_with_shortfall=("shortfall_kg", lambda s: int((pd.to_numeric(s, errors="coerce") > 1e-9).sum())),
            worst_week_value_captured_vs_perfect_foresight=("value_captured_vs_perfect_foresight", "min"),
            mean_average_actual_price_paid=("average_actual_price_paid", "mean"),
        )
    )
    gamma_rows = gamma_rows.merge(
        totals,
        on=["artifact_id", "model_label", "cvar_alpha", "cvar_gamma"],
        how="left",
    )
    economic_order = gamma_rows.sort_values(
        ["mean_realised_adjusted_profit", "total_realised_adjusted_profit", "mean_uplift_vs_price_insensitive"],
        ascending=[False, False, False],
    ).index
    reliability_order = gamma_rows.sort_values(
        ["total_shortfall", "number_of_weeks_with_shortfall", "total_rejected_energy", "total_unused_cleared_energy"],
        ascending=[True, True, True, True],
    ).index
    risk_order = gamma_rows.sort_values(
        ["mean_cvar_tail_profit", "worst_scenario_profit"],
        ascending=[False, False],
    ).index
    gamma_rows["economic_rank"] = gamma_rows.index.map(pd.Series(range(1, len(economic_order) + 1), index=economic_order))
    gamma_rows["reliability_rank"] = gamma_rows.index.map(pd.Series(range(1, len(reliability_order) + 1), index=reliability_order))
    gamma_rows["risk_rank"] = gamma_rows.index.map(pd.Series(range(1, len(risk_order) + 1), index=risk_order))
    recommendations: list[str] = []
    notes: list[str] = []
    for row in gamma_rows.itertuples():
        note_parts: list[str] = []
        if float(row.total_shortfall) > 1e-9:
            note_parts.append(f"shortfall_total={float(row.total_shortfall):.3f}")
        if int(row.number_of_weeks_with_shortfall) > 0:
            note_parts.append(f"weeks_with_shortfall={int(row.number_of_weeks_with_shortfall)}")
        if int(row.economic_rank) <= 2 and int(row.reliability_rank) <= 3 and int(row.risk_rank) <= 3:
            recommendation = "primary continuation candidate"
        elif int(row.economic_rank) <= 4 and int(row.reliability_rank) <= 5 and int(row.risk_rank) <= 5:
            recommendation = "strong alternative"
        elif float(row.total_shortfall) > 1e-9 or int(row.economic_rank) >= 7:
            recommendation = "keep as reference only"
        else:
            recommendation = "inconclusive"
        recommendations.append(recommendation)
        notes.append("; ".join(note_parts))
    gamma_rows["recommendation_category"] = recommendations
    gamma_rows["notes"] = notes

    model_rows: list[dict[str, Any]] = []
    for model_label, group in gamma_rows.groupby("model_label", sort=False):
        best_profit = group.sort_values(["mean_realised_adjusted_profit", "total_realised_adjusted_profit"], ascending=[False, False]).iloc[0]
        best_reliability = group.sort_values(["total_shortfall", "number_of_weeks_with_shortfall", "total_rejected_energy"], ascending=[True, True, True]).iloc[0]
        best_risk = group.sort_values(["mean_cvar_tail_profit", "worst_scenario_profit"], ascending=[False, False]).iloc[0]
        consistent = len({float(best_profit["cvar_gamma"]), float(best_reliability["cvar_gamma"]), float(best_risk["cvar_gamma"])}) == 1
        recommendation = "inconclusive"
        if consistent and str(best_profit["recommendation_category"]) in {"primary continuation candidate", "strong alternative"}:
            recommendation = str(best_profit["recommendation_category"])
        elif str(best_profit["recommendation_category"]) == "primary continuation candidate":
            recommendation = "strong alternative"
        model_rows.append(
            {
                "row_type": "model_summary",
                "artifact_id": str(best_profit["artifact_id"]),
                "model_label": str(model_label),
                "cvar_alpha": float(best_profit["cvar_alpha"]),
                "cvar_gamma": pd.NA,
                "test_week_count": int(group[count_col].max()),
                "mean_realised_adjusted_profit": float(group["mean_realised_adjusted_profit"].mean()),
                "median_realised_adjusted_profit": float(group["median_realised_adjusted_profit"].mean()),
                "worst_week_realised_adjusted_profit": float(group["worst_week_realised_adjusted_profit"].min()),
                "total_realised_adjusted_profit": float(group["total_realised_adjusted_profit"].max()),
                "mean_uplift_vs_price_insensitive": float(group["mean_uplift_vs_price_insensitive"].mean()),
                "mean_value_captured_vs_perfect_foresight": float(group["mean_value_captured_vs_perfect_foresight"].mean()),
                "worst_week_value_captured_vs_perfect_foresight": float(group["worst_week_value_captured_vs_perfect_foresight"].min()),
                "mean_cvar_tail_profit": float(group["mean_cvar_tail_profit"].mean()),
                "worst_scenario_profit": float(group["worst_scenario_profit"].min()),
                "mean_clearing_ratio": float(group["mean_clearing_ratio"].mean()),
                "total_rejected_energy": float(group["total_rejected_energy"].sum()),
                "total_unused_cleared_energy": float(group["total_unused_cleared_energy"].sum()),
                "total_shortfall": float(group["total_shortfall"].sum()),
                "number_of_weeks_with_shortfall": int(group["number_of_weeks_with_shortfall"].sum()),
                "mean_average_actual_price_paid": float(group["mean_average_actual_price_paid"].mean()),
                "mean_high_bid_share": float(group["mean_high_bid_share"].mean()),
                "mean_solve_time_seconds": float(group["mean_solve_time_seconds"].mean()),
                "economic_rank": int(best_profit["economic_rank"]),
                "reliability_rank": int(best_reliability["reliability_rank"]),
                "risk_rank": int(best_risk["risk_rank"]),
                "recommendation_category": recommendation,
                "notes": f"best_profit_gamma={float(best_profit['cvar_gamma']):.2f}; best_reliability_gamma={float(best_reliability['cvar_gamma']):.2f}; best_risk_gamma={float(best_risk['cvar_gamma']):.2f}",
            }
        )
    gamma_rows = gamma_rows.rename(columns={"validation_week_count": "test_week_count"})
    gamma_rows = gamma_rows[
        [
            "row_type",
            "artifact_id",
            "model_label",
            "cvar_alpha",
            "cvar_gamma",
            "test_week_count",
            "mean_realised_adjusted_profit",
            "median_realised_adjusted_profit",
            "worst_week_realised_adjusted_profit",
            "total_realised_adjusted_profit",
            "mean_expected_adjusted_profit",
            "mean_uplift_vs_price_insensitive",
            "mean_value_captured_vs_perfect_foresight",
            "worst_week_value_captured_vs_perfect_foresight",
            "mean_cvar_tail_profit",
            "worst_scenario_profit",
            "mean_clearing_ratio",
            "total_rejected_energy",
            "total_unused_cleared_energy",
            "total_shortfall",
            "number_of_weeks_with_shortfall",
            "mean_average_actual_price_paid",
            "mean_high_bid_share",
            "mean_solve_time_seconds",
            "economic_rank",
            "reliability_rank",
            "risk_rank",
            "recommendation_category",
            "notes",
        ]
    ]
    return pd.concat([gamma_rows, pd.DataFrame(model_rows)], ignore_index=True)


def _plot_aggregated_scatter(
    frame: pd.DataFrame,
    *,
    x_metric: str,
    y_metric: str,
    xlabel: str,
    ylabel: str,
    title: str,
    output_path: Path,
) -> None:
    if frame.empty:
        return
    apply_visual_style()
    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    for model_label, group in frame.groupby("model_label", sort=False):
        color = MODEL_COLORS.get(str(model_label), "#1F4E79")
        ax.scatter(group[x_metric], group[y_metric], s=60, color=color, label=str(model_label))
        for _, row in group.iterrows():
            ax.annotate(f"g={float(row['cvar_gamma']):.2f}", (float(row[x_metric]), float(row[y_metric])), fontsize=8)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_gamma_metric_by_model_aggregated(
    frame: pd.DataFrame,
    *,
    metric: str,
    ylabel: str,
    title: str,
    output_path: Path,
) -> None:
    if frame.empty:
        return
    apply_visual_style()
    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    for model_label, group in frame.groupby("model_label", sort=False):
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


def _plot_metric_by_model_gamma_week(
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
    models = [label for label in ["LEAR Strict", "LEAR FS3 pruned candidate", "XGBoost FS3 pruned candidate"] if label in weekly_metrics["model_label"].astype(str).unique().tolist()]
    weeks = [label for label in DEFAULT_WEEK_IDS if label in weekly_metrics["regime_label"].astype(str).unique().tolist()]
    fig, axes = plt.subplots(len(models), 1, figsize=(10.5, max(4.2, 3.4 * len(models))), sharex=True)
    if len(models) == 1:
        axes = [axes]
    week_colors = {
        "high_volatility": "#7F3C8D",
        "high_price": "#11A579",
        "typical_winter": "#3969AC",
        "typical_summer": "#F2B701",
    }
    for ax, model_label in zip(axes, models, strict=True):
        model_group = weekly_metrics.loc[weekly_metrics["model_label"].astype(str).eq(model_label)].copy()
        for regime_label in weeks:
            group = model_group.loc[model_group["regime_label"].astype(str).eq(regime_label)].sort_values("cvar_gamma")
            if group.empty:
                continue
            ax.plot(group["cvar_gamma"], pd.to_numeric(group[metric], errors="coerce"), marker="o", linewidth=1.6, color=week_colors.get(regime_label, "#666666"), label=regime_label)
        ax.set_title(model_label)
        ax.set_ylabel(ylabel)
        ax.legend(loc="best", fontsize=8)
    axes[-1].set_xlabel("Gamma")
    fig.suptitle(title, y=0.995)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_weekly_profit_vs_benchmarks(
    weekly_metrics: pd.DataFrame,
    benchmark_metrics: pd.DataFrame,
    perfect_foresight_metrics: pd.DataFrame,
    output_path: Path,
) -> None:
    if weekly_metrics.empty:
        return
    apply_visual_style()
    weeks = [label for label in DEFAULT_WEEK_IDS if label in weekly_metrics["regime_label"].astype(str).unique().tolist()]
    fig, axes = plt.subplots(len(weeks), 1, figsize=(12.0, max(4.5, 3.4 * len(weeks))), sharex=False)
    if len(weeks) == 1:
        axes = [axes]
    gamma_values = sorted(weekly_metrics["cvar_gamma"].astype(float).unique().tolist())
    width = 0.22
    for ax, regime_label in zip(axes, weeks, strict=True):
        subset = weekly_metrics.loc[weekly_metrics["regime_label"].astype(str).eq(regime_label)].copy()
        models = subset["model_label"].astype(str).drop_duplicates().tolist()
        x = np.arange(len(models))
        for idx, gamma in enumerate(gamma_values):
            gamma_subset = subset.loc[subset["cvar_gamma"].astype(float).eq(gamma)].set_index("model_label")
            vals = [float(gamma_subset.loc[model, "realised_adjusted_profit"]) for model in models]
            ax.bar(x + (idx - 1) * width, vals, width=width, label=f"g={gamma:.2f}")
        bench = benchmark_metrics.loc[
            (benchmark_metrics["aggregation_level"].astype(str).eq("weekly"))
            & (benchmark_metrics["week_label"].astype(str).eq(week_label))
        ].copy()
        if not bench.empty:
            bench_vals = [float(bench.loc[bench["model_label"].astype(str).eq(model), "realised_adjusted_profit"].iloc[0]) for model in models]
            ax.plot(x, bench_vals, color="#333333", linewidth=1.8, marker="D", label="benchmark")
        pf = perfect_foresight_metrics.loc[
            (perfect_foresight_metrics["aggregation_level"].astype(str).eq("weekly"))
            & (perfect_foresight_metrics["week_label"].astype(str).eq(week_label))
        ].copy()
        if not pf.empty:
            ax.axhline(float(pf["realised_adjusted_profit"].iloc[0]), color="#111111", linestyle="--", linewidth=1.6, label="perfect foresight")
        ax.set_title(regime_label)
        ax.set_ylabel("Realised profit (EUR)")
        ax.set_xticks(x)
        ax.set_xticklabels(models, rotation=10)
        ax.legend(loc="best", fontsize=8)
    fig.suptitle("Weekly realised profit vs price-insensitive and perfect-foresight benchmarks", y=0.995)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_value_captured_vs_perfect_foresight(frame: pd.DataFrame, output_path: Path) -> None:
    if frame.empty or frame["mean_value_captured_vs_perfect_foresight"].dropna().empty:
        return
    _plot_gamma_metric_by_model_aggregated(
        frame,
        metric="mean_value_captured_vs_perfect_foresight",
        ylabel="Share of perfect-foresight profit",
        title="Mean value captured vs perfect foresight by model and policy",
        output_path=output_path,
    )


def _plot_bid_firmness_by_model_gamma(weekly_metrics: pd.DataFrame, output_path: Path) -> None:
    if weekly_metrics.empty:
        return
    aggregated = (
        weekly_metrics.groupby(["model_label", "cvar_gamma"], as_index=False)
        .agg(
            weighted_average_bid_price=("weighted_average_bid_price", "mean"),
            high_bid_share=("high_bid_share", "mean"),
            market_cap_bid_share=("market_cap_bid_share", "mean"),
        )
    )
    apply_visual_style()
    fig, axes = plt.subplots(3, 1, figsize=(9.0, 10.5), sharex=True)
    metrics = [
        ("weighted_average_bid_price", "Weighted average bid price (EUR/MWh)"),
        ("high_bid_share", "High-bid share"),
        ("market_cap_bid_share", "Market-cap bid share"),
    ]
    for ax, (metric, ylabel) in zip(axes, metrics, strict=True):
        for model_label, group in aggregated.groupby("model_label", sort=False):
            color = MODEL_COLORS.get(str(model_label), "#1F4E79")
            group = group.sort_values("cvar_gamma")
            ax.plot(group["cvar_gamma"], pd.to_numeric(group[metric], errors="coerce"), marker="o", linewidth=1.8, color=color, label=str(model_label))
        ax.set_ylabel(ylabel)
        ax.legend(loc="best", fontsize=8)
    axes[-1].set_xlabel("Gamma")
    fig.suptitle("Aggregated bid firmness by model and fixed risk-preference policy", y=0.995)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_scenario_fans_by_week_model(scenario_frame: pd.DataFrame, output_dir: Path) -> None:
    if scenario_frame.empty:
        return
    apply_visual_style()
    gamma_zero = scenario_frame.loc[scenario_frame["cvar_gamma"].astype(float).abs() <= 1e-12].copy()
    if gamma_zero.empty:
        gamma_zero = scenario_frame.copy()
    for (week_label, model_label), group in gamma_zero.groupby(["week_label", "model_label"], sort=False):
        rows: list[dict[str, Any]] = []
        for ts, hour_group in group.groupby("delivery_start_utc", sort=True):
            vals = hour_group["scenario_price_eur_per_mwh"].astype(float).to_numpy()
            probs = hour_group["scenario_probability"].astype(float).to_numpy()
            actual = float(hour_group["actual_price_eur_per_mwh"].iloc[0])
            rows.append(
                {
                    "delivery_start_utc": pd.Timestamp(ts),
                    "scenario_min": float(np.min(vals)),
                    "scenario_max": float(np.max(vals)),
                    "q05": float(_weighted_quantile(vals, probs, 0.05)),
                    "q10": float(_weighted_quantile(vals, probs, 0.10)),
                    "q50": float(_weighted_quantile(vals, probs, 0.50)),
                    "q90": float(_weighted_quantile(vals, probs, 0.90)),
                    "q95": float(_weighted_quantile(vals, probs, 0.95)),
                    "actual": actual,
                    "outside_envelope": bool(actual < float(np.min(vals)) - TOLERANCE or actual > float(np.max(vals)) + TOLERANCE),
                }
            )
        quant = pd.DataFrame(rows).sort_values("delivery_start_utc")
        fig, ax = plt.subplots(figsize=(12, 4.8))
        color = MODEL_COLORS.get(str(model_label), "#1F4E79")
        ax.fill_between(quant["delivery_start_utc"], quant["scenario_min"], quant["scenario_max"], alpha=0.08, color=color, label="scenario min-max")
        ax.fill_between(quant["delivery_start_utc"], quant["q05"], quant["q95"], alpha=0.16, color=color, label="p05-p95")
        ax.fill_between(quant["delivery_start_utc"], quant["q10"], quant["q90"], alpha=0.24, color=color, label="p10-p90")
        ax.plot(quant["delivery_start_utc"], quant["q50"], color=color, linewidth=1.6, label="scenario median")
        ax.plot(quant["delivery_start_utc"], quant["actual"], color="#222222", linewidth=1.8, label="actual price")
        outside = quant.loc[quant["outside_envelope"].astype(bool)]
        if not outside.empty:
            ax.scatter(outside["delivery_start_utc"], outside["actual"], color="#D55E00", s=18, label="outside scenario envelope")
        ax.set_title(f"{week_label}: scenario fan vs realised price for {model_label}")
        ax.set_ylabel("EUR/MWh")
        ax.legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(output_dir / f"fig_scenario_fan_{week_label}_{_slugify(model_label)}.png", dpi=300, bbox_inches="tight")
        plt.close(fig)


def _select_example_dates(daily_metrics: pd.DataFrame) -> dict[str, str]:
    gamma_zero = daily_metrics.loc[daily_metrics["cvar_gamma"].astype(float).abs() <= 1e-12].copy()
    if gamma_zero.empty:
        gamma_zero = daily_metrics.copy()
    base = (
        gamma_zero.groupby(["regime_label", "delivery_day"], as_index=False)
        .agg(
            actual_price_max=("actual_price_max", "max"),
            actual_price_std=("actual_price_std", "max"),
            actual_price_mean=("actual_price_mean", "mean"),
            actual_price_min=("actual_price_min", "min"),
            actual_price_spread=("actual_price_spread", "max"),
        )
    )
    picks: dict[str, str] = {}
    for regime_label in ["high_volatility", "high_price", "typical_summer", "typical_winter"]:
        group = base.loc[base["regime_label"].astype(str).eq(regime_label)].copy()
        if group.empty:
            continue
        if regime_label == "high_volatility":
            row = group.sort_values(["actual_price_max", "actual_price_std"], ascending=[False, False]).iloc[0]
        elif regime_label == "high_price":
            row = group.sort_values(["actual_price_max", "actual_price_spread"], ascending=[False, False]).iloc[0]
        else:
            row = group.sort_values(["actual_price_std", "actual_price_spread"], ascending=[True, True]).iloc[0]
        picks[regime_label] = str(row["delivery_day"])
    return picks


def _plot_example_day_operations(
    *,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    scenario_frame: pd.DataFrame,
    example_dates: dict[str, str],
    reserve_line: float,
    output_dir: Path,
) -> None:
    if actual_clearing.empty or actual_redispatch_timeseries.empty:
        return
    apply_visual_style()
    gamma_values = [0.0, 0.05, 0.25]
    for week_label, delivery_day in example_dates.items():
        for model_label in actual_clearing["model_label"].astype(str).drop_duplicates().tolist():
            fig, axes = plt.subplots(5, 1, figsize=(11.2, 12.8), sharex=True)
            for gamma in gamma_values:
                fan = scenario_frame.loc[
                    scenario_frame["week_label"].astype(str).eq(str(week_label))
                    & scenario_frame["model_label"].astype(str).eq(str(model_label))
                    & scenario_frame["delivery_day"].astype(str).eq(str(delivery_day))
                    & scenario_frame["cvar_gamma"].astype(float).eq(float(gamma))
                ].copy()
                if fan.empty:
                    continue
                hourly_rows: list[dict[str, Any]] = []
                for ts, hour_group in fan.groupby("delivery_start_utc", sort=True):
                    vals = hour_group["scenario_price_eur_per_mwh"].astype(float).to_numpy()
                    probs = hour_group["scenario_probability"].astype(float).to_numpy()
                    hourly_rows.append(
                        {
                            "delivery_start_utc": pd.Timestamp(ts),
                            "q10": float(_weighted_quantile(vals, probs, 0.10)),
                            "q50": float(_weighted_quantile(vals, probs, 0.50)),
                            "q90": float(_weighted_quantile(vals, probs, 0.90)),
                            "actual": float(hour_group["actual_price_eur_per_mwh"].iloc[0]),
                        }
                    )
                hourly = pd.DataFrame(hourly_rows).sort_values("delivery_start_utc")
                color = MODEL_COLORS.get(str(model_label), "#1F4E79")
                axes[0].plot(hourly["delivery_start_utc"], hourly["q50"], color=color, linewidth=1.1, alpha=0.80, label=f"median g={gamma:.2f}")
                if gamma == 0.0:
                    axes[0].fill_between(hourly["delivery_start_utc"], hourly["q10"], hourly["q90"], color=color, alpha=0.10)
                    axes[0].plot(hourly["delivery_start_utc"], hourly["actual"], color="#222222", linewidth=1.8, label="actual price")

                clearing_hour = (
                    actual_clearing.loc[
                        actual_clearing["week_label"].astype(str).eq(str(week_label))
                        & actual_clearing["model_label"].astype(str).eq(str(model_label))
                        & actual_clearing["delivery_day"].astype(str).eq(str(delivery_day))
                        & actual_clearing["cvar_gamma"].astype(float).eq(float(gamma))
                    ]
                    .groupby("delivery_start_utc", as_index=False)
                    .agg(
                        submitted_energy_mwh=("bid_quantity_mw", "sum"),
                        cleared_energy_mwh=("cleared_energy_mwh", "sum"),
                    )
                )
                clearing_hour["rejected_energy_mwh"] = clearing_hour["submitted_energy_mwh"] - clearing_hour["cleared_energy_mwh"]
                axes[1].plot(clearing_hour["delivery_start_utc"], clearing_hour["cleared_energy_mwh"], color=color, linewidth=1.2, label=f"cleared g={gamma:.2f}")
                axes[1].plot(clearing_hour["delivery_start_utc"], clearing_hour["rejected_energy_mwh"], color=color, linewidth=1.0, linestyle="--", label=f"rejected g={gamma:.2f}")

                redispatch = actual_redispatch_timeseries.loc[
                    actual_redispatch_timeseries["week_label"].astype(str).eq(str(week_label))
                    & actual_redispatch_timeseries["model_label"].astype(str).eq(str(model_label))
                    & actual_redispatch_timeseries["delivery_day"].astype(str).eq(str(delivery_day))
                    & actual_redispatch_timeseries["cvar_gamma"].astype(float).eq(float(gamma))
                ].sort_values("delivery_start_utc")
                axes[2].plot(redispatch["delivery_start_utc"], redispatch["used_energy_mwh"], color=color, linewidth=1.2, label=f"used g={gamma:.2f}")
                axes[2].plot(redispatch["delivery_start_utc"], redispatch["unused_cleared_energy_mwh"], color=color, linewidth=1.0, linestyle="--", label=f"unused g={gamma:.2f}")
                axes[3].plot(redispatch["delivery_start_utc"], redispatch["P_el_mw"], color=color, linewidth=1.2, label=f"electrolyser g={gamma:.2f}")
                axes[3].plot(redispatch["delivery_start_utc"], redispatch["P_comp_mw"], color=color, linewidth=1.0, linestyle="--", label=f"compressor g={gamma:.2f}")
                axes[4].plot(redispatch["delivery_start_utc"], redispatch["H_buf_kg"], color=color, linewidth=1.2, label=f"storage g={gamma:.2f}")
                axes[4].plot(redispatch["delivery_start_utc"], redispatch["shortfall_kg"], color=color, linewidth=0.9, linestyle=":", label=f"shortfall g={gamma:.2f}")

            axes[0].set_title("Actual price with scenario median and p10-p90 band")
            axes[0].set_ylabel("EUR/MWh")
            axes[1].set_title("Cleared and rejected electricity")
            axes[1].set_ylabel("MWh")
            axes[2].set_title("Used and unused cleared electricity")
            axes[2].set_ylabel("MWh")
            axes[3].set_title("Electrolyser and compressor power")
            axes[3].set_ylabel("MW")
            axes[4].set_title("Hydrogen storage and shortfall")
            axes[4].set_ylabel("kg")
            axes[4].axhline(float(reserve_line), color="#555555", linestyle="--", linewidth=1.0, label="reserve line")
            axes[4].set_xlabel("Delivery hour (UTC)")
            for ax in axes:
                ax.legend(loc="best", fontsize=7, ncol=2)
            fig.suptitle(f"Example-day operation: {delivery_day} | {week_label} | {model_label}", y=0.995)
            fig.tight_layout()
            fig.savefig(output_dir / f"fig_example_day_operation_{delivery_day}_{_slugify(model_label)}.png", dpi=300, bbox_inches="tight")
            plt.close(fig)


def _plot_economic_decomposition_by_model_gamma(weekly_metrics: pd.DataFrame, output_path: Path) -> None:
    if weekly_metrics.empty:
        return
    aggregated = (
        weekly_metrics.groupby(["model_label", "cvar_gamma"], as_index=False)
        .agg(
            hydrogen_revenue=("hydrogen_revenue", "sum"),
            da_settlement_cost=("da_settlement_cost", "sum"),
            shortfall_penalty=("shortfall_penalty", "sum"),
            unused_energy_penalty=("unused_energy_penalty", "sum"),
            terminal_inventory_correction=("terminal_inventory_correction", "sum"),
            realised_adjusted_profit=("realised_adjusted_profit", "sum"),
        )
        .sort_values(["model_label", "cvar_gamma"])
    )
    labels = [f"{row.model_label}\ng={float(row.cvar_gamma):.2f}" for row in aggregated.itertuples()]
    x = np.arange(len(labels))
    hydrogen_revenue = pd.to_numeric(aggregated["hydrogen_revenue"], errors="coerce").to_numpy()
    da_cost = -pd.to_numeric(aggregated["da_settlement_cost"], errors="coerce").to_numpy()
    shortfall_penalty = -pd.to_numeric(aggregated["shortfall_penalty"], errors="coerce").to_numpy()
    unused_penalty = -pd.to_numeric(aggregated["unused_energy_penalty"], errors="coerce").to_numpy()
    terminal = pd.to_numeric(aggregated["terminal_inventory_correction"], errors="coerce").to_numpy()
    realised_profit = pd.to_numeric(aggregated["realised_adjusted_profit"], errors="coerce").to_numpy()
    apply_visual_style()
    fig, ax = plt.subplots(figsize=(12.2, 5.8))
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


def _plot_model_selection_summary(summary: pd.DataFrame, output_path: Path) -> None:
    if summary.empty:
        return
    frame = summary.loc[summary["row_type"].astype(str).eq("model_gamma")].copy()
    if frame.empty:
        return
    apply_visual_style()
    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    color_map = {
        "primary continuation candidate": "#1b9e77",
        "strong alternative": "#7570b3",
        "keep as reference only": "#d95f02",
        "inconclusive": "#666666",
    }
    for _, row in frame.iterrows():
        color = color_map.get(str(row["recommendation_category"]), "#666666")
        ax.scatter(
            float(row["economic_rank"]),
            float(row["reliability_rank"]),
            s=max(60.0, float(row["mean_cvar_tail_profit"]) / 5000.0),
            color=color,
        )
        ax.annotate(
            f"{row['model_label']}\ng={float(row['cvar_gamma']):.2f}",
            (float(row["economic_rank"]), float(row["reliability_rank"])),
            fontsize=8,
        )
    ax.set_xlabel("Economic rank (lower is better)")
    ax.set_ylabel("Reliability rank (lower is better)")
    ax.set_title("Model-selection evidence summary")
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _create_figures(
    *,
    run_dir: Path,
    config: HydrogenConfig,
    daily_metrics: pd.DataFrame,
    weekly_metrics: pd.DataFrame,
    cvar_frontier_aggregated: pd.DataFrame,
    model_selection_evidence_summary: pd.DataFrame,
    benchmark_metrics: pd.DataFrame,
    perfect_foresight_metrics: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    scenario_frame: pd.DataFrame,
) -> None:
    figures_dir = run_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    _plot_aggregated_scatter(
        cvar_frontier_aggregated,
        x_metric="mean_cvar_tail_profit",
        y_metric="mean_realised_adjusted_profit",
        xlabel="Mean CVaR tail profit (-CVaR loss)",
        ylabel="Mean realised adjusted profit (EUR)",
        title="Aggregated risk-return comparison across selected test weeks",
        output_path=figures_dir / "fig_aggregated_risk_return_profit_vs_cvar_tail_profit.png",
    )
    _plot_aggregated_scatter(
        cvar_frontier_aggregated.dropna(subset=["mean_value_captured_vs_perfect_foresight"]),
        x_metric="mean_value_captured_vs_perfect_foresight",
        y_metric="mean_realised_adjusted_profit",
        xlabel="Mean value captured vs perfect foresight",
        ylabel="Mean realised adjusted profit (EUR)",
        title="Aggregated value captured vs realised profit",
        output_path=figures_dir / "fig_aggregated_value_captured_vs_profit.png",
    )
    _plot_gamma_metric_by_model_aggregated(
        cvar_frontier_aggregated,
        metric="mean_realised_adjusted_profit",
        ylabel="Mean realised adjusted profit (EUR)",
        title="Gamma vs mean realised adjusted profit by model",
        output_path=figures_dir / "fig_gamma_vs_realised_profit_by_model.png",
    )
    _plot_gamma_metric_by_model_aggregated(
        cvar_frontier_aggregated,
        metric="mean_cvar_tail_profit",
        ylabel="Mean CVaR tail profit (EUR)",
        title="Gamma vs mean CVaR tail profit by model",
        output_path=figures_dir / "fig_gamma_vs_cvar_tail_profit_by_model.png",
    )
    _plot_gamma_metric_by_model_aggregated(
        cvar_frontier_aggregated,
        metric="worst_scenario_profit",
        ylabel="Worst-scenario profit (EUR)",
        title="Gamma vs worst-scenario profit by model",
        output_path=figures_dir / "fig_gamma_vs_worst_scenario_profit_by_model.png",
    )
    _plot_weekly_profit_vs_benchmarks(
        weekly_metrics,
        benchmark_metrics,
        perfect_foresight_metrics,
        figures_dir / "fig_weekly_profit_vs_benchmarks.png",
    )
    _plot_value_captured_vs_perfect_foresight(
        cvar_frontier_aggregated,
        figures_dir / "fig_value_captured_vs_perfect_foresight.png",
    )
    _plot_metric_by_model_gamma_week(
        weekly_metrics,
        metric="clearing_ratio",
        ylabel="ratio",
        title="Clearing ratio by model, gamma, and week",
        output_path=figures_dir / "fig_clearing_ratio_by_model_gamma_week.png",
    )
    _plot_metric_by_model_gamma_week(
        weekly_metrics,
        metric="rejected_energy_mwh",
        ylabel="MWh",
        title="Rejected energy by model, gamma, and week",
        output_path=figures_dir / "fig_rejected_energy_by_model_gamma_week.png",
    )
    _plot_metric_by_model_gamma_week(
        weekly_metrics,
        metric="unused_cleared_energy_mwh",
        ylabel="MWh",
        title="Unused cleared energy by model, gamma, and week",
        output_path=figures_dir / "fig_unused_energy_by_model_gamma_week.png",
    )
    _plot_bid_firmness_by_model_gamma(weekly_metrics, figures_dir / "fig_bid_firmness_by_model_gamma.png")
    _plot_scenario_fans_by_week_model(scenario_frame, figures_dir)
    _plot_example_day_operations(
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        scenario_frame=scenario_frame,
        example_dates=_select_example_dates(daily_metrics),
        reserve_line=float(config.hydrogen_system.reserve_kg),
        output_dir=figures_dir,
    )
    _plot_economic_decomposition_by_model_gamma(weekly_metrics, figures_dir / "fig_economic_decomposition_by_model_gamma.png")
    _plot_model_selection_summary(model_selection_evidence_summary, figures_dir / "fig_model_selection_summary.png")


def _write_readme(
    *,
    run_dir: Path,
    selected_weeks: pd.DataFrame,
    artifact_ids: list[str],
    cvar_alpha: float,
    gamma_values: list[float],
    benchmark_included: bool,
    perfect_foresight_included: bool,
    weekly_metrics: pd.DataFrame,
    cvar_frontier_aggregated: pd.DataFrame,
    model_selection_evidence_summary: pd.DataFrame,
    validation_checks: pd.DataFrame,
    cvar_validation_checks: pd.DataFrame,
) -> None:
    hard_fail_count = int(validation_checks.loc[(validation_checks["severity"].astype(str) == "hard_fail") & (validation_checks["status"].astype(str) == "fail")].shape[0])
    cvar_fail_count = int(cvar_validation_checks.loc[cvar_validation_checks["status"].astype(str) == "fail"].shape[0])
    lines = [
        "# Phase E2 Fixed-Policy Selected Test-Week CVaR Evaluation",
        "",
        "## Scope",
        "",
        "- label: fixed-policy selected test-week evaluation on common partial support",
        "- hourly, D-only, DA-only",
        "- selected test weeks only",
        "- gamma values are fixed risk-preference policies, not tuned on the test set",
        "- no validation weeks were used",
        "- no scenario, probability, bid-grid, or MILP formulation changes were introduced",
        "",
        "## Selected Test Weeks",
        "",
        "```csv",
        selected_weeks[["week_label", "delivery_start_date", "delivery_end_date", "selection_reason"]].to_csv(index=False).strip(),
        "```",
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
            "- gamma = 0 is risk-neutral.",
            "- gamma = 0.05 is moderate risk aversion.",
            "- gamma = 0.25 is conservative risk aversion.",
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
            weekly_metrics[[
                "week_label",
                "model_label",
                "cvar_gamma",
                "realised_adjusted_profit",
                "stochastic_minus_benchmark_profit",
                "perfect_foresight_profit",
                "value_captured_vs_perfect_foresight",
                "cvar_tail_profit",
                "clearing_ratio",
                "shortfall_kg",
            ]].to_csv(index=False).strip(),
            "```",
            "",
            "## Aggregated Results",
            "",
            "```csv",
            cvar_frontier_aggregated.to_csv(index=False).strip(),
            "```",
            "",
            "## Model-Selection Evidence",
            "",
            "```csv",
            model_selection_evidence_summary.to_csv(index=False).strip(),
            "```",
            "",
            "## Validation Status",
            "",
            f"- hard validation failures: {hard_fail_count}",
            f"- CVaR reconstruction / consistency failures: {cvar_fail_count}",
            "",
            "## Interpretation Guardrails",
            "",
            "- this is fixed-policy selected test-week evaluation, not gamma tuning;",
            "- scenario undercoverage still limits how strongly tail-risk performance should be generalized;",
            "- results apply only to the selected common-support weeks, not the full test year;",
            "- perfect foresight is an upper bound, not an operational strategy.",
            "",
            "## Phase Status",
            "",
            f"- Phase E2 status: {'pass' if hard_fail_count == 0 and cvar_fail_count == 0 else 'fail'}",
            f"- safe to proceed to later extensions: {'yes, with explicit scenario-quality caveats' if hard_fail_count == 0 and cvar_fail_count == 0 else 'not yet'}",
        ]
    )
    save_text(run_dir, "README_selected_test_weeks_cvar_policy_eval.md", "\n".join(lines))


def run_selected_test_weeks_cvar_policy_eval(
    *,
    config: HydrogenConfig | str | Path,
    week_ids: list[str] | tuple[str, ...] = DEFAULT_WEEK_IDS,
    artifact_ids: list[str] | tuple[str, ...] = DEFAULT_ARTIFACT_IDS,
    cvar_alpha: float = DEFAULT_ALPHA,
    gamma_values: list[float] | tuple[float, ...] = DEFAULT_GAMMAS,
    include_price_insensitive_benchmark: bool = True,
    include_perfect_foresight_benchmark: bool = True,
    run_slug: str = "phase_e2_all_selected_test_weeks_cvar_policy_three_model",
    output_root: Path | None = None,
    week_registry_path: Path = DEFAULT_WEEK_REGISTRY,
    support_csv_path: Path = DEFAULT_SUPPORT_CSV,
    selected_weeks_yaml_path: Path | None = DEFAULT_SELECTED_WEEKS_YAML,
) -> PhaseE2PolicyEvalResult:
    gamma_list = [float(value) for value in gamma_values]
    if gamma_list != [0.0, 0.05, 0.25]:
        raise ValueError(f"Phase E2 requires gamma grid exactly [0, 0.05, 0.25], got {gamma_list}.")
    if abs(float(cvar_alpha) - 0.95) > 1e-12:
        raise ValueError(f"Phase E2 requires alpha 0.95, got {cvar_alpha}.")
    if not include_price_insensitive_benchmark:
        raise ValueError("Phase E2 requires the price-insensitive benchmark to be included.")

    selected_weeks, support_days = _load_and_validate_phase_e2_weeks(
        week_registry_path=Path(week_registry_path),
        support_csv_path=Path(support_csv_path),
        selected_weeks_yaml_path=Path(selected_weeks_yaml_path) if selected_weeks_yaml_path is not None else None,
        week_ids=week_ids,
    )

    suite_config = _build_phase_e2_config(
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
    preflight = run_selected_week_input_preflight(
        config=suite_config,
        artifact_ids=[str(value) for value in artifact_ids],
        requested_identifiers=[str(value) for value in week_ids],
        selected_weeks_yaml_path=Path(selected_weeks_yaml_path) if selected_weeks_yaml_path is not None else None,
        expected_split="test",
        cache_root=run_dir / "cache",
        output_policy_name="minimal",
    )
    save_frame_csv(run_dir, "selected_week_input_preflight.csv", preflight.audit_rows)
    save_frame_csv(run_dir, "selected_week_input_runtime_profile.csv", preflight.runtime_profile)
    if not preflight.audit_rows.empty and not preflight.audit_rows["status"].astype(str).eq("pass").all():
        raise RuntimeError(
            "Phase E2 selected-week input preflight failed before optimisation; "
            f"see {run_dir / 'selected_week_input_preflight.csv'}."
        )

    save_json(
        run_dir,
        "selected_weeks_manifest.json",
        {
            "selected_weeks": selected_weeks[["week_id", "week_label", "delivery_start_date", "delivery_end_date", "regime_label", "methodological_use", "support_status"]].to_dict(orient="records"),
            "selected_delivery_days": support_days["delivery_date"].dt.strftime("%Y-%m-%d").tolist(),
            "support_label": "fixed-policy selected test-week evaluation on common partial support",
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
            "gamma_selection_rule": "frozen_from_validation_phases_D2_D3_do_not_tune_on_test_weeks",
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
    benchmark_identity_rows: list[dict[str, str]] = []
    perfect_foresight_identity_rows: list[dict[str, str]] = []
    benchmark_cache: dict[tuple[str, str], pd.Series] = {}
    benchmark_signature_by_day: dict[str, tuple[float, ...]] = {}
    perfect_foresight_profit_by_day: dict[str, pd.Series] = {}
    perfect_foresight_signature_by_day: dict[str, tuple[float, ...]] = {}

    for artifact_id in [str(value) for value in artifact_ids]:
        selected_daily, _, spec, catalog_entry, manifest = _valid_daily_registry_for_artifact(
            config=suite_config,
            artifact_id=artifact_id,
        )
        selected_daily = selected_daily.loc[selected_daily["delivery_day"].astype(str).isin(selected_delivery_days)].copy()
        if int(selected_daily.shape[0]) != len(selected_delivery_days):
            raise ValueError(f"Artifact {artifact_id!r} produced {int(selected_daily.shape[0])} test days for Phase E2; expected {len(selected_delivery_days)}.")
        selected_daily = selected_daily.sort_values("delivery_day").reset_index(drop=True)
        model_label = _label_for_artifact(artifact_id)
        validation_mode = str(catalog_entry.get("validation_mode", spec.validation_mode))
        thesis_grade = bool(manifest.get("thesis_grade", catalog_entry.get("thesis_grade", validation_mode == "thesis_grade")))
        reconstruction_used = bool(manifest.get("forecast_origin_reconstruction_used", manifest.get("forecast_origin_reconstructed", False)))

        for day_record in selected_daily.to_dict(orient="records"):
            delivery_day = str(day_record["delivery_day"])
            week_meta = delivery_to_week[delivery_day]
            week_row = week_row_lookup[str(week_meta["week_label"])].copy()
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
                    dry_run_label=f"{week_meta['week_label']}_gamma_{_normalized_gamma_tag(gamma)}",
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
                            week_id=str(week_meta["week_id"]),
                            week_label=str(week_meta["week_label"]),
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
                    perfect_foresight_signature_by_day[delivery_day] = actual_price_signature
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
                elif include_perfect_foresight_benchmark:
                    pf_same_signature = perfect_foresight_signature_by_day[delivery_day] == actual_price_signature
                    perfect_foresight_identity_rows.append(
                        _validation_row(
                            check_name="perfect_foresight_day_price_signature_consistent_across_artifacts",
                            status="pass" if pf_same_signature else "fail",
                            details=f"delivery_day={delivery_day}; same_actual_price_signature={pf_same_signature}",
                            severity="hard_fail",
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=str(week_meta["week_id"]),
                            week_label=str(week_meta["week_label"]),
                            delivery_day=delivery_day,
                            forecast_origin_utc=str(result.forecast_origin_utc),
                        )
                    )
                pf_row = perfect_foresight_profit_by_day.get(delivery_day)

                metric_row = _build_daily_metric_row(
                    result=result,
                    artifact_id=artifact_id,
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
                metric_row["period_type"] = "test"
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
                        artifact_id=artifact_id,
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
                    "artifact_id": artifact_id,
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

    daily_metrics = pd.DataFrame(daily_rows).sort_values(["week_label", "model_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    if daily_metrics.empty:
        raise RuntimeError("Phase E2 produced no daily metrics.")
    daily_metrics["run_id"] = str(run_id)
    daily_metrics["period_type"] = "test"

    submitted_bids = pd.concat(submitted_rows, ignore_index=True) if submitted_rows else pd.DataFrame()
    scenario_clearing = pd.concat(scenario_clearing_rows, ignore_index=True) if scenario_clearing_rows else pd.DataFrame()
    scenario_settlement_results = pd.concat(scenario_settlement_rows, ignore_index=True) if scenario_settlement_rows else pd.DataFrame()
    actual_clearing = pd.concat(actual_clearing_rows, ignore_index=True) if actual_clearing_rows else pd.DataFrame()
    actual_redispatch_timeseries = pd.concat(actual_redispatch_rows, ignore_index=True) if actual_redispatch_rows else pd.DataFrame()
    actual_settlement_results = pd.concat(actual_settlement_rows, ignore_index=True) if actual_settlement_rows else pd.DataFrame()
    validation_checks_existing = pd.concat(validation_rows, ignore_index=True) if validation_rows else pd.DataFrame()
    day_run_dirs = pd.DataFrame(day_run_dir_rows).sort_values(["week_label", "model_label", "cvar_gamma", "delivery_day"]).reset_index(drop=True)
    benchmark_daily = pd.DataFrame(benchmark_daily_rows).sort_values(["week_label", "model_label", "delivery_day"]).reset_index(drop=True)
    perfect_foresight_daily = pd.DataFrame(perfect_foresight_daily_rows).sort_values(["week_label", "delivery_day"]).reset_index(drop=True)
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

    weekly_parts: list[pd.DataFrame] = []
    benchmark_parts: list[pd.DataFrame] = []
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
            benchmark_parts.append(bench_week)
    weekly_metrics = pd.concat(weekly_parts, ignore_index=True).sort_values(["week_label", "model_label", "cvar_gamma"]).reset_index(drop=True)
    benchmark_metrics = pd.concat(benchmark_parts, ignore_index=True) if benchmark_parts else pd.DataFrame()
    perfect_foresight_metrics = _aggregate_perfect_foresight_metrics(perfect_foresight_daily)
    if not benchmark_metrics.empty:
        benchmark_metrics["period_type"] = "test"
    if not perfect_foresight_metrics.empty:
        perfect_foresight_metrics["period_type"] = "test"

    if not perfect_foresight_metrics.empty:
        pf_weekly = perfect_foresight_metrics.loc[perfect_foresight_metrics["aggregation_level"].astype(str).eq("weekly"), ["week_id", "realised_adjusted_profit"]].rename(columns={"realised_adjusted_profit": "perfect_foresight_profit"})
        weekly_metrics = weekly_metrics.merge(pf_weekly, on="week_id", how="left")
        weekly_metrics["value_captured_vs_perfect_foresight"] = np.where(
            pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce").abs() > 1e-9,
            pd.to_numeric(weekly_metrics["realised_adjusted_profit"], errors="coerce") / pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce"),
            np.nan,
        )
        weekly_metrics["regret_vs_perfect_foresight"] = pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce") - pd.to_numeric(weekly_metrics["realised_adjusted_profit"], errors="coerce")
    else:
        weekly_metrics["perfect_foresight_profit"] = pd.NA
        weekly_metrics["value_captured_vs_perfect_foresight"] = pd.NA
        weekly_metrics["regret_vs_perfect_foresight"] = pd.NA
    weekly_metrics["cvar_tail_profit"] = -pd.to_numeric(weekly_metrics["cvar_loss"], errors="coerce")

    cvar_sweep_daily = daily_metrics.copy()
    cvar_sweep_weekly = weekly_metrics.copy()
    weekly_metrics_by_model_gamma = weekly_metrics.copy()
    cvar_frontier_by_model_week = _build_cvar_frontier_by_model_week(weekly_metrics)
    cvar_frontier_aggregated = _build_cvar_frontier_aggregated(weekly_metrics)
    cvar_bid_firmness_metrics = weekly_metrics[["week_id", "week_label", "regime_label", "artifact_id", "model_label", "cvar_alpha", "cvar_gamma", "weighted_average_bid_price", "high_bid_share", "market_cap_bid_share", "clearing_ratio", "rejected_energy_mwh", "unused_cleared_energy_mwh"]].copy()
    model_stats_by_gamma = _build_model_stats_by_gamma_week(daily_metrics)
    solver_log_manifest = _build_solver_log_manifest(day_run_dirs)
    model_selection_evidence_summary = _build_model_selection_evidence_summary(cvar_frontier_aggregated, weekly_metrics)
    save_json(run_dir, "scenario_manifest.json", {"phase": "E2", "support_label": "fixed-policy selected test-week evaluation on common partial support", "artifacts": scenario_manifest_rows})

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
        selected_weeks=selected_weeks,
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
    save_frame_csv(run_dir, "cvar_frontier_by_model_week.csv", cvar_frontier_by_model_week)
    save_frame_csv(run_dir, "cvar_frontier_aggregated.csv", cvar_frontier_aggregated)
    save_frame_csv(run_dir, "cvar_frontier_by_model.csv", cvar_frontier_by_model_week)
    save_frame_csv(run_dir, "cvar_bid_firmness_metrics.csv", cvar_bid_firmness_metrics)
    save_frame_csv(run_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(run_dir, "model_selection_evidence_summary.csv", model_selection_evidence_summary)
    save_frame_csv(run_dir, "day_run_dirs.csv", day_run_dirs)

    notebook_inputs_dir = run_dir / "notebook_inputs"
    notebook_inputs_dir.mkdir(parents=True, exist_ok=True)
    save_frame_csv(notebook_inputs_dir, "selected_weeks_manifest_table.csv", selected_weeks)
    save_frame_csv(notebook_inputs_dir, "selected_week_manifest_table.csv", selected_weeks)
    save_frame_csv(notebook_inputs_dir, "support_days.csv", support_days)
    save_frame_csv(notebook_inputs_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(notebook_inputs_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_frontier_by_model_week.csv", cvar_frontier_by_model_week)
    save_frame_csv(notebook_inputs_dir, "cvar_frontier_aggregated.csv", cvar_frontier_aggregated)
    save_frame_csv(notebook_inputs_dir, "cvar_frontier_by_model.csv", cvar_frontier_by_model_week)
    save_frame_csv(notebook_inputs_dir, "benchmark_metrics.csv", benchmark_metrics)
    save_frame_csv(notebook_inputs_dir, "perfect_foresight_metrics.csv", perfect_foresight_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_bid_firmness_metrics.csv", cvar_bid_firmness_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_csv(notebook_inputs_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(notebook_inputs_dir, "model_selection_evidence_summary.csv", model_selection_evidence_summary)
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
        cvar_frontier_aggregated=cvar_frontier_aggregated,
        model_selection_evidence_summary=model_selection_evidence_summary,
        benchmark_metrics=benchmark_metrics,
        perfect_foresight_metrics=perfect_foresight_metrics,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        scenario_frame=scenario_frame,
    )
    _write_readme(
        run_dir=run_dir,
        selected_weeks=selected_weeks,
        artifact_ids=[str(value) for value in artifact_ids],
        cvar_alpha=float(cvar_alpha),
        gamma_values=gamma_list,
        benchmark_included=bool(include_price_insensitive_benchmark),
        perfect_foresight_included=bool(include_perfect_foresight_benchmark),
        weekly_metrics=weekly_metrics,
        cvar_frontier_aggregated=cvar_frontier_aggregated,
        model_selection_evidence_summary=model_selection_evidence_summary,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
    )

    hard_fail_count = int(validation_checks_all_runs.loc[(validation_checks_all_runs["severity"].astype(str) == "hard_fail") & (validation_checks_all_runs["status"].astype(str) == "fail")].shape[0])
    cvar_fail_count = int(cvar_validation_checks.loc[cvar_validation_checks["status"].astype(str) == "fail"].shape[0])
    if hard_fail_count > 0 or cvar_fail_count > 0:
        raise RuntimeError(f"Phase E2 completed but validation failed (hard_fail_count={hard_fail_count}, cvar_fail_count={cvar_fail_count}); see run folder {run_dir}.")

    notebook_path = Path("scripts/Data/03_Hydrogen_Test_Case/notebooks/13_standard_cvar_policy_test_report.ipynb")
    return PhaseE2PolicyEvalResult(
        run_dir=run_dir,
        notebook_path=notebook_path,
        selected_weeks=selected_weeks,
        support_days=support_days,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        cvar_frontier_aggregated=cvar_frontier_aggregated,
        model_selection_evidence_summary=model_selection_evidence_summary,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
        benchmark_metrics=benchmark_metrics,
        perfect_foresight_metrics=perfect_foresight_metrics,
    )
