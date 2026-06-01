from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Any
import warnings

import numpy as np
import pandas as pd

from .plant_parameters import HydrogenConfig, load_hydrogen_config
from .scenario_loader import ScenarioArtifactSpec, load_scenarios_for_artifact, resolve_artifact_specs


TZ = "Europe/Amsterdam"
VALIDATION_START = pd.Timestamp("2023-10-01")
VALIDATION_END = pd.Timestamp("2024-09-30")
TEST_START = pd.Timestamp("2024-10-01")
TEST_END = pd.Timestamp("2025-09-30")
EXPECTED_SCENARIO_COUNT = 75
ACTUAL_PRICE_PATH = Path("data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv")

ARTIFACT_LABELS: dict[str, str] = {
    "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support": "LEAR Strict",
    "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate": "LEAR FS3",
    "hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate": "XGBoost FS3",
}

ARTIFACT_SHORT_NAMES: dict[str, str] = {
    "hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support": "lear_strict",
    "hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate": "lear_fs3",
    "hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate": "xgboost_fs3",
}

INTENDED_REGIME_LABELS = (
    "typical_summer",
    "typical_winter",
    "high_volatility",
    "high_price",
)
VALIDATION_SELECTED_REGIME_LABELS = (
    "typical_summer",
    "winter_proxy",
    "high_volatility",
    "high_price",
)
TEST_SELECTED_REGIME_LABELS = INTENDED_REGIME_LABELS
SEASONAL_TYPICALITY_METRICS = (
    "actual_price_mean",
    "actual_price_std",
    "actual_price_spread",
    "price_iqr",
    "high_price_hours",
    "negative_price_hours",
)


@dataclass(frozen=True)
class CommonSupportAuditResult:
    validation_results: pd.DataFrame
    common_support_days: pd.DataFrame
    candidate_weeks: pd.DataFrame
    selected_weeks: pd.DataFrame
    selected_week_checks: pd.DataFrame
    metadata: dict[str, Any]


def _period_type(delivery_date: pd.Timestamp) -> str:
    normalized = pd.Timestamp(delivery_date).normalize()
    if VALIDATION_START <= normalized <= VALIDATION_END:
        return "validation"
    if TEST_START <= normalized <= TEST_END:
        return "test"
    return "outside_split"


def _expected_hours_for_local_day(delivery_date: pd.Timestamp | str) -> int:
    timestamp = pd.Timestamp(delivery_date)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(TZ).tz_localize(None)
    local_midnight = timestamp.normalize()
    day_start = local_midnight.tz_localize(TZ)
    day_end = (local_midnight + pd.Timedelta(days=1)).tz_localize(TZ)
    hours = (day_end.tz_convert("UTC") - day_start.tz_convert("UTC")) / pd.Timedelta(hours=1)
    return int(hours)


def _hourly_spacing_valid(values: pd.Series) -> bool:
    timestamps = pd.to_datetime(values, utc=True, errors="coerce").dropna().sort_values().drop_duplicates()
    if timestamps.empty:
        return False
    if len(timestamps) == 1:
        return True
    diffs = timestamps.diff().dropna()
    return bool((diffs == pd.Timedelta(hours=1)).all())


def _read_scenarios(spec: ScenarioArtifactSpec, *, config: HydrogenConfig) -> tuple[pd.DataFrame, list[str]]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=pd.errors.DtypeWarning)
        return load_scenarios_for_artifact(spec, config=config)


def _load_actual_prices(repo_root: Path) -> pd.DataFrame:
    path = (repo_root / ACTUAL_PRICE_PATH).resolve()
    usecols = [
        "timestamp_utc",
        "region",
        "price_eur_per_mwh",
        "resolution_minutes",
        "is_interpolated_value",
        "is_flagged_missing_value",
        "gap_fix_action",
    ]
    actual = pd.read_csv(path, usecols=usecols)
    actual = actual.loc[(actual["region"].astype(str) == "NL") & (actual["resolution_minutes"].astype(float) == 60.0)].copy()
    actual["timestamp_utc"] = pd.to_datetime(actual["timestamp_utc"], utc=True, errors="coerce")
    actual["delivery_start_utc"] = actual["timestamp_utc"]
    actual["delivery_date"] = actual["timestamp_utc"].dt.tz_convert(TZ).dt.tz_localize(None).dt.normalize()
    actual["delivery_date_str"] = actual["delivery_date"].dt.strftime("%Y-%m-%d")
    actual["is_interpolated_value"] = actual["is_interpolated_value"].fillna(False).astype(bool)
    actual["is_flagged_missing_value"] = actual["is_flagged_missing_value"].fillna(False).astype(bool)
    actual["price_eur_per_mwh"] = pd.to_numeric(actual["price_eur_per_mwh"], errors="coerce")
    return actual.sort_values("delivery_start_utc").reset_index(drop=True)


def _build_actual_day_summary(actual: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for delivery_date, group in actual.groupby("delivery_date", sort=True):
        expected_hours = _expected_hours_for_local_day(delivery_date)
        duplicate_count = int(
            group.duplicated(subset=["delivery_start_utc"], keep=False).sum()
        )
        interpolated_count = int(group["is_interpolated_value"].sum())
        flagged_count = int(group["is_flagged_missing_value"].sum())
        hourly_spacing_valid = _hourly_spacing_valid(group["delivery_start_utc"])
        complete = (
            int(group["delivery_start_utc"].nunique()) == expected_hours
            and duplicate_count == 0
            and interpolated_count == 0
            and flagged_count == 0
            and hourly_spacing_valid
        )
        reasons: list[str] = []
        if int(group["delivery_start_utc"].nunique()) != expected_hours:
            reasons.append(f"actual_hours_{int(group['delivery_start_utc'].nunique())}_expected_{expected_hours}")
        if duplicate_count:
            reasons.append(f"actual_duplicate_rows_{duplicate_count}")
        if interpolated_count:
            reasons.append(f"actual_interpolated_rows_{interpolated_count}")
        if flagged_count:
            reasons.append(f"actual_flagged_rows_{flagged_count}")
        if not hourly_spacing_valid:
            reasons.append("actual_timestamp_spacing_invalid")
        rows.append(
            {
                "delivery_date": pd.Timestamp(delivery_date).normalize(),
                "delivery_date_str": pd.Timestamp(delivery_date).strftime("%Y-%m-%d"),
                "expected_hours_local_day": expected_hours,
                "n_hours_actual": int(group["delivery_start_utc"].nunique()),
                "complete_actual_prices": bool(complete),
                "actual_missing_reason": "; ".join(reasons),
            }
        )
    return pd.DataFrame(rows).sort_values("delivery_date").reset_index(drop=True)


def _validate_artifact_frame(spec: ScenarioArtifactSpec, frame: pd.DataFrame) -> dict[str, Any]:
    unique_rows = frame[["forecast_origin_utc", "scenario_id", "scenario_probability"]].drop_duplicates()
    probability_blocks = (
        unique_rows.groupby("forecast_origin_utc", as_index=False)
        .agg(
            scenario_count=("scenario_id", "nunique"),
            probability_sum=("scenario_probability", "sum"),
        )
        .sort_values("forecast_origin_utc")
        .reset_index(drop=True)
    )
    duplicate_row_count = int(
        frame.duplicated(subset=["forecast_origin_utc", "delivery_start_utc", "scenario_id", "model_id"], keep=False).sum()
    )
    delivery_days = pd.to_datetime(frame["delivery_day"], errors="coerce")
    return {
        "artifact_key": spec.artifact_key,
        "artifact_label": ARTIFACT_LABELS.get(spec.artifact_key, spec.artifact_key),
        "path": str(spec.path),
        "artifact_exists": bool(spec.path.exists()),
        "validation_mode": str(spec.validation_mode),
        "forecast_origin_explicit": bool(frame["forecast_origin_utc"].notna().all()) and not bool(
            frame["allow_forecast_origin_reconstruction"].astype(bool).any()
        ),
        "granularity_values": ",".join(sorted(frame["granularity"].dropna().astype(str).unique().tolist())),
        "lead_day_values": ",".join(sorted({str(int(value)) for value in frame["lead_day"].dropna().astype(int).tolist()})),
        "scenario_count_min": int(probability_blocks["scenario_count"].min()),
        "scenario_count_max": int(probability_blocks["scenario_count"].max()),
        "probability_sum_min": float(probability_blocks["probability_sum"].min()),
        "probability_sum_max": float(probability_blocks["probability_sum"].max()),
        "duplicate_row_count": duplicate_row_count,
        "delivery_start_min_utc": frame["delivery_start_utc"].min().isoformat(),
        "delivery_start_max_utc": frame["delivery_start_utc"].max().isoformat(),
        "delivery_date_min": delivery_days.min().strftime("%Y-%m-%d"),
        "delivery_date_max": delivery_days.max().strftime("%Y-%m-%d"),
        "n_delivery_days": int(delivery_days.dt.normalize().nunique()),
        "n_forecast_origins": int(frame["forecast_origin_utc"].nunique()),
        "actual_price_missing_rows": int(frame["actual_price_eur_per_mwh"].isna().sum()),
        "status": "pass",
        "message": "Artifact passed thesis-grade validation and day-level prechecks.",
    }


def _build_artifact_day_summary(frame: pd.DataFrame, artifact_key: str) -> pd.DataFrame:
    hourly = (
        frame[["forecast_origin_utc", "delivery_start_utc", "delivery_day", "actual_price_eur_per_mwh", "lead_day", "granularity"]]
        .drop_duplicates(subset=["forecast_origin_utc", "delivery_start_utc"])
        .copy()
    )
    scenario_counts = (
        frame[["forecast_origin_utc", "scenario_id", "scenario_probability"]]
        .drop_duplicates(subset=["forecast_origin_utc", "scenario_id"])
        .groupby("forecast_origin_utc", as_index=False)
        .agg(
            n_scenarios_per_origin=("scenario_id", "nunique"),
            probability_sum=("scenario_probability", "sum"),
        )
    )
    duplicate_counts = (
        frame.assign(
            duplicate_flag=frame.duplicated(
                subset=["forecast_origin_utc", "delivery_start_utc", "scenario_id", "model_id"],
                keep=False,
            )
        )
        .groupby("forecast_origin_utc", as_index=False)["duplicate_flag"]
        .sum()
        .rename(columns={"duplicate_flag": "duplicate_row_count"})
    )
    origin_summary = (
        hourly.groupby("forecast_origin_utc", as_index=False)
        .agg(
            delivery_date=("delivery_day", "first"),
            n_hours=("delivery_start_utc", "nunique"),
            missing_actual_rows=("actual_price_eur_per_mwh", lambda s: int(pd.to_numeric(s, errors="coerce").isna().sum())),
            granularity_value=("granularity", lambda s: ",".join(sorted(s.dropna().astype(str).unique().tolist()))),
            lead_day_min=("lead_day", "min"),
            lead_day_max=("lead_day", "max"),
        )
        .merge(scenario_counts, on="forecast_origin_utc", how="left")
        .merge(duplicate_counts, on="forecast_origin_utc", how="left")
    )
    origin_summary["duplicate_row_count"] = origin_summary["duplicate_row_count"].fillna(0).astype(int)
    origin_summary["delivery_date"] = pd.to_datetime(origin_summary["delivery_date"], errors="coerce").dt.normalize()
    timestamp_spacing = (
        hourly.groupby("forecast_origin_utc")["delivery_start_utc"]
        .apply(_hourly_spacing_valid)
        .rename("hourly_spacing_valid")
        .reset_index()
    )
    origin_summary = origin_summary.merge(timestamp_spacing, on="forecast_origin_utc", how="left")
    origin_summary["expected_hours_local_day"] = origin_summary["delivery_date"].apply(_expected_hours_for_local_day)

    rows: list[dict[str, Any]] = []
    for delivery_date, group in origin_summary.groupby("delivery_date", sort=True):
        reasons: list[str] = []
        if int(group["forecast_origin_utc"].nunique()) != 1:
            reasons.append(f"origin_count_{int(group['forecast_origin_utc'].nunique())}")
        row = group.iloc[0]
        if int(row["n_hours"]) != int(row["expected_hours_local_day"]):
            reasons.append(f"hours_{int(row['n_hours'])}_expected_{int(row['expected_hours_local_day'])}")
        if int(row["n_scenarios_per_origin"]) != EXPECTED_SCENARIO_COUNT:
            reasons.append(f"scenario_count_{int(row['n_scenarios_per_origin'])}")
        if not np.isclose(float(row["probability_sum"]), 1.0, atol=1e-6):
            reasons.append(f"probability_sum_{float(row['probability_sum']):.6f}")
        if int(row["duplicate_row_count"]) != 0:
            reasons.append(f"duplicate_rows_{int(row['duplicate_row_count'])}")
        if int(row["missing_actual_rows"]) != 0:
            reasons.append(f"artifact_actual_missing_{int(row['missing_actual_rows'])}")
        if str(row["granularity_value"]).lower() != "hourly":
            reasons.append(f"granularity_{row['granularity_value']}")
        if not (int(row["lead_day_min"]) == 0 and int(row["lead_day_max"]) == 0):
            reasons.append(f"lead_day_{int(row['lead_day_min'])}_{int(row['lead_day_max'])}")
        if not bool(row["hourly_spacing_valid"]):
            reasons.append("artifact_timestamp_spacing_invalid")
        rows.append(
            {
                "delivery_date": pd.Timestamp(delivery_date).normalize(),
                "delivery_date_str": pd.Timestamp(delivery_date).strftime("%Y-%m-%d"),
                "expected_hours_local_day": int(row["expected_hours_local_day"]),
                "n_hours": int(row["n_hours"]),
                "n_scenarios_per_origin": int(row["n_scenarios_per_origin"]),
                "probability_sum": float(row["probability_sum"]),
                "n_origins": int(group["forecast_origin_utc"].nunique()),
                "complete": len(reasons) == 0,
                "missing_reason": "; ".join(reasons),
                "artifact_key": artifact_key,
            }
        )
    return pd.DataFrame(rows).sort_values("delivery_date").reset_index(drop=True)


def _support_segments(day_support: pd.DataFrame, period_type: str) -> list[dict[str, Any]]:
    subset = day_support.loc[
        (day_support["period_type"] == period_type) & day_support["common_complete_support"].astype(bool),
        ["delivery_date"],
    ].sort_values("delivery_date")
    if subset.empty:
        return []
    diffs = subset["delivery_date"].diff().dt.days.fillna(1)
    segment_ids = diffs.ne(1).cumsum()
    segments: list[dict[str, Any]] = []
    for _, group in subset.assign(segment_id=segment_ids).groupby("segment_id"):
        segments.append(
            {
                "start": group["delivery_date"].min().strftime("%Y-%m-%d"),
                "end": group["delivery_date"].max().strftime("%Y-%m-%d"),
                "n_days": int(group.shape[0]),
            }
        )
    return segments


def _season_label(week_days: pd.Series) -> str:
    months = pd.to_datetime(week_days, errors="raise").dt.month
    counts = {
        "winter": int(months.isin([12, 1, 2]).sum()),
        "spring": int(months.isin([3, 4, 5]).sum()),
        "summer": int(months.isin([6, 7, 8]).sum()),
        "autumn": int(months.isin([9, 10, 11]).sum()),
    }
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def _candidate_period_label(period_types: set[str]) -> str:
    if len(period_types) == 1:
        period = next(iter(period_types))
        return period if period in {"validation", "test"} else "outside_split"
    return "outside_split"


def _rank(series: pd.Series, *, ascending: bool) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.notna().sum() == 0:
        return pd.Series(np.nan, index=series.index)
    return values.rank(method="average", pct=True, ascending=ascending)


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows_"
    display = frame.copy()
    headers = [str(column) for column in display.columns]
    rows = [[str(value) for value in row] for row in display.to_numpy().tolist()]
    separator = ["---"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _typicality_score(subset: pd.DataFrame) -> pd.Series:
    if subset.empty:
        return pd.Series(dtype=float)
    ranks = pd.concat(
        [_rank(subset[column], ascending=True) for column in SEASONAL_TYPICALITY_METRICS],
        axis=1,
    )
    distances = ranks.sub(0.5).abs().mul(2.0)
    return 1.0 - distances.mean(axis=1)


def _score_candidate_weeks(candidate_weeks: pd.DataFrame) -> pd.DataFrame:
    scored = candidate_weeks.copy()
    scored["volatility_score"] = np.nan
    scored["high_price_score"] = np.nan
    scored["low_price_score"] = np.nan
    scored["typical_overall_score"] = np.nan
    scored["typical_summer_score"] = np.nan
    scored["typical_winter_score"] = np.nan
    for period_type in ["validation", "test"]:
        mask = (
            (scored["period_type"] == period_type)
            & (scored["number_of_delivery_days"] == 7)
            & scored["complete_for_all_models"].astype(bool)
            & scored["complete_actual_prices"].astype(bool)
            & ~scored["dst_flag"].astype(bool)
        )
        subset = scored.loc[mask].copy()
        if subset.empty:
            continue
        volatility = pd.concat(
            [
                _rank(subset["actual_price_std"], ascending=True),
                _rank(subset["price_iqr"], ascending=True),
                _rank(subset["actual_price_spread"], ascending=True),
            ],
            axis=1,
        ).mean(axis=1)
        high_price = pd.concat(
            [
                _rank(subset["actual_price_mean"], ascending=True),
                _rank(subset["peak_price"], ascending=True),
                _rank(subset["high_price_hours"], ascending=True),
            ],
            axis=1,
        ).mean(axis=1)
        low_price = pd.concat(
            [
                _rank(subset["actual_price_mean"], ascending=False),
                _rank(subset["negative_price_hours"], ascending=True),
                _rank(subset["actual_price_min"], ascending=False),
            ],
            axis=1,
        ).mean(axis=1)
        scored.loc[mask, "volatility_score"] = volatility.to_numpy()
        scored.loc[mask, "high_price_score"] = high_price.to_numpy()
        scored.loc[mask, "low_price_score"] = low_price.to_numpy()
        scored.loc[mask, "typical_overall_score"] = _typicality_score(subset).to_numpy()
        for season_label in ["summer", "winter"]:
            season_subset = subset.loc[subset["season_label"].astype(str) == season_label].copy()
            if season_subset.empty:
                continue
            scored.loc[season_subset.index, f"typical_{season_label}_score"] = _typicality_score(season_subset).to_numpy()
    return scored


def _pick_week(
    candidates: pd.DataFrame,
    selected_ids: set[str],
    *,
    week_label: str,
    regime_label: str,
    selection_reason: str,
    selection_rule: str,
    selection_status: str,
    dedicated_regime_candidate: bool,
    target_season: str,
    fallback_reason: str,
    sort_columns: list[str],
    ascending: list[bool],
) -> dict[str, Any] | None:
    ranked = candidates.sort_values(sort_columns, ascending=ascending).reset_index(drop=True)
    skipped = 0
    for row in ranked.to_dict(orient="records"):
        candidate_week_id = str(row["candidate_week_id"])
        if candidate_week_id in selected_ids:
            skipped += 1
            continue
        note = "calendar_week_monday_to_sunday; high_price_threshold_eur_per_mwh=158.0"
        if skipped:
            note += f"; skipped_{skipped}_higher_ranked_overlapping_selection(s)"
        return {
            "week_id": candidate_week_id,
            "period_type": str(row["period_type"]),
            "week_label": week_label,
            "regime_label": regime_label,
            "delivery_start_date": str(row["delivery_start_date"]),
            "delivery_end_date": str(row["delivery_end_date"]),
            "number_of_delivery_days": int(row["number_of_delivery_days"]),
            "selection_reason": selection_reason,
            "selection_rule": selection_rule,
            "selection_status": selection_status,
            "dedicated_regime_candidate": bool(dedicated_regime_candidate),
            "target_season": target_season,
            "fallback_reason": fallback_reason,
            "actual_price_mean": float(row["actual_price_mean"]),
            "actual_price_std": float(row["actual_price_std"]),
            "actual_price_min": float(row["actual_price_min"]),
            "actual_price_max": float(row["actual_price_max"]),
            "actual_price_spread": float(row["actual_price_spread"]),
            "negative_price_hours": int(row["negative_price_hours"]),
            "high_price_hours": int(row["high_price_hours"]),
            "peak_price": float(row["peak_price"]),
            "price_iqr": float(row["price_iqr"]),
            "volatility_score": float(row["volatility_score"]),
            "high_price_score": float(row["high_price_score"]),
            "low_price_score": float(row["low_price_score"]),
            "typical_overall_score": float(row["typical_overall_score"]),
            "typical_summer_score": float(row["typical_summer_score"]) if pd.notna(row["typical_summer_score"]) else float("nan"),
            "typical_winter_score": float(row["typical_winter_score"]) if pd.notna(row["typical_winter_score"]) else float("nan"),
            "season_label": str(row["season_label"]),
            "complete_for_lear_strict": True,
            "complete_for_lear_fs3": True,
            "complete_for_xgboost_fs3": True,
            "complete_actual_prices": True,
            "support_status": "common_complete_support_selected",
            "methodological_use": "cvar_selection" if str(row["period_type"]) == "validation" else "diagnostic_reporting",
            "notes": note,
            "proxy_for_regime_label": "typical_winter" if regime_label == "winter_proxy" else "",
            "seasonal_claims_valid": False if regime_label == "winter_proxy" else True,
            "allowed_use_restriction": (
                "runtime_debug_common_support_only_unless_justified"
                if regime_label == "winter_proxy"
                else ""
            ),
        }
    return None


def _candidate_subset(
    eligible: pd.DataFrame,
    *,
    season_label: str | None = None,
) -> pd.DataFrame:
    subset = eligible.copy()
    if season_label is not None:
        subset = subset.loc[subset["season_label"].astype(str) == str(season_label)].copy()
    return subset


def _select_regime_week(
    *,
    eligible: pd.DataFrame,
    selected_ids: set[str],
    period_type: str,
    regime_label: str,
    dedicated_candidates: pd.DataFrame,
    dedicated_reason: str,
    dedicated_rule: str,
    sort_columns: list[str],
    ascending: list[bool],
    target_season: str = "",
    fallback_candidates: pd.DataFrame | None = None,
    fallback_reason: str = "",
    fallback_rule: str = "",
    fallback_regime_label: str | None = None,
) -> dict[str, Any] | None:
    week_label = f"{period_type}_{regime_label}_week"
    chosen = _pick_week(
        dedicated_candidates,
        selected_ids,
        week_label=week_label,
        regime_label=regime_label,
        selection_reason=dedicated_reason,
        selection_rule=dedicated_rule,
        selection_status="selected_dedicated",
        dedicated_regime_candidate=True,
        target_season=target_season,
        fallback_reason="",
        sort_columns=sort_columns,
        ascending=ascending,
    )
    if chosen is not None:
        return chosen
    if fallback_candidates is None or fallback_candidates.empty:
        return None
    effective_fallback_regime = str(fallback_regime_label or regime_label)
    return _pick_week(
        fallback_candidates,
        selected_ids,
        week_label=f"{period_type}_{effective_fallback_regime}_week",
        regime_label=effective_fallback_regime,
        selection_reason=fallback_reason,
        selection_rule=fallback_rule,
        selection_status="selected_backup",
        dedicated_regime_candidate=False,
        target_season=target_season,
        fallback_reason=fallback_reason,
        sort_columns=sort_columns,
        ascending=ascending,
    )


def _build_selected_week_checks(
    selected_weeks: pd.DataFrame,
    candidate_weeks: pd.DataFrame,
    day_support: pd.DataFrame,
    artifact_frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    checks: list[dict[str, Any]] = []
    lookup = candidate_weeks.set_index("candidate_week_id")
    for row in selected_weeks.to_dict(orient="records"):
        week_id = str(row["week_id"])
        candidate = lookup.loc[week_id]
        start_date = str(row["delivery_start_date"])
        end_date = str(row["delivery_end_date"])
        week_days = day_support.loc[
            (day_support["delivery_date_str"] >= start_date) & (day_support["delivery_date_str"] <= end_date)
        ].copy()

        def add(check_name: str, passed: bool, detail: str) -> None:
            checks.append(
                {
                    "week_id": week_id,
                    "week_label": str(row["week_label"]),
                    "check_name": check_name,
                    "status": "pass" if passed else "fail",
                    "detail": detail,
                }
            )

        add("week_has_seven_delivery_days", int(candidate["number_of_delivery_days"]) == 7, f"number_of_delivery_days={int(candidate['number_of_delivery_days'])}")
        add(
            "week_inside_declared_period_only",
            week_days["period_type"].nunique() == 1 and str(week_days["period_type"].iloc[0]) == str(row["period_type"]),
            f"period_types={sorted(week_days['period_type'].astype(str).unique().tolist())}",
        )
        add(
            "all_days_common_complete_support",
            bool(week_days["common_complete_support"].all()),
            f"common_complete_support_days={int(week_days['common_complete_support'].sum())}/7",
        )
        add(
            "all_days_complete_actual_prices",
            bool(week_days["complete_actual_prices"].all()),
            f"complete_actual_price_days={int(week_days['complete_actual_prices'].sum())}/7",
        )
        add(
            "calendar_week_not_dst",
            not bool(candidate["dst_flag"]),
            f"dst_flag={bool(candidate['dst_flag'])}",
        )
        for artifact_key, frame in artifact_frames.items():
            short_name = ARTIFACT_SHORT_NAMES[artifact_key]
            week_frame = frame.loc[
                (frame["delivery_day"].astype(str) >= start_date) & (frame["delivery_day"].astype(str) <= end_date)
            ].copy()
            unique_prob = (
                week_frame[["forecast_origin_utc", "scenario_id", "scenario_probability"]]
                .drop_duplicates(subset=["forecast_origin_utc", "scenario_id"])
                .groupby("forecast_origin_utc", as_index=False)
                .agg(
                    probability_sum=("scenario_probability", "sum"),
                    scenario_count=("scenario_id", "nunique"),
                )
            )
            prob_pass = bool(unique_prob["probability_sum"].between(0.999999, 1.000001).all())
            scenario_count_pass = bool((unique_prob["scenario_count"].astype(int) == EXPECTED_SCENARIO_COUNT).all())
            add(
                f"{short_name}_probabilities_sum_to_one_per_origin",
                prob_pass,
                f"origin_rows={int(unique_prob.shape[0])}; probability_sum_min={float(unique_prob['probability_sum'].min()):.6f}; probability_sum_max={float(unique_prob['probability_sum'].max()):.6f}",
            )
            add(
                f"{short_name}_scenario_count_per_origin_is_75",
                scenario_count_pass,
                f"origin_rows={int(unique_prob.shape[0])}; scenario_count_min={int(unique_prob['scenario_count'].min())}; scenario_count_max={int(unique_prob['scenario_count'].max())}",
            )

    overall_test_periods = selected_weeks.loc[selected_weeks["period_type"] == "test", "methodological_use"].astype(str)
    overall_validation_periods = selected_weeks.loc[selected_weeks["period_type"] == "validation", "methodological_use"].astype(str)
    checks.append(
        {
            "week_id": "ALL",
            "week_label": "ALL",
            "check_name": "test_weeks_reserved_for_diagnostic_reporting",
            "status": "pass" if overall_test_periods.eq("diagnostic_reporting").all() else "fail",
            "detail": f"test_methodological_use={sorted(overall_test_periods.unique().tolist())}",
        }
    )
    checks.append(
        {
            "week_id": "ALL",
            "week_label": "ALL",
            "check_name": "validation_weeks_reserved_for_cvar_selection",
            "status": "pass" if overall_validation_periods.eq("cvar_selection").all() else "fail",
            "detail": f"validation_methodological_use={sorted(overall_validation_periods.unique().tolist())}",
        }
    )
    for period_type in ["validation", "test"]:
        period_rows = selected_weeks.loc[selected_weeks["period_type"].astype(str) == period_type].copy()
        observed = sorted(period_rows["regime_label"].astype(str).tolist())
        checks.append(
            {
                "week_id": "ALL",
                "week_label": "ALL",
                "check_name": f"{period_type}_selected_regimes_present",
                "status": "pass"
                if observed
                == sorted(
                    VALIDATION_SELECTED_REGIME_LABELS
                    if period_type == "validation"
                    else TEST_SELECTED_REGIME_LABELS
                )
                else "fail",
                "detail": f"observed_regime_labels={observed}",
            }
        )
    return pd.DataFrame(checks)


def _write_common_support_markdown(
    validation_results: pd.DataFrame,
    common_support_days: pd.DataFrame,
    candidate_weeks: pd.DataFrame,
    metadata: dict[str, Any],
) -> str:
    lines = [
        "# Three-Model Hourly Common Support Audit",
        "",
        "This file documents the Phase B common-support audit for the three hourly D-only hydrogen bidding artifacts.",
        "",
        "Important scope limits:",
        "",
        "- no stochastic bidding MILPs were run;",
        "- no CVaR runs were run;",
        "- no optimisation model code was changed;",
        "- this is an audit and registry phase only.",
        "",
        "## Artifact validation",
        "",
        _markdown_table(validation_results),
        "",
        "## Common-support summary",
        "",
        f"- validation common-support earliest day: `{metadata['validation_support_start']}`",
        f"- validation common-support latest day: `{metadata['validation_support_end']}`",
        f"- validation common-support day count: `{metadata['validation_support_day_count']}`",
        f"- test common-support earliest day: `{metadata['test_support_start']}`",
        f"- test common-support latest day: `{metadata['test_support_end']}`",
        f"- test common-support day count: `{metadata['test_support_day_count']}`",
        f"- eligible complete validation calendar weeks: `{metadata['eligible_validation_weeks']}`",
        f"- eligible complete test calendar weeks: `{metadata['eligible_test_weeks']}`",
        "",
        "Support is sparse, not continuous. The exact support is defined by `common_complete_support = true` in the CSV, not by the min and max dates alone.",
        "",
        "## Contiguous support segments",
        "",
        "Validation segments:",
    ]
    for segment in metadata["validation_segments"]:
        lines.append(f"- `{segment['start']}` to `{segment['end']}` ({segment['n_days']} days)")
    lines.extend(["", "Test segments:"])
    for segment in metadata["test_segments"]:
        lines.append(f"- `{segment['start']}` to `{segment['end']}` ({segment['n_days']} days)")
    lines.extend(
        [
            "",
            "## Candidate-week generation",
            "",
            "- candidate weeks are Monday-Sunday calendar weeks;",
            "- weeks must contain 7 delivery days inside one split only;",
            "- all 7 days must be complete for all three artifacts and for observed hourly actual prices;",
            "- DST weeks are excluded if any day in the week is not a 24-hour local delivery day;",
            "- `high_price_hours` uses the hydrogen test-case reference threshold `158 EUR/MWh`.",
            "",
            "## Candidate-week counts by status",
            "",
            _markdown_table(candidate_weeks.groupby(["period_type", "exclusion_reason"], dropna=False).size().reset_index(name="n_weeks")),
        ]
    )
    return "\n".join(lines)


def _write_selection_report(
    selected_weeks: pd.DataFrame,
    candidate_weeks: pd.DataFrame,
    metadata: dict[str, Any],
) -> str:
    test_selected = selected_weeks.loc[selected_weeks["period_type"] == "test"].copy()
    validation_selected = selected_weeks.loc[selected_weeks["period_type"] == "validation"].copy()
    missing_test_labels = [
        regime_label
        for regime_label in TEST_SELECTED_REGIME_LABELS
        if regime_label not in set(test_selected["regime_label"].astype(str))
    ]
    missing_validation_labels = [
        regime_label
        for regime_label in VALIDATION_SELECTED_REGIME_LABELS
        if regime_label not in set(validation_selected["regime_label"].astype(str))
    ]
    backup_rows = selected_weeks.loc[selected_weeks["selection_status"].astype(str) != "selected_dedicated"].copy()
    lines = [
        "# Selected Week Selection Report",
        "",
        "## Why common support is required",
        "",
        "Later three-model hydrogen bidding runs must compare the same delivery weeks for LEAR Strict, LEAR FS3, and XGBoost FS3. If the models are run on different days, any realised-profit or operational difference would mix model quality with market-regime selection bias.",
        "",
        "## Why full three-model hourly test-year comparison is still blocked",
        "",
        "A full 2024-10-01 to 2025-09-30 three-model hourly comparison is still blocked because the recovered LEAR Strict thesis-grade artifact only covers a partial, irregular subset of that period. The correct label for this phase is therefore:",
        "",
        "`three-model hourly selected-week comparison on common partial test support`",
        "",
        "## Exact common support",
        "",
        f"- validation earliest common complete day: `{metadata['validation_support_start']}`",
        f"- validation latest common complete day: `{metadata['validation_support_end']}`",
        f"- validation common complete day count: `{metadata['validation_support_day_count']}`",
        f"- test earliest common complete day: `{metadata['test_support_start']}`",
        f"- test latest common complete day: `{metadata['test_support_end']}`",
        f"- test common complete day count: `{metadata['test_support_day_count']}`",
        f"- eligible complete validation calendar weeks: `{metadata['eligible_validation_weeks']}`",
        f"- eligible complete test calendar weeks: `{metadata['eligible_test_weeks']}`",
        "",
        "These support ranges are sparse. The selected weeks come only from days where `common_complete_support = true` for all three artifacts and observed hourly actual prices.",
        "",
        "## Candidate-week generation",
        "",
        "- candidate weeks are Monday-Sunday calendar weeks to match the existing selected-week workflow and to avoid arbitrary sliding-window tuning;",
        "- each candidate week must contain exactly 7 delivery days inside one split only;",
        "- all 7 days must be complete for LEAR Strict, LEAR FS3, XGBoost FS3, and hourly actual prices;",
        "- DST weeks are excluded if any day in the week is not a 24-hour local day;",
        "- `high_price_hours` is counted with the documented threshold `158 EUR/MWh`, taken from the hydrogen test-case reference price;",
        "- diagnostic scores are relative ranks within each split and are used only to label regimes, not to tune the optimiser;",
        "- `typical_summer` and `typical_winter` mean closest to the seasonal median behaviour, not lowest volatility;",
        "- if a split has no eligible week for a required target season, the fallback is the remaining week with the highest split-wide typicality score, and that backup is labelled explicitly;",
        "- the current validation split has no exact-common-support winter week, so its backup is labelled `winter_proxy` and is not valid for seasonal winter claims.",
        "",
        "Score definitions:",
        "",
        "- `volatility_score`: average percentile rank of weekly standard deviation, interquartile range, and full spread;",
        "- `low_price_score`: average percentile rank of low weekly mean price, negative-price hours, and low weekly minimum price;",
        "- `high_price_score`: average percentile rank of weekly mean price, peak price, and count of hours above `158 EUR/MWh`;",
        "- `typical_overall_score`: split-wide median-closeness score across mean, volatility, spread, IQR, high-price hours, and negative-price hours;",
        "- `typical_summer_score` / `typical_winter_score`: the same median-closeness score, but computed inside the requested season only.",
        "",
        "## Selected validation weeks",
        "",
        _markdown_table(
            validation_selected[
                [
                    "regime_label",
                    "week_label",
                    "delivery_start_date",
                    "delivery_end_date",
                    "selection_status",
                    "selection_reason",
                    "actual_price_mean",
                    "actual_price_std",
                    "peak_price",
                    "high_price_hours",
                ]
            ]
        ) if not validation_selected.empty else "No validation weeks were selected.",
        "",
        "## Selected test weeks",
        "",
        _markdown_table(
            test_selected[
                [
                    "regime_label",
                    "week_label",
                    "delivery_start_date",
                    "delivery_end_date",
                    "selection_status",
                    "selection_reason",
                    "actual_price_mean",
                    "actual_price_std",
                    "peak_price",
                    "high_price_hours",
                ]
            ]
        ) if not test_selected.empty else "No test weeks were selected.",
        "",
        "## Explicit backups",
        "",
        _markdown_table(
            backup_rows[
                [
                    "period_type",
                    "regime_label",
                    "week_label",
                    "delivery_start_date",
                    "delivery_end_date",
                    "fallback_reason",
                ]
            ]
        ) if not backup_rows.empty else "No backup selections were needed.",
        "",
        "## Regimes not selected",
        "",
        f"- missing test regime labels: {', '.join(missing_test_labels) if missing_test_labels else 'none'}",
        f"- missing validation regime labels: {', '.join(missing_validation_labels) if missing_validation_labels else 'none'}",
        "",
        "## DST handling",
        "",
        "DST weeks were excluded from selection if any delivery day in the calendar week was not a 24-hour local day.",
        "",
        "## Guardrails for later phases",
        "",
        "- selected test weeks are for diagnostic reporting only and must not be used to choose CVaR gamma;",
        "- any later CVaR gamma selection must use validation weeks only;",
        "- all later three-model comparisons must use the same selected weeks for all three models;",
        "- this report does not authorise full-period test-year claims.",
    ]
    return "\n".join(lines)


def _build_selected_weeks_yaml(selected_weeks: pd.DataFrame) -> str:
    lines = ["selected_weeks:"]
    for row in selected_weeks.to_dict(orient="records"):
        lines.extend(
            [
                f"  - label: {row['week_label']}",
                f"    regime_label: {row['regime_label']}",
                f"    start_local_date: \"{row['delivery_start_date']}\"",
                f"    end_local_date: \"{row['delivery_end_date']}\"",
                f"    week_id: {row['week_id']}",
                f"    period_type: {row['period_type']}",
                f"    selection_status: {row['selection_status']}",
                f"    dedicated_regime_candidate: {str(bool(row['dedicated_regime_candidate'])).lower()}",
                f"    selection_rule: {row['selection_rule']}",
                f"    fallback_reason: \"{str(row['fallback_reason']).replace('\"', '\\\"')}\"",
                f"    notes: {row['methodological_use']}",
            ]
        )
    return "\n".join(lines) + "\n"


def _build_split_selected_weeks_yaml(
    selected_weeks: pd.DataFrame,
    *,
    period_type: str,
) -> str:
    regime_labels = VALIDATION_SELECTED_REGIME_LABELS if period_type == "validation" else TEST_SELECTED_REGIME_LABELS
    regime_order = {label: idx for idx, label in enumerate(regime_labels)}
    rows = selected_weeks.loc[selected_weeks["period_type"].astype(str) == str(period_type)].copy()
    rows["regime_order"] = rows["regime_label"].map(regime_order)
    rows = rows.sort_values(["regime_order", "delivery_start_date"]).drop(columns=["regime_order"]).reset_index(drop=True)
    status = "active"
    methodological_use = "cvar_selection" if period_type == "validation" else "diagnostic_reporting"
    allowed_use = (
        [
            "validation-only model, scenario, and CVaR policy selection",
            "validation diagnostics and support-controlled comparison work",
        ]
        if period_type == "validation"
        else [
            "out-of-sample selected-week evaluation and thesis reporting",
            "benchmark comparison and diagnostic reporting after policy freezing",
        ]
    )
    forbidden_use = (
        [
            "final out-of-sample test claims",
            "presenting validation results as test evidence",
        ]
        if period_type == "validation"
        else [
            "parameter tuning",
            "CVaR gamma selection",
            "scenario or model selection based on test outcomes",
        ]
    )
    lines = [
        f"status: {status}",
        f"split: {period_type}",
        "allowed_use:",
    ]
    for item in allowed_use:
        lines.append(f"  - {item}")
    lines.append("forbidden_use:")
    for item in forbidden_use:
        lines.append(f"  - {item}")
    selection_rule_text = (
        "Monday-Sunday calendar weeks selected from exact three-model common support with complete observed hourly actual prices; "
        "high_volatility uses the realised volatility score; "
        "high_price uses the realised high-price score; "
        "typical_summer and typical_winter use seasonal median-closeness."
    )
    if period_type == "validation":
        selection_rule_text += (
            " If the validation split has no eligible exact-common-support winter week, the backup is written as "
            "winter_proxy rather than being presented as a true validation typical_winter week."
        )
    lines.extend(
        [
            "selection_policy_version: selected_week_policy_v2_regime_split_20260528",
            "created_at: \"2026-05-28\"",
            f"selection_rule: {selection_rule_text}",
            "no_optimisation_results_used: true",
            "intended_regime_labels:",
        ]
    )
    for regime_label in INTENDED_REGIME_LABELS:
        lines.append(f"  - {regime_label}")
    if period_type == "validation":
        lines.extend(
            [
                "selected_regime_labels:",
                "  - typical_summer",
                "  - winter_proxy",
                "  - high_volatility",
                "  - high_price",
            ]
        )
    else:
        lines.extend(
            [
                "selected_regime_labels:",
                "  - typical_summer",
                "  - typical_winter",
                "  - high_volatility",
                "  - high_price",
            ]
        )
    lines.extend(
        [
            "provenance:",
            "  source_registry: scripts/Data/03_Hydrogen_Test_Case/docs/selected_week_registry_common_support.csv",
            "  source_yaml: scripts/Data/03_Hydrogen_Test_Case/configs/selected_weeks_common_support.yaml",
            f"  methodological_use_required: {methodological_use}",
            "selected_weeks:",
        ]
    )
    for row in rows.to_dict(orient="records"):
        lines.extend(
            [
                f"  - label: {row['regime_label']}",
                f"    week_label: {row['week_label']}",
                f"    week_id: {row['week_id']}",
                f"    regime_label: {row['regime_label']}",
                f"    start_local_date: \"{row['delivery_start_date']}\"",
                f"    end_local_date: \"{row['delivery_end_date']}\"",
                f"    selection_status: {row['selection_status']}",
                f"    dedicated_regime_candidate: {str(bool(row['dedicated_regime_candidate'])).lower()}",
                f"    selection_rule: {row['selection_rule']}",
                f"    target_season: {row['target_season'] if str(row['target_season']) else 'none'}",
                f"    selection_reason: \"{str(row['selection_reason']).replace('\"', '\\\"')}\"",
                f"    fallback_reason: \"{str(row['fallback_reason']).replace('\"', '\\\"')}\"",
                f"    proxy_for_regime_label: {row['proxy_for_regime_label'] if str(row['proxy_for_regime_label']) else 'none'}",
                f"    seasonal_claims_valid: {str(bool(row['seasonal_claims_valid'])).lower()}",
                f"    allowed_use_restriction: {row['allowed_use_restriction'] if str(row['allowed_use_restriction']) else 'none'}",
                f"    notes: {row['methodological_use']}",
            ]
        )
    return "\n".join(lines) + "\n"


def run_common_support_audit(
    *,
    config: HydrogenConfig | str | Path,
    artifact_keys: list[str] | tuple[str, ...],
) -> CommonSupportAuditResult:
    loaded_config = config if isinstance(config, HydrogenConfig) else load_hydrogen_config(config)
    audit_config = replace(loaded_config, models=replace(loaded_config.models, include=tuple(str(value) for value in artifact_keys)))
    specs = resolve_artifact_specs(audit_config)

    actual_prices = _load_actual_prices(audit_config.repo_root)
    actual_day_summary = _build_actual_day_summary(actual_prices)

    validation_rows: list[dict[str, Any]] = []
    artifact_frames: dict[str, pd.DataFrame] = {}
    artifact_day_summaries: dict[str, pd.DataFrame] = {}
    for spec in specs:
        frame, _ = _read_scenarios(spec, config=audit_config)
        artifact_frames[spec.artifact_key] = frame.copy()
        validation_rows.append(_validate_artifact_frame(spec, frame))
        artifact_day_summaries[spec.artifact_key] = _build_artifact_day_summary(frame, spec.artifact_key)
    validation_results = pd.DataFrame(validation_rows)

    all_dates = pd.date_range(start=VALIDATION_START, end=TEST_END, freq="D")
    day_rows: list[dict[str, Any]] = []
    actual_lookup = actual_day_summary.set_index("delivery_date_str").to_dict(orient="index")
    artifact_lookup = {
        artifact_key: frame.set_index("delivery_date_str").to_dict(orient="index")
        for artifact_key, frame in artifact_day_summaries.items()
    }
    for delivery_date in all_dates:
        delivery_date_str = delivery_date.strftime("%Y-%m-%d")
        actual_row = actual_lookup.get(
            delivery_date_str,
            {
                "expected_hours_local_day": _expected_hours_for_local_day(delivery_date),
                "n_hours_actual": 0,
                "complete_actual_prices": False,
                "actual_missing_reason": "actual_day_missing",
            },
        )
        row: dict[str, Any] = {
            "delivery_date": delivery_date,
            "delivery_date_str": delivery_date_str,
            "period_type": _period_type(delivery_date),
            "expected_hours_local_day": int(actual_row["expected_hours_local_day"]),
            "complete_actual_prices": bool(actual_row["complete_actual_prices"]),
            "n_hours_actual": int(actual_row["n_hours_actual"]),
        }
        missing_reasons: list[str] = []
        if not row["complete_actual_prices"]:
            missing_reasons.append(str(actual_row["actual_missing_reason"]))
        for artifact_key in artifact_keys:
            short_name = ARTIFACT_SHORT_NAMES[str(artifact_key)]
            artifact_row = artifact_lookup[str(artifact_key)].get(
                delivery_date_str,
                {
                    "complete": False,
                    "n_hours": 0,
                    "n_scenarios_per_origin": 0,
                    "missing_reason": f"{short_name}_day_missing",
                },
            )
            row[f"complete_for_{short_name}"] = bool(artifact_row["complete"])
            row[f"n_hours_{short_name}"] = int(artifact_row["n_hours"])
            row[f"n_scenarios_per_origin_{short_name}"] = int(artifact_row["n_scenarios_per_origin"])
            if not row[f"complete_for_{short_name}"]:
                missing_reasons.append(str(artifact_row["missing_reason"]))
        row["common_complete_support"] = bool(
            row["period_type"] in {"validation", "test"}
            and row["complete_actual_prices"]
            and row["complete_for_lear_strict"]
            and row["complete_for_lear_fs3"]
            and row["complete_for_xgboost_fs3"]
        )
        row["missing_reason"] = "" if row["common_complete_support"] else "; ".join(reason for reason in missing_reasons if reason)
        day_rows.append(row)
    common_support_days = pd.DataFrame(day_rows)

    first_candidate_week_start = VALIDATION_START + pd.offsets.Week(weekday=0)
    if pd.Timestamp(first_candidate_week_start) < VALIDATION_START:
        first_candidate_week_start += pd.Timedelta(days=7)
    week_starts = pd.date_range(start=pd.Timestamp(first_candidate_week_start), end=TEST_END, freq="W-MON")
    candidate_rows: list[dict[str, Any]] = []
    for week_start in week_starts:
        week_end = week_start + pd.Timedelta(days=6)
        week_days = common_support_days.loc[
            (common_support_days["delivery_date"] >= week_start) & (common_support_days["delivery_date"] <= week_end)
        ].copy()
        period_types = set(week_days["period_type"].astype(str).tolist())
        period_type = _candidate_period_label(period_types)
        actual_week = actual_prices.loc[
            (actual_prices["delivery_date"] >= week_start) & (actual_prices["delivery_date"] <= week_end)
        ].copy()
        expected_days = pd.date_range(start=week_start, end=week_end, freq="D")
        complete_for_all_models = bool(
            week_days.shape[0] == 7
            and week_days["complete_for_lear_strict"].astype(bool).all()
            and week_days["complete_for_lear_fs3"].astype(bool).all()
            and week_days["complete_for_xgboost_fs3"].astype(bool).all()
        )
        complete_actual_prices = bool(week_days.shape[0] == 7 and week_days["complete_actual_prices"].astype(bool).all())
        dst_flag = bool(week_days.shape[0] == 7 and (week_days["expected_hours_local_day"].astype(int) != 24).any())
        exclusion_reasons: list[str] = []
        if week_days.shape[0] != 7:
            exclusion_reasons.append("week_not_fully_inside_audited_split_range")
        if period_type == "outside_split":
            exclusion_reasons.append("mixes_validation_and_test_days")
        if not complete_for_all_models:
            exclusion_reasons.append("not_complete_for_all_models")
        if not complete_actual_prices:
            exclusion_reasons.append("actual_prices_incomplete")
        if dst_flag:
            exclusion_reasons.append("contains_dst_transition_day")

        price_values = pd.to_numeric(actual_week["price_eur_per_mwh"], errors="coerce")
        candidate_rows.append(
            {
                "candidate_week_id": f"{period_type}_{week_start.strftime('%Y%m%d')}_{week_end.strftime('%Y%m%d')}",
                "period_type": period_type,
                "delivery_start_date": week_start.strftime("%Y-%m-%d"),
                "delivery_end_date": week_end.strftime("%Y-%m-%d"),
                "number_of_delivery_days": int(len(expected_days)),
                "complete_for_all_models": complete_for_all_models,
                "complete_actual_prices": complete_actual_prices,
                "actual_price_mean": float(price_values.mean()) if not price_values.empty else float("nan"),
                "actual_price_std": float(price_values.std(ddof=1)) if not price_values.empty else float("nan"),
                "actual_price_min": float(price_values.min()) if not price_values.empty else float("nan"),
                "actual_price_max": float(price_values.max()) if not price_values.empty else float("nan"),
                "actual_price_spread": float(price_values.max() - price_values.min()) if not price_values.empty else float("nan"),
                "negative_price_hours": int((price_values < 0.0).sum()) if not price_values.empty else 0,
                "high_price_hours": int((price_values > loaded_config.economics.p_ref_eur_per_mwh).sum()) if not price_values.empty else 0,
                "peak_price": float(price_values.max()) if not price_values.empty else float("nan"),
                "price_iqr": float(price_values.quantile(0.75) - price_values.quantile(0.25)) if not price_values.empty else float("nan"),
                "volatility_score": np.nan,
                "high_price_score": np.nan,
                "low_price_score": np.nan,
                "typical_overall_score": np.nan,
                "typical_summer_score": np.nan,
                "typical_winter_score": np.nan,
                "season_label": _season_label(week_days["delivery_date"]) if week_days.shape[0] == 7 else "outside_split",
                "dst_flag": dst_flag,
                "exclusion_reason": "; ".join(exclusion_reasons),
            }
        )
    candidate_weeks = _score_candidate_weeks(pd.DataFrame(candidate_rows))

    selected_rows: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    eligible_validation = candidate_weeks.loc[
        (candidate_weeks["period_type"] == "validation")
        & candidate_weeks["complete_for_all_models"].astype(bool)
        & candidate_weeks["complete_actual_prices"].astype(bool)
        & ~candidate_weeks["dst_flag"].astype(bool)
    ].copy()
    eligible_test = candidate_weeks.loc[
        (candidate_weeks["period_type"] == "test")
        & candidate_weeks["complete_for_all_models"].astype(bool)
        & candidate_weeks["complete_actual_prices"].astype(bool)
        & ~candidate_weeks["dst_flag"].astype(bool)
    ].copy()

    split_specs = [
        ("validation", eligible_validation),
        ("test", eligible_test),
    ]
    for period_type, eligible in split_specs:
        regime_specs = [
            lambda: _select_regime_week(
                eligible=eligible,
                selected_ids=selected_ids,
                period_type=period_type,
                regime_label="high_volatility",
                dedicated_candidates=eligible,
                dedicated_reason=f"{period_type} week with the highest realised volatility score under exact three-model common support",
                dedicated_rule="volatility_score",
                sort_columns=["volatility_score", "actual_price_std", "actual_price_spread", "delivery_start_date"],
                ascending=[False, False, False, True],
            ),
            lambda: _select_regime_week(
                eligible=eligible,
                selected_ids=selected_ids,
                period_type=period_type,
                regime_label="high_price",
                dedicated_candidates=eligible.loc[eligible["high_price_hours"].astype(int) > 0].copy(),
                dedicated_reason=f"{period_type} week with the strongest realised high-price score under exact three-model common support",
                dedicated_rule="high_price_score",
                sort_columns=["high_price_score", "high_price_hours", "peak_price", "actual_price_mean", "delivery_start_date"],
                ascending=[False, False, False, False, True],
                fallback_candidates=eligible,
                fallback_reason=f"No dedicated {period_type} high-price week exists under exact three-model common support; selected the strongest backup week under the documented high-price score.",
                fallback_rule="high_price_score_fallback",
            ),
            lambda: _select_regime_week(
                eligible=eligible,
                selected_ids=selected_ids,
                period_type=period_type,
                regime_label="typical_summer",
                dedicated_candidates=_candidate_subset(eligible, season_label="summer"),
                dedicated_reason=f"summer {period_type} week closest to seasonal median behaviour under exact three-model common support",
                dedicated_rule="typical_summer_score",
                sort_columns=["typical_summer_score", "typical_overall_score", "delivery_start_date"],
                ascending=[False, False, True],
                target_season="summer",
                fallback_candidates=eligible,
                fallback_reason=f"No complete summer {period_type} week exists under exact three-model common support; selected the closest split-wide typical backup week.",
                fallback_rule="typical_overall_score_fallback",
            ),
            lambda: _select_regime_week(
                eligible=eligible,
                selected_ids=selected_ids,
                period_type=period_type,
                regime_label="typical_winter",
                dedicated_candidates=_candidate_subset(eligible, season_label="winter"),
                dedicated_reason=f"winter {period_type} week closest to seasonal median behaviour under exact three-model common support",
                dedicated_rule="typical_winter_score",
                sort_columns=["typical_winter_score", "typical_overall_score", "delivery_start_date"],
                ascending=[False, False, True],
                target_season="winter",
                fallback_candidates=eligible,
                fallback_reason=(
                    f"No complete winter {period_type} week exists under exact three-model common support; "
                    "selected the closest split-wide typical backup week and labelled it winter_proxy because it is not valid for seasonal winter claims."
                    if period_type == "validation"
                    else f"No complete winter {period_type} week exists under exact three-model common support; selected the closest split-wide typical backup week."
                ),
                fallback_rule="typical_overall_score_fallback",
                fallback_regime_label="winter_proxy" if period_type == "validation" else None,
            ),
        ]
        for pick_regime in regime_specs:
            chosen = pick_regime()
            if chosen is None:
                continue
            selected_rows.append(chosen)
            selected_ids.add(str(chosen["week_id"]))
    selected_weeks = pd.DataFrame(selected_rows)
    if not selected_weeks.empty:
        selected_weeks = selected_weeks.sort_values(["period_type", "regime_label", "delivery_start_date"]).reset_index(drop=True)

    selected_week_checks = _build_selected_week_checks(selected_weeks, candidate_weeks, common_support_days, artifact_frames)
    validation_segments = _support_segments(common_support_days, "validation")
    test_segments = _support_segments(common_support_days, "test")
    validation_common = common_support_days.loc[
        (common_support_days["period_type"] == "validation") & common_support_days["common_complete_support"].astype(bool)
    ].copy()
    test_common = common_support_days.loc[
        (common_support_days["period_type"] == "test") & common_support_days["common_complete_support"].astype(bool)
    ].copy()
    metadata = {
        "validation_support_start": validation_common["delivery_date_str"].min() if not validation_common.empty else "",
        "validation_support_end": validation_common["delivery_date_str"].max() if not validation_common.empty else "",
        "validation_support_day_count": int(validation_common.shape[0]),
        "test_support_start": test_common["delivery_date_str"].min() if not test_common.empty else "",
        "test_support_end": test_common["delivery_date_str"].max() if not test_common.empty else "",
        "test_support_day_count": int(test_common.shape[0]),
        "eligible_validation_weeks": int(
            candidate_weeks.loc[
                (candidate_weeks["period_type"] == "validation")
                & candidate_weeks["complete_for_all_models"].astype(bool)
                & candidate_weeks["complete_actual_prices"].astype(bool)
                & ~candidate_weeks["dst_flag"].astype(bool)
            ].shape[0]
        ),
        "eligible_test_weeks": int(
            candidate_weeks.loc[
                (candidate_weeks["period_type"] == "test")
                & candidate_weeks["complete_for_all_models"].astype(bool)
                & candidate_weeks["complete_actual_prices"].astype(bool)
                & ~candidate_weeks["dst_flag"].astype(bool)
            ].shape[0]
        ),
        "validation_segments": validation_segments,
        "test_segments": test_segments,
        "intended_regime_labels": list(INTENDED_REGIME_LABELS),
        "validation_selected_regime_labels": list(VALIDATION_SELECTED_REGIME_LABELS),
        "test_selected_regime_labels": list(TEST_SELECTED_REGIME_LABELS),
        "backup_selection_count": int(
            selected_weeks.loc[selected_weeks["selection_status"].astype(str) != "selected_dedicated"].shape[0]
        ) if not selected_weeks.empty else 0,
    }
    return CommonSupportAuditResult(
        validation_results=validation_results,
        common_support_days=common_support_days,
        candidate_weeks=candidate_weeks,
        selected_weeks=selected_weeks,
        selected_week_checks=selected_week_checks,
        metadata=metadata,
    )


def write_common_support_outputs(
    result: CommonSupportAuditResult,
    *,
    docs_dir: Path,
    configs_dir: Path | None = None,
) -> dict[str, Path]:
    docs_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "common_support_csv": docs_dir / "common_support_three_model_hourly.csv",
        "common_support_md": docs_dir / "common_support_three_model_hourly.md",
        "candidate_weeks_csv": docs_dir / "common_support_three_model_hourly_candidate_weeks.csv",
        "selected_registry_csv": docs_dir / "selected_week_registry_common_support.csv",
        "selected_checks_csv": docs_dir / "selected_week_support_checks.csv",
        "selection_report_md": docs_dir / "selected_week_selection_report.md",
    }
    result.common_support_days.to_csv(output_paths["common_support_csv"], index=False)
    result.candidate_weeks.to_csv(output_paths["candidate_weeks_csv"], index=False)
    result.selected_weeks.to_csv(output_paths["selected_registry_csv"], index=False)
    result.selected_week_checks.to_csv(output_paths["selected_checks_csv"], index=False)
    output_paths["common_support_md"].write_text(
        _write_common_support_markdown(
            result.validation_results,
            result.common_support_days,
            result.candidate_weeks,
            result.metadata,
        ),
        encoding="utf-8",
    )
    output_paths["selection_report_md"].write_text(
        _write_selection_report(
            result.selected_weeks,
            result.candidate_weeks,
            result.metadata,
        ),
        encoding="utf-8",
    )
    if configs_dir is not None:
        configs_dir.mkdir(parents=True, exist_ok=True)
        yaml_path = configs_dir / "selected_weeks_common_support.yaml"
        yaml_path.write_text(_build_selected_weeks_yaml(result.selected_weeks), encoding="utf-8")
        output_paths["selected_weeks_yaml"] = yaml_path
        validation_yaml_path = configs_dir / "selected_validation_weeks.yaml"
        validation_yaml_path.write_text(
            _build_split_selected_weeks_yaml(result.selected_weeks, period_type="validation"),
            encoding="utf-8",
        )
        output_paths["selected_validation_weeks_yaml"] = validation_yaml_path
        test_yaml_path = configs_dir / "selected_test_weeks.yaml"
        test_yaml_path.write_text(
            _build_split_selected_weeks_yaml(result.selected_weeks, period_type="test"),
            encoding="utf-8",
        )
        output_paths["selected_test_weeks_yaml"] = test_yaml_path
    return output_paths
