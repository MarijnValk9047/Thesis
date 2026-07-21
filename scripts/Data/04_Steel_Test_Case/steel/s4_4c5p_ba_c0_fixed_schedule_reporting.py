"""Run the governed C0 schedule as a reporting-only physical surface.

This module deliberately does not add C0 planning freedom, capacity, yields,
or any residual utility input.  It exposes the existing fixed schedule with
the same trace, ledger, origin and anchor-contract vocabulary used by the
canonical C1 physical baseline.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .rolling_production_quota import build_rolling_production_quota_plan
from .s4_4b_unified_input_validator import validate_unified_dev_inputs
from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    _build_c0_inputs,
    _load_tables,
    _solve_c0_configuration,
)


STAGE = "S4.4c5p_ba_c0_fixed_schedule_reporting"
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "configs" / "steel_c0_fixed_schedule_reporting.yaml"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
ANCHOR_REGISTER = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4" / "c5_model_anchor_register" / "c5_model_anchor_evidence_register.csv"
HOURS_PER_YEAR = 8760.0
TOLERANCE = 1e-6
# Hourly dispatch is exported to six decimals before this reporting compiler
# annualises it. These thresholds cover that deterministic export rounding,
# not a physical balance relaxation.
DISPATCH_EXPORT_TOLERANCE_T = 1e-4
CARRIER_EXPORT_TOLERANCE_MWH_Y = 1e-2
C0 = "C0_current_BF_BOF_reference"
C0_FIXED_SCHEDULE_ASSETS = (
    "coking_plant_1",
    "coking_plant_2",
    "sintering_plant",
    "blast_furnace_6",
    "blast_furnace_7",
    "basic_oxygen_furnace",
    "hot_strip_mill",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _file_record(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "status": "read" if path.exists() else "missing",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "",
    }


def _as_float(value: Any) -> float:
    return float(value) if value not in (None, "") else 0.0


def _load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("C0 fixed-schedule reporting config must be a mapping.")
    required = {
        "run_id", "configuration_id", "canonical_c1_run_id", "planning_horizon_hours",
        "execution_block_hours", "quota_per_execution_block_t", "base_quota_per_execution_block_t",
        "c0_schedule_policy", "development_controller_activation", "output_policy", "run_class",
        "lineage_role", "retention", "source_coke_chain", "c0_fixed_schedule",
    }
    missing = sorted(required.difference(config))
    if missing:
        raise ValueError(f"C0 reporting config is missing: {missing}")
    if config["configuration_id"] != C0:
        raise ValueError("C0 reporting surface may only run C0_current_BF_BOF_reference.")
    if config["c0_schedule_policy"] != "fixed_static_binary_schedule":
        raise ValueError("C0 reporting surface forbids free C0 binary planning.")
    schedule = config["c0_fixed_schedule"]
    if not isinstance(schedule, dict):
        raise ValueError("C0 reporting surface requires a c0_fixed_schedule mapping.")
    required_schedule = {
        "schedule_id", "source_status", "source_hierarchy", "source_locator",
        "caveat", "active_hours_by_process",
    }
    missing_schedule = sorted(required_schedule.difference(schedule))
    if missing_schedule:
        raise ValueError(f"C0 fixed schedule is missing: {missing_schedule}")
    if schedule["source_status"] not in {
        "inherited_static_regression_not_source_backed",
        "source_backed_fixed_calendar",
    }:
        raise ValueError("C0 fixed schedule must declare its source-backed or inherited-regression status.")
    active_hours = schedule["active_hours_by_process"]
    if not isinstance(active_hours, dict) or set(active_hours) != set(C0_FIXED_SCHEDULE_ASSETS):
        raise ValueError("C0 fixed schedule must define active hours for every active C0 process.")
    normalised_hours: dict[str, list[int]] = {}
    for asset_id in C0_FIXED_SCHEDULE_ASSETS:
        hours = active_hours[asset_id]
        if not isinstance(hours, list) or not hours:
            raise ValueError(f"C0 fixed schedule requires a non-empty hour list for {asset_id}.")
        try:
            parsed = sorted(int(hour) for hour in hours)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"C0 fixed schedule hours must be integers for {asset_id}.") from exc
        if len(set(parsed)) != len(parsed) or any(hour < 0 or hour > 23 for hour in parsed):
            raise ValueError(f"C0 fixed schedule hours must be unique values in [0, 23] for {asset_id}.")
        normalised_hours[asset_id] = parsed
    schedule["active_hours_by_process"] = normalised_hours
    source_coke_chain = config["source_coke_chain"]
    if not isinstance(source_coke_chain, dict):
        raise ValueError("C0 reporting surface requires a source_coke_chain mapping.")
    required_coke = {"dry_coal_t_per_t_coke", "bf_coke_t_per_t_hot_metal"}
    missing_coke = sorted(required_coke.difference(source_coke_chain))
    if missing_coke or any(float(source_coke_chain[key]) <= 0.0 for key in required_coke):
        raise ValueError(f"C0 source_coke_chain requires positive {sorted(required_coke)}.")
    for key in ("market_prices_enabled", "energy_cost_objective_enabled", "product_revenue_enabled", "co2_ets_objective_enabled"):
        if config.get(key) is not False:
            raise ValueError(f"C0 reporting surface requires {key}: false.")
    return config


def _annual(rows: list[dict[str, Any]], field: str, horizon_hours: int) -> float:
    return sum(_as_float(row.get(field)) for row in rows) * HOURS_PER_YEAR / float(horizon_hours)


def _deadline_rows(rows: list[dict[str, Any]], deadlines: dict[int, float]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for hour, target in sorted(deadlines.items()):
        fulfilled = sum(_as_float(row.get("final_product_output_t")) for row in rows if int(row["hour_index"]) < hour)
        residual = fulfilled - target
        result.append({
            "configuration_id": C0,
            "deadline_hour": hour,
            "cumulative_required_final_product_t": round(target, 6),
            "cumulative_fulfilled_final_product_t": round(fulfilled, 6),
            "residual_t": round(residual, 6),
            "status": "pass" if residual >= -DISPATCH_EXPORT_TOLERANCE_T else "fail",
            "quota_denominator": "final_product_proxy",
        })
    return result


def _schedule_basis_rows(schedule: dict[str, Any]) -> list[dict[str, Any]]:
    """Trace the governed C0 calendar separately from physical dispatch results."""
    classification = "historical" if schedule["source_status"] == "inherited_static_regression_not_source_backed" else "executable"
    return [
        {
            "configuration_id": C0,
            "schedule_id": schedule["schedule_id"],
            "asset_id": asset_id,
            "active_hours_of_day": ";".join(str(hour) for hour in schedule["active_hours_by_process"][asset_id]),
            "active_hours_per_day": len(schedule["active_hours_by_process"][asset_id]),
            "source_status": schedule["source_status"],
            "source_hierarchy": schedule["source_hierarchy"],
            "source_locator": schedule["source_locator"],
            "pyomo_component": f"{asset_id}_on",
            "pyomo_constraint_or_expression": "process_min; process_max; fixed binary schedule",
            "classification": classification,
            "caveat": schedule["caveat"],
        }
        for asset_id in C0_FIXED_SCHEDULE_ASSETS
    ]


def _fixed_schedule_coke_diagnostic(
    tables: Any,
    source_coke_chain: dict[str, Any],
    schedule: dict[str, Any],
) -> list[dict[str, Any]]:
    """Explain source-corrected coke feasibility conditional on the declared fixed schedule."""
    inputs = _build_c0_inputs(tables, horizon_hours_override=24)
    dry_coal_per_t_coke = float(source_coke_chain["dry_coal_t_per_t_coke"])
    bf_coke_per_t_hot_metal = float(source_coke_chain["bf_coke_t_per_t_hot_metal"])
    active_hours = schedule["active_hours_by_process"]
    coking_max_dry_coal = (
        len(active_hours["coking_plant_1"]) * inputs.process_limits["coking_plant_1"][1]
        + len(active_hours["coking_plant_2"]) * inputs.process_limits["coking_plant_2"][1]
    )
    coke_output_max = coking_max_dry_coal / dry_coal_per_t_coke
    bf_min_hot_metal = (
        len(active_hours["blast_furnace_6"]) * inputs.process_limits["blast_furnace_6"][0]
        + len(active_hours["blast_furnace_7"]) * inputs.process_limits["blast_furnace_7"][0]
    ) * inputs.bf_hot_iron_per_t_sinter
    bf_min_coke_demand = bf_min_hot_metal * bf_coke_per_t_hot_metal
    return [
        {
            "diagnostic_id": "C0_FIXED_SCHEDULE_COKE_MINIMUM",
            "basis": "declared_fixed_schedule_and_source_coke_chain",
            "schedule_id": schedule["schedule_id"],
            "schedule_source_status": schedule["source_status"],
            "coking_plant_1_active_hours_per_day": len(active_hours["coking_plant_1"]),
            "coking_plant_2_active_hours_per_day": len(active_hours["coking_plant_2"]),
            "BF6_active_hours_per_day": len(active_hours["blast_furnace_6"]),
            "BF7_active_hours_per_day": len(active_hours["blast_furnace_7"]),
            "maximum_coke_output_t_per_day": round(coke_output_max, 6),
            "minimum_BF_coke_demand_t_per_day": round(bf_min_coke_demand, 6),
            "daily_coke_gap_t": round(coke_output_max - bf_min_coke_demand, 6),
            "status": "fail" if coke_output_max + TOLERANCE < bf_min_coke_demand else "pass",
            "caveat": "This is a pre-solve schedule-conditional proof. It does not alter capacity, yields, WAG factors or C0 binary freedom; an inherited calendar is not source-backed C0 availability evidence.",
        }
    ]


def _material_rows(
    rows: list[dict[str, Any]], horizon_hours: int, *, source_coke_chain_active: bool
) -> list[dict[str, Any]]:
    annual = lambda field: _annual(rows, field, horizon_hours)
    return [
        {
            "metric": "coking_dry_coal_activity",
            "annual_value": round(annual("C0_coking_input_t_h"), 6),
            "unit": "t_dry_coal/y",
            "model_component": "coking_plant_1 + coking_plant_2",
            "source_basis_status": "executable_development_input",
            "caveat": "C0 coking activity is explicitly t_coal/h in process_units.csv.",
        },
        {
            "metric": "coke_output",
            "annual_value": round(annual("C0_coke_output_t_h"), 6),
            "unit": "t_coke/y",
            "model_component": "coke_balance",
            "source_basis_status": "source_backed_coke_output" if source_coke_chain_active else "blocked_unit_basis_mismatch",
            "caveat": "Coke output is dry-coal activity divided by the named source factor." if source_coke_chain_active else "The current C0 balance adds t_dry_coal activity directly to coke inventory, while the governed COG factor is per t_dry_coal.",
        },
        {
            "metric": "BF_coke_demand",
            "annual_value": round(annual("C0_BF_coke_demand_t_h"), 6),
            "unit": "t_coke/y",
            "model_component": "bf_coke_demand",
            "source_basis_status": "source_backed_BF_coke_per_hot_metal" if source_coke_chain_active else "blocked_unit_basis_mismatch",
            "caveat": "BF coke demand is the named source rate times represented hot metal." if source_coke_chain_active else "The current C0 balance derives coke demand from the unreconciled sinter activity basis.",
        },
        {
            "metric": "sintering_activity",
            "annual_value": round(annual("C0_sintering_input_t_h"), 6),
            "unit": "t_iron_ore_proxy/y",
            "model_component": "sintering_plant",
            "source_basis_status": "executable_development_input_with_boundary_caveat",
            "caveat": "The active C0 sinter/iron-ore activity basis remains a documented denominator blocker.",
        },
        {
            "metric": "BF_sinter_input",
            "annual_value": round(annual("C0_BF_sinter_input_t_h"), 6),
            "unit": "t_sinter/y",
            "model_component": "bf_sinter_input",
            "source_basis_status": "executable_development_input",
            "caveat": "BF6 and BF7 inputs remain separate in hourly dispatch.",
        },
        {
            "metric": "BF_hot_metal_output",
            "annual_value": round(annual("C0_BF_hot_iron_output_t"), 6),
            "unit": "t_hot_metal/y",
            "model_component": "bf_hot_iron_output",
            "source_basis_status": "blocked_sinter_to_hot_metal_basis_review",
            "caveat": "The active conversion is retained for reporting only until the C0 sinter/burden denominator is reconciled.",
        },
        {
            "metric": "BOF_crude_steel_output",
            "annual_value": round(annual("C0_BOF_crude_steel_output_t"), 6),
            "unit": "t_crude_steel/y",
            "model_component": "bof_crude_steel_output",
            "source_basis_status": "executable_development_input",
            "caveat": "This is an explicit BOF output, not a substitute for final-product output.",
        },
        {
            "metric": "HSM_final_product",
            "annual_value": round(annual("C0_HSM_final_product_t"), 6),
            "unit": "t_final_product/y",
            "model_component": "final_product_output",
            "source_basis_status": "origin_tagged_executable",
            "caveat": "C0 final product is HSM-origin tagged in the executable surface.",
        },
        {
            "metric": "DSP_final_product",
            "annual_value": 0.0,
            "unit": "t_final_product/y",
            "model_component": "none",
            "source_basis_status": "blocked_no_executable_C0_DSP_route",
            "caveat": "DSP is retained as an explicit zero-route reporting row; it is not inferred from HSM or a residual.",
        },
    ]


def _carrier_rows(rows: list[dict[str, Any]], horizon_hours: int) -> list[dict[str, Any]]:
    annual = lambda field: _annual(rows, field, horizon_hours)
    definitions = {
        "BFG": ("BFG_generated_mwh", ("BFG_to_BF_hot_stove_mwh", "BFG_to_HSM_mwh"), ("BFG_to_boiler_mwh",), ("BFG_to_vattenfall_mwh",), ("BFG_flared_mwh",), "BF_hot_metal_output"),
        "COG": ("COG_generated_mwh", ("COG_to_KGF1_mwh", "COG_to_KGF2_mwh", "COG_to_sinter_mwh", "COG_to_HSM_mwh", "COG_to_PEFA_branderij_mwh"), ("COG_to_boiler_mwh",), ("COG_to_vattenfall_mwh",), ("COG_flared_mwh",), "coking_dry_coal_activity"),
        "BOFG": ("BOFG_generated_mwh", ("BOFG_to_HSM_mwh", "BOFG_to_PEFA_malerij_mwh"), (), ("BOFG_to_vattenfall_mwh",), ("BOFG_flared_mwh",), "BOF_crude_steel_output"),
    }
    output: list[dict[str, Any]] = []
    for carrier, (generation_field, process_fields, boiler_fields, generator_fields, flare_fields, basis) in definitions.items():
        generation = annual(generation_field)
        process = sum(annual(field) for field in process_fields)
        boiler = sum(annual(field) for field in boiler_fields)
        generator = sum(annual(field) for field in generator_fields)
        flare = sum(annual(field) for field in flare_fields)
        accounted = process + boiler + generator + flare
        output.append({
            "configuration": C0,
            "carrier": carrier,
            "source_activity_basis": basis,
            "generation_MWh_LHV_y": round(generation, 6),
            "process_or_self_use_MWh_LHV_y": round(process, 6),
            "steam_boiler_MWh_LHV_y": round(boiler, 6),
            "generator_MWh_LHV_y": round(generator, 6),
            "flare_MWh_LHV_y": round(flare, 6),
            "residual_MWh_LHV_y": round(generation - accounted, 9),
            "balance_status": "pass" if abs(generation - accounted) <= CARRIER_EXPORT_TOLERANCE_MWH_Y else "fail",
            "physical_carrier_status": "carrier_specific_accepted",
            "caveat": "Carrier-specific C0 reporting only; no aggregate or mixed WAG allocation is created.",
        })
    return output


def _sink_rows(rows: list[dict[str, Any]], horizon_hours: int) -> list[dict[str, Any]]:
    annual = lambda field: _annual(rows, field, horizon_hours)
    definitions = (
        ("BFG", "BF hot stove", "BFG_to_BF_hot_stove_mwh", "mandatory_process_self_use"),
        ("COG", "KGF1 underfiring", "COG_to_KGF1_mwh", "mandatory_process_self_use"),
        ("COG", "KGF2 underfiring", "COG_to_KGF2_mwh", "mandatory_process_self_use"),
        ("COG", "sinter", "COG_to_sinter_mwh", "mandatory_process_self_use"),
        ("BFG", "HSM reheat", "BFG_to_HSM_mwh", "HSM_controller"),
        ("COG", "HSM reheat", "COG_to_HSM_mwh", "HSM_controller"),
        ("BOFG", "HSM reheat", "BOFG_to_HSM_mwh", "HSM_controller"),
        ("NG", "HSM reheat", "NG_to_HSM_mwh", "HSM_named_backup"),
        ("BOFG", "PEFA Malerij", "BOFG_to_PEFA_malerij_mwh", "PEFA_controller"),
        ("COG", "PEFA Branderij", "COG_to_PEFA_branderij_mwh", "PEFA_controller"),
        ("NG", "PEFA Malerij", "NG_to_PEFA_malerij_mwh", "PEFA_named_backup"),
        ("NG", "PEFA Branderij", "NG_to_PEFA_branderij_mwh", "PEFA_named_backup"),
        ("BFG", "15-bar boiler bridge", "BFG_to_boiler_mwh", "steam_utility"),
        ("COG", "15-bar boiler bridge", "COG_to_boiler_mwh", "steam_utility"),
        ("NG", "15-bar boiler bridge", "natural_gas_boiler_mwh", "steam_named_backup"),
        ("BFG", "VN25/IJ01 interface", "BFG_to_vattenfall_mwh", "generator_interface"),
        ("COG", "VN25/IJ01 interface", "COG_to_vattenfall_mwh", "generator_interface"),
        ("BOFG", "VN25/IJ01 interface", "BOFG_to_vattenfall_mwh", "generator_interface"),
        ("BFG", "flare", "BFG_flared_mwh", "carrier_specific_flare"),
        ("COG", "flare", "COG_flared_mwh", "carrier_specific_flare"),
        ("BOFG", "flare", "BOFG_flared_mwh", "carrier_specific_flare"),
    )
    return [
        {
            "configuration": C0,
            "carrier": carrier,
            "sink": sink,
            "controller_role": role,
            "annual_MWh_LHV_y": round(annual(field), 6),
            "physical_carrier_flow": "yes",
            "caveat": "Carrier-specific realised flow; no aggregate or mixed WAG carrier is created.",
        }
        for carrier, sink, field, role in definitions
    ]


def _utility_rows(rows: list[dict[str, Any]], horizon_hours: int) -> list[dict[str, Any]]:
    annual = lambda field: _annual(rows, field, horizon_hours)
    controller_ng = sum(annual(field) for field in ("NG_to_HSM_mwh", "NG_to_PEFA_malerij_mwh", "NG_to_PEFA_branderij_mwh", "natural_gas_boiler_mwh"))
    return [
        {"metric": "final_product_output", "model_value": round(annual("final_product_output_t") / 1_000_000.0, 6), "unit": "Mt/y", "boundary_status": "C0_HSM_final_product_proxy", "caveat": "Representative-week annualisation of the governed C0 schedule; not an annual Tata production claim."},
        {"metric": "C0_BOF_crude_steel_output", "model_value": round(annual("C0_BOF_crude_steel_output_t") / 1_000_000.0, 6), "unit": "Mt/y", "boundary_status": "represented_C0_liquid_steel", "caveat": "Explicit BOF output is reported separately from final product."},
        {"metric": "gross_electricity", "model_value": round(annual("gross_electricity_mwh") / 1_000_000.0, 6), "unit": "TWh/y", "boundary_status": "historical_fixed_C0_site_proxy", "caveat": "Fixed C0 electricity proxy is a reporting surface only, not a source-backed activity driver or residual input."},
        {"metric": "internal_WAG_generator_electricity_offset", "model_value": round(annual("wag_electricity_mwh") / 1_000_000.0, 6), "unit": "TWh/y", "boundary_status": "internal_offset_not_market_revenue", "caveat": "Internal generator offset only; no DA or export revenue is active."},
        {"metric": "net_grid_import_after_internal_WAG_offset", "model_value": round(annual("net_grid_import_mwh") / 1_000_000.0, 6), "unit": "TWh/y", "boundary_status": "represented_net_import_only", "caveat": "Not a full-site grid-import claim."},
        {"metric": "steam_production_proxy", "model_value": round(annual("steam") / 1_000_000.0, 6), "unit": "TWh_th/y", "boundary_status": "boiler_fuel_energy_proxy", "caveat": "Energy proxy only; the mapped 15-bar mass bridge is reported separately."},
        {"metric": "modelled_steam_15bar_demand", "model_value": round(annual("steam_15bar_demand_t") / 1_000.0, 6), "unit": "kt_steam/y", "boundary_status": "mapped_C5p_b_demand_only", "caveat": "Mapped demand only; no full-site steam residual is filled."},
        {"metric": "modelled_steam_15bar_supply", "model_value": round(annual("steam_15bar_supply_t") / 1_000.0, 6), "unit": "kt_steam/y", "boundary_status": "mapped_C5p_b_supply_only", "caveat": "Mapped fuel-to-mass bridge only; no detailed enthalpy dispatch is claimed."},
        {"metric": "modelled_steam_15bar_unserved", "model_value": round(annual("steam_15bar_unserved_t") / 1_000.0, 6), "unit": "kt_steam/y", "boundary_status": "mapped_C5p_b_demand_only", "caveat": "Zero applies only to represented mapped demand."},
        {"metric": "named_NG_HSM_PEFA_boiler_energy", "model_value": round(controller_ng * 3.6 / 1_000_000.0, 6), "unit": "PJ_LHV/y", "boundary_status": "named_controller_NG_energy", "caveat": "Separate from unallocated full-site NG context."},
        {"metric": "WAG_explicit_combustion_CO2", "model_value": round(annual("WAG_explicit_combustion_co2_t") / 1_000_000.0, 6), "unit": "MtCO2/y", "boundary_status": "Mode_B_represented_oxidation_sinks_only", "caveat": "Excludes aggregate process counters, full-site Scope 1 and unrepresented NG."},
        {"metric": "WAG_flare_CO2", "model_value": round(annual("flaring_co2_t") / 1_000_000.0, 6), "unit": "MtCO2/y", "boundary_status": "carrier_specific_flare_only", "caveat": "Included within WAG explicit combustion; do not add again."},
    ]


def _origin_rows(material: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_metric = {row["metric"]: row for row in material}
    hsm = float(by_metric["HSM_final_product"]["annual_value"])
    dsp = float(by_metric["DSP_final_product"]["annual_value"])
    return [
        {"metric": "C0_BOF_to_HSM", "annual_value": hsm, "unit": "t/y", "boundary": "endogenous_downstream_route", "status": "reported", "caveat": "C0 final product is entirely HSM-origin in this executable surface."},
        {"metric": "C0_HSM_final_product", "annual_value": hsm, "unit": "t/y", "boundary": "origin_tagged_downstream", "status": "reported", "caveat": "HSM origin is explicit."},
        {"metric": "C0_DSP_final_product", "annual_value": dsp, "unit": "t/y", "boundary": "no_executable_C0_DSP_route", "status": "blocked", "caveat": "No DSP output is inferred or allocated."},
        {"metric": "C0_site_final_product", "annual_value": hsm + dsp, "unit": "t/y", "boundary": "final_product_proxy", "status": "reported", "caveat": "Final-product denominator; it is not silently replaced by liquid steel."},
        {"metric": "C0_HSM_DSP_origin_balance_residual", "annual_value": 0.0, "unit": "t/y", "boundary": "origin_tagged_downstream", "status": "pass", "caveat": "HSM plus explicit zero DSP equals the C0 final-product proxy."},
    ]


def _model_metrics(utilities: list[dict[str, Any]], carriers: list[dict[str, Any]]) -> dict[str, tuple[float, str, str]]:
    by_metric = {str(row["metric"]): row for row in utilities}
    wag_used = sum(
        float(row["process_or_self_use_MWh_LHV_y"]) + float(row["steam_boiler_MWh_LHV_y"]) + float(row["generator_MWh_LHV_y"])
        for row in carriers
    )
    wag_generation = sum(float(row["generation_MWh_LHV_y"]) for row in carriers)
    return {
        "final_product": (float(by_metric["final_product_output"]["model_value"]), "Mt/y", "final_product_output"),
        "liquid_steel": (float(by_metric["C0_BOF_crude_steel_output"]["model_value"]), "Mt/y", "C0_BOF_crude_steel_output"),
        "hsm": (float(by_metric["final_product_output"]["model_value"]), "Mt/y", "C0_HSM_final_product"),
        "dsp": (0.0, "Mt/y", "C0_DSP_final_product"),
        "gross_electricity": (float(by_metric["gross_electricity"]["model_value"]), "TWh/y", "gross_electricity"),
        "net_grid_import": (float(by_metric["net_grid_import_after_internal_WAG_offset"]["model_value"]), "TWh/y", "net_grid_import_after_internal_WAG_offset"),
        "generator_offset": (float(by_metric["internal_WAG_generator_electricity_offset"]["model_value"]), "TWh/y", "internal_WAG_generator_electricity_offset"),
        "named_ng": (float(by_metric["named_NG_HSM_PEFA_boiler_energy"]["model_value"]), "PJ/y", "named_NG_HSM_PEFA_boiler_energy"),
        "wag_generation": (wag_generation * 3.6 / 1_000_000.0, "PJ/y", "carrier_specific_WAG_generation"),
        "wag_reuse": (wag_used * 3.6 / 1_000_000.0, "PJ/y", "carrier_specific_WAG_reuse"),
        "mode_b_co2": (float(by_metric["WAG_explicit_combustion_CO2"]["model_value"]), "MtCO2/y", "WAG_explicit_combustion_CO2"),
    }


def _convert(value: float, source_unit: str, target_unit: str) -> float | None:
    if source_unit == target_unit:
        return value
    pairs = {
        ("TWh/y", "PJ/y"): 3.6,
        ("PJ/y", "TWh/y"): 1.0 / 3.6,
        ("Mt/y", "t/y"): 1_000_000.0,
        ("t/y", "Mt/y"): 1.0 / 1_000_000.0,
    }
    factor = pairs.get((source_unit, target_unit))
    return value * factor if factor is not None else None


def _anchor_rows(utilities: list[dict[str, Any]], carriers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = _model_metrics(utilities, carriers)
    metric_mapping = {
        "active_steel_target_6_75": "final_product",
        "c0_public_liquid_steel_7_2": "liquid_steel",
        "c0_dsp_raw_output_1_5": "dsp",
        "c0_hsm_wbw_raw_output_5_4": "hsm",
        "c0_final_product_proxy_6_9": "final_product",
        "c0_total_site_electricity_3twh_context": "gross_electricity",
        "c0_average_power_360mw_context": "gross_electricity",
        "c0_official_total_site_electricity_13_7pj_missing": "gross_electricity",
        "athan_table8_current_electricity_3_17": "gross_electricity",
        "c0_residual_gas_electricity_2twh": "generator_offset",
        "c0_generator_actual_2_067665": "generator_offset",
        "c0_full_site_ng_12_5pj_missing": "named_ng",
        "c0_product_gas_reuse_54pj": "wag_reuse",
        "athan_table8_current_wag_2_74": "generator_offset",
        "c0_official_scope1_12_6_missing": "mode_b_co2",
        "athan_table8_current_co2_13_365": "mode_b_co2",
    }
    output: list[dict[str, Any]] = []
    for anchor in _read_csv(ANCHOR_REGISTER):
        if anchor.get("configuration") not in {"C0", "both"}:
            continue
        key = metric_mapping.get(str(anchor["anchor_id"]))
        anchor_value = _as_float(anchor.get("converted_value"))
        anchor_unit = str(anchor.get("converted_unit") or "")
        numerator_value = ""
        numerator_unit = ""
        numerator_metric = ""
        residual = ""
        residual_share = ""
        if key is not None and anchor_value and anchor_unit:
            model_value, model_unit, model_metric = metrics[key]
            converted = _convert(model_value, model_unit, anchor_unit)
            numerator_metric = model_metric
            if converted is not None:
                numerator_value = round(converted, 6)
                numerator_unit = anchor_unit
                residual = round(converted - anchor_value, 6)
                residual_share = round((converted - anchor_value) / anchor_value, 9)
        if str(anchor["anchor_id"]) == "c0_dsp_raw_output_1_5":
            status = "blocked"
            reason = "No executable C0 DSP route exists; zero is reported rather than inferred."
        elif key is None or not anchor_value or not anchor_unit:
            status = "blocked"
            reason = "No like-for-like numerator or converted anchor unit is available."
        elif str(anchor["anchor_id"]) in {"c0_hsm_wbw_raw_output_5_4", "c0_final_product_proxy_6_9", "c0_public_liquid_steel_7_2"}:
            status = "not_comparable"
            reason = "C0 downstream and liquid-steel denominator conventions remain unresolved."
        else:
            status = "reporting_only"
            reason = "C0 reporting surface preserves the signed residual but does not establish a complete site or final-product boundary."
        output.append({
            "anchor_id": anchor["anchor_id"],
            "configuration": C0,
            "anchor_name": anchor["anchor_name"],
            "model_numerator_metric": numerator_metric,
            "model_numerator_value": numerator_value,
            "model_numerator_unit": numerator_unit,
            "anchor_value": anchor.get("converted_value", ""),
            "anchor_unit": anchor_unit,
            "denominator_type": anchor.get("denominator_type", ""),
            "model_boundary": "C0_fixed_schedule_represented_boundary",
            "scaling_policy": anchor.get("scaling_method", ""),
            "source_rank": anchor.get("source_trust_rank", ""),
            "comparability_status": status,
            "comparability_reason": reason,
            "signed_residual": residual,
            "signed_residual_share": residual_share,
            "caveat": anchor.get("caveat", ""),
        })
    return output


def _canonical_anchor_matrix(c0_rows: list[dict[str, Any]], c1_directory: Path, c0_run_id: str) -> list[dict[str, Any]]:
    """Classify every registered anchor against exactly one C0 or C1 surface."""
    register = _read_csv(ANCHOR_REGISTER)
    c0_by_id = {str(row["anchor_id"]): row for row in c0_rows}
    c1_raw = {str(row["anchor_id"]): row for row in _read_csv(c1_directory / "anchor_comparison.csv")}
    # The pre-existing C1 compiler predates the evidence-register identifier.
    # Normalize that one stable alias here rather than creating a duplicate
    # active production target in the source register.
    if "active_final_product_target_6_75" in c1_raw:
        c1_raw["active_steel_target_6_75"] = c1_raw["active_final_product_target_6_75"]

    matrix: list[dict[str, Any]] = []
    for anchor in register:
        registered_configuration = str(anchor.get("configuration", ""))
        configurations = (C0, "C1_phase1_BF_BOF_plus_DRP_EAF") if registered_configuration == "both" else (
            (C0,) if registered_configuration == "C0" else
            ("C1_phase1_BF_BOF_plus_DRP_EAF",) if registered_configuration == "C1" else
            ("generic",)
        )
        for configuration in configurations:
            anchor_id = str(anchor["anchor_id"])
            if configuration == C0:
                source = c0_by_id.get(anchor_id)
                if source is None:
                    matrix.append({
                        "anchor_id": anchor_id,
                        "registered_configuration": registered_configuration,
                        "configuration": configuration,
                        "source_run_id": c0_run_id,
                        "model_numerator_metric": "",
                        "model_numerator_value": "",
                        "model_numerator_unit": "",
                        "anchor_value": anchor.get("converted_value", ""),
                        "anchor_unit": anchor.get("converted_unit", ""),
                        "denominator_type": anchor.get("denominator_type", ""),
                        "boundary": "no_accepted_source_corrected_C0_solution",
                        "scaling_policy": anchor.get("scaling_method", ""),
                        "source_rank": anchor.get("source_trust_rank", ""),
                        "comparability_status": "blocked",
                        "comparability_reason": "The governed source-corrected C0 fixed schedule has no accepted physical solution.",
                        "signed_residual": "",
                        "signed_residual_share": "",
                        "caveat": anchor.get("caveat", ""),
                    })
                    continue
                matrix.append({
                    "anchor_id": anchor_id,
                    "registered_configuration": registered_configuration,
                    "configuration": configuration,
                    "source_run_id": c0_run_id,
                    "model_numerator_metric": source["model_numerator_metric"],
                    "model_numerator_value": source["model_numerator_value"],
                    "model_numerator_unit": source["model_numerator_unit"],
                    "anchor_value": source["anchor_value"],
                    "anchor_unit": source["anchor_unit"],
                    "denominator_type": source["denominator_type"],
                    "boundary": source["model_boundary"],
                    "scaling_policy": source["scaling_policy"],
                    "source_rank": source["source_rank"],
                    "comparability_status": source["comparability_status"],
                    "comparability_reason": source["comparability_reason"],
                    "signed_residual": source["signed_residual"],
                    "signed_residual_share": source["signed_residual_share"],
                    "caveat": source["caveat"],
                })
                continue
            if configuration == "C1_phase1_BF_BOF_plus_DRP_EAF":
                source = c1_raw.get(anchor_id)
                if source is None:
                    matrix.append({
                        "anchor_id": anchor_id,
                        "registered_configuration": registered_configuration,
                        "configuration": configuration,
                        "source_run_id": c1_directory.name,
                        "model_numerator_metric": "",
                        "model_numerator_value": "",
                        "model_numerator_unit": "",
                        "anchor_value": anchor.get("converted_value", ""),
                        "anchor_unit": anchor.get("converted_unit", ""),
                        "denominator_type": anchor.get("denominator_type", ""),
                        "boundary": "no_current_canonical_C1_numerator",
                        "scaling_policy": anchor.get("scaling_method", ""),
                        "source_rank": anchor.get("source_trust_rank", ""),
                        "comparability_status": "blocked",
                        "comparability_reason": "The canonical C1 ledgers have no non-overlapping numerator for this registered anchor.",
                        "signed_residual": "",
                        "signed_residual_share": "",
                        "caveat": anchor.get("caveat", ""),
                    })
                    continue
                # New canonical C1 runs state their gate classification directly.
                # Keep a narrow fallback so an older, immutable C1 artifact can
                # still be inspected without silently treating context rows as
                # comparable in a newly generated reconciliation matrix.
                status = str(source.get("comparability_status", ""))
                if status not in {"comparable", "reporting_only", "not_comparable", "blocked"}:
                    raw_status = str(source.get("status", ""))
                    comparison_class = str(source.get("comparison_class", ""))
                    status = (
                        "reporting_only" if comparison_class == "reporting_only" else
                        "not_comparable" if raw_status in {"comparable_with_caveat", "not_comparable"} else
                        "blocked"
                    )
                matrix.append({
                    "anchor_id": anchor_id,
                    "registered_configuration": registered_configuration,
                    "configuration": configuration,
                    "source_run_id": c1_directory.name,
                    "model_numerator_metric": source.get("metric", ""),
                    "model_numerator_value": source.get("model_value", ""),
                    "model_numerator_unit": source.get("unit", ""),
                    "anchor_value": source.get("anchor_value", anchor.get("converted_value", "")),
                    "anchor_unit": source.get("unit", anchor.get("converted_unit", "")),
                    "denominator_type": anchor.get("denominator_type", ""),
                    "boundary": source.get("comparison_basis", ""),
                    "scaling_policy": anchor.get("scaling_method", ""),
                    "source_rank": source.get("source_rank", anchor.get("source_trust_rank", "")),
                    "comparability_status": status,
                    "comparability_reason": source.get("comparability_reason", source.get("caveat", "")),
                    "signed_residual": source.get("signed_residual", ""),
                    "signed_residual_share": source.get("signed_residual_share", ""),
                    "caveat": anchor.get("caveat", ""),
                })
                continue
            matrix.append({
                "anchor_id": anchor_id,
                "registered_configuration": registered_configuration,
                "configuration": "generic",
                "source_run_id": "",
                "model_numerator_metric": "",
                "model_numerator_value": "",
                "model_numerator_unit": "",
                "anchor_value": anchor.get("converted_value", ""),
                "anchor_unit": anchor.get("converted_unit", ""),
                "denominator_type": anchor.get("denominator_type", ""),
                "boundary": "not_configuration_specific",
                "scaling_policy": anchor.get("scaling_method", ""),
                "source_rank": anchor.get("source_trust_rank", ""),
                "comparability_status": "blocked",
                "comparability_reason": "Generic anchor has no configuration-specific canonical numerator.",
                "signed_residual": "",
                "signed_residual_share": "",
                "caveat": anchor.get("caveat", ""),
            })
    return matrix


def _flow_trace(material: list[dict[str, Any]], sinks: list[dict[str, Any]], utilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for material_row in material:
        status = str(material_row["source_basis_status"])
        rows.append({
            "configuration": C0,
            "flow_id": material_row["metric"],
            "carrier_or_material": "material",
            "input_source": "process_units.csv; process_io_coefficients.csv",
            "activity_basis": material_row["unit"],
            "pyomo_component": material_row["model_component"],
            "pyomo_constraint_or_expression": "C0 material balance or named process expression",
            "annual_ledger_destination": "material_ledger.csv",
            "anchor_numerator_role": "supporting_material_ledger",
            "classification": "blocked" if status.startswith("blocked") else "executable",
            "caveat": material_row["caveat"],
        })
    for sink in sinks:
        rows.append({
            "configuration": C0,
            "flow_id": f"{str(sink['carrier']).lower()}_to_{str(sink['sink']).lower().replace(' ', '_').replace('/', '_')}",
            "carrier_or_material": sink["carrier"],
            "input_source": "wag_generation_coefficients.csv; wag_sink_eligibility.csv; C5 controller profile",
            "activity_basis": "MWh_LHV/y",
            "pyomo_component": sink["sink"],
            "pyomo_constraint_or_expression": "carrier balance or explicit controller demand",
            "annual_ledger_destination": "wag_sink_mix_ledger.csv; wag_carrier_ledger.csv",
            "anchor_numerator_role": "generator_or_flare_WAG_anchor" if sink["sink"] in {"VN25/IJ01 interface", "flare"} else "supporting_carrier_ledger",
            "classification": "executable",
            "caveat": sink["caveat"],
        })
    for utility in utilities:
        classification = "historical" if utility["metric"] == "gross_electricity" else "executable"
        rows.append({
            "configuration": C0,
            "flow_id": utility["metric"],
            "carrier_or_material": "utility_or_emissions",
            "input_source": "C5 controller profile or explicit C0 reporting expression",
            "activity_basis": utility["unit"],
            "pyomo_component": utility["metric"],
            "pyomo_constraint_or_expression": "represented utility or Mode-B expression",
            "annual_ledger_destination": "utility_energy_co2_ledger.csv",
            "anchor_numerator_role": "anchor_or_visible_residual_context",
            "classification": classification,
            "caveat": utility["caveat"],
        })
    rows.extend([
        {"configuration": C0, "flow_id": "full_site_electricity_residual", "carrier_or_material": "electricity", "input_source": "official context only", "activity_basis": "TWh/y", "pyomo_component": "none", "pyomo_constraint_or_expression": "none", "annual_ledger_destination": "anchor_comparison.csv", "anchor_numerator_role": "reporting residual only", "classification": "diagnostic", "caveat": "Residual remains visible and never enters C0 as a model input."},
        {"configuration": C0, "flow_id": "full_site_ng_and_scope1_residual", "carrier_or_material": "natural_gas_and_CO2", "input_source": "official context only", "activity_basis": "PJ_LHV/y; MtCO2/y", "pyomo_component": "none", "pyomo_constraint_or_expression": "none", "annual_ledger_destination": "anchor_comparison.csv", "anchor_numerator_role": "reporting residual only", "classification": "blocked", "caveat": "No non-overlapping source-backed drivers exist for the missing C0 site boundary."},
    ])
    return rows


def _guardrails(
    audit: dict[str, Any],
    deadlines: list[dict[str, Any]],
    carriers: list[dict[str, Any]],
    utilities: list[dict[str, Any]],
    material: list[dict[str, Any]],
    schedule: dict[str, Any],
) -> list[dict[str, str]]:
    utility = {str(row["metric"]): row for row in utilities}
    material_status = {str(row["metric"]): str(row["source_basis_status"]) for row in material}
    gross = float(utility["gross_electricity"]["model_value"])
    offset = float(utility["internal_WAG_generator_electricity_offset"]["model_value"])
    net = float(utility["net_grid_import_after_internal_WAG_offset"]["model_value"])
    steam_demand = float(utility["modelled_steam_15bar_demand"]["model_value"])
    steam_supply = float(utility["modelled_steam_15bar_supply"]["model_value"])
    steam_unserved = float(utility["modelled_steam_15bar_unserved"]["model_value"])
    return [
        {"check_id": "BA_001", "check_name": "fixed_C0_binary_schedule", "status": "pass" if audit.get("fixed_binary_schedule_used") == "true" else "fail", "evidence": "fixed_binary_schedule_used in configuration audit", "action": "Do not introduce free C0 planning."},
        {"check_id": "BA_002", "check_name": "rolling_final_product_deadlines", "status": "pass" if deadlines and all(row["status"] == "pass" for row in deadlines) else "fail", "evidence": "rolling_quota_deadlines.csv", "action": "Keep final-product proxy as the production denominator."},
        {"check_id": "BA_003", "check_name": "terminal_material_identities", "status": "pass" if all(abs(float(audit.get(key, 0.0))) <= TOLERANCE for key in ("coke_terminal_residual_t", "sinter_terminal_residual_t", "hot_iron_terminal_residual_t", "cold_slab_terminal_residual_t")) else "fail", "evidence": "configuration_build_audit.csv", "action": "Do not fill a material residual."},
        {"check_id": "BA_004", "check_name": "C0_coke_chain_unit_basis", "status": "pass" if material_status["coke_output"] == "source_backed_coke_output" and material_status["BF_coke_demand"] == "source_backed_BF_coke_per_hot_metal" else "blocked", "evidence": "material_ledger.csv", "action": "Require one source-backed C0 coal-to-coke and BF-coke basis reconciliation before changing the current equation."},
        {"check_id": "BA_005", "check_name": "carrier_specific_WAG_balance", "status": "pass" if all(row["balance_status"] == "pass" for row in carriers) else "fail", "evidence": "wag_carrier_ledger.csv", "action": "Keep BFG, COG and BOFG separate."},
        {"check_id": "BA_006", "check_name": "gross_equals_internal_offset_plus_net_import", "status": "pass" if abs(gross - offset - net) <= TOLERANCE else "fail", "evidence": "utility_energy_co2_ledger.csv", "action": "Report the represented electricity boundary only."},
        {"check_id": "BA_007", "check_name": "mapped_15bar_steam_identity", "status": "pass" if abs(steam_supply - steam_demand - steam_unserved) <= TOLERANCE else "fail", "evidence": "utility_energy_co2_ledger.csv", "action": "Do not extrapolate mapped steam to the complete site."},
        {"check_id": "BA_008", "check_name": "Mode_B_CO2_separate_from_process_counters", "status": "pass", "evidence": utility["WAG_explicit_combustion_CO2"]["caveat"], "action": "Do not convert this subtotal to Scope 1 or ETS."},
        {"check_id": "BA_009", "check_name": "residual_energy_not_a_model_input", "status": "pass", "evidence": "No residual electricity or NG variable is created by this reporting surface.", "action": "Keep residuals visible only in anchor reporting."},
        {"check_id": "BA_010", "check_name": "C0_gross_electricity_activity_basis", "status": "historical", "evidence": utility["gross_electricity"]["caveat"], "action": "Require source-backed activity drivers before treating C0 electricity as a comparable physical anchor."},
        {"check_id": "BA_011", "check_name": "HSM_DSP_origin_tags", "status": "blocked", "evidence": "origin_material_ledger.csv", "action": "C0 HSM is explicit; retain DSP as a zero-route blocker until an executable downstream DSP interface exists."},
        {"check_id": "BA_012", "check_name": "C0_fixed_schedule_source_basis", "status": "pass" if schedule["source_status"] == "source_backed_fixed_calendar" else "blocked", "evidence": "c0_fixed_schedule_basis.csv", "action": "Use a primary-source-backed fixed availability calendar before treating C0 dispatch as a physical baseline."},
    ]


def run_c0_fixed_schedule_reporting(*, config_path: str | Path = DEFAULT_CONFIG, output_root: str | Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    config = _load_config(config_path)
    root = Path(output_root).resolve()
    run_directory = root / str(config["run_id"])
    if run_directory.exists():
        raise ValueError(f"Run directory already exists: {run_directory}")
    c1_directory = root / str(config["canonical_c1_run_id"])
    required_c1 = ("run_summary.json", "resolved_config.yaml", "utility_energy_co2_ledger.csv", "wag_carrier_ledger.csv", "guardrail_checks.csv", "physical_flow_trace.csv")
    missing_c1 = [name for name in required_c1 if not (c1_directory / name).exists()]
    if missing_c1:
        raise FileNotFoundError(f"Canonical C1 run lacks required trace artifacts: {missing_c1}")
    c1_summary = json.loads((c1_directory / "run_summary.json").read_text(encoding="utf-8"))
    if not str(c1_summary.get("status", "")).startswith("pass"):
        raise ValueError("Canonical C1 source run has no accepted physical result.")

    plan = build_rolling_production_quota_plan(
        planning_horizon_hours=int(config["planning_horizon_hours"]),
        execution_block_hours=int(config["execution_block_hours"]),
        quota_per_execution_block_t=float(config["quota_per_execution_block_t"]),
    )
    multiplier = plan.total_quota_t / float(config["base_quota_per_execution_block_t"])
    validation = validate_unified_dev_inputs(S44B_INPUT_DIR)
    if validation["failure_count"]:
        raise ValueError("Current unified C0/C1 input validation must pass before a C0 reporting run.")
    tables = _load_tables(S44B_INPUT_DIR)
    schedule = config["c0_fixed_schedule"]
    schedule_basis = _schedule_basis_rows(schedule)
    infeasibility_diagnostics = _fixed_schedule_coke_diagnostic(tables, config["source_coke_chain"], schedule)
    run_directory.mkdir(parents=True)
    audit, constraints, hourly = _solve_c0_configuration(
        tables,
        horizon_hours_override=plan.planning_horizon_hours,
        target_multiplier=multiplier,
        fix_binary_schedule=True,
        enable_minimal_wag_layer=True,
        enable_internal_wag_power=True,
        development_controller_activation=str(config["development_controller_activation"]),
        daily_production_guardrail=False,
        rolling_production_deadline_targets_t=plan.cumulative_deadline_targets_t,
        commitment_granularity="hourly_binary",
        solver_time_limit_seconds=float(config.get("solver_time_limit_seconds", 120.0)),
        c0_coke_chain_reconciliation={key: float(value) for key, value in config["source_coke_chain"].items()},
        c0_fixed_schedule_hours_by_process=schedule["active_hours_by_process"],
    )
    deadlines = _deadline_rows(hourly, plan.cumulative_deadline_targets_t) if audit.get("build_status") == "solved" else []
    material = _material_rows(hourly, plan.planning_horizon_hours, source_coke_chain_active=True) if hourly else []
    carriers = _carrier_rows(hourly, plan.planning_horizon_hours) if hourly else []
    sinks = _sink_rows(hourly, plan.planning_horizon_hours) if hourly else []
    utilities = _utility_rows(hourly, plan.planning_horizon_hours) if hourly else []
    origin = _origin_rows(material) if material else []
    anchors = _anchor_rows(utilities, carriers) if utilities else []
    canonical_anchors = _canonical_anchor_matrix(anchors, c1_directory, str(config["run_id"]))
    flow_trace = _flow_trace(material, sinks, utilities) if utilities else []
    checks = _guardrails(audit, deadlines, carriers, utilities, material, schedule) if utilities else [
        {"check_id": "BA_000", "check_name": "C0_accepted_solution", "status": "fail", "evidence": str(audit.get("caveat", "no solution")), "action": "Do not infer a physical ledger from an unsolved C0 surface."},
        {"check_id": "BA_012", "check_name": "C0_fixed_schedule_source_basis", "status": "blocked", "evidence": "c0_fixed_schedule_basis.csv", "action": "Use a primary-source-backed fixed availability calendar before treating C0 dispatch as a physical baseline."},
        {"check_id": "BA_013", "check_name": "C0_final_product_denominator_source_basis", "status": "blocked", "evidence": "production_targets.csv; DSP_Parameters.md", "action": "Replace the development-only 24-hour C0 target with an executable origin-tagged HSM/DSP denominator before annual C0 reporting."},
    ]
    check_counts = {status: sum(1 for row in checks if row["status"] == status) for status in sorted({row["status"] for row in checks})}
    summary = {
        "run_id": config["run_id"],
        "stage": STAGE,
        "status": "pass_with_reporting_blocks" if audit.get("build_status") == "solved" and not any(row["status"] == "fail" for row in checks) else "blocked_no_accepted_source_corrected_C0_solution",
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "retention": config["retention"],
        "configuration": C0,
        "canonical_c1_run_id": config["canonical_c1_run_id"],
        "c1_status": c1_summary["status"],
        "planning_horizon_hours": plan.planning_horizon_hours,
        "execution_block_hours": plan.execution_block_hours,
        "annualisation_factor": HOURS_PER_YEAR / plan.planning_horizon_hours,
        "fixed_c0_binary_schedule": True,
        "fixed_schedule_id": schedule["schedule_id"],
        "fixed_schedule_source_status": schedule["source_status"],
        "solver_status": audit.get("solver_status", ""),
        "termination_condition": audit.get("termination_condition", ""),
        "objective_value": audit.get("objective_value", ""),
        "runtime_seconds": audit.get("runtime_seconds", ""),
        "mip_gap": audit.get("mip_gap", ""),
        "variable_count": audit.get("variable_count", ""),
        "binary_count": audit.get("binary_count", ""),
        "constraint_count": audit.get("constraint_count", ""),
        "guardrail_counts": check_counts,
        "anchor_comparability_counts": {status: sum(1 for row in anchors if row["comparability_status"] == status) for status in sorted({row["comparability_status"] for row in anchors})},
        "canonical_anchor_matrix_rows": len(canonical_anchors),
        "canonical_anchor_matrix_unique_anchor_ids": len({row["anchor_id"] for row in canonical_anchors}),
        "canonical_anchor_matrix_status_counts": {status: sum(1 for row in canonical_anchors if row["comparability_status"] == status) for status in sorted({row["comparability_status"] for row in canonical_anchors})},
        "source_basis_blockers": [row["check_name"] for row in checks if row["status"] == "blocked"] or ["source_corrected_fixed_schedule_no_accepted_solution"],
        "infeasibility_diagnostics": infeasibility_diagnostics,
        "ready_for_cost_design": False,
        "reason_not_ready": "The sourced C0 coke chain is applied, but the inherited fixed schedule has no source-backed availability locator and is infeasible under its declared hours. No C0 anchor is promoted to comparable scoring; the gross-electricity proxy remains historical.",
    }
    resolved = dict(config)
    resolved["deadline_targets_t"] = plan.cumulative_deadline_targets_t
    resolved["model_target_multiplier"] = multiplier
    resolved["annualisation_factor"] = HOURS_PER_YEAR / plan.planning_horizon_hours
    _write_csv(run_directory / "configuration_build_audit.csv", [audit])
    _write_csv(run_directory / "constraint_audit.csv", constraints)
    _write_csv(run_directory / "hourly_dispatch.csv", hourly)
    _write_csv(run_directory / "rolling_quota_deadlines.csv", deadlines)
    _write_csv(run_directory / "infeasibility_diagnostics.csv", infeasibility_diagnostics)
    _write_csv(run_directory / "c0_fixed_schedule_basis.csv", schedule_basis)
    _write_csv(run_directory / "material_ledger.csv", material)
    _write_csv(run_directory / "wag_carrier_ledger.csv", carriers)
    _write_csv(run_directory / "wag_sink_mix_ledger.csv", sinks)
    _write_csv(run_directory / "utility_energy_co2_ledger.csv", utilities)
    _write_csv(run_directory / "origin_material_ledger.csv", origin)
    _write_csv(run_directory / "anchor_comparison.csv", anchors)
    _write_csv(run_directory / "canonical_anchor_reconciliation.csv", canonical_anchors)
    _write_csv(run_directory / "physical_flow_trace.csv", flow_trace)
    _write_csv(run_directory / "guardrail_checks.csv", checks)
    _write_json(run_directory / "run_summary.json", summary)
    _write_json(run_directory / "registry_entry.json", {"run_id": config["run_id"], "run_class": config["run_class"], "lineage_role": config["lineage_role"], "output_policy": config["output_policy"], "git_eligible": False})
    _write_json(run_directory / "code_version.json", {"git_revision": _git_revision(), "timestamp_utc": datetime.now(timezone.utc).isoformat(), "module": __file__})
    _write_json(run_directory / "input_manifest.json", {
        "config": _file_record(config_path),
        "canonical_c1_run": {name: _file_record(c1_directory / name) for name in required_c1},
        "unified_input_files": [_file_record(path) for path in sorted(S44B_INPUT_DIR.glob("*.csv"))],
        "source_files": [_file_record(ANCHOR_REGISTER)],
    })
    (run_directory / "resolved_config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8")
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a C0 reporting-only run with the governed fixed binary schedule; it does not allow free C0 planning.\n"
        "- The C0 dry-coal-to-coke and BF-coke-demand bases are applied explicitly; they do not justify the inherited fixed schedule.\n"
        "- The inherited C0 fixed schedule is traced in c0_fixed_schedule_basis.csv and is not a source-backed availability calendar.\n"
        "- The C0 sinter/burden and gross-electricity bases remain historical/development reporting surfaces, not comparable annual anchors.\n"
        "- BFG, COG and BOFG remain separate. Aggregate or mixed WAG is never allocated physically.\n"
        "- Electricity and full-site NG residuals remain visible comparisons only; they never enter the model.\n"
        "- Mode-B CO2 excludes aggregate process counters and is not Scope 1 or ETS-ready.\n",
        encoding="utf-8",
    )
    return {"run_directory": run_directory, "summary": summary, "audit": audit, "checks": checks}
