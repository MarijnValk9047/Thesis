from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator

import pandas as pd


@dataclass(frozen=True)
class RuntimeRecord:
    stage: str
    started_utc: str
    finished_utc: str
    wall_time_seconds: float
    details: dict[str, Any]


class RuntimeProfiler:
    def __init__(self) -> None:
        self._records: list[RuntimeRecord] = []

    @contextmanager
    def track(self, stage: str, **details: Any) -> Iterator[None]:
        started_at = datetime.now(tz=timezone.utc)
        started = perf_counter()
        try:
            yield
        finally:
            finished_at = datetime.now(tz=timezone.utc)
            elapsed = perf_counter() - started
            self._records.append(
                RuntimeRecord(
                    stage=str(stage),
                    started_utc=started_at.isoformat(),
                    finished_utc=finished_at.isoformat(),
                    wall_time_seconds=float(elapsed),
                    details={str(key): value for key, value in details.items()},
                )
            )

    def to_frame(self) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for record in self._records:
            rows.append(
                {
                    "stage": record.stage,
                    "started_utc": record.started_utc,
                    "finished_utc": record.finished_utc,
                    "wall_time_seconds": record.wall_time_seconds,
                    **record.details,
                }
            )
        return pd.DataFrame(rows)

    def save_csv(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.to_frame().to_csv(path, index=False)
        return path

    def save_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.to_frame().to_json(path, orient="records", indent=2)
        return path
