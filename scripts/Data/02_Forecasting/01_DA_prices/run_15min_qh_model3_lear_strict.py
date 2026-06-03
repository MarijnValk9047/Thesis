from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from quarterhour_da.config import QuarterHourDAExtensionConfig
from quarterhour_da.model3_lear_strict import (
    DEFAULT_LEAR_STRICT_ANCHOR_RUN_ID,
    DEFAULT_OBSERVED_RUN_ID,
    run_qh_model3_lear_strict,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run QH_MODEL_3 = LEAR_STRICT hourly anchor + zero-mean quarter-hour mean-shape deviation."
    )
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--max-origins", type=int, default=None)
    parser.add_argument("--output-tag", type=str, default="")
    parser.add_argument("--observed-run-id", type=str, default=DEFAULT_OBSERVED_RUN_ID)
    parser.add_argument("--anchor-run-id", type=str, default=DEFAULT_LEAR_STRICT_ANCHOR_RUN_ID)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run_dir = run_qh_model3_lear_strict(
        QuarterHourDAExtensionConfig(),
        output_tag=args.output_tag,
        check_only=bool(args.check_only),
        max_origins=args.max_origins,
        observed_run_id=args.observed_run_id,
        anchor_run_id=args.anchor_run_id,
    )
    payload = {
        "run_dir": str(run_dir),
        "check_only": bool(args.check_only),
        "max_origins": args.max_origins,
        "output_tag": str(args.output_tag or ""),
        "observed_run_id": str(args.observed_run_id),
        "anchor_run_id": str(args.anchor_run_id),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
