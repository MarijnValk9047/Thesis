from __future__ import annotations

import json

from quarterhour_da import QuarterHourDAExtensionConfig, run_phase06_milp_exports


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    run_dir = run_phase06_milp_exports(config)
    payload = {
        "run_dir": str(run_dir),
        "run_summary_json": str(run_dir / "run_summary.json"),
        "export_manifest_csv": str(run_dir / "export_manifest.csv"),
        "export_root": str(run_dir / "milp_ready_exports"),
        "legacy_exploratory_only": True,
        "warning": "Phase 6 mixed realized/forecast exports are exploratory only and are not authorised thesis-grade 15-minute actual market truth.",
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
