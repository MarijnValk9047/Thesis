"""S4.4c unified C0/C1 physical modelbuilder smoke regression.

This stage validates that the S4.4b input layer can drive a common physical
model interface. It intentionally does not implement DA price-taking.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Collection, Mapping

from pyomo.environ import (
    Binary,
    ConcreteModel,
    Constraint,
    ConstraintList,
    Expression,
    NonNegativeReals,
    Objective,
    RangeSet,
    Set,
    UnitInterval,
    SolverFactory,
    Var,
    maximize,
    minimize,
    value,
)
from pyomo.contrib.fbbt.fbbt import compute_bounds_on_expr, fbbt
from pyomo.core.expr.visitor import identify_variables

from scripts.optimisation_performance import (
    StructuralSignature,
    StructuralTemplateCache,
    dst_shape_for_steps,
    fingerprint_paths,
    stable_hash,
    validate_performance_mode,
)

from .model import collect_model_stats
from .reporting import iso_utc, now_utc, repo_rel, resolve_git_commit, write_json
from .s4_0b_guardrail_regression_runner import _mip_gap
from .s4_4b_unified_input_validator import validate_unified_dev_inputs
from .s4_4b5a_asymmetric_correction import CORRECTED_INPUT_DIR
from .wag_milp_input_contract import load_governed_wag_factor_maps
from .wag_development_controller_contract import (
    DevelopmentControllerProfile,
    bf_hot_stove_mwh_per_t_hot_metal,
    hsm_reheat_mwh_per_t_hrc,
    hsm_rolling_electricity_mwh_per_t_hrc,
    load_development_controller_profile,
)
from .validation_tolerance_policy import (
    SOLVER_NUMERICAL_TOLERANCE,
    TERMINAL_STATE_TOLERANCE_T,
    ValidationTolerancePolicyError,
    canonical_json_sha256,
    constraint_family_rule,
    constraint_registry_fingerprint,
    policy_contract as validation_tolerance_policy_contract,
    resolve_policy_contract,
    validation_record,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
ALLOCATION_ENDPOINT_ACCURACY_SCHEMA = "steel_endpoint_solver_accuracy_v1"
ALLOCATION_ENDPOINT_RELATIVE_MIP_GAP = 0.0
ALLOCATION_ENDPOINT_ABSOLUTE_MIP_GAP_MWH = 0.001
ALLOCATION_ENDPOINT_BOUND_COMPARISON_EPSILON_MWH = 1e-9
S44C_DIR = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "s4_4c_unified_physical_regression"
)
DEFAULT_REPORT_JSON_PATH = S44C_DIR / "s4_4c_unified_physical_regression_report.json"
DEFAULT_REPORT_CSV_PATH = S44C_DIR / "s4_4c_unified_physical_regression_report.csv"
DEFAULT_HOURLY_CSV_PATH = S44C_DIR / "s4_4c_unified_physical_hourly.csv"
DEFAULT_BUILD_AUDIT_CSV_PATH = S44C_DIR / "s4_4c_configuration_build_audit.csv"
DEFAULT_CONSTRAINT_AUDIT_CSV_PATH = S44C_DIR / "s4_4c_constraint_audit.csv"
DEFAULT_STAGE_GATE_JSON_PATH = S44C_DIR / "s4_4c_stage_gate.json"
DEFAULT_STAGE_GATE_CSV_PATH = S44C_DIR / "s4_4c_stage_gate.csv"

# S4.4b5a is the current validated development-input surface.  The older
# s4_4b_unified_dev_inputs package is preserved as a historical contract but
# no longer passes its own blocker-preservation validation.
S44B_INPUT_DIR = CORRECTED_INPUT_DIR.resolve()

CONFIGURATIONS = (
    "C0_current_BF_BOF_reference",
    "C1_phase1_BF_BOF_plus_DRP_EAF",
)
EXECUTABLE_STATUSES = {"development_only", "selected_development_input_candidate"}
POLICY_MODE = "price_naive_static_or_cost_smoothed"
MODE_ID = "s4_4c_unified_physical_static_regression"
TOLERANCE = 1e-6
SOLVER_PREFERENCE = ("gurobi", "gurobi_direct", "appsi_highs", "highs", "cbc", "glpk")
_STEEL_TABLE_CACHE: dict[str, UnifiedInputTables] = {}
_STEEL_VALIDATION_CACHE: dict[str, dict[str, Any]] = {}
_STEEL_INPUT_FINGERPRINT_CACHE: dict[str, tuple[tuple[tuple[str, int, int], ...], str]] = {}
_STEEL_STRUCTURAL_TEMPLATE_CACHE = StructuralTemplateCache()
MJ_PER_MWH = 3600.0
PJ_TO_MWH = 277777.77777777775
# Compatibility exports for historical C5 diagnostics.  Unlike the former
# literals, both maps now come from the single governed selected-input adapter.
SELECTED_WAG_LHV_MJ_PER_NM3, FLARE_CO2_EF_T_PER_MWH = load_governed_wag_factor_maps()
KGF_UNDERFIRING_MWH_PER_T_COKE = 3.5 / 3.6
SINTER_COG_MWH_PER_T_SINTER = 0.067 / 3.6
BOILER_WAG_PLACEHOLDER_CAP_MWH_H = 3.0 * PJ_TO_MWH / 8760.0
BOILER_TOTAL_PLACEHOLDER_MWH_H = 6.0 * PJ_TO_MWH / 8760.0
ETA_BOILER_STEAM = 0.90
C1_EMISSIONS_PROXY_RETAINED_BFBOF_SHARE = 3.9 / (3.9 + 6.0)
C1_RETAINED_BFBOF_TARGET_SHARE = 2525.0 / 5905.2
C0_SITE_ELECTRICITY_PROXY_MWH_H = 3_000_000.0 / 8760.0
WAG_TO_POWER_EFFICIENCY = 0.3715
VATTENFALL_VELSEN25_WAG_CAP_NM3_H = 600_000.0
VATTENFALL_IJM01_WAG_CAP_NM3_H = 300_000.0
VATTENFALL_TOTAL_WAG_CAP_NM3_H = VATTENFALL_VELSEN25_WAG_CAP_NM3_H + VATTENFALL_IJM01_WAG_CAP_NM3_H
FLARING_CO2_DIAGNOSTIC_EUR_PER_T = 75.0
NG_COMBUSTION_T_CO2_PER_MWH_LHV = 56.1 * 3.6 / 1000.0
FORBIDDEN_TERMS = {
    "product_revenue",
    "export_revenue",
    "grid_tariff",
    "WAG_direct_market_value",
    "CO2_ETS",
}
DEVELOPMENT_CONTROLLER_ACTIVATION_PHASES = (
    "none",
    "hsm",
    "hsm_pefa",
    "hsm_pefa_boiler",
    "full",
    "full_electricity_boundary",
)


class S44CModelBuilderError(ValueError):
    """Raised when S4.4c inputs or model construction are invalid."""


def _model_value_or_zero(model: ConcreteModel, component_name: str, t: int) -> float:
    """Read an optional shared-boundary expression without crossing configuration scope."""

    if not hasattr(model, component_name):
        return 0.0
    return float(value(getattr(model, component_name)[t]))


def _costed_c0_ng_reporting_value(raw_value: float) -> float:
    """Preserve cost-ledger precision for opt-in C0 named-NG reporting fields."""

    return round(float(raw_value), 12)


def _development_controller_flags(phase: str) -> dict[str, bool]:
    """Return the opt-in controller set for one fixed-schedule development round."""

    if phase not in DEVELOPMENT_CONTROLLER_ACTIVATION_PHASES:
        raise S44CModelBuilderError(
            f"Unsupported development controller activation phase: {phase}. "
            f"Expected one of {DEVELOPMENT_CONTROLLER_ACTIVATION_PHASES}."
        )
    order = {name: index for index, name in enumerate(DEVELOPMENT_CONTROLLER_ACTIVATION_PHASES)}
    return {
        "hsm": order[phase] >= order["hsm"],
        "pefa": order[phase] >= order["hsm_pefa"],
        "boiler": order[phase] >= order["hsm_pefa_boiler"],
        "generator": order[phase] >= order["full"],
        "electricity_boundary": order[phase] >= order["full_electricity_boundary"],
    }


@dataclass(frozen=True)
class UnifiedInputTables:
    input_dir: Path
    tables: dict[str, list[dict[str, str]]]


@dataclass(frozen=True)
class ModelTimeGrid:
    """Explicit physical duration and interval count for the steel MILP.

    Model flow variables remain quantities per interval.  Source capacities
    and fixed services are hourly rates and are converted once, before model
    construction.  Keeping that boundary explicit prevents a 480-quarter
    horizon from being mistaken for 480 physical hours.
    """

    horizon_hours: int
    execution_hours: int
    time_step_hours: float = 1.0

    def __post_init__(self) -> None:
        if self.horizon_hours <= 0 or self.execution_hours <= 0:
            raise S44CModelBuilderError("Time-grid horizons must be positive.")
        if self.execution_hours > self.horizon_hours:
            raise S44CModelBuilderError("Execution duration exceeds the planning horizon.")
        if self.time_step_hours not in {1.0, 0.25}:
            raise S44CModelBuilderError("Steel time steps are restricted to 1 hour or 15 minutes.")
        for label, hours in {
            "planning": self.horizon_hours,
            "execution": self.execution_hours,
        }.items():
            steps = hours / self.time_step_hours
            if abs(steps - round(steps)) > 1e-9:
                raise S44CModelBuilderError(
                    f"{label.capitalize()} duration is not divisible by the time step."
                )

    @property
    def horizon_steps(self) -> int:
        return int(round(self.horizon_hours / self.time_step_hours))

    @property
    def execution_steps(self) -> int:
        return int(round(self.execution_hours / self.time_step_hours))

    @property
    def steps_per_hour(self) -> int:
        return int(round(1.0 / self.time_step_hours))

    def hours_to_steps(self, hours: int) -> int:
        steps = float(hours) / self.time_step_hours
        if abs(steps - round(steps)) > 1e-9:
            raise S44CModelBuilderError("Hour deadline is not aligned to the model time step.")
        return int(round(steps))


@dataclass(frozen=True)
class EAFHeatStateParameters:
    """Source-labelled start-only EAF heat formulation on an internal QH grid.

    The 45-minute design basis is the three-quarter-hour rounding of
    ``325 t / 458 t LS h-1 = 42.6 minutes``.  It is not a measured Tata
    minimum tap-to-tap time.
    """

    active: bool = True
    heat_size_t_liquid_steel: float = 325.0
    total_qh_steps: int = 3
    melting_qh_steps: int = 2
    tapping_qh_steps: int = 1
    arc_electricity_mwh_per_t_liquid_steel: float = 0.4222222222
    secondary_electricity_mwh_per_t_liquid_steel: float = 0.031
    design_liquid_steel_rate_t_h: float = 458.0
    quantization_allowance_t: float = 162.5
    initial_start_lag1: int = 0
    initial_start_lag2: int = 0
    maintenance_intervals: tuple[int, ...] = ()
    require_idle_terminal_state: bool = False

    def __post_init__(self) -> None:
        if self.total_qh_steps != 3 or self.melting_qh_steps != 2 or self.tapping_qh_steps != 1:
            raise S44CModelBuilderError(
                "The Phase-6D EAF base requires exactly two melting quarters and one tap quarter."
            )
        if self.heat_size_t_liquid_steel <= 0.0:
            raise S44CModelBuilderError("EAF heat size must be positive.")
        if self.arc_electricity_mwh_per_t_liquid_steel <= 0.0:
            raise S44CModelBuilderError("EAF arc-energy intensity must be positive.")
        if self.secondary_electricity_mwh_per_t_liquid_steel < 0.0:
            raise S44CModelBuilderError("EAF secondary-energy intensity cannot be negative.")
        if self.quantization_allowance_t != 0.5 * self.heat_size_t_liquid_steel:
            raise S44CModelBuilderError(
                "EAF route-band quantization allowance must equal half a heat."
            )
        if self.initial_start_lag1 not in {0, 1} or self.initial_start_lag2 not in {0, 1}:
            raise S44CModelBuilderError("EAF rolling start lags must be binary.")
        if self.initial_start_lag1 + self.initial_start_lag2 > 1:
            raise S44CModelBuilderError("Overlapping EAF rolling start lags are impossible.")
        if any(int(interval) < 0 for interval in self.maintenance_intervals):
            raise S44CModelBuilderError("EAF maintenance intervals must be non-negative.")

    @property
    def derived_design_cycle_minutes(self) -> float:
        return 60.0 * self.heat_size_t_liquid_steel / self.design_liquid_steel_rate_t_h

    @property
    def arc_energy_mwh_per_heat(self) -> float:
        return (
            self.heat_size_t_liquid_steel
            * self.arc_electricity_mwh_per_t_liquid_steel
        )

    @property
    def arc_energy_mwh_per_melting_interval(self) -> float:
        return self.arc_energy_mwh_per_heat / self.melting_qh_steps

    @property
    def arc_on_power_mw(self) -> float:
        return self.arc_energy_mwh_per_melting_interval / 0.25

    @property
    def secondary_energy_mwh_per_heat(self) -> float:
        return (
            self.heat_size_t_liquid_steel
            * self.secondary_electricity_mwh_per_t_liquid_steel
        )


@dataclass(frozen=True)
class C1ExecutableInputs:
    horizon_hours: int
    final_product_target_t: float
    drp_capacity_t_pellets_h: float
    drp_min_pu: float
    drp_max_pu: float
    drp_ramp_pu_per_h: float
    drp_yield_t_dri_per_t_pellets: float
    drp_electricity_mwh_per_t_pellets: float
    drp_ng_nm3_per_t_pellets: float
    drp_o2_t_per_t_pellets: float
    eaf_capacity_t_dri_h: float
    eaf_min_pu: float
    eaf_max_pu: float
    eaf_yield_t_final_per_t_dri: float
    eaf_electricity_mwh_per_t_dri: float
    eaf_o2_t_per_t_dri: float
    eaf_scrap_t_per_t_dri: float
    dri_buffer_capacity_t: float
    dri_buffer_initial_t: float
    retained_bf_bof: RetainedBfBofInputs | None = None

    @property
    def drp_min_t_pellets_h(self) -> float:
        return self.drp_capacity_t_pellets_h * self.drp_min_pu

    @property
    def drp_max_t_pellets_h(self) -> float:
        return self.drp_capacity_t_pellets_h * self.drp_max_pu

    @property
    def drp_ramp_t_pellets_h(self) -> float:
        return self.drp_capacity_t_pellets_h * self.drp_ramp_pu_per_h

    @property
    def eaf_min_t_dri_h(self) -> float:
        return self.eaf_capacity_t_dri_h * self.eaf_min_pu

    @property
    def eaf_max_t_dri_h(self) -> float:
        return self.eaf_capacity_t_dri_h * self.eaf_max_pu


@dataclass(frozen=True)
class C0ExecutableInputs:
    horizon_hours: int
    final_product_target_t: float
    process_limits: dict[str, tuple[float, float]]
    sinter_output_per_t_iron_ore: float
    bf_hot_iron_per_t_sinter: float
    bof_crude_steel_per_t_hot_iron: float
    hsm_final_per_t_crude_steel: float
    coke_per_t_sinter: float
    coke_store_capacity_t: float
    coke_store_initial_t: float
    sinter_store_capacity_t: float
    sinter_store_initial_t: float
    hot_iron_store_capacity_t: float
    hot_iron_store_initial_t: float
    cold_slab_store_capacity_t: float
    cold_slab_store_initial_t: float
    bfg_nm3_per_t_hot_iron: float
    cog_m3_per_t_dry_coal: float
    bofg_nm3_per_t_liquid_steel: float
    bfg_mwh_per_t_hot_iron: float
    cog_mwh_per_t_coke: float
    bofg_mwh_per_t_liquid_steel: float
    kgf_underfiring_mwh_per_t_coke: float
    sinter_cog_mwh_per_t_sinter: float
    boiler_wag_cap_mwh_h: float
    boiler_total_placeholder_mwh_h: float
    eta_boiler_steam: float


@dataclass(frozen=True)
class RetainedBfBofInputs:
    process_limits: dict[str, tuple[float, float]]
    sinter_output_per_t_iron_ore: float
    bf_hot_iron_per_t_sinter: float
    bof_crude_steel_per_t_hot_iron: float
    hsm_final_per_t_crude_steel: float
    coke_per_t_sinter: float
    coke_store_capacity_t: float
    coke_store_initial_t: float
    sinter_store_capacity_t: float
    sinter_store_initial_t: float
    hot_iron_store_capacity_t: float
    hot_iron_store_initial_t: float
    cold_slab_store_capacity_t: float
    cold_slab_store_initial_t: float
    bfg_nm3_per_t_hot_iron: float
    cog_m3_per_t_dry_coal: float
    bofg_nm3_per_t_liquid_steel: float
    bfg_mwh_per_t_hot_iron: float
    cog_mwh_per_t_coke: float
    bofg_mwh_per_t_liquid_steel: float
    kgf_underfiring_mwh_per_t_coke: float
    sinter_cog_mwh_per_t_sinter: float
    boiler_wag_cap_mwh_h: float
    boiler_total_placeholder_mwh_h: float
    eta_boiler_steam: float
    retained_target_share: float


def scale_c0_inputs_to_time_grid(
    inputs: C0ExecutableInputs,
    grid: ModelTimeGrid,
) -> C0ExecutableInputs:
    """Convert C0 hourly rate bounds to quantities per model interval."""

    dt = grid.time_step_hours
    return replace(
        inputs,
        horizon_hours=grid.horizon_steps,
        process_limits={
            name: (float(lower) * dt, float(upper) * dt)
            for name, (lower, upper) in inputs.process_limits.items()
        },
        boiler_wag_cap_mwh_h=float(inputs.boiler_wag_cap_mwh_h) * dt,
        boiler_total_placeholder_mwh_h=float(inputs.boiler_total_placeholder_mwh_h) * dt,
    )


def scale_c1_inputs_to_time_grid(
    inputs: C1ExecutableInputs,
    grid: ModelTimeGrid,
) -> C1ExecutableInputs:
    """Convert C1 and retained-route hourly rates to interval quantities."""

    dt = grid.time_step_hours
    retained = inputs.retained_bf_bof
    scaled_retained = (
        None
        if retained is None
        else replace(
            retained,
            process_limits={
                name: (float(lower) * dt, float(upper) * dt)
                for name, (lower, upper) in retained.process_limits.items()
            },
            boiler_wag_cap_mwh_h=float(retained.boiler_wag_cap_mwh_h) * dt,
            boiler_total_placeholder_mwh_h=float(retained.boiler_total_placeholder_mwh_h) * dt,
        )
    )
    return replace(
        inputs,
        horizon_hours=grid.horizon_steps,
        drp_capacity_t_pellets_h=float(inputs.drp_capacity_t_pellets_h) * dt,
        # The property is applied to an interval quantity, so multiplying the
        # per-hour ramp fraction by dt yields the required R * dt^2 bound.
        drp_ramp_pu_per_h=float(inputs.drp_ramp_pu_per_h) * dt,
        eaf_capacity_t_dri_h=float(inputs.eaf_capacity_t_dri_h) * dt,
        retained_bf_bof=scaled_retained,
    )


def _apply_wag_generation_yield_overrides(
    inputs: C0ExecutableInputs | RetainedBfBofInputs,
    overrides: Mapping[str, float] | None,
) -> C0ExecutableInputs | RetainedBfBofInputs:
    """Apply an explicit carrier-yield overlay without merging WAG carriers."""

    if not overrides:
        return inputs
    allowed = {"BFG", "COG", "BOFG"}
    unknown = set(overrides).difference(allowed)
    if unknown:
        raise S44CModelBuilderError(
            f"Unsupported WAG generation-yield override carrier(s): {sorted(unknown)}"
        )
    values = {carrier: float(value) for carrier, value in overrides.items()}
    if any(value <= 0.0 for value in values.values()):
        raise S44CModelBuilderError("Every WAG generation-yield override must be positive.")
    replacements: dict[str, float] = {}
    field_names = {
        "BFG": ("bfg_nm3_per_t_hot_iron", "bfg_mwh_per_t_hot_iron"),
        "COG": ("cog_m3_per_t_dry_coal", "cog_mwh_per_t_coke"),
        "BOFG": ("bofg_nm3_per_t_liquid_steel", "bofg_mwh_per_t_liquid_steel"),
    }
    for carrier, override in values.items():
        volume_field, energy_field = field_names[carrier]
        replacements[volume_field] = override
        replacements[energy_field] = _gas_mwh_per_activity(override, carrier)
    return replace(inputs, **replacements)


def _apply_c0_initial_inventory_overrides(
    inputs: C0ExecutableInputs,
    overrides: Mapping[str, float] | None,
) -> C0ExecutableInputs:
    """Apply a validated rolling-horizon inventory handoff to C0 inputs."""
    if not overrides:
        return inputs
    allowed = {
        "coke_store_initial_t": inputs.coke_store_capacity_t,
        "sinter_store_initial_t": inputs.sinter_store_capacity_t,
        "hot_iron_store_initial_t": inputs.hot_iron_store_capacity_t,
        "cold_slab_store_initial_t": inputs.cold_slab_store_capacity_t,
    }
    unknown = sorted(set(overrides).difference(allowed))
    if unknown:
        raise S44CModelBuilderError(f"Unsupported C0 rolling inventory override(s): {unknown}")
    resolved = {key: float(value) for key, value in overrides.items()}
    if any(value < -TOLERANCE or value > allowed[key] + TOLERANCE for key, value in resolved.items()):
        raise S44CModelBuilderError("C0 rolling inventory override is negative or exceeds its store capacity.")
    return replace(inputs, **resolved)


def _apply_c1_initial_inventory_overrides(
    inputs: C1ExecutableInputs,
    overrides: Mapping[str, float] | None,
) -> C1ExecutableInputs:
    """Apply a validated rolling-horizon inventory handoff to C1 inputs."""
    if not overrides:
        return inputs
    retained = inputs.retained_bf_bof
    allowed: dict[str, float] = {"dri_buffer_initial_t": inputs.dri_buffer_capacity_t}
    if retained is not None:
        allowed.update(
            {
                "coke_store_initial_t": retained.coke_store_capacity_t,
                "sinter_store_initial_t": retained.sinter_store_capacity_t,
                "hot_iron_store_initial_t": retained.hot_iron_store_capacity_t,
                "cold_slab_store_initial_t": retained.cold_slab_store_capacity_t,
            }
        )
    unknown = sorted(set(overrides).difference(allowed))
    if unknown:
        raise S44CModelBuilderError(f"Unsupported C1 rolling inventory override(s): {unknown}")
    resolved = {key: float(value) for key, value in overrides.items()}
    if any(value < -TOLERANCE or value > allowed[key] + TOLERANCE for key, value in resolved.items()):
        raise S44CModelBuilderError("C1 rolling inventory override is negative or exceeds its store capacity.")
    dri_initial = resolved.pop("dri_buffer_initial_t", inputs.dri_buffer_initial_t)
    if retained is not None:
        retained_updates = {key: value for key, value in resolved.items() if key in {
            "coke_store_initial_t", "sinter_store_initial_t", "hot_iron_store_initial_t", "cold_slab_store_initial_t"
        }}
        retained = replace(retained, **retained_updates)
    return replace(inputs, dri_buffer_initial_t=dri_initial, retained_bf_bof=retained)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        if rows:
            fieldnames = []
            for row in rows:
                for key in row:
                    if key not in fieldnames:
                        fieldnames.append(key)
        else:
            fieldnames = ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        if rows:
            writer.writerows(rows)


_UNIFIED_TABLE_NAMES = (
        "configuration_assets.csv",
        "process_units.csv",
        "process_io_coefficients.csv",
        "process_energy_intensities.csv",
        "process_emission_factors.csv",
        "buffers_and_stores.csv",
        "wag_generation_coefficients.csv",
        "wag_sink_eligibility.csv",
        "utility_demands.csv",
        "utility_conversion_assets.csv",
        "external_supply_costs.csv",
        "market_price_inputs.csv",
        "production_targets.csv",
        "validation_anchors.csv",
        "policy_modes.csv",
        "solver_and_horizon_config.csv",
    )


def _steel_input_fingerprint(input_dir: Path) -> str:
    resolved = Path(input_dir).resolve()
    stat_signature = tuple(
        (
            name,
            int((resolved / name).stat().st_size),
            int((resolved / name).stat().st_mtime_ns),
        )
        for name in _UNIFIED_TABLE_NAMES
    )
    cache_key = str(resolved)
    cached = _STEEL_INPUT_FINGERPRINT_CACHE.get(cache_key)
    if cached is not None and cached[0] == stat_signature:
        return cached[1]
    fingerprint = fingerprint_paths([resolved / name for name in _UNIFIED_TABLE_NAMES])
    _STEEL_INPUT_FINGERPRINT_CACHE[cache_key] = (stat_signature, fingerprint)
    return fingerprint


def _load_tables_with_status(
    input_dir: Path = S44B_INPUT_DIR,
    *,
    performance_mode: str = "optimized_equivalent",
) -> tuple[UnifiedInputTables, str, str]:
    mode = validate_performance_mode(performance_mode)
    resolved = Path(input_dir).resolve()
    source_hash = _steel_input_fingerprint(resolved)
    if mode == "optimized_equivalent" and source_hash in _STEEL_TABLE_CACHE:
        return _STEEL_TABLE_CACHE[source_hash], "hit", source_hash
    tables = UnifiedInputTables(
        input_dir=input_dir,
        tables={table_name: _read_csv(resolved / table_name) for table_name in _UNIFIED_TABLE_NAMES},
    )
    if mode == "optimized_equivalent":
        _STEEL_TABLE_CACHE[source_hash] = tables
    return tables, ("miss_registered" if mode == "optimized_equivalent" else "disabled_legacy_rebuild"), source_hash


def _load_tables(
    input_dir: Path = S44B_INPUT_DIR,
    *,
    performance_mode: str = "optimized_equivalent",
) -> UnifiedInputTables:
    tables, _, _ = _load_tables_with_status(input_dir, performance_mode=performance_mode)
    return tables


def _is_executable(row: dict[str, str]) -> bool:
    return row.get("input_status", "") in EXECUTABLE_STATUSES


def _is_active(row: dict[str, str]) -> bool:
    return row.get("active", "").strip().lower() == "true"


def _as_float(value_in: str, *, field_name: str) -> float:
    try:
        return float(value_in)
    except (TypeError, ValueError) as exc:
        raise S44CModelBuilderError(f"Expected numeric {field_name}, got {value_in!r}.") from exc


def _gas_mwh_per_activity(coefficient: float, carrier: str) -> float:
    lhv_mj_per_nm3, _ = load_governed_wag_factor_maps()
    return coefficient * lhv_mj_per_nm3[carrier] / MJ_PER_MWH


def _parse_pu_capacity(rate_unit: str) -> float:
    match = re.match(r"pu_of_([0-9.]+)_t_[A-Za-z0-9_]+_per_h$", rate_unit)
    if not match:
        raise S44CModelBuilderError(f"Cannot parse per-unit capacity from rate_unit={rate_unit!r}.")
    return float(match.group(1))


def _parse_fixed_initial(rule: str, *, field_name: str) -> float:
    if rule == "zero_for_smoke":
        return 0.0
    prefix = "fixed_initial_"
    if not rule.startswith(prefix):
        raise S44CModelBuilderError(f"Cannot parse {field_name} from initial_rule={rule!r}.")
    return _as_float(rule[len(prefix):], field_name=field_name)


def _first_row(rows: list[dict[str, str]], **criteria: str) -> dict[str, str]:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    raise S44CModelBuilderError(f"Missing row matching {criteria}.")


def _optional_float(rows: list[dict[str, str]], default: float, **criteria: str) -> float:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()) and _is_executable(row):
            return _as_float(row["intensity" if "intensity" in row else "coefficient"], field_name=str(criteria))
    return default


def _numeric_coefficient(
    rows: list[dict[str, str]],
    *,
    process_id: str,
    input_material: str,
    output_material: str,
    expected_unit: str | None = None,
) -> float:
    row = _first_row(
        rows,
        process_id=process_id,
        input_material=input_material,
        output_material=output_material,
    )
    if not _is_executable(row):
        raise S44CModelBuilderError(f"Coefficient row for {process_id} is not executable.")
    if expected_unit is not None and row.get("coefficient_unit") != expected_unit:
        raise S44CModelBuilderError(
            f"{process_id} coefficient must use {expected_unit}, got {row.get('coefficient_unit')!r}."
        )
    coefficient = _as_float(row["coefficient"], field_name=f"{process_id} coefficient")
    if coefficient <= 0.0:
        raise S44CModelBuilderError(f"{process_id} coefficient must be positive.")
    return coefficient


def _require_process_rate_unit(
    process_units: list[dict[str, str]],
    configuration_id: str,
    asset_id: str,
    expected_unit: str,
) -> None:
    row = _first_row(process_units, configuration_id=configuration_id, asset_id=asset_id)
    if row.get("rate_unit") != expected_unit:
        raise S44CModelBuilderError(
            f"{configuration_id} {asset_id} must use {expected_unit}, got {row.get('rate_unit')!r}."
        )


def _c0_process_limit(process_units: list[dict[str, str]], asset_id: str) -> tuple[float, float]:
    return _configuration_process_limit(process_units, "C0_current_BF_BOF_reference", asset_id)


def _configuration_process_limit(
    process_units: list[dict[str, str]],
    configuration_id: str,
    asset_id: str,
) -> tuple[float, float]:
    row = _first_row(process_units, configuration_id=configuration_id, asset_id=asset_id)
    if not _is_executable(row):
        raise S44CModelBuilderError(f"{configuration_id} process unit {asset_id} is not executable.")
    return (
        _as_float(row["min_rate"], field_name=f"{asset_id} min_rate"),
        _as_float(row["max_rate"], field_name=f"{asset_id} max_rate"),
    )


def _c0_store(buffer_rows: list[dict[str, str]], buffer_id: str) -> tuple[float, float]:
    return _configuration_store(buffer_rows, "C0_current_BF_BOF_reference", buffer_id)


def _configuration_store(
    buffer_rows: list[dict[str, str]],
    configuration_id: str,
    buffer_id: str,
) -> tuple[float, float]:
    row = _first_row(buffer_rows, configuration_id=configuration_id, buffer_id=buffer_id)
    if not _is_executable(row):
        raise S44CModelBuilderError(f"{configuration_id} store {buffer_id} is not executable.")
    return (
        _as_float(row["capacity"], field_name=f"{buffer_id} capacity"),
        _as_float(row.get("initial_inventory_value") or str(_parse_fixed_initial(row["initial_rule"], field_name=buffer_id)), field_name=f"{buffer_id} initial"),
    )


def _select_solver():
    for solver_name in SOLVER_PREFERENCE:
        try:
            solver = SolverFactory(solver_name)
        except Exception:
            continue
        if solver is not None and solver.available(exception_flag=False):
            return solver_name, solver
    return None, None


def _apply_solver_time_limit(solver_name: str, solver: Any, seconds: float | None) -> None:
    """Apply a hard solver limit without changing the physical formulation."""

    if seconds is None:
        return
    if seconds <= 0:
        raise S44CModelBuilderError("solver_time_limit_seconds must be positive when provided.")
    if solver_name in {"gurobi", "gurobi_direct"}:
        solver.options["TimeLimit"] = float(seconds)
    elif solver_name == "appsi_highs":
        solver.config.time_limit = float(seconds)
        # The LegacySolver wrapper forwards this dictionary to HiGHS.  Setting
        # both surfaces protects the run contract across installed Pyomo builds.
        solver.options["time_limit"] = float(seconds)
    elif solver_name == "highs":
        solver.options["time_limit"] = float(seconds)
    elif solver_name == "cbc":
        solver.options["seconds"] = float(seconds)
    elif solver_name == "glpk":
        solver.options["tmlim"] = max(1, int(seconds))
    else:
        raise S44CModelBuilderError(f"No time-limit adapter is defined for solver {solver_name}.")


def _audit_loaded_incumbent(
    model: ConcreteModel,
    *,
    tolerance: float = 1e-6,
    structurally_inactive_exclusions: Collection[str] = (),
) -> dict[str, Any]:
    """Audit the loaded incumbent without hiding floating-point boundary cases.

    This is an exact diagnostic over the values exposed by Pyomo: it does not
    round residuals or add a secondary numerical margin to ``tolerance``.  A
    fixed-incumbent solver oracle remains the authority where the raw Python
    evaluation and the solver's row arithmetic differ at the feasibility
    boundary.
    """

    max_constraint_violation = 0.0
    max_bound_violation = 0.0
    max_integrality_violation = 0.0
    constraint_count = 0
    variable_count = 0
    discrete_count = 0
    undefined_value_count = 0
    undefined_names: list[str] = []
    bound_violations: list[dict[str, Any]] = []
    integrality_violations: list[dict[str, Any]] = []
    constraint_violations: list[dict[str, Any]] = []
    excluded_names = set(structurally_inactive_exclusions)
    for variable in model.component_data_objects(Var, active=True):
        if variable.name in excluded_names:
            continue
        variable_count += 1
        current = variable.value
        if current is None:
            undefined_value_count += 1
            undefined_names.append(variable.name)
            continue
        current = float(current)
        lower = None if variable.lb is None else float(value(variable.lb))
        upper = None if variable.ub is None else float(value(variable.ub))
        lower_violation = (
            0.0 if lower is None else max(0.0, lower - current)
        )
        upper_violation = (
            0.0 if upper is None else max(0.0, current - upper)
        )
        bound_violation = max(lower_violation, upper_violation)
        if bound_violation > 0.0:
            bound_violations.append(
                {
                    "name": variable.name,
                    "value": current,
                    "lower": lower,
                    "upper": upper,
                    "lower_violation": lower_violation,
                    "upper_violation": upper_violation,
                    "absolute_violation": bound_violation,
                }
            )
        if variable.lb is not None:
            max_bound_violation = max(
                max_bound_violation, float(value(variable.lb)) - current
            )
        if variable.ub is not None:
            max_bound_violation = max(
                max_bound_violation, current - float(value(variable.ub))
            )
        if variable.is_binary() or variable.is_integer():
            discrete_count += 1
            integrality_violation = abs(current - round(current))
            if integrality_violation > 0.0:
                integrality_violations.append(
                    {
                        "name": variable.name,
                        "value": current,
                        "nearest_integer": round(current),
                        "absolute_violation": integrality_violation,
                    }
                )
            max_integrality_violation = max(
                max_integrality_violation, integrality_violation
            )
    for constraint in model.component_data_objects(Constraint, active=True):
        constraint_count += 1
        try:
            body = float(value(constraint.body))
        except (TypeError, ValueError):
            undefined_value_count += 1
            undefined_names.append(constraint.name)
            continue
        lower = (
            None
            if constraint.lower is None
            else float(value(constraint.lower))
        )
        upper = (
            None
            if constraint.upper is None
            else float(value(constraint.upper))
        )
        lower_violation = (
            0.0 if lower is None else max(0.0, lower - body)
        )
        upper_violation = (
            0.0 if upper is None else max(0.0, body - upper)
        )
        constraint_violation = max(lower_violation, upper_violation)
        if constraint_violation > 0.0:
            constraint_violations.append(
                {
                    "name": constraint.name,
                    "component_name": constraint.parent_component().name,
                    "index": str(constraint.index()),
                    "violated_side": (
                        "lower"
                        if lower_violation >= upper_violation
                        else "upper"
                    ),
                    "body": body,
                    "lower": lower,
                    "upper": upper,
                    "lower_violation": lower_violation,
                    "upper_violation": upper_violation,
                    "absolute_violation": constraint_violation,
                    "expression": str(constraint.expr),
                }
            )
        max_constraint_violation = max(
            max_constraint_violation, constraint_violation
        )
    max_constraint_violation = max(0.0, max_constraint_violation)
    max_bound_violation = max(0.0, max_bound_violation)
    def _violation_order(row: Mapping[str, Any]) -> tuple[float, str, str]:
        return (
            -float(row["absolute_violation"]),
            str(row["name"]),
            str(row.get("violated_side", "")),
        )

    constraint_violations.sort(key=_violation_order)
    bound_violations.sort(key=_violation_order)
    integrality_violations.sort(key=_violation_order)
    constraint_above_tolerance = [
        row
        for row in constraint_violations
        if float(row["absolute_violation"]) > tolerance
    ]
    exact_maximum_constraint_records = [
        row
        for row in constraint_violations
        if float(row["absolute_violation"]) == max_constraint_violation
    ]
    constraint_diagnostic_sha256 = hashlib.sha256(
        json.dumps(
            constraint_violations,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    result = {
        "constraint_count": constraint_count,
        "variable_count": variable_count,
        "discrete_variable_count": discrete_count,
        "undefined_value_count": undefined_value_count,
        "structurally_inactive_exclusion_count": len(excluded_names),
        "max_constraint_violation": max_constraint_violation,
        "max_variable_bound_violation": max_bound_violation,
        "max_integrality_violation": max_integrality_violation,
        "tolerance": tolerance,
        "evaluation_contract": {
            "schema_version": "steel_loaded_incumbent_exact_diagnostics_v1",
            "arithmetic": "Python float over Pyomo value(constraint.body/bounds)",
            "comparison": "raw_absolute_violation_lte_tolerance",
            "rounding_or_secondary_margin": False,
            "constraint_iteration": "active Pyomo ConstraintData declaration order",
            "diagnostic_order": "absolute_violation_desc_name_asc_side_asc",
        },
        "undefined_names": sorted(undefined_names),
        "positive_constraint_violation_count": len(constraint_violations),
        "constraint_above_tolerance_count": len(
            constraint_above_tolerance
        ),
        "constraint_violation_diagnostic_sha256": (
            constraint_diagnostic_sha256
        ),
        "exact_maximum_constraint_violations": (
            exact_maximum_constraint_records
        ),
        "constraints_above_tolerance": constraint_above_tolerance,
        "top_constraint_violations": constraint_violations[:20],
        "top_variable_bound_violations": bound_violations[:20],
        "top_integrality_violations": integrality_violations[:20],
        "feasible": (
            undefined_value_count == 0
            and max_constraint_violation <= tolerance
            and max_bound_violation <= tolerance
            and max_integrality_violation <= tolerance
        ),
    }
    return result


def _constraint_raw_validation_row(constraint: Any) -> dict[str, Any]:
    """Evaluate one active row at the loaded full-precision incumbent."""

    body = float(value(constraint.body))
    lower = (
        None
        if constraint.lower is None
        else float(value(constraint.lower))
    )
    upper = (
        None
        if constraint.upper is None
        else float(value(constraint.upper))
    )
    lower_residual = 0.0 if lower is None else max(0.0, lower - body)
    upper_residual = 0.0 if upper is None else max(0.0, body - upper)
    return {
        "constraint_name": constraint.name,
        "constraint_family": constraint.parent_component().name,
        "constraint_index": str(constraint.index()),
        "body": body,
        "lower": lower,
        "upper": upper,
        "lower_raw_residual": lower_residual,
        "upper_raw_residual": upper_residual,
        "raw_residual": max(lower_residual, upper_residual),
        "expression": str(constraint.expr),
    }


def _constraint_validation_definition(constraint: Any) -> dict[str, Any]:
    """Record a row definition without requiring initialized variables."""

    return {
        "constraint_name": constraint.name,
        "constraint_family": constraint.parent_component().name,
        "constraint_index": str(constraint.index()),
        "lower": None
        if constraint.lower is None
        else float(value(constraint.lower)),
        "upper": None
        if constraint.upper is None
        else float(value(constraint.upper)),
        "expression": str(constraint.expr),
    }


def _install_registered_validation_relaxations(
    validation_model: ConcreteModel,
) -> dict[str, Any]:
    """Replace only registered acceptance rows by explicitly bounded slacks."""

    constraints = list(
        validation_model.component_data_objects(Constraint, active=True)
    )
    row_contexts: list[dict[str, Any]] = []
    relaxation_sides: list[dict[str, Any]] = []
    families: list[str] = []
    for constraint in constraints:
        raw = _constraint_raw_validation_row(constraint)
        family = str(raw["constraint_family"])
        try:
            rule = constraint_family_rule(family)
        except ValidationTolerancePolicyError as exc:
            error = S44CModelBuilderError(str(exc))
            error.phase2_stage = "sale_containment.validation_policy_registration"
            raise error from exc
        families.append(family)
        evidence = {
            **raw,
            **validation_record(
                validation_id=str(raw["constraint_name"]),
                purpose=rule.purpose,
                unit=rule.unit,
                raw_residual=float(raw["raw_residual"]),
                allowed_tolerance=rule.tolerance,
                aggregation=rule.aggregation,
            ),
            "relaxation_allowed": rule.relaxation_allowed,
            "relaxation_side_indices": [],
        }
        context = {
            "constraint": constraint,
            "rule": rule,
            "evidence": evidence,
        }
        row_contexts.append(context)
        if not rule.relaxation_allowed:
            continue
        constraint.deactivate()
        for side in ("lower", "upper"):
            bound = raw[side]
            if bound is None:
                continue
            index = len(relaxation_sides)
            required = float(raw[f"{side}_raw_residual"])
            relaxation_sides.append(
                {
                    "row_context_index": len(row_contexts) - 1,
                    "side": side,
                    "allowed_tolerance": rule.tolerance,
                    "required_relaxation": required,
                    "body_expression": constraint.body,
                    "bound": float(bound),
                }
            )
            evidence["relaxation_side_indices"].append(index)

    validation_model.SALE_VALIDATION_RELAXATION_SIDE = Set(
        initialize=range(len(relaxation_sides)), ordered=True
    )
    allowed_by_index = {
        index: float(side["allowed_tolerance"])
        for index, side in enumerate(relaxation_sides)
    }
    initial_by_index = {
        index: min(
            float(side["required_relaxation"]),
            float(side["allowed_tolerance"]),
        )
        for index, side in enumerate(relaxation_sides)
    }
    validation_model.sale_validation_relaxation = Var(
        validation_model.SALE_VALIDATION_RELAXATION_SIDE,
        domain=NonNegativeReals,
        bounds=lambda _m, index: (0.0, allowed_by_index[int(index)]),
        initialize=lambda _m, index: initial_by_index[int(index)],
    )
    validation_model.sale_validation_relaxed_rows = ConstraintList()
    for index, side in enumerate(relaxation_sides):
        slack = validation_model.sale_validation_relaxation[index]
        if side["side"] == "lower":
            validation_model.sale_validation_relaxed_rows.add(
                side["body_expression"] + slack >= side["bound"]
            )
        else:
            validation_model.sale_validation_relaxed_rows.add(
                side["body_expression"] - slack <= side["bound"]
            )

    return {
        "row_contexts": row_contexts,
        "relaxation_sides": relaxation_sides,
        "constraint_family_registry_sha256": (
            constraint_registry_fingerprint(families)
        ),
        "active_constraint_family_count": len(set(families)),
        "active_validation_row_count": len(row_contexts),
        "relaxation_side_count": len(relaxation_sides),
    }


def _finalize_registered_validation_evidence(
    validation_model: ConcreteModel,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    side_rows: list[dict[str, Any]] = []
    for index, side_context in enumerate(context["relaxation_sides"]):
        row_context = context["row_contexts"][
            int(side_context["row_context_index"])
        ]
        row_evidence = row_context["evidence"]
        required = float(side_context["required_relaxation"])
        allowed = float(side_context["allowed_tolerance"])
        raw_used = value(
            validation_model.sale_validation_relaxation[index],
            exception=False,
        )
        used = None if raw_used is None else float(raw_used)
        finite_used = used is not None and math.isfinite(used)
        normalized_raw = required / allowed if allowed > 0.0 else (
            0.0 if required == 0.0 else None
        )
        normalized_used = (
            used / allowed
            if finite_used and allowed > 0.0
            else 0.0
            if finite_used and used == 0.0
            else None
        )
        required_within_allowed = required <= allowed
        used_within_allowed = bool(finite_used and used <= allowed)
        used_covers_required = bool(
            finite_used
            and used + SOLVER_NUMERICAL_TOLERANCE >= required
        )
        side_rows.append(
            {
                "relaxation_side_index": index,
                "side": str(side_context["side"]),
                "constraint_name": str(row_evidence["constraint_name"]),
                "constraint_family": str(row_evidence["constraint_family"]),
                "constraint_index": str(row_evidence["constraint_index"]),
                "raw_required_relaxation": required,
                "allowed_tolerance": allowed,
                "solved_used_relaxation": used,
                "normalized_raw_residual": normalized_raw,
                "normalized_used_residual": normalized_used,
                "required_within_allowed_tolerance": required_within_allowed,
                "used_within_allowed_tolerance": used_within_allowed,
                "solved_used_slack_covers_required": used_covers_required,
                "coverage_numerical_tolerance": (
                    SOLVER_NUMERICAL_TOLERANCE
                ),
                "status": (
                    "pass"
                    if required_within_allowed
                    and used_within_allowed
                    and used_covers_required
                    else "fail"
                ),
            }
        )
    side_rows.sort(
        key=lambda row: (
            str(row["constraint_name"]),
            0 if row["side"] == "lower" else 1,
            int(row["relaxation_side_index"]),
        )
    )
    side_by_index = {
        int(row["relaxation_side_index"]): row for row in side_rows
    }
    rows: list[dict[str, Any]] = []
    for row_context in context["row_contexts"]:
        evidence = dict(row_context["evidence"])
        row_side_evidence = [
            side_by_index[int(index)]
            for index in evidence["relaxation_side_indices"]
        ]
        used_values = [
            row["solved_used_relaxation"] for row in row_side_evidence
        ]
        all_used_finite = all(value is not None for value in used_values)
        used = (
            max((float(item) for item in used_values), default=0.0)
            if all_used_finite
            else None
        )
        evidence["used_relaxation"] = used
        evidence["relaxation_side_status"] = (
            "pass"
            if all(row["status"] == "pass" for row in row_side_evidence)
            else "fail"
        )
        evidence["status"] = (
            "pass"
            if float(evidence["raw_residual"])
            <= float(evidence["allowed_tolerance"])
            and evidence["relaxation_side_status"] == "pass"
            and used is not None
            and used <= float(evidence["allowed_tolerance"])
            else "fail"
        )
        rows.append(evidence)
    rows.sort(key=lambda row: str(row["constraint_name"]))
    failures = [row for row in rows if row["status"] != "pass"]
    side_failures = [row for row in side_rows if row["status"] != "pass"]
    rows_sha256 = canonical_json_sha256(rows)
    side_rows_sha256 = canonical_json_sha256(side_rows)
    return {
        "schema_version": "steel_registered_validation_rows_v2",
        "policy": validation_tolerance_policy_contract(),
        "constraint_family_registry_sha256": context[
            "constraint_family_registry_sha256"
        ],
        "active_constraint_family_count": context[
            "active_constraint_family_count"
        ],
        "active_validation_row_count": len(rows),
        "relaxation_side_count": context["relaxation_side_count"],
        "failed_validation_row_count": len(failures),
        "failed_relaxation_side_count": len(side_failures),
        "max_normalized_residual": max(
            (float(row["normalized_residual"]) for row in rows), default=0.0
        ),
        "max_normalized_used_relaxation": max(
            (
                float(row["normalized_used_residual"])
                for row in side_rows
                if row["normalized_used_residual"] is not None
            ),
            default=0.0,
        ),
        "rows_sha256": rows_sha256,
        "relaxation_sides_sha256": side_rows_sha256,
        "evidence_manifest_sha256": canonical_json_sha256(
            {
                "rows_sha256": rows_sha256,
                "relaxation_sides_sha256": side_rows_sha256,
            }
        ),
        "rows": rows,
        "relaxation_sides": side_rows,
        "status": (
            "pass" if not failures and not side_failures else "fail"
        ),
    }


def _sale_economic_core_fingerprint(model: ConcreteModel) -> str:
    """Fingerprint the core while ignoring activation-only overlay routing."""

    payload = {
        "variables": sorted(
            (
                {
                    "name": variable.name,
                    "domain": str(variable.domain),
                    "lower": str(variable.lb),
                    "upper": str(variable.ub),
                    "fixed": bool(variable.fixed),
                }
                for variable in model.component_data_objects(Var, active=None)
            ),
            key=lambda row: row["name"],
        ),
        "constraints": sorted(
            (
                {
                    "name": constraint.name,
                    "body": str(constraint.body),
                    "lower": None
                    if constraint.lower is None
                    else str(constraint.lower),
                    "upper": None
                    if constraint.upper is None
                    else str(constraint.upper),
                }
                for constraint in model.component_data_objects(
                    Constraint, active=None
                )
                if constraint.parent_component().name
                != "sale_economic_validation_overlay_rows"
            ),
            key=lambda row: row["name"],
        ),
        "objectives": sorted(
            (
                {
                    "name": objective.name,
                    "expression": str(objective.expr),
                    "sense": str(objective.sense),
                }
                for objective in model.component_data_objects(
                    Objective, active=None
                )
            ),
            key=lambda row: row["name"],
        ),
    }
    return canonical_json_sha256(payload)


def _install_sale_economic_validation_overlay(
    model: ConcreteModel,
) -> dict[str, Any]:
    """Expand only registered acceptance rows without decision slacks."""

    constraints = list(model.component_data_objects(Constraint, active=True))
    resolved: list[tuple[Any, Any, dict[str, Any]]] = []
    families: list[str] = []
    for constraint in constraints:
        raw = _constraint_validation_definition(constraint)
        family = str(raw["constraint_family"])
        try:
            rule = constraint_family_rule(family)
        except ValidationTolerancePolicyError as exc:
            error = S44CModelBuilderError(str(exc))
            error.phase2_stage = "sale_economic.validation_policy_registration"
            raise error from exc
        resolved.append((constraint, rule, raw))
        families.append(family)

    core_before = _sale_economic_core_fingerprint(model)
    model.sale_economic_validation_overlay_rows = ConstraintList()
    row_contexts: list[dict[str, Any]] = []
    for constraint, rule, raw in resolved:
        if not rule.relaxation_allowed:
            continue
        original_lower = raw["lower"]
        original_upper = raw["upper"]
        overlay_lower = (
            None
            if original_lower is None
            else float(original_lower) - float(rule.tolerance)
        )
        overlay_upper = (
            None
            if original_upper is None
            else float(original_upper) + float(rule.tolerance)
        )
        constraint.deactivate()
        overlay = model.sale_economic_validation_overlay_rows.add(
            (overlay_lower, constraint.body, overlay_upper)
        )
        row_contexts.append(
            {
                "constraint": constraint,
                "overlay_constraint": overlay,
                "rule": rule,
                "pre_solve_raw": raw,
                "overlay_lower": overlay_lower,
                "overlay_upper": overlay_upper,
            }
        )
    core_after = _sale_economic_core_fingerprint(model)
    if core_after != core_before:
        raise S44CModelBuilderError(
            "Sale economic validation overlay changed the underlying core."
        )
    return {
        "schema_version": "steel_sale_economic_validation_overlay_v2",
        "row_contexts": row_contexts,
        "constraint_family_registry_sha256": constraint_registry_fingerprint(
            families
        ),
        "active_constraint_family_count": len(set(families)),
        "registered_acceptance_row_count": len(row_contexts),
        "underlying_core_sha256_before": core_before,
        "underlying_core_sha256_after": core_after,
    }


def _finalize_sale_economic_validation_overlay(
    model: ConcreteModel,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in context["row_contexts"]:
        rule = item["rule"]
        overlay = item["overlay_constraint"]
        definition = _constraint_validation_definition(item["constraint"])
        try:
            raw = _constraint_raw_validation_row(item["constraint"])
            overlay_raw = _constraint_raw_validation_row(overlay)
            record = validation_record(
                validation_id=str(raw["constraint_name"]),
                purpose=rule.purpose,
                unit=rule.unit,
                raw_residual=float(raw["raw_residual"]),
                allowed_tolerance=float(rule.tolerance),
                aggregation=rule.aggregation,
            )
            governed_tolerance = float(rule.tolerance)
            raw_residual = float(raw["raw_residual"])
            overlay_residual = float(overlay_raw["raw_residual"])
            excess_beyond_governed_tolerance = max(
                0.0, raw_residual - governed_tolerance
            )
            solver_numerical_allowance = SOLVER_NUMERICAL_TOLERANCE
            finite = bool(
                math.isfinite(raw_residual)
                and math.isfinite(governed_tolerance)
                and math.isfinite(excess_beyond_governed_tolerance)
                and math.isfinite(overlay_residual)
            )
        except (TypeError, ValueError, ValidationTolerancePolicyError):
            raw = {
                **definition,
                "body": None,
                "lower_raw_residual": None,
                "upper_raw_residual": None,
                "raw_residual": None,
            }
            overlay_raw = {"raw_residual": None}
            governed_tolerance = float(rule.tolerance)
            excess_beyond_governed_tolerance = None
            solver_numerical_allowance = SOLVER_NUMERICAL_TOLERANCE
            overlay_residual = None
            record = {
                "validation_id": str(definition["constraint_name"]),
                "purpose": rule.purpose,
                "unit": rule.unit,
                "aggregation": rule.aggregation,
                "raw_residual": None,
                "allowed_tolerance": float(rule.tolerance),
                "normalized_residual": None,
                "status": "fail",
            }
            finite = False
        rows.append(
            {
                **raw,
                **record,
                "relaxation_allowed": True,
                "original_expression": raw["expression"],
                "original_lower": raw["lower"],
                "original_upper": raw["upper"],
                "overlay_constraint_name": overlay.name,
                "overlay_expression": str(overlay.expr),
                "overlay_lower": item["overlay_lower"],
                "overlay_upper": item["overlay_upper"],
                "overlay_raw_residual": overlay_raw["raw_residual"],
                "overlay_residual": overlay_residual,
                "governed_tolerance": governed_tolerance,
                "excess_beyond_governed_tolerance": (
                    excess_beyond_governed_tolerance
                ),
                "solver_numerical_allowance": solver_numerical_allowance,
                "status": (
                    "pass"
                    if finite
                    and float(excess_beyond_governed_tolerance)
                    <= solver_numerical_allowance
                    and float(overlay_residual)
                    <= solver_numerical_allowance
                    else "fail"
                ),
            }
        )
    rows.sort(key=lambda row: str(row["constraint_name"]))
    failures = [row for row in rows if row["status"] != "pass"]
    core_unchanged = bool(
        context["underlying_core_sha256_before"]
        == context["underlying_core_sha256_after"]
    )
    result = {
        "schema_version": context["schema_version"],
        "status": "pass" if not failures and core_unchanged else "fail",
        "policy": validation_tolerance_policy_contract(),
        "constraint_family_registry_sha256": context[
            "constraint_family_registry_sha256"
        ],
        "active_constraint_family_count": context[
            "active_constraint_family_count"
        ],
        "registered_acceptance_row_count": len(rows),
        "failed_validation_row_count": len(failures),
        "underlying_core_unchanged": core_unchanged,
        "underlying_core_sha256_before": context[
            "underlying_core_sha256_before"
        ],
        "underlying_core_sha256_after_install": context[
            "underlying_core_sha256_after"
        ],
        "rows_sha256": canonical_json_sha256(rows),
        "rows": rows,
    }
    evidence_path = context.get("evidence_path")
    if evidence_path is not None:
        resolved_path = Path(evidence_path)
        resolved_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        result["evidence_path"] = _portable_repository_path(resolved_path)
        result["evidence_sha256"] = _sha256_file(resolved_path)
    return result


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _portable_repository_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved)


def _variable_bound(variable: Any, attribute: str) -> float | None:
    raw = getattr(variable, attribute)
    return None if raw is None else float(value(raw))


def _record_declared_variable_schema(model: ConcreteModel) -> dict[str, dict[str, Any]]:
    """Freeze first-seen variable schema before any bound propagation mutates it."""

    declared = dict(getattr(model, "declared_variable_schema_snapshot", {}))
    for variable in model.component_data_objects(Var, active=True):
        declared.setdefault(
            variable.name,
            {
                "name": variable.name,
                "domain": str(variable.domain),
                "lb": _variable_bound(variable, "lb"),
                "ub": _variable_bound(variable, "ub"),
            },
        )
    model.declared_variable_schema_snapshot = declared
    return declared


def _active_variable_records(
    model: ConcreteModel, *, allow_undefined: bool = False
) -> list[dict[str, Any]]:
    records = []
    for variable in model.component_data_objects(Var, active=True):
        if variable.value is None and not allow_undefined:
            raise S44CModelBuilderError(
                f"Normal solution contains an undefined variable: {variable.name}."
            )
        current = None if variable.value is None else float(variable.value)
        records.append(
            {
                "name": variable.name,
                "value": current,
                "fixed": bool(variable.fixed),
                "fixed_value": current if variable.fixed else None,
                "stale": bool(variable.stale),
                "domain": str(variable.domain),
                "lb": _variable_bound(variable, "lb"),
                "ub": _variable_bound(variable, "ub"),
            }
        )
    return sorted(records, key=lambda row: row["name"])


_CARRIED_STATE_COMPONENTS = {
    "coke_inventory",
    "sinter_inventory",
    "hot_iron_inventory",
    "cold_slab_inventory",
    "dri_inventory",
}

_SALE_STATE_PRESERVATION_SCHEMA_VERSION = (
    "steel_phase2_sale_state_preservation_v4"
)
_SALE_STATE_TARGET_SCHEMA = (
    "executed_final_product_t",
    "executed_bof_liquid_steel_t",
    "executed_hsm_final_output_t",
    "executed_dsp_final_output_t",
    "coke_inventory_t",
    "sinter_inventory_t",
    "hot_iron_inventory_t",
    "cold_slab_inventory_t",
)
_SALE_STATE_COMPONENTS = {
    "final_product_output",
    "bof_crude_steel_output",
    "c0_hsm_final_product_output",
    "c0_dsp_final_product_output",
    "coke_inventory",
    "sinter_inventory",
    "hot_iron_inventory",
    "cold_slab_inventory",
}
_SALE_C0_CARRIED_COMPONENTS = {
    "coke_inventory",
    "sinter_inventory",
    "hot_iron_inventory",
    "cold_slab_inventory",
}
_SALE_STATE_CONSTRAINT_NAMES = {
    target_id: f"sale_state_{stem}_preservation_exact"
    for target_id, stem in {
        "executed_final_product_t": "executed_final_product",
        "executed_bof_liquid_steel_t": "executed_bof_liquid_steel",
        "executed_hsm_final_output_t": "executed_hsm_final_output",
        "executed_dsp_final_output_t": "executed_dsp_final_output",
        "coke_inventory_t": "coke_inventory",
        "sinter_inventory_t": "sinter_inventory",
        "hot_iron_inventory_t": "hot_iron_inventory",
        "cold_slab_inventory_t": "cold_slab_inventory",
    }.items()
}

_SALE_BREAKTHROUGH_MODES = {
    "phase5b_physical_wag_upper_bound_v1",
    "phase5b_clean_economic_export_v1",
}
_SALE_BREAKTHROUGH_NG_COMPONENTS = (
    "ng_to_hsm_mwh",
    "ng_to_pefa_malerij_mwh",
    "ng_to_pefa_branderij_mwh",
    "ng_to_boiler_mwh",
    "generator_named_ng_mwh",
    "full_site_energy_bridge_named_ng_mwh",
    "site_baseload_ng_mwh",
)


def _variable_structural_classification(model: ConcreteModel) -> dict[str, Any]:
    """Classify variables from active model incidence without guessing values."""

    declared_schema = dict(
        getattr(model, "declared_variable_schema_snapshot", {})
    )
    variables = {
        variable.name: variable
        for variable in model.component_data_objects(Var, active=True)
    }
    constraint_families = {name: set() for name in variables}
    objective_families = {name: set() for name in variables}
    expression_families = {name: set() for name in variables}
    for constraint in model.component_data_objects(Constraint, active=True):
        family = constraint.parent_component().name
        for variable in identify_variables(constraint.body, include_fixed=True):
            if variable.name in constraint_families:
                constraint_families[variable.name].add(family)
    for objective in model.component_data_objects(Objective, active=True):
        for variable in identify_variables(objective.expr, include_fixed=True):
            if variable.name in objective_families:
                objective_families[variable.name].add(objective.name)
    for expression in model.component_data_objects(Expression, active=True):
        family = expression.parent_component().name
        for variable in identify_variables(expression.expr, include_fixed=True):
            if variable.name in expression_families:
                expression_families[variable.name].add(family)
    rows: list[dict[str, Any]] = []
    for name, variable in variables.items():
        constraints = sorted(constraint_families[name])
        objectives = sorted(objective_families[name])
        expressions = sorted(expression_families[name])
        component = variable.parent_component().name
        roles: list[str] = []
        if component in _CARRIED_STATE_COMPONENTS:
            roles.append("carried_state")
        if expressions:
            roles.append("report_result_expression")
        if any("balance" in family.lower() for family in constraints):
            roles.append("balance_constraint")
        if objectives:
            roles.append("economic_or_tiebreak_objective")
        solver_relevant = bool(constraints or objectives)
        incumbent_required = bool(solver_relevant or roles)
        excluded = not incumbent_required
        current_domain = str(variable.domain)
        current_lb = _variable_bound(variable, "lb")
        current_ub = _variable_bound(variable, "ub")
        declared = declared_schema.get(name)
        if declared is None:
            declared = {
                "domain": current_domain,
                "lb": current_lb,
                "ub": current_ub,
            }
            schema_source = "current_model_state_fallback"
        else:
            schema_source = "pre_bound_propagation_declaration_snapshot"
        declared_domain = str(declared["domain"])
        declared_lb = declared.get("lb")
        declared_ub = declared.get("ub")
        rows.append(
            {
                "name": name,
                "component": component,
                # The legacy field names remain aliases for the stable declared
                # schema.  Current/FBBT-derived bounds are evidence, never
                # structural identity.
                "domain": declared_domain,
                "lb": declared_lb,
                "ub": declared_ub,
                "declared_domain": declared_domain,
                "declared_lb": declared_lb,
                "declared_ub": declared_ub,
                "current_domain": current_domain,
                "current_lb": current_lb,
                "current_ub": current_ub,
                "schema_source": schema_source,
                "current_schema_differs_from_declared": bool(
                    (current_domain, current_lb, current_ub)
                    != (declared_domain, declared_lb, declared_ub)
                ),
                "fixed": bool(variable.fixed),
                "value": None if variable.value is None else float(variable.value),
                "stale": bool(variable.stale),
                "active_constraint_families": constraints,
                "active_objective_families": objectives,
                "active_expression_families": expressions,
                "solver_representation": (
                    "active_constraint_or_objective"
                    if solver_relevant
                    else "not_in_active_solver_incidence"
                ),
                "governed_role_categories": sorted(roles),
                "solver_relevant": solver_relevant,
                "incumbent_required": incumbent_required,
                "structurally_inactive_exclusion": excluded,
                "classification_reason": (
                    "required_active_solver_incidence"
                    if solver_relevant
                    else "required_governed_carried_report_or_result_role"
                    if roles
                    else "excluded_no_active_solver_or_governed_role_incidence"
                ),
            }
        )
    rows.sort(key=lambda row: row["name"])

    def digest(payload: Any) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

    schema_fields = (
        "name",
        "declared_domain",
        "declared_lb",
        "declared_ub",
    )
    incidence_fields = (
        "name",
        "active_constraint_families",
        "active_objective_families",
        "active_expression_families",
        "solver_representation",
        "governed_role_categories",
        "classification_reason",
    )
    required = [row for row in rows if row["incumbent_required"]]
    excluded = [row for row in rows if row["structurally_inactive_exclusion"]]
    return {
        "schema_version": "steel_variable_structural_classification_v2",
        "variables": rows,
        "required_variables": required,
        "inactive_exclusions": excluded,
        "complete_structure_sha256": digest(
            [{field: row[field] for field in schema_fields} for row in rows]
        ),
        "solver_relevant_schema_sha256": digest(
            [
                {field: row[field] for field in schema_fields}
                for row in rows
                if row["solver_relevant"]
            ]
        ),
        "inactive_exclusion_sha256": digest(
            [
                {
                    key: row[key]
                    for key in (
                        *schema_fields,
                        *incidence_fields,
                        "solver_relevant",
                        "incumbent_required",
                        "structurally_inactive_exclusion",
                    )
                }
                for row in excluded
            ]
        ),
        "fixed_values_sha256": digest(
            [
                {
                    "name": row["name"],
                    "fixed": row["fixed"],
                    "value": row["value"] if row["fixed"] else None,
                }
                for row in required
            ]
        ),
        "active_incidence_sha256": digest(
            [{field: row[field] for field in incidence_fields} for row in rows]
        ),
    }


def _shared_variable_schema_diagnostics(
    normal_classification: Mapping[str, Any],
    sale_classification: Mapping[str, Any],
    shared_names: Collection[str],
) -> dict[str, Any]:
    """Separate stable declaration mismatches from legitimate derived bounds."""

    normal_by_name = {
        str(row["name"]): row
        for row in normal_classification.get("variables", ())
    }
    sale_by_name = {
        str(row["name"]): row
        for row in sale_classification.get("variables", ())
    }

    def schema(row: Mapping[str, Any], lifecycle: str) -> dict[str, Any]:
        if lifecycle == "declared":
            return {
                "domain": row.get("declared_domain", row.get("domain")),
                "lb": row.get("declared_lb", row.get("lb")),
                "ub": row.get("declared_ub", row.get("ub")),
            }
        return {
            "domain": row.get("current_domain", row.get("domain")),
            "lb": row.get("current_lb", row.get("lb")),
            "ub": row.get("current_ub", row.get("ub")),
        }

    declared_mismatches: list[dict[str, Any]] = []
    derived_differences: list[dict[str, Any]] = []
    category_names: dict[str, list[str]] = {}
    category_schemas: dict[str, dict[str, Any]] = {}
    for name in sorted(set(shared_names)):
        if name not in normal_by_name or name not in sale_by_name:
            continue
        normal_declared = schema(normal_by_name[name], "declared")
        sale_declared = schema(sale_by_name[name], "declared")
        if normal_declared != sale_declared:
            declared_mismatches.append(
                {
                    "name": name,
                    "normal_declared_schema": normal_declared,
                    "sale_declared_schema": sale_declared,
                }
            )
        normal_current = schema(normal_by_name[name], "current")
        sale_current = schema(sale_by_name[name], "current")
        if normal_current != sale_current:
            detail = {
                "name": name,
                "normal_current_schema": normal_current,
                "sale_current_schema": sale_current,
            }
            derived_differences.append(detail)
            category_schema = {
                "normal_current_schema": normal_current,
                "sale_current_schema": sale_current,
            }
            category_key = json.dumps(
                category_schema, sort_keys=True, separators=(",", ":")
            )
            category_names.setdefault(category_key, []).append(name)
            category_schemas[category_key] = category_schema
    categories = [
        {
            **category_schemas[key],
            "variable_count": len(names),
            "variable_names": names,
        }
        for key, names in category_names.items()
    ]
    categories.sort(
        key=lambda row: (
            -int(row["variable_count"]),
            json.dumps(row, sort_keys=True, separators=(",", ":")),
        )
    )
    return {
        "declared_schema_mismatches": declared_mismatches,
        "declared_schema_mismatch_count": len(declared_mismatches),
        "current_or_derived_bound_differences": derived_differences,
        "current_or_derived_bound_difference_count": len(derived_differences),
        "current_or_derived_bound_pair_categories": categories,
    }


def _variable_name_and_schema_hashes(
    records: Collection[Mapping[str, Any]],
) -> tuple[str, str, str]:
    names = [str(row["name"]) for row in records]
    schema = [
        {
            "name": row["name"],
            "domain": row["domain"],
            "lb": row["lb"],
            "ub": row["ub"],
        }
        for row in records
    ]
    fixed_schema = [
        {
            "name": row["name"],
            "fixed": bool(row["fixed"]),
            "fixed_value": (
                float(row["fixed_value"])
                if row["fixed_value"] is not None
                else None
            ),
        }
        for row in records
    ]
    return (
        hashlib.sha256(
            json.dumps(names, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        hashlib.sha256(
            json.dumps(
                schema, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        hashlib.sha256(
            json.dumps(
                fixed_schema, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
    )


def _variable_value_and_fixed_state_sha256(
    records: Collection[Mapping[str, Any]],
) -> str:
    state = [
        {
            "name": row["name"],
            "value": (
                None if row["value"] is None else float(row["value"])
            ),
            "fixed": bool(row["fixed"]),
            "fixed_value": (
                float(row["fixed_value"])
                if row["fixed_value"] is not None
                else None
            ),
        }
        for row in records
    ]
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _model_structure_sha256(model: ConcreteModel) -> str:
    classification = _variable_structural_classification(model)
    payload = {
        "complete_structure_sha256": classification[
            "complete_structure_sha256"
        ],
        "active_incidence_sha256": classification["active_incidence_sha256"],
        "active_constraint_names": sorted(
            constraint.name
            for constraint in model.component_data_objects(
                Constraint, active=True
            )
        ),
        "active_objectives": sorted(
            [
                {
                    "name": objective.name,
                    "sense": str(objective.sense),
                }
                for objective in model.component_data_objects(
                    Objective, active=True
                )
            ],
            key=lambda row: row["name"],
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _write_deterministic_gzip_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, mtime=0
        ) as compressed:
            compressed.write(encoded)


def _read_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise S44CModelBuilderError(
            "Normal solution record must contain a JSON mapping."
        )
    return payload


def _solver_version(solver: Any) -> str:
    try:
        raw = solver.version()
    except Exception:
        return "unavailable"
    if isinstance(raw, tuple):
        return ".".join(str(item) for item in raw)
    return str(raw)


def _capture_complete_normal_solution(
    model: ConcreteModel,
    *,
    metadata: Mapping[str, Any],
    solver: Any,
    configuration_id: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    if policy.get("enabled") is not True:
        raise S44CModelBuilderError(
            "Normal-solution capture requires enabled=true."
    )
    path = Path(str(policy["path"])).resolve()
    classification = _variable_structural_classification(model)
    exclusion_enabled = bool(
        policy.get("structural_inactive_exclusion_enabled", False)
    )
    undefined_required = [
        row
        for row in (
            classification["required_variables"]
            if exclusion_enabled
            else classification["variables"]
        )
        if row["value"] is None
    ]
    if undefined_required:
        failure_path = path.with_name(path.name + ".classification_failure.json")
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        failure_path.write_text(
            json.dumps(
                {
                    "status": "fail_undefined_incumbent_required",
                    "undefined_variables": undefined_required,
                    "classification": classification,
                    "provenance": dict(policy.get("provenance", {})),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        error = S44CModelBuilderError(
            "Normal solution contains undefined solver/governed-relevant "
            f"variables: {[row['name'] for row in undefined_required]}."
        )
        error.phase2_stage = "normal_capture.variable_classification"
        error.variable_classification_evidence_path = str(failure_path)
        raise error
    required_names = {
        str(row["name"])
        for row in (
            classification["required_variables"]
            if exclusion_enabled
            else classification["variables"]
        )
    }
    records = [
        row
        for row in _active_variable_records(model, allow_undefined=True)
        if str(row["name"]) in required_names
    ]
    name_hash, schema_hash, fixed_schema_hash = (
        _variable_name_and_schema_hashes(records)
    )
    capture_audit = _audit_loaded_incumbent(
        model,
        tolerance=float(policy.get("feasibility_tolerance", 1e-6)),
        structurally_inactive_exclusions=tuple(
            str(row["name"])
            for row in classification["inactive_exclusions"]
        ),
    )
    if (
        capture_audit["undefined_value_count"] != 0
        or capture_audit["max_variable_bound_violation"]
        > capture_audit["tolerance"]
        or capture_audit["max_integrality_violation"]
        > capture_audit["tolerance"]
    ):
        raise S44CModelBuilderError(
            "Normal solution capture failed the exact loaded-value precheck "
            "for undefined values, variable bounds, or integrality."
        )
    payload = {
        "schema_version": "steel_complete_normal_solution_v2",
        "configuration_id": configuration_id,
        "replan_index": int(policy["replan_index"]),
        "variable_count": len(records),
        "variable_name_sha256": name_hash,
        "variable_schema_sha256": schema_hash,
        "variable_fixed_schema_sha256": fixed_schema_hash,
        "model_structure_sha256": _model_structure_sha256(model),
        "variable_classification": classification,
        "complete_structure_sha256": classification["complete_structure_sha256"],
        "solver_relevant_schema_sha256": classification[
            "solver_relevant_schema_sha256"
        ],
        "inactive_exclusion_sha256": classification[
            "inactive_exclusion_sha256"
        ],
        "fixed_values_sha256": classification["fixed_values_sha256"],
        "active_incidence_sha256": classification["active_incidence_sha256"],
        "inactive_exclusion_count": len(classification["inactive_exclusions"]),
        "structural_inactive_exclusion_enabled": exclusion_enabled,
        "variables": records,
        "post_solve_incumbent_audit": capture_audit,
        "constraint_feasibility_authority": (
            "normal_optimization_solver_termination_then_required_sale_"
            "fixed_incumbent_pyomo_and_native_gurobi_zero_objective"
        ),
        "solve_hierarchy": {
            "primary_cost_objective_eur": metadata.get(
                "primary_cost_objective_eur"
            ),
            "primary_cost_best_bound_eur": metadata.get(
                "primary_cost_best_bound_eur"
            ),
            "primary_cost_termination_condition": metadata.get(
                "primary_cost_termination_condition"
            ),
            "tie_break_objective_value": metadata.get(
                "tie_break_objective_value"
            ),
            "tie_break_cost_objective_eur": metadata.get(
                "tie_break_cost_objective_eur"
            ),
            "production_progress_target_t": metadata.get(
                "production_progress_target_t"
            ),
            "production_progress_optimum_deviation_t": metadata.get(
                "production_progress_optimum_deviation_t"
            ),
            "production_progress_actual_t": metadata.get(
                "production_progress_actual_t"
            ),
        },
        "solver": {
            "name": str(getattr(solver, "name", "")),
            "version": _solver_version(solver),
            "options": {
                str(key): value
                for key, value in sorted(
                    dict(getattr(solver, "options", {})).items()
                )
            },
        },
        "controller_state": dict(policy.get("controller_state", {})),
        "provenance": dict(policy.get("provenance", {})),
    }
    _write_deterministic_gzip_json(path, payload)
    return {
        "normal_solution_capture_path": str(path),
        "normal_solution_capture_sha256": _sha256_file(path),
        "normal_solution_variable_count": len(records),
        "normal_solution_variable_name_sha256": name_hash,
        "normal_solution_variable_schema_sha256": schema_hash,
        "normal_solution_variable_fixed_schema_sha256": fixed_schema_hash,
        "normal_solution_model_structure_sha256": payload[
            "model_structure_sha256"
        ],
        "normal_solution_complete_structure_sha256": payload[
            "complete_structure_sha256"
        ],
        "normal_solution_solver_relevant_schema_sha256": payload[
            "solver_relevant_schema_sha256"
        ],
        "normal_solution_inactive_exclusion_sha256": payload[
            "inactive_exclusion_sha256"
        ],
        "normal_solution_active_incidence_sha256": payload[
            "active_incidence_sha256"
        ],
        "normal_solution_inactive_exclusion_count": payload[
            "inactive_exclusion_count"
        ],
    }


def _native_gurobi_zero_objective_check(
    lp_path: Path,
    *,
    log_path: Path,
    iis_path: Path,
    tolerance: float,
) -> dict[str, Any]:
    import gurobipy as gp

    native = gp.read(str(lp_path))
    native.Params.TimeLimit = 300.0
    native.Params.DualReductions = 0
    native.Params.InfUnbdInfo = 1
    native.Params.FeasibilityTol = tolerance
    native.Params.LogFile = str(log_path)
    native.optimize()
    status_names = {
        gp.GRB.OPTIMAL: "optimal",
        gp.GRB.INFEASIBLE: "infeasible",
        gp.GRB.INF_OR_UNBD: "infeasible_or_unbounded",
        gp.GRB.UNBOUNDED: "unbounded",
        gp.GRB.TIME_LIMIT: "time_limit",
        gp.GRB.NUMERIC: "numeric",
    }
    status = status_names.get(native.Status, f"status_{native.Status}")

    def _optional_quality_attribute(name: str) -> float | None:
        if native.SolCount <= 0:
            return None
        try:
            return float(getattr(native, name))
        except (AttributeError, gp.GurobiError):
            # Some quality attributes (notably IntVio) are unavailable when
            # the fixed oracle LP contains no variables of the relevant type.
            return None

    iis_created = False
    if native.Status in {gp.GRB.INFEASIBLE, gp.GRB.INF_OR_UNBD}:
        native.computeIIS()
        native.write(str(iis_path))
        iis_created = True
    return {
        "status": status,
        "status_code": int(native.Status),
        "solution_count": int(native.SolCount),
        "objective_sense": (
            "maximise" if native.ModelSense == -1 else "minimise"
        ),
        "objective_term_count": sum(
            abs(float(variable.Obj)) > 0.0 for variable in native.getVars()
        ),
        "max_primal_violation": _optional_quality_attribute("MaxVio"),
        "constraint_violation": _optional_quality_attribute("ConstrVio"),
        "bound_violation": _optional_quality_attribute("BoundVio"),
        "integrality_violation": _optional_quality_attribute("IntVio"),
        "model_fingerprint": f"0x{int(native.Fingerprint) & 0xFFFFFFFF:08x}",
        "row_count": int(native.NumConstrs),
        "column_count": int(native.NumVars),
        "binary_count": int(native.NumBinVars),
        "iis_created": iis_created,
        "iis_path": str(iis_path) if iis_created else None,
    }


def _canonical_payload_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _validated_sale_state_preservation_contract(
    contract: Mapping[str, Any],
    *,
    model: ConcreteModel,
    saved_capture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    required_keys = {
        "schema_version",
        "enabled",
        "configuration_id",
        "replan_index",
        "execution_hours",
        "implementation_sha256",
    }
    if set(contract) != required_keys:
        raise S44CModelBuilderError(
            "Sale state-preservation contract has missing or extra fields."
        )
    try:
        implementation_sha256 = str(
            contract["implementation_sha256"]
        ).lower()
        normalized = {
            "schema_version": str(contract["schema_version"]),
            "enabled": contract["enabled"] is True,
            "configuration_id": str(contract["configuration_id"]),
            "replan_index": int(contract["replan_index"]),
            "execution_hours": int(contract["execution_hours"]),
            "implementation_sha256": implementation_sha256,
        }
    except (TypeError, ValueError) as exc:
        raise S44CModelBuilderError(
            "Sale state-preservation contract identity is invalid."
        ) from exc
    if (
        normalized["schema_version"]
        != _SALE_STATE_PRESERVATION_SCHEMA_VERSION
        or normalized["enabled"] is not True
        or normalized["configuration_id"]
        != "C0_current_BF_BOF_reference"
        or normalized["replan_index"] < 0
        or normalized["execution_hours"] <= 0
        or normalized["execution_hours"] > len(model.TIME)
        or len(implementation_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in implementation_sha256
        )
    ):
        raise S44CModelBuilderError(
            "Sale state-preservation contract identity is invalid."
        )
    if saved_capture is not None:
        provenance = dict(saved_capture.get("provenance", {}))
        try:
            saved_replan_index = int(saved_capture.get("replan_index", -1))
        except (TypeError, ValueError) as exc:
            raise S44CModelBuilderError(
                "Sale state-preservation capture identity is invalid."
            ) from exc
        if (
            saved_capture.get("configuration_id")
            != normalized["configuration_id"]
            or saved_replan_index != normalized["replan_index"]
            or provenance.get("implementation_sha256")
            != implementation_sha256
        ):
            raise S44CModelBuilderError(
                "Sale state-preservation capture identity does not match the "
                "configuration, replan, or implementation contract."
            )
    return normalized


def _sale_state_expressions(
    model: ConcreteModel, *, execution_hours: int
) -> dict[str, Any]:
    time_by_index = {int(t): t for t in model.TIME}
    expected_execution_indices = set(range(execution_hours))
    if not expected_execution_indices.issubset(time_by_index):
        raise S44CModelBuilderError(
            "Sale state preservation execution hours are absent from model.TIME."
        )
    missing_components = sorted(
        component
        for component in _SALE_STATE_COMPONENTS
        if not hasattr(model, component)
    )
    present_carried_components = {
        component
        for component in _CARRIED_STATE_COMPONENTS
        if hasattr(model, component)
    }
    if (
        missing_components
        or present_carried_components != _SALE_C0_CARRIED_COMPONENTS
    ):
        raise S44CModelBuilderError(
            "Sale state-preservation model component schema mismatch: "
            f"missing={missing_components}, "
            f"carried={sorted(present_carried_components)}."
        )
    handoff_index = execution_hours - 1
    handoff_hour = time_by_index[handoff_index]
    return {
        "executed_final_product_t": sum(
            model.final_product_output[time_by_index[index]]
            for index in range(execution_hours)
        ),
        "executed_bof_liquid_steel_t": sum(
            model.bof_crude_steel_output[time_by_index[index]]
            for index in range(execution_hours)
        ),
        "executed_hsm_final_output_t": sum(
            model.c0_hsm_final_product_output[time_by_index[index]]
            for index in range(execution_hours)
        ),
        "executed_dsp_final_output_t": sum(
            model.c0_dsp_final_product_output[time_by_index[index]]
            for index in range(execution_hours)
        ),
        "coke_inventory_t": model.coke_inventory[handoff_hour],
        "sinter_inventory_t": model.sinter_inventory[handoff_hour],
        "hot_iron_inventory_t": model.hot_iron_inventory[handoff_hour],
        "cold_slab_inventory_t": model.cold_slab_inventory[handoff_hour],
    }


def _sale_state_schema_payload() -> list[dict[str, Any]]:
    component_by_target = {
        "executed_final_product_t": "final_product_output",
        "executed_bof_liquid_steel_t": "bof_crude_steel_output",
        "executed_hsm_final_output_t": "c0_hsm_final_product_output",
        "executed_dsp_final_output_t": "c0_dsp_final_product_output",
    }
    cumulative_targets = set(component_by_target)
    return [
        {
            "target_id": target_id,
            "model_component": component_by_target.get(
                target_id, target_id.removesuffix("_t")
            ),
            "selection": (
                "sum_executed_hours"
                if target_id in cumulative_targets
                else "handoff_hour"
            ),
            "unit": "t",
            "operational_constraint": "full_precision_exact_equality",
            "final_validation": "independent_state_acceptance",
            "allowed_tolerance_t": TERMINAL_STATE_TOLERANCE_T,
        }
        for target_id in _SALE_STATE_TARGET_SCHEMA
    ]


def _sale_state_target_bounds(
    targets: Mapping[str, float],
) -> dict[str, dict[str, float]]:
    return {
        target_id: {
            "lower_bound_t": float(targets[target_id])
            - TERMINAL_STATE_TOLERANCE_T,
            "upper_bound_t": float(targets[target_id])
            + TERMINAL_STATE_TOLERANCE_T,
        }
        for target_id in _SALE_STATE_TARGET_SCHEMA
    }


def _capture_sale_state_preservation_targets(
    model: ConcreteModel,
    *,
    contract: Mapping[str, Any],
    saved_capture: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_contract = _validated_sale_state_preservation_contract(
        contract, model=model, saved_capture=saved_capture
    )
    expressions = _sale_state_expressions(
        model, execution_hours=int(normalized_contract["execution_hours"])
    )
    if tuple(expressions) != _SALE_STATE_TARGET_SCHEMA:
        raise S44CModelBuilderError(
            "Sale state-preservation target schema changed."
        )
    try:
        targets = {
            target_id: float(value(expressions[target_id]))
            for target_id in _SALE_STATE_TARGET_SCHEMA
        }
    except (TypeError, ValueError) as exc:
        raise S44CModelBuilderError(
            "Sale state-preservation target is undefined or nonnumeric."
        ) from exc
    if not all(math.isfinite(target) for target in targets.values()):
        raise S44CModelBuilderError(
            "Sale state-preservation target contains a nonfinite value."
        )
    state_schema = _sale_state_schema_payload()
    constraint_names = {
        target_id: _SALE_STATE_CONSTRAINT_NAMES[target_id]
        for target_id in _SALE_STATE_TARGET_SCHEMA
    }
    target_bounds = _sale_state_target_bounds(targets)
    return {
        "schema_version": _SALE_STATE_PRESERVATION_SCHEMA_VERSION,
        "contract": normalized_contract,
        "handoff_index": int(normalized_contract["execution_hours"]) - 1,
        "target_schema": list(_SALE_STATE_TARGET_SCHEMA),
        "state_schema": state_schema,
        "state_schema_sha256": _canonical_payload_sha256(state_schema),
        "targets": targets,
        "targets_sha256": _canonical_payload_sha256(targets),
        "target_bounds": target_bounds,
        "target_bounds_sha256": _canonical_payload_sha256(target_bounds),
        "constraint_names": constraint_names,
        "constraint_names_sha256": _canonical_payload_sha256(
            constraint_names
        ),
    }


def _apply_sale_state_preservation(
    model: ConcreteModel,
    *,
    containment_result: Mapping[str, Any],
    containment_policy: Mapping[str, Any],
    contract: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    if tolerance != SOLVER_NUMERICAL_TOLERANCE:
        raise S44CModelBuilderError(
            "Sale state preservation requires the strict canonical solver "
            "numerical tolerance."
        )
    normalized_contract = _validated_sale_state_preservation_contract(
        contract, model=model
    )
    if containment_result.get("status") != "pass":
        raise S44CModelBuilderError(
            "Sale state preservation requires a passing containment oracle."
        )
    capture = containment_result.get("state_preservation_capture")
    if not isinstance(capture, Mapping):
        raise S44CModelBuilderError(
            "Sale containment omitted the verified state-preservation targets."
        )
    if dict(capture.get("contract", {})) != normalized_contract:
        raise S44CModelBuilderError(
            "Sale state-preservation target contract identity mismatch."
        )
    expected_provenance = dict(
        containment_policy.get("normal_solution_expected_provenance", {})
    )
    if (
        dict(containment_result.get("provenance", {})) != expected_provenance
        or expected_provenance.get("implementation_sha256")
        != normalized_contract["implementation_sha256"]
        or containment_result.get("saved_normal_solution_sha256")
        != containment_policy.get("normal_solution_record_sha256")
        or containment_result.get("fixed_state_sha256_before")
        != containment_result.get("fixed_state_sha256_after")
        or containment_result.get("value_state_sha256_before")
        != containment_result.get("value_state_sha256_after")
    ):
        raise S44CModelBuilderError(
            "Sale state preservation rejected capture provenance, fingerprint, "
            "implementation identity, or oracle restoration."
        )
    evidence_dir = Path(str(containment_policy["oracle_directory"])).resolve()
    containment_record_path = evidence_dir / "sale_incumbent_containment.json"
    containment_record_sha256 = str(
        containment_result.get("record_sha256", "")
    )
    if (
        not containment_record_path.is_file()
        or _sha256_file(containment_record_path)
        != containment_record_sha256
    ):
        raise S44CModelBuilderError(
            "Sale state preservation rejected the containment record fingerprint."
        )
    try:
        containment_record = json.loads(
            containment_record_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise S44CModelBuilderError(
            "Sale state preservation could not verify the containment record."
        ) from exc
    if (
        containment_record.get("status") != "pass"
        or containment_record.get("state_preservation_capture") != capture
        or containment_record.get("provenance") != expected_provenance
        or containment_record.get("saved_normal_solution_sha256")
        != containment_policy.get("normal_solution_record_sha256")
    ):
        raise S44CModelBuilderError(
            "Sale state-preservation capture is not bound to the passing "
            "containment record."
        )
    target_schema = tuple(capture.get("target_schema", ()))
    targets = dict(capture.get("targets", {}))
    target_bounds = dict(capture.get("target_bounds", {}))
    expected_state_schema = _sale_state_schema_payload()
    if (
        capture.get("schema_version")
        != _SALE_STATE_PRESERVATION_SCHEMA_VERSION
        or capture.get("handoff_index")
        != normalized_contract["execution_hours"] - 1
        or target_schema != _SALE_STATE_TARGET_SCHEMA
        or set(targets) != set(_SALE_STATE_TARGET_SCHEMA)
        or set(target_bounds) != set(_SALE_STATE_TARGET_SCHEMA)
        or capture.get("state_schema") != expected_state_schema
        or capture.get("constraint_names") != _SALE_STATE_CONSTRAINT_NAMES
    ):
        raise S44CModelBuilderError(
            "Sale state-preservation target schema has missing or extra fields."
        )
    try:
        targets = {
            target_id: float(targets[target_id])
            for target_id in _SALE_STATE_TARGET_SCHEMA
        }
    except (TypeError, ValueError) as exc:
        raise S44CModelBuilderError(
            "Sale state-preservation target is nonnumeric."
        ) from exc
    if (
        not all(math.isfinite(target) for target in targets.values())
        or target_bounds != _sale_state_target_bounds(targets)
        or capture.get("targets_sha256")
        != _canonical_payload_sha256(targets)
        or capture.get("target_bounds_sha256")
        != _canonical_payload_sha256(target_bounds)
        or capture.get("state_schema_sha256")
        != _canonical_payload_sha256(expected_state_schema)
        or capture.get("constraint_names_sha256")
        != _canonical_payload_sha256(_SALE_STATE_CONSTRAINT_NAMES)
    ):
        raise S44CModelBuilderError(
            "Sale state-preservation target values or schema fingerprints are invalid."
        )
    expressions = _sale_state_expressions(
        model, execution_hours=int(normalized_contract["execution_hours"])
    )
    for target_id, constraint_name in _SALE_STATE_CONSTRAINT_NAMES.items():
        if hasattr(model, constraint_name):
            raise S44CModelBuilderError(
                "Sale state-preservation constraint already exists: "
                f"{constraint_name}."
            )
        setattr(
            model,
            constraint_name,
            Constraint(expr=expressions[target_id] == targets[target_id]),
        )
    actual_constraint_names = {
        target_id: getattr(model, constraint_name).name
        for target_id, constraint_name in _SALE_STATE_CONSTRAINT_NAMES.items()
    }
    if actual_constraint_names != _SALE_STATE_CONSTRAINT_NAMES:
        raise S44CModelBuilderError(
            "Sale state-preservation constraint-name schema changed."
        )
    evidence_path = evidence_dir / "sale_state_preservation_pre_solve.json"
    record = {
        "schema_version": _SALE_STATE_PRESERVATION_SCHEMA_VERSION,
        "status": "targets_applied_pending_economic_solve",
        "configuration_id": normalized_contract["configuration_id"],
        "replan_index": normalized_contract["replan_index"],
        "execution_hours": normalized_contract["execution_hours"],
        "handoff_index": int(normalized_contract["execution_hours"]) - 1,
        "implementation_sha256": normalized_contract[
            "implementation_sha256"
        ],
        "source_capture_path": containment_result.get(
            "saved_normal_solution_path"
        ),
        "source_capture_sha256": containment_result.get(
            "saved_normal_solution_sha256"
        ),
        "source_capture_provenance": expected_provenance,
        "containment_record_path": _portable_repository_path(
            containment_record_path
        ),
        "containment_record_sha256": containment_record_sha256,
        "target_schema": list(_SALE_STATE_TARGET_SCHEMA),
        "state_schema": _sale_state_schema_payload(),
        "state_schema_sha256": capture["state_schema_sha256"],
        "targets": targets,
        "targets_sha256": capture["targets_sha256"],
        "target_bounds": target_bounds,
        "target_bounds_sha256": capture["target_bounds_sha256"],
        "constraint_names": actual_constraint_names,
        "constraint_names_sha256": capture["constraint_names_sha256"],
        "expected_values": targets,
        "actual_values": None,
        "signed_residuals": None,
        "absolute_residuals": None,
        "normalized_residuals": None,
        "per_state_validation": None,
        "max_residual": None,
        "solver_numerical_tolerance": tolerance,
        "validation_acceptance_tolerance_t": TERMINAL_STATE_TOLERANCE_T,
        "validation_tolerance_policy": validation_tolerance_policy_contract(),
    }
    evidence_path.write_text(
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return {
        "record": record,
        "evidence_path": evidence_path,
        "contract": normalized_contract,
        "targets": targets,
        "target_bounds": target_bounds,
    }


def _finalize_sale_state_preservation(
    model: ConcreteModel,
    *,
    context: Mapping[str, Any],
    termination_condition: str,
    tolerance: float,
) -> dict[str, Any]:
    if tolerance != TERMINAL_STATE_TOLERANCE_T:
        raise S44CModelBuilderError(
            "Sale terminal-state reporting requires the canonical 1.0-t "
            "validation acceptance tolerance."
        )
    contract = dict(context["contract"])
    targets = {
        target_id: float(context["targets"][target_id])
        for target_id in _SALE_STATE_TARGET_SCHEMA
    }
    expected_bounds = _sale_state_target_bounds(targets)
    expressions = _sale_state_expressions(
        model, execution_hours=int(contract["execution_hours"])
    )
    schema_failures: list[str] = []
    record = dict(context["record"])
    if (
        record.get("schema_version") != _SALE_STATE_PRESERVATION_SCHEMA_VERSION
        or tuple(record.get("target_schema", ())) != _SALE_STATE_TARGET_SCHEMA
        or record.get("target_bounds") != expected_bounds
        or record.get("target_bounds_sha256")
        != _canonical_payload_sha256(expected_bounds)
        or record.get("constraint_names") != _SALE_STATE_CONSTRAINT_NAMES
        or record.get("constraint_names_sha256")
        != _canonical_payload_sha256(_SALE_STATE_CONSTRAINT_NAMES)
    ):
        schema_failures.append("evidence_schema_mismatch")
    expected_constraint_name_set = {
        constraint_name for constraint_name in _SALE_STATE_CONSTRAINT_NAMES.values()
    }
    actual_constraint_name_set = {
        name
        for name in model.component_map(Constraint)
        if name.startswith("sale_state_") and "_preservation_" in name
    }
    if actual_constraint_name_set != expected_constraint_name_set:
        schema_failures.append("constraint_name_schema_mismatch")
    for target_id, constraint_name in _SALE_STATE_CONSTRAINT_NAMES.items():
        constraint = getattr(model, constraint_name, None)
        try:
            lower = float(value(constraint.lower))
            upper = float(value(constraint.upper))
            body_matches = str(constraint.body) == str(expressions[target_id])
        except (AttributeError, TypeError, ValueError):
            lower = math.nan
            upper = math.nan
            body_matches = False
        if (
            not math.isfinite(lower)
            or not math.isfinite(upper)
            or lower != targets[target_id]
            or upper != targets[target_id]
            or not body_matches
            or constraint is None
            or not constraint.active
        ):
            schema_failures.append(f"invalid_exact_target:{target_id}")
    actual_values: dict[str, float | None] = {}
    signed_residuals: dict[str, float | None] = {}
    absolute_residuals: dict[str, float | None] = {}
    normalized_residuals: dict[str, float | None] = {}
    per_state_validation: dict[str, dict[str, Any]] = {}
    for target_id in _SALE_STATE_TARGET_SCHEMA:
        try:
            actual = float(value(expressions[target_id]))
        except (TypeError, ValueError):
            actual = None
        if actual is not None and not math.isfinite(actual):
            actual = None
        actual_values[target_id] = actual
        signed = actual - targets[target_id] if actual is not None else None
        signed_residuals[target_id] = signed
        if signed is None:
            absolute_residuals[target_id] = None
            normalized_residuals[target_id] = None
            per_state_validation[target_id] = {
                "validation_id": f"sale_state_preservation[{target_id}]",
                "purpose": "cumulative_production_or_carried_state",
                "unit": "t",
                "aggregation": "independent_state_no_accumulation",
                "target_value_t": targets[target_id],
                **expected_bounds[target_id],
                "signed_residual_t": None,
                "absolute_residual_t": None,
                "allowed_tolerance_t": tolerance,
                "normalized_residual": None,
                "status": "fail",
            }
            continue
        validation = validation_record(
            validation_id=f"sale_state_preservation[{target_id}]",
            purpose="cumulative_production_or_carried_state",
            unit="t",
            raw_residual=signed,
            allowed_tolerance=tolerance,
            aggregation="independent_state_no_accumulation",
        )
        absolute_residuals[target_id] = float(validation["raw_residual"])
        normalized_residuals[target_id] = float(
            validation["normalized_residual"]
        )
        per_state_validation[target_id] = {
            **validation,
            "target_value_t": targets[target_id],
            **expected_bounds[target_id],
            "signed_residual_t": signed,
            "absolute_residual_t": validation["raw_residual"],
            "allowed_tolerance_t": validation["allowed_tolerance"],
        }
    finite_residuals = [
        residual
        for residual in absolute_residuals.values()
        if residual is not None
    ]
    max_residual = max(finite_residuals, default=math.inf)
    solved = termination_condition.lower() in {"optimal", "feasible"}
    passed = bool(
        solved
        and not schema_failures
        and len(finite_residuals) == len(_SALE_STATE_TARGET_SCHEMA)
        and all(
            row["status"] == "pass"
            for row in per_state_validation.values()
        )
    )
    record.update(
        {
            "status": "pass" if passed else "fail_closed",
            "economic_solve_termination_condition": termination_condition,
            "schema_failure_reasons": sorted(set(schema_failures)),
            "actual_values": actual_values,
            "signed_residuals": signed_residuals,
            "absolute_residuals": absolute_residuals,
            "normalized_residuals": normalized_residuals,
            "per_state_validation": per_state_validation,
            "max_residual": max_residual if math.isfinite(max_residual) else None,
        }
    )
    pre_solve_evidence_path = Path(context["evidence_path"])
    record["pre_solve_evidence_path"] = _portable_repository_path(
        pre_solve_evidence_path
    )
    record["pre_solve_evidence_sha256"] = _sha256_file(
        pre_solve_evidence_path
    )
    evidence_path = (
        pre_solve_evidence_path.parent
        / "sale_state_preservation_final.json"
    )
    evidence_path.write_text(
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return {
        "status": record["status"],
        "evidence_path": _portable_repository_path(evidence_path),
        "evidence_sha256": _sha256_file(evidence_path),
        "pre_solve_evidence_path": _portable_repository_path(
            pre_solve_evidence_path
        ),
        "pre_solve_evidence_sha256": _sha256_file(
            pre_solve_evidence_path
        ),
        "targets_sha256": record["targets_sha256"],
        "state_schema_sha256": record["state_schema_sha256"],
        "constraint_names_sha256": record["constraint_names_sha256"],
        "max_residual": record["max_residual"],
        "actual_values": actual_values,
        "signed_residuals": signed_residuals,
        "absolute_residuals": absolute_residuals,
        "normalized_residuals": normalized_residuals,
        "per_state_validation": per_state_validation,
        "schema_failure_reasons": record["schema_failure_reasons"],
    }


def _sale_incumbent_containment_oracle(
    model: ConcreteModel,
    *,
    solver: Any,
    policy: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    """Prove that the accepted no-export incumbent is contained in Mode C.

    Every variable shared with the captured ordinary formulation is fixed at
    its full-precision saved value.  Only the three genuinely new grid-
    exchange variable families may be absent from the capture; export is fixed
    to zero while import and the exclusivity binary are derived by the model.
    """

    try:
        resolved_tolerance_policy = resolve_policy_contract(
            policy["validation_tolerance_policy"]
        )
    except (KeyError, TypeError, ValidationTolerancePolicyError) as exc:
        raise S44CModelBuilderError(
            "Sale containment requires the canonical validation-tolerance "
            "policy identity."
        ) from exc
    if tolerance != SOLVER_NUMERICAL_TOLERANCE:
        raise S44CModelBuilderError(
            "Sale containment solver numerical tolerance must remain strict."
        )

    record_path = Path(str(policy["normal_solution_record_path"])).resolve()
    evidence_dir = Path(str(policy["oracle_directory"])).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    expected_hash = str(policy["normal_solution_record_sha256"])
    if not record_path.is_file() or _sha256_file(record_path) != expected_hash:
        raise S44CModelBuilderError("Sale-containment normal record fingerprint mismatch.")
    saved = _read_gzip_json(record_path)
    if saved.get("schema_version") != "steel_complete_normal_solution_v2":
        raise S44CModelBuilderError("Sale containment requires complete-normal schema v2.")
    if saved.get("structural_inactive_exclusion_enabled") is not True:
        raise S44CModelBuilderError(
            "Sale containment requires the governed structural-classification capture mode."
        )
    saved_capture_audit = saved.get("post_solve_incumbent_audit")
    if not isinstance(saved_capture_audit, Mapping):
        raise S44CModelBuilderError(
            "Sale containment requires the exact post-solve incumbent audit "
            "embedded in the normal capture."
        )
    expected_provenance = dict(policy.get("normal_solution_expected_provenance", {}))
    if dict(saved.get("provenance", {})) != expected_provenance:
        raise S44CModelBuilderError("Sale-containment provenance mismatch.")

    variables = {
        variable.name: variable
        for variable in model.component_data_objects(Var, active=True)
    }
    saved_rows = list(saved.get("variables", ()))
    saved_by_name = {str(row["name"]): row for row in saved_rows}
    sale_classification = _variable_structural_classification(model)
    normal_classification = dict(saved.get("variable_classification", {}))
    if (
        normal_classification.get("schema_version")
        != "steel_variable_structural_classification_v2"
    ):
        raise S44CModelBuilderError(
            "Sale containment requires governed normal variable classification."
        )
    missing = sorted(set(saved_by_name).difference(variables))
    allowed_new_prefixes = (
        "gross_grid_import_mwh[",
        "gross_grid_export_mwh[",
        "grid_import_mode[",
    )
    sale_required_names = {
        str(row["name"])
        for row in sale_classification["required_variables"]
        if not str(row["name"]).startswith(allowed_new_prefixes)
    }
    required_not_captured = sorted(sale_required_names.difference(saved_by_name))
    normal_exclusions = {
        str(row["name"]): row
        for row in normal_classification.get("inactive_exclusions", ())
    }
    new_names = sorted(
        set(variables).difference(saved_by_name).difference(normal_exclusions)
    )
    prohibited_new = [
        name for name in new_names if not name.startswith(allowed_new_prefixes)
    ]
    sale_exclusions = {
        str(row["name"]): row
        for row in sale_classification["inactive_exclusions"]
        if not str(row["name"]).startswith(allowed_new_prefixes)
    }
    exclusion_name_mismatch = sorted(
        set(normal_exclusions).symmetric_difference(sale_exclusions)
    )
    exclusion_classification_mismatch = sorted(
        name
        for name in set(normal_exclusions).intersection(sale_exclusions)
        if _shared_variable_schema_diagnostics(
            {"variables": [normal_exclusions[name]]},
            {"variables": [sale_exclusions[name]]},
            [name],
        )["declared_schema_mismatch_count"]
        or {
            key: normal_exclusions[name].get(key)
            for key in (
                "active_constraint_families",
                "active_objective_families",
                "active_expression_families",
                "solver_representation",
                "governed_role_categories",
                "solver_relevant",
                "incumbent_required",
                "structurally_inactive_exclusion",
                "classification_reason",
            )
        }
        != {
            key: sale_exclusions[name].get(key)
            for key in (
                "active_constraint_families",
                "active_objective_families",
                "active_expression_families",
                "solver_representation",
                "governed_role_categories",
                "solver_relevant",
                "incumbent_required",
                "structurally_inactive_exclusion",
                "classification_reason",
            )
        }
    )
    shared_schema_diagnostics = _shared_variable_schema_diagnostics(
        normal_classification,
        sale_classification,
        set(saved_by_name).intersection(variables),
    )
    shared_schema_mismatches = [
        str(row["name"])
        for row in shared_schema_diagnostics["declared_schema_mismatches"]
    ]
    if (
        missing
        or prohibited_new
        or required_not_captured
        or exclusion_name_mismatch
        or exclusion_classification_mismatch
        or shared_schema_mismatches
    ):
        precheck_path = (
            evidence_dir / "sale_incumbent_containment_precheck_failure.json"
        )
        precheck = {
            "status": "fail_closed",
            "failure_stage": "schema_and_structural_classification",
            "missing_saved_variables": missing,
            "prohibited_new_variables": prohibited_new,
            "required_not_captured": required_not_captured,
            "inactive_exclusion_name_mismatch": exclusion_name_mismatch,
            "inactive_exclusion_classification_mismatch": (
                exclusion_classification_mismatch
            ),
            "shared_schema_mismatches": shared_schema_mismatches,
            "shared_declared_schema_mismatch_details": (
                shared_schema_diagnostics["declared_schema_mismatches"]
            ),
            "shared_current_or_derived_bound_difference_count": (
                shared_schema_diagnostics[
                    "current_or_derived_bound_difference_count"
                ]
            ),
            "shared_current_or_derived_bound_pair_categories": (
                shared_schema_diagnostics[
                    "current_or_derived_bound_pair_categories"
                ]
            ),
            "normal_variable_classification": normal_classification,
            "sale_variable_classification": sale_classification,
            "saved_normal_solution_sha256": expected_hash,
            "provenance": saved.get("provenance", {}),
        }
        precheck_path.write_text(
            json.dumps(precheck, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        error = S44CModelBuilderError(
            "Sale-containment schema/classification mismatch: "
            f"missing={missing}, prohibited_new={prohibited_new}, "
            f"required_not_captured={required_not_captured}, "
            f"exclusion_names={exclusion_name_mismatch}, "
            f"exclusion_classification={exclusion_classification_mismatch}, "
            f"shared_schema={shared_schema_mismatches}."
        )
        error.phase2_stage = "sale_containment.schema_classification"
        error.containment_evidence_path = str(precheck_path)
        error.bound_audit = getattr(model, "grid_import_bound_audit", None)
        raise error

    before = _active_variable_records(model, allow_undefined=True)
    before_name_hash, before_schema_hash, before_fixed_hash = (
        _variable_name_and_schema_hashes(before)
    )
    before_value_hash = _variable_value_and_fixed_state_sha256(before)
    before_model_structure_hash = _model_structure_sha256(model)
    validation_model = model.clone()
    validation_variables = {
        variable.name: variable
        for variable in validation_model.component_data_objects(Var, active=True)
    }
    fixed_status_mismatches: list[str] = []
    active_objectives = list(
        validation_model.component_data_objects(Objective, active=True)
    )
    original_options = dict(getattr(solver, "options", {}))
    lp_path = evidence_dir / "sale_incumbent_containment.lp"
    pyomo_log = evidence_dir / "pyomo_sale_containment.log"
    native_log = evidence_dir / "native_sale_containment.log"
    iis_path = evidence_dir / "sale_incumbent_containment_iis.ilp"
    pyomo_status = "not_run"
    pyomo_termination = "not_run"
    native: dict[str, Any] = {"status": "not_run", "iis_created": False}
    loaded_audit: dict[str, Any] = {"feasible": False}
    loaded_value_precheck_pass = False
    constraint_audit_disposition = "not_evaluated"
    registered_validation_context: dict[str, Any] | None = None
    registered_validation_evidence: dict[str, Any] = {
        "status": "not_evaluated",
        "rows": [],
    }
    state_preservation_capture: dict[str, Any] | None = None
    failure: Exception | None = None
    failure_stage = "schema_validation"
    try:
        failure_stage = "incumbent_fixing"
        for name, row in saved_by_name.items():
            variable = validation_variables[name]
            if bool(variable.fixed) != bool(row.get("fixed")):
                fixed_status_mismatches.append(name)
            if variable.fixed:
                fixed_value = float(variable.value)
                saved_value = float(row["value"])
                if fixed_value != saved_value:
                    fixed_status_mismatches.append(name)
                variable.unfix()
            variable.set_value(float(row["value"]), skip_validation=False)
            variable.fix(float(row["value"]))
        if fixed_status_mismatches:
            raise S44CModelBuilderError(
                f"Saved/current fixed status or value mismatch: {sorted(set(fixed_status_mismatches))}."
            )
        for t in validation_model.TIME:
            validation_model.gross_grid_export_mwh[t].fix(0.0)
            required_import = float(
                value(validation_model.gross_total_electricity_mwh[t])
                - value(validation_model.total_generator_electricity_mwh[t])
            )
            if required_import < -SOLVER_NUMERICAL_TOLERANCE:
                raise S44CModelBuilderError(
                    "Captured no-export incumbent unexpectedly requires export at "
                    f"hour {t}: {required_import} MWh."
                )
            validation_model.gross_grid_import_mwh[t].fix(
                max(0.0, required_import)
            )
            validation_model.grid_import_mode[t].fix(
                1 if required_import > SOLVER_NUMERICAL_TOLERANCE else 0
            )
        failure_stage = "registered_validation_model_setup"
        for objective in active_objectives:
            objective.deactivate()
        loaded_audit = _audit_loaded_incumbent(
            validation_model,
            tolerance=SOLVER_NUMERICAL_TOLERANCE,
            structurally_inactive_exclusions=tuple(sale_exclusions),
        )
        loaded_value_precheck_pass = bool(
            loaded_audit.get("undefined_value_count") == 0
            and float(
                loaded_audit.get("max_variable_bound_violation", float("inf"))
            )
            <= SOLVER_NUMERICAL_TOLERANCE
            and float(
                loaded_audit.get("max_integrality_violation", float("inf"))
            )
            <= SOLVER_NUMERICAL_TOLERANCE
        )
        if not loaded_value_precheck_pass:
            raise S44CModelBuilderError(
                "Loaded no-export incumbent failed its exact undefined-value, "
                "variable-bound, or integrality precheck."
            )
        registered_validation_context = (
            _install_registered_validation_relaxations(validation_model)
        )
        validation_model.sale_incumbent_containment_objective = Objective(
            expr=sum(
                validation_model.sale_validation_relaxation[index]
                / float(
                    registered_validation_context["relaxation_sides"][
                        int(index)
                    ]["allowed_tolerance"]
                )
                for index in validation_model.SALE_VALIDATION_RELAXATION_SIDE
            ),
            sense=minimize,
        )
        validation_model.write(
            str(lp_path), io_options={"symbolic_solver_labels": True}
        )
        constraint_audit_disposition = (
            "registered_unit_purpose_validation_model_required"
        )
        raw_state_preservation = policy.get("state_preservation")
        if raw_state_preservation is not None:
            if not isinstance(raw_state_preservation, Mapping):
                raise S44CModelBuilderError(
                    "Sale containment state-preservation contract must be a mapping."
                )
            failure_stage = "state_preservation_target_capture"
            state_preservation_capture = (
                _capture_sale_state_preservation_targets(
                    validation_model,
                    # Targets come from the fixed validation clone; the
                    # original economic model remains byte-for-byte in state.
                    contract=raw_state_preservation,
                    saved_capture=saved,
                )
            )
        solver_name = str(getattr(solver, "name", "")).lower()
        if "gurobi" not in solver_name:
            raise S44CModelBuilderError("Governed sale containment requires Gurobi.")
        solver.options["TimeLimit"] = 300.0
        solver.options["DualReductions"] = 0
        solver.options["InfUnbdInfo"] = 1
        solver.options["FeasibilityTol"] = SOLVER_NUMERICAL_TOLERANCE
        solver.options["LogFile"] = str(pyomo_log)
        failure_stage = "pyomo_registered_validation_solve"
        result = solver.solve(validation_model, load_solutions=True)
        pyomo_status = str(result.solver.status)
        pyomo_termination = str(result.solver.termination_condition)
        failure_stage = "native_gurobi_reread"
        native = _native_gurobi_zero_objective_check(
            lp_path,
            log_path=native_log,
            iis_path=iis_path,
            tolerance=SOLVER_NUMERICAL_TOLERANCE,
        )
        if registered_validation_context is not None:
            registered_validation_evidence = (
                _finalize_registered_validation_evidence(
                    validation_model, registered_validation_context
                )
            )
    except Exception as exc:
        failure = exc
    finally:
        if hasattr(solver, "options"):
            solver.options.clear()
            solver.options.update(original_options)

    after = _active_variable_records(model, allow_undefined=True)
    after_name_hash, after_schema_hash, after_fixed_hash = (
        _variable_name_and_schema_hashes(after)
    )
    after_value_hash = _variable_value_and_fixed_state_sha256(after)
    after_model_structure_hash = _model_structure_sha256(model)
    passed = bool(
        failure is None
        and pyomo_termination.lower() == "optimal"
        and native.get("status") == "optimal"
        and loaded_value_precheck_pass
        and registered_validation_evidence.get("status") == "pass"
        and before_name_hash == after_name_hash
        and before_schema_hash == after_schema_hash
        and before_fixed_hash == after_fixed_hash
        and before_value_hash == after_value_hash
        and before_model_structure_hash == after_model_structure_hash
    )
    record = {
        "schema_version": "steel_sale_incumbent_containment_v2",
        "status": "pass" if passed else "fail_closed",
        "failure_stage": None if passed else failure_stage,
        "exception": None if failure is None else f"{type(failure).__name__}: {failure}",
        "solver_numerical_tolerance": SOLVER_NUMERICAL_TOLERANCE,
        "validation_tolerance_policy": resolved_tolerance_policy,
        "saved_normal_solution_path": _portable_repository_path(record_path),
        "saved_normal_solution_sha256": expected_hash,
        "saved_normal_variable_count": len(saved_rows),
        "sale_variable_count": len(before),
        "normal_complete_structure_sha256": saved.get(
            "complete_structure_sha256"
        ),
        "sale_complete_structure_sha256": sale_classification[
            "complete_structure_sha256"
        ],
        "normal_solver_relevant_schema_sha256": saved.get(
            "solver_relevant_schema_sha256"
        ),
        "sale_solver_relevant_schema_sha256": sale_classification[
            "solver_relevant_schema_sha256"
        ],
        "normal_inactive_exclusion_sha256": saved.get(
            "inactive_exclusion_sha256"
        ),
        "sale_inactive_exclusion_sha256": sale_classification[
            "inactive_exclusion_sha256"
        ],
        "normal_fixed_values_sha256": saved.get("fixed_values_sha256"),
        "sale_original_fixed_values_sha256": sale_classification[
            "fixed_values_sha256"
        ],
        "normal_active_incidence_sha256": saved.get(
            "active_incidence_sha256"
        ),
        "sale_active_incidence_sha256": sale_classification[
            "active_incidence_sha256"
        ],
        "normal_inactive_exclusion_count": len(normal_exclusions),
        "sale_inactive_exclusion_count": len(sale_exclusions),
        "normal_variable_classification": normal_classification,
        "sale_variable_classification": sale_classification,
        "shared_declared_schema_mismatch_count": (
            shared_schema_diagnostics["declared_schema_mismatch_count"]
        ),
        "shared_current_or_derived_bound_difference_count": (
            shared_schema_diagnostics[
                "current_or_derived_bound_difference_count"
            ]
        ),
        "shared_current_or_derived_bound_pair_categories": (
            shared_schema_diagnostics[
                "current_or_derived_bound_pair_categories"
            ]
        ),
        "new_exchange_variable_names": new_names,
        "variable_name_sha256": before_name_hash,
        "variable_schema_sha256": before_schema_hash,
        "variable_name_sha256_after": after_name_hash,
        "variable_schema_sha256_after": after_schema_hash,
        "original_model_structure_sha256_before": before_model_structure_hash,
        "original_model_structure_sha256_after": after_model_structure_hash,
        "original_model_fingerprint_unchanged": (
            before_model_structure_hash == after_model_structure_hash
            and before_name_hash == after_name_hash
            and before_schema_hash == after_schema_hash
            and before_fixed_hash == after_fixed_hash
            and before_value_hash == after_value_hash
        ),
        "fixed_state_sha256_before": before_fixed_hash,
        "fixed_state_sha256_after": after_fixed_hash,
        "value_state_sha256_before": before_value_hash,
        "value_state_sha256_after": after_value_hash,
        "fixed_status_mismatch_count": len(set(fixed_status_mismatches)),
        "loaded_incumbent_audit": loaded_audit,
        "normal_capture_post_solve_incumbent_audit": saved_capture_audit,
        "loaded_value_precheck_pass": loaded_value_precheck_pass,
        "constraint_audit_disposition": constraint_audit_disposition,
        "constraint_feasibility_authority": (
            "required_pyomo_and_native_gurobi_fixed_incumbent_registered_"
            "validation_model"
        ),
        "registered_validation_evidence": registered_validation_evidence,
        "pyomo_solver_status": pyomo_status,
        "pyomo_termination_condition": pyomo_termination,
        "native_gurobi": native,
        "lp_path": _portable_repository_path(lp_path) if lp_path.is_file() else None,
        "lp_sha256": _sha256_file(lp_path) if lp_path.is_file() else None,
        "pyomo_log_sha256": _sha256_file(pyomo_log) if pyomo_log.is_file() else None,
        "native_log_sha256": _sha256_file(native_log) if native_log.is_file() else None,
        "iis_path": _portable_repository_path(iis_path) if iis_path.is_file() else None,
        "iis_sha256": _sha256_file(iis_path) if iis_path.is_file() else None,
        "controller_state": saved.get("controller_state", {}),
        "provenance": saved.get("provenance", {}),
        "state_preservation_capture": state_preservation_capture,
    }
    record_path_out = evidence_dir / "sale_incumbent_containment.json"
    record_path_out.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not passed:
        error = S44CModelBuilderError(
            f"Sale incumbent containment failed closed during {failure_stage}: {record}."
        )
        error.phase2_stage = f"sale_containment.{failure_stage}"
        error.bound_audit = getattr(model, "grid_import_bound_audit", None)
        error.containment_evidence_path = str(record_path_out)
        raise error
    return {
        **record,
        "record_path": _portable_repository_path(record_path_out),
        "record_sha256": _sha256_file(record_path_out),
    }


def _complete_normal_feasibility_oracle(
    model: ConcreteModel,
    *,
    solver: Any,
    diagnostic: Mapping[str, Any],
    tolerance: float,
    base_model_structure_sha256: str,
) -> dict[str, Any]:
    record_path = Path(str(diagnostic["normal_solution_record_path"])).resolve()
    oracle_directory = Path(str(diagnostic["oracle_directory"])).resolve()
    oracle_directory.mkdir(parents=True, exist_ok=True)
    record_output = oracle_directory / "normal_feasibility_oracle.json"
    expected_record_hash = str(
        diagnostic["normal_solution_record_sha256"]
    )
    if _sha256_file(record_path) != expected_record_hash:
        raise S44CModelBuilderError(
            "Complete normal-solution record fingerprint mismatch."
        )
    saved = _read_gzip_json(record_path)
    expected_provenance = dict(
        diagnostic.get("normal_solution_expected_provenance", {})
    )
    actual_provenance = dict(saved.get("provenance", {}))
    if actual_provenance != expected_provenance:
        raise S44CModelBuilderError(
            "Complete normal-solution provenance fingerprint mismatch."
        )
    saved_records = list(saved.get("variables", ()))
    if saved.get("schema_version") != "steel_complete_normal_solution_v2":
        raise S44CModelBuilderError(
            "Complete normal-solution record does not use the v2 fixed-state schema."
        )
    if saved.get("model_structure_sha256") != base_model_structure_sha256:
        raise S44CModelBuilderError(
            "Endpoint base-model structure fingerprint differs from the saved "
            "normal model."
        )
    current_records = _active_variable_records(model)
    (
        current_name_hash,
        current_schema_hash,
        current_fixed_schema_hash,
    ) = _variable_name_and_schema_hashes(current_records)
    (
        saved_name_hash,
        saved_schema_hash,
        saved_fixed_schema_hash,
    ) = _variable_name_and_schema_hashes(saved_records)
    if (
        len(saved_records) != len(current_records)
        or saved.get("variable_count") != len(saved_records)
        or saved.get("variable_name_sha256") != saved_name_hash
        or saved.get("variable_schema_sha256") != saved_schema_hash
        or saved.get("variable_fixed_schema_sha256")
        != saved_fixed_schema_hash
        or saved_name_hash != current_name_hash
        or saved_schema_hash != current_schema_hash
        or [row["name"] for row in saved_records]
        != [row["name"] for row in current_records]
    ):
        raise S44CModelBuilderError(
            "Endpoint variable names/schema differ from the saved normal model."
        )

    variables = {
        variable.name: variable
        for variable in model.component_data_objects(Var, active=True)
    }
    saved_by_name = {str(row["name"]): row for row in saved_records}
    endpoint_prefixed_checked_count = 0
    max_endpoint_prefixed_value_residual = 0.0
    mismatches: list[dict[str, Any]] = []
    for current in current_records:
        name = str(current["name"])
        saved_row = saved_by_name[name]
        current_fixed = bool(current["fixed"])
        saved_fixed = bool(saved_row.get("fixed"))
        if current_fixed:
            endpoint_prefixed_checked_count += 1
        if current_fixed != saved_fixed:
            mismatches.append(
                {
                    "name": name,
                    "reason": (
                        "endpoint_fixed_saved_free"
                        if current_fixed
                        else "endpoint_free_saved_fixed"
                    ),
                    "endpoint_fixed": current_fixed,
                    "saved_fixed": saved_fixed,
                    "endpoint_fixed_value": current.get("fixed_value"),
                    "saved_fixed_value": saved_row.get("fixed_value"),
                }
            )
            continue
        if current_fixed:
            current_fixed_value = current.get("fixed_value")
            saved_fixed_value = saved_row.get("fixed_value")
            if current_fixed_value is None or saved_fixed_value is None:
                residual = float("inf")
            else:
                residual = abs(
                    float(current_fixed_value) - float(saved_fixed_value)
                )
                max_endpoint_prefixed_value_residual = max(
                    max_endpoint_prefixed_value_residual, residual
                )
            if residual > tolerance:
                mismatches.append(
                    {
                        "name": name,
                        "reason": "endpoint_fixed_value_mismatch",
                        "endpoint_fixed": True,
                        "saved_fixed": True,
                        "endpoint_fixed_value": current_fixed_value,
                        "saved_fixed_value": saved_fixed_value,
                        "absolute_residual": residual,
                        "tolerance": tolerance,
                    }
                )

    fixed_compatibility = {
        "endpoint_prefixed_checked_count": endpoint_prefixed_checked_count,
        "endpoint_prefixed_overwrite_count": 0,
        "temporarily_fixed_count": 0,
        "max_endpoint_prefixed_value_residual": (
            max_endpoint_prefixed_value_residual
        ),
        "fixed_status_or_value_mismatch_count": len(mismatches),
        "fixed_status_or_value_mismatches": mismatches,
        "endpoint_fixed_state_sha256_before": current_fixed_schema_hash,
        "endpoint_fixed_state_sha256_after": current_fixed_schema_hash,
        "endpoint_variable_state_sha256_before": (
            _variable_value_and_fixed_state_sha256(current_records)
        ),
        "endpoint_variable_state_sha256_after": (
            _variable_value_and_fixed_state_sha256(current_records)
        ),
        "saved_normal_fixed_schema_sha256": saved_fixed_schema_hash,
        "unchanged_endpoint_fixed_state": True,
    }
    if mismatches:
        mismatch_record = {
            "schema_version": "steel_normal_feasibility_oracle_v2",
            "case_id": diagnostic.get("case_id"),
            "replan_index": diagnostic.get("replan_index"),
            "configuration_id": "C0_current_BF_BOF_reference",
            "feasibility_tolerance": tolerance,
            "saved_normal_solution_path": _portable_repository_path(
                record_path
            ),
            "saved_normal_solution_sha256": expected_record_hash,
            "variable_count": len(saved_records),
            "variable_name_sha256": current_name_hash,
            "variable_schema_sha256": current_schema_hash,
            "variable_fixed_schema_sha256": saved_fixed_schema_hash,
            "endpoint_fixed_schema_sha256": current_fixed_schema_hash,
            "fixed_variable_compatibility_audit": fixed_compatibility,
            "controller_state": saved.get("controller_state", {}),
            "provenance": actual_provenance,
            "status": "fail_closed",
            "failure_stage": "pre_mutation_fixed_variable_compatibility",
        }
        record_output.write_text(
            json.dumps(mismatch_record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise S44CModelBuilderError(
            "Endpoint/saved-normal fixed-variable compatibility failed before "
            f"mutation: {fixed_compatibility}."
        )

    original_free_values: dict[str, float | None] = {}
    temporarily_fixed_names: list[str] = []
    active_objectives = list(model.component_data_objects(Objective, active=True))
    original_solver_options = dict(getattr(solver, "options", {}))
    lp_path = oracle_directory / "normal_feasibility_oracle.lp"
    pre_solve_audit: dict[str, Any] = {
        "feasible": False,
        "status": "not_run",
        "tolerance": tolerance,
    }
    pyomo_status = "not_run"
    pyomo_termination = "not_run"
    native_record: dict[str, Any] = {
        "status": "not_run",
        "status_code": None,
        "solution_count": 0,
        "iis_created": False,
        "iis_path": None,
    }
    oracle_exception: Exception | None = None
    failure_stage = "temporary_free_variable_fixing"
    try:
        for row in saved_records:
            name = str(row["name"])
            variable = variables[name]
            if variable.fixed:
                continue
            original_free_values[name] = (
                None if variable.value is None else float(variable.value)
            )
            temporarily_fixed_names.append(name)
            variable.set_value(float(row["value"]), skip_validation=False)
            variable.fix(float(row["value"]))
        fixed_compatibility["temporarily_fixed_count"] = len(
            temporarily_fixed_names
        )
        _, _, pre_solve_fixed_state_hash = _variable_name_and_schema_hashes(
            _active_variable_records(model)
        )
        fixed_compatibility["oracle_pre_solve_fixed_state_sha256"] = (
            pre_solve_fixed_state_hash
        )
        failure_stage = "zero_objective_setup"
        for objective in active_objectives:
            objective.deactivate()
        model.allocation_envelope_normal_oracle_objective = Objective(
            expr=0.0, sense=minimize
        )
        failure_stage = "pre_solve_lp_write"
        model.write(str(lp_path), io_options={"symbolic_solver_labels": True})
        failure_stage = "loaded_value_audit"
        pre_solve_audit = _audit_loaded_incumbent(model, tolerance=tolerance)
        solver_name = str(getattr(solver, "name", "")).lower()
        if "gurobi" in solver_name:
            solver.options["TimeLimit"] = 300.0
            solver.options["DualReductions"] = 0
            solver.options["InfUnbdInfo"] = 1
            solver.options["FeasibilityTol"] = tolerance
            solver.options["LogFile"] = str(
                oracle_directory / "pyomo_oracle_solver.log"
            )
        failure_stage = "pyomo_zero_objective_solve"
        pyomo_result = solver.solve(model, load_solutions=False)
        pyomo_status = str(pyomo_result.solver.status)
        pyomo_termination = str(pyomo_result.solver.termination_condition)
        failure_stage = "native_gurobi_zero_objective_reread"
        native_record = _native_gurobi_zero_objective_check(
            lp_path,
            log_path=oracle_directory / "native_oracle_solver.log",
            iis_path=oracle_directory / "normal_feasibility_oracle_iis.ilp",
            tolerance=tolerance,
        )
        failure_stage = "combined_oracle_audit"
    except Exception as exc:
        oracle_exception = exc
    finally:
        if hasattr(model, "allocation_envelope_normal_oracle_objective"):
            model.allocation_envelope_normal_oracle_objective.deactivate()
            model.del_component(
                "allocation_envelope_normal_oracle_objective"
            )
        for name in temporarily_fixed_names:
            variable = variables[name]
            variable.unfix()
            original_value = original_free_values[name]
            variable.set_value(original_value, skip_validation=False)
        for objective in active_objectives:
            objective.activate()
        if hasattr(solver, "options"):
            solver.options.clear()
            solver.options.update(original_solver_options)
    restored_records = _active_variable_records(model)
    _, _, restored_fixed_state_hash = _variable_name_and_schema_hashes(
        restored_records
    )
    fixed_compatibility["endpoint_fixed_state_sha256_after"] = (
        restored_fixed_state_hash
    )
    fixed_compatibility["unchanged_endpoint_fixed_state"] = (
        restored_fixed_state_hash == current_fixed_schema_hash
    )
    fixed_compatibility["endpoint_variable_state_sha256_after"] = (
        _variable_value_and_fixed_state_sha256(restored_records)
    )
    fixed_compatibility["unchanged_endpoint_variable_state"] = (
        fixed_compatibility["endpoint_variable_state_sha256_after"]
        == fixed_compatibility["endpoint_variable_state_sha256_before"]
    )
    pyomo_optimal = pyomo_termination.lower() == "optimal"
    native_optimal = native_record["status"] == "optimal"
    pyomo_log_path = oracle_directory / "pyomo_oracle_solver.log"
    native_log_path = oracle_directory / "native_oracle_solver.log"
    oracle_pass = bool(
        oracle_exception is None
        and
        pyomo_optimal
        and native_optimal
        and pre_solve_audit.get("feasible") is True
        and fixed_compatibility["unchanged_endpoint_fixed_state"]
        and fixed_compatibility["unchanged_endpoint_variable_state"]
        and not mismatches
        and fixed_compatibility["endpoint_prefixed_overwrite_count"] == 0
    )
    oracle_record = {
        "schema_version": "steel_normal_feasibility_oracle_v2",
        "case_id": diagnostic.get("case_id"),
        "replan_index": diagnostic.get("replan_index"),
        "configuration_id": "C0_current_BF_BOF_reference",
        "feasibility_tolerance": tolerance,
        "saved_normal_solution_path": _portable_repository_path(record_path),
        "saved_normal_solution_sha256": expected_record_hash,
        "variable_count": len(saved_records),
        "variable_name_sha256": current_name_hash,
        "variable_schema_sha256": current_schema_hash,
        "variable_fixed_schema_sha256": saved_fixed_schema_hash,
        "endpoint_fixed_schema_sha256": current_fixed_schema_hash,
        "fixed_variable_compatibility_audit": fixed_compatibility,
        "normal_base_model_structure_sha256": (
            base_model_structure_sha256
        ),
        "pre_solve_symbolic_lp": (
            _portable_repository_path(lp_path) if lp_path.is_file() else None
        ),
        "pre_solve_symbolic_lp_sha256": (
            _sha256_file(lp_path) if lp_path.is_file() else None
        ),
        "pre_solve_loaded_value_audit": pre_solve_audit,
        "pyomo_solve": {
            "solver_status": pyomo_status,
            "termination_condition": pyomo_termination,
            "optimal": pyomo_optimal,
            "FeasibilityTol": tolerance,
        },
        "native_gurobi_reread_solve": native_record,
        "solver_log_evidence": {
            "pyomo": {
                "path": (
                    _portable_repository_path(pyomo_log_path)
                    if pyomo_log_path.is_file()
                    else None
                ),
                "sha256": (
                    _sha256_file(pyomo_log_path)
                    if pyomo_log_path.is_file()
                    else None
                ),
            },
            "native_gurobi": {
                "path": (
                    _portable_repository_path(native_log_path)
                    if native_log_path.is_file()
                    else None
                ),
                "sha256": (
                    _sha256_file(native_log_path)
                    if native_log_path.is_file()
                    else None
                ),
            },
        },
        "dual_path_agreement": (
            oracle_exception is None and pyomo_optimal == native_optimal
        ),
        "controller_state": saved.get("controller_state", {}),
        "provenance": actual_provenance,
        "status": (
            "pass" if oracle_pass else "fail_closed"
        ),
        "failure_stage": (
            None if oracle_pass else failure_stage
        ),
        "exception": (
            None
            if oracle_exception is None
            else {
                "type": type(oracle_exception).__name__,
                "message": str(oracle_exception),
            }
        ),
    }
    record_output.write_text(
        json.dumps(oracle_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if oracle_exception is not None:
        raise S44CModelBuilderError(
            "Normal-feasibility oracle failed closed during "
            f"{failure_stage}: {type(oracle_exception).__name__}: "
            f"{oracle_exception}"
        ) from oracle_exception
    if not fixed_compatibility["unchanged_endpoint_fixed_state"] or not (
        fixed_compatibility["unchanged_endpoint_variable_state"]
    ):
        raise S44CModelBuilderError(
            "Normal-feasibility oracle altered the endpoint fixed-state schema."
        )
    if not (pyomo_optimal and native_optimal):
        raise S44CModelBuilderError(
            "Complete normal-feasibility oracle failed or solver paths "
            f"disagreed: pyomo={pyomo_termination}, "
            f"native={native_record['status']}."
        )
    if not pre_solve_audit.get("feasible"):
        raise S44CModelBuilderError(
            "Loaded complete normal solution violates the endpoint formulation "
            f"at tolerance {tolerance}: {pre_solve_audit}."
        )
    if not oracle_pass:
        raise S44CModelBuilderError(
            "Complete normal-feasibility oracle failed its combined v5 audit."
        )

    return {
        **oracle_record,
        "oracle_record_path": _portable_repository_path(record_output),
        "oracle_record_sha256": _sha256_file(record_output),
    }


def _in_memory_physical_upper_bound_oracle(
    model: ConcreteModel,
    *,
    diagnostic: Mapping[str, Any],
    tolerance: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Audit the already-solved capped sale incumbent used to seed the oracle."""

    raw_directory = diagnostic.get("oracle_directory") or diagnostic.get(
        "failure_evidence_directory"
    )
    if not raw_directory:
        raise S44CModelBuilderError(
            "Physical upper-bound in-memory oracle directory is missing."
        )
    directory = Path(str(raw_directory)).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    records = _active_variable_records(model)
    name_hash, schema_hash, fixed_hash = _variable_name_and_schema_hashes(records)
    audit = _audit_loaded_incumbent(model, tolerance=tolerance)
    if not audit.get("feasible"):
        raise S44CModelBuilderError(
            "The solved capped-sale incumbent is infeasible before physical maximization: "
            f"{audit}."
        )
    value_state_hash = _variable_value_and_fixed_state_sha256(records)
    fixed_compatibility = {
        "endpoint_prefixed_checked_count": sum(
            1 for row in records if bool(row["fixed"])
        ),
        "endpoint_prefixed_overwrite_count": 0,
        "temporarily_fixed_count": 0,
        "max_endpoint_prefixed_value_residual": 0.0,
        "endpoint_fixed_state_sha256_before": fixed_hash,
        "endpoint_fixed_state_sha256_after": fixed_hash,
        "unchanged_endpoint_fixed_state": True,
        "in_memory_solved_incumbent": True,
    }
    record_path = directory / "physical_upper_bound_in_memory_oracle.json"
    record = {
        "schema_version": "steel_phase5b_physical_upper_bound_oracle_v1",
        "status": "pass_in_memory_solved_incumbent",
        "variable_count": len(records),
        "variable_name_sha256": name_hash,
        "variable_schema_sha256": schema_hash,
        "variable_fixed_schema_sha256": fixed_hash,
        "saved_normal_solution_sha256": value_state_hash,
        "pre_solve_loaded_value_audit": audit,
        "fixed_variable_compatibility_audit": fixed_compatibility,
    }
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    oracle = {
        **record,
        "oracle_record_path": _portable_repository_path(record_path),
        "oracle_record_sha256": _sha256_file(record_path),
    }
    warm_start_path = directory / "endpoint_warm_start_audit.json"
    warm_start = {
        "schema_version": "steel_endpoint_warm_start_v1",
        "status": "pass_in_memory_solved_incumbent",
        "assignment_count": sum(1 for row in records if not bool(row["fixed"])),
        "assignment_variable_name_sha256": name_hash,
        "assignment_variable_schema_sha256": schema_hash,
        "assignment_value_state_sha256": value_state_hash,
        "full_start_value_state_sha256": value_state_hash,
        "source_normal_solution_sha256": value_state_hash,
        "endpoint_fixed_overwrite_count": 0,
        "loaded_start_audit": audit,
    }
    warm_start_path.write_text(
        json.dumps(warm_start, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    warm_start.update(
        {
            "audit_path": _portable_repository_path(warm_start_path),
            "audit_sha256": _sha256_file(warm_start_path),
        }
    )
    return oracle, warm_start


def _prepare_allocation_endpoint_warm_start(
    model: ConcreteModel,
    *,
    diagnostic: Mapping[str, Any],
    normal_oracle: Mapping[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    """Load only endpoint-free values from the verified v2 normal record."""

    record_path = Path(str(diagnostic["normal_solution_record_path"])).resolve()
    expected_record_hash = str(
        diagnostic["normal_solution_record_sha256"]
    )
    actual_record_hash = _sha256_file(record_path)
    if (
        actual_record_hash != expected_record_hash
        or actual_record_hash
        != normal_oracle.get("saved_normal_solution_sha256")
    ):
        raise S44CModelBuilderError(
            "Endpoint warm-start saved-normal fingerprint mismatch."
        )
    saved = _read_gzip_json(record_path)
    saved_records = list(saved.get("variables", ()))
    if saved.get("schema_version") != "steel_complete_normal_solution_v2":
        raise S44CModelBuilderError(
            "Endpoint warm start requires the saved-normal v2 schema."
        )
    current_records = _active_variable_records(model)
    (
        current_name_hash,
        current_schema_hash,
        current_fixed_schema_hash,
    ) = _variable_name_and_schema_hashes(current_records)
    (
        saved_name_hash,
        saved_schema_hash,
        saved_fixed_schema_hash,
    ) = _variable_name_and_schema_hashes(saved_records)
    if (
        len(saved_records) != len(current_records)
        or saved.get("variable_count") != len(saved_records)
        or saved.get("variable_name_sha256") != saved_name_hash
        or saved.get("variable_schema_sha256") != saved_schema_hash
        or saved.get("variable_fixed_schema_sha256")
        != saved_fixed_schema_hash
        or saved_name_hash != current_name_hash
        or saved_schema_hash != current_schema_hash
        or saved_fixed_schema_hash != current_fixed_schema_hash
        or [row["name"] for row in saved_records]
        != [row["name"] for row in current_records]
    ):
        raise S44CModelBuilderError(
            "Endpoint warm-start variable name/schema/fixed-state mismatch."
        )

    # The oracle directory is replan-specific.  Keep the warm-start proof beside
    # that oracle so a multi-window trajectory cannot overwrite earlier audits.
    raw_directory = diagnostic.get("oracle_directory") or diagnostic.get(
        "failure_evidence_directory"
    )
    if not raw_directory:
        raise S44CModelBuilderError(
            "Endpoint warm-start audit directory is missing."
        )
    audit_directory = Path(str(raw_directory)).resolve()
    audit_directory.mkdir(parents=True, exist_ok=True)
    audit_path = audit_directory / "endpoint_warm_start_audit.json"
    variables = {
        variable.name: variable
        for variable in model.component_data_objects(Var, active=True)
    }
    saved_by_name = {str(row["name"]): row for row in saved_records}
    fixed_value_mismatches: list[dict[str, Any]] = []
    assignment_names: list[str] = []
    for current in current_records:
        name = str(current["name"])
        saved_row = saved_by_name[name]
        if bool(current["fixed"]):
            current_value = float(current["fixed_value"])
            saved_value = float(saved_row["fixed_value"])
            residual = abs(current_value - saved_value)
            if not bool(saved_row["fixed"]) or residual > tolerance:
                fixed_value_mismatches.append(
                    {
                        "name": name,
                        "endpoint_fixed_value": current_value,
                        "saved_fixed": bool(saved_row["fixed"]),
                        "saved_fixed_value": saved_row["fixed_value"],
                        "absolute_residual": residual,
                    }
                )
            continue
        if bool(saved_row["fixed"]):
            fixed_value_mismatches.append(
                {
                    "name": name,
                    "endpoint_fixed_value": None,
                    "saved_fixed": True,
                    "saved_fixed_value": saved_row["fixed_value"],
                    "absolute_residual": None,
                }
            )
            continue
        assignment_names.append(name)

    if fixed_value_mismatches:
        failure = {
            "schema_version": "steel_endpoint_warm_start_v1",
            "status": "fail_closed",
            "failure_stage": "fixed_variable_compatibility",
            "source_normal_solution_sha256": actual_record_hash,
            "fixed_status_or_value_mismatch_count": len(
                fixed_value_mismatches
            ),
            "fixed_status_or_value_mismatches": fixed_value_mismatches,
        }
        audit_path.write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise S44CModelBuilderError(
            "Endpoint warm-start fixed-variable compatibility failed before "
            "value loading."
        )

    fixed_state_hash_before = current_fixed_schema_hash
    for name in assignment_names:
        variables[name].set_value(
            float(saved_by_name[name]["value"]), skip_validation=False
        )
    loaded_records = _active_variable_records(model)
    _, _, fixed_state_hash_after = _variable_name_and_schema_hashes(
        loaded_records
    )
    assignment_record_names = set(assignment_names)
    assignment_records = [
        row
        for row in loaded_records
        if str(row["name"]) in assignment_record_names
    ]
    assignment_name_hash, assignment_schema_hash, _ = (
        _variable_name_and_schema_hashes(assignment_records)
    )
    loaded_audit = _audit_loaded_incumbent(model, tolerance=tolerance)
    fixed_state_unchanged = (
        fixed_state_hash_after == fixed_state_hash_before
    )
    status = (
        "pass"
        if loaded_audit["feasible"] and fixed_state_unchanged
        else "fail_closed"
    )
    warm_start_record = {
        "schema_version": "steel_endpoint_warm_start_v1",
        "case_id": diagnostic.get("case_id"),
        "replan_index": diagnostic.get("replan_index"),
        "status": status,
        "failure_stage": (
            None if status == "pass" else "loaded_start_feasibility_audit"
        ),
        "feasibility_tolerance": tolerance,
        "source_normal_solution_path": _portable_repository_path(record_path),
        "source_normal_solution_sha256": actual_record_hash,
        "source_variable_count": len(saved_records),
        "source_variable_name_sha256": saved_name_hash,
        "source_variable_schema_sha256": saved_schema_hash,
        "source_variable_fixed_schema_sha256": saved_fixed_schema_hash,
        "assignment_count": len(assignment_records),
        "assignment_variable_name_sha256": assignment_name_hash,
        "assignment_variable_schema_sha256": assignment_schema_hash,
        "assignment_value_state_sha256": (
            _variable_value_and_fixed_state_sha256(assignment_records)
        ),
        "full_start_value_state_sha256": (
            _variable_value_and_fixed_state_sha256(loaded_records)
        ),
        "endpoint_fixed_count": len(saved_records) - len(assignment_records),
        "endpoint_fixed_overwrite_count": 0,
        "endpoint_fixed_state_sha256_before": fixed_state_hash_before,
        "endpoint_fixed_state_sha256_after": fixed_state_hash_after,
        "endpoint_fixed_state_unchanged": fixed_state_unchanged,
        "loaded_start_audit": loaded_audit,
    }
    audit_path.write_text(
        json.dumps(warm_start_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    warm_start_record["audit_path"] = _portable_repository_path(audit_path)
    warm_start_record["audit_sha256"] = _sha256_file(audit_path)
    if status != "pass":
        raise S44CModelBuilderError(
            "Endpoint warm-start values failed the governed feasibility audit: "
            f"{loaded_audit}."
        )
    return warm_start_record


def _allocation_endpoint_objective_bound_audit(
    result: Any,
    *,
    endpoint: str,
    incumbent_mwh: float,
    absolute_gap_limit_mwh: float = ALLOCATION_ENDPOINT_ABSOLUTE_MIP_GAP_MWH,
    comparison_epsilon_mwh: float = (
        ALLOCATION_ENDPOINT_BOUND_COMPARISON_EPSILON_MWH
    ),
) -> dict[str, Any]:
    """Audit the endpoint incumbent against the sense-correct solver bound."""

    bound_attribute = "lower_bound" if endpoint == "min" else "upper_bound"
    record: dict[str, Any] = {
        "schema_version": ALLOCATION_ENDPOINT_ACCURACY_SCHEMA,
        "status": "fail",
        "endpoint": endpoint,
        "incumbent_mwh": float(incumbent_mwh),
        "best_bound_attribute": bound_attribute,
        "best_bound_availability": "unavailable",
        "best_bound_mwh": None,
        "absolute_objective_bound_gap_mwh": None,
        "absolute_gap_limit_mwh": float(absolute_gap_limit_mwh),
        "comparison_epsilon_mwh": float(comparison_epsilon_mwh),
        "sense_consistency_status": "not_checked",
        "failure_reason": None,
    }
    if endpoint not in {"min", "max"}:
        record["failure_reason"] = "invalid_endpoint_sense"
        return record
    raw_bound = getattr(getattr(result, "problem", None), bound_attribute, None)
    try:
        best_bound = float(raw_bound)
    except (TypeError, ValueError):
        record["failure_reason"] = "missing_or_non_numeric_best_bound"
        return record
    if not math.isfinite(best_bound):
        record["failure_reason"] = "nonfinite_best_bound"
        return record
    record["best_bound_availability"] = "available"
    record["best_bound_mwh"] = best_bound
    sense_consistent = (
        best_bound <= incumbent_mwh + comparison_epsilon_mwh
        if endpoint == "min"
        else best_bound >= incumbent_mwh - comparison_epsilon_mwh
    )
    record["sense_consistency_status"] = (
        "pass" if sense_consistent else "fail"
    )
    absolute_gap = abs(float(incumbent_mwh) - best_bound)
    record["absolute_objective_bound_gap_mwh"] = absolute_gap
    if not sense_consistent:
        record["failure_reason"] = "sense_inconsistent_best_bound"
        return record
    if absolute_gap > absolute_gap_limit_mwh + comparison_epsilon_mwh:
        record["failure_reason"] = "absolute_objective_bound_gap_exceeds_limit"
        return record
    record["status"] = "pass"
    return record


def _install_sale_breakthrough_test(
    model: ConcreteModel,
    policy: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Install Phase-5B comparator-resource caps without changing physics."""

    if policy is None:
        return None
    mode = str(policy.get("mode", ""))
    if mode not in _SALE_BREAKTHROUGH_MODES:
        raise S44CModelBuilderError(
            f"Unsupported Phase-5B breakthrough-test mode: {mode!r}."
        )
    execution_hours = int(policy.get("execution_hours", 0))
    if execution_hours <= 0 or execution_hours > len(model.TIME):
        raise S44CModelBuilderError(
            "Phase-5B breakthrough execution hours are outside model.TIME."
        )
    reference = policy.get("reference_metrics")
    if not isinstance(reference, Mapping):
        raise S44CModelBuilderError(
            "Phase-5B breakthrough test requires comparator reference metrics."
        )
    required = {
        "gross_grid_import_mwh",
        "named_ng_mwh_lhv",
        "wag_generator_electricity_mwh",
    }
    if set(reference) != required:
        raise S44CModelBuilderError(
            "Phase-5B breakthrough comparator metric schema changed."
        )
    targets = {key: float(reference[key]) for key in sorted(required)}
    if any(not math.isfinite(item) or item < 0.0 for item in targets.values()):
        raise S44CModelBuilderError(
            "Phase-5B breakthrough comparator metrics must be finite and nonnegative."
        )
    for attribute in ("gross_grid_import_mwh", "wag_generator_electricity_mwh"):
        if not hasattr(model, attribute):
            raise S44CModelBuilderError(
                f"Phase-5B breakthrough model component is missing: {attribute}."
            )
    missing_ng = [
        attribute
        for attribute in _SALE_BREAKTHROUGH_NG_COMPONENTS
        if not hasattr(model, attribute)
    ]
    if missing_ng:
        raise S44CModelBuilderError(
            f"Phase-5B breakthrough named-NG components are missing: {missing_ng}."
        )
    import_expression = sum(
        model.gross_grid_import_mwh[t] for t in range(execution_hours)
    )
    named_ng_expression = sum(
        getattr(model, attribute)[t]
        for attribute in _SALE_BREAKTHROUGH_NG_COMPONENTS
        for t in range(execution_hours)
    )
    wag_expression = sum(
        model.wag_generator_electricity_mwh[t]
        for t in range(execution_hours)
    )
    model.phase5b_breakthrough_gross_import_cap = Constraint(
        expr=import_expression <= targets["gross_grid_import_mwh"]
    )
    model.phase5b_breakthrough_named_ng_cap = Constraint(
        expr=named_ng_expression <= targets["named_ng_mwh_lhv"]
    )
    return {
        "schema_version": "steel_phase5b_breakthrough_resource_caps_v1",
        "mode": mode,
        "execution_hours": execution_hours,
        "targets": targets,
        "expressions": {
            "gross_grid_import_mwh": import_expression,
            "named_ng_mwh_lhv": named_ng_expression,
            "wag_generator_electricity_mwh": wag_expression,
        },
    }


def _sale_breakthrough_test_record(
    context: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if context is None:
        return None
    targets = dict(context["targets"])
    actual = {
        key: float(value(expression))
        for key, expression in context["expressions"].items()
    }
    residuals = {
        "gross_grid_import_mwh": (
            actual["gross_grid_import_mwh"] - targets["gross_grid_import_mwh"]
        ),
        "named_ng_mwh_lhv": (
            actual["named_ng_mwh_lhv"] - targets["named_ng_mwh_lhv"]
        ),
        "wag_generator_electricity_mwh": (
            actual["wag_generator_electricity_mwh"]
            - targets["wag_generator_electricity_mwh"]
        ),
    }
    return {
        "schema_version": context["schema_version"],
        "mode": context["mode"],
        "execution_hours": context["execution_hours"],
        "reference_metrics": targets,
        "actual_metrics": actual,
        "residuals": residuals,
        "resource_caps_status": (
            "pass"
            if residuals["gross_grid_import_mwh"] <= 1e-6
            and residuals["named_ng_mwh_lhv"] <= 1e-6
            else "fail"
        ),
    }


def _preserve_allocation_endpoint_failure(
    model: ConcreteModel,
    result: Any,
    diagnostic: Mapping[str, Any],
    *,
    endpoint: str,
    normal_snapshot: Mapping[str, float],
    primary_cost: float,
    primary_best_bound: float | None,
    normal_cost: float,
    cost_tolerance: float,
    normal_oracle: Mapping[str, Any],
    warm_start_audit: Mapping[str, Any],
    deactivated_deadline_name: str,
    endpoint_pre_solve_model_path: Path | None,
    endpoint_pre_solve_model_sha256: str | None,
    endpoint_solver_log_path: Path | None,
    endpoint_objective_bound_audit: Mapping[str, Any] | None = None,
) -> None:
    """Persist the first endpoint failure without performing another solve."""

    raw_directory = diagnostic.get("failure_evidence_directory")
    if not raw_directory:
        return
    directory = Path(str(raw_directory)).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stats = collect_model_stats(model)
    controller_state = dict(normal_oracle.get("controller_state", {}))
    provenance = dict(normal_oracle.get("provenance", {}))
    authoritative_schedule = dict(
        controller_state.get("authoritative_schedule_row", {})
    )
    endpoint_log_hash = (
        _sha256_file(endpoint_solver_log_path)
        if endpoint_solver_log_path is not None
        and endpoint_solver_log_path.is_file()
        else None
    )
    saved_normal_source = Path(
        str(diagnostic["normal_solution_record_path"])
    ).resolve()
    bundled_normal_path = directory / "saved_normal_solution.json.gz"
    shutil.copy2(saved_normal_source, bundled_normal_path)
    bundled_normal_hash = _sha256_file(bundled_normal_path)
    record = {
        "case_id": diagnostic.get("case_id"),
        "replan_index": diagnostic.get("replan_index"),
        "solver_stage": "allocation_envelope_endpoint",
        "endpoint": endpoint,
        "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "objective_value": (
            float(value(model.allocation_envelope_objective))
            if str(result.solver.termination_condition).lower()
            in {"optimal", "feasible"}
            else None
        ),
        "solver_best_bound": (
            endpoint_objective_bound_audit.get("best_bound_mwh")
            if endpoint_objective_bound_audit is not None
            else getattr(
                result.problem,
                "lower_bound" if endpoint == "min" else "upper_bound",
                None,
            )
        ),
        "endpoint_objective_bound_audit": (
            dict(endpoint_objective_bound_audit)
            if endpoint_objective_bound_audit is not None
            else None
        ),
        "primary_cost_objective_eur": primary_cost,
        "primary_cost_best_bound_eur": primary_best_bound,
        "cost_cap_rhs_eur": primary_cost + cost_tolerance,
        "governed_cost_tolerance_eur": cost_tolerance,
        "loaded_normal_cost_eur": normal_cost,
        "loaded_normal_cost_minus_cap_rhs_eur": (
            normal_cost - primary_cost - cost_tolerance
        ),
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "normal_snapshot": dict(normal_snapshot),
        "normal_feasibility_oracle": {
            "path": normal_oracle.get("oracle_record_path"),
            "sha256": normal_oracle.get("oracle_record_sha256"),
            "status": normal_oracle.get("status"),
            "saved_normal_solution_path": normal_oracle.get(
                "saved_normal_solution_path"
            ),
            "saved_normal_solution_sha256": normal_oracle.get(
                "saved_normal_solution_sha256"
            ),
            "variable_count": normal_oracle.get("variable_count"),
            "variable_name_sha256": normal_oracle.get(
                "variable_name_sha256"
            ),
            "variable_schema_sha256": normal_oracle.get(
                "variable_schema_sha256"
            ),
            "variable_fixed_schema_sha256": normal_oracle.get(
                "variable_fixed_schema_sha256"
            ),
            "fixed_variable_compatibility_audit": normal_oracle.get(
                "fixed_variable_compatibility_audit"
            ),
            "loaded_value_audit": normal_oracle.get(
                "pre_solve_loaded_value_audit"
            ),
            "pre_solve_symbolic_lp": normal_oracle.get(
                "pre_solve_symbolic_lp"
            ),
            "pre_solve_symbolic_lp_sha256": normal_oracle.get(
                "pre_solve_symbolic_lp_sha256"
            ),
            "solver_log_evidence": normal_oracle.get(
                "solver_log_evidence"
            ),
        },
        "endpoint_warm_start": dict(warm_start_audit),
        "bundled_saved_normal_solution": {
            "path": _portable_repository_path(bundled_normal_path),
            "sha256": bundled_normal_hash,
            "source_sha256": normal_oracle.get(
                "saved_normal_solution_sha256"
            ),
            "hash_matches_source": (
                bundled_normal_hash
                == normal_oracle.get("saved_normal_solution_sha256")
            ),
        },
        "normal_controller_schedule_sha256": provenance.get(
            "normal_controller_schedule_sha256"
        ),
        "controller_schedule_row_sha256": provenance.get(
            "controller_schedule_row_sha256"
        ),
        "controller_state": controller_state,
        "authoritative_schedule_row": authoritative_schedule,
        "start_state": authoritative_schedule.get(
            "start_overrides", controller_state.get("start_overrides")
        ),
        "deactivated_constraint_row": deactivated_deadline_name,
        "endpoint_pre_solve_model": (
            _portable_repository_path(endpoint_pre_solve_model_path)
            if endpoint_pre_solve_model_path is not None
            else None
        ),
        "endpoint_pre_solve_model_sha256": (
            endpoint_pre_solve_model_sha256
        ),
        "endpoint_solver_log": (
            _portable_repository_path(endpoint_solver_log_path)
            if endpoint_solver_log_path is not None
            else None
        ),
        "endpoint_solver_log_sha256": endpoint_log_hash,
        "diagnostic_solver_options": {
            "DualReductions": 0,
            "InfUnbdInfo": 1,
            "FeasibilityTol": normal_oracle.get(
                "feasibility_tolerance"
            ),
            "MIPGap": ALLOCATION_ENDPOINT_RELATIVE_MIP_GAP,
            "MIPGapAbs": ALLOCATION_ENDPOINT_ABSOLUTE_MIP_GAP_MWH,
            "warmstart": True,
        },
        "second_solve_performed": False,
    }
    evidence_path = directory / "first_failure.json"
    evidence_path.write_text(
        json.dumps(record, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    model_path = directory / "first_failure_model.lp"
    try:
        model.write(str(model_path), io_options={"symbolic_solver_labels": True})
        if model_path.stat().st_size > 3_000_000:
            model_path.unlink()
            record["compact_model_status"] = "omitted_above_3MB_budget"
        else:
            record["compact_model_status"] = "preserved"
            record["compact_model_path"] = _portable_repository_path(
                model_path
            )
            record["compact_model_sha256"] = hashlib.sha256(
                model_path.read_bytes()
            ).hexdigest()
    except Exception as exc:  # pragma: no cover - writer support is plugin-specific
        record["compact_model_status"] = f"write_failed:{type(exc).__name__}"
    evidence_path.write_text(
        json.dumps(record, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    record_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    (directory / "first_failure.sha256").write_text(
        f"{record_hash}  first_failure.json\n", encoding="utf-8"
    )


def _solve_with_optional_lexicographic_cost(
    model: ConcreteModel,
    *,
    solver: Any,
    configuration_id: str,
    deterministic_cost_policy: Mapping[str, Any] | None,
    electricity_sale_sensitivity: Mapping[str, Any] | None = None,
    allocation_envelope_diagnostic: Mapping[str, Any] | None = None,
    normal_solution_capture: Mapping[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Solve physical progress, represented cost and tie-breaker in order."""

    progress_active = hasattr(model, "rolling_production_progress_objective")
    metadata = {
        "cost_objective_active": deterministic_cost_policy is not None,
        "primary_cost_objective_eur": None,
        "primary_import_procurement_cost_eur": None,
        "primary_electricity_export_revenue_eur": None,
        "primary_cost_best_bound_eur": None,
        "primary_cost_best_bound_availability": "not_solved",
        "primary_cost_solver_status": None,
        "primary_cost_termination_condition": None,
        "primary_cost_mip_gap": None,
        "primary_cost_runtime_seconds": 0.0,
        "production_progress_objective_active": progress_active,
        "production_progress_target_t": (
            float(model.rolling_production_progress_target_t)
            if progress_active
            else None
        ),
        "production_progress_optimum_deviation_t": None,
        "production_progress_actual_t": None,
        "production_progress_surplus_t": None,
        "production_progress_deficit_t": None,
        "production_progress_runtime_seconds": 0.0,
        "tie_break_objective_value": None,
        "tie_break_cost_objective_eur": None,
        "tie_break_runtime_seconds": 0.0,
        "priced_flow_count": 0,
        "electricity_sale_sensitivity_active": False,
        "sale_incumbent_containment": None,
        "sale_state_preservation": None,
        "sale_economic_validation_overlay": None,
        "sale_breakthrough_test": None,
    }

    cost_objective = None
    sale_preservation_context: dict[str, Any] | None = None
    sale_validation_context: dict[str, Any] | None = None
    sale_containment_policy: Mapping[str, Any] | None = None
    sale_state_contract: Mapping[str, Any] | None = None
    sale_breakthrough_context: dict[str, Any] | None = None
    flows: list[Mapping[str, Any]] = []
    sale_enabled = bool(
        electricity_sale_sensitivity
        and electricity_sale_sensitivity.get("enabled") is True
    )
    if sale_enabled and deterministic_cost_policy is None:
        raise S44CModelBuilderError(
            "The electricity-sale sensitivity requires represented deterministic cost."
        )
    if sale_enabled:
        if configuration_id != "C0_current_BF_BOF_reference":
            raise S44CModelBuilderError(
                "The electricity-sale sensitivity is available for C0 only."
            )
        containment = electricity_sale_sensitivity.get("incumbent_containment")
        if not isinstance(containment, Mapping):
            raise S44CModelBuilderError(
                "The sale sensitivity requires a complete no-export incumbent containment contract."
            )
        state_preservation = electricity_sale_sensitivity.get(
            "state_preservation"
        )
        if not isinstance(state_preservation, Mapping):
            raise S44CModelBuilderError(
                "The sale sensitivity requires the governed state-preservation contract."
            )
        normalized_state_preservation = (
            _validated_sale_state_preservation_contract(
                state_preservation, model=model
            )
        )
        try:
            resolved_runtime_tolerance_policy = resolve_policy_contract(
                containment["validation_tolerance_policy"]
            )
            matching_runtime_identity = bool(
                containment.get("state_preservation") == state_preservation
                and int(
                    electricity_sale_sensitivity.get("replan_index", -1)
                )
                == normalized_state_preservation["replan_index"]
                and int(
                    electricity_sale_sensitivity.get("execution_hours", -1)
                )
                == normalized_state_preservation["execution_hours"]
                and resolved_runtime_tolerance_policy
                == validation_tolerance_policy_contract()
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            ValidationTolerancePolicyError,
        ):
            matching_runtime_identity = False
        if not matching_runtime_identity:
            raise S44CModelBuilderError(
                "Sale state-preservation identity, horizon, or governed tolerance changed."
            )
        if not hasattr(model, "grid_import_bound_audit"):
            raise S44CModelBuilderError(
                "Sale containment requires the completed hourly FBBT bound audit."
            )
        if containment.get("oracle_directory"):
            bound_evidence_dir = Path(
                str(containment["oracle_directory"])
            ).resolve()
            bound_evidence_dir.mkdir(parents=True, exist_ok=True)
            bound_audit_path = (
                bound_evidence_dir / "grid_import_hourly_bound_audit.json"
            )
            bound_audit_path.write_text(
                json.dumps(
                    model.grid_import_bound_audit,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
            metadata["grid_import_bound_audit_path"] = (
                _portable_repository_path(bound_audit_path)
            )
            metadata["grid_import_bound_audit_sha256"] = _sha256_file(
                bound_audit_path
            )
        metadata["sale_incumbent_containment"] = (
            _sale_incumbent_containment_oracle(
                model,
                solver=solver,
                policy=containment,
                tolerance=SOLVER_NUMERICAL_TOLERANCE,
            )
        )
        sale_containment_policy = containment
        sale_state_contract = state_preservation
    if deterministic_cost_policy is not None:
        configuration = "C0" if configuration_id.startswith("C0_") else "C1"
        flows = [
            row
            for row in deterministic_cost_policy.get("flows", ())
            if row.get("configuration") in {configuration, "both"}
        ]
        if not flows:
            raise S44CModelBuilderError(
                f"No deterministic procurement flows mapped for {configuration_id}."
            )
        cost_terms = []
        for flow in flows:
            attributes = str(flow["model_component_attribute"]).split(";")
            prices = list(flow["price_eur_by_hour"])
            if len(prices) != len(model.TIME):
                raise S44CModelBuilderError(
                    f"Price horizon mismatch for {flow['flow_id']}."
                )
            for attribute in attributes:
                if not hasattr(model, attribute):
                    raise S44CModelBuilderError(
                        f"Model cost component is missing for {flow['flow_id']}: {attribute}"
                    )
                component = getattr(model, attribute)
                cost_terms.extend(
                    float(prices[int(t)]) * component[t] for t in model.TIME
                )
        if sale_enabled:
            sale_prices = list(
                electricity_sale_sensitivity.get("sale_price_eur_by_hour", ())
            )
            if len(sale_prices) != len(model.TIME):
                raise S44CModelBuilderError(
                    "The electricity-sale price horizon must match model.TIME."
                )
            if not getattr(model, "electricity_sale_sensitivity_active", False):
                raise S44CModelBuilderError(
                    "The sale objective requires the opt-in physical export boundary."
                )
            model.electricity_export_revenue_eur = Expression(
                expr=sum(
                    float(sale_prices[int(t)]) * model.gross_grid_export_mwh[t]
                    for t in model.TIME
                )
            )
            model.represented_import_procurement_cost_eur = Expression(
                expr=sum(cost_terms)
            )
            model.represented_procurement_cost_eur = Expression(
                expr=model.represented_import_procurement_cost_eur
                - model.electricity_export_revenue_eur
            )
        else:
            # Preserve the accepted absent/disabled model structure and cost
            # definition exactly.
            model.represented_procurement_cost_eur = Expression(
                expr=sum(cost_terms)
            )
        model.deterministic_procurement_cost_objective = Objective(
            expr=model.represented_procurement_cost_eur,
            sense=minimize,
        )
        cost_objective = model.deterministic_procurement_cost_objective
        cost_objective.deactivate()
        metadata["priced_flow_count"] = len(flows)
        metadata["electricity_sale_sensitivity_active"] = sale_enabled

    if sale_enabled:
        assert sale_containment_policy is not None
        assert sale_state_contract is not None
        sale_validation_context = _install_sale_economic_validation_overlay(
            model
        )
        sale_validation_context["evidence_path"] = (
            Path(str(sale_containment_policy["oracle_directory"])).resolve()
            / "sale_economic_validation_overlay.json"
        )
        metadata["sale_economic_validation_overlay"] = {
            "status": "installed_pending_economic_solve",
            "schema_version": sale_validation_context["schema_version"],
            "registered_acceptance_row_count": sale_validation_context[
                "registered_acceptance_row_count"
            ],
            "underlying_core_unchanged": True,
            "underlying_core_sha256": sale_validation_context[
                "underlying_core_sha256_before"
            ],
        }
        sale_preservation_context = _apply_sale_state_preservation(
            model,
            containment_result=metadata["sale_incumbent_containment"],
            containment_policy=sale_containment_policy,
            contract=sale_state_contract,
            tolerance=SOLVER_NUMERICAL_TOLERANCE,
        )
        pending_evidence_path = Path(
            sale_preservation_context["evidence_path"]
        )
        metadata["sale_state_preservation"] = {
            "status": "targets_applied_pending_economic_solve",
            "evidence_path": _portable_repository_path(
                pending_evidence_path
            ),
            "evidence_sha256": _sha256_file(pending_evidence_path),
            "targets_sha256": sale_preservation_context["record"][
                "targets_sha256"
            ],
            "state_schema_sha256": sale_preservation_context["record"][
                "state_schema_sha256"
            ],
            "constraint_names_sha256": sale_preservation_context["record"][
                "constraint_names_sha256"
            ],
        }
        sale_breakthrough_context = _install_sale_breakthrough_test(
            model,
            electricity_sale_sensitivity.get("breakthrough_test"),
        )
        if sale_breakthrough_context is not None:
            metadata["sale_breakthrough_test"] = {
                "schema_version": sale_breakthrough_context["schema_version"],
                "mode": sale_breakthrough_context["mode"],
                "execution_hours": sale_breakthrough_context["execution_hours"],
                "reference_metrics": dict(sale_breakthrough_context["targets"]),
                "status": "installed_pending_solve",
            }

    model.static_price_naive_objective.deactivate()
    if progress_active:
        model.rolling_production_progress_objective.activate()
        progress_start = time.perf_counter()
        progress_result = solver.solve(model)
        metadata["production_progress_runtime_seconds"] = (
            time.perf_counter() - progress_start
        )
        if str(progress_result.solver.termination_condition).lower() not in {
            "optimal",
            "feasible",
        }:
            if sale_preservation_context is not None:
                metadata["sale_state_preservation"] = (
                    _finalize_sale_state_preservation(
                        model,
                        context=sale_preservation_context,
                        termination_condition=str(
                            progress_result.solver.termination_condition
                        ),
                        tolerance=TERMINAL_STATE_TOLERANCE_T,
                    )
                )
            if sale_validation_context is not None:
                metadata["sale_economic_validation_overlay"] = (
                    _finalize_sale_economic_validation_overlay(
                        model, sale_validation_context
                    )
                )
            return progress_result, metadata
        progress_optimum = float(
            value(model.rolling_production_progress_deviation_t)
        )
        metadata["production_progress_optimum_deviation_t"] = progress_optimum
        model.rolling_production_progress_objective.deactivate()
        model.rolling_production_progress_optimum_preservation = Constraint(
            expr=model.rolling_production_progress_deviation_t
            <= progress_optimum + 1e-6
        )

    if cost_objective is not None:
        cost_objective.activate()
        primary_start = time.perf_counter()
        primary_result = solver.solve(model)
        metadata["primary_cost_runtime_seconds"] = time.perf_counter() - primary_start
        metadata["primary_cost_mip_gap"] = _mip_gap(primary_result)
        primary_termination = str(primary_result.solver.termination_condition)
        metadata["primary_cost_solver_status"] = str(primary_result.solver.status)
        metadata["primary_cost_termination_condition"] = primary_termination
        if (
            allocation_envelope_diagnostic is not None
            and primary_termination.lower() != "optimal"
        ):
            raise S44CModelBuilderError(
                "The allocation-envelope primary procurement-cost stage must "
                f"terminate optimal; received {primary_termination}."
            )
        if primary_termination.lower() not in {
            "optimal",
            "feasible",
        }:
            if sale_preservation_context is not None:
                metadata["sale_state_preservation"] = (
                    _finalize_sale_state_preservation(
                        model,
                        context=sale_preservation_context,
                        termination_condition=primary_termination,
                        tolerance=TERMINAL_STATE_TOLERANCE_T,
                    )
                )
            if sale_validation_context is not None:
                metadata["sale_economic_validation_overlay"] = (
                    _finalize_sale_economic_validation_overlay(
                        model, sale_validation_context
                    )
                )
            return primary_result, metadata
        optimum = float(value(model.represented_procurement_cost_eur))
        tolerance = float(deterministic_cost_policy["objective_tolerance_eur"])
        if tolerance < 0.0:
            raise S44CModelBuilderError("Cost-objective tolerance cannot be negative.")
        metadata["primary_cost_objective_eur"] = optimum
        if sale_enabled:
            metadata["primary_import_procurement_cost_eur"] = float(
                value(model.represented_import_procurement_cost_eur)
            )
            metadata["primary_electricity_export_revenue_eur"] = float(
                value(model.electricity_export_revenue_eur)
            )
        try:
            primary_best_bound = float(primary_result.problem.lower_bound)
            if not math.isfinite(primary_best_bound):
                raise ValueError("non-finite primary best bound")
        except (AttributeError, TypeError, ValueError):
            metadata["primary_cost_best_bound_eur"] = None
            metadata["primary_cost_best_bound_availability"] = "unavailable"
        else:
            metadata["primary_cost_best_bound_eur"] = primary_best_bound
            metadata["primary_cost_best_bound_availability"] = "available"
        cost_objective.deactivate()
        model.procurement_cost_optimum_preservation = Constraint(
            expr=model.represented_procurement_cost_eur <= optimum + tolerance
        )

    model.static_price_naive_objective.activate()
    tie_start = time.perf_counter()
    tie_result = solver.solve(model)
    metadata["tie_break_runtime_seconds"] = time.perf_counter() - tie_start
    tie_termination = str(tie_result.solver.termination_condition)
    if tie_termination.lower() in {
        "optimal",
        "feasible",
    }:
        metadata["tie_break_objective_value"] = float(
            value(model.static_price_naive_objective)
        )
        if cost_objective is not None:
            metadata["tie_break_cost_objective_eur"] = float(
                value(model.represented_procurement_cost_eur)
            )
        if progress_active:
            execution_hours = int(model.rolling_production_progress_execution_hours)
            metadata["production_progress_actual_t"] = sum(
                float(value(model.final_product_output[t]))
                for t in range(execution_hours)
            )
            metadata["production_progress_surplus_t"] = float(
                value(model.rolling_production_progress_surplus_t)
            )
            metadata["production_progress_deficit_t"] = float(
                value(model.rolling_production_progress_deficit_t)
            )
    if sale_preservation_context is not None:
        finalized_state_preservation = _finalize_sale_state_preservation(
            model,
            context=sale_preservation_context,
            termination_condition=tie_termination,
            tolerance=TERMINAL_STATE_TOLERANCE_T,
        )
        metadata["sale_state_preservation"] = finalized_state_preservation
        if finalized_state_preservation["status"] != "pass":
            error = S44CModelBuilderError(
                "Sale economic solve failed the governed terminal-state "
                "preservation audit."
            )
            error.phase2_stage = "sale_state_preservation.final_audit"
            error.state_preservation_evidence_path = (
                finalized_state_preservation["evidence_path"]
            )
            raise error
    if sale_validation_context is not None:
        finalized_validation_overlay = (
            _finalize_sale_economic_validation_overlay(
                model, sale_validation_context
            )
        )
        metadata["sale_economic_validation_overlay"] = (
            finalized_validation_overlay
        )
        if finalized_validation_overlay["status"] != "pass":
            error = S44CModelBuilderError(
                "Sale economic solve failed the registered validation-row "
                "acceptance audit."
            )
            error.phase2_stage = (
                "sale_economic.validation_overlay_final_audit"
            )
            raise error
    if sale_breakthrough_context is not None:
        metadata["sale_breakthrough_test"] = _sale_breakthrough_test_record(
            sale_breakthrough_context
        )
        if metadata["sale_breakthrough_test"]["resource_caps_status"] != "pass":
            raise S44CModelBuilderError(
                "Phase-5B breakthrough resource-cap audit failed."
            )
    if normal_solution_capture is not None:
        metadata.update(
            _capture_complete_normal_solution(
                model,
                metadata=metadata,
                solver=solver,
                configuration_id=configuration_id,
                policy=normal_solution_capture,
            )
        )
    if allocation_envelope_diagnostic is None:
        return tie_result, metadata

    if configuration_id != "C0_current_BF_BOF_reference":
        raise S44CModelBuilderError(
            "The allocation-envelope diagnostic is available for C0 only."
        )
    if cost_objective is None or metadata["primary_cost_objective_eur"] is None:
        raise S44CModelBuilderError(
            "The allocation-envelope diagnostic requires the represented procurement-cost objective."
        )
    if str(tie_result.solver.termination_condition).lower() != "optimal":
        raise S44CModelBuilderError(
            "The normal physical tie-break must be optimal before an allocation endpoint is solved."
        )
    endpoint = str(allocation_envelope_diagnostic.get("endpoint", ""))
    if endpoint not in {"min", "max"}:
        raise S44CModelBuilderError(
            "Allocation-envelope endpoint must be exactly 'min' or 'max'."
        )
    breakthrough_mode = str(
        allocation_envelope_diagnostic.get("breakthrough_mode", "")
    )
    physical_wag_upper_bound = (
        breakthrough_mode == "phase5b_physical_wag_upper_bound_v1"
    )
    if breakthrough_mode and breakthrough_mode not in _SALE_BREAKTHROUGH_MODES:
        raise S44CModelBuilderError(
            f"Unsupported allocation-envelope breakthrough mode: {breakthrough_mode!r}."
        )
    if physical_wag_upper_bound and (
        sale_breakthrough_context is None
        or sale_breakthrough_context["mode"] != breakthrough_mode
        or endpoint != "max"
    ):
        raise S44CModelBuilderError(
            "The Phase-5B physical WAG upper bound requires matching sale resource caps and endpoint=max."
        )
    execution_hours = int(
        allocation_envelope_diagnostic.get(
            "execution_hours",
            getattr(model, "rolling_production_progress_execution_hours", 0),
        )
    )
    state_tolerance = float(
        allocation_envelope_diagnostic.get("state_tolerance", 1e-6)
    )
    endpoint_accuracy_schema = allocation_envelope_diagnostic.get(
        "endpoint_solver_accuracy_schema", ALLOCATION_ENDPOINT_ACCURACY_SCHEMA
    )
    endpoint_relative_mip_gap = float(
        allocation_envelope_diagnostic.get(
            "endpoint_relative_mip_gap", ALLOCATION_ENDPOINT_RELATIVE_MIP_GAP
        )
    )
    endpoint_absolute_mip_gap_mwh = float(
        allocation_envelope_diagnostic.get(
            "endpoint_absolute_mip_gap_mwh",
            ALLOCATION_ENDPOINT_ABSOLUTE_MIP_GAP_MWH,
        )
    )
    endpoint_bound_comparison_epsilon_mwh = float(
        allocation_envelope_diagnostic.get(
            "endpoint_bound_comparison_epsilon_mwh",
            ALLOCATION_ENDPOINT_BOUND_COMPARISON_EPSILON_MWH,
        )
    )
    if (
        execution_hours <= 0
        or execution_hours > len(model.TIME)
        or state_tolerance != 1e-6
    ):
        raise S44CModelBuilderError(
            "Allocation-envelope execution hours are invalid or the governed "
            "absolute feasibility tolerance is not exactly 1e-6."
        )
    if (
        endpoint_accuracy_schema != ALLOCATION_ENDPOINT_ACCURACY_SCHEMA
        or endpoint_relative_mip_gap != ALLOCATION_ENDPOINT_RELATIVE_MIP_GAP
        or endpoint_absolute_mip_gap_mwh
        != ALLOCATION_ENDPOINT_ABSOLUTE_MIP_GAP_MWH
        or endpoint_bound_comparison_epsilon_mwh
        != ALLOCATION_ENDPOINT_BOUND_COMPARISON_EPSILON_MWH
    ):
        raise S44CModelBuilderError(
            "Allocation-envelope endpoint solver-accuracy contract changed."
        )
    for attribute in (
        "wag_generator_electricity_mwh",
        "final_product_output",
        "coke_inventory",
        "sinter_inventory",
        "hot_iron_inventory",
        "cold_slab_inventory",
    ):
        if not hasattr(model, attribute):
            raise S44CModelBuilderError(
                f"Allocation-envelope model component is missing: {attribute}"
            )

    handoff_hour = execution_hours - 1
    local_normal_snapshot = {
        "executed_final_product_t": sum(
            float(value(model.final_product_output[t]))
            for t in range(execution_hours)
        ),
        "coke_inventory_t": float(value(model.coke_inventory[handoff_hour])),
        "sinter_inventory_t": float(value(model.sinter_inventory[handoff_hour])),
        "hot_iron_inventory_t": float(
            value(model.hot_iron_inventory[handoff_hour])
        ),
        "cold_slab_inventory_t": float(
            value(model.cold_slab_inventory[handoff_hour])
        ),
    }
    supplied_normal_snapshot = allocation_envelope_diagnostic.get(
        "normal_snapshot"
    )
    if supplied_normal_snapshot is not None:
        if not isinstance(supplied_normal_snapshot, Mapping):
            raise S44CModelBuilderError(
                "Allocation-envelope normal snapshot must be a mapping."
            )
        normal_snapshot = {
            key: float(supplied_normal_snapshot[key])
            for key in local_normal_snapshot
        }
        max_local_normal_schedule_residual = max(
            abs(local_normal_snapshot[key] - normal_snapshot[key])
            for key in normal_snapshot
        )
        if max_local_normal_schedule_residual > state_tolerance:
            raise S44CModelBuilderError(
                "Current hook-absent normal schedule does not reproduce in the "
                "endpoint formulation: "
                f"max_residual={max_local_normal_schedule_residual}."
            )
    else:
        normal_snapshot = dict(local_normal_snapshot)
        max_local_normal_schedule_residual = 0.0
    primary_cost = float(metadata["primary_cost_objective_eur"])
    cost_tolerance = float(deterministic_cost_policy["objective_tolerance_eur"])
    normal_cost = float(metadata["tie_break_cost_objective_eur"])
    local_normal_endpoint_objective_value = sum(
        float(value(model.wag_generator_electricity_mwh[t]))
        for t in range(execution_hours)
    )
    normal_endpoint_objective_value = float(
        supplied_normal_snapshot.get(
            "wag_generator_electricity_mwh",
            local_normal_endpoint_objective_value,
        )
        if supplied_normal_snapshot is not None
        else local_normal_endpoint_objective_value
    )
    normal_cost_minus_upper_limit = normal_cost - (
        primary_cost + cost_tolerance
    )
    if not physical_wag_upper_bound and normal_cost_minus_upper_limit > 1e-6:
        raise S44CModelBuilderError(
            "The normal tie-break incumbent is not feasible for the allocation "
            "endpoint formulations: "
            f"normal_cost_eur={normal_cost}, primary_cost_eur={primary_cost}, "
            f"upper_tolerance_eur={cost_tolerance}."
        )

    def _snapshot_hash(snapshot: Mapping[str, float]) -> str:
        normalized = {key: float(snapshot[key]) for key in sorted(snapshot)}
        return hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

    if physical_wag_upper_bound:
        if not hasattr(model, "procurement_cost_optimum_preservation"):
            raise S44CModelBuilderError(
                "The physical WAG upper bound expected the completed economic stage before removing its cost cap."
            )
        model.del_component(model.procurement_cost_optimum_preservation)
    base_model_structure_sha256 = _model_structure_sha256(model)
    model.static_price_naive_objective.deactivate()
    state_expressions = {
        "executed_final_product_t": sum(
            model.final_product_output[t] for t in range(execution_hours)
        ),
        "coke_inventory_t": model.coke_inventory[handoff_hour],
        "sinter_inventory_t": model.sinter_inventory[handoff_hour],
        "hot_iron_inventory_t": model.hot_iron_inventory[handoff_hour],
        "cold_slab_inventory_t": model.cold_slab_inventory[handoff_hour],
    }
    if hasattr(model, "dri_inventory"):
        state_expressions["dri_inventory_t"] = model.dri_inventory[handoff_hour]
        normal_snapshot["dri_inventory_t"] = float(
            supplied_normal_snapshot["dri_inventory_t"]
        )
    preservation_names = {
        "executed_final_product_t": (
            "allocation_envelope_executed_final_product_preservation"
        ),
        "coke_inventory_t": "allocation_envelope_coke_inventory_preservation",
        "sinter_inventory_t": (
            "allocation_envelope_sinter_inventory_preservation"
        ),
        "hot_iron_inventory_t": (
            "allocation_envelope_hot_iron_inventory_preservation"
        ),
        "cold_slab_inventory_t": (
            "allocation_envelope_cold_slab_inventory_preservation"
        ),
        "dri_inventory_t": "allocation_envelope_dri_inventory_preservation",
    }
    for key, expression in state_expressions.items():
        setattr(
            model,
            preservation_names[key],
            Constraint(expr=expression == normal_snapshot[key]),
        )
    deadline = getattr(model, "rolling_production_deadline", None)
    if deadline is None or execution_hours not in deadline:
        raise S44CModelBuilderError(
            "The IIS-proven executed-hours rolling deadline row is absent."
        )
    deadline_row = deadline[execution_hours]
    if not deadline_row.active and not physical_wag_upper_bound:
        raise S44CModelBuilderError(
            "The IIS-proven executed-hours rolling deadline row was already inactive."
        )
    if deadline_row.active:
        deadline_row.deactivate()
        deactivated_deadline_name = deadline_row.name
    else:
        deactivated_deadline_name = (
            f"{deadline_row.name}:already_replaced_by_governed_sale_validation_overlay"
        )
    if hasattr(model, "rolling_production_progress_identity"):
        if not model.rolling_production_progress_identity.active:
            raise S44CModelBuilderError(
                "Rolling production progress identity must remain active."
            )
    if hasattr(model, "rolling_production_progress_optimum_preservation"):
        if not model.rolling_production_progress_optimum_preservation.active:
            raise S44CModelBuilderError(
                "Rolling production progress optimum preservation must remain active."
            )
    endpoint_expression = sum(
        model.wag_generator_electricity_mwh[t]
        for t in range(execution_hours)
    )
    model.allocation_envelope_objective = Objective(
        expr=endpoint_expression,
        sense=minimize if endpoint == "min" else maximize,
    )
    model.allocation_envelope_objective.deactivate()
    in_memory_endpoint_warm_start: dict[str, Any] | None = None
    if physical_wag_upper_bound:
        normal_oracle, in_memory_endpoint_warm_start = (
            _in_memory_physical_upper_bound_oracle(
                model,
                diagnostic=allocation_envelope_diagnostic,
                tolerance=state_tolerance,
            )
        )
    else:
        normal_oracle = _complete_normal_feasibility_oracle(
            model,
            solver=solver,
            diagnostic=allocation_envelope_diagnostic,
            tolerance=state_tolerance,
            base_model_structure_sha256=base_model_structure_sha256,
        )
    normal_incumbent_audit = dict(
        normal_oracle["pre_solve_loaded_value_audit"]
    )
    objective_definition_valid = (
        model.allocation_envelope_objective.expr is endpoint_expression
        and model.allocation_envelope_objective.sense
        == (minimize if endpoint == "min" else maximize)
        and execution_hours
        == int(allocation_envelope_diagnostic["execution_hours"])
    )
    normal_incumbent_audit["cost_cap_present"] = hasattr(
        model, "procurement_cost_optimum_preservation"
    )
    normal_incumbent_audit["cost_cap_requirement"] = (
        "not_applicable_physical_upper_bound"
        if physical_wag_upper_bound
        else "required"
    )
    normal_incumbent_audit["production_and_state_preservation_present"] = (
        all(
            hasattr(model, preservation_names[key])
            for key in state_expressions
        )
    )
    normal_incumbent_audit["single_absolute_tolerance"] = state_tolerance
    normal_incumbent_audit["deactivated_deadline_row"] = (
        deactivated_deadline_name
    )
    normal_incumbent_audit["objective_definition_valid"] = (
        objective_definition_valid
    )
    normal_incumbent_audit["feasible"] = bool(
        normal_incumbent_audit["feasible"]
        and (
            physical_wag_upper_bound
            or normal_incumbent_audit["cost_cap_present"]
        )
        and normal_incumbent_audit["production_and_state_preservation_present"]
        and objective_definition_valid
    )
    if not normal_incumbent_audit["feasible"]:
        raise S44CModelBuilderError(
            "The complete saved-normal incumbent feasibility audit failed: "
            f"{normal_incumbent_audit}."
        )
    metadata.update(
        {
            "allocation_envelope_active": True,
            "allocation_envelope_endpoint": endpoint,
            "allocation_envelope_execution_hours": execution_hours,
            "allocation_envelope_normal_feasibility_oracle_status": (
                normal_oracle["status"]
            ),
            "allocation_envelope_normal_feasibility_oracle_record_path": (
                normal_oracle["oracle_record_path"]
            ),
            "allocation_envelope_normal_feasibility_oracle_record_sha256": (
                normal_oracle["oracle_record_sha256"]
            ),
            "allocation_envelope_normal_solution_variable_count": (
                normal_oracle["variable_count"]
            ),
            "allocation_envelope_normal_solution_variable_name_sha256": (
                normal_oracle["variable_name_sha256"]
            ),
            "allocation_envelope_normal_solution_variable_schema_sha256": (
                normal_oracle["variable_schema_sha256"]
            ),
            "allocation_envelope_normal_solution_variable_fixed_schema_sha256": (
                normal_oracle["variable_fixed_schema_sha256"]
            ),
            "allocation_envelope_normal_solution_record_sha256": (
                normal_oracle["saved_normal_solution_sha256"]
            ),
            "allocation_envelope_endpoint_prefixed_checked_count": (
                normal_oracle["fixed_variable_compatibility_audit"][
                    "endpoint_prefixed_checked_count"
                ]
            ),
            "allocation_envelope_oracle_temporarily_fixed_count": (
                normal_oracle["fixed_variable_compatibility_audit"][
                    "temporarily_fixed_count"
                ]
            ),
            "allocation_envelope_endpoint_prefixed_overwrite_count": (
                normal_oracle["fixed_variable_compatibility_audit"][
                    "endpoint_prefixed_overwrite_count"
                ]
            ),
            "allocation_envelope_endpoint_prefixed_max_value_residual": (
                normal_oracle["fixed_variable_compatibility_audit"][
                    "max_endpoint_prefixed_value_residual"
                ]
            ),
            "allocation_envelope_endpoint_fixed_state_sha256_before": (
                normal_oracle["fixed_variable_compatibility_audit"][
                    "endpoint_fixed_state_sha256_before"
                ]
            ),
            "allocation_envelope_endpoint_fixed_state_sha256_after": (
                normal_oracle["fixed_variable_compatibility_audit"][
                    "endpoint_fixed_state_sha256_after"
                ]
            ),
            "allocation_envelope_deactivated_deadline_row": (
                deactivated_deadline_name
            ),
            "allocation_envelope_iis_evidence_sha256": str(
                allocation_envelope_diagnostic["iis_evidence_sha256"]
            ),
            "allocation_envelope_state_tolerance": state_tolerance,
            "allocation_envelope_effective_state_tolerance": state_tolerance,
        }
    )
    if bool(allocation_envelope_diagnostic.get("oracle_only", False)):
        metadata.update(
            {
                "allocation_envelope_oracle_only": True,
                "allocation_envelope_termination_condition": (
                    "not_run_oracle_only"
                ),
            }
        )
        return tie_result, metadata
    model.allocation_envelope_objective.activate()
    endpoint_warm_start = (
        in_memory_endpoint_warm_start
        if in_memory_endpoint_warm_start is not None
        else _prepare_allocation_endpoint_warm_start(
            model,
            diagnostic=allocation_envelope_diagnostic,
            normal_oracle=normal_oracle,
            tolerance=state_tolerance,
        )
    )
    metadata.update(
        {
            "allocation_envelope_warm_start_status": endpoint_warm_start[
                "status"
            ],
            "allocation_envelope_warm_start_assignment_count": (
                endpoint_warm_start["assignment_count"]
            ),
            "allocation_envelope_warm_start_variable_name_sha256": (
                endpoint_warm_start["assignment_variable_name_sha256"]
            ),
            "allocation_envelope_warm_start_variable_schema_sha256": (
                endpoint_warm_start["assignment_variable_schema_sha256"]
            ),
            "allocation_envelope_warm_start_value_state_sha256": (
                endpoint_warm_start["assignment_value_state_sha256"]
            ),
            "allocation_envelope_warm_start_full_state_sha256": (
                endpoint_warm_start["full_start_value_state_sha256"]
            ),
            "allocation_envelope_warm_start_source_record_sha256": (
                endpoint_warm_start["source_normal_solution_sha256"]
            ),
            "allocation_envelope_warm_start_fixed_overwrite_count": (
                endpoint_warm_start["endpoint_fixed_overwrite_count"]
            ),
            "allocation_envelope_warm_start_max_constraint_violation": (
                endpoint_warm_start["loaded_start_audit"][
                    "max_constraint_violation"
                ]
            ),
            "allocation_envelope_warm_start_max_bound_violation": (
                endpoint_warm_start["loaded_start_audit"][
                    "max_variable_bound_violation"
                ]
            ),
            "allocation_envelope_warm_start_max_integrality_violation": (
                endpoint_warm_start["loaded_start_audit"][
                    "max_integrality_violation"
                ]
            ),
            "allocation_envelope_warm_start_audit_path": (
                endpoint_warm_start["audit_path"]
            ),
            "allocation_envelope_warm_start_audit_sha256": (
                endpoint_warm_start["audit_sha256"]
            ),
        }
    )
    solver_name = str(getattr(solver, "name", "")).lower()
    endpoint_warmstart_argument = "gurobi" in solver_name
    endpoint_pre_solve_model_path: Path | None = None
    endpoint_pre_solve_model_sha256: str | None = None
    endpoint_solver_log_path: Path | None = None
    endpoint_option_names = (
        "DualReductions",
        "InfUnbdInfo",
        "FeasibilityTol",
        "MIPGap",
        "MIPGapAbs",
        "LogFile",
    )
    missing_option = object()
    prior_endpoint_options: dict[str, Any] = {}
    endpoint_start = time.perf_counter()
    try:
        if "gurobi" in solver_name:
            prior_endpoint_options = {
                name: (
                    solver.options[name]
                    if name in solver.options
                    else missing_option
                )
                for name in endpoint_option_names
            }
            solver.options["DualReductions"] = 0
            solver.options["InfUnbdInfo"] = 1
            solver.options["FeasibilityTol"] = state_tolerance
            solver.options["MIPGap"] = endpoint_relative_mip_gap
            solver.options["MIPGapAbs"] = endpoint_absolute_mip_gap_mwh
            # Prefer the replan-specific oracle directory.  The failure-evidence
            # directory is shared by the trajectory and would overwrite earlier
            # endpoint LPs and solver logs in a seven-window run.
            failure_directory = allocation_envelope_diagnostic.get(
                "oracle_directory"
            ) or allocation_envelope_diagnostic.get(
                "failure_evidence_directory"
            )
            if failure_directory:
                resolved_failure_directory = Path(
                    str(failure_directory)
                ).resolve()
                resolved_failure_directory.mkdir(parents=True, exist_ok=True)
                endpoint_solver_log_path = (
                    resolved_failure_directory / "endpoint_solver.log"
                )
                endpoint_pre_solve_model_path = (
                    resolved_failure_directory / "endpoint_pre_solve_model.lp"
                )
                model.write(
                    str(endpoint_pre_solve_model_path),
                    io_options={"symbolic_solver_labels": True},
                )
                endpoint_pre_solve_model_sha256 = _sha256_file(
                    endpoint_pre_solve_model_path
                )
                solver.options["LogFile"] = str(endpoint_solver_log_path)
        endpoint_result = (
            solver.solve(model, warmstart=True)
            if endpoint_warmstart_argument
            else solver.solve(model)
        )
    finally:
        for name, previous_value in prior_endpoint_options.items():
            if previous_value is missing_option:
                solver.options.pop(name, None)
            else:
                solver.options[name] = previous_value
    endpoint_runtime = time.perf_counter() - endpoint_start
    endpoint_termination = str(endpoint_result.solver.termination_condition)
    endpoint_solver_log_sha256 = (
        _sha256_file(endpoint_solver_log_path)
        if endpoint_solver_log_path is not None
        and endpoint_solver_log_path.is_file()
        else None
    )
    if endpoint_termination.lower() != "optimal":
        _preserve_allocation_endpoint_failure(
            model,
            endpoint_result,
            allocation_envelope_diagnostic,
            endpoint=endpoint,
            normal_snapshot=normal_snapshot,
            primary_cost=primary_cost,
            primary_best_bound=metadata["primary_cost_best_bound_eur"],
            normal_cost=normal_cost,
            cost_tolerance=cost_tolerance,
            normal_oracle=normal_oracle,
            warm_start_audit=endpoint_warm_start,
            deactivated_deadline_name=deactivated_deadline_name,
            endpoint_pre_solve_model_path=endpoint_pre_solve_model_path,
            endpoint_pre_solve_model_sha256=(
                endpoint_pre_solve_model_sha256
            ),
            endpoint_solver_log_path=endpoint_solver_log_path,
        )
        raise S44CModelBuilderError(
            "Allocation-envelope endpoint did not terminate optimal: "
            f"{endpoint_termination}."
        )
    endpoint_incumbent_mwh = float(value(endpoint_expression))
    endpoint_objective_bound_audit = (
        _allocation_endpoint_objective_bound_audit(
            endpoint_result,
            endpoint=endpoint,
            incumbent_mwh=endpoint_incumbent_mwh,
            absolute_gap_limit_mwh=endpoint_absolute_mip_gap_mwh,
            comparison_epsilon_mwh=(
                endpoint_bound_comparison_epsilon_mwh
            ),
        )
    )
    if endpoint_objective_bound_audit["status"] != "pass":
        _preserve_allocation_endpoint_failure(
            model,
            endpoint_result,
            allocation_envelope_diagnostic,
            endpoint=endpoint,
            normal_snapshot=normal_snapshot,
            primary_cost=primary_cost,
            primary_best_bound=metadata["primary_cost_best_bound_eur"],
            normal_cost=normal_cost,
            cost_tolerance=cost_tolerance,
            normal_oracle=normal_oracle,
            warm_start_audit=endpoint_warm_start,
            deactivated_deadline_name=deactivated_deadline_name,
            endpoint_pre_solve_model_path=endpoint_pre_solve_model_path,
            endpoint_pre_solve_model_sha256=(
                endpoint_pre_solve_model_sha256
            ),
            endpoint_solver_log_path=endpoint_solver_log_path,
            endpoint_objective_bound_audit=(
                endpoint_objective_bound_audit
            ),
        )
        raise S44CModelBuilderError(
            "Allocation-envelope endpoint incumbent/best-bound audit failed: "
            f"{endpoint_objective_bound_audit}."
        )
    endpoint_snapshot = {
        key: float(value(expression))
        for key, expression in state_expressions.items()
    }
    max_state_residual = max(
        abs(endpoint_snapshot[key] - normal_snapshot[key])
        for key in normal_snapshot
    )
    endpoint_cost = float(value(model.represented_procurement_cost_eur))
    primary_best_bound = metadata["primary_cost_best_bound_eur"]
    best_bound_availability = metadata[
        "primary_cost_best_bound_availability"
    ]
    endpoint_minus_primary_best_bound = (
        endpoint_cost - float(primary_best_bound)
        if primary_best_bound is not None
        else None
    )
    solver_cost_feasibility_tolerance = (
        1e-6 if "gurobi" in str(getattr(solver, "name", "")).lower() else 0.0
    )
    best_bound_audit_status = (
        "not_applicable_physical_upper_bound"
        if physical_wag_upper_bound
        else "pass"
        if endpoint_minus_primary_best_bound is not None
        and endpoint_minus_primary_best_bound >= 0.0
        else "unavailable"
        if best_bound_availability != "available"
        else "fail"
    )
    primary_objective_audit_status = (
        "not_applicable_physical_upper_bound"
        if physical_wag_upper_bound
        else "pass"
        if endpoint_cost
        <= primary_cost + cost_tolerance + solver_cost_feasibility_tolerance
        else "fail"
    )
    solver_state_feasibility_tolerance = (
        1e-6 if "gurobi" in str(getattr(solver, "name", "")).lower() else 0.0
    )
    effective_state_tolerance = state_tolerance
    if (
        max_state_residual > effective_state_tolerance
        or (
            not physical_wag_upper_bound
            and endpoint_cost > primary_cost + cost_tolerance + 1e-6
        )
        or (
            not physical_wag_upper_bound
            and best_bound_audit_status != "pass"
        )
    ):
        raise S44CModelBuilderError(
            "Allocation-envelope endpoint failed state or represented-cost "
            f"preservation: max_state_residual={max_state_residual}, "
            f"state_tolerance={state_tolerance}, endpoint_cost_eur={endpoint_cost}, "
            f"primary_cost_eur={primary_cost}, upper_tolerance_eur={cost_tolerance}, "
            f"primary_best_bound_eur={primary_best_bound}, "
            f"best_bound_availability={best_bound_availability}, "
            f"best_bound_audit_status={best_bound_audit_status}."
        )
    normal_handoff_hash = _snapshot_hash(normal_snapshot)
    raw_endpoint_handoff_hash = _snapshot_hash(endpoint_snapshot)
    endpoint_handoff_hash = raw_endpoint_handoff_hash
    if sale_breakthrough_context is not None:
        metadata["sale_breakthrough_test"] = _sale_breakthrough_test_record(
            sale_breakthrough_context
        )
        if metadata["sale_breakthrough_test"]["resource_caps_status"] != "pass":
            raise S44CModelBuilderError(
                "Phase-5B endpoint violated its comparator resource caps."
            )
    metadata.update(
        {
            "allocation_envelope_active": True,
            "allocation_envelope_endpoint": endpoint,
            "allocation_envelope_breakthrough_mode": (
                breakthrough_mode or None
            ),
            "allocation_envelope_cost_preservation_requirement": (
                "not_applicable_physical_upper_bound"
                if physical_wag_upper_bound
                else "required"
            ),
            "allocation_envelope_execution_hours": execution_hours,
            "allocation_envelope_objective_value_mwh": endpoint_incumbent_mwh,
            "allocation_envelope_endpoint_accuracy_schema": (
                endpoint_objective_bound_audit["schema_version"]
            ),
            "allocation_envelope_endpoint_incumbent_basis": (
                "feasible_solution"
            ),
            "allocation_envelope_endpoint_best_bound_availability": (
                endpoint_objective_bound_audit["best_bound_availability"]
            ),
            "allocation_envelope_endpoint_best_bound_mwh": (
                endpoint_objective_bound_audit["best_bound_mwh"]
            ),
            "allocation_envelope_endpoint_objective_bound_abs_gap_mwh": (
                endpoint_objective_bound_audit[
                    "absolute_objective_bound_gap_mwh"
                ]
            ),
            "allocation_envelope_endpoint_objective_bound_audit_status": (
                endpoint_objective_bound_audit["status"]
            ),
            "allocation_envelope_endpoint_bound_sense_status": (
                endpoint_objective_bound_audit["sense_consistency_status"]
            ),
            "allocation_envelope_endpoint_relative_mip_gap_target": (
                endpoint_relative_mip_gap
            ),
            "allocation_envelope_endpoint_absolute_mip_gap_target_mwh": (
                endpoint_absolute_mip_gap_mwh
            ),
            "allocation_envelope_endpoint_bound_comparison_epsilon_mwh": (
                endpoint_bound_comparison_epsilon_mwh
            ),
            "allocation_envelope_endpoint_solver_options": {
                "MIPGap": endpoint_relative_mip_gap,
                "MIPGapAbs": endpoint_absolute_mip_gap_mwh,
                "warmstart": endpoint_warmstart_argument,
            },
            "allocation_envelope_endpoint_solver_options_sha256": (
                hashlib.sha256(
                    json.dumps(
                        {
                            "MIPGap": endpoint_relative_mip_gap,
                            "MIPGapAbs": endpoint_absolute_mip_gap_mwh,
                            "warmstart": endpoint_warmstart_argument,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            ),
            "allocation_envelope_runtime_seconds": endpoint_runtime,
            "allocation_envelope_solver_status": str(
                endpoint_result.solver.status
            ),
            "allocation_envelope_termination_condition": endpoint_termination,
            "allocation_envelope_mip_gap": _mip_gap(endpoint_result),
            "allocation_envelope_warmstart_solver_argument": (
                endpoint_warmstart_argument
            ),
            "allocation_envelope_endpoint_solver_log_path": (
                _portable_repository_path(endpoint_solver_log_path)
                if endpoint_solver_log_path is not None
                else None
            ),
            "allocation_envelope_endpoint_pre_solve_model_path": (
                _portable_repository_path(endpoint_pre_solve_model_path)
                if endpoint_pre_solve_model_path is not None
                else None
            ),
            "allocation_envelope_endpoint_pre_solve_model_sha256": (
                endpoint_pre_solve_model_sha256
            ),
            "allocation_envelope_endpoint_solver_log_sha256": (
                endpoint_solver_log_sha256
            ),
            "allocation_envelope_cost_eur": endpoint_cost,
            "allocation_envelope_cost_minus_primary_eur": endpoint_cost
            - primary_cost,
            "allocation_envelope_primary_cost_best_bound_eur": (
                primary_best_bound
            ),
            "allocation_envelope_primary_cost_best_bound_availability": (
                best_bound_availability
            ),
            "allocation_envelope_cost_minus_primary_best_bound_eur": (
                endpoint_minus_primary_best_bound
            ),
            "allocation_envelope_primary_objective_audit_status": (
                primary_objective_audit_status
            ),
            "allocation_envelope_best_bound_audit_status": (
                best_bound_audit_status
            ),
            "allocation_envelope_upper_cost_tolerance_eur": cost_tolerance,
            "allocation_envelope_solver_cost_feasibility_tolerance_eur": (
                solver_cost_feasibility_tolerance
            ),
            "allocation_envelope_normal_cost_eur": normal_cost,
            "allocation_envelope_normal_cost_minus_upper_limit_eur": (
                normal_cost_minus_upper_limit
            ),
            "allocation_envelope_normal_incumbent_min_formulation_feasible": (
                bool(normal_incumbent_audit["feasible"])
            ),
            "allocation_envelope_normal_incumbent_max_formulation_feasible": (
                bool(normal_incumbent_audit["feasible"])
            ),
            "allocation_envelope_normal_incumbent_feasibility_audit": (
                normal_incumbent_audit
            ),
            "allocation_envelope_normal_feasibility_oracle_status": (
                normal_oracle["status"]
            ),
            "allocation_envelope_normal_feasibility_oracle_record_path": (
                normal_oracle["oracle_record_path"]
            ),
            "allocation_envelope_normal_feasibility_oracle_record_sha256": (
                normal_oracle["oracle_record_sha256"]
            ),
            "allocation_envelope_deactivated_deadline_row": (
                deactivated_deadline_name
            ),
            "allocation_envelope_iis_evidence_sha256": str(
                allocation_envelope_diagnostic["iis_evidence_sha256"]
            ),
            "allocation_envelope_normal_objective_value_mwh": (
                normal_endpoint_objective_value
            ),
            "allocation_envelope_normal_handoff_snapshot": normal_snapshot,
            "allocation_envelope_endpoint_handoff_snapshot": endpoint_snapshot,
            "allocation_envelope_normal_handoff_hash": normal_handoff_hash,
            "allocation_envelope_endpoint_handoff_hash": endpoint_handoff_hash,
            "allocation_envelope_raw_endpoint_handoff_hash": (
                raw_endpoint_handoff_hash
            ),
            "allocation_envelope_local_normal_handoff_snapshot": (
                local_normal_snapshot
            ),
            "allocation_envelope_max_local_normal_schedule_residual": (
                max_local_normal_schedule_residual
            ),
            "allocation_envelope_max_state_residual": max_state_residual,
            "allocation_envelope_state_tolerance": state_tolerance,
            "allocation_envelope_solver_state_feasibility_tolerance": (
                solver_state_feasibility_tolerance
            ),
            "allocation_envelope_effective_state_tolerance": (
                effective_state_tolerance
            ),
        }
    )
    return endpoint_result, metadata


def _horizon_hours(tables: UnifiedInputTables, horizon_hours_override: int | None = None) -> int:
    if horizon_hours_override is not None:
        return int(horizon_hours_override)
    row = _first_row(
        tables.tables["solver_and_horizon_config.csv"],
        run_profile_id="S4_4B_24H_STATIC_REGRESSION",
    )
    return int(_as_float(row["horizon_hours"], field_name="horizon_hours"))


def _target_for_configuration(tables: UnifiedInputTables, configuration_id: str, target_multiplier: float = 1.0) -> float:
    rows = [
        row
        for row in tables.tables["production_targets.csv"]
        if row.get("configuration_id") == configuration_id
        and row.get("hard_target", "").lower() == "true"
        and _is_executable(row)
    ]
    if not rows:
        raise S44CModelBuilderError(f"No executable hard production target for {configuration_id}.")
    return _as_float(rows[0]["target_value"], field_name="target_value") * target_multiplier


def _has_completed_c0_inputs(tables: UnifiedInputTables) -> bool:
    try:
        _build_c0_inputs(tables)
    except S44CModelBuilderError:
        return False
    return True


def _build_c0_inputs(
    tables: UnifiedInputTables,
    *,
    horizon_hours_override: int | None = None,
    target_multiplier: float = 1.0,
) -> C0ExecutableInputs:
    process_units = [row for row in tables.tables["process_units.csv"] if _is_executable(row)]
    io_rows = [row for row in tables.tables["process_io_coefficients.csv"] if _is_executable(row)]
    buffer_rows = [row for row in tables.tables["buffers_and_stores.csv"] if _is_executable(row)]
    wag_rows = [row for row in tables.tables["wag_generation_coefficients.csv"] if _is_executable(row)]

    _require_process_rate_unit(
        process_units, "C0_current_BF_BOF_reference", "sintering_plant", "t_iron_ore/h"
    )
    _require_process_rate_unit(
        process_units, "C0_current_BF_BOF_reference", "blast_furnace_6", "t_sinter/h"
    )
    _require_process_rate_unit(
        process_units, "C0_current_BF_BOF_reference", "blast_furnace_7", "t_sinter/h"
    )

    process_limits = {
        asset_id: _c0_process_limit(process_units, asset_id)
        for asset_id in (
            "coking_plant_1",
            "coking_plant_2",
            "sintering_plant",
            "blast_furnace_6",
            "blast_furnace_7",
            "basic_oxygen_furnace",
            "hot_strip_mill",
        )
    }
    coke_capacity, coke_initial = _c0_store(buffer_rows, "C0_current_BF_BOF_reference__coke_store")
    sinter_capacity, sinter_initial = _c0_store(buffer_rows, "C0_current_BF_BOF_reference__sinter_store")
    hot_iron_capacity, hot_iron_initial = _c0_store(buffer_rows, "C0_current_BF_BOF_reference__hot_iron_store")
    cold_slab_capacity, cold_slab_initial = _c0_store(buffer_rows, "C0_current_BF_BOF_reference__cold_slab_store")
    bfg = _first_row(wag_rows, configuration_id="C0_current_BF_BOF_reference", process_id="blast_furnace_6", wag_carrier="BFG")
    cog = _first_row(wag_rows, configuration_id="C0_current_BF_BOF_reference", process_id="coking_plant_1", wag_carrier="COG")
    bofg = _first_row(wag_rows, configuration_id="C0_current_BF_BOF_reference", process_id="basic_oxygen_furnace", wag_carrier="BOFG")

    return C0ExecutableInputs(
        horizon_hours=_horizon_hours(tables, horizon_hours_override),
        final_product_target_t=_target_for_configuration(tables, "C0_current_BF_BOF_reference", target_multiplier),
        process_limits=process_limits,
        sinter_output_per_t_iron_ore=_numeric_coefficient(
            io_rows,
            process_id="sintering_plant",
            input_material="iron_ore",
            output_material="sinter",
            expected_unit="t_sinter/t_iron_ore",
        ),
        bf_hot_iron_per_t_sinter=_numeric_coefficient(
            io_rows,
            process_id="blast_furnace_6",
            input_material="sinter",
            output_material="hot_iron",
            expected_unit="t_hot_iron/t_sinter",
        ),
        bof_crude_steel_per_t_hot_iron=_numeric_coefficient(
            io_rows,
            process_id="basic_oxygen_furnace",
            input_material="hot_iron",
            output_material="crude_steel",
        ),
        hsm_final_per_t_crude_steel=1.0,
        coke_per_t_sinter=0.5,
        coke_store_capacity_t=coke_capacity,
        coke_store_initial_t=coke_initial,
        sinter_store_capacity_t=sinter_capacity,
        sinter_store_initial_t=sinter_initial,
        hot_iron_store_capacity_t=hot_iron_capacity,
        hot_iron_store_initial_t=hot_iron_initial,
        cold_slab_store_capacity_t=cold_slab_capacity,
        cold_slab_store_initial_t=cold_slab_initial,
        bfg_nm3_per_t_hot_iron=_as_float(bfg["coefficient"], field_name="BFG coefficient"),
        cog_m3_per_t_dry_coal=_as_float(cog["coefficient"], field_name="COG coefficient"),
        bofg_nm3_per_t_liquid_steel=_as_float(bofg["coefficient"], field_name="BOFG coefficient"),
        bfg_mwh_per_t_hot_iron=_gas_mwh_per_activity(
            _as_float(bfg["coefficient"], field_name="BFG coefficient"),
            "BFG",
        ),
        cog_mwh_per_t_coke=_gas_mwh_per_activity(
            _as_float(cog["coefficient"], field_name="COG coefficient"),
            "COG",
        ),
        bofg_mwh_per_t_liquid_steel=_gas_mwh_per_activity(
            _as_float(bofg["coefficient"], field_name="BOFG coefficient"),
            "BOFG",
        ),
        kgf_underfiring_mwh_per_t_coke=KGF_UNDERFIRING_MWH_PER_T_COKE,
        sinter_cog_mwh_per_t_sinter=SINTER_COG_MWH_PER_T_SINTER,
        boiler_wag_cap_mwh_h=BOILER_WAG_PLACEHOLDER_CAP_MWH_H,
        boiler_total_placeholder_mwh_h=BOILER_TOTAL_PLACEHOLDER_MWH_H,
        eta_boiler_steam=ETA_BOILER_STEAM,
    )


def _build_retained_bf_bof_inputs(
    tables: UnifiedInputTables,
    *,
    configuration_id: str,
) -> RetainedBfBofInputs:
    process_units = [row for row in tables.tables["process_units.csv"] if _is_executable(row)]
    io_rows = [row for row in tables.tables["process_io_coefficients.csv"] if _is_executable(row)]
    buffer_rows = [row for row in tables.tables["buffers_and_stores.csv"] if _is_executable(row)]
    wag_rows = [row for row in tables.tables["wag_generation_coefficients.csv"] if _is_executable(row)]

    _require_process_rate_unit(process_units, configuration_id, "sintering_plant", "t_iron_ore/h")
    _require_process_rate_unit(process_units, configuration_id, "blast_furnace_6", "t_sinter/h")

    process_limits = {
        asset_id: _configuration_process_limit(process_units, configuration_id, asset_id)
        for asset_id in (
            "coking_plant_1",
            "sintering_plant",
            "blast_furnace_6",
            "basic_oxygen_furnace",
            "hot_strip_mill",
        )
    }
    coke_capacity, coke_initial = _configuration_store(buffer_rows, configuration_id, f"{configuration_id}__coke_store")
    sinter_capacity, sinter_initial = _configuration_store(buffer_rows, configuration_id, f"{configuration_id}__sinter_store")
    hot_iron_capacity, hot_iron_initial = _configuration_store(
        buffer_rows,
        configuration_id,
        f"{configuration_id}__hot_iron_store",
    )
    cold_slab_capacity, cold_slab_initial = _configuration_store(
        buffer_rows,
        configuration_id,
        f"{configuration_id}__cold_slab_store",
    )
    bfg = _first_row(wag_rows, configuration_id=configuration_id, process_id="blast_furnace_6", wag_carrier="BFG")
    cog = _first_row(wag_rows, configuration_id=configuration_id, process_id="coking_plant_1", wag_carrier="COG")
    bofg = _first_row(wag_rows, configuration_id=configuration_id, process_id="basic_oxygen_furnace", wag_carrier="BOFG")

    return RetainedBfBofInputs(
        process_limits=process_limits,
        sinter_output_per_t_iron_ore=_numeric_coefficient(
            io_rows,
            process_id="sintering_plant",
            input_material="iron_ore",
            output_material="sinter",
            expected_unit="t_sinter/t_iron_ore",
        ),
        bf_hot_iron_per_t_sinter=_numeric_coefficient(
            io_rows,
            process_id="blast_furnace_6",
            input_material="sinter",
            output_material="hot_iron",
            expected_unit="t_hot_iron/t_sinter",
        ),
        bof_crude_steel_per_t_hot_iron=_numeric_coefficient(
            io_rows,
            process_id="basic_oxygen_furnace",
            input_material="hot_iron",
            output_material="crude_steel",
        ),
        hsm_final_per_t_crude_steel=1.0,
        coke_per_t_sinter=0.5,
        coke_store_capacity_t=coke_capacity,
        coke_store_initial_t=coke_initial,
        sinter_store_capacity_t=sinter_capacity,
        sinter_store_initial_t=sinter_initial,
        hot_iron_store_capacity_t=hot_iron_capacity,
        hot_iron_store_initial_t=hot_iron_initial,
        cold_slab_store_capacity_t=cold_slab_capacity,
        cold_slab_store_initial_t=cold_slab_initial,
        bfg_nm3_per_t_hot_iron=_as_float(bfg["coefficient"], field_name="C1 BFG coefficient"),
        cog_m3_per_t_dry_coal=_as_float(cog["coefficient"], field_name="C1 COG coefficient"),
        bofg_nm3_per_t_liquid_steel=_as_float(bofg["coefficient"], field_name="C1 BOFG coefficient"),
        bfg_mwh_per_t_hot_iron=_gas_mwh_per_activity(
            _as_float(bfg["coefficient"], field_name="C1 BFG coefficient"),
            "BFG",
        ),
        cog_mwh_per_t_coke=_gas_mwh_per_activity(
            _as_float(cog["coefficient"], field_name="C1 COG coefficient"),
            "COG",
        ),
        bofg_mwh_per_t_liquid_steel=_gas_mwh_per_activity(
            _as_float(bofg["coefficient"], field_name="C1 BOFG coefficient"),
            "BOFG",
        ),
        kgf_underfiring_mwh_per_t_coke=KGF_UNDERFIRING_MWH_PER_T_COKE,
        sinter_cog_mwh_per_t_sinter=SINTER_COG_MWH_PER_T_SINTER,
        boiler_wag_cap_mwh_h=BOILER_WAG_PLACEHOLDER_CAP_MWH_H,
        boiler_total_placeholder_mwh_h=BOILER_TOTAL_PLACEHOLDER_MWH_H,
        eta_boiler_steam=ETA_BOILER_STEAM,
        retained_target_share=C1_RETAINED_BFBOF_TARGET_SHARE,
    )


def _apply_c0_static_binary_schedule(
    model: ConcreteModel,
    inputs: C0ExecutableInputs,
    process_names: tuple[str, ...],
    *,
    wag_compatible: bool = False,
    fixed_schedule_hours_by_process: Mapping[str, Collection[int]] | None = None,
) -> None:
    if inputs.horizon_hours % 24 != 0:
        raise S44CModelBuilderError("Fixed C0 binary schedule requires a full-day horizon.")
    if fixed_schedule_hours_by_process is not None:
        expected = set(process_names)
        actual = set(fixed_schedule_hours_by_process)
        if actual != expected:
            raise S44CModelBuilderError(
                "Fixed C0 schedule profile must define exactly the active C0 processes. "
                f"Missing={sorted(expected.difference(actual))}; extra={sorted(actual.difference(expected))}."
            )
        try:
            invalid_hours = sorted(
                {
                    int(hour)
                    for hours in fixed_schedule_hours_by_process.values()
                    for hour in hours
                    if int(hour) not in range(24)
                }
            )
        except (TypeError, ValueError) as exc:
            raise S44CModelBuilderError("Fixed C0 schedule profile hours must be integers.") from exc
        if invalid_hours:
            raise S44CModelBuilderError(f"Fixed C0 schedule profile has invalid hours: {invalid_hours}")
        for t in model.TIME:
            hour_of_day = int(t) % 24
            for process_name in process_names:
                active = hour_of_day in fixed_schedule_hours_by_process[process_name]
                getattr(model, f"{process_name}_on")[t].fix(1 if active else 0)
        return
    eight_hour_block = {
        "coking_plant_1",
        "blast_furnace_6",
        "blast_furnace_7",
        "basic_oxygen_furnace",
        "hot_strip_mill",
    }
    for t in model.TIME:
        hour_of_day = int(t) % 24
        for process_name in process_names:
            active = process_name in eight_hour_block and hour_of_day < 8
            if process_name == "sintering_plant":
                active = hour_of_day < 9
            if wag_compatible:
                if process_name == "coking_plant_1":
                    active = hour_of_day in {0, 2, 4, 6, 8}
                elif process_name == "coking_plant_2":
                    active = hour_of_day in {1, 3, 5, 7}
                elif process_name in {
                    "blast_furnace_6",
                    "blast_furnace_7",
                    "basic_oxygen_furnace",
                    "hot_strip_mill",
                    "sintering_plant",
                }:
                    active = hour_of_day < 9
            getattr(model, f"{process_name}_on")[t].fix(1 if active else 0)


def _add_daily_production_guardrail(model: ConcreteModel, inputs: C0ExecutableInputs) -> None:
    if inputs.horizon_hours % 24 != 0:
        raise S44CModelBuilderError("Daily production guardrail requires a full-day horizon.")
    day_count = inputs.horizon_hours // 24
    average_daily_target = inputs.final_product_target_t / day_count
    model.DAYS = RangeSet(0, day_count - 1)
    model.daily_production_lower_guardrail = Constraint(
        model.DAYS,
        rule=lambda m, d: sum(m.final_product_output[t] for t in range(int(d) * 24, int(d) * 24 + 24))
        >= 0.80 * average_daily_target,
    )
    model.daily_production_upper_guardrail = Constraint(
        model.DAYS,
        rule=lambda m, d: sum(m.final_product_output[t] for t in range(int(d) * 24, int(d) * 24 + 24))
        <= 1.20 * average_daily_target,
    )


def _apply_c1_hybrid_static_schedule(model: ConcreteModel, horizon_hours: int) -> None:
    if horizon_hours % 24 != 0:
        raise S44CModelBuilderError("C1 hybrid fixed schedule requires a full-day horizon.")
    retained_hours = {
        "coking_plant_1": {1, 3, 5, 7},
        "sintering_plant": {1, 3, 5, 7},
        "blast_furnace_6": set(range(0, 8)),
        "basic_oxygen_furnace": {0, 2, 3, 5, 7},
        "hot_strip_mill": {0, 2, 3, 5, 7},
    }
    drp_hours = set(range(0, 10))
    eaf_hours = set(range(1, 10))
    for t in model.TIME:
        hour_of_day = int(t) % 24
        for process_name, active_hours in retained_hours.items():
            getattr(model, f"{process_name}_on")[t].fix(1 if hour_of_day in active_hours else 0)
        model.drp_on[t].fix(1 if hour_of_day in drp_hours else 0)
        model.eaf_on[t].fix(1 if hour_of_day in eaf_hours else 0)


def _apply_c1_bottom_up_retained_route_policy(model: ConcreteModel, horizon_hours: int) -> None:
    """Fix the retained C1 BF-BOF route from process rates, not a route-share target."""
    _apply_c1_hybrid_static_schedule(model, horizon_hours)
    retained_rates: dict[str, float | dict[int, float]] = {
        "coking_plant_1": 150.0,
        "sintering_plant": 300.0,
        "blast_furnace_6": {0: 170.0, 1: 170.0, 2: 170.0, 3: 170.0, 4: 130.0, 5: 130.0, 6: 130.0, 7: 130.0},
        "basic_oxygen_furnace": 505.0,
        "hot_strip_mill": 505.0,
    }
    for t in model.TIME:
        hour_of_day = int(t) % 24
        for process_name, rate in retained_rates.items():
            on_value = int(round(float(getattr(model, f"{process_name}_on")[t].value or 0.0)))
            hourly_rate = rate.get(hour_of_day, 0.0) if isinstance(rate, dict) else rate
            getattr(model, process_name)[t].fix(hourly_rate if on_value else 0.0)


def _add_rolling_production_deadline_envelope(
    model: ConcreteModel,
    *,
    horizon_hours: int,
    final_product_target_t: float,
    deadline_targets_t: Mapping[int, float],
) -> None:
    """Add cumulative hard production deadlines to an existing physical model.

    This is a scheduling envelope, not a market objective or annual
    calibration. The final deadline equals the configured horizon quota; every
    deadline remains a lower-bound service requirement.
    """
    if not deadline_targets_t:
        raise S44CModelBuilderError("Rolling production deadline targets cannot be empty.")
    deadlines = tuple(sorted(int(hour) for hour in deadline_targets_t))
    if any(hour <= 0 or hour > horizon_hours for hour in deadlines):
        raise S44CModelBuilderError("Rolling production deadlines must lie within the planning horizon.")
    targets = {hour: float(deadline_targets_t[hour]) for hour in deadlines}
    if any(target < 0.0 for target in targets.values()):
        raise S44CModelBuilderError("Rolling production deadline targets must be non-negative.")
    if any(targets[right] + TOLERANCE < targets[left] for left, right in zip(deadlines, deadlines[1:])):
        raise S44CModelBuilderError("Rolling production deadline targets must be cumulative and non-decreasing.")
    if deadlines[-1] != horizon_hours:
        raise S44CModelBuilderError("Rolling production deadline envelope must include the planning-horizon endpoint.")
    if abs(targets[deadlines[-1]] - final_product_target_t) > TOLERANCE:
        raise S44CModelBuilderError("Final rolling production deadline must equal the model final-product target.")

    model.ROLLING_PRODUCTION_DEADLINE = tuple(deadlines)
    model.rolling_production_deadline = Constraint(
        model.ROLLING_PRODUCTION_DEADLINE,
        rule=lambda m, hour: sum(m.final_product_output[t] for t in range(int(hour))) >= targets[int(hour)],
    )


def _add_rolling_production_progress_tracking(
    model: ConcreteModel,
    *,
    execution_block_hours: int,
    next_execution_target_t: float,
    hard_exact_execution_target: bool = False,
    exact_deadline_hour: int | None = None,
    exact_deadline_target_t: float | None = None,
    execution_lower_bound_t: float | None = None,
    execution_upper_bound_t: float | None = None,
    zero_deviation_inside_recoverability_band: bool = False,
) -> None:
    """Add a lexicographic target for the next executed rolling block.

    The target is supplied by the rolling controller after subtracting carried
    production credit (or adding carried debt).  It is deliberately an
    objective tier, not a fixed hourly profile or a hard production equality:
    a primary procurement-cost objective may still select another point inside
    the governed feasibility envelope when prices make that optimal.
    """

    if execution_block_hours <= 0 or execution_block_hours > len(model.TIME):
        raise S44CModelBuilderError(
            "Rolling production-progress execution hours must lie inside the horizon."
        )
    if next_execution_target_t < 0.0:
        raise S44CModelBuilderError(
            "Rolling production-progress target must be non-negative."
        )
    model.rolling_production_progress_surplus_t = Var(domain=NonNegativeReals)
    model.rolling_production_progress_deficit_t = Var(domain=NonNegativeReals)
    executed_output = sum(
        model.final_product_output[t] for t in range(execution_block_hours)
    )
    if zero_deviation_inside_recoverability_band:
        if execution_lower_bound_t is None or execution_upper_bound_t is None:
            raise S44CModelBuilderError(
                "Band-neutral production progress requires both recoverability bounds."
            )
        model.rolling_production_progress_above_band = Constraint(
            expr=executed_output - float(execution_upper_bound_t)
            <= model.rolling_production_progress_surplus_t
        )
        model.rolling_production_progress_below_band = Constraint(
            expr=float(execution_lower_bound_t) - executed_output
            <= model.rolling_production_progress_deficit_t
        )
    else:
        model.rolling_production_progress_identity = Constraint(
            expr=(
                executed_output
                - float(next_execution_target_t)
                == model.rolling_production_progress_surplus_t
                - model.rolling_production_progress_deficit_t
            )
        )
    if execution_lower_bound_t is not None:
        model.rolling_production_recoverability_lower = Constraint(
            expr=executed_output >= float(execution_lower_bound_t)
        )
    if execution_upper_bound_t is not None:
        if (
            execution_lower_bound_t is not None
            and float(execution_upper_bound_t) + TOLERANCE
            < float(execution_lower_bound_t)
        ):
            raise S44CModelBuilderError(
                "Rolling recoverability upper bound is below its lower bound."
            )
        model.rolling_production_recoverability_upper = Constraint(
            expr=executed_output <= float(execution_upper_bound_t)
        )
    if hard_exact_execution_target:
        model.rolling_production_terminal_quota_equality = Constraint(
            expr=sum(
                model.final_product_output[t]
                for t in range(execution_block_hours)
            )
            == float(next_execution_target_t)
        )
    if exact_deadline_hour is not None or exact_deadline_target_t is not None:
        if exact_deadline_hour is None or exact_deadline_target_t is None:
            raise S44CModelBuilderError(
                "A rolling exact deadline requires both its hour and target."
            )
        deadline_hour = int(exact_deadline_hour)
        if deadline_hour <= 0 or deadline_hour > len(model.TIME):
            raise S44CModelBuilderError(
                "Rolling exact deadline hour must lie inside the planning horizon."
            )
        if float(exact_deadline_target_t) < 0.0:
            raise S44CModelBuilderError(
                "Rolling exact deadline target must be non-negative."
            )
        model.rolling_production_future_terminal_quota_equality = Constraint(
            expr=sum(model.final_product_output[t] for t in range(deadline_hour))
            == float(exact_deadline_target_t)
        )
    model.rolling_production_progress_deviation_t = Expression(
        expr=model.rolling_production_progress_surplus_t
        + model.rolling_production_progress_deficit_t
    )
    model.rolling_production_progress_objective = Objective(
        expr=model.rolling_production_progress_deviation_t,
        sense=minimize,
    )
    # The solve adapter activates this objective at the correct lexicographic
    # tier.  Keeping it inactive during model construction prevents multiple
    # active objectives.
    model.rolling_production_progress_objective.deactivate()
    model.rolling_production_progress_target_t = float(next_execution_target_t)
    model.rolling_production_progress_execution_hours = int(execution_block_hours)
    model.rolling_production_hard_exact_execution_target = bool(
        hard_exact_execution_target
    )
    model.rolling_production_zero_deviation_inside_recoverability_band = bool(
        zero_deviation_inside_recoverability_band
    )


def _add_rolling_terminal_inventory_band(
    model: ConcreteModel,
    *,
    terminal_hour: int | None,
    bounds_t: Mapping[str, Mapping[str, float]] | None,
) -> None:
    """Replace cyclic horizon closure with a frozen campaign-terminal band."""

    if bounds_t is None:
        return
    if terminal_hour is None:
        raise S44CModelBuilderError(
            "A rolling terminal inventory band requires its in-horizon hour."
        )
    if terminal_hour <= 0 or terminal_hour > len(model.TIME):
        raise S44CModelBuilderError(
            "Rolling terminal inventory hour must lie inside the planning horizon."
        )
    if terminal_hour != len(model.TIME):
        raise S44CModelBuilderError(
            "A campaign-terminal inventory band must be applied at the effective "
            "end of the truncated planning horizon."
        )
    expressions = {
        "coke_inventory_t": "coke_inventory",
        "sinter_inventory_t": "sinter_inventory",
        "hot_iron_inventory_t": "hot_iron_inventory",
        "cold_slab_inventory_t": "cold_slab_inventory",
        "dri_inventory_t": "dri_inventory",
    }
    cyclic_constraints = {
        "coke_inventory_t": "coke_terminal",
        "sinter_inventory_t": "sinter_terminal",
        "hot_iron_inventory_t": "hot_iron_terminal",
        "cold_slab_inventory_t": "cold_slab_terminal",
        "dri_inventory_t": "dri_terminal_equality",
    }
    unknown = set(bounds_t).difference(expressions)
    if unknown:
        raise S44CModelBuilderError(
            f"Unsupported rolling terminal inventory state(s): {sorted(unknown)}."
        )
    target_index = int(terminal_hour) - 1
    model.rolling_terminal_inventory_lower_bounds = ConstraintList()
    model.rolling_terminal_inventory_upper_bounds = ConstraintList()
    normalized: dict[str, dict[str, float]] = {}
    replaced_cyclic_constraints: list[str] = []
    for state_id, raw_bounds in sorted(bounds_t.items()):
        attribute = expressions[state_id]
        if not hasattr(model, attribute):
            raise S44CModelBuilderError(
                f"Rolling terminal state {state_id} is not available in this configuration."
            )
        if not isinstance(raw_bounds, Mapping):
            raise S44CModelBuilderError(
                f"Rolling terminal bounds for {state_id} must be a mapping."
            )
        lower_t = float(raw_bounds.get("lower_t", math.nan))
        upper_t = float(raw_bounds.get("upper_t", math.nan))
        target_t = float(raw_bounds.get("target_t", math.nan))
        if (
            not all(math.isfinite(value) for value in (lower_t, upper_t, target_t))
            or lower_t < 0.0
            or lower_t > target_t
            or target_t > upper_t
        ):
            raise S44CModelBuilderError(
                f"Invalid rolling terminal inventory band for {state_id}."
            )
        expression = getattr(model, attribute)[target_index]
        cyclic_name = cyclic_constraints[state_id]
        if hasattr(model, cyclic_name):
            getattr(model, cyclic_name).deactivate()
            replaced_cyclic_constraints.append(cyclic_name)
        model.rolling_terminal_inventory_lower_bounds.add(
            expression >= lower_t
        )
        model.rolling_terminal_inventory_upper_bounds.add(
            expression <= upper_t
        )
        normalized[state_id] = {
            "target_t": target_t,
            "lower_t": lower_t,
            "upper_t": upper_t,
        }
    model.rolling_terminal_inventory_target_hour = target_index
    model.rolling_terminal_inventory_band = normalized
    model.rolling_terminal_inventory_replaced_cyclic_constraints = tuple(
        replaced_cyclic_constraints
    )


def _apply_c1_inventory_terminal_policy(
    model: ConcreteModel,
    *,
    recoverable_handoff_execution_steps: int | None,
    recoverable_dri_tail_state: bool = False,
) -> None:
    """Distinguish a bounded look-ahead tail from a genuine hard terminal.

    With no execution boundary the shared C1 builder retains its exact cyclic
    inventory closure.  With a boundary, the executed state is certified by
    the remaining bounded physical continuation; the artificial tail endpoint
    does not become a second coke/sinter/hot-iron production deadline.
    """

    if recoverable_handoff_execution_steps is None:
        model.c1_inventory_terminal_policy = "hard_cyclic_or_campaign_terminal"
        model.temporal_tail_cyclic_closures_replaced = ()
        return
    execution_steps = int(recoverable_handoff_execution_steps)
    horizon_steps = len(model.TIME)
    if execution_steps <= 0 or execution_steps >= horizon_steps:
        raise S44CModelBuilderError(
            "A recoverable C1 handoff requires an execution boundary strictly "
            "inside the physical horizon."
        )
    for name in (
        "coke_capacity",
        "sinter_capacity",
        "hot_iron_capacity",
        "cold_slab_capacity",
    ):
        if not hasattr(model, name) or not getattr(model, name).active:
            raise S44CModelBuilderError(
                f"A recoverable C1 handoff requires active {name}."
            )
    replaced: list[str] = []
    for name in (
        "coke_terminal",
        "sinter_terminal",
        "hot_iron_terminal",
        "cold_slab_terminal",
    ):
        if not hasattr(model, name) or not getattr(model, name).active:
            raise S44CModelBuilderError(
                f"A recoverable C1 handoff expected active cyclic {name}."
            )
        getattr(model, name).deactivate()
        replaced.append(name)
    if hasattr(model, "pellet_terminal"):
        model.pellet_terminal.deactivate()
        replaced.append("pellet_terminal")
    if hasattr(model, "eaf_slab_terminal"):
        model.eaf_slab_terminal.deactivate()
        replaced.append("eaf_slab_terminal")
    if recoverable_dri_tail_state:
        if not hasattr(model, "dri_terminal_equality") or not model.dri_terminal_equality.active:
            raise S44CModelBuilderError(
                "A recoverable DRI tail expected the active finite-tail equality."
            )
        model.dri_terminal_equality.deactivate()
        replaced.append("dri_terminal_equality")
    model.c1_inventory_terminal_policy = (
        "executed_state_with_bounded_physical_continuation_no_cyclic_tail_closure"
    )
    model.temporal_tail_handoff_policy = model.c1_inventory_terminal_policy
    model.temporal_tail_cyclic_closures_replaced = tuple(replaced)
    model.temporal_executed_handoff_index = execution_steps - 1
    model.temporal_physical_tail_steps = horizon_steps - execution_steps
    model.temporal_dri_tail_state_policy = (
        "capacity_bounded_rolling_state_no_artificial_tail_cycle"
        if recoverable_dri_tail_state
        else "finite_tail_cyclic_reference"
    )


def _apply_c0_inventory_terminal_policy(
    model: ConcreteModel,
    *,
    recoverable_handoff_execution_steps: int | None,
) -> None:
    """Remove artificial C0 tail closure while retaining bounded continuation."""

    if recoverable_handoff_execution_steps is None:
        model.c0_inventory_terminal_policy = "hard_cyclic_or_campaign_terminal"
        model.temporal_tail_cyclic_closures_replaced = ()
        return
    execution_steps = int(recoverable_handoff_execution_steps)
    horizon_steps = len(model.TIME)
    if execution_steps <= 0 or execution_steps >= horizon_steps:
        raise S44CModelBuilderError(
            "A recoverable C0 handoff needs an execution boundary inside the horizon."
        )
    required_capacity = (
        "coke_capacity",
        "sinter_capacity",
        "hot_iron_capacity",
        "cold_slab_capacity",
        "pellet_capacity",
    )
    for name in required_capacity:
        if not hasattr(model, name) or not getattr(model, name).active:
            raise S44CModelBuilderError(
                f"A recoverable C0 handoff requires active {name}."
            )
    replaced: list[str] = []
    for name in (
        "coke_terminal",
        "sinter_terminal",
        "hot_iron_terminal",
        "cold_slab_terminal",
        "pellet_terminal",
    ):
        if not hasattr(model, name) or not getattr(model, name).active:
            raise S44CModelBuilderError(
                f"A recoverable C0 handoff expected active {name}."
            )
        getattr(model, name).deactivate()
        replaced.append(name)
    model.c0_inventory_terminal_policy = (
        "executed_state_with_bounded_physical_continuation_no_cyclic_tail_closure"
    )
    model.temporal_tail_handoff_policy = model.c0_inventory_terminal_policy
    model.temporal_tail_cyclic_closures_replaced = tuple(replaced)
    model.temporal_executed_handoff_index = execution_steps - 1
    model.temporal_physical_tail_steps = horizon_steps - execution_steps


def _add_final_product_requirement(
    model: ConcreteModel,
    *,
    final_product_target_t: float,
    quota_lower_bound: bool,
) -> None:
    """Add either the rolling quota lower bound or the legacy exact target."""

    total_output = sum(model.final_product_output[t] for t in model.TIME)
    model.final_product_fulfilment = Constraint(
        expr=(total_output >= final_product_target_t) if quota_lower_bound else (total_output == final_product_target_t)
    )


def _add_reference_horizon_band(
    model: ConcreteModel,
    *,
    constraint_id: str,
    expression: Any,
    band: Mapping[str, float],
) -> None:
    """Add a cumulative reference-scenario band without fixing an hourly profile."""

    required = {"lower_t", "upper_t"}
    missing = required.difference(band)
    if missing:
        raise S44CModelBuilderError(
            f"Reference band {constraint_id} is missing: {sorted(missing)}"
        )
    original_lower = float(band["lower_t"])
    original_upper = float(band["upper_t"])
    quantization_allowance = float(band.get("quantization_allowance_t", 0.0))
    lower = max(0.0, original_lower - quantization_allowance)
    upper = original_upper + quantization_allowance
    if not 0.0 <= lower <= upper:
        raise S44CModelBuilderError(
            f"Reference band {constraint_id} must satisfy 0 <= lower <= upper."
        )
    setattr(model, f"{constraint_id}_lower", Constraint(expr=expression >= lower))
    setattr(model, f"{constraint_id}_upper", Constraint(expr=expression <= upper))
    setattr(model, f"{constraint_id}_original_lower_t", original_lower)
    setattr(model, f"{constraint_id}_original_upper_t", original_upper)
    setattr(
        model,
        f"{constraint_id}_quantization_allowance_t",
        quantization_allowance,
    )
    setattr(model, f"{constraint_id}_effective_lower_t", lower)
    setattr(model, f"{constraint_id}_effective_upper_t", upper)


def _add_reference_cumulative_deadline_bands(
    model: ConcreteModel,
    *,
    constraint_prefix: str,
    hourly_expressions: Mapping[str, Any],
    bands: Mapping[str, Mapping[str, float]],
    deadline_hours: Collection[int],
    horizon_hours: int,
    explicit_deadline_bands: Mapping[
        str, Mapping[int, Mapping[str, float]]
    ] | None = None,
) -> None:
    """Scale horizon scenario bands to execution deadlines without hourly fixing."""

    deadlines = sorted({int(hour) for hour in deadline_hours})
    if not deadlines or deadlines[-1] != horizon_hours:
        raise S44CModelBuilderError(
            "Fixed-reference cumulative deadlines must include the horizon end."
        )
    if any(hour <= 0 or hour > horizon_hours for hour in deadlines):
        raise S44CModelBuilderError(
            "Fixed-reference cumulative deadlines must lie inside the horizon."
        )
    for band_id, band in bands.items():
        if band_id not in hourly_expressions:
            raise S44CModelBuilderError(
                f"Unknown fixed-reference deadline band: {band_id}"
            )
        component = hourly_expressions[band_id]
        lower = float(band["lower_t"])
        upper = float(band["upper_t"])
        quantization_allowance = float(band.get("quantization_allowance_t", 0.0))
        for deadline in deadlines:
            if explicit_deadline_bands is not None:
                try:
                    deadline_band = explicit_deadline_bands[band_id][deadline]
                    deadline_lower = float(deadline_band["lower_t"])
                    deadline_upper = float(deadline_band["upper_t"])
                    deadline_allowance = float(
                        deadline_band.get(
                            "quantization_allowance_t",
                            quantization_allowance,
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise S44CModelBuilderError(
                        "Explicit fixed-reference deadline bands are incomplete."
                    ) from exc
            else:
                scale = deadline / horizon_hours
                deadline_lower = lower * scale
                deadline_upper = upper * scale
                deadline_allowance = quantization_allowance
            deadline_lower = max(0.0, deadline_lower - deadline_allowance)
            deadline_upper += deadline_allowance
            cumulative = sum(component[t] for t in range(deadline))
            setattr(
                model,
                f"{constraint_prefix}_{band_id}_{deadline}h_lower",
                Constraint(expr=cumulative >= deadline_lower),
            )
            setattr(
                model,
                f"{constraint_prefix}_{band_id}_{deadline}h_upper",
                Constraint(expr=cumulative <= deadline_upper),
            )


def _add_day_commitment_layer(
    model: ConcreteModel,
    *,
    horizon_hours: int,
    commitment_definitions: Mapping[str, tuple[str, str, float]],
    commitment_day_lengths: Collection[int] | None = None,
    time_step_hours: float = 1.0,
) -> None:
    """Use one daily plant-commitment binary with interval throughput.

    This is a tractable development abstraction for a price-free quota model:
    it selects plant availability from physical demand without prescribing
    operating hours. Existing hourly maximum capacities remain binding.
    """
    explicit_day_lengths = commitment_day_lengths is not None
    day_lengths = (
        [int(value) for value in commitment_day_lengths]
        if explicit_day_lengths
        else [int(round(24.0 / time_step_hours))]
        * int(round(horizon_hours * time_step_hours / 24.0))
    )
    full_local_day_hours = {23.0, 24.0, 25.0}
    complete_segments = day_lengths[:-1] if explicit_day_lengths else day_lengths
    final_segment_hours = round(day_lengths[-1] * time_step_hours, 10) if day_lengths else 0.0
    if (
        not day_lengths
        or sum(day_lengths) != horizon_hours
        or any(round(value * time_step_hours, 10) not in full_local_day_hours for value in complete_segments)
        or (
            final_segment_hours not in full_local_day_hours
            and not (explicit_day_lengths and 0.0 < final_segment_hours < 23.0)
        )
    ):
        raise S44CModelBuilderError(
            "Daily commitment requires complete 23/24/25-hour local delivery days; "
            "an explicit physical-tail partition may end in one partial final day."
        )
    boundaries: list[tuple[int, int]] = []
    start = 0
    for length in day_lengths:
        boundaries.append((start, start + length))
        start += length
    hour_to_day = {
        hour: day
        for day, (day_start, day_end) in enumerate(boundaries)
        for hour in range(day_start, day_end)
    }
    model.COMMITMENT_DAY = RangeSet(0, len(day_lengths) - 1)
    model.commitment_final_segment_partial = (
        final_segment_hours not in full_local_day_hours
    )
    model.commitment_day_lengths_hours = tuple(
        float(value) * time_step_hours for value in day_lengths
    )
    for commitment_id, (activity_name, on_name, minimum_rate) in commitment_definitions.items():
        day_on_name = f"{commitment_id}_day_on"
        setattr(model, day_on_name, Var(model.COMMITMENT_DAY, domain=Binary))
        setattr(
            model,
            f"{commitment_id}_hourly_within_day",
            Constraint(
                model.TIME,
                rule=lambda m, t, on_name=on_name, day_on_name=day_on_name: getattr(m, on_name)[t]
                <= getattr(m, day_on_name)[hour_to_day[int(t)]],
            ),
        )
        setattr(
            model,
            f"{commitment_id}_daily_minimum_activity",
            Constraint(
                model.COMMITMENT_DAY,
                rule=lambda m, d, activity_name=activity_name, day_on_name=day_on_name, minimum_rate=minimum_rate:
                sum(getattr(m, activity_name)[t] for t in range(*boundaries[int(d)]))
                >= (minimum_rate / time_step_hours) * getattr(m, day_on_name)[d],
            ),
        )


def _constraint_aware_hourly_import_bounds(model: ConcreteModel) -> dict[str, Any]:
    """Tighten the completed C0 sale model and prove an hourly import bound."""

    started = time.perf_counter()
    active_constraint_families = sorted(
        {
            constraint.parent_component().name
            for constraint in model.component_data_objects(
                Constraint, active=True
            )
        }
    )
    audit: dict[str, Any] = {
        "schema_version": "steel_c0_hourly_import_bound_audit_v1",
        "status": "running",
        "derivation_method": (
            "pyomo.contrib.fbbt.fbbt.fbbt(model), followed by "
            "compute_bounds_on_expr(gross_total_electricity_mwh[t])"
        ),
        "constraint_aware_fbbt": True,
        "hourly_bounds": [],
        "unbounded_variables": [],
        "missing_constraint_families": [],
        "ineffective_constraint_families": [],
        "active_constraint_family_count": len(active_constraint_families),
        "active_constraint_families": active_constraint_families,
        "active_constraint_families_sha256": hashlib.sha256(
            json.dumps(
                active_constraint_families, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
    }
    try:
        fbbt(model)
        for t in model.TIME:
            lower, upper = compute_bounds_on_expr(
                model.gross_total_electricity_mwh[t]
            )
            finite = upper is not None and math.isfinite(float(upper))
            audit["hourly_bounds"].append(
                {
                    "hour_index": int(t),
                    "gross_consumption_lower_bound_mwh": (
                        None if lower is None else float(lower)
                    ),
                    "gross_consumption_upper_bound_mwh": (
                        None if upper is None else float(upper)
                    ),
                    "gross_grid_import_upper_bound_mwh": (
                        float(upper) if finite else None
                    ),
                    "status": "finite" if finite else "nonfinite",
                }
            )
        failed_hours = [
            row for row in audit["hourly_bounds"] if row["status"] != "finite"
        ]
        if failed_hours:
            failed_indices = {row["hour_index"] for row in failed_hours}
            unbounded: dict[str, dict[str, Any]] = {}
            for t in model.TIME:
                if int(t) not in failed_indices:
                    continue
                for variable in identify_variables(
                    model.gross_total_electricity_mwh[t], include_fixed=False
                ):
                    if variable.ub is None or not math.isfinite(float(variable.ub)):
                        unbounded[variable.name] = {
                            "name": variable.name,
                            "lower_bound": variable.lb,
                            "upper_bound": variable.ub,
                        }
            active_constraints = list(
                model.component_data_objects(Constraint, active=True)
            )
            families: set[str] = set()
            for constraint in active_constraints:
                names = {
                    variable.name
                    for variable in identify_variables(
                        constraint.body, include_fixed=False
                    )
                }
                if names.intersection(unbounded):
                    families.add(constraint.parent_component().name)
            audit["unbounded_variables"] = sorted(
                unbounded.values(), key=lambda row: row["name"]
            )
            audit["missing_constraint_families"] = (
                ["no_active_capacity_constraint_references_unbounded_consumption_variables"]
                if unbounded and not families
                else []
            )
            audit["ineffective_constraint_families"] = sorted(families)
            audit["status"] = "fail_nonfinite"
            error = S44CModelBuilderError(
                "Constraint-aware FBBT could not prove finite hourly gross-consumption "
                "bounds; no grid-capacity or guessed big-M fallback is permitted. "
                f"Unbounded variables={sorted(unbounded)}; "
                f"missing families={audit['missing_constraint_families']}; "
                f"ineffective families={audit['ineffective_constraint_families']}."
            )
            error.phase2_stage = "model_construction.constraint_aware_fbbt"
            error.bound_audit = audit
            raise error
        audit["status"] = "pass"
        return audit
    except S44CModelBuilderError:
        raise
    except Exception as exc:
        audit["status"] = "fail_fbbt_exception"
        audit["exception_type"] = type(exc).__name__
        audit["exception_message"] = str(exc)
        error = S44CModelBuilderError(
            f"Constraint-aware FBBT failed closed: {type(exc).__name__}: {exc}"
        )
        error.phase2_stage = "model_construction.constraint_aware_fbbt"
        error.bound_audit = audit
        raise error from exc
    finally:
        audit["runtime_seconds"] = time.perf_counter() - started


def _add_c0_minimal_wag_layer(
    model: ConcreteModel,
    inputs: C0ExecutableInputs | RetainedBfBofInputs,
    *,
    time_step_hours: float = 1.0,
    enable_internal_wag_power: bool = False,
    gross_electricity_rule: Any | None = None,
    development_profile: DevelopmentControllerProfile | None = None,
    enable_hsm_controller: bool = False,
    enable_pefa_controller: bool = False,
    enable_boiler_scaffold: bool = False,
    enable_generator_interface: bool = False,
    enable_electricity_boundary_controller: bool = False,
    hsm_rolling_electricity_mwh_per_t_hrc_override: float | None = None,
    retire_legacy_boiler_placeholder: bool = False,
    development_controller_profile_weights: Mapping[str, Mapping[int, float]] | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    site_baseload_ng_mwh_h: float = 0.0,
    site_residual_steam_t_h: float = 0.0,
    site_residual_direct_co2_t_h: float = 0.0,
    kgf_underfiring_activity_rule: Any | None = None,
    kgf_underfiring_activity_rule_kgf2: Any | None = None,
    hsm_carrier_precedence: Collection[str] | None = None,
    hsm_eligible_carriers: Collection[str] | None = None,
    hsm_source_mix_policy: Mapping[str, Any] | None = None,
    generator_interface_cap_mode: str = "inherited_profile",
    generator_unit_interface: Mapping[str, Any] | None = None,
    initial_vn25_output_mw: float | None = None,
    aggregate_generator_technical_interface: Mapping[str, Any] | None = None,
    full_site_energy_bridge: Mapping[str, Any] | None = None,
    eaf_secondary_electricity_mwh_per_t_ls_override: float | None = None,
    dsp_electricity_mwh_per_t_coil_override: float | None = None,
    hsm_output_activity_rule: Any | None = None,
    dsp_output_activity_rule: Any | None = None,
    bf_hot_metal_activity_rule: Any | None = None,
    bf_electricity_intensity_scale: float = 1.0,
    experimental_self_use_calibration: Mapping[str, Any] | None = None,
    experimental_process_electricity_overlay: Mapping[str, Any] | None = None,
    experimental_ng_service_calibration: Mapping[str, Any] | None = None,
    experimental_coal_wag_calibration: Mapping[str, Any] | None = None,
    electricity_sale_sensitivity: Mapping[str, Any] | None = None,
) -> None:
    lhv_mj_per_nm3, combustion_t_per_mwh = load_governed_wag_factor_maps()
    bf_hot_stove_mwh_per_t_hm = bf_hot_stove_mwh_per_t_hot_metal()
    if linde_n2_auxiliary_electricity_mwh_h < 0.0:
        raise S44CModelBuilderError("Linde N2 auxiliary electricity must be non-negative.")
    if site_background_electricity_mwh_h < 0.0:
        raise S44CModelBuilderError("Site background electricity must be non-negative.")
    if site_baseload_ng_mwh_h < 0.0:
        raise S44CModelBuilderError("Site baseload NG must be non-negative.")
    if site_residual_steam_t_h < 0.0:
        raise S44CModelBuilderError("Site residual steam demand must be non-negative.")
    if site_residual_direct_co2_t_h < 0.0:
        raise S44CModelBuilderError("Site residual direct CO2 must be non-negative.")
    if eaf_secondary_electricity_mwh_per_t_ls_override is not None and eaf_secondary_electricity_mwh_per_t_ls_override < 0.0:
        raise S44CModelBuilderError("EAF secondary-electricity override must be non-negative.")
    if dsp_electricity_mwh_per_t_coil_override is not None and dsp_electricity_mwh_per_t_coil_override < 0.0:
        raise S44CModelBuilderError("DSP electricity override must be non-negative.")
    if bf_electricity_intensity_scale <= 0.0:
        raise S44CModelBuilderError("BF electricity-intensity scale must be positive.")
    calibration = dict(experimental_self_use_calibration or {})
    electricity_overlay = dict(experimental_process_electricity_overlay or {})
    ng_service_calibration = dict(experimental_ng_service_calibration or {})
    coal_wag_calibration = dict(experimental_coal_wag_calibration or {})
    if electricity_overlay and (
        electricity_overlay.get("classification")
        != "experimental_proportional_process_electricity_not_source_proven"
        or float(electricity_overlay.get("mwh_per_t_activity", -1.0)) < 0.0
    ):
        raise S44CModelBuilderError("Invalid experimental process-electricity overlay.")
    if calibration:
        required_calibration = {
            "classification",
            "additional_cog_mwh_per_t_kgf_activity",
            "additional_cog_mwh_per_t_sinter",
            "additional_bofg_mwh_per_t_pellet",
        }
        missing_calibration = required_calibration.difference(calibration)
        if missing_calibration:
            raise S44CModelBuilderError(
                f"Experimental self-use calibration is missing: {sorted(missing_calibration)}"
            )
        if calibration["classification"] != "experimental_carrier_self_use_calibration_not_source_proven":
            raise S44CModelBuilderError("Unexpected experimental self-use classification.")
        if any(float(calibration[key]) < 0.0 for key in required_calibration - {"classification"}):
            raise S44CModelBuilderError("Experimental self-use coefficients must be non-negative.")
    if ng_service_calibration:
        required_ng_service = {
            "classification",
            "ironmaking_target_pj_y",
            "ironmaking_basis_t_y",
            "downstream_target_pj_y",
            "downstream_basis_t_y",
        }
        missing_ng_service = required_ng_service.difference(ng_service_calibration)
        if missing_ng_service:
            raise S44CModelBuilderError(
                f"Experimental NG service calibration is missing: {sorted(missing_ng_service)}"
            )
        if ng_service_calibration["classification"] != (
            "user_authorized_c1_origin_explicit_ng_service_calibration"
        ):
            raise S44CModelBuilderError("Unexpected experimental NG service classification.")
        if any(
            float(ng_service_calibration[key]) <= 0.0
            for key in required_ng_service - {"classification"}
        ):
            raise S44CModelBuilderError(
                "Experimental NG service targets and production bases must be positive."
            )
    if coal_wag_calibration:
        required_coal_wag = {
            "classification",
            "coal_procurement_multiplier",
            "bfg_mwh_per_t_hot_metal",
            "cog_mwh_per_t_kgf_activity",
            "bofg_mwh_per_t_bof_steel",
            "cog_self_use_scale",
        }
        missing_coal_wag = required_coal_wag.difference(coal_wag_calibration)
        if missing_coal_wag:
            raise S44CModelBuilderError(
                f"Experimental coal/WAG calibration is missing: {sorted(missing_coal_wag)}"
            )
        if coal_wag_calibration["classification"] != (
            "user_authorized_c1_coal_completion_carrier_wag_calibration"
        ):
            raise S44CModelBuilderError("Unexpected coal/WAG calibration classification.")
        if float(coal_wag_calibration["coal_procurement_multiplier"]) < 1.0:
            raise S44CModelBuilderError("Coal completion may not reduce represented procurement.")
        if any(
            float(coal_wag_calibration[key]) <= 0.0
            for key in required_coal_wag
            - {"classification", "coal_procurement_multiplier"}
        ):
            raise S44CModelBuilderError("Carrier-specific WAG intensities must be positive.")

    # Every eligible carrier stays separately balanced.  The active HSM
    # development controller defaults to the source-backed QRA COG/NG
    # composition; an explicit empty mapping retains the historical broad-fuel
    # allocation for labelled diagnostics only.
    supported_hsm_carriers = ("BFG", "COG", "BOFG", "NG")
    if (
        hsm_source_mix_policy is None
        and enable_hsm_controller
        and development_profile is not None
    ):
        if development_profile.configuration_id == "C0_current_BF_BOF_reference":
            source_mix = {
                "basis": "qra_reference_volumetric_design_flow_45_ng_55_cog",
                "ng_volume_fraction": 0.45,
                "cog_volume_fraction": 0.55,
                "ng_lhv_mj_per_nm3": 37.5,
                "cog_lhv_mj_per_nm3": 18.5,
                "block_hours": 24,
                "energy_share_tolerance_fraction": 0.0,
                "displace_from_c0_fixed_ng_bridge": full_site_energy_bridge is not None,
            }
        elif development_profile.configuration_id == "C1_phase1_BF_BOF_plus_DRP_EAF":
            source_mix = {
                "basis": "qra_heracless_volumetric_design_flow_80_ng_20_cog",
                "ng_volume_fraction": 0.80,
                "cog_volume_fraction": 0.20,
                "ng_lhv_mj_per_nm3": 37.5,
                "cog_lhv_mj_per_nm3": 18.5,
                "block_hours": 24,
                "energy_share_tolerance_fraction": 0.0,
                "displace_from_c0_fixed_ng_bridge": False,
            }
        else:
            raise S44CModelBuilderError(
                "No default HSM QRA source-mixture policy exists for "
                f"{development_profile.configuration_id!r}."
            )
    else:
        source_mix = dict(hsm_source_mix_policy or {})
    if source_mix and not enable_hsm_controller:
        raise S44CModelBuilderError(
            "An HSM source-mixture policy requires the active HSM controller."
        )
    allowed_hsm_carriers = tuple(
        hsm_eligible_carriers
        or (("COG", "NG") if source_mix else supported_hsm_carriers)
    )
    if not allowed_hsm_carriers or len(allowed_hsm_carriers) != len(set(allowed_hsm_carriers)) or not set(allowed_hsm_carriers).issubset(supported_hsm_carriers):
        raise S44CModelBuilderError(
            "HSM eligible carriers must be a non-empty unique subset of BFG, COG, BOFG and NG."
        )
    hsm_precedence = tuple(hsm_carrier_precedence or allowed_hsm_carriers)
    if len(hsm_precedence) != len(allowed_hsm_carriers) or set(hsm_precedence) != set(allowed_hsm_carriers):
        raise S44CModelBuilderError(
            "HSM carrier precedence must contain every eligible HSM carrier exactly once."
        )
    if generator_interface_cap_mode not in {"inherited_profile", "volume_envelope_only"}:
        raise S44CModelBuilderError(
            "Generator interface cap mode must be inherited_profile or volume_envelope_only."
        )
    hsm_precedence_penalty = {
        carrier: (0.0 if carrier not in hsm_precedence else 10.0 ** (-8 + hsm_precedence.index(carrier)))
        for carrier in supported_hsm_carriers
    }
    model.hsm_carrier_precedence = hsm_precedence
    model.hsm_eligible_carriers = allowed_hsm_carriers
    if source_mix:
        required_mix_keys = {
            "ng_volume_fraction",
            "cog_volume_fraction",
            "ng_lhv_mj_per_nm3",
            "cog_lhv_mj_per_nm3",
            "block_hours",
        }
        missing_mix_keys = required_mix_keys.difference(source_mix)
        if missing_mix_keys:
            raise S44CModelBuilderError(
                f"HSM source-mixture policy is missing: {sorted(missing_mix_keys)}"
            )
        if set(allowed_hsm_carriers) != {"COG", "NG"}:
            raise S44CModelBuilderError(
                "The source-backed HSM mixture permits exactly COG and NG."
            )
        ng_volume_fraction = float(source_mix["ng_volume_fraction"])
        cog_volume_fraction = float(source_mix["cog_volume_fraction"])
        ng_lhv_mj_per_nm3 = float(source_mix["ng_lhv_mj_per_nm3"])
        cog_lhv_mj_per_nm3 = float(source_mix["cog_lhv_mj_per_nm3"])
        hsm_mix_block_hours = int(source_mix["block_hours"])
        hsm_mix_tolerance = float(
            source_mix.get("energy_share_tolerance_fraction", 0.0)
        )
        if (
            ng_volume_fraction <= 0.0
            or cog_volume_fraction <= 0.0
            or abs(ng_volume_fraction + cog_volume_fraction - 1.0) > 1e-9
        ):
            raise S44CModelBuilderError(
                "HSM COG/NG volumetric fractions must be positive and sum to one."
            )
        if ng_lhv_mj_per_nm3 <= 0.0 or cog_lhv_mj_per_nm3 <= 0.0:
            raise S44CModelBuilderError("HSM COG/NG LHVs must be positive.")
        if hsm_mix_block_hours <= 0:
            raise S44CModelBuilderError("HSM mixture block hours must be positive.")
        if not 0.0 <= hsm_mix_tolerance < 0.5:
            raise S44CModelBuilderError(
                "HSM mixture energy-share tolerance must lie in [0, 0.5)."
            )
        hsm_ng_energy_share = (
            ng_volume_fraction * ng_lhv_mj_per_nm3
            / (
                ng_volume_fraction * ng_lhv_mj_per_nm3
                + cog_volume_fraction * cog_lhv_mj_per_nm3
            )
        )
    else:
        hsm_mix_block_hours = 0
        hsm_mix_tolerance = 0.0
        hsm_ng_energy_share = 0.0
    model.hsm_source_mix_policy_active = bool(source_mix)
    model.hsm_source_mix_basis = str(source_mix.get("basis", "inactive"))
    model.hsm_ng_energy_share_target = hsm_ng_energy_share
    model.hsm_source_mix_block_hours = hsm_mix_block_hours
    model.generator_interface_cap_mode = generator_interface_cap_mode
    model.generator_unit_interface_active = generator_unit_interface is not None
    hsm_output_activity = hsm_output_activity_rule or (lambda m, t: m.hot_strip_mill[t])
    dsp_output_activity = dsp_output_activity_rule or (lambda m, t: m.dsp_final_product_output[t])
    bf_hot_metal_activity = bf_hot_metal_activity_rule or (lambda m, t: m.bf6_hot_iron_output[t])
    overlay_coefficient = float(electricity_overlay.get("mwh_per_t_activity", 0.0))
    model.experimental_process_electricity_overlay_mwh = Expression(
        model.TIME,
        rule=lambda m, t: overlay_coefficient * (
            m.coking_plant_1[t] + m.sinter_output[t] + bf_hot_metal_activity(m, t)
            + m.bof_crude_steel_output[t]
            + (
                m.pefa_pellet_output_t[t]
                if hasattr(m, "pefa_pellet_output_t")
                else (
                    development_profile.pefa_pellets_t_h * time_step_hours
                    if development_profile is not None
                    else 0.0
                )
            )
            + hsm_output_activity(m, t) + dsp_output_activity(m, t)
        ),
    )

    def _controller_profile_weight(controller_key: str, t: int) -> float:
        """Return an optional fixed diagnostic timing weight for one demand row.

        The default is one, preserving the accepted continuous annual-average
        controller profile.  Callers may supply only precomputed, non-negative
        weights for a fixed-schedule diagnostic; this helper never derives a
        gas mix, a WAG/NG ratio, or a new allocation rule.
        """

        if development_controller_profile_weights is None:
            return 1.0
        controller_weights = development_controller_profile_weights.get(controller_key)
        if controller_weights is None:
            return 1.0
        if int(t) not in controller_weights:
            raise S44CModelBuilderError(
                f"Missing representative-profile weight for {controller_key} at hour {int(t)}."
            )
        weight = float(controller_weights[int(t)])
        if weight < 0.0:
            raise S44CModelBuilderError(
                f"Representative-profile weight for {controller_key} at hour {int(t)} must be non-negative."
            )
        return weight
    bfg_mwh_per_t_hot_metal = float(
        coal_wag_calibration.get(
            "bfg_mwh_per_t_hot_metal", inputs.bfg_mwh_per_t_hot_iron
        )
    )
    cog_mwh_per_t_kgf_activity = float(
        coal_wag_calibration.get(
            "cog_mwh_per_t_kgf_activity", inputs.cog_mwh_per_t_coke
        )
    )
    bofg_mwh_per_t_bof_steel = float(
        coal_wag_calibration.get(
            "bofg_mwh_per_t_bof_steel", inputs.bofg_mwh_per_t_liquid_steel
        )
    )
    model.bfg_prod_bf6 = Expression(
        model.TIME,
        rule=lambda m, t: bfg_mwh_per_t_hot_metal * m.bf6_hot_iron_output[t],
    )
    model.bfg_prod_bf7 = Expression(
        model.TIME,
        rule=lambda m, t: bfg_mwh_per_t_hot_metal * m.bf7_hot_iron_output[t],
    )
    model.bfg_generated = Expression(model.TIME, rule=lambda m, t: m.bfg_prod_bf6[t] + m.bfg_prod_bf7[t])
    model.cog_prod_kgf1 = Expression(
        model.TIME,
        rule=lambda m, t: cog_mwh_per_t_kgf_activity * m.coking_plant_1[t],
    )
    model.cog_prod_kgf2 = Expression(
        model.TIME,
        rule=lambda m, t: cog_mwh_per_t_kgf_activity * m.coking_plant_2[t],
    )
    model.cog_generated = Expression(model.TIME, rule=lambda m, t: m.cog_prod_kgf1[t] + m.cog_prod_kgf2[t])
    model.bofg_prod_bof = Expression(
        model.TIME,
        rule=lambda m, t: bofg_mwh_per_t_bof_steel * m.bof_crude_steel_output[t],
    )
    model.bofg_generated = Expression(model.TIME, rule=lambda m, t: m.bofg_prod_bof[t])

    # The user-approved C0/C1 development contract treats hot-blast heat as a
    # separate BFG-first controller, never as direct gas injection into the BF
    # reactor.  BFG generation is production-coupled and exceeds this demand
    # under the selected coefficient set, so no fallback fuel is silently
    # activated in this first integration.
    model.bfg_to_bf_hot_stove = Expression(
        model.TIME,
        rule=lambda m, t: bf_hot_stove_mwh_per_t_hm * (m.bf6_hot_iron_output[t] + m.bf7_hot_iron_output[t]),
    )


    model.bfg_to_kgf1 = Expression(
        model.TIME,
        rule=lambda _m, _t: 0.0,
    )
    # C0 retains the historical coking-input basis.  The reconciled C1 chain
    # supplies an explicit coke-output expression, because KGF underfiring is
    # specified per tonne of coke whereas its production activity is dry coal.
    # This changes only the KGF COG self-use sink; COG generation remains on
    # its separately governed dry-coal activity basis.
    kgf_underfiring_activity = (
        kgf_underfiring_activity_rule
        if kgf_underfiring_activity_rule is not None
        else lambda m, t: m.coking_plant_1[t]
    )
    kgf2_underfiring_activity = (
        kgf_underfiring_activity_rule_kgf2
        if kgf_underfiring_activity_rule_kgf2 is not None
        else lambda m, t: m.coking_plant_2[t]
    )
    model.cog_to_kgf1 = Expression(
        model.TIME,
        rule=lambda m, t: (
            float(coal_wag_calibration.get("cog_self_use_scale", 1.0))
            * (
                inputs.kgf_underfiring_mwh_per_t_coke
                + float(calibration.get("additional_cog_mwh_per_t_kgf_activity", 0.0))
            )
        ) * kgf_underfiring_activity(m, t),
    )
    model.cog_to_kgf2 = Expression(
        model.TIME,
        rule=lambda m, t: inputs.kgf_underfiring_mwh_per_t_coke * kgf2_underfiring_activity(m, t),
    )
    model.cog_to_sinter = Expression(
        model.TIME,
        rule=lambda m, t: (
            float(coal_wag_calibration.get("cog_self_use_scale", 1.0))
            * (
                inputs.sinter_cog_mwh_per_t_sinter
                + float(calibration.get("additional_cog_mwh_per_t_sinter", 0.0))
            )
        ) * m.sinter_output[t],
    )

    if (enable_hsm_controller or enable_pefa_controller or enable_boiler_scaffold or enable_generator_interface or enable_electricity_boundary_controller) and development_profile is None:
        raise S44CModelBuilderError("An activated development controller requires its read-only C5 profile.")

    if enable_hsm_controller:
        model.hsm_reheat_demand_mwh = Expression(
            model.TIME,
            rule=lambda m, t: hsm_reheat_mwh_per_t_hrc() * hsm_output_activity(m, t),
        )
        model.bfg_to_hsm = Var(model.TIME, domain=NonNegativeReals)
        model.cog_to_hsm = Var(model.TIME, domain=NonNegativeReals)
        model.bofg_to_hsm = Var(model.TIME, domain=NonNegativeReals)
        model.ng_to_hsm_mwh = Var(model.TIME, domain=NonNegativeReals)
        for carrier, variable_name in {
            "BFG": "bfg_to_hsm",
            "COG": "cog_to_hsm",
            "BOFG": "bofg_to_hsm",
            "NG": "ng_to_hsm_mwh",
        }.items():
            if carrier not in allowed_hsm_carriers:
                for t in model.TIME:
                    getattr(model, variable_name)[t].fix(0.0)
        model.hsm_reheat_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.bfg_to_hsm[t] + m.cog_to_hsm[t] + m.bofg_to_hsm[t] + m.ng_to_hsm_mwh[t]
            == m.hsm_reheat_demand_mwh[t],
        )
        model.hsm_source_mix_constraints = ConstraintList()
        if source_mix:
            lower_share = max(0.0, hsm_ng_energy_share - hsm_mix_tolerance)
            upper_share = min(1.0, hsm_ng_energy_share + hsm_mix_tolerance)
            complete_block_starts = tuple(
                start
                for start in range(0, len(model.TIME), hsm_mix_block_hours)
                if start + hsm_mix_block_hours <= len(model.TIME)
            )
            # A short smoke horizon is constrained as one aggregate block. In
            # rolling runs, an incomplete forecast tail is deliberately left
            # unconstrained; it must never collapse the QRA share into an
            # accidental one-hour composition requirement.
            block_starts = complete_block_starts or (0,)
            for start in block_starts:
                hours = range(
                    start,
                    min(start + hsm_mix_block_hours, len(model.TIME)),
                )
                block_ng = sum(model.ng_to_hsm_mwh[t] for t in hours)
                block_heat = sum(model.hsm_reheat_demand_mwh[t] for t in hours)
                model.hsm_source_mix_constraints.add(block_ng >= lower_share * block_heat)
                model.hsm_source_mix_constraints.add(block_ng <= upper_share * block_heat)
        model.hsm_carrier_precedence_penalty = Expression(
            model.TIME,
            rule=lambda m, t: (
                hsm_precedence_penalty["BFG"] * m.bfg_to_hsm[t]
                + hsm_precedence_penalty["COG"] * m.cog_to_hsm[t]
                + hsm_precedence_penalty["BOFG"] * m.bofg_to_hsm[t]
                + hsm_precedence_penalty["NG"] * m.ng_to_hsm_mwh[t]
            ),
        )
    else:
        model.hsm_reheat_demand_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bfg_to_hsm = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.cog_to_hsm = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bofg_to_hsm = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_to_hsm_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.hsm_carrier_precedence_penalty = Expression(model.TIME, rule=lambda _m, _t: 0.0)

    # C5n_a resolves the total PEFA-gas controller without inventing a fixed
    # stage-intensity split.  These are its accepted continuous output rows.
    if enable_pefa_controller:
        if not hasattr(model, "pefa_pellet_output_t"):
            model.pefa_pellet_output_t = Expression(
                model.TIME,
                rule=lambda _m, _t: development_profile.pefa_pellets_t_h
                * time_step_hours,
            )
        pefa_bofg_mwh_per_t = (
            development_profile.pefa_bofg_mwh_h
            / development_profile.pefa_pellets_t_h
        )
        pefa_cog_mwh_per_t = (
            development_profile.pefa_cog_mwh_h
            / development_profile.pefa_pellets_t_h
        )
        model.bofg_to_pefa_malerij = Var(model.TIME, domain=NonNegativeReals)
        model.cog_to_pefa_branderij = Var(model.TIME, domain=NonNegativeReals)
        model.ng_to_pefa_malerij_mwh = Var(model.TIME, domain=NonNegativeReals)
        model.ng_to_pefa_branderij_mwh = Var(model.TIME, domain=NonNegativeReals)
        model.pefa_malerij_heat_balance = Constraint(
            model.TIME,
            rule=lambda m, t: (
                m.bofg_to_pefa_malerij[t] + m.ng_to_pefa_malerij_mwh[t]
                == pefa_bofg_mwh_per_t
                * m.pefa_pellet_output_t[t]
                * _controller_profile_weight("pefa_bofg", int(t))
                + float(calibration.get("additional_bofg_mwh_per_t_pellet", 0.0))
                * m.pefa_pellet_output_t[t]
            ),
        )
        model.pefa_branderij_heat_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.cog_to_pefa_branderij[t] + m.ng_to_pefa_branderij_mwh[t]
            == pefa_cog_mwh_per_t
            * m.pefa_pellet_output_t[t]
            * _controller_profile_weight("pefa_cog", int(t)),
        )
    else:
        if not hasattr(model, "pefa_pellet_output_t"):
            model.pefa_pellet_output_t = Expression(
                model.TIME, rule=lambda _m, _t: 0.0
            )
        model.bofg_to_pefa_malerij = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.cog_to_pefa_branderij = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_to_pefa_malerij_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_to_pefa_branderij_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)

    if enable_boiler_scaffold:
        # The explicit demand remains source-stage fixed. Phase 5H may add a
        # constant residual demand, but only through this existing
        # instantaneous WAG/NG boiler interface. No capacity-derived demand,
        # storage, startup state or steam quality conversion is introduced.
        model.bfg_to_boiler = Var(model.TIME, domain=NonNegativeReals)
        model.cog_to_boiler = Var(model.TIME, domain=NonNegativeReals)
        model.ng_to_boiler_mwh = Var(model.TIME, domain=NonNegativeReals)
        model.boiler_scaffold_fuel_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.bfg_to_boiler[t] + m.cog_to_boiler[t] + m.ng_to_boiler_mwh[t]
            == development_profile.boiler_fuel_mwh_h * time_step_hours
            + site_residual_steam_t_h
            * development_profile.boiler_fuel_mwh_per_t_steam,
        )
        model.steam_15bar_explicit_demand_t = Expression(
            model.TIME,
            rule=lambda _m, _t: development_profile.boiler_steam_15bar_demand_t_h
            * time_step_hours,
        )
        model.residual_steam_15bar_demand_t = Expression(
            model.TIME, rule=lambda _m, _t: site_residual_steam_t_h
        )
        model.steam_15bar_demand_t = Expression(
            model.TIME,
            rule=lambda m, t: m.steam_15bar_explicit_demand_t[t]
            + m.residual_steam_15bar_demand_t[t],
        )
        model.steam_15bar_supply_t = Expression(
            model.TIME,
            rule=lambda m, t: (
                m.bfg_to_boiler[t] + m.cog_to_boiler[t] + m.ng_to_boiler_mwh[t]
            ) / development_profile.boiler_fuel_mwh_per_t_steam,
        )
        model.steam_15bar_existing_demand_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.steam_15bar_supply_t[t] == m.steam_15bar_demand_t[t],
        )
        model.steam_15bar_unserved_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.wag_boiler_steam_supply_t = Expression(
            model.TIME,
            rule=lambda m, t: (m.bfg_to_boiler[t] + m.cog_to_boiler[t])
            / development_profile.boiler_fuel_mwh_per_t_steam,
        )
        model.ng_boiler_steam_supply_t = Expression(
            model.TIME,
            rule=lambda m, t: m.ng_to_boiler_mwh[t]
            / development_profile.boiler_fuel_mwh_per_t_steam,
        )
        model.recovered_steam_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.external_steam_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_spill_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    elif retire_legacy_boiler_placeholder:
        model.bfg_to_boiler = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.cog_to_boiler = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_to_boiler_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_explicit_demand_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.residual_steam_15bar_demand_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_demand_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_unserved_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.wag_boiler_steam_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_boiler_steam_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.recovered_steam_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.external_steam_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_spill_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    else:
        model.bfg_to_boiler = Var(model.TIME, domain=NonNegativeReals)
        model.cog_to_boiler = Var(model.TIME, domain=NonNegativeReals)
        model.ng_to_boiler_mwh = Var(model.TIME, domain=NonNegativeReals)
        model.steam_15bar_explicit_demand_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.residual_steam_15bar_demand_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_demand_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_unserved_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.wag_boiler_steam_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_boiler_steam_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.recovered_steam_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.external_steam_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_spill_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)

    # These existing controller-electricity expressions are declared before
    # gross electricity because an opt-in C1 gross-load rule may reference
    # them.  They remain zero unless their respective controller is active.
    if hsm_rolling_electricity_mwh_per_t_hrc_override is not None and hsm_rolling_electricity_mwh_per_t_hrc_override <= 0.0:
        raise S44CModelBuilderError("HSM rolling-electricity override must be positive when supplied.")
    hsm_rolling_electricity_coefficient = (
        hsm_rolling_electricity_mwh_per_t_hrc_override
        if hsm_rolling_electricity_mwh_per_t_hrc_override is not None
        else hsm_rolling_electricity_mwh_per_t_hrc()
    )
    model.hsm_rolling_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: hsm_rolling_electricity_coefficient * hsm_output_activity(m, t)
        if enable_hsm_controller
        else 0.0,
    )
    model.pefa_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: (
            0.0213 * m.pefa_pellet_output_t[t]
            if enable_pefa_controller
            else 0.0
        ),
    )
    model.development_controller_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: m.hsm_rolling_electricity_mwh[t] + m.pefa_electricity_mwh[t],
    )
    if enable_electricity_boundary_controller:
        dsp_electricity_coefficient = (
            dsp_electricity_mwh_per_t_coil_override
            if dsp_electricity_mwh_per_t_coil_override is not None
            else development_profile.dsp_electricity_mwh_per_t_coil
        )
        # These are explicitly source-traceable development electricity rows
        # with activity drivers already present in the C1 retained-route model.
        # They make represented loads visible; they are not a residual site
        # electricity plug and do not introduce any WAG/NG allocation.
        model.bof_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: development_profile.bof_electricity_mwh_per_t_ls * m.bof_crude_steel_output[t],
        )
        model.bf_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: bf_electricity_intensity_scale
            * development_profile.bf_electricity_mwh_per_t_hot_metal
            * bf_hot_metal_activity(m, t),
        )
        model.kgf_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: development_profile.kgf_electricity_mwh_per_t_coke * m.coke_output[t],
        )
        model.dsp_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: dsp_electricity_coefficient * dsp_output_activity(m, t),
        )
        model.eaf_secondary_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: (
                eaf_secondary_electricity_mwh_per_t_ls_override * m.eaf_liquid_steel_output[t]
                if eaf_secondary_electricity_mwh_per_t_ls_override is not None
                else 0.0
            ),
        )
        model.eaf_total_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: (
                m.eaf_arc_electricity_mwh[t]
                if hasattr(m, "eaf_arc_electricity_mwh")
                else 0.0
            )
            + m.eaf_secondary_electricity_mwh[t]
            + (
                m.eaf_cold_dri_reheat_electricity_mwh[t]
                if hasattr(m, "eaf_cold_dri_reheat_electricity_mwh")
                else 0.0
            ),
        )
        model.bof_oxygen_development_t = Expression(
            model.TIME,
            rule=lambda m, t: development_profile.bof_oxygen_t_per_t_ls * m.bof_crude_steel_output[t],
        )
        model.bf_oxygen_development_t = Expression(
            model.TIME,
            rule=lambda m, t: development_profile.bf_oxygen_t_per_t_hot_metal * bf_hot_metal_activity(m, t),
        )
        model.represented_oxygen_t = Expression(
            model.TIME,
            rule=lambda m, t: (
                m.oxygen_t[t] if hasattr(m, "oxygen_t") else 0.0
            )
            + m.bof_oxygen_development_t[t]
            + m.bf_oxygen_development_t[t],
        )
        model.asu_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: development_profile.asu_electricity_mwh_per_t_o2 * m.represented_oxygen_t[t],
        )
        # The Linde auxiliary/N2 load is deliberately separate from the
        # oxygen-specific ASU intensity.  It is an explicit site-context
        # electricity load, not an oxygen demand, residual plug, fuel sink or
        # flexibility resource.  Callers opt in with a source-carded value.
        model.linde_n2_auxiliary_electricity_mwh = Expression(
            model.TIME,
            rule=lambda _m, _t: linde_n2_auxiliary_electricity_mwh_h,
        )
        model.linde_total_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.asu_electricity_mwh[t] + m.linde_n2_auxiliary_electricity_mwh[t],
        )
        model.sinter_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: development_profile.sinter_electricity_mwh_per_t_sinter * m.sinter_output[t],
        )
        model.electricity_boundary_development_mwh = Expression(
            model.TIME,
            rule=lambda m, t: (
                m.bof_electricity_mwh[t]
                + m.bf_electricity_mwh[t]
                + m.kgf_electricity_mwh[t]
                + m.dsp_electricity_mwh[t]
                + m.linde_total_electricity_mwh[t]
                + m.sinter_electricity_mwh[t]
                + m.eaf_secondary_electricity_mwh[t]
            ),
        )
    else:
        model.bof_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bf_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.kgf_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.dsp_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.eaf_secondary_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        # The shared reporting layer also builds C0, which deliberately has
        # no EAF arc component.  Report an explicit zero instead of reaching
        # across configurations or constructing a residual electricity load.
        model.eaf_total_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: (
                m.eaf_arc_electricity_mwh[t]
                if hasattr(m, "eaf_arc_electricity_mwh")
                else 0.0
            )
            + (
                m.eaf_cold_dri_reheat_electricity_mwh[t]
                if hasattr(m, "eaf_cold_dri_reheat_electricity_mwh")
                else 0.0
            ),
        )
        model.asu_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.linde_n2_auxiliary_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.linde_total_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.sinter_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bof_oxygen_development_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bf_oxygen_development_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        # C0 has no executable oxygen-demand variable in the current physical
        # boundary.  Keep that absent demand at zero for reporting instead of
        # failing construction or introducing an implicit oxygen residual.
        model.represented_oxygen_t = Expression(
            model.TIME,
            rule=lambda m, t: m.oxygen_t[t] if hasattr(m, "oxygen_t") else 0.0,
        )
        model.electricity_boundary_development_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)

    bridge = dict(full_site_energy_bridge or {})
    if bridge:
        required_bridge_keys = {
            "fixed_full_site_ng_component_mwh_h",
            "flexible_other_site_heat_service_envelope_mwh_h",
            "normal_case_flexible_ng_validation_reference_mwh_h",
        }
        missing_bridge_keys = required_bridge_keys.difference(bridge)
        if missing_bridge_keys:
            raise S44CModelBuilderError(
                f"Full-site energy bridge is missing: {sorted(missing_bridge_keys)}"
            )
        fixed_ng_mwh_h = float(bridge["fixed_full_site_ng_component_mwh_h"])
        flexible_heat_service_mwh_h = float(
            bridge["flexible_other_site_heat_service_envelope_mwh_h"]
        )
        normal_case_flexible_ng_reference_mwh_h = float(
            bridge["normal_case_flexible_ng_validation_reference_mwh_h"]
        )
        flexible_ng_allocation_policy = str(
            bridge.get("flexible_ng_allocation_policy", "dispatch_endogenous")
        )
        if flexible_ng_allocation_policy not in {
            "dispatch_endogenous",
            "normal_case_reference_exact_hourly",
        }:
            raise S44CModelBuilderError(
                "Unsupported flexible-heat NG allocation policy: "
                f"{flexible_ng_allocation_policy}"
            )
        if fixed_ng_mwh_h <= 0.0:
            raise S44CModelBuilderError(
                "The net fixed full-site NG component must remain positive when enabled."
            )
        if not 0.0 <= normal_case_flexible_ng_reference_mwh_h <= flexible_heat_service_mwh_h:
            raise S44CModelBuilderError(
                "The normal-case flexible NG reference must lie inside the flexible heat service envelope."
            )
        model.bfg_to_flexible_other_site_heat = Var(model.TIME, domain=NonNegativeReals)
        model.cog_to_flexible_other_site_heat = Var(model.TIME, domain=NonNegativeReals)
        model.bofg_to_flexible_other_site_heat = Var(model.TIME, domain=NonNegativeReals)
        model.flexible_other_site_heat_ng_mwh = Var(model.TIME, domain=NonNegativeReals)
        model.flexible_other_site_heat_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.bfg_to_flexible_other_site_heat[t]
            + m.cog_to_flexible_other_site_heat[t]
            + m.bofg_to_flexible_other_site_heat[t]
            + m.flexible_other_site_heat_ng_mwh[t]
            == flexible_heat_service_mwh_h,
        )
        model.flexible_other_site_heat_ng_envelope = Constraint(
            model.TIME,
            rule=lambda m, t: m.flexible_other_site_heat_ng_mwh[t]
            <= flexible_heat_service_mwh_h,
        )
        if flexible_ng_allocation_policy == "normal_case_reference_exact_hourly":
            model.flexible_other_site_heat_ng_source_emulation = Constraint(
                model.TIME,
                rule=lambda m, t: m.flexible_other_site_heat_ng_mwh[t]
                == normal_case_flexible_ng_reference_mwh_h,
            )
    else:
        fixed_ng_mwh_h = 0.0
        flexible_heat_service_mwh_h = 0.0
        normal_case_flexible_ng_reference_mwh_h = 0.0
        flexible_ng_allocation_policy = "inactive"
        model.bfg_to_flexible_other_site_heat = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.cog_to_flexible_other_site_heat = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bofg_to_flexible_other_site_heat = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.flexible_other_site_heat_ng_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    reclassify_hsm_ng = bool(
        source_mix.get("displace_from_c0_fixed_ng_bridge", False)
    )
    if reclassify_hsm_ng and not bridge:
        raise S44CModelBuilderError(
            "HSM NG can only displace an enabled C0 fixed-NG bridge."
        )
    model.full_site_fixed_ng_component_gross_mwh = Expression(
        model.TIME, rule=lambda _m, _t: fixed_ng_mwh_h
    )
    model.hsm_ng_reclassified_from_fixed_bridge_mwh = Expression(
        model.TIME,
        rule=lambda m, t: m.ng_to_hsm_mwh[t] if reclassify_hsm_ng else 0.0,
    )
    model.full_site_fixed_ng_component_mwh = Expression(
        model.TIME,
        rule=lambda m, t: m.full_site_fixed_ng_component_gross_mwh[t]
        - m.hsm_ng_reclassified_from_fixed_bridge_mwh[t],
    )
    model.full_site_fixed_ng_component_nonnegative = Constraint(
        model.TIME,
        rule=lambda m, t: m.full_site_fixed_ng_component_mwh[t] >= 0.0,
    )
    model.hsm_ng_displaces_fixed_bridge = reclassify_hsm_ng
    model.flexible_other_site_heat_service_envelope_mwh = Expression(
        model.TIME, rule=lambda _m, _t: flexible_heat_service_mwh_h
    )
    model.normal_case_flexible_ng_validation_reference_mwh = Expression(
        model.TIME, rule=lambda _m, _t: normal_case_flexible_ng_reference_mwh_h
    )
    model.full_site_energy_bridge_named_ng_mwh = Expression(
        model.TIME,
        rule=lambda m, t: m.full_site_fixed_ng_component_mwh[t]
        + m.flexible_other_site_heat_ng_mwh[t],
    )
    model.site_baseload_ng_mwh = Expression(
        model.TIME, rule=lambda _m, _t: site_baseload_ng_mwh_h
    )
    ng_service_active = bool(ng_service_calibration)
    ironmaking_ng_mwh_per_t = (
        float(ng_service_calibration.get("ironmaking_target_pj_y", 0.0))
        * 1_000_000.0
        / 3.6
        / float(ng_service_calibration.get("ironmaking_basis_t_y", 1.0))
    )
    downstream_ng_mwh_per_t = (
        float(ng_service_calibration.get("downstream_target_pj_y", 0.0))
        * 1_000_000.0
        / 3.6
        / float(ng_service_calibration.get("downstream_basis_t_y", 1.0))
    )
    model.c1_existing_ironmaking_ng_service_mwh = Expression(
        model.TIME,
        rule=lambda m, t: (
            ironmaking_ng_mwh_per_t * bf_hot_metal_activity(m, t)
            if ng_service_active
            else 0.0
        ),
    )
    model.c1_existing_downstream_ng_service_mwh = Expression(
        model.TIME,
        rule=lambda m, t: (
            downstream_ng_mwh_per_t
            * (hsm_output_activity(m, t) + dsp_output_activity(m, t))
            if ng_service_active
            else 0.0
        ),
    )
    model.c1_explicit_downstream_named_ng_mwh = Expression(
        model.TIME,
        rule=lambda m, t: (
            m.ng_to_hsm_mwh[t]
            + m.ng_to_pefa_malerij_mwh[t]
            + m.ng_to_pefa_branderij_mwh[t]
            + m.ng_to_boiler_mwh[t]
        ),
    )
    if ng_service_active:
        model.c1_downstream_ng_service_covers_explicit_flows = Constraint(
            model.TIME,
            rule=lambda m, t: m.c1_existing_downstream_ng_service_mwh[t]
            >= m.c1_explicit_downstream_named_ng_mwh[t],
        )
        model.experimental_ng_service_policy = (
            "origin_explicit_services_replace_legacy_baseload_and_contain_explicit_downstream_ng"
        )
        model.experimental_ng_service_targets = {
            "ironmaking_target_pj_y": float(
                ng_service_calibration["ironmaking_target_pj_y"]
            ),
            "ironmaking_basis_t_y": float(
                ng_service_calibration["ironmaking_basis_t_y"]
            ),
            "downstream_target_pj_y": float(
                ng_service_calibration["downstream_target_pj_y"]
            ),
            "downstream_basis_t_y": float(
                ng_service_calibration["downstream_basis_t_y"]
            ),
        }
    model.full_site_energy_bridge_active = bool(bridge)
    model.site_baseload_ng_mwh_h = site_baseload_ng_mwh_h
    model.flexible_ng_allocation_policy = flexible_ng_allocation_policy
    model.flexible_other_site_heat_service_envelope_mwh_h = flexible_heat_service_mwh_h
    model.normal_case_flexible_ng_validation_reference_mwh_h = (
        normal_case_flexible_ng_reference_mwh_h
    )

    generator_active = enable_internal_wag_power or enable_generator_interface
    if generator_unit_interface is not None and not enable_generator_interface:
        raise S44CModelBuilderError(
            "A unit-specific generator boundary requires the generator controller phase."
        )
    if aggregate_generator_technical_interface is not None and not generator_active:
        raise S44CModelBuilderError(
            "An aggregate generator technical interface requires active internal generation."
        )
    if aggregate_generator_technical_interface is not None and generator_unit_interface is not None:
        raise S44CModelBuilderError(
            "Aggregate and unit-specific generator interfaces cannot be active together."
        )
    if generator_active and generator_unit_interface is not None:
        required_generator_keys = {
            "operating_mode",
            "vn25_electricity_efficiency",
            "vn25_electric_capacity_mw",
            "unit_volume_caps_nm3_h",
            "validation_anchors_pj_y",
            "ij01_total_fuel_horizon_cap_mwh",
            "ij01_total_fuel_deadline_caps_mwh",
        }
        missing_generator_keys = required_generator_keys.difference(generator_unit_interface)
        if missing_generator_keys:
            raise S44CModelBuilderError(
                f"Generator unit interface is missing: {sorted(missing_generator_keys)}"
            )
        for unit in ("vn25", "ij01"):
            for carrier in ("bfg", "cog", "bofg"):
                setattr(model, f"{carrier}_to_{unit}", Var(model.TIME, domain=NonNegativeReals))
        model.ng_to_vn25_mwh = Var(model.TIME, domain=NonNegativeReals)
        model.ng_to_ij01_mwh = Var(model.TIME, domain=NonNegativeReals)
        for t in model.TIME:
            model.ng_to_ij01_mwh[t].fix(0.0)
        normal_operation_vn25 = (
            str(generator_unit_interface["operating_mode"])
            == "normal_operation_vn25_available"
        )
        if normal_operation_vn25:
            required_normal_operation_keys = {
                "vn25_min_electric_output_mw",
                "vn25_ramp_mw_per_h",
                "ij01_forced_off",
                "development_policy_authorization",
            }
            missing_normal_operation_keys = required_normal_operation_keys.difference(
                generator_unit_interface
            )
            if missing_normal_operation_keys:
                raise S44CModelBuilderError(
                    "VN25 normal-operation interface is missing: "
                    f"{sorted(missing_normal_operation_keys)}"
                )
            if not bool(generator_unit_interface["ij01_forced_off"]):
                raise S44CModelBuilderError(
                    "VN25 normal operation requires IJ01 to be forced off."
                )
            if (
                str(generator_unit_interface["development_policy_authorization"])
                != "explicit_user_authorized_development_policy_not_site_truth"
            ):
                raise S44CModelBuilderError(
                    "VN25 minimum output and ramp must remain labelled as the "
                    "explicit user-authorized development policy."
                )
            for unit_carrier in ("bfg", "cog", "bofg"):
                component = getattr(model, f"{unit_carrier}_to_ij01")
                for t in model.TIME:
                    component[t].fix(0.0)
        model.bfg_to_vattenfall = Expression(
            model.TIME, rule=lambda m, t: m.bfg_to_vn25[t] + m.bfg_to_ij01[t]
        )
        model.cog_to_vattenfall = Expression(
            model.TIME, rule=lambda m, t: m.cog_to_vn25[t] + m.cog_to_ij01[t]
        )
        model.bofg_to_vattenfall = Expression(
            model.TIME, rule=lambda m, t: m.bofg_to_vn25[t] + m.bofg_to_ij01[t]
        )
        unit_volume_caps = generator_unit_interface["unit_volume_caps_nm3_h"]
        for unit in ("vn25", "ij01"):
            setattr(
                model,
                f"{unit}_gas_volume_cap",
                Constraint(
                    model.TIME,
                    rule=lambda m, t, unit=unit: (
                        getattr(m, f"bfg_to_{unit}")[t]
                        / (lhv_mj_per_nm3["BFG"] / MJ_PER_MWH)
                        + getattr(m, f"cog_to_{unit}")[t]
                        / (lhv_mj_per_nm3["COG"] / MJ_PER_MWH)
                        + getattr(m, f"bofg_to_{unit}")[t]
                        / (lhv_mj_per_nm3["BOFG"] / MJ_PER_MWH)
                    )
                    <= float(unit_volume_caps[unit]),
                ),
            )
        model.vn25_wag_fuel_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.bfg_to_vn25[t] + m.cog_to_vn25[t] + m.bofg_to_vn25[t],
        )
        model.ij01_wag_fuel_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.bfg_to_ij01[t] + m.cog_to_ij01[t] + m.bofg_to_ij01[t],
        )
        model.vn25_total_fuel_mwh = Expression(
            model.TIME, rule=lambda m, t: m.vn25_wag_fuel_mwh[t] + m.ng_to_vn25_mwh[t]
        )
        model.ij01_total_fuel_mwh = Expression(
            model.TIME, rule=lambda m, t: m.ij01_wag_fuel_mwh[t]
        )
        model.ij01_total_fuel_horizon_cap = Constraint(
            expr=sum(model.ij01_total_fuel_mwh[t] for t in model.TIME)
            <= float(generator_unit_interface["ij01_total_fuel_horizon_cap_mwh"])
        )
        for deadline, cap_mwh in generator_unit_interface[
            "ij01_total_fuel_deadline_caps_mwh"
        ].items():
            deadline_hour = int(deadline)
            if deadline_hour <= 0 or deadline_hour > len(model.TIME):
                raise S44CModelBuilderError("IJ01 rolling fuel deadline lies outside the horizon.")
            setattr(
                model,
                f"ij01_total_fuel_deadline_cap_{deadline_hour}",
                Constraint(
                    expr=sum(
                        model.ij01_total_fuel_mwh[t]
                        for t in model.TIME
                        if int(t) < deadline_hour
                    )
                    <= float(cap_mwh)
                ),
            )
        vn25_efficiency = float(generator_unit_interface["vn25_electricity_efficiency"])
        if not 0.0 < vn25_efficiency < 1.0:
            raise S44CModelBuilderError("VN25 electricity efficiency must be inside (0, 1).")
        model.vn25_electricity_mwh = Expression(
            model.TIME, rule=lambda m, t: vn25_efficiency * m.vn25_total_fuel_mwh[t]
        )
        vn25_electric_capacity_mw = float(
            generator_unit_interface["vn25_electric_capacity_mw"]
        )
        if vn25_electric_capacity_mw <= 0.0:
            raise S44CModelBuilderError(
                "VN25 development electric capacity must be positive."
            )
        model.vn25_electric_capacity = Constraint(
            model.TIME,
            rule=lambda m, t: m.vn25_electricity_mwh[t]
            <= vn25_electric_capacity_mw,
        )
        model.vn25_electric_capacity_interval_mwh = vn25_electric_capacity_mw
        model.vn25_electric_capacity_mw = (
            vn25_electric_capacity_mw / float(time_step_hours)
        )
        model.generator_operating_mode = str(
            generator_unit_interface["operating_mode"]
        )
        if normal_operation_vn25:
            minimum_output_interval_mwh = float(
                generator_unit_interface["vn25_min_electric_output_mw"]
            )
            ramp_mw_per_h = float(
                generator_unit_interface["vn25_ramp_mw_per_h"]
            )
            if not (
                0.0
                < minimum_output_interval_mwh
                <= vn25_electric_capacity_mw
            ):
                raise S44CModelBuilderError(
                    "VN25 interval minimum must be positive and no greater than "
                    "its interval capacity."
                )
            if ramp_mw_per_h <= 0.0:
                raise S44CModelBuilderError(
                    "VN25 development ramp must be positive."
                )
            model.vn25_minimum_electric_output = Constraint(
                model.TIME,
                rule=lambda m, t: m.vn25_electricity_mwh[t]
                >= minimum_output_interval_mwh,
            )
            ramp_energy_mwh = ramp_mw_per_h * float(time_step_hours) ** 2
            model.vn25_ramp_up = Constraint(
                model.TIME,
                rule=lambda m, t: Constraint.Skip
                if int(t) == 0
                else m.vn25_electricity_mwh[t]
                - m.vn25_electricity_mwh[int(t) - 1]
                <= ramp_energy_mwh,
            )
            model.vn25_ramp_down = Constraint(
                model.TIME,
                rule=lambda m, t: Constraint.Skip
                if int(t) == 0
                else m.vn25_electricity_mwh[int(t) - 1]
                - m.vn25_electricity_mwh[t]
                <= ramp_energy_mwh,
            )
            if initial_vn25_output_mw is not None:
                initial_output_mw = float(initial_vn25_output_mw)
                if not (
                    minimum_output_interval_mwh / float(time_step_hours)
                    - TOLERANCE
                    <= initial_output_mw
                    <= vn25_electric_capacity_mw / float(time_step_hours)
                    + TOLERANCE
                ):
                    raise S44CModelBuilderError(
                        "Initial VN25 output lies outside its development "
                        "normal-operation range."
                    )
                initial_energy_mwh = initial_output_mw * float(time_step_hours)
                model.vn25_initial_ramp_up = Constraint(
                    expr=model.vn25_electricity_mwh[0] - initial_energy_mwh
                    <= ramp_energy_mwh
                )
                model.vn25_initial_ramp_down = Constraint(
                    expr=initial_energy_mwh - model.vn25_electricity_mwh[0]
                    <= ramp_energy_mwh
                )
            model.vn25_min_electric_output_interval_mwh = (
                minimum_output_interval_mwh
            )
            model.vn25_min_electric_output_mw = (
                minimum_output_interval_mwh / float(time_step_hours)
            )
            model.vn25_ramp_mw_per_h = ramp_mw_per_h
            model.vn25_ramp_interval_power_delta_mw = (
                ramp_mw_per_h * float(time_step_hours)
            )
            model.vn25_ramp_interval_energy_delta_mwh = ramp_energy_mwh
            model.vn25_development_policy_authorization = str(
                generator_unit_interface["development_policy_authorization"]
            )
        model.vn25_conversion_loss_mwh = Expression(
            model.TIME, rule=lambda m, t: m.vn25_total_fuel_mwh[t] - m.vn25_electricity_mwh[t]
        )
        # No quantitative IJ01 electricity/steam split is source-accepted.
        # Its represented fuel is conserved in a named deferred-conversion
        # bucket instead of inventing an efficiency or useful-output split.
        model.ij01_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ij01_deferred_conversion_mwh = Expression(
            model.TIME, rule=lambda m, t: m.ij01_total_fuel_mwh[t]
        )
    elif generator_active:
        model.bfg_to_vattenfall = Var(model.TIME, domain=NonNegativeReals)
        model.cog_to_vattenfall = Var(model.TIME, domain=NonNegativeReals)
        model.bofg_to_vattenfall = Var(model.TIME, domain=NonNegativeReals)
        if aggregate_generator_technical_interface is not None:
            required_aggregate_keys = {
                "electricity_efficiency",
                "total_fuel_volume_cap_nm3_h",
                "natural_gas_lhv_mj_per_nm3",
                "electrical_capacity_mw",
            }
            missing_aggregate_keys = required_aggregate_keys.difference(
                aggregate_generator_technical_interface
            )
            if missing_aggregate_keys:
                raise S44CModelBuilderError(
                    f"Aggregate generator technical interface is missing: {sorted(missing_aggregate_keys)}"
                )
            aggregate_efficiency = float(
                aggregate_generator_technical_interface["electricity_efficiency"]
            )
            aggregate_volume_cap_nm3_h = float(
                aggregate_generator_technical_interface["total_fuel_volume_cap_nm3_h"]
            )
            aggregate_ng_lhv_mj_per_nm3 = float(
                aggregate_generator_technical_interface["natural_gas_lhv_mj_per_nm3"]
            )
            aggregate_electrical_capacity_mw = float(
                aggregate_generator_technical_interface["electrical_capacity_mw"]
            )
            if not 0.0 < aggregate_efficiency < 1.0:
                raise S44CModelBuilderError(
                    "Aggregate generator electricity efficiency must be inside (0, 1)."
                )
            if (
                aggregate_volume_cap_nm3_h <= 0.0
                or aggregate_ng_lhv_mj_per_nm3 <= 0.0
                or aggregate_electrical_capacity_mw <= 0.0
            ):
                raise S44CModelBuilderError(
                    "Aggregate generator volume cap, electrical capacity and natural-gas LHV must be positive."
                )
            model.ng_to_vattenfall_mwh = Var(model.TIME, domain=NonNegativeReals)
        else:
            aggregate_efficiency = WAG_TO_POWER_EFFICIENCY
            aggregate_volume_cap_nm3_h = VATTENFALL_TOTAL_WAG_CAP_NM3_H
            aggregate_ng_lhv_mj_per_nm3 = 35.8
            aggregate_electrical_capacity_mw = 0.0
            model.ng_to_vattenfall_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    else:
        model.bfg_to_vattenfall = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.cog_to_vattenfall = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bofg_to_vattenfall = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_to_vattenfall_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bfg_flared = Var(model.TIME, domain=NonNegativeReals)
    model.cog_flared = Var(model.TIME, domain=NonNegativeReals)
    model.bofg_flared = Var(model.TIME, domain=NonNegativeReals)

    model.bfg_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.bfg_generated[t]
        == m.bfg_to_bf_hot_stove[t]
        + m.bfg_to_kgf1[t]
        + m.bfg_to_hsm[t]
        + m.bfg_to_boiler[t]
        + m.bfg_to_vattenfall[t]
        + m.bfg_to_flexible_other_site_heat[t]
        + m.bfg_flared[t],
    )
    model.cog_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.cog_generated[t]
        == m.cog_to_kgf1[t]
        + m.cog_to_kgf2[t]
        + m.cog_to_sinter[t]
        + m.cog_to_hsm[t]
        + m.cog_to_pefa_branderij[t]
        + m.cog_to_boiler[t]
        + m.cog_to_vattenfall[t]
        + m.cog_to_flexible_other_site_heat[t]
        + m.cog_flared[t],
    )
    model.bofg_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.bofg_generated[t]
        == m.bofg_to_hsm[t]
        + m.bofg_to_pefa_malerij[t]
        + m.bofg_to_vattenfall[t]
        + m.bofg_to_flexible_other_site_heat[t]
        + m.bofg_flared[t],
    )
    if not enable_boiler_scaffold and not retire_legacy_boiler_placeholder:
        model.boiler_wag_cap = Constraint(
            model.TIME,
            rule=lambda m, t: m.bfg_to_boiler[t] + m.cog_to_boiler[t] <= inputs.boiler_wag_cap_mwh_h,
        )
        model.boiler_fuel_placeholder = Constraint(
            model.TIME,
            rule=lambda m, t: m.bfg_to_boiler[t] + m.cog_to_boiler[t] + m.ng_to_boiler_mwh[t]
            == inputs.boiler_total_placeholder_mwh_h,
        )
    if generator_active:
        if aggregate_generator_technical_interface is not None:
            model.vattenfall_total_volume_cap = Constraint(
                model.TIME,
                rule=lambda m, t: (
                    m.bfg_to_vattenfall[t] / (lhv_mj_per_nm3["BFG"] / MJ_PER_MWH)
                    + m.cog_to_vattenfall[t] / (lhv_mj_per_nm3["COG"] / MJ_PER_MWH)
                    + m.bofg_to_vattenfall[t] / (lhv_mj_per_nm3["BOFG"] / MJ_PER_MWH)
                    + m.ng_to_vattenfall_mwh[t]
                    / (aggregate_ng_lhv_mj_per_nm3 / MJ_PER_MWH)
                )
                <= aggregate_volume_cap_nm3_h,
            )
        elif generator_unit_interface is None:
            model.vattenfall_total_volume_cap = Constraint(
            model.TIME,
            rule=lambda m, t: (
                m.bfg_to_vattenfall[t] / (lhv_mj_per_nm3["BFG"] / MJ_PER_MWH)
                + m.cog_to_vattenfall[t] / (lhv_mj_per_nm3["COG"] / MJ_PER_MWH)
                + m.bofg_to_vattenfall[t] / (lhv_mj_per_nm3["BOFG"] / MJ_PER_MWH)
            )
            <= VATTENFALL_TOTAL_WAG_CAP_NM3_H,
            )
        if (
            enable_generator_interface
            and generator_interface_cap_mode == "inherited_profile"
            and generator_unit_interface is None
            and aggregate_generator_technical_interface is None
        ):
            model.vattenfall_fixed_interface_cap = Constraint(
                model.TIME,
                rule=lambda m, t: m.bfg_to_vattenfall[t] + m.cog_to_vattenfall[t] + m.bofg_to_vattenfall[t]
                    <= development_profile.generator_wag_interface_cap_mwh_h
                    * time_step_hours,
            )
        model.vattenfall_fuel_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.bfg_to_vattenfall[t] + m.cog_to_vattenfall[t] + m.bofg_to_vattenfall[t],
        )
        if aggregate_generator_technical_interface is not None:
            model.aggregate_generator_volume_used_nm3_h = Expression(
                model.TIME,
                rule=lambda m, t: (
                    m.bfg_to_vattenfall[t] / (lhv_mj_per_nm3["BFG"] / MJ_PER_MWH)
                    + m.cog_to_vattenfall[t] / (lhv_mj_per_nm3["COG"] / MJ_PER_MWH)
                    + m.bofg_to_vattenfall[t] / (lhv_mj_per_nm3["BOFG"] / MJ_PER_MWH)
                    + m.ng_to_vattenfall_mwh[t]
                    / (aggregate_ng_lhv_mj_per_nm3 / MJ_PER_MWH)
                ),
            )
            model.aggregate_generator_volume_unused_nm3_h = Expression(
                model.TIME,
                rule=lambda m, t: aggregate_volume_cap_nm3_h
                - m.aggregate_generator_volume_used_nm3_h[t],
            )
        else:
            model.aggregate_generator_volume_used_nm3_h = Expression(
                model.TIME, rule=lambda _m, _t: 0.0
            )
            model.aggregate_generator_volume_unused_nm3_h = Expression(
                model.TIME, rule=lambda _m, _t: 0.0
            )
        if generator_unit_interface is not None:
            model.generator_named_ng_mwh = Expression(
                model.TIME, rule=lambda m, t: m.ng_to_vn25_mwh[t]
            )
            model.generator_total_fuel_mwh = Expression(
                model.TIME,
                rule=lambda m, t: m.vn25_total_fuel_mwh[t] + m.ij01_total_fuel_mwh[t],
            )
            model.wag_generator_electricity_mwh = Expression(
                model.TIME,
                rule=lambda m, t: vn25_efficiency * m.vn25_wag_fuel_mwh[t]
                + m.ij01_electricity_mwh[t],
            )
            model.ng_generator_electricity_mwh = Expression(
                model.TIME,
                rule=lambda m, t: vn25_efficiency * m.ng_to_vn25_mwh[t],
            )
        elif aggregate_generator_technical_interface is not None:
            model.generator_named_ng_mwh = Expression(
                model.TIME, rule=lambda m, t: m.ng_to_vattenfall_mwh[t]
            )
            model.generator_total_fuel_mwh = Expression(
                model.TIME,
                rule=lambda m, t: m.vattenfall_fuel_mwh[t]
                + m.ng_to_vattenfall_mwh[t],
            )
            model.wag_generator_electricity_mwh = Expression(
                model.TIME,
                rule=lambda m, t: aggregate_efficiency * m.vattenfall_fuel_mwh[t],
            )
            model.ng_generator_electricity_mwh = Expression(
                model.TIME,
                rule=lambda m, t: aggregate_efficiency * m.ng_to_vattenfall_mwh[t],
            )
        else:
            model.generator_named_ng_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
            model.generator_total_fuel_mwh = Expression(
                model.TIME, rule=lambda m, t: m.vattenfall_fuel_mwh[t]
            )
            model.wag_generator_electricity_mwh = Expression(
                model.TIME,
                rule=lambda m, t: WAG_TO_POWER_EFFICIENCY * m.vattenfall_fuel_mwh[t],
            )
            model.ng_generator_electricity_mwh = Expression(
                model.TIME, rule=lambda _m, _t: 0.0
            )
        model.total_generator_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.wag_generator_electricity_mwh[t]
            + m.ng_generator_electricity_mwh[t],
        )
        if aggregate_generator_technical_interface is not None:
            model.aggregate_generator_electrical_capacity = Constraint(
                model.TIME,
                rule=lambda m, t: m.total_generator_electricity_mwh[t]
                <= aggregate_electrical_capacity_mw,
            )
        # Legacy aliases retain their historical total internal-offset meaning.
        # True WAG-only output is exposed only by wag_generator_electricity_mwh.
        model.generator_electricity_mwh = Expression(
            model.TIME, rule=lambda m, t: m.total_generator_electricity_mwh[t]
        )
        model.wag_electricity_mwh = Expression(
            model.TIME, rule=lambda m, t: m.total_generator_electricity_mwh[t]
        )
        model.represented_gross_electricity_before_background_mwh = Expression(
            model.TIME,
            rule=gross_electricity_rule or (lambda _m, _t: 0.0),
        )
        model.site_background_electricity_mwh = Expression(
            model.TIME,
            # Under the explicit proportional-allocation diagnostic, the
            # represented process boundary is the active electricity-demand
            # boundary.  The independent MER difference between the 16.2-PJ
            # operating total and the broader 17.8-PJ context remains a
            # reporting residual and must not be introduced as dispatch load.
            rule=lambda _m, _t: (
                0.0 if electricity_overlay else site_background_electricity_mwh_h
            ),
        )
        if electricity_overlay:
            model.experimental_process_electricity_boundary_policy = (
                "operating_process_total_active_broad_site_difference_reporting_only"
            )
        model.gross_total_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.represented_gross_electricity_before_background_mwh[t]
            + m.site_background_electricity_mwh[t],
        )
        model.gross_electricity_mwh = Expression(
            model.TIME, rule=lambda m, t: m.gross_total_electricity_mwh[t]
        )
        sale_enabled = bool(
            electricity_sale_sensitivity
            and electricity_sale_sensitivity.get("enabled") is True
        )
        # Freeze the common declaration schema before the sale-only FBBT pass.
        # FBBT correctly tightens current bounds in place; those derived bounds
        # must remain auditable without becoming formulation identity.
        _record_declared_variable_schema(model)
        if sale_enabled:
            if aggregate_generator_technical_interface is None:
                raise S44CModelBuilderError(
                    "The C0 electricity-sale sensitivity requires the frozen aggregate-generator interface."
                )
            if bool(aggregate_generator_technical_interface.get("export_allowed")):
                raise S44CModelBuilderError(
                    "The Phase-1 aggregate-generator interface must remain export-disabled; export is opt-in only through the sale sensitivity."
                )
            if electricity_sale_sensitivity.get("policy_id") != "athanasiadis_sale_enabled":
                raise S44CModelBuilderError("Unexpected electricity-sale sensitivity policy.")
            model.electricity_sale_sensitivity_active = True
            export_big_m_mw = float(aggregate_electrical_capacity_mw)
            model.grid_import_mode = Var(model.TIME, domain=Binary)
            model.gross_grid_import_mwh = Var(model.TIME, domain=NonNegativeReals)
            model.gross_grid_export_mwh = Var(model.TIME, domain=NonNegativeReals)
            _record_declared_variable_schema(model)
            model.grid_export_capacity = Constraint(
                model.TIME,
                rule=lambda m, t: m.gross_grid_export_mwh[t]
                <= export_big_m_mw * (1 - m.grid_import_mode[t]),
            )
            model.no_grid_reexport = Constraint(
                model.TIME,
                rule=lambda m, t: m.gross_grid_import_mwh[t]
                <= m.gross_total_electricity_mwh[t],
            )
            model.export_bounded_by_internal_generation = Constraint(
                model.TIME,
                rule=lambda m, t: m.gross_grid_export_mwh[t]
                <= m.total_generator_electricity_mwh[t],
            )
            model.gross_site_electricity_balance = Constraint(
                model.TIME,
                rule=lambda m, t: m.total_generator_electricity_mwh[t]
                + m.gross_grid_import_mwh[t]
                == m.gross_total_electricity_mwh[t]
                + m.gross_grid_export_mwh[t],
            )
            # Run the model-level, constraint-aware FBBT pass only after the
            # complete sale electricity boundary and all upstream process
            # capacity constraints exist.  The import disjunction is added
            # afterwards from the separately proven bound for each hour.
            model.grid_import_bound_audit = _constraint_aware_hourly_import_bounds(
                model
            )
            hourly_import_upper_bound = {
                int(row["hour_index"]): float(
                    row["gross_grid_import_upper_bound_mwh"]
                )
                for row in model.grid_import_bound_audit["hourly_bounds"]
            }
            model.grid_import_capacity = Constraint(
                model.TIME,
                rule=lambda m, t: m.gross_grid_import_mwh[t]
                <= hourly_import_upper_bound[int(t)] * m.grid_import_mode[t],
            )
            model.grid_import_big_m_proof = {
                "source": model.grid_import_bound_audit["derivation_method"],
                "status": model.grid_import_bound_audit["status"],
                "hourly_upper_bounds_mwh": hourly_import_upper_bound,
                "export_upper_bound_mwh": export_big_m_mw,
            }
        else:
            model.no_export_from_total_generation = Constraint(
                model.TIME,
                rule=lambda m, t: m.total_generator_electricity_mwh[t]
                <= m.gross_total_electricity_mwh[t],
            )
            model.gross_grid_import_mwh = Expression(
                model.TIME,
                rule=lambda m, t: m.gross_total_electricity_mwh[t]
                - m.total_generator_electricity_mwh[t],
            )
            model.gross_grid_export_mwh = Expression(
                model.TIME, rule=lambda _m, _t: 0.0
            )
        model.net_grid_exchange_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.gross_grid_import_mwh[t] - m.gross_grid_export_mwh[t],
        )
        # Historical cost contracts name this purchase quantity
        # ``net_grid_import_mwh``.  Under the sale sensitivity it remains the
        # non-negative gross import; signed exchange is separate above.
        model.net_grid_import_mwh = Expression(
            model.TIME, rule=lambda m, t: m.gross_grid_import_mwh[t]
        )
        model.gross_site_electricity_identity_residual_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.gross_total_electricity_mwh[t]
            - m.total_generator_electricity_mwh[t]
            - m.gross_grid_import_mwh[t]
            + m.gross_grid_export_mwh[t],
        )
    else:
        model.vattenfall_fuel_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.aggregate_generator_volume_used_nm3_h = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
        model.aggregate_generator_volume_unused_nm3_h = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
        model.generator_named_ng_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.generator_total_fuel_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.wag_generator_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_generator_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.total_generator_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.generator_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.wag_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.represented_gross_electricity_before_background_mwh = Expression(
            model.TIME, rule=gross_electricity_rule or (lambda _m, _t: 0.0)
        )
        model.site_background_electricity_mwh = Expression(
            model.TIME, rule=lambda _m, _t: site_background_electricity_mwh_h
        )
        model.gross_total_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.represented_gross_electricity_before_background_mwh[t]
            + m.site_background_electricity_mwh[t],
        )
        model.gross_electricity_mwh = Expression(
            model.TIME, rule=lambda m, t: m.gross_total_electricity_mwh[t]
        )
        model.gross_grid_import_mwh = Expression(
            model.TIME, rule=lambda m, t: m.gross_total_electricity_mwh[t]
        )
        model.gross_grid_export_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.net_grid_exchange_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.gross_grid_import_mwh[t] - m.gross_grid_export_mwh[t],
        )
        model.net_grid_import_mwh = Expression(
            model.TIME, rule=lambda m, t: m.net_grid_exchange_mwh[t]
        )
        model.gross_site_electricity_identity_residual_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.gross_total_electricity_mwh[t]
            - m.total_generator_electricity_mwh[t]
            - m.gross_grid_import_mwh[t]
            + m.gross_grid_export_mwh[t],
        )
    def _total_named_ng_procurement_rule(m, t):
        route_ng = (
            (m.drp_named_ng_mwh[t] if hasattr(m, "drp_named_ng_mwh") else 0.0)
            + (m.eaf_named_ng_mwh[t] if hasattr(m, "eaf_named_ng_mwh") else 0.0)
        )
        common_ng = m.generator_named_ng_mwh[t] + m.full_site_energy_bridge_named_ng_mwh[t]
        if ng_service_active:
            return (
                common_ng
                + m.c1_existing_ironmaking_ng_service_mwh[t]
                + m.c1_existing_downstream_ng_service_mwh[t]
                + route_ng
            )
        return (
            common_ng
            + m.ng_to_hsm_mwh[t]
            + m.ng_to_pefa_malerij_mwh[t]
            + m.ng_to_pefa_branderij_mwh[t]
            + m.ng_to_boiler_mwh[t]
            + m.site_baseload_ng_mwh[t]
            + route_ng
        )

    model.total_named_ng_procurement_mwh = Expression(
        model.TIME, rule=_total_named_ng_procurement_rule
    )
    model.aggregate_generator_technical_interface_active = bool(
        aggregate_generator_technical_interface
    )
    model.aggregate_generator_volume_cap_nm3_h = (
        float(aggregate_volume_cap_nm3_h)
        if aggregate_generator_technical_interface is not None
        else 0.0
    )
    model.aggregate_generator_electrical_capacity_mw = (
        float(aggregate_electrical_capacity_mw)
        if aggregate_generator_technical_interface is not None
        else 0.0
    )
    model.wag_used = Expression(
        model.TIME,
        rule=lambda m, t: m.bfg_to_bf_hot_stove[t]
        + m.bfg_to_kgf1[t]
        + m.bfg_to_hsm[t]
        + m.cog_to_kgf1[t]
        + m.cog_to_kgf2[t]
        + m.cog_to_sinter[t]
        + m.cog_to_hsm[t]
        + m.cog_to_pefa_branderij[t]
        + m.bofg_to_hsm[t]
        + m.bofg_to_pefa_malerij[t]
        + m.bfg_to_boiler[t]
        + m.cog_to_boiler[t]
        + m.bfg_to_vattenfall[t]
        + m.cog_to_vattenfall[t]
        + m.bofg_to_vattenfall[t]
        + m.bfg_to_flexible_other_site_heat[t]
        + m.cog_to_flexible_other_site_heat[t]
        + m.bofg_to_flexible_other_site_heat[t],
    )
    model.wag_flared = Expression(
        model.TIME,
        rule=lambda m, t: m.bfg_flared[t] + m.cog_flared[t] + m.bofg_flared[t],
    )
    model.wag_generated = Expression(
        model.TIME,
        rule=lambda m, t: m.bfg_generated[t] + m.cog_generated[t] + m.bofg_generated[t],
    )
    model.steam_production_mwh = Expression(
        model.TIME,
        rule=lambda m, t: inputs.eta_boiler_steam
        * (m.bfg_to_boiler[t] + m.cog_to_boiler[t] + m.ng_to_boiler_mwh[t]),
    )
    model.bfg_balance_residual = Expression(
        model.TIME,
        rule=lambda m, t: m.bfg_generated[t]
        - m.bfg_to_bf_hot_stove[t]
        - m.bfg_to_kgf1[t]
        - m.bfg_to_hsm[t]
        - m.bfg_to_boiler[t]
        - m.bfg_to_vattenfall[t]
        - m.bfg_to_flexible_other_site_heat[t]
        - m.bfg_flared[t],
    )
    model.cog_balance_residual = Expression(
        model.TIME,
        rule=lambda m, t: m.cog_generated[t]
        - m.cog_to_kgf1[t]
        - m.cog_to_kgf2[t]
        - m.cog_to_sinter[t]
        - m.cog_to_hsm[t]
        - m.cog_to_pefa_branderij[t]
        - m.cog_to_boiler[t]
        - m.cog_to_vattenfall[t]
        - m.cog_to_flexible_other_site_heat[t]
        - m.cog_flared[t],
    )
    model.bofg_balance_residual = Expression(
        model.TIME,
        rule=lambda m, t: m.bofg_generated[t]
        - m.bofg_to_hsm[t]
        - m.bofg_to_pefa_malerij[t]
        - m.bofg_to_vattenfall[t]
        - m.bofg_to_flexible_other_site_heat[t]
        - m.bofg_flared[t],
    )
    model.bfg_flare_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: combustion_t_per_mwh["BFG"] * m.bfg_flared[t],
    )
    model.cog_flare_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: combustion_t_per_mwh["COG"] * m.cog_flared[t],
    )
    model.bofg_flare_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: combustion_t_per_mwh["BOFG"] * m.bofg_flared[t],
    )
    model.flaring_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: m.bfg_flare_co2_t[t] + m.cog_flare_co2_t[t] + m.bofg_flare_co2_t[t],
    )
    # Mode B diagnostic only: carbon is counted once at each represented
    # oxidation sink.  Aggregate BF/BOF/KGF/PEFA/sinter counters remain out of
    # this expression, and placeholder boiler NG remains excluded.
    model.bfg_explicit_combustion_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: combustion_t_per_mwh["BFG"]
        * (
            m.bfg_to_bf_hot_stove[t]
            + m.bfg_to_hsm[t]
            + m.bfg_to_boiler[t]
            + m.bfg_to_vattenfall[t]
            + m.bfg_to_flexible_other_site_heat[t]
            + m.bfg_flared[t]
        ),
    )
    model.cog_explicit_combustion_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: combustion_t_per_mwh["COG"]
        * (
            m.cog_to_kgf1[t]
            + m.cog_to_kgf2[t]
            + m.cog_to_sinter[t]
            + m.cog_to_hsm[t]
            + m.cog_to_pefa_branderij[t]
            + m.cog_to_boiler[t]
            + m.cog_to_vattenfall[t]
            + m.cog_to_flexible_other_site_heat[t]
            + m.cog_flared[t]
        ),
    )
    model.bofg_explicit_combustion_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: combustion_t_per_mwh["BOFG"]
        * (
            m.bofg_to_hsm[t]
            + m.bofg_to_pefa_malerij[t]
            + m.bofg_to_vattenfall[t]
            + m.bofg_to_flexible_other_site_heat[t]
            + m.bofg_flared[t]
        ),
    )
    model.wag_explicit_combustion_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: m.bfg_explicit_combustion_co2_t[t]
        + m.cog_explicit_combustion_co2_t[t]
        + m.bofg_explicit_combustion_co2_t[t],
    )
    model.explicit_ng_combustion_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: NG_COMBUSTION_T_CO2_PER_MWH_LHV
        * m.total_named_ng_procurement_mwh[t],
    )
    # Aggregate process counters remain visible in the separate emissions
    # ledgers and are intentionally excluded here because their carbon basis
    # overlaps represented fuel oxidation. This is not an ETS ledger.
    model.represented_process_counter_direct_co2_t = Expression(
        model.TIME, rule=lambda _m, _t: 0.0
    )
    model.residual_unmodelled_direct_co2_t = Expression(
        model.TIME, rule=lambda _m, _t: site_residual_direct_co2_t_h
    )
    model.explicit_direct_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: m.wag_explicit_combustion_co2_t[t]
        + m.explicit_ng_combustion_co2_t[t],
    )
    model.total_direct_co2_reporting_t = Expression(
        model.TIME,
        rule=lambda m, t: m.explicit_direct_co2_t[t]
        + m.residual_unmodelled_direct_co2_t[t],
    )
    model.site_residual_steam_t_h = site_residual_steam_t_h
    model.site_residual_direct_co2_t_h = site_residual_direct_co2_t_h
    model.flaring_co2_diagnostic_cost_eur = Expression(
        model.TIME,
        rule=lambda m, t: FLARING_CO2_DIAGNOSTIC_EUR_PER_T * m.flaring_co2_t[t],
    )


def _enforce_continuous_must_run_availability(
    model: ConcreteModel,
    *,
    activity_to_on_var: Mapping[str, str],
    activities: Collection[str] | None,
    configuration_id: str,
) -> None:
    """Keep source-classified continuous assets on without fixing throughput."""

    requested = tuple(activities or ())
    if len(requested) != len(set(requested)):
        raise S44CModelBuilderError(
            f"Duplicate continuous must-run activity requested for {configuration_id}: {sorted(requested)}"
        )
    unknown = set(requested).difference(activity_to_on_var)
    if unknown:
        raise S44CModelBuilderError(
            f"Unknown or non-continuous activity requested for {configuration_id}: {sorted(unknown)}"
        )
    for activity_name in requested:
        on_var = getattr(model, activity_to_on_var[activity_name])
        for t in model.TIME:
            on_var[t].fix(1.0)


def _add_pellet_origin_ledger(
    model: ConcreteModel,
    *,
    configuration: str,
    time_step_hours: float,
    imported_pellets_t_y: float,
    initial_internal_inventory_t: float,
    internal_inventory_capacity_t: float | None = None,
) -> None:
    """Conserve internal PeFa and external pellet origins separately.

    C0 imports are BF-grade and can only feed the blast furnaces. C1 imports
    are DR-grade and can only feed the DRP. PeFa output is the sole internal
    origin and may serve the configuration's represented BF and DRP demands.
    The compatibility expression ``imported_pellet_supply_t`` remains the
    total external flow, but it is no longer mixed into internal inventory.
    """

    if configuration not in {"C0", "C1"}:
        raise S44CModelBuilderError("Unknown pellet-origin configuration.")
    imported_per_interval_t = (
        float(imported_pellets_t_y) / 8_760.0 * float(time_step_hours)
    )
    if min(imported_per_interval_t, float(initial_internal_inventory_t)) < 0.0:
        raise S44CModelBuilderError("Invalid pellet-origin supply or inventory.")
    if (
        internal_inventory_capacity_t is not None
        and not 0.0
        <= float(initial_internal_inventory_t)
        <= float(internal_inventory_capacity_t)
    ):
        raise S44CModelBuilderError("Invalid internal PeFa inventory capacity.")

    model.internal_pefa_pellets_to_bf_t = Var(
        model.TIME, domain=NonNegativeReals
    )
    if configuration == "C1":
        model.internal_pefa_pellets_to_drp_t = Var(
            model.TIME, domain=NonNegativeReals
        )
        model.external_bf_pellets_to_bf_t = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
        model.external_dr_pellets_to_drp_t = Expression(
            model.TIME, rule=lambda _m, _t: imported_per_interval_t
        )
        model.pellet_bf_origin_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.bf_pellet_input_t[t]
            == m.internal_pefa_pellets_to_bf_t[t],
        )
        model.pellet_drp_origin_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.drp_pellet_input[t]
            == m.internal_pefa_pellets_to_drp_t[t]
            + m.external_dr_pellets_to_drp_t[t],
        )
    else:
        model.internal_pefa_pellets_to_drp_t = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
        model.external_bf_pellets_to_bf_t = Expression(
            model.TIME, rule=lambda _m, _t: imported_per_interval_t
        )
        model.external_dr_pellets_to_drp_t = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
        model.pellet_bf_origin_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.bf_pellet_input_t[t]
            == m.internal_pefa_pellets_to_bf_t[t]
            + m.external_bf_pellets_to_bf_t[t],
        )

    model.imported_pellet_supply_t = Expression(
        model.TIME,
        rule=lambda m, t: m.external_bf_pellets_to_bf_t[t]
        + m.external_dr_pellets_to_drp_t[t],
    )
    model.pellet_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.pellet_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.pellet_inventory[t]
        == (
            float(initial_internal_inventory_t)
            if int(t) == 0
            else m.pellet_inventory[int(t) - 1]
        )
        + m.pefa_pellet_output_t[t]
        - m.internal_pefa_pellets_to_bf_t[t]
        - m.internal_pefa_pellets_to_drp_t[t],
    )
    if internal_inventory_capacity_t is not None:
        model.pellet_capacity = Constraint(
            model.TIME,
            rule=lambda m, t: m.pellet_inventory[t]
            <= float(internal_inventory_capacity_t),
        )
    model.pellet_terminal = Constraint(
        expr=model.pellet_inventory[len(model.TIME) - 1]
        == float(initial_internal_inventory_t)
    )
    if (
        configuration == "C1"
        and getattr(model, "c1_inventory_terminal_policy", "")
        == "executed_state_with_bounded_physical_continuation_no_cyclic_tail_closure"
    ):
        model.pellet_terminal.deactivate()
        model.temporal_tail_cyclic_closures_replaced = tuple(
            dict.fromkeys(
                (*model.temporal_tail_cyclic_closures_replaced, "pellet_terminal")
            )
        )
    model.pellet_origin_ledger_status = (
        "physical_origin_conservation_internal_pefa_and_external_grade_specific"
    )
    model.pellet_inventory_origin = "internal_pefa_fired_pellets_only"
    model.external_pellet_annual_anchor_t_y = float(imported_pellets_t_y)


def _add_c1_temporal_plant_dynamics(
    model: ConcreteModel,
    *,
    time_step_hours: float,
    contract: Mapping[str, Any],
    initial_rate_t_h: Mapping[str, float],
) -> None:
    """Install the governed C1 development dynamics on interval quantities.

    These settings are explicit development policies. They must not be cited
    as measured Tata control-room limits. Process variables store tonnes per
    model interval, while the contract and rolling state use tonnes per hour.
    """

    if float(time_step_hours) not in {0.25, 1.0}:
        raise S44CModelBuilderError(
            "C1 temporal plant dynamics require an hourly or quarter-hour grid."
        )
    required_initial = {
        "coking_plant_1",
        "sintering_plant",
        "blast_furnace_6",
        "drp_pellet_input",
    }
    missing_initial = required_initial.difference(initial_rate_t_h)
    if missing_initial:
        raise S44CModelBuilderError(
            "C1 temporal dynamics lack rolling boundary rates: "
            f"{sorted(missing_initial)}"
        )

    sifa = contract.get("sifa")
    bf6 = contract.get("bf6")
    drp = contract.get("drp")
    kgf1 = contract.get("kgf1")
    pefa = contract.get("pefa")
    if not all(
        isinstance(item, Mapping) for item in (sifa, bf6, drp, kgf1, pefa)
    ):
        raise S44CModelBuilderError(
            "C1 temporal dynamics require SiFa, BF6, DRP, KGF1 and PeFa contracts."
        )

    # SiFa: small QH changes plus an explicit no-reversal window. Direction
    # flags carry a strictly positive movement, preventing arbitrary flag
    # choices on flat intervals from contaminating the rolling state.
    sifa_ramp_rate = float(sifa["ramp_t_h_per_qh"])
    sifa_direction_hours = float(
        sifa.get(
            "minimum_direction_hours",
            0.25 * int(sifa["minimum_direction_intervals"]),
        )
    )
    sifa_window_float = sifa_direction_hours / float(time_step_hours)
    sifa_window = int(round(sifa_window_float))
    if sifa_ramp_rate <= 0.0 or sifa_window < 1:
        raise S44CModelBuilderError("Invalid SiFa ramp or direction window.")
    if not math.isclose(sifa_window_float, sifa_window):
        raise S44CModelBuilderError("SiFa direction duration is not grid-aligned.")
    # The QH contract and the hourly discretisation are explicit alternatives.
    # The hourly value is deliberately conservative: an hourly endpoint must
    # not silently inherit four QH movements while being represented as one
    # constant hourly block.
    sifa_rate_step_t_h = (
        float(sifa["ramp_t_h_per_hour"])
        if math.isclose(float(time_step_hours), 1.0)
        and "ramp_t_h_per_hour" in sifa
        else sifa_ramp_rate
    )
    sifa_ramp_interval = sifa_rate_step_t_h * float(time_step_hours)
    movement_epsilon = float(sifa.get("movement_epsilon_t_h", 1e-4)) * time_step_hours
    model.sifa_rate_increase_t = Var(model.TIME, domain=NonNegativeReals)
    model.sifa_rate_decrease_t = Var(model.TIME, domain=NonNegativeReals)
    model.sifa_up_direction = Var(model.TIME, domain=Binary)
    model.sifa_down_direction = Var(model.TIME, domain=Binary)

    def _sifa_previous(m: ConcreteModel, t: int):
        return (
            float(initial_rate_t_h["sintering_plant"]) * time_step_hours
            if int(t) == 0
            else m.sintering_plant[int(t) - 1]
        )

    model.sifa_rate_change_identity = Constraint(
        model.TIME,
        rule=lambda m, t: m.sintering_plant[t] - _sifa_previous(m, int(t))
        == m.sifa_rate_increase_t[t] - m.sifa_rate_decrease_t[t],
    )
    model.sifa_rate_increase_upper = Constraint(
        model.TIME,
        rule=lambda m, t: m.sifa_rate_increase_t[t]
        <= sifa_ramp_interval * m.sifa_up_direction[t],
    )
    model.sifa_rate_decrease_upper = Constraint(
        model.TIME,
        rule=lambda m, t: m.sifa_rate_decrease_t[t]
        <= sifa_ramp_interval * m.sifa_down_direction[t],
    )
    model.sifa_rate_increase_lower = Constraint(
        model.TIME,
        rule=lambda m, t: m.sifa_rate_increase_t[t]
        >= movement_epsilon * m.sifa_up_direction[t],
    )
    model.sifa_rate_decrease_lower = Constraint(
        model.TIME,
        rule=lambda m, t: m.sifa_rate_decrease_t[t]
        >= movement_epsilon * m.sifa_down_direction[t],
    )
    model.sifa_single_direction = Constraint(
        model.TIME,
        rule=lambda m, t: m.sifa_up_direction[t] + m.sifa_down_direction[t]
        <= 1,
    )
    model.sifa_no_direction_reversal = ConstraintList()
    horizon_steps = len(model.TIME)
    for start in range(horizon_steps):
        for later in range(start + 1, min(horizon_steps, start + sifa_window)):
            model.sifa_no_direction_reversal.add(
                model.sifa_up_direction[start]
                + model.sifa_down_direction[later]
                <= 1
            )
            model.sifa_no_direction_reversal.add(
                model.sifa_down_direction[start]
                + model.sifa_up_direction[later]
                <= 1
            )
    initial_direction = str(sifa.get("initial_direction", "flat"))
    initial_cooldown = int(sifa.get("initial_cooldown_intervals", 0))
    if initial_direction not in {"up", "down", "flat"}:
        raise S44CModelBuilderError("Invalid carried SiFa direction.")
    if not 0 <= initial_cooldown < sifa_window:
        raise S44CModelBuilderError("Invalid carried SiFa reversal cooldown.")
    for interval in range(min(initial_cooldown, horizon_steps)):
        if initial_direction == "up":
            model.sifa_down_direction[interval].fix(0.0)
        elif initial_direction == "down":
            model.sifa_up_direction[interval].fix(0.0)

    def _add_rate_setpoint_contract(
        *,
        component_name: str,
        prefix: str,
        block_hours: float,
        maximum_step_t_h: float,
    ) -> None:
        block_steps_float = float(block_hours) / time_step_hours
        block_steps = int(round(block_steps_float))
        if (
            block_steps < 1
            or not math.isclose(block_steps_float, block_steps)
            or maximum_step_t_h < 0.0
        ):
            raise S44CModelBuilderError(
                f"Invalid {prefix} setpoint block or step contract."
            )
        component = getattr(model, component_name)
        holds = ConstraintList()
        ramps = ConstraintList()
        setattr(model, f"{prefix}_setpoint_holds", holds)
        setattr(model, f"{prefix}_setpoint_steps", ramps)
        for t in range(horizon_steps):
            if t % block_steps:
                holds.add(component[t] == component[t - 1])
            else:
                previous = (
                    float(initial_rate_t_h[component_name]) * time_step_hours
                    if t == 0
                    else component[t - 1]
                )
                step_interval = maximum_step_t_h * time_step_hours
                ramps.add(component[t] - previous <= step_interval)
                ramps.add(previous - component[t] <= step_interval)
        setattr(model, f"{prefix}_setpoint_block_steps", block_steps)
        setattr(model, f"{prefix}_maximum_step_t_h", maximum_step_t_h)

    _add_rate_setpoint_contract(
        component_name="blast_furnace_6",
        prefix="bf6",
        block_hours=float(bf6["setpoint_block_hours"]),
        maximum_step_t_h=float(bf6["maximum_step_t_h"]),
    )
    _add_rate_setpoint_contract(
        component_name="coking_plant_1",
        prefix="kgf1",
        block_hours=float(kgf1["setpoint_block_hours"]),
        maximum_step_t_h=float(kgf1["maximum_step_t_h"]),
    )
    _add_rate_setpoint_contract(
        component_name="drp_pellet_input",
        prefix="drp_temporal",
        block_hours=float(drp["setpoint_block_hours"]),
        maximum_step_t_h=float(drp["maximum_step_t_h"]),
    )

    pefa_min_t_h = float(pefa["minimum_output_t_h"])
    pefa_max_t_h = float(pefa["maximum_output_t_h"])
    if not 0.0 < pefa_min_t_h <= pefa_max_t_h:
        raise S44CModelBuilderError("Invalid bounded PeFa output range.")
    model.pefa_pellet_output_t = Var(model.TIME, domain=NonNegativeReals)
    model.pefa_output_lower = Constraint(
        model.TIME,
        rule=lambda m, t: m.pefa_pellet_output_t[t]
        >= pefa_min_t_h * time_step_hours,
    )
    model.pefa_output_upper = Constraint(
        model.TIME,
        rule=lambda m, t: m.pefa_pellet_output_t[t]
        <= pefa_max_t_h * time_step_hours,
    )
    _add_rate_setpoint_contract(
        component_name="pefa_pellet_output_t",
        prefix="pefa",
        block_hours=float(pefa["setpoint_block_hours"]),
        maximum_step_t_h=float(pefa["maximum_step_t_h"]),
    )
    bf_pellets_per_t_hot_metal = float(pefa["bf_pellets_t_per_t_hot_metal"])
    initial_pellet_inventory_t = float(pefa["initial_inventory_t"])
    if min(bf_pellets_per_t_hot_metal, initial_pellet_inventory_t) < 0.0:
        raise S44CModelBuilderError("Invalid PeFa/pellet-bus contract.")
    model.bf_pellet_input_t = Expression(
        model.TIME,
        rule=lambda m, t: bf_pellets_per_t_hot_metal
        * m.bf_hot_iron_output[t],
    )
    _add_pellet_origin_ledger(
        model,
        configuration="C1",
        time_step_hours=time_step_hours,
        imported_pellets_t_y=float(pefa["imported_pellets_t_y"]),
        initial_internal_inventory_t=initial_pellet_inventory_t,
    )
    model.pefa_price_response_policy = (
        "bounded_endogenous_response_via_closed_fired_pellet_bus"
    )
    model.pellet_storage_capacity_policy = str(pefa["capacity_policy"])

    downstream = contract.get("downstream_block_sensitivity", {})
    if bool(downstream.get("active", False)):
        block_hours = float(downstream["block_hours"])
        block_steps_float = block_hours / time_step_hours
        block_steps = int(round(block_steps_float))
        if block_steps < 1 or not math.isclose(block_steps_float, block_steps):
            raise S44CModelBuilderError("Invalid downstream sensitivity block length.")
        model.downstream_block_sensitivity_constraints = ConstraintList()
        for component_name in tuple(downstream.get("components", ())):
            if component_name not in {"basic_oxygen_furnace", "hot_strip_mill"}:
                raise S44CModelBuilderError(
                    f"Unsupported downstream block component: {component_name}."
                )
            component = getattr(model, component_name)
            for t in range(horizon_steps):
                if t % block_steps:
                    model.downstream_block_sensitivity_constraints.add(
                        component[t] == component[t - 1]
                    )
        model.downstream_block_sensitivity_status = (
            "offline_development_sensitivity_not_site_truth"
        )

    _add_normalized_capacity_contract(
        model,
        time_step_hours=time_step_hours,
        contract=contract,
        configuration="C1",
    )

    model.c1_temporal_plant_dynamics_status = (
        "user_authorized_development_policy_not_site_truth"
    )
    model.sifa_ramp_t_h_per_qh = sifa_ramp_rate
    model.sifa_minimum_direction_intervals = sifa_window
    model.sifa_minimum_direction_hours = sifa_direction_hours
    model.sifa_maximum_rate_step_t_h = sifa_rate_step_t_h


def _add_normalized_capacity_contract(
    model: ConcreteModel,
    *,
    time_step_hours: float,
    contract: Mapping[str, Any],
    configuration: str,
) -> None:
    """Apply reproducible relative operating envelopes around flat references.

    The references come from an accepted price-insensitive physical trajectory.
    Relative widths are shared by asset family across configurations and are
    planning assumptions, not measured technical nameplate limits.
    """

    payload = contract.get("normalized_capacity_contract")
    if not isinstance(payload, Mapping):
        return
    assets = payload.get("assets")
    if not isinstance(assets, Mapping) or not assets:
        raise S44CModelBuilderError(
            f"{configuration} normalized capacity contract has no assets."
        )
    constraints = ConstraintList()
    model.normalized_capacity_envelope_constraints = constraints
    resolved: dict[str, dict[str, float | str]] = {}
    for component_name, row in assets.items():
        if not isinstance(row, Mapping) or not hasattr(model, str(component_name)):
            raise S44CModelBuilderError(
                f"Invalid {configuration} normalized capacity asset: {component_name}."
            )
        reference = float(row["reference_rate_t_h"])
        half_width = float(row["relative_half_width"])
        lower = float(row["resolved_minimum_t_h"])
        upper = float(row["resolved_maximum_t_h"])
        raw_lower = reference * (1.0 - half_width)
        raw_upper = reference * (1.0 + half_width)
        lower_policy = str(row.get("lower_policy", "normalized_family_envelope"))
        upper_policy = str(row.get("upper_policy", "normalized_family_envelope"))
        authorized_lower_override = lower_policy.startswith("user_authorized_")
        authorized_upper_override = upper_policy.startswith("user_authorized_")
        if (
            reference <= 0.0
            or not 0.0 <= half_width < 1.0
            or not 0.0 <= lower < upper
            or (lower < raw_lower - 1e-5 and not authorized_lower_override)
            or (upper > raw_upper + 1e-5 and not authorized_upper_override)
            or not lower <= reference <= upper
        ):
            raise S44CModelBuilderError(
                f"Invalid normalized capacity envelope for {component_name}."
            )
        component = getattr(model, str(component_name))
        for t in model.TIME:
            constraints.add(component[t] >= lower * time_step_hours)
            constraints.add(component[t] <= upper * time_step_hours)
        resolved[str(component_name)] = {
            "display_name": str(row.get("display_name", component_name)),
            "family": str(row.get("family", component_name)),
            "reference_rate_t_h": reference,
            "relative_half_width": half_width,
            "resolved_minimum_t_h": lower,
            "resolved_maximum_t_h": upper,
            "lower_policy": lower_policy,
            "upper_policy": upper_policy,
            "ramp_fraction_of_reference_per_setpoint": float(
                row["ramp_fraction_of_reference_per_setpoint"]
            ),
        }
    model.normalized_capacity_contract = resolved
    model.normalized_capacity_contract_policy = str(payload["policy"])
    model.normalized_capacity_calibration_evidence_run = str(
        payload["calibration_evidence_run"]
    )
    model.normalized_capacity_price_response_used_for_calibration = bool(
        not payload.get("price_response_not_used_for_calibration", False)
    )
    aggregate_floors = payload.get("aggregate_recoverability_floors", {})
    if not isinstance(aggregate_floors, Mapping):
        raise S44CModelBuilderError(
            f"Invalid {configuration} normalized aggregate recoverability contract."
        )
    model.normalized_capacity_aggregate_recoverability = ConstraintList()
    resolved_aggregate_floors: dict[str, dict[str, Any]] = {}
    for floor_id, row in aggregate_floors.items():
        if not isinstance(row, Mapping):
            raise S44CModelBuilderError(f"Invalid aggregate floor: {floor_id}.")
        components = tuple(str(name) for name in row["components"])
        if not components or any(not hasattr(model, name) for name in components):
            raise S44CModelBuilderError(f"Unknown aggregate-floor component: {floor_id}.")
        minimum_rate = float(row["minimum_combined_rate_t_h"])
        if minimum_rate <= 0.0:
            raise S44CModelBuilderError(f"Invalid aggregate-floor rate: {floor_id}.")
        for t in model.TIME:
            model.normalized_capacity_aggregate_recoverability.add(
                sum(getattr(model, name)[t] for name in components)
                >= minimum_rate * time_step_hours
            )
        resolved_aggregate_floors[str(floor_id)] = {
            "components": components,
            "minimum_combined_rate_t_h": minimum_rate,
            "basis": str(row["basis"]),
            "methodological_status": str(row["methodological_status"]),
        }
    model.normalized_capacity_aggregate_recoverability_floors = (
        resolved_aggregate_floors
    )


def _add_downstream_temporal_contract(
    model: ConcreteModel,
    *,
    time_step_hours: float,
    contract: Mapping[str, Any],
    dsp_component_name: str,
    initial_rate_t_h: Mapping[str, float],
) -> None:
    """Apply the same bounded downstream timing contract to C0 and C1."""

    downstream = contract.get("downstream_temporal_contract")
    if not isinstance(downstream, Mapping):
        return

    def add_block_hold(component_name: str, prefix: str, block_hours: float) -> None:
        block_steps_float = block_hours / time_step_hours
        block_steps = int(round(block_steps_float))
        if block_steps <= 0 or not math.isclose(block_steps_float, block_steps):
            raise S44CModelBuilderError(
                f"Invalid downstream {prefix} setpoint block."
            )
        component = getattr(model, component_name)
        holds = ConstraintList()
        setattr(model, f"{prefix}_temporal_block_holds", holds)
        for t in model.TIME:
            index = int(t)
            if index % block_steps:
                holds.add(component[index] == component[index - index % block_steps])
        setattr(model, f"{prefix}_temporal_block_steps", block_steps)

    add_block_hold(
        "hot_strip_mill",
        "hsm",
        float(downstream["hsm_setpoint_block_hours"]),
    )
    hsm_block_steps = int(model.hsm_temporal_block_steps)
    hsm_maximum_step_t_h = float(downstream["hsm_maximum_step_t_h"])
    hsm_initial_rate_t_h = float(initial_rate_t_h["hot_strip_mill"])
    if hsm_maximum_step_t_h <= 0.0 or hsm_initial_rate_t_h < 0.0:
        raise S44CModelBuilderError("Invalid HSM campaign boundary contract.")
    model.hsm_temporal_step_constraints = ConstraintList()
    for t in model.TIME:
        index = int(t)
        if index % hsm_block_steps:
            continue
        previous = (
            hsm_initial_rate_t_h * time_step_hours
            if index == 0
            else model.hot_strip_mill[index - 1]
        )
        maximum_interval_step = hsm_maximum_step_t_h * time_step_hours
        model.hsm_temporal_step_constraints.add(
            model.hot_strip_mill[index] - previous <= maximum_interval_step
        )
        model.hsm_temporal_step_constraints.add(
            previous - model.hot_strip_mill[index] <= maximum_interval_step
        )
    model.hsm_temporal_initial_rate_t_h = hsm_initial_rate_t_h
    model.hsm_temporal_maximum_step_t_h = hsm_maximum_step_t_h
    model.hsm_temporal_campaign_minimum_hours = float(
        downstream["hsm_setpoint_block_hours"]
    )
    model.hsm_temporal_campaign_status = (
        "user_authorized_blocked_hourly_development_policy_not_site_truth"
    )
    add_block_hold(
        dsp_component_name,
        "dsp",
        float(downstream["dsp_setpoint_block_hours"]),
    )
    dsp_max_t_h = float(downstream["dsp_final_product_max_t_h"])
    if dsp_max_t_h <= 0.0:
        raise S44CModelBuilderError("DSP temporal envelope must be positive.")
    dsp_output = getattr(model, dsp_component_name)
    model.dsp_temporal_output_cap = Constraint(
        model.TIME,
        rule=lambda _m, t: dsp_output[t] <= dsp_max_t_h * time_step_hours,
    )
    model.downstream_temporal_policy = (
        "shared_hourly_HSM_DSP_setpoints_and_uniform_DSP_development_envelope"
    )


def _add_c0_temporal_plant_dynamics(
    model: ConcreteModel,
    *,
    time_step_hours: float,
    contract: Mapping[str, Any],
    initial_rate_t_h: Mapping[str, float],
) -> None:
    """Install configuration-specific C0 development dynamics.

    The limits are governed planning assumptions, not measured Tata control
    limits. Process variables contain interval quantities; state and contract
    values use rates per hour.
    """

    if float(time_step_hours) not in {0.25, 1.0}:
        raise S44CModelBuilderError(
            "C0 temporal plant dynamics require an hourly or quarter-hour grid."
        )
    required_initial = {
        "coking_plant_1",
        "coking_plant_2",
        "sintering_plant",
        "blast_furnace_6",
        "blast_furnace_7",
        "pefa_pellet_output_t",
    }
    missing_initial = required_initial.difference(initial_rate_t_h)
    if missing_initial:
        raise S44CModelBuilderError(
            "C0 temporal dynamics lack rolling boundary rates: "
            f"{sorted(missing_initial)}"
        )
    required_contract = {"sifa", "bf6", "bf7", "kgf1", "kgf2", "pefa"}
    missing_contract = required_contract.difference(contract)
    if missing_contract or any(
        not isinstance(contract[key], Mapping) for key in required_contract
    ):
        raise S44CModelBuilderError(
            "C0 temporal dynamics require governed SiFa, BF6/BF7, "
            "KGF1/KGF2 and PeFa contracts."
        )

    horizon_steps = len(model.TIME)
    sifa = contract["sifa"]
    sifa_ramp_t_h = float(sifa["ramp_t_h_per_qh"])
    direction_hours = float(
        sifa.get(
            "minimum_direction_hours",
            0.25 * int(sifa["minimum_direction_intervals"]),
        )
    )
    direction_window_float = direction_hours / float(time_step_hours)
    direction_window = int(round(direction_window_float))
    if sifa_ramp_t_h <= 0.0 or direction_window < 1:
        raise S44CModelBuilderError("Invalid C0 SiFa movement contract.")
    if not math.isclose(direction_window_float, direction_window):
        raise S44CModelBuilderError("C0 SiFa direction duration is not grid-aligned.")
    sifa_rate_step_t_h = (
        float(sifa["ramp_t_h_per_hour"])
        if math.isclose(float(time_step_hours), 1.0)
        and "ramp_t_h_per_hour" in sifa
        else sifa_ramp_t_h
    )
    interval_ramp = sifa_rate_step_t_h * float(time_step_hours)
    movement_epsilon = float(sifa.get("movement_epsilon_t_h", 1e-4)) * time_step_hours
    model.sifa_rate_increase_t = Var(model.TIME, domain=NonNegativeReals)
    model.sifa_rate_decrease_t = Var(model.TIME, domain=NonNegativeReals)
    model.sifa_up_direction = Var(model.TIME, domain=Binary)
    model.sifa_down_direction = Var(model.TIME, domain=Binary)

    def previous_sifa(m: ConcreteModel, t: int):
        return (
            float(initial_rate_t_h["sintering_plant"]) * time_step_hours
            if t == 0
            else m.sintering_plant[t - 1]
        )

    model.sifa_rate_change_identity = Constraint(
        model.TIME,
        rule=lambda m, t: m.sintering_plant[t] - previous_sifa(m, int(t))
        == m.sifa_rate_increase_t[t] - m.sifa_rate_decrease_t[t],
    )
    model.sifa_rate_increase_upper = Constraint(
        model.TIME,
        rule=lambda m, t: m.sifa_rate_increase_t[t]
        <= interval_ramp * m.sifa_up_direction[t],
    )
    model.sifa_rate_decrease_upper = Constraint(
        model.TIME,
        rule=lambda m, t: m.sifa_rate_decrease_t[t]
        <= interval_ramp * m.sifa_down_direction[t],
    )
    model.sifa_rate_increase_lower = Constraint(
        model.TIME,
        rule=lambda m, t: m.sifa_rate_increase_t[t]
        >= movement_epsilon * m.sifa_up_direction[t],
    )
    model.sifa_rate_decrease_lower = Constraint(
        model.TIME,
        rule=lambda m, t: m.sifa_rate_decrease_t[t]
        >= movement_epsilon * m.sifa_down_direction[t],
    )
    model.sifa_single_direction = Constraint(
        model.TIME,
        rule=lambda m, t: m.sifa_up_direction[t] + m.sifa_down_direction[t] <= 1,
    )
    model.sifa_no_direction_reversal = ConstraintList()
    for start in range(horizon_steps):
        for later in range(start + 1, min(horizon_steps, start + direction_window)):
            model.sifa_no_direction_reversal.add(
                model.sifa_up_direction[start] + model.sifa_down_direction[later] <= 1
            )
            model.sifa_no_direction_reversal.add(
                model.sifa_down_direction[start] + model.sifa_up_direction[later] <= 1
            )

    def add_setpoint(component_name: str, prefix: str, payload: Mapping[str, Any]) -> None:
        block_steps_float = float(payload["setpoint_block_hours"]) / time_step_hours
        block_steps = int(round(block_steps_float))
        maximum_step_t_h = float(payload["maximum_step_t_h"])
        if (
            block_steps < 1
            or not math.isclose(block_steps_float, block_steps)
            or maximum_step_t_h < 0.0
        ):
            raise S44CModelBuilderError(f"Invalid C0 {prefix} setpoint contract.")
        component = getattr(model, component_name)
        holds = ConstraintList()
        steps = ConstraintList()
        setattr(model, f"{prefix}_setpoint_holds", holds)
        setattr(model, f"{prefix}_setpoint_steps", steps)
        for t in range(horizon_steps):
            if t % block_steps:
                holds.add(component[t] == component[t - 1])
            else:
                previous = (
                    float(initial_rate_t_h[component_name]) * time_step_hours
                    if t == 0
                    else component[t - 1]
                )
                maximum_interval_step = maximum_step_t_h * time_step_hours
                steps.add(component[t] - previous <= maximum_interval_step)
                steps.add(previous - component[t] <= maximum_interval_step)
        setattr(model, f"{prefix}_setpoint_block_steps", block_steps)
        setattr(model, f"{prefix}_maximum_step_t_h", maximum_step_t_h)

    for component_name, prefix, key in (
        ("blast_furnace_6", "bf6", "bf6"),
        ("blast_furnace_7", "bf7", "bf7"),
        ("coking_plant_1", "kgf1", "kgf1"),
        ("coking_plant_2", "kgf2", "kgf2"),
    ):
        add_setpoint(component_name, prefix, contract[key])

    pefa = contract["pefa"]
    pefa_min_t_h = float(pefa["minimum_output_t_h"])
    pefa_max_t_h = float(pefa["maximum_output_t_h"])
    pellet_capacity_t = float(pefa["inventory_capacity_t"])
    initial_pellet_inventory_t = float(pefa["initial_inventory_t"])
    if not 0.0 < pefa_min_t_h <= pefa_max_t_h:
        raise S44CModelBuilderError("Invalid C0 PeFa output range.")
    if not 0.0 <= initial_pellet_inventory_t <= pellet_capacity_t:
        raise S44CModelBuilderError("Invalid C0 pellet inventory contract.")
    model.pefa_pellet_output_t = Var(model.TIME, domain=NonNegativeReals)
    model.pefa_output_lower = Constraint(
        model.TIME,
        rule=lambda m, t: m.pefa_pellet_output_t[t]
        >= pefa_min_t_h * time_step_hours,
    )
    model.pefa_output_upper = Constraint(
        model.TIME,
        rule=lambda m, t: m.pefa_pellet_output_t[t]
        <= pefa_max_t_h * time_step_hours,
    )
    add_setpoint("pefa_pellet_output_t", "pefa", pefa)
    _add_pellet_origin_ledger(
        model,
        configuration="C0",
        time_step_hours=time_step_hours,
        imported_pellets_t_y=float(pefa["imported_pellets_t_y"]),
        initial_internal_inventory_t=initial_pellet_inventory_t,
        internal_inventory_capacity_t=pellet_capacity_t,
    )
    model.c0_temporal_plant_dynamics_status = (
        "user_authorized_development_policy_not_site_truth"
    )
    model.sifa_minimum_direction_intervals = direction_window
    model.sifa_minimum_direction_hours = direction_hours
    model.sifa_maximum_rate_step_t_h = sifa_rate_step_t_h
    model.c0_temporal_operating_ranges_t_h = {
        str(asset): tuple(float(value) for value in bounds)
        for asset, bounds in contract.get("active_operating_ranges_t_h", {}).items()
    }
    model.c0_kgf2_bf7_symmetry_status = (
        "controlled_symmetry_assumption_not_independent_measurement"
    )
    model.pefa_price_response_policy = (
        "bounded_endogenous_response_via_closed_fired_pellet_bus"
    )
    _add_normalized_capacity_contract(
        model,
        time_step_hours=time_step_hours,
        contract=contract,
        configuration="C0",
    )


def _build_c0_model(
    inputs: C0ExecutableInputs,
    *,
    time_step_hours: float = 1.0,
    fix_binary_schedule: bool = False,
    enable_minimal_wag_layer: bool = False,
    enable_internal_wag_power: bool = False,
    development_controller_activation: str = "none",
    development_controller_profile_weights: Mapping[str, Mapping[int, float]] | None = None,
    daily_production_guardrail: bool = False,
    rolling_production_deadline_targets_t: Mapping[int, float] | None = None,
    commitment_granularity: str = "hourly_binary",
    commitment_day_lengths: Collection[int] | None = None,
    continuous_must_run_activities: Collection[str] | None = None,
    c0_coke_chain_reconciliation: Mapping[str, float] | None = None,
    c0_fixed_schedule_hours_by_process: Mapping[str, Collection[int]] | None = None,
    c0_downstream_reference_routing: Mapping[str, Any] | None = None,
    c0_bf_material_interface: Mapping[str, float] | None = None,
    scrap_supply_ledger: Mapping[str, Any] | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    site_baseload_ng_mwh_h: float = 0.0,
    site_residual_steam_t_h: float = 0.0,
    site_residual_direct_co2_t_h: float = 0.0,
    external_procurement_flow_coefficients: Mapping[str, float] | None = None,
    bf_electricity_intensity_scale: float = 1.0,
    aggregate_generator_technical_interface: Mapping[str, Any] | None = None,
    full_site_energy_bridge: Mapping[str, Any] | None = None,
    hsm_source_mix_policy: Mapping[str, Any] | None = None,
    electricity_sale_sensitivity: Mapping[str, Any] | None = None,
    enforce_final_product_requirement: bool = True,
    recoverable_handoff_execution_steps: int | None = None,
    temporal_plant_dynamics: Mapping[str, Any] | None = None,
    initial_continuous_rate_t_h: Mapping[str, float] | None = None,
):
    if time_step_hours not in {1.0, 0.25}:
        raise S44CModelBuilderError("C0 model time step must be 1 hour or 15 minutes.")
    if time_step_hours != 1.0 and (fix_binary_schedule or c0_fixed_schedule_hours_by_process):
        raise S44CModelBuilderError(
            "Historical fixed-hour C0 schedules are not valid at quarter-hour resolution."
        )
    if commitment_granularity not in {"hourly_binary", "daily_binary_hourly_throughput"}:
        raise S44CModelBuilderError(f"Unsupported commitment granularity: {commitment_granularity}")
    if fix_binary_schedule and continuous_must_run_activities:
        raise S44CModelBuilderError(
            "C0 continuous must-run enforcement cannot be combined with a fixed binary schedule."
        )
    if external_procurement_flow_coefficients is not None:
        required = {
            "pci_t_per_t_hot_metal",
            "pefa_iron_ore_t_per_t_pellets",
        }
        missing = required.difference(external_procurement_flow_coefficients)
        if missing:
            raise S44CModelBuilderError(
                f"C0 external procurement flow coefficients are missing: {sorted(missing)}"
            )
        if any(
            float(external_procurement_flow_coefficients[key]) <= 0.0
            for key in required
        ):
            raise S44CModelBuilderError(
                "C0 external procurement flow coefficients must be positive."
            )
    if c0_coke_chain_reconciliation is not None:
        required = {"dry_coal_t_per_t_coke", "bf_coke_t_per_t_hot_metal"}
        missing = required.difference(c0_coke_chain_reconciliation)
        if missing:
            raise S44CModelBuilderError(f"C0 coke-chain reconciliation is missing: {sorted(missing)}")
        if any(float(c0_coke_chain_reconciliation[key]) <= 0.0 for key in required):
            raise S44CModelBuilderError("C0 coke-chain reconciliation factors must be positive.")
    if c0_downstream_reference_routing is not None:
        required = {
            "hsm_final_t_per_t_slab",
            "dsp_liquid_steel_input_t_per_t_coil",
            "dsp_final_product_horizon_cap_t",
            "dsp_final_product_max_t_h",
            "bof_hot_metal_t_per_t_liquid_steel",
            "bof_scrap_t_per_t_liquid_steel",
            "bof_total_scrap_horizon_cap_t",
            "bof_total_scrap_max_t_h",
        }
        missing = required.difference(c0_downstream_reference_routing)
        if missing:
            raise S44CModelBuilderError(
                f"C0 reference downstream routing is missing: {sorted(missing)}"
            )
        if any(
            float(c0_downstream_reference_routing[key]) <= 0.0
            for key in required
        ):
            raise S44CModelBuilderError("C0 reference downstream factors and cap must be positive.")
    model = ConcreteModel()
    model.TIME = RangeSet(0, inputs.horizon_hours - 1)
    model.time_step_hours = float(time_step_hours)
    model.horizon_steps = int(inputs.horizon_hours)
    model.physical_horizon_hours = float(inputs.horizon_hours) * time_step_hours
    process_names = tuple(inputs.process_limits)

    on_domain = UnitInterval if commitment_granularity == "daily_binary_hourly_throughput" else Binary
    for process_name in process_names:
        setattr(model, process_name, Var(model.TIME, domain=NonNegativeReals))
        setattr(model, f"{process_name}_on", Var(model.TIME, domain=on_domain))

    model.coke_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.sinter_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.hot_iron_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.cold_slab_inventory = Var(model.TIME, domain=NonNegativeReals)

    def _process_var(m, name, t):
        return getattr(m, name)[t]

    def _on_var(m, name, t):
        return getattr(m, f"{name}_on")[t]

    model.process_min = Constraint(
        process_names,
        model.TIME,
        rule=lambda m, name, t: _process_var(m, name, t) >= inputs.process_limits[name][0] * _on_var(m, name, t),
    )
    model.process_max = Constraint(
        process_names,
        model.TIME,
        rule=lambda m, name, t: _process_var(m, name, t) <= inputs.process_limits[name][1] * _on_var(m, name, t),
    )

    model.bf_activity_proxy = Expression(
        model.TIME,
        rule=lambda m, t: m.blast_furnace_6[t] + m.blast_furnace_7[t],
    )
    model.sinter_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.sinter_output_per_t_iron_ore * m.sintering_plant[t],
    )
    model.bf_hot_iron_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.bf_hot_iron_per_t_sinter * m.bf_activity_proxy[t],
    )
    model.bf6_hot_iron_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.bf_hot_iron_per_t_sinter * m.blast_furnace_6[t],
    )
    model.bf7_hot_iron_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.bf_hot_iron_per_t_sinter * m.blast_furnace_7[t],
    )
    if c0_bf_material_interface is None:
        model.bf_sinter_input = Expression(
            model.TIME, rule=lambda m, t: m.bf_activity_proxy[t]
        )
        model.bf_pellet_input_t = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
        model.c0_bf_material_interface_status = "legacy_activity_proxy_boundary"
    else:
        required_bf_interface = {
            "sinter_t_per_t_hot_metal",
            "pellets_t_per_t_hot_metal",
        }
        missing_bf_interface = required_bf_interface.difference(
            c0_bf_material_interface
        )
        if missing_bf_interface:
            raise S44CModelBuilderError(
                "C0 BF material interface is missing: "
                f"{sorted(missing_bf_interface)}"
            )
        sinter_per_hot_metal = float(
            c0_bf_material_interface["sinter_t_per_t_hot_metal"]
        )
        pellets_per_hot_metal = float(
            c0_bf_material_interface["pellets_t_per_t_hot_metal"]
        )
        if sinter_per_hot_metal <= 0.0 or pellets_per_hot_metal <= 0.0:
            raise S44CModelBuilderError(
                "C0 BF physical burden coefficients must be positive."
            )
        model.bf_sinter_input = Expression(
            model.TIME,
            rule=lambda m, t: sinter_per_hot_metal * m.bf_hot_iron_output[t],
        )
        model.bf_pellet_input_t = Expression(
            model.TIME,
            rule=lambda m, t: pellets_per_hot_metal * m.bf_hot_iron_output[t],
        )
        model.c0_bf_material_interface_status = (
            "annual_mer_reconciliation_separate_from_bf_activity_proxy"
        )
    if c0_downstream_reference_routing is None:
        model.bof_crude_steel_output = Expression(
            model.TIME,
            rule=lambda m, t: inputs.bof_crude_steel_per_t_hot_iron * m.basic_oxygen_furnace[t],
        )
        model.c0_bof_scrap_input = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.c0_bof_material_loss = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.c0_bof_material_balance_residual = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    else:
        bof_hot_metal_per_t_ls = float(
            c0_downstream_reference_routing["bof_hot_metal_t_per_t_liquid_steel"]
        )
        bof_scrap_per_t_ls = float(
            c0_downstream_reference_routing["bof_scrap_t_per_t_liquid_steel"]
        )
        bof_loss_per_t_ls = bof_hot_metal_per_t_ls + bof_scrap_per_t_ls - 1.0
        if bof_loss_per_t_ls < 0.0:
            raise S44CModelBuilderError(
                "C0 BOF hot-metal plus scrap inputs must cover liquid steel output."
            )
        model.bof_crude_steel_output = Expression(
            model.TIME,
            rule=lambda m, t: m.basic_oxygen_furnace[t] / bof_hot_metal_per_t_ls,
        )
        model.c0_bof_scrap_input = Expression(
            model.TIME,
            rule=lambda m, t: bof_scrap_per_t_ls * m.bof_crude_steel_output[t],
        )
        model.c0_bof_material_loss = Expression(
            model.TIME,
            rule=lambda m, t: bof_loss_per_t_ls * m.bof_crude_steel_output[t],
        )
        model.c0_bof_material_balance_residual = Expression(
            model.TIME,
            rule=lambda m, t: (
                m.basic_oxygen_furnace[t]
                + m.c0_bof_scrap_input[t]
                - m.bof_crude_steel_output[t]
                - m.c0_bof_material_loss[t]
            ),
        )
        model.c0_bof_total_scrap_cap = Constraint(
            expr=sum(model.c0_bof_scrap_input[t] for t in model.TIME)
            <= float(c0_downstream_reference_routing["bof_total_scrap_horizon_cap_t"])
        )
        model.c0_bof_hourly_scrap_cap = Constraint(
            model.TIME,
            rule=lambda m, t: m.c0_bof_scrap_input[t]
            <= float(c0_downstream_reference_routing["bof_total_scrap_max_t_h"]),
        )
        if scrap_supply_ledger is not None:
            required_scrap = {
                "external_scrap_supply_cap_t",
                "internal_scrap_supply_cap_t",
                "site_total_scrap_supply_cap_t",
                "bof_scrap_supply_cap_t",
            }
            missing_scrap = required_scrap.difference(scrap_supply_ledger)
            if missing_scrap:
                raise S44CModelBuilderError(
                    f"C0 scrap-origin ledger is missing: {sorted(missing_scrap)}"
                )
            model.external_scrap_to_bof_t = Var(
                model.TIME, domain=NonNegativeReals
            )
            model.internal_scrap_to_bof_t = Var(
                model.TIME, domain=NonNegativeReals
            )
            model.external_scrap_to_eaf_t = Expression(
                model.TIME, rule=lambda _m, _t: 0.0
            )
            model.internal_scrap_to_eaf_t = Expression(
                model.TIME, rule=lambda _m, _t: 0.0
            )
            model.c0_bof_scrap_origin_balance = Constraint(
                model.TIME,
                rule=lambda m, t: m.external_scrap_to_bof_t[t]
                + m.internal_scrap_to_bof_t[t]
                == m.c0_bof_scrap_input[t],
            )
            model.c0_external_scrap_cap = Constraint(
                expr=sum(model.external_scrap_to_bof_t[t] for t in model.TIME)
                <= float(scrap_supply_ledger["external_scrap_supply_cap_t"])
            )
            model.c0_internal_scrap_cap = Constraint(
                expr=sum(model.internal_scrap_to_bof_t[t] for t in model.TIME)
                <= float(scrap_supply_ledger["internal_scrap_supply_cap_t"])
            )
            model.c0_site_scrap_cap = Constraint(
                expr=sum(model.c0_bof_scrap_input[t] for t in model.TIME)
                <= float(scrap_supply_ledger["site_total_scrap_supply_cap_t"])
            )
            model.c0_bof_origin_scrap_cap = Constraint(
                expr=sum(model.c0_bof_scrap_input[t] for t in model.TIME)
                <= float(scrap_supply_ledger["bof_scrap_supply_cap_t"])
            )
            model.c0_scrap_origin_policy = (
                "external_and_internal_nonrenewable_annual_origin_ledger"
            )
            deadline_components = {
                "external_scrap_supply_deadline_caps_t": (
                    "c0_external_scrap_deadline_caps",
                    lambda t: model.external_scrap_to_bof_t[t],
                ),
                "internal_scrap_supply_deadline_caps_t": (
                    "c0_internal_scrap_deadline_caps",
                    lambda t: model.internal_scrap_to_bof_t[t],
                ),
                "bof_scrap_supply_deadline_caps_t": (
                    "c0_bof_scrap_deadline_caps",
                    lambda t: model.c0_bof_scrap_input[t],
                ),
                "site_total_scrap_supply_deadline_caps_t": (
                    "c0_site_scrap_deadline_caps",
                    lambda t: model.c0_bof_scrap_input[t],
                ),
            }
            for ledger_key, (component_name, expression_at) in deadline_components.items():
                if ledger_key not in scrap_supply_ledger:
                    continue
                constraint_list = ConstraintList()
                setattr(model, component_name, constraint_list)
                for deadline, cap in sorted(
                    scrap_supply_ledger[ledger_key].items()
                ):
                    endpoint = int(deadline)
                    if endpoint <= 0 or endpoint > inputs.horizon_hours:
                        raise S44CModelBuilderError(
                            "C0 scrap deadline lies outside the physical horizon."
                        )
                    constraint_list.add(
                        sum(expression_at(t) for t in range(endpoint))
                        <= float(cap)
                    )
    if c0_downstream_reference_routing is None:
        model.c0_dsp_liquid_steel_input = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.c0_dsp_final_product_output = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.c0_hsm_final_product_output = Expression(
            model.TIME,
            rule=lambda m, t: inputs.hsm_final_per_t_crude_steel * m.hot_strip_mill[t],
        )
    else:
        hsm_final_per_t_slab = float(c0_downstream_reference_routing["hsm_final_t_per_t_slab"])
        dsp_input_per_t_coil = float(c0_downstream_reference_routing["dsp_liquid_steel_input_t_per_t_coil"])
        dsp_horizon_cap_t = float(c0_downstream_reference_routing["dsp_final_product_horizon_cap_t"])
        model.c0_dsp_liquid_steel_input = Var(model.TIME, domain=NonNegativeReals)
        model.c0_dsp_from_current_bof = Constraint(
            model.TIME,
            rule=lambda m, t: m.c0_dsp_liquid_steel_input[t] <= m.bof_crude_steel_output[t],
        )
        model.c0_dsp_final_product_output = Expression(
            model.TIME,
            rule=lambda m, t: m.c0_dsp_liquid_steel_input[t] / dsp_input_per_t_coil,
        )
        model.c0_dsp_material_loss = Expression(
            model.TIME,
            rule=lambda m, t: m.c0_dsp_liquid_steel_input[t] - m.c0_dsp_final_product_output[t],
        )
        model.c0_dsp_final_product_horizon_cap = Constraint(
            expr=sum(model.c0_dsp_final_product_output[t] for t in model.TIME) <= dsp_horizon_cap_t
        )
        model.c0_dsp_final_product_hourly_cap = Constraint(
            model.TIME,
            rule=lambda m, t: m.c0_dsp_final_product_output[t]
            <= float(c0_downstream_reference_routing["dsp_final_product_max_t_h"]),
        )
        model.c0_hsm_final_product_output = Expression(
            model.TIME,
            rule=lambda m, t: hsm_final_per_t_slab * m.hot_strip_mill[t],
        )
    if c0_downstream_reference_routing is None:
        model.c0_dsp_material_loss = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.final_product_output = Expression(
        model.TIME,
        rule=lambda m, t: m.c0_hsm_final_product_output[t] + m.c0_dsp_final_product_output[t],
    )
    if c0_coke_chain_reconciliation is None:
        model.coke_output_kgf1 = Expression(model.TIME, rule=lambda m, t: m.coking_plant_1[t])
        model.coke_output_kgf2 = Expression(model.TIME, rule=lambda m, t: m.coking_plant_2[t])
        model.coke_output = Expression(model.TIME, rule=lambda m, t: m.coke_output_kgf1[t] + m.coke_output_kgf2[t])
        model.bf_coke_demand = Expression(
            model.TIME,
            rule=lambda m, t: inputs.coke_per_t_sinter * m.bf_sinter_input[t],
        )
    else:
        dry_coal_per_t_coke = float(c0_coke_chain_reconciliation["dry_coal_t_per_t_coke"])
        bf_coke_per_t_hot_metal = float(c0_coke_chain_reconciliation["bf_coke_t_per_t_hot_metal"])
        model.c0_dry_coal_t_per_t_coke = dry_coal_per_t_coke
        model.c0_bf_coke_t_per_t_hot_metal = bf_coke_per_t_hot_metal
        model.coke_output_kgf1 = Expression(
            model.TIME,
            rule=lambda m, t: m.coking_plant_1[t] / dry_coal_per_t_coke,
        )
        model.coke_output_kgf2 = Expression(
            model.TIME,
            rule=lambda m, t: m.coking_plant_2[t] / dry_coal_per_t_coke,
        )
        model.coke_output = Expression(model.TIME, rule=lambda m, t: m.coke_output_kgf1[t] + m.coke_output_kgf2[t])
        model.bf_coke_demand = Expression(
            model.TIME,
            rule=lambda m, t: bf_coke_per_t_hot_metal * m.bf_hot_iron_output[t],
        )
    if temporal_plant_dynamics is not None:
        if initial_continuous_rate_t_h is None:
            raise S44CModelBuilderError(
                "C0 temporal plant dynamics require rolling boundary rates."
            )
        _add_c0_temporal_plant_dynamics(
            model,
            time_step_hours=time_step_hours,
            contract=temporal_plant_dynamics,
            initial_rate_t_h=initial_continuous_rate_t_h,
        )
        _add_downstream_temporal_contract(
            model,
            time_step_hours=time_step_hours,
            contract=temporal_plant_dynamics,
            dsp_component_name="c0_dsp_final_product_output",
            initial_rate_t_h=initial_continuous_rate_t_h,
        )
    elif recoverable_handoff_execution_steps is not None:
        raise S44CModelBuilderError(
            "A recoverable C0 temporal handoff requires the closed PeFa bus."
        )
    controller_flags = _development_controller_flags(development_controller_activation)
    if development_controller_activation != "none" and not enable_minimal_wag_layer:
        raise S44CModelBuilderError("Development controller activation requires the carrier-specific WAG layer.")
    if enable_minimal_wag_layer:
        _add_c0_minimal_wag_layer(
            model,
            inputs,
            time_step_hours=time_step_hours,
            enable_internal_wag_power=enable_internal_wag_power,
            gross_electricity_rule=(
                (lambda m, t: m.development_controller_electricity_mwh[t] + m.electricity_boundary_development_mwh[t])
                if controller_flags["electricity_boundary"]
                else (
                    (lambda _m, _t: C0_SITE_ELECTRICITY_PROXY_MWH_H * time_step_hours)
                    if enable_internal_wag_power or controller_flags["generator"]
                    else (lambda _m, _t: 0.0)
                )
            ),
            development_profile=(load_development_controller_profile("C0_current_BF_BOF_reference") if development_controller_activation != "none" else None),
            enable_hsm_controller=controller_flags["hsm"],
            enable_pefa_controller=controller_flags["pefa"],
            enable_boiler_scaffold=controller_flags["boiler"],
            enable_generator_interface=controller_flags["generator"],
            enable_electricity_boundary_controller=controller_flags["electricity_boundary"],
            retire_legacy_boiler_placeholder=development_controller_activation != "none",
            development_controller_profile_weights=development_controller_profile_weights,
            linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
            site_background_electricity_mwh_h=site_background_electricity_mwh_h,
            site_baseload_ng_mwh_h=site_baseload_ng_mwh_h,
            site_residual_steam_t_h=site_residual_steam_t_h,
            site_residual_direct_co2_t_h=site_residual_direct_co2_t_h,
            bf_electricity_intensity_scale=bf_electricity_intensity_scale,
            aggregate_generator_technical_interface=aggregate_generator_technical_interface,
            full_site_energy_bridge=full_site_energy_bridge,
            hsm_source_mix_policy=hsm_source_mix_policy,
            electricity_sale_sensitivity=electricity_sale_sensitivity,
            kgf_underfiring_activity_rule=(
                (lambda m, t: m.coke_output_kgf1[t]) if c0_coke_chain_reconciliation is not None else None
            ),
            kgf_underfiring_activity_rule_kgf2=(
                (lambda m, t: m.coke_output_kgf2[t]) if c0_coke_chain_reconciliation is not None else None
            ),
            hsm_output_activity_rule=lambda m, t: m.c0_hsm_final_product_output[t],
            dsp_output_activity_rule=lambda m, t: m.c0_dsp_final_product_output[t],
            bf_hot_metal_activity_rule=lambda m, t: m.bf_hot_iron_output[t],
        )
    else:
        model.bfg_generated = Expression(
            model.TIME,
            rule=lambda m, t: inputs.bfg_nm3_per_t_hot_iron * m.bf_hot_iron_output[t],
        )
        model.cog_generated = Expression(
            model.TIME,
            rule=lambda m, t: inputs.cog_m3_per_t_dry_coal * (m.coking_plant_1[t] + m.coking_plant_2[t]),
        )
        model.bofg_generated = Expression(
            model.TIME,
            rule=lambda m, t: inputs.bofg_nm3_per_t_liquid_steel * m.bof_crude_steel_output[t],
        )
        model.wag_generated = Expression(
            model.TIME,
            rule=lambda m, t: m.bfg_generated[t] + m.cog_generated[t] + m.bofg_generated[t],
        )

    model.coke_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.coke_inventory[t]
        == (inputs.coke_store_initial_t if t == 0 else m.coke_inventory[t - 1])
        + m.coke_output[t]
        - m.bf_coke_demand[t],
    )
    model.sinter_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.sinter_inventory[t]
        == (inputs.sinter_store_initial_t if t == 0 else m.sinter_inventory[t - 1])
        + m.sinter_output[t]
        - m.bf_sinter_input[t],
    )
    model.hot_iron_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.hot_iron_inventory[t]
        == (inputs.hot_iron_store_initial_t if t == 0 else m.hot_iron_inventory[t - 1])
        + m.bf_hot_iron_output[t]
        - m.basic_oxygen_furnace[t],
    )
    model.cold_slab_balance = Constraint(
        model.TIME,
        rule=(
            lambda m, t: m.cold_slab_inventory[t]
            == (inputs.cold_slab_store_initial_t if t == 0 else m.cold_slab_inventory[t - 1])
            + m.bof_crude_steel_output[t]
            - m.c0_dsp_liquid_steel_input[t]
            - m.hot_strip_mill[t]
        )
        if c0_downstream_reference_routing is not None
        else (
            lambda m, t: m.cold_slab_inventory[t]
            == (inputs.cold_slab_store_initial_t if t == 0 else m.cold_slab_inventory[t - 1])
            + m.bof_crude_steel_output[t]
            - m.hot_strip_mill[t]
        ),
    )
    model.coke_capacity = Constraint(model.TIME, rule=lambda m, t: m.coke_inventory[t] <= inputs.coke_store_capacity_t)
    model.sinter_capacity = Constraint(model.TIME, rule=lambda m, t: m.sinter_inventory[t] <= inputs.sinter_store_capacity_t)
    model.hot_iron_capacity = Constraint(model.TIME, rule=lambda m, t: m.hot_iron_inventory[t] <= inputs.hot_iron_store_capacity_t)
    model.cold_slab_capacity = Constraint(model.TIME, rule=lambda m, t: m.cold_slab_inventory[t] <= inputs.cold_slab_store_capacity_t)
    model.coke_terminal = Constraint(expr=model.coke_inventory[inputs.horizon_hours - 1] == inputs.coke_store_initial_t)
    model.sinter_terminal = Constraint(expr=model.sinter_inventory[inputs.horizon_hours - 1] == inputs.sinter_store_initial_t)
    model.hot_iron_terminal = Constraint(expr=model.hot_iron_inventory[inputs.horizon_hours - 1] == inputs.hot_iron_store_initial_t)
    model.cold_slab_terminal = Constraint(expr=model.cold_slab_inventory[inputs.horizon_hours - 1] == inputs.cold_slab_store_initial_t)
    if (
        c0_downstream_reference_routing is not None
        and "reference_validation_bands" in c0_downstream_reference_routing
    ):
        c0_reference_bands = c0_downstream_reference_routing["reference_validation_bands"]
        reference_expressions = {
            "bof_liquid_steel": sum(model.bof_crude_steel_output[t] for t in model.TIME),
            "hsm_final_output": sum(model.c0_hsm_final_product_output[t] for t in model.TIME),
            "dsp_final_output": sum(model.c0_dsp_final_product_output[t] for t in model.TIME),
        }
        unknown_bands = set(c0_reference_bands).difference(reference_expressions)
        if unknown_bands:
            raise S44CModelBuilderError(f"Unknown C0 reference band(s): {sorted(unknown_bands)}")
        for band_id, band in c0_reference_bands.items():
            _add_reference_horizon_band(
                model,
                constraint_id=f"c0_reference_{band_id}",
                expression=reference_expressions[band_id],
                band=band,
            )
        c0_deadlines = c0_downstream_reference_routing.get(
            "reference_band_deadline_hours"
        )
        if c0_deadlines is not None:
            _add_reference_cumulative_deadline_bands(
                model,
                constraint_prefix="c0_reference_deadline",
                hourly_expressions={
                    "bof_liquid_steel": model.bof_crude_steel_output,
                    "hsm_final_output": model.c0_hsm_final_product_output,
                    "dsp_final_output": model.c0_dsp_final_product_output,
                },
                bands=c0_reference_bands,
                deadline_hours=c0_deadlines,
                horizon_hours=inputs.horizon_hours,
                explicit_deadline_bands=c0_downstream_reference_routing.get(
                    "reference_deadline_bands"
                ),
            )
    if enforce_final_product_requirement:
        _add_final_product_requirement(
            model,
            final_product_target_t=inputs.final_product_target_t,
            quota_lower_bound=rolling_production_deadline_targets_t is not None,
        )
    if commitment_granularity == "daily_binary_hourly_throughput":
        _add_day_commitment_layer(
            model,
            horizon_hours=inputs.horizon_hours,
            commitment_definitions={
                name: (name, f"{name}_on", inputs.process_limits[name][0])
                for name in process_names
            },
            commitment_day_lengths=commitment_day_lengths,
            time_step_hours=time_step_hours,
        )
    if daily_production_guardrail:
        _add_daily_production_guardrail(model, inputs)
    if rolling_production_deadline_targets_t is not None:
        _add_rolling_production_deadline_envelope(
            model,
            horizon_hours=inputs.horizon_hours,
            final_product_target_t=inputs.final_product_target_t,
            deadline_targets_t=rolling_production_deadline_targets_t,
        )
    if fix_binary_schedule:
        _apply_c0_static_binary_schedule(
            model,
            inputs,
            process_names,
            wag_compatible=enable_minimal_wag_layer,
            fixed_schedule_hours_by_process=c0_fixed_schedule_hours_by_process,
        )
    _enforce_continuous_must_run_availability(
        model,
        activity_to_on_var={name: f"{name}_on" for name in process_names},
        activities=continuous_must_run_activities,
        configuration_id="C0_current_BF_BOF_reference",
    )
    _apply_c0_inventory_terminal_policy(
        model,
        recoverable_handoff_execution_steps=recoverable_handoff_execution_steps,
    )
    if external_procurement_flow_coefficients is None:
        model.bf_pci_input_t = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
        model.pefa_iron_ore_input_t = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
    else:
        pci_factor = float(
            external_procurement_flow_coefficients["pci_t_per_t_hot_metal"]
        )
        pefa_ore_factor = float(
            external_procurement_flow_coefficients[
                "pefa_iron_ore_t_per_t_pellets"
            ]
        )
        model.bf_pci_input_t = Expression(
            model.TIME,
            rule=lambda m, t: pci_factor * m.bf_hot_iron_output[t],
        )
        model.pefa_iron_ore_input_t = Expression(
            model.TIME,
            rule=lambda m, t: pefa_ore_factor * m.pefa_pellet_output_t[t],
        )
    flare_tiebreaker = 0.0
    controller_tiebreaker = 0.0
    if enable_minimal_wag_layer:
        flare_tiebreaker = 1e-6 * sum(
            model.bfg_flared[t] + model.cog_flared[t] + model.bofg_flared[t]
            for t in model.TIME
        )
    if controller_flags["hsm"]:
        # Existing C5l's BFG-first diagnostic order is represented only as a
        # tiny non-economic tie-breaker: WAG precedes named NG, and flaring
        # still beats unnecessary NG use.
        controller_tiebreaker = sum(
            1e-7 * (model.cog_to_hsm[t] + model.bofg_to_hsm[t])
            + 1e-5
            * (
                model.ng_to_hsm_mwh[t]
                + model.ng_to_pefa_malerij_mwh[t]
                + model.ng_to_pefa_branderij_mwh[t]
                + model.ng_to_boiler_mwh[t]
            )
            for t in model.TIME
        )
    if full_site_energy_bridge is not None:
        controller_tiebreaker += 1e-5 * sum(
            model.flexible_other_site_heat_ng_mwh[t] for t in model.TIME
        )
    day_commitment_tiebreaker = (
        1e-4 * sum(getattr(model, f"{name}_day_on")[d] for name in process_names for d in model.COMMITMENT_DAY)
        if commitment_granularity == "daily_binary_hourly_throughput"
        else 0.0
    )
    model.static_price_naive_objective = Objective(
        expr=sum(getattr(model, f"{name}_on")[t] for name in process_names for t in model.TIME)
        + 1e-8
        * sum(
            model.coke_inventory[t]
            + model.sinter_inventory[t]
            + model.hot_iron_inventory[t]
            + model.cold_slab_inventory[t]
            for t in model.TIME
        )
        + flare_tiebreaker
        + controller_tiebreaker
        + day_commitment_tiebreaker,
        sense=minimize,
    )
    return model


def _build_c1_inputs(
    tables: UnifiedInputTables,
    *,
    horizon_hours_override: int | None = None,
    target_multiplier: float = 1.0,
    include_retained_bf_bof: bool = False,
) -> C1ExecutableInputs:
    process_units = [row for row in tables.tables["process_units.csv"] if _is_executable(row)]
    drp = _first_row(process_units, configuration_id="C1_phase1_BF_BOF_plus_DRP_EAF", process_id="C1_DRP")
    eaf = _first_row(process_units, configuration_id="C1_phase1_BF_BOF_plus_DRP_EAF", process_id="C1_EAF")
    io_rows = [row for row in tables.tables["process_io_coefficients.csv"] if _is_executable(row)]
    energy_rows = [row for row in tables.tables["process_energy_intensities.csv"] if _is_executable(row)]
    buffer_rows = [row for row in tables.tables["buffers_and_stores.csv"] if _is_executable(row)]

    drp_yield = _as_float(
        _first_row(io_rows, process_id="C1_DRP", input_material="pellets", output_material="DRI")["coefficient"],
        field_name="C1_DRP pellets_to_DRI",
    )
    eaf_yield = _as_float(
        _first_row(io_rows, process_id="C1_EAF", input_material="DRI", output_material="liquid_steel")["coefficient"],
        field_name="C1_EAF DRI_to_liquid_steel",
    )
    buffer = _first_row(
        buffer_rows,
        configuration_id="C1_phase1_BF_BOF_plus_DRP_EAF",
        buffer_id="C1_DRI_BUFFER",
    )
    initial_rule = buffer["initial_rule"]
    buffer_capacity = _as_float(buffer["capacity"], field_name="C1_DRI_BUFFER capacity")
    if initial_rule != "zero_for_smoke":
        raise S44CModelBuilderError("S4.4c currently supports only zero_for_smoke DRI initial inventory.")

    return C1ExecutableInputs(
        horizon_hours=_horizon_hours(tables, horizon_hours_override),
        final_product_target_t=_target_for_configuration(tables, "C1_phase1_BF_BOF_plus_DRP_EAF", target_multiplier),
        drp_capacity_t_pellets_h=_parse_pu_capacity(drp["rate_unit"]),
        drp_min_pu=_as_float(drp["min_rate"], field_name="C1_DRP min_rate"),
        drp_max_pu=_as_float(drp["max_rate"], field_name="C1_DRP max_rate"),
        drp_ramp_pu_per_h=_as_float(drp["ramp_up"], field_name="C1_DRP ramp_up"),
        drp_yield_t_dri_per_t_pellets=drp_yield,
        drp_electricity_mwh_per_t_pellets=_optional_float(
            energy_rows,
            0.0,
            process_id="C1_DRP",
            carrier="electricity",
            direction="input",
        ),
        drp_ng_nm3_per_t_pellets=_optional_float(
            energy_rows,
            0.0,
            process_id="C1_DRP",
            carrier="natural_gas",
            direction="input",
        ),
        drp_o2_t_per_t_pellets=_optional_float(
            energy_rows,
            0.0,
            process_id="C1_DRP",
            carrier="oxygen",
            direction="input",
        ),
        eaf_capacity_t_dri_h=_parse_pu_capacity(eaf["rate_unit"]),
        eaf_min_pu=_as_float(eaf["min_rate"], field_name="C1_EAF min_rate"),
        eaf_max_pu=_as_float(eaf["max_rate"], field_name="C1_EAF max_rate"),
        eaf_yield_t_final_per_t_dri=eaf_yield,
        eaf_electricity_mwh_per_t_dri=_optional_float(
            energy_rows,
            0.0,
            process_id="C1_EAF",
            carrier="electricity",
            direction="input",
        ),
        eaf_o2_t_per_t_dri=_optional_float(
            energy_rows,
            0.0,
            process_id="C1_EAF",
            carrier="oxygen",
            direction="input",
        ),
        eaf_scrap_t_per_t_dri=_optional_float(
            io_rows,
            0.0,
            process_id="C1_EAF",
            input_material="scrap",
            output_material="liquid_steel",
        ),
        dri_buffer_capacity_t=buffer_capacity,
        dri_buffer_initial_t=0.0,
        retained_bf_bof=_build_retained_bf_bof_inputs(
            tables,
            configuration_id="C1_phase1_BF_BOF_plus_DRP_EAF",
        )
        if include_retained_bf_bof
        else None,
    )


def _build_c1_hybrid_model(
    inputs: C1ExecutableInputs,
    *,
    time_step_hours: float = 1.0,
    enable_minimal_wag_layer: bool = False,
    enable_internal_wag_power: bool = False,
    development_controller_activation: str = "none",
    hsm_rolling_electricity_mwh_per_t_hrc_override: float | None = None,
    development_controller_profile_weights: Mapping[str, Mapping[int, float]] | None = None,
    daily_production_guardrail: bool = False,
    rolling_production_deadline_targets_t: Mapping[int, float] | None = None,
    fix_c1_hybrid_schedule: bool = False,
    c1_retained_route_policy: str = "target_share",
    commitment_granularity: str = "hourly_binary",
    commitment_day_lengths: Collection[int] | None = None,
    eaf_material_balance: Mapping[str, float] | None = None,
    bof_material_balance: Mapping[str, float] | None = None,
    scrap_supply_ledger: Mapping[str, Any] | None = None,
    c1_bf_material_interface: Mapping[str, Any] | None = None,
    c1_metallics_sensitivity: Mapping[str, Any] | None = None,
    downstream_origin_routing: Mapping[str, float] | None = None,
    c1_liquid_steel_route_band: Mapping[str, float] | None = None,
    continuous_must_run_activities: Collection[str] | None = None,
    c0_coke_chain_reconciliation: Mapping[str, float] | None = None,
    c1_coke_chain_reconciliation: Mapping[str, float] | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    site_baseload_ng_mwh_h: float = 0.0,
    site_residual_steam_t_h: float = 0.0,
    site_residual_direct_co2_t_h: float = 0.0,
    hsm_carrier_precedence: Collection[str] | None = None,
    hsm_eligible_carriers: Collection[str] | None = None,
    hsm_source_mix_policy: Mapping[str, Any] | None = None,
    generator_interface_cap_mode: str = "inherited_profile",
    generator_unit_interface: Mapping[str, Any] | None = None,
    c1_energy_boundary: Mapping[str, float] | None = None,
    eaf_secondary_electricity_mwh_per_t_ls_override: float | None = None,
    dsp_electricity_mwh_per_t_coil_override: float | None = None,
    external_procurement_flow_coefficients: Mapping[str, float] | None = None,
    bf_electricity_intensity_scale: float = 1.0,
    eaf_heat_state_parameters: EAFHeatStateParameters | None = None,
    initial_drp_pellet_input_t: float | None = None,
    initial_vn25_output_mw: float | None = None,
    enforce_final_product_requirement: bool = True,
    recoverable_handoff_execution_steps: int | None = None,
    temporal_plant_dynamics: Mapping[str, Any] | None = None,
    initial_continuous_rate_t_h: Mapping[str, float] | None = None,
    recoverable_dri_tail_state: bool = False,
    experimental_self_use_calibration: Mapping[str, Any] | None = None,
    experimental_process_electricity_overlay: Mapping[str, Any] | None = None,
    experimental_ng_service_calibration: Mapping[str, Any] | None = None,
    experimental_coal_wag_calibration: Mapping[str, Any] | None = None,
):
    if time_step_hours not in {1.0, 0.25}:
        raise S44CModelBuilderError("C1 model time step must be 1 hour or 15 minutes.")
    if time_step_hours != 1.0 and fix_c1_hybrid_schedule:
        raise S44CModelBuilderError(
            "Historical fixed-hour C1 schedules are not valid at quarter-hour resolution."
        )
    heat_state_active = bool(
        eaf_heat_state_parameters is not None
        and eaf_heat_state_parameters.active
    )
    if heat_state_active and time_step_hours not in {0.25, 1.0}:
        raise S44CModelBuilderError(
            "The discrete EAF heat-state component requires either the shared "
            "15-minute grid or the hourly grid with internal EAF batch subslots."
        )
    if initial_drp_pellet_input_t is not None and float(initial_drp_pellet_input_t) < 0.0:
        raise S44CModelBuilderError("Initial DRP pellet input cannot be negative.")
    if commitment_granularity not in {"hourly_binary", "daily_binary_hourly_throughput"}:
        raise S44CModelBuilderError(f"Unsupported commitment granularity: {commitment_granularity}")
    if external_procurement_flow_coefficients is not None:
        required = {
            "pci_t_per_t_hot_metal",
            "pefa_iron_ore_t_per_t_pellets",
        }
        missing = required.difference(external_procurement_flow_coefficients)
        if missing:
            raise S44CModelBuilderError(
                f"C1 external procurement flow coefficients are missing: {sorted(missing)}"
            )
        if any(
            float(external_procurement_flow_coefficients[key]) <= 0.0
            for key in required
        ):
            raise S44CModelBuilderError(
                "C1 external procurement flow coefficients must be positive."
            )
    if c1_energy_boundary is not None:
        required_energy = {
            "drp_ng_gj_per_t_dri",
            "drp_electricity_mwh_per_t_dri",
            "eaf_arc_electricity_mwh_per_t_liquid_steel",
            "eaf_ng_gj_per_t_liquid_steel",
            "natural_gas_lhv_mj_per_nm3",
        }
        missing_energy = required_energy.difference(c1_energy_boundary)
        if missing_energy:
            raise S44CModelBuilderError(
                f"C1 source-backed energy boundary is missing: {sorted(missing_energy)}"
            )
        if any(float(c1_energy_boundary[key]) <= 0.0 for key in required_energy):
            raise S44CModelBuilderError("C1 source-backed energy-boundary values must be positive.")
    if eaf_material_balance is not None:
        required = {"hdri_t_per_t_liquid_steel", "scrap_t_per_t_liquid_steel"}
        if scrap_supply_ledger is None:
            required.add("scrap_supply_cap_t")
        missing = required.difference(eaf_material_balance)
        if missing:
            raise S44CModelBuilderError(f"C1 EAF material balance is missing: {sorted(missing)}")
    if bof_material_balance is not None:
        required = {"hot_metal_t_per_t_liquid_steel", "scrap_t_per_t_liquid_steel"}
        missing = required.difference(bof_material_balance)
        if missing:
            raise S44CModelBuilderError(f"C1 BOF material balance is missing: {sorted(missing)}")
    if scrap_supply_ledger is not None:
        required = {
            "site_total_scrap_supply_cap_t",
            "bof_scrap_supply_cap_t",
            "eaf_scrap_supply_cap_t",
        }
        missing = required.difference(scrap_supply_ledger)
        if missing:
            raise S44CModelBuilderError(f"C1 scrap supply ledger is missing: {sorted(missing)}")
        if bof_material_balance is None or eaf_material_balance is None:
            raise S44CModelBuilderError("C1 scrap supply ledger requires both BOF and EAF named material balances.")
        deadline_keys = {
            "site_total_scrap_supply_deadline_caps_t",
            "bof_scrap_supply_deadline_caps_t",
            "eaf_scrap_supply_deadline_caps_t",
        }
        supplied_deadline_keys = deadline_keys.intersection(scrap_supply_ledger)
        if supplied_deadline_keys and supplied_deadline_keys != deadline_keys:
            raise S44CModelBuilderError(
                "C1 rolling scrap deadlines require site, BOF and EAF cap mappings together."
            )
        origin_keys = {
            "external_scrap_supply_cap_t",
            "internal_scrap_supply_cap_t",
        }
        supplied_origin_keys = origin_keys.intersection(scrap_supply_ledger)
        if supplied_origin_keys and supplied_origin_keys != origin_keys:
            raise S44CModelBuilderError(
                "C1 origin-tagged scrap requires external and internal caps together."
            )
        origin_deadline_keys = {
            "external_scrap_supply_deadline_caps_t",
            "internal_scrap_supply_deadline_caps_t",
        }
        supplied_origin_deadlines = origin_deadline_keys.intersection(
            scrap_supply_ledger
        )
        if supplied_origin_deadlines and supplied_origin_deadlines != origin_deadline_keys:
            raise S44CModelBuilderError(
                "C1 rolling origin-tagged scrap deadlines require external and "
                "internal mappings together."
            )
        if supplied_origin_deadlines and supplied_origin_keys != origin_keys:
            raise S44CModelBuilderError(
                "C1 rolling origin-tagged scrap deadlines require origin horizon caps."
            )
    if c1_bf_material_interface is not None:
        required = {
            "activity_quantity_role",
            "activity_rate_unit",
            "hot_metal_t_per_t_represented_bf_activity",
            "sinter_t_per_t_hot_metal",
            "annual_sinter_anchor_t_y",
            "annual_hot_metal_anchor_t_y",
        }
        missing = required.difference(c1_bf_material_interface)
        if missing:
            raise S44CModelBuilderError(
                f"C1 BF material interface is missing: {sorted(missing)}"
            )
        if str(c1_bf_material_interface["activity_quantity_role"]) != (
            "governed_represented_bf_activity_proxy"
        ):
            raise S44CModelBuilderError(
                "C1 BF6 120-170 must remain a governed represented-activity proxy."
            )
        if str(c1_bf_material_interface["activity_rate_unit"]) != (
            "t_represented_bf_activity/h"
        ):
            raise S44CModelBuilderError(
                "C1 BF6 activity must not be labelled as physical sinter throughput."
            )
        if any(
            float(c1_bf_material_interface[key]) <= 0.0
            for key in required.difference(
                {"activity_quantity_role", "activity_rate_unit"}
            )
        ):
            raise S44CModelBuilderError(
                "C1 BF material-interface factors and anchors must be positive."
            )
    metallics_mode = "base"
    dri_thermal_state_mode = "generic_dri_buffer"
    dri_thermal_state_active = False
    if c1_metallics_sensitivity is not None:
        metallics_mode = str(c1_metallics_sensitivity.get("mode", "base"))
        if metallics_mode not in {"base", "hbi", "high_scrap"}:
            raise S44CModelBuilderError(
                f"Unsupported C1 metallics sensitivity mode: {metallics_mode!r}."
            )
        if metallics_mode == "hbi" and not heat_state_active:
            raise S44CModelBuilderError(
                "The bounded HBI sensitivity is certified only with the EAF heat model."
            )
        if metallics_mode == "hbi" and float(
            c1_metallics_sensitivity.get("hbi_horizon_cap_t", -1.0)
        ) < 0.0:
            raise S44CModelBuilderError("The HBI sensitivity requires a non-negative cap.")
        dri_thermal_state_mode = str(
            c1_metallics_sensitivity.get(
                "dri_thermal_state_mode", "generic_dri_buffer"
            )
        )
        if dri_thermal_state_mode not in {
            "generic_dri_buffer",
            "hdri_direct_plus_cdri_buffer",
        }:
            raise S44CModelBuilderError(
                f"Unsupported DRI thermal-state mode: {dri_thermal_state_mode!r}."
            )
        dri_thermal_state_active = (
            dri_thermal_state_mode == "hdri_direct_plus_cdri_buffer"
        )
        if dri_thermal_state_active:
            if metallics_mode == "hbi":
                # HBI is an explicitly separate offline sensitivity.  The
                # base HDRI/CDRI thermal split is therefore not stacked into
                # that imported-material variant even though the common
                # configuration mapping carries the base metadata.
                dri_thermal_state_active = False
                dri_thermal_state_mode = "generic_dri_buffer_hbi_sensitivity"
        if dri_thermal_state_active:
            required_thermal = {
                "hdri_temperature_c",
                "cdri_temperature_c",
                "cold_dri_max_share_of_eaf_dri",
                "cold_dri_eaf_arc_electricity_premium_fraction",
            }
            missing_thermal = required_thermal.difference(c1_metallics_sensitivity)
            if missing_thermal:
                raise S44CModelBuilderError(
                    "The HDRI/CDRI contract is missing: "
                    f"{sorted(missing_thermal)}"
                )
            cold_share = float(
                c1_metallics_sensitivity["cold_dri_max_share_of_eaf_dri"]
            )
            cold_premium = float(
                c1_metallics_sensitivity[
                    "cold_dri_eaf_arc_electricity_premium_fraction"
                ]
            )
            if not 0.0 <= cold_share <= 1.0 or cold_premium < 0.0:
                raise S44CModelBuilderError(
                    "The HDRI/CDRI cold share must be in [0, 1] and its electricity "
                    "premium must be non-negative."
                )
    if c1_liquid_steel_route_band is not None:
        required = {"bof_lower_share", "bof_upper_share"}
        missing = required.difference(c1_liquid_steel_route_band)
        if missing:
            raise S44CModelBuilderError(f"C1 liquid-steel route band is missing: {sorted(missing)}")
        lower_share = float(c1_liquid_steel_route_band["bof_lower_share"])
        upper_share = float(c1_liquid_steel_route_band["bof_upper_share"])
        if not 0.0 <= lower_share <= upper_share <= 1.0:
            raise S44CModelBuilderError("C1 BOF liquid-steel route shares must satisfy 0 <= lower <= upper <= 1.")
    if c1_coke_chain_reconciliation is not None:
        required = {"dry_coal_t_per_t_coke", "bf_coke_t_per_t_hot_metal"}
        missing = required.difference(c1_coke_chain_reconciliation)
        if missing:
            raise S44CModelBuilderError(f"C1 coke-chain reconciliation is missing: {sorted(missing)}")
        if any(float(c1_coke_chain_reconciliation[key]) <= 0.0 for key in required):
            raise S44CModelBuilderError("C1 coke-chain reconciliation factors must be positive.")
    if downstream_origin_routing is not None:
        required = {
            "hsm_final_t_per_t_slab",
            "dsp_liquid_steel_input_t_per_t_coil",
            "dsp_final_product_horizon_cap_t",
            "imported_slab_max_t_h",
        }
        missing = required.difference(downstream_origin_routing)
        if missing:
            raise S44CModelBuilderError(f"C1 downstream origin routing is missing: {sorted(missing)}")
        if any(float(downstream_origin_routing[key]) <= 0.0 for key in required.difference({"imported_slab_max_t_h"})):
            raise S44CModelBuilderError("C1 downstream origin routing requires positive HSM and DSP conversion factors.")
        if any(float(downstream_origin_routing[key]) < 0.0 for key in {"dsp_final_product_horizon_cap_t", "imported_slab_max_t_h"}):
            raise S44CModelBuilderError("C1 downstream origin routing caps must be non-negative.")
        if float(
            downstream_origin_routing.get(
                "imported_slab_horizon_cap_t",
                float(downstream_origin_routing["imported_slab_max_t_h"]) * inputs.horizon_hours,
            )
        ) < 0.0:
            raise S44CModelBuilderError("C1 imported-slab horizon cap must be non-negative.")
    retained = inputs.retained_bf_bof
    if retained is None:
        raise S44CModelBuilderError("C1 hybrid WAG route requires retained BF-BOF inputs.")

    model = ConcreteModel()
    model.TIME = RangeSet(0, inputs.horizon_hours - 1)
    model.time_step_hours = float(time_step_hours)
    model.horizon_steps = int(inputs.horizon_hours)
    model.physical_horizon_hours = float(inputs.horizon_hours) * time_step_hours
    retained_process_names = tuple(retained.process_limits)
    on_domain = UnitInterval if commitment_granularity == "daily_binary_hourly_throughput" else Binary
    for process_name in retained_process_names:
        setattr(model, process_name, Var(model.TIME, domain=NonNegativeReals))
        setattr(model, f"{process_name}_on", Var(model.TIME, domain=on_domain))

    model.drp_pellet_input = Var(model.TIME, domain=NonNegativeReals)
    model.drp_on = Var(model.TIME, domain=on_domain)
    if heat_state_active and time_step_hours == 0.25:
        heat = eaf_heat_state_parameters
        assert heat is not None
        model.eaf_heat_start = Var(model.TIME, domain=Binary)

        def _eaf_start_at(m, interval: int):
            if interval >= 0:
                return m.eaf_heat_start[interval]
            if interval == -1:
                return float(heat.initial_start_lag1)
            if interval == -2:
                return float(heat.initial_start_lag2)
            return 0.0

        model.eaf_melt = Expression(
            model.TIME,
            rule=lambda m, t: _eaf_start_at(m, int(t))
            + _eaf_start_at(m, int(t) - 1),
        )
        model.eaf_tap = Expression(
            model.TIME,
            rule=lambda m, t: _eaf_start_at(m, int(t) - 2),
        )
        model.eaf_completed_heat = Expression(
            model.TIME, rule=lambda m, t: m.eaf_tap[t]
        )
        model.eaf_on = Expression(
            model.TIME, rule=lambda m, t: m.eaf_melt[t] + m.eaf_tap[t]
        )
        model.eaf_single_furnace_occupancy = Constraint(
            model.TIME,
            rule=lambda m, t: m.eaf_melt[t] + m.eaf_tap[t] <= 1.0,
        )
        maintenance = {
            int(interval)
            for interval in heat.maintenance_intervals
            if int(interval) < inputs.horizon_hours
        }
        for start_interval in model.TIME:
            occupied = {
                int(start_interval),
                int(start_interval) + 1,
                int(start_interval) + 2,
            }
            if occupied.intersection(maintenance):
                model.eaf_heat_start[start_interval].fix(0.0)
        for interval in maintenance:
            setattr(
                model,
                f"eaf_maintenance_off_{interval}",
                Constraint(expr=model.eaf_on[interval] == 0.0),
            )
        # A heat may cross the rolling execution boundary, but it may not
        # disappear beyond the finite planning boundary.  Fix only starts that
        # cannot reach their tap inside this model.
        for interval in range(max(0, inputs.horizon_hours - 2), inputs.horizon_hours):
            model.eaf_heat_start[interval].fix(0.0)
        model.eaf_heat_count_started = Expression(
            expr=sum(model.eaf_heat_start[t] for t in model.TIME)
        )
        model.eaf_heat_count_tapped = Expression(
            expr=sum(model.eaf_tap[t] for t in model.TIME)
        )
        model.eaf_arc_on_interval_count = Expression(
            expr=sum(model.eaf_melt[t] for t in model.TIME)
        )
        model.eaf_unfinished_heat_count_end = Expression(
            expr=model.eaf_heat_start[inputs.horizon_hours - 2]
            + model.eaf_heat_start[inputs.horizon_hours - 1]
        )
        if heat.require_idle_terminal_state:
            model.eaf_terminal_idle = Constraint(
                expr=model.eaf_unfinished_heat_count_end == 0.0
            )
        model.eaf_heat_state_active = True
        model.eaf_heat_size_t_liquid_steel = heat.heat_size_t_liquid_steel
        model.eaf_arc_energy_mwh_per_heat = heat.arc_energy_mwh_per_heat
        model.eaf_arc_on_power_mw = heat.arc_on_power_mw
        model.eaf_secondary_energy_mwh_per_heat = heat.secondary_energy_mwh_per_heat
        model.eaf_quantization_allowance_t = heat.quantization_allowance_t
        model.eaf_batch_time_contract = "global_15_minute_grid"
        model.eaf_internal_batch_subslots_per_hour = 1
    elif heat_state_active:
        # The deterministic hourly model keeps one global decision interval per
        # hour.  Only the EAF retains four internal 15-minute batch positions so
        # the accepted 45-minute heat cycle is not rounded to one hour (which
        # would incorrectly cap the furnace at 24 heats/day).  All material,
        # energy and price expressions below remain indexed by the hourly TIME
        # set; these expressions aggregate the internal phase counts exactly.
        heat = eaf_heat_state_parameters
        assert heat is not None
        subslots_per_hour = 4
        subslot_count = inputs.horizon_hours * subslots_per_hour
        model.EAF_SUBTIME = RangeSet(0, subslot_count - 1)
        model.eaf_heat_start_subslot = Var(model.EAF_SUBTIME, domain=Binary)

        def _hourly_eaf_start_at(m, subslot: int):
            if subslot >= 0:
                return m.eaf_heat_start_subslot[subslot]
            if subslot == -1:
                return float(heat.initial_start_lag1)
            if subslot == -2:
                return float(heat.initial_start_lag2)
            return 0.0

        model.eaf_heat_start = Expression(
            model.TIME,
            rule=lambda m, t: sum(
                m.eaf_heat_start_subslot[4 * int(t) + p]
                for p in range(subslots_per_hour)
            ),
        )
        model.eaf_melt = Expression(
            model.TIME,
            rule=lambda m, t: sum(
                _hourly_eaf_start_at(m, 4 * int(t) + p)
                + _hourly_eaf_start_at(m, 4 * int(t) + p - 1)
                for p in range(subslots_per_hour)
            ),
        )
        model.eaf_tap = Expression(
            model.TIME,
            rule=lambda m, t: sum(
                _hourly_eaf_start_at(m, 4 * int(t) + p - 2)
                for p in range(subslots_per_hour)
            ),
        )
        model.eaf_completed_heat = Expression(
            model.TIME, rule=lambda m, t: m.eaf_tap[t]
        )
        model.eaf_on = Expression(
            model.TIME,
            rule=lambda m, t: 0.25 * (m.eaf_melt[t] + m.eaf_tap[t]),
        )
        model.eaf_single_furnace_occupancy = Constraint(
            model.EAF_SUBTIME,
            rule=lambda m, s: _hourly_eaf_start_at(m, int(s))
            + _hourly_eaf_start_at(m, int(s) - 1)
            + _hourly_eaf_start_at(m, int(s) - 2)
            <= 1.0,
        )
        model.eaf_melt_subslot = Expression(
            model.EAF_SUBTIME,
            rule=lambda m, s: _hourly_eaf_start_at(m, int(s))
            + _hourly_eaf_start_at(m, int(s) - 1),
        )
        model.eaf_tap_subslot = Expression(
            model.EAF_SUBTIME,
            rule=lambda m, s: _hourly_eaf_start_at(m, int(s) - 2),
        )
        model.eaf_arc_power_mw_subslot = Expression(
            model.EAF_SUBTIME,
            rule=lambda m, s: heat.arc_on_power_mw * m.eaf_melt_subslot[s],
        )
        maintenance = {
            int(interval)
            for interval in heat.maintenance_intervals
            if int(interval) < subslot_count
        }
        for start_subslot in model.EAF_SUBTIME:
            occupied = {
                int(start_subslot),
                int(start_subslot) + 1,
                int(start_subslot) + 2,
            }
            if occupied.intersection(maintenance):
                model.eaf_heat_start_subslot[start_subslot].fix(0.0)
        for subslot in range(max(0, subslot_count - 2), subslot_count):
            model.eaf_heat_start_subslot[subslot].fix(0.0)
        model.eaf_heat_count_started = Expression(
            expr=sum(model.eaf_heat_start_subslot[s] for s in model.EAF_SUBTIME)
        )
        model.eaf_heat_count_tapped = Expression(
            expr=sum(model.eaf_tap[t] for t in model.TIME)
        )
        model.eaf_arc_on_interval_count = Expression(
            expr=sum(model.eaf_melt[t] for t in model.TIME)
        )
        model.eaf_unfinished_heat_count_end = Expression(
            expr=model.eaf_heat_start_subslot[subslot_count - 2]
            + model.eaf_heat_start_subslot[subslot_count - 1]
        )
        if heat.require_idle_terminal_state:
            model.eaf_terminal_idle = Constraint(
                expr=model.eaf_unfinished_heat_count_end == 0.0
            )
        model.eaf_heat_state_active = True
        model.eaf_heat_size_t_liquid_steel = heat.heat_size_t_liquid_steel
        model.eaf_arc_energy_mwh_per_heat = heat.arc_energy_mwh_per_heat
        model.eaf_arc_on_power_mw = heat.arc_on_power_mw
        model.eaf_secondary_energy_mwh_per_heat = heat.secondary_energy_mwh_per_heat
        model.eaf_quantization_allowance_t = heat.quantization_allowance_t
        model.eaf_batch_time_contract = "hourly_grid_with_internal_15_minute_eaf_subslots"
        model.eaf_internal_batch_subslots_per_hour = subslots_per_hour
    else:
        model.eaf_dri_input = Var(model.TIME, domain=NonNegativeReals)
        model.eaf_on = Var(model.TIME, domain=on_domain)
        model.eaf_heat_state_active = False
    model.dri_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.coke_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.sinter_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.hot_iron_inventory = Var(model.TIME, domain=NonNegativeReals)
    model.cold_slab_inventory = Var(model.TIME, domain=NonNegativeReals)

    def _process_var(m, name, t):
        return getattr(m, name)[t]

    def _on_var(m, name, t):
        return getattr(m, f"{name}_on")[t]

    model.retained_process_min = Constraint(
        retained_process_names,
        model.TIME,
        rule=lambda m, name, t: _process_var(m, name, t) >= retained.process_limits[name][0] * _on_var(m, name, t),
    )
    model.retained_process_max = Constraint(
        retained_process_names,
        model.TIME,
        rule=lambda m, name, t: _process_var(m, name, t) <= retained.process_limits[name][1] * _on_var(m, name, t),
    )

    model.coking_plant_2 = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.blast_furnace_7 = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bf6_represented_activity = Expression(
        model.TIME, rule=lambda m, t: m.blast_furnace_6[t]
    )
    model.sinter_output = Expression(
        model.TIME,
        rule=lambda m, t: retained.sinter_output_per_t_iron_ore * m.sintering_plant[t],
    )
    if c1_bf_material_interface is None:
        # Historical static callers retain their former interface. The active
        # deterministic temporal contract supplies the explicit C1 interface
        # below, in which BF6 activity is not a physical sinter bus.
        model.bf6_hot_iron_output = Expression(
            model.TIME,
            rule=lambda m, t: retained.bf_hot_iron_per_t_sinter
            * m.blast_furnace_6[t],
        )
        model.bf_sinter_input = Expression(
            model.TIME, rule=lambda m, t: m.blast_furnace_6[t]
        )
        model.c1_bf_activity_quantity_role = "legacy_physical_sinter_interface"
        model.c1_bf_activity_rate_unit = "t_sinter/h"
        model.c1_sinter_t_per_t_hot_metal = (
            1.0 / retained.bf_hot_iron_per_t_sinter
        )
    else:
        hot_metal_per_activity = float(
            c1_bf_material_interface[
                "hot_metal_t_per_t_represented_bf_activity"
            ]
        )
        sinter_per_hot_metal = float(
            c1_bf_material_interface["sinter_t_per_t_hot_metal"]
        )
        model.bf6_hot_iron_output = Expression(
            model.TIME,
            rule=lambda m, t: hot_metal_per_activity
            * m.bf6_represented_activity[t],
        )
        model.bf_sinter_input = Expression(
            model.TIME,
            rule=lambda m, t: sinter_per_hot_metal
            * m.bf6_hot_iron_output[t],
        )
        model.c1_bf_activity_quantity_role = str(
            c1_bf_material_interface["activity_quantity_role"]
        )
        model.c1_bf_activity_rate_unit = str(
            c1_bf_material_interface["activity_rate_unit"]
        )
        model.c1_hot_metal_t_per_t_represented_bf_activity = (
            hot_metal_per_activity
        )
        model.c1_bf_activity_min_t_h = (
            float(retained.process_limits["blast_furnace_6"][0])
            / float(time_step_hours)
        )
        model.c1_bf_activity_max_t_h = (
            float(retained.process_limits["blast_furnace_6"][1])
            / float(time_step_hours)
        )
        model.c1_sinter_t_per_t_hot_metal = sinter_per_hot_metal
        model.c1_annual_sinter_anchor_t_y = float(
            c1_bf_material_interface["annual_sinter_anchor_t_y"]
        )
        model.c1_annual_hot_metal_anchor_t_y = float(
            c1_bf_material_interface["annual_hot_metal_anchor_t_y"]
        )
    model.bf7_hot_iron_output = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bf_hot_iron_output = Expression(model.TIME, rule=lambda m, t: m.bf6_hot_iron_output[t])
    if bof_material_balance is None:
        model.bof_crude_steel_output = Expression(
            model.TIME,
            rule=lambda m, t: retained.bof_crude_steel_per_t_hot_iron * m.basic_oxygen_furnace[t],
        )
        model.bof_scrap_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    else:
        hot_metal_per_t_ls = float(bof_material_balance["hot_metal_t_per_t_liquid_steel"])
        bof_scrap_per_t_ls = float(bof_material_balance["scrap_t_per_t_liquid_steel"])
        if hot_metal_per_t_ls <= 0.0 or bof_scrap_per_t_ls < 0.0:
            raise S44CModelBuilderError("C1 BOF material balance requires a positive hot-metal basis and non-negative scrap basis.")
        model.bof_crude_steel_output = Expression(
            model.TIME,
            rule=lambda m, t: m.basic_oxygen_furnace[t] / hot_metal_per_t_ls,
        )
        model.bof_scrap_supply_t = Var(model.TIME, domain=NonNegativeReals)
        model.bof_scrap_material_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.bof_scrap_supply_t[t] == bof_scrap_per_t_ls * m.bof_crude_steel_output[t],
        )
    model.drp_yield_t_dri_per_t_pellets = float(
        inputs.drp_yield_t_dri_per_t_pellets
    )
    model.drp_dri_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.drp_yield_t_dri_per_t_pellets * m.drp_pellet_input[t],
    )
    if eaf_material_balance is None:
        hdri_per_t_ls = 1.0 / inputs.eaf_yield_t_final_per_t_dri
        scrap_per_t_ls = inputs.eaf_scrap_t_per_t_dri * hdri_per_t_ls
    else:
        hdri_per_t_ls = float(eaf_material_balance["hdri_t_per_t_liquid_steel"])
        scrap_per_t_ls = float(eaf_material_balance["scrap_t_per_t_liquid_steel"])
        scrap_supply_cap_t = float(eaf_material_balance.get("scrap_supply_cap_t", 0.0))
        if hdri_per_t_ls <= 0.0 or scrap_per_t_ls < 0.0 or (scrap_supply_ledger is None and scrap_supply_cap_t < 0.0):
            raise S44CModelBuilderError("C1 EAF material balance requires non-negative, non-zero HDRI basis values.")
    if heat_state_active:
        heat = eaf_heat_state_parameters
        assert heat is not None
        half_hdri_per_heat = (
            hdri_per_t_ls * heat.heat_size_t_liquid_steel / heat.melting_qh_steps
        )
        half_scrap_per_heat = (
            scrap_per_t_ls * heat.heat_size_t_liquid_steel / heat.melting_qh_steps
        )
        model.eaf_liquid_steel_output = Expression(
            model.TIME,
            rule=lambda m, t: heat.heat_size_t_liquid_steel * m.eaf_tap[t],
        )
        model.eaf_dri_equivalent_input = Expression(
            model.TIME,
            rule=lambda m, t: half_hdri_per_heat * m.eaf_melt[t],
        )
        if metallics_mode == "hbi":
            model.eaf_dri_input = Var(model.TIME, domain=NonNegativeReals)
            model.imported_hbi_to_eaf_t = Var(
                model.TIME, domain=NonNegativeReals
            )
            model.eaf_dri_equivalent_balance = Constraint(
                model.TIME,
                rule=lambda m, t: m.eaf_dri_input[t]
                + m.imported_hbi_to_eaf_t[t]
                == m.eaf_dri_equivalent_input[t],
            )
            model.imported_hbi_horizon_cap = Constraint(
                expr=sum(model.imported_hbi_to_eaf_t[t] for t in model.TIME)
                <= float(c1_metallics_sensitivity["hbi_horizon_cap_t"])
            )
        else:
            model.eaf_dri_input = Expression(
                model.TIME,
                rule=lambda m, t: m.eaf_dri_equivalent_input[t],
            )
            model.imported_hbi_to_eaf_t = Expression(
                model.TIME, rule=lambda _m, _t: 0.0
            )
        model.eaf_scrap_supply_t = Expression(
            model.TIME,
            rule=lambda m, t: half_scrap_per_heat * m.eaf_melt[t],
        )
        model.scrap_t = Expression(
            model.TIME, rule=lambda m, t: m.eaf_scrap_supply_t[t]
        )
    elif eaf_material_balance is None:
        model.eaf_liquid_steel_output = Expression(
            model.TIME,
            rule=lambda m, t: inputs.eaf_yield_t_final_per_t_dri * m.eaf_dri_input[t],
        )
        model.scrap_t = Expression(
            model.TIME,
            rule=lambda m, t: inputs.eaf_scrap_t_per_t_dri * m.eaf_dri_input[t],
        )
    else:
        model.eaf_scrap_supply_t = Var(model.TIME, domain=NonNegativeReals)
        model.eaf_liquid_steel_output = Expression(
            model.TIME,
            rule=lambda m, t: m.eaf_dri_input[t] / hdri_per_t_ls,
        )
        model.eaf_scrap_material_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.eaf_scrap_supply_t[t] == scrap_per_t_ls * m.eaf_liquid_steel_output[t],
        )
        if scrap_supply_ledger is None:
            model.eaf_scrap_supply_cap = Constraint(
                expr=sum(model.eaf_scrap_supply_t[t] for t in model.TIME) <= scrap_supply_cap_t
            )
        model.scrap_t = Expression(model.TIME, rule=lambda m, t: m.eaf_scrap_supply_t[t])
    if not hasattr(model, "eaf_dri_equivalent_input"):
        model.eaf_dri_equivalent_input = Expression(
            model.TIME, rule=lambda m, t: m.eaf_dri_input[t]
        )
    if not hasattr(model, "imported_hbi_to_eaf_t"):
        model.imported_hbi_to_eaf_t = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
    if dri_thermal_state_active:
        assert c1_metallics_sensitivity is not None
        model.hdri_direct_to_eaf_t = Var(model.TIME, domain=NonNegativeReals)
        model.hdri_to_cdri_storage_t = Var(model.TIME, domain=NonNegativeReals)
        model.cdri_from_storage_to_eaf_t = Var(model.TIME, domain=NonNegativeReals)
        model.drp_hdri_allocation_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.drp_dri_output[t]
            == m.hdri_direct_to_eaf_t[t] + m.hdri_to_cdri_storage_t[t],
        )
        model.eaf_dri_thermal_input_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.eaf_dri_input[t]
            == m.hdri_direct_to_eaf_t[t] + m.cdri_from_storage_to_eaf_t[t],
        )
        model.eaf_cdri_share_limit = Constraint(
            model.TIME,
            rule=lambda m, t: m.cdri_from_storage_to_eaf_t[t]
            <= float(
                c1_metallics_sensitivity["cold_dri_max_share_of_eaf_dri"]
            )
            * m.eaf_dri_input[t],
        )
        model.cdri_withdrawal_from_prior_inventory = Constraint(
            model.TIME,
            rule=lambda m, t: m.cdri_from_storage_to_eaf_t[t]
            <= (
                inputs.dri_buffer_initial_t
                if int(t) == 0
                else m.dri_inventory[int(t) - 1]
            ),
        )
        arc_mwh_per_t_liquid_steel = (
            eaf_heat_state_parameters.arc_electricity_mwh_per_t_liquid_steel
            if heat_state_active and eaf_heat_state_parameters is not None
            else (
                float(
                    c1_energy_boundary[
                        "eaf_arc_electricity_mwh_per_t_liquid_steel"
                    ]
                )
                if c1_energy_boundary is not None
                else inputs.eaf_electricity_mwh_per_t_dri * hdri_per_t_ls
            )
        )
        model.eaf_cold_dri_reheat_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: float(
                c1_metallics_sensitivity[
                    "cold_dri_eaf_arc_electricity_premium_fraction"
                ]
            )
            * arc_mwh_per_t_liquid_steel
            * m.cdri_from_storage_to_eaf_t[t]
            / hdri_per_t_ls,
        )
    else:
        model.hdri_direct_to_eaf_t = Expression(
            model.TIME, rule=lambda m, t: m.eaf_dri_input[t]
        )
        model.hdri_to_cdri_storage_t = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
        model.cdri_from_storage_to_eaf_t = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
        model.eaf_cold_dri_reheat_electricity_mwh = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
    if scrap_supply_ledger is not None:
        site_cap = float(scrap_supply_ledger["site_total_scrap_supply_cap_t"])
        bof_cap = float(scrap_supply_ledger["bof_scrap_supply_cap_t"])
        eaf_cap = float(scrap_supply_ledger["eaf_scrap_supply_cap_t"])
        if min(site_cap, bof_cap, eaf_cap) < 0.0:
            raise S44CModelBuilderError("C1 scrap supply ledger caps must be non-negative.")
        model.site_scrap_supply_total_t = Expression(
            expr=sum(model.bof_scrap_supply_t[t] + model.eaf_scrap_supply_t[t] for t in model.TIME)
        )
        model.site_scrap_supply_cap = Constraint(expr=model.site_scrap_supply_total_t <= site_cap)
        model.bof_scrap_supply_cap = Constraint(expr=sum(model.bof_scrap_supply_t[t] for t in model.TIME) <= bof_cap)
        model.eaf_scrap_supply_cap = Constraint(expr=sum(model.eaf_scrap_supply_t[t] for t in model.TIME) <= eaf_cap)
        origin_active = all(
            key in scrap_supply_ledger
            for key in (
                "external_scrap_supply_cap_t",
                "internal_scrap_supply_cap_t",
            )
        )
        if origin_active:
            model.external_scrap_to_bof_t = Var(
                model.TIME, domain=NonNegativeReals
            )
            model.external_scrap_to_eaf_t = Var(
                model.TIME, domain=NonNegativeReals
            )
            model.internal_scrap_to_bof_t = Var(
                model.TIME, domain=NonNegativeReals
            )
            model.internal_scrap_to_eaf_t = Var(
                model.TIME, domain=NonNegativeReals
            )
            model.bof_scrap_origin_balance = Constraint(
                model.TIME,
                rule=lambda m, t: m.external_scrap_to_bof_t[t]
                + m.internal_scrap_to_bof_t[t]
                == m.bof_scrap_supply_t[t],
            )
            model.eaf_scrap_origin_balance = Constraint(
                model.TIME,
                rule=lambda m, t: m.external_scrap_to_eaf_t[t]
                + m.internal_scrap_to_eaf_t[t]
                == m.eaf_scrap_supply_t[t],
            )
            model.external_scrap_supply_total_t = Expression(
                expr=sum(
                    model.external_scrap_to_bof_t[t]
                    + model.external_scrap_to_eaf_t[t]
                    for t in model.TIME
                )
            )
            model.internal_scrap_supply_total_t = Expression(
                expr=sum(
                    model.internal_scrap_to_bof_t[t]
                    + model.internal_scrap_to_eaf_t[t]
                    for t in model.TIME
                )
            )
            model.external_scrap_supply_cap = Constraint(
                expr=model.external_scrap_supply_total_t
                <= float(scrap_supply_ledger["external_scrap_supply_cap_t"])
            )
            model.internal_scrap_supply_cap = Constraint(
                expr=model.internal_scrap_supply_total_t
                <= float(scrap_supply_ledger["internal_scrap_supply_cap_t"])
            )
            model.c1_scrap_origin_policy = str(
                scrap_supply_ledger.get(
                    "origin_policy",
                    "external_purchase_plus_bounded_internal_reuse_no_caster_link",
                )
            )
        deadline_keys = (
            "site_total_scrap_supply_deadline_caps_t",
            "bof_scrap_supply_deadline_caps_t",
            "eaf_scrap_supply_deadline_caps_t",
        )
        if all(key in scrap_supply_ledger for key in deadline_keys):
            deadline_maps = {
                key: {int(deadline): float(cap) for deadline, cap in scrap_supply_ledger[key].items()}
                for key in deadline_keys
            }
            deadlines = tuple(sorted(deadline_maps[deadline_keys[0]]))
            if not deadlines or any(
                tuple(sorted(deadline_maps[key])) != deadlines for key in deadline_keys[1:]
            ):
                raise S44CModelBuilderError(
                    "C1 rolling scrap deadline mappings must share the same non-empty deadlines."
                )
            if deadlines[0] <= 0 or deadlines[-1] > inputs.horizon_hours:
                raise S44CModelBuilderError(
                    "C1 rolling scrap deadlines must lie inside the planning horizon."
                )
            if any(
                cap < 0.0
                for mapping in deadline_maps.values()
                for cap in mapping.values()
            ):
                raise S44CModelBuilderError("C1 rolling scrap deadline caps must be non-negative.")
            model.scrap_supply_deadlines = Set(initialize=deadlines, ordered=True)
            model.site_scrap_supply_deadline_cap = Constraint(
                model.scrap_supply_deadlines,
                rule=lambda m, deadline: sum(
                    m.bof_scrap_supply_t[t] + m.eaf_scrap_supply_t[t]
                    for t in range(int(deadline))
                )
                <= deadline_maps["site_total_scrap_supply_deadline_caps_t"][int(deadline)],
            )
            model.bof_scrap_supply_deadline_cap = Constraint(
                model.scrap_supply_deadlines,
                rule=lambda m, deadline: sum(
                    m.bof_scrap_supply_t[t] for t in range(int(deadline))
                )
                <= deadline_maps["bof_scrap_supply_deadline_caps_t"][int(deadline)],
            )
            model.eaf_scrap_supply_deadline_cap = Constraint(
                model.scrap_supply_deadlines,
                rule=lambda m, deadline: sum(
                    m.eaf_scrap_supply_t[t] for t in range(int(deadline))
                )
                <= deadline_maps["eaf_scrap_supply_deadline_caps_t"][int(deadline)],
            )
            if origin_active:
                origin_deadline_maps = {
                    key: {
                        int(deadline): float(cap)
                        for deadline, cap in scrap_supply_ledger[key].items()
                    }
                    for key in (
                        "external_scrap_supply_deadline_caps_t",
                        "internal_scrap_supply_deadline_caps_t",
                    )
                }
                if any(
                    tuple(sorted(mapping)) != deadlines
                    for mapping in origin_deadline_maps.values()
                ):
                    raise S44CModelBuilderError(
                        "C1 origin-tagged scrap deadlines must match route deadlines."
                    )
                model.external_scrap_supply_deadline_cap = Constraint(
                    model.scrap_supply_deadlines,
                    rule=lambda m, deadline: sum(
                        m.external_scrap_to_bof_t[t]
                        + m.external_scrap_to_eaf_t[t]
                        for t in range(int(deadline))
                    )
                    <= origin_deadline_maps[
                        "external_scrap_supply_deadline_caps_t"
                    ][int(deadline)],
                )
                model.internal_scrap_supply_deadline_cap = Constraint(
                    model.scrap_supply_deadlines,
                    rule=lambda m, deadline: sum(
                        m.internal_scrap_to_bof_t[t]
                        + m.internal_scrap_to_eaf_t[t]
                        for t in range(int(deadline))
                    )
                    <= origin_deadline_maps[
                        "internal_scrap_supply_deadline_caps_t"
                    ][int(deadline)],
                )
    elif bof_material_balance is None:
        model.site_scrap_supply_total_t = Expression(expr=sum(model.scrap_t[t] for t in model.TIME))
    else:
        model.site_scrap_supply_total_t = Expression(
            expr=sum(model.bof_scrap_supply_t[t] + model.scrap_t[t] for t in model.TIME)
        )
    model.c1_metallics_sensitivity_mode = metallics_mode
    if downstream_origin_routing is None:
        model.retained_bf_bof_final_product_output = Expression(
            model.TIME,
            rule=lambda m, t: retained.hsm_final_per_t_crude_steel * m.hot_strip_mill[t],
        )
        model.eaf_final_product_output = Expression(
            model.TIME,
            rule=lambda m, t: m.eaf_liquid_steel_output[t],
        )
        model.bof_to_hsm_slab = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bof_to_dsp_liquid_steel = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.eaf_to_hsm_slab = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.eaf_to_dsp_liquid_steel = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.imported_slab_to_hsm = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.dsp_final_product_output = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.final_product_output = Expression(
            model.TIME,
            rule=lambda m, t: m.retained_bf_bof_final_product_output[t] + m.eaf_final_product_output[t],
        )
    else:
        hsm_final_per_t_slab = float(downstream_origin_routing["hsm_final_t_per_t_slab"])
        dsp_input_per_t_coil = float(downstream_origin_routing["dsp_liquid_steel_input_t_per_t_coil"])
        dsp_final_product_horizon_cap_t = float(downstream_origin_routing["dsp_final_product_horizon_cap_t"])
        imported_slab_max_t_h = float(downstream_origin_routing["imported_slab_max_t_h"])
        imported_slab_horizon_cap_t = float(
            downstream_origin_routing.get(
                "imported_slab_horizon_cap_t",
                imported_slab_max_t_h * inputs.horizon_hours,
            )
        )
        model.bof_to_hsm_slab = Var(model.TIME, domain=NonNegativeReals)
        model.bof_to_dsp_liquid_steel = Var(model.TIME, domain=NonNegativeReals)
        model.eaf_to_hsm_slab = Var(model.TIME, domain=NonNegativeReals)
        model.eaf_to_dsp_liquid_steel = Var(model.TIME, domain=NonNegativeReals)
        model.imported_slab_to_hsm = Var(model.TIME, domain=NonNegativeReals)
        model.cold_slab_draw_to_hsm = Var(model.TIME, domain=NonNegativeReals)
        model.eaf_slab_inventory = Var(model.TIME, domain=NonNegativeReals)
        model.eaf_slab_draw_to_hsm = Var(model.TIME, domain=NonNegativeReals)
        model.bof_origin_route_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.bof_to_hsm_slab[t] + m.bof_to_dsp_liquid_steel[t] == m.bof_crude_steel_output[t],
        )
        model.eaf_origin_route_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.eaf_to_hsm_slab[t] + m.eaf_to_dsp_liquid_steel[t] == m.eaf_liquid_steel_output[t],
        )
        model.imported_slab_hourly_cap = Constraint(
            model.TIME,
            rule=lambda m, t: m.imported_slab_to_hsm[t] <= imported_slab_max_t_h,
        )
        model.imported_slab_horizon_cap = Constraint(
            expr=sum(model.imported_slab_to_hsm[t] for t in model.TIME) <= imported_slab_horizon_cap_t
        )
        model.hsm_origin_input_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.hot_strip_mill[t]
            == m.cold_slab_draw_to_hsm[t]
            + m.eaf_slab_draw_to_hsm[t]
            + m.imported_slab_to_hsm[t],
        )
        model.dsp_final_product_output = Expression(
            model.TIME,
            rule=lambda m, t: (m.bof_to_dsp_liquid_steel[t] + m.eaf_to_dsp_liquid_steel[t]) / dsp_input_per_t_coil,
        )
        model.dsp_final_product_horizon_cap = Constraint(
            expr=sum(model.dsp_final_product_output[t] for t in model.TIME) <= dsp_final_product_horizon_cap_t
        )
        model.retained_bf_bof_final_product_output = Expression(
            model.TIME,
            rule=lambda m, t: hsm_final_per_t_slab * m.cold_slab_draw_to_hsm[t]
            + m.bof_to_dsp_liquid_steel[t] / dsp_input_per_t_coil,
        )
        model.eaf_final_product_output = Expression(
            model.TIME,
            rule=lambda m, t: hsm_final_per_t_slab * m.eaf_slab_draw_to_hsm[t]
            + m.eaf_to_dsp_liquid_steel[t] / dsp_input_per_t_coil,
        )
        model.final_product_output = Expression(
            model.TIME,
            rule=lambda m, t: hsm_final_per_t_slab * m.hot_strip_mill[t] + m.dsp_final_product_output[t],
        )
    # Keep the existing physical electricity balance unchanged, but expose the
    # DRP and EAF terms separately for price-insensitive plant-load diagnostics.
    model.drp_electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: (
            float(c1_energy_boundary["drp_electricity_mwh_per_t_dri"])
            * m.drp_dri_output[t]
            if c1_energy_boundary is not None
            else inputs.drp_electricity_mwh_per_t_pellets * m.drp_pellet_input[t]
        ),
    )
    if heat_state_active:
        heat = eaf_heat_state_parameters
        assert heat is not None
        if (
            c1_energy_boundary is not None
            and abs(
                float(c1_energy_boundary["eaf_arc_electricity_mwh_per_t_liquid_steel"])
                - heat.arc_electricity_mwh_per_t_liquid_steel
            )
            > 1e-9
        ):
            raise S44CModelBuilderError(
                "EAF heat-state arc intensity differs from the frozen C1 energy boundary."
            )
        model.eaf_arc_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: heat.arc_energy_mwh_per_melting_interval
            * m.eaf_melt[t],
        )
    else:
        model.eaf_arc_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: (
                float(c1_energy_boundary["eaf_arc_electricity_mwh_per_t_liquid_steel"])
                * m.eaf_liquid_steel_output[t]
                if c1_energy_boundary is not None
                else inputs.eaf_electricity_mwh_per_t_dri * m.eaf_dri_input[t]
            ),
        )
    model.electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: m.drp_electricity_mwh[t]
        + m.eaf_arc_electricity_mwh[t]
        + m.eaf_cold_dri_reheat_electricity_mwh[t],
    )
    model.drp_named_ng_mwh = Expression(
        model.TIME,
        rule=lambda m, t: (
            float(c1_energy_boundary["drp_ng_gj_per_t_dri"]) / 3.6
            * m.drp_dri_output[t]
            if c1_energy_boundary is not None
            else inputs.drp_ng_nm3_per_t_pellets
            * m.drp_pellet_input[t]
            * 35.8
            / 3600.0
        ),
    )
    # HERACLES separates the existing 9.9-GJ/t DRI natural-gas total into
    # reduction and furnace services.  These are reporting expressions only.
    model.drp_reduction_ng_mwh = Expression(
        model.TIME,
        rule=lambda m, t: (8.1 / 3.6) * m.drp_dri_output[t]
        if c1_energy_boundary is not None
        else 0.0,
    )
    model.drp_furnace_ng_mwh = Expression(
        model.TIME,
        rule=lambda m, t: (1.8 / 3.6) * m.drp_dri_output[t]
        if c1_energy_boundary is not None
        else 0.0,
    )
    model.drp_heracless_ng_split_residual_mwh = Expression(
        model.TIME,
        rule=lambda m, t: m.drp_reduction_ng_mwh[t]
        + m.drp_furnace_ng_mwh[t]
        - m.drp_named_ng_mwh[t],
    )
    model.natural_gas_nm3 = Expression(
        model.TIME,
        rule=lambda m, t: (
            m.drp_named_ng_mwh[t]
            * 3600.0
            / float(c1_energy_boundary["natural_gas_lhv_mj_per_nm3"])
            if c1_energy_boundary is not None
            else inputs.drp_ng_nm3_per_t_pellets * m.drp_pellet_input[t]
        ),
    )
    if heat_state_active:
        heat = eaf_heat_state_parameters
        assert heat is not None
        eaf_ng_mwh_per_melt = (
            float(c1_energy_boundary["eaf_ng_gj_per_t_liquid_steel"])
            / 3.6
            * heat.heat_size_t_liquid_steel
            / heat.melting_qh_steps
            if c1_energy_boundary is not None
            else 0.0
        )
        model.eaf_named_ng_mwh = Expression(
            model.TIME,
            rule=lambda m, t: eaf_ng_mwh_per_melt * m.eaf_melt[t],
        )
    else:
        model.eaf_named_ng_mwh = Expression(
            model.TIME,
            rule=lambda m, t: (
                float(c1_energy_boundary["eaf_ng_gj_per_t_liquid_steel"]) / 3.6
                * m.eaf_liquid_steel_output[t]
                if c1_energy_boundary is not None
                else 0.0
            ),
        )
    model.oxygen_t = Expression(
        model.TIME,
        rule=lambda m, t: inputs.drp_o2_t_per_t_pellets * m.drp_pellet_input[t]
        + inputs.eaf_o2_t_per_t_dri * m.eaf_dri_equivalent_input[t],
    )

    model.drp_off_on_upper = Constraint(
        model.TIME,
        rule=lambda m, t: m.drp_pellet_input[t] <= inputs.drp_max_t_pellets_h * m.drp_on[t],
    )
    model.drp_off_on_lower = Constraint(
        model.TIME,
        rule=lambda m, t: m.drp_pellet_input[t] >= inputs.drp_min_t_pellets_h * m.drp_on[t],
    )
    if not heat_state_active:
        model.eaf_off_on_upper = Constraint(model.TIME, rule=lambda m, t: m.eaf_dri_input[t] <= inputs.eaf_max_t_dri_h * m.eaf_on[t])
        model.eaf_off_on_lower = Constraint(model.TIME, rule=lambda m, t: m.eaf_dri_input[t] >= inputs.eaf_min_t_dri_h * m.eaf_on[t])

    drp_time_points = list(range(inputs.horizon_hours))
    model.drp_ramp_up = Constraint(
        drp_time_points[1:],
        rule=lambda m, t: m.drp_pellet_input[t] - m.drp_pellet_input[t - 1]
        <= inputs.drp_ramp_t_pellets_h,
    )
    model.drp_ramp_down = Constraint(
        drp_time_points[1:],
        rule=lambda m, t: m.drp_pellet_input[t - 1] - m.drp_pellet_input[t]
        <= inputs.drp_ramp_t_pellets_h,
    )
    if initial_drp_pellet_input_t is not None:
        model.drp_initial_ramp_up = Constraint(
            expr=model.drp_pellet_input[0] - float(initial_drp_pellet_input_t)
            <= inputs.drp_ramp_t_pellets_h
        )
        model.drp_initial_ramp_down = Constraint(
            expr=float(initial_drp_pellet_input_t) - model.drp_pellet_input[0]
            <= inputs.drp_ramp_t_pellets_h
        )

    if dri_thermal_state_active:
        model.dri_buffer_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.dri_inventory[t]
            == (inputs.dri_buffer_initial_t if int(t) == 0 else m.dri_inventory[int(t) - 1])
            + m.hdri_to_cdri_storage_t[t]
            - m.cdri_from_storage_to_eaf_t[t],
        )
    else:
        model.dri_buffer_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.dri_inventory[t]
            == (inputs.dri_buffer_initial_t if int(t) == 0 else m.dri_inventory[int(t) - 1])
            + m.drp_dri_output[t]
            - m.eaf_dri_input[t],
        )
    model.dri_buffer_capacity = Constraint(model.TIME, rule=lambda m, t: m.dri_inventory[t] <= inputs.dri_buffer_capacity_t)
    if c1_metallics_sensitivity is not None:
        model.c1_dri_buffer_representation = str(
            c1_metallics_sensitivity.get(
                "dri_buffer_representation",
                "generic_bounded_dri_timing_buffer",
            )
        )
        model.c1_dri_buffer_active_capacity_t = inputs.dri_buffer_capacity_t
        model.c1_dri_buffer_source_candidate_t = float(
            c1_metallics_sensitivity.get("dri_buffer_source_candidate_t", 15_350.0)
        )
        model.c1_dri_buffer_thermal_or_silo_claim = (
            "cold_dri_inventory_only_no_separate_silo_or_cooling_dynamics"
            if dri_thermal_state_active
            else "none"
        )
        model.c1_dri_thermal_state_mode = dri_thermal_state_mode
        model.c1_hdri_temperature_c = float(
            c1_metallics_sensitivity.get("hdri_temperature_c", 0.0)
        )
        model.c1_cdri_temperature_c = float(
            c1_metallics_sensitivity.get("cdri_temperature_c", 0.0)
        )
        model.c1_cdri_max_share = float(
            c1_metallics_sensitivity.get("cold_dri_max_share_of_eaf_dri", 0.0)
        )
    if heat_state_active:
        # A continuously operating DRP necessarily produces DRI in the final
        # quarter, while the last completable EAF heat is already tapping.
        # Preserve the cyclic inventory at the last melting-capable boundary
        # and expose the unavoidable final-quarter DRP production as explicit
        # carry inventory.  Campaign terminal bands still replace this local
        # look-ahead equality through the existing named constraint.
        model.dri_terminal_equality = Constraint(
            expr=model.dri_inventory[inputs.horizon_hours - 2]
            == inputs.dri_buffer_initial_t
        )
        model.dri_terminal_carry_inventory_t = Expression(
            expr=model.dri_inventory[inputs.horizon_hours - 1]
            - inputs.dri_buffer_initial_t
        )
    else:
        model.dri_terminal_equality = Constraint(
            expr=model.dri_inventory[inputs.horizon_hours - 1]
            == inputs.dri_buffer_initial_t
        )
    if c1_coke_chain_reconciliation is None:
        model.coke_output = Expression(model.TIME, rule=lambda m, t: m.coking_plant_1[t])
        model.bf_coke_demand = Expression(
            model.TIME,
            rule=lambda m, t: retained.coke_per_t_sinter * m.bf_sinter_input[t],
        )
    else:
        dry_coal_per_t_coke = float(c1_coke_chain_reconciliation["dry_coal_t_per_t_coke"])
        bf_coke_per_t_hot_metal = float(c1_coke_chain_reconciliation["bf_coke_t_per_t_hot_metal"])
        model.coke_output = Expression(
            model.TIME,
            rule=lambda m, t: m.coking_plant_1[t] / dry_coal_per_t_coke,
        )
        model.bf_coke_demand = Expression(
            model.TIME,
            rule=lambda m, t: bf_coke_per_t_hot_metal * m.bf_hot_iron_output[t],
        )
    model.coke_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.coke_inventory[t]
        == (retained.coke_store_initial_t if t == 0 else m.coke_inventory[t - 1])
        + m.coke_output[t]
        - m.bf_coke_demand[t],
    )
    model.sinter_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.sinter_inventory[t]
        == (retained.sinter_store_initial_t if t == 0 else m.sinter_inventory[t - 1])
        + m.sinter_output[t]
        - m.bf_sinter_input[t],
    )
    model.hot_iron_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.hot_iron_inventory[t]
        == (retained.hot_iron_store_initial_t if t == 0 else m.hot_iron_inventory[t - 1])
        + m.bf_hot_iron_output[t]
        - m.basic_oxygen_furnace[t],
    )
    model.cold_slab_balance = Constraint(
        model.TIME,
        rule=(
            lambda m, t: m.cold_slab_inventory[t]
            == (retained.cold_slab_store_initial_t if t == 0 else m.cold_slab_inventory[t - 1])
            + m.bof_to_hsm_slab[t]
            - m.cold_slab_draw_to_hsm[t]
        )
        if downstream_origin_routing is not None
        else (
            lambda m, t: m.cold_slab_inventory[t]
            == (retained.cold_slab_store_initial_t if t == 0 else m.cold_slab_inventory[t - 1])
            + m.bof_crude_steel_output[t]
            - m.hot_strip_mill[t]
        ),
    )
    if downstream_origin_routing is not None:
        eaf_slab_initial_t = float(
            downstream_origin_routing.get("eaf_slab_initial_t", 0.0)
        )
        if not 0.0 <= eaf_slab_initial_t <= retained.cold_slab_store_capacity_t:
            raise S44CModelBuilderError("Invalid EAF slab rolling-state inventory.")
        model.eaf_slab_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.eaf_slab_inventory[t]
            == (eaf_slab_initial_t if int(t) == 0 else m.eaf_slab_inventory[int(t) - 1])
            + m.eaf_to_hsm_slab[t]
            - m.eaf_slab_draw_to_hsm[t],
        )
        model.shared_cold_slab_capacity = Constraint(
            model.TIME,
            rule=lambda m, t: m.cold_slab_inventory[t] + m.eaf_slab_inventory[t]
            <= retained.cold_slab_store_capacity_t,
        )
        model.eaf_slab_terminal = Constraint(
            expr=model.eaf_slab_inventory[inputs.horizon_hours - 1]
            == eaf_slab_initial_t
        )
        model.eaf_slab_handoff_policy = (
            "origin_preserving_EAF_slab_inventory_with_shared_cold_slab_capacity"
        )
    model.coke_capacity = Constraint(model.TIME, rule=lambda m, t: m.coke_inventory[t] <= retained.coke_store_capacity_t)
    model.sinter_capacity = Constraint(model.TIME, rule=lambda m, t: m.sinter_inventory[t] <= retained.sinter_store_capacity_t)
    model.hot_iron_capacity = Constraint(model.TIME, rule=lambda m, t: m.hot_iron_inventory[t] <= retained.hot_iron_store_capacity_t)
    model.cold_slab_capacity = Constraint(model.TIME, rule=lambda m, t: m.cold_slab_inventory[t] <= retained.cold_slab_store_capacity_t)
    model.coke_terminal = Constraint(expr=model.coke_inventory[inputs.horizon_hours - 1] == retained.coke_store_initial_t)
    model.sinter_terminal = Constraint(expr=model.sinter_inventory[inputs.horizon_hours - 1] == retained.sinter_store_initial_t)
    model.hot_iron_terminal = Constraint(expr=model.hot_iron_inventory[inputs.horizon_hours - 1] == retained.hot_iron_store_initial_t)
    model.cold_slab_terminal = Constraint(expr=model.cold_slab_inventory[inputs.horizon_hours - 1] == retained.cold_slab_store_initial_t)
    _apply_c1_inventory_terminal_policy(
        model,
        recoverable_handoff_execution_steps=recoverable_handoff_execution_steps,
        recoverable_dri_tail_state=recoverable_dri_tail_state,
    )

    if c1_retained_route_policy not in {"target_share", "bottom_up_fixed_retained_route", "quota_driven_topology"}:
        raise S44CModelBuilderError(f"Unsupported C1 retained route policy: {c1_retained_route_policy}")
    if c1_retained_route_policy == "target_share":
        retained_target = inputs.final_product_target_t * retained.retained_target_share
        eaf_target = inputs.final_product_target_t - retained_target
        model.retained_bf_bof_target = Constraint(
            expr=sum(model.retained_bf_bof_final_product_output[t] for t in model.TIME) == retained_target
        )
        model.eaf_route_target = Constraint(
            expr=sum(model.eaf_final_product_output[t] for t in model.TIME) == eaf_target
        )
    model.bof_liquid_steel_total = Expression(
        expr=sum(model.bof_crude_steel_output[t] for t in model.TIME)
    )
    model.eaf_liquid_steel_total = Expression(
        expr=sum(model.eaf_liquid_steel_output[t] for t in model.TIME)
    )
    model.endogenous_liquid_steel_total = Expression(
        expr=model.bof_liquid_steel_total + model.eaf_liquid_steel_total
    )
    if c1_liquid_steel_route_band is not None:
        model.bof_liquid_steel_lower_share = Constraint(
            expr=model.bof_liquid_steel_total
            >= lower_share * model.endogenous_liquid_steel_total
        )
        model.bof_liquid_steel_upper_share = Constraint(
            expr=model.bof_liquid_steel_total
            <= upper_share * model.endogenous_liquid_steel_total
        )
    if downstream_origin_routing is not None and downstream_origin_routing.get("reference_validation_bands") is not None:
        c1_reference_bands = downstream_origin_routing["reference_validation_bands"]
        hsm_yield = float(downstream_origin_routing["hsm_final_t_per_t_slab"])
        reference_expressions = {
            "bof_liquid_steel": model.bof_liquid_steel_total,
            "eaf_liquid_steel": model.eaf_liquid_steel_total,
            "hsm_final_output": sum(hsm_yield * model.hot_strip_mill[t] for t in model.TIME),
            "dsp_final_output": sum(model.dsp_final_product_output[t] for t in model.TIME),
            "imported_slab": sum(model.imported_slab_to_hsm[t] for t in model.TIME),
        }
        unknown_bands = set(c1_reference_bands).difference(reference_expressions)
        if unknown_bands:
            raise S44CModelBuilderError(f"Unknown C1 reference band(s): {sorted(unknown_bands)}")
        for band_id, band in c1_reference_bands.items():
            _add_reference_horizon_band(
                model,
                constraint_id=f"c1_reference_{band_id}",
                expression=reference_expressions[band_id],
                band=band,
            )
        c1_deadlines = downstream_origin_routing.get(
            "reference_band_deadline_hours"
        )
        if c1_deadlines is not None:
            _add_reference_cumulative_deadline_bands(
                model,
                constraint_prefix="c1_reference_deadline",
                hourly_expressions={
                    "bof_liquid_steel": model.bof_crude_steel_output,
                    "eaf_liquid_steel": model.eaf_liquid_steel_output,
                    "hsm_final_output": {
                        t: hsm_yield * model.hot_strip_mill[t]
                        for t in model.TIME
                    },
                    "dsp_final_output": model.dsp_final_product_output,
                    "imported_slab": model.imported_slab_to_hsm,
                },
                bands=c1_reference_bands,
                deadline_hours=c1_deadlines,
                horizon_hours=inputs.horizon_hours,
                explicit_deadline_bands=downstream_origin_routing.get(
                    "reference_deadline_bands"
                ),
            )
    if enforce_final_product_requirement:
        _add_final_product_requirement(
            model,
            final_product_target_t=inputs.final_product_target_t,
            quota_lower_bound=rolling_production_deadline_targets_t is not None,
        )
    if commitment_granularity == "daily_binary_hourly_throughput":
        commitment_definitions = {
            **{
                name: (name, f"{name}_on", retained.process_limits[name][0])
                for name in retained_process_names
            },
            "drp": ("drp_pellet_input", "drp_on", inputs.drp_min_t_pellets_h),
        }
        if not heat_state_active:
            commitment_definitions["eaf"] = (
                "eaf_dri_input",
                "eaf_on",
                inputs.eaf_min_t_dri_h,
            )
        _add_day_commitment_layer(
            model,
            horizon_hours=inputs.horizon_hours,
            commitment_definitions=commitment_definitions,
            commitment_day_lengths=commitment_day_lengths,
            time_step_hours=time_step_hours,
        )
    if daily_production_guardrail:
        _add_daily_production_guardrail(model, inputs)
    if rolling_production_deadline_targets_t is not None:
        _add_rolling_production_deadline_envelope(
            model,
            horizon_hours=inputs.horizon_hours,
            final_product_target_t=inputs.final_product_target_t,
            deadline_targets_t=rolling_production_deadline_targets_t,
        )
    if c1_retained_route_policy == "bottom_up_fixed_retained_route":
        _apply_c1_bottom_up_retained_route_policy(model, inputs.horizon_hours)
    elif fix_c1_hybrid_schedule:
        _apply_c1_hybrid_static_schedule(model, inputs.horizon_hours)

    _enforce_continuous_must_run_availability(
        model,
        activity_to_on_var={
            **{name: f"{name}_on" for name in retained_process_names},
            "drp_pellet_input": "drp_on",
        },
        activities=continuous_must_run_activities,
        configuration_id="C1_phase1_BF_BOF_plus_DRP_EAF",
    )
    if temporal_plant_dynamics is not None:
        if initial_continuous_rate_t_h is None:
            raise S44CModelBuilderError(
                "Temporal plant dynamics require rolling boundary rates."
            )
        _add_c1_temporal_plant_dynamics(
            model,
            time_step_hours=time_step_hours,
            contract=temporal_plant_dynamics,
            initial_rate_t_h=initial_continuous_rate_t_h,
        )
        _add_downstream_temporal_contract(
            model,
            time_step_hours=time_step_hours,
            contract=temporal_plant_dynamics,
            dsp_component_name="dsp_final_product_output",
            initial_rate_t_h=initial_continuous_rate_t_h,
        )

    controller_flags = _development_controller_flags(development_controller_activation)
    if development_controller_activation != "none" and not enable_minimal_wag_layer:
        raise S44CModelBuilderError("Development controller activation requires the carrier-specific WAG layer.")
    if enable_minimal_wag_layer:
        _add_c0_minimal_wag_layer(
            model,
            retained,
            time_step_hours=time_step_hours,
            enable_internal_wag_power=enable_internal_wag_power,
            # DRP/EAF electricity is the existing C1 route demand.  When the
            # opt-in HSM/PEFA development controllers are active, their
            # Existing DRP/EAF load, then source-traceable controller and
            # boundary rows. These remain gross demand only; no residual is
            # used to force a site anchor.
            gross_electricity_rule=lambda m, t: (
                m.electricity_mwh[t]
                + m.development_controller_electricity_mwh[t]
                + m.electricity_boundary_development_mwh[t]
                + m.experimental_process_electricity_overlay_mwh[t]
            ),
            development_profile=(load_development_controller_profile("C1_phase1_BF_BOF_plus_DRP_EAF") if development_controller_activation != "none" else None),
            enable_hsm_controller=controller_flags["hsm"],
            enable_pefa_controller=controller_flags["pefa"],
            enable_boiler_scaffold=controller_flags["boiler"],
            enable_generator_interface=controller_flags["generator"],
            enable_electricity_boundary_controller=controller_flags["electricity_boundary"],
            hsm_rolling_electricity_mwh_per_t_hrc_override=hsm_rolling_electricity_mwh_per_t_hrc_override,
            retire_legacy_boiler_placeholder=development_controller_activation != "none",
            development_controller_profile_weights=development_controller_profile_weights,
            linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
            site_background_electricity_mwh_h=site_background_electricity_mwh_h,
            site_baseload_ng_mwh_h=site_baseload_ng_mwh_h,
            site_residual_steam_t_h=site_residual_steam_t_h,
            site_residual_direct_co2_t_h=site_residual_direct_co2_t_h,
            hsm_carrier_precedence=hsm_carrier_precedence,
            hsm_eligible_carriers=hsm_eligible_carriers,
            hsm_source_mix_policy=hsm_source_mix_policy,
            generator_interface_cap_mode=generator_interface_cap_mode,
            generator_unit_interface=generator_unit_interface,
            initial_vn25_output_mw=initial_vn25_output_mw,
            eaf_secondary_electricity_mwh_per_t_ls_override=eaf_secondary_electricity_mwh_per_t_ls_override,
            dsp_electricity_mwh_per_t_coil_override=dsp_electricity_mwh_per_t_coil_override,
            bf_electricity_intensity_scale=bf_electricity_intensity_scale,
            experimental_self_use_calibration=experimental_self_use_calibration,
            experimental_process_electricity_overlay=experimental_process_electricity_overlay,
            experimental_ng_service_calibration=experimental_ng_service_calibration,
            experimental_coal_wag_calibration=experimental_coal_wag_calibration,
            kgf_underfiring_activity_rule=(
                (lambda m, t: m.coke_output[t])
                if c1_coke_chain_reconciliation is not None
                else None
            ),
            hsm_output_activity_rule=(
                (lambda m, t: float(downstream_origin_routing["hsm_final_t_per_t_slab"]) * m.hot_strip_mill[t])
                if downstream_origin_routing is not None
                else None
            ),
        )
    else:
        model.bfg_generated = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.cog_generated = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bofg_generated = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.wag_generated = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.wag_used = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.wag_flared = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_to_boiler_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_production_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.gross_electricity_mwh = Expression(model.TIME, rule=lambda m, t: m.electricity_mwh[t])
        model.net_grid_import_mwh = Expression(model.TIME, rule=lambda m, t: m.electricity_mwh[t])
        model.wag_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)

    if external_procurement_flow_coefficients is None:
        model.bf_pci_input_t = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
        model.pefa_iron_ore_input_t = Expression(
            model.TIME, rule=lambda _m, _t: 0.0
        )
    else:
        pci_factor = float(
            external_procurement_flow_coefficients["pci_t_per_t_hot_metal"]
        )
        pefa_ore_factor = float(
            external_procurement_flow_coefficients[
                "pefa_iron_ore_t_per_t_pellets"
            ]
        )
        model.bf_pci_input_t = Expression(
            model.TIME,
            rule=lambda m, t: pci_factor * m.bf_hot_iron_output[t],
        )
        model.pefa_iron_ore_input_t = Expression(
            model.TIME,
            rule=lambda m, t: pefa_ore_factor * m.pefa_pellet_output_t[t],
        )
    coal_procurement_multiplier = float(
        (experimental_coal_wag_calibration or {}).get(
            "coal_procurement_multiplier", 1.0
        )
    )
    model.c1_adjusted_coking_coal_input_t = Expression(
        model.TIME,
        rule=lambda m, t: coal_procurement_multiplier * m.coking_plant_1[t],
    )
    model.c1_adjusted_pci_input_t = Expression(
        model.TIME,
        rule=lambda m, t: coal_procurement_multiplier * m.bf_pci_input_t[t],
    )
    model.c1_total_coal_input_t = Expression(
        model.TIME,
        rule=lambda m, t: m.c1_adjusted_coking_coal_input_t[t]
        + m.c1_adjusted_pci_input_t[t],
    )
    model.c1_additional_coal_completion_t = Expression(
        model.TIME,
        rule=lambda m, t: m.c1_total_coal_input_t[t]
        - m.coking_plant_1[t]
        - m.bf_pci_input_t[t],
    )
    model.experimental_coal_wag_policy = (
        "production_linked_coal_procurement_completion_with_carrier_specific_wag_yields"
        if experimental_coal_wag_calibration
        else "inactive"
    )
    if experimental_coal_wag_calibration:
        model.experimental_coal_wag_parameters = dict(
            experimental_coal_wag_calibration
        )
    # C1 temporal-contract v2 intentionally carries no default physical
    # preference.  The previous objective rewarded fewer process-on intervals,
    # fewer EAF starts, low inventories and flaring/NG routing.  Those are
    # physical states or audited outcomes, not valid optimisation incentives.
    # The deterministic controller installs its explicit lexicographic tiers
    # after model construction.  Keep an algebraic zero objective only for API
    # compatibility with historical callers that deactivate this component.
    model.static_price_naive_objective = Objective(
        expr=0.0 * sum(model.final_product_output[t] for t in model.TIME),
        sense=minimize,
    )
    return model


def _build_c1_model(
    inputs: C1ExecutableInputs,
    *,
    time_step_hours: float = 1.0,
    enable_minimal_wag_layer: bool = False,
    enable_c1_retained_bf_bof_route: bool = False,
    enable_internal_wag_power: bool = False,
    development_controller_activation: str = "none",
    hsm_rolling_electricity_mwh_per_t_hrc_override: float | None = None,
    development_controller_profile_weights: Mapping[str, Mapping[int, float]] | None = None,
    daily_production_guardrail: bool = False,
    rolling_production_deadline_targets_t: Mapping[int, float] | None = None,
    fix_c1_hybrid_schedule: bool = False,
    c1_retained_route_policy: str = "target_share",
    commitment_granularity: str = "hourly_binary",
    commitment_day_lengths: Collection[int] | None = None,
    eaf_material_balance: Mapping[str, float] | None = None,
    bof_material_balance: Mapping[str, float] | None = None,
    scrap_supply_ledger: Mapping[str, Any] | None = None,
    c1_bf_material_interface: Mapping[str, Any] | None = None,
    c1_metallics_sensitivity: Mapping[str, Any] | None = None,
    downstream_origin_routing: Mapping[str, float] | None = None,
    c1_liquid_steel_route_band: Mapping[str, float] | None = None,
    continuous_must_run_activities: Collection[str] | None = None,
    c1_coke_chain_reconciliation: Mapping[str, float] | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    site_baseload_ng_mwh_h: float = 0.0,
    site_residual_steam_t_h: float = 0.0,
    site_residual_direct_co2_t_h: float = 0.0,
    hsm_carrier_precedence: Collection[str] | None = None,
    hsm_eligible_carriers: Collection[str] | None = None,
    hsm_source_mix_policy: Mapping[str, Any] | None = None,
    generator_interface_cap_mode: str = "inherited_profile",
    generator_unit_interface: Mapping[str, Any] | None = None,
    c1_energy_boundary: Mapping[str, float] | None = None,
    eaf_secondary_electricity_mwh_per_t_ls_override: float | None = None,
    dsp_electricity_mwh_per_t_coil_override: float | None = None,
    external_procurement_flow_coefficients: Mapping[str, float] | None = None,
    bf_electricity_intensity_scale: float = 1.0,
    eaf_heat_state_parameters: EAFHeatStateParameters | None = None,
    initial_drp_pellet_input_t: float | None = None,
    initial_vn25_output_mw: float | None = None,
    enforce_final_product_requirement: bool = True,
    recoverable_handoff_execution_steps: int | None = None,
    temporal_plant_dynamics: Mapping[str, Any] | None = None,
    initial_continuous_rate_t_h: Mapping[str, float] | None = None,
    recoverable_dri_tail_state: bool = False,
    experimental_self_use_calibration: Mapping[str, Any] | None = None,
    experimental_process_electricity_overlay: Mapping[str, Any] | None = None,
    experimental_ng_service_calibration: Mapping[str, Any] | None = None,
    experimental_coal_wag_calibration: Mapping[str, Any] | None = None,
):
    if enable_c1_retained_bf_bof_route:
        return _build_c1_hybrid_model(
            inputs,
            time_step_hours=time_step_hours,
            enable_minimal_wag_layer=enable_minimal_wag_layer,
            enable_internal_wag_power=enable_internal_wag_power,
            development_controller_activation=development_controller_activation,
            hsm_rolling_electricity_mwh_per_t_hrc_override=hsm_rolling_electricity_mwh_per_t_hrc_override,
            development_controller_profile_weights=development_controller_profile_weights,
            daily_production_guardrail=daily_production_guardrail,
            rolling_production_deadline_targets_t=rolling_production_deadline_targets_t,
            fix_c1_hybrid_schedule=fix_c1_hybrid_schedule,
            c1_retained_route_policy=c1_retained_route_policy,
            commitment_granularity=commitment_granularity,
            commitment_day_lengths=commitment_day_lengths,
            eaf_material_balance=eaf_material_balance,
            bof_material_balance=bof_material_balance,
            scrap_supply_ledger=scrap_supply_ledger,
            c1_bf_material_interface=c1_bf_material_interface,
            c1_metallics_sensitivity=c1_metallics_sensitivity,
            downstream_origin_routing=downstream_origin_routing,
            c1_liquid_steel_route_band=c1_liquid_steel_route_band,
            continuous_must_run_activities=continuous_must_run_activities,
            c1_coke_chain_reconciliation=c1_coke_chain_reconciliation,
            linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
            site_background_electricity_mwh_h=site_background_electricity_mwh_h,
            site_baseload_ng_mwh_h=site_baseload_ng_mwh_h,
            site_residual_steam_t_h=site_residual_steam_t_h,
            site_residual_direct_co2_t_h=site_residual_direct_co2_t_h,
            hsm_carrier_precedence=hsm_carrier_precedence,
            hsm_eligible_carriers=hsm_eligible_carriers,
            hsm_source_mix_policy=hsm_source_mix_policy,
            generator_interface_cap_mode=generator_interface_cap_mode,
            generator_unit_interface=generator_unit_interface,
            c1_energy_boundary=c1_energy_boundary,
            eaf_secondary_electricity_mwh_per_t_ls_override=eaf_secondary_electricity_mwh_per_t_ls_override,
            dsp_electricity_mwh_per_t_coil_override=dsp_electricity_mwh_per_t_coil_override,
            external_procurement_flow_coefficients=external_procurement_flow_coefficients,
            bf_electricity_intensity_scale=bf_electricity_intensity_scale,
            experimental_self_use_calibration=experimental_self_use_calibration,
            experimental_process_electricity_overlay=experimental_process_electricity_overlay,
            experimental_ng_service_calibration=experimental_ng_service_calibration,
            experimental_coal_wag_calibration=experimental_coal_wag_calibration,
            eaf_heat_state_parameters=eaf_heat_state_parameters,
            initial_drp_pellet_input_t=initial_drp_pellet_input_t,
            initial_vn25_output_mw=initial_vn25_output_mw,
            enforce_final_product_requirement=enforce_final_product_requirement,
            recoverable_handoff_execution_steps=recoverable_handoff_execution_steps,
            temporal_plant_dynamics=temporal_plant_dynamics,
            initial_continuous_rate_t_h=initial_continuous_rate_t_h,
            recoverable_dri_tail_state=recoverable_dri_tail_state,
        )
    if recoverable_handoff_execution_steps is not None:
        raise S44CModelBuilderError(
            "A recoverable sinter/hot-iron handoff requires the retained C1 "
            "BF-BOF route."
        )
    if development_controller_activation != "none":
        raise S44CModelBuilderError("Development WAG controllers require the retained C1 BF-BOF route.")
    model = ConcreteModel()
    model.TIME = RangeSet(0, inputs.horizon_hours - 1)
    model.time_step_hours = float(time_step_hours)
    model.horizon_steps = int(inputs.horizon_hours)
    model.physical_horizon_hours = float(inputs.horizon_hours) * time_step_hours
    model.drp_pellet_input = Var(model.TIME, domain=NonNegativeReals)
    model.eaf_dri_input = Var(model.TIME, domain=NonNegativeReals)
    model.eaf_on = Var(model.TIME, domain=Binary)
    model.dri_inventory = Var(model.TIME, domain=NonNegativeReals)

    model.drp_dri_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.drp_yield_t_dri_per_t_pellets * m.drp_pellet_input[t],
    )
    model.final_product_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.eaf_yield_t_final_per_t_dri * m.eaf_dri_input[t],
    )
    model.electricity_mwh = Expression(
        model.TIME,
        rule=lambda m, t: inputs.drp_electricity_mwh_per_t_pellets * m.drp_pellet_input[t]
        + inputs.eaf_electricity_mwh_per_t_dri * m.eaf_dri_input[t],
    )
    model.natural_gas_nm3 = Expression(
        model.TIME,
        rule=lambda m, t: inputs.drp_ng_nm3_per_t_pellets * m.drp_pellet_input[t],
    )
    model.oxygen_t = Expression(
        model.TIME,
        rule=lambda m, t: inputs.drp_o2_t_per_t_pellets * m.drp_pellet_input[t]
        + inputs.eaf_o2_t_per_t_dri * m.eaf_dri_input[t],
    )
    model.scrap_t = Expression(
        model.TIME,
        rule=lambda m, t: inputs.eaf_scrap_t_per_t_dri * m.eaf_dri_input[t],
    )
    model.bfg_generated = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.cog_generated = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bofg_generated = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.wag_generated = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.wag_used = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.wag_flared = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bfg_to_kgf1 = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.cog_to_kgf1 = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.cog_to_kgf2 = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.cog_to_sinter = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bfg_to_boiler = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.cog_to_boiler = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bfg_to_vattenfall = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.cog_to_vattenfall = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bofg_to_vattenfall = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.vattenfall_fuel_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.wag_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.gross_electricity_mwh = Expression(model.TIME, rule=lambda m, t: m.electricity_mwh[t])
    model.net_grid_import_mwh = Expression(model.TIME, rule=lambda m, t: m.electricity_mwh[t])
    model.bfg_flared = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.cog_flared = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bofg_flared = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bfg_balance_residual = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.cog_balance_residual = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bofg_balance_residual = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bfg_flare_co2_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.cog_flare_co2_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bofg_flare_co2_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.flaring_co2_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.flaring_co2_diagnostic_cost_eur = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.ng_to_boiler_mwh = Expression(
        model.TIME,
        rule=lambda _m, _t: BOILER_TOTAL_PLACEHOLDER_MWH_H if enable_minimal_wag_layer else 0.0,
    )
    model.steam_production_mwh = Expression(
        model.TIME,
        rule=lambda m, t: ETA_BOILER_STEAM * m.ng_to_boiler_mwh[t],
    )

    model.drp_min_bound = Constraint(model.TIME, rule=lambda m, t: m.drp_pellet_input[t] >= inputs.drp_min_t_pellets_h)
    model.drp_max_bound = Constraint(model.TIME, rule=lambda m, t: m.drp_pellet_input[t] <= inputs.drp_max_t_pellets_h)
    model.eaf_off_on_upper = Constraint(model.TIME, rule=lambda m, t: m.eaf_dri_input[t] <= inputs.eaf_max_t_dri_h * m.eaf_on[t])
    model.eaf_off_on_lower = Constraint(model.TIME, rule=lambda m, t: m.eaf_dri_input[t] >= inputs.eaf_min_t_dri_h * m.eaf_on[t])

    time_points = list(range(inputs.horizon_hours))
    model.drp_ramp_up = Constraint(
        time_points[1:],
        rule=lambda m, t: m.drp_pellet_input[t] - m.drp_pellet_input[t - 1] <= inputs.drp_ramp_t_pellets_h,
    )
    model.drp_ramp_down = Constraint(
        time_points[1:],
        rule=lambda m, t: m.drp_pellet_input[t - 1] - m.drp_pellet_input[t] <= inputs.drp_ramp_t_pellets_h,
    )
    model.dri_buffer_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.dri_inventory[t]
        == (inputs.dri_buffer_initial_t if t == 0 else m.dri_inventory[t - 1])
        + m.drp_dri_output[t]
        - m.eaf_dri_input[t],
    )
    model.dri_buffer_capacity = Constraint(model.TIME, rule=lambda m, t: m.dri_inventory[t] <= inputs.dri_buffer_capacity_t)
    model.dri_terminal_equality = Constraint(
        expr=model.dri_inventory[inputs.horizon_hours - 1] == inputs.dri_buffer_initial_t
    )
    _add_final_product_requirement(
        model,
        final_product_target_t=inputs.final_product_target_t,
        quota_lower_bound=rolling_production_deadline_targets_t is not None,
    )
    if rolling_production_deadline_targets_t is not None:
        _add_rolling_production_deadline_envelope(
            model,
            horizon_hours=inputs.horizon_hours,
            final_product_target_t=inputs.final_product_target_t,
            deadline_targets_t=rolling_production_deadline_targets_t,
        )
    model.static_price_naive_objective = Objective(
        expr=sum(model.eaf_on[t] for t in model.TIME) + 1e-6 * sum(model.dri_inventory[t] for t in model.TIME),
        sense=minimize,
    )
    return model


def _block_configuration(
    tables: UnifiedInputTables,
    configuration_id: str,
    *,
    caveat: str,
    horizon_hours_override: int | None = None,
    target_multiplier: float = 1.0,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    assets = [
        row
        for row in tables.tables["configuration_assets.csv"]
        if row["configuration_id"] == configuration_id and _is_active(row)
    ]
    blockers = [
        row
        for rows in tables.tables.values()
        for row in rows
        if row.get("configuration_id") == configuration_id and row.get("input_status") == "missing_blocker"
    ]
    audit = {
        "configuration_id": configuration_id,
        "build_status": "blocked_missing_inputs",
        "active_assets_count": len(assets),
        "active_processes_count": 0,
        "active_buffers_count": 0,
        "active_materials_count": 0,
        "active_energy_carriers_count": 0,
        "executable_cost_terms_count": 0,
        "blocker_count": len(blockers),
        "warning_count": 0,
        "solver_status": "not_run_blocked_missing_inputs",
        "termination_condition": "not_run_blocked_missing_inputs",
        "objective_value": "not_applicable",
        "variable_count": 0,
        "binary_count": 0,
        "constraint_count": 0,
        "final_product_target_t": _target_for_configuration(tables, configuration_id, target_multiplier),
        "final_product_fulfilled_t": "not_solved",
        "final_product_residual_t": "not_solved",
        "caveat": caveat,
    }
    constraint_rows = [
        {
            "configuration_id": configuration_id,
            "constraint_family": family,
            "implemented": "no",
            "row_count_or_constraint_count": 0,
            "source_table": source_table,
            "blocking_if_missing": "yes",
            "caveat": caveat,
        }
        for family, source_table in (
            ("process_activity", "process_units.csv"),
            ("capacity_bounds", "process_units.csv"),
            ("material_balance", "process_io_coefficients.csv"),
            ("buffer_balance", "buffers_and_stores.csv"),
            ("final_product_fulfilment", "production_targets.csv"),
        )
    ]
    hourly_rows = [
        {
            "hour_index": hour,
            "configuration_id": configuration_id,
            "build_status": "blocked_missing_inputs",
            "C0_BF_BOF_STATIC_BLOCK_activity": "",
            "C1_DRP_activity_t_pellets_h": "",
            "C1_EAF_activity_t_DRI_h": "",
            "final_product_output_t": "",
            "DRI_inventory_t": "",
            "electricity_mwh": "",
            "natural_gas_nm3": "",
            "WAG_generated": "",
            "WAG_used": "",
            "WAG_flared": "",
            "steam": "",
            "oxygen_t": "",
            "total_static_cost": "",
            "caveat": caveat,
        }
        for hour in range(_horizon_hours(tables, horizon_hours_override))
    ]
    return audit, constraint_rows, hourly_rows, blockers


def _solve_c0_configuration(
    tables: UnifiedInputTables,
    *,
    horizon_hours_override: int | None = None,
    target_multiplier: float = 1.0,
    fix_binary_schedule: bool = False,
    enable_minimal_wag_layer: bool = False,
    enable_internal_wag_power: bool = False,
    development_controller_activation: str = "none",
    development_controller_profile_weights: Mapping[str, Mapping[int, float]] | None = None,
    daily_production_guardrail: bool = False,
    rolling_production_deadline_targets_t: Mapping[int, float] | None = None,
    rolling_production_progress_target_t: float | None = None,
    rolling_production_progress_lower_bound_t: float | None = None,
    rolling_production_progress_upper_bound_t: float | None = None,
    rolling_production_execution_block_hours: int = 24,
    rolling_production_hard_exact_execution_target: bool = False,
    rolling_production_exact_deadline_hour: int | None = None,
    rolling_production_exact_deadline_target_t: float | None = None,
    initial_inventory_overrides: Mapping[str, float] | None = None,
    rolling_terminal_inventory_hour: int | None = None,
    rolling_terminal_inventory_bounds_t: Mapping[str, Mapping[str, float]] | None = None,
    commitment_granularity: str = "hourly_binary",
    commitment_day_lengths: Collection[int] | None = None,
    solver_time_limit_seconds: float | None = None,
    continuous_must_run_activities: Collection[str] | None = None,
    c0_coke_chain_reconciliation: Mapping[str, float] | None = None,
    c0_fixed_schedule_hours_by_process: Mapping[str, Collection[int]] | None = None,
    c0_downstream_reference_routing: Mapping[str, Any] | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    site_baseload_ng_mwh_h: float = 0.0,
    site_residual_steam_t_h: float = 0.0,
    site_residual_direct_co2_t_h: float = 0.0,
    external_procurement_flow_coefficients: Mapping[str, float] | None = None,
    deterministic_cost_policy: Mapping[str, Any] | None = None,
    wag_generation_yield_overrides: Mapping[str, float] | None = None,
    bf_electricity_intensity_scale: float = 1.0,
    aggregate_generator_technical_interface: Mapping[str, Any] | None = None,
    full_site_energy_bridge: Mapping[str, Any] | None = None,
    hsm_source_mix_policy: Mapping[str, Any] | None = None,
    electricity_sale_sensitivity: Mapping[str, Any] | None = None,
    allocation_envelope_diagnostic: Mapping[str, Any] | None = None,
    normal_solution_capture: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    inputs = _build_c0_inputs(
        tables,
        horizon_hours_override=horizon_hours_override,
        target_multiplier=target_multiplier,
    )
    inputs = _apply_wag_generation_yield_overrides(
        inputs, wag_generation_yield_overrides
    )
    inputs = _apply_c0_initial_inventory_overrides(inputs, initial_inventory_overrides)
    build_start = time.perf_counter()
    model = _build_c0_model(
        inputs,
        fix_binary_schedule=fix_binary_schedule,
        enable_minimal_wag_layer=enable_minimal_wag_layer,
        enable_internal_wag_power=enable_internal_wag_power,
        development_controller_activation=development_controller_activation,
        development_controller_profile_weights=development_controller_profile_weights,
        daily_production_guardrail=daily_production_guardrail,
        rolling_production_deadline_targets_t=rolling_production_deadline_targets_t,
        commitment_granularity=commitment_granularity,
        commitment_day_lengths=commitment_day_lengths,
        continuous_must_run_activities=continuous_must_run_activities,
        c0_coke_chain_reconciliation=c0_coke_chain_reconciliation,
        c0_fixed_schedule_hours_by_process=c0_fixed_schedule_hours_by_process,
        c0_downstream_reference_routing=c0_downstream_reference_routing,
        linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
        site_background_electricity_mwh_h=site_background_electricity_mwh_h,
        site_baseload_ng_mwh_h=site_baseload_ng_mwh_h,
        site_residual_steam_t_h=site_residual_steam_t_h,
        site_residual_direct_co2_t_h=site_residual_direct_co2_t_h,
        external_procurement_flow_coefficients=external_procurement_flow_coefficients,
        bf_electricity_intensity_scale=bf_electricity_intensity_scale,
        aggregate_generator_technical_interface=aggregate_generator_technical_interface,
        full_site_energy_bridge=full_site_energy_bridge,
        hsm_source_mix_policy=hsm_source_mix_policy,
        electricity_sale_sensitivity=electricity_sale_sensitivity,
    )
    if rolling_production_progress_target_t is not None:
        _add_rolling_production_progress_tracking(
            model,
            execution_block_hours=rolling_production_execution_block_hours,
            next_execution_target_t=rolling_production_progress_target_t,
            hard_exact_execution_target=rolling_production_hard_exact_execution_target,
            exact_deadline_hour=rolling_production_exact_deadline_hour,
            exact_deadline_target_t=rolling_production_exact_deadline_target_t,
            execution_lower_bound_t=rolling_production_progress_lower_bound_t,
            execution_upper_bound_t=rolling_production_progress_upper_bound_t,
        )
    _add_rolling_terminal_inventory_band(
        model,
        terminal_hour=rolling_terminal_inventory_hour,
        bounds_t=rolling_terminal_inventory_bounds_t,
    )
    build_runtime = time.perf_counter() - build_start
    solver_name, solver = _select_solver()
    if solver is None:
        raise S44CModelBuilderError("No LP/MIP solver available for S4.4c C0 physical regression.")
    _apply_solver_time_limit(solver_name, solver, solver_time_limit_seconds)
    solve_start = time.perf_counter()
    try:
        result, cost_metadata = _solve_with_optional_lexicographic_cost(
            model,
            solver=solver,
            configuration_id="C0_current_BF_BOF_reference",
            deterministic_cost_policy=deterministic_cost_policy,
            electricity_sale_sensitivity=electricity_sale_sensitivity,
            allocation_envelope_diagnostic=allocation_envelope_diagnostic,
            normal_solution_capture=normal_solution_capture,
        )
    except RuntimeError as exc:
        solve_runtime = time.perf_counter() - solve_start
        stats = collect_model_stats(model)
        diagnostic_status = "exception_no_solution_loaded"
        diagnostic_termination = "infeasible_or_no_accepted_solution"
        diagnostic_caveat = str(exc)
        if allocation_envelope_diagnostic is None:
            try:
                diagnostic_result = solver.solve(model, load_solutions=False)
                diagnostic_status = str(diagnostic_result.solver.status)
                diagnostic_termination = str(
                    diagnostic_result.solver.termination_condition
                )
            except Exception as diagnostic_exc:  # pragma: no cover - solver-plugin-specific fallback
                diagnostic_caveat = (
                    f"{exc}; diagnostic solve also failed: {diagnostic_exc}"
                )
        else:
            diagnostic_caveat = (
                f"{exc}; allocation-envelope failure evidence was preserved "
                "without a second solve"
            )
        return {
            "configuration_id": "C0_current_BF_BOF_reference",
            "build_status": "solver_failed",
            "active_assets_count": len([row for row in tables.tables["configuration_assets.csv"] if row["configuration_id"] == "C0_current_BF_BOF_reference" and _is_active(row)]),
            "active_processes_count": 7, "active_buffers_count": 4, "active_materials_count": 7,
            "active_energy_carriers_count": 3, "executable_cost_terms_count": 0,
            "blocker_count": 0, "warning_count": 1, "solver_name": solver_name,
            "solver_status": diagnostic_status,
            "termination_condition": diagnostic_termination,
            "objective_value": "not_available", "build_runtime_seconds": round(build_runtime, 6),
            "runtime_seconds": round(solve_runtime, 6), "solver_time_limit_seconds": solver_time_limit_seconds or "",
            "mip_gap": "not_available", "variable_count": stats.variables, "binary_count": stats.binaries,
            "constraint_count": stats.constraints, "final_product_target_t": round(inputs.final_product_target_t, 6),
            "final_product_fulfilled_t": "not_solved", "final_product_residual_t": "not_solved",
            "fixed_binary_schedule_used": str(fix_binary_schedule).lower(),
            "continuous_must_run_activities": ";".join(sorted(continuous_must_run_activities or ())),
            "continuous_must_run_rule_count": len(tuple(continuous_must_run_activities or ())) * inputs.horizon_hours,
            "continuous_must_run_throughput_fixed": "false",
            "caveat": f"C0 solver returned no accepted solution: {diagnostic_caveat}",
        }, [], []
    solve_runtime = time.perf_counter() - solve_start
    solver_status = str(result.solver.status)
    termination_condition = str(result.solver.termination_condition)
    stats = collect_model_stats(model)
    if termination_condition.lower() not in {"optimal", "feasible"}:
        audit = {
            "configuration_id": "C0_current_BF_BOF_reference",
            "build_status": "solver_failed",
            "active_assets_count": len(
                [
                    row
                    for row in tables.tables["configuration_assets.csv"]
                    if row["configuration_id"] == "C0_current_BF_BOF_reference" and _is_active(row)
                ]
            ),
            "active_processes_count": 7,
            "active_buffers_count": 4,
            "active_materials_count": 7,
            "active_energy_carriers_count": 3,
            "executable_cost_terms_count": 0,
            "blocker_count": 0,
            "warning_count": 1,
            "solver_name": solver_name,
            "solver_status": solver_status,
            "termination_condition": termination_condition,
            "objective_value": "not_available",
            "build_runtime_seconds": round(build_runtime, 6),
            "runtime_seconds": round(solve_runtime, 6),
            "solver_time_limit_seconds": solver_time_limit_seconds or "",
            "mip_gap": _mip_gap(result),
            "variable_count": stats.variables,
            "binary_count": stats.binaries,
            "constraint_count": stats.constraints,
            "final_product_target_t": round(inputs.final_product_target_t, 6),
            "final_product_fulfilled_t": "not_solved",
            "final_product_residual_t": "not_solved",
            "fixed_binary_schedule_used": str(fix_binary_schedule).lower(),
            "continuous_must_run_activities": ";".join(sorted(continuous_must_run_activities or ())),
            "continuous_must_run_rule_count": len(tuple(continuous_must_run_activities or ())) * inputs.horizon_hours,
            "continuous_must_run_throughput_fixed": "false",
            "caveat": "C0 model was built from B5 inputs but solver did not return a feasible/optimal solution.",
        }
        return audit, [], []

    objective_value = (
        float(cost_metadata["primary_cost_objective_eur"])
        if cost_metadata["cost_objective_active"]
        else float(value(model.static_price_naive_objective))
    )
    final_product_fulfilled = sum(float(value(model.final_product_output[t])) for t in model.TIME)
    final_product_residual = final_product_fulfilled - inputs.final_product_target_t
    coke_inventory = [float(value(model.coke_inventory[t])) for t in model.TIME]
    sinter_inventory = [float(value(model.sinter_inventory[t])) for t in model.TIME]
    hot_iron_inventory = [float(value(model.hot_iron_inventory[t])) for t in model.TIME]
    cold_slab_inventory = [float(value(model.cold_slab_inventory[t])) for t in model.TIME]
    coking_total = [
        float(value(model.coking_plant_1[t] + model.coking_plant_2[t]))
        for t in model.TIME
    ]
    coke_output = [float(value(model.coke_output[t])) for t in model.TIME]
    bf_coke_demand = [float(value(model.bf_coke_demand[t])) for t in model.TIME]
    bf_sinter = [float(value(model.bf_sinter_input[t])) for t in model.TIME]
    bof = [float(value(model.basic_oxygen_furnace[t])) for t in model.TIME]
    hsm = [float(value(model.hot_strip_mill[t])) for t in model.TIME]
    wag_generated = [float(value(model.wag_generated[t])) for t in model.TIME]
    wag_used = [float(value(model.wag_used[t])) for t in model.TIME] if enable_minimal_wag_layer else [0.0 for _ in model.TIME]
    wag_flared = [float(value(model.wag_flared[t])) for t in model.TIME] if enable_minimal_wag_layer else wag_generated
    ng_boiler = (
        [float(value(model.ng_to_boiler_mwh[t])) for t in model.TIME]
        if enable_minimal_wag_layer
        else [0.0 for _ in model.TIME]
    )
    steam = (
        [float(value(model.steam_production_mwh[t])) for t in model.TIME]
        if enable_minimal_wag_layer
        else [0.0 for _ in model.TIME]
    )

    audit = {
        "configuration_id": "C0_current_BF_BOF_reference",
        "build_status": "solved",
        "active_assets_count": len(
            [
                row
                for row in tables.tables["configuration_assets.csv"]
                if row["configuration_id"] == "C0_current_BF_BOF_reference" and _is_active(row)
            ]
        ),
        "active_processes_count": 7,
        "active_buffers_count": 4,
        "active_materials_count": 7,
        "active_energy_carriers_count": 6 if enable_minimal_wag_layer else 3,
        "executable_cost_terms_count": cost_metadata["priced_flow_count"],
        "blocker_count": 0,
        "warning_count": 2,
        "solver_name": solver_name,
        "solver_status": solver_status,
        "termination_condition": termination_condition,
        "objective_value": round(objective_value, 6),
        "objective_type": (
            "represented_external_procurement_cost_eur"
            if cost_metadata["cost_objective_active"]
            else "physical_tie_breaker"
        ),
        "primary_cost_objective_eur": (
            round(float(cost_metadata["primary_cost_objective_eur"]), 6)
            if cost_metadata["primary_cost_objective_eur"] is not None
            else ""
        ),
        "primary_import_procurement_cost_eur": (
            round(float(cost_metadata["primary_import_procurement_cost_eur"]), 6)
            if cost_metadata["primary_import_procurement_cost_eur"] is not None
            else ""
        ),
        "primary_electricity_export_revenue_eur": (
            round(float(cost_metadata["primary_electricity_export_revenue_eur"]), 6)
            if cost_metadata["primary_electricity_export_revenue_eur"] is not None
            else ""
        ),
        "electricity_sale_sensitivity_active": cost_metadata[
            "electricity_sale_sensitivity_active"
        ],
        "sale_breakthrough_mode": (
            (cost_metadata.get("sale_breakthrough_test") or {}).get("mode", "")
        ),
        "sale_breakthrough_resource_caps_status": (
            (cost_metadata.get("sale_breakthrough_test") or {}).get(
                "resource_caps_status", ""
            )
        ),
        "sale_breakthrough_actual_gross_grid_import_mwh": (
            (cost_metadata.get("sale_breakthrough_test") or {})
            .get("actual_metrics", {})
            .get("gross_grid_import_mwh", "")
        ),
        "sale_breakthrough_actual_named_ng_mwh_lhv": (
            (cost_metadata.get("sale_breakthrough_test") or {})
            .get("actual_metrics", {})
            .get("named_ng_mwh_lhv", "")
        ),
        "sale_breakthrough_actual_wag_generator_electricity_mwh": (
            (cost_metadata.get("sale_breakthrough_test") or {})
            .get("actual_metrics", {})
            .get("wag_generator_electricity_mwh", "")
        ),
        "grid_import_bound_audit_status": (
            model.grid_import_bound_audit["status"]
            if hasattr(model, "grid_import_bound_audit")
            else "not_applicable"
        ),
        "grid_import_bound_derivation_method": (
            model.grid_import_bound_audit["derivation_method"]
            if hasattr(model, "grid_import_bound_audit")
            else ""
        ),
        "grid_import_bound_audit_runtime_seconds": (
            model.grid_import_bound_audit["runtime_seconds"]
            if hasattr(model, "grid_import_bound_audit")
            else 0.0
        ),
        "grid_import_hourly_upper_bounds_json": (
            json.dumps(
                model.grid_import_bound_audit["hourly_bounds"],
                sort_keys=True,
                separators=(",", ":"),
            )
            if hasattr(model, "grid_import_bound_audit")
            else "[]"
        ),
        "primary_cost_best_bound_eur": (
            round(float(cost_metadata["primary_cost_best_bound_eur"]), 6)
            if cost_metadata["primary_cost_best_bound_eur"] is not None
            else ""
        ),
        "primary_cost_best_bound_availability": cost_metadata[
            "primary_cost_best_bound_availability"
        ],
        "primary_cost_solver_status": cost_metadata["primary_cost_solver_status"],
        "primary_cost_termination_condition": cost_metadata[
            "primary_cost_termination_condition"
        ],
        "primary_cost_mip_gap": cost_metadata["primary_cost_mip_gap"],
        "primary_cost_runtime_seconds": round(
            float(cost_metadata["primary_cost_runtime_seconds"]), 6
        ),
        "production_progress_objective_active": cost_metadata[
            "production_progress_objective_active"
        ],
        "production_progress_target_t": (
            round(float(cost_metadata["production_progress_target_t"]), 6)
            if cost_metadata["production_progress_target_t"] is not None
            else ""
        ),
        "production_progress_optimum_deviation_t": (
            round(
                float(cost_metadata["production_progress_optimum_deviation_t"]),
                9,
            )
            if cost_metadata["production_progress_optimum_deviation_t"]
            is not None
            else ""
        ),
        "production_progress_actual_t": (
            round(float(cost_metadata["production_progress_actual_t"]), 6)
            if cost_metadata["production_progress_actual_t"] is not None
            else ""
        ),
        "production_progress_surplus_t": (
            round(float(cost_metadata["production_progress_surplus_t"]), 9)
            if cost_metadata["production_progress_surplus_t"] is not None
            else ""
        ),
        "production_progress_deficit_t": (
            round(float(cost_metadata["production_progress_deficit_t"]), 9)
            if cost_metadata["production_progress_deficit_t"] is not None
            else ""
        ),
        "production_progress_runtime_seconds": round(
            float(cost_metadata["production_progress_runtime_seconds"]), 6
        ),
        "tie_break_objective_value": cost_metadata["tie_break_objective_value"],
        "tie_break_cost_objective_eur": (
            round(float(cost_metadata["tie_break_cost_objective_eur"]), 6)
            if cost_metadata["tie_break_cost_objective_eur"] is not None
            else ""
        ),
        "tie_break_runtime_seconds": round(
            float(cost_metadata["tie_break_runtime_seconds"]), 6
        ),
        "priced_flow_count": cost_metadata["priced_flow_count"],
        "build_runtime_seconds": round(build_runtime, 6),
        "runtime_seconds": round(solve_runtime, 6),
        "solver_time_limit_seconds": solver_time_limit_seconds or "",
        "mip_gap": _mip_gap(result),
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "final_product_target_t": round(inputs.final_product_target_t, 6),
        "final_product_fulfilled_t": round(final_product_fulfilled, 6),
        "final_product_residual_t": round(final_product_residual, 9),
        "coke_terminal_residual_t": round(coke_inventory[-1] - inputs.coke_store_initial_t, 9),
        "sinter_terminal_residual_t": round(sinter_inventory[-1] - inputs.sinter_store_initial_t, 9),
        "hot_iron_terminal_residual_t": round(hot_iron_inventory[-1] - inputs.hot_iron_store_initial_t, 9),
        "cold_slab_terminal_residual_t": round(cold_slab_inventory[-1] - inputs.cold_slab_store_initial_t, 9),
        "coke_inventory_min_t": round(min(coke_inventory), 6),
        "coke_inventory_max_t": round(max(coke_inventory), 6),
        "sinter_inventory_min_t": round(min(sinter_inventory), 6),
        "sinter_inventory_max_t": round(max(sinter_inventory), 6),
        "hot_iron_inventory_min_t": round(min(hot_iron_inventory), 6),
        "hot_iron_inventory_max_t": round(max(hot_iron_inventory), 6),
        "cold_slab_inventory_min_t": round(min(cold_slab_inventory), 6),
        "cold_slab_inventory_max_t": round(max(cold_slab_inventory), 6),
        "coking_input_total_t": round(sum(coking_total), 6),
        "coke_output_total_t": round(sum(coke_output), 6),
        "bf_coke_demand_total_t": round(sum(bf_coke_demand), 6),
        "coke_chain_reconciliation_active": str(c0_coke_chain_reconciliation is not None).lower(),
        "bf_sinter_input_total_t": round(sum(bf_sinter), 6),
        "bof_hot_iron_input_total_t": round(sum(bof), 6),
        "hsm_input_total_t": round(sum(hsm), 6),
        "hsm_final_output_total_t": round(
            sum(float(value(model.c0_hsm_final_product_output[t])) for t in model.TIME), 6
        ),
        "dsp_final_output_total_t": round(
            sum(float(value(model.c0_dsp_final_product_output[t])) for t in model.TIME), 6
        ),
        "reference_downstream_routing_active": str(c0_downstream_reference_routing is not None).lower(),
        "electricity_mwh": round(sum(float(value(model.gross_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "natural_gas_nm3": 0.0,
        "natural_gas_boiler_mwh": round(sum(ng_boiler), 6),
        "steam_15bar_explicit_demand_t": round(sum(float(value(model.steam_15bar_explicit_demand_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "residual_steam_15bar_demand_t": round(sum(float(value(model.residual_steam_15bar_demand_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "steam_15bar_total_demand_t": round(sum(float(value(model.steam_15bar_demand_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "steam_15bar_unserved_t": round(sum(float(value(model.steam_15bar_unserved_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "generator_named_ng_mwh": _costed_c0_ng_reporting_value(
            sum(float(value(model.generator_named_ng_mwh[t])) for t in model.TIME)
        )
        if enable_minimal_wag_layer
        else 0.0,
        "full_site_fixed_ng_component_mwh": _costed_c0_ng_reporting_value(
            sum(float(value(model.full_site_fixed_ng_component_mwh[t])) for t in model.TIME)
        )
        if enable_minimal_wag_layer
        else 0.0,
        "full_site_fixed_ng_component_gross_mwh": _costed_c0_ng_reporting_value(
            sum(
                float(value(model.full_site_fixed_ng_component_gross_mwh[t]))
                for t in model.TIME
            )
        )
        if enable_minimal_wag_layer
        else 0.0,
        "hsm_ng_reclassified_from_fixed_bridge_mwh": _costed_c0_ng_reporting_value(
            sum(
                float(value(model.hsm_ng_reclassified_from_fixed_bridge_mwh[t]))
                for t in model.TIME
            )
        )
        if enable_minimal_wag_layer
        else 0.0,
        "hsm_source_mix_policy_active": str(
            enable_minimal_wag_layer and model.hsm_source_mix_policy_active
        ).lower(),
        "hsm_ng_energy_share_target": (
            model.hsm_ng_energy_share_target if enable_minimal_wag_layer else 0.0
        ),
        "flexible_other_site_heat_ng_mwh": _costed_c0_ng_reporting_value(
            sum(float(value(model.flexible_other_site_heat_ng_mwh[t])) for t in model.TIME)
        )
        if enable_minimal_wag_layer
        else 0.0,
        "full_site_energy_bridge_named_ng_mwh": _costed_c0_ng_reporting_value(
            sum(float(value(model.full_site_energy_bridge_named_ng_mwh[t])) for t in model.TIME)
        )
        if enable_minimal_wag_layer
        else 0.0,
        "site_baseload_ng_mwh": _costed_c0_ng_reporting_value(
            sum(float(value(model.site_baseload_ng_mwh[t])) for t in model.TIME)
        )
        if enable_minimal_wag_layer
        else 0.0,
        "total_named_ng_procurement_mwh": _costed_c0_ng_reporting_value(
            sum(float(value(model.total_named_ng_procurement_mwh[t])) for t in model.TIME)
        )
        if enable_minimal_wag_layer
        else 0.0,
        "aggregate_generator_technical_interface_active": str(
            enable_minimal_wag_layer
            and model.aggregate_generator_technical_interface_active
        ).lower(),
        "aggregate_generator_volume_cap_nm3_h": (
            model.aggregate_generator_volume_cap_nm3_h
            if enable_minimal_wag_layer
            else 0.0
        ),
        "aggregate_generator_electrical_capacity_mw": (
            model.aggregate_generator_electrical_capacity_mw
            if enable_minimal_wag_layer
            else 0.0
        ),
        "steam_mwh": round(sum(steam), 6),
        "oxygen_t": 0.0,
        "WAG_generated": round(sum(wag_generated), 6),
        "WAG_used": round(sum(wag_used), 6),
        "WAG_flared": round(sum(wag_flared), 6),
        "WAG_explicit_combustion_co2_t": round(sum(float(value(model.wag_explicit_combustion_co2_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "explicit_NG_combustion_co2_t": round(sum(float(value(model.explicit_ng_combustion_co2_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "residual_unmodelled_direct_co2_t": round(sum(float(value(model.residual_unmodelled_direct_co2_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "total_direct_co2_reporting_t": round(sum(float(value(model.total_direct_co2_reporting_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "development_controller_activation": development_controller_activation,
        "development_controller_profile_weights_active": development_controller_profile_weights is not None,
        "HSM_reheat_demand_mwh": round(sum(float(value(model.hsm_reheat_demand_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "HSM_NG_mwh": round(sum(float(value(model.ng_to_hsm_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "PEFA_NG_mwh": round(
            sum(float(value(model.ng_to_pefa_malerij_mwh[t] + model.ng_to_pefa_branderij_mwh[t])) for t in model.TIME),
            6,
        )
        if enable_minimal_wag_layer
        else 0.0,
        "development_controller_electricity_mwh": round(
            sum(float(value(model.development_controller_electricity_mwh[t])) for t in model.TIME), 6
        )
        if enable_minimal_wag_layer
        else 0.0,
        "fixed_binary_schedule_used": str(fix_binary_schedule).lower(),
        "continuous_must_run_activities": ";".join(sorted(continuous_must_run_activities or ())),
        "continuous_must_run_rule_count": len(tuple(continuous_must_run_activities or ())) * inputs.horizon_hours,
        "continuous_must_run_throughput_fixed": "false",
        "sinter_activity_basis": "iron_ore_feed_t",
        "sinter_output_per_t_iron_ore": inputs.sinter_output_per_t_iron_ore,
        "sinter_iron_ore_feed_total_t": round(
            sum(float(value(model.sintering_plant[t])) for t in model.TIME), 6
        ),
        "sinter_output_total_t": round(sum(float(value(model.sinter_output[t])) for t in model.TIME), 6),
        "minimal_wag_layer_active": str(enable_minimal_wag_layer).lower(),
        "daily_production_guardrail_active": str(daily_production_guardrail).lower(),
        "allocation_tiebreaker": "non_economic_minimise_flare_1e-6" if enable_minimal_wag_layer else "",
        "caveat": "Solved C0 static BF-BOF development-only physical regression; WAG is balanced by carrier with process sinks, boiler placeholder, and flaring when minimal WAG layer is active.",
    }
    if allocation_envelope_diagnostic is not None:
        audit.update(
            {
                key: cost_metadata[key]
                for key in (
                    "allocation_envelope_active",
                    "allocation_envelope_endpoint",
                    "allocation_envelope_breakthrough_mode",
                    "allocation_envelope_cost_preservation_requirement",
                    "allocation_envelope_execution_hours",
                    "allocation_envelope_objective_value_mwh",
                    "allocation_envelope_endpoint_accuracy_schema",
                    "allocation_envelope_endpoint_incumbent_basis",
                    "allocation_envelope_endpoint_best_bound_availability",
                    "allocation_envelope_endpoint_best_bound_mwh",
                    "allocation_envelope_endpoint_objective_bound_abs_gap_mwh",
                    "allocation_envelope_endpoint_objective_bound_audit_status",
                    "allocation_envelope_endpoint_bound_sense_status",
                    "allocation_envelope_endpoint_relative_mip_gap_target",
                    "allocation_envelope_endpoint_absolute_mip_gap_target_mwh",
                    "allocation_envelope_endpoint_bound_comparison_epsilon_mwh",
                    "allocation_envelope_endpoint_solver_options",
                    "allocation_envelope_endpoint_solver_options_sha256",
                    "allocation_envelope_runtime_seconds",
                    "allocation_envelope_solver_status",
                    "allocation_envelope_termination_condition",
                    "allocation_envelope_mip_gap",
                    "allocation_envelope_warmstart_solver_argument",
                    "allocation_envelope_endpoint_solver_log_path",
                    "allocation_envelope_endpoint_solver_log_sha256",
                    "allocation_envelope_endpoint_pre_solve_model_path",
                    "allocation_envelope_endpoint_pre_solve_model_sha256",
                    "allocation_envelope_warm_start_status",
                    "allocation_envelope_warm_start_assignment_count",
                    "allocation_envelope_warm_start_variable_name_sha256",
                    "allocation_envelope_warm_start_variable_schema_sha256",
                    "allocation_envelope_warm_start_value_state_sha256",
                    "allocation_envelope_warm_start_full_state_sha256",
                    "allocation_envelope_warm_start_source_record_sha256",
                    "allocation_envelope_warm_start_fixed_overwrite_count",
                    "allocation_envelope_warm_start_max_constraint_violation",
                    "allocation_envelope_warm_start_max_bound_violation",
                    "allocation_envelope_warm_start_max_integrality_violation",
                    "allocation_envelope_warm_start_audit_path",
                    "allocation_envelope_warm_start_audit_sha256",
                    "allocation_envelope_cost_eur",
                    "allocation_envelope_cost_minus_primary_eur",
                    "allocation_envelope_primary_cost_best_bound_eur",
                    "allocation_envelope_primary_cost_best_bound_availability",
                    "allocation_envelope_cost_minus_primary_best_bound_eur",
                    "allocation_envelope_primary_objective_audit_status",
                    "allocation_envelope_best_bound_audit_status",
                    "allocation_envelope_upper_cost_tolerance_eur",
                    "allocation_envelope_solver_cost_feasibility_tolerance_eur",
                    "allocation_envelope_normal_cost_eur",
                    "allocation_envelope_normal_cost_minus_upper_limit_eur",
                    "allocation_envelope_normal_incumbent_min_formulation_feasible",
                    "allocation_envelope_normal_incumbent_max_formulation_feasible",
                    "allocation_envelope_normal_incumbent_feasibility_audit",
                    "allocation_envelope_normal_objective_value_mwh",
                    "allocation_envelope_normal_handoff_snapshot",
                    "allocation_envelope_endpoint_handoff_snapshot",
                    "allocation_envelope_normal_handoff_hash",
                    "allocation_envelope_endpoint_handoff_hash",
                    "allocation_envelope_raw_endpoint_handoff_hash",
                    "allocation_envelope_local_normal_handoff_snapshot",
                    "allocation_envelope_max_local_normal_schedule_residual",
                    "allocation_envelope_max_state_residual",
                    "allocation_envelope_state_tolerance",
                    "allocation_envelope_solver_state_feasibility_tolerance",
                    "allocation_envelope_effective_state_tolerance",
                    "allocation_envelope_normal_feasibility_oracle_status",
                    "allocation_envelope_normal_feasibility_oracle_record_path",
                    "allocation_envelope_normal_feasibility_oracle_record_sha256",
                    "allocation_envelope_normal_solution_variable_count",
                    "allocation_envelope_normal_solution_variable_name_sha256",
                    "allocation_envelope_normal_solution_variable_schema_sha256",
                    "allocation_envelope_normal_solution_variable_fixed_schema_sha256",
                    "allocation_envelope_normal_solution_record_sha256",
                    "allocation_envelope_endpoint_prefixed_checked_count",
                    "allocation_envelope_oracle_temporarily_fixed_count",
                    "allocation_envelope_endpoint_prefixed_overwrite_count",
                    "allocation_envelope_endpoint_prefixed_max_value_residual",
                    "allocation_envelope_endpoint_fixed_state_sha256_before",
                    "allocation_envelope_endpoint_fixed_state_sha256_after",
                    "allocation_envelope_deactivated_deadline_row",
                    "allocation_envelope_iis_evidence_sha256",
                    "allocation_envelope_oracle_only",
                )
                if key in cost_metadata
            }
        )
    if normal_solution_capture is not None:
        audit.update(
            {
                key: cost_metadata[key]
                for key in (
                    "normal_solution_capture_path",
                    "normal_solution_capture_sha256",
                    "normal_solution_variable_count",
                    "normal_solution_variable_name_sha256",
                    "normal_solution_variable_schema_sha256",
                    "normal_solution_variable_fixed_schema_sha256",
                )
            }
        )
    if enable_minimal_wag_layer:
        audit.update(
            {
                "BFG_generated_mwh": round(sum(float(value(model.bfg_generated[t])) for t in model.TIME), 6),
                "COG_generated_mwh": round(sum(float(value(model.cog_generated[t])) for t in model.TIME), 6),
                "BOFG_generated_mwh": round(sum(float(value(model.bofg_generated[t])) for t in model.TIME), 6),
                "BFG_used_mwh": round(
                    sum(float(value(model.bfg_to_bf_hot_stove[t] + model.bfg_to_kgf1[t] + model.bfg_to_hsm[t] + model.bfg_to_boiler[t] + model.bfg_to_vattenfall[t])) for t in model.TIME),
                    6,
                ),
                "COG_used_mwh": round(
                    sum(
                        float(
                            value(
                                model.cog_to_kgf1[t]
                                + model.cog_to_kgf2[t]
                                + model.cog_to_sinter[t]
                                + model.cog_to_hsm[t]
                                + model.cog_to_pefa_branderij[t]
                                + model.cog_to_boiler[t]
                                + model.cog_to_vattenfall[t]
                            )
                        )
                        for t in model.TIME
                    ),
                    6,
                ),
                "BOFG_used_mwh": round(
                    sum(float(value(model.bofg_to_hsm[t] + model.bofg_to_pefa_malerij[t] + model.bofg_to_vattenfall[t])) for t in model.TIME),
                    6,
                ),
                "BFG_to_vattenfall_mwh": round(sum(float(value(model.bfg_to_vattenfall[t])) for t in model.TIME), 6),
                "COG_to_vattenfall_mwh": round(sum(float(value(model.cog_to_vattenfall[t])) for t in model.TIME), 6),
                "BOFG_to_vattenfall_mwh": round(sum(float(value(model.bofg_to_vattenfall[t])) for t in model.TIME), 6),
                "vattenfall_fuel_mwh": round(sum(float(value(model.vattenfall_fuel_mwh[t])) for t in model.TIME), 6),
                "WAG_generator_electricity_mwh": round(sum(float(value(model.wag_generator_electricity_mwh[t])) for t in model.TIME), 6),
                "NG_generator_electricity_mwh": round(sum(float(value(model.ng_generator_electricity_mwh[t])) for t in model.TIME), 6),
                "total_generator_electricity_mwh": round(sum(float(value(model.total_generator_electricity_mwh[t])) for t in model.TIME), 6),
                "wag_electricity_mwh": round(sum(float(value(model.wag_electricity_mwh[t])) for t in model.TIME), 6),
                "represented_gross_electricity_before_background_mwh": round(sum(float(value(model.represented_gross_electricity_before_background_mwh[t])) for t in model.TIME), 6),
                "site_background_electricity_mwh": round(sum(float(value(model.site_background_electricity_mwh[t])) for t in model.TIME), 6),
                "gross_total_electricity_mwh": round(sum(float(value(model.gross_total_electricity_mwh[t])) for t in model.TIME), 6),
                "gross_electricity_mwh": round(sum(float(value(model.gross_electricity_mwh[t])) for t in model.TIME), 6),
                "gross_grid_import_mwh": round(sum(float(value(model.gross_grid_import_mwh[t])) for t in model.TIME), 6),
                "gross_grid_export_mwh": round(sum(float(value(model.gross_grid_export_mwh[t])) for t in model.TIME), 6),
                "net_grid_exchange_mwh": round(sum(float(value(model.net_grid_exchange_mwh[t])) for t in model.TIME), 6),
                "net_grid_import_mwh": round(sum(float(value(model.net_grid_import_mwh[t])) for t in model.TIME), 6),
                "BFG_flared_mwh": round(sum(float(value(model.bfg_flared[t])) for t in model.TIME), 6),
                "COG_flared_mwh": round(sum(float(value(model.cog_flared[t])) for t in model.TIME), 6),
                "BOFG_flared_mwh": round(sum(float(value(model.bofg_flared[t])) for t in model.TIME), 6),
                "flaring_co2_t": round(sum(float(value(model.flaring_co2_t[t])) for t in model.TIME), 6),
                "flaring_co2_diagnostic_cost_eur": round(
                    sum(float(value(model.flaring_co2_diagnostic_cost_eur[t])) for t in model.TIME),
                    6,
                ),
                "max_abs_wag_balance_residual_mwh": round(
                    max(
                        max(abs(float(value(model.bfg_balance_residual[t]))) for t in model.TIME),
                        max(abs(float(value(model.cog_balance_residual[t]))) for t in model.TIME),
                        max(abs(float(value(model.bofg_balance_residual[t]))) for t in model.TIME),
                    ),
                    9,
                ),
            }
        )
    constraint_rows = [
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "constraint_family": "process_activity_variables",
            "implemented": "yes",
            "row_count_or_constraint_count": 7 * inputs.horizon_hours,
            "source_table": "process_units.csv",
            "blocking_if_missing": "yes",
            "caveat": "C0 process activity variables and on/off controls implemented from B5 rows.",
        },
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "constraint_family": "capacity_bounds",
            "implemented": "yes",
            "row_count_or_constraint_count": 14 * inputs.horizon_hours,
            "source_table": "process_units.csv",
            "blocking_if_missing": "yes",
            "caveat": "Min/max figure-derived or symmetry-assumption process bounds implemented.",
        },
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "constraint_family": "continuous_operation_class",
            "implemented": "yes" if continuous_must_run_activities else "no",
            "row_count_or_constraint_count": len(tuple(continuous_must_run_activities or ())) * inputs.horizon_hours,
            "source_table": "c5_component_ontology/c5_builder_operation_class_overrides.csv",
            "blocking_if_missing": "yes",
            "caveat": "Source-classified continuous assets are fixed on; their process throughput remains an unfixed variable inside the governed min/max bounds.",
        },
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "constraint_family": "material_balance",
            "implemented": "yes",
            "row_count_or_constraint_count": 4 * inputs.horizon_hours,
            "source_table": "process_io_coefficients.csv;buffers_and_stores.csv",
            "blocking_if_missing": "yes",
            "caveat": "Coke, sinter, hot-iron, and cold-slab balances implemented.",
        },
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "constraint_family": "terminal_inventory_rule",
            "implemented": "yes",
            "row_count_or_constraint_count": 4,
            "source_table": "buffers_and_stores.csv",
            "blocking_if_missing": "yes",
            "caveat": "Terminal equality to initial inventory implemented for active C0 stores.",
        },
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "constraint_family": "final_product_fulfilment",
            "implemented": "yes",
            "row_count_or_constraint_count": 1,
            "source_table": "production_targets.csv",
            "blocking_if_missing": "yes",
            "caveat": (
                "Hard cumulative quota lower bound; overproduction is allowed and reported."
                if rolling_production_deadline_targets_t is not None
                else "Hard equality to final-product target."
            ),
        },
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "constraint_family": "WAG_generation_and_spillage" if not enable_minimal_wag_layer else "carrier_specific_WAG_balances",
            "implemented": "yes",
            "row_count_or_constraint_count": inputs.horizon_hours if not enable_minimal_wag_layer else 5 * inputs.horizon_hours,
            "source_table": "wag_generation_coefficients.csv;wag_sink_eligibility.csv",
            "blocking_if_missing": "yes",
            "caveat": "WAG generated from BFG/COG/BOFG coefficients and closed by explicit flaring/spillage; no valuation."
            if not enable_minimal_wag_layer
            else "BFG/COG/BOFG each balance hourly to mandatory process sinks, boiler placeholder use, or carrier-specific flaring.",
        },
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "constraint_family": "daily_production_guardrail",
            "implemented": "yes" if daily_production_guardrail else "no",
            "row_count_or_constraint_count": 2 * (inputs.horizon_hours // 24) if daily_production_guardrail else 0,
            "source_table": "S4.4c3 production-stability guardrail",
            "blocking_if_missing": "no",
            "caveat": "Daily production must stay within 80-120 percent of average daily target when active.",
        },
    ]
    import_bound_by_hour = {
        int(row["hour_index"]): row
        for row in getattr(model, "grid_import_bound_audit", {}).get(
            "hourly_bounds", []
        )
    }
    hourly_rows = []
    for t in model.TIME:
        hourly_rows.append(
            {
                "hour_index": int(t),
                "configuration_id": "C0_current_BF_BOF_reference",
                "build_status": "solved",
                "C0_BF_BOF_STATIC_BLOCK_activity": round(float(value(model.hot_strip_mill[t])), 6),
                "C0_KGF1_input_t_h": round(float(value(model.coking_plant_1[t])), 6),
                "C0_KGF2_input_t_h": round(float(value(model.coking_plant_2[t])), 6),
                "C0_coking_input_t_h": round(float(value(model.coking_plant_1[t] + model.coking_plant_2[t])), 12),
                "C0_KGF1_coke_output_t_h": round(float(value(model.coke_output_kgf1[t])), 6),
                "C0_KGF2_coke_output_t_h": round(float(value(model.coke_output_kgf2[t])), 6),
                "C0_coke_output_t_h": round(float(value(model.coke_output[t])), 6),
                "C0_BF_coke_demand_t_h": round(float(value(model.bf_coke_demand[t])), 6),
                "C0_sintering_input_t_h": round(float(value(model.sintering_plant[t])), 6),
                "C0_sinter_iron_ore_feed_t_h": round(float(value(model.sintering_plant[t])), 12),
                "C0_sinter_output_t_h": round(float(value(model.sinter_output[t])), 6),
                "PEFA_pellet_output_t": round(
                    _model_value_or_zero(model, "pefa_pellet_output_t", t), 6
                ),
                "PEFA_iron_ore_input_t": round(
                    _model_value_or_zero(model, "pefa_iron_ore_input_t", t), 12
                ),
                "C0_BF6_sinter_input_t_h": round(float(value(model.blast_furnace_6[t])), 6),
                "C0_BF7_sinter_input_t_h": round(float(value(model.blast_furnace_7[t])), 6),
                "C0_BF_sinter_input_t_h": round(float(value(model.bf_sinter_input[t])), 6),
                "C0_BF_hot_iron_output_t": round(float(value(model.bf_hot_iron_output[t])), 6),
                "C0_BF_PCI_input_t": round(float(value(model.bf_pci_input_t[t])), 12),
                "C0_BOF_hot_iron_input_t_h": round(float(value(model.basic_oxygen_furnace[t])), 6),
                "C0_BOF_crude_steel_output_t": round(float(value(model.bof_crude_steel_output[t])), 6),
                "C0_BOF_scrap_input_t": round(float(value(model.c0_bof_scrap_input[t])), 12),
                "C0_BOF_material_loss_t": round(float(value(model.c0_bof_material_loss[t])), 6),
                "C0_BOF_material_balance_residual_t": round(
                    float(value(model.c0_bof_material_balance_residual[t])), 9
                ),
                "C0_HSM_input_t_h": round(float(value(model.hot_strip_mill[t])), 6),
                "C0_HSM_final_product_t": round(float(value(model.c0_hsm_final_product_output[t])), 6),
                "C0_HSM_material_loss_t": round(
                    float(value(model.hot_strip_mill[t] - model.c0_hsm_final_product_output[t])), 6
                ),
                "C0_DSP_liquid_steel_input_t": round(float(value(model.c0_dsp_liquid_steel_input[t])), 6),
                "C0_DSP_final_product_t": round(float(value(model.c0_dsp_final_product_output[t])), 6),
                "C0_DSP_material_loss_t": round(float(value(model.c0_dsp_material_loss[t])), 6),
                "C0_HSM_origin_tag": "endogenous_BOF_route",
                "C0_DSP_origin_tag": (
                    "endogenous_BOF_reference_route"
                    if c0_downstream_reference_routing is not None
                    else "no_executable_C0_DSP_route"
                ),
                "C0_KGF1_on": round(float(value(model.coking_plant_1_on[t])), 6),
                "C0_KGF2_on": round(float(value(model.coking_plant_2_on[t])), 6),
                "C0_sintering_on": round(float(value(model.sintering_plant_on[t])), 6),
                "C0_BF6_on": round(float(value(model.blast_furnace_6_on[t])), 6),
                "C0_BF7_on": round(float(value(model.blast_furnace_7_on[t])), 6),
                "C0_BOF_on": round(float(value(model.basic_oxygen_furnace_on[t])), 6),
                "C0_HSM_on": round(float(value(model.hot_strip_mill_on[t])), 6),
                "C1_DRP_activity_t_pellets_h": "",
                "C1_EAF_activity_t_DRI_h": "",
                "final_product_output_t": round(float(value(model.final_product_output[t])), 6),
                "final_product_output_t_unrounded": float(
                    value(model.final_product_output[t])
                ),
                "coke_inventory_t": round(float(value(model.coke_inventory[t])), 6),
                "coke_inventory_t_unrounded": float(value(model.coke_inventory[t])),
                "sinter_inventory_t": round(float(value(model.sinter_inventory[t])), 6),
                "sinter_inventory_t_unrounded": float(
                    value(model.sinter_inventory[t])
                ),
                "hot_iron_inventory_t": round(float(value(model.hot_iron_inventory[t])), 6),
                "hot_iron_inventory_t_unrounded": float(
                    value(model.hot_iron_inventory[t])
                ),
                "cold_slab_inventory_t": round(float(value(model.cold_slab_inventory[t])), 6),
                "cold_slab_inventory_t_unrounded": float(
                    value(model.cold_slab_inventory[t])
                ),
                "DRI_inventory_t": "",
                "base_process_electricity_mwh": 0.0,
                "DRP_electricity_mwh": 0.0,
                "EAF_arc_electricity_mwh": 0.0,
                "HSM_rolling_electricity_mwh": round(_model_value_or_zero(model, "hsm_rolling_electricity_mwh", t), 6),
                "PEFA_electricity_mwh": round(_model_value_or_zero(model, "pefa_electricity_mwh", t), 6),
                "BOF_electricity_mwh": round(_model_value_or_zero(model, "bof_electricity_mwh", t), 6),
                "BF_electricity_mwh": round(_model_value_or_zero(model, "bf_electricity_mwh", t), 6),
                "KGF_electricity_mwh": round(_model_value_or_zero(model, "kgf_electricity_mwh", t), 6),
                "DSP_electricity_mwh": round(_model_value_or_zero(model, "dsp_electricity_mwh", t), 6),
                "EAF_secondary_electricity_mwh": 0.0,
                "ASU_oxygen_electricity_mwh": round(_model_value_or_zero(model, "asu_electricity_mwh", t), 6),
                "Linde_N2_auxiliary_electricity_mwh": round(_model_value_or_zero(model, "linde_n2_auxiliary_electricity_mwh", t), 6),
                "Linde_total_electricity_mwh": round(_model_value_or_zero(model, "linde_total_electricity_mwh", t), 6),
                "sinter_electricity_mwh": round(_model_value_or_zero(model, "sinter_electricity_mwh", t), 6),
                "represented_electricity_bucket_sum_mwh": round(
                    _model_value_or_zero(model, "development_controller_electricity_mwh", t)
                    + _model_value_or_zero(model, "electricity_boundary_development_mwh", t), 6
                ),
                "electricity_bucket_sum_residual_mwh": round(
                    float(value(model.represented_gross_electricity_before_background_mwh[t]))
                    - _model_value_or_zero(model, "development_controller_electricity_mwh", t)
                    - _model_value_or_zero(model, "electricity_boundary_development_mwh", t), 9
                ) if development_controller_activation == "full_electricity_boundary" else 0.0,
                "linde_split_residual_mwh": round(
                    _model_value_or_zero(model, "linde_total_electricity_mwh", t)
                    - _model_value_or_zero(model, "asu_electricity_mwh", t)
                    - _model_value_or_zero(model, "linde_n2_auxiliary_electricity_mwh", t), 9
                ),
                "exact_site_electricity_proxy_active": 1.0
                if enable_minimal_wag_layer and development_controller_activation != "full_electricity_boundary"
                else 0.0,
                "electricity_mwh": round(float(value(model.gross_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "natural_gas_nm3": 0.0,
                "DRP_named_NG_mwh": 0.0,
                "EAF_named_NG_mwh": 0.0,
                "natural_gas_boiler_mwh": round(float(value(model.ng_to_boiler_mwh[t])), 12)
                if enable_minimal_wag_layer
                else 0.0,
                "BFG_generated_mwh": round(float(value(model.bfg_generated[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "COG_generated_mwh": round(float(value(model.cog_generated[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BOFG_generated_mwh": round(float(value(model.bofg_generated[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BFG_to_BF_hot_stove_mwh": round(float(value(model.bfg_to_bf_hot_stove[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BFG_to_KGF1_mwh": round(float(value(model.bfg_to_kgf1[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "COG_to_KGF1_mwh": round(float(value(model.cog_to_kgf1[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "COG_to_KGF2_mwh": round(float(value(model.cog_to_kgf2[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "COG_to_sinter_mwh": round(float(value(model.cog_to_sinter[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BFG_to_HSM_mwh": round(float(value(model.bfg_to_hsm[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "COG_to_HSM_mwh": round(float(value(model.cog_to_hsm[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BOFG_to_HSM_mwh": round(float(value(model.bofg_to_hsm[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "NG_to_HSM_mwh": round(float(value(model.ng_to_hsm_mwh[t])), 12)
                if enable_minimal_wag_layer
                else "",
                "BOFG_to_PEFA_malerij_mwh": round(float(value(model.bofg_to_pefa_malerij[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "COG_to_PEFA_branderij_mwh": round(float(value(model.cog_to_pefa_branderij[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "NG_to_PEFA_malerij_mwh": round(float(value(model.ng_to_pefa_malerij_mwh[t])), 12)
                if enable_minimal_wag_layer
                else "",
                "NG_to_PEFA_branderij_mwh": round(float(value(model.ng_to_pefa_branderij_mwh[t])), 12)
                if enable_minimal_wag_layer
                else "",
                "BFG_to_boiler_mwh": round(float(value(model.bfg_to_boiler[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "COG_to_boiler_mwh": round(float(value(model.cog_to_boiler[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BOFG_to_boiler_mwh": 0.0 if enable_minimal_wag_layer else "",
                "BFG_to_vattenfall_mwh": round(float(value(model.bfg_to_vattenfall[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "COG_to_vattenfall_mwh": round(float(value(model.cog_to_vattenfall[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BOFG_to_vattenfall_mwh": round(float(value(model.bofg_to_vattenfall[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "NG_to_vattenfall_mwh": round(float(value(model.ng_to_vattenfall_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "aggregate_generator_volume_used_nm3_h": round(
                    float(value(model.aggregate_generator_volume_used_nm3_h[t])), 6
                )
                if enable_minimal_wag_layer
                else "",
                "aggregate_generator_volume_unused_nm3_h": round(
                    float(value(model.aggregate_generator_volume_unused_nm3_h[t])), 6
                )
                if enable_minimal_wag_layer
                else "",
                "aggregate_generator_electrical_capacity_mw": (
                    model.aggregate_generator_electrical_capacity_mw
                    if enable_minimal_wag_layer
                    else ""
                ),
                "BFG_to_flexible_other_site_heat_mwh": round(
                    float(value(model.bfg_to_flexible_other_site_heat[t])), 6
                )
                if enable_minimal_wag_layer
                else "",
                "COG_to_flexible_other_site_heat_mwh": round(
                    float(value(model.cog_to_flexible_other_site_heat[t])), 6
                )
                if enable_minimal_wag_layer
                else "",
                "BOFG_to_flexible_other_site_heat_mwh": round(
                    float(value(model.bofg_to_flexible_other_site_heat[t])), 6
                )
                if enable_minimal_wag_layer
                else "",
                "flexible_other_site_heat_ng_mwh": _costed_c0_ng_reporting_value(
                    float(value(model.flexible_other_site_heat_ng_mwh[t]))
                )
                if enable_minimal_wag_layer
                else "",
                "full_site_fixed_ng_component_mwh": _costed_c0_ng_reporting_value(
                    float(value(model.full_site_fixed_ng_component_mwh[t]))
                )
                if enable_minimal_wag_layer
                else "",
                "full_site_fixed_ng_component_gross_mwh": _costed_c0_ng_reporting_value(
                    float(value(model.full_site_fixed_ng_component_gross_mwh[t]))
                )
                if enable_minimal_wag_layer
                else "",
                "hsm_ng_reclassified_from_fixed_bridge_mwh": _costed_c0_ng_reporting_value(
                    float(value(model.hsm_ng_reclassified_from_fixed_bridge_mwh[t]))
                )
                if enable_minimal_wag_layer
                else "",
                "full_site_energy_bridge_named_ng_mwh": _costed_c0_ng_reporting_value(
                    float(value(model.full_site_energy_bridge_named_ng_mwh[t]))
                )
                if enable_minimal_wag_layer
                else "",
                "site_baseload_ng_mwh": _costed_c0_ng_reporting_value(
                    float(value(model.site_baseload_ng_mwh[t]))
                )
                if enable_minimal_wag_layer
                else "",
                "total_named_ng_procurement_mwh": _costed_c0_ng_reporting_value(
                    float(value(model.total_named_ng_procurement_mwh[t]))
                )
                if enable_minimal_wag_layer
                else "",
                "flexible_other_site_heat_service_envelope_mwh": round(
                    float(value(model.flexible_other_site_heat_service_envelope_mwh[t])), 6
                )
                if enable_minimal_wag_layer
                else "",
                "normal_case_flexible_ng_validation_reference_mwh": round(
                    float(
                        value(
                            model.normal_case_flexible_ng_validation_reference_mwh[t]
                        )
                    ),
                    6,
                )
                if enable_minimal_wag_layer
                else "",
                "vattenfall_fuel_mwh": round(float(value(model.vattenfall_fuel_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "generator_named_ng_mwh": _costed_c0_ng_reporting_value(
                    float(value(model.generator_named_ng_mwh[t]))
                )
                if enable_minimal_wag_layer
                else "",
                "generator_total_fuel_mwh": round(float(value(model.generator_total_fuel_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "generator_electricity_mwh": round(float(value(model.generator_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "WAG_generator_electricity_mwh": round(float(value(model.wag_generator_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "WAG_generator_electricity_mwh_unrounded": float(
                    value(model.wag_generator_electricity_mwh[t])
                )
                if enable_minimal_wag_layer
                else "",
                "NG_generator_electricity_mwh": round(float(value(model.ng_generator_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "NG_generator_electricity_mwh_unrounded": float(
                    value(model.ng_generator_electricity_mwh[t])
                )
                if enable_minimal_wag_layer
                else "",
                "total_generator_electricity_mwh": round(float(value(model.total_generator_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "total_generator_electricity_mwh_unrounded": float(
                    value(model.total_generator_electricity_mwh[t])
                )
                if enable_minimal_wag_layer
                else "",
                "generator_unit_interface_active": 0.0,
                "aggregate_generator_technical_interface_active": 1.0
                if enable_minimal_wag_layer
                and model.aggregate_generator_technical_interface_active
                else 0.0,
                "wag_electricity_mwh": round(float(value(model.wag_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "represented_gross_electricity_before_background_mwh": round(float(value(model.represented_gross_electricity_before_background_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "site_background_electricity_mwh": round(float(value(model.site_background_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "gross_total_electricity_mwh": round(float(value(model.gross_total_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "gross_electricity_mwh": round(float(value(model.gross_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "gross_grid_import_mwh": round(float(value(model.gross_grid_import_mwh[t])), 12)
                if enable_minimal_wag_layer
                else "",
                "gross_grid_export_mwh": round(float(value(model.gross_grid_export_mwh[t])), 12)
                if enable_minimal_wag_layer
                else "",
                "gross_grid_import_upper_bound_mwh": (
                    import_bound_by_hour[int(t)][
                        "gross_grid_import_upper_bound_mwh"
                    ]
                    if int(t) in import_bound_by_hour
                    else ""
                ),
                "gross_grid_import_bound_status": (
                    import_bound_by_hour[int(t)]["status"]
                    if int(t) in import_bound_by_hour
                    else "not_applicable"
                ),
                "gross_grid_import_bound_method": (
                    model.grid_import_bound_audit["derivation_method"]
                    if int(t) in import_bound_by_hour
                    else ""
                ),
                "electricity_sale_price_eur_per_mwh": (
                    float(
                        electricity_sale_sensitivity["sale_price_eur_by_hour"][int(t)]
                    )
                    if electricity_sale_sensitivity
                    and electricity_sale_sensitivity.get("enabled") is True
                    else ""
                ),
                "electricity_export_revenue_eur": (
                    round(
                        float(
                            electricity_sale_sensitivity[
                                "sale_price_eur_by_hour"
                            ][int(t)]
                        )
                        * float(value(model.gross_grid_export_mwh[t])),
                        9,
                    )
                    if electricity_sale_sensitivity
                    and electricity_sale_sensitivity.get("enabled") is True
                    else 0.0
                ),
                "net_grid_exchange_mwh": round(float(value(model.net_grid_exchange_mwh[t])), 12)
                if enable_minimal_wag_layer
                else "",
                "gross_site_electricity_identity_residual_mwh": round(float(value(model.gross_site_electricity_identity_residual_mwh[t])), 12)
                if enable_minimal_wag_layer
                else "",
                "net_grid_import_mwh": round(float(value(model.net_grid_import_mwh[t])), 12)
                if enable_minimal_wag_layer
                else "",
                "BFG_flared_mwh": round(float(value(model.bfg_flared[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "COG_flared_mwh": round(float(value(model.cog_flared[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BOFG_flared_mwh": round(float(value(model.bofg_flared[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "WAG_generated": round(float(value(model.wag_generated[t])), 6),
                "WAG_used": round(float(value(model.wag_used[t])), 6) if enable_minimal_wag_layer else 0.0,
                "WAG_flared": round(float(value(model.wag_flared[t])), 6)
                if enable_minimal_wag_layer
                else round(float(value(model.wag_generated[t])), 6),
                "steam": round(float(value(model.steam_production_mwh[t])), 6) if enable_minimal_wag_layer else "",
                "steam_15bar_demand_t": round(float(value(model.steam_15bar_demand_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "steam_15bar_explicit_demand_t": round(float(value(model.steam_15bar_explicit_demand_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "residual_steam_15bar_demand_t": round(float(value(model.residual_steam_15bar_demand_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "steam_15bar_supply_t": round(float(value(model.steam_15bar_supply_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "steam_15bar_unserved_t": round(float(value(model.steam_15bar_unserved_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "WAG_boiler_steam_supply_t": round(float(value(model.wag_boiler_steam_supply_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "NG_boiler_steam_supply_t": round(float(value(model.ng_boiler_steam_supply_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "recovered_steam_supply_t": round(float(value(model.recovered_steam_supply_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "external_steam_supply_t": round(float(value(model.external_steam_supply_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "steam_15bar_spill_t": round(float(value(model.steam_15bar_spill_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BFG_balance_residual_mwh": round(float(value(model.bfg_balance_residual[t])), 9)
                if enable_minimal_wag_layer
                else "",
                "COG_balance_residual_mwh": round(float(value(model.cog_balance_residual[t])), 9)
                if enable_minimal_wag_layer
                else "",
                "BOFG_balance_residual_mwh": round(float(value(model.bofg_balance_residual[t])), 9)
                if enable_minimal_wag_layer
                else "",
                "BFG_flare_co2_t": round(float(value(model.bfg_flare_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "COG_flare_co2_t": round(float(value(model.cog_flare_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BOFG_flare_co2_t": round(float(value(model.bofg_flare_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "flaring_co2_t": round(float(value(model.flaring_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BFG_explicit_combustion_co2_t": round(float(value(model.bfg_explicit_combustion_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "COG_explicit_combustion_co2_t": round(float(value(model.cog_explicit_combustion_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "BOFG_explicit_combustion_co2_t": round(float(value(model.bofg_explicit_combustion_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "WAG_explicit_combustion_co2_t": round(float(value(model.wag_explicit_combustion_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "explicit_NG_combustion_co2_t": round(float(value(model.explicit_ng_combustion_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "residual_unmodelled_direct_co2_t": round(float(value(model.residual_unmodelled_direct_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "total_direct_co2_reporting_t": round(float(value(model.total_direct_co2_reporting_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "flaring_co2_diagnostic_cost_eur": round(float(value(model.flaring_co2_diagnostic_cost_eur[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "oxygen_t": "",
                "total_static_cost": 0.0,
                "caveat": "C0 static BF-BOF physical regression; controlled development assumptions only.",
            }
        )
    if normal_solution_capture is not None:
        audit.update(
            {
                key: cost_metadata[key]
                for key in (
                    "normal_solution_capture_path",
                    "normal_solution_capture_sha256",
                    "normal_solution_variable_count",
                    "normal_solution_variable_name_sha256",
                    "normal_solution_variable_schema_sha256",
                    "normal_solution_variable_fixed_schema_sha256",
                )
            }
        )
    return audit, constraint_rows, hourly_rows


def _solve_c1_configuration(
    tables: UnifiedInputTables,
    *,
    horizon_hours_override: int | None = None,
    target_multiplier: float = 1.0,
    enable_minimal_wag_layer: bool = False,
    enable_c1_retained_bf_bof_route: bool = False,
    enable_internal_wag_power: bool = False,
    development_controller_activation: str = "none",
    hsm_rolling_electricity_mwh_per_t_hrc_override: float | None = None,
    development_controller_profile_weights: Mapping[str, Mapping[int, float]] | None = None,
    daily_production_guardrail: bool = False,
    rolling_production_deadline_targets_t: Mapping[int, float] | None = None,
    rolling_production_progress_target_t: float | None = None,
    rolling_production_progress_lower_bound_t: float | None = None,
    rolling_production_progress_upper_bound_t: float | None = None,
    rolling_production_execution_block_hours: int = 24,
    rolling_production_hard_exact_execution_target: bool = False,
    rolling_production_exact_deadline_hour: int | None = None,
    rolling_production_exact_deadline_target_t: float | None = None,
    initial_inventory_overrides: Mapping[str, float] | None = None,
    rolling_terminal_inventory_hour: int | None = None,
    rolling_terminal_inventory_bounds_t: Mapping[str, Mapping[str, float]] | None = None,
    fix_c1_hybrid_schedule: bool = False,
    c1_retained_route_policy: str = "target_share",
    commitment_granularity: str = "hourly_binary",
    commitment_day_lengths: Collection[int] | None = None,
    solver_time_limit_seconds: float | None = None,
    eaf_material_balance: Mapping[str, float] | None = None,
    bof_material_balance: Mapping[str, float] | None = None,
    scrap_supply_ledger: Mapping[str, Any] | None = None,
    downstream_origin_routing: Mapping[str, float] | None = None,
    c1_liquid_steel_route_band: Mapping[str, float] | None = None,
    continuous_must_run_activities: Collection[str] | None = None,
    c1_coke_chain_reconciliation: Mapping[str, float] | None = None,
    generator_interface_cap_mode: str = "inherited_profile",
    generator_unit_interface: Mapping[str, Any] | None = None,
    c1_energy_boundary: Mapping[str, float] | None = None,
    hsm_source_mix_policy: Mapping[str, Any] | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    site_baseload_ng_mwh_h: float = 0.0,
    site_residual_steam_t_h: float = 0.0,
    site_residual_direct_co2_t_h: float = 0.0,
    eaf_secondary_electricity_mwh_per_t_ls_override: float | None = None,
    dsp_electricity_mwh_per_t_coil_override: float | None = None,
    external_procurement_flow_coefficients: Mapping[str, float] | None = None,
    deterministic_cost_policy: Mapping[str, Any] | None = None,
    wag_generation_yield_overrides: Mapping[str, float] | None = None,
    bf_electricity_intensity_scale: float = 1.0,
    normal_solution_capture: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    inputs = _build_c1_inputs(
        tables,
        horizon_hours_override=horizon_hours_override,
        target_multiplier=target_multiplier,
        include_retained_bf_bof=enable_c1_retained_bf_bof_route,
    )
    if inputs.retained_bf_bof is not None:
        inputs = replace(
            inputs,
            retained_bf_bof=_apply_wag_generation_yield_overrides(
                inputs.retained_bf_bof, wag_generation_yield_overrides
            ),
        )
    inputs = _apply_c1_initial_inventory_overrides(inputs, initial_inventory_overrides)
    build_start = time.perf_counter()
    model = _build_c1_model(
        inputs,
        enable_minimal_wag_layer=enable_minimal_wag_layer,
        enable_c1_retained_bf_bof_route=enable_c1_retained_bf_bof_route,
        enable_internal_wag_power=enable_internal_wag_power,
        development_controller_activation=development_controller_activation,
        hsm_rolling_electricity_mwh_per_t_hrc_override=hsm_rolling_electricity_mwh_per_t_hrc_override,
        development_controller_profile_weights=development_controller_profile_weights,
        daily_production_guardrail=daily_production_guardrail,
        rolling_production_deadline_targets_t=rolling_production_deadline_targets_t,
        fix_c1_hybrid_schedule=fix_c1_hybrid_schedule,
        c1_retained_route_policy=c1_retained_route_policy,
        commitment_granularity=commitment_granularity,
        commitment_day_lengths=commitment_day_lengths,
        eaf_material_balance=eaf_material_balance,
        bof_material_balance=bof_material_balance,
        scrap_supply_ledger=scrap_supply_ledger,
        downstream_origin_routing=downstream_origin_routing,
        c1_liquid_steel_route_band=c1_liquid_steel_route_band,
        continuous_must_run_activities=continuous_must_run_activities,
        c1_coke_chain_reconciliation=c1_coke_chain_reconciliation,
        generator_interface_cap_mode=generator_interface_cap_mode,
        generator_unit_interface=generator_unit_interface,
        c1_energy_boundary=c1_energy_boundary,
        hsm_source_mix_policy=hsm_source_mix_policy,
        linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
        site_background_electricity_mwh_h=site_background_electricity_mwh_h,
        site_baseload_ng_mwh_h=site_baseload_ng_mwh_h,
        site_residual_steam_t_h=site_residual_steam_t_h,
        site_residual_direct_co2_t_h=site_residual_direct_co2_t_h,
        eaf_secondary_electricity_mwh_per_t_ls_override=eaf_secondary_electricity_mwh_per_t_ls_override,
        dsp_electricity_mwh_per_t_coil_override=dsp_electricity_mwh_per_t_coil_override,
        external_procurement_flow_coefficients=external_procurement_flow_coefficients,
        bf_electricity_intensity_scale=bf_electricity_intensity_scale,
    )
    if rolling_production_progress_target_t is not None:
        _add_rolling_production_progress_tracking(
            model,
            execution_block_hours=rolling_production_execution_block_hours,
            next_execution_target_t=rolling_production_progress_target_t,
            hard_exact_execution_target=rolling_production_hard_exact_execution_target,
            exact_deadline_hour=rolling_production_exact_deadline_hour,
            exact_deadline_target_t=rolling_production_exact_deadline_target_t,
            execution_lower_bound_t=rolling_production_progress_lower_bound_t,
            execution_upper_bound_t=rolling_production_progress_upper_bound_t,
        )
    _add_rolling_terminal_inventory_band(
        model,
        terminal_hour=rolling_terminal_inventory_hour,
        bounds_t=rolling_terminal_inventory_bounds_t,
    )
    build_runtime = time.perf_counter() - build_start
    solver_name, solver = _select_solver()
    if solver is None:
        raise S44CModelBuilderError("No LP/MIP solver available for S4.4c C1 physical regression.")
    _apply_solver_time_limit(solver_name, solver, solver_time_limit_seconds)
    start = time.perf_counter()
    minimize_imported_slab = bool(
        downstream_origin_routing is not None
        and downstream_origin_routing.get("minimize_imported_slab", False)
    )
    minimum_imported_slab_t: float | str = "not_requested"
    import_minimization_termination: str = "not_requested"
    if minimize_imported_slab:
        if rolling_production_progress_target_t is not None:
            raise S44CModelBuilderError(
                "Imported-slab minimisation and rolling production-progress tracking "
                "need an explicit lexicographic policy before they can be combined."
            )
        model.static_price_naive_objective.deactivate()
        model.imported_slab_minimization_objective = Objective(
            expr=sum(model.imported_slab_to_hsm[t] for t in model.TIME),
            sense=minimize,
        )
    try:
        if minimize_imported_slab and deterministic_cost_policy is not None:
            raise S44CModelBuilderError(
                "Imported-slab minimisation must be disabled in deterministic cost mode."
            )
        result, cost_metadata = _solve_with_optional_lexicographic_cost(
            model,
            solver=solver,
            configuration_id="C1_phase1_BF_BOF_plus_DRP_EAF",
            deterministic_cost_policy=deterministic_cost_policy,
            normal_solution_capture=normal_solution_capture,
        )
        if minimize_imported_slab:
            import_minimization_termination = str(result.solver.termination_condition)
            if import_minimization_termination.lower() in {"optimal", "feasible"}:
                minimum_imported_slab_t = sum(
                    float(value(model.imported_slab_to_hsm[t])) for t in model.TIME
                )
                model.imported_slab_minimization_objective.deactivate()
                model.minimum_imported_slab_preservation = Constraint(
                    expr=sum(model.imported_slab_to_hsm[t] for t in model.TIME)
                    <= float(minimum_imported_slab_t) + TOLERANCE
                )
                model.static_price_naive_objective.activate()
                result = solver.solve(model)
                cost_metadata = {
                    "cost_objective_active": False,
                    "primary_cost_objective_eur": None,
                    "primary_cost_best_bound_eur": None,
                    "primary_cost_mip_gap": None,
                    "primary_cost_runtime_seconds": 0.0,
                    "tie_break_objective_value": float(
                        value(model.static_price_naive_objective)
                    ),
                    "tie_break_cost_objective_eur": None,
                    "tie_break_runtime_seconds": 0.0,
                    "priced_flow_count": 0,
                }
    except RuntimeError as exc:
        runtime = time.perf_counter() - start
        stats = collect_model_stats(model)
        return {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "build_status": "solver_stopped_without_accepted_solution",
            "active_assets_count": len([row for row in tables.tables["configuration_assets.csv"] if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF" and _is_active(row)]),
            "active_processes_count": 7 if enable_c1_retained_bf_bof_route else 2,
            "active_buffers_count": 5 if enable_c1_retained_bf_bof_route else 1,
            "active_materials_count": 9 if enable_c1_retained_bf_bof_route else 4,
            "active_energy_carriers_count": 8 if enable_minimal_wag_layer else 3,
            "executable_cost_terms_count": 0, "blocker_count": 0, "warning_count": 1,
            "solver_name": solver_name, "solver_status": "exception_no_solution_loaded",
            "termination_condition": "infeasible_or_no_accepted_solution",
            "objective_value": "not_available", "build_runtime_seconds": round(build_runtime, 6),
            "runtime_seconds": round(runtime, 6), "solver_time_limit_seconds": solver_time_limit_seconds or "",
            "mip_gap": "not_available", "variable_count": stats.variables, "binary_count": stats.binaries,
            "constraint_count": stats.constraints, "final_product_target_t": round(inputs.final_product_target_t, 6),
            "final_product_fulfilled_t": "not_solved", "final_product_residual_t": "not_solved",
            "import_minimization_active": str(minimize_imported_slab).lower(),
            "import_minimization_termination": import_minimization_termination,
            "minimum_imported_slab_t": minimum_imported_slab_t,
            "caveat": f"C1 solver returned no accepted solution: {exc}",
        }, [], []
    runtime = time.perf_counter() - start
    solver_status = str(result.solver.status)
    termination_condition = str(result.solver.termination_condition)
    stats = collect_model_stats(model)
    if termination_condition.lower() not in {"optimal", "feasible"}:
        audit = {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "build_status": "solver_stopped_without_accepted_solution",
            "active_assets_count": len([row for row in tables.tables["configuration_assets.csv"] if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF" and _is_active(row)]),
            "active_processes_count": 7 if enable_c1_retained_bf_bof_route else 2,
            "active_buffers_count": 5 if enable_c1_retained_bf_bof_route else 1,
            "active_materials_count": 9 if enable_c1_retained_bf_bof_route else 4,
            "active_energy_carriers_count": 8 if enable_minimal_wag_layer else 3,
            "executable_cost_terms_count": 0,
            "blocker_count": 0,
            "warning_count": 1,
            "solver_name": solver_name,
            "solver_status": solver_status,
            "termination_condition": termination_condition,
            "objective_value": "not_available",
            "build_runtime_seconds": round(build_runtime, 6),
            "runtime_seconds": round(runtime, 6),
            "solver_time_limit_seconds": solver_time_limit_seconds or "",
            "mip_gap": _mip_gap(result),
            "variable_count": stats.variables,
            "binary_count": stats.binaries,
            "constraint_count": stats.constraints,
            "final_product_target_t": round(inputs.final_product_target_t, 6),
            "final_product_fulfilled_t": "not_solved",
            "final_product_residual_t": "not_solved",
            "import_minimization_active": str(minimize_imported_slab).lower(),
            "import_minimization_termination": import_minimization_termination,
            "minimum_imported_slab_t": minimum_imported_slab_t,
            "caveat": "C1 solve stopped before an accepted feasible/optimal solution; no dispatch or anchor result is reported.",
        }
        return audit, [], []
    objective_value = (
        float(cost_metadata["primary_cost_objective_eur"])
        if cost_metadata["cost_objective_active"]
        else float(value(model.static_price_naive_objective))
    )
    final_product_fulfilled = sum(float(value(model.final_product_output[t])) for t in model.TIME)
    final_product_residual = final_product_fulfilled - inputs.final_product_target_t
    terminal_residual = float(value(model.dri_inventory[inputs.horizon_hours - 1])) - inputs.dri_buffer_initial_t
    inventories = [float(value(model.dri_inventory[t])) for t in model.TIME]
    drp_values = [float(value(model.drp_pellet_input[t])) for t in model.TIME]
    eaf_values = [float(value(model.eaf_dri_input[t])) for t in model.TIME]
    eaf_on = [float(value(model.eaf_on[t])) for t in model.TIME]
    hybrid_route_active = enable_c1_retained_bf_bof_route
    retained_final = (
        [float(value(model.retained_bf_bof_final_product_output[t])) for t in model.TIME]
        if hybrid_route_active
        else [0.0 for _ in model.TIME]
    )
    eaf_final = (
        [float(value(model.eaf_final_product_output[t])) for t in model.TIME]
        if hybrid_route_active
        else [float(value(model.final_product_output[t])) for t in model.TIME]
    )
    retained_coking = (
        [float(value(model.coking_plant_1[t])) for t in model.TIME]
        if hybrid_route_active
        else [0.0 for _ in model.TIME]
    )
    retained_bf6 = (
        [float(value(model.blast_furnace_6[t])) for t in model.TIME]
        if hybrid_route_active
        else [0.0 for _ in model.TIME]
    )
    retained_bof = (
        [float(value(model.basic_oxygen_furnace[t])) for t in model.TIME]
        if hybrid_route_active
        else [0.0 for _ in model.TIME]
    )
    retained_hsm = (
        [float(value(model.hot_strip_mill[t])) for t in model.TIME]
        if hybrid_route_active
        else [0.0 for _ in model.TIME]
    )
    retained_sinter = (
        [float(value(model.sintering_plant[t])) for t in model.TIME]
        if hybrid_route_active
        else [0.0 for _ in model.TIME]
    )
    coke_inventory = (
        [float(value(model.coke_inventory[t])) for t in model.TIME]
        if hybrid_route_active
        else []
    )
    sinter_inventory = (
        [float(value(model.sinter_inventory[t])) for t in model.TIME]
        if hybrid_route_active
        else []
    )
    hot_iron_inventory = (
        [float(value(model.hot_iron_inventory[t])) for t in model.TIME]
        if hybrid_route_active
        else []
    )
    cold_slab_inventory = (
        [float(value(model.cold_slab_inventory[t])) for t in model.TIME]
        if hybrid_route_active
        else []
    )

    audit = {
        "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
        "build_status": "solved",
        "active_assets_count": len(
            [
                row
                for row in tables.tables["configuration_assets.csv"]
                if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF" and _is_active(row)
            ]
        ),
        "active_processes_count": 7 if hybrid_route_active else 2,
        "active_buffers_count": 5 if hybrid_route_active else 1,
        "active_materials_count": 9 if hybrid_route_active else 4,
        "active_energy_carriers_count": 8 if enable_minimal_wag_layer else 3,
        "executable_cost_terms_count": cost_metadata["priced_flow_count"],
        "blocker_count": len(
            [
                row
                for rows in tables.tables.values()
                for row in rows
                if row.get("configuration_id") == "C1_phase1_BF_BOF_plus_DRP_EAF"
                and row.get("input_status") == "missing_blocker"
            ]
        ),
        "warning_count": 1,
        "solver_name": solver_name,
        "solver_status": solver_status,
        "termination_condition": termination_condition,
        "objective_value": round(objective_value, 6),
        "objective_type": (
            "represented_external_procurement_cost_eur"
            if cost_metadata["cost_objective_active"]
            else "physical_tie_breaker"
        ),
        "primary_cost_objective_eur": (
            round(float(cost_metadata["primary_cost_objective_eur"]), 6)
            if cost_metadata["primary_cost_objective_eur"] is not None
            else ""
        ),
        "primary_cost_best_bound_eur": (
            round(float(cost_metadata["primary_cost_best_bound_eur"]), 6)
            if cost_metadata["primary_cost_best_bound_eur"] is not None
            else ""
        ),
        "primary_cost_best_bound_availability": cost_metadata[
            "primary_cost_best_bound_availability"
        ],
        "primary_cost_solver_status": cost_metadata["primary_cost_solver_status"],
        "primary_cost_termination_condition": cost_metadata[
            "primary_cost_termination_condition"
        ],
        "primary_cost_mip_gap": cost_metadata["primary_cost_mip_gap"],
        "primary_cost_runtime_seconds": round(
            float(cost_metadata["primary_cost_runtime_seconds"]), 6
        ),
        "production_progress_objective_active": cost_metadata[
            "production_progress_objective_active"
        ],
        "production_progress_target_t": (
            round(float(cost_metadata["production_progress_target_t"]), 6)
            if cost_metadata["production_progress_target_t"] is not None
            else ""
        ),
        "production_progress_optimum_deviation_t": (
            round(
                float(cost_metadata["production_progress_optimum_deviation_t"]),
                9,
            )
            if cost_metadata["production_progress_optimum_deviation_t"]
            is not None
            else ""
        ),
        "production_progress_actual_t": (
            round(float(cost_metadata["production_progress_actual_t"]), 6)
            if cost_metadata["production_progress_actual_t"] is not None
            else ""
        ),
        "production_progress_surplus_t": (
            round(float(cost_metadata["production_progress_surplus_t"]), 9)
            if cost_metadata["production_progress_surplus_t"] is not None
            else ""
        ),
        "production_progress_deficit_t": (
            round(float(cost_metadata["production_progress_deficit_t"]), 9)
            if cost_metadata["production_progress_deficit_t"] is not None
            else ""
        ),
        "production_progress_runtime_seconds": round(
            float(cost_metadata["production_progress_runtime_seconds"]), 6
        ),
        "tie_break_objective_value": cost_metadata["tie_break_objective_value"],
        "tie_break_cost_objective_eur": (
            round(float(cost_metadata["tie_break_cost_objective_eur"]), 6)
            if cost_metadata["tie_break_cost_objective_eur"] is not None
            else ""
        ),
        "tie_break_runtime_seconds": round(
            float(cost_metadata["tie_break_runtime_seconds"]), 6
        ),
        "priced_flow_count": cost_metadata["priced_flow_count"],
        "build_runtime_seconds": round(build_runtime, 6),
        "runtime_seconds": round(runtime, 6),
        "solver_time_limit_seconds": solver_time_limit_seconds or "",
        "mip_gap": _mip_gap(result),
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "final_product_target_t": round(inputs.final_product_target_t, 6),
        "final_product_fulfilled_t": round(final_product_fulfilled, 6),
        "final_product_residual_t": round(final_product_residual, 9),
        "dri_terminal_residual_t": round(terminal_residual, 9),
        "dri_buffer_min_t": round(min(inventories), 6),
        "dri_buffer_max_t": round(max(inventories), 6),
        "eaf_on_hours": round(sum(eaf_on), 6),
        "drp_pellet_input_total_t": round(sum(drp_values), 6),
        "eaf_dri_input_total_t": round(sum(eaf_values), 6),
        "retained_bf_bof_final_product_t": round(sum(retained_final), 6),
        "eaf_final_product_t": round(sum(eaf_final), 6),
        "bof_liquid_steel_t": round(float(value(model.bof_liquid_steel_total)), 6)
        if hybrid_route_active
        else 0.0,
        "eaf_liquid_steel_t": round(float(value(model.eaf_liquid_steel_total)), 6)
        if hybrid_route_active
        else round(sum(eaf_final), 6),
        "endogenous_liquid_steel_t": round(float(value(model.endogenous_liquid_steel_total)), 6)
        if hybrid_route_active
        else round(sum(eaf_final), 6),
        "downstream_origin_routing_active": downstream_origin_routing is not None,
        "BOF_to_HSM_slab_t": round(sum(float(value(model.bof_to_hsm_slab[t])) for t in model.TIME), 6)
        if hybrid_route_active
        else 0.0,
        "BOF_to_DSP_liquid_steel_t": round(sum(float(value(model.bof_to_dsp_liquid_steel[t])) for t in model.TIME), 6)
        if hybrid_route_active
        else 0.0,
        "EAF_to_HSM_slab_t": round(sum(float(value(model.eaf_to_hsm_slab[t])) for t in model.TIME), 6)
        if hybrid_route_active
        else 0.0,
        "EAF_to_DSP_liquid_steel_t": round(sum(float(value(model.eaf_to_dsp_liquid_steel[t])) for t in model.TIME), 6)
        if hybrid_route_active
        else 0.0,
        "imported_slab_to_HSM_t": round(sum(float(value(model.imported_slab_to_hsm[t])) for t in model.TIME), 6)
        if hybrid_route_active
        else 0.0,
        "imported_slab_horizon_cap_t": round(
            float(
                downstream_origin_routing.get(
                    "imported_slab_horizon_cap_t",
                    float(downstream_origin_routing["imported_slab_max_t_h"]) * inputs.horizon_hours,
                )
            ),
            6,
        )
        if downstream_origin_routing is not None
        else 0.0,
        "import_minimization_active": str(minimize_imported_slab).lower(),
        "import_minimization_termination": import_minimization_termination,
        "minimum_imported_slab_t": round(float(minimum_imported_slab_t), 6)
        if minimum_imported_slab_t != "not_requested"
        else "not_requested",
        "DSP_final_product_t": round(sum(float(value(model.dsp_final_product_output[t])) for t in model.TIME), 6)
        if hybrid_route_active
        else 0.0,
        "retained_bf_bof_target_share": round(inputs.retained_bf_bof.retained_target_share, 9)
        if hybrid_route_active and inputs.retained_bf_bof is not None
        else "",
        "retained_route_policy": c1_retained_route_policy if hybrid_route_active else "",
        "liquid_steel_route_band_active": str(c1_liquid_steel_route_band is not None).lower(),
        "continuous_must_run_activities": ";".join(sorted(continuous_must_run_activities or ())),
        "coke_chain_reconciliation_active": str(c1_coke_chain_reconciliation is not None).lower(),
        "kgf_underfiring_activity_basis": (
            "coke_output_t" if c1_coke_chain_reconciliation is not None else "coking_input_t"
        ),
        "retained_coking_input_total_t": round(sum(retained_coking), 6),
        "retained_sintering_input_total_t": round(sum(retained_sinter), 6),
        "retained_sinter_activity_basis": "iron_ore_feed_t" if hybrid_route_active else "",
        "retained_sinter_output_per_t_iron_ore": inputs.retained_bf_bof.sinter_output_per_t_iron_ore
        if hybrid_route_active and inputs.retained_bf_bof is not None
        else "",
        "retained_sinter_output_total_t": round(
            sum(float(value(model.sinter_output[t])) for t in model.TIME), 6
        )
        if hybrid_route_active
        else 0.0,
        "retained_bf6_sinter_input_total_t": round(sum(retained_bf6), 6),
        "retained_bof_hot_iron_input_total_t": round(sum(retained_bof), 6),
        "retained_hsm_input_total_t": round(sum(retained_hsm), 6),
        "bf7_activity_total_t": 0.0,
        "kgf2_activity_total_t": 0.0,
        "electricity_mwh": round(sum(float(value(model.gross_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else round(sum(float(value(model.electricity_mwh[t])) for t in model.TIME), 6),
        "natural_gas_nm3": round(sum(float(value(model.natural_gas_nm3[t])) for t in model.TIME), 6),
        "DRP_NG_mwh": round(sum(_model_value_or_zero(model, "drp_named_ng_mwh", t) for t in model.TIME), 6),
        "DRP_reduction_NG_mwh": round(
            sum(_model_value_or_zero(model, "drp_reduction_ng_mwh", t) for t in model.TIME), 6
        ),
        "DRP_furnace_NG_mwh": round(
            sum(_model_value_or_zero(model, "drp_furnace_ng_mwh", t) for t in model.TIME), 6
        ),
        "DRP_HERACLES_NG_split_max_abs_residual_mwh": round(
            max(
                abs(_model_value_or_zero(model, "drp_heracless_ng_split_residual_mwh", t))
                for t in model.TIME
            ),
            9,
        ),
        "EAF_NG_mwh": round(sum(_model_value_or_zero(model, "eaf_named_ng_mwh", t) for t in model.TIME), 6),
        "site_baseload_ng_mwh": round(
            sum(float(value(model.site_baseload_ng_mwh[t])) for t in model.TIME), 6
        )
        if enable_minimal_wag_layer
        else 0.0,
        "total_named_ng_procurement_mwh": round(
            sum(float(value(model.total_named_ng_procurement_mwh[t])) for t in model.TIME), 6
        )
        if enable_minimal_wag_layer
        else 0.0,
        "natural_gas_boiler_mwh": round(sum(float(value(model.ng_to_boiler_mwh[t])) for t in model.TIME), 6),
        "steam_15bar_explicit_demand_t": round(sum(float(value(model.steam_15bar_explicit_demand_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "residual_steam_15bar_demand_t": round(sum(float(value(model.residual_steam_15bar_demand_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "steam_15bar_total_demand_t": round(sum(float(value(model.steam_15bar_demand_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "steam_15bar_unserved_t": round(sum(float(value(model.steam_15bar_unserved_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "steam_mwh": round(sum(float(value(model.steam_production_mwh[t])) for t in model.TIME), 6),
        "oxygen_t": round(sum(float(value(model.oxygen_t[t])) for t in model.TIME), 6),
        "scrap_t": round(sum(float(value(model.scrap_t[t])) for t in model.TIME), 6),
        "bof_scrap_t": round(sum(float(value(model.bof_scrap_supply_t[t])) for t in model.TIME), 6)
        if hybrid_route_active
        else 0.0,
        "site_total_scrap_t": round(float(value(model.site_scrap_supply_total_t)), 6)
        if hybrid_route_active
        else round(sum(float(value(model.scrap_t[t])) for t in model.TIME), 6),
        "named_bof_eaf_metallics_active": str(
            eaf_material_balance is not None
            and bof_material_balance is not None
            and scrap_supply_ledger is not None
        ).lower(),
        "WAG_generated": round(sum(float(value(model.wag_generated[t])) for t in model.TIME), 6),
        "WAG_used": round(sum(float(value(model.wag_used[t])) for t in model.TIME), 6),
        "WAG_flared": round(sum(float(value(model.wag_flared[t])) for t in model.TIME), 6),
        "WAG_explicit_combustion_co2_t": round(sum(float(value(model.wag_explicit_combustion_co2_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "explicit_NG_combustion_co2_t": round(sum(float(value(model.explicit_ng_combustion_co2_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "residual_unmodelled_direct_co2_t": round(sum(float(value(model.residual_unmodelled_direct_co2_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "total_direct_co2_reporting_t": round(sum(float(value(model.total_direct_co2_reporting_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "BFG_generated_mwh": round(sum(float(value(model.bfg_generated[t])) for t in model.TIME), 6),
        "development_controller_activation": development_controller_activation,
        "HSM_reheat_demand_mwh": round(sum(float(value(model.hsm_reheat_demand_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "HSM_NG_mwh": round(sum(float(value(model.ng_to_hsm_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "PEFA_NG_mwh": round(
            sum(float(value(model.ng_to_pefa_malerij_mwh[t] + model.ng_to_pefa_branderij_mwh[t])) for t in model.TIME),
            6,
        )
        if enable_minimal_wag_layer
        else 0.0,
        "development_controller_electricity_mwh": round(
            sum(float(value(model.development_controller_electricity_mwh[t])) for t in model.TIME), 6
        )
        if enable_minimal_wag_layer
        else 0.0,
        "COG_generated_mwh": round(sum(float(value(model.cog_generated[t])) for t in model.TIME), 6),
        "BOFG_generated_mwh": round(sum(float(value(model.bofg_generated[t])) for t in model.TIME), 6),
        "BFG_used_mwh": round(
            sum(float(value(model.bfg_to_bf_hot_stove[t] + model.bfg_to_kgf1[t] + model.bfg_to_hsm[t] + model.bfg_to_boiler[t] + model.bfg_to_vattenfall[t])) for t in model.TIME),
            6,
        )
        if enable_minimal_wag_layer
        else 0.0,
        "COG_used_mwh": round(
            sum(
                float(
                    value(
                        model.cog_to_kgf1[t]
                        + model.cog_to_kgf2[t]
                        + model.cog_to_sinter[t]
                        + model.cog_to_hsm[t]
                        + model.cog_to_pefa_branderij[t]
                        + model.cog_to_boiler[t]
                        + model.cog_to_vattenfall[t]
                    )
                )
                for t in model.TIME
            ),
            6,
        )
        if enable_minimal_wag_layer
        else 0.0,
        "BOFG_used_mwh": round(sum(float(value(model.bofg_to_hsm[t] + model.bofg_to_pefa_malerij[t] + model.bofg_to_vattenfall[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "BFG_to_vattenfall_mwh": round(sum(float(value(model.bfg_to_vattenfall[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "COG_to_vattenfall_mwh": round(sum(float(value(model.cog_to_vattenfall[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "BOFG_to_vattenfall_mwh": round(sum(float(value(model.bofg_to_vattenfall[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "vattenfall_fuel_mwh": round(sum(float(value(model.vattenfall_fuel_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "WAG_generator_electricity_mwh": round(sum(float(value(model.wag_generator_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "NG_generator_electricity_mwh": round(sum(float(value(model.ng_generator_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "total_generator_electricity_mwh": round(sum(float(value(model.total_generator_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "wag_electricity_mwh": round(sum(float(value(model.wag_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "represented_gross_electricity_before_background_mwh": round(sum(float(value(model.represented_gross_electricity_before_background_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else round(sum(float(value(model.electricity_mwh[t])) for t in model.TIME), 6),
        "site_background_electricity_mwh": round(sum(float(value(model.site_background_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "gross_total_electricity_mwh": round(sum(float(value(model.gross_total_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else round(sum(float(value(model.electricity_mwh[t])) for t in model.TIME), 6),
        "gross_electricity_mwh": round(sum(float(value(model.gross_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else round(sum(float(value(model.electricity_mwh[t])) for t in model.TIME), 6),
        "net_grid_import_mwh": round(sum(float(value(model.net_grid_import_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else round(sum(float(value(model.electricity_mwh[t])) for t in model.TIME), 6),
        "gross_grid_import_mwh": round(sum(float(value(model.gross_grid_import_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else round(sum(float(value(model.electricity_mwh[t])) for t in model.TIME), 6),
        "gross_grid_export_mwh": round(sum(float(value(model.gross_grid_export_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "net_grid_exchange_mwh": round(sum(float(value(model.net_grid_exchange_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else round(sum(float(value(model.electricity_mwh[t])) for t in model.TIME), 6),
        "BFG_flared_mwh": round(sum(float(value(model.bfg_flared[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "COG_flared_mwh": round(sum(float(value(model.cog_flared[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "BOFG_flared_mwh": round(sum(float(value(model.bofg_flared[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "flaring_co2_t": round(sum(float(value(model.flaring_co2_t[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "flaring_co2_diagnostic_cost_eur": round(
            sum(float(value(model.flaring_co2_diagnostic_cost_eur[t])) for t in model.TIME),
            6,
        )
        if enable_minimal_wag_layer
        else 0.0,
        "max_abs_wag_balance_residual_mwh": round(
            max(
                max(abs(float(value(model.bfg_balance_residual[t]))) for t in model.TIME),
                max(abs(float(value(model.cog_balance_residual[t]))) for t in model.TIME),
                max(abs(float(value(model.bofg_balance_residual[t]))) for t in model.TIME),
            ),
            9,
        )
        if enable_minimal_wag_layer
        else 0.0,
        "minimal_wag_layer_active": str(enable_minimal_wag_layer).lower(),
        "fixed_c1_hybrid_schedule_used": str(fix_c1_hybrid_schedule and hybrid_route_active).lower(),
        "caveat": "Solved C1 hybrid DRP/EAF plus retained BF6/KGF1/BOF route; DRP turndown is modelled as an on-state binary for this C4C development run."
        if hybrid_route_active
        else "Solved C1 DRP/EAF scoped development-only physical regression. Minimal WAG layer reports zero C1 WAG in this builder; retained BF-BOF WAG route remains a next implementation caveat.",
    }
    if hybrid_route_active:
        audit.update(
            {
                "coke_terminal_residual_t": round(coke_inventory[-1] - inputs.retained_bf_bof.coke_store_initial_t, 9)
                if inputs.retained_bf_bof is not None
                else "",
                "sinter_terminal_residual_t": round(sinter_inventory[-1] - inputs.retained_bf_bof.sinter_store_initial_t, 9)
                if inputs.retained_bf_bof is not None
                else "",
                "hot_iron_terminal_residual_t": round(hot_iron_inventory[-1] - inputs.retained_bf_bof.hot_iron_store_initial_t, 9)
                if inputs.retained_bf_bof is not None
                else "",
                "cold_slab_terminal_residual_t": round(cold_slab_inventory[-1] - inputs.retained_bf_bof.cold_slab_store_initial_t, 9)
                if inputs.retained_bf_bof is not None
                else "",
                "coke_inventory_min_t": round(min(coke_inventory), 6),
                "coke_inventory_max_t": round(max(coke_inventory), 6),
                "sinter_inventory_min_t": round(min(sinter_inventory), 6),
                "sinter_inventory_max_t": round(max(sinter_inventory), 6),
                "hot_iron_inventory_min_t": round(min(hot_iron_inventory), 6),
                "hot_iron_inventory_max_t": round(max(hot_iron_inventory), 6),
                "cold_slab_inventory_min_t": round(min(cold_slab_inventory), 6),
                "cold_slab_inventory_max_t": round(max(cold_slab_inventory), 6),
            }
        )
    constraint_rows = [
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "constraint_family": "process_activity_variables",
            "implemented": "yes",
            "row_count_or_constraint_count": (7 if hybrid_route_active else 2) * inputs.horizon_hours,
            "source_table": "process_units.csv",
            "blocking_if_missing": "yes",
            "caveat": "DRP/EAF plus retained KGF1/Sinter/BF6/BOF/HSM variables implemented."
            if hybrid_route_active
            else "DRP pellet input and EAF DRI input variables implemented.",
        },
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "constraint_family": "capacity_bounds",
            "implemented": "yes",
            "row_count_or_constraint_count": (14 if hybrid_route_active else 4) * inputs.horizon_hours,
            "source_table": "process_units.csv",
            "blocking_if_missing": "yes",
            "caveat": "Retained route and DRP/EAF on-state min/max bounds implemented."
            if hybrid_route_active
            else "DRP min/max and EAF off/on min/max implemented.",
        },
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "constraint_family": "ramp_limits",
            "implemented": "deferred_in_hybrid" if hybrid_route_active else "yes",
            "row_count_or_constraint_count": 0 if hybrid_route_active else 2 * (inputs.horizon_hours - 1),
            "source_table": "process_units.csv",
            "blocking_if_missing": "no",
            "caveat": "DRP ramp is deferred in C4C hybrid route because the on-state binary replaces the earlier always-on DRP shortcut."
            if hybrid_route_active
            else "DRP ramp implemented where ramp input exists.",
        },
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "constraint_family": "DRI_and_retained_route_buffer_balance" if hybrid_route_active else "DRI_buffer_balance",
            "implemented": "yes",
            "row_count_or_constraint_count": (5 if hybrid_route_active else 1) * inputs.horizon_hours,
            "source_table": "buffers_and_stores.csv",
            "blocking_if_missing": "yes",
            "caveat": "DRI, coke, sinter, hot iron, and cold slab balances implemented."
            if hybrid_route_active
            else "Nonnegative inventory and balance implemented.",
        },
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "constraint_family": "DRI_buffer_capacity",
            "implemented": "yes",
            "row_count_or_constraint_count": inputs.horizon_hours,
            "source_table": "buffers_and_stores.csv",
            "blocking_if_missing": "yes",
            "caveat": "Finite capacity bound implemented.",
        },
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "constraint_family": "terminal_inventory_rule",
            "implemented": "yes",
            "row_count_or_constraint_count": 1,
            "source_table": "buffers_and_stores.csv",
            "blocking_if_missing": "yes",
            "caveat": "Terminal equality to initial inventory implemented.",
        },
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "constraint_family": "final_product_fulfilment",
            "implemented": "yes",
            "row_count_or_constraint_count": 1,
            "source_table": "production_targets.csv",
            "blocking_if_missing": "yes",
            "caveat": (
                "Hard cumulative quota lower bound; overproduction is allowed and reported."
                if rolling_production_deadline_targets_t is not None
                else "Hard equality to final-product proxy target."
            ),
        },
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "constraint_family": "downstream_origin_tagged_material_interface",
            "implemented": "yes" if downstream_origin_routing is not None else "no",
            "row_count_or_constraint_count": 5 * inputs.horizon_hours if downstream_origin_routing is not None else 0,
            "source_table": "DSP_Parameters.md;HSM_Parameters.md;C5 product-boundary policy",
            "blocking_if_missing": "yes_for_site_final_product_anchor_claims",
            "caveat": "BOF/EAF-to-HSM/DSP balances and a separate capped import-to-HSM input are active; the EAF DSP route-share anchor remains reporting-only."
            if downstream_origin_routing is not None
            else "The current pooled/direct final-product proxy remains active.",
        },
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "constraint_family": "carrier_specific_WAG_steam_internal_generation_balance"
            if hybrid_route_active and enable_minimal_wag_layer
            else "WAG_steam_grid_balance",
            "implemented": "yes" if hybrid_route_active and enable_minimal_wag_layer else ("partial_placeholder" if enable_minimal_wag_layer else "no"),
            "row_count_or_constraint_count": 6 * inputs.horizon_hours if hybrid_route_active and enable_minimal_wag_layer else (inputs.horizon_hours if enable_minimal_wag_layer else 0),
            "source_table": "wag_generation_coefficients.csv;utility_conversion_assets.csv",
            "blocking_if_missing": "yes_for_site_scope_claims",
            "caveat": "Retained BF6/KGF1/BOF WAG generation, process sinks, boiler placeholder, Vattenfall/internal generation, and carrier flaring are active."
            if hybrid_route_active and enable_minimal_wag_layer
            else (
                "Minimal layer reports zero C1 WAG in the current DRP/EAF builder and applies boiler/steam placeholder reporting; retained BF-BOF WAG route remains not implemented."
                if enable_minimal_wag_layer
                else "Blocked by missing WAG and full-site utility inputs."
            ),
        },
    ]
    hourly_rows = []
    for t in model.TIME:
        hourly_rows.append(
            {
                "hour_index": int(t),
                "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
                "build_status": "solved",
                "C0_BF_BOF_STATIC_BLOCK_activity": round(float(value(model.hot_strip_mill[t])), 6)
                if hybrid_route_active
                else "",
                "C1_retained_coking_input_t_h": round(float(value(model.coking_plant_1[t])), 12)
                if hybrid_route_active
                else "",
                "C1_retained_coke_output_t_h": round(float(value(model.coke_output[t])), 6)
                if hybrid_route_active
                else "",
                "C1_retained_BF_coke_demand_t_h": round(float(value(model.bf_coke_demand[t])), 6)
                if hybrid_route_active
                else "",
                "C1_retained_sintering_input_t_h": round(float(value(model.sintering_plant[t])), 6)
                if hybrid_route_active
                else "",
                "C1_retained_sinter_iron_ore_feed_t_h": round(float(value(model.sintering_plant[t])), 12)
                if hybrid_route_active
                else "",
                "C1_retained_sinter_output_t_h": round(float(value(model.sinter_output[t])), 6)
                if hybrid_route_active
                else "",
                "C1_retained_BF6_sinter_input_t_h": round(float(value(model.blast_furnace_6[t])), 6)
                if hybrid_route_active
                else "",
                "C1_retained_BF_hot_iron_output_t_h": round(float(value(model.bf_hot_iron_output[t])), 6)
                if hybrid_route_active
                else "",
                "C1_BF_PCI_input_t": round(float(value(model.bf_pci_input_t[t])), 12)
                if hybrid_route_active
                else "",
                "C1_retained_BOF_hot_iron_input_t_h": round(float(value(model.basic_oxygen_furnace[t])), 6)
                if hybrid_route_active
                else "",
                "C1_BOF_liquid_steel_output_t_h": round(float(value(model.bof_crude_steel_output[t])), 6)
                if hybrid_route_active
                else "",
                "C1_EAF_liquid_steel_output_t_h": round(
                    float(value(model.eaf_liquid_steel_output[t]))
                    if hybrid_route_active
                    else float(value(model.final_product_output[t])),
                    6,
                ),
                "C1_retained_HSM_input_t_h": round(float(value(model.hot_strip_mill[t])), 6)
                if hybrid_route_active
                else "",
                "C1_HSM_final_product_output_t": round(
                    float(
                        value(
                            float(downstream_origin_routing["hsm_final_t_per_t_slab"])
                            * model.hot_strip_mill[t]
                        )
                    ),
                    6,
                )
                if hybrid_route_active and downstream_origin_routing is not None
                else (
                    round(float(value(model.hot_strip_mill[t])), 6)
                    if hybrid_route_active
                    else ""
                ),
                "C1_HSM_material_loss_t": round(
                    float(
                        value(
                            model.hot_strip_mill[t]
                            - float(downstream_origin_routing["hsm_final_t_per_t_slab"])
                            * model.hot_strip_mill[t]
                        )
                    ),
                    6,
                )
                if hybrid_route_active and downstream_origin_routing is not None
                else 0.0,
                "C1_BOF_to_HSM_slab_t_h": round(float(value(model.bof_to_hsm_slab[t])), 6)
                if hybrid_route_active
                else "",
                "C1_BOF_to_DSP_liquid_steel_t_h": round(float(value(model.bof_to_dsp_liquid_steel[t])), 6)
                if hybrid_route_active
                else "",
                "C1_EAF_to_HSM_slab_t_h": round(float(value(model.eaf_to_hsm_slab[t])), 6)
                if hybrid_route_active
                else "",
                "C1_EAF_to_DSP_liquid_steel_t_h": round(float(value(model.eaf_to_dsp_liquid_steel[t])), 6)
                if hybrid_route_active
                else "",
                "C1_imported_slab_to_HSM_t_h": round(float(value(model.imported_slab_to_hsm[t])), 12)
                if hybrid_route_active
                else "",
                "C1_cold_slab_draw_to_HSM_t_h": round(float(value(model.cold_slab_draw_to_hsm[t])), 6)
                if hybrid_route_active and downstream_origin_routing is not None
                else "",
                "C1_DSP_final_product_output_t": round(float(value(model.dsp_final_product_output[t])), 6)
                if hybrid_route_active
                else "",
                "C1_KGF1_on": round(float(value(model.coking_plant_1_on[t])), 6)
                if hybrid_route_active
                else 0.0,
                "C1_sintering_on": round(float(value(model.sintering_plant_on[t])), 6)
                if hybrid_route_active
                else 0.0,
                "C1_BF6_on": round(float(value(model.blast_furnace_6_on[t])), 6)
                if hybrid_route_active
                else 0.0,
                "C1_BOF_on": round(float(value(model.basic_oxygen_furnace_on[t])), 6)
                if hybrid_route_active
                else 0.0,
                "C1_HSM_on": round(float(value(model.hot_strip_mill_on[t])), 6)
                if hybrid_route_active
                else 0.0,
                "C1_DRP_on": round(float(value(model.drp_on[t])), 6) if hasattr(model, "drp_on") else "",
                "C1_EAF_on": round(float(value(model.eaf_on[t])), 6),
                "C1_retained_final_product_output_t": round(float(value(model.retained_bf_bof_final_product_output[t])), 6)
                if hybrid_route_active
                else "",
                "C1_EAF_final_product_output_t": round(float(value(model.eaf_final_product_output[t])), 6)
                if hybrid_route_active
                else round(float(value(model.final_product_output[t])), 6),
                "C1_BF7_activity_t_h": 0.0,
                "C1_KGF2_activity_t_h": 0.0,
                "C1_DRP_activity_t_pellets_h": round(float(value(model.drp_pellet_input[t])), 12),
                "PEFA_pellet_output_t": round(
                    _model_value_or_zero(model, "pefa_pellet_output_t", t), 6
                ),
                "PEFA_iron_ore_input_t": round(
                    _model_value_or_zero(model, "pefa_iron_ore_input_t", t), 12
                ),
                "C1_DRP_DRI_output_t_h": round(float(value(model.drp_dri_output[t])), 6),
                "C1_EAF_activity_t_DRI_h": round(float(value(model.eaf_dri_input[t])), 6),
                "C1_BOF_scrap_input_t_h": round(float(value(model.bof_scrap_supply_t[t])), 12)
                if hybrid_route_active
                else "",
                "C1_EAF_scrap_input_t_h": round(float(value(model.eaf_scrap_supply_t[t])), 12)
                if hybrid_route_active and hasattr(model, "eaf_scrap_supply_t")
                else round(float(value(model.scrap_t[t])), 6),
                "final_product_output_t": round(float(value(model.final_product_output[t])), 6),
                "final_product_output_t_unrounded": float(
                    value(model.final_product_output[t])
                ),
                "coke_inventory_t": round(float(value(model.coke_inventory[t])), 6)
                if hybrid_route_active
                else "",
                "coke_inventory_t_unrounded": float(value(model.coke_inventory[t]))
                if hybrid_route_active
                else "",
                "sinter_inventory_t": round(float(value(model.sinter_inventory[t])), 6)
                if hybrid_route_active
                else "",
                "sinter_inventory_t_unrounded": float(
                    value(model.sinter_inventory[t])
                )
                if hybrid_route_active
                else "",
                "hot_iron_inventory_t": round(float(value(model.hot_iron_inventory[t])), 6)
                if hybrid_route_active
                else "",
                "hot_iron_inventory_t_unrounded": float(
                    value(model.hot_iron_inventory[t])
                )
                if hybrid_route_active
                else "",
                "cold_slab_inventory_t": round(float(value(model.cold_slab_inventory[t])), 6)
                if hybrid_route_active
                else "",
                "cold_slab_inventory_t_unrounded": float(
                    value(model.cold_slab_inventory[t])
                )
                if hybrid_route_active
                else "",
                "DRI_inventory_t": round(float(value(model.dri_inventory[t])), 6),
                "DRI_inventory_t_unrounded": float(value(model.dri_inventory[t])),
                "base_process_electricity_mwh": round(float(value(model.electricity_mwh[t])), 6),
                "development_controller_electricity_mwh": round(
                    float(value(model.development_controller_electricity_mwh[t])), 6
                )
                if enable_minimal_wag_layer
                else 0.0,
                "DRP_electricity_mwh": round(_model_value_or_zero(model, "drp_electricity_mwh", t), 6),
                "EAF_arc_electricity_mwh": round(_model_value_or_zero(model, "eaf_arc_electricity_mwh", t), 6),
                "HSM_rolling_electricity_mwh": round(_model_value_or_zero(model, "hsm_rolling_electricity_mwh", t), 6),
                "PEFA_electricity_mwh": round(_model_value_or_zero(model, "pefa_electricity_mwh", t), 6),
                "BOF_electricity_mwh": round(_model_value_or_zero(model, "bof_electricity_mwh", t), 6),
                "BF_electricity_mwh": round(_model_value_or_zero(model, "bf_electricity_mwh", t), 6),
                "KGF_electricity_mwh": round(_model_value_or_zero(model, "kgf_electricity_mwh", t), 6),
                "DSP_electricity_mwh": round(_model_value_or_zero(model, "dsp_electricity_mwh", t), 6),
                "EAF_secondary_electricity_mwh": round(_model_value_or_zero(model, "eaf_secondary_electricity_mwh", t), 6),
                "ASU_oxygen_electricity_mwh": round(_model_value_or_zero(model, "asu_electricity_mwh", t), 6),
                "Linde_N2_auxiliary_electricity_mwh": round(_model_value_or_zero(model, "linde_n2_auxiliary_electricity_mwh", t), 6),
                "Linde_total_electricity_mwh": round(_model_value_or_zero(model, "linde_total_electricity_mwh", t), 6),
                "sinter_electricity_mwh": round(_model_value_or_zero(model, "sinter_electricity_mwh", t), 6),
                "represented_electricity_bucket_sum_mwh": round(
                    float(value(model.electricity_mwh[t]))
                    + _model_value_or_zero(model, "development_controller_electricity_mwh", t)
                    + _model_value_or_zero(model, "electricity_boundary_development_mwh", t), 6
                ),
                "electricity_bucket_sum_residual_mwh": round(
                    float(value(model.represented_gross_electricity_before_background_mwh[t] - model.electricity_mwh[t]))
                    - _model_value_or_zero(model, "development_controller_electricity_mwh", t)
                    - _model_value_or_zero(model, "electricity_boundary_development_mwh", t), 9
                ) if development_controller_activation == "full_electricity_boundary" else 0.0,
                "linde_split_residual_mwh": round(
                    _model_value_or_zero(model, "linde_total_electricity_mwh", t)
                    - _model_value_or_zero(model, "asu_electricity_mwh", t)
                    - _model_value_or_zero(model, "linde_n2_auxiliary_electricity_mwh", t), 9
                ),
                "exact_site_electricity_proxy_active": 0.0,
                "electricity_mwh": round(float(value(model.gross_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else round(float(value(model.electricity_mwh[t])), 6),
                "natural_gas_nm3": round(float(value(model.natural_gas_nm3[t])), 6),
                "DRP_named_NG_mwh": round(_model_value_or_zero(model, "drp_named_ng_mwh", t), 12),
                "DRP_reduction_NG_mwh": round(_model_value_or_zero(model, "drp_reduction_ng_mwh", t), 12),
                "DRP_furnace_NG_mwh": round(_model_value_or_zero(model, "drp_furnace_ng_mwh", t), 12),
                "DRP_HERACLES_NG_split_residual_mwh": round(
                    _model_value_or_zero(model, "drp_heracless_ng_split_residual_mwh", t), 12
                ),
                "EAF_named_NG_mwh": round(_model_value_or_zero(model, "eaf_named_ng_mwh", t), 12),
                "natural_gas_boiler_mwh": round(float(value(model.ng_to_boiler_mwh[t])), 12),
                "BFG_generated_mwh": round(float(value(model.bfg_generated[t])), 6),
                "COG_generated_mwh": round(float(value(model.cog_generated[t])), 6),
                "BOFG_generated_mwh": round(float(value(model.bofg_generated[t])), 6),
                "BFG_to_BF_hot_stove_mwh": round(float(value(model.bfg_to_bf_hot_stove[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BFG_to_KGF1_mwh": round(float(value(model.bfg_to_kgf1[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "COG_to_KGF1_mwh": round(float(value(model.cog_to_kgf1[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "COG_to_KGF2_mwh": round(float(value(model.cog_to_kgf2[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "COG_to_sinter_mwh": round(float(value(model.cog_to_sinter[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BFG_to_HSM_mwh": round(float(value(model.bfg_to_hsm[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "COG_to_HSM_mwh": round(float(value(model.cog_to_hsm[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BOFG_to_HSM_mwh": round(float(value(model.bofg_to_hsm[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "COG_to_PEFA_branderij_mwh": round(float(value(model.cog_to_pefa_branderij[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BOFG_to_PEFA_malerij_mwh": round(float(value(model.bofg_to_pefa_malerij[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "NG_to_HSM_mwh": round(float(value(model.ng_to_hsm_mwh[t])), 12)
                if enable_minimal_wag_layer
                else 0.0,
                "NG_to_PEFA_malerij_mwh": round(float(value(model.ng_to_pefa_malerij_mwh[t])), 12)
                if enable_minimal_wag_layer
                else 0.0,
                "NG_to_PEFA_branderij_mwh": round(float(value(model.ng_to_pefa_branderij_mwh[t])), 12)
                if enable_minimal_wag_layer
                else 0.0,
                "BFG_to_boiler_mwh": round(float(value(model.bfg_to_boiler[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "COG_to_boiler_mwh": round(float(value(model.cog_to_boiler[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BOFG_to_boiler_mwh": 0.0,
                "BFG_to_vattenfall_mwh": round(float(value(model.bfg_to_vattenfall[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "COG_to_vattenfall_mwh": round(float(value(model.cog_to_vattenfall[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BOFG_to_vattenfall_mwh": round(float(value(model.bofg_to_vattenfall[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BFG_to_VN25_mwh": round(float(value(model.bfg_to_vn25[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "bfg_to_vn25")
                else 0.0,
                "COG_to_VN25_mwh": round(float(value(model.cog_to_vn25[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "cog_to_vn25")
                else 0.0,
                "BOFG_to_VN25_mwh": round(float(value(model.bofg_to_vn25[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "bofg_to_vn25")
                else 0.0,
                "BFG_to_IJ01_mwh": round(float(value(model.bfg_to_ij01[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "bfg_to_ij01")
                else 0.0,
                "COG_to_IJ01_mwh": round(float(value(model.cog_to_ij01[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "cog_to_ij01")
                else 0.0,
                "BOFG_to_IJ01_mwh": round(float(value(model.bofg_to_ij01[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "bofg_to_ij01")
                else 0.0,
                "vattenfall_fuel_mwh": round(float(value(model.vattenfall_fuel_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "generator_named_ng_mwh": round(float(value(model.generator_named_ng_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "site_baseload_ng_mwh": round(float(value(model.site_baseload_ng_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "total_named_ng_procurement_mwh": round(
                    float(value(model.total_named_ng_procurement_mwh[t])), 6
                )
                if enable_minimal_wag_layer
                else 0.0,
                "generator_total_fuel_mwh": round(float(value(model.generator_total_fuel_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "generator_electricity_mwh": round(float(value(model.generator_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "WAG_generator_electricity_mwh": round(float(value(model.wag_generator_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "WAG_generator_electricity_mwh_unrounded": float(
                    value(model.wag_generator_electricity_mwh[t])
                )
                if enable_minimal_wag_layer
                else 0.0,
                "NG_generator_electricity_mwh": round(float(value(model.ng_generator_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "NG_generator_electricity_mwh_unrounded": float(
                    value(model.ng_generator_electricity_mwh[t])
                )
                if enable_minimal_wag_layer
                else 0.0,
                "total_generator_electricity_mwh": round(float(value(model.total_generator_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "total_generator_electricity_mwh_unrounded": float(
                    value(model.total_generator_electricity_mwh[t])
                )
                if enable_minimal_wag_layer
                else 0.0,
                "generator_unit_interface_active": 1.0
                if enable_minimal_wag_layer and getattr(model, "generator_unit_interface_active", False)
                else 0.0,
                "VN25_WAG_fuel_mwh": round(float(value(model.vn25_wag_fuel_mwh[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "vn25_wag_fuel_mwh")
                else 0.0,
                "VN25_NG_fuel_mwh": round(float(value(model.ng_to_vn25_mwh[t])), 12)
                if enable_minimal_wag_layer and hasattr(model, "ng_to_vn25_mwh")
                else 0.0,
                "VN25_total_fuel_mwh": round(float(value(model.vn25_total_fuel_mwh[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "vn25_total_fuel_mwh")
                else 0.0,
                "VN25_electricity_mwh": round(float(value(model.vn25_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "vn25_electricity_mwh")
                else 0.0,
                "VN25_electric_capacity_mw": float(
                    getattr(model, "vn25_electric_capacity_mw", 0.0)
                ),
                "generator_operating_mode": str(
                    getattr(model, "generator_operating_mode", "not_applicable")
                ),
                "VN25_conversion_loss_mwh": round(float(value(model.vn25_conversion_loss_mwh[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "vn25_conversion_loss_mwh")
                else 0.0,
                "IJ01_WAG_fuel_mwh": round(float(value(model.ij01_wag_fuel_mwh[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "ij01_wag_fuel_mwh")
                else 0.0,
                "IJ01_NG_fuel_mwh": round(float(value(model.ng_to_ij01_mwh[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "ng_to_ij01_mwh")
                else 0.0,
                "IJ01_total_fuel_mwh": round(float(value(model.ij01_total_fuel_mwh[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "ij01_total_fuel_mwh")
                else 0.0,
                "IJ01_electricity_mwh": round(float(value(model.ij01_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "ij01_electricity_mwh")
                else 0.0,
                "IJ01_deferred_conversion_mwh": round(float(value(model.ij01_deferred_conversion_mwh[t])), 6)
                if enable_minimal_wag_layer and hasattr(model, "ij01_deferred_conversion_mwh")
                else 0.0,
                "generator_fuel_identity_residual_mwh": round(
                    float(
                        value(
                            model.generator_total_fuel_mwh[t]
                            - model.generator_electricity_mwh[t]
                            - (
                                model.vn25_conversion_loss_mwh[t]
                                + model.ij01_deferred_conversion_mwh[t]
                                if hasattr(model, "vn25_conversion_loss_mwh")
                                else model.generator_total_fuel_mwh[t]
                                - model.generator_electricity_mwh[t]
                            )
                        )
                    ),
                    9,
                )
                if enable_minimal_wag_layer
                else 0.0,
                "wag_electricity_mwh": round(float(value(model.wag_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "represented_gross_electricity_before_background_mwh": round(float(value(model.represented_gross_electricity_before_background_mwh[t])), 6)
                if enable_minimal_wag_layer
                else round(float(value(model.electricity_mwh[t])), 6),
                "site_background_electricity_mwh": round(float(value(model.site_background_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "gross_total_electricity_mwh": round(float(value(model.gross_total_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else round(float(value(model.electricity_mwh[t])), 6),
                "gross_electricity_mwh": round(float(value(model.gross_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else round(float(value(model.electricity_mwh[t])), 6),
                "gross_grid_import_mwh": round(float(value(model.gross_grid_import_mwh[t])), 12)
                if enable_minimal_wag_layer
                else round(float(value(model.electricity_mwh[t])), 6),
                "gross_grid_export_mwh": round(float(value(model.gross_grid_export_mwh[t])), 12)
                if enable_minimal_wag_layer
                else 0.0,
                "net_grid_exchange_mwh": round(float(value(model.net_grid_exchange_mwh[t])), 12)
                if enable_minimal_wag_layer
                else round(float(value(model.electricity_mwh[t])), 6),
                "gross_site_electricity_identity_residual_mwh": round(float(value(model.gross_site_electricity_identity_residual_mwh[t])), 12)
                if enable_minimal_wag_layer
                else 0.0,
                "net_grid_import_mwh": round(float(value(model.net_grid_import_mwh[t])), 12)
                if enable_minimal_wag_layer
                else round(float(value(model.electricity_mwh[t])), 6),
                "BFG_flared_mwh": round(float(value(model.bfg_flared[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "COG_flared_mwh": round(float(value(model.cog_flared[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BOFG_flared_mwh": round(float(value(model.bofg_flared[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "WAG_generated": round(float(value(model.wag_generated[t])), 6),
                "WAG_used": round(float(value(model.wag_used[t])), 6),
                "WAG_flared": round(float(value(model.wag_flared[t])), 6),
                "steam": round(float(value(model.steam_production_mwh[t])), 6),
                "steam_15bar_explicit_demand_t": round(float(value(model.steam_15bar_explicit_demand_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "residual_steam_15bar_demand_t": round(float(value(model.residual_steam_15bar_demand_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "steam_15bar_demand_t": round(float(value(model.steam_15bar_demand_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "steam_15bar_supply_t": round(float(value(model.steam_15bar_supply_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "WAG_boiler_steam_supply_t": round(float(value(model.wag_boiler_steam_supply_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "NG_boiler_steam_supply_t": round(float(value(model.ng_boiler_steam_supply_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "recovered_steam_supply_t": round(float(value(model.recovered_steam_supply_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "external_steam_supply_t": round(float(value(model.external_steam_supply_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "steam_15bar_spill_t": round(float(value(model.steam_15bar_spill_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "steam_15bar_unserved_t": round(float(value(model.steam_15bar_unserved_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BFG_balance_residual_mwh": round(float(value(model.bfg_balance_residual[t])), 9)
                if enable_minimal_wag_layer
                else 0.0,
                "COG_balance_residual_mwh": round(float(value(model.cog_balance_residual[t])), 9)
                if enable_minimal_wag_layer
                else 0.0,
                "BOFG_balance_residual_mwh": round(float(value(model.bofg_balance_residual[t])), 9)
                if enable_minimal_wag_layer
                else 0.0,
                "BFG_flare_co2_t": round(float(value(model.bfg_flare_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "COG_flare_co2_t": round(float(value(model.cog_flare_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BOFG_flare_co2_t": round(float(value(model.bofg_flare_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "flaring_co2_t": round(float(value(model.flaring_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BFG_explicit_combustion_co2_t": round(float(value(model.bfg_explicit_combustion_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "COG_explicit_combustion_co2_t": round(float(value(model.cog_explicit_combustion_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "BOFG_explicit_combustion_co2_t": round(float(value(model.bofg_explicit_combustion_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "WAG_explicit_combustion_co2_t": round(float(value(model.wag_explicit_combustion_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "explicit_NG_combustion_co2_t": round(float(value(model.explicit_ng_combustion_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "residual_unmodelled_direct_co2_t": round(float(value(model.residual_unmodelled_direct_co2_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "total_direct_co2_reporting_t": round(float(value(model.total_direct_co2_reporting_t[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "flaring_co2_diagnostic_cost_eur": round(float(value(model.flaring_co2_diagnostic_cost_eur[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "oxygen_t": round(float(value(model.oxygen_t[t])), 6),
                "total_static_cost": 0.0,
                "caveat": "C1 hybrid retained BF6/KGF1/BOF plus DRP/EAF development run; DRP on/off treatment is C4C-specific."
                if hybrid_route_active
                else "C1 DRP/EAF scoped physical regression only; retained BF-BOF WAG route not represented in this builder.",
            }
        )
    if normal_solution_capture is not None:
        audit.update(
            {
                key: cost_metadata[key]
                for key in (
                    "normal_solution_capture_path",
                    "normal_solution_capture_sha256",
                    "normal_solution_variable_count",
                    "normal_solution_variable_name_sha256",
                    "normal_solution_variable_schema_sha256",
                    "normal_solution_variable_fixed_schema_sha256",
                )
            }
        )
    return audit, constraint_rows, hourly_rows


def _report_rows(build_audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration_id": row["configuration_id"],
            "build_status": row["build_status"],
            "solver_status": row["solver_status"],
            "termination_condition": row["termination_condition"],
            "objective_value": row["objective_value"],
            "variable_count": row["variable_count"],
            "binary_count": row["binary_count"],
            "constraint_count": row["constraint_count"],
            "final_product_target_t": row["final_product_target_t"],
            "final_product_fulfilled_t": row["final_product_fulfilled_t"],
            "final_product_residual_t": row["final_product_residual_t"],
            "blocker_count": row["blocker_count"],
            "caveat": row["caveat"],
        }
        for row in build_audits
    ]


def _stage_gate(build_audits: list[dict[str, Any]], invalid_rows_used_count: int) -> dict[str, Any]:
    statuses = {row["configuration_id"]: row["build_status"] for row in build_audits}
    solved_count = sum(1 for status in statuses.values() if status == "solved")
    blocked_count = sum(1 for status in statuses.values() if status == "blocked_missing_inputs")
    fake_value_failure = invalid_rows_used_count > 0
    if fake_value_failure:
        decision = "block_s4_4d"
        may_proceed = False
    elif solved_count == len(CONFIGURATIONS):
        decision = "pass_to_s4_4d"
        may_proceed = True
    elif solved_count >= 1 and blocked_count >= 1:
        decision = "pass_with_limitations_to_s4_4d"
        may_proceed = True
    else:
        decision = "block_s4_4d"
        may_proceed = False
    return {
        "stage": "S4.4c",
        "decision": decision,
        "may_proceed_to_s4_4d": may_proceed,
        "model_behaviour_changed": False,
        "price_naive_policy_mode": POLICY_MODE,
        "hourly_da_price_taking_active": False,
        "product_revenue_active": False,
        "export_revenue_active": False,
        "grid_tariff_objective_active": False,
        "direct_wag_market_valuation_active": False,
        "co2_ets_objective_active": False,
        "invalid_input_rows_used_count": invalid_rows_used_count,
        "solved_configuration_count": solved_count,
        "blocked_configuration_count": blocked_count,
        "c0_status": statuses.get("C0_current_BF_BOF_reference"),
        "c1_status": statuses.get("C1_phase1_BF_BOF_plus_DRP_EAF"),
        "thesis_usability": "development_only_with_limitations",
        "caveat": "S4.4c is static-price physical regression. C0 remains blocked if no executable physical rows exist.",
    }


def _validate_forbidden_terms(tables: UnifiedInputTables) -> int:
    invalid = 0
    for row in tables.tables["external_supply_costs.csv"]:
        if row["carrier_or_material"] in FORBIDDEN_TERMS and row["active_in_objective"].strip().lower() != "false":
            invalid += 1
    return invalid


def run_s44c_unified_physical_regression(
    *,
    input_dir: str | Path = S44B_INPUT_DIR,
    run_id: str | None = None,
    write_report: bool = True,
    report_dir: str | Path | None = None,
    horizon_hours_override: int | None = None,
    target_multiplier: float = 1.0,
    target_multiplier_by_configuration: Mapping[str, float] | None = None,
    fix_c0_binary_schedule: bool = False,
    enable_minimal_wag_layer: bool = False,
    enable_c1_retained_bf_bof_route: bool = False,
    enable_internal_wag_power: bool = False,
    development_controller_activation: str = "none",
    hsm_rolling_electricity_mwh_per_t_hrc_override: float | None = None,
    development_controller_profile_weights_by_configuration: Mapping[str, Mapping[str, Mapping[int, float]]] | None = None,
    daily_production_guardrail: bool = False,
    rolling_production_deadline_targets_t: Mapping[int, float] | None = None,
    rolling_production_deadline_targets_by_configuration_t: Mapping[
        str, Mapping[int, float]
    ]
    | None = None,
    rolling_production_progress_target_by_configuration_t: Mapping[
        str, float
    ]
    | None = None,
    rolling_production_progress_lower_bound_by_configuration_t: Mapping[
        str, float
    ]
    | None = None,
    rolling_production_progress_upper_bound_by_configuration_t: Mapping[
        str, float
    ]
    | None = None,
    rolling_production_execution_block_hours: int = 24,
    rolling_production_hard_exact_execution_target: bool = False,
    rolling_production_exact_deadline_hour: int | None = None,
    rolling_production_exact_deadline_target_by_configuration_t: Mapping[
        str, float
    ]
    | None = None,
    initial_inventory_overrides_by_configuration: Mapping[str, Mapping[str, float]] | None = None,
    rolling_terminal_inventory_hour: int | None = None,
    rolling_terminal_inventory_bounds_by_configuration: Mapping[
        str, Mapping[str, Mapping[str, float]]
    ]
    | None = None,
    fix_c1_hybrid_schedule: bool = False,
    c1_retained_route_policy: str = "target_share",
    commitment_granularity: str = "hourly_binary",
    commitment_day_lengths: Collection[int] | None = None,
    solver_time_limit_seconds: float | None = None,
    c0_continuous_must_run_activities: Collection[str] | None = None,
    c0_coke_chain_reconciliation: Mapping[str, float] | None = None,
    c0_downstream_reference_routing: Mapping[str, Any] | None = None,
    downstream_origin_routing: Mapping[str, float] | None = None,
    eaf_material_balance: Mapping[str, float] | None = None,
    bof_material_balance: Mapping[str, float] | None = None,
    scrap_supply_ledger: Mapping[str, Any] | None = None,
    c1_liquid_steel_route_band: Mapping[str, float] | None = None,
    continuous_must_run_activities: Collection[str] | None = None,
    c1_coke_chain_reconciliation: Mapping[str, float] | None = None,
    generator_interface_cap_mode: str = "inherited_profile",
    generator_unit_interface: Mapping[str, Any] | None = None,
    c1_energy_boundary: Mapping[str, float] | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h_by_configuration: Mapping[str, float] | None = None,
    site_baseload_ng_mwh_h_by_configuration: Mapping[str, float] | None = None,
    site_residual_steam_t_h_by_configuration: Mapping[str, float] | None = None,
    site_residual_direct_co2_t_h_by_configuration: Mapping[str, float] | None = None,
    eaf_secondary_electricity_mwh_per_t_ls_override: float | None = None,
    dsp_electricity_mwh_per_t_coil_override: float | None = None,
    external_procurement_flow_coefficients: Mapping[str, float] | None = None,
    deterministic_cost_policy: Mapping[str, Any] | None = None,
    wag_generation_yield_overrides_by_configuration: Mapping[
        str, Mapping[str, float]
    ]
    | None = None,
    bf_electricity_intensity_scale_by_configuration: Mapping[str, float] | None = None,
    c0_aggregate_generator_technical_interface: Mapping[str, Any] | None = None,
    c0_full_site_energy_bridge: Mapping[str, Any] | None = None,
    hsm_source_mix_policy_by_configuration: Mapping[
        str, Mapping[str, Any]
    ]
    | None = None,
    c0_electricity_sale_sensitivity: Mapping[str, Any] | None = None,
    c0_allocation_envelope_diagnostic: Mapping[str, Any] | None = None,
    normal_solution_capture_by_configuration: Mapping[
        str, Mapping[str, Any]
    ]
    | None = None,
    performance_mode: str = "optimized_equivalent",
) -> dict[str, Any]:
    start = time.perf_counter()
    timestamp = now_utc()
    resolved_run_id = run_id or f"{MODE_ID}_{timestamp.strftime('%Y%m%d_%H%M%S')}"
    input_path = Path(input_dir)
    performance_mode_value = validate_performance_mode(performance_mode)
    if site_background_electricity_mwh_h < 0.0:
        raise S44CModelBuilderError("Site background electricity must be non-negative.")
    background_overrides = dict(site_background_electricity_mwh_h_by_configuration or {})
    unknown_background_configurations = set(background_overrides).difference(CONFIGURATIONS)
    if unknown_background_configurations:
        raise S44CModelBuilderError(
            "Unknown site-background configuration(s): "
            f"{sorted(unknown_background_configurations)}."
        )
    resolved_site_background_by_configuration = {
        configuration: float(
            background_overrides.get(configuration, site_background_electricity_mwh_h)
        )
        for configuration in CONFIGURATIONS
    }
    if any(value < 0.0 for value in resolved_site_background_by_configuration.values()):
        raise S44CModelBuilderError(
            "Every configuration-specific site background electricity value must be non-negative."
        )
    ng_baseload_overrides = dict(site_baseload_ng_mwh_h_by_configuration or {})
    unknown_ng_baseload_configurations = set(ng_baseload_overrides).difference(CONFIGURATIONS)
    if unknown_ng_baseload_configurations:
        raise S44CModelBuilderError(
            "Unknown site-baseload NG configuration(s): "
            f"{sorted(unknown_ng_baseload_configurations)}."
        )
    resolved_site_baseload_ng_by_configuration = {
        configuration: float(ng_baseload_overrides.get(configuration, 0.0))
        for configuration in CONFIGURATIONS
    }
    if any(value < 0.0 for value in resolved_site_baseload_ng_by_configuration.values()):
        raise S44CModelBuilderError(
            "Every configuration-specific site baseload NG value must be non-negative."
        )
    residual_steam_overrides = dict(site_residual_steam_t_h_by_configuration or {})
    residual_co2_overrides = dict(site_residual_direct_co2_t_h_by_configuration or {})
    unknown_residual_configurations = (
        set(residual_steam_overrides) | set(residual_co2_overrides)
    ).difference(CONFIGURATIONS)
    if unknown_residual_configurations:
        raise S44CModelBuilderError(
            "Unknown site-residual configuration(s): "
            f"{sorted(unknown_residual_configurations)}."
        )
    resolved_site_residual_steam_by_configuration = {
        configuration: float(residual_steam_overrides.get(configuration, 0.0))
        for configuration in CONFIGURATIONS
    }
    resolved_site_residual_co2_by_configuration = {
        configuration: float(residual_co2_overrides.get(configuration, 0.0))
        for configuration in CONFIGURATIONS
    }
    if any(
        value < 0.0
        for value in (
            *resolved_site_residual_steam_by_configuration.values(),
            *resolved_site_residual_co2_by_configuration.values(),
        )
    ):
        raise S44CModelBuilderError(
            "Every configuration-specific residual steam/CO2 value must be non-negative."
        )
    wag_yield_overrides = dict(wag_generation_yield_overrides_by_configuration or {})
    bf_electricity_scales = dict(bf_electricity_intensity_scale_by_configuration or {})
    hsm_source_mix_policies = dict(hsm_source_mix_policy_by_configuration or {})
    unknown_overlay_configurations = (
        set(wag_yield_overrides)
        | set(bf_electricity_scales)
        | set(hsm_source_mix_policies)
    ).difference(CONFIGURATIONS)
    if unknown_overlay_configurations:
        raise S44CModelBuilderError(
            "Unknown user-authorized overlay configuration(s): "
            f"{sorted(unknown_overlay_configurations)}."
        )
    resolved_bf_electricity_scales = {
        configuration: float(bf_electricity_scales.get(configuration, 1.0))
        for configuration in CONFIGURATIONS
    }
    if any(value <= 0.0 for value in resolved_bf_electricity_scales.values()):
        raise S44CModelBuilderError(
            "Every BF electricity-intensity scale must be positive."
        )
    input_resolution_started = time.perf_counter()
    input_fingerprint = _steel_input_fingerprint(input_path)
    validation_cache_status = "disabled_legacy_rebuild"
    if (
        performance_mode_value == "optimized_equivalent"
        and input_fingerprint in _STEEL_VALIDATION_CACHE
    ):
        validation_result = _STEEL_VALIDATION_CACHE[input_fingerprint]
        validation_cache_status = "hit"
    else:
        validation_result = validate_unified_dev_inputs(input_path)
        if performance_mode_value == "optimized_equivalent":
            _STEEL_VALIDATION_CACHE[input_fingerprint] = validation_result
            validation_cache_status = "miss_registered"
    if validation_result["failure_count"] != 0:
        raise S44CModelBuilderError("S4.4b input validation must pass before S4.4c model construction.")

    tables, table_cache_status, _ = _load_tables_with_status(
        input_path, performance_mode=performance_mode_value
    )
    input_resolution_seconds = time.perf_counter() - input_resolution_started
    horizon_steps = _horizon_hours(tables, horizon_hours_override)
    structural_signature = StructuralSignature(
        model_type="steel_deterministic_rolling_physical",
        granularity="hourly",
        timestep_count=int(horizon_steps),
        scenario_count=1,
        bid_grid=(),
        dst_shape=dst_shape_for_steps("hourly", int(horizon_steps)),
        physical_config_hash=stable_hash(
            {
                "input_fingerprint": input_fingerprint,
                "commitment_granularity": commitment_granularity,
                "fix_c0_binary_schedule": fix_c0_binary_schedule,
                "fix_c1_hybrid_schedule": fix_c1_hybrid_schedule,
                "minimal_wag": enable_minimal_wag_layer,
                "internal_wag_power": enable_internal_wag_power,
                "retained_route": enable_c1_retained_bf_bof_route,
            }
        ),
        quota_structure=stable_hash(
            {
                "deadline_hours": sorted((rolling_production_deadline_targets_t or {}).keys()),
                "execution_block_hours": rolling_production_execution_block_hours,
                "hard_exact": rolling_production_hard_exact_execution_target,
            }
        ),
    )
    template_cache_status, _ = _STEEL_STRUCTURAL_TEMPLATE_CACHE.register(
        structural_signature,
        {"horizon_steps": int(horizon_steps), "configuration_count": len(CONFIGURATIONS)},
    )
    invalid_rows_used_count = _validate_forbidden_terms(tables)
    build_audits: list[dict[str, Any]] = []
    constraint_audits: list[dict[str, Any]] = []
    hourly_rows: list[dict[str, Any]] = []
    blocker_rows: list[dict[str, Any]] = []

    if _has_completed_c0_inputs(tables):
        c0_audit, c0_constraints, c0_hourly = _solve_c0_configuration(
            tables,
            horizon_hours_override=horizon_hours_override,
            target_multiplier=(
                float(
                    target_multiplier_by_configuration.get(
                        "C0_current_BF_BOF_reference", target_multiplier
                    )
                )
                if target_multiplier_by_configuration is not None
                else target_multiplier
            ),
            fix_binary_schedule=fix_c0_binary_schedule,
            enable_minimal_wag_layer=enable_minimal_wag_layer,
            enable_internal_wag_power=enable_internal_wag_power,
            development_controller_activation=development_controller_activation,
            development_controller_profile_weights=(
                development_controller_profile_weights_by_configuration.get("C0_current_BF_BOF_reference")
                if development_controller_profile_weights_by_configuration is not None
                else None
            ),
            daily_production_guardrail=daily_production_guardrail,
            rolling_production_deadline_targets_t=(
                rolling_production_deadline_targets_by_configuration_t.get(
                    "C0_current_BF_BOF_reference",
                    rolling_production_deadline_targets_t or {},
                )
                if rolling_production_deadline_targets_by_configuration_t is not None
                else rolling_production_deadline_targets_t
            ),
            rolling_production_progress_target_t=(
                rolling_production_progress_target_by_configuration_t.get(
                    "C0_current_BF_BOF_reference"
                )
                if rolling_production_progress_target_by_configuration_t is not None
                else None
            ),
            rolling_production_progress_lower_bound_t=(
                rolling_production_progress_lower_bound_by_configuration_t.get(
                    "C0_current_BF_BOF_reference"
                )
                if rolling_production_progress_lower_bound_by_configuration_t
                is not None
                else None
            ),
            rolling_production_progress_upper_bound_t=(
                rolling_production_progress_upper_bound_by_configuration_t.get(
                    "C0_current_BF_BOF_reference"
                )
                if rolling_production_progress_upper_bound_by_configuration_t
                is not None
                else None
            ),
            rolling_production_execution_block_hours=rolling_production_execution_block_hours,
            rolling_production_hard_exact_execution_target=rolling_production_hard_exact_execution_target,
            rolling_production_exact_deadline_hour=rolling_production_exact_deadline_hour,
            rolling_production_exact_deadline_target_t=(
                rolling_production_exact_deadline_target_by_configuration_t.get(
                    "C0_current_BF_BOF_reference"
                )
                if rolling_production_exact_deadline_target_by_configuration_t
                is not None
                else None
            ),
            initial_inventory_overrides=(
                initial_inventory_overrides_by_configuration.get("C0_current_BF_BOF_reference")
                if initial_inventory_overrides_by_configuration is not None
                else None
            ),
            commitment_granularity=commitment_granularity,
            commitment_day_lengths=commitment_day_lengths,
            solver_time_limit_seconds=solver_time_limit_seconds,
            continuous_must_run_activities=c0_continuous_must_run_activities,
            c0_coke_chain_reconciliation=c0_coke_chain_reconciliation,
            c0_downstream_reference_routing=c0_downstream_reference_routing,
            linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
            site_background_electricity_mwh_h=resolved_site_background_by_configuration[
                "C0_current_BF_BOF_reference"
            ],
            site_baseload_ng_mwh_h=resolved_site_baseload_ng_by_configuration[
                "C0_current_BF_BOF_reference"
            ],
            site_residual_steam_t_h=resolved_site_residual_steam_by_configuration[
                "C0_current_BF_BOF_reference"
            ],
            site_residual_direct_co2_t_h=resolved_site_residual_co2_by_configuration[
                "C0_current_BF_BOF_reference"
            ],
            external_procurement_flow_coefficients=external_procurement_flow_coefficients,
            deterministic_cost_policy=deterministic_cost_policy,
            wag_generation_yield_overrides=wag_yield_overrides.get(
                "C0_current_BF_BOF_reference"
            ),
            bf_electricity_intensity_scale=resolved_bf_electricity_scales[
                "C0_current_BF_BOF_reference"
            ],
            aggregate_generator_technical_interface=c0_aggregate_generator_technical_interface,
            full_site_energy_bridge=c0_full_site_energy_bridge,
            hsm_source_mix_policy=hsm_source_mix_policies.get(
                "C0_current_BF_BOF_reference"
            ),
            electricity_sale_sensitivity=c0_electricity_sale_sensitivity,
            allocation_envelope_diagnostic=c0_allocation_envelope_diagnostic,
            normal_solution_capture=(
                normal_solution_capture_by_configuration.get(
                    "C0_current_BF_BOF_reference"
                )
                if normal_solution_capture_by_configuration is not None
                else None
            ),
            rolling_terminal_inventory_hour=rolling_terminal_inventory_hour,
            rolling_terminal_inventory_bounds_t=(
                rolling_terminal_inventory_bounds_by_configuration.get(
                    "C0_current_BF_BOF_reference"
                )
                if rolling_terminal_inventory_bounds_by_configuration is not None
                else None
            ),
        )
        build_audits.append(c0_audit)
        constraint_audits.extend(c0_constraints)
        hourly_rows.extend(c0_hourly)
    else:
        c0_audit, c0_constraints, c0_hourly, c0_blockers = _block_configuration(
            tables,
            "C0_current_BF_BOF_reference",
            caveat="C0 lacks completed executable hourly physical process rows and is blocked rather than given fake flexibility.",
            horizon_hours_override=horizon_hours_override,
            target_multiplier=target_multiplier,
        )
        build_audits.append(c0_audit)
        constraint_audits.extend(c0_constraints)
        hourly_rows.extend(c0_hourly)
        blocker_rows.extend(c0_blockers)

    c1_audit, c1_constraints, c1_hourly = _solve_c1_configuration(
        tables,
        horizon_hours_override=horizon_hours_override,
        target_multiplier=(
            float(
                target_multiplier_by_configuration.get(
                    "C1_phase1_BF_BOF_plus_DRP_EAF", target_multiplier
                )
            )
            if target_multiplier_by_configuration is not None
            else target_multiplier
        ),
        enable_minimal_wag_layer=enable_minimal_wag_layer,
        enable_c1_retained_bf_bof_route=enable_c1_retained_bf_bof_route,
        enable_internal_wag_power=enable_internal_wag_power,
        development_controller_activation=development_controller_activation,
        hsm_rolling_electricity_mwh_per_t_hrc_override=hsm_rolling_electricity_mwh_per_t_hrc_override,
        development_controller_profile_weights=(
            development_controller_profile_weights_by_configuration.get("C1_phase1_BF_BOF_plus_DRP_EAF")
            if development_controller_profile_weights_by_configuration is not None
            else None
        ),
        daily_production_guardrail=daily_production_guardrail,
        rolling_production_deadline_targets_t=(
            rolling_production_deadline_targets_by_configuration_t.get(
                "C1_phase1_BF_BOF_plus_DRP_EAF",
                rolling_production_deadline_targets_t or {},
            )
            if rolling_production_deadline_targets_by_configuration_t is not None
            else rolling_production_deadline_targets_t
        ),
        rolling_production_progress_target_t=(
            rolling_production_progress_target_by_configuration_t.get(
                "C1_phase1_BF_BOF_plus_DRP_EAF"
            )
            if rolling_production_progress_target_by_configuration_t is not None
            else None
        ),
        rolling_production_progress_lower_bound_t=(
            rolling_production_progress_lower_bound_by_configuration_t.get(
                "C1_phase1_BF_BOF_plus_DRP_EAF"
            )
            if rolling_production_progress_lower_bound_by_configuration_t
            is not None
            else None
        ),
        rolling_production_progress_upper_bound_t=(
            rolling_production_progress_upper_bound_by_configuration_t.get(
                "C1_phase1_BF_BOF_plus_DRP_EAF"
            )
            if rolling_production_progress_upper_bound_by_configuration_t
            is not None
            else None
        ),
        rolling_production_execution_block_hours=rolling_production_execution_block_hours,
        rolling_production_hard_exact_execution_target=rolling_production_hard_exact_execution_target,
        rolling_production_exact_deadline_hour=rolling_production_exact_deadline_hour,
        rolling_production_exact_deadline_target_t=(
            rolling_production_exact_deadline_target_by_configuration_t.get(
                "C1_phase1_BF_BOF_plus_DRP_EAF"
            )
            if rolling_production_exact_deadline_target_by_configuration_t
            is not None
            else None
        ),
        initial_inventory_overrides=(
            initial_inventory_overrides_by_configuration.get("C1_phase1_BF_BOF_plus_DRP_EAF")
            if initial_inventory_overrides_by_configuration is not None
            else None
        ),
        fix_c1_hybrid_schedule=fix_c1_hybrid_schedule,
        c1_retained_route_policy=c1_retained_route_policy,
        commitment_granularity=commitment_granularity,
        commitment_day_lengths=commitment_day_lengths,
        solver_time_limit_seconds=solver_time_limit_seconds,
        eaf_material_balance=eaf_material_balance,
        bof_material_balance=bof_material_balance,
        scrap_supply_ledger=scrap_supply_ledger,
        downstream_origin_routing=downstream_origin_routing,
        c1_liquid_steel_route_band=c1_liquid_steel_route_band,
        continuous_must_run_activities=continuous_must_run_activities,
        c1_coke_chain_reconciliation=c1_coke_chain_reconciliation,
        generator_interface_cap_mode=generator_interface_cap_mode,
        generator_unit_interface=generator_unit_interface,
        c1_energy_boundary=c1_energy_boundary,
        hsm_source_mix_policy=hsm_source_mix_policies.get(
            "C1_phase1_BF_BOF_plus_DRP_EAF"
        ),
        linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
        site_background_electricity_mwh_h=resolved_site_background_by_configuration[
            "C1_phase1_BF_BOF_plus_DRP_EAF"
        ],
        site_baseload_ng_mwh_h=resolved_site_baseload_ng_by_configuration[
            "C1_phase1_BF_BOF_plus_DRP_EAF"
        ],
        site_residual_steam_t_h=resolved_site_residual_steam_by_configuration[
            "C1_phase1_BF_BOF_plus_DRP_EAF"
        ],
        site_residual_direct_co2_t_h=resolved_site_residual_co2_by_configuration[
            "C1_phase1_BF_BOF_plus_DRP_EAF"
        ],
        eaf_secondary_electricity_mwh_per_t_ls_override=eaf_secondary_electricity_mwh_per_t_ls_override,
        dsp_electricity_mwh_per_t_coil_override=dsp_electricity_mwh_per_t_coil_override,
        external_procurement_flow_coefficients=external_procurement_flow_coefficients,
        deterministic_cost_policy=deterministic_cost_policy,
        wag_generation_yield_overrides=wag_yield_overrides.get(
            "C1_phase1_BF_BOF_plus_DRP_EAF"
        ),
        bf_electricity_intensity_scale=resolved_bf_electricity_scales[
            "C1_phase1_BF_BOF_plus_DRP_EAF"
        ],
        normal_solution_capture=(
            normal_solution_capture_by_configuration.get(
                "C1_phase1_BF_BOF_plus_DRP_EAF"
            )
            if normal_solution_capture_by_configuration is not None
            else None
        ),
        rolling_terminal_inventory_hour=rolling_terminal_inventory_hour,
        rolling_terminal_inventory_bounds_t=(
            rolling_terminal_inventory_bounds_by_configuration.get(
                "C1_phase1_BF_BOF_plus_DRP_EAF"
            )
            if rolling_terminal_inventory_bounds_by_configuration is not None
            else None
        ),
    )
    build_audits.append(c1_audit)
    constraint_audits.extend(c1_constraints)
    hourly_rows.extend(c1_hourly)

    for audit in build_audits:
        audit.update(
            {
                "performance_mode": performance_mode_value,
                "structural_signature": structural_signature.digest,
                "model_reuse_status": (
                    "static_input_and_structure_cache_hit_pyomo_rebuilt"
                    if table_cache_status == "hit" and template_cache_status == "hit"
                    else "static_input_or_structure_registered_pyomo_rebuilt"
                ),
                "cache_status": table_cache_status,
                "warm_start_status": "safe_fallback_no_cross_replan_mapper",
                "warm_start_values_applied": 0,
                "pyomo_model_rebuilt": True,
            }
        )

    gate = _stage_gate(build_audits, invalid_rows_used_count)
    report = {
        "run_id": resolved_run_id,
        "mode": MODE_ID,
        "timestamp_utc": iso_utc(timestamp),
        "git_commit": resolve_git_commit(REPO_ROOT),
        "input_directory": repo_rel(input_path, REPO_ROOT),
        "s4_4b_validation_decision": validation_result["decision"],
        "policy_mode": POLICY_MODE,
        "static_price_regression": True,
        "horizon_hours_override": horizon_hours_override,
        "target_multiplier": target_multiplier,
        "target_multiplier_by_configuration": dict(
            target_multiplier_by_configuration or {}
        ),
        "fix_c0_binary_schedule": fix_c0_binary_schedule,
        "enable_minimal_wag_layer": enable_minimal_wag_layer,
        "enable_c1_retained_bf_bof_route": enable_c1_retained_bf_bof_route,
        "enable_internal_wag_power": enable_internal_wag_power,
        "development_controller_activation": development_controller_activation,
        "hsm_rolling_electricity_mwh_per_t_hrc_override": hsm_rolling_electricity_mwh_per_t_hrc_override,
        "generator_interface_cap_mode": generator_interface_cap_mode,
        "generator_unit_interface_active": generator_unit_interface is not None,
        "c1_energy_boundary_active": c1_energy_boundary is not None,
        "c1_energy_boundary": dict(c1_energy_boundary or {}),
        "linde_n2_auxiliary_electricity_mwh_h": linde_n2_auxiliary_electricity_mwh_h,
        "site_background_electricity_mwh_h": site_background_electricity_mwh_h,
        "site_background_electricity_mwh_h_by_configuration": dict(
            resolved_site_background_by_configuration
        ),
        "site_baseload_ng_mwh_h_by_configuration": dict(
            resolved_site_baseload_ng_by_configuration
        ),
        "site_residual_steam_t_h_by_configuration": dict(
            resolved_site_residual_steam_by_configuration
        ),
        "site_residual_direct_co2_t_h_by_configuration": dict(
            resolved_site_residual_co2_by_configuration
        ),
        "wag_generation_yield_overrides_by_configuration": wag_yield_overrides,
        "bf_electricity_intensity_scale_by_configuration": resolved_bf_electricity_scales,
        "c0_aggregate_generator_technical_interface": dict(
            c0_aggregate_generator_technical_interface or {}
        ),
        "c0_full_site_energy_bridge": dict(c0_full_site_energy_bridge or {}),
        **(
            {
                "c0_electricity_sale_sensitivity": {
                    key: value
                    for key, value in dict(c0_electricity_sale_sensitivity).items()
                    if key != "sale_price_eur_by_hour"
                }
            }
            if c0_electricity_sale_sensitivity is not None
            else {}
        ),
        **(
            {
                "c0_allocation_envelope_diagnostic": dict(
                    c0_allocation_envelope_diagnostic
                )
            }
            if c0_allocation_envelope_diagnostic is not None
            else {}
        ),
        "eaf_secondary_electricity_mwh_per_t_ls_override": eaf_secondary_electricity_mwh_per_t_ls_override,
        "dsp_electricity_mwh_per_t_coil_override": dsp_electricity_mwh_per_t_coil_override,
        "external_procurement_flow_coefficients": dict(
            external_procurement_flow_coefficients or {}
        ),
        "deterministic_cost_policy_active": deterministic_cost_policy is not None,
        "daily_production_guardrail": daily_production_guardrail,
        "rolling_production_deadline_targets_t": dict(rolling_production_deadline_targets_t or {}),
        "rolling_production_deadline_targets_by_configuration_t": {
            configuration: dict(targets)
            for configuration, targets in (
                rolling_production_deadline_targets_by_configuration_t or {}
            ).items()
        },
        "rolling_production_progress_target_by_configuration_t": dict(
            rolling_production_progress_target_by_configuration_t or {}
        ),
        "rolling_production_execution_block_hours": rolling_production_execution_block_hours,
        "rolling_production_hard_exact_execution_target": rolling_production_hard_exact_execution_target,
        "rolling_production_exact_deadline_hour": rolling_production_exact_deadline_hour,
        "final_product_requirement_sense": (
            "cumulative_quota_lower_bound"
            if rolling_production_deadline_targets_t is not None
            or rolling_production_deadline_targets_by_configuration_t is not None
            else "exact_target"
        ),
        "initial_inventory_overrides_by_configuration": {
            key: dict(value) for key, value in (initial_inventory_overrides_by_configuration or {}).items()
        },
        "rolling_terminal_inventory_hour": rolling_terminal_inventory_hour,
        "rolling_terminal_inventory_bounds_by_configuration": {
            key: dict(value)
            for key, value in (
                rolling_terminal_inventory_bounds_by_configuration or {}
            ).items()
        },
        "fix_c1_hybrid_schedule": fix_c1_hybrid_schedule,
        "c1_retained_route_policy": c1_retained_route_policy,
        "commitment_granularity": commitment_granularity,
        "solver_time_limit_seconds": solver_time_limit_seconds,
        "c0_continuous_must_run_activities": sorted(c0_continuous_must_run_activities or ()),
        "c0_downstream_reference_routing_active": c0_downstream_reference_routing is not None,
        "c1_continuous_must_run_activities": sorted(continuous_must_run_activities or ()),
        "c0_coke_chain_reconciliation": dict(c0_coke_chain_reconciliation or {}),
        "c1_coke_chain_reconciliation": dict(c1_coke_chain_reconciliation or {}),
        "downstream_origin_routing": dict(downstream_origin_routing or {}),
        "hourly_da_price_taking_active": False,
        "bidding_active": False,
        "stochastic_active": False,
        "oracle_active": False,
        "forbidden_terms_active": {
            "product_revenue": False,
            "export_revenue": False,
            "grid_tariffs": False,
            "direct_WAG_market_valuation": False,
            "CO2_ETS_objective": False,
        },
        "configuration_build_audit": build_audits,
        "constraint_audit": constraint_audits,
        "performance": {
            "schema_version": "optimisation_performance_v1",
            "performance_mode": performance_mode_value,
            "structural_signature": structural_signature.digest,
            "model_reuse_status": (
                "static_input_and_structure_cache_hit_pyomo_rebuilt"
                if table_cache_status == "hit" and template_cache_status == "hit"
                else "static_input_or_structure_registered_pyomo_rebuilt"
            ),
            "input_validation_cache_status": validation_cache_status,
            "input_table_cache_status": table_cache_status,
            "structural_template_cache_status": template_cache_status,
            "warm_start_status": "safe_fallback_no_cross_replan_mapper",
            "warm_start_values_applied": 0,
            "pyomo_model_rebuilt": True,
            "input_resolution_seconds": input_resolution_seconds,
        },
        "blocker_rows_preserved": len(blocker_rows),
        "stage_gate": gate,
        "runtime_seconds": round(time.perf_counter() - start, 6),
        "caveat": "Unified S4.4c physical regression uses only executable development rows. Missing deferred validation and reporting rows are not used as constraints or objective inputs.",
    }

    if write_report:
        destination = S44C_DIR if report_dir is None else Path(report_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        write_json(destination / DEFAULT_REPORT_JSON_PATH.name, report)
        _write_csv(destination / DEFAULT_REPORT_CSV_PATH.name, _report_rows(build_audits))
        _write_csv(destination / DEFAULT_BUILD_AUDIT_CSV_PATH.name, build_audits)
        _write_csv(destination / DEFAULT_CONSTRAINT_AUDIT_CSV_PATH.name, constraint_audits)
        _write_csv(destination / DEFAULT_HOURLY_CSV_PATH.name, hourly_rows)
        write_json(destination / DEFAULT_STAGE_GATE_JSON_PATH.name, gate)
        _write_csv(destination / DEFAULT_STAGE_GATE_CSV_PATH.name, [gate])

    return {
        **report,
        "hourly_rows": hourly_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run S4.4c unified physical static regression.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--solver-time-limit-seconds", type=float, default=None)
    args = parser.parse_args(argv)
    report = run_s44c_unified_physical_regression(run_id=args.run_id, write_report=True, solver_time_limit_seconds=args.solver_time_limit_seconds)
    print(
        json.dumps(
            {
                "decision": report["stage_gate"]["decision"],
                "may_proceed_to_s4_4d": report["stage_gate"]["may_proceed_to_s4_4d"],
                "c0_status": report["stage_gate"]["c0_status"],
                "c1_status": report["stage_gate"]["c1_status"],
                "configuration_count": len(report["configuration_build_audit"]),
                "blocker_rows_preserved": report["blocker_rows_preserved"],
            },
            indent=2,
        )
    )
    return 0 if report["stage_gate"]["may_proceed_to_s4_4d"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
