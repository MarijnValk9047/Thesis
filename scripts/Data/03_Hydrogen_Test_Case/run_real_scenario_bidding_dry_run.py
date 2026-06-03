from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.bidding_backtest import run_real_scenario_bidding_dry_run
from hydrogen.plant_parameters import load_hydrogen_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a one-day real-scenario stochastic bidding integration dry run.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the hydrogen config YAML.",
    )
    parser.add_argument(
        "--artifact-id",
        required=True,
        help="Scenario artifact ID from scenario_catalog.yaml.",
    )
    parser.add_argument(
        "--forecast-origin-utc",
        default=None,
        help="Optional explicit forecast origin UTC. If omitted, the first complete 24-hour origin is used.",
    )
    parser.add_argument(
        "--max-origins",
        type=int,
        default=1,
        help="Maximum number of forecast origins to run. Phase 6b only supports 1.",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Optional output root override.",
    )
    parser.add_argument(
        "--strategy-name",
        default="stochastic_bid_risk_neutral",
        help="Strategy label written into the submitted bid outputs.",
    )
    parser.add_argument(
        "--dry-run-label",
        default="integration_candidate",
        help="Run label suffix used in the output folder.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_hydrogen_config(args.config)
    result = run_real_scenario_bidding_dry_run(
        config=config,
        artifact_id=str(args.artifact_id),
        forecast_origin_utc=args.forecast_origin_utc,
        max_origins=int(args.max_origins),
        output_root=Path(args.output_root) if args.output_root else None,
        strategy_name=str(args.strategy_name),
        dry_run_label=str(args.dry_run_label),
    )
    summary = result.metrics_summary.iloc[0].to_dict()
    print("run_dir=", result.run_dir)
    print("artifact_id=", result.artifact_id)
    print("forecast_origin_utc=", result.forecast_origin_utc.isoformat())
    print("delivery_day=", result.delivery_day)
    print("solver_status=", summary.get("solver_status"))
    print("expected_adjusted_profit_eur=", summary.get("expected_adjusted_profit_eur"))
    print("realised_adjusted_profit_eur=", summary.get("realised_adjusted_profit_eur"))


if __name__ == "__main__":
    main()
