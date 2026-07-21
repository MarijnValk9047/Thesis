"""Run the C0 fixed-schedule reporting-only physical surface."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_ba_c0_fixed_schedule_reporting import run_c0_fixed_schedule_reporting


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run governed C0 rolling physical reporting.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()
    kwargs = {}
    if args.config:
        kwargs["config_path"] = args.config
    if args.output_root:
        kwargs["output_root"] = args.output_root
    result = run_c0_fixed_schedule_reporting(**kwargs)
    print(result["summary"])
