from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd


DATASET_NAME = "12_3_e_nl_ir_a61"
RAW_SUBDIR = Path("ENTSOE/12_3_E/12_3_E_NL_IR_A61")
OUTPUT_SUBDIR = Path("02_Balancing_mFRR_IR") / "IR Energy" / DATASET_NAME
MARKET = "NL"
MARKET_TIMEZONE = "Europe/Amsterdam"
KNOWN_AT_RULE = "not_provided_in_raw_xml"
CANONICAL_RESOLUTION = "PT15M"
CANONICAL_RESOLUTION_MINUTES = 15

PT_RESOLUTION_PATTERN = re.compile(r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?$")

FLOW_DIRECTION_LABELS = {
    "A01": "Up",
    "A02": "Down",
    "A03": "Symmetric",
}

DOCUMENT_TYPE_LABELS = {
    "A24": "Bid_document",
}

PROCESS_TYPE_LABELS = {
    "A61": "Direct_activation_mFRR",
}

BUSINESS_TYPE_LABELS = {
    "A14": "Aggregated_energy_data",
}

CURVE_TYPE_LABELS = {
    "A01": "Sequential_fixed_size_curve",
    "A02": "Point_curve",
    "A03": "Variable_block_curve",
    "A04": "Overlapping_breakpoint_curve",
    "A05": "Non_overlapping_breakpoint_curve",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse and clean ENTSO-E 12.3.E NL IR A61 XML files into sparse points, derived blocks, "
            "canonical quarter-hour long/wide tables, hourly long/wide tables, and diagnostics."
        )
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/00_Raw"),
        help="Root folder that contains the ENTSOE raw subdirectory.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/01_cleaned"),
        help="Root folder for cleaned outputs.",
    )
    return parser.parse_args()


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
    if not pt_match:
        return value, None, None

    hours = int(pt_match.group("hours") or 0)
    minutes = int(pt_match.group("minutes") or 0)
    total_minutes = hours * 60 + minutes
    if total_minutes <= 0:
        return value, None, None
    return value, total_minutes, pd.Timedelta(minutes=total_minutes)


def label_for(code: str | None, mapping: dict[str, str]) -> str | None:
    if code is None:
        return None
    return mapping.get(code, code)


def counts_to_json(series: pd.Series) -> str:
    counts = series.value_counts(dropna=False).sort_index()
    payload: dict[str, int] = {}
    for key, value in counts.items():
        if pd.isna(key):
            key_str = "missing"
        elif isinstance(key, (int, float, bool, str)):
            key_str = str(key)
        else:
            key_str = str(key)
        payload[key_str] = int(value)
    return json.dumps(payload, sort_keys=True)


def add_time_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    enriched = frame.copy()
    local_timestamp = enriched["timestamp_utc"].dt.tz_convert(MARKET_TIMEZONE)
    enriched["target_delivery_local_date"] = local_timestamp.dt.date
    enriched["target_hour_local"] = local_timestamp.dt.hour.astype("Int64")
    enriched["target_minute_local"] = local_timestamp.dt.minute.astype("Int64")
    return enriched


def make_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    datetime_columns = [
        "created_datetime_utc",
        "document_period_start_utc",
        "document_period_end_utc",
        "series_period_start_utc",
        "series_period_end_utc",
        "point_timestamp_utc",
    ]
    for column in datetime_columns:
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")

    int_columns = [
        "timeseries_index",
        "period_index",
        "point_position",
        "point_count_in_period",
        "reported_resolution_minutes",
        "expected_dense_point_count",
    ]
    for column in int_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")

    float_columns = [
        "quantity_maw",
        "secondary_quantity_maw",
        "unavailable_quantity_maw",
    ]
    for column in float_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    return frame


def parse_xml_files(raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    all_rows: list[dict[str, Any]] = []
    file_summaries: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []

    for file_path in sorted(raw_dir.glob("*.xml")):
        try:
            root = ET.parse(file_path).getroot()
        except Exception as exc:  # pragma: no cover - defensive logging
            parse_errors.append({"source_file": file_path.name, "error": str(exc)})
            continue

        namespace = infer_namespace(root)
        created_datetime_utc = parse_ts(find_text(root, "ns:createdDateTime", namespace))
        document_type_code = find_text(root, "ns:type", namespace)
        process_type_code = find_text(root, "ns:process.processType", namespace)
        area_domain = find_text(root, "ns:area_Domain.mRID", namespace)
        document_period_start_utc = parse_ts(find_text(root, "ns:period.timeInterval/ns:start", namespace))
        document_period_end_utc = parse_ts(find_text(root, "ns:period.timeInterval/ns:end", namespace))

        file_point_count = 0
        file_period_count = 0
        flow_direction_counts: dict[str, int] = {}
        resolution_counts: dict[str, int] = {}

        for timeseries_index, time_series in enumerate(root.findall("ns:TimeSeries", namespace), start=1):
            flow_direction_code = find_text(time_series, "ns:flowDirection.direction", namespace)
            business_type_code = find_text(time_series, "ns:businessType", namespace)
            market_product_type_code = find_text(
                time_series, "ns:original_MarketProduct.marketProductType", namespace
            )
            quantity_unit = find_text(time_series, "ns:quantity_Measure_Unit.name", namespace)
            curve_type_code = find_text(time_series, "ns:curveType", namespace)

            flow_direction_counts[flow_direction_code or "missing"] = (
                flow_direction_counts.get(flow_direction_code or "missing", 0) + 1
            )

            for period_index, period in enumerate(time_series.findall("ns:Period", namespace), start=1):
                file_period_count += 1
                series_period_start_utc = parse_ts(find_text(period, "ns:timeInterval/ns:start", namespace))
                series_period_end_utc = parse_ts(find_text(period, "ns:timeInterval/ns:end", namespace))
                reported_resolution, reported_resolution_minutes, resolution_delta = parse_resolution(
                    find_text(period, "ns:resolution", namespace)
                )
                point_nodes = period.findall("ns:Point", namespace)
                point_count_in_period = len(point_nodes)
                resolution_counts[reported_resolution or "missing"] = (
                    resolution_counts.get(reported_resolution or "missing", 0) + 1
                )

                expected_dense_point_count: int | None = None
                if (
                    series_period_start_utc is not None
                    and series_period_end_utc is not None
                    and reported_resolution_minutes
                    and series_period_end_utc > series_period_start_utc
                ):
                    total_minutes = int((series_period_end_utc - series_period_start_utc).total_seconds() // 60)
                    expected_dense_point_count = total_minutes // reported_resolution_minutes

                for point in point_nodes:
                    point_position_text = find_text(point, "ns:position", namespace)
                    point_position = int(point_position_text) if point_position_text else None
                    point_timestamp_utc = None
                    if (
                        series_period_start_utc is not None
                        and resolution_delta is not None
                        and point_position is not None
                        and point_position >= 1
                    ):
                        point_timestamp_utc = series_period_start_utc + (point_position - 1) * resolution_delta

                    all_rows.append(
                        {
                            "family": DATASET_NAME,
                            "market": MARKET,
                            "source_file": file_path.name,
                            "created_datetime_utc": created_datetime_utc,
                            "document_type_code": document_type_code,
                            "document_type_label": label_for(document_type_code, DOCUMENT_TYPE_LABELS),
                            "process_type_code": process_type_code,
                            "process_type_label": label_for(process_type_code, PROCESS_TYPE_LABELS),
                            "area_domain": area_domain,
                            "document_period_start_utc": document_period_start_utc,
                            "document_period_end_utc": document_period_end_utc,
                            "timeseries_index": timeseries_index,
                            "period_index": period_index,
                            "business_type_code": business_type_code,
                            "business_type_label": label_for(business_type_code, BUSINESS_TYPE_LABELS),
                            "market_product_type_code": market_product_type_code,
                            "flow_direction_code": flow_direction_code,
                            "flow_direction_label": label_for(flow_direction_code, FLOW_DIRECTION_LABELS),
                            "curve_type_code": curve_type_code,
                            "curve_type_label": label_for(curve_type_code, CURVE_TYPE_LABELS),
                            "quantity_unit": quantity_unit,
                            "series_period_start_utc": series_period_start_utc,
                            "series_period_end_utc": series_period_end_utc,
                            "reported_resolution": reported_resolution,
                            "reported_resolution_minutes": reported_resolution_minutes,
                            "point_count_in_period": point_count_in_period,
                            "expected_dense_point_count": expected_dense_point_count,
                            "point_position": point_position,
                            "point_timestamp_utc": point_timestamp_utc,
                            "quantity_maw": find_text(point, "ns:quantity", namespace),
                            "secondary_quantity_maw": find_text(point, "ns:secondaryQuantity", namespace),
                            "unavailable_quantity_maw": find_text(
                                point, "ns:unavailable_Quantity.quantity", namespace
                            ),
                        }
                    )
                    file_point_count += 1

        file_summaries.append(
            {
                "source_file": file_path.name,
                "size_kb": round(file_path.stat().st_size / 1024, 1),
                "created_datetime_utc": created_datetime_utc.isoformat() if created_datetime_utc else None,
                "document_type_code": document_type_code,
                "document_type_label": label_for(document_type_code, DOCUMENT_TYPE_LABELS),
                "process_type_code": process_type_code,
                "process_type_label": label_for(process_type_code, PROCESS_TYPE_LABELS),
                "document_period_start_utc": document_period_start_utc.isoformat()
                if document_period_start_utc
                else None,
                "document_period_end_utc": document_period_end_utc.isoformat() if document_period_end_utc else None,
                "point_rows": file_point_count,
                "period_count": file_period_count,
                "flow_direction_distribution": json.dumps(flow_direction_counts, sort_keys=True),
                "reported_resolution_distribution": json.dumps(resolution_counts, sort_keys=True),
            }
        )

    points = make_frame(all_rows)
    file_summary = pd.DataFrame(file_summaries).sort_values("source_file").reset_index(drop=True)
    parse_errors_df = pd.DataFrame(parse_errors)
    if parse_errors_df.empty:
        parse_errors_df = pd.DataFrame(columns=["source_file", "error"])
    return points, file_summary, parse_errors_df


def deduplicate_points(points: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if points.empty:
        return points.copy(), points.copy()

    key_columns = [
        "market",
        "flow_direction_code",
        "series_period_start_utc",
        "series_period_end_utc",
        "point_position",
    ]
    ordered = points.sort_values(
        key_columns + ["created_datetime_utc", "source_file", "timeseries_index", "period_index"]
    ).reset_index(drop=True)
    duplicate_mask = ordered.duplicated(subset=key_columns, keep="last")
    duplicates_removed = ordered.loc[duplicate_mask].reset_index(drop=True)
    deduplicated = ordered.loc[~duplicate_mask].reset_index(drop=True)
    return deduplicated, duplicates_removed


def build_period_diagnostics(points: pd.DataFrame) -> pd.DataFrame:
    if points.empty:
        return pd.DataFrame()

    period_columns = [
        "source_file",
        "timeseries_index",
        "period_index",
        "flow_direction_code",
        "flow_direction_label",
        "business_type_code",
        "business_type_label",
        "market_product_type_code",
        "curve_type_code",
        "curve_type_label",
        "series_period_start_utc",
        "series_period_end_utc",
        "reported_resolution",
        "reported_resolution_minutes",
        "expected_dense_point_count",
    ]
    period_diagnostics = (
        points.groupby(period_columns, dropna=False, as_index=False)
        .agg(
            point_count=("point_position", "size"),
            first_position=("point_position", "min"),
            last_position=("point_position", "max"),
            first_point_timestamp_utc=("point_timestamp_utc", "min"),
            last_point_timestamp_utc=("point_timestamp_utc", "max"),
            unique_quantity_levels=("quantity_maw", "nunique"),
        )
        .sort_values(["series_period_start_utc", "flow_direction_code", "period_index"])
        .reset_index(drop=True)
    )
    period_diagnostics["period_duration_minutes"] = (
        (period_diagnostics["series_period_end_utc"] - period_diagnostics["series_period_start_utc"])
        .dt.total_seconds()
        .div(60)
        .astype("Int64")
    )
    period_diagnostics["compression_ratio_vs_dense_grid"] = (
        period_diagnostics["point_count"] / period_diagnostics["expected_dense_point_count"]
    )
    return period_diagnostics


def build_blocks(points: pd.DataFrame) -> pd.DataFrame:
    if points.empty:
        return pd.DataFrame()

    period_keys = [
        "source_file",
        "timeseries_index",
        "period_index",
        "flow_direction_code",
        "series_period_start_utc",
        "series_period_end_utc",
    ]
    ordered = points.sort_values(period_keys + ["point_position"]).reset_index(drop=True).copy()
    grouped = ordered.groupby(period_keys, dropna=False, sort=False)

    ordered["next_point_position"] = grouped["point_position"].shift(-1)
    ordered["next_point_timestamp_utc"] = grouped["point_timestamp_utc"].shift(-1)
    ordered["block_start_utc"] = ordered["point_timestamp_utc"]
    ordered["block_end_utc"] = ordered["next_point_timestamp_utc"].fillna(ordered["series_period_end_utc"])
    ordered["block_duration_minutes"] = (
        (ordered["block_end_utc"] - ordered["block_start_utc"]).dt.total_seconds().div(60).astype("Int64")
    )
    ordered["block_quarterhour_count"] = (
        ordered["block_duration_minutes"].div(CANONICAL_RESOLUTION_MINUTES).astype("Int64")
    )
    ordered["block_position_step"] = (
        ordered["next_point_position"] - ordered["point_position"]
    ).astype("Int64")
    ordered["block_interpretation"] = ordered["next_point_timestamp_utc"].notna().map(
        {True: "change_point_to_next_position", False: "last_point_to_period_end"}
    )

    blocks = ordered.rename(columns={"point_timestamp_utc": "native_point_timestamp_utc"}).copy()
    blocks = blocks.loc[blocks["block_end_utc"] > blocks["block_start_utc"]].reset_index(drop=True)
    blocks["block_id"] = range(1, len(blocks) + 1)

    ordered_columns = [
        "block_id",
        "family",
        "market",
        "source_file",
        "created_datetime_utc",
        "document_type_code",
        "document_type_label",
        "process_type_code",
        "process_type_label",
        "area_domain",
        "timeseries_index",
        "period_index",
        "business_type_code",
        "business_type_label",
        "market_product_type_code",
        "flow_direction_code",
        "flow_direction_label",
        "curve_type_code",
        "curve_type_label",
        "quantity_unit",
        "series_period_start_utc",
        "series_period_end_utc",
        "reported_resolution",
        "reported_resolution_minutes",
        "point_count_in_period",
        "expected_dense_point_count",
        "point_position",
        "native_point_timestamp_utc",
        "next_point_position",
        "next_point_timestamp_utc",
        "block_start_utc",
        "block_end_utc",
        "block_duration_minutes",
        "block_quarterhour_count",
        "block_position_step",
        "block_interpretation",
        "quantity_maw",
        "secondary_quantity_maw",
        "unavailable_quantity_maw",
    ]
    return blocks[ordered_columns].sort_values(["block_start_utc", "flow_direction_code", "block_id"]).reset_index(
        drop=True
    )


def expand_blocks_to_quarterhour(blocks: pd.DataFrame) -> pd.DataFrame:
    if blocks.empty:
        return pd.DataFrame()

    resolution_delta = pd.Timedelta(minutes=CANONICAL_RESOLUTION_MINUTES)
    rows: list[dict[str, Any]] = []

    for row in blocks.itertuples(index=False):
        if pd.isna(row.block_start_utc) or pd.isna(row.block_end_utc) or row.block_end_utc <= row.block_start_utc:
            continue

        quarterhours = pd.date_range(
            start=row.block_start_utc,
            end=row.block_end_utc - resolution_delta,
            freq=resolution_delta,
        )
        for timestamp_utc in quarterhours:
            rows.append(
                {
                    "family": row.family,
                    "market": row.market,
                    "timestamp_utc": timestamp_utc,
                    "interval_end_utc": timestamp_utc + resolution_delta,
                    "resolution_minutes": CANONICAL_RESOLUTION_MINUTES,
                    "quantity_maw": row.quantity_maw,
                    "secondary_quantity_maw": row.secondary_quantity_maw,
                    "unavailable_quantity_maw": row.unavailable_quantity_maw,
                    "source_block_id": row.block_id,
                    "source_file": row.source_file,
                    "flow_direction_code": row.flow_direction_code,
                    "flow_direction_label": row.flow_direction_label,
                    "business_type_code": row.business_type_code,
                    "business_type_label": row.business_type_label,
                    "market_product_type_code": row.market_product_type_code,
                    "curve_type_code": row.curve_type_code,
                    "curve_type_label": row.curve_type_label,
                    "series_period_start_utc": row.series_period_start_utc,
                    "series_period_end_utc": row.series_period_end_utc,
                    "block_start_utc": row.block_start_utc,
                    "block_end_utc": row.block_end_utc,
                    "block_duration_minutes": row.block_duration_minutes,
                }
            )

    quarterhour = pd.DataFrame(rows)
    if quarterhour.empty:
        return quarterhour

    quarterhour["timestamp_utc"] = pd.to_datetime(quarterhour["timestamp_utc"], utc=True, errors="coerce")
    quarterhour["interval_end_utc"] = pd.to_datetime(quarterhour["interval_end_utc"], utc=True, errors="coerce")
    quarterhour = add_time_columns(quarterhour)
    return quarterhour.sort_values(["timestamp_utc", "flow_direction_code", "source_block_id"]).reset_index(drop=True)


def build_quarterhour_wide(quarterhour_long: pd.DataFrame) -> pd.DataFrame:
    if quarterhour_long.empty:
        return pd.DataFrame(columns=["timestamp_utc"])

    working = quarterhour_long.copy()
    working["direction_key"] = working["flow_direction_label"].str.lower().str.replace(" ", "_", regex=False)
    working["market_key"] = working["market"].str.lower()

    wide_parts: list[pd.DataFrame] = []
    for metric in ["quantity_maw", "secondary_quantity_maw", "unavailable_quantity_maw"]:
        part = (
            working.assign(column_key=working["market_key"] + "_" + working["direction_key"] + "_" + metric)
            .pivot_table(index="timestamp_utc", columns="column_key", values=metric, aggfunc="last")
            .sort_index()
        )
        wide_parts.append(part)

    wide = pd.concat(wide_parts, axis=1).sort_index(axis=1).reset_index()
    wide.columns.name = None
    return wide


def aggregate_hourly(quarterhour_long: pd.DataFrame) -> pd.DataFrame:
    if quarterhour_long.empty:
        return pd.DataFrame()

    working = quarterhour_long.copy()
    working["hour_timestamp_utc"] = working["timestamp_utc"].dt.floor("h")
    group_columns = [
        "family",
        "market",
        "hour_timestamp_utc",
        "flow_direction_code",
        "flow_direction_label",
        "business_type_code",
        "business_type_label",
        "market_product_type_code",
        "curve_type_code",
        "curve_type_label",
    ]
    hourly = (
        working.groupby(group_columns, as_index=False)
        .agg(
            quarterhour_count=("timestamp_utc", "size"),
            quantity_maw=("quantity_maw", "mean"),
            secondary_quantity_maw=("secondary_quantity_maw", "mean"),
            unavailable_quantity_maw=("unavailable_quantity_maw", "mean"),
            source_block_count=("source_block_id", "nunique"),
            source_file_count=("source_file", "nunique"),
        )
        .rename(columns={"hour_timestamp_utc": "timestamp_utc"})
    )
    hourly["coverage_minutes"] = hourly["quarterhour_count"] * CANONICAL_RESOLUTION_MINUTES
    hourly["expected_coverage_minutes"] = 60
    hourly["is_complete_hour"] = hourly["coverage_minutes"].eq(hourly["expected_coverage_minutes"])
    hourly.loc[
        ~hourly["is_complete_hour"],
        ["quantity_maw", "secondary_quantity_maw", "unavailable_quantity_maw"],
    ] = pd.NA
    hourly["interval_end_utc"] = hourly["timestamp_utc"] + pd.Timedelta(hours=1)
    hourly["known_at_utc"] = pd.NaT
    hourly["known_at_rule"] = KNOWN_AT_RULE
    hourly = add_time_columns(hourly)

    ordered_columns = [
        "family",
        "market",
        "timestamp_utc",
        "interval_end_utc",
        "quantity_maw",
        "secondary_quantity_maw",
        "unavailable_quantity_maw",
        "quarterhour_count",
        "coverage_minutes",
        "expected_coverage_minutes",
        "is_complete_hour",
        "source_block_count",
        "source_file_count",
        "flow_direction_code",
        "flow_direction_label",
        "business_type_code",
        "business_type_label",
        "market_product_type_code",
        "curve_type_code",
        "curve_type_label",
        "target_delivery_local_date",
        "target_hour_local",
        "target_minute_local",
        "known_at_utc",
        "known_at_rule",
    ]
    return hourly[ordered_columns].sort_values(["timestamp_utc", "flow_direction_code"]).reset_index(drop=True)


def build_hourly_wide(hourly_long: pd.DataFrame) -> pd.DataFrame:
    if hourly_long.empty:
        return pd.DataFrame(columns=["timestamp_utc"])

    working = hourly_long.copy()
    working["direction_key"] = working["flow_direction_label"].str.lower().str.replace(" ", "_", regex=False)
    working["market_key"] = working["market"].str.lower()

    wide_parts: list[pd.DataFrame] = []
    for metric in ["quantity_maw", "secondary_quantity_maw", "unavailable_quantity_maw"]:
        part = (
            working.assign(column_key=working["market_key"] + "_" + working["direction_key"] + "_" + metric)
            .pivot_table(index="timestamp_utc", columns="column_key", values=metric, aggfunc="last")
            .sort_index()
        )
        wide_parts.append(part)

    wide = pd.concat(wide_parts, axis=1).sort_index(axis=1).reset_index()
    wide.columns.name = None
    return wide


def summarize_points(points: pd.DataFrame) -> pd.DataFrame:
    if points.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (flow_direction_code, flow_direction_label), group in points.groupby(
        ["flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "flow_direction_code": flow_direction_code,
                "flow_direction_label": flow_direction_label,
                "rows": int(group.shape[0]),
                "unique_periods": int(
                    group[["series_period_start_utc", "series_period_end_utc", "period_index"]].drop_duplicates().shape[0]
                ),
                "min_point_timestamp_utc": group["point_timestamp_utc"].min().isoformat()
                if group["point_timestamp_utc"].notna().any()
                else None,
                "max_point_timestamp_utc": group["point_timestamp_utc"].max().isoformat()
                if group["point_timestamp_utc"].notna().any()
                else None,
                "min_local_delivery_date": str(
                    group["point_timestamp_utc"].dt.tz_convert(MARKET_TIMEZONE).dt.date.min()
                ),
                "max_local_delivery_date": str(
                    group["point_timestamp_utc"].dt.tz_convert(MARKET_TIMEZONE).dt.date.max()
                ),
                "reported_resolution_distribution": json.dumps(
                    group["reported_resolution"].fillna("missing").value_counts().sort_index().to_dict(),
                    sort_keys=True,
                ),
                "point_count_distribution": counts_to_json(group["point_count_in_period"]),
            }
        )
    return pd.DataFrame(rows).sort_values("flow_direction_code").reset_index(drop=True)


def summarize_blocks(blocks: pd.DataFrame) -> pd.DataFrame:
    if blocks.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (flow_direction_code, flow_direction_label), group in blocks.groupby(
        ["flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "flow_direction_code": flow_direction_code,
                "flow_direction_label": flow_direction_label,
                "rows": int(group.shape[0]),
                "min_block_start_utc": group["block_start_utc"].min().isoformat()
                if group["block_start_utc"].notna().any()
                else None,
                "max_block_end_utc": group["block_end_utc"].max().isoformat() if group["block_end_utc"].notna().any() else None,
                "min_block_duration_minutes": int(group["block_duration_minutes"].min()),
                "max_block_duration_minutes": int(group["block_duration_minutes"].max()),
                "block_duration_distribution": counts_to_json(group["block_duration_minutes"]),
            }
        )
    return pd.DataFrame(rows).sort_values("flow_direction_code").reset_index(drop=True)


def summarize_quarterhour(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (flow_direction_code, flow_direction_label), group in frame.groupby(
        ["flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "flow_direction_code": flow_direction_code,
                "flow_direction_label": flow_direction_label,
                "rows": int(group.shape[0]),
                "unique_intervals": int(group["timestamp_utc"].nunique()),
                "min_timestamp_utc": group["timestamp_utc"].min().isoformat() if group["timestamp_utc"].notna().any() else None,
                "max_interval_end_utc": group["interval_end_utc"].max().isoformat()
                if group["interval_end_utc"].notna().any()
                else None,
                "min_local_delivery_date": str(group["target_delivery_local_date"].min()),
                "max_local_delivery_date": str(group["target_delivery_local_date"].max()),
            }
        )
    return pd.DataFrame(rows).sort_values("flow_direction_code").reset_index(drop=True)


def summarize_hourly(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (flow_direction_code, flow_direction_label), group in frame.groupby(
        ["flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "flow_direction_code": flow_direction_code,
                "flow_direction_label": flow_direction_label,
                "rows": int(group.shape[0]),
                "unique_hours": int(group["timestamp_utc"].nunique()),
                "incomplete_hours": int((~group["is_complete_hour"]).sum()),
                "min_timestamp_utc": group["timestamp_utc"].min().isoformat() if group["timestamp_utc"].notna().any() else None,
                "max_interval_end_utc": group["interval_end_utc"].max().isoformat()
                if group["interval_end_utc"].notna().any()
                else None,
                "min_local_delivery_date": str(group["target_delivery_local_date"].min()),
                "max_local_delivery_date": str(group["target_delivery_local_date"].max()),
            }
        )
    return pd.DataFrame(rows).sort_values("flow_direction_code").reset_index(drop=True)


def find_gap_intervals(quarterhour_long: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if quarterhour_long.empty:
        empty_columns = [
            "market",
            "flow_direction_code",
            "flow_direction_label",
            "timestamp_utc",
            "interval_end_utc",
        ]
        summary_columns = [
            "market",
            "flow_direction_code",
            "flow_direction_label",
            "missing_quarterhours",
            "merged_gap_count",
            "gap_start_utc",
            "gap_end_utc",
        ]
        return pd.DataFrame(columns=empty_columns), pd.DataFrame(columns=summary_columns)

    resolution_delta = pd.Timedelta(minutes=CANONICAL_RESOLUTION_MINUTES)
    gap_rows: list[dict[str, Any]] = []
    merged_rows: list[dict[str, Any]] = []

    for (market, flow_direction_code, flow_direction_label), group in quarterhour_long.groupby(
        ["market", "flow_direction_code", "flow_direction_label"], dropna=False
    ):
        present = pd.DatetimeIndex(group["timestamp_utc"].drop_duplicates().sort_values())
        if present.empty:
            continue

        full = pd.date_range(start=present.min(), end=group["interval_end_utc"].max() - resolution_delta, freq=resolution_delta)
        missing = full.difference(present)

        for timestamp_utc in missing:
            gap_rows.append(
                {
                    "market": market,
                    "flow_direction_code": flow_direction_code,
                    "flow_direction_label": flow_direction_label,
                    "timestamp_utc": timestamp_utc,
                    "interval_end_utc": timestamp_utc + resolution_delta,
                }
            )

        if missing.empty:
            continue

        missing_frame = pd.DataFrame({"timestamp_utc": missing})
        missing_frame["interval_end_utc"] = missing_frame["timestamp_utc"] + resolution_delta
        missing_frame["gap_group"] = missing_frame["timestamp_utc"].diff().ne(resolution_delta).cumsum()
        merged = (
            missing_frame.groupby("gap_group", as_index=False)
            .agg(
                gap_start_utc=("timestamp_utc", "min"),
                gap_last_timestamp_utc=("timestamp_utc", "max"),
                missing_quarterhours=("timestamp_utc", "size"),
            )
            .drop(columns=["gap_group"])
        )
        merged["gap_end_utc"] = merged["gap_last_timestamp_utc"] + resolution_delta
        merged["market"] = market
        merged["flow_direction_code"] = flow_direction_code
        merged["flow_direction_label"] = flow_direction_label
        merged["merged_gap_count"] = range(1, len(merged) + 1)
        merged_rows.extend(merged.drop(columns=["gap_last_timestamp_utc"]).to_dict("records"))

    gap_intervals = pd.DataFrame(gap_rows)
    if gap_intervals.empty:
        gap_intervals = pd.DataFrame(
            columns=["market", "flow_direction_code", "flow_direction_label", "timestamp_utc", "interval_end_utc"]
        )

    gap_summary = pd.DataFrame(merged_rows)
    if gap_summary.empty:
        gap_summary = pd.DataFrame(
            columns=[
                "market",
                "flow_direction_code",
                "flow_direction_label",
                "merged_gap_count",
                "missing_quarterhours",
                "gap_start_utc",
                "gap_end_utc",
            ]
        )
    else:
        gap_summary = gap_summary.sort_values(["flow_direction_code", "gap_start_utc"]).reset_index(drop=True)

    return gap_intervals, gap_summary


def write_outputs(
    output_root: Path,
    points_long: pd.DataFrame,
    blocks_long: pd.DataFrame,
    quarterhour_long: pd.DataFrame,
    quarterhour_wide: pd.DataFrame,
    hourly_long: pd.DataFrame,
    hourly_wide: pd.DataFrame,
    file_summary: pd.DataFrame,
    parse_errors: pd.DataFrame,
    points_summary: pd.DataFrame,
    period_diagnostics: pd.DataFrame,
    blocks_summary: pd.DataFrame,
    quarterhour_summary: pd.DataFrame,
    hourly_summary: pd.DataFrame,
    gap_intervals: pd.DataFrame,
    gap_summary: pd.DataFrame,
    duplicates_removed: pd.DataFrame,
) -> dict[str, str]:
    family_root = output_root / OUTPUT_SUBDIR
    parsed_dir = family_root / "parsed"
    quarterhour_dir = family_root / "quarterhour"
    hourly_dir = family_root / "hourly"
    diagnostics_dir = family_root / "diagnostics"

    parsed_dir.mkdir(parents=True, exist_ok=True)
    quarterhour_dir.mkdir(parents=True, exist_ok=True)
    hourly_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    points_long_path = parsed_dir / f"{DATASET_NAME}_points_long.csv"
    blocks_long_path = parsed_dir / f"{DATASET_NAME}_blocks_long.csv"
    quarterhour_long_path = quarterhour_dir / f"{DATASET_NAME}_quarterhour_long.csv"
    quarterhour_wide_path = quarterhour_dir / f"{DATASET_NAME}_quarterhour_wide.csv"
    hourly_long_path = hourly_dir / f"{DATASET_NAME}_hourly_long.csv"
    hourly_wide_path = hourly_dir / f"{DATASET_NAME}_hourly_wide.csv"

    points_long.to_csv(points_long_path, index=False)
    blocks_long.to_csv(blocks_long_path, index=False)
    quarterhour_long.to_csv(quarterhour_long_path, index=False)
    quarterhour_wide.to_csv(quarterhour_wide_path, index=False)
    hourly_long.to_csv(hourly_long_path, index=False)
    hourly_wide.to_csv(hourly_wide_path, index=False)

    file_summary_path = diagnostics_dir / "file_parse_summary.csv"
    parse_errors_path = diagnostics_dir / "parse_errors.csv"
    points_summary_path = diagnostics_dir / "points_summary.csv"
    period_diagnostics_path = diagnostics_dir / "period_diagnostics.csv"
    blocks_summary_path = diagnostics_dir / "blocks_summary.csv"
    quarterhour_summary_path = diagnostics_dir / "quarterhour_summary.csv"
    hourly_summary_path = diagnostics_dir / "hourly_summary.csv"
    gap_intervals_path = diagnostics_dir / "gap_intervals.csv"
    gap_summary_path = diagnostics_dir / "gap_summary.csv"
    duplicates_removed_path = diagnostics_dir / "duplicate_points_removed.csv"

    file_summary.to_csv(file_summary_path, index=False)
    parse_errors.to_csv(parse_errors_path, index=False)
    points_summary.to_csv(points_summary_path, index=False)
    period_diagnostics.to_csv(period_diagnostics_path, index=False)
    blocks_summary.to_csv(blocks_summary_path, index=False)
    quarterhour_summary.to_csv(quarterhour_summary_path, index=False)
    hourly_summary.to_csv(hourly_summary_path, index=False)
    gap_intervals.to_csv(gap_intervals_path, index=False)
    gap_summary.to_csv(gap_summary_path, index=False)
    duplicates_removed.to_csv(duplicates_removed_path, index=False)

    metadata = {
        "dataset": DATASET_NAME,
        "market": MARKET,
        "market_timezone_for_reporting": MARKET_TIMEZONE,
        "raw_input_dir": str(Path("data/00_Raw") / RAW_SUBDIR),
        "output_dir": str(Path("data/01_cleaned") / OUTPUT_SUBDIR),
        "canonical_resolution": CANONICAL_RESOLUTION,
        "known_at_rule": KNOWN_AT_RULE,
        "notes": [
            "Raw XML timestamps are stored and cleaned in UTC. Local date and hour fields are Europe/Amsterdam reporting helpers.",
            "The XML uses curveType A03 with sparse point positions. Each point is interpreted as the start of a block that runs until the next point or the end of the reported Period.",
            "The derived quarter-hour table is expanded on a canonical [start, end) PT15M UTC grid. Uncovered intervals are left missing instead of being invented.",
            "Hourly values are simple means across quarter-hours and are set to missing whenever hour coverage is incomplete.",
            "The raw files do not provide allocationDecision_DateAndOrTime. createdDateTime reflects file creation/export timing and is not treated as a forecast-safe known-at timestamp.",
        ],
        "code_labels": {
            "document_type": DOCUMENT_TYPE_LABELS,
            "process_type": PROCESS_TYPE_LABELS,
            "business_type": BUSINESS_TYPE_LABELS,
            "curve_type": CURVE_TYPE_LABELS,
            "flow_direction": FLOW_DIRECTION_LABELS,
        },
        "points_long_path": str(points_long_path),
        "blocks_long_path": str(blocks_long_path),
        "quarterhour_long_path": str(quarterhour_long_path),
        "quarterhour_wide_path": str(quarterhour_wide_path),
        "hourly_long_path": str(hourly_long_path),
        "hourly_wide_path": str(hourly_wide_path),
        "file_summary_path": str(file_summary_path),
        "parse_errors_path": str(parse_errors_path),
        "points_summary_path": str(points_summary_path),
        "period_diagnostics_path": str(period_diagnostics_path),
        "blocks_summary_path": str(blocks_summary_path),
        "quarterhour_summary_path": str(quarterhour_summary_path),
        "hourly_summary_path": str(hourly_summary_path),
        "gap_intervals_path": str(gap_intervals_path),
        "gap_summary_path": str(gap_summary_path),
        "duplicate_points_removed_path": str(duplicates_removed_path),
    }
    metadata_path = diagnostics_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    metadata["metadata_path"] = str(metadata_path)
    return metadata


def main() -> None:
    args = parse_args()
    raw_dir = args.raw_root / RAW_SUBDIR
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw input directory not found: {raw_dir}")

    points_raw, file_summary, parse_errors = parse_xml_files(raw_dir)
    points_long, duplicates_removed = deduplicate_points(points_raw)
    points_long = points_long.reset_index(drop=True)

    period_diagnostics = build_period_diagnostics(points_long)
    blocks_long = build_blocks(points_long)
    quarterhour_long = expand_blocks_to_quarterhour(blocks_long)
    quarterhour_wide = build_quarterhour_wide(quarterhour_long)
    hourly_long = aggregate_hourly(quarterhour_long)
    hourly_wide = build_hourly_wide(hourly_long)
    gap_intervals, gap_summary = find_gap_intervals(quarterhour_long)

    points_summary = summarize_points(points_long)
    blocks_summary = summarize_blocks(blocks_long)
    quarterhour_summary = summarize_quarterhour(quarterhour_long)
    hourly_summary = summarize_hourly(hourly_long)

    metadata = write_outputs(
        output_root=args.output_root,
        points_long=points_long,
        blocks_long=blocks_long,
        quarterhour_long=quarterhour_long,
        quarterhour_wide=quarterhour_wide,
        hourly_long=hourly_long,
        hourly_wide=hourly_wide,
        file_summary=file_summary,
        parse_errors=parse_errors,
        points_summary=points_summary,
        period_diagnostics=period_diagnostics,
        blocks_summary=blocks_summary,
        quarterhour_summary=quarterhour_summary,
        hourly_summary=hourly_summary,
        gap_intervals=gap_intervals,
        gap_summary=gap_summary,
        duplicates_removed=duplicates_removed,
    )

    print(f"Wrote sparse points to {metadata['points_long_path']}")
    print(f"Wrote derived blocks to {metadata['blocks_long_path']}")
    print(f"Wrote quarter-hour long table to {metadata['quarterhour_long_path']}")
    print(f"Wrote hourly long table to {metadata['hourly_long_path']}")
    print(f"Detected {len(gap_intervals)} uncovered quarter-hours across {len(gap_summary)} merged gaps")


if __name__ == "__main__":
    main()
