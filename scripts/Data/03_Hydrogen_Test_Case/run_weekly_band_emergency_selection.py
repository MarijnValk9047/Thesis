from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.weekly_band_emergency_selection import run_weekly_band_emergency_selection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase E4c: compare weekly hard production with daily bands on vs off under emergency import fallback."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--week-ids", nargs="+", required=True)
    parser.add_argument("--artifacts", nargs="+", required=True)
    parser.add_argument("--alpha", type=float, required=True)
    parser.add_argument("--gammas", nargs="+", type=float, required=True)
    parser.add_argument("--production-variants", nargs="+", required=True)
    parser.add_argument("--daily-min-fraction", type=float, required=True)
    parser.add_argument("--daily-max-fraction", type=float, required=True)
    parser.add_argument("--emergency-import-price", type=float, required=True)
    parser.add_argument("--reporting-mode", default="machine_only")
    parser.add_argument("--safe-resume", default="true")
    parser.add_argument("--resume-run-dir", default=None)
    parser.add_argument("--run-slug", default="phase_e4c_band_on_off_emergency_selection")
    return parser.parse_args()


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"Unable to parse boolean value: {value!r}")


def main() -> None:
    args = parse_args()
    if str(args.reporting_mode).strip().lower() != "machine_only":
        raise ValueError(f"Phase E4c requires --reporting-mode machine_only, got {args.reporting_mode!r}.")
    result = run_weekly_band_emergency_selection(
        config=args.config,
        week_ids=[str(value) for value in args.week_ids],
        artifact_ids=[str(value) for value in args.artifacts],
        cvar_alpha=float(args.alpha),
        gamma_values=[float(value) for value in args.gammas],
        production_variants=[str(value) for value in args.production_variants],
        daily_min_fraction=float(args.daily_min_fraction),
        daily_max_fraction=float(args.daily_max_fraction),
        emergency_import_price=float(args.emergency_import_price),
        safe_resume=_parse_bool(args.safe_resume),
        resume_run_dir=None if args.resume_run_dir in {None, "", "none", "null"} else Path(args.resume_run_dir),
        run_slug=str(args.run_slug),
    )
    print(f"run_dir={result.run_dir}")
    print(f"daily_rows={len(result.daily_metrics)}")
    print(f"weekly_rows={len(result.weekly_metrics)}")
    print(f"decision_rows={len(result.model_decision_summary)}")


if __name__ == "__main__":
    main()
