from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd

from .config import BIDDING_ZONE_DOMAIN_CODES, DA_PRICE_DOMAIN_CODES, HourlyDAPipelineConfig, MARKET_TIMEZONES
from .data_loading import build_canonical_hourly_frame, load_hourly_price_frame
from .reporting import find_latest_run


RAW_FILE_YEAR_PATTERN = re.compile(r"_(?P<year>\d{4})_offset_")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[6]


def load_cleaning_module() -> ModuleType:
    module_path = repo_root() / "scripts" / "Data" / "01_cleaning" / "day_ahead_prices_pipeline.py"
    spec = importlib.util.spec_from_file_location("day_ahead_prices_pipeline", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load cleaning module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _raw_xml_metadata(region: str, raw_root: Path) -> dict[str, object]:
    xml_files = sorted((raw_root / f"DA_prices_{region}").rglob("*.xml"))
    years = sorted(
        {
            int(match.group("year"))
            for xml_file in xml_files
            for match in [RAW_FILE_YEAR_PATTERN.search(xml_file.name)]
            if match is not None
        }
    )
    return {
        "market_area": region,
        "raw_xml_file_count": int(len(xml_files)),
        "raw_xml_years_from_filename_json": json.dumps(years),
        "raw_xml_has_2021_files": bool(2021 in years),
    }


def build_raw_stage_frames(region: str, raw_root: Path, max_timestamp_utc: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    cleaning = load_cleaning_module()
    xml_files = sorted((raw_root / f"DA_prices_{region}").rglob("*.xml"))
    rows: list[dict[str, object]] = []
    for xml_file in xml_files:
        file_rows, _ = cleaning.parse_single_xml(region, xml_file)
        rows.extend(file_rows)

    raw_imported_all = pd.DataFrame(rows)
    parsed_all = cleaning.make_region_dataframe(rows)
    raw_imported = raw_imported_all.copy()
    if not raw_imported.empty and "resolution_minutes" in raw_imported.columns:
        raw_imported = raw_imported[raw_imported["resolution_minutes"] == 60].copy()
    parsed = parsed_all.copy()
    if not parsed.empty and "resolution_minutes" in parsed.columns:
        parsed = parsed[parsed["resolution_minutes"] == 60].copy()
    normalized = parsed.copy()
    sequence_2_rows_removed = 0
    if region == "DE" and not normalized.empty:
        mask_seq2 = normalized["timeseries_sequence_position"] == 2
        sequence_2_rows_removed = int(mask_seq2.sum())
        normalized = normalized[~mask_seq2].copy()
    normalized, duplicate_rows_removed = cleaning.split_duplicate_stats(normalized)
    normalized = cleaning.clip_to_max_timestamp(normalized, max_timestamp_utc=max_timestamp_utc)
    normalized = normalized[normalized["resolution_minutes"] == 60].copy().sort_values("timestamp_utc").reset_index(drop=True)
    return (
        {
            "raw_imported": raw_imported,
            "parsed_series": parsed,
            "normalized_utc_series": normalized,
        },
        {
            "duplicate_rows_removed": duplicate_rows_removed,
            "sequence_2_rows_removed": sequence_2_rows_removed,
            "raw_total_rows_all_resolutions": int(raw_imported_all.shape[0]),
            "raw_non_hourly_rows_excluded": int(raw_imported_all.shape[0] - raw_imported.shape[0]),
            "parsed_total_rows_all_resolutions": int(parsed_all.shape[0]),
            "parsed_non_hourly_rows_excluded": int(parsed_all.shape[0] - parsed.shape[0]),
            **_raw_xml_metadata(region, raw_root),
        },
    )


def _gap_intervals_from_missing_index(
    missing_index: pd.DatetimeIndex,
    market_area: str,
    stage_name: str,
    timezone: str,
    gap_origin_assessment: str,
) -> pd.DataFrame:
    if missing_index.empty:
        return pd.DataFrame(
            columns=[
                "market_area",
                "stage_name",
                "gap_start_utc",
                "gap_end_utc",
                "gap_length_hours",
                "gap_start_local",
                "gap_end_local",
                "affected_year_local",
                "gap_origin_assessment",
            ]
        )

    gap_rows: list[dict[str, object]] = []
    group_ids = (missing_index.to_series().diff().fillna(pd.Timedelta(hours=1)) != pd.Timedelta(hours=1)).cumsum()
    for _, group in pd.Series(missing_index, index=missing_index).groupby(group_ids):
        start_utc = group.iloc[0]
        end_utc = group.iloc[-1]
        start_local = start_utc.tz_convert(timezone)
        end_local = end_utc.tz_convert(timezone)
        gap_rows.append(
            {
                "market_area": market_area,
                "stage_name": stage_name,
                "gap_start_utc": start_utc.isoformat(),
                "gap_end_utc": end_utc.isoformat(),
                "gap_length_hours": int(group.shape[0]),
                "gap_start_local": start_local.isoformat(),
                "gap_end_local": end_local.isoformat(),
                "affected_year_local": int(start_local.year),
                "gap_origin_assessment": gap_origin_assessment,
            }
        )
    return pd.DataFrame(gap_rows)


def summarize_stage(
    frame: pd.DataFrame,
    market_area: str,
    stage_name: str,
    timezone: str,
    timestamp_col: str,
    gap_reference_col: str | None,
    previous_gap_count: int | None,
    metadata: dict[str, object] | None = None,
) -> tuple[dict[str, object], pd.DataFrame]:
    metadata = metadata or {}
    stage_frame = frame.copy()
    stage_frame[timestamp_col] = pd.to_datetime(stage_frame[timestamp_col], utc=True, errors="coerce")
    valid = stage_frame[stage_frame[timestamp_col].notna()].copy()
    row_count = int(stage_frame.shape[0])
    invalid_timestamp_rows = int(row_count - valid.shape[0])
    duplicate_timestamp_rows = int(valid[timestamp_col].duplicated(keep=False).sum())

    if valid.empty:
        summary = {
            "market_area": market_area,
            "stage_name": stage_name,
            "row_count": row_count,
            "valid_timestamp_rows": 0,
            "invalid_timestamp_rows": invalid_timestamp_rows,
            "unique_timestamp_count": 0,
            "duplicate_timestamp_rows": duplicate_timestamp_rows,
            "missing_timestamps_count": 0,
            "gap_count": 0,
            "gap_length_min_hours": 0,
            "gap_length_max_hours": 0,
            "affected_years_local_json": "[]",
            "gap_origin_assessment": "no_rows",
            **metadata,
        }
        return summary, pd.DataFrame()

    unique_timestamps = pd.DatetimeIndex(valid[timestamp_col].sort_values().unique(), tz="UTC")
    if gap_reference_col is None:
        expected_index = pd.date_range(start=unique_timestamps.min(), end=unique_timestamps.max(), freq="h", tz="UTC")
        missing_index = expected_index.difference(unique_timestamps)
    else:
        missing_index = pd.DatetimeIndex(
            valid.loc[valid[gap_reference_col].isna(), timestamp_col].sort_values().tolist(),
            tz="UTC",
        )

    if previous_gap_count is None:
        gap_origin_assessment = "baseline_stage"
    elif len(missing_index) == previous_gap_count:
        gap_origin_assessment = "gaps_already_existed"
    elif len(missing_index) > previous_gap_count:
        gap_origin_assessment = "additional_gaps_or_missing_values_introduced"
    else:
        gap_origin_assessment = "gaps_resolved_or_reduced"

    gap_intervals = _gap_intervals_from_missing_index(
        missing_index=missing_index,
        market_area=market_area,
        stage_name=stage_name,
        timezone=timezone,
        gap_origin_assessment=gap_origin_assessment,
    )
    affected_years = sorted(gap_intervals["affected_year_local"].unique().tolist()) if not gap_intervals.empty else []
    summary = {
        "market_area": market_area,
        "stage_name": stage_name,
        "row_count": row_count,
        "valid_timestamp_rows": int(valid.shape[0]),
        "invalid_timestamp_rows": invalid_timestamp_rows,
        "unique_timestamp_count": int(unique_timestamps.shape[0]),
        "duplicate_timestamp_rows": duplicate_timestamp_rows,
        "missing_timestamps_count": int(missing_index.shape[0]),
        "gap_count": int(gap_intervals.shape[0]),
        "gap_length_min_hours": int(gap_intervals["gap_length_hours"].min()) if not gap_intervals.empty else 0,
        "gap_length_max_hours": int(gap_intervals["gap_length_hours"].max()) if not gap_intervals.empty else 0,
        "affected_years_local_json": json.dumps(affected_years),
        "gap_origin_assessment": gap_origin_assessment,
        **metadata,
    }
    return summary, gap_intervals


def build_gap_audit_tables(markets: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    markets = markets or ["NL", "BE", "DE"]
    base_config = HourlyDAPipelineConfig()
    diagnostics_path = repo_root() / "data" / "01_cleaned" / "Day_ahead_prices" / "diagnostics" / "diagnostics_comparison.csv"
    diagnostics = pd.read_csv(diagnostics_path)
    run_metadata_path = repo_root() / "data" / "01_cleaned" / "Day_ahead_prices" / "diagnostics" / "run_metadata.json"
    run_metadata = json.loads(run_metadata_path.read_text(encoding="utf-8"))
    max_timestamp_utc = pd.to_datetime(run_metadata["max_timestamp_utc"], utc=True)

    summary_rows: list[dict[str, object]] = []
    interval_frames: list[pd.DataFrame] = []
    domain_rows: list[dict[str, object]] = []
    artifact_rows: list[dict[str, object]] = []

    latest_data_overview = None
    try:
        latest_data_overview = find_latest_run(base_config.output_root, "data_overview")
    except FileNotFoundError:
        latest_data_overview = None

    for market_area in markets:
        config = HourlyDAPipelineConfig(
            market_area=market_area,
            business_timezone=MARKET_TIMEZONES[market_area],
            holiday_country=market_area,
        )
        timezone = config.resolved_business_timezone()
        raw_frames, raw_meta = build_raw_stage_frames(market_area, config.raw_root, max_timestamp_utc=max_timestamp_utc)
        cleaned = load_hourly_price_frame(config)
        canonical = build_canonical_hourly_frame(cleaned, config)

        previous_gap_count: int | None = None
        for stage_name, frame, gap_reference_col, extra_meta in [
            ("raw_imported_data", raw_frames["raw_imported"], None, raw_meta),
            ("parsed_series", raw_frames["parsed_series"], None, {}),
            ("normalized_utc_series", raw_frames["normalized_utc_series"], None, {}),
            ("post_reindex_series", canonical, config.target_col, {}),
            ("feature_source_series", canonical, config.feature_source_col, {"feature_gap_fill_method": config.feature_gap_fill_method}),
        ]:
            summary, intervals = summarize_stage(
                frame=frame,
                market_area=market_area,
                stage_name=stage_name,
                timezone=timezone,
                timestamp_col=config.timestamp_col,
                gap_reference_col=gap_reference_col,
                previous_gap_count=previous_gap_count,
                metadata=extra_meta,
            )
            previous_gap_count = int(summary["missing_timestamps_count"])
            summary_rows.append(summary)
            if not intervals.empty:
                interval_frames.append(intervals)

        sample_domains = cleaned[["in_domain", "out_domain"]].dropna().drop_duplicates().sort_values(["in_domain", "out_domain"])
        domain_rows.append(
            {
                "market_area": market_area,
                "market_timezone": timezone,
                "price_domain_code": DA_PRICE_DOMAIN_CODES[market_area],
                "bidding_zone_code": BIDDING_ZONE_DOMAIN_CODES[market_area],
                "source_in_domain_values_json": json.dumps(sample_domains["in_domain"].tolist()),
                "source_out_domain_values_json": json.dumps(sample_domains["out_domain"].tolist()),
                "price_query_level_note": (
                    "A44 day-ahead prices use the price-area / bidding-zone level code. "
                    "Germany uses 10Y1001A1001A82H for DE-LU prices, while 10Y1001A1001A83F is the DE bidding-zone "
                    "code used for other query families such as load."
                ),
            }
        )

        diagnostics_hourly = diagnostics[(diagnostics["record_type"] == "region") & (diagnostics["dataset"] == "hourly") & (diagnostics["region"] == market_area)]
        if not diagnostics_hourly.empty:
            row = diagnostics_hourly.iloc[0]
            artifact_rows.append(
                {
                    "market_area": market_area,
                    "artifact_name": "cleaning_diagnostics_hourly_missing_timestamps",
                    "artifact_value": int(row["missing_timestamps_count"]),
                    "current_stage_name": "normalized_utc_series",
                    "current_value": int(next(r for r in summary_rows if r["market_area"] == market_area and r["stage_name"] == "normalized_utc_series")["missing_timestamps_count"]),
                }
            )
        if latest_data_overview is not None and market_area == "NL":
            gap_summary = pd.read_csv(latest_data_overview / "gap_summary.csv")
            if not gap_summary.empty:
                artifact_rows.append(
                    {
                        "market_area": market_area,
                        "artifact_name": "existing_hourly_da_gap_summary_rows_missing",
                        "artifact_value": int(gap_summary["rows_missing"].iloc[0]),
                        "current_stage_name": "post_reindex_series",
                        "current_value": int(next(r for r in summary_rows if r["market_area"] == market_area and r["stage_name"] == "post_reindex_series")["missing_timestamps_count"]),
                    }
                )

    summary_df = pd.DataFrame(summary_rows).sort_values(["market_area", "stage_name"]).reset_index(drop=True)
    intervals_df = (
        pd.concat(interval_frames, ignore_index=True).sort_values(["market_area", "stage_name", "gap_start_utc"]).reset_index(drop=True)
        if interval_frames
        else pd.DataFrame()
    )
    domain_df = pd.DataFrame(domain_rows).sort_values(["market_area"]).reset_index(drop=True)
    artifact_df = pd.DataFrame(artifact_rows).sort_values(["market_area", "artifact_name"]).reset_index(drop=True)
    return summary_df, intervals_df, domain_df, artifact_df
