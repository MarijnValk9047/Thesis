from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.full_year_repaired_lear_strict import (
    DEFAULT_PHASE_E5_RUN_SLUG,
    run_full_year_repaired_lear_strict,
)
from hydrogen.production_target import TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET


def _bool_arg(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Unable to parse boolean argument from {value!r}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase E5: full-year optimisation run for repaired LEAR Strict with weekly hard target, bands off, emergency fallback.",
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--test-start", required=True)
    parser.add_argument("--test-end", required=True)
    parser.add_argument("--alpha", type=float, required=True)
    parser.add_argument("--gammas", nargs="+", type=float, required=True)
    parser.add_argument("--target-mode", required=True)
    parser.add_argument("--emergency-import-price", type=float, required=True)
    parser.add_argument("--include-price-insensitive-benchmark", type=_bool_arg, default=True)
    parser.add_argument("--include-perfect-foresight-benchmark", type=_bool_arg, default=True)
    parser.add_argument("--reuse-true-pf-from", default=None)
    parser.add_argument("--reporting-mode", default="machine_only")
    parser.add_argument("--safe-resume", type=_bool_arg, default=True)
    parser.add_argument("--run-slug", default=DEFAULT_PHASE_E5_RUN_SLUG)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--resume-run-dir", default=None)
    parser.add_argument("--gamma-filter", nargs="+", type=float, default=None)
    parser.add_argument("--chunk-start", default=None)
    parser.add_argument("--chunk-end", default=None)
    parser.add_argument("--max-new-solves", type=int, default=None)
    parser.add_argument("--day-output-mode", default="full")
    parser.add_argument("--audit-days", default="")
    parser.add_argument("--checkpoint-every-n-solves", type=int, default=10)
    parser.add_argument(
        "--target-accounting-policy",
        default=TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = run_full_year_repaired_lear_strict(
        config=args.config,
        artifact_id=str(args.artifact),
        test_start=str(args.test_start),
        test_end=str(args.test_end),
        alpha=float(args.alpha),
        gammas=[float(value) for value in args.gammas],
        target_mode=str(args.target_mode),
        emergency_import_price=float(args.emergency_import_price),
        include_price_insensitive_benchmark=bool(args.include_price_insensitive_benchmark),
        include_perfect_foresight_benchmark=bool(args.include_perfect_foresight_benchmark),
        reuse_true_pf_from=Path(args.reuse_true_pf_from) if args.reuse_true_pf_from else None,
        reporting_mode=str(args.reporting_mode),
        safe_resume=bool(args.safe_resume),
        run_slug=str(args.run_slug),
        output_root=Path(args.output_root) if args.output_root else None,
        resume_run_dir=Path(args.resume_run_dir) if args.resume_run_dir else None,
        gamma_filter=[float(value) for value in args.gamma_filter] if args.gamma_filter else None,
        chunk_start=str(args.chunk_start) if args.chunk_start else None,
        chunk_end=str(args.chunk_end) if args.chunk_end else None,
        max_new_solves=None if args.max_new_solves is None else int(args.max_new_solves),
        day_output_mode=str(args.day_output_mode),
        audit_days=[day.strip() for day in str(args.audit_days).split(",") if day.strip()],
        checkpoint_every_n_solves=int(args.checkpoint_every_n_solves),
        target_accounting_policy=str(args.target_accounting_policy),
    )
    print(f"run_dir={result.run_dir}")
    print(f"daily_rows={int(result.daily_metrics.shape[0])}")
    print(f"weekly_rows={int(result.weekly_metrics.shape[0])}")
    print(f"monthly_rows={int(result.monthly_metrics.shape[0])}")
    print(f"annual_rows={int(result.annual_metrics_by_gamma.shape[0])}")


if __name__ == "__main__":
    main()
