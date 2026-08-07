"""Run the governed deterministic C0 temporal example-week validation."""

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

from steel.s4_4c6_deterministic_c0_temporal_validation import (  # noqa: E402
    CONFIG_PATH,
    run_c0_temporal_validation,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--run-id", default="c0_high_volatility_week_v1")
    parser.add_argument("--week-regime", default=None)
    args = parser.parse_args()
    result = run_c0_temporal_validation(
        config_path=args.config,
        run_id=args.run_id,
        week_regime=args.week_regime,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
