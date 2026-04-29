from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

PREDICTION_PARQUET_COMPRESSION = "zstd"


def create_run_directory(output_root: Path, run_label: str) -> tuple[str, Path]:
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run_label}"
    run_dir = output_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def write_parquet(path: Path, frame: pd.DataFrame, compression: str = PREDICTION_PARQUET_COMPRESSION) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, compression=compression)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
