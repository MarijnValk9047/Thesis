"""Freeze representative D-D+4 weeks for source/emulation validation."""

from __future__ import annotations

import argparse
import os

from steel.c5_source_emulation_validation import run_representative_period_design
from steel.c5_source_emulation_evaluation import run_source_emulation_evaluation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--forecast-run-root",
        default=os.environ.get("STEEL_DA_FORECAST_RUN_ROOT"),
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--output-directory", default=None)
    parser.add_argument("--scratch-root", default=None)
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()
    if not args.forecast_run_root:
        parser.error("--forecast-run-root or STEEL_DA_FORECAST_RUN_ROOT is required")
    kwargs = {"forecast_run_root": args.forecast_run_root}
    if args.config:
        kwargs["config_path"] = args.config
    if args.output_directory:
        kwargs["output_directory"] = args.output_directory
    if args.evaluate:
        if args.scratch_root:
            kwargs["scratch_root"] = args.scratch_root
        kwargs["smoke_only"] = args.smoke_only
        kwargs["aggregate_only"] = args.aggregate_only
        result = run_source_emulation_evaluation(**kwargs)
    else:
        result = run_representative_period_design(**kwargs)
    print(result["output_directory"])
    print(result["summary"]["decision"])


if __name__ == "__main__":
    main()
