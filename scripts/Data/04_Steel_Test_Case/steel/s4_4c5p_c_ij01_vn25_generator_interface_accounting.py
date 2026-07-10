"""S4.4c5p_c IJ01/VN25 generator-interface accounting layer.

This development-only stage adds carrier-specific IJ01/VN25 generator
interface accounting on top of C5p_b boiler/steam residual WAG ledgers. It is
not a Vattenfall digital twin, not price-responsive generator dispatch, and not
an electricity-revenue layer.
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
from .s4_4c5p_b_boiler_steam_circuit_accounting import (
    C5P_B_DIR,
    run_s4_4c5p_b_boiler_steam_circuit_accounting,
)


STAGE = "S4.4c5p_c_ij01_vn25_generator_interface_accounting"
C5P_C_DIR = S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting"
SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/IJ01_VN25_GENERATORS_Parameters.md")
DEPENDENCY_CHAIN = (
    "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b "
    "-> C5m_c -> C5m_d -> C5m_e -> C5m_f -> C5n_a -> C5n_b -> C5o_a "
    "-> C5o_b -> C5o_c -> C5p_a -> C5p_b -> C5p_c"
)
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_healthcheck_pattern;"
    "generator_values_loaded_from_IJ01_VN25_source_card_development_rows;"
    "carrier_specific_BFG_BOFG_COG_NG_interface_accounting;"
    "electricity_offset_reporting_only_not_DA_market_revenue"
)

TOL = 1e-6
PJ_TO_MWH = 1_000_000.0 / 3.6
MWH_TO_PJ = 3.6 / 1_000_000.0
HOURS_PER_YEAR = 8760.0

GENERATOR_DISPATCH_MODE = "fixed_or_validation_scaled_interface"
GENERATOR_ELECTRICITY_VALUE_MODE = "offset_site_grid_import"
GENERATOR_EXPORT_REVENUE_ENABLED_BASE = False
GENERATOR_PRICE_RESPONSIVE_DISPATCH_BASE = False
GENERATOR_MFRR_ENABLED_BASE = False
ELECTRICITY_ACCOUNTING_STATUS = "internal_offset_or_reporting_only_not_DA_market_revenue"
DENOMINATOR_STATUS = "unresolved_until_residual_loads_and_boundary_complete"

FUELS = ("BFG", "BOFG", "COG", "NG")
WAG_FUELS = ("BFG", "BOFG", "COG")
GENERATOR_ORDER = ("VN25", "IJ01")

GENERATOR_UNITS: dict[str, dict[str, Any]] = {
    "VN25": {
        "enabled_base": True,
        "role": "primary_residual_gas_generator",
        "allowed_fuels": ("BFG", "BOFG", "COG", "NG"),
        "electric_efficiency_dev": 0.345,
        "electricity_conversion_status": "VN25_EFFICIENCY_DEVELOPMENT_ONLY",
        "steam_output_status": "not_applicable_electricity_only_abstraction",
        "capacity_mw_dev": 350.0,
        "wag_capacity_m3_h_dev": 600_000.0,
    },
    "IJ01": {
        "enabled_base": True,
        "role": "chp_backup_or_reserve",
        "allowed_fuels": ("BFG", "BOFG", "COG"),
        "electric_efficiency_dev": None,
        "electricity_conversion_status": "IJ01_ELECTRICITY_CONVERSION_DEFERRED",
        "steam_output_status": "IJ01_CHP_STEAM_OUTPUT_DEFERRED",
        "capacity_mw_dev": None,
        "wag_capacity_m3_h_dev": None,
    },
    "VN24": {
        "enabled_base": False,
        "role": "cold_backup_reserve_only",
        "allowed_fuels": (),
        "electric_efficiency_dev": None,
        "electricity_conversion_status": "VN24_BACKUP_DEFERRED",
        "steam_output_status": "not_active",
        "capacity_mw_dev": None,
        "wag_capacity_m3_h_dev": None,
    },
}

C1_PREFERRED_ANCHORS_PJ: dict[str, dict[str, float]] = {
    "VN25": {"BFG": 8.4, "BOFG": 1.2, "COG": 0.1, "NG": 4.1},
    "IJ01": {"BFG": 0.7, "BOFG": 0.1, "COG": 0.0, "NG": 0.0},
}
C1_PREFERRED_TOTAL_ANCHORS_PJ = {"VN25": 13.7, "IJ01": 0.8}
C1_OPERATION_ANCHORS: dict[str, dict[str, Any]] = {
    "VN25": {
        "operation_hours_table": 7519.0,
        "operation_hours_text": "~7500",
        "operation_load_text": "~0.50",
        "operation_share_text": 0.85,
    },
    "IJ01": {
        "operation_hours_table": 899.0,
        "operation_hours_text": "~1300",
        "operation_load_text": "",
        "operation_share_text": 0.15,
    },
}
C1_FLARE_ANCHOR_PJ = 0.1
C1_GENERATOR_TOTAL_WITH_FLARE_ANCHOR_PJ = 14.6
C1_IJ01_BASE_VARIANT = {
    "VN25_TOTAL_FUEL_IJ01_BASE_VARIANT_PJ_Y": 1.7,
    "IJ01_TOTAL_FUEL_IJ01_BASE_VARIANT_PJ_Y": 8.3,
    "VN25_OPERATION_HOURS_IJ01_BASE_VARIANT": 961.0,
    "IJ01_OPERATION_HOURS_IJ01_BASE_VARIANT": 7418.0,
    "GENERATOR_TOTAL_FUEL_IJ01_BASE_VARIANT_PJ_Y": 10.0,
    "GENERATOR_FUEL_SAVING_VARIANT_PJ_Y": 3.5,
}
C0_CONTEXT_ANCHORS = {
    "CURRENT_PRODUCT_GAS_REUSE_ANNUAL_PJ_Y": 54.0,
    "CURRENT_TATA_AVG_ELECTRIC_POWER_MW": 360.0,
    "CURRENT_VATTENFALL_RESIDUAL_GAS_ELECTRICITY_TWH_Y": 2.0,
    "TRANSFERRED_POWER_PLANTS_TOTAL_CAPACITY_MW": 770.0,
}
C0_GENERATOR_INTERFACE_UNIT = "C0_CURRENT_GENERATOR_INTERFACE"
C0_GENERATOR_INTERFACE_STATUS = "C0_residual_wag_generator_interface_active"
C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y = 2_000_000.0
C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV = 0.34

REDFLAG_NAMES = [
    "C0_GENERATORS_REPORTED_AS_PHYSICALLY_INACTIVE",
    "C0_GENERATOR_FUEL_ZERO_WHILE_RESIDUAL_WAG_AVAILABLE",
    "C0_GENERATOR_USES_GENERIC_WAG_WITHOUT_CARRIER_SPLIT",
    "C0_GENERATOR_CONSUMES_MORE_WAG_THAN_AVAILABLE",
    "C0_GENERATOR_ELECTRICITY_TARGET_ENFORCED_TO_2TWH",
    "C0_GENERATOR_ELECTRICITY_ANCHOR_USED_AS_EQUALITY_CONSTRAINT",
    "C0_GENERATOR_FUEL_BACKCALCULATED_FROM_2TWH_ANCHOR",
    "C0_GENERATOR_ELECTRICITY_TARGET_MET_WITHOUT_FUEL",
    "C0_GENERATOR_ELECTRICITY_COUNTED_AS_DA_REVENUE",
    "C0_GENERATOR_ELECTRICITY_COUNTED_AS_EXPORT_REVENUE",
    "C0_FULL_SITE_NET_IMPORT_CLAIMED_WITHOUT_BOUNDARY",
    "C0_770MW_USED_AS_UNIT_CAPACITY",
    "C0_360MW_AVG_POWER_USED_AS_CONNECTION_CAPACITY",
    "C0_54PJ_PRODUCT_GAS_REUSE_USED_AS_EXACT_GENERATOR_FUEL_WITHOUT_INTERPRETATION",
    "GENERATOR_EXPORT_REVENUE_ACTIVE",
    "GENERATOR_PRICE_RESPONSIVE_DISPATCH_ACTIVE",
    "GENERATOR_MFRR_ENABLED_IN_BASE",
    "WAG_DIRECT_MARKET_VALUE_ACTIVE",
    "GENERIC_WAG_TO_GENERATORS_ACTIVE",
    "BFG_COG_BOFG_COLLAPSED_WITHOUT_EXPLICIT_MIXING",
    "VN24_ACTIVE_IN_BASE",
    "IJ01_NG_USED_IN_BASE",
    "GENERATOR_CONSUMES_UNLIMITED_WAG",
    "GENERATOR_OUTPUT_COUNTED_AS_DA_REVENUE",
    "GENERATOR_OUTPUT_COUNTED_AS_FINAL_FULL_SITE_NET_IMPORT_WITHOUT_BOUNDARY",
    "VN25_OR_IJ01_USES_770MW_AS_UNIT_CAPACITY",
    "ATHANASIADIS_350MW_TREATED_AS_PUBLIC_TATA_CAPACITY",
    "TABLE_5_5_USED_AS_HOURLY_DISPATCH_SCHEDULE",
    "FORECAST_COMPARISON_WITH_CHANGED_GENERATOR_POLICY",
    "BOILER_STEAM_LAYER_CHANGED_UNEXPECTEDLY",
    "HSM_BASE_0_50_REVERTED",
    "COKE_RECONCILIATION_BASELINE_REOPENED",
    "DENOMINATOR_SILENTLY_FROZEN",
]

CAVEAT_NAMES = [
    "C0_GENERATOR_INTERFACE_DEVELOPMENT_ONLY",
    "C0_RESIDUAL_WAG_GENERATOR_INTERFACE_ACTIVE",
    "C0_GENERATOR_2TWH_VALIDATION_ANCHOR_ONLY",
    "C0_GENERATOR_CARRIER_SPLIT_UNDERPARAMETERISED",
    "C0_GENERATOR_CARRIER_SPLIT_PROXY_DEVELOPMENT_ONLY",
    "C0_GENERATOR_EFFICIENCY_DEVELOPMENT_ONLY",
    "C0_GENERATOR_ELECTRICITY_OFFSET_REPORTING_ONLY",
    "C0_PRODUCT_GAS_REUSE_CONTEXT_ONLY",
    "CURRENT_TATA_AVG_POWER_CONTEXT_ONLY",
    "GENERATOR_INTERFACE_DEVELOPMENT_ONLY",
    "GENERATOR_ELECTRICITY_OFFSET_REPORTING_ONLY",
    "GENERATOR_EXPORT_REVENUE_DEFERRED",
    "GENERATOR_PRICE_RESPONSIVE_MODE_DEFERRED",
    "GENERATOR_MFRR_DEFERRED",
    "VN24_BACKUP_DEFERRED",
    "IJ01_CHP_STEAM_OUTPUT_DEFERRED",
    "IJ01_ELECTRICITY_CONVERSION_DEFERRED",
    "VN25_EFFICIENCY_DEVELOPMENT_ONLY",
    "ATHANASIADIS_CAPACITY_PRECEDENT_ONLY",
    "TRANSFERRED_770MW_TOTAL_CAPACITY_CONTEXT_ONLY",
    "TABLE_5_5_ANNUAL_ANCHORS_NOT_HOURLY_SCHEDULES",
    "IJ01_HOURS_TEXT_TABLE_CONFLICT",
    "WAG_GAS_QUALITY_WOBBE_DEFERRED",
    "CO2_FUEL_EXPLICIT_DEFERRED",
    "FULL_SITE_ELECTRICITY_BOUNDARY_INCOMPLETE",
    "DENOMINATOR_UNRESOLVED_UNTIL_RESIDUAL_LOADS_AND_BOUNDARY_COMPLETE",
    "GENERATOR_NOT_THESIS_APPROVED",
]


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _bool(value: bool) -> str:
    return str(value).lower()


def _by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _dev_row(
    parameter_id: str,
    base_value: Any,
    unit: str,
    parameter_group: str,
    caveat: str,
    *,
    input_status: str = "development_candidate_reviewed_from_source_card",
    evidence_strength: str = "source_card_public_anchor_or_project_policy",
    active_base: str = "true",
) -> dict[str, Any]:
    return {
        "stage_id": STAGE,
        "parameter_id": parameter_id,
        "base_value": base_value,
        "unit": unit,
        "parameter_group": parameter_group,
        "input_status": input_status,
        "active_base": active_base,
        "thesis_usability": "false",
        "source_card": _rel(SOURCE_CARD),
        "source_or_candidate_evidence": "IJ01_VN25_GENERATORS_Parameters.md",
        "evidence_strength": evidence_strength,
        "human_review_required": "true",
        "codex_may_decide": "false",
        "caveat": caveat,
    }


def _generator_dev_rows() -> list[dict[str, Any]]:
    rows = [
        _dev_row("GENERATOR_DISPATCH_MODE", GENERATOR_DISPATCH_MODE, "policy", "mode", "Mode A only; fixed annual/interface accounting, not price dispatch."),
        _dev_row("GENERATOR_ELECTRICITY_VALUE_MODE", GENERATOR_ELECTRICITY_VALUE_MODE, "policy", "mode", "Internal offset/reporting only; not export revenue."),
        _dev_row("GENERATOR_EXPORT_REVENUE_ENABLED_BASE", "false", "bool", "market_policy", "No generator export revenue in base."),
        _dev_row("GENERATOR_PRICE_RESPONSIVE_DISPATCH_BASE", "false", "bool", "market_policy", "No DA price-responsive generator dispatch."),
        _dev_row("GENERATOR_MFRR_ENABLED_BASE", "false", "bool", "market_policy", "No generator mFRR in base."),
        _dev_row("GENERIC_WAG_TO_GENERATORS_ACTIVE", "false", "bool", "carrier_policy", "BFG, BOFG and COG remain separate carriers."),
        _dev_row("C0_GENERATOR_INTERFACE_STATUS", C0_GENERATOR_INTERFACE_STATUS, "status", "C0_option_B", "C0 residual-WAG-derived development-only generator-interface; not unit dispatch."),
        _dev_row("C0_GENERATOR_INTERFACE_UNIT", C0_GENERATOR_INTERFACE_UNIT, "unit_id", "C0_option_B", "Aggregate C0 interface unit used because no public VN25/IJ01 C0 split is claimed."),
        _dev_row("C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y", C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y, "MWh_e/y", "C0_option_B", "2.0 TWh/y residual-gas electricity context anchor used only as validation comparison, not a dispatch target."),
        _dev_row("C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV", C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV, "MWh_e/MWh_fuel", "C0_option_B", "Development-only single value from 0.34-0.35 source-card range; not official Tata/Vattenfall efficiency."),
        _dev_row("C0_GENERATOR_CARRIER_SPLIT_PROXY_DEVELOPMENT_ONLY", "true", "bool", "C0_option_B", "C0 carrier allocation uses transparent proportional split over governed residual BFG/BOFG/COG after steam."),
        _dev_row("VN25_ENABLED_BASE", "true", "bool", "topology", "VN25 is primary C1 residual-gas generator interface."),
        _dev_row("IJ01_ENABLED_BASE", "true", "bool", "topology", "IJ01 is CHP/backup generator interface; steam and electricity split deferred."),
        _dev_row("VN24_ENABLED_BASE", "false", "bool", "topology", "VN24 is cold/backup reserve only and inactive in base."),
        _dev_row("VN25_ELECTRIC_EFFICIENCY_DEV", 0.345, "MWh_e/MWh_fuel", "development_conversion", "Midpoint of 0.34-0.35; development smoke/reporting only."),
        _dev_row("VN25_ELECTRIC_CAPACITY_MW_DEV", 350.0, "MW", "capacity_context", "Athanasiadis development precedent only, not public Tata capacity."),
        _dev_row("VN25_WAG_CAPACITY_M3_H_DEV", 600000.0, "m3/h", "capacity_context", "Athanasiadis development precedent only, not public Tata capacity."),
        _dev_row("TRANSFERRED_POWER_PLANTS_TOTAL_CAPACITY_MW", 770.0, "MW", "context_anchor", "Total transferred capacity only; never a VN25/IJ01 unit capacity."),
        _dev_row("IJ01_ELECTRIC_EFFICIENCY_DEV", "deferred", "MWh_e/MWh_fuel", "development_conversion", "IJ01 CHP electricity/steam split not source-backed.", input_status="development_deferred"),
        _dev_row("IJ01_STEAM_OUTPUT_STATUS", "deferred", "status", "chp_topology", "IJ01 CHP functionality visible, quantitative steam output deferred.", input_status="development_deferred"),
        _dev_row("GENERATOR_CO2_ACCOUNTING_MODE", "fuel_explicit_later", "policy", "co2", "Avoid WAG combustion CO2 double counting in C5p_c.", input_status="development_deferred"),
    ]
    for unit_id, config in GENERATOR_UNITS.items():
        for carrier in FUELS + ("GENERIC_WAG",):
            allowed = carrier in config["allowed_fuels"]
            if unit_id == "VN24":
                allowed = False
            rows.append(
                _dev_row(
                    f"{unit_id}_{carrier}_ALLOWED_BASE",
                    _bool(allowed),
                    "bool",
                    "fuel_eligibility",
                    _eligibility_caveat(unit_id, carrier, allowed),
                    input_status="development_assumption" if carrier == "GENERIC_WAG" else "development_candidate_reviewed_from_source_card",
                )
            )
    for generator_id, anchors in C1_PREFERRED_ANCHORS_PJ.items():
        for carrier, value in anchors.items():
            rows.append(
                _dev_row(
                    f"{generator_id}_{carrier}_C1_PJ_Y",
                    value,
                    "PJ/y",
                    "C1_preferred_validation_anchor",
                    "Table 5.5 annual validation anchor, not hourly dispatch.",
                    input_status="validation_anchor_not_dispatch_constraint",
                )
            )
        rows.append(
                _dev_row(
                    f"{generator_id}_TOTAL_FUEL_C1_PJ_Y",
                    C1_PREFERRED_TOTAL_ANCHORS_PJ[generator_id],
                    "PJ/y",
                    "C1_preferred_validation_anchor",
                    "Explicit Table 5.5 total; rounded carrier rows are also reported.",
                    input_status="validation_anchor_not_dispatch_constraint",
                )
            )
    rows.extend(
        [
            _dev_row("GENERATOR_FLARE_C1_PJ_Y", C1_FLARE_ANCHOR_PJ, "PJ/y", "C1_preferred_validation_anchor", "Explicit flaring anchor; reported as diagnostic.", input_status="validation_anchor_not_dispatch_constraint"),
            _dev_row("GENERATOR_TOTAL_FUEL_C1_PJ_Y", C1_GENERATOR_TOTAL_WITH_FLARE_ANCHOR_PJ, "PJ/y", "C1_preferred_validation_anchor", "VN25 + IJ01 + flare Table 5.5 total.", input_status="validation_anchor_not_dispatch_constraint"),
            _dev_row("VN25_OPERATION_HOURS_C1_TABLE", 7519, "h/y", "C1_preferred_validation_anchor", "Annual operating-hour anchor, not hourly schedule.", input_status="validation_anchor_not_dispatch_constraint"),
            _dev_row("IJ01_OPERATION_HOURS_C1_TABLE", 899, "h/y", "C1_preferred_validation_anchor", "Conflicts with ~1300 h/y text; report conflict.", input_status="validation_anchor_not_dispatch_constraint"),
            _dev_row("VN25_OPERATION_HOURS_C1_TEXT", "~7500", "h/y", "C1_text_anchor", "Text anchor, not hourly schedule.", input_status="validation_anchor_not_dispatch_constraint"),
            _dev_row("IJ01_OPERATION_HOURS_C1_TEXT", "~1300", "h/y", "C1_text_anchor", "Conflicts with Table 5.5 899 h/y.", input_status="validation_anchor_not_dispatch_constraint"),
        ]
    )
    for parameter_id, value in C1_IJ01_BASE_VARIANT.items():
        rows.append(
            _dev_row(
                parameter_id,
                value,
                "PJ/y" if "FUEL" in parameter_id else "h/y",
                "C1_IJ01_base_variant_sensitivity",
                "Sensitivity/deferred row only; not active base.",
                input_status="sensitivity_anchor_deferred_not_active_base",
                active_base="false",
            )
        )
    for parameter_id, value in C0_CONTEXT_ANCHORS.items():
        if parameter_id == "TRANSFERRED_POWER_PLANTS_TOTAL_CAPACITY_MW":
            continue
        rows.append(
            _dev_row(
                parameter_id,
                value,
                "PJ/y" if "PJ" in parameter_id else ("TWh/y" if "TWH" in parameter_id else "MW"),
                "C0_context_validation_anchor",
                "Context/sanity check only; not forced generator dispatch.",
                input_status="context_validation_anchor_not_dispatch_constraint",
                active_base="false",
            )
        )
    return rows


def _generator_bus_rows() -> list[dict[str, Any]]:
    rows = [
        ("bfg_bus", "BFG", "energy", "existing_C5_WAG_carrier"),
        ("bofg_bus", "BOFG", "energy", "existing_C5_WAG_carrier"),
        ("cog_bus", "COG", "energy", "existing_C5_WAG_carrier"),
        ("natural_gas_bus", "NG", "energy", "external_NG_interface"),
        ("vn25_fuel_energy_bus", "mixed_fuel_energy", "energy", "VN25 controller bus"),
        ("ij01_fuel_energy_bus", "mixed_fuel_energy", "energy", "IJ01 controller bus"),
        ("electricity_internal_bus", "electricity", "electricity", "internal offset/reporting only"),
        ("steam_or_heat_ij01_bus", "steam_or_heat", "utility", "IJ01 CHP output deferred"),
        ("flare_or_spill_bus", "WAG residual/spill", "diagnostic", "explicit residual/flaring interface"),
        ("co2_bus", "CO2", "diagnostic", "fuel-explicit CO2 deferred"),
    ]
    return [
        {
            "stage_id": STAGE,
            "bus_id": bus_id,
            "carrier": carrier,
            "bus_type": bus_type,
            "status": status,
            "thesis_usability": "false",
        }
        for bus_id, carrier, bus_type, status in rows
    ]


def _fuel_eligibility_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for unit_id, config in GENERATOR_UNITS.items():
        for carrier in FUELS + ("GENERIC_WAG",):
            allowed = carrier in config["allowed_fuels"] and config["enabled_base"]
            rows.append(
                {
                    "stage_id": STAGE,
                    "unit_id": unit_id,
                    "input_carrier": carrier,
                    "allowed": _bool(allowed),
                    "enabled_base": _bool(bool(config["enabled_base"])),
                    "source_status": _eligibility_source_status(unit_id, carrier, allowed),
                    "generic_wag_carrier_active": "false",
                    "direct_WAG_market_value_active": "false",
                    "export_revenue_active": "false",
                    "mFRR_enabled_base": "false",
                    "thesis_usability": "false",
                    "caveat": _eligibility_caveat(unit_id, carrier, allowed),
                }
            )
    return rows


def _eligibility_source_status(unit_id: str, carrier: str, allowed: bool) -> str:
    if unit_id == "VN24":
        return "blocked_VN24_cold_backup_deferred"
    if carrier == "GENERIC_WAG":
        return "blocked_generic_WAG_forbidden"
    if unit_id == "IJ01" and carrier == "NG":
        return "blocked_IJ01_NG_not_allowed_in_base"
    if carrier == "NG" and allowed:
        return "source_backed_external_NG_for_VN25"
    if allowed:
        return "source_backed_carrier_specific_generator_fuel"
    return "blocked"


def _eligibility_caveat(unit_id: str, carrier: str, allowed: bool) -> str:
    if unit_id == "VN24":
        return "VN24 is documented cold/backup reserve only and inactive in base."
    if carrier == "GENERIC_WAG":
        return "Generic WAG-to-generator carrier is forbidden; BFG/BOFG/COG stay separate."
    if unit_id == "IJ01" and carrier == "NG":
        return "IJ01 NG is blocked in base; Table 5.5 preferred and variant rows show zero NG."
    if carrier == "NG" and allowed:
        return "VN25 NG follows annual validation anchor; not a price-responsive fuel choice."
    if allowed:
        return "Carrier-specific annual/interface accounting only; no direct WAG value."
    return "Carrier not active for this unit in the base interface."


def _source_payload() -> dict[str, Any]:
    run_s4_4c5p_b_boiler_steam_circuit_accounting()
    return {
        "steam_residual": _by_key(_read_csv(C5P_B_DIR / "s4_4c5p_b_wag_residual_after_steam.csv")),
        "steam_totals": _by_key(_read_csv(C5P_B_DIR / "s4_4c5p_b_modelled_totals_delta.csv")),
        "steam_electricity": _by_key(_read_csv(C5P_B_DIR / "s4_4c5p_b_internal_electricity_ledger.csv")),
        "steam_health": _by_key(_read_csv(C5P_B_DIR / "s4_4c5p_b_compact_healthcheck.csv")),
    }


def _anchor_mwh(config: str, generator_id: str, carrier: str) -> float:
    if config != C1:
        return 0.0
    return C1_PREFERRED_ANCHORS_PJ[generator_id][carrier] * PJ_TO_MWH


def _fuel_allocation_rows(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fuel_rows: list[dict[str, Any]] = []
    residual_rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            residual = payload["steam_residual"][key]
            available = {
                "BFG": _zero(residual["residual_BFG_after_steam_MWh_LHV_y"]),
                "BOFG": _zero(residual["residual_BOFG_after_steam_MWh_LHV_y"]),
                "COG": _zero(residual["residual_COG_after_steam_MWh_LHV_y"]),
                "NG": 0.0,
            }
            start_available = dict(available)
            allocations: dict[str, dict[str, dict[str, float]]] = {
                unit: {carrier: {"anchor": _anchor_mwh(config, unit, carrier), "allocated": 0.0, "gap": 0.0} for carrier in FUELS}
                for unit in GENERATOR_ORDER
            }
            c0_interface = {
                carrier: {"anchor": 0.0, "allocated": 0.0, "gap": 0.0}
                for carrier in FUELS
            }
            c0_validation_anchor_electricity = 0.0
            c0_actual_electricity = 0.0
            c0_available_generator_fuel = 0.0
            c0_total_gap = 0.0
            c0_carrier_split_status = ""
            if config == C0:
                residual_wag_available = sum(start_available[carrier] for carrier in WAG_FUELS)
                c0_validation_anchor_electricity = C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y
                c0_available_generator_fuel = residual_wag_available
                c0_total_allocated = residual_wag_available
                c0_actual_electricity = c0_total_allocated * C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV
                c0_carrier_split_status = "proportional_split_over_governed_residual_BFG_BOFG_COG_after_steam"
                for carrier in WAG_FUELS:
                    c0_interface[carrier]["allocated"] = start_available[carrier]
                    available[carrier] -= c0_interface[carrier]["allocated"]
            if config == C1:
                for unit in GENERATOR_ORDER:
                    for carrier in FUELS:
                        anchor = allocations[unit][carrier]["anchor"]
                        if anchor <= TOL:
                            continue
                        if carrier == "NG":
                            if carrier in GENERATOR_UNITS[unit]["allowed_fuels"]:
                                allocations[unit][carrier]["allocated"] = anchor
                                available["NG"] += anchor
                            else:
                                allocations[unit][carrier]["gap"] = anchor
                            continue
                        if carrier not in GENERATOR_UNITS[unit]["allowed_fuels"]:
                            allocations[unit][carrier]["gap"] = anchor
                            continue
                        take = min(anchor, available[carrier])
                        allocations[unit][carrier]["allocated"] = take
                        allocations[unit][carrier]["gap"] = max(anchor - take, 0.0)
                        available[carrier] -= take

            for unit in GENERATOR_ORDER:
                unit_total_anchor = 0.0
                unit_total_allocated = 0.0
                unit_total_gap = 0.0
                for carrier in FUELS:
                    entry = allocations[unit][carrier]
                    unit_total_anchor += entry["anchor"]
                    unit_total_allocated += entry["allocated"]
                    unit_total_gap += entry["gap"]
                reported_total_anchor = (
                    C1_PREFERRED_TOTAL_ANCHORS_PJ[unit] * PJ_TO_MWH if config == C1 else unit_total_anchor
                )
                fuel_rows.append(
                    {
                        "stage_id": STAGE,
                        "configuration": config,
                        "horizon_hours": horizon,
                        "unit_id": unit,
                        "enabled_base": _bool(bool(GENERATOR_UNITS[unit]["enabled_base"])),
                        "dispatch_mode": GENERATOR_DISPATCH_MODE,
                        "annual_anchor_not_hourly_dispatch_constraint": "true",
                        "BFG_anchor_MWh_LHV_y": _fmt(allocations[unit]["BFG"]["anchor"]),
                        "BOFG_anchor_MWh_LHV_y": _fmt(allocations[unit]["BOFG"]["anchor"]),
                        "COG_anchor_MWh_LHV_y": _fmt(allocations[unit]["COG"]["anchor"]),
                        "NG_anchor_MWh_LHV_y": _fmt(allocations[unit]["NG"]["anchor"]),
                        "BFG_MWh_LHV_y": _fmt(allocations[unit]["BFG"]["allocated"]),
                        "BOFG_MWh_LHV_y": _fmt(allocations[unit]["BOFG"]["allocated"]),
                        "COG_MWh_LHV_y": _fmt(allocations[unit]["COG"]["allocated"]),
                        "NG_MWh_LHV_y": _fmt(allocations[unit]["NG"]["allocated"]),
                        "BFG_gap_unserved_MWh_LHV_y": _fmt(allocations[unit]["BFG"]["gap"]),
                        "BOFG_gap_unserved_MWh_LHV_y": _fmt(allocations[unit]["BOFG"]["gap"]),
                        "COG_gap_unserved_MWh_LHV_y": _fmt(allocations[unit]["COG"]["gap"]),
                        "NG_gap_unserved_MWh_LHV_y": _fmt(allocations[unit]["NG"]["gap"]),
                        "carrier_sum_fuel_anchor_MWh_LHV_y": _fmt(unit_total_anchor),
                        "total_fuel_anchor_MWh_LHV_y": _fmt(reported_total_anchor),
                        "total_fuel_allocated_MWh_LHV_y": _fmt(unit_total_allocated),
                        "total_fuel_gap_unserved_MWh_LHV_y": _fmt(unit_total_gap),
                        "carrier_sum_fuel_anchor_PJ_y": _fmt(unit_total_anchor * MWH_TO_PJ),
                        "total_fuel_anchor_PJ_y": _fmt(reported_total_anchor * MWH_TO_PJ),
                        "total_fuel_allocated_PJ_y": _fmt(unit_total_allocated * MWH_TO_PJ),
                        "total_fuel_gap_unserved_PJ_y": _fmt(unit_total_gap * MWH_TO_PJ),
                        "allowed_fuels": ";".join(GENERATOR_UNITS[unit]["allowed_fuels"]),
                        "generic_WAG_carrier_active": "false",
                        "market_revenue_active": "false",
                        "price_responsive_dispatch_active": "false",
                        "mFRR_enabled_base": "false",
                        "status": "pass_with_gap" if unit_total_gap > TOL else "pass",
                    }
                )
            if config == C0:
                c0_total_allocated = sum(c0_interface[carrier]["allocated"] for carrier in FUELS)
                c0_unit_gap = sum(c0_interface[carrier]["gap"] for carrier in FUELS)
                fuel_rows.append(
                    {
                        "stage_id": STAGE,
                        "configuration": config,
                        "horizon_hours": horizon,
                        "unit_id": C0_GENERATOR_INTERFACE_UNIT,
                        "enabled_base": "true",
                        "dispatch_mode": GENERATOR_DISPATCH_MODE,
                        "annual_anchor_not_hourly_dispatch_constraint": "true",
                        "BFG_anchor_MWh_LHV_y": _fmt(c0_interface["BFG"]["anchor"]),
                        "BOFG_anchor_MWh_LHV_y": _fmt(c0_interface["BOFG"]["anchor"]),
                        "COG_anchor_MWh_LHV_y": _fmt(c0_interface["COG"]["anchor"]),
                        "NG_anchor_MWh_LHV_y": _fmt(0.0),
                        "BFG_MWh_LHV_y": _fmt(c0_interface["BFG"]["allocated"]),
                        "BOFG_MWh_LHV_y": _fmt(c0_interface["BOFG"]["allocated"]),
                        "COG_MWh_LHV_y": _fmt(c0_interface["COG"]["allocated"]),
                        "NG_MWh_LHV_y": _fmt(0.0),
                        "BFG_gap_unserved_MWh_LHV_y": _fmt(c0_interface["BFG"]["gap"]),
                        "BOFG_gap_unserved_MWh_LHV_y": _fmt(c0_interface["BOFG"]["gap"]),
                        "COG_gap_unserved_MWh_LHV_y": _fmt(c0_interface["COG"]["gap"]),
                        "NG_gap_unserved_MWh_LHV_y": _fmt(0.0),
                        "carrier_sum_fuel_anchor_MWh_LHV_y": _fmt(0.0),
                        "total_fuel_anchor_MWh_LHV_y": _fmt(0.0),
                        "total_fuel_allocated_MWh_LHV_y": _fmt(c0_total_allocated),
                        "total_fuel_gap_unserved_MWh_LHV_y": _fmt(c0_unit_gap),
                        "carrier_sum_fuel_anchor_PJ_y": _fmt(0.0),
                        "total_fuel_anchor_PJ_y": _fmt(0.0),
                        "total_fuel_allocated_PJ_y": _fmt(c0_total_allocated * MWH_TO_PJ),
                        "total_fuel_gap_unserved_PJ_y": _fmt(c0_unit_gap * MWH_TO_PJ),
                        "allowed_fuels": "BFG;BOFG;COG",
                        "generic_WAG_carrier_active": "false",
                        "market_revenue_active": "false",
                        "price_responsive_dispatch_active": "false",
                        "mFRR_enabled_base": "false",
                        "status": "pass_with_gap" if c0_unit_gap > TOL else "pass",
                        "carrier_split_status": c0_carrier_split_status,
                        "electricity_validation_anchor_MWh_e_y": _fmt(c0_validation_anchor_electricity),
                        "electricity_actual_MWh_e_y": _fmt(c0_actual_electricity),
                        "electric_efficiency_dev": _fmt(C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV),
                        "caveat": "C0 aggregate generator interface routes governed residual BFG/BOFG/COG using a proportional residual-carrier split proxy; no public VN25/IJ01 C0 split is claimed.",
                    }
                )

            flare_anchor = C1_FLARE_ANCHOR_PJ * PJ_TO_MWH if config == C1 else 0.0
            residual_wag_before_flare = sum(available[carrier] for carrier in WAG_FUELS)
            flare = min(residual_wag_before_flare, flare_anchor)
            generator_gap = (
                c0_total_gap
                if config == C0
                else sum(
                    allocations[unit][carrier]["gap"]
                    for unit in GENERATOR_ORDER
                    for carrier in FUELS
                )
            )
            residual_rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "available_BFG_after_steam_MWh_LHV_y": _fmt(start_available["BFG"]),
                    "available_BOFG_after_steam_MWh_LHV_y": _fmt(start_available["BOFG"]),
                    "available_COG_after_steam_MWh_LHV_y": _fmt(start_available["COG"]),
                    "BFG_to_generators_MWh_LHV_y": _fmt(start_available["BFG"] - available["BFG"]),
                    "BOFG_to_generators_MWh_LHV_y": _fmt(start_available["BOFG"] - available["BOFG"]),
                    "COG_to_generators_MWh_LHV_y": _fmt(start_available["COG"] - available["COG"]),
                    "NG_to_generators_MWh_LHV_y": _fmt(available["NG"]),
                    "WAG_to_generators_MWh_LHV_y": _fmt(
                        start_available["BFG"] - available["BFG"]
                        + start_available["BOFG"] - available["BOFG"]
                        + start_available["COG"] - available["COG"]
                    ),
                    "generator_fuel_gap_unserved_MWh_LHV_y": _fmt(generator_gap),
                    "generator_flare_anchor_MWh_LHV_y": _fmt(flare_anchor),
                    "generator_flare_or_spill_MWh_LHV_y": _fmt(flare),
                    "C0_generator_electricity_validation_anchor_MWh_e_y": _fmt(c0_validation_anchor_electricity),
                    "C0_generator_electricity_actual_MWh_e_y": _fmt(c0_actual_electricity),
                    "C0_generator_electric_efficiency_dev": _fmt(C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV if config == C0 else 0.0),
                    "C0_generator_available_fuel_MWh_LHV_y": _fmt(c0_available_generator_fuel),
                    "C0_generator_carrier_split_status": c0_carrier_split_status,
                    "residual_BFG_after_generators_MWh_LHV_y": _fmt(available["BFG"]),
                    "residual_BOFG_after_generators_MWh_LHV_y": _fmt(available["BOFG"]),
                    "residual_COG_after_generators_MWh_LHV_y": _fmt(available["COG"]),
                    "residual_WAG_after_generators_before_flare_MWh_LHV_y": _fmt(residual_wag_before_flare),
                    "residual_WAG_after_generators_and_flare_MWh_LHV_y": _fmt(max(residual_wag_before_flare - flare, 0.0)),
                    "residual_WAG_after_generators_and_flare_PJ_y": _fmt(max(residual_wag_before_flare - flare, 0.0) * MWH_TO_PJ),
                    "WAG_direct_market_value_active": "false",
                    "WAG_export_revenue_active": "false",
                    "generic_WAG_carrier_active": "false",
                    "status": "residual_visible_reporting_only",
                    "caveat": "Residual WAG is not direct market value; C1 gaps reflect annual anchor fuel exceeding governed residual carrier availability.",
                }
            )
    return fuel_rows, residual_rows


def _electricity_rows(
    payload: dict[str, Any],
    fuel_rows: list[dict[str, Any]],
    residual_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fuel_by_key = {(row["configuration"], int(row["horizon_hours"]), row["unit_id"]): row for row in fuel_rows}
    residual_by_key = _by_key(residual_rows)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            prior = payload["steam_totals"][key]
            vn25_fuel = _zero(fuel_by_key[(config, horizon, "VN25")]["total_fuel_allocated_MWh_LHV_y"])
            ij01_fuel = _zero(fuel_by_key[(config, horizon, "IJ01")]["total_fuel_allocated_MWh_LHV_y"])
            c0_fuel = (
                _zero(fuel_by_key[(config, horizon, C0_GENERATOR_INTERFACE_UNIT)]["total_fuel_allocated_MWh_LHV_y"])
                if config == C0
                else 0.0
            )
            c0_electricity = c0_fuel * C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV
            vn25_electricity = vn25_fuel * GENERATOR_UNITS["VN25"]["electric_efficiency_dev"]
            ij01_electricity = 0.0
            total_electricity = c0_electricity + vn25_electricity + ij01_electricity
            process_before = _zero(prior["process_electricity_after_boiler_steam_MWh_e_y"])
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "VN25_fuel_for_electricity_MWh_LHV_y": _fmt(vn25_fuel),
                    "VN25_electric_efficiency_dev": GENERATOR_UNITS["VN25"]["electric_efficiency_dev"],
                    "VN25_electricity_offset_MWh_e_y": _fmt(vn25_electricity),
                    "VN25_average_electricity_MW_e": _fmt(vn25_electricity / HOURS_PER_YEAR),
                    "VN25_capacity_context_MW_dev": GENERATOR_UNITS["VN25"]["capacity_mw_dev"],
                    "VN25_capacity_context_status": "ATHANASIADIS_CAPACITY_PRECEDENT_ONLY",
                    "VN25_capacity_exceeded_dev_context": _bool(
                        vn25_electricity / HOURS_PER_YEAR > GENERATOR_UNITS["VN25"]["capacity_mw_dev"] + TOL
                    ),
                    "IJ01_fuel_for_electricity_MWh_LHV_y": _fmt(ij01_fuel),
                    "IJ01_electricity_offset_MWh_e_y": _fmt(ij01_electricity),
                    "IJ01_electricity_conversion_status": "IJ01_ELECTRICITY_CONVERSION_DEFERRED",
                    "IJ01_steam_or_heat_output_status": "IJ01_CHP_STEAM_OUTPUT_DEFERRED",
                    "C0_generator_interface_unit": C0_GENERATOR_INTERFACE_UNIT if config == C0 else "",
                    "C0_generator_fuel_for_electricity_MWh_LHV_y": _fmt(c0_fuel),
                    "C0_generator_electricity_validation_anchor_MWh_e_y": _fmt(C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y if config == C0 else 0.0),
                    "C0_generator_electricity_actual_MWh_e_y": _fmt(c0_electricity),
                    "C0_generator_electricity_validation_anchor_TWh_e_y": _fmt(C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y / 1_000_000.0 if config == C0 else 0.0),
                    "C0_generator_electricity_actual_TWh_e_y": _fmt(c0_electricity / 1_000_000.0),
                    "C0_generator_electricity_gap_to_validation_anchor_TWh_e_y": _fmt(
                        (c0_electricity - (C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y if config == C0 else 0.0))
                        / 1_000_000.0
                    ),
                    "C0_generator_electric_efficiency_dev": _fmt(C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV if config == C0 else 0.0),
                    "C0_generator_status": C0_GENERATOR_INTERFACE_STATUS if config == C0 else "",
                    "total_generator_electricity_offset_MWh_e_y": _fmt(total_electricity),
                    "steam_circuit_electricity_MWh_e_y": payload["steam_electricity"][key]["total_steam_circuit_electricity_output_MWh_e_y"],
                    "process_electricity_before_generator_offset_MWh_e_y": _fmt(process_before),
                    "process_electricity_after_generator_offset_reporting_only_MWh_e_y": _fmt(max(process_before - total_electricity, 0.0)),
                    "generator_electricity_value_mode": GENERATOR_ELECTRICITY_VALUE_MODE,
                    "electricity_accounting_status": ELECTRICITY_ACCOUNTING_STATUS,
                    "full_site_net_electricity_claimed": "false",
                    "DA_market_revenue_active": "false",
                    "export_revenue_active": "false",
                    "price_responsive_dispatch_active": "false",
                    "mFRR_enabled_base": "false",
                    "residual_WAG_after_generators_and_flare_MWh_LHV_y": residual_by_key[key]["residual_WAG_after_generators_and_flare_MWh_LHV_y"],
                }
            )
    return rows


def _anchor_rows(
    fuel_rows: list[dict[str, Any]],
    residual_rows: list[dict[str, Any]],
    electricity_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fuel_by_key = {(row["configuration"], int(row["horizon_hours"]), row["unit_id"]): row for row in fuel_rows}
    residual_by_key = _by_key(residual_rows)
    electricity_by_key = _by_key(electricity_rows)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            for unit in GENERATOR_ORDER:
                fuel = fuel_by_key[(config, horizon, unit)]
                for carrier in FUELS:
                    anchor = _zero(fuel[f"{carrier}_anchor_MWh_LHV_y"])
                    model = _zero(fuel[f"{carrier}_MWh_LHV_y"])
                    rows.append(
                        {
                            "stage_id": STAGE,
                            "configuration": config,
                            "horizon_hours": horizon,
                            "anchor_id": f"{unit}_{carrier}_fuel",
                            "unit_id": unit,
                            "carrier": carrier,
                            "anchor_value_PJ_y": _fmt(anchor * MWH_TO_PJ),
                            "model_value_PJ_y": _fmt(model * MWH_TO_PJ),
                            "gap_PJ_y": _fmt((model - anchor) * MWH_TO_PJ),
                            "anchor_status": "C1_preferred_validation_anchor_not_hourly_dispatch" if config == C1 else "C0_context_no_active_dispatch_anchor",
                            "active_base": _bool(config == C1),
                            "caveat": "Annual validation anchor; not hourly schedule or price-responsive dispatch.",
                        }
                    )
                rows.append(
                    {
                        "stage_id": STAGE,
                        "configuration": config,
                        "horizon_hours": horizon,
                        "anchor_id": f"{unit}_total_fuel",
                        "unit_id": unit,
                        "carrier": "total",
                        "anchor_value_PJ_y": fuel["total_fuel_anchor_PJ_y"],
                        "model_value_PJ_y": fuel["total_fuel_allocated_PJ_y"],
                        "gap_PJ_y": _fmt(_zero(fuel["total_fuel_allocated_PJ_y"]) - _zero(fuel["total_fuel_anchor_PJ_y"])),
                        "anchor_status": "C1_preferred_validation_anchor_not_hourly_dispatch" if config == C1 else "C0_context_no_active_dispatch_anchor",
                        "active_base": _bool(config == C1),
                        "caveat": "Fuel gap is reported where governed residual WAG is insufficient.",
                    }
                )
            if config == C0:
                c0_fuel = fuel_by_key[(config, horizon, C0_GENERATOR_INTERFACE_UNIT)]
                for carrier in WAG_FUELS:
                    anchor = _zero(c0_fuel[f"{carrier}_anchor_MWh_LHV_y"])
                    model = _zero(c0_fuel[f"{carrier}_MWh_LHV_y"])
                    rows.append(
                        {
                            "stage_id": STAGE,
                            "configuration": config,
                            "horizon_hours": horizon,
                            "anchor_id": f"{C0_GENERATOR_INTERFACE_UNIT}_{carrier}_fuel_proxy",
                            "unit_id": C0_GENERATOR_INTERFACE_UNIT,
                            "carrier": carrier,
                            "anchor_value_PJ_y": _fmt(anchor * MWH_TO_PJ),
                            "model_value_PJ_y": _fmt(model * MWH_TO_PJ),
                            "gap_PJ_y": _fmt((model - anchor) * MWH_TO_PJ),
                            "anchor_status": "C0_residual_wag_generator_interface_proxy_split",
                            "active_base": "true",
                            "caveat": "Carrier split is a transparent development proxy over residual BFG/BOFG/COG, not a public C0 VN25/IJ01 split.",
                        }
                    )
                rows.append(
                    {
                        "stage_id": STAGE,
                        "configuration": config,
                        "horizon_hours": horizon,
                        "anchor_id": "C0_generator_interface_total_fuel",
                        "unit_id": C0_GENERATOR_INTERFACE_UNIT,
                        "carrier": "BFG_BOFG_COG_proxy_split",
                        "anchor_value_PJ_y": c0_fuel["total_fuel_anchor_PJ_y"],
                        "model_value_PJ_y": c0_fuel["total_fuel_allocated_PJ_y"],
                        "gap_PJ_y": _fmt(_zero(c0_fuel["total_fuel_allocated_PJ_y"]) - _zero(c0_fuel["total_fuel_anchor_PJ_y"])),
                        "anchor_status": C0_GENERATOR_INTERFACE_STATUS,
                        "active_base": "true",
                        "caveat": "Fuel use is derived from governed residual WAG and development efficiency; the 2.0 TWh/y electricity value is validation-only.",
                    }
                )
            residual = residual_by_key[(config, horizon)]
            electricity = electricity_by_key[(config, horizon)]
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "anchor_id": "generator_flare",
                    "unit_id": "generator_interface",
                    "carrier": "WAG_flare_or_spill",
                    "anchor_value_PJ_y": _fmt(_zero(residual["generator_flare_anchor_MWh_LHV_y"]) * MWH_TO_PJ),
                    "model_value_PJ_y": _fmt(_zero(residual["generator_flare_or_spill_MWh_LHV_y"]) * MWH_TO_PJ),
                    "gap_PJ_y": _fmt((_zero(residual["generator_flare_or_spill_MWh_LHV_y"]) - _zero(residual["generator_flare_anchor_MWh_LHV_y"])) * MWH_TO_PJ),
                    "anchor_status": "C1_preferred_validation_anchor_not_hourly_dispatch" if config == C1 else "C0_context_no_active_dispatch_anchor",
                    "active_base": _bool(config == C1),
                    "caveat": "Flare/spill remains reporting-only and has no direct market value.",
                }
            )
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "anchor_id": "generator_total_with_flare",
                    "unit_id": "generator_interface",
                    "carrier": "total_plus_flare",
                    "anchor_value_PJ_y": _fmt(C1_GENERATOR_TOTAL_WITH_FLARE_ANCHOR_PJ if config == C1 else 0.0),
                    "model_value_PJ_y": _fmt(
                        (
                            (
                                _zero(fuel_by_key[(config, horizon, C0_GENERATOR_INTERFACE_UNIT)]["total_fuel_allocated_MWh_LHV_y"])
                                if config == C0
                                else 0.0
                            )
                            +
                            sum(_zero(fuel_by_key[(config, horizon, unit)]["total_fuel_allocated_MWh_LHV_y"]) for unit in GENERATOR_ORDER)
                            + _zero(residual["generator_flare_or_spill_MWh_LHV_y"])
                        )
                        * MWH_TO_PJ
                    ),
                    "gap_PJ_y": _fmt(
                        (
                            (
                                _zero(fuel_by_key[(config, horizon, C0_GENERATOR_INTERFACE_UNIT)]["total_fuel_allocated_MWh_LHV_y"])
                                if config == C0
                                else 0.0
                            )
                            +
                            sum(_zero(fuel_by_key[(config, horizon, unit)]["total_fuel_allocated_MWh_LHV_y"]) for unit in GENERATOR_ORDER)
                            + _zero(residual["generator_flare_or_spill_MWh_LHV_y"])
                        )
                        * MWH_TO_PJ
                        - (C1_GENERATOR_TOTAL_WITH_FLARE_ANCHOR_PJ if config == C1 else 0.0)
                    ),
                    "anchor_status": "C1_preferred_validation_anchor_not_hourly_dispatch" if config == C1 else "C0_context_no_active_dispatch_anchor",
                    "active_base": _bool(config == C1),
                    "caveat": "Total is validation comparison only.",
                }
            )
            if config == C0:
                for anchor_id, value in C0_CONTEXT_ANCHORS.items():
                    model_value = ""
                    unit = "PJ/y" if "PJ" in anchor_id else ("TWh/y" if "TWH" in anchor_id else "MW")
                    if anchor_id == "CURRENT_VATTENFALL_RESIDUAL_GAS_ELECTRICITY_TWH_Y":
                        model_value = _fmt(_zero(electricity["total_generator_electricity_offset_MWh_e_y"]) / 1_000_000.0)
                    rows.append(
                        {
                            "stage_id": STAGE,
                            "configuration": config,
                            "horizon_hours": horizon,
                            "anchor_id": anchor_id,
                            "unit_id": "C0_context",
                            "carrier": "context",
                            "anchor_value_PJ_y": _fmt(value) if unit == "PJ/y" else "",
                            "model_value_PJ_y": "",
                            "gap_PJ_y": "",
                            "anchor_status": "C0_context_validation_only_not_dispatch_constraint",
                            "active_base": "false",
                            "context_anchor_value": _fmt(value),
                            "context_model_value": model_value,
                            "context_unit": unit,
                            "caveat": "C0 generator context only; no exact current generator dispatch is forced.",
                        }
                    )
            else:
                for parameter_id, value in C1_IJ01_BASE_VARIANT.items():
                    rows.append(
                        {
                            "stage_id": STAGE,
                            "configuration": config,
                            "horizon_hours": horizon,
                            "anchor_id": parameter_id,
                            "unit_id": "sensitivity_deferred",
                            "carrier": "sensitivity",
                            "anchor_value_PJ_y": _fmt(value) if "FUEL" in parameter_id else "",
                            "model_value_PJ_y": "",
                            "gap_PJ_y": "",
                            "anchor_status": "sensitivity_anchor_deferred_not_active_base",
                            "active_base": "false",
                            "context_anchor_value": _fmt(value),
                            "context_model_value": "",
                            "context_unit": "PJ/y" if "FUEL" in parameter_id else "h/y",
                            "caveat": "IJ01-as-base variant is recorded only as sensitivity/deferred.",
                        }
                    )
    return rows


def _modelled_totals_delta_rows(
    payload: dict[str, Any],
    residual_rows: list[dict[str, Any]],
    electricity_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    residual_by_key = _by_key(residual_rows)
    electricity_by_key = _by_key(electricity_rows)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            prior = payload["steam_totals"][key]
            residual = residual_by_key[key]
            electricity = electricity_by_key[key]
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only_generator_interface_accounting",
                    "thesis_usability": "false",
                    "process_electricity_after_boiler_steam_MWh_e_y": prior["process_electricity_after_boiler_steam_MWh_e_y"],
                    "generator_electricity_offset_MWh_e_y": electricity["total_generator_electricity_offset_MWh_e_y"],
                    "process_electricity_after_generator_offset_reporting_only_MWh_e_y": electricity["process_electricity_after_generator_offset_reporting_only_MWh_e_y"],
                    "electricity_accounting_status": ELECTRICITY_ACCOUNTING_STATUS,
                    "full_site_net_electricity_claimed": "false",
                    "DA_market_revenue_active": "false",
                    "WAG_to_generators_MWh_LHV_y": residual["WAG_to_generators_MWh_LHV_y"],
                    "NG_to_generators_MWh_LHV_y": residual["NG_to_generators_MWh_LHV_y"],
                    "generator_fuel_gap_unserved_MWh_LHV_y": residual["generator_fuel_gap_unserved_MWh_LHV_y"],
                    "generator_flare_or_spill_MWh_LHV_y": residual["generator_flare_or_spill_MWh_LHV_y"],
                    "residual_WAG_after_generators_and_flare_MWh_LHV_y": residual["residual_WAG_after_generators_and_flare_MWh_LHV_y"],
                    "CO2_status_after_generators": "deferred_fuel_explicit_later_avoid_WAG_double_count",
                    "HSM_heat_case": "base_0_50",
                    "coke_reconciliation_baseline_status": "C5m_f_bounded_coke_reconciliation_active_development_baseline",
                    "external_unmodelled_coke_status": "fallback_only_not_active_baseline",
                    "denominator_status": DENOMINATOR_STATUS,
                }
            )
    return rows


def _plant_kpi_rows(
    fuel_rows: list[dict[str, Any]],
    residual_rows: list[dict[str, Any]],
    electricity_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fuel_by_key = {(row["configuration"], int(row["horizon_hours"]), row["unit_id"]): row for row in fuel_rows}
    residual_by_key = _by_key(residual_rows)
    electricity_by_key = _by_key(electricity_rows)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            vn25 = fuel_by_key[(config, horizon, "VN25")]
            ij01 = fuel_by_key[(config, horizon, "IJ01")]
            c0_interface = fuel_by_key.get((config, horizon, C0_GENERATOR_INTERFACE_UNIT), {})
            residual = residual_by_key[key]
            electricity = electricity_by_key[key]
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "plant_group": "IJ01_VN25_generator_interface",
                    "generator_layer_status": "active_C1_preferred_anchor_interface" if config == C1 else C0_GENERATOR_INTERFACE_STATUS,
                    "VN25_enabled_base": "true",
                    "IJ01_enabled_base": "true",
                    "VN24_enabled_base": "false",
                    "generator_dispatch_mode": GENERATOR_DISPATCH_MODE,
                    "generator_electricity_value_mode": GENERATOR_ELECTRICITY_VALUE_MODE,
                    "VN25_total_fuel_PJ_y": vn25["total_fuel_allocated_PJ_y"],
                    "IJ01_total_fuel_PJ_y": ij01["total_fuel_allocated_PJ_y"],
                    "C0_generator_interface_unit": C0_GENERATOR_INTERFACE_UNIT if config == C0 else "",
                    "C0_generator_total_fuel_PJ_y": c0_interface.get("total_fuel_allocated_PJ_y", ""),
                    "C0_generator_electricity_TWh_e_y": electricity["C0_generator_electricity_actual_TWh_e_y"],
                    "C0_generator_carrier_split_status": c0_interface.get("carrier_split_status", ""),
                    "generator_fuel_gap_PJ_y": _fmt(_zero(residual["generator_fuel_gap_unserved_MWh_LHV_y"]) * MWH_TO_PJ),
                    "generator_flare_or_spill_PJ_y": _fmt(_zero(residual["generator_flare_or_spill_MWh_LHV_y"]) * MWH_TO_PJ),
                    "total_generator_electricity_offset_MWh_e_y": electricity["total_generator_electricity_offset_MWh_e_y"],
                    "residual_WAG_after_generators_and_flare_PJ_y": residual["residual_WAG_after_generators_and_flare_PJ_y"],
                    "electricity_accounting_status": ELECTRICITY_ACCOUNTING_STATUS,
                    "export_revenue_active": "false",
                    "price_responsive_dispatch_active": "false",
                    "mFRR_enabled_base": "false",
                }
            )
    return rows


def _health_rows(
    payload: dict[str, Any],
    fuel_rows: list[dict[str, Any]],
    residual_rows: list[dict[str, Any]],
    electricity_rows: list[dict[str, Any]],
    totals_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fuel_by_key = {(row["configuration"], int(row["horizon_hours"]), row["unit_id"]): row for row in fuel_rows}
    residual_by_key = _by_key(residual_rows)
    electricity_by_key = _by_key(electricity_rows)
    totals_by_key = _by_key(totals_rows)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            vn25 = fuel_by_key[(config, horizon, "VN25")]
            ij01 = fuel_by_key[(config, horizon, "IJ01")]
            c0_interface = fuel_by_key.get((config, horizon, C0_GENERATOR_INTERFACE_UNIT), {})
            residual = residual_by_key[key]
            electricity = electricity_by_key[key]
            totals = totals_by_key[key]
            steam_health = payload["steam_health"][key]
            consumed_wag = _zero(residual["WAG_to_generators_MWh_LHV_y"])
            available_wag = (
                _zero(residual["available_BFG_after_steam_MWh_LHV_y"])
                + _zero(residual["available_BOFG_after_steam_MWh_LHV_y"])
                + _zero(residual["available_COG_after_steam_MWh_LHV_y"])
            )
            c0_active = config == C0
            c0_status = C0_GENERATOR_INTERFACE_STATUS if c0_active else ""
            c0_actual_electricity = _zero(electricity["C0_generator_electricity_actual_MWh_e_y"])
            c0_fuel = _zero(c0_interface.get("total_fuel_allocated_MWh_LHV_y", 0.0))
            c0_anchor = C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y if c0_active else 0.0
            c0_backcalculated_fuel = (
                C0_GENERATOR_ELECTRICITY_VALIDATION_ANCHOR_MWH_E_Y / C0_GENERATOR_ELECTRIC_EFFICIENCY_DEV
                if c0_active
                else 0.0
            )
            flags = {
                "C0_GENERATORS_REPORTED_AS_PHYSICALLY_INACTIVE": c0_active and c0_status != C0_GENERATOR_INTERFACE_STATUS,
                "C0_GENERATOR_FUEL_ZERO_WHILE_RESIDUAL_WAG_AVAILABLE": c0_active and available_wag > TOL and c0_fuel <= TOL,
                "C0_GENERATOR_USES_GENERIC_WAG_WITHOUT_CARRIER_SPLIT": False,
                "C0_GENERATOR_CONSUMES_MORE_WAG_THAN_AVAILABLE": c0_active and consumed_wag > available_wag + TOL,
                "C0_GENERATOR_ELECTRICITY_TARGET_ENFORCED_TO_2TWH": c0_active
                and abs(c0_actual_electricity - c0_anchor) <= TOL
                and abs(c0_fuel - available_wag) > TOL,
                "C0_GENERATOR_ELECTRICITY_ANCHOR_USED_AS_EQUALITY_CONSTRAINT": c0_active
                and abs(c0_actual_electricity - c0_anchor) <= TOL
                and abs(c0_fuel - available_wag) > TOL,
                "C0_GENERATOR_FUEL_BACKCALCULATED_FROM_2TWH_ANCHOR": c0_active
                and abs(c0_fuel - c0_backcalculated_fuel) <= TOL
                and abs(c0_fuel - available_wag) > TOL,
                "C0_GENERATOR_ELECTRICITY_TARGET_MET_WITHOUT_FUEL": c0_active and c0_actual_electricity > TOL and c0_fuel <= TOL,
                "C0_GENERATOR_ELECTRICITY_COUNTED_AS_DA_REVENUE": False,
                "C0_GENERATOR_ELECTRICITY_COUNTED_AS_EXPORT_REVENUE": False,
                "C0_FULL_SITE_NET_IMPORT_CLAIMED_WITHOUT_BOUNDARY": False,
                "C0_770MW_USED_AS_UNIT_CAPACITY": False,
                "C0_360MW_AVG_POWER_USED_AS_CONNECTION_CAPACITY": False,
                "C0_54PJ_PRODUCT_GAS_REUSE_USED_AS_EXACT_GENERATOR_FUEL_WITHOUT_INTERPRETATION": False,
                "GENERATOR_EXPORT_REVENUE_ACTIVE": False,
                "GENERATOR_PRICE_RESPONSIVE_DISPATCH_ACTIVE": False,
                "GENERATOR_MFRR_ENABLED_IN_BASE": False,
                "WAG_DIRECT_MARKET_VALUE_ACTIVE": False,
                "GENERIC_WAG_TO_GENERATORS_ACTIVE": False,
                "BFG_COG_BOFG_COLLAPSED_WITHOUT_EXPLICIT_MIXING": False,
                "VN24_ACTIVE_IN_BASE": GENERATOR_UNITS["VN24"]["enabled_base"],
                "IJ01_NG_USED_IN_BASE": _zero(ij01["NG_MWh_LHV_y"]) > TOL,
                "GENERATOR_CONSUMES_UNLIMITED_WAG": consumed_wag > available_wag + TOL,
                "GENERATOR_OUTPUT_COUNTED_AS_DA_REVENUE": False,
                "GENERATOR_OUTPUT_COUNTED_AS_FINAL_FULL_SITE_NET_IMPORT_WITHOUT_BOUNDARY": False,
                "VN25_OR_IJ01_USES_770MW_AS_UNIT_CAPACITY": False,
                "ATHANASIADIS_350MW_TREATED_AS_PUBLIC_TATA_CAPACITY": False,
                "TABLE_5_5_USED_AS_HOURLY_DISPATCH_SCHEDULE": False,
                "FORECAST_COMPARISON_WITH_CHANGED_GENERATOR_POLICY": False,
                "BOILER_STEAM_LAYER_CHANGED_UNEXPECTEDLY": False,
                "HSM_BASE_0_50_REVERTED": totals["HSM_heat_case"] != "base_0_50",
                "COKE_RECONCILIATION_BASELINE_REOPENED": totals["coke_reconciliation_baseline_status"]
                != "C5m_f_bounded_coke_reconciliation_active_development_baseline",
                "DENOMINATOR_SILENTLY_FROZEN": totals["denominator_status"] != DENOMINATOR_STATUS,
            }
            caveats = {name: True for name in CAVEAT_NAMES}
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "generator_layer_status": "active_C1_preferred_anchor_interface" if config == C1 else c0_status,
                    "generator_dispatch_mode": GENERATOR_DISPATCH_MODE,
                    "generator_electricity_value_mode": GENERATOR_ELECTRICITY_VALUE_MODE,
                    "export_revenue_enabled_base": "false",
                    "price_responsive_dispatch_base": "false",
                    "mFRR_enabled_base": "false",
                    "VN25_enabled_base": "true",
                    "IJ01_enabled_base": "true",
                    "VN24_enabled_base": "false",
                    "VN24_status": "cold_backup_reserve_only_inactive_base",
                    "VN25_BFG_MWh_LHV_y": vn25["BFG_MWh_LHV_y"],
                    "VN25_BOFG_MWh_LHV_y": vn25["BOFG_MWh_LHV_y"],
                    "VN25_COG_MWh_LHV_y": vn25["COG_MWh_LHV_y"],
                    "VN25_NG_MWh_LHV_y": vn25["NG_MWh_LHV_y"],
                    "VN25_total_fuel_PJ_y": vn25["total_fuel_allocated_PJ_y"],
                    "VN25_total_fuel_anchor_PJ_y": vn25["total_fuel_anchor_PJ_y"],
                    "IJ01_BFG_MWh_LHV_y": ij01["BFG_MWh_LHV_y"],
                    "IJ01_BOFG_MWh_LHV_y": ij01["BOFG_MWh_LHV_y"],
                    "IJ01_COG_MWh_LHV_y": ij01["COG_MWh_LHV_y"],
                    "IJ01_NG_MWh_LHV_y": ij01["NG_MWh_LHV_y"],
                    "IJ01_total_fuel_PJ_y": ij01["total_fuel_allocated_PJ_y"],
                    "IJ01_total_fuel_anchor_PJ_y": ij01["total_fuel_anchor_PJ_y"],
                    "C0_generator_interface_unit": C0_GENERATOR_INTERFACE_UNIT if config == C0 else "",
                    "C0_generator_BFG_MWh_LHV_y": c0_interface.get("BFG_MWh_LHV_y", ""),
                    "C0_generator_BOFG_MWh_LHV_y": c0_interface.get("BOFG_MWh_LHV_y", ""),
                    "C0_generator_COG_MWh_LHV_y": c0_interface.get("COG_MWh_LHV_y", ""),
                    "C0_generator_NG_MWh_LHV_y": c0_interface.get("NG_MWh_LHV_y", ""),
                    "C0_generator_total_fuel_PJ_y": c0_interface.get("total_fuel_allocated_PJ_y", ""),
                    "C0_generator_total_fuel_anchor_PJ_y": c0_interface.get("total_fuel_anchor_PJ_y", ""),
                    "C0_generator_carrier_split_status": c0_interface.get("carrier_split_status", ""),
                    "C0_generator_electric_efficiency_dev": electricity["C0_generator_electric_efficiency_dev"],
                    "C0_generator_electricity_validation_anchor_TWh_e_y": electricity["C0_generator_electricity_validation_anchor_TWh_e_y"],
                    "C0_generator_electricity_actual_TWh_e_y": electricity["C0_generator_electricity_actual_TWh_e_y"],
                    "C0_generator_electricity_gap_to_validation_anchor_TWh_e_y": electricity["C0_generator_electricity_gap_to_validation_anchor_TWh_e_y"],
                    "generator_fuel_gap_unserved_PJ_y": _fmt(_zero(residual["generator_fuel_gap_unserved_MWh_LHV_y"]) * MWH_TO_PJ),
                    "generator_flare_or_spill_PJ_y": _fmt(_zero(residual["generator_flare_or_spill_MWh_LHV_y"]) * MWH_TO_PJ),
                    "generator_total_with_flare_anchor_PJ_y": _fmt(C1_GENERATOR_TOTAL_WITH_FLARE_ANCHOR_PJ if config == C1 else 0.0),
                    "generator_total_with_flare_model_PJ_y": _fmt(
                        (
                            c0_fuel
                            +
                            _zero(vn25["total_fuel_allocated_MWh_LHV_y"])
                            + _zero(ij01["total_fuel_allocated_MWh_LHV_y"])
                            + _zero(residual["generator_flare_or_spill_MWh_LHV_y"])
                        )
                        * MWH_TO_PJ
                    ),
                    "residual_WAG_after_steam_PJ_y": _fmt(available_wag * MWH_TO_PJ),
                    "WAG_to_generators_PJ_y": _fmt(consumed_wag * MWH_TO_PJ),
                    "residual_WAG_after_generators_and_flare_PJ_y": residual["residual_WAG_after_generators_and_flare_PJ_y"],
                    "VN25_electricity_offset_MWh_e_y": electricity["VN25_electricity_offset_MWh_e_y"],
                    "IJ01_electricity_offset_MWh_e_y": electricity["IJ01_electricity_offset_MWh_e_y"],
                    "IJ01_electricity_conversion_status": electricity["IJ01_electricity_conversion_status"],
                    "total_generator_electricity_offset_MWh_e_y": electricity["total_generator_electricity_offset_MWh_e_y"],
                    "steam_circuit_electricity_MWh_e_y": electricity["steam_circuit_electricity_MWh_e_y"],
                    "process_electricity_before_generator_offset_MWh_e_y": electricity["process_electricity_before_generator_offset_MWh_e_y"],
                    "process_electricity_after_generator_offset_reporting_only_MWh_e_y": electricity["process_electricity_after_generator_offset_reporting_only_MWh_e_y"],
                    "full_site_net_electricity_claimed": "false",
                    "DA_market_revenue_active": "false",
                    "C0_product_gas_reuse_context_PJ_y": _fmt(C0_CONTEXT_ANCHORS["CURRENT_PRODUCT_GAS_REUSE_ANNUAL_PJ_Y"]) if config == C0 else "",
                    "C0_vattenfall_electricity_context_TWh_y": _fmt(C0_CONTEXT_ANCHORS["CURRENT_VATTENFALL_RESIDUAL_GAS_ELECTRICITY_TWH_Y"]) if config == C0 else "",
                    "C0_tata_average_power_context_MW": _fmt(C0_CONTEXT_ANCHORS["CURRENT_TATA_AVG_ELECTRIC_POWER_MW"]) if config == C0 else "",
                    "steam_layer_failure_count": steam_health["failure_count"],
                    "coke_reconciliation_baseline_status": totals["coke_reconciliation_baseline_status"],
                    "external_unmodelled_coke_status": totals["external_unmodelled_coke_status"],
                    "HSM_heat_case": totals["HSM_heat_case"],
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
            "generator_layer_status": row["generator_layer_status"],
            "VN25_fuel_PJ_y": row["VN25_total_fuel_PJ_y"],
            "IJ01_fuel_PJ_y": row["IJ01_total_fuel_PJ_y"],
            "C0_generator_fuel_PJ_y": row["C0_generator_total_fuel_PJ_y"],
            "C0_generator_electricity_TWh_e_y": row["C0_generator_electricity_actual_TWh_e_y"],
            "C0_generator_electricity_validation_anchor_TWh_e_y": row["C0_generator_electricity_validation_anchor_TWh_e_y"],
            "C0_generator_electricity_gap_to_validation_anchor_TWh_e_y": row["C0_generator_electricity_gap_to_validation_anchor_TWh_e_y"],
            "fuel_gap_PJ_y": row["generator_fuel_gap_unserved_PJ_y"],
            "flare_spill_PJ_y": row["generator_flare_or_spill_PJ_y"],
            "VN25_electricity_GWh_e_y": _fmt(_zero(row["VN25_electricity_offset_MWh_e_y"]) / 1000.0),
            "IJ01_electricity_GWh_e_y": _fmt(_zero(row["IJ01_electricity_offset_MWh_e_y"]) / 1000.0),
            "total_generator_electricity_GWh_e_y": _fmt(_zero(row["total_generator_electricity_offset_MWh_e_y"]) / 1000.0),
            "residual_WAG_after_generators_PJ_y": row["residual_WAG_after_generators_and_flare_PJ_y"],
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
        "decision": "pass_development_generator_interface_accounting"
        if failure_count == 0
        else "fail_development_generator_interface_accounting",
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "output_directory": _rel(C5P_C_DIR),
        "failure_count": failure_count,
        "generator_dispatch_mode": GENERATOR_DISPATCH_MODE,
        "generator_electricity_value_mode": GENERATOR_ELECTRICITY_VALUE_MODE,
        "generator_export_revenue_enabled_base": GENERATOR_EXPORT_REVENUE_ENABLED_BASE,
        "generator_price_responsive_dispatch_base": GENERATOR_PRICE_RESPONSIVE_DISPATCH_BASE,
        "generator_mFRR_enabled_base": GENERATOR_MFRR_ENABLED_BASE,
        "VN25_enabled_base": True,
        "IJ01_enabled_base": True,
        "VN24_enabled_base": False,
        "VN24_status": "cold_backup_reserve_only_inactive_base",
        "electricity_accounting_status": ELECTRICITY_ACCOUNTING_STATUS,
        "full_site_net_electricity_claimed": False,
        "DA_market_revenue_active": False,
        "C0_24h_generator_layer_status": c0["generator_layer_status"],
        "C0_24h_generator_fuel_PJ_y": _zero(c0["C0_generator_total_fuel_PJ_y"]),
        "C0_24h_generator_electricity_validation_anchor_TWh_e_y": _zero(c0["C0_generator_electricity_validation_anchor_TWh_e_y"]),
        "C0_24h_generator_electricity_actual_TWh_e_y": _zero(c0["C0_generator_electricity_actual_TWh_e_y"]),
        "C0_24h_generator_electricity_gap_to_validation_anchor_TWh_e_y": _zero(c0["C0_generator_electricity_gap_to_validation_anchor_TWh_e_y"]),
        "C0_24h_generator_electric_efficiency_dev": _zero(c0["C0_generator_electric_efficiency_dev"]),
        "C0_24h_total_generator_electricity_offset_MWh_e_y": _zero(c0["total_generator_electricity_offset_MWh_e_y"]),
        "C0_24h_residual_WAG_after_generators_and_flare_PJ_y": _zero(c0["residual_WAG_after_generators_and_flare_PJ_y"]),
        "C1_24h_VN25_total_fuel_PJ_y": _zero(c1["VN25_total_fuel_PJ_y"]),
        "C1_24h_IJ01_total_fuel_PJ_y": _zero(c1["IJ01_total_fuel_PJ_y"]),
        "C1_24h_generator_fuel_gap_unserved_PJ_y": _zero(c1["generator_fuel_gap_unserved_PJ_y"]),
        "C1_24h_generator_flare_or_spill_PJ_y": _zero(c1["generator_flare_or_spill_PJ_y"]),
        "C1_24h_total_generator_electricity_offset_MWh_e_y": _zero(c1["total_generator_electricity_offset_MWh_e_y"]),
        "C1_24h_residual_WAG_after_generators_and_flare_PJ_y": _zero(c1["residual_WAG_after_generators_and_flare_PJ_y"]),
        "C1_preferred_VN25_total_fuel_anchor_PJ_y": 13.7,
        "C1_preferred_IJ01_total_fuel_anchor_PJ_y": 0.8,
        "C1_preferred_generator_flare_anchor_PJ_y": C1_FLARE_ANCHOR_PJ,
        "C1_preferred_generator_total_with_flare_anchor_PJ_y": C1_GENERATOR_TOTAL_WITH_FLARE_ANCHOR_PJ,
        "coke_reconciliation_baseline_status": "C5m_f_bounded_coke_reconciliation_active_development_baseline",
        "external_unmodelled_coke_status": "fallback_only_not_active_baseline",
        "denominator_status": DENOMINATOR_STATUS,
    }


def _write_outputs() -> dict[str, Any]:
    C5P_C_DIR.mkdir(parents=True, exist_ok=True)
    dev_rows = _generator_dev_rows()
    bus_rows = _generator_bus_rows()
    eligibility = _fuel_eligibility_rows()
    payload = _source_payload()
    fuel, residual = _fuel_allocation_rows(payload)
    electricity = _electricity_rows(payload, fuel, residual)
    anchors = _anchor_rows(fuel, residual, electricity)
    totals = _modelled_totals_delta_rows(payload, residual, electricity)
    kpis = _plant_kpi_rows(fuel, residual, electricity)
    health = _health_rows(payload, fuel, residual, electricity, totals)
    redflags = _redflag_rows(health)
    compact = _compact_table_rows(health)
    gate = _stage_gate(redflags, health)

    _write_csv(C5P_C_DIR / "s4_4c5p_c_generator_development_input_rows.csv", dev_rows)
    _write_csv(C5P_C_DIR / "s4_4c5p_c_generator_bus_rows.csv", bus_rows)
    _write_csv(C5P_C_DIR / "s4_4c5p_c_generator_fuel_eligibility_rows.csv", eligibility)
    _write_csv(C5P_C_DIR / "s4_4c5p_c_generator_anchor_comparison.csv", anchors)
    _write_csv(C5P_C_DIR / "s4_4c5p_c_generator_fuel_allocation.csv", fuel)
    _write_csv(C5P_C_DIR / "s4_4c5p_c_generator_electricity_ledger.csv", electricity)
    _write_csv(C5P_C_DIR / "s4_4c5p_c_wag_residual_after_generators.csv", residual)
    _write_csv(C5P_C_DIR / "s4_4c5p_c_modelled_totals_delta.csv", totals)
    _write_csv(C5P_C_DIR / "s4_4c5p_c_plant_kpi_table.csv", kpis)
    _write_csv(C5P_C_DIR / "s4_4c5p_c_compact_healthcheck.csv", health)
    _write_csv(C5P_C_DIR / "s4_4c5p_c_red_flags.csv", redflags)
    _write_csv(C5P_C_DIR / "s4_4c5p_c_compact_table_for_chat.csv", compact)
    _write_json(C5P_C_DIR / "s4_4c5p_c_stage_gate.json", gate)
    _write_csv(
        C5P_C_DIR / "s4_4c5p_c_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5p_b_boiler_steam_circuit_accounting",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_json(
        C5P_C_DIR / "s4_4c5p_c_generator_interface_report.json",
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
                "boiler_steam_outputs_changed": False,
                "generator_export_revenue_active": False,
                "generator_price_responsive_dispatch_active": False,
                "generator_mFRR_enabled": False,
                "denominator_frozen": False,
            },
            "sections": {
                "development_inputs": dev_rows,
                "generator_buses": bus_rows,
                "fuel_eligibility": eligibility,
                "anchor_comparison": anchors,
                "fuel_allocation": fuel,
                "electricity": electricity,
                "wag_residual_after_generators": residual,
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
            "generator_buses": len(bus_rows),
            "fuel_eligibility": len(eligibility),
            "anchor_comparison": len(anchors),
            "fuel_allocation": len(fuel),
            "electricity": len(electricity),
            "wag_residual": len(residual),
            "modelled_totals": len(totals),
            "health": len(health),
            "redflags": len(redflags),
        },
    }
    _write_json(C5P_C_DIR / "s4_4c5p_c_summary.json", summary)
    return summary


def run_s4_4c5p_c_ij01_vn25_generator_interface_accounting() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5p_c_ij01_vn25_generator_interface_accounting(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
