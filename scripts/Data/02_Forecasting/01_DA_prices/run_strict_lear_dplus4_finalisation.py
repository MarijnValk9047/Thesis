from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "scripts/Data/02_Forecasting/01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from quarterhour_da.strict_lear_finalisation import run_finalisation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalise Strict LEAR hourly/QH D..D+4 point forecasts and coupled 30/10 scenarios.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/configs/strict_lear_dplus4_finalisation.yaml"),
    )
    parser.add_argument("--legacy-cleaned-root", type=Path, required=True)
    parser.add_argument("--historical-qh-csv", type=Path, required=True)
    parser.add_argument(
        "--refreshed-input-root",
        type=Path,
        default=Path("data/02_Forecasting/01_DA_prices/scenario_evaluation/20260729_strict_inputs"),
    )
    parser.add_argument("--refreshed-res-cleaned-root", type=Path, required=True)
    parser.add_argument("--refreshed-qh-csv", type=Path, default=None)
    parser.add_argument("--horizon-policy-csv", type=Path, required=True)
    parser.add_argument("--anchor-seed-predictions", type=Path, default=None)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/02_Forecasting/01_DA_prices/scenario_evaluation/strict_lear_dplus4_finalisation"),
    )
    parser.add_argument("--run-id", type=str, default="")
    parser.add_argument("--resume-run", action="store_true", help="Resume an explicitly named incomplete generated run.")
    return parser.parse_args()


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def main() -> int:
    args = parse_args()
    run_id = args.run_id.strip() or datetime.now(UTC).strftime("%Y%m%d_%H%M%S_strict_lear_dplus4_full")
    output_root = _resolve(args.output_root)
    run_dir = output_root / run_id
    summary = run_finalisation(
        repo_root=REPO_ROOT,
        config_path=_resolve(args.config),
        run_dir=run_dir,
        legacy_cleaned_root=_resolve(args.legacy_cleaned_root),
        historical_qh_path=_resolve(args.historical_qh_csv),
        refreshed_input_root=_resolve(args.refreshed_input_root),
        refreshed_qh_path=_resolve(args.refreshed_qh_csv) if args.refreshed_qh_csv else None,
        refreshed_res_cleaned_root=_resolve(args.refreshed_res_cleaned_root),
        horizon_policy_csv=_resolve(args.horizon_policy_csv),
        anchor_seed_predictions=_resolve(args.anchor_seed_predictions) if args.anchor_seed_predictions else None,
        resume_run=bool(args.resume_run),
    )
    print(f"Completed Strict LEAR D..D+4 finalisation: {run_dir}")
    print(f"Evaluation origins: {summary['selected_evaluation_origins']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
