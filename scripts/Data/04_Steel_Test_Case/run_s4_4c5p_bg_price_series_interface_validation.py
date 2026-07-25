"""Run the pre-DAM price-series interface validation."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_bg_price_series_interface_validation import (
    run_price_series_interface_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase4-parent", default=None)
    parser.add_argument("--flat-run", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = run_price_series_interface_validation(
        **({"phase4_parent": args.phase4_parent} if args.phase4_parent else {}),
        **({"flat_interface_run": args.flat_run} if args.flat_run else {}),
        **({"output_directory": args.output} if args.output else {}),
    )
    print(result["summary"])
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
