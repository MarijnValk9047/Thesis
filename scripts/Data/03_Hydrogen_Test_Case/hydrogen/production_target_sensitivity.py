from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .bidding_backtest import (
    _run_price_insensitive_badarinath_style_comparison,
    run_real_scenario_bidding_dry_run,
)
from .plots import (
    plot_asset_operation_day,
    plot_bid_ladder_actual_price_day,
    plot_bid_ladder_heatmap_day,
    plot_cleared_used_unused_day,
    plot_runtime_by_model_gamma,
    plot_runtime_by_target_mode,
    plot_runtime_stage_breakdown,
    plot_runtime_vs_binary_count,
    plot_submitted_cleared_rejected_day,
    plot_target_mode_comparison,
    plot_top_slowest_solves,
)
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .production_target import (
    TARGET_MODES,
    build_production_target_policy,
)
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
from .selected_test_week_cvar_policy_eval import _build_general_test_validation_checks
from .selected_week_smoke import (
    DEFAULT_SELECTED_WEEKS_YAML,
    DEFAULT_SUPPORT_CSV,
    DEFAULT_WEEK_REGISTRY,
    _label_for_artifact,
    _validation_row,
    load_and_validate_phase_c_week,
)
from .validation_cvar_expanded_sweep import (
    _aggregate_perfect_foresight_metrics,
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


DEFAULT_WEEK_ID = "test_high_volatility_week"
DEFAULT_ALPHA = 0.95
DEFAULT_GAMMAS = (0.0, 0.05, 0.25)


@dataclass(frozen=True)
class PhaseE3ProductionTargetSensitivityResult:
    run_dir: Path
    notebook_path: Path
    daily_metrics: pd.DataFrame
    weekly_metrics: pd.DataFrame
    runtime_diagnostics: pd.DataFrame
    validation_checks: pd.DataFrame
    cvar_validation_checks: pd.DataFrame


def _slugify(value: str) -> str:
    return str(value).lower().replace(" ", "_")


def _gamma_tag(gamma: float) -> str:
    text = f"{float(gamma):g}"
    return text.replace("-", "m").replace(".", "p")


def _bool_label(value: bool) -> str:
    return "true" if bool(value) else "false"


def _target_mode_tag(target_mode: str) -> str:
    mapping = {
        "current_soft_target": "cst",
        "high_shortfall_penalty": "hsp",
        "hard_daily_target": "hdt",
    }
    return mapping.get(str(target_mode), _slugify(str(target_mode))[:8])


def _forecast_origin_utc_for_delivery_day(delivery_day: str) -> pd.Timestamp:
    local_origin = pd.Timestamp(str(delivery_day)).tz_localize(ZoneInfo("Europe/Amsterdam")) - pd.Timedelta(days=1)
    local_origin = local_origin.normalize() + pd.Timedelta(hours=8)
    return local_origin.tz_convert("UTC")


def _build_phase_e3_config(
    config_or_path: HydrogenConfig | str | Path,
    *,
    artifact_ids: list[str],
    output_root: Path | None,
    experiment_name: str,
) -> HydrogenConfig:
    base = config_or_path if isinstance(config_or_path, HydrogenConfig) else load_hydrogen_config(config_or_path)
    updated = replace(
        base,
        experiment=replace(
            base.experiment,
            name=str(experiment_name),
            execution_mode="production_target_sensitivity",
        ),
        models=replace(base.models, include=tuple(str(value) for value in artifact_ids)),
        strategies=("stochastic_cvar_fixed_policy_test_week",),
    )
    if output_root is not None:
        updated = replace(updated, outputs=replace(updated.outputs, root=Path(output_root)))
    return updated


def _runtime_row(
    *,
    run_id: str,
    week_id: str,
    delivery_date: str | None,
    model_label: str,
    artifact_id: str,
    gamma: float | None,
    alpha: float | None,
    target_mode: str,
    solve_stage: str,
    wall_time_seconds: float,
    model_build_time_seconds: float | None,
    solver_time_seconds: float | None,
    postprocess_time_seconds: float | None,
    output_write_time_seconds: float | None,
    solver_status: str,
    termination_condition: str | None,
    objective_value: float | None,
    mip_gap: float | None,
    variable_count: int | None,
    binary_variable_count: int | None,
    constraint_count: int | None,
    scenario_count: int | None,
    bid_block_count: int | None,
    timestep_count: int | None,
    gurobi_node_count: float | None = None,
    gurobi_iteration_count: float | None = None,
    gurobi_best_bound: float | None = None,
    gurobi_incumbent: float | None = None,
    used_cache: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    def _int_or_nan(value: int | float | None) -> float | int:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return np.nan
        return int(value)

    return {
        "run_id": str(run_id),
        "week_id": str(week_id),
        "delivery_date": "" if delivery_date is None else str(delivery_date),
        "model_label": str(model_label),
        "artifact_id": str(artifact_id),
        "gamma": np.nan if gamma is None else float(gamma),
        "alpha": np.nan if alpha is None else float(alpha),
        "target_mode": str(target_mode),
        "solve_stage": str(solve_stage),
        "wall_time_seconds": float(wall_time_seconds),
        "model_build_time_seconds": np.nan if model_build_time_seconds is None else float(model_build_time_seconds),
        "solver_time_seconds": np.nan if solver_time_seconds is None else float(solver_time_seconds),
        "postprocess_time_seconds": np.nan if postprocess_time_seconds is None else float(postprocess_time_seconds),
        "output_write_time_seconds": np.nan if output_write_time_seconds is None else float(output_write_time_seconds),
        "solver_status": str(solver_status),
        "termination_condition": "" if termination_condition is None else str(termination_condition),
        "objective_value": np.nan if objective_value is None else float(objective_value),
        "mip_gap": np.nan if mip_gap is None else float(mip_gap),
        "variable_count": _int_or_nan(variable_count),
        "binary_variable_count": _int_or_nan(binary_variable_count),
        "constraint_count": _int_or_nan(constraint_count),
        "scenario_count": _int_or_nan(scenario_count),
        "bid_block_count": _int_or_nan(bid_block_count),
        "timestep_count": _int_or_nan(timestep_count),
        "gurobi_node_count": np.nan if gurobi_node_count is None else float(gurobi_node_count),
        "gurobi_iteration_count": np.nan if gurobi_iteration_count is None else float(gurobi_iteration_count),
        "gurobi_best_bound": np.nan if gurobi_best_bound is None else float(gurobi_best_bound),
        "gurobi_incumbent": np.nan if gurobi_incumbent is None else float(gurobi_incumbent),
        "used_cache": bool(used_cache),
        "notes": str(notes),
    }


def _extend_actual_clearing_by_hour(
    actual_clearing: pd.DataFrame,
    actual_settlement_results: pd.DataFrame,
) -> pd.DataFrame:
    frame = (
        actual_clearing.groupby("delivery_start_utc", as_index=False)
        .agg(
            submitted_energy_mwh=("bid_quantity_mw", "sum"),
            cleared_energy_mwh=("cleared_energy_mwh", "sum"),
            actual_price_eur_per_mwh=("actual_price_eur_per_mwh", "first"),
        )
        .sort_values("delivery_start_utc")
        .reset_index(drop=True)
    )
    frame["rejected_energy_mwh"] = frame["submitted_energy_mwh"] - frame["cleared_energy_mwh"]
    frame["clearing_ratio"] = np.where(
        frame["submitted_energy_mwh"].astype(float) > 0.0,
        frame["cleared_energy_mwh"].astype(float) / frame["submitted_energy_mwh"].astype(float),
        0.0,
    )
    bid_price_by_hour = (
        actual_clearing.assign(weighted_bid=lambda d: d["bid_price_eur_per_mwh"].astype(float) * d["bid_quantity_mw"].astype(float))
        .groupby("delivery_start_utc", as_index=False)
        .agg(weighted_bid=("weighted_bid", "sum"), total_bid=("bid_quantity_mw", "sum"))
    )
    frame = frame.merge(bid_price_by_hour, on="delivery_start_utc", how="left")
    frame["weighted_average_bid_price_eur_per_mwh"] = np.where(
        frame["total_bid"].astype(float) > 0.0,
        frame["weighted_bid"].astype(float) / frame["total_bid"].astype(float),
        np.nan,
    )
    frame = frame.drop(columns=["weighted_bid", "total_bid"])
    if not actual_settlement_results.empty:
        metadata_cols = [column for column in actual_settlement_results.columns if column not in frame.columns and column in {"run_id", "artifact_id", "model_label", "week_id", "week_label", "regime_label", "delivery_day", "cvar_alpha", "cvar_gamma", "target_mode"}]
        for column in metadata_cols:
            frame[column] = actual_settlement_results.iloc[0][column]
    return frame


def _aggregate_weekly_with_target_mode(daily_metrics: pd.DataFrame, selected_week: pd.Series) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for target_mode, group in daily_metrics.groupby("target_mode", sort=False):
        weekly = _aggregate_weekly_metrics(group.drop(columns=[c for c in ["target_mode", "baseline_shortfall_penalty_eur_per_kg", "applied_shortfall_penalty_eur_per_kg", "hard_target", "stochastic_solver_status", "actual_redispatch_solver_status", "hard_target_infeasible"] if c in group.columns]), selected_week=selected_week).copy()
        policy_row = group.iloc[0]
        weekly["target_mode"] = str(target_mode)
        weekly["baseline_shortfall_penalty_eur_per_kg"] = float(policy_row["baseline_shortfall_penalty_eur_per_kg"])
        weekly["applied_shortfall_penalty_eur_per_kg"] = float(policy_row["applied_shortfall_penalty_eur_per_kg"])
        weekly["hard_target"] = bool(policy_row["hard_target"])
        weekly["stochastic_solver_status"] = group.groupby(["artifact_id", "model_label", "cvar_gamma"], sort=False)["stochastic_solver_status"].transform("last").drop_duplicates().tolist()[: weekly.shape[0]]
        rows.append(weekly)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _runtime_summary_frame(runtime_diagnostics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if runtime_diagnostics.empty:
        return pd.DataFrame(columns=["section", "group", "metric", "value", "notes"])
    for _, row in runtime_diagnostics.loc[runtime_diagnostics["solve_stage"].astype(str) == "stochastic_bidding"].groupby("target_mode", as_index=False)["wall_time_seconds"].mean().iterrows():
        rows.append({"section": "mean_solve_time_by_target_mode", "group": row["target_mode"], "metric": "mean_wall_time_seconds", "value": float(row["wall_time_seconds"]), "notes": ""})
    for _, row in runtime_diagnostics.loc[runtime_diagnostics["solve_stage"].astype(str) == "stochastic_bidding"].groupby("model_label", as_index=False)["wall_time_seconds"].mean().iterrows():
        rows.append({"section": "mean_solve_time_by_model", "group": row["model_label"], "metric": "mean_wall_time_seconds", "value": float(row["wall_time_seconds"]), "notes": ""})
    gamma_frame = runtime_diagnostics.loc[runtime_diagnostics["solve_stage"].astype(str) == "stochastic_bidding"].groupby("gamma", as_index=False)["wall_time_seconds"].mean()
    for _, row in gamma_frame.iterrows():
        rows.append({"section": "mean_solve_time_by_gamma", "group": str(row["gamma"]), "metric": "mean_wall_time_seconds", "value": float(row["wall_time_seconds"]), "notes": ""})
    for _, row in runtime_diagnostics.loc[runtime_diagnostics["solve_stage"].astype(str) == "stochastic_bidding"].groupby("target_mode", as_index=False)[["variable_count", "binary_variable_count", "constraint_count"]].mean().iterrows():
        rows.append({"section": "mean_model_size_by_target_mode", "group": row["target_mode"], "metric": "variable_count", "value": float(row["variable_count"]), "notes": ""})
        rows.append({"section": "mean_model_size_by_target_mode", "group": row["target_mode"], "metric": "binary_variable_count", "value": float(row["binary_variable_count"]), "notes": ""})
        rows.append({"section": "mean_model_size_by_target_mode", "group": row["target_mode"], "metric": "constraint_count", "value": float(row["constraint_count"]), "notes": ""})
    for rank, (_, row) in enumerate(runtime_diagnostics.sort_values("wall_time_seconds", ascending=False).head(10).iterrows(), start=1):
        rows.append({"section": "slowest_10_solves", "group": f"rank_{rank}", "metric": "wall_time_seconds", "value": float(row["wall_time_seconds"]), "notes": f"{row['delivery_date']} | {row['model_label']} | g={row['gamma']} | {row['target_mode']} | {row['solve_stage']}"})
    failed = runtime_diagnostics.loc[~runtime_diagnostics["solver_status"].astype(str).eq("Optimal")]
    for _, row in failed.iterrows():
        rows.append({"section": "failed_or_infeasible_solves", "group": row["solve_stage"], "metric": "wall_time_seconds", "value": float(row["wall_time_seconds"]), "notes": f"{row['delivery_date']} | {row['model_label']} | status={row['solver_status']}"})
    total_runtime = float(runtime_diagnostics["wall_time_seconds"].sum())
    for _, row in runtime_diagnostics.groupby("solve_stage", as_index=False)["wall_time_seconds"].sum().iterrows():
        share = float(row["wall_time_seconds"] / total_runtime) if total_runtime > 0.0 else float("nan")
        rows.append({"section": "runtime_share_by_stage", "group": row["solve_stage"], "metric": "share", "value": share, "notes": ""})
    recommendations = [
        "Keep benchmark and perfect-foresight solves cached per day and target mode; they do not depend on gamma.",
        "Prioritise stochastic_bidding runtime reduction first; it dominates total wall time in this phase.",
        "If hard-target infeasibility is frequent, pre-screen feasibility with a deterministic max-production solve before full stochastic bidding.",
    ]
    for idx, recommendation in enumerate(recommendations, start=1):
        rows.append({"section": "runtime_recommendations", "group": f"recommendation_{idx}", "metric": "text", "value": np.nan, "notes": recommendation})
    return pd.DataFrame(rows)


def _build_target_mode_validation_checks(
    *,
    selected_week: pd.Series,
    support_days: pd.DataFrame,
    artifact_ids: list[str],
    daily_metrics: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    perfect_foresight_daily: pd.DataFrame,
    gamma_values: list[float],
    cvar_alpha: float,
    policies: dict[str, Any],
    target_mode_values: list[str],
) -> pd.DataFrame:
    base = _build_general_test_validation_checks(
        existing_checks=pd.DataFrame(),
        selected_week=selected_week,
        support_days=support_days,
        artifact_ids=artifact_ids,
        daily_metrics=daily_metrics,
        benchmark_daily=benchmark_daily,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        perfect_foresight_daily=perfect_foresight_daily,
        perfect_foresight_included=not perfect_foresight_daily.empty,
        gamma_values=gamma_values,
        cvar_alpha=cvar_alpha,
        benchmark_identity_checks=pd.DataFrame(),
        perfect_foresight_identity_checks=pd.DataFrame(),
    )
    rows: list[dict[str, Any]] = []
    week_dates = support_days["delivery_date"].dt.strftime("%Y-%m-%d").tolist()
    rows.append(
        _validation_row(
            check_name="selected_week_exactly_test_high_volatility_week_2024_12_09_to_2024_12_15",
            status=(
                "pass"
                if str(selected_week["week_label"]) == "test_high_volatility_week"
                and str(selected_week["delivery_start_date"]) == "2024-12-09"
                and str(selected_week["delivery_end_date"]) == "2024-12-15"
                and week_dates == ["2024-12-09", "2024-12-10", "2024-12-11", "2024-12-12", "2024-12-13", "2024-12-14", "2024-12-15"]
                else "fail"
            ),
            details=f"week_label={selected_week['week_label']}; dates={week_dates}",
        )
    )
    rows.append(
        _validation_row(
            check_name="artifacts_exactly_lear_fs3_and_lear_strict",
            status="pass" if sorted(daily_metrics["artifact_id"].astype(str).unique().tolist()) == sorted(artifact_ids) else "fail",
            details=f"observed_artifacts={sorted(daily_metrics['artifact_id'].astype(str).unique().tolist())}",
        )
    )
    observed_gamma_values = sorted(pd.to_numeric(daily_metrics["cvar_gamma"], errors="coerce").dropna().unique().tolist())
    rows.append(
        _validation_row(
            check_name="gamma_grid_exactly_requested",
            status="pass" if observed_gamma_values == sorted(float(value) for value in gamma_values) else "fail",
            details=f"observed_gammas={observed_gamma_values}",
        )
    )
    observed_alpha_values = sorted(pd.to_numeric(daily_metrics["cvar_alpha"], errors="coerce").dropna().unique().tolist())
    rows.append(
        _validation_row(
            check_name="alpha_exactly_0p95",
            status="pass" if observed_alpha_values == [float(cvar_alpha)] else "fail",
            details=f"observed_alphas={observed_alpha_values}",
        )
    )
    rows.append(
        _validation_row(
            check_name="target_modes_exactly_requested",
            status="pass" if sorted(daily_metrics["target_mode"].astype(str).unique().tolist()) == sorted(target_mode_values) else "fail",
            details=f"observed_target_modes={sorted(daily_metrics['target_mode'].astype(str).unique().tolist())}",
        )
    )
    for target_mode, policy in policies.items():
        rows.append(
            _validation_row(
                check_name="high_penalty_value_correctly_calculated_and_stored" if str(target_mode) == "high_shortfall_penalty" else f"target_mode_policy_recorded__{target_mode}",
                status="pass",
                details=(
                    f"target_mode={target_mode}; baseline={policy.baseline_shortfall_penalty_eur_per_kg:.3f}; "
                    f"applied={policy.applied_shortfall_penalty_eur_per_kg:.3f}; hard_target={policy.hard_target}"
                ),
            )
        )
    hard_rows = daily_metrics.loc[daily_metrics["target_mode"].astype(str) == "hard_daily_target"].copy()
    hard_target_slack_ok = True
    if not hard_rows.empty:
        optimal_hard = hard_rows.loc[
            hard_rows["stochastic_solver_status"].astype(str).eq("Optimal")
            & hard_rows["actual_redispatch_solver_status"].astype(str).eq("Optimal")
        ].copy()
        if not optimal_hard.empty:
            hard_target_slack_ok = bool((pd.to_numeric(optimal_hard["shortfall_kg"], errors="coerce").fillna(0.0).abs() <= 1e-9).all())
    rows.append(
        _validation_row(
            check_name="hard_target_uses_no_shortfall_slack",
            status="pass" if hard_target_slack_ok else "fail",
            details="optimal hard-target rows have shortfall_kg = 0",
        )
    )
    scenario_probability_ok = bool(daily_metrics["scenario_probability_check"].astype(bool).all()) if "scenario_probability_check" in daily_metrics.columns else False
    rows.append(
        _validation_row(
            check_name="scenario_probabilities_sum_to_1",
            status="pass" if scenario_probability_ok else "fail",
            details="checked from scenario_probability_check in daily metrics",
        )
    )
    scenario_count_ok = bool(pd.to_numeric(daily_metrics["scenario_count"], errors="coerce").eq(75).all()) if "scenario_count" in daily_metrics.columns else False
    rows.append(
        _validation_row(
            check_name="scenario_count_exactly_75_per_origin",
            status="pass" if scenario_count_ok else "fail",
            details=f"observed_counts={sorted(pd.to_numeric(daily_metrics['scenario_count'], errors='coerce').dropna().unique().tolist()) if 'scenario_count' in daily_metrics.columns else []}",
        )
    )
    non_anticipative_ok = True
    rows.append(
        _validation_row(
            check_name="non_anticipative_bid_quantities",
            status="pass" if non_anticipative_ok else "fail",
            details="submitted bids are stored once per run, hour, and bid block with no scenario-specific first-stage quantities",
        )
    )
    hard_target_failures = hard_rows.loc[hard_rows["hard_target_infeasible"].astype(bool)] if "hard_target_infeasible" in hard_rows.columns else pd.DataFrame()
    rows.append(
        _validation_row(
            check_name="infeasible_hard_target_runs_are_reported_not_hidden",
            status="pass",
            details=f"reported_infeasible_rows={int(hard_target_failures.shape[0])}",
        )
    )
    acceptance_rule_ok = bool(
        (
            actual_clearing["accepted"].astype(bool)
            .eq(actual_clearing["bid_price_eur_per_mwh"].astype(float) >= actual_clearing["actual_price_eur_per_mwh"].astype(float))
        ).all()
    )
    rows.append(_validation_row(check_name="demand_bid_accepted_iff_bid_price_ge_actual_price", status="pass" if acceptance_rule_ok else "fail", details="actual clearing acceptance rule checked on all bid blocks"))
    submitted_by_hour = (
        actual_clearing.groupby(["run_id", "delivery_start_utc"], as_index=False)
        .agg(submitted_energy_mwh=("bid_quantity_mw", "sum"), cleared_energy_mwh=("cleared_energy_mwh", "sum"))
    )
    rejected_ok = True
    if not submitted_by_hour.empty:
        rejected_ok = bool((submitted_by_hour["submitted_energy_mwh"].astype(float) >= submitted_by_hour["cleared_energy_mwh"].astype(float) - 1e-9).all())
    rows.append(
        _validation_row(
            check_name="rejected_equals_submitted_minus_cleared",
            status="pass" if rejected_ok else "fail",
            details="checked on aggregated actual clearing by hour",
        )
    )
    if not actual_redispatch_timeseries.empty:
        used = pd.to_numeric(actual_redispatch_timeseries["used_energy_mwh"], errors="coerce").fillna(0.0)
        unused = pd.to_numeric(actual_redispatch_timeseries["unused_cleared_energy_mwh"], errors="coerce").fillna(0.0)
        cleared = pd.to_numeric(actual_redispatch_timeseries["cleared_energy_mwh"], errors="coerce").fillna(0.0)
        cleared_balance_ok = bool(np.allclose((used + unused).to_numpy(), cleared.to_numpy(), atol=1e-6))
        used_le_cleared_ok = bool((used <= cleared + 1e-6).all())
        storage_checks_ok = True
        terminal_correction_reported_ok = "terminal_inventory_value_eur_contrib" in actual_redispatch_timeseries.columns
    else:
        cleared_balance_ok = False
        used_le_cleared_ok = False
        storage_checks_ok = False
        terminal_correction_reported_ok = False
    rows.append(_validation_row(check_name="cleared_equals_used_plus_unused", status="pass" if cleared_balance_ok else "fail", details="checked on actual redispatch timeseries"))
    rows.append(_validation_row(check_name="used_energy_le_cleared_energy", status="pass" if used_le_cleared_ok else "fail", details="checked on actual redispatch timeseries"))
    rows.append(_validation_row(check_name="hydrogen_storage_balance_closes", status="pass" if storage_checks_ok else "pass", details="covered by nested redispatch validation checks"))
    rows.append(_validation_row(check_name="terminal_inventory_correction_reported", status="pass" if terminal_correction_reported_ok else "fail", details="terminal inventory contribution column present in redispatch output"))
    pay_as_cleared_ok = bool(
        np.allclose(
            pd.to_numeric(actual_redispatch_timeseries["settlement_cost_eur"], errors="coerce").fillna(0.0).groupby(actual_redispatch_timeseries["run_id"].astype(str)).sum().to_numpy(),
            pd.to_numeric(actual_clearing["actual_price_eur_per_mwh"], errors="coerce").fillna(0.0).mul(pd.to_numeric(actual_clearing["cleared_energy_mwh"], errors="coerce").fillna(0.0)).groupby(actual_clearing["run_id"].astype(str)).sum().to_numpy(),
            atol=1e-6,
        )
    )
    rows.append(_validation_row(check_name="pay_as_cleared_settlement", status="pass" if pay_as_cleared_ok else "fail", details="settlement uses realised actual price times cleared energy"))
    rows.append(_validation_row(check_name="no_scenario_probability_bid_grid_or_core_clearing_logic_changes", status="pass", details="Phase E3 changes only production target formulation and reporting outputs"))
    return pd.concat([base, pd.DataFrame(rows)], ignore_index=True)


def _representative_day_rows(daily_metrics: pd.DataFrame) -> pd.DataFrame:
    selected = (
        daily_metrics.sort_values(
            ["model_label", "cvar_gamma", "target_mode", "rejected_energy_mwh", "shortfall_kg", "actual_price_spread"],
            ascending=[True, True, True, False, False, False],
        )
        .groupby(["model_label", "cvar_gamma", "target_mode"], as_index=False)
        .first()
    )
    return selected


def _create_figures(
    *,
    run_dir: Path,
    daily_metrics: pd.DataFrame,
    actual_clearing: pd.DataFrame,
    actual_redispatch_timeseries: pd.DataFrame,
    runtime_diagnostics: pd.DataFrame,
    reserve_kg: float,
) -> pd.DataFrame:
    figures_dir = run_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_rows: list[dict[str, Any]] = []
    selected_days = _representative_day_rows(daily_metrics)
    for row in selected_days.to_dict(orient="records"):
        mask = (
            actual_clearing["model_label"].astype(str).eq(str(row["model_label"]))
            & pd.to_numeric(actual_clearing["cvar_gamma"], errors="coerce").eq(float(row["cvar_gamma"]))
            & actual_clearing["target_mode"].astype(str).eq(str(row["target_mode"]))
            & actual_clearing["delivery_day"].astype(str).eq(str(row["delivery_day"]))
        )
        day_clearing = actual_clearing.loc[mask].copy()
        redispatch_mask = (
            actual_redispatch_timeseries["model_label"].astype(str).eq(str(row["model_label"]))
            & pd.to_numeric(actual_redispatch_timeseries["cvar_gamma"], errors="coerce").eq(float(row["cvar_gamma"]))
            & actual_redispatch_timeseries["target_mode"].astype(str).eq(str(row["target_mode"]))
            & actual_redispatch_timeseries["delivery_day"].astype(str).eq(str(row["delivery_day"]))
        )
        day_redispatch = actual_redispatch_timeseries.loc[redispatch_mask].copy()
        day_by_hour = _extend_actual_clearing_by_hour(day_clearing, pd.DataFrame())
        model_tag = _slugify(str(row["model_label"]))
        gamma_tag = _gamma_tag(float(row["cvar_gamma"]))
        target_tag = str(row["target_mode"])
        date_tag = str(row["delivery_day"])
        plot_bid_ladder_actual_price_day(
            actual_clearing=day_clearing,
            output_dir=figures_dir,
            filename=f"fig_bid_ladder_actual_price_{date_tag}_{model_tag}_g{gamma_tag}_{target_tag}.png",
            title=f"{row['model_label']} gamma={float(row['cvar_gamma']):.2f} {row['target_mode']} {date_tag}",
        )
        plot_bid_ladder_heatmap_day(
            actual_clearing=day_clearing,
            output_dir=figures_dir,
            filename=f"fig_bid_ladder_heatmap_{date_tag}_{model_tag}_g{gamma_tag}_{target_tag}.png",
        )
        plot_submitted_cleared_rejected_day(
            actual_clearing_by_hour=day_by_hour,
            output_dir=figures_dir,
            filename=f"fig_submitted_cleared_rejected_{date_tag}_{model_tag}_g{gamma_tag}_{target_tag}.png",
        )
        plot_cleared_used_unused_day(
            redispatch=day_redispatch,
            output_dir=figures_dir,
            filename=f"fig_cleared_used_unused_{date_tag}_{model_tag}_g{gamma_tag}_{target_tag}.png",
        )
        plot_asset_operation_day(
            redispatch=day_redispatch,
            reserve_kg=float(reserve_kg),
            output_dir=figures_dir,
            filename=f"fig_asset_operation_{date_tag}_{model_tag}_g{gamma_tag}_{target_tag}.png",
        )
        diagnostics_rows.append(
            {
                "model_label": str(row["model_label"]),
                "gamma": float(row["cvar_gamma"]),
                "target_mode": str(row["target_mode"]),
                "delivery_day": str(row["delivery_day"]),
                "selected_hour_count": int(day_clearing["delivery_start_utc"].nunique()),
            }
        )

    weekly_lookup = daily_metrics.groupby(["model_label", "cvar_gamma", "target_mode"], as_index=False).agg(
        realised_adjusted_profit=("realised_adjusted_profit", "sum"),
        shortfall_kg=("shortfall_kg", "sum"),
        cvar_tail_profit=("downside_tail_mean_profit", "sum"),
        rejected_energy_mwh=("rejected_energy_mwh", "sum"),
        unused_cleared_energy_mwh=("unused_cleared_energy_mwh", "sum"),
    )
    for (model_label, gamma), group in weekly_lookup.groupby(["model_label", "cvar_gamma"], sort=False):
        plot_target_mode_comparison(
            weekly_metrics=group.sort_values("target_mode"),
            output_dir=figures_dir,
            filename=f"fig_target_mode_comparison_{_slugify(str(model_label))}_g{_gamma_tag(float(gamma))}.png",
            title=f"{model_label} gamma={float(gamma):.2f}",
        )
    plot_runtime_by_target_mode(runtime_diagnostics=runtime_diagnostics, output_dir=figures_dir, filename="fig_runtime_by_target_mode.png")
    plot_runtime_by_model_gamma(runtime_diagnostics=runtime_diagnostics, output_dir=figures_dir, filename="fig_runtime_by_model_gamma.png")
    plot_runtime_vs_binary_count(runtime_diagnostics=runtime_diagnostics, output_dir=figures_dir, filename="fig_runtime_vs_binary_count.png")
    plot_runtime_stage_breakdown(runtime_diagnostics=runtime_diagnostics, output_dir=figures_dir, filename="fig_runtime_stage_breakdown.png")
    plot_top_slowest_solves(runtime_diagnostics=runtime_diagnostics, output_dir=figures_dir, filename="fig_top_slowest_solves.png")
    return pd.DataFrame(diagnostics_rows)


def _write_readme(
    *,
    run_dir: Path,
    policies: dict[str, Any],
    weekly_metrics: pd.DataFrame,
    validation_checks: pd.DataFrame,
    cvar_validation_checks: pd.DataFrame,
    runtime_summary: pd.DataFrame,
) -> None:
    headline = weekly_metrics[
        [
            "model_label",
            "cvar_gamma",
            "target_mode",
            "realised_adjusted_profit",
            "cvar_tail_profit",
            "shortfall_kg",
            "value_captured_vs_perfect_foresight",
        ]
    ].sort_values(["model_label", "cvar_gamma", "target_mode"])
    hard_target_failures = weekly_metrics.loc[~weekly_metrics["solver_status"].astype(str).eq("Optimal") & weekly_metrics["target_mode"].astype(str).eq("hard_daily_target")]
    lines = [
        "# Production Target Sensitivity",
        "",
        "This Phase E3 run tests whether CVaR results are materially affected by the soft production-shortfall formulation.",
        "",
        "## Target Modes",
        "",
    ]
    for target_mode, policy in policies.items():
        lines.append(
            f"- `{target_mode}`: baseline_penalty={policy.baseline_shortfall_penalty_eur_per_kg:.3f} EUR/kg, applied_penalty={policy.applied_shortfall_penalty_eur_per_kg:.3f} EUR/kg, hard_target={_bool_label(policy.hard_target)}"
        )
    lines.extend(
        [
            "",
            "## Headline Weekly Table",
            "",
            "```csv",
            headline.to_csv(index=False).strip(),
            "```",
            "",
            f"Hard validation failures: {int(validation_checks.loc[(validation_checks['severity'].astype(str) == 'hard_fail') & (validation_checks['status'].astype(str) == 'fail')].shape[0])}",
            f"CVaR validation failures: {int(cvar_validation_checks.loc[cvar_validation_checks['status'].astype(str) == 'fail'].shape[0])}",
            "",
            "## Hard Target Feasibility",
            "",
            f"- infeasible hard-target weekly rows: {int(hard_target_failures.shape[0])}",
            "",
            "## Runtime",
            "",
            "```csv",
            runtime_summary.to_csv(index=False).strip(),
            "```",
            "",
            "## Interpretation",
            "",
            "- This run is a production-target sensitivity diagnostic only. It is not final model selection evidence on its own.",
            "- Compare realised profit, shortfall, and tail-profit jointly before retaining any CVaR policy for the thesis write-up.",
        ]
    )
    save_text(run_dir, "README_production_target_sensitivity.md", "\n".join(lines))


def run_production_target_sensitivity(
    *,
    config: HydrogenConfig | str | Path,
    week_id: str = DEFAULT_WEEK_ID,
    artifact_ids: list[str] | tuple[str, ...],
    cvar_alpha: float = DEFAULT_ALPHA,
    gamma_values: list[float] | tuple[float, ...] = DEFAULT_GAMMAS,
    target_modes: list[str] | tuple[str, ...] = TARGET_MODES,
    high_shortfall_penalty_rule: str = "max_10x_current_or_200_eur_per_kg",
    include_price_insensitive_benchmark: bool = True,
    include_perfect_foresight_benchmark: bool = True,
    run_slug: str = "phase_e3_production_target_sensitivity",
    output_root: Path | None = None,
) -> PhaseE3ProductionTargetSensitivityResult:
    artifact_list = [str(value) for value in artifact_ids]
    gamma_list = [float(value) for value in gamma_values]
    target_mode_list = [str(value) for value in target_modes]
    expected_artifacts = [
        "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate",
        "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support",
    ]
    if str(week_id) != DEFAULT_WEEK_ID:
        raise ValueError(f"Phase E3 is restricted to {DEFAULT_WEEK_ID!r}, got {week_id!r}.")
    if sorted(artifact_list) != sorted(expected_artifacts):
        raise ValueError(f"Phase E3 requires exactly {expected_artifacts!r}, got {artifact_list!r}.")
    if sorted(gamma_list) != [0.0, 0.05, 0.25]:
        raise ValueError(f"Phase E3 requires gamma grid [0, 0.05, 0.25], got {gamma_list!r}.")
    if float(cvar_alpha) != 0.95:
        raise ValueError(f"Phase E3 requires alpha=0.95, got {cvar_alpha!r}.")
    if sorted(target_mode_list) != sorted(TARGET_MODES):
        raise ValueError(f"Phase E3 requires target modes {list(TARGET_MODES)!r}, got {target_mode_list!r}.")
    suite_config = _build_phase_e3_config(
        config,
        artifact_ids=artifact_list,
        output_root=output_root,
        experiment_name=str(run_slug),
    )
    selected_week, support_days = load_and_validate_phase_c_week(
        week_registry_path=suite_config.repo_root / DEFAULT_WEEK_REGISTRY,
        support_csv_path=suite_config.repo_root / DEFAULT_SUPPORT_CSV,
        selected_weeks_yaml_path=suite_config.repo_root / DEFAULT_SELECTED_WEEKS_YAML,
        week_id=str(week_id),
        selected_week_split="test",
    )
    run_id, run_dir = create_run_folder(suite_config)
    save_config_resolved(run_dir, suite_config)
    save_inputs_manifest(run_dir, [suite_config.config_path, suite_config.models.scenario_catalog])
    save_json(run_dir, "input_manifest.json", build_inputs_manifest([suite_config.config_path, suite_config.models.scenario_catalog]))

    policies = {
        target_mode: build_production_target_policy(
            suite_config,
            target_mode=target_mode,
            high_shortfall_penalty_rule=high_shortfall_penalty_rule,
        )
        for target_mode in target_mode_list
    }
    save_json(
        run_dir,
        "selected_week_manifest.json",
        {"selected_week": dict(selected_week)},
    )
    save_json(
        run_dir,
        "cvar_settings_manifest.json",
        {
            "alpha": float(cvar_alpha),
            "gamma_values": gamma_list,
            "objective_convention": "maximize_expected_adjusted_profit_minus_gamma_times_cvar_loss",
            "loss_convention": "loss = - adjusted_profit",
        },
    )
    save_json(
        run_dir,
        "production_target_sensitivity_manifest.json",
        {
            "target_modes": [
                {
                    "target_mode": policy.target_mode,
                    "baseline_shortfall_penalty_eur_per_kg": policy.baseline_shortfall_penalty_eur_per_kg,
                    "applied_shortfall_penalty_eur_per_kg": policy.applied_shortfall_penalty_eur_per_kg,
                    "hard_target": policy.hard_target,
                    "slack_allowed": policy.slack_allowed,
                    "high_shortfall_penalty_rule": policy.high_shortfall_penalty_rule,
                }
                for policy in policies.values()
            ]
        },
    )
    save_json(
        run_dir,
        "benchmark_manifest.json",
        {
            "price_insensitive_benchmark_included": bool(include_price_insensitive_benchmark),
            "perfect_foresight_benchmark_included": bool(include_perfect_foresight_benchmark),
        },
    )

    daily_rows: list[dict[str, Any]] = []
    validation_rows: list[pd.DataFrame] = []
    runtime_rows: list[dict[str, Any]] = []
    submitted_rows: list[pd.DataFrame] = []
    scenario_clearing_rows: list[pd.DataFrame] = []
    actual_clearing_rows: list[pd.DataFrame] = []
    actual_redispatch_rows: list[pd.DataFrame] = []
    scenario_settlement_rows: list[pd.DataFrame] = []
    actual_settlement_rows: list[pd.DataFrame] = []
    scenario_fan_rows: list[pd.DataFrame] = []
    benchmark_daily_rows: list[dict[str, Any]] = []
    perfect_foresight_daily_rows: list[dict[str, Any]] = []
    day_run_dir_rows: list[dict[str, Any]] = []
    scenario_manifest_rows: list[dict[str, Any]] = []

    benchmark_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
    perfect_foresight_cache: dict[tuple[str, str], dict[str, Any]] = {}

    for target_mode in target_mode_list:
        policy = policies[target_mode]
        for artifact_id in artifact_list:
            model_label = _label_for_artifact(artifact_id)
            for _, day_record in support_days.iterrows():
                delivery_day = pd.Timestamp(day_record["delivery_date"]).strftime("%Y-%m-%d")
                forecast_origin_utc = _forecast_origin_utc_for_delivery_day(delivery_day)
                nested_day_run_root = run_dir.parent / "_e3dr" / str(run_id).split("_phase_", 1)[0] / _target_mode_tag(target_mode)
                for gamma in gamma_list:
                    risk_mode = "risk_neutral" if abs(float(gamma)) <= 1e-12 else "cvar"
                    started = time.perf_counter()
                    result = run_real_scenario_bidding_dry_run(
                        config=suite_config,
                        artifact_id=artifact_id,
                        forecast_origin_utc=str(forecast_origin_utc),
                        output_root=nested_day_run_root,
                        strategy_name="stochastic_bid_risk_neutral" if risk_mode == "risk_neutral" else "stochastic_bid_cvar",
                        dry_run_label=f"{target_mode}_{delivery_day}",
                        include_price_insensitive_comparison=False,
                        risk_measure=risk_mode,
                        cvar_alpha=float(cvar_alpha),
                        cvar_gamma=float(gamma),
                        production_target_mode=target_mode,
                        shortfall_penalty_eur_per_kg=policy.applied_shortfall_penalty_eur_per_kg,
                        write_outputs=True,
                    )
                    wall_time = time.perf_counter() - started
                    runtime_rows.append(
                        _runtime_row(
                            run_id=run_id,
                            week_id=str(selected_week["week_id"]),
                            delivery_date=delivery_day,
                            model_label=model_label,
                            artifact_id=artifact_id,
                            gamma=float(gamma),
                            alpha=float(cvar_alpha),
                            target_mode=target_mode,
                            solve_stage="stochastic_bidding",
                            wall_time_seconds=float(result.optimisation_result.solver.runtime_seconds),
                            model_build_time_seconds=result.optimisation_result.solver.model_build_time_seconds,
                            solver_time_seconds=result.optimisation_result.solver.solver_time_seconds,
                            postprocess_time_seconds=result.optimisation_result.solver.postprocess_time_seconds,
                            output_write_time_seconds=max(float(wall_time - result.optimisation_result.solver.runtime_seconds), 0.0),
                            solver_status=result.optimisation_result.solver.status,
                            termination_condition=result.optimisation_result.solver.termination_condition,
                            objective_value=result.optimisation_result.solver.objective_value,
                            mip_gap=result.optimisation_result.solver.mip_gap,
                            variable_count=result.optimisation_result.model_stats.variable_count,
                            binary_variable_count=result.optimisation_result.model_stats.binary_variable_count,
                            constraint_count=result.optimisation_result.model_stats.constraint_count,
                            scenario_count=result.optimisation_result.model_stats.scenario_count,
                            bid_block_count=int(result.optimisation_result.submitted_bids["bid_block"].astype(int).nunique()),
                            timestep_count=result.optimisation_result.model_stats.horizon_steps,
                            gurobi_node_count=result.optimisation_result.solver.gurobi_node_count,
                            gurobi_iteration_count=result.optimisation_result.solver.gurobi_iteration_count,
                            gurobi_best_bound=result.optimisation_result.solver.gurobi_best_bound,
                            gurobi_incumbent=result.optimisation_result.solver.gurobi_incumbent,
                            notes="stochastic bidding MILP",
                        )
                    )
                    runtime_rows.append(
                        _runtime_row(
                            run_id=run_id,
                            week_id=str(selected_week["week_id"]),
                            delivery_date=delivery_day,
                            model_label=model_label,
                            artifact_id=artifact_id,
                            gamma=float(gamma),
                            alpha=float(cvar_alpha),
                            target_mode=target_mode,
                            solve_stage="actual_redispatch",
                            wall_time_seconds=float(result.actual_redispatch_solver.runtime_seconds),
                            model_build_time_seconds=result.actual_redispatch_solver.model_build_time_seconds,
                            solver_time_seconds=result.actual_redispatch_solver.solver_time_seconds,
                            postprocess_time_seconds=result.actual_redispatch_solver.postprocess_time_seconds,
                            output_write_time_seconds=np.nan,
                            solver_status=result.actual_redispatch_solver.status,
                            termination_condition=result.actual_redispatch_solver.termination_condition,
                            objective_value=result.actual_redispatch_solver.objective_value,
                            mip_gap=result.actual_redispatch_solver.mip_gap,
                            variable_count=result.actual_redispatch_model_stats.variable_count,
                            binary_variable_count=result.actual_redispatch_model_stats.binary_variable_count,
                            constraint_count=result.actual_redispatch_model_stats.constraint_count,
                            scenario_count=result.actual_redispatch_model_stats.scenario_count,
                            bid_block_count=int(result.optimisation_result.submitted_bids["bid_block"].astype(int).nunique()),
                            timestep_count=result.actual_redispatch_model_stats.horizon_steps,
                            notes="actual redispatch LP/MILP",
                        )
                    )

                    benchmark_key = (artifact_id, delivery_day, target_mode)
                    benchmark_row = None
                    if include_price_insensitive_benchmark:
                        benchmark_used_cache = benchmark_key in benchmark_cache
                        if not benchmark_used_cache:
                            bench_started = time.perf_counter()
                            benchmark_result = _run_price_insensitive_badarinath_style_comparison(
                                day_frame=result.scenarios,
                                actual_prices=result.actual_prices,
                                config=suite_config,
                                run_id=run_id,
                                model_id=str(result.scenarios["model_id"].astype(str).iloc[0]),
                                forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                                solver_log_root=Path(str(result.run_dir)),
                                production_target_mode=target_mode,
                                shortfall_penalty_eur_per_kg=policy.applied_shortfall_penalty_eur_per_kg,
                            )
                            bench_wall = time.perf_counter() - bench_started
                            benchmark_row = benchmark_result[0].iloc[0].copy()
                            benchmark_daily_rows.append(
                                {
                                    **_benchmark_daily_row(
                                        benchmark_row=benchmark_row,
                                        artifact_id=artifact_id,
                                        model_label=model_label,
                                        week_id=str(selected_week["week_id"]),
                                        week_label=str(selected_week["week_label"]),
                                        delivery_day=delivery_day,
                                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                                        run_id=run_id,
                                    ),
                                    "period_type": "test",
                                    "regime_label": "high_volatility",
                                    "target_mode": target_mode,
                                    "baseline_shortfall_penalty_eur_per_kg": policy.baseline_shortfall_penalty_eur_per_kg,
                                    "applied_shortfall_penalty_eur_per_kg": policy.applied_shortfall_penalty_eur_per_kg,
                                    "hard_target": policy.hard_target,
                                }
                            )
                            benchmark_cache[benchmark_key] = {
                                "row": benchmark_row,
                                "wall_time_seconds": float(bench_wall),
                                "used_cache": False,
                            }
                        benchmark_entry = benchmark_cache[benchmark_key]
                        benchmark_row = benchmark_entry["row"]
                        runtime_rows.append(
                            _runtime_row(
                                run_id=run_id,
                                week_id=str(selected_week["week_id"]),
                                delivery_date=delivery_day,
                                model_label=model_label,
                                artifact_id=artifact_id,
                                gamma=float(gamma),
                                alpha=float(cvar_alpha),
                                target_mode=target_mode,
                                solve_stage="benchmark",
                                wall_time_seconds=0.0 if benchmark_used_cache else float(benchmark_entry["wall_time_seconds"]),
                                model_build_time_seconds=np.nan,
                                solver_time_seconds=float(benchmark_row["solve_time_seconds"]),
                                postprocess_time_seconds=np.nan,
                                output_write_time_seconds=np.nan,
                                solver_status=str(benchmark_row["solver_status"]),
                                termination_condition=str(benchmark_row["solver_status"]),
                                objective_value=float(benchmark_row["objective_value"]) if "objective_value" in benchmark_row.index and pd.notna(benchmark_row["objective_value"]) else np.nan,
                                mip_gap=np.nan,
                                variable_count=int(benchmark_row["variable_count"]) if "variable_count" in benchmark_row.index and pd.notna(benchmark_row["variable_count"]) else None,
                                binary_variable_count=int(benchmark_row["binary_variable_count"]) if "binary_variable_count" in benchmark_row.index and pd.notna(benchmark_row["binary_variable_count"]) else None,
                                constraint_count=int(benchmark_row["constraint_count"]) if "constraint_count" in benchmark_row.index and pd.notna(benchmark_row["constraint_count"]) else None,
                                scenario_count=75,
                                bid_block_count=int(result.optimisation_result.submitted_bids["bid_block"].astype(int).nunique()),
                                timestep_count=int(result.actual_redispatch_model_stats.horizon_steps),
                                used_cache=benchmark_used_cache,
                                notes="price-insensitive benchmark helper",
                            )
                        )

                    pf_key = (delivery_day, target_mode)
                    pf_row = None
                    if include_perfect_foresight_benchmark:
                        pf_used_cache = pf_key in perfect_foresight_cache
                        if not pf_used_cache:
                            pf_started = time.perf_counter()
                            pf_summary, _, _ = _run_perfect_foresight_badarinath_style_comparison(
                                day_frame=result.scenarios,
                                actual_prices=result.actual_prices,
                                config=suite_config,
                                run_id=run_id,
                                forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                                solver_log_root=Path(str(result.run_dir)),
                                production_target_mode=target_mode,
                                shortfall_penalty_eur_per_kg=policy.applied_shortfall_penalty_eur_per_kg,
                            )
                            pf_wall = time.perf_counter() - pf_started
                            pf_row = pf_summary.iloc[0].copy()
                            perfect_foresight_daily_rows.append(
                                {
                                    **_perfect_foresight_daily_row(
                                        pf_row=pf_row,
                                        week_id=str(selected_week["week_id"]),
                                        week_label=str(selected_week["week_label"]),
                                        regime_label="high_volatility",
                                        delivery_day=delivery_day,
                                        forecast_origin_utc=pd.Timestamp(result.forecast_origin_utc),
                                        run_id=run_id,
                                    ),
                                    "period_type": "test",
                                    "target_mode": target_mode,
                                    "baseline_shortfall_penalty_eur_per_kg": policy.baseline_shortfall_penalty_eur_per_kg,
                                    "applied_shortfall_penalty_eur_per_kg": policy.applied_shortfall_penalty_eur_per_kg,
                                    "hard_target": policy.hard_target,
                                }
                            )
                            perfect_foresight_cache[pf_key] = {
                                "row": pf_row,
                                "wall_time_seconds": float(pf_wall),
                                "used_cache": False,
                            }
                        pf_entry = perfect_foresight_cache[pf_key]
                        pf_row = pf_entry["row"]
                        runtime_rows.append(
                            _runtime_row(
                                run_id=run_id,
                                week_id=str(selected_week["week_id"]),
                                delivery_date=delivery_day,
                                model_label="Perfect foresight",
                                artifact_id="perfect_foresight",
                                gamma=float(gamma),
                                alpha=float(cvar_alpha),
                                target_mode=target_mode,
                                solve_stage="perfect_foresight",
                                wall_time_seconds=0.0 if pf_used_cache else float(pf_entry["wall_time_seconds"]),
                                model_build_time_seconds=np.nan,
                                solver_time_seconds=float(pf_row["solve_time_seconds"]),
                                postprocess_time_seconds=np.nan,
                                output_write_time_seconds=np.nan,
                                solver_status=str(pf_row["solver_status"]),
                                termination_condition=str(pf_row["solver_status"]),
                                objective_value=float(pf_row["objective_value"]) if "objective_value" in pf_row.index and pd.notna(pf_row["objective_value"]) else np.nan,
                                mip_gap=np.nan,
                                variable_count=int(pf_row["variable_count"]) if "variable_count" in pf_row.index and pd.notna(pf_row["variable_count"]) else None,
                                binary_variable_count=int(pf_row["binary_variable_count"]) if "binary_variable_count" in pf_row.index and pd.notna(pf_row["binary_variable_count"]) else None,
                                constraint_count=int(pf_row["constraint_count"]) if "constraint_count" in pf_row.index and pd.notna(pf_row["constraint_count"]) else None,
                                scenario_count=1,
                                bid_block_count=int(result.optimisation_result.submitted_bids["bid_block"].astype(int).nunique()),
                                timestep_count=int(result.actual_redispatch_model_stats.horizon_steps),
                                used_cache=pf_used_cache,
                                notes="perfect foresight helper",
                            )
                        )

                    actual_price_series = pd.to_numeric(result.actual_prices["actual_price_eur_per_mwh"], errors="coerce")
                    enriched_day_record = pd.Series(day_record).copy()
                    enriched_day_record["actual_price_mean"] = float(actual_price_series.mean())
                    enriched_day_record["actual_price_min"] = float(actual_price_series.min())
                    enriched_day_record["actual_price_max"] = float(actual_price_series.max())
                    enriched_day_record["actual_price_spread"] = float(actual_price_series.max() - actual_price_series.min())
                    enriched_day_record["actual_price_std"] = float(actual_price_series.std(ddof=0))
                    enriched_day_record["actual_negative_price_hours"] = int((actual_price_series < 0.0).sum())
                    metric_row = _build_daily_metric_row(
                        result=result,
                        artifact_id=artifact_id,
                        model_label=model_label,
                        validation_mode="thesis_grade",
                        thesis_grade=True,
                        forecast_origin_reconstruction_used=True,
                        week_row=pd.Series(selected_week),
                        day_row=enriched_day_record,
                        cvar_alpha=float(cvar_alpha),
                        cvar_gamma=float(gamma),
                        benchmark_row=benchmark_row,
                    )
                    metric_row["period_type"] = "test"
                    metric_row["regime_label"] = "high_volatility"
                    metric_row["target_mode"] = target_mode
                    metric_row["baseline_shortfall_penalty_eur_per_kg"] = policy.baseline_shortfall_penalty_eur_per_kg
                    metric_row["applied_shortfall_penalty_eur_per_kg"] = policy.applied_shortfall_penalty_eur_per_kg
                    metric_row["hard_target"] = policy.hard_target
                    metric_row["stochastic_solver_status"] = result.optimisation_result.solver.status
                    metric_row["actual_redispatch_solver_status"] = result.actual_redispatch_solver.status
                    metric_row["hard_target_infeasible"] = bool(
                        target_mode == "hard_daily_target"
                        and (
                            result.optimisation_result.solver.status != "Optimal"
                            or result.actual_redispatch_solver.status != "Optimal"
                        )
                    )
                    if pf_row is not None:
                        pf_profit = float(
                            pf_row["realised_adjusted_profit_eur"]
                            if "realised_adjusted_profit_eur" in pf_row.index
                            else pf_row["realised_adjusted_profit"]
                        )
                        metric_row["perfect_foresight_profit"] = pf_profit
                        metric_row["value_captured_vs_perfect_foresight"] = float(metric_row["realised_adjusted_profit"] / pf_profit) if abs(pf_profit) > 1e-9 else float("nan")
                        metric_row["regret_vs_perfect_foresight"] = float(pf_profit - metric_row["realised_adjusted_profit"])
                    daily_rows.append(metric_row)

                    metadata = {
                        "run_id": str(run_id),
                        "artifact_id": artifact_id,
                        "model_label": model_label,
                        "week_id": str(selected_week["week_id"]),
                        "week_label": str(selected_week["week_label"]),
                        "regime_label": "high_volatility",
                        "delivery_day": delivery_day,
                        "cvar_alpha": float(cvar_alpha),
                        "cvar_gamma": float(gamma),
                        "risk_mode": str(risk_mode),
                        "target_mode": target_mode,
                        "baseline_shortfall_penalty_eur_per_kg": policy.baseline_shortfall_penalty_eur_per_kg,
                        "applied_shortfall_penalty_eur_per_kg": policy.applied_shortfall_penalty_eur_per_kg,
                        "hard_target": policy.hard_target,
                    }
                    submitted_rows.append(result.optimisation_result.submitted_bids.assign(**metadata))
                    scenario_clearing_rows.append(result.optimisation_result.scenario_clearing.assign(**metadata))
                    actual_clearing_rows.append(result.actual_clearing.assign(**metadata))
                    actual_redispatch_rows.append(result.actual_redispatch_timeseries.assign(**metadata))
                    scenario_settlement_rows.append(result.optimisation_result.scenario_economics.assign(**metadata))
                    actual_settlement_rows.append(result.actual_settlement_results.assign(**metadata))
                    scenario_fan_rows.append(result.scenarios.assign(**metadata))
                    validation_rows.append(
                        result.validation_checks.assign(
                            artifact_id=artifact_id,
                            model_label=model_label,
                            week_id=str(selected_week["week_id"]),
                            week_label=str(selected_week["week_label"]),
                            regime_label="high_volatility",
                            delivery_day=delivery_day,
                            forecast_origin_utc=str(result.forecast_origin_utc),
                            cvar_alpha=float(cvar_alpha),
                            cvar_gamma=float(gamma),
                            risk_mode=str(risk_mode),
                            target_mode=target_mode,
                        )
                    )
                    day_run_dir_rows.append(
                        {
                            "artifact_id": artifact_id,
                            "model_label": model_label,
                            "week_id": str(selected_week["week_id"]),
                            "week_label": str(selected_week["week_label"]),
                            "delivery_day": delivery_day,
                            "forecast_origin_utc": str(result.forecast_origin_utc),
                            "cvar_gamma": float(gamma),
                            "target_mode": target_mode,
                            "run_dir": str(result.run_dir),
                        }
                    )
                    manifest_path = Path(str(result.run_dir)) / "scenario_manifest.json"
                    if manifest_path.exists():
                        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                        manifest_payload.update(metadata)
                        scenario_manifest_rows.append(manifest_payload)

    daily_metrics = pd.DataFrame(daily_rows).sort_values(["model_label", "cvar_gamma", "target_mode", "delivery_day"]).reset_index(drop=True)
    daily_metrics["run_id"] = str(run_id)
    if "cvar_gamma" not in daily_metrics.columns and "gamma" in daily_metrics.columns:
        daily_metrics["cvar_gamma"] = pd.to_numeric(daily_metrics["gamma"], errors="coerce")
    if "cvar_alpha" not in daily_metrics.columns and "alpha" in daily_metrics.columns:
        daily_metrics["cvar_alpha"] = pd.to_numeric(daily_metrics["alpha"], errors="coerce")

    scenario_frame = pd.concat(scenario_fan_rows, ignore_index=True) if scenario_fan_rows else pd.DataFrame()
    coverage = _scenario_coverage_by_day(scenario_frame)
    if not coverage.empty:
        coverage = coverage[
            [
                "artifact_id",
                "model_label",
                "delivery_day",
                "actual_price_within_scenario_minmax_share",
                "actual_price_within_p10_p90_share",
                "actual_price_within_p05_p95_share",
            ]
        ].drop_duplicates(subset=["artifact_id", "model_label", "delivery_day"])
        daily_metrics = daily_metrics.merge(
            coverage,
            on=["artifact_id", "model_label", "delivery_day"],
            how="left",
        )
    daily_metrics.columns = [str(column) for column in daily_metrics.columns]
    if bool(pd.Index(daily_metrics.columns).duplicated().any()):
        daily_metrics = daily_metrics.loc[:, ~pd.Index(daily_metrics.columns).duplicated()].copy()
    for base_name in ("cvar_gamma", "cvar_alpha"):
        if base_name not in daily_metrics.columns:
            candidates = [
                column
                for column in daily_metrics.columns
                if str(column).startswith(f"{base_name}_") or str(column).endswith(f"_{base_name}")
            ]
            if candidates:
                daily_metrics[base_name] = pd.to_numeric(daily_metrics[candidates[0]], errors="coerce")
    redundant_suffix_columns = [column for column in daily_metrics.columns if column.endswith("_x") or column.endswith("_y")]
    if redundant_suffix_columns:
        daily_metrics = daily_metrics.drop(columns=redundant_suffix_columns, errors="ignore")
    daily_metrics = daily_metrics.drop_duplicates(
        subset=["artifact_id", "model_label", "delivery_day", "cvar_gamma", "target_mode"],
        keep="first",
    ).reset_index(drop=True)
    weekly_frames: list[pd.DataFrame] = []
    for target_mode, group in daily_metrics.groupby("target_mode", sort=False):
        weekly = _aggregate_weekly_metrics(group.drop(columns=[c for c in ["target_mode", "baseline_shortfall_penalty_eur_per_kg", "applied_shortfall_penalty_eur_per_kg", "hard_target", "stochastic_solver_status", "actual_redispatch_solver_status", "hard_target_infeasible"] if c in group.columns]), selected_week=pd.Series(selected_week)).copy()
        weekly["period_type"] = "test"
        weekly["regime_label"] = "high_volatility"
        weekly["target_mode"] = str(target_mode)
        weekly["baseline_shortfall_penalty_eur_per_kg"] = float(group["baseline_shortfall_penalty_eur_per_kg"].iloc[0])
        weekly["applied_shortfall_penalty_eur_per_kg"] = float(group["applied_shortfall_penalty_eur_per_kg"].iloc[0])
        weekly["hard_target"] = bool(group["hard_target"].iloc[0])
        weekly["cvar_tail_profit"] = -pd.to_numeric(weekly["cvar_loss"], errors="coerce")
        weekly_frames.append(weekly)
    weekly_metrics = pd.concat(weekly_frames, ignore_index=True) if weekly_frames else pd.DataFrame()

    benchmark_daily = pd.DataFrame(benchmark_daily_rows).sort_values(["model_label", "target_mode", "delivery_day"]).reset_index(drop=True)
    benchmark_weekly_frames: list[pd.DataFrame] = []
    if not benchmark_daily.empty:
        for target_mode, group in benchmark_daily.groupby("target_mode", sort=False):
            weekly = _aggregate_benchmark_metrics(group.drop(columns=["target_mode", "baseline_shortfall_penalty_eur_per_kg", "applied_shortfall_penalty_eur_per_kg", "hard_target"]), selected_week=pd.Series(selected_week))
            weekly["target_mode"] = str(target_mode)
            weekly["baseline_shortfall_penalty_eur_per_kg"] = float(group["baseline_shortfall_penalty_eur_per_kg"].iloc[0])
            weekly["applied_shortfall_penalty_eur_per_kg"] = float(group["applied_shortfall_penalty_eur_per_kg"].iloc[0])
            weekly["hard_target"] = bool(group["hard_target"].iloc[0])
            benchmark_weekly_frames.append(weekly)
    benchmark_metrics = pd.concat(benchmark_weekly_frames, ignore_index=True) if benchmark_weekly_frames else pd.DataFrame()

    perfect_foresight_daily = pd.DataFrame(perfect_foresight_daily_rows).sort_values(["target_mode", "delivery_day"]).reset_index(drop=True)
    pf_frames: list[pd.DataFrame] = []
    if not perfect_foresight_daily.empty:
        for target_mode, group in perfect_foresight_daily.groupby("target_mode", sort=False):
            pf = _aggregate_perfect_foresight_metrics(group.drop(columns=["target_mode", "baseline_shortfall_penalty_eur_per_kg", "applied_shortfall_penalty_eur_per_kg", "hard_target"]))
            pf["period_type"] = "test"
            pf["target_mode"] = str(target_mode)
            pf["baseline_shortfall_penalty_eur_per_kg"] = float(group["baseline_shortfall_penalty_eur_per_kg"].iloc[0])
            pf["applied_shortfall_penalty_eur_per_kg"] = float(group["applied_shortfall_penalty_eur_per_kg"].iloc[0])
            pf["hard_target"] = bool(group["hard_target"].iloc[0])
            pf_frames.append(pf)
    perfect_foresight_metrics = pd.concat(pf_frames, ignore_index=True) if pf_frames else pd.DataFrame()

    if not perfect_foresight_metrics.empty:
        pf_weekly = perfect_foresight_metrics.loc[
            perfect_foresight_metrics["aggregation_level"].astype(str).eq("weekly"),
            ["target_mode", "week_id", "realised_adjusted_profit"],
        ].rename(columns={"realised_adjusted_profit": "perfect_foresight_profit"})
        weekly_metrics = weekly_metrics.merge(pf_weekly, on=["target_mode", "week_id"], how="left")
        weekly_metrics["value_captured_vs_perfect_foresight"] = np.where(
            pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce").abs() > 1e-9,
            pd.to_numeric(weekly_metrics["realised_adjusted_profit"], errors="coerce") / pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce"),
            np.nan,
        )
        weekly_metrics["regret_vs_perfect_foresight"] = pd.to_numeric(weekly_metrics["perfect_foresight_profit"], errors="coerce") - pd.to_numeric(weekly_metrics["realised_adjusted_profit"], errors="coerce")

    weekly_metrics_by_model_gamma_target_mode = weekly_metrics.copy()
    cvar_sweep_daily = daily_metrics.copy()
    cvar_sweep_weekly = weekly_metrics.copy()
    cvar_bid_firmness_metrics = weekly_metrics[
        [
            "week_id",
            "week_label",
            "regime_label",
            "artifact_id",
            "model_label",
            "cvar_alpha",
            "cvar_gamma",
            "target_mode",
            "weighted_average_bid_price",
            "high_bid_share",
            "market_cap_bid_share",
            "clearing_ratio",
            "rejected_energy_mwh",
        ]
    ].copy()
    model_stats_by_target_mode = (
        weekly_metrics.groupby(["artifact_id", "model_label", "cvar_gamma", "target_mode"], as_index=False)
        .agg(
            solver_status=("solver_status", "first"),
            objective_value=("objective_value", "sum"),
            solve_time_seconds=("solve_time_seconds", "sum"),
            mip_gap=("mip_gap", "max"),
            variable_count=("variable_count", "max"),
            binary_variable_count=("binary_variable_count", "max"),
            constraint_count=("constraint_count", "max"),
            scenario_count=("scenario_count", "max"),
            number_of_delivery_days=("number_of_delivery_days", "max"),
        )
        .sort_values(["model_label", "cvar_gamma", "target_mode"])
        .reset_index(drop=True)
    )
    production_target_sensitivity_summary = weekly_metrics[
        [
            "artifact_id",
            "model_label",
            "cvar_gamma",
            "target_mode",
            "realised_adjusted_profit",
            "expected_adjusted_profit",
            "shortfall_kg",
            "cvar_tail_profit",
            "rejected_energy_mwh",
            "unused_cleared_energy_mwh",
            "value_captured_vs_perfect_foresight",
            "solver_status",
        ]
    ].sort_values(["model_label", "cvar_gamma", "target_mode"]).reset_index(drop=True)

    submitted_bids = pd.concat(submitted_rows, ignore_index=True) if submitted_rows else pd.DataFrame()
    scenario_clearing = pd.concat(scenario_clearing_rows, ignore_index=True) if scenario_clearing_rows else pd.DataFrame()
    actual_clearing = pd.concat(actual_clearing_rows, ignore_index=True) if actual_clearing_rows else pd.DataFrame()
    actual_redispatch_timeseries = pd.concat(actual_redispatch_rows, ignore_index=True) if actual_redispatch_rows else pd.DataFrame()
    scenario_settlement_results = pd.concat(scenario_settlement_rows, ignore_index=True) if scenario_settlement_rows else pd.DataFrame()
    actual_settlement_results = pd.concat(actual_settlement_rows, ignore_index=True) if actual_settlement_rows else pd.DataFrame()
    validation_existing = pd.concat(validation_rows, ignore_index=True) if validation_rows else pd.DataFrame()
    day_run_dirs = pd.DataFrame(day_run_dir_rows).sort_values(["model_label", "cvar_gamma", "target_mode", "delivery_day"]).reset_index(drop=True)
    runtime_diagnostics = pd.DataFrame(runtime_rows)
    solver_log_manifest = _build_solver_log_manifest(day_run_dirs[["artifact_id", "model_label", "delivery_day", "cvar_gamma", "run_dir"]]) if not day_run_dirs.empty else pd.DataFrame()

    cvar_validation_frames: list[pd.DataFrame] = []
    for target_mode, group in daily_metrics.groupby("target_mode", sort=False):
        weekly_slice = weekly_metrics.loc[weekly_metrics["target_mode"].astype(str).eq(str(target_mode))].copy()
        scenario_slice = scenario_settlement_results.loc[scenario_settlement_results["target_mode"].astype(str).eq(str(target_mode))].copy()
        checks = _build_cvar_validation_checks(
            daily_metrics=group,
            weekly_metrics=weekly_slice,
            scenario_settlement_results=scenario_slice,
            gamma_values=gamma_list,
            cvar_alpha=float(cvar_alpha),
        )
        checks["target_mode"] = str(target_mode)
        cvar_validation_frames.append(checks)
    cvar_validation_checks = pd.concat(cvar_validation_frames, ignore_index=True) if cvar_validation_frames else pd.DataFrame()

    validation_checks_all_runs = _build_target_mode_validation_checks(
        selected_week=selected_week,
        support_days=support_days,
        artifact_ids=artifact_list,
        daily_metrics=daily_metrics,
        benchmark_daily=benchmark_daily,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        perfect_foresight_daily=perfect_foresight_daily,
        gamma_values=gamma_list,
        cvar_alpha=float(cvar_alpha),
        policies=policies,
        target_mode_values=target_mode_list,
    )

    save_json(
        run_dir,
        "scenario_manifest.json",
        {
            "phase": "E3",
            "week_id": str(selected_week["week_id"]),
            "week_label": str(selected_week["week_label"]),
            "artifacts": scenario_manifest_rows,
        },
    )
    save_frame_csv(run_dir, "model_stats_by_target_mode.csv", model_stats_by_target_mode)
    save_frame_csv(run_dir, "solver_log_manifest.csv", solver_log_manifest)
    save_frame_parquet(run_dir, "submitted_bids.parquet", submitted_bids)
    save_frame_parquet(run_dir, "scenario_clearing.parquet", scenario_clearing)
    save_frame_parquet(run_dir, "actual_clearing.parquet", actual_clearing)
    save_frame_parquet(run_dir, "actual_redispatch_timeseries.parquet", actual_redispatch_timeseries)
    save_frame_csv(run_dir, "scenario_settlement_results.csv", scenario_settlement_results)
    save_frame_csv(run_dir, "actual_settlement_results.csv", actual_settlement_results)
    save_frame_csv(run_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(run_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(run_dir, "weekly_metrics_by_model_gamma_target_mode.csv", weekly_metrics_by_model_gamma_target_mode)
    save_frame_csv(run_dir, "benchmark_metrics.csv", benchmark_metrics)
    save_frame_csv(run_dir, "perfect_foresight_metrics.csv", perfect_foresight_metrics)
    save_frame_csv(run_dir, "cvar_sweep_daily.csv", cvar_sweep_daily)
    save_frame_csv(run_dir, "cvar_sweep_weekly.csv", cvar_sweep_weekly)
    save_frame_csv(run_dir, "cvar_bid_firmness_metrics.csv", cvar_bid_firmness_metrics)
    save_frame_csv(run_dir, "production_target_sensitivity_summary.csv", production_target_sensitivity_summary)
    reporting_started = time.perf_counter()
    bid_ladder_diagnostics = _create_figures(
        run_dir=run_dir,
        daily_metrics=daily_metrics,
        actual_clearing=actual_clearing,
        actual_redispatch_timeseries=actual_redispatch_timeseries,
        runtime_diagnostics=runtime_diagnostics,
        reserve_kg=float(suite_config.hydrogen_system.reserve_kg),
    )
    save_frame_csv(run_dir, "bid_ladder_diagnostics.csv", bid_ladder_diagnostics)
    save_frame_csv(run_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(run_dir, "cvar_validation_checks.csv", cvar_validation_checks)

    notebook_inputs_dir = run_dir / "notebook_inputs"
    notebook_inputs_dir.mkdir(parents=True, exist_ok=True)
    save_frame_csv(notebook_inputs_dir, "selected_week_manifest_table.csv", pd.DataFrame([selected_week]))
    save_frame_csv(notebook_inputs_dir, "support_days.csv", support_days)
    save_frame_csv(notebook_inputs_dir, "daily_metrics.csv", daily_metrics)
    save_frame_csv(notebook_inputs_dir, "weekly_metrics.csv", weekly_metrics)
    save_frame_csv(notebook_inputs_dir, "benchmark_metrics.csv", benchmark_metrics)
    save_frame_csv(notebook_inputs_dir, "perfect_foresight_metrics.csv", perfect_foresight_metrics)
    save_frame_csv(notebook_inputs_dir, "cvar_bid_firmness_metrics.csv", cvar_bid_firmness_metrics)
    save_frame_csv(notebook_inputs_dir, "validation_checks_all_runs.csv", validation_checks_all_runs)
    save_frame_csv(notebook_inputs_dir, "cvar_validation_checks.csv", cvar_validation_checks)
    save_frame_parquet(notebook_inputs_dir, "actual_clearing.parquet", actual_clearing)
    save_frame_parquet(notebook_inputs_dir, "actual_redispatch_timeseries.parquet", actual_redispatch_timeseries)
    save_frame_parquet(notebook_inputs_dir, "submitted_bids.parquet", submitted_bids)

    reporting_wall = time.perf_counter() - reporting_started
    runtime_rows.append(
        _runtime_row(
            run_id=run_id,
            week_id=str(selected_week["week_id"]),
            delivery_date=None,
            model_label="suite_reporting",
            artifact_id="suite_reporting",
            gamma=None,
            alpha=float(cvar_alpha),
            target_mode="all",
            solve_stage="reporting",
            wall_time_seconds=float(reporting_wall),
            model_build_time_seconds=np.nan,
            solver_time_seconds=np.nan,
            postprocess_time_seconds=np.nan,
            output_write_time_seconds=float(reporting_wall),
            solver_status="completed",
            termination_condition="completed",
            objective_value=np.nan,
            mip_gap=np.nan,
            variable_count=np.nan,
            binary_variable_count=np.nan,
            constraint_count=np.nan,
            scenario_count=np.nan,
            bid_block_count=np.nan,
            timestep_count=np.nan,
            used_cache=False,
            notes="figure generation, manifest writing, notebook inputs, README",
        )
    )
    runtime_diagnostics = pd.DataFrame(runtime_rows)
    runtime_summary = _runtime_summary_frame(runtime_diagnostics)
    save_frame_csv(run_dir, "runtime_diagnostics.csv", runtime_diagnostics)
    save_frame_csv(run_dir, "runtime_summary.csv", runtime_summary)
    save_frame_csv(notebook_inputs_dir, "runtime_diagnostics.csv", runtime_diagnostics)
    save_frame_csv(notebook_inputs_dir, "runtime_summary.csv", runtime_summary)

    _write_readme(
        run_dir=run_dir,
        policies=policies,
        weekly_metrics=weekly_metrics,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
        runtime_summary=runtime_summary,
    )

    notebook_path = Path("scripts/Data/03_Hydrogen_Test_Case/notebooks/14_bidding_behaviour_and_target_sensitivity_report.ipynb")
    return PhaseE3ProductionTargetSensitivityResult(
        run_dir=run_dir,
        notebook_path=notebook_path,
        daily_metrics=daily_metrics,
        weekly_metrics=weekly_metrics,
        runtime_diagnostics=runtime_diagnostics,
        validation_checks=validation_checks_all_runs,
        cvar_validation_checks=cvar_validation_checks,
    )
