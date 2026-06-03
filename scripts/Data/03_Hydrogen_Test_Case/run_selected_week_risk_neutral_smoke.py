from __future__ import annotations

import argparse
from pathlib import Path

from hydrogen.plant_parameters import load_hydrogen_config
from hydrogen.selected_week_smoke import (
    DEFAULT_ARTIFACT_IDS,
    DEFAULT_SELECTED_WEEKS_YAML,
    DEFAULT_SUPPORT_CSV,
    DEFAULT_WEEK_REGISTRY,
    run_selected_week_risk_neutral_smoke,
)


def _bool_arg(value: str) -> bool:
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Unable to parse boolean argument from {value!r}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Phase C one-week risk-neutral selected-week smoke run.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the hydrogen config YAML.",
    )
    parser.add_argument(
        "--week-id",
        required=True,
        help="Selected week label or canonical week_id from the common-support registry.",
    )
    parser.add_argument(
        "--artifacts",
        nargs="+",
        default=list(DEFAULT_ARTIFACT_IDS),
        help="Scenario artifact IDs to run on the selected week.",
    )
    parser.add_argument(
        "--risk-mode",
        default="risk_neutral",
        help="Risk mode label. Phase C supports risk_neutral only.",
    )
    parser.add_argument(
        "--include-price-insensitive-benchmark",
        type=_bool_arg,
        default=True,
        help="Whether to run the price-insensitive benchmark. Phase C requires true.",
    )
    parser.add_argument(
        "--run-slug",
        required=True,
        help="Run slug to embed in the suite run folder name.",
    )
    parser.add_argument(
        "--week-registry",
        default=str(DEFAULT_WEEK_REGISTRY),
        help="Path to selected_week_registry_common_support.csv.",
    )
    parser.add_argument(
        "--support-csv",
        default=str(DEFAULT_SUPPORT_CSV),
        help="Path to common_support_three_model_hourly.csv.",
    )
    parser.add_argument(
        "--selected-weeks-yaml",
        default=str(DEFAULT_SELECTED_WEEKS_YAML),
        help="Path to the official split selected-weeks YAML.",
    )
    parser.add_argument(
        "--selected-week-split",
        choices=["validation", "test"],
        default="validation",
        help="Selected-week split for the generic smoke runner. Defaults to validation.",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Optional output root override.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_hydrogen_config(args.config)
    result = run_selected_week_risk_neutral_smoke(
        config=config,
        week_id=str(args.week_id),
        artifact_ids=[str(value) for value in args.artifacts],
        run_slug=str(args.run_slug),
        risk_mode=str(args.risk_mode),
        include_price_insensitive_benchmark=bool(args.include_price_insensitive_benchmark),
        output_root=Path(args.output_root) if args.output_root else None,
        week_registry_path=Path(args.week_registry),
        support_csv_path=Path(args.support_csv),
        selected_weeks_yaml_path=Path(args.selected_weeks_yaml),
        selected_week_split=str(args.selected_week_split),
    )
    print("run_dir=", result.run_dir)
    print("week_id=", result.selected_week["week_id"])
    print("week_label=", result.selected_week["week_label"])
    print("weekly_models=", int(result.weekly_metrics.shape[0]))
    print("validation_rows=", int(result.validation_checks.shape[0]))


if __name__ == "__main__":
    main()
