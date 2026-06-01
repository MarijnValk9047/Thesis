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
from quarterhour_da.three_model_comparison import run_qh_three_model_comparison


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run observed-QH three-model comparison artifacts.")
    parser.add_argument("--model3-run-id", type=str, required=True)
    parser.add_argument("--phase27-run-id", type=str, default=None)
    parser.add_argument("--include-operational", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run_dir = run_qh_three_model_comparison(
        QuarterHourDAExtensionConfig(),
        model3_run_id=args.model3_run_id,
        phase27_run_id=args.phase27_run_id,
        include_operational=bool(args.include_operational),
    )
    payload = {
        "run_dir": str(run_dir),
        "model3_run_id": str(args.model3_run_id),
        "phase27_run_id": str(args.phase27_run_id) if args.phase27_run_id else None,
        "include_operational": bool(args.include_operational),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
