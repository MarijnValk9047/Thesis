from __future__ import annotations

from typing import Any

from pyomo.environ import value


HOURS_PER_YEAR = 8760.0
GJ_PER_MWH = 3.6
GJ_PER_PJ = 1_000_000.0
MWH_PER_TWH = 1_000_000.0


def _value(expr: Any) -> float:
    return float(value(expr))


def _sum_time(model: Any, component_name: str) -> float:
    component = getattr(model, component_name)
    return float(sum(value(component[t]) for t in model.TIME))


def _sum_carrier_time(model: Any, component_name: str, carrier: str) -> float:
    component = getattr(model, component_name)
    return float(sum(value(component[carrier, t]) for t in model.TIME))


def _sum_time_if_present(model: Any, component_name: str) -> float:
    if not hasattr(model, component_name):
        return 0.0
    return _sum_time(model, component_name)


def _sum_all_carriers_time_if_present(model: Any, component_name: str) -> float:
    if not hasattr(model, component_name):
        return 0.0
    component = getattr(model, component_name)
    return float(sum(value(component[carrier, t]) for carrier in model.WAG_CARRIERS for t in model.TIME))


def _max_equality_residual(constraints: Any) -> float:
    residuals: list[float] = []
    for constraint in constraints:
        if not constraint.equality:
            continue
        residuals.append(abs(float(value(constraint.body)) - float(value(constraint.lower))))
    return max(residuals) if residuals else 0.0


def _annual_factor(horizon_hours: int) -> float:
    return HOURS_PER_YEAR / float(horizon_hours)


def _safe_ratio(numerator: float, denominator: float) -> float:
    return 0.0 if abs(denominator) <= 1e-12 else numerator / denominator


def collect_site_validation_metrics(
    model: Any,
    *,
    residual_ng_m3_per_t_final: float,
    coal_primary_energy_factor_gj_per_t_dry_coal: float,
) -> dict[str, float | str | bool]:
    """Collect annualised S3.3 calibration metrics from a solved S3.2-compatible model.

    The adapter deliberately separates gross electricity, WAG electricity, and net
    grid import. WAG fuel energy is reported as internal conversion energy and is
    not added again to the Athanasiadis-compatible primary-energy proxy.
    """

    horizon_hours = len(model.TIME)
    factor = _annual_factor(horizon_hours)
    final_product_t = _value(model.horizon_final_product_output)
    final_product_t_per_h = final_product_t / float(horizon_hours)
    annual_final_product_t = final_product_t * factor
    route_total = _value(model.route_total_liquid_steel_source)
    bof_t = _value(model.bof_route_total)
    eaf_t = _value(model.eaf_route_total)

    gross_electricity_mwh = _value(model.horizon_gross_electricity_mwh)
    wag_electricity_mwh = _value(model.horizon_wag_power_output_mwh)
    grid_import_mwh = _value(model.horizon_grid_import_mwh)

    model_ng_gj = _value(model.horizon_natural_gas_import_gj)
    lhv_gj_per_m3 = float(model.s3_1_assumptions.natural_gas_energy_content_gj_per_m3)
    model_ng_m3 = model_ng_gj / lhv_gj_per_m3 if lhv_gj_per_m3 > 0 else 0.0
    residual_ng_m3 = residual_ng_m3_per_t_final * final_product_t
    total_ng_m3 = model_ng_m3 + residual_ng_m3
    total_ng_gj = total_ng_m3 * lhv_gj_per_m3
    drp_ng_m3 = _value(model.horizon_drp_natural_gas_m3) if hasattr(model, "horizon_drp_natural_gas_m3") else 0.0
    steam_ng_gj = _sum_time_if_present(model, "natural_gas_steam_gj")
    reheating_ng_gj = _sum_time_if_present(model, "natural_gas_reheating_gj")
    utility_heat_ng_gj = _sum_time_if_present(model, "natural_gas_utility_heat_gj")
    steam_ng_m3 = steam_ng_gj / lhv_gj_per_m3 if lhv_gj_per_m3 > 0 else 0.0
    reheating_ng_m3 = reheating_ng_gj / lhv_gj_per_m3 if lhv_gj_per_m3 > 0 else 0.0
    utility_heat_ng_m3 = utility_heat_ng_gj / lhv_gj_per_m3 if lhv_gj_per_m3 > 0 else 0.0

    dry_coal_t = _sum_time(model, "cog_dry_coal_driver_t")
    external_coal_gj = dry_coal_t * coal_primary_energy_factor_gj_per_t_dry_coal
    gross_electricity_gj = gross_electricity_mwh * GJ_PER_MWH
    net_grid_gj = grid_import_mwh * GJ_PER_MWH
    physical_external_energy_gj = external_coal_gj + total_ng_gj + net_grid_gj
    athanasiadis_primary_proxy_gj = external_coal_gj + total_ng_gj + gross_electricity_gj

    total_wag_generated_gj = _value(model.horizon_total_wag_generated_gj)
    flare_gj = _value(model.horizon_flare_spill_gj)
    direct_co2_t = _value(model.horizon_s3_2_total_direct_co2_t)
    scope2_t = _value(model.scope2_operational_co2_t)
    total_direct_plus_scope2_t = _value(model.total_location_based_direct_plus_scope2_t)

    bfg_gj = _sum_time(model, "bfg_generated_gj")
    cog_gj = _sum_time(model, "cog_generated_gj")
    bofg_gj = _sum_time(model, "bofg_generated_gj")
    wag_process_use_gj = _sum_all_carriers_time_if_present(model, "wag_process_use_gj")
    wag_steam_boiler_use_gj = _sum_all_carriers_time_if_present(model, "wag_steam_boiler_use_gj")
    wag_reheating_use_gj = _sum_all_carriers_time_if_present(model, "wag_reheating_use_gj")
    wag_utility_heat_use_gj = _sum_all_carriers_time_if_present(model, "wag_utility_heat_use_gj")
    wag_power_use_gj = _sum_all_carriers_time_if_present(model, "wag_power_use_gj")
    utility_heat_demand_gj = _sum_time_if_present(model, "downstream_light_side_utility_heat_demand_gj")

    max_cold = max(float(value(model.cold_slab_inventory[t])) for t in model.TIME)
    last_t = max(model.TIME)
    cold_terminal_target = (
        model.s2_13_assumptions.initial_cold_slab_inventory_t
        * model.s2_13_assumptions.terminal_cold_inventory_ratio
    )
    terminal_cold_residual = abs(float(value(model.cold_slab_inventory[last_t])) - cold_terminal_target)
    terminal_hot_residual = abs(
        sum(float(value(model.hot_slab_inventory[age, last_t])) for age in model.HOT_AGES)
        - model.s2_13_assumptions.terminal_hot_slab_inventory_t
    )
    terminal_reheated_residual = abs(
        float(value(model.reheated_slab_queue[last_t]))
        - model.s2_13_assumptions.terminal_reheated_queue_t
    )

    carrier_proxy = athanasiadis_primary_proxy_gj
    return {
        "horizon_hours": float(horizon_hours),
        "annualised_final_product_t": annual_final_product_t,
        "final_product_t_per_h": final_product_t_per_h,
        "horizon_final_product_t": final_product_t,
        "bf_bof_share": _safe_ratio(bof_t, route_total),
        "drp_eaf_share": _safe_ratio(eaf_t, route_total),
        "gross_electricity_twh_per_year": gross_electricity_mwh * factor / MWH_PER_TWH,
        "wag_electricity_twh_per_year": wag_electricity_mwh * factor / MWH_PER_TWH,
        "net_grid_import_twh_per_year": grid_import_mwh * factor / MWH_PER_TWH,
        "natural_gas_m3_per_h": total_ng_m3 / float(horizon_hours),
        "model_natural_gas_m3_per_h": model_ng_m3 / float(horizon_hours),
        "explicit_drp_natural_gas_m3_per_h": drp_ng_m3 / float(horizon_hours),
        "steam_boiler_natural_gas_m3_per_h": steam_ng_m3 / float(horizon_hours),
        "reheating_natural_gas_m3_per_h": reheating_ng_m3 / float(horizon_hours),
        "utility_heat_natural_gas_m3_per_h": utility_heat_ng_m3 / float(horizon_hours),
        "represented_steam_reheating_ng_m3_per_h": (steam_ng_m3 + reheating_ng_m3) / float(horizon_hours),
        "represented_steam_reheating_utility_ng_m3_per_h": (
            steam_ng_m3 + reheating_ng_m3 + utility_heat_ng_m3
        )
        / float(horizon_hours),
        "residual_ng_m3_per_h": residual_ng_m3 / float(horizon_hours),
        "residual_ng_m3_per_t_final": residual_ng_m3_per_t_final,
        "natural_gas_pj_per_year": total_ng_gj * factor / GJ_PER_PJ,
        "model_natural_gas_pj_per_year": model_ng_gj * factor / GJ_PER_PJ,
        "explicit_drp_natural_gas_pj_per_year": drp_ng_m3 * lhv_gj_per_m3 * factor / GJ_PER_PJ,
        "steam_boiler_natural_gas_pj_per_year": steam_ng_gj * factor / GJ_PER_PJ,
        "reheating_natural_gas_pj_per_year": reheating_ng_gj * factor / GJ_PER_PJ,
        "utility_heat_natural_gas_pj_per_year": utility_heat_ng_gj * factor / GJ_PER_PJ,
        "residual_ng_pj_per_year": residual_ng_m3 * lhv_gj_per_m3 * factor / GJ_PER_PJ,
        "external_coal_origin_energy_pj_per_year": external_coal_gj * factor / GJ_PER_PJ,
        "gross_electricity_energy_pj_per_year": gross_electricity_gj * factor / GJ_PER_PJ,
        "net_grid_energy_pj_per_year": net_grid_gj * factor / GJ_PER_PJ,
        "total_physical_external_energy_pj_per_year": physical_external_energy_gj * factor / GJ_PER_PJ,
        "athanasiadis_primary_proxy_pj_per_year": athanasiadis_primary_proxy_gj * factor / GJ_PER_PJ,
        "coal_share_athanasiadis_proxy": _safe_ratio(external_coal_gj, carrier_proxy),
        "electricity_share_athanasiadis_proxy": _safe_ratio(gross_electricity_gj, carrier_proxy),
        "natural_gas_share_athanasiadis_proxy": _safe_ratio(total_ng_gj, carrier_proxy),
        "direct_site_co2_t_per_year": direct_co2_t * factor,
        "scope2_t_per_year": scope2_t * factor,
        "direct_plus_scope2_t_per_year": total_direct_plus_scope2_t * factor,
        "bfg_generated_pj_per_year": bfg_gj * factor / GJ_PER_PJ,
        "cog_generated_pj_per_year": cog_gj * factor / GJ_PER_PJ,
        "bofg_generated_pj_per_year": bofg_gj * factor / GJ_PER_PJ,
        "total_wag_generated_pj_per_year": total_wag_generated_gj * factor / GJ_PER_PJ,
        "wag_process_use_pj_per_year": wag_process_use_gj * factor / GJ_PER_PJ,
        "wag_steam_boiler_use_pj_per_year": wag_steam_boiler_use_gj * factor / GJ_PER_PJ,
        "wag_reheating_use_pj_per_year": wag_reheating_use_gj * factor / GJ_PER_PJ,
        "wag_utility_heat_use_pj_per_year": wag_utility_heat_use_gj * factor / GJ_PER_PJ,
        "wag_power_fuel_use_pj_per_year": wag_power_use_gj * factor / GJ_PER_PJ,
        "downstream_light_side_utility_heat_demand_pj_per_year": utility_heat_demand_gj
        * factor
        / GJ_PER_PJ,
        "flare_pj_per_year": flare_gj * factor / GJ_PER_PJ,
        "flare_fraction_of_wag_generated": _safe_ratio(flare_gj, total_wag_generated_gj),
        "gj_per_t_final_athanasiadis_proxy": _safe_ratio(athanasiadis_primary_proxy_gj, final_product_t),
        "mwh_gross_electricity_per_t": _safe_ratio(gross_electricity_mwh, final_product_t),
        "mwh_wag_electricity_per_t": _safe_ratio(wag_electricity_mwh, final_product_t),
        "m3_ng_per_t": _safe_ratio(total_ng_m3, final_product_t),
        "tco2_direct_per_t": _safe_ratio(direct_co2_t, final_product_t),
        "max_cold_slab_inventory_t": max_cold,
        "slab_yard_capacity_t": float(model.s2_13_assumptions.slab_yard_capacity_t),
        "hot_metal_capacity_t": 500.0,
        "terminal_cold_residual_t": terminal_cold_residual,
        "terminal_hot_residual_t": terminal_hot_residual,
        "terminal_reheated_residual_t": terminal_reheated_residual,
        "max_wag_balance_residual_gj": _max_equality_residual(model.wag_carrier_balance.values()),
        "max_electricity_balance_residual_mwh": _max_equality_residual(model.grid_import_balance.values()),
        "max_carbon_decomposition_residual_t": _max_equality_residual(
            list(model.drp_direct_co2_decomposition.values())
            + list(model.bf_bof_direct_co2_decomposition.values())
        ),
        "wag_double_counted_in_primary_proxy": False,
    }


TARGET_TO_METRIC_KEY = {
    "C0_TABLE8_GROSS_ELECTRICITY": "gross_electricity_twh_per_year",
    "C0_TABLE8_WAG_ELECTRICITY": "wag_electricity_twh_per_year",
    "C0_TABLE8_NATURAL_GAS_FLOW": "natural_gas_m3_per_h",
    "C0_TABLE8_DIRECT_CO2": "direct_site_co2_t_per_year",
    "C0_FIG96_TOTAL_PRIMARY_PROXY": "athanasiadis_primary_proxy_pj_per_year",
    "C0_NORMAL_FLARE_FRACTION": "flare_fraction_of_wag_generated",
}


def calibration_error_rows(
    metrics: dict[str, float | str | bool],
    target_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in target_rows:
        target_id = str(target["target_id"])
        metric_key = TARGET_TO_METRIC_KEY.get(target_id)
        if metric_key is None:
            continue
        target_value = float(target["value"])
        actual = float(metrics[metric_key])
        tolerance_pct = float(target.get("tolerance_pct", 0.0) or 0.0)
        absolute_error = actual - target_value
        percentage_error = 0.0 if abs(target_value) <= 1e-12 else absolute_error / target_value
        tolerance_normalised_abs_error = (
            abs(percentage_error) / (tolerance_pct / 100.0)
            if tolerance_pct > 0.0
            else abs(percentage_error)
        )
        rows.append(
            {
                "target_id": target_id,
                "metric": target["metric"],
                "actual_value": actual,
                "target_value": target_value,
                "unit": target["unit"],
                "absolute_error": absolute_error,
                "percentage_error": percentage_error,
                "tolerance_pct": tolerance_pct,
                "tolerance_normalised_abs_error": tolerance_normalised_abs_error,
                "role": target["role"],
            }
        )
    return rows
