from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.append(str(PACKAGE_ROOT))

from quarterhour_da import QuarterHourDAExtensionConfig, run_phase07_realistic_track_a


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    run_dir = run_phase07_realistic_track_a(config)
    payload = {
        "run_dir": str(run_dir),
        "run_summary_json": str(run_dir / "run_summary.json"),
        "status_summary_csv": str(run_dir / "status_summary.csv"),
        "hourly_anchor_feasibility_csv": str(run_dir / "hourly_anchor_feasibility.csv"),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
