"""Phase 6D one-day EAF heat-state hourly/QH engineering validation.

Only the C1 EAF is discrete.  Both hourly and quarter-hour DA cases solve the
same internal quarter-hour physical model.  The hourly market interface groups
four physical quarters into one pay-as-cleared hourly purchase bid.
"""

from __future__ import annotations

import copy
from bisect import bisect_left
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd
import yaml
from pyomo.environ import (
    Block,
    ConcreteModel,
    Constraint,
    NonNegativeReals,
    Objective,
    Set,
    Var,
    minimize,
    value,
)
from pyomo.repn import generate_standard_repn

from .model import collect_model_stats
from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
)
from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    ENERGY_TOLERANCE_MWH,
    MIP_GAP_LIMIT,
    MONEY_TOLERANCE_EUR,
    STEEL_BID_GRID,
    Phase6BError,
    SteelActualPriceBundle,
    SteelBidPlan,
    SteelClearingResult,
    SteelPhysicalContext,
    SteelPriceInformationBundle,
    SteelRollingState,
    _build_physical_model,
    _component_value,
    _executed_non_grid_cost,
    _git_head,
    _inventory_overrides,
    _load_oracle_prices,
    _policy_role,
    _policy_trajectory,
    _represented_cost_expression,
    _resolve,
    _scenario_inputs,
    _select_solver,
    _sha256,
    _solver_gap,
    _write_csv,
    _write_gzip_json_atomic,
    _write_json,
    clear_hourly_da_bids,
    expected_origin_utc,
    grid_sha256,
    load_hourly_actual_prices,
    load_hourly_price_information,
    load_phase6b_config,
    load_phase6c_config,
    load_qh_actual_prices,
    load_qh_price_information,
    prepare_physical_context,
)
from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    _apply_solver_time_limit,
)


PHASE6D_CONFIG = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "configs"
    / "steel_c6_phase6d_eaf_heat_state_one_day.yaml"
)
PHASE6B_CONFIG = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "configs"
    / "steel_c6_phase6b_hourly_da_bid_clear_redispatch.yaml"
)
PHASE6C_CONFIG = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "configs"
    / "steel_c6_phase6c_qh_da_bid_clear_redispatch.yaml"
)
PHASE6D_GRID_IDS = {
    "hourly": "steel_phase6d_hourly_shared_qh_eaf_bid_grid_v1",
    "quarterhour": "steel_phase6d_qh_shared_qh_eaf_bid_grid_v1",
}
PHASE6D_POLICIES = {
    "hourly": ("H-point", "price-insensitive", "true-PF", "H-S10"),
    "quarterhour": ("QH-point", "price-insensitive", "true-PF", "QH-S10"),
}
FULL_PHYSICAL_TIEBREAK = "full_physical_tiebreak"
EXPECTED_COST_INCUMBENT = "expected_cost_incumbent"
HANDOFF_STATE_TIEBREAK = "handoff_state_tiebreak"
EXECUTION_WINDOW_TIEBREAK = "execution_window_tiebreak"
NATIVE_GUROBI_HIERARCHY = "native_gurobi_hierarchy"
PLANNING_SOLVER_SEQUENTIAL = "sequential_pyomo"
PLANNING_SOLVER_NATIVE_TWO_OBJECTIVE = "native_gurobi_two_objective"
PLANNING_SOLVER_EXECUTION_MODES = {
    PLANNING_SOLVER_SEQUENTIAL,
    PLANNING_SOLVER_NATIVE_TWO_OBJECTIVE,
}
REDISPATCH_PHYSICAL_TIEBREAK_TIER = "redispatch_physical_tiebreak"
FEASIBILITY_BID_FULL_MILP = "full_canonical_bid_milp"
FEASIBILITY_BID_EXPECTED_COST_INCUMBENT = "expected_cost_incumbent"
FEASIBILITY_BID_FIXED_ECONOMIC_BINARY = (
    "fixed_economic_binary_reduced_canonicalisation"
)
FEASIBILITY_BID_SELECTION_MODES = {
    FEASIBILITY_BID_FULL_MILP,
    FEASIBILITY_BID_EXPECTED_COST_INCUMBENT,
    FEASIBILITY_BID_FIXED_ECONOMIC_BINARY,
}
PLANNING_PHYSICAL_TIEBREAK_MODES = {
    FULL_PHYSICAL_TIEBREAK,
    EXPECTED_COST_INCUMBENT,
    HANDOFF_STATE_TIEBREAK,
    EXECUTION_WINDOW_TIEBREAK,
    NATIVE_GUROBI_HIERARCHY,
}
EXPECTED_DELIVERY_DAY = date(2026, 4, 27)
PHYSICAL_TIME_STEP_HOURS = 0.25
PHYSICAL_INTERVALS_PER_DAY = 96
MATERIAL_TOLERANCE_T = 1e-5
DEFAULT_IMBALANCE_PENALTY_EUR_PER_MWH = 5000.0
ECONOMIC_MIP_GAP_LIMIT = 0.002
ECONOMIC_MIP_COST_TIERS = frozenset(
    {
        "parent_round_restricted_expected_cost_bridge",
        "expected_represented_cost",
        "redispatch_represented_cost",
        "redispatch_represented_cost_hard_zero_imbalance",
    }
)
# Use the same absolute MWh tolerance as the existing cleared-energy and
# physical-import identities.  Any larger deviation is material and cannot be
# rounded into a normal E-program-compliant result.
IMBALANCE_ZERO_TOLERANCE_MWH = ENERGY_TOLERANCE_MWH
MAX_PATH_FEASIBILITY_AUGMENTATION_ROUNDS = 3
SolverProgressCallback = Callable[[Mapping[str, Any]], None]


class Phase6DError(Phase6BError):
    """Raised when the Phase-6D engineering contract fails."""


class Phase6DPerformanceIncomplete(Phase6DError):
    """Raised when an otherwise valid head model does not prove optimality."""

    def __init__(
        self, message: str, diagnostic: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.diagnostic = dict(diagnostic or {})


class Phase6DEmergencyRecourse(Phase6DError):
    """Raised when minimum physically feasible imbalance remains positive."""

    def __init__(self, message: str, diagnostic: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.diagnostic = dict(diagnostic)


class Phase6DPathFeasibilityIncomplete(Phase6DError):
    """Raised when bounded clearing-pattern augmentation cannot close."""

    def __init__(self, message: str, diagnostic: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.diagnostic = dict(diagnostic)


@dataclass
class Phase6DRedispatchResult:
    policy: str
    configuration_id: str
    market_granularity: str
    delivery_day: date
    physical_intervals: list[dict[str, Any]]
    next_state: SteelRollingState
    produced_t: float
    other_represented_cost_eur: float
    imbalance_penalty_eur: float
    absolute_imbalance_mwh: float
    upward_consumption_imbalance_mwh: float
    downward_consumption_imbalance_mwh: float
    imbalance_affected_market_interval_count: int
    maximum_market_interval_imbalance_mwh: float
    solver: dict[str, Any]
    executed_route_progress_t: dict[str, float]


def load_phase6d_config(path: str | Path = PHASE6D_CONFIG) -> dict[str, Any]:
    config_path = _resolve(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("phase6d"), dict):
        raise Phase6DError("Phase-6D config must contain a phase6d mapping.")
    if (
        payload.get("output_policy") != "diagnostics"
        or payload.get("run_class") != "diagnostic_validation"
    ):
        raise Phase6DError("Phase-6D output classification changed.")
    phase = payload["phase6d"]
    if date.fromisoformat(str(phase["delivery_date"])) != EXPECTED_DELIVERY_DAY:
        raise Phase6DError("Phase-6D is restricted to 27 April 2026.")
    if (
        float(phase.get("time_step_hours", 0.0)) != PHYSICAL_TIME_STEP_HOURS
        or int(phase.get("planning_horizon_hours", 0)) != 120
        or int(phase.get("execution_hours", 0)) != 24
    ):
        raise Phase6DError("Phase-6D requires a 120-hour internal QH plan and 24-hour execution.")
    if tuple(float(item) for item in phase.get("bid_grid_eur_per_mwh", ())) != STEEL_BID_GRID:
        raise Phase6DError("The frozen sixteen-step steel bid grid changed.")
    if phase.get("actuals_use") != "clearing_settlement_and_isolated_pf_only":
        raise Phase6DError("Phase-6D actual-price information timing changed.")
    if (
        phase.get("c1_non_eaf_availability_policy")
        != "inherit_phase6b_phase6c_endogenous_commitment"
    ):
        raise Phase6DError(
            "Phase-6D must preserve the Phase-6B/6C C1 non-EAF commitment physics."
        )
    eaf = phase.get("eaf_heat_state", {})
    exact = {
        "heat_size_t_liquid_steel": 325.0,
        "total_qh_steps": 3,
        "melting_qh_steps": 2,
        "tapping_qh_steps": 1,
        "arc_electricity_mwh_per_t_liquid_steel": 0.4222222222,
        "secondary_electricity_mwh_per_t_liquid_steel": 0.031,
        "design_liquid_steel_rate_t_h": 458.0,
        "quantization_allowance_t": 162.5,
    }
    for key, expected in exact.items():
        observed = float(eaf.get(key, math.nan))
        if not math.isfinite(observed) or abs(observed - float(expected)) > 1e-10:
            raise Phase6DError(f"Frozen EAF heat-state parameter changed: {key}.")
    if (
        not bool(eaf.get("active"))
        or not bool(eaf.get("normal_operation_day_no_planned_maintenance"))
        or tuple(eaf.get("maintenance_intervals", ()))
    ):
        raise Phase6DError("The one-day Phase-6D run must be normal operation without maintenance.")
    if (
        int(eaf.get("weekly_taphole_maintenance_hours_documented_not_active", 0)) != 8
        or int(eaf.get("annual_maintenance_days_documented_not_active", 0)) != 14
    ):
        raise Phase6DError("Documented EAF maintenance anchors changed.")
    if expected_origin_utc(EXPECTED_DELIVERY_DAY) != pd.Timestamp(
        "2026-04-26T06:00:00Z"
    ):
        raise Phase6DError("D-1 08:00 Europe/Amsterdam origin contract changed.")
    return payload


def _context_for_market(
    config: Mapping[str, Any], market_granularity: str
) -> SteelPhysicalContext:
    if market_granularity not in {"hourly", "quarterhour"}:
        raise Phase6DError(f"Unsupported Phase-6D market granularity: {market_granularity}.")
    local = copy.deepcopy(dict(config))
    phase = local["phase6d"]
    phase["granularity"] = market_granularity
    phase["bid_grid_id"] = PHASE6D_GRID_IDS[market_granularity]
    phase["model_id"] = (
        "lear_lago_direct_dplus4_strict_no_future_1092"
        if market_granularity == "hourly"
        else "qh-fs1__mean_shape__hourly_anchor__lear_strict"
    )
    context = prepare_physical_context(local)
    if context.time_grid.time_step_hours != PHYSICAL_TIME_STEP_HOURS:
        raise Phase6DError("Hourly and QH Phase-6D contexts must share the internal QH grid.")
    return context


def _market_step_hours(granularity: str) -> float:
    return 1.0 if granularity == "hourly" else 0.25


def _physical_group_size(granularity: str) -> int:
    ratio = _market_step_hours(granularity) / PHYSICAL_TIME_STEP_HOURS
    if abs(ratio - round(ratio)) > 1e-12:
        raise Phase6DError("Market intervals do not align with the internal EAF grid.")
    return int(round(ratio))


def canonical_bid_volumes_from_scenario_requirements(
    scenario_prices: Mapping[str, Sequence[float]],
    scenario_imports: Mapping[str, Sequence[float]],
    *,
    bid_grid: Sequence[float] = STEEL_BID_GRID,
    tolerance_mwh: float = ENERGY_TOLERANCE_MWH,
) -> dict[tuple[int, float], float]:
    """Recover the frozen minimum-volume/highest-price canonical bid curve.

    The stochastic model identifies cumulative accepted quantity only at the
    sampled scenario prices.  This separable reconstruction selects the same
    canonical curve as the historical final bid MIP: no unused total volume,
    and every required incremental block at the highest grid price that keeps
    all sampled scenario clearings unchanged.
    """

    grid = tuple(float(item) for item in bid_grid)
    if not grid or tuple(sorted(grid)) != grid or len(set(grid)) != len(grid):
        raise Phase6DError("The canonical bid grid must be unique and increasing.")
    scenario_ids = tuple(sorted(scenario_prices))
    if not scenario_ids or set(scenario_imports) != set(scenario_ids):
        raise Phase6DError("Canonical bid inputs have different scenario support.")
    interval_count = len(scenario_prices[scenario_ids[0]])
    if any(
        len(scenario_prices[item]) != interval_count
        or len(scenario_imports[item]) != interval_count
        for item in scenario_ids
    ):
        raise Phase6DError("Canonical bid inputs have inconsistent horizons.")
    result = {
        (market_t, bid_price): 0.0
        for market_t in range(interval_count)
        for bid_price in grid
    }
    for market_t in range(interval_count):
        cumulative_by_first_accepted: dict[int, float] = {}
        for scenario_id in scenario_ids:
            price = float(scenario_prices[scenario_id][market_t])
            quantity = float(scenario_imports[scenario_id][market_t])
            first_accepted = bisect_left(grid, price)
            existing = cumulative_by_first_accepted.get(first_accepted)
            if existing is not None and abs(existing - quantity) > tolerance_mwh:
                raise Phase6DError(
                    "Scenarios with the same bid-grid acceptance set require "
                    "different quantities."
                )
            cumulative_by_first_accepted[first_accepted] = quantity
        cutoffs = sorted(cumulative_by_first_accepted)
        for left, right in zip(cutoffs, cutoffs[1:]):
            delta = (
                cumulative_by_first_accepted[left]
                - cumulative_by_first_accepted[right]
            )
            if delta < -tolerance_mwh or right <= 0:
                raise Phase6DError("Scenario quantities do not define a monotone bid curve.")
            if delta > tolerance_mwh:
                result[(market_t, grid[right - 1])] += max(0.0, delta)
        highest_cutoff = cutoffs[-1]
        highest_quantity = cumulative_by_first_accepted[highest_cutoff]
        if highest_quantity < -tolerance_mwh:
            raise Phase6DError("Canonical bid quantity cannot be negative.")
        if highest_cutoff < len(grid) and highest_quantity > tolerance_mwh:
            result[(market_t, grid[-1])] += max(0.0, highest_quantity)
        elif highest_cutoff == len(grid) and abs(highest_quantity) > tolerance_mwh:
            raise Phase6DError("Positive import is required above the maximum bid price.")
        for scenario_id in scenario_ids:
            reconstructed = sum(
                result[(market_t, bid_price)]
                for bid_price in grid
                if bid_price >= float(scenario_prices[scenario_id][market_t])
            )
            if (
                abs(reconstructed - float(scenario_imports[scenario_id][market_t]))
                > tolerance_mwh
            ):
                raise Phase6DError("Analytical canonical bid reconstruction failed.")
    return result


def _payload_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pattern_hash_payload(pattern: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in pattern.items()
        if key not in {"path_id", "pattern_sha256"}
    }


def _acceptance_mask_thresholds(
    pattern: Mapping[str, Any],
    *,
    bid_grid: Sequence[float] = STEEL_BID_GRID,
) -> tuple[float, ...]:
    """Map accepted bid-step ranks to portable synthetic clearing thresholds."""

    grid = tuple(float(item) for item in bid_grid)
    masks = pattern.get("acceptance_mask_by_lead_position")
    if not isinstance(masks, (tuple, list)):
        raise Phase6DError("Feasibility pattern has no acceptance-mask support.")
    thresholds: list[float] = []
    for mask in masks:
        row = tuple(bool(item) for item in mask)
        if len(row) != len(grid):
            raise Phase6DError("Feasibility acceptance mask differs from the bid grid.")
        accepted = tuple(index for index, item in enumerate(row) if item)
        if accepted and accepted != tuple(range(accepted[0], len(grid))):
            raise Phase6DError("Feasibility acceptance mask is not a monotone suffix.")
        thresholds.append(grid[accepted[0]] if accepted else grid[-1] + 1.0)
    return tuple(thresholds)


def validate_feasibility_clearing_pattern(
    pattern: Mapping[str, Any],
    *,
    market_granularity: str,
    market_intervals: int,
    bid_grid_id: str,
) -> dict[str, Any]:
    """Validate a probability-free validation clearing-pattern contract."""

    forbidden = {
        "probability",
        "scenario_probability",
        "expected_cost_weight",
        "raw_prices_eur_per_mwh",
    }
    if forbidden.intersection(pattern):
        raise Phase6DError(
            "Feasibility paths cannot carry probability, economic weight or raw prices."
        )
    if pattern.get("lineage_role") != "validation_derived_feasibility_only":
        raise Phase6DError("Feasibility pattern has the wrong lineage role.")
    source_class = str(pattern.get("source_class", "development_shadow"))
    if source_class == "development_shadow":
        if pattern.get("development_shadow_case") is not True:
            raise Phase6DError("A shadow pattern lost its development classification.")
        if not str(pattern.get("source_shadow_id", "")).startswith("shadow__"):
            raise Phase6DError("A shadow pattern has no governed shadow source id.")
        expected_cutoff_status = "D_minus_1_compliant"
    elif source_class == "controlled_synthetic_validation":
        if (
            pattern.get("development_shadow_case") is not False
            or pattern.get("development_validation_case") is not True
        ):
            raise Phase6DError(
                "A controlled synthetic pattern lost its validation classification."
            )
        if not str(pattern.get("source_validation_case_id", "")).startswith(
            "synthetic_validation__"
        ):
            raise Phase6DError(
                "A controlled synthetic pattern has no governed validation id."
            )
        lineage_hash = str(pattern.get("source_lineage_sha256", ""))
        if len(lineage_hash) != 64:
            raise Phase6DError(
                "A controlled synthetic pattern has incomplete source lineage."
            )
        expected_cutoff_status = "pre_final_validation_only_not_origin_information"
    else:
        raise Phase6DError("Unknown feasibility-pattern source class.")
    if pattern.get("final_test_case") is not False:
        raise Phase6DError("A final-test pattern source is forbidden.")
    if pattern.get("support_status") != "complete_uninterpolated":
        raise Phase6DError("Feasibility pattern support is not complete and frozen.")
    if pattern.get("cutoff_status") != expected_cutoff_status:
        raise Phase6DError("Feasibility pattern does not satisfy the D-1 cutoff.")
    if pattern.get("market_grid") != market_granularity:
        raise Phase6DError("Hourly and quarter-hour feasibility patterns cannot mix.")
    if int(pattern.get("market_interval_count", -1)) != int(market_intervals):
        raise Phase6DError("Feasibility pattern has incompatible market-grid support.")
    if pattern.get("bid_grid_id") != bid_grid_id:
        raise Phase6DError("Feasibility pattern uses a different canonical bid grid.")
    if pattern.get("bid_grid_sha256") != grid_sha256():
        raise Phase6DError("Feasibility pattern bid-grid hash changed.")
    lead_positions = tuple(int(item) for item in pattern.get("lead_positions", ()))
    if lead_positions != tuple(range(market_intervals)):
        raise Phase6DError("Feasibility lead positions are incomplete or reordered.")
    _acceptance_mask_thresholds(pattern)
    expected_hash = _payload_sha256(_pattern_hash_payload(pattern))
    if pattern.get("pattern_sha256") != expected_hash:
        raise Phase6DError("Feasibility pattern hash does not match its payload.")
    expected_path_id = f"feasibility_path__{expected_hash[:16]}"
    if pattern.get("path_id") != expected_path_id:
        raise Phase6DError("Feasibility path id is not canonical.")
    return dict(pattern)


def build_validation_feasibility_clearing_pattern(
    actual: SteelActualPriceBundle,
    *,
    source_shadow_id: str | None = None,
    source_validation_case_id: str | None = None,
    source_profile_id: str | None = None,
    source_lineage_sha256: str | None = None,
    bid_grid_id: str,
    forbidden_final_periods: Sequence[tuple[date, date]],
    support_status: str = "complete_uninterpolated",
    cutoff_status: str | None = None,
) -> dict[str, Any]:
    """Convert a validation actual into a transportable bid-rank mask.

    The authoritative clearing helper is exercised once per canonical bid rank.
    Absolute validation prices are deliberately omitted from the returned
    contract; another origin applies the mask by lead position and local bid
    rank only.
    """

    shadow_source = source_shadow_id is not None
    synthetic_source = source_validation_case_id is not None
    if shadow_source == synthetic_source:
        raise Phase6DError(
            "A feasibility pattern requires exactly one governed validation source."
        )
    if shadow_source:
        if not str(source_shadow_id).startswith("shadow__"):
            raise Phase6DError("A feasibility source must be a governed shadow id.")
        source_payload: dict[str, Any] = {
            "source_class": "development_shadow",
            "source_shadow_id": str(source_shadow_id),
            "development_shadow_case": True,
        }
        resolved_cutoff_status = cutoff_status or "D_minus_1_compliant"
        contract_version = "steel_c6_validation_feasibility_path_v1"
    else:
        if not str(source_validation_case_id).startswith("synthetic_validation__"):
            raise Phase6DError(
                "A synthetic feasibility source needs a governed validation id."
            )
        if not source_profile_id:
            raise Phase6DError("A synthetic feasibility source needs a profile id.")
        lineage_hash = str(source_lineage_sha256 or "")
        if len(lineage_hash) != 64:
            raise Phase6DError(
                "A synthetic feasibility source needs a complete lineage hash."
            )
        source_payload = {
            "source_class": "controlled_synthetic_validation",
            "source_validation_case_id": str(source_validation_case_id),
            "source_profile_id": str(source_profile_id),
            "source_lineage_sha256": lineage_hash,
            "development_validation_case": True,
            "development_shadow_case": False,
        }
        resolved_cutoff_status = (
            cutoff_status or "pre_final_validation_only_not_origin_information"
        )
        contract_version = "steel_c6_validation_feasibility_path_v2"
    if any(start <= actual.delivery_day <= end for start, end in forbidden_final_periods):
        raise Phase6DError("A final-week day cannot become an augmentation source.")
    interval_count = len(actual.timestamps_utc)
    if (
        interval_count != len(actual.prices)
        or interval_count * float(actual.time_step_hours) != 24.0
    ):
        raise Phase6DError("Feasibility patterns require one complete 24-hour grid.")
    if actual.granularity not in PHASE6D_GRID_IDS:
        raise Phase6DError("Unknown feasibility-pattern market grid.")
    if bid_grid_id != PHASE6D_GRID_IDS[actual.granularity]:
        raise Phase6DError("Pattern extraction received the wrong bid-grid identity.")

    marker_rows: list[dict[str, Any]] = []
    for lead_position, timestamp in enumerate(actual.timestamps_utc):
        for bid_price in STEEL_BID_GRID:
            marker_rows.append(
                {
                    "policy": "validation-feasibility-pattern",
                    "configuration_id": C1_CONFIGURATION,
                    "delivery_day": actual.delivery_day.isoformat(),
                    "target_timestamp_utc": timestamp.isoformat(),
                    "market_interval_index": lead_position,
                    "market_granularity": actual.granularity,
                    "market_time_step_hours": actual.time_step_hours,
                    "bid_grid_id": bid_grid_id,
                    "bid_grid_sha256": grid_sha256(),
                    "bid_price_eur_per_mwh": float(bid_price),
                    "incremental_bid_volume_mwh": 0.0,
                    "information_timing": "validation_pattern_extraction_only",
                }
            )
    masks = [[False for _ in STEEL_BID_GRID] for _ in range(interval_count)]
    for bid_index, bid_price in enumerate(STEEL_BID_GRID):
        marked = [
            {
                **row,
                "incremental_bid_volume_mwh": (
                    1.0
                    if float(row["bid_price_eur_per_mwh"]) == float(bid_price)
                    else 0.0
                ),
            }
            for row in marker_rows
        ]
        cleared = clear_hourly_da_bids(marked, actual)
        for lead_position, row in enumerate(cleared.hourly):
            quantity = float(row["cleared_energy_mwh"])
            if min(abs(quantity), abs(quantity - 1.0)) > ENERGY_TOLERANCE_MWH:
                raise Phase6DError("Canonical clearing did not yield a binary mask.")
            masks[lead_position][bid_index] = quantity > 0.5

    payload: dict[str, Any] = {
        "contract_version": contract_version,
        "lineage_role": "validation_derived_feasibility_only",
        **source_payload,
        "source_delivery_day": actual.delivery_day.isoformat(),
        "final_test_case": False,
        "support_status": str(support_status),
        "cutoff_status": str(resolved_cutoff_status),
        "market_grid": actual.granularity,
        "market_time_step_hours": float(actual.time_step_hours),
        "market_interval_count": interval_count,
        "lead_positions": list(range(interval_count)),
        "bid_grid_id": str(bid_grid_id),
        "bid_grid_sha256": grid_sha256(),
        "acceptance_mask_semantics": (
            "canonical_bid_step_rank_accepted_at_matching_lead_position"
        ),
        "acceptance_mask_by_lead_position": [
            [int(item) for item in row] for row in masks
        ],
        "economic_scenario": False,
        "settlement_eligible": False,
        "forecast_metric_eligible": False,
    }
    digest = _payload_sha256(payload)
    pattern = {
        **payload,
        "path_id": f"feasibility_path__{digest[:16]}",
        "pattern_sha256": digest,
    }
    return validate_feasibility_clearing_pattern(
        pattern,
        market_granularity=actual.granularity,
        market_intervals=interval_count,
        bid_grid_id=bid_grid_id,
    )


def actual_bundle_from_feasibility_pattern(
    pattern: Mapping[str, Any],
    *,
    delivery_day: date,
    timestamps_utc: Sequence[pd.Timestamp],
    market_granularity: str,
    market_time_step_hours: float,
    bid_grid_id: str,
) -> SteelActualPriceBundle:
    """Apply a shadow mask to another origin without copying shadow prices."""

    validated = validate_feasibility_clearing_pattern(
        pattern,
        market_granularity=market_granularity,
        market_intervals=len(timestamps_utc),
        bid_grid_id=bid_grid_id,
    )
    if abs(
        float(validated["market_time_step_hours"])
        - float(market_time_step_hours)
    ) > 1e-12:
        raise Phase6DError("Feasibility pattern time step differs from the local grid.")
    return SteelActualPriceBundle(
        delivery_day=delivery_day,
        timestamps_utc=tuple(pd.Timestamp(item) for item in timestamps_utc),
        prices=_acceptance_mask_thresholds(validated),
        granularity=market_granularity,
        time_step_hours=float(market_time_step_hours),
    )


def select_worst_feasibility_path_violation(
    diagnostics: Sequence[Mapping[str, Any]],
    *,
    tolerance_mwh: float = IMBALANCE_ZERO_TOLERANCE_MWH,
) -> dict[str, Any] | None:
    violating = [
        dict(row)
        for row in diagnostics
        if float(row.get("minimum_imbalance_mwh", math.inf)) > tolerance_mwh
    ]
    if not violating:
        return None
    return min(
        violating,
        key=lambda row: (
            -float(row["minimum_imbalance_mwh"]),
            str(row["path_id"]),
        ),
    )


def run_limited_path_feasibility_constraint_generation(
    candidate_paths: Sequence[Mapping[str, Any]],
    *,
    solve_plan: Callable[[Sequence[Mapping[str, Any]], int], SteelBidPlan],
    assess_plan: Callable[
        [SteelBidPlan, Sequence[Mapping[str, Any]], int],
        Sequence[Mapping[str, Any]],
    ],
    max_augmentation_rounds: int,
) -> dict[str, Any]:
    """Add at most one worst validation path per bounded augmentation round."""

    if not 1 <= int(max_augmentation_rounds) <= MAX_PATH_FEASIBILITY_AUGMENTATION_ROUNDS:
        raise Phase6DError("Path-feasibility augmentation must be capped at one to three rounds.")
    by_id = {str(row["path_id"]): dict(row) for row in candidate_paths}
    if len(by_id) != len(candidate_paths) or not by_id:
        raise Phase6DError("Constraint generation requires unique candidate paths.")
    selected: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    plan = solve_plan(tuple(selected), 0)
    for round_index in range(int(max_augmentation_rounds) + 1):
        diagnostics = [
            dict(item)
            for item in assess_plan(plan, tuple(by_id.values()), round_index)
        ]
        worst = select_worst_feasibility_path_violation(diagnostics)
        rounds.append(
            {
                "round_index": round_index,
                "selected_path_ids_before_round": [
                    str(item["path_id"]) for item in selected
                ],
                "assessed_path_count": len(diagnostics),
                "maximum_minimum_imbalance_mwh": max(
                    (
                        float(item.get("minimum_imbalance_mwh", math.inf))
                        for item in diagnostics
                    ),
                    default=0.0,
                ),
                "worst_path_id": None if worst is None else str(worst["path_id"]),
                "added_path_count": 0 if worst is None else 1,
                "plan_variable_count": plan.solver.get("variable_count"),
                "plan_binary_count": plan.solver.get("binary_count"),
                "plan_constraint_count": plan.solver.get("constraint_count"),
                "plan_total_solver_seconds": plan.solver.get("total_solver_seconds"),
            }
        )
        if worst is None:
            return {
                "status": "pass",
                "plan": plan,
                "selected_paths": selected,
                "rounds": rounds,
            }
        if round_index >= int(max_augmentation_rounds):
            break
        worst_id = str(worst["path_id"])
        if worst_id in {str(item["path_id"]) for item in selected}:
            raise Phase6DPathFeasibilityIncomplete(
                "An already active feasibility path remains infeasible.",
                {
                    "status": "path_feasibility_augmentation_incomplete",
                    "reason": "active_path_still_violating",
                    "path_id": worst_id,
                    "rounds": rounds,
                },
            )
        selected.append(by_id[worst_id])
        plan = solve_plan(tuple(selected), round_index + 1)
    raise Phase6DPathFeasibilityIncomplete(
        "Three bounded path-feasibility augmentation rounds were insufficient.",
        {
            "status": "path_feasibility_augmentation_incomplete",
            "reason": "maximum_augmentation_rounds_reached",
            "maximum_augmentation_rounds": int(max_augmentation_rounds),
            "selected_path_ids": [str(item["path_id"]) for item in selected],
            "rounds": rounds,
        },
    )


def _split_horizon_support(
    context: SteelPhysicalContext,
    price_bundle: SteelPriceInformationBundle,
) -> tuple[bool, int, int]:
    """Validate the 24h economic / longer price-free physical-tail contract."""

    market_intervals = len(price_bundle.timestamps_utc)
    group_size = _physical_group_size(price_bundle.granularity)
    economic_physical_intervals = market_intervals * group_size
    split_active = bool(context.physical_feasibility_tail_active)
    if not split_active:
        if economic_physical_intervals != context.time_grid.horizon_steps:
            raise Phase6DError(
                "Grouped bidding support differs from the configured physical horizon."
            )
        return False, market_intervals, economic_physical_intervals

    economic_hours = context.economic_horizon_hours
    if economic_hours is None:
        raise Phase6DError("The physical feasibility tail lacks an economic horizon.")
    if int(economic_hours) != int(context.time_grid.execution_hours):
        raise Phase6DError(
            "The split horizon must execute exactly its complete economic horizon."
        )
    if context.time_grid.horizon_hours <= int(economic_hours):
        raise Phase6DError("The physical feasibility tail must extend beyond the economic horizon.")
    expected_market_intervals = int(
        round(float(economic_hours) / float(price_bundle.time_step_hours))
    )
    if market_intervals != expected_market_intervals:
        raise Phase6DError(
            "The split-horizon price bundle must contain exactly the causal economic day."
        )
    if economic_physical_intervals != context.time_grid.execution_steps:
        raise Phase6DError(
            "Split-horizon market support does not align with the executed physical day."
        )
    return True, market_intervals, economic_physical_intervals


def _canonical_eaf_start_expression(model: Any) -> Any:
    """Choose one reproducible EAF timing after preserving physical objectives.

    Flat-price heat timing is otherwise non-unique.  An increasing timestamp
    weight selects the earliest feasible pattern without changing production,
    represented cost or the existing physical tie-break optimum.
    """

    if not hasattr(model, "eaf_heat_start"):
        raise Phase6DError("The Phase-6D C1 model has no EAF heat-start state.")
    return sum(
        (int(q) + 1) * model.eaf_heat_start[q]
        for q in model.TIME
    )


def _canonical_physical_path_expression(model: Any) -> Any:
    """Select one granularity-independent path after primary optima are fixed."""

    weighted_components = (
        ("coke_inventory", 1e-6),
        ("sinter_inventory", 1e-6),
        ("hot_iron_inventory", 1e-6),
        ("cold_slab_inventory", 1e-6),
        ("dri_inventory", 1e-6),
        ("final_product_output", 1e-4),
        ("net_grid_import_mwh", 1e-5),
        ("total_generator_electricity_mwh", 1e-5),
        ("total_named_ng_procurement_mwh", 1e-5),
    )
    terms = []
    for name, scale in weighted_components:
        if not hasattr(model, name):
            continue
        component = getattr(model, name)
        terms.extend(
            float(scale) * (int(q) + 1) * component[q]
            for q in model.TIME
        )
    if not terms:
        raise Phase6DError("No physical state is available for path canonicalisation.")
    return sum(terms)


def _handoff_state_tiebreak_expression(model: Any, execution_steps: int) -> Any:
    """Project the frozen tie-break onto variables exported to the next replan."""

    handoff = int(execution_steps) - 1
    if handoff < 1:
        raise Phase6DError("The handoff tie-break requires at least two intervals.")
    inventory_names = (
        "coke_inventory",
        "sinter_inventory",
        "hot_iron_inventory",
        "cold_slab_inventory",
        "dri_inventory",
    )
    continuous_state = sum(
        getattr(model, name)[handoff]
        for name in inventory_names
        if hasattr(model, name)
    )
    if hasattr(model, "drp_pellet_input"):
        continuous_state += model.drp_pellet_input[handoff]
    discrete_state = 0.0
    if hasattr(model, "eaf_heat_start"):
        discrete_state += (
            model.eaf_heat_start[handoff]
            + model.eaf_heat_start[handoff - 1]
        )
    if hasattr(model, "drp_on"):
        discrete_state += model.drp_on[handoff]
    return discrete_state + 1e-8 * continuous_state


def _execution_window_tiebreak_expression(
    model: Any, execution_steps: int
) -> Any:
    """Apply the frozen physical tie-break only to the executed 24-hour window."""

    indices = tuple(range(int(execution_steps)))
    process_names = (
        "coking_plant_1",
        "sintering_plant",
        "blast_furnace_6",
        "basic_oxygen_furnace",
        "hot_strip_mill",
    )
    commitment = sum(model.eaf_heat_start[t] for t in indices)
    commitment += sum(model.drp_on[t] for t in indices)
    commitment += sum(
        getattr(model, f"{name}_on")[t]
        for name in process_names
        for t in indices
    )
    inventory = 1e-8 * sum(
        model.dri_inventory[t]
        + model.coke_inventory[t]
        + model.sinter_inventory[t]
        + model.hot_iron_inventory[t]
        + model.cold_slab_inventory[t]
        for t in indices
    )
    flare = 1e-6 * sum(
        model.bfg_flared[t] + model.cog_flared[t] + model.bofg_flared[t]
        for t in indices
    )
    controller = sum(
        model.hsm_carrier_precedence_penalty[t]
        + 1e-5
        * (
            model.ng_to_pefa_malerij_mwh[t]
            + model.ng_to_pefa_branderij_mwh[t]
            + model.ng_to_boiler_mwh[t]
            + model.generator_named_ng_mwh[t]
        )
        for t in indices
    )
    daily = 0.0
    if hasattr(model, "COMMITMENT_DAY"):
        execution_days = max(1, math.ceil(int(execution_steps) / 96))
        daily = 1e-4 * sum(
            getattr(model, f"{name}_day_on")[day]
            for name in (*process_names, "drp")
            for day in model.COMMITMENT_DAY
            if int(day) < execution_days
        )
    return commitment + inventory + flare + controller + daily


def _planning_tiebreak_expression(
    model: Any, mode: str, execution_steps: int
) -> Any:
    if mode == HANDOFF_STATE_TIEBREAK:
        return _handoff_state_tiebreak_expression(model, execution_steps)
    if mode == EXECUTION_WINDOW_TIEBREAK:
        return _execution_window_tiebreak_expression(model, execution_steps)
    return model.static_price_naive_objective.expr


def _native_gurobi_linear_expression(solver: Any, expression: Any) -> Any:
    """Translate one Pyomo linear expression for native Gurobi multiobjective use."""

    import gurobipy as gp

    representation = generate_standard_repn(expression)
    if not representation.is_linear():
        raise Phase6DError("Native Gurobi hierarchy requires linear objectives.")
    result = gp.LinExpr(float(value(representation.constant)))
    for coefficient, variable in zip(
        representation.linear_coefs, representation.linear_vars
    ):
        result.addTerms(
            float(value(coefficient)),
            solver._pyomo_var_to_solver_var_map[variable],
        )
    return result


def _native_multiobjective_log_tiers(
    log_path: Path,
    *,
    model_stats: Any,
    fallback_status: str,
    fallback_termination: str,
    tier_names: Sequence[str] = (
        "production_progress",
        "expected_represented_cost",
        "physical_tiebreak",
    ),
) -> list[dict[str, Any]]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    markers = list(
        re.finditer(
            r"Multi-objectives:\s+optimize objective\s+\d+\s+\(([^)]+)\)",
            text,
        )
    )
    segments: list[str] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        segments.append(text[marker.end() : end])
    records: list[dict[str, Any]] = []
    previous_cumulative_seconds = 0.0
    for index, tier_name in enumerate(tier_names):
        # Gurobi truncates objective names in the text log.  Objective order is
        # the stable native contract, so parse by the explicitly assigned index.
        segment = segments[index] if index < len(segments) else ""
        explored = re.findall(
            r"Explored\s+([0-9]+)\s+nodes.*?in\s+([0-9.]+)\s+seconds\s+\(([0-9.eE+-]+)\s+work units\)",
            segment,
        )
        objective = re.findall(
            r"Best objective\s+([^,]+),\s+best bound\s+([^,]+),\s+gap\s+([0-9.]+)%",
            segment,
        )
        cumulative_seconds = (
            float(explored[-1][1]) if explored else previous_cumulative_seconds
        )
        attributed_seconds = max(
            0.0, cumulative_seconds - previous_cumulative_seconds
        )
        previous_cumulative_seconds = cumulative_seconds
        records.append(
            {
                "tier": tier_name,
                "solver_status": fallback_status,
                "termination_condition": fallback_termination,
                "mip_gap": (
                    float(objective[-1][2]) / 100.0 if objective else None
                ),
                "runtime_seconds": attributed_seconds,
                "wall_seconds": None,
                "solver_reported_time_seconds": attributed_seconds,
                "native_cumulative_solver_seconds": cumulative_seconds,
                "objective_value": (
                    float(objective[-1][0]) if objective else None
                ),
                "best_bound": float(objective[-1][1]) if objective else None,
                "branch_and_bound_nodes": int(explored[-1][0]) if explored else None,
                "gurobi_work_units": float(explored[-1][2]) if explored else None,
                "solver_log_file": log_path.name,
                "variable_count": model_stats.variables,
                "binary_count": model_stats.binaries,
                "constraint_count": model_stats.constraints,
                "incumbent_warm_start_requested": False,
                "incumbent_warm_start_used": False,
                "runtime_attribution": "difference_of_native_cumulative_log_times",
            }
        )
    return records


def _solve_native_gurobi_hierarchy(
    context: SteelPhysicalContext,
    model: ConcreteModel,
    *,
    progress_expr: Any,
    cost_expr: Any,
    tie_expr: Any,
) -> tuple[Any, list[dict[str, Any]], float, float, float, float]:
    """Solve the frozen three priorities in one native Gurobi invocation."""

    import gurobipy as gp
    from pyomo.environ import SolverFactory

    solver = SolverFactory("gurobi_persistent")
    if solver is None or not solver.available(exception_flag=False):
        raise Phase6DError("V4 requires the native gurobi_persistent interface.")
    solver.set_instance(model)
    settings = _phase6d_solver_settings(context)
    solver.options["TimeLimit"] = settings["time_limit_seconds"]
    solver.options["MIPGap"] = settings["mip_gap_limit"]
    solver.options["IntFeasTol"] = settings["integer_feasibility_tolerance"]
    if settings["seed"] is not None:
        solver.options["Seed"] = settings["seed"]
    log_directory = Path(str(context.config["solver_log_directory"]))
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / (
        f"{context.config.get('solver_log_prefix', 'solve')}__native_multiobjective.log"
    )
    solver.options["LogFile"] = str(log_path)
    native_model = solver._solver_model
    native_model.ModelSense = gp.GRB.MINIMIZE
    native_model.setObjectiveN(
        _native_gurobi_linear_expression(solver, progress_expr),
        0,
        priority=3,
        weight=1.0,
        abstol=1e-6,
        reltol=0.0,
        name="production_progress",
    )
    native_model.setObjectiveN(
        _native_gurobi_linear_expression(solver, cost_expr),
        1,
        priority=2,
        weight=1.0,
        abstol=float(context.cost_tolerance_eur),
        reltol=0.0,
        name="expected_represented_cost",
    )
    native_model.setObjectiveN(
        _native_gurobi_linear_expression(solver, tie_expr),
        2,
        priority=1,
        weight=1.0,
        abstol=0.0,
        reltol=0.0,
        name="physical_tiebreak",
    )
    started = time.perf_counter()
    result = solver.solve(load_solutions=True)
    total_wall_seconds = time.perf_counter() - started
    termination = str(result.solver.termination_condition).lower()
    stats = collect_model_stats(model)
    tiers = _native_multiobjective_log_tiers(
        log_path,
        model_stats=stats,
        fallback_status=str(result.solver.status),
        fallback_termination=str(result.solver.termination_condition),
    )
    if termination != "optimal" or any(
        record["objective_value"] is None for record in tiers
    ):
        raise Phase6DPerformanceIncomplete(
            "native_gurobi_hierarchy did not prove all objectives: "
            f"termination={result.solver.termination_condition}, tiers={tiers}."
        )
    return (
        result,
        tiers,
        float(tiers[0]["objective_value"]),
        float(tiers[1]["objective_value"]),
        float(tiers[2]["objective_value"]),
        total_wall_seconds,
    )


def _solve_native_gurobi_two_objective(
    context: SteelPhysicalContext,
    model: ConcreteModel,
    *,
    progress_expr: Any,
    cost_expr: Any,
    progress_callback: SolverProgressCallback | None,
) -> tuple[Any, list[dict[str, Any]], float, float, float]:
    """Solve production progress and expected cost in one native invocation."""

    import gurobipy as gp
    from pyomo.environ import SolverFactory

    solver = SolverFactory("gurobi_persistent")
    if solver is None or not solver.available(exception_flag=False):
        raise Phase6DError(
            "Native two-objective planning requires gurobi_persistent."
        )
    solver.set_instance(model)
    settings = _phase6d_solver_settings(context)
    solver.options["TimeLimit"] = settings["time_limit_seconds"]
    solver.options["MIPGap"] = settings["mip_gap_limit"]
    solver.options["IntFeasTol"] = settings["integer_feasibility_tolerance"]
    if settings["seed"] is not None:
        solver.options["Seed"] = settings["seed"]
    log_directory = Path(str(context.config["solver_log_directory"]))
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / (
        f"{context.config.get('solver_log_prefix', 'solve')}__native_two_objective.log"
    )
    solver.options["LogFile"] = str(log_path)
    native_model = solver._solver_model
    native_model.ModelSense = gp.GRB.MINIMIZE
    native_model.setObjectiveN(
        _native_gurobi_linear_expression(solver, progress_expr),
        0,
        priority=2,
        weight=1.0,
        abstol=1e-6,
        reltol=0.0,
        name="production_progress",
    )
    native_model.setObjectiveN(
        _native_gurobi_linear_expression(solver, cost_expr),
        1,
        priority=1,
        weight=1.0,
        abstol=0.0,
        reltol=0.0,
        name="expected_represented_cost",
    )
    started_at_utc = datetime.now(timezone.utc).isoformat()
    if progress_callback is not None:
        for tier_name in ("production_progress", "expected_represented_cost"):
            progress_callback(
                {
                    "event": "solver_tier_started",
                    "tier": tier_name,
                    "started_at_utc": started_at_utc,
                    "native_multiobjective_invocation": True,
                }
            )
    started = time.perf_counter()
    result = solver.solve(load_solutions=True)
    total_wall_seconds = time.perf_counter() - started
    termination = str(result.solver.termination_condition).lower()
    stats = collect_model_stats(model)
    tiers = _native_multiobjective_log_tiers(
        log_path,
        model_stats=stats,
        fallback_status=str(result.solver.status),
        fallback_termination=str(result.solver.termination_condition),
        tier_names=("production_progress", "expected_represented_cost"),
    )
    for record in tiers:
        record["native_multiobjective_invocation"] = True
        record["native_total_wall_seconds"] = total_wall_seconds
        if progress_callback is not None:
            progress_callback({"event": "solver_tier_finished", **record})
    if termination != "optimal" or any(
        record["objective_value"] is None for record in tiers
    ):
        diagnostic = {
            "status": "performance_incomplete",
            "native_total_wall_seconds": total_wall_seconds,
            "tier_solves": tiers,
        }
        raise Phase6DPerformanceIncomplete(
            "native_gurobi_two_objective did not prove both objectives.",
            diagnostic=diagnostic,
        )
    return (
        result,
        tiers,
        float(tiers[0]["objective_value"]),
        float(tiers[1]["objective_value"]),
        total_wall_seconds,
    )


def _expand_market_values(
    values: Sequence[float], market_granularity: str
) -> tuple[float, ...]:
    group = _physical_group_size(market_granularity)
    return tuple(float(item) for item in values for _ in range(group))


def _physical_timestamp(
    market_timestamp: pd.Timestamp, within_market_index: int
) -> pd.Timestamp:
    return pd.Timestamp(market_timestamp) + pd.Timedelta(
        minutes=15 * int(within_market_index)
    )


def _parse_gurobi_performance_log(log_text: str) -> dict[str, float | int]:
    parsed: dict[str, float | int] = {}

    def last_match(pattern: str) -> tuple[str, ...] | None:
        matches = re.findall(pattern, log_text, flags=re.MULTILINE)
        if not matches:
            return None
        match = matches[-1]
        return (match,) if isinstance(match, str) else tuple(match)

    presolve_removed = last_match(
        r"Presolve removed\s+([0-9]+)\s+rows and\s+([0-9]+)\s+columns"
    )
    if presolve_removed:
        parsed["presolve_removed_rows"] = int(presolve_removed[0])
        parsed["presolve_removed_columns"] = int(presolve_removed[1])
    presolved = last_match(
        r"Presolved:\s+([0-9]+)\s+rows,\s+([0-9]+)\s+columns,\s+([0-9]+)\s+nonzeros"
    )
    if presolved:
        parsed["presolved_rows"] = int(presolved[0])
        parsed["presolved_columns"] = int(presolved[1])
        parsed["presolved_nonzeros"] = int(presolved[2])
    presolve_time = last_match(r"Presolve time:\s*([0-9.eE+-]+)s")
    if presolve_time:
        parsed["presolve_seconds"] = float(presolve_time[0])
    root = last_match(
        r"Root relaxation:\s*objective\s+([0-9.eE+-]+).*?([0-9.eE+-]+)\s+seconds"
    )
    if root:
        parsed["root_relaxation_objective"] = float(root[0])
        parsed["root_relaxation_seconds"] = float(root[1])
    root_work = last_match(
        r"Root relaxation:.*?\(([0-9.eE+-]+)\s+work units\)"
    )
    if root_work:
        parsed["root_relaxation_work_units"] = float(root_work[0])
    mip_start = last_match(
        r"Loaded user MIP start with objective\s+([0-9.eE+-]+)"
    )
    if mip_start:
        parsed["loaded_mip_start_objective"] = float(mip_start[0])
    heuristic = re.findall(
        r"Found heuristic solution:\s*objective\s+([0-9.eE+-]+)", log_text
    )
    if heuristic:
        parsed["first_heuristic_incumbent"] = float(heuristic[0])
    objective = last_match(
        r"Best objective\s+([^,]+),\s+best bound\s+([^,]+),\s+gap\s+([0-9.eE+-]+)%"
    )
    if objective:
        parsed["best_incumbent"] = float(objective[0])
        parsed["best_bound"] = float(objective[1])
        parsed["final_mip_gap"] = float(objective[2]) / 100.0
    explored = last_match(
        r"Explored\s+([0-9]+)\s+nodes.*?in\s+([0-9.]+)\s+seconds"
        r"(?:\s+\(([0-9.eE+-]+)\s+work units\))?"
    )
    if explored:
        parsed["branch_and_bound_nodes"] = int(explored[0])
        parsed["solver_reported_time_seconds"] = float(explored[1])
        if len(explored) > 2 and explored[2]:
            parsed["work_units"] = float(explored[2])
    work = last_match(r"Work units:\s*([0-9.eE+-]+)")
    if work:
        parsed["work_units"] = float(work[0])
    symmetry = last_match(r"Detected\s+([0-9]+)\s+symmetr(?:y|ies)")
    if symmetry:
        parsed["detected_symmetry_count"] = int(symmetry[0])
    return parsed


def _solve_optimal(
    model: ConcreteModel,
    solver: Any,
    tier: str,
    *,
    warmstart: bool,
    economic_mip_gap_limit: float | None = None,
    progress_callback: SolverProgressCallback | None = None,
) -> tuple[Any, dict[str, Any]]:
    if economic_mip_gap_limit is not None:
        if tier not in ECONOMIC_MIP_COST_TIERS:
            raise Phase6DError(
                "The economic MIP-gap policy cannot be applied to a physical tier."
            )
        if not math.isclose(
            float(economic_mip_gap_limit),
            ECONOMIC_MIP_GAP_LIMIT,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise Phase6DError("The fixed economic MIP-gap policy changed.")
    log_directory = getattr(solver, "_phase6d_log_directory", None)
    log_prefix = str(getattr(solver, "_phase6d_log_prefix", "solve"))
    log_path: Path | None = None
    if log_directory is not None:
        log_path = Path(log_directory) / f"{log_prefix}__{tier}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        solver.options["LogFile"] = str(log_path)
    started_at_utc = datetime.now(timezone.utc).isoformat()
    if progress_callback is not None:
        progress_callback(
            {
                "event": "solver_tier_started",
                "tier": tier,
                "started_at_utc": started_at_utc,
                "incumbent_warm_start_requested": warmstart,
            }
        )
    started = time.perf_counter()
    missing_option = object()
    previous_mip_gap = solver.options.get("MIPGap", missing_option)
    if economic_mip_gap_limit is not None:
        solver.options["MIPGap"] = float(economic_mip_gap_limit)
    try:
        try:
            result = solver.solve(model, warmstart=warmstart)
            warmstart_used = warmstart
        except (TypeError, ValueError):
            result = solver.solve(model)
            warmstart_used = False
    except Exception as exc:
        runtime = time.perf_counter() - started
        failure = {
            "event": "solver_tier_finished",
            "tier": tier,
            "started_at_utc": started_at_utc,
            "ended_at_utc": datetime.now(timezone.utc).isoformat(),
            "runtime_seconds": runtime,
            "solver_status": "exception",
            "termination_condition": type(exc).__name__,
            "mip_gap": None,
            "error": str(exc),
        }
        if progress_callback is not None:
            progress_callback(failure)
        error = Phase6DError(f"{tier} solver invocation failed: {failure}.")
        error.diagnostic = {"status": "solver_invocation_failure", "tier": failure}
        raise error from exc
    finally:
        if economic_mip_gap_limit is not None:
            if previous_mip_gap is missing_option:
                solver.options.pop("MIPGap", None)
            else:
                solver.options["MIPGap"] = previous_mip_gap
    runtime = time.perf_counter() - started
    ended_at_utc = datetime.now(timezone.utc).isoformat()
    termination = str(result.solver.termination_condition).lower()
    gap = _solver_gap(result)
    statistics = getattr(result.solver, "statistics", None)
    branch_and_bound = (
        getattr(statistics, "branch_and_bound", None)
        if statistics is not None
        else None
    )

    def _optional_number(*names: str) -> float | int | None:
        for container in (branch_and_bound, result.solver):
            if container is None:
                continue
            for name in names:
                candidate = getattr(container, name, None)
                if candidate is None:
                    continue
                try:
                    number = float(candidate)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(number):
                    continue
                return int(number) if number.is_integer() else number
        return None

    active_objectives = list(
        model.component_data_objects(Objective, active=True, descend_into=True)
    )
    stats = collect_model_stats(model)
    parsed_log: dict[str, float | int] = {}
    if log_path is not None and log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        parsed_log = _parse_gurobi_performance_log(log_text)
        if gap is None and "final_mip_gap" in parsed_log:
            gap = float(parsed_log["final_mip_gap"])
    objective_value: float | None = None
    if len(active_objectives) == 1:
        try:
            candidate = float(value(active_objectives[0]))
        except (TypeError, ValueError):
            candidate = math.nan
        if math.isfinite(candidate):
            objective_value = candidate

    problem = getattr(result, "problem", None)

    def _problem_number(name: str) -> float | None:
        candidate = getattr(problem, name, None)
        try:
            number = float(candidate)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    best_incumbent = parsed_log.get("best_incumbent")
    if best_incumbent is None:
        best_incumbent = _problem_number("upper_bound")
    best_bound = parsed_log.get("best_bound")
    if best_bound is None:
        best_bound = _problem_number("lower_bound")
    epsilon_record = _economic_mip_acceptance_record(
        tier=tier,
        termination=termination,
        objective_value=objective_value,
        best_incumbent=best_incumbent,
        best_bound=best_bound,
        accepted_relative_gap=economic_mip_gap_limit,
    )
    record = {
        "tier": tier,
        "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "mip_gap": gap,
        "runtime_seconds": runtime,
        "wall_seconds": runtime,
        "started_at_utc": started_at_utc,
        "ended_at_utc": ended_at_utc,
        "solver_reported_time_seconds": parsed_log.get(
            "solver_reported_time_seconds",
            _optional_number("wallclock_time", "time", "user_time"),
        ),
        "objective_value": objective_value,
        "branch_and_bound_nodes": parsed_log.get(
            "branch_and_bound_nodes",
            _optional_number(
                "number_of_created_subproblems",
                "number_of_bounded_subproblems",
                "node_count",
            ),
        ),
        "gurobi_work_units": parsed_log.get("work_units"),
        "presolve_removed_rows": parsed_log.get("presolve_removed_rows"),
        "presolve_removed_columns": parsed_log.get("presolve_removed_columns"),
        "presolved_rows": parsed_log.get("presolved_rows"),
        "presolved_columns": parsed_log.get("presolved_columns"),
        "presolved_nonzeros": parsed_log.get("presolved_nonzeros"),
        "presolve_seconds": parsed_log.get("presolve_seconds"),
        "root_relaxation_objective": parsed_log.get("root_relaxation_objective"),
        "root_relaxation_seconds": parsed_log.get("root_relaxation_seconds"),
        "root_relaxation_work_units": parsed_log.get(
            "root_relaxation_work_units"
        ),
        "loaded_mip_start_objective": parsed_log.get(
            "loaded_mip_start_objective"
        ),
        "first_heuristic_incumbent": parsed_log.get("first_heuristic_incumbent"),
        "best_incumbent": best_incumbent,
        "best_bound": best_bound,
        "detected_symmetry_count": parsed_log.get("detected_symmetry_count"),
        "solver_log_file": log_path.name if log_path is not None else None,
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "incumbent_warm_start_requested": warmstart,
        "incumbent_warm_start_used": warmstart_used,
        **epsilon_record,
    }
    if progress_callback is not None:
        progress_callback({"event": "solver_tier_finished", **record})
    accepted_epsilon = bool(record["epsilon_optimal_accepted"])
    if economic_mip_gap_limit is not None and not accepted_epsilon:
        raise Phase6DPerformanceIncomplete(
            f"{tier} lacks a valid economic epsilon-optimality certificate: "
            f"{record}.",
            diagnostic={
                "status": "economic_epsilon_optimality_unproven",
                "tier": record,
            },
        )
    if termination != "optimal" and not accepted_epsilon:
        if "time" in termination or "limit" in termination:
            raise Phase6DPerformanceIncomplete(
                f"{tier} did not prove optimality: {record}.",
                diagnostic={"status": "performance_incomplete", "tier": record},
            )
        error = Phase6DError(f"{tier} solve failed: {record}.")
        error.diagnostic = {"status": "solver_failure", "tier": record}
        raise error
    return result, record


def _economic_mip_acceptance_record(
    *,
    tier: str,
    termination: str,
    objective_value: float | None,
    best_incumbent: float | int | None,
    best_bound: float | int | None,
    accepted_relative_gap: float | None,
) -> dict[str, Any]:
    """Return a fail-closed certificate for an economic minimisation tier."""

    economic_policy_active = accepted_relative_gap is not None
    default = {
        "economic_mip_gap_policy_active": economic_policy_active,
        "economic_mip_gap_limit": accepted_relative_gap,
        "epsilon_optimal_accepted": False,
        "optimality_class": "strict_optimal" if termination == "optimal" else None,
        "objective_lower_bound_eur": None,
        "objective_upper_bound_eur": None,
        "absolute_objective_band_eur": None,
        "certified_relative_gap": None,
    }
    if not economic_policy_active:
        return default
    if tier not in ECONOMIC_MIP_COST_TIERS:
        raise Phase6DError("Economic MIP acceptance was requested for a physical tier.")
    eligible_termination = termination == "optimal" or (
        "time" in termination and "limit" in termination
    )
    if not eligible_termination:
        return default
    values = (objective_value, best_incumbent, best_bound)
    try:
        objective, incumbent, bound = (float(item) for item in values)
    except (TypeError, ValueError):
        return default
    if not all(math.isfinite(item) for item in (objective, incumbent, bound)):
        return default
    objective_match_tolerance = max(MONEY_TOLERANCE_EUR, 1e-9 * abs(incumbent))
    if abs(objective - incumbent) > objective_match_tolerance:
        return default
    absolute_band = incumbent - bound
    if absolute_band < -objective_match_tolerance:
        return default
    absolute_band = max(0.0, absolute_band)
    denominator = max(abs(incumbent), 1e-12)
    certified_gap = absolute_band / denominator
    accepted = certified_gap <= float(accepted_relative_gap) + 1e-12
    return {
        **default,
        "epsilon_optimal_accepted": accepted,
        "optimality_class": "epsilon_optimal" if accepted else None,
        "objective_lower_bound_eur": bound,
        "objective_upper_bound_eur": incumbent,
        "absolute_objective_band_eur": absolute_band,
        "certified_relative_gap": certified_gap,
    }


def _solver_for_phase6d(context: SteelPhysicalContext) -> tuple[str, Any]:
    solver_name, solver = _select_solver()
    if solver is None or not str(solver_name).startswith("gurobi"):
        raise Phase6DError("Phase-6D requires Gurobi.")
    settings = _phase6d_solver_settings(context)
    _apply_solver_time_limit(solver_name, solver, settings["time_limit_seconds"])
    solver.options["MIPGap"] = settings["mip_gap_limit"]
    solver.options["IntFeasTol"] = settings["integer_feasibility_tolerance"]
    if settings["seed"] is not None:
        solver.options["Seed"] = settings["seed"]
    for name, option_value in settings["gurobi_performance_options"].items():
        solver.options[name] = option_value
    if context.config.get("solver_log_directory") is not None:
        solver._phase6d_log_directory = str(
            context.config["solver_log_directory"]
        )
        solver._phase6d_log_prefix = str(
            context.config.get("solver_log_prefix", "solve")
        )
    return str(solver_name), solver


def _phase6d_solver_settings(context: SteelPhysicalContext) -> dict[str, Any]:
    economic_mip_gap_limit = float(
        context.config.get("economic_mip_gap_limit", ECONOMIC_MIP_GAP_LIMIT)
    )
    if not math.isclose(
        economic_mip_gap_limit,
        ECONOMIC_MIP_GAP_LIMIT,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise Phase6DError("The fixed economic MIP-gap policy changed.")
    return {
        "time_limit_seconds": float(context.config["solver_time_limit_seconds"]),
        "mip_gap_limit": float(context.config.get("mip_gap_limit", MIP_GAP_LIMIT)),
        "economic_mip_gap_limit": economic_mip_gap_limit,
        "integer_feasibility_tolerance": float(
            context.config.get("integer_feasibility_tolerance", 1e-9)
        ),
        "seed": (
            int(context.config["solver_seed"])
            if context.config.get("solver_seed") is not None
            else None
        ),
        "gurobi_performance_options": _gurobi_performance_options(context),
    }


def _gurobi_performance_options(
    context: SteelPhysicalContext,
) -> dict[str, int | float]:
    raw = context.config.get("gurobi_performance_options", {})
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise Phase6DError("gurobi_performance_options must be a mapping.")
    allowed: dict[str, tuple[float, float, type]] = {
        "MIPFocus": (0, 3, int),
        "Cuts": (-1, 3, int),
        "Symmetry": (-1, 2, int),
        "Heuristics": (0.0, 1.0, float),
    }
    result: dict[str, int | float] = {}
    for name, option_value in raw.items():
        if name not in allowed:
            raise Phase6DError(f"Unsupported Gurobi performance option: {name}.")
        lower, upper, target_type = allowed[name]
        try:
            converted = target_type(option_value)
        except (TypeError, ValueError) as exc:
            raise Phase6DError(
                f"Invalid Gurobi performance option value for {name}."
            ) from exc
        if not lower <= float(converted) <= upper:
            raise Phase6DError(
                f"Gurobi performance option {name} is outside its safe range."
            )
        result[name] = converted
    return result


def _gurobi_version() -> str:
    try:
        import gurobipy as gp

        raw = gp.gurobi.version()
    except Exception:
        return "unavailable"
    return ".".join(str(item) for item in raw) if isinstance(raw, tuple) else str(raw)


def _planning_physical_tiebreak_mode(context: SteelPhysicalContext) -> str:
    mode = str(
        context.config.get(
            "planning_physical_tiebreak_mode", FULL_PHYSICAL_TIEBREAK
        )
    )
    if mode not in PLANNING_PHYSICAL_TIEBREAK_MODES:
        raise Phase6DError(
            "Unsupported planning_physical_tiebreak_mode: " f"{mode!r}."
        )
    return mode


def _planning_solver_execution_mode(context: SteelPhysicalContext) -> str:
    mode = str(
        context.config.get(
            "planning_solver_execution_mode", PLANNING_SOLVER_SEQUENTIAL
        )
    )
    if mode not in PLANNING_SOLVER_EXECUTION_MODES:
        raise Phase6DError(
            f"Unsupported planning_solver_execution_mode: {mode!r}."
        )
    return mode


def _planning_physical_tiebreak_solve_required(mode: str) -> bool:
    if mode not in PLANNING_PHYSICAL_TIEBREAK_MODES:
        raise Phase6DError(
            "Unsupported planning_physical_tiebreak_mode: " f"{mode!r}."
        )
    return mode != EXPECTED_COST_INCUMBENT


def _feasibility_bid_selection_mode(context: SteelPhysicalContext) -> str:
    mode = str(
        context.config.get(
            "feasibility_bid_selection_mode", FEASIBILITY_BID_FULL_MILP
        )
    )
    if mode not in FEASIBILITY_BID_SELECTION_MODES:
        raise Phase6DError(
            f"Unsupported feasibility_bid_selection_mode: {mode!r}."
        )
    return mode


def _feasibility_bid_canonical_solve_required(
    mode: str, *, feasibility_path_count: int
) -> bool:
    if mode not in FEASIBILITY_BID_SELECTION_MODES:
        raise Phase6DError(
            f"Unsupported feasibility_bid_selection_mode: {mode!r}."
        )
    return feasibility_path_count > 0 and mode in {
        FEASIBILITY_BID_FULL_MILP,
        FEASIBILITY_BID_FIXED_ECONOMIC_BINARY,
    }


def _fix_economic_scenario_binary_incumbent(root: ConcreteModel) -> int:
    fixed_count = 0
    for scenario_id in root.SCENARIO:
        block = root.scenario[scenario_id]
        for variable in block.component_data_objects(
            Var, active=True, descend_into=True
        ):
            if not variable.is_binary():
                continue
            incumbent = float(value(variable))
            rounded = float(round(incumbent))
            if abs(incumbent - rounded) > 1e-6:
                raise Phase6DError(
                    "Expected-cost incumbent contains a non-integral binary value."
                )
            variable.fix(rounded)
            fixed_count += 1
    return fixed_count


def _binary_fix_counts(model: ConcreteModel) -> tuple[int, int]:
    fixed = 0
    unfixed = 0
    for variable in model.component_data_objects(Var, active=True, descend_into=True):
        if not variable.is_binary():
            continue
        if variable.fixed:
            fixed += 1
        else:
            unfixed += 1
    return fixed, unfixed


def _seed_economic_incumbent_from_bid_plan(
    root: ConcreteModel,
    bid_plan: SteelBidPlan,
    *,
    scenario_ids: Sequence[str],
) -> dict[str, int]:
    """Seed shared bids and economic blocks from a proven parent-round plan."""

    if tuple(str(item) for item in bid_plan.input_scenario_ids) != tuple(
        str(item) for item in scenario_ids
    ):
        raise Phase6DError("Parent warm start has different economic scenario ids.")
    bid_values = {
        (int(row["market_interval_index"]), float(row["bid_price_eur_per_mwh"])): float(
            row["incremental_bid_volume_mwh"]
        )
        for row in bid_plan.bids
    }
    seeded_bid_count = 0
    for market_t in root.MARKET_TIME:
        for bid_price in STEEL_BID_GRID:
            key = (int(market_t), float(bid_price))
            if key not in bid_values:
                raise Phase6DError("Parent warm start has incomplete bid support.")
            variable = root.bid_volume_mwh[market_t, bid_price]
            if not variable.fixed:
                variable.set_value(bid_values[key])
                seeded_bid_count += 1

    dispatch = {
        (str(row["scenario_id"]), int(row["physical_interval_index"])): row
        for row in bid_plan.scenario_dispatch
    }
    field_map = {
        "planned_net_grid_import_mwh": "net_grid_import_mwh",
        "planned_coke_inventory_t": "coke_inventory",
        "planned_sinter_inventory_t": "sinter_inventory",
        "planned_hot_iron_inventory_t": "hot_iron_inventory",
        "planned_cold_slab_inventory_t": "cold_slab_inventory",
        "planned_dri_inventory_t": "dri_inventory",
        "planned_drp_pellet_input_t": "drp_pellet_input",
        "planned_drp_on": "drp_on",
        "planned_coking_plant_1_t": "coking_plant_1",
        "planned_sintering_plant_t": "sintering_plant",
        "planned_blast_furnace_6_t": "blast_furnace_6",
        "planned_basic_oxygen_furnace_t": "basic_oxygen_furnace",
        "planned_hot_strip_mill_t": "hot_strip_mill",
        "planned_coking_plant_1_on": "coking_plant_1_on",
        "planned_sintering_plant_on": "sintering_plant_on",
        "planned_blast_furnace_6_on": "blast_furnace_6_on",
        "planned_basic_oxygen_furnace_on": "basic_oxygen_furnace_on",
        "planned_hot_strip_mill_on": "hot_strip_mill_on",
        "planned_vn25_electricity_mwh": "vn25_electricity_mwh",
        "planned_total_generator_electricity_mwh": "total_generator_electricity_mwh",
        "planned_total_named_ng_procurement_mwh": "total_named_ng_procurement_mwh",
        "eaf_heat_start": "eaf_heat_start",
    }
    seeded_component_count = 0
    for scenario_id in scenario_ids:
        block = root.scenario[str(scenario_id)]
        for q in block.TIME:
            row = dispatch.get((str(scenario_id), int(q)))
            if row is None:
                raise Phase6DError("Parent warm start has incomplete physical support.")
            for field, component_name in field_map.items():
                if field not in row or not hasattr(block, component_name):
                    continue
                data = getattr(block, component_name)[q]
                if data.is_variable_type() and not data.fixed:
                    data.set_value(float(row[field]))
                    seeded_component_count += 1

        commitment_sources = {
            "coking_plant_1_day_on": "planned_coking_plant_1_t",
            "sintering_plant_day_on": "planned_sintering_plant_t",
            "blast_furnace_6_day_on": "planned_blast_furnace_6_t",
            "basic_oxygen_furnace_day_on": "planned_basic_oxygen_furnace_t",
            "hot_strip_mill_day_on": "planned_hot_strip_mill_t",
            "drp_day_on": "planned_drp_pellet_input_t",
        }
        if hasattr(block, "COMMITMENT_DAY"):
            day_count = len(tuple(block.COMMITMENT_DAY))
            intervals = len(tuple(block.TIME))
            if day_count <= 0 or intervals % day_count:
                raise Phase6DError("Parent warm start cannot map commitment days.")
            intervals_per_day = intervals // day_count
            for component_name, field in commitment_sources.items():
                if not hasattr(block, component_name):
                    continue
                component = getattr(block, component_name)
                for day in block.COMMITMENT_DAY:
                    start = int(day) * intervals_per_day
                    end = start + intervals_per_day
                    active = any(
                        float(dispatch[(str(scenario_id), q)].get(field, 0.0)) > 1e-8
                        for q in range(start, end)
                    )
                    component[day].set_value(float(active))
                    seeded_component_count += 1
    return {
        "seeded_bid_variable_count": seeded_bid_count,
        "seeded_economic_component_count": seeded_component_count,
    }


def _apply_bid_acceptance_signature_symmetry_breaking(
    root: ConcreteModel,
    *,
    scenario_ids: Sequence[str],
    scenario_prices: Mapping[str, Sequence[float]],
    feasibility_masks: Mapping[str, Sequence[Sequence[bool]]],
) -> dict[str, int]:
    """Keep one bid step per identical modelled acceptance signature."""

    fixed_count = 0
    retained_count = 0
    signature_count = 0
    path_ids = tuple(sorted(feasibility_masks))
    for market_t in root.MARKET_TIME:
        groups: dict[tuple[bool, ...], list[float]] = {}
        for bid_index, bid_price in enumerate(STEEL_BID_GRID):
            signature = tuple(
                float(bid_price)
                >= float(scenario_prices[str(scenario_id)][int(market_t)])
                for scenario_id in scenario_ids
            ) + tuple(
                bool(feasibility_masks[path_id][int(market_t)][bid_index])
                for path_id in path_ids
            )
            groups.setdefault(signature, []).append(float(bid_price))
        signature_count += len(groups)
        for signature, prices in groups.items():
            retained_price = max(prices) if any(signature) else None
            for bid_price in prices:
                if retained_price is not None and bid_price == retained_price:
                    retained_count += 1
                    continue
                root.bid_volume_mwh[market_t, bid_price].fix(0.0)
                fixed_count += 1
    return {
        "fixed_bid_step_count": fixed_count,
        "retained_bid_step_count": retained_count,
        "distinct_acceptance_signature_count": signature_count,
    }


def solve_grouped_da_bid_plan(
    context: SteelPhysicalContext,
    configuration: str,
    price_bundle: SteelPriceInformationBundle,
    rolling_state: SteelRollingState,
    policy: str,
    *,
    actuals_oracle: SteelActualPriceBundle | None = None,
    audit_future_paths: bool = False,
    diagnostic_frozen_expected_cost_optimum_eur: float | None = None,
    feasibility_paths: Sequence[Mapping[str, Any]] = (),
    feasibility_progress_optimum_t: float | None = None,
    parent_round_warm_start_plan: SteelBidPlan | None = None,
    progress_callback: SolverProgressCallback | None = None,
) -> SteelBidPlan:
    """Solve DA bids on a market grid around one shared QH physical model."""

    tiebreak_mode = _planning_physical_tiebreak_mode(context)
    planning_solver_execution_mode = _planning_solver_execution_mode(context)
    feasibility_bid_selection_mode = _feasibility_bid_selection_mode(context)
    economic_mip_gap_limit = _phase6d_solver_settings(context)[
        "economic_mip_gap_limit"
    ]
    expected_cost_warmstart = bool(
        context.config.get("expected_cost_warmstart", True)
    )
    market_granularity = price_bundle.granularity
    if market_granularity != context.granularity:
        raise Phase6DError("Price and physical-context market identities differ.")
    if tuple(float(item) for item in STEEL_BID_GRID) != STEEL_BID_GRID:
        raise Phase6DError("Frozen bid grid changed.")
    scenario_prices, probabilities = _scenario_inputs(
        policy, price_bundle, actuals_oracle
    )
    split_horizon, market_intervals, economic_physical_intervals = (
        _split_horizon_support(context, price_bundle)
    )
    validated_feasibility_paths = tuple(
        validate_feasibility_clearing_pattern(
            pattern,
            market_granularity=market_granularity,
            market_intervals=market_intervals,
            bid_grid_id=context.grid_id,
        )
        for pattern in feasibility_paths
    )
    if validated_feasibility_paths:
        if _policy_role(policy) != "H-S10" or len(scenario_prices) != 10:
            raise Phase6DError(
                "Feasibility-only augmentation is restricted to the frozen S10 plan."
            )
        if feasibility_progress_optimum_t is None or not math.isfinite(
            float(feasibility_progress_optimum_t)
        ):
            raise Phase6DError(
                "Augmented feasibility paths require the frozen production-progress optimum."
            )
        if len({str(item["path_id"]) for item in validated_feasibility_paths}) != len(
            validated_feasibility_paths
        ):
            raise Phase6DError("Augmented feasibility path ids must be unique.")
    group_size = _physical_group_size(market_granularity)
    physical_intervals = context.time_grid.horizon_steps
    base = _build_physical_model(
        context,
        configuration,
        rolling_state,
        terminal_day=False,
        planning_horizon_hours=context.time_grid.horizon_hours,
        terminal_hour_in_horizon=None,
    )
    if len(tuple(base.TIME)) != physical_intervals:
        raise Phase6DError("Physical EAF horizon differs from expanded market support.")
    base_model_stats = collect_model_stats(base)

    root = ConcreteModel()
    scenario_ids = tuple(sorted(scenario_prices))
    root.SCENARIO = Set(initialize=scenario_ids, ordered=True)
    root.MARKET_TIME = Set(
        initialize=tuple(range(market_intervals)), ordered=True
    )
    root.BID = Set(initialize=STEEL_BID_GRID, ordered=True)
    root.bid_volume_mwh = Var(
        root.MARKET_TIME, root.BID, domain=NonNegativeReals
    )
    root.scenario = Block(root.SCENARIO)
    for scenario_id in scenario_ids:
        root.scenario[scenario_id].transfer_attributes_from(base.clone())
    feasibility_masks: dict[str, tuple[tuple[bool, ...], ...]] = {}
    if validated_feasibility_paths:
        path_ids = tuple(str(item["path_id"]) for item in validated_feasibility_paths)
        feasibility_masks = {
            str(item["path_id"]): tuple(
                tuple(bool(value_) for value_ in row)
                for row in item["acceptance_mask_by_lead_position"]
            )
            for item in validated_feasibility_paths
        }
        root.FEASIBILITY_PATH = Set(initialize=path_ids, ordered=True)
        root.feasibility_path = Block(root.FEASIBILITY_PATH)
        for path_id in path_ids:
            root.feasibility_path[path_id].transfer_attributes_from(base.clone())
        root.feasibility_path_clearing = Constraint(
            root.FEASIBILITY_PATH,
            root.MARKET_TIME,
            rule=lambda m, path_id, market_t: sum(
                m.feasibility_path[path_id].net_grid_import_mwh[q]
                for q in range(
                    int(market_t) * group_size,
                    (int(market_t) + 1) * group_size,
                )
            )
            == sum(
                m.bid_volume_mwh[market_t, bid_price]
                for bid_index, bid_price in enumerate(STEEL_BID_GRID)
                if feasibility_masks[str(path_id)][int(market_t)][bid_index]
            ),
        )
        root.feasibility_path_progress_preservation = Constraint(
            root.FEASIBILITY_PATH,
            rule=lambda m, path_id: m.feasibility_path[
                path_id
            ].rolling_production_progress_deviation_t
            <= float(feasibility_progress_optimum_t) + 1e-6,
        )
    bid_signature_symmetry_breaking_active = bool(
        context.config.get("bid_signature_symmetry_breaking", False)
    )
    bid_signature_symmetry_breaking = {
        "fixed_bid_step_count": 0,
        "retained_bid_step_count": len(tuple(root.MARKET_TIME))
        * len(STEEL_BID_GRID),
        "distinct_acceptance_signature_count": 0,
    }
    if bid_signature_symmetry_breaking_active:
        bid_signature_symmetry_breaking = (
            _apply_bid_acceptance_signature_symmetry_breaking(
                root,
                scenario_ids=scenario_ids,
                scenario_prices=scenario_prices,
                feasibility_masks=feasibility_masks,
            )
        )
    if _policy_role(policy) == "price-insensitive":
        for market_t in root.MARKET_TIME:
            for bid_price in root.BID:
                if float(bid_price) != max(STEEL_BID_GRID):
                    root.bid_volume_mwh[market_t, bid_price].fix(0.0)
    root.market_clearing = Constraint(
        root.SCENARIO,
        root.MARKET_TIME,
        rule=lambda m, scenario_id, market_t: sum(
            m.scenario[scenario_id].net_grid_import_mwh[q]
            for q in range(
                int(market_t) * group_size,
                (int(market_t) + 1) * group_size,
            )
        )
        == sum(
            m.bid_volume_mwh[market_t, bid_price]
            for bid_price in m.BID
            if float(bid_price)
            >= float(scenario_prices[str(scenario_id)][int(market_t)])
        ),
    )
    progress_expr = sum(
        float(probabilities[str(scenario_id)])
        * root.scenario[scenario_id].rolling_production_progress_deviation_t
        for scenario_id in root.SCENARIO
    )
    expanded_prices = {}
    for scenario_id in scenario_ids:
        expanded = _expand_market_values(
            scenario_prices[scenario_id], market_granularity
        )
        if len(expanded) != economic_physical_intervals:
            raise Phase6DError("Scenario price support differs from the causal economic day.")
        expanded_prices[scenario_id] = expanded + tuple(
            0.0 for _ in range(physical_intervals - economic_physical_intervals)
        )
    objective_intervals = (
        tuple(range(context.time_grid.execution_steps))
        if split_horizon or _policy_role(policy) == "true-PF"
        else None
    )
    cost_expr = sum(
        float(probabilities[str(scenario_id)])
        * _represented_cost_expression(
            context,
            root.scenario[scenario_id],
            configuration,
            expanded_prices[scenario_id],
            objective_hours=objective_intervals,
        )
        for scenario_id in root.SCENARIO
    )
    tie_expr = sum(
        float(probabilities[str(scenario_id)])
        * _planning_tiebreak_expression(
            root.scenario[scenario_id],
            tiebreak_mode,
            context.time_grid.execution_steps,
        )
        for scenario_id in root.SCENARIO
    )
    canonical_eaf_expr = (
        sum(
            float(probabilities[str(scenario_id)])
            * _canonical_eaf_start_expression(root.scenario[scenario_id])
            for scenario_id in root.SCENARIO
        )
        if _policy_role(policy) == "price-insensitive"
        and configuration == C1_CONFIGURATION
        else None
    )
    canonical_physical_expr = (
        sum(
            float(probabilities[str(scenario_id)])
            * _canonical_physical_path_expression(root.scenario[scenario_id])
            for scenario_id in root.SCENARIO
        )
        if _policy_role(policy) == "price-insensitive"
        else None
    )
    tiers: list[dict[str, Any]] = []
    parent_round_bridge_performed = False
    parent_round_bridge_fixed_binary_count = 0
    parent_round_bridge_cost_eur: float | None = None
    parent_round_bridge_seed_stats = {
        "seeded_bid_variable_count": 0,
        "seeded_economic_component_count": 0,
    }
    root.progress_objective = Objective(expr=progress_expr, sense=minimize)
    native_multiobjective_total_wall_seconds: float | None = None
    native_two_objective_active = (
        planning_solver_execution_mode == PLANNING_SOLVER_NATIVE_TWO_OBJECTIVE
        and tiebreak_mode == EXPECTED_COST_INCUMBENT
        and not validated_feasibility_paths
        and diagnostic_frozen_expected_cost_optimum_eur is None
        and canonical_eaf_expr is None
        and canonical_physical_expr is None
    )
    if native_two_objective_active:
        solver_name = "gurobi_persistent_native_two_objective"
        (
            final_result,
            tiers,
            progress_optimum,
            cost_optimum,
            native_multiobjective_total_wall_seconds,
        ) = _solve_native_gurobi_two_objective(
            context,
            root,
            progress_expr=progress_expr,
            cost_expr=cost_expr,
            progress_callback=progress_callback,
        )
        tie_optimum = float(value(tie_expr))
        expected_cost_optimality_proof = "native_gurobi_two_objective_current_solve"
        physical_tiebreak_solve_performed = False
        root.progress_objective.deactivate()
    elif tiebreak_mode == NATIVE_GUROBI_HIERARCHY:
        if canonical_eaf_expr is not None or canonical_physical_expr is not None:
            raise Phase6DError(
                "Native hierarchy is restricted to the stochastic V4 audit."
            )
        solver_name = "gurobi_persistent_native_multiobjective"
        (
            final_result,
            tiers,
            progress_optimum,
            cost_optimum,
            tie_optimum,
            native_multiobjective_total_wall_seconds,
        ) = _solve_native_gurobi_hierarchy(
            context,
            root,
            progress_expr=progress_expr,
            cost_expr=cost_expr,
            tie_expr=tie_expr,
        )
        expected_cost_optimality_proof = "current_solve"
        physical_tiebreak_solve_performed = True
        root.progress_objective.deactivate()
    else:
        solver_name, solver = _solver_for_phase6d(context)
        final_result, record = _solve_optimal(
            root,
            solver,
            "production_progress",
            warmstart=False,
            progress_callback=progress_callback,
        )
        tiers.append(record)
        progress_optimum = float(value(progress_expr))
        root.progress_preservation = Constraint(
            expr=progress_expr <= progress_optimum + 1e-6
        )
        root.progress_objective.deactivate()
        if diagnostic_frozen_expected_cost_optimum_eur is None:
            if parent_round_warm_start_plan is not None:
                if not validated_feasibility_paths:
                    raise Phase6DError(
                        "A parent-round bridge requires active feasibility paths."
                    )
                if context.config.get("parent_round_restricted_bridge_active") is not True:
                    raise Phase6DError(
                        "The parent-round bridge is not active in the frozen contract."
                    )
                parent_round_bridge_seed_stats = (
                    _seed_economic_incumbent_from_bid_plan(
                        root,
                        parent_round_warm_start_plan,
                        scenario_ids=scenario_ids,
                    )
                )
                bridge_fixed_variables = []
                for scenario_id in scenario_ids:
                    block = root.scenario[str(scenario_id)]
                    for variable in block.component_data_objects(
                        Var, active=True, descend_into=True
                    ):
                        if not variable.is_binary():
                            continue
                        if variable.value is None:
                            raise Phase6DError(
                                "Parent-round bridge has an uninitialised economic binary."
                            )
                        variable.fix(int(round(float(variable.value))))
                        bridge_fixed_variables.append(variable)
                parent_round_bridge_fixed_binary_count = len(
                    bridge_fixed_variables
                )
                root.parent_round_bridge_objective = Objective(
                    expr=cost_expr, sense=minimize
                )
                final_result, bridge_record = _solve_optimal(
                    root,
                    solver,
                    "parent_round_restricted_expected_cost_bridge",
                    warmstart=True,
                    economic_mip_gap_limit=economic_mip_gap_limit,
                    progress_callback=progress_callback,
                )
                parent_round_bridge_cost_eur = float(value(cost_expr))
                bridge_record.update(
                    {
                        "warm_start_only_not_accepted_as_final": True,
                        "fixed_economic_binary_count": (
                            parent_round_bridge_fixed_binary_count
                        ),
                        **parent_round_bridge_seed_stats,
                    }
                )
                tiers.append(bridge_record)
                root.parent_round_bridge_objective.deactivate()
                for variable in bridge_fixed_variables:
                    variable.unfix()
                parent_round_bridge_performed = True
            root.expected_cost_objective = Objective(expr=cost_expr, sense=minimize)
            final_result, record = _solve_optimal(
                root,
                solver,
                "expected_represented_cost",
                warmstart=expected_cost_warmstart,
                economic_mip_gap_limit=economic_mip_gap_limit,
                progress_callback=progress_callback,
            )
            expected_cost_optimality_proof = (
                "current_solve_epsilon_optimal"
                if record["optimality_class"] == "epsilon_optimal"
                else "current_solve"
            )
        else:
            if tiebreak_mode != EXPECTED_COST_INCUMBENT:
                raise Phase6DError(
                    "Frozen-cost diagnostic feasibility is restricted to V1."
                )
            root.diagnostic_frozen_expected_cost_bound = Constraint(
                expr=cost_expr
                <= float(diagnostic_frozen_expected_cost_optimum_eur)
                + context.cost_tolerance_eur
            )
            root.expected_cost_objective = Objective(expr=0.0, sense=minimize)
            final_result, record = _solve_optimal(
                root,
                solver,
                "diagnostic_frozen_expected_cost_feasibility",
                warmstart=expected_cost_warmstart,
                progress_callback=progress_callback,
            )
            frozen_cost_error = float(value(cost_expr)) - float(
                diagnostic_frozen_expected_cost_optimum_eur
            )
            if abs(frozen_cost_error) > context.cost_tolerance_eur + 1e-6:
                raise Phase6DError(
                    "Diagnostic incumbent does not reproduce the frozen cost optimum."
                )
            record.update(
                {
                    "frozen_expected_cost_optimum_eur": float(
                        diagnostic_frozen_expected_cost_optimum_eur
                    ),
                    "frozen_expected_cost_reproduction_error_eur": frozen_cost_error,
                    "frozen_expected_cost_reproduction_tolerance_eur": (
                        context.cost_tolerance_eur
                    ),
                    "optimality_proof_source": (
                        "frozen_parent_optimum_plus_current_feasibility_proof"
                    ),
                }
            )
            expected_cost_optimality_proof = (
                "frozen_parent_optimum_plus_current_feasibility_proof"
            )
        tiers.append(record)
        cost_optimum = float(value(cost_expr))
        root.expected_cost_objective.deactivate()
        physical_tiebreak_solve_performed = (
            _planning_physical_tiebreak_solve_required(tiebreak_mode)
        )
        if (
            physical_tiebreak_solve_performed
            or canonical_eaf_expr is not None
            or canonical_physical_expr is not None
        ):
            root.cost_preservation = Constraint(
                expr=cost_expr <= cost_optimum + context.cost_tolerance_eur
            )
        if physical_tiebreak_solve_performed:
            root.physical_tiebreak_objective = Objective(
                expr=tie_expr, sense=minimize
            )
            tier_name = {
                FULL_PHYSICAL_TIEBREAK: "physical_tiebreak",
                HANDOFF_STATE_TIEBREAK: "handoff_state_tiebreak",
                EXECUTION_WINDOW_TIEBREAK: "execution_window_tiebreak",
            }[tiebreak_mode]
            final_result, record = _solve_optimal(
                root,
                solver,
                tier_name,
                warmstart=True,
                progress_callback=progress_callback,
            )
            tiers.append(record)
            tie_optimum = float(value(tie_expr))
            root.tie_preservation = Constraint(
                expr=tie_expr <= tie_optimum + 1e-6
            )
            root.physical_tiebreak_objective.deactivate()
        else:
            tie_optimum = float(value(tie_expr))
    if canonical_eaf_expr is not None and tiebreak_mode != NATIVE_GUROBI_HIERARCHY:
        root.canonical_eaf_objective = Objective(
            expr=canonical_eaf_expr, sense=minimize
        )
        final_result, record = _solve_optimal(
            root,
            solver,
            "canonical_eaf_heat_timing",
            warmstart=True,
            progress_callback=progress_callback,
        )
        tiers.append(record)
        canonical_eaf_optimum = float(value(canonical_eaf_expr))
        root.canonical_eaf_preservation = Constraint(
            expr=canonical_eaf_expr <= canonical_eaf_optimum + 1e-6
        )
        root.canonical_eaf_objective.deactivate()
    if canonical_physical_expr is not None and tiebreak_mode != NATIVE_GUROBI_HIERARCHY:
        root.canonical_physical_path_objective = Objective(
            expr=canonical_physical_expr, sense=minimize
        )
        final_result, record = _solve_optimal(
            root,
            solver,
            "canonical_physical_path",
            warmstart=True,
            progress_callback=progress_callback,
        )
        tiers.append(record)
        canonical_physical_optimum = float(value(canonical_physical_expr))
        root.canonical_physical_path_preservation = Constraint(
            expr=canonical_physical_expr <= canonical_physical_optimum + 1e-8
        )
        root.canonical_physical_path_objective.deactivate()
    feasibility_canonical_bid_solve_performed = False
    feasibility_canonical_fixed_economic_binary_count = 0
    if _feasibility_bid_canonical_solve_required(
        feasibility_bid_selection_mode,
        feasibility_path_count=len(validated_feasibility_paths),
    ):
        if (
            feasibility_bid_selection_mode
            == FEASIBILITY_BID_FIXED_ECONOMIC_BINARY
        ):
            feasibility_canonical_fixed_economic_binary_count = (
                _fix_economic_scenario_binary_incumbent(root)
            )
        if not hasattr(root, "cost_preservation"):
            root.cost_preservation = Constraint(
                expr=cost_expr <= cost_optimum + context.cost_tolerance_eur
            )
        root.feasibility_canonical_bid_objective = Objective(
            expr=sum(
                (1.0 + 1e-6 * (len(STEEL_BID_GRID) - bid_index))
                * root.bid_volume_mwh[market_t, bid_price]
                for market_t in root.MARKET_TIME
                for bid_index, bid_price in enumerate(STEEL_BID_GRID)
            ),
            sense=minimize,
        )
        final_result, record = _solve_optimal(
            root,
            solver,
            "feasibility_aware_canonical_bid_curve",
            warmstart=True,
            progress_callback=progress_callback,
        )
        tiers.append(record)
        fixed_binary_count, unfixed_binary_count = _binary_fix_counts(root)
        record.update(
            {
                "fixed_binary_count_at_solve": fixed_binary_count,
                "unfixed_binary_count_at_solve": unfixed_binary_count,
                "canonical_bid_solve_class": (
                    "reduced_feasibility_mip"
                    if feasibility_bid_selection_mode
                    == FEASIBILITY_BID_FIXED_ECONOMIC_BINARY
                    else "full_mip"
                ),
            }
        )
        root.feasibility_canonical_bid_objective.deactivate()
        feasibility_canonical_bid_solve_performed = True
    execution_market_intervals = int(
        round(context.time_grid.execution_hours / price_bundle.time_step_hours)
    )
    uninitialized_unused_bid_count = 0
    maximum_bid_nonnegativity_violation_mwh = 0.0
    raw_bid_values: dict[tuple[int, float], float] = {}
    for market_t in root.MARKET_TIME:
        for bid_price in root.BID:
            raw = root.bid_volume_mwh[market_t, bid_price].value
            if raw is None:
                raw = 0.0
                uninitialized_unused_bid_count += 1
            raw_value = float(raw)
            maximum_bid_nonnegativity_violation_mwh = max(
                maximum_bid_nonnegativity_violation_mwh, max(0.0, -raw_value)
            )
            if raw_value < -ENERGY_TOLERANCE_MWH:
                raise Phase6DError("Retained incumbent contains a negative bid volume.")
            if raw_value < 0.0:
                raw_value = 0.0
            raw_bid_values[(int(market_t), float(bid_price))] = raw_value
    maximum_raw_bid_reconstruction_error = 0.0
    scenario_imports: dict[str, tuple[float, ...]] = {}
    for scenario_id in scenario_ids:
        block = root.scenario[scenario_id]
        imports: list[float] = []
        for market_t in range(market_intervals):
            physical_import = sum(
                _component_value(block, "net_grid_import_mwh", q)
                for q in range(
                    market_t * group_size,
                    (market_t + 1) * group_size,
                )
            )
            imports.append(physical_import)
            reconstructed = sum(
                raw_bid_values[(market_t, float(bid_price))]
                for bid_price in STEEL_BID_GRID
                if float(bid_price) >= float(scenario_prices[scenario_id][market_t])
            )
            maximum_raw_bid_reconstruction_error = max(
                maximum_raw_bid_reconstruction_error,
                abs(physical_import - reconstructed),
            )
        scenario_imports[str(scenario_id)] = tuple(imports)
    if maximum_raw_bid_reconstruction_error > ENERGY_TOLERANCE_MWH:
        raise Phase6DError("Retained incumbent bid curve does not reconstruct clearing.")
    feasibility_path_imports: dict[str, tuple[float, ...]] = {}
    maximum_raw_feasibility_path_reconstruction_error = 0.0
    for pattern in validated_feasibility_paths:
        path_id = str(pattern["path_id"])
        block = root.feasibility_path[path_id]
        imports = tuple(
            sum(
                _component_value(block, "net_grid_import_mwh", q)
                for q in range(
                    market_t * group_size,
                    (market_t + 1) * group_size,
                )
            )
            for market_t in range(market_intervals)
        )
        feasibility_path_imports[path_id] = imports
        for market_t, physical_import in enumerate(imports):
            reconstructed = sum(
                raw_bid_values[(market_t, float(bid_price))]
                for bid_index, bid_price in enumerate(STEEL_BID_GRID)
                if feasibility_masks[path_id][market_t][bid_index]
            )
            maximum_raw_feasibility_path_reconstruction_error = max(
                maximum_raw_feasibility_path_reconstruction_error,
                abs(physical_import - reconstructed),
            )
    if (
        maximum_raw_feasibility_path_reconstruction_error
        > ENERGY_TOLERANCE_MWH
    ):
        raise Phase6DError(
            "Shared bid variables do not reconstruct a feasibility path."
        )
    bid_values = (
        dict(raw_bid_values)
        if validated_feasibility_paths
        else canonical_bid_volumes_from_scenario_requirements(
            scenario_prices,
            scenario_imports,
        )
    )
    maximum_bid_reconstruction_error = 0.0
    for scenario_id in scenario_ids:
        for market_t, physical_import in enumerate(scenario_imports[scenario_id]):
            reconstructed = sum(
                bid_values[(market_t, float(bid_price))]
                for bid_price in STEEL_BID_GRID
                if float(bid_price) >= float(scenario_prices[scenario_id][market_t])
            )
            maximum_bid_reconstruction_error = max(
                maximum_bid_reconstruction_error,
                abs(physical_import - reconstructed),
            )
    if maximum_bid_reconstruction_error > ENERGY_TOLERANCE_MWH:
        raise Phase6DError("Canonical bid curve does not reconstruct scenario clearing.")
    maximum_feasibility_path_reconstruction_error = 0.0
    for pattern in validated_feasibility_paths:
        path_id = str(pattern["path_id"])
        for market_t, physical_import in enumerate(
            feasibility_path_imports[path_id]
        ):
            reconstructed = sum(
                bid_values[(market_t, float(bid_price))]
                for bid_index, bid_price in enumerate(STEEL_BID_GRID)
                if feasibility_masks[path_id][market_t][bid_index]
            )
            maximum_feasibility_path_reconstruction_error = max(
                maximum_feasibility_path_reconstruction_error,
                abs(physical_import - reconstructed),
            )
    if maximum_feasibility_path_reconstruction_error > ENERGY_TOLERANCE_MWH:
        raise Phase6DError("Output bid curve does not reconstruct a feasibility path.")
    bids: list[dict[str, Any]] = []
    for market_t in range(execution_market_intervals):
        timestamp = price_bundle.timestamps_utc[market_t]
        for bid_price in STEEL_BID_GRID:
            bids.append(
                {
                    "policy": policy,
                    "configuration_id": configuration,
                    "delivery_day": price_bundle.delivery_day.isoformat(),
                    "forecast_origin_utc": price_bundle.forecast_origin_utc.isoformat(),
                    "target_timestamp_utc": timestamp.isoformat(),
                    "market_interval_index": market_t,
                    "market_granularity": market_granularity,
                    "market_time_step_hours": price_bundle.time_step_hours,
                    "physical_time_step_hours": PHYSICAL_TIME_STEP_HOURS,
                    "bid_grid_id": context.grid_id,
                    "bid_grid_sha256": grid_sha256(),
                    "bid_price_eur_per_mwh": bid_price,
                    "incremental_bid_volume_mwh": bid_values[
                        (market_t, float(bid_price))
                    ],
                    "information_timing": (
                        "isolated_oracle"
                        if _policy_role(policy) == "true-PF"
                        else "forecast_origin_only"
                    ),
                }
            )

    scenario_dispatch: list[dict[str, Any]] = []
    dispatch_physical_intervals = (
        physical_intervals if audit_future_paths else context.time_grid.execution_steps
    )
    for scenario_id in scenario_ids:
        block = root.scenario[scenario_id]
        for q in range(dispatch_physical_intervals):
            market_t, within = divmod(q, group_size)
            in_economic_horizon = q < economic_physical_intervals
            target_timestamp = (
                _physical_timestamp(price_bundle.timestamps_utc[market_t], within)
                if in_economic_horizon
                else _physical_timestamp(price_bundle.timestamps_utc[0], q)
            )
            audit_state = (
                {
                    "planned_coke_inventory_t": _component_value(
                        block, "coke_inventory", q
                    ),
                    "planned_sinter_inventory_t": _component_value(
                        block, "sinter_inventory", q
                    ),
                    "planned_hot_iron_inventory_t": _component_value(
                        block, "hot_iron_inventory", q
                    ),
                    "planned_cold_slab_inventory_t": _component_value(
                        block, "cold_slab_inventory", q
                    ),
                    "planned_dri_inventory_t": _component_value(
                        block, "dri_inventory", q
                    ),
                    "planned_drp_pellet_input_t": _component_value(
                        block, "drp_pellet_input", q
                    ),
                    "planned_drp_on": _component_value(block, "drp_on", q),
                    "planned_coking_plant_1_t": _component_value(
                        block, "coking_plant_1", q
                    ),
                    "planned_sintering_plant_t": _component_value(
                        block, "sintering_plant", q
                    ),
                    "planned_blast_furnace_6_t": _component_value(
                        block, "blast_furnace_6", q
                    ),
                    "planned_basic_oxygen_furnace_t": _component_value(
                        block, "basic_oxygen_furnace", q
                    ),
                    "planned_hot_strip_mill_t": _component_value(
                        block, "hot_strip_mill", q
                    ),
                    "planned_coking_plant_1_on": _component_value(
                        block, "coking_plant_1_on", q
                    ),
                    "planned_sintering_plant_on": _component_value(
                        block, "sintering_plant_on", q
                    ),
                    "planned_blast_furnace_6_on": _component_value(
                        block, "blast_furnace_6_on", q
                    ),
                    "planned_basic_oxygen_furnace_on": _component_value(
                        block, "basic_oxygen_furnace_on", q
                    ),
                    "planned_hot_strip_mill_on": _component_value(
                        block, "hot_strip_mill_on", q
                    ),
                    "planned_vn25_electricity_mwh": _component_value(
                        block, "vn25_electricity_mwh", q
                    ),
                    "planned_total_generator_electricity_mwh": _component_value(
                        block, "total_generator_electricity_mwh", q
                    ),
                    "planned_total_named_ng_procurement_mwh": _component_value(
                        block, "total_named_ng_procurement_mwh", q
                    ),
                    "planned_eaf_liquid_steel_output_t": _component_value(
                        block, "eaf_liquid_steel_output", q
                    ),
                }
                if audit_future_paths
                else {}
            )
            scenario_dispatch.append(
                {
                    "policy": policy,
                    "configuration_id": configuration,
                    "scenario_id": scenario_id,
                    "scenario_probability": probabilities[scenario_id],
                    "physical_interval_index": q,
                    "market_interval_index": market_t if in_economic_horizon else None,
                    "market_granularity": market_granularity,
                    "target_timestamp_utc": target_timestamp.isoformat(),
                    "scenario_price_eur_per_mwh": (
                        scenario_prices[scenario_id][market_t]
                        if in_economic_horizon
                        else None
                    ),
                    "economic_horizon_active": in_economic_horizon,
                    "physical_feasibility_tail": not in_economic_horizon,
                    "planned_net_grid_import_mwh": _component_value(
                        block, "net_grid_import_mwh", q
                    ),
                    "planned_final_product_t": _component_value(
                        block, "final_product_output", q
                    ),
                    "eaf_heat_start": _component_value(
                        block, "eaf_heat_start", q
                    ),
                    "eaf_melt": _component_value(block, "eaf_melt", q),
                    "eaf_tap": _component_value(block, "eaf_tap", q),
                    **audit_state,
                }
            )
    stats = collect_model_stats(root)
    scenario_represented_costs = {
        str(scenario_id): float(
            value(
                _represented_cost_expression(
                    context,
                    root.scenario[scenario_id],
                    configuration,
                    expanded_prices[str(scenario_id)],
                    objective_hours=objective_intervals,
                )
            )
        )
        for scenario_id in scenario_ids
    }
    reconstructed_expected_cost = sum(
        float(probabilities[scenario_id]) * scenario_represented_costs[scenario_id]
        for scenario_id in scenario_ids
    )
    expected_cost_reconstruction_error = reconstructed_expected_cost - cost_optimum
    if abs(expected_cost_reconstruction_error) > context.cost_tolerance_eur + 1e-6:
        raise Phase6DError("Scenario-wise expected-cost reconstruction exceeds tolerance.")
    solver_settings = _phase6d_solver_settings(context)
    economic_tier_record = next(
        (
            row
            for row in reversed(tiers)
            if str(row.get("tier")) in ECONOMIC_MIP_COST_TIERS
        ),
        {},
    )
    solver_record = {
        "solver_name": solver_name,
        "solver_version": _gurobi_version(),
        "solver_status": str(final_result.solver.status),
        "termination_condition": str(final_result.solver.termination_condition),
        "mip_gap": _solver_gap(final_result),
        "economic_optimality_class": economic_tier_record.get(
            "optimality_class"
        ),
        "economic_epsilon_optimal_accepted": bool(
            economic_tier_record.get("epsilon_optimal_accepted", False)
        ),
        "economic_objective_lower_bound_eur": economic_tier_record.get(
            "objective_lower_bound_eur"
        ),
        "economic_objective_upper_bound_eur": economic_tier_record.get(
            "objective_upper_bound_eur"
        ),
        "economic_absolute_objective_band_eur": economic_tier_record.get(
            "absolute_objective_band_eur"
        ),
        "economic_certified_relative_gap": economic_tier_record.get(
            "certified_relative_gap"
        ),
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "scenario_count": len(scenario_ids),
        "planning_hours": context.time_grid.horizon_hours,
        "economic_horizon_hours": (
            context.economic_horizon_hours
            if split_horizon
            else context.time_grid.horizon_hours
        ),
        "physical_feasibility_tail_active": split_horizon,
        "physical_feasibility_tail_hours": (
            context.time_grid.horizon_hours - int(context.economic_horizon_hours)
            if split_horizon
            else 0
        ),
        "tail_market_binding": False if split_horizon else None,
        "tail_price_information": "none" if split_horizon else None,
        "tail_executed_or_settled": False if split_horizon else None,
        "bid_curve_source": (
            (
                "shared_model_bid_variables_with_feasibility_only_constraints_"
                "and_frozen_canonical_tiebreak"
                if feasibility_bid_selection_mode == FEASIBILITY_BID_FULL_MILP
                else (
                    "shared_model_bid_variables_with_fixed_economic_binary_"
                    "reduced_feasibility_canonicalisation"
                    if feasibility_bid_selection_mode
                    == FEASIBILITY_BID_FIXED_ECONOMIC_BINARY
                    else "shared_model_bid_variables_from_feasibility_aware_"
                    "expected_cost_incumbent_with_analytical_zero_fill"
                )
            )
            if validated_feasibility_paths
            else "analytical_frozen_minimum_volume_highest_willingness_price_"
            "canonicalisation_from_feasible_incumbent"
        ),
        "bid_curve_resolve_performed": feasibility_canonical_bid_solve_performed,
        "bid_curve_canonicalisation_performed": (
            not validated_feasibility_paths
            or feasibility_bid_selection_mode
            in {
                FEASIBILITY_BID_FULL_MILP,
                FEASIBILITY_BID_FIXED_ECONOMIC_BINARY,
            }
        ),
        "bid_curve_canonicalisation_requires_additional_solve": (
            feasibility_canonical_bid_solve_performed
        ),
        "bid_curve_canonical_tiebreak": (
            "minimum_total_volume_then_highest_willingness_price"
            if not validated_feasibility_paths
            or feasibility_bid_selection_mode
            in {
                FEASIBILITY_BID_FULL_MILP,
                FEASIBILITY_BID_FIXED_ECONOMIC_BINARY,
            }
            else None
        ),
        "feasibility_bid_selection_mode": feasibility_bid_selection_mode,
        "feasibility_canonical_fixed_economic_binary_count": (
            feasibility_canonical_fixed_economic_binary_count
        ),
        "feasibility_canonical_unfixed_binary_count": (
            _binary_fix_counts(root)[1]
            if feasibility_canonical_bid_solve_performed
            else None
        ),
        "feasibility_bid_incumbent_reconstruction_required": bool(
            validated_feasibility_paths
            and feasibility_bid_selection_mode
            == FEASIBILITY_BID_EXPECTED_COST_INCUMBENT
        ),
        "uninitialized_unused_bid_steps_set_to_zero": uninitialized_unused_bid_count,
        "maximum_bid_nonnegativity_violation_mwh": (
            maximum_bid_nonnegativity_violation_mwh
        ),
        "maximum_raw_incumbent_bid_clearing_reconstruction_error_mwh": (
            maximum_raw_bid_reconstruction_error
        ),
        "maximum_bid_clearing_reconstruction_error_mwh": (
            maximum_bid_reconstruction_error
        ),
        "feasibility_path_count": len(validated_feasibility_paths),
        "feasibility_path_ids_json": json.dumps(
            [str(item["path_id"]) for item in validated_feasibility_paths]
        ),
        "feasibility_path_probability_present": False,
        "feasibility_path_expected_cost_contribution_eur": 0.0,
        "feasibility_path_forecast_metric_eligible": False,
        "feasibility_path_shared_bid_variable_component": "bid_volume_mwh",
        "feasibility_path_zero_imbalance_identity": (
            "physical_net_import_mwh_equals_mask_cleared_shared_bid_volume_mwh"
        ),
        "parent_round_restricted_bridge_performed": parent_round_bridge_performed,
        "parent_round_bridge_final_result_eligible": False,
        "parent_round_bridge_fixed_economic_binary_count": (
            parent_round_bridge_fixed_binary_count
        ),
        "parent_round_bridge_cost_eur": parent_round_bridge_cost_eur,
        **{
            f"parent_round_bridge_{key}": value_
            for key, value_ in parent_round_bridge_seed_stats.items()
        },
        "feasibility_path_progress_optimum_t": (
            float(feasibility_progress_optimum_t)
            if validated_feasibility_paths
            else None
        ),
        "maximum_raw_feasibility_path_reconstruction_error_mwh": (
            maximum_raw_feasibility_path_reconstruction_error
        ),
        "maximum_feasibility_path_reconstruction_error_mwh": (
            maximum_feasibility_path_reconstruction_error
        ),
        "feasibility_path_variable_growth": (
            len(validated_feasibility_paths) * base_model_stats.variables
        ),
        "feasibility_path_binary_growth": (
            len(validated_feasibility_paths) * base_model_stats.binaries
        ),
        "feasibility_path_constraint_growth": (
            len(validated_feasibility_paths)
            * (base_model_stats.constraints + market_intervals + 1)
            + (1 if validated_feasibility_paths else 0)
        ),
        "market_intervals": market_intervals,
        "economic_physical_intervals": economic_physical_intervals,
        "physical_intervals": physical_intervals,
        "market_time_step_hours": price_bundle.time_step_hours,
        "physical_time_step_hours": PHYSICAL_TIME_STEP_HOURS,
        "market_granularity": market_granularity,
        "scenario_ids_json": json.dumps(scenario_ids),
        "scenario_probability_sum": sum(probabilities.values()),
        "bid_signature_symmetry_breaking_active": (
            bid_signature_symmetry_breaking_active
        ),
        "bid_signature_symmetry_breaking": bid_signature_symmetry_breaking,
        "scenario_probabilities_json": json.dumps(probabilities, sort_keys=True),
        "economic_s10_contract_sha256": _payload_sha256(
            {
                "scenario_ids": scenario_ids,
                "scenario_prices": scenario_prices,
                "scenario_probabilities": probabilities,
            }
        ),
        "scenario_represented_costs_json": json.dumps(
            scenario_represented_costs, sort_keys=True
        ),
        "planning_physical_tiebreak_mode": tiebreak_mode,
        "planning_solver_execution_mode": planning_solver_execution_mode,
        "native_two_objective_active": native_two_objective_active,
        "physical_tiebreak_solve_performed": physical_tiebreak_solve_performed,
        "production_progress_optimum_t": progress_optimum,
        "expected_cost_optimum_eur": cost_optimum,
        "expected_cost_optimality_proof": expected_cost_optimality_proof,
        "expected_cost_warm_start_requested": expected_cost_warmstart,
        "diagnostic_frozen_expected_cost_optimum_eur": (
            diagnostic_frozen_expected_cost_optimum_eur
        ),
        "selected_incumbent_expected_cost_eur": reconstructed_expected_cost,
        "selected_incumbent_physical_tiebreak_value": tie_optimum,
        "solver_seed": solver_settings["seed"],
        "solver_time_limit_seconds": solver_settings["time_limit_seconds"],
        "solver_mip_gap_limit": solver_settings["mip_gap_limit"],
        "solver_economic_mip_gap_limit": solver_settings[
            "economic_mip_gap_limit"
        ],
        "solver_integer_feasibility_tolerance": solver_settings[
            "integer_feasibility_tolerance"
        ],
        "gurobi_performance_options_json": json.dumps(
            solver_settings["gurobi_performance_options"], sort_keys=True
        ),
        "native_multiobjective_total_wall_seconds": (
            native_multiobjective_total_wall_seconds
        ),
        "expected_cost_reconstructed_eur": reconstructed_expected_cost,
        "expected_cost_reconstruction_error_eur": expected_cost_reconstruction_error,
        "expected_cost_reconstruction_tolerance_eur": context.cost_tolerance_eur,
        "tier_solves": tiers,
        "total_solver_seconds": sum(
            float(item["runtime_seconds"]) for item in tiers
        ),
        "persistent_solver_reuse": native_two_objective_active,
        "persistent_solver_reason": (
            "native_gurobi_two_objective_single_invocation"
            if native_two_objective_active
            else "not_enabled_for_cloned_scenario_blocks; incumbent warm starts retain exact model semantics"
        ),
    }
    return SteelBidPlan(
        policy=policy,
        configuration_id=configuration,
        delivery_day=price_bundle.delivery_day,
        bids=bids,
        scenario_dispatch=scenario_dispatch,
        solver=solver_record,
        expected_cost_eur=cost_optimum,
        input_scenario_ids=scenario_ids,
        input_probabilities=probabilities,
    )


def _route_progress(
    context: SteelPhysicalContext,
    model: ConcreteModel,
    configuration: str,
    q: int,
) -> dict[str, float]:
    if configuration == C0_CONFIGURATION:
        return {
            "C0_BOF_crude_steel_output_t": _component_value(
                model, "bof_crude_steel_output", q
            ),
            "C0_HSM_final_product_t": _component_value(
                model, "c0_hsm_final_product_output", q
            ),
            "C0_DSP_final_product_t": _component_value(
                model, "c0_dsp_final_product_output", q
            ),
        }
    return {
        "C1_BOF_liquid_steel_output_t_h": _component_value(
            model, "bof_crude_steel_output", q
        ),
        "C1_EAF_liquid_steel_output_t_h": _component_value(
            model, "eaf_liquid_steel_output", q
        ),
        "C1_HSM_final_product_output_t": (
            float(context.c1_reference_routing["hsm_final_t_per_t_slab"])
            * _component_value(model, "hot_strip_mill", q)
        ),
        "C1_DSP_final_product_output_t": _component_value(
            model, "dsp_final_product_output", q
        ),
        "C1_imported_slab_to_HSM_t_h": _component_value(
            model, "imported_slab_to_hsm", q
        ),
    }


def _reconstruct_cleared_da_settlement(clearing: SteelClearingResult) -> float:
    """Reconstruct DA settlement only from cleared energy and realised DA price."""

    return sum(
        float(row["cleared_energy_mwh"])
        * float(row["realised_price_eur_per_mwh"])
        for row in clearing.hourly
    )


def _reconstruct_imbalance_state(
    model: ConcreteModel,
    imbalance_volume_expr: Any,
    imbalance_penalty_expr: Any,
    cleared_energy_mwh: Sequence[float],
    group_size: int,
    penalty_eur_per_mwh: float,
) -> dict[str, Any]:
    """Independently reconstruct the recourse identities from solved variables."""

    upward_by_interval = [
        max(0.0, float(value(model.phase6d_imbalance_positive_mwh[market_t])))
        for market_t in model.PHASE6D_EXECUTION_MARKET
    ]
    downward_by_interval = [
        max(0.0, float(value(model.phase6d_imbalance_negative_mwh[market_t])))
        for market_t in model.PHASE6D_EXECUTION_MARKET
    ]
    absolute_by_interval = [
        upward + downward
        for upward, downward in zip(
            upward_by_interval, downward_by_interval, strict=True
        )
    ]
    upward = sum(upward_by_interval)
    downward = sum(downward_by_interval)
    reconstructed_absolute = upward + downward
    expression_absolute = float(value(imbalance_volume_expr))
    volume_error = expression_absolute - reconstructed_absolute
    identity_errors: list[float] = []
    for market_t, cleared in enumerate(cleared_energy_mwh):
        physical_import = sum(
            float(value(model.net_grid_import_mwh[q]))
            for q in range(market_t * group_size, (market_t + 1) * group_size)
        )
        identity_errors.append(
            physical_import
            - float(cleared)
            - upward_by_interval[market_t]
            + downward_by_interval[market_t]
        )
    maximum_identity_error = max((abs(item) for item in identity_errors), default=0.0)
    reconstructed_penalty = float(penalty_eur_per_mwh) * reconstructed_absolute
    expression_penalty = float(value(imbalance_penalty_expr))
    penalty_error = expression_penalty - reconstructed_penalty
    if (
        abs(volume_error) > IMBALANCE_ZERO_TOLERANCE_MWH
        or maximum_identity_error > ENERGY_TOLERANCE_MWH
        or abs(penalty_error) > MONEY_TOLERANCE_EUR
    ):
        error = Phase6DError("Conditional imbalance-gate reconstruction failed.")
        error.diagnostic = {
            "status": "imbalance_reconstruction_failure",
            "absolute_imbalance_expression_mwh": expression_absolute,
            "absolute_imbalance_reconstructed_mwh": reconstructed_absolute,
            "absolute_imbalance_reconstruction_error_mwh": volume_error,
            "maximum_cleared_physical_identity_error_mwh": maximum_identity_error,
            "penalty_expression_eur": expression_penalty,
            "penalty_reconstructed_eur": reconstructed_penalty,
            "penalty_reconstruction_error_eur": penalty_error,
        }
        raise error
    affected = [
        index
        for index, interval_volume in enumerate(absolute_by_interval)
        if interval_volume > IMBALANCE_ZERO_TOLERANCE_MWH
    ]
    net = upward - downward
    if upward > IMBALANCE_ZERO_TOLERANCE_MWH and downward <= IMBALANCE_ZERO_TOLERANCE_MWH:
        direction = "upward_consumption"
    elif downward > IMBALANCE_ZERO_TOLERANCE_MWH and upward <= IMBALANCE_ZERO_TOLERANCE_MWH:
        direction = "downward_consumption"
    elif reconstructed_absolute <= IMBALANCE_ZERO_TOLERANCE_MWH:
        direction = "none"
    else:
        direction = "mixed"
    return {
        "absolute_imbalance_mwh": reconstructed_absolute,
        "upward_consumption_imbalance_mwh": upward,
        "downward_consumption_imbalance_mwh": downward,
        "net_consumption_imbalance_mwh": net,
        "direction": direction,
        "affected_market_interval_count": len(affected),
        "affected_market_interval_indices": affected,
        "maximum_market_interval_imbalance_mwh": max(
            absolute_by_interval, default=0.0
        ),
        "imbalance_penalty_eur_per_mwh": float(penalty_eur_per_mwh),
        "imbalance_penalty_eur": reconstructed_penalty,
        "maximum_cleared_physical_identity_error_mwh": maximum_identity_error,
        "absolute_imbalance_reconstruction_error_mwh": volume_error,
        "penalty_reconstruction_error_eur": penalty_error,
    }


def _solve_conditional_minimum_imbalance_gate(
    model: ConcreteModel,
    solver: Any,
    *,
    cost_expr: Any,
    imbalance_volume_expr: Any,
    imbalance_penalty_expr: Any,
    imbalance_recourse_active: bool,
    imbalance_penalty_eur_per_mwh: float | None,
    cleared_energy_mwh: Sequence[float],
    group_size: int,
    cost_tolerance_eur: float,
    economic_mip_gap_limit: float,
    tiers: list[dict[str, Any]],
    progress_callback: SolverProgressCallback | None,
) -> tuple[Any, float, dict[str, Any]]:
    """Solve economics and diagnose minimum imbalance only when economics uses it."""

    model.phase6d_cost_objective = Objective(expr=cost_expr, sense=minimize)
    result, record = _solve_optimal(
        model,
        solver,
        "redispatch_represented_cost",
        warmstart=True,
        economic_mip_gap_limit=economic_mip_gap_limit,
        progress_callback=progress_callback,
    )
    tiers.append(record)
    first_cost_optimum = float(value(cost_expr))
    first_economic_imbalance = float(value(imbalance_volume_expr))
    gate = {
        "imbalance_zero_tolerance_mwh": IMBALANCE_ZERO_TOLERANCE_MWH,
        "economic_imbalance_before_gate_mwh": first_economic_imbalance,
        "conditional_minimum_imbalance_solve_performed": False,
        "hard_zero_economic_resolve_performed": False,
        "minimum_imbalance_mwh": 0.0,
        "status": (
            "exact_clearing_without_recourse"
            if not imbalance_recourse_active
            else "zero_imbalance_from_economic_solve"
        ),
    }
    cost_optimum = first_cost_optimum
    if imbalance_recourse_active:
        penalty = float(imbalance_penalty_eur_per_mwh)
        first_state = _reconstruct_imbalance_state(
            model,
            imbalance_volume_expr,
            imbalance_penalty_expr,
            cleared_energy_mwh,
            group_size,
            penalty,
        )
        gate["economic_imbalance_before_gate"] = first_state
        if first_economic_imbalance > IMBALANCE_ZERO_TOLERANCE_MWH:
            gate["conditional_minimum_imbalance_solve_performed"] = True
            model.phase6d_cost_objective.deactivate()
            model.phase6d_minimum_imbalance_objective = Objective(
                expr=imbalance_volume_expr, sense=minimize
            )
            try:
                result, record = _solve_optimal(
                    model,
                    solver,
                    "redispatch_minimum_absolute_imbalance",
                    warmstart=True,
                    progress_callback=progress_callback,
                )
            except Phase6DPerformanceIncomplete as exc:
                diagnostic = {
                    "status": "minimum_imbalance_optimality_unproven",
                    "economic_imbalance_before_gate": first_state,
                    "tier_solves": [*tiers, exc.diagnostic.get("tier", {})],
                    "economic_result_accepted": False,
                    "abc_comparison_eligible": False,
                }
                raise Phase6DPerformanceIncomplete(
                    "Minimum-imbalance solve did not prove optimality; gate failed closed.",
                    diagnostic=diagnostic,
                ) from exc
            except Phase6DError as exc:
                exc.diagnostic = {
                    "status": "minimum_imbalance_solve_failed",
                    "economic_imbalance_before_gate": first_state,
                    "tier_solves": [*tiers, getattr(exc, "diagnostic", {})],
                    "economic_result_accepted": False,
                    "abc_comparison_eligible": False,
                }
                raise
            tiers.append(record)
            minimum_state = _reconstruct_imbalance_state(
                model,
                imbalance_volume_expr,
                imbalance_penalty_expr,
                cleared_energy_mwh,
                group_size,
                penalty,
            )
            minimum_imbalance = float(minimum_state["absolute_imbalance_mwh"])
            gate["minimum_imbalance_mwh"] = minimum_imbalance
            gate["minimum_imbalance_state"] = minimum_state
            if minimum_imbalance > IMBALANCE_ZERO_TOLERANCE_MWH:
                diagnostic = {
                    "status": "emergency_recourse",
                    **minimum_state,
                    "economic_imbalance_before_gate": first_state,
                    "economic_result_accepted": False,
                    "abc_comparison_eligible": False,
                    "rolling_continuation_authorized": False,
                    "tier_solves": list(tiers),
                }
                raise Phase6DEmergencyRecourse(
                    "Minimum physically feasible imbalance remains positive; "
                    "redispatch is emergency recourse only.",
                    diagnostic,
                )
            for market_t in model.PHASE6D_EXECUTION_MARKET:
                model.phase6d_imbalance_positive_mwh[market_t].fix(0.0)
                model.phase6d_imbalance_negative_mwh[market_t].fix(0.0)
            model.phase6d_minimum_imbalance_objective.deactivate()
            model.phase6d_cost_objective.activate()
            result, record = _solve_optimal(
                model,
                solver,
                "redispatch_represented_cost_hard_zero_imbalance",
                warmstart=True,
                economic_mip_gap_limit=economic_mip_gap_limit,
                progress_callback=progress_callback,
            )
            tiers.append(record)
            gate["hard_zero_economic_resolve_performed"] = True
            gate["status"] = "zero_imbalance_enforced_after_minimum_diagnosis"
            cost_optimum = float(value(cost_expr))
        else:
            # Preserve numerical zero through the physical tie-break without
            # spending an extra minimum-imbalance solve.
            model.phase6d_zero_imbalance_preservation = Constraint(
                expr=imbalance_volume_expr <= IMBALANCE_ZERO_TOLERANCE_MWH
            )
    model.phase6d_cost_preservation = Constraint(
        expr=cost_expr <= cost_optimum + float(cost_tolerance_eur)
    )
    model.phase6d_cost_objective.deactivate()
    return result, cost_optimum, gate


def _solve_grouped_redispatch_model(
    context: SteelPhysicalContext,
    configuration: str,
    state: SteelRollingState,
    clearing: SteelClearingResult,
    future_point_prices: Sequence[float],
    *,
    oracle_execute_D_cost_only: bool,
    imbalance_penalty_eur_per_mwh: float | None = None,
    minimum_imbalance_only: bool = False,
    required_production_progress_optimum_t: float | None = None,
    progress_callback: SolverProgressCallback | None = None,
) -> tuple[ConcreteModel, dict[str, Any], float]:
    if imbalance_penalty_eur_per_mwh is not None and (
        not math.isfinite(float(imbalance_penalty_eur_per_mwh))
        or float(imbalance_penalty_eur_per_mwh)
        != DEFAULT_IMBALANCE_PENALTY_EUR_PER_MWH
    ):
        raise Phase6DError(
            "Execution recourse permits exactly one fixed imbalance penalty: "
            "EUR 5,000/MWh."
        )
    imbalance_recourse_active = imbalance_penalty_eur_per_mwh is not None
    group_size = _physical_group_size(context.granularity)
    physical_market_intervals = int(
        round(context.time_grid.horizon_hours / _market_step_hours(context.granularity))
    )
    split_horizon = bool(context.physical_feasibility_tail_active)
    expected_economic_market_intervals = int(
        round(
            float(
                context.economic_horizon_hours
                if split_horizon
                else context.time_grid.horizon_hours
            )
            / _market_step_hours(context.granularity)
        )
    )
    if split_horizon:
        if len(future_point_prices) != expected_economic_market_intervals:
            raise Phase6DError(
                "Split-horizon redispatch requires only the causal economic-day point path."
            )
    elif len(future_point_prices) < physical_market_intervals:
        raise Phase6DError("Future market-price path is shorter than the configured horizon.")
    model = _build_physical_model(
        context,
        configuration,
        state,
        terminal_day=False,
        planning_horizon_hours=context.time_grid.horizon_hours,
        terminal_hour_in_horizon=None,
    )
    cleared = [float(row["cleared_energy_mwh"]) for row in clearing.hourly]
    model.PHASE6D_EXECUTION_MARKET = Set(
        initialize=tuple(range(len(cleared))), ordered=True
    )
    if imbalance_recourse_active:
        model.phase6d_imbalance_positive_mwh = Var(
            model.PHASE6D_EXECUTION_MARKET, domain=NonNegativeReals
        )
        model.phase6d_imbalance_negative_mwh = Var(
            model.PHASE6D_EXECUTION_MARKET, domain=NonNegativeReals
        )
        model.phase6d_cleared_import = Constraint(
            model.PHASE6D_EXECUTION_MARKET,
            rule=lambda m, market_t: sum(
                m.net_grid_import_mwh[q]
                for q in range(
                    int(market_t) * group_size,
                    (int(market_t) + 1) * group_size,
                )
            )
            == cleared[int(market_t)]
            + m.phase6d_imbalance_positive_mwh[market_t]
            - m.phase6d_imbalance_negative_mwh[market_t],
        )
        imbalance_volume_expr = sum(
            model.phase6d_imbalance_positive_mwh[market_t]
            + model.phase6d_imbalance_negative_mwh[market_t]
            for market_t in model.PHASE6D_EXECUTION_MARKET
        )
    else:
        model.phase6d_cleared_import = Constraint(
            model.PHASE6D_EXECUTION_MARKET,
            rule=lambda m, market_t: sum(
                m.net_grid_import_mwh[q]
                for q in range(
                    int(market_t) * group_size,
                    (int(market_t) + 1) * group_size,
                )
            )
            == cleared[int(market_t)],
        )
        imbalance_volume_expr = 0.0
    expanded_prices = _expand_market_values(
        future_point_prices[:expected_economic_market_intervals], context.granularity
    )
    expanded_prices = expanded_prices + tuple(
        0.0 for _ in range(context.time_grid.horizon_steps - len(expanded_prices))
    )
    execution_physical_intervals = len(cleared) * group_size
    redispatch_prices = tuple(0.0 for _ in range(execution_physical_intervals)) + tuple(
        expanded_prices[execution_physical_intervals:]
    )
    progress_expr = model.rolling_production_progress_deviation_t
    represented_cost_expr = _represented_cost_expression(
        context,
        model,
        configuration,
        redispatch_prices,
        zero_electricity_hours=execution_physical_intervals,
        objective_hours=(
            tuple(range(execution_physical_intervals))
            if split_horizon or oracle_execute_D_cost_only
            else None
        ),
    )
    imbalance_penalty_expr = (
        float(imbalance_penalty_eur_per_mwh) * imbalance_volume_expr
        if imbalance_recourse_active
        else 0.0
    )
    cost_expr = represented_cost_expr + imbalance_penalty_expr
    tie_expr = model.static_price_naive_objective.expr
    canonical_eaf_expr = (
        _canonical_eaf_start_expression(model)
        if _policy_role(clearing.policy) == "price-insensitive"
        and configuration == C1_CONFIGURATION
        else None
    )
    canonical_physical_expr = (
        _canonical_physical_path_expression(model)
        if _policy_role(clearing.policy) == "price-insensitive"
        else None
    )
    solver_name, solver = _solver_for_phase6d(context)
    tiers: list[dict[str, Any]] = []
    if minimum_imbalance_only:
        if not imbalance_recourse_active:
            raise Phase6DError(
                "A minimum-imbalance diagnostic requires explicit recourse variables."
            )
        if required_production_progress_optimum_t is None or not math.isfinite(
            float(required_production_progress_optimum_t)
        ):
            raise Phase6DError(
                "A minimum-imbalance diagnostic requires frozen production progress."
            )
        model.phase6d_required_progress = Constraint(
            expr=progress_expr
            <= float(required_production_progress_optimum_t) + 1e-6
        )
        model.phase6d_minimum_imbalance_objective = Objective(
            expr=imbalance_volume_expr,
            sense=minimize,
        )
        result, record = _solve_optimal(
            model,
            solver,
            "feasibility_path_minimum_absolute_imbalance",
            warmstart=False,
            progress_callback=progress_callback,
        )
        tiers.append(record)
        minimum_state = _reconstruct_imbalance_state(
            model,
            imbalance_volume_expr,
            imbalance_penalty_expr,
            cleared,
            group_size,
            float(imbalance_penalty_eur_per_mwh),
        )
        stats = collect_model_stats(model)
        settings = _phase6d_solver_settings(context)
        return model, {
            "status": "minimum_imbalance_proven",
            "solver_name": solver_name,
            "solver_status": str(result.solver.status),
            "termination_condition": str(result.solver.termination_condition),
            "mip_gap": _solver_gap(result),
            "variable_count": stats.variables,
            "binary_count": stats.binaries,
            "constraint_count": stats.constraints,
            "solver_time_limit_seconds": settings["time_limit_seconds"],
            "solver_mip_gap_limit": settings["mip_gap_limit"],
            "solver_integer_feasibility_tolerance": settings[
                "integer_feasibility_tolerance"
            ],
            "production_progress_optimum_t": float(
                required_production_progress_optimum_t
            ),
            "minimum_imbalance_state": minimum_state,
            "tier_solves": tiers,
            "total_solver_seconds": sum(
                float(item["runtime_seconds"]) for item in tiers
            ),
            "economic_objective_solved": False,
            "settlement_eligible": False,
            "feasibility_only": True,
        }, float(minimum_state["absolute_imbalance_mwh"])
    model.phase6d_progress_objective = Objective(
        expr=progress_expr, sense=minimize
    )
    _, record = _solve_optimal(
        model,
        solver,
        "redispatch_production_progress",
        warmstart=False,
        progress_callback=progress_callback,
    )
    tiers.append(record)
    progress_optimum = float(value(progress_expr))
    model.phase6d_progress_preservation = Constraint(
        expr=progress_expr <= progress_optimum + 1e-6
    )
    model.phase6d_progress_objective.deactivate()
    result, cost_optimum, imbalance_gate = (
        _solve_conditional_minimum_imbalance_gate(
            model,
            solver,
            cost_expr=cost_expr,
            imbalance_volume_expr=imbalance_volume_expr,
            imbalance_penalty_expr=imbalance_penalty_expr,
            imbalance_recourse_active=imbalance_recourse_active,
            imbalance_penalty_eur_per_mwh=imbalance_penalty_eur_per_mwh,
            cleared_energy_mwh=cleared,
            group_size=group_size,
            cost_tolerance_eur=context.cost_tolerance_eur,
            economic_mip_gap_limit=_phase6d_solver_settings(context)[
                "economic_mip_gap_limit"
            ],
            tiers=tiers,
            progress_callback=progress_callback,
        )
    )
    model.phase6d_tie_objective = Objective(expr=tie_expr, sense=minimize)
    result, record = _solve_optimal(
        model,
        solver,
        REDISPATCH_PHYSICAL_TIEBREAK_TIER,
        warmstart=True,
        progress_callback=progress_callback,
    )
    tiers.append(record)
    tie_optimum = float(value(tie_expr))
    if canonical_eaf_expr is not None or canonical_physical_expr is not None:
        model.phase6d_tie_preservation = Constraint(
            expr=tie_expr <= tie_optimum + 1e-8
        )
        model.phase6d_tie_objective.deactivate()
    if canonical_eaf_expr is not None:
        model.phase6d_canonical_eaf_objective = Objective(
            expr=canonical_eaf_expr, sense=minimize
        )
        result, record = _solve_optimal(
            model,
            solver,
            "redispatch_canonical_eaf_heat_timing",
            warmstart=True,
            progress_callback=progress_callback,
        )
        tiers.append(record)
        canonical_eaf_optimum = float(value(canonical_eaf_expr))
        model.phase6d_canonical_eaf_preservation = Constraint(
            expr=canonical_eaf_expr <= canonical_eaf_optimum + 1e-6
        )
        model.phase6d_canonical_eaf_objective.deactivate()
    if canonical_physical_expr is not None:
        model.phase6d_canonical_physical_path_objective = Objective(
            expr=canonical_physical_expr, sense=minimize
        )
        result, record = _solve_optimal(
            model,
            solver,
            "redispatch_canonical_physical_path",
            warmstart=True,
            progress_callback=progress_callback,
        )
        tiers.append(record)
    if imbalance_recourse_active:
        final_imbalance_state = _reconstruct_imbalance_state(
            model,
            imbalance_volume_expr,
            imbalance_penalty_expr,
            cleared,
            group_size,
            float(imbalance_penalty_eur_per_mwh),
        )
        if (
            float(final_imbalance_state["absolute_imbalance_mwh"])
            > IMBALANCE_ZERO_TOLERANCE_MWH
        ):
            error = Phase6DError(
                "Final redispatch regained positive imbalance after the gate."
            )
            error.diagnostic = {
                "status": "final_imbalance_gate_failure",
                **final_imbalance_state,
                "tier_solves": list(tiers),
            }
            raise error
        imbalance_gate["final_imbalance_state"] = final_imbalance_state
        imbalance_gate["economic_result_accepted"] = True
        imbalance_gate["abc_comparison_eligible"] = True
    stats = collect_model_stats(model)
    solver_settings = _phase6d_solver_settings(context)
    economic_tier_record = next(
        (
            row
            for row in reversed(tiers)
            if str(row.get("tier")) in ECONOMIC_MIP_COST_TIERS
        ),
        {},
    )
    return model, {
        "solver_name": solver_name,
        "solver_version": _gurobi_version(),
        "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "mip_gap": _solver_gap(result),
        "economic_optimality_class": economic_tier_record.get(
            "optimality_class"
        ),
        "economic_epsilon_optimal_accepted": bool(
            economic_tier_record.get("epsilon_optimal_accepted", False)
        ),
        "economic_objective_lower_bound_eur": economic_tier_record.get(
            "objective_lower_bound_eur"
        ),
        "economic_objective_upper_bound_eur": economic_tier_record.get(
            "objective_upper_bound_eur"
        ),
        "economic_absolute_objective_band_eur": economic_tier_record.get(
            "absolute_objective_band_eur"
        ),
        "economic_certified_relative_gap": economic_tier_record.get(
            "certified_relative_gap"
        ),
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "market_intervals": len(cleared),
        "physical_market_intervals": physical_market_intervals,
        "economic_horizon_hours": (
            context.economic_horizon_hours
            if split_horizon
            else context.time_grid.horizon_hours
        ),
        "physical_feasibility_tail_active": split_horizon,
        "physical_feasibility_tail_hours": (
            context.time_grid.horizon_hours - int(context.economic_horizon_hours)
            if split_horizon
            else 0
        ),
        "tail_market_binding": False if split_horizon else None,
        "tail_price_information": "none" if split_horizon else None,
        "tail_executed_or_settled": False if split_horizon else None,
        "physical_intervals": len(tuple(model.TIME)),
        "market_time_step_hours": _market_step_hours(context.granularity),
        "physical_time_step_hours": PHYSICAL_TIME_STEP_HOURS,
        "market_granularity": context.granularity,
        "physical_tiebreak_solve_performed": True,
        "production_progress_optimum_t": progress_optimum,
        "represented_cost_optimum_eur": cost_optimum,
        "final_economic_objective_eur": float(value(cost_expr)),
        "economic_objective_preservation_error_eur": float(value(cost_expr))
        - cost_optimum,
        "economic_objective_includes_da_settlement": False,
        "da_settlement_accounting": "separate_on_cleared_e_program",
        "imbalance_penalty_term_count": 1 if imbalance_recourse_active else 0,
        "represented_cost_excluding_imbalance_penalty_eur": float(
            value(represented_cost_expr)
        ),
        "imbalance_recourse_active": imbalance_recourse_active,
        "imbalance_penalty_eur_per_mwh": (
            float(imbalance_penalty_eur_per_mwh)
            if imbalance_recourse_active
            else None
        ),
        "absolute_imbalance_mwh": float(value(imbalance_volume_expr)),
        "imbalance_penalty_eur": float(value(imbalance_penalty_expr)),
        "conditional_imbalance_gate": imbalance_gate,
        "imbalance_gate_status": imbalance_gate["status"],
        "imbalance_zero_tolerance_mwh": IMBALANCE_ZERO_TOLERANCE_MWH,
        "conditional_minimum_imbalance_solve_performed": imbalance_gate[
            "conditional_minimum_imbalance_solve_performed"
        ],
        "hard_zero_economic_resolve_performed": imbalance_gate[
            "hard_zero_economic_resolve_performed"
        ],
        "imbalance_semantics": (
            "physical_import_minus_da_cleared_e_program; artificial_symmetric_penalty"
            if imbalance_recourse_active
            else "exact_da_clearing_no_imbalance"
        ),
        "selected_incumbent_physical_tiebreak_value": tie_optimum,
        "solver_seed": solver_settings["seed"],
        "solver_time_limit_seconds": solver_settings["time_limit_seconds"],
        "solver_mip_gap_limit": solver_settings["mip_gap_limit"],
        "solver_economic_mip_gap_limit": solver_settings[
            "economic_mip_gap_limit"
        ],
        "solver_integer_feasibility_tolerance": solver_settings[
            "integer_feasibility_tolerance"
        ],
        "tier_solves": tiers,
        "total_solver_seconds": sum(
            float(item["runtime_seconds"]) for item in tiers
        ),
    }, cost_optimum


def diagnose_feasibility_path_minimum_imbalance(
    context: SteelPhysicalContext,
    configuration: str,
    clearing: SteelClearingResult,
    state: SteelRollingState,
    future_point_prices: Sequence[float],
    *,
    required_production_progress_optimum_t: float,
    progress_callback: SolverProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the one-tier, probability-free separation oracle for one path."""

    _, diagnostic, minimum_imbalance_mwh = _solve_grouped_redispatch_model(
        context,
        configuration,
        state,
        clearing,
        future_point_prices,
        oracle_execute_D_cost_only=False,
        imbalance_penalty_eur_per_mwh=DEFAULT_IMBALANCE_PENALTY_EUR_PER_MWH,
        minimum_imbalance_only=True,
        required_production_progress_optimum_t=(
            required_production_progress_optimum_t
        ),
        progress_callback=progress_callback,
    )
    return {
        **diagnostic,
        "minimum_imbalance_mwh": float(minimum_imbalance_mwh),
    }


def solve_grouped_actual_redispatch(
    context: SteelPhysicalContext,
    configuration: str,
    clearing: SteelClearingResult,
    rolling_state: SteelRollingState,
    point_prices: Sequence[float],
    *,
    oracle_execute_D_cost_only: bool = False,
    imbalance_penalty_eur_per_mwh: float | None = None,
    progress_callback: SolverProgressCallback | None = None,
) -> Phase6DRedispatchResult:
    model, solver_record, _ = _solve_grouped_redispatch_model(
        context,
        configuration,
        rolling_state,
        clearing,
        point_prices,
        oracle_execute_D_cost_only=oracle_execute_D_cost_only,
        imbalance_penalty_eur_per_mwh=imbalance_penalty_eur_per_mwh,
        progress_callback=progress_callback,
    )
    group_size = _physical_group_size(context.granularity)
    imbalance_recourse_active = imbalance_penalty_eur_per_mwh is not None

    def component_upper_bound(name: str, q: int) -> float | None:
        component = getattr(model, name, None)
        if component is None:
            return None
        upper = getattr(component[q], "ub", None)
        return None if upper is None else float(value(upper))

    physical_rows: list[dict[str, Any]] = []
    for market_t, clearing_row in enumerate(clearing.hourly):
        market_physical_import = 0.0
        imbalance_positive = (
            float(value(model.phase6d_imbalance_positive_mwh[market_t]))
            if imbalance_recourse_active
            else 0.0
        )
        imbalance_negative = (
            float(value(model.phase6d_imbalance_negative_mwh[market_t]))
            if imbalance_recourse_active
            else 0.0
        )
        for within in range(group_size):
            q = market_t * group_size + within
            net_import = _component_value(model, "net_grid_import_mwh", q)
            market_physical_import += net_import
            route_progress = _route_progress(context, model, configuration, q)
            physical_rows.append(
                {
                    "policy": clearing.policy,
                    "configuration_id": configuration,
                    "delivery_day": clearing.delivery_day.isoformat(),
                    "market_granularity": context.granularity,
                    "market_interval_index": market_t,
                    "physical_interval_index": q,
                    "target_timestamp_utc": _physical_timestamp(
                        pd.Timestamp(clearing_row["target_timestamp_utc"]), within
                    ).isoformat(),
                    "market_period_timestamp_utc": clearing_row[
                        "target_timestamp_utc"
                    ],
                    "market_time_step_hours": _market_step_hours(
                        context.granularity
                    ),
                    "physical_time_step_hours": PHYSICAL_TIME_STEP_HOURS,
                    "realised_price_eur_per_mwh": float(
                        clearing_row["realised_price_eur_per_mwh"]
                    ),
                    "market_period_cleared_energy_mwh": float(
                        clearing_row["cleared_energy_mwh"]
                    ),
                    "redispatched_net_grid_import_mwh": net_import,
                    "allocated_pay_as_cleared_settlement_eur": float(
                        clearing_row["settlement_cost_eur"]
                    )
                    / group_size,
                    "allocated_upward_consumption_imbalance_mwh": (
                        imbalance_positive / group_size
                    ),
                    "allocated_downward_consumption_imbalance_mwh": (
                        imbalance_negative / group_size
                    ),
                    "allocated_absolute_imbalance_mwh": (
                        imbalance_positive + imbalance_negative
                    )
                    / group_size,
                    "allocated_imbalance_penalty_eur": (
                        (imbalance_positive + imbalance_negative)
                        * float(imbalance_penalty_eur_per_mwh)
                        / group_size
                        if imbalance_recourse_active
                        else 0.0
                    ),
                    "final_product_output_t": _component_value(
                        model, "final_product_output", q
                    ),
                    "gross_electricity_mwh": _component_value(
                        model, "gross_electricity_mwh", q
                    ),
                    "total_internal_generation_mwh": _component_value(
                        model, "total_generator_electricity_mwh", q
                    ),
                    "gross_grid_export_mwh": _component_value(
                        model, "gross_grid_export_mwh", q
                    ),
                    "total_named_ng_procurement_mwh": _component_value(
                        model, "total_named_ng_procurement_mwh", q
                    ),
                    "site_background_electricity_mwh": _component_value(
                        model, "site_background_electricity_mwh", q
                    ),
                    "site_baseload_ng_mwh": _component_value(
                        model, "site_baseload_ng_mwh", q
                    ),
                    "residual_steam_15bar_demand_t": _component_value(
                        model, "residual_steam_15bar_demand_t", q
                    ),
                    "steam_15bar_demand_t": _component_value(
                        model, "steam_15bar_demand_t", q
                    ),
                    "steam_15bar_supply_t": _component_value(
                        model, "steam_15bar_supply_t", q
                    ),
                    "steam_15bar_spill_t": _component_value(
                        model, "steam_15bar_spill_t", q
                    ),
                    "steam_15bar_unserved_t": _component_value(
                        model, "steam_15bar_unserved_t", q
                    ),
                    "boiler_bfg_mwh": _component_value(
                        model, "bfg_to_boiler", q
                    ),
                    "boiler_cog_mwh": _component_value(
                        model, "cog_to_boiler", q
                    ),
                    "boiler_named_ng_mwh": _component_value(
                        model, "ng_to_boiler_mwh", q
                    ),
                    "gross_site_electricity_identity_residual_mwh": _component_value(
                        model, "gross_site_electricity_identity_residual_mwh", q
                    ),
                    "bfg_balance_residual_mwh": _component_value(
                        model, "bfg_balance_residual", q
                    ),
                    "cog_balance_residual_mwh": _component_value(
                        model, "cog_balance_residual", q
                    ),
                    "bofg_balance_residual_mwh": _component_value(
                        model, "bofg_balance_residual", q
                    ),
                    "c0_bof_material_balance_residual_t": _component_value(
                        model, "c0_bof_material_balance_residual", q
                    ),
                    "blast_furnace_6_t": _component_value(
                        model, "blast_furnace_6", q
                    ),
                    "blast_furnace_6_capacity_t": component_upper_bound(
                        "blast_furnace_6", q
                    ),
                    "basic_oxygen_furnace_t": _component_value(
                        model, "basic_oxygen_furnace", q
                    ),
                    "hot_strip_mill_t": _component_value(
                        model, "hot_strip_mill", q
                    ),
                    "dsp_final_product_output_t": _component_value(
                        model, "dsp_final_product_output", q
                    ),
                    "bof_crude_steel_output_t": _component_value(
                        model, "bof_crude_steel_output", q
                    ),
                    "bof_to_hsm_slab_t": _component_value(
                        model, "bof_to_hsm_slab", q
                    ),
                    "bof_to_dsp_liquid_steel_t": _component_value(
                        model, "bof_to_dsp_liquid_steel", q
                    ),
                    "eaf_to_hsm_slab_t": _component_value(
                        model, "eaf_to_hsm_slab", q
                    ),
                    "eaf_to_dsp_liquid_steel_t": _component_value(
                        model, "eaf_to_dsp_liquid_steel", q
                    ),
                    "cold_slab_draw_to_hsm_t": _component_value(
                        model, "cold_slab_draw_to_hsm", q
                    ),
                    "imported_slab_to_hsm_t": _component_value(
                        model, "imported_slab_to_hsm", q
                    ),
                    "vn25_wag_fuel_mwh": _component_value(
                        model, "vn25_wag_fuel_mwh", q
                    ),
                    "vn25_named_ng_mwh": _component_value(
                        model, "ng_to_vn25_mwh", q
                    ),
                    "vn25_total_fuel_mwh": _component_value(
                        model, "vn25_total_fuel_mwh", q
                    ),
                    "vn25_electricity_mwh": _component_value(
                        model, "vn25_electricity_mwh", q
                    ),
                    "vn25_electric_capacity_mw": float(
                        getattr(model, "vn25_electric_capacity_mw", 0.0)
                    ),
                    "ij01_wag_fuel_mwh": _component_value(
                        model, "ij01_wag_fuel_mwh", q
                    ),
                    "ij01_named_ng_mwh": _component_value(
                        model, "ng_to_ij01_mwh", q
                    ),
                    "ij01_total_fuel_mwh": _component_value(
                        model, "ij01_total_fuel_mwh", q
                    ),
                    "ij01_electricity_mwh": _component_value(
                        model, "ij01_electricity_mwh", q
                    ),
                    "bfg_flared_mwh": _component_value(model, "bfg_flared", q),
                    "cog_flared_mwh": _component_value(model, "cog_flared", q),
                    "bofg_flared_mwh": _component_value(model, "bofg_flared", q),
                    "wag_flared_mwh": _component_value(model, "wag_flared", q),
                    "wag_generated_mwh": _component_value(model, "wag_generated", q),
                    "wag_used_mwh": _component_value(model, "wag_used", q),
                    "coke_inventory_t": _component_value(
                        model, "coke_inventory", q
                    ),
                    "sinter_inventory_t": _component_value(
                        model, "sinter_inventory", q
                    ),
                    "hot_iron_inventory_t": _component_value(
                        model, "hot_iron_inventory", q
                    ),
                    "cold_slab_inventory_t": _component_value(
                        model, "cold_slab_inventory", q
                    ),
                    "dri_inventory_t": _component_value(
                        model, "dri_inventory", q
                    ),
                    "drp_pellet_input_t": _component_value(
                        model, "drp_pellet_input", q
                    ),
                    "drp_electricity_mwh": _component_value(
                        model, "drp_electricity_mwh", q
                    ),
                    "drp_named_ng_mwh": _component_value(
                        model, "drp_named_ng_mwh", q
                    ),
                    "drp_on": _component_value(model, "drp_on", q),
                    "c1_kgf1_on": _component_value(
                        model, "coking_plant_1_on", q
                    ),
                    "c1_sinter_on": _component_value(
                        model, "sintering_plant_on", q
                    ),
                    "c1_bf6_on": _component_value(
                        model, "blast_furnace_6_on", q
                    ),
                    "eaf_heat_start": _component_value(
                        model, "eaf_heat_start", q
                    ),
                    "eaf_melt": _component_value(model, "eaf_melt", q),
                    "eaf_tap": _component_value(model, "eaf_tap", q),
                    "eaf_liquid_steel_output_t": _component_value(
                        model, "eaf_liquid_steel_output", q
                    ),
                    "eaf_arc_electricity_mwh": _component_value(
                        model, "eaf_arc_electricity_mwh", q
                    ),
                    "eaf_secondary_electricity_mwh": _component_value(
                        model, "eaf_secondary_electricity_mwh", q
                    ),
                    "eaf_total_electricity_mwh": _component_value(
                        model, "eaf_total_electricity_mwh", q
                    ),
                    "eaf_dri_input_t": _component_value(
                        model, "eaf_dri_input", q
                    ),
                    "eaf_scrap_input_t": _component_value(
                        model, "eaf_scrap_supply_t", q
                    ),
                    "eaf_named_ng_mwh": _component_value(
                        model, "eaf_named_ng_mwh", q
                    ),
                    "represented_oxygen_t": _component_value(
                        model, "represented_oxygen_t", q
                    ),
                    **route_progress,
                }
            )
        residual = market_physical_import - float(
            clearing_row["cleared_energy_mwh"]
        )
        recourse_identity_residual = residual - (
            imbalance_positive - imbalance_negative
        )
        if abs(recourse_identity_residual) > ENERGY_TOLERANCE_MWH:
            raise Phase6DError(
                "Grouped redispatch violates the cleared-energy plus imbalance identity: "
                f"{recourse_identity_residual} MWh."
            )
    if len(physical_rows) != context.time_grid.execution_steps:
        raise Phase6DError("Grouped execution differs from the configured physical horizon.")
    if max(abs(float(row["gross_grid_export_mwh"])) for row in physical_rows) > ENERGY_TOLERANCE_MWH:
        raise Phase6DError("Unexpected electricity export appeared in Phase-6D.")
    settlement_allocated = sum(
        float(row["allocated_pay_as_cleared_settlement_eur"])
        for row in physical_rows
    )
    if abs(settlement_allocated - clearing.settlement_cost_eur) > MONEY_TOLERANCE_EUR:
        raise Phase6DError("Physical settlement allocation is not exactly pay-as-cleared.")
    settlement_reconstructed = _reconstruct_cleared_da_settlement(clearing)
    if (
        abs(settlement_reconstructed - clearing.settlement_cost_eur)
        > MONEY_TOLERANCE_EUR
    ):
        raise Phase6DError(
            "Independent DA settlement reconstruction from the cleared E-program failed."
        )
    upward_imbalance = sum(
        float(row["allocated_upward_consumption_imbalance_mwh"])
        for row in physical_rows
    )
    downward_imbalance = sum(
        float(row["allocated_downward_consumption_imbalance_mwh"])
        for row in physical_rows
    )
    absolute_imbalance = upward_imbalance + downward_imbalance
    market_interval_imbalances = [
        float(value(model.phase6d_imbalance_positive_mwh[market_t]))
        + float(value(model.phase6d_imbalance_negative_mwh[market_t]))
        for market_t in model.PHASE6D_EXECUTION_MARKET
    ] if imbalance_recourse_active else [0.0 for _ in clearing.hourly]
    affected_market_intervals = sum(
        item > ENERGY_TOLERANCE_MWH for item in market_interval_imbalances
    )
    maximum_market_interval_imbalance = max(
        market_interval_imbalances, default=0.0
    )
    imbalance_penalty = sum(
        float(row["allocated_imbalance_penalty_eur"])
        for row in physical_rows
    )
    if abs(
        imbalance_penalty
        - absolute_imbalance * float(imbalance_penalty_eur_per_mwh or 0.0)
    ) > MONEY_TOLERANCE_EUR:
        raise Phase6DError("Imbalance penalty reconstruction failed.")
    other_represented_cost = _executed_non_grid_cost(
        context, model, configuration, context.time_grid.execution_steps
    )
    executed_economic_objective = other_represented_cost + imbalance_penalty
    objective_reconstruction_applicable = bool(
        solver_record["physical_feasibility_tail_active"]
        or oracle_execute_D_cost_only
    )
    objective_reconstruction_error = (
        float(solver_record["final_economic_objective_eur"])
        - executed_economic_objective
        if objective_reconstruction_applicable
        else None
    )
    if (
        objective_reconstruction_error is not None
        and abs(objective_reconstruction_error)
        > context.cost_tolerance_eur + MONEY_TOLERANCE_EUR
    ):
        error = Phase6DError(
            "Independent redispatch economic-objective reconstruction failed."
        )
        error.diagnostic = {
            "status": "economic_objective_reconstruction_failure",
            "solver_economic_objective_eur": solver_record[
                "final_economic_objective_eur"
            ],
            "executed_operational_cost_eur": other_represented_cost,
            "imbalance_penalty_eur": imbalance_penalty,
            "reconstruction_error_eur": objective_reconstruction_error,
        }
        raise error
    solver_record.update(
        {
            "imbalance_affected_market_interval_count": affected_market_intervals,
            "maximum_market_interval_imbalance_mwh": maximum_market_interval_imbalance,
            "da_settlement_reconstructed_eur": settlement_reconstructed,
            "da_settlement_reconstruction_error_eur": (
                settlement_reconstructed - clearing.settlement_cost_eur
            ),
            "executed_operational_cost_reconstructed_eur": other_represented_cost,
            "executed_economic_objective_reconstructed_eur": (
                executed_economic_objective
            ),
            "economic_objective_reconstruction_applicable": (
                objective_reconstruction_applicable
            ),
            "economic_objective_reconstruction_error_eur": (
                objective_reconstruction_error
            ),
            "penalty_counted_once_in_economic_objective": True,
        }
    )

    inventory_components = {
        "coke_inventory_t": "coke_inventory",
        "sinter_inventory_t": "sinter_inventory",
        "hot_iron_inventory_t": "hot_iron_inventory",
        "cold_slab_inventory_t": "cold_slab_inventory",
        "dri_inventory_t": "dri_inventory",
    }
    inventory_bound_violation = 0.0
    for component_name in inventory_components.values():
        component = getattr(model, component_name, None)
        if component is None:
            continue
        for q in model.TIME:
            item = component[q]
            observed = float(value(item))
            lower = getattr(item, "lb", None)
            upper = getattr(item, "ub", None)
            if lower is not None:
                inventory_bound_violation = max(
                    inventory_bound_violation, float(value(lower)) - observed
                )
            if upper is not None:
                inventory_bound_violation = max(
                    inventory_bound_violation, observed - float(value(upper))
                )
    terminal_q = context.time_grid.horizon_steps - 1
    terminal_observed = {
        state_id: _component_value(model, component_name, terminal_q)
        for state_id, component_name in inventory_components.items()
        if hasattr(model, component_name)
    }
    terminal_reference_distances: dict[str, float] = {}
    for state_id, bounds in context.terminal_inventory_band[configuration].items():
        observed = terminal_observed[state_id]
        terminal_reference_distances[state_id] = max(
            float(bounds["lower_t"]) - observed,
            observed - float(bounds["upper_t"]),
            0.0,
        )
    terminal_band_active = hasattr(model, "rolling_terminal_inventory_band")
    solver_record.update(
        {
            "inventory_bound_max_violation_t": max(inventory_bound_violation, 0.0),
            "terminal_inventory_observed_json": json.dumps(
                terminal_observed, sort_keys=True
            ),
            "terminal_inventory_reference_distance_json": json.dumps(
                terminal_reference_distances, sort_keys=True
            ),
            "terminal_inventory_reference_max_distance_t": max(
                terminal_reference_distances.values(), default=0.0
            ),
            "terminal_inventory_band_active": terminal_band_active,
            "terminal_condition_policy": (
                "active_rolling_terminal_inventory_band"
                if terminal_band_active
                else "non_terminal_rolling_day_no_terminal_band"
            ),
        }
    )

    last_q = context.time_grid.execution_steps - 1
    route_fields = tuple(_route_progress(context, model, configuration, 0))
    route_progress = {
        field: sum(float(row[field]) for row in physical_rows)
        for field in route_fields
    }
    next_inventory = _inventory_overrides(model, configuration, last_q)
    if configuration == C1_CONFIGURATION:
        start_lag1 = int(
            round(_component_value(model, "eaf_heat_start", last_q))
        )
        start_lag2 = int(
            round(_component_value(model, "eaf_heat_start", last_q - 1))
        )
        drp_last = _component_value(model, "drp_pellet_input", last_q)
    else:
        start_lag1 = start_lag2 = 0
        drp_last = None
    produced = sum(
        float(row["final_product_output_t"]) for row in physical_rows
    )
    next_state = SteelRollingState(
        episode_id=rolling_state.episode_id,
        configuration_id=configuration,
        inventory_overrides=next_inventory,
        cumulative_production_t=rolling_state.cumulative_production_t + produced,
        executed_hours=rolling_state.executed_hours + context.time_grid.execution_hours,
        executed_intervals=rolling_state.executed_intervals
        + context.time_grid.execution_steps,
        last_executed_timestamp_utc=physical_rows[-1]["target_timestamp_utc"],
        cumulative_route_progress_t={
            key: float(rolling_state.cumulative_route_progress_t.get(key, 0.0))
            + float(route_progress.get(key, 0.0))
            for key in set(rolling_state.cumulative_route_progress_t)
            | set(route_progress)
        },
        eaf_start_lag1=start_lag1,
        eaf_start_lag2=start_lag2,
        drp_last_pellet_input_t=drp_last,
    )
    return Phase6DRedispatchResult(
        policy=clearing.policy,
        configuration_id=configuration,
        market_granularity=context.granularity,
        delivery_day=clearing.delivery_day,
        physical_intervals=physical_rows,
        next_state=next_state,
        produced_t=produced,
        other_represented_cost_eur=other_represented_cost,
        imbalance_penalty_eur=imbalance_penalty,
        absolute_imbalance_mwh=absolute_imbalance,
        upward_consumption_imbalance_mwh=upward_imbalance,
        downward_consumption_imbalance_mwh=downward_imbalance,
        imbalance_affected_market_interval_count=affected_market_intervals,
        maximum_market_interval_imbalance_mwh=maximum_market_interval_imbalance,
        solver=solver_record,
        executed_route_progress_t=route_progress,
    )


def _price_inputs(
    phase: Mapping[str, Any],
    market_granularity: str,
    delivery_day: date,
) -> tuple[SteelPriceInformationBundle, SteelActualPriceBundle]:
    if market_granularity == "hourly":
        return (
            load_hourly_price_information(
                phase["forecast_root"], delivery_day, 10
            ),
            load_hourly_actual_prices(phase["forecast_root"], delivery_day),
        )
    return (
        load_qh_price_information(phase["forecast_root"], delivery_day, 10),
        load_qh_actual_prices(phase["forecast_root"], delivery_day),
    )


def run_phase6d_trajectory(
    config: Mapping[str, Any],
    *,
    market_granularity: str,
    configuration: str,
    policy: str,
) -> dict[str, Any]:
    context = _context_for_market(config, market_granularity)
    phase = config["phase6d"]
    delivery_day = date.fromisoformat(str(phase["delivery_date"]))
    price_bundle, actuals = _price_inputs(
        phase, market_granularity, delivery_day
    )
    if price_bundle.forecast_origin_utc != expected_origin_utc(delivery_day):
        raise Phase6DError("Forecast origin differs from D-1 08:00 Europe/Amsterdam.")
    oracle = (
        _load_oracle_prices(phase["forecast_root"], price_bundle)
        if _policy_role(policy) == "true-PF"
        else None
    )
    state = SteelRollingState(
        episode_id="phase6d_one_day", configuration_id=configuration
    )
    bid_plan = solve_grouped_da_bid_plan(
        context,
        configuration,
        price_bundle,
        state,
        policy,
        actuals_oracle=oracle,
        audit_future_paths=False,
    )
    clearing = clear_hourly_da_bids(bid_plan.bids, actuals)
    redispatch = solve_grouped_actual_redispatch(
        context,
        configuration,
        clearing,
        state,
        oracle.prices if oracle is not None else price_bundle.point_prices,
        oracle_execute_D_cost_only=_policy_role(policy) == "true-PF",
    )
    total_cost = (
        clearing.settlement_cost_eur + redispatch.other_represented_cost_eur
    )
    state_row = {
        "delivery_day": delivery_day.isoformat(),
        "market_granularity": market_granularity,
        "configuration_id": configuration,
        "policy": policy,
        "state_before_json": json.dumps(state.snapshot(), sort_keys=True),
        "state_after_json": json.dumps(
            redispatch.next_state.snapshot(), sort_keys=True
        ),
        "settlement_cost_eur": clearing.settlement_cost_eur,
        "other_represented_cost_eur": redispatch.other_represented_cost_eur,
        "total_realised_cost_eur": total_cost,
        "produced_t": redispatch.produced_t,
        "eaf_heat_count_started": sum(
            float(row["eaf_heat_start"])
            for row in redispatch.physical_intervals
        ),
        "eaf_heat_count_tapped": sum(
            float(row["eaf_tap"]) for row in redispatch.physical_intervals
        ),
        "eaf_arc_on_intervals": sum(
            float(row["eaf_melt"]) for row in redispatch.physical_intervals
        ),
        "eaf_unfinished_start_lag1": redispatch.next_state.eaf_start_lag1,
        "eaf_unfinished_start_lag2": redispatch.next_state.eaf_start_lag2,
    }
    return {
        "market_granularity": market_granularity,
        "configuration_id": configuration,
        "policy": policy,
        "bids": bid_plan.bids,
        "scenario_dispatch": bid_plan.scenario_dispatch,
        "clearing": clearing.hourly,
        "physical_dispatch": redispatch.physical_intervals,
        "state": state_row,
        "solver": [
            {"solve_role": "bidding", **bid_plan.solver},
            {"solve_role": "redispatch", **redispatch.solver},
        ],
        "final_state": redispatch.next_state.snapshot(),
        "total_realised_cost_eur": total_cost,
    }


def _trajectory_summary(trajectory: Mapping[str, Any]) -> dict[str, Any]:
    dispatch = trajectory["physical_dispatch"]
    state = trajectory["state"]
    solver = trajectory["solver"]
    cleared_mwh = sum(
        float(row["redispatched_net_grid_import_mwh"]) for row in dispatch
    )
    settlement = float(state["settlement_cost_eur"])
    arc = sum(float(row["eaf_arc_electricity_mwh"]) for row in dispatch)
    secondary = sum(
        float(row["eaf_secondary_electricity_mwh"]) for row in dispatch
    )
    taps = [
        row["target_timestamp_utc"]
        for row in dispatch
        if float(row["eaf_tap"]) > 0.5
    ]
    arc_mw = [
        float(row["eaf_arc_electricity_mwh"]) / PHYSICAL_TIME_STEP_HOURS
        for row in dispatch
    ]
    gaps = [
        float(row["mip_gap"])
        for row in solver
        if row.get("mip_gap") not in (None, "")
    ]
    return {
        "market_granularity": trajectory["market_granularity"],
        "configuration_id": trajectory["configuration_id"],
        "policy": trajectory["policy"],
        "represented_cost_eur": trajectory["total_realised_cost_eur"],
        "da_settlement_eur": settlement,
        "other_represented_procurement_eur": float(
            state["other_represented_cost_eur"]
        ),
        "produced_t": float(state["produced_t"]),
        "eaf_heat_count_started": float(state["eaf_heat_count_started"]),
        "eaf_heat_count_tapped": float(state["eaf_heat_count_tapped"]),
        "eaf_tap_timestamps_json": json.dumps(taps),
        "eaf_arc_mwh": arc,
        "eaf_secondary_mwh": secondary,
        "eaf_average_arc_mw": sum(arc_mw) / len(arc_mw) if arc_mw else 0.0,
        "eaf_max_arc_mw": max(arc_mw, default=0.0),
        "cleared_import_mwh": cleared_mwh,
        "volume_weighted_paid_price_eur_per_mwh": (
            settlement / cleared_mwh if cleared_mwh > ENERGY_TOLERANCE_MWH else math.nan
        ),
        "dri_buffer_end_t": float(dispatch[-1]["dri_inventory_t"]),
        "route_totals_json": json.dumps(
            {
                key: sum(float(row.get(key, 0.0)) for row in dispatch)
                for key in (
                    "C0_BOF_crude_steel_output_t",
                    "C0_HSM_final_product_t",
                    "C0_DSP_final_product_t",
                    "C1_BOF_liquid_steel_output_t_h",
                    "C1_EAF_liquid_steel_output_t_h",
                    "C1_HSM_final_product_output_t",
                    "C1_DSP_final_product_output_t",
                    "C1_imported_slab_to_HSM_t_h",
                )
                if key in dispatch[0]
            },
            sort_keys=True,
        ),
        "solver_seconds": sum(
            float(row["total_solver_seconds"]) for row in solver
        ),
        "max_variable_count": max(int(row["variable_count"]) for row in solver),
        "max_binary_count": max(int(row["binary_count"]) for row in solver),
        "max_constraint_count": max(
            int(row["constraint_count"]) for row in solver
        ),
        "max_mip_gap": max(gaps, default=0.0),
        "unfinished_heat_state_json": json.dumps(
            {
                "start_lag1": int(state["eaf_unfinished_start_lag1"]),
                "start_lag2": int(state["eaf_unfinished_start_lag2"]),
            },
            sort_keys=True,
        ),
    }


def validate_phase6d_trajectory(
    trajectory: Mapping[str, Any],
) -> list[dict[str, Any]]:
    dispatch = trajectory["physical_dispatch"]
    configuration = trajectory["configuration_id"]
    checks: list[dict[str, Any]] = []

    def add(check_id: str, passed: bool, observed: Any, expected: Any) -> None:
        checks.append(
            {
                "market_granularity": trajectory["market_granularity"],
                "configuration_id": configuration,
                "policy": trajectory["policy"],
                "check_id": check_id,
                "observed": observed,
                "expected": expected,
                "status": "pass" if passed else "fail",
            }
        )

    solver_optimal = all(
        str(row["termination_condition"]).lower() == "optimal"
        and all(
            str(tier["termination_condition"]).lower() == "optimal"
            for tier in row["tier_solves"]
        )
        for row in trajectory["solver"]
    )
    add("all_head_and_tier_solves_optimal", solver_optimal, solver_optimal, True)
    add(
        "physical_execution_interval_count",
        len(dispatch) == PHYSICAL_INTERVALS_PER_DAY,
        len(dispatch),
        PHYSICAL_INTERVALS_PER_DAY,
    )
    settlement_allocated = sum(
        float(row["allocated_pay_as_cleared_settlement_eur"])
        for row in dispatch
    )
    settlement = float(trajectory["state"]["settlement_cost_eur"])
    add(
        "pay_as_cleared_settlement_identity",
        abs(settlement_allocated - settlement) <= MONEY_TOLERANCE_EUR,
        settlement_allocated - settlement,
        0.0,
    )
    market_recourse_residuals: list[float] = []
    for market_t in sorted(
        {int(row["market_interval_index"]) for row in dispatch}
    ):
        selected = [
            row
            for row in dispatch
            if int(row["market_interval_index"]) == market_t
        ]
        physical_import = sum(
            float(row["redispatched_net_grid_import_mwh"]) for row in selected
        )
        cleared_import = float(selected[0]["market_period_cleared_energy_mwh"])
        upward = sum(
            float(row["allocated_upward_consumption_imbalance_mwh"])
            for row in selected
        )
        downward = sum(
            float(row["allocated_downward_consumption_imbalance_mwh"])
            for row in selected
        )
        market_recourse_residuals.append(
            physical_import - cleared_import - upward + downward
        )
    maximum_recourse_residual = max(
        (abs(item) for item in market_recourse_residuals), default=0.0
    )
    add(
        "cleared_e_program_plus_imbalance_identity",
        maximum_recourse_residual <= ENERGY_TOLERANCE_MWH,
        maximum_recourse_residual,
        0.0,
    )
    absolute_imbalance = sum(
        float(row["allocated_absolute_imbalance_mwh"]) for row in dispatch
    )
    allocated_imbalance_penalty = sum(
        float(row["allocated_imbalance_penalty_eur"]) for row in dispatch
    )
    redispatch_solver = next(
        (
            row
            for row in trajectory["solver"]
            if "imbalance_recourse_active" in row
        ),
        {},
    )
    penalty_rate = float(
        redispatch_solver.get("imbalance_penalty_eur_per_mwh") or 0.0
    )
    penalty_error = allocated_imbalance_penalty - penalty_rate * absolute_imbalance
    add(
        "imbalance_penalty_identity",
        abs(penalty_error) <= MONEY_TOLERANCE_EUR,
        penalty_error,
        0.0,
    )
    add(
        "no_export",
        max(abs(float(row["gross_grid_export_mwh"])) for row in dispatch)
        <= ENERGY_TOLERANCE_MWH,
        max(abs(float(row["gross_grid_export_mwh"])) for row in dispatch),
        0.0,
    )
    if configuration == C1_CONFIGURATION:
        start_values = [float(row["eaf_heat_start"]) for row in dispatch]
        melt_values = [float(row["eaf_melt"]) for row in dispatch]
        tap_values = [float(row["eaf_tap"]) for row in dispatch]
        add(
            "eaf_start_binary_integrality",
            max(abs(item - round(item)) for item in start_values) <= 1e-7,
            max(abs(item - round(item)) for item in start_values),
            0.0,
        )
        add(
            "eaf_no_overlap",
            max(melt + tap for melt, tap in zip(melt_values, tap_values))
            <= 1.0 + 1e-7,
            max(melt + tap for melt, tap in zip(melt_values, tap_values)),
            1.0,
        )
        tap_output_residual = max(
            abs(float(row["eaf_liquid_steel_output_t"]) - 325.0 * float(row["eaf_tap"]))
            for row in dispatch
        )
        add(
            "eaf_325_t_per_tap",
            tap_output_residual <= MATERIAL_TOLERANCE_T,
            tap_output_residual,
            0.0,
        )
        arc_residual = max(
            abs(
                float(row["eaf_arc_electricity_mwh"])
                - 68.6111111075 * float(row["eaf_melt"])
            )
            for row in dispatch
        )
        add(
            "eaf_arc_energy_only_during_melt",
            arc_residual <= 1e-7,
            arc_residual,
            0.0,
        )
        secondary_residual = max(
            abs(
                float(row["eaf_secondary_electricity_mwh"])
                - 10.075 * float(row["eaf_tap"])
            )
            for row in dispatch
        )
        add(
            "eaf_secondary_energy_at_tap",
            secondary_residual <= 1e-7,
            secondary_residual,
            0.0,
        )
        drp = [float(row["drp_pellet_input_t"]) for row in dispatch]
        max_delta = max(
            abs(drp[index] - drp[index - 1])
            for index in range(1, len(drp))
        )
        # The active source input has 500 t pellets/h capacity and a 0.1-pu/h
        # ramp; on the QH interval-quantity basis this is
        # 500 * 0.1 * 0.25^2 = 3.125 t per adjacent interval.
        ramp_bound = 3.125
        add(
            "drp_scaled_ramp_active",
            max_delta <= ramp_bound + MATERIAL_TOLERANCE_T,
            max_delta,
            ramp_bound,
        )
        total_arc = sum(
            float(row["eaf_arc_electricity_mwh"]) for row in dispatch
        )
        total_melt = sum(melt_values)
        add(
            "eaf_arc_total_from_melt_intervals",
            abs(total_arc - 68.6111111075 * total_melt) <= 1e-6,
            total_arc - 68.6111111075 * total_melt,
            0.0,
        )
    return checks


def validate_flat_price_physics_identity(
    trajectories: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected = {
        trajectory["market_granularity"]: trajectory
        for trajectory in trajectories
        if trajectory["configuration_id"] == C1_CONFIGURATION
        and trajectory["policy"] == "price-insensitive"
    }
    if set(selected) != {"hourly", "quarterhour"}:
        return {
            "check_id": "flat_price_shared_eaf_physics",
            "status": "fail",
            "observed": sorted(selected),
            "expected": ["hourly", "quarterhour"],
        }
    fields = (
        "eaf_heat_start",
        "eaf_melt",
        "eaf_tap",
        "eaf_arc_electricity_mwh",
        "eaf_liquid_steel_output_t",
    )
    maximum = max(
        abs(
            float(hourly[field]) - float(qh[field])
        )
        for hourly, qh in zip(
            selected["hourly"]["physical_dispatch"],
            selected["quarterhour"]["physical_dispatch"],
        )
        for field in fields
    )
    return {
        "check_id": "flat_price_shared_eaf_physics",
        "status": "pass" if maximum <= 1e-7 else "fail",
        "observed": maximum,
        "expected": 0.0,
    }


def _fingerprint(config_path: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    phase = config["phase6d"]
    forecast = _resolve(phase["forecast_root"]) / "optimisation_inputs"
    paths = [
        config_path,
        Path(__file__).resolve(),
        Path(__file__).with_name(
            "s4_4c6_phase6b_hourly_da_bid_clear_redispatch.py"
        ).resolve(),
        Path(__file__).with_name(
            "s4_4c_unified_physical_modelbuilder.py"
        ).resolve(),
        forecast / "hourly_point_forecasts.parquet",
        forecast / "hourly_scenarios_10.parquet",
        forecast / "quarterhour_point_forecasts.parquet",
        forecast / "quarterhour_scenarios_10.parquet",
        _resolve(phase["forecast_root"]) / "evaluation_actuals.parquet",
    ]
    payload = {
        "config_sha256": _sha256(config_path),
        "code_sha256": {
            str(path.relative_to(REPO_ROOT)): _sha256(path)
            for path in paths[1:4]
        },
        "forecast_sha256": {
            path.name: _sha256(path) for path in paths[4:]
        },
        "legacy_hourly_run_summary_sha256": _sha256(
            _resolve(phase["legacy_hourly_run_root"]) / "run_summary.json"
        ),
        "legacy_qh_run_summary_sha256": _sha256(
            _resolve(phase["legacy_qh_run_root"]) / "run_summary.json"
        ),
        "eaf_heat_state_sha256": hashlib.sha256(
            json.dumps(
                phase["eaf_heat_state"], sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        "git_head": _git_head(),
    }
    payload["run_fingerprint"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return payload


def _checkpoint_path(
    output_root: Path,
    market_granularity: str,
    configuration: str,
    policy: str,
) -> Path:
    short = "C0" if configuration == C0_CONFIGURATION else "C1"
    safe_policy = policy.lower().replace("-", "_")
    return (
        output_root
        / "checkpoints"
        / f"{market_granularity}_{short}_{safe_policy}.json.gz"
    )


def _load_or_run_trajectory(
    config: Mapping[str, Any],
    output_root: Path,
    fingerprint: Mapping[str, Any],
    *,
    market_granularity: str,
    configuration: str,
    policy: str,
) -> dict[str, Any]:
    path = _checkpoint_path(
        output_root, market_granularity, configuration, policy
    )
    if path.exists():
        import gzip

        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("run_fingerprint") != fingerprint["run_fingerprint"]:
            raise Phase6DError("Phase-6D checkpoint fingerprint mismatch.")
        return payload["trajectory"]
    trajectory = run_phase6d_trajectory(
        config,
        market_granularity=market_granularity,
        configuration=configuration,
        policy=policy,
    )
    _write_gzip_json_atomic(
        path,
        {
            "run_fingerprint": fingerprint["run_fingerprint"],
            "trajectory": trajectory,
        },
    )
    return trajectory


def _c0_regression_checkpoint_path(
    output_root: Path, market_granularity: str
) -> Path:
    return (
        output_root
        / "checkpoints"
        / f"{market_granularity}_C0_regression.json.gz"
    )


def _run_c0_regression(
    output_root: Path,
    fingerprint: Mapping[str, Any],
    *,
    market_granularity: str,
) -> dict[str, Any]:
    """Rerun the unchanged legacy C0 engine on its native market/physical grid."""

    path = _c0_regression_checkpoint_path(output_root, market_granularity)
    if path.exists():
        import gzip

        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("run_fingerprint") != fingerprint["run_fingerprint"]:
            raise Phase6DError("C0 regression checkpoint fingerprint mismatch.")
        return payload["trajectory"]
    if market_granularity == "hourly":
        config = load_phase6b_config(PHASE6B_CONFIG)
        policy = "H-point"
    else:
        config = load_phase6c_config(PHASE6C_CONFIG)
        policy = "QH-point"
    context = prepare_physical_context(config)
    trajectory = _policy_trajectory(
        context,
        config,
        fixture_id="normal_day",
        delivery_days=[EXPECTED_DELIVERY_DAY],
        policy=policy,
        configuration=C0_CONFIGURATION,
        audit_future_paths=False,
        apply_campaign_terminal=False,
    )
    _write_gzip_json_atomic(
        path,
        {
            "run_fingerprint": fingerprint["run_fingerprint"],
            "trajectory": trajectory,
        },
    )
    return trajectory


def _c0_regression_check(
    trajectory: Mapping[str, Any],
    phase: Mapping[str, Any],
    *,
    market_granularity: str,
) -> dict[str, Any]:
    policy = "H-point" if market_granularity == "hourly" else "QH-point"
    legacy = _legacy_day_summary(
        _resolve(
            phase[
                "legacy_hourly_run_root"
                if market_granularity == "hourly"
                else "legacy_qh_run_root"
            ]
        ),
        market_granularity=market_granularity,
        configuration=C0_CONFIGURATION,
        policy=policy,
    )
    state = trajectory["states"][0]
    cost = float(state["total_realised_cost_eur"])
    produced = float(state["produced_t"])
    cost_tolerance = max(
        0.01, 1e-6 * max(abs(legacy["represented_cost_eur"]), 1.0)
    )
    solver_optimal = all(
        str(row["termination_condition"]).lower() == "optimal"
        and all(
            str(tier["termination_condition"]).lower() == "optimal"
            for tier in row["tier_solves"]
        )
        for row in trajectory["solver"]
    )
    cost_error = cost - legacy["represented_cost_eur"]
    production_error = produced - legacy["produced_t"]
    return {
        "market_granularity": market_granularity,
        "configuration_id": C0_CONFIGURATION,
        "policy": policy,
        "check_id": "c0_native_grid_legacy_parity",
        "new_represented_cost_eur": cost,
        "legacy_represented_cost_eur": legacy["represented_cost_eur"],
        "represented_cost_error_eur": cost_error,
        "represented_cost_tolerance_eur": cost_tolerance,
        "new_produced_t": produced,
        "legacy_produced_t": legacy["produced_t"],
        "production_error_t": production_error,
        "solver_optimal": solver_optimal,
        "status": (
            "pass"
            if solver_optimal
            and abs(cost_error) <= cost_tolerance
            and abs(production_error) <= MATERIAL_TOLERANCE_T
            else "fail"
        ),
    }


def _legacy_day_summary(
    run_root: Path,
    *,
    market_granularity: str,
    configuration: str,
    policy: str,
) -> dict[str, float]:
    states = pd.read_csv(run_root / "rolling_state_handoffs.csv")
    if market_granularity == "hourly":
        case = states[
            (states["fixture_id"] == "normal_day")
            & (states["delivery_day"] == EXPECTED_DELIVERY_DAY.isoformat())
            & (states["configuration_id"] == configuration)
            & (states["policy"] == policy)
        ]
    else:
        case = states[
            (states["fixture_id"] == "rolling_week")
            & (states["delivery_day"] == EXPECTED_DELIVERY_DAY.isoformat())
            & (states["configuration_id"] == configuration)
            & (states["policy"] == policy)
        ]
    if len(case) != 1:
        raise Phase6DError(
            f"Legacy common-day state row unavailable: {market_granularity}/{configuration}/{policy}."
        )
    row = case.iloc[0]
    return {
        "represented_cost_eur": float(row["total_realised_cost_eur"]),
        "settlement_cost_eur": float(row["settlement_cost_eur"]),
        "other_represented_cost_eur": float(row["other_represented_cost_eur"]),
        "produced_t": float(row["produced_t"]),
    }


def _comparison_rows(
    summaries: Sequence[Mapping[str, Any]],
    phase: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary in summaries:
        legacy = _legacy_day_summary(
            _resolve(
                phase[
                    "legacy_hourly_run_root"
                    if summary["market_granularity"] == "hourly"
                    else "legacy_qh_run_root"
                ]
            ),
            market_granularity=str(summary["market_granularity"]),
            configuration=str(summary["configuration_id"]),
            policy=str(summary["policy"]),
        )
        rows.append(
            {
                **dict(summary),
                "legacy_represented_cost_eur": legacy[
                    "represented_cost_eur"
                ],
                "represented_cost_change_vs_legacy_eur": float(
                    summary["represented_cost_eur"]
                )
                - legacy["represented_cost_eur"],
                "legacy_da_settlement_eur": legacy["settlement_cost_eur"],
                "legacy_other_represented_procurement_eur": legacy[
                    "other_represented_cost_eur"
                ],
                "legacy_produced_t": legacy["produced_t"],
                "physical_baseline_changed": (
                    summary["configuration_id"] == C1_CONFIGURATION
                ),
            }
        )
    return rows


def _standard_run_files(
    output_root: Path,
    config_path: Path,
    config: Mapping[str, Any],
    fingerprint: Mapping[str, Any],
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "resolved_config.yaml").write_text(
        yaml.safe_dump(dict(config), sort_keys=False), encoding="utf-8"
    )
    _write_json(output_root / "fingerprint_manifest.json", fingerprint)
    _write_json(
        output_root / "input_manifest.json",
        {
            "forecast_root": config["phase6d"]["forecast_root"],
            "delivery_date": EXPECTED_DELIVERY_DAY.isoformat(),
            "forecast_origin_utc": expected_origin_utc(
                EXPECTED_DELIVERY_DAY
            ).isoformat(),
            "legacy_hourly_run_root": config["phase6d"][
                "legacy_hourly_run_root"
            ],
            "legacy_qh_run_root": config["phase6d"]["legacy_qh_run_root"],
            "run_fingerprint": fingerprint["run_fingerprint"],
        },
    )
    _write_json(
        output_root / "code_version.json",
        {
            "git_head": _git_head(),
            "phase6d_module_sha256": _sha256(Path(__file__).resolve()),
            "config_sha256": _sha256(config_path),
        },
    )


def run_phase6d(
    config_path: str | Path = PHASE6D_CONFIG,
    *,
    include_gate_b: bool = True,
) -> dict[str, Any]:
    config_file = _resolve(config_path)
    config = load_phase6d_config(config_file)
    phase = config["phase6d"]
    output_root = _resolve(config["output_root"])
    fingerprint = _fingerprint(config_file, config)
    _standard_run_files(output_root, config_file, config, fingerprint)

    trajectories: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    c0_regressions: list[dict[str, Any]] = []
    c0_checks: list[dict[str, Any]] = []
    started = time.perf_counter()
    for granularity in ("hourly", "quarterhour"):
        try:
            c0_trajectory = _run_c0_regression(
                output_root,
                fingerprint,
                market_granularity=granularity,
            )
            c0_regressions.append(c0_trajectory)
            c0_checks.append(
                _c0_regression_check(
                    c0_trajectory,
                    phase,
                    market_granularity=granularity,
                )
            )
        except (Phase6DError, Phase6BError) as exc:
            failures.append(
                {
                    "gate": "A",
                    "market_granularity": granularity,
                    "configuration_id": C0_CONFIGURATION,
                    "policy": (
                        "H-point"
                        if granularity == "hourly"
                        else "QH-point"
                    ),
                    "error": str(exc),
                }
            )
            break
    gate_a_matrix = [
        ("hourly", C1_CONFIGURATION, "H-point"),
        ("hourly", C1_CONFIGURATION, "price-insensitive"),
        ("hourly", C1_CONFIGURATION, "true-PF"),
        ("quarterhour", C1_CONFIGURATION, "QH-point"),
        ("quarterhour", C1_CONFIGURATION, "price-insensitive"),
        ("quarterhour", C1_CONFIGURATION, "true-PF"),
    ]
    for granularity, configuration, policy in gate_a_matrix:
        if failures:
            break
        try:
            trajectories.append(
                _load_or_run_trajectory(
                    config,
                    output_root,
                    fingerprint,
                    market_granularity=granularity,
                    configuration=configuration,
                    policy=policy,
                )
            )
        except (Phase6DError, Phase6BError) as exc:
            failures.append(
                {
                    "gate": "A",
                    "market_granularity": granularity,
                    "configuration_id": configuration,
                    "policy": policy,
                    "error": str(exc),
                }
            )
            break

    checks = [
        check
        for trajectory in trajectories
        for check in validate_phase6d_trajectory(trajectory)
    ]
    if trajectories:
        checks.append(validate_flat_price_physics_identity(trajectories))
    checks.extend(
        {
            "market_granularity": row["market_granularity"],
            "configuration_id": row["configuration_id"],
            "policy": row["policy"],
            "check_id": row["check_id"],
            "observed": row["represented_cost_error_eur"],
            "expected": 0.0,
            "status": row["status"],
        }
        for row in c0_checks
    )
    gate_a_pass = (
        not failures
        and len(trajectories) == len(gate_a_matrix)
        and len(c0_checks) == 2
        and all(check["status"] == "pass" for check in checks)
    )

    gate_b_status = "not_requested"
    if include_gate_b and gate_a_pass:
        gate_b_status = "in_progress"
        for granularity, policy in (("hourly", "H-S10"), ("quarterhour", "QH-S10")):
            try:
                trajectory = _load_or_run_trajectory(
                    config,
                    output_root,
                    fingerprint,
                    market_granularity=granularity,
                    configuration=C1_CONFIGURATION,
                    policy=policy,
                )
                trajectories.append(trajectory)
                checks.extend(validate_phase6d_trajectory(trajectory))
            except Phase6DPerformanceIncomplete as exc:
                failures.append(
                    {
                        "gate": "B",
                        "market_granularity": granularity,
                        "configuration_id": C1_CONFIGURATION,
                        "policy": policy,
                        "error": str(exc),
                        "classification": "performance_incomplete",
                    }
                )
                gate_b_status = "performance_incomplete"
                break
            except (Phase6DError, Phase6BError) as exc:
                failures.append(
                    {
                        "gate": "B",
                        "market_granularity": granularity,
                        "configuration_id": C1_CONFIGURATION,
                        "policy": policy,
                        "error": str(exc),
                        "classification": "engineering_failure",
                    }
                )
                gate_b_status = "failed"
                break
        if gate_b_status == "in_progress":
            gate_b_status = "pass"

    summaries = [_trajectory_summary(item) for item in trajectories]
    comparisons = _comparison_rows(summaries, phase)
    bids = [
        {
            "market_granularity": trajectory["market_granularity"],
            **row,
        }
        for trajectory in trajectories
        for row in trajectory["bids"]
    ]
    clearing = [
        {
            "market_granularity": trajectory["market_granularity"],
            **row,
        }
        for trajectory in trajectories
        for row in trajectory["clearing"]
    ]
    dispatch = [
        row
        for trajectory in trajectories
        for row in trajectory["physical_dispatch"]
    ]
    states = [trajectory["state"] for trajectory in trajectories]
    solvers = [
        {
            "market_granularity": trajectory["market_granularity"],
            "configuration_id": trajectory["configuration_id"],
            "policy": trajectory["policy"],
            **row,
        }
        for trajectory in trajectories
        for row in trajectory["solver"]
    ]
    scenario_dispatch = [
        row
        for trajectory in trajectories
        for row in trajectory["scenario_dispatch"]
    ]
    heat_events = [
        {
            key: row[key]
            for key in (
                "market_granularity",
                "configuration_id",
                "policy",
                "delivery_day",
                "target_timestamp_utc",
                "physical_interval_index",
                "eaf_heat_start",
                "eaf_melt",
                "eaf_tap",
                "eaf_liquid_steel_output_t",
                "eaf_arc_electricity_mwh",
                "eaf_secondary_electricity_mwh",
                "eaf_dri_input_t",
                "eaf_scrap_input_t",
                "eaf_named_ng_mwh",
            )
        }
        for row in dispatch
        if row["configuration_id"] == C1_CONFIGURATION
        and (
            float(row["eaf_heat_start"]) > 0.5
            or float(row["eaf_melt"]) > 0.5
            or float(row["eaf_tap"]) > 0.5
        )
    ]
    _write_csv(output_root / "submitted_D_bid_curves.csv", bids)
    _write_csv(output_root / "realised_D_market_clearing.csv", clearing)
    _write_csv(output_root / "realised_D_internal_qh_dispatch.csv", dispatch)
    _write_csv(output_root / "rolling_state_handoffs.csv", states)
    _write_csv(output_root / "solver_diagnostics.csv", solvers)
    _write_csv(
        output_root / "planned_scenario_dispatch_audit.csv", scenario_dispatch
    )
    _write_csv(output_root / "eaf_heat_events.csv", heat_events)
    _write_csv(output_root / "phase6d_one_day_summary.csv", summaries)
    _write_csv(
        output_root / "legacy_common_day_comparison.csv", comparisons
    )
    _write_csv(output_root / "validation_checks.csv", checks)
    _write_csv(output_root / "failures.csv", failures)
    _write_csv(output_root / "c0_regression_checks.csv", c0_checks)
    _write_csv(
        output_root / "c0_regression_solver_diagnostics.csv",
        [
            {
                "market_granularity": granularity,
                **row,
            }
            for granularity, trajectory in zip(
                ("hourly", "quarterhour"), c0_regressions
            )
            for row in trajectory["solver"]
        ],
    )

    all_checks_pass = all(check["status"] == "pass" for check in checks)
    accepted = (
        gate_a_pass
        and (not include_gate_b or gate_b_status == "pass")
        and all_checks_pass
        and not failures
    )
    decision = (
        "eaf_heat_state_one_day_hourly_qh_validated"
        if accepted
        else "eaf_heat_state_engineering_validation_incomplete"
    )
    summary = {
        "run_id": config["run_id"],
        "status": "pass" if accepted else "incomplete",
        "decision": decision,
        "delivery_date": EXPECTED_DELIVERY_DAY.isoformat(),
        "forecast_origin_utc": expected_origin_utc(
            EXPECTED_DELIVERY_DAY
        ).isoformat(),
        "gate_a_status": "pass" if gate_a_pass else "failed",
        "gate_b_status": gate_b_status,
        "trajectory_count": len(trajectories),
        "validation_check_count": len(checks),
        "validation_failure_count": sum(
            check["status"] != "pass" for check in checks
        ),
        "failure_count": len(failures),
        "runtime_seconds": time.perf_counter() - started,
        "run_fingerprint": fingerprint["run_fingerprint"],
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
    }
    _write_json(output_root / "run_summary.json", summary)
    _write_json(
        output_root / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "run_root": str(output_root.relative_to(REPO_ROOT)).replace("\\", "/"),
            "decision": decision,
            "lineage_role": config["lineage_role"],
            "git_eligible": False,
        },
    )
    (output_root / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- The 45-minute heat is a QH design-basis rounding of 325/458 = "
        "42.6 minutes, not a measured Tata minimum tap-to-tap time.\n"
        "- Only the C1 EAF is discrete; no other plant gained heat/start/ramp assumptions.\n"
        "- The run is a normal operation day; the documented 8 h/week taphole "
        "maintenance and 14 day/year annual maintenance are not activated.\n"
        "- Longer campaigns require an exogenous EAF maintenance calendar and "
        "explicit overlap policy.\n"
        "- The legacy C1 comparison changes the physical baseline and is not a "
        "continuation of the former Phase-6B/6C week headline.\n"
        "- KGF1, sinter and BF6 retain the existing endogenous Phase-6B/6C "
        "C1 commitment physics. Their continuous-must-run reconciliation is "
        "outside this EAF gate.\n"
        "- mFRR, overpower, intra-heat modulation, CVaR, export, ETS and product "
        "revenue are outside this run.\n",
        encoding="utf-8",
    )
    (output_root / "README.md").write_text(
        "# Phase 6D EAF heat-state one-day validation\n\n"
        "Reproducible one-day comparison for 27 April 2026. Hourly and QH market "
        "interfaces share one internal quarter-hour EAF heat formulation. See "
        "`run_summary.json`, `phase6d_one_day_summary.csv`, "
        "`legacy_common_day_comparison.csv`, and `validation_checks.csv`.\n",
        encoding="utf-8",
    )
    return summary


__all__ = [
    "PHASE6D_CONFIG",
    "Phase6DError",
    "Phase6DPerformanceIncomplete",
    "load_phase6d_config",
    "run_phase6d",
    "run_phase6d_trajectory",
    "solve_grouped_actual_redispatch",
    "solve_grouped_da_bid_plan",
    "validate_flat_price_physics_identity",
    "validate_phase6d_trajectory",
]
