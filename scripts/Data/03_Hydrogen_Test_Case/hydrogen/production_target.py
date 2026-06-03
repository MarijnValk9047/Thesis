from __future__ import annotations

from dataclasses import dataclass

from .plant_parameters import HydrogenConfig


TARGET_MODE_CURRENT_SOFT = "current_soft_target"
TARGET_MODE_HIGH_PENALTY = "high_shortfall_penalty"
TARGET_MODE_HARD = "hard_daily_target"
TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET = "included_day_prorated_weekly_target"

TARGET_MODES = (
    TARGET_MODE_CURRENT_SOFT,
    TARGET_MODE_HIGH_PENALTY,
    TARGET_MODE_HARD,
)

TARGET_ACCOUNTING_POLICIES = (
    TARGET_ACCOUNTING_POLICY_INCLUDED_DAY_PRORATED_WEEKLY_TARGET,
)


@dataclass(frozen=True)
class ProductionTargetPolicy:
    target_mode: str
    baseline_shortfall_penalty_eur_per_kg: float
    applied_shortfall_penalty_eur_per_kg: float
    hard_target: bool
    slack_allowed: bool
    high_shortfall_penalty_rule: str


def validate_target_accounting_policy(target_accounting_policy: str) -> str:
    normalized = str(target_accounting_policy).strip()
    if normalized not in TARGET_ACCOUNTING_POLICIES:
        raise ValueError(f"Unsupported target accounting policy: {target_accounting_policy!r}")
    return normalized


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
