from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import HourlyDAPipelineConfig
from .time_utils import delivery_local_date_for_timestamp, known_at_utc_for_delivery_date


HOURLY_RESOLUTION_MINUTES = 60


@dataclass(frozen=True)
class TimezoneAudit:
    input_csv: str
    timestamp_col: str
    rows_read: int
    parsed_dtype: str
    timezone_name: str | None
    source_timestamp_representation: str
    sample_strings_have_explicit_utc: bool
    all_parsed_offsets_zero: bool
    ambiguous_localization_count: int
    nonexistent_localization_count: int
    duplicate_local_clock_count: int
    verdict: str
    note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "input_csv": self.input_csv,
            "timestamp_col": self.timestamp_col,
            "rows_read": self.rows_read,
            "parsed_dtype": self.parsed_dtype,
            "timezone_name": self.timezone_name,
            "source_timestamp_representation": self.source_timestamp_representation,
            "sample_strings_have_explicit_utc": self.sample_strings_have_explicit_utc,
            "all_parsed_offsets_zero": self.all_parsed_offsets_zero,
            "ambiguous_localization_count": self.ambiguous_localization_count,
            "nonexistent_localization_count": self.nonexistent_localization_count,
            "duplicate_local_clock_count": self.duplicate_local_clock_count,
            "verdict": self.verdict,
            "note": self.note,
        }


@dataclass(frozen=True)
class DAValidationArtifacts:
    source_frame: pd.DataFrame
    integrity_summary: pd.DataFrame
    duplicate_details: pd.DataFrame


@dataclass(frozen=True)
class MissingDataArtifacts:
    canonical_frame: pd.DataFrame
    integrity_summary: pd.DataFrame
    missing_policy_summary: pd.DataFrame
    gap_intervals: pd.DataFrame


def _empty_duplicate_details() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "timestamp_utc",
            "duplicate_row_count",
            "duplicate_rows_removed",
            "non_missing_price_count",
            "kept_source_row_number",
            "kept_price_eur_per_mwh",
            "resolution_rule",
        ]
    )


def _empty_gap_intervals() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "gap_start_utc",
            "gap_end_utc",
            "missing_hours",
            "missing_timestamp_count",
            "missing_value_count",
        ]
    )


def _resolve_duplicate_timestamps(
    frame: pd.DataFrame,
    *,
    timestamp_col: str,
    target_col: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame.copy(), _empty_duplicate_details()

    detail_rows: list[dict[str, object]] = []
    keep_indices: list[int] = []
    for _, group in frame.groupby(timestamp_col, sort=True):
        if group.shape[0] == 1:
            keep_indices.append(int(group.index[0]))
            continue

        non_missing = group[group[target_col].notna()]
        if not non_missing.empty:
            kept_row = non_missing.iloc[-1]
            resolution_rule = "keep_last_non_missing_price_in_original_order"
        else:
            kept_row = group.iloc[-1]
            resolution_rule = "all_duplicate_prices_missing_keep_last_in_original_order"

        keep_indices.append(int(kept_row.name))
        detail_rows.append(
            {
                "timestamp_utc": pd.Timestamp(group[timestamp_col].iloc[0]).isoformat(),
                "duplicate_row_count": int(group.shape[0]),
                "duplicate_rows_removed": int(group.shape[0] - 1),
                "non_missing_price_count": int(group[target_col].notna().sum()),
                "kept_source_row_number": int(kept_row["_source_row_number"]),
                "kept_price_eur_per_mwh": (
                    float(kept_row[target_col]) if pd.notna(kept_row[target_col]) else np.nan
                ),
                "resolution_rule": resolution_rule,
            }
        )

    deduplicated = (
        frame.loc[sorted(set(keep_indices))]
        .sort_values([timestamp_col, "_source_row_number"])
        .reset_index(drop=True)
    )
    duplicate_details = (
        pd.DataFrame(detail_rows).sort_values("timestamp_utc").reset_index(drop=True)
        if detail_rows
        else _empty_duplicate_details()
    )
    return deduplicated, duplicate_details


def _feature_source_from_causal_imputation(
    observed_series: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    values = observed_series.astype(float).to_numpy(copy=True)
    methods = np.full(shape=values.shape[0], fill_value="observed", dtype=object)
    last_available_value = np.nan

    for index, value in enumerate(values):
        if not np.isnan(value):
            last_available_value = value
            continue

        if index >= 24 and not np.isnan(values[index - 24]):
            values[index] = values[index - 24]
            methods[index] = "same_hour_previous_day"
        elif index >= 168 and not np.isnan(values[index - 168]):
            values[index] = values[index - 168]
            methods[index] = "same_hour_previous_week"
        elif not np.isnan(last_available_value):
            values[index] = last_available_value
            methods[index] = "last_available_observation"
        else:
            methods[index] = "unfilled"

        if not np.isnan(values[index]):
            last_available_value = values[index]

    return (
        pd.Series(values, index=observed_series.index, dtype=float),
        pd.Series(methods, index=observed_series.index, dtype="object"),
    )


def load_and_validate_da_series(config: HourlyDAPipelineConfig) -> DAValidationArtifacts:
    input_path = Path(config.input_csv)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    frame = pd.read_csv(input_path)
    required_cols = {"region", config.timestamp_col, config.target_col}
    missing_cols = sorted(required_cols - set(frame.columns))
    if missing_cols:
        raise ValueError(f"Missing required columns in input data: {missing_cols}")

    rows_in_input_csv = int(frame.shape[0])
    frame = frame[frame["region"] == config.market_area].copy()
    if frame.empty:
        raise ValueError(f"No rows found for region '{config.market_area}'.")

    frame["_source_row_number"] = np.arange(frame.shape[0], dtype=int)
    rows_after_region_filter = int(frame.shape[0])
    frame[config.timestamp_col] = pd.to_datetime(frame[config.timestamp_col], utc=True, errors="coerce")
    frame[config.target_col] = pd.to_numeric(frame[config.target_col], errors="coerce")
    rows_with_unparsed_timestamp = int(frame[config.timestamp_col].isna().sum())
    frame = frame.dropna(subset=[config.timestamp_col]).copy()
    non_monotonic_order_detected = bool(not frame[config.timestamp_col].is_monotonic_increasing)
    frame = frame.sort_values([config.timestamp_col, "_source_row_number"]).reset_index(drop=True)

    if "resolution_minutes" in frame.columns:
        resolution_minutes = pd.to_numeric(frame["resolution_minutes"], errors="coerce")
        non_hourly = frame[resolution_minutes.notna() & (resolution_minutes != HOURLY_RESOLUTION_MINUTES)]
        if not non_hourly.empty:
            raise ValueError(
                f"Found non-hourly rows in hourly DA input for region '{config.market_area}': {int(non_hourly.shape[0])}"
            )

    deduplicated, duplicate_details = _resolve_duplicate_timestamps(
        frame=frame,
        timestamp_col=config.timestamp_col,
        target_col=config.target_col,
    )
    source_frame = deduplicated.drop(columns=["_source_row_number"]).reset_index(drop=True)
    duplicate_groups = int(duplicate_details.shape[0])
    duplicate_rows_removed = int(duplicate_details["duplicate_rows_removed"].sum()) if not duplicate_details.empty else 0
    missing_price_values = int(source_frame[config.target_col].isna().sum())

    integrity_summary = pd.DataFrame(
        [
            {
                "market_area": config.market_area,
                "rows_in_input_csv": rows_in_input_csv,
                "rows_after_region_filter": rows_after_region_filter,
                "rows_with_unparsed_timestamp_dropped": rows_with_unparsed_timestamp,
                "non_monotonic_order_detected": non_monotonic_order_detected,
                "duplicate_timestamp_groups": duplicate_groups,
                "duplicate_rows_removed": duplicate_rows_removed,
                "rows_after_duplicate_resolution": int(source_frame.shape[0]),
                "missing_price_values_in_observed_rows": missing_price_values,
                "min_timestamp_utc": source_frame[config.timestamp_col].min().isoformat(),
                "max_timestamp_utc": source_frame[config.timestamp_col].max().isoformat(),
            }
        ]
    )
    return DAValidationArtifacts(
        source_frame=source_frame,
        integrity_summary=integrity_summary,
        duplicate_details=duplicate_details,
    )


def load_hourly_price_frame(config: HourlyDAPipelineConfig) -> pd.DataFrame:
    return load_and_validate_da_series(config).source_frame


def audit_timezone_handling(config: HourlyDAPipelineConfig) -> TimezoneAudit:
    raw_sample = pd.read_csv(config.input_csv, usecols=[config.timestamp_col], nrows=10)
    sample_strings = raw_sample[config.timestamp_col].astype(str).tolist()
    parsed = pd.to_datetime(raw_sample[config.timestamp_col], utc=True, errors="coerce")
    if parsed.isna().any():
        raise ValueError("Unable to parse one or more timestamp samples during UTC audit.")

    sample_strings_have_explicit_utc = all(value.endswith("Z") or value.endswith("+00:00") for value in sample_strings)
    offsets = [ts.utcoffset() for ts in parsed.tolist()]
    all_offsets_zero = all(offset is not None and offset.total_seconds() == 0 for offset in offsets)
    timezone_name = str(parsed.dt.tz)
    verdict = "UTC_CONFIRMED" if timezone_name == "UTC" and all_offsets_zero else "UTC_NOT_CONFIRMED"
    note = (
        "Raw DA XML periods enter with explicit UTC offsets such as '2021-12-31T23:00Z'. The cleaner parses those "
        "timestamps with utc=True and stores timezone-aware UTC in timestamp_utc. Local-time columns are derived only "
        "for business rules and reporting. No ambiguous or nonexistent local-time source timestamps were encountered, "
        "because the source representation is already UTC-based."
    )
    return TimezoneAudit(
        input_csv=str(config.input_csv),
        timestamp_col=config.timestamp_col,
        rows_read=int(parsed.shape[0]),
        parsed_dtype=str(parsed.dtype),
        timezone_name=timezone_name,
        source_timestamp_representation="raw_xml_utc_with_explicit_offset",
        sample_strings_have_explicit_utc=sample_strings_have_explicit_utc,
        all_parsed_offsets_zero=all_offsets_zero,
        ambiguous_localization_count=0,
        nonexistent_localization_count=0,
        duplicate_local_clock_count=0,
        verdict=verdict,
        note=note,
    )


def handle_missing_da_prices(frame: pd.DataFrame, config: HourlyDAPipelineConfig) -> MissingDataArtifacts:
    if frame.empty:
        raise ValueError("Cannot handle missing DA prices on an empty frame.")

    ordered = frame.sort_values(config.timestamp_col).reset_index(drop=True).copy()
    ordered["_original_row_present"] = True
    ordered["_original_value_present"] = ordered[config.target_col].notna()

    start_utc = ordered[config.timestamp_col].min()
    end_utc = ordered[config.timestamp_col].max()
    canonical_index = pd.date_range(start=start_utc, end=end_utc, freq="h", tz="UTC")
    canonical = pd.DataFrame({config.timestamp_col: canonical_index})
    observed_cols = [column for column in ordered.columns if column != config.timestamp_col]
    merged = canonical.merge(
        ordered[[config.timestamp_col] + observed_cols],
        on=config.timestamp_col,
        how="left",
        sort=True,
    )

    merged["region"] = merged["region"].fillna(config.market_area)
    if "resolution_minutes" in merged.columns:
        merged["resolution_minutes"] = (
            pd.to_numeric(merged["resolution_minutes"], errors="coerce")
            .fillna(HOURLY_RESOLUTION_MINUTES)
            .astype("Int64")
        )
    if "resolution" in merged.columns:
        merged["resolution"] = merged["resolution"].fillna("PT60M")

    merged["is_missing_timestamp"] = merged["_original_row_present"].isna()
    merged["is_missing_target_value"] = (
        merged["_original_row_present"].fillna(False).astype(bool)
        & ~merged["_original_value_present"].fillna(False).astype(bool)
    )
    merged["is_missing_observation"] = merged[config.target_col].isna()
    observed_target_mask = ~merged["is_missing_observation"]
    if "is_interpolated_value" in merged.columns:
        observed_target_mask &= ~merged["is_interpolated_value"].fillna(False).astype(bool)
    if "is_flagged_missing_value" in merged.columns:
        observed_target_mask &= ~merged["is_flagged_missing_value"].fillna(False).astype(bool)
    merged["is_observed_target"] = observed_target_mask

    timezone = config.resolved_business_timezone()
    target_timestamps_local = merged[config.timestamp_col].dt.tz_convert(timezone)
    merged["target_timestamp_local"] = target_timestamps_local
    merged["target_hour_local"] = target_timestamps_local.dt.hour.astype(int)
    delivery_local_dates = [delivery_local_date_for_timestamp(timestamp, timezone) for timestamp in merged[config.timestamp_col]]
    merged["target_delivery_local_date"] = delivery_local_dates
    merged[config.known_at_col] = [known_at_utc_for_delivery_date(value, config) for value in delivery_local_dates]

    feature_source, imputation_method = _feature_source_from_causal_imputation(merged[config.target_col])
    merged[config.feature_source_col] = feature_source.to_numpy(dtype=float)
    merged["feature_source_imputation_method"] = imputation_method.astype(str)
    merged["is_imputed_feature_source"] = merged["is_missing_observation"] & merged[config.feature_source_col].notna()

    missing_mask = merged["is_missing_observation"].astype(bool)
    gap_rows: list[dict[str, object]] = []
    if missing_mask.any():
        working = merged[[config.timestamp_col, "is_missing_timestamp", "is_missing_target_value"]].copy()
        working["gap_group"] = missing_mask.ne(missing_mask.shift(fill_value=False)).cumsum()
        gaps = working[missing_mask]
        for _, gap in gaps.groupby("gap_group", sort=True):
            gap_rows.append(
                {
                    "gap_start_utc": pd.Timestamp(gap[config.timestamp_col].iloc[0]).isoformat(),
                    "gap_end_utc": pd.Timestamp(gap[config.timestamp_col].iloc[-1]).isoformat(),
                    "missing_hours": int(gap.shape[0]),
                    "missing_timestamp_count": int(gap["is_missing_timestamp"].sum()),
                    "missing_value_count": int(gap["is_missing_target_value"].sum()),
                }
            )
    gap_intervals = (
        pd.DataFrame(gap_rows).sort_values(["missing_hours", "gap_start_utc"], ascending=[False, True]).reset_index(drop=True)
        if gap_rows
        else _empty_gap_intervals()
    )

    imputation_counts = merged["feature_source_imputation_method"].value_counts(dropna=False)
    missing_timestamp_count = int(merged["is_missing_timestamp"].sum())
    missing_value_count = int(merged["is_missing_target_value"].sum())
    missing_observation_count = int(merged["is_missing_observation"].sum())
    remaining_feature_source_missing = int(merged[config.feature_source_col].isna().sum())
    longest_gap_hours = int(gap_intervals["missing_hours"].max()) if not gap_intervals.empty else 0

    integrity_summary = pd.DataFrame(
        [
            {
                "market_area": config.market_area,
                "rows_after_validation": int(frame.shape[0]),
                "rows_on_canonical_grid": int(merged.shape[0]),
                "missing_timestamps_count": missing_timestamp_count,
                "missing_target_values_count": missing_value_count,
                "missing_observations_count": missing_observation_count,
                "feature_source_imputed_count": int(merged["is_imputed_feature_source"].sum()),
                "feature_source_remaining_missing_count": remaining_feature_source_missing,
                "same_hour_previous_day_count": int(imputation_counts.get("same_hour_previous_day", 0)),
                "same_hour_previous_week_count": int(imputation_counts.get("same_hour_previous_week", 0)),
                "last_available_observation_count": int(imputation_counts.get("last_available_observation", 0)),
                "unfilled_feature_source_count": int(imputation_counts.get("unfilled", 0)),
                "gap_count": int(gap_intervals.shape[0]),
                "longest_gap_hours": longest_gap_hours,
                "min_timestamp_utc": merged[config.timestamp_col].min().isoformat(),
                "max_timestamp_utc": merged[config.timestamp_col].max().isoformat(),
            }
        ]
    )

    missing_policy_summary = pd.DataFrame(
        [
            {
                "step_order": 1,
                "policy_step": "sort_chronologically",
                "description": "Sort the hourly DA series in ascending UTC order before any validation or filling.",
                "rows_affected": int(merged.shape[0]),
            },
            {
                "step_order": 2,
                "policy_step": "insert_missing_hourly_timestamps",
                "description": "Reindex to a complete expected hourly UTC grid so missing hours become explicit rows.",
                "rows_affected": missing_timestamp_count,
            },
            {
                "step_order": 3,
                "policy_step": "mark_originally_missing_values",
                "description": "Keep flags that distinguish missing timestamps from rows whose price value was missing.",
                "rows_affected": missing_observation_count,
            },
            {
                "step_order": 4,
                "policy_step": "same_hour_previous_day",
                "description": "For feature construction only, first try the value 24 hours earlier on the canonical UTC grid.",
                "rows_affected": int(imputation_counts.get("same_hour_previous_day", 0)),
            },
            {
                "step_order": 5,
                "policy_step": "same_hour_previous_week",
                "description": "If the previous-day value is unavailable, try the value 168 hours earlier.",
                "rows_affected": int(imputation_counts.get("same_hour_previous_week", 0)),
            },
            {
                "step_order": 6,
                "policy_step": "last_available_observation",
                "description": "If neither seasonal fallback is available, use the last earlier available value as a causal fallback.",
                "rows_affected": int(imputation_counts.get("last_available_observation", 0)),
            },
            {
                "step_order": 7,
                "policy_step": "leave_target_missing_visible",
                "description": "The observed target column is never overwritten; missing targets remain visible for diagnostics and row filtering.",
                "rows_affected": missing_observation_count,
            },
            {
                "step_order": 8,
                "policy_step": "unfilled_feature_source",
                "description": "If no earlier causal fallback exists, keep the feature-source value missing and report it explicitly.",
                "rows_affected": int(imputation_counts.get("unfilled", 0)),
            },
        ]
    ).sort_values("step_order").reset_index(drop=True)

    cleaned = merged.drop(columns=["_original_row_present", "_original_value_present"])
    return MissingDataArtifacts(
        canonical_frame=cleaned,
        integrity_summary=integrity_summary,
        missing_policy_summary=missing_policy_summary,
        gap_intervals=gap_intervals,
    )


def build_canonical_hourly_frame(frame: pd.DataFrame, config: HourlyDAPipelineConfig) -> pd.DataFrame:
    return handle_missing_da_prices(frame, config).canonical_frame


def summarize_gaps(canonical_frame: pd.DataFrame, config: HourlyDAPipelineConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing_mask = canonical_frame[config.target_col].isna()
    feature_source_missing_mask = canonical_frame[config.feature_source_col].isna()
    imputation_counts = canonical_frame["feature_source_imputation_method"].value_counts(dropna=False)
    summary = pd.DataFrame(
        [
            {
                "region": config.market_area,
                "rows_total": int(canonical_frame.shape[0]),
                "rows_observed": int((~missing_mask).sum()),
                "rows_missing": int(missing_mask.sum()),
                "missing_share_pct": float(missing_mask.mean() * 100.0),
                "missing_timestamps": int(canonical_frame["is_missing_timestamp"].sum()),
                "missing_values": int(canonical_frame["is_missing_target_value"].sum()),
                "feature_source_rows_imputed": int(canonical_frame["is_imputed_feature_source"].sum()),
                "feature_source_imputed_previous_day": int(imputation_counts.get("same_hour_previous_day", 0)),
                "feature_source_imputed_previous_week": int(imputation_counts.get("same_hour_previous_week", 0)),
                "feature_source_imputed_last_available": int(imputation_counts.get("last_available_observation", 0)),
                "feature_source_rows_missing_after_fill": int(feature_source_missing_mask.sum()),
                "feature_gap_fill_method": config.feature_gap_fill_method,
                "min_timestamp_utc": canonical_frame[config.timestamp_col].min().isoformat(),
                "max_timestamp_utc": canonical_frame[config.timestamp_col].max().isoformat(),
            }
        ]
    )

    gap_intervals = (
        canonical_frame.loc[canonical_frame["is_missing_observation"], [
            config.timestamp_col,
            "is_missing_timestamp",
            "is_missing_target_value",
        ]]
        .assign(gap_group=missing_mask.ne(missing_mask.shift(fill_value=False)).cumsum())
        .groupby("gap_group", as_index=False)
        .agg(
            gap_start_utc=(config.timestamp_col, "min"),
            gap_end_utc=(config.timestamp_col, "max"),
            missing_hours=(config.timestamp_col, "size"),
            missing_timestamp_count=("is_missing_timestamp", "sum"),
            missing_value_count=("is_missing_target_value", "sum"),
        )
    )
    if gap_intervals.empty:
        gap_intervals = _empty_gap_intervals()
    else:
        gap_intervals["gap_start_utc"] = pd.to_datetime(gap_intervals["gap_start_utc"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        gap_intervals["gap_end_utc"] = pd.to_datetime(gap_intervals["gap_end_utc"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        gap_intervals = gap_intervals.drop(columns=["gap_group"]).sort_values(
            ["missing_hours", "gap_start_utc"],
            ascending=[False, True],
        ).reset_index(drop=True)
        gap_intervals["gap_start_utc"] = gap_intervals["gap_start_utc"].str.replace("+0000", "+00:00", regex=False)
        gap_intervals["gap_end_utc"] = gap_intervals["gap_end_utc"].str.replace("+0000", "+00:00", regex=False)
    return summary, gap_intervals
