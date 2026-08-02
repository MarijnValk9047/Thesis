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

from steel.s4_4c6_phase6b_hourly_da_bid_clear_redispatch import run_phase6b


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase-6B hourly steel DA engineering validation.")
    parser.add_argument(
        "--config",
        default="scripts/Data/04_Steel_Test_Case/configs/steel_c6_phase6b_hourly_da_bid_clear_redispatch.yaml",
    )
    parser.add_argument("--fixture", choices=("day", "week", "all"), default="all")
    args = parser.parse_args()
    print(json.dumps(run_phase6b(args.config, fixture=args.fixture), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
