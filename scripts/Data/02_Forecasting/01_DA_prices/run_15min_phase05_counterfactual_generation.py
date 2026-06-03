from __future__ import annotations

import json

from quarterhour_da import QuarterHourDAExtensionConfig, run_phase05_counterfactual_generation


def main() -> int:
    config = QuarterHourDAExtensionConfig()
    run_dir = run_phase05_counterfactual_generation(config)
    payload = {
        "run_dir": str(run_dir),
        "run_summary_json": str(run_dir / "run_summary.json"),
        "counterfactual_generation_summary_csv": str(run_dir / "counterfactual_generation_summary.csv"),
        "counterfactual_realized_15min_long_csv": str(run_dir / "counterfactual_realized_15min_long.csv"),
        "counterfactual_shape_forecast_input_15min_long_csv": str(run_dir / "counterfactual_shape_forecast_input_15min_long.csv"),
        "legacy_exploratory_only": True,
        "warning": "Phase 5 realized-path outputs are exploratory only and are not authorised thesis-grade 15-minute actual market truth.",
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
