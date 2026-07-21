"""Run the bounded fixed-reference deterministic cost sensitivity family."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_be_fixed_reference_cost_sensitivities import (
    run_bounded_fixed_reference_cost_sensitivities,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--central-parent", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--reaggregate", action="store_true")
    args = parser.parse_args()
    result = run_bounded_fixed_reference_cost_sensitivities(
        **({"config_path": args.config} if args.config else {}),
        **({"central_parent": args.central_parent} if args.central_parent else {}),
        **({"output_root": args.output_root} if args.output_root else {}),
        reaggregate=args.reaggregate,
    )
    print(result["summary"])
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
