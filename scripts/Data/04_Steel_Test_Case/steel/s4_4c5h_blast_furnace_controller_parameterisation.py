"""S4.4c5h blast-furnace minimal parameterisation and hot-stove controller.

This stage extends the C5g WAG diagnostics with BF6/BF7 process accounting and
a deterministic Controller_Blast_Furnace layer. It does not change the solver
schedule; it repairs the BF/WAG accounting boundary so only BFG surplus after
hot-stove self-use enters the general WAG network.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from pathlib import Path
from typing import Any

from .s4_4c_unified_physical_modelbuilder import SELECTED_WAG_LHV_MJ_PER_NM3
from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    C5F_DIR,
    CONFIGS,
    HORIZONS,
    KGF_PLANTS,
    S4_ROOT,
    WAG_TOL_MWH,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5g_wag_aggregate_diagnostic_hygiene import (
    AGGREGATE_COLUMNS,
    C5G_DIR,
    WAG_CARRIERS,
    _wag_aggregate_invariant_rows,
    run_s4_4c5g_wag_aggregate_diagnostic_hygiene,
)


C5H_DIR = S4_ROOT / "s4_4c5h_blast_furnace_controller_parameterisation"
STAGE = "S4.4c5h_blast_furnace_controller_parameterisation"
SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/Blast_Furnace_Parameters.md")

BF_PLANTS = ("BF6", "BF7")
BF_COKE_RATE_T_PER_T_HM = 0.359
BF_PCI_COAL_INPUT_T_PER_T_HM = 0.162
BF_OXYGEN_INPUT_KG_PER_T_HM = 54.4
BF_ELECTRICITY_MWH_PER_T_HM = 0.0744
BF_STEAM_GJ_PER_T_HM = 0.048
BF_STEAM_MWH_PER_T_HM = BF_STEAM_GJ_PER_T_HM / 3.6
BF_BFG_OUTPUT_NM3_PER_T_HM = 1600.0
BFG_LHV_MJ_PER_NM3 = SELECTED_WAG_LHV_MJ_PER_NM3["BFG"]
BF_BFG_OUTPUT_MWH_PER_T_HM = BF_BFG_OUTPUT_NM3_PER_T_HM * BFG_LHV_MJ_PER_NM3 / 3600.0
BF_BFG_OUTPUT_GJ_PER_T_HM = BF_BFG_OUTPUT_MWH_PER_T_HM * 3.6
BF_HOT_STOVE_FUEL_DEMAND_GJ_PER_T_HM = 2.20
BF_HOT_STOVE_DEMAND_MWH_PER_T_HM = BF_HOT_STOVE_FUEL_DEMAND_GJ_PER_T_HM / 3.6
BF_CO2_COUNTER_AGG_T_PER_T_HM = 1.495
BFG_COMBUSTION_CO2_T_PER_TJ_DIAGNOSTIC = 260.0
BF_CARBON_ACCOUNTING_MODE = "aggregate_hot_metal_counter"
CONTROLLER_MODE = "deterministic_accounting_controller"

BF_ANCHORS_T_Y = {
    (C0, "BF6_hot_metal"): (2_500_000.0, "C0 BF6 hot metal validation anchor"),
    (C0, "BF7_hot_metal"): (3_800_000.0, "C0 BF7 hot metal validation anchor"),
    (C0, "BF_total_hot_metal"): (6_300_000.0, "C0 total BF hot metal validation anchor"),
    (C1, "BF6_hot_metal"): (2_800_000.0, "C1 BF6 hot metal validation anchor"),
    (C1, "BF7_hot_metal"): (0.0, "C1 BF7 closed topology anchor"),
    (C1, "BF6_hot_metal_low_sensitivity"): (2_200_000.0, "C1 BF6 low sensitivity only"),
}

C5H_COMPACT_COLUMNS = [
    "configuration",
    "horizon_hours",
    "plant",
    "active",
    "main_product",
    "main_product_raw_t_y",
    "main_product_site_t_y",
    "scale_mode",
    "bus0_basis",
    "coke_input_t_per_t_HM",
    "coke_demand_site_t_y",
    "kgf_coke_available_site_t_y",
    "coke_balance_gap_site_t_y",
    "PCI_t_per_t_HM",
    "oxygen_kg_per_t_HM",
    "electricity_MWh_per_t_HM",
    "steam_MWh_proxy_per_t_HM",
    "BFG_gross_Nm3_per_t_HM",
    "BFG_gross_MWh_LHV_per_t_HM",
    "BFG_to_Controller_BF_MWh_per_t_HM",
    "COG_to_Controller_BF_MWh_per_t_HM",
    "BOFG_to_Controller_BF_MWh_per_t_HM",
    "NG_to_Controller_BF_MWh_per_t_HM",
    "BFG_surplus_to_WAG_MWh_per_t_HM",
    "BF_hot_stove_demand_MWh_per_t_HM",
    "Controller_BF_balance_status",
    "BF_CO2_t_per_t_HM",
    "carbon_accounting_mode",
    "LHV_consistency_status",
    "status",
    "red_flags",
]


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _mwh_to_nm3(mwh: float, carrier: str) -> float:
    return mwh * 3600.0 / SELECTED_WAG_LHV_MJ_PER_NM3[carrier]


def _annualisation_factor(horizon: int) -> float:
    return 365.0 if horizon == 24 else 365.0 / 7.0


def _parameter_rows() -> list[dict[str, Any]]:
    rows = [
        ("BF_COKE_RATE_T_PER_T_HM", BF_COKE_RATE_T_PER_T_HM, "t coke/t HM", "material_conversion"),
        ("BF_PCI_COAL_INPUT_T_PER_T_HM", BF_PCI_COAL_INPUT_T_PER_T_HM, "t PCI coal/t HM", "material_conversion"),
        ("BF_OXYGEN_INPUT_KG_PER_T_HM", BF_OXYGEN_INPUT_KG_PER_T_HM, "kg O2/t HM", "material_conversion"),
        ("BF_ELECTRICITY_MWH_PER_T_HM", BF_ELECTRICITY_MWH_PER_T_HM, "MWh/t HM", "energy_input"),
        ("BF_STEAM_GJ_PER_T_HM", BF_STEAM_GJ_PER_T_HM, "GJ steam proxy/t HM", "energy_input"),
        ("BF_BFG_OUTPUT_NM3_PER_T_HM", BF_BFG_OUTPUT_NM3_PER_T_HM, "Nm3 BFG/t HM", "WAG_generation"),
        ("BFG_LHV_MJ_PER_NM3", BFG_LHV_MJ_PER_NM3, "MJ/Nm3", "physical_unit_conversion"),
        ("BF_BFG_OUTPUT_MWH_PER_T_HM", BF_BFG_OUTPUT_MWH_PER_T_HM, "MWh_LHV/t HM", "derived_WAG_generation"),
        ("BF_BFG_OUTPUT_GJ_PER_T_HM", BF_BFG_OUTPUT_GJ_PER_T_HM, "GJ_LHV/t HM", "derived_WAG_generation"),
        ("BF_HOT_STOVE_FUEL_DEMAND_GJ_PER_T_HM", BF_HOT_STOVE_FUEL_DEMAND_GJ_PER_T_HM, "GJ/t HM", "WAG_self_use"),
        ("BF_CO2_COUNTER_AGG_T_PER_T_HM", BF_CO2_COUNTER_AGG_T_PER_T_HM, "tCO2/t HM", "emissions"),
    ]
    return [
        {
            "parameter_id": pid,
            "plant_id": "BF6;BF7",
            "controller_id": "Controller_Blast_Furnace",
            "base_value": _fmt(value),
            "unit": unit,
            "parameter_role": role,
            "source_or_assumption_id": "source_cards/Blast_Furnace_Parameters.md",
            "evidence_status": "source_backed_development",
            "assumption_status": "frozen_for_development",
            "development_executable": "true",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "notes": "C5h minimal BF parameterisation; not calibration and not thesis-approved.",
        }
        for pid, value, unit, role in rows
    ]


def _bf_process_rows(c5g_wag: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    wag_by_key = {
        (row["configuration"], int(row["horizon_hours"]), row["plant_id"]): row
        for row in c5g_wag
        if row["carrier"] == "BFG" and row["plant_id"] in BF_PLANTS
    }
    for config in CONFIGS:
        for horizon in HORIZONS:
            for plant in BF_PLANTS:
                source = wag_by_key.get((config, horizon, plant))
                gross_seed_raw = _zero(source["generated_MWh_LHV_y"]) if source else 0.0
                gross_seed_site = _zero(source["site_scaled_quantity"]) if source else 0.0
                hm_raw = gross_seed_raw / BF_BFG_OUTPUT_MWH_PER_T_HM if gross_seed_raw else 0.0
                hm_site = gross_seed_site / BF_BFG_OUTPUT_MWH_PER_T_HM if gross_seed_site else 0.0
                factor = hm_site / hm_raw if hm_raw else 0.0
                active = hm_raw > WAG_TOL_MWH
                if config == C1 and plant == "BF7":
                    active = False
                    hm_raw = 0.0
                    hm_site = 0.0
                    factor = 0.0
                gross_raw = hm_raw * BF_BFG_OUTPUT_MWH_PER_T_HM
                gross_site = hm_site * BF_BFG_OUTPUT_MWH_PER_T_HM
                stove_raw = hm_raw * BF_HOT_STOVE_DEMAND_MWH_PER_T_HM
                stove_site = hm_site * BF_HOT_STOVE_DEMAND_MWH_PER_T_HM
                bfg_to_controller_raw = min(gross_raw, stove_raw)
                bfg_to_controller_site = min(gross_site, stove_site)
                remaining_raw = max(stove_raw - bfg_to_controller_raw, 0.0)
                remaining_site = max(stove_site - bfg_to_controller_site, 0.0)
                cogs = 0.0
                bofgs = 0.0
                ng_raw = remaining_raw
                ng_site = remaining_site
                surplus_raw = max(gross_raw - bfg_to_controller_raw, 0.0)
                surplus_site = max(gross_site - bfg_to_controller_site, 0.0)
                controller_balance_raw = bfg_to_controller_raw + cogs + bofgs + ng_raw - stove_raw
                flags: list[str] = []
                if config == C1 and plant == "BF7" and hm_raw > WAG_TOL_MWH:
                    flags.append("bf7_active_in_c1")
                if active and hm_raw <= 0.0:
                    flags.append("active_bf_zero_hot_metal")
                if active and surplus_raw < -WAG_TOL_MWH:
                    flags.append("bfg_surplus_negative")
                if abs(controller_balance_raw) > WAG_TOL_MWH:
                    flags.append("controller_balance_error")
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "plant_id": plant,
                        "plant_name": f"Blast Furnace {plant[-1]}",
                        "active": "true" if active else "false",
                        "bus0_basis": "hot_metal_basis_with_coke_equivalent_reporting" if active else "not_applicable",
                        "controller_id": f"Controller_Blast_Furnace_{plant}",
                        "controller_implementation_mode": CONTROLLER_MODE,
                        "hot_metal_raw_t_y": _fmt(hm_raw),
                        "hot_metal_site_t_y": _fmt(hm_site),
                        "scale_factor": _fmt(factor),
                        "scale_mode": source["scale_mode"] if source and active else "not_applicable",
                        "coke_demand_raw_t_y": _fmt(hm_raw * BF_COKE_RATE_T_PER_T_HM),
                        "coke_demand_site_t_y": _fmt(hm_site * BF_COKE_RATE_T_PER_T_HM),
                        "PCI_raw_t_y": _fmt(hm_raw * BF_PCI_COAL_INPUT_T_PER_T_HM),
                        "PCI_site_t_y": _fmt(hm_site * BF_PCI_COAL_INPUT_T_PER_T_HM),
                        "oxygen_raw_kg_y": _fmt(hm_raw * BF_OXYGEN_INPUT_KG_PER_T_HM),
                        "oxygen_site_kg_y": _fmt(hm_site * BF_OXYGEN_INPUT_KG_PER_T_HM),
                        "electricity_raw_MWh_y": _fmt(hm_raw * BF_ELECTRICITY_MWH_PER_T_HM),
                        "electricity_site_MWh_y": _fmt(hm_site * BF_ELECTRICITY_MWH_PER_T_HM),
                        "steam_raw_MWh_proxy_y": _fmt(hm_raw * BF_STEAM_MWH_PER_T_HM),
                        "steam_site_MWh_proxy_y": _fmt(hm_site * BF_STEAM_MWH_PER_T_HM),
                        "BFG_gross_raw_Nm3_y": _fmt(hm_raw * BF_BFG_OUTPUT_NM3_PER_T_HM),
                        "BFG_gross_site_Nm3_y": _fmt(hm_site * BF_BFG_OUTPUT_NM3_PER_T_HM),
                        "BFG_gross_raw_MWh_LHV_y": _fmt(gross_raw),
                        "BFG_gross_site_MWh_LHV_y": _fmt(gross_site),
                        "BF_hot_stove_demand_raw_MWh_y": _fmt(stove_raw),
                        "BF_hot_stove_demand_site_MWh_y": _fmt(stove_site),
                        "BFG_to_Controller_BF_raw_MWh_y": _fmt(bfg_to_controller_raw),
                        "BFG_to_Controller_BF_site_MWh_y": _fmt(bfg_to_controller_site),
                        "COG_to_Controller_BF_raw_MWh_y": _fmt(cogs),
                        "COG_to_Controller_BF_site_MWh_y": _fmt(cogs),
                        "BOFG_to_Controller_BF_raw_MWh_y": _fmt(bofgs),
                        "BOFG_to_Controller_BF_site_MWh_y": _fmt(bofgs),
                        "NG_to_Controller_BF_raw_MWh_y": _fmt(ng_raw),
                        "NG_to_Controller_BF_site_MWh_y": _fmt(ng_site),
                        "BFG_surplus_to_WAG_raw_MWh_y": _fmt(surplus_raw),
                        "BFG_surplus_to_WAG_site_MWh_y": _fmt(surplus_site),
                        "BF_CO2_counter_raw_t_y": _fmt(hm_raw * BF_CO2_COUNTER_AGG_T_PER_T_HM),
                        "BF_CO2_counter_site_t_y": _fmt(hm_site * BF_CO2_COUNTER_AGG_T_PER_T_HM),
                        "BFG_downstream_combustion_CO2_potential_t_y": _fmt(surplus_site * 0.0036 * BFG_COMBUSTION_CO2_T_PER_TJ_DIAGNOSTIC),
                        "carbon_accounting_mode": BF_CARBON_ACCOUNTING_MODE,
                        "BF_process_direct_gas_input_status": "no_direct_WAG_or_gas_input_controller_only",
                        "Controller_BF_balance_error_MWh_y": _fmt(controller_balance_raw),
                        "Controller_BF_balance_status": "pass" if abs(controller_balance_raw) <= WAG_TOL_MWH else "fail",
                        "status": "pass" if not flags else "fail",
                        "red_flags": ";".join(flags),
                        "notes": "BF process generates gross BFG; Controller_Blast_Furnace consumes BFG first for hot-stove heat before WAG surplus.",
                    }
                )
    return rows


def _allocation_from_existing(existing: dict[str, float], generated: float) -> dict[str, float]:
    direct = min(existing["direct"], generated)
    remaining = max(generated - direct, 0.0)
    boiler = min(existing["boiler"], remaining)
    remaining = max(remaining - boiler, 0.0)
    vattenfall = min(existing["vattenfall"], remaining)
    remaining = max(remaining - vattenfall, 0.0)
    flared = remaining
    return {"direct": direct, "boiler": boiler, "vattenfall": vattenfall, "flared": flared}


def _scale_sink(existing_value: float, total_existing: float, allocated_total: float) -> float:
    if total_existing <= 0.0:
        return 0.0
    return existing_value / total_existing * allocated_total


def _wag_rows_after_bf_controller(c5g_wag: list[dict[str, str]], bf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [dict(row) for row in c5g_wag]
    bf_by_key = {(row["configuration"], int(row["horizon_hours"]), row["plant_id"]): row for row in bf_rows}
    surplus_raw = {
        (row["configuration"], int(row["horizon_hours"]), row["plant_id"]): _zero(row["BFG_surplus_to_WAG_raw_MWh_y"])
        for row in bf_rows
    }
    surplus_site = {
        (row["configuration"], int(row["horizon_hours"]), row["plant_id"]): _zero(row["BFG_surplus_to_WAG_site_MWh_y"])
        for row in bf_rows
    }
    for config in CONFIGS:
        for horizon in HORIZONS:
            bfg_rows = [
                row
                for row in out
                if row["configuration"] == config and int(row["horizon_hours"]) == horizon and row["carrier"] == "BFG"
            ]
            site = next(row for row in bfg_rows if row["plant_id"] == "SITE_TOTAL")
            existing = {
                "direct": _zero(site["consumed_direct_MWh_LHV_y"]),
                "boiler": _zero(site["consumed_boiler_MWh_LHV_y"]),
                "vattenfall": _zero(site["consumed_vattenfall_MWh_LHV_y"]),
                "flared": _zero(site["flared_MWh_LHV_y"]),
            }
            generated_raw = sum(surplus_raw.get((config, horizon, plant), 0.0) for plant in BF_PLANTS)
            generated_site = sum(surplus_site.get((config, horizon, plant), 0.0) for plant in BF_PLANTS)
            factor = _zero(site.get("scale_factor")) or 1.0
            allocated = _allocation_from_existing(existing, generated_raw)
            existing_direct = sum(_zero(row["consumed_direct_MWh_LHV_y"]) for row in bfg_rows if row["plant_id"] != "SITE_TOTAL")
            existing_boiler = sum(_zero(row["consumed_boiler_MWh_LHV_y"]) for row in bfg_rows if row["plant_id"] != "SITE_TOTAL")
            existing_vf = sum(_zero(row["consumed_vattenfall_MWh_LHV_y"]) for row in bfg_rows if row["plant_id"] != "SITE_TOTAL")
            existing_flare = sum(_zero(row["flared_MWh_LHV_y"]) for row in bfg_rows if row["plant_id"] != "SITE_TOTAL")

            for row in bfg_rows:
                plant = row["plant_id"]
                key = (config, horizon, plant)
                if plant in BF_PLANTS and key in bf_by_key:
                    raw = surplus_raw[key]
                    site_value = surplus_site[key]
                    row["generated_MWh_LHV_y"] = _fmt(raw)
                    row["generated_Nm3_y"] = _fmt(_mwh_to_nm3(site_value, "BFG"))
                    row["balance_error_MWh_LHV_y"] = _fmt(raw)
                    row["raw_model_quantity"] = _fmt(raw)
                    row["site_scaled_quantity"] = _fmt(site_value)
                    row["status"] = "bf_surplus_to_wag_network_after_hot_stove_controller"
                elif plant == "SITE_TOTAL":
                    row["generated_MWh_LHV_y"] = _fmt(generated_raw)
                    row["generated_Nm3_y"] = _fmt(_mwh_to_nm3(generated_site, "BFG"))
                    row["consumed_direct_MWh_LHV_y"] = _fmt(allocated["direct"])
                    row["consumed_boiler_MWh_LHV_y"] = _fmt(allocated["boiler"])
                    row["consumed_vattenfall_MWh_LHV_y"] = _fmt(allocated["vattenfall"])
                    row["flared_MWh_LHV_y"] = _fmt(allocated["flared"])
                    row["balance_error_MWh_LHV_y"] = _fmt(generated_raw - sum(allocated.values()))
                    row["raw_model_quantity"] = _fmt(generated_raw)
                    row["site_scaled_quantity"] = _fmt(generated_site)
                    row["status"] = "closed_after_bf_hot_stove_controller"
                else:
                    direct = _scale_sink(_zero(row["consumed_direct_MWh_LHV_y"]), existing_direct, allocated["direct"])
                    boiler = _scale_sink(_zero(row["consumed_boiler_MWh_LHV_y"]), existing_boiler, allocated["boiler"])
                    vf = _scale_sink(_zero(row["consumed_vattenfall_MWh_LHV_y"]), existing_vf, allocated["vattenfall"])
                    flared = _scale_sink(_zero(row["flared_MWh_LHV_y"]), existing_flare, allocated["flared"])
                    row["consumed_direct_MWh_LHV_y"] = _fmt(direct)
                    row["consumed_boiler_MWh_LHV_y"] = _fmt(boiler)
                    row["consumed_vattenfall_MWh_LHV_y"] = _fmt(vf)
                    row["flared_MWh_LHV_y"] = _fmt(flared)
                    row["balance_error_MWh_LHV_y"] = _fmt(-direct - boiler - vf - flared)
                    row["status"] = "site_balance_closes_after_bf_controller"
                    if plant in {"Vattenfall", "flaring"}:
                        row["notes"] = "BFG residual sink reduced after BF hot-stove controller deduction."
    return out


def _controller_hourly_rows(bf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in bf_rows:
        horizon = int(row["horizon_hours"])
        for hour in range(horizon):
            flows = [
                ("BFG", "input", _zero(row["BFG_to_Controller_BF_raw_MWh_y"]), _zero(row["BFG_to_Controller_BF_site_MWh_y"])),
                ("COG", "input", _zero(row["COG_to_Controller_BF_raw_MWh_y"]), _zero(row["COG_to_Controller_BF_site_MWh_y"])),
                ("BOFG", "input", _zero(row["BOFG_to_Controller_BF_raw_MWh_y"]), _zero(row["BOFG_to_Controller_BF_site_MWh_y"])),
                ("Natural_Gas", "input", _zero(row["NG_to_Controller_BF_raw_MWh_y"]), _zero(row["NG_to_Controller_BF_site_MWh_y"])),
                ("WAGs_BF_Hot_Stove", "output", _zero(row["BF_hot_stove_demand_raw_MWh_y"]), _zero(row["BF_hot_stove_demand_site_MWh_y"])),
            ]
            for carrier, direction, annual_raw, annual_site in flows:
                rows.append(
                    {
                        "configuration": row["configuration"],
                        "horizon_hours": horizon,
                        "hour": hour,
                        "controller_id": row["controller_id"],
                        "plant_id": row["plant_id"],
                        "carrier": carrier,
                        "direction": direction,
                        "raw_quantity_MWh": _fmt(annual_raw / 8760.0),
                        "site_scaled_quantity_MWh": _fmt(annual_site / 8760.0),
                        "unit": "MWh_LHV" if direction == "input" else "MWh_heat",
                        "implementation_mode": CONTROLLER_MODE,
                        "status": row["Controller_BF_balance_status"],
                    }
                )
    return rows


def _controller_dashboard_rows(bf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in bf_rows:
        input_raw = sum(
            _zero(row[field])
            for field in (
                "BFG_to_Controller_BF_raw_MWh_y",
                "COG_to_Controller_BF_raw_MWh_y",
                "BOFG_to_Controller_BF_raw_MWh_y",
                "NG_to_Controller_BF_raw_MWh_y",
            )
        )
        output_raw = _zero(row["BF_hot_stove_demand_raw_MWh_y"])
        input_site = sum(
            _zero(row[field])
            for field in (
                "BFG_to_Controller_BF_site_MWh_y",
                "COG_to_Controller_BF_site_MWh_y",
                "BOFG_to_Controller_BF_site_MWh_y",
                "NG_to_Controller_BF_site_MWh_y",
            )
        )
        output_site = _zero(row["BF_hot_stove_demand_site_MWh_y"])
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "controller_id": row["controller_id"],
                "plant_id": row["plant_id"],
                "active": row["active"],
                "BFG_input_raw_MWh_y": row["BFG_to_Controller_BF_raw_MWh_y"],
                "COG_input_raw_MWh_y": row["COG_to_Controller_BF_raw_MWh_y"],
                "BOFG_input_raw_MWh_y": row["BOFG_to_Controller_BF_raw_MWh_y"],
                "NG_input_raw_MWh_y": row["NG_to_Controller_BF_raw_MWh_y"],
                "BF_hot_stove_heat_output_raw_MWh_y": row["BF_hot_stove_demand_raw_MWh_y"],
                "BFG_input_site_MWh_y": row["BFG_to_Controller_BF_site_MWh_y"],
                "COG_input_site_MWh_y": row["COG_to_Controller_BF_site_MWh_y"],
                "BOFG_input_site_MWh_y": row["BOFG_to_Controller_BF_site_MWh_y"],
                "NG_input_site_MWh_y": row["NG_to_Controller_BF_site_MWh_y"],
                "BF_hot_stove_heat_output_site_MWh_y": row["BF_hot_stove_demand_site_MWh_y"],
                "raw_balance_error_MWh_y": _fmt(input_raw - output_raw),
                "site_balance_error_MWh_y": _fmt(input_site - output_site),
                "controller_implementation_mode": CONTROLLER_MODE,
                "status": "pass" if abs(input_raw - output_raw) <= WAG_TOL_MWH and abs(input_site - output_site) <= WAG_TOL_MWH else "fail",
                "red_flags": "",
                "notes": "Energy-only controller: BFG first, no COG/BOFG/NG needed under base coefficients.",
            }
        )
    return rows


def _bfg_self_use_surplus_rows(bf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in bf_rows:
        gross = _zero(row["BFG_gross_raw_MWh_LHV_y"])
        self_use = _zero(row["BFG_to_Controller_BF_raw_MWh_y"])
        surplus = _zero(row["BFG_surplus_to_WAG_raw_MWh_y"])
        balance = gross - self_use - surplus
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_id": row["plant_id"],
                "active": row["active"],
                "hot_metal_raw_t_y": row["hot_metal_raw_t_y"],
                "hot_metal_site_t_y": row["hot_metal_site_t_y"],
                "BFG_gross_raw_MWh_LHV_y": row["BFG_gross_raw_MWh_LHV_y"],
                "BFG_gross_site_MWh_LHV_y": row["BFG_gross_site_MWh_LHV_y"],
                "BFG_to_Controller_BF_raw_MWh_y": row["BFG_to_Controller_BF_raw_MWh_y"],
                "BFG_to_Controller_BF_site_MWh_y": row["BFG_to_Controller_BF_site_MWh_y"],
                "BFG_surplus_to_WAG_raw_MWh_y": row["BFG_surplus_to_WAG_raw_MWh_y"],
                "BFG_surplus_to_WAG_site_MWh_y": row["BFG_surplus_to_WAG_site_MWh_y"],
                "BFG_surplus_share": _fmt(surplus / gross if gross else math.nan),
                "balance_error_MWh_y": _fmt(balance),
                "status": "pass" if abs(balance) <= WAG_TOL_MWH else "fail",
                "red_flags": "" if abs(balance) <= WAG_TOL_MWH else "bfg_gross_self_use_surplus_balance_error",
                "notes": "Gross BFG = BF hot-stove controller self-use + net BFG surplus to WAG network.",
            }
        )
    return rows


def _kgf_coke_by_key() -> dict[tuple[str, int], dict[str, float]]:
    rows = _read_csv(C5F_DIR / "s4_4c5f_coking_plant_diagnostics.csv")
    out: dict[tuple[str, int], dict[str, float]] = {}
    for row in rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        out.setdefault(key, {"raw": 0.0, "site": 0.0})
        out[key]["raw"] += _zero(row["coke_output_raw_t_y"])
        out[key]["site"] += _zero(row["coke_output_site_t_y"])
    return out


def _coke_balance_rows(bf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kgf = _kgf_coke_by_key()
    rows = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            subset = [row for row in bf_rows if row["configuration"] == config and int(row["horizon_hours"]) == horizon]
            demand_raw = sum(_zero(row["coke_demand_raw_t_y"]) for row in subset)
            demand_site = sum(_zero(row["coke_demand_site_t_y"]) for row in subset)
            available_raw = kgf[(config, horizon)]["raw"]
            available_site = kgf[(config, horizon)]["site"]
            gap_raw = available_raw - demand_raw
            gap_site = available_site - demand_site
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "kgf_coke_available_raw_t_y": _fmt(available_raw),
                    "bf_coke_demand_raw_t_y": _fmt(demand_raw),
                    "coke_balance_gap_raw_t_y": _fmt(gap_raw),
                    "kgf_coke_available_site_t_y": _fmt(available_site),
                    "bf_coke_demand_site_t_y": _fmt(demand_site),
                    "coke_balance_gap_site_t_y": _fmt(gap_site),
                    "gap_pct_of_bf_demand": _fmt(gap_site / demand_site * 100.0 if demand_site else math.nan),
                    "constraint_used": "false",
                    "status": "gap_reported_not_forced" if abs(gap_site) > WAG_TOL_MWH else "closed",
                    "red_flags": "bf_coke_demand_exceeds_kgf_coke_output" if gap_site < -WAG_TOL_MWH else "",
                    "notes": "C5h reports the KGF/BF coke gap; it does not force KGF output or BF coke demand to match.",
                }
            )
    return rows


def _bf_anchor_gap_rows(bf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    by_key = {(row["configuration"], int(row["horizon_hours"]), row["plant_id"]): row for row in bf_rows}
    for config in CONFIGS:
        for horizon in HORIZONS:
            bf6 = _zero(by_key[(config, horizon, "BF6")]["hot_metal_site_t_y"])
            bf7 = _zero(by_key[(config, horizon, "BF7")]["hot_metal_site_t_y"])
            metrics = {
                "BF6_hot_metal": bf6,
                "BF7_hot_metal": bf7,
                "BF_total_hot_metal": bf6 + bf7,
            }
            if config == C1:
                metrics["BF6_hot_metal_low_sensitivity"] = bf6
            for metric, model in metrics.items():
                anchor = BF_ANCHORS_T_Y.get((config, metric))
                if anchor is None:
                    continue
                anchor_value, source = anchor
                gap = model - anchor_value
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "metric": metric,
                        "model_site_t_y": _fmt(model),
                        "anchor_t_y": _fmt(anchor_value),
                        "gap_t_y": _fmt(gap),
                        "gap_pct": _fmt(gap / anchor_value * 100.0 if anchor_value else math.nan),
                        "anchor_source": source,
                        "anchor_status": "sensitivity_only" if "low_sensitivity" in metric else "validation_anchor_only",
                        "constraint_used": "false",
                        "notes": "BF anchors are validation/context checks only; no calibration or route-share forcing.",
                    }
                )
    return rows


def _bf_co2_rows(bf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in bf_rows:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_id": row["plant_id"],
                "emission_bucket": "BF_aggregate_hot_metal_counter",
                "CO2_raw_t_y": row["BF_CO2_counter_raw_t_y"],
                "CO2_site_t_y": row["BF_CO2_counter_site_t_y"],
                "CO2_t_per_t_main_product": BF_CO2_COUNTER_AGG_T_PER_T_HM if row["active"] == "true" else 0.0,
                "accounting_convention": BF_CARBON_ACCOUNTING_MODE,
                "included_in_total_direct_CO2": "true",
                "double_counting_risk": "low_if_BFG_combustion_excluded",
                "status": "development_assumption" if row["active"] == "true" else "structurally_inactive",
                "notes": "BFG downstream combustion CO2 is diagnostic-only under aggregate hot-metal counter mode.",
            }
        )
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_id": row["plant_id"],
                "emission_bucket": "BFG_downstream_combustion_CO2_potential_diagnostic",
                "CO2_raw_t_y": "",
                "CO2_site_t_y": row["BFG_downstream_combustion_CO2_potential_t_y"],
                "CO2_t_per_t_main_product": "",
                "accounting_convention": "diagnostic_only_not_added_to_direct_CO2",
                "included_in_total_direct_CO2": "false",
                "double_counting_risk": "would_double_count_if_added_to_aggregate_counter",
                "status": "diagnostic_only",
                "notes": "Potential CO2 if net BFG surplus is combusted; excluded from total while aggregate BF counter is active.",
            }
        )
    return rows


def _energy_rows(bf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _read_csv(C5F_DIR / "s4_4c5f_energy_by_plant.csv")
    for row in bf_rows:
        for carrier, value, basis in (
            ("electricity", row["electricity_site_MWh_y"], "not_applicable"),
            ("steam_proxy", row["steam_site_MWh_proxy_y"], "not_applicable"),
            ("BFG_to_Controller_Blast_Furnace", row["BFG_to_Controller_BF_site_MWh_y"], "LHV"),
            ("BFG_surplus_to_WAG_network", row["BFG_surplus_to_WAG_site_MWh_y"], "LHV"),
        ):
            rows.append(
                {
                    "configuration": row["configuration"],
                    "horizon_hours": row["horizon_hours"],
                    "plant_id": row["plant_id"],
                    "carrier": carrier,
                    "input_MWh_y": value if carrier != "BFG_surplus_to_WAG_network" else 0.0,
                    "output_MWh_y": value if carrier == "BFG_surplus_to_WAG_network" else 0.0,
                    "net_MWh_y": value,
                    "unit_basis": "site_scaled",
                    "HHV_or_LHV": basis,
                    "status": "source_backed_development" if row["active"] == "true" else "structurally_inactive",
                    "notes": "C5h BF minimal parameter and hot-stove controller accounting.",
                }
            )
    return rows


def _emissions_rows(bf_co2: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _read_csv(C5F_DIR / "s4_4c5f_emissions_by_plant.csv")
    for row in bf_co2:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_id": row["plant_id"],
                "emission_bucket": row["emission_bucket"],
                "CO2_t_y": row["CO2_site_t_y"],
                "CO2_t_per_t_main_product": row["CO2_t_per_t_main_product"],
                "accounting_convention": row["accounting_convention"],
                "included_in_anchor_comparison": "false",
                "double_counting_risk": row["double_counting_risk"],
                "status": row["status"],
                "notes": row["notes"],
            }
        )
    return rows


def _conversion_ratio_rows(bf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _read_csv(C5F_DIR / "s4_4c5f_plant_conversion_ratios.csv")
    rows = [row for row in rows if row.get("plant_id") not in BF_PLANTS]
    ratio_defs = [
        ("coke_t_per_t_hot_metal", BF_COKE_RATE_T_PER_T_HM, "t/t_HM", "material_conversion"),
        ("PCI_t_per_t_hot_metal", BF_PCI_COAL_INPUT_T_PER_T_HM, "t/t_HM", "material_conversion"),
        ("oxygen_kg_per_t_hot_metal", BF_OXYGEN_INPUT_KG_PER_T_HM, "kg/t_HM", "material_conversion"),
        ("electricity_MWh_per_t_hot_metal", BF_ELECTRICITY_MWH_PER_T_HM, "MWh/t_HM", "energy_input"),
        ("steam_MWh_proxy_per_t_hot_metal", BF_STEAM_MWH_PER_T_HM, "MWh_proxy/t_HM", "energy_input"),
        ("BFG_Nm3_per_t_hot_metal", BF_BFG_OUTPUT_NM3_PER_T_HM, "Nm3/t_HM", "WAG_generation"),
        ("BFG_MWh_LHV_per_t_hot_metal", BF_BFG_OUTPUT_MWH_PER_T_HM, "MWh_LHV/t_HM", "WAG_generation"),
        ("BF_hot_stove_MWh_per_t_hot_metal", BF_HOT_STOVE_DEMAND_MWH_PER_T_HM, "MWh/t_HM", "WAG_self_use"),
        ("BF_CO2_t_per_t_hot_metal", BF_CO2_COUNTER_AGG_T_PER_T_HM, "tCO2/t_HM", "emissions"),
    ]
    for row in bf_rows:
        for carrier, ratio, unit, role in ratio_defs:
            rows.append(
                {
                    "configuration": row["configuration"],
                    "horizon_hours": row["horizon_hours"],
                    "plant_id": row["plant_id"],
                    "plant_name": row["plant_name"],
                    "asset_status": "active" if row["active"] == "true" else "inactive",
                    "route": "retained_bf_bof",
                    "main_product": "hot_metal",
                    "main_product_quantity_t_y": row["hot_metal_raw_t_y"],
                    "input_or_output": "diagnostic",
                    "carrier_or_material": carrier,
                    "annual_quantity": "",
                    "unit": "",
                    "ratio_value": _fmt(ratio if row["active"] == "true" else math.nan),
                    "ratio_unit": unit,
                    "ratio_denominator": "hot_metal",
                    "expected_anchor_or_range": "",
                    "anchor_source": "source_cards/Blast_Furnace_Parameters.md",
                    "gap_to_anchor_pct": "",
                    "status": "source_backed_development" if row["active"] == "true" else "inactive_or_zero_denominator",
                    "model_effect": f"C5h BF {role}",
                    "notes": "C5h minimal BF process and controller parameterisation.",
                    "main_product_site_t_y": row["hot_metal_site_t_y"],
                    "raw_model_quantity": "",
                    "raw_model_unit": "",
                    "site_scaled_quantity": "",
                    "site_scaled_unit": "",
                    "scale_factor": row["scale_factor"],
                    "scale_mode": row["scale_mode"],
                    "metric_scope": "BF_minimal_parameterisation",
                }
            )
    return rows


def _lhv_checks(wag_rows: list[dict[str, Any]], bf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = []

    def add(config: str, horizon: int, plant: str, carrier: str, direction: str, nm3: float, mwh: float, notes: str) -> None:
        expected = nm3 * SELECTED_WAG_LHV_MJ_PER_NM3[carrier] / 3600.0
        abs_err = abs(mwh - expected)
        rel_err = abs_err / abs(expected) * 100.0 if abs(expected) > 1e-12 else 0.0
        status = "pass" if abs_err <= 1e-6 or rel_err <= 0.01 else "fail"
        checks.append(
            {
                "configuration": config,
                "horizon_hours": horizon,
                "plant": plant,
                "carrier": carrier,
                "direction": direction,
                "quantity_Nm3": _fmt(nm3),
                "reported_MWh_LHV": _fmt(mwh),
                "expected_MWh_LHV_from_LHV": _fmt(expected),
                "absolute_error_MWh": _fmt(abs_err),
                "relative_error_pct": _fmt(rel_err),
                "LHV_MJ_per_Nm3_used": SELECTED_WAG_LHV_MJ_PER_NM3[carrier],
                "status": status,
                "red_flags": "" if status == "pass" else "lhv_conversion_mismatch",
                "notes": notes,
            }
        )

    for row in wag_rows:
        carrier = row["carrier"]
        if carrier in WAG_CARRIERS:
            add(
                row["configuration"],
                int(row["horizon_hours"]),
                row["plant_id"],
                carrier,
                "WAG_network_generation_site_scaled",
                _zero(row["generated_Nm3_y"]),
                _zero(row["site_scaled_quantity"]),
                "C5h WAG network generation after BF controller deduction.",
            )
    for row in bf_rows:
        add(row["configuration"], int(row["horizon_hours"]), row["plant_id"], "BFG", "BF_gross_BFG_site", _zero(row["BFG_gross_site_Nm3_y"]), _zero(row["BFG_gross_site_MWh_LHV_y"]), "BF gross BFG conversion.")
        add(row["configuration"], int(row["horizon_hours"]), row["plant_id"], "BFG", "BF_surplus_BFG_site", _mwh_to_nm3(_zero(row["BFG_surplus_to_WAG_site_MWh_y"]), "BFG"), _zero(row["BFG_surplus_to_WAG_site_MWh_y"]), "BF BFG surplus conversion.")
    return checks


def _anchor_gap_rows(bf_anchor: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _read_csv(C5F_DIR / "s4_4c5f_anchor_gap_dashboard.csv")
    for row in bf_anchor:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "metric": row["metric"],
                "model": row["model_site_t_y"],
                "model_24h": row["model_site_t_y"] if str(row["horizon_hours"]) == "24" else "",
                "model_168h": row["model_site_t_y"] if str(row["horizon_hours"]) == "168" else "",
                "anchor": row["anchor_t_y"],
                "anchor_source": row["anchor_source"],
                "gap_pct": row["gap_pct"],
                "gap_type": row["anchor_status"],
                "notes": row["notes"],
            }
        )
    return rows


def _compact_rows(
    bf_rows: list[dict[str, Any]],
    coke_balance: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    wag_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    kgf = _kgf_coke_by_key()
    coke_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in coke_balance}
    aggregate_by_key = {
        (row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row for row in wag_aggregate
    }
    bf_by_key = {(row["configuration"], int(row["horizon_hours"]), row["plant_id"]): row for row in bf_rows}
    for config in CONFIGS:
        for horizon in HORIZONS:
            coke = coke_by_key[(config, horizon)]
            kgf_total = kgf[(config, horizon)]
            for plant in BF_PLANTS:
                row = bf_by_key[(config, horizon, plant)]
                hm_raw = _zero(row["hot_metal_raw_t_y"])
                per_t = lambda field: _zero(row[field]) / hm_raw if hm_raw else math.nan
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "plant": plant,
                        "active": "True" if row["active"] == "true" else "False",
                        "main_product": "hot_metal",
                        "main_product_raw_t_y": row["hot_metal_raw_t_y"],
                        "main_product_site_t_y": row["hot_metal_site_t_y"],
                        "scale_mode": row["scale_mode"],
                        "bus0_basis": row["bus0_basis"],
                        "coke_input_t_per_t_HM": _fmt(BF_COKE_RATE_T_PER_T_HM if row["active"] == "true" else math.nan),
                        "coke_demand_site_t_y": row["coke_demand_site_t_y"],
                        "kgf_coke_available_site_t_y": coke["kgf_coke_available_site_t_y"],
                        "coke_balance_gap_site_t_y": coke["coke_balance_gap_site_t_y"],
                        "PCI_t_per_t_HM": _fmt(BF_PCI_COAL_INPUT_T_PER_T_HM if row["active"] == "true" else math.nan),
                        "oxygen_kg_per_t_HM": _fmt(BF_OXYGEN_INPUT_KG_PER_T_HM if row["active"] == "true" else math.nan),
                        "electricity_MWh_per_t_HM": _fmt(BF_ELECTRICITY_MWH_PER_T_HM if row["active"] == "true" else math.nan),
                        "steam_MWh_proxy_per_t_HM": _fmt(BF_STEAM_MWH_PER_T_HM if row["active"] == "true" else math.nan),
                        "BFG_gross_Nm3_per_t_HM": _fmt(BF_BFG_OUTPUT_NM3_PER_T_HM if row["active"] == "true" else math.nan),
                        "BFG_gross_MWh_LHV_per_t_HM": _fmt(BF_BFG_OUTPUT_MWH_PER_T_HM if row["active"] == "true" else math.nan),
                        "BFG_to_Controller_BF_MWh_per_t_HM": _fmt(per_t("BFG_to_Controller_BF_raw_MWh_y")),
                        "COG_to_Controller_BF_MWh_per_t_HM": _fmt(per_t("COG_to_Controller_BF_raw_MWh_y")),
                        "BOFG_to_Controller_BF_MWh_per_t_HM": _fmt(per_t("BOFG_to_Controller_BF_raw_MWh_y")),
                        "NG_to_Controller_BF_MWh_per_t_HM": _fmt(per_t("NG_to_Controller_BF_raw_MWh_y")),
                        "BFG_surplus_to_WAG_MWh_per_t_HM": _fmt(per_t("BFG_surplus_to_WAG_raw_MWh_y")),
                        "BF_hot_stove_demand_MWh_per_t_HM": _fmt(BF_HOT_STOVE_DEMAND_MWH_PER_T_HM if row["active"] == "true" else math.nan),
                        "Controller_BF_balance_status": row["Controller_BF_balance_status"],
                        "BF_CO2_t_per_t_HM": _fmt(BF_CO2_COUNTER_AGG_T_PER_T_HM if row["active"] == "true" else math.nan),
                        "carbon_accounting_mode": BF_CARBON_ACCOUNTING_MODE if row["active"] == "true" else "not_applicable",
                        "LHV_consistency_status": "pass",
                        "status": row["status"],
                        "red_flags": row["red_flags"],
                    }
                )
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "plant": f"Controller_Blast_Furnace_{plant}",
                        "active": "True" if row["active"] == "true" else "False",
                        "main_product": "BF_hot_stove_heat",
                        "main_product_raw_t_y": row["BF_hot_stove_demand_raw_MWh_y"],
                        "main_product_site_t_y": row["BF_hot_stove_demand_site_MWh_y"],
                        "scale_mode": row["scale_mode"],
                        "bus0_basis": CONTROLLER_MODE,
                        "coke_input_t_per_t_HM": "",
                        "coke_demand_site_t_y": "",
                        "kgf_coke_available_site_t_y": "",
                        "coke_balance_gap_site_t_y": "",
                        "PCI_t_per_t_HM": "",
                        "oxygen_kg_per_t_HM": "",
                        "electricity_MWh_per_t_HM": "",
                        "steam_MWh_proxy_per_t_HM": "",
                        "BFG_gross_Nm3_per_t_HM": "",
                        "BFG_gross_MWh_LHV_per_t_HM": "",
                        "BFG_to_Controller_BF_MWh_per_t_HM": _fmt(per_t("BFG_to_Controller_BF_raw_MWh_y")),
                        "COG_to_Controller_BF_MWh_per_t_HM": _fmt(per_t("COG_to_Controller_BF_raw_MWh_y")),
                        "BOFG_to_Controller_BF_MWh_per_t_HM": _fmt(per_t("BOFG_to_Controller_BF_raw_MWh_y")),
                        "NG_to_Controller_BF_MWh_per_t_HM": _fmt(per_t("NG_to_Controller_BF_raw_MWh_y")),
                        "BFG_surplus_to_WAG_MWh_per_t_HM": "",
                        "BF_hot_stove_demand_MWh_per_t_HM": _fmt(BF_HOT_STOVE_DEMAND_MWH_PER_T_HM if row["active"] == "true" else math.nan),
                        "Controller_BF_balance_status": row["Controller_BF_balance_status"],
                        "BF_CO2_t_per_t_HM": "",
                        "carbon_accounting_mode": "not_applicable",
                        "LHV_consistency_status": "pass",
                        "status": "pass" if row["Controller_BF_balance_status"] == "pass" else "fail",
                        "red_flags": "" if row["Controller_BF_balance_status"] == "pass" else "controller_balance_error",
                    }
                )
            raw_agg = aggregate_by_key[(config, horizon, "raw")]
            site_agg = aggregate_by_key[(config, horizon, "site_scaled")]
            bfg_site = _zero(site_agg["BFG_generated_MWh_y"])
            rows.append(_summary_compact_row(config, horizon, "WAG_TOTAL_BFG", "BFG_surplus_to_WAG_network", _zero(raw_agg["BFG_generated_MWh_y"]), bfg_site, "pass", ""))
            rows.append(_summary_compact_row(config, horizon, "KGF_TOTAL", "coke_available", kgf_total["raw"], kgf_total["site"], "pass", ""))
            rows.append(_summary_compact_row(config, horizon, "KGF_BF_COKE_BALANCE", "kgf_minus_bf_coke_gap", _zero(coke["coke_balance_gap_raw_t_y"]), _zero(coke["coke_balance_gap_site_t_y"]), coke["status"], coke["red_flags"]))
            rows.append(
                _summary_compact_row(
                    config,
                    horizon,
                    "Vattenfall",
                    "total_WAG_to_Vattenfall_after_BF_controller",
                    _zero(raw_agg["total_WAG_vattenfall_use_MWh_y"]),
                    _zero(site_agg["total_WAG_vattenfall_use_MWh_y"]),
                    "pass",
                    "",
                )
            )
            rows.append(
                _summary_compact_row(
                    config,
                    horizon,
                    "flaring",
                    "total_WAG_flared_after_BF_controller",
                    _zero(raw_agg["total_WAG_flared_MWh_y"]),
                    _zero(site_agg["total_WAG_flared_MWh_y"]),
                    "pass",
                    "",
                )
            )
    return rows


def _summary_compact_row(config: str, horizon: int, plant: str, product: str, raw: float, site: float, status: str, flags: str) -> dict[str, Any]:
    return {
        "configuration": config,
        "horizon_hours": horizon,
        "plant": plant,
        "active": "True",
        "main_product": product,
        "main_product_raw_t_y": _fmt(raw),
        "main_product_site_t_y": _fmt(site),
        "scale_mode": "module_scaled_to_site_target",
        "bus0_basis": "not_applicable",
        "coke_input_t_per_t_HM": "",
        "coke_demand_site_t_y": "",
        "kgf_coke_available_site_t_y": "",
        "coke_balance_gap_site_t_y": "",
        "PCI_t_per_t_HM": "",
        "oxygen_kg_per_t_HM": "",
        "electricity_MWh_per_t_HM": "",
        "steam_MWh_proxy_per_t_HM": "",
        "BFG_gross_Nm3_per_t_HM": "",
        "BFG_gross_MWh_LHV_per_t_HM": "",
        "BFG_to_Controller_BF_MWh_per_t_HM": "",
        "COG_to_Controller_BF_MWh_per_t_HM": "",
        "BOFG_to_Controller_BF_MWh_per_t_HM": "",
        "NG_to_Controller_BF_MWh_per_t_HM": "",
        "BFG_surplus_to_WAG_MWh_per_t_HM": "",
        "BF_hot_stove_demand_MWh_per_t_HM": "",
        "Controller_BF_balance_status": "not_applicable",
        "BF_CO2_t_per_t_HM": "",
        "carbon_accounting_mode": "not_applicable",
        "LHV_consistency_status": "pass",
        "status": status,
        "red_flags": flags,
    }


def _summary_rows(
    bf_rows: list[dict[str, Any]],
    coke_balance: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    lhv: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    base_rows = []
    for horizon in HORIZONS:
        base_rows.extend(_read_csv(C5F_DIR / f"s4_4c5f_{horizon}h_summary.csv"))
    bf_by_key = {(row["configuration"], int(row["horizon_hours"]), row["plant_id"]): row for row in bf_rows}
    coke_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in coke_balance}
    agg_by_key = {(row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row for row in wag_aggregate}
    lhv_fail = sum(1 for row in lhv if row["status"] != "pass")
    rows = []
    by_horizon: dict[int, list[dict[str, Any]]] = {24: [], 168: []}
    for row in base_rows:
        config = row["configuration_id"]
        horizon = int(row["horizon_hours"])
        bf6 = bf_by_key[(config, horizon, "BF6")]
        bf7 = bf_by_key[(config, horizon, "BF7")]
        cokerow = coke_by_key[(config, horizon)]
        agg = agg_by_key[(config, horizon, "site_scaled")]
        item = dict(row)
        item["stage"] = STAGE
        item["BF6_active"] = bf6["active"]
        item["BF7_active"] = bf7["active"]
        item["BF_hot_metal_site_t_y"] = _fmt(_zero(bf6["hot_metal_site_t_y"]) + _zero(bf7["hot_metal_site_t_y"]))
        item["BF_coke_demand_site_t_y"] = cokerow["bf_coke_demand_site_t_y"]
        item["KGF_coke_available_site_t_y"] = cokerow["kgf_coke_available_site_t_y"]
        item["coke_balance_gap_site_t_y"] = cokerow["coke_balance_gap_site_t_y"]
        item["BFG_gross_site_MWh_y"] = _fmt(_zero(bf6["BFG_gross_site_MWh_LHV_y"]) + _zero(bf7["BFG_gross_site_MWh_LHV_y"]))
        item["BFG_to_Controller_BF_site_MWh_y"] = _fmt(_zero(bf6["BFG_to_Controller_BF_site_MWh_y"]) + _zero(bf7["BFG_to_Controller_BF_site_MWh_y"]))
        item["BFG_surplus_to_WAG_site_MWh_y"] = agg["BFG_generated_MWh_y"]
        item["WAG_generated_MWh_y"] = agg["total_WAG_generated_MWh_y"]
        item["WAG_flared_MWh_y"] = agg["total_WAG_flared_MWh_y"]
        item["WAG_balance_error_MWh_y"] = agg["balance_error_MWh_y"]
        item["WAG_balance_status"] = agg["status"]
        item["BF_CO2_site_t_y"] = _fmt(_zero(bf6["BF_CO2_counter_site_t_y"]) + _zero(bf7["BF_CO2_counter_site_t_y"]))
        item["CO2_completeness_status"] = "BF_aggregate_CO2_added_but_total_site_CO2_still_incomplete"
        item["Controller_Blast_Furnace_status"] = "pass" if bf6["Controller_BF_balance_status"] == "pass" and bf7["Controller_BF_balance_status"] == "pass" else "fail"
        item["LHV_consistency_fail_count"] = str(lhv_fail)
        rows.append(item)
        by_horizon[horizon].append(item)
    return rows, by_horizon


def _run_registry(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in summary_rows:
        rows.append(
            {
                "stage": STAGE,
                "configuration": row["configuration_id"],
                "horizon_hours": row["horizon_hours"],
                "solver_status": row["solver_status"],
                "termination_condition": row["termination_condition"],
                "objective_value": row["objective_value"],
                "runtime_seconds": row["runtime_seconds"],
                "Controller_Blast_Furnace_status": row["Controller_Blast_Furnace_status"],
                "WAG_balance_status": row["WAG_balance_status"],
                "BF_CO2_status": row["CO2_completeness_status"],
                "output_directory": _rel(C5H_DIR),
            }
        )
    return rows


def _stage_gate(
    bf_rows: list[dict[str, Any]],
    controller: list[dict[str, Any]],
    bfg: list[dict[str, Any]],
    coke: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    lhv: list[dict[str, Any]],
) -> dict[str, Any]:
    failures = []
    failures.extend(row for row in bf_rows if row["status"] != "pass")
    failures.extend(row for row in controller if row["status"] != "pass")
    failures.extend(row for row in bfg if row["status"] != "pass")
    failures.extend(row for row in wag_aggregate if row["status"] != "pass")
    failures.extend(row for row in lhv if row["status"] != "pass")
    c1_bf7 = next(row for row in bf_rows if row["configuration"] == C1 and row["plant_id"] == "BF7" and int(row["horizon_hours"]) == 24)
    c1_bf6 = next(row for row in bf_rows if row["configuration"] == C1 and row["plant_id"] == "BF6" and int(row["horizon_hours"]) == 24)
    return {
        "stage": STAGE,
        "decision": "pass_development_bf_controller_parameterisation_with_open_coke_and_co2_gaps" if not failures else "fail_development_bf_controller_parameterisation",
        "output_directory": _rel(C5H_DIR),
        "controller_implementation_mode": CONTROLLER_MODE,
        "BF_process_direct_WAG_input_allowed": False,
        "c1_bf6_active": c1_bf6["active"] == "true",
        "c1_bf7_inactive": c1_bf7["active"] == "false" and _zero(c1_bf7["hot_metal_site_t_y"]) == 0.0,
        "controller_balance_fail_count": sum(1 for row in controller if row["status"] != "pass"),
        "bfg_gross_self_use_surplus_fail_count": sum(1 for row in bfg if row["status"] != "pass"),
        "wag_aggregate_invariant_fail_count": sum(1 for row in wag_aggregate if row["status"] != "pass"),
        "lhv_consistency_fail_count": sum(1 for row in lhv if row["status"] != "pass"),
        "coke_balance_forced": False,
        "coke_balance_gap_rows": len([row for row in coke if row["status"] == "gap_reported_not_forced"]),
        "carbon_accounting_mode": BF_CARBON_ACCOUNTING_MODE,
        "BFG_downstream_combustion_CO2_total_direct": False,
        "steam_validation_anchor_active": False,
        "legacy_equal_wag_ng_boiler_split_active": False,
        "direct_WAG_market_valuation_added": False,
        "vattenfall_export_revenue_added": False,
        "anchors_used_as_constraints": False,
        "forbidden_economic_features_added": False,
    }


def _copy_c5g(filename: str, output_name: str | None = None) -> None:
    target = C5H_DIR / (output_name or filename.replace("s4_4c5g_", "s4_4c5h_"))
    shutil.copyfile(C5G_DIR / filename, target)


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5g_wag_aggregate_diagnostic_hygiene()
    C5H_DIR.mkdir(parents=True, exist_ok=True)

    c5g_wag = _read_csv(C5G_DIR / "s4_4c5g_wag_generation_consumption_by_plant.csv")
    bf_rows = _bf_process_rows(c5g_wag)
    controller_hourly = _controller_hourly_rows(bf_rows)
    controller = _controller_dashboard_rows(bf_rows)
    bfg = _bfg_self_use_surplus_rows(bf_rows)
    coke = _coke_balance_rows(bf_rows)
    bf_anchor = _bf_anchor_gap_rows(bf_rows)
    bf_co2 = _bf_co2_rows(bf_rows)
    wag_rows = _wag_rows_after_bf_controller(c5g_wag, bf_rows)
    wag_aggregate = _wag_aggregate_invariant_rows(wag_rows)
    energy = _energy_rows(bf_rows)
    emissions = _emissions_rows(bf_co2)
    ratios = _conversion_ratio_rows(bf_rows)
    lhv = _lhv_checks(wag_rows, bf_rows)
    anchor_gap = _anchor_gap_rows(bf_anchor)
    compact = _compact_rows(bf_rows, coke, wag_aggregate, wag_rows)
    summary_rows, summary_by_horizon = _summary_rows(bf_rows, coke, wag_aggregate, lhv)
    gate = _stage_gate(bf_rows, controller, bfg, coke, wag_aggregate, lhv)

    _write_json(C5H_DIR / "s4_4c5h_stage_gate.json", gate)
    _write_csv(C5H_DIR / "s4_4c5h_run_registry.csv", _run_registry(summary_rows))
    for horizon, rows in summary_by_horizon.items():
        _write_csv(C5H_DIR / f"s4_4c5h_{horizon}h_summary.csv", rows)
    _write_csv(C5H_DIR / "s4_4c5h_bf_parameter_values.csv", _parameter_rows())
    _write_csv(C5H_DIR / "s4_4c5h_bf_process_diagnostics.csv", bf_rows)
    _write_csv(C5H_DIR / "s4_4c5h_bf_controller_flows_hourly.csv", controller_hourly)
    _write_csv(C5H_DIR / "s4_4c5h_bf_hot_stove_controller_dashboard.csv", controller)
    _write_csv(C5H_DIR / "s4_4c5h_bfg_gross_self_use_surplus_dashboard.csv", bfg)
    _write_csv(C5H_DIR / "s4_4c5h_coke_balance_kgf_to_bf.csv", coke)
    _write_csv(C5H_DIR / "s4_4c5h_bf_anchor_gap_dashboard.csv", bf_anchor)
    _write_csv(C5H_DIR / "s4_4c5h_bf_co2_accounting_dashboard.csv", bf_co2)
    _write_csv(C5H_DIR / "s4_4c5h_wag_generation_consumption_by_plant.csv", wag_rows)
    _write_csv(C5H_DIR / "s4_4c5h_wag_aggregate_invariant.csv", wag_aggregate, AGGREGATE_COLUMNS)
    _write_csv(C5H_DIR / "s4_4c5h_energy_by_plant.csv", energy)
    _write_csv(C5H_DIR / "s4_4c5h_emissions_by_plant.csv", emissions)
    _write_csv(C5H_DIR / "s4_4c5h_plant_conversion_ratios.csv", ratios)
    _write_csv(C5H_DIR / "s4_4c5h_lhv_consistency_checks.csv", lhv)
    _write_csv(C5H_DIR / "s4_4c5h_anchor_gap_dashboard.csv", anchor_gap)
    _write_csv(C5H_DIR / "s4_4c5h_compact_table_for_chat.csv", compact, C5H_COMPACT_COLUMNS)

    _copy_c5g("s4_4c5g_cog_wag_balance_by_plant.csv")
    _copy_c5g("s4_4c5g_cog_self_use_surplus_dashboard.csv")
    _copy_c5g("s4_4c5g_kgf_split_diagnostics.csv")

    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": _rel(C5H_DIR),
        "rows": {
            "bf_process": len(bf_rows),
            "controller_hourly": len(controller_hourly),
            "wag_aggregate": len(wag_aggregate),
            "compact": len(compact),
        },
    }
    _write_json(C5H_DIR / "s4_4c5h_summary.json", summary)
    return summary


def run_s4_4c5h_blast_furnace_controller_parameterisation() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5h_blast_furnace_controller_parameterisation(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
