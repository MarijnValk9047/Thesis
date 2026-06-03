from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.selected_test_week_cvar_policy_eval import (
    DEFAULT_ALPHA,
    DEFAULT_GAMMAS,
    DEFAULT_WEEK_ID,
    run_selected_test_week_cvar_policy_eval,
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
        description="Run the Phase E1 one-week selected test-week CVaR policy evaluation.",
    )
    parser.add_argument("--config", required=True, help="Path to the hydrogen config YAML.")
    parser.add_argument("--week-id", default=DEFAULT_WEEK_ID, help="Selected test-week label or canonical week ID.")
    parser.add_argument("--artifacts", nargs="+", required=True, help="Scenario artifact IDs to run.")
    parser.add_argument("--alpha", type=float, default=float(DEFAULT_ALPHA), help="CVaR alpha. Phase E1 requires 0.95.")
    parser.add_argument("--gammas", nargs="+", type=float, default=list(DEFAULT_GAMMAS), help="Gamma grid. Phase E1 requires exactly 0 0.05 0.25.")
    parser.add_argument(
        "--include-price-insensitive-benchmark",
        type=_bool_arg,
        default=True,
        help="Whether to run the price-insensitive benchmark. Phase E1 requires true.",
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
    result = run_selected_test_week_cvar_policy_eval(
        config=config,
        week_id=str(args.week_id),
        artifact_ids=[str(value) for value in args.artifacts],
        cvar_alpha=float(args.alpha),
        gamma_values=[float(value) for value in args.gammas],
        include_price_insensitive_benchmark=bool(args.include_price_insensitive_benchmark),
        include_perfect_foresight_benchmark=bool(args.include_perfect_foresight_benchmark),
        run_slug=str(args.run_slug),
        output_root=Path(args.output_root) if args.output_root else None,
    )
    print("run_dir=", result.run_dir)
    print("notebook_path=", result.notebook_path)
    print("selected_week=", str(result.selected_week["week_label"]))
    print("daily_rows=", int(result.daily_metrics.shape[0]))
    print("weekly_rows=", int(result.weekly_metrics.shape[0]))


if __name__ == "__main__":
    main()
