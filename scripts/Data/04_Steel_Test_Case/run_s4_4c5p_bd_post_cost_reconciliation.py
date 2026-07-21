"""Run post-cost reconciliation from the accepted fixed-reference cost lineage."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_bd_post_cost_reconciliation import run_post_cost_reconciliation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = run_post_cost_reconciliation(
        **({"parent_run_directory": args.parent} if args.parent else {}),
        **({"output_directory": args.output} if args.output else {}),
    )
    print(result["summary"])
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
