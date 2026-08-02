"""CLI for the governed Phase-6D EAF heat-state one-day validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STEEL_ROOT = Path(__file__).resolve().parent
for path in (REPO_ROOT, STEEL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from steel.s4_4c6_phase6d_eaf_heat_state_one_day import (  # noqa: E402
    PHASE6D_CONFIG,
    run_phase6d,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=PHASE6D_CONFIG)
    parser.add_argument(
        "--gate-a-only",
        action="store_true",
        help="Run only Gate A; Gate B remains gated and unexecuted.",
    )
    args = parser.parse_args()
    summary = run_phase6d(
        args.config,
        include_gate_b=not args.gate_a_only,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "pass" or args.gate_a_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
