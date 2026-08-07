from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
STEEL_ROOT = ROOT / "scripts" / "Data" / "04_Steel_Test_Case"
for candidate in (ROOT, STEEL_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from steel.s4_4c6_deterministic_c0_four_week_reporting import (  # noqa: E402
    CONFIG_PATH,
    run_four_week_reporting,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--run-id", default="c0_c1_four_example_weeks_v1")
    args = parser.parse_args()
    result = run_four_week_reporting(config_path=args.config, run_id=args.run_id)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
