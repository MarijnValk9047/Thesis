from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pandas as pd

if TYPE_CHECKING:
    from .plant_parameters import HydrogenConfig, ProductionTargetEntry, ProductionTargetsSettings


TARGET_MODE_CURRENT_SOFT = "current_soft_target"
TARGET_MODE_HIGH_PENALTY = "high_shortfall_penalty"
TARGET_MODE_HARD = "hard_daily_target"
TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET = "included_day_prorated_weekly_target"
PRODUCTION_TARGETS_MODE_LEGACY_DAILY_MINIMUM = "legacy_daily_minimum"
PRODUCTION_TARGETS_MODE_ROLLING_DEADLINE_ENVELOPE = "rolling_deadline_envelope"
TERMINAL_INVENTORY_VALUE_MODE_LEGACY = "legacy"
TERMINAL_INVENTORY_VALUE_MODE_DISABLED = "disabled"
RESERVE_FEASIBILITY_PROXY_MODE_NONE = "none"
RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION = "conservative_output_absorption"
RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION_AND_RECOVERY = "conservative_output_absorption_and_recovery"
RESERVE_FEASIBILITY_PROXY_DOWN_SOURCE_ROLLING_PRODUCTION_CREDIT_HEADROOM = "rolling_production_credit_headroom"
RESERVE_FEASIBILITY_PROXY_UP_SOURCE_ROLLING_FUTURE_RECOVERABLE_PRODUCTION_HEADROOM = "rolling_future_recoverable_production_headroom"

TARGET_MODES = (
    TARGET_MODE_CURRENT_SOFT,
    TARGET_MODE_HIGH_PENALTY,
    TARGET_MODE_HARD,
)

TARGET_ACCOUNTING_POLICIES = (
    TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
)

PRODUCTION_TARGETS_MODES = (
    PRODUCTION_TARGETS_MODE_LEGACY_DAILY_MINIMUM,
    PRODUCTION_TARGETS_MODE_ROLLING_DEADLINE_ENVELOPE,
)

TERMINAL_INVENTORY_VALUE_MODES = (
    TERMINAL_INVENTORY_VALUE_MODE_LEGACY,
    TERMINAL_INVENTORY_VALUE_MODE_DISABLED,
)
RESERVE_FEASIBILITY_PROXY_MODES = (
    RESERVE_FEASIBILITY_PROXY_MODE_NONE,
    RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION,
    RESERVE_FEASIBILITY_PROXY_MODE_CONSERVATIVE_OUTPUT_ABSORPTION_AND_RECOVERY,
)
RESERVE_FEASIBILITY_PROXY_DOWN_SOURCES = (
    RESERVE_FEASIBILITY_PROXY_DOWN_SOURCE_ROLLING_PRODUCTION_CREDIT_HEADROOM,
)
RESERVE_FEASIBILITY_PROXY_UP_SOURCES = (
    RESERVE_FEASIBILITY_PROXY_UP_SOURCE_ROLLING_FUTURE_RECOVERABLE_PRODUCTION_HEADROOM,
)

PRODUCTION_TARGETS_TZ = ZoneInfo("Europe/Amsterdam")


@dataclass(frozen=True)
class ProductionTargetPolicy:
    target_mode: str
    baseline_shortfall_penalty_eur_per_kg: float
    applied_shortfall_penalty_eur_per_kg: float
    hard_target: bool
    slack_allowed: bool
    high_shortfall_penalty_rule: str


@dataclass(frozen=True)
class RollingDeadlineConstraint:
    due_date: str
    cutoff_time_index: int
    cumulative_required_kg: float


@dataclass(frozen=True)
class RollingTerminalFeasibilityGuard:
    due_date: str
    cumulative_required_kg: float
    future_max_production_kg: float
    minimum_h_comp_required_by_horizon_end_kg: float
    active: bool


@dataclass(frozen=True)
class RollingProductionTargetPlan:
    mode: str
    due_date_interpretation: str
    initial_inventory_kg: float
    max_inventory_kg: float | None
    terminal_inventory_value_mode: str
    horizon_start_local_date: str
    horizon_end_local_date: str
    production_credit_formula: str
    rolling_constraints: tuple[RollingDeadlineConstraint, ...]
    terminal_guards: tuple[RollingTerminalFeasibilityGuard, ...]
    cumulative_requirements_by_due_date: tuple[tuple[str, float], ...]
    cumulative_required_due_by_time_index_kg: tuple[float, ...]
    past_due_required_kg: float


@dataclass(frozen=True)
class RollingUpRecoveryProxyBound:
    time_index: int
    due_date: str
    cumulative_required_kg: float
    future_max_recoverable_output_kg: float


def validate_production_targets_mode(mode: str) -> str:
    normalized = str(mode).strip()
    if normalized not in PRODUCTION_TARGETS_MODES:
        raise ValueError(f"Unsupported production_targets.mode: {mode!r}")
    return normalized


def validate_terminal_inventory_value_mode(mode: str) -> str:
    normalized = str(mode).strip()
    if normalized not in TERMINAL_INVENTORY_VALUE_MODES:
        raise ValueError(f"Unsupported production_targets.terminal_inventory_value_mode: {mode!r}")
    return normalized


def validate_reserve_feasibility_proxy_mode(mode: str) -> str:
    normalized = str(mode).strip()
    if normalized not in RESERVE_FEASIBILITY_PROXY_MODES:
        raise ValueError(f"Unsupported reserve_feasibility_proxy.mode: {mode!r}")
    return normalized


def validate_reserve_feasibility_proxy_down_source(source: str) -> str:
    normalized = str(source).strip()
    if normalized not in RESERVE_FEASIBILITY_PROXY_DOWN_SOURCES:
        raise ValueError(f"Unsupported reserve_feasibility_proxy.down_output_absorption_source: {source!r}")
    return normalized


def validate_reserve_feasibility_proxy_up_source(source: str) -> str:
    normalized = str(source).strip()
    if normalized not in RESERVE_FEASIBILITY_PROXY_UP_SOURCES:
        raise ValueError(f"Unsupported reserve_feasibility_proxy.up_recovery_source: {source!r}")
    return normalized


def is_rolling_deadline_mode(production_targets: ProductionTargetsSettings | None) -> bool:
    if production_targets is None:
        return False
    return str(production_targets.mode).strip() == PRODUCTION_TARGETS_MODE_ROLLING_DEADLINE_ENVELOPE


def should_apply_terminal_inventory_value(
    *,
    apply_terminal_value: bool,
    production_targets: ProductionTargetsSettings | None,
) -> bool:
    if not bool(apply_terminal_value):
        return False
    if not is_rolling_deadline_mode(production_targets):
        return True
    return str(production_targets.terminal_inventory_value_mode).strip() != TERMINAL_INVENTORY_VALUE_MODE_DISABLED


def validate_target_accounting_policy(target_accounting_policy: str) -> str:
    normalized = str(target_accounting_policy).strip()
    if normalized not in TARGET_ACCOUNTING_POLICIES:
        raise ValueError(f"Unsupported target accounting policy: {target_accounting_policy!r}")
    return normalized


def _date_range_inclusive(start_day: date, end_day: date) -> list[date]:
    if end_day < start_day:
        return []
    cursor = start_day
    out: list[date] = []
    while cursor <= end_day:
        out.append(cursor)
        cursor += timedelta(days=1)
    return out


def _hours_in_local_day(local_day: date) -> float:
    day_start = pd.Timestamp(local_day.isoformat()).tz_localize(PRODUCTION_TARGETS_TZ)
    next_day_start = pd.Timestamp((local_day + timedelta(days=1)).isoformat()).tz_localize(PRODUCTION_TARGETS_TZ)
    return float((next_day_start.tz_convert("UTC") - day_start.tz_convert("UTC")).total_seconds() / 3600.0)


def deliverable_output_kg_per_site_load_mwh(*, hydrogen: object) -> float:
    h2_efficiency_kg_per_mwh = float(hydrogen.h2_efficiency_kg_per_mwh)
    compressor_specific_mwh_per_kg = float(hydrogen.compressor_specific_mwh_per_kg)
    if h2_efficiency_kg_per_mwh <= 0.0:
        raise ValueError("h2_efficiency_kg_per_mwh must be positive for reserve-feasibility conversion.")
    if compressor_specific_mwh_per_kg <= 0.0:
        raise ValueError("compressor_specific_mwh_per_kg must be positive for reserve-feasibility conversion.")
    site_mwh_per_kg = (1.0 / h2_efficiency_kg_per_mwh) + compressor_specific_mwh_per_kg
    if site_mwh_per_kg <= 0.0:
        raise ValueError("Computed site_mwh_per_kg must be positive for reserve-feasibility conversion.")
    return float(1.0 / site_mwh_per_kg)


def conservative_max_deliverable_kg_for_step_count(
    *,
    hydrogen: object,
    step_count: int,
    delta_t_hours: float,
) -> float:
    if step_count <= 0:
        return 0.0
    step_hours = float(delta_t_hours)
    if step_hours <= 0.0:
        raise ValueError("delta_t_hours must be positive for reserve-feasibility conversion.")
    ramp_per_h = float(hydrogen.electrolyser_ramp_mw_per_h)
    nominal_mw = float(hydrogen.electrolyser_nominal_mw)
    current_power = 0.0
    electrolyser_energy_mwh = 0.0
    for _ in range(int(step_count)):
        current_power = min(nominal_mw, current_power + ramp_per_h * step_hours)
        electrolyser_energy_mwh += current_power * step_hours
    electrolyser_limit = electrolyser_energy_mwh * float(hydrogen.h2_efficiency_kg_per_mwh)
    compressor_specific = float(hydrogen.compressor_specific_mwh_per_kg)
    if compressor_specific <= 0.0:
        raise ValueError("compressor_specific_mwh_per_kg must be positive for reserve-feasibility conversion.")
    compressor_limit = float(hydrogen.compressor_max_mw) * float(step_count) * step_hours / compressor_specific
    return float(min(electrolyser_limit, compressor_limit))


def conservative_max_deliverable_kg_for_local_day(
    *,
    hydrogen: object,
    local_day: date,
    delta_t_hours: float,
) -> float:
    day_hours = _hours_in_local_day(local_day)
    step_hours = float(delta_t_hours)
    if step_hours <= 0.0:
        raise ValueError("delta_t_hours must be positive for rolling deadline preprocessing.")
    step_count = int(round(day_hours / step_hours))
    if step_count <= 0 or abs(step_count * step_hours - day_hours) > 1e-9:
        raise ValueError(
            "Local-day duration is not compatible with delta_t_hours in rolling deadline preprocessing. "
            f"day_hours={day_hours}, delta_t_hours={step_hours}"
        )
    return conservative_max_deliverable_kg_for_step_count(
        hydrogen=hydrogen,
        step_count=step_count,
        delta_t_hours=delta_t_hours,
    )


def conservative_future_max_deliverable_kg(
    *,
    hydrogen: object,
    start_local_day: date,
    end_local_day: date,
    delta_t_hours: float,
) -> float:
    total = 0.0
    for local_day in _date_range_inclusive(start_local_day, end_local_day):
        total += conservative_max_deliverable_kg_for_local_day(
            hydrogen=hydrogen,
            local_day=local_day,
            delta_t_hours=delta_t_hours,
        )
    return float(total)


def build_rolling_production_target_plan(
    *,
    timestamps_utc: pd.DatetimeIndex,
    hydrogen: object,
    production_targets: ProductionTargetsSettings,
    delta_t_hours: float,
) -> RollingProductionTargetPlan:
    if not is_rolling_deadline_mode(production_targets):
        raise ValueError("Rolling production target preprocessing requested for non-rolling mode.")
    if timestamps_utc.empty:
        raise ValueError("Rolling production target preprocessing requires a non-empty horizon.")

    timestamps = pd.DatetimeIndex(pd.to_datetime(timestamps_utc, utc=True))
    local_timestamps = timestamps.tz_convert(PRODUCTION_TARGETS_TZ)
    local_dates = [ts.date() for ts in local_timestamps]
    horizon_start = local_dates[0]
    horizon_end = local_dates[-1]
    last_index_by_date: dict[date, int] = {}
    for idx, local_day in enumerate(local_dates):
        last_index_by_date[local_day] = idx

    if production_targets.max_inventory_kg is not None and float(production_targets.initial_inventory_kg) > float(production_targets.max_inventory_kg) + 1e-9:
        raise ValueError(
            "production_targets.initial_inventory_kg exceeds production_targets.max_inventory_kg "
            f"({production_targets.initial_inventory_kg} > {production_targets.max_inventory_kg})."
        )

    due_quantity_by_date: dict[date, float] = {}
    for target in production_targets.targets:
        due_day = date.fromisoformat(str(target.due_date))
        if target.earliest_production_date is not None and date.fromisoformat(str(target.earliest_production_date)) > due_day:
            raise ValueError(
                f"production target {target.delivery_id!r} has earliest_production_date after due_date."
            )
        due_quantity_by_date[due_day] = due_quantity_by_date.get(due_day, 0.0) + float(target.required_quantity_kg)

    sorted_due_days = sorted(due_quantity_by_date)
    cumulative_required_by_due: dict[date, float] = {}
    cumulative = 0.0
    for due_day in sorted_due_days:
        cumulative += float(due_quantity_by_date[due_day])
        cumulative_required_by_due[due_day] = float(cumulative)

    past_due_required_kg = max(
        [value for due_day, value in cumulative_required_by_due.items() if due_day < horizon_start] or [0.0]
    )
    if past_due_required_kg > float(production_targets.initial_inventory_kg) + 1e-9:
        raise ValueError(
            "Rolling production target calendar is already infeasible at horizon start: "
            f"past_due_required_kg={past_due_required_kg} exceeds initial_inventory_kg={production_targets.initial_inventory_kg}."
        )

    rolling_constraints: list[RollingDeadlineConstraint] = []
    for due_day in sorted_due_days:
        if horizon_start <= due_day <= horizon_end:
            rolling_constraints.append(
                RollingDeadlineConstraint(
                    due_date=due_day.isoformat(),
                    cutoff_time_index=int(last_index_by_date[due_day]),
                    cumulative_required_kg=float(cumulative_required_by_due[due_day]),
                )
            )

    terminal_guards: list[RollingTerminalFeasibilityGuard] = []
    for due_day in sorted_due_days:
        if due_day <= horizon_end:
            continue
        future_max_production = conservative_future_max_deliverable_kg(
            hydrogen=hydrogen,
            start_local_day=horizon_end + timedelta(days=1),
            end_local_day=due_day,
            delta_t_hours=delta_t_hours,
        )
        minimum_required = max(
            0.0,
            float(cumulative_required_by_due[due_day])
            - float(production_targets.initial_inventory_kg)
            - float(future_max_production),
        )
        terminal_guards.append(
            RollingTerminalFeasibilityGuard(
                due_date=due_day.isoformat(),
                cumulative_required_kg=float(cumulative_required_by_due[due_day]),
                future_max_production_kg=float(future_max_production),
                minimum_h_comp_required_by_horizon_end_kg=float(minimum_required),
                active=bool(minimum_required > 1e-9),
            )
        )

    due_by_close_local_date: dict[date, float] = {}
    for local_day in sorted(set(local_dates)):
        due_by_close_local_date[local_day] = max(
            [value for due_day, value in cumulative_required_by_due.items() if due_day <= local_day] or [0.0]
        )
    cumulative_required_due_by_time_index_kg = tuple(
        float(due_by_close_local_date[local_day]) for local_day in local_dates
    )

    return RollingProductionTargetPlan(
        mode=str(production_targets.mode),
        due_date_interpretation="date_only_due_by_end_of_local_delivery_day_europe_amsterdam",
        initial_inventory_kg=float(production_targets.initial_inventory_kg),
        max_inventory_kg=None if production_targets.max_inventory_kg is None else float(production_targets.max_inventory_kg),
        terminal_inventory_value_mode=str(production_targets.terminal_inventory_value_mode),
        horizon_start_local_date=horizon_start.isoformat(),
        horizon_end_local_date=horizon_end.isoformat(),
        production_credit_formula=(
            "future_daily_max_kg = min(conservative_ramp_from_zero_electrolyser_profile_kg(local_day_hours, delta_t_hours), "
            "compressor_max_mw * local_day_hours / compressor_specific_mwh_per_kg)"
        ),
        rolling_constraints=tuple(rolling_constraints),
        terminal_guards=tuple(terminal_guards),
        cumulative_requirements_by_due_date=tuple(
            (due_day.isoformat(), float(cumulative_required_by_due[due_day])) for due_day in sorted_due_days
        ),
        cumulative_required_due_by_time_index_kg=cumulative_required_due_by_time_index_kg,
        past_due_required_kg=float(past_due_required_kg),
    )


def build_rolling_up_recovery_proxy_bounds(
    *,
    timestamps_utc: pd.DatetimeIndex,
    hydrogen: object,
    rolling_target_plan: RollingProductionTargetPlan,
    delta_t_hours: float,
) -> tuple[RollingUpRecoveryProxyBound, ...]:
    timestamps = pd.DatetimeIndex(pd.to_datetime(timestamps_utc, utc=True))
    if timestamps.empty:
        return tuple()
    local_timestamps = timestamps.tz_convert(PRODUCTION_TARGETS_TZ)
    local_dates = [ts.date() for ts in local_timestamps]
    bounds: list[RollingUpRecoveryProxyBound] = []
    unique_due_requirements = [
        (date.fromisoformat(str(due_date)), float(cumulative_required_kg))
        for due_date, cumulative_required_kg in rolling_target_plan.cumulative_requirements_by_due_date
    ]
    for time_index, local_day in enumerate(local_dates):
        remaining_same_day_steps = int(sum(1 for future_day in local_dates[time_index + 1 :] if future_day == local_day))
        for due_day, cumulative_required_kg in unique_due_requirements:
            if due_day < local_day:
                continue
            future_max_recoverable_output_kg = conservative_max_deliverable_kg_for_step_count(
                hydrogen=hydrogen,
                step_count=remaining_same_day_steps,
                delta_t_hours=delta_t_hours,
            )
            if due_day > local_day:
                future_max_recoverable_output_kg += conservative_future_max_deliverable_kg(
                    hydrogen=hydrogen,
                    start_local_day=local_day + timedelta(days=1),
                    end_local_day=due_day,
                    delta_t_hours=delta_t_hours,
                )
            bounds.append(
                RollingUpRecoveryProxyBound(
                    time_index=int(time_index),
                    due_date=due_day.isoformat(),
                    cumulative_required_kg=float(cumulative_required_kg),
                    future_max_recoverable_output_kg=float(future_max_recoverable_output_kg),
                )
            )
    return tuple(bounds)


def build_production_target_policy(
    config: HydrogenConfig,
    *,
    target_mode: str,
    high_shortfall_penalty_rule: str = "max_10x_current_or_200_eur_per_kg",
) -> ProductionTargetPolicy:
    normalized_mode = str(target_mode).strip()
    if normalized_mode not in TARGET_MODES:
        raise ValueError(f"Unsupported production target mode: {target_mode!r}")

    baseline_penalty = float(config.economics.shortfall_penalty_eur_per_kg)
    if normalized_mode == TARGET_MODE_CURRENT_SOFT:
        applied_penalty = baseline_penalty
        hard_target = False
        slack_allowed = True
    elif normalized_mode == TARGET_MODE_HIGH_PENALTY:
        if str(high_shortfall_penalty_rule) != "max_10x_current_or_200_eur_per_kg":
            raise ValueError(
                "Unsupported high shortfall penalty rule: "
                f"{high_shortfall_penalty_rule!r}"
            )
        applied_penalty = max(10.0 * baseline_penalty, 200.0)
        hard_target = False
        slack_allowed = True
    else:
        applied_penalty = baseline_penalty
        hard_target = True
        slack_allowed = False

    return ProductionTargetPolicy(
        target_mode=normalized_mode,
        baseline_shortfall_penalty_eur_per_kg=baseline_penalty,
        applied_shortfall_penalty_eur_per_kg=float(applied_penalty),
        hard_target=bool(hard_target),
        slack_allowed=bool(slack_allowed),
        high_shortfall_penalty_rule=str(high_shortfall_penalty_rule),
    )


def is_hard_target_mode(target_mode: str) -> bool:
    return str(target_mode).strip() == TARGET_MODE_HARD
