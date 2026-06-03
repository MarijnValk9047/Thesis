from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.validation_cvar_sweep import (
    DEFAULT_ALPHA,
    DEFAULT_GAMMAS,
    run_validation_week_cvar_smoke_sweep,
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
        description="Run the Phase D validation-week CVaR smoke/sweep.",
    )
    parser.add_argument("--config", required=True, help="Path to the hydrogen config YAML.")
    parser.add_argument("--week-id", required=True, help="Selected validation week label or canonical week_id.")
    parser.add_argument("--artifacts", nargs="+", required=True, help="Scenario artifact IDs to run.")
    parser.add_argument("--alpha", type=float, default=float(DEFAULT_ALPHA), help="CVaR alpha. Phase D requires 0.95.")
    parser.add_argument("--gammas", nargs="+", type=float, default=list(DEFAULT_GAMMAS), help="Gamma grid. Phase D requires exactly 0 0.05 0.25.")
    parser.add_argument(
        "--include-price-insensitive-benchmark",
        type=_bool_arg,
        default=True,
        help="Whether to run the price-insensitive benchmark. Phase D requires true.",
    )
    parser.add_argument("--run-slug", required=True, help="Run slug to embed in the run folder name.")
    parser.add_argument("--output-root", default=None, help="Optional output root override.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_hydrogen_config(args.config)
    result = run_validation_week_cvar_smoke_sweep(
        config=config,
        week_id=str(args.week_id),
        artifact_ids=[str(value) for value in args.artifacts],
        cvar_alpha=float(args.alpha),
        gamma_values=[float(value) for value in args.gammas],
        include_price_insensitive_benchmark=bool(args.include_price_insensitive_benchmark),
        run_slug=str(args.run_slug),
        output_root=Path(args.output_root) if args.output_root else None,
    )
    print("run_dir=", result.run_dir)
    print("week_id=", result.selected_week["week_id"])
    print("week_label=", result.selected_week["week_label"])
    print("weekly_rows=", int(result.weekly_metrics.shape[0]))
    print("cvar_validation_rows=", int(result.cvar_validation_checks.shape[0]))


if __name__ == "__main__":
    main()
