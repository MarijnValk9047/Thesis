"""S4.4c5m Sinter minimal parameterisation.

This stage adds a development-only Sinter Plant layer to the accepted C5
physical diagnostic chain. It is a per-timestep production-coupled accounting
link, not a standalone Sinter model and not an annual-only diagnostic.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    COG_LHV_MJ_PER_NM3,
    CONFIGS,
    HORIZONS,
    S4_ROOT,
    WAG_TOL_MWH,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5g_wag_aggregate_diagnostic_hygiene import WAG_CARRIERS
from .s4_4c5h_blast_furnace_controller_parameterisation import (
    C5H_DIR,
    run_s4_4c5h_blast_furnace_controller_parameterisation,
)
from .s4_4c5j_bof_osf_minimal_parameterisation import C5J_DIR
from .s4_4c5k_production_policy_and_route_split_normalisation import (
    C5K_DIR,
    run_s4_4c5k_production_policy_and_route_split_normalisation,
)
from .s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch import (
    C5L_D_DIR,
    HSM_CO2_STATUS,
    HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
    HSM_HOT_CHARGE_CAP_SENSITIVITY_CASES,
    run_s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch,
)


STAGE = "S4.4c5m_Sinter_minimal_parameterisation"
C5M_DIR = S4_ROOT / "s4_4c5m_Sinter_minimal_parameterisation"
SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/SINTER_Parameters.md")
SOURCE_ID = "SINTER_Parameters_candidate_source_card"
DEPENDENCY_CHAIN = "C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m"

SINTER_DRIVER_MODE = "BF_hot_metal_coupled"
SINTER_PROCESS_CLASS = "continuous_lp_link"
SINTER_STEAM_MODE = "active_utility_demand_with_proxy_supply"
SINTER_CO2_ACCOUNTING_MODE = "aggregate_counter_mode"
SINTER_ALLOWED_GAS_CARRIERS = ("COG", "NG")
SINTER_WAG_PRODUCTION_FLAG = False
SINTER_GAS_CONTROLLER_MODE = "shared_eligibility_constrained_WAG_allocation_controller"
SINTER_GAS_CONTROLLER_OBJECTIVE = "physical_allocation_proxy_no_market_or_ets_steering"
STEAM_SUPPLY_MODE = "proxy_supply_until_steam_network"
PATTERN_AUDIT_SUMMARY = (
    "matched_existing_C5_development_input_rows_source_card_stage_runner_csv_json_"
    "report_stage_gate_wag_lhv_co2_pytest_patterns"
)

SINTER_PER_T_HOT_METAL_C0 = 3.7 / 6.3
SINTER_PER_T_HOT_METAL_C1 = 2.8 / 2.8
SINTER_IRON_ORE_INPUT_T_PER_T_SINTER = 0.813
SINTER_OUTPUT_T_PER_T_IRON_ORE_BUS0 = 1.230
SINTER_ELECTRICITY_MWH_PER_T_SINTER = 0.0343
SINTER_COG_INPUT_GJ_PER_T_SINTER = 0.067
SINTER_COG_INPUT_MWH_PER_T_SINTER = 0.0186
SINTER_STEAM_INPUT_T_PER_T_SINTER = 0.010
SINTER_DIRECT_CO2_T_PER_T_SINTER = 0.248

SINTER_ELECTRICITY_RANGE_MWH_PER_T = (0.0256, 0.0431)
SINTER_GAS_RANGE_GJ_PER_T = (0.035, 0.185)
SINTER_STEAM_RANGE_T_PER_T = (0.003, 0.021)
SINTER_CO2_RANGE_T_PER_T = (0.162, 0.368)
SINTER_CO2_IPCC_SANITY_T_PER_T = 0.21
SINTER_CO2_EU_ETS_BENCHMARK_T_PER_T = 0.157

ANCHOR_SINTER_C0_OUTPUT_T_Y = 3_700_000.0
ANCHOR_SINTER_C1_OUTPUT_T_Y = 2_800_000.0
ANCHOR_BF_C0_HOT_METAL_T_Y = 6_300_000.0
ANCHOR_BF_C1_HOT_METAL_T_Y = 2_800_000.0
ANCHOR_SINTER_C1_FLEX_MIN_T_Y = 1_800_000.0
ANCHOR_SINTER_C1_FLEX_MAX_T_Y = 2_800_000.0

TOL_T = 1e-4
TOL_MWH = 1e-2

SINTER_PARAMETER_COLUMNS = [
    "parameter_id",
    "configuration_scope",
    "applies_to_configuration",
    "plant_id",
    "parameter_name",
    "parameter_role",
    "direction",
    "carrier_or_material",
    "base_value",
    "low_value",
    "high_value",
    "unit",
    "basis",
    "conversion_formula",
    "source_or_assumption_id",
    "input_status",
    "source_status",
    "evidence_strength",
    "executable_status",
    "development_executable",
    "thesis_usability",
    "human_review_required",
    "codex_may_decide",
    "applies_to_solver",
    "applies_to_diagnostics",
    "applies_to_anchor_comparison",
    "constraint_used",
    "caveat",
]


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _annualisation_factor(horizon: int) -> float:
    return 8760.0 / horizon


def _ratio_for_config(config: str, params: dict[str, str]) -> float:
    parameter_id = "SINTER_PER_T_HOT_METAL_C0" if config == C0 else "SINTER_PER_T_HOT_METAL_C1"
    return _zero(params[parameter_id])


def _active_anchor_for_config(config: str) -> float:
    return ANCHOR_SINTER_C0_OUTPUT_T_Y if config == C0 else ANCHOR_SINTER_C1_OUTPUT_T_Y


def _bf_anchor_for_config(config: str) -> float:
    return ANCHOR_BF_C0_HOT_METAL_T_Y if config == C0 else ANCHOR_BF_C1_HOT_METAL_T_Y


def _input_row(
    parameter_id: str,
    base_value: Any,
    unit: str,
    *,
    configuration: str = "all",
    role: str = "coefficient",
    direction: str = "input",
    carrier_or_material: str = "",
    low_value: Any = "",
    high_value: Any = "",
    basis: str = "per_t_sinter",
    conversion_formula: str = "",
    input_status: str = "development_candidate",
    evidence_strength: str = "candidate only; not Tata-validated; not thesis-approved",
    applies_to_anchor_comparison: str = "false",
    constraint_used: str = "false",
    caveat: str = "candidate only; not Tata-validated; not thesis-approved",
) -> dict[str, Any]:
    return {
        "parameter_id": parameter_id,
        "configuration_scope": configuration,
        "applies_to_configuration": configuration,
        "plant_id": "Sinter_Plant",
        "parameter_name": parameter_id,
        "parameter_role": role,
        "direction": direction,
        "carrier_or_material": carrier_or_material,
        "base_value": _fmt(base_value),
        "low_value": _fmt(low_value),
        "high_value": _fmt(high_value),
        "unit": unit,
        "basis": basis,
        "conversion_formula": conversion_formula,
        "source_or_assumption_id": SOURCE_ID,
        "input_status": input_status,
        "source_status": "source_card_candidate",
        "evidence_strength": evidence_strength,
        "executable_status": "development_executable",
        "development_executable": "true",
        "thesis_usability": "false",
        "human_review_required": "true",
        "codex_may_decide": "false",
        "applies_to_solver": "false",
        "applies_to_diagnostics": "true",
        "applies_to_anchor_comparison": applies_to_anchor_comparison,
        "constraint_used": constraint_used,
        "caveat": caveat,
    }


def _development_input_rows() -> list[dict[str, Any]]:
    rows = [
        _input_row(
            "SINTER_BUS0",
            "iron_ore",
            "material_bus",
            role="mode",
            direction="input",
            carrier_or_material="iron_ore",
            basis="bus0",
            input_status="development_assumption",
        ),
        _input_row(
            "SINTER_PROCESS_CLASS",
            SINTER_PROCESS_CLASS,
            "class_label",
            role="mode",
            basis="plant_class",
            input_status="development_assumption",
        ),
        _input_row(
            "SINTER_STEAM_MODE",
            SINTER_STEAM_MODE,
            "mode_label",
            role="mode",
            carrier_or_material="steam",
            basis="utility_supply",
            input_status="development_utility_proxy",
        ),
        _input_row(
            "SINTER_CO2_ACCOUNTING_MODE",
            SINTER_CO2_ACCOUNTING_MODE,
            "mode_label",
            role="mode",
            carrier_or_material="CO2",
            basis="carbon_accounting",
            input_status="development_assumption",
            caveat="aggregate CO2 counter only; Sinter COG/NG combustion CO2 objective accounting blocked",
        ),
        _input_row(
            "SINTER_ALLOWED_GAS_CARRIERS",
            "COG;NG",
            "carrier_set",
            role="eligibility",
            carrier_or_material="COG;NG",
            basis="WAG_controller",
            input_status="development_assumption",
            caveat="Sinter cannot use BFG or BOFG in the base C5m implementation",
        ),
        _input_row(
            "SINTER_WAG_PRODUCTION_FLAG",
            "false",
            "boolean",
            role="eligibility",
            direction="output",
            carrier_or_material="WAG",
            basis="WAG_controller",
            input_status="development_assumption",
            caveat="Sinter is a WAG consumer only; no Sinter off-gas useful-WAG is modelled",
        ),
        _input_row(
            "SINTER_PER_T_HOT_METAL_C0",
            SINTER_PER_T_HOT_METAL_C0,
            "t sinter / t hot metal",
            configuration=C0,
            role="driver_ratio",
            direction="output",
            carrier_or_material="sinter",
            basis="BF_hot_metal_coupled",
            conversion_formula="ANCHOR_SINTER_C0_OUTPUT / ANCHOR_BF_C0_HOT_METAL = 3.7 / 6.3",
            input_status="development_candidate",
            caveat="development coupling coefficient; not a universal sinter recipe; not calibrated to active C0 output",
        ),
        _input_row(
            "SINTER_PER_T_HOT_METAL_C1",
            SINTER_PER_T_HOT_METAL_C1,
            "t sinter / t hot metal",
            configuration=C1,
            role="driver_ratio",
            direction="output",
            carrier_or_material="sinter",
            basis="BF_hot_metal_coupled",
            conversion_formula="ANCHOR_SINTER_C1_OUTPUT / ANCHOR_BF_C1_HOT_METAL = 2.8 / 2.8",
            input_status="development_candidate",
            caveat="development coupling coefficient; C1 operational flex band is not an hourly ramp range",
        ),
        _input_row(
            "SINTER_IRON_ORE_INPUT_T_PER_T_SINTER",
            SINTER_IRON_ORE_INPUT_T_PER_T_SINTER,
            "t iron ore / t sinter",
            direction="input",
            carrier_or_material="iron_ore",
            basis="per_t_sinter",
        ),
        _input_row(
            "SINTER_OUTPUT_T_PER_T_IRON_ORE_BUS0",
            SINTER_OUTPUT_T_PER_T_IRON_ORE_BUS0,
            "t sinter / t iron ore bus0",
            role="derived_bus0_output_factor",
            direction="output",
            carrier_or_material="sinter",
            basis="bus0_iron_ore",
            conversion_formula="1 / SINTER_IRON_ORE_INPUT_T_PER_T_SINTER",
            caveat="output exceeds bus0 input because omitted raw-mix inputs are implicit",
        ),
        _input_row(
            "SINTER_ELECTRICITY_MWH_PER_T_SINTER",
            SINTER_ELECTRICITY_MWH_PER_T_SINTER,
            "MWh_e / t sinter",
            low_value=SINTER_ELECTRICITY_RANGE_MWH_PER_T[0],
            high_value=SINTER_ELECTRICITY_RANGE_MWH_PER_T[1],
            role="utility_coefficient",
            direction="input",
            carrier_or_material="electricity",
            input_status="development_utility_proxy",
        ),
        _input_row(
            "SINTER_COG_INPUT_GJ_PER_T_SINTER",
            SINTER_COG_INPUT_GJ_PER_T_SINTER,
            "GJ_LHV / t sinter",
            low_value=SINTER_GAS_RANGE_GJ_PER_T[0],
            high_value=SINTER_GAS_RANGE_GJ_PER_T[1],
            role="gas_coefficient",
            direction="input",
            carrier_or_material="COG_or_NG",
        ),
        _input_row(
            "SINTER_COG_INPUT_MWH_PER_T_SINTER",
            SINTER_COG_INPUT_MWH_PER_T_SINTER,
            "MWh_LHV / t sinter",
            role="gas_coefficient",
            direction="input",
            carrier_or_material="COG_or_NG",
            conversion_formula="SINTER_COG_INPUT_GJ_PER_T_SINTER / 3.6",
        ),
        _input_row(
            "SINTER_STEAM_INPUT_T_PER_T_SINTER",
            SINTER_STEAM_INPUT_T_PER_T_SINTER,
            "t steam / t sinter",
            low_value=SINTER_STEAM_RANGE_T_PER_T[0],
            high_value=SINTER_STEAM_RANGE_T_PER_T[1],
            role="utility_coefficient",
            direction="input",
            carrier_or_material="steam",
            input_status="development_utility_proxy",
        ),
        _input_row(
            "SINTER_DIRECT_CO2_T_PER_T_SINTER",
            SINTER_DIRECT_CO2_T_PER_T_SINTER,
            "tCO2e / t sinter",
            low_value=SINTER_CO2_RANGE_T_PER_T[0],
            high_value=SINTER_CO2_RANGE_T_PER_T[1],
            role="aggregate_co2_counter",
            direction="output",
            carrier_or_material="CO2",
            input_status="development_candidate",
            caveat="aggregate counter only; do not also book full Sinter COG/NG combustion CO2 as objective emissions",
        ),
        _input_row(
            "SINTER_CO2_IPCC_SANITY_T_PER_T_SINTER",
            SINTER_CO2_IPCC_SANITY_T_PER_T,
            "tCO2 / t sinter",
            role="sensitivity_metadata",
            direction="output",
            carrier_or_material="CO2",
            input_status="development_anchor_context",
            applies_to_anchor_comparison="true",
        ),
        _input_row(
            "SINTER_CO2_EU_ETS_BENCHMARK_T_PER_T_SINTER",
            SINTER_CO2_EU_ETS_BENCHMARK_T_PER_T,
            "tCO2e / t sinter",
            role="sensitivity_metadata",
            direction="output",
            carrier_or_material="CO2",
            input_status="development_anchor_context",
            applies_to_anchor_comparison="true",
            caveat="benchmark-only reference; not used for ETS objective steering",
        ),
    ]
    anchor_rows = [
        ("ANCHOR_SINTER_C0_OUTPUT", ANCHOR_SINTER_C0_OUTPUT_T_Y, C0, "t/y"),
        ("ANCHOR_SINTER_C1_OUTPUT", ANCHOR_SINTER_C1_OUTPUT_T_Y, C1, "t/y"),
        ("ANCHOR_BF_C0_HOT_METAL", ANCHOR_BF_C0_HOT_METAL_T_Y, C0, "t/y"),
        ("ANCHOR_BF_C1_HOT_METAL", ANCHOR_BF_C1_HOT_METAL_T_Y, C1, "t/y"),
        ("ANCHOR_SINTER_C1_OPERATIONAL_FLEX_MIN", ANCHOR_SINTER_C1_FLEX_MIN_T_Y, C1, "t/y"),
        ("ANCHOR_SINTER_C1_OPERATIONAL_FLEX_MAX", ANCHOR_SINTER_C1_FLEX_MAX_T_Y, C1, "t/y"),
    ]
    for parameter_id, value, config, unit in anchor_rows:
        rows.append(
            _input_row(
                parameter_id,
                value,
                unit,
                configuration=config,
                role="validation_anchor_context",
                direction="context",
                carrier_or_material="sinter_or_hot_metal",
                basis="public_MER_context_anchor",
                input_status="development_anchor_context",
                applies_to_anchor_comparison="true",
                caveat="validation/context only; constraint_used=false; not a dispatch or calibration constraint",
            )
        )
    return rows


def _source_candidate_rows(input_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "record_type": "source_card",
            "source_card_id": SOURCE_ID,
            "citation": "SINTER_Parameters.md candidate source-card memo, repository-local development note",
            "url_or_path": _rel(SOURCE_CARD),
            "locator_status": "repository source-card memo; exact external provenance remains pending human review",
            "thesis_usability": "false",
            "human_review_required": "true",
            "codex_may_decide": "false",
            "status": "development_only",
            "caveat": "candidate only; not Tata-validated; not thesis-approved",
        }
    ]
    for row in input_rows:
        rows.append(
            {
                "record_type": "candidate_parameter",
                "source_card_id": SOURCE_ID,
                "parameter_id": row["parameter_id"],
                "candidate_value": row["base_value"],
                "unit": row["unit"],
                "input_status": row["input_status"],
                "evidence_strength": row["evidence_strength"],
                "locator_status": "repository source-card memo; exact external provenance remains pending human review",
                "thesis_usability": row["thesis_usability"],
                "human_review_required": row["human_review_required"],
                "codex_may_decide": row["codex_may_decide"],
                "constraint_used": row["constraint_used"],
                "caveat": row["caveat"],
            }
        )
    return rows


def _params(input_rows: list[dict[str, str]]) -> dict[str, str]:
    return {row["parameter_id"]: row["base_value"] for row in input_rows}


def _bf_driver_by_key(c5k_report: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in c5k_report}


def _hourly_rows(c5k_report: list[dict[str, str]], params: dict[str, str]) -> list[dict[str, Any]]:
    c5k = _bf_driver_by_key(c5k_report)
    rows: list[dict[str, Any]] = []
    iron_ore = _zero(params["SINTER_IRON_ORE_INPUT_T_PER_T_SINTER"])
    electricity = _zero(params["SINTER_ELECTRICITY_MWH_PER_T_SINTER"])
    gas_gj = _zero(params["SINTER_COG_INPUT_GJ_PER_T_SINTER"])
    steam = _zero(params["SINTER_STEAM_INPUT_T_PER_T_SINTER"])
    co2 = _zero(params["SINTER_DIRECT_CO2_T_PER_T_SINTER"])
    for config in CONFIGS:
        for horizon in HORIZONS:
            ann = _annualisation_factor(horizon)
            source = c5k[(config, horizon)]
            bf_hm_annual = _zero(source["bf_hot_metal_normalised_site_t_y"])
            bf_hm_t = bf_hm_annual / ann / horizon
            ratio = _ratio_for_config(config, params)
            for timestep in range(horizon):
                sinter_t = bf_hm_t * ratio
                gas_gj_t = sinter_t * gas_gj
                rows.append(
                    {
                        "stage_id": STAGE,
                        "configuration": config,
                        "horizon_hours": horizon,
                        "timestep": timestep,
                        "annualisation_factor": _fmt(ann),
                        "status": "pass",
                        "thesis_usability": "false",
                        "sinter_per_t_hot_metal": _fmt(ratio),
                        "sinter_driver_mode": SINTER_DRIVER_MODE,
                        "bf_hot_metal_output_site_t": _fmt(bf_hm_t),
                        "sinter_output_site_t": _fmt(sinter_t),
                        "sinter_iron_ore_input_site_t": _fmt(sinter_t * iron_ore),
                        "sinter_electricity_site_MWh_e": _fmt(sinter_t * electricity),
                        "sinter_gas_demand_site_GJ_LHV": _fmt(gas_gj_t),
                        "sinter_gas_demand_site_MWh_LHV": _fmt(gas_gj_t / 3.6),
                        "sinter_steam_demand_site_t": _fmt(sinter_t * steam),
                        "sinter_steam_proxy_supply_site_t": _fmt(sinter_t * steam),
                        "sinter_steam_unserved_site_t": _fmt(0.0),
                        "sinter_aggregate_CO2_site_t": _fmt(sinter_t * co2),
                        "BFG_to_Sinter_site_MWh_LHV": _fmt(0.0),
                        "BOFG_to_Sinter_site_MWh_LHV": _fmt(0.0),
                        "per_timestep_equation": "sinter_output_t = bf_hot_metal_output_t * SINTER_PER_T_HOT_METAL",
                    }
                )
    return rows


def _aggregate_hourly(hourly: list[dict[str, Any]], c5k_report: list[dict[str, str]], params: dict[str, str]) -> list[dict[str, Any]]:
    c5k = _bf_driver_by_key(c5k_report)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            ann = _annualisation_factor(horizon)
            subset = [row for row in hourly if row["configuration"] == config and int(row["horizon_hours"]) == horizon]

            def annual(field: str) -> float:
                return sum(_zero(row[field]) for row in subset) * ann

            source = c5k[(config, horizon)]
            bf_hm = annual("bf_hot_metal_output_site_t")
            sinter = annual("sinter_output_site_t")
            iron_ore = annual("sinter_iron_ore_input_site_t")
            electricity = annual("sinter_electricity_site_MWh_e")
            gas_gj = annual("sinter_gas_demand_site_GJ_LHV")
            gas_mwh = annual("sinter_gas_demand_site_MWh_LHV")
            steam = annual("sinter_steam_demand_site_t")
            co2 = annual("sinter_aggregate_CO2_site_t")
            ratio = _ratio_for_config(config, params)
            raw_sinter_anchor = _active_anchor_for_config(config)
            bf_anchor = _bf_anchor_for_config(config)
            active_expected = _zero(source["bf_hot_metal_normalised_site_t_y"]) * ratio
            flex_status = ""
            if config == C1:
                flex_upper_tolerance = 5_000.0
                if ANCHOR_SINTER_C1_FLEX_MIN_T_Y <= sinter <= ANCHOR_SINTER_C1_FLEX_MAX_T_Y:
                    flex_status = "within_context_band_not_ramp"
                elif ANCHOR_SINTER_C1_FLEX_MIN_T_Y <= sinter <= ANCHOR_SINTER_C1_FLEX_MAX_T_Y + flex_upper_tolerance:
                    flex_status = "near_upper_bound_context_gap_not_ramp"
                else:
                    flex_status = "outside_context_band_not_ramp"
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "dependency_chain": DEPENDENCY_CHAIN,
                    "existing_pattern_audit_summary": PATTERN_AUDIT_SUMMARY,
                    "active_configurations": ";".join(CONFIGS),
                    "active_horizons_hours": ";".join(str(item) for item in HORIZONS),
                    "inherited_hsm_heat_case": HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
                    "sensitivity_references_available": "C5l_d_high_0_80;C5l_c_uncapped_reference;C5l_b_average_reheat",
                    "sinter_process_class": params["SINTER_PROCESS_CLASS"],
                    "sinter_bus0": params["SINTER_BUS0"],
                    "sinter_allowed_gas_carriers": ";".join(SINTER_ALLOWED_GAS_CARRIERS),
                    "sinter_wag_production_flag": str(SINTER_WAG_PRODUCTION_FLAG).lower(),
                    "sinter_per_timestep_driver_mode": SINTER_DRIVER_MODE,
                    "sinter_per_t_hot_metal": _fmt(ratio),
                    "bf_hot_metal_driver_site_t_y": _fmt(bf_hm),
                    "sinter_output_site_t_y": _fmt(sinter),
                    "sinter_iron_ore_bus0_input_site_t_y": _fmt(iron_ore),
                    "sinter_output_t_per_t_iron_ore_bus0": params["SINTER_OUTPUT_T_PER_T_IRON_ORE_BUS0"],
                    "sinter_electricity_site_MWh_e_y": _fmt(electricity),
                    "sinter_electricity_site_GWh_e_y": _fmt(electricity / 1000.0),
                    "sinter_electricity_site_TWh_e_y": _fmt(electricity / 1_000_000.0),
                    "sinter_gas_demand_site_GJ_LHV_y": _fmt(gas_gj),
                    "sinter_gas_demand_site_PJ_LHV_y": _fmt(gas_gj / 1_000_000.0),
                    "sinter_gas_demand_site_MWh_LHV_y": _fmt(gas_mwh),
                    "sinter_gas_demand_site_TWh_LHV_y": _fmt(gas_mwh / 1_000_000.0),
                    "sinter_gas_demand_MWh_LHV_per_t_sinter": params["SINTER_COG_INPUT_MWH_PER_T_SINTER"],
                    "sinter_steam_demand_site_t_y": _fmt(steam),
                    "sinter_steam_demand_site_kt_y": _fmt(steam / 1000.0),
                    "sinter_steam_proxy_supply_site_t_y": _fmt(steam),
                    "sinter_steam_unserved_site_t_y": _fmt(0.0),
                    "steam_supply_mode": STEAM_SUPPLY_MODE,
                    "sinter_aggregate_CO2_site_t_y": _fmt(co2),
                    "sinter_aggregate_CO2_site_Mt_y": _fmt(co2 / 1_000_000.0),
                    "sinter_CO2_accounting_mode": SINTER_CO2_ACCOUNTING_MODE,
                    "sinter_CO2_BREF_low_site_Mt_y": _fmt(sinter * SINTER_CO2_RANGE_T_PER_T[0] / 1_000_000.0),
                    "sinter_CO2_BREF_high_site_Mt_y": _fmt(sinter * SINTER_CO2_RANGE_T_PER_T[1] / 1_000_000.0),
                    "sinter_CO2_IPCC_sanity_site_Mt_y": _fmt(sinter * SINTER_CO2_IPCC_SANITY_T_PER_T / 1_000_000.0),
                    "sinter_CO2_EU_ETS_benchmark_site_Mt_y": _fmt(sinter * SINTER_CO2_EU_ETS_BENCHMARK_T_PER_T / 1_000_000.0),
                    "raw_MER_sinter_anchor_site_t_y": _fmt(raw_sinter_anchor),
                    "raw_MER_sinter_gap_site_t_y": _fmt(sinter - raw_sinter_anchor),
                    "raw_MER_sinter_gap_pct": _fmt((sinter - raw_sinter_anchor) / raw_sinter_anchor * 100.0),
                    "raw_MER_BF_hot_metal_anchor_site_t_y": _fmt(bf_anchor),
                    "raw_MER_BF_hot_metal_gap_site_t_y": _fmt(bf_hm - bf_anchor),
                    "active_scale_expected_sinter_site_t_y": _fmt(active_expected),
                    "active_scale_sinter_gap_site_t_y": _fmt(sinter - active_expected),
                    "C1_operational_flex_band_min_t_y": _fmt(ANCHOR_SINTER_C1_FLEX_MIN_T_Y if config == C1 else ""),
                    "C1_operational_flex_band_max_t_y": _fmt(ANCHOR_SINTER_C1_FLEX_MAX_T_Y if config == C1 else ""),
                    "C1_operational_flex_band_status": flex_status,
                    "anchor_constraints_used": "0",
                    "no_anchor_constraint_status": "pass",
                    "no_sinter_wag_production_status": "pass",
                    "site_process_electricity_ledger_update_status": "process_electricity_demand_added",
                    "CO2_double_counting_guard_status": "pass",
                    "WAG_invariant_status": "",
                    "LHV_consistency_status": "",
                    "HSM_reheat_demand_site_MWh_y": "",
                    "BFG_to_HSM_site_MWh_y": "",
                    "COG_to_HSM_site_MWh_y": "",
                    "BOFG_to_HSM_site_MWh_y": "",
                    "NG_to_HSM_site_MWh_y": "",
                    "COG_to_Sinter_site_MWh_y": "",
                    "NG_to_Sinter_site_MWh_y": "",
                    "BFG_to_Sinter_site_MWh_y": "0",
                    "BOFG_to_Sinter_site_MWh_y": "0",
                    "Sinter_gas_unserved_site_MWh_y": "0",
                    "residual_COG_after_HSM_and_Sinter_site_MWh_y": "",
                    "HSM_CO2_status": HSM_CO2_STATUS,
                    "final_product_proxy_site_t_y": source["active_total_liquid_steel_target_site_t_y"],
                    "excluded_real_sinter_inputs": "limestone;lime;dolomite;coke_breeze;return_fines;residues;off_gas;dust;gas_cleaning;cooler_heat_recovery;detailed_chemistry",
                    "deferred_items": "full_steam_network;Sinter_offgas;waste_heat_recovery;coke_breeze_carbon_split;ramp_flex_scheduling;DA_price_response;ETS_objective",
                    "caveats": "candidate only; not Tata-validated; not thesis-approved; active C0 output follows C5k BF HM, not raw MER 3.7 Mt/y anchor",
                }
            )
    return rows


def _hsm_base_by_key(c5l_d_report: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in c5l_d_report
        if row["cap_case"] == HSM_HOT_CHARGE_CAP_ACTIVE_CASE
    }


def _site_total_wag_rows(c5k_wag: list[dict[str, str]], config: str, horizon: int) -> dict[str, dict[str, str]]:
    return {
        row["carrier"]: row
        for row in c5k_wag
        if row["configuration"] == config
        and int(row["horizon_hours"]) == horizon
        and row["plant_id"] == "SITE_TOTAL"
        and row["carrier"] in WAG_CARRIERS
    }


def _carrier_state(source: dict[str, str]) -> dict[str, float]:
    scale = _zero(source.get("scale_factor")) or 1.0
    generated_raw = _zero(source["generated_MWh_LHV_y"])
    generated_site = _zero(source.get("site_scaled_quantity")) or generated_raw * scale
    direct_raw = _zero(source["consumed_direct_MWh_LHV_y"])
    boiler_raw = _zero(source["consumed_boiler_MWh_LHV_y"])
    vattenfall_raw = _zero(source["consumed_vattenfall_MWh_LHV_y"])
    flare_raw = _zero(source["flared_MWh_LHV_y"])
    direct_site = direct_raw * scale
    available_site = max(generated_site - direct_site, 0.0)
    return {
        "scale": scale,
        "generated_raw": generated_raw,
        "generated_site": generated_site,
        "direct_pre_raw": direct_raw,
        "direct_pre_site": direct_site,
        "boiler_pre_raw": boiler_raw,
        "vattenfall_pre_raw": vattenfall_raw,
        "flare_pre_raw": flare_raw,
        "available_site": available_site,
    }


def _allocate_shared_wag(
    report: list[dict[str, Any]],
    c5k_wag: list[dict[str, str]],
    c5l_d_report: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, int, str], dict[str, float]]]:
    hsm = _hsm_base_by_key(c5l_d_report)
    dashboard: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    allocation: dict[tuple[str, int, str], dict[str, float]] = {}

    report_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in report}
    for config in CONFIGS:
        for horizon in HORIZONS:
            item = report_by_key[(config, horizon)]
            hsm_demand = _zero(hsm[(config, horizon)]["hsm_reheat_heat_site_MWh_th_y"])
            sinter_demand = _zero(item["sinter_gas_demand_site_MWh_LHV_y"])
            source_rows = _site_total_wag_rows(c5k_wag, config, horizon)
            state = {carrier: _carrier_state(source_rows[carrier]) for carrier in WAG_CARRIERS}

            hsm_remaining = hsm_demand
            sinter_remaining = sinter_demand

            bfg_to_hsm = min(hsm_remaining, state["BFG"]["available_site"])
            hsm_remaining -= bfg_to_hsm
            cog_to_sinter = min(sinter_remaining, state["COG"]["available_site"])
            sinter_remaining -= cog_to_sinter
            cog_after_sinter = max(state["COG"]["available_site"] - cog_to_sinter, 0.0)
            cog_to_hsm = min(hsm_remaining, cog_after_sinter)
            hsm_remaining -= cog_to_hsm
            bofg_to_hsm = min(hsm_remaining, state["BOFG"]["available_site"])
            hsm_remaining -= bofg_to_hsm

            ng_to_hsm = max(hsm_remaining, 0.0)
            ng_to_sinter = max(sinter_remaining, 0.0)
            hsm_unserved = 0.0
            sinter_unserved = 0.0

            carrier_uses_site = {
                "BFG": {"hsm": bfg_to_hsm, "sinter": 0.0},
                "COG": {"hsm": cog_to_hsm, "sinter": cog_to_sinter},
                "BOFG": {"hsm": bofg_to_hsm, "sinter": 0.0},
            }
            residual_site_by_carrier: dict[str, float] = {}
            for carrier in WAG_CARRIERS:
                scale = state[carrier]["scale"]
                used_site = carrier_uses_site[carrier]["hsm"] + carrier_uses_site[carrier]["sinter"]
                used_raw = used_site / scale if scale else 0.0
                direct_post_raw = state[carrier]["direct_pre_raw"] + used_raw
                generated_raw = state[carrier]["generated_raw"]
                boiler_post_raw = min(state[carrier]["boiler_pre_raw"], max(generated_raw - direct_post_raw, 0.0))
                vattenfall_post_raw = min(
                    state[carrier]["vattenfall_pre_raw"],
                    max(generated_raw - direct_post_raw - boiler_post_raw, 0.0),
                )
                flare_post_raw = max(generated_raw - direct_post_raw - boiler_post_raw - vattenfall_post_raw, 0.0)
                balance_error_raw = generated_raw - direct_post_raw - boiler_post_raw - vattenfall_post_raw - flare_post_raw
                if abs(balance_error_raw) <= WAG_TOL_MWH:
                    balance_error_raw = 0.0
                residual_site_by_carrier[carrier] = max(state[carrier]["available_site"] - used_site, 0.0)
                allocation[(config, horizon, carrier)] = {
                    **state[carrier],
                    "hsm_used_site": carrier_uses_site[carrier]["hsm"],
                    "sinter_used_site": carrier_uses_site[carrier]["sinter"],
                    "used_site": used_site,
                    "used_raw": used_raw,
                    "direct_post_raw": direct_post_raw,
                    "boiler_post_raw": boiler_post_raw,
                    "vattenfall_post_raw": vattenfall_post_raw,
                    "flare_post_raw": flare_post_raw,
                    "balance_error_raw": balance_error_raw,
                    "residual_site": residual_site_by_carrier[carrier],
                }
                for sink, used in (
                    ("HSM_reheat", carrier_uses_site[carrier]["hsm"]),
                    ("Sinter_gas", carrier_uses_site[carrier]["sinter"]),
                ):
                    eligible = (sink == "HSM_reheat" and carrier in WAG_CARRIERS) or (sink == "Sinter_gas" and carrier == "COG")
                    trace.append(
                        {
                            "configuration": config,
                            "horizon_hours": horizon,
                            "sink_id": sink,
                            "carrier": carrier,
                            "eligible_for_sink": str(eligible).lower(),
                            "allocated_site_MWh_LHV_y": _fmt(used),
                            "allocated_raw_MWh_LHV_y": _fmt(used / scale if scale else 0.0),
                            "available_to_controller_site_MWh_LHV_y": _fmt(state[carrier]["available_site"]),
                            "residual_after_HSM_and_Sinter_site_MWh_LHV_y": _fmt(residual_site_by_carrier[carrier]),
                            "controller_mode": SINTER_GAS_CONTROLLER_MODE,
                            "allocation_rule": "eligibility_constrained_physical_proxy_with_NG_backup",
                            "status": "pass" if eligible or used == 0.0 else "fail",
                        }
                    )

            hsm_balance = bfg_to_hsm + cog_to_hsm + bofg_to_hsm + ng_to_hsm + hsm_unserved - hsm_demand
            sinter_balance = cog_to_sinter + ng_to_sinter + sinter_unserved - sinter_demand
            if abs(hsm_balance) <= WAG_TOL_MWH:
                hsm_balance = 0.0
            if abs(sinter_balance) <= WAG_TOL_MWH:
                sinter_balance = 0.0
            status = "pass" if abs(hsm_balance) <= WAG_TOL_MWH and abs(sinter_balance) <= WAG_TOL_MWH and sinter_unserved == 0.0 else "fail"
            dashboard.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "inherited_hsm_heat_case": HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
                    "controller_mode": SINTER_GAS_CONTROLLER_MODE,
                    "controller_objective": SINTER_GAS_CONTROLLER_OBJECTIVE,
                    "hsm_reheat_demand_site_MWh_y": _fmt(hsm_demand),
                    "sinter_gas_demand_site_MWh_y": _fmt(sinter_demand),
                    "BFG_to_HSM_site_MWh_y": _fmt(bfg_to_hsm),
                    "COG_to_HSM_site_MWh_y": _fmt(cog_to_hsm),
                    "BOFG_to_HSM_site_MWh_y": _fmt(bofg_to_hsm),
                    "NG_to_HSM_site_MWh_y": _fmt(ng_to_hsm),
                    "HSM_unserved_reheat_site_MWh_y": _fmt(hsm_unserved),
                    "COG_to_Sinter_site_MWh_y": _fmt(cog_to_sinter),
                    "NG_to_Sinter_site_MWh_y": _fmt(ng_to_sinter),
                    "BFG_to_Sinter_site_MWh_y": _fmt(0.0),
                    "BOFG_to_Sinter_site_MWh_y": _fmt(0.0),
                    "Sinter_gas_unserved_site_MWh_y": _fmt(sinter_unserved),
                    "residual_BFG_after_HSM_and_Sinter_site_MWh_y": _fmt(residual_site_by_carrier["BFG"]),
                    "residual_COG_after_HSM_and_Sinter_site_MWh_y": _fmt(residual_site_by_carrier["COG"]),
                    "residual_BOFG_after_HSM_and_Sinter_site_MWh_y": _fmt(residual_site_by_carrier["BOFG"]),
                    "residual_WAG_after_HSM_and_Sinter_site_MWh_y": _fmt(sum(residual_site_by_carrier.values())),
                    "hsm_controller_balance_error_site_MWh_y": _fmt(hsm_balance),
                    "sinter_controller_balance_error_site_MWh_y": _fmt(sinter_balance),
                    "fixed_plant_priority_imposed": "false",
                    "NG_backup_allowed": "true",
                    "WAG_market_valuation_added": "false",
                    "WAG_export_revenue_added": "false",
                    "status": status,
                    "red_flags": "" if status == "pass" else "controller_balance_or_unserved_sinter_gas",
                }
            )
    return dashboard, trace, allocation


def _update_report_with_controller(
    report: list[dict[str, Any]],
    controller: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    lhv: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ctrl = {(row["configuration"], int(row["horizon_hours"])): row for row in controller}
    agg = {
        (row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row
        for row in wag_aggregate
    }
    lhv_fail_by_key: dict[tuple[str, int], int] = {}
    for row in lhv:
        key = (row["configuration"], int(row["horizon_hours"]))
        lhv_fail_by_key[key] = lhv_fail_by_key.get(key, 0) + (0 if row["status"] == "pass" else 1)
    out: list[dict[str, Any]] = []
    for row in report:
        item = dict(row)
        key = (row["configuration"], int(row["horizon_hours"]))
        controller_row = ctrl[key]
        item.update(
            {
                "WAG_invariant_status": agg[(key[0], key[1], "site_scaled")]["status"],
                "LHV_consistency_status": "pass" if lhv_fail_by_key.get(key, 0) == 0 else "fail",
                "HSM_reheat_demand_site_MWh_y": controller_row["hsm_reheat_demand_site_MWh_y"],
                "BFG_to_HSM_site_MWh_y": controller_row["BFG_to_HSM_site_MWh_y"],
                "COG_to_HSM_site_MWh_y": controller_row["COG_to_HSM_site_MWh_y"],
                "BOFG_to_HSM_site_MWh_y": controller_row["BOFG_to_HSM_site_MWh_y"],
                "NG_to_HSM_site_MWh_y": controller_row["NG_to_HSM_site_MWh_y"],
                "COG_to_Sinter_site_MWh_y": controller_row["COG_to_Sinter_site_MWh_y"],
                "NG_to_Sinter_site_MWh_y": controller_row["NG_to_Sinter_site_MWh_y"],
                "BFG_to_Sinter_site_MWh_y": controller_row["BFG_to_Sinter_site_MWh_y"],
                "BOFG_to_Sinter_site_MWh_y": controller_row["BOFG_to_Sinter_site_MWh_y"],
                "Sinter_gas_unserved_site_MWh_y": controller_row["Sinter_gas_unserved_site_MWh_y"],
                "residual_COG_after_HSM_and_Sinter_site_MWh_y": controller_row["residual_COG_after_HSM_and_Sinter_site_MWh_y"],
            }
        )
        out.append(item)
    return out


def _wag_generation_consumption_rows(c5k_wag: list[dict[str, str]], allocation: dict[tuple[str, int, str], dict[str, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in c5k_wag:
        item = dict(row)
        if row["plant_id"] == "SITE_TOTAL" and row["carrier"] in WAG_CARRIERS:
            key = (row["configuration"], int(row["horizon_hours"]), row["carrier"])
            if key in allocation:
                alloc = allocation[key]
                item["consumed_direct_MWh_LHV_y"] = _fmt(alloc["direct_post_raw"])
                item["consumed_boiler_MWh_LHV_y"] = _fmt(alloc["boiler_post_raw"])
                item["consumed_vattenfall_MWh_LHV_y"] = _fmt(alloc["vattenfall_post_raw"])
                item["flared_MWh_LHV_y"] = _fmt(alloc["flare_post_raw"])
                item["balance_error_MWh_LHV_y"] = _fmt(alloc["balance_error_raw"])
                item["status"] = "closed_after_C5m_HSM_and_Sinter_shared_controller"
                item["notes"] = "SITE_TOTAL WAG direct use includes inherited C5l_d base HSM reheat and C5m Sinter gas demand where eligible."
        rows.append(item)

    for config in CONFIGS:
        for horizon in HORIZONS:
            for carrier in WAG_CARRIERS:
                alloc = allocation[(config, horizon, carrier)]
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "plant_id": "Sinter_Plant",
                        "carrier": carrier,
                        "generated_MWh_LHV_y": _fmt(0.0),
                        "generated_Nm3_y": _fmt(0.0),
                        "consumed_direct_MWh_LHV_y": _fmt(alloc["sinter_used_site"] / alloc["scale"] if alloc["scale"] else 0.0),
                        "consumed_boiler_MWh_LHV_y": _fmt(0.0),
                        "consumed_vattenfall_MWh_LHV_y": _fmt(0.0),
                        "flared_MWh_LHV_y": _fmt(0.0),
                        "balance_error_MWh_LHV_y": _fmt(-(alloc["sinter_used_site"] / alloc["scale"] if alloc["scale"] else 0.0)),
                        "raw_model_quantity": _fmt(alloc["sinter_used_site"] / alloc["scale"] if alloc["scale"] else 0.0),
                        "raw_model_unit": "MWh_LHV/y",
                        "site_scaled_quantity": _fmt(alloc["sinter_used_site"]),
                        "site_scaled_unit": "MWh_LHV/y",
                        "scale_factor": _fmt(alloc["scale"]),
                        "LHV_MJ_per_Nm3_used": _fmt(COG_LHV_MJ_PER_NM3 if carrier == "COG" else ""),
                        "metric_scope": "Sinter_consumer_trace_only_not_WAG_generation",
                        "status": "sinter_wag_consumer_trace_only" if carrier == "COG" else "ineligible_zero_use",
                        "notes": "Sinter does not generate WAG; only COG is eligible as WAG input in C5m.",
                    }
                )
    return rows


def _wag_aggregate_rows(allocation: dict[tuple[str, int, str], dict[str, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            for basis in ("raw", "site_scaled"):
                generated = direct = boiler = vattenfall = flared = 0.0
                generated_by_carrier: dict[str, float] = {}
                for carrier in WAG_CARRIERS:
                    alloc = allocation[(config, horizon, carrier)]
                    scale = alloc["scale"] if basis == "site_scaled" else 1.0
                    generated_by_carrier[carrier] = alloc["generated_raw"] * scale
                    generated += alloc["generated_raw"] * scale
                    direct += alloc["direct_post_raw"] * scale
                    boiler += alloc["boiler_post_raw"] * scale
                    vattenfall += alloc["vattenfall_post_raw"] * scale
                    flared += alloc["flare_post_raw"] * scale
                explicit_other = generated - direct - boiler - vattenfall - flared
                if abs(explicit_other) <= WAG_TOL_MWH:
                    explicit_other = 0.0
                accounted = direct + boiler + vattenfall + flared + explicit_other
                balance = generated - accounted
                if abs(balance) <= WAG_TOL_MWH:
                    balance = 0.0
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "scale_basis": basis,
                        "BFG_generated_MWh_y": _fmt(generated_by_carrier["BFG"]),
                        "COG_generated_MWh_y": _fmt(generated_by_carrier["COG"]),
                        "BOFG_generated_MWh_y": _fmt(generated_by_carrier["BOFG"]),
                        "total_WAG_generated_MWh_y": _fmt(generated),
                        "total_WAG_direct_use_MWh_y": _fmt(direct),
                        "total_WAG_boiler_use_MWh_y": _fmt(boiler),
                        "total_WAG_vattenfall_use_MWh_y": _fmt(vattenfall),
                        "total_WAG_flared_MWh_y": _fmt(flared),
                        "total_WAG_explicit_other_sink_or_loss_MWh_y": _fmt(explicit_other),
                        "total_WAG_accounted_MWh_y": _fmt(accounted),
                        "balance_error_MWh_y": _fmt(balance),
                        "status": "pass" if abs(balance) <= WAG_TOL_MWH else "fail",
                        "red_flags": "" if abs(balance) <= WAG_TOL_MWH else "aggregate_wag_balance_error",
                        "notes": "C5m aggregate includes inherited C5l_d base HSM reheat and Sinter COG use.",
                    }
                )
    return rows


def _lhv_rows(report: list[dict[str, Any]], controller: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ctrl = {(row["configuration"], int(row["horizon_hours"])): row for row in controller}
    rows: list[dict[str, Any]] = []
    for item in report:
        key = (item["configuration"], int(item["horizon_hours"]))
        demand_mwh = _zero(item["sinter_gas_demand_site_MWh_LHV_y"])
        demand_gj = _zero(item["sinter_gas_demand_site_GJ_LHV_y"])
        expected_mwh = demand_gj / 3.6
        rows.append(
            {
                "configuration": item["configuration"],
                "horizon_hours": item["horizon_hours"],
                "plant": "Sinter_Plant",
                "carrier": "COG_or_NG",
                "reported_GJ_LHV_y": _fmt(demand_gj),
                "reported_MWh_LHV_y": _fmt(demand_mwh),
                "expected_MWh_LHV_from_GJ": _fmt(expected_mwh),
                "absolute_error_MWh": _fmt(demand_mwh - expected_mwh),
                "allocated_COG_MWh_LHV_y": ctrl[key]["COG_to_Sinter_site_MWh_y"],
                "allocated_NG_MWh_LHV_y": ctrl[key]["NG_to_Sinter_site_MWh_y"],
                "status": "pass" if abs(demand_mwh - expected_mwh) <= TOL_MWH else "fail",
                "red_flags": "" if abs(demand_mwh - expected_mwh) <= TOL_MWH else "gj_mwh_conversion_mismatch",
                "notes": "Sinter gas demand uses 1 MWh = 3.6 GJ; no Wobbe-index constraint is introduced.",
            }
        )
    return rows


def _co2_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in report:
        rows.extend(
            [
                {
                    "configuration": item["configuration"],
                    "horizon_hours": item["horizon_hours"],
                    "emission_bucket": "Sinter_aggregate_CO2_diagnostic",
                    "CO2_site_t_y": item["sinter_aggregate_CO2_site_t_y"],
                    "CO2_site_Mt_y": item["sinter_aggregate_CO2_site_Mt_y"],
                    "CO2_mode": SINTER_CO2_ACCOUNTING_MODE,
                    "included_in_objective_ETS_cost": "false",
                    "included_in_total_direct_CO2": "diagnostic_counter_only",
                    "double_counting_risk": "blocked_by_C5m_aggregate_counter_guard",
                    "status": "pass",
                    "notes": "Sinter aggregate CO2 diagnostic = sinter output * 0.248 tCO2e/t.",
                },
                {
                    "configuration": item["configuration"],
                    "horizon_hours": item["horizon_hours"],
                    "emission_bucket": "Sinter_COG_NG_combustion_CO2",
                    "CO2_site_t_y": "",
                    "CO2_site_Mt_y": "",
                    "CO2_mode": "blocked_to_avoid_double_counting_with_aggregate_sinter_counter",
                    "included_in_objective_ETS_cost": "false",
                    "included_in_total_direct_CO2": "false",
                    "double_counting_risk": "would_double_count_if_added_with_aggregate_sinter_CO2",
                    "status": "pass",
                    "notes": "Full Sinter gas combustion CO2 is not booked while aggregate Sinter CO2 is active.",
                },
                {
                    "configuration": item["configuration"],
                    "horizon_hours": item["horizon_hours"],
                    "emission_bucket": "Sinter_CO2_range_diagnostic",
                    "CO2_site_t_y": "",
                    "CO2_site_Mt_y": f"{item['sinter_CO2_BREF_low_site_Mt_y']}..{item['sinter_CO2_BREF_high_site_Mt_y']}",
                    "CO2_mode": "range_metadata_not_active_variant",
                    "included_in_objective_ETS_cost": "false",
                    "included_in_total_direct_CO2": "false",
                    "double_counting_risk": "not_active",
                    "status": "pass",
                    "notes": "BREF range, IPCC sanity and EU ETS benchmark are reported as diagnostics only.",
                },
            ]
        )
    return rows


def _steam_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration": row["configuration"],
            "horizon_hours": row["horizon_hours"],
            "steam_mode": SINTER_STEAM_MODE,
            "steam_supply_mode": STEAM_SUPPLY_MODE,
            "sinter_steam_demand_site_t_y": row["sinter_steam_demand_site_t_y"],
            "sinter_steam_proxy_supply_site_t_y": row["sinter_steam_proxy_supply_site_t_y"],
            "sinter_steam_unserved_site_t_y": row["sinter_steam_unserved_site_t_y"],
            "status": "pass" if abs(_zero(row["sinter_steam_demand_site_t_y"]) - _zero(row["sinter_steam_proxy_supply_site_t_y"])) <= TOL_T and _zero(row["sinter_steam_unserved_site_t_y"]) == 0.0 else "fail",
            "caveat": "active utility demand with proxy supply until governed steam network exists; candidate only; not Tata-validated",
        }
        for row in report
    ]


def _electricity_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration": row["configuration"],
            "horizon_hours": row["horizon_hours"],
            "ledger_scope": "process_electricity_demand",
            "component": "Sinter_Plant",
            "electricity_site_MWh_e_y": row["sinter_electricity_site_MWh_e_y"],
            "electricity_site_GWh_e_y": row["sinter_electricity_site_GWh_e_y"],
            "electricity_site_TWh_e_y": row["sinter_electricity_site_TWh_e_y"],
            "electricity_price_response_asset": "false",
            "DA_bidding_or_settlement_added": "false",
            "status": "process_electricity_demand_added",
            "notes": "Sinter electricity is mandatory process demand and is not a DA price-response asset.",
        }
        for row in report
    ]


def _material_route_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration": row["configuration"],
            "horizon_hours": row["horizon_hours"],
            "route": "BF_hot_metal_to_sinter_to_iron_ore_bus0",
            "bf_hot_metal_driver_site_t_y": row["bf_hot_metal_driver_site_t_y"],
            "sinter_per_t_hot_metal": row["sinter_per_t_hot_metal"],
            "sinter_output_site_t_y": row["sinter_output_site_t_y"],
            "sinter_iron_ore_bus0_input_site_t_y": row["sinter_iron_ore_bus0_input_site_t_y"],
            "sinter_output_t_per_t_iron_ore_bus0": row["sinter_output_t_per_t_iron_ore_bus0"],
            "status": "pass",
            "caveat": "output exceeds bus0 iron ore input because omitted raw-mix inputs are implicit",
        }
        for row in report
    ]


def _utility_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration": row["configuration"],
            "horizon_hours": row["horizon_hours"],
            "electricity_site_MWh_e_y": row["sinter_electricity_site_MWh_e_y"],
            "steam_demand_site_t_y": row["sinter_steam_demand_site_t_y"],
            "steam_proxy_supply_site_t_y": row["sinter_steam_proxy_supply_site_t_y"],
            "steam_unserved_site_t_y": row["sinter_steam_unserved_site_t_y"],
            "steam_supply_mode": STEAM_SUPPLY_MODE,
            "status": "pass",
        }
        for row in report
    ]


def _anchor_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in report:
        rows.extend(
            [
                {
                    "configuration": item["configuration"],
                    "horizon_hours": item["horizon_hours"],
                    "metric": "raw_MER_sinter_output_context",
                    "model_site_quantity": item["sinter_output_site_t_y"],
                    "anchor_quantity": item["raw_MER_sinter_anchor_site_t_y"],
                    "unit": "t/y",
                    "gap_quantity": item["raw_MER_sinter_gap_site_t_y"],
                    "gap_pct": item["raw_MER_sinter_gap_pct"],
                    "anchor_status": "validation_context_only",
                    "constraint_used": "false",
                    "notes": "Raw MER Sinter anchor is reported but not used as a dispatch constraint.",
                },
                {
                    "configuration": item["configuration"],
                    "horizon_hours": item["horizon_hours"],
                    "metric": "active_scale_sinter_output_expected_from_C5k_BF_HM",
                    "model_site_quantity": item["sinter_output_site_t_y"],
                    "anchor_quantity": item["active_scale_expected_sinter_site_t_y"],
                    "unit": "t/y",
                    "gap_quantity": item["active_scale_sinter_gap_site_t_y"],
                    "gap_pct": _fmt(_zero(item["active_scale_sinter_gap_site_t_y"]) / _zero(item["active_scale_expected_sinter_site_t_y"]) * 100.0 if _zero(item["active_scale_expected_sinter_site_t_y"]) else 0.0),
                    "anchor_status": "active_scale_equation_check",
                    "constraint_used": "false",
                    "notes": "Active-scale check follows C5k BF hot metal and the governed Sinter ratio.",
                },
            ]
        )
    return rows


def _summary_rows(report: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    rows: list[dict[str, Any]] = []
    by_horizon: dict[int, list[dict[str, Any]]] = {24: [], 168: []}
    for item in report:
        row = {
            "stage": STAGE,
            "configuration": item["configuration"],
            "horizon_hours": item["horizon_hours"],
            "solver_status": "deterministic_per_timestep_accounting_not_optimisation",
            "status": item["status"],
            "thesis_usability": item["thesis_usability"],
            "inherited_hsm_heat_case": item["inherited_hsm_heat_case"],
            "sinter_output_site_Mt_y": _fmt(_zero(item["sinter_output_site_t_y"]) / 1_000_000.0),
            "bf_hot_metal_driver_site_Mt_y": _fmt(_zero(item["bf_hot_metal_driver_site_t_y"]) / 1_000_000.0),
            "iron_ore_bus0_input_site_Mt_y": _fmt(_zero(item["sinter_iron_ore_bus0_input_site_t_y"]) / 1_000_000.0),
            "electricity_site_TWh_e_y": item["sinter_electricity_site_TWh_e_y"],
            "gas_demand_site_PJ_LHV_y": item["sinter_gas_demand_site_PJ_LHV_y"],
            "steam_demand_site_kt_y": item["sinter_steam_demand_site_kt_y"],
            "aggregate_CO2_site_Mt_y": item["sinter_aggregate_CO2_site_Mt_y"],
            "COG_to_Sinter_site_MWh_y": item["COG_to_Sinter_site_MWh_y"],
            "NG_to_Sinter_site_MWh_y": item["NG_to_Sinter_site_MWh_y"],
            "Sinter_gas_unserved_site_MWh_y": item["Sinter_gas_unserved_site_MWh_y"],
            "WAG_invariant_status": item["WAG_invariant_status"],
            "LHV_consistency_status": item["LHV_consistency_status"],
            "CO2_double_counting_guard_status": item["CO2_double_counting_guard_status"],
            "anchor_constraints_used": item["anchor_constraints_used"],
            "sinter_wag_production_flag": item["sinter_wag_production_flag"],
        }
        rows.append(row)
        by_horizon[int(item["horizon_hours"])].append(row)
    return rows, by_horizon


def _stage_gate(
    source_card_exists: bool,
    input_rows: list[dict[str, str]],
    hourly: list[dict[str, Any]],
    report: list[dict[str, Any]],
    controller: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    lhv: list[dict[str, Any]],
    co2: list[dict[str, Any]],
    steam: list[dict[str, Any]],
    electricity: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[Any] = []
    if not source_card_exists:
        failures.append("missing_sinter_source_card")
    failures.extend(
        row
        for row in input_rows
        if row["thesis_usability"] != "false"
        or row["human_review_required"] != "true"
        or row["codex_may_decide"] != "false"
        or row["constraint_used"] != "false"
    )
    params = _params(input_rows)
    if abs(_zero(params["SINTER_PER_T_HOT_METAL_C0"]) - SINTER_PER_T_HOT_METAL_C0) > 1e-6:
        failures.append("C0_sinter_ratio_changed")
    if abs(_zero(params["SINTER_PER_T_HOT_METAL_C1"]) - SINTER_PER_T_HOT_METAL_C1) > 1e-6:
        failures.append("C1_sinter_ratio_changed")
    for row in hourly:
        expected = _zero(row["bf_hot_metal_output_site_t"]) * _zero(row["sinter_per_t_hot_metal"])
        if abs(_zero(row["sinter_output_site_t"]) - expected) > TOL_T:
            failures.append(("hourly_sinter_equation_failed", row["configuration"], row["horizon_hours"], row["timestep"]))
    failures.extend(row for row in report if row["anchor_constraints_used"] != "0")
    failures.extend(row for row in report if row["sinter_wag_production_flag"] != "false")
    failures.extend(row for row in report if row["sinter_allowed_gas_carriers"] != "COG;NG")
    failures.extend(row for row in controller if row["status"] != "pass")
    failures.extend(row for row in controller if _zero(row["BFG_to_Sinter_site_MWh_y"]) != 0.0 or _zero(row["BOFG_to_Sinter_site_MWh_y"]) != 0.0)
    failures.extend(row for row in controller if abs(_zero(row["COG_to_Sinter_site_MWh_y"]) + _zero(row["NG_to_Sinter_site_MWh_y"]) - _zero(row["sinter_gas_demand_site_MWh_y"])) > WAG_TOL_MWH)
    failures.extend(row for row in controller if _zero(row["Sinter_gas_unserved_site_MWh_y"]) != 0.0)
    failures.extend(row for row in wag_aggregate if row["status"] != "pass")
    failures.extend(row for row in lhv if row["status"] != "pass")
    failures.extend(row for row in co2 if row["included_in_objective_ETS_cost"] != "false")
    failures.extend(row for row in co2 if row["emission_bucket"] == "Sinter_COG_NG_combustion_CO2" and row["included_in_total_direct_CO2"] != "false")
    failures.extend(row for row in steam if row["status"] != "pass")
    failures.extend(row for row in electricity if row["status"] != "process_electricity_demand_added")

    c0 = next(row for row in report if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    c1 = next(row for row in report if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    return {
        "stage": STAGE,
        "decision": "pass_development_sinter_minimal_parameterisation" if not failures else "fail_development_sinter_minimal_parameterisation",
        "output_directory": _rel(C5M_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "existing_pattern_audit_summary": PATTERN_AUDIT_SUMMARY,
        "source_card_exists": source_card_exists,
        "inherited_hsm_heat_case": HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
        "sensitivity_references_available": ["C5l_d_high_0_80", "C5l_c_uncapped_reference", "C5l_b_average_reheat"],
        "SINTER_STEAM_MODE": SINTER_STEAM_MODE,
        "SINTER_CO2_ACCOUNTING_MODE": SINTER_CO2_ACCOUNTING_MODE,
        "SINTER_PER_T_HOT_METAL_C0": SINTER_PER_T_HOT_METAL_C0,
        "SINTER_PER_T_HOT_METAL_C1": SINTER_PER_T_HOT_METAL_C1,
        "C0_24h_sinter_output_Mt_y": _zero(c0["sinter_output_site_t_y"]) / 1_000_000.0,
        "C1_24h_sinter_output_Mt_y": _zero(c1["sinter_output_site_t_y"]) / 1_000_000.0,
        "C0_24h_sinter_electricity_TWh_e_y": _zero(c0["sinter_electricity_site_TWh_e_y"]),
        "C1_24h_sinter_electricity_TWh_e_y": _zero(c1["sinter_electricity_site_TWh_e_y"]),
        "C0_24h_sinter_gas_PJ_LHV_y": _zero(c0["sinter_gas_demand_site_PJ_LHV_y"]),
        "C1_24h_sinter_gas_PJ_LHV_y": _zero(c1["sinter_gas_demand_site_PJ_LHV_y"]),
        "C0_24h_sinter_steam_kt_y": _zero(c0["sinter_steam_demand_site_kt_y"]),
        "C1_24h_sinter_steam_kt_y": _zero(c1["sinter_steam_demand_site_kt_y"]),
        "C0_24h_sinter_CO2_Mt_y": _zero(c0["sinter_aggregate_CO2_site_Mt_y"]),
        "C1_24h_sinter_CO2_Mt_y": _zero(c1["sinter_aggregate_CO2_site_Mt_y"]),
        "sinter_allowed_gas_carriers": list(SINTER_ALLOWED_GAS_CARRIERS),
        "sinter_wag_production_flag": SINTER_WAG_PRODUCTION_FLAG,
        "anchor_constraints_used": 0,
        "wag_invariant_fail_count": sum(1 for row in wag_aggregate if row["status"] != "pass"),
        "lhv_consistency_fail_count": sum(1 for row in lhv if row["status"] != "pass"),
        "co2_double_counting_guard_status": "pass" if all(row["included_in_objective_ETS_cost"] == "false" for row in co2) else "fail",
        "steam_proxy_supply_status": "pass" if all(row["status"] == "pass" for row in steam) else "fail",
        "site_process_electricity_ledger_update_status": "pass" if all(row["status"] == "process_electricity_demand_added" for row in electricity) else "fail",
        "C5l_d_base_0_50_inherited": HSM_HOT_CHARGE_CAP_ACTIVE_CASE == "base_0_50",
        "C5k_production_targets_and_route_split_changed": False,
        "C5j_BOF_coefficients_changed": False,
        "C5h_BF_hot_stove_convention_changed": False,
        "KGF_COG_self_use_convention_changed": False,
        "Sinter_ramp_or_DA_price_response_added": False,
        "ETS_objective_steering_added": False,
        "WAG_market_valuation_added": False,
        "WAG_export_revenue_added": False,
        "failure_count": len(failures),
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5h_blast_furnace_controller_parameterisation()
    run_s4_4c5k_production_policy_and_route_split_normalisation()
    run_s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch()
    C5M_DIR.mkdir(parents=True, exist_ok=True)

    input_rows_any = _development_input_rows()
    _write_csv(C5M_DIR / "s4_4c5m_sinter_development_input_rows.csv", input_rows_any, SINTER_PARAMETER_COLUMNS)
    input_rows = _read_csv(C5M_DIR / "s4_4c5m_sinter_development_input_rows.csv")
    params = _params(input_rows)

    c5k_report = _read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv")
    hourly = _hourly_rows(c5k_report, params)
    report = _aggregate_hourly(hourly, c5k_report, params)
    c5k_wag = _read_csv(C5K_DIR / "s4_4c5k_wag_generation_consumption_by_plant.csv")
    c5l_d_report = _read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv")
    controller, trace, allocation = _allocate_shared_wag(report, c5k_wag, c5l_d_report)
    wag_rows = _wag_generation_consumption_rows(c5k_wag, allocation)
    wag_aggregate = _wag_aggregate_rows(allocation)
    lhv = _lhv_rows(report, controller)
    report = _update_report_with_controller(report, controller, wag_aggregate, lhv)
    co2 = _co2_rows(report)
    steam = _steam_rows(report)
    electricity = _electricity_rows(report)
    material = _material_route_rows(report)
    utility = _utility_rows(report)
    anchors = _anchor_rows(report)
    summary_rows, by_horizon = _summary_rows(report)
    gate = _stage_gate(SOURCE_CARD.exists(), input_rows, hourly, report, controller, wag_aggregate, lhv, co2, steam, electricity)

    _write_json(C5M_DIR / "s4_4c5m_stage_gate.json", gate)
    _write_csv(
        C5M_DIR / "s4_4c5m_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5l_d_HSM_hot_charge_share_cap_and_reheat_sensitivity_patch",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5M_DIR / "s4_4c5m_source_candidate_evidence.csv", _source_candidate_rows(input_rows))
    _write_csv(C5M_DIR / "s4_4c5m_sinter_hourly_flows.csv", hourly)
    _write_csv(C5M_DIR / "s4_4c5m_sinter_report.csv", report)
    _write_csv(C5M_DIR / "s4_4c5m_sinter_material_route_dashboard.csv", material)
    _write_csv(C5M_DIR / "s4_4c5m_sinter_utility_dashboard.csv", utility)
    _write_csv(C5M_DIR / "s4_4c5m_sinter_steam_proxy_dashboard.csv", steam)
    _write_csv(C5M_DIR / "s4_4c5m_sinter_electricity_ledger.csv", electricity)
    _write_csv(C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv", controller)
    _write_csv(C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_trace.csv", trace)
    _write_csv(C5M_DIR / "s4_4c5m_wag_generation_consumption_by_plant.csv", wag_rows)
    _write_csv(C5M_DIR / "s4_4c5m_wag_aggregate_invariant.csv", wag_aggregate)
    _write_csv(C5M_DIR / "s4_4c5m_lhv_consistency_checks.csv", lhv)
    _write_csv(C5M_DIR / "s4_4c5m_sinter_co2_accounting_dashboard.csv", co2)
    _write_csv(C5M_DIR / "s4_4c5m_anchor_gap_dashboard.csv", anchors)
    _write_csv(C5M_DIR / "s4_4c5m_compact_table_for_chat.csv", summary_rows)
    for horizon, rows in by_horizon.items():
        _write_csv(C5M_DIR / f"s4_4c5m_{horizon}h_summary.csv", rows)
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "hourly": len(hourly),
            "report": len(report),
            "controller": len(controller),
            "wag_aggregate": len(wag_aggregate),
        },
    }
    _write_json(C5M_DIR / "s4_4c5m_summary.json", summary)
    return summary


def run_s4_4c5m_sinter_minimal_parameterisation() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5m_sinter_minimal_parameterisation(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
