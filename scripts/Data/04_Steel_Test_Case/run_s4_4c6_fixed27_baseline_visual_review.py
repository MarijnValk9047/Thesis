"""CLI for the fixed-27 C6 baseline visual review."""

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

from steel.s4_4c6_fixed27_baseline_visual_review import (  # noqa: E402
    VISUAL_REVIEW_CONFIG,
    preflight_fixed27_visual_review,
    run_fixed27_visual_review,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=VISUAL_REVIEW_CONFIG)
    parser.add_argument("--mode", choices=("preflight", "run"), default="preflight")
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--reuse-case-checkpoint",
        action="append",
        default=[],
        metavar="CASE_ID=PATH",
        help="Reuse a post-physical-check checkpoint from an earlier diagnostic.",
    )
    args = parser.parse_args()
    if args.mode == "preflight":
        result = preflight_fixed27_visual_review(args.config)
    else:
        run_id = args.run_id.strip() or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        reusable: dict[str, Path] = {}
        for raw in args.reuse_case_checkpoint:
            case_id, separator, raw_path = raw.partition("=")
            if not separator or not case_id or not raw_path:
                parser.error("--reuse-case-checkpoint requires CASE_ID=PATH.")
            reusable[case_id] = Path(raw_path)
        result = run_fixed27_visual_review(
            args.config,
            run_id=run_id,
            reusable_case_checkpoints=reusable,
        )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("decision") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
