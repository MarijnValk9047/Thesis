from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from hydrogen.bidding_metrics import attach_redispatch_uplift_metrics, compute_bridge_clearing_metrics  # noqa: E402
from hydrogen.plant_parameters import load_hydrogen_config  # noqa: E402
from hydrogen.plots import (  # noqa: E402
    plot_cleared_used_unused_electricity,
    plot_redispatch_operation,
    plot_redispatch_production_fulfilment,
)
from hydrogen.redispatch import solve_actual_redispatch_from_cleared_energy  # noqa: E402


DEFAULT_PHASE2_RUN = ROOT / "runs" / "20260515_131723_hydrogen_phase2_schedule_to_bid_bridge"
DEFAULT_CONFIG = ROOT / "configs" / "base_hydrogen.yaml"


def _resolve_latest_phase2_run() -> Path:
    runs_root = ROOT / "runs"
    candidates = sorted(
        [path for path in runs_root.iterdir() if path.is_dir() and (path / "bridge_clearing_by_hour.parquet").exists()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No Phase 2 bridge run folder with bridge_clearing_by_hour.parquet was found.")
    return candidates[0]


def _build_stress_profiles(reference_hourly: pd.DataFrame) -> list[pd.DataFrame]:
    base = reference_hourly[
        [
            "delivery_start_utc",
            "actual_price_eur_per_mwh",
            "timestep_hours",
            "granularity",
            "horizon",
            "forecast_origin_utc",
        ]
    ].copy()
    stress_definitions = {
        "stress_zero_cleared_energy": 0.0,
        "stress_scarce_cleared_energy": 15.0,
        "stress_abundant_cleared_energy": 70.0,
    }
    profiles: list[pd.DataFrame] = []
    for case_name, cleared_energy in stress_definitions.items():
        frame = base.copy()
        frame["cleared_energy_mwh"] = float(cleared_energy)
        frame["run_id"] = "synthetic_phase3_stress"
        frame["strategy"] = case_name
        frame["source_strategy"] = "stress_case"
        frame["bridge_strategy"] = case_name
        frame["forecast_model"] = pd.NA
        frame["scenario_model"] = "synthetic"
        frame["redispatch_case"] = case_name
        profiles.append(frame)
    return profiles


def _write_readme(output_dir: Path, *, phase2_run_dir: Path, summary: pd.DataFrame) -> None:
    lines = [
        "# Redispatch After Clearing",
        "",
        "This run solves the physical hydrogen operation problem using only cleared day-ahead electricity.",
        "",
        f"- Input Phase 2 folder: `{phase2_run_dir}`",
        "- Core identity: `used_energy_mwh + unused_cleared_energy_mwh = cleared_energy_mwh`",
        "- Redispatch treats cleared electricity as sunk; settlement cost is reported separately at actual DA price",
        "- Redispatch objective excludes DA procurement cost and penalises physically unused cleared electricity",
        f"- Configured unused-energy penalty: `{summary['unused_energy_penalty_eur_per_mwh'].iloc[0] if 'unused_energy_penalty_eur_per_mwh' in summary.columns and not summary.empty else 'unknown'} EUR/MWh`",
        "- Reliability fulfilment is reported with a capped metric; above-target hydrogen remains physically allowed",
        "- This is deterministic redispatch after actual clearing, not a stochastic bidding MILP",
        "",
        "## Summary",
        "",
        "```csv",
        summary.to_csv(index=False).strip(),
        "```",
    ]
    (output_dir / "README_redispatch.md").write_text("\n".join(lines), encoding="utf-8")


def run_redispatch(phase2_run_dir: Path, config_path: Path, output_root: Path) -> Path:
    config = load_hydrogen_config(config_path)
    phase2_run_dir = phase2_run_dir.resolve()
    hourly_path = phase2_run_dir / "bridge_clearing_by_hour.parquet"
    metrics_path = phase2_run_dir / "bridge_actual_clearing.parquet"
    if not hourly_path.exists():
        raise FileNotFoundError(f"Missing Phase 2 hourly clearing file: {hourly_path}")

    bridge_hourly = pd.read_parquet(hourly_path)
    if "timestep_hours" not in bridge_hourly.columns:
        bridge_hourly["timestep_hours"] = 1.0
    bridge_actual = pd.read_parquet(metrics_path) if metrics_path.exists() else pd.DataFrame()
    bridge_metrics = compute_bridge_clearing_metrics(bridge_actual) if not bridge_actual.empty else pd.DataFrame()

    output_dir = output_root / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_hydrogen_phase3_redispatch_after_clearing"
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    solve_inputs: list[pd.DataFrame] = []
    grouping_columns = [
        "run_id",
        "strategy",
        "source_strategy",
        "bridge_strategy",
        "forecast_model",
        "scenario_model",
        "granularity",
        "horizon",
        "forecast_origin_utc",
    ]
    for _, group in bridge_hourly.groupby(grouping_columns, dropna=False):
        solve_inputs.append(group.copy())

    reference_group = bridge_hourly.loc[bridge_hourly["bridge_strategy"] == "high_price_bid"].sort_values("delivery_start_utc")
    if reference_group.empty:
        reference_group = bridge_hourly.sort_values("delivery_start_utc")
    reference_template = next(iter(reference_group.groupby(["source_strategy", "bridge_strategy"], dropna=False)))[1]
    solve_inputs.extend(_build_stress_profiles(reference_template))

    summaries: list[pd.DataFrame] = []
    validations: list[pd.DataFrame] = []
    timeseries_frames: list[pd.DataFrame] = []

    for profile in solve_inputs:
        label = str(profile["strategy"].iloc[0])
        log_path = output_dir / f"{label}__solver_log.txt"
        result = solve_actual_redispatch_from_cleared_energy(
            profile,
            config=config,
            solver_log_path=log_path,
        )
        summaries.append(result.summary)
        validations.append(result.validation_checks.assign(strategy=result.summary["strategy"].iloc[0]))
        timeseries_frames.append(result.timeseries)

        stem = label
        plot_cleared_used_unused_electricity(
            redispatch=result.timeseries,
            output_dir=figures_dir,
            filename=f"{stem}__cleared_used_unused.png",
            title=label,
        )
        plot_redispatch_operation(
            redispatch=result.timeseries,
            reserve_kg=config.hydrogen_system.reserve_kg,
            output_dir=figures_dir,
            filename=f"{stem}__operation.png",
            title=label,
        )
        plot_redispatch_production_fulfilment(
            summary_row=result.summary.iloc[0],
            output_dir=figures_dir,
            filename=f"{stem}__fulfilment.png",
            title=label,
        )

    redispatch_summary = pd.concat(summaries, ignore_index=True)
    redispatch_validation = pd.concat(validations, ignore_index=True)
    redispatch_timeseries = pd.concat(timeseries_frames, ignore_index=True)
    if not bridge_metrics.empty:
        redispatch_summary = attach_redispatch_uplift_metrics(bridge_metrics, redispatch_summary).combine_first(redispatch_summary)

    redispatch_timeseries.to_parquet(output_dir / "redispatch_timeseries.parquet", index=False)
    redispatch_summary.to_csv(output_dir / "redispatch_summary.csv", index=False)
    redispatch_validation.to_csv(output_dir / "redispatch_validation_checks.csv", index=False)
    production_semantics = redispatch_summary[
        [
            column
            for column in [
                "strategy",
                "source_strategy",
                "bridge_strategy",
                "target_hydrogen_kg",
                "hydrogen_compressed_or_sold_kg",
                "hydrogen_above_target_kg",
                "target_fulfilment_ratio_capped_for_reliability",
                "production_to_target_ratio_uncapped",
                "terminal_inventory_change_kg",
                "terminal_inventory_correction_eur",
                "realised_adjusted_profit_eur",
            ]
            if column in redispatch_summary.columns
        ]
    ].copy()
    production_semantics.to_csv(output_dir / "production_semantics_summary.csv", index=False)
    (output_dir / "redispatch_manifest.json").write_text(
        json.dumps(
            {
                "input_phase2_run_dir": str(phase2_run_dir),
                "config_path": str(config_path),
                "output_dir": str(output_dir),
                "stress_cases": [
                    "stress_zero_cleared_energy",
                    "stress_scarce_cleared_energy",
                    "stress_abundant_cleared_energy",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_readme(output_dir, phase2_run_dir=phase2_run_dir, summary=redispatch_summary)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve deterministic redispatch after actual clearing for hydrogen bridge outputs.")
    parser.add_argument(
        "--input-run",
        type=Path,
        default=DEFAULT_PHASE2_RUN if DEFAULT_PHASE2_RUN.exists() else _resolve_latest_phase2_run(),
        help="Phase 2 bridge run folder containing bridge_clearing_by_hour.parquet.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Hydrogen config path.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "runs",
        help="Output root for redispatch runs.",
    )
    args = parser.parse_args()
    output_dir = run_redispatch(args.input_run, args.config, args.output_root)
    print(output_dir)


if __name__ == "__main__":
    main()
