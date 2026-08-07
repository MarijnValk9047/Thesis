from __future__ import annotations

import argparse
import json
from pathlib import Path

from steel.s4_4c6_deterministic_hourly_temporal_validation import (
    run_hourly_example_week,
    run_hourly_year_readiness_smoke,
    prepare_hourly_annual_run_inputs,
    run_hourly_year_terminal_recovery_smoke,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="high_volatility_hourly_week_01")
    parser.add_argument("--regime", default="high_volatility")
    parser.add_argument(
        "--annual-readiness-smoke",
        action="store_true",
        help="Run seven hourly days with annual-prefix semantics; never runs 8760 hours.",
    )
    parser.add_argument(
        "--prepare-annual-inputs",
        action="store_true",
        help="Write the governed 8,760-hour calendar/price inputs without solving.",
    )
    parser.add_argument(
        "--annual-price-strategy",
        choices=("price_insensitive", "perfect_foresight_oracle"),
        default="price_insensitive",
    )
    parser.add_argument("--annual-price-source", type=Path)
    parser.add_argument("--source-is-realised-oracle", action="store_true")
    parser.add_argument(
        "--terminal-recovery-smoke",
        action="store_true",
        help="Solve only the synthetic day-364/365 terminal recovery certificate.",
    )
    args = parser.parse_args()
    if args.terminal_recovery_smoke:
        result = run_hourly_year_terminal_recovery_smoke(run_id=args.run_id)
    elif args.prepare_annual_inputs:
        result = prepare_hourly_annual_run_inputs(
            run_id=args.run_id,
            price_strategy=args.annual_price_strategy,
            price_source=args.annual_price_source,
            source_is_realised_oracle=args.source_is_realised_oracle,
        )
    elif args.annual_readiness_smoke:
        result = run_hourly_year_readiness_smoke(run_id=args.run_id, regime=args.regime)
    else:
        result = run_hourly_example_week(run_id=args.run_id, regime=args.regime)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
