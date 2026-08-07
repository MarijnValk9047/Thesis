"""CLI for deterministic C1 plant-behaviour and partial anchor validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STEEL_SCRIPT_ROOT = Path(__file__).resolve().parent
for path in (REPO_ROOT, STEEL_SCRIPT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from steel.s4_4c6_deterministic_behaviour_anchor_validation import (  # noqa: E402
    CONFIG_PATH,
    run_behaviour_anchor_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--skip-partial-year-replay",
        action="store_true",
        help="Use only an existing cumulative-total artifact; fail if it is absent.",
    )
    parser.add_argument(
        "--annual-totals-source",
        type=Path,
        default=None,
        help="Reuse a contract-identical cumulative_execution_totals.json artifact.",
    )
    parser.add_argument(
        "--before-run-root",
        type=Path,
        default=None,
        help="Compare identical cases with a pre-repair validation run folder.",
    )
    args = parser.parse_args()
    decision = run_behaviour_anchor_validation(
        config_path=args.config,
        run_id=args.run_id,
        skip_partial_year_replay=args.skip_partial_year_replay,
        annual_totals_source=args.annual_totals_source,
        before_run_root=args.before_run_root,
    )
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if decision.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
