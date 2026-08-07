"""CLI for the deterministic C1 scalar temporal-repair gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STEEL_SCRIPT_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(STEEL_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_SCRIPT_ROOT))

from steel.s4_4c6_deterministic_temporal_repair import (  # noqa: E402
    CONFIG_PATH,
    run_causal_flat_year,
    run_temporal_repair,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--run-id", default="scalar_validation_45e0fc2")
    parser.add_argument(
        "--annual-flat-year",
        action="store_true",
        help="Run the causal flat-price calendar-year anchor re-evaluation.",
    )
    parser.add_argument(
        "--maximum-days",
        type=int,
        default=None,
        help="Optional bounded annual-prefix smoke; omit for the full year.",
    )
    parser.add_argument(
        "--wag-self-use-diagnostic",
        action="store_true",
        help=(
            "Run the non-promoted C1 carrier-cap diagnostic: no COG to VN25 "
            "and BOFG to VN25 capped at the MER annualised comparison value."
        ),
    )
    parser.add_argument("--generator-efficiency-418", action="store_true")
    parser.add_argument("--process-electricity-overlay", action="store_true")
    parser.add_argument("--ng-service-anchor-overlay", action="store_true")
    parser.add_argument("--coal-wag-carbon-overlay", action="store_true")
    args = parser.parse_args()
    decision = (
        run_causal_flat_year(
            config_path=args.config,
            run_id=args.run_id,
            maximum_days=args.maximum_days,
        )
        if args.annual_flat_year
        else run_temporal_repair(
            config_path=args.config,
            run_id=args.run_id,
            wag_self_use_diagnostic=bool(args.wag_self_use_diagnostic),
            generator_efficiency_418=bool(args.generator_efficiency_418),
            process_electricity_overlay=bool(args.process_electricity_overlay),
            ng_service_anchor_overlay=bool(args.ng_service_anchor_overlay),
            coal_wag_carbon_overlay=bool(args.coal_wag_carbon_overlay),
        )
    )
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if decision["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
