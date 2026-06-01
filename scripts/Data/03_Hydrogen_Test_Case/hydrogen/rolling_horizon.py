from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

from .benchmarks import STRATEGY_REGISTRY, StrategyResult
from .data_loader import filter_scenarios_to_period, resolve_execution_period
from .metrics import build_period_timeseries, compute_all_metrics
from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .plots import (
    plot_baseline_dispatch,
    plot_benchmark_comparison,
    plot_buffer_trajectory,
    plot_consumption_delta_vs_baseline,
    plot_consumption_quartiles,
    plot_cvar_frontier,
    plot_physical_balance,
    plot_price_scenario_operation,
    plot_strategy_comparison_dashboard,
)
from .run_registry import (
    create_run_folder,
    save_config_resolved,
    save_frame_csv,
    save_frame_parquet,
    save_inputs_manifest,
    save_json,
    save_text,
    write_manifest,
)
from .scenario_loader import load_all_scenarios
from .validation_checks import (
    collect_validation_report,
    validate_dispatch_physical,
    validate_economic_consistency,
    validate_gamma_selection,
    validate_model_stats,
    validate_scenario_table,
    validate_solver_statuses,
)


def _resolve_config(config_or_path: HydrogenConfig | str | Path) -> HydrogenConfig:
    if isinstance(config_or_path, HydrogenConfig):
        return config_or_path
    return load_hydrogen_config(config_or_path)


def _select_day_frame(model_frame: pd.DataFrame, local_day: str) -> pd.DataFrame:
    day_frame = model_frame[model_frame["delivery_day"].astype(str) == str(local_day)].copy()
    if day_frame.empty:
        return day_frame
    latest_origin = day_frame["forecast_origin_utc"].max()
    day_frame = day_frame[day_frame["forecast_origin_utc"] == latest_origin].copy()
    return day_frame.sort_values(["delivery_start_utc", "scenario_id"]).reset_index(drop=True)


def _run_one_strategy_for_day(
    *,
    strategy: str,
    day_frame: pd.DataFrame,
    config: HydrogenConfig,
    inventory_start_kg: float,
    reserve_kg: float,
    apply_terminal_value: bool,
    terminal_reference_start_kg: float,
    solver_log_path: str | None,
) -> StrategyResult:
    if strategy not in STRATEGY_REGISTRY:
        raise KeyError(f"Unknown strategy requested: {strategy}")
    runner = STRATEGY_REGISTRY[strategy]
    kwargs = {
        "day_frame": day_frame,
        "config": config,
        "inventory_start_kg": inventory_start_kg,
        "reserve_kg": reserve_kg,
        "apply_terminal_value": apply_terminal_value,
        "terminal_reference_start_kg": terminal_reference_start_kg,
        "solver_log_path": solver_log_path,
    }
    if strategy == "stochastic_cvar":
        kwargs["gamma"] = float(config.risk.gamma)
    return runner(**kwargs)


def run_hydrogen_backtest(config_or_path: HydrogenConfig | str | Path) -> dict[str, Any]:
    config = _resolve_config(config_or_path)
    started = perf_counter()

    scenario_table, artifact_specs, loader_warnings = load_all_scenarios(config)
    period = resolve_execution_period(config)
    period_scenarios = filter_scenarios_to_period(
        scenario_table,
        period=period,
        dataset_split=config.experiment.dataset_split,
    )
    run_id, run_dir = create_run_folder(config)
    save_config_resolved(run_dir, config)
    save_inputs_manifest(run_dir, [config.config_path, config.models.scenario_catalog, *[spec.path for spec in artifact_specs]])

    all_rows: list[pd.DataFrame] = []
    solver_status_rows: list[dict[str, Any]] = []
    model_stats_rows: list[dict[str, Any]] = []
    cvar_strategy_map: dict[str, float | None] = {}
    dispatch_checks_all: list[dict[str, str]] = []
    sample_dispatch_by_strategy: dict[str, pd.DataFrame] = {}
    sample_scenarios_by_strategy: dict[str, pd.DataFrame] = {}

    for model_id in sorted(period_scenarios["model_id"].astype(str).unique()):
        model_frame = period_scenarios[period_scenarios["model_id"].astype(str) == model_id].copy()
        inventory_by_strategy = {strategy: float(config.hydrogen_system.storage_initial_kg) for strategy in config.strategies}
        period_initial_by_strategy = dict(inventory_by_strategy)
        period_days = sorted(model_frame["delivery_day"].astype(str).unique().tolist())

        # TODO(milp-next): upgrade this D-only loop to D..D+4 rolling optimisation where only D is executed
        # and inventory is propagated from realised D execution.
        for day_idx, day_label in enumerate(period_days):
            day_frame = _select_day_frame(model_frame, day_label)
            if day_frame.empty:
                continue
            forecast_origin = pd.Timestamp(day_frame["forecast_origin_utc"].iloc[0])
            lead_day = int(day_frame["lead_day"].iloc[0])
            timestamps = (
                day_frame[["delivery_start_utc", "actual_price_eur_per_mwh", "point_forecast_eur_per_mwh"]]
                .drop_duplicates(subset=["delivery_start_utc"])
                .sort_values("delivery_start_utc")
            )
            actual_prices = timestamps["actual_price_eur_per_mwh"].astype(float).reset_index(drop=True)
            point_prices = timestamps["point_forecast_eur_per_mwh"].astype(float).reset_index(drop=True)

            for strategy in config.strategies:
                apply_terminal = day_idx == len(period_days) - 1
                inventory_start_for_day = inventory_by_strategy[strategy]
                terminal_ref_start = (
                    period_initial_by_strategy[strategy] if apply_terminal else inventory_start_for_day
                )
                strategy_result = _run_one_strategy_for_day(
                    strategy=strategy,
                    day_frame=day_frame,
                    config=config,
                    inventory_start_kg=inventory_start_for_day,
                    reserve_kg=config.hydrogen_system.reserve_kg,
                    apply_terminal_value=apply_terminal,
                    terminal_reference_start_kg=terminal_ref_start,
                    solver_log_path=str(run_dir / "solver_log.txt") if config.outputs.save_solver_log else None,
                )
                dispatch = strategy_result.dispatch.copy()
                dispatch["actual_price_eur_per_mwh"] = actual_prices.to_numpy()
                dispatch["point_forecast_eur_per_mwh"] = point_prices.to_numpy()
                dispatch["electrolyser_electricity_mwh"] = dispatch["P_el_mw"].astype(float)
                dispatch["compressor_electricity_mwh"] = dispatch["P_comp_mw"].astype(float)
                dispatch["total_electricity_mwh"] = (
                    dispatch["electrolyser_electricity_mwh"].astype(float) + dispatch["compressor_electricity_mwh"].astype(float)
                )
                inventory_by_strategy[strategy] = float(dispatch["H_buf_kg"].iloc[-1])
                cvar_strategy_map[strategy] = strategy_result.optimisation_cvar

                day_timeseries = build_period_timeseries(
                    dispatch=dispatch,
                    actual_prices=actual_prices,
                    point_forecast=point_prices,
                    strategy=strategy,
                    model_id=model_id,
                    delivery_day=str(day_label),
                    forecast_origin_utc=forecast_origin,
                    lead_day=lead_day,
                    shortfall_kg=float(dispatch["shortfall_kg"].iloc[0]),
                    objective_value_eur=strategy_result.objective_value,
                    solver_status=strategy_result.solver_status,
                    market_model_type=strategy_result.market_model_type,
                )
                day_timeseries["scenario_id"] = pd.NA
                day_timeseries["scenario_probability"] = pd.NA
                day_timeseries["terminal_reference_start_kg"] = terminal_ref_start if apply_terminal else pd.NA
                day_timeseries["terminal_applied_flag"] = bool(apply_terminal)
                all_rows.append(day_timeseries)

                solver_status_rows.append(
                    {
                        "model_id": model_id,
                        "delivery_day": day_label,
                        "strategy": strategy,
                        "solver_status": strategy_result.solver_status,
                        "solver_runtime_seconds": strategy_result.solver_runtime_seconds,
                        "solver_name": strategy_result.solver_name,
                        "solver_package": strategy_result.solver_package,
                        "objective_value_eur": strategy_result.objective_value,
                    }
                )
                if strategy_result.model_stats is not None:
                    model_stats_rows.append(
                        {
                            "model_id": model_id,
                            "delivery_day": day_label,
                            "strategy": strategy,
                            "market_model_type": strategy_result.market_model_type,
                            "variable_count": strategy_result.model_stats.variable_count,
                            "binary_variable_count": strategy_result.model_stats.binary_variable_count,
                            "constraint_count": strategy_result.model_stats.constraint_count,
                            "scenario_count": strategy_result.model_stats.scenario_count,
                            "horizon_steps": strategy_result.model_stats.horizon_steps,
                            "timestep_hours": strategy_result.model_stats.timestep_hours,
                        }
                    )
                checks = validate_dispatch_physical(
                    dispatch,
                    config=config,
                    reserve_kg=config.hydrogen_system.reserve_kg,
                    inventory_start_kg=inventory_start_for_day,
                )
                for check in checks:
                    check["check_name"] = f"{strategy}.{check['check_name']}"
                dispatch_checks_all.extend(checks)
                if strategy not in sample_dispatch_by_strategy:
                    sample_dispatch_by_strategy[strategy] = dispatch.copy()
                    sample_scenarios_by_strategy[strategy] = day_frame.copy()

    if not all_rows:
        raise RuntimeError("No daily runs were executed. Check model IDs, selected period, and scenario inputs.")

    timeseries = pd.concat(all_rows, ignore_index=True)
    timeseries["electricity_cost_eur"] = (
        timeseries["actual_price_eur_per_mwh"].astype(float)
        * (timeseries["P_el_mw"].astype(float) + timeseries["P_comp_mw"].astype(float))
        * config.delta_t_hours
    )
    timeseries["revenue_eur"] = config.economics.h2_sale_price_eur_per_kg * timeseries["H_comp_kg"].astype(float)
    timeseries["shortfall_penalty_eur_contrib"] = 0.0
    timeseries["terminal_inventory_value_eur_contrib"] = 0.0

    group_cols = ["strategy", "model_id", "delivery_day"]
    for _, grp in timeseries.groupby(group_cols):
        idx_last = grp.index[-1]
        shortfall_kg = float(grp["shortfall_kg"].max())
        timeseries.loc[idx_last, "shortfall_penalty_eur_contrib"] = shortfall_kg * config.economics.shortfall_penalty_eur_per_kg
        if bool(grp["terminal_applied_flag"].iloc[-1]) and pd.notna(grp["terminal_reference_start_kg"].iloc[-1]):
            terminal = config.terminal_inventory_value_per_kg * (
                float(grp["H_buf_kg"].iloc[-1]) - float(grp["terminal_reference_start_kg"].iloc[-1])
            )
            timeseries.loc[idx_last, "terminal_inventory_value_eur_contrib"] = terminal
    timeseries["adjusted_profit_contribution_eur"] = (
        timeseries["revenue_eur"]
        - timeseries["electricity_cost_eur"]
        - timeseries["shortfall_penalty_eur_contrib"]
        + timeseries["terminal_inventory_value_eur_contrib"]
    )

    q_pivot = (
        period_scenarios.groupby(["model_id", "delivery_start_utc"], as_index=False)
        .agg(
            scenario_q05_eur_per_mwh=("scenario_price_eur_per_mwh", lambda s: float(s.quantile(0.05))),
            scenario_q50_eur_per_mwh=("scenario_price_eur_per_mwh", lambda s: float(s.quantile(0.50))),
            scenario_q95_eur_per_mwh=("scenario_price_eur_per_mwh", lambda s: float(s.quantile(0.95))),
        )
    )
    if not q_pivot.empty:
        timeseries = timeseries.merge(q_pivot, on=["model_id", "delivery_start_utc"], how="left")

    summary, metrics_by_day, metrics_by_week, cvar_summary = compute_all_metrics(
        timeseries=timeseries,
        scenario_period=period_scenarios,
        cvar_by_strategy=cvar_strategy_map,
        config=config,
    )

    scenario_checks = validate_scenario_table(period_scenarios)
    economic_checks = validate_economic_consistency(summary)
    solver_checks = validate_solver_statuses(pd.DataFrame(solver_status_rows))
    model_stats_checks = validate_model_stats(pd.DataFrame(model_stats_rows))
    gamma_checks = validate_gamma_selection(
        selection_split=config.risk.gamma_selection,
        evaluation_split=config.experiment.dataset_split,
    )
    validation_report = collect_validation_report(
        scenario_checks=scenario_checks,
        dispatch_checks=dispatch_checks_all,
        economic_checks=economic_checks,
        solver_checks=solver_checks,
        model_stats_checks=model_stats_checks,
        gamma_checks=gamma_checks,
    )

    if config.outputs.save_timeseries:
        save_frame_parquet(run_dir, "results_timeseries.parquet", timeseries)
    save_frame_csv(run_dir, "results_summary.csv", summary)
    save_frame_csv(run_dir, "metrics_by_day.csv", metrics_by_day)
    save_frame_csv(run_dir, "metrics_by_week.csv", metrics_by_week)
    save_frame_csv(run_dir, "cvar_summary.csv", cvar_summary)
    save_frame_csv(run_dir, "validation_checks.csv", validation_report)
    save_frame_csv(run_dir, "solver_statuses.csv", pd.DataFrame(solver_status_rows))
    model_stats_frame = pd.DataFrame(model_stats_rows)
    save_frame_csv(run_dir, "model_stats.csv", model_stats_frame)
    save_json(
        run_dir,
        "model_stats.json",
        {
            "rows": model_stats_rows,
            "max_variable_count": int(model_stats_frame["variable_count"].max()) if not model_stats_frame.empty else 0,
            "max_binary_variable_count": int(model_stats_frame["binary_variable_count"].max()) if not model_stats_frame.empty else 0,
            "max_constraint_count": int(model_stats_frame["constraint_count"].max()) if not model_stats_frame.empty else 0,
        },
    )

    strategy_summary_table = summary[
        [
            "strategy",
            "model_id",
            "market_model_type",
            "objective_value_eur",
            "adjusted_net_profit_eur",
            "compressed_hydrogen_kg",
            "target_fulfilment_pct",
            "average_price_paid_eur_per_mwh",
            "terminal_inventory_value_eur",
            "solver_status",
        ]
    ].copy()
    strategy_summary_table = strategy_summary_table.rename(
        columns={
            "compressed_hydrogen_kg": "hydrogen_produced_or_sold_kg",
        }
    )
    save_frame_csv(run_dir, "strategy_summary_table.csv", strategy_summary_table)

    figure_paths: list[str] = []
    if config.outputs.save_figures and sample_dispatch_by_strategy:
        figures_dir = run_dir / "figures"
        baseline_strategy = (
            "stochastic_risk_neutral"
            if "stochastic_risk_neutral" in sample_dispatch_by_strategy
            else next(iter(sample_dispatch_by_strategy))
        )
        sample_dispatch = sample_dispatch_by_strategy[baseline_strategy]
        sample_scenarios = sample_scenarios_by_strategy[baseline_strategy]
        figure_paths.append(str(plot_price_scenario_operation(scenario_period=sample_scenarios, dispatch=sample_dispatch, output_dir=figures_dir)))
        figure_paths.append(
            str(
                plot_buffer_trajectory(
                    dispatch=sample_dispatch,
                    reserve_kg=config.hydrogen_system.reserve_kg,
                    buffer_capacity_kg=config.hydrogen_system.storage_capacity_kg,
                    daily_target_kg=config.economics.daily_target_kg,
                    output_dir=figures_dir,
                )
            )
        )
        figure_paths.append(str(plot_strategy_comparison_dashboard(summary=summary, output_dir=figures_dir)))
        figure_paths.append(str(plot_consumption_quartiles(summary=summary, output_dir=figures_dir)))
        figure_paths.append(str(plot_baseline_dispatch(dispatch=sample_dispatch, output_dir=figures_dir)))
        figure_paths.append(str(plot_physical_balance(dispatch=sample_dispatch, output_dir=figures_dir)))
        figure_paths.append(str(plot_benchmark_comparison(summary=summary, output_dir=figures_dir)))
        delta_plot = plot_consumption_delta_vs_baseline(timeseries=timeseries, strategy="stochastic_cvar", output_dir=figures_dir)
        if delta_plot is not None:
            figure_paths.append(str(delta_plot))
        frontier_plot = plot_cvar_frontier(cvar_sweep=pd.DataFrame(), output_dir=figures_dir)
        if frontier_plot is not None:
            figure_paths.append(str(frontier_plot))

    runtime_seconds = perf_counter() - started
    warnings = list(loader_warnings)
    solver_packages = sorted({str(row.get("solver_package", "")) for row in solver_status_rows if row.get("solver_package")})
    solver_names = sorted({str(row.get("solver_name", "")) for row in solver_status_rows if row.get("solver_name")})
    manifest = write_manifest(
        run_dir=run_dir,
        run_id=run_id,
        config=config,
        scenario_paths=[spec.path for spec in artifact_specs],
        selected_period=period.as_manifest_record(),
        model_ids=sorted(period_scenarios["model_id"].astype(str).unique().tolist()),
        solver_package=solver_packages[0] if len(solver_packages) == 1 else ",".join(solver_packages) if solver_packages else "unknown",
        solver_name=solver_names[0] if len(solver_names) == 1 else ",".join(solver_names) if solver_names else "unknown",
        solver_statuses=solver_status_rows,
        runtime_seconds=runtime_seconds,
        warnings=warnings,
    )
    run_summary = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "runtime_seconds": float(runtime_seconds),
        "strategies": list(config.strategies),
        "models": sorted(period_scenarios["model_id"].astype(str).unique().tolist()),
        "period": period.as_manifest_record(),
        "validation_checks_path": str(run_dir / "validation_checks.csv"),
        "figure_paths": figure_paths,
        "manifest_path": str(manifest),
    }
    save_json(run_dir, "run_summary.json", run_summary)

    if config.outputs.save_solver_log:
        text = pd.DataFrame(solver_status_rows).to_csv(index=False)
        save_text(run_dir, "solver_log.txt", text)

    return {
        "run_id": run_id,
        "run_dir": run_dir,
        "summary": summary,
        "metrics_by_day": metrics_by_day,
        "metrics_by_week": metrics_by_week,
        "cvar_summary": cvar_summary,
        "validation_checks": validation_report,
        "timeseries": timeseries,
    }


def run_cvar_gamma_validation_sweep(
    *,
    config_or_path: HydrogenConfig | str | Path,
    gamma_grid: list[float] | None = None,
) -> pd.DataFrame:
    config = _resolve_config(config_or_path)
    sweep_values = gamma_grid or list(config.risk.gamma_grid)
    rows: list[dict[str, Any]] = []
    for gamma in sweep_values:
        updated = replace(config, risk=replace(config.risk, gamma=float(gamma)))
        result = run_hydrogen_backtest(updated)
        summary = result["summary"]
        cvar = summary[summary["strategy"] == "stochastic_cvar"].head(1)
        if cvar.empty:
            continue
        rows.append(
            {
                "gamma": float(gamma),
                "adjusted_net_profit_eur": float(cvar["adjusted_net_profit_eur"].iloc[0]),
                "realised_empirical_CVaR": float(cvar["realised_empirical_CVaR"].iloc[0]),
                "optimisation_CVaR": float(cvar["optimisation_CVaR"].iloc[0]) if pd.notna(cvar["optimisation_CVaR"].iloc[0]) else float("nan"),
                "run_id": result["run_id"],
                "run_dir": str(result["run_dir"]),
            }
        )
    return pd.DataFrame(rows).sort_values("gamma").reset_index(drop=True)
