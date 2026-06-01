from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.lear_strict_cvar_opportunity_diagnostic import (
    run_lear_strict_cvar_opportunity_diagnostic,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase E4d: LEAR Strict full-year support audit, CVaR opportunity screening, and one-week diagnostic."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--audit-start", required=True)
    parser.add_argument("--audit-end", required=True)
    parser.add_argument("--alpha", type=float, required=True)
    parser.add_argument("--gammas", nargs="+", type=float, required=True)
    parser.add_argument("--production-variants", nargs="+", required=True)
    parser.add_argument("--daily-min-fraction", type=float, required=True)
    parser.add_argument("--daily-max-fraction", type=float, required=True)
    parser.add_argument("--emergency-import-price", type=float, required=True)
    parser.add_argument("--reporting-mode", default="machine_only")
    parser.add_argument("--safe-resume", default="true")
    parser.add_argument("--resume-run-dir", default=None)
    parser.add_argument("--run-slug", default="phase_e4d_lear_strict_cvar_opportunity_diagnostic")
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
        raise ValueError(f"Phase E4d requires --reporting-mode machine_only, got {args.reporting_mode!r}.")
    result = run_lear_strict_cvar_opportunity_diagnostic(
        config=args.config,
        artifact_id=str(args.artifact),
        audit_start=str(args.audit_start),
        audit_end=str(args.audit_end),
        alpha=float(args.alpha),
        gammas=[float(value) for value in args.gammas],
        production_variants=[str(value) for value in args.production_variants],
        daily_min_fraction=float(args.daily_min_fraction),
        daily_max_fraction=float(args.daily_max_fraction),
        emergency_import_price=float(args.emergency_import_price),
        safe_resume=_parse_bool(args.safe_resume),
        resume_run_dir=None if args.resume_run_dir in {None, "", "none", "null"} else Path(args.resume_run_dir),
        run_slug=str(args.run_slug),
    )
    print(f"run_dir={result.run_dir}")
    print(f"screening_rows={len(result.screening)}")
    print(f"daily_rows={len(result.daily_metrics)}")
    print(f"weekly_rows={len(result.weekly_metrics)}")


if __name__ == "__main__":
    main()
