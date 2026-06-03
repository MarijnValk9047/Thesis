from __future__ import annotations

import argparse
import json
import logging
import os
import re
import socket
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from dotenv import load_dotenv


BASE_URL = "https://web-api.tp.entsoe.eu/api"
TOKEN_ENV_VAR = "ENTSOE_KEY"
PSR_LABELS = {
    "B16": "solar",
    "B18": "wind_offshore",
    "B19": "wind_onshore",
}
NO_DATA_PATTERNS = [
    re.compile(r"no matching data found", flags=re.IGNORECASE),
    re.compile(r"<reason>", flags=re.IGNORECASE),
]


@dataclass(frozen=True)
class QueryPlanRow:
    psr_type: str
    psr_label: str
    year: int
    period_start: str
    period_end: str
    output_subdir: str
    page_size: int
    max_pages_per_query: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import NL A69 day-ahead wind/solar forecast by PSR into staged raw root.")
    parser.add_argument("--run-import", action="store_true", help="Execute the import. If omitted, no network calls are made.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned queries without downloading.")
    parser.add_argument("--start-year", type=int, default=2019)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--output-root", type=Path, default=Path("data/00_raw_lago_lear_six_year"))
    parser.add_argument("--psr-types", nargs="+", default=["B16", "B18", "B19"])
    parser.add_argument("--domain", type=str, default="10YNL----------L")
    parser.add_argument("--document-type", type=str, default="A69")
    parser.add_argument("--process-type", type=str, default="A01")
    parser.add_argument("--single-test-query", action="store_true", help="Run exactly one bounded API call.")
    parser.add_argument("--test-period-start", type=str, default="202308152200")
    parser.add_argument("--test-period-end", type=str, default="202308162200")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-pages-per-query", type=int, default=250)
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args()


def configure_logging(log_file: Path, log_level: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, str(log_level).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def get_token() -> str:
    load_dotenv()
    token = (os.getenv(TOKEN_ENV_VAR) or "").strip()
    if not token:
        raise ValueError(f"{TOKEN_ENV_VAR} is missing in environment/.env")
    return token


def period_for_year(year: int) -> tuple[str, str]:
    return f"{year}01010000", f"{year + 1}01010000"


def _timeseries_count(payload: bytes) -> int:
    text = payload.decode("utf-8", errors="replace")
    return text.count("<TimeSeries")


def _is_no_data_payload(payload: bytes) -> bool:
    text = payload.decode("utf-8", errors="replace")
    if _timeseries_count(payload) > 0:
        return False
    return any(pattern.search(text) for pattern in NO_DATA_PATTERNS)


def fetch_payload(params: dict[str, str]) -> bytes:
    url = f"{BASE_URL}?{urlencode(params)}"
    request = Request(url, method="GET")
    with urlopen(request, timeout=180) as response:
        return response.read()


def _build_request_url(params: dict[str, str]) -> str:
    return f"{BASE_URL}?{urlencode(params)}"


def _redact_url(url: str) -> str:
    return re.sub(r"(securityToken=)[^&]+", r"\1***REDACTED***", url)


def _psr_output_subdir(psr_type: str) -> str:
    label = PSR_LABELS.get(psr_type, psr_type.lower())
    return f"RES_Generation_Forecast/NL/A69_DA_Wind_Solar_Forecast_By_PSR/{psr_type}_{label}"


def build_plan_rows(args: argparse.Namespace) -> list[QueryPlanRow]:
    rows: list[QueryPlanRow] = []
    if args.single_test_query:
        psr_type = str(args.psr_types[0])
        rows.append(
            QueryPlanRow(
                psr_type=psr_type,
                psr_label=PSR_LABELS.get(psr_type, "unknown"),
                year=0,
                period_start=str(args.test_period_start),
                period_end=str(args.test_period_end),
                output_subdir=_psr_output_subdir(psr_type),
                page_size=100,
                max_pages_per_query=1,
            )
        )
        return rows
    for psr_type in args.psr_types:
        psr_label = PSR_LABELS.get(psr_type, "unknown")
        for year in range(int(args.start_year), int(args.end_year) + 1):
            period_start, period_end = period_for_year(year)
            rows.append(
                QueryPlanRow(
                    psr_type=str(psr_type),
                    psr_label=psr_label,
                    year=int(year),
                    period_start=period_start,
                    period_end=period_end,
                    output_subdir=_psr_output_subdir(str(psr_type)),
                    page_size=100,
                    max_pages_per_query=int(args.max_pages_per_query),
                )
            )
    return rows


def _target_filename(plan: QueryPlanRow, offset: int) -> str:
    if int(plan.year) == 0:
        return (
            f"a69_nl_da_res_fcst_{plan.psr_type}_test_"
            f"{plan.period_start}_{plan.period_end}_offset_{offset:04d}.xml"
        )
    return (
        f"a69_nl_da_res_fcst_{plan.psr_type}_{plan.year}_"
        f"{plan.period_start}_{plan.period_end}_offset_{offset:04d}.xml"
    )


def _count_timeseries_with_parse(payload: bytes) -> tuple[int, str | None]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        return 0, str(exc)
    if "}" in root.tag:
        ns_uri = root.tag.split("}", 1)[0].strip("{")
        count = len(root.findall(f".//{{{ns_uri}}}TimeSeries"))
    else:
        count = len(root.findall(".//TimeSeries"))
    return int(count), None


def run_import(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    token = get_token()
    plan_rows = build_plan_rows(args)
    status_rows: list[dict[str, Any]] = []
    query_rows: list[dict[str, Any]] = []

    for plan in plan_rows:
        out_dir = args.output_root / plan.output_subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        logging.info(
            "Plan query | psr=%s year=%s period=%s..%s out=%s",
            plan.psr_type,
            plan.year,
            plan.period_start,
            plan.period_end,
            out_dir,
        )
        query_rows.append(asdict(plan))
        if args.dry_run and not args.run_import:
            status_rows.append(
                {
                    **asdict(plan),
                    "offset": None,
                    "status": "dry_run_only",
                    "saved_path": None,
                    "timeseries_count": None,
                    "note": "No network call made.",
                }
            )
            continue

        offset = 0
        pages_downloaded = 0
        while pages_downloaded < int(plan.max_pages_per_query):
            target_path = out_dir / _target_filename(plan, offset)
            if target_path.exists() and args.skip_existing and not args.force:
                logging.info("Skip existing %s", target_path)
                status_rows.append(
                    {
                        **asdict(plan),
                        "offset": int(offset),
                        "status": "skipped_existing",
                        "saved_path": str(target_path),
                        "timeseries_count": None,
                        "note": "File exists and --skip-existing enabled.",
                    }
                )
                offset += int(plan.page_size)
                pages_downloaded += 1
                continue

            params = {
                "securityToken": token,
                "documentType": str(args.document_type),
                "processType": str(args.process_type),
                "in_Domain": str(args.domain),
                "periodStart": plan.period_start,
                "periodEnd": plan.period_end,
                "PsrType": plan.psr_type,
                "offset": str(offset),
            }
            request_url = _build_request_url(params)
            logging.info("Request URL: %s", _redact_url(request_url))
            try:
                payload = fetch_payload(params)
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                status = "auth_error" if int(exc.code) in (401, 403) else "api_error"
                status_rows.append(
                    {
                        **asdict(plan),
                        "offset": int(offset),
                        "status": status,
                        "saved_path": None,
                        "timeseries_count": None,
                        "note": f"http_{exc.code}: {body[:1000]}",
                    }
                )
                break
            except (URLError, TimeoutError, socket.timeout) as exc:
                status_rows.append(
                    {
                        **asdict(plan),
                        "offset": int(offset),
                        "status": "api_error",
                        "saved_path": None,
                        "timeseries_count": None,
                        "note": str(exc),
                    }
                )
                break

            ts_count, parse_error = _count_timeseries_with_parse(payload)
            if parse_error is not None:
                status_rows.append(
                    {
                        **asdict(plan),
                        "offset": int(offset),
                        "status": "parse_error",
                        "saved_path": None,
                        "timeseries_count": None,
                        "note": parse_error,
                    }
                )
                break
            if _is_no_data_payload(payload) or ts_count == 0:
                status_rows.append(
                    {
                        **asdict(plan),
                        "offset": int(offset),
                        "status": "no_data",
                        "saved_path": None,
                        "timeseries_count": int(ts_count),
                        "note": "API returned no data for this offset.",
                    }
                )
                if offset == 0:
                    break
                break

            target_path.write_bytes(payload)
            status_rows.append(
                {
                    **asdict(plan),
                    "offset": int(offset),
                    "status": "success_with_timeseries",
                    "saved_path": str(target_path),
                    "timeseries_count": int(ts_count),
                    "note": "",
                }
            )
            logging.info("Saved %s (%s TimeSeries)", target_path, ts_count)

            pages_downloaded += 1
            if ts_count < int(plan.page_size):
                break
            offset += int(plan.page_size)
        else:
            status_rows.append(
                {
                    **asdict(plan),
                    "offset": int(offset),
                    "status": "max_pages_reached",
                    "saved_path": None,
                    "timeseries_count": None,
                    "note": "Increase --max-pages-per-query if expected.",
                }
            )
    return query_rows, status_rows


def main() -> None:
    args = parse_args()
    import_root = args.output_root / "RES_Generation_Forecast" / "NL" / "A69_DA_Wind_Solar_Forecast_By_PSR"
    plan_path = import_root / "res_forecast_import_plan.json"
    status_path = import_root / "res_forecast_import_status.csv"
    log_path = import_root / "res_forecast_import.log"
    configure_logging(log_path, args.log_level)

    if int(args.start_year) > int(args.end_year):
        raise ValueError("start-year cannot be greater than end-year")
    if args.single_test_query and len(args.psr_types) < 1:
        raise ValueError("--single-test-query requires at least one PSR type.")
    if not args.run_import and not args.dry_run:
        logging.info("No execution flag was provided. Use --dry-run or --run-import.")
        plan_rows = build_plan_rows(args)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps([asdict(row) for row in plan_rows], indent=2), encoding="utf-8")
        pd.DataFrame(
            [
                {
                    **asdict(row),
                    "offset": None,
                    "status": "no_op",
                    "saved_path": None,
                    "timeseries_count": None,
                    "note": "No import requested.",
                }
                for row in plan_rows
            ]
        ).to_csv(status_path, index=False)
        return

    query_rows, status_rows = run_import(args)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(query_rows, indent=2), encoding="utf-8")
    pd.DataFrame(status_rows).to_csv(status_path, index=False)
    logging.info("Wrote plan to %s", plan_path)
    logging.info("Wrote status to %s", status_path)


if __name__ == "__main__":
    main()
