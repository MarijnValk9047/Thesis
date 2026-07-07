"""Build a canonical NL Incident Reserve activation-volume tape.

This script converts a local TenneT Frequency Restoration Reserve Activations
CSV into an asset-neutral ISP-long volume table. It does not retrieve data,
does not add prices, and does not integrate with optimisation models.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
MARKET_TIMEZONE = "Europe/Amsterdam"
SOURCE_DATASET = "tennet_frequency_restoration_reserve_activations"
SOURCE_FILE_PATTERN = re.compile(r"_(?P<start>\d{12})_(?P<end>\d{12})_CET")

DEFAULT_INPUT_PATH = (
    REPO_ROOT
    / "data"
    / "02_Forecasting"
    / "02_Balancing_mFRR_IR"
    / "IR_Activation"
    / "frequency_restoration_reserve_activations_202412312300_202512312300_CET (1).csv"
)
DEFAULT_OUTPUT_PATH = (
    REPO_ROOT
    / "data"
    / "02_Forecasting"
    / "02_Balancing_mFRR_IR"
    / "IR_Activation"
    / "nl_ir_activation_volume_tape_isp_v1.csv"
)
DEFAULT_DIAGNOSTICS_PATH = (
    REPO_ROOT
    / "data"
    / "02_Forecasting"
    / "02_Balancing_mFRR_IR"
    / "IR_Activation"
    / "diagnostics"
    / "nl_ir_activation_volume_tape_diagnostics_v1.csv"
)

REQUIRED_COLUMNS = [
    "Timeinterval Start Loc",
    "Timeinterval End Loc",
    "Isp",
    "Quantity Measurement Unit Name",
    "Afrr Down",
    "Afrr Up",
    "Incident Reserve Down",
    "Incident Reserve Up",
    "Absolute Total Volume",
    "Total Volume",
]
TARGET_VOLUME_COLUMNS = ["Incident Reserve Up", "Incident Reserve Down"]
NUMERIC_COLUMNS = [
    "Afrr Down",
    "Afrr Up",
    "Incident Reserve Down",
    "Incident Reserve Up",
    "Absolute Total Volume",
    "Total Volume",
]
QUALITY_FLAGS = [
    "accepted_activation_volume_source",
    "product_scope_to_verify",
    "no_activation_price_in_source",
]


@dataclass(frozen=True)
class PeriodBounds:
    start_utc: pd.Timestamp
    end_utc: pd.Timestamp
    duration: pd.Timedelta


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a canonical ISP-long NL Incident Reserve activation-volume "
            "tape from a local TenneT FRR activations CSV."
        )
    )
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--diagnostics-path", type=Path, default=DEFAULT_DIAGNOSTICS_PATH
    )
    return parser.parse_args()


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def require_columns(frame: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required source columns: {missing}")


def infer_period_from_filename(path: Path, row_count: int) -> PeriodBounds:
    match = SOURCE_FILE_PATTERN.search(path.name)
    if not match:
        raise ValueError(
            "Input filename must contain '<YYYYMMDDHHMM>_<YYYYMMDDHHMM>_CET' "
            "so UTC interval bounds can be reconstructed safely."
        )
    start_utc = pd.to_datetime(match.group("start"), format="%Y%m%d%H%M", utc=True)
    end_utc = pd.to_datetime(match.group("end"), format="%Y%m%d%H%M", utc=True)
    if end_utc <= start_utc:
        raise ValueError("Filename period end must be after period start.")
    if row_count <= 0:
        raise ValueError("Source CSV has no rows.")

    total_seconds = (end_utc - start_utc).total_seconds()
    duration_seconds = total_seconds / row_count
    if duration_seconds <= 0:
        raise ValueError("Inferred nonpositive ISP duration.")
    if abs(duration_seconds - round(duration_seconds)) > 1e-9:
        raise ValueError(
            f"Inferred ISP duration is not an integer number of seconds: {duration_seconds}"
        )
    duration = pd.Timedelta(seconds=int(round(duration_seconds)))
    if duration <= pd.Timedelta(0):
        raise ValueError("Inferred nonpositive ISP duration.")
    return PeriodBounds(start_utc=start_utc, end_utc=end_utc, duration=duration)


def iso_utc(value: pd.Timestamp) -> str:
    return value.isoformat().replace("+00:00", "Z")


def iso_local(value: pd.Timestamp) -> str:
    return value.isoformat()


def read_source(input_path: Path) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")
    frame = pd.read_csv(input_path)
    require_columns(frame, REQUIRED_COLUMNS)

    for column in ["Timeinterval Start Loc", "Timeinterval End Loc"]:
        parsed = pd.to_datetime(frame[column], errors="coerce")
        if parsed.isna().any():
            bad_count = int(parsed.isna().sum())
            raise ValueError(f"{column} has {bad_count} unparsable timestamps.")
        frame[f"_{column}_parsed"] = parsed

    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise")

    units = set(frame["Quantity Measurement Unit Name"].dropna().astype(str).unique())
    if units != {"kWh"}:
        raise ValueError(f"Expected source unit exactly {{'kWh'}}, got {sorted(units)}")

    if frame[TARGET_VOLUME_COLUMNS].isna().any().any():
        raise ValueError("Incident Reserve target volume columns contain missing values.")

    if (frame[TARGET_VOLUME_COLUMNS] < 0).any().any():
        raise ValueError("Incident Reserve target volume columns contain negative values.")

    price_like_columns = [
        column
        for column in frame.columns
        if "price" in column.lower() or "revenue" in column.lower()
    ]
    if price_like_columns:
        raise ValueError(
            "Source CSV unexpectedly contains price/revenue-like columns: "
            f"{price_like_columns}"
        )

    return frame


def add_time_grid(frame: pd.DataFrame, bounds: PeriodBounds) -> pd.DataFrame:
    working = frame.copy()
    working["delivery_date_local"] = working["_Timeinterval Start Loc_parsed"].dt.date.astype(str)
    working["isp_index_local"] = pd.to_numeric(working["Isp"], errors="raise").astype(int)

    local_midnight = pd.to_datetime(working["delivery_date_local"], errors="raise").dt.tz_localize(
        MARKET_TIMEZONE
    )
    local_midnight_utc = local_midnight.dt.tz_convert("UTC")
    isp_offsets = pd.to_timedelta(
        (working["isp_index_local"] - 1) * bounds.duration.total_seconds(), unit="s"
    )
    starts_utc = local_midnight_utc + isp_offsets
    ends_utc = starts_utc + bounds.duration

    if starts_utc.min() != bounds.start_utc or ends_utc.max() != bounds.end_utc:
        raise ValueError(
            "Reconstructed UTC bounds do not match filename period: "
            f"start={starts_utc.min()} expected={bounds.start_utc}, "
            f"end={ends_utc.max()} expected={bounds.end_utc}."
        )
    if starts_utc.duplicated().any():
        raise ValueError("Reconstructed UTC grid contains duplicate interval starts.")

    starts_local = starts_utc.dt.tz_convert(MARKET_TIMEZONE)
    ends_local = ends_utc.dt.tz_convert(MARKET_TIMEZONE)
    source_start_naive = working["_Timeinterval Start Loc_parsed"].reset_index(drop=True)
    source_end_naive = working["_Timeinterval End Loc_parsed"].reset_index(drop=True)
    generated_start_naive = starts_local.dt.tz_localize(None).reset_index(drop=True)
    generated_end_naive = ends_local.dt.tz_localize(None).reset_index(drop=True)

    start_mismatches = source_start_naive.ne(generated_start_naive)
    end_mismatches = source_end_naive.ne(generated_end_naive)
    if start_mismatches.any() or end_mismatches.any():
        raise ValueError(
            "UTC reconstruction does not reproduce source local interval labels: "
            f"start mismatches={int(start_mismatches.sum())}, "
            f"end mismatches={int(end_mismatches.sum())}."
        )

    working["delivery_start_utc_ts"] = starts_utc
    working["delivery_end_utc_ts"] = ends_utc
    working["delivery_start_local_ts"] = starts_local
    working["delivery_end_local_ts"] = ends_local
    working["activation_duration_hours"] = bounds.duration.total_seconds() / 3600.0
    return working


def validate_source_time_grid(frame: pd.DataFrame) -> dict[str, int]:
    day_counts = frame.groupby("delivery_date_local", observed=True).size()
    invalid = day_counts[~day_counts.isin([92, 96, 100])]
    if not invalid.empty:
        raise ValueError(
            "Local day ISP counts must be 92, 96, or 100. Invalid counts: "
            f"{invalid.to_dict()}"
        )

    for day, group in frame.groupby("delivery_date_local", observed=True):
        isp_values = group["isp_index_local"]
        expected = set(range(1, len(group) + 1))
        actual = set(int(value) for value in isp_values)
        if actual != expected:
            raise ValueError(
                f"Local day {day} has non-contiguous ISP index values: "
                f"min={isp_values.min()}, max={isp_values.max()}, count={len(group)}"
            )

    return {
        "normal_day_count": int(day_counts.eq(96).sum()),
        "spring_dst_92_isp_day_count": int(day_counts.eq(92).sum()),
        "autumn_dst_100_isp_day_count": int(day_counts.eq(100).sum()),
    }


def build_volume_tape(frame: pd.DataFrame, input_path: Path) -> pd.DataFrame:
    source_file = repo_relative(input_path)
    base_columns = [
        "delivery_start_utc_ts",
        "delivery_end_utc_ts",
        "delivery_start_local_ts",
        "delivery_end_local_ts",
        "delivery_date_local",
        "isp_index_local",
        "activation_duration_hours",
    ]
    parts: list[pd.DataFrame] = []
    for direction, source_column in [
        ("Up", "Incident Reserve Up"),
        ("Down", "Incident Reserve Down"),
    ]:
        part = frame[base_columns].copy()
        part["direction"] = direction
        part["activation_energy_kwh"] = frame[source_column].astype(float)
        parts.append(part)

    tape = pd.concat(parts, ignore_index=True)
    tape["activation_flag"] = tape["activation_energy_kwh"].gt(0)
    tape["activation_energy_mwh"] = tape["activation_energy_kwh"] / 1000.0
    tape["average_activation_mw"] = (
        tape["activation_energy_mwh"] / tape["activation_duration_hours"]
    )
    tape["source_dataset"] = SOURCE_DATASET
    tape["source_file"] = source_file
    tape["activation_scope"] = "historical_realised_activation_volume"
    tape["reserve_type"] = "Incident Reserve / mFRRda"
    tape["product_type"] = "product_scope_to_verify"
    tape["product_scope_status"] = "product_scope_to_verify"
    tape["historical_realised_flag"] = True
    tape["data_quality_flag"] = ";".join(QUALITY_FLAGS)
    tape = add_activation_clusters(tape)

    tape["delivery_start_utc"] = tape["delivery_start_utc_ts"].map(iso_utc)
    tape["delivery_end_utc"] = tape["delivery_end_utc_ts"].map(iso_utc)
    tape["delivery_start_local"] = tape["delivery_start_local_ts"].map(iso_local)
    tape["delivery_end_local"] = tape["delivery_end_local_ts"].map(iso_local)
    tape["activation_cluster_start_utc"] = tape["activation_cluster_start_utc_ts"].map(
        lambda value: iso_utc(value) if pd.notna(value) else pd.NA
    )
    tape["activation_cluster_end_utc"] = tape["activation_cluster_end_utc_ts"].map(
        lambda value: iso_utc(value) if pd.notna(value) else pd.NA
    )

    ordered_columns = [
        "delivery_start_utc",
        "delivery_end_utc",
        "delivery_start_local",
        "delivery_end_local",
        "delivery_date_local",
        "isp_index_local",
        "direction",
        "activation_flag",
        "activation_energy_kwh",
        "activation_energy_mwh",
        "average_activation_mw",
        "activation_duration_hours",
        "source_dataset",
        "source_file",
        "activation_scope",
        "reserve_type",
        "product_type",
        "product_scope_status",
        "historical_realised_flag",
        "data_quality_flag",
        "activation_cluster_id",
        "activation_cluster_length_isps",
        "activation_cluster_start_utc",
        "activation_cluster_end_utc",
    ]
    return (
        tape[ordered_columns]
        .sort_values(["delivery_start_utc", "direction"], kind="stable")
        .reset_index(drop=True)
    )


def add_activation_clusters(tape: pd.DataFrame) -> pd.DataFrame:
    working = tape.sort_values(["direction", "delivery_start_utc_ts"], kind="stable").copy()
    working["activation_cluster_id"] = pd.NA
    working["activation_cluster_length_isps"] = pd.NA
    working["activation_cluster_start_utc_ts"] = pd.NA
    working["activation_cluster_end_utc_ts"] = pd.NA

    for direction, group in working.groupby("direction", sort=False):
        previous_active = False
        previous_end = None
        current_cluster_id = 0
        active_indices: list[int] = []
        cluster_by_index: dict[int, str] = {}
        for index, row in group.iterrows():
            active = bool(row["activation_flag"])
            consecutive = previous_end is not None and row["delivery_start_utc_ts"] == previous_end
            if active and (not previous_active or not consecutive):
                current_cluster_id += 1
            if active:
                cluster_by_index[index] = f"{direction}_{current_cluster_id:03d}"
                active_indices.append(index)
            previous_active = active
            previous_end = row["delivery_end_utc_ts"]

        if not active_indices:
            continue

        cluster_series = pd.Series(cluster_by_index, dtype="string")
        working.loc[cluster_series.index, "activation_cluster_id"] = cluster_series
        for cluster_id, cluster_rows in working.loc[active_indices].groupby(
            "activation_cluster_id", sort=False
        ):
            indices = cluster_rows.index
            working.loc[indices, "activation_cluster_length_isps"] = len(cluster_rows)
            working.loc[indices, "activation_cluster_start_utc_ts"] = cluster_rows[
                "delivery_start_utc_ts"
            ].min()
            working.loc[indices, "activation_cluster_end_utc_ts"] = cluster_rows[
                "delivery_end_utc_ts"
            ].max()

    return working.sort_index()


def validate_output(tape: pd.DataFrame) -> None:
    required_directions = {"Up", "Down"}
    actual_directions = set(tape["direction"].dropna().unique())
    if actual_directions != required_directions:
        raise ValueError(f"Output directions must be Up/Down, got {actual_directions}")
    if tape.duplicated(["delivery_start_utc", "direction"]).any():
        raise ValueError("Duplicate delivery_start_utc x direction rows in output tape.")
    if tape["activation_energy_kwh"].lt(0).any():
        raise ValueError("Output tape contains negative activation energy.")
    if tape["activation_duration_hours"].le(0).any():
        raise ValueError("Output tape contains nonpositive activation duration.")
    if not tape["activation_flag"].equals(tape["activation_energy_kwh"].gt(0)):
        raise ValueError("activation_flag does not equal activation_energy_kwh > 0.")
    price_like_columns = [
        column
        for column in tape.columns
        if "price" in column.lower() or "revenue" in column.lower()
    ]
    if price_like_columns:
        raise ValueError(f"Output tape must not include price/revenue columns: {price_like_columns}")


def nullable_mean(series: pd.Series) -> float | None:
    if series.empty:
        return None
    return float(series.mean())


def build_diagnostics(
    tape: pd.DataFrame,
    source: pd.DataFrame,
    day_count_info: dict[str, int],
) -> pd.DataFrame:
    source_by_time = source.set_index("delivery_start_utc_ts")
    both_nonzero = (
        source_by_time["Incident Reserve Up"].gt(0)
        & source_by_time["Incident Reserve Down"].gt(0)
    )
    full_start_utc = tape["delivery_start_utc"].min()
    full_end_utc = tape["delivery_end_utc"].max()
    full_start_local = tape["delivery_start_local"].min()
    full_end_local = tape["delivery_end_local"].max()
    rows: list[dict[str, object]] = []

    for direction, group in tape.groupby("direction", sort=True):
        active = group[group["activation_flag"]].copy()
        cluster_lengths = (
            active.dropna(subset=["activation_cluster_id"])
            .drop_duplicates("activation_cluster_id")["activation_cluster_length_isps"]
            .astype(float)
        )
        rows.append(
            {
                "row_count": int(len(tape)),
                "start_utc": full_start_utc,
                "end_utc": full_end_utc,
                "start_local": full_start_local,
                "end_local": full_end_local,
                **day_count_info,
                "direction": direction,
                "interval_count": int(len(group)),
                "nonzero_activation_interval_count": int(len(active)),
                "activation_frequency": float(len(active) / len(group)) if len(group) else 0.0,
                "mean_nonzero_activation_energy_kwh": nullable_mean(
                    active["activation_energy_kwh"]
                ),
                "max_activation_energy_kwh": float(active["activation_energy_kwh"].max())
                if len(active)
                else 0.0,
                "mean_nonzero_average_activation_mw": nullable_mean(
                    active["average_activation_mw"]
                ),
                "max_average_activation_mw": float(active["average_activation_mw"].max())
                if len(active)
                else 0.0,
                "activation_cluster_count": int(
                    active["activation_cluster_id"].dropna().nunique()
                ),
                "mean_cluster_length_isps": nullable_mean(cluster_lengths),
                "max_cluster_length_isps": int(cluster_lengths.max())
                if len(cluster_lengths)
                else 0,
                "both_up_down_nonzero_interval_count": int(both_nonzero.sum()),
                "missing_value_count": int(group["activation_energy_kwh"].isna().sum()),
                "negative_value_count": int(group["activation_energy_kwh"].lt(0).sum()),
            }
        )
    return pd.DataFrame(rows)


def write_outputs(tape: pd.DataFrame, diagnostics: pd.DataFrame, output_path: Path, diagnostics_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    tape.to_csv(output_path, index=False)
    diagnostics.to_csv(diagnostics_path, index=False)


def run(input_path: Path, output_path: Path, diagnostics_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    source = read_source(input_path)
    bounds = infer_period_from_filename(input_path, len(source))
    source = add_time_grid(source, bounds)
    day_count_info = validate_source_time_grid(source)
    tape = build_volume_tape(source, input_path)
    validate_output(tape)
    diagnostics = build_diagnostics(tape, source, day_count_info)
    write_outputs(tape, diagnostics, output_path, diagnostics_path)
    return tape, diagnostics


def main() -> int:
    args = parse_args()
    tape, diagnostics = run(
        input_path=args.input_path,
        output_path=args.output_path,
        diagnostics_path=args.diagnostics_path,
    )
    print(f"Wrote {repo_relative(args.output_path)} rows={len(tape)}")
    print(f"Wrote {repo_relative(args.diagnostics_path)} rows={len(diagnostics)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
