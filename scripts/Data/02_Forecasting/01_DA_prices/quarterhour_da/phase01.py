from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .anchor_selection import selection_contract_frame
from .config import QuarterHourDAExtensionConfig


@dataclass(frozen=True)
class DatasetSnapshot:
    dataset: str
    path: str
    rows: int
    latest_timestamp_utc: str | None


def _timestamped_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S_phase01_refresh")


def find_latest_phase01_run(config: QuarterHourDAExtensionConfig) -> Path | None:
    run_root = config.phase01_runs_root
    if not run_root.exists():
        return None
    candidates = sorted(path for path in run_root.iterdir() if path.is_dir() and (path / "run_summary.json").exists())
    return candidates[-1] if candidates else None


def _snapshot_csv(path: Path, *, timestamp_col: str = "timestamp_utc") -> DatasetSnapshot:
    if not path.exists():
        return DatasetSnapshot(dataset=path.stem, path=str(path), rows=0, latest_timestamp_utc=None)
    frame = pd.read_csv(path, usecols=[timestamp_col])
    if frame.empty:
        return DatasetSnapshot(dataset=path.stem, path=str(path), rows=0, latest_timestamp_utc=None)
    timestamps = pd.to_datetime(frame[timestamp_col], utc=True, errors="coerce").dropna()
    latest_timestamp = timestamps.max().isoformat() if not timestamps.empty else None
    return DatasetSnapshot(dataset=path.stem, path=str(path), rows=int(frame.shape[0]), latest_timestamp_utc=latest_timestamp)


def _run_command(
    *,
    command_name: str,
    command: list[str],
    workdir: Path,
    log_dir: Path,
) -> dict[str, Any]:
    started_at = pd.Timestamp.now(tz="UTC")
    completed = subprocess.run(
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    finished_at = pd.Timestamp.now(tz="UTC")
    log_path = log_dir / f"{command_name}.log"
    log_text = (
        f"COMMAND: {' '.join(str(part) for part in command)}\n"
        f"STARTED_AT_UTC: {started_at.isoformat()}\n"
        f"FINISHED_AT_UTC: {finished_at.isoformat()}\n"
        f"RETURN_CODE: {completed.returncode}\n\n"
        f"STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}"
    )
    log_path.write_text(log_text, encoding="utf-8")
    return {
        "command_name": command_name,
        "command": [str(part) for part in command],
        "return_code": int(completed.returncode),
        "status": "success" if completed.returncode == 0 else "failed",
        "log_path": str(log_path),
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def _interpreter_supports_required_modules(interpreter: Path) -> bool:
    if not interpreter.exists():
        return False
    probe = subprocess.run(
        [
            str(interpreter),
            "-c",
            "import importlib.util; import sys; "
            "mods=['pandas','dotenv']; "
            "missing=[m for m in mods if importlib.util.find_spec(m) is None]; "
            "sys.exit(0 if not missing else 1)",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return probe.returncode == 0


def _select_refresh_interpreter(config: QuarterHourDAExtensionConfig) -> Path:
    current = Path(sys.executable)
    candidates = [
        current,
        config.repo_root / ".venv" / "Scripts" / "python.exe",
        config.repo_root / ".venv312" / "Scripts" / "python.exe",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        if _interpreter_supports_required_modules(candidate):
            return candidate
    raise RuntimeError(
        "No suitable Python interpreter was found for the Phase 0/1 refresh. A working interpreter must provide "
        "both pandas and python-dotenv."
    )


def _build_foundation_contracts(config: QuarterHourDAExtensionConfig) -> pd.DataFrame:
    rows = [
        {
            "contract_group": "dataset",
            "contract_name": "hourly_actual_authoritative",
            "authority_level": "authoritative",
            "path_or_target": str(config.shared_hourly_csv),
            "implementation_choice": "Keep the existing shared cleaned hourly NL DAM output as the canonical observed hourly source.",
            "notes": "No synthetic hourly extension is written into this dataset after the 2025-10-01 quarter-hour market change.",
        },
        {
            "contract_group": "dataset",
            "contract_name": "quarterhour_actual_authoritative",
            "authority_level": "authoritative",
            "path_or_target": str(config.shared_quarterly_csv),
            "implementation_choice": "Keep the existing shared cleaned quarterly NL DAM output as the downstream quarter-hour source for compatibility.",
            "notes": "This preserves the established Day_ahead_prices cleaned layout used elsewhere in the repo.",
        },
        {
            "contract_group": "dataset",
            "contract_name": "quarterhour_continuation_companion",
            "authority_level": "companion",
            "path_or_target": str(config.dedicated_quarterly_csv),
            "implementation_choice": "Use the dedicated NL quarterly pipeline as the continuation updater and audit companion.",
            "notes": "This path is not treated as the sole authoritative downstream input yet; it complements the shared cleaned quarterly output.",
        },
        {
            "contract_group": "updater",
            "contract_name": "hourly_raw_import",
            "authority_level": "repo_native",
            "path_or_target": str(config.repo_root / "scripts" / "Data" / "00_data_imports" / "API_GETS.py"),
            "implementation_choice": "Refresh the shared NL A01 day-ahead raw XML via the existing ENTSO-E importer.",
            "notes": "The current-year NL A01 pull is rerun to extend the partial-year raw history without inventing a parallel downloader.",
        },
        {
            "contract_group": "updater",
            "contract_name": "shared_da_cleaner",
            "authority_level": "repo_native",
            "path_or_target": str(config.repo_root / "scripts" / "Data" / "01_cleaning" / "day_ahead_prices_pipeline.py"),
            "implementation_choice": "Rebuild the shared hourly and quarterly cleaned outputs with the existing unified cleaner.",
            "notes": "The cleaner remains responsible for the shared cleaned Day_ahead_prices outputs and their diagnostics.",
        },
        {
            "contract_group": "updater",
            "contract_name": "dedicated_quarterly_cleaner",
            "authority_level": "repo_native",
            "path_or_target": str(config.repo_root / "scripts" / "Data" / "01_cleaning" / "nl_quarterly_da_prices_pipeline.py"),
            "implementation_choice": "Maintain the dedicated NL quarterly continuation path with the specialized updater.",
            "notes": "This companion path gives a quarter-hour-specific audit trail and incremental state for later phases.",
        },
        {
            "contract_group": "notebook",
            "contract_name": "notebook_generation_pattern",
            "authority_level": "repo_native",
            "path_or_target": str(config.repo_root / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "create_da_15min_extension_notebooks.py"),
            "implementation_choice": "Use a dedicated notebook-creation script instead of hand-maintaining the downstream 15-minute notebooks.",
            "notes": "This matches the existing repo pattern used for the DA cleaning and scenario notebooks.",
        },
        {
            "contract_group": "output",
            "contract_name": "quarterhour_extension_output_root",
            "authority_level": "repo_native",
            "path_or_target": str(config.output_root),
            "implementation_choice": "Store downstream 15-minute artifacts under a separate quarterhour_da output root.",
            "notes": "This avoids mixing the new downstream artifacts with the established hourly benchmark run folders.",
        },
    ]
    contract_frame = pd.DataFrame(rows)
    selection_source = selection_contract_frame().iloc[0].to_dict()
    selection_frame = pd.DataFrame(
        [
            {
                "contract_group": "selection",
                "contract_name": str(selection_source["contract_name"]),
                "authority_level": "repo_native",
                "path_or_target": str(selection_source["authority_module"]),
                "implementation_choice": (
                    f"Selection roles: {selection_source['selection_roles']}; "
                    f"hardcoded names allowed: {selection_source['hardcoded_model_names_allowed']}"
                ),
                "notes": (
                    f"{selection_source['selection_slice_rule']}. "
                    f"{selection_source['notes']}"
                ),
            }
        ]
    )
    return pd.concat([contract_frame, selection_frame], ignore_index=True)


def _current_year_refresh_command(config: QuarterHourDAExtensionConfig, *, interpreter: Path) -> list[str]:
    current_year = config.latest_full_local_day().year
    return [
        str(interpreter),
        str(config.repo_root / "scripts" / "Data" / "00_data_imports" / "API_GETS.py"),
        "--dataset",
        "12_1_d_energy_prices_a01_day_ahead_nl",
        "--start-year",
        str(current_year),
        "--end-year",
        str(current_year),
        "--output-root",
        str(config.repo_root / "data" / "00_Raw"),
    ]


def _shared_cleaner_command(config: QuarterHourDAExtensionConfig, *, interpreter: Path) -> list[str]:
    max_timestamp = config.end_timestamp_inclusive_for_local_day(
        config.latest_full_local_day(),
        step_minutes=15,
    )
    return [
        str(interpreter),
        str(config.repo_root / "scripts" / "Data" / "01_cleaning" / "day_ahead_prices_pipeline.py"),
        "--raw-root",
        str(config.shared_raw_root),
        "--output-root",
        str(config.shared_clean_root),
        "--cutoff-local-date",
        config.cleaning_cutoff_local_date.isoformat(),
        "--local-timezone",
        "Europe/Brussels",
        "--max-timestamp-utc",
        max_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
    ]


def _dedicated_quarterly_command(config: QuarterHourDAExtensionConfig, *, interpreter: Path) -> list[str]:
    return [
        str(interpreter),
        str(config.repo_root / "scripts" / "Data" / "01_cleaning" / "nl_quarterly_da_prices_pipeline.py"),
        "--mode",
        "incremental",
        "--raw-root",
        str(config.dedicated_quarterly_raw_root),
        "--output-root",
        str(config.dedicated_quarterly_output_root),
        "--cutoff-local-date",
        config.cleaning_cutoff_local_date.isoformat(),
    ]


def _collect_primary_snapshots(config: QuarterHourDAExtensionConfig) -> dict[str, DatasetSnapshot]:
    return {
        "hourly_shared_cleaned": _snapshot_csv(config.shared_hourly_csv),
        "quarterhour_shared_cleaned": _snapshot_csv(config.shared_quarterly_csv),
        "quarterhour_dedicated_cleaned": _snapshot_csv(config.dedicated_quarterly_csv),
    }


def _build_refresh_summary(
    *,
    config: QuarterHourDAExtensionConfig,
    before: dict[str, DatasetSnapshot],
    after: dict[str, DatasetSnapshot],
    command_results: list[dict[str, Any]],
) -> pd.DataFrame:
    result_by_name = {row["command_name"]: row for row in command_results}
    rows: list[dict[str, Any]] = []
    specs = [
        (
            "hourly_shared_cleaned",
            "Hourly NL DAM cleaned output",
            str(config.shared_hourly_csv),
            "Shared cleaned output remains authoritative.",
            "api_gets_nl_a01_current_year + day_ahead_prices_pipeline",
        ),
        (
            "quarterhour_shared_cleaned",
            "Quarter-hour NL DAM cleaned output",
            str(config.shared_quarterly_csv),
            "Shared cleaned output remains authoritative for the downstream extension.",
            "api_gets_nl_a01_current_year + day_ahead_prices_pipeline",
        ),
        (
            "quarterhour_dedicated_cleaned",
            "Quarter-hour NL dedicated continuation output",
            str(config.dedicated_quarterly_csv),
            "Companion continuation/audit path built by the dedicated quarterly updater.",
            "nl_quarterly_da_prices_pipeline",
        ),
    ]
    for key, label, path, note, source_used in specs:
        before_snapshot = before[key]
        after_snapshot = after[key]
        if key == "quarterhour_dedicated_cleaned":
            primary_command = result_by_name.get("dedicated_quarterly_refresh")
        else:
            primary_command = result_by_name.get("shared_da_cleaner")
        status = primary_command["status"] if primary_command is not None else "unknown"
        warning = ""
        if primary_command is not None and primary_command["status"] != "success":
            warning = f"Primary refresh command failed; inspect {primary_command['log_path']}."
        rows.append(
            {
                "dataset": label,
                "cleaned_path": path,
                "latest_timestamp_before_update_utc": before_snapshot.latest_timestamp_utc,
                "latest_timestamp_after_update_utc": after_snapshot.latest_timestamp_utc,
                "rows_before": int(before_snapshot.rows),
                "rows_after": int(after_snapshot.rows),
                "new_rows_added": int(after_snapshot.rows - before_snapshot.rows),
                "source_used": source_used,
                "update_status": status,
                "notes": note,
                "warnings": warning,
            }
        )
    return pd.DataFrame(rows)


def run_phase01_refresh(config: QuarterHourDAExtensionConfig | None = None) -> Path:
    config = config or QuarterHourDAExtensionConfig()
    run_id = _timestamped_run_id()
    run_dir = config.phase01_runs_root / run_id
    log_dir = run_dir / "logs"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    foundation_contracts = _build_foundation_contracts(config)
    foundation_contracts.to_csv(run_dir / "foundation_contracts.csv", index=False)

    before = _collect_primary_snapshots(config)
    refresh_interpreter = _select_refresh_interpreter(config)
    command_results = [
        _run_command(
            command_name="api_gets_nl_a01_current_year",
            command=_current_year_refresh_command(config, interpreter=refresh_interpreter),
            workdir=config.repo_root,
            log_dir=log_dir,
        ),
        _run_command(
            command_name="shared_da_cleaner",
            command=_shared_cleaner_command(config, interpreter=refresh_interpreter),
            workdir=config.repo_root,
            log_dir=log_dir,
        ),
        _run_command(
            command_name="dedicated_quarterly_refresh",
            command=_dedicated_quarterly_command(config, interpreter=refresh_interpreter),
            workdir=config.repo_root,
            log_dir=log_dir,
        ),
    ]
    command_frame = pd.DataFrame(command_results)
    command_frame.to_csv(run_dir / "command_status_summary.csv", index=False)

    after = _collect_primary_snapshots(config)
    refresh_summary = _build_refresh_summary(
        config=config,
        before=before,
        after=after,
        command_results=command_results,
    )
    refresh_summary.to_csv(run_dir / "data_refresh_summary.csv", index=False)

    run_summary = {
        "run_id": run_id,
        "phase": "phase01_foundation_refresh",
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()},
        "refresh_interpreter": str(refresh_interpreter),
        "latest_full_local_day": config.latest_full_local_day().isoformat(),
        "before_snapshots": {key: asdict(value) for key, value in before.items()},
        "after_snapshots": {key: asdict(value) for key, value in after.items()},
        "command_results": command_results,
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    (run_dir / "run_summary.json").write_text(json.dumps(run_summary, indent=2, default=str), encoding="utf-8")
    return run_dir
