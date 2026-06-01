from __future__ import annotations

import json

from quarterhour_da import QuarterHourDAExtensionConfig, run_phase02_shape_targets


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    run_dir = run_phase02_shape_targets(config)
    payload = {
        "run_dir": str(run_dir),
        "run_summary_json": str(run_dir / "run_summary.json"),
        "shape_target_long_csv": str(run_dir / "shape_target_long.csv"),
        "split_summary_csv": str(run_dir / "split_summary.csv"),
        "quarter_diagnostics_csv": str(run_dir / "quarter_diagnostics.csv"),
        "hour_quarter_diagnostics_csv": str(run_dir / "hour_quarter_diagnostics.csv"),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
