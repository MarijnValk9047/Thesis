"""S4.4c unified C0/C1 physical modelbuilder smoke regression.

This stage validates that the S4.4b input layer can drive a common physical
model interface. It intentionally does not implement DA price-taking.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyomo.environ import (
    Binary,
    ConcreteModel,
    Constraint,
    Expression,
    NonNegativeReals,
    Objective,
    RangeSet,
    SolverFactory,
    Var,
    minimize,
    value,
)

from .model import collect_model_stats
from .reporting import iso_utc, now_utc, repo_rel, resolve_git_commit, write_json
from .s4_0b_guardrail_regression_runner import _mip_gap
from .s4_4b_unified_input_validator import (
    INPUT_DIR as S44B_INPUT_DIR,
    validate_unified_dev_inputs,
    write_validation_outputs,
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

CONFIGURATIONS = (
    "C0_current_BF_BOF_reference",
    "C1_phase1_BF_BOF_plus_DRP_EAF",
)
EXECUTABLE_STATUSES = {"development_only", "selected_development_input_candidate"}
POLICY_MODE = "price_naive_static_or_cost_smoothed"
MODE_ID = "s4_4c_unified_physical_static_regression"
TOLERANCE = 1e-6
SOLVER_PREFERENCE = ("appsi_highs", "highs", "cbc", "glpk")
MJ_PER_MWH = 3600.0
PJ_TO_MWH = 277777.77777777775
SELECTED_WAG_LHV_MJ_PER_NM3 = {
    "BFG": 3.85,
    "COG": 18.5,
    "BOFG": 8.6,
}
KGF_UNDERFIRING_MWH_PER_T_COKE = 3.5 / 3.6
SINTER_COG_MWH_PER_T_SINTER = 0.10 / 3.6
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
FLARE_CO2_EF_T_PER_MWH = {
    "BFG": 0.75,
    "COG": 0.20,
    "BOFG": 0.70,
}
FLARING_CO2_DIAGNOSTIC_EUR_PER_T = 75.0
FORBIDDEN_TERMS = {
    "product_revenue",
    "export_revenue",
    "grid_tariff",
    "WAG_direct_market_value",
    "CO2_ETS",
}


class S44CModelBuilderError(ValueError):
    """Raised when S4.4c inputs or model construction are invalid."""


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
    return coefficient * SELECTED_WAG_LHV_MJ_PER_NM3[carrier] / MJ_PER_MWH


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
) -> float:
    row = _first_row(
        rows,
        process_id=process_id,
        input_material=input_material,
        output_material=output_material,
    )
    if not _is_executable(row):
        raise S44CModelBuilderError(f"Coefficient row for {process_id} is not executable.")
    return _as_float(row["coefficient"], field_name=f"{process_id} coefficient")


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
        bf_hot_iron_per_t_sinter=_numeric_coefficient(
            io_rows,
            process_id="blast_furnace_6",
            input_material="sinter",
            output_material="hot_iron",
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
        bf_hot_iron_per_t_sinter=_numeric_coefficient(
            io_rows,
            process_id="blast_furnace_6",
            input_material="sinter",
            output_material="hot_iron",
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
) -> None:
    if inputs.horizon_hours % 24 != 0:
        raise S44CModelBuilderError("Fixed C0 binary schedule requires a full-day horizon.")
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


def _add_c0_minimal_wag_layer(
    model: ConcreteModel,
    inputs: C0ExecutableInputs | RetainedBfBofInputs,
    *,
    enable_internal_wag_power: bool = False,
    gross_electricity_rule: Any | None = None,
) -> None:
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
        rule=lambda m, t: inputs.bofg_mwh_per_t_liquid_steel * m.basic_oxygen_furnace[t],
    )
    model.bofg_generated = Expression(model.TIME, rule=lambda m, t: m.bofg_prod_bof[t])

    model.bfg_to_kgf1 = Expression(
        model.TIME,
        rule=lambda m, t: 0.5 * inputs.kgf_underfiring_mwh_per_t_coke * m.coking_plant_1[t],
    )
    model.cog_to_kgf1 = Expression(
        model.TIME,
        rule=lambda m, t: 0.5 * inputs.kgf_underfiring_mwh_per_t_coke * m.coking_plant_1[t],
    )
    model.cog_to_kgf2 = Expression(
        model.TIME,
        rule=lambda m, t: inputs.kgf_underfiring_mwh_per_t_coke * m.coking_plant_2[t],
    )
    model.cog_to_sinter = Expression(
        model.TIME,
        rule=lambda m, t: inputs.sinter_cog_mwh_per_t_sinter * m.sintering_plant[t],
    )

    model.bfg_to_boiler = Var(model.TIME, domain=NonNegativeReals)
    model.cog_to_boiler = Var(model.TIME, domain=NonNegativeReals)
    model.ng_to_boiler_mwh = Var(model.TIME, domain=NonNegativeReals)
    if enable_internal_wag_power:
        model.bfg_to_vattenfall = Var(model.TIME, domain=NonNegativeReals)
        model.cog_to_vattenfall = Var(model.TIME, domain=NonNegativeReals)
        model.bofg_to_vattenfall = Var(model.TIME, domain=NonNegativeReals)
    else:
        model.bfg_to_vattenfall = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.cog_to_vattenfall = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.bofg_to_vattenfall = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bfg_flared = Var(model.TIME, domain=NonNegativeReals)
    model.cog_flared = Var(model.TIME, domain=NonNegativeReals)
    model.bofg_flared = Var(model.TIME, domain=NonNegativeReals)

    model.bfg_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.bfg_generated[t]
        == m.bfg_to_kgf1[t] + m.bfg_to_boiler[t] + m.bfg_to_vattenfall[t] + m.bfg_flared[t],
    )
    model.cog_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.cog_generated[t]
        == m.cog_to_kgf1[t]
        + m.cog_to_kgf2[t]
        + m.cog_to_sinter[t]
        + m.cog_to_boiler[t]
        + m.cog_to_vattenfall[t]
        + m.cog_flared[t],
    )
    model.bofg_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.bofg_generated[t] == m.bofg_to_vattenfall[t] + m.bofg_flared[t],
    )
    model.boiler_wag_cap = Constraint(
        model.TIME,
        rule=lambda m, t: m.bfg_to_boiler[t] + m.cog_to_boiler[t] <= inputs.boiler_wag_cap_mwh_h,
    )
    model.boiler_fuel_placeholder = Constraint(
        model.TIME,
        rule=lambda m, t: m.bfg_to_boiler[t] + m.cog_to_boiler[t] + m.ng_to_boiler_mwh[t]
        == inputs.boiler_total_placeholder_mwh_h,
    )
    if enable_internal_wag_power:
        model.vattenfall_total_volume_cap = Constraint(
            model.TIME,
            rule=lambda m, t: (
                m.bfg_to_vattenfall[t] / (SELECTED_WAG_LHV_MJ_PER_NM3["BFG"] / MJ_PER_MWH)
                + m.cog_to_vattenfall[t] / (SELECTED_WAG_LHV_MJ_PER_NM3["COG"] / MJ_PER_MWH)
                + m.bofg_to_vattenfall[t] / (SELECTED_WAG_LHV_MJ_PER_NM3["BOFG"] / MJ_PER_MWH)
            )
            <= VATTENFALL_TOTAL_WAG_CAP_NM3_H,
        )
        model.vattenfall_fuel_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.bfg_to_vattenfall[t] + m.cog_to_vattenfall[t] + m.bofg_to_vattenfall[t],
        )
        model.wag_electricity_mwh = Expression(
            model.TIME,
            rule=lambda m, t: WAG_TO_POWER_EFFICIENCY * m.vattenfall_fuel_mwh[t],
        )
        model.gross_electricity_mwh = Expression(
            model.TIME,
            rule=gross_electricity_rule or (lambda _m, _t: 0.0),
        )
        model.no_export_from_wag_generation = Constraint(
            model.TIME,
            rule=lambda m, t: m.wag_electricity_mwh[t] <= m.gross_electricity_mwh[t],
        )
        model.net_grid_import_mwh = Expression(
            model.TIME,
            rule=lambda m, t: m.gross_electricity_mwh[t] - m.wag_electricity_mwh[t],
        )
    else:
        model.vattenfall_fuel_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.wag_electricity_mwh = Expression(model.TIME, rule=lambda _m, _t: 0.0)
        model.gross_electricity_mwh = Expression(model.TIME, rule=gross_electricity_rule or (lambda _m, _t: 0.0))
        model.net_grid_import_mwh = Expression(model.TIME, rule=lambda m, t: m.gross_electricity_mwh[t])
    model.wag_used = Expression(
        model.TIME,
        rule=lambda m, t: m.bfg_to_kgf1[t]
        + m.cog_to_kgf1[t]
        + m.cog_to_kgf2[t]
        + m.cog_to_sinter[t]
        + m.bfg_to_boiler[t]
        + m.cog_to_boiler[t]
        + m.bfg_to_vattenfall[t]
        + m.cog_to_vattenfall[t]
        + m.bofg_to_vattenfall[t],
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
        - m.bfg_to_kgf1[t]
        - m.bfg_to_boiler[t]
        - m.bfg_to_vattenfall[t]
        - m.bfg_flared[t],
    )
    model.cog_balance_residual = Expression(
        model.TIME,
        rule=lambda m, t: m.cog_generated[t]
        - m.cog_to_kgf1[t]
        - m.cog_to_kgf2[t]
        - m.cog_to_sinter[t]
        - m.cog_to_boiler[t]
        - m.cog_to_vattenfall[t]
        - m.cog_flared[t],
    )
    model.bofg_balance_residual = Expression(
        model.TIME,
        rule=lambda m, t: m.bofg_generated[t] - m.bofg_to_vattenfall[t] - m.bofg_flared[t],
    )
    model.bfg_flare_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: FLARE_CO2_EF_T_PER_MWH["BFG"] * m.bfg_flared[t],
    )
    model.cog_flare_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: FLARE_CO2_EF_T_PER_MWH["COG"] * m.cog_flared[t],
    )
    model.bofg_flare_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: FLARE_CO2_EF_T_PER_MWH["BOFG"] * m.bofg_flared[t],
    )
    model.flaring_co2_t = Expression(
        model.TIME,
        rule=lambda m, t: m.bfg_flare_co2_t[t] + m.cog_flare_co2_t[t] + m.bofg_flare_co2_t[t],
    )
    model.flaring_co2_diagnostic_cost_eur = Expression(
        model.TIME,
        rule=lambda m, t: FLARING_CO2_DIAGNOSTIC_EUR_PER_T * m.flaring_co2_t[t],
    )


def _build_c0_model(
    inputs: C0ExecutableInputs,
    *,
    fix_binary_schedule: bool = False,
    enable_minimal_wag_layer: bool = False,
    enable_internal_wag_power: bool = False,
    daily_production_guardrail: bool = False,
):
    model = ConcreteModel()
    model.TIME = RangeSet(0, inputs.horizon_hours - 1)
    process_names = tuple(inputs.process_limits)

    for process_name in process_names:
        setattr(model, process_name, Var(model.TIME, domain=NonNegativeReals))
        setattr(model, f"{process_name}_on", Var(model.TIME, domain=Binary))

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
    model.bof_crude_steel_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.bof_crude_steel_per_t_hot_iron * m.basic_oxygen_furnace[t],
    )
    model.final_product_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.hsm_final_per_t_crude_steel * m.hot_strip_mill[t],
    )
    if enable_minimal_wag_layer:
        _add_c0_minimal_wag_layer(
            model,
            inputs,
            enable_internal_wag_power=enable_internal_wag_power,
            gross_electricity_rule=lambda _m, _t: C0_SITE_ELECTRICITY_PROXY_MWH_H
            if enable_internal_wag_power
            else 0.0,
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
            rule=lambda m, t: inputs.bofg_nm3_per_t_liquid_steel * m.basic_oxygen_furnace[t],
        )
        model.wag_generated = Expression(
            model.TIME,
            rule=lambda m, t: m.bfg_generated[t] + m.cog_generated[t] + m.bofg_generated[t],
        )

    model.coke_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.coke_inventory[t]
        == (inputs.coke_store_initial_t if t == 0 else m.coke_inventory[t - 1])
        + m.coking_plant_1[t]
        + m.coking_plant_2[t]
        - inputs.coke_per_t_sinter * m.bf_sinter_input[t],
    )
    model.sinter_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.sinter_inventory[t]
        == (inputs.sinter_store_initial_t if t == 0 else m.sinter_inventory[t - 1])
        + m.sintering_plant[t]
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
        rule=lambda m, t: m.cold_slab_inventory[t]
        == (inputs.cold_slab_store_initial_t if t == 0 else m.cold_slab_inventory[t - 1])
        + m.bof_crude_steel_output[t]
        - m.hot_strip_mill[t],
    )
    model.coke_capacity = Constraint(model.TIME, rule=lambda m, t: m.coke_inventory[t] <= inputs.coke_store_capacity_t)
    model.sinter_capacity = Constraint(model.TIME, rule=lambda m, t: m.sinter_inventory[t] <= inputs.sinter_store_capacity_t)
    model.hot_iron_capacity = Constraint(model.TIME, rule=lambda m, t: m.hot_iron_inventory[t] <= inputs.hot_iron_store_capacity_t)
    model.cold_slab_capacity = Constraint(model.TIME, rule=lambda m, t: m.cold_slab_inventory[t] <= inputs.cold_slab_store_capacity_t)
    model.coke_terminal = Constraint(expr=model.coke_inventory[inputs.horizon_hours - 1] == inputs.coke_store_initial_t)
    model.sinter_terminal = Constraint(expr=model.sinter_inventory[inputs.horizon_hours - 1] == inputs.sinter_store_initial_t)
    model.hot_iron_terminal = Constraint(expr=model.hot_iron_inventory[inputs.horizon_hours - 1] == inputs.hot_iron_store_initial_t)
    model.cold_slab_terminal = Constraint(expr=model.cold_slab_inventory[inputs.horizon_hours - 1] == inputs.cold_slab_store_initial_t)
    model.final_product_fulfilment = Constraint(
        expr=sum(model.final_product_output[t] for t in model.TIME) == inputs.final_product_target_t
    )
    if daily_production_guardrail:
        _add_daily_production_guardrail(model, inputs)
    if fix_binary_schedule:
        _apply_c0_static_binary_schedule(
            model,
            inputs,
            process_names,
            wag_compatible=enable_minimal_wag_layer,
        )
    flare_tiebreaker = 0.0
    if enable_minimal_wag_layer:
        flare_tiebreaker = 1e-6 * sum(
            model.bfg_flared[t] + model.cog_flared[t] + model.bofg_flared[t]
            for t in model.TIME
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
        + flare_tiebreaker,
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
    daily_production_guardrail: bool = False,
    fix_c1_hybrid_schedule: bool = False,
    c1_retained_route_policy: str = "target_share",
):
    retained = inputs.retained_bf_bof
    if retained is None:
        raise S44CModelBuilderError("C1 hybrid WAG route requires retained BF-BOF inputs.")

    model = ConcreteModel()
    model.TIME = RangeSet(0, inputs.horizon_hours - 1)
    retained_process_names = tuple(retained.process_limits)
    for process_name in retained_process_names:
        setattr(model, process_name, Var(model.TIME, domain=NonNegativeReals))
        setattr(model, f"{process_name}_on", Var(model.TIME, domain=Binary))

    model.drp_pellet_input = Var(model.TIME, domain=NonNegativeReals)
    model.drp_on = Var(model.TIME, domain=Binary)
    model.eaf_dri_input = Var(model.TIME, domain=NonNegativeReals)
    model.eaf_on = Var(model.TIME, domain=Binary)
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
    model.bf6_hot_iron_output = Expression(
        model.TIME,
        rule=lambda m, t: retained.bf_hot_iron_per_t_sinter * m.blast_furnace_6[t],
    )
    model.bf7_hot_iron_output = Expression(model.TIME, rule=lambda _m, _t: 0.0)
    model.bf_hot_iron_output = Expression(model.TIME, rule=lambda m, t: m.bf6_hot_iron_output[t])
    model.bof_crude_steel_output = Expression(
        model.TIME,
        rule=lambda m, t: retained.bof_crude_steel_per_t_hot_iron * m.basic_oxygen_furnace[t],
    )
    model.retained_bf_bof_final_product_output = Expression(
        model.TIME,
        rule=lambda m, t: retained.hsm_final_per_t_crude_steel * m.hot_strip_mill[t],
    )

    model.drp_dri_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.drp_yield_t_dri_per_t_pellets * m.drp_pellet_input[t],
    )
    model.eaf_final_product_output = Expression(
        model.TIME,
        rule=lambda m, t: inputs.eaf_yield_t_final_per_t_dri * m.eaf_dri_input[t],
    )
    model.final_product_output = Expression(
        model.TIME,
        rule=lambda m, t: m.retained_bf_bof_final_product_output[t] + m.eaf_final_product_output[t],
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
    model.coke_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.coke_inventory[t]
        == (retained.coke_store_initial_t if t == 0 else m.coke_inventory[t - 1])
        + m.coking_plant_1[t]
        - retained.coke_per_t_sinter * m.bf_sinter_input[t],
    )
    model.sinter_balance = Constraint(
        model.TIME,
        rule=lambda m, t: m.sinter_inventory[t]
        == (retained.sinter_store_initial_t if t == 0 else m.sinter_inventory[t - 1])
        + m.sintering_plant[t]
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
        rule=lambda m, t: m.cold_slab_inventory[t]
        == (retained.cold_slab_store_initial_t if t == 0 else m.cold_slab_inventory[t - 1])
        + m.bof_crude_steel_output[t]
        - m.hot_strip_mill[t],
    )
    model.coke_capacity = Constraint(model.TIME, rule=lambda m, t: m.coke_inventory[t] <= retained.coke_store_capacity_t)
    model.sinter_capacity = Constraint(model.TIME, rule=lambda m, t: m.sinter_inventory[t] <= retained.sinter_store_capacity_t)
    model.hot_iron_capacity = Constraint(model.TIME, rule=lambda m, t: m.hot_iron_inventory[t] <= retained.hot_iron_store_capacity_t)
    model.cold_slab_capacity = Constraint(model.TIME, rule=lambda m, t: m.cold_slab_inventory[t] <= retained.cold_slab_store_capacity_t)
    model.coke_terminal = Constraint(expr=model.coke_inventory[inputs.horizon_hours - 1] == retained.coke_store_initial_t)
    model.sinter_terminal = Constraint(expr=model.sinter_inventory[inputs.horizon_hours - 1] == retained.sinter_store_initial_t)
    model.hot_iron_terminal = Constraint(expr=model.hot_iron_inventory[inputs.horizon_hours - 1] == retained.hot_iron_store_initial_t)
    model.cold_slab_terminal = Constraint(expr=model.cold_slab_inventory[inputs.horizon_hours - 1] == retained.cold_slab_store_initial_t)

    if c1_retained_route_policy not in {"target_share", "bottom_up_fixed_retained_route"}:
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
    model.final_product_fulfilment = Constraint(
        expr=sum(model.final_product_output[t] for t in model.TIME) == inputs.final_product_target_t
    )
    if daily_production_guardrail:
        _add_daily_production_guardrail(model, inputs)
    if c1_retained_route_policy == "bottom_up_fixed_retained_route":
        _apply_c1_bottom_up_retained_route_policy(model, inputs.horizon_hours)
    elif fix_c1_hybrid_schedule:
        _apply_c1_hybrid_static_schedule(model, inputs.horizon_hours)

    if enable_minimal_wag_layer:
        _add_c0_minimal_wag_layer(
            model,
            retained,
            enable_internal_wag_power=enable_internal_wag_power,
            gross_electricity_rule=lambda m, t: m.electricity_mwh[t],
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
    if enable_minimal_wag_layer:
        flare_tiebreaker = 1e-6 * sum(
            model.bfg_flared[t] + model.cog_flared[t] + model.bofg_flared[t]
            for t in model.TIME
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
        + flare_tiebreaker,
        sense=minimize,
    )
    return model


def _build_c1_model(
    inputs: C1ExecutableInputs,
    *,
    enable_minimal_wag_layer: bool = False,
    enable_c1_retained_bf_bof_route: bool = False,
    enable_internal_wag_power: bool = False,
    daily_production_guardrail: bool = False,
    fix_c1_hybrid_schedule: bool = False,
    c1_retained_route_policy: str = "target_share",
):
    if enable_c1_retained_bf_bof_route:
        return _build_c1_hybrid_model(
            inputs,
            enable_minimal_wag_layer=enable_minimal_wag_layer,
            enable_internal_wag_power=enable_internal_wag_power,
            daily_production_guardrail=daily_production_guardrail,
            fix_c1_hybrid_schedule=fix_c1_hybrid_schedule,
            c1_retained_route_policy=c1_retained_route_policy,
        )
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
    model.final_product_fulfilment = Constraint(
        expr=sum(model.final_product_output[t] for t in model.TIME) == inputs.final_product_target_t
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
    daily_production_guardrail: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    inputs = _build_c0_inputs(
        tables,
        horizon_hours_override=horizon_hours_override,
        target_multiplier=target_multiplier,
    )
    build_start = time.perf_counter()
    model = _build_c0_model(
        inputs,
        fix_binary_schedule=fix_binary_schedule,
        enable_minimal_wag_layer=enable_minimal_wag_layer,
        enable_internal_wag_power=enable_internal_wag_power,
        daily_production_guardrail=daily_production_guardrail,
    )
    build_runtime = time.perf_counter() - build_start
    solver_name, solver = _select_solver()
    if solver is None:
        raise S44CModelBuilderError("No LP/MIP solver available for S4.4c C0 physical regression.")
    solve_start = time.perf_counter()
    result = solver.solve(model)
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
            "mip_gap": _mip_gap(result),
            "variable_count": stats.variables,
            "binary_count": stats.binaries,
            "constraint_count": stats.constraints,
            "final_product_target_t": round(inputs.final_product_target_t, 6),
            "final_product_fulfilled_t": "not_solved",
            "final_product_residual_t": "not_solved",
            "fixed_binary_schedule_used": str(fix_binary_schedule).lower(),
            "caveat": "C0 model was built from B5 inputs but solver did not return a feasible/optimal solution.",
        }
        return audit, [], []

    objective_value = float(value(model.static_price_naive_objective))
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
        "executable_cost_terms_count": 0,
        "blocker_count": 0,
        "warning_count": 2,
        "solver_name": solver_name,
        "solver_status": solver_status,
        "termination_condition": termination_condition,
        "objective_value": round(objective_value, 6),
        "build_runtime_seconds": round(build_runtime, 6),
        "runtime_seconds": round(solve_runtime, 6),
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
        "bf_sinter_input_total_t": round(sum(bf_sinter), 6),
        "bof_hot_iron_input_total_t": round(sum(bof), 6),
        "hsm_input_total_t": round(sum(hsm), 6),
        "electricity_mwh": round(sum(float(value(model.gross_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "natural_gas_nm3": 0.0,
        "natural_gas_boiler_mwh": round(sum(ng_boiler), 6),
        "steam_mwh": round(sum(steam), 6),
        "oxygen_t": 0.0,
        "WAG_generated": round(sum(wag_generated), 6),
        "WAG_used": round(sum(wag_used), 6),
        "WAG_flared": round(sum(wag_flared), 6),
        "fixed_binary_schedule_used": str(fix_binary_schedule).lower(),
        "minimal_wag_layer_active": str(enable_minimal_wag_layer).lower(),
        "daily_production_guardrail_active": str(daily_production_guardrail).lower(),
        "allocation_tiebreaker": "non_economic_minimise_flare_1e-6" if enable_minimal_wag_layer else "",
        "caveat": "Solved C0 static BF-BOF development-only physical regression; WAG is balanced by carrier with process sinks, boiler placeholder, and flaring when minimal WAG layer is active.",
    }
    if enable_minimal_wag_layer:
        audit.update(
            {
                "BFG_generated_mwh": round(sum(float(value(model.bfg_generated[t])) for t in model.TIME), 6),
                "COG_generated_mwh": round(sum(float(value(model.cog_generated[t])) for t in model.TIME), 6),
                "BOFG_generated_mwh": round(sum(float(value(model.bofg_generated[t])) for t in model.TIME), 6),
                "BFG_used_mwh": round(
                    sum(float(value(model.bfg_to_kgf1[t] + model.bfg_to_boiler[t])) for t in model.TIME),
                    6,
                ),
                "COG_used_mwh": round(
                    sum(
                        float(
                            value(
                                model.cog_to_kgf1[t]
                                + model.cog_to_kgf2[t]
                                + model.cog_to_sinter[t]
                                + model.cog_to_boiler[t]
                            )
                        )
                        for t in model.TIME
                    ),
                    6,
                ),
                "BOFG_used_mwh": 0.0,
                "BFG_to_vattenfall_mwh": round(sum(float(value(model.bfg_to_vattenfall[t])) for t in model.TIME), 6),
                "COG_to_vattenfall_mwh": round(sum(float(value(model.cog_to_vattenfall[t])) for t in model.TIME), 6),
                "BOFG_to_vattenfall_mwh": round(sum(float(value(model.bofg_to_vattenfall[t])) for t in model.TIME), 6),
                "vattenfall_fuel_mwh": round(sum(float(value(model.vattenfall_fuel_mwh[t])) for t in model.TIME), 6),
                "wag_electricity_mwh": round(sum(float(value(model.wag_electricity_mwh[t])) for t in model.TIME), 6),
                "gross_electricity_mwh": round(sum(float(value(model.gross_electricity_mwh[t])) for t in model.TIME), 6),
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
            "caveat": "Hard equality to final-product target.",
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
                "C0_coking_input_t_h": round(float(value(model.coking_plant_1[t] + model.coking_plant_2[t])), 6),
                "C0_sintering_input_t_h": round(float(value(model.sintering_plant[t])), 6),
                "C0_BF6_sinter_input_t_h": round(float(value(model.blast_furnace_6[t])), 6),
                "C0_BF7_sinter_input_t_h": round(float(value(model.blast_furnace_7[t])), 6),
                "C0_BF_sinter_input_t_h": round(float(value(model.bf_sinter_input[t])), 6),
                "C0_BOF_hot_iron_input_t_h": round(float(value(model.basic_oxygen_furnace[t])), 6),
                "C0_HSM_input_t_h": round(float(value(model.hot_strip_mill[t])), 6),
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
                "coke_inventory_t": round(float(value(model.coke_inventory[t])), 6),
                "sinter_inventory_t": round(float(value(model.sinter_inventory[t])), 6),
                "hot_iron_inventory_t": round(float(value(model.hot_iron_inventory[t])), 6),
                "cold_slab_inventory_t": round(float(value(model.cold_slab_inventory[t])), 6),
                "DRI_inventory_t": "",
                "electricity_mwh": round(float(value(model.gross_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "natural_gas_nm3": 0.0,
                "natural_gas_boiler_mwh": round(float(value(model.ng_to_boiler_mwh[t])), 6)
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
                "vattenfall_fuel_mwh": round(float(value(model.vattenfall_fuel_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "wag_electricity_mwh": round(float(value(model.wag_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "gross_electricity_mwh": round(float(value(model.gross_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else "",
                "net_grid_import_mwh": round(float(value(model.net_grid_import_mwh[t])), 6)
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
    daily_production_guardrail: bool = False,
    fix_c1_hybrid_schedule: bool = False,
    c1_retained_route_policy: str = "target_share",
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    inputs = _build_c1_inputs(
        tables,
        horizon_hours_override=horizon_hours_override,
        target_multiplier=target_multiplier,
        include_retained_bf_bof=enable_c1_retained_bf_bof_route,
    )
    build_start = time.perf_counter()
    model = _build_c1_model(
        inputs,
        enable_minimal_wag_layer=enable_minimal_wag_layer,
        enable_c1_retained_bf_bof_route=enable_c1_retained_bf_bof_route,
        enable_internal_wag_power=enable_internal_wag_power,
        daily_production_guardrail=daily_production_guardrail,
        fix_c1_hybrid_schedule=fix_c1_hybrid_schedule,
        c1_retained_route_policy=c1_retained_route_policy,
    )
    build_runtime = time.perf_counter() - build_start
    solver_name, solver = _select_solver()
    if solver is None:
        raise S44CModelBuilderError("No LP/MIP solver available for S4.4c C1 physical regression.")
    start = time.perf_counter()
    result = solver.solve(model)
    runtime = time.perf_counter() - start
    solver_status = str(result.solver.status)
    termination_condition = str(result.solver.termination_condition)
    stats = collect_model_stats(model)
    objective_value = float(value(model.static_price_naive_objective))
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
        "executable_cost_terms_count": 0,
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
        "build_runtime_seconds": round(build_runtime, 6),
        "runtime_seconds": round(runtime, 6),
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
        "retained_bf_bof_target_share": round(inputs.retained_bf_bof.retained_target_share, 9)
        if hybrid_route_active and inputs.retained_bf_bof is not None
        else "",
        "retained_route_policy": c1_retained_route_policy if hybrid_route_active else "",
        "retained_coking_input_total_t": round(sum(retained_coking), 6),
        "retained_sintering_input_total_t": round(sum(retained_sinter), 6),
        "retained_bf6_sinter_input_total_t": round(sum(retained_bf6), 6),
        "retained_bof_hot_iron_input_total_t": round(sum(retained_bof), 6),
        "retained_hsm_input_total_t": round(sum(retained_hsm), 6),
        "bf7_activity_total_t": 0.0,
        "kgf2_activity_total_t": 0.0,
        "electricity_mwh": round(sum(float(value(model.gross_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else round(sum(float(value(model.electricity_mwh[t])) for t in model.TIME), 6),
        "natural_gas_nm3": round(sum(float(value(model.natural_gas_nm3[t])) for t in model.TIME), 6),
        "natural_gas_boiler_mwh": round(sum(float(value(model.ng_to_boiler_mwh[t])) for t in model.TIME), 6),
        "steam_mwh": round(sum(float(value(model.steam_production_mwh[t])) for t in model.TIME), 6),
        "oxygen_t": round(sum(float(value(model.oxygen_t[t])) for t in model.TIME), 6),
        "scrap_t": round(sum(float(value(model.scrap_t[t])) for t in model.TIME), 6),
        "WAG_generated": round(sum(float(value(model.wag_generated[t])) for t in model.TIME), 6),
        "WAG_used": round(sum(float(value(model.wag_used[t])) for t in model.TIME), 6),
        "WAG_flared": round(sum(float(value(model.wag_flared[t])) for t in model.TIME), 6),
        "BFG_generated_mwh": round(sum(float(value(model.bfg_generated[t])) for t in model.TIME), 6),
        "COG_generated_mwh": round(sum(float(value(model.cog_generated[t])) for t in model.TIME), 6),
        "BOFG_generated_mwh": round(sum(float(value(model.bofg_generated[t])) for t in model.TIME), 6),
        "BFG_used_mwh": round(
            sum(float(value(model.bfg_to_kgf1[t] + model.bfg_to_boiler[t] + model.bfg_to_vattenfall[t])) for t in model.TIME),
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
        "BOFG_used_mwh": round(sum(float(value(model.bofg_to_vattenfall[t])) for t in model.TIME), 6)
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
        "wag_electricity_mwh": round(sum(float(value(model.wag_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else 0.0,
        "gross_electricity_mwh": round(sum(float(value(model.gross_electricity_mwh[t])) for t in model.TIME), 6)
        if enable_minimal_wag_layer
        else round(sum(float(value(model.electricity_mwh[t])) for t in model.TIME), 6),
        "net_grid_import_mwh": round(sum(float(value(model.net_grid_import_mwh[t])) for t in model.TIME), 6)
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
            "caveat": "Hard equality to final-product proxy target.",
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
                "C1_retained_coking_input_t_h": round(float(value(model.coking_plant_1[t])), 6)
                if hybrid_route_active
                else "",
                "C1_retained_sintering_input_t_h": round(float(value(model.sintering_plant[t])), 6)
                if hybrid_route_active
                else "",
                "C1_retained_BF6_sinter_input_t_h": round(float(value(model.blast_furnace_6[t])), 6)
                if hybrid_route_active
                else "",
                "C1_retained_BOF_hot_iron_input_t_h": round(float(value(model.basic_oxygen_furnace[t])), 6)
                if hybrid_route_active
                else "",
                "C1_retained_HSM_input_t_h": round(float(value(model.hot_strip_mill[t])), 6)
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
                "C1_DRP_activity_t_pellets_h": round(float(value(model.drp_pellet_input[t])), 6),
                "C1_EAF_activity_t_DRI_h": round(float(value(model.eaf_dri_input[t])), 6),
                "final_product_output_t": round(float(value(model.final_product_output[t])), 6),
                "coke_inventory_t": round(float(value(model.coke_inventory[t])), 6)
                if hybrid_route_active
                else "",
                "sinter_inventory_t": round(float(value(model.sinter_inventory[t])), 6)
                if hybrid_route_active
                else "",
                "hot_iron_inventory_t": round(float(value(model.hot_iron_inventory[t])), 6)
                if hybrid_route_active
                else "",
                "cold_slab_inventory_t": round(float(value(model.cold_slab_inventory[t])), 6)
                if hybrid_route_active
                else "",
                "DRI_inventory_t": round(float(value(model.dri_inventory[t])), 6),
                "electricity_mwh": round(float(value(model.gross_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else round(float(value(model.electricity_mwh[t])), 6),
                "natural_gas_nm3": round(float(value(model.natural_gas_nm3[t])), 6),
                "natural_gas_boiler_mwh": round(float(value(model.ng_to_boiler_mwh[t])), 6),
                "BFG_generated_mwh": round(float(value(model.bfg_generated[t])), 6),
                "COG_generated_mwh": round(float(value(model.cog_generated[t])), 6),
                "BOFG_generated_mwh": round(float(value(model.bofg_generated[t])), 6),
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
                "vattenfall_fuel_mwh": round(float(value(model.vattenfall_fuel_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "wag_electricity_mwh": round(float(value(model.wag_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else 0.0,
                "gross_electricity_mwh": round(float(value(model.gross_electricity_mwh[t])), 6)
                if enable_minimal_wag_layer
                else round(float(value(model.electricity_mwh[t])), 6),
                "net_grid_import_mwh": round(float(value(model.net_grid_import_mwh[t])), 6)
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
    fix_c0_binary_schedule: bool = False,
    enable_minimal_wag_layer: bool = False,
    enable_c1_retained_bf_bof_route: bool = False,
    enable_internal_wag_power: bool = False,
    daily_production_guardrail: bool = False,
    fix_c1_hybrid_schedule: bool = False,
    c1_retained_route_policy: str = "target_share",
) -> dict[str, Any]:
    start = time.perf_counter()
    timestamp = now_utc()
    resolved_run_id = run_id or f"{MODE_ID}_{timestamp.strftime('%Y%m%d_%H%M%S')}"
    input_path = Path(input_dir)
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
            target_multiplier=target_multiplier,
            fix_binary_schedule=fix_c0_binary_schedule,
            enable_minimal_wag_layer=enable_minimal_wag_layer,
            enable_internal_wag_power=enable_internal_wag_power,
            daily_production_guardrail=daily_production_guardrail,
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
        target_multiplier=target_multiplier,
        enable_minimal_wag_layer=enable_minimal_wag_layer,
        enable_c1_retained_bf_bof_route=enable_c1_retained_bf_bof_route,
        enable_internal_wag_power=enable_internal_wag_power,
        daily_production_guardrail=daily_production_guardrail,
        fix_c1_hybrid_schedule=fix_c1_hybrid_schedule,
        c1_retained_route_policy=c1_retained_route_policy,
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
        "fix_c0_binary_schedule": fix_c0_binary_schedule,
        "enable_minimal_wag_layer": enable_minimal_wag_layer,
        "enable_c1_retained_bf_bof_route": enable_c1_retained_bf_bof_route,
        "enable_internal_wag_power": enable_internal_wag_power,
        "daily_production_guardrail": daily_production_guardrail,
        "fix_c1_hybrid_schedule": fix_c1_hybrid_schedule,
        "c1_retained_route_policy": c1_retained_route_policy,
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
    args = parser.parse_args(argv)
    report = run_s44c_unified_physical_regression(run_id=args.run_id, write_report=True)
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
