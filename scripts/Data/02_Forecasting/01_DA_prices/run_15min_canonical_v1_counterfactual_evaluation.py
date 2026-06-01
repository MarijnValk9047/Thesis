from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from quarterhour_da import run_canonical_v1_counterfactual_evaluation


def main() -> int:
    run_dir = run_canonical_v1_counterfactual_evaluation()
    print(f"canonical_v1 counterfactual quarter-hour evaluation completed: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
