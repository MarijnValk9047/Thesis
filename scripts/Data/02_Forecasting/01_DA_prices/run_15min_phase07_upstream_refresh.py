from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.append(str(PACKAGE_ROOT))

from quarterhour_da import QuarterHourDAExtensionConfig, run_phase07_upstream_refresh


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    run_dir = run_phase07_upstream_refresh(config)
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "run_summary_json": str(run_dir / "run_summary.json"),
                "freshness_summary_csv": str(run_dir / "freshness_summary.csv"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
