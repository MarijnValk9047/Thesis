from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.bidding_backtest import run_real_scenario_selected_origin_suite
from hydrogen.plant_parameters import load_hydrogen_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a selected-origin real-scenario integration dry-run suite.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the hydrogen config YAML.",
    )
    parser.add_argument(
        "--artifact-ids",
        nargs="+",
        required=True,
        help="One or more scenario artifact IDs from scenario_catalog.yaml.",
    )
    parser.add_argument(
        "--max-origins-per-artifact",
        type=int,
        default=5,
        help="Maximum selected origins per artifact. Phase 6c expects 3 to 5.",
    )
    parser.add_argument(
        "--selection-method",
        default="price_diagnostics",
        help="Origin selection method. Supported: price_diagnostics.",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Optional output root override.",
    )
    parser.add_argument(
        "--dry-run-label",
        default="integration_candidate",
        help="Run label suffix used in nested origin runs.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_hydrogen_config(args.config)
    result = run_real_scenario_selected_origin_suite(
        config=config,
        artifact_ids=[str(value) for value in args.artifact_ids],
        max_origins_per_artifact=int(args.max_origins_per_artifact),
        selection_method=str(args.selection_method),
        output_root=Path(args.output_root) if args.output_root else None,
        dry_run_label=str(args.dry_run_label),
    )
    print("suite_dir=", result.suite_dir)
    print("origin_count=", int(result.metrics_by_origin.shape[0]))
    print("artifacts=", sorted(result.metrics_by_origin["artifact_id"].astype(str).unique().tolist()))


if __name__ == "__main__":
    main()
