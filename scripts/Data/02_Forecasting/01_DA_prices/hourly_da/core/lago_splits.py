from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import matplotlib
import pandas as pd

from .lago_lear_config import LagoLearBenchmarkConfig


def _running_inside_ipykernel() -> bool:
    try:
        from IPython import get_ipython
    except Exception:
        return False
    shell = get_ipython()
    return shell is not None and shell.__class__.__name__ == "ZMQInteractiveShell"


if not _running_inside_ipykernel():
    matplotlib.use("Agg")

import matplotlib.pyplot as plt


@dataclass(frozen=True)
class LagoSplitConfig:
    split_policy: str = "lago_104w_test"
    custom_validation_start_local: date | None = None
    custom_test_start_local: date | None = None
    thesis_official_train_start_local: date = date(2022, 1, 1)
    thesis_official_train_end_local: date = date(2023, 9, 30)
    thesis_official_validation_start_local: date = date(2023, 10, 1)
    thesis_official_validation_end_local: date = date(2024, 9, 30)
    thesis_official_test_start_local: date = date(2024, 10, 1)
    thesis_official_test_end_local: date = date(2025, 9, 30)


def _date_range(start_local: date, end_local: date) -> list[date]:
    if end_local < start_local:
        return []
    days: list[date] = []
    cursor = start_local
    while cursor <= end_local:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def build_split_days(
    config: LagoLearBenchmarkConfig,
    split_config: LagoSplitConfig,
) -> pd.DataFrame:
    days = config.benchmark_delivery_days()
    if not days:
        return pd.DataFrame(columns=["delivery_local_date", "dataset_split"])

    if split_config.split_policy == "lago_104w_test":
        end_day = config.benchmark_end_inclusive_local_date()
        test_start = end_day - timedelta(days=(104 * 7) - 1)
        validation_end = test_start - timedelta(days=1)
        validation_start = validation_end - timedelta(days=(52 * 7) - 1)
        train_start = config.benchmark_start_local_date
        train_end = validation_start - timedelta(days=1)
    elif split_config.split_policy == "thesis_official":
        train_start = split_config.thesis_official_train_start_local
        train_end = split_config.thesis_official_train_end_local
        validation_start = split_config.thesis_official_validation_start_local
        validation_end = split_config.thesis_official_validation_end_local
        test_start = split_config.thesis_official_test_start_local
        end_day = min(config.benchmark_end_inclusive_local_date(), split_config.thesis_official_test_end_local)
    elif split_config.split_policy == "custom":
        if split_config.custom_validation_start_local is None or split_config.custom_test_start_local is None:
            raise ValueError("Custom split policy requires custom_validation_start_local and custom_test_start_local.")
        train_start = config.benchmark_start_local_date
        train_end = split_config.custom_validation_start_local - timedelta(days=1)
        validation_start = split_config.custom_validation_start_local
        validation_end = split_config.custom_test_start_local - timedelta(days=1)
        test_start = split_config.custom_test_start_local
        end_day = config.benchmark_end_inclusive_local_date()
    else:
        raise ValueError(f"Unsupported split policy: {split_config.split_policy}")

    train_set = set(_date_range(train_start, train_end))
    validation_set = set(_date_range(validation_start, validation_end))
    test_set = set(_date_range(test_start, end_day))

    rows: list[dict[str, Any]] = []
    for day in days:
        split_name: str | None
        if day in train_set:
            split_name = "train"
        elif day in validation_set:
            split_name = "validation"
        elif day in test_set:
            split_name = "test"
        else:
            split_name = None
        rows.append(
            {
                "delivery_local_date": day.isoformat(),
                "dataset_split": split_name,
            }
        )

    frame = pd.DataFrame(rows)
    return frame


def split_summary_payload(
    split_days: pd.DataFrame,
    split_policy: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "split_policy": str(split_policy),
        "total_days": int(split_days.shape[0]),
    }
    for split_name in ("train", "validation", "test"):
        part = split_days[split_days["dataset_split"] == split_name]
        payload[f"{split_name}_days"] = int(part.shape[0])
        payload[f"{split_name}_start_local_date"] = str(part["delivery_local_date"].min()) if not part.empty else None
        payload[f"{split_name}_end_local_date"] = str(part["delivery_local_date"].max()) if not part.empty else None
    payload["unassigned_days"] = int(split_days["dataset_split"].isna().sum())
    return payload


def plot_split_visualization(split_days: pd.DataFrame, output_path: Path) -> None:
    if split_days.empty:
        return
    split_days = split_days.copy()
    split_days["delivery_local_date"] = pd.to_datetime(split_days["delivery_local_date"], errors="coerce")
    split_days = split_days.dropna(subset=["delivery_local_date"]).sort_values("delivery_local_date")
    if split_days.empty:
        return

    color_map = {
        "train": "#d8ead4",
        "validation": "#f4ebc9",
        "test": "#f1d7d4",
        None: "#e8edf2",
    }

    fig, ax = plt.subplots(figsize=(14, 2.8))
    start = split_days["delivery_local_date"].min()
    end = split_days["delivery_local_date"].max()
    current_split = None
    segment_start = start
    for row in split_days.to_dict(orient="records"):
        row_date = pd.Timestamp(row["delivery_local_date"])
        split_name = row["dataset_split"]
        if current_split is None:
            current_split = split_name
            segment_start = row_date
            continue
        if split_name != current_split:
            ax.axvspan(segment_start, row_date, color=color_map.get(current_split, "#e8edf2"), alpha=0.85)
            current_split = split_name
            segment_start = row_date
    ax.axvspan(segment_start, end + pd.Timedelta(days=1), color=color_map.get(current_split, "#e8edf2"), alpha=0.85)

    ax.set_xlim(start, end + pd.Timedelta(days=1))
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_title("Lago LEAR Split Policy", loc="left", fontsize=13, fontweight="bold")
    ax.set_xlabel("Local delivery date")
    for split_name in ("train", "validation", "test"):
        ax.plot([], [], color=color_map[split_name], linewidth=10, label=split_name)
    ax.legend(loc="upper right")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
