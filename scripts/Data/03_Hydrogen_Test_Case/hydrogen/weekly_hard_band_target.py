from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import pandas as pd

from .production_target import (
    TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
    validate_target_accounting_policy,
)


TARGET_MODE_WEEKLY_HARD_BAND = "weekly_hard_band_target"
PRODUCTION_VARIANT_WEEKLY_HARD_BAND_ON = "weekly_hard_band_on"
PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF = "weekly_hard_band_off"


@dataclass(frozen=True)
class WeeklyHardBandSettings:
    daily_target_kg: float
    daily_min_fraction: float
    daily_max_fraction: float
    target_accounting_policy: str = TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET

    @property
    def weekly_target_kg(self) -> float:
        return 7.0 * float(self.daily_target_kg)

    @property
    def daily_min_kg(self) -> float:
        return float(self.daily_target_kg) * float(self.daily_min_fraction)

    @property
    def daily_max_kg(self) -> float:
        return float(self.daily_target_kg) * float(self.daily_max_fraction)


@dataclass(frozen=True)
class WeeklyTargetDayBounds:
    target_accounting_policy: str
    accounting_week_id: str
    included_day_index_in_week: int
    included_days_in_week: int
    remaining_included_days_after_today: int
    is_boundary_week: bool
    week_start_date: str
    week_end_date: str
    excluded_days_in_calendar_week: tuple[str, ...]
    exclusion_reason: tuple[str, ...]
    weekly_target_kg: float
    cumulative_before_kg: float
    remaining_target_before_today_kg: float
    days_remaining_in_week: int
    daily_lower_bound_kg: float
    daily_upper_bound_kg: float
    tracker_feasible: bool


def build_weekly_hard_band_settings(
    *,
    daily_target_kg: float,
    daily_min_fraction: float,
    daily_max_fraction: float,
    target_accounting_policy: str = TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
) -> WeeklyHardBandSettings:
    if float(daily_target_kg) <= 0.0:
        raise ValueError("daily_target_kg must be positive.")
    if not (0.0 <= float(daily_min_fraction) <= 1.0):
        raise ValueError("daily_min_fraction must lie inside [0, 1].")
    if float(daily_max_fraction) < 1.0:
        raise ValueError("daily_max_fraction must be at least 1.0 for the weekly band formulation.")
    if float(daily_min_fraction) > float(daily_max_fraction):
        raise ValueError("daily_min_fraction must not exceed daily_max_fraction.")
    return WeeklyHardBandSettings(
        daily_target_kg=float(daily_target_kg),
        daily_min_fraction=float(daily_min_fraction),
        daily_max_fraction=float(daily_max_fraction),
        target_accounting_policy=validate_target_accounting_policy(target_accounting_policy),
    )


def _normalize_delivery_days(included_delivery_days: Sequence[str | pd.Timestamp]) -> list[str]:
    if not included_delivery_days:
        return []
    normalized = sorted(
        {
            pd.Timestamp(value).strftime("%Y-%m-%d")
            for value in included_delivery_days
        }
    )
    return normalized


def _normalize_exclusion_reason_map(
    excluded_day_reasons: Mapping[str, Any] | None,
) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    if not excluded_day_reasons:
        return normalized
    for day, reason in excluded_day_reasons.items():
        key = pd.Timestamp(day).strftime("%Y-%m-%d")
        if isinstance(reason, (list, tuple, set)):
            values = [str(item).strip() for item in reason if str(item).strip()]
        else:
            text = str(reason).strip()
            values = [text] if text else []
        if values:
            normalized[key] = values
    return normalized


def build_included_day_prorated_weekly_accounting(
    *,
    included_delivery_days: Sequence[str | pd.Timestamp],
    daily_target_kg: float,
    excluded_day_reasons: Mapping[str, Any] | None = None,
    target_accounting_policy: str = TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
) -> pd.DataFrame:
    normalized_days = _normalize_delivery_days(included_delivery_days)
    policy = validate_target_accounting_policy(target_accounting_policy)
    if not normalized_days:
        return pd.DataFrame(
            columns=[
                "delivery_day",
                "accounting_week_id",
                "included_day_index_in_week",
                "included_days_in_week",
                "remaining_included_days_after_today",
                "days_remaining_in_week",
                "is_boundary_week",
                "week_start_date",
                "week_end_date",
                "weekly_target_kg",
                "cumulative_target_after_day_kg",
                "excluded_days_in_calendar_week",
                "exclusion_reason",
                "target_accounting_policy",
            ]
        )

    reason_map = _normalize_exclusion_reason_map(excluded_day_reasons)
    frame = pd.DataFrame({"delivery_day": pd.to_datetime(pd.Series(normalized_days), errors="raise")})
    frame["week_start"] = frame["delivery_day"] - pd.to_timedelta(frame["delivery_day"].dt.weekday, unit="D")
    rows: list[dict[str, Any]] = []
    for week_start, group in frame.groupby("week_start", sort=True):
        ordered = group.sort_values("delivery_day").reset_index(drop=True)
        week_start_ts = pd.Timestamp(week_start)
        week_end_ts = week_start_ts + pd.Timedelta(days=6)
        included_days = ordered["delivery_day"].dt.strftime("%Y-%m-%d").tolist()
        included_count = int(len(included_days))
        excluded_days = [
            day
            for day in pd.date_range(week_start_ts, week_end_ts, freq="D").strftime("%Y-%m-%d").tolist()
            if day not in included_days and day in reason_map
        ]
        exclusion_reason = [f"{day}:{'|'.join(reason_map[day])}" for day in excluded_days]
        weekly_target = float(included_count * float(daily_target_kg))
        for idx, delivery_day in enumerate(included_days, start=1):
            remaining_after = included_count - idx
            rows.append(
                {
                    "delivery_day": delivery_day,
                    "accounting_week_id": f"week_{week_start_ts.strftime('%Y%m%d')}_{week_end_ts.strftime('%Y%m%d')}",
                    "included_day_index_in_week": int(idx),
                    "included_days_in_week": int(included_count),
                    "remaining_included_days_after_today": int(remaining_after),
                    "days_remaining_in_week": int(remaining_after + 1),
                    "is_boundary_week": bool(included_count != 7),
                    "week_start_date": week_start_ts.strftime("%Y-%m-%d"),
                    "week_end_date": week_end_ts.strftime("%Y-%m-%d"),
                    "weekly_target_kg": float(weekly_target),
                    "cumulative_target_after_day_kg": float(idx * float(daily_target_kg)),
                    "excluded_days_in_calendar_week": tuple(excluded_days),
                    "exclusion_reason": tuple(exclusion_reason),
                    "target_accounting_policy": str(policy),
                }
            )
    return pd.DataFrame(rows).sort_values("delivery_day").reset_index(drop=True)


def build_production_accounting_lookup(accounting_frame: pd.DataFrame) -> dict[str, pd.Series]:
    if accounting_frame.empty:
        return {}
    return {
        str(row.delivery_day): pd.Series(row._asdict())
        for row in accounting_frame.itertuples()
    }


def target_accounting_fields_from_bounds(bounds: WeeklyTargetDayBounds) -> dict[str, Any]:
    return {
        "target_accounting_policy": str(bounds.target_accounting_policy),
        "accounting_week_id": str(bounds.accounting_week_id),
        "included_day_index_in_week": int(bounds.included_day_index_in_week),
        "included_days_in_week": int(bounds.included_days_in_week),
        "remaining_included_days_after_today": int(bounds.remaining_included_days_after_today),
        "days_remaining_in_week": int(bounds.days_remaining_in_week),
        "is_boundary_week": bool(bounds.is_boundary_week),
        "week_start_date": str(bounds.week_start_date),
        "week_end_date": str(bounds.week_end_date),
        "excluded_days_in_calendar_week": "|".join(bounds.excluded_days_in_calendar_week),
        "exclusion_reason": "|".join(bounds.exclusion_reason),
    }


def daily_frame_matches_accounting(
    *,
    daily_frame: pd.DataFrame,
    accounting_frame: pd.DataFrame,
    target_accounting_policy: str,
) -> bool:
    if daily_frame.empty or accounting_frame.empty:
        return False
    required_daily_columns = {"delivery_day", "weekly_target_kg"}
    if not required_daily_columns.issubset(set(daily_frame.columns)):
        return False
    expected = accounting_frame.copy()
    observed = daily_frame.copy()
    expected["delivery_day"] = expected["delivery_day"].astype(str)
    observed["delivery_day"] = observed["delivery_day"].astype(str)
    if sorted(expected["delivery_day"].tolist()) != sorted(observed["delivery_day"].tolist()):
        return False
    if "target_accounting_policy" in observed.columns and not observed["target_accounting_policy"].astype(str).eq(str(target_accounting_policy)).all():
        return False
    merged = observed.merge(
        expected[
            [
                "delivery_day",
                "accounting_week_id",
                "included_day_index_in_week",
                "included_days_in_week",
                "weekly_target_kg",
            ]
        ],
        on="delivery_day",
        how="left",
        suffixes=("_observed", "_expected"),
    )
    if merged["weekly_target_kg_expected"].isna().any():
        return False
    if "accounting_week_id" in observed.columns and not merged["accounting_week_id_observed"].astype(str).eq(merged["accounting_week_id_expected"].astype(str)).all():
        return False
    if "included_day_index_in_week" in observed.columns and not pd.to_numeric(merged["included_day_index_in_week_observed"], errors="coerce").eq(pd.to_numeric(merged["included_day_index_in_week_expected"], errors="coerce")).all():
        return False
    if "included_days_in_week" in observed.columns and not pd.to_numeric(merged["included_days_in_week_observed"], errors="coerce").eq(pd.to_numeric(merged["included_days_in_week_expected"], errors="coerce")).all():
        return False
    return bool(
        pd.to_numeric(merged["weekly_target_kg_observed"], errors="coerce").round(9).eq(
            pd.to_numeric(merged["weekly_target_kg_expected"], errors="coerce").round(9)
        ).all()
    )


def build_weekly_accounting_exclusion_reason_map(
    *,
    included_delivery_days: Sequence[str | pd.Timestamp],
    explicit_exclusions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, list[str]]:
    included = set(_normalize_delivery_days(included_delivery_days))
    reasons: dict[str, list[str]] = {}
    for item in explicit_exclusions or []:
        day = pd.Timestamp(item["delivery_day"]).strftime("%Y-%m-%d")
        if day in included:
            continue
        parts = [str(item.get("reason", "")).strip()]
        if "local_hour_count" in item:
            parts.append(f"local_hour_count={int(item['local_hour_count'])}")
        reasons[day] = [part for part in parts if part]
    return reasons


def coerce_accounting_day(
    accounting_day: WeeklyTargetDayBounds | Mapping[str, Any] | pd.Series | None,
) -> Mapping[str, Any] | None:
    if accounting_day is None:
        return None
    if isinstance(accounting_day, WeeklyTargetDayBounds):
        return {
            "target_accounting_policy": accounting_day.target_accounting_policy,
            "accounting_week_id": accounting_day.accounting_week_id,
            "included_day_index_in_week": accounting_day.included_day_index_in_week,
            "included_days_in_week": accounting_day.included_days_in_week,
            "remaining_included_days_after_today": accounting_day.remaining_included_days_after_today,
            "days_remaining_in_week": accounting_day.days_remaining_in_week,
            "is_boundary_week": accounting_day.is_boundary_week,
            "week_start_date": accounting_day.week_start_date,
            "week_end_date": accounting_day.week_end_date,
            "weekly_target_kg": accounting_day.weekly_target_kg,
            "excluded_days_in_calendar_week": accounting_day.excluded_days_in_calendar_week,
            "exclusion_reason": accounting_day.exclusion_reason,
        }
    if isinstance(accounting_day, pd.Series):
        return accounting_day.to_dict()
    return accounting_day


def _resolve_accounting_context(
    *,
    settings: WeeklyHardBandSettings,
    accounting_day: WeeklyTargetDayBounds | Mapping[str, Any] | pd.Series | None,
    days_remaining_in_week: int | None,
) -> dict[str, Any]:
    coerced = coerce_accounting_day(accounting_day)
    if coerced is None:
        if days_remaining_in_week is None or int(days_remaining_in_week) <= 0:
            raise ValueError("days_remaining_in_week must be positive when accounting_day is not provided.")
        included_days = int(round(float(settings.weekly_target_kg) / float(settings.daily_target_kg)))
        days_remaining = int(days_remaining_in_week)
        included_index = included_days - days_remaining + 1
        return {
            "target_accounting_policy": str(settings.target_accounting_policy),
            "accounting_week_id": "",
            "included_day_index_in_week": int(included_index),
            "included_days_in_week": int(included_days),
            "remaining_included_days_after_today": int(days_remaining - 1),
            "days_remaining_in_week": int(days_remaining),
            "is_boundary_week": bool(included_days != 7),
            "week_start_date": "",
            "week_end_date": "",
            "weekly_target_kg": float(settings.weekly_target_kg),
            "excluded_days_in_calendar_week": tuple(),
            "exclusion_reason": tuple(),
        }
    days_remaining = int(coerced.get("days_remaining_in_week", int(coerced["remaining_included_days_after_today"]) + 1))
    return {
        "target_accounting_policy": str(coerced.get("target_accounting_policy", settings.target_accounting_policy)),
        "accounting_week_id": str(coerced.get("accounting_week_id", "")),
        "included_day_index_in_week": int(coerced.get("included_day_index_in_week", 0)),
        "included_days_in_week": int(coerced.get("included_days_in_week", days_remaining)),
        "remaining_included_days_after_today": int(coerced.get("remaining_included_days_after_today", days_remaining - 1)),
        "days_remaining_in_week": int(days_remaining),
        "is_boundary_week": bool(coerced.get("is_boundary_week", int(coerced.get("included_days_in_week", 7)) != 7)),
        "week_start_date": str(coerced.get("week_start_date", "")),
        "week_end_date": str(coerced.get("week_end_date", "")),
        "weekly_target_kg": float(coerced["weekly_target_kg"]),
        "excluded_days_in_calendar_week": tuple(str(item) for item in coerced.get("excluded_days_in_calendar_week", tuple())),
        "exclusion_reason": tuple(str(item) for item in coerced.get("exclusion_reason", tuple())),
    }


def compute_weekly_target_day_bounds(
    *,
    settings: WeeklyHardBandSettings,
    cumulative_realised_h2_kg_before_today: float,
    days_remaining_in_week: int | None = None,
    accounting_day: WeeklyTargetDayBounds | Mapping[str, Any] | pd.Series | None = None,
) -> WeeklyTargetDayBounds:
    context = _resolve_accounting_context(
        settings=settings,
        accounting_day=accounting_day,
        days_remaining_in_week=days_remaining_in_week,
    )
    cumulative_before = float(cumulative_realised_h2_kg_before_today)
    remaining_target = float(context["weekly_target_kg"] - cumulative_before)
    remaining_after = int(context["remaining_included_days_after_today"])
    lower_today = max(
        float(settings.daily_min_kg),
        remaining_target - float(settings.daily_max_kg) * remaining_after,
    )
    upper_today = min(
        float(settings.daily_max_kg),
        remaining_target - float(settings.daily_min_kg) * remaining_after,
    )
    return WeeklyTargetDayBounds(
        target_accounting_policy=str(context["target_accounting_policy"]),
        accounting_week_id=str(context["accounting_week_id"]),
        included_day_index_in_week=int(context["included_day_index_in_week"]),
        included_days_in_week=int(context["included_days_in_week"]),
        remaining_included_days_after_today=int(remaining_after),
        days_remaining_in_week=int(context["days_remaining_in_week"]),
        is_boundary_week=bool(context["is_boundary_week"]),
        week_start_date=str(context["week_start_date"]),
        week_end_date=str(context["week_end_date"]),
        excluded_days_in_calendar_week=tuple(context["excluded_days_in_calendar_week"]),
        exclusion_reason=tuple(context["exclusion_reason"]),
        weekly_target_kg=float(context["weekly_target_kg"]),
        cumulative_before_kg=cumulative_before,
        remaining_target_before_today_kg=float(remaining_target),
        daily_lower_bound_kg=float(lower_today),
        daily_upper_bound_kg=float(upper_today),
        tracker_feasible=bool(upper_today + 1e-9 >= lower_today),
    )


def compute_weekly_target_day_bounds_for_variant(
    *,
    settings: WeeklyHardBandSettings,
    production_variant: str,
    cumulative_realised_h2_kg_before_today: float,
    days_remaining_in_week: int | None = None,
    physical_daily_max_kg: float | None = None,
    accounting_day: WeeklyTargetDayBounds | Mapping[str, Any] | pd.Series | None = None,
) -> WeeklyTargetDayBounds:
    variant = str(production_variant).strip()
    if variant == PRODUCTION_VARIANT_WEEKLY_HARD_BAND_ON:
        return compute_weekly_target_day_bounds(
            settings=settings,
            cumulative_realised_h2_kg_before_today=cumulative_realised_h2_kg_before_today,
            days_remaining_in_week=days_remaining_in_week,
            accounting_day=accounting_day,
        )
    if variant != PRODUCTION_VARIANT_WEEKLY_HARD_BAND_OFF:
        raise ValueError(f"Unsupported production_variant: {production_variant!r}")
    if physical_daily_max_kg is None or float(physical_daily_max_kg) <= 0.0:
        raise ValueError("physical_daily_max_kg must be positive for weekly_hard_band_off.")
    context = _resolve_accounting_context(
        settings=settings,
        accounting_day=accounting_day,
        days_remaining_in_week=days_remaining_in_week,
    )
    cumulative_before = float(cumulative_realised_h2_kg_before_today)
    remaining_target = float(context["weekly_target_kg"] - cumulative_before)
    remaining_after = int(context["remaining_included_days_after_today"])
    lower_today = max(0.0, remaining_target - float(physical_daily_max_kg) * remaining_after)
    upper_today = float(physical_daily_max_kg)
    if remaining_after == 0:
        if remaining_target <= 0.0:
            lower_today = 0.0
            upper_today = 0.0
        else:
            lower_today = max(lower_today, remaining_target)
            upper_today = min(upper_today, remaining_target)
    return WeeklyTargetDayBounds(
        target_accounting_policy=str(context["target_accounting_policy"]),
        accounting_week_id=str(context["accounting_week_id"]),
        included_day_index_in_week=int(context["included_day_index_in_week"]),
        included_days_in_week=int(context["included_days_in_week"]),
        remaining_included_days_after_today=int(remaining_after),
        days_remaining_in_week=int(context["days_remaining_in_week"]),
        is_boundary_week=bool(context["is_boundary_week"]),
        week_start_date=str(context["week_start_date"]),
        week_end_date=str(context["week_end_date"]),
        excluded_days_in_calendar_week=tuple(context["excluded_days_in_calendar_week"]),
        exclusion_reason=tuple(context["exclusion_reason"]),
        weekly_target_kg=float(context["weekly_target_kg"]),
        cumulative_before_kg=cumulative_before,
        remaining_target_before_today_kg=float(remaining_target),
        daily_lower_bound_kg=float(lower_today),
        daily_upper_bound_kg=float(upper_today),
        tracker_feasible=bool(upper_today + 1e-9 >= lower_today),
    )
