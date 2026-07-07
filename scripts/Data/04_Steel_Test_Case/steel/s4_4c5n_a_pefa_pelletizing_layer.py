"""S4.4c5n_a PEFA / Pelletizing Plant physical-accounting layer.

This stage adds a development-only Pelletizing Plant accounting layer on top of
the current C5 plant stack. PEFA is production-coupled, not DA-responsive, and
does not produce useful WAG. The stage writes and then consumes explicit
development input rows so physical coefficients are visible in the governed C5
artifact pattern rather than silently embedded in the equations.
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
from .s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR
from .s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration import C5M_B_DIR
from .s4_4c5m_f_bounded_coke_reconciliation_sensitivity import (
    C5M_F_DIR,
    run_s4_4c5m_f_bounded_coke_reconciliation_sensitivity,
)
from .s4_4c5m_sinter_minimal_parameterisation import C5M_DIR


STAGE = "S4.4c5n_a_pefa_pelletizing_layer"
C5N_A_DIR = S4_ROOT / "s4_4c5n_a_pefa_pelletizing_layer"
SOURCE_CARD = "data/03_Optimisation/inputs/assets/steel/source_cards/PELLETIZING_Parameters.md"
DEPENDENCY_CHAIN = "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b -> C5m_c -> C5m_d -> C5m_e -> C5m_f -> C5n_a"
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_healthcheck_pattern;"
    "PEFA_coefficients_loaded_from_C5n_a_development_input_rows"
)

TOL = 1e-6
TOL_MWH = 1.0
PEFA_OPERATION_CLASS = "continuous_upstream_process_not_DA_responsive"
PEFA_ACTIVITY_MODE = "fixed_profile_scaled_to_active_target"
PEFA_CO2_MODE = "aggregate_diagnostic"
PEFA_STEAM_STATUS = "deferred_no_source"


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _bool(value: bool) -> str:
    return str(value).lower()


def _by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _by_key_carrier(rows: list[dict[str, str]]) -> dict[tuple[str, int, str], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"]), row["carrier"]): row for row in rows}


def _param_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["parameter_id"]: row for row in rows}


def _pefa_dev_rows() -> list[dict[str, Any]]:
    base = {
        "source_card": SOURCE_CARD,
        "input_status": "development_candidate",
        "thesis_usability": "false",
        "human_review_required": "true",
        "codex_may_decide": "false",
        "evidence_strength": "source_card_candidate_not_Tata_validated",
    }
    rows = [
        ("PEFA_OUTPUT_BASIS", "fired_pellets", "", "", "-", "activity basis", "Primary PEFA activity basis; not a numerical dispatch constraint."),
        ("PEFA_OPERATION_CLASS", PEFA_OPERATION_CLASS, "", "", "-", "policy", "Continuous upstream process, not DA responsive."),
        ("PEFA_ACTIVITY_MODE", PEFA_ACTIVITY_MODE, "", "", "-", "policy", "Fixed/profile-coupled development activity scaled with existing C5 target convention."),
        ("PEFA_IRON_ORE_INPUT_T_PER_T_PELLETS", 0.950, 0.935, 0.965, "t iron ore/t pellets", "material", "Main compact material conversion; additives deferred."),
        ("PEFA_ELECTRICITY_MWH_PER_T", 0.0213, 0.0150, 0.0275, "MWh_e/t pellets", "electricity", "Mandatory process electricity; not DA-responsive in this layer."),
        ("PEFA_GAS_FUEL_TOTAL_GJ_PER_T", 0.320, "", "", "GJ_LHV/t pellets", "gas_heat", "Option A total gas heat demand."),
        ("PEFA_COG_BOFG_ENERGY_GJ_PER_T", 0.306, "", "", "GJ_LHV/t pellets", "gas_heat_check", "Candidate evidence/check only; allocation remains eligibility constrained."),
        ("PEFA_NG_ENERGY_GJ_PER_T", 0.014, "", "", "GJ_LHV/t pellets", "gas_backup_check", "Candidate backup check; NG used only if eligible WAG is insufficient."),
        ("PEFA_COKE_BREEZE_OR_ANTHRACITE_GJ_PER_T", 0.342, "", "", "GJ/t pellets", "solid_fuel", "Solid-fuel diagnostic driver, not WAG."),
        ("PEFA_DIRECT_CO2_T_PER_T", 0.105, 0.017, 0.193, "tCO2/t pellets", "aggregate_CO2", "Midpoint development diagnostic; not ETS objective and not thesis truth."),
        ("PEFA_WASTE_GAS_FLOW_NM3_PER_T", 2170.0, 1940.0, 2400.0, "Nm3/t pellets", "waste_gas_reporting", "Reporting only; must not enter WAG balances."),
        ("PEFA_GROSS_ENERGY_GJ_PER_T", 1.4, "", "", "GJ/t pellets", "validation_check", "Validation/check only; includes recuperation and must not be added to fuel terms."),
        ("PEFA_HEAT_RECUPERATION_GJ_PER_T", 0.7, "", "", "GJ/t pellets", "deferred_validation", "Validation/deferred only; not dispatchable heat recovery."),
        ("PEFA_HOT_AIR_RECIRC_DUCT_GJ_PER_T", 0.0675, "", "", "GJ/t pellets", "deferred_validation", "Validation/deferred only; not a free flexibility source."),
        ("PEFA_MALERIJ_ALLOWED_FUELS", "BOFG;NG", "", "", "carrier_set", "controller_eligibility", "Malerij heat may use BOFG or NG only."),
        ("PEFA_BRANDERIJ_ALLOWED_FUELS", "COG;NG", "", "", "carrier_set", "controller_eligibility", "Branderij heat may use COG or NG only."),
        ("PEFA_BFG_ALLOWED", "false", "", "", "boolean", "controller_eligibility", "BFG is blocked for PEFA base implementation."),
        ("PEFA_DIRECT_WAG_MARKET_VALUE", "false", "", "", "boolean", "policy_forbidden", "No direct WAG market valuation."),
        ("PEFA_STAGE_GAS_SPLIT_REQUIRED", "false", "", "", "boolean", "controller_mode", "Option A uses total gas heat without fixed stage split."),
        ("PEFA_CO2_MODE", PEFA_CO2_MODE, "", "", "-", "CO2_policy", "Aggregate diagnostic only; fuel-explicit CO2 inactive."),
        ("PEFA_STEAM_STATUS", PEFA_STEAM_STATUS, "", "", "-", "utility_status", "No active PEFA steam demand without reviewed source."),
    ]
    return [
        {
            "parameter_id": pid,
            "base_value": value,
            "low_value": low,
            "high_value": high,
            "unit": unit,
            "parameter_group": group,
            "caveat": caveat,
            **base,
        }
        for pid, value, low, high, unit, group, caveat in rows
    ]


def _pefa_anchor_rows() -> list[dict[str, Any]]:
    return [
        {
            "configuration": C0,
            "anchor_id": "PEFA_C0_OUTPUT_ANNUAL_MT",
            "raw_anchor_Mt_y": 4.6,
            "operational_band_low_Mt_y": "",
            "operational_band_high_Mt_y": "",
            "MER_liquid_steel_context_Mt_y": 7.2,
            "anchor_status": "validation_anchor_not_dispatch_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "C0 raw MER anchor; scaled development activity uses existing C5 active-target convention.",
        },
        {
            "configuration": C1,
            "anchor_id": "PEFA_C1_OUTPUT_ANNUAL_MT",
            "raw_anchor_Mt_y": 5.0,
            "operational_band_low_Mt_y": 4.0,
            "operational_band_high_Mt_y": 5.0,
            "MER_liquid_steel_context_Mt_y": 6.8,
            "anchor_status": "validation_anchor_not_dispatch_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "C1 raw MER anchor and operational band; not an hourly ramp/flex constraint.",
        },
    ]


def _source_payload() -> dict[str, Any]:
    c5k = _by_key(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv"))
    totals = _by_key(_read_csv(C5M_B_DIR / "s4_4c5m_b_modelled_totals.csv"))
    wag = _by_key_carrier(_read_csv(C5M_B_DIR / "s4_4c5m_b_wag_carrier_ledger.csv"))
    sinter_ctrl = _by_key(_read_csv(C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv"))
    c5m_f_gate = json.loads((C5M_F_DIR / "s4_4c5m_f_stage_gate.json").read_text(encoding="utf-8"))
    pefa_params = _param_map(_read_csv(C5N_A_DIR / "s4_4c5n_a_pefa_development_input_rows.csv"))
    pefa_anchors = {row["configuration"]: row for row in _read_csv(C5N_A_DIR / "s4_4c5n_a_pefa_validation_anchors.csv")}
    return locals()


def _param_float(params: dict[str, dict[str, str]], parameter_id: str) -> float:
    return _zero(params[parameter_id]["base_value"])


def _param_text(params: dict[str, dict[str, str]], parameter_id: str) -> str:
    return params[parameter_id]["base_value"]


def _activity_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        anchor = payload["pefa_anchors"][config]
        raw_anchor = _zero(anchor["raw_anchor_Mt_y"]) * 1_000_000.0
        mer_context = _zero(anchor["MER_liquid_steel_context_Mt_y"]) * 1_000_000.0
        for horizon in HORIZONS:
            c5k = payload["c5k"][(config, horizon)]
            active_ls = _zero(c5k["active_total_liquid_steel_target_site_t_y"])
            output = raw_anchor * active_ls / mer_context if mer_context else 0.0
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "PEFA_OPERATION_CLASS": PEFA_OPERATION_CLASS,
                    "PEFA_ACTIVITY_MODE": PEFA_ACTIVITY_MODE,
                    "active_total_liquid_steel_target_site_t_y": _fmt(active_ls),
                    "raw_PEFA_output_anchor_site_t_y": _fmt(raw_anchor),
                    "scaled_PEFA_development_target_site_t_y": _fmt(output),
                    "PEFA_output_site_t_y": _fmt(output),
                    "raw_anchor_gap_t_y": _fmt(output - raw_anchor),
                    "raw_anchor_gap_pct": _fmt((output - raw_anchor) / raw_anchor * 100.0 if raw_anchor else 0.0),
                    "C1_operational_band_low_site_t_y": _fmt(_zero(anchor["operational_band_low_Mt_y"]) * 1_000_000.0) if config == C1 else "",
                    "C1_operational_band_high_site_t_y": _fmt(_zero(anchor["operational_band_high_Mt_y"]) * 1_000_000.0) if config == C1 else "",
                    "PEFA_DA_RESPONSIVE": "false",
                    "price_response_test_status": "not_applicable_no_PEFA_DA_mode_in_C5n_a",
                    "anchor_used_as_hourly_cap": "false",
                    "status": "development_only_scaled_anchor_activity",
                }
            )
    return rows


def _material_rows(payload: dict[str, Any], activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = payload["pefa_params"]
    ore_coeff = _param_float(params, "PEFA_IRON_ORE_INPUT_T_PER_T_PELLETS")
    rows: list[dict[str, Any]] = []
    for row in activity:
        output = _zero(row["PEFA_output_site_t_y"])
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "PEFA_output_site_t_y": _fmt(output),
                "PEFA_iron_ore_input_site_t_y": _fmt(output * ore_coeff),
                "PEFA_iron_ore_input_t_per_t_pellets": _fmt(ore_coeff),
                "fired_pellets_output_site_t_y": _fmt(output),
                "pellet_supply_demand_balance_status": "diagnostic_only_no_governed_BF_DRP_pellet_burden_balance",
                "pellet_supply_demand_gap_site_t_y": "",
                "deferred_material_details": "bentonite;olivine;limestone;dolomite;quartzite;moisture;pellet_quality",
            }
        )
    return rows


def _electricity_rows(payload: dict[str, Any], activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coeff = _param_float(payload["pefa_params"], "PEFA_ELECTRICITY_MWH_PER_T")
    rows: list[dict[str, Any]] = []
    for row in activity:
        key = (row["configuration"], int(row["horizon_hours"]))
        output = _zero(row["PEFA_output_site_t_y"])
        electricity = output * coeff
        old_total = _zero(payload["totals"][key]["new_process_electricity_including_BF_KGF_site_MWh_e_y"])
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "PEFA_output_site_t_y": row["PEFA_output_site_t_y"],
                "PEFA_electricity_MWh_per_t": _fmt(coeff),
                "PEFA_electricity_site_MWh_e_y": _fmt(electricity),
                "PEFA_electricity_site_TWh_e_y": _fmt(electricity / 1_000_000.0),
                "process_electricity_total_before_PEFA_MWh_e_y": _fmt(old_total),
                "process_electricity_total_after_PEFA_MWh_e_y": _fmt(old_total + electricity),
                "process_electricity_delta_PEFA_MWh_e_y": _fmt(electricity),
                "included_in_modelled_process_electricity_total": "true",
                "PEFA_DA_RESPONSIVE": "false",
            }
        )
    return rows


def _gas_controller_rows(payload: dict[str, Any], activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = payload["pefa_params"]
    gas_gj_per_t = _param_float(params, "PEFA_GAS_FUEL_TOTAL_GJ_PER_T")
    rows: list[dict[str, Any]] = []
    for row in activity:
        key = (row["configuration"], int(row["horizon_hours"]))
        ctrl = payload["sinter_ctrl"][key]
        output = _zero(row["PEFA_output_site_t_y"])
        demand_mwh = output * gas_gj_per_t / 3.6
        available_cog = max(_zero(ctrl["residual_COG_after_HSM_and_Sinter_site_MWh_y"]), 0.0)
        available_bofg = max(_zero(ctrl["residual_BOFG_after_HSM_and_Sinter_site_MWh_y"]), 0.0)
        available_total = available_cog + available_bofg
        wag_served = min(demand_mwh, available_total)
        if available_total > 0.0:
            bofg_to_malerij = wag_served * available_bofg / available_total
            cog_to_branderij = wag_served * available_cog / available_total
        else:
            bofg_to_malerij = 0.0
            cog_to_branderij = 0.0
        ng_backup = max(demand_mwh - wag_served, 0.0)
        ng_to_malerij = ng_backup * 0.5
        ng_to_branderij = ng_backup - ng_to_malerij
        malerij_heat = bofg_to_malerij + ng_to_malerij
        branderij_heat = cog_to_branderij + ng_to_branderij
        residual_cog = available_cog - cog_to_branderij
        residual_bofg = available_bofg - bofg_to_malerij
        balance_error = demand_mwh - malerij_heat - branderij_heat
        degenerate = (bofg_to_malerij <= TOL_MWH or cog_to_branderij <= TOL_MWH) and demand_mwh > TOL_MWH
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "controller_mode": "Option_A_total_gas_heat_eligibility_constrained_no_fixed_stage_split",
                "PEFA_gas_heat_demand_site_GJ_y": _fmt(output * gas_gj_per_t),
                "PEFA_gas_heat_demand_site_PJ_y": _fmt(output * gas_gj_per_t / 1_000_000.0),
                "PEFA_gas_heat_demand_site_MWh_y": _fmt(demand_mwh),
                "PEFA_malerij_heat_site_MWh_y": _fmt(malerij_heat),
                "PEFA_branderij_heat_site_MWh_y": _fmt(branderij_heat),
                "BOFG_to_PEFA_malerij_site_MWh_y": _fmt(bofg_to_malerij),
                "NG_to_PEFA_malerij_site_MWh_y": _fmt(ng_to_malerij),
                "COG_to_PEFA_branderij_site_MWh_y": _fmt(cog_to_branderij),
                "NG_to_PEFA_branderij_site_MWh_y": _fmt(ng_to_branderij),
                "BFG_to_PEFA_site_MWh_y": _fmt(0.0),
                "PEFA_NG_backup_site_MWh_y": _fmt(ng_backup),
                "PEFA_unserved_heat_site_MWh_y": _fmt(max(balance_error, 0.0)),
                "available_COG_before_PEFA_site_MWh_y": _fmt(available_cog),
                "available_BOFG_before_PEFA_site_MWh_y": _fmt(available_bofg),
                "residual_COG_after_PEFA_site_MWh_y": _fmt(residual_cog),
                "residual_BOFG_after_PEFA_site_MWh_y": _fmt(residual_bofg),
                "PEFA_STAGE_ALLOCATION_DEGENERATE_OR_IMPLAUSIBLE": _bool(degenerate),
                "PEFA_MALERIJ_ALLOWED_FUELS": _param_text(params, "PEFA_MALERIJ_ALLOWED_FUELS"),
                "PEFA_BRANDERIJ_ALLOWED_FUELS": _param_text(params, "PEFA_BRANDERIJ_ALLOWED_FUELS"),
                "PEFA_BFG_ALLOWED": _param_text(params, "PEFA_BFG_ALLOWED"),
                "PEFA_DIRECT_WAG_MARKET_VALUE": _param_text(params, "PEFA_DIRECT_WAG_MARKET_VALUE"),
                "PEFA_STAGE_GAS_SPLIT_REQUIRED": _param_text(params, "PEFA_STAGE_GAS_SPLIT_REQUIRED"),
                "heat_balance_error_MWh_y": _fmt(balance_error),
                "status": "pass" if abs(balance_error) <= TOL_MWH else "fail",
            }
        )
    return rows


def _solid_co2_waste_rows(payload: dict[str, Any], activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = payload["pefa_params"]
    solid_gj = _param_float(params, "PEFA_COKE_BREEZE_OR_ANTHRACITE_GJ_PER_T")
    co2 = _param_float(params, "PEFA_DIRECT_CO2_T_PER_T")
    waste = _param_float(params, "PEFA_WASTE_GAS_FLOW_NM3_PER_T")
    rows: list[dict[str, Any]] = []
    for row in activity:
        output = _zero(row["PEFA_output_site_t_y"])
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "PEFA_coke_breeze_or_anthracite_GJ_per_t": _fmt(solid_gj),
                "PEFA_coke_breeze_or_anthracite_site_GJ_y": _fmt(output * solid_gj),
                "PEFA_coke_breeze_or_anthracite_site_PJ_y": _fmt(output * solid_gj / 1_000_000.0),
                "PEFA_CO2_MODE": PEFA_CO2_MODE,
                "PEFA_direct_CO2_t_per_t": _fmt(co2),
                "PEFA_direct_CO2_range_low_t_per_t": payload["pefa_params"]["PEFA_DIRECT_CO2_T_PER_T"]["low_value"],
                "PEFA_direct_CO2_range_high_t_per_t": payload["pefa_params"]["PEFA_DIRECT_CO2_T_PER_T"]["high_value"],
                "PEFA_diagnostic_CO2_site_t_y": _fmt(output * co2),
                "PEFA_diagnostic_CO2_site_Mt_y": _fmt(output * co2 / 1_000_000.0),
                "PEFA_fuel_explicit_CO2_active": "false",
                "PEFA_CO2_double_count_guard_status": "pass",
                "PEFA_waste_gas_flow_Nm3_per_t": _fmt(waste),
                "PEFA_waste_gas_flow_site_Nm3_y": _fmt(output * waste),
                "PEFA_waste_gas_reporting_only": "true",
                "PEFA_waste_gas_in_WAG_balance": "false",
                "PEFA_useful_WAG_generation_MWh_y": _fmt(0.0),
                "waste_gas_caveat": "off-gas/emissions reporting only; not BFG, COG, BOFG, mixed WAG, or useful energy",
            }
        )
    return rows


def _modelled_total_delta_rows(
    payload: dict[str, Any],
    electricity: list[dict[str, Any]],
    gas: list[dict[str, Any]],
    co2_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    e = _by_key([{key: str(value) for key, value in row.items()} for row in electricity])
    g = _by_key([{key: str(value) for key, value in row.items()} for row in gas])
    c = _by_key([{key: str(value) for key, value in row.items()} for row in co2_rows])
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            before = payload["totals"][key]
            pefa_e = _zero(e[key]["PEFA_electricity_site_MWh_e_y"])
            pefa_co2 = _zero(c[key]["PEFA_diagnostic_CO2_site_t_y"])
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "process_electricity_before_PEFA_MWh_e_y": before["new_process_electricity_including_BF_KGF_site_MWh_e_y"],
                    "PEFA_electricity_delta_MWh_e_y": _fmt(pefa_e),
                    "process_electricity_after_PEFA_MWh_e_y": _fmt(_zero(before["new_process_electricity_including_BF_KGF_site_MWh_e_y"]) + pefa_e),
                    "diagnostic_CO2_before_PEFA_t_y": before["new_diagnostic_CO2_including_KGF_site_t_y"],
                    "PEFA_CO2_delta_t_y": _fmt(pefa_co2),
                    "diagnostic_CO2_after_PEFA_t_y": _fmt(_zero(before["new_diagnostic_CO2_including_KGF_site_t_y"]) + pefa_co2),
                    "PEFA_COG_consumption_MWh_y": g[key]["COG_to_PEFA_branderij_site_MWh_y"],
                    "PEFA_BOFG_consumption_MWh_y": g[key]["BOFG_to_PEFA_malerij_site_MWh_y"],
                    "PEFA_NG_backup_MWh_y": g[key]["PEFA_NG_backup_site_MWh_y"],
                    "PEFA_BFG_consumption_MWh_y": g[key]["BFG_to_PEFA_site_MWh_y"],
                    "HSM_heat_case": before["HSM_heat_case"],
                    "WAG_invariant_status_before_PEFA": before["WAG_invariant_status"],
                    "CO2_guard_status_before_PEFA": before["CO2_double_counting_guard_status"],
                    "status": "development_only_scope_expansion_due_to_PEFA_accounting",
                }
            )
    return rows


def _plant_healthcheck_rows(
    activity: list[dict[str, Any]],
    material: list[dict[str, Any]],
    electricity: list[dict[str, Any]],
    gas: list[dict[str, Any]],
    co2_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mat = _by_key([{key: str(value) for key, value in row.items()} for row in material])
    elec = _by_key([{key: str(value) for key, value in row.items()} for row in electricity])
    ctrl = _by_key([{key: str(value) for key, value in row.items()} for row in gas])
    co2 = _by_key([{key: str(value) for key, value in row.items()} for row in co2_rows])
    rows: list[dict[str, Any]] = []
    for row in activity:
        key = (row["configuration"], int(row["horizon_hours"]))
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_or_controller": "PEFA_Pelletizing_Plant",
                "stage_status": "development_only",
                "thesis_usability": "false",
                "activity_driver": "fired_pellets_output",
                "activity_driver_value": row["PEFA_output_site_t_y"],
                "raw_anchor_gap_t_y": row["raw_anchor_gap_t_y"],
                "material_inputs_summary": f"iron_ore={mat[key]['PEFA_iron_ore_input_site_t_y']}",
                "material_outputs_summary": f"fired_pellets={mat[key]['fired_pellets_output_site_t_y']}",
                "electricity_MWh_y": elec[key]["PEFA_electricity_site_MWh_e_y"],
                "gas_heat_MWh_y": ctrl[key]["PEFA_gas_heat_demand_site_MWh_y"],
                "solid_fuel_PJ_y": co2[key]["PEFA_coke_breeze_or_anthracite_site_PJ_y"],
                "BOFG_to_PEFA_malerij_MWh_y": ctrl[key]["BOFG_to_PEFA_malerij_site_MWh_y"],
                "COG_to_PEFA_branderij_MWh_y": ctrl[key]["COG_to_PEFA_branderij_site_MWh_y"],
                "BFG_to_PEFA_MWh_y": ctrl[key]["BFG_to_PEFA_site_MWh_y"],
                "NG_to_PEFA_MWh_y": _fmt(_zero(ctrl[key]["NG_to_PEFA_malerij_site_MWh_y"]) + _zero(ctrl[key]["NG_to_PEFA_branderij_site_MWh_y"])),
                "PEFA_unserved_heat_MWh_y": ctrl[key]["PEFA_unserved_heat_site_MWh_y"],
                "PEFA_steam_status": PEFA_STEAM_STATUS,
                "PEFA_waste_gas_status": co2[key]["waste_gas_caveat"],
                "PEFA_diagnostic_CO2_t_y": co2[key]["PEFA_diagnostic_CO2_site_t_y"],
                "PEFA_CO2_double_count_guard_status": co2[key]["PEFA_CO2_double_count_guard_status"],
                "PEFA_WAG_generation_MWh_y": co2[key]["PEFA_useful_WAG_generation_MWh_y"],
                "PEFA_DA_RESPONSIVE": row["PEFA_DA_RESPONSIVE"],
                "price_response_test_status": row["price_response_test_status"],
                "red_flags": _healthcheck_redflag_string(ctrl[key], co2[key], row),
                "failure_count": _healthcheck_failure_count(ctrl[key], co2[key], row),
            }
        )
    return rows


def _healthcheck_redflag_string(ctrl: dict[str, str], co2: dict[str, str], activity: dict[str, Any]) -> str:
    flags = _healthcheck_flags(ctrl, co2, activity)
    return ";".join(name for name, value in flags.items() if value)


def _healthcheck_failure_count(ctrl: dict[str, str], co2: dict[str, str], activity: dict[str, Any]) -> int:
    return sum(1 for value in _healthcheck_flags(ctrl, co2, activity).values() if value)


def _healthcheck_flags(ctrl: dict[str, str], co2: dict[str, str], activity: dict[str, Any]) -> dict[str, bool]:
    return {
        "PEFA_BFG_USED": _zero(ctrl["BFG_to_PEFA_site_MWh_y"]) > TOL_MWH,
        "PEFA_WAG_GENERATION_NONZERO": _zero(co2["PEFA_useful_WAG_generation_MWh_y"]) > TOL_MWH,
        "PEFA_WASTE_GAS_IN_WAG_BALANCE": co2["PEFA_waste_gas_in_WAG_balance"] != "false",
        "PEFA_UNSERVED_HEAT": _zero(ctrl["PEFA_unserved_heat_site_MWh_y"]) > TOL_MWH,
        "PEFA_CO2_DOUBLE_COUNT": co2["PEFA_CO2_double_count_guard_status"] != "pass",
        "PEFA_ACTIVITY_PRICE_RESPONSIVE": activity["PEFA_DA_RESPONSIVE"] != "false",
        "PEFA_ANCHOR_USED_AS_HOURLY_CAP": activity["anchor_used_as_hourly_cap"] != "false",
        "PEFA_STAGE_ALLOCATION_DEGENERATE_OR_IMPLAUSIBLE": ctrl["PEFA_STAGE_ALLOCATION_DEGENERATE_OR_IMPLAUSIBLE"] != "false",
        "PEFA_STEAM_SILENTLY_UNMODELLED": PEFA_STEAM_STATUS == "",
    }


def _redflag_rows(health: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in health:
        flags = {name: name in str(row["red_flags"]).split(";") for name in [
            "PEFA_BFG_USED",
            "PEFA_WAG_GENERATION_NONZERO",
            "PEFA_WASTE_GAS_IN_WAG_BALANCE",
            "PEFA_UNSERVED_HEAT",
            "PEFA_CO2_DOUBLE_COUNT",
            "PEFA_ACTIVITY_PRICE_RESPONSIVE",
            "PEFA_ANCHOR_USED_AS_HOURLY_CAP",
            "PEFA_STAGE_ALLOCATION_DEGENERATE_OR_IMPLAUSIBLE",
            "PEFA_STEAM_SILENTLY_UNMODELLED",
        ]}
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                **{name: _bool(value) for name, value in flags.items()},
                "failure_count": row["failure_count"],
                "status": "pass" if int(row["failure_count"]) == 0 else "fail",
            }
        )
    return rows


def _stage_gate(redflags: list[dict[str, Any]], deltas: list[dict[str, Any]]) -> dict[str, Any]:
    failure_count = sum(int(row["failure_count"]) for row in redflags)
    return {
        "stage": STAGE,
        "decision": "pass_development_pefa_pelletizing_layer" if failure_count == 0 else "fail_development_pefa_pelletizing_layer",
        "output_directory": _rel(C5N_A_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "failure_count": failure_count,
        "PEFA_active_configurations": list(CONFIGS),
        "PEFA_WAG_generation_expected_zero": True,
        "PEFA_BFG_allowed": False,
        "PEFA_waste_gas_reporting_only": True,
        "PEFA_CO2_mode": PEFA_CO2_MODE,
        "PEFA_process_electricity_delta_MWh_y_C0_24h": next(
            row["PEFA_electricity_delta_MWh_e_y"] for row in deltas if row["configuration"] == C0 and int(row["horizon_hours"]) == 24
        ),
        "PEFA_process_electricity_delta_MWh_y_C1_24h": next(
            row["PEFA_electricity_delta_MWh_e_y"] for row in deltas if row["configuration"] == C1 and int(row["horizon_hours"]) == 24
        ),
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5m_f_bounded_coke_reconciliation_sensitivity()
    C5N_A_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(C5N_A_DIR / "s4_4c5n_a_pefa_development_input_rows.csv", _pefa_dev_rows())
    _write_csv(C5N_A_DIR / "s4_4c5n_a_pefa_validation_anchors.csv", _pefa_anchor_rows())

    payload = _source_payload()
    activity = _activity_rows(payload)
    material = _material_rows(payload, activity)
    electricity = _electricity_rows(payload, activity)
    gas = _gas_controller_rows(payload, activity)
    solid_co2_waste = _solid_co2_waste_rows(payload, activity)
    deltas = _modelled_total_delta_rows(payload, electricity, gas, solid_co2_waste)
    health = _plant_healthcheck_rows(activity, material, electricity, gas, solid_co2_waste)
    redflags = _redflag_rows(health)
    gate = _stage_gate(redflags, deltas)

    _write_json(C5N_A_DIR / "s4_4c5n_a_stage_gate.json", gate)
    _write_csv(
        C5N_A_DIR / "s4_4c5n_a_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5m_f_bounded_coke_reconciliation_sensitivity",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5N_A_DIR / "s4_4c5n_a_pefa_activity_report.csv", activity)
    _write_csv(C5N_A_DIR / "s4_4c5n_a_pefa_material_ledger.csv", material)
    _write_csv(C5N_A_DIR / "s4_4c5n_a_pefa_electricity_ledger.csv", electricity)
    _write_csv(C5N_A_DIR / "s4_4c5n_a_pefa_gas_controller_dashboard.csv", gas)
    _write_csv(C5N_A_DIR / "s4_4c5n_a_pefa_solid_fuel_co2_waste_gas.csv", solid_co2_waste)
    _write_csv(C5N_A_DIR / "s4_4c5n_a_modelled_totals_delta.csv", deltas)
    _write_csv(C5N_A_DIR / "s4_4c5n_a_pefa_compact_healthcheck.csv", health)
    _write_csv(C5N_A_DIR / "s4_4c5n_a_red_flags.csv", redflags)
    _write_csv(C5N_A_DIR / "s4_4c5n_a_compact_table_for_chat.csv", deltas)
    _write_json(
        C5N_A_DIR / "s4_4c5n_a_pefa_pelletizing_report.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "development_inputs": _pefa_dev_rows(),
            "validation_anchors": _pefa_anchor_rows(),
            "activity": activity,
            "material": material,
            "electricity": electricity,
            "gas_controller": gas,
            "solid_fuel_co2_waste_gas": solid_co2_waste,
            "modelled_totals_delta": deltas,
            "healthcheck": health,
            "red_flags": redflags,
        },
    )
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "development_inputs": len(_pefa_dev_rows()),
            "activity": len(activity),
            "material": len(material),
            "electricity": len(electricity),
            "gas": len(gas),
            "health": len(health),
            "redflags": len(redflags),
        },
    }
    _write_json(C5N_A_DIR / "s4_4c5n_a_summary.json", summary)
    return summary


def run_s4_4c5n_a_pefa_pelletizing_layer() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5n_a_pefa_pelletizing_layer(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
