"""Prepare, execute, resume, or cache-aggregate Checkpoint 6."""

from __future__ import annotations

import argparse
import json
import os

from steel.s4_4c5p_c0_real_anchor_checkpoint6_evaluation import run_checkpoint6


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--forecast-run-root",
        default=os.environ.get("STEEL_DA_FORECAST_RUN_ROOT"),
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--scratch-root", default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()
    if not args.forecast_run_root:
        parser.error("--forecast-run-root or STEEL_DA_FORECAST_RUN_ROOT is required")
    kwargs: dict[str, object] = {
        "forecast_run_root": args.forecast_run_root,
        "prepare_only": args.prepare_only,
        "aggregate_only": args.aggregate_only,
    }
    if args.config:
        kwargs["config_path"] = args.config
    if args.scratch_root:
        kwargs["scratch_root"] = args.scratch_root
    result = run_checkpoint6(**kwargs)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
