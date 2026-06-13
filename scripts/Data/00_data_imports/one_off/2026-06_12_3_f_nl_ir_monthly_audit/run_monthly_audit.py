from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[5]
DOWNLOADER_PATH = REPO_ROOT / "scripts" / "Data" / "00_data_imports" / "API_GETS.py"
CLEANER_PATH = REPO_ROOT / "scripts" / "Data" / "01_cleaning" / "procured_balancing_capacity_pipeline.py"

RAW_PROBE_DIR = REPO_ROOT / "data" / "00_Raw" / "ENTSOE" / "12_3_F_NL_IR" / "probes" / "monthly_scan_2022_2025"
INTERMEDIATE_DIR = REPO_ROOT / "data" / "02_intermediate" / "02_Balancing_mFRR_IR" / "IR_Capacity"
MANIFEST_PATH = INTERMEDIATE_DIR / "12_3_f_nl_ir_availability_manifest.csv"


@dataclass
class MonthResult:
    year: int
    month: int
    period_start_utc: str
    period_end_utc: str
    status: str
    response_type: str
    offset_count: int
    raw_file_count: int
    raw_total_size_bytes: int
    parsed_row_count: int
    daily_direction_count: int
    first_delivery_start_utc: str | None
    last_delivery_end_utc: str | None
    error_message_short: str
    notes: str


def load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


downloader = load_module(DOWNLOADER_PATH, "entsoe_api_gets_monthly_audit")
cleaner = load_module(CLEANER_PATH, "procured_balancing_capacity_monthly_audit")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded monthly audit for 12_3_f_nl_ir.")
    parser.add_argument("--start", default="2022-01", help="Inclusive start month, format YYYY-MM.")
    parser.add_argument("--end", default="2025-12", help="Inclusive end month, format YYYY-MM.")
    parser.add_argument("--retry-limit", type=int, default=3, help="Retries for transient API failures.")
    parser.add_argument("--max-pages-per-month", type=int, default=200, help="Safety cap for pagination.")
    parser.add_argument("--write-manifest", action="store_true", help="Write compact availability manifest CSV.")
    return parser.parse_args()


def month_start(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m").replace(tzinfo=timezone.utc)


def month_iter(start_ym: str, end_ym: str):
    current = month_start(start_ym)
    end = month_start(end_ym)
    while current <= end:
        if current.month == 12:
            nxt = current.replace(year=current.year + 1, month=1)
        else:
            nxt = current.replace(month=current.month + 1)
        yield current, nxt
        current = nxt


def compact_error(exc: Exception) -> str:
    message = str(exc).strip().replace("\r", " ").replace("\n", " ")
    return message[:240]


def save_payload(target_dir: Path, year: int, month: int, offset: int, extension: str, payload: bytes) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"12_3_f_nl_ir_{year:04d}_{month:02d}_offset_{offset:04d}.{extension}"
    target.write_bytes(payload)
    return target


def retrieve_month(
    target_dir: Path,
    year: int,
    month: int,
    period_start: str,
    period_end: str,
    retry_limit: int,
    max_pages_per_month: int,
) -> MonthResult:
    token = downloader.get_token()
    config = downloader.DATASETS["12_3_f_nl_ir"]

    offset = 0
    pages_saved = 0
    raw_total_size_bytes = 0
    response_types: list[str] = []
    seen_signatures: set[str] = set()
    notes: list[str] = []

    for _page in range(max_pages_per_month):
        params = {
            "securityToken": token,
            "periodStart": period_start,
            "periodEnd": period_end,
            "offset": str(offset),
            **config.params,
        }

        payload: bytes | None = None
        error_text = ""

        for attempt in range(1, retry_limit + 1):
            try:
                payload = downloader.fetch_payload(params)
                break
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                reason = downloader.extract_reason_text(body) or f"HTTP {exc.code}"
                error_text = reason
                if exc.code == 400:
                    if "No matching data found" in body:
                        return MonthResult(
                            year=year,
                            month=month,
                            period_start_utc=period_start,
                            period_end_utc=period_end,
                            status="empty_no_matching_data",
                            response_type="xml_reason",
                            offset_count=0,
                            raw_file_count=0,
                            raw_total_size_bytes=0,
                            parsed_row_count=0,
                            daily_direction_count=0,
                            first_delivery_start_utc=None,
                            last_delivery_end_utc=None,
                            error_message_short="",
                            notes="no matching data on first page",
                        )
                    return MonthResult(
                        year=year,
                        month=month,
                        period_start_utc=period_start,
                        period_end_utc=period_end,
                        status="api_error" if pages_saved == 0 else "partial_download",
                        response_type="xml_reason",
                        offset_count=pages_saved,
                        raw_file_count=pages_saved,
                        raw_total_size_bytes=raw_total_size_bytes,
                        parsed_row_count=0,
                        daily_direction_count=0,
                        first_delivery_start_utc=None,
                        last_delivery_end_utc=None,
                        error_message_short=reason[:240],
                        notes="http_400",
                    )
                if 500 <= exc.code < 600 and attempt < retry_limit:
                    continue
                return MonthResult(
                    year=year,
                    month=month,
                    period_start_utc=period_start,
                    period_end_utc=period_end,
                    status="api_error" if pages_saved == 0 else "partial_download",
                    response_type="unknown",
                    offset_count=pages_saved,
                    raw_file_count=pages_saved,
                    raw_total_size_bytes=raw_total_size_bytes,
                    parsed_row_count=0,
                    daily_direction_count=0,
                    first_delivery_start_utc=None,
                    last_delivery_end_utc=None,
                    error_message_short=reason[:240],
                    notes=f"http_{exc.code}",
                )
            except (TimeoutError, socket.timeout, URLError) as exc:
                error_text = compact_error(exc)
                if attempt < retry_limit:
                    continue
                return MonthResult(
                    year=year,
                    month=month,
                    period_start_utc=period_start,
                    period_end_utc=period_end,
                    status="downloader_error" if pages_saved == 0 else "partial_download",
                    response_type="unknown",
                    offset_count=pages_saved,
                    raw_file_count=pages_saved,
                    raw_total_size_bytes=raw_total_size_bytes,
                    parsed_row_count=0,
                    daily_direction_count=0,
                    first_delivery_start_utc=None,
                    last_delivery_end_utc=None,
                    error_message_short=error_text,
                    notes="network_or_timeout",
                )

        if payload is None:
            return MonthResult(
                year=year,
                month=month,
                period_start_utc=period_start,
                period_end_utc=period_end,
                status="inconclusive" if pages_saved == 0 else "partial_download",
                response_type="unknown",
                offset_count=pages_saved,
                raw_file_count=pages_saved,
                raw_total_size_bytes=raw_total_size_bytes,
                parsed_row_count=0,
                daily_direction_count=0,
                first_delivery_start_utc=None,
                last_delivery_end_utc=None,
                error_message_short=error_text[:240],
                notes="payload_missing_after_retries",
            )

        xml_docs = downloader.extract_xml_documents(payload)
        signature = downloader.normalized_docs_signature(xml_docs)
        if signature in seen_signatures:
            notes.append(f"duplicate_page_at_offset_{offset}")
            break
        seen_signatures.add(signature)

        if downloader.contains_no_matching_data(xml_docs):
            if pages_saved == 0:
                return MonthResult(
                    year=year,
                    month=month,
                    period_start_utc=period_start,
                    period_end_utc=period_end,
                    status="empty_no_matching_data",
                    response_type="xml_reason",
                    offset_count=0,
                    raw_file_count=0,
                    raw_total_size_bytes=0,
                    parsed_row_count=0,
                    daily_direction_count=0,
                    first_delivery_start_utc=None,
                    last_delivery_end_utc=None,
                    error_message_short="",
                    notes="no matching data",
                )
            break

        if downloader.contains_entsoe_reason_error(xml_docs):
            reason = downloader.extract_reason_text(xml_docs[0]) if xml_docs else "ENTSO-E reason error"
            return MonthResult(
                year=year,
                month=month,
                period_start_utc=period_start,
                period_end_utc=period_end,
                status="api_error" if pages_saved == 0 else "partial_download",
                response_type="xml_reason",
                offset_count=pages_saved,
                raw_file_count=pages_saved,
                raw_total_size_bytes=raw_total_size_bytes,
                parsed_row_count=0,
                daily_direction_count=0,
                first_delivery_start_utc=None,
                last_delivery_end_utc=None,
                error_message_short=reason[:240],
                notes="reason_block",
            )

        series_count = downloader.total_time_series_count(xml_docs)
        if series_count == 0:
            if pages_saved == 0:
                return MonthResult(
                    year=year,
                    month=month,
                    period_start_utc=period_start,
                    period_end_utc=period_end,
                    status="empty_no_matching_data",
                    response_type="xml",
                    offset_count=0,
                    raw_file_count=0,
                    raw_total_size_bytes=0,
                    parsed_row_count=0,
                    daily_direction_count=0,
                    first_delivery_start_utc=None,
                    last_delivery_end_utc=None,
                    error_message_short="",
                    notes="no_timeseries",
                )
            notes.append(f"no_timeseries_after_offset_{offset}")
            break

        extension = "zip" if downloader.is_zip_payload(payload) else "xml"
        save_payload(target_dir, year, month, offset, extension, payload)
        pages_saved += 1
        raw_total_size_bytes += len(payload)
        response_types.append(extension)

        if series_count < config.page_size:
            break
        offset += config.page_size
    else:
        return MonthResult(
            year=year,
            month=month,
            period_start_utc=period_start,
            period_end_utc=period_end,
            status="partial_download",
            response_type="mixed" if len(set(response_types)) > 1 else (response_types[0] if response_types else "unknown"),
            offset_count=pages_saved,
            raw_file_count=pages_saved,
            raw_total_size_bytes=raw_total_size_bytes,
            parsed_row_count=0,
            daily_direction_count=0,
            first_delivery_start_utc=None,
            last_delivery_end_utc=None,
            error_message_short="max_pages_per_month_reached",
            notes="pagination_cap_hit",
        )

    if pages_saved == 0:
        return MonthResult(
            year=year,
            month=month,
            period_start_utc=period_start,
            period_end_utc=period_end,
            status="inconclusive",
            response_type="unknown",
            offset_count=0,
            raw_file_count=0,
            raw_total_size_bytes=0,
            parsed_row_count=0,
            daily_direction_count=0,
            first_delivery_start_utc=None,
            last_delivery_end_utc=None,
            error_message_short="",
            notes="no_pages_saved_without_explicit_empty",
        )

    return MonthResult(
        year=year,
        month=month,
        period_start_utc=period_start,
        period_end_utc=period_end,
        status="available_downloaded",
        response_type="mixed" if len(set(response_types)) > 1 else response_types[0],
        offset_count=pages_saved,
        raw_file_count=pages_saved,
        raw_total_size_bytes=raw_total_size_bytes,
        parsed_row_count=0,
        daily_direction_count=0,
        first_delivery_start_utc=None,
        last_delivery_end_utc=None,
        error_message_short="",
        notes=";".join(notes),
    )


def compute_month_parse_stats(offers_long: pd.DataFrame, daily_long: pd.DataFrame, year: int, month: int) -> dict[str, Any]:
    if offers_long.empty:
        return {
            "parsed_row_count": 0,
            "daily_direction_count": 0,
            "first_delivery_start_utc": None,
            "last_delivery_end_utc": None,
        }

    month_mask = (
        (offers_long["timestamp_utc"].dt.year == year)
        & (offers_long["timestamp_utc"].dt.month == month)
    )
    offers_month = offers_long.loc[month_mask].copy()
    daily_mask = (
        (daily_long["timestamp_utc"].dt.year == year)
        & (daily_long["timestamp_utc"].dt.month == month)
    )
    daily_month = daily_long.loc[daily_mask].copy()

    if offers_month.empty:
        return {
            "parsed_row_count": 0,
            "daily_direction_count": 0,
            "first_delivery_start_utc": None,
            "last_delivery_end_utc": None,
        }

    return {
        "parsed_row_count": int(len(offers_month)),
        "daily_direction_count": int(len(daily_month)),
        "first_delivery_start_utc": offers_month["timestamp_utc"].min().isoformat(),
        "last_delivery_end_utc": offers_month["interval_end_utc"].max().isoformat(),
    }


def build_offer_stack_readiness(offers_long: pd.DataFrame) -> dict[str, Any]:
    group = (
        offers_long.groupby(["timestamp_utc", "flow_direction_label"], dropna=False, as_index=False)
        .agg(
            offer_count=("native_offer_id", "size"),
            total_quantity_maw=("quantity_maw", "sum"),
            max_price=("procurement_price_eur_per_maw", "max"),
            min_price=("procurement_price_eur_per_maw", "min"),
            has_missing_price=("procurement_price_eur_per_maw", lambda s: bool(s.isna().any())),
            has_missing_quantity=("quantity_maw", lambda s: bool(s.isna().any())),
            has_nonpositive_price=("procurement_price_eur_per_maw", lambda s: bool((s <= 0).fillna(False).any())),
            has_negative_price=("procurement_price_eur_per_maw", lambda s: bool((s < 0).fillna(False).any())),
            has_nonpositive_quantity=("quantity_maw", lambda s: bool((s <= 0).fillna(False).any())),
            duplicate_price_quantity_rows=("native_offer_id", lambda s: 0),
        )
    )

    duplicates = (
        offers_long.groupby(["timestamp_utc", "flow_direction_label", "procurement_price_eur_per_maw", "quantity_maw"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    dup_by_group = (
        duplicates[duplicates["n"] > 1]
        .groupby(["timestamp_utc", "flow_direction_label"], as_index=False)
        .agg(duplicate_price_quantity_rows=("n", lambda s: int((s - 1).sum())))
    )
    group = group.drop(columns=["duplicate_price_quantity_rows"]).merge(
        dup_by_group, on=["timestamp_utc", "flow_direction_label"], how="left"
    )
    group["duplicate_price_quantity_rows"] = group["duplicate_price_quantity_rows"].fillna(0).astype(int)
    group["weighted_price"] = (
        offers_long.assign(weighted=offers_long["quantity_maw"] * offers_long["procurement_price_eur_per_maw"])
        .groupby(["timestamp_utc", "flow_direction_label"], dropna=False)["weighted"]
        .sum()
        .reset_index(drop=True)
    )
    group["quantity_weighted_price"] = group["weighted_price"] / group["total_quantity_maw"]
    group["valid_offer_stack"] = (
        (group["offer_count"] > 0)
        & (group["total_quantity_maw"] > 0)
        & (~group["has_missing_price"])
        & (~group["has_missing_quantity"])
    )

    extreme_price_threshold = offers_long["procurement_price_eur_per_maw"].quantile(0.999)
    extreme_groups = (
        offers_long.groupby(["timestamp_utc", "flow_direction_label"], dropna=False)["procurement_price_eur_per_maw"]
        .max()
        .reset_index(name="group_max_price")
    )
    suspicious = group[
        (~group["valid_offer_stack"])
        | group["has_negative_price"]
        | group["has_nonpositive_quantity"]
        | (group["group_max_price"] > extreme_price_threshold if "group_max_price" in group.columns else False)
    ].copy() if False else None

    up_days = set(group.loc[group["flow_direction_label"] == "Up", "timestamp_utc"])
    down_days = set(group.loc[group["flow_direction_label"] == "Down", "timestamp_utc"])

    return {
        "group_df": group,
        "valid_pct": float(group["valid_offer_stack"].mean() * 100) if not group.empty else 0.0,
        "suspicious_count": int((~group["valid_offer_stack"]).sum()),
        "zero_or_negative_price_groups": int((group["has_nonpositive_price"] | group["has_negative_price"]).sum()),
        "zero_or_negative_quantity_groups": int(group["has_nonpositive_quantity"].sum()),
        "duplicate_price_quantity_group_count": int((group["duplicate_price_quantity_rows"] > 0).sum()),
        "up_down_day_match_pct": float((len(up_days & down_days) / len(up_days | down_days) * 100) if (up_days or down_days) else 0.0),
    }


def cross_check_with_17_1_bc(daily_long: pd.DataFrame) -> dict[str, Any]:
    path = REPO_ROOT / "data" / "01_cleaned" / "02_Balancing_mFRR_IR" / "IR Capacity" / "balancing_reserves_under_contract" / "parsed" / "balancing_reserves_under_contract_long.csv"
    if not path.exists():
        return {"matched_rows": 0, "status": "17_1_bc_missing"}

    bc = pd.read_csv(path, parse_dates=["timestamp_utc", "interval_end_utc"])
    bc["timestamp_utc"] = pd.to_datetime(bc["timestamp_utc"], utc=True, errors="coerce")
    bc = bc[
        [
            "timestamp_utc",
            "flow_direction_label",
            "quantity_maw",
            "procurement_price_eur",
            "price_category_label",
        ]
    ].copy()
    bc = bc[bc["price_category_label"] == "Average_bid_price"].copy()

    f = daily_long[
        [
            "timestamp_utc",
            "flow_direction_label",
            "total_quantity_maw",
            "quantity_weighted_price_eur_per_maw",
            "price_max_eur_per_maw",
        ]
    ].copy()
    merged = f.merge(bc, on=["timestamp_utc", "flow_direction_label"], how="inner")
    if merged.empty:
        return {"matched_rows": 0, "status": "no_overlap"}

    merged["mw_diff"] = merged["total_quantity_maw"] - merged["quantity_maw"]
    merged["weighted_price_diff"] = merged["quantity_weighted_price_eur_per_maw"] - merged["procurement_price_eur"]
    merged["max_price_diff"] = merged["price_max_eur_per_maw"] - merged["procurement_price_eur"]

    return {
        "matched_rows": int(len(merged)),
        "mean_abs_mw_diff": float(merged["mw_diff"].abs().mean()),
        "max_abs_mw_diff": float(merged["mw_diff"].abs().max()),
        "mean_abs_weighted_price_diff": float(merged["weighted_price_diff"].abs().mean()),
        "mean_abs_max_price_diff": float(merged["max_price_diff"].abs().mean()),
        "weighted_price_corr": float(merged["quantity_weighted_price_eur_per_maw"].corr(merged["procurement_price_eur"])),
        "max_price_corr": float(merged["price_max_eur_per_maw"].corr(merged["procurement_price_eur"])),
        "status": "ok",
    }


def main() -> int:
    args = parse_args()

    month_results: list[MonthResult] = []
    for start_dt, end_dt in month_iter(args.start, args.end):
        result = retrieve_month(
            target_dir=RAW_PROBE_DIR,
            year=start_dt.year,
            month=start_dt.month,
            period_start=start_dt.strftime("%Y%m%d%H%M"),
            period_end=end_dt.strftime("%Y%m%d%H%M"),
            retry_limit=args.retry_limit,
            max_pages_per_month=args.max_pages_per_month,
        )
        month_results.append(result)
        print(f"{start_dt.strftime('%Y-%m')}: {result.status} ({result.raw_file_count} files, {result.offset_count} offsets)")

    available_count = sum(1 for row in month_results if row.status == "available_downloaded")
    if available_count == 0:
        manifest_df = pd.DataFrame([row.__dict__ for row in month_results])
        if args.write_manifest:
            INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
            manifest_df.to_csv(MANIFEST_PATH, index=False)
        print(json.dumps({"months_attempted": len(month_results), "months_available": 0}, indent=2))
        return 0

    offers_raw, archive_summary, parse_errors = cleaner.parse_archives(RAW_PROBE_DIR)
    offers_long = cleaner.build_offer_stack(offers_raw)
    daily_long = cleaner.build_daily_direction_summary(offers_long)
    daily_wide = cleaner.build_daily_direction_wide(daily_long)
    hourly_long = cleaner.build_hourly_direction_summary(daily_long)
    hourly_wide = cleaner.build_hourly_direction_wide(hourly_long)

    offers_summary = cleaner.summarize_offers(offers_long)
    daily_summary = cleaner.summarize_daily(daily_long)
    hourly_summary = cleaner.summarize_hourly(hourly_long)
    ambiguous_duplicate_content = cleaner.build_ambiguous_duplicate_content_summary(offers_long)
    timeseries_mrid_reuse = cleaner.build_timeseries_mrid_reuse_summary(offers_long)

    metadata = cleaner.write_outputs(
        output_root=REPO_ROOT / "data" / "01_cleaned",
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
    metadata_path = Path(metadata["metadata_path"])
    metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata_payload["raw_input_dir"] = str(RAW_PROBE_DIR.relative_to(REPO_ROOT))
    metadata_payload["notes"].append("Cleaned outputs were rebuilt from the bounded monthly probe directory for the 2022-2025 availability audit.")
    metadata_path.write_text(json.dumps(metadata_payload, indent=2), encoding="utf-8")

    result_rows: list[dict[str, Any]] = []
    for row in month_results:
        row_dict = row.__dict__.copy()
        if row.status == "available_downloaded":
            stats = compute_month_parse_stats(offers_long, daily_long, row.year, row.month)
            row_dict.update(stats)
            if stats["parsed_row_count"] == 0:
                row_dict["status"] = "parser_error"
                row_dict["error_message_short"] = "downloaded raw files but parsed_row_count=0"
        result_rows.append(row_dict)

    manifest_df = pd.DataFrame(result_rows)
    if args.write_manifest:
        INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
        manifest_df.to_csv(MANIFEST_PATH, index=False)

    readiness = build_offer_stack_readiness(offers_long)
    cross_check = cross_check_with_17_1_bc(daily_long)

    summary = {
        "months_attempted": int(len(manifest_df)),
        "months_available": int((manifest_df["status"] == "available_downloaded").sum()),
        "months_empty": int((manifest_df["status"] == "empty_no_matching_data").sum()),
        "months_failed": int((~manifest_df["status"].isin(["available_downloaded", "empty_no_matching_data"])).sum()),
        "first_delivery_start_utc": offers_long["timestamp_utc"].min().isoformat() if not offers_long.empty else None,
        "last_delivery_end_utc": offers_long["interval_end_utc"].max().isoformat() if not offers_long.empty else None,
        "raw_file_count": int(sum(row.raw_file_count for row in month_results)),
        "raw_total_size_bytes": int(sum(row.raw_total_size_bytes for row in month_results)),
        "cleaned_offer_rows": int(len(offers_long)),
        "cleaned_daily_direction_rows": int(len(daily_long)),
        "offer_stack_valid_pct": readiness["valid_pct"],
        "cross_check_status": cross_check["status"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
