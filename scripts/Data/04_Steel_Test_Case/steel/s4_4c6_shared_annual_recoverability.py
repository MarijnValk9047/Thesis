"""Shared annual terminal and calendar-continuation contracts for C0/C1.

This module deliberately contains no prices or objective terms.  It is the
single annual reporting-denominator contract reused by hourly deterministic
models and is structured so the QH and stochastic builders can consume the
same calendar rows later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


SHARED_ANNUAL_RECOVERABILITY_CONTRACT_VERSION = (
    "steel_shared_annual_recoverability_v10_physical_deadline"
)
ANNUAL_REPORTED_FINAL_PRODUCT_TARGET_T = 6_750_000.0
ANNUAL_REPORTED_FINAL_PRODUCT_TOLERANCE_T = 4_000.0
ANNUAL_REPORTED_FINAL_PRODUCT_LOWER_T = 6_746_000.0
ANNUAL_REPORTED_FINAL_PRODUCT_UPPER_T = 6_754_000.0


class AnnualRecoverabilityContractError(ValueError):
    """Raised when a shared annual contract is incomplete or contradictory."""


@dataclass(frozen=True)
class AnnualFinalProductBand:
    """Common reporting band and its configuration-specific physical image."""

    reporting_factor: float
    reported_target_t: float = ANNUAL_REPORTED_FINAL_PRODUCT_TARGET_T
    reported_tolerance_t: float = ANNUAL_REPORTED_FINAL_PRODUCT_TOLERANCE_T

    def __post_init__(self) -> None:
        if self.reporting_factor <= 0.0:
            raise AnnualRecoverabilityContractError(
                "Annual final-product reporting factor must be positive."
            )
        if self.reported_target_t <= self.reported_tolerance_t:
            raise AnnualRecoverabilityContractError(
                "Annual final-product tolerance is invalid."
            )

    @property
    def reported_lower_t(self) -> float:
        return self.reported_target_t - self.reported_tolerance_t

    @property
    def reported_upper_t(self) -> float:
        return self.reported_target_t + self.reported_tolerance_t

    @property
    def physical_target_t(self) -> float:
        return self.reported_target_t / self.reporting_factor

    @property
    def physical_lower_t(self) -> float:
        return self.reported_lower_t / self.reporting_factor

    @property
    def physical_upper_t(self) -> float:
        return self.reported_upper_t / self.reporting_factor

    @property
    def physical_tolerance_t(self) -> float:
        return self.reported_tolerance_t / self.reporting_factor

    def audit(self) -> dict[str, float | str]:
        return {
            "contract_version": SHARED_ANNUAL_RECOVERABILITY_CONTRACT_VERSION,
            "reported_target_t": self.reported_target_t,
            "reported_lower_t": self.reported_lower_t,
            "reported_upper_t": self.reported_upper_t,
            "reporting_factor": self.reporting_factor,
            "physical_target_t": self.physical_target_t,
            "physical_lower_t": self.physical_lower_t,
            "physical_upper_t": self.physical_upper_t,
            "physical_tolerance_t": self.physical_tolerance_t,
        }


def annual_final_product_band(
    *, configuration: str, c0_material_contract: Mapping[str, Any]
) -> AnnualFinalProductBand:
    """Resolve the common 6.75-Mt reporting band without changing C0 yields."""

    if str(configuration).startswith("C0"):
        factor = float(c0_material_contract["reporting_normalization_factor"])
        physical = float(c0_material_contract["physical_final_product_t_y"])
        expected = ANNUAL_REPORTED_FINAL_PRODUCT_TARGET_T / factor
        if abs(physical - expected) > 1e-6:
            raise AnnualRecoverabilityContractError(
                "C0 physical output and the common reporting denominator diverge."
            )
        return AnnualFinalProductBand(reporting_factor=factor)
    if str(configuration).startswith("C1"):
        return AnnualFinalProductBand(reporting_factor=1.0)
    raise AnnualRecoverabilityContractError(
        f"Unsupported annual configuration {configuration!r}."
    )


def validate_future_heat_calendar(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, int], ...]:
    """Validate and compact the price-blind future EAF calendar.

    Rows describe complete local calendar days after the execution day.  They
    carry physical daily heat bounds and quota-period membership; prices are
    intentionally neither accepted nor returned.
    """

    compact: list[dict[str, int]] = []
    previous_day = 0
    for raw in rows:
        row = {
            "calendar_day_index": int(raw["calendar_day_index"]),
            "day_length_hours": int(raw["day_length_hours"]),
            "lower_taps": int(raw["lower"]),
            "upper_taps": int(raw["upper"]),
            "quota_period_index": int(raw["quota_period_index"]),
            "quota_period_target": int(raw["quota_period_target"]),
            "quota_period_boundary": int(bool(raw["quota_period_boundary"])),
        }
        if row["calendar_day_index"] <= previous_day:
            raise AnnualRecoverabilityContractError(
                "Future heat-calendar days must be strictly ordered."
            )
        if row["day_length_hours"] not in {23, 24, 25}:
            raise AnnualRecoverabilityContractError(
                "Future heat-calendar day length must be 23, 24 or 25 hours."
            )
        if not 0 <= row["lower_taps"] <= row["upper_taps"]:
            raise AnnualRecoverabilityContractError(
                "Future heat-calendar bounds are invalid."
            )
        if row["quota_period_target"] < 0:
            raise AnnualRecoverabilityContractError(
                "Future heat-calendar quota target must be non-negative."
            )
        compact.append(row)
        previous_day = row["calendar_day_index"]
    return tuple(compact)


def future_quota_requirements(
    rows: Sequence[Mapping[str, int]],
    *,
    current_period_index: int,
    current_remaining_taps: int,
) -> dict[str, Any]:
    """Partition future calendar days without crossing a quota boundary."""

    if int(current_remaining_taps) < 0:
        raise AnnualRecoverabilityContractError(
            "Current remaining EAF quota cannot be negative."
        )
    period_rows: dict[int, list[int]] = {}
    period_targets: dict[int, int] = {}
    for index, row in enumerate(rows):
        period = int(row["quota_period_index"])
        period_rows.setdefault(period, []).append(index)
        target = int(row["quota_period_target"])
        if period in period_targets and period_targets[period] != target:
            raise AnnualRecoverabilityContractError(
                "A future quota period has inconsistent targets."
            )
        period_targets[period] = target
    current = int(current_period_index)
    later = {
        period: {
            "indices": tuple(indices),
            "target_taps": period_targets[period],
        }
        for period, indices in sorted(period_rows.items())
        if period != current
    }
    return {
        "current_period_index": current,
        "current_remaining_taps": int(current_remaining_taps),
        "current_future_indices": tuple(period_rows.get(current, ())),
        "current_closes_in_execution": current not in period_rows,
        "later_periods": later,
    }


__all__ = [
    "ANNUAL_REPORTED_FINAL_PRODUCT_LOWER_T",
    "ANNUAL_REPORTED_FINAL_PRODUCT_TARGET_T",
    "ANNUAL_REPORTED_FINAL_PRODUCT_TOLERANCE_T",
    "ANNUAL_REPORTED_FINAL_PRODUCT_UPPER_T",
    "AnnualFinalProductBand",
    "AnnualRecoverabilityContractError",
    "SHARED_ANNUAL_RECOVERABILITY_CONTRACT_VERSION",
    "annual_final_product_band",
    "future_quota_requirements",
    "validate_future_heat_calendar",
]
