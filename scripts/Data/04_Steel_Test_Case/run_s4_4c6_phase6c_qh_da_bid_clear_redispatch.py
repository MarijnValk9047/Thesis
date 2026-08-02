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

from steel.s4_4c6_phase6c_qh_da_bid_clear_redispatch import run_phase6c, run_phase6c_smoke


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase-6C QH steel DA validation.")
    parser.add_argument(
        "--config",
        default="scripts/Data/04_Steel_Test_Case/configs/steel_c6_phase6c_qh_da_bid_clear_redispatch.yaml",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    result = (
        run_phase6c_smoke(args.config)
        if args.smoke
        else run_phase6c(args.config, resume=args.resume)
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
