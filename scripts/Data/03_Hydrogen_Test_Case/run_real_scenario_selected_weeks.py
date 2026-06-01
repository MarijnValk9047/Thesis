from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.selected_week_suite import run_real_scenario_selected_week_suite


def _bool_arg(value: str) -> bool:
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Unable to parse boolean argument from {value!r}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run selected-week hourly real-scenario stochastic bidding diagnostics.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the hydrogen config YAML.",
    )
    parser.add_argument(
        "--artifact-ids",
        nargs="+",
        required=True,
        help="Scenario artifact IDs from scenario_catalog.yaml.",
    )
    parser.add_argument(
        "--week-registry",
        default=None,
        help="Optional existing selected_week_registry.csv to reuse.",
    )
    parser.add_argument(
        "--selection-method",
        default="price_diagnostics",
        help="Week selection method. Supported: price_diagnostics.",
    )
    parser.add_argument(
        "--week-count",
        type=int,
        default=5,
        help="Number of selected diagnostic weeks. Supported: 4 or 5. Default: 5.",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Optional output root override.",
    )
    parser.add_argument(
        "--strategy-name",
        default="stochastic_bid_risk_neutral",
        help="Strategy label written into nested day-run outputs.",
    )
    parser.add_argument(
        "--include-price-insensitive-benchmark",
        type=_bool_arg,
        default=True,
        help="Whether to run the price-insensitive benchmark alongside stochastic bidding. Default: true.",
    )
    parser.add_argument(
        "--risk-measure",
        default="risk_neutral",
        help="Risk measure label. Current implementation supports risk_neutral only.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_hydrogen_config(args.config)
    result = run_real_scenario_selected_week_suite(
        config=config,
        artifact_ids=[str(value) for value in args.artifact_ids],
        week_registry=Path(args.week_registry) if args.week_registry else None,
        selection_method=str(args.selection_method),
        week_count=int(args.week_count),
        output_root=Path(args.output_root) if args.output_root else None,
        strategy_name=str(args.strategy_name),
        include_price_insensitive_benchmark=bool(args.include_price_insensitive_benchmark),
        risk_measure=str(args.risk_measure),
    )
    print("suite_dir=", result.suite_dir)
    print("selected_week_count=", int(result.selected_week_registry.shape[0]))
    print("daily_run_count=", int(result.daily_metrics.shape[0]))
    print("artifacts=", sorted(result.daily_metrics["artifact_id"].astype(str).unique().tolist()))


if __name__ == "__main__":
    main()
