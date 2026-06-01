from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .plant_parameters import HydrogenConfig


def _to_serializable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_serializable(sub_value) for key, sub_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_serializable(item) for item in value]
    return value


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_hash(config: HydrogenConfig) -> str:
    payload = json.dumps(asdict(config), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _git_commit(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return completed.stdout.strip() or None


def make_run_id(run_label: str) -> str:
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run_label}"


def create_run_folder(config: HydrogenConfig) -> tuple[str, Path]:
    run_id = make_run_id(config.experiment.name)
    run_dir = config.run_output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "figures").mkdir(parents=True, exist_ok=True)
    return run_id, run_dir


def save_config_resolved(run_dir: Path, config: HydrogenConfig) -> Path:
    target = run_dir / "config_resolved.yaml"
    payload = _to_serializable(asdict(config))
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return target


def build_inputs_manifest(paths: list[Path]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            records.append(
                {
                    "path": str(path),
                    "exists": False,
                    "size_bytes": None,
                    "modified_utc": None,
                    "sha256": None,
                }
            )
            continue
        stat = path.stat()
        records.append(
            {
                "path": str(path),
                "exists": True,
                "size_bytes": int(stat.st_size),
                "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "sha256": _file_hash(path),
            }
        )
    return {"files": records}


def save_inputs_manifest(run_dir: Path, paths: list[Path]) -> Path:
    payload = build_inputs_manifest(paths)
    target = run_dir / "inputs_manifest.json"
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def write_manifest(
    *,
    run_dir: Path,
    run_id: str,
    config: HydrogenConfig,
    scenario_paths: list[Path],
    selected_period: dict[str, Any],
    model_ids: list[str],
    solver_package: str,
    solver_name: str,
    solver_statuses: list[dict[str, Any]],
    runtime_seconds: float,
    warnings: list[str],
) -> Path:
    payload = {
        "run_id": run_id,
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
        "git_commit": _git_commit(config.repo_root),
        "config_hash": _config_hash(config),
        "config_path": str(config.config_path),
        "scenario_artifact_paths": [str(path) for path in scenario_paths],
        "actual_price_source": "scenario_input.actual_price_eur_per_mwh",
        "selected_period": selected_period,
        "model_ids": model_ids,
        "strategies": list(config.strategies),
        "granularity": config.experiment.granularity,
        "horizon_mode": config.experiment.horizon_mode,
        "solver_package": solver_package,
        "solver_name": solver_name,
        "solver_statuses": solver_statuses,
        "runtime_seconds": float(runtime_seconds),
        "random_seed": int(config.experiment.random_seed),
        "notes_warnings": warnings,
    }
    target = run_dir / "manifest.json"
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def save_frame_csv(run_dir: Path, name: str, frame: pd.DataFrame) -> Path:
    target = run_dir / name
    frame.to_csv(target, index=False)
    return target


def save_frame_parquet(run_dir: Path, name: str, frame: pd.DataFrame) -> Path:
    target = run_dir / name
    frame.to_parquet(target, index=False)
    return target


def save_json(run_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    target = run_dir / name
    target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return target


def save_text(run_dir: Path, name: str, content: str) -> Path:
    target = run_dir / name
    target.write_text(content, encoding="utf-8")
    return target
