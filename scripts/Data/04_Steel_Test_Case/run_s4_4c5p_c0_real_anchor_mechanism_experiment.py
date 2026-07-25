from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


STEEL_ROOT = Path(__file__).resolve().parent
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_c0_real_anchor_mechanism_experiment import (
    DEFAULT_CONFIG_PATH,
    run_mechanism_experiment,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded C0 real-anchor development-mechanism experiment."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--forecast-run-root", required=True)
    parser.add_argument("--scratch-root", default=None)
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()
    summary = run_mechanism_experiment(
        args.config,
        forecast_run_root=args.forecast_run_root,
        scratch_root=args.scratch_root,
        aggregate_only=args.aggregate_only,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
