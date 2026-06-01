from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class DatasetSpec:
    slug: str
    key: str
    description: str


DATASET_SPECS = {
    "da_price": DatasetSpec("da_price", "12_1_d_energy_prices_a01_day_ahead_nl", "NL day-ahead A01 price"),
    "load_da": DatasetSpec("load_da", "6_1_b_da_total_load_forecast_nl", "NL DA total load forecast"),
    "load_week_ahead": DatasetSpec(
        "load_week_ahead",
        "6_1_c_week_ahead_load_forecast_nl",
        "NL week-ahead total load forecast",
    ),
    "generation_da": DatasetSpec("generation_da", "14_1_c_da_generation_forecast_nl", "NL DA aggregate generation forecast"),
    "generation_actual_by_psr": DatasetSpec(
        "generation_actual_by_psr",
        "16_1_bc_actual_generation_by_psr_a74_nl",
        "NL actual generation by PSR",
    ),
    "capacity_by_psr": DatasetSpec(
        "capacity_by_psr",
        "14_1_a_installed_capacity_by_psr_nl",
        "NL installed capacity by PSR",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Staged Lago LEAR import orchestration for ENTSO-E datasets.")
    parser.add_argument("--run-import", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--start-year", type=int, default=2019)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--output-root", type=Path, default=Path("data/00_raw_lago_lear_six_year"))
    parser.add_argument("--max-pages-per-year", type=int, default=250)
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["all"],
        help="Subset: all|da_price|load_da|load_week_ahead|generation_da|generation_actual_by_psr|capacity_by_psr",
    )
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args()


def configure_logging(log_file: Path, log_level: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, str(log_level).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _load_api_gets_module() -> Any:
    module_path = Path("scripts/Data/00_data_imports/API_GETS.py")
    if not module_path.exists():
        raise FileNotFoundError(f"Missing importer module: {module_path}")
    spec = importlib.util.spec_from_file_location("api_gets_module", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_dataset_specs(dataset_args: list[str]) -> list[DatasetSpec]:
    values = [str(value).strip() for value in dataset_args if str(value).strip()]
    if not values or "all" in values:
        return list(DATASET_SPECS.values())
    resolved: list[DatasetSpec] = []
    for value in values:
        if value not in DATASET_SPECS:
            raise ValueError(f"Unknown dataset slug: {value}")
        resolved.append(DATASET_SPECS[value])
    return resolved


def _overwrite_risk_for_year(target_dir: Path, year: int) -> dict[str, Any]:
    matches = sorted(target_dir.glob(f"*_{year}_offset_*.*"))
    return {
        "existing_file_count": int(len(matches)),
        "existing_example": str(matches[0]) if matches else None,
    }


def _dataset_target_dir(output_root: Path, dataset_config: Any) -> Path:
    return Path(output_root) / str(dataset_config.output_subdir)


def main() -> None:
    args = parse_args()
    import_root = args.output_root / "lago_import_audit"
    plan_path = import_root / "import_plan.json"
    status_path = import_root / "import_status.csv"
    log_path = import_root / "import_log.txt"
    configure_logging(log_path, args.log_level)

    if int(args.start_year) > int(args.end_year):
        raise ValueError("start-year cannot be greater than end-year")

    api_gets = _load_api_gets_module()
    selected_specs = _resolve_dataset_specs(args.datasets)
    token_missing = False
    try:
        token = api_gets.get_token()
    except Exception as exc:  # noqa: BLE001
        token = None
        token_missing = True
        logging.warning("Could not read ENTSOE key at preflight: %s", exc)

    plan_rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    for spec in selected_specs:
        dataset_cfg = api_gets.DATASETS.get(spec.key)
        if dataset_cfg is None:
            plan_rows.append(
                {
                    "dataset_slug": spec.slug,
                    "dataset_key": spec.key,
                    "description": spec.description,
                    "status": "missing_dataset_key",
                    "target_dir": None,
                    "year": None,
                    "overwrite_risk_existing_file_count": None,
                }
            )
            status_rows.append(
                {
                    "dataset_slug": spec.slug,
                    "dataset_key": spec.key,
                    "year": None,
                    "status": "missing_dataset_key",
                    "note": "Dataset key not found in API_GETS.py",
                }
            )
            continue

        target_dir = _dataset_target_dir(args.output_root, dataset_cfg)
        for year in range(int(args.start_year), int(args.end_year) + 1):
            risk = _overwrite_risk_for_year(target_dir, year)
            plan_rows.append(
                {
                    "dataset_slug": spec.slug,
                    "dataset_key": spec.key,
                    "description": spec.description,
                    "status": "planned",
                    "target_dir": str(target_dir),
                    "year": int(year),
                    "overwrite_risk_existing_file_count": int(risk["existing_file_count"]),
                    "overwrite_risk_example": risk["existing_example"],
                }
            )

            if args.dry_run and not args.run_import:
                status_rows.append(
                    {
                        "dataset_slug": spec.slug,
                        "dataset_key": spec.key,
                        "year": int(year),
                        "status": "dry_run_only",
                        "note": f"Would import into {target_dir}",
                    }
                )
                continue

            if not args.run_import:
                status_rows.append(
                    {
                        "dataset_slug": spec.slug,
                        "dataset_key": spec.key,
                        "year": int(year),
                        "status": "no_op",
                        "note": "No --run-import flag set.",
                    }
                )
                continue

            if token_missing or token is None:
                status_rows.append(
                    {
                        "dataset_slug": spec.slug,
                        "dataset_key": spec.key,
                        "year": int(year),
                        "status": "token_missing",
                        "note": "ENTSOE_KEY missing.",
                    }
                )
                continue

            if args.skip_existing and not args.force and int(risk["existing_file_count"]) > 0:
                status_rows.append(
                    {
                        "dataset_slug": spec.slug,
                        "dataset_key": spec.key,
                        "year": int(year),
                        "status": "skipped_existing",
                        "note": f"Found {risk['existing_file_count']} staged files for this year.",
                    }
                )
                continue

            logging.info("Importing %s year %s to %s", spec.key, year, target_dir)
            try:
                api_gets.download_dataset(
                    config=dataset_cfg,
                    token=token,
                    start_year=int(year),
                    end_year=int(year),
                    output_root=args.output_root,
                    max_pages_per_year=int(args.max_pages_per_year),
                )
                status_rows.append(
                    {
                        "dataset_slug": spec.slug,
                        "dataset_key": spec.key,
                        "year": int(year),
                        "status": "imported",
                        "note": "",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                status_rows.append(
                    {
                        "dataset_slug": spec.slug,
                        "dataset_key": spec.key,
                        "year": int(year),
                        "status": "import_error",
                        "note": str(exc),
                    }
                )

    import_root.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan_rows, indent=2), encoding="utf-8")
    pd.DataFrame(status_rows).to_csv(status_path, index=False)
    logging.info("Wrote import plan: %s", plan_path)
    logging.info("Wrote import status: %s", status_path)


if __name__ == "__main__":
    main()
