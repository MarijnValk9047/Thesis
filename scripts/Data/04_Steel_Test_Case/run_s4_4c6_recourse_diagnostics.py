"""CLI for the bounded S0 C1 recourse-cause diagnostics."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
STEEL_ROOT = Path(__file__).resolve().parent
for path in (REPO_ROOT, STEEL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from steel.s4_4c6_recourse_diagnostics import (  # noqa: E402
    RECOURSE_DIAGNOSTIC_CONFIG,
    prepare_recourse_diagnostic,
    run_recourse_diagnostics,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=RECOURSE_DIAGNOSTIC_CONFIG)
    parser.add_argument("--mode", choices=("prepare", "run"), default="prepare")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run_id = args.run_id.strip() or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    if args.mode == "prepare":
        prepared = prepare_recourse_diagnostic(
            args.config, run_id=run_id, resume=bool(args.resume)
        )
        result = {
            "status": "prepared_no_solver_runs",
            "output": str(prepared["output"]),
            "output_declaration": prepared["declaration"],
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    result = run_recourse_diagnostics(
        args.config, run_id=run_id, resume=bool(args.resume)
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["summary"]["status"].startswith("complete_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
