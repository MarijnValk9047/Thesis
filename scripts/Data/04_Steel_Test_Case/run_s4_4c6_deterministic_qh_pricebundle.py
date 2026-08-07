from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from steel.s4_4c6_deterministic_qh_pricebundle import build_annual_qh_pricebundle  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the annual deterministic QH price bundle only.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_annual_qh_pricebundle(output=args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
