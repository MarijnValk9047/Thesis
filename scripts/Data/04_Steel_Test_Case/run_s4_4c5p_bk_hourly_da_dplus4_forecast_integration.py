"""Run governed hourly D-D+4 point-forecast integration validation."""

from __future__ import annotations

import argparse

from steel.s4_4c5p_bk_hourly_da_dplus4_forecast_integration import (
    run_hourly_da_dplus4_forecast_integration,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forecast-run-root", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = run_hourly_da_dplus4_forecast_integration(
        forecast_run_root=args.forecast_run_root,
        **({"output_directory": args.output} if args.output else {}),
    )
    print(result["summary"])
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
