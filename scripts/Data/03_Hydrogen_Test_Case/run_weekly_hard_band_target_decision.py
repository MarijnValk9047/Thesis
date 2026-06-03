from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.weekly_hard_band_decision import (
    run_weekly_hard_band_target_decision,
)


def _bool_arg(value: str) -> bool:
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Unable to parse boolean argument from {value!r}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Phase E4 weekly hard-band target model selection on the selected common-support test weeks.",
    )
    parser.add_argument("--config", required=True, help="Path to the hydrogen config YAML.")
    parser.add_argument("--week-ids", nargs="+", required=True, help="Selected test-week labels.")
    parser.add_argument("--artifacts", nargs="+", required=True, help="Scenario artifact IDs to run.")
    parser.add_argument("--alpha", type=float, required=True, help="CVaR alpha. Phase E4 requires 0.95.")
    parser.add_argument("--gammas", nargs="+", type=float, required=True, help="Gamma grid. Phase E4 requires 0 0.05 0.25.")
    parser.add_argument("--target-mode", required=True, help="Target mode. Phase E4 requires weekly_hard_band_target.")
    parser.add_argument("--daily-min-fraction", type=float, required=True, help="Daily minimum fraction of daily_target_kg.")
    parser.add_argument("--daily-max-fraction", type=float, required=True, help="Daily maximum fraction of daily_target_kg.")
    parser.add_argument("--include-price-insensitive-benchmark", type=_bool_arg, default=True)
    parser.add_argument("--include-perfect-foresight-benchmark", type=_bool_arg, default=True)
    parser.add_argument("--reporting-mode", default="machine_only", help="Phase E4 only supports machine_only.")
    parser.add_argument("--run-slug", required=True, help="Run slug to embed in the run folder name.")
    parser.add_argument("--output-root", default=None, help="Optional output root override.")
    parser.add_argument("--resume-run-dir", default=None, help="Optional existing run folder to resume safely.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if str(args.target_mode).strip() != "weekly_hard_band_target":
        raise ValueError(f"Phase E4 requires --target-mode weekly_hard_band_target, got {args.target_mode!r}.")
    if str(args.reporting_mode).strip() != "machine_only":
        raise ValueError(f"Phase E4 requires --reporting-mode machine_only, got {args.reporting_mode!r}.")
    config = load_hydrogen_config(args.config)
    result = run_weekly_hard_band_target_decision(
        config=config,
        week_ids=[str(value) for value in args.week_ids],
        artifact_ids=[str(value) for value in args.artifacts],
        cvar_alpha=float(args.alpha),
        gamma_values=[float(value) for value in args.gammas],
        daily_min_fraction=float(args.daily_min_fraction),
        daily_max_fraction=float(args.daily_max_fraction),
        include_price_insensitive_benchmark=bool(args.include_price_insensitive_benchmark),
        include_perfect_foresight_benchmark=bool(args.include_perfect_foresight_benchmark),
        run_slug=str(args.run_slug),
        output_root=Path(args.output_root) if args.output_root else None,
        resume_run_dir=Path(args.resume_run_dir) if args.resume_run_dir else None,
    )
    print("run_dir=", result.run_dir)
    print("daily_rows=", int(result.daily_metrics.shape[0]))
    print("weekly_rows=", int(result.weekly_metrics.shape[0]))
    print("aggregated_rows=", int(result.aggregated_metrics_by_model_gamma.shape[0]))
    print("decision_rows=", int(result.model_decision_summary.shape[0]))


if __name__ == "__main__":
    main()
