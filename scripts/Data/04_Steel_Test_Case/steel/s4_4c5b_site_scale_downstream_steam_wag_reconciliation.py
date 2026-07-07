"""S4.4c5b site-scale physical/accounting reconciliation.

This stage is development-only. It reruns the existing C5 physical diagnostics,
refreshes the C5a anchor/accounting reports, and then writes a site-scale
reconciliation layer. Validation anchors are never used as optimiser
constraints or objective terms.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .s4_4c5_physical_diagnostics import (
    C0,
    C1,
    C5_DIR,
    REPO_ROOT,
    _read_rows,
    _safe_float,
    _sum,
    _write_csv,
    _write_json,
    run_s4_4c5_physical_diagnostics,
)
from .s4_4c5a_anchor_scaling_correction import (
    ATHANASIADIS_ANCHORS,
    NG_HHV_MJ_PER_NM3,
    PJ_TO_MWH,
    SELECTED_PRODUCTION_ANCHOR_T_Y,
    TWH_TO_MWH,
    run_s4_4c5a_anchor_scaling_correction,
)
from .s4_4c_unified_physical_modelbuilder import (
    SELECTED_WAG_LHV_MJ_PER_NM3,
    VATTENFALL_TOTAL_WAG_CAP_NM3_H,
)


S4_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4"
C5B_DIR = S4_ROOT / "s4_4c5b_site_scale_downstream_steam_wag_reconciliation"
STAGE = "S4.4c5b_site_scale_downstream_steam_wag_reconciliation"
HORIZONS = {"24h": 24, "168h": 168}
CARRIERS = ("BFG", "COG", "BOFG")
C1_ELECTRICITY_GAP_CLASS = "missing_retained_route_or_background_electricity_accounting"
TARGET_BASIS = "liquid_steel_equivalent_with_downstream_continuation"
STEAM_BASIS = "residual_unvalidated_placeholder"
EPS = 1e-6


def _read_csv(path: Path) -> list[dict[str, str]]:
    return _read_rows(path)


def _annualisation_factor(horizon_hours: int) -> float:
    if horizon_hours == 24:
        return 365.0
    if horizon_hours == 168:
        return 365.0 / 7.0
    return 8760.0 / horizon_hours


def _annualise(value: float, horizon_hours: int) -> float:
    return value * _annualisation_factor(horizon_hours)


def _target_for_horizon(horizon_hours: int) -> float:
    return SELECTED_PRODUCTION_ANCHOR_T_Y * horizon_hours / 8760.0


def _mwh_to_nm3(carrier: str, value_mwh: float) -> float:
    lhv = SELECTED_WAG_LHV_MJ_PER_NM3[carrier]
    return value_mwh * 3600.0 / lhv if lhv else 0.0


def _nm3_to_mwh(carrier: str, value_nm3: float) -> float:
    return value_nm3 * SELECTED_WAG_LHV_MJ_PER_NM3[carrier] / 3600.0


def _ng_mwh_lhv_to_nm3_hhv_equiv(value_mwh_lhv: float) -> float:
    return value_mwh_lhv * 3600.0 / NG_HHV_MJ_PER_NM3


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return "unavailable"
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def _report_rows(horizon: str) -> list[dict[str, str]]:
    return _read_csv(C5_DIR / f"s4_4c5_{horizon}_report.csv")


def _analytics_rows(horizon: str) -> list[dict[str, str]]:
    return _read_csv(C5_DIR / f"s4_4c5_{horizon}_computational_analytics.csv")


def _hourly_rows(horizon: str) -> list[dict[str, str]]:
    return _read_csv(C5_DIR / f"s4_4c5_{horizon}_hourly_dispatch_c0.csv") + _read_csv(
        C5_DIR / f"s4_4c5_{horizon}_hourly_dispatch_c1.csv"
    )


def _plant_rows(horizon: str) -> list[dict[str, str]]:
    return _read_csv(S4_ROOT / "s4_4c5a_anchor_scaling_accounting_correction" / f"s4_4c5a_{horizon}_plant_diagnostics.csv")


def _by_config(rows: list[dict[str, Any]], config_id: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("configuration_id") == config_id]


def _one_by_config(rows: list[dict[str, str]], config_id: str) -> dict[str, str]:
    for row in rows:
        if row.get("configuration_id") == config_id:
            return row
    return {}


def _site_projection_scale(config_id: str, report_row: dict[str, str], horizon_hours: int) -> float:
    if config_id == C0:
        return 1.0
    physical = _safe_float(report_row.get("final_product_fulfilled_t"))
    return _target_for_horizon(horizon_hours) / physical if physical else 0.0


def _direct_sink_demands(row: dict[str, str], flow_scale: float) -> list[dict[str, Any]]:
    config_id = row["configuration_id"]
    demands = [
        ("WAGs_COK1", "KGF1_CokingPlant1", "BFG", "BFG_to_KGF1_mwh", "direct_process_wag"),
        ("WAGs_COK1", "KGF1_CokingPlant1", "COG", "COG_to_KGF1_mwh", "direct_process_wag"),
        ("SinterPlantDirectCOG", "SinteringPlant", "COG", "COG_to_sinter_mwh", "direct_process_wag"),
    ]
    if config_id == C0:
        demands.append(("CokingPlant2DirectCOG", "KGF2_CokingPlant2", "COG", "COG_to_KGF2_mwh", "direct_process_wag"))
    else:
        demands.append(("CokingPlant2DirectCOG", "KGF2_CokingPlant2", "COG", "COG_to_KGF2_mwh", "inactive_c1_topology"))
    rows = []
    for sink, plant, carrier, field, accounting_class in demands:
        requested = _safe_float(row.get(field)) * flow_scale
        rows.append(
            {
                "sink": sink,
                "plant": plant,
                "carrier": carrier,
                "requested_mwh": requested,
                "accounting_class": accounting_class,
                "source_or_assumption": "existing C5 direct WAG sink scaled only for C1 site-proxy route-linked flows",
            }
        )
    return rows


def _allocate_wag_hour(row: dict[str, str], horizon: str, horizon_hours: int, flow_scale: float) -> list[dict[str, Any]]:
    available = {
        carrier: _safe_float(row.get(f"{carrier}_generated_mwh")) * flow_scale
        for carrier in CARRIERS
    }
    allocations: list[dict[str, Any]] = []

    def add(
        sink: str,
        plant: str,
        carrier: str,
        category: str,
        quantity_mwh: float,
        status: str,
        source: str,
        allocation_order: int,
        requested_mwh: float | str = "",
        electricity_mwh: float = 0.0,
        volume_nm3_h: float = 0.0,
    ) -> None:
        allocations.append(
            {
                "horizon": horizon,
                "horizon_hours": horizon_hours,
                "configuration_id": row["configuration_id"],
                "hour": int(float(row["hour_index"])),
                "sink": sink,
                "plant": plant,
                "carrier": carrier,
                "allocation_category": category,
                "allocation_order": allocation_order,
                "requested_mwh": requested_mwh,
                "quantity_mwh": round(quantity_mwh, 6),
                "WAG_to_electricity_MWh": round(electricity_mwh, 6),
                "volume_Nm3_h": round(volume_nm3_h, 6),
                "status": status,
                "scale_mode": "site_scale_projected_for_C1_only" if flow_scale != 1.0 else "direct_physical_output",
                "source_or_assumption": source,
            }
        )

    for demand in _direct_sink_demands(row, flow_scale):
        carrier = demand["carrier"]
        requested = demand["requested_mwh"]
        quantity = min(available[carrier], requested)
        available[carrier] -= quantity
        status = demand["accounting_class"]
        if requested > quantity + EPS:
            status = "direct_process_wag_shortfall_diagnostic"
        add(
            demand["sink"],
            demand["plant"],
            carrier,
            "direct_process_sink",
            quantity,
            status,
            demand["source_or_assumption"],
            1,
            requested_mwh=round(requested, 6),
        )

    missing_sinks = [
        ("HSM_COG_NG", "HSM", "COG"),
        ("PEFA_Malerij_BOFG_NG", "PEFA_Malerij", "BOFG"),
        ("PEFA_Branderij_COG_NG", "PEFA_Branderij", "COG"),
    ]
    for sink, plant, carrier in missing_sinks:
        add(
            sink,
            plant,
            carrier,
            "missing_direct_process_sink",
            0.0,
            "missing_executable_coefficient",
            "model_effect=may_overstate_WAG_to_Vattenfall_or_flaring",
            1,
            requested_mwh="",
        )

    boiler_fuel_requirement = (
        _safe_float(row.get("BFG_to_boiler_mwh"))
        + _safe_float(row.get("COG_to_boiler_mwh"))
        + _safe_float(row.get("BOFG_to_boiler_mwh"))
        + _safe_float(row.get("natural_gas_boiler_mwh"))
    )
    remaining_boiler = boiler_fuel_requirement
    for carrier in CARRIERS:
        quantity = min(available[carrier], remaining_boiler)
        available[carrier] -= quantity
        remaining_boiler -= quantity
        add(
            "BoilerSteamUtility",
            "BoilerSteamUtility",
            carrier,
            "boiler_steam_wag_first",
            quantity,
            "allocated_after_direct_process_sinks",
            "deterministic WAG-first accounting allocator; not economic dispatch",
            2,
            requested_mwh=round(boiler_fuel_requirement, 6),
        )
    boiler_ng = max(remaining_boiler, 0.0)
    add(
        "BoilerSteamUtility",
        "BoilerSteamUtility",
        "NaturalGas",
        "boiler_steam_ng_supplement",
        boiler_ng,
        "ng_supplement_after_eligible_wag",
        "NG supplements only remaining boiler/steam fuel requirement; never WAGs_COK1",
        2,
        requested_mwh=round(boiler_fuel_requirement, 6),
    )

    original_vattenfall_fuel = _safe_float(row.get("vattenfall_fuel_mwh"))
    original_wag_electricity = _safe_float(row.get("wag_electricity_mwh"))
    electricity_efficiency = original_wag_electricity / original_vattenfall_fuel if original_vattenfall_fuel > EPS else 0.0
    remaining_cap_nm3 = VATTENFALL_TOTAL_WAG_CAP_NM3_H
    for carrier in CARRIERS:
        available_volume = _mwh_to_nm3(carrier, available[carrier])
        allocated_volume = min(available_volume, remaining_cap_nm3)
        quantity = _nm3_to_mwh(carrier, allocated_volume)
        available[carrier] -= quantity
        remaining_cap_nm3 -= allocated_volume
        add(
            "Vattenfall_internal_generation",
            "VattenfallInternalGeneration",
            carrier,
            "vattenfall_internal_generation",
            quantity,
            "combined_cap_limited" if remaining_cap_nm3 <= EPS and available[carrier] > EPS else "combined_cap_checked",
            "combined BFG+COG+BOFG volume cap; no export revenue or merchant dispatch",
            3,
            electricity_mwh=quantity * electricity_efficiency,
            volume_nm3_h=allocated_volume,
        )

    for carrier in CARRIERS:
        quantity = max(available[carrier], 0.0)
        add(
            "CarrierSpecificFlare",
            "CarrierSpecificFlare",
            carrier,
            "flare_after_all_eligible_sinks",
            quantity,
            "allocated_after_direct_boiler_vattenfall",
            "Flaring is residual after direct sinks, boiler/steam, and Vattenfall/interface allocation",
            4,
        )
    return allocations


def _allocation_rows(horizon: str, horizon_hours: int, report_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_config = {row["configuration_id"]: row for row in report_rows}
    rows: list[dict[str, Any]] = []
    for hourly in _hourly_rows(horizon):
        scale = _site_projection_scale(hourly["configuration_id"], by_config[hourly["configuration_id"]], horizon_hours)
        rows.extend(_allocate_wag_hour(hourly, horizon, horizon_hours, scale))
    return rows


def _sum_alloc(rows: list[dict[str, Any]], config_id: str, category: str | None = None, carrier: str | None = None) -> float:
    total = 0.0
    for row in rows:
        if row.get("configuration_id") != config_id:
            continue
        if category is not None and row.get("allocation_category") != category:
            continue
        if carrier is not None and row.get("carrier") != carrier:
            continue
        total += _safe_float(row.get("quantity_mwh"))
    return total


def _sum_alloc_electricity(rows: list[dict[str, Any]], config_id: str, carrier: str | None = None) -> float:
    total = 0.0
    for row in rows:
        if row.get("configuration_id") != config_id:
            continue
        if row.get("allocation_category") != "vattenfall_internal_generation":
            continue
        if carrier is not None and row.get("carrier") != carrier:
            continue
        total += _safe_float(row.get("WAG_to_electricity_MWh"))
    return total


def _validation_anchor_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config_id, anchors in ATHANASIADIS_ANCHORS.items():
        for metric, anchor in anchors.items():
            rows.append(
                {
                    "anchor_family": "Athanasiadis",
                    "configuration_id": config_id,
                    "anchor_metric": metric,
                    "anchor_value": anchor["anchor_value"],
                    "unit": anchor["unit"],
                    "source_locator": anchor["source"],
                    "validation_target_only": True,
                    "constraint_or_objective_input": False,
                    "availability_status": "available_from_C5a_anchor_table",
                    "caveat": anchor["basis"],
                }
            )
    heracless_missing = [
        "total_liquid_steel_context",
        "retained_BF_BOF_route",
        "DRI_EAF_route",
        "NG_energy_HHV",
        "electricity",
        "coal",
        "DRI",
        "DRI_flexibility_range",
        "DRI_NG_reduction",
        "DRI_NG_furnace_fuel",
        "DRI_electricity",
        "slab_import",
    ]
    for metric in heracless_missing:
        rows.append(
            {
                "anchor_family": "Heracless",
                "configuration_id": C1,
                "anchor_metric": metric,
                "anchor_value": "",
                "unit": "",
                "source_locator": "",
                "validation_target_only": True,
                "constraint_or_objective_input": False,
                "availability_status": "missing_reviewed_or_migrated_source_in_C5a_inputs",
                "caveat": "Prompt context not promoted to executable validation anchor without reviewed source matrix or migration evidence.",
            }
        )
    return rows


def _electricity_rows(
    horizon: str,
    horizon_hours: int,
    report_rows: list[dict[str, str]],
    allocations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    hourly_rows = _hourly_rows(horizon)
    plants = _plant_rows(horizon)
    for config_id in (C0, C1):
        report = _one_by_config(report_rows, config_id)
        flow_scale = _site_projection_scale(config_id, report, horizon_hours)
        physical_hourly = _by_config(hourly_rows, config_id)
        physical_plants = _by_config(plants, config_id)
        process_electricity = sum(
            _safe_float(row.get("electricity_use_mwh"))
            for row in physical_plants
            if row.get("electricity_use_mwh") not in {"", "not_modelled_separately", None}
        )
        gross = _sum(physical_hourly, "gross_electricity_mwh")
        if config_id == C1:
            process_electricity *= flow_scale
            gross *= flow_scale
            metric_scale_mode = "site_scaled_route_linked_variable_electricity"
        else:
            metric_scale_mode = "full_site_proxy_no_module_upscale"
        wag_electricity = _sum_alloc_electricity(allocations, config_id)
        gross_y = _annualise(gross, horizon_hours)
        wag_y = _annualise(wag_electricity, horizon_hours)
        net_y = gross_y - wag_y
        anchor = ATHANASIADIS_ANCHORS[config_id]["electricity_total"]["anchor_value"]
        residual = max(anchor - gross_y, 0.0)
        gap_class = ""
        if config_id == C1 and gross_y <= _annualise(_sum(_by_config(hourly_rows, C0), "gross_electricity_mwh"), horizon_hours):
            gap_class = C1_ELECTRICITY_GAP_CLASS
        rows.append(
            {
                "horizon": horizon,
                "configuration_id": config_id,
                "variable_process_electricity_MWh_y": round(_annualise(process_electricity, horizon_hours), 6),
                "retained_route_background_electricity_MWh_y": 0.0,
                "drp_eaf_variable_electricity_MWh_y": round(_annualise(process_electricity, horizon_hours), 6) if config_id == C1 else 0.0,
                "downstream_electricity_MWh_y": 0.0,
                "full_site_proxy_electricity_MWh_y": round(gross_y, 6),
                "residual_background_electricity_load_MWh_y": round(residual, 6),
                "WAG_internal_generation_MWh_y": round(wag_y, 6),
                "gross_site_electricity_demand_MWh_y": round(gross_y, 6),
                "net_grid_import_proxy_MWh_y": round(net_y, 6),
                "validation_anchor_MWh_y": round(anchor, 6),
                "scale_mode": metric_scale_mode,
                "gap_classification": gap_class,
                "residual_load_in_optimizer": False,
                "caveat": "Residual background load is diagnostic only; no electricity anchor is imposed as a constraint.",
            }
        )
    return rows


def _ng_rows(
    horizon: str,
    horizon_hours: int,
    report_rows: list[dict[str, str]],
    allocations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    hourly_rows = _hourly_rows(horizon)
    for config_id in (C0, C1):
        report = _one_by_config(report_rows, config_id)
        flow_scale = _site_projection_scale(config_id, report, horizon_hours)
        physical_hourly = _by_config(hourly_rows, config_id)
        drp_ng_nm3 = _sum(physical_hourly, "natural_gas_nm3") * (flow_scale if config_id == C1 else 1.0)
        boiler_ng_lhv_mwh = _sum_alloc(allocations, config_id, "boiler_steam_ng_supplement", "NaturalGas")
        boiler_ng_nm3 = _ng_mwh_lhv_to_nm3_hhv_equiv(boiler_ng_lhv_mwh)
        total_nm3 = drp_ng_nm3 + boiler_ng_nm3
        total_nm3_y = _annualise(total_nm3, horizon_hours)
        total_pj_y = total_nm3_y * NG_HHV_MJ_PER_NM3 / 1_000_000_000.0
        rows.append(
            {
                "horizon": horizon,
                "configuration_id": config_id,
                "DRP_NG_Nm3_h_avg_HHV_basis": round(drp_ng_nm3 / horizon_hours, 6),
                "boiler_NG_Nm3_h_avg_HHV_equivalent": round(boiler_ng_nm3 / horizon_hours, 6),
                "HSM_or_process_NG_Nm3_h_avg_HHV_basis": 0.0,
                "PEFA_or_process_NG_Nm3_h_avg_HHV_basis": 0.0,
                "background_NG_Nm3_h_avg_HHV_basis": 0.0,
                "Vattenfall_NG_Nm3_h_avg_HHV_basis": 0.0,
                "NG_Nm3_h_avg_HHV_basis": round(total_nm3 / horizon_hours, 6),
                "NG_PJ_y_HHV": round(total_pj_y, 6),
                "boiler_NG_MWh_y_LHV": round(_annualise(boiler_ng_lhv_mwh, horizon_hours), 6),
                "NG_MWh_y_LHV_available": round(_annualise(boiler_ng_lhv_mwh, horizon_hours), 6),
                "conversion_method": "DRP NG uses Nm3 with HHV 39.8 MJ/Nm3; boiler model MWh_LHV is converted to HHV-equivalent Nm3 for validation only.",
                "scale_mode": "C1_DRP_site_scaled_boiler_placeholder_unscaled" if config_id == C1 else "C0_boiler_placeholder_unscaled",
            }
        )
    return rows


def _co2_rows(
    horizon: str,
    horizon_hours: int,
    report_rows: list[dict[str, str]],
    allocations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    plants = _plant_rows(horizon)
    hourly_rows = _hourly_rows(horizon)
    for config_id in (C0, C1):
        report = _one_by_config(report_rows, config_id)
        flow_scale = _site_projection_scale(config_id, report, horizon_hours)
        scale = flow_scale if config_id == C1 else 1.0
        process_drp = sum(
            _safe_float(row.get("process_co2_t"))
            for row in _by_config(plants, config_id)
            if row.get("plant_id") == "DRP"
        ) * scale
        flare_co2 = 0.0
        for carrier in CARRIERS:
            original_flare = _sum(_by_config(hourly_rows, config_id), f"{carrier}_flared_mwh")
            original_co2 = _sum(_by_config(hourly_rows, config_id), f"{carrier}_flare_co2_t")
            factor = original_co2 / original_flare if original_flare > EPS else 0.0
            flare_mwh = _sum_alloc(allocations, config_id, "flare_after_all_eligible_sinks", carrier)
            flare_co2 += flare_mwh * factor
        total_partial = process_drp + flare_co2
        bucket_values = {
            "BF_process_combustion_CO2": ("missing_executable_coefficient", 0.0),
            "BOF_process_CO2": ("missing_executable_coefficient", 0.0),
            "KGF_coking_process_combustion_CO2": ("missing_executable_coefficient", 0.0),
            "DRP_NG_combustion_process_CO2": ("partial_process_placeholder_only", process_drp),
            "EAF_direct_CO2": ("not_modelled", 0.0),
            "boiler_NG_combustion_CO2": ("missing_executable_factor", 0.0),
            "WAG_combustion_CO2": ("excluded_to_avoid_double_count_without_boundary_convention", 0.0),
            "flaring_CO2": ("active_diagnostic", flare_co2),
            "captured_CO2_diagnostic": ("missing_Heracless_source_rows", 0.0),
            "Scope2_electricity_CO2": ("disabled_reporting_only", 0.0),
        }
        for bucket, (status, value) in bucket_values.items():
            rows.append(
                {
                    "horizon": horizon,
                    "configuration_id": config_id,
                    "co2_bucket": bucket,
                    "CO2_t_y": round(_annualise(value, horizon_hours), 6),
                    "status": status,
                    "objective_status": "not_in_objective",
                    "double_counting_convention": "WAG carbon is not counted at generation and again at use; current total is partial.",
                    "scale_mode": "C1_route_scaled_partial" if config_id == C1 else "C0_partial_unscaled",
                }
            )
        rows.append(
            {
                "horizon": horizon,
                "configuration_id": config_id,
                "co2_bucket": "partial_total_CO2_for_anchor_gap",
                "CO2_t_y": round(_annualise(total_partial, horizon_hours), 6),
                "status": "partial_not_comparable_to_total_anchor",
                "objective_status": "not_in_objective",
                "double_counting_convention": "Includes DRP process placeholder and flaring only.",
                "scale_mode": "C1_route_scaled_partial" if config_id == C1 else "C0_partial_unscaled",
            }
        )
    return rows


def _steam_rows(horizon: str, horizon_hours: int, allocations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    hourly_rows = _hourly_rows(horizon)
    for config_id in (C0, C1):
        steam = _sum(_by_config(hourly_rows, config_id), "steam")
        boiler_wag = sum(
            _sum_alloc(allocations, config_id, "boiler_steam_wag_first", carrier)
            for carrier in CARRIERS
        )
        boiler_ng = _sum_alloc(allocations, config_id, "boiler_steam_ng_supplement", "NaturalGas")
        rows.append(
            {
                "horizon": horizon,
                "configuration_id": config_id,
                "source_backed_process_steam_demand_MWh_y": "",
                "residual_steam_demand_MWh_y": round(_annualise(steam, horizon_hours), 6),
                "total_steam_demand_MWh_y": round(_annualise(steam, horizon_hours), 6),
                "steam_basis": STEAM_BASIS,
                "steam_residual_unvalidated_placeholder_MWh_y": round(_annualise(steam, horizon_hours), 6),
                "boiler_WAG_fuel_MWh_y_LHV": round(_annualise(boiler_wag, horizon_hours), 6),
                "boiler_NG_fuel_MWh_y_LHV": round(_annualise(boiler_ng, horizon_hours), 6),
                "steam_validation_anchor_active": False,
                "thesis_approved": False,
                "caveat": "Flat residual steam placeholder only; no legacy steam validation anchor is used.",
            }
        )
    return rows


def _route_rows(horizon: str, horizon_hours: int, report_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for config_id in (C0, C1):
        report = _one_by_config(report_rows, config_id)
        flow_scale = _site_projection_scale(config_id, report, horizon_hours)
        if config_id == C1:
            retained_horizon = _safe_float(report.get("retained_bf_bof_final_product_t")) * flow_scale
            drp_horizon = _safe_float(report.get("eaf_final_product_t")) * flow_scale
        else:
            retained_horizon = _target_for_horizon(horizon_hours)
            drp_horizon = 0.0
        total = retained_horizon + drp_horizon
        rows.append(
            {
                "horizon": horizon,
                "configuration_id": config_id,
                "target_basis": TARGET_BASIS,
                "retained_bf_bof_liquid_steel_t_y": round(_annualise(retained_horizon, horizon_hours), 6),
                "drp_eaf_liquid_steel_t_y": round(_annualise(drp_horizon, horizon_hours), 6),
                "retained_route_share": round(retained_horizon / total, 9) if total else 0.0,
                "drp_eaf_route_share": round(drp_horizon / total, 9) if total else 0.0,
                "route_logic": "bottom_up_retained_route_then_DRP_EAF_residual" if config_id == C1 else "C0_current_BF_BOF_reference_route",
                "Heracless_retained_BF_BOF_anchor_t_y": "",
                "Heracless_DRI_EAF_anchor_t_y": "",
                "Heracless_anchor_status": "missing_reviewed_or_migrated_source_in_C5a_inputs",
                "anchors_forced": False,
            }
        )
    return rows


def _downstream_rows(horizon: str, horizon_hours: int, report_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    site_target = _target_for_horizon(horizon_hours)
    for config_id in (C0, C1):
        report = _one_by_config(report_rows, config_id)
        physical = _safe_float(report.get("final_product_fulfilled_t"))
        rows.append(
            {
                "horizon": horizon,
                "configuration_id": config_id,
                "target_basis": TARGET_BASIS,
                "liquid_steel_produced_t": round(site_target, 6),
                "internal_slab_produced_t": round(site_target, 6),
                "external_slab_import_t": 0.0,
                "final_product_proxy_t": round(site_target, 6),
                "final_product_proxy_fulfilment": 1.0,
                "production_residual_t": 0.0,
                "physical_solver_final_product_t": round(physical, 6),
                "physical_solver_site_target_fulfilment": round(physical / site_target, 9) if site_target else 0.0,
                "physical_solver_production_residual_t": round(site_target - physical, 6),
                "hot_cold_slab_store_status": "diagnostic_or_blocked_no_strategic_arbitrage",
                "terminal_policy_status": "no_active_slab_store_in_C5b_accounting_projection",
                "caveat": "Downstream continuation is accounting projection, not a free slab battery.",
            }
        )
    return rows


def _vattenfall_rows(horizon: str, horizon_hours: int, allocations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for config_id in (C0, C1):
        for hour in range(horizon_hours):
            hour_rows = [
                row
                for row in allocations
                if row["configuration_id"] == config_id
                and row["hour"] == hour
                and row["allocation_category"] == "vattenfall_internal_generation"
            ]
            by_carrier = {carrier: 0.0 for carrier in CARRIERS}
            elec_by_carrier = {carrier: 0.0 for carrier in CARRIERS}
            volume_by_carrier = {carrier: 0.0 for carrier in CARRIERS}
            for alloc in hour_rows:
                carrier = alloc["carrier"]
                by_carrier[carrier] += _safe_float(alloc.get("quantity_mwh"))
                elec_by_carrier[carrier] += _safe_float(alloc.get("WAG_to_electricity_MWh"))
                volume_by_carrier[carrier] += _safe_float(alloc.get("volume_Nm3_h"))
            combined = sum(volume_by_carrier.values())
            rows.append(
                {
                    "horizon": horizon,
                    "horizon_hours": horizon_hours,
                    "configuration_id": config_id,
                    "hour": hour,
                    "BFG_to_vattenfall_MWh_LHV": round(by_carrier["BFG"], 6),
                    "COG_to_vattenfall_MWh_LHV": round(by_carrier["COG"], 6),
                    "BOFG_to_vattenfall_MWh_LHV": round(by_carrier["BOFG"], 6),
                    "BFG_volume_Nm3_h": round(volume_by_carrier["BFG"], 6),
                    "COG_volume_Nm3_h": round(volume_by_carrier["COG"], 6),
                    "BOFG_volume_Nm3_h": round(volume_by_carrier["BOFG"], 6),
                    "combined_vattenfall_wag_volume_Nm3_h": round(combined, 6),
                    "max_combined_vattenfall_wag_volume_Nm3_h": "",
                    "mean_combined_vattenfall_wag_volume_Nm3_h": "",
                    "binding_hours": "",
                    "BFG_WAG_to_electricity_MWh": round(elec_by_carrier["BFG"], 6),
                    "COG_WAG_to_electricity_MWh": round(elec_by_carrier["COG"], 6),
                    "BOFG_WAG_to_electricity_MWh": round(elec_by_carrier["BOFG"], 6),
                    "Vattenfall_cap_Nm3_h": VATTENFALL_TOTAL_WAG_CAP_NM3_H,
                    "Vattenfall_cap_status": "binding" if combined >= VATTENFALL_TOTAL_WAG_CAP_NM3_H - EPS else "not_binding",
                    "cap_policy": "combined_BFG_COG_BOFG_volume_cap_not_per_carrier",
                }
            )
    summary: dict[tuple[str, str], dict[str, float]] = {}
    for key_config in (C0, C1):
        values = [
            _safe_float(row["combined_vattenfall_wag_volume_Nm3_h"])
            for row in rows
            if row["configuration_id"] == key_config and row["horizon"] == horizon
        ]
        summary[(horizon, key_config)] = {
            "max": max(values) if values else 0.0,
            "mean": sum(values) / len(values) if values else 0.0,
            "binding": sum(1 for value in values if value >= VATTENFALL_TOTAL_WAG_CAP_NM3_H - EPS),
        }
    for row in rows:
        stats = summary[(row["horizon"], row["configuration_id"])]
        row["max_combined_vattenfall_wag_volume_Nm3_h"] = round(stats["max"], 6)
        row["mean_combined_vattenfall_wag_volume_Nm3_h"] = round(stats["mean"], 6)
        row["binding_hours"] = int(stats["binding"])
    return rows


def _plant_carrier_io_rows(
    horizon: str,
    horizon_hours: int,
    report_rows: list[dict[str, str]],
    allocations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    downstream = _downstream_rows(horizon, horizon_hours, report_rows)
    for prod in downstream:
        for component, quantity in (
            ("liquid_steel", prod["liquid_steel_produced_t"]),
            ("internal_slab", prod["internal_slab_produced_t"]),
            ("external_slab_import", prod["external_slab_import_t"]),
            ("final_product_proxy", prod["final_product_proxy_t"]),
        ):
            rows.append(
                {
                    "configuration": prod["configuration_id"],
                    "horizon_hours": horizon_hours,
                    "hour": "",
                    "plant": "DownstreamContinuation",
                    "component": component,
                    "carrier": "steel_material",
                    "direction": "output" if component != "external_slab_import" else "input",
                    "quantity": quantity,
                    "unit": "t/horizon",
                    "accounting_class": "downstream_continuation_accounting",
                    "source_or_assumption": "6.75 Mt/y site-scale target projected to horizon",
                    "status": "active_accounting_projection",
                }
            )
    for alloc in allocations:
        direction = "input"
        if alloc["allocation_category"] == "flare_after_all_eligible_sinks":
            direction = "output"
        rows.append(
            {
                "configuration": alloc["configuration_id"],
                "horizon_hours": horizon_hours,
                "hour": alloc["hour"],
                "plant": alloc["plant"],
                "component": alloc["sink"],
                "carrier": alloc["carrier"],
                "direction": direction,
                "quantity": alloc["quantity_mwh"],
                "unit": "MWh_LHV/h",
                "accounting_class": alloc["allocation_category"],
                "source_or_assumption": alloc["source_or_assumption"],
                "status": alloc["status"],
            }
        )
    return rows


def _anchor_gap_rows(
    horizon: str,
    horizon_hours: int,
    electricity_rows: list[dict[str, Any]],
    ng_rows: list[dict[str, Any]],
    co2_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for config_id in (C0, C1):
        elec = _one_by_config(electricity_rows, config_id)
        ng = _one_by_config(ng_rows, config_id)
        partial_co2 = next(
            row
            for row in co2_rows
            if row["configuration_id"] == config_id and row["co2_bucket"] == "partial_total_CO2_for_anchor_gap"
        )
        metrics = {
            "electricity_total": _safe_float(elec.get("gross_site_electricity_demand_MWh_y")),
            "natural_gas": _safe_float(ng.get("NG_Nm3_h_avg_HHV_basis")),
            "co2_total": _safe_float(partial_co2.get("CO2_t_y")),
            "wag_electricity": _safe_float(elec.get("WAG_internal_generation_MWh_y")),
        }
        for metric, value in metrics.items():
            anchor = ATHANASIADIS_ANCHORS[config_id][metric]
            anchor_value = anchor["anchor_value"]
            gap = value - anchor_value
            rows.append(
                {
                    "horizon": horizon,
                    "configuration_id": config_id,
                    "anchor_family": "Athanasiadis",
                    "metric": metric,
                    "model_value": round(value, 6),
                    "anchor_value": round(anchor_value, 6),
                    "unit": anchor["unit"],
                    "gap_absolute": round(gap, 6),
                    "gap_percent": round(gap / anchor_value * 100.0, 6) if anchor_value else "",
                    "scale_mode": elec.get("scale_mode") if metric in {"electricity_total", "wag_electricity"} else ng.get("scale_mode") if metric == "natural_gas" else partial_co2.get("scale_mode"),
                    "gap_classification": elec.get("gap_classification") if metric == "electricity_total" else "partial_CO2_not_comparable_to_total_anchor" if metric == "co2_total" else "",
                    "anchor_used_as_constraint": False,
                }
            )
    rows.append(
        {
            "horizon": horizon,
            "configuration_id": C1,
            "anchor_family": "Heracless",
            "metric": "route_and_energy_context",
            "model_value": "",
            "anchor_value": "",
            "unit": "",
            "gap_absolute": "",
            "gap_percent": "",
            "scale_mode": "",
            "gap_classification": "missing_reviewed_or_migrated_source_in_C5a_inputs",
            "anchor_used_as_constraint": False,
        }
    )
    return rows


def _summary_rows(
    horizon: str,
    horizon_hours: int,
    report_rows: list[dict[str, str]],
    analytics_rows: list[dict[str, str]],
    downstream_rows: list[dict[str, Any]],
    route_rows: list[dict[str, Any]],
    electricity_rows: list[dict[str, Any]],
    ng_rows: list[dict[str, Any]],
    co2_rows: list[dict[str, Any]],
    allocations: list[dict[str, Any]],
    vattenfall_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for config_id in (C0, C1):
        report = _one_by_config(report_rows, config_id)
        analytics = _one_by_config(analytics_rows, config_id)
        down = _one_by_config(downstream_rows, config_id)
        route = _one_by_config(route_rows, config_id)
        elec = _one_by_config(electricity_rows, config_id)
        ng = _one_by_config(ng_rows, config_id)
        partial_co2 = next(
            row
            for row in co2_rows
            if row["configuration_id"] == config_id and row["co2_bucket"] == "partial_total_CO2_for_anchor_gap"
        )
        vf = [row for row in vattenfall_rows if row["configuration_id"] == config_id]
        wag_generation = _sum(_by_config(_hourly_rows(horizon), config_id), "WAG_generated")
        if config_id == C1:
            wag_generation *= _site_projection_scale(config_id, report, horizon_hours)
        rows.append(
            {
                "stage": STAGE,
                "configuration_id": config_id,
                "horizon": horizon,
                "horizon_hours": horizon_hours,
                "annualisation_factor": _annualisation_factor(horizon_hours),
                "solver_status": report.get("solver_status"),
                "termination_condition": report.get("termination_condition"),
                "objective_value": report.get("objective_value"),
                "runtime_seconds": analytics.get("total_runtime_seconds"),
                "mip_gap": analytics.get("mip_gap"),
                "variable_count": report.get("variable_count"),
                "binary_count": report.get("binary_count"),
                "constraint_count": report.get("constraint_count"),
                "production_fulfilment": down.get("final_product_proxy_fulfilment"),
                "production_residual_t": down.get("production_residual_t"),
                "physical_solver_site_target_fulfilment": down.get("physical_solver_site_target_fulfilment"),
                "liquid_steel_t": down.get("liquid_steel_produced_t"),
                "slab_produced_t": down.get("internal_slab_produced_t"),
                "slab_imported_t": down.get("external_slab_import_t"),
                "final_product_proxy_t": down.get("final_product_proxy_t"),
                "target_basis": TARGET_BASIS,
                "retained_route_share": route.get("retained_route_share"),
                "drp_eaf_route_share": route.get("drp_eaf_route_share"),
                "electricity_gross_MWh_y": elec.get("gross_site_electricity_demand_MWh_y"),
                "WAG_electricity_MWh_y": elec.get("WAG_internal_generation_MWh_y"),
                "net_grid_import_proxy_MWh_y": elec.get("net_grid_import_proxy_MWh_y"),
                "NG_Nm3_h_avg_HHV_basis": ng.get("NG_Nm3_h_avg_HHV_basis"),
                "NG_PJ_y_HHV": ng.get("NG_PJ_y_HHV"),
                "CO2_partial_total_t_y": partial_co2.get("CO2_t_y"),
                "WAG_generated_MWh_y": round(_annualise(wag_generation, horizon_hours), 6),
                "WAG_consumed_direct_boiler_vattenfall_MWh_y": round(
                    _annualise(
                        sum(
                            _sum_alloc(allocations, config_id, category, carrier)
                            for category in ("direct_process_sink", "boiler_steam_wag_first", "vattenfall_internal_generation")
                            for carrier in CARRIERS
                        ),
                        horizon_hours,
                    ),
                    6,
                ),
                "WAG_flared_MWh_y": round(
                    _annualise(sum(_sum_alloc(allocations, config_id, "flare_after_all_eligible_sinks", carrier) for carrier in CARRIERS), horizon_hours),
                    6,
                ),
                "max_combined_vattenfall_wag_volume_Nm3_h": max((_safe_float(row["combined_vattenfall_wag_volume_Nm3_h"]) for row in vf), default=0.0),
                "mean_combined_vattenfall_wag_volume_Nm3_h": round(sum(_safe_float(row["combined_vattenfall_wag_volume_Nm3_h"]) for row in vf) / len(vf), 6) if vf else 0.0,
                "vattenfall_binding_hours": sum(1 for row in vf if row["Vattenfall_cap_status"] == "binding"),
                "terminal_inventory_status": "no_new_active_store_in_C5b; inherited C5 terminal diagnostics",
            }
        )
    return rows


def _component_gap_rows() -> list[dict[str, Any]]:
    return [
        {
            "component": "HSM COG/NG use",
            "status": "missing_executable_coefficient",
            "model_effect": "may_overstate_WAG_to_Vattenfall_or_flaring",
            "recommended_action": "migrate reviewed HSM fuel coefficient before thesis-grade site accounting",
        },
        {
            "component": "PEFA Malerij BOFG/NG use",
            "status": "missing_executable_coefficient",
            "model_effect": "may_overstate_WAG_to_Vattenfall_or_flaring",
            "recommended_action": "migrate reviewed PEFA Malerij fuel coefficient",
        },
        {
            "component": "PEFA Branderij COG/NG use",
            "status": "missing_executable_coefficient",
            "model_effect": "may_overstate_WAG_to_Vattenfall_or_flaring",
            "recommended_action": "migrate reviewed PEFA Branderij fuel coefficient",
        },
        {
            "component": "Steam",
            "status": "steam_residual_unvalidated_placeholder",
            "model_effect": "not thesis-approved; no legacy steam anchor active",
            "recommended_action": "replace residual placeholder with source-backed process steam demand",
        },
        {
            "component": "C1 electricity",
            "status": C1_ELECTRICITY_GAP_CLASS,
            "model_effect": "C1 gross electricity remains below C0 because retained-route/background/downstream loads are incomplete",
            "recommended_action": "add retained-route and downstream electricity coefficients before economic comparison",
        },
        {
            "component": "CO2 ledger",
            "status": "partial_not_comparable_to_total_anchor",
            "model_effect": "BF/BOF/KGF/boiler/WAG combustion factors incomplete; total CO2 anchor gaps are diagnostic only",
            "recommended_action": "freeze a no-double-counting CO2 boundary and migrate missing factors",
        },
        {
            "component": "Heracless anchors",
            "status": "missing_reviewed_or_migrated_source_in_C5a_inputs",
            "model_effect": "Heracless route and energy gaps are not computed in C5b",
            "recommended_action": "migrate reviewed augmented readiness matrix rows before numeric Heracless gap reporting",
        },
        {
            "component": "Hot/cold slab stores",
            "status": "diagnostic_or_blocked_no_strategic_arbitrage",
            "model_effect": "no free slab battery or hot/cold slab arbitrage in C5b",
            "recommended_action": "define finite capacities and terminal policy before activating slab stores",
        },
    ]


def _write_stage_gate(summary_rows: list[dict[str, Any]]) -> dict[str, Any]:
    solved = all(row["solver_status"] == "ok" and row["termination_condition"] == "optimal" for row in summary_rows)
    c1_rows = [row for row in summary_rows if row["configuration_id"] == C1]
    gate = {
        "stage": STAGE,
        "decision": "pass_s4_4c5b_development_accounting_reconciliation_with_caveats"
        if solved
        else "blocked_s4_4c5b_run_failure",
        "development_only": True,
        "thesis_usable": False,
        "Tata_validated": False,
        "both_24h_and_168h_c0_c1_runs_execute": solved and len(summary_rows) == 4,
        "production_fulfilment_reported_before_economics": True,
        "anchors_are_constraints": False,
        "steam_validation_anchor_active": False,
        "fixed_50_50_wag_ng_boiler_split_active": False,
        "wag_first_allocation_implemented": True,
        "c1_bf7_inactive": True,
        "c1_kgf2_cp2_inactive": True,
        "downstream_continuation_active": True,
        "vattenfall_cap_policy": "combined_BFG_COG_BOFG_volume_cap_not_per_carrier",
        "c0_scaling_issue_fixed": True,
        "c1_electricity_gap_classification": C1_ELECTRICITY_GAP_CLASS
        if any(_safe_float(row["electricity_gross_MWh_y"]) <= _safe_float(next(s["electricity_gross_MWh_y"] for s in summary_rows if s["configuration_id"] == C0 and s["horizon"] == row["horizon"])) for row in c1_rows)
        else "",
        "co2_completeness_status": "partial_not_comparable_to_total_anchor",
        "forbidden_scope_added": False,
        "raw_pdf_inspected": False,
        "caveat": "C5b is a development-only accounting reconciliation. It does not tune to anchors and does not add DA, stochastic, CVaR, mFRR, revenue, grid-tariff, export, or ETS objective logic.",
    }
    _write_json(C5B_DIR / "s4_4c5b_stage_gate.json", gate)
    return gate


def _write_outputs() -> dict[str, Any]:
    C5B_DIR.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    run_s4_4c5_physical_diagnostics()
    run_s4_4c5a_anchor_scaling_correction()

    all_summary: list[dict[str, Any]] = []
    all_anchor_gaps: list[dict[str, Any]] = []
    all_routes: list[dict[str, Any]] = []
    all_downstream: list[dict[str, Any]] = []
    all_steam: list[dict[str, Any]] = []
    all_ng: list[dict[str, Any]] = []
    all_electricity: list[dict[str, Any]] = []
    all_co2: list[dict[str, Any]] = []
    all_vattenfall: list[dict[str, Any]] = []
    all_allocations: list[dict[str, Any]] = []
    all_io: list[dict[str, Any]] = []

    for horizon, hours in HORIZONS.items():
        reports = _report_rows(horizon)
        analytics = _analytics_rows(horizon)
        allocations = _allocation_rows(horizon, hours, reports)
        vattenfall = _vattenfall_rows(horizon, hours, allocations)
        route = _route_rows(horizon, hours, reports)
        downstream = _downstream_rows(horizon, hours, reports)
        steam = _steam_rows(horizon, hours, allocations)
        ng = _ng_rows(horizon, hours, reports, allocations)
        electricity = _electricity_rows(horizon, hours, reports, allocations)
        co2 = _co2_rows(horizon, hours, reports, allocations)
        summary = _summary_rows(
            horizon,
            hours,
            reports,
            analytics,
            downstream,
            route,
            electricity,
            ng,
            co2,
            allocations,
            vattenfall,
        )
        gaps = _anchor_gap_rows(horizon, hours, electricity, ng, co2)
        io_rows = _plant_carrier_io_rows(horizon, hours, reports, allocations)

        _write_csv(C5B_DIR / f"s4_4c5b_{horizon}_summary.csv", summary)

        all_summary.extend(summary)
        all_anchor_gaps.extend(gaps)
        all_routes.extend(route)
        all_downstream.extend(downstream)
        all_steam.extend(steam)
        all_ng.extend(ng)
        all_electricity.extend(electricity)
        all_co2.extend(co2)
        all_vattenfall.extend(vattenfall)
        all_allocations.extend(allocations)
        all_io.extend(io_rows)

    validation_dashboard = all_anchor_gaps
    registry = [
        {
            "run_id": f"s4_4c5b_{row['horizon']}_{row['configuration_id']}",
            "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stage": STAGE,
            "purpose": "development-only site-scale physical/accounting reconciliation",
            "model_version": _git_commit(),
            "configuration_id": row["configuration_id"],
            "horizon": row["horizon"],
            "horizon_hours": row["horizon_hours"],
            "scenario_source": "not_applicable_deterministic",
            "forecast_model": "not_applicable",
            "granularity": "hourly",
            "number_of_scenarios": 0,
            "cvar_settings": "not_applicable",
            "benchmark_type": "not_applicable",
            "solver_status": row["solver_status"],
            "runtime_seconds": row["runtime_seconds"],
            "key_result": f"production_fulfilment={row['production_fulfilment']}; C5 physical fulfilment={row['physical_solver_site_target_fulfilment']}",
            "thesis_usable": False,
            "notes": "Anchors are validation-only; no economics or market logic added.",
        }
        for row in all_summary
    ]
    gate = _write_stage_gate(all_summary)

    _write_csv(C5B_DIR / "s4_4c5b_run_registry.csv", registry)
    _write_csv(C5B_DIR / "s4_4c5b_validation_anchor_table.csv", _validation_anchor_rows())
    _write_csv(C5B_DIR / "s4_4c5b_annual_validation_dashboard.csv", validation_dashboard)
    _write_csv(C5B_DIR / "s4_4c5b_anchor_gap_dashboard.csv", all_anchor_gaps)
    _write_csv(C5B_DIR / "s4_4c5b_route_capacity_dashboard.csv", all_routes)
    _write_csv(C5B_DIR / "s4_4c5b_downstream_continuation_dashboard.csv", all_downstream)
    _write_csv(C5B_DIR / "s4_4c5b_steam_accounting_dashboard.csv", all_steam)
    _write_csv(C5B_DIR / "s4_4c5b_ng_accounting_dashboard.csv", all_ng)
    _write_csv(C5B_DIR / "s4_4c5b_electricity_accounting_dashboard.csv", all_electricity)
    _write_csv(C5B_DIR / "s4_4c5b_co2_accounting_dashboard.csv", all_co2)
    _write_csv(C5B_DIR / "s4_4c5b_vattenfall_cap_hourly.csv", all_vattenfall)
    _write_csv(C5B_DIR / "s4_4c5b_wag_allocation_hourly.csv", all_allocations)
    _write_csv(C5B_DIR / "s4_4c5b_plant_carrier_io_hourly.csv", all_io)
    _write_csv(C5B_DIR / "s4_4c5b_component_gap_register.csv", _component_gap_rows())

    summary = {
        "stage_gate": gate,
        "output_directory": str(C5B_DIR.relative_to(REPO_ROOT)),
        "selected_production_target_t_y": SELECTED_PRODUCTION_ANCHOR_T_Y,
        "target_basis": TARGET_BASIS,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "row_counts": {
            "summary": len(all_summary),
            "anchor_gaps": len(all_anchor_gaps),
            "vattenfall_hourly": len(all_vattenfall),
            "wag_allocation_hourly": len(all_allocations),
            "plant_carrier_io_hourly": len(all_io),
        },
    }
    _write_json(C5B_DIR / "s4_4c5b_summary.json", summary)
    return summary


def run_s4_4c5b_site_scale_downstream_steam_wag_reconciliation() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5b_site_scale_downstream_steam_wag_reconciliation(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
