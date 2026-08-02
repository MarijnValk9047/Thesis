from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd
import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from hydrogen.horizon_granularity_comparison import (
    SCENARIO_UNDERCOVERAGE_WARNING,
    _read_actuals,
    _read_scenarios,
    _resolved,
    build_comparison_tables,
    load_comparison_config,
    resolved_hydrogen_config,
    run_rolling_policy,
    validate_support_contract,
    write_run_governance,
)
from hydrogen.horizon_granularity_metrics import (
    build_hourly_donly_point_metrics,
    build_hourly_donly_scenario_metrics,
    create_thesis_figures,
)
from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.optimisation.input_resolver import InputSliceRequest, resolve_input_slice


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the governed Strict LEAR horizon/granularity hydrogen comparison.")
    parser.add_argument(
        "--config",
        default="scripts/Data/03_Hydrogen_Test_Case/configs/strict_lear_horizon_granularity_comparison.yaml",
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument("--episodes", nargs="*", default=[])
    parser.add_argument("--configurations", nargs="*", default=[])
    parser.add_argument("--policies", nargs="*", default=[])
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def _code_version(repo_root: Path) -> dict[str, Any]:
    def command(*args: str) -> str:
        try:
            return subprocess.check_output(args, cwd=repo_root, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return "unknown"

    return {
        "git_commit": command("git", "rev-parse", "HEAD"),
        "git_branch": command("git", "branch", "--show-current"),
        "git_dirty": bool(command("git", "status", "--porcelain")),
        "python": sys.version,
    }


def _write_checkpoint(path: Path, frames: list[pd.DataFrame]) -> None:
    if frames:
        pd.concat(frames, ignore_index=True).to_parquet(path, index=False)


def _comparability_contract(
    *, base_config: Any, comparison_config: dict[str, Any], repo_root: Path
) -> tuple[dict[str, Any], str]:
    payload = {
        "hydrogen_system": asdict(base_config.hydrogen_system),
        "economics": asdict(base_config.economics),
        "production": asdict(base_config.production),
        "bidding": asdict(base_config.bidding),
        "risk": {
            "measure": comparison_config["risk_measure"],
            "alpha": comparison_config["cvar_alpha"],
            "gamma": comparison_config["cvar_gamma"],
        },
        "quota": {
            "policy": comparison_config["weekly_quota_policy"],
            "daily_target_kg": comparison_config["daily_target_kg"],
        },
        "emergency_import_price_eur_per_mwh": comparison_config[
            "emergency_import_price_eur_per_mwh"
        ],
        "settlement_code_sha256": {
            name: hashlib.sha256((repo_root / relative).read_bytes()).hexdigest()
            for name, relative in {
                "clearing": "scripts/Data/03_Hydrogen_Test_Case/hydrogen/clearing.py",
                "redispatch": "scripts/Data/03_Hydrogen_Test_Case/hydrogen/redispatch.py",
            }.items()
        },
    }
    serialized = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return payload, hashlib.sha256(serialized).hexdigest()


def _artifact_inventory(*roots: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for root in roots:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            rows.append(
                {
                    "root": str(root),
                    "relative_path": str(path.relative_to(root)),
                    "size_bytes": int(path.stat().st_size),
                }
            )
    return pd.DataFrame(rows)


def _copy_forecast_metrics(forecast_root: Path, comparison_dir: Path) -> None:
    for name in (
        "point_forecast_metrics.csv",
        "point_forecast_improvements.csv",
        "scenario_metrics_summary.csv",
        "scenario_metrics_by_origin.csv",
        "scenario_reduction_effects.csv",
        "thesis_body_scenario_table.csv",
        "thesis_appendix_scenario_table.csv",
    ):
        source = forecast_root / name
        if source.exists():
            shutil.copy2(source, comparison_dir / name)


def _oracle_gate(aggregate: pd.DataFrame, tolerance: float = 1e-5) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (episode, configuration), group in aggregate.groupby(["episode_id", "configuration"]):
        lookup = group.set_index("policy")["realised_adjusted_profit_eur"]
        if "true_pf" not in lookup:
            continue
        for policy, value in lookup.items():
            if policy == "true_pf":
                continue
            difference = float(lookup["true_pf"] - value)
            rows.append(
                {
                    "episode_id": episode,
                    "configuration": configuration,
                    "policy": policy,
                    "pf_minus_policy_eur": difference,
                    "passed": difference >= -tolerance,
                }
            )
    return pd.DataFrame(rows)


def _state_carryover_checks(daily: pd.DataFrame, tolerance: float = 1e-8) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in daily.groupby(["episode_id", "configuration", "policy"]):
        ordered = group.sort_values("delivery_day").reset_index(drop=True)
        storage_diff = (ordered["storage_start_kg"].iloc[1:].to_numpy() - ordered["storage_end_kg"].iloc[:-1].to_numpy())
        power_diff = (
            ordered["electrolyser_power_start_mw"].iloc[1:].to_numpy()
            - ordered["electrolyser_power_end_mw"].iloc[:-1].to_numpy()
        )
        rows.append(
            {
                "episode_id": keys[0],
                "configuration": keys[1],
                "policy": keys[2],
                "max_storage_carryover_difference": float(abs(storage_diff).max()) if len(storage_diff) else 0.0,
                "max_power_carryover_difference": float(abs(power_diff).max()) if len(power_diff) else 0.0,
                "initial_storage_kg": float(ordered["storage_start_kg"].iloc[0]),
                "passed": bool(
                    (not len(storage_diff) or abs(storage_diff).max() <= tolerance)
                    and (not len(power_diff) or abs(power_diff).max() <= tolerance)
                    and abs(float(ordered["storage_start_kg"].iloc[0]) - 5000.0) <= tolerance
                ),
            }
        )
    return pd.DataFrame(rows)


def _weekly_quota_table(metadata: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in metadata.to_dict(orient="records"):
        realised = record["weekly_quota_realised_kg"]
        required = record["weekly_quota_required_kg"]
        for week_id, required_kg in required.items():
            realised_kg = float(realised.get(week_id, 0.0))
            rows.append(
                {
                    "episode_id": record["episode_id"],
                    "configuration": record["configuration"],
                    "policy": record["policy"],
                    "week_id": week_id,
                    "required_kg": float(required_kg),
                    "realised_kg": realised_kg,
                    "surplus_kg": realised_kg - float(required_kg),
                    "fulfilled": realised_kg + 1e-6 >= float(required_kg),
                }
            )
    return pd.DataFrame(rows)


def _resolve_scenario_set(
    *, hydrogen_config: Any, artifact_id: str, lead_days: list[int], cache_root: Path
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    resolved = resolve_input_slice(
        hydrogen_config,
        request=InputSliceRequest(
            artifact_id=artifact_id,
            start_local_date="2026-03-18",
            end_local_date="2026-07-23",
            period_mode="strict_lear_common_support_plus_dplus4_targets",
            dataset_split="extended_oos",
        ),
        output_policy_name="audit",
        cache_root=cache_root,
        use_cache=True,
        methodological_approximations=("scenario_undercoverage_warning",),
    )
    frame = resolved.scenarios.loc[resolved.scenarios["lead_day"].isin(lead_days)].copy()
    actuals = frame[
        ["forecast_origin_utc", "delivery_start_utc", "lead_day", "actual_price_eur_per_mwh"]
    ].drop_duplicates()
    provenance = {
        "artifact_id": artifact_id,
        "slice_fingerprint": resolved.slice_fingerprint,
        "experiment_fingerprint": resolved.experiment_fingerprint.digest,
        "cache_status": resolved.cache_status,
        "selected_period": resolved.selected_period,
        "findings": resolved.findings,
    }
    return frame, actuals, provenance


def main() -> None:
    args = _parse_args()
    started = perf_counter()
    config, repo_root = load_comparison_config(args.config)
    config_path = Path(args.config).resolve()
    forecast_root = _resolved(repo_root, config["forecast_run_root"])
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_strict_lear_horizon_granularity")
    run_dir = _resolved(repo_root, config["outputs"]["run_root"]) / run_id
    comparison_dir = _resolved(repo_root, config["outputs"]["comparison_root"]) / run_id

    input_paths = [
        config_path,
        _resolved(repo_root, config["base_hydrogen_config"]),
        forecast_root / "evaluation_actuals.parquet",
        forecast_root / config["scenario_reduction_mapping_file"],
        forecast_root / "optimisation_inputs/hourly_donly_point_forecasts.parquet",
        forecast_root / "optimisation_inputs/hourly_point_forecasts.parquet",
        forecast_root / "optimisation_inputs/quarterhour_point_forecasts.parquet",
        forecast_root / "optimisation_inputs/hourly_donly_support_manifest.json",
        forecast_root / "point_forecast_metrics.csv",
        forecast_root / "scenario_metrics_summary.csv",
    ]
    for spec in config["configurations"].values():
        input_paths.extend(forecast_root / relative for relative in spec["scenario_files"].values())
    missing = [str(path) for path in input_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Required comparison inputs are missing: {missing}")
    write_run_governance(
        run_dir=run_dir,
        comparison_dir=comparison_dir,
        config=config,
        config_path=config_path,
        input_paths=list(dict.fromkeys(input_paths)),
    )
    (run_dir / "code_version.json").write_text(json.dumps(_code_version(repo_root), indent=2), encoding="utf-8")

    support_checks, support = validate_support_contract(forecast_root=forecast_root, comparison_config=config)
    support_checks.to_csv(run_dir / "support_checks.csv", index=False)
    (run_dir / "support_summary.json").write_text(json.dumps(support, indent=2), encoding="utf-8")
    _copy_forecast_metrics(forecast_root, comparison_dir)
    donly_point_metrics, dm_test = build_hourly_donly_point_metrics(forecast_root)
    donly_scenario_metrics = build_hourly_donly_scenario_metrics(forecast_root)
    donly_point_metrics.to_csv(comparison_dir / "hourly_donly_point_metrics.csv", index=False)
    dm_test.to_csv(comparison_dir / "hourly_donly_vs_dplus4_dm_test.csv", index=False)
    donly_scenario_metrics.to_csv(comparison_dir / "hourly_donly_scenario_metrics.csv", index=False)
    if args.prepare_only:
        summary = {
            "run_id": run_id,
            "status": "prepared_support_validated",
            "support": support,
            "warning": SCENARIO_UNDERCOVERAGE_WARNING,
            "runtime_seconds": perf_counter() - started,
        }
        (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return

    base_config = load_hydrogen_config(_resolved(repo_root, config["base_hydrogen_config"]))
    comparability_payload, comparability_hash = _comparability_contract(
        base_config=base_config,
        comparison_config=config,
        repo_root=repo_root,
    )
    (run_dir / "frozen_comparability_contract.json").write_text(
        json.dumps(
            {
                "contract_sha256": comparability_hash,
                "applies_to": list(config["configurations"]),
                "excluded_case_dimensions": ["forecast_artifact", "horizon", "granularity", "scenario_count", "benchmark_policy"],
                "contract": comparability_payload,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    selected_episodes = args.episodes or list(config["episodes"])
    selected_configurations = args.configurations or list(config["configurations"])
    selected_policies = args.policies or list(config["policies"])
    actuals_path = forecast_root / "evaluation_actuals.parquet"
    daily_frames: list[pd.DataFrame] = []
    dispatch_frames: list[pd.DataFrame] = []
    solver_frames: list[pd.DataFrame] = []
    metadata_rows: list[dict[str, Any]] = []
    resolver_provenance: list[dict[str, Any]] = []
    completed: set[tuple[str, str, str]] = set()
    checkpoint_dir = run_dir / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    if args.resume and (checkpoint_dir / "daily_metrics.parquet").exists():
        daily_existing = pd.read_parquet(checkpoint_dir / "daily_metrics.parquet")
        solver_existing = pd.read_parquet(checkpoint_dir / "solver_metrics.parquet")
        metadata_existing = json.loads((checkpoint_dir / "episode_metadata.json").read_text(encoding="utf-8"))
        daily_frames.append(daily_existing)
        solver_frames.append(solver_existing)
        metadata_rows.extend(metadata_existing)
        if (checkpoint_dir / "executed_dispatch.parquet").exists():
            dispatch_frames.append(pd.read_parquet(checkpoint_dir / "executed_dispatch.parquet"))
        completed = {
            (str(row["episode_id"]), str(row["configuration"]), str(row["policy"])) for row in metadata_existing
        }

    for configuration in selected_configurations:
        spec = config["configurations"][configuration]
        granularity = str(spec["granularity"])
        horizon_mode = "D_only" if spec["horizon_lead_days"] == [0] else "D_to_Dplus4"
        hydrogen_config = resolved_hydrogen_config(
            base_config, granularity=granularity, horizon_mode=horizon_mode, comparison_config=config
        )
        scenario_30, actuals, provenance_30 = _resolve_scenario_set(
            hydrogen_config=hydrogen_config,
            artifact_id=spec["artifact_ids"][30],
            lead_days=spec["horizon_lead_days"],
            cache_root=repo_root / "tmp/hydrogen_horizon_granularity_input_cache",
        )
        scenario_10, _, provenance_10 = _resolve_scenario_set(
            hydrogen_config=hydrogen_config,
            artifact_id=spec["artifact_ids"][10],
            lead_days=spec["horizon_lead_days"],
            cache_root=repo_root / "tmp/hydrogen_horizon_granularity_input_cache",
        )
        resolver_provenance.extend([provenance_30, provenance_10])
        for episode_id in selected_episodes:
            days = support["episodes"][episode_id]
            for policy in selected_policies:
                key = (episode_id, configuration, policy)
                if key in completed:
                    continue
                daily, dispatch, solver, metadata = run_rolling_policy(
                    config_id=configuration,
                    policy=policy,
                    episode_id=episode_id,
                    episode_days=days,
                    scenario_30=scenario_30,
                    scenario_10=scenario_10,
                    actuals=actuals,
                    hydrogen_config=hydrogen_config,
                    comparison_config=config,
                    run_id=run_id,
                )
                daily_frames.append(daily)
                dispatch_frames.append(dispatch)
                solver_frames.append(solver)
                metadata_rows.append(metadata)
                checkpoint_io_started = perf_counter()
                _write_checkpoint(checkpoint_dir / "daily_metrics.parquet", daily_frames)
                if config["outputs"].get("save_executed_dispatch", True):
                    _write_checkpoint(checkpoint_dir / "executed_dispatch.parquet", dispatch_frames)
                (checkpoint_dir / "episode_metadata.json").write_text(
                    json.dumps(metadata_rows, indent=2, default=str), encoding="utf-8"
                )
                checkpoint_io_seconds = perf_counter() - checkpoint_io_started
                solver.loc[:, "output_io_seconds"] = checkpoint_io_seconds / max(len(solver), 1)
                _write_checkpoint(checkpoint_dir / "solver_metrics.parquet", solver_frames)

    if "H-D4" in selected_configurations and "primary" in selected_episodes and "stochastic_30" in selected_policies:
        control_key = ("primary", "H-D4|D", "stochastic_30")
        if control_key not in completed:
            spec = config["configurations"]["H-D4"]
            h_config = resolved_hydrogen_config(
                base_config, granularity="hourly", horizon_mode="D_only_attribution_control", comparison_config=config
            )
            scenario_30, actuals, provenance_30 = _resolve_scenario_set(
                hydrogen_config=h_config,
                artifact_id=spec["artifact_ids"][30],
                lead_days=[0],
                cache_root=repo_root / "tmp/hydrogen_horizon_granularity_input_cache",
            )
            scenario_10, _, provenance_10 = _resolve_scenario_set(
                hydrogen_config=h_config,
                artifact_id=spec["artifact_ids"][10],
                lead_days=[0],
                cache_root=repo_root / "tmp/hydrogen_horizon_granularity_input_cache",
            )
            resolver_provenance.extend([provenance_30, provenance_10])
            daily, dispatch, solver, metadata = run_rolling_policy(
                config_id="H-D4|D",
                policy="stochastic_30",
                episode_id="primary",
                episode_days=support["episodes"]["primary"],
                scenario_30=scenario_30,
                scenario_10=scenario_10,
                actuals=actuals,
                hydrogen_config=h_config,
                comparison_config=config,
                run_id=run_id,
            )
            daily_frames.append(daily)
            dispatch_frames.append(dispatch)
            solver_frames.append(solver)
            metadata_rows.append(metadata)

    daily_all = pd.concat(daily_frames, ignore_index=True)
    dispatch_all = pd.concat(dispatch_frames, ignore_index=True)
    solver_all = pd.concat(solver_frames, ignore_index=True)
    metadata_frame = pd.DataFrame(metadata_rows)
    aggregate, effects = build_comparison_tables(daily_all, metadata_frame, config["bootstrap"])
    oracle_checks = _oracle_gate(aggregate)
    state_checks = _state_carryover_checks(daily_all)
    quota_table = _weekly_quota_table(metadata_frame)
    dispatch_all["dispatch_delivery_day"] = pd.to_datetime(
        dispatch_all["delivery_start_utc"], utc=True
    ).dt.tz_convert("Europe/Amsterdam").dt.strftime("%Y-%m-%d")
    settlement_checks = dispatch_all.groupby(
        ["episode_id", "configuration", "policy", "delivery_day"], as_index=False
    ).agg(
        executed_timestamp_count=("delivery_start_utc", "nunique"),
        distinct_local_delivery_days=("dispatch_delivery_day", "nunique"),
        executed_local_delivery_day=("dispatch_delivery_day", "first"),
    )
    settlement_checks["passed"] = (
        settlement_checks["distinct_local_delivery_days"].eq(1)
        & settlement_checks["executed_local_delivery_day"].eq(settlement_checks["delivery_day"])
    )
    monthly = daily_all.assign(month=pd.to_datetime(daily_all["delivery_day"]).dt.strftime("%Y-%m")).groupby(
        ["episode_id", "configuration", "policy", "month"], as_index=False
    ).agg(
        realised_adjusted_profit_ex_terminal_eur=("realised_adjusted_profit_ex_terminal_eur", "sum"),
        da_cost_eur=("da_cost_eur", "sum"),
        hydrogen_compressed_kg=("hydrogen_compressed_kg", "sum"),
        shortfall_kg=("shortfall_kg", "sum"),
        emergency_import_mwh=("emergency_import_mwh", "sum"),
        average_paid_price_eur_per_mwh=("average_paid_price_eur_per_mwh", "mean"),
        high_price_energy_share=("high_price_energy_share", "mean"),
        low_price_energy_share=("low_price_energy_share", "mean"),
        execution_days=("delivery_day", "nunique"),
    )
    scenario_sensitivity = aggregate.loc[
        aggregate["policy"].isin(["stochastic_30", "stochastic_10"])
    ].pivot(
        index=["episode_id", "configuration"],
        columns="policy",
        values=["realised_adjusted_profit_eur", "wall_time_seconds", "shortfall_kg", "emergency_import_mwh"],
    )
    scenario_sensitivity.columns = [f"{metric}_{policy}" for metric, policy in scenario_sensitivity.columns]
    scenario_sensitivity = scenario_sensitivity.reset_index()
    for metric in ("realised_adjusted_profit_eur", "wall_time_seconds", "shortfall_kg", "emergency_import_mwh"):
        scenario_sensitivity[f"{metric}_10_minus_30"] = (
            scenario_sensitivity[f"{metric}_stochastic_10"]
            - scenario_sensitivity[f"{metric}_stochastic_30"]
        )
    solver_gate = bool(solver_all["accepted_for_headline"].all())
    oracle_gate = bool(oracle_checks["passed"].all()) if not oracle_checks.empty else False
    state_gate = bool(state_checks["passed"].all())
    quota_gate = bool(quota_table["fulfilled"].all())
    settlement_gate = bool(settlement_checks["passed"].all())

    daily_all.to_parquet(comparison_dir / "daily_paired_results.parquet", index=False)
    solver_all.to_parquet(comparison_dir / "solver_metrics.parquet", index=False)
    metadata_frame.to_json(comparison_dir / "episode_state_and_quota_summary.json", orient="records", indent=2)
    aggregate.to_csv(comparison_dir / "thesis_body_hydrogen_results.csv", index=False)
    monthly.to_csv(comparison_dir / "appendix_monthly_hydrogen_results.csv", index=False)
    scenario_sensitivity.to_csv(comparison_dir / "scenario_count_30_vs_10.csv", index=False)
    effects.to_csv(comparison_dir / "paired_effects_moving_block_bootstrap.csv", index=False)
    oracle_checks.to_csv(run_dir / "true_pf_dominance_checks.csv", index=False)
    state_checks.to_csv(run_dir / "state_carryover_checks.csv", index=False)
    quota_table.to_csv(run_dir / "weekly_quota_checks.csv", index=False)
    settlement_checks.to_csv(run_dir / "settlement_D_only_checks.csv", index=False)
    (run_dir / "input_slice_provenance.json").write_text(
        json.dumps(resolver_provenance, indent=2, default=str), encoding="utf-8"
    )
    if config["outputs"].get("save_executed_dispatch", True):
        dispatch_all.drop(columns="dispatch_delivery_day").to_parquet(
            comparison_dir / "executed_D_dispatch.parquet", index=False
        )
    figure_paths = create_thesis_figures(
        aggregate=aggregate,
        effects=effects,
        solver=solver_all,
        output_dir=comparison_dir / "figures",
    )
    inventory = _artifact_inventory(run_dir, comparison_dir)
    inventory.to_csv(run_dir / "artifact_inventory.csv", index=False)
    summary = {
        "run_id": run_id,
        "status": "complete" if solver_gate and oracle_gate and state_gate and quota_gate and settlement_gate else "failed_headline_gate",
        "support": support,
        "completed_policy_runs": int(len(metadata_frame)),
        "solver_gate_passed": solver_gate,
        "true_pf_dominance_gate_passed": oracle_gate,
        "state_carryover_gate_passed": state_gate,
        "weekly_quota_gate_passed": quota_gate,
        "settlement_D_only_gate_passed": settlement_gate,
        "comparability_contract_sha256": comparability_hash,
        "solver_convergence_repair": config.get("solver", {}).get("convergence_repair"),
        "scenario_undercoverage_warning": SCENARIO_UNDERCOVERAGE_WARNING,
        "runtime_seconds": perf_counter() - started,
        "comparison_dir": str(comparison_dir),
        "figure_paths": [str(path) for path in figure_paths],
    }
    (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (comparison_dir / "README.md").write_text(
        "# Strict LEAR hydrogen horizon/granularity comparison\n\n"
        f"Run `{run_id}`. Status: `{summary['status']}`.\n\n"
        f"Warning: {SCENARIO_UNDERCOVERAGE_WARNING}\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    if not solver_gate or not oracle_gate or not state_gate or not quota_gate or not settlement_gate:
        raise SystemExit("Full comparison completed but failed a headline acceptance gate.")


if __name__ == "__main__":
    main()
