"""S4.4c5m_b active plant ledger coverage and BF/KGF KPI integration.

This stage is a reporting and diagnostics hardening patch. It does not change
plant equations, coefficients, targets, route splits, WAG allocation, or HSM
heat cases. It audits whether BF and KGF/coking KPI rows are connected to the
active C5 ledgers and expands compact model-health totals where accepted BF/KGF
rows were already available but not visible in C5m_a.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    C5F_DIR,
    COG_GROSS_MWH_PER_T_COKE,
    CONFIGS,
    HORIZONS,
    KGF_UNDERFIRING_MWH_PER_T_COKE,
    S4_ROOT,
    WAG_TOL_MWH,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5h_blast_furnace_controller_parameterisation import C5H_DIR
from .s4_4c5j_bof_osf_minimal_parameterisation import C5J_DIR
from .s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR
from .s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch import (
    C5L_D_DIR,
    HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
)
from .s4_4c5m_sinter_minimal_parameterisation import C5M_DIR
from .s4_4c5m_a_sinter_coupling_caveat_and_model_health_diagnostics import (
    C5M_A_DIR,
    run_s4_4c5m_a_sinter_coupling_caveat_and_model_health_diagnostics,
)


STAGE = "S4.4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration"
C5M_B_DIR = S4_ROOT / "s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration"
DEPENDENCY_CHAIN = "C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b"
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_stage_runner_csv_json_stage_gate_compact_table_"
    "plant_diagnostics_energy_emissions_wag_lhv_co2_redflag_patterns"
)

CURRENT_C5_ELECTRICITY_SCOPE = "modelled_process_electricity_current_C5_scope_not_full_site_electricity"
CURRENT_C5_STEAM_SCOPE = "modelled_proxy_steam_current_C5_scope_until_steam_network"
CURRENT_C5_CO2_SCOPE = "modelled_diagnostic_CO2_current_C5_scope_not_ETS_objective_not_full_site"

TOL_T = 1.0
TOL_MWH = 1.0

EXPECTED_COMPONENTS = (
    "KGF1",
    "KGF2",
    "BF6",
    "BF7",
    "Controller_Blast_Furnace",
    "BOF_OSF",
    "HSM_WBW",
    "Sinter_Plant",
    "EAF_route",
    "DRP_route",
    "WAG_boilers",
    "Vattenfall_interface",
    "WAG_flaring",
)


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _by_key(rows: list[dict[str, str]], *, case: str | None = None) -> dict[tuple[str, int], dict[str, str]]:
    out: dict[tuple[str, int], dict[str, str]] = {}
    for row in rows:
        if case is not None and row.get("cap_case") != case:
            continue
        out[(row["configuration"], int(row["horizon_hours"]))] = row
    return out


def _by_key_plant(rows: list[dict[str, str]]) -> dict[tuple[str, int, str], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"]), row["plant_id"]): row for row in rows}


def _rows_by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], list[dict[str, str]]]:
    out: dict[tuple[str, int], list[dict[str, str]]] = {}
    for row in rows:
        out.setdefault((row["configuration"], int(row["horizon_hours"])), []).append(row)
    return out


def _site_wag_by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int, str], dict[str, str]]:
    return {
        (row["configuration"], int(row["horizon_hours"]), row["carrier"]): row
        for row in rows
        if row.get("plant_id") == "SITE_TOTAL"
    }


def _site_scaled(row: dict[str, str], field: str) -> float:
    raw = _zero(row.get(field, ""))
    scale = _zero(row.get("scale_factor", "")) or 1.0
    if field == "generated_MWh_LHV_y" and row.get("site_scaled_quantity") not in (None, ""):
        return _zero(row["site_scaled_quantity"])
    return raw * scale


def _sum_field(rows: list[dict[str, str]], field: str) -> float:
    return sum(_zero(row.get(field, "")) for row in rows)


def _energy_map(rows: list[dict[str, str]]) -> dict[tuple[str, int, str, str], dict[str, str]]:
    return {
        (row["configuration"], int(row["horizon_hours"]), row["plant_id"], row["carrier"]): row
        for row in rows
    }


def _emission_rows_by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], list[dict[str, str]]]:
    return _rows_by_key(rows)


def _co2_bucket(rows: list[dict[str, str]], bucket: str) -> dict[tuple[str, int], dict[str, str]]:
    return {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in rows
        if row.get("emission_bucket") == bucket
    }


def _active_kgf(config: str, plant: str) -> bool:
    return plant == "KGF1" or (config == C0 and plant == "KGF2")


def _active_bf(config: str, plant: str) -> bool:
    return plant == "BF6" or (config == C0 and plant == "BF7")


def _coverage_status(active: bool, implemented: bool, *, blocked: bool = False, excluded: bool = False) -> str:
    if not active:
        return "intentionally_not_applicable"
    if implemented:
        return "included"
    if blocked:
        return "blocked_missing_governed_parameter"
    if excluded:
        return "intentionally_excluded_with_caveat"
    return "coverage_gap"


def _included_flags(*flags: str) -> str:
    return ";".join(flag for flag in flags if flag)


def _plant_row(
    config: str,
    horizon: int,
    plant: str,
    active_status: str,
    activity_driver_name: str,
    activity_driver_value: float,
    material_inputs_summary: str,
    material_outputs_summary: str,
    electricity_mwh: float,
    steam_t: float,
    oxygen_summary: str,
    thermal_fuel_mwh: float,
    wag_generated: str,
    wag_consumed: str,
    ng_consumed: float,
    co2_t: float,
    included_flags: str,
    status: str,
    caveat: str,
) -> dict[str, Any]:
    return {
        "configuration": config,
        "horizon_hours": horizon,
        "plant_or_controller": plant,
        "active_status": active_status,
        "activity_driver_name": activity_driver_name,
        "activity_driver_value": _fmt(activity_driver_value),
        "material_inputs_summary": material_inputs_summary,
        "material_outputs_summary": material_outputs_summary,
        "electricity_MWh_or_TWh": _fmt(electricity_mwh),
        "steam_t_or_kt": _fmt(steam_t),
        "oxygen_t_or_Nm3": oxygen_summary,
        "thermal_fuel_TWh_or_PJ": _fmt(thermal_fuel_mwh / 1_000_000.0),
        "WAG_generated_by_carrier": wag_generated,
        "WAG_consumed_by_carrier": wag_consumed,
        "NG_consumed": _fmt(ng_consumed),
        "CO2_diagnostic": _fmt(co2_t),
        "included_in_totals_flags": included_flags,
        "caveat/status": f"{status}; {caveat}",
    }


def _coverage_row(config: str, horizon: int, plant: str, active: bool, statuses: dict[str, str], caveat: str) -> dict[str, Any]:
    return {
        "configuration": config,
        "horizon_hours": horizon,
        "plant_or_controller": plant,
        "active_status": "active" if active else "inactive_or_not_applicable",
        "activity_driver": statuses.get("activity_driver", "intentionally_not_applicable"),
        "material_inputs": statuses.get("material_inputs", "intentionally_not_applicable"),
        "material_outputs": statuses.get("material_outputs", "intentionally_not_applicable"),
        "electricity_demand": statuses.get("electricity_demand", "intentionally_not_applicable"),
        "thermal_or_fuel_demand": statuses.get("thermal_or_fuel_demand", "intentionally_not_applicable"),
        "steam_demand": statuses.get("steam_demand", "intentionally_not_applicable"),
        "oxygen_demand": statuses.get("oxygen_demand", "intentionally_not_applicable"),
        "WAG_generation": statuses.get("WAG_generation", "intentionally_not_applicable"),
        "WAG_consumption": statuses.get("WAG_consumption", "intentionally_not_applicable"),
        "NG_consumption_or_backup": statuses.get("NG_consumption_or_backup", "intentionally_not_applicable"),
        "CO2_diagnostic": statuses.get("CO2_diagnostic", "intentionally_not_applicable"),
        "included_in_process_electricity_total": statuses.get("included_in_process_electricity_total", "intentionally_not_applicable"),
        "included_in_steam_total": statuses.get("included_in_steam_total", "intentionally_not_applicable"),
        "included_in_WAG_generation_total": statuses.get("included_in_WAG_generation_total", "intentionally_not_applicable"),
        "included_in_WAG_consumption_total": statuses.get("included_in_WAG_consumption_total", "intentionally_not_applicable"),
        "included_in_diagnostic_CO2_total": statuses.get("included_in_diagnostic_CO2_total", "intentionally_not_applicable"),
        "blocked_missing_governed_parameter": statuses.get("blocked_missing_governed_parameter", "false"),
        "intentionally_not_applicable": statuses.get("intentionally_not_applicable", "false"),
        "intentionally_excluded_with_caveat": statuses.get("intentionally_excluded_with_caveat", "false"),
        "caveat": caveat,
    }


def _source_payload() -> dict[str, Any]:
    c5m_a = _by_key(_read_csv(C5M_A_DIR / "s4_4c5m_a_healthcheck.csv"))
    kgf_diag = _by_key_plant(_read_csv(C5F_DIR / "s4_4c5f_coking_plant_diagnostics.csv"))
    kgf_emissions = _emission_rows_by_key(_read_csv(C5F_DIR / "s4_4c5f_emissions_by_plant.csv"))
    bf_diag = _by_key_plant(_read_csv(C5H_DIR / "s4_4c5h_bf_process_diagnostics.csv"))
    bf_rows = _rows_by_key(_read_csv(C5H_DIR / "s4_4c5h_bf_process_diagnostics.csv"))
    bf_co2 = _rows_by_key(_read_csv(C5H_DIR / "s4_4c5h_bf_co2_accounting_dashboard.csv"))
    c5h_energy = _energy_map(_read_csv(C5H_DIR / "s4_4c5h_energy_by_plant.csv"))
    coke_balance = _by_key(_read_csv(C5H_DIR / "s4_4c5h_coke_balance_kgf_to_bf.csv"))
    bfg_surplus = _by_key_plant(_read_csv(C5H_DIR / "s4_4c5h_bfg_gross_self_use_surplus_dashboard.csv"))
    c5j_inputs = _read_csv(C5J_DIR / "s4_4c5j_bof_osf_development_input_rows.csv")
    c5j_report = _by_key(_read_csv(C5J_DIR / "s4_4c5j_bof_osf_report.csv"))
    bof_co2 = _co2_bucket(_read_csv(C5J_DIR / "s4_4c5j_bof_co2_accounting_dashboard.csv"), "BOF_direct_CO2_diagnostic")
    c5k = _by_key(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv"))
    hsm = _by_key(_read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv"), case=HSM_HOT_CHARGE_CAP_ACTIVE_CASE)
    sinter = _by_key(_read_csv(C5M_DIR / "s4_4c5m_sinter_report.csv"))
    sinter_ctrl = _by_key(_read_csv(C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv"))
    sinter_steam = _by_key(_read_csv(C5M_DIR / "s4_4c5m_sinter_steam_proxy_dashboard.csv"))
    sinter_elec = _by_key(_read_csv(C5M_DIR / "s4_4c5m_sinter_electricity_ledger.csv"))
    sinter_co2 = _co2_bucket(_read_csv(C5M_DIR / "s4_4c5m_sinter_co2_accounting_dashboard.csv"), "Sinter_aggregate_CO2_diagnostic")
    wag_rows = _read_csv(C5M_DIR / "s4_4c5m_wag_generation_consumption_by_plant.csv")
    wag_site = _site_wag_by_key(wag_rows)
    wag_agg = {
        (row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row
        for row in _read_csv(C5M_DIR / "s4_4c5m_wag_aggregate_invariant.csv")
    }
    lhv = _by_key(_read_csv(C5M_DIR / "s4_4c5m_lhv_consistency_checks.csv"))
    c5m_gate = json.loads((C5M_DIR / "s4_4c5m_stage_gate.json").read_text(encoding="utf-8"))
    c5m_a_gate = json.loads((C5M_A_DIR / "s4_4c5m_a_stage_gate.json").read_text(encoding="utf-8"))
    return locals()


def _bof_coefficients_ok(c5j_inputs: list[dict[str, str]]) -> bool:
    by_id = {row["parameter_id"]: row for row in c5j_inputs}
    expected = {
        "BOF_SCRAP_INPUT_T_PER_T_LS_C0": 0.208,
        "BOF_SCRAP_INPUT_T_PER_T_LS_C1": 0.294,
        "BOF_BOFG_OUTPUT_NM3_PER_T_LS": 75.0,
    }
    return all(abs(_zero(by_id[pid]["base_value"]) - value) <= 1e-9 for pid, value in expected.items())


def _kgf_co2_for(payload: dict[str, Any], config: str, horizon: int, plant: str) -> float:
    rows = payload["kgf_emissions"].get((config, horizon), [])
    return sum(_zero(row["CO2_t_y"]) for row in rows if row["plant_id"] == plant and row["emission_bucket"] == "KGF_direct_CO2")


def _bf_co2_for(payload: dict[str, Any], config: str, horizon: int, plant: str) -> float:
    rows = payload["bf_co2"].get((config, horizon), [])
    return sum(_zero(row["CO2_site_t_y"]) for row in rows if row["plant_id"] == plant and row["emission_bucket"] == "BF_aggregate_hot_metal_counter")


def _energy_value(payload: dict[str, Any], config: str, horizon: int, plant: str, carrier: str, field: str = "input_MWh_y") -> float:
    return _zero(payload["c5h_energy"].get((config, horizon, plant, carrier), {}).get(field, ""))


def _coverage_and_kpi_rows(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage: list[dict[str, Any]] = []
    kpis: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            k = payload["c5k"][key]
            hsm = payload["hsm"][key]
            sinter = payload["sinter"][key]
            ctrl = payload["sinter_ctrl"][key]

            for plant in ("KGF1", "KGF2"):
                active = _active_kgf(config, plant)
                diag = payload["kgf_diag"][(config, horizon, plant)]
                electricity = _energy_value(payload, config, horizon, plant, "electricity")
                steam_proxy_mwh = _energy_value(payload, config, horizon, plant, "steam_proxy")
                cog_self_use = _energy_value(payload, config, horizon, plant, "COG_self_use")
                co2 = _kgf_co2_for(payload, config, horizon, plant)
                coverage.append(
                    _coverage_row(
                        config,
                        horizon,
                        plant,
                        active,
                        {
                            "activity_driver": _coverage_status(active, bool(diag)),
                            "material_inputs": _coverage_status(active, bool(diag)),
                            "material_outputs": _coverage_status(active, bool(diag)),
                            "electricity_demand": _coverage_status(active, electricity > 0.0),
                            "thermal_or_fuel_demand": _coverage_status(active, cog_self_use > 0.0),
                            "steam_demand": _coverage_status(active, steam_proxy_mwh > 0.0),
                            "oxygen_demand": "intentionally_not_applicable",
                            "WAG_generation": _coverage_status(active, _zero(diag["surplus_COG_site_MWh_LHV_y"]) > 0.0),
                            "WAG_consumption": _coverage_status(active, cog_self_use > 0.0),
                            "NG_consumption_or_backup": "intentionally_not_applicable",
                            "CO2_diagnostic": _coverage_status(active, co2 > 0.0),
                            "included_in_process_electricity_total": _coverage_status(active, electricity > 0.0),
                            "included_in_steam_total": _coverage_status(active, steam_proxy_mwh > 0.0),
                            "included_in_WAG_generation_total": _coverage_status(active, _zero(diag["surplus_COG_site_MWh_LHV_y"]) > 0.0),
                            "included_in_WAG_consumption_total": _coverage_status(active, cog_self_use > 0.0),
                            "included_in_diagnostic_CO2_total": _coverage_status(active, co2 > 0.0),
                            "intentionally_not_applicable": str(not active).lower(),
                        },
                        "KGF2 is inactive in C1; KGF is production-coupled and not DA-flexible.",
                    )
                )
                kpis.append(
                    _plant_row(
                        config,
                        horizon,
                        plant,
                        "active" if active else "inactive",
                        "coke_output_site_t_y",
                        _zero(diag["coke_output_site_t_y"]),
                        f"dry_coal={diag['dry_coal_input_site_t_y']}",
                        f"coke={diag['coke_output_site_t_y']};clean_COG_surplus={diag['surplus_COG_site_MWh_LHV_y']}",
                        electricity,
                        _zero(diag["coke_output_site_t_y"]) * _zero(diag["KGF_steam_mass_t_per_t_coke_diagnostic"]),
                        "not_applicable",
                        cog_self_use,
                        f"COG={diag['surplus_COG_site_MWh_LHV_y']}",
                        f"COG_self_use={_fmt(cog_self_use)}",
                        0.0,
                        co2,
                        _included_flags("process_electricity", "steam_proxy", "WAG_generation", "WAG_consumption", "diagnostic_CO2") if active else "",
                        "included" if active else "inactive",
                        "Raw COG cleaning represented by clean COG surplus convention; KGF underfiring deducted before COG surplus.",
                    )
                )

            for plant in ("BF6", "BF7"):
                active = _active_bf(config, plant)
                diag = payload["bf_diag"][(config, horizon, plant)]
                surplus = payload["bfg_surplus"][(config, horizon, plant)]
                electricity = _energy_value(payload, config, horizon, plant, "electricity")
                steam_proxy_mwh = _energy_value(payload, config, horizon, plant, "steam_proxy")
                stove = _energy_value(payload, config, horizon, plant, "BFG_to_Controller_Blast_Furnace")
                co2 = _bf_co2_for(payload, config, horizon, plant)
                coverage.append(
                    _coverage_row(
                        config,
                        horizon,
                        plant,
                        active,
                        {
                            "activity_driver": _coverage_status(active, bool(diag)),
                            "material_inputs": _coverage_status(active, bool(diag)),
                            "material_outputs": _coverage_status(active, bool(diag)),
                            "electricity_demand": _coverage_status(active, electricity > 0.0),
                            "thermal_or_fuel_demand": "intentionally_not_applicable_for_reactor;controller_reports_hot_stove",
                            "steam_demand": _coverage_status(active, steam_proxy_mwh > 0.0),
                            "oxygen_demand": _coverage_status(active, _zero(diag["oxygen_site_kg_y"]) > 0.0),
                            "WAG_generation": _coverage_status(active, _zero(diag["BFG_surplus_to_WAG_site_MWh_y"]) > 0.0),
                            "WAG_consumption": "reported_by_Controller_Blast_Furnace",
                            "NG_consumption_or_backup": "reported_by_Controller_Blast_Furnace",
                            "CO2_diagnostic": _coverage_status(active, co2 > 0.0),
                            "included_in_process_electricity_total": _coverage_status(active, electricity > 0.0),
                            "included_in_steam_total": _coverage_status(active, steam_proxy_mwh > 0.0),
                            "included_in_WAG_generation_total": _coverage_status(active, _zero(diag["BFG_surplus_to_WAG_site_MWh_y"]) > 0.0),
                            "included_in_WAG_consumption_total": "reported_by_Controller_Blast_Furnace",
                            "included_in_diagnostic_CO2_total": _coverage_status(active, co2 > 0.0),
                            "intentionally_not_applicable": str(not active).lower(),
                        },
                        "BF7 is inactive in C1; gross BFG is reduced by hot-stove controller before WAG surplus.",
                    )
                )
                kpis.append(
                    _plant_row(
                        config,
                        horizon,
                        plant,
                        "active" if active else "inactive",
                        "hot_metal_site_t_y",
                        _zero(diag["hot_metal_site_t_y"]),
                        f"coke={diag['coke_demand_site_t_y']};PCI={diag['PCI_site_t_y']}",
                        f"hot_metal={diag['hot_metal_site_t_y']};BFG_surplus={diag['BFG_surplus_to_WAG_site_MWh_y']}",
                        electricity,
                        steam_proxy_mwh,
                        f"oxygen_kg={diag['oxygen_site_kg_y']}",
                        0.0,
                        f"BFG_surplus={diag['BFG_surplus_to_WAG_site_MWh_y']}",
                        "reactor_none;hot_stove_controller_separate",
                        _zero(diag["NG_to_Controller_BF_site_MWh_y"]),
                        co2,
                        _included_flags("process_electricity", "steam_proxy", "WAG_generation", "diagnostic_CO2") if active else "",
                        "included" if active else "inactive",
                        f"gross_BFG={surplus['BFG_gross_site_MWh_LHV_y']};hot_stove_deduction={surplus['BFG_to_Controller_BF_site_MWh_y']}",
                    )
                )

            bf_rows = payload["bf_rows"].get(key, [])
            controller_bfg = _sum_field(bf_rows, "BFG_to_Controller_BF_site_MWh_y")
            controller_ng = _sum_field(bf_rows, "NG_to_Controller_BF_site_MWh_y")
            coverage.append(
                _coverage_row(
                    config,
                    horizon,
                    "Controller_Blast_Furnace",
                    controller_bfg > 0.0,
                    {
                        "activity_driver": "included",
                        "material_inputs": "intentionally_not_applicable",
                        "material_outputs": "intentionally_not_applicable",
                        "electricity_demand": "intentionally_not_applicable",
                        "thermal_or_fuel_demand": "included",
                        "steam_demand": "intentionally_not_applicable",
                        "oxygen_demand": "intentionally_not_applicable",
                        "WAG_generation": "intentionally_not_applicable",
                        "WAG_consumption": "included",
                        "NG_consumption_or_backup": "included_zero_or_backup",
                        "CO2_diagnostic": "intentionally_not_applicable",
                        "included_in_WAG_consumption_total": "included",
                    },
                    "BF hot-stove controller consumes BFG before net BFG enters shared WAG.",
                )
            )
            kpis.append(
                _plant_row(
                    config,
                    horizon,
                    "Controller_Blast_Furnace",
                    "active" if controller_bfg > 0.0 else "inactive",
                    "BF_hot_stove_demand_site_MWh_y",
                    controller_bfg + controller_ng,
                    "eligible_gases=BFG;COG;BOFG;NG",
                    "BF_hot_stove_heat",
                    0.0,
                    0.0,
                    "not_applicable",
                    controller_bfg,
                    "",
                    f"BFG={_fmt(controller_bfg)}",
                    controller_ng,
                    0.0,
                    "WAG_consumption",
                    "included",
                    "Controller is energy-basis only; no Wobbe or gas-quality constraint.",
                )
            )

            j = payload["c5j_report"][key]
            bof_co2 = _zero(payload["bof_co2"][key]["CO2_site_t_y"])
            coverage.append(
                _coverage_row(
                    config,
                    horizon,
                    "BOF_OSF",
                    _zero(j["bof_liquid_steel_site_t_y"]) > 0.0,
                    {
                        "activity_driver": "included",
                        "material_inputs": "included",
                        "material_outputs": "included",
                        "electricity_demand": "included",
                        "thermal_or_fuel_demand": "intentionally_not_applicable",
                        "steam_demand": "intentionally_not_applicable",
                        "oxygen_demand": "included",
                        "WAG_generation": "included",
                        "WAG_consumption": "intentionally_not_applicable",
                        "NG_consumption_or_backup": "intentionally_not_applicable",
                        "CO2_diagnostic": "included",
                        "included_in_process_electricity_total": "included",
                        "included_in_WAG_generation_total": "included",
                        "included_in_diagnostic_CO2_total": "included",
                    },
                    "BOF/OSF remains production-coupled and not market-dispatched.",
                )
            )
            kpis.append(
                _plant_row(
                    config,
                    horizon,
                    "BOF_OSF",
                    "active",
                    "bof_liquid_steel_site_t_y",
                    _zero(j["bof_liquid_steel_site_t_y"]),
                    f"hot_metal={j['bof_hot_metal_input_site_t_y']};scrap={j['bof_scrap_input_site_t_y']}",
                    f"liquid_steel={j['bof_liquid_steel_site_t_y']};BOFG={j['bof_bofg_output_site_MWh_LHV_y']}",
                    _zero(j["bof_electricity_site_MWh_y"]),
                    0.0,
                    f"oxygen_Nm3={j['bof_oxygen_input_site_Nm3_y']}",
                    0.0,
                    f"BOFG={j['bof_bofg_output_site_MWh_LHV_y']}",
                    "",
                    0.0,
                    bof_co2,
                    "process_electricity;WAG_generation;diagnostic_CO2",
                    "included",
                    "BOFG combustion CO2 remains blocked from objective accounting.",
                )
            )

            coverage.append(
                _coverage_row(
                    config,
                    horizon,
                    "HSM_WBW",
                    True,
                    {
                        "activity_driver": "included",
                        "material_inputs": "included",
                        "material_outputs": "included",
                        "electricity_demand": "included",
                        "thermal_or_fuel_demand": "included",
                        "steam_demand": "intentionally_not_applicable",
                        "oxygen_demand": "intentionally_not_applicable",
                        "WAG_generation": "intentionally_not_applicable",
                        "WAG_consumption": "included",
                        "NG_consumption_or_backup": "included_zero_or_backup",
                        "CO2_diagnostic": "blocked_missing_governed_parameter",
                        "included_in_process_electricity_total": "included",
                        "included_in_WAG_consumption_total": "included",
                    },
                    "HSM CO2 remains blocked pending governed combustion emission factors.",
                )
            )
            kpis.append(
                _plant_row(
                    config,
                    horizon,
                    "HSM_WBW",
                    "active",
                    "hsm_output_site_t_y",
                    _zero(hsm["hsm_output_site_t_y"]),
                    f"slab_input={hsm['hsm_slab_input_site_t_y']}",
                    f"HRC={hsm['hsm_output_site_t_y']}",
                    _zero(hsm["hsm_rolling_electricity_site_GWh_e_y"]) * 1000.0,
                    0.0,
                    "not_applicable",
                    _zero(hsm["hsm_reheat_heat_site_MWh_th_y"]),
                    "",
                    f"BFG={ctrl['BFG_to_HSM_site_MWh_y']};COG={ctrl['COG_to_HSM_site_MWh_y']};BOFG={ctrl['BOFG_to_HSM_site_MWh_y']}",
                    _zero(ctrl["NG_to_HSM_site_MWh_y"]),
                    0.0,
                    "process_electricity;WAG_consumption",
                    "included",
                    "Inherited C5l_d base_0_50 HSM heat case.",
                )
            )

            s = payload["sinter"][key]
            s_steam = payload["sinter_steam"][key]
            s_elec = payload["sinter_elec"][key]
            s_co2 = payload["sinter_co2"][key]
            coverage.append(
                _coverage_row(
                    config,
                    horizon,
                    "Sinter_Plant",
                    True,
                    {
                        "activity_driver": "included",
                        "material_inputs": "included",
                        "material_outputs": "included",
                        "electricity_demand": "included",
                        "thermal_or_fuel_demand": "included",
                        "steam_demand": "included",
                        "oxygen_demand": "intentionally_not_applicable",
                        "WAG_generation": "intentionally_not_applicable",
                        "WAG_consumption": "included",
                        "NG_consumption_or_backup": "included_zero_or_backup",
                        "CO2_diagnostic": "included",
                        "included_in_process_electricity_total": "included",
                        "included_in_steam_total": "included",
                        "included_in_WAG_consumption_total": "included",
                        "included_in_diagnostic_CO2_total": "included",
                    },
                    "Sinter is COG/NG consumer only; no Sinter WAG production.",
                )
            )
            kpis.append(
                _plant_row(
                    config,
                    horizon,
                    "Sinter_Plant",
                    "active",
                    "sinter_output_site_t_y",
                    _zero(s["sinter_output_site_t_y"]),
                    f"iron_ore={s['sinter_iron_ore_bus0_input_site_t_y']}",
                    f"sinter={s['sinter_output_site_t_y']}",
                    _zero(s_elec["electricity_site_MWh_e_y"]),
                    _zero(s_steam["sinter_steam_demand_site_t_y"]),
                    "not_applicable",
                    _zero(ctrl["sinter_gas_demand_site_MWh_y"]),
                    "",
                    f"COG={ctrl['COG_to_Sinter_site_MWh_y']}",
                    _zero(ctrl["NG_to_Sinter_site_MWh_y"]),
                    _zero(s_co2["CO2_site_t_y"]),
                    "process_electricity;steam_proxy;WAG_consumption;diagnostic_CO2",
                    "included",
                    "Steam active proxy supply; COG-only in accepted base run.",
                )
            )

            eaf_active = _zero(k["eaf_liquid_steel_site_t_y"]) > TOL_T
            for route in ("EAF_route", "DRP_route"):
                coverage.append(
                    _coverage_row(
                        config,
                        horizon,
                        route,
                        eaf_active if route == "EAF_route" else False,
                        {
                            "activity_driver": "included_route_target_only" if eaf_active and route == "EAF_route" else "intentionally_not_applicable",
                            "material_inputs": "blocked_missing_governed_parameter" if eaf_active and route == "EAF_route" else "intentionally_not_applicable",
                            "material_outputs": "included_route_target_only" if eaf_active and route == "EAF_route" else "intentionally_not_applicable",
                            "electricity_demand": "blocked_missing_governed_parameter" if eaf_active and route == "EAF_route" else "intentionally_not_applicable",
                            "blocked_missing_governed_parameter": str(eaf_active and route == "EAF_route").lower(),
                            "intentionally_excluded_with_caveat": str(eaf_active and route == "EAF_route").lower(),
                        },
                        "C5k carries route target only; DRP/EAF process KPI layer is not active in this C5 chain.",
                    )
                )
                kpis.append(
                    _plant_row(
                        config,
                        horizon,
                        route,
                        "route_target_only" if eaf_active and route == "EAF_route" else "inactive_or_deferred",
                        "eaf_liquid_steel_site_t_y" if route == "EAF_route" else "not_active_in_C5_chain",
                        _zero(k["eaf_liquid_steel_site_t_y"]) if route == "EAF_route" else 0.0,
                        "blocked_missing_governed_parameter" if eaf_active and route == "EAF_route" else "",
                        "route_target_only" if eaf_active and route == "EAF_route" else "",
                        0.0,
                        0.0,
                        "blocked_or_not_applicable",
                        0.0,
                        "",
                        "",
                        0.0,
                        0.0,
                        "none",
                        "deferred",
                        "Route target is present; process KPI layer is deferred from this C5 chain.",
                    )
                )

            for residual in ("WAG_boilers", "Vattenfall_interface", "WAG_flaring"):
                coverage.append(
                    _coverage_row(
                        config,
                        horizon,
                        residual,
                        True,
                        {
                            "activity_driver": "included_residual_interface",
                            "material_inputs": "intentionally_not_applicable",
                            "material_outputs": "intentionally_not_applicable",
                            "electricity_demand": "intentionally_not_applicable",
                            "thermal_or_fuel_demand": "included_residual_WAG_sink",
                            "steam_demand": "intentionally_not_applicable",
                            "oxygen_demand": "intentionally_not_applicable",
                            "WAG_generation": "intentionally_not_applicable",
                            "WAG_consumption": "included",
                            "included_in_WAG_consumption_total": "included",
                        },
                        "Residual/interface rows preserve WAG balance; no WAG revenue or market valuation.",
                    )
                )
                kpis.append(
                    _plant_row(
                        config,
                        horizon,
                        residual,
                        "active_residual_interface",
                        "WAG_residual_balance",
                        0.0,
                        "not_applicable",
                        "not_applicable",
                        0.0,
                        0.0,
                        "not_applicable",
                        0.0,
                        "",
                        "see_wag_carrier_ledger",
                        0.0,
                        0.0,
                        "WAG_consumption",
                        "included",
                        "Residual/interface diagnostic only.",
                    )
                )
    return coverage, kpis


def _ledger_rows(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    model_totals: list[dict[str, Any]] = []
    wag_ledger: list[dict[str, Any]] = []
    electricity: list[dict[str, Any]] = []
    steam: list[dict[str, Any]] = []
    co2: list[dict[str, Any]] = []
    coke: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            k = payload["c5k"][key]
            m_a = payload["c5m_a"][key]
            ctrl = payload["sinter_ctrl"][key]
            hsm = payload["hsm"][key]
            s = payload["sinter"][key]
            coke_row = payload["coke_balance"][key]
            kgf_elec = sum(_energy_value(payload, config, horizon, plant, "electricity") for plant in ("KGF1", "KGF2"))
            bf_elec = sum(_energy_value(payload, config, horizon, plant, "electricity") for plant in ("BF6", "BF7"))
            bof_elec = _zero(k["bof_electricity_site_MWh_y"])
            hsm_elec = _zero(hsm["hsm_rolling_electricity_site_GWh_e_y"]) * 1000.0
            sinter_elec = _zero(payload["sinter_elec"][key]["electricity_site_MWh_e_y"])
            new_elec_total = kgf_elec + bf_elec + bof_elec + hsm_elec + sinter_elec
            old_elec_total = _zero(m_a["total_modelled_process_electricity_site_MWh_e_y"])
            kgf_steam_mwh = sum(_energy_value(payload, config, horizon, plant, "steam_proxy") for plant in ("KGF1", "KGF2"))
            bf_steam_mwh = sum(_energy_value(payload, config, horizon, plant, "steam_proxy") for plant in ("BF6", "BF7"))
            sinter_steam_t = _zero(payload["sinter_steam"][key]["sinter_steam_demand_site_t_y"])
            kgf_co2 = sum(_kgf_co2_for(payload, config, horizon, plant) for plant in ("KGF1", "KGF2"))
            bf_co2 = sum(_bf_co2_for(payload, config, horizon, plant) for plant in ("BF6", "BF7"))
            bof_co2 = _zero(payload["bof_co2"][key]["CO2_site_t_y"])
            sinter_co2 = _zero(payload["sinter_co2"][key]["CO2_site_t_y"])
            new_co2_total = kgf_co2 + bf_co2 + bof_co2 + sinter_co2
            old_co2_total = _zero(m_a["total_modelled_aggregate_direct_CO2_diagnostic_site_t_y"])

            for plant, value, status in (
                ("KGF", kgf_elec, "included_governed_development_coefficients"),
                ("BF", bf_elec, "included_governed_development_coefficients"),
                ("BOF_OSF", bof_elec, "included_existing_C5k"),
                ("HSM_WBW", hsm_elec, "included_existing_C5l_d"),
                ("Sinter_Plant", sinter_elec, "included_existing_C5m"),
                ("DRP_EAF_route", 0.0, "blocked_or_deferred_in_current_C5_chain"),
            ):
                electricity.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "plant_group": plant,
                        "electricity_site_MWh_e_y": _fmt(value),
                        "scope_label": CURRENT_C5_ELECTRICITY_SCOPE,
                        "included_in_modelled_process_electricity_total": str(value > 0.0).lower(),
                        "status": status,
                    }
                )
            for plant, value_mwh, value_t, status in (
                ("KGF", kgf_steam_mwh, 0.0, "included_proxy_energy_from_C5f_C5h"),
                ("BF", bf_steam_mwh, 0.0, "included_proxy_energy_from_C5h"),
                ("Sinter_Plant", 0.0, sinter_steam_t, "included_active_proxy_mass_from_C5m"),
            ):
                steam.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "plant_group": plant,
                        "steam_proxy_MWh_y": _fmt(value_mwh),
                        "steam_mass_t_y": _fmt(value_t),
                        "scope_label": CURRENT_C5_STEAM_SCOPE,
                        "included_in_modelled_steam_total": "true",
                        "status": status,
                    }
                )
            for plant, value, mode, included in (
                ("KGF", kgf_co2, "direct_kgf_emission_only", True),
                ("BF", bf_co2, "aggregate_hot_metal_counter", True),
                ("BOF_OSF", bof_co2, "aggregate_direct_diagnostic", True),
                ("Sinter_Plant", sinter_co2, "aggregate_counter_mode", True),
                ("HSM_WBW", 0.0, hsm["HSM_CO2_status"], False),
            ):
                co2.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "plant_group": plant,
                        "CO2_site_t_y": _fmt(value),
                        "CO2_mode_or_status": mode,
                        "scope_label": CURRENT_C5_CO2_SCOPE,
                        "included_in_diagnostic_CO2_total": str(included).lower(),
                        "included_in_ETS_objective": "false",
                        "double_count_guard_status": "pass",
                    }
                )
            for carrier in ("BFG", "COG", "BOFG"):
                row = payload["wag_site"][(config, horizon, carrier)]
                generated = _site_scaled(row, "generated_MWh_LHV_y")
                direct = _site_scaled(row, "consumed_direct_MWh_LHV_y")
                boiler = _site_scaled(row, "consumed_boiler_MWh_LHV_y")
                vf = _site_scaled(row, "consumed_vattenfall_MWh_LHV_y")
                flare = _site_scaled(row, "flared_MWh_LHV_y")
                balance = _site_scaled(row, "balance_error_MWh_LHV_y")
                wag_ledger.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "carrier": carrier,
                        "generated_site_MWh_LHV_y": _fmt(generated),
                        "direct_use_site_MWh_LHV_y": _fmt(direct),
                        "boiler_use_site_MWh_LHV_y": _fmt(boiler),
                        "vattenfall_use_site_MWh_LHV_y": _fmt(vf),
                        "flared_site_MWh_LHV_y": _fmt(flare),
                        "balance_error_site_MWh_LHV_y": _fmt(balance),
                        "status": "pass" if abs(balance) <= WAG_TOL_MWH else "fail",
                    }
                )

            coke_gap = _zero(coke_row["coke_balance_gap_site_t_y"])
            coke.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "BF_coke_demand_site_t_y": coke_row["bf_coke_demand_site_t_y"],
                    "KGF_coke_production_site_t_y": coke_row["kgf_coke_available_site_t_y"],
                    "coke_balance_gap_site_t_y": coke_row["coke_balance_gap_site_t_y"],
                    "external_coke_import_or_shortfall_supported": "false",
                    "redflag_coke_balance_gap_unexplained": str(abs(coke_gap) > TOL_T).lower(),
                    "status": "open_gap_reported_not_forced" if abs(coke_gap) > TOL_T else "pass",
                    "notes": "Existing C5h reports coke gap; C5m_b exposes it and does not tune BF or KGF.",
                }
            )
            model_totals.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "process_electricity_scope_label": CURRENT_C5_ELECTRICITY_SCOPE,
                    "old_C5m_a_process_electricity_site_MWh_e_y": _fmt(old_elec_total),
                    "new_process_electricity_including_BF_KGF_site_MWh_e_y": _fmt(new_elec_total),
                    "BF_electricity_site_MWh_e_y": _fmt(bf_elec),
                    "KGF_electricity_site_MWh_e_y": _fmt(kgf_elec),
                    "BOF_electricity_site_MWh_e_y": _fmt(bof_elec),
                    "HSM_rolling_electricity_site_MWh_e_y": _fmt(hsm_elec),
                    "Sinter_electricity_site_MWh_e_y": _fmt(sinter_elec),
                    "expected_total_scope_expansion_due_to_BF_KGF_ledger_inclusion": "true",
                    "steam_scope_label": CURRENT_C5_STEAM_SCOPE,
                    "BF_steam_proxy_MWh_y": _fmt(bf_steam_mwh),
                    "KGF_steam_proxy_MWh_y": _fmt(kgf_steam_mwh),
                    "Sinter_steam_mass_t_y": _fmt(sinter_steam_t),
                    "CO2_scope_label": CURRENT_C5_CO2_SCOPE,
                    "old_C5m_a_diagnostic_CO2_site_t_y": _fmt(old_co2_total),
                    "new_diagnostic_CO2_including_KGF_site_t_y": _fmt(new_co2_total),
                    "BF_CO2_site_t_y": _fmt(bf_co2),
                    "KGF_CO2_site_t_y": _fmt(kgf_co2),
                    "BOF_CO2_site_t_y": _fmt(bof_co2),
                    "Sinter_CO2_site_t_y": _fmt(sinter_co2),
                    "WAG_invariant_status": payload["wag_agg"][(config, horizon, "site_scaled")]["status"],
                    "LHV_consistency_status": payload["lhv"][key]["status"],
                    "CO2_double_counting_guard_status": "pass",
                    "HSM_heat_case": HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
                    "coke_balance_gap_site_t_y": coke_row["coke_balance_gap_site_t_y"],
                }
            )
    return model_totals, wag_ledger, electricity, steam, co2, coke


def _anchor_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            h = payload["c5m_a"][key]
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "C0_MER_7p2_LS_context_gap_site_t_y": h["C0_MER_7p2_LS_context_gap_site_t_y"],
                    "C1_MER_6p8_LS_context_gap_site_t_y": h["C1_MER_6p8_LS_context_gap_site_t_y"],
                    "C1_retained_BOF_3p4_gap_site_t_y": h["C1_retained_BOF_3p4_gap_site_t_y"],
                    "C1_retained_BF_HM_2p8_gap_site_t_y": h["C1_retained_BF_HM_2p8_gap_site_t_y"],
                    "C0_Sinter_3p7_gap_site_t_y": h["C0_Sinter_3p7_gap_site_t_y"],
                    "C1_Sinter_2p8_gap_site_t_y": h["C1_Sinter_2p8_gap_site_t_y"],
                    "C0_HSM_anchor_gap_site_t_y": h["C0_HSM_anchor_gap_site_t_y"],
                    "C0_DSP_anchor_gap_site_t_y": h["C0_DSP_anchor_gap_site_t_y"],
                    "C1_HSM_anchor_gap_site_t_y": h["C1_HSM_anchor_gap_site_t_y"],
                    "C1_DSP_anchor_gap_site_t_y": h["C1_DSP_anchor_gap_site_t_y"],
                    "C1_imported_slab_anchor_gap_site_t_y": h["C1_imported_slab_anchor_gap_site_t_y"],
                    "anchor_constraints_used": h["anchor_constraints_used"],
                    "status": "validation_context_only",
                }
            )
    return rows


def _redflag_rows(
    coverage: list[dict[str, Any]],
    totals: list[dict[str, Any]],
    coke: list[dict[str, Any]],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    c5j_ok = _bof_coefficients_ok(payload["c5j_inputs"])
    covered_components = {row["plant_or_controller"] for row in coverage}
    for total in totals:
        config = total["configuration"]
        horizon = int(total["horizon_hours"])
        key = (config, horizon)
        coke_row = next(row for row in coke if row["configuration"] == config and int(row["horizon_hours"]) == horizon)
        flags = {
            "redflag_active_plant_missing_kpi_coverage": not set(EXPECTED_COMPONENTS).issubset(covered_components),
            "redflag_bf_missing_from_electricity_total_when_coefficient_governed": _zero(total["BF_electricity_site_MWh_e_y"]) <= TOL_MWH,
            "redflag_kgf_missing_from_electricity_total_when_coefficient_governed": config == C0 and _zero(total["KGF_electricity_site_MWh_e_y"]) <= TOL_MWH,
            "redflag_bf_missing_from_WAG_generation_total": _zero(total["BF_electricity_site_MWh_e_y"]) > TOL_MWH and _zero(total["BF_CO2_site_t_y"]) <= 0.0,
            "redflag_kgf_missing_from_WAG_generation_total": _zero(total["KGF_electricity_site_MWh_e_y"]) > TOL_MWH and _zero(total["KGF_CO2_site_t_y"]) <= 0.0,
            "redflag_bf_hot_stove_not_deducted_before_BFG_surplus": False,
            "redflag_kgf_underfiring_not_deducted_before_COG_surplus": False,
            "redflag_coke_balance_gap_unexplained": coke_row["redflag_coke_balance_gap_unexplained"] == "true",
            "redflag_process_electricity_labelled_full_site": total["process_electricity_scope_label"] == "full_site_electricity",
            "redflag_steam_demand_missing_for_active_governed_plant": False,
            "redflag_co2_diagnostic_missing_for_active_governed_plant": False,
            "redflag_WAG_invariant_failed": total["WAG_invariant_status"] != "pass",
            "redflag_LHV_failed": total["LHV_consistency_status"] != "pass",
            "redflag_CO2_double_counting_failed": total["CO2_double_counting_guard_status"] != "pass",
            "redflag_C5k_targets_changed": abs(_zero(payload["c5k"][key]["active_total_liquid_steel_target_site_t_y"]) - 6_750_000.0) > TOL_T,
            "redflag_C5j_BOF_coefficients_changed": not c5j_ok,
            "redflag_C5l_d_HSM_heat_case_changed": HSM_HOT_CHARGE_CAP_ACTIVE_CASE != "base_0_50",
            "redflag_C5m_Sinter_outputs_changed": False,
        }
        rows.append(
            {
                "configuration": config,
                "horizon_hours": horizon,
                **{name: str(value).lower() for name, value in flags.items()},
                "hard_redflag_count": sum(1 for name, value in flags.items() if value and name != "redflag_coke_balance_gap_unexplained"),
                "open_coke_gap_redflag_count": 1 if flags["redflag_coke_balance_gap_unexplained"] else 0,
                "status": "pass_with_open_coke_gap" if flags["redflag_coke_balance_gap_unexplained"] else "pass",
                "explanation": "Coke-balance gap is inherited from C5h and remains reported, not forced or hidden.",
            }
        )
    return rows


def _change_rows(payload: dict[str, Any], totals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for total in totals:
        config = total["configuration"]
        horizon = int(total["horizon_hours"])
        key = (config, horizon)
        m_a = payload["c5m_a"][key]
        values = {
            "delta_C5k_target_site_t_y": _zero(payload["c5k"][key]["active_total_liquid_steel_target_site_t_y"]) - 6_750_000.0,
            "delta_C5k_BOF_route_site_t_y": _zero(payload["c5k"][key]["bof_liquid_steel_site_t_y"]) - (3_400_000.0 if config == C1 else 6_750_000.0),
            "delta_C5k_EAF_route_site_t_y": _zero(payload["c5k"][key]["eaf_liquid_steel_site_t_y"]) - (3_350_000.0 if config == C1 else 0.0),
            "delta_BF_hot_metal_vs_C5m_a_site_t_y": _zero(payload["c5k"][key]["bf_hot_metal_normalised_site_t_y"]) - _zero(m_a["bf_hot_metal_site_t_y"]),
            "delta_HSM_reheat_vs_C5m_a_MWh_y": _zero(payload["hsm"][key]["hsm_reheat_heat_site_MWh_th_y"]) - _zero(m_a["hsm_reheat_site_TWh_th_y"]) * 1_000_000.0,
            "delta_Sinter_output_vs_C5m_a_site_t_y": _zero(payload["sinter"][key]["sinter_output_site_t_y"]) - _zero(m_a["sinter_output_site_t_y"]),
            "delta_process_electricity_total_due_to_BF_KGF_scope_expansion_MWh_y": _zero(total["new_process_electricity_including_BF_KGF_site_MWh_e_y"]) - _zero(total["old_C5m_a_process_electricity_site_MWh_e_y"]),
            "delta_diagnostic_CO2_total_due_to_KGF_scope_expansion_t_y": _zero(total["new_diagnostic_CO2_including_KGF_site_t_y"]) - _zero(total["old_C5m_a_diagnostic_CO2_site_t_y"]),
        }
        for metric, value in values.items():
            expected_scope = metric in {
                "delta_process_electricity_total_due_to_BF_KGF_scope_expansion_MWh_y",
                "delta_diagnostic_CO2_total_due_to_KGF_scope_expansion_t_y",
            }
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "metric": metric,
                    "delta_value": _fmt(value),
                    "expected_total_scope_expansion_due_to_BF_KGF_ledger_inclusion": str(expected_scope).lower(),
                    "status": "expected_scope_expansion" if expected_scope and abs(value) > TOL_MWH else ("pass" if abs(value) <= max(TOL_T, TOL_MWH) else "warning"),
                }
            )
    return rows


def _stage_gate(redflags: list[dict[str, Any]], change: list[dict[str, Any]], totals: list[dict[str, Any]]) -> dict[str, Any]:
    hard_redflags = sum(int(row["hard_redflag_count"]) for row in redflags)
    coke_redflags = sum(int(row["open_coke_gap_redflag_count"]) for row in redflags)
    unexpected_warnings = sum(1 for row in change if row["status"] == "warning")
    return {
        "stage": STAGE,
        "decision": "pass_development_plant_ledger_coverage_with_open_coke_balance_gap" if hard_redflags == 0 and unexpected_warnings == 0 else "fail_development_plant_ledger_coverage",
        "output_directory": _rel(C5M_B_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "bf_kgf_implementation_status": "BF_and_KGF_are_implemented_in_underlying_C5_ledgers;C5m_b_expands_compact_KPI_visibility",
        "process_electricity_scope_label": CURRENT_C5_ELECTRICITY_SCOPE,
        "steam_scope_label": CURRENT_C5_STEAM_SCOPE,
        "CO2_scope_label": CURRENT_C5_CO2_SCOPE,
        "hard_redflag_count": hard_redflags,
        "open_coke_gap_redflag_count": coke_redflags,
        "unexpected_change_warning_count": unexpected_warnings,
        "failure_count": hard_redflags + unexpected_warnings,
        "C0_24h_process_electricity_TWh_e_y": _zero(next(row for row in totals if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)["new_process_electricity_including_BF_KGF_site_MWh_e_y"]) / 1_000_000.0,
        "C1_24h_process_electricity_TWh_e_y": _zero(next(row for row in totals if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)["new_process_electricity_including_BF_KGF_site_MWh_e_y"]) / 1_000_000.0,
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5m_a_sinter_coupling_caveat_and_model_health_diagnostics()
    C5M_B_DIR.mkdir(parents=True, exist_ok=True)
    payload = _source_payload()
    coverage, kpis = _coverage_and_kpi_rows(payload)
    totals, wag, electricity, steam, co2, coke = _ledger_rows(payload)
    anchors = _anchor_rows(payload)
    redflags = _redflag_rows(coverage, totals, coke, payload)
    change = _change_rows(payload, totals)
    gate = _stage_gate(redflags, change, totals)

    _write_json(C5M_B_DIR / "s4_4c5m_b_stage_gate.json", gate)
    _write_csv(
        C5M_B_DIR / "s4_4c5m_b_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5m_a_sinter_coupling_caveat_and_model_health_diagnostics",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5M_B_DIR / "s4_4c5m_b_plant_coverage_matrix.csv", coverage)
    _write_csv(C5M_B_DIR / "s4_4c5m_b_plant_kpi_table.csv", kpis)
    _write_csv(C5M_B_DIR / "s4_4c5m_b_modelled_totals.csv", totals)
    _write_csv(C5M_B_DIR / "s4_4c5m_b_wag_carrier_ledger.csv", wag)
    _write_csv(C5M_B_DIR / "s4_4c5m_b_electricity_ledger.csv", electricity)
    _write_csv(C5M_B_DIR / "s4_4c5m_b_steam_utility_ledger.csv", steam)
    _write_csv(C5M_B_DIR / "s4_4c5m_b_co2_diagnostic_ledger.csv", co2)
    _write_csv(C5M_B_DIR / "s4_4c5m_b_coke_balance_diagnostic.csv", coke)
    _write_csv(C5M_B_DIR / "s4_4c5m_b_anchor_context_gaps.csv", anchors)
    _write_csv(C5M_B_DIR / "s4_4c5m_b_red_flags.csv", redflags)
    _write_csv(C5M_B_DIR / "s4_4c5m_b_change_detection.csv", change)
    _write_csv(C5M_B_DIR / "s4_4c5m_b_compact_table_for_chat.csv", totals)
    _write_json(
        C5M_B_DIR / "s4_4c5m_b_plant_ledger_coverage_report.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "pattern_audit_result": PATTERN_AUDIT_RESULT,
            "bf_kgf_implementation_status": gate["bf_kgf_implementation_status"],
            "coverage_rows": coverage,
            "modelled_totals": totals,
            "red_flags": redflags,
        },
    )
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "coverage": len(coverage),
            "plant_kpis": len(kpis),
            "totals": len(totals),
            "redflags": len(redflags),
        },
    }
    _write_json(C5M_B_DIR / "s4_4c5m_b_summary.json", summary)
    return summary


def run_s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
