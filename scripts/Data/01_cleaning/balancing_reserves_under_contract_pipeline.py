from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd


DATASET_NAME = "balancing_reserves_under_contract"
RAW_SUBDIR = Path("ENTSOE/17_1_BC_NL_IR")
OUTPUT_SUBDIR = Path("Balancing") / "IR Capacity" / DATASET_NAME
MARKET = "NL"
MARKET_TIMEZONE = "Europe/Amsterdam"
KNOWN_AT_RULE = "allocation_decision_datetime_utc"

PT_RESOLUTION_PATTERN = re.compile(r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?$")
PERIOD_RESOLUTION_PATTERN = re.compile(r"^P(?:(?P<days>\d+)D)?$")

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

PRICE_CATEGORY_LABELS = {
    "A04": "Excess_balance",
    "A05": "Insufficient_balance",
    "A06": "Average_bid_price",
    "A07": "Single_marginal_bid_price",
    "A08": "Cross_border_marginal_price",
}

RESERVE_SOURCE_LABELS = {
    "A01": "Standard",
    "A02": "Specific",
    "A03": "Integrated_process",
    "A04": "Local",
    "A05": "Standard_mFRR_DA",
    "A07": "Standard_mFRR_SA_DA",
}

BUSINESS_TYPE_LABELS = {
    "B95": "Procured_capacity",
}

DOCUMENT_TYPE_LABELS = {
    "A81": "Contracted_reserves",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse and clean ENTSO-E 17.1 B&C NL control-area reserve procurement files into "
            "native and hourly long/wide tables with diagnostics."
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
    if pt_match:
        hours = int(pt_match.group("hours") or 0)
        minutes = int(pt_match.group("minutes") or 0)
        total_minutes = hours * 60 + minutes
        if total_minutes <= 0:
            return value, None, None
        return value, total_minutes, pd.Timedelta(minutes=total_minutes)

    period_match = PERIOD_RESOLUTION_PATTERN.match(value)
    if period_match:
        days = int(period_match.group("days") or 0)
        if days <= 0:
            return value, None, None
        total_minutes = days * 24 * 60
        return value, total_minutes, pd.Timedelta(days=days)

    return value, None, None


def label_for(code: str | None, mapping: dict[str, str]) -> str | None:
    if code is None:
        return None
    return mapping.get(code, code)


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
        "timestamp_utc",
        "interval_end_utc",
        "created_datetime_utc",
        "allocation_decision_datetime_utc",
        "document_period_start_utc",
        "document_period_end_utc",
        "series_period_start_utc",
        "series_period_end_utc",
        "known_at_utc",
    ]
    for column in datetime_columns:
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")

    int_columns = [
        "reported_resolution_minutes",
        "effective_interval_minutes",
        "timeseries_index",
        "period_index",
        "point_position",
        "point_count_in_period",
        "expected_point_count_from_reported_resolution",
    ]
    for column in int_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")

    float_columns = ["quantity_maw", "procurement_price_eur"]
    for column in float_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    return frame


def add_time_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    enriched = frame.copy()
    local_timestamp = enriched["timestamp_utc"].dt.tz_convert(MARKET_TIMEZONE)
    enriched["target_delivery_local_date"] = local_timestamp.dt.date
    enriched["target_hour_local"] = local_timestamp.dt.hour.astype("Int64")
    return enriched


def parse_archives(raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    all_rows: list[dict[str, Any]] = []
    member_summaries: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []

    for archive_path in sorted(raw_dir.glob("*.zip")):
        with zipfile.ZipFile(archive_path) as zip_handle:
            member_names = sorted(name for name in zip_handle.namelist() if name.lower().endswith(".xml"))
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
                allocation_decision_datetime_utc = parse_ts(
                    find_text(root, "ns:allocationDecision_DateAndOrTime.dateTime", namespace)
                )
                document_type = find_text(root, "ns:type", namespace)
                process_type = find_text(root, "ns:process.processType", namespace)
                area_domain = find_text(root, "ns:area_Domain.mRID", namespace)
                document_period_start_utc = parse_ts(find_text(root, "ns:period.timeInterval/ns:start", namespace))
                document_period_end_utc = parse_ts(find_text(root, "ns:period.timeInterval/ns:end", namespace))

                resolution_counts: dict[str, int] = {}
                interpretation_counts: dict[str, int] = {}
                time_series_count = 0
                point_count = 0
                member_rows_start = len(all_rows)

                for timeseries_index, time_series in enumerate(root.findall("ns:TimeSeries", namespace), start=1):
                    time_series_count += 1
                    business_type = find_text(time_series, "ns:businessType", namespace)
                    contract_type_code = find_text(time_series, "ns:type_MarketAgreement.type", namespace)
                    reserve_source_code = find_text(time_series, "ns:mktPSRType.psrType", namespace)
                    flow_direction_code = find_text(time_series, "ns:flowDirection.direction", namespace)
                    currency_unit = find_text(time_series, "ns:currency_Unit.name", namespace)
                    quantity_unit = find_text(time_series, "ns:quantity_Measure_Unit.name", namespace)
                    curve_type = find_text(time_series, "ns:curveType", namespace)

                    for period_index, period in enumerate(time_series.findall("ns:Period", namespace), start=1):
                        series_period_start_utc = parse_ts(find_text(period, "ns:timeInterval/ns:start", namespace))
                        series_period_end_utc = parse_ts(find_text(period, "ns:timeInterval/ns:end", namespace))
                        reported_resolution = find_text(period, "ns:resolution", namespace)
                        _, reported_resolution_minutes, resolution_delta = parse_resolution(reported_resolution)
                        point_nodes = period.findall("ns:Point", namespace)
                        points_in_period = len(point_nodes)
                        resolution_counts[reported_resolution or "missing"] = resolution_counts.get(reported_resolution or "missing", 0) + 1

                        expected_point_count: int | None = None
                        if (
                            series_period_start_utc is not None
                            and series_period_end_utc is not None
                            and resolution_delta is not None
                            and series_period_end_utc > series_period_start_utc
                        ):
                            duration_minutes = int((series_period_end_utc - series_period_start_utc).total_seconds() // 60)
                            step_minutes = int(resolution_delta.total_seconds() // 60)
                            if step_minutes > 0 and duration_minutes % step_minutes == 0:
                                expected_point_count = duration_minutes // step_minutes

                        for point in point_nodes:
                            point_count += 1
                            point_position_text = find_text(point, "ns:position", namespace)
                            try:
                                point_position = int(point_position_text) if point_position_text is not None else None
                            except ValueError:
                                point_position = None

                            quantity = pd.to_numeric(find_text(point, "ns:quantity", namespace), errors="coerce")
                            procurement_price = pd.to_numeric(
                                find_text(point, "ns:procurement_Price.amount", namespace),
                                errors="coerce",
                            )
                            price_category_code = find_text(point, "ns:imbalance_Price.category", namespace)

                            timestamp_utc, interval_end_utc, interval_interpretation = effective_interval(
                                period_start_utc=series_period_start_utc,
                                period_end_utc=series_period_end_utc,
                                resolution_delta=resolution_delta,
                                point_count=points_in_period,
                                position=point_position,
                            )
                            interpretation_counts[interval_interpretation] = interpretation_counts.get(interval_interpretation, 0) + 1

                            effective_interval_minutes: int | None = None
                            if timestamp_utc is not None and interval_end_utc is not None and interval_end_utc > timestamp_utc:
                                effective_interval_minutes = int((interval_end_utc - timestamp_utc).total_seconds() // 60)

                            all_rows.append(
                                {
                                    "family": DATASET_NAME,
                                    "market": MARKET,
                                    "timestamp_utc": timestamp_utc,
                                    "interval_end_utc": interval_end_utc,
                                    "effective_interval_minutes": effective_interval_minutes,
                                    "quantity_maw": float(quantity) if pd.notna(quantity) else None,
                                    "procurement_price_eur": float(procurement_price) if pd.notna(procurement_price) else None,
                                    "reported_resolution": reported_resolution,
                                    "reported_resolution_minutes": reported_resolution_minutes,
                                    "interval_interpretation": interval_interpretation,
                                    "document_type": document_type,
                                    "document_type_label": label_for(document_type, DOCUMENT_TYPE_LABELS),
                                    "process_type": process_type,
                                    "business_type": business_type,
                                    "business_type_label": label_for(business_type, BUSINESS_TYPE_LABELS),
                                    "contract_type_code": contract_type_code,
                                    "contract_type_label": label_for(contract_type_code, CONTRACT_TYPE_LABELS),
                                    "reserve_source_code": reserve_source_code,
                                    "reserve_source_label": label_for(reserve_source_code, RESERVE_SOURCE_LABELS),
                                    "flow_direction_code": flow_direction_code,
                                    "flow_direction_label": label_for(flow_direction_code, FLOW_DIRECTION_LABELS),
                                    "price_category_code": price_category_code,
                                    "price_category_label": label_for(price_category_code, PRICE_CATEGORY_LABELS),
                                    "curve_type": curve_type,
                                    "area_domain": area_domain,
                                    "currency_unit": currency_unit,
                                    "quantity_unit": quantity_unit,
                                    "created_datetime_utc": created_datetime_utc,
                                    "allocation_decision_datetime_utc": allocation_decision_datetime_utc,
                                    "known_at_utc": allocation_decision_datetime_utc,
                                    "known_at_rule": KNOWN_AT_RULE,
                                    "document_period_start_utc": document_period_start_utc,
                                    "document_period_end_utc": document_period_end_utc,
                                    "series_period_start_utc": series_period_start_utc,
                                    "series_period_end_utc": series_period_end_utc,
                                    "source_archive": archive_path.name,
                                    "source_member": member_name,
                                    "source_path": f"{archive_path}::{member_name}",
                                    "timeseries_index": timeseries_index,
                                    "period_index": period_index,
                                    "point_position": point_position,
                                    "point_count_in_period": points_in_period,
                                    "expected_point_count_from_reported_resolution": expected_point_count,
                                }
                            )

                member_row_count = len(all_rows) - member_rows_start
                member_summaries.append(
                    {
                        "source_archive": archive_path.name,
                        "source_member": member_name,
                        "created_datetime_utc": created_datetime_utc.isoformat() if created_datetime_utc is not None else None,
                        "allocation_decision_datetime_utc": allocation_decision_datetime_utc.isoformat()
                        if allocation_decision_datetime_utc is not None
                        else None,
                        "document_type": document_type,
                        "process_type": process_type,
                        "area_domain": area_domain,
                        "document_period_start_utc": document_period_start_utc.isoformat()
                        if document_period_start_utc is not None
                        else None,
                        "document_period_end_utc": document_period_end_utc.isoformat()
                        if document_period_end_utc is not None
                        else None,
                        "time_series_count": time_series_count,
                        "point_count": point_count,
                        "rows_generated": member_row_count,
                        "reported_resolution_distribution": json.dumps(
                            dict(sorted(resolution_counts.items())),
                            sort_keys=True,
                        ),
                        "interval_interpretation_distribution": json.dumps(
                            dict(sorted(interpretation_counts.items())),
                            sort_keys=True,
                        ),
                    }
                )

    parsed_long = add_time_columns(make_frame(all_rows))
    member_summary_df = pd.DataFrame(member_summaries)
    parse_errors_df = pd.DataFrame(parse_errors)

    archive_summary_df = pd.DataFrame()
    if not member_summary_df.empty:
        archive_summary_df = (
            member_summary_df.groupby("source_archive", as_index=False)
            .agg(
                member_count=("source_member", "nunique"),
                rows_generated=("rows_generated", "sum"),
                time_series_count=("time_series_count", "sum"),
                point_count=("point_count", "sum"),
                first_document_period_start_utc=("document_period_start_utc", "min"),
                last_document_period_end_utc=("document_period_end_utc", "max"),
            )
            .sort_values("source_archive")
            .reset_index(drop=True)
        )

    return parsed_long, member_summary_df, archive_summary_df, parse_errors_df


def deduplicate_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame.copy(), frame.copy()

    key_columns = [
        "market",
        "timestamp_utc",
        "interval_end_utc",
        "flow_direction_code",
        "contract_type_code",
        "reserve_source_code",
        "price_category_code",
    ]
    ordered = frame.sort_values(
        key_columns
        + [
            "created_datetime_utc",
            "allocation_decision_datetime_utc",
            "source_archive",
            "source_member",
            "timeseries_index",
            "point_position",
        ],
        na_position="first",
    )
    duplicate_mask = ordered.duplicated(subset=key_columns, keep="last")
    duplicates_removed = ordered.loc[duplicate_mask].copy().reset_index(drop=True)
    deduped = ordered.loc[~duplicate_mask].copy().reset_index(drop=True)
    return deduped, duplicates_removed


def build_hourly_fragments(parsed_long: pd.DataFrame) -> pd.DataFrame:
    fragments: list[dict[str, Any]] = []
    if parsed_long.empty:
        return pd.DataFrame()

    for row in parsed_long.itertuples(index=False):
        start_utc = pd.Timestamp(row.timestamp_utc) if pd.notna(row.timestamp_utc) else None
        end_utc = pd.Timestamp(row.interval_end_utc) if pd.notna(row.interval_end_utc) else None
        if start_utc is None or end_utc is None or end_utc <= start_utc:
            continue

        hour_cursor = start_utc.floor("h")
        source_id = f"{row.source_archive}::{row.source_member}"
        while hour_cursor < end_utc:
            hour_end = hour_cursor + pd.Timedelta(hours=1)
            overlap_start = max(start_utc, hour_cursor)
            overlap_end = min(end_utc, hour_end)
            overlap_minutes = int((overlap_end - overlap_start).total_seconds() // 60)
            if overlap_minutes > 0:
                quantity_value = float(row.quantity_maw) if pd.notna(row.quantity_maw) else None
                procurement_price_value = float(row.procurement_price_eur) if pd.notna(row.procurement_price_eur) else None
                fragments.append(
                    {
                        "family": row.family,
                        "market": row.market,
                        "hour_timestamp_utc": hour_cursor,
                        "flow_direction_code": row.flow_direction_code,
                        "flow_direction_label": row.flow_direction_label,
                        "contract_type_code": row.contract_type_code,
                        "contract_type_label": row.contract_type_label,
                        "reserve_source_code": row.reserve_source_code,
                        "reserve_source_label": row.reserve_source_label,
                        "price_category_code": row.price_category_code,
                        "price_category_label": row.price_category_label,
                        "coverage_minutes": overlap_minutes,
                        "quantity_weighted": quantity_value * overlap_minutes if quantity_value is not None else None,
                        "price_weighted": procurement_price_value * overlap_minutes
                        if procurement_price_value is not None
                        else None,
                        "quantity_valid_minutes": overlap_minutes if quantity_value is not None else 0,
                        "price_valid_minutes": overlap_minutes if procurement_price_value is not None else 0,
                        "source_id": source_id,
                        "known_at_utc": row.known_at_utc,
                    }
                )
            hour_cursor = hour_end

    return pd.DataFrame(fragments)


def aggregate_hourly(parsed_long: pd.DataFrame) -> pd.DataFrame:
    fragments = build_hourly_fragments(parsed_long)
    if fragments.empty:
        return pd.DataFrame(
            columns=[
                "family",
                "market",
                "timestamp_utc",
                "interval_end_utc",
                "quantity_maw",
                "procurement_price_eur",
                "source_observations",
                "coverage_minutes",
                "expected_coverage_minutes",
                "quantity_valid_minutes",
                "price_valid_minutes",
                "is_complete_hour",
                "source_file_count",
                "flow_direction_code",
                "flow_direction_label",
                "contract_type_code",
                "contract_type_label",
                "reserve_source_code",
                "reserve_source_label",
                "price_category_code",
                "price_category_label",
                "known_at_utc",
                "known_at_rule",
            ]
        )

    group_columns = [
        "family",
        "market",
        "hour_timestamp_utc",
        "flow_direction_code",
        "flow_direction_label",
        "contract_type_code",
        "contract_type_label",
        "reserve_source_code",
        "reserve_source_label",
        "price_category_code",
        "price_category_label",
    ]
    grouped = (
        fragments.groupby(group_columns, as_index=False)
        .agg(
            coverage_minutes=("coverage_minutes", "sum"),
            quantity_weighted=("quantity_weighted", "sum"),
            price_weighted=("price_weighted", "sum"),
            quantity_valid_minutes=("quantity_valid_minutes", "sum"),
            price_valid_minutes=("price_valid_minutes", "sum"),
            source_observations=("source_id", "size"),
            source_file_count=("source_id", "nunique"),
            known_at_utc=("known_at_utc", "max"),
        )
        .rename(columns={"hour_timestamp_utc": "timestamp_utc"})
    )
    grouped["expected_coverage_minutes"] = 60
    grouped["is_complete_hour"] = grouped["coverage_minutes"].eq(grouped["expected_coverage_minutes"])
    grouped["quantity_maw"] = grouped["quantity_weighted"] / grouped["quantity_valid_minutes"]
    grouped["procurement_price_eur"] = grouped["price_weighted"] / grouped["price_valid_minutes"]
    grouped.loc[grouped["quantity_valid_minutes"] != grouped["coverage_minutes"], "quantity_maw"] = pd.NA
    grouped.loc[grouped["price_valid_minutes"] != grouped["coverage_minutes"], "procurement_price_eur"] = pd.NA
    grouped.loc[~grouped["is_complete_hour"], ["quantity_maw", "procurement_price_eur"]] = pd.NA
    grouped["interval_end_utc"] = grouped["timestamp_utc"] + pd.Timedelta(hours=1)
    grouped["known_at_rule"] = KNOWN_AT_RULE
    grouped = grouped.drop(columns=["quantity_weighted", "price_weighted"])
    grouped = add_time_columns(grouped)
    ordered_columns = [
        "family",
        "market",
        "timestamp_utc",
        "interval_end_utc",
        "quantity_maw",
        "procurement_price_eur",
        "source_observations",
        "coverage_minutes",
        "expected_coverage_minutes",
        "quantity_valid_minutes",
        "price_valid_minutes",
        "is_complete_hour",
        "source_file_count",
        "flow_direction_code",
        "flow_direction_label",
        "contract_type_code",
        "contract_type_label",
        "reserve_source_code",
        "reserve_source_label",
        "price_category_code",
        "price_category_label",
        "target_delivery_local_date",
        "target_hour_local",
        "known_at_utc",
        "known_at_rule",
    ]
    return grouped[ordered_columns].sort_values(
        ["timestamp_utc", "flow_direction_code", "contract_type_code", "reserve_source_code"]
    ).reset_index(drop=True)


def build_hourly_wide(hourly_long: pd.DataFrame) -> pd.DataFrame:
    if hourly_long.empty:
        return pd.DataFrame(columns=["timestamp_utc"])

    working = hourly_long.copy()
    working["direction_key"] = working["flow_direction_label"].str.lower().str.replace(" ", "_", regex=False)
    working["market_key"] = working["market"].str.lower()

    quantity_wide = (
        working.assign(column_key=working["market_key"] + "_" + working["direction_key"] + "_quantity_maw")
        .pivot_table(index="timestamp_utc", columns="column_key", values="quantity_maw", aggfunc="last")
        .sort_index()
    )
    price_wide = (
        working.assign(column_key=working["market_key"] + "_" + working["direction_key"] + "_procurement_price_eur")
        .pivot_table(index="timestamp_utc", columns="column_key", values="procurement_price_eur", aggfunc="last")
        .sort_index()
    )

    wide = pd.concat([quantity_wide, price_wide], axis=1).sort_index(axis=1).reset_index()
    wide.columns.name = None
    return wide


def summarize_parsed(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            [
                {
                    "flow_direction_code": None,
                    "flow_direction_label": None,
                    "rows": 0,
                    "unique_intervals": 0,
                    "missing_quantity_rows": 0,
                    "missing_price_rows": 0,
                    "min_timestamp_utc": None,
                    "max_interval_end_utc": None,
                }
            ]
        )

    rows: list[dict[str, Any]] = []
    for (flow_direction_code, flow_direction_label), group in frame.groupby(
        ["flow_direction_code", "flow_direction_label"], dropna=False
    ):
        rows.append(
            {
                "flow_direction_code": flow_direction_code,
                "flow_direction_label": flow_direction_label,
                "rows": int(group.shape[0]),
                "unique_intervals": int(group[["timestamp_utc", "interval_end_utc"]].drop_duplicates().shape[0]),
                "missing_quantity_rows": int(group["quantity_maw"].isna().sum()),
                "missing_price_rows": int(group["procurement_price_eur"].isna().sum()),
                "min_timestamp_utc": group["timestamp_utc"].min().isoformat() if group["timestamp_utc"].notna().any() else None,
                "max_interval_end_utc": group["interval_end_utc"].max().isoformat()
                if group["interval_end_utc"].notna().any()
                else None,
                "min_local_delivery_date": str(group["target_delivery_local_date"].min()),
                "max_local_delivery_date": str(group["target_delivery_local_date"].max()),
                "reported_resolution_distribution": json.dumps(
                    group["reported_resolution"].fillna("missing").value_counts().sort_index().to_dict(),
                    sort_keys=True,
                ),
                "interval_interpretation_distribution": json.dumps(
                    group["interval_interpretation"].fillna("missing").value_counts().sort_index().to_dict(),
                    sort_keys=True,
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("flow_direction_code").reset_index(drop=True)


def summarize_hourly(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            [
                {
                    "flow_direction_code": None,
                    "flow_direction_label": None,
                    "rows": 0,
                    "unique_hours": 0,
                    "missing_quantity_rows": 0,
                    "missing_price_rows": 0,
                    "incomplete_hours": 0,
                    "min_timestamp_utc": None,
                    "max_interval_end_utc": None,
                }
            ]
        )

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
                "missing_quantity_rows": int(group["quantity_maw"].isna().sum()),
                "missing_price_rows": int(group["procurement_price_eur"].isna().sum()),
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


def build_interval_diagnostics(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "reported_resolution",
                "point_count_in_period",
                "expected_point_count_from_reported_resolution",
                "effective_interval_minutes",
                "interval_interpretation",
                "rows",
            ]
        )

    return (
        frame.groupby(
            [
                "reported_resolution",
                "point_count_in_period",
                "expected_point_count_from_reported_resolution",
                "effective_interval_minutes",
                "interval_interpretation",
            ],
            dropna=False,
            as_index=False,
        )
        .size()
        .rename(columns={"size": "rows"})
        .sort_values(
            [
                "reported_resolution",
                "point_count_in_period",
                "effective_interval_minutes",
                "interval_interpretation",
            ]
        )
        .reset_index(drop=True)
    )


def write_outputs(
    output_root: Path,
    parsed_long: pd.DataFrame,
    hourly_long: pd.DataFrame,
    hourly_wide: pd.DataFrame,
    member_summary: pd.DataFrame,
    archive_summary: pd.DataFrame,
    parse_errors: pd.DataFrame,
    parsed_summary: pd.DataFrame,
    hourly_summary: pd.DataFrame,
    interval_diagnostics: pd.DataFrame,
    duplicates_removed: pd.DataFrame,
) -> dict[str, str]:
    family_root = output_root / OUTPUT_SUBDIR
    parsed_dir = family_root / "parsed"
    hourly_dir = family_root / "hourly"
    diagnostics_dir = family_root / "diagnostics"

    parsed_dir.mkdir(parents=True, exist_ok=True)
    hourly_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    parsed_long_path = parsed_dir / f"{DATASET_NAME}_long.csv"
    hourly_long_path = hourly_dir / f"{DATASET_NAME}_hourly_long.csv"
    hourly_wide_path = hourly_dir / f"{DATASET_NAME}_hourly_wide.csv"
    member_summary_path = diagnostics_dir / "member_parse_summary.csv"
    archive_summary_path = diagnostics_dir / "archive_summary.csv"
    parse_errors_path = diagnostics_dir / "parse_errors.csv"
    parsed_summary_path = diagnostics_dir / "parsed_summary.csv"
    hourly_summary_path = diagnostics_dir / "hourly_summary.csv"
    interval_diagnostics_path = diagnostics_dir / "interval_diagnostics.csv"
    duplicates_removed_path = diagnostics_dir / "duplicate_rows_removed.csv"

    parsed_long.to_csv(parsed_long_path, index=False)
    hourly_long.to_csv(hourly_long_path, index=False)
    hourly_wide.to_csv(hourly_wide_path, index=False)
    member_summary.to_csv(member_summary_path, index=False)
    archive_summary.to_csv(archive_summary_path, index=False)
    parse_errors.to_csv(parse_errors_path, index=False)
    parsed_summary.to_csv(parsed_summary_path, index=False)
    hourly_summary.to_csv(hourly_summary_path, index=False)
    interval_diagnostics.to_csv(interval_diagnostics_path, index=False)
    duplicates_removed.to_csv(duplicates_removed_path, index=False)

    metadata = {
        "dataset": DATASET_NAME,
        "market": MARKET,
        "market_timezone_for_reporting": MARKET_TIMEZONE,
        "raw_input_dir": str(Path("data/00_Raw") / RAW_SUBDIR),
        "output_dir": str(Path("data/01_cleaned") / OUTPUT_SUBDIR),
        "known_at_rule": KNOWN_AT_RULE,
        "notes": [
            "Timestamps are stored in UTC. target_delivery_local_date and target_hour_local are Europe/Amsterdam reporting helpers.",
            "Single-point periods are treated as covering the full reported series period. This keeps daily contracts intact even when 2025 files report PT15M resolution with one point for a full-day period.",
            "Boundary duplicates from overlapping archive pages are deduplicated by keeping the latest created_datetime_utc/source member.",
            "The dataset carries both contracted volume (quantity_maw) and procurement_price_eur for each direction.",
        ],
        "code_labels": {
            "document_type": DOCUMENT_TYPE_LABELS,
            "business_type": BUSINESS_TYPE_LABELS,
            "contract_type": CONTRACT_TYPE_LABELS,
            "reserve_source": RESERVE_SOURCE_LABELS,
            "flow_direction": FLOW_DIRECTION_LABELS,
            "price_category": PRICE_CATEGORY_LABELS,
        },
        "parsed_long_path": str(parsed_long_path),
        "hourly_long_path": str(hourly_long_path),
        "hourly_wide_path": str(hourly_wide_path),
        "member_summary_path": str(member_summary_path),
        "archive_summary_path": str(archive_summary_path),
        "parse_errors_path": str(parse_errors_path),
        "parsed_summary_path": str(parsed_summary_path),
        "hourly_summary_path": str(hourly_summary_path),
        "interval_diagnostics_path": str(interval_diagnostics_path),
        "duplicate_rows_removed_path": str(duplicates_removed_path),
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

    parsed_long_raw, member_summary, archive_summary, parse_errors = parse_archives(raw_dir)
    parsed_long, duplicates_removed = deduplicate_rows(parsed_long_raw)
    parsed_long = parsed_long.reset_index(drop=True)

    hourly_long = aggregate_hourly(parsed_long)
    hourly_wide = build_hourly_wide(hourly_long)

    parsed_summary = summarize_parsed(parsed_long)
    hourly_summary = summarize_hourly(hourly_long)
    interval_diagnostics = build_interval_diagnostics(parsed_long)
    metadata = write_outputs(
        output_root=args.output_root,
        parsed_long=parsed_long,
        hourly_long=hourly_long,
        hourly_wide=hourly_wide,
        member_summary=member_summary,
        archive_summary=archive_summary,
        parse_errors=parse_errors,
        parsed_summary=parsed_summary,
        hourly_summary=hourly_summary,
        interval_diagnostics=interval_diagnostics,
        duplicates_removed=duplicates_removed,
    )

    print(f"Wrote parsed long table to {metadata['parsed_long_path']}")
    print(f"Wrote hourly long table to {metadata['hourly_long_path']}")
    print(f"Wrote hourly wide table to {metadata['hourly_wide_path']}")
    print(f"Removed {len(duplicates_removed)} duplicate boundary rows")


if __name__ == "__main__":
    main()
