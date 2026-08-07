"""Deterministic C1 temporal-contract repair and governed validation runner.

The module is deliberately isolated from DA bidding, scenarios, clearing,
settlement and stochastic/CVaR code.  It reuses only the shared physical C1
builder and represented-procurement-cost expression.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, time as wall_time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import yaml
from pyomo.environ import (
    Constraint,
    ConstraintList,
    NonNegativeReals,
    Objective,
    Set,
    Var,
    minimize,
    value,
)
from pyomo.opt import SolverFactory
from pyomo.core.expr.visitor import identify_variables
from pyomo.contrib.iis import write_iis
from pyomo.repn import generate_standard_repn

from .model import collect_model_stats
from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C1_CONFIGURATION,
)
from .s4_4c5p_phase5e_source_backed_anchor_closure import (
    annual_anchor_comparisons,
    carrier_coverage,
    generator_balances,
    load_source_contract,
)
from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    SteelPhysicalContext,
    SteelRollingState,
    _build_physical_model,
    _component_value,
    _inventory_overrides,
    _represented_cost_expression,
    _route_progress_values,
    _solver_gap,
    prepare_physical_context,
)
from .rolling_production_quota import (
    build_rolling_production_quota_plan,
    build_timestamped_rolling_production_quota_plan,
)
from .s4_4c_unified_physical_modelbuilder import ModelTimeGrid, REPO_ROOT
from .wag_milp_input_contract import load_governed_wag_factor_maps


TEMPORAL_CONTRACT_VERSION = "c1_deterministic_scalar_temporal_v11_eaf_hsm_load_shape"
CALENDAR_CONTRACT_VERSION = "normal_operation_maintenance_excluded_v1"
RUN_FAMILY_ID = "steel_c6_deterministic_scalar_temporal_repair_v2_20260803"
OBJECTIVE_MODE = "scalar_procurement_plus_linear_continuation"
CONFIG_PATH = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "configs"
    / "steel_c6_deterministic_temporal_repair.yaml"
)
ANNUAL_EAF_ROUTE_T = 3_232_012.260
MWH_TO_PJ = 3.6e-6
EXTERNAL_MER_EAF_REFERENCE_T = 3_300_000.0
EAF_HEAT_SIZE_T = 325.0
HOURS_PER_YEAR = 8_760
QUOTA_PERIOD_HOURS = 168
CONTINUOUS_ASSETS = (
    "coking_plant_1",
    "sintering_plant",
    "blast_furnace_6",
    "drp_pellet_input",
)
ASSET_ON_COMPONENTS = {
    "coking_plant_1": "coking_plant_1_on",
    "sintering_plant": "sintering_plant_on",
    "blast_furnace_6": "blast_furnace_6_on",
    "drp_pellet_input": "drp_on",
}
DEFAULT_RATE_RANGES_T_H = {
    "coking_plant_1": (135.0, 180.0),
    "sintering_plant": (200.0, 340.0),
    "blast_furnace_6": (120.0, 170.0),
    "drp_pellet_input": (350.0, 550.0),
}
INVENTORY_COMPONENTS = (
    "dri_inventory",
    "coke_inventory",
    "sinter_inventory",
    "hot_iron_inventory",
    "cold_slab_inventory",
)
OUTPUT_FILES = (
    "objective_incentive_ledger.csv",
    "temporal_kpis.csv",
    "state_handoff_audit.csv",
    "eaf_heat_ledger.csv",
    "route_progress.csv",
    "energy_wag_generator_audit.csv",
    "baseline_delta.csv",
    "heat_count_certification.csv",
    "scalar_objective_components.csv",
    "continuation_calibration.json",
    "annual_operational_anchor_results.csv",
    "administrative_carbon_balance.csv",
    "annual_anchor_delta_vs_last_accepted.csv",
    "annual_operational_anchor_gate.json",
    "certification_progress.json",
    "solver_attempts.json",
    "run_manifest.json",
    "gate_decision.json",
)
MONEY_PRESERVATION_FLOOR_EUR = 1e-4
PHYSICAL_TOLERANCE = 1e-6
STATE_BOUND_CANONICALIZATION_TOLERANCE = 1e-5
ANCHOR_REGISTER_PATH = (
    REPO_ROOT
    / "data/03_Optimisation/inputs/assets/steel/S4/c5_model_anchor_register/"
    "c5_model_anchor_evidence_register.csv"
)
ANNUAL_SERVICE_CONTRACT_PATH = (
    REPO_ROOT
    / "data/03_Optimisation/inputs/assets/steel/S4/"
    "c5_phase5e_source_backed_anchor_contract/"
    "source_backed_annual_service_contract.csv"
)
LAST_ACCEPTED_ANNUAL_BASELINE_ROOT = (
    REPO_ROOT
    / "data/03_Optimisation/runs/"
    "steel_c5_phase5e_source_backed_anchor_closure_v1_20260727"
)
PHASE5E_CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/"
    "steel_c5_phase5e_source_backed_anchor_closure.yaml"
)


@dataclass(frozen=True)
class HeatCountCertificationCase:
    """Stateful identity of one deterministic fixed-count certification."""

    case_id: str
    count: int
    start_state: SteelRollingState
    calendar_day_length_hours: int
    remaining_quota_taps: int
    physical_horizon_hours: int = 48
    terminal_policy: str = "recoverable_physical_tail"

    @property
    def interval_count(self) -> int:
        return int(self.calendar_day_length_hours * 4)

    @property
    def physical_tail_hours(self) -> int:
        return int(self.physical_horizon_hours - self.calendar_day_length_hours)


@dataclass(frozen=True)
class ScalarObjectiveComponents:
    """Named expressions for the one deterministic operational objective."""

    procurement_eur: Any
    continuation_eur: Any
    total_eur: Any
    remaining_taps_before: int
    continuation_eur_per_heat: float


@dataclass(frozen=True)
class LinearHeatContinuationCalibration:
    """Fingerprinted offline calibration of the temporary linear terminal value."""

    continuation_eur_per_heat: float
    endpoint_costs_eur: Mapping[int, float]
    marginal_costs_eur_per_heat: Mapping[str, float]
    state_sha256: str
    price_profile_sha256: str
    contract_version: str
    input_sha256: Mapping[str, str]


@dataclass
class ScalarSolveResult:
    """One primary or fallback scalar-solver attempt."""

    run_case: str
    attempt: str
    status: str
    solver_status: str
    termination_condition: str
    feasible_incumbent: bool
    incumbent_objective_eur: float | None
    procurement_eur: float | None
    continuation_eur: float | None
    best_bound_eur: float | None
    absolute_gap_eur: float | None
    relative_gap: float | None
    runtime_seconds: float
    time_limit_seconds: float
    mip_gap_target: float
    fallback_used: bool
    solver_log_path: str
    variable_count: int
    binary_count: int
    constraint_count: int
    audit_status: str = "pending"

    def record(self) -> dict[str, Any]:
        return dict(self.__dict__)


class TemporalRepairError(RuntimeError):
    """Fail-closed deterministic temporal repair error."""


class TemporalPhysicalInfeasibility(TemporalRepairError):
    """Source/development contract has been proved physically infeasible."""


def round_half_up(value_in: float | Decimal) -> int:
    return int(Decimal(str(value_in)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cumulative_eaf_target_taps(hours: int) -> int:
    if int(hours) < 0:
        raise TemporalRepairError("Cumulative EAF target hours cannot be negative.")
    return round_half_up(
        Decimal(str(ANNUAL_EAF_ROUTE_T))
        / Decimal(str(EAF_HEAT_SIZE_T))
        * Decimal(int(hours))
        / Decimal(HOURS_PER_YEAR)
    )


def quota_period_target_taps(period_index: int) -> int:
    start = int(period_index) * QUOTA_PERIOD_HOURS
    end = start + QUOTA_PERIOD_HOURS
    return cumulative_eaf_target_taps(end) - cumulative_eaf_target_taps(start)


def physical_day_heat_cap(
    interval_count: int,
    *,
    initial_start_lag1: int = 0,
    initial_start_lag2: int = 0,
) -> int:
    """Return the exact maximum taps under three-QH single-furnace occupancy."""

    if int(interval_count) <= 0:
        raise TemporalRepairError("A calendar day must contain positive intervals.")
    state = (int(initial_start_lag1), int(initial_start_lag2))
    if state[0] not in {0, 1} or state[1] not in {0, 1} or sum(state) > 1:
        raise TemporalRepairError("Invalid EAF carry-in start lags.")
    frontier: dict[tuple[int, int], int] = {state: 0}
    for _ in range(int(interval_count)):
        next_frontier: dict[tuple[int, int], int] = {}
        for (lag1, lag2), taps in frontier.items():
            for start in (0, 1):
                if start + lag1 + lag2 > 1:
                    continue
                next_state = (start, lag1)
                next_frontier[next_state] = max(
                    next_frontier.get(next_state, -1), taps + lag2
                )
        frontier = next_frontier
    return max(frontier.values())


def heat_count_expansion_order(
    lower: int = 20,
    upper: int = 32,
) -> tuple[int, ...]:
    """Return the governed core-first, alternating fixed-count order."""

    if int(lower) > 26 or int(upper) < 28:
        raise TemporalRepairError("Heat-count expansion must contain core 26--28.")
    order = [27, 26, 28]
    distance = 1
    while 26 - distance >= int(lower) or 28 + distance <= int(upper):
        if 26 - distance >= int(lower):
            order.append(26 - distance)
        if 28 + distance <= int(upper):
            order.append(28 + distance)
        distance += 1
    return tuple(order)


def dynamic_daily_heat_bounds(
    *,
    remaining_taps: int,
    today_lower: int,
    today_upper: int,
    future_lower_bounds: Sequence[int],
    future_upper_bounds: Sequence[int],
) -> tuple[int, int]:
    lower = max(int(today_lower), int(remaining_taps) - sum(future_upper_bounds))
    upper = min(int(today_upper), int(remaining_taps) - sum(future_lower_bounds))
    if lower > upper:
        raise TemporalPhysicalInfeasibility(
            "EAF weekly target is not recoverable under the certified daily band."
        )
    return lower, upper


def quota_neutral_daily_taps(remaining_taps: int, remaining_days: int) -> int:
    if int(remaining_days) <= 0:
        raise TemporalRepairError("Quota-neutral heat selection requires a remaining day.")
    return round_half_up(Decimal(int(remaining_taps)) / Decimal(int(remaining_days)))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _calendar_day_context(
    context: SteelPhysicalContext,
    *,
    calendar_day_length_hours: int,
    physical_horizon_hours: int,
) -> SteelPhysicalContext:
    """Return a physical context whose executed block follows the calendar day."""

    day_hours = int(calendar_day_length_hours)
    horizon_hours = int(physical_horizon_hours)
    if day_hours not in {23, 24, 25}:
        raise TemporalRepairError("Heat certification supports only 23/24/25-hour days.")
    if horizon_hours < day_hours:
        raise TemporalRepairError("Physical horizon must contain the executed calendar day.")
    time_grid = ModelTimeGrid(
        horizon_hours=horizon_hours,
        execution_hours=day_hours,
        time_step_hours=float(context.time_grid.time_step_hours),
    )
    quota_t = (
        float(context.config["annual_reference_target_mt_y"])
        * 1_000_000.0
        * day_hours
        / HOURS_PER_YEAR
    )
    plan = (
        build_rolling_production_quota_plan(
            planning_horizon_hours=horizon_hours,
            execution_block_hours=day_hours,
            quota_per_execution_block_t=quota_t,
        )
        if horizon_hours % day_hours == 0
        else build_timestamped_rolling_production_quota_plan(
            planning_horizon_hours=horizon_hours,
            execution_block_hours=day_hours,
            cumulative_deadline_hours=(day_hours, horizon_hours),
            quota_per_hour_t=quota_t / day_hours,
        )
    )
    return replace(
        context,
        plan=plan,
        time_grid=time_grid,
        economic_horizon_hours=day_hours,
    )


def reachable_eaf_carry_in_states(
    reference_state: SteelRollingState,
) -> tuple[SteelRollingState, ...]:
    """Enumerate legal occupancy templates, not full physically reached states."""

    return tuple(
        replace(reference_state, eaf_start_lag1=lag1, eaf_start_lag2=lag2)
        for lag1, lag2 in ((0, 0), (1, 0), (0, 1))
    )


def add_execution_boundary_carry_witness(
    model: Any,
    *,
    execution_steps: int,
    lag1: int,
    lag2: int,
) -> None:
    """Force a predecessor solve to produce one exact rolling EAF carry state."""

    if (int(lag1), int(lag2)) not in {(1, 0), (0, 1)}:
        raise TemporalRepairError(
            "A non-idle carry witness must select exactly one EAF start lag."
        )
    if int(execution_steps) < 2:
        raise TemporalRepairError("A carry witness needs at least two executed intervals.")
    if not hasattr(model, "eaf_heat_start"):
        raise TemporalRepairError("The EAF heat-state model is required for carry witnesses.")
    model.temporal_carry_witness_lag1 = Constraint(
        expr=model.eaf_heat_start[int(execution_steps) - 1] == int(lag1)
    )
    model.temporal_carry_witness_lag2 = Constraint(
        expr=model.eaf_heat_start[int(execution_steps) - 2] == int(lag2)
    )


def _remaining_scrap_caps(
    state: SteelRollingState,
    config: Mapping[str, Any],
) -> dict[str, float]:
    scrap = config["deterministic_temporal_repair"]["scrap_origin_contract"]
    external_used = (
        float(state.cumulative_external_scrap_to_bof_t)
        + float(state.cumulative_external_scrap_to_eaf_t)
    )
    internal_used = (
        float(state.cumulative_internal_scrap_to_bof_t)
        + float(state.cumulative_internal_scrap_to_eaf_t)
    )
    return {
        "remaining_bof_scrap_cap_t": max(
            0.0,
            float(scrap["annual_bof_scrap_cap_t_y"])
            - float(state.cumulative_external_scrap_to_bof_t)
            - float(state.cumulative_internal_scrap_to_bof_t),
        ),
        "remaining_eaf_scrap_cap_t": max(
            0.0,
            float(scrap["annual_eaf_scrap_cap_t_y"])
            - float(state.cumulative_external_scrap_to_eaf_t)
            - float(state.cumulative_internal_scrap_to_eaf_t),
        ),
        "remaining_external_scrap_cap_t": max(
            0.0, float(scrap["annual_external_scrap_cap_t_y"]) - external_used
        ),
        "remaining_internal_scrap_cap_t": max(
            0.0, float(scrap["annual_internal_scrap_cap_t_y"]) - internal_used
        ),
        "remaining_site_scrap_cap_t": max(
            0.0,
            float(scrap["annual_site_scrap_cap_t_y"])
            - external_used
            - internal_used,
        ),
    }


def heat_count_case_metadata(
    case: HeatCountCertificationCase,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    state = case.start_state
    return {
        "case_id": case.case_id,
        "fixed_count": int(case.count),
        "state_sha256": _canonical_json_sha256(state.snapshot()),
        "calendar_day_length_hours": int(case.calendar_day_length_hours),
        "interval_count": int(case.interval_count),
        "carry_in_lag1": int(state.eaf_start_lag1),
        "carry_in_lag2": int(state.eaf_start_lag2),
        "beginning_inventories_json": json.dumps(
            state.inventory_overrides, sort_keys=True
        ),
        **_remaining_scrap_caps(state, config),
        "remaining_week_taps": int(case.remaining_quota_taps),
        "physical_horizon_hours": int(case.physical_horizon_hours),
        "physical_tail_hours": int(case.physical_tail_hours),
        "terminal_policy": case.terminal_policy,
    }


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def load_temporal_repair_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("temporal_contract_version") != TEMPORAL_CONTRACT_VERSION:
        raise TemporalRepairError("Unexpected deterministic temporal contract version.")
    if config.get("calendar_contract_version") != CALENDAR_CONTRACT_VERSION:
        raise TemporalRepairError("Unexpected deterministic calendar contract version.")
    if config.get("objective_mode") != OBJECTIVE_MODE:
        raise TemporalRepairError("Unexpected deterministic scalar objective mode.")
    repair = config.get("deterministic_temporal_repair")
    if not isinstance(repair, Mapping):
        raise TemporalRepairError("Missing deterministic_temporal_repair config block.")
    exact = {
        "economic_horizon_hours": 24,
        "physical_horizon_hours": 48,
        "offline_week_horizon_hours": 168,
        "time_step_hours": 0.25,
    }
    for key, expected in exact.items():
        if float(repair[key]) != float(expected):
            raise TemporalRepairError(f"Temporal contract field {key} must remain {expected}.")
    if float(repair.get("feasibility_initial_time_limit_seconds", 0.0)) != 60.0:
        raise TemporalRepairError("D3 initial feasibility limit must remain 60 seconds.")
    if float(repair.get("feasibility_extended_time_limit_seconds", 0.0)) < 60.0:
        raise TemporalRepairError("D3 extended feasibility limit cannot be below 60 seconds.")
    if float(repair.get("operational_time_limit_seconds", 0.0)) != 6.0:
        raise TemporalRepairError("Operational scalar time limit must remain 6 seconds.")
    if float(repair.get("operational_fallback_time_limit_seconds", 0.0)) != 60.0:
        raise TemporalRepairError("Operational scalar fallback must remain 60 seconds.")
    if not math.isclose(float(repair["runtime_mip_gap"]), 0.002):
        raise TemporalRepairError("Operational scalar MIP gap must remain 0.002.")
    if any(not bool(value) for value in config.get("forbidden_scope", {}).values()):
        raise TemporalRepairError("Every market/stochastic/final-period scope flag must remain forbidden.")
    eaf = repair["eaf_heat_contract"]
    if not math.isclose(float(eaf["annual_route_basis_t"]), ANNUAL_EAF_ROUTE_T):
        raise TemporalRepairError("Executable EAF route basis changed.")
    if not math.isclose(float(eaf["external_mer_reference_t"]), EXTERNAL_MER_EAF_REFERENCE_T):
        raise TemporalRepairError("External MER EAF reference changed.")
    if int(eaf["normal_day_forbidden_taps"]) != 34:
        raise TemporalRepairError("The impossible 34-tap normal day must remain explicit.")
    bf = repair.get("c1_bf_material_interface")
    if not isinstance(bf, Mapping):
        raise TemporalRepairError("Missing explicit C1 BF material interface.")
    if str(bf.get("activity_rate_unit")) != "t_represented_bf_activity/h":
        raise TemporalRepairError("BF6 activity was relabelled as physical throughput.")
    if not math.isclose(float(bf["sinter_t_per_t_hot_metal"]), 1.0):
        raise TemporalRepairError("Central C1 sinter/hot-metal coupling must remain 1.0.")
    if not math.isclose(
        float(bf["sensitivity_sinter_t_per_t_hot_metal"]), 1.088
    ):
        raise TemporalRepairError("The predetermined sinter sensitivity must remain 1.088.")
    if any(
        not math.isclose(float(bf[key]), 2_800_000.0)
        for key in ("annual_sinter_anchor_t_y", "annual_hot_metal_anchor_t_y")
    ):
        raise TemporalRepairError("C1 sinter and hot-metal anchors must remain 2.8 Mt/y.")
    scrap = repair.get("scrap_origin_contract")
    expected_scrap = {
        "annual_bof_scrap_cap_t_y": 1_000_000.0,
        "annual_eaf_scrap_cap_t_y": 900_000.0,
        "annual_external_scrap_cap_t_y": 1_300_000.0,
        "annual_internal_scrap_cap_t_y": 600_000.0,
        "annual_site_scrap_cap_t_y": 1_900_000.0,
    }
    if not isinstance(scrap, Mapping) or any(
        not math.isclose(float(scrap.get(key, math.nan)), expected)
        for key, expected in expected_scrap.items()
    ):
        raise TemporalRepairError("The base C1 scrap-origin caps changed.")
    metallics = repair.get("c1_metallics_sensitivity")
    if not isinstance(metallics, Mapping) or str(metallics.get("mode")) != "base":
        raise TemporalRepairError("The central temporal run must keep base metallics mode.")
    if float(metallics.get("hbi_annual_cap_t_y", math.nan)) != 0.0:
        raise TemporalRepairError("Central C1 HBI must remain exactly zero.")
    if bool(metallics.get("buffer_capacity_change_authorized", True)):
        raise TemporalRepairError("The generic DRI buffer capacity may not be tuned.")
    dynamics = repair.get("plant_dynamics")
    if not isinstance(dynamics, Mapping):
        raise TemporalRepairError("Missing governed C1 plant-dynamics contract.")
    sifa_dynamics = dynamics.get("sifa")
    bf6_dynamics = dynamics.get("bf6")
    drp_dynamics = dynamics.get("drp")
    kgf1_dynamics = dynamics.get("kgf1")
    pefa_dynamics = dynamics.get("pefa")
    if not all(
        isinstance(item, Mapping)
        for item in (
            sifa_dynamics,
            bf6_dynamics,
            drp_dynamics,
            kgf1_dynamics,
            pefa_dynamics,
        )
    ):
        raise TemporalRepairError("Incomplete C1 plant-dynamics contract.")
    if not math.isclose(float(sifa_dynamics["ramp_t_h_per_qh"]), 6.265638):
        raise TemporalRepairError("Central SiFa normalized development ramp changed.")
    if int(sifa_dynamics["minimum_direction_intervals"]) != 8:
        raise TemporalRepairError("Central SiFa anti-reversal window must remain 8 QH.")
    if not math.isclose(float(bf6_dynamics["maximum_step_t_h"]), 2.94819):
        raise TemporalRepairError("BF6 normalized hourly step changed.")
    if not math.isclose(float(kgf1_dynamics["setpoint_block_hours"]), 4.0):
        raise TemporalRepairError("KGF1 must use four-hour setpoints.")
    if not math.isclose(float(drp_dynamics["maximum_step_t_h"]), 12.5):
        raise TemporalRepairError("DRP must use the bounded hourly setpoint step.")
    if not (
        math.isclose(float(pefa_dynamics["minimum_output_t_h"]), 450.0)
        and math.isclose(float(pefa_dynamics["maximum_output_t_h"]), 600.0)
        and math.isclose(float(pefa_dynamics["imported_pellets_t_y"]), 200_000.0)
    ):
        raise TemporalRepairError("The bounded PeFa/pellet-interface contract changed.")
    kgf1 = repair.get("kgf1_route_scale_reconciliation")
    expected_kgf1 = {
        "active": True,
        "raw_kgf1_coke_anchor_t_y": 1_000_000.0,
        "raw_bof_liquid_steel_anchor_t_y": 3_400_000.0,
    }
    if not isinstance(kgf1, Mapping) or any(
        (
            bool(kgf1.get(key)) != expected
            if isinstance(expected, bool)
            else not math.isclose(float(kgf1.get(key, math.nan)), expected)
        )
        for key, expected in expected_kgf1.items()
    ):
        raise TemporalRepairError("The KGF1 route-scale reconciliation changed.")
    return config


def rate_ranges_from_config(config: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
    rows = config["deterministic_temporal_repair"]["continuous_must_run_assets"]
    result = {
        str(asset): (
            float(bounds["minimum_rate_t_h"]),
            float(bounds["maximum_rate_t_h"]),
        )
        for asset, bounds in rows.items()
    }
    if result != DEFAULT_RATE_RANGES_T_H:
        raise TemporalRepairError("C1 must-run throughput bounds changed from the active inputs.")
    return result


def canonicalize_state_rate(
    rate: float,
    lower: float,
    upper: float,
) -> float:
    """Snap solver roundoff to an existing state bound without widening it."""

    observed = float(rate)
    if lower - STATE_BOUND_CANONICALIZATION_TOLERANCE <= observed < lower:
        return float(lower)
    if upper < observed <= upper + STATE_BOUND_CANONICALIZATION_TOLERANCE:
        return float(upper)
    return observed


def prepare_temporal_context(config: Mapping[str, Any]) -> SteelPhysicalContext:
    repair = config["deterministic_temporal_repair"]
    base_path = REPO_ROOT / str(repair["base_context_config"])
    base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    phase = base["phase6d"]
    phase["planning_horizon_hours"] = int(repair["physical_horizon_hours"])
    phase["execution_hours"] = int(repair["economic_horizon_hours"])
    phase["time_step_hours"] = float(repair["time_step_hours"])
    phase["economic_horizon_hours"] = int(repair["economic_horizon_hours"])
    phase["physical_feasibility_tail_active"] = True
    phase["solver_time_limit_seconds"] = float(repair["solver_time_limit_seconds"])
    phase["temporal_contract_version"] = TEMPORAL_CONTRACT_VERSION
    context = prepare_physical_context(base)
    if tuple(context.c1_continuous_activities) != CONTINUOUS_ASSETS:
        raise TemporalRepairError(
            "C1 component ontology did not resolve the four required must-run assets."
        )
    if context.generator_unit_interface is None:
        raise TemporalRepairError("The active C1 physical boundary has no VN25 interface.")
    generator_mode = repair["generator_mode"]
    generator = dict(context.generator_unit_interface)
    generator.update(
        {
            "operating_mode": str(generator_mode["mode_id"]),
            "hourly_price_response": True,
            "vn25_electric_capacity_mw": float(
                generator_mode["vn25_maximum_output_mw"]
            ),
            "vn25_min_electric_output_mw": float(
                generator_mode["vn25_minimum_output_mw"]
            ),
            "vn25_ramp_mw_per_h": float(generator_mode["vn25_ramp_mw_per_h"]),
            "ij01_forced_off": bool(generator_mode["ij01_forced_off"]),
            "development_policy_authorization": str(
                generator_mode["development_policy_authorization"]
            ),
            "ij01_total_fuel_horizon_cap_mwh": 0.0,
            "ij01_total_fuel_deadline_caps_mwh": {24: 0.0, 48: 0.0},
        }
    )
    generator_sensitivity = repair.get("experimental_generator_efficiency")
    if generator_sensitivity:
        if generator_sensitivity.get("classification") != "experimental_combined_generator_efficiency_not_vn25_source_truth":
            raise TemporalRepairError("Unexpected generator-efficiency sensitivity.")
        generator["vn25_electricity_efficiency"] = float(generator_sensitivity["efficiency"])
    return replace(
        context,
        generator_unit_interface=generator,
        generator_interface_cap_mode="volume_envelope_only",
        temporal_contract_version=TEMPORAL_CONTRACT_VERSION,
        calendar_contract_version=CALENDAR_CONTRACT_VERSION,
        economic_horizon_hours=24,
        physical_feasibility_tail_active=True,
    )


def initial_temporal_state(config: Mapping[str, Any]) -> SteelRollingState:
    ranges = rate_ranges_from_config(config)
    dynamics = config["deterministic_temporal_repair"]["plant_dynamics"]
    reference_rates = {
        str(asset): float(rate)
        for asset, rate in dynamics["normal_reference_rates_t_h"].items()
    }
    if set(reference_rates) != set(CONTINUOUS_ASSETS):
        raise TemporalRepairError("Normal reference state lacks a continuous asset.")
    pefa = dynamics["pefa"]
    return SteelRollingState(
        episode_id="deterministic_temporal_repair",
        configuration_id=C1_CONFIGURATION,
        temporal_contract_version=TEMPORAL_CONTRACT_VERSION,
        calendar_contract_version=CALENDAR_CONTRACT_VERSION,
        last_continuous_rate_t_h=reference_rates,
        last_vn25_output_mw=175.0,
        drp_last_pellet_input_t=ranges["drp_pellet_input"][0] * 0.25,
        eaf_quota_period_id="week_0000",
        eaf_quota_target_taps=quota_period_target_taps(0),
        eaf_quota_completed_taps=0,
        pefa_last_output_t_h=float(pefa["initial_output_t_h"]),
        pellet_inventory_t=float(pefa["initial_inventory_t"]),
        hsm_last_input_t_h=float(
            dynamics["downstream_temporal_contract"]["hsm_initial_rate_t_h"]
        ),
    )


def validate_temporal_state(state: SteelRollingState, config: Mapping[str, Any]) -> None:
    if state.temporal_contract_version != TEMPORAL_CONTRACT_VERSION:
        raise TemporalRepairError("Old or unversioned rolling state is forbidden under v5.")
    if state.calendar_contract_version != CALENDAR_CONTRACT_VERSION:
        raise TemporalRepairError(
            "Old maintenance-calendar rolling state is forbidden under the "
            "maintenance-excluded calendar contract."
        )
    if state.configuration_id != C1_CONFIGURATION:
        raise TemporalRepairError("Temporal v5 state must belong to C1.")
    ranges = rate_ranges_from_config(config)
    if set(state.last_continuous_rate_t_h) != set(CONTINUOUS_ASSETS):
        raise TemporalRepairError("Temporal state lacks a canonical continuous-asset rate.")
    for asset, rate in state.last_continuous_rate_t_h.items():
        lower, upper = ranges[asset]
        if not lower - PHYSICAL_TOLERANCE <= float(rate) <= upper + PHYSICAL_TOLERANCE:
            raise TemporalRepairError(f"State rate for {asset} is outside its existing bounds.")
    if state.last_vn25_output_mw is None or not (
        175.0 - PHYSICAL_TOLERANCE
        <= state.last_vn25_output_mw
        <= 350.0 + PHYSICAL_TOLERANCE
    ):
        raise TemporalRepairError("Temporal state lacks a valid VN25 output.")
    if state.eaf_quota_period_id is None or state.eaf_quota_target_taps is None:
        raise TemporalRepairError("Temporal state lacks its EAF quota-period contract.")
    if not 0 <= state.eaf_quota_completed_taps <= state.eaf_quota_target_taps:
        raise TemporalRepairError("Temporal state has invalid completed EAF taps.")
    if state.sifa_trend_direction not in {"up", "down", "flat"}:
        raise TemporalRepairError("Temporal state has an invalid SiFa trend direction.")
    direction_window = int(
        config["deterministic_temporal_repair"]["plant_dynamics"]["sifa"]
        ["minimum_direction_intervals"]
    )
    if not 0 <= int(state.sifa_trend_cooldown_intervals) < direction_window:
        raise TemporalRepairError("Temporal state has an invalid SiFa reversal cooldown.")
    pefa = config["deterministic_temporal_repair"]["plant_dynamics"]["pefa"]
    if state.pefa_last_output_t_h is None or not (
        float(pefa["minimum_output_t_h"]) - PHYSICAL_TOLERANCE
        <= float(state.pefa_last_output_t_h)
        <= float(pefa["maximum_output_t_h"]) + PHYSICAL_TOLERANCE
    ):
        raise TemporalRepairError("Temporal state lacks a valid PeFa output.")
    if state.pellet_inventory_t is None or float(state.pellet_inventory_t) < 0.0:
        raise TemporalRepairError("Temporal state lacks a valid pellet inventory.")
    if state.hsm_last_input_t_h is None or not 0.0 <= float(
        state.hsm_last_input_t_h
    ) <= 800.0:
        raise TemporalRepairError("Temporal state lacks its HSM campaign handoff.")
    scrap_fields = (
        "cumulative_external_scrap_to_bof_t",
        "cumulative_external_scrap_to_eaf_t",
        "cumulative_internal_scrap_to_bof_t",
        "cumulative_internal_scrap_to_eaf_t",
    )
    if any(float(getattr(state, field)) < -PHYSICAL_TOLERANCE for field in scrap_fields):
        raise TemporalRepairError("Temporal state contains negative cumulative scrap use.")
    scrap = config["deterministic_temporal_repair"]["scrap_origin_contract"]
    external = float(state.cumulative_external_scrap_to_bof_t) + float(
        state.cumulative_external_scrap_to_eaf_t
    )
    internal = float(state.cumulative_internal_scrap_to_bof_t) + float(
        state.cumulative_internal_scrap_to_eaf_t
    )
    if external > float(scrap["annual_external_scrap_cap_t_y"]) + 1e-5:
        raise TemporalRepairError("Executed external scrap exceeds its annual quota.")
    if internal > float(scrap["annual_internal_scrap_cap_t_y"]) + 1e-5:
        raise TemporalRepairError("Executed internal scrap exceeds its annual quota.")
    if external + internal > float(scrap["annual_site_scrap_cap_t_y"]) + 1e-5:
        raise TemporalRepairError("Executed site scrap exceeds its annual quota.")


def final_product_execution_band(
    context: SteelPhysicalContext,
    state: SteelRollingState,
) -> tuple[float, float]:
    annual_total_t = float(context.config["annual_reference_target_mt_y"]) * 1_000_000.0
    next_hours = int(state.executed_hours) + int(context.time_grid.execution_hours)
    cumulative_central = annual_total_t * next_hours / HOURS_PER_YEAR
    cumulative_lower = cumulative_central * 0.995
    cumulative_upper = cumulative_central * 1.005
    return (
        max(0.0, cumulative_lower - float(state.cumulative_production_t)),
        max(0.0, cumulative_upper - float(state.cumulative_production_t)),
    )


def _add_daily_heat_contract(
    model: Any,
    *,
    lower_taps: int,
    upper_taps: int,
    fixed_taps: int | None,
    execution_steps: int,
    week_boundary: bool,
) -> None:
    if int(upper_taps) > physical_day_heat_cap(execution_steps):
        raise TemporalRepairError("Daily EAF upper bound exceeds exact occupancy capacity.")
    if fixed_taps is not None and not int(lower_taps) <= int(fixed_taps) <= int(upper_taps):
        raise TemporalRepairError("Fixed EAF count lies outside the declared daily bounds.")
    model.executed_eaf_taps = sum(model.eaf_tap[q] for q in range(execution_steps))
    if fixed_taps is None:
        model.eaf_daily_heat_lower = Constraint(expr=model.executed_eaf_taps >= int(lower_taps))
        model.eaf_daily_heat_upper = Constraint(expr=model.executed_eaf_taps <= int(upper_taps))
    else:
        model.eaf_daily_heat_fixed = Constraint(expr=model.executed_eaf_taps == int(fixed_taps))
    if week_boundary:
        model.eaf_week_boundary_idle = Constraint(
            expr=model.eaf_heat_start[execution_steps - 2]
            + model.eaf_heat_start[execution_steps - 1]
            == 0
        )
    model.eaf_daily_lower_taps = int(lower_taps)
    model.eaf_daily_upper_taps = int(upper_taps)
    model.eaf_week_boundary_active = bool(week_boundary)


def build_temporal_model(
    context: SteelPhysicalContext,
    state: SteelRollingState,
    config: Mapping[str, Any],
    *,
    lower_taps: int,
    upper_taps: int,
    fixed_taps: int | None = None,
    planning_horizon_hours: int = 48,
    week_boundary: bool = False,
    hard_inventory_terminal: bool = False,
    final_product_execution_bounds_t: tuple[float, float] | None = None,
    execution_inventory_terminal_targets_t: Mapping[str, float] | None = None,
    route_reference_policy: str = "maintenance_free_daily_reference",
    executed_route_bounds_t: Mapping[str, tuple[float, float]] | None = None,
) -> Any:
    validate_temporal_state(state, config)
    lower_product, upper_product = (
        final_product_execution_band(context, state)
        if final_product_execution_bounds_t is None
        else tuple(float(item) for item in final_product_execution_bounds_t)
    )
    if not 0.0 <= lower_product <= upper_product:
        raise TemporalRepairError("Invalid final-product execution bounds.")
    model = _build_physical_model(
        context,
        C1_CONFIGURATION,
        state,
        terminal_day=False,
        planning_horizon_hours=int(planning_horizon_hours),
        temporal_repair_contract={
            "temporal_contract_version": TEMPORAL_CONTRACT_VERSION,
            "inventory_terminal_policy": (
                "hard_terminal"
                if hard_inventory_terminal
                else "recoverable_physical_tail"
            ),
            "recursive_recovery_horizon_hours": 48,
            "final_product_execution_lower_t": lower_product,
            "final_product_execution_upper_t": upper_product,
            "eaf_annual_route_basis_t_y": ANNUAL_EAF_ROUTE_T,
            "route_reference_policy": str(route_reference_policy),
            "c1_bf_material_interface": dict(
                config["deterministic_temporal_repair"][
                    "c1_bf_material_interface"
                ]
            ),
            "scrap_origin_contract": dict(
                config["deterministic_temporal_repair"]["scrap_origin_contract"]
            ),
            "kgf1_route_scale_reconciliation": dict(
                config["deterministic_temporal_repair"][
                    "kgf1_route_scale_reconciliation"
                ]
            ),
            "c1_metallics_sensitivity": {
                **dict(
                    config["deterministic_temporal_repair"][
                        "c1_metallics_sensitivity"
                    ]
                ),
                "hbi_horizon_cap_t": float(
                    config["deterministic_temporal_repair"][
                        "c1_metallics_sensitivity"
                    ]["hbi_annual_cap_t_y"]
                )
                * int(planning_horizon_hours)
                / HOURS_PER_YEAR,
            },
            "plant_dynamics": {
                **dict(
                    config["deterministic_temporal_repair"]["plant_dynamics"]
                ),
                "sifa": {
                    **dict(
                        config["deterministic_temporal_repair"]["plant_dynamics"]
                        ["sifa"]
                    ),
                    "initial_direction": state.sifa_trend_direction,
                    "initial_cooldown_intervals": int(
                        state.sifa_trend_cooldown_intervals
                    ),
                },
                "pefa": {
                    **dict(
                        config["deterministic_temporal_repair"]["plant_dynamics"]
                        ["pefa"]
                    ),
                    "initial_output_t_h": float(state.pefa_last_output_t_h),
                    "initial_inventory_t": float(state.pellet_inventory_t),
                },
            },
            "experimental_self_use_calibration": dict(
                config["deterministic_temporal_repair"].get(
                    "experimental_self_use_calibration", {}
                )
            ),
            "experimental_process_electricity_overlay": dict(
                config["deterministic_temporal_repair"].get(
                    "experimental_process_electricity_overlay", {}
                )
            ),
            "experimental_ng_service_calibration": dict(
                config["deterministic_temporal_repair"].get(
                    "experimental_ng_service_calibration", {}
                )
            ),
            "experimental_coal_wag_calibration": dict(
                config["deterministic_temporal_repair"].get(
                    "experimental_coal_wag_calibration", {}
                )
            ),
        },
    )
    _add_daily_heat_contract(
        model,
        lower_taps=lower_taps,
        upper_taps=upper_taps,
        fixed_taps=fixed_taps,
        execution_steps=context.time_grid.execution_steps,
        week_boundary=week_boundary,
    )
    model.kgf1_anchor_constraints_active = False
    model.kgf1_anchor_role = (
        "validation_only_mer_annual_reference_physical_coke_balance_drives_output"
    )
    wag_diagnostic = dict(
        config["deterministic_temporal_repair"].get(
            "experimental_wag_self_use_diagnostic", {}
        )
    )
    if wag_diagnostic.get("active"):
        annual_caps = dict(wag_diagnostic.get("vn25_carrier_caps_pj_y", {}))
        expected = {"COG": 0.0, "BOFG": 1.4}
        if annual_caps != expected:
            raise TemporalRepairError(
                "The WAG self-use diagnostic must retain its declared COG/BOFG caps."
            )
        model.experimental_wag_self_use_caps = ConstraintList()
        for carrier, annual_cap_pj in annual_caps.items():
            variable_name = f"{carrier.lower()}_to_vn25"
            if not hasattr(model, variable_name):
                raise TemporalRepairError(
                    f"Missing VN25 carrier variable for diagnostic cap: {carrier}."
                )
            execution_cap_mwh = (
                float(annual_cap_pj) * 1_000_000.0 / 3.6
                * context.time_grid.execution_hours / HOURS_PER_YEAR
            )
            model.experimental_wag_self_use_caps.add(
                sum(
                    getattr(model, variable_name)[q]
                    for q in range(context.time_grid.execution_steps)
                )
                <= execution_cap_mwh
            )
        model.experimental_wag_self_use_diagnostic = True
        model.experimental_wag_self_use_status = (
            "non_promoted_annualised_vn25_carrier_caps_no_new_process_sink"
        )
    if execution_inventory_terminal_targets_t is not None:
        last_executed = context.time_grid.execution_steps - 1
        allowed = {
            "dri_inventory",
            "coke_inventory",
            "sinter_inventory",
            "hot_iron_inventory",
            "cold_slab_inventory",
        }
        unknown = set(execution_inventory_terminal_targets_t).difference(allowed)
        if unknown:
            raise TemporalRepairError(
                f"Unknown annual execution-terminal inventories: {sorted(unknown)}"
            )
        model.annual_execution_inventory_terminal = ConstraintList()
        for component_name, target in execution_inventory_terminal_targets_t.items():
            target_index = (
                last_executed - 1
                if component_name == "dri_inventory"
                and bool(getattr(model, "eaf_heat_state_active", False))
                else last_executed
            )
            model.annual_execution_inventory_terminal.add(
                getattr(model, component_name)[target_index] == float(target)
            )
        model.annual_execution_inventory_terminal_status = (
            "hard_calendar_year_closure_with_last_quarter_dri_carry"
        )
        model.annual_execution_dri_terminal_index = last_executed - 1
    if executed_route_bounds_t is not None:
        if route_reference_policy != "annual_recoverable_calendar":
            raise TemporalRepairError(
                "Executed route bounds require annual-recoverable route policy."
            )
        hsm_yield = float(context.c1_reference_routing["hsm_final_t_per_t_slab"])
        route_expressions = {
            "bof_liquid_steel": sum(
                model.bof_crude_steel_output[q] for q in range(context.time_grid.execution_steps)
            ),
            "eaf_liquid_steel": sum(
                model.eaf_liquid_steel_output[q] for q in range(context.time_grid.execution_steps)
            ),
            "hsm_final_output": sum(
                hsm_yield * model.hot_strip_mill[q]
                for q in range(context.time_grid.execution_steps)
            ),
            "dsp_final_output": sum(
                model.dsp_final_product_output[q]
                for q in range(context.time_grid.execution_steps)
            ),
            "imported_slab": sum(
                model.imported_slab_to_hsm[q]
                for q in range(context.time_grid.execution_steps)
            ),
        }
        unknown_routes = set(executed_route_bounds_t).difference(route_expressions)
        if unknown_routes:
            raise TemporalRepairError(
                f"Unknown annual executed route bounds: {sorted(unknown_routes)}"
            )
        model.annual_executed_route_bounds = ConstraintList()
        for route_id, bounds in executed_route_bounds_t.items():
            lower, upper = (float(item) for item in bounds)
            if not 0.0 <= lower <= upper:
                raise TemporalRepairError(f"Invalid annual route bounds for {route_id}.")
            model.annual_executed_route_bounds.add(
                route_expressions[route_id] >= lower
            )
            model.annual_executed_route_bounds.add(
                route_expressions[route_id] <= upper
            )
        model.annual_route_reference_status = (
            "same_annual_route_volumes_calendar_recoverable"
        )
    return model


def add_week_heat_contract(
    model: Any,
    *,
    target_taps: int,
    daily_pattern: Sequence[int] | None = None,
    intervals_per_day: int = 96,
) -> None:
    model.eaf_week_total_taps = sum(model.eaf_tap[q] for q in model.TIME)
    model.eaf_week_target = Constraint(expr=model.eaf_week_total_taps == int(target_taps))
    model.eaf_week_terminal_idle = Constraint(
        expr=model.eaf_heat_start[len(model.TIME) - 2]
        + model.eaf_heat_start[len(model.TIME) - 1]
        == 0
    )
    if daily_pattern is not None:
        if sum(int(item) for item in daily_pattern) != int(target_taps):
            raise TemporalRepairError("Extreme EAF daily pattern does not close its week target.")
        model.EAF_WEEK_DAY = Set(initialize=range(len(daily_pattern)), ordered=True)
        model.eaf_week_daily_pattern = Constraint(
            model.EAF_WEEK_DAY,
            rule=lambda m, day: sum(
                m.eaf_tap[q]
                for q in range(
                    int(day) * intervals_per_day,
                    (int(day) + 1) * intervals_per_day,
                )
            )
            == int(daily_pattern[int(day)]),
        )


def extreme_week_patterns(lower: int, upper: int, target: int) -> dict[str, list[int]]:
    def allocate(order: Sequence[int]) -> list[int]:
        result = [int(lower)] * 7
        remaining = int(target) - sum(result)
        for day in order:
            addition = min(int(upper) - int(lower), remaining)
            result[int(day)] += addition
            remaining -= addition
        if remaining != 0:
            raise TemporalPhysicalInfeasibility("Certified band cannot allocate the weekly target.")
        return result

    return {
        "front_loaded": allocate(range(7)),
        "back_loaded": allocate(range(6, -1, -1)),
        "alternating": allocate((0, 2, 4, 6, 1, 3, 5)),
    }


def add_total_variation_tier(
    model: Any,
    state: SteelRollingState,
    config: Mapping[str, Any],
    *,
    execution_steps: int,
) -> Any:
    ranges = rate_ranges_from_config(config)
    index = tuple((asset, q) for asset in CONTINUOUS_ASSETS for q in range(execution_steps))
    model.TEMPORAL_TV_INDEX = Set(dimen=2, initialize=index, ordered=True)
    model.temporal_tv_abs = Var(model.TEMPORAL_TV_INDEX, domain=NonNegativeReals)
    model.temporal_tv_positive = ConstraintList()
    model.temporal_tv_negative = ConstraintList()
    dt = float(model.time_step_hours)
    for asset in CONTINUOUS_ASSETS:
        component = getattr(model, asset)
        rate_range = ranges[asset][1] - ranges[asset][0]
        for q in range(execution_steps):
            current_rate = component[q] / dt
            previous_rate = (
                float(state.last_continuous_rate_t_h[asset])
                if q == 0
                else component[q - 1] / dt
            )
            normalized_delta = (current_rate - previous_rate) / rate_range
            model.temporal_tv_positive.add(
                model.temporal_tv_abs[asset, q] >= normalized_delta
            )
            model.temporal_tv_negative.add(
                model.temporal_tv_abs[asset, q] >= -normalized_delta
            )
    model.temporal_total_variation = sum(
        model.temporal_tv_abs[asset, q] for asset, q in index
    )
    return model.temporal_total_variation


def add_heat_neutrality_tier(model: Any, neutral_taps: int) -> Any:
    model.temporal_heat_count_deviation = Var(domain=NonNegativeReals)
    model.temporal_heat_count_deviation_positive = Constraint(
        expr=model.temporal_heat_count_deviation
        >= model.executed_eaf_taps - int(neutral_taps)
    )
    model.temporal_heat_count_deviation_negative = Constraint(
        expr=model.temporal_heat_count_deviation
        >= int(neutral_taps) - model.executed_eaf_taps
    )
    model.temporal_quota_neutral_taps = int(neutral_taps)
    return model.temporal_heat_count_deviation


def objective_variable_names(expression: Any) -> set[str]:
    representation = generate_standard_repn(expression)
    return {variable.parent_component().name for variable in representation.linear_vars}


def must_run_bof_conflict_diagnostic(model: Any) -> dict[str, Any]:
    """Reconstruct the must-run/route conflict algebraically without another solve."""

    def coefficient(expression: Any, variable: Any) -> float:
        representation = generate_standard_repn(expression)
        for item, factor in zip(
            representation.linear_vars, representation.linear_coefs
        ):
            if item is variable:
                return float(factor)
        raise TemporalRepairError(f"Coefficient for {variable.name} is absent.")

    first = 0
    sinter_yield = -coefficient(
        model.sinter_balance[first].body, model.sintering_plant[first]
    )
    hot_metal_per_activity = -coefficient(
        model.hot_iron_balance[first].body, model.blast_furnace_6[first]
    )
    sinter_per_activity = coefficient(
        model.sinter_balance[first].body, model.blast_furnace_6[first]
    )
    bof_liquid_yield = coefficient(
        model.bof_crude_steel_output[first].expr,
        model.basic_oxygen_furnace[first],
    )
    minimum_sinter_feed_interval_t = 160.0 * float(model.time_step_hours)
    horizon_sinter_output_t = (
        len(model.TIME) * minimum_sinter_feed_interval_t * sinter_yield
    )

    def initial_inventory(balance: Any) -> float:
        representation = generate_standard_repn(balance[first].body)
        return -float(representation.constant or 0.0)

    sinter_initial_t = initial_inventory(model.sinter_balance)
    hot_iron_initial_t = initial_inventory(model.hot_iron_balance)
    sinter_capacity_t = float(value(model.sinter_capacity[first].upper))
    hot_iron_capacity_t = float(value(model.hot_iron_capacity[first].upper))
    sinter_terminal_active = bool(model.sinter_terminal.active)
    hot_iron_terminal_active = bool(model.hot_iron_terminal.active)
    maximum_sinter_carry_increase_t = (
        0.0
        if sinter_terminal_active
        else max(0.0, sinter_capacity_t - sinter_initial_t)
    )
    minimum_bf_sinter_input_from_sifa_t = max(
        0.0,
        horizon_sinter_output_t - maximum_sinter_carry_increase_t,
    )
    minimum_activity_from_sifa_t = (
        minimum_bf_sinter_input_from_sifa_t / sinter_per_activity
    )
    minimum_must_run_activity_t = (
        float(model.c1_bf_activity_min_t_h)
        * len(model.TIME)
        * float(model.time_step_hours)
    )
    minimum_bf_activity_t = max(
        minimum_activity_from_sifa_t, minimum_must_run_activity_t
    )
    minimum_bf_sinter_input_t = minimum_bf_activity_t * sinter_per_activity
    horizon_hot_iron_output_t = minimum_bf_activity_t * hot_metal_per_activity
    maximum_hot_iron_carry_increase_t = (
        0.0
        if hot_iron_terminal_active
        else max(0.0, hot_iron_capacity_t - hot_iron_initial_t)
    )
    minimum_bof_hot_iron_input_t = max(
        0.0,
        horizon_hot_iron_output_t - maximum_hot_iron_carry_increase_t,
    )
    forced_bof_liquid_t = minimum_bof_hot_iron_input_t * bof_liquid_yield
    upper_name = (
        "c1_reference_deadline_bof_liquid_steel_"
        f"{len(model.TIME)}h_upper"
    )
    upper_constraint = getattr(model, upper_name)
    route_upper_t = float(value(upper_constraint.upper))
    return {
        "conflict_id": "c1_must_run_sinter_to_bof_route_upper",
        "proof_basis": (
            "algebraic_capacity_lower_bound_under_recoverable_physical_tail"
        ),
        "iis_constraint_families": [
            "retained_process_min[sintering_plant,*]",
            "sinter_balance[*]",
            "sinter_capacity[*]",
            "hot_iron_balance[*]",
            "hot_iron_capacity[*]",
            upper_name,
        ],
        "conversion_direction_audit": {
            "sinter": "t_sinter_output_per_t_iron_ore_input",
            "bf_activity": "t_represented_bf_activity_not_physical_sinter",
            "hot_iron": "t_hot_iron_output_per_t_represented_bf_activity",
            "physical_sinter": "t_sinter_input_per_t_hot_iron_output",
            "bof": "t_liquid_steel_output_per_t_hot_iron_input",
            "status": "activity_and_physical_material_buses_separated",
        },
        "tail_handoff_policy": getattr(
            model, "temporal_tail_handoff_policy", "cyclic_tail_closure"
        ),
        "sinter_terminal_active": sinter_terminal_active,
        "hot_iron_terminal_active": hot_iron_terminal_active,
        "minimum_sinter_feed_t_h": 160.0,
        "sinter_output_t_per_t_ore": sinter_yield,
        "hot_iron_output_t_per_t_represented_bf_activity": (
            hot_metal_per_activity
        ),
        "sinter_input_t_per_t_represented_bf_activity": sinter_per_activity,
        "sinter_input_t_per_t_hot_metal": float(
            model.c1_sinter_t_per_t_hot_metal
        ),
        "bof_liquid_output_t_per_t_hot_iron_input": bof_liquid_yield,
        "sinter_initial_inventory_t": sinter_initial_t,
        "sinter_capacity_t": sinter_capacity_t,
        "maximum_sinter_carry_increase_t": maximum_sinter_carry_increase_t,
        "minimum_bf_activity_t": minimum_bf_activity_t,
        "minimum_bf_sinter_input_t": minimum_bf_sinter_input_t,
        "hot_iron_initial_inventory_t": hot_iron_initial_t,
        "hot_iron_capacity_t": hot_iron_capacity_t,
        "maximum_hot_iron_carry_increase_t": maximum_hot_iron_carry_increase_t,
        "minimum_bof_hot_iron_input_t": minimum_bof_hot_iron_input_t,
        "forced_minimum_bof_liquid_steel_t": forced_bof_liquid_t,
        "existing_bof_route_upper_t": route_upper_t,
        "minimum_excess_over_upper_t": forced_bof_liquid_t - route_upper_t,
        "horizon_hours": len(model.TIME) * float(model.time_step_hours),
        "bound_changes_applied": False,
    }


def recursive_coke_hot_iron_conflict_diagnostic(model: Any) -> dict[str, Any]:
    """Prove the rolling KGF1/coke/hot-iron/BOF conflict without another solve."""

    cut = model.temporal_coke_hot_iron_route_recursive_recoverability
    representation = generate_standard_repn(cut.body)
    coefficients = {
        variable.name: float(coefficient)
        for variable, coefficient in zip(
            representation.linear_vars,
            representation.linear_coefs,
        )
    }
    handoff = int(model.temporal_recursive_recovery_handoff_index)
    coke_coefficient = coefficients[f"coke_inventory[{handoff}]"]
    hot_iron_coefficient = coefficients[f"hot_iron_inventory[{handoff}]"]
    beginning = dict(model.temporal_beginning_inventories_t)
    coke_initial = float(beginning["coke_store_initial_t"])
    hot_iron_initial = float(beginning["hot_iron_store_initial_t"])
    weighted_initial = (
        coke_coefficient * coke_initial
        + hot_iron_coefficient * hot_iron_initial
    )
    execution_steps = int(model.temporal_objective_execution_steps)
    recovery_steps = int(model.temporal_recursive_recovery_horizon_steps)
    minimum_coke_output_execution = (
        float(model.temporal_recursive_recovery_minimum_coke_output_t)
        * execution_steps
        / recovery_steps
    )
    execution_upper_name = (
        f"c1_reference_deadline_bof_liquid_steel_{execution_steps}h_upper"
    )
    execution_upper = float(value(getattr(model, execution_upper_name).upper))
    minimum_weighted_handoff = (
        weighted_initial
        + coke_coefficient * minimum_coke_output_execution
        - execution_upper
    )
    cut_inventory_limit = float(value(cut.upper)) - float(
        representation.constant or 0.0
    )
    recovery_hours = float(model.temporal_recursive_recovery_horizon_hours)
    minimum_equivalent_bof_rate = (
        coke_coefficient
        * float(model.temporal_recursive_recovery_minimum_coke_output_t)
        / recovery_hours
    )
    bof_upper_rate = (
        float(model.temporal_recursive_recovery_route_upper_t) / recovery_hours
    )
    hard_week_terminal_excess = (
        minimum_equivalent_bof_rate - bof_upper_rate
    ) * QUOTA_PERIOD_HOURS
    return {
        "conflict_id": "c1_kgf1_coke_hot_iron_bof_recursive_week_conflict",
        "proof_basis": "conserved_coke_hot_iron_equivalent_inventory",
        "iis_constraint_families": [
            "retained_process_min[coking_plant_1,*]",
            "coke_balance[*]",
            "hot_iron_balance[*]",
            execution_upper_name,
            "temporal_coke_hot_iron_route_recursive_recoverability",
        ],
        "coke_initial_t": coke_initial,
        "hot_iron_initial_t": hot_iron_initial,
        "weighted_equivalent_initial_t_liquid_steel": weighted_initial,
        "minimum_coke_output_execution_t": minimum_coke_output_execution,
        "maximum_bof_liquid_steel_execution_t": execution_upper,
        "minimum_weighted_handoff_t_liquid_steel": minimum_weighted_handoff,
        "recursive_handoff_limit_t_liquid_steel": cut_inventory_limit,
        "recursive_handoff_excess_t_liquid_steel": (
            minimum_weighted_handoff - cut_inventory_limit
        ),
        "minimum_kgf1_equivalent_bof_rate_t_h": minimum_equivalent_bof_rate,
        "bof_route_upper_rate_t_h": bof_upper_rate,
        "hard_168h_terminal_minimum_excess_t_liquid_steel": (
            hard_week_terminal_excess
        ),
        "physical_bounds_or_yields_changed": False,
    }


def _solver(
    config: Mapping[str, Any],
    *,
    mip_gap: float,
    warm_start: bool = False,
    time_limit_seconds: float | None = None,
    solver_log_path: Path | None = None,
    dual_reductions: bool = True,
    feasibility_tolerance: float | None = None,
    mip_gap_abs_eur: float | None = None,
) -> Any:
    repair = config["deterministic_temporal_repair"]
    solver = SolverFactory("gurobi")
    if solver is None or not solver.available(exception_flag=False):
        raise TemporalRepairError("Gurobi is required for deterministic temporal repair.")
    solver.options["TimeLimit"] = float(
        repair["solver_time_limit_seconds"]
        if time_limit_seconds is None
        else time_limit_seconds
    )
    solver.options["MIPGap"] = float(mip_gap)
    if mip_gap_abs_eur is not None:
        solver.options["MIPGapAbs"] = float(mip_gap_abs_eur)
    solver.options["MIPFocus"] = int(repair["runtime_mip_focus"])
    solver.options["Threads"] = int(repair["solver_threads"])
    solver.options["Seed"] = int(repair["solver_seed"])
    solver.options["DualReductions"] = int(bool(dual_reductions))
    if feasibility_tolerance is not None:
        tolerance = float(feasibility_tolerance)
        if not 1e-9 <= tolerance <= 1e-2:
            raise TemporalRepairError("Gurobi feasibility tolerance is out of range.")
        solver.options["FeasibilityTol"] = tolerance
    if solver_log_path is not None:
        solver_log_path.parent.mkdir(parents=True, exist_ok=True)
        solver.options["LogFile"] = str(solver_log_path)
    solver._temporal_warm_start = bool(warm_start)
    return solver


def _copy_adjacent_warm_start(source_model: Any, target_model: Any) -> int:
    """Copy like-named variable values between adjacent fixed-count models."""

    copied = 0
    for source_component in source_model.component_objects(Var, active=True):
        target_component = target_model.find_component(source_component.name)
        if target_component is None:
            continue
        for index in source_component:
            if index not in target_component:
                continue
            source_value = source_component[index].value
            target_variable = target_component[index]
            if source_value is None or target_variable.fixed:
                continue
            target_variable.set_value(source_value, skip_validation=True)
            copied += 1
    return copied


def _variable_belongs_to_executed_prefix(
    variable: Any,
    *,
    execution_steps: int,
    time_step_hours: float,
) -> bool:
    index = variable.index()
    if isinstance(index, tuple):
        integer_indices = [item for item in index if isinstance(item, int)]
        if not integer_indices:
            return False
        temporal_index = integer_indices[-1]
    elif isinstance(index, int):
        temporal_index = index
    else:
        return False
    if variable.parent_component().name.endswith("_day_on"):
        executed_days = int(
            math.ceil(execution_steps * float(time_step_hours) / 24.0)
        )
        return temporal_index < executed_days
    return temporal_index < execution_steps


def _fix_executed_solution_prefix(
    source_model: Any,
    target_model: Any,
    execution_steps: int,
) -> int:
    """Fix the exact executed prefix for a longer-tail extension certificate."""

    fixed = 0
    for source_component in source_model.component_objects(Var, active=True):
        target_component = target_model.find_component(source_component.name)
        if target_component is None:
            continue
        for index in source_component:
            if index not in target_component:
                continue
            if not _variable_belongs_to_executed_prefix(
                source_component[index],
                execution_steps=execution_steps,
                time_step_hours=float(getattr(source_model, "time_step_hours", 1.0)),
            ):
                continue
            reference_value = source_component[index].value
            if reference_value is None:
                raise TemporalRepairError(
                    f"Executed prefix variable {source_component[index].name} has no value."
                )
            target_variable = target_component[index]
            if target_variable.fixed and abs(
                float(value(target_variable)) - float(reference_value)
            ) > PHYSICAL_TOLERANCE:
                raise TemporalRepairError(
                    f"Executed prefix conflicts with fixed {target_variable.name}."
                )
            target_variable.fix(float(reference_value))
            fixed += 1
    if fixed == 0:
        raise TemporalRepairError("No executed variables were fixed for tail extension.")
    return fixed


def solve_tier(
    model: Any,
    solver: Any,
    *,
    tier: str,
    run_case: str,
    require_optimal: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        try:
            result = solver.solve(
                model,
                tee=False,
                warmstart=bool(getattr(solver, "_temporal_warm_start", False)),
            )
        except (TypeError, ValueError):
            result = solver.solve(model, tee=False)
    except Exception as exc:
        raise TemporalRepairError(f"{run_case}/{tier} solver invocation failed: {exc}") from exc
    runtime = time.perf_counter() - started
    termination = str(result.solver.termination_condition).lower()
    stats = collect_model_stats(model)
    record = {
        "run_case": run_case,
        "tier": tier,
        "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "mip_gap": _solver_gap(result),
        "runtime_seconds": runtime,
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
    }
    if termination in {"infeasible", "infeasibleorunbounded"}:
        error = TemporalPhysicalInfeasibility(
            f"{run_case}/{tier} is infeasible under the source/development contract."
        )
        error.solver_record = record
        raise error
    if require_optimal and termination != "optimal":
        raise TemporalRepairError(
            f"{run_case}/{tier} did not prove optimality: "
            f"{result.solver.status}/{result.solver.termination_condition}."
        )
    if termination not in {"optimal", "feasible", "maxtimelimit"}:
        raise TemporalRepairError(
            f"{run_case}/{tier} failed: {result.solver.status}/"
            f"{result.solver.termination_condition}."
        )
    return record


def _result_bound(result: Any) -> float | None:
    for container_name in ("problem", "solver"):
        container = getattr(result, container_name, None)
        if container is None:
            continue
        for field in ("lower_bound", "upper_bound", "best_bound", "bound"):
            try:
                raw = getattr(container, field)
            except (AttributeError, TypeError):
                continue
            try:
                candidate = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(candidate):
                return candidate
    return None


def _write_infeasible_iis(model: Any, path: Path | None) -> tuple[str, str]:
    if path is None:
        return "not_requested", ""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_iis(model, str(path), solver="gurobi")
    except Exception as exc:  # pragma: no cover - solver/version specific
        return f"failed:{type(exc).__name__}:{exc}", ""
    return "written", str(path.relative_to(REPO_ROOT))


def _solve_zero_objective_feasibility(
    model: Any,
    config: Mapping[str, Any],
    *,
    run_case: str,
    iis_path: Path | None = None,
    write_iis_on_infeasible: bool = False,
    time_limit_seconds: float | None = None,
    warm_start: bool = False,
    warm_start_source_case: str = "",
    solver_log_path: Path | None = None,
) -> dict[str, Any]:
    """Certify feasibility without requiring an economic optimality proof."""

    if not hasattr(model, "temporal_physical_zero_preservation"):
        model.temporal_physical_zero_preservation = Constraint(
            expr=model.rolling_production_progress_deviation_t == 0.0
        )
    if not hasattr(model, "temporal_feasibility_objective"):
        model.temporal_feasibility_objective = Objective(
            expr=0.0 * model.executed_eaf_taps,
            sense=minimize,
        )
    solver = _solver(
        config,
        mip_gap=0.0,
        warm_start=warm_start,
        time_limit_seconds=time_limit_seconds,
        solver_log_path=solver_log_path,
    )
    started = time.perf_counter()
    try:
        try:
            result = solver.solve(
                model,
                tee=False,
                load_solutions=False,
                warmstart=warm_start,
            )
        except TypeError:
            result = solver.solve(model, tee=False)
    except Exception as exc:
        raise TemporalRepairError(
            f"{run_case}/physical_feasibility_certificate solver invocation failed: {exc}"
        ) from exc
    runtime = time.perf_counter() - started
    termination = str(result.solver.termination_condition).lower()
    solution_count = len(result.solution)
    feasible_incumbent = solution_count > 0
    if feasible_incumbent:
        try:
            model.solutions.load_from(result)
        except Exception as exc:
            raise TemporalRepairError(
                f"{run_case} has an incumbent that Pyomo could not load: {exc}"
            ) from exc
    infeasible = termination == "infeasible"
    if infeasible and write_iis_on_infeasible:
        iis_status, iis_relative_path = _write_infeasible_iis(model, iis_path)
    elif infeasible:
        iis_status, iis_relative_path = "not_requested_regular_infeasible", ""
    else:
        iis_status, iis_relative_path = "not_applicable", ""
    accepted = feasible_incumbent and not infeasible
    stats = collect_model_stats(model)
    return {
        "run_case": run_case,
        "tier": "physical_feasibility_certificate",
        "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "mip_gap": _solver_gap(result),
        "objective_bound": _result_bound(result),
        "runtime_seconds": runtime,
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "objective_value": 0.0 if feasible_incumbent else None,
        "feasible_incumbent": feasible_incumbent,
        "feasibility_status": (
            "accepted_feasible_incumbent"
            if accepted
            else ("proven_infeasible" if infeasible else "unknown")
        ),
        "iis_status": iis_status,
        "iis_path": iis_relative_path,
        "physical_optimum_fixed_t": 0.0,
        "time_limit_seconds": time_limit_seconds,
        "warm_start_used": bool(warm_start),
        "warm_start_source_case": warm_start_source_case,
        "solver_log_path": (
            ""
            if solver_log_path is None
            else str(solver_log_path.relative_to(REPO_ROOT))
        ),
    }


def solve_heat_count_certificate(
    model: Any,
    config: Mapping[str, Any],
    case: HeatCountCertificationCase,
    *,
    iis_root: Path | None = None,
    solve_attempt: str = "initial",
    time_limit_seconds: float | None = None,
    warm_start: bool = False,
    warm_start_source_case: str = "",
    solver_log_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    iis_path = None if iis_root is None else iis_root / f"{case.case_id}.ilp"
    record = _solve_zero_objective_feasibility(
        model,
        config,
        run_case=case.case_id,
        iis_path=iis_path,
        write_iis_on_infeasible=False,
        time_limit_seconds=time_limit_seconds,
        warm_start=warm_start,
        warm_start_source_case=warm_start_source_case,
        solver_log_path=solver_log_path,
    )
    certification = {
        **heat_count_case_metadata(case, config),
        "feasible_incumbent": record["feasible_incumbent"],
        "objective_bound": record["objective_bound"],
        "mip_gap": record["mip_gap"],
        "solver_status": record["solver_status"],
        "termination_condition": record["termination_condition"],
        "feasibility_status": record["feasibility_status"],
        "iis_status": record["iis_status"],
        "iis_path": record["iis_path"],
        "cost_check_status": (
            "pending_applicable_feasible_endpoint"
            if record["feasible_incumbent"]
            else (
                "not_applicable_unknown_endpoint"
                if record["feasibility_status"] == "unknown"
                else "not_applicable_infeasible_endpoint"
            )
        ),
        "represented_cost_D_eur": "",
        "solve_attempt": solve_attempt,
        "time_limit_seconds": time_limit_seconds,
        "warm_start_used": bool(warm_start),
        "warm_start_source_case": warm_start_source_case,
        "solver_log_path": record["solver_log_path"],
    }
    certification["beginning_inventories_json"] = json.dumps(
        getattr(
            model,
            "temporal_beginning_inventories_t",
            case.start_state.inventory_overrides,
        ),
        sort_keys=True,
    )
    return record, certification


def build_and_solve_heat_count_case(
    context: SteelPhysicalContext,
    config: Mapping[str, Any],
    case: HeatCountCertificationCase,
    *,
    iis_root: Path | None = None,
    adjacent_model: Any | None = None,
    adjacent_case_id: str = "",
    solve_attempt: str = "initial",
    time_limit_seconds: float | None = None,
    solver_log_path: Path | None = None,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    day_context = _calendar_day_context(
        context,
        calendar_day_length_hours=case.calendar_day_length_hours,
        physical_horizon_hours=case.physical_horizon_hours,
    )
    physical_cap = physical_day_heat_cap(
        case.interval_count,
        initial_start_lag1=case.start_state.eaf_start_lag1,
        initial_start_lag2=case.start_state.eaf_start_lag2,
    )
    declared_upper = min(32, physical_cap)
    if not 20 <= int(case.count) <= declared_upper:
        raise TemporalRepairError(
            f"{case.case_id} fixed count {case.count} exceeds its stateful "
            f"20--{declared_upper} contract."
        )
    model = build_temporal_model(
        day_context,
        case.start_state,
        config,
        lower_taps=20,
        upper_taps=declared_upper,
        fixed_taps=case.count,
        planning_horizon_hours=case.physical_horizon_hours,
    )
    warm_start_count = (
        0
        if adjacent_model is None
        else _copy_adjacent_warm_start(adjacent_model, model)
    )
    record, certification = solve_heat_count_certificate(
        model,
        config,
        case,
        iis_root=iis_root,
        solve_attempt=solve_attempt,
        time_limit_seconds=time_limit_seconds,
        warm_start=warm_start_count > 0,
        warm_start_source_case=adjacent_case_id if warm_start_count > 0 else "",
        solver_log_path=solver_log_path,
    )
    record["warm_start_value_count"] = warm_start_count
    certification["warm_start_value_count"] = warm_start_count
    certification["physical_day_cap_taps"] = physical_cap
    return model, record, certification


def solve_fixed_count_cost_endpoint(
    context: SteelPhysicalContext,
    model: Any,
    config: Mapping[str, Any],
    *,
    run_case: str,
    electricity_prices: Sequence[float],
    solver_log_path: Path | None = None,
) -> tuple[dict[str, Any], float]:
    execution_steps = context.time_grid.execution_steps
    if len(electricity_prices) != execution_steps:
        raise TemporalRepairError("Cost endpoint prices must cover executed D only.")
    represented_cost = _represented_cost_expression(
        context,
        model,
        C1_CONFIGURATION,
        tuple(float(item) for item in electricity_prices)
        + tuple(0.0 for _ in range(len(model.TIME) - execution_steps)),
        objective_hours=tuple(range(execution_steps)),
    )
    for variable in identify_variables(represented_cost, include_fixed=False):
        index = variable.index()
        time_index = index[-1] if isinstance(index, tuple) else index
        if not isinstance(time_index, int) or time_index >= execution_steps:
            raise TemporalRepairError(
                f"Tail variable leaked into fixed-count cost endpoint: {variable.name}."
            )
    model.temporal_physical_zero_preservation = Constraint(
        expr=model.rolling_production_progress_deviation_t == 0.0
    )
    model.temporal_cost_endpoint_objective = Objective(
        expr=represented_cost,
        sense=minimize,
    )
    record = solve_tier(
        model,
        _solver(config, mip_gap=0.0, solver_log_path=solver_log_path),
        tier="represented_cost_D_fixed_physical_zero",
        run_case=run_case,
        require_optimal=True,
    )
    cost = float(value(represented_cost))
    record["objective_value"] = cost
    record["physical_optimum_fixed_t"] = 0.0
    record["solver_log_path"] = (
        ""
        if solver_log_path is None
        else str(solver_log_path.relative_to(REPO_ROOT))
    )
    return record, cost


def build_scalar_objective_components(
    context: SteelPhysicalContext,
    model: Any,
    *,
    electricity_prices: Sequence[float],
    remaining_taps: int,
    continuation_eur_per_heat: float,
) -> ScalarObjectiveComponents:
    """Build the single D-only procurement plus linear terminal-value objective."""

    execution_steps = context.time_grid.execution_steps
    if len(electricity_prices) != execution_steps:
        raise TemporalRepairError("Economic price vector must contain executed D only.")
    prices = tuple(float(item) for item in electricity_prices) + tuple(
        0.0 for _ in range(len(model.TIME) - execution_steps)
    )
    represented_cost = _represented_cost_expression(
        context,
        model,
        C1_CONFIGURATION,
        prices,
        objective_hours=tuple(range(execution_steps)),
    )
    cost_variables = list(identify_variables(represented_cost, include_fixed=False))
    if not cost_variables:
        raise TemporalRepairError("D-only represented cost unexpectedly has no variables.")
    for variable in cost_variables:
        index = variable.index()
        time_index = index[-1] if isinstance(index, tuple) else index
        if not isinstance(time_index, int) or time_index >= execution_steps:
            raise TemporalRepairError(
                f"Tail variable leaked into D-only cost: {variable.name}."
            )
    if not hasattr(model, "temporal_physical_zero_preservation"):
        model.temporal_physical_zero_preservation = Constraint(
            expr=model.rolling_production_progress_deviation_t == 0.0
        )
    continuation = float(continuation_eur_per_heat) * (
        int(remaining_taps) - model.executed_eaf_taps
    )
    total = represented_cost + continuation
    model.temporal_scalar_objective = Objective(expr=total, sense=minimize)
    model.temporal_objective_mode = OBJECTIVE_MODE
    model.temporal_objective_execution_steps = int(execution_steps)
    return ScalarObjectiveComponents(
        procurement_eur=represented_cost,
        continuation_eur=continuation,
        total_eur=total,
        remaining_taps_before=int(remaining_taps),
        continuation_eur_per_heat=float(continuation_eur_per_heat),
    )


def scalar_reporting_kpis(
    model: Any,
    state: SteelRollingState,
    config: Mapping[str, Any],
    *,
    execution_steps: int,
    remaining_taps: int,
    remaining_days: int,
) -> dict[str, float]:
    """Evaluate reporting-only TV and quota-neutrality without model penalties."""

    ranges = rate_ranges_from_config(config)
    dt = float(model.time_step_hours)
    total_variation = 0.0
    for asset in CONTINUOUS_ASSETS:
        component = getattr(model, asset)
        span = ranges[asset][1] - ranges[asset][0]
        previous = float(state.last_continuous_rate_t_h[asset])
        for q in range(execution_steps):
            current = float(value(component[q])) / dt
            total_variation += abs(current - previous) / span
            previous = current
    taps = round_half_up(float(value(model.executed_eaf_taps)))
    neutral = quota_neutral_daily_taps(remaining_taps, remaining_days)
    return {
        "normalized_total_variation": total_variation,
        "quota_neutral_taps": float(neutral),
        "heat_deviation": float(abs(taps - neutral)),
        "executed_taps": float(taps),
    }


def _solve_scalar_attempt(
    model: Any,
    components: ScalarObjectiveComponents,
    config: Mapping[str, Any],
    *,
    run_case: str,
    attempt: str,
    time_limit_seconds: float,
    mip_gap: float,
    solver_log_path: Path,
    fallback_used: bool,
    warm_start: bool = False,
    dual_reductions: bool = True,
    feasibility_tolerance: float | None = None,
    mip_gap_abs_eur: float | None = None,
) -> ScalarSolveResult:
    solver = _solver(
        config,
        mip_gap=mip_gap,
        warm_start=warm_start,
        time_limit_seconds=time_limit_seconds,
        solver_log_path=solver_log_path,
        dual_reductions=dual_reductions,
        feasibility_tolerance=feasibility_tolerance,
        mip_gap_abs_eur=mip_gap_abs_eur,
    )
    started = time.perf_counter()
    try:
        try:
            result = solver.solve(
                model,
                tee=False,
                load_solutions=False,
                warmstart=warm_start,
            )
        except TypeError:
            result = solver.solve(model, tee=False, load_solutions=False)
    except Exception as exc:
        raise TemporalRepairError(f"{run_case}/{attempt} scalar solve failed: {exc}") from exc
    runtime = time.perf_counter() - started
    termination = str(result.solver.termination_condition).lower()
    feasible_incumbent = len(result.solution) > 0
    if feasible_incumbent:
        model.solutions.load_from(result)
    proven_infeasible = termination == "infeasible"
    if proven_infeasible:
        status = "proven_infeasible"
    elif feasible_incumbent and termination == "optimal":
        status = "optimal"
    elif feasible_incumbent:
        status = "feasible_fallback" if fallback_used else "feasible_time_limited"
    else:
        status = "unknown_under_time_limit"
    incumbent = float(value(components.total_eur)) if feasible_incumbent else None
    procurement = (
        float(value(components.procurement_eur)) if feasible_incumbent else None
    )
    continuation = (
        float(value(components.continuation_eur)) if feasible_incumbent else None
    )
    bound = _result_bound(result)
    absolute_gap = (
        None
        if incumbent is None or bound is None
        else max(0.0, float(incumbent) - float(bound))
    )
    relative_gap = _solver_gap(result)
    if relative_gap is None and absolute_gap is not None and incumbent is not None:
        relative_gap = absolute_gap / max(1.0, abs(incumbent))
    stats = collect_model_stats(model)
    return ScalarSolveResult(
        run_case=run_case,
        attempt=attempt,
        status=status,
        solver_status=str(result.solver.status),
        termination_condition=str(result.solver.termination_condition),
        feasible_incumbent=feasible_incumbent,
        incumbent_objective_eur=incumbent,
        procurement_eur=procurement,
        continuation_eur=continuation,
        best_bound_eur=bound,
        absolute_gap_eur=absolute_gap,
        relative_gap=relative_gap,
        runtime_seconds=runtime,
        time_limit_seconds=float(time_limit_seconds),
        mip_gap_target=float(mip_gap),
        fallback_used=bool(fallback_used),
        solver_log_path=str(solver_log_path.relative_to(REPO_ROOT)),
        variable_count=stats.variables,
        binary_count=stats.binaries,
        constraint_count=stats.constraints,
    )


def solve_scalar_operational_model(
    model: Any,
    components: ScalarObjectiveComponents,
    config: Mapping[str, Any],
    *,
    run_case: str,
    solver_log_root: Path,
    attempt_callback: Any | None = None,
    warm_start: bool = False,
    mip_gap_override: float | None = None,
    feasibility_tolerance_override: float | None = None,
) -> tuple[ScalarSolveResult, list[ScalarSolveResult]]:
    """Solve once for six seconds and fall back only when no incumbent exists."""

    repair = config["deterministic_temporal_repair"]
    mip_gap = (
        float(repair["runtime_mip_gap"])
        if mip_gap_override is None
        else float(mip_gap_override)
    )
    if mip_gap < 0.0:
        raise TemporalRepairError("Scalar solve MIP gap cannot be negative.")
    attempts: list[ScalarSolveResult] = []
    primary = _solve_scalar_attempt(
        model,
        components,
        config,
        run_case=run_case,
        attempt="primary_6s",
        time_limit_seconds=float(repair["operational_time_limit_seconds"]),
        mip_gap=mip_gap,
        solver_log_path=solver_log_root / f"{run_case}_primary_6s.log",
        fallback_used=False,
        warm_start=warm_start,
        feasibility_tolerance=feasibility_tolerance_override,
    )
    attempts.append(primary)
    if attempt_callback is not None:
        attempt_callback(primary)
    if primary.status == "proven_infeasible":
        raise TemporalPhysicalInfeasibility(
            f"{run_case} is solver-proven infeasible under the scalar contract."
        )
    if primary.feasible_incumbent:
        return primary, attempts
    fallback = _solve_scalar_attempt(
        model,
        components,
        config,
        run_case=run_case,
        attempt="fallback_60s",
        time_limit_seconds=float(repair["operational_fallback_time_limit_seconds"]),
        mip_gap=mip_gap,
        solver_log_path=solver_log_root / f"{run_case}_fallback_60s.log",
        fallback_used=True,
        warm_start=False,
        dual_reductions=False,
        feasibility_tolerance=feasibility_tolerance_override,
    )
    attempts.append(fallback)
    if attempt_callback is not None:
        attempt_callback(fallback)
    if fallback.status == "proven_infeasible":
        raise TemporalPhysicalInfeasibility(
            f"{run_case} is solver-proven infeasible in the scalar fallback."
        )
    if not fallback.feasible_incumbent:
        raise TemporalRepairError(
            f"{run_case} remains unknown_under_time_limit after the 60-s fallback."
        )
    return fallback, attempts


def solve_feasibility_only(
    model: Any,
    config: Mapping[str, Any],
    *,
    run_case: str,
) -> list[dict[str, Any]]:
    record = _solve_zero_objective_feasibility(
        model,
        config,
        run_case=run_case,
    )
    if not record["feasible_incumbent"]:
        error = TemporalPhysicalInfeasibility(
            f"{run_case} is infeasible with physical optimum fixed at zero."
        )
        error.solver_record = record
        raise error
    return [record]


def price_profile(config: Mapping[str, Any], profile: str) -> tuple[float, ...]:
    row = config["deterministic_temporal_repair"]["price_profiles_eur_per_mwh"][profile]
    return tuple([float(row["first_12h"])] * 48 + [float(row["second_12h"])] * 48)


def _series(model: Any, component: str, steps: int) -> list[float]:
    return [_component_value(model, component, q) for q in range(steps)]


def temporal_kpi_rows(
    model: Any,
    state: SteelRollingState,
    config: Mapping[str, Any],
    *,
    run_case: str,
) -> list[dict[str, Any]]:
    steps = int(getattr(model, "temporal_objective_execution_steps", 96))
    dt = float(model.time_step_hours)
    ranges = rate_ranges_from_config(config)
    rows: list[dict[str, Any]] = []

    def add(entity: str, metric: str, observed: float, unit: str, status: str = "observed") -> None:
        rows.append(
            {
                "run_case": run_case,
                "window": f"executed_D_{steps / 4:g}h",
                "entity": entity,
                "metric": metric,
                "value": float(observed),
                "unit": unit,
                "status": status,
            }
        )

    for asset in CONTINUOUS_ASSETS:
        rates = [item / dt for item in _series(model, asset, steps)]
        on = _series(model, ASSET_ON_COMPONENTS[asset], steps)
        jumps = [abs(rates[0] - state.last_continuous_rate_t_h[asset])] + [
            abs(rates[q] - rates[q - 1]) for q in range(1, steps)
        ]
        lower, upper = ranges[asset]
        add(asset, "off_interval_count", sum(item < 0.5 for item in on), "interval")
        add(asset, "minimum_rate", min(rates), "t/h")
        add(asset, "maximum_rate", max(rates), "t/h")
        add(asset, "minimum_bound_hits", sum(abs(item - lower) <= 1e-5 for item in rates), "interval")
        add(asset, "maximum_bound_hits", sum(abs(item - upper) <= 1e-5 for item in rates), "interval")
        add(asset, "normalized_total_variation", sum(jumps) / (upper - lower), "range")
        add(asset, "largest_rate_jump_including_day_boundary", max(jumps), "t/h")

    pefa = config["deterministic_temporal_repair"]["plant_dynamics"]["pefa"]
    pefa_rates = [item / dt for item in _series(model, "pefa_pellet_output_t", steps)]
    pefa_jumps = [abs(pefa_rates[0] - float(state.pefa_last_output_t_h))] + [
        abs(pefa_rates[q] - pefa_rates[q - 1]) for q in range(1, steps)
    ]
    pefa_lower = float(pefa["minimum_output_t_h"])
    pefa_upper = float(pefa["maximum_output_t_h"])
    add("pelletizing_plant", "minimum_rate", min(pefa_rates), "t/h")
    add("pelletizing_plant", "maximum_rate", max(pefa_rates), "t/h")
    add(
        "pelletizing_plant",
        "normalized_total_variation",
        sum(pefa_jumps) / (pefa_upper - pefa_lower),
        "range",
    )
    add(
        "pelletizing_plant",
        "largest_rate_jump_including_day_boundary",
        max(pefa_jumps),
        "t/h",
    )

    for inventory in INVENTORY_COMPONENTS:
        observed = _series(model, inventory, steps)
        add(inventory, "start_after_first_interval", observed[0], "t")
        add(inventory, "executed_day_end", observed[-1], "t")
        add(inventory, "minimum", min(observed), "t")
        add(inventory, "maximum", max(observed), "t")
    pellet_inventory = _series(model, "pellet_inventory", steps)
    add("pellet_inventory", "start_after_first_interval", pellet_inventory[0], "t")
    add("pellet_inventory", "executed_day_end", pellet_inventory[-1], "t")
    add("pellet_inventory", "minimum", min(pellet_inventory), "t")
    add("pellet_inventory", "maximum", max(pellet_inventory), "t")
    for asset, component_name in (
        ("basic_oxygen_furnace", "basic_oxygen_furnace"),
        ("hot_strip_mill", "hot_strip_mill"),
        ("direct_sheet_plant", "dsp_final_product_output"),
    ):
        rates = [item / dt for item in _series(model, component_name, steps)]
        change_count = sum(
            abs(rates[q] - rates[q - 1]) > 1e-6 for q in range(1, steps)
        )
        free_qh_oscillation = change_count == steps - 1
        add(
            asset,
            "quarterhour_rate_change_count",
            change_count,
            "transition",
            "needs_bounded_fix" if free_qh_oscillation else "pass",
        )
        add(
            asset,
            "largest_quarterhour_rate_jump",
            max(abs(rates[q] - rates[q - 1]) for q in range(1, steps)),
            "t/h",
            "needs_bounded_fix" if free_qh_oscillation else "pass",
        )
    starts = _series(model, "eaf_heat_start", steps)
    taps = _series(model, "eaf_tap", steps)
    add("eaf", "heat_starts", sum(starts), "count")
    add("eaf", "heat_taps", sum(taps), "count")
    add("eaf", "unfinished_heats", starts[-2] + starts[-1], "count")
    vn25 = [item / dt for item in _series(model, "vn25_electricity_mwh", steps)]
    vn25_jumps = [abs(vn25[0] - float(state.last_vn25_output_mw))] + [
        abs(vn25[q] - vn25[q - 1]) for q in range(1, steps)
    ]
    add("vn25", "minimum_output", min(vn25), "MW")
    add("vn25", "maximum_output", max(vn25), "MW")
    add("vn25", "largest_ramp_including_day_boundary", max(vn25_jumps), "MW")
    for component, unit in (
        ("vn25_wag_fuel_mwh", "MWh_LHV"),
        ("ng_to_vn25_mwh", "MWh_LHV"),
        ("ij01_wag_fuel_mwh", "MWh_LHV"),
        ("ng_to_ij01_mwh", "MWh_LHV"),
        ("bfg_flared", "MWh_LHV"),
        ("cog_flared", "MWh_LHV"),
        ("bofg_flared", "MWh_LHV"),
        ("net_grid_import_mwh", "MWh_e"),
        ("final_product_output", "t"),
        ("eaf_liquid_steel_output", "t"),
        ("bof_crude_steel_output", "t"),
    ):
        add("aggregate", f"total_{component}", sum(_series(model, component, steps)), unit)
    return rows


def energy_audit_rows(model: Any, *, run_case: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    steps = int(getattr(model, "temporal_objective_execution_steps", 96))
    dt = float(model.time_step_hours)
    lhv_mj_per_nm3, _ = load_governed_wag_factor_maps()
    volume_cap_nm3 = float(value(model.vn25_gas_volume_cap[0].upper))
    for q in range(steps):
        vn25_mw = _component_value(model, "vn25_electricity_mwh", q) / dt
        ng = _component_value(model, "ng_to_vn25_mwh", q)
        carrier_flare = {
            carrier: _component_value(model, f"{carrier.lower()}_flared", q)
            for carrier in ("BFG", "COG", "BOFG")
        }
        wag_to_vn25 = {
            carrier: _component_value(model, f"{carrier.lower()}_to_vn25", q)
            for carrier in ("BFG", "COG", "BOFG")
        }
        used_volume_nm3 = sum(
            wag_to_vn25[carrier] / (lhv_mj_per_nm3[carrier] / 3_600.0)
            for carrier in wag_to_vn25
        )
        volume_slack_nm3 = max(0.0, volume_cap_nm3 - used_volume_nm3)
        deployable_flared_wag_mwh = sum(
            min(
                carrier_flare[carrier],
                volume_slack_nm3 * (lhv_mj_per_nm3[carrier] / 3_600.0),
            )
            for carrier in carrier_flare
        )
        avoidable = (
            ng > 1e-6
            and deployable_flared_wag_mwh > 1e-6
            and vn25_mw < 350.0 - 1e-6
        )
        rows.append(
            {
                "run_case": run_case,
                "interval": q,
                "vn25_output_mw": vn25_mw,
                "vn25_ramp_from_previous_mw": (
                    "" if q == 0 else vn25_mw - rows[-1]["vn25_output_mw"]
                ),
                "vn25_wag_mwh_lhv": _component_value(model, "vn25_wag_fuel_mwh", q),
                "vn25_named_ng_mwh_lhv": ng,
                "ij01_wag_mwh_lhv": _component_value(model, "ij01_wag_fuel_mwh", q),
                "ij01_named_ng_mwh_lhv": _component_value(model, "ng_to_ij01_mwh", q),
                "bfg_flare_mwh_lhv": carrier_flare["BFG"],
                "cog_flare_mwh_lhv": carrier_flare["COG"],
                "bofg_flare_mwh_lhv": carrier_flare["BOFG"],
                "vn25_wag_volume_slack_nm3": volume_slack_nm3,
                "deployable_flared_wag_mwh_lhv": deployable_flared_wag_mwh,
                "avoidable_flare_plus_vn25_ng": avoidable,
                "status": "fail" if avoidable else "pass",
            }
        )
    return rows


def _execution_totals(model: Any, execution_steps: int) -> dict[str, float]:
    """Extract solved executed-block quantities without adding residual plugs."""

    component_names = (
        "bfg_generated", "cog_generated", "bofg_generated",
        "bfg_flared", "cog_flared", "bofg_flared",
        "bfg_to_vn25", "cog_to_vn25", "bofg_to_vn25",
        "ng_to_vn25_mwh", "ng_to_ij01_mwh",
        "drp_named_ng_mwh", "eaf_named_ng_mwh", "ng_to_hsm_mwh",
        "ng_to_pefa_malerij_mwh", "ng_to_pefa_branderij_mwh",
        "ng_to_boiler_mwh", "full_site_energy_bridge_named_ng_mwh",
        "site_baseload_ng_mwh", "total_named_ng_procurement_mwh",
        "c1_existing_ironmaking_ng_service_mwh",
        "c1_existing_downstream_ng_service_mwh",
        "c1_explicit_downstream_named_ng_mwh",
        "represented_gross_electricity_before_background_mwh",
        "gross_total_electricity_mwh", "gross_grid_import_mwh",
        "gross_grid_export_mwh", "net_grid_exchange_mwh",
        "total_generator_electricity_mwh", "generator_total_fuel_mwh",
        "generator_fuel_identity_residual_mwh",
        "gross_site_electricity_identity_residual_mwh",
        "bfg_balance_residual", "cog_balance_residual", "bofg_balance_residual",
        "bfg_explicit_combustion_co2_t", "cog_explicit_combustion_co2_t",
        "bofg_explicit_combustion_co2_t", "explicit_ng_combustion_co2_t",
        "explicit_direct_co2_t", "total_direct_co2_reporting_t",
        "sinter_output", "bf_hot_iron_output", "bof_crude_steel_output",
        "eaf_liquid_steel_output", "drp_dri_output", "drp_pellet_input",
        "coking_plant_1", "sintering_plant", "bf_pci_input_t",
        "c1_adjusted_coking_coal_input_t", "c1_adjusted_pci_input_t",
        "c1_total_coal_input_t", "c1_additional_coal_completion_t",
        "pefa_iron_ore_input_t", "hot_strip_mill",
        "dsp_final_product_output",
        "bof_scrap_supply_t", "eaf_scrap_supply_t",
        "external_scrap_to_bof_t", "external_scrap_to_eaf_t",
        "internal_scrap_to_bof_t", "internal_scrap_to_eaf_t",
        "imported_hbi_to_eaf_t", "imported_slab_to_hsm", "final_product_output",
        "steam_production_mwh", "steam_15bar_supply_t",
        "steam_15bar_demand_t", "steam_15bar_spill_t",
    )
    return {
        name: sum(_component_value(model, name, q) for q in range(execution_steps))
        for name in component_names
    }


def _sum_execution_totals(items: Sequence[Mapping[str, float]]) -> dict[str, float]:
    keys = {key for item in items for key in item}
    return {key: sum(float(item.get(key, 0.0)) for item in items) for key in keys}


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _last_accepted_annual_values() -> dict[str, float]:
    """Evaluate, rather than copy, common metrics from accepted Phase-5E rows."""

    path = LAST_ACCEPTED_ANNUAL_BASELINE_ROOT / "dynamic_period_metrics.csv"
    rows = [
        row for row in _csv_rows(path)
        if row.get("configuration_id") == C1_CONFIGURATION
    ]
    if not rows or any(int(row["executed_hours"]) <= 0 for row in rows):
        raise TemporalRepairError("Accepted Phase-5E C1 baseline metrics are unavailable.")

    def average(values: Sequence[float]) -> float:
        return sum(values) / len(values)

    return {
        "site_final_product": average([
            float(row["final_product_t"]) * HOURS_PER_YEAR / int(row["executed_hours"])
            for row in rows
        ]),
        "represented_named_ng_total": average([
            float(row["optimizer_boundary_ng_pj_y_annual_equivalent"])
            for row in rows
        ]),
        "total_wag_generation": average([
            float(row["total_wag_pj_y_annual_equivalent"]) for row in rows
        ]),
        "gross_grid_import": average([
            float(row["gross_grid_import_mwh"])
            * HOURS_PER_YEAR
            / int(row["executed_hours"])
            * MWH_TO_PJ
            for row in rows
        ]),
        "generator_output": average([
            float(row["generator_electricity_mwh"])
            * HOURS_PER_YEAR
            / int(row["executed_hours"])
            * MWH_TO_PJ
            for row in rows
        ]),
        "dri_output": average([
            float(row["dri_output_t"]) * HOURS_PER_YEAR / int(row["executed_hours"])
            for row in rows
        ]),
    }


def _phase5e_static_anchor_gate() -> dict[str, Any]:
    source_rows = load_source_contract(ANNUAL_SERVICE_CONTRACT_PATH)
    phase5e = yaml.safe_load(PHASE5E_CONFIG_PATH.read_text(encoding="utf-8"))["phase5e"]
    gates = phase5e["gates"]
    comparisons = annual_anchor_comparisons(
        source_rows, float(gates["primary_anchor_relative_tolerance"])
    )
    coverage = carrier_coverage(
        source_rows,
        float(gates["minimum_named_share_per_carrier"]),
        float(gates["maximum_unallocated_share_per_carrier"]),
    )
    generators = generator_balances(
        source_rows,
        gates["secondary_wag_electricity_anchors_twh_y"],
        float(gates["primary_anchor_relative_tolerance"]),
    )
    return {
        "annual_anchor_comparison_pass": all(row["status"] == "pass" for row in comparisons),
        "carrier_coverage_pass": all(row["status"] == "pass" for row in coverage),
        "generator_source_identity_pass": all(row["status"] == "pass" for row in generators),
        "comparison_count": len(comparisons),
        "coverage_count": len(coverage),
        "generator_balance_count": len(generators),
        "annual_anchors_enter_constraints": False,
        "annual_anchors_enter_objectives": False,
        "annual_validation_mip_gap": 0.0,
    }


def annual_operational_anchor_rows(
    totals: Mapping[str, float],
    *,
    evaluation_id: str,
    executed_hours: int,
    period_classification: str,
    calendar_coverage: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Annualise accepted temporal decisions for reporting-only anchor checks."""

    if int(executed_hours) <= 0:
        raise TemporalRepairError("Annual diagnostics require positive executed hours.")
    factor = HOURS_PER_YEAR / float(executed_hours)
    service = {
        str(row["record_id"]): row
        for row in load_source_contract(ANNUAL_SERVICE_CONTRACT_PATH)
        if row["configuration"] == "C1"
    }
    register = {
        row["anchor_id"]: row for row in _csv_rows(ANCHOR_REGISTER_PATH)
    }
    rows: list[dict[str, Any]] = []

    def service_anchor(record_id: str) -> tuple[float, str, str]:
        row = service[record_id]
        return float(row["value"]), str(row["unit"]), str(row["source_locator"])

    def register_anchor(anchor_id: str) -> tuple[float, str, str]:
        row = register[anchor_id]
        return (
            float(row["converted_value"]),
            str(row["converted_unit"]),
            str(row["source_locator"]),
        )

    def add(
        metric_id: str,
        metric: str,
        model_value: float,
        unit: str,
        *,
        source_value: float | str = "",
        source_unit: str = "",
        source_locator: str = "",
        coverage: str,
        boundary: str,
        comparability: str,
        family: str,
        caveat: str = "",
    ) -> None:
        absolute = ""
        relative = ""
        if source_value != "":
            absolute = float(model_value) - float(source_value)
            relative = (
                absolute / abs(float(source_value))
                if abs(float(source_value)) > PHYSICAL_TOLERANCE
                else (0.0 if abs(absolute) <= PHYSICAL_TOLERANCE else "")
            )
        rows.append(
            {
                "evaluation_id": evaluation_id,
                "period_classification": period_classification,
                "executed_hours": int(executed_hours),
                "calendar_coverage": calendar_coverage,
                "annualisation_denominator_hours": int(executed_hours),
                "metric_id": metric_id,
                "metric": metric,
                "family": family,
                "source_value": source_value,
                "source_unit": source_unit,
                "model_annual_equivalent": float(model_value),
                "model_unit": unit,
                "absolute_deviation": absolute,
                "relative_deviation": relative,
                "model_coverage": coverage,
                "boundary_denominator": boundary,
                "comparability": comparability,
                "source_locator": source_locator,
                "caveat": caveat,
            }
        )

    def pj(field: str) -> float:
        return float(totals.get(field, 0.0)) * factor * MWH_TO_PJ

    def tonnes(field: str) -> float:
        return float(totals.get(field, 0.0)) * factor

    def mt(field: str) -> float:
        return tonnes(field) / 1_000_000.0

    wag_source_ids = {"BFG": "c1_wag_bfg", "COG": "c1_wag_cog", "BOFG": "c1_wag_bofg"}
    generator_source_ids = {
        "BFG": "c1_generator_fuel_bfg",
        "COG": "c1_generator_fuel_cog",
        "BOFG": "c1_generator_fuel_bofg",
    }
    for carrier in ("BFG", "COG", "BOFG"):
        lower = carrier.lower()
        source_value, source_unit, locator = service_anchor(wag_source_ids[carrier])
        generated = pj(f"{lower}_generated")
        flared = pj(f"{lower}_flared")
        generator_fuel = pj(f"{lower}_to_vn25")
        used = generated - flared
        add(f"{lower}_production", f"{carrier} production", generated, "PJ/y", source_value=source_value, source_unit=source_unit, source_locator=locator, coverage="carrier_explicit_represented_boundary", boundary="represented C1 WAG carrier", comparability="comparable", family="WAG")
        add(f"{lower}_consumption", f"{carrier} total represented use", used, "PJ/y", coverage="carrier_explicit_represented_boundary", boundary="represented C1 named sinks", comparability="not_comparable", family="WAG")
        fuel_source, fuel_unit, fuel_locator = service_anchor(generator_source_ids[carrier])
        add(f"{lower}_generator_fuel", f"{carrier} to VN25", generator_fuel, "PJ/y", source_value=fuel_source, source_unit=fuel_unit, source_locator=fuel_locator, coverage="VN25 carrier-explicit", boundary="VN25 fuel input", comparability="comparable", family="generator")
        add(f"{lower}_flare", f"{carrier} flare", flared, "PJ/y", coverage="carrier_explicit_represented_boundary", boundary="represented flare", comparability="not_comparable", family="WAG")
        add(f"{lower}_fuel_explicit_co2", f"{carrier} fuel-explicit CO2", mt(f"{lower}_explicit_combustion_co2_t"), "MtCO2/y", coverage="fuel_explicit_carrier", boundary="represented oxidation sinks including flare", comparability="not_comparable", family="CO2")

    total_wag_source, total_wag_unit, total_wag_locator = service_anchor("c1_wag_total")
    total_wag = sum(pj(f"{carrier}_generated") for carrier in ("bfg", "cog", "bofg"))
    add("total_wag_generation", "Total BFG+COG+BOFG production", total_wag, "PJ/y", source_value=total_wag_source, source_unit=total_wag_unit, source_locator=total_wag_locator, coverage="carrier_explicit_represented_boundary", boundary="sum of three represented carriers", comparability="comparable", family="WAG")

    ng_components: dict[str, tuple[str, str | None]] = {
        "drp_named_ng": ("drp_named_ng_mwh", "c1_ng_dri"),
        "eaf_named_ng": ("eaf_named_ng_mwh", "c1_ng_eaf"),
        "vn25_named_ng": ("ng_to_vn25_mwh", "c1_ng_vattenfall"),
        "ij01_named_ng": ("ng_to_ij01_mwh", None),
    }
    service_calibrated = (
        float(totals.get("c1_existing_ironmaking_ng_service_mwh", 0.0))
        + float(totals.get("c1_existing_downstream_ng_service_mwh", 0.0))
        > PHYSICAL_TOLERANCE
    )
    if service_calibrated:
        ng_components.update(
            {
                "existing_ironmaking_named_ng": (
                    "c1_existing_ironmaking_ng_service_mwh",
                    "c1_ng_existing_ironmaking",
                ),
                "existing_downstream_named_ng": (
                    "c1_existing_downstream_ng_service_mwh",
                    "c1_ng_existing_downstream",
                ),
            }
        )
    else:
        ng_components.update(
            {
                "hsm_named_ng": ("ng_to_hsm_mwh", None),
                "pefa_malerij_named_ng": ("ng_to_pefa_malerij_mwh", None),
                "pefa_branderij_named_ng": ("ng_to_pefa_branderij_mwh", None),
                "boiler_named_ng": ("ng_to_boiler_mwh", None),
                "site_baseload_named_ng": ("site_baseload_ng_mwh", None),
            }
        )
    ng_total_mwh = float(totals.get("total_named_ng_procurement_mwh", 0.0))
    ng_co2_total_t = float(totals.get("explicit_ng_combustion_co2_t", 0.0))
    for metric_id, (field, source_id) in ng_components.items():
        kwargs: dict[str, Any] = {}
        if source_id is not None:
            source_value, source_unit, locator = service_anchor(source_id)
            kwargs = {"source_value": source_value, "source_unit": source_unit, "source_locator": locator}
        component_mwh = float(totals.get(field, 0.0))
        add(metric_id, metric_id.replace("_", " "), component_mwh * factor * MWH_TO_PJ, "PJ/y", coverage="named represented component", boundary="component fuel input", comparability="partially_comparable" if source_id else "not_comparable", family="natural_gas", **kwargs)
        component_co2 = 0.0 if ng_total_mwh <= PHYSICAL_TOLERANCE else ng_co2_total_t * component_mwh / ng_total_mwh
        add(f"{metric_id}_fuel_explicit_co2", f"{metric_id} fuel-explicit CO2", component_co2 * factor / 1_000_000.0, "MtCO2/y", coverage="fuel_explicit_named_component", boundary="represented NG oxidation", comparability="not_comparable", family="CO2")
    ng_source, ng_unit, ng_locator = service_anchor("c1_ng_total")
    represented_ng = pj("total_named_ng_procurement_mwh")
    add("represented_named_ng_total", "Total represented named NG", represented_ng, "PJ/y", source_value=ng_source, source_unit=ng_unit, source_locator=ng_locator, coverage="partial represented boundary", boundary="represented named consumers only; residual reported, never plugged", comparability="partially_comparable", family="natural_gas", caveat=f"Unrepresented full-site residual: {ng_source - represented_ng:.9f} PJ/y.")

    process_source, process_unit, process_locator = service_anchor("c1_electricity_operating_total")
    full_source, full_unit, full_locator = service_anchor("c1_electricity_total")
    process_electricity = pj("represented_gross_electricity_before_background_mwh")
    gross_electricity = pj("gross_total_electricity_mwh")
    add("process_electricity_boundary", "Represented process electricity", process_electricity, "PJ/y", source_value=process_source, source_unit=process_unit, source_locator=process_locator, coverage="represented process loads", boundary="16.2-PJ operating/process denominator", comparability="partially_comparable", family="electricity")
    add("broad_site_electricity_boundary", "Represented plus explicit site electricity", gross_electricity, "PJ/y", source_value=full_source, source_unit=full_unit, source_locator=full_locator, coverage="represented plus explicit background boundary", boundary="17.8-PJ broad site denominator", comparability="partially_comparable", family="electricity")
    add("gross_grid_import", "Gross grid import", pj("gross_grid_import_mwh"), "PJ/y", coverage="represented electricity identity", boundary="gross import", comparability="not_comparable", family="electricity")
    add("net_grid_import", "Net grid exchange", pj("net_grid_exchange_mwh"), "PJ/y", coverage="represented electricity identity", boundary="gross import minus export", comparability="not_comparable", family="electricity")
    add("internal_generation", "Internal generator output", pj("total_generator_electricity_mwh"), "PJ/y", coverage="VN25 plus IJ01 explicit", boundary="internal electricity supply", comparability="not_comparable", family="electricity")
    add("grid_export", "Grid export", pj("gross_grid_export_mwh"), "PJ/y", coverage="represented electricity identity", boundary="export", comparability="not_comparable", family="electricity")

    generator_fuel_source, generator_fuel_unit, generator_fuel_locator = service_anchor("c1_generator_fuel_total")
    generator_output_source, generator_output_unit, generator_output_locator = service_anchor("c1_generator_output")
    generator_loss_source, generator_loss_unit, generator_loss_locator = service_anchor("c1_generator_loss")
    generator_fuel = pj("generator_total_fuel_mwh")
    generator_output = pj("total_generator_electricity_mwh")
    generator_loss = generator_fuel - generator_output
    add("generator_fuel_total", "Total generator fuel", generator_fuel, "PJ/y", source_value=generator_fuel_source, source_unit=generator_fuel_unit, source_locator=generator_fuel_locator, coverage="VN25/IJ01 explicit fuel", boundary="generator fuel input", comparability="comparable", family="generator")
    add("generator_output", "Generator electricity output", generator_output, "PJ/y", source_value=generator_output_source, source_unit=generator_output_unit, source_locator=generator_output_locator, coverage="VN25/IJ01 explicit output", boundary="generator electricity output", comparability="comparable", family="generator")
    add("generator_conversion_loss", "Generator fuel minus output", generator_loss, "PJ/y", source_value=generator_loss_source, source_unit=generator_loss_unit, source_locator=generator_loss_locator, coverage="VN25/IJ01 explicit balance", boundary="fuel minus electricity", comparability="comparable", family="generator")

    scope_source, scope_unit, scope_locator = register_anchor("c1_official_scope1_8_3_missing")
    explicit_co2 = mt("explicit_direct_co2_t")
    add("fuel_explicit_co2_total", "Fuel-explicit represented CO2", explicit_co2, "MtCO2/y", source_value=scope_source, source_unit=scope_unit, source_locator=scope_locator, coverage="partial fuel-explicit boundary", boundary="not full-site Scope 1 or ETS", comparability="partially_comparable", family="CO2", caveat="8.3 MtCO2/y is validation-only; no residual is added.")
    capture_source, capture_unit, capture_locator = register_anchor("c1_drp_capture_stream_0_794912")
    drp_capture = tonnes("drp_dri_output") * 0.286 / 1_000_000.0
    add("drp_captured_co2", "DRP captured CO2 stream", drp_capture, "MtCO2/y", source_value=capture_source, source_unit=capture_unit, source_locator=capture_locator, coverage="DRP output-linked reporting stream", boundary="captured stream separate from direct emissions", comparability="partially_comparable", family="CO2")

    total_coal_t = tonnes("c1_total_coal_input_t")
    if total_coal_t <= PHYSICAL_TOLERANCE:
        total_coal_t = tonnes("coking_plant_1") + tonnes("bf_pci_input_t")
    coal_energy_pj = total_coal_t * (58.0 / 2_200_000.0)
    add("c1_total_coal_mass", "C1 total represented coal input", total_coal_t, "t/y", source_value=2_200_000.0, source_unit="t/y", source_locator="user-verified MER C1 material anchor", coverage="adjusted coking coal plus PCI", boundary="represented C1 purchased coal", comparability="partially_comparable", family="coal")
    add("c1_total_coal_energy", "C1 represented coal-energy equivalent", coal_energy_pj, "PJ/y", source_value=58.0, source_unit="PJ/y", source_locator="WD07 Tables 6.2 and 6.6", coverage="mass converted with joint MER 58-PJ/2.2-Mt denominator", boundary="represented C1 purchased coal", comparability="partially_comparable", family="coal", caveat="Diagnostic joint-anchor conversion; not a modelled carrier LHV balance.")
    add("c1_additional_coal_completion", "Additional coal versus prior represented flows", tonnes("c1_additional_coal_completion_t"), "t/y", coverage="user-authorized coal completion", boundary="external coal procurement", comparability="not_comparable", family="coal")

    material_anchors = (
        ("site_final_product", "Site final product", tonnes("final_product_output"), 6_750_000.0, "t/y", "active C5 denominator"),
        ("sinter_output", "Sinter output", tonnes("sinter_output"), 2_800_000.0, "t/y", "C1 configuration anchor"),
        ("hot_metal_output", "BF6 hot metal", tonnes("bf_hot_iron_output"), 2_800_000.0, "t/y", "C1 configuration anchor"),
        ("bof_liquid_steel", "BOF liquid steel", tonnes("bof_crude_steel_output"), 3_400_000.0, "t/y", "retained BOF route"),
        ("eaf_liquid_steel", "EAF liquid steel", tonnes("eaf_liquid_steel_output"), ANNUAL_EAF_ROUTE_T, "t/y", "active reconciled EAF route"),
        ("dri_output", "DRP DRI output", tonnes("drp_dri_output"), 2_800_000.0, "t/y", "MER DRP central"),
        ("drp_pellet_input", "DRP pellet input", tonnes("drp_pellet_input"), 2_800_000.0 / 0.74, "t/y", "source-to-equation 0.74 yield"),
        ("bof_scrap", "BOF scrap input", tonnes("bof_scrap_supply_t"), 1_000_000.0, "t/y", "BOF recipe anchor"),
        ("eaf_scrap", "EAF scrap input", tonnes("eaf_scrap_supply_t"), 900_000.0, "t/y", "EAF recipe anchor"),
        ("site_scrap", "Total site scrap input", tonnes("bof_scrap_supply_t") + tonnes("eaf_scrap_supply_t"), 1_900_000.0, "t/y", "site availability cap"),
        ("hbi_import", "Imported HBI", tonnes("imported_hbi_to_eaf_t"), 0.0, "t/y", "base HBI contract"),
        ("imported_slab", "Imported slab", tonnes("imported_slab_to_hsm"), 600_000.0, "t/y", "external slab cap"),
    )
    for metric_id, metric, model_value, source_value, unit, boundary in material_anchors:
        add(metric_id, metric, model_value, unit, source_value=source_value, source_unit=unit, source_locator="source-to-equation gate / governed route contract", coverage="represented material route", boundary=boundary, comparability="partially_comparable", family="material", caveat="Scenario-definition/cap rows are reported but are not independent validation targets.")

    raw_identity_residuals = {
        "BFG": abs(float(totals.get("bfg_balance_residual", 0.0))),
        "COG": abs(float(totals.get("cog_balance_residual", 0.0))),
        "BOFG": abs(float(totals.get("bofg_balance_residual", 0.0))),
        "generator_fuel": abs(float(totals.get("generator_fuel_identity_residual_mwh", 0.0))),
        "electricity": abs(float(totals.get("gross_site_electricity_identity_residual_mwh", 0.0))),
        "co2_double_count": abs(
            float(totals.get("explicit_direct_co2_t", 0.0))
            - float(totals.get("bfg_explicit_combustion_co2_t", 0.0))
            - float(totals.get("cog_explicit_combustion_co2_t", 0.0))
            - float(totals.get("bofg_explicit_combustion_co2_t", 0.0))
            - float(totals.get("explicit_ng_combustion_co2_t", 0.0))
        ),
    }
    identity_pass = max(raw_identity_residuals.values(), default=0.0) <= 1e-5
    return rows, {
        "evaluation_id": evaluation_id,
        "period_classification": period_classification,
        "executed_hours": int(executed_hours),
        "calendar_coverage": calendar_coverage,
        "identity_residuals_unannualised": raw_identity_residuals,
        "identity_gate_pass": identity_pass,
        "partial_boundaries_do_not_fail_on_full_site_gap": True,
        "annual_anchors_enter_constraints": False,
        "annual_anchors_enter_objectives": False,
    }


def annual_anchor_delta_rows(
    result_rows: Sequence[Mapping[str, Any]],
    *,
    baseline_id: str,
    baseline_values: Mapping[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in result_rows:
        metric_id = str(result["metric_id"])
        baseline = baseline_values.get(metric_id)
        current = float(result["model_annual_equivalent"])
        delta = "" if baseline is None else current - float(baseline)
        relative = (
            ""
            if baseline is None or abs(float(baseline)) <= PHYSICAL_TOLERANCE
            else float(delta) / abs(float(baseline))
        )
        rows.append(
            {
                "evaluation_id": result["evaluation_id"],
                "metric_id": metric_id,
                "baseline_id": baseline_id,
                "last_accepted_value": "" if baseline is None else baseline,
                "current_value": current,
                "unit": result["model_unit"],
                "absolute_delta": delta,
                "relative_delta": relative,
                "comparison_status": (
                    "not_available_no_comparable_baseline"
                    if baseline is None
                    else "compared"
                ),
            }
        )
    return rows


def administrative_carbon_balance_rows(
    anchor_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Reconcile MER source classes without creating a physical CO2 plug."""

    values = {
        str(row["metric_id"]): float(row["model_annual_equivalent"])
        for row in anchor_rows
    }
    wag_co2 = sum(
        values.get(f"{carrier}_fuel_explicit_co2", 0.0)
        for carrier in ("bfg", "cog", "bofg")
    )
    total_explicit = values.get("fuel_explicit_co2_total", 0.0)
    ng_co2 = total_explicit - wag_co2
    categories = (
        ("coal_and_other_carbon", 5.5, wag_co2, "WAG oxidation only; upstream and non-WAG process carbon absent"),
        ("natural_gas", 2.6, ng_co2, "all represented named-NG oxidation"),
        ("fluxes", 0.2, 0.0, "flux chemistry not represented"),
        ("full_site_scope1", 8.3, total_explicit, "validation total; residual remains reporting-only"),
    )
    return [
        {
            "evaluation_id": "D3_causal_week",
            "source_class": source_class,
            "source_mtco2_y": source,
            "represented_mtco2_y": represented,
            "coverage_residual_mtco2_y": source - represented,
            "coverage_fraction": represented / source if source else "",
            "accounting_status": "reporting_only_partial_carbon_reconciliation",
            "physical_balance_closed": False,
            "residual_enters_model": False,
            "notes": notes,
        }
        for source_class, source, represented, notes in categories
    ]


def unexpected_anchor_worsening(
    result_rows: Sequence[Mapping[str, Any]],
    baseline_values: Mapping[str, float],
    *,
    relative_tolerance: float,
) -> list[dict[str, Any]]:
    """Return comparable anchors whose source gap worsened beyond tolerance."""

    failures: list[dict[str, Any]] = []
    for row in result_rows:
        metric_id = str(row["metric_id"])
        if (
            row["comparability"] == "not_comparable"
            or row["source_value"] == ""
            or metric_id not in baseline_values
        ):
            continue
        source = float(row["source_value"])
        baseline_gap = abs(float(baseline_values[metric_id]) - source)
        current_gap = abs(float(row["model_annual_equivalent"]) - source)
        allowance = max(abs(source) * float(relative_tolerance), PHYSICAL_TOLERANCE)
        if current_gap > baseline_gap + allowance:
            failures.append(
                {
                    "metric_id": metric_id,
                    "baseline_gap": baseline_gap,
                    "current_gap": current_gap,
                    "allowance": allowance,
                }
            )
    return failures


def material_annual_drift(
    result_rows: Sequence[Mapping[str, Any]],
    reference_values: Mapping[str, float],
    *,
    relative_tolerance: float,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in result_rows:
        metric_id = str(row["metric_id"])
        if metric_id not in reference_values:
            continue
        reference = float(reference_values[metric_id])
        current = float(row["model_annual_equivalent"])
        scale = max(abs(reference), 1.0)
        relative = abs(current - reference) / scale
        if relative > float(relative_tolerance):
            failures.append(
                {
                    "metric_id": metric_id,
                    "reference_value": reference,
                    "current_value": current,
                    "relative_drift": relative,
                    "tolerance": relative_tolerance,
                }
            )
    return failures


def advance_temporal_state(
    context: SteelPhysicalContext,
    model: Any,
    state: SteelRollingState,
    *,
    last_timestamp_utc: str,
) -> SteelRollingState:
    steps = context.time_grid.execution_steps
    last = steps - 1
    dt = context.time_grid.time_step_hours
    produced = sum(_component_value(model, "final_product_output", q) for q in range(steps))
    taps = round_half_up(sum(_component_value(model, "eaf_tap", q) for q in range(steps)))
    route_increment: dict[str, float] = {}
    for q in range(steps):
        for key, amount in _route_progress_values(context, model, C1_CONFIGURATION, q).items():
            route_increment[key] = route_increment.get(key, 0.0) + float(amount)
    scrap_increment = {
        field: sum(_component_value(model, field, q) for q in range(steps))
        for field in (
            "external_scrap_to_bof_t",
            "external_scrap_to_eaf_t",
            "internal_scrap_to_bof_t",
            "internal_scrap_to_eaf_t",
        )
    }
    sifa_window = int(getattr(model, "sifa_minimum_direction_intervals", 1))
    sifa_direction = str(state.sifa_trend_direction)
    sifa_cooldown = max(
        0, int(state.sifa_trend_cooldown_intervals) - int(steps)
    )
    if hasattr(model, "sifa_up_direction"):
        last_movement: tuple[int, str] | None = None
        for q in range(steps):
            if _component_value(model, "sifa_up_direction", q) > 0.5:
                last_movement = (q, "up")
            elif _component_value(model, "sifa_down_direction", q) > 0.5:
                last_movement = (q, "down")
        if last_movement is None:
            if sifa_cooldown == 0:
                sifa_direction = "flat"
        else:
            movement_index, sifa_direction = last_movement
            sifa_cooldown = max(0, sifa_window - (steps - movement_index))
    next_state = SteelRollingState(
        episode_id=state.episode_id,
        configuration_id=state.configuration_id,
        inventory_overrides=_inventory_overrides(model, C1_CONFIGURATION, last),
        cumulative_production_t=float(state.cumulative_production_t) + produced,
        executed_hours=int(state.executed_hours) + context.time_grid.execution_hours,
        executed_intervals=int(state.executed_intervals) + steps,
        last_executed_timestamp_utc=str(last_timestamp_utc),
        cumulative_route_progress_t={
            key: float(state.cumulative_route_progress_t.get(key, 0.0))
            + float(route_increment.get(key, 0.0))
            for key in set(state.cumulative_route_progress_t) | set(route_increment)
        },
        eaf_start_lag1=round_half_up(_component_value(model, "eaf_heat_start", last)),
        eaf_start_lag2=round_half_up(_component_value(model, "eaf_heat_start", last - 1)),
        drp_last_pellet_input_t=_component_value(model, "drp_pellet_input", last),
        temporal_contract_version=TEMPORAL_CONTRACT_VERSION,
        calendar_contract_version=CALENDAR_CONTRACT_VERSION,
        last_continuous_rate_t_h={
            asset: canonicalize_state_rate(
                _component_value(model, asset, last) / dt,
                *DEFAULT_RATE_RANGES_T_H[asset],
            )
            for asset in CONTINUOUS_ASSETS
        },
        last_vn25_output_mw=_component_value(model, "vn25_electricity_mwh", last) / dt,
        eaf_quota_period_id=state.eaf_quota_period_id,
        eaf_quota_target_taps=state.eaf_quota_target_taps,
        eaf_quota_completed_taps=int(state.eaf_quota_completed_taps) + taps,
        cumulative_external_scrap_to_bof_t=(
            float(state.cumulative_external_scrap_to_bof_t)
            + scrap_increment["external_scrap_to_bof_t"]
        ),
        cumulative_external_scrap_to_eaf_t=(
            float(state.cumulative_external_scrap_to_eaf_t)
            + scrap_increment["external_scrap_to_eaf_t"]
        ),
        cumulative_internal_scrap_to_bof_t=(
            float(state.cumulative_internal_scrap_to_bof_t)
            + scrap_increment["internal_scrap_to_bof_t"]
        ),
        cumulative_internal_scrap_to_eaf_t=(
            float(state.cumulative_internal_scrap_to_eaf_t)
            + scrap_increment["internal_scrap_to_eaf_t"]
        ),
        sifa_trend_direction=sifa_direction,
        sifa_trend_cooldown_intervals=sifa_cooldown,
        pefa_last_output_t_h=(
            _component_value(model, "pefa_pellet_output_t", last) / dt
        ),
        pellet_inventory_t=_component_value(model, "pellet_inventory", last),
        hsm_last_input_t_h=(
            _component_value(model, "hot_strip_mill", last) / dt
        ),
    )
    validate_temporal_state(next_state, {
        "deterministic_temporal_repair": {
            "continuous_must_run_assets": {
                asset: {"minimum_rate_t_h": bounds[0], "maximum_rate_t_h": bounds[1]}
                for asset, bounds in DEFAULT_RATE_RANGES_T_H.items()
            },
            "scrap_origin_contract": {
                "annual_external_scrap_cap_t_y": 1_300_000.0,
                "annual_internal_scrap_cap_t_y": 600_000.0,
                "annual_site_scrap_cap_t_y": 1_900_000.0,
            },
            "plant_dynamics": {
                "sifa": {"minimum_direction_intervals": sifa_window},
                "pefa": {
                    "minimum_output_t_h": 540.0,
                    "maximum_output_t_h": 595.0,
                },
            },
        }
    })
    return next_state


def state_handoff_row(
    before: SteelRollingState,
    after: SteelRollingState,
    *,
    run_case: str,
) -> dict[str, Any]:
    before_payload = before.snapshot()
    after_payload = after.snapshot()
    return {
        "run_case": run_case,
        "temporal_contract_version": after.temporal_contract_version,
        "state_before_sha256": _canonical_json_sha256(before_payload),
        "state_after_sha256": _canonical_json_sha256(after_payload),
        "exported_interval_role": "last_executed_D_interval_only",
        "executed_hours_before": before.executed_hours,
        "executed_hours_after": after.executed_hours,
        "eaf_taps_before": before.eaf_quota_completed_taps,
        "eaf_taps_after": after.eaf_quota_completed_taps,
        "state_after_json": json.dumps(after_payload, sort_keys=True),
        "status": "pass",
    }


def objective_incentive_ledger() -> list[dict[str, Any]]:
    return [
        {"tier": "hard_constraint", "term": "recoverable_final_product_band_deviation", "sign": "=", "coefficient": 0.0, "unit": "t", "active_intervals": "executed_D", "preservation_tolerance": PHYSICAL_TOLERANCE, "methodological_status": "hard_zero_constraint"},
        {"tier": "scalar_objective", "term": "represented_procurement_cost_D", "sign": "+", "coefficient": 1.0, "unit": "EUR", "active_intervals": "executed_D_only", "preservation_tolerance": "solver_optimality_envelope", "methodological_status": "active_economic"},
        {"tier": "scalar_objective", "term": "remaining_taps_after_D", "sign": "+", "coefficient": "calibrated_continuation_eur_per_heat", "unit": "EUR", "active_intervals": "executed_state_only", "preservation_tolerance": "solver_optimality_envelope", "methodological_status": "active_causal_continuation"},
        {"tier": "reporting_only", "term": "normalized_total_variation", "sign": "none", "coefficient": 0.0, "unit": "throughput_range", "active_intervals": "executed_D_plus_prior_executed_rate", "preservation_tolerance": "not_applicable", "methodological_status": "reporting_kpi"},
        {"tier": "reporting_only", "term": "absolute_daily_tap_deviation_from_quota_neutral", "sign": "none", "coefficient": 0.0, "unit": "tap", "active_intervals": "executed_D", "preservation_tolerance": "not_applicable", "methodological_status": "reporting_kpi"},
        {"tier": "excluded", "term": "inventory_levels_process_on_hours_eaf_starts_timestamp_weights_flare_penalty_annual_anchors", "sign": "none", "coefficient": 0.0, "unit": "none", "active_intervals": "none", "preservation_tolerance": 0.0, "methodological_status": "not_in_objective"},
    ]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _empty_output_rows() -> dict[str, list[dict[str, Any]]]:
    return {
        "temporal_kpis": [],
        "state_handoff_audit": [],
        "eaf_heat_ledger": [],
        "route_progress": [],
        "energy_wag_generator_audit": [],
        "baseline_delta": [],
        "heat_count_certification": [],
        "annual_operational_anchor_results": [],
        "administrative_carbon_balance": [],
        "annual_anchor_delta_vs_last_accepted": [],
        "annual_operational_anchor_gate": [],
        "scalar_objective_components": [],
        "continuation_calibration": [],
        "solver_attempts": [],
    }


def _output_schemas() -> dict[str, tuple[str, ...]]:
    return {
        "temporal_kpis": ("run_case", "window", "entity", "metric", "value", "unit", "status"),
        "state_handoff_audit": ("run_case", "temporal_contract_version", "state_before_sha256", "state_after_sha256", "exported_interval_role", "executed_hours_before", "executed_hours_after", "eaf_taps_before", "eaf_taps_after", "state_after_json", "status"),
        "eaf_heat_ledger": ("run_case", "day_index", "lower_taps", "upper_taps", "quota_neutral_taps", "executed_taps", "remaining_before", "remaining_after", "unfinished_after", "status"),
        "route_progress": ("run_case", "route", "executed_increment_t", "cumulative_t", "status"),
        "energy_wag_generator_audit": ("run_case", "interval", "vn25_output_mw", "vn25_ramp_from_previous_mw", "vn25_wag_mwh_lhv", "vn25_named_ng_mwh_lhv", "ij01_wag_mwh_lhv", "ij01_named_ng_mwh_lhv", "bfg_flare_mwh_lhv", "cog_flare_mwh_lhv", "bofg_flare_mwh_lhv", "vn25_wag_volume_slack_nm3", "deployable_flared_wag_mwh_lhv", "avoidable_flare_plus_vn25_ng", "status"),
        "baseline_delta": ("run_case", "entity", "metric", "prechange_value", "postchange_value", "delta", "unit", "status"),
        "heat_count_certification": (
            "case_id", "fixed_count", "state_sha256",
            "calendar_day_length_hours", "interval_count", "carry_in_lag1",
            "carry_in_lag2", "physical_day_cap_taps", "beginning_inventories_json",
            "remaining_bof_scrap_cap_t", "remaining_eaf_scrap_cap_t",
            "remaining_external_scrap_cap_t", "remaining_internal_scrap_cap_t",
            "remaining_site_scrap_cap_t", "remaining_week_taps",
            "physical_horizon_hours", "physical_tail_hours", "terminal_policy",
            "feasible_incumbent", "objective_bound", "mip_gap", "solver_status",
            "termination_condition", "feasibility_status", "iis_status", "iis_path",
            "cost_check_status", "represented_cost_D_eur", "solve_attempt",
            "time_limit_seconds", "warm_start_used", "warm_start_source_case",
            "warm_start_value_count", "solver_log_path",
        ),
        "annual_operational_anchor_results": (
            "evaluation_id", "period_classification", "executed_hours",
            "calendar_coverage", "annualisation_denominator_hours", "metric_id",
            "metric", "family", "source_value", "source_unit",
            "model_annual_equivalent", "model_unit", "absolute_deviation",
            "relative_deviation", "model_coverage", "boundary_denominator",
            "comparability", "source_locator", "caveat",
        ),
        "administrative_carbon_balance": (
            "evaluation_id", "source_class", "source_mtco2_y",
            "represented_mtco2_y", "coverage_residual_mtco2_y",
            "coverage_fraction", "accounting_status",
            "physical_balance_closed", "residual_enters_model", "notes",
        ),
        "annual_anchor_delta_vs_last_accepted": (
            "evaluation_id", "metric_id", "baseline_id", "last_accepted_value",
            "current_value", "unit", "absolute_delta", "relative_delta",
            "comparison_status",
        ),
        "scalar_objective_components": (
            "run_case", "attempt", "status", "procurement_eur",
            "continuation_eur", "total_objective_eur",
            "remaining_taps_before", "remaining_taps_after", "executed_taps",
            "continuation_eur_per_heat", "normalized_total_variation",
            "quota_neutral_taps", "heat_deviation", "best_bound_eur",
            "absolute_gap_eur", "relative_gap", "audit_status",
        ),
    }


def _write_incremental_checkpoint(
    output: Path,
    rows: Mapping[str, list[dict[str, Any]]],
    manifest: Mapping[str, Any],
    *,
    checkpoint_phase: str,
) -> None:
    """Persist accepted progress after D1 and after every certification solve."""

    for name in (
        "heat_count_certification",
        "annual_operational_anchor_results",
        "annual_anchor_delta_vs_last_accepted",
        "scalar_objective_components",
    ):
        _write_csv(output / f"{name}.csv", rows[name], _output_schemas()[name])
    annual_gate = (
        rows["annual_operational_anchor_gate"][0]
        if rows["annual_operational_anchor_gate"]
        else {
            "status": "certification_in_progress",
            "annual_anchors_enter_constraints": False,
            "annual_anchors_enter_objectives": False,
            "full_four_week_matrix_authorized": False,
        }
    )
    _write_json(output / "annual_operational_anchor_gate.json", annual_gate)
    _write_json(output / "solver_attempts.json", rows["solver_attempts"])
    _write_json(
        output / "continuation_calibration.json",
        rows["continuation_calibration"][0]
        if rows["continuation_calibration"]
        else {"status": "not_yet_calibrated"},
    )
    progress = {
        "checkpoint_phase": checkpoint_phase,
        "checkpointed_at_utc": datetime.now(timezone.utc).isoformat(),
        "solve_record_count": len(rows["solver_attempts"]),
        "heat_count_certificate_count": len(rows["heat_count_certification"]),
        "last_heat_count_certificate": (
            rows["heat_count_certification"][-1]
            if rows["heat_count_certification"]
            else None
        ),
        "full_four_week_matrix_authorized": False,
    }
    _write_json(output / "certification_progress.json", progress)
    _write_json(
        output / "run_manifest.json",
        {
            **manifest,
            "incremental_checkpoint_phase": checkpoint_phase,
            "incremental_checkpointed_at_utc": progress["checkpointed_at_utc"],
            "incremental_progress_persisted": True,
        },
    )


def _write_outputs(
    output: Path,
    rows: Mapping[str, list[dict[str, Any]]],
    manifest: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output / "objective_incentive_ledger.csv",
        objective_incentive_ledger(),
        ("tier", "term", "sign", "coefficient", "unit", "active_intervals", "preservation_tolerance", "methodological_status"),
    )
    schemas = _output_schemas()
    for name, fields in schemas.items():
        _write_csv(output / f"{name}.csv", rows[name], fields)
    annual_gate = (
        rows["annual_operational_anchor_gate"][0]
        if rows["annual_operational_anchor_gate"]
        else {
            "status": "not_reached",
            "decision": "needs_bounded_fix",
            "annual_anchors_enter_constraints": False,
            "annual_anchors_enter_objectives": False,
            "full_four_week_matrix_authorized": False,
        }
    )
    _write_json(output / "annual_operational_anchor_gate.json", annual_gate)
    _write_json(output / "solver_attempts.json", rows["solver_attempts"])
    _write_json(
        output / "continuation_calibration.json",
        rows["continuation_calibration"][0]
        if rows["continuation_calibration"]
        else {"status": "not_reached"},
    )
    _write_json(output / "run_manifest.json", manifest)
    _write_json(output / "gate_decision.json", decision)


def _manifest(config: Mapping[str, Any], run_id: str, output: Path) -> dict[str, Any]:
    repair = config["deterministic_temporal_repair"]
    planned = repair["planned_full_run"]
    inputs = (
        CONFIG_PATH,
        REPO_ROOT / str(repair["base_context_config"]),
        Path(__file__).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c6_phase6b_hourly_da_bid_clear_redispatch.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_component_ontology/c5_builder_operation_class_overrides.csv",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_component_ontology/c5_route_boundary_contract.csv",
        ANCHOR_REGISTER_PATH,
        ANNUAL_SERVICE_CONTRACT_PATH,
        PHASE5E_CONFIG_PATH,
        LAST_ACCEPTED_ANNUAL_BASELINE_ROOT / "dynamic_period_metrics.csv",
    )
    return {
        "schema_version": "steel_c1_deterministic_scalar_temporal_repair_manifest_v1",
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "temporal_contract_version": TEMPORAL_CONTRACT_VERSION,
        "output_root": str(output),
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "retention_status": config["retention_status"],
        "git_eligible": bool(config["git_eligible"]),
        "planned_model_build_count_upper_bound": int(
            planned["model_build_count_upper_bound"]
        ),
        "planned_solve_attempt_count_upper_bound": int(
            planned["solve_attempt_count_upper_bound"]
        ),
        "conditional_solve_plan": (
            "fixed_27_26_28_physical_then_strict_cost_calibration; "
            "one_scalar_operational_attempt_plus_one_no_incumbent_fallback"
        ),
        "planned_artifact_count": len(OUTPUT_FILES),
        "planned_artifacts": list(OUTPUT_FILES),
        "estimated_output_size_mb_upper_bound": int(planned["estimated_output_size_mb_upper_bound"]),
        "maximum_figure_count": int(planned["maximum_figure_count"]),
        "figure_count": 0,
        "deterministic_only": True,
        "economic_horizon_hours": 24,
        "physical_horizon_hours": 48,
        "offline_certification_horizon_hours": 168,
        "input_sha256": {
            str(path.relative_to(REPO_ROOT)): _sha256(path) for path in inputs
        },
        "solver_settings": {
            "strict_mip_gap": float(repair["strict_mip_gap"]),
            "runtime_mip_gap": float(repair["runtime_mip_gap"]),
            "MIPFocus": int(repair["runtime_mip_focus"]),
            "Threads": int(repair["solver_threads"]),
            "Seed": int(repair["solver_seed"]),
            "operational_time_limit_seconds": float(
                repair["operational_time_limit_seconds"]
            ),
            "operational_fallback_time_limit_seconds": float(
                repair["operational_fallback_time_limit_seconds"]
            ),
        },
        "objective_mode": OBJECTIVE_MODE,
        "full_four_week_matrix_authorized": False,
    }


def _maximum_incumbent_violation(model: Any) -> tuple[float, str]:
    """Reconstruct active bounds/constraints before accepting an incumbent."""

    maximum = 0.0
    location = ""
    for constraint in model.component_data_objects(Constraint, active=True):
        body = float(value(constraint.body))
        violation = 0.0
        if constraint.has_lb():
            violation = max(violation, float(value(constraint.lower)) - body)
        if constraint.has_ub():
            violation = max(violation, body - float(value(constraint.upper)))
        if violation > maximum:
            maximum = violation
            location = constraint.name
    for variable in model.component_data_objects(Var, active=True):
        if variable.value is None:
            continue
        observed = float(value(variable))
        violation = 0.0
        if variable.has_lb():
            violation = max(violation, float(value(variable.lb)) - observed)
        if variable.has_ub():
            violation = max(violation, observed - float(value(variable.ub)))
        if variable.is_binary() or variable.is_integer():
            violation = max(violation, abs(observed - round(observed)))
        if violation > maximum:
            maximum = violation
            location = variable.name
    return max(0.0, maximum), location


def _scalar_objective_row(
    result: ScalarSolveResult,
    components: ScalarObjectiveComponents,
    reporting: Mapping[str, float],
) -> dict[str, Any]:
    executed = int(round(float(reporting["executed_taps"])))
    return {
        "run_case": result.run_case,
        "attempt": result.attempt,
        "status": result.status,
        "procurement_eur": result.procurement_eur,
        "continuation_eur": result.continuation_eur,
        "total_objective_eur": result.incumbent_objective_eur,
        "remaining_taps_before": components.remaining_taps_before,
        "remaining_taps_after": components.remaining_taps_before - executed,
        "executed_taps": executed,
        "continuation_eur_per_heat": components.continuation_eur_per_heat,
        "normalized_total_variation": reporting["normalized_total_variation"],
        "quota_neutral_taps": reporting["quota_neutral_taps"],
        "heat_deviation": reporting["heat_deviation"],
        "best_bound_eur": result.best_bound_eur,
        "absolute_gap_eur": result.absolute_gap_eur,
        "relative_gap": result.relative_gap,
        "audit_status": result.audit_status,
    }


def _executed_discrete_signature(model: Any, execution_steps: int) -> dict[str, int]:
    signature: dict[str, int] = {}
    for variable in model.component_data_objects(Var, active=True):
        if not (variable.is_binary() or variable.is_integer()):
            continue
        if not _variable_belongs_to_executed_prefix(
            variable,
            execution_steps=execution_steps,
            time_step_hours=float(getattr(model, "time_step_hours", 1.0)),
        ):
            continue
        signature[variable.name] = int(round(float(value(variable))))
    return signature


def _executed_operational_signature(model: Any, execution_steps: int) -> dict[str, int]:
    """Return discrete outcomes that must survive scalar-equivalent schedules.

    Quarter-hour heat timing and direction auxiliaries are deliberately omitted:
    a scalar solve may choose another equally valid timing pattern.  Daily starts,
    taps, unfinished heats, and genuine commitment totals remain exact.
    """

    starts = _series(model, "eaf_heat_start", execution_steps)
    taps = _series(model, "eaf_heat_tap", execution_steps)
    signature = {
        "eaf_starts": int(round(sum(starts))),
        "eaf_taps": int(round(sum(taps))),
        "unfinished_heats": int(round(sum(starts[-2:]))),
    }
    for component in model.component_objects(Var, active=True):
        name = component.name.lower()
        if "commitment" not in name and not name.endswith("_on"):
            continue
        values: list[int] = []
        for index in component:
            variable = component[index]
            if not (variable.is_binary() or variable.is_integer()):
                continue
            if _variable_belongs_to_executed_prefix(
                variable,
                execution_steps=execution_steps,
                time_step_hours=float(getattr(model, "time_step_hours", 1.0)),
            ):
                values.append(int(round(float(value(variable)))))
        if values:
            signature[f"commitment_total.{component.name}"] = sum(values)
    return signature


def _state_numeric_drift(
    reference: SteelRollingState,
    candidate: SteelRollingState,
    config: Mapping[str, Any],
) -> dict[str, float]:
    drift: dict[str, float] = {}
    repair = config["deterministic_temporal_repair"]

    def compare_mapping(
        prefix: str,
        left: Mapping[str, float],
        right: Mapping[str, float],
        tolerance: float,
    ) -> None:
        for key in set(left) | set(right):
            difference = abs(float(left.get(key, 0.0)) - float(right.get(key, 0.0)))
            if difference > tolerance:
                drift[f"{prefix}.{key}"] = difference

    inventory_tolerance = float(repair["d5_inventory_tolerance_t"])
    route_tolerance = float(repair["d5_route_tolerance_t"])
    rate_tolerance = float(repair["d5_rate_tolerance_t_h"])
    scrap_tolerance = float(repair["d5_scrap_tolerance_t"])
    vn25_tolerance = float(repair["d5_vn25_tolerance_mw"])
    compare_mapping(
        "inventory", reference.inventory_overrides, candidate.inventory_overrides,
        inventory_tolerance,
    )
    compare_mapping(
        "route", reference.cumulative_route_progress_t,
        candidate.cumulative_route_progress_t,
        route_tolerance,
    )
    compare_mapping(
        "rate", reference.last_continuous_rate_t_h,
        candidate.last_continuous_rate_t_h,
        rate_tolerance,
    )
    scalar_tolerances = {
        "cumulative_production_t": route_tolerance,
        "drp_last_pellet_input_t": rate_tolerance * 0.25,
        "last_vn25_output_mw": vn25_tolerance,
        "cumulative_external_scrap_to_bof_t": scrap_tolerance,
        "cumulative_external_scrap_to_eaf_t": scrap_tolerance,
        "cumulative_internal_scrap_to_bof_t": scrap_tolerance,
        "cumulative_internal_scrap_to_eaf_t": scrap_tolerance,
        "pefa_last_output_t_h": rate_tolerance,
        "pellet_inventory_t": inventory_tolerance,
    }
    for field, tolerance in scalar_tolerances.items():
        difference = abs(float(getattr(reference, field)) - float(getattr(candidate, field)))
        if difference > tolerance:
            drift[field] = difference
    integer_fields = (
        "executed_hours", "executed_intervals", "eaf_start_lag1",
        "eaf_start_lag2", "eaf_quota_target_taps", "eaf_quota_completed_taps",
    )
    for field in integer_fields:
        difference = abs(int(getattr(reference, field)) - int(getattr(candidate, field)))
        if difference:
            drift[field] = float(difference)
    return drift


def _calibration_payload(
    calibration: LinearHeatContinuationCalibration,
) -> dict[str, Any]:
    return {
        "status": "accepted_strict_fixed_26_27_28",
        "continuation_eur_per_heat": calibration.continuation_eur_per_heat,
        "endpoint_costs_eur": {
            str(key): value_in for key, value_in in calibration.endpoint_costs_eur.items()
        },
        "marginal_costs_eur_per_heat": dict(
            calibration.marginal_costs_eur_per_heat
        ),
        "state_sha256": calibration.state_sha256,
        "price_profile_sha256": calibration.price_profile_sha256,
        "contract_version": calibration.contract_version,
        "input_sha256": dict(calibration.input_sha256),
        "endpoint_definition": "fixed_26_27_28; hard_zero_progress; D_only_cost",
    }


def _run_lexicographic_temporal_repair_superseded(
    *,
    config_path: str | Path = CONFIG_PATH,
    run_id: str = "full_validation_45e0fc2",
) -> dict[str, Any]:
    raise TemporalRepairError(
        "The lexicographic temporal runner is historical and cannot be executed."
    )

    def solve_temporal_hierarchy(*_args: Any, **_kwargs: Any) -> Any:
        raise TemporalRepairError(
            "The lexicographic operational solver is superseded by the scalar runner."
        )

    config = load_temporal_repair_config(config_path)
    output = REPO_ROOT / str(config["output_root"]) / str(run_id)
    if output.exists() and any(output.iterdir()):
        raise TemporalRepairError(f"Refusing to overwrite non-empty run folder: {output}")
    output.mkdir(parents=True, exist_ok=True)
    manifest = _manifest(config, run_id, output)
    _write_json(output / "run_manifest.json", manifest)
    print(
        json.dumps(
            {
                "before_first_solve": True,
                "output_root": str(output),
                "planned_model_build_count_upper_bound": manifest[
                    "planned_model_build_count_upper_bound"
                ],
                "planned_solve_tier_count_upper_bound": manifest[
                    "planned_solve_tier_count_upper_bound"
                ],
                "conditional_endpoint_policy": manifest["conditional_solve_plan"],
                "exact_planned_artifact_count": manifest["planned_artifact_count"],
                "estimated_output_size_mb_upper_bound": manifest["estimated_output_size_mb_upper_bound"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    context = prepare_temporal_context(config)
    initial = initial_temporal_state(config)
    rows = _empty_output_rows()
    static_anchor_gate = _phase5e_static_anchor_gate()
    last_accepted_annual = _last_accepted_annual_values()
    annual_gate_evaluations: list[dict[str, Any]] = []
    model_build_count = 0
    try:
        if not all(
            bool(static_anchor_gate[key])
            for key in (
                "annual_anchor_comparison_pass",
                "carrier_coverage_pass",
                "generator_source_identity_pass",
            )
        ):
            raise TemporalRepairError(
                "Reused Phase-5E source-accounting or carrier-coverage gate failed."
            )
        # D0: six construction-only fixtures, deliberately without a solve.
        for fixed in (None, 20, 26, 27, 28, 32):
            build_temporal_model(
                context,
                initial,
                config,
                lower_taps=20,
                upper_taps=32,
                fixed_taps=fixed,
            )
            model_build_count += 1

        # D1 is the first solve gate. It deliberately uses zero continuation:
        # that value is not calibrated until D3. D1 is a strict flat physical
        # baseline, so fix its count to the causal quota-neutral 191/7 result;
        # D3 separately certifies and selects the operational count band.
        d1_quota_neutral_taps = quota_neutral_daily_taps(
            quota_period_target_taps(0), 7
        )
        model = build_temporal_model(
            context,
            initial,
            config,
            lower_taps=20,
            upper_taps=32,
            fixed_taps=d1_quota_neutral_taps,
        )
        model_build_count += 1
        try:
            tier_rows, d1_values = solve_temporal_hierarchy(
                context,
                model,
                initial,
                config,
                run_case="D1_flat",
                electricity_prices=price_profile(config, "flat"),
                remaining_taps=quota_period_target_taps(0),
                remaining_days=7,
                continuation_eur_per_heat=0.0,
            )
        except TemporalPhysicalInfeasibility as exc:
            if hasattr(exc, "solver_record"):
                rows["solver_tiers"].append(exc.solver_record)
            raise
        rows["solver_tiers"].extend(tier_rows)
        if abs(float(d1_values["progress_optimum_t"])) > PHYSICAL_TOLERANCE:
            raise TemporalRepairError(
                "D1 did not prove the required zero physical/recoverable optimum."
            )
        flat_kpis = temporal_kpi_rows(
            model, initial, config, run_case="D1_flat"
        )
        rows["temporal_kpis"].extend(flat_kpis)
        d1_taps = round_half_up(
            next(
                float(item["value"])
                for item in flat_kpis
                if item["entity"] == "eaf" and item["metric"] == "heat_taps"
            )
        )
        if d1_taps != d1_quota_neutral_taps:
            raise TemporalRepairError(
                f"D1 flat executed {d1_taps} taps instead of fixed quota-neutral "
                f"{d1_quota_neutral_taps}."
            )
        if any(item["status"] == "needs_bounded_fix" for item in flat_kpis):
            raise TemporalRepairError(
                "D1 flat shows unconstrained quarter-hour BOF/HSM/DSP oscillation."
            )
        flat_energy_rows = energy_audit_rows(model, run_case="D1_flat")
        rows["energy_wag_generator_audit"].extend(flat_energy_rows)
        if any(item["status"] == "fail" for item in flat_energy_rows):
            raise TemporalRepairError("D1 flat fails WAG/NG precedence audit.")

        d1_annual_rows, d1_annual_gate = annual_operational_anchor_rows(
            _execution_totals(model, context.time_grid.execution_steps),
            evaluation_id="D1_flat_provisional",
            executed_hours=context.time_grid.execution_hours,
            period_classification="provisional_single_day_annualised_diagnostic",
            calendar_coverage="one synthetic normal 24-hour day; not a representative year",
        )
        rows["annual_operational_anchor_results"].extend(d1_annual_rows)
        rows["annual_anchor_delta_vs_last_accepted"].extend(
            annual_anchor_delta_rows(
                d1_annual_rows,
                baseline_id="steel_c5_phase5e_source_backed_anchor_closure_v1_20260727",
                baseline_values=last_accepted_annual,
            )
        )
        d1_annual_gate["drift_gate_applicable"] = False
        d1_annual_gate["status"] = (
            "pass_provisional" if d1_annual_gate["identity_gate_pass"] else "fail"
        )
        annual_gate_evaluations.append(d1_annual_gate)
        rows["annual_operational_anchor_gate"] = [
            {
                "status": d1_annual_gate["status"],
                "decision": "certification_in_progress",
                "evaluations": list(annual_gate_evaluations),
                "annual_anchors_enter_constraints": False,
                "annual_anchors_enter_objectives": False,
                "full_four_week_matrix_authorized": False,
            }
        ]
        _write_incremental_checkpoint(
            output,
            rows,
            manifest,
            checkpoint_phase="D1_annual_anchors_complete",
        )

        # D3 begins with the normal 96-QH, zero-carry reference state.  A
        # fixed count is certified as the full stateful tuple recorded below,
        # never as a universal property of a calendar day.
        certification_by_case: dict[str, dict[str, Any]] = {}
        repair = config["deterministic_temporal_repair"]
        initial_feasibility_limit = float(
            repair["feasibility_initial_time_limit_seconds"]
        )
        extended_feasibility_limit = float(
            repair["feasibility_extended_time_limit_seconds"]
        )

        def store_certification(
            record: Mapping[str, Any], certification: dict[str, Any]
        ) -> None:
            rows["solver_tiers"].append(dict(record))
            rows["heat_count_certification"].append(certification)
            certification_by_case[str(certification["case_id"])] = certification
            _write_incremental_checkpoint(
                output,
                rows,
                manifest,
                checkpoint_phase=f"D3_after_{certification['case_id']}_"
                f"{certification['solve_attempt']}",
            )

        def certify_case(
            case: HeatCountCertificationCase,
            *,
            adjacent_model: Any | None,
            adjacent_case_id: str,
            extend_unknown: bool,
        ) -> tuple[Any, dict[str, Any]]:
            nonlocal model_build_count
            safe_case = case.case_id.replace("/", "_")
            model, record, certification = build_and_solve_heat_count_case(
                context,
                config,
                case,
                adjacent_model=adjacent_model,
                adjacent_case_id=adjacent_case_id,
                solve_attempt="initial_60s",
                time_limit_seconds=initial_feasibility_limit,
                solver_log_path=output / "solver_logs" / f"{safe_case}_initial_60s.log",
            )
            model_build_count += 1
            store_certification(record, certification)
            if certification["feasibility_status"] != "unknown":
                return model, certification
            if not extend_unknown:
                return model, certification
            extended_model, extended_record, extended = (
                build_and_solve_heat_count_case(
                    context,
                    config,
                    case,
                    adjacent_model=adjacent_model,
                    adjacent_case_id=adjacent_case_id,
                    solve_attempt="extended_band_determining",
                    time_limit_seconds=extended_feasibility_limit,
                    solver_log_path=(
                        output
                        / "solver_logs"
                        / f"{safe_case}_extended_band_determining.log"
                    ),
                )
            )
            model_build_count += 1
            store_certification(extended_record, extended)
            return extended_model, extended

        def certify_expanding_counts(
            *,
            case_prefix: str,
            start_state: SteelRollingState,
            calendar_day_length_hours: int,
            physical_horizon_hours: int,
            allowed_counts: set[int],
        ) -> set[int]:
            feasible: set[int] = set()
            solved_models: dict[int, Any] = {}
            solved_case_ids: dict[int, str] = {}
            lower_open = True
            upper_open = True
            for count in expansion_order:
                if count not in allowed_counts:
                    continue
                if count < 26 and not lower_open:
                    continue
                if count > 28 and not upper_open:
                    continue
                case_id = f"{case_prefix}_fixed_{count}"
                case = HeatCountCertificationCase(
                    case_id=case_id,
                    count=count,
                    start_state=start_state,
                    calendar_day_length_hours=calendar_day_length_hours,
                    remaining_quota_taps=quota_period_target_taps(0),
                    physical_horizon_hours=physical_horizon_hours,
                )
                adjacent_counts = [
                    candidate
                    for candidate in solved_models
                    if abs(candidate - count) == 1 and candidate in feasible
                ]
                adjacent_count = adjacent_counts[0] if adjacent_counts else None
                model, certification = certify_case(
                    case,
                    adjacent_model=(
                        None
                        if adjacent_count is None
                        else solved_models[adjacent_count]
                    ),
                    adjacent_case_id=(
                        ""
                        if adjacent_count is None
                        else solved_case_ids[adjacent_count]
                    ),
                    extend_unknown=True,
                )
                solved_models[count] = model
                solved_case_ids[count] = case_id
                status = str(certification["feasibility_status"])
                if bool(certification["feasible_incumbent"]):
                    feasible.add(count)
                elif status == "proven_infeasible":
                    if count < 26:
                        lower_open = False
                    elif count > 28:
                        upper_open = False
                else:
                    raise TemporalRepairError(
                        f"Band-determining {case_id} remains unknown after extension."
                    )
            return feasible

        reference_feasible: set[int] = set()
        reference_case_ids: dict[int, str] = {}
        reference_models: dict[int, Any] = {}
        reference_status: dict[int, str] = {}
        expansion_order = heat_count_expansion_order()
        lower_open = True
        upper_open = True
        for count in expansion_order:
            if count < 26 and not lower_open:
                continue
            if count > 28 and not upper_open:
                continue
            case_id = f"D3_reference_24h_zero_carry_fixed_{count}"
            case = HeatCountCertificationCase(
                case_id=case_id,
                count=count,
                start_state=initial,
                calendar_day_length_hours=24,
                remaining_quota_taps=quota_period_target_taps(0),
                physical_horizon_hours=48,
            )
            adjacent_counts = [
                candidate
                for candidate in reference_models
                if abs(candidate - count) == 1
                and reference_status.get(candidate) == "accepted_feasible_incumbent"
            ]
            adjacent_count = (
                min(adjacent_counts, key=lambda candidate: abs(candidate - count))
                if adjacent_counts
                else None
            )
            model, certification = certify_case(
                case,
                adjacent_model=(
                    None if adjacent_count is None else reference_models[adjacent_count]
                ),
                adjacent_case_id=(
                    "" if adjacent_count is None else reference_case_ids[adjacent_count]
                ),
                extend_unknown=True,
            )
            reference_case_ids[count] = case_id
            reference_models[count] = model
            reference_status[count] = str(certification["feasibility_status"])
            if bool(certification["feasible_incumbent"]):
                reference_feasible.add(count)
            elif certification["feasibility_status"] == "proven_infeasible":
                if count in {26, 27, 28}:
                    raise TemporalPhysicalInfeasibility(
                        f"Mandatory core heat count {count} is physically infeasible."
                    )
                if count < 26:
                    lower_open = False
                elif count > 28:
                    upper_open = False
            else:
                raise TemporalRepairError(
                    f"Band-determining {case_id} remains unknown after extension."
                )

        if not {26, 27, 28}.issubset(reference_feasible):
            raise TemporalPhysicalInfeasibility(
                "Normal zero-carry reference does not certify required counts 26--28."
            )

        # Economic optimality is requested only for feasible calibration and
        # marginal-check endpoints. Infeasible endpoints remain explicitly
        # not applicable and are never indexed in endpoint_costs.
        endpoint_costs: dict[int, float] = {}
        for count in (20, 26, 27, 28, 32):
            if count not in reference_feasible:
                if count in reference_case_ids:
                    certification_by_case[reference_case_ids[count]][
                        "cost_check_status"
                    ] = "not_applicable_infeasible_endpoint"
                continue
            certification = certification_by_case[reference_case_ids[count]]
            cost_model = build_temporal_model(
                context,
                initial,
                config,
                lower_taps=20,
                upper_taps=32,
                fixed_taps=count,
            )
            model_build_count += 1
            cost_record, endpoint_cost = solve_fixed_count_cost_endpoint(
                context,
                cost_model,
                config,
                run_case=f"D3_cost_endpoint_{count}",
                electricity_prices=price_profile(config, "flat"),
                solver_log_path=(
                    output / "solver_logs" / f"D3_cost_endpoint_{count}.log"
                ),
            )
            rows["solver_tiers"].append(cost_record)
            endpoint_costs[count] = endpoint_cost
            certification["cost_check_status"] = "optimal_cost_endpoint"
            certification["represented_cost_D_eur"] = endpoint_cost
            _write_incremental_checkpoint(
                output,
                rows,
                manifest,
                checkpoint_phase=f"D3_after_cost_endpoint_{count}",
            )

        if 26 not in endpoint_costs or 28 not in endpoint_costs:
            raise TemporalPhysicalInfeasibility(
                "Fixed 26/28 continuation cost endpoints are not both applicable."
            )
        continuation = (endpoint_costs[28] - endpoint_costs[26]) / 2.0
        if not math.isfinite(continuation) or continuation <= 0.0:
            raise TemporalRepairError(
                "Continuation calibration has an invalid non-positive sign."
            )
        comparable_pairs = [
            (left, right)
            for left, right in ((20, 26), (26, 27), (27, 28), (28, 32))
            if left in endpoint_costs and right in endpoint_costs
        ]
        local_deltas = [
            endpoint_costs[right] - endpoint_costs[left]
            for left, right in comparable_pairs
        ]
        if not all(math.isfinite(item) and item >= 0.0 for item in local_deltas):
            raise TemporalRepairError(
                "Applicable fixed-count marginal costs are non-finite or non-monotone."
            )

        # Normal-day carry states are individually reachable under the
        # three-QH occupancy automaton. The normal certified band is the
        # intersection of reference and carry-state feasibility.
        normal_stateful_feasible = set(reference_feasible)
        carry_states = reachable_eaf_carry_in_states(initial)
        for carry_state in carry_states[1:]:
            carry_id = f"lag{carry_state.eaf_start_lag1}{carry_state.eaf_start_lag2}"
            cap = min(
                32,
                physical_day_heat_cap(
                    96,
                    initial_start_lag1=carry_state.eaf_start_lag1,
                    initial_start_lag2=carry_state.eaf_start_lag2,
                ),
            )
            feasible_here = certify_expanding_counts(
                case_prefix=f"D3_normal_24h_{carry_id}",
                start_state=carry_state,
                calendar_day_length_hours=24,
                physical_horizon_hours=48,
                allowed_counts={
                    count for count in reference_feasible if count <= cap
                },
            )
            normal_stateful_feasible.intersection_update(feasible_here)

        # The same state tuple is evaluated on 23/25-hour days. These results
        # have their own occupancy caps and do not silently redefine the
        # normal-day band.
        for day_hours in (23, 25):
            for carry_state in carry_states:
                carry_id = (
                    f"lag{carry_state.eaf_start_lag1}{carry_state.eaf_start_lag2}"
                )
                cap = min(
                    32,
                    physical_day_heat_cap(
                        day_hours * 4,
                        initial_start_lag1=carry_state.eaf_start_lag1,
                        initial_start_lag2=carry_state.eaf_start_lag2,
                    ),
                )
                certify_expanding_counts(
                    case_prefix=f"D3_DST_{day_hours}h_{carry_id}",
                    start_state=carry_state,
                    calendar_day_length_hours=day_hours,
                    physical_horizon_hours=48,
                    allowed_counts=set(range(20, cap + 1)),
                )

        # Physical-tail identity is explicit in the certificate as well.
        tail_feasible = certify_expanding_counts(
            case_prefix="D3_reference_24h_zero_carry_72h",
            start_state=initial,
            calendar_day_length_hours=24,
            physical_horizon_hours=72,
            allowed_counts=set(normal_stateful_feasible),
        )
        normal_stateful_feasible.intersection_update(tail_feasible)

        contiguous = []
        for lower in range(20, 28):
            for upper in range(28, 33):
                if all(
                    count in normal_stateful_feasible
                    for count in range(lower, upper + 1)
                ):
                    contiguous.append((lower, upper))
        if not contiguous:
            raise TemporalPhysicalInfeasibility("No certified daily EAF band contains 27 and 28.")
        primary_band = max(contiguous, key=lambda item: (item[1] - item[0], -item[0]))
        fallback_band = (26, 28)
        band_results: dict[tuple[int, int], bool] = {}
        for band in (primary_band, fallback_band):
            band_pass = True
            target = quota_period_target_taps(0)
            patterns: list[tuple[str, Sequence[int] | None]] = [("exact_week", None)]
            patterns.extend(extreme_week_patterns(*band, target).items())
            for pattern_id, pattern in patterns:
                model = build_temporal_model(
                    context, initial, config,
                    lower_taps=band[0], upper_taps=band[1],
                    planning_horizon_hours=168,
                    hard_inventory_terminal=True,
                )
                model_build_count += 1
                add_week_heat_contract(model, target_taps=target, daily_pattern=pattern)
                week_case_id = f"D3_week_{band[0]}_{band[1]}_{pattern_id}"
                week_record = _solve_zero_objective_feasibility(
                    model,
                    config,
                    run_case=week_case_id,
                    write_iis_on_infeasible=False,
                    time_limit_seconds=initial_feasibility_limit,
                    solver_log_path=(
                        output / "solver_logs" / f"{week_case_id}_initial_60s.log"
                    ),
                )
                week_case = HeatCountCertificationCase(
                    case_id=week_case_id,
                    count=-1,
                    start_state=initial,
                    calendar_day_length_hours=24,
                    remaining_quota_taps=target,
                    physical_horizon_hours=168,
                    terminal_policy="hard_week_terminal",
                )
                week_certification = {
                        **heat_count_case_metadata(week_case, config),
                        "physical_day_cap_taps": physical_day_heat_cap(96),
                        "feasible_incumbent": week_record["feasible_incumbent"],
                        "objective_bound": week_record["objective_bound"],
                        "mip_gap": week_record["mip_gap"],
                        "solver_status": week_record["solver_status"],
                        "termination_condition": week_record["termination_condition"],
                        "feasibility_status": week_record["feasibility_status"],
                        "iis_status": week_record["iis_status"],
                        "iis_path": week_record["iis_path"],
                        "cost_check_status": "not_applicable_week_pattern",
                        "represented_cost_D_eur": "",
                        "solve_attempt": "initial_60s",
                        "time_limit_seconds": initial_feasibility_limit,
                        "warm_start_used": False,
                        "warm_start_source_case": "",
                        "warm_start_value_count": 0,
                        "solver_log_path": week_record["solver_log_path"],
                    }
                store_certification(week_record, week_certification)
                if week_record["feasibility_status"] == "unknown":
                    week_record = _solve_zero_objective_feasibility(
                        model,
                        config,
                        run_case=week_case_id,
                        write_iis_on_infeasible=False,
                        time_limit_seconds=extended_feasibility_limit,
                        solver_log_path=(
                            output
                            / "solver_logs"
                            / f"{week_case_id}_extended_band_determining.log"
                        ),
                    )
                    extended_week = {
                        **week_certification,
                        "feasible_incumbent": week_record["feasible_incumbent"],
                        "objective_bound": week_record["objective_bound"],
                        "mip_gap": week_record["mip_gap"],
                        "solver_status": week_record["solver_status"],
                        "termination_condition": week_record["termination_condition"],
                        "feasibility_status": week_record["feasibility_status"],
                        "iis_status": week_record["iis_status"],
                        "iis_path": week_record["iis_path"],
                        "solve_attempt": "extended_band_determining",
                        "time_limit_seconds": extended_feasibility_limit,
                        "solver_log_path": week_record["solver_log_path"],
                    }
                    store_certification(week_record, extended_week)
                if week_record["feasibility_status"] == "unknown":
                    raise TemporalRepairError(
                        f"Mandatory causal-week case {week_case_id} remains unknown."
                    )
                if not bool(week_record["feasible_incumbent"]):
                    band_pass = False
            band_results[band] = band_pass
        if band_results.get(primary_band):
            certified_band = primary_band
        elif band_results.get(fallback_band):
            certified_band = fallback_band
        else:
            raise TemporalPhysicalInfeasibility(
                "Neither the widest candidate nor fallback 26-28 closes the causal week."
            )

        # D1/D2/D4: four deterministic synthetic profiles.
        for profile in ("cheap_to_expensive", "expensive_to_cheap", "negative_price"):
            model = build_temporal_model(
                context, initial, config,
                lower_taps=certified_band[0], upper_taps=certified_band[1],
            )
            model_build_count += 1
            tier_rows, _ = solve_temporal_hierarchy(
                context, model, initial, config,
                run_case=f"D_profile_{profile}",
                electricity_prices=price_profile(config, profile),
                remaining_taps=quota_period_target_taps(0),
                remaining_days=7,
                continuation_eur_per_heat=continuation,
            )
            rows["solver_tiers"].extend(tier_rows)
            profile_kpis = temporal_kpi_rows(
                model, initial, config, run_case=f"D_profile_{profile}"
            )
            rows["temporal_kpis"].extend(profile_kpis)
            if any(item["status"] == "needs_bounded_fix" for item in profile_kpis):
                raise TemporalRepairError(
                    f"{profile} shows unconstrained quarter-hour BOF/HSM/DSP oscillation."
                )
            energy_rows = energy_audit_rows(model, run_case=f"D_profile_{profile}")
            rows["energy_wag_generator_audit"].extend(energy_rows)
            if any(item["status"] == "fail" for item in energy_rows):
                raise TemporalRepairError(
                    f"{profile} has avoidable WAG flare together with VN25 named NG."
                )

        # D3: causal seven-day operation with dynamic recoverability bounds.
        state = initial
        daily_prices = config["deterministic_temporal_repair"]["causal_week_daily_flat_prices_eur_per_mwh"]
        daily_taps: list[int] = []
        causal_week_totals: list[dict[str, float]] = []
        for day_index, daily_price in enumerate(daily_prices):
            remaining_days = 7 - day_index
            remaining = int(state.eaf_quota_target_taps) - state.eaf_quota_completed_taps
            future_lowers = [certified_band[0]] * (remaining_days - 1)
            future_uppers = [certified_band[1]] * (remaining_days - 1)
            lower, upper = dynamic_daily_heat_bounds(
                remaining_taps=remaining,
                today_lower=certified_band[0],
                today_upper=min(certified_band[1], physical_day_heat_cap(96, initial_start_lag1=state.eaf_start_lag1, initial_start_lag2=state.eaf_start_lag2)),
                future_lower_bounds=future_lowers,
                future_upper_bounds=future_uppers,
            )
            model = build_temporal_model(
                context, state, config,
                lower_taps=lower, upper_taps=upper,
                week_boundary=day_index == 6,
            )
            model_build_count += 1
            run_case = f"D3_causal_week_day_{day_index + 1}"
            tier_rows, values = solve_temporal_hierarchy(
                context, model, state, config,
                run_case=run_case,
                electricity_prices=tuple([float(daily_price)] * 96),
                remaining_taps=remaining,
                remaining_days=remaining_days,
                continuation_eur_per_heat=continuation,
            )
            rows["solver_tiers"].extend(tier_rows)
            day_kpis = temporal_kpi_rows(
                model, state, config, run_case=run_case
            )
            rows["temporal_kpis"].extend(day_kpis)
            if any(item["status"] == "needs_bounded_fix" for item in day_kpis):
                raise TemporalRepairError(
                    f"{run_case} shows unconstrained quarter-hour BOF/HSM/DSP oscillation."
                )
            energy_rows = energy_audit_rows(model, run_case=run_case)
            rows["energy_wag_generator_audit"].extend(energy_rows)
            if any(item["status"] == "fail" for item in energy_rows):
                raise TemporalRepairError(f"{run_case} fails WAG/NG precedence audit.")
            causal_week_totals.append(
                _execution_totals(model, context.time_grid.execution_steps)
            )
            executed_taps = round_half_up(values["executed_taps"])
            daily_taps.append(executed_taps)
            before = state
            state = advance_temporal_state(
                context, model, state,
                last_timestamp_utc=f"2026-01-{day_index + 1:02d}T23:45:00+00:00",
            )
            rows["state_handoff_audit"].append(
                state_handoff_row(before, state, run_case=run_case)
            )
            rows["eaf_heat_ledger"].append(
                {
                    "run_case": run_case,
                    "day_index": day_index + 1,
                    "lower_taps": lower,
                    "upper_taps": upper,
                    "quota_neutral_taps": quota_neutral_daily_taps(remaining, remaining_days),
                    "executed_taps": executed_taps,
                    "remaining_before": remaining,
                    "remaining_after": remaining - executed_taps,
                    "unfinished_after": state.eaf_start_lag1 + state.eaf_start_lag2,
                    "status": "pass",
                }
            )
            for route, cumulative in state.cumulative_route_progress_t.items():
                previous = before.cumulative_route_progress_t.get(route, 0.0)
                rows["route_progress"].append(
                    {
                        "run_case": run_case,
                        "route": route,
                        "executed_increment_t": cumulative - previous,
                        "cumulative_t": cumulative,
                        "status": "pass",
                    }
                )
        if state.eaf_quota_completed_taps != state.eaf_quota_target_taps:
            raise TemporalRepairError("Causal week did not close the exact cumulative tap target.")
        cheapest_day = min(range(7), key=lambda day: daily_prices[day])
        most_expensive_day = max(range(7), key=lambda day: daily_prices[day])
        if daily_taps[cheapest_day] < daily_taps[most_expensive_day]:
            raise TemporalRepairError("Predetermined cheapest day receives fewer taps than the expensive day.")

        d3_annual_rows, d3_annual_gate = annual_operational_anchor_rows(
            _sum_execution_totals(causal_week_totals),
            evaluation_id="D3_causal_week",
            executed_hours=168,
            period_classification="representative_period_annualised",
            calendar_coverage="seven causal normal days; 168 executed hours",
        )
        rows["annual_operational_anchor_results"].extend(d3_annual_rows)
        rows["administrative_carbon_balance"] = (
            administrative_carbon_balance_rows(d3_annual_rows)
        )
        rows["annual_anchor_delta_vs_last_accepted"].extend(
            annual_anchor_delta_rows(
                d3_annual_rows,
                baseline_id="steel_c5_phase5e_source_backed_anchor_closure_v1_20260727",
                baseline_values=last_accepted_annual,
            )
        )
        d3_worsening = unexpected_anchor_worsening(
            d3_annual_rows,
            last_accepted_annual,
            relative_tolerance=float(
                config["deterministic_temporal_repair"][
                    "annual_anchor_worsening_tolerance_fraction"
                ]
            ),
        )
        d3_annual_gate["drift_gate_applicable"] = True
        d3_annual_gate["unexpected_worsening"] = d3_worsening
        d3_annual_gate["status"] = (
            "pass"
            if d3_annual_gate["identity_gate_pass"] and not d3_worsening
            else "fail"
        )
        annual_gate_evaluations.append(d3_annual_gate)
        if d3_annual_gate["status"] != "pass":
            raise TemporalRepairError(
                "D3 annual operational anchors or exact accounting identities regressed."
            )
        # D5: six independent robustness builds, each through five tiers.
        robustness_signatures: list[dict[str, Any]] = []
        d5_annual_reference: dict[str, float] | None = None
        robustness_cases = (
            ("strict_reference", 48, 0.0, False),
            ("runtime_gap", 48, 0.002, False),
            ("cold_repeat", 48, 0.0, False),
            ("warm_repeat", 48, 0.0, True),
            ("tail_72h", 72, 0.0, False),
            ("independent_process_equivalent", 48, 0.0, False),
        )
        for case_id, horizon, gap, warm in robustness_cases:
            model = build_temporal_model(
                context, initial, config,
                lower_taps=certified_band[0], upper_taps=certified_band[1],
                planning_horizon_hours=horizon,
            )
            model_build_count += 1
            tier_rows, values = solve_temporal_hierarchy(
                context, model, initial, config,
                run_case=f"D5_{case_id}",
                electricity_prices=price_profile(config, "flat"),
                remaining_taps=quota_period_target_taps(0),
                remaining_days=7,
                continuation_eur_per_heat=continuation,
                mip_gap=gap,
                warm_start=warm,
                include_algebraic_final_tier=False,
                include_heat_tier=False,
            )
            rows["solver_tiers"].extend(tier_rows)
            next_state = advance_temporal_state(
                context, model, initial,
                last_timestamp_utc="2026-01-01T23:45:00+00:00",
            )
            d5_rows, d5_gate = annual_operational_anchor_rows(
                _execution_totals(model, context.time_grid.execution_steps),
                evaluation_id=f"D5_{case_id}",
                executed_hours=context.time_grid.execution_hours,
                period_classification="robustness_single_day_annualised_diagnostic",
                calendar_coverage=(
                    f"one synthetic 24-hour executed day with {horizon}-hour "
                    "physical horizon"
                ),
            )
            rows["annual_operational_anchor_results"].extend(d5_rows)
            rows["annual_anchor_delta_vs_last_accepted"].extend(
                annual_anchor_delta_rows(
                    d5_rows,
                    baseline_id="steel_c5_phase5e_source_backed_anchor_closure_v1_20260727",
                    baseline_values=last_accepted_annual,
                )
            )
            if d5_annual_reference is None:
                d5_annual_reference = {
                    str(row["metric_id"]): float(row["model_annual_equivalent"])
                    for row in d5_rows
                }
                drift: list[dict[str, Any]] = []
            else:
                rows["annual_anchor_delta_vs_last_accepted"].extend(
                    annual_anchor_delta_rows(
                        d5_rows,
                        baseline_id="D5_strict_reference",
                        baseline_values=d5_annual_reference,
                    )
                )
                drift = material_annual_drift(
                    d5_rows,
                    d5_annual_reference,
                    relative_tolerance=float(
                        config["deterministic_temporal_repair"][
                            "d5_annual_anchor_drift_tolerance_fraction"
                        ]
                    ),
                )
            d5_gate["drift_gate_applicable"] = case_id != "strict_reference"
            d5_gate["reference_evaluation_id"] = "D5_strict_reference"
            d5_gate["material_annual_anchor_drift"] = drift
            d5_gate["status"] = (
                "pass" if d5_gate["identity_gate_pass"] and not drift else "fail"
            )
            annual_gate_evaluations.append(d5_gate)
            if d5_gate["status"] != "pass":
                raise TemporalRepairError(
                    f"D5 {case_id} causes material annual-anchor drift."
                )
            robustness_signatures.append(
                {
                    "case": case_id,
                    "taps": round_half_up(values["executed_taps"]),
                    "state_hash": _canonical_json_sha256(next_state.snapshot()),
                    "rates": next_state.last_continuous_rate_t_h,
                    "vn25": next_state.last_vn25_output_mw,
                }
            )
        strict = robustness_signatures[0]
        for signature in robustness_signatures[2:]:
            if signature["taps"] != strict["taps"] or signature["state_hash"] != strict["state_hash"]:
                raise TemporalRepairError(
                    "Cold/warm/process/tail robustness changed executed integers or state hash."
                )

        if model_build_count > int(manifest["planned_model_build_count_upper_bound"]):
            raise TemporalRepairError(
                f"Model-build manifest upper bound exceeded: {model_build_count} > "
                f"{manifest['planned_model_build_count_upper_bound']}."
            )
        if len(rows["solver_tiers"]) > int(manifest["planned_solve_tier_count_upper_bound"]):
            raise TemporalRepairError(
                f"Solve-tier manifest upper bound exceeded: {len(rows['solver_tiers'])} > "
                f"{manifest['planned_solve_tier_count_upper_bound']}."
            )
        decision = {
            "decision": "deterministic_operational_repair_pass_ready_for_single_s10_smoke",
            "status": "pass",
            "temporal_contract_version": TEMPORAL_CONTRACT_VERSION,
            "certified_daily_heat_band": list(certified_band),
            "continuation_eur_per_heat": continuation,
            "model_build_count": model_build_count,
            "solve_tier_count": len(rows["solver_tiers"]),
            "full_four_week_matrix_authorized": False,
            "s10_solve_started": False,
            "stochastic_solve_started": False,
        }
    except TemporalPhysicalInfeasibility as exc:
        conflict = (
            must_run_bof_conflict_diagnostic(model)
            if "model" in locals() and hasattr(model, "sinter_balance")
            else None
        )
        decision = {
            "decision": "physically_infeasible_under_source_contract",
            "status": "fail",
            "reason": str(exc),
            "model_build_count": model_build_count,
            "solve_tier_count": len(rows["solver_tiers"]),
            "full_four_week_matrix_authorized": False,
            "s10_solve_started": False,
            "stochastic_solve_started": False,
            "source_contract_conflict": conflict,
        }
    except Exception as exc:
        decision = {
            "decision": "needs_bounded_fix",
            "status": "fail",
            "reason": f"{type(exc).__name__}: {exc}",
            "model_build_count": model_build_count,
            "solve_tier_count": len(rows["solver_tiers"]),
            "full_four_week_matrix_authorized": False,
            "s10_solve_started": False,
            "stochastic_solve_started": False,
        }
    annual_gate_status = (
        "pass"
        if decision["status"] == "pass"
        and annual_gate_evaluations
        and all(item.get("status", "fail").startswith("pass") for item in annual_gate_evaluations)
        else "incomplete_at_first_hard_failure"
        if decision["status"] != "pass"
        else "fail"
    )
    rows["annual_operational_anchor_gate"] = [
        {
            "status": annual_gate_status,
            "decision": decision["decision"],
            "phase5e_static_gate": static_anchor_gate,
            "evaluations": annual_gate_evaluations,
            "last_accepted_deterministic_baseline": (
                "steel_c5_phase5e_source_backed_anchor_closure_v1_20260727"
            ),
            "annual_anchors_enter_constraints": False,
            "annual_anchors_enter_objectives": False,
            "residual_plugs_added": False,
            "partial_boundary_shortfall_is_failure": False,
            "full_four_week_matrix_authorized": False,
        }
    ]
    manifest = {
        **manifest,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "actual_model_build_count": model_build_count,
        "actual_solve_tier_count": len(rows["solver_tiers"]),
        "stopped_at_first_hard_failure": decision["status"] != "pass",
    }
    _write_outputs(output, rows, manifest, decision)
    return decision


def run_temporal_repair(
    *,
    config_path: str | Path = CONFIG_PATH,
    run_id: str = "scalar_validation_45e0fc2",
    wag_self_use_diagnostic: bool = False,
    generator_efficiency_418: bool = False,
    process_electricity_overlay: bool = False,
    ng_service_anchor_overlay: bool = False,
    coal_wag_carbon_overlay: bool = False,
) -> dict[str, Any]:
    """Run the governed scalar D0--D5 deterministic temporal validation."""

    config = load_temporal_repair_config(config_path)
    if wag_self_use_diagnostic:
        config["deterministic_temporal_repair"]["experimental_wag_self_use_diagnostic"] = {
            "active": True,
            "classification": "non_promoted_anchor_diagnostic_no_new_process_sink",
            "vn25_carrier_caps_pj_y": {"COG": 0.0, "BOFG": 1.4},
        }
        config["deterministic_temporal_repair"]["experimental_self_use_calibration"] = {
            "classification": "experimental_carrier_self_use_calibration_not_source_proven",
            "additional_cog_mwh_per_t_kgf_activity": 0.2396,
            "additional_cog_mwh_per_t_sinter": 0.2396,
            "additional_bofg_mwh_per_t_pellet": 0.00363,
        }
    if generator_efficiency_418:
        config["deterministic_temporal_repair"]["experimental_generator_efficiency"] = {
            "classification": "experimental_combined_generator_efficiency_not_vn25_source_truth",
            "efficiency": 0.418,
        }
    if process_electricity_overlay:
        config["deterministic_temporal_repair"]["experimental_process_electricity_overlay"] = {
            "classification": "experimental_proportional_process_electricity_not_source_proven",
            "mwh_per_t_activity": 0.04664,
        }
    if ng_service_anchor_overlay:
        config["deterministic_temporal_repair"]["experimental_ng_service_calibration"] = {
            "classification": "user_authorized_c1_origin_explicit_ng_service_calibration",
            "ironmaking_target_pj_y": 2.0,
            "ironmaking_basis_t_y": 2_800_000.0,
            "downstream_target_pj_y": 13.1,
            "downstream_basis_t_y": 6_750_000.0,
        }
    if coal_wag_carbon_overlay:
        config["deterministic_temporal_repair"]["experimental_coal_wag_calibration"] = {
            "classification": "user_authorized_c1_coal_completion_carrier_wag_calibration",
            "coal_procurement_multiplier": 1.28495216932074,
            "bfg_mwh_per_t_hot_metal": 1.46825396825397,
            "cog_mwh_per_t_kgf_activity": 1.78780575437936,
            "bofg_mwh_per_t_bof_steel": 0.179738562091503,
            "cog_self_use_scale": 0.942949340241867,
            "coal_anchor_t_y": 2_200_000.0,
            "coal_anchor_pj_y": 58.0,
        }
    output = REPO_ROOT / str(config["output_root"]) / str(run_id)
    if output.exists() and any(output.iterdir()):
        raise TemporalRepairError(f"Refusing to overwrite non-empty run folder: {output}")
    output.mkdir(parents=True, exist_ok=True)
    manifest = _manifest(config, run_id, output)
    _write_json(output / "run_manifest.json", manifest)
    print(
        json.dumps(
            {
                "before_first_solve": True,
                "output_root": str(output),
                "planned_model_build_count_upper_bound": manifest[
                    "planned_model_build_count_upper_bound"
                ],
                "planned_solve_attempt_count_upper_bound": manifest[
                    "planned_solve_attempt_count_upper_bound"
                ],
                "conditional_solve_plan": manifest["conditional_solve_plan"],
                "exact_planned_artifact_count": manifest["planned_artifact_count"],
                "estimated_output_size_mb_upper_bound": manifest[
                    "estimated_output_size_mb_upper_bound"
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    context = prepare_temporal_context(config)
    initial = initial_temporal_state(config)
    rows = _empty_output_rows()
    static_anchor_gate = _phase5e_static_anchor_gate()
    last_accepted_annual = _last_accepted_annual_values()
    annual_gate_evaluations: list[dict[str, Any]] = []
    model_build_count = 0
    certified_band = (26, 28)
    continuation = math.nan
    model: Any | None = None
    repair = config["deterministic_temporal_repair"]

    def checkpoint(phase: str) -> None:
        _write_incremental_checkpoint(
            output,
            rows,
            manifest,
            checkpoint_phase=phase,
        )

    def store_attempt(
        result: ScalarSolveResult,
        phase: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        rows["solver_attempts"].append(
            {**result.record(), **({} if metadata is None else dict(metadata))}
        )
        checkpoint(f"{phase}_{result.attempt}")

    def update_attempt_audit(result: ScalarSolveResult) -> None:
        for record in reversed(rows["solver_attempts"]):
            if (
                record.get("run_case") == result.run_case
                and record.get("attempt") == result.attempt
            ):
                record["audit_status"] = result.audit_status
                return
        raise TemporalRepairError("Accepted scalar attempt was not checkpointed.")

    def audit_scalar_incumbent(
        day_context: SteelPhysicalContext,
        solved_model: Any,
        state: SteelRollingState,
        components: ScalarObjectiveComponents,
        result: ScalarSolveResult,
        *,
        run_case: str,
        lower_taps: int,
        upper_taps: int,
        remaining_taps: int,
        remaining_days: int,
    ) -> dict[str, float]:
        violation, location = _maximum_incumbent_violation(solved_model)
        if violation > 1e-5:
            result.audit_status = "fail_hard_constraint_reconstruction"
            update_attempt_audit(result)
            raise TemporalRepairError(
                f"{run_case} incumbent violates {location} by {violation:.9g}."
            )
        progress = abs(
            float(value(solved_model.rolling_production_progress_deviation_t))
        )
        if progress > PHYSICAL_TOLERANCE:
            result.audit_status = "fail_nonzero_production_progress"
            update_attempt_audit(result)
            raise TemporalRepairError(
                f"{run_case} violates hard zero production progress by {progress:.9g} t."
            )
        reporting = scalar_reporting_kpis(
            solved_model,
            state,
            config,
            execution_steps=day_context.time_grid.execution_steps,
            remaining_taps=remaining_taps,
            remaining_days=remaining_days,
        )
        executed = int(round(reporting["executed_taps"]))
        if not int(lower_taps) <= executed <= int(upper_taps):
            result.audit_status = "fail_dynamic_heat_bound"
            update_attempt_audit(result)
            raise TemporalRepairError(
                f"{run_case} executed {executed} taps outside {lower_taps}--{upper_taps}."
            )
        kpis = temporal_kpi_rows(
            solved_model,
            state,
            config,
            run_case=run_case,
        )
        rows["temporal_kpis"].extend(kpis)
        if any(item["status"] == "needs_bounded_fix" for item in kpis):
            result.audit_status = "fail_unbounded_qh_oscillation"
            update_attempt_audit(result)
            raise TemporalRepairError(
                f"{run_case} shows unconstrained BOF/HSM/DSP quarter-hour oscillation."
            )
        energy = energy_audit_rows(solved_model, run_case=run_case)
        rows["energy_wag_generator_audit"].extend(energy)
        if any(item["status"] == "fail" for item in energy):
            result.audit_status = "fail_wag_ng_precedence"
            update_attempt_audit(result)
            raise TemporalRepairError(
                f"{run_case} fails WAG/NG/flare precedence reconstruction."
            )
        reconstructed_total = float(value(components.procurement_eur)) + float(
            value(components.continuation_eur)
        )
        if abs(reconstructed_total - float(result.incumbent_objective_eur)) > 1e-5:
            result.audit_status = "fail_objective_reconstruction"
            update_attempt_audit(result)
            raise TemporalRepairError(
                f"{run_case} scalar objective components do not reconstruct the incumbent."
            )
        result.audit_status = "pass"
        update_attempt_audit(result)
        rows["scalar_objective_components"].append(
            _scalar_objective_row(result, components, reporting)
        )
        checkpoint(f"{run_case}_accepted_incumbent")
        return reporting

    def solve_operation(
        day_context: SteelPhysicalContext,
        state: SteelRollingState,
        *,
        run_case: str,
        prices: Sequence[float],
        lower_taps: int,
        upper_taps: int,
        remaining_taps: int,
        remaining_days: int,
        planning_horizon_hours: int = 48,
        week_boundary: bool = False,
        warm_source: Any | None = None,
        forced_carry_lags: tuple[int, int] | None = None,
        fixed_executed_source: Any | None = None,
    ) -> tuple[Any, ScalarSolveResult, dict[str, float]]:
        nonlocal model_build_count, model
        model = build_temporal_model(
            day_context,
            state,
            config,
            lower_taps=lower_taps,
            upper_taps=upper_taps,
            planning_horizon_hours=planning_horizon_hours,
            week_boundary=week_boundary,
        )
        model_build_count += 1
        if forced_carry_lags is not None:
            add_execution_boundary_carry_witness(
                model,
                execution_steps=day_context.time_grid.execution_steps,
                lag1=forced_carry_lags[0],
                lag2=forced_carry_lags[1],
            )
        components = build_scalar_objective_components(
            day_context,
            model,
            electricity_prices=prices,
            remaining_taps=remaining_taps,
            continuation_eur_per_heat=continuation,
        )
        fixed_prefix_count = (
            0
            if fixed_executed_source is None
            else _fix_executed_solution_prefix(
                fixed_executed_source,
                model,
                day_context.time_grid.execution_steps,
            )
        )
        copied = 0 if warm_source is None else _copy_adjacent_warm_start(warm_source, model)
        attempt_metadata = {
            "state_sha256": _canonical_json_sha256(state.snapshot()),
            "calendar_day_length_hours": day_context.time_grid.execution_hours,
            "carry_in_lag1": int(state.eaf_start_lag1),
            "carry_in_lag2": int(state.eaf_start_lag2),
            "beginning_inventories_json": json.dumps(
                state.inventory_overrides, sort_keys=True
            ),
            **_remaining_scrap_caps(state, config),
            "remaining_week_taps": int(remaining_taps),
            "physical_horizon_hours": int(planning_horizon_hours),
            "physical_tail_hours": int(
                planning_horizon_hours - day_context.time_grid.execution_hours
            ),
            "fixed_executed_prefix_variable_count": fixed_prefix_count,
        }
        result, _ = solve_scalar_operational_model(
            model,
            components,
            config,
            run_case=run_case,
            solver_log_root=output / "solver_logs",
            attempt_callback=lambda attempt: store_attempt(
                attempt, run_case, attempt_metadata
            ),
            warm_start=copied > 0,
        )
        reporting = audit_scalar_incumbent(
            day_context,
            model,
            state,
            components,
            result,
            run_case=run_case,
            lower_taps=lower_taps,
            upper_taps=upper_taps,
            remaining_taps=remaining_taps,
            remaining_days=remaining_days,
        )
        return model, result, reporting

    def append_annual_evaluation(
        solved_model: Any,
        day_context: SteelPhysicalContext,
        *,
        evaluation_id: str,
        period_classification: str,
        calendar_coverage: str,
        totals: Mapping[str, float] | None = None,
        apply_baseline_worsening_gate: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        observed = (
            _execution_totals(
                solved_model,
                day_context.time_grid.execution_steps,
            )
            if totals is None
            else dict(totals)
        )
        anchor_rows, gate = annual_operational_anchor_rows(
            observed,
            evaluation_id=evaluation_id,
            executed_hours=(
                day_context.time_grid.execution_hours
                if totals is None
                else int(round(168))
            ),
            period_classification=period_classification,
            calendar_coverage=calendar_coverage,
        )
        rows["annual_operational_anchor_results"].extend(anchor_rows)
        if evaluation_id == "D3_causal_week":
            rows["administrative_carbon_balance"] = (
                administrative_carbon_balance_rows(anchor_rows)
            )
        rows["annual_anchor_delta_vs_last_accepted"].extend(
            annual_anchor_delta_rows(
                anchor_rows,
                baseline_id=(
                    "steel_c5_phase5e_source_backed_anchor_closure_v1_20260727"
                ),
                baseline_values=last_accepted_annual,
            )
        )
        worsening = (
            unexpected_anchor_worsening(
                anchor_rows,
                last_accepted_annual,
                relative_tolerance=float(
                    repair["annual_anchor_worsening_tolerance_fraction"]
                ),
            )
            if apply_baseline_worsening_gate
            else []
        )
        gate["drift_gate_applicable"] = bool(apply_baseline_worsening_gate)
        gate["unexpected_worsening"] = worsening
        gate["status"] = (
            "pass" if gate["identity_gate_pass"] and not worsening else "fail"
        )
        annual_gate_evaluations.append(gate)
        return anchor_rows, gate

    try:
        if not all(
            bool(static_anchor_gate[key])
            for key in (
                "annual_anchor_comparison_pass",
                "carrier_coverage_pass",
                "generator_source_identity_pass",
            )
        ):
            raise TemporalRepairError(
                "Reused Phase-5E source-accounting or carrier-coverage gate failed."
            )

        # D0: one free-count model, one linear objective and no reporting penalty.
        model = build_temporal_model(
            context,
            initial,
            config,
            lower_taps=26,
            upper_taps=28,
        )
        model_build_count += 1
        d0_components = build_scalar_objective_components(
            context,
            model,
            electricity_prices=price_profile(config, "flat"),
            remaining_taps=quota_period_target_taps(0),
            continuation_eur_per_heat=0.0,
        )
        active_objectives = list(
            model.component_data_objects(Objective, active=True)
        )
        if len(active_objectives) != 1 or active_objectives[0].name != (
            "temporal_scalar_objective"
        ):
            raise TemporalRepairError("D0 did not construct exactly one scalar objective.")
        if any(
            hasattr(model, name)
            for name in (
                "temporal_tv_abs",
                "temporal_heat_deviation",
                "temporal_inventory_objective",
                "temporal_algebraic_tiebreak_objective",
            )
        ):
            raise TemporalRepairError("D0 found a forbidden regularisation component.")
        if not hasattr(model, "temporal_physical_zero_preservation"):
            raise TemporalRepairError("D0 is missing hard zero production progress.")
        repn = generate_standard_repn(d0_components.total_eur)
        if repn.nonlinear_expr is not None:
            raise TemporalRepairError("D0 scalar objective is not linear.")
        if config["objective_mode"] != OBJECTIVE_MODE:
            raise TemporalRepairError("D0 objective mode is not the scalar contract.")
        checkpoint("D0_scalar_static_contract_complete")

        # Offline core physical certificates: reference state only, order 27, 26, 28.
        certified_models: dict[int, Any] = {}
        certification_rows: dict[int, dict[str, Any]] = {}
        initial_limit = float(repair["feasibility_initial_time_limit_seconds"])
        extended_limit = float(repair["feasibility_extended_time_limit_seconds"])
        adjacent_count: int | None = None
        for count in (27, 26, 28):
            case = HeatCountCertificationCase(
                case_id=f"D1_reference_24h_zero_carry_fixed_{count}",
                count=count,
                start_state=initial,
                calendar_day_length_hours=24,
                remaining_quota_taps=quota_period_target_taps(0),
                physical_horizon_hours=48,
            )
            safe_case = case.case_id
            fixed_model, record, certificate = build_and_solve_heat_count_case(
                context,
                config,
                case,
                adjacent_model=(
                    None if adjacent_count is None else certified_models[adjacent_count]
                ),
                adjacent_case_id=(
                    "" if adjacent_count is None else f"fixed_{adjacent_count}"
                ),
                solve_attempt="initial_60s",
                time_limit_seconds=initial_limit,
                solver_log_path=output / "solver_logs" / f"{safe_case}_initial_60s.log",
            )
            model_build_count += 1
            rows["solver_attempts"].append(
                {**record, "attempt": certificate["solve_attempt"], "status": certificate["feasibility_status"]}
            )
            rows["heat_count_certification"].append(certificate)
            checkpoint(f"{safe_case}_initial_60s")
            if certificate["feasibility_status"] == "unknown":
                fixed_model, record, certificate = build_and_solve_heat_count_case(
                    context,
                    config,
                    case,
                    adjacent_model=(
                        None if adjacent_count is None else certified_models[adjacent_count]
                    ),
                    adjacent_case_id=(
                        "" if adjacent_count is None else f"fixed_{adjacent_count}"
                    ),
                    solve_attempt="extended_mandatory_core",
                    time_limit_seconds=extended_limit,
                    solver_log_path=(
                        output / "solver_logs" / f"{safe_case}_extended_mandatory_core.log"
                    ),
                )
                model_build_count += 1
                rows["solver_attempts"].append(
                    {**record, "attempt": certificate["solve_attempt"], "status": certificate["feasibility_status"]}
                )
                rows["heat_count_certification"].append(certificate)
                checkpoint(f"{safe_case}_extended_mandatory_core")
            if certificate["feasibility_status"] == "proven_infeasible":
                raise TemporalPhysicalInfeasibility(
                    f"Mandatory fixed {count} reference endpoint is physically infeasible."
                )
            if not certificate["feasible_incumbent"]:
                raise TemporalRepairError(
                    f"Mandatory fixed {count} remains unknown after extension."
                )
            certified_models[count] = fixed_model
            certification_rows[count] = certificate
            adjacent_count = count

        # Exact-fingerprint cache, otherwise strict fixed 26/27/28 D-cost endpoints.
        state_sha = _canonical_json_sha256(initial.snapshot())
        flat_prices = price_profile(config, "flat")
        price_sha = hashlib.sha256(
            json.dumps(list(flat_prices), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        expected_calibration_identity = {
            "state_sha256": state_sha,
            "price_profile_sha256": price_sha,
            "contract_version": TEMPORAL_CONTRACT_VERSION,
            "input_sha256": manifest["input_sha256"],
            "endpoint_definition": "fixed_26_27_28; hard_zero_progress; D_only_cost",
        }
        calibration_cache_path = REPO_ROOT / "tmp" / "steel_c1_scalar_continuation_calibration.json"
        cached: dict[str, Any] | None = None
        if calibration_cache_path.exists():
            candidate = json.loads(calibration_cache_path.read_text(encoding="utf-8"))
            if all(candidate.get(key) == expected_calibration_identity[key] for key in expected_calibration_identity):
                cached = candidate
        if cached is None:
            endpoint_costs: dict[int, float] = {}
            for count in (26, 27, 28):
                endpoint_model = build_temporal_model(
                    context,
                    initial,
                    config,
                    lower_taps=26,
                    upper_taps=28,
                    fixed_taps=count,
                )
                model_build_count += 1
                endpoint_components = build_scalar_objective_components(
                    context,
                    endpoint_model,
                    electricity_prices=flat_prices,
                    remaining_taps=count,
                    continuation_eur_per_heat=0.0,
                )
                endpoint_result = _solve_scalar_attempt(
                    endpoint_model,
                    endpoint_components,
                    config,
                    run_case=f"D1_cost_endpoint_{count}",
                    attempt="strict_cost_endpoint",
                    time_limit_seconds=float(repair["solver_time_limit_seconds"]),
                    mip_gap=0.0,
                    solver_log_path=output / "solver_logs" / f"D1_cost_endpoint_{count}.log",
                    fallback_used=False,
                )
                rows["solver_attempts"].append(endpoint_result.record())
                checkpoint(f"D1_cost_endpoint_{count}")
                if endpoint_result.status == "proven_infeasible":
                    raise TemporalPhysicalInfeasibility(
                        f"Strict fixed {count} cost endpoint is physically infeasible."
                    )
                if endpoint_result.status != "optimal":
                    raise TemporalRepairError(
                        f"Strict fixed {count} cost endpoint did not prove optimality."
                    )
                endpoint_violation, endpoint_location = (
                    _maximum_incumbent_violation(endpoint_model)
                )
                endpoint_progress = abs(
                    float(
                        value(
                            endpoint_model.rolling_production_progress_deviation_t
                        )
                    )
                )
                if endpoint_violation > 1e-5 or endpoint_progress > PHYSICAL_TOLERANCE:
                    raise TemporalRepairError(
                        f"Strict fixed {count} endpoint audit failed at "
                        f"{endpoint_location or 'production_progress'}: "
                        f"constraint={endpoint_violation:.9g}, "
                        f"progress={endpoint_progress:.9g}."
                    )
                endpoint_result.audit_status = "pass_strict_cost_endpoint"
                update_attempt_audit(endpoint_result)
                endpoint_costs[count] = float(endpoint_result.procurement_eur)
                certification_rows[count]["cost_check_status"] = "optimal_cost_endpoint"
                certification_rows[count]["represented_cost_D_eur"] = endpoint_costs[count]
            marginal_26_27 = endpoint_costs[27] - endpoint_costs[26]
            marginal_27_28 = endpoint_costs[28] - endpoint_costs[27]
            continuation = (endpoint_costs[28] - endpoint_costs[26]) / 2.0
            if not all(
                math.isfinite(item) and item >= 0.0
                for item in (marginal_26_27, marginal_27_28, continuation)
            ):
                raise TemporalRepairError(
                    "Continuation endpoints have non-finite or negative local marginals."
                )
            calibration = LinearHeatContinuationCalibration(
                continuation_eur_per_heat=continuation,
                endpoint_costs_eur=endpoint_costs,
                marginal_costs_eur_per_heat={
                    "C27_minus_C26": marginal_26_27,
                    "C28_minus_C27": marginal_27_28,
                    "local_marginal_difference": marginal_27_28 - marginal_26_27,
                },
                state_sha256=state_sha,
                price_profile_sha256=price_sha,
                contract_version=TEMPORAL_CONTRACT_VERSION,
                input_sha256=manifest["input_sha256"],
            )
            calibration_payload = _calibration_payload(calibration)
            calibration_cache_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(calibration_cache_path, calibration_payload)
        else:
            calibration_payload = {**cached, "status": "reused_exact_fingerprint_cache"}
            endpoint_costs = {
                int(key): float(value_in)
                for key, value_in in cached["endpoint_costs_eur"].items()
            }
            continuation = float(cached["continuation_eur_per_heat"])
            for count in (26, 27, 28):
                certification_rows[count]["cost_check_status"] = "reused_exact_cost_endpoint"
                certification_rows[count]["represented_cost_D_eur"] = endpoint_costs[count]
        rows["continuation_calibration"] = [calibration_payload]
        checkpoint("D1_continuation_calibration_complete")

        # D1: free count, dynamic 26--28 recoverability band, scalar objective.
        target = quota_period_target_taps(0)
        lower, upper = dynamic_daily_heat_bounds(
            remaining_taps=target,
            today_lower=26,
            today_upper=28,
            future_lower_bounds=[26] * 6,
            future_upper_bounds=[28] * 6,
        )
        d1_model, _, d1_reporting = solve_operation(
            context,
            initial,
            run_case="D1_flat_free_count",
            prices=flat_prices,
            lower_taps=lower,
            upper_taps=upper,
            remaining_taps=target,
            remaining_days=7,
        )
        d1_anchor_rows, d1_gate = append_annual_evaluation(
            d1_model,
            context,
            evaluation_id="D1_flat_provisional",
            period_classification="provisional_single_day_annualised_diagnostic",
            calendar_coverage="one synthetic normal 24-hour day; not a representative year",
            apply_baseline_worsening_gate=False,
        )
        d1_gate["status"] = "pass_provisional" if d1_gate["identity_gate_pass"] else "fail"
        if not d1_gate["identity_gate_pass"]:
            raise TemporalRepairError("D1 accounting identities do not close.")
        checkpoint("D1_flat_and_provisional_annual_anchors_complete")

        # D2: current-day prices only; timing must reverse with price direction.
        d2_models: dict[str, Any] = {}
        tap_centres: dict[str, float] = {}
        for profile in ("cheap_to_expensive", "expensive_to_cheap"):
            profile_model, _, _ = solve_operation(
                context,
                initial,
                run_case=f"D2_{profile}",
                prices=price_profile(config, profile),
                lower_taps=lower,
                upper_taps=upper,
                remaining_taps=target,
                remaining_days=7,
            )
            d2_models[profile] = profile_model
            taps = [
                _component_value(profile_model, "eaf_tap", q)
                for q in range(context.time_grid.execution_steps)
            ]
            tap_centres[profile] = sum(q * item for q, item in enumerate(taps)) / max(
                sum(taps), 1.0
            )
        if tap_centres["cheap_to_expensive"] > tap_centres["expensive_to_cheap"] + PHYSICAL_TOLERANCE:
            raise TemporalRepairError("D2 EAF tap timing moves against the price direction.")

        # D3: causal seven-day free-count operation.
        state = initial
        daily_prices = tuple(
            float(item) for item in repair["causal_week_daily_flat_prices_eur_per_mwh"]
        )
        daily_taps: list[int] = []
        causal_week_totals: list[dict[str, float]] = []
        for day_index, daily_price in enumerate(daily_prices):
            remaining_days = 7 - day_index
            remaining = int(state.eaf_quota_target_taps) - int(
                state.eaf_quota_completed_taps
            )
            physical_upper = min(
                28,
                physical_day_heat_cap(
                    context.time_grid.execution_steps,
                    initial_start_lag1=state.eaf_start_lag1,
                    initial_start_lag2=state.eaf_start_lag2,
                ),
            )
            lower_day, upper_day = dynamic_daily_heat_bounds(
                remaining_taps=remaining,
                today_lower=26,
                today_upper=physical_upper,
                future_lower_bounds=[26] * (remaining_days - 1),
                future_upper_bounds=[28] * (remaining_days - 1),
            )
            run_case = f"D3_causal_week_day_{day_index + 1}"
            day_model, _, reporting = solve_operation(
                context,
                state,
                run_case=run_case,
                prices=[daily_price] * context.time_grid.execution_steps,
                lower_taps=lower_day,
                upper_taps=upper_day,
                remaining_taps=remaining,
                remaining_days=remaining_days,
                week_boundary=day_index == 6,
            )
            causal_week_totals.append(
                _execution_totals(day_model, context.time_grid.execution_steps)
            )
            executed = int(round(reporting["executed_taps"]))
            daily_taps.append(executed)
            before = state
            state = advance_temporal_state(
                context,
                day_model,
                state,
                last_timestamp_utc=f"2026-01-{day_index + 1:02d}T23:45:00+00:00",
            )
            rows["state_handoff_audit"].append(
                state_handoff_row(before, state, run_case=run_case)
            )
            rows["eaf_heat_ledger"].append(
                {
                    "run_case": run_case,
                    "day_index": day_index + 1,
                    "lower_taps": lower_day,
                    "upper_taps": upper_day,
                    "quota_neutral_taps": quota_neutral_daily_taps(
                        remaining, remaining_days
                    ),
                    "executed_taps": executed,
                    "remaining_before": remaining,
                    "remaining_after": remaining - executed,
                    "unfinished_after": state.eaf_start_lag1 + state.eaf_start_lag2,
                    "status": "pass",
                }
            )
            for route, cumulative in state.cumulative_route_progress_t.items():
                previous = before.cumulative_route_progress_t.get(route, 0.0)
                rows["route_progress"].append(
                    {
                        "run_case": run_case,
                        "route": route,
                        "executed_increment_t": cumulative - previous,
                        "cumulative_t": cumulative,
                        "status": "pass",
                    }
                )
            checkpoint(f"{run_case}_state_export_complete")
        if state.eaf_quota_completed_taps != state.eaf_quota_target_taps:
            raise TemporalRepairError("D3 causal week did not close its exact tap target.")
        cheapest_day = min(range(7), key=lambda day: daily_prices[day])
        expensive_day = max(range(7), key=lambda day: daily_prices[day])
        if daily_taps[cheapest_day] < daily_taps[expensive_day]:
            raise TemporalRepairError(
                "D3 predetermined cheapest day receives fewer taps than the expensive day."
            )
        d3_anchor_rows, d3_gate = append_annual_evaluation(
            d1_model,
            context,
            evaluation_id="D3_causal_week",
            period_classification="representative_period_annualised",
            calendar_coverage="seven causal normal days; 168 executed hours; denominator 168 h",
            totals=_sum_execution_totals(causal_week_totals),
            apply_baseline_worsening_gate=True,
        )
        if d3_gate["status"] != "pass":
            raise TemporalRepairError(
                "D3 annual operational anchors or exact accounting identities regressed."
            )

        # A carry flag alone is not a physically reached state: inventories,
        # rates, scrap budgets and completed taps must come from the same
        # predecessor solution.  Produce explicit witnesses first, then use
        # those exported states in normal- and DST-day scalar solves.
        reached_carry_states = [initial]
        for carry_template in reachable_eaf_carry_in_states(initial)[1:]:
            lag1 = int(carry_template.eaf_start_lag1)
            lag2 = int(carry_template.eaf_start_lag2)
            carry_id = f"lag{lag1}{lag2}"
            witness_case = f"D3_carry_witness_{carry_id}"
            witness_model, _, _ = solve_operation(
                context,
                initial,
                run_case=witness_case,
                prices=flat_prices,
                lower_taps=26,
                upper_taps=28,
                remaining_taps=target,
                remaining_days=7,
                forced_carry_lags=(lag1, lag2),
            )
            reached_state = advance_temporal_state(
                context,
                witness_model,
                initial,
                last_timestamp_utc="2025-12-31T23:45:00+00:00",
            )
            if (
                reached_state.eaf_start_lag1,
                reached_state.eaf_start_lag2,
            ) != (lag1, lag2):
                raise TemporalRepairError(
                    f"{witness_case} did not export its forced EAF carry state."
                )
            rows["state_handoff_audit"].append(
                state_handoff_row(initial, reached_state, run_case=witness_case)
            )
            reached_carry_states.append(reached_state)
            checkpoint(f"{witness_case}_state_export_complete")

        for carry_state in reached_carry_states[1:]:
            carry_id = f"lag{carry_state.eaf_start_lag1}{carry_state.eaf_start_lag2}"
            remaining = int(carry_state.eaf_quota_target_taps) - int(
                carry_state.eaf_quota_completed_taps
            )
            lower_carry, upper_carry = dynamic_daily_heat_bounds(
                remaining_taps=remaining,
                today_lower=26,
                today_upper=min(
                    28,
                    physical_day_heat_cap(
                        96,
                        initial_start_lag1=carry_state.eaf_start_lag1,
                        initial_start_lag2=carry_state.eaf_start_lag2,
                    ),
                ),
                future_lower_bounds=(26,) * 5,
                future_upper_bounds=(28,) * 5,
            )
            solve_operation(
                context,
                carry_state,
                run_case=f"D3_reachable_carry_{carry_id}",
                prices=flat_prices,
                lower_taps=lower_carry,
                upper_taps=upper_carry,
                remaining_taps=remaining,
                remaining_days=6,
            )

        for day_hours in (23, 25):
            day_context = _calendar_day_context(
                context,
                calendar_day_length_hours=day_hours,
                physical_horizon_hours=48,
            )
            for carry_state in reached_carry_states:
                carry_id = (
                    f"lag{carry_state.eaf_start_lag1}{carry_state.eaf_start_lag2}"
                )
                remaining = int(carry_state.eaf_quota_target_taps) - int(
                    carry_state.eaf_quota_completed_taps
                )
                remaining_days = 7 if carry_state is initial else 6
                future_count = remaining_days - 1
                lower_dst, upper_dst = dynamic_daily_heat_bounds(
                    remaining_taps=remaining,
                    today_lower=26,
                    today_upper=min(
                        28,
                        physical_day_heat_cap(
                            day_context.time_grid.execution_steps,
                            initial_start_lag1=carry_state.eaf_start_lag1,
                            initial_start_lag2=carry_state.eaf_start_lag2,
                        ),
                    ),
                    future_lower_bounds=(26,) * future_count,
                    future_upper_bounds=(28,) * future_count,
                )
                solve_operation(
                    day_context,
                    carry_state,
                    run_case=f"D3_DST_{day_hours}h_{carry_id}_free_count",
                    prices=[75.0] * day_context.time_grid.execution_steps,
                    lower_taps=lower_dst,
                    upper_taps=upper_dst,
                    remaining_taps=remaining,
                    remaining_days=remaining_days,
                )

        # Offline hard-terminal week stresses; no economic hierarchy or IIS.
        for pattern_id, pattern in extreme_week_patterns(26, 28, target).items():
            week_model = build_temporal_model(
                context,
                initial,
                config,
                lower_taps=26,
                upper_taps=28,
                planning_horizon_hours=168,
                hard_inventory_terminal=True,
            )
            model_build_count += 1
            add_week_heat_contract(
                week_model,
                target_taps=target,
                daily_pattern=pattern,
            )
            week_case_id = f"D3_week_{pattern_id}"
            week_record = _solve_zero_objective_feasibility(
                week_model,
                config,
                run_case=week_case_id,
                write_iis_on_infeasible=False,
                time_limit_seconds=initial_limit,
                solver_log_path=output / "solver_logs" / f"{week_case_id}_initial_60s.log",
            )
            rows["solver_attempts"].append(
                {**week_record, "attempt": "initial_60s", "status": week_record["feasibility_status"]}
            )
            week_case = HeatCountCertificationCase(
                case_id=week_case_id,
                count=-1,
                start_state=initial,
                calendar_day_length_hours=24,
                remaining_quota_taps=target,
                physical_horizon_hours=168,
                terminal_policy="hard_week_terminal",
            )
            certificate = {
                **heat_count_case_metadata(week_case, config),
                "physical_day_cap_taps": physical_day_heat_cap(96),
                "feasible_incumbent": week_record["feasible_incumbent"],
                "objective_bound": week_record["objective_bound"],
                "mip_gap": week_record["mip_gap"],
                "solver_status": week_record["solver_status"],
                "termination_condition": week_record["termination_condition"],
                "feasibility_status": week_record["feasibility_status"],
                "iis_status": week_record["iis_status"],
                "iis_path": week_record["iis_path"],
                "cost_check_status": "not_applicable_week_pattern",
                "represented_cost_D_eur": "",
                "solve_attempt": "initial_60s",
                "time_limit_seconds": initial_limit,
                "warm_start_used": False,
                "warm_start_source_case": "",
                "warm_start_value_count": 0,
                "solver_log_path": week_record["solver_log_path"],
            }
            rows["heat_count_certification"].append(certificate)
            checkpoint(f"{week_case_id}_initial_60s")
            if week_record["feasibility_status"] == "unknown":
                week_record = _solve_zero_objective_feasibility(
                    week_model,
                    config,
                    run_case=week_case_id,
                    write_iis_on_infeasible=False,
                    time_limit_seconds=extended_limit,
                    solver_log_path=output / "solver_logs" / f"{week_case_id}_extended.log",
                )
                rows["solver_attempts"].append(
                    {**week_record, "attempt": "extended_mandatory_week", "status": week_record["feasibility_status"]}
                )
                extended_certificate = {
                    **certificate,
                    "feasible_incumbent": week_record["feasible_incumbent"],
                    "objective_bound": week_record["objective_bound"],
                    "mip_gap": week_record["mip_gap"],
                    "solver_status": week_record["solver_status"],
                    "termination_condition": week_record["termination_condition"],
                    "feasibility_status": week_record["feasibility_status"],
                    "solve_attempt": "extended_mandatory_week",
                    "time_limit_seconds": extended_limit,
                    "solver_log_path": week_record["solver_log_path"],
                }
                rows["heat_count_certification"].append(extended_certificate)
                checkpoint(f"{week_case_id}_extended_mandatory_week")
            if week_record["feasibility_status"] == "proven_infeasible":
                raise TemporalPhysicalInfeasibility(
                    f"D3 hard-terminal {pattern_id} week is physically infeasible."
                )
            if not week_record["feasible_incumbent"]:
                raise TemporalRepairError(
                    f"D3 hard-terminal {pattern_id} week remains unknown."
                )

        # D4: negative prices cannot override must-run, generator or WAG identities.
        solve_operation(
            context,
            initial,
            run_case="D4_negative_price",
            prices=price_profile(config, "negative_price"),
            lower_taps=lower,
            upper_taps=upper,
            remaining_taps=target,
            remaining_days=7,
        )

        # D5: strict oracle plus operational repeats and 72-hour tail.
        d5_cases: list[dict[str, Any]] = []
        strict_model = build_temporal_model(
            context,
            initial,
            config,
            lower_taps=lower,
            upper_taps=upper,
            planning_horizon_hours=48,
        )
        model_build_count += 1
        strict_components = build_scalar_objective_components(
            context,
            strict_model,
            electricity_prices=flat_prices,
            remaining_taps=target,
            continuation_eur_per_heat=continuation,
        )
        strict_result = _solve_scalar_attempt(
            strict_model,
            strict_components,
            config,
            run_case="D5_strict_scalar_oracle",
            attempt="bounded_strict_oracle",
            time_limit_seconds=float(repair["d5_strict_time_limit_seconds"]),
            mip_gap=float(repair["d5_strict_relative_gap"]),
            mip_gap_abs_eur=float(repair["d5_strict_absolute_gap_eur"]),
            solver_log_path=output / "solver_logs" / "D5_strict_scalar_oracle.log",
            fallback_used=False,
        )
        store_attempt(strict_result, "D5_strict_scalar_oracle")
        if strict_result.status == "proven_infeasible":
            raise TemporalPhysicalInfeasibility("D5 strict scalar oracle is infeasible.")
        if strict_result.incumbent_objective_eur is None:
            raise TemporalRepairError("D5 bounded strict oracle has no incumbent.")
        strict_allowed_gap = max(
            float(repair["d5_strict_absolute_gap_eur"]),
            float(repair["d5_strict_relative_gap"])
            * abs(float(strict_result.incumbent_objective_eur)),
        )
        if (
            strict_result.absolute_gap_eur is None
            or float(strict_result.absolute_gap_eur) > strict_allowed_gap
        ):
            raise TemporalRepairError(
                "D5 bounded strict oracle exceeds its certified economic envelope."
            )
        strict_reporting = audit_scalar_incumbent(
            context,
            strict_model,
            initial,
            strict_components,
            strict_result,
            run_case="D5_strict_scalar_oracle",
            lower_taps=lower,
            upper_taps=upper,
            remaining_taps=target,
            remaining_days=7,
        )
        strict_state = advance_temporal_state(
            context,
            strict_model,
            initial,
            last_timestamp_utc="2026-01-01T23:45:00+00:00",
        )
        strict_signature = _executed_operational_signature(
            strict_model, context.time_grid.execution_steps
        )
        rows["state_handoff_audit"].append(
            state_handoff_row(
                initial,
                strict_state,
                run_case="D5_strict_scalar_oracle",
            )
        )
        d5_cases.append(
            {
                "case": "strict_scalar_oracle",
                "model": strict_model,
                "result": strict_result,
                "state": strict_state,
                "signature": strict_signature,
                "reporting": strict_reporting,
            }
        )
        for case_id, warm in (
            ("runtime_6s", False),
            ("cold_repeat", False),
            ("warm_repeat", True),
        ):
            case_model, case_result, case_reporting = solve_operation(
                context,
                initial,
                run_case=f"D5_{case_id}",
                prices=flat_prices,
                lower_taps=lower,
                upper_taps=upper,
                remaining_taps=target,
                remaining_days=7,
                planning_horizon_hours=48,
                warm_source=strict_model if warm else None,
            )
            case_state = advance_temporal_state(
                context,
                case_model,
                initial,
                last_timestamp_utc="2026-01-01T23:45:00+00:00",
            )
            signature = _executed_operational_signature(
                case_model, context.time_grid.execution_steps
            )
            if signature != strict_signature:
                raise TemporalRepairError(
                    f"D5 {case_id} changes executed EAF/commitment integer decisions."
                )
            state_drift = _state_numeric_drift(strict_state, case_state, config)
            if state_drift:
                raise TemporalRepairError(
                    f"D5 {case_id} changes carried physical state: {state_drift}."
                )
            objective_delta = abs(
                float(case_result.incumbent_objective_eur)
                - float(strict_result.incumbent_objective_eur)
            )
            envelope = max(
                MONEY_PRESERVATION_FLOOR_EUR,
                float(strict_result.absolute_gap_eur or 0.0)
                + float(case_result.absolute_gap_eur or 0.0),
            )
            if objective_delta > envelope + MONEY_PRESERVATION_FLOOR_EUR:
                raise TemporalRepairError(
                    f"D5 {case_id} objective delta exceeds its certified envelope."
                )
            rows["state_handoff_audit"].append(
                state_handoff_row(
                    initial,
                    case_state,
                    run_case=f"D5_{case_id}",
                )
            )
            d5_cases.append(
                {
                    "case": case_id,
                    "model": case_model,
                    "result": case_result,
                    "state": case_state,
                    "signature": signature,
                    "reporting": case_reporting,
                }
            )

        # The flat-price continuation calibration deliberately leaves the
        # 26--28 endpoints scalar-equivalent.  First prove that a free 72 h
        # model has the same certified economic optimum, even if it selects a
        # different member of that set.  Then prove that the exact canonical
        # 48 h executed prefix and exported state admit a 72 h continuation.
        free_tail_model, free_tail_result, free_tail_reporting = solve_operation(
            context,
            initial,
            run_case="D5_tail_72h_unconstrained_equivalence",
            prices=flat_prices,
            lower_taps=lower,
            upper_taps=upper,
            remaining_taps=target,
            remaining_days=7,
            planning_horizon_hours=72,
        )
        free_tail_signature = _executed_discrete_signature(
            free_tail_model, context.time_grid.execution_steps
        )
        free_tail_objective_delta = abs(
            float(free_tail_result.incumbent_objective_eur)
            - float(strict_result.incumbent_objective_eur)
        )
        free_tail_envelope = (
            float(strict_result.absolute_gap_eur or 0.0)
            + float(free_tail_result.absolute_gap_eur or 0.0)
            + 2.0 * MONEY_PRESERVATION_FLOOR_EUR
        )
        if free_tail_objective_delta > free_tail_envelope:
            raise TemporalRepairError(
                "D5 free 72 h tail changes the certified scalar optimum."
            )
        rows["baseline_delta"].extend(
            (
                {
                    "run_case": "D5_tail_72h_unconstrained_equivalence",
                    "entity": "scalar_optimum_set",
                    "metric": "executed_taps",
                    "prechange_value": strict_reporting["executed_taps"],
                    "postchange_value": free_tail_reporting["executed_taps"],
                    "delta": (
                        free_tail_reporting["executed_taps"]
                        - strict_reporting["executed_taps"]
                    ),
                    "unit": "heat",
                    "status": (
                        "pass_same_signature"
                        if free_tail_signature == strict_signature
                        else "pass_set_valued_scalar_optimum"
                    ),
                },
                {
                    "run_case": "D5_tail_72h_unconstrained_equivalence",
                    "entity": "scalar_optimum_set",
                    "metric": "total_objective_eur",
                    "prechange_value": strict_result.incumbent_objective_eur,
                    "postchange_value": free_tail_result.incumbent_objective_eur,
                    "delta": free_tail_objective_delta,
                    "unit": "EUR",
                    "status": "pass_within_certified_envelope",
                },
            )
        )
        checkpoint("D5_tail_72h_unconstrained_equivalence_complete")

        tail_model, tail_result, tail_reporting = solve_operation(
            context,
            initial,
            run_case="D5_tail_72h_extension_certificate",
            prices=flat_prices,
            lower_taps=lower,
            upper_taps=upper,
            remaining_taps=target,
            remaining_days=7,
            planning_horizon_hours=72,
            fixed_executed_source=strict_model,
        )
        tail_state = advance_temporal_state(
            context,
            tail_model,
            initial,
            last_timestamp_utc="2026-01-01T23:45:00+00:00",
        )
        tail_signature = _executed_discrete_signature(
            tail_model, context.time_grid.execution_steps
        )
        if tail_signature != strict_signature:
            raise TemporalRepairError(
                "D5 72 h extension did not preserve the fixed executed signature."
            )
        tail_state_drift = _state_numeric_drift(strict_state, tail_state, config)
        if tail_state_drift:
            raise TemporalRepairError(
                f"D5 72 h extension changes carried state: {tail_state_drift}."
            )
        rows["state_handoff_audit"].append(
            state_handoff_row(
                initial,
                tail_state,
                run_case="D5_tail_72h_extension_certificate",
            )
        )
        d5_cases.append(
            {
                "case": "tail_72h_extension_certificate",
                "model": tail_model,
                "result": tail_result,
                "state": tail_state,
                "signature": tail_signature,
                "reporting": tail_reporting,
            }
        )

        d5_reference_values: dict[str, float] | None = None
        for case in d5_cases:
            case_id = str(case["case"])
            anchor_rows, gate = append_annual_evaluation(
                case["model"],
                context,
                evaluation_id=f"D5_{case_id}",
                period_classification="robustness_single_day_annualised_diagnostic",
                calendar_coverage=(
                    "one synthetic 24-hour executed day; robustness comparison only"
                ),
                apply_baseline_worsening_gate=False,
            )
            if d5_reference_values is None:
                d5_reference_values = {
                    str(row["metric_id"]): float(row["model_annual_equivalent"])
                    for row in anchor_rows
                }
                drift: list[dict[str, Any]] = []
            else:
                drift = material_annual_drift(
                    anchor_rows,
                    d5_reference_values,
                    relative_tolerance=float(
                        repair["d5_annual_anchor_drift_tolerance_fraction"]
                    ),
                )
                rows["annual_anchor_delta_vs_last_accepted"].extend(
                    annual_anchor_delta_rows(
                        anchor_rows,
                        baseline_id="D5_strict_scalar_oracle",
                        baseline_values=d5_reference_values,
                    )
                )
            gate["material_annual_anchor_drift"] = drift
            gate["reference_evaluation_id"] = "D5_strict_scalar_oracle"
            gate["status"] = "pass" if gate["identity_gate_pass"] and not drift else "fail"
            if gate["status"] != "pass":
                raise TemporalRepairError(
                    f"D5 {case_id} causes material annual-anchor drift."
                )

        if model_build_count > int(manifest["planned_model_build_count_upper_bound"]):
            raise TemporalRepairError(
                f"Model-build manifest upper bound exceeded: {model_build_count}."
            )
        if len(rows["solver_attempts"]) > int(
            manifest["planned_solve_attempt_count_upper_bound"]
        ):
            raise TemporalRepairError(
                f"Solve-attempt manifest upper bound exceeded: {len(rows['solver_attempts'])}."
            )
        decision = {
            "decision": "deterministic_operational_repair_pass_ready_for_single_s10_smoke",
            "status": "pass",
            "objective_mode": OBJECTIVE_MODE,
            "temporal_contract_version": TEMPORAL_CONTRACT_VERSION,
            "certified_daily_heat_band": list(certified_band),
            "continuation_eur_per_heat": continuation,
            "d5_tail_72h_validation": (
                "free_scalar_equivalence_plus_fixed_executed_prefix_extension"
            ),
            "d5_free_tail_set_valued_optimum": (
                free_tail_signature != strict_signature
            ),
            "model_build_count": model_build_count,
            "solve_attempt_count": len(rows["solver_attempts"]),
            "full_four_week_matrix_authorized": False,
            "s10_solve_started": False,
            "stochastic_solve_started": False,
        }
    except TemporalPhysicalInfeasibility as exc:
        if model is not None and hasattr(
            model, "temporal_coke_hot_iron_route_recursive_recoverability"
        ):
            conflict = recursive_coke_hot_iron_conflict_diagnostic(model)
        else:
            conflict = (
                must_run_bof_conflict_diagnostic(model)
                if model is not None and hasattr(model, "sinter_balance")
                else None
            )
        decision = {
            "decision": "physically_infeasible_under_source_contract",
            "status": "fail",
            "reason": str(exc),
            "objective_mode": OBJECTIVE_MODE,
            "model_build_count": model_build_count,
            "solve_attempt_count": len(rows["solver_attempts"]),
            "source_contract_conflict": conflict,
            "full_four_week_matrix_authorized": False,
            "s10_solve_started": False,
            "stochastic_solve_started": False,
        }
    except Exception as exc:
        decision = {
            "decision": "needs_bounded_fix",
            "status": "fail",
            "reason": f"{type(exc).__name__}: {exc}",
            "objective_mode": OBJECTIVE_MODE,
            "model_build_count": model_build_count,
            "solve_attempt_count": len(rows["solver_attempts"]),
            "full_four_week_matrix_authorized": False,
            "s10_solve_started": False,
            "stochastic_solve_started": False,
        }
    annual_gate_status = (
        "pass"
        if decision["status"] == "pass"
        and annual_gate_evaluations
        and all(str(item.get("status", "fail")).startswith("pass") for item in annual_gate_evaluations)
        else "incomplete_at_first_hard_failure"
        if decision["status"] != "pass"
        else "fail"
    )
    rows["annual_operational_anchor_gate"] = [
        {
            "status": annual_gate_status,
            "decision": decision["decision"],
            "phase5e_static_gate": static_anchor_gate,
            "evaluations": annual_gate_evaluations,
            "last_accepted_deterministic_baseline": (
                "steel_c5_phase5e_source_backed_anchor_closure_v1_20260727"
            ),
            "annual_anchors_enter_constraints": False,
            "annual_anchors_enter_objectives": False,
            "residual_plugs_added": False,
            "partial_boundary_shortfall_is_failure": False,
            "full_four_week_matrix_authorized": False,
        }
    ]
    manifest = {
        **manifest,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "actual_model_build_count": model_build_count,
        "actual_solve_attempt_count": len(rows["solver_attempts"]),
        "stopped_at_first_hard_failure": decision["status"] != "pass",
    }
    _write_outputs(output, rows, manifest, decision)
    return decision


def _annual_calendar_contract(
    config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], set[date]]:
    """Build the maintenance-excluded local calendar without price data."""

    year = config["deterministic_temporal_repair"]["causal_flat_year"]
    calendar_year = int(year["calendar_year"])
    timezone_name = str(year["timezone"])
    if timezone_name != "Europe/Amsterdam":
        raise TemporalRepairError("The annual C1 calendar must remain Europe/Amsterdam.")
    if str(year["calendar_contract_version"]) != CALENDAR_CONTRACT_VERSION:
        raise TemporalRepairError("The annual calendar contract version changed.")
    if int(year["maintenance_hours_represented"]) != 0:
        raise TemporalRepairError("The central annual calendar must exclude maintenance.")
    zone = ZoneInfo(timezone_name)

    first = date(calendar_year, 1, 1)
    last = date(calendar_year + 1, 1, 1)
    days: list[dict[str, Any]] = []
    current = first
    cumulative_available = 0
    while current < last:
        start_local = datetime.combine(current, wall_time.min, tzinfo=zone)
        end_local = datetime.combine(current + timedelta(days=1), wall_time.min, tzinfo=zone)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        execution_steps = int(round((end_utc - start_utc).total_seconds() / 900.0))
        unavailable_steps = 0
        available_steps = execution_steps - unavailable_steps
        cumulative_available += available_steps
        days.append(
            {
                "date": current,
                "day_length_hours": execution_steps // 4,
                "execution_steps": execution_steps,
                "eaf_major_outage": False,
                "eaf_weekly_outage": False,
                "eaf_unavailable_steps": unavailable_steps,
                "eaf_available_steps": available_steps,
                "cumulative_eaf_available_steps": cumulative_available,
                "start_utc": start_utc,
            }
        )
        current += timedelta(days=1)
    if sum(int(item["day_length_hours"]) for item in days) != HOURS_PER_YEAR:
        raise TemporalRepairError("The annual local calendar does not cover exactly 8760 hours.")
    return days, set()


def _eaf_maintenance_intervals_for_horizon(
    *,
    start_utc: datetime,
    horizon_steps: int,
    major_dates: set[date],
    timezone_name: str,
    weekly_weekday: int = 6,
    weekly_duration_steps: int = 32,
) -> tuple[int, ...]:
    del start_utc, major_dates, weekly_weekday, weekly_duration_steps
    if timezone_name != "Europe/Amsterdam" or int(horizon_steps) <= 0:
        raise TemporalRepairError("Invalid maintenance-excluded horizon request.")
    return ()


def _annual_heat_schedule(
    days: Sequence[Mapping[str, Any]],
    *,
    annual_target_taps: int,
    daily_tolerance: int,
    quota_period_days: int | None = None,
    quota_neutral_upper_cap: int | None = None,
) -> list[dict[str, int]]:
    if int(daily_tolerance) < 0:
        raise TemporalRepairError("Annual EAF reporting tolerance cannot be negative.")
    if quota_period_days is not None and int(quota_period_days) <= 0:
        raise TemporalRepairError("Annual EAF quota period must contain days.")
    group_size = len(days) if quota_period_days is None else int(quota_period_days)
    schedule: list[dict[str, int]] = []
    cumulative_hours = 0
    previous_cumulative_target = 0
    for period_index, start in enumerate(range(0, len(days), group_size)):
        period = days[start : start + group_size]
        period_hours = sum(int(item["day_length_hours"]) for item in period)
        cumulative_hours += period_hours
        cumulative_target = cumulative_eaf_target_taps(cumulative_hours)
        period_target = cumulative_target - previous_cumulative_target
        previous_cumulative_target = cumulative_target
        period_occupancy_steps = sum(int(item["execution_steps"]) for item in period)
        if period_occupancy_steps < period_target * 3:
            raise TemporalPhysicalInfeasibility(
                "The maintenance-excluded calendar lacks quota-period occupancy."
            )
        proportional_targets: list[int] = []
        physical_caps = [int(item["execution_steps"]) // 3 for item in period]
        cumulative_period_steps = 0
        previous_period_target = 0
        for item in period:
            cumulative_period_steps += int(item["execution_steps"])
            allocated = round_half_up(
                Decimal(period_target)
                * Decimal(cumulative_period_steps)
                / Decimal(period_occupancy_steps)
            )
            target = allocated - previous_period_target
            previous_period_target = allocated
            proportional_targets.append(target)
        physical_lowers = [min(20, cap) for cap in physical_caps]
        adjusted_targets = [
            max(target, lower)
            for target, lower in zip(
                proportional_targets, physical_lowers, strict=True
            )
        ]
        excess = sum(adjusted_targets) - period_target
        while excess > 0:
            candidates = [
                day_index
                for day_index, (target, lower) in enumerate(
                    zip(adjusted_targets, physical_lowers, strict=True)
                )
                if target > lower
            ]
            if not candidates:
                raise TemporalPhysicalInfeasibility(
                    "The EAF quota period cannot respect its daily physical minima."
                )
            selected = max(
                candidates,
                key=lambda day_index: (
                    adjusted_targets[day_index] - physical_lowers[day_index],
                    -day_index,
                ),
            )
            adjusted_targets[selected] -= 1
            excess -= 1
        cumulative_adjusted_target = 0
        for offset, (item, target, physical_cap) in enumerate(
            zip(period, adjusted_targets, physical_caps, strict=True)
        ):
            if target > physical_cap:
                raise TemporalPhysicalInfeasibility(
                    f"Calendar-duration EAF target {target} exceeds cap {physical_cap}."
                )
            if quota_period_days is None:
                lower = physical_lowers[offset]
                upper = physical_cap
            else:
                lower = min(
                    physical_cap,
                    max(physical_lowers[offset], target - int(daily_tolerance)),
                )
                upper = max(
                    lower,
                    min(physical_cap, target + int(daily_tolerance)),
                )
                if quota_neutral_upper_cap is not None:
                    upper = min(upper, int(quota_neutral_upper_cap))
                if lower > upper:
                    raise TemporalPhysicalInfeasibility(
                        "The quota-neutral EAF day band is empty."
                    )
            cumulative_adjusted_target += target
            schedule.append(
                {
                    "target": target,
                    # The calendar-duration target is reporting-only. Operational
                    # days retain the governed free-count band; quota-period
                    # recoverability narrows it causally near the boundary.
                    "lower": lower,
                    "upper": upper,
                    "physical_cap": physical_cap,
                    "quota_period_index": period_index,
                    "quota_period_target": period_target,
                    "quota_period_cumulative_target": cumulative_adjusted_target,
                    "quota_period_boundary": int(offset == len(period) - 1),
                }
            )
    if previous_cumulative_target != int(annual_target_taps):
        raise TemporalRepairError("Annual EAF availability allocation does not close.")
    return schedule


def _calendar_year_inventory_terminal_targets(
    initial_inventory_targets: Mapping[str, float],
    *,
    final_day: bool,
    full_year: bool,
) -> Mapping[str, float] | None:
    """Apply hard inventory closure only at a real calendar-year boundary."""

    if not (final_day and full_year):
        return None
    return dict(initial_inventory_targets)


def _annual_recoverable_execution_bounds(
    *,
    terminal_lower_t: float,
    terminal_upper_t: float,
    completed_t: float,
    future_physical_max_t: float,
    mandatory_future_minimum_t: float = 0.0,
) -> tuple[float, float]:
    """Return today's non-prescriptive band that preserves terminal recovery."""

    values = (
        float(terminal_lower_t),
        float(terminal_upper_t),
        float(completed_t),
        float(future_physical_max_t),
        float(mandatory_future_minimum_t),
    )
    if not all(math.isfinite(item) for item in values):
        raise TemporalRepairError("Annual recoverability inputs must be finite.")
    lower_terminal, upper_terminal, completed, future_max, future_minimum = values
    if (
        lower_terminal < 0.0
        or upper_terminal < lower_terminal
        or future_max < 0.0
        or future_minimum < 0.0
    ):
        raise TemporalRepairError("Annual recoverability inputs are invalid.")
    lower_today = max(0.0, lower_terminal - completed - future_max)
    upper_today = upper_terminal - completed - future_minimum
    if upper_today < -PHYSICAL_TOLERANCE or lower_today > upper_today + PHYSICAL_TOLERANCE:
        raise TemporalPhysicalInfeasibility(
            "The accepted rolling state cannot recover the annual terminal band."
        )
    return lower_today, max(0.0, upper_today)


def _annual_progress_corridor_execution_bounds(
    *,
    planned_cumulative_t: float,
    physical_tail_corridor_t: float,
    executed_lead_corridor_t: float | None = None,
    terminal_lower_t: float,
    terminal_upper_t: float,
    completed_t: float,
    future_physical_max_t: float,
    mandatory_future_minimum_t: float = 0.0,
) -> tuple[float, float]:
    """Intersect terminal recovery with a causal one-tail progress corridor."""

    recoverable_lower, recoverable_upper = _annual_recoverable_execution_bounds(
        terminal_lower_t=terminal_lower_t,
        terminal_upper_t=terminal_upper_t,
        completed_t=completed_t,
        future_physical_max_t=future_physical_max_t,
        mandatory_future_minimum_t=mandatory_future_minimum_t,
    )
    planned = float(planned_cumulative_t)
    corridor = float(physical_tail_corridor_t)
    lead_corridor = (
        corridor
        if executed_lead_corridor_t is None
        else float(executed_lead_corridor_t)
    )
    completed = float(completed_t)
    if (
        not math.isfinite(planned)
        or not math.isfinite(corridor)
        or not math.isfinite(lead_corridor)
        or corridor < 0.0
        or lead_corridor < 0.0
    ):
        raise TemporalRepairError("Annual progress corridor inputs are invalid.")
    progress_lower = max(0.0, planned - corridor - completed)
    progress_upper = planned + lead_corridor - completed
    lower = max(recoverable_lower, progress_lower)
    upper = min(recoverable_upper, max(0.0, progress_upper))
    if lower > upper + PHYSICAL_TOLERANCE:
        raise TemporalPhysicalInfeasibility(
            "The accepted rolling state left the annual physical-tail progress corridor."
        )
    return lower, upper


def add_annual_upper_recoverability(
    model: Any,
    *,
    execution_steps: int,
    hsm_final_t_per_t_slab: float,
    terminal_bounds_t: Mapping[str, tuple[float, float]],
    completed_t: Mapping[str, float],
    future_physical_max_t: Mapping[str, float],
) -> None:
    """Reserve mandatory future output below every annual metric upper.

    The future-minimum variables are physical/recoverability witnesses only;
    they are absent from the objective.  Besides every metric's own hard
    annual lower, HSM and DSP reserve the future output forced by the final-
    product lower when the alternative route runs at its physical maximum.
    """

    metrics = (
        "final_product",
        "bof_liquid_steel",
        "hsm_final_output",
        "dsp_final_output",
        "imported_slab",
    )
    expected = set(metrics)
    for label, mapping in (
        ("terminal bounds", terminal_bounds_t),
        ("completed values", completed_t),
        ("future maxima", future_physical_max_t),
    ):
        if set(mapping) != expected:
            raise TemporalRepairError(
                f"Annual upper recoverability {label} must cover {sorted(expected)}."
            )
    hsm_yield = float(hsm_final_t_per_t_slab)
    steps = int(execution_steps)
    if steps <= 0 or hsm_yield <= 0.0:
        raise TemporalRepairError("Annual upper recoverability dimensions are invalid.")
    execution = {
        "final_product": sum(model.final_product_output[q] for q in range(steps)),
        "bof_liquid_steel": sum(
            model.bof_crude_steel_output[q] for q in range(steps)
        ),
        "hsm_final_output": sum(
            hsm_yield * model.hot_strip_mill[q] for q in range(steps)
        ),
        "dsp_final_output": sum(
            model.dsp_final_product_output[q] for q in range(steps)
        ),
        "imported_slab": sum(
            model.imported_slab_to_hsm[q] for q in range(steps)
        ),
    }
    model.ANNUAL_UPPER_RECOVERABILITY_METRICS = Set(
        initialize=metrics, ordered=True
    )
    model.annual_mandatory_future_minimum_t = Var(
        model.ANNUAL_UPPER_RECOVERABILITY_METRICS,
        domain=NonNegativeReals,
    )
    model.annual_own_lower_future_minimum = Constraint(
        model.ANNUAL_UPPER_RECOVERABILITY_METRICS,
        rule=lambda m, metric: m.annual_mandatory_future_minimum_t[metric]
        >= float(terminal_bounds_t[metric][0])
        - float(completed_t[metric])
        - execution[metric],
    )
    model.annual_upper_recoverability = Constraint(
        model.ANNUAL_UPPER_RECOVERABILITY_METRICS,
        rule=lambda m, metric: execution[metric]
        <= float(terminal_bounds_t[metric][1])
        - float(completed_t[metric])
        - m.annual_mandatory_future_minimum_t[metric],
    )
    final_lower = float(terminal_bounds_t["final_product"][0])
    completed_product = float(completed_t["final_product"])
    model.annual_cross_route_future_minimum = ConstraintList()
    model.annual_cross_route_future_minimum.add(
        model.annual_mandatory_future_minimum_t["dsp_final_output"]
        >= final_lower
        - completed_product
        - execution["final_product"]
        - float(future_physical_max_t["hsm_final_output"])
    )
    model.annual_cross_route_future_minimum.add(
        model.annual_mandatory_future_minimum_t["hsm_final_output"]
        >= final_lower
        - completed_product
        - execution["final_product"]
        - float(future_physical_max_t["dsp_final_output"])
    )
    model.annual_cross_route_future_minimum.add(
        model.annual_mandatory_future_minimum_t["final_product"]
        >= model.annual_mandatory_future_minimum_t["hsm_final_output"]
        + model.annual_mandatory_future_minimum_t["dsp_final_output"]
    )
    model.annual_upper_recoverability_formula = (
        "upper_today=annual_upper-cumulative_completed-mandatory_future_minimum"
    )


def run_causal_flat_year(
    *,
    config_path: str | Path = CONFIG_PATH,
    run_id: str = "causal_flat_year_2025_v1",
    maximum_days: int | None = None,
    stop_after_contract_days: int | None = None,
    output_root_override: str | Path | None = None,
) -> dict[str, Any]:
    """Run the causal flat-price C1 calendar year and re-evaluate anchors.

    The central annual calendar represents normal operation and excludes all
    maintenance and outage intervals. DST day lengths remain explicit.
    """

    config = load_temporal_repair_config(config_path)
    repair = config["deterministic_temporal_repair"]
    annual = repair["causal_flat_year"]
    output_root = (
        REPO_ROOT / str(annual["output_root"])
        if output_root_override is None
        else Path(output_root_override)
    )
    output = output_root / str(run_id)
    if output.exists() and any(output.iterdir()):
        raise TemporalRepairError(f"Refusing to overwrite non-empty annual run: {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "solver_logs").mkdir(exist_ok=True)
    calendar, major_dates = _annual_calendar_contract(config)
    if maximum_days is not None and stop_after_contract_days is not None:
        raise TemporalRepairError(
            "maximum_days and stop_after_contract_days are mutually exclusive."
        )
    if maximum_days is not None:
        requested = int(maximum_days)
        if requested <= 0 or requested > len(calendar):
            raise TemporalRepairError("Annual smoke day count is outside the calendar.")
        calendar = calendar[:requested]
    execution_calendar = calendar
    if stop_after_contract_days is not None:
        requested = int(stop_after_contract_days)
        if requested <= 0 or requested >= len(calendar):
            raise TemporalRepairError(
                "Contract-preserving annual prefix must stop before day 365."
            )
        execution_calendar = calendar[:requested]
    full_year = len(calendar) == 365
    full_year_execution = len(execution_calendar) == len(calendar) == 365
    annual_target_taps = cumulative_eaf_target_taps(
        sum(int(item["day_length_hours"]) for item in calendar)
    )
    if full_year and annual_target_taps != cumulative_eaf_target_taps(HOURS_PER_YEAR):
        raise TemporalRepairError("Annual EAF target construction changed.")
    heat_schedule = _annual_heat_schedule(
        calendar,
        annual_target_taps=annual_target_taps,
        daily_tolerance=int(annual["heat_target_daily_tolerance"]),
        quota_period_days=7,
        quota_neutral_upper_cap=int(
            annual["routine_quota_normal_day_upper_taps"]
        ),
    )
    manifest = {
        "run_id": run_id,
        "run_family_id": "steel_c6_causal_flat_year_v1_20260803",
        "temporal_contract_version": TEMPORAL_CONTRACT_VERSION,
        "calendar_contract_version": CALENDAR_CONTRACT_VERSION,
        "objective_mode": OBJECTIVE_MODE,
        "calendar_year": int(annual["calendar_year"]),
        "calendar_day_count": len(execution_calendar),
        "annual_contract_day_count": len(calendar),
        "executed_hours_planned": sum(
            int(item["day_length_hours"]) for item in execution_calendar
        ),
        "partial_year_reporting_contract": (
            "full_year_execution"
            if full_year_execution
            else "partial_year_contract_preserved_no_terminal_claim"
        ),
        "annual_target_taps": annual_target_taps,
        "eaf_quota_period_policy": "seven_calendar_days_cumulative_rounding",
        "output_policy": str(annual["output_policy"]),
        "run_class": str(annual["run_class"]),
        "lineage_role": str(annual["lineage_role"]),
        "planned_model_build_count_upper_bound": (
            len(execution_calendar) + 3
        ),
        "planned_solve_attempt_count_upper_bound": (
            len(execution_calendar) * 2 + 3
        ),
        "estimated_output_size_mb_upper_bound": float(
            annual["estimated_output_size_mb_upper_bound"]
        ),
        "operation_label": "normal_operation_maintenance_excluded",
        "eaf_maintenance_calendar_status": "maintenance_excluded",
        "maintenance_hours_represented": 0,
        "annual_availability_comparable": False,
        "major_outage_certified": False,
        "drp_outage_physical_status": str(annual["drp_outage_physical_status"]),
        "annual_validation_feasibility_tolerance": float(
            annual["solver_feasibility_tolerance"]
        ),
        "annual_anchors_enter_constraints": False,
        "annual_anchors_enter_objectives": False,
        "full_four_week_matrix_authorized": False,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(output / "run_manifest.json", manifest)
    print(
        json.dumps(
            {
                "before_first_solve": True,
                "output_root": str(output),
                "planned_model_build_count_upper_bound": manifest[
                    "planned_model_build_count_upper_bound"
                ],
                "planned_solve_attempt_count_upper_bound": manifest[
                    "planned_solve_attempt_count_upper_bound"
                ],
                "planned_artifact_count": 10,
                "estimated_output_size_mb_upper_bound": manifest[
                    "estimated_output_size_mb_upper_bound"
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )

    base_context = prepare_temporal_context(config)
    initial = replace(
        initial_temporal_state(config),
        episode_id=f"causal_flat_year_{annual['calendar_year']}",
        eaf_quota_period_id=(
            f"calendar_year_{annual['calendar_year']}_quota_"
            f"{heat_schedule[0]['quota_period_index']:03d}"
        ),
        eaf_quota_target_taps=int(heat_schedule[0]["quota_period_target"]),
        eaf_quota_completed_taps=0,
    )
    state = initial
    daily_rows: list[dict[str, Any]] = []
    attempt_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    daily_kpis: list[dict[str, Any]] = []
    totals: dict[str, float] = {}
    annual_completed_taps = 0
    model_build_count = 0
    last_model: Any | None = None
    decision: dict[str, Any]

    def write_progress(phase: str) -> None:
        _write_json(
            output / "progress_current.json",
            {
                "phase": phase,
                "completed_days": len(daily_rows),
                "solve_attempt_count": len(attempt_rows),
                "last_day": daily_rows[-1] if daily_rows else None,
                "full_four_week_matrix_authorized": False,
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        _write_json(output / "annual_solver_attempts.json", attempt_rows)
        _write_json(
            output / "cumulative_execution_totals.json",
            {
                "period_classification": (
                    "full_year" if full_year_execution else "partial_year_8688h"
                ),
                "executed_hours": int(state.executed_hours),
                "completed_days": len(daily_rows),
                "totals": totals,
                "not_full_year_validated": not full_year_execution,
                "full_four_week_matrix_authorized": False,
            },
        )
        if daily_rows:
            _write_csv(
                output / "annual_daily_progress.csv",
                daily_rows,
                tuple(daily_rows[0]),
            )

    try:
        # Strict annual-state continuation calibration on the same physical
        # reference day. The quota identifier changes, so old statehash caches
        # are deliberately not reused.
        endpoint_costs: dict[int, float] = {}
        process_limits_t_per_interval: Mapping[str, tuple[float, float]] | None = None
        flat_reference = price_profile(config, "flat")
        for count in (26, 27, 28):
            endpoint_model = build_temporal_model(
                base_context,
                initial,
                config,
                lower_taps=26,
                upper_taps=28,
                fixed_taps=count,
            )
            model_build_count += 1
            components = build_scalar_objective_components(
                base_context,
                endpoint_model,
                electricity_prices=flat_reference,
                remaining_taps=count,
                continuation_eur_per_heat=0.0,
            )
            result = _solve_scalar_attempt(
                endpoint_model,
                components,
                config,
                run_case=f"annual_calibration_fixed_{count}",
                attempt="strict_cost_endpoint",
                time_limit_seconds=float(repair["solver_time_limit_seconds"]),
                mip_gap=0.0,
                solver_log_path=output / "solver_logs" / f"annual_calibration_{count}.log",
                fallback_used=False,
                feasibility_tolerance=float(
                    annual["solver_feasibility_tolerance"]
                ),
            )
            attempt_rows.append(result.record())
            write_progress(f"annual_calibration_fixed_{count}")
            if result.status != "optimal":
                raise TemporalRepairError(
                    f"Annual continuation endpoint {count} is not optimal."
                )
            violation, location = _maximum_incumbent_violation(endpoint_model)
            if violation > 1e-5:
                raise TemporalRepairError(
                    f"Annual endpoint {count} violates {location}: {violation}."
                )
            endpoint_costs[count] = float(result.procurement_eur)
            if process_limits_t_per_interval is None:
                process_limits_t_per_interval = dict(
                    endpoint_model.temporal_process_limits_t_per_interval
                )
        continuation = (endpoint_costs[28] - endpoint_costs[26]) / 2.0
        if continuation < 0.0 or not math.isfinite(continuation):
            raise TemporalRepairError("Annual continuation calibration is invalid.")
        _write_json(
            output / "continuation_calibration.json",
            {
                "status": "strict_annual_state_endpoints_optimal",
                "endpoint_costs_eur": endpoint_costs,
                "continuation_eur_per_heat": continuation,
                "state_sha256": _canonical_json_sha256(initial.snapshot()),
                "temporal_contract_version": TEMPORAL_CONTRACT_VERSION,
            },
        )

        target_final_product = (
            float(base_context.config["annual_reference_target_mt_y"])
            * 1_000_000.0
            * sum(int(item["day_length_hours"]) for item in calendar)
            / HOURS_PER_YEAR
        )
        total_calendar_hours = sum(
            int(item["day_length_hours"]) for item in calendar
        )
        if process_limits_t_per_interval is None:
            raise TemporalRepairError("Annual process-capacity interface is missing.")
        interval_hours = float(base_context.time_grid.time_step_hours)
        hsm_yield = float(base_context.c1_reference_routing["hsm_final_t_per_t_slab"])
        bof_hot_metal_per_t_ls = float(
            base_context.config["bof_material_balance"][
                "hot_metal_t_per_t_liquid_steel"
            ]
        )
        annual_route_max_t_h = {
            "bof_liquid_steel": float(
                process_limits_t_per_interval["basic_oxygen_furnace"][1]
            )
            / interval_hours
            / bof_hot_metal_per_t_ls,
            "hsm_final_output": float(
                process_limits_t_per_interval["hot_strip_mill"][1]
            )
            / interval_hours
            * hsm_yield,
            "dsp_final_output": float(
                base_context.c1_reference_routing[
                    "dsp_final_product_horizon_cap_t"
                ]
            )
            / float(base_context.time_grid.horizon_hours),
            "imported_slab": float(
                base_context.c1_reference_routing["imported_slab_max_t_h"]
            ),
        }
        final_product_max_t_h = (
            annual_route_max_t_h["hsm_final_output"]
            + annual_route_max_t_h["dsp_final_output"]
        )
        total_execution_steps = sum(
            int(item["execution_steps"]) for item in calendar
        )
        route_share = ANNUAL_EAF_ROUTE_T / (3_400_000.0 + ANNUAL_EAF_ROUTE_T)
        cumulative_product_weight = 0.0
        cumulative_calendar_hours = 0
        reference_bands = base_context.c1_reference_routing[
            "reference_validation_bands"
        ]
        annual_route_terminal_bounds = {
            route_id: (
                float(bounds["lower_t"])
                * total_calendar_hours
                / float(base_context.time_grid.horizon_hours),
                float(bounds["upper_t"])
                * total_calendar_hours
                / float(base_context.time_grid.horizon_hours),
            )
            for route_id, bounds in reference_bands.items()
            if route_id != "eaf_liquid_steel"
        }
        route_state_keys = {
            "bof_liquid_steel": "C1_BOF_liquid_steel_output_t_h",
            "hsm_final_output": "C1_HSM_final_product_output_t",
            "dsp_final_output": "C1_DSP_final_product_output_t",
            "imported_slab": "C1_imported_slab_to_HSM_t_h",
        }
        initial_inventory_targets = {
            "dri_inventory": 0.0,
            "coke_inventory": 180.0,
            "sinter_inventory": 320.0,
            "hot_iron_inventory": 250.0,
            "cold_slab_inventory": 12_500.0,
        }
        for index, (day, scheduled) in enumerate(
            zip(execution_calendar, heat_schedule, strict=False)
        ):
            day_hours = int(day["day_length_hours"])
            day_context = _calendar_day_context(
                base_context,
                calendar_day_length_hours=day_hours,
                physical_horizon_hours=48,
            )
            maintenance_intervals = _eaf_maintenance_intervals_for_horizon(
                start_utc=day["start_utc"],
                horizon_steps=day_context.time_grid.horizon_steps,
                major_dates=major_dates,
                timezone_name=str(annual["timezone"]),
            )
            day_context = replace(
                day_context,
                eaf_heat_state_parameters=replace(
                    day_context.eaf_heat_state_parameters,
                    maintenance_intervals=maintenance_intervals,
                ),
            )
            remaining_taps = int(state.eaf_quota_target_taps) - int(
                state.eaf_quota_completed_taps
            )
            period_index = int(scheduled["quota_period_index"])
            period_future = [
                item
                for item in heat_schedule[index + 1 :]
                if int(item["quota_period_index"]) == period_index
            ]
            future_lower = [item["lower"] for item in period_future]
            future_upper = [item["upper"] for item in period_future]
            lower_taps, upper_taps = dynamic_daily_heat_bounds(
                remaining_taps=remaining_taps,
                today_lower=scheduled["lower"],
                today_upper=scheduled["upper"],
                future_lower_bounds=future_lower,
                future_upper_bounds=future_upper,
            )
            cumulative_heat_target = int(
                scheduled["quota_period_cumulative_target"]
            )
            heat_progress_tolerance = int(
                annual["heat_target_daily_tolerance"]
            )
            completed_before = int(state.eaf_quota_completed_taps)
            lower_taps = max(
                lower_taps,
                cumulative_heat_target
                - heat_progress_tolerance
                - completed_before,
            )
            upper_taps = min(
                upper_taps,
                cumulative_heat_target
                + heat_progress_tolerance
                - completed_before,
            )
            if lower_taps > upper_taps:
                raise TemporalPhysicalInfeasibility(
                    "The rolling state left the maintenance-excluded EAF quota corridor."
                )
            day_weight = (
                (1.0 - route_share) * day_hours / total_calendar_hours
                + route_share
                * int(day["execution_steps"])
                / total_execution_steps
            )
            cumulative_product_weight += day_weight
            cumulative_calendar_hours += day_hours
            future_hours = total_calendar_hours - cumulative_calendar_hours
            terminal_tolerance = float(
                annual["final_product_year_terminal_tolerance_t"]
            )
            product_bounds = _annual_progress_corridor_execution_bounds(
                planned_cumulative_t=(
                    target_final_product * cumulative_product_weight
                ),
                physical_tail_corridor_t=(
                    final_product_max_t_h * 48.0
                ),
                executed_lead_corridor_t=final_product_max_t_h * 24.0,
                terminal_lower_t=max(0.0, target_final_product - terminal_tolerance),
                terminal_upper_t=target_final_product + terminal_tolerance,
                completed_t=float(state.cumulative_production_t),
                future_physical_max_t=final_product_max_t_h * future_hours,
            )
            final_day = index == len(calendar) - 1
            executed_route_bounds: dict[str, tuple[float, float]] = {}
            for route_id, terminal_bounds in annual_route_terminal_bounds.items():
                completed = float(
                    state.cumulative_route_progress_t.get(
                        route_state_keys[route_id], 0.0
                    )
                )
                terminal_center = (terminal_bounds[0] + terminal_bounds[1]) / 2.0
                cumulative_fraction = (
                    cumulative_calendar_hours / total_calendar_hours
                    if route_id in {"bof_liquid_steel", "imported_slab"}
                    else cumulative_product_weight
                )
                executed_route_bounds[route_id] = (
                    _annual_progress_corridor_execution_bounds(
                        planned_cumulative_t=terminal_center * cumulative_fraction,
                        physical_tail_corridor_t=(
                            annual_route_max_t_h[route_id] * 48.0
                        ),
                        terminal_lower_t=terminal_bounds[0],
                        terminal_upper_t=terminal_bounds[1],
                        completed_t=completed,
                        future_physical_max_t=(
                            annual_route_max_t_h[route_id] * future_hours
                        ),
                    )
                )
            model = build_temporal_model(
                day_context,
                state,
                config,
                lower_taps=lower_taps,
                upper_taps=upper_taps,
                planning_horizon_hours=48,
                week_boundary=bool(scheduled["quota_period_boundary"]),
                final_product_execution_bounds_t=product_bounds,
                execution_inventory_terminal_targets_t=(
                    _calendar_year_inventory_terminal_targets(
                        initial_inventory_targets,
                        final_day=final_day,
                        full_year=full_year,
                    )
                ),
                route_reference_policy="annual_recoverable_calendar",
                executed_route_bounds_t=executed_route_bounds,
            )
            add_annual_upper_recoverability(
                model,
                execution_steps=day_context.time_grid.execution_steps,
                hsm_final_t_per_t_slab=hsm_yield,
                terminal_bounds_t={
                    "final_product": (
                        max(0.0, target_final_product - terminal_tolerance),
                        target_final_product + terminal_tolerance,
                    ),
                    **annual_route_terminal_bounds,
                },
                completed_t={
                    "final_product": float(state.cumulative_production_t),
                    **{
                        route_id: float(
                            state.cumulative_route_progress_t.get(
                                route_state_keys[route_id], 0.0
                            )
                        )
                        for route_id in annual_route_terminal_bounds
                    },
                },
                future_physical_max_t={
                    "final_product": final_product_max_t_h * future_hours,
                    **{
                        route_id: annual_route_max_t_h[route_id] * future_hours
                        for route_id in annual_route_terminal_bounds
                    },
                },
            )
            model_build_count += 1
            if last_model is not None:
                _copy_adjacent_warm_start(last_model, model)
            components = build_scalar_objective_components(
                day_context,
                model,
                electricity_prices=(
                    float(annual["flat_electricity_price_eur_per_mwh"]),
                )
                * day_context.time_grid.execution_steps,
                remaining_taps=remaining_taps,
                continuation_eur_per_heat=continuation,
            )
            accepted, attempts = solve_scalar_operational_model(
                model,
                components,
                config,
                run_case=f"annual_day_{index + 1:03d}_{day['date'].isoformat()}",
                solver_log_root=output / "solver_logs",
                warm_start=last_model is not None,
                mip_gap_override=0.0,
                feasibility_tolerance_override=float(
                    annual["solver_feasibility_tolerance"]
                ),
            )
            attempt_rows.extend(item.record() for item in attempts)
            violation, location = _maximum_incumbent_violation(model)
            if violation > 1e-5:
                raise TemporalRepairError(
                    f"Annual day {index + 1} violates {location}: {violation}."
                )
            if abs(float(value(model.rolling_production_progress_deviation_t))) > PHYSICAL_TOLERANCE:
                raise TemporalRepairError(
                    f"Annual day {index + 1} has non-zero production progress deviation."
                )
            energy_rows = energy_audit_rows(
                model, run_case=f"annual_day_{index + 1:03d}"
            )
            if any(item["status"] == "fail" for item in energy_rows):
                raise TemporalRepairError(
                    f"Annual day {index + 1} fails WAG/NG/flare precedence."
                )
            before = state
            advanced_state = advance_temporal_state(
                day_context,
                model,
                state,
                last_timestamp_utc=(
                    day["start_utc"]
                    + timedelta(minutes=15 * (day_context.time_grid.execution_steps - 1))
                ).isoformat(),
            )
            executed_taps = int(round(value(model.executed_eaf_taps)))
            annual_completed_taps += executed_taps
            remaining_after_execution = (
                int(advanced_state.eaf_quota_target_taps)
                - int(advanced_state.eaf_quota_completed_taps)
            )
            if bool(scheduled["quota_period_boundary"]):
                if remaining_after_execution != 0:
                    raise TemporalRepairError(
                        f"EAF quota period {period_index} did not close."
                    )
                if index + 1 < len(heat_schedule):
                    following = heat_schedule[index + 1]
                    state = replace(
                        advanced_state,
                        eaf_quota_period_id=(
                            f"calendar_year_{annual['calendar_year']}_quota_"
                            f"{int(following['quota_period_index']):03d}"
                        ),
                        eaf_quota_target_taps=int(
                            following["quota_period_target"]
                        ),
                        eaf_quota_completed_taps=0,
                    )
                else:
                    state = advanced_state
            else:
                state = advanced_state
            state_rows.append(
                state_handoff_row(
                    before,
                    state,
                    run_case=f"annual_day_{index + 1:03d}",
                )
            )
            executed_product = sum(
                _component_value(model, "final_product_output", q)
                for q in range(day_context.time_grid.execution_steps)
            )
            day_totals = _execution_totals(
                model, day_context.time_grid.execution_steps
            )
            totals = _sum_execution_totals((totals, day_totals))
            kpi_rows = temporal_kpi_rows(
                model,
                before,
                config,
                run_case=f"annual_day_{index + 1:03d}",
            )
            for entity in (
                "sintering_plant",
                "blast_furnace_6",
                "basic_oxygen_furnace",
                "hot_strip_mill",
                "direct_sheet_plant",
            ):
                for metric in (
                    "normalized_total_variation",
                    "largest_rate_jump_including_day_boundary",
                    "quarterhour_rate_change_count",
                ):
                    match = next(
                        (
                            row
                            for row in kpi_rows
                            if row["entity"] == entity and row["metric"] == metric
                        ),
                        None,
                    )
                    if match is not None:
                        daily_kpis.append(
                            {
                                "day_index": index + 1,
                                "date": day["date"].isoformat(),
                                **match,
                            }
                        )
            daily_rows.append(
                {
                    "day_index": index + 1,
                    "date": day["date"].isoformat(),
                    "calendar_day_length_hours": day_hours,
                    "eaf_weekly_outage": bool(day["eaf_weekly_outage"]),
                    "eaf_major_outage": bool(day["eaf_major_outage"]),
                    "eaf_unavailable_intervals": int(day["eaf_unavailable_steps"]),
                    "heat_target": int(scheduled["target"]),
                    "lower_taps": lower_taps,
                    "upper_taps": upper_taps,
                    "executed_taps": executed_taps,
                    "quota_period_index": period_index,
                    "quota_period_target": int(scheduled["quota_period_target"]),
                    "quota_period_cumulative_target": int(
                        scheduled["quota_period_cumulative_target"]
                    ),
                    "quota_period_boundary": bool(
                        scheduled["quota_period_boundary"]
                    ),
                    "remaining_taps_after": remaining_after_execution,
                    "product_lower_t": product_bounds[0],
                    "product_upper_t": product_bounds[1],
                    "executed_final_product_t": executed_product,
                    "cumulative_final_product_t": state.cumulative_production_t,
                    "solver_status": accepted.status,
                    "incumbent_objective_eur": accepted.incumbent_objective_eur,
                    "best_bound_eur": accepted.best_bound_eur,
                    "relative_gap": accepted.relative_gap,
                    "runtime_seconds": accepted.runtime_seconds,
                    "fallback_used": accepted.fallback_used,
                    "state_sha256": _canonical_json_sha256(state.snapshot()),
                    "status": "pass",
                }
            )
            write_progress(f"annual_day_{index + 1:03d}_accepted")
            last_model = model

        if full_year_execution and annual_completed_taps != annual_target_taps:
            raise TemporalRepairError("The annual EAF tap target did not close.")
        final_product_residual: float | str = (
            float(state.cumulative_production_t) - target_final_product
            if full_year_execution
            else ""
        )
        if full_year_execution and abs(float(final_product_residual)) > float(
            annual["final_product_year_terminal_tolerance_t"]
        ) + PHYSICAL_TOLERANCE:
            raise TemporalRepairError("The annual final-product target did not close.")
        anchor_rows, anchor_gate = annual_operational_anchor_rows(
            totals,
            evaluation_id=f"causal_flat_calendar_{annual['calendar_year']}",
            executed_hours=int(state.executed_hours),
            period_classification=(
                "causal_calendar_year"
                if full_year_execution
                else "partial_year_8688h"
            ),
            calendar_coverage=(
                f"{len(execution_calendar)} sequential local calendar days; "
                "flat price; normal operation; maintenance and major outage excluded"
            ),
        )
        last_accepted = _last_accepted_annual_values()
        delta_rows = annual_anchor_delta_rows(
            anchor_rows,
            baseline_id="steel_c5_phase5e_source_backed_anchor_closure_v1_20260727",
            baseline_values=last_accepted,
        )
        anchor_worsening = unexpected_anchor_worsening(
            anchor_rows,
            last_accepted,
            relative_tolerance=float(
                repair["annual_anchor_worsening_tolerance_fraction"]
            ),
        )
        core_ids = {
            "site_final_product",
            "sinter_output",
            "hot_metal_output",
            "bof_liquid_steel",
            "eaf_liquid_steel",
            "dri_output",
            "bof_scrap",
            "eaf_scrap",
            "site_scrap",
            "hbi_import",
        }
        core_failures: list[dict[str, Any]] = []
        tolerance = float(annual["core_material_anchor_relative_tolerance"])
        for row in anchor_rows:
            if row["metric_id"] not in core_ids or row["source_value"] == "":
                continue
            source = float(row["source_value"])
            observed = float(row["model_annual_equivalent"])
            relative = abs(observed - source) / max(abs(source), 1.0)
            if relative > tolerance:
                core_failures.append(
                    {
                        "metric_id": row["metric_id"],
                        "source_value": source,
                        "model_value": observed,
                        "relative_deviation": relative,
                        "tolerance": tolerance,
                    }
                )
        anchor_gate.update(
            {
                "status": (
                    "partial_year_8688h_not_full_year_validated"
                    if not full_year_execution
                    else (
                        "pass_normal_operation_maintenance_excluded"
                        if (
                            anchor_gate["identity_gate_pass"]
                            and not core_failures
                            and not anchor_worsening
                        )
                        else "needs_bounded_fix"
                    )
                ),
                "core_material_anchor_failures": core_failures,
                "core_material_anchor_relative_tolerance": tolerance,
                "unexpected_anchor_worsening": anchor_worsening,
                "annual_anchor_worsening_tolerance_fraction": float(
                    repair["annual_anchor_worsening_tolerance_fraction"]
                ),
                "operation_label": "normal_operation_maintenance_excluded",
                "maintenance_hours_represented": 0,
                "annual_availability_comparable": False,
                "major_outage_certified": False,
                "eaf_routine_outages_physically_represented": False,
                "eaf_major_outage_physically_represented": False,
                "eaf_major_outage_source_gap": (
                    "requires_separate_source_backed_outage_contract"
                ),
                "drp_outages_physically_represented": False,
                "drp_outage_source_gap": str(annual["drp_outage_physical_status"]),
                "annual_anchors_enter_constraints": False,
                "annual_anchors_enter_objectives": False,
                "residual_plugs_added": False,
                "full_four_week_matrix_authorized": False,
            }
        )
        decision = {
            "decision": (
                "partial_year_8688h_generated_not_full_year_validated"
                if not full_year_execution
                else (
                    "annual_normal_operation_maintenance_excluded_anchor_re_evaluation_complete"
                    if anchor_gate["status"].startswith("pass")
                    else "needs_bounded_fix"
                )
            ),
            "status": (
                "pass"
                if not full_year_execution or anchor_gate["status"].startswith("pass")
                else "fail"
            ),
            "calendar_days": len(execution_calendar),
            "executed_hours": state.executed_hours,
            "eaf_taps": annual_completed_taps,
            "final_product_t": state.cumulative_production_t,
            "final_product_residual_t": final_product_residual,
            "model_build_count": model_build_count,
            "solve_attempt_count": len(attempt_rows),
            "continuation_eur_per_heat": continuation,
            "annual_anchor_gate_status": anchor_gate["status"],
            "s10_solve_started": False,
            "stochastic_solve_started": False,
            "full_four_week_matrix_authorized": False,
        }
        _write_csv(
            output / "annual_operational_anchor_results.csv",
            anchor_rows,
            _output_schemas()["annual_operational_anchor_results"],
        )
        _write_csv(
            output / "annual_anchor_delta_vs_last_accepted.csv",
            delta_rows,
            _output_schemas()["annual_anchor_delta_vs_last_accepted"],
        )
        _write_json(output / "annual_operational_anchor_gate.json", anchor_gate)
    except TemporalPhysicalInfeasibility as exc:
        decision = {
            "decision": "physically_infeasible_under_source_contract",
            "status": "fail",
            "reason": str(exc),
            "completed_days": len(daily_rows),
            "model_build_count": model_build_count,
            "solve_attempt_count": len(attempt_rows),
            "s10_solve_started": False,
            "stochastic_solve_started": False,
            "full_four_week_matrix_authorized": False,
        }
    except Exception as exc:
        decision = {
            "decision": "needs_bounded_fix",
            "status": "fail",
            "reason": f"{type(exc).__name__}: {exc}",
            "completed_days": len(daily_rows),
            "model_build_count": model_build_count,
            "solve_attempt_count": len(attempt_rows),
            "s10_solve_started": False,
            "stochastic_solve_started": False,
            "full_four_week_matrix_authorized": False,
        }
    if state_rows:
        _write_csv(
            output / "state_handoff_audit.csv",
            state_rows,
            _output_schemas()["state_handoff_audit"],
        )
    if daily_kpis:
        _write_csv(
            output / "annual_daily_plant_kpis.csv",
            daily_kpis,
            tuple(daily_kpis[0]),
        )
    write_progress("complete" if decision["status"] == "pass" else "stopped_at_failure")
    _write_json(output / "gate_decision.json", decision)
    _write_json(
        output / "run_manifest.json",
        {
            **manifest,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "actual_model_build_count": model_build_count,
            "actual_solve_attempt_count": len(attempt_rows),
            "stopped_at_first_hard_failure": decision["status"] != "pass",
        },
    )
    return decision


__all__ = [
    "ANNUAL_EAF_ROUTE_T",
    "CONTINUOUS_ASSETS",
    "HeatCountCertificationCase",
    "LinearHeatContinuationCalibration",
    "OBJECTIVE_MODE",
    "ScalarObjectiveComponents",
    "ScalarSolveResult",
    "TEMPORAL_CONTRACT_VERSION",
    "TemporalPhysicalInfeasibility",
    "TemporalRepairError",
    "add_total_variation_tier",
    "annual_anchor_delta_rows",
    "annual_operational_anchor_rows",
    "add_execution_boundary_carry_witness",
    "build_scalar_objective_components",
    "build_temporal_model",
    "cumulative_eaf_target_taps",
    "dynamic_daily_heat_bounds",
    "_fix_executed_solution_prefix",
    "heat_count_case_metadata",
    "heat_count_expansion_order",
    "initial_temporal_state",
    "load_temporal_repair_config",
    "objective_variable_names",
    "physical_day_heat_cap",
    "prepare_temporal_context",
    "quota_neutral_daily_taps",
    "quota_period_target_taps",
    "recursive_coke_hot_iron_conflict_diagnostic",
    "reachable_eaf_carry_in_states",
    "round_half_up",
    "run_temporal_repair",
    "run_causal_flat_year",
    "scalar_reporting_kpis",
    "solve_scalar_operational_model",
    "validate_temporal_state",
]
