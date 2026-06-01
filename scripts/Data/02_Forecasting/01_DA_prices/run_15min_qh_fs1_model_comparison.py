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
    run_dir = run_phase07_realistic_track_a(config, horizon_days=5)
    payload = {
        "run_label": "qh_fs1_model_comparison_manual_contract",
        "implementation_note": "Thin CLI alias over run_phase07_realistic_track_a using minimal_realistic_anchor_features_v1 for LEAR and XGBoost candidate generation on a rolling-origin D..D+4 horizon.",
        "run_dir": str(run_dir),
        "run_summary_json": str(run_dir / "run_summary.json"),
        "predictions_long_csv": str(run_dir / "predictions_long.csv"),
        "reconstructed_price_metrics_csv": str(run_dir / "reconstructed_price_metrics.csv"),
        "model_configuration_summary_csv": str(run_dir / "model_configuration_summary.csv"),
        "feature_column_summary_csv": str(run_dir / "feature_column_summary.csv"),
        "recommended_model_summary_csv": str(run_dir / "recommended_model_summary.csv"),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
