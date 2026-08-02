from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_ROOT = REPO_ROOT / "data" / "00_Raw" / "DA_Prices_quarterly" / "NL" / "A01_Day_Ahead_Market"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "01_cleaned" / "Day_ahead_prices_quarterly" / "NL"
DEFAULT_DATASET_KEY = "12_1_d_energy_prices_a01_day_ahead_nl"
DEFAULT_MARKET_AREA = "NL"
DEFAULT_LOCAL_TIMEZONE = "Europe/Amsterdam"
DEFAULT_CUTOFF_LOCAL_DATE = date(2025, 10, 1)
DEFAULT_CHUNK_DAYS = 31
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES_PER_CHUNK = 50
DEFAULT_LATEST_FULL_DAY_LAG_DAYS = 1
RAW_FILENAME_PREFIX = "nl_da_prices_quarterly"
STATE_FILE_NAME = "update_state.json"
RUN_METADATA_FILE_NAME = "run_metadata.json"
QUARTERLY_FILE_NAME = "da_prices_NL_quarterly.csv"
QUARTERLY_STEP_MINUTES = 15
XML_TIME_TEXT_PATTERN = re.compile(
    r"<(?:[A-Za-z0-9_]+:)?(?:start|end|createdDateTime)>([^<]+)</(?:[A-Za-z0-9_]+:)?(?:start|end|createdDateTime)>"
)


def _load_module(module_name: str, path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module '{module_name}' from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


ENTSOE_API = _load_module(
    "thesis_entsoe_api_gets",
    REPO_ROOT / "scripts" / "Data" / "00_data_imports" / "API_GETS.py",
)
DA_CLEANING = _load_module(
    "thesis_day_ahead_prices_pipeline",
    REPO_ROOT / "scripts" / "Data" / "01_cleaning" / "day_ahead_prices_pipeline.py",
)


@dataclass(frozen=True)
class QuarterlyNLPipelineConfig:
    raw_root: Path
    output_root: Path
    dataset_key: str = DEFAULT_DATASET_KEY
    market_area: str = DEFAULT_MARKET_AREA
    local_timezone: str = DEFAULT_LOCAL_TIMEZONE
    cutoff_local_date: date = DEFAULT_CUTOFF_LOCAL_DATE
    chunk_days: int = DEFAULT_CHUNK_DAYS
    max_pages_per_chunk: int = DEFAULT_MAX_PAGES_PER_CHUNK
    latest_full_day_lag_days: int = DEFAULT_LATEST_FULL_DAY_LAG_DAYS

    @property
    def diagnostics_dir(self) -> Path:
        return self.output_root / "diagnostics"

    @property
    def quarterly_dir(self) -> Path:
        return self.output_root / "quarterly"

    @property
    def quarterly_csv(self) -> Path:
        return self.quarterly_dir / QUARTERLY_FILE_NAME

    @property
    def state_path(self) -> Path:
        return self.diagnostics_dir / STATE_FILE_NAME

    @property
    def run_metadata_path(self) -> Path:
        return self.diagnostics_dir / RUN_METADATA_FILE_NAME


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO local date: {value}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dedicated NL quarter-hour day-ahead price pipeline. Downloads quarter-hour-capable raw A01 data into a "
            "separate raw folder, rebuilds a separate cleaned quarterly dataset, and keeps the hourly workflow untouched."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("full-refresh", "incremental"),
        default="incremental",
        help="Import the full cutoff..latest-full-day window or only complete local delivery days not yet imported.",
    )
    parser.add_argument(
        "--start-local-date",
        type=parse_date,
        help="Optional local delivery date override for the first imported day.",
    )
    parser.add_argument(
        "--end-local-date",
        type=parse_date,
        help="Optional local delivery date override for the last imported day. Must be a full local day.",
    )
    parser.add_argument(
        "--cutoff-local-date",
        type=parse_date,
        default=DEFAULT_CUTOFF_LOCAL_DATE,
        help="Local delivery date from which the official quarter-hour NL DA dataset starts.",
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=DEFAULT_RAW_ROOT,
        help="Dedicated raw folder for the isolated NL quarter-hour DA import.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Dedicated cleaned output root for the isolated NL quarter-hour DA dataset.",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=DEFAULT_CHUNK_DAYS,
        help="Number of local delivery days per API request chunk.",
    )
    parser.add_argument(
        "--max-pages-per-chunk",
        type=int,
        default=DEFAULT_MAX_PAGES_PER_CHUNK,
        help="Safety cap for API pagination within one request chunk.",
    )
    parser.add_argument(
        "--latest-full-day-lag-days",
        type=int,
        default=DEFAULT_LATEST_FULL_DAY_LAG_DAYS,
        help="How many local days behind 'today' count as the latest fully completed delivery day.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Reuse the existing dedicated raw folder and only rebuild the cleaned quarterly output.",
    )
    return parser.parse_args()


def local_midnight_to_utc(local_day: date, timezone: str) -> pd.Timestamp:
    local_ts = pd.Timestamp(datetime.combine(local_day, time.min)).tz_localize(timezone)
    return local_ts.tz_convert("UTC")


def latest_full_local_day(timezone: str, lag_days: int) -> date:
    if lag_days < 0:
        raise ValueError("latest_full_day_lag_days must be non-negative")
    now_local = pd.Timestamp.now(tz=timezone)
    return (now_local - pd.Timedelta(days=lag_days)).date()


def expected_quarterhours_for_local_day(local_day: date, timezone: str) -> int:
    start_utc = local_midnight_to_utc(local_day, timezone)
    end_utc = local_midnight_to_utc(local_day + timedelta(days=1), timezone)
    return int((end_utc - start_utc) / pd.Timedelta(minutes=QUARTERLY_STEP_MINUTES))


def iter_local_day_chunks(start_local_day: date, end_local_day: date, chunk_days: int) -> list[tuple[date, date]]:
    if chunk_days <= 0:
        raise ValueError("chunk_days must be positive")
    if end_local_day < start_local_day:
        return []
    chunks: list[tuple[date, date]] = []
    cursor = start_local_day
    while cursor <= end_local_day:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_local_day)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def utc_period_strings_for_local_days(
    start_local_day: date,
    end_local_day: date,
    timezone: str,
) -> tuple[str, str, pd.Timestamp, pd.Timestamp]:
    start_utc = local_midnight_to_utc(start_local_day, timezone)
    end_utc_exclusive = local_midnight_to_utc(end_local_day + timedelta(days=1), timezone)
    return (
        start_utc.strftime("%Y%m%d%H%M"),
        end_utc_exclusive.strftime("%Y%m%d%H%M"),
        start_utc,
        end_utc_exclusive,
    )


def end_timestamp_inclusive_for_local_day(end_local_day: date, timezone: str) -> pd.Timestamp:
    end_utc_exclusive = local_midnight_to_utc(end_local_day + timedelta(days=1), timezone)
    return end_utc_exclusive - pd.Timedelta(minutes=QUARTERLY_STEP_MINUTES)


def read_state_anchor(state_path: Path) -> date | None:
    if not state_path.exists():
        return None
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    value = payload.get("latest_complete_delivery_local_date")
    if not value:
        return None
    return date.fromisoformat(str(value))


def infer_latest_complete_local_day_from_cleaned(cleaned_csv: Path, timezone: str) -> date | None:
    if not cleaned_csv.exists():
        return None
    frame = pd.read_csv(cleaned_csv, usecols=["timestamp_utc"])
    if frame.empty:
        return None
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce").dropna()
    if timestamps.empty:
        return None
    local_dates = timestamps.dt.tz_convert(timezone).dt.date
    counts = local_dates.value_counts().sort_index()
    latest_complete: date | None = None
    for local_day, count in counts.items():
        if int(count) == expected_quarterhours_for_local_day(local_day, timezone):
            latest_complete = local_day
    return latest_complete


def determine_incremental_start_local_day(config: QuarterlyNLPipelineConfig) -> date:
    state_anchor = read_state_anchor(config.state_path)
    if state_anchor is not None:
        return state_anchor + timedelta(days=1)
    inferred_anchor = infer_latest_complete_local_day_from_cleaned(config.quarterly_csv, config.local_timezone)
    if inferred_anchor is not None:
        return inferred_anchor + timedelta(days=1)
    return config.cutoff_local_date


def resolve_import_window(
    mode: str,
    config: QuarterlyNLPipelineConfig,
    *,
    start_local_date_override: date | None,
    end_local_date_override: date | None,
) -> tuple[date, date, date]:
    latest_complete_day = latest_full_local_day(config.local_timezone, config.latest_full_day_lag_days)
    if end_local_date_override is not None and end_local_date_override > latest_complete_day:
        raise ValueError(
            f"Requested end_local_date {end_local_date_override.isoformat()} exceeds the latest fully completed local "
            f"day {latest_complete_day.isoformat()}."
        )

    end_local_day = end_local_date_override or latest_complete_day
    if mode == "full-refresh":
        start_local_day = start_local_date_override or config.cutoff_local_date
    elif mode == "incremental":
        start_local_day = start_local_date_override or determine_incremental_start_local_day(config)
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    if start_local_day < config.cutoff_local_date:
        start_local_day = config.cutoff_local_date
    return start_local_day, end_local_day, latest_complete_day


def verify_sample_source_timestamps_are_utc(xml_paths: list[Path]) -> dict[str, Any]:
    samples: list[str] = []
    for xml_path in xml_paths[:3]:
        text = xml_path.read_text(encoding="utf-8", errors="replace")
        samples.extend(XML_TIME_TEXT_PATTERN.findall(text)[:6])
    samples = [str(value).strip() for value in samples if str(value).strip()]
    explicit_timezone = [value.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", value) is not None for value in samples]
    parsed = pd.to_datetime(samples, utc=False, errors="coerce") if samples else pd.Series(dtype="datetime64[ns]")
    offsets_zero = True
    for timestamp in parsed.tolist():
        if pd.isna(timestamp):
            offsets_zero = False
            break
        offset = timestamp.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            offsets_zero = False
            break
    return {
        "sample_count": len(samples),
        "sample_values": samples[:6],
        "all_samples_have_explicit_timezone": bool(samples) and all(explicit_timezone),
        "all_sample_offsets_are_zero": bool(samples) and offsets_zero,
        "verdict": "UTC_CONFIRMED" if samples and all(explicit_timezone) and offsets_zero else "UTC_NOT_CONFIRMED",
        "note": (
            "The ENTSO-E A44 day-ahead XML carries explicit UTC timestamp strings in the document and period time "
            "intervals. The quarterly cleaner stores timestamp_utc in UTC and keeps local time only in diagnostics."
        ),
    }


def build_download_params(dataset_key: str, token: str, *, period_start: str, period_end: str, offset: int) -> dict[str, str]:
    dataset = ENTSOE_API.DATASETS[dataset_key]
    return {
        "securityToken": token,
        "periodStart": period_start,
        "periodEnd": period_end,
        "offset": str(offset),
        **dataset.params,
    }


def save_xml_documents(
    xml_docs: list[str],
    *,
    raw_root: Path,
    chunk_start_local_day: date,
    chunk_end_local_day: date,
    offset: int,
) -> list[Path]:
    saved_paths: list[Path] = []
    base_name = (
        f"{RAW_FILENAME_PREFIX}_{chunk_start_local_day.strftime('%Y%m%d')}_{chunk_end_local_day.strftime('%Y%m%d')}"
        f"_offset_{offset:04d}"
    )
    for doc_idx, xml_text in enumerate(xml_docs, start=1):
        suffix = f"_doc_{doc_idx:02d}" if len(xml_docs) > 1 else ""
        target = raw_root / f"{base_name}{suffix}.xml"
        target.write_text(xml_text, encoding="utf-8")
        saved_paths.append(target)
    return saved_paths


def download_raw_range(
    config: QuarterlyNLPipelineConfig,
    *,
    start_local_day: date,
    end_local_day: date,
) -> dict[str, Any]:
    config.raw_root.mkdir(parents=True, exist_ok=True)
    token = ENTSOE_API.get_token()
    total_saved_files = 0
    total_saved_pages = 0
    total_series_count = 0
    chunk_records: list[dict[str, Any]] = []
    dataset = ENTSOE_API.DATASETS[config.dataset_key]

    for chunk_start_local_day, chunk_end_local_day in iter_local_day_chunks(
        start_local_day,
        end_local_day,
        config.chunk_days,
    ):
        period_start, period_end, chunk_start_utc, chunk_end_utc_exclusive = utc_period_strings_for_local_days(
            chunk_start_local_day,
            chunk_end_local_day,
            config.local_timezone,
        )
        print(
            "Downloading NL quarter-hour DA chunk "
            f"{chunk_start_local_day.isoformat()}..{chunk_end_local_day.isoformat()} "
            f"(UTC {chunk_start_utc.isoformat()} .. {chunk_end_utc_exclusive.isoformat()})"
        )

        offset = 0
        pages_downloaded = 0
        seen_payload_hashes: set[str] = set()
        chunk_saved_files = 0
        chunk_series_count = 0
        chunk_file_paths: list[str] = []

        while pages_downloaded < config.max_pages_per_chunk:
            params = build_download_params(
                config.dataset_key,
                token,
                period_start=period_start,
                period_end=period_end,
                offset=offset,
            )
            payload: bytes | None = None
            for attempt in range(1, 4):
                try:
                    payload = ENTSOE_API.fetch_payload(params)
                    break
                except HTTPError as exc:
                    body = exc.read().decode("utf-8", errors="replace")
                    reason = ENTSOE_API.extract_reason_text(body)
                    if exc.code == 400:
                        print(
                            f"  Stopped at offset {offset} (HTTP 400)"
                            f"{': ' + reason if reason else ''}."
                        )
                        break
                    if 500 <= exc.code < 600 and attempt < 3:
                        print(f"  Temporary HTTP {exc.code} at offset {offset}, retry {attempt}/3.")
                        continue
                    raise RuntimeError(
                        f"HTTP {exc.code} at offset {offset}. {reason or 'No reason provided.'}"
                    ) from exc
                except (TimeoutError, socket.timeout, URLError):
                    if attempt < 3:
                        print(f"  Temporary network/timeout at offset {offset}, retry {attempt}/3.")
                        continue
                    print(f"  Timeout/network issue at offset {offset}. Stopping this chunk.")
                    break

            if payload is None:
                break

            xml_docs = ENTSOE_API.extract_xml_documents(payload)
            docs_signature = ENTSOE_API.normalized_docs_signature(xml_docs)
            if docs_signature in seen_payload_hashes:
                print(f"  Duplicate page detected at offset {offset}. Stopping this chunk.")
                break
            seen_payload_hashes.add(docs_signature)

            if ENTSOE_API.contains_no_matching_data(xml_docs):
                if pages_downloaded == 0:
                    print("  No data found for this chunk.")
                break

            if ENTSOE_API.contains_entsoe_reason_error(xml_docs):
                raise RuntimeError(
                    "ENTSO-E returned an API error for the NL quarter-hour DA request at "
                    f"offset {offset}."
                )

            series_count = ENTSOE_API.total_time_series_count(xml_docs)
            if series_count == 0:
                print(f"  No TimeSeries returned at offset {offset}.")
                break

            saved_paths = save_xml_documents(
                xml_docs,
                raw_root=config.raw_root,
                chunk_start_local_day=chunk_start_local_day,
                chunk_end_local_day=chunk_end_local_day,
                offset=offset,
            )
            pages_downloaded += 1
            chunk_saved_files += len(saved_paths)
            chunk_series_count += int(series_count)
            chunk_file_paths.extend(str(path) for path in saved_paths)
            print(
                f"  Saved {len(saved_paths)} XML file(s) for offset {offset} ({series_count} TimeSeries, "
                f"dataset page size {dataset.page_size})."
            )

            if series_count < dataset.page_size:
                break
            offset += dataset.page_size
        else:
            raise RuntimeError(
                f"Stopped at max_pages_per_chunk={config.max_pages_per_chunk} for "
                f"{chunk_start_local_day.isoformat()}..{chunk_end_local_day.isoformat()}."
            )

        total_saved_files += chunk_saved_files
        total_saved_pages += pages_downloaded
        total_series_count += chunk_series_count
        chunk_records.append(
            {
                "chunk_start_local_date": chunk_start_local_day.isoformat(),
                "chunk_end_local_date": chunk_end_local_day.isoformat(),
                "chunk_start_utc": chunk_start_utc.isoformat(),
                "chunk_end_utc_exclusive": chunk_end_utc_exclusive.isoformat(),
                "pages_downloaded": int(pages_downloaded),
                "saved_xml_files": int(chunk_saved_files),
                "time_series_count": int(chunk_series_count),
                "saved_files": chunk_file_paths,
            }
        )

    return {
        "raw_root": str(config.raw_root),
        "chunks": chunk_records,
        "saved_xml_files": int(total_saved_files),
        "saved_pages": int(total_saved_pages),
        "time_series_count": int(total_series_count),
    }


def parse_raw_xml_directory(raw_root: Path, region: str) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    xml_files = sorted(raw_root.glob("*.xml"))
    if not xml_files:
        return pd.DataFrame(), [], []

    rows: list[dict[str, Any]] = []
    file_summaries: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []

    for xml_path in xml_files:
        try:
            parsed_rows, file_summary = DA_CLEANING.parse_single_xml(region, xml_path)
        except Exception as exc:  # pragma: no cover - defensive logging around XML parsing
            parse_errors.append({"source_file": xml_path.name, "source_path": str(xml_path), "error": str(exc)})
            continue
        rows.extend(parsed_rows)
        file_summaries.append(file_summary)

    frame = DA_CLEANING.make_region_dataframe(rows)
    return frame, file_summaries, parse_errors


def expand_a03_variable_blocks(frame: pd.DataFrame, *, expected_minutes: int) -> pd.DataFrame:
    """Expand ENTSO-E A03 variable blocks; this is source parsing, not interpolation."""

    if frame.empty or "curve_type" not in frame.columns:
        result = frame.copy()
        result["a03_variable_block_expanded"] = False
        result["a03_source_block_start_utc"] = pd.NaT
        result["a03_expansion_method"] = "not_applicable"
        return result
    working = frame.copy()
    for column in ("timestamp_utc", "period_start_utc", "period_end_utc"):
        working[column] = pd.to_datetime(working[column], utc=True, errors="coerce")
    a03_mask = working["curve_type"].astype(str).str.upper().eq("A03")
    a03 = working[a03_mask].copy()
    other = working[~a03_mask].copy()
    other["a03_variable_block_expanded"] = False
    other["a03_source_block_start_utc"] = pd.NaT
    other["a03_expansion_method"] = "not_applicable"
    if a03.empty:
        return other.sort_values("timestamp_utc").reset_index(drop=True)
    group_candidates = [
        "source_path",
        "document_id",
        "timeseries_index",
        "period_index",
        "period_start_utc",
        "period_end_utc",
        "resolution_minutes",
    ]
    group_columns = [column for column in group_candidates if column in a03.columns]
    if not {"period_start_utc", "period_end_utc"}.issubset(group_columns):
        raise ValueError("A03 expansion requires period_start_utc and period_end_utc")
    expanded_rows: list[dict[str, Any]] = []
    step = pd.Timedelta(minutes=int(expected_minutes))
    for _, group in a03.groupby(group_columns, dropna=False, sort=False):
        ordered = group.dropna(subset=["timestamp_utc", "period_start_utc", "period_end_utc"]).sort_values("timestamp_utc")
        if ordered.empty:
            continue
        period_start = pd.Timestamp(ordered["period_start_utc"].iloc[0])
        period_end = pd.Timestamp(ordered["period_end_utc"].iloc[0])
        records = ordered.to_dict(orient="records")
        for index, source_row in enumerate(records):
            block_start = pd.Timestamp(source_row["timestamp_utc"])
            block_end = pd.Timestamp(records[index + 1]["timestamp_utc"]) if index + 1 < len(records) else period_end
            if block_start < period_start or block_end > period_end or block_end <= block_start:
                raise ValueError(f"Invalid A03 block interval {block_start}..{block_end} within {period_start}..{period_end}")
            for timestamp in pd.date_range(block_start, block_end, freq=step, inclusive="left"):
                row = dict(source_row)
                row["a03_source_position"] = source_row.get("position")
                row["timestamp_utc"] = timestamp
                row["position"] = int((timestamp - period_start) / step) + 1
                row["a03_variable_block_expanded"] = bool(timestamp != block_start)
                row["a03_source_block_start_utc"] = block_start
                row["a03_expansion_method"] = "official_curve_type_a03_forward_block"
                expanded_rows.append(row)
    expanded = pd.DataFrame(expanded_rows)
    result = pd.concat([other, expanded], ignore_index=True, sort=False)
    sort_columns = [column for column in ("timestamp_utc", "created_datetime_utc") if column in result.columns]
    return result.sort_values(sort_columns, na_position="last").reset_index(drop=True)


def build_delivery_day_coverage(quarterly_frame: pd.DataFrame, timezone: str) -> pd.DataFrame:
    if quarterly_frame.empty:
        return pd.DataFrame(
            columns=[
                "delivery_local_date",
                "expected_quarterhours",
                "rows_after_fix",
                "observed_non_missing_rows",
                "interpolated_points_count",
                "flagged_missing_points_count",
                "remaining_missing_points_after_fix",
                "is_complete_local_day",
            ]
        )

    work = quarterly_frame.copy()
    work["delivery_local_date"] = work["timestamp_utc"].dt.tz_convert(timezone).dt.date
    rows: list[dict[str, Any]] = []
    for delivery_local_date, group in work.groupby("delivery_local_date", sort=True):
        expected_quarters = expected_quarterhours_for_local_day(delivery_local_date, timezone)
        remaining_missing = int(group["price_eur_per_mwh"].isna().sum())
        rows.append(
            {
                "delivery_local_date": delivery_local_date.isoformat(),
                "expected_quarterhours": int(expected_quarters),
                "rows_after_fix": int(group.shape[0]),
                "observed_non_missing_rows": int(group["price_eur_per_mwh_original"].notna().sum()),
                "interpolated_points_count": int(group["is_interpolated_value"].sum()),
                "flagged_missing_points_count": int(group["is_flagged_missing_value"].sum()),
                "remaining_missing_points_after_fix": remaining_missing,
                "is_complete_local_day": bool(int(group.shape[0]) == int(expected_quarters) and remaining_missing == 0),
            }
        )
    return pd.DataFrame(rows).sort_values("delivery_local_date").reset_index(drop=True)


def write_clean_outputs(
    config: QuarterlyNLPipelineConfig,
    *,
    quarterly_frame: pd.DataFrame,
    diagnostics_summary: pd.DataFrame,
    gap_fix_details: pd.DataFrame,
    xml_file_summary: pd.DataFrame,
    xml_parse_errors: pd.DataFrame,
    delivery_day_coverage: pd.DataFrame,
    run_metadata: dict[str, Any],
    latest_complete_delivery_local_date: date | None,
) -> None:
    config.output_root.mkdir(parents=True, exist_ok=True)
    config.quarterly_dir.mkdir(parents=True, exist_ok=True)
    config.diagnostics_dir.mkdir(parents=True, exist_ok=True)

    quarterly_frame.to_csv(config.quarterly_csv, index=False)
    diagnostics_summary.to_csv(config.diagnostics_dir / "quarterly_diagnostics_summary.csv", index=False)
    gap_fix_details.to_csv(config.diagnostics_dir / "gap_fix_details.csv", index=False)
    xml_file_summary.to_csv(config.diagnostics_dir / "xml_file_summary.csv", index=False)
    xml_parse_errors.to_csv(config.diagnostics_dir / "xml_parse_errors.csv", index=False)
    delivery_day_coverage.to_csv(config.diagnostics_dir / "delivery_day_coverage.csv", index=False)
    config.run_metadata_path.write_text(json.dumps(run_metadata, indent=2), encoding="utf-8")

    state_payload = {
        "market_area": config.market_area,
        "local_timezone": config.local_timezone,
        "cutoff_local_date": config.cutoff_local_date.isoformat(),
        "latest_complete_delivery_local_date": (
            latest_complete_delivery_local_date.isoformat() if latest_complete_delivery_local_date is not None else None
        ),
        "latest_timestamp_utc": (
            pd.Timestamp(quarterly_frame["timestamp_utc"].max()).isoformat() if not quarterly_frame.empty else None
        ),
        "quarterly_rows": int(quarterly_frame.shape[0]),
        "updated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    config.state_path.write_text(json.dumps(state_payload, indent=2), encoding="utf-8")


def rebuild_clean_quarterly_dataset(
    config: QuarterlyNLPipelineConfig,
    *,
    requested_start_local_day: date,
    requested_end_local_day: date,
    mode: str,
    download_summary: dict[str, Any] | None,
    latest_complete_day_cap: date,
) -> dict[str, Any]:
    raw_frame, file_summaries, parse_errors = parse_raw_xml_directory(config.raw_root, config.market_area)
    xml_file_summary = pd.DataFrame(file_summaries)
    xml_parse_errors = pd.DataFrame(parse_errors)
    xml_paths = sorted(config.raw_root.glob("*.xml"))
    utc_verification = verify_sample_source_timestamps_are_utc(xml_paths)

    requested_start_utc = local_midnight_to_utc(requested_start_local_day, config.local_timezone)
    cutoff_utc = local_midnight_to_utc(config.cutoff_local_date, config.local_timezone)
    max_timestamp_utc = end_timestamp_inclusive_for_local_day(requested_end_local_day, config.local_timezone)
    target_start_utc = max(requested_start_utc, cutoff_utc)

    if raw_frame.empty:
        quarterly_raw = raw_frame.copy()
        duplicate_rows_removed = 0
        quarterly_fix = DA_CLEANING.apply_missing_datapoint_fix(
            quarterly_raw,
            expected_minutes=QUARTERLY_STEP_MINUTES,
            dataset="quarterly",
            local_timezone=config.local_timezone,
        )
    else:
        raw_frame = raw_frame[raw_frame["timestamp_utc"].notna()].copy()
        raw_frame = raw_frame[
            (raw_frame["timestamp_utc"] >= target_start_utc)
            & (raw_frame["timestamp_utc"] <= max_timestamp_utc)
        ].copy()
        quarterly_raw = raw_frame[raw_frame["resolution_minutes"] == QUARTERLY_STEP_MINUTES].copy()
        quarterly_raw = expand_a03_variable_blocks(quarterly_raw, expected_minutes=QUARTERLY_STEP_MINUTES)
        quarterly_raw, duplicate_rows_removed = DA_CLEANING.split_duplicate_stats(quarterly_raw)
        quarterly_raw = DA_CLEANING.clip_to_max_timestamp(quarterly_raw, max_timestamp_utc=max_timestamp_utc)
        quarterly_fix = DA_CLEANING.apply_missing_datapoint_fix(
            quarterly_raw,
            expected_minutes=QUARTERLY_STEP_MINUTES,
            dataset="quarterly",
            local_timezone=config.local_timezone,
        )

    quarterly_frame = quarterly_fix.cleaned_frame.copy()
    quarterly_frame = quarterly_frame.sort_values("timestamp_utc").reset_index(drop=True)
    diagnostics_summary = pd.DataFrame(
        [
            DA_CLEANING.stats_row(
                region=config.market_area,
                dataset="quarterly",
                df=quarterly_frame,
                duplicate_rows_removed=duplicate_rows_removed,
                gap_fix_summary=quarterly_fix.summary,
                missing_timestamps_count_override=quarterly_fix.summary["missing_timestamps_before_fix"],
            )
        ]
    )
    delivery_day_coverage = build_delivery_day_coverage(quarterly_frame, config.local_timezone)
    latest_complete_delivery_local_date = None
    if not delivery_day_coverage.empty:
        complete_days = delivery_day_coverage[delivery_day_coverage["is_complete_local_day"] == True]
        if not complete_days.empty:
            latest_complete_delivery_local_date = date.fromisoformat(str(complete_days["delivery_local_date"].iloc[-1]))

    run_metadata = {
        "pipeline": "nl_quarterly_da_prices_pipeline",
        "mode": mode,
        "market_area": config.market_area,
        "local_timezone": config.local_timezone,
        "cutoff_local_date": config.cutoff_local_date.isoformat(),
        "requested_start_local_date": requested_start_local_day.isoformat(),
        "requested_end_local_date": requested_end_local_day.isoformat(),
        "latest_full_local_date_cap": latest_complete_day_cap.isoformat(),
        "target_start_utc": target_start_utc.isoformat(),
        "max_timestamp_utc": max_timestamp_utc.isoformat(),
        "raw_root": str(config.raw_root),
        "output_root": str(config.output_root),
        "utc_source_verification": utc_verification,
        "download_summary": download_summary or {"skipped": True},
        "xml_files_available": int(len(xml_paths)),
        "xml_files_parsed": int(len(file_summaries)),
        "xml_parse_errors": int(len(parse_errors)),
        "quarterly_rows_before_fix": int(quarterly_fix.summary["rows_before_fix"]),
        "a03_variable_block_expanded_points": int(
            quarterly_raw.get("a03_variable_block_expanded", pd.Series(dtype=bool)).fillna(False).sum()
        ),
        "quarterly_rows_after_fix": int(quarterly_fix.summary["rows_after_fix"]),
        "missing_datapoints_before_fix": int(quarterly_fix.summary["missing_datapoints_before_fix"]),
        "interpolated_points_count": int(quarterly_fix.summary["interpolated_points_count"]),
        "remaining_missing_points_after_fix": int(quarterly_fix.summary["remaining_missing_points_after_fix"]),
        "latest_complete_delivery_local_date": (
            latest_complete_delivery_local_date.isoformat() if latest_complete_delivery_local_date is not None else None
        ),
        "updated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }

    write_clean_outputs(
        config,
        quarterly_frame=quarterly_frame,
        diagnostics_summary=diagnostics_summary,
        gap_fix_details=quarterly_fix.gap_details,
        xml_file_summary=xml_file_summary,
        xml_parse_errors=xml_parse_errors,
        delivery_day_coverage=delivery_day_coverage,
        run_metadata=run_metadata,
        latest_complete_delivery_local_date=latest_complete_delivery_local_date,
    )

    return {
        "quarterly_rows": int(quarterly_frame.shape[0]),
        "latest_complete_delivery_local_date": (
            latest_complete_delivery_local_date.isoformat() if latest_complete_delivery_local_date is not None else None
        ),
        "quarterly_csv": str(config.quarterly_csv),
        "diagnostics_dir": str(config.diagnostics_dir),
    }


def main() -> int:
    args = parse_args()
    config = QuarterlyNLPipelineConfig(
        raw_root=args.raw_root,
        output_root=args.output_root,
        cutoff_local_date=args.cutoff_local_date,
        chunk_days=args.chunk_days,
        max_pages_per_chunk=args.max_pages_per_chunk,
        latest_full_day_lag_days=args.latest_full_day_lag_days,
    )

    start_local_day, end_local_day, latest_complete_day = resolve_import_window(
        args.mode,
        config,
        start_local_date_override=args.start_local_date,
        end_local_date_override=args.end_local_date,
    )

    if start_local_day > end_local_day:
        print(
            "No complete NL quarter-hour DA delivery days need importing. "
            f"Resolved window {start_local_day.isoformat()}..{end_local_day.isoformat()} is empty."
        )
        return 0

    download_summary = None
    if not args.skip_download:
        download_summary = download_raw_range(
            config,
            start_local_day=start_local_day,
            end_local_day=end_local_day,
        )
    elif not config.raw_root.exists():
        raise FileNotFoundError(f"skip-download requested but raw root does not exist: {config.raw_root}")

    rebuild_summary = rebuild_clean_quarterly_dataset(
        config,
        requested_start_local_day=config.cutoff_local_date,
        requested_end_local_day=end_local_day,
        mode=args.mode,
        download_summary=download_summary,
        latest_complete_day_cap=latest_complete_day,
    )
    print(json.dumps({"config": asdict(config), "rebuild_summary": rebuild_summary}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, FileNotFoundError, HTTPError, URLError, TimeoutError, socket.timeout) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
