from __future__ import annotations

import json

from quarterhour_da import QuarterHourDAExtensionConfig, run_phase03_anchor_selection


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    run_dir = run_phase03_anchor_selection(config)
    payload = {
        "run_dir": str(run_dir),
        "run_summary_json": str(run_dir / "run_summary.json"),
        "candidate_availability_csv": str(run_dir / "candidate_availability.csv"),
        "candidate_selection_summary_csv": str(run_dir / "candidate_selection_summary.csv"),
        "selected_anchor_models_csv": str(run_dir / "selected_anchor_models.csv"),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
