from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import socket
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

BASE_URL = "https://web-api.tp.entsoe.eu/api"
TOKEN_ENV_VAR = "ENTSOE_KEY"
DE_CONTROL_AREA_DOMAINS = [
    "10YDE-EON------1",
    "10Y1001C--00002H",
    "10YDE-VE-------2",
    "10YDE-ENBW-----N",
]
NL_CONTROL_AREA_DOMAIN = "10YNL----------L"
COUNTRY_BIDDING_ZONE_DOMAINS = {
    "BE": "10YBE----------2",
    "DE": "10Y1001A1001A83F",
    "NL": "10YNL----------L",
}
COUNTRY_PRICE_DOMAINS = {
    "BE": "10YBE----------2",
    "DE": "10Y1001A1001A82H",
    "NL": "10YNL----------L",
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


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    output_subdir: str
    default_start_year: int
    default_end_year: int
    page_size: int
    params: Dict[str, str]
    area_domains: List[str] | None = None
    domains: List[str] | None = None
    domain_param: str | None = None
    query_variants: List[Tuple[str, Dict[str, str]]] | None = None
    year_chunk_months: int | None = None


DATASETS: Dict[str, DatasetConfig] = {
    "17_1_bc_nl_ir": DatasetConfig(
        name="17_1_bc_nl_ir",
        output_subdir="ENTSOE/17_1_BC_NL_IR",
        default_start_year=2022,
        default_end_year=2025,
        page_size=100,
        params={
            "documentType": "A81",
            "businessType": "B95",
            "processType": "A47",
            "Type_MarketAgreement.Type": "A01",
            "controlArea_Domain": "10YNL----------L",
            "psrType": "A04",
        },
    ),
    "12_3_bc_nl_ir": DatasetConfig(
        name="12_3_bc_nl_ir",
        output_subdir="ENTSOE/12_3_BC_NL_IR",
        default_start_year=2022,
        default_end_year=2025,
        page_size=100,
        params={
            "documentType": "A37",
            "businessType": "B74",
            "processType": "A47",
            "connecting_Domain": "10YNL----------L",
            "Original_MarketProduct": "A02",
        },
    ),
    "12_3_f_nl_ir": DatasetConfig(
        name="12_3_f_nl_ir",
        output_subdir="ENTSOE/12_3_F_NL_IR",
        default_start_year=2022,
        default_end_year=2025,
        page_size=100,
        params={
            "documentType": "A15",
            "processType": "A47",
            "area_Domain": "10YNL----------L",
            "Type_MarketAgreement.Type": "A01",
        },
    ),
    "12_3_e_nl_ir_a47": DatasetConfig(
        name="12_3_e_nl_ir_mFRR",
        output_subdir="ENTSOE/12_3_E_NL_IR_mFRR",
        default_start_year=2022,
        default_end_year=2025,
        page_size=100,
        params={
            "documentType": "A24",
            "processType": "A47",
            "area_Domain": "10YNL----------L",
        },
    ),
    "12_3_e_nl_ir_a60": DatasetConfig(
        name="12_3_e_nl_ir_mFRRsa",
        output_subdir="ENTSOE/12_3_E_NL_IR_mFRRsa",
        default_start_year=2022,
        default_end_year=2025,
        page_size=100,
        params={
            "documentType": "A24",
            "processType": "A60",
            "area_Domain": "10YNL----------L",
        },
    ),
    "12_3_e_nl_ir_a61": DatasetConfig(
        name="12_3_e_nl_ir_mFRRda",
        output_subdir="ENTSOE/12_3_E_NL_IR_mFRRda",
        default_start_year=2022,
        default_end_year=2025,
        page_size=100,
        params={
            "documentType": "A24",
            "processType": "A61",
            "area_Domain": "10YNL----------L",
        },
    ),
    "12_3_e_de_mari_mfrrsa": DatasetConfig(
        name="12_3_e_de_mari_mfrrsa",
        output_subdir="ENTSOE/12_3_E_DE_MARI_mFRRsa",
        default_start_year=2022,
        default_end_year=2025,
        page_size=100,
        params={
            "documentType": "A24",
            "processType": "A60",
        },
        area_domains=DE_CONTROL_AREA_DOMAINS,
    ),
    "12_3_e_de_mari_mfrrda": DatasetConfig(
        name="12_3_e_de_mari_mfrrda",
        output_subdir="ENTSOE/12_3_E_DE_MARI_mFRRda",
        default_start_year=2022,
        default_end_year=2025,
        page_size=100,
        params={
            "documentType": "A24",
            "processType": "A61",
        },
        area_domains=DE_CONTROL_AREA_DOMAINS,
    ),
    "17_1_f_de_a16_realised": DatasetConfig(
        name="17_1_f_de_A16_(Realised)",
        output_subdir="ENTSOE/17.1 F - Prices of activated balancing energy/DE/A16 (Realised)",
        default_start_year=2022,
        default_end_year=2025,
        page_size=100,
        params={
            "documentType": "A84",
            "processType": "A16",
            "businessType": "A97",
        },
        domains=DE_CONTROL_AREA_DOMAINS,
        domain_param="controlArea_Domain",
        query_variants=[
            ("Standard_MarketProduct_A01", {"Standard_MarketProduct": "A01"}),
        ],
    ),
    "17_1_f_nl_a16_realised": DatasetConfig(
        name="17_1_f_nl_A16_(Realised)",
        output_subdir="ENTSOE/17.1 F - Prices of activated balancing energy/NL/A16 (Realised)",
        default_start_year=2022,
        default_end_year=2025,
        page_size=100,
        params={
            "documentType": "A84",
            "processType": "A16",
            "businessType": "A97",
        },
        domains=[NL_CONTROL_AREA_DOMAIN],
        domain_param="controlArea_Domain",
        query_variants=[
            ("Original_MarketProduct_A02", {"Original_MarketProduct": "A02"}),
            ("Original_MarketProduct_A04", {"Original_MarketProduct": "A04"}),
            ("No_MarketProduct_Filter", {}),
        ],
        year_chunk_months=3,
    ),

}


def build_psr_variants(psr_types: List[str]) -> List[Tuple[str, Dict[str, str]]]:
    return [
        (f"{psr}_{PSR_TYPE_LABELS[psr]}", {"psrType": psr})
        for psr in psr_types
    ]


def add_dataset(key: str, config: DatasetConfig) -> None:
    if key in DATASETS:
        raise ValueError(f"Duplicate dataset key: {key}")
    DATASETS[key] = config


ALL_PSR_VARIANTS = build_psr_variants(list(PSR_TYPE_LABELS.keys()))
WIND_SOLAR_PSR = [
    ("B16", "Solar"),
    ("B18", "Offshore"),
    ("B19", "Onshore"),
]


for country_code, domain in COUNTRY_BIDDING_ZONE_DOMAINS.items():
    cc = country_code.lower()
    price_domain = COUNTRY_PRICE_DOMAINS[country_code]

    add_dataset(
        f"6_1_a_actual_total_load_{cc}",
        DatasetConfig(
            name=f"6_1_a_actual_total_load_{country_code}",
            output_subdir=f"Load/Load_{country_code}/6_1_A_Actual_Total_Load",
            default_start_year=2022,
            default_end_year=2025,
            page_size=100,
            params={
                "documentType": "A65",
                "processType": "A16",
                "outBiddingZone_Domain": domain,
            },
        ),
    )
    add_dataset(
        f"6_1_b_da_total_load_forecast_{cc}",
        DatasetConfig(
            name=f"6_1_b_da_total_load_forecast_{country_code}",
            output_subdir=f"Load/Load_{country_code}/6_1_B_DA_Total_Load_Forecast",
            default_start_year=2022,
            default_end_year=2025,
            page_size=100,
            params={
                "documentType": "A65",
                "processType": "A01",
                "outBiddingZone_Domain": domain,
            },
        ),
    )
    add_dataset(
        f"6_1_c_week_ahead_load_forecast_{cc}",
        DatasetConfig(
            name=f"6_1_c_week_ahead_load_forecast_{country_code}",
            output_subdir=f"Load/Load_{country_code}/6_1_C_Week_Ahead_Total_Load_Forecast",
            default_start_year=2022,
            default_end_year=2025,
            page_size=100,
            params={
                "documentType": "A65",
                "processType": "A31",
                "outBiddingZone_Domain": domain,
            },
        ),
    )

    add_dataset(
        f"14_1_a_installed_capacity_by_psr_{cc}",
        DatasetConfig(
            name=f"14_1_a_installed_capacity_by_psr_{country_code}",
            output_subdir=(
                f"RES_Generation_Forecast/{country_code}/"
                "14_1_A_Installed_Capacity_per_Production_Type"
            ),
            default_start_year=2022,
            default_end_year=2025,
            page_size=100,
            params={
                "documentType": "A68",
                "processType": "A33",
                "in_Domain": domain,
            },
            query_variants=ALL_PSR_VARIANTS,
        ),
    )
    add_dataset(
        f"16_1_bc_actual_generation_by_psr_a74_{cc}",
        DatasetConfig(
            name=f"16_1_bc_actual_generation_by_psr_a74_{country_code}",
            output_subdir=(
                f"RES_Generation_Forecast/{country_code}/"
                "16_1_BC_Actual_Generation_per_Production_Type_A74"
            ),
            default_start_year=2022,
            default_end_year=2025,
            page_size=100,
            params={
                "documentType": "A74",
                "processType": "A16",
                "in_Domain": domain,
            },
            query_variants=ALL_PSR_VARIANTS,
        ),
    )
    add_dataset(
        f"16_1_bc_actual_generation_all_types_a75_{cc}",
        DatasetConfig(
            name=f"16_1_bc_actual_generation_all_types_a75_{country_code}",
            output_subdir=(
                f"RES_Generation_Forecast/{country_code}/"
                "16_1_BC_Actual_Generation_All_Production_Types_A75"
            ),
            default_start_year=2022,
            default_end_year=2025,
            page_size=100,
            params={
                "documentType": "A75",
                "processType": "A16",
                "in_Domain": domain,
            },
        ),
    )
    add_dataset(
        f"14_1_c_da_generation_forecast_{cc}",
        DatasetConfig(
            name=f"14_1_c_da_generation_forecast_{country_code}",
            output_subdir=f"RES_Generation_Forecast/{country_code}/14_1_C_DA_Generation_Forecast",
            default_start_year=2022,
            default_end_year=2025,
            page_size=100,
            params={
                "documentType": "A71",
                "processType": "A01",
                "in_Domain": domain,
            },
        ),
    )

    for psr, folder in WIND_SOLAR_PSR:
        add_dataset(
            f"14_1_d_intraday_generation_forecast_{cc}_{folder.lower()}",
            DatasetConfig(
                name=(
                    f"14_1_d_intraday_generation_forecast_{country_code}_"
                    f"{PSR_TYPE_LABELS[psr]}"
                ),
                output_subdir=f"RES_Generation_Forecast/{country_code}_intraday_forecast/{folder}",
                default_start_year=2022,
                default_end_year=2025,
                page_size=100,
                params={
                    "documentType": "A69",
                    "processType": "A40",
                    "in_Domain": domain,
                    "psrType": psr,
                },
            ),
        )

    add_dataset(
        f"12_1_d_energy_prices_a01_day_ahead_{cc}",
        DatasetConfig(
            name=f"12_1_d_energy_prices_a01_day_ahead_{country_code}",
            output_subdir=f"DA_Prices/DA_prices_{country_code}/A01_Day_Ahead_Market",
            default_start_year=2022,
            default_end_year=2025,
            page_size=100,
            params={
                "documentType": "A44",
                "in_Domain": price_domain,
                "out_Domain": price_domain,
                "contract_MarketAgreement.type": "A01",
            },
        ),
    )
    add_dataset(
        f"12_1_d_energy_prices_a07_intraday_{cc}",
        DatasetConfig(
            name=f"12_1_d_energy_prices_a07_intraday_{country_code}",
            output_subdir=f"DA_Prices/DA_prices_{country_code}/A07_Intraday_Market",
            default_start_year=2022,
            default_end_year=2025,
            page_size=100,
            params={
                "documentType": "A44",
                "in_Domain": price_domain,
                "out_Domain": price_domain,
                "contract_MarketAgreement.type": "A07",
            },
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download ENTSO-E datasets and store raw XML responses."
    )
    parser.add_argument(
        "--dataset",
        default="17_1_bc_nl_ir",
        choices=sorted(DATASETS.keys()),
        help="Dataset key from DATASETS config.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        help="First year to request (inclusive).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        help="Last year to request (inclusive).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/00_Raw"),
        help="Root output folder where XML files are stored.",
    )
    parser.add_argument(
        "--max-pages-per-year",
        type=int,
        default=250,
        help="Safety cap for pagination loops.",
    )
    return parser.parse_args()


def get_token() -> str:
    load_dotenv()
    token = (os.getenv(TOKEN_ENV_VAR) or "").strip()
    if not token:
        raise ValueError(f"{TOKEN_ENV_VAR} is missing in .env")
    return token


def period_for_year(year: int) -> tuple[str, str]:
    period_start = f"{year}01010000"
    period_end = f"{year + 1}01010000"
    return period_start, period_end


def add_months(dt: datetime, months: int) -> datetime:
    month_index = dt.month - 1 + months
    year = dt.year + (month_index // 12)
    month = (month_index % 12) + 1
    return datetime(year, month, 1)


def period_chunks_for_year(year: int, chunk_months: int | None) -> List[Tuple[str, str, str]]:
    if not chunk_months or chunk_months >= 12:
        period_start, period_end = period_for_year(year)
        return [("", period_start, period_end)]

    chunks: List[Tuple[str, str, str]] = []
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)
    idx = 1
    while start < end:
        nxt = add_months(start, chunk_months)
        if nxt > end:
            nxt = end
        label = f"chunk_{idx:02d}"
        chunks.append((label, start.strftime("%Y%m%d%H%M"), nxt.strftime("%Y%m%d%H%M")))
        start = nxt
        idx += 1
    return chunks


def count_time_series(xml_text: str) -> int:
    return len(re.findall(r"<(?:[A-Za-z0-9_]+:)?TimeSeries\b", xml_text))


def fetch_payload(params: Dict[str, str]) -> bytes:
    url = f"{BASE_URL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "thesis-entsoe-downloader/1.0"})
    with urlopen(req, timeout=180) as response:
        return response.read()


def is_zip_payload(payload: bytes) -> bool:
    return payload.startswith(b"PK\x03\x04")


def extract_xml_documents(payload: bytes) -> List[str]:
    if not is_zip_payload(payload):
        return [payload.decode("utf-8", errors="replace")]

    docs: List[str] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as zip_handle:
        for member_name in zip_handle.namelist():
            if member_name.endswith("/"):
                continue
            with zip_handle.open(member_name) as member:
                docs.append(member.read().decode("utf-8", errors="replace"))
    return docs


def contains_no_matching_data(xml_docs: List[str]) -> bool:
    return any("No matching data found" in doc for doc in xml_docs)


def contains_entsoe_reason_error(xml_docs: List[str]) -> bool:
    reason_pattern = re.compile(r"<(?:[A-Za-z0-9_]+:)?Reason\b")
    for doc in xml_docs:
        if reason_pattern.search(doc) and "No matching data found" not in doc:
            return True
    return False


def total_time_series_count(xml_docs: List[str]) -> int:
    return sum(count_time_series(doc) for doc in xml_docs)


def extract_reason_text(xml_text: str) -> str:
    reasons = re.findall(r"<text>(.*?)</text>", xml_text, re.S)
    return " | ".join(reason.strip() for reason in reasons if reason.strip())


def normalized_docs_signature(xml_docs: List[str]) -> str:
    normalized_docs: List[str] = []
    for doc in xml_docs:
        normalized = re.sub(r"<mRID>.*?</mRID>", "<mRID></mRID>", doc, count=1, flags=re.S)
        normalized = re.sub(
            r"<createdDateTime>.*?</createdDateTime>",
            "<createdDateTime></createdDateTime>",
            normalized,
            count=1,
            flags=re.S,
        )
        normalized_docs.append(normalized)
    return hashlib.sha256("||".join(normalized_docs).encode("utf-8")).hexdigest()


def download_dataset(
    config: DatasetConfig,
    token: str,
    start_year: int,
    end_year: int,
    output_root: Path,
    max_pages_per_year: int,
) -> None:
    out_dir = output_root / config.output_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    if config.domains:
        domain_values = config.domains
        domain_param = config.domain_param or "area_Domain"
    else:
        domain_values = config.area_domains or [None]
        domain_param = "area_Domain"
    query_variants = config.query_variants or [("", {})]

    for year in range(start_year, end_year + 1):
        period_chunks = period_chunks_for_year(year, config.year_chunk_months)
        for chunk_label, period_start, period_end in period_chunks:
            for domain_value in domain_values:
                for variant_label, variant_params in query_variants:
                    if domain_value:
                        print(
                            f"Year {year}, {domain_param}={domain_value}: "
                            f"periodStart={period_start}, periodEnd={period_end}"
                        )
                    else:
                        print(
                            f"Year {year}: periodStart={period_start}, periodEnd={period_end}"
                        )
                    if chunk_label:
                        print(f"  Chunk: {chunk_label}")
                    if variant_label:
                        print(f"  Variant: {variant_label}")

                    offset = 0
                    pages_downloaded = 0
                    seen_payload_hashes: set[str] = set()

                    while pages_downloaded < max_pages_per_year:
                        params = {
                            "securityToken": token,
                            "periodStart": period_start,
                            "periodEnd": period_end,
                            "offset": str(offset),
                            **config.params,
                            **variant_params,
                        }
                        if domain_value:
                            params[domain_param] = domain_value

                        payload: bytes | None = None
                        for attempt in range(1, 4):
                            try:
                                payload = fetch_payload(params)
                                break
                            except HTTPError as exc:
                                body = exc.read().decode("utf-8", errors="replace")
                                reason = extract_reason_text(body)
                                if exc.code == 400:
                                    if reason:
                                        print(
                                            f"  Stopped at offset {offset} "
                                            f"(HTTP 400): {reason}"
                                        )
                                    else:
                                        print(f"  Stopped at offset {offset} (HTTP 400).")
                                    break
                                if 500 <= exc.code < 600 and attempt < 3:
                                    print(
                                        f"  Temporary HTTP {exc.code} at offset {offset}, "
                                        f"retry {attempt}/3."
                                    )
                                    continue
                                raise RuntimeError(
                                    f"HTTP {exc.code} at offset {offset}. "
                                    f"{reason or 'No reason provided.'}"
                                )
                            except (TimeoutError, socket.timeout, URLError):
                                if attempt < 3:
                                    print(
                                        f"  Temporary network/timeout at offset {offset}, "
                                        f"retry {attempt}/3."
                                    )
                                    continue
                                print(
                                    f"  Timeout/network issue at year {year}, "
                                    f"offset {offset}. Stopping this combination."
                                )
                                break

                        if payload is None:
                            break

                        xml_docs = extract_xml_documents(payload)
                        docs_signature = normalized_docs_signature(xml_docs)
                        if docs_signature in seen_payload_hashes:
                            print(
                                f"  Duplicate page detected at offset {offset}. "
                                "Stopping pagination for this combination."
                            )
                            break
                        seen_payload_hashes.add(docs_signature)

                        if contains_no_matching_data(xml_docs):
                            if pages_downloaded == 0:
                                if domain_value:
                                    print(
                                        f"  No data found for {year}, "
                                        f"{domain_param}={domain_value}."
                                    )
                                else:
                                    print(f"  No data found for {year}.")
                            break

                        if contains_entsoe_reason_error(xml_docs):
                            domain_context = (
                                f", {domain_param}={domain_value}" if domain_value else ""
                            )
                            variant_context = (
                                f", variant={variant_label}" if variant_label else ""
                            )
                            raise RuntimeError(
                                f"ENTSO-E returned an API error for year {year}"
                                f"{domain_context}{variant_context}, offset {offset}."
                            )

                        series_count = total_time_series_count(xml_docs)
                        if series_count == 0:
                            if domain_value:
                                print(
                                    f"  No TimeSeries returned for year {year}, "
                                    f"{domain_param}={domain_value}, offset {offset}."
                                )
                            else:
                                print(
                                    f"  No TimeSeries returned for year {year}, offset {offset}."
                                )
                            break

                        extension = "zip" if is_zip_payload(payload) else "xml"
                        file_parts = [config.name]
                        if domain_value:
                            file_parts.append(domain_value)
                        if variant_label:
                            file_parts.append(variant_label)
                        if chunk_label:
                            file_parts.append(chunk_label)
                        file_parts.append(str(year))
                        file_parts.append(f"offset_{offset:04d}")
                        target_name = "_".join(file_parts) + f".{extension}"
                        target = out_dir / target_name
                        target.write_bytes(payload)
                        pages_downloaded += 1
                        print(f"  Saved {target} ({series_count} TimeSeries).")

                        if series_count < config.page_size:
                            break

                        offset += config.page_size
                    else:
                        domain_context = (
                            f", {domain_param}={domain_value}" if domain_value else ""
                        )
                        variant_context = f", variant={variant_label}" if variant_label else ""
                        raise RuntimeError(
                            f"Stopped at max-pages-per-year={max_pages_per_year} for year {year}"
                            f"{domain_context}{variant_context}. Increase the cap if this is "
                            "expected."
                        )


def main() -> int:
    args = parse_args()
    config = DATASETS[args.dataset]

    start_year = args.start_year or config.default_start_year
    end_year = args.end_year or config.default_end_year

    if start_year > end_year:
        raise ValueError("start-year cannot be greater than end-year")

    token = get_token()
    download_dataset(
        config=config,
        token=token,
        start_year=start_year,
        end_year=end_year,
        output_root=args.output_root,
        max_pages_per_year=args.max_pages_per_year,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, HTTPError, URLError, TimeoutError, socket.timeout) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
