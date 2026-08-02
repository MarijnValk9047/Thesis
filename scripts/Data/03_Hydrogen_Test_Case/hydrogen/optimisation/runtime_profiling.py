from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator

import pandas as pd

from scripts.optimisation_performance import (
    PERFORMANCE_SCHEMA_VERSION,
    peak_working_set_mb,
)


@dataclass(frozen=True)
class RuntimeRecord:
    stage: str
    started_utc: str
    finished_utc: str
    wall_time_seconds: float
    peak_working_set_mb: float | None
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
                    peak_working_set_mb=peak_working_set_mb(),
                    details={str(key): value for key, value in details.items()},
                )
            )

    def to_frame(self) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for record in self._records:
            rows.append(
                {
                    "schema_version": PERFORMANCE_SCHEMA_VERSION,
                    "stage": record.stage,
                    "solve_stage": record.stage,
                    "started_utc": record.started_utc,
                    "finished_utc": record.finished_utc,
                    "wall_time_seconds": record.wall_time_seconds,
                    "peak_working_set_mb": record.peak_working_set_mb,
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
