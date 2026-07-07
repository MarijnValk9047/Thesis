"""S4.4c5a anchor, scaling, and accounting correction reports."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .s4_4c5_physical_diagnostics import (
    C0,
    C1,
    C5_DIR,
    CANDIDATE_REGISTER,
    REPO_ROOT,
    SOURCE_REGISTER,
    _read_rows,
    _safe_float,
    _sum,
    _write_csv,
    _write_json,
)
from .s4_4c_unified_physical_modelbuilder import (
    FLARING_CO2_DIAGNOSTIC_EUR_PER_T,
    SELECTED_WAG_LHV_MJ_PER_NM3,
    VATTENFALL_IJM01_WAG_CAP_NM3_H,
    VATTENFALL_TOTAL_WAG_CAP_NM3_H,
    VATTENFALL_VELSEN25_WAG_CAP_NM3_H,
)


S4_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4"
C5A_DIR = S4_ROOT / "s4_4c5a_anchor_scaling_accounting_correction"
PJ_TO_MWH = 277_777.77777777775
TWH_TO_MWH = 1_000_000.0
NG_HHV_MJ_PER_NM3 = 39.8
SELECTED_PRODUCTION_ANCHOR_T_Y = 6_750_000.0
PREVIOUS_C5_PRODUCTION_ANCHOR_T_Y = 7_200_000.0
TOLERANCE = 1e-6


ATHANASIADIS_ANCHORS: dict[str, dict[str, dict[str, Any]]] = {
    C0: {
        "natural_gas": {
            "anchor_value": 33_243.63,
            "unit": "Nm3/h",
            "source": "Athanasiadis Table 8 p.96",
            "basis": "C0 average natural gas validation target; HHV accounting.",
        },
        "co2_total": {
            "anchor_value": 13_365_216.16,
            "unit": "tCO2/y",
            "source": "Athanasiadis Table 8 p.96",
            "basis": "C0 annual CO2 validation target.",
        },
        "electricity_total": {
            "anchor_value": 3.17 * TWH_TO_MWH,
            "unit": "MWh/y",
            "source": "Athanasiadis Table 8 p.96",
            "basis": "C0 annual electricity total validation target.",
        },
        "wag_electricity": {
            "anchor_value": 2.74 * TWH_TO_MWH,
            "unit": "MWh/y",
            "source": "Athanasiadis Table 8 p.96",
            "basis": "C0 annual WAG electricity/generation-context validation target.",
        },
    },
    C1: {
        "natural_gas": {
            "anchor_value": 151_673.52,
            "unit": "Nm3/h",
            "source": "Athanasiadis Table 9 p.101; addendum row S33I-ATH-GAS-013",
            "basis": "C1 average natural gas validation target; HHV accounting.",
        },
        "co2_total": {
            "anchor_value": 9_107_793.17,
            "unit": "tCO2/y",
            "source": "Athanasiadis Table 9 p.101; addendum row S33I-ATH-GAS-013",
            "basis": "C1 annual CO2 validation target.",
        },
        "electricity_total": {
            "anchor_value": 4.89 * TWH_TO_MWH,
            "unit": "MWh/y",
            "source": "Athanasiadis Table 9 p.101; addendum row S33I-ATH-GAS-013",
            "basis": "C1 annual electricity total validation target.",
        },
        "wag_electricity": {
            "anchor_value": 1.23 * TWH_TO_MWH,
            "unit": "MWh/y",
            "source": "Athanasiadis Table 9 p.101; addendum row S33I-ATH-GAS-013",
            "basis": "C1 annual WAG electricity/generation-context validation target.",
        },
    },
}

FIGURE_91_DIRECTIONAL_ERRORS = {
    "co2": 9.06,
    "natural_gas": 7.11,
    "coal": 7.68,
    "wag_electricity": 9.72,
}


def _read_csv(name: str) -> list[dict[str, str]]:
    return _read_rows(C5_DIR / name)


def _write_stage_gate(decision: str, caveat: str) -> dict[str, Any]:
    gate = {
        "stage": "S4.4c5a_anchor_scaling_accounting_correction",
        "decision": decision,
        "raw_pdf_inspected": False,
        "anchors_are_constraints": False,
        "optimiser_outputs_forced_to_match_anchors": False,
        "da_bidding_or_economics_added": False,
        "thesis_usable": False,
        "Tata_validated": False,
        "caveat": caveat,
    }
    _write_json(C5A_DIR / "s4_4c5a_stage_gate.json", gate)
    _write_csv(C5A_DIR / "s4_4c5a_stage_gate.csv", [gate])
    return gate


def _source_support_summary() -> dict[str, Any]:
    source_rows = _read_rows(SOURCE_REGISTER)
    candidate_rows = _read_rows(CANDIDATE_REGISTER)
    addendum_rows = _read_rows(REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_evidence/athanasiadis_gas_network_source_card_addendum.csv")
    return {
        "badarinath_source_card_present": any(row.get("source_card_id") == "S3_4_GUARDRAIL_BADARINATH_2025" for row in source_rows),
        "badarinath_6_75_candidate_present": any("6.75" in json.dumps(row) or "6750000" in json.dumps(row) for row in candidate_rows),
        "athanasiadis_master_source_card_present": any(row.get("source_card_id") == "STEEL-SC-0021" for row in source_rows),
        "athanasiadis_table9_addendum_present": any("Table 9" in json.dumps(row) for row in addendum_rows),
        "athanasiadis_table8_register_present": any("Table 8" in json.dumps(row) for row in candidate_rows + addendum_rows),
    }


def _production_anchor_rows() -> list[dict[str, Any]]:
    support = _source_support_summary()
    return [
        {
            "anchor_id": "production_anchor_previous_c5",
            "value_t_y": PREVIOUS_C5_PRODUCTION_ANCHOR_T_Y,
            "status": "superseded_for_c5a_validation_scaling",
            "source_basis": "legacy C5 diagnostic scale assumption",
            "source_support_status": "used_in_prior_C5_only",
            "selected": False,
            "caveat": "Kept as conflict/history row to avoid silent scale drift.",
        },
        {
            "anchor_id": "production_anchor_selected_c5a",
            "value_t_y": SELECTED_PRODUCTION_ANCHOR_T_Y,
            "status": "selected_development_validation_anchor",
            "source_basis": "Badarinath-compatible full-site production scale from user C5a correction decision",
            "source_support_status": "Badarinath source card present; exact 6.75 Mt/y value not found in candidate register"
            if support["badarinath_source_card_present"] and not support["badarinath_6_75_candidate_present"]
            else "registered",
            "selected": True,
            "caveat": "Development validation scaling anchor only; not Tata-validated and not an optimiser constraint.",
        },
    ]


def _anchor_table_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    support = _source_support_summary()
    for config_id, anchors in ATHANASIADIS_ANCHORS.items():
        for metric, anchor in anchors.items():
            value = anchor["anchor_value"]
            extra: dict[str, Any] = {}
            if metric == "natural_gas":
                nm3_h = value
                nm3_y = nm3_h * 8760.0
                pj_hhv_y = nm3_y * NG_HHV_MJ_PER_NM3 / 1_000_000_000.0
                extra = {
                    "anchor_nm3_h": round(nm3_h, 6),
                    "anchor_nm3_y": round(nm3_y, 6),
                    "anchor_pj_hhv_y": round(pj_hhv_y, 6),
                    "anchor_mwh_hhv_y": round(pj_hhv_y * PJ_TO_MWH, 6),
                    "hhv_lhv_basis_note": "NG uses HHV 39.8 MJ/Nm3; WAG balances remain LHV.",
                }
            rows.append(
                {
                    "configuration_id": config_id,
                    "anchor_metric": metric,
                    "anchor_value": value,
                    "unit": anchor["unit"],
                    "source_locator": anchor["source"],
                    "basis": anchor["basis"],
                    "source_card_id": "STEEL-SC-0021",
                    "register_support_status": "source_card_present_addendum_present"
                    if support["athanasiadis_table9_addendum_present"] or config_id == C0
                    else "source_card_present_prompt_supplied_locator",
                    "validation_target_only": True,
                    "constraint_or_objective_input": False,
                    "thesis_usable": False,
                    "caveat": "Athanasiadis/model-derived validation target; not Tata-measured truth.",
                    **extra,
                }
            )
    return rows


def _config_rows(horizon: str) -> list[dict[str, str]]:
    return _read_csv(f"s4_4c5_{horizon}_report.csv")


def _hourly_rows(horizon: str) -> list[dict[str, str]]:
    return _read_csv(f"s4_4c5_{horizon}_hourly_dispatch_c0.csv") + _read_csv(f"s4_4c5_{horizon}_hourly_dispatch_c1.csv")


def _plant_rows(horizon: str) -> list[dict[str, str]]:
    return _read_csv(f"s4_4c5_{horizon}_plant_diagnostics.csv")


def _scale_rows(horizon: str, horizon_hours: int) -> list[dict[str, Any]]:
    rows = []
    for row in _config_rows(horizon):
        production = _safe_float(row["final_product_fulfilled_t"])
        annualised = production * 8760.0 / horizon_hours
        scale = annualised / SELECTED_PRODUCTION_ANCHOR_T_Y
        if abs(scale - 1.0) <= 0.05:
            mode = "site_scale"
        elif scale < 0.75:
            mode = "module_scale"
        else:
            mode = "diagnostic_scale"
        rows.append(
            {
                "horizon": horizon,
                "configuration_id": row["configuration_id"],
                "model_production_t": round(production, 6),
                "model_annualised_production_t_y": round(annualised, 6),
                "selected_full_site_anchor_t_y": SELECTED_PRODUCTION_ANCHOR_T_Y,
                "previous_c5_anchor_t_y": PREVIOUS_C5_PRODUCTION_ANCHOR_T_Y,
                "production_scale_factor": round(scale, 9),
                "scale_mode": mode,
                "anchor_mix_allowed": False,
                "caveat": "Module-scale output; full-site anchors must be production-scaled or model outputs must be scaled up for validation only.",
            }
        )
    return rows


def _annualised(value: float, horizon_hours: int) -> float:
    return value * 8760.0 / horizon_hours


def _full_site_scaled(value: float, scale_factor: float) -> float:
    return value / scale_factor if scale_factor else 0.0


def _model_metric(config_id: str, horizon: str, metric: str, horizon_hours: int) -> tuple[float, str, str]:
    rows = [row for row in _hourly_rows(horizon) if row["configuration_id"] == config_id]
    plant_rows = [row for row in _plant_rows(horizon) if row["configuration_id"] == config_id]
    if metric == "electricity_total":
        value = _sum(rows, "gross_electricity_mwh")
        return _annualised(value, horizon_hours), "diagnostic_comparable_with_scale_caveat", "Current C5 model gross electricity proxy; not a forced anchor."
    if metric == "wag_electricity":
        value = _sum(rows, "wag_electricity_mwh")
        return _annualised(value, horizon_hours), "diagnostic_comparable", "Mode B internal WAG electricity, no revenue/export."
    if metric == "natural_gas":
        # Report process NG volume only. Boiler NG is stored as LHV MWh and kept separate.
        value = _sum(rows, "natural_gas_nm3")
        nm3_y = _annualised(value, horizon_hours)
        comparable = "partial_process_ng_only" if value > TOLERANCE else "not_comparable_no_process_ng_volume"
        return nm3_y / 8760.0, comparable, "Process natural gas volume average; boiler NG LHV placeholder kept separate."
    if metric == "co2_total":
        flaring = _sum(rows, "flaring_co2_t")
        drp_process = sum(_safe_float(row.get("process_co2_t")) for row in plant_rows if row.get("plant_id") == "DRP")
        value = flaring + drp_process
        return _annualised(value, horizon_hours), "partial_not_comparable_to_total", "Partial CO2 only: DRP process proxy plus flaring; BF/BOF and boiler combustion CO2 not fully represented."
    return 0.0, "not_mapped", "Metric not mapped."


def _validation_dashboard_rows(horizon: str, horizon_hours: int) -> list[dict[str, Any]]:
    scale_lookup = {row["configuration_id"]: row for row in _scale_rows(horizon, horizon_hours)}
    rows: list[dict[str, Any]] = []
    for config_id, anchors in ATHANASIADIS_ANCHORS.items():
        scale = _safe_float(scale_lookup[config_id]["production_scale_factor"])
        for metric, anchor in anchors.items():
            annualised_value, comparable, caveat = _model_metric(config_id, horizon, metric, horizon_hours)
            full_site_scaled_value = _full_site_scaled(annualised_value, scale)
            anchor_value = anchor["anchor_value"]
            if metric == "natural_gas":
                # Natural-gas anchor is average Nm3/h, and model metric is annual average Nm3/h.
                gap_abs = full_site_scaled_value - anchor_value
            else:
                gap_abs = full_site_scaled_value - anchor_value
            gap_pct = gap_abs / anchor_value * 100.0 if anchor_value else 0.0
            rows.append(
                {
                    "horizon": horizon,
                    "configuration_id": config_id,
                    "metric": metric,
                    "module_annualised_value": round(annualised_value, 6),
                    "full_site_scaled_model_value": round(full_site_scaled_value, 6),
                    "anchor_value": round(anchor_value, 6),
                    "unit": anchor["unit"],
                    "gap_absolute": round(gap_abs, 6),
                    "gap_percent": round(gap_pct, 6),
                    "production_scale_factor": round(scale, 9),
                    "scale_mode": scale_lookup[config_id]["scale_mode"],
                    "basis_source": anchor["source"],
                    "comparable": comparable,
                    "figure91_directional_error_percent": FIGURE_91_DIRECTIONAL_ERRORS.get(
                        "natural_gas" if metric == "natural_gas" else "co2" if metric == "co2_total" else "wag_electricity" if metric == "wag_electricity" else "",
                        "",
                    ),
                    "figure91_use": "directional_check_only" if metric in {"natural_gas", "co2_total", "wag_electricity"} else "",
                    "caveat": caveat,
                }
            )
    return rows


def _ng_accounting_rows(horizon: str, horizon_hours: int) -> list[dict[str, Any]]:
    rows = []
    for config_id in (C0, C1):
        hourly = [row for row in _hourly_rows(horizon) if row["configuration_id"] == config_id]
        ng_nm3 = _sum(hourly, "natural_gas_nm3")
        ng_nm3_y = _annualised(ng_nm3, horizon_hours)
        pj_hhv_y = ng_nm3_y * NG_HHV_MJ_PER_NM3 / 1_000_000_000.0
        boiler_lhv = _sum(hourly, "natural_gas_boiler_mwh")
        rows.append(
            {
                "horizon": horizon,
                "configuration_id": config_id,
                "process_ng_nm3_h_average": round(ng_nm3 / horizon_hours, 6),
                "process_ng_nm3_y_annualised": round(ng_nm3_y, 6),
                "process_ng_pj_hhv_y": round(pj_hhv_y, 6),
                "process_ng_mwh_hhv_y": round(pj_hhv_y * PJ_TO_MWH, 6),
                "boiler_ng_model_mwh_lhv_horizon": round(boiler_lhv, 6),
                "boiler_ng_hhv_conversion_status": "not_converted_missing_LHV_HHV_ratio_policy",
                "ng_hhv_mj_per_nm3": NG_HHV_MJ_PER_NM3,
                "wag_energy_basis": "LHV",
                "comparison_allowed": "only within labelled HHV/LHV basis",
                "caveat": "Do not compare HHV NG directly to LHV WAG without labelled conversion.",
            }
        )
    return rows


def _electricity_accounting_rows(horizon: str, horizon_hours: int) -> list[dict[str, Any]]:
    rows = []
    scale_lookup = {row["configuration_id"]: row for row in _scale_rows(horizon, horizon_hours)}
    for config_id in (C0, C1):
        hourly = [row for row in _hourly_rows(horizon) if row["configuration_id"] == config_id]
        plants = [row for row in _plant_rows(horizon) if row["configuration_id"] == config_id]
        variable = sum(
            _safe_float(row.get("electricity_use_mwh"))
            for row in plants
            if row.get("electricity_use_mwh") not in {"", "not_modelled_separately", None}
        )
        c5_gross = _sum(hourly, "gross_electricity_mwh")
        wag_electricity = _sum(hourly, "wag_electricity_mwh")
        scale = _safe_float(scale_lookup[config_id]["production_scale_factor"])
        anchor = ATHANASIADIS_ANCHORS[config_id]["electricity_total"]["anchor_value"]
        module_anchor = anchor * scale
        residual = module_anchor - _annualised(variable, horizon_hours)
        gross_proxy = _annualised(variable, horizon_hours) + max(residual, 0.0)
        net_proxy = gross_proxy - _annualised(wag_electricity, horizon_hours)
        current_full_site_gap = _full_site_scaled(_annualised(c5_gross, horizon_hours), scale) - anchor
        rows.append(
            {
                "horizon": horizon,
                "configuration_id": config_id,
                "modelled_variable_electricity_only_mwh_y": round(_annualised(variable, horizon_hours), 6),
                "residual_background_electricity_load_diagnostic_mwh_y": round(residual, 6),
                "gross_site_electricity_demand_proxy_mwh_y": round(gross_proxy, 6),
                "current_c5_gross_electricity_proxy_mwh_y": round(_annualised(c5_gross, horizon_hours), 6),
                "WAG_electricity_generation_mwh_y": round(_annualised(wag_electricity, horizon_hours), 6),
                "net_grid_import_proxy_mwh_y": round(net_proxy, 6),
                "electricity_anchor_gap_current_c5_full_site_scaled_mwh_y": round(current_full_site_gap, 6),
                "production_scale_factor": round(scale, 9),
                "residual_load_in_optimizer": False,
                "caveat": "Residual background load is diagnostic only and is not added to optimiser constraints.",
            }
        )
    return rows


def _enhanced_plant_rows(horizon: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base = _plant_rows(horizon)
    hourly = _hourly_rows(horizon)
    for row in base:
        rows.append(
            {
                **row,
                "component_type": "process_plant",
                "throughput_value": row["activity_t_h"],
                "throughput_unit": "t/h_or_t_input/h",
                "accounting_status": "existing_c5_process_row",
            }
        )
    for row in hourly:
        bfg_to_boiler = _safe_float(row.get("BFG_to_boiler_mwh"))
        cog_to_boiler = _safe_float(row.get("COG_to_boiler_mwh"))
        ng_boiler = _safe_float(row.get("natural_gas_boiler_mwh"))
        steam = _safe_float(row.get("steam"))
        bfg_to_vattenfall = _safe_float(row.get("BFG_to_vattenfall_mwh"))
        cog_to_vattenfall = _safe_float(row.get("COG_to_vattenfall_mwh"))
        bofg_to_vattenfall = _safe_float(row.get("BOFG_to_vattenfall_mwh"))
        bfg_flared = _safe_float(row.get("BFG_flared_mwh"))
        cog_flared = _safe_float(row.get("COG_flared_mwh"))
        bofg_flared = _safe_float(row.get("BOFG_flared_mwh"))
        bfg_kgf1 = _safe_float(row.get("BFG_to_KGF1_mwh"))
        cog_kgf1 = _safe_float(row.get("COG_to_KGF1_mwh"))
        total_vattenfall = bfg_to_vattenfall + cog_to_vattenfall + bofg_to_vattenfall
        volume = sum(
            value / (SELECTED_WAG_LHV_MJ_PER_NM3[carrier] / 3600.0)
            for carrier, value in (
                ("BFG", bfg_to_vattenfall),
                ("COG", cog_to_vattenfall),
                ("BOFG", bofg_to_vattenfall),
            )
        )
        common = {
            "horizon": horizon,
            "hour_index": row["hour_index"],
            "configuration_id": row["configuration_id"],
            "activity_or_on_state": 1,
            "material_input_t": "",
            "material_output_t": "",
            "electricity_use_mwh": 0.0,
            "natural_gas_use_nm3": "",
            "oxygen_use_t": "",
            "process_co2_t": "",
            "combustion_co2_t": "not_modelled",
            "schedule_status": "fixed_development_accounting_node",
        }
        rows.extend(
            [
                {
                    **common,
                    "plant_id": "KGF1_WAG_mixing_station",
                    "component_type": "mixing_station_accounting_node",
                    "activity_t_h": round(bfg_kgf1 + cog_kgf1, 6),
                    "throughput_value": round(bfg_kgf1 + cog_kgf1, 6),
                    "throughput_unit": "MWh_LHV/h",
                    "steam_or_boiler_use_mwh": 0.0,
                    "BFG_generated_mwh": 0.0,
                    "COG_generated_mwh": 0.0,
                    "BOFG_generated_mwh": 0.0,
                    "BFG_consumed_mwh": round(bfg_kgf1, 6),
                    "COG_consumed_mwh": round(cog_kgf1, 6),
                    "BOFG_consumed_mwh": 0.0,
                    "WAG_to_electricity_mwh": 0.0,
                    "BFG_flared_mwh": 0.0,
                    "COG_flared_mwh": 0.0,
                    "BOFG_flared_mwh": 0.0,
                    "flaring_co2_t": 0.0,
                    "capacity_utilisation": "",
                    "accounting_status": "reported_accounting_node_not_separate_pyomo_asset",
                    "caveat": "Mixing station is algebraic/reporting split; not a separate optimisation asset.",
                },
                {
                    **common,
                    "plant_id": "BoilerSteamUtility",
                    "component_type": "boiler_steam_placeholder",
                    "activity_t_h": round(bfg_to_boiler + cog_to_boiler + ng_boiler, 6),
                    "throughput_value": round(steam, 6),
                    "throughput_unit": "MWh_steam_proxy/h",
                    "steam_or_boiler_use_mwh": round(steam, 6),
                    "BFG_generated_mwh": 0.0,
                    "COG_generated_mwh": 0.0,
                    "BOFG_generated_mwh": 0.0,
                    "BFG_consumed_mwh": round(bfg_to_boiler, 6),
                    "COG_consumed_mwh": round(cog_to_boiler, 6),
                    "BOFG_consumed_mwh": 0.0,
                    "WAG_to_electricity_mwh": 0.0,
                    "BFG_flared_mwh": 0.0,
                    "COG_flared_mwh": 0.0,
                    "BOFG_flared_mwh": 0.0,
                    "flaring_co2_t": 0.0,
                    "natural_gas_mwh_lhv_model": round(ng_boiler, 6),
                    "capacity_utilisation": "",
                    "accounting_status": "executable_placeholder",
                    "caveat": "6 PJ/y flat placeholder; no calibrated process steam demand.",
                },
                {
                    **common,
                    "plant_id": "VattenfallInternalGeneration",
                    "component_type": "internal_generation_interface",
                    "activity_t_h": round(total_vattenfall, 6),
                    "throughput_value": round(total_vattenfall, 6),
                    "throughput_unit": "MWh_LHV/h",
                    "steam_or_boiler_use_mwh": 0.0,
                    "BFG_generated_mwh": 0.0,
                    "COG_generated_mwh": 0.0,
                    "BOFG_generated_mwh": 0.0,
                    "BFG_consumed_mwh": round(bfg_to_vattenfall, 6),
                    "COG_consumed_mwh": round(cog_to_vattenfall, 6),
                    "BOFG_consumed_mwh": round(bofg_to_vattenfall, 6),
                    "WAG_to_electricity_mwh": round(_safe_float(row.get("wag_electricity_mwh")), 6),
                    "BFG_flared_mwh": 0.0,
                    "COG_flared_mwh": 0.0,
                    "BOFG_flared_mwh": 0.0,
                    "flaring_co2_t": 0.0,
                    "combined_wag_volume_nm3_h": round(volume, 6),
                    "capacity_utilisation": round(volume / VATTENFALL_TOTAL_WAG_CAP_NM3_H, 6),
                    "accounting_status": "executable_internal_offset_no_revenue",
                    "caveat": "Combined volumetric cap, no export revenue or Vattenfall merchant dispatch.",
                },
                {
                    **common,
                    "plant_id": "CarrierSpecificFlare",
                    "component_type": "flare_accounting_node",
                    "activity_t_h": round(bfg_flared + cog_flared + bofg_flared, 6),
                    "throughput_value": round(bfg_flared + cog_flared + bofg_flared, 6),
                    "throughput_unit": "MWh_LHV/h",
                    "steam_or_boiler_use_mwh": 0.0,
                    "BFG_generated_mwh": 0.0,
                    "COG_generated_mwh": 0.0,
                    "BOFG_generated_mwh": 0.0,
                    "BFG_consumed_mwh": 0.0,
                    "COG_consumed_mwh": 0.0,
                    "BOFG_consumed_mwh": 0.0,
                    "WAG_to_electricity_mwh": 0.0,
                    "BFG_flared_mwh": round(bfg_flared, 6),
                    "COG_flared_mwh": round(cog_flared, 6),
                    "BOFG_flared_mwh": round(bofg_flared, 6),
                    "flaring_co2_t": round(_safe_float(row.get("flaring_co2_t")), 6),
                    "capacity_utilisation": "",
                    "accounting_status": "executable_carrier_specific_closure",
                    "caveat": "Flaring CO2 cost is diagnostic only, not ETS objective.",
                },
            ]
        )
    return rows


def _wag_rules_audit_rows() -> list[dict[str, Any]]:
    return [
        {
            "rule": "Vattenfall_combined_cap",
            "status": "confirmed",
            "detail": "BFG_volume + COG_volume + BOFG_volume <= 900000 Nm3/h",
            "Velsen_25_Nm3_h": VATTENFALL_VELSEN25_WAG_CAP_NM3_H,
            "IJmuiden_01_Nm3_h": VATTENFALL_IJM01_WAG_CAP_NM3_H,
            "total_Nm3_h": VATTENFALL_TOTAL_WAG_CAP_NM3_H,
            "caveat": "Not applied separately per carrier.",
        },
        {
            "rule": "process_priority_reporting",
            "status": "confirmed_reporting_order",
            "detail": "Fixed process sinks, then boiler/steam placeholder, then Vattenfall/internal generation, then carrier-specific flare.",
            "caveat": "The model uses fixed process sink expressions and a tiny non-economic flare-minimising tie-breaker; it is not an economic merit order.",
        },
        {
            "rule": "HSM_PEFA_gas_sinks",
            "status": "inactive_deferred",
            "detail": "Eligibility remains non-executable because coefficients are not approved.",
            "caveat": "Do not silently add HSM/PEFA fuel loads before source approval.",
        },
    ]


def _co2_convention_rows() -> list[dict[str, Any]]:
    return [
        {
            "co2_layer": "process_CO2",
            "status": "separate_partial_reporting",
            "current_model_scope": "DRP process proxy in plant diagnostics; BF/BOF process CO2 not fully represented.",
            "double_counting_rule": "Do not count carbon at WAG generation if it is later combusted/flared.",
            "objective_status": "not_in_objective",
        },
        {
            "co2_layer": "combustion_CO2",
            "status": "deferred",
            "current_model_scope": "Boiler and process combustion CO2 not yet calibrated.",
            "double_counting_rule": "Combustion CO2 must be tied to actual sink combustion once factors are approved.",
            "objective_status": "not_in_objective",
        },
        {
            "co2_layer": "flaring_CO2",
            "status": "active_diagnostic_reporting",
            "current_model_scope": "Carrier-specific flaring CO2 from BFG/COG/BOFG placeholders.",
            "double_counting_rule": "Flaring is counted only at flare sink, not at gas generation.",
            "objective_status": f"diagnostic cost only at {FLARING_CO2_DIAGNOSTIC_EUR_PER_T} EUR/tCO2; no ETS objective",
        },
    ]


def _write_outputs() -> dict[str, Any]:
    C5A_DIR.mkdir(parents=True, exist_ok=True)
    production_rows = _production_anchor_rows()
    anchor_rows = _anchor_table_rows()
    scale_rows = _scale_rows("24h", 24) + _scale_rows("168h", 168)
    dashboard_rows = _validation_dashboard_rows("24h", 24) + _validation_dashboard_rows("168h", 168)
    ng_rows = _ng_accounting_rows("24h", 24) + _ng_accounting_rows("168h", 168)
    electricity_rows = _electricity_accounting_rows("24h", 24) + _electricity_accounting_rows("168h", 168)
    plant24 = _enhanced_plant_rows("24h")
    plant168 = _enhanced_plant_rows("168h")
    wag_rows = _wag_rules_audit_rows()
    co2_rows = _co2_convention_rows()

    _write_csv(C5A_DIR / "s4_4c5a_production_anchor_selection.csv", production_rows)
    _write_csv(C5A_DIR / "s4_4c5a_corrected_anchor_table.csv", anchor_rows)
    _write_csv(C5A_DIR / "s4_4c5a_scale_mode_findings.csv", scale_rows)
    _write_csv(C5A_DIR / "s4_4c5a_corrected_annual_validation_dashboard.csv", dashboard_rows)
    _write_csv(C5A_DIR / "s4_4c5a_ng_hhv_lhv_accounting.csv", ng_rows)
    _write_csv(C5A_DIR / "s4_4c5a_electricity_accounting_separation.csv", electricity_rows)
    _write_csv(C5A_DIR / "s4_4c5a_24h_plant_diagnostics.csv", plant24)
    _write_csv(C5A_DIR / "s4_4c5a_168h_plant_diagnostics.csv", plant168)
    _write_csv(C5A_DIR / "s4_4c5a_wag_rules_audit.csv", wag_rows)
    _write_csv(C5A_DIR / "s4_4c5a_co2_accounting_convention.csv", co2_rows)

    severe_failures = []
    if not any(row["selected"] for row in production_rows):
        severe_failures.append("no_selected_production_anchor")
    if not all(row["scale_mode"] == "module_scale" for row in scale_rows):
        severe_failures.append("unexpected_scale_mode")
    if not any(row["metric"] == "electricity_total" for row in dashboard_rows):
        severe_failures.append("dashboard_missing_electricity")
    decision = "pass_s4_4c5a_validation_hardening_with_caveats" if not severe_failures else "blocked_s4_4c5a_schema_or_anchor_failure"
    gate = _write_stage_gate(
        decision,
        "Corrected validation/reconciliation outputs created; anchors remain diagnostic only.",
    )
    summary = {
        "stage_gate": gate,
        "selected_production_anchor_t_y": SELECTED_PRODUCTION_ANCHOR_T_Y,
        "output_directory": str(C5A_DIR.relative_to(REPO_ROOT)),
        "row_counts": {
            "production_anchor_selection": len(production_rows),
            "corrected_anchor_table": len(anchor_rows),
            "scale_mode_findings": len(scale_rows),
            "validation_dashboard": len(dashboard_rows),
            "ng_accounting": len(ng_rows),
            "electricity_accounting": len(electricity_rows),
            "plant_24h": len(plant24),
            "plant_168h": len(plant168),
        },
        "severe_failures": severe_failures,
    }
    _write_json(C5A_DIR / "s4_4c5a_summary.json", summary)
    return summary


def run_s4_4c5a_anchor_scaling_correction() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5a_anchor_scaling_correction(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
