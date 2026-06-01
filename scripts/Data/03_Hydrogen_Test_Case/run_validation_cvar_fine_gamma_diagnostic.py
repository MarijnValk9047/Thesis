from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.validation_cvar_fine_gamma_diagnostic import (
    DEFAULT_ALPHA,
    DEFAULT_ARTIFACT_ID,
    DEFAULT_FINE_GAMMAS,
    DEFAULT_WEEK_IDS,
    run_validation_cvar_fine_gamma_diagnostic,
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
        description="Run the Phase D3 LEAR FS3 fine near-zero gamma diagnostic.",
    )
    parser.add_argument("--config", required=True, help="Path to the hydrogen config YAML.")
    parser.add_argument("--week-ids", nargs="+", default=list(DEFAULT_WEEK_IDS), help="Selected validation week labels or canonical week IDs.")
    parser.add_argument("--artifact", default=DEFAULT_ARTIFACT_ID, help="Scenario artifact ID. Phase D3 requires LEAR FS3 only.")
    parser.add_argument("--alpha", type=float, default=float(DEFAULT_ALPHA), help="CVaR alpha. Phase D3 requires 0.95.")
    parser.add_argument(
        "--gammas",
        nargs="+",
        type=float,
        default=list(DEFAULT_FINE_GAMMAS),
        help="Fine gamma grid. Phase D3 requires exactly 0 0.001 0.0025 0.005 0.01 0.015 0.02 0.025 0.05.",
    )
    parser.add_argument(
        "--include-price-insensitive-benchmark",
        type=_bool_arg,
        default=True,
        help="Whether to run the price-insensitive benchmark. Phase D3 requires true.",
    )
    parser.add_argument(
        "--include-perfect-foresight-benchmark",
        type=_bool_arg,
        default=True,
        help="Whether to run the perfect-foresight benchmark.",
    )
    parser.add_argument("--run-slug", required=True, help="Run slug to embed in the run folder name.")
    parser.add_argument("--output-root", default=None, help="Optional output root override.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_hydrogen_config(args.config)
    result = run_validation_cvar_fine_gamma_diagnostic(
        config=config,
        week_ids=[str(value) for value in args.week_ids],
        artifact_id=str(args.artifact),
        cvar_alpha=float(args.alpha),
        gamma_values=[float(value) for value in args.gammas],
        include_price_insensitive_benchmark=bool(args.include_price_insensitive_benchmark),
        include_perfect_foresight_benchmark=bool(args.include_perfect_foresight_benchmark),
        run_slug=str(args.run_slug),
        output_root=Path(args.output_root) if args.output_root else None,
    )
    print("run_dir=", result.run_dir)
    print("notebook_path=", result.notebook_path)
    print("weekly_rows=", int(result.weekly_metrics.shape[0]))
    print("aggregated_rows=", int(result.fine_gamma_aggregated.shape[0]))
    print("bid_diff_rows=", int(result.bid_difference_by_gamma.shape[0]))


if __name__ == "__main__":
    main()
