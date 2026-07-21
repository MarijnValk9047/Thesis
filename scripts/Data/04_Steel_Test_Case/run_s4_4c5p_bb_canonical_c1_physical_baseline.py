"""Run the governed canonical C1 physical baseline."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_bb_canonical_c1_physical_baseline import run_canonical_c1_physical_baseline


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run canonical C1 physical baseline.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()
    kwargs = {}
    if args.config:
        kwargs["config_path"] = args.config
    if args.output_root:
        kwargs["output_root"] = args.output_root
    result = run_canonical_c1_physical_baseline(**kwargs)
    print(result["summary"])
