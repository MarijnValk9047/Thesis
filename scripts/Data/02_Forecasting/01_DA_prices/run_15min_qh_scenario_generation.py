from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from quarterhour_da.config import QuarterHourDAExtensionConfig
from quarterhour_da.scenario_generation_qh import (
    DEFAULT_MODEL3_RUN_ID,
    DEFAULT_PHASE27_RUN_ID,
    run_qh_scenario_generation,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate quarter-hour DA scenarios for all three observed-QH models.")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--all-three-models", action="store_true")
    parser.add_argument("--n-raw", type=int, default=30)
    parser.add_argument("--n-final", type=int, default=15)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--horizon-mode", type=str, default="D_ONLY", choices=["D_ONLY", "D_PLUS_4"])
    parser.add_argument("--calibration-policy", type=str, default="validation_only", choices=["validation_only", "train_validation"])
    parser.add_argument("--calibration-rationale", type=str, default="")
    parser.add_argument("--max-origins", type=int, default=None)
    parser.add_argument("--output-tag", type=str, default="")
    parser.add_argument("--phase27-run-id", type=str, default=DEFAULT_PHASE27_RUN_ID)
    parser.add_argument("--model3-run-id", type=str, default=DEFAULT_MODEL3_RUN_ID)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run_dir = run_qh_scenario_generation(
        QuarterHourDAExtensionConfig(),
        check_only=bool(args.check_only),
        smoke=bool(args.smoke),
        all_three_models=bool(args.all_three_models),
        n_raw_scenarios=int(args.n_raw),
        n_final_scenarios=int(args.n_final),
        random_seed=int(args.random_seed),
        horizon_mode=str(args.horizon_mode),
        calibration_policy=str(args.calibration_policy),
        calibration_rationale=str(args.calibration_rationale or ""),
        max_origins=args.max_origins,
        output_tag=str(args.output_tag or ""),
        phase27_run_id=str(args.phase27_run_id),
        model3_run_id=str(args.model3_run_id),
    )
    payload = {
        "run_dir": str(run_dir),
        "check_only": bool(args.check_only),
        "smoke": bool(args.smoke),
        "all_three_models": bool(args.all_three_models),
        "n_raw": int(args.n_raw),
        "n_final": int(args.n_final),
        "random_seed": int(args.random_seed),
        "horizon_mode": str(args.horizon_mode),
        "calibration_policy": str(args.calibration_policy),
        "calibration_rationale": str(args.calibration_rationale or ""),
        "max_origins": args.max_origins,
        "phase27_run_id": str(args.phase27_run_id),
        "model3_run_id": str(args.model3_run_id),
        "output_tag": str(args.output_tag or ""),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
