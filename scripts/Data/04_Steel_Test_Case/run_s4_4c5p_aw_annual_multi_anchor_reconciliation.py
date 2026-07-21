from __future__ import annotations

import argparse

from steel.s4_4c5p_aw_annual_multi_anchor_reconciliation import run_annual_multi_anchor_reconciliation


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compile existing annual C1 anchor comparisons without solving a model.")
    parser.add_argument("--config", default=None, help="Optional annual-anchor reconciliation YAML.")
    args = parser.parse_args()
    kwargs = {"config_path": args.config} if args.config else {}
    result = run_annual_multi_anchor_reconciliation(**kwargs)
    print(result["run_directory"])
