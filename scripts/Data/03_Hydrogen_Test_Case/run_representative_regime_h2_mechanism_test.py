"""CLI for the short representative-regime H2 mechanism test."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys


SCRIPT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parents[2]
for path in (REPO_ROOT, SCRIPT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hydrogen.representative_regime_mechanism_test import (  # noqa: E402
    DEFAULT_CONFIG,
    preflight,
    run_mechanism_test,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", choices=("preflight", "run"), default="preflight")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--cases", nargs="*", default=[])
    parser.add_argument("--arms", nargs="*", default=[])
    parser.add_argument("--policies", nargs="*", default=[])
    args = parser.parse_args()
    if args.mode == "preflight":
        print(json.dumps(preflight(args.config), indent=2, sort_keys=True))
        return 0
    run_id = args.run_id.strip() or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    result = run_mechanism_test(
        args.config,
        run_id=run_id,
        selected_cases=args.cases,
        selected_arms=args.arms,
        selected_policies=args.policies,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["summary"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
