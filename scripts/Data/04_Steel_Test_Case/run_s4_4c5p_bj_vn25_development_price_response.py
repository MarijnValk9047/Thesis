"""Run bounded VN25 development price-response validation."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_bj_vn25_development_price_response import (
    run_vn25_development_price_response,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = run_vn25_development_price_response(
        **({"output_directory": args.output} if args.output else {})
    )
    print(result["summary"])
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
