from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from quarterhour_da.config import QuarterHourDAExtensionConfig
from quarterhour_da.scenario_generation_qh import qh_residual_availability_report


def main() -> int:
    report = qh_residual_availability_report(QuarterHourDAExtensionConfig())
    output_root = (
        REPO_ROOT
        / "data"
        / "02_Forecasting"
        / "01_DA_prices"
        / "quarterhour_da"
        / "finalisation_runs"
        / "qh_scenario_preflight"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_qh_scenario_preflight")
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "qh_residual_availability_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    rows = []
    for item in report.get("policies", []):
        rows.append(
            {
                "calibration_policy": str(item.get("calibration_policy")),
                "calibration_splits_used": ",".join([str(x) for x in item.get("calibration_splits_used", [])]),
                "residual_rows": int(item.get("residual_rows", 0)),
                "residual_source_days": int(item.get("residual_source_days", 0)),
                "sufficient_for_generation": bool(item.get("sufficient_for_generation", False)),
            }
        )
    pd.DataFrame(rows).to_csv(run_dir / "qh_residual_availability_summary.csv", index=False)
    print(json.dumps({"run_dir": str(run_dir), "status": "completed"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
