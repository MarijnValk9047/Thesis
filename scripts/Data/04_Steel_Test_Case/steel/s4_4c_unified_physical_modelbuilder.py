"""S4.4c unified C0/C1 physical modelbuilder smoke regression.

This stage validates that the S4.4b input layer can drive a common physical
model interface. It intentionally does not implement DA price-taking.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
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

from .model import collect_model_stats
from .reporting import iso_utc, now_utc, repo_rel, resolve_git_commit, write_json
from .s4_0b_guardrail_regression_runner import _mip_gap
from .s4_4b_unified_input_validator import (
    validate_unified_dev_inputs,
    write_validation_outputs,
)
from .s4_4b5a_asymmetric_correction import CORRECTED_INPUT_DIR
from .wag_milp_input_contract import load_governed_wag_factor_maps
from .wag_development_controller_contract import (
    DevelopmentControllerProfile,
    bf_hot_stove_mwh_per_t_hot_metal,
    hsm_reheat_mwh_per_t_hrc,
    hsm_rolling_electricity_mwh_per_t_hrc,
    load_development_controller_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
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


def _load_tables(input_dir: Path = S44B_INPUT_DIR) -> UnifiedInputTables:
    table_names = (
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
    return UnifiedInputTables(
        input_dir=input_dir,
        tables={table_name: _read_csv(input_dir / table_name) for table_name in table_names},
    )


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


def _audit_loaded_incumbent(model: ConcreteModel, *, tolerance: float = 1e-6) -> dict[str, Any]:
    """Audit the currently loaded incumbent against the complete active model."""

    max_constraint_violation = 0.0
    max_bound_violation = 0.0
    max_integrality_violation = 0.0
    constraint_count = 0
    variable_count = 0
    discrete_count = 0
    undefined_value_count = 0
    for variable in model.component_data_objects(Var, active=True):
        variable_count += 1
        current = variable.value
        if current is None:
            undefined_value_count += 1
            continue
        current = float(current)
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
            max_integrality_violation = max(
                max_integrality_violation, abs(current - round(current))
            )
    for constraint in model.component_data_objects(Constraint, active=True):
        constraint_count += 1
        try:
            body = float(value(constraint.body))
        except (TypeError, ValueError):
            undefined_value_count += 1
            continue
        if constraint.lower is not None:
            max_constraint_violation = max(
                max_constraint_violation,
                float(value(constraint.lower)) - body,
            )
        if constraint.upper is not None:
            max_constraint_violation = max(
                max_constraint_violation,
                body - float(value(constraint.upper)),
            )
    max_constraint_violation = max(0.0, max_constraint_violation)
    max_bound_violation = max(0.0, max_bound_violation)
    return {
        "constraint_count": constraint_count,
        "variable_count": variable_count,
        "discrete_variable_count": discrete_count,
        "undefined_value_count": undefined_value_count,
        "max_constraint_violation": max_constraint_violation,
        "max_variable_bound_violation": max_bound_violation,
        "max_integrality_violation": max_integrality_violation,
        "tolerance": tolerance,
        "feasible": (
            undefined_value_count == 0
            and max_constraint_violation <= tolerance
            and max_bound_violation <= tolerance
            and max_integrality_violation <= tolerance
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
) -> None:
    """Persist the first endpoint failure without performing another solve."""

    raw_directory = diagnostic.get("failure_evidence_directory")
    if not raw_directory:
        return
    directory = Path(str(raw_directory)).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stats = collect_model_stats(model)
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
        "solver_best_bound": getattr(result.problem, "lower_bound", None),
        "primary_cost_objective_eur": primary_cost,
        "primary_cost_best_bound_eur": primary_best_bound,
        "variable_count": stats.variables,
        "binary_count": stats.binaries,
        "constraint_count": stats.constraints,
        "normal_snapshot": dict(normal_snapshot),
        "diagnostic_solver_options": {
            "DualReductions": 0,
            "InfUnbdInfo": 1,
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
    allocation_envelope_diagnostic: Mapping[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Solve physical progress, represented cost and tie-breaker in order."""

    progress_active = hasattr(model, "rolling_production_progress_objective")
    metadata = {
        "cost_objective_active": deterministic_cost_policy is not None,
        "primary_cost_objective_eur": None,
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
    }

    cost_objective = None
    flows: list[Mapping[str, Any]] = []
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
        model.represented_procurement_cost_eur = Expression(expr=sum(cost_terms))
        model.deterministic_procurement_cost_objective = Objective(
            expr=model.represented_procurement_cost_eur,
            sense=minimize,
        )
        cost_objective = model.deterministic_procurement_cost_objective
        cost_objective.deactivate()
        metadata["priced_flow_count"] = len(flows)

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
            return primary_result, metadata
        optimum = float(value(model.represented_procurement_cost_eur))
        tolerance = float(deterministic_cost_policy["objective_tolerance_eur"])
        if tolerance < 0.0:
            raise S44CModelBuilderError("Cost-objective tolerance cannot be negative.")
        metadata["primary_cost_objective_eur"] = optimum
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
    if str(tie_result.solver.termination_condition).lower() in {
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
    execution_hours = int(
        allocation_envelope_diagnostic.get(
            "execution_hours",
            getattr(model, "rolling_production_progress_execution_hours", 0),
        )
    )
    state_tolerance = float(
        allocation_envelope_diagnostic.get("state_tolerance", 1e-6)
    )
    if (
        execution_hours <= 0
        or execution_hours > len(model.TIME)
        or state_tolerance <= 0.0
    ):
        raise S44CModelBuilderError(
            "Invalid allocation-envelope execution hours or state tolerance."
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
        if max_local_normal_schedule_residual > state_tolerance + 1e-6:
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
    if normal_cost_minus_upper_limit > 1e-6:
        raise S44CModelBuilderError(
            "The normal tie-break incumbent is not feasible for the allocation "
            "endpoint formulations: "
            f"normal_cost_eur={normal_cost}, primary_cost_eur={primary_cost}, "
            f"upper_tolerance_eur={cost_tolerance}."
        )

    def _snapshot_hash(snapshot: Mapping[str, float]) -> str:
        normalized = {
            key: round(float(snapshot[key]), 6) for key in sorted(snapshot)
        }
        return hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

    model.static_price_naive_objective.deactivate()
    model.allocation_envelope_state_preservation = ConstraintList()
    state_expressions = {
        "executed_final_product_t": sum(
            model.final_product_output[t] for t in range(execution_hours)
        ),
        "coke_inventory_t": model.coke_inventory[handoff_hour],
        "sinter_inventory_t": model.sinter_inventory[handoff_hour],
        "hot_iron_inventory_t": model.hot_iron_inventory[handoff_hour],
        "cold_slab_inventory_t": model.cold_slab_inventory[handoff_hour],
    }
    for key, expression in state_expressions.items():
        normal_value = normal_snapshot[key]
        model.allocation_envelope_state_preservation.add(
            expression >= normal_value - state_tolerance
        )
        model.allocation_envelope_state_preservation.add(
            expression <= normal_value + state_tolerance
        )
    endpoint_expression = sum(
        model.wag_generator_electricity_mwh[t]
        for t in range(execution_hours)
    )
    model.allocation_envelope_objective = Objective(
        expr=endpoint_expression,
        sense=minimize if endpoint == "min" else maximize,
    )
    normal_incumbent_audit = _audit_loaded_incumbent(
        model, tolerance=state_tolerance + 1e-6
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
    normal_incumbent_audit["production_and_state_preservation_present"] = (
        len(model.allocation_envelope_state_preservation)
        == 2 * len(state_expressions)
    )
    normal_incumbent_audit["objective_definition_valid"] = (
        objective_definition_valid
    )
    normal_incumbent_audit["feasible"] = bool(
        normal_incumbent_audit["feasible"]
        and normal_incumbent_audit["cost_cap_present"]
        and normal_incumbent_audit["production_and_state_preservation_present"]
        and objective_definition_valid
    )
    if not normal_incumbent_audit["feasible"]:
        raise S44CModelBuilderError(
            "The complete saved-normal incumbent feasibility audit failed: "
            f"{normal_incumbent_audit}."
        )
    solver_name = str(getattr(solver, "name", "")).lower()
    if "gurobi" in solver_name:
        solver.options["DualReductions"] = 0
        solver.options["InfUnbdInfo"] = 1
        failure_directory = allocation_envelope_diagnostic.get(
            "failure_evidence_directory"
        )
        if failure_directory:
            Path(str(failure_directory)).resolve().mkdir(
                parents=True, exist_ok=True
            )
            solver.options["LogFile"] = str(
                Path(str(failure_directory)).resolve()
                / "endpoint_solver.log"
            )
    endpoint_start = time.perf_counter()
    endpoint_result = solver.solve(model)
    endpoint_runtime = time.perf_counter() - endpoint_start
    endpoint_termination = str(endpoint_result.solver.termination_condition)
    if endpoint_termination.lower() != "optimal":
        _preserve_allocation_endpoint_failure(
            model,
            endpoint_result,
            allocation_envelope_diagnostic,
            endpoint=endpoint,
            normal_snapshot=normal_snapshot,
            primary_cost=primary_cost,
            primary_best_bound=metadata["primary_cost_best_bound_eur"],
        )
        raise S44CModelBuilderError(
            "Allocation-envelope endpoint did not terminate optimal: "
            f"{endpoint_termination}."
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
        "pass"
        if endpoint_minus_primary_best_bound is not None
        and endpoint_minus_primary_best_bound >= 0.0
        else "unavailable"
        if best_bound_availability != "available"
        else "fail"
    )
    primary_objective_audit_status = (
        "pass"
        if endpoint_cost
        <= primary_cost + cost_tolerance + solver_cost_feasibility_tolerance
        else "fail"
    )
    solver_state_feasibility_tolerance = (
        1e-6 if "gurobi" in str(getattr(solver, "name", "")).lower() else 0.0
    )
    effective_state_tolerance = (
        state_tolerance + solver_state_feasibility_tolerance
    )
    if (
        max_state_residual > effective_state_tolerance + 1e-9
        or endpoint_cost > primary_cost + cost_tolerance + 1e-6
        or best_bound_audit_status != "pass"
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
    metadata.update(
        {
            "allocation_envelope_active": True,
            "allocation_envelope_endpoint": endpoint,
            "allocation_envelope_execution_hours": execution_hours,
            "allocation_envelope_objective_value_mwh": float(
                value(endpoint_expression)
            ),
            "allocation_envelope_runtime_seconds": endpoint_runtime,
            "allocation_envelope_solver_status": str(
                endpoint_result.solver.status
            ),
            "allocation_envelope_termination_condition": endpoint_termination,
            "allocation_envelope_mip_gap": _mip_gap(endpoint_result),
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
    model.rolling_production_progress_identity = Constraint(
        expr=(
            sum(
                model.final_product_output[t]
                for t in range(execution_block_hours)
            )
            - float(next_execution_target_t)
            == model.rolling_production_progress_surplus_t
            - model.rolling_production_progress_deficit_t
        )
    )
    executed_output = sum(
        model.final_product_output[t] for t in range(execution_block_hours)
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
    lower = float(band["lower_t"])
    upper = float(band["upper_t"])
    if not 0.0 <= lower <= upper:
        raise S44CModelBuilderError(
            f"Reference band {constraint_id} must satisfy 0 <= lower <= upper."
        )
    setattr(model, f"{constraint_id}_lower", Constraint(expr=expression >= lower))
    setattr(model, f"{constraint_id}_upper", Constraint(expr=expression <= upper))


def _add_reference_cumulative_deadline_bands(
    model: ConcreteModel,
    *,
    constraint_prefix: str,
    hourly_expressions: Mapping[str, Any],
    bands: Mapping[str, Mapping[str, float]],
    deadline_hours: Collection[int],
    horizon_hours: int,
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
        for deadline in deadlines:
            scale = deadline / horizon_hours
            cumulative = sum(component[t] for t in range(deadline))
            setattr(
                model,
                f"{constraint_prefix}_{band_id}_{deadline}h_lower",
                Constraint(expr=cumulative >= lower * scale),
            )
            setattr(
                model,
                f"{constraint_prefix}_{band_id}_{deadline}h_upper",
                Constraint(expr=cumulative <= upper * scale),
            )


def _add_day_commitment_layer(
    model: ConcreteModel,
    *,
    horizon_hours: int,
    commitment_definitions: Mapping[str, tuple[str, str, float]],
    commitment_day_lengths: Collection[int] | None = None,
) -> None:
    """Use one daily plant-commitment binary while retaining hourly throughput.

    This is a tractable development abstraction for a price-free quota model:
    it selects plant availability from physical demand without prescribing
    operating hours. Existing hourly maximum capacities remain binding.
    """
    day_lengths = (
        [int(value) for value in commitment_day_lengths]
        if commitment_day_lengths is not None
        else [24] * (horizon_hours // 24)
    )
    if (
        not day_lengths
        or sum(day_lengths) != horizon_hours
        or any(value not in {23, 24, 25} for value in day_lengths)
    ):
        raise S44CModelBuilderError(
            "Daily commitment requires complete 23/24/25-hour local delivery days."
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
                >= minimum_rate * getattr(m, day_on_name)[d],
            ),
        )


def _add_c0_minimal_wag_layer(
    model: ConcreteModel,
    inputs: C0ExecutableInputs | RetainedBfBofInputs,
    *,
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
    kgf_underfiring_activity_rule: Any | None = None,
    kgf_underfiring_activity_rule_kgf2: Any | None = None,
    hsm_carrier_precedence: Collection[str] | None = None,
    hsm_eligible_carriers: Collection[str] | None = None,
    generator_interface_cap_mode: str = "inherited_profile",
    generator_unit_interface: Mapping[str, Any] | None = None,
    aggregate_generator_technical_interface: Mapping[str, Any] | None = None,
    full_site_energy_bridge: Mapping[str, float] | None = None,
    eaf_secondary_electricity_mwh_per_t_ls_override: float | None = None,
    dsp_electricity_mwh_per_t_coil_override: float | None = None,
    hsm_output_activity_rule: Any | None = None,
    dsp_output_activity_rule: Any | None = None,
    bf_hot_metal_activity_rule: Any | None = None,
    bf_electricity_intensity_scale: float = 1.0,
) -> None:
    lhv_mj_per_nm3, combustion_t_per_mwh = load_governed_wag_factor_maps()
    bf_hot_stove_mwh_per_t_hm = bf_hot_stove_mwh_per_t_hot_metal()
    if linde_n2_auxiliary_electricity_mwh_h < 0.0:
        raise S44CModelBuilderError("Linde N2 auxiliary electricity must be non-negative.")
    if site_background_electricity_mwh_h < 0.0:
        raise S44CModelBuilderError("Site background electricity must be non-negative.")
    if eaf_secondary_electricity_mwh_per_t_ls_override is not None and eaf_secondary_electricity_mwh_per_t_ls_override < 0.0:
        raise S44CModelBuilderError("EAF secondary-electricity override must be non-negative.")
    if dsp_electricity_mwh_per_t_coil_override is not None and dsp_electricity_mwh_per_t_coil_override < 0.0:
        raise S44CModelBuilderError("DSP electricity override must be non-negative.")
    if bf_electricity_intensity_scale <= 0.0:
        raise S44CModelBuilderError("BF electricity-intensity scale must be positive.")

    # This is a diagnostic allocation *order*, not a gas-mix ratio or a
    # gas-quality model.  Every eligible carrier stays separately balanced.
    # The default preserves the historical BFG-first tie-breaker; callers must
    # opt in explicitly to a different source-backed development case.
    supported_hsm_carriers = ("BFG", "COG", "BOFG", "NG")
    allowed_hsm_carriers = tuple(hsm_eligible_carriers or supported_hsm_carriers)
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
    model.generator_interface_cap_mode = generator_interface_cap_mode
    model.generator_unit_interface_active = generator_unit_interface is not None
    hsm_output_activity = hsm_output_activity_rule or (lambda m, t: m.hot_strip_mill[t])
    dsp_output_activity = dsp_output_activity_rule or (lambda m, t: m.dsp_final_product_output[t])
    bf_hot_metal_activity = bf_hot_metal_activity_rule or (lambda m, t: m.bf6_hot_iron_output[t])

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
    model.bfg_prod_bf6 = Expression(
        model.TIME,
        rule=lambda m, t: inputs.bfg_mwh_per_t_hot_iron * m.bf6_hot_iron_output[t],
    )
    model.bfg_prod_bf7 = Expression(
        model.TIME,
        rule=lambda m, t: inputs.bfg_mwh_per_t_hot_iron * m.bf7_hot_iron_output[t],
    )
    model.bfg_generated = Expression(model.TIME, rule=lambda m, t: m.bfg_prod_bf6[t] + m.bfg_prod_bf7[t])
    model.cog_prod_kgf1 = Expression(
        model.TIME,
        rule=lambda m, t: inputs.cog_mwh_per_t_coke * m.coking_plant_1[t],
    )
    model.cog_prod_kgf2 = Expression(
        model.TIME,
        rule=lambda m, t: inputs.cog_mwh_per_t_coke * m.coking_plant_2[t],
    )
    model.cog_generated = Expression(model.TIME, rule=lambda m, t: m.cog_prod_kgf1[t] + m.cog_prod_kgf2[t])
    model.bofg_prod_bof = Expression(
        model.TIME,
        rule=lambda m, t: inputs.bofg_mwh_per_t_liquid_steel * m.bof_crude_steel_output[t],
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
        rule=lambda m, t: inputs.kgf_underfiring_mwh_per_t_coke * kgf_underfiring_activity(m, t),
    )
    model.cog_to_kgf2 = Expression(
        model.TIME,
        rule=lambda m, t: inputs.kgf_underfiring_mwh_per_t_coke * kgf2_underfiring_activity(m, t),
    )
    model.cog_to_sinter = Expression(
        model.TIME,
        rule=lambda m, t: inputs.sinter_cog_mwh_per_t_sinter * m.sinter_output[t],
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
        model.pefa_pellet_output_t = Expression(model.TIME, rule=lambda _m, _t: development_profile.pefa_pellets_t_h)
        model.bofg_to_pefa_malerij = Var(model.TIME, domain=NonNegativeReals)
        model.cog_to_pefa_branderij = Var(model.TIME, domain=NonNegativeReals)
        model.ng_to_pefa_malerij_mwh = Var(model.TIME, domain=NonNegativeReals)
        model.ng_to_pefa_branderij_mwh = Var(model.TIME, domain=NonNegativeReals)
        model.pefa_malerij_heat_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.bofg_to_pefa_malerij[t] + m.ng_to_pefa_malerij_mwh[t]
            == development_profile.pefa_bofg_mwh_h * _controller_profile_weight("pefa_bofg", int(t)),
        )
        model.pefa_branderij_heat_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.cog_to_pefa_branderij[t] + m.ng_to_pefa_branderij_mwh[t]
            == development_profile.pefa_cog_mwh_h * _controller_profile_weight("pefa_cog", int(t)),
        )
    else:
        model.pefa_pellet_output_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bofg_to_pefa_malerij = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.cog_to_pefa_branderij = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_to_pefa_malerij_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_to_pefa_branderij_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)

    if enable_boiler_scaffold:
        # C5p_b fixes the continuous, existing-modelled 15-bar steam demand
        # and its source-stage fuel requirement. Carrier use remains BFG/COG
        # first with named NG backup; no residual steam or capacity-derived
        # fuel demand is introduced here.
        model.bfg_to_boiler = Var(model.TIME, domain=NonNegativeReals)
        model.cog_to_boiler = Var(model.TIME, domain=NonNegativeReals)
        model.ng_to_boiler_mwh = Var(model.TIME, domain=NonNegativeReals)
        model.boiler_scaffold_fuel_balance = Constraint(
            model.TIME,
            rule=lambda m, t: m.bfg_to_boiler[t] + m.cog_to_boiler[t] + m.ng_to_boiler_mwh[t]
            == development_profile.boiler_fuel_mwh_h,
        )
        model.steam_15bar_demand_t = Expression(
            model.TIME,
            rule=lambda _m, _t: development_profile.boiler_steam_15bar_demand_t_h,
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
    elif retire_legacy_boiler_placeholder:
        model.bfg_to_boiler = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.cog_to_boiler = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.ng_to_boiler_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_demand_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_unserved_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    else:
        model.bfg_to_boiler = Var(model.TIME, domain=NonNegativeReals)
        model.cog_to_boiler = Var(model.TIME, domain=NonNegativeReals)
        model.ng_to_boiler_mwh = Var(model.TIME, domain=NonNegativeReals)
        model.steam_15bar_demand_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_supply_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.steam_15bar_unserved_t = Expression(model.TIME, rule=lambda _m, _t: 0.0)

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
        rule=lambda _m, _t: 0.0213 * development_profile.pefa_pellets_t_h if enable_pefa_controller else 0.0,
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
            + m.eaf_secondary_electricity_mwh[t],
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
            rule=lambda m, t: m.eaf_arc_electricity_mwh[t] if hasattr(m, "eaf_arc_electricity_mwh") else 0.0,
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
    else:
        fixed_ng_mwh_h = 0.0
        flexible_heat_service_mwh_h = 0.0
        normal_case_flexible_ng_reference_mwh_h = 0.0
        model.bfg_to_flexible_other_site_heat = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.cog_to_flexible_other_site_heat = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bofg_to_flexible_other_site_heat = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.flexible_other_site_heat_ng_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.full_site_fixed_ng_component_mwh = Expression(
        model.TIME, rule=lambda _m, _t: fixed_ng_mwh_h
    )
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
    model.full_site_energy_bridge_active = bool(bridge)
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
        model.vn25_electric_capacity_mw = vn25_electric_capacity_mw
        model.generator_operating_mode = str(
            generator_unit_interface["operating_mode"]
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
                <= development_profile.generator_wag_interface_cap_mwh_h,
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


def _build_c0_model(
    inputs: C0ExecutableInputs,
    *,
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
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    external_procurement_flow_coefficients: Mapping[str, float] | None = None,
    bf_electricity_intensity_scale: float = 1.0,
    aggregate_generator_technical_interface: Mapping[str, Any] | None = None,
    full_site_energy_bridge: Mapping[str, float] | None = None,
):
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

    model.bf_sinter_input = Expression(
        model.TIME,
        rule=lambda m, t: m.blast_furnace_6[t] + m.blast_furnace_7[t],
    )
    model.sinter_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.sinter_output_per_t_iron_ore * m.sintering_plant[t],
    )
    model.bf_hot_iron_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.bf_hot_iron_per_t_sinter * m.bf_sinter_input[t],
    )
    model.bf6_hot_iron_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.bf_hot_iron_per_t_sinter * m.blast_furnace_6[t],
    )
    model.bf7_hot_iron_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.bf_hot_iron_per_t_sinter * m.blast_furnace_7[t],
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
    controller_flags = _development_controller_flags(development_controller_activation)
    if development_controller_activation != "none" and not enable_minimal_wag_layer:
        raise S44CModelBuilderError("Development controller activation requires the carrier-specific WAG layer.")
    if enable_minimal_wag_layer:
        _add_c0_minimal_wag_layer(
            model,
            inputs,
            enable_internal_wag_power=enable_internal_wag_power,
            gross_electricity_rule=(
                (lambda m, t: m.development_controller_electricity_mwh[t] + m.electricity_boundary_development_mwh[t])
                if controller_flags["electricity_boundary"]
                else (
                    (lambda _m, _t: C0_SITE_ELECTRICITY_PROXY_MWH_H)
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
            bf_electricity_intensity_scale=bf_electricity_intensity_scale,
            aggregate_generator_technical_interface=aggregate_generator_technical_interface,
            full_site_energy_bridge=full_site_energy_bridge,
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
            )
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
    downstream_origin_routing: Mapping[str, float] | None = None,
    c1_liquid_steel_route_band: Mapping[str, float] | None = None,
    continuous_must_run_activities: Collection[str] | None = None,
    c0_coke_chain_reconciliation: Mapping[str, float] | None = None,
    c1_coke_chain_reconciliation: Mapping[str, float] | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    hsm_carrier_precedence: Collection[str] | None = None,
    hsm_eligible_carriers: Collection[str] | None = None,
    generator_interface_cap_mode: str = "inherited_profile",
    generator_unit_interface: Mapping[str, Any] | None = None,
    c1_energy_boundary: Mapping[str, float] | None = None,
    eaf_secondary_electricity_mwh_per_t_ls_override: float | None = None,
    dsp_electricity_mwh_per_t_coil_override: float | None = None,
    external_procurement_flow_coefficients: Mapping[str, float] | None = None,
    bf_electricity_intensity_scale: float = 1.0,
):
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
        required = {"site_total_scrap_supply_cap_t", "bof_scrap_supply_cap_t", "eaf_scrap_supply_cap_t"}
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
    retained_process_names = tuple(retained.process_limits)
    on_domain = UnitInterval if commitment_granularity == "daily_binary_hourly_throughput" else Binary
    for process_name in retained_process_names:
        setattr(model, process_name, Var(model.TIME, domain=NonNegativeReals))
        setattr(model, f"{process_name}_on", Var(model.TIME, domain=on_domain))

    model.drp_pellet_input = Var(model.TIME, domain=NonNegativeReals)
    model.drp_on = Var(model.TIME, domain=on_domain)
    model.eaf_dri_input = Var(model.TIME, domain=NonNegativeReals)
    model.eaf_on = Var(model.TIME, domain=on_domain)
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
    model.bf_sinter_input = Expression(model.TIME, rule=lambda m, t: m.blast_furnace_6[t])
    model.sinter_output = Expression(
        model.TIME,
        rule=lambda m, t: retained.sinter_output_per_t_iron_ore * m.sintering_plant[t],
    )
    model.bf6_hot_iron_output = Expression(
        model.TIME,
        rule=lambda m, t: retained.bf_hot_iron_per_t_sinter * m.blast_furnace_6[t],
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
    model.drp_dri_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.drp_yield_t_dri_per_t_pellets * m.drp_pellet_input[t],
    )
    if eaf_material_balance is None:
        model.eaf_liquid_steel_output = Expression(
            model.TIME,
            rule=lambda m, t: inputs.eaf_yield_t_final_per_t_dri * m.eaf_dri_input[t],
        )
        model.scrap_t = Expression(
            model.TIME,
            rule=lambda m, t: inputs.eaf_scrap_t_per_t_dri * m.eaf_dri_input[t],
        )
    else:
        hdri_per_t_ls = float(eaf_material_balance["hdri_t_per_t_liquid_steel"])
        scrap_per_t_ls = float(eaf_material_balance["scrap_t_per_t_liquid_steel"])
        scrap_supply_cap_t = float(eaf_material_balance.get("scrap_supply_cap_t", 0.0))
        if hdri_per_t_ls <= 0.0 or scrap_per_t_ls < 0.0 or (scrap_supply_ledger is None and scrap_supply_cap_t < 0.0):
            raise S44CModelBuilderError("C1 EAF material balance requires non-negative, non-zero HDRI basis values.")
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
    elif bof_material_balance is None:
        model.site_scrap_supply_total_t = Expression(expr=sum(model.scrap_t[t] for t in model.TIME))
    else:
        model.site_scrap_supply_total_t = Expression(
            expr=sum(model.bof_scrap_supply_t[t] + model.scrap_t[t] for t in model.TIME)
        )
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
            rule=lambda m, t: m.hot_strip_mill[t] == m.cold_slab_draw_to_hsm[t] + m.eaf_to_hsm_slab[t] + m.imported_slab_to_hsm[t],
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
            rule=lambda m, t: hsm_final_per_t_slab * m.eaf_to_hsm_slab[t]
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
        rule=lambda m, t: m.drp_electricity_mwh[t] + m.eaf_arc_electricity_mwh[t],
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
        + inputs.eaf_o2_t_per_t_dri * m.eaf_dri_input[t],
    )

    model.drp_off_on_upper = Constraint(
        model.TIME,
        rule=lambda m, t: m.drp_pellet_input[t] <= inputs.drp_max_t_pellets_h * m.drp_on[t],
    )
    model.drp_off_on_lower = Constraint(
        model.TIME,
        rule=lambda m, t: m.drp_pellet_input[t] >= inputs.drp_min_t_pellets_h * m.drp_on[t],
    )
    model.eaf_off_on_upper = Constraint(model.TIME, rule=lambda m, t: m.eaf_dri_input[t] <= inputs.eaf_max_t_dri_h * m.eaf_on[t])
    model.eaf_off_on_lower = Constraint(model.TIME, rule=lambda m, t: m.eaf_dri_input[t] >= inputs.eaf_min_t_dri_h * m.eaf_on[t])

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
    model.coke_capacity = Constraint(model.TIME, rule=lambda m, t: m.coke_inventory[t] <= retained.coke_store_capacity_t)
    model.sinter_capacity = Constraint(model.TIME, rule=lambda m, t: m.sinter_inventory[t] <= retained.sinter_store_capacity_t)
    model.hot_iron_capacity = Constraint(model.TIME, rule=lambda m, t: m.hot_iron_inventory[t] <= retained.hot_iron_store_capacity_t)
    model.cold_slab_capacity = Constraint(model.TIME, rule=lambda m, t: m.cold_slab_inventory[t] <= retained.cold_slab_store_capacity_t)
    model.coke_terminal = Constraint(expr=model.coke_inventory[inputs.horizon_hours - 1] == retained.coke_store_initial_t)
    model.sinter_terminal = Constraint(expr=model.sinter_inventory[inputs.horizon_hours - 1] == retained.sinter_store_initial_t)
    model.hot_iron_terminal = Constraint(expr=model.hot_iron_inventory[inputs.horizon_hours - 1] == retained.hot_iron_store_initial_t)
    model.cold_slab_terminal = Constraint(expr=model.cold_slab_inventory[inputs.horizon_hours - 1] == retained.cold_slab_store_initial_t)

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
            )
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
                **{
                    name: (name, f"{name}_on", retained.process_limits[name][0])
                    for name in retained_process_names
                },
                "drp": ("drp_pellet_input", "drp_on", inputs.drp_min_t_pellets_h),
                "eaf": ("eaf_dri_input", "eaf_on", inputs.eaf_min_t_dri_h),
            },
            commitment_day_lengths=commitment_day_lengths,
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

    controller_flags = _development_controller_flags(development_controller_activation)
    if development_controller_activation != "none" and not enable_minimal_wag_layer:
        raise S44CModelBuilderError("Development controller activation requires the carrier-specific WAG layer.")
    if enable_minimal_wag_layer:
        _add_c0_minimal_wag_layer(
            model,
            retained,
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
            hsm_carrier_precedence=hsm_carrier_precedence,
            hsm_eligible_carriers=hsm_eligible_carriers,
            generator_interface_cap_mode=generator_interface_cap_mode,
            generator_unit_interface=generator_unit_interface,
            eaf_secondary_electricity_mwh_per_t_ls_override=eaf_secondary_electricity_mwh_per_t_ls_override,
            dsp_electricity_mwh_per_t_coil_override=dsp_electricity_mwh_per_t_coil_override,
            bf_electricity_intensity_scale=bf_electricity_intensity_scale,
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

    flare_tiebreaker = 0.0
    controller_tiebreaker = 0.0
    if enable_minimal_wag_layer:
        flare_tiebreaker = 1e-6 * sum(
            model.bfg_flared[t] + model.cog_flared[t] + model.bofg_flared[t]
            for t in model.TIME
        )
    if controller_flags["hsm"]:
        controller_tiebreaker = sum(
            model.hsm_carrier_precedence_penalty[t]
            + 1e-5
            * (
                model.ng_to_pefa_malerij_mwh[t]
                + model.ng_to_pefa_branderij_mwh[t]
                + model.ng_to_boiler_mwh[t]
                + model.generator_named_ng_mwh[t]
            )
            for t in model.TIME
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
    day_commitment_tiebreaker = (
        1e-4
        * sum(
            getattr(model, f"{name}_day_on")[d]
            for name in (*retained_process_names, "drp", "eaf")
            for d in model.COMMITMENT_DAY
        )
        if commitment_granularity == "daily_binary_hourly_throughput"
        else 0.0
    )
    model.static_price_naive_objective = Objective(
        expr=sum(model.eaf_on[t] + model.drp_on[t] for t in model.TIME)
        + sum(getattr(model, f"{name}_on")[t] for name in retained_process_names for t in model.TIME)
        + 1e-8
        * sum(
            model.dri_inventory[t]
            + model.coke_inventory[t]
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


def _build_c1_model(
    inputs: C1ExecutableInputs,
    *,
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
    downstream_origin_routing: Mapping[str, float] | None = None,
    c1_liquid_steel_route_band: Mapping[str, float] | None = None,
    continuous_must_run_activities: Collection[str] | None = None,
    c1_coke_chain_reconciliation: Mapping[str, float] | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    hsm_carrier_precedence: Collection[str] | None = None,
    hsm_eligible_carriers: Collection[str] | None = None,
    generator_interface_cap_mode: str = "inherited_profile",
    generator_unit_interface: Mapping[str, Any] | None = None,
    c1_energy_boundary: Mapping[str, float] | None = None,
    eaf_secondary_electricity_mwh_per_t_ls_override: float | None = None,
    dsp_electricity_mwh_per_t_coil_override: float | None = None,
    external_procurement_flow_coefficients: Mapping[str, float] | None = None,
    bf_electricity_intensity_scale: float = 1.0,
):
    if enable_c1_retained_bf_bof_route:
        return _build_c1_hybrid_model(
            inputs,
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
            downstream_origin_routing=downstream_origin_routing,
            c1_liquid_steel_route_band=c1_liquid_steel_route_band,
            continuous_must_run_activities=continuous_must_run_activities,
            c1_coke_chain_reconciliation=c1_coke_chain_reconciliation,
            linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
            site_background_electricity_mwh_h=site_background_electricity_mwh_h,
            hsm_carrier_precedence=hsm_carrier_precedence,
            hsm_eligible_carriers=hsm_eligible_carriers,
            generator_interface_cap_mode=generator_interface_cap_mode,
            generator_unit_interface=generator_unit_interface,
            c1_energy_boundary=c1_energy_boundary,
            eaf_secondary_electricity_mwh_per_t_ls_override=eaf_secondary_electricity_mwh_per_t_ls_override,
            dsp_electricity_mwh_per_t_coil_override=dsp_electricity_mwh_per_t_coil_override,
            external_procurement_flow_coefficients=external_procurement_flow_coefficients,
            bf_electricity_intensity_scale=bf_electricity_intensity_scale,
        )
    if development_controller_activation != "none":
        raise S44CModelBuilderError("Development WAG controllers require the retained C1 BF-BOF route.")
    model = ConcreteModel()
    model.TIME = RangeSet(0, inputs.horizon_hours - 1)
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
    commitment_granularity: str = "hourly_binary",
    commitment_day_lengths: Collection[int] | None = None,
    solver_time_limit_seconds: float | None = None,
    continuous_must_run_activities: Collection[str] | None = None,
    c0_coke_chain_reconciliation: Mapping[str, float] | None = None,
    c0_fixed_schedule_hours_by_process: Mapping[str, Collection[int]] | None = None,
    c0_downstream_reference_routing: Mapping[str, Any] | None = None,
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    external_procurement_flow_coefficients: Mapping[str, float] | None = None,
    deterministic_cost_policy: Mapping[str, Any] | None = None,
    wag_generation_yield_overrides: Mapping[str, float] | None = None,
    bf_electricity_intensity_scale: float = 1.0,
    aggregate_generator_technical_interface: Mapping[str, Any] | None = None,
    full_site_energy_bridge: Mapping[str, float] | None = None,
    allocation_envelope_diagnostic: Mapping[str, Any] | None = None,
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
        external_procurement_flow_coefficients=external_procurement_flow_coefficients,
        bf_electricity_intensity_scale=bf_electricity_intensity_scale,
        aggregate_generator_technical_interface=aggregate_generator_technical_interface,
        full_site_energy_bridge=full_site_energy_bridge,
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
            allocation_envelope_diagnostic=allocation_envelope_diagnostic,
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
                    "allocation_envelope_execution_hours",
                    "allocation_envelope_objective_value_mwh",
                    "allocation_envelope_runtime_seconds",
                    "allocation_envelope_solver_status",
                    "allocation_envelope_termination_condition",
                    "allocation_envelope_mip_gap",
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
                "full_site_energy_bridge_named_ng_mwh": _costed_c0_ng_reporting_value(
                    float(value(model.full_site_energy_bridge_named_ng_mwh[t]))
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
                "steam_15bar_supply_t": round(float(value(model.steam_15bar_supply_t[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "steam_15bar_unserved_t": round(float(value(model.steam_15bar_unserved_t[t])), 6)
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
                "flaring_co2_diagnostic_cost_eur": round(float(value(model.flaring_co2_diagnostic_cost_eur[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "oxygen_t": "",
                "total_static_cost": 0.0,
                "caveat": "C0 static BF-BOF physical regression; controlled development assumptions only.",
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
    linde_n2_auxiliary_electricity_mwh_h: float = 0.0,
    site_background_electricity_mwh_h: float = 0.0,
    eaf_secondary_electricity_mwh_per_t_ls_override: float | None = None,
    dsp_electricity_mwh_per_t_coil_override: float | None = None,
    external_procurement_flow_coefficients: Mapping[str, float] | None = None,
    deterministic_cost_policy: Mapping[str, Any] | None = None,
    wag_generation_yield_overrides: Mapping[str, float] | None = None,
    bf_electricity_intensity_scale: float = 1.0,
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
        linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
        site_background_electricity_mwh_h=site_background_electricity_mwh_h,
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
        "EAF_NG_mwh": round(sum(_model_value_or_zero(model, "eaf_named_ng_mwh", t) for t in model.TIME), 6),
        "natural_gas_boiler_mwh": round(sum(float(value(model.ng_to_boiler_mwh[t])) for t in model.TIME), 6),
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
    c0_full_site_energy_bridge: Mapping[str, float] | None = None,
    c0_allocation_envelope_diagnostic: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    timestamp = now_utc()
    resolved_run_id = run_id or f"{MODE_ID}_{timestamp.strftime('%Y%m%d_%H%M%S')}"
    input_path = Path(input_dir)
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
    wag_yield_overrides = dict(wag_generation_yield_overrides_by_configuration or {})
    bf_electricity_scales = dict(bf_electricity_intensity_scale_by_configuration or {})
    unknown_overlay_configurations = (
        set(wag_yield_overrides) | set(bf_electricity_scales)
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
    validation_result = validate_unified_dev_inputs(input_path)
    write_validation_outputs(validation_result, input_path)
    if validation_result["failure_count"] != 0:
        raise S44CModelBuilderError("S4.4b input validation must pass before S4.4c model construction.")

    tables = _load_tables(input_path)
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
            allocation_envelope_diagnostic=c0_allocation_envelope_diagnostic,
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
        linde_n2_auxiliary_electricity_mwh_h=linde_n2_auxiliary_electricity_mwh_h,
        site_background_electricity_mwh_h=resolved_site_background_by_configuration[
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
    )
    build_audits.append(c1_audit)
    constraint_audits.extend(c1_constraints)
    hourly_rows.extend(c1_hourly)

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
        "wag_generation_yield_overrides_by_configuration": wag_yield_overrides,
        "bf_electricity_intensity_scale_by_configuration": resolved_bf_electricity_scales,
        "c0_aggregate_generator_technical_interface": dict(
            c0_aggregate_generator_technical_interface or {}
        ),
        "c0_full_site_energy_bridge": dict(c0_full_site_energy_bridge or {}),
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
        "blocker_rows_preserved": len(blocker_rows),
        "stage_gate": gate,
        "runtime_seconds": round(time.perf_counter() - start, 6),
        "caveat": "Unified S4.4c physical regression uses only executable development rows. Missing deferred validation and reporting rows are not used as constraints or objective inputs.",
    }

    if write_report:
        S44C_DIR.mkdir(parents=True, exist_ok=True)
        write_json(DEFAULT_REPORT_JSON_PATH, report)
        _write_csv(DEFAULT_REPORT_CSV_PATH, _report_rows(build_audits))
        _write_csv(DEFAULT_BUILD_AUDIT_CSV_PATH, build_audits)
        _write_csv(DEFAULT_CONSTRAINT_AUDIT_CSV_PATH, constraint_audits)
        _write_csv(DEFAULT_HOURLY_CSV_PATH, hourly_rows)
        write_json(DEFAULT_STAGE_GATE_JSON_PATH, gate)
        _write_csv(DEFAULT_STAGE_GATE_CSV_PATH, [gate])

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
