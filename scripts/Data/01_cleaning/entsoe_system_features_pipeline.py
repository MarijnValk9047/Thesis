from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


MARKET_TIMEZONES = {
    "BE": "Europe/Brussels",
    "DE": "Europe/Berlin",
    "NL": "Europe/Amsterdam",
}

PSR_TYPE_LABELS = {
    "B01": "Biomass",
    "B02": "Fossil_Brown_coal_Lignite",
    "B03": "Fossil_Coal_derived_gas",
    "B04": "Fossil_Gas",
    "B05": "Fossil_Hard_coal",
    "B06": "Fossil_Oil",
    "B07": "Fossil_Oil_shale",
    "B08": "Fossil_Peat",
    "B09": "Geothermal",
    "B10": "Hydro_Pumped_Storage",
    "B11": "Hydro_Run_of_river_and_poundage",
    "B12": "Hydro_Water_Reservoir",
    "B13": "Marine",
    "B14": "Nuclear",
    "B15": "Other_renewable",
    "B16": "Solar",
    "B17": "Waste",
    "B18": "Wind_Offshore",
    "B19": "Wind_Onshore",
    "B20": "Other",
    "B25": "Energy_storage",
}

PT_RESOLUTION_PATTERN = re.compile(r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?$")
PERIOD_RESOLUTION_PATTERN = re.compile(r"^P(?:(?P<years>\d+)Y)?(?:(?P<days>\d+)D)?$")
FILENAME_PSR_PATTERN = re.compile(r"_(B\d{2})_")


@dataclass(frozen=True)
class FamilyConfig:
    name: str
    raw_subdir_template: str
    output_subdir: str
    known_at_rule: str
    has_psr_dimension: bool
    availability_category: str
    future_horizon_safe: bool
    notes: str


FAMILY_CONFIGS: tuple[FamilyConfig, ...] = (
    FamilyConfig(
        name="actual_total_load",
        raw_subdir_template="Load/Load_{market}/6_1_A_Actual_Total_Load",
        output_subdir="Load/actual_total_load",
        known_at_rule="actual_interval_end",
        has_psr_dimension=False,
        availability_category="historical_only",
        future_horizon_safe=False,
        notes="Actual load is only known after delivery and can only be used as historical information or lagged errors.",
    ),
    FamilyConfig(
        name="da_total_load_forecast",
        raw_subdir_template="Load/Load_{market}/6_1_B_DA_Total_Load_Forecast",
        output_subdir="Load/da_total_load_forecast",
        known_at_rule="day_ahead_local_08",
        has_psr_dimension=False,
        availability_category="previous_delivery_day_known_under_current_method",
        future_horizon_safe=False,
        notes=(
            "Under the current thesis simplification, the full day-ahead curve for local delivery day t is treated as "
            "known at t 08:00 local. That makes this family safe for historical use but not as a direct full-horizon "
            "future regressor for D..D+4."
        ),
    ),
    FamilyConfig(
        name="week_ahead_total_load_forecast",
        raw_subdir_template="Load/Load_{market}/6_1_C_Week_Ahead_Total_Load_Forecast",
        output_subdir="Load/week_ahead_total_load_forecast",
        known_at_rule="week_ahead_local_08",
        has_psr_dimension=False,
        availability_category="future_horizon_known",
        future_horizon_safe=True,
        notes=(
            "Week-ahead load forecast is treated as known one week before the delivery day at 08:00 local, which "
            "makes it directly usable over the D..D+4 horizon under the current setup."
        ),
    ),
    FamilyConfig(
        name="da_generation_forecast",
        raw_subdir_template="RES_Generation_Forecast/{market}/14_1_C_DA_Generation_Forecast",
        output_subdir="Generation/da_generation_forecast",
        known_at_rule="day_ahead_local_08",
        has_psr_dimension=False,
        availability_category="previous_delivery_day_known_under_current_method",
        future_horizon_safe=False,
        notes=(
            "The remaining raw day-ahead generation forecast files contain total generation forecast rather than "
            "type-specific future curves. Under the current availability simplification they are safe as historical "
            "information, not as direct D..D+4 future regressors."
        ),
    ),
    FamilyConfig(
        name="actual_generation_by_psr",
        raw_subdir_template="RES_Generation_Forecast/{market}/16_1_BC_Actual_Generation_All_Production_Types_A75",
        output_subdir="Generation/actual_generation_by_psr",
        known_at_rule="actual_interval_end",
        has_psr_dimension=True,
        availability_category="historical_only",
        future_horizon_safe=False,
        notes="Actual generation by production type is historical-only and should enter forecasting only via lagged summaries.",
    ),
    FamilyConfig(
        name="installed_capacity_by_psr",
        raw_subdir_template="RES_Generation_Forecast/{market}/14_1_A_Installed_Capacity_per_Production_Type",
        output_subdir="Generation/installed_capacity_by_psr",
        known_at_rule="valid_from_utc",
        has_psr_dimension=True,
        availability_category="future_horizon_known",
        future_horizon_safe=True,
        notes="Installed capacity changes slowly and is treated as known from the start of its validity interval.",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse and clean ENTSO-E load, generation, and installed-capacity XML families into forecasting-ready tables."
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/00_Raw"),
        help="Root folder that contains the Load and RES_Generation_Forecast raw subfolders.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/01_cleaned"),
        help="Root folder for cleaned outputs.",
    )
    parser.add_argument(
        "--markets",
        nargs="+",
        default=["BE", "DE", "NL"],
        help="Markets to process.",
    )
    parser.add_argument(
        "--families",
        nargs="+",
        default=None,
        help="Optional subset of family names to process.",
    )
    return parser.parse_args()


def local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def infer_namespace(root: ET.Element) -> dict[str, str]:
    namespace = root.tag.split("}", 1)[0].strip("{")
    return {"ns": namespace}


def parse_ts(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    return timestamp if pd.notna(timestamp) else None


def find_text(element: ET.Element, path: str, namespace: dict[str, str]) -> str | None:
    found = element.find(path, namespace)
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text if text else None


def parse_resolution(value: str | None) -> tuple[str | None, int | None, pd.Timedelta | None]:
    if not value:
        return None, None, None

    pt_match = PT_RESOLUTION_PATTERN.match(value)
    if pt_match:
        hours = int(pt_match.group("hours") or 0)
        minutes = int(pt_match.group("minutes") or 0)
        total_minutes = hours * 60 + minutes
        if total_minutes <= 0:
            return value, None, None
        return value, total_minutes, pd.Timedelta(minutes=total_minutes)

    period_match = PERIOD_RESOLUTION_PATTERN.match(value)
    if period_match:
        years = int(period_match.group("years") or 0)
        days = int(period_match.group("days") or 0)
        if years <= 0:
            if days <= 0:
                return value, None, None
            total_minutes = days * 24 * 60
            return value, total_minutes, pd.Timedelta(days=days)
        return value, None, None

    return value, None, None


def psr_label(psr_type: str | None) -> str | None:
    if psr_type is None:
        return None
    return PSR_TYPE_LABELS.get(psr_type, psr_type)


def filename_psr_type(path: Path) -> str | None:
    match = FILENAME_PSR_PATTERN.search(path.name)
    return match.group(1) if match else None


def delivery_local_date(timestamp_utc: pd.Timestamp, market: str) -> date:
    return timestamp_utc.tz_convert(MARKET_TIMEZONES[market]).date()


def localize_delivery_datetime(local_value: date, market: str, day_offset: int = 0, hour: int = 8, minute: int = 0) -> pd.Timestamp:
    adjusted = local_value + timedelta(days=day_offset)
    naive_value = datetime.combine(adjusted, time(hour=hour, minute=minute))
    return pd.Timestamp(naive_value).tz_localize(MARKET_TIMEZONES[market], ambiguous="raise", nonexistent="raise")


def known_at_for_rule(
    rule: str,
    market: str,
    timestamp_utc: pd.Timestamp,
    interval_end_utc: pd.Timestamp | None,
) -> pd.Timestamp:
    if rule == "actual_interval_end":
        return interval_end_utc if interval_end_utc is not None else timestamp_utc

    if rule == "day_ahead_local_08":
        local_day = delivery_local_date(timestamp_utc, market)
        return localize_delivery_datetime(local_day, market, day_offset=0, hour=8, minute=0).tz_convert("UTC")

    if rule == "week_ahead_local_08":
        local_day = delivery_local_date(timestamp_utc, market)
        return localize_delivery_datetime(local_day, market, day_offset=-7, hour=8, minute=0).tz_convert("UTC")

    if rule == "valid_from_utc":
        return timestamp_utc

    raise ValueError(f"Unsupported known_at_rule: {rule}")


def sanitize_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()


def parse_family_file(market: str, xml_path: Path, family: FamilyConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    namespace = infer_namespace(root)

    created_datetime_utc = parse_ts(find_text(root, "ns:createdDateTime", namespace))
    document_type = find_text(root, "ns:type", namespace)
    process_type = find_text(root, "ns:process.processType", namespace)
    document_period_start_utc = parse_ts(find_text(root, "ns:time_Period.timeInterval/ns:start", namespace))
    document_period_end_utc = parse_ts(find_text(root, "ns:time_Period.timeInterval/ns:end", namespace))

    rows: list[dict[str, Any]] = []
    resolution_counts: dict[str, int] = {}
    time_series_count = 0
    point_count = 0

    for timeseries_index, time_series in enumerate(root.findall("ns:TimeSeries", namespace), start=1):
        time_series_count += 1
        business_type = find_text(time_series, "ns:businessType", namespace)
        object_aggregation = find_text(time_series, "ns:objectAggregation", namespace)
        in_domain = (
            find_text(time_series, "ns:inBiddingZone_Domain.mRID", namespace)
            or find_text(time_series, "ns:in_Domain.mRID", namespace)
        )
        out_domain = (
            find_text(time_series, "ns:outBiddingZone_Domain.mRID", namespace)
            or find_text(time_series, "ns:out_Domain.mRID", namespace)
        )
        unit_name = find_text(time_series, "ns:quantity_Measure_Unit.name", namespace)
        curve_type = find_text(time_series, "ns:curveType", namespace)
        current_psr_type = find_text(time_series, "ns:MktPSRType/ns:psrType", namespace) or filename_psr_type(xml_path)

        for period_index, period in enumerate(time_series.findall("ns:Period", namespace), start=1):
            resolution = find_text(period, "ns:resolution", namespace)
            resolution_counts[resolution or "missing"] = resolution_counts.get(resolution or "missing", 0) + 1
            _, resolution_minutes, resolution_delta = parse_resolution(resolution)

            period_start_utc = parse_ts(find_text(period, "ns:timeInterval/ns:start", namespace))
            period_end_utc = parse_ts(find_text(period, "ns:timeInterval/ns:end", namespace))

            for point in period.findall("ns:Point", namespace):
                point_count += 1
                position_text = find_text(point, "ns:position", namespace)
                quantity_text = find_text(point, "ns:quantity", namespace)

                try:
                    position = int(position_text) if position_text is not None else None
                except ValueError:
                    position = None

                quantity = pd.to_numeric(quantity_text, errors="coerce")
                quantity_value = float(quantity) if pd.notna(quantity) else None

                timestamp_utc: pd.Timestamp | None = None
                interval_end_utc: pd.Timestamp | None = None
                if period_start_utc is not None and position is not None:
                    if resolution_delta is not None:
                        timestamp_utc = period_start_utc + (position - 1) * resolution_delta
                        interval_end_utc = timestamp_utc + resolution_delta
                    elif resolution == "P1Y" and period_end_utc is not None:
                        timestamp_utc = period_start_utc
                        interval_end_utc = period_end_utc

                rows.append(
                    {
                        "family": family.name,
                        "market": market,
                        "timestamp_utc": timestamp_utc,
                        "interval_end_utc": interval_end_utc,
                        "value_mw": quantity_value,
                        "resolution": resolution,
                        "resolution_minutes": resolution_minutes,
                        "document_type": document_type,
                        "process_type": process_type,
                        "business_type": business_type,
                        "object_aggregation": object_aggregation,
                        "unit_name": unit_name,
                        "curve_type": curve_type,
                        "psr_type": current_psr_type,
                        "psr_label": psr_label(current_psr_type),
                        "in_domain": in_domain,
                        "out_domain": out_domain,
                        "created_datetime_utc": created_datetime_utc,
                        "document_period_start_utc": document_period_start_utc,
                        "document_period_end_utc": document_period_end_utc,
                        "source_file": xml_path.name,
                        "source_path": str(xml_path),
                        "timeseries_index": timeseries_index,
                        "period_index": period_index,
                        "position": position,
                    }
                )

    file_summary = {
        "family": family.name,
        "market": market,
        "source_file": xml_path.name,
        "source_path": str(xml_path),
        "document_type": document_type,
        "process_type": process_type,
        "created_datetime_utc": created_datetime_utc.isoformat() if created_datetime_utc is not None else None,
        "document_period_start_utc": document_period_start_utc.isoformat() if document_period_start_utc is not None else None,
        "document_period_end_utc": document_period_end_utc.isoformat() if document_period_end_utc is not None else None,
        "time_series_count": time_series_count,
        "point_count": point_count,
        "rows_generated": len(rows),
        "resolution_distribution": json.dumps(dict(sorted(resolution_counts.items())), sort_keys=True),
    }
    return rows, file_summary


def make_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    for column in [
        "timestamp_utc",
        "interval_end_utc",
        "created_datetime_utc",
        "document_period_start_utc",
        "document_period_end_utc",
    ]:
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")

    numeric_int_columns = ["resolution_minutes", "timeseries_index", "period_index", "position"]
    for column in numeric_int_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    frame["value_mw"] = pd.to_numeric(frame["value_mw"], errors="coerce")
    return frame


def deduplicate_rows(frame: pd.DataFrame, family: FamilyConfig) -> tuple[pd.DataFrame, int]:
    if frame.empty:
        return frame.copy(), 0

    key_columns = ["market", "timestamp_utc"]
    if family.has_psr_dimension:
        key_columns.append("psr_type")
    frame = frame.copy()
    frame["psr_type"] = frame["psr_type"].fillna("TOTAL")
    frame["psr_label"] = frame["psr_label"].fillna("Total")
    ordered = frame.sort_values(
        key_columns + ["created_datetime_utc", "source_file", "timeseries_index", "period_index", "position"],
        na_position="first",
    )
    duplicate_rows = int(ordered.duplicated(subset=key_columns, keep="last").sum())
    deduped = ordered.drop_duplicates(subset=key_columns, keep="last").sort_values(key_columns).reset_index(drop=True)
    return deduped, duplicate_rows


def add_time_columns(frame: pd.DataFrame, family: FamilyConfig) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    enriched = frame.copy()
    local_dates: list[date] = []
    local_hours: list[int] = []
    known_at_values: list[pd.Timestamp] = []
    for row in enriched.itertuples(index=False):
        timestamp_utc = pd.Timestamp(row.timestamp_utc)
        market = str(row.market)
        local_timestamp = timestamp_utc.tz_convert(MARKET_TIMEZONES[market])
        local_dates.append(local_timestamp.date())
        local_hours.append(int(local_timestamp.hour))
        interval_end_utc = pd.Timestamp(row.interval_end_utc) if pd.notna(row.interval_end_utc) else None
        known_at_values.append(known_at_for_rule(family.known_at_rule, market, timestamp_utc, interval_end_utc))

    enriched["target_delivery_local_date"] = local_dates
    enriched["target_hour_local"] = local_hours
    enriched["known_at_utc"] = known_at_values
    enriched["known_at_rule"] = family.known_at_rule
    return enriched


def aggregate_to_hourly(frame: pd.DataFrame, family: FamilyConfig) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    if frame["resolution"].eq("P1Y").all():
        return expand_yearly_capacity_to_hourly(frame, family)

    work = frame.copy()
    work = work[work["timestamp_utc"].notna()].copy()

    expanded_parts: list[pd.DataFrame] = []
    long_interval_mask = work["resolution_minutes"].fillna(0).gt(60)
    if long_interval_mask.any():
        for row in work[long_interval_mask].itertuples(index=False):
            start_utc = pd.Timestamp(row.timestamp_utc)
            end_utc = pd.Timestamp(row.interval_end_utc)
            if pd.isna(start_utc) or pd.isna(end_utc) or end_utc <= start_utc:
                continue
            hourly_index = pd.date_range(start=start_utc, end=end_utc - pd.Timedelta(hours=1), freq="h", tz="UTC")
            if hourly_index.empty:
                continue
            base_payload = {
                "family": family.name,
                "market": row.market,
                "timestamp_utc": hourly_index,
                "interval_end_utc": hourly_index + pd.Timedelta(hours=1),
                "value_mw": float(row.value_mw) if pd.notna(row.value_mw) else pd.NA,
                "source_observations": 1,
                "coverage_minutes": 60,
                "expected_coverage_minutes": 60,
                "is_complete_hour": True,
                "source_file_count": 1,
            }
            if family.has_psr_dimension:
                base_payload["psr_type"] = row.psr_type
                base_payload["psr_label"] = row.psr_label
            expanded_parts.append(pd.DataFrame(base_payload))

    short_interval_rows = work[~long_interval_mask].copy()
    if not short_interval_rows.empty:
        short_interval_rows["hour_timestamp_utc"] = short_interval_rows["timestamp_utc"].dt.floor("h")
        short_interval_rows["interval_minutes"] = short_interval_rows["resolution_minutes"].fillna(60).astype(float)
        short_interval_rows["weighted_value"] = short_interval_rows["value_mw"] * short_interval_rows["interval_minutes"]

        group_columns = ["market", "hour_timestamp_utc"]
        if family.has_psr_dimension:
            group_columns.extend(["psr_type", "psr_label"])

        grouped = (
            short_interval_rows.groupby(group_columns, as_index=False)
            .agg(
                interval_end_utc=("interval_end_utc", "max"),
                source_observations=("value_mw", "size"),
                coverage_minutes=("interval_minutes", "sum"),
                weighted_value=("weighted_value", "sum"),
                source_file_count=("source_file", "nunique"),
            )
            .rename(columns={"hour_timestamp_utc": "timestamp_utc"})
        )
        grouped["expected_coverage_minutes"] = 60
        grouped["is_complete_hour"] = grouped["coverage_minutes"].eq(grouped["expected_coverage_minutes"])
        grouped["value_mw"] = grouped["weighted_value"] / grouped["coverage_minutes"]
        grouped.loc[~grouped["is_complete_hour"], "value_mw"] = pd.NA
        grouped = grouped.drop(columns=["weighted_value"])
        grouped["family"] = family.name
        expanded_parts.append(grouped)

    hourly = pd.concat(expanded_parts, ignore_index=True) if expanded_parts else pd.DataFrame()
    return add_time_columns(hourly, family)


def expand_yearly_capacity_to_hourly(frame: pd.DataFrame, family: FamilyConfig) -> pd.DataFrame:
    hourly_parts: list[pd.DataFrame] = []
    for row in frame.itertuples(index=False):
        start_utc = pd.Timestamp(row.timestamp_utc)
        end_utc = pd.Timestamp(row.interval_end_utc)
        if pd.isna(start_utc) or pd.isna(end_utc) or end_utc <= start_utc:
            continue
        index = pd.date_range(start=start_utc, end=end_utc - pd.Timedelta(hours=1), freq="h", tz="UTC")
        if index.empty:
            continue
        part = pd.DataFrame(
            {
                "family": family.name,
                "market": row.market,
                "timestamp_utc": index,
                "interval_end_utc": index + pd.Timedelta(hours=1),
                "value_mw": float(row.value_mw) if pd.notna(row.value_mw) else pd.NA,
                "source_observations": 1,
                "coverage_minutes": 60,
                "expected_coverage_minutes": 60,
                "is_complete_hour": True,
                "source_file_count": 1,
                "psr_type": row.psr_type,
                "psr_label": row.psr_label,
            }
        )
        hourly_parts.append(part)

    hourly = pd.concat(hourly_parts, ignore_index=True) if hourly_parts else pd.DataFrame()
    return add_time_columns(hourly, family)


def summarize_frame(frame: pd.DataFrame, family: FamilyConfig, stage: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            [
                {
                    "family": family.name,
                    "stage": stage,
                    "market": None,
                    "psr_scope": None,
                    "rows": 0,
                    "unique_timestamps": 0,
                    "duplicates": 0,
                    "missing_values": 0,
                    "min_timestamp_utc": None,
                    "max_timestamp_utc": None,
                    "coverage_rows_complete": 0,
                }
            ]
        )

    summary_rows: list[dict[str, Any]] = []
    group_columns = ["market"]
    if family.has_psr_dimension:
        group_columns.append("psr_type")
    for keys, group in frame.groupby(group_columns, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        market = keys[0]
        psr_scope = keys[1] if family.has_psr_dimension and len(keys) > 1 else "TOTAL"
        summary_rows.append(
            {
                "family": family.name,
                "stage": stage,
                "market": market,
                "psr_scope": psr_scope,
                "rows": int(group.shape[0]),
                "unique_timestamps": int(group["timestamp_utc"].nunique()),
                "duplicates": int(group.duplicated(subset=["timestamp_utc"]).sum()),
                "missing_values": int(group["value_mw"].isna().sum()),
                "min_timestamp_utc": group["timestamp_utc"].min().isoformat() if group["timestamp_utc"].notna().any() else None,
                "max_timestamp_utc": group["timestamp_utc"].max().isoformat() if group["timestamp_utc"].notna().any() else None,
                "coverage_rows_complete": int(group.get("is_complete_hour", pd.Series(dtype=bool)).fillna(False).sum())
                if "is_complete_hour" in group
                else None,
            }
        )
    return pd.DataFrame(summary_rows).sort_values(["market", "psr_scope"]).reset_index(drop=True)


def build_hourly_wide(hourly_long: pd.DataFrame, family: FamilyConfig) -> pd.DataFrame:
    if hourly_long.empty:
        return pd.DataFrame(columns=["timestamp_utc"])

    wide_source = hourly_long.copy()
    if family.has_psr_dimension:
        wide_source["column_key"] = wide_source.apply(
            lambda row: f"{row['market']}_{row['psr_type']}_{sanitize_label(str(row['psr_label']))}_mw",
            axis=1,
        )
    else:
        wide_source["column_key"] = wide_source["market"].map(lambda market: f"{market}_{family.name}_mw")

    wide = (
        wide_source.pivot_table(index="timestamp_utc", columns="column_key", values="value_mw", aggfunc="last")
        .sort_index()
        .reset_index()
    )
    wide.columns.name = None
    return wide


def write_family_outputs(
    output_root: Path,
    family: FamilyConfig,
    parsed_long: pd.DataFrame,
    hourly_long: pd.DataFrame,
    hourly_wide: pd.DataFrame,
    file_summary: pd.DataFrame,
    parsed_summary: pd.DataFrame,
    hourly_summary: pd.DataFrame,
) -> dict[str, str]:
    family_root = output_root / family.output_subdir
    parsed_dir = family_root / "parsed"
    hourly_dir = family_root / "hourly"
    diagnostics_dir = family_root / "diagnostics"

    parsed_dir.mkdir(parents=True, exist_ok=True)
    hourly_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    parsed_long_path = parsed_dir / f"{family.name}_long.csv"
    hourly_long_path = hourly_dir / f"{family.name}_hourly_long.csv"
    hourly_wide_path = hourly_dir / f"{family.name}_hourly_wide.csv"
    file_summary_path = diagnostics_dir / "file_parse_summary.csv"
    parsed_summary_path = diagnostics_dir / "parsed_summary.csv"
    hourly_summary_path = diagnostics_dir / "hourly_summary.csv"

    parsed_long.to_csv(parsed_long_path, index=False)
    hourly_long.to_csv(hourly_long_path, index=False)
    hourly_wide.to_csv(hourly_wide_path, index=False)
    file_summary.to_csv(file_summary_path, index=False)
    parsed_summary.to_csv(parsed_summary_path, index=False)
    hourly_summary.to_csv(hourly_summary_path, index=False)

    metadata = {
        "family": family.name,
        "availability_category": family.availability_category,
        "future_horizon_safe": family.future_horizon_safe,
        "known_at_rule": family.known_at_rule,
        "notes": family.notes,
        "parsed_long_path": str(parsed_long_path),
        "hourly_long_path": str(hourly_long_path),
        "hourly_wide_path": str(hourly_wide_path),
    }
    metadata_path = diagnostics_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    metadata["metadata_path"] = str(metadata_path)
    return metadata


def process_family(raw_root: Path, output_root: Path, markets: list[str], family: FamilyConfig) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    file_summaries: list[dict[str, Any]] = []
    missing_inputs: list[str] = []

    for market in markets:
        raw_dir = raw_root / family.raw_subdir_template.format(market=market)
        if not raw_dir.exists():
            missing_inputs.append(str(raw_dir))
            continue
        for xml_path in sorted(raw_dir.glob("*.xml")):
            rows, file_summary = parse_family_file(market=market, xml_path=xml_path, family=family)
            all_rows.extend(rows)
            file_summaries.append(file_summary)

    parsed_long = make_frame(all_rows)
    invalid_timestamp_rows = int(parsed_long["timestamp_utc"].isna().sum()) if not parsed_long.empty else 0
    parsed_long = parsed_long[parsed_long["timestamp_utc"].notna()].copy()
    deduped_long, duplicate_rows_removed = deduplicate_rows(parsed_long, family)
    parsed_long = add_time_columns(deduped_long, family)
    hourly_long = aggregate_to_hourly(parsed_long, family)
    hourly_wide = build_hourly_wide(hourly_long, family)

    file_summary_df = pd.DataFrame(file_summaries)
    parsed_summary_df = summarize_frame(parsed_long, family, stage="parsed")
    hourly_summary_df = summarize_frame(hourly_long, family, stage="hourly")
    metadata = write_family_outputs(
        output_root=output_root,
        family=family,
        parsed_long=parsed_long,
        hourly_long=hourly_long,
        hourly_wide=hourly_wide,
        file_summary=file_summary_df,
        parsed_summary=parsed_summary_df,
        hourly_summary=hourly_summary_df,
    )

    return {
        "family": family.name,
        "availability_category": family.availability_category,
        "future_horizon_safe": family.future_horizon_safe,
        "known_at_rule": family.known_at_rule,
        "notes": family.notes,
        "rows_parsed": int(parsed_long.shape[0]),
        "rows_hourly": int(hourly_long.shape[0]),
        "duplicate_rows_removed": duplicate_rows_removed,
        "invalid_timestamp_rows_dropped": invalid_timestamp_rows,
        "markets_processed": ",".join(sorted(markets)),
        "missing_input_dirs": json.dumps(missing_inputs),
        "parsed_long_path": metadata["parsed_long_path"],
        "hourly_long_path": metadata["hourly_long_path"],
        "hourly_wide_path": metadata["hourly_wide_path"],
        "metadata_path": metadata["metadata_path"],
    }


def main() -> None:
    args = parse_args()
    output_root = args.output_root
    output_root.mkdir(parents=True, exist_ok=True)

    selected_families = {value.strip() for value in args.families} if args.families else None
    manifest_rows: list[dict[str, Any]] = []
    for family in FAMILY_CONFIGS:
        if selected_families is not None and family.name not in selected_families:
            continue
        manifest_rows.append(
            process_family(
                raw_root=args.raw_root,
                output_root=output_root,
                markets=[market.upper() for market in args.markets],
                family=family,
            )
        )

    manifest = pd.DataFrame(manifest_rows).sort_values("family").reset_index(drop=True)
    manifest_path = output_root / "entsoe_feature_family_manifest.csv"
    manifest.to_csv(manifest_path, index=False)
    print(f"Wrote feature-family manifest to {manifest_path}")


if __name__ == "__main__":
    main()
