"""Run the final fixed-reference cost completion audit."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_bh_fixed_reference_cost_completion_audit import (
    run_completion_audit,
    run_final_acceptance_explanation_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--final-acceptance",
        action="store_true",
        help="Build the derived S2 final acceptance and explanation audit.",
    )
    args = parser.parse_args()
    runner = (
        run_final_acceptance_explanation_audit
        if args.final_acceptance
        else run_completion_audit
    )
    result = runner(**({"output_directory": args.output} if args.output else {}))
    print(result["summary"])
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
