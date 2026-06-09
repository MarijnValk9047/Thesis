from __future__ import annotations

import csv
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[4]
IR_ROOT = PROJECT_ROOT / "data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity"
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
UTC = timezone.utc

KNOWN_AT_ASSUMPTION_09 = (
    "incident_reserve_capacity_auction_d_minus_1_09am_europe_amsterdam_and_result_known_before_dam_closure"
)

TIMING_COLUMNS = {
    "forecast_origin_utc",
    "forecast_origin_local",
    "known_at_cutoff_utc",
    "known_at_assumption",
}

ARTIFACTS = [
    "nl_ir_capacity_target_daily_direction.csv",
    "nl_ir_capacity_features_endogenous_da_aligned_daily_direction.csv",
    "nl_ir_capacity_features_exogenous_small_da_aligned_daily_direction.csv",
    "nl_ir_capacity_forecast_naive7d_da_aligned_daily_direction_long.csv",
    "nl_ir_capacity_forecast_lear_exogenous_small_da_aligned_daily_direction_long.csv",
    "nl_ir_capacity_forecast_xgboost_exogenous_small_da_aligned_daily_direction_long.csv",
    "nl_ir_capacity_12_3_f_threshold_scenarios_da_aligned_daily_direction_long.csv",
]


@dataclass
class RepairResult:
    path: Path
    row_count: int
    changed_columns: list[str]
    original_local_examples: list[str]
    repaired_local_examples: list[str]


def parse_delivery_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def make_cutoff(delivery_date_local: date) -> tuple[datetime, datetime]:
    previous_day = delivery_date_local - timedelta(days=1)
    local_dt = datetime.combine(previous_day, time(hour=9, minute=0), tzinfo=AMSTERDAM)
    return local_dt, local_dt.astimezone(UTC)


def infer_format_style(sample: str | None) -> str:
    if not sample:
        return "iso_tz_t"
    if sample.endswith("Z"):
        return "utc_z"
    if "T" in sample:
        return "iso_tz_t"
    if "+" in sample:
        return "iso_tz_space"
    return "plain"


def format_datetime(value: datetime, style: str) -> str:
    if style == "utc_z":
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if style == "iso_tz_space":
        return value.isoformat(sep=" ")
    if style == "plain":
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value.isoformat()


def load_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        if reader.fieldnames is None:
            raise ValueError(f"{path.name} is missing a header row.")
        return rows, list(reader.fieldnames)


def write_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        delete=False,
        dir=path.parent,
        suffix=".tmp",
    ) as handle:
        temp_path = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)


def validate_no_non_timing_changes(
    original_rows: list[dict[str, str]],
    repaired_rows: list[dict[str, str]],
    path: Path,
) -> None:
    if len(original_rows) != len(repaired_rows):
        raise ValueError(f"{path.name}: row count changed during timing repair.")
    for idx, (before, after) in enumerate(zip(original_rows, repaired_rows), start=1):
        for key, before_value in before.items():
            if key in TIMING_COLUMNS:
                continue
            if before_value != after.get(key):
                raise ValueError(
                    f"{path.name}: non-timing field changed at row {idx}, column {key}."
                )


def validate_repaired_rows(rows: list[dict[str, str]], path: Path) -> None:
    for idx, row in enumerate(rows, start=1):
        delivery_date_local = parse_delivery_date(row["delivery_date_local"])
        local_dt, utc_dt = make_cutoff(delivery_date_local)

        if "forecast_origin_local" in row and row["forecast_origin_local"]:
            parsed_local = datetime.fromisoformat(row["forecast_origin_local"])
            if parsed_local != local_dt:
                raise ValueError(f"{path.name}: forecast_origin_local mismatch at row {idx}.")
        if "forecast_origin_utc" in row and row["forecast_origin_utc"]:
            parsed_origin_utc = datetime.fromisoformat(row["forecast_origin_utc"].replace("Z", "+00:00"))
            if parsed_origin_utc != utc_dt:
                raise ValueError(f"{path.name}: forecast_origin_utc mismatch at row {idx}.")
        if "known_at_cutoff_utc" in row and row["known_at_cutoff_utc"]:
            parsed_cutoff_utc = datetime.fromisoformat(row["known_at_cutoff_utc"].replace("Z", "+00:00"))
            if parsed_cutoff_utc != utc_dt:
                raise ValueError(f"{path.name}: known_at_cutoff_utc mismatch at row {idx}.")
        if "known_at_assumption" in row and row["known_at_assumption"]:
            lowered = row["known_at_assumption"].lower()
            if "10am" in lowered or "10:00" in lowered:
                raise ValueError(f"{path.name}: known_at_assumption still references 10:00 at row {idx}.")


def repair_artifact(path: Path) -> RepairResult:
    original_rows, fieldnames = load_rows(path)
    repaired_rows = [dict(row) for row in original_rows]
    column_samples: dict[str, str | None] = {}
    for column in ["forecast_origin_local", "forecast_origin_utc", "known_at_cutoff_utc"]:
        sample = next((row[column] for row in original_rows if column in row and row[column]), None)
        column_samples[column] = sample

    changed_columns: set[str] = set()
    original_local_examples: list[str] = []
    repaired_local_examples: list[str] = []

    for row in repaired_rows:
        delivery_date_local = parse_delivery_date(row["delivery_date_local"])
        local_dt, utc_dt = make_cutoff(delivery_date_local)

        if "forecast_origin_local" in row and row["forecast_origin_local"]:
            original_local_examples.append(row["forecast_origin_local"])
            row["forecast_origin_local"] = format_datetime(local_dt, infer_format_style(column_samples["forecast_origin_local"]))
            repaired_local_examples.append(row["forecast_origin_local"])
            changed_columns.add("forecast_origin_local")
        if "forecast_origin_utc" in row and row["forecast_origin_utc"]:
            row["forecast_origin_utc"] = format_datetime(utc_dt, infer_format_style(column_samples["forecast_origin_utc"]))
            changed_columns.add("forecast_origin_utc")
        if "known_at_cutoff_utc" in row and row["known_at_cutoff_utc"]:
            row["known_at_cutoff_utc"] = format_datetime(utc_dt, infer_format_style(column_samples["known_at_cutoff_utc"]))
            changed_columns.add("known_at_cutoff_utc")
        if "known_at_assumption" in row and row["known_at_assumption"]:
            row["known_at_assumption"] = KNOWN_AT_ASSUMPTION_09
            changed_columns.add("known_at_assumption")

    validate_no_non_timing_changes(original_rows, repaired_rows, path)
    write_rows(path, repaired_rows, fieldnames)
    validate_repaired_rows(repaired_rows, path)

    return RepairResult(
        path=path,
        row_count=len(repaired_rows),
        changed_columns=sorted(changed_columns),
        original_local_examples=original_local_examples[:3],
        repaired_local_examples=repaired_local_examples[:3],
    )


def main() -> None:
    results: list[RepairResult] = []
    for name in ARTIFACTS:
        path = IR_ROOT / name
        if not path.exists():
            raise FileNotFoundError(f"Required artifact missing: {path}")
        results.append(repair_artifact(path))

    for result in results:
        print(
            {
                "file": result.path.name,
                "row_count": result.row_count,
                "changed_columns": result.changed_columns,
                "original_local_examples": result.original_local_examples,
                "repaired_local_examples": result.repaired_local_examples,
            }
        )


if __name__ == "__main__":
    main()
