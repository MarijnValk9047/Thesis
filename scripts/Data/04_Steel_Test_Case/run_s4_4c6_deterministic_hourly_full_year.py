from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from steel.s4_4c6_deterministic_hourly_full_year import (  # noqa: E402
    run_hourly_full_year,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the governed hourly C0/C1 price-insensitive and "
            "perfect-foresight calendar year with terminal ETA updates."
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the last atomic daily checkpoint in the same run folder.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Materialise and audit the 8,760-hour Strict-LEAR price/calendar input only.",
    )
    parser.add_argument(
        "--feasibility-shakedown",
        action="store_true",
        help=(
            "Run only one flat-price causal shakedown year for C0 and C1; "
            "skip economics and figures."
        ),
    )
    parser.add_argument(
        "--stop-after-total-day-solves",
        type=int,
        help="Testing-only checkpoint stop across the four trajectories.",
    )
    parser.add_argument(
        "--stop-after-day-per-case",
        type=int,
        help=(
            "Checkpoint every configured trajectory after this calendar day; "
            "resume the same run-id to extend all trajectories causally."
        ),
    )
    parser.add_argument(
        "--configuration",
        action="append",
        choices=("C0", "C1"),
        help=(
            "Testing-only configuration filter; repeat to select both. "
            "The unfiltered governed year run still executes C0 and C1."
        ),
    )
    args = parser.parse_args()
    result = run_hourly_full_year(
        run_id=args.run_id,
        resume=args.resume,
        dry_run=args.dry_run,
        feasibility_shakedown=args.feasibility_shakedown,
        stop_after_total_day_solves=args.stop_after_total_day_solves,
        stop_after_day_per_case=args.stop_after_day_per_case,
        selected_configurations=args.configuration,
    )
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
