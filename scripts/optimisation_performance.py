"""Shared, semantics-preserving optimisation performance contract.

The module is deliberately model-agnostic. Hydrogen and steel keep their own
builders; they share signatures, cache accounting, timing fields and parity
rules through this small contract.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator, Mapping, Sequence


PERFORMANCE_MODES = ("optimized_equivalent", "legacy_rebuild")
PERFORMANCE_SCHEMA_VERSION = "optimisation_performance_v1"
RUNTIME_COLUMNS = (
    "schema_version", "system", "model_type", "configuration", "policy",
    "episode_id", "origin", "solve_stage", "performance_mode",
    "input_resolution_seconds", "array_preparation_seconds",
    "model_build_seconds", "presolve_solver_seconds", "postprocessing_seconds",
    "dataframe_construction_seconds", "output_io_seconds", "wall_time_seconds",
    "peak_working_set_mb", "variables", "binaries", "constraints", "scenarios",
    "timesteps", "bid_ladder_steps", "solver_status", "termination_condition",
    "mip_gap", "structural_signature", "model_reuse_status", "cache_status",
    "warm_start_status", "warm_start_values_applied", "pyomo_model_rebuilt",
)


def validate_performance_mode(mode: str) -> str:
    value = str(mode).strip().lower()
    if value not in PERFORMANCE_MODES:
        raise ValueError(f"Unsupported performance_mode={mode!r}; expected one of {PERFORMANCE_MODES}.")
    return value


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fingerprint_paths(paths: Sequence[Path]) -> str:
    records: list[dict[str, Any]] = []
    for raw_path in sorted((Path(path).resolve() for path in paths), key=str):
        stat = raw_path.stat()
        records.append(
            {
                "path": str(raw_path),
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
                "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            }
        )
    return stable_hash(records)


@dataclass(frozen=True)
class StructuralSignature:
    model_type: str
    granularity: str
    timestep_count: int
    scenario_count: int
    bid_grid: tuple[float, ...]
    dst_shape: str
    physical_config_hash: str
    quota_structure: str

    @property
    def digest(self) -> str:
        return stable_hash(asdict(self))


def dst_shape_for_steps(granularity: str, timestep_count: int, delivery_days: int | None = None) -> str:
    resolution = str(granularity).strip().lower()
    per_day = 4 if resolution in {"quarter_hour", "quarter-hour", "qh", "15min"} else 1
    nominal = 96 if per_day == 4 else 24
    days = int(delivery_days or max(1, round(int(timestep_count) / nominal)))
    delta = int(timestep_count) - days * nominal
    return f"{days}d_{int(timestep_count)}steps_dst_delta_{delta:+d}"


class StructuralTemplateCache:
    """Small in-process cache for immutable structural metadata.

    It never stores realised prices or mutable model state. A cache hit proves
    that the same structure was seen; it does not imply that a Pyomo model was
    reused. Callers must report ``pyomo_model_rebuilt`` separately.
    """

    def __init__(self) -> None:
        self._entries: dict[str, Mapping[str, Any]] = {}

    def register(self, signature: StructuralSignature, metadata: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
        key = signature.digest
        if key in self._entries:
            return "hit", self._entries[key]
        frozen = dict(metadata)
        self._entries[key] = frozen
        return "miss_registered", frozen

    def clear(self) -> None:
        self._entries.clear()


def peak_working_set_mb() -> float | None:
    try:
        import psutil  # type: ignore

        return float(psutil.Process(os.getpid()).memory_info().rss / (1024.0 * 1024.0))
    except Exception:
        return None


class PerformanceProfiler:
    def __init__(self, **base: Any) -> None:
        self.base = {str(key): value for key, value in base.items()}
        self.records: list[dict[str, Any]] = []

    @contextmanager
    def track(self, stage: str, **details: Any) -> Iterator[None]:
        started_utc = datetime.now(tz=timezone.utc).isoformat()
        started = perf_counter()
        try:
            yield
        finally:
            self.records.append(
                {
                    **self.base,
                    **details,
                    "stage": str(stage),
                    "started_utc": started_utc,
                    "wall_time_seconds": float(perf_counter() - started),
                    "working_set_mb": peak_working_set_mb(),
                }
            )


def runtime_record(**values: Any) -> dict[str, Any]:
    record = {column: None for column in RUNTIME_COLUMNS}
    record.update(values)
    record["schema_version"] = PERFORMANCE_SCHEMA_VERSION
    missing = set(values).difference(record)
    if missing:
        raise ValueError(f"Unknown performance runtime fields: {sorted(missing)}")
    return record


def parity_difference(
    legacy: Mapping[str, Any],
    optimized: Mapping[str, Any],
    *,
    fields: Sequence[str],
    absolute_tolerance: float,
    relative_tolerance: float = 1e-6,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in fields:
        left = float(legacy[field])
        right = float(optimized[field])
        difference = right - left
        limit = max(float(absolute_tolerance), float(relative_tolerance) * max(abs(left), abs(right)))
        rows.append(
            {
                "field": field,
                "legacy_value": left,
                "optimized_value": right,
                "difference": difference,
                "tolerance": limit,
                "passed": abs(difference) <= limit,
            }
        )
    return rows
