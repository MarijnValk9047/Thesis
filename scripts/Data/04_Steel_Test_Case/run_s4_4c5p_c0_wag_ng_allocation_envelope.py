from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


STEEL_ROOT = Path(__file__).resolve().parent
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_c0_wag_ng_allocation_envelope import (
    DEFAULT_CONFIG_PATH,
    run_allocation_envelope,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded C0 WAG/NG cost-optimal allocation envelope."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument(
        "--forecast-run-root",
        default=os.environ.get("STEEL_DA_FORECAST_RUN_ROOT"),
    )
    parser.add_argument("--scratch-root", default=None)
    parser.add_argument("--aggregate-only", action="store_true")
    parser.add_argument("--diagnostic-case-id", default=None)
    parser.add_argument("--diagnostic-replan-index", type=int, default=None)
    parser.add_argument("--oracle-only", action="store_true")
    args = parser.parse_args()
    if not args.forecast_run_root:
        parser.error("--forecast-run-root or STEEL_DA_FORECAST_RUN_ROOT is required")
    summary = run_allocation_envelope(
        args.config,
        forecast_run_root=args.forecast_run_root,
        scratch_root=args.scratch_root,
        aggregate_only=args.aggregate_only,
        diagnostic_case_id=args.diagnostic_case_id,
        diagnostic_replan_index=args.diagnostic_replan_index,
        oracle_only=args.oracle_only,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] in {"pass", "diagnostic_pass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
