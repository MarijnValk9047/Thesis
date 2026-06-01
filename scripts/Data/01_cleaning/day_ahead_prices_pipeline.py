from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib
import pandas as pd


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


NAMESPACE = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}
RESOLUTION_PATTERN = re.compile(r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?$")
REGION_DIR_PATTERN = re.compile(r"^DA_prices_(?P<region>[A-Z]{2})$")


@dataclass
class ParseSummary:
    file_summaries: list[dict[str, Any]] = field(default_factory=list)
    parse_errors: list[dict[str, str]] = field(default_factory=list)


@dataclass
class MissingDatapointFixResult:
    cleaned_frame: pd.DataFrame
    gap_details: pd.DataFrame
    summary: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Unified DA prices pipeline: clean raw XML, split hourly/quarterly, "
            "write diagnostics and plots."
        )
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/00_Raw/DA_Prices"),
        help="Path to raw DA folder with DA_prices_<REGION> subfolders.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/01_cleaned/Day_ahead_prices"),
        help="Output root folder.",
    )
    parser.add_argument(
        "--cutoff-local-date",
        type=str,
        default="2025-10-01",
        help="Local date (Europe/Brussels) from which 15-minute granularity starts.",
    )
    parser.add_argument(
        "--local-timezone",
        type=str,
        default="Europe/Brussels",
        help="Timezone for cutoff interpretation.",
    )
    parser.add_argument(
        "--regions",
        nargs="+",
        default=["BE", "DE", "NL"],
        help="Region codes to process.",
    )
    parser.add_argument(
        "--quarterly-regions",
        nargs="+",
        default=["NL"],
        help=(
            "Region codes that should switch from hourly to quarter-hourly data from the cutoff date onward. "
            "Regions not listed here keep their hourly series across the full cleaned horizon."
        ),
    )
    parser.add_argument(
        "--max-timestamp-utc",
        type=str,
        default="2026-01-01T00:00:00Z",
        help="Keep data points with timestamp_utc <= this UTC timestamp.",
    )
    return parser.parse_args()


def local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def parse_resolution_to_minutes(resolution: str | None) -> int | None:
    if not resolution:
        return None
    match = RESOLUTION_PATTERN.match(resolution.strip())
    if not match:
        return None
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    total = hours * 60 + minutes
    return total or None


def parse_ts(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    return ts if pd.notna(ts) else None


def find_text(elem: ET.Element, path: str) -> str | None:
    found = elem.find(path, NAMESPACE)
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text if text else None


def find_region_directories(raw_root: Path, regions: list[str]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    allowed = set(regions)
    for child in raw_root.iterdir():
        if not child.is_dir():
            continue
        match = REGION_DIR_PATTERN.match(child.name)
        if not match:
            continue
        region = match.group("region")
        if region in allowed:
            found[region] = child
    return dict(sorted(found.items()))


def parse_single_xml(region: str, xml_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    rows: list[dict[str, Any]] = []
    document_id = find_text(root, "ns:mRID")
    created_datetime_utc = parse_ts(find_text(root, "ns:createdDateTime"))
    doc_period_start_utc = parse_ts(find_text(root, "ns:period.timeInterval/ns:start"))
    doc_period_end_utc = parse_ts(find_text(root, "ns:period.timeInterval/ns:end"))

    resolution_counter: Counter[str] = Counter()
    point_count = 0
    timeseries_count = 0
    period_count = 0

    for timeseries_index, timeseries in enumerate(root.findall("ns:TimeSeries", NAMESPACE), start=1):
        timeseries_count += 1
        auction_type = find_text(timeseries, "ns:auction.type")
        business_type = find_text(timeseries, "ns:businessType")
        in_domain = find_text(timeseries, "ns:in_Domain.mRID")
        out_domain = find_text(timeseries, "ns:out_Domain.mRID")
        contract_type = find_text(timeseries, "ns:contract_MarketAgreement.type")
        currency_unit = find_text(timeseries, "ns:currency_Unit.name")
        price_unit = find_text(timeseries, "ns:price_Measure_Unit.name")
        curve_type = find_text(timeseries, "ns:curveType")
        sequence_position_text = find_text(timeseries, "ns:classificationSequence_AttributeInstanceComponent.position")
        try:
            sequence_position = int(sequence_position_text) if sequence_position_text is not None else None
        except ValueError:
            sequence_position = None

        for period_index, period in enumerate(timeseries.findall("ns:Period", NAMESPACE), start=1):
            period_count += 1
            period_start_utc = parse_ts(find_text(period, "ns:timeInterval/ns:start"))
            period_end_utc = parse_ts(find_text(period, "ns:timeInterval/ns:end"))
            resolution = find_text(period, "ns:resolution")
            resolution_counter.update([resolution or "missing"])
            resolution_minutes = parse_resolution_to_minutes(resolution)

            for point in period.findall("ns:Point", NAMESPACE):
                point_count += 1
                position_text = find_text(point, "ns:position")
                price_text = find_text(point, "ns:price.amount")

                try:
                    position = int(position_text) if position_text is not None else None
                except ValueError:
                    position = None

                try:
                    price = float(price_text) if price_text is not None else None
                except ValueError:
                    price = None

                timestamp_utc = None
                if period_start_utc is not None and resolution_minutes and position is not None:
                    timestamp_utc = period_start_utc + pd.to_timedelta((position - 1) * resolution_minutes, unit="minute")

                rows.append(
                    {
                        "region": region,
                        "timestamp_utc": timestamp_utc,
                        "price_eur_per_mwh": price,
                        "resolution": resolution,
                        "resolution_minutes": resolution_minutes,
                        "position": position,
                        "period_start_utc": period_start_utc,
                        "period_end_utc": period_end_utc,
                        "created_datetime_utc": created_datetime_utc,
                        "document_id": document_id,
                        "auction_type": auction_type,
                        "business_type": business_type,
                        "in_domain": in_domain,
                        "out_domain": out_domain,
                        "contract_type": contract_type,
                        "currency_unit": currency_unit,
                        "price_unit": price_unit,
                        "curve_type": curve_type,
                        "timeseries_sequence_position": sequence_position,
                        "source_file": xml_path.name,
                        "source_path": str(xml_path),
                        "timeseries_index": timeseries_index,
                        "period_index": period_index,
                    }
                )

    file_summary = {
        "region": region,
        "source_file": xml_path.name,
        "source_path": str(xml_path),
        "document_id": document_id,
        "created_datetime_utc": created_datetime_utc.isoformat() if created_datetime_utc is not None else None,
        "doc_period_start_utc": doc_period_start_utc.isoformat() if doc_period_start_utc is not None else None,
        "doc_period_end_utc": doc_period_end_utc.isoformat() if doc_period_end_utc is not None else None,
        "timeseries_count": timeseries_count,
        "period_count": period_count,
        "point_count": point_count,
        "rows_generated": len(rows),
        "resolution_distribution": json.dumps(dict(sorted(resolution_counter.items())), sort_keys=True),
    }
    return rows, file_summary


def make_region_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df["period_start_utc"] = pd.to_datetime(df["period_start_utc"], utc=True, errors="coerce")
    df["period_end_utc"] = pd.to_datetime(df["period_end_utc"], utc=True, errors="coerce")
    df["created_datetime_utc"] = pd.to_datetime(df["created_datetime_utc"], utc=True, errors="coerce")
    df["price_eur_per_mwh"] = pd.to_numeric(df["price_eur_per_mwh"], errors="coerce")
    df["resolution_minutes"] = pd.to_numeric(df["resolution_minutes"], errors="coerce").astype("Int64")
    df["position"] = pd.to_numeric(df["position"], errors="coerce").astype("Int64")
    df["timeseries_sequence_position"] = pd.to_numeric(df["timeseries_sequence_position"], errors="coerce").astype("Int64")
    return df


def split_duplicate_stats(df_raw: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if df_raw.empty:
        return df_raw.copy(), 0
    valid = df_raw[df_raw["timestamp_utc"].notna()].copy()
    valid = valid.sort_values(
        ["timestamp_utc", "created_datetime_utc", "source_file", "timeseries_index", "period_index"],
        na_position="first",
    )
    duplicate_rows = int(valid.duplicated(subset=["timestamp_utc"], keep="last").sum())
    clean = valid.drop_duplicates(subset=["timestamp_utc"], keep="last")
    clean = clean.sort_values("timestamp_utc").reset_index(drop=True)
    return clean, duplicate_rows


def clip_to_max_timestamp(df: pd.DataFrame, max_timestamp_utc: pd.Timestamp) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    clipped = df[df["timestamp_utc"] <= max_timestamp_utc].copy()
    return clipped.sort_values("timestamp_utc").reset_index(drop=True)


def resolution_to_iso_string(expected_minutes: int) -> str | None:
    if expected_minutes <= 0:
        return None
    hours, minutes = divmod(expected_minutes, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}H")
    if minutes:
        parts.append(f"{minutes}M")
    return f"PT{''.join(parts)}" if parts else None


def empty_gap_details_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "region",
            "dataset",
            "expected_step_minutes",
            "gap_run_id",
            "gap_start_utc",
            "gap_end_utc",
            "gap_start_local",
            "gap_end_local",
            "gap_length_points",
            "missing_timestamps_in_gap",
            "missing_values_in_gap",
            "missing_datapoint_sources",
            "is_bounded",
            "previous_known_timestamp_utc",
            "next_known_timestamp_utc",
            "previous_known_price",
            "next_known_price",
            "dst_artifact",
            "dst_note",
            "action",
        ]
    )


def apply_missing_datapoint_fix(
    df: pd.DataFrame,
    *,
    expected_minutes: int,
    dataset: str,
    local_timezone: str,
    max_interpolated_gap_points: int = 2,
) -> MissingDatapointFixResult:
    if expected_minutes <= 0:
        raise ValueError(f"expected_minutes must be positive, received {expected_minutes}")

    if df.empty:
        cleaned = df.copy()
        cleaned["price_eur_per_mwh_original"] = pd.Series(dtype=float)
        cleaned["missing_datapoint_source"] = pd.Series(dtype="object")
        cleaned["gap_run_id"] = pd.Series(dtype="Int64")
        cleaned["gap_fix_action"] = pd.Series(dtype="object")
        cleaned["is_interpolated_value"] = pd.Series(dtype=bool)
        cleaned["is_flagged_missing_value"] = pd.Series(dtype=bool)
        return MissingDatapointFixResult(
            cleaned_frame=cleaned,
            gap_details=empty_gap_details_frame(),
            summary={
                "region": None,
                "dataset": dataset,
                "expected_step_minutes": expected_minutes,
                "rows_before_fix": 0,
                "rows_after_fix": 0,
                "missing_datapoints_before_fix": 0,
                "missing_timestamps_before_fix": 0,
                "missing_values_before_fix": 0,
                "interpolated_points_count": 0,
                "flagged_gap_groups_count": 0,
                "flagged_gap_points_count": 0,
                "flagged_long_gap_groups_count": 0,
                "flagged_long_gap_points_count": 0,
                "flagged_unbounded_gap_groups_count": 0,
                "flagged_unbounded_gap_points_count": 0,
                "flagged_dst_gap_groups_count": 0,
                "remaining_missing_points_after_fix": 0,
            },
        )

    working = df.copy()
    working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True, errors="coerce")
    working["price_eur_per_mwh"] = pd.to_numeric(working["price_eur_per_mwh"], errors="coerce")
    working = working.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").reset_index(drop=True)
    if working["timestamp_utc"].duplicated().any():
        duplicate_count = int(working["timestamp_utc"].duplicated(keep=False).sum())
        raise ValueError(f"Missing-datapoint fix requires unique timestamps; found {duplicate_count} duplicate rows.")

    region_values = working["region"].dropna().astype(str).unique().tolist() if "region" in working.columns else []
    region = region_values[0] if region_values else None

    canonical_index = pd.date_range(
        start=working["timestamp_utc"].min(),
        end=working["timestamp_utc"].max(),
        freq=f"{expected_minutes}min",
        tz="UTC",
    )
    canonical = pd.DataFrame({"timestamp_utc": canonical_index})
    working["_row_present_before_fix"] = True

    merged = canonical.merge(working, on="timestamp_utc", how="left", sort=True)
    if "region" in merged.columns:
        merged["region"] = merged["region"].fillna(region)
    if "resolution_minutes" in merged.columns:
        merged["resolution_minutes"] = pd.to_numeric(merged["resolution_minutes"], errors="coerce")
        merged["resolution_minutes"] = merged["resolution_minutes"].fillna(expected_minutes).round().astype("Int64")
    if "resolution" in merged.columns:
        merged["resolution"] = merged["resolution"].fillna(resolution_to_iso_string(expected_minutes))

    merged["price_eur_per_mwh_original"] = merged["price_eur_per_mwh"]
    merged["gap_run_id"] = pd.Series(pd.NA, index=merged.index, dtype="Int64")
    merged["gap_fix_action"] = "observed"
    merged["is_interpolated_value"] = False
    merged["is_flagged_missing_value"] = False

    row_missing_mask = merged["_row_present_before_fix"].isna()
    value_missing_mask = (~row_missing_mask) & merged["price_eur_per_mwh"].isna()
    missing_mask = merged["price_eur_per_mwh"].isna()

    missing_source = pd.Series("observed", index=merged.index, dtype="object")
    missing_source.loc[row_missing_mask] = "missing_timestamp"
    missing_source.loc[value_missing_mask] = "missing_value"
    merged["missing_datapoint_source"] = missing_source

    interpolated_full = (
        merged.set_index("timestamp_utc")["price_eur_per_mwh"]
        .astype(float)
        .interpolate(method="time", limit_area="inside")
    )

    gap_details_rows: list[dict[str, Any]] = []
    if missing_mask.any():
        missing_group_ids = missing_mask.ne(missing_mask.shift(fill_value=False)).cumsum()
        gap_run_id = 1
        missing_rows = merged.loc[missing_mask].copy()
        missing_rows["_gap_group_id"] = missing_group_ids.loc[missing_mask].to_numpy()
        for _, gap in missing_rows.groupby("_gap_group_id", sort=True):
            start_idx = int(gap.index.min())
            end_idx = int(gap.index.max())
            prev_idx = start_idx - 1
            next_idx = end_idx + 1
            prev_known = prev_idx >= 0 and pd.notna(merged.at[prev_idx, "price_eur_per_mwh"])
            next_known = next_idx < len(merged.index) and pd.notna(merged.at[next_idx, "price_eur_per_mwh"])
            is_bounded = bool(prev_known and next_known)
            gap_length_points = int(gap.shape[0])
            dst_artifact = False
            dst_note = "Source timestamps are stored in UTC, so DST does not create missing UTC datapoints."

            if dst_artifact:
                action = "flag_dst_gap"
            elif not is_bounded:
                action = "flag_unbounded_gap"
            elif gap_length_points > max_interpolated_gap_points:
                action = "flag_long_gap"
            else:
                action = "interpolate"
                gap_timestamps = gap["timestamp_utc"].tolist()
                merged.loc[start_idx:end_idx, "price_eur_per_mwh"] = interpolated_full.loc[gap_timestamps].to_numpy(dtype=float)

            merged.loc[start_idx:end_idx, "gap_run_id"] = gap_run_id
            merged.loc[start_idx:end_idx, "gap_fix_action"] = action
            merged.loc[start_idx:end_idx, "is_interpolated_value"] = action == "interpolate"
            merged.loc[start_idx:end_idx, "is_flagged_missing_value"] = action != "interpolate"

            gap_start_utc = gap["timestamp_utc"].iloc[0]
            gap_end_utc = gap["timestamp_utc"].iloc[-1]
            gap_details_rows.append(
                {
                    "region": region,
                    "dataset": dataset,
                    "expected_step_minutes": expected_minutes,
                    "gap_run_id": gap_run_id,
                    "gap_start_utc": gap_start_utc.isoformat(),
                    "gap_end_utc": gap_end_utc.isoformat(),
                    "gap_start_local": gap_start_utc.tz_convert(local_timezone).isoformat(),
                    "gap_end_local": gap_end_utc.tz_convert(local_timezone).isoformat(),
                    "gap_length_points": gap_length_points,
                    "missing_timestamps_in_gap": int((gap["missing_datapoint_source"] == "missing_timestamp").sum()),
                    "missing_values_in_gap": int((gap["missing_datapoint_source"] == "missing_value").sum()),
                    "missing_datapoint_sources": ",".join(sorted(gap["missing_datapoint_source"].unique().tolist())),
                    "is_bounded": is_bounded,
                    "previous_known_timestamp_utc": (
                        merged.at[prev_idx, "timestamp_utc"].isoformat() if prev_known else None
                    ),
                    "next_known_timestamp_utc": (
                        merged.at[next_idx, "timestamp_utc"].isoformat() if next_known else None
                    ),
                    "previous_known_price": float(merged.at[prev_idx, "price_eur_per_mwh"]) if prev_known else None,
                    "next_known_price": float(merged.at[next_idx, "price_eur_per_mwh"]) if next_known else None,
                    "dst_artifact": dst_artifact,
                    "dst_note": dst_note,
                    "action": action,
                }
            )
            gap_run_id += 1

    gap_details = (
        pd.DataFrame(gap_details_rows).sort_values(["gap_start_utc"]).reset_index(drop=True)
        if gap_details_rows
        else empty_gap_details_frame()
    )

    merged = merged.drop(columns=["_row_present_before_fix"])
    merged = merged.sort_values("timestamp_utc").reset_index(drop=True)

    summary = {
        "region": region,
        "dataset": dataset,
        "expected_step_minutes": expected_minutes,
        "rows_before_fix": int(df.shape[0]),
        "rows_after_fix": int(merged.shape[0]),
        "missing_datapoints_before_fix": int(missing_mask.sum()),
        "missing_timestamps_before_fix": int(row_missing_mask.sum()),
        "missing_values_before_fix": int(value_missing_mask.sum()),
        "interpolated_points_count": int(merged["is_interpolated_value"].sum()),
        "flagged_gap_groups_count": int((gap_details["action"] != "interpolate").sum()) if not gap_details.empty else 0,
        "flagged_gap_points_count": int(
            merged["gap_fix_action"].isin(["flag_long_gap", "flag_unbounded_gap", "flag_dst_gap"]).sum()
        ),
        "flagged_long_gap_groups_count": int((gap_details["action"] == "flag_long_gap").sum()) if not gap_details.empty else 0,
        "flagged_long_gap_points_count": int((merged["gap_fix_action"] == "flag_long_gap").sum()),
        "flagged_unbounded_gap_groups_count": int((gap_details["action"] == "flag_unbounded_gap").sum()) if not gap_details.empty else 0,
        "flagged_unbounded_gap_points_count": int((merged["gap_fix_action"] == "flag_unbounded_gap").sum()),
        "flagged_dst_gap_groups_count": int((gap_details["action"] == "flag_dst_gap").sum()) if not gap_details.empty else 0,
        "remaining_missing_points_after_fix": int(merged["price_eur_per_mwh"].isna().sum()),
    }
    return MissingDatapointFixResult(cleaned_frame=merged, gap_details=gap_details, summary=summary)


def infer_mode_step_minutes(timestamps_utc: pd.Series) -> int | None:
    if timestamps_utc.empty:
        return None
    diffs = timestamps_utc.sort_values().diff().dropna().dt.total_seconds().div(60)
    if diffs.empty:
        return None
    vc = diffs.value_counts()
    return int(vc.index[0]) if not vc.empty else None


def missing_timestamps(df: pd.DataFrame, expected_minutes: int | None) -> int:
    if df.empty or expected_minutes is None:
        return 0
    start = df["timestamp_utc"].min()
    end = df["timestamp_utc"].max()
    if pd.isna(start) or pd.isna(end):
        return 0
    expected = pd.date_range(start=start, end=end, freq=f"{expected_minutes}min", tz="UTC")
    observed = pd.DatetimeIndex(df["timestamp_utc"].dropna().sort_values().unique(), tz="UTC")
    return int(expected.difference(observed).shape[0])


def stats_row(
    region: str,
    dataset: str,
    df: pd.DataFrame,
    duplicate_rows_removed: int = 0,
    sequence_2_rows_removed: int = 0,
    gap_fix_summary: dict[str, Any] | None = None,
    missing_timestamps_count_override: int | None = None,
) -> dict[str, Any]:
    gap_fix_summary = gap_fix_summary or {}
    if df.empty:
        return {
            "record_type": "region",
            "dataset": dataset,
            "region": region,
            "rows": 0,
            "min_timestamp_utc": None,
            "max_timestamp_utc": None,
            "dominant_step_minutes": None,
            "missing_timestamps_count": 0,
            "offgrid_count": 0,
            "duplicate_rows_removed": duplicate_rows_removed,
            "sequence_2_rows_removed": sequence_2_rows_removed,
            "missing_price_points_count": 0,
            "missing_datapoints_before_fix": int(gap_fix_summary.get("missing_datapoints_before_fix", 0)),
            "missing_timestamps_before_fix": int(gap_fix_summary.get("missing_timestamps_before_fix", 0)),
            "missing_values_before_fix": int(gap_fix_summary.get("missing_values_before_fix", 0)),
            "interpolated_points_count": int(gap_fix_summary.get("interpolated_points_count", 0)),
            "flagged_gap_groups_count": int(gap_fix_summary.get("flagged_gap_groups_count", 0)),
            "flagged_gap_points_count": int(gap_fix_summary.get("flagged_gap_points_count", 0)),
            "flagged_long_gap_groups_count": int(gap_fix_summary.get("flagged_long_gap_groups_count", 0)),
            "flagged_long_gap_points_count": int(gap_fix_summary.get("flagged_long_gap_points_count", 0)),
            "flagged_unbounded_gap_groups_count": int(gap_fix_summary.get("flagged_unbounded_gap_groups_count", 0)),
            "flagged_unbounded_gap_points_count": int(gap_fix_summary.get("flagged_unbounded_gap_points_count", 0)),
            "remaining_missing_points_after_fix": int(gap_fix_summary.get("remaining_missing_points_after_fix", 0)),
            "mean_price": None,
            "std_price": None,
            "min_price": None,
            "max_price": None,
            "negative_price_count": 0,
            "resolution_distribution": "{}",
            "union_timestamp_count": None,
            "intersection_timestamp_count": None,
            "missing_vs_union_json": None,
        }

    step = infer_mode_step_minutes(df["timestamp_utc"])
    price = df["price_eur_per_mwh"].dropna()

    offgrid_count = 0
    if dataset == "hourly":
        offgrid_count = int(((df["timestamp_utc"].dt.minute != 0) | (df["timestamp_utc"].dt.second != 0)).sum())
        expected_step = 60
    elif dataset == "quarterly":
        offgrid_count = int((((df["timestamp_utc"].dt.minute % 15) != 0) | (df["timestamp_utc"].dt.second != 0)).sum())
        expected_step = 15
    else:
        expected_step = step

    missing_timestamps_count = (
        int(missing_timestamps_count_override)
        if missing_timestamps_count_override is not None
        else missing_timestamps(df, expected_step)
    )
    return {
        "record_type": "region",
        "dataset": dataset,
        "region": region,
        "rows": int(df.shape[0]),
        "min_timestamp_utc": df["timestamp_utc"].min().isoformat(),
        "max_timestamp_utc": df["timestamp_utc"].max().isoformat(),
        "dominant_step_minutes": step,
        "missing_timestamps_count": missing_timestamps_count,
        "offgrid_count": offgrid_count,
        "duplicate_rows_removed": duplicate_rows_removed,
        "sequence_2_rows_removed": sequence_2_rows_removed,
        "missing_price_points_count": int(df["price_eur_per_mwh"].isna().sum()),
        "missing_datapoints_before_fix": int(gap_fix_summary.get("missing_datapoints_before_fix", 0)),
        "missing_timestamps_before_fix": int(gap_fix_summary.get("missing_timestamps_before_fix", 0)),
        "missing_values_before_fix": int(gap_fix_summary.get("missing_values_before_fix", 0)),
        "interpolated_points_count": int(gap_fix_summary.get("interpolated_points_count", 0)),
        "flagged_gap_groups_count": int(gap_fix_summary.get("flagged_gap_groups_count", 0)),
        "flagged_gap_points_count": int(gap_fix_summary.get("flagged_gap_points_count", 0)),
        "flagged_long_gap_groups_count": int(gap_fix_summary.get("flagged_long_gap_groups_count", 0)),
        "flagged_long_gap_points_count": int(gap_fix_summary.get("flagged_long_gap_points_count", 0)),
        "flagged_unbounded_gap_groups_count": int(gap_fix_summary.get("flagged_unbounded_gap_groups_count", 0)),
        "flagged_unbounded_gap_points_count": int(gap_fix_summary.get("flagged_unbounded_gap_points_count", 0)),
        "remaining_missing_points_after_fix": int(gap_fix_summary.get("remaining_missing_points_after_fix", df["price_eur_per_mwh"].isna().sum())),
        "mean_price": float(price.mean()) if not price.empty else None,
        "std_price": float(price.std(ddof=1)) if price.shape[0] > 1 else None,
        "min_price": float(price.min()) if not price.empty else None,
        "max_price": float(price.max()) if not price.empty else None,
        "negative_price_count": int((price < 0).sum()) if not price.empty else 0,
        "resolution_distribution": json.dumps(
            df["resolution_minutes"].dropna().astype(int).value_counts().sort_index().to_dict()
        ),
        "union_timestamp_count": None,
        "intersection_timestamp_count": None,
        "missing_vs_union_json": None,
    }


def cross_region_row(dataset: str, region_frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    sets: dict[str, pd.DatetimeIndex] = {}
    for region, df in region_frames.items():
        sets[region] = pd.DatetimeIndex(df["timestamp_utc"].dropna().sort_values().unique(), tz="UTC")

    union = pd.DatetimeIndex([], tz="UTC")
    intersection: pd.DatetimeIndex | None = None
    for region in sorted(sets.keys()):
        union = union.union(sets[region])
        intersection = sets[region] if intersection is None else intersection.intersection(sets[region])

    intersection_count = int(intersection.shape[0]) if intersection is not None else 0
    missing_vs_union = {region: int(union.shape[0] - sets[region].shape[0]) for region in sorted(sets.keys())}

    return {
        "record_type": "cross_region",
        "dataset": dataset,
        "region": "ALL",
        "rows": None,
        "min_timestamp_utc": intersection.min().isoformat() if intersection is not None and not intersection.empty else None,
        "max_timestamp_utc": intersection.max().isoformat() if intersection is not None and not intersection.empty else None,
        "dominant_step_minutes": None,
        "missing_timestamps_count": None,
        "offgrid_count": None,
        "duplicate_rows_removed": None,
        "sequence_2_rows_removed": None,
        "missing_price_points_count": None,
        "missing_datapoints_before_fix": None,
        "missing_timestamps_before_fix": None,
        "missing_values_before_fix": None,
        "interpolated_points_count": None,
        "flagged_gap_groups_count": None,
        "flagged_gap_points_count": None,
        "flagged_long_gap_groups_count": None,
        "flagged_long_gap_points_count": None,
        "flagged_unbounded_gap_groups_count": None,
        "flagged_unbounded_gap_points_count": None,
        "remaining_missing_points_after_fix": None,
        "mean_price": None,
        "std_price": None,
        "min_price": None,
        "max_price": None,
        "negative_price_count": None,
        "resolution_distribution": None,
        "union_timestamp_count": int(union.shape[0]),
        "intersection_timestamp_count": intersection_count,
        "missing_vs_union_json": json.dumps(missing_vs_union, sort_keys=True),
    }


def save_granularity_files(
    output_root: Path,
    hourly_frames: dict[str, pd.DataFrame],
    quarterly_frames: dict[str, pd.DataFrame],
    all_frames: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    da_root = output_root / "DA_prices"
    hourly_dir = da_root / "hourly"
    quarterly_dir = da_root / "quarterly"
    aggregated_dir = da_root / "aggregated"
    for directory in [hourly_dir, quarterly_dir, aggregated_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    for region, df in hourly_frames.items():
        df.to_csv(hourly_dir / f"da_prices_{region}_hourly.csv", index=False)
    for region, df in quarterly_frames.items():
        df.to_csv(quarterly_dir / f"da_prices_{region}_quarterly.csv", index=False)
    for region, df in all_frames.items():
        df.to_csv(aggregated_dir / f"da_prices_{region}_all.csv", index=False)

    all_hourly = pd.concat(hourly_frames.values(), ignore_index=True) if hourly_frames else pd.DataFrame()
    all_quarterly = pd.concat(quarterly_frames.values(), ignore_index=True) if quarterly_frames else pd.DataFrame()
    all_all = pd.concat(all_frames.values(), ignore_index=True) if all_frames else pd.DataFrame()

    if not all_hourly.empty:
        all_hourly = all_hourly.sort_values(["timestamp_utc", "region"]).reset_index(drop=True)
    if not all_quarterly.empty:
        all_quarterly = all_quarterly.sort_values(["timestamp_utc", "region"]).reset_index(drop=True)
    if not all_all.empty:
        all_all = all_all.sort_values(["timestamp_utc", "region"]).reset_index(drop=True)

    all_hourly.to_csv(hourly_dir / "da_prices_all_regions_hourly.csv", index=False)
    all_quarterly.to_csv(quarterly_dir / "da_prices_all_regions_quarterly.csv", index=False)
    all_all.to_csv(aggregated_dir / "da_prices_all_regions_all.csv", index=False)
    return all_all, all_hourly, all_quarterly


def plot_overall_granularity(all_df: pd.DataFrame, granularity: str, out_path: Path) -> None:
    if all_df.empty:
        return
    plt.figure(figsize=(14, 5))
    for region in sorted(all_df["region"].unique()):
        series = (
            all_df[all_df["region"] == region]
            .set_index("timestamp_utc")["price_eur_per_mwh"]
            .sort_index()
            .resample("D")
            .mean()
        )
        plt.plot(series.index, series.values, linewidth=1.1, label=region)
    plt.title(f"Day-Ahead Prices - {granularity.capitalize()} (Daily Mean)")
    plt.xlabel("Date")
    plt.ylabel("EUR/MWh")
    plt.grid(alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def plot_yearly(all_df: pd.DataFrame, granularity: str, yearly_dir: Path) -> None:
    if all_df.empty:
        return
    yearly_dir.mkdir(parents=True, exist_ok=True)
    years = sorted(all_df["timestamp_utc"].dt.year.unique().tolist())
    for year in years:
        subset = all_df[all_df["timestamp_utc"].dt.year == year]
        if subset.empty:
            continue
        plt.figure(figsize=(14, 5))
        for region in sorted(subset["region"].unique()):
            region_df = subset[subset["region"] == region].sort_values("timestamp_utc")
            plt.plot(region_df["timestamp_utc"], region_df["price_eur_per_mwh"], linewidth=0.8, label=region)
        plt.title(f"Day-Ahead Prices {year} - {granularity.capitalize()}")
        plt.xlabel("Timestamp UTC")
        plt.ylabel("EUR/MWh")
        plt.grid(alpha=0.2)
        plt.legend()
        plt.tight_layout()
        plt.savefig(yearly_dir / f"da_prices_{granularity}_{year}.png", dpi=150)
        plt.close()


def weekly_region_metrics(all_df: pd.DataFrame) -> pd.DataFrame:
    work = all_df[["timestamp_utc", "region", "price_eur_per_mwh", "granularity"]].copy()
    ts_naive = work["timestamp_utc"].dt.tz_convert("UTC").dt.tz_localize(None)
    week_start_naive = ts_naive.dt.floor("D") - pd.to_timedelta(ts_naive.dt.weekday, unit="D")
    work["week_start_utc"] = week_start_naive.dt.tz_localize("UTC")
    work["year"] = work["week_start_utc"].dt.year

    weekly = (
        work.groupby(["granularity", "year", "week_start_utc", "region"], dropna=False)["price_eur_per_mwh"]
        .agg(mean_price="mean", std_price="std", min_price="min", max_price="max", observations="count")
        .reset_index()
    )
    weekly["std_price"] = weekly["std_price"].fillna(0.0)
    return weekly


def plot_nl_focus_week(
    subset: pd.DataFrame,
    granularity: str,
    year: int,
    metric: str,
    week_start: pd.Timestamp,
    output_path: Path,
) -> None:
    plt.figure(figsize=(14, 5))
    region_order = ["BE", "DE", "NL"]
    for region in region_order:
        region_df = subset[subset["region"] == region].sort_values("timestamp_utc")
        if region_df.empty:
            continue
        if region == "NL":
            plt.plot(
                region_df["timestamp_utc"],
                region_df["price_eur_per_mwh"],
                linewidth=2.0,
                alpha=1.0,
                label="NL",
                color="tab:orange",
            )
        else:
            plt.plot(
                region_df["timestamp_utc"],
                region_df["price_eur_per_mwh"],
                linewidth=1.0,
                alpha=0.35,
                label=region,
                color="tab:blue" if region == "BE" else "tab:green",
            )
    week_end = week_start + pd.Timedelta(days=7)
    plt.title(f"{granularity.capitalize()} {year} - NL {metric.capitalize()} Week ({week_start.date()} to {week_end.date()})")
    plt.xlabel("Timestamp UTC")
    plt.ylabel("EUR/MWh")
    plt.grid(alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def choose_nl_outlier_weeks(all_df: pd.DataFrame, granularity: str, output_dir: Path) -> pd.DataFrame:
    if all_df.empty:
        return pd.DataFrame()

    work = all_df[["timestamp_utc", "region", "price_eur_per_mwh"]].copy()
    work["granularity"] = granularity
    weekly = weekly_region_metrics(work)

    nl_weekly = weekly[weekly["region"] == "NL"].copy()
    if nl_weekly.empty:
        return pd.DataFrame()

    expected_points = 24 * 7 if granularity == "hourly" else 24 * 4 * 7
    min_points = max(1, int(expected_points * 0.2))
    nl_weekly = nl_weekly[nl_weekly["observations"] >= min_points].copy()
    if nl_weekly.empty:
        return pd.DataFrame()

    out_dir = output_dir / "outlier_weeks" / granularity
    out_dir.mkdir(parents=True, exist_ok=True)

    comparison_rows: list[dict[str, Any]] = []
    for year in sorted(nl_weekly["year"].unique().tolist()):
        year_nl = nl_weekly[nl_weekly["year"] == year].copy()
        if year_nl.empty:
            continue

        selected = {
            "volatile": year_nl.sort_values("std_price", ascending=False).iloc[0],
            "high": year_nl.sort_values("mean_price", ascending=False).iloc[0],
            "low": year_nl.sort_values("mean_price", ascending=True).iloc[0],
        }

        for metric, row in selected.items():
            week_start = row["week_start_utc"]
            week_end = week_start + pd.Timedelta(days=7)
            subset = all_df[(all_df["timestamp_utc"] >= week_start) & (all_df["timestamp_utc"] < week_end)].copy()
            if subset.empty:
                continue

            plot_nl_focus_week(
                subset=subset,
                granularity=granularity,
                year=int(year),
                metric=metric,
                week_start=week_start,
                output_path=out_dir / f"nl_focus_{year}_{metric}.png",
            )

            weekly_slice = weekly[(weekly["year"] == year) & (weekly["week_start_utc"] == week_start)].copy()
            row_out: dict[str, Any] = {
                "granularity": granularity,
                "year": int(year),
                "metric": metric,
                "week_start_utc": week_start.isoformat(),
                "week_end_utc": week_end.isoformat(),
            }
            for region in ["NL", "BE", "DE"]:
                region_row = weekly_slice[weekly_slice["region"] == region]
                if region_row.empty:
                    row_out[f"{region}_mean_price"] = None
                    row_out[f"{region}_std_price"] = None
                    row_out[f"{region}_min_price"] = None
                    row_out[f"{region}_max_price"] = None
                    row_out[f"{region}_observations"] = 0
                else:
                    r = region_row.iloc[0]
                    row_out[f"{region}_mean_price"] = float(r["mean_price"])
                    row_out[f"{region}_std_price"] = float(r["std_price"])
                    row_out[f"{region}_min_price"] = float(r["min_price"])
                    row_out[f"{region}_max_price"] = float(r["max_price"])
                    row_out[f"{region}_observations"] = int(r["observations"])
            comparison_rows.append(row_out)

    return pd.DataFrame(comparison_rows)


def run(
    raw_root: Path,
    output_root: Path,
    cutoff_local_date: str,
    local_timezone: str,
    regions: list[str],
    quarterly_regions: set[str],
    max_timestamp_utc_str: str,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    diagnostics_dir = output_root / "diagnostics"
    plots_dir = output_root / "plots"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    cutoff_local = pd.Timestamp(cutoff_local_date).tz_localize(local_timezone)
    cutoff_utc = cutoff_local.tz_convert("UTC")
    max_timestamp_utc = pd.to_datetime(max_timestamp_utc_str, utc=True, errors="raise")

    region_dirs = find_region_directories(raw_root, regions)
    if not region_dirs:
        raise FileNotFoundError(f"No DA_prices_<REGION> directories found in: {raw_root}")

    parse_summary = ParseSummary()
    region_all: dict[str, pd.DataFrame] = {}
    region_hourly: dict[str, pd.DataFrame] = {}
    region_quarterly: dict[str, pd.DataFrame] = {}
    diagnostics_rows: list[dict[str, Any]] = []
    gap_fix_summaries: list[dict[str, Any]] = []
    gap_fix_details_frames: list[pd.DataFrame] = []

    for region, region_dir in region_dirs.items():
        xml_files = sorted(region_dir.rglob("*.xml"))
        rows: list[dict[str, Any]] = []
        for xml_file in xml_files:
            try:
                file_rows, file_summary = parse_single_xml(region, xml_file)
            except Exception as exc:  # noqa: BLE001
                parse_summary.parse_errors.append({"region": region, "source_path": str(xml_file), "error": str(exc)})
                continue
            rows.extend(file_rows)
            parse_summary.file_summaries.append(file_summary)

        df_raw = make_region_dataframe(rows)

        sequence_2_rows_removed = 0
        if region == "DE" and not df_raw.empty:
            mask_seq2 = df_raw["timeseries_sequence_position"] == 2
            sequence_2_rows_removed = int(mask_seq2.sum())
            if sequence_2_rows_removed > 0:
                df_raw = df_raw[~mask_seq2].copy()

        df_clean_all, duplicate_rows_removed = split_duplicate_stats(df_raw)
        df_clean_all = clip_to_max_timestamp(df_clean_all, max_timestamp_utc=max_timestamp_utc)

        uses_quarterly_cutoff = region in quarterly_regions
        if uses_quarterly_cutoff:
            pre = df_clean_all[df_clean_all["timestamp_utc"] < cutoff_utc].copy()
            post = df_clean_all[df_clean_all["timestamp_utc"] >= cutoff_utc].copy()
            hourly_raw = pre[pre["resolution_minutes"] == 60].copy()
            quarterly_raw = post[post["resolution_minutes"] == 15].copy()
        else:
            hourly_raw = df_clean_all[df_clean_all["resolution_minutes"] == 60].copy()
            quarterly_raw = df_clean_all.iloc[0:0].copy()

        hourly_fix = apply_missing_datapoint_fix(
            hourly_raw,
            expected_minutes=60,
            dataset="hourly",
            local_timezone=local_timezone,
        )
        quarterly_fix = apply_missing_datapoint_fix(
            quarterly_raw,
            expected_minutes=15,
            dataset="quarterly",
            local_timezone=local_timezone,
        )
        hourly = hourly_fix.cleaned_frame
        quarterly = quarterly_fix.cleaned_frame

        other_rows = df_clean_all.copy()
        if uses_quarterly_cutoff:
            hourly_scope_mask = (other_rows["timestamp_utc"] < cutoff_utc) & (other_rows["resolution_minutes"] == 60)
            quarterly_scope_mask = (other_rows["timestamp_utc"] >= cutoff_utc) & (other_rows["resolution_minutes"] == 15)
        else:
            hourly_scope_mask = other_rows["resolution_minutes"] == 60
            quarterly_scope_mask = pd.Series(False, index=other_rows.index)
        other_rows = other_rows[~hourly_scope_mask & ~quarterly_scope_mask].copy()
        frames_to_concat = [frame for frame in [other_rows, hourly, quarterly] if not frame.empty]
        if frames_to_concat:
            df_clean_all_final = pd.concat(frames_to_concat, ignore_index=True).sort_values("timestamp_utc").reset_index(drop=True)
        else:
            df_clean_all_final = pd.DataFrame(columns=df_clean_all.columns)

        region_all[region] = df_clean_all_final
        region_hourly[region] = hourly
        region_quarterly[region] = quarterly
        gap_fix_summaries.extend([hourly_fix.summary, quarterly_fix.summary])
        if not hourly_fix.gap_details.empty:
            gap_fix_details_frames.append(hourly_fix.gap_details)
        if not quarterly_fix.gap_details.empty:
            gap_fix_details_frames.append(quarterly_fix.gap_details)

        diagnostics_rows.append(
            stats_row(
                region=region,
                dataset="aggregated",
                df=df_clean_all_final,
                duplicate_rows_removed=duplicate_rows_removed,
                sequence_2_rows_removed=sequence_2_rows_removed,
            )
        )
        diagnostics_rows.append(
            stats_row(
                region=region,
                dataset="hourly",
                df=hourly,
                gap_fix_summary=hourly_fix.summary,
                missing_timestamps_count_override=hourly_fix.summary["missing_timestamps_before_fix"],
            )
        )
        diagnostics_rows.append(
            stats_row(
                region=region,
                dataset="quarterly",
                df=quarterly,
                gap_fix_summary=quarterly_fix.summary,
                missing_timestamps_count_override=quarterly_fix.summary["missing_timestamps_before_fix"],
            )
        )

    all_all, all_hourly, all_quarterly = save_granularity_files(output_root, region_hourly, region_quarterly, region_all)

    diagnostics_rows.append(cross_region_row("aggregated", region_all))
    diagnostics_rows.append(cross_region_row("hourly", region_hourly))
    diagnostics_rows.append(cross_region_row("quarterly", region_quarterly))

    diagnostics_df = pd.DataFrame(diagnostics_rows).sort_values(["record_type", "dataset", "region"])
    diagnostics_df.to_csv(output_root / "diagnostics_comparison.csv", index=False)
    diagnostics_df.to_csv(diagnostics_dir / "diagnostics_comparison.csv", index=False)

    pd.DataFrame(parse_summary.file_summaries).to_csv(diagnostics_dir / "xml_file_summary.csv", index=False)
    pd.DataFrame(parse_summary.parse_errors).to_csv(diagnostics_dir / "xml_parse_errors.csv", index=False)
    pd.DataFrame(gap_fix_summaries).to_csv(diagnostics_dir / "gap_fix_summary.csv", index=False)
    gap_fix_details = (
        pd.concat(gap_fix_details_frames, ignore_index=True).sort_values(["region", "dataset", "gap_start_utc"]).reset_index(drop=True)
        if gap_fix_details_frames
        else empty_gap_details_frame()
    )
    gap_fix_details.to_csv(diagnostics_dir / "gap_fix_details.csv", index=False)

    plot_overall_granularity(all_hourly, "hourly", plots_dir / "overall_hourly_all_regions.png")
    plot_overall_granularity(all_quarterly, "quarterly", plots_dir / "overall_quarterly_all_regions.png")

    plot_yearly(all_hourly, "hourly", plots_dir / "yearly" / "hourly")
    plot_yearly(all_quarterly, "quarterly", plots_dir / "yearly" / "quarterly")

    nl_outliers_hourly = choose_nl_outlier_weeks(all_hourly, "hourly", plots_dir)
    nl_outliers_quarterly = choose_nl_outlier_weeks(all_quarterly, "quarterly", plots_dir)
    nl_outliers = (
        pd.concat([nl_outliers_hourly, nl_outliers_quarterly], ignore_index=True)
        if (not nl_outliers_hourly.empty or not nl_outliers_quarterly.empty)
        else pd.DataFrame()
    )
    nl_outliers.to_csv(diagnostics_dir / "nl_outlier_weeks_comparison.csv", index=False)

    run_meta = {
        "raw_root": str(raw_root.resolve()),
        "output_root": str(output_root.resolve()),
        "cutoff_local": cutoff_local.isoformat(),
        "cutoff_utc": cutoff_utc.isoformat(),
        "max_timestamp_utc": max_timestamp_utc.isoformat(),
        "regions": sorted(region_dirs.keys()),
        "missing_datapoint_fix": {
            "interpolate_consecutive_points_up_to": 2,
            "dst_policy": "Source timestamps are UTC, so DST does not create missing UTC datapoints.",
            "long_gap_policy": "Flag and keep missing when more than two consecutive datapoints are missing.",
        },
    }
    (diagnostics_dir / "run_metadata.json").write_text(json.dumps(run_meta, indent=2), encoding="utf-8")


if __name__ == "__main__":
    args = parse_args()
    run(
        raw_root=args.raw_root,
        output_root=args.output_root,
        cutoff_local_date=args.cutoff_local_date,
        local_timezone=args.local_timezone,
        regions=args.regions,
        quarterly_regions={region.upper() for region in args.quarterly_regions},
        max_timestamp_utc_str=args.max_timestamp_utc,
    )
