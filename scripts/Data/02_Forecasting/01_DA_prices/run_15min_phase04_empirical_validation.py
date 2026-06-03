from __future__ import annotations

import json

from quarterhour_da import QuarterHourDAExtensionConfig, run_phase04_empirical_validation


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    run_dir = run_phase04_empirical_validation(config)
    payload = {
        "run_dir": str(run_dir),
        "run_summary_json": str(run_dir / "run_summary.json"),
        "shape_only_metrics_csv": str(run_dir / "shape_only_metrics.csv"),
        "reconstructed_price_metrics_csv": str(run_dir / "reconstructed_price_metrics.csv"),
        "realistic_anchor_availability_csv": str(run_dir / "realistic_anchor_availability.csv"),
        "recommended_model_summary_csv": str(run_dir / "recommended_model_summary.csv"),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
