"""CLI for the governed four-regime counterfactual steel study."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
STEEL_ROOT = Path(__file__).resolve().parent
for path in (REPO_ROOT, STEEL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from steel.s4_4c6_representative_regime_counterfactual import (  # noqa: E402
    REPRESENTATIVE_CONFIG,
    preflight,
    run_selected_experiments,
    run_split_horizon_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=REPRESENTATIVE_CONFIG)
    parser.add_argument(
        "--mode",
        choices=("preflight", "split-horizon-gate", "run"),
        default="preflight",
    )
    parser.add_argument("--experiment-id", action="append", default=[])
    ready_group = parser.add_mutually_exclusive_group()
    ready_group.add_argument("--all-ready", action="store_true")
    ready_group.add_argument("--all-central-ready", action="store_true")
    ready_group.add_argument("--all-sensitivity-ready", action="store_true")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.mode == "preflight":
        print(json.dumps(preflight(args.config), indent=2, sort_keys=True))
        return 0
    run_id = args.run_id.strip() or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    if args.mode == "split-horizon-gate":
        result = run_split_horizon_gate(args.config, run_id=run_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["summary"]["status"] == "pass" else 1
    result = run_selected_experiments(
        args.config,
        args.experiment_id,
        all_ready=bool(
            args.all_ready or args.all_central_ready or args.all_sensitivity_ready
        ),
        ready_scope=(
            "central"
            if args.all_central_ready
            else "sensitivity" if args.all_sensitivity_ready else None
        ),
        run_id=run_id,
        resume=bool(args.resume),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
