from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ProgressPaths:
    log_csv: Path
    current_json: Path


class ProgressReporter:
    def __init__(
        self,
        *,
        run_id: str,
        run_folder: Path,
        split: str,
        period_mode: str,
        total_solves: int,
        progress_paths: ProgressPaths | None = None,
    ) -> None:
        self.run_id = str(run_id)
        self.run_folder = Path(run_folder)
        self.split = str(split)
        self.period_mode = str(period_mode)
        self.total_solves = int(total_solves)
        self.started = perf_counter()
        self.completed_solves = 0
        self.failures_so_far = 0
        self._rows: list[dict[str, Any]] = []
        self.paths = progress_paths or ProgressPaths(
            log_csv=self.run_folder / "progress_log.csv",
            current_json=self.run_folder / "progress_current.json",
        )
        self.paths.log_csv.parent.mkdir(parents=True, exist_ok=True)
        self._write_current(
            current_status="initialised",
            current_regime="",
            current_model="",
            current_delivery_day="",
            warning="",
        )

    def record_solve(
        self,
        *,
        regime: str,
        model: str,
        delivery_day: str,
        gamma: float,
        build_seconds: float,
        solver_seconds: float,
        postprocess_seconds: float,
        status: str,
        mip_gap: float | None,
        variables: int,
        binaries: int,
        constraints: int,
        warning: str = "",
    ) -> None:
        self.completed_solves += 1
        elapsed = perf_counter() - self.started
        completed = max(self.completed_solves, 1)
        average_seconds = elapsed / float(completed)
        remaining = max(self.total_solves - self.completed_solves, 0)
        eta_seconds = average_seconds * float(remaining)
        status_text = str(status)
        if status_text.strip().lower() != "optimal":
            self.failures_so_far += 1
        row = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "run_id": self.run_id,
            "split": self.split,
            "period_mode": self.period_mode,
            "regime": str(regime),
            "model": str(model),
            "delivery_day": str(delivery_day),
            "gamma": float(gamma),
            "solve_index": int(self.completed_solves),
            "total_solves": int(self.total_solves),
            "build_seconds": float(build_seconds),
            "solver_seconds": float(solver_seconds),
            "postprocess_seconds": float(postprocess_seconds),
            "status": status_text,
            "mip_gap": None if mip_gap is None else float(mip_gap),
            "variables": int(variables),
            "binaries": int(binaries),
            "constraints": int(constraints),
            "eta_seconds": float(eta_seconds),
            "warning": str(warning),
        }
        self._rows.append(row)
        self._write_log()
        current_status = "running"
        if self.completed_solves >= self.total_solves:
            current_status = "complete_with_failures" if self.failures_so_far > 0 else "complete"
        self._write_current(
            current_status=current_status,
            current_regime=str(regime),
            current_model=str(model),
            current_delivery_day=str(delivery_day),
            warning=str(warning),
            estimated_remaining_seconds=eta_seconds,
        )
        print(
            f"[{self.completed_solves}/{self.total_solves}] regime={regime} model={model} day={delivery_day} "
            f"status={status_text} build={build_seconds:.2f}s solve={solver_seconds:.2f}s "
            f"post={postprocess_seconds:.2f}s eta={eta_seconds:.1f}s"
        )

    def mark_failed(self, *, regime: str, model: str, delivery_day: str, warning: str) -> None:
        self.failures_so_far += 1
        self._write_current(
            current_status="failed",
            current_regime=str(regime),
            current_model=str(model),
            current_delivery_day=str(delivery_day),
            warning=str(warning),
            estimated_remaining_seconds=None,
        )

    def _write_log(self) -> None:
        pd.DataFrame(self._rows).to_csv(self.paths.log_csv, index=False)

    def _write_current(
        self,
        *,
        current_status: str,
        current_regime: str,
        current_model: str,
        current_delivery_day: str,
        warning: str,
        estimated_remaining_seconds: float | None = None,
    ) -> None:
        elapsed = perf_counter() - self.started
        payload = {
            "run_id": self.run_id,
            "run_folder": str(self.run_folder),
            "current_status": str(current_status),
            "completed_solves": int(self.completed_solves),
            "total_solves": int(self.total_solves),
            "percent_complete": float(0.0 if self.total_solves <= 0 else 100.0 * self.completed_solves / self.total_solves),
            "current_regime": str(current_regime),
            "current_model": str(current_model),
            "current_delivery_day": str(current_delivery_day),
            "elapsed_seconds": float(elapsed),
            "estimated_remaining_seconds": None if estimated_remaining_seconds is None else float(estimated_remaining_seconds),
            "failures_so_far": int(self.failures_so_far),
            "last_update_timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "warning": str(warning),
        }
        self.paths.current_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
