from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from hydrogen.bidding_backtest import RealScenarioBiddingDryRunResult
from hydrogen.optimisation_model import ModelStats, SolverResult
from hydrogen.plant_parameters import load_hydrogen_config
import hydrogen.production_target_sensitivity as phase_e3


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_summary_frame(
    *,
    metrics_row: pd.Series,
    submitted_bids: pd.DataFrame,
    model_stats: dict[str, Any],
) -> pd.DataFrame:
    submitted_energy = float(submitted_bids["bid_quantity_mw"].astype(float).sum())
    weighted_average_bid_price = float(
        (
            submitted_bids["bid_price_eur_per_mwh"].astype(float)
            * submitted_bids["bid_quantity_mw"].astype(float)
        ).sum()
        / submitted_energy
    ) if submitted_energy > 0.0 else float("nan")
    high_bid_share = float(
        submitted_bids.loc[
            submitted_bids["bid_price_eur_per_mwh"].astype(float) >= 250.0,
            "bid_quantity_mw",
        ].astype(float).sum()
        / submitted_energy
    ) if submitted_energy > 0.0 else 0.0
    return pd.DataFrame(
        [
            {
                "weighted_average_bid_price_eur_per_mwh": weighted_average_bid_price,
                "high_bid_energy_share_ge_250": high_bid_share,
                "worst_scenario_profit": float(metrics_row["worst_scenario_profit_eur"]),
                "worst_scenario_loss": float(metrics_row["worst_scenario_loss_eur"]),
                "VaR_loss_zeta": float(metrics_row["var_loss_eur"]),
                "CVaR_loss": float(metrics_row["cvar_loss_eur"]),
                "solver_status": str(metrics_row["solver_status"]),
                "objective_with_regularisation": float(metrics_row["objective_with_regularisation"]),
                "solve_time_seconds": float(metrics_row["solve_time_seconds"]),
                "variable_count": int(model_stats["variable_count"]),
                "binary_variable_count": int(model_stats["binary_variable_count"]),
                "constraint_count": int(model_stats["constraint_count"]),
            }
        ]
    )


def _build_solver_result(
    *,
    metrics_row: pd.Series,
    model_stats: dict[str, Any],
    mip_gap: float,
    objective_key: str,
) -> tuple[SolverResult, ModelStats]:
    return (
        SolverResult(
            status=str(metrics_row["solver_status"]),
            objective_value=float(metrics_row[objective_key]) if objective_key in metrics_row.index and pd.notna(metrics_row[objective_key]) else None,
            runtime_seconds=float(metrics_row["solve_time_seconds"]),
            mip_gap=float(mip_gap),
            solver_package="cached",
            solver_name="cached_day_run",
            termination_condition=str(metrics_row["solver_status"]),
        ),
        ModelStats(
            variable_count=int(model_stats["variable_count"]),
            binary_variable_count=int(model_stats["binary_variable_count"]),
            constraint_count=int(model_stats["constraint_count"]),
            scenario_count=int(model_stats["scenario_count"]),
            horizon_steps=int(model_stats["horizon_steps"]),
            timestep_hours=float(model_stats["timestep_hours"]),
        ),
    )


def _reconstruct_scenarios(
    *,
    input_manifest: dict[str, Any],
    scenario_clearing: pd.DataFrame,
    actual_clearing: pd.DataFrame,
) -> pd.DataFrame:
    scenarios = (
        scenario_clearing[
            [
                "forecast_origin_utc",
                "scenario_id",
                "scenario_probability",
                "delivery_start_utc",
                "scenario_price_eur_per_mwh",
            ]
        ]
        .drop_duplicates()
        .sort_values(["scenario_id", "delivery_start_utc"])
        .reset_index(drop=True)
    )
    actual_prices = (
        actual_clearing[["delivery_start_utc", "actual_price_eur_per_mwh"]]
        .drop_duplicates()
        .sort_values("delivery_start_utc")
        .reset_index(drop=True)
    )
    scenarios = scenarios.merge(actual_prices, on="delivery_start_utc", how="left")
    scenarios["model_id"] = str(input_manifest["selected_model_id"])
    scenarios["delivery_day"] = str(input_manifest["selected_delivery_day"])
    scenarios["lead_day"] = 0
    return scenarios


def _build_cache_index(cache_root: Path) -> dict[tuple[str, str, float, str, str], Path]:
    index: dict[tuple[str, str, float, str, str], Path] = {}
    for manifest_path in cache_root.rglob("input_manifest.json"):
        run_dir = manifest_path.parent
        if run_dir.parent == cache_root:
            continue
        payload = _load_json(manifest_path)
        target_tag = run_dir.parent.name
        key = (
            str(payload["artifact_id"]),
            pd.Timestamp(payload["selected_forecast_origin_utc"]).isoformat(),
            float(payload["cvar_gamma"]),
            str(payload["risk_measure"]),
            str(target_tag),
        )
        previous = index.get(key)
        if previous is None or run_dir.name > previous.name:
            index[key] = run_dir
    return index


def _make_cached_loader(
    *,
    cache_root: Path,
) -> Any:
    cache_index = _build_cache_index(cache_root)

    def _loader(
        *,
        config: Any,
        artifact_id: str,
        forecast_origin_utc: str | None = None,
        max_origins: int = 1,
        output_root: Path | None = None,
        strategy_name: str = "stochastic_bid_risk_neutral",
        dry_run_label: str = "integration_candidate",
        include_price_insensitive_comparison: bool = True,
        risk_measure: str = "risk_neutral",
        cvar_alpha: float | None = None,
        cvar_gamma: float = 0.0,
        production_target_mode: str = "current_soft_target",
        shortfall_penalty_eur_per_kg: float | None = None,
        write_outputs: bool = True,
    ) -> RealScenarioBiddingDryRunResult:
        del max_origins, output_root, strategy_name, dry_run_label, include_price_insensitive_comparison
        del cvar_alpha, shortfall_penalty_eur_per_kg, write_outputs
        forecast_origin = pd.Timestamp(forecast_origin_utc).isoformat()
        key = (
            str(artifact_id),
            forecast_origin,
            float(cvar_gamma),
            str(risk_measure),
            phase_e3._target_mode_tag(production_target_mode),
        )
        if key not in cache_index:
            raise FileNotFoundError(f"No cached day run found for {key!r} in {cache_root}.")
        run_dir = cache_index[key]
        input_manifest = _load_json(run_dir / "input_manifest.json")
        model_stats_payload = _load_json(run_dir / "model_stats.json")

        submitted_bids = pd.read_parquet(run_dir / "submitted_bids.parquet")
        scenario_clearing = pd.read_parquet(run_dir / "scenario_clearing.parquet")
        actual_clearing = pd.read_parquet(run_dir / "actual_clearing.parquet")
        actual_redispatch = pd.read_parquet(run_dir / "actual_redispatch_timeseries.parquet")
        scenario_objective_summary = pd.read_csv(run_dir / "scenario_objective_summary.csv")
        scenario_settlement = pd.read_csv(run_dir / "scenario_settlement_results.csv")
        metrics_summary = pd.read_csv(run_dir / "metrics_summary.csv")
        actual_settlement = pd.read_csv(run_dir / "actual_settlement_results.csv")
        validation_checks = pd.read_csv(run_dir / "validation_checks.csv")
        sanity_summary = pd.read_csv(run_dir / "real_scenario_dry_run_sanity_summary.csv")
        scenarios = _reconstruct_scenarios(
            input_manifest=input_manifest,
            scenario_clearing=scenario_clearing,
            actual_clearing=actual_clearing,
        )
        actual_prices = (
            actual_clearing[["delivery_start_utc", "actual_price_eur_per_mwh"]]
            .drop_duplicates()
            .sort_values("delivery_start_utc")
            .reset_index(drop=True)
        )
        stochastic_solver, stochastic_model_stats = _build_solver_result(
            metrics_row=metrics_summary.iloc[0],
            model_stats=model_stats_payload["stochastic_bidding_model"],
            mip_gap=float(config.solver.mip_gap),
            objective_key="objective_with_regularisation",
        )
        redispatch_solver, redispatch_model_stats = _build_solver_result(
            metrics_row=actual_settlement.iloc[0],
            model_stats=model_stats_payload["actual_redispatch_model"],
            mip_gap=float(config.solver.mip_gap),
            objective_key="objective_value",
        )
        optimisation_result = SimpleNamespace(
            submitted_bids=submitted_bids,
            scenario_clearing=scenario_clearing,
            scenario_economics=scenario_settlement,
            summary=_build_summary_frame(
                metrics_row=metrics_summary.iloc[0],
                submitted_bids=submitted_bids,
                model_stats=model_stats_payload["stochastic_bidding_model"],
            ),
            solver=stochastic_solver,
            model_stats=stochastic_model_stats,
        )
        return SimpleNamespace(
            artifact_id=str(artifact_id),
            forecast_origin_utc=pd.Timestamp(input_manifest["selected_forecast_origin_utc"]),
            delivery_day=str(input_manifest["selected_delivery_day"]),
            scenarios=scenarios,
            actual_prices=actual_prices,
            optimisation_result=optimisation_result,
            actual_clearing=actual_clearing,
            actual_clearing_by_hour=pd.read_parquet(run_dir / "actual_clearing_by_hour.parquet"),
            actual_redispatch_timeseries=actual_redispatch,
            actual_settlement_results=actual_settlement,
            actual_redispatch_solver=redispatch_solver,
            actual_redispatch_model_stats=redispatch_model_stats,
            scenario_objective_summary=scenario_objective_summary,
            metrics_summary=metrics_summary,
            validation_checks=validation_checks,
            sanity_summary=sanity_summary,
            benchmark_comparison=pd.DataFrame(),
            run_dir=run_dir,
        )

    return _loader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recover Phase E3 outputs from cached day runs.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--week-id", default=phase_e3.DEFAULT_WEEK_ID)
    parser.add_argument("--artifacts", nargs="+", required=True)
    parser.add_argument("--alpha", type=float, default=float(phase_e3.DEFAULT_ALPHA))
    parser.add_argument("--gammas", nargs="+", type=float, default=list(phase_e3.DEFAULT_GAMMAS))
    parser.add_argument("--target-modes", nargs="+", required=True)
    parser.add_argument("--high-shortfall-penalty-rule", default="max_10x_current_or_200_eur_per_kg")
    parser.add_argument("--include-price-insensitive-benchmark", default="true")
    parser.add_argument("--include-perfect-foresight-benchmark", default="true")
    parser.add_argument("--run-slug", required=True)
    return parser


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def main() -> None:
    args = build_parser().parse_args()
    config = load_hydrogen_config(args.config)
    cached_loader = _make_cached_loader(
        cache_root=Path(args.cache_root),
    )
    original_loader = phase_e3.run_real_scenario_bidding_dry_run
    try:
        phase_e3.run_real_scenario_bidding_dry_run = cached_loader
        result = phase_e3.run_production_target_sensitivity(
            config=config,
            week_id=str(args.week_id),
            artifact_ids=[str(value) for value in args.artifacts],
            cvar_alpha=float(args.alpha),
            gamma_values=[float(value) for value in args.gammas],
            target_modes=[str(value) for value in args.target_modes],
            high_shortfall_penalty_rule=str(args.high_shortfall_penalty_rule),
            include_price_insensitive_benchmark=_parse_bool(args.include_price_insensitive_benchmark),
            include_perfect_foresight_benchmark=_parse_bool(args.include_perfect_foresight_benchmark),
            run_slug=str(args.run_slug),
        )
    finally:
        phase_e3.run_real_scenario_bidding_dry_run = original_loader
    print("run_dir=", result.run_dir)
    print("notebook_path=", result.notebook_path)
    print("daily_rows=", int(result.daily_metrics.shape[0]))
    print("weekly_rows=", int(result.weekly_metrics.shape[0]))


if __name__ == "__main__":
    main()
