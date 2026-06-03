from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.procurement_repair_test import run_procurement_repair_test


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the one-week Phase E4b procurement repair test under weekly hard-band production obligations on one selected common-support test week.",
    )
    parser.add_argument("--config", required=True, help="Path to the hydrogen config YAML.")
    parser.add_argument("--week-id", required=True, help="Selected common-support test week label.")
    parser.add_argument("--artifact", required=True, help="Phase E4b requires the LEAR Strict hourly D-only artifact.")
    parser.add_argument("--alpha", type=float, required=True, help="CVaR alpha. Phase E4b requires 0.95.")
    parser.add_argument("--gamma", type=float, required=True, help="CVaR gamma. Phase E4b requires 0.25.")
    parser.add_argument("--target-mode", required=True, help="Phase E4b requires weekly_hard_band_target.")
    parser.add_argument("--daily-min-fraction", type=float, required=True, help="Daily minimum fraction of daily_target_kg.")
    parser.add_argument("--daily-max-fraction", type=float, required=True, help="Daily maximum fraction of daily_target_kg.")
    parser.add_argument("--repair-policies", nargs="+", required=True, help="Repair policies to evaluate.")
    parser.add_argument("--firm-baseline-bid-price", type=float, required=True, help="High-price DA bid for the firm baseline floor.")
    parser.add_argument("--emergency-import-price", type=float, required=True, help="Emergency import fallback price.")
    parser.add_argument("--reporting-mode", default="machine_only", help="Phase E4b supports machine_only only.")
    parser.add_argument("--run-slug", required=True, help="Run slug to embed in the run folder name.")
    parser.add_argument("--output-root", default=None, help="Optional output root override.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if str(args.target_mode).strip() != "weekly_hard_band_target":
        raise ValueError(f"Phase E4b requires --target-mode weekly_hard_band_target, got {args.target_mode!r}.")
    if str(args.reporting_mode).strip() != "machine_only":
        raise ValueError(f"Phase E4b requires --reporting-mode machine_only, got {args.reporting_mode!r}.")
    config = load_hydrogen_config(args.config)
    result = run_procurement_repair_test(
        config=config,
        week_id=str(args.week_id),
        artifact_id=str(args.artifact),
        alpha=float(args.alpha),
        gamma=float(args.gamma),
        daily_min_fraction=float(args.daily_min_fraction),
        daily_max_fraction=float(args.daily_max_fraction),
        repair_policies=[str(value) for value in args.repair_policies],
        firm_baseline_bid_price=float(args.firm_baseline_bid_price),
        emergency_import_price=float(args.emergency_import_price),
        run_slug=str(args.run_slug),
        output_root=Path(args.output_root) if args.output_root else None,
    )
    print("run_dir=", result.run_dir)
    print("daily_rows=", int(result.daily_metrics.shape[0]))
    print("weekly_rows=", int(result.weekly_metrics.shape[0]))
    print("comparison_rows=", int(result.comparison.shape[0]))


if __name__ == "__main__":
    main()
