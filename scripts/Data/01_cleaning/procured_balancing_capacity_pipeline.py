from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd


DATASET_NAME = "12_3_f_nl_ir"
RAW_SUBDIR = Path("ENTSOE/12_3_F_NL_IR")
OUTPUT_SUBDIR = Path("Balancing") / "IR Capacity" / DATASET_NAME
MARKET = "NL"
MARKET_TIMEZONE = "Europe/Amsterdam"
KNOWN_AT_RULE = "created_datetime_utc_from_export_only_not_forecast_safe"

PT_RESOLUTION_PATTERN = re.compile(r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?$")
ARCHIVE_OFFSET_PATTERN = re.compile(r"_offset_(?P<offset>\d+)\.zip$", re.IGNORECASE)

FLOW_DIRECTION_LABELS = {
    "A01": "Up",
    "A02": "Down",
    "A03": "Symmetric",
}

CONTRACT_TYPE_LABELS = {
    "A01": "Daily",
    "A02": "Weekly",
    "A03": "Monthly",
    "A04": "Yearly",
    "A06": "Long_term_contract",
    "A13": "Hourly",
}

BUSINESS_TYPE_LABELS = {
    "B95": "Procured_capacity",
}

DOCUMENT_TYPE_LABELS = {
    "A15": "Acquiring_system_operator_reserve_schedule",
}

PROCESS_TYPE_LABELS = {
    "A47": "mFRR",
}

RESERVE_SOURCE_LABELS = {
    "A01": "Standard",
    "A02": "Specific",
    "A03": "Integrated_process",
    "A04": "Local",
    "A05": "Standard_mFRR_DA",
    "A07": "Standard_mFRR_SA_DA",
}

CURVE_TYPE_LABELS = {
    "A03": "Variable_block_curve",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse and clean ENTSO-E 12.3 F NL IR procured balancing capacity files into native offer-level "
            "long tables, daily direction summaries, hourly expanded summaries, and diagnostics."
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


def parse_archive_offset(archive_name: str) -> int | None:
    match = ARCHIVE_OFFSET_PATTERN.search(archive_name)
    if not match:
        return None
    return int(match.group("offset"))


def add_time_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    enriched = frame.copy()
    local_timestamp = enriched["timestamp_utc"].dt.tz_convert(MARKET_TIMEZONE)
    enriched["target_delivery_local_date"] = local_timestamp.dt.date
    enriched["target_hour_local"] = local_timestamp.dt.hour.astype("Int64")
    enriched["target_minute_local"] = local_timestamp.dt.minute.astype("Int64")
    return enriched


def counts_to_json(series: pd.Series) -> str:
    counts = series.value_counts(dropna=False).sort_index()
    payload: dict[str, int] = {}
    for key, value in counts.items():
        key_str = "missing" if pd.isna(key) else str(key)
        payload[key_str] = int(value)
    return json.dumps(payload, sort_keys=True)


def effective_interval(
    period_start_utc: pd.Timestamp | None,
    period_end_utc: pd.Timestamp | None,
    resolution_delta: pd.Timedelta | None,
    point_count: int,
    position: int | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None, str]:
    if period_start_utc is None:
        return None, None, "missing_period_start"

    if point_count == 1 and (position is None or position == 1) and period_end_utc is not None and period_end_utc > period_start_utc:
        return period_start_utc, period_end_utc, "single_point_full_period"

    if resolution_delta is not None and position is not None:
        timestamp_utc = period_start_utc + (position - 1) * resolution_delta
        interval_end_utc = timestamp_utc + resolution_delta
        if period_end_utc is not None and interval_end_utc > period_end_utc:
            interval_end_utc = period_end_utc
        return timestamp_utc, interval_end_utc, "point_resolution"

    if period_end_utc is not None and period_end_utc > period_start_utc:
        return period_start_utc, period_end_utc, "full_period_fallback"

    return period_start_utc, None, "start_only"


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
        "timestamp_utc",
        "interval_end_utc",
        "known_at_utc",
    ]
    for column in datetime_columns:
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")

    int_columns = [
        "source_archive_offset",
        "timeseries_index",
        "period_index",
        "point_position",
        "point_count_in_period",
        "reported_resolution_minutes",
        "effective_interval_minutes",
    ]
    for column in int_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")

    float_columns = ["quantity_maw", "procurement_price_eur_per_maw"]
    for column in float_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    return frame


def parse_archives(raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    all_rows: list[dict[str, Any]] = []
    archive_summaries: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []

    for archive_path in sorted(raw_dir.glob("*.zip")):
        archive_offset = parse_archive_offset(archive_path.name)
        try:
            with zipfile.ZipFile(archive_path) as zip_handle:
                member_names = sorted(name for name in zip_handle.namelist() if name.lower().endswith(".xml"))
                if not member_names:
                    parse_errors.append({"source_archive": archive_path.name, "source_member": None, "error": "No XML members found"})
                    continue

                archive_row_count = 0
                archive_periods: set[tuple[str | None, str | None]] = set()
                flow_counts: dict[str, int] = {}
                point_count_distribution: dict[int, int] = {}
                created_datetime_iso: str | None = None
                document_type_code: str | None = None
                process_type_code: str | None = None
                document_period_start_iso: str | None = None
                document_period_end_iso: str | None = None

                for member_name in member_names:
                    try:
                        root = ET.fromstring(zip_handle.read(member_name))
                    except Exception as exc:  # pragma: no cover - defensive logging
                        parse_errors.append(
                            {
                                "source_archive": archive_path.name,
                                "source_member": member_name,
                                "error": str(exc),
                            }
                        )
                        continue

                    namespace = infer_namespace(root)
                    created_datetime_utc = parse_ts(find_text(root, "ns:createdDateTime", namespace))
                    created_datetime_iso = created_datetime_utc.isoformat() if created_datetime_utc else created_datetime_iso
                    document_type_code = find_text(root, "ns:type", namespace)
                    process_type_code = find_text(root, "ns:process.processType", namespace)
                    area_domain = find_text(root, "ns:area_Domain.mRID", namespace)
                    document_period_start_utc = parse_ts(find_text(root, "ns:period.timeInterval/ns:start", namespace))
                    document_period_end_utc = parse_ts(find_text(root, "ns:period.timeInterval/ns:end", namespace))
                    document_period_start_iso = (
                        document_period_start_utc.isoformat() if document_period_start_utc else document_period_start_iso
                    )
                    document_period_end_iso = (
                        document_period_end_utc.isoformat() if document_period_end_utc else document_period_end_iso
                    )

                    for timeseries_index, time_series in enumerate(root.findall("ns:TimeSeries", namespace), start=1):
                        flow_direction_code = find_text(time_series, "ns:flowDirection.direction", namespace)
                        flow_counts[flow_direction_code or "missing"] = flow_counts.get(flow_direction_code or "missing", 0) + 1

                        business_type_code = find_text(time_series, "ns:businessType", namespace)
                        contract_type_code = find_text(time_series, "ns:type_MarketAgreement.type", namespace)
                        market_product_type_code = find_text(
                            time_series, "ns:original_MarketProduct.marketProductType", namespace
                        )
                        reserve_source_code = find_text(time_series, "ns:mktPSRType.psrType", namespace)
                        currency_unit = find_text(time_series, "ns:currency_Unit.name", namespace)
                        quantity_unit = find_text(time_series, "ns:quantity_Measure_Unit.name", namespace)
                        price_measure_unit = find_text(time_series, "ns:price_Measure_Unit.name", namespace)
                        curve_type_code = find_text(time_series, "ns:curveType", namespace)
                        timeseries_mrid = find_text(time_series, "ns:mRID", namespace)

                        for period_index, period in enumerate(time_series.findall("ns:Period", namespace), start=1):
                            series_period_start_utc = parse_ts(find_text(period, "ns:timeInterval/ns:start", namespace))
                            series_period_end_utc = parse_ts(find_text(period, "ns:timeInterval/ns:end", namespace))
                            archive_periods.add(
                                (
                                    series_period_start_utc.isoformat() if series_period_start_utc else None,
                                    series_period_end_utc.isoformat() if series_period_end_utc else None,
                                )
                            )

                            reported_resolution, reported_resolution_minutes, resolution_delta = parse_resolution(
                                find_text(period, "ns:resolution", namespace)
                            )
                            point_nodes = period.findall("ns:Point", namespace)
                            point_count_in_period = len(point_nodes)
                            point_count_distribution[point_count_in_period] = (
                                point_count_distribution.get(point_count_in_period, 0) + 1
                            )

                            for point in point_nodes:
                                point_position_text = find_text(point, "ns:position", namespace)
                                point_position = int(point_position_text) if point_position_text else None
                                timestamp_utc, interval_end_utc, interpretation = effective_interval(
                                    period_start_utc=series_period_start_utc,
                                    period_end_utc=series_period_end_utc,
                                    resolution_delta=resolution_delta,
                                    point_count=point_count_in_period,
                                    position=point_position,
                                )

                                effective_interval_minutes = None
                                if timestamp_utc is not None and interval_end_utc is not None and interval_end_utc > timestamp_utc:
                                    effective_interval_minutes = int((interval_end_utc - timestamp_utc).total_seconds() // 60)

                                native_offer_id = (
                                    f"{archive_path.name}::{member_name}::ts{timeseries_index:03d}::"
                                    f"p{period_index:02d}::pt{point_position or 0:03d}"
                                )

                                all_rows.append(
                                    {
                                        "family": DATASET_NAME,
                                        "market": MARKET,
                                        "native_offer_id": native_offer_id,
                                        "source_archive": archive_path.name,
                                        "source_archive_offset": archive_offset,
                                        "source_member": member_name,
                                        "created_datetime_utc": created_datetime_utc,
                                        "document_type_code": document_type_code,
                                        "document_type_label": label_for(document_type_code, DOCUMENT_TYPE_LABELS),
                                        "process_type_code": process_type_code,
                                        "process_type_label": label_for(process_type_code, PROCESS_TYPE_LABELS),
                                        "area_domain": area_domain,
                                        "document_period_start_utc": document_period_start_utc,
                                        "document_period_end_utc": document_period_end_utc,
                                        "timeseries_index": timeseries_index,
                                        "timeseries_mrid": timeseries_mrid,
                                        "period_index": period_index,
                                        "business_type_code": business_type_code,
                                        "business_type_label": label_for(business_type_code, BUSINESS_TYPE_LABELS),
                                        "contract_type_code": contract_type_code,
                                        "contract_type_label": label_for(contract_type_code, CONTRACT_TYPE_LABELS),
                                        "market_product_type_code": market_product_type_code,
                                        "reserve_source_code": reserve_source_code,
                                        "reserve_source_label": label_for(reserve_source_code, RESERVE_SOURCE_LABELS),
                                        "flow_direction_code": flow_direction_code,
                                        "flow_direction_label": label_for(flow_direction_code, FLOW_DIRECTION_LABELS),
                                        "curve_type_code": curve_type_code,
                                        "curve_type_label": label_for(curve_type_code, CURVE_TYPE_LABELS),
                                        "currency_unit": currency_unit,
                                        "quantity_unit": quantity_unit,
                                        "price_measure_unit": price_measure_unit,
                                        "series_period_start_utc": series_period_start_utc,
                                        "series_period_end_utc": series_period_end_utc,
                                        "reported_resolution": reported_resolution,
                                        "reported_resolution_minutes": reported_resolution_minutes,
                                        "point_position": point_position,
                                        "point_count_in_period": point_count_in_period,
                                        "interval_interpretation": interpretation,
                                        "timestamp_utc": timestamp_utc,
                                        "interval_end_utc": interval_end_utc,
                                        "effective_interval_minutes": effective_interval_minutes,
                                        "quantity_maw": find_text(point, "ns:quantity", namespace),
                                        "procurement_price_eur_per_maw": find_text(
                                            point, "ns:procurement_Price.amount", namespace
                                        ),
                                        "known_at_utc": created_datetime_utc,
                                        "known_at_rule": KNOWN_AT_RULE,
                                    }
                                )
                                archive_row_count += 1

                archive_summaries.append(
                    {
                        "source_archive": archive_path.name,
                        "source_archive_offset": archive_offset,
                        "size_kb": round(archive_path.stat().st_size / 1024, 1),
                        "created_datetime_utc": created_datetime_iso,
                        "document_type_code": document_type_code,
                        "document_type_label": label_for(document_type_code, DOCUMENT_TYPE_LABELS),
                        "process_type_code": process_type_code,
                        "process_type_label": label_for(process_type_code, PROCESS_TYPE_LABELS),
                        "document_period_start_utc": document_period_start_iso,
                        "document_period_end_utc": document_period_end_iso,
                        "offer_rows": archive_row_count,
                        "unique_delivery_periods": len(archive_periods),
                        "flow_direction_distribution": json.dumps(flow_counts, sort_keys=True),
                        "point_count_distribution": json.dumps(point_count_distribution, sort_keys=True),
                    }
                )
        except Exception as exc:  # pragma: no cover - defensive logging
            parse_errors.append({"source_archive": archive_path.name, "source_member": None, "error": str(exc)})

    offers = make_frame(all_rows)
    archive_summary = pd.DataFrame(archive_summaries).sort_values("source_archive").reset_index(drop=True)
    parse_errors_df = pd.DataFrame(parse_errors)
    if parse_errors_df.empty:
        parse_errors_df = pd.DataFrame(columns=["source_archive", "source_member", "error"])
    return offers, archive_summary, parse_errors_df


def build_offer_stack(offers: pd.DataFrame) -> pd.DataFrame:
    if offers.empty:
        return offers.copy()

    stacked = offers.copy()
    sort_columns = [
        "timestamp_utc",
        "interval_end_utc",
        "flow_direction_code",
        "procurement_price_eur_per_maw",
        "quantity_maw",
        "source_archive_offset",
        "timeseries_index",
        "native_offer_id",
    ]
    stacked = stacked.sort_values(
        sort_columns,
        ascending=[True, True, True, True, False, True, True, True],
    ).reset_index(drop=True)

    group_columns = ["timestamp_utc", "interval_end_utc", "flow_direction_code"]
    stacked["offer_rank_price_asc"] = stacked.groupby(group_columns).cumcount() + 1
    stacked["daily_direction_total_quantity_maw"] = stacked.groupby(group_columns)["quantity_maw"].transform("sum")
    stacked["daily_direction_offer_count"] = stacked.groupby(group_columns)["native_offer_id"].transform("size")
    stacked["cumulative_quantity_maw"] = stacked.groupby(group_columns)["quantity_maw"].cumsum()
    stacked["quantity_share_of_day_direction"] = stacked["quantity_maw"] / stacked["daily_direction_total_quantity_maw"]
    stacked["cumulative_quantity_share"] = stacked["cumulative_quantity_maw"] / stacked["daily_direction_total_quantity_maw"]
    stacked = add_time_columns(stacked)
    return stacked


def build_ambiguous_duplicate_content_summary(offers: pd.DataFrame) -> pd.DataFrame:
    if offers.empty:
        return pd.DataFrame()

    key_columns = [
        "timestamp_utc",
        "interval_end_utc",
        "flow_direction_code",
        "flow_direction_label",
        "quantity_maw",
        "procurement_price_eur_per_maw",
    ]
    summary = (
        offers.groupby(key_columns, as_index=False)
        .agg(
            ambiguous_offer_rows=("native_offer_id", "size"),
            source_archive_count=("source_archive", "nunique"),
        )
        .query("ambiguous_offer_rows > 1")
        .sort_values(["timestamp_utc", "flow_direction_code", "procurement_price_eur_per_maw", "quantity_maw"])
        .reset_index(drop=True)
    )
    return summary


def build_timeseries_mrid_reuse_summary(offers: pd.DataFrame) -> pd.DataFrame:
    if offers.empty:
        return pd.DataFrame()

    summary = (
        offers.groupby("timeseries_mrid", dropna=False, as_index=False)
        .agg(
            rows=("native_offer_id", "size"),
            source_archive_count=("source_archive", "nunique"),
            first_timestamp_utc=("timestamp_utc", "min"),
            last_timestamp_utc=("timestamp_utc", "max"),
        )
        .sort_values("timeseries_mrid")
        .reset_index(drop=True)
    )
    return summary


def build_daily_direction_summary(offers: pd.DataFrame) -> pd.DataFrame:
    if offers.empty:
        return pd.DataFrame()

    group_columns = [
        "family",
        "market",
        "timestamp_utc",
        "interval_end_utc",
        "flow_direction_code",
        "flow_direction_label",
        "contract_type_code",
        "contract_type_label",
        "reserve_source_code",
        "reserve_source_label",
        "business_type_code",
        "business_type_label",
        "market_product_type_code",
        "currency_unit",
        "quantity_unit",
        "price_measure_unit",
    ]

    weighted = (
        offers.assign(weighted_price_component=offers["quantity_maw"] * offers["procurement_price_eur_per_maw"])
        .groupby(group_columns, as_index=False)["weighted_price_component"]
        .sum()
    )

    daily = (
        offers.groupby(group_columns, as_index=False)
        .agg(
            offer_count=("native_offer_id", "size"),
            total_quantity_maw=("quantity_maw", "sum"),
            price_mean_eur_per_maw=("procurement_price_eur_per_maw", "mean"),
            price_median_eur_per_maw=("procurement_price_eur_per_maw", "median"),
            price_min_eur_per_maw=("procurement_price_eur_per_maw", "min"),
            price_max_eur_per_maw=("procurement_price_eur_per_maw", "max"),
            unique_price_levels=("procurement_price_eur_per_maw", "nunique"),
            max_offer_quantity_maw=("quantity_maw", "max"),
            source_archive_count=("source_archive", "nunique"),
            source_offer_rows=("native_offer_id", "size"),
            known_at_utc=("created_datetime_utc", "max"),
        )
    )
    daily = daily.merge(weighted, on=group_columns, how="left")
    daily["quantity_weighted_price_eur_per_maw"] = (
        daily["weighted_price_component"] / daily["total_quantity_maw"]
    )
    daily = daily.drop(columns=["weighted_price_component"])
    daily["effective_interval_minutes"] = (
        (daily["interval_end_utc"] - daily["timestamp_utc"]).dt.total_seconds().div(60).astype("Int64")
    )
    daily["known_at_rule"] = KNOWN_AT_RULE
    daily = add_time_columns(daily)

    ordered_columns = [
        "family",
        "market",
        "timestamp_utc",
        "interval_end_utc",
        "effective_interval_minutes",
        "offer_count",
        "total_quantity_maw",
        "quantity_weighted_price_eur_per_maw",
        "price_mean_eur_per_maw",
        "price_median_eur_per_maw",
        "price_min_eur_per_maw",
        "price_max_eur_per_maw",
        "unique_price_levels",
        "max_offer_quantity_maw",
        "source_archive_count",
        "source_offer_rows",
        "flow_direction_code",
        "flow_direction_label",
        "contract_type_code",
        "contract_type_label",
        "reserve_source_code",
        "reserve_source_label",
        "business_type_code",
        "business_type_label",
        "market_product_type_code",
        "currency_unit",
        "quantity_unit",
        "price_measure_unit",
        "target_delivery_local_date",
        "target_hour_local",
        "target_minute_local",
        "known_at_utc",
        "known_at_rule",
    ]
    return daily[ordered_columns].sort_values(["timestamp_utc", "flow_direction_code"]).reset_index(drop=True)


def build_daily_direction_wide(daily_long: pd.DataFrame) -> pd.DataFrame:
    if daily_long.empty:
        return pd.DataFrame(columns=["timestamp_utc"])

    working = daily_long.copy()
    working["direction_key"] = working["flow_direction_label"].str.lower().str.replace(" ", "_", regex=False)
    working["market_key"] = working["market"].str.lower()

    wide_parts: list[pd.DataFrame] = []
    for metric in ["offer_count", "total_quantity_maw", "quantity_weighted_price_eur_per_maw"]:
        part = (
            working.assign(column_key=working["market_key"] + "_" + working["direction_key"] + "_" + metric)
            .pivot_table(index="timestamp_utc", columns="column_key", values=metric, aggfunc="last")
            .sort_index()
        )
        wide_parts.append(part)

    wide = pd.concat(wide_parts, axis=1).sort_index(axis=1).reset_index()
    wide.columns.name = None
    return wide


def build_hourly_direction_summary(daily_long: pd.DataFrame) -> pd.DataFrame:
    if daily_long.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for row in daily_long.itertuples(index=False):
        if pd.isna(row.timestamp_utc) or pd.isna(row.interval_end_utc) or row.interval_end_utc <= row.timestamp_utc:
            continue

        hours = pd.date_range(start=row.timestamp_utc, end=row.interval_end_utc - pd.Timedelta(hours=1), freq="1h")
        for hour_timestamp_utc in hours:
            rows.append(
                {
                    "family": row.family,
                    "market": row.market,
                    "timestamp_utc": hour_timestamp_utc,
                    "interval_end_utc": hour_timestamp_utc + pd.Timedelta(hours=1),
                    "effective_interval_minutes": 60,
                    "offer_count": row.offer_count,
                    "total_quantity_maw": row.total_quantity_maw,
                    "quantity_weighted_price_eur_per_maw": row.quantity_weighted_price_eur_per_maw,
                    "price_mean_eur_per_maw": row.price_mean_eur_per_maw,
                    "price_median_eur_per_maw": row.price_median_eur_per_maw,
                    "price_min_eur_per_maw": row.price_min_eur_per_maw,
                    "price_max_eur_per_maw": row.price_max_eur_per_maw,
                    "unique_price_levels": row.unique_price_levels,
                    "max_offer_quantity_maw": row.max_offer_quantity_maw,
                    "source_archive_count": row.source_archive_count,
                    "source_offer_rows": row.source_offer_rows,
                    "is_complete_hour": True,
                    "flow_direction_code": row.flow_direction_code,
                    "flow_direction_label": row.flow_direction_label,
                    "contract_type_code": row.contract_type_code,
                    "contract_type_label": row.contract_type_label,
                    "reserve_source_code": row.reserve_source_code,
                    "reserve_source_label": row.reserve_source_label,
                    "business_type_code": row.business_type_code,
                    "business_type_label": row.business_type_label,
                    "market_product_type_code": row.market_product_type_code,
                    "currency_unit": row.currency_unit,
                    "quantity_unit": row.quantity_unit,
                    "price_measure_unit": row.price_measure_unit,
                    "known_at_utc": row.known_at_utc,
                    "known_at_rule": row.known_at_rule,
                }
            )

    hourly = pd.DataFrame(rows)
    if hourly.empty:
        return hourly
    hourly["timestamp_utc"] = pd.to_datetime(hourly["timestamp_utc"], utc=True, errors="coerce")
    hourly["interval_end_utc"] = pd.to_datetime(hourly["interval_end_utc"], utc=True, errors="coerce")
    hourly = add_time_columns(hourly)
    return hourly.sort_values(["timestamp_utc", "flow_direction_code"]).reset_index(drop=True)


def build_hourly_direction_wide(hourly_long: pd.DataFrame) -> pd.DataFrame:
    if hourly_long.empty:
        return pd.DataFrame(columns=["timestamp_utc"])

    working = hourly_long.copy()
    working["direction_key"] = working["flow_direction_label"].str.lower().str.replace(" ", "_", regex=False)
    working["market_key"] = working["market"].str.lower()

    wide_parts: list[pd.DataFrame] = []
    for metric in ["offer_count", "total_quantity_maw", "quantity_weighted_price_eur_per_maw"]:
        part = (
            working.assign(column_key=working["market_key"] + "_" + working["direction_key"] + "_" + metric)
            .pivot_table(index="timestamp_utc", columns="column_key", values=metric, aggfunc="last")
            .sort_index()
        )
        wide_parts.append(part)

    wide = pd.concat(wide_parts, axis=1).sort_index(axis=1).reset_index()
    wide.columns.name = None
    return wide


def summarize_offers(offers: pd.DataFrame) -> pd.DataFrame:
    if offers.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (flow_direction_code, flow_direction_label), group in offers.groupby(
        ["flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "flow_direction_code": flow_direction_code,
                "flow_direction_label": flow_direction_label,
                "rows": int(group.shape[0]),
                "unique_delivery_periods": int(group[["timestamp_utc", "interval_end_utc"]].drop_duplicates().shape[0]),
                "min_timestamp_utc": group["timestamp_utc"].min().isoformat() if group["timestamp_utc"].notna().any() else None,
                "max_interval_end_utc": group["interval_end_utc"].max().isoformat()
                if group["interval_end_utc"].notna().any()
                else None,
                "min_local_delivery_date": str(group["target_delivery_local_date"].min()),
                "max_local_delivery_date": str(group["target_delivery_local_date"].max()),
                "point_count_distribution": counts_to_json(group["point_count_in_period"]),
                "resolution_distribution": counts_to_json(group["reported_resolution"]),
                "interval_interpretation_distribution": counts_to_json(group["interval_interpretation"]),
            }
        )
    return pd.DataFrame(rows).sort_values("flow_direction_code").reset_index(drop=True)


def summarize_daily(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (flow_direction_code, flow_direction_label), group in daily.groupby(
        ["flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "flow_direction_code": flow_direction_code,
                "flow_direction_label": flow_direction_label,
                "rows": int(group.shape[0]),
                "min_timestamp_utc": group["timestamp_utc"].min().isoformat() if group["timestamp_utc"].notna().any() else None,
                "max_interval_end_utc": group["interval_end_utc"].max().isoformat()
                if group["interval_end_utc"].notna().any()
                else None,
                "min_local_delivery_date": str(group["target_delivery_local_date"].min()),
                "max_local_delivery_date": str(group["target_delivery_local_date"].max()),
                "total_offers": int(group["offer_count"].sum()),
                "total_quantity_maw": float(group["total_quantity_maw"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("flow_direction_code").reset_index(drop=True)


def summarize_hourly(hourly: pd.DataFrame) -> pd.DataFrame:
    if hourly.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (flow_direction_code, flow_direction_label), group in hourly.groupby(
        ["flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "flow_direction_code": flow_direction_code,
                "flow_direction_label": flow_direction_label,
                "rows": int(group.shape[0]),
                "unique_hours": int(group["timestamp_utc"].nunique()),
                "min_timestamp_utc": group["timestamp_utc"].min().isoformat() if group["timestamp_utc"].notna().any() else None,
                "max_interval_end_utc": group["interval_end_utc"].max().isoformat()
                if group["interval_end_utc"].notna().any()
                else None,
                "min_local_delivery_date": str(group["target_delivery_local_date"].min()),
                "max_local_delivery_date": str(group["target_delivery_local_date"].max()),
            }
        )
    return pd.DataFrame(rows).sort_values("flow_direction_code").reset_index(drop=True)


def write_outputs(
    output_root: Path,
    offers_long: pd.DataFrame,
    daily_long: pd.DataFrame,
    daily_wide: pd.DataFrame,
    hourly_long: pd.DataFrame,
    hourly_wide: pd.DataFrame,
    archive_summary: pd.DataFrame,
    parse_errors: pd.DataFrame,
    offers_summary: pd.DataFrame,
    daily_summary: pd.DataFrame,
    hourly_summary: pd.DataFrame,
    ambiguous_duplicate_content: pd.DataFrame,
    timeseries_mrid_reuse: pd.DataFrame,
) -> dict[str, str]:
    family_root = output_root / OUTPUT_SUBDIR
    parsed_dir = family_root / "parsed"
    aggregated_dir = family_root / "aggregated"
    hourly_dir = family_root / "hourly"
    diagnostics_dir = family_root / "diagnostics"

    parsed_dir.mkdir(parents=True, exist_ok=True)
    aggregated_dir.mkdir(parents=True, exist_ok=True)
    hourly_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    offers_long_path = parsed_dir / f"{DATASET_NAME}_offer_long.csv"
    daily_long_path = aggregated_dir / f"{DATASET_NAME}_daily_direction_long.csv"
    daily_wide_path = aggregated_dir / f"{DATASET_NAME}_daily_direction_wide.csv"
    hourly_long_path = hourly_dir / f"{DATASET_NAME}_hourly_direction_long.csv"
    hourly_wide_path = hourly_dir / f"{DATASET_NAME}_hourly_direction_wide.csv"

    offers_long.to_csv(offers_long_path, index=False)
    daily_long.to_csv(daily_long_path, index=False)
    daily_wide.to_csv(daily_wide_path, index=False)
    hourly_long.to_csv(hourly_long_path, index=False)
    hourly_wide.to_csv(hourly_wide_path, index=False)

    archive_summary_path = diagnostics_dir / "archive_summary.csv"
    parse_errors_path = diagnostics_dir / "parse_errors.csv"
    offers_summary_path = diagnostics_dir / "offers_summary.csv"
    daily_summary_path = diagnostics_dir / "daily_summary.csv"
    hourly_summary_path = diagnostics_dir / "hourly_summary.csv"
    ambiguous_duplicate_content_path = diagnostics_dir / "ambiguous_duplicate_content_summary.csv"
    timeseries_mrid_reuse_path = diagnostics_dir / "timeseries_mrid_reuse_summary.csv"

    archive_summary.to_csv(archive_summary_path, index=False)
    parse_errors.to_csv(parse_errors_path, index=False)
    offers_summary.to_csv(offers_summary_path, index=False)
    daily_summary.to_csv(daily_summary_path, index=False)
    hourly_summary.to_csv(hourly_summary_path, index=False)
    ambiguous_duplicate_content.to_csv(ambiguous_duplicate_content_path, index=False)
    timeseries_mrid_reuse.to_csv(timeseries_mrid_reuse_path, index=False)

    metadata = {
        "dataset": DATASET_NAME,
        "market": MARKET,
        "market_timezone_for_reporting": MARKET_TIMEZONE,
        "raw_input_dir": str(Path("data/00_Raw") / RAW_SUBDIR),
        "output_dir": str(Path("data/01_cleaned") / OUTPUT_SUBDIR),
        "known_at_rule": KNOWN_AT_RULE,
        "notes": [
            "Raw data is paginated across many zip archives with one XML member each and up to 100 offer rows per archive.",
            "Each native offer row is treated as a full-period daily contract when the file reports one point for the whole Period.",
            "The native offer-level table is preserved without removing ambiguous duplicate-looking rows because source files do not expose stable provider or resource identifiers and identical quantity-price tuples can be legitimate separate offers.",
            "Daily direction summaries aggregate native offers to total procured quantity and quantity-weighted procurement price.",
            "Hourly summaries are expansions of the aggregated daily summaries, repeated over the covered UTC hours of each delivery period.",
        ],
        "code_labels": {
            "document_type": DOCUMENT_TYPE_LABELS,
            "process_type": PROCESS_TYPE_LABELS,
            "business_type": BUSINESS_TYPE_LABELS,
            "contract_type": CONTRACT_TYPE_LABELS,
            "reserve_source": RESERVE_SOURCE_LABELS,
            "flow_direction": FLOW_DIRECTION_LABELS,
            "curve_type": CURVE_TYPE_LABELS,
        },
        "offers_long_path": str(offers_long_path),
        "daily_long_path": str(daily_long_path),
        "daily_wide_path": str(daily_wide_path),
        "hourly_long_path": str(hourly_long_path),
        "hourly_wide_path": str(hourly_wide_path),
        "archive_summary_path": str(archive_summary_path),
        "parse_errors_path": str(parse_errors_path),
        "offers_summary_path": str(offers_summary_path),
        "daily_summary_path": str(daily_summary_path),
        "hourly_summary_path": str(hourly_summary_path),
        "ambiguous_duplicate_content_path": str(ambiguous_duplicate_content_path),
        "timeseries_mrid_reuse_path": str(timeseries_mrid_reuse_path),
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

    offers_raw, archive_summary, parse_errors = parse_archives(raw_dir)
    offers_long = build_offer_stack(offers_raw)
    daily_long = build_daily_direction_summary(offers_long)
    daily_wide = build_daily_direction_wide(daily_long)
    hourly_long = build_hourly_direction_summary(daily_long)
    hourly_wide = build_hourly_direction_wide(hourly_long)

    offers_summary = summarize_offers(offers_long)
    daily_summary = summarize_daily(daily_long)
    hourly_summary = summarize_hourly(hourly_long)
    ambiguous_duplicate_content = build_ambiguous_duplicate_content_summary(offers_long)
    timeseries_mrid_reuse = build_timeseries_mrid_reuse_summary(offers_long)

    metadata = write_outputs(
        output_root=args.output_root,
        offers_long=offers_long,
        daily_long=daily_long,
        daily_wide=daily_wide,
        hourly_long=hourly_long,
        hourly_wide=hourly_wide,
        archive_summary=archive_summary,
        parse_errors=parse_errors,
        offers_summary=offers_summary,
        daily_summary=daily_summary,
        hourly_summary=hourly_summary,
        ambiguous_duplicate_content=ambiguous_duplicate_content,
        timeseries_mrid_reuse=timeseries_mrid_reuse,
    )

    print(f"Wrote native offer table to {metadata['offers_long_path']}")
    print(f"Wrote daily direction summary to {metadata['daily_long_path']}")
    print(f"Wrote hourly direction summary to {metadata['hourly_long_path']}")
    print(f"Ambiguous duplicate-content groups retained: {len(ambiguous_duplicate_content)}")


if __name__ == "__main__":
    main()
