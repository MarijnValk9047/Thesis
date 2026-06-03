from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from .config import QuarterHourDAExtensionConfig


PHASE07_REQUIRED_DATASETS: tuple[str, ...] = (
    "6_1_a_actual_total_load_be",
    "6_1_a_actual_total_load_de",
    "6_1_a_actual_total_load_nl",
    "6_1_b_da_total_load_forecast_be",
    "6_1_b_da_total_load_forecast_de",
    "6_1_b_da_total_load_forecast_nl",
    "6_1_c_week_ahead_load_forecast_be",
    "6_1_c_week_ahead_load_forecast_de",
    "6_1_c_week_ahead_load_forecast_nl",
    "14_1_a_installed_capacity_by_psr_be",
    "14_1_a_installed_capacity_by_psr_de",
    "14_1_a_installed_capacity_by_psr_nl",
    "16_1_bc_actual_generation_all_types_a75_be",
    "16_1_bc_actual_generation_all_types_a75_de",
    "16_1_bc_actual_generation_all_types_a75_nl",
    "14_1_c_da_generation_forecast_be",
    "14_1_c_da_generation_forecast_de",
    "14_1_c_da_generation_forecast_nl",
    "12_1_d_energy_prices_a01_day_ahead_be",
    "12_1_d_energy_prices_a01_day_ahead_de",
    "12_1_d_energy_prices_a01_day_ahead_nl",
)

PHASE07_REQUIRED_FAMILIES: tuple[str, ...] = (
    "actual_total_load",
    "da_total_load_forecast",
    "week_ahead_total_load_forecast",
    "da_generation_forecast",
    "actual_generation_by_psr",
    "installed_capacity_by_psr",
)


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_phase07_upstream_refresh")


def find_latest_phase07_upstream_refresh_run(config: QuarterHourDAExtensionConfig) -> Path | None:
    run_root = config.phase07_upstream_refresh_runs_root
    if not run_root.exists():
        return None
    candidates = sorted(path for path in run_root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    return candidates[-1] if candidates else None


def _coverage_targets(config: QuarterHourDAExtensionConfig) -> dict[str, Path]:
    return {
        "actual_generation_by_psr_hourly_long": config.repo_root
        / "data"
        / "01_cleaned"
        / "Generation"
        / "actual_generation_by_psr"
        / "hourly"
        / "actual_generation_by_psr_hourly_long.csv",
        "actual_total_load_hourly_long": config.repo_root
        / "data"
        / "01_cleaned"
        / "Load"
        / "actual_total_load"
        / "hourly"
        / "actual_total_load_hourly_long.csv",
        "da_generation_forecast_hourly_long": config.repo_root
        / "data"
        / "01_cleaned"
        / "Generation"
        / "da_generation_forecast"
        / "hourly"
        / "da_generation_forecast_hourly_long.csv",
        "da_prices_BE_hourly": config.shared_clean_root / "DA_prices" / "hourly" / "da_prices_BE_hourly.csv",
        "da_prices_DE_hourly": config.shared_clean_root / "DA_prices" / "hourly" / "da_prices_DE_hourly.csv",
        "da_prices_NL_hourly": config.shared_clean_root / "DA_prices" / "hourly" / "da_prices_NL_hourly.csv",
        "da_prices_all_regions_hourly": config.shared_all_regions_hourly_csv,
        "da_total_load_forecast_hourly_long": config.repo_root
        / "data"
        / "01_cleaned"
        / "Load"
        / "da_total_load_forecast"
        / "hourly"
        / "da_total_load_forecast_hourly_long.csv",
        "installed_capacity_by_psr_hourly_long": config.repo_root
        / "data"
        / "01_cleaned"
        / "Generation"
        / "installed_capacity_by_psr"
        / "hourly"
        / "installed_capacity_by_psr_hourly_long.csv",
        "week_ahead_total_load_forecast_hourly_long": config.repo_root
        / "data"
        / "01_cleaned"
        / "Load"
        / "week_ahead_total_load_forecast"
        / "hourly"
        / "week_ahead_total_load_forecast_hourly_long.csv",
    }


def _file_coverage_row(name: str, path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "dataset": name,
            "path": str(path),
            "exists": False,
            "rows": 0,
            "min_timestamp_utc": None,
            "max_timestamp_utc": None,
        }
    frame = pd.read_csv(path, usecols=["timestamp_utc"])
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce").dropna()
    return {
        "dataset": name,
        "path": str(path),
        "exists": True,
        "rows": int(frame.shape[0]),
        "min_timestamp_utc": timestamps.min().isoformat() if not timestamps.empty else None,
        "max_timestamp_utc": timestamps.max().isoformat() if not timestamps.empty else None,
    }


def _collect_cleaned_coverage(config: QuarterHourDAExtensionConfig) -> pd.DataFrame:
    rows = [_file_coverage_row(name, path) for name, path in _coverage_targets(config).items()]
    return pd.DataFrame(rows).sort_values("dataset").reset_index(drop=True)


def _run_command(command: list[str], *, cwd: Path, log_path: Path) -> None:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    log_path.write_text(
        "\n".join(
            [
                f"COMMAND: {' '.join(command)}",
                "",
                "STDOUT:",
                result.stdout or "",
                "",
                "STDERR:",
                result.stderr or "",
                "",
                f"RETURN_CODE: {result.returncode}",
            ]
        ),
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {' '.join(command)}")


def run_phase07_upstream_refresh(config: QuarterHourDAExtensionConfig) -> Path:
    run_dir = config.phase07_upstream_refresh_runs_root / _timestamped_run_id()
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    before_coverage = _collect_cleaned_coverage(config)
    before_coverage.to_csv(run_dir / "coverage_before.csv", index=False)

    latest_full_day = config.latest_full_local_day()
    max_hourly_timestamp_utc = config.end_timestamp_inclusive_for_local_day(latest_full_day, step_minutes=60)
    python_executable = Path(sys.executable)

    for dataset_key in PHASE07_REQUIRED_DATASETS:
        _run_command(
            [
                str(python_executable),
                "scripts/Data/00_data_imports/API_GETS.py",
                "--dataset",
                dataset_key,
                "--start-year",
                "2026",
                "--end-year",
                "2026",
            ],
            cwd=config.repo_root,
            log_path=logs_dir / f"download_{dataset_key}.log",
        )

    _run_command(
        [
            str(python_executable),
            "scripts/Data/01_cleaning/entsoe_system_features_pipeline.py",
            "--markets",
            "BE",
            "DE",
            "NL",
            "--families",
            *PHASE07_REQUIRED_FAMILIES,
        ],
        cwd=config.repo_root,
        log_path=logs_dir / "clean_entsoe_system_features.log",
    )

    _run_command(
        [
            str(python_executable),
            "scripts/Data/01_cleaning/day_ahead_prices_pipeline.py",
            "--regions",
            "BE",
            "DE",
            "NL",
            "--quarterly-regions",
            "NL",
            "--max-timestamp-utc",
            max_hourly_timestamp_utc.isoformat(),
        ],
        cwd=config.repo_root,
        log_path=logs_dir / "clean_day_ahead_prices.log",
    )

    after_coverage = _collect_cleaned_coverage(config)
    after_coverage.to_csv(run_dir / "coverage_after.csv", index=False)

    freshness = before_coverage.merge(
        after_coverage,
        on="dataset",
        how="outer",
        suffixes=("_before", "_after"),
    )
    freshness["rows_added"] = freshness["rows_after"].fillna(0) - freshness["rows_before"].fillna(0)
    freshness["path"] = freshness["path_after"].fillna(freshness["path_before"])
    freshness["latest_timestamp_before"] = freshness["max_timestamp_utc_before"]
    freshness["latest_timestamp_after"] = freshness["max_timestamp_utc_after"]
    freshness = freshness[
        [
            "dataset",
            "path",
            "rows_before",
            "rows_after",
            "rows_added",
            "latest_timestamp_before",
            "latest_timestamp_after",
        ]
    ].sort_values("dataset").reset_index(drop=True)
    freshness.to_csv(run_dir / "freshness_summary.csv", index=False)

    run_summary = {
        "run_dir": str(run_dir),
        "python_executable": str(python_executable),
        "latest_full_local_day": str(latest_full_day),
        "max_hourly_timestamp_utc": max_hourly_timestamp_utc.isoformat(),
        "dataset_count": len(PHASE07_REQUIRED_DATASETS),
        "families_recleaned": list(PHASE07_REQUIRED_FAMILIES),
        "freshness_summary_csv": str(run_dir / "freshness_summary.csv"),
    }
    (run_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2), encoding="utf-8")
    return run_dir
