"""CLI for the bounded Phase-6D physical tie-break runtime audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
STEEL_ROOT = Path(__file__).resolve().parent
for path in (REPO_ROOT, STEEL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from steel.s4_4c6_physical_tiebreak_runtime_audit import (  # noqa: E402
    AUDIT_CONFIG,
    compare_primary,
    finalise_audit,
    run_variant,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=AUDIT_CONFIG)
    parser.add_argument(
        "--mode", choices=("run", "compare-primary", "finalise"), default="run"
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--variant", choices=("V0", "V1", "V2", "V3", "V4")
    )
    parser.add_argument("--repeat-id", type=int, default=1)
    parser.add_argument("--day-count", type=int, choices=(1, 2), default=1)
    parser.add_argument("--arm", choices=("B_qh_flat", "C_qh_shape"), default="B_qh_flat")
    args = parser.parse_args()
    if args.mode == "finalise":
        result = finalise_audit(args.config)
    elif args.mode == "compare-primary":
        if not args.run_id:
            parser.error("--run-id is required in compare-primary mode")
        result = compare_primary(args.config, run_id=args.run_id)
    else:
        if not args.run_id:
            parser.error("--run-id is required in run mode")
        if args.variant is None:
            parser.error("--variant is required in run mode")
        result = run_variant(
            args.config,
            run_id=args.run_id,
            variant=args.variant,
            repeat_id=args.repeat_id,
            day_count=args.day_count,
            arm=args.arm,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {
        "pass",
        "insufficient",
        "complete_no_promotion",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
