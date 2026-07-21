"""Run deterministic steel D-D+4 response and anchor diagnostics."""

from __future__ import annotations

import argparse
import os

from steel.s4_4c5p_bl_deterministic_price_response_anchor_diagnostics import (
    run_deterministic_price_response_anchor_diagnostics,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--forecast-run-root",
        default=os.environ.get("STEEL_DA_FORECAST_RUN_ROOT"),
    )
    parser.add_argument("--output-directory", default=None)
    args = parser.parse_args()
    if not args.forecast_run_root:
        parser.error("--forecast-run-root or STEEL_DA_FORECAST_RUN_ROOT is required")
    kwargs = {"forecast_run_root": args.forecast_run_root}
    if args.output_directory:
        kwargs["output_directory"] = args.output_directory
    result = run_deterministic_price_response_anchor_diagnostics(**kwargs)
    print(result["output_directory"])
    print(result["summary"]["decision"])


if __name__ == "__main__":
    main()
