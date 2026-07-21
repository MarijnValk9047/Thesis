"""Reusable rolling production-quota envelope for the steel feasibility model.

The pattern is adapted from the historical hydrogen rolling-deadline design,
but uses tonnes of final-product proxy and deliberately contains no market,
price or annual-calibration logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RollingProductionQuotaPlan:
    planning_horizon_hours: int
    execution_block_hours: int
    quota_per_execution_block_t: float
    cumulative_deadline_targets_t: dict[int, float]

    @property
    def total_quota_t(self) -> float:
        return self.cumulative_deadline_targets_t[self.planning_horizon_hours]


def build_rolling_production_quota_plan(
    *,
    planning_horizon_hours: int,
    execution_block_hours: int,
    quota_per_execution_block_t: float,
) -> RollingProductionQuotaPlan:
    """Create hard cumulative quota deadlines for a single planning window."""
    if planning_horizon_hours <= 0 or execution_block_hours <= 0:
        raise ValueError("Planning horizon and execution block must be positive.")
    if planning_horizon_hours % execution_block_hours != 0:
        raise ValueError("Planning horizon must be an exact multiple of the execution block.")
    if quota_per_execution_block_t <= 0.0:
        raise ValueError("Quota per execution block must be positive.")

    block_count = planning_horizon_hours // execution_block_hours
    deadlines = {
        block * execution_block_hours: float(block) * float(quota_per_execution_block_t)
        for block in range(1, block_count + 1)
    }
    return RollingProductionQuotaPlan(
        planning_horizon_hours=int(planning_horizon_hours),
        execution_block_hours=int(execution_block_hours),
        quota_per_execution_block_t=float(quota_per_execution_block_t),
        cumulative_deadline_targets_t=deadlines,
    )


def build_timestamped_rolling_production_quota_plan(
    *,
    planning_horizon_hours: int,
    execution_block_hours: int,
    cumulative_deadline_hours: list[int] | tuple[int, ...],
    quota_per_hour_t: float,
) -> RollingProductionQuotaPlan:
    """Create a quota plan from actual timestamp-derived delivery-day lengths.

    A five-local-day D-D+4 horizon contains 119, 120 or 121 UTC hours around
    daylight-saving transitions.  The production trajectory remains an hourly
    annual-rate proxy, while deadlines follow the ends of the represented
    local delivery days instead of assuming five identical 24-hour blocks.
    """

    if planning_horizon_hours <= 0 or execution_block_hours <= 0:
        raise ValueError("Planning horizon and execution block must be positive.")
    if quota_per_hour_t <= 0.0:
        raise ValueError("Hourly production quota must be positive.")
    deadlines = tuple(int(hour) for hour in cumulative_deadline_hours)
    if (
        not deadlines
        or deadlines != tuple(sorted(set(deadlines)))
        or deadlines[0] != int(execution_block_hours)
        or deadlines[-1] != int(planning_horizon_hours)
    ):
        raise ValueError(
            "Timestamped deadline hours must be unique, increasing, start at "
            "the execution boundary and end at the planning horizon."
        )
    targets = {hour: float(hour) * float(quota_per_hour_t) for hour in deadlines}
    return RollingProductionQuotaPlan(
        planning_horizon_hours=int(planning_horizon_hours),
        execution_block_hours=int(execution_block_hours),
        quota_per_execution_block_t=float(execution_block_hours)
        * float(quota_per_hour_t),
        cumulative_deadline_targets_t=targets,
    )
