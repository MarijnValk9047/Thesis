from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import pandas as pd


MARKET = "DE"
MARKET_TIMEZONE = "Europe/Berlin"
KNOWN_AT_RULE = "not_provided_in_raw_xml"
CANONICAL_RESOLUTION = "PT15M"
CANONICAL_RESOLUTION_MINUTES = 15
EXPECTED_ZONE_COUNT = 4
ZONE_HANDLING_POLICY = (
    "Preserve zone-level German control-area outputs and build a combined-DE canonical layer by summing the "
    "reported zone quantities per quarter-hour and direction. Keep cross-zone diagnostics because the zone-level "
    "series are not assumed to be duplicates."
)

PT_RESOLUTION_PATTERN = re.compile(r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?$")
DE_FILENAME_PATTERN = re.compile(
    r"(?P<dataset>12_3_e_de_mari_mfrr(?:da|sa))_(?P<zone>[^_]+)_(?P<year>\d{4})_offset_(?P<offset>\d+)\.xml$",
    re.IGNORECASE,
)

FLOW_DIRECTION_LABELS = {
    "A01": "Up",
    "A02": "Down",
    "A03": "Symmetric",
}

DOCUMENT_TYPE_LABELS = {
    "A24": "Bid_document",
}

PROCESS_TYPE_LABELS = {
    "A60": "Scheduled_activation_mFRR",
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


@dataclass(frozen=True)
class DatasetConfig:
    dataset_key: str
    raw_subdir: Path
    output_subdir: Path
    process_type_code: str


DATASETS: dict[str, DatasetConfig] = {
    "12_3_e_de_mari_mfrrda": DatasetConfig(
        dataset_key="12_3_e_de_mari_mfrrda",
        raw_subdir=Path("ENTSOE/12_3_E/12_3_E_DE_MARI_mFRRda"),
        output_subdir=Path("Balancing") / "MARI DE" / "12_3_e_de_mari_mfrrda",
        process_type_code="A61",
    ),
    "12_3_e_de_mari_mfrrsa": DatasetConfig(
        dataset_key="12_3_e_de_mari_mfrrsa",
        raw_subdir=Path("ENTSOE/12_3_E/12_3_E_DE_MARI_mFRRsa"),
        output_subdir=Path("Balancing") / "MARI DE" / "12_3_e_de_mari_mfrrsa",
        process_type_code="A60",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse and clean ENTSO-E 12.3.E DE MARI XML files into native zone-level points, variable-duration "
            "blocks, zone-level and combined-DE quarter-hour tables, hourly tables, and diagnostics."
        )
    )
    parser.add_argument(
        "--dataset-key",
        choices=sorted(DATASETS),
        required=True,
        help="Dataset key to clean.",
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
        key_str = "missing" if pd.isna(key) else str(key)
        payload[key_str] = int(value)
    return json.dumps(payload, sort_keys=True)


def json_list(values: list[Any]) -> str:
    normalized = ["missing" if pd.isna(value) else str(value) for value in values]
    return json.dumps(sorted(dict.fromkeys(normalized)), sort_keys=False)


def add_time_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    enriched = frame.copy()
    local_timestamp = enriched["timestamp_utc"].dt.tz_convert(MARKET_TIMEZONE)
    enriched["target_delivery_local_date"] = local_timestamp.dt.date
    enriched["target_hour_local"] = local_timestamp.dt.hour.astype("Int64")
    enriched["target_minute_local"] = local_timestamp.dt.minute.astype("Int64")
    return enriched


def sanitize_key(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", value.strip()).strip("_").lower()


def parse_file_metadata(file_name: str) -> dict[str, Any]:
    match = DE_FILENAME_PATTERN.match(file_name)
    if not match:
        return {
            "source_zone_code": None,
            "source_year": None,
            "source_offset": None,
        }
    return {
        "source_zone_code": match.group("zone"),
        "source_year": int(match.group("year")),
        "source_offset": int(match.group("offset")),
    }


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
        "source_year",
        "source_offset",
        "timeseries_index",
        "timeseries_mrid",
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
        "effective_quantity_maw",
    ]
    for column in float_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    return frame


def parse_xml_files(raw_dir: Path, dataset_key: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    all_rows: list[dict[str, Any]] = []
    file_summaries: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []

    for file_path in sorted(raw_dir.glob("*.xml")):
        file_meta = parse_file_metadata(file_path.name)
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
        effective_source_counts: dict[str, int] = {}

        for timeseries_index, time_series in enumerate(root.findall("ns:TimeSeries", namespace), start=1):
            timeseries_mrid = find_text(time_series, "ns:mRID", namespace)
            business_type_code = find_text(time_series, "ns:businessType", namespace)
            market_product_type_code = find_text(
                time_series, "ns:standard_MarketProduct.marketProductType", namespace
            )
            flow_direction_code = find_text(time_series, "ns:flowDirection.direction", namespace)
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

                    quantity_text = find_text(point, "ns:quantity", namespace)
                    secondary_quantity_text = find_text(point, "ns:secondaryQuantity", namespace)
                    unavailable_quantity_text = find_text(point, "ns:unavailable_Quantity.quantity", namespace)

                    if secondary_quantity_text is not None:
                        effective_quantity_text = secondary_quantity_text
                        effective_quantity_source = "secondary_quantity"
                    elif quantity_text is not None:
                        effective_quantity_text = quantity_text
                        effective_quantity_source = "quantity"
                    else:
                        effective_quantity_text = None
                        effective_quantity_source = "missing"

                    effective_source_counts[effective_quantity_source] = (
                        effective_source_counts.get(effective_quantity_source, 0) + 1
                    )

                    all_rows.append(
                        {
                            "family": dataset_key,
                            "market": MARKET,
                            "source_file": file_path.name,
                            "source_zone_code": file_meta["source_zone_code"],
                            "source_year": file_meta["source_year"],
                            "source_offset": file_meta["source_offset"],
                            "created_datetime_utc": created_datetime_utc,
                            "document_type_code": document_type_code,
                            "document_type_label": label_for(document_type_code, DOCUMENT_TYPE_LABELS),
                            "process_type_code": process_type_code,
                            "process_type_label": label_for(process_type_code, PROCESS_TYPE_LABELS),
                            "area_domain": area_domain,
                            "area_domain_matches_filename_zone": area_domain == file_meta["source_zone_code"],
                            "document_period_start_utc": document_period_start_utc,
                            "document_period_end_utc": document_period_end_utc,
                            "timeseries_index": timeseries_index,
                            "timeseries_mrid": timeseries_mrid,
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
                            "quantity_maw": quantity_text,
                            "secondary_quantity_maw": secondary_quantity_text,
                            "unavailable_quantity_maw": unavailable_quantity_text,
                            "effective_quantity_maw": effective_quantity_text,
                            "effective_quantity_source": effective_quantity_source,
                        }
                    )
                    file_point_count += 1

        file_summaries.append(
            {
                "source_file": file_path.name,
                "source_zone_code": file_meta["source_zone_code"],
                "source_year": file_meta["source_year"],
                "source_offset": file_meta["source_offset"],
                "size_kb": round(file_path.stat().st_size / 1024, 1),
                "created_datetime_utc": created_datetime_utc.isoformat() if created_datetime_utc else None,
                "document_type_code": document_type_code,
                "document_type_label": label_for(document_type_code, DOCUMENT_TYPE_LABELS),
                "process_type_code": process_type_code,
                "process_type_label": label_for(process_type_code, PROCESS_TYPE_LABELS),
                "area_domain": area_domain,
                "area_domain_matches_filename_zone": area_domain == file_meta["source_zone_code"],
                "document_period_start_utc": document_period_start_utc.isoformat()
                if document_period_start_utc
                else None,
                "document_period_end_utc": document_period_end_utc.isoformat() if document_period_end_utc else None,
                "point_rows": file_point_count,
                "period_count": file_period_count,
                "flow_direction_distribution": json.dumps(flow_direction_counts, sort_keys=True),
                "reported_resolution_distribution": json.dumps(resolution_counts, sort_keys=True),
                "effective_quantity_source_distribution": json.dumps(effective_source_counts, sort_keys=True),
            }
        )

    points = make_frame(all_rows)
    file_summary = pd.DataFrame(file_summaries).sort_values(["source_zone_code", "source_year", "source_file"]).reset_index(
        drop=True
    )
    parse_errors_df = pd.DataFrame(parse_errors)
    if parse_errors_df.empty:
        parse_errors_df = pd.DataFrame(columns=["source_file", "error"])
    return points, file_summary, parse_errors_df


def deduplicate_points(points: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if points.empty:
        return points.copy(), points.copy()

    key_columns = [
        "source_zone_code",
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
        "source_zone_code",
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
    diagnostics = (
        points.groupby(period_columns, dropna=False, as_index=False)
        .agg(
            point_count=("point_position", "size"),
            first_position=("point_position", "min"),
            last_position=("point_position", "max"),
            first_point_timestamp_utc=("point_timestamp_utc", "min"),
            last_point_timestamp_utc=("point_timestamp_utc", "max"),
            unique_effective_quantity_levels=("effective_quantity_maw", "nunique"),
            effective_quantity_source_distribution=("effective_quantity_source", counts_to_json),
        )
        .sort_values(["source_zone_code", "series_period_start_utc", "flow_direction_code", "period_index"])
        .reset_index(drop=True)
    )
    diagnostics["period_duration_minutes"] = (
        (diagnostics["series_period_end_utc"] - diagnostics["series_period_start_utc"])
        .dt.total_seconds()
        .div(60)
        .astype("Int64")
    )
    diagnostics["compression_ratio_vs_dense_grid"] = (
        diagnostics["point_count"] / diagnostics["expected_dense_point_count"]
    )
    diagnostics["first_position_gt_1"] = diagnostics["first_position"].gt(1)
    diagnostics["has_sparse_gaps_between_positions"] = (
        diagnostics["last_position"] - diagnostics["first_position"] + 1
    ).gt(diagnostics["point_count"])
    return diagnostics


def build_blocks(points: pd.DataFrame) -> pd.DataFrame:
    if points.empty:
        return pd.DataFrame()

    period_keys = [
        "source_zone_code",
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
        "source_zone_code",
        "source_year",
        "source_offset",
        "created_datetime_utc",
        "document_type_code",
        "document_type_label",
        "process_type_code",
        "process_type_label",
        "area_domain",
        "area_domain_matches_filename_zone",
        "timeseries_index",
        "timeseries_mrid",
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
        "effective_quantity_maw",
        "effective_quantity_source",
    ]
    return blocks[ordered_columns].sort_values(
        ["source_zone_code", "block_start_utc", "flow_direction_code", "block_id"]
    ).reset_index(drop=True)


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
                    "source_zone_code": row.source_zone_code,
                    "timestamp_utc": timestamp_utc,
                    "interval_end_utc": timestamp_utc + resolution_delta,
                    "resolution_minutes": CANONICAL_RESOLUTION_MINUTES,
                    "quantity_maw": row.quantity_maw,
                    "secondary_quantity_maw": row.secondary_quantity_maw,
                    "unavailable_quantity_maw": row.unavailable_quantity_maw,
                    "effective_quantity_maw": row.effective_quantity_maw,
                    "effective_quantity_source": row.effective_quantity_source,
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
    return quarterhour.sort_values(["source_zone_code", "timestamp_utc", "flow_direction_code"]).reset_index(drop=True)


def build_zone_quarterhour_wide(quarterhour_long: pd.DataFrame) -> pd.DataFrame:
    if quarterhour_long.empty:
        return pd.DataFrame(columns=["timestamp_utc"])

    working = quarterhour_long.copy()
    working["zone_key"] = working["source_zone_code"].fillna("missing").map(sanitize_key)
    working["direction_key"] = working["flow_direction_label"].fillna("missing").map(sanitize_key)

    wide_parts: list[pd.DataFrame] = []
    for metric in ["effective_quantity_maw", "secondary_quantity_maw", "quantity_maw", "unavailable_quantity_maw"]:
        part = (
            working.assign(column_key=working["zone_key"] + "_" + working["direction_key"] + "_" + metric)
            .pivot_table(index="timestamp_utc", columns="column_key", values=metric, aggfunc="last")
            .sort_index()
        )
        wide_parts.append(part)

    wide = pd.concat(wide_parts, axis=1).sort_index(axis=1).reset_index()
    wide.columns.name = None
    return wide


def build_combined_quarterhour(zone_quarterhour_long: pd.DataFrame) -> pd.DataFrame:
    if zone_quarterhour_long.empty:
        return pd.DataFrame()

    grouped = zone_quarterhour_long.groupby(
        ["timestamp_utc", "interval_end_utc", "flow_direction_code", "flow_direction_label"], dropna=False
    )
    rows: list[dict[str, Any]] = []
    for (timestamp_utc, interval_end_utc, flow_direction_code, flow_direction_label), group in grouped:
        zone_codes = sorted(value for value in group["source_zone_code"].dropna().unique())
        unique_effective = sorted(value for value in group["effective_quantity_maw"].dropna().unique())
        all_identical = len(unique_effective) <= 1
        rows.append(
            {
                "family": group["family"].iloc[0],
                "market": MARKET,
                "combined_market_code": "DE_combined",
                "timestamp_utc": timestamp_utc,
                "interval_end_utc": interval_end_utc,
                "flow_direction_code": flow_direction_code,
                "flow_direction_label": flow_direction_label,
                "combined_effective_quantity_maw": group["effective_quantity_maw"].sum(min_count=1),
                "combined_secondary_quantity_maw": group["secondary_quantity_maw"].sum(min_count=1),
                "combined_quantity_maw": group["quantity_maw"].sum(min_count=1),
                "combined_unavailable_quantity_maw": group["unavailable_quantity_maw"].sum(min_count=1),
                "combined_aggregation_rule": "sum_across_reporting_zones",
                "reporting_zone_count": int(group["source_zone_code"].nunique(dropna=True)),
                "expected_zone_count": EXPECTED_ZONE_COUNT,
                "all_expected_zones_reporting": int(group["source_zone_code"].nunique(dropna=True)) == EXPECTED_ZONE_COUNT,
                "unique_zone_effective_quantity_count": len(unique_effective),
                "all_zone_values_identical": all_identical,
                "zone_effective_quantity_min_maw": group["effective_quantity_maw"].min(),
                "zone_effective_quantity_max_maw": group["effective_quantity_maw"].max(),
                "zone_effective_quantity_spread_maw": group["effective_quantity_maw"].max()
                - group["effective_quantity_maw"].min(),
                "zone_codes_json": json_list(zone_codes),
                "effective_quantity_source_distribution": counts_to_json(group["effective_quantity_source"]),
            }
        )

    combined = pd.DataFrame(rows)
    if combined.empty:
        return combined

    combined["timestamp_utc"] = pd.to_datetime(combined["timestamp_utc"], utc=True, errors="coerce")
    combined["interval_end_utc"] = pd.to_datetime(combined["interval_end_utc"], utc=True, errors="coerce")
    combined = add_time_columns(combined)
    return combined.sort_values(["timestamp_utc", "flow_direction_code"]).reset_index(drop=True)


def build_combined_quarterhour_wide(combined_quarterhour_long: pd.DataFrame) -> pd.DataFrame:
    if combined_quarterhour_long.empty:
        return pd.DataFrame(columns=["timestamp_utc"])

    working = combined_quarterhour_long.copy()
    working["direction_key"] = working["flow_direction_label"].fillna("missing").map(sanitize_key)

    wide_parts: list[pd.DataFrame] = []
    for metric in ["combined_effective_quantity_maw", "reporting_zone_count", "zone_effective_quantity_spread_maw"]:
        part = (
            working.assign(column_key="de_combined_" + working["direction_key"] + "_" + metric)
            .pivot_table(index="timestamp_utc", columns="column_key", values=metric, aggfunc="last")
            .sort_index()
        )
        wide_parts.append(part)

    wide = pd.concat(wide_parts, axis=1).sort_index(axis=1).reset_index()
    wide.columns.name = None
    return wide


def aggregate_zone_hourly(zone_quarterhour_long: pd.DataFrame) -> pd.DataFrame:
    if zone_quarterhour_long.empty:
        return pd.DataFrame()

    working = zone_quarterhour_long.copy()
    working["hour_timestamp_utc"] = working["timestamp_utc"].dt.floor("h")
    group_columns = [
        "family",
        "market",
        "source_zone_code",
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
            effective_quantity_maw=("effective_quantity_maw", "mean"),
            secondary_quantity_maw=("secondary_quantity_maw", "mean"),
            quantity_maw=("quantity_maw", "mean"),
            unavailable_quantity_maw=("unavailable_quantity_maw", "mean"),
            source_block_count=("source_block_id", "nunique"),
            source_file_count=("source_file", "nunique"),
        )
        .rename(columns={"hour_timestamp_utc": "timestamp_utc"})
    )
    hourly["coverage_minutes"] = hourly["quarterhour_count"] * CANONICAL_RESOLUTION_MINUTES
    hourly["expected_coverage_minutes"] = 60
    hourly["is_complete_hour"] = hourly["coverage_minutes"].eq(hourly["expected_coverage_minutes"])
    hourly["interval_end_utc"] = hourly["timestamp_utc"] + pd.Timedelta(hours=1)
    hourly["known_at_utc"] = pd.NaT
    hourly["known_at_rule"] = KNOWN_AT_RULE
    hourly = add_time_columns(hourly)
    return hourly.sort_values(["source_zone_code", "timestamp_utc", "flow_direction_code"]).reset_index(drop=True)


def aggregate_combined_hourly(combined_quarterhour_long: pd.DataFrame) -> pd.DataFrame:
    if combined_quarterhour_long.empty:
        return pd.DataFrame()

    working = combined_quarterhour_long.copy()
    working["hour_timestamp_utc"] = working["timestamp_utc"].dt.floor("h")
    group_columns = [
        "family",
        "market",
        "combined_market_code",
        "hour_timestamp_utc",
        "flow_direction_code",
        "flow_direction_label",
    ]
    hourly = (
        working.groupby(group_columns, as_index=False)
        .agg(
            quarterhour_count=("timestamp_utc", "size"),
            combined_effective_quantity_mean_maw=("combined_effective_quantity_maw", "mean"),
            combined_effective_quantity_min_maw=("combined_effective_quantity_maw", "min"),
            combined_effective_quantity_max_maw=("combined_effective_quantity_maw", "max"),
            min_reporting_zone_count=("reporting_zone_count", "min"),
            max_reporting_zone_count=("reporting_zone_count", "max"),
            zone_conflict_quarterhour_count=("all_zone_values_identical", lambda s: int((~s).sum())),
        )
        .rename(columns={"hour_timestamp_utc": "timestamp_utc"})
    )
    hourly["coverage_minutes"] = hourly["quarterhour_count"] * CANONICAL_RESOLUTION_MINUTES
    hourly["expected_coverage_minutes"] = 60
    hourly["is_complete_hour"] = hourly["coverage_minutes"].eq(hourly["expected_coverage_minutes"])
    hourly["combined_effective_quantity_spread_maw"] = (
        hourly["combined_effective_quantity_max_maw"] - hourly["combined_effective_quantity_min_maw"]
    )
    hourly["interval_end_utc"] = hourly["timestamp_utc"] + pd.Timedelta(hours=1)
    hourly["known_at_utc"] = pd.NaT
    hourly["known_at_rule"] = KNOWN_AT_RULE
    hourly["has_zone_conflict_in_hour"] = hourly["zone_conflict_quarterhour_count"].gt(0)
    hourly = add_time_columns(hourly)
    return hourly.sort_values(["timestamp_utc", "flow_direction_code"]).reset_index(drop=True)


def build_combined_hourly_wide(combined_hourly_long: pd.DataFrame) -> pd.DataFrame:
    if combined_hourly_long.empty:
        return pd.DataFrame(columns=["timestamp_utc"])

    working = combined_hourly_long.copy()
    working["direction_key"] = working["flow_direction_label"].fillna("missing").map(sanitize_key)

    wide_parts: list[pd.DataFrame] = []
    for metric in ["combined_effective_quantity_mean_maw", "quarterhour_count", "min_reporting_zone_count"]:
        part = (
            working.assign(column_key="de_combined_" + working["direction_key"] + "_" + metric)
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
    for (source_zone_code, flow_direction_code, flow_direction_label), group in points.groupby(
        ["source_zone_code", "flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "source_zone_code": source_zone_code,
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
                "effective_quantity_source_distribution": counts_to_json(group["effective_quantity_source"]),
            }
        )
    return pd.DataFrame(rows).sort_values(["source_zone_code", "flow_direction_code"]).reset_index(drop=True)


def summarize_blocks(blocks: pd.DataFrame) -> pd.DataFrame:
    if blocks.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (source_zone_code, flow_direction_code, flow_direction_label), group in blocks.groupby(
        ["source_zone_code", "flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "source_zone_code": source_zone_code,
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
    return pd.DataFrame(rows).sort_values(["source_zone_code", "flow_direction_code"]).reset_index(drop=True)


def summarize_zone_quarterhour(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (source_zone_code, flow_direction_code, flow_direction_label), group in frame.groupby(
        ["source_zone_code", "flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "source_zone_code": source_zone_code,
                "flow_direction_code": flow_direction_code,
                "flow_direction_label": flow_direction_label,
                "rows": int(group.shape[0]),
                "unique_intervals": int(group["timestamp_utc"].nunique()),
                "min_timestamp_utc": group["timestamp_utc"].min().isoformat() if group["timestamp_utc"].notna().any() else None,
                "max_interval_end_utc": group["interval_end_utc"].max().isoformat()
                if group["interval_end_utc"].notna().any()
                else None,
            }
        )
    return pd.DataFrame(rows).sort_values(["source_zone_code", "flow_direction_code"]).reset_index(drop=True)


def summarize_combined_quarterhour(frame: pd.DataFrame) -> pd.DataFrame:
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
                "min_reporting_zone_count": int(group["reporting_zone_count"].min()),
                "max_reporting_zone_count": int(group["reporting_zone_count"].max()),
                "zone_conflict_rows": int((~group["all_zone_values_identical"]).sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("flow_direction_code").reset_index(drop=True)


def summarize_zone_hourly(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (source_zone_code, flow_direction_code, flow_direction_label), group in frame.groupby(
        ["source_zone_code", "flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "source_zone_code": source_zone_code,
                "flow_direction_code": flow_direction_code,
                "flow_direction_label": flow_direction_label,
                "rows": int(group.shape[0]),
                "unique_hours": int(group["timestamp_utc"].nunique()),
                "full_coverage_hours": int(group["is_complete_hour"].sum()),
                "partial_hours": int((~group["is_complete_hour"]).sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["source_zone_code", "flow_direction_code"]).reset_index(drop=True)


def summarize_combined_hourly(frame: pd.DataFrame) -> pd.DataFrame:
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
                "full_coverage_hours": int(group["is_complete_hour"].sum()),
                "partial_hours": int((~group["is_complete_hour"]).sum()),
                "hours_with_zone_conflicts": int(group["has_zone_conflict_in_hour"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("flow_direction_code").reset_index(drop=True)


def build_zone_pair_comparison(zone_quarterhour_long: pd.DataFrame) -> pd.DataFrame:
    if zone_quarterhour_long.empty:
        return pd.DataFrame()

    comparisons: list[dict[str, Any]] = []
    zone_codes = sorted(value for value in zone_quarterhour_long["source_zone_code"].dropna().unique())
    for left_zone, right_zone in combinations(zone_codes, 2):
        left = zone_quarterhour_long.loc[zone_quarterhour_long["source_zone_code"] == left_zone, [
            "flow_direction_code",
            "timestamp_utc",
            "effective_quantity_maw",
        ]].rename(columns={"effective_quantity_maw": "left_effective_quantity_maw"})
        right = zone_quarterhour_long.loc[zone_quarterhour_long["source_zone_code"] == right_zone, [
            "flow_direction_code",
            "timestamp_utc",
            "effective_quantity_maw",
        ]].rename(columns={"effective_quantity_maw": "right_effective_quantity_maw"})
        merged = left.merge(right, on=["flow_direction_code", "timestamp_utc"], how="outer", indicator=True)
        both = merged.loc[merged["_merge"] == "both"].copy()
        comparisons.append(
            {
                "left_zone_code": left_zone,
                "right_zone_code": right_zone,
                "left_rows": int(len(left)),
                "right_rows": int(len(right)),
                "matching_rows": int(len(both)),
                "left_only_rows": int((merged["_merge"] == "left_only").sum()),
                "right_only_rows": int((merged["_merge"] == "right_only").sum()),
                "quantity_diff_rows": int((both["left_effective_quantity_maw"] != both["right_effective_quantity_maw"]).sum()),
                "identical_quarterhour_series": merged["_merge"].eq("both").all()
                and bool((both["left_effective_quantity_maw"] == both["right_effective_quantity_maw"]).all()),
            }
        )

    return pd.DataFrame(comparisons).sort_values(["left_zone_code", "right_zone_code"]).reset_index(drop=True)


def build_cross_zone_duplicate_summary(combined_quarterhour_long: pd.DataFrame) -> pd.DataFrame:
    if combined_quarterhour_long.empty:
        return pd.DataFrame()

    summary = combined_quarterhour_long[
        [
            "timestamp_utc",
            "interval_end_utc",
            "flow_direction_code",
            "flow_direction_label",
            "reporting_zone_count",
            "unique_zone_effective_quantity_count",
            "all_zone_values_identical",
            "zone_effective_quantity_spread_maw",
        ]
    ].copy()
    summary["is_exact_cross_zone_duplicate"] = summary["reporting_zone_count"].gt(1) & summary["all_zone_values_identical"]
    return summary.sort_values(["timestamp_utc", "flow_direction_code"]).reset_index(drop=True)


def write_outputs(
    config: DatasetConfig,
    output_dir: Path,
    *,
    points_raw: pd.DataFrame,
    file_summary: pd.DataFrame,
    parse_errors: pd.DataFrame,
    points_long: pd.DataFrame,
    duplicates_removed: pd.DataFrame,
    period_diagnostics: pd.DataFrame,
    blocks_long: pd.DataFrame,
    zone_quarterhour_long: pd.DataFrame,
    zone_quarterhour_wide: pd.DataFrame,
    combined_quarterhour_long: pd.DataFrame,
    combined_quarterhour_wide: pd.DataFrame,
    zone_hourly_long: pd.DataFrame,
    combined_hourly_long: pd.DataFrame,
    combined_hourly_wide: pd.DataFrame,
    points_summary: pd.DataFrame,
    blocks_summary: pd.DataFrame,
    zone_quarterhour_summary: pd.DataFrame,
    combined_quarterhour_summary: pd.DataFrame,
    zone_hourly_summary: pd.DataFrame,
    combined_hourly_summary: pd.DataFrame,
    zone_pair_comparison: pd.DataFrame,
    cross_zone_duplicate_summary: pd.DataFrame,
) -> None:
    parsed_dir = output_dir / "parsed"
    quarterhour_dir = output_dir / "quarterhour"
    hourly_dir = output_dir / "hourly"
    diagnostics_dir = output_dir / "diagnostics"

    for directory in [parsed_dir, quarterhour_dir, hourly_dir, diagnostics_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    dataset_key = config.dataset_key
    points_raw.to_csv(parsed_dir / f"{dataset_key}_points_raw.csv", index=False)
    points_long.to_csv(parsed_dir / f"{dataset_key}_points_long.csv", index=False)
    blocks_long.to_csv(parsed_dir / f"{dataset_key}_blocks_long.csv", index=False)
    zone_quarterhour_long.to_csv(quarterhour_dir / f"{dataset_key}_zone_quarterhour_long.csv", index=False)
    zone_quarterhour_wide.to_csv(quarterhour_dir / f"{dataset_key}_zone_quarterhour_wide.csv", index=False)
    combined_quarterhour_long.to_csv(quarterhour_dir / f"{dataset_key}_combined_quarterhour_long.csv", index=False)
    combined_quarterhour_wide.to_csv(quarterhour_dir / f"{dataset_key}_combined_quarterhour_wide.csv", index=False)
    zone_hourly_long.to_csv(hourly_dir / f"{dataset_key}_zone_hourly_long.csv", index=False)
    combined_hourly_long.to_csv(hourly_dir / f"{dataset_key}_combined_hourly_long.csv", index=False)
    combined_hourly_wide.to_csv(hourly_dir / f"{dataset_key}_combined_hourly_wide.csv", index=False)
    combined_quarterhour_long.to_csv(quarterhour_dir / f"{dataset_key}_canonical_quarterhour_long.csv", index=False)
    combined_quarterhour_wide.to_csv(quarterhour_dir / f"{dataset_key}_canonical_quarterhour_wide.csv", index=False)
    combined_hourly_long.to_csv(hourly_dir / f"{dataset_key}_canonical_hourly_long.csv", index=False)
    combined_hourly_wide.to_csv(hourly_dir / f"{dataset_key}_canonical_hourly_wide.csv", index=False)

    file_summary.to_csv(diagnostics_dir / "file_summary.csv", index=False)
    parse_errors.to_csv(diagnostics_dir / "parse_errors.csv", index=False)
    duplicates_removed.to_csv(diagnostics_dir / "duplicates_removed.csv", index=False)
    period_diagnostics.to_csv(diagnostics_dir / "period_diagnostics.csv", index=False)
    points_summary.to_csv(diagnostics_dir / "points_summary.csv", index=False)
    blocks_summary.to_csv(diagnostics_dir / "blocks_summary.csv", index=False)
    zone_quarterhour_summary.to_csv(diagnostics_dir / "zone_quarterhour_summary.csv", index=False)
    combined_quarterhour_summary.to_csv(diagnostics_dir / "combined_quarterhour_summary.csv", index=False)
    zone_hourly_summary.to_csv(diagnostics_dir / "zone_hourly_summary.csv", index=False)
    combined_hourly_summary.to_csv(diagnostics_dir / "combined_hourly_summary.csv", index=False)
    zone_pair_comparison.to_csv(diagnostics_dir / "zone_pair_comparison.csv", index=False)
    cross_zone_duplicate_summary.to_csv(diagnostics_dir / "cross_zone_duplicate_summary.csv", index=False)

    all_pairwise_identical = bool(
        not zone_pair_comparison.empty and zone_pair_comparison["identical_quarterhour_series"].all()
    )
    combined_conflict_count = int((~combined_quarterhour_long["all_zone_values_identical"]).sum()) if not combined_quarterhour_long.empty else 0

    metadata = {
        "dataset_name": dataset_key,
        "market": MARKET,
        "market_timezone": MARKET_TIMEZONE,
        "known_at_rule": KNOWN_AT_RULE,
        "canonical_resolution": CANONICAL_RESOLUTION,
        "canonical_resolution_minutes": CANONICAL_RESOLUTION_MINUTES,
        "expected_zone_count": EXPECTED_ZONE_COUNT,
        "zone_handling_policy": {
            "canonical_market_view": "combined_de_sum",
            "preserve_zone_level_outputs": True,
            "policy_note": ZONE_HANDLING_POLICY,
            "canonical_selection_reason": (
                "The combined-DE canonical layer sums the zone-level effective quantities per quarter-hour and direction."
            ),
        },
        "value_policy": {
            "effective_quantity_rule": "Use secondaryQuantity when present, otherwise quantity.",
            "effective_quantity_source_distribution": counts_to_json(points_long["effective_quantity_source"])
            if not points_long.empty
            else "{}",
        },
        "recommended_outputs": {
            "quarterhour_long": f"quarterhour/{dataset_key}_canonical_quarterhour_long.csv",
            "quarterhour_wide": f"quarterhour/{dataset_key}_canonical_quarterhour_wide.csv",
            "hourly_long": f"hourly/{dataset_key}_canonical_hourly_long.csv",
            "hourly_wide": f"hourly/{dataset_key}_canonical_hourly_wide.csv",
        },
        "rows": {
            "points_raw": int(len(points_raw)),
            "points_long": int(len(points_long)),
            "duplicates_removed": int(len(duplicates_removed)),
            "blocks_long": int(len(blocks_long)),
            "zone_quarterhour_long": int(len(zone_quarterhour_long)),
            "combined_quarterhour_long": int(len(combined_quarterhour_long)),
            "zone_hourly_long": int(len(zone_hourly_long)),
            "combined_hourly_long": int(len(combined_hourly_long)),
        },
        "coverage": {
            "min_point_timestamp_utc": points_long["point_timestamp_utc"].min().isoformat()
            if not points_long.empty and points_long["point_timestamp_utc"].notna().any()
            else None,
            "max_interval_end_utc": zone_quarterhour_long["interval_end_utc"].max().isoformat()
            if not zone_quarterhour_long.empty and zone_quarterhour_long["interval_end_utc"].notna().any()
            else None,
        },
        "validity_flags": {
            "all_pairwise_zone_quarterhour_series_identical": all_pairwise_identical,
            "combined_quarterhours_with_zone_conflicts": combined_conflict_count,
        },
        "code_labels": {
            "document_type": DOCUMENT_TYPE_LABELS,
            "process_type": PROCESS_TYPE_LABELS,
            "business_type": BUSINESS_TYPE_LABELS,
            "flow_direction": FLOW_DIRECTION_LABELS,
            "curve_type": CURVE_TYPE_LABELS,
        },
    }
    (diagnostics_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    config = DATASETS[args.dataset_key]
    raw_dir = args.raw_root / config.raw_subdir
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw input directory not found: {raw_dir}")

    output_dir = args.output_root / config.output_subdir

    points_raw, file_summary, parse_errors = parse_xml_files(raw_dir, config.dataset_key)
    points_long, duplicates_removed = deduplicate_points(points_raw)
    period_diagnostics = build_period_diagnostics(points_long)
    blocks_long = build_blocks(points_long)
    zone_quarterhour_long = expand_blocks_to_quarterhour(blocks_long)
    zone_quarterhour_wide = build_zone_quarterhour_wide(zone_quarterhour_long)
    combined_quarterhour_long = build_combined_quarterhour(zone_quarterhour_long)
    combined_quarterhour_wide = build_combined_quarterhour_wide(combined_quarterhour_long)
    zone_hourly_long = aggregate_zone_hourly(zone_quarterhour_long)
    combined_hourly_long = aggregate_combined_hourly(combined_quarterhour_long)
    combined_hourly_wide = build_combined_hourly_wide(combined_hourly_long)
    points_summary = summarize_points(points_long)
    blocks_summary = summarize_blocks(blocks_long)
    zone_quarterhour_summary = summarize_zone_quarterhour(zone_quarterhour_long)
    combined_quarterhour_summary = summarize_combined_quarterhour(combined_quarterhour_long)
    zone_hourly_summary = summarize_zone_hourly(zone_hourly_long)
    combined_hourly_summary = summarize_combined_hourly(combined_hourly_long)
    zone_pair_comparison = build_zone_pair_comparison(zone_quarterhour_long)
    cross_zone_duplicate_summary = build_cross_zone_duplicate_summary(combined_quarterhour_long)

    write_outputs(
        config,
        output_dir,
        points_raw=points_raw,
        file_summary=file_summary,
        parse_errors=parse_errors,
        points_long=points_long,
        duplicates_removed=duplicates_removed,
        period_diagnostics=period_diagnostics,
        blocks_long=blocks_long,
        zone_quarterhour_long=zone_quarterhour_long,
        zone_quarterhour_wide=zone_quarterhour_wide,
        combined_quarterhour_long=combined_quarterhour_long,
        combined_quarterhour_wide=combined_quarterhour_wide,
        zone_hourly_long=zone_hourly_long,
        combined_hourly_long=combined_hourly_long,
        combined_hourly_wide=combined_hourly_wide,
        points_summary=points_summary,
        blocks_summary=blocks_summary,
        zone_quarterhour_summary=zone_quarterhour_summary,
        combined_quarterhour_summary=combined_quarterhour_summary,
        zone_hourly_summary=zone_hourly_summary,
        combined_hourly_summary=combined_hourly_summary,
        zone_pair_comparison=zone_pair_comparison,
        cross_zone_duplicate_summary=cross_zone_duplicate_summary,
    )


if __name__ == "__main__":
    main()
