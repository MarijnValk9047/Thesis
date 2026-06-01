from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .plant_parameters import HydrogenConfig


@dataclass(frozen=True)
class ExecutionPeriod:
    mode: str
    labels: tuple[str, ...]
    start_local_date: date
    end_local_date: date
    days: tuple[date, ...]

    def as_manifest_record(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "labels": list(self.labels),
            "start_local_date": self.start_local_date.isoformat(),
            "end_local_date": self.end_local_date.isoformat(),
            "days": [day.isoformat() for day in self.days],
        }


def _load_selected_weeks(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Selected weeks file not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows = payload.get("selected_weeks", []) if isinstance(payload, dict) else []
    frame = pd.DataFrame(rows)
    required = {"label", "start_local_date", "end_local_date"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"selected_weeks.yaml is missing required fields: {sorted(missing)}")
    frame["label"] = frame["label"].astype(str)
    frame["start_local_date"] = pd.to_datetime(frame["start_local_date"]).dt.date
    frame["end_local_date"] = pd.to_datetime(frame["end_local_date"]).dt.date
    return frame


def _date_range_days(start_day: date, end_day: date) -> tuple[date, ...]:
    days = pd.date_range(start_day, end_day, freq="D")
    return tuple(pd.Timestamp(value).date() for value in days)


def resolve_execution_period(config: HydrogenConfig) -> ExecutionPeriod:
    mode = str(config.experiment.execution_mode).strip().lower()
    if mode == "selected_weeks":
        selected = _load_selected_weeks(config.experiment.selected_weeks_source)
        labels = list(config.experiment.selected_week_labels)
        if labels:
            selected = selected[selected["label"].isin(labels)].copy()
        if selected.empty:
            raise ValueError(
                "No selected weeks matched the configured labels. "
                f"Source: {config.experiment.selected_weeks_source}, labels: {labels}"
            )
        start_day = min(selected["start_local_date"])
        end_day = max(selected["end_local_date"])
        return ExecutionPeriod(
            mode="selected_weeks",
            labels=tuple(selected["label"].astype(str).tolist()),
            start_local_date=start_day,
            end_local_date=end_day,
            days=_date_range_days(start_day, end_day),
        )
    if mode == "custom_period":
        if config.experiment.custom_start is None or config.experiment.custom_end is None:
            raise ValueError("custom_period requires experiment.custom_start and experiment.custom_end.")
        start_day = pd.Timestamp(config.experiment.custom_start).date()
        end_day = pd.Timestamp(config.experiment.custom_end).date()
        if end_day < start_day:
            raise ValueError("custom_end must be on or after custom_start.")
        return ExecutionPeriod(
            mode="custom_period",
            labels=("custom_period",),
            start_local_date=start_day,
            end_local_date=end_day,
            days=_date_range_days(start_day, end_day),
        )
    raise ValueError(f"Unsupported execution_mode: {config.experiment.execution_mode}")


def filter_scenarios_to_period(
    scenarios: pd.DataFrame,
    *,
    period: ExecutionPeriod,
    dataset_split: str | None = None,
) -> pd.DataFrame:
    frame = scenarios.copy()
    if dataset_split is not None and "dataset_split" in frame.columns:
        frame = frame[frame["dataset_split"].astype(str) == str(dataset_split)].copy()
    if frame.empty:
        raise ValueError(
            "Scenario table is empty after split filtering. "
            f"Requested split={dataset_split}. Check scenario_catalog split configuration."
        )

    available_min = pd.to_datetime(frame["delivery_start_local"], errors="coerce").dropna().min()
    available_max = pd.to_datetime(frame["delivery_start_local"], errors="coerce").dropna().max()
    frame["delivery_local_date"] = pd.to_datetime(frame["delivery_start_local"], errors="coerce").dt.date
    mask = (frame["delivery_local_date"] >= period.start_local_date) & (frame["delivery_local_date"] <= period.end_local_date)
    frame = frame[mask].copy()
    if frame.empty:
        raise ValueError(
            "Scenario table is empty after period filtering. "
            f"Period: {period.start_local_date}..{period.end_local_date}, split: {dataset_split}. "
            f"Available local coverage for this split/model selection: "
            f"{available_min.date() if pd.notna(available_min) else 'unknown'}..{available_max.date() if pd.notna(available_max) else 'unknown'}."
        )
    return frame.reset_index(drop=True)
