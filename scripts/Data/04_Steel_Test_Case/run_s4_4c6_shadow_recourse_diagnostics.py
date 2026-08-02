"""CLI for the bounded non-final C1 shadow recourse diagnosis."""

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

from steel.s4_4c6_shadow_recourse_diagnostics import (  # noqa: E402
    SHADOW_RECOURSE_CONFIG,
    prepare_shadow_recourse_diagnostic,
    run_shadow_recourse_diagnostics,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(SHADOW_RECOURSE_CONFIG))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = (
        prepare_shadow_recourse_diagnostic(
            args.config, run_id=args.run_id, resume=args.resume
        )
        if args.prepare_only
        else run_shadow_recourse_diagnostics(
            args.config, run_id=args.run_id, resume=args.resume
        )
    )
    printable = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in result.items()
        if key not in {"config", "inputs"}
    }
    print(json.dumps(printable, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
