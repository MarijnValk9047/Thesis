from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np


PT_RESOLUTION_PATTERN = re.compile(r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?$")
PSR_LABELS = {"B16": "solar", "B18": "wind_offshore", "B19": "wind_onshore"}


@dataclass(frozen=True)
class CleaningTaskStatus:
    task_name: str
    status: str
    note: str
    output_path: str | None = None


def _solar_elevation_deg_approx(timestamp_utc: pd.Timestamp, latitude_deg: float, longitude_deg: float) -> float:
    ts = pd.Timestamp(timestamp_utc)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    day_of_year = int(ts.dayofyear)
    hour_utc = float(ts.hour + ts.minute / 60.0 + ts.second / 3600.0)
    gamma = 2.0 * np.pi / 365.0 * (day_of_year - 1 + (hour_utc - 12.0) / 24.0)
    decl = (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2 * gamma)
        + 0.000907 * np.sin(2 * gamma)
        - 0.002697 * np.cos(3 * gamma)
        + 0.00148 * np.sin(3 * gamma)
    )
    eq_time = 229.18 * (
        0.000075
        + 0.001868 * np.cos(gamma)
        - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2 * gamma)
        - 0.040849 * np.sin(2 * gamma)
    )
    time_offset_min = eq_time + 4.0 * longitude_deg
    true_solar_time_min = (hour_utc * 60.0 + time_offset_min) % 1440.0
    hour_angle_deg = true_solar_time_min / 4.0 - 180.0
    lat_rad = np.deg2rad(latitude_deg)
    ha_rad = np.deg2rad(hour_angle_deg)
    cos_zenith = np.sin(lat_rad) * np.sin(decl) + np.cos(lat_rad) * np.cos(decl) * np.cos(ha_rad)
    cos_zenith = float(np.clip(cos_zenith, -1.0, 1.0))
    zenith_deg = np.rad2deg(np.arccos(cos_zenith))
    return float(90.0 - zenith_deg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Staged cleaning for Lago LEAR six-year benchmark.")
    parser.add_argument("--run-cleaning", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--raw-root", type=Path, default=Path("data/00_raw_lago_lear_six_year"))
    parser.add_argument("--output-root", type=Path, default=Path("data/01_cleaned_lago_lear_six_year"))
    parser.add_argument("--start-local-date", type=str, default="2019-10-01")
    parser.add_argument("--end-exclusive-local-date", type=str, default="2025-10-01")
    parser.add_argument("--local-timezone", type=str, default="Europe/Amsterdam")
    parser.add_argument("--regions", nargs="+", default=["NL"])
    parser.add_argument("--res-max-missing-share", type=float, default=0.20)
    parser.add_argument("--res-min-coverage-share", type=float, default=0.90)
    parser.add_argument("--res-allow-partial-x2", action="store_true")
    parser.add_argument("--res-feature-ready-max-missing-share", type=float, default=0.10)
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


def _load_module(module_path: Path, module_name: str) -> Any:
    if not module_path.exists():
        raise FileNotFoundError(f"Missing module: {module_path}")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _known_at_day_ahead_local_08(timestamp_utc: pd.Timestamp, timezone: str) -> pd.Timestamp:
    local_day = timestamp_utc.tz_convert(timezone).date()
    local_known = pd.Timestamp(datetime.combine(local_day, time(hour=8, minute=0))).tz_localize(
        timezone,
        ambiguous="raise",
        nonexistent="raise",
    )
    return local_known.tz_convert("UTC")


def _parse_resolution(resolution: str | None) -> timedelta | None:
    if not resolution:
        return None
    match = PT_RESOLUTION_PATTERN.match(str(resolution).strip())
    if not match:
        return None
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    total_minutes = hours * 60 + minutes
    if total_minutes <= 0:
        return None
    return timedelta(minutes=total_minutes)


def _find_text(elem: ET.Element, path: str, ns: dict[str, str]) -> str | None:
    node = elem.find(path, ns)
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text if text else None


def _parse_a69_file(xml_path: Path, psr_type_fallback: str) -> list[dict[str, Any]]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    namespace = {"ns": root.tag.split("}", 1)[0].strip("{")} if "}" in root.tag else {"ns": ""}
    document_type = _find_text(root, "ns:type", namespace)
    process_type = _find_text(root, "ns:process.processType", namespace)
    created_dt = pd.to_datetime(_find_text(root, "ns:createdDateTime", namespace), utc=True, errors="coerce")

    rows: list[dict[str, Any]] = []
    for ts_idx, ts in enumerate(root.findall("ns:TimeSeries", namespace), start=1):
        psr_type = _find_text(ts, "ns:MktPSRType/ns:psrType", namespace) or psr_type_fallback
        for period_idx, period in enumerate(ts.findall("ns:Period", namespace), start=1):
            start_utc = pd.to_datetime(_find_text(period, "ns:timeInterval/ns:start", namespace), utc=True, errors="coerce")
            resolution_raw = _find_text(period, "ns:resolution", namespace)
            step = _parse_resolution(resolution_raw)
            if pd.isna(start_utc) or step is None:
                continue
            duration_minutes = int(step.total_seconds() // 60)
            for point in period.findall("ns:Point", namespace):
                pos_text = _find_text(point, "ns:position", namespace)
                qty_text = _find_text(point, "ns:quantity", namespace)
                try:
                    position = int(pos_text) if pos_text is not None else None
                except ValueError:
                    position = None
                if position is None:
                    continue
                quantity = pd.to_numeric(qty_text, errors="coerce")
                timestamp_utc = pd.Timestamp(start_utc + (position - 1) * step)
                rows.append(
                    {
                        "timestamp_utc": timestamp_utc,
                        "region": "NL",
                        "psr_type": psr_type,
                        "psr_label": PSR_LABELS.get(psr_type, psr_type.lower()),
                        "value_mw": float(quantity) if pd.notna(quantity) else pd.NA,
                        "source_document_type": document_type or "A69",
                        "process_type": process_type or "A01",
                        "source_file": xml_path.name,
                        "source_path": str(xml_path),
                        "created_datetime_utc": created_dt if pd.notna(created_dt) else pd.NaT,
                        "timeseries_index": ts_idx,
                        "period_index": period_idx,
                        "resolution": resolution_raw,
                        "duration_minutes": duration_minutes,
                    }
                )
    return rows


def _clean_a69_res_forecast(
    *,
    raw_root: Path,
    output_root: Path,
    timezone: str,
    start_local_date: str,
    end_exclusive_local_date: str,
    max_missing_share: float,
    min_coverage_share: float,
    allow_partial_x2: bool,
    feature_ready_max_missing_share: float,
) -> dict[str, Path]:
    raw_dir = raw_root / "RES_Generation_Forecast" / "NL" / "A69_DA_Wind_Solar_Forecast_By_PSR"
    out_native = output_root / "Generation/da_res_generation_forecast_by_psr/native/da_res_generation_forecast_by_psr_native_long.csv"
    out_by_psr = output_root / "Generation/da_res_generation_forecast_by_psr/hourly/da_res_generation_forecast_by_psr_hourly_long.csv"
    out_agg = output_root / "Generation/da_res_generation_forecast/hourly/da_res_generation_forecast_hourly_long.csv"
    out_by_psr_feature_ready = output_root / "Generation/da_res_generation_forecast_by_psr/hourly/da_res_generation_forecast_by_psr_hourly_feature_ready_long.csv"
    out_agg_feature_ready = output_root / "Generation/da_res_generation_forecast/hourly/da_res_generation_forecast_hourly_feature_ready_long.csv"
    coverage_path = output_root / "Generation/da_res_generation_forecast_by_psr/res_forecast_coverage_summary.csv"
    missing_path = output_root / "Generation/da_res_generation_forecast_by_psr/res_forecast_missingness_by_psr.csv"
    native_resolution_summary_path = output_root / "Generation/da_res_generation_forecast_by_psr/res_forecast_native_resolution_summary.csv"
    hourly_audit_path = output_root / "Generation/da_res_generation_forecast_by_psr/res_forecast_hourly_aggregation_audit.csv"
    validation_report_path = output_root / "Generation/da_res_generation_forecast_by_psr/cleaning_validation_report.csv"
    feature_diag_root = output_root / "Generation/da_res_generation_forecast/diagnostics"
    feature_policy_audit_path = feature_diag_root / "res_feature_ready_policy_audit.csv"
    feature_missingness_path = feature_diag_root / "res_feature_ready_missingness.csv"
    feature_daylight_audit_path = feature_diag_root / "res_feature_ready_daylight_solar_audit.csv"

    rows: list[dict[str, Any]] = []
    for psr_type, label in PSR_LABELS.items():
        psr_dir = raw_dir / f"{psr_type}_{label}"
        xml_files = sorted(psr_dir.glob("*.xml")) if psr_dir.exists() else []
        for xml_file in xml_files:
            try:
                rows.extend(_parse_a69_file(xml_file, psr_type_fallback=psr_type))
            except Exception as exc:  # noqa: BLE001
                logging.warning("Failed parsing %s: %s", xml_file, exc)

    if not rows:
        empty = pd.DataFrame(
            columns=[
                "timestamp_utc",
                "timestamp_local",
                "region",
                "psr_type",
                "psr_label",
                "value_mw",
                "source_document_type",
                "process_type",
                "known_at_utc",
                "known_at_rule",
                "source_file",
                "is_missing",
                "quality_flag",
            ]
        )
        out_native.parent.mkdir(parents=True, exist_ok=True)
        empty.to_csv(out_native, index=False)
        out_by_psr.parent.mkdir(parents=True, exist_ok=True)
        empty.to_csv(out_by_psr, index=False)
        out_agg.parent.mkdir(parents=True, exist_ok=True)
        empty.drop(columns=["psr_type", "psr_label"]).to_csv(out_agg, index=False)
        pd.DataFrame().to_csv(coverage_path, index=False)
        pd.DataFrame().to_csv(missing_path, index=False)
        return {
            "native": out_native,
            "by_psr": out_by_psr,
            "aggregate": out_agg,
            "by_psr_feature_ready": out_by_psr_feature_ready,
            "aggregate_feature_ready": out_agg_feature_ready,
            "native_resolution_summary": native_resolution_summary_path,
            "hourly_audit": hourly_audit_path,
            "coverage": coverage_path,
            "missingness": missing_path,
            "validation_report": validation_report_path,
            "feature_policy_audit": feature_policy_audit_path,
            "feature_missingness": feature_missingness_path,
            "feature_daylight_audit": feature_daylight_audit_path,
        }

    frame = pd.DataFrame(rows)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame["created_datetime_utc"] = pd.to_datetime(frame["created_datetime_utc"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp_utc"]).copy()
    frame = frame.sort_values(["timestamp_utc", "psr_type", "created_datetime_utc", "source_file"]).drop_duplicates(
        subset=["timestamp_utc", "psr_type"], keep="last"
    )
    frame["timestamp_local"] = frame["timestamp_utc"].dt.tz_convert(timezone)
    frame["known_at_utc"] = frame["timestamp_utc"].map(lambda ts: _known_at_day_ahead_local_08(pd.Timestamp(ts), timezone))
    frame["known_at_rule"] = "day_ahead_local_08_assumption_a69_psr"
    frame["is_missing"] = frame["value_mw"].isna()
    frame["quality_flag"] = ""
    frame = frame[
        [
            "timestamp_utc",
            "timestamp_local",
            "region",
            "psr_type",
            "psr_label",
            "value_mw",
            "source_document_type",
            "process_type",
            "known_at_utc",
            "known_at_rule",
            "source_file",
            "is_missing",
            "quality_flag",
            "duration_minutes",
        ]
    ].reset_index(drop=True)
    out_native.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_native, index=False)

    frame["timestamp_hour_utc"] = frame["timestamp_utc"].dt.floor("h")
    frame["duration_minutes"] = pd.to_numeric(frame["duration_minutes"], errors="coerce")
    frame["duration_minutes"] = frame["duration_minutes"].fillna(15.0)
    frame["duration_minutes"] = frame["duration_minutes"].clip(lower=1.0, upper=60.0)
    frame["weighted_value"] = frame["value_mw"] * frame["duration_minutes"]
    group_cols = ["timestamp_hour_utc", "region", "psr_type"]
    grouped = frame.groupby(group_cols, dropna=False)
    agg_base = grouped.agg(
        weighted_value_sum=("weighted_value", "sum"),
        duration_sum_non_missing=("duration_minutes", lambda s: float(s[frame.loc[s.index, "value_mw"].notna()].sum())),
        native_points_in_hour=("timestamp_utc", "size"),
        duration_min=("duration_minutes", "min"),
        source_document_type=("source_document_type", "first"),
        process_type=("process_type", "first"),
        psr_label=("psr_label", "first"),
        known_at_utc=("known_at_utc", "max"),
        known_at_rule=("known_at_rule", "first"),
        source_file=("source_file", lambda s: "|".join(sorted(set(s.dropna().astype(str).tolist()))[:10])),
        any_missing=("is_missing", "max"),
    ).reset_index()
    agg_base["expected_native_points_in_hour"] = (60.0 / agg_base["duration_min"]).round().astype("Int64")
    agg_base["expected_native_points_in_hour"] = agg_base["expected_native_points_in_hour"].clip(lower=1, upper=60)
    agg_base["incomplete_hour_flag"] = agg_base["native_points_in_hour"] < agg_base["expected_native_points_in_hour"]
    agg_base["value_mw"] = agg_base["weighted_value_sum"] / agg_base["duration_sum_non_missing"]
    agg_base.loc[agg_base["duration_sum_non_missing"] <= 0, "value_mw"] = pd.NA
    agg_base["is_missing"] = agg_base["any_missing"] | agg_base["incomplete_hour_flag"] | agg_base["value_mw"].isna()
    agg_base["quality_flag"] = agg_base["incomplete_hour_flag"].map(lambda v: "incomplete_hour" if bool(v) else "")
    agg_base["hourly_aggregation_method"] = "duration_weighted_mean_mw"
    agg_base["timestamp_utc"] = agg_base["timestamp_hour_utc"]
    agg_base["timestamp_local"] = pd.to_datetime(agg_base["timestamp_utc"], utc=True).dt.tz_convert(timezone)
    by_psr_hourly = agg_base[
        [
            "timestamp_utc",
            "timestamp_local",
            "region",
            "psr_type",
            "psr_label",
            "value_mw",
            "source_document_type",
            "process_type",
            "known_at_utc",
            "known_at_rule",
            "source_file",
            "is_missing",
            "quality_flag",
            "native_points_in_hour",
            "expected_native_points_in_hour",
            "hourly_aggregation_method",
            "incomplete_hour_flag",
        ]
    ].sort_values(["timestamp_utc", "region", "psr_type"]).reset_index(drop=True)
    out_by_psr.parent.mkdir(parents=True, exist_ok=True)
    by_psr_hourly.to_csv(out_by_psr, index=False)

    x2_wide = by_psr_hourly[by_psr_hourly["psr_type"].isin(["B16", "B18", "B19"])].pivot_table(
        index=["timestamp_utc", "timestamp_local", "region"],
        columns="psr_type",
        values="value_mw",
        aggfunc="first",
    ).reset_index()
    for psr in ["B16", "B18", "B19"]:
        if psr not in x2_wide.columns:
            x2_wide[psr] = pd.NA
    x2_wide["missing_component_count"] = x2_wide[["B16", "B18", "B19"]].isna().sum(axis=1)
    all_present = x2_wide["missing_component_count"] == 0
    x2_wide["value_mw"] = x2_wide[["B16", "B18", "B19"]].sum(axis=1, min_count=3 if not allow_partial_x2 else 1)
    if not allow_partial_x2:
        x2_wide.loc[~all_present, "value_mw"] = pd.NA
    known_at_x2 = (
        by_psr_hourly[by_psr_hourly["psr_type"].isin(["B16", "B18", "B19"])]
        .groupby(["timestamp_utc", "region"], dropna=False)["known_at_utc"]
        .max()
        .reset_index()
    )
    agg = x2_wide.merge(known_at_x2, on=["timestamp_utc", "region"], how="left")
    agg["source_document_type"] = "A69"
    agg["process_type"] = "A01"
    agg["known_at_rule"] = "day_ahead_local_08_assumption_a69_psr"
    agg["source_file"] = "aggregated_from_B16_B18_B19_hourly"
    agg["is_missing"] = agg["value_mw"].isna() | (~all_present if not allow_partial_x2 else False)
    agg["quality_flag"] = agg["missing_component_count"].map(lambda n: f"missing_components={int(n)}" if int(n) > 0 else "")
    agg = agg[
        [
            "timestamp_utc",
            "timestamp_local",
            "region",
            "value_mw",
            "source_document_type",
            "process_type",
            "known_at_utc",
            "known_at_rule",
            "source_file",
            "is_missing",
            "quality_flag",
        ]
    ].reset_index(drop=True)
    out_agg.parent.mkdir(parents=True, exist_ok=True)
    agg.to_csv(out_agg, index=False)

    # Feature-ready policy layer (strict outputs above remain audit reference).
    strict = by_psr_hourly.copy()
    strict["coverage_ratio"] = (
        pd.to_numeric(strict["native_points_in_hour"], errors="coerce")
        / pd.to_numeric(strict["expected_native_points_in_hour"], errors="coerce")
    )
    strict["coverage_ratio"] = strict["coverage_ratio"].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    min_ts = pd.to_datetime(strict["timestamp_utc"], utc=True).min()
    max_ts = pd.to_datetime(strict["timestamp_utc"], utc=True).max()
    full_hours = pd.date_range(start=min_ts, end=max_ts, freq="h", tz="UTC")
    full_idx = pd.MultiIndex.from_product(
        [full_hours, ["NL"], ["B16", "B18", "B19"]],
        names=["timestamp_utc", "region", "psr_type"],
    ).to_frame(index=False)
    feature = full_idx.merge(strict, on=["timestamp_utc", "region", "psr_type"], how="left", suffixes=("", "_strict"))
    feature["psr_label"] = feature["psr_type"].map(PSR_LABELS).fillna(feature.get("psr_label"))
    feature["timestamp_local"] = pd.to_datetime(feature["timestamp_utc"], utc=True).dt.tz_convert(timezone)
    feature["known_at_utc"] = feature["known_at_utc"].where(feature["known_at_utc"].notna(), feature["timestamp_utc"].map(lambda ts: _known_at_day_ahead_local_08(pd.Timestamp(ts), timezone)))
    feature["known_at_rule"] = feature["known_at_rule"].fillna("day_ahead_local_08_assumption_a69_psr")
    feature["source_document_type"] = feature["source_document_type"].fillna("A69")
    feature["process_type"] = feature["process_type"].fillna("A01")
    feature["hourly_aggregation_method"] = feature["hourly_aggregation_method"].fillna("duration_weighted_mean_mw")
    feature["native_points_in_hour"] = pd.to_numeric(feature["native_points_in_hour"], errors="coerce").fillna(0).astype("Int64")
    feature["expected_native_points_in_hour"] = pd.to_numeric(feature["expected_native_points_in_hour"], errors="coerce").fillna(4).astype("Int64")
    feature["coverage_ratio"] = (
        pd.to_numeric(feature["native_points_in_hour"], errors="coerce")
        / pd.to_numeric(feature["expected_native_points_in_hour"], errors="coerce")
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    feature["source_file"] = feature["source_file"].fillna("")

    feature["solar_elevation_deg"] = feature["timestamp_utc"].map(lambda ts: _solar_elevation_deg_approx(pd.Timestamp(ts), 52.1, 5.3))
    feature["is_daylight_nl"] = feature["solar_elevation_deg"] > -3.0

    feature["feature_ready_policy"] = ""
    feature["feature_ready_flag"] = ""
    feature["feature_ready_flag"] = feature["feature_ready_flag"].astype(str)
    feature["is_feature_ready_missing"] = True

    wind_mask = feature["psr_type"].isin(["B18", "B19"])
    wind_complete = wind_mask & (feature["native_points_in_hour"] >= 4) & feature["value_mw"].notna()
    wind_partial = wind_mask & (feature["native_points_in_hour"] >= 3) & feature["value_mw"].notna() & ~wind_complete
    wind_insufficient = wind_mask & ~(wind_complete | wind_partial)
    feature.loc[wind_complete, ["feature_ready_policy", "is_feature_ready_missing"]] = ["complete_hour", False]
    feature.loc[wind_partial, ["feature_ready_policy", "feature_ready_flag", "is_feature_ready_missing"]] = [
        "accepted_partial_hour_min_3_of_4",
        "partial_hour_accepted",
        False,
    ]
    feature.loc[wind_insufficient, ["feature_ready_policy", "is_feature_ready_missing"]] = ["insufficient_wind_coverage", True]

    solar_mask = feature["psr_type"] == "B16"
    solar_complete = solar_mask & (feature["native_points_in_hour"] >= 4) & feature["value_mw"].notna()
    solar_partial = solar_mask & (feature["native_points_in_hour"] >= 3) & feature["value_mw"].notna() & ~solar_complete
    solar_dark_lowcov = solar_mask & (feature["native_points_in_hour"] < 3) & (~feature["is_daylight_nl"])
    solar_day_lowcov = solar_mask & (feature["native_points_in_hour"] < 3) & feature["is_daylight_nl"]
    solar_dark_missing_row = solar_mask & (feature["native_points_in_hour"] == 0) & (~feature["is_daylight_nl"])
    solar_day_missing_row = solar_mask & (feature["native_points_in_hour"] == 0) & feature["is_daylight_nl"]
    feature.loc[solar_complete, ["feature_ready_policy", "is_feature_ready_missing"]] = ["complete_hour", False]
    feature.loc[solar_partial, ["feature_ready_policy", "feature_ready_flag", "is_feature_ready_missing"]] = [
        "accepted_partial_hour_min_3_of_4",
        "partial_hour_accepted",
        False,
    ]
    feature.loc[solar_dark_lowcov, "value_mw"] = 0.0
    feature.loc[solar_dark_lowcov, ["feature_ready_policy", "feature_ready_flag", "is_feature_ready_missing"]] = [
        "solar_zero_filled_dark_hour",
        "solar_zero_fill_dark_hour",
        False,
    ]
    feature.loc[solar_dark_missing_row, "value_mw"] = 0.0
    feature.loc[solar_dark_missing_row, ["feature_ready_policy", "feature_ready_flag", "is_feature_ready_missing"]] = [
        "solar_zero_filled_missing_dark_hour",
        "solar_zero_fill_missing_dark_hour",
        False,
    ]
    feature.loc[solar_day_lowcov, ["feature_ready_policy", "is_feature_ready_missing"]] = ["insufficient_solar_coverage_daylight", True]
    feature.loc[solar_day_missing_row, ["feature_ready_policy", "is_feature_ready_missing"]] = ["missing_solar_daylight", True]

    feature["feature_ready_flag"] = feature["feature_ready_flag"].replace({"nan": ""}).fillna("")
    feature["feature_ready_policy"] = feature["feature_ready_policy"].replace("", "unclassified")
    feature["feature_ready_policy"] = feature["feature_ready_policy"].astype(str)
    feature["feature_ready_flag"] = feature["feature_ready_flag"].astype(str)
    feature["is_feature_ready_missing"] = feature["is_feature_ready_missing"].astype(bool)

    feature["quality_flag"] = np.where(
        feature["is_feature_ready_missing"],
        feature["feature_ready_policy"],
        feature["quality_flag"].fillna(""),
    )

    by_psr_feature_ready = feature[
        [
            "timestamp_utc",
            "timestamp_local",
            "region",
            "psr_type",
            "psr_label",
            "value_mw",
            "source_document_type",
            "process_type",
            "known_at_utc",
            "known_at_rule",
            "source_file",
            "is_missing",
            "quality_flag",
            "native_points_in_hour",
            "expected_native_points_in_hour",
            "coverage_ratio",
            "hourly_aggregation_method",
            "incomplete_hour_flag",
            "is_daylight_nl",
            "solar_elevation_deg",
            "feature_ready_policy",
            "feature_ready_flag",
            "is_feature_ready_missing",
        ]
    ].sort_values(["timestamp_utc", "psr_type"]).reset_index(drop=True)
    out_by_psr_feature_ready.parent.mkdir(parents=True, exist_ok=True)
    by_psr_feature_ready.to_csv(out_by_psr_feature_ready, index=False)

    fr_wide = by_psr_feature_ready.pivot_table(
        index=["timestamp_utc", "timestamp_local", "region"],
        columns="psr_type",
        values="value_mw",
        aggfunc="first",
    ).reset_index()
    fr_miss = by_psr_feature_ready.pivot_table(
        index=["timestamp_utc", "timestamp_local", "region"],
        columns="psr_type",
        values="is_feature_ready_missing",
        aggfunc="first",
    ).reset_index()
    fr_pol = by_psr_feature_ready.pivot_table(
        index=["timestamp_utc", "timestamp_local", "region"],
        columns="psr_type",
        values="feature_ready_policy",
        aggfunc="first",
    ).reset_index()
    fr_flag = by_psr_feature_ready.pivot_table(
        index=["timestamp_utc", "timestamp_local", "region"],
        columns="psr_type",
        values="feature_ready_flag",
        aggfunc="first",
    ).reset_index()
    fr_known = (
        by_psr_feature_ready.groupby(["timestamp_utc", "timestamp_local", "region"], dropna=False)["known_at_utc"]
        .max()
        .reset_index()
    )
    fr = fr_wide.merge(fr_miss, on=["timestamp_utc", "timestamp_local", "region"], suffixes=("", "_miss"), how="left")
    fr = fr.merge(fr_pol, on=["timestamp_utc", "timestamp_local", "region"], suffixes=("", "_pol"), how="left")
    fr = fr.merge(fr_flag, on=["timestamp_utc", "timestamp_local", "region"], suffixes=("", "_flag"), how="left")
    fr = fr.merge(fr_known, on=["timestamp_utc", "timestamp_local", "region"], how="left")
    for psr in ["B16", "B18", "B19"]:
        if psr not in fr.columns:
            fr[psr] = pd.NA
        if f"{psr}_miss" not in fr.columns:
            fr[f"{psr}_miss"] = True
        if f"{psr}_pol" not in fr.columns:
            fr[f"{psr}_pol"] = "missing"
        if f"{psr}_flag" not in fr.columns:
            fr[f"{psr}_flag"] = ""
    fr["x2_components_complete"] = (~fr["B16_miss"].astype(bool)) & (~fr["B18_miss"].astype(bool)) & (~fr["B19_miss"].astype(bool))
    fr["x2_res_forecast_mw"] = fr[["B16", "B18", "B19"]].sum(axis=1, min_count=3)
    fr.loc[~fr["x2_components_complete"], "x2_res_forecast_mw"] = pd.NA
    fr["missing_components"] = fr.apply(
        lambda r: ",".join([psr for psr in ["B16", "B18", "B19"] if bool(r[f"{psr}_miss"])]),
        axis=1,
    )
    fr["is_missing"] = ~fr["x2_components_complete"]
    fr["quality_flag"] = fr["missing_components"].map(lambda s: f"missing_components:{s}" if s else "")
    fr["source_document_type"] = "A69"
    fr["process_type"] = "A01"
    fr["known_at_rule"] = "day_ahead_local_08_assumption_a69_psr"
    fr["source_file"] = "feature_ready_aggregated_from_B16_B18_B19"
    agg_feature_ready = fr[
        [
            "timestamp_utc",
            "timestamp_local",
            "region",
            "x2_res_forecast_mw",
            "source_document_type",
            "process_type",
            "known_at_utc",
            "known_at_rule",
            "source_file",
            "is_missing",
            "quality_flag",
            "B16",
            "B18",
            "B19",
            "B16_pol",
            "B18_pol",
            "B19_pol",
            "B16_flag",
            "B18_flag",
            "B19_flag",
            "x2_components_complete",
        ]
    ].rename(
        columns={
            "x2_res_forecast_mw": "value_mw",
            "B16": "b16_value_mw",
            "B18": "b18_value_mw",
            "B19": "b19_value_mw",
            "B16_pol": "b16_policy",
            "B18_pol": "b18_policy",
            "B19_pol": "b19_policy",
            "B16_flag": "b16_feature_ready_flag",
            "B18_flag": "b18_feature_ready_flag",
            "B19_flag": "b19_feature_ready_flag",
        }
    ).sort_values("timestamp_utc").reset_index(drop=True)
    out_agg_feature_ready.parent.mkdir(parents=True, exist_ok=True)
    agg_feature_ready.to_csv(out_agg_feature_ready, index=False)

    feature_diag_root.mkdir(parents=True, exist_ok=True)
    policy_audit = (
        by_psr_feature_ready.groupby(["psr_type", "feature_ready_policy"], dropna=False)
        .agg(rows=("timestamp_utc", "size"))
        .reset_index()
        .sort_values(["psr_type", "rows"], ascending=[True, False])
    )
    policy_audit.to_csv(feature_policy_audit_path, index=False)
    feature_missingness = agg_feature_ready.assign(
        year=pd.to_datetime(agg_feature_ready["timestamp_local"], errors="coerce").dt.year.astype("Int64"),
        month=pd.to_datetime(agg_feature_ready["timestamp_local"], errors="coerce").dt.month.astype("Int64"),
    ).groupby(["year", "month"], dropna=False)["is_missing"].mean().rename("missing_share").reset_index()
    feature_missingness.to_csv(feature_missingness_path, index=False)
    daylight_audit = (
        by_psr_feature_ready[by_psr_feature_ready["psr_type"] == "B16"]
        .groupby(["is_daylight_nl", "feature_ready_policy"], dropna=False)
        .agg(rows=("timestamp_utc", "size"))
        .reset_index()
        .sort_values(["is_daylight_nl", "rows"], ascending=[True, False])
    )
    daylight_audit.to_csv(feature_daylight_audit_path, index=False)

    coverage = (
        by_psr_hourly.groupby("psr_type", dropna=False)
        .agg(
            rows=("timestamp_utc", "size"),
            min_timestamp_utc=("timestamp_utc", "min"),
            max_timestamp_utc=("timestamp_utc", "max"),
            missing_values=("is_missing", "sum"),
        )
        .reset_index()
    )
    coverage["min_timestamp_utc"] = pd.to_datetime(coverage["min_timestamp_utc"], utc=True).astype(str)
    coverage["max_timestamp_utc"] = pd.to_datetime(coverage["max_timestamp_utc"], utc=True).astype(str)
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(coverage_path, index=False)

    minute_diag_before = (
        frame.assign(minute=frame["timestamp_utc"].dt.minute, year=frame["timestamp_local"].dt.year.astype("Int64"))
        .groupby(["psr_type", "year", "minute"], dropna=False)["is_missing"]
        .mean()
        .rename("missing_share")
        .reset_index()
        .assign(stage="native")
    )
    minute_diag_after = (
        by_psr_hourly.assign(minute=by_psr_hourly["timestamp_utc"].dt.minute, year=by_psr_hourly["timestamp_local"].dt.year.astype("Int64"))
        .groupby(["psr_type", "year", "minute"], dropna=False)["is_missing"]
        .mean()
        .rename("missing_share")
        .reset_index()
        .assign(stage="hourly")
    )
    miss = pd.concat([minute_diag_before, minute_diag_after], ignore_index=True)
    missing_path.parent.mkdir(parents=True, exist_ok=True)
    miss.to_csv(missing_path, index=False)

    native_resolution_summary = (
        frame.assign(minute=frame["timestamp_utc"].dt.minute)
        .groupby(["psr_type", "duration_minutes", "minute"], dropna=False)
        .agg(rows=("timestamp_utc", "size"))
        .reset_index()
        .sort_values(["psr_type", "duration_minutes", "minute"])
    )
    native_resolution_summary_path.parent.mkdir(parents=True, exist_ok=True)
    native_resolution_summary.to_csv(native_resolution_summary_path, index=False)

    hourly_audit = by_psr_hourly[
        [
            "timestamp_utc",
            "region",
            "psr_type",
            "native_points_in_hour",
            "expected_native_points_in_hour",
            "hourly_aggregation_method",
            "incomplete_hour_flag",
            "is_missing",
        ]
    ]
    hourly_audit_path.parent.mkdir(parents=True, exist_ok=True)
    hourly_audit.to_csv(hourly_audit_path, index=False)

    validation_rows: list[dict[str, Any]] = []
    by_psr_minutes_ok = bool((by_psr_hourly["timestamp_utc"].dt.minute == 0).all())
    validation_rows.append({"check": "by_psr_hourly_minute_zero", "passed": by_psr_minutes_ok, "value": int((by_psr_hourly["timestamp_utc"].dt.minute != 0).sum())})
    agg_minutes_ok = bool((agg["timestamp_utc"].dt.minute == 0).all())
    validation_rows.append({"check": "aggregate_hourly_minute_zero", "passed": agg_minutes_ok, "value": int((agg["timestamp_utc"].dt.minute != 0).sum())})
    dup_by_psr = int(by_psr_hourly.duplicated(subset=["timestamp_utc", "region", "psr_type"]).sum())
    validation_rows.append({"check": "by_psr_no_duplicates", "passed": dup_by_psr == 0, "value": dup_by_psr})
    dup_agg = int(agg.duplicated(subset=["timestamp_utc", "region"]).sum())
    validation_rows.append({"check": "aggregate_no_duplicates", "passed": dup_agg == 0, "value": dup_agg})
    missing_known = int(by_psr_hourly["known_at_utc"].isna().sum() + agg["known_at_utc"].isna().sum())
    validation_rows.append({"check": "known_at_not_missing", "passed": missing_known == 0, "value": missing_known})
    start_utc = pd.Timestamp(start_local_date).tz_localize(timezone).tz_convert("UTC")
    end_utc = pd.Timestamp(end_exclusive_local_date).tz_localize(timezone).tz_convert("UTC")
    expected_hours = int(len(pd.date_range(start=start_utc, end=end_utc - pd.Timedelta(hours=1), freq="h", tz="UTC")))
    slice_by_psr = by_psr_hourly[(by_psr_hourly["timestamp_utc"] >= start_utc) & (by_psr_hourly["timestamp_utc"] < end_utc)]
    psr_cov = (
        slice_by_psr.groupby("psr_type", dropna=False)["timestamp_utc"].nunique().reset_index(name="observed_hours")
    )
    psr_cov["coverage_share"] = psr_cov["observed_hours"] / float(expected_hours) if expected_hours > 0 else pd.NA
    for row in psr_cov.itertuples(index=False):
        validation_rows.append(
            {
                "check": f"coverage_{row.psr_type}",
                "passed": bool(row.coverage_share >= min_coverage_share),
                "value": float(row.coverage_share),
            }
        )
    miss_share = float(by_psr_hourly["is_missing"].mean()) if not by_psr_hourly.empty else 1.0
    validation_rows.append({"check": "missing_share_threshold", "passed": miss_share <= max_missing_share, "value": miss_share})
    fr_by_psr_minutes_ok = bool((by_psr_feature_ready["timestamp_utc"].dt.minute == 0).all())
    validation_rows.append({"check": "feature_ready_by_psr_minute_zero", "passed": fr_by_psr_minutes_ok, "value": int((by_psr_feature_ready["timestamp_utc"].dt.minute != 0).sum())})
    fr_agg_minutes_ok = bool((agg_feature_ready["timestamp_utc"].dt.minute == 0).all())
    validation_rows.append({"check": "feature_ready_aggregate_minute_zero", "passed": fr_agg_minutes_ok, "value": int((agg_feature_ready["timestamp_utc"].dt.minute != 0).sum())})
    fr_dup_by_psr = int(by_psr_feature_ready.duplicated(subset=["timestamp_utc", "psr_type"]).sum())
    validation_rows.append({"check": "feature_ready_by_psr_no_duplicates", "passed": fr_dup_by_psr == 0, "value": fr_dup_by_psr})
    fr_dup_agg = int(agg_feature_ready.duplicated(subset=["timestamp_utc"]).sum())
    validation_rows.append({"check": "feature_ready_aggregate_no_duplicates", "passed": fr_dup_agg == 0, "value": fr_dup_agg})
    fr_missing_known = int(
        by_psr_feature_ready.loc[~by_psr_feature_ready["is_feature_ready_missing"], "known_at_utc"].isna().sum()
        + agg_feature_ready.loc[~agg_feature_ready["is_missing"], "known_at_utc"].isna().sum()
    )
    validation_rows.append({"check": "feature_ready_known_at_not_missing_for_accepted_rows", "passed": fr_missing_known == 0, "value": fr_missing_known})
    benchmark_start_utc = pd.Timestamp("2019-10-01").tz_localize(timezone).tz_convert("UTC")
    benchmark_end_utc = pd.Timestamp("2025-10-01").tz_localize(timezone).tz_convert("UTC")
    fr_benchmark = agg_feature_ready[(agg_feature_ready["timestamp_utc"] >= benchmark_start_utc) & (agg_feature_ready["timestamp_utc"] < benchmark_end_utc)]
    fr_missing_share = float(fr_benchmark["is_missing"].mean()) if not fr_benchmark.empty else 1.0
    validation_rows.append(
        {
            "check": "feature_ready_aggregate_missing_share_benchmark",
            "passed": fr_missing_share <= float(feature_ready_max_missing_share),
            "value": fr_missing_share,
        }
    )

    validation = pd.DataFrame(validation_rows)
    validation_path_dir = validation_report_path.parent
    validation_path_dir.mkdir(parents=True, exist_ok=True)
    validation.to_csv(validation_report_path, index=False)

    return {
        "native": out_native,
        "by_psr": out_by_psr,
        "aggregate": out_agg,
        "by_psr_feature_ready": out_by_psr_feature_ready,
        "aggregate_feature_ready": out_agg_feature_ready,
        "native_resolution_summary": native_resolution_summary_path,
        "hourly_audit": hourly_audit_path,
        "coverage": coverage_path,
        "missingness": missing_path,
        "validation_report": validation_report_path,
        "feature_policy_audit": feature_policy_audit_path,
        "feature_missingness": feature_missingness_path,
        "feature_daylight_audit": feature_daylight_audit_path,
    }


def _compute_cleaned_data_audit(output_root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for csv_path in sorted(output_root.rglob("*.csv")):
        try:
            frame = pd.read_csv(csv_path, nrows=5000)
        except Exception:  # noqa: BLE001
            continue
        timestamp_col = "timestamp_utc" if "timestamp_utc" in frame.columns else None
        min_ts = None
        max_ts = None
        if timestamp_col is not None:
            ts = pd.to_datetime(frame[timestamp_col], utc=True, errors="coerce").dropna()
            if not ts.empty:
                min_ts = ts.min().isoformat()
                max_ts = ts.max().isoformat()
        rows.append(
            {
                "path": str(csv_path),
                "sample_rows_read": int(frame.shape[0]),
                "column_count": int(frame.shape[1]),
                "columns": ",".join(frame.columns.tolist()),
                "min_timestamp_utc": min_ts,
                "max_timestamp_utc": max_ts,
            }
        )
    return pd.DataFrame(rows).sort_values("path").reset_index(drop=True) if rows else pd.DataFrame()


def _known_at_audit(output_root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for csv_path in sorted(output_root.rglob("*hourly_long.csv")):
        try:
            frame = pd.read_csv(csv_path)
        except Exception:  # noqa: BLE001
            continue
        if "known_at_utc" not in frame.columns:
            rows.append(
                {
                    "path": str(csv_path),
                    "has_known_at_utc": False,
                    "missing_known_at_count": None,
                    "known_at_rule_values": None,
                }
            )
            continue
        known_at = pd.to_datetime(frame["known_at_utc"], utc=True, errors="coerce")
        rows.append(
            {
                "path": str(csv_path),
                "has_known_at_utc": True,
                "missing_known_at_count": int(known_at.isna().sum()),
                "known_at_rule_values": ",".join(sorted(set(frame.get("known_at_rule", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()))),
            }
        )
    return pd.DataFrame(rows).sort_values("path").reset_index(drop=True) if rows else pd.DataFrame()


def main() -> None:
    args = parse_args()
    audit_root = args.output_root / "lago_cleaning_audit"
    plan_path = audit_root / "cleaning_plan.json"
    status_path = audit_root / "cleaning_status.csv"
    cleaned_audit_path = audit_root / "cleaned_data_audit.csv"
    missingness_report_path = audit_root / "missingness_report.csv"
    known_at_audit_path = audit_root / "known_at_audit.csv"
    log_path = audit_root / "cleaning_log.txt"
    configure_logging(log_path, args.log_level)

    tasks: list[dict[str, Any]] = [
        {
            "task": "day_ahead_prices_pipeline",
            "raw_root": str(args.raw_root / "DA_Prices"),
            "output_root": str(args.output_root / "Day_ahead_prices"),
        },
        {
            "task": "entsoe_system_features_pipeline",
            "raw_root": str(args.raw_root),
            "output_root": str(args.output_root),
            "markets": args.regions,
        },
        {
            "task": "a69_res_forecast_by_psr_cleaning",
            "raw_root": str(args.raw_root / "RES_Generation_Forecast/NL/A69_DA_Wind_Solar_Forecast_By_PSR"),
            "output_root": str(args.output_root / "Generation"),
        },
    ]
    audit_root.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(tasks, indent=2), encoding="utf-8")

    statuses: list[CleaningTaskStatus] = []
    if not args.run_cleaning and not args.dry_run:
        statuses.append(
            CleaningTaskStatus(
                task_name="all",
                status="no_op",
                note="No --run-cleaning or --dry-run flag provided.",
            )
        )
        pd.DataFrame([asdict(item) for item in statuses]).to_csv(status_path, index=False)
        return

    if args.dry_run and not args.run_cleaning:
        statuses.extend(
            [
                CleaningTaskStatus("day_ahead_prices_pipeline", "dry_run_only", "No execution.", str(args.output_root / "Day_ahead_prices")),
                CleaningTaskStatus("entsoe_system_features_pipeline", "dry_run_only", "No execution.", str(args.output_root)),
                CleaningTaskStatus("a69_res_forecast_by_psr_cleaning", "dry_run_only", "No execution.", str(args.output_root / "Generation")),
            ]
        )
        pd.DataFrame([asdict(item) for item in statuses]).to_csv(status_path, index=False)
        return

    # Run day-ahead cleaning
    try:
        day_ahead_module = _load_module(Path("scripts/Data/01_cleaning/day_ahead_prices_pipeline.py"), "day_ahead_prices_pipeline")
        end_exclusive_local = pd.Timestamp(str(args.end_exclusive_local_date)).date()
        cutoff_local = pd.Timestamp(str(args.end_exclusive_local_date))
        cutoff_local = cutoff_local.tz_localize(args.local_timezone)
        max_ts_utc = (cutoff_local.tz_convert("UTC") - pd.Timedelta(minutes=1)).isoformat()
        day_ahead_module.run(
            raw_root=args.raw_root / "DA_Prices",
            output_root=args.output_root / "Day_ahead_prices",
            cutoff_local_date=str(args.end_exclusive_local_date),
            local_timezone=str(args.local_timezone),
            regions=[str(value).upper() for value in args.regions],
            quarterly_regions=set(),
            max_timestamp_utc_str=max_ts_utc,
        )
        statuses.append(
            CleaningTaskStatus(
                task_name="day_ahead_prices_pipeline",
                status="completed",
                note="Ran staged DA price cleaning.",
                output_path=str(args.output_root / "Day_ahead_prices"),
            )
        )
    except Exception as exc:  # noqa: BLE001
        statuses.append(
            CleaningTaskStatus(
                task_name="day_ahead_prices_pipeline",
                status="failed",
                note=str(exc),
                output_path=str(args.output_root / "Day_ahead_prices"),
            )
        )

    # Run ENTSOE system features cleaning
    try:
        entsoe_module = _load_module(Path("scripts/Data/01_cleaning/entsoe_system_features_pipeline.py"), "entsoe_system_features_pipeline")
        family_lookup = {family.name: family for family in entsoe_module.FAMILY_CONFIGS}
        family_names = [
            "actual_total_load",
            "da_total_load_forecast",
            "week_ahead_total_load_forecast",
            "da_generation_forecast",
            "actual_generation_by_psr",
            "installed_capacity_by_psr",
        ]
        manifest_rows: list[dict[str, Any]] = []
        for family_name in family_names:
            family = family_lookup.get(family_name)
            if family is None:
                statuses.append(
                    CleaningTaskStatus(
                        task_name=f"entsoe_family::{family_name}",
                        status="missing_family_config",
                        note="Family missing in entsoe_system_features_pipeline.py",
                    )
                )
                continue
            summary = entsoe_module.process_family(
                raw_root=args.raw_root,
                output_root=args.output_root,
                markets=[str(value).upper() for value in args.regions],
                family=family,
            )
            manifest_rows.append(summary)
            statuses.append(
                CleaningTaskStatus(
                    task_name=f"entsoe_family::{family_name}",
                    status="completed",
                    note=f"rows_hourly={summary.get('rows_hourly')}",
                    output_path=str(summary.get("hourly_long_path")),
                )
            )
        if manifest_rows:
            pd.DataFrame(manifest_rows).to_csv(args.output_root / "entsoe_feature_family_manifest.csv", index=False)
    except Exception as exc:  # noqa: BLE001
        statuses.append(
            CleaningTaskStatus(
                task_name="entsoe_system_features_pipeline",
                status="failed",
                note=str(exc),
                output_path=str(args.output_root),
            )
        )

    # Run staged A69 by-PSR cleaner and aggregate builder.
    try:
        paths = _clean_a69_res_forecast(
            raw_root=args.raw_root,
            output_root=args.output_root,
            timezone=str(args.local_timezone),
            start_local_date=str(args.start_local_date),
            end_exclusive_local_date=str(args.end_exclusive_local_date),
            max_missing_share=float(args.res_max_missing_share),
            min_coverage_share=float(args.res_min_coverage_share),
            allow_partial_x2=bool(args.res_allow_partial_x2),
            feature_ready_max_missing_share=float(args.res_feature_ready_max_missing_share),
        )
        statuses.append(
            CleaningTaskStatus(
                task_name="a69_res_forecast_by_psr_cleaning",
                status="completed",
                note="Parsed A69 by-PSR and built aggregated RES forecast.",
                output_path=str(paths["by_psr"]),
            )
        )
    except Exception as exc:  # noqa: BLE001
        statuses.append(
            CleaningTaskStatus(
                task_name="a69_res_forecast_by_psr_cleaning",
                status="failed",
                note=str(exc),
                output_path=str(args.output_root / "Generation"),
            )
        )

    # Audits
    cleaned_audit = _compute_cleaned_data_audit(args.output_root)
    known_audit = _known_at_audit(args.output_root)
    missing_rows: list[dict[str, Any]] = []
    for csv_path in sorted(args.output_root.rglob("*hourly_long.csv")):
        try:
            frame = pd.read_csv(csv_path)
        except Exception:  # noqa: BLE001
            continue
        missing_rows.append(
            {
                "path": str(csv_path),
                "rows": int(frame.shape[0]),
                "missing_value_cells": int(frame.isna().sum().sum()),
                "missing_value_mw_rows": int(frame["value_mw"].isna().sum()) if "value_mw" in frame.columns else None,
                "missing_price_rows": int(frame["price_eur_per_mwh"].isna().sum()) if "price_eur_per_mwh" in frame.columns else None,
            }
        )
    missing_report = pd.DataFrame(missing_rows).sort_values("path").reset_index(drop=True) if missing_rows else pd.DataFrame()

    pd.DataFrame([asdict(item) for item in statuses]).to_csv(status_path, index=False)
    cleaned_audit.to_csv(cleaned_audit_path, index=False)
    missing_report.to_csv(missingness_report_path, index=False)
    known_audit.to_csv(known_at_audit_path, index=False)
    logging.info("Wrote cleaning artifacts under %s", audit_root)


if __name__ == "__main__":
    main()
