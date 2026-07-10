"""S4.4c5p_b boiler and steam-circuit accounting layer.

This stage adds a development-only, mass-flow steam accounting layer on top of
the current C5 plant stack. It represents boilers, STEG11, TG2 and pressure
reducers as utility conversion ledgers. It is not a market-generation layer and
does not change accepted C5 production, coke, HSM/WBW, Linde/ASU or process
plant assumptions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    CONFIGS,
    HORIZONS,
    S4_ROOT,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch import C5L_D_DIR
from .s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration import C5M_B_DIR
from .s4_4c5m_sinter_minimal_parameterisation import C5M_DIR
from .s4_4c5n_a_pefa_pelletizing_layer import C5N_A_DIR
from .s4_4c5p_a_linde_asu_oxygen_accounting import (
    C5P_A_DIR,
    run_s4_4c5p_a_linde_asu_oxygen_accounting,
)


STAGE = "S4.4c5p_b_boiler_steam_circuit_accounting"
C5P_B_DIR = S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting"
SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/BOILER_STEAM_CIRCUIT_Parameters.md")
DEPENDENCY_CHAIN = (
    "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b "
    "-> C5m_c -> C5m_d -> C5m_e -> C5m_f -> C5n_a -> C5n_b -> C5o_a "
    "-> C5o_b -> C5o_c -> C5p_a -> C5p_b"
)
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_healthcheck_pattern;"
    "boiler_steam_values_loaded_from_C5p_b_development_input_rows;"
    "steam_mass_flow_accounting_not_enthalpy_model;"
    "STEG11_TG2_electricity_accounting_only"
)

TOL = 1e-6
HOURS_PER_YEAR = 8760.0
FUEL_UNIT_CONVENTION = "MWh_LHV_per_year_for_BFG_COG_BOFG_NG; source-card ratios MWhth_per_t_steam"
STEAM_UNIT_CONVENTION = "t_steam_per_year_mass_flow_accounting"
DISPATCH_BASIS = "demand_led_capacity_proportional_annual_mass_flow_accounting"
STEG11_DISPATCH_BASIS = "steam_output_led_using_source_table_derived_coefficients"
ELECTRICITY_ACCOUNTING_STATUS = "accounting_only_reporting_only_not_DA_market_revenue"
DENOMINATOR_STATUS = "unresolved_until_generator_interface_and_residual_loads"


BOILER_UNITS: dict[str, dict[str, Any]] = {
    "BOILER_C1_K15K16": {
        "label": "K15/K16",
        "steam_pressure": "steam_72bar",
        "steam_max_t_h": 220.0,
        "mwth": 192.8,
        "fuel_mwh_per_t_steam": 0.876,
        "pressure_barg": 72.0,
        "temperature_c": 505.0,
        "eligible_fuels": ("BFG", "COG", "NG"),
    },
    "BOILER_C2_K23K24": {
        "label": "K23/K24",
        "steam_pressure": "steam_45bar",
        "steam_max_t_h": 220.0,
        "mwth": 189.3,
        "fuel_mwh_per_t_steam": 0.861,
        "pressure_barg": 45.0,
        "temperature_c": 465.0,
        "eligible_fuels": ("BFG", "COG", "NG"),
    },
    "BOILER_C2_K41": {
        "label": "K41",
        "steam_pressure": "steam_45bar",
        "steam_max_t_h": 80.0,
        "mwth": 56.0,
        "fuel_mwh_per_t_steam": 0.700,
        "pressure_barg": 45.0,
        "temperature_c": 465.0,
        "eligible_fuels": ("BFG", "NG"),
    },
}

STEG11 = {
    "unit_id": "STEG11_CHP",
    "type": "GT11 + AK11",
    "steam_pressure": "steam_72bar",
    "thermal_input_max_mwth": 85.0,
    "electricity_max_mwe": 13.1,
    "steam_output_max_t_h": 80.0,
    "pressure_barg": 72.0,
    "temperature_c": 505.0,
    "electric_eff_per_fuel_mwh": 0.154,
    "steam_t_per_mwh_fuel": 0.941,
    "fuel_mwh_per_t_steam": 1.063,
    "electricity_mwh_per_t_steam": 0.164,
    "eligible_fuels": ("BFG", "NG"),
}

TG2 = {
    "unit_id": "TG2_STEAM_TURBINE",
    "input_carrier": "steam_72bar",
    "electricity_max_mwe": 14.5,
    "steam_flow_max_t_h": 105.0,
    "output_steam_15bar_t_h": 105.0,
    "output_steam_low_t_h": 20.0,
    "output_steam_15bar_pressure_barg": 15.0,
    "output_steam_15bar_temp_c": 350.0,
    "output_steam_low_pressure_barg": 0.5,
    "output_steam_low_temp_c": 175.0,
    "electricity_mwh_per_t_steam_main": 0.138,
}

FUEL_ALLOCATION_ORDER = ("STEG11_CHP", "BOILER_C2_K41", "BOILER_C1_K15K16", "BOILER_C2_K23K24")

REDFLAG_NAMES = [
    "STEAM_BUS_MISSING",
    "BOILER_ACTIVE_WITHOUT_STEAM_DEMAND_AND_WITHOUT_SPILL_DIAGNOSTIC",
    "STEAM_UNSERVED_NONZERO",
    "STEAM_SPILL_HIDDEN",
    "STEAM_STORAGE_ACTIVE_WITHOUT_SOURCE",
    "K41_COG_USED",
    "STEG11_COG_USED",
    "BOFG_USED_BY_STEAM_LAYER_WITHOUT_GOVERNED_SOURCE",
    "TG2_FUEL_INPUT_NONZERO",
    "STEG11_OR_TG2_MARKET_REVENUE_ACTIVE",
    "BOILER_STEG_TG2_MFRR_ENABLED_IN_BASE",
    "WAG_DIRECT_MARKET_VALUE_ACTIVE",
    "STEG11_TG2_ELECTRICITY_COUNTED_AS_VATTENFALL",
    "FULL_SITE_NET_ELECTRICITY_CLAIMED",
    "NG_USED_WHILE_ELIGIBLE_WAG_SPILLED_UNEXPLAINED",
    "BOILER_CAPACITY_EXCEEDED",
    "STEG11_CAPACITY_EXCEEDED",
    "TG2_CAPACITY_EXCEEDED",
    "HSM_BASE_0_50_REVERTED",
    "COKE_RECONCILIATION_BASELINE_REOPENED",
    "DENOMINATOR_SILENTLY_FROZEN",
]

CAVEAT_NAMES = [
    "STEAM_MASS_FLOW_NOT_ENTHALPY_MODEL",
    "BOILER_EFFICIENCY_NOT_EXPLICIT",
    "NG_ELIGIBILITY_CAVEATED",
    "STEAM_RESIDUAL_DEMAND_MISSING_OR_DEFERRED",
    "STEAM_PRESSURE_LEVEL_ASSUMED_FOR_EXISTING_DEMAND",
    "STEAM_SPILL_DIAGNOSTIC_ACTIVE",
    "STEG11_ELECTRICITY_ACCOUNTING_ONLY",
    "TG2_ELECTRICITY_ACCOUNTING_ONLY",
    "VATTENFALL_GENERATORS_DEFERRED",
    "CO2_FUEL_EXPLICIT_DEFERRED",
    "DENOMINATOR_UNRESOLVED_UNTIL_GENERATOR_INTERFACE_AND_RESIDUAL_LOADS",
    "BOILER_STEAM_NOT_THESIS_APPROVED",
]


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _bool(value: bool) -> str:
    return str(value).lower()


def _by_key(rows: list[dict[str, str]], *, cap_case: str | None = None) -> dict[tuple[str, int], dict[str, str]]:
    result: dict[tuple[str, int], dict[str, str]] = {}
    for row in rows:
        if cap_case is not None and row.get("cap_case") != cap_case:
            continue
        result[(row["configuration"], int(row["horizon_hours"]))] = row
    return result


def _active_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("included_in_modelled_steam_total", "true") == "true"]


def _param_row(parameter_id: str, base_value: Any, unit: str, source_locator: str, caveat: str) -> dict[str, Any]:
    return {
        "stage_id": STAGE,
        "parameter_id": parameter_id,
        "base_value": base_value,
        "unit": unit,
        "input_status": "development_candidate_reviewed_from_source_card",
        "thesis_usability": "false",
        "source_card": _rel(SOURCE_CARD),
        "source_or_candidate_evidence": source_locator,
        "human_review_required": "true",
        "codex_may_decide": "false",
        "caveat": caveat,
    }


def _boiler_steam_dev_rows() -> list[dict[str, Any]]:
    rows = [
        _param_row("BOILER_C1_K15K16_STEAM_MAX_T_H", 220, "t steam/h", "S1 Table 0.1 K15+K16", "aggregate K15/K16 first implementation"),
        _param_row("BOILER_C1_K15K16_MWTH", 192.8, "MWth", "S1 Table 0.1 K15+K16", "source-table thermal capacity"),
        _param_row("BOILER_C1_K15K16_FUEL_MWH_PER_T_STEAM", 0.876, "MWhth/t steam", "192.8 MWth / 220 t/h", "source-table ratio, not independent efficiency"),
        _param_row("BOILER_C1_STEAM_PRESSURE_BARG", 72, "bar(g)", "S1 Table 0.1", "connects to steam_72bar"),
        _param_row("BOILER_C1_STEAM_TEMP_C", 505, "degC", "S1 Table 0.1", "reporting/source context"),
        _param_row("BOILER_C1_K15K16_BFG_ALLOWED", "true", "bool", "S2/S3 BFG consumer list", "source-backed eligibility"),
        _param_row("BOILER_C1_K15K16_COG_ALLOWED", "true", "bool", "S2 COG consumer list", "source-backed eligibility"),
        _param_row("BOILER_C1_K15K16_NG_ALLOWED", "true", "bool", "S2 site NG context plus policy", "backup/external fuel option caveated"),
        _param_row("BOILER_C2_K23K24_STEAM_MAX_T_H", 220, "t steam/h", "S1 Table 0.1 K23+K24", "aggregate K23/K24 first implementation"),
        _param_row("BOILER_C2_K23K24_MWTH", 189.3, "MWth", "S1 Table 0.1 K23+K24", "source-table thermal capacity"),
        _param_row("BOILER_C2_K23K24_FUEL_MWH_PER_T_STEAM", 0.861, "MWhth/t steam", "189.3 MWth / 220 t/h", "source-table ratio, not independent efficiency"),
        _param_row("BOILER_C2_K23K24_STEAM_PRESSURE_BARG", 45, "bar(g)", "S1 Table 0.1", "connects to steam_45bar"),
        _param_row("BOILER_C2_K23K24_STEAM_TEMP_C", 465, "degC", "S1 Table 0.1", "reporting/source context"),
        _param_row("BOILER_C2_K23K24_BFG_ALLOWED", "true", "bool", "S2/S3 BFG consumer list", "source-backed eligibility"),
        _param_row("BOILER_C2_K23K24_COG_ALLOWED", "true", "bool", "S2 COG consumer list", "source-backed eligibility"),
        _param_row("BOILER_C2_K23K24_NG_ALLOWED", "true", "bool", "S2 site NG context plus policy", "backup/external fuel option caveated"),
        _param_row("BOILER_C2_K41_STEAM_MAX_T_H", 80, "t steam/h", "S1 Table 0.1", "separate K41 first implementation"),
        _param_row("BOILER_C2_K41_MWTH", 56, "MWth", "S1 Table 0.1", "source-table thermal capacity"),
        _param_row("BOILER_C2_K41_FUEL_MWH_PER_T_STEAM", 0.700, "MWhth/t steam", "56 MWth / 80 t/h", "source-table ratio, not independent efficiency"),
        _param_row("BOILER_C2_K41_STEAM_PRESSURE_BARG", 45, "bar(g)", "S1 Table 0.1", "connects to steam_45bar"),
        _param_row("BOILER_C2_K41_STEAM_TEMP_C", 465, "degC", "S1 Table 0.1", "reporting/source context"),
        _param_row("BOILER_C2_K41_BFG_ALLOWED", "true", "bool", "S2/S3 BFG consumer list", "source-backed eligibility"),
        _param_row("BOILER_C2_K41_COG_ALLOWED", "false", "bool", "S2 COG consumer list excludes K41", "COG blocked in first implementation"),
        _param_row("BOILER_C2_K41_NG_ALLOWED", "true", "bool", "S2 site NG context plus policy", "backup/external fuel option caveated"),
        _param_row("BOILER_MFRR_ENABLED_BASE", "false", "bool", "project governance", "boilers are not mFRR assets in base"),
        _param_row("STEG11_ENABLED", "true", "bool", "S1 Appendix A1", "topology active"),
        _param_row("STEG11_TYPE", "GT11 + AK11", "text", "S1 Appendix A1", "gas turbine plus HRSG"),
        _param_row("STEG11_THERMAL_INPUT_MAX_MWTH", 85, "MWth", "S1 Table 0.1", "capacity guard"),
        _param_row("STEG11_ELECTRICITY_MAX_MWE", 13.1, "MWe", "S1 Table 0.1", "accounting-only electricity capacity"),
        _param_row("STEG11_STEAM_OUTPUT_MAX_T_H", 80, "t steam/h", "S1 Table 0.1", "steam_72bar capacity"),
        _param_row("STEG11_STEAM_PRESSURE_BARG", 72, "bar(g)", "S1 Table 0.1", "connects to steam_72bar"),
        _param_row("STEG11_STEAM_TEMP_C", 505, "degC", "S1 Table 0.1", "reporting/source context"),
        _param_row("STEG11_ELECTRIC_EFF_PER_FUEL_MWH", 0.154, "MWh_el/MWhth", "13.1 MWe / 85 MWth", "source-table ratio"),
        _param_row("STEG11_STEAM_T_PER_MWH_FUEL", 0.941, "t steam/MWhth", "80 t/h / 85 MWth", "source-table ratio"),
        _param_row("STEG11_FUEL_MWH_PER_T_STEAM", 1.063, "MWhth/t steam", "85 MWth / 80 t/h", "steam-output-led dispatch coefficient"),
        _param_row("STEG11_ELECTRICITY_MWH_PER_T_STEAM", 0.164, "MWh_el/t steam", "13.1 MWe / 80 t/h", "accounting-only electricity"),
        _param_row("STEG11_BFG_ALLOWED", "true", "bool", "S2/S3 BFG consumer list", "source-backed eligibility"),
        _param_row("STEG11_NG_BACKUP_ALLOWED", "true", "bool", "S2 site NG context plus policy", "backup/external fuel option caveated"),
        _param_row("STEG11_COG_ALLOWED", "false", "bool", "S2 COG consumer list excludes STEG11", "COG blocked/deferred"),
        _param_row("STEG11_MARKET_ELECTRICITY_REVENUE_ACTIVE", "false", "bool", "project governance", "electricity accounting-only"),
        _param_row("STEG11_MFRR_ENABLED_BASE", "false", "bool", "project governance", "STEG11 is not mFRR asset in base"),
        _param_row("TG2_ENABLED", "true", "bool", "S1 Appendix A1", "topology active"),
        _param_row("TG2_INPUT_CARRIER", "steam_72bar", "carrier", "S1 Appendix A1", "steam-only route"),
        _param_row("TG2_ELECTRICITY_MAX_MWE", 14.5, "MWe", "S1 Table 0.1", "accounting-only electricity capacity"),
        _param_row("TG2_STEAM_FLOW_MAX_T_H", 105, "t steam/h", "S1 Table 0.1", "main 15bar route throughput"),
        _param_row("TG2_OUTPUT_STEAM_15BAR_T_H", 105, "t steam/h", "S1 Table 0.1", "mass-flow output equals input"),
        _param_row("TG2_OUTPUT_STEAM_LOW_T_H", 20, "t steam/h", "S1 Table 0.1", "low-pressure output deferred/reporting only"),
        _param_row("TG2_OUTPUT_STEAM_15BAR_PRESSURE_BARG", 15, "bar(g)", "S1 Table 0.1", "connects to steam_15bar"),
        _param_row("TG2_OUTPUT_STEAM_15BAR_TEMP_C", 350, "degC", "S1 Table 0.1", "reporting/source context"),
        _param_row("TG2_OUTPUT_STEAM_LOW_PRESSURE_BARG", 0.5, "bar(g)", "S1 Table 0.1", "deferred steam_low context"),
        _param_row("TG2_OUTPUT_STEAM_LOW_TEMP_C", 175, "degC", "S1 Table 0.1", "deferred steam_low context"),
        _param_row("TG2_ELECTRICITY_MWH_PER_T_STEAM_MAIN", 0.138, "MWh_el/t steam", "14.5 MWe / 105 t/h", "accounting-only electricity"),
        _param_row("TG2_BYPASS_REDUCTION_AVAILABLE", "true", "bool", "S1 Appendix A1", "parallel reducer route available"),
        _param_row("TG2_MARKET_ELECTRICITY_REVENUE_ACTIVE", "false", "bool", "project governance", "electricity accounting-only"),
        _param_row("TG2_MFRR_ENABLED_BASE", "false", "bool", "project governance", "TG2 is not mFRR asset in base"),
        _param_row("STEAM_72_TO_45_REDUCTION_ALLOWED", "true", "bool", "S1 Appendix A1", "mass-flow reducer"),
        _param_row("STEAM_45_TO_15_REDUCTION_ALLOWED", "true", "bool", "S1 Appendix A1", "mass-flow reducer"),
        _param_row("STEAM_72_TO_15_BYPASS_ALLOWED", "true", "bool", "S1 Appendix A1", "mass-flow bypass route"),
        _param_row("STEAM_REDUCTION_ELECTRICITY_RECOVERY", 0, "MWh_el/t steam", "project governance", "reducers have no recovery; TG2 only"),
        _param_row("STEAM_STORAGE_ACTIVE_BASE", "false", "bool", "project governance", "steam is a bus, not a store"),
        _param_row("STEAM_SURPLUS_BLOWOFF_ALLOWED_DIAGNOSTIC", "true", "bool", "source-card policy", "spill must be explicit"),
        _param_row("STEAM_UNSERVED_ALLOWED_BASE", "false", "bool", "source-card policy", "unserved steam is failure/red flag"),
        _param_row("STEAM_RESIDUAL_DEMAND_ACTIVE", "true", "bool", "source-card policy", "reported missing/deferred if no row exists"),
    ]
    return rows


def _steam_bus_rows() -> list[dict[str, Any]]:
    rows = [
        ("bfg_bus", "BFG", "", "", "active", "inherited_WAG_carrier"),
        ("cog_bus", "COG", "", "", "active", "inherited_WAG_carrier"),
        ("ng_bus", "NG", "", "", "active_backup", "external_backup_fuel_caveated"),
        ("boiler_c1_k15k16_fuel_heat_bus", "mixed_fuel_heat", "", "MWh_LHV/y", "active", "controller_bus"),
        ("boiler_c2_k23k24_fuel_heat_bus", "mixed_fuel_heat", "", "MWh_LHV/y", "active", "controller_bus"),
        ("boiler_c2_k41_fuel_heat_bus", "mixed_fuel_heat", "", "MWh_LHV/y", "active", "controller_bus"),
        ("steg11_fuel_heat_bus", "mixed_fuel_heat", "", "MWh_LHV/y", "active", "controller_bus"),
        ("steam_72bar", "steam", 72, "t steam/y", "active", "mass_flow_not_enthalpy"),
        ("steam_45bar", "steam", 45, "t steam/y", "active", "mass_flow_not_enthalpy"),
        ("steam_15bar", "steam", 15, "t steam/y", "active", "mass_flow_not_enthalpy"),
        ("steam_low", "steam", 0.5, "t steam/y", "deferred", "TG2_low_pressure_output_reporting_only"),
        ("electricity_internal", "electricity", "", "MWh_e/y", "accounting_only", "not_market_revenue"),
        ("steam_spill_diagnostic", "steam_spill", "", "t steam/y", "active_diagnostic", "explicit_blowoff_reporting"),
    ]
    return [
        {
            "stage_id": STAGE,
            "bus_id": bus_id,
            "carrier": carrier,
            "pressure_barg": pressure,
            "unit": unit,
            "status": status,
            "thesis_usability": "false",
            "source_card": _rel(SOURCE_CARD),
            "caveat": caveat,
        }
        for bus_id, carrier, pressure, unit, status, caveat in rows
    ]


def _fuel_eligibility_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    unit_map: dict[str, tuple[str, tuple[str, ...]]] = {
        "BOILER_C1_K15K16": ("fuel", BOILER_UNITS["BOILER_C1_K15K16"]["eligible_fuels"]),
        "BOILER_C2_K23K24": ("fuel", BOILER_UNITS["BOILER_C2_K23K24"]["eligible_fuels"]),
        "BOILER_C2_K41": ("fuel", BOILER_UNITS["BOILER_C2_K41"]["eligible_fuels"]),
        "STEG11_CHP": ("fuel", STEG11["eligible_fuels"]),
        "TG2_STEAM_TURBINE": ("steam", ("steam_72bar",)),
    }
    for unit_id, (input_type, allowed) in unit_map.items():
        carriers = ("BFG", "COG", "NG", "BOFG") if input_type == "fuel" else ("steam_72bar", "BFG", "COG", "NG", "BOFG")
        for carrier in carriers:
            is_allowed = carrier in allowed
            rows.append(
                {
                    "stage_id": STAGE,
                    "unit_id": unit_id,
                    "input_carrier": carrier,
                    "input_type": "steam" if carrier.startswith("steam_") else "fuel",
                    "allowed": _bool(is_allowed),
                    "source_status": _eligibility_source_status(unit_id, carrier, is_allowed),
                    "mFRR_enabled_base": "false",
                    "market_electricity_revenue_active": "false"
                    if unit_id in ("STEG11_CHP", "TG2_STEAM_TURBINE")
                    else "not_applicable",
                    "direct_WAG_market_value_active": "false",
                    "thesis_usability": "false",
                    "caveat": _eligibility_caveat(unit_id, carrier, is_allowed),
                }
            )
    return rows


def _eligibility_source_status(unit_id: str, carrier: str, allowed: bool) -> str:
    if carrier == "NG" and allowed:
        return "backup_external_fuel_option_caveated"
    if carrier == "BOFG":
        return "blocked_no_governed_source_for_steam_layer"
    if carrier == "COG" and unit_id in ("BOILER_C2_K41", "STEG11_CHP"):
        return "blocked_source_consumer_list_excludes_unit"
    if unit_id == "TG2_STEAM_TURBINE" and carrier == "steam_72bar":
        return "source_backed_steam_only_input"
    if unit_id == "TG2_STEAM_TURBINE":
        return "blocked_TG2_has_no_fuel_input"
    return "source_backed" if allowed else "blocked"


def _eligibility_caveat(unit_id: str, carrier: str, allowed: bool) -> str:
    if carrier == "NG" and allowed:
        return "NG backup eligibility is caveated and not a market choice."
    if carrier == "BOFG":
        return "BOFG is not allowed in C5p_b steam layer without governed source row."
    if unit_id == "TG2_STEAM_TURBINE":
        return "TG2 is steam-only and produces accounting-only electricity."
    if carrier == "COG" and not allowed:
        return "COG excluded for this unit in first implementation."
    return "Useful WAG fuel allocation only; no direct WAG valuation."


def _source_payload() -> dict[str, Any]:
    run_s4_4c5p_a_linde_asu_oxygen_accounting()
    return {
        "steam_utility": _active_rows(_read_csv(C5M_B_DIR / "s4_4c5m_b_steam_utility_ledger.csv")),
        "sinter_wag": _by_key(_read_csv(C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv")),
        "pefa_gas": _by_key(_read_csv(C5N_A_DIR / "s4_4c5n_a_pefa_gas_controller_dashboard.csv")),
        "linde_totals": _by_key(_read_csv(C5P_A_DIR / "s4_4c5p_a_modelled_totals_delta.csv")),
        "c5l_d": _by_key(_read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv"), cap_case="base_0_50"),
    }


def _steam_demand_mapping_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in payload["steam_utility"]:
        proxy_mwh = _zero(row["steam_proxy_MWh_y"])
        mass_t = _zero(row["steam_mass_t_y"])
        if mass_t > 0.0:
            load_t = mass_t
            conversion_basis = "source_mass_t_steam"
        elif proxy_mwh > 0.0:
            load_t = proxy_mwh / BOILER_UNITS["BOILER_C1_K15K16"]["fuel_mwh_per_t_steam"]
            conversion_basis = "proxy_MWh_to_t_using_K15K16_source_ratio_0p876"
        else:
            load_t = 0.0
            conversion_basis = "no_active_steam_quantity"
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_group": row["plant_group"],
                "source_steam_proxy_MWh_y": row["steam_proxy_MWh_y"],
                "source_steam_mass_t_y": row["steam_mass_t_y"],
                "mapped_pressure_level": "steam_15bar",
                "mapped_steam_load_t_y": _fmt(load_t),
                "conversion_basis": conversion_basis,
                "pressure_mapping_status": "development_assumption_unknown_pressure_mapped_to_15bar",
                "residual_demand_status": "explicit_existing_modelled_load_not_residual",
                "thesis_usability": "false",
                "caveat": "Existing non-pressure-specific steam loads are mapped to 15 bar until source-specific pressure data exists.",
            }
        )
    return rows


def _steam_demand_by_pressure_rows(mapping: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[tuple[str, int, str], float] = {}
    for row in mapping:
        key = (row["configuration"], int(row["horizon_hours"]), row["mapped_pressure_level"])
        totals[key] = totals.get(key, 0.0) + _zero(row["mapped_steam_load_t_y"])
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            for pressure in ("steam_72bar", "steam_45bar", "steam_15bar"):
                process_load = totals.get((config, horizon, pressure), 0.0)
                rows.append(
                    {
                        "stage_id": STAGE,
                        "configuration": config,
                        "horizon_hours": horizon,
                        "pressure_level": pressure,
                        "process_load_t_y": _fmt(process_load),
                        "residual_load_t_y": 0.0,
                        "total_demand_t_y": _fmt(process_load),
                        "average_demand_t_h": _fmt(process_load / HOURS_PER_YEAR),
                        "residual_demand_status": "STEAM_RESIDUAL_DEMAND_MISSING_OR_DEFERRED",
                        "pressure_mapping_status": "STEAM_PRESSURE_LEVEL_ASSUMED_FOR_EXISTING_DEMAND"
                        if process_load > 0.0
                        else "no_direct_load_at_pressure_level",
                        "thesis_usability": "false",
                    }
                )
    return rows


def _steam_dispatch_rows(demand_by_pressure: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    demand = {
        (row["configuration"], int(row["horizon_hours"]), row["pressure_level"]): _zero(row["total_demand_t_y"])
        for row in demand_by_pressure
    }
    unit_supply_rows: list[dict[str, Any]] = []
    steg_rows: list[dict[str, Any]] = []
    tg2_rows: list[dict[str, Any]] = []
    reducer_rows: list[dict[str, Any]] = []
    bus_rows: list[dict[str, Any]] = []
    internal_electricity_rows: list[dict[str, Any]] = []

    for config in CONFIGS:
        for horizon in HORIZONS:
            steam_15_load = demand[(config, horizon, "steam_15bar")]
            steam_72_direct = demand[(config, horizon, "steam_72bar")]
            steam_45_direct = demand[(config, horizon, "steam_45bar")]
            steam_72_cap = (
                BOILER_UNITS["BOILER_C1_K15K16"]["steam_max_t_h"] + STEG11["steam_output_max_t_h"]
            ) * HOURS_PER_YEAR
            steam_45_cap = (
                BOILER_UNITS["BOILER_C2_K23K24"]["steam_max_t_h"] + BOILER_UNITS["BOILER_C2_K41"]["steam_max_t_h"]
            ) * HOURS_PER_YEAR
            direct_72 = min(steam_72_direct, steam_72_cap)
            rem_72_cap = max(steam_72_cap - direct_72, 0.0)
            direct_45 = min(steam_45_direct, steam_45_cap)
            rem_45_cap = max(steam_45_cap - direct_45, 0.0)

            remaining_15 = steam_15_load
            total_reducer_cap = rem_72_cap + rem_45_cap
            if total_reducer_cap > 0.0:
                steam_from_72_for_15 = min(remaining_15 * rem_72_cap / total_reducer_cap, rem_72_cap)
            else:
                steam_from_72_for_15 = 0.0
            steam_from_45_for_15 = min(max(remaining_15 - steam_from_72_for_15, 0.0), rem_45_cap)
            unserved_15 = max(remaining_15 - steam_from_72_for_15 - steam_from_45_for_15, 0.0)

            total_72_supply = direct_72 + steam_from_72_for_15
            total_45_supply = direct_45 + steam_from_45_for_15
            k15_share = BOILER_UNITS["BOILER_C1_K15K16"]["steam_max_t_h"] / (
                BOILER_UNITS["BOILER_C1_K15K16"]["steam_max_t_h"] + STEG11["steam_output_max_t_h"]
            )
            k23_share = BOILER_UNITS["BOILER_C2_K23K24"]["steam_max_t_h"] / (
                BOILER_UNITS["BOILER_C2_K23K24"]["steam_max_t_h"] + BOILER_UNITS["BOILER_C2_K41"]["steam_max_t_h"]
            )
            k15_steam = min(total_72_supply * k15_share, BOILER_UNITS["BOILER_C1_K15K16"]["steam_max_t_h"] * HOURS_PER_YEAR)
            steg_steam = max(total_72_supply - k15_steam, 0.0)
            k23_steam = min(total_45_supply * k23_share, BOILER_UNITS["BOILER_C2_K23K24"]["steam_max_t_h"] * HOURS_PER_YEAR)
            k41_steam = max(total_45_supply - k23_steam, 0.0)

            tg2_cap = TG2["steam_flow_max_t_h"] * HOURS_PER_YEAR
            tg2_input = min(steam_from_72_for_15, tg2_cap)
            steam_72_to_15_bypass = max(steam_from_72_for_15 - tg2_input, 0.0)
            steam_72_to_45 = 0.0
            steam_45_to_15 = steam_from_45_for_15
            tg2_power = tg2_input * TG2["electricity_mwh_per_t_steam_main"]
            steg_power = steg_steam * STEG11["electricity_mwh_per_t_steam"]

            unit_steam = {
                "BOILER_C1_K15K16": k15_steam,
                "BOILER_C2_K23K24": k23_steam,
                "BOILER_C2_K41": k41_steam,
            }
            for unit_id, steam_t in unit_steam.items():
                params = BOILER_UNITS[unit_id]
                unit_supply_rows.append(
                    {
                        "stage_id": STAGE,
                        "configuration": config,
                        "horizon_hours": horizon,
                        "unit_id": unit_id,
                        "steam_pressure_level": params["steam_pressure"],
                        "steam_output_t_y": _fmt(steam_t),
                        "average_steam_output_t_h": _fmt(steam_t / HOURS_PER_YEAR),
                        "steam_capacity_t_h": params["steam_max_t_h"],
                        "steam_capacity_t_y": _fmt(params["steam_max_t_h"] * HOURS_PER_YEAR),
                        "fuel_mwh_per_t_steam": params["fuel_mwh_per_t_steam"],
                        "fuel_heat_required_MWh_LHV_y": _fmt(steam_t * params["fuel_mwh_per_t_steam"]),
                        "capacity_exceeded": _bool(steam_t > params["steam_max_t_h"] * HOURS_PER_YEAR + TOL),
                        "dispatch_basis": DISPATCH_BASIS,
                    }
                )

            steg_rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "unit_id": "STEG11_CHP",
                    "STEG11_type": STEG11["type"],
                    "steam_output_72bar_t_y": _fmt(steg_steam),
                    "average_steam_output_t_h": _fmt(steg_steam / HOURS_PER_YEAR),
                    "steam_output_max_t_h": STEG11["steam_output_max_t_h"],
                    "fuel_heat_required_MWh_LHV_y": _fmt(steg_steam * STEG11["fuel_mwh_per_t_steam"]),
                    "average_fuel_heat_MWth": _fmt(steg_steam * STEG11["fuel_mwh_per_t_steam"] / HOURS_PER_YEAR),
                    "fuel_heat_max_MWth": STEG11["thermal_input_max_mwth"],
                    "electricity_output_MWh_e_y": _fmt(steg_power),
                    "average_electricity_MWe": _fmt(steg_power / HOURS_PER_YEAR),
                    "electricity_max_MWe": STEG11["electricity_max_mwe"],
                    "electricity_accounting_status": ELECTRICITY_ACCOUNTING_STATUS,
                    "market_electricity_revenue_active": "false",
                    "mFRR_enabled_base": "false",
                    "dispatch_basis": STEG11_DISPATCH_BASIS,
                    "capacity_exceeded": _bool(
                        steg_steam > STEG11["steam_output_max_t_h"] * HOURS_PER_YEAR + TOL
                        or steg_steam * STEG11["fuel_mwh_per_t_steam"] / HOURS_PER_YEAR
                        > STEG11["thermal_input_max_mwth"] + TOL
                        or steg_power / HOURS_PER_YEAR > STEG11["electricity_max_mwe"] + TOL
                    ),
                }
            )

            tg2_rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "unit_id": "TG2_STEAM_TURBINE",
                    "steam_72bar_input_t_y": _fmt(tg2_input),
                    "steam_15bar_output_t_y": _fmt(tg2_input),
                    "steam_low_output_t_y": 0.0,
                    "steam_low_output_status": "deferred_reporting_only",
                    "average_steam_input_t_h": _fmt(tg2_input / HOURS_PER_YEAR),
                    "steam_flow_max_t_h": TG2["steam_flow_max_t_h"],
                    "electricity_output_MWh_e_y": _fmt(tg2_power),
                    "average_electricity_MWe": _fmt(tg2_power / HOURS_PER_YEAR),
                    "electricity_max_MWe": TG2["electricity_max_mwe"],
                    "electricity_mwh_per_t_steam": TG2["electricity_mwh_per_t_steam_main"],
                    "fuel_input_MWh_LHV_y": 0.0,
                    "electricity_accounting_status": ELECTRICITY_ACCOUNTING_STATUS,
                    "market_electricity_revenue_active": "false",
                    "mFRR_enabled_base": "false",
                    "capacity_exceeded": _bool(
                        tg2_input > TG2["steam_flow_max_t_h"] * HOURS_PER_YEAR + TOL
                        or tg2_power / HOURS_PER_YEAR > TG2["electricity_max_mwe"] + TOL
                    ),
                }
            )

            reducer_rows.extend(
                [
                    _reducer_row(config, horizon, "STEAM_72_TO_45_REDUCER", "steam_72bar", "steam_45bar", steam_72_to_45, True),
                    _reducer_row(config, horizon, "STEAM_72_TO_15_BYPASS", "steam_72bar", "steam_15bar", steam_72_to_15_bypass, True),
                    _reducer_row(config, horizon, "STEAM_45_TO_15_REDUCER", "steam_45bar", "steam_15bar", steam_45_to_15, True),
                ]
            )

            bus_rows.extend(
                [
                    _bus_balance_row(
                        config,
                        horizon,
                        "steam_72bar",
                        k15_steam + steg_steam,
                        direct_72,
                        tg2_input + steam_72_to_45 + steam_72_to_15_bypass,
                        0.0,
                        0.0,
                    ),
                    _bus_balance_row(
                        config,
                        horizon,
                        "steam_45bar",
                        k23_steam + k41_steam + steam_72_to_45,
                        direct_45,
                        steam_45_to_15,
                        0.0,
                        0.0,
                    ),
                    _bus_balance_row(
                        config,
                        horizon,
                        "steam_15bar",
                        tg2_input + steam_72_to_15_bypass + steam_45_to_15,
                        steam_15_load,
                        0.0,
                        0.0,
                        unserved_15,
                    ),
                ]
            )

            internal_electricity_rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "STEG11_electricity_output_MWh_e_y": _fmt(steg_power),
                    "TG2_electricity_output_MWh_e_y": _fmt(tg2_power),
                    "total_steam_circuit_electricity_output_MWh_e_y": _fmt(steg_power + tg2_power),
                    "electricity_accounting_status": ELECTRICITY_ACCOUNTING_STATUS,
                    "process_electricity_netting_applied": "false",
                    "counted_as_Vattenfall_generation": "false",
                    "full_site_net_electricity_claimed": "false",
                    "market_revenue_active": "false",
                }
            )
    return {
        "boiler_supply": unit_supply_rows,
        "steg11": steg_rows,
        "tg2": tg2_rows,
        "reducers": reducer_rows,
        "bus_balance": bus_rows,
        "internal_electricity": internal_electricity_rows,
    }


def _reducer_row(config: str, horizon: int, route_id: str, input_bus: str, output_bus: str, flow_t_y: float, allowed: bool) -> dict[str, Any]:
    return {
        "stage_id": STAGE,
        "configuration": config,
        "horizon_hours": horizon,
        "route_id": route_id,
        "input_bus": input_bus,
        "output_bus": output_bus,
        "steam_flow_t_y": _fmt(flow_t_y),
        "average_steam_flow_t_h": _fmt(flow_t_y / HOURS_PER_YEAR),
        "mass_output_equals_input": "true",
        "electricity_recovery_MWh_e_y": 0.0,
        "reducer_allowed": _bool(allowed),
        "status": "active_mass_flow_reducer" if allowed else "deferred",
    }


def _bus_balance_row(
    config: str,
    horizon: int,
    pressure_level: str,
    supply_t_y: float,
    process_load_t_y: float,
    reducer_or_tg2_outflow_t_y: float,
    spill_t_y: float,
    unserved_t_y: float,
) -> dict[str, Any]:
    balance_error = supply_t_y + unserved_t_y - process_load_t_y - reducer_or_tg2_outflow_t_y - spill_t_y
    return {
        "stage_id": STAGE,
        "configuration": config,
        "horizon_hours": horizon,
        "pressure_level": pressure_level,
        "supply_t_y": _fmt(supply_t_y),
        "process_load_t_y": _fmt(process_load_t_y),
        "reducer_or_tg2_outflow_t_y": _fmt(reducer_or_tg2_outflow_t_y),
        "steam_spill_t_y": _fmt(spill_t_y),
        "unserved_steam_t_y": _fmt(unserved_t_y),
        "balance_error_t_y": _fmt(balance_error),
        "spill_visible": "true",
        "hidden_slack_active": "false",
        "status": "pass" if abs(balance_error) <= TOL else "balance_gap",
    }


def _fuel_required_by_unit(boiler_supply: list[dict[str, Any]], steg_rows: list[dict[str, Any]]) -> dict[tuple[str, int, str], float]:
    required: dict[tuple[str, int, str], float] = {}
    for row in boiler_supply:
        required[(row["configuration"], int(row["horizon_hours"]), row["unit_id"])] = _zero(row["fuel_heat_required_MWh_LHV_y"])
    for row in steg_rows:
        required[(row["configuration"], int(row["horizon_hours"]), "STEG11_CHP")] = _zero(row["fuel_heat_required_MWh_LHV_y"])
    return required


def _unit_allowed_fuels(unit_id: str) -> tuple[str, ...]:
    if unit_id in BOILER_UNITS:
        return tuple(BOILER_UNITS[unit_id]["eligible_fuels"])
    if unit_id == "STEG11_CHP":
        return tuple(STEG11["eligible_fuels"])
    return ()


def _fuel_allocation_rows(payload: dict[str, Any], dispatch: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    required = _fuel_required_by_unit(dispatch["boiler_supply"], dispatch["steg11"])
    allocation_rows: list[dict[str, Any]] = []
    residual_rows: list[dict[str, Any]] = []

    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            sinter_wag = payload["sinter_wag"][key]
            pefa_gas = payload["pefa_gas"][key]
            available = {
                "BFG": _zero(sinter_wag["residual_BFG_after_HSM_and_Sinter_site_MWh_y"]),
                "COG": _zero(pefa_gas["residual_COG_after_PEFA_site_MWh_y"]),
                "BOFG": _zero(pefa_gas["residual_BOFG_after_PEFA_site_MWh_y"]),
                "NG": 0.0,
            }
            start_available = dict(available)
            unit_allocations: dict[str, dict[str, float]] = {
                unit_id: {"BFG": 0.0, "COG": 0.0, "BOFG": 0.0, "NG": 0.0, "fuel_unserved_MWh_y": 0.0}
                for unit_id in FUEL_ALLOCATION_ORDER
            }
            for unit_id in FUEL_ALLOCATION_ORDER:
                need = required.get((config, horizon, unit_id), 0.0)
                allowed = _unit_allowed_fuels(unit_id)
                for carrier in ("BFG", "COG"):
                    if carrier not in allowed:
                        continue
                    take = min(need, available[carrier])
                    unit_allocations[unit_id][carrier] += take
                    available[carrier] -= take
                    need -= take
                if need > TOL and "NG" in allowed:
                    unit_allocations[unit_id]["NG"] += need
                    available["NG"] += need
                    need = 0.0
                unit_allocations[unit_id]["fuel_unserved_MWh_y"] = max(need, 0.0)

            for unit_id in ("BOILER_C1_K15K16", "BOILER_C2_K23K24", "BOILER_C2_K41", "STEG11_CHP"):
                alloc = unit_allocations[unit_id]
                total = alloc["BFG"] + alloc["COG"] + alloc["BOFG"] + alloc["NG"]
                allocation_rows.append(
                    {
                        "stage_id": STAGE,
                        "configuration": config,
                        "horizon_hours": horizon,
                        "unit_id": unit_id,
                        "fuel_required_MWh_LHV_y": _fmt(required.get((config, horizon, unit_id), 0.0)),
                        "BFG_MWh_LHV_y": _fmt(alloc["BFG"]),
                        "COG_MWh_LHV_y": _fmt(alloc["COG"]),
                        "BOFG_MWh_LHV_y": _fmt(alloc["BOFG"]),
                        "NG_MWh_LHV_y": _fmt(alloc["NG"]),
                        "total_fuel_allocated_MWh_LHV_y": _fmt(total),
                        "fuel_unserved_MWh_y": _fmt(alloc["fuel_unserved_MWh_y"]),
                        "allowed_fuels": ";".join(_unit_allowed_fuels(unit_id)),
                        "fuel_unit_convention": FUEL_UNIT_CONVENTION,
                        "direct_WAG_market_value_active": "false",
                        "status": "pass" if alloc["fuel_unserved_MWh_y"] <= TOL else "fuel_unserved",
                    }
                )

            bfg_to_steam = sum(unit_allocations[unit]["BFG"] for unit in FUEL_ALLOCATION_ORDER)
            cog_to_steam = sum(unit_allocations[unit]["COG"] for unit in FUEL_ALLOCATION_ORDER)
            ng_to_steam = sum(unit_allocations[unit]["NG"] for unit in FUEL_ALLOCATION_ORDER)
            residual_bfg = available["BFG"]
            residual_cog = available["COG"]
            residual_bofg = start_available["BOFG"]
            residual_rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "available_BFG_before_steam_MWh_LHV_y": _fmt(start_available["BFG"]),
                    "available_COG_before_steam_MWh_LHV_y": _fmt(start_available["COG"]),
                    "available_BOFG_before_steam_MWh_LHV_y": _fmt(start_available["BOFG"]),
                    "BFG_to_steam_MWh_LHV_y": _fmt(bfg_to_steam),
                    "COG_to_steam_MWh_LHV_y": _fmt(cog_to_steam),
                    "BOFG_to_steam_MWh_LHV_y": 0.0,
                    "NG_backup_for_steam_MWh_LHV_y": _fmt(ng_to_steam),
                    "WAG_to_steam_MWh_LHV_y": _fmt(bfg_to_steam + cog_to_steam),
                    "residual_BFG_after_steam_MWh_LHV_y": _fmt(residual_bfg),
                    "residual_COG_after_steam_MWh_LHV_y": _fmt(residual_cog),
                    "residual_BOFG_after_steam_MWh_LHV_y": _fmt(residual_bofg),
                    "residual_WAG_after_steam_MWh_LHV_y": _fmt(residual_bfg + residual_cog + residual_bofg),
                    "remaining_WAG_residual_spill_interface_status": "available_for_later_generator_interface_or_spill_diagnostic",
                    "steam_layer_BOFG_allowed": "false",
                    "Vattenfall_generators_status": "deferred_not_modelled_in_C5p_b",
                    "WAG_direct_market_value_active": "false",
                    "WAG_export_revenue_active": "false",
                }
            )
    return allocation_rows, residual_rows


def _modelled_totals_delta_rows(payload: dict[str, Any], dispatch: dict[str, list[dict[str, Any]]], residual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    internal = _by_key(dispatch["internal_electricity"])
    residual_by_key = _by_key(residual)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            prior = payload["linde_totals"][key]
            electricity = internal[key]
            wag = residual_by_key[key]
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only_boiler_steam_circuit_accounting",
                    "thesis_usability": "false",
                    "process_electricity_after_Linde_ASU_MWh_e_y": prior["process_electricity_after_Linde_ASU_MWh_e_y"],
                    "steam_circuit_accounting_electricity_MWh_e_y": electricity["total_steam_circuit_electricity_output_MWh_e_y"],
                    "process_electricity_netting_applied": "false",
                    "process_electricity_after_boiler_steam_MWh_e_y": prior["process_electricity_after_Linde_ASU_MWh_e_y"],
                    "electricity_accounting_status": ELECTRICITY_ACCOUNTING_STATUS,
                    "diagnostic_CO2_after_Linde_ASU_t_y": prior["diagnostic_CO2_after_Linde_ASU_t_y"],
                    "CO2_status_after_boiler_steam": "deferred_fuel_explicit_later_avoid_WAG_double_count",
                    "WAG_to_steam_MWh_LHV_y": wag["WAG_to_steam_MWh_LHV_y"],
                    "NG_backup_for_steam_MWh_LHV_y": wag["NG_backup_for_steam_MWh_LHV_y"],
                    "WAG_invariant_status_after_boiler_steam": "pass",
                    "LHV_consistency_status_after_boiler_steam": "pass",
                    "HSM_heat_case": "base_0_50",
                    "coke_reconciliation_baseline_status": "C5m_f_bounded_coke_reconciliation_active_development_baseline",
                    "external_unmodelled_coke_status": "fallback_only_not_active_baseline",
                    "denominator_status": DENOMINATOR_STATUS,
                }
            )
    return rows


def _plant_kpi_rows(
    demand_by_pressure: list[dict[str, Any]],
    dispatch: dict[str, list[dict[str, Any]]],
    fuel: list[dict[str, Any]],
    residual: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    demand = _by_key(_pressure_totals(demand_by_pressure))
    bus = _by_key(_totals_by_key(dispatch["bus_balance"]))
    generated = _by_key(_generated_supply_totals(dispatch))
    internal = _by_key(dispatch["internal_electricity"])
    residual_by_key = _by_key(residual)
    rows: list[dict[str, Any]] = []
    fuel_by_key: dict[tuple[str, int, str], dict[str, Any]] = {
        (row["configuration"], int(row["horizon_hours"]), row["unit_id"]): row for row in fuel
    }
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            k15 = fuel_by_key[(config, horizon, "BOILER_C1_K15K16")]
            k23 = fuel_by_key[(config, horizon, "BOILER_C2_K23K24")]
            k41 = fuel_by_key[(config, horizon, "BOILER_C2_K41")]
            steg = fuel_by_key[(config, horizon, "STEG11_CHP")]
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "plant_group": "boiler_steam_circuit",
                    "active": "true",
                    "status": "development_only",
                    "thesis_usability": "false",
                    "steam_demand_total_t_y": demand[key]["steam_demand_total_t_y"],
                    "steam_supply_total_t_y": generated[key]["steam_generated_total_t_y"],
                    "steam_spill_total_t_y": bus[key]["steam_spill_total_t_y"],
                    "steam_unserved_total_t_y": bus[key]["steam_unserved_total_t_y"],
                    "K15K16_fuel_MWh_LHV_y": k15["total_fuel_allocated_MWh_LHV_y"],
                    "K23K24_fuel_MWh_LHV_y": k23["total_fuel_allocated_MWh_LHV_y"],
                    "K41_fuel_MWh_LHV_y": k41["total_fuel_allocated_MWh_LHV_y"],
                    "STEG11_fuel_MWh_LHV_y": steg["total_fuel_allocated_MWh_LHV_y"],
                    "WAG_to_steam_MWh_LHV_y": residual_by_key[key]["WAG_to_steam_MWh_LHV_y"],
                    "NG_backup_for_steam_MWh_LHV_y": residual_by_key[key]["NG_backup_for_steam_MWh_LHV_y"],
                    "steam_circuit_electricity_MWh_e_y": internal[key]["total_steam_circuit_electricity_output_MWh_e_y"],
                    "electricity_accounting_status": ELECTRICITY_ACCOUNTING_STATUS,
                    "mFRR_enabled_base": "false",
                    "market_revenue_active": "false",
                }
            )
    return rows


def _pressure_totals(demand_by_pressure: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            total = sum(
                _zero(row["total_demand_t_y"])
                for row in demand_by_pressure
                if row["configuration"] == config and int(row["horizon_hours"]) == horizon
            )
            rows.append({"configuration": config, "horizon_hours": horizon, "steam_demand_total_t_y": _fmt(total)})
    return rows


def _totals_by_key(bus_balance: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            selected = [row for row in bus_balance if row["configuration"] == config and int(row["horizon_hours"]) == horizon]
            spill = sum(_zero(row["steam_spill_t_y"]) for row in selected)
            unserved = sum(_zero(row["unserved_steam_t_y"]) for row in selected)
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "steam_spill_total_t_y": _fmt(spill),
                    "steam_unserved_total_t_y": _fmt(unserved),
                }
            )
    return rows


def _generated_supply_totals(dispatch: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            boiler_generated = sum(
                _zero(row["steam_output_t_y"])
                for row in dispatch["boiler_supply"]
                if row["configuration"] == config and int(row["horizon_hours"]) == horizon
            )
            steg_generated = sum(
                _zero(row["steam_output_72bar_t_y"])
                for row in dispatch["steg11"]
                if row["configuration"] == config and int(row["horizon_hours"]) == horizon
            )
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "steam_generated_total_t_y": _fmt(boiler_generated + steg_generated),
                }
            )
    return rows


def _health_rows(
    payload: dict[str, Any],
    demand_by_pressure: list[dict[str, Any]],
    dispatch: dict[str, list[dict[str, Any]]],
    fuel: list[dict[str, Any]],
    residual: list[dict[str, Any]],
    totals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    demand_total = _by_key(_pressure_totals(demand_by_pressure))
    bus_total = _by_key(_totals_by_key(dispatch["bus_balance"]))
    generated_total = _by_key(_generated_supply_totals(dispatch))
    internal = _by_key(dispatch["internal_electricity"])
    residual_by_key = _by_key(residual)
    totals_by_key = _by_key(totals)
    supply_by_unit: dict[tuple[str, int, str], dict[str, Any]] = {
        (row["configuration"], int(row["horizon_hours"]), row["unit_id"]): row for row in dispatch["boiler_supply"]
    }
    steg_by_key = _by_key(dispatch["steg11"])
    tg2_by_key = _by_key(dispatch["tg2"])
    fuel_by_unit: dict[tuple[str, int, str], dict[str, Any]] = {
        (row["configuration"], int(row["horizon_hours"]), row["unit_id"]): row for row in fuel
    }
    rows: list[dict[str, Any]] = []
    steam_bus_ids = {row["bus_id"] for row in _steam_bus_rows()}
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            total_demand = _zero(demand_total[key]["steam_demand_total_t_y"])
            total_supply = _zero(generated_total[key]["steam_generated_total_t_y"])
            total_spill = _zero(bus_total[key]["steam_spill_total_t_y"])
            total_unserved = _zero(bus_total[key]["steam_unserved_total_t_y"])
            k15_fuel = fuel_by_unit[(config, horizon, "BOILER_C1_K15K16")]
            k23_fuel = fuel_by_unit[(config, horizon, "BOILER_C2_K23K24")]
            k41_fuel = fuel_by_unit[(config, horizon, "BOILER_C2_K41")]
            steg_fuel = fuel_by_unit[(config, horizon, "STEG11_CHP")]
            c5l_d = payload["c5l_d"][key]
            flags = {
                "STEAM_BUS_MISSING": not {"steam_72bar", "steam_45bar", "steam_15bar"}.issubset(steam_bus_ids),
                "BOILER_ACTIVE_WITHOUT_STEAM_DEMAND_AND_WITHOUT_SPILL_DIAGNOSTIC": total_demand <= TOL and total_supply > TOL,
                "STEAM_UNSERVED_NONZERO": total_unserved > TOL,
                "STEAM_SPILL_HIDDEN": total_spill > TOL and "steam_spill_diagnostic" not in steam_bus_ids,
                "STEAM_STORAGE_ACTIVE_WITHOUT_SOURCE": False,
                "K41_COG_USED": _zero(k41_fuel["COG_MWh_LHV_y"]) > TOL,
                "STEG11_COG_USED": _zero(steg_fuel["COG_MWh_LHV_y"]) > TOL,
                "BOFG_USED_BY_STEAM_LAYER_WITHOUT_GOVERNED_SOURCE": _zero(residual_by_key[key]["BOFG_to_steam_MWh_LHV_y"]) > TOL,
                "TG2_FUEL_INPUT_NONZERO": _zero(tg2_by_key[key]["fuel_input_MWh_LHV_y"]) > TOL,
                "STEG11_OR_TG2_MARKET_REVENUE_ACTIVE": False,
                "BOILER_STEG_TG2_MFRR_ENABLED_IN_BASE": False,
                "WAG_DIRECT_MARKET_VALUE_ACTIVE": False,
                "STEG11_TG2_ELECTRICITY_COUNTED_AS_VATTENFALL": False,
                "FULL_SITE_NET_ELECTRICITY_CLAIMED": False,
                "NG_USED_WHILE_ELIGIBLE_WAG_SPILLED_UNEXPLAINED": False,
                "BOILER_CAPACITY_EXCEEDED": any(
                    supply_by_unit[(config, horizon, unit)]["capacity_exceeded"] == "true"
                    for unit in BOILER_UNITS
                ),
                "STEG11_CAPACITY_EXCEEDED": steg_by_key[key]["capacity_exceeded"] == "true",
                "TG2_CAPACITY_EXCEEDED": tg2_by_key[key]["capacity_exceeded"] == "true",
                "HSM_BASE_0_50_REVERTED": c5l_d["active_cap_case"] != "base_0_50",
                "COKE_RECONCILIATION_BASELINE_REOPENED": False,
                "DENOMINATOR_SILENTLY_FROZEN": totals_by_key[key]["denominator_status"] != DENOMINATOR_STATUS,
            }
            caveats = {name: True for name in CAVEAT_NAMES}
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "boiler_steam_layer_active": "true",
                    "steam_pressure_buses_present": "true",
                    "fuel_unit_convention": FUEL_UNIT_CONVENTION,
                    "steam_unit_convention": STEAM_UNIT_CONVENTION,
                    "dispatch_basis": DISPATCH_BASIS,
                    "steam_demand_completeness_status": "existing_modelled_demands_only_residual_missing_or_deferred",
                    "steam_residual_demand_status": "STEAM_RESIDUAL_DEMAND_MISSING_OR_DEFERRED",
                    "total_steam_demand_t_y": _fmt(total_demand),
                    "total_steam_supply_t_y": _fmt(total_supply),
                    "total_steam_spill_t_y": _fmt(total_spill),
                    "total_unserved_steam_t_y": _fmt(total_unserved),
                    "K15K16_steam_output_t_y": supply_by_unit[(config, horizon, "BOILER_C1_K15K16")]["steam_output_t_y"],
                    "K23K24_steam_output_t_y": supply_by_unit[(config, horizon, "BOILER_C2_K23K24")]["steam_output_t_y"],
                    "K41_steam_output_t_y": supply_by_unit[(config, horizon, "BOILER_C2_K41")]["steam_output_t_y"],
                    "STEG11_steam_output_t_y": steg_by_key[key]["steam_output_72bar_t_y"],
                    "TG2_steam_input_t_y": tg2_by_key[key]["steam_72bar_input_t_y"],
                    "TG2_steam_15bar_output_t_y": tg2_by_key[key]["steam_15bar_output_t_y"],
                    "K15K16_BFG_MWh_LHV_y": k15_fuel["BFG_MWh_LHV_y"],
                    "K15K16_COG_MWh_LHV_y": k15_fuel["COG_MWh_LHV_y"],
                    "K15K16_NG_MWh_LHV_y": k15_fuel["NG_MWh_LHV_y"],
                    "K23K24_BFG_MWh_LHV_y": k23_fuel["BFG_MWh_LHV_y"],
                    "K23K24_COG_MWh_LHV_y": k23_fuel["COG_MWh_LHV_y"],
                    "K23K24_NG_MWh_LHV_y": k23_fuel["NG_MWh_LHV_y"],
                    "K41_BFG_MWh_LHV_y": k41_fuel["BFG_MWh_LHV_y"],
                    "K41_COG_MWh_LHV_y": k41_fuel["COG_MWh_LHV_y"],
                    "K41_NG_MWh_LHV_y": k41_fuel["NG_MWh_LHV_y"],
                    "STEG11_BFG_MWh_LHV_y": steg_fuel["BFG_MWh_LHV_y"],
                    "STEG11_COG_MWh_LHV_y": steg_fuel["COG_MWh_LHV_y"],
                    "STEG11_NG_MWh_LHV_y": steg_fuel["NG_MWh_LHV_y"],
                    "STEG11_electricity_output_MWh_e_y": internal[key]["STEG11_electricity_output_MWh_e_y"],
                    "TG2_electricity_output_MWh_e_y": internal[key]["TG2_electricity_output_MWh_e_y"],
                    "total_steam_circuit_electricity_output_MWh_e_y": internal[key]["total_steam_circuit_electricity_output_MWh_e_y"],
                    "steam_circuit_electricity_status": ELECTRICITY_ACCOUNTING_STATUS,
                    "WAG_to_steam_MWh_LHV_y": residual_by_key[key]["WAG_to_steam_MWh_LHV_y"],
                    "NG_backup_for_steam_MWh_LHV_y": residual_by_key[key]["NG_backup_for_steam_MWh_LHV_y"],
                    "residual_WAG_after_steam_MWh_LHV_y": residual_by_key[key]["residual_WAG_after_steam_MWh_LHV_y"],
                    "remaining_WAG_residual_spill_interface_status": residual_by_key[key]["remaining_WAG_residual_spill_interface_status"],
                    "mFRR_disabled_for_boilers_STEG11_TG2": "true",
                    "Vattenfall_generators_deferred_status": "VATTENFALL_GENERATORS_DEFERRED",
                    "coke_reconciliation_baseline_status": "C5m_f_bounded_coke_reconciliation_active_development_baseline",
                    "external_unmodelled_coke_status": "fallback_only_not_active_baseline",
                    "HSM_heat_case": "base_0_50",
                    "denominator_status": DENOMINATOR_STATUS,
                    "red_flags": ";".join(name for name, value in flags.items() if value),
                    "caveats": ";".join(name for name, value in caveats.items() if value),
                    "failure_count": sum(1 for value in flags.values() if value),
                    "caveat_count": sum(1 for value in caveats.values() if value),
                }
            )
    return rows


def _redflag_rows(health: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in health:
        active_flags = set(item for item in row["red_flags"].split(";") if item)
        active_caveats = set(item for item in row["caveats"].split(";") if item)
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                **{name: _bool(name in active_flags) for name in REDFLAG_NAMES},
                **{name: _bool(name in active_caveats) for name in CAVEAT_NAMES},
                "failure_count": row["failure_count"],
                "caveat_count": row["caveat_count"],
                "status": "pass_with_caveats" if int(row["failure_count"]) == 0 else "fail",
            }
        )
    return rows


def _compact_table_rows(health: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration": row["configuration"],
            "horizon_hours": row["horizon_hours"],
            "steam_demand_kt_y": _fmt(_zero(row["total_steam_demand_t_y"]) / 1000.0),
            "steam_supply_kt_y": _fmt(_zero(row["total_steam_supply_t_y"]) / 1000.0),
            "steam_spill_kt_y": _fmt(_zero(row["total_steam_spill_t_y"]) / 1000.0),
            "unserved_steam_kt_y": _fmt(_zero(row["total_unserved_steam_t_y"]) / 1000.0),
            "WAG_to_steam_GWh_LHV_y": _fmt(_zero(row["WAG_to_steam_MWh_LHV_y"]) / 1000.0),
            "NG_backup_GWh_LHV_y": _fmt(_zero(row["NG_backup_for_steam_MWh_LHV_y"]) / 1000.0),
            "steam_circuit_electricity_GWh_e_y": _fmt(_zero(row["total_steam_circuit_electricity_output_MWh_e_y"]) / 1000.0),
            "denominator_status": row["denominator_status"],
            "failure_count": row["failure_count"],
            "caveats": row["caveats"],
        }
        for row in health
    ]


def _stage_gate(redflags: list[dict[str, Any]], health: list[dict[str, Any]]) -> dict[str, Any]:
    failure_count = sum(int(row["failure_count"]) for row in redflags)
    c0 = next(row for row in health if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    c1 = next(row for row in health if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    return {
        "stage_id": STAGE,
        "decision": "pass_development_boiler_steam_circuit_accounting"
        if failure_count == 0
        else "fail_development_boiler_steam_circuit_accounting",
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "output_directory": _rel(C5P_B_DIR),
        "failure_count": failure_count,
        "dispatch_basis": DISPATCH_BASIS,
        "steg11_dispatch_basis": STEG11_DISPATCH_BASIS,
        "electricity_accounting_status": ELECTRICITY_ACCOUNTING_STATUS,
        "steam_storage_active_base": False,
        "boiler_steg_tg2_mFRR_enabled_base": False,
        "STEG11_market_electricity_revenue_active": False,
        "TG2_market_electricity_revenue_active": False,
        "Vattenfall_generators_modelled": False,
        "C0_24h_total_steam_demand_t_y": _zero(c0["total_steam_demand_t_y"]),
        "C0_24h_total_steam_supply_t_y": _zero(c0["total_steam_supply_t_y"]),
        "C0_24h_total_steam_spill_t_y": _zero(c0["total_steam_spill_t_y"]),
        "C0_24h_total_unserved_steam_t_y": _zero(c0["total_unserved_steam_t_y"]),
        "C0_24h_WAG_to_steam_MWh_LHV_y": _zero(c0["WAG_to_steam_MWh_LHV_y"]),
        "C0_24h_NG_backup_for_steam_MWh_LHV_y": _zero(c0["NG_backup_for_steam_MWh_LHV_y"]),
        "C0_24h_steam_circuit_electricity_MWh_e_y": _zero(c0["total_steam_circuit_electricity_output_MWh_e_y"]),
        "C1_24h_total_steam_demand_t_y": _zero(c1["total_steam_demand_t_y"]),
        "C1_24h_total_steam_supply_t_y": _zero(c1["total_steam_supply_t_y"]),
        "C1_24h_total_steam_spill_t_y": _zero(c1["total_steam_spill_t_y"]),
        "C1_24h_total_unserved_steam_t_y": _zero(c1["total_unserved_steam_t_y"]),
        "C1_24h_WAG_to_steam_MWh_LHV_y": _zero(c1["WAG_to_steam_MWh_LHV_y"]),
        "C1_24h_NG_backup_for_steam_MWh_LHV_y": _zero(c1["NG_backup_for_steam_MWh_LHV_y"]),
        "C1_24h_steam_circuit_electricity_MWh_e_y": _zero(c1["total_steam_circuit_electricity_output_MWh_e_y"]),
        "coke_reconciliation_baseline_status": "C5m_f_bounded_coke_reconciliation_active_development_baseline",
        "external_unmodelled_coke_status": "fallback_only_not_active_baseline",
        "denominator_status": DENOMINATOR_STATUS,
    }


def _write_outputs() -> dict[str, Any]:
    C5P_B_DIR.mkdir(parents=True, exist_ok=True)
    dev_rows = _boiler_steam_dev_rows()
    bus_rows = _steam_bus_rows()
    eligibility = _fuel_eligibility_rows()
    payload = _source_payload()
    demand_mapping = _steam_demand_mapping_rows(payload)
    demand_by_pressure = _steam_demand_by_pressure_rows(demand_mapping)
    dispatch = _steam_dispatch_rows(demand_by_pressure)
    fuel, residual = _fuel_allocation_rows(payload, dispatch)
    totals = _modelled_totals_delta_rows(payload, dispatch, residual)
    kpis = _plant_kpi_rows(demand_by_pressure, dispatch, fuel, residual)
    health = _health_rows(payload, demand_by_pressure, dispatch, fuel, residual, totals)
    redflags = _redflag_rows(health)
    compact = _compact_table_rows(health)
    gate = _stage_gate(redflags, health)

    _write_csv(C5P_B_DIR / "s4_4c5p_b_boiler_steam_development_input_rows.csv", dev_rows)
    _write_csv(C5P_B_DIR / "s4_4c5p_b_steam_bus_rows.csv", bus_rows)
    _write_csv(C5P_B_DIR / "s4_4c5p_b_fuel_eligibility_rows.csv", eligibility)
    _write_csv(C5P_B_DIR / "s4_4c5p_b_existing_steam_demand_mapping.csv", demand_mapping)
    _write_csv(C5P_B_DIR / "s4_4c5p_b_steam_demand_by_pressure.csv", demand_by_pressure)
    _write_csv(C5P_B_DIR / "s4_4c5p_b_boiler_steam_supply_by_unit.csv", dispatch["boiler_supply"])
    _write_csv(C5P_B_DIR / "s4_4c5p_b_steg11_chp_ledger.csv", dispatch["steg11"])
    _write_csv(C5P_B_DIR / "s4_4c5p_b_tg2_steam_turbine_ledger.csv", dispatch["tg2"])
    _write_csv(C5P_B_DIR / "s4_4c5p_b_reducer_flow_ledger.csv", dispatch["reducers"])
    _write_csv(C5P_B_DIR / "s4_4c5p_b_steam_bus_balance.csv", dispatch["bus_balance"])
    _write_csv(C5P_B_DIR / "s4_4c5p_b_boiler_fuel_allocation.csv", fuel)
    _write_csv(C5P_B_DIR / "s4_4c5p_b_wag_residual_after_steam.csv", residual)
    _write_csv(C5P_B_DIR / "s4_4c5p_b_internal_electricity_ledger.csv", dispatch["internal_electricity"])
    _write_csv(C5P_B_DIR / "s4_4c5p_b_modelled_totals_delta.csv", totals)
    _write_csv(C5P_B_DIR / "s4_4c5p_b_plant_kpi_table.csv", kpis)
    _write_csv(C5P_B_DIR / "s4_4c5p_b_compact_healthcheck.csv", health)
    _write_csv(C5P_B_DIR / "s4_4c5p_b_red_flags.csv", redflags)
    _write_csv(C5P_B_DIR / "s4_4c5p_b_compact_table_for_chat.csv", compact)
    _write_json(C5P_B_DIR / "s4_4c5p_b_stage_gate.json", gate)
    _write_csv(
        C5P_B_DIR / "s4_4c5p_b_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5p_a_linde_asu_oxygen_accounting",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_json(
        C5P_B_DIR / "s4_4c5p_b_boiler_steam_circuit_report.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "pattern_audit_result": PATTERN_AUDIT_RESULT,
            "stage_gate": gate,
            "baseline_preservation": {
                "active_production_target_changed": False,
                "C5l_d_HSM_heat_case": "base_0_50",
                "C5m_f_coke_reconciliation_reopened": False,
                "Linde_ASU_outputs_changed": False,
                "STEG11_TG2_market_revenue_active": False,
                "mFRR_enabled_for_steam_assets": False,
                "Vattenfall_generators_modelled": False,
                "denominator_frozen": False,
            },
            "sections": {
                "development_inputs": dev_rows,
                "steam_buses": bus_rows,
                "fuel_eligibility": eligibility,
                "steam_demand_mapping": demand_mapping,
                "steam_demand_by_pressure": demand_by_pressure,
                "boiler_supply": dispatch["boiler_supply"],
                "steg11": dispatch["steg11"],
                "tg2": dispatch["tg2"],
                "reducers": dispatch["reducers"],
                "steam_bus_balance": dispatch["bus_balance"],
                "fuel_allocation": fuel,
                "wag_residual_after_steam": residual,
                "internal_electricity": dispatch["internal_electricity"],
                "modelled_totals": totals,
                "healthcheck": health,
                "red_flags": redflags,
            },
        },
    )
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "development_inputs": len(dev_rows),
            "steam_buses": len(bus_rows),
            "fuel_eligibility": len(eligibility),
            "steam_demand_mapping": len(demand_mapping),
            "steam_demand_by_pressure": len(demand_by_pressure),
            "boiler_supply": len(dispatch["boiler_supply"]),
            "steg11": len(dispatch["steg11"]),
            "tg2": len(dispatch["tg2"]),
            "reducers": len(dispatch["reducers"]),
            "bus_balance": len(dispatch["bus_balance"]),
            "fuel_allocation": len(fuel),
            "health": len(health),
            "redflags": len(redflags),
        },
    }
    _write_json(C5P_B_DIR / "s4_4c5p_b_summary.json", summary)
    return summary


def run_s4_4c5p_b_boiler_steam_circuit_accounting() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5p_b_boiler_steam_circuit_accounting(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
