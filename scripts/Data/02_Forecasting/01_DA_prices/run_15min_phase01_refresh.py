from __future__ import annotations

import json

from quarterhour_da import QuarterHourDAExtensionConfig, run_phase01_refresh


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    run_dir = run_phase01_refresh(config)
    payload = {
        "run_dir": str(run_dir),
        "run_summary_json": str(run_dir / "run_summary.json"),
        "foundation_contracts_csv": str(run_dir / "foundation_contracts.csv"),
        "data_refresh_summary_csv": str(run_dir / "data_refresh_summary.csv"),
        "command_status_summary_csv": str(run_dir / "command_status_summary.csv"),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
