"""Diagnostic-only C5 anchor, route, denominator and material-accounting review.

This builder reads existing C5 compact artifacts and writes compact diagnostic
CSV/Markdown outputs. It does not run or modify any plant-layer model stage.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


S4_ROOT = Path("data/03_Optimisation/inputs/assets/steel/S4")
OUT_DIR = S4_ROOT / "c5_anchor_route_diagnostics"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_ANCHOR_ROUTE_DENOMINATOR_DIAGNOSTICS.md")

C0 = "C0_current_BF_BOF_reference"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
CONFIGS = (C0, C1)
HORIZON = 24


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _num(value: Any) -> float:
    if value in (None, "", "nan", "NaN"):
        return 0.0
    return float(value)


def _fmt(value: Any, digits: int = 6) -> str:
    if value in ("", None):
        return ""
    number = _num(value)
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _by_key(rows: list[dict[str, str]], *, cap_case: str | None = None) -> dict[tuple[str, int], dict[str, str]]:
    result: dict[tuple[str, int], dict[str, str]] = {}
    for row in rows:
        if cap_case is not None and row.get("cap_case") != cap_case:
            continue
        result[(row["configuration"], int(row["horizon_hours"]))] = row
    return result


def _key(rows: dict[tuple[str, int], dict[str, str]], config: str) -> dict[str, str]:
    return rows[(config, HORIZON)]


def _unit_row(rows: list[dict[str, str]], config: str, unit_id: str) -> dict[str, str]:
    for row in rows:
        if row["configuration"] == config and int(row["horizon_hours"]) == HORIZON and row.get("unit_id") == unit_id:
            return row
    raise KeyError((config, HORIZON, unit_id))


def _pressure_row(rows: list[dict[str, str]], config: str, pressure_level: str) -> dict[str, str]:
    for row in rows:
        if row["configuration"] == config and int(row["horizon_hours"]) == HORIZON and row.get("pressure_level") == pressure_level:
            return row
    raise KeyError((config, HORIZON, pressure_level))


def _coke_case(
    payload: dict[str, Any],
    config: str,
    case_id: str = "case_1_active_scaled_KGF_anchor_exact_BF_rate",
) -> dict[str, str]:
    for row in payload["c5m_f_coke"]:
        if row["configuration"] == config and int(row["horizon_hours"]) == HORIZON and row["case_id"] == case_id:
            return row
    raise KeyError((config, HORIZON, case_id))


def _gap(model: Any, active: Any = "", raw: Any = "") -> tuple[str, str]:
    denominator = active if active not in ("", None) else raw
    if denominator in ("", None):
        return "", ""
    try:
        model_value = _num(model)
        denom = _num(denominator)
    except ValueError:
        return "", ""
    abs_gap = model_value - denom
    rel_gap = abs_gap / denom if abs(denom) > 1e-12 else 0.0
    return _fmt(abs_gap), _fmt(rel_gap)


def _anchor_row(
    anchor_id: str,
    config: str,
    asset_or_flow: str,
    metric: str,
    unit: str,
    raw: Any,
    active: Any,
    model: Any,
    anchor_role: str,
    reconciliation_mode: str,
    source: str,
    stage: str,
    caveat: str,
    decision_needed: str,
) -> dict[str, Any]:
    abs_gap, rel_gap = _gap(model, active, raw)
    return {
        "anchor_id": anchor_id,
        "configuration": config,
        "asset_or_flow": asset_or_flow,
        "metric": metric,
        "unit": unit,
        "raw_source_anchor": raw,
        "active_scaled_anchor": active,
        "model_output": model,
        "absolute_gap": abs_gap,
        "relative_gap": rel_gap,
        "anchor_role": anchor_role,
        "reconciliation_mode": reconciliation_mode,
        "source_card_or_stage": source,
        "stage_introduced": stage,
        "thesis_usability": "false",
        "caveat": caveat,
        "decision_needed": decision_needed,
    }


def _load_payload() -> dict[str, Any]:
    return {
        "c5k": _by_key(_read_csv(S4_ROOT / "s4_4c5k_production_policy_and_route_split_normalisation" / "s4_4c5k_route_split_normalisation_report.csv")),
        "c5l_d": _by_key(_read_csv(S4_ROOT / "s4_4c5l_d_HSM_hot_charge_share_cap_and_reheat_sensitivity_patch" / "s4_4c5l_d_hot_charge_cap_report.csv"), cap_case="base_0_50"),
        "c5m_b_totals": _by_key(_read_csv(S4_ROOT / "s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration" / "s4_4c5m_b_modelled_totals.csv")),
        "c5m_b_wag": _read_csv(S4_ROOT / "s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration" / "s4_4c5m_b_wag_carrier_ledger.csv"),
        "c5m_b_elec": _read_csv(S4_ROOT / "s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration" / "s4_4c5m_b_electricity_ledger.csv"),
        "c5m_b_co2": _read_csv(S4_ROOT / "s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration" / "s4_4c5m_b_co2_diagnostic_ledger.csv"),
        "c5m_f_coke": _read_csv(S4_ROOT / "s4_4c5m_f_bounded_coke_reconciliation_sensitivity" / "s4_4c5m_f_coke_balance_by_scenario.csv"),
        "sinter_route": _by_key(_read_csv(S4_ROOT / "s4_4c5m_sinter_minimal_parameterisation" / "s4_4c5m_sinter_material_route_dashboard.csv")),
        "sinter_utility": _by_key(_read_csv(S4_ROOT / "s4_4c5m_sinter_minimal_parameterisation" / "s4_4c5m_sinter_utility_dashboard.csv")),
        "pefa_material": _by_key(_read_csv(S4_ROOT / "s4_4c5n_a_pefa_pelletizing_layer" / "s4_4c5n_a_pefa_material_ledger.csv")),
        "pefa_elec": _by_key(_read_csv(S4_ROOT / "s4_4c5n_a_pefa_pelletizing_layer" / "s4_4c5n_a_pefa_electricity_ledger.csv")),
        "pefa_gas": _by_key(_read_csv(S4_ROOT / "s4_4c5n_a_pefa_pelletizing_layer" / "s4_4c5n_a_pefa_gas_controller_dashboard.csv")),
        "pefa_co2": _by_key(_read_csv(S4_ROOT / "s4_4c5n_a_pefa_pelletizing_layer" / "s4_4c5n_a_pefa_solid_fuel_co2_waste_gas.csv")),
        "pellet": _by_key(_read_csv(S4_ROOT / "s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy" / "s4_4c5n_b_pellet_balance_report.csv")),
        "drp": _by_key(_read_csv(S4_ROOT / "s4_4c5o_a_ng_drp_physical_layer_with_dri_interface" / "s4_4c5o_a_drp_material_energy_ledger.csv")),
        "drp_buffer": _by_key(_read_csv(S4_ROOT / "s4_4c5o_a_ng_drp_physical_layer_with_dri_interface" / "s4_4c5o_a_dri_buffer_interface_dashboard.csv")),
        "eaf_activity": _by_key(_read_csv(S4_ROOT / "s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff" / "s4_4c5o_b_eaf_activity_report.csv")),
        "eaf": _by_key(_read_csv(S4_ROOT / "s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff" / "s4_4c5o_b_eaf_material_energy_ledger.csv")),
        "eaf_handoff": _by_key(_read_csv(S4_ROOT / "s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff" / "s4_4c5o_b_dri_buffer_handoff_dashboard.csv")),
        "eaf_downstream": _by_key(_read_csv(S4_ROOT / "s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff" / "s4_4c5o_b_downstream_integration_dashboard.csv")),
        "dsp_activity": _by_key(_read_csv(S4_ROOT / "s4_4c5o_c_dsp_downstream_physical_layer" / "s4_4c5o_c_dsp_activity_report.csv")),
        "dsp": _by_key(_read_csv(S4_ROOT / "s4_4c5o_c_dsp_downstream_physical_layer" / "s4_4c5o_c_dsp_material_energy_ledger.csv")),
        "dsp_downstream": _by_key(_read_csv(S4_ROOT / "s4_4c5o_c_dsp_downstream_physical_layer" / "s4_4c5o_c_downstream_integration_dashboard.csv")),
        "dsp_totals": _by_key(_read_csv(S4_ROOT / "s4_4c5o_c_dsp_downstream_physical_layer" / "s4_4c5o_c_modelled_totals_delta.csv")),
        "linde_oxygen": _by_key(_read_csv(S4_ROOT / "s4_4c5p_a_linde_asu_oxygen_accounting" / "s4_4c5p_a_oxygen_demand_ledger.csv")),
        "linde_asu": _by_key(_read_csv(S4_ROOT / "s4_4c5p_a_linde_asu_oxygen_accounting" / "s4_4c5p_a_asu_electricity_ledger.csv")),
        "linde_totals": _by_key(_read_csv(S4_ROOT / "s4_4c5p_a_linde_asu_oxygen_accounting" / "s4_4c5p_a_modelled_totals_delta.csv")),
        "steam_health": _by_key(_read_csv(S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_compact_healthcheck.csv")),
        "steam_supply": _read_csv(S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_boiler_steam_supply_by_unit.csv"),
        "steam_steg11": _by_key(_read_csv(S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_steg11_chp_ledger.csv")),
        "steam_tg2": _by_key(_read_csv(S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_tg2_steam_turbine_ledger.csv")),
        "steam_bus_balance": _read_csv(S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_steam_bus_balance.csv"),
        "steam_fuel": _read_csv(S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_boiler_fuel_allocation.csv"),
        "steam_wag_residual": _by_key(_read_csv(S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_wag_residual_after_steam.csv")),
        "steam_internal_electricity": _by_key(_read_csv(S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_internal_electricity_ledger.csv")),
        "steam_totals": _by_key(_read_csv(S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_modelled_totals_delta.csv")),
        "generator_health": _by_key(_read_csv(S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting" / "s4_4c5p_c_compact_healthcheck.csv")),
        "generator_fuel": _read_csv(S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting" / "s4_4c5p_c_generator_fuel_allocation.csv"),
        "generator_electricity": _by_key(_read_csv(S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting" / "s4_4c5p_c_generator_electricity_ledger.csv")),
        "generator_residual": _by_key(_read_csv(S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting" / "s4_4c5p_c_wag_residual_after_generators.csv")),
        "generator_totals": _by_key(_read_csv(S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting" / "s4_4c5p_c_modelled_totals_delta.csv")),
    }


def build_anchor_matrix(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_total = {C0: 7_200_000.0, C1: 6_800_000.0}
    raw_bof = {C0: 7_200_000.0, C1: 3_400_000.0}
    raw_eaf = {C0: 0.0, C1: 3_300_000.0}
    raw_bf_hm = {C0: 6_300_000.0, C1: 2_800_000.0}
    raw_drp = {C0: 0.0, C1: 2_800_000.0}
    raw_pefa = {C0: 4_600_000.0, C1: 5_000_000.0}
    raw_imported_pellets = {C0: 1_500_000.0, C1: 200_000.0}
    raw_sinter = {C0: 3_700_000.0, C1: 2_800_000.0}
    raw_hsm = {C0: 5_400_000.0, C1: 5_500_000.0}
    raw_dsp = {C0: 1_500_000.0, C1: 1_500_000.0}
    raw_final = {C0: 6_900_000.0, C1: 7_000_000.0}
    raw_core_oxygen_t = {C0: 953_000.0, C1: 744_000.0}
    raw_asu_precedent_mwh = 60.0 * 8760.0

    for config in CONFIGS:
        c5k = _key(payload["c5k"], config)
        c5l_d = _key(payload["c5l_d"], config)
        pellet = _key(payload["pellet"], config)
        pefa = _key(payload["pefa_material"], config)
        pefa_elec = _key(payload["pefa_elec"], config)
        pefa_gas = _key(payload["pefa_gas"], config)
        pefa_co2 = _key(payload["pefa_co2"], config)
        drp = _key(payload["drp"], config)
        eaf = _key(payload["eaf"], config)
        eaf_act = _key(payload["eaf_activity"], config)
        dsp = _key(payload["dsp"], config)
        dsp_act = _key(payload["dsp_activity"], config)
        dsp_down = _key(payload["dsp_downstream"], config)
        sinter = _key(payload["sinter_route"], config)
        sinter_util = _key(payload["sinter_utility"], config)
        coke = _coke_case(payload, config)
        totals = _key(payload["linde_totals"], config)
        linde_o2 = _key(payload["linde_oxygen"], config)
        linde_asu = _key(payload["linde_asu"], config)
        steam_health = _key(payload["steam_health"], config)
        steam_wag = _key(payload["steam_wag_residual"], config)
        steam_elec = _key(payload["steam_internal_electricity"], config)
        steam_totals = _key(payload["steam_totals"], config)
        steg11 = _key(payload["steam_steg11"], config)
        tg2 = _key(payload["steam_tg2"], config)
        generator_health = _key(payload["generator_health"], config)
        generator_elec = _key(payload["generator_electricity"], config)
        generator_residual = _key(payload["generator_residual"], config)
        generator_totals = _key(payload["generator_totals"], config)
        steam_72 = _pressure_row(payload["steam_bus_balance"], config, "steam_72bar")
        steam_45 = _pressure_row(payload["steam_bus_balance"], config, "steam_45bar")
        steam_15 = _pressure_row(payload["steam_bus_balance"], config, "steam_15bar")
        k15 = _unit_row(payload["steam_supply"], config, "BOILER_C1_K15K16")
        k23 = _unit_row(payload["steam_supply"], config, "BOILER_C2_K23K24")
        k41 = _unit_row(payload["steam_supply"], config, "BOILER_C2_K41")
        active_target = _num(c5k["active_total_liquid_steel_target_site_t_y"])

        definitions = [
            ("active_total_liquid_steel_target", "site", "liquid steel production target", "t/y", raw_total[config], active_target, active_target, "development_input", "active_target_6p75_over_mer_context", "C5k production normalisation", "C5k", "Freeze or explicitly sensitivity-test 6.75 Mt/y before DA."),
            ("bof_liquid_steel", "BOF", "liquid steel output", "t/y", raw_bof[config], c5k["active_bof_liquid_steel_target_site_t_y"], c5k["bof_liquid_steel_site_t_y"], "development_input", "C5k_route_split_normalisation", "C5k report", "C5k", "No DA/economic claims if route split is changed silently."),
            ("eaf_liquid_steel", "EAF", "liquid steel output", "t/y", raw_eaf[config], c5k["active_eaf_liquid_steel_target_site_t_y"], eaf["EAF_LS_output_site_t_y"], "development_input", "C5o_b_preserves_C5k_EAF_target", "EAF source card / C5o_b", "C5o_b", "C1 EAF target is active C5 route target, not raw anchor."),
            ("bf_hot_metal", "BF", "hot metal driver", "t/y", raw_bf_hm[config], "", c5k["bof_hot_metal_input_site_t_y"], "validation_anchor", "C5k_no_buffer_BF_equals_BOF_HM_input", "C5k / BF source context", "C5k", "BF HM differs from raw anchors after no-buffer BOF coupling."),
            ("drp_dri_output", "DRP", "DRI output", "t/y", raw_drp[config], raw_drp[config] * active_target / raw_total[config] if raw_total[config] else 0.0, drp["DRI_output_site_t_y"], "development_input", "DRP_scaled_to_active_target", "DRP source card / C5o_a", "C5o_a", "C0 inactive; C1 scaled from MER 2.8 Mt/y."),
            ("eaf_dri_input", "EAF", "DRI input", "t/y", raw_drp[config], _num(drp["DRI_output_site_t_y"]), eaf["EAF_DRI_input_site_t_y"], "reconciliation_parameter", "EAF_DRI_coeff_reconciled_to_available_DRP_DRI", "EAF source card / C5o_b", "C5o_b", "Resolved active DRI coefficient is not a Tata EAF recipe."),
            ("pefa_output", "PEFA", "fired pellets output", "t/y", raw_pefa[config], raw_pefa[config] * active_target / raw_total[config], pefa["PEFA_output_site_t_y"], "development_input", "scaled_with_active_target", "PELLETIZING source card / C5n_a", "C5n_a", "Single fired-pellets proxy; no grade split."),
            ("imported_pellets", "pellet burden", "imported pellets", "t/y", raw_imported_pellets[config], raw_imported_pellets[config] * active_target / raw_total[config], pellet["imported_pellets_site_t_y"], "development_input", "scale_with_active_production_target", "PELLETIZING source card / C5n_b", "C5n_b", "Fixed exogenous supply, not free slack."),
            ("bf_pellet_demand", "pellet burden", "BF pellet demand", "t/y", "", "", pellet["BF_pellet_demand_site_t_y"], "reconciliation_parameter", "BF_pellet_coeff_resolves_public_annual_burden_balance", "C5n_b pellet balance", "C5n_b", "Coefficient is reconciliation, not BF burden truth."),
            ("drp_pellet_demand", "pellet burden", "DRP pellet demand", "t/y", "", "", pellet["DRP_pellet_demand_site_t_y"], "development_input", "DRP_pellet_coeff_from_DRP_yield", "C5n_b / C5o_a", "C5n_b/C5o_a", "Now fed by actual C5o_a DRP input."),
            ("dsp_output", "DSP", "DSP hot rolled coil output", "t/y", raw_dsp[config], dsp_act["DSP_scaled_anchor_site_t_y"], dsp["DSP_output_site_t_y"], "development_input", "preserve_C5l_d_DSP_placeholder", "DSP source card / C5o_c", "C5o_c", "Active output is 1.35 Mt/y placeholder replacement, not raw 1.5 Mt/y."),
            ("hsm_wbw_output", "HSM/WBW", "rolled coil output", "t/y", raw_hsm[config], "", c5l_d["hsm_output_site_t_y"], "development_input", "C5l_d_base_0_50_hot_charge_case", "HSM C5l_d", "C5l_d", "HSM output reflects slab input factor and imported slab context."),
            ("final_product_proxy", "downstream", "HSM plus DSP final-product proxy", "t/y", raw_final[config], "", dsp_down["DSP_plus_HSM_final_product_proxy_site_t_y"], "reporting_only", "C5o_c_final_product_proxy", "C5l_d / C5o_c", "C5l_d/C5o_c", "Denominator candidate, not yet final economics denominator."),
            ("kgf_coke_output", "KGF/coking", "coke production", "t/y", "", "", coke["KGF_output_site_t_y"], "development_input", "C5m_f_bounded_reconciliation_active_development_baseline", "C5m_f coke reconciliation", "C5m_f", "Bounded C5m_f reconciliation is active development baseline; external coke remains fallback-only."),
            ("bf_coke_demand", "BF", "coke demand", "t/y", "", "", coke["BF_coke_demand_site_t_y"], "development_input", "C5m_f_bounded_reconciliation_active_development_baseline", "C5m_e/C5m_f", "C5m_e/C5m_f", "Driver repaired; BF coke rate/KGF anchor reconciliation is no longer an open method decision."),
            ("sinter_output", "Sinter", "sinter output", "t/y", raw_sinter[config], "", sinter["sinter_output_site_t_y"], "development_input", "BF_hot_metal_coupled", "SINTER source card / C5m", "C5m", "C0 site-average and C1 retained-BF coupling caveated."),
            ("sinter_iron_ore_input", "Sinter", "iron ore bus0 input", "t/y", "", "", sinter["sinter_iron_ore_bus0_input_site_t_y"], "development_input", "per_t_sinter_input", "C5m", "C5m", "Other raw-mix inputs implicit."),
            ("boiler_hsm_reheat", "HSM/WBW", "HSM reheat demand", "PJ/y", "", "", c5l_d["hsm_reheat_heat_site_PJ_y"], "development_input", "C5l_d_base_0_50_hot_charge_cap", "C5l_d", "C5l_d", "Thermal/LHV, not electricity."),
            ("boiler_hsm_rolling_electricity", "HSM/WBW", "rolling electricity", "GWh/y", "", "", c5l_d["hsm_rolling_electricity_site_GWh_e_y"], "development_input", "existing_HSM_rolling_electricity", "C5l_d", "C5l_d", "Already in process electricity scope."),
            ("pefa_electricity", "PEFA", "electricity", "MWh/y", "", "", pefa_elec["PEFA_electricity_site_MWh_e_y"], "development_input", "process_coupled_not_DA_responsive", "C5n_a", "C5n_a", "Not price-responsive."),
            ("pefa_gas_heat", "PEFA", "gas heat demand", "PJ/y", "", "", pefa_gas["PEFA_gas_heat_demand_site_PJ_y"], "development_input", "eligible_COG_BOFG_NG_controller", "C5n_a", "C5n_a", "No BFG; no WAG market value."),
            ("pefa_co2", "PEFA", "diagnostic CO2", "t/y", "", "", pefa_co2["PEFA_diagnostic_CO2_site_t_y"], "reporting_only", "aggregate_diagnostic_no_fuel_double_count", "C5n_a", "C5n_a", "Not ETS objective."),
            ("sinter_electricity", "Sinter", "electricity", "MWh/y", "", "", sinter_util["electricity_site_MWh_e_y"], "development_input", "process_coupled", "C5m", "C5m", "Not DA-responsive."),
            ("drp_electricity", "DRP", "electricity", "MWh/y", "", "", drp["DRP_electricity_site_MWh_e_y"], "development_input", "continuous_NG_DRP_auxiliary", "C5o_a", "C5o_a", "Not EAF arc load."),
            ("drp_ng", "DRP", "NG total", "PJ/y", "", "", drp["DRP_NG_total_PJ_y"], "development_input", "external_NG_process_coupled", "C5o_a", "C5o_a", "Tailgas not WAG."),
            ("drp_oxygen", "DRP", "oxygen demand diagnostic", "t/y", "", "", drp["DRP_oxygen_diagnostic_site_t_y"], "reporting_only", "oxygen_supply_not_implemented", "C5o_a", "C5o_a", "Requires Linde/ASU layer."),
            ("drp_co2_capture", "DRP", "CO2 capture stream", "t/y", "", "", drp["DRP_CO2_capture_stream_site_t_y"], "reporting_only", "capture_stream_validation", "C5o_a", "C5o_a", "Not direct emissions total."),
            ("eaf_electricity", "EAF", "arc electricity", "MWh/y", "", "", eaf["EAF_arc_electricity_MWh_e_y"], "development_input", "heat_equivalent_accounting", "C5o_b", "C5o_b", "No mFRR variables or DA dispatch."),
            ("eaf_ng", "EAF", "NG demand", "PJ/y", "", "", eaf["EAF_NG_PJ_y"], "development_input", "process_NG_driver", "C5o_b", "C5o_b", "No WAG offgas."),
            ("eaf_oxygen", "EAF", "oxygen demand diagnostic", "t/y", "", "", eaf["EAF_oxygen_diagnostic_t_y"], "reporting_only", "oxygen_supply_not_implemented", "C5o_b", "C5o_b", "Requires Linde/ASU layer."),
            ("eaf_co2", "EAF", "diagnostic CO2 midpoint", "t/y", "", "", eaf["EAF_CO2_diagnostic_midpoint_t_y"], "reporting_only", "aggregate_BREF_midpoint_diagnostic", "C5o_b", "C5o_b", "Not ETS/full-site emissions."),
            ("dsp_electricity", "DSP", "electricity", "MWh/y", "", "", dsp["DSP_electricity_MWh_e_y"], "development_input", "process_coupled_not_DA_responsive", "C5o_c", "C5o_c", "No fuel heat active."),
            ("dsp_internal_scrap", "DSP", "internal scrap/loss", "t/y", "", "", dsp["DSP_internal_scrap_loss_site_t_y"], "reporting_only", "reported_not_EAF_scrap_supply", "C5o_c", "C5o_c", "Future scrap loop decision needed."),
            ("dsp_direct_co2", "DSP", "direct CO2", "t/y", "", "", dsp["DSP_direct_CO2_t_y"], "reporting_only", "zero_because_fuel_inactive", "C5o_c", "C5o_c", "Not physical zero-emissions claim."),
            ("bof_oxygen", "BOF", "oxygen demand diagnostic", "t/y", "", "", _num(c5k["bof_oxygen_input_site_kg_y"]) / 1000.0, "development_input", "BOF_OSF_parameterisation", "C5k/C5j", "C5j/C5k", "Requires Linde/ASU supply layer."),
            ("linde_total_oxygen_demand", "Linde/ASU", "total core oxygen demand", "t/y", raw_core_oxygen_t[config], "", linde_o2["total_core_oxygen_demand_t_y"], "development_input", "BF_BOF_EAF_DRP_oxygen_bus_accounting", "LINDE source card / C5p_a", "C5p_a", "Core demand excludes residual/unmodelled O2 users; DRP basis caveated."),
            ("linde_average_oxygen_demand", "Linde/ASU", "average core oxygen demand", "t/h", 150.0, "", linde_o2["average_core_oxygen_demand_t_per_h"], "validation_anchor", "comparison_to_150_t_h_precedent", "LINDE source card / C5p_a", "C5p_a", "150 t/h is a precedent/sanity check, not a capacity constraint."),
            ("linde_asu_electricity", "Linde/ASU", "ASU electricity", "MWh/y", raw_asu_precedent_mwh, "", linde_asu["ASU_electricity_MWh_y"], "development_input", "0p400_MWh_per_t_O2_accounting", "LINDE source card / C5p_a", "C5p_a", "Added to current C5 process scope; not full-site electricity."),
            ("linde_residual_unmodelled_oxygen", "Linde/ASU", "residual/unmodelled O2 to 150 t/h precedent", "t/y", "", "", linde_o2["residual_or_unmodelled_uses_t_y_to_150_precedent"], "reporting_only", "not_added_to_ASU_production", "LINDE source card / C5p_a", "C5p_a", "Reported gap only; not hidden plant demand."),
            ("steam_total_demand", "steam circuit", "existing modelled steam demand", "t steam/y", "", "", steam_health["total_steam_demand_t_y"], "development_input", "existing_C5_steam_demands_mapped_to_pressure_buses", "BOILER_STEAM source card / C5p_b", "C5p_b", "Residual/unmodelled steam demand is reported missing/deferred, not hidden."),
            ("steam_supply_total", "steam circuit", "boiler plus STEG11 steam generation", "t steam/y", "", "", steam_health["total_steam_supply_t_y"], "development_input", "demand_led_mass_flow_steam_generation", "BOILER_STEAM source card / C5p_b", "C5p_b", "Mass-flow steam accounting, not enthalpy model."),
            ("steam_72bar_supply", "steam_72bar", "72 bar supply", "t steam/y", "", "", steam_72["supply_t_y"], "development_input", "K15K16_plus_STEG11_to_72bar_bus", "C5p_b", "C5p_b", "Pressure bus balance, not storage."),
            ("steam_45bar_supply", "steam_45bar", "45 bar supply", "t steam/y", "", "", steam_45["supply_t_y"], "development_input", "K23K24_plus_K41_to_45bar_bus", "C5p_b", "C5p_b", "Pressure bus balance, not storage."),
            ("steam_15bar_process_load", "steam_15bar", "15 bar process load", "t steam/y", "", "", steam_15["process_load_t_y"], "development_input", "unknown_pressure_existing_loads_assumed_15bar", "C5p_b", "C5p_b", "Pressure level assumption must be reviewed before thesis claims."),
            ("steam_spill_total", "steam circuit", "explicit steam spill diagnostic", "t steam/y", "", "", steam_health["total_steam_spill_t_y"], "reporting_only", "explicit_spill_not_hidden_slack", "C5p_b", "C5p_b", "Nonzero spill would indicate missing sinks or overproduction."),
            ("steam_unserved_total", "steam circuit", "unserved steam", "t steam/y", "", "", steam_health["total_unserved_steam_t_y"], "failure_guard", "unserved_steam_must_be_zero_for_thesis_usable_runs", "C5p_b", "C5p_b", "Unserved steam is not hidden slack."),
            ("boiler_k15k16_steam_capacity", "BOILER_C1_K15K16", "steam capacity", "t/h", 220.0, 220.0, k15["steam_capacity_t_h"], "validation_anchor", "source_card_capacity_anchor", "BOILER_STEAM source card / C5p_b", "C5p_b", "Capacity anchor, not hidden hourly constraint in annual ledger."),
            ("boiler_k23k24_steam_capacity", "BOILER_C2_K23K24", "steam capacity", "t/h", 220.0, 220.0, k23["steam_capacity_t_h"], "validation_anchor", "source_card_capacity_anchor", "BOILER_STEAM source card / C5p_b", "C5p_b", "Capacity anchor, not hidden hourly constraint in annual ledger."),
            ("boiler_k41_steam_capacity", "BOILER_C2_K41", "steam capacity", "t/h", 80.0, 80.0, k41["steam_capacity_t_h"], "validation_anchor", "source_card_capacity_anchor", "BOILER_STEAM source card / C5p_b", "C5p_b", "K41 kept separate because COG is blocked."),
            ("steg11_steam_capacity", "STEG11_CHP", "steam capacity", "t/h", 80.0, 80.0, steg11["steam_output_max_t_h"], "validation_anchor", "source_card_capacity_anchor", "BOILER_STEAM source card / C5p_b", "C5p_b", "STEG11 electricity is accounting-only."),
            ("steg11_electricity_capacity", "STEG11_CHP", "electricity capacity", "MWe", 13.1, 13.1, steg11["electricity_max_MWe"], "validation_anchor", "source_card_capacity_anchor", "BOILER_STEAM source card / C5p_b", "C5p_b", "Not market revenue."),
            ("tg2_steam_capacity", "TG2_STEAM_TURBINE", "steam throughput capacity", "t/h", 105.0, 105.0, tg2["steam_flow_max_t_h"], "validation_anchor", "source_card_capacity_anchor", "BOILER_STEAM source card / C5p_b", "C5p_b", "TG2 is steam-only."),
            ("tg2_electricity_capacity", "TG2_STEAM_TURBINE", "electricity capacity", "MWe", 14.5, 14.5, tg2["electricity_max_MWe"], "validation_anchor", "source_card_capacity_anchor", "BOILER_STEAM source card / C5p_b", "C5p_b", "Not market revenue."),
            ("wag_to_steam", "WAG ledger", "BFG/COG to steam layer", "MWh_LHV/y", "", "", steam_wag["WAG_to_steam_MWh_LHV_y"], "development_input", "useful_WAG_to_steam_no_direct_market_value", "C5p_b", "C5p_b", "BOFG remains blocked/deferred for this layer."),
            ("ng_backup_for_steam", "NG", "NG backup for steam", "MWh_LHV/y", "", "", steam_wag["NG_backup_for_steam_MWh_LHV_y"], "reporting_only", "backup_external_fuel_only", "C5p_b", "C5p_b", "NG eligibility is caveated; no gas-market economics added."),
            ("remaining_wag_after_steam", "WAG ledger", "remaining WAG after steam layer", "MWh_LHV/y", "", "", steam_wag["residual_WAG_after_steam_MWh_LHV_y"], "reporting_only", "deferred_generator_interface_or_spill_status", "C5p_b", "C5p_b", "Vattenfall generator/interface layer remains deferred."),
            ("steg11_electricity", "STEG11_CHP", "accounting-only electricity", "MWh/y", "", "", steg11["electricity_output_MWh_e_y"], "reporting_only", "internal_accounting_only_not_market_revenue", "C5p_b", "C5p_b", "Do not present as full-site net generation."),
            ("tg2_electricity", "TG2_STEAM_TURBINE", "accounting-only electricity", "MWh/y", "", "", tg2["electricity_output_MWh_e_y"], "reporting_only", "internal_accounting_only_not_market_revenue", "C5p_b", "C5p_b", "Do not present as Vattenfall generation."),
            ("steam_circuit_internal_electricity", "steam circuit", "total accounting-only electricity", "MWh/y", "", "", steam_elec["total_steam_circuit_electricity_output_MWh_e_y"], "reporting_only", "not_netted_against_process_electricity", "C5p_b", "C5p_b", "Current modelled process electricity is unchanged by C5p_b."),
            ("process_electricity_total", "site", "modelled process electricity after boiler/steam", "MWh/y", "", "", steam_totals["process_electricity_after_boiler_steam_MWh_e_y"], "reporting_only", "current_C5_scope_not_full_site_no_STEG_TG2_netting", "C5p_b", "C5p_b", "Not full-site electricity boundary."),
            ("diagnostic_co2_total", "site", "diagnostic CO2 after boiler/steam", "t/y", "", "", steam_totals["diagnostic_CO2_after_Linde_ASU_t_y"], "reporting_only", "fuel_explicit_steam_CO2_deferred", "C5p_b", "C5p_b", "Not ETS/full-site emissions; avoid WAG combustion double counting."),
            ("generator_dispatch_mode", "IJ01/VN25 generator interface", "dispatch mode", "policy", "", "", generator_health["generator_dispatch_mode"], "development_policy", "fixed_or_validation_scaled_interface", "IJ01/VN25 source card / C5p_c", "C5p_c", "Fixed/interface accounting only; not DA price-responsive dispatch."),
            ("generator_electricity_value_mode", "IJ01/VN25 generator interface", "electricity value mode", "policy", "", "", generator_health["generator_electricity_value_mode"], "development_policy", "offset_site_grid_import_reporting_only", "IJ01/VN25 source card / C5p_c", "C5p_c", "Internal offset/reporting only; no export revenue."),
            ("c0_generator_option_b_status", "C0 generator interface", "Option B status", "status", "", "", generator_health["generator_layer_status"] if config == C0 else "", "development_input", "C0_residual_wag_generator_interface_active", "IJ01/VN25 source card / C5p_c", "C5p_c", "C0 is active residual-WAG-derived interface, not context-only no dispatch."),
            ("c0_generator_interface_total_fuel", "C0 generator interface", "residual WAG generator fuel", "PJ/y", "", "", generator_health["C0_generator_total_fuel_PJ_y"], "development_input", "governed_residual_WAG_after_process_and_steam", "IJ01/VN25 source card / C5p_c", "C5p_c", "Aggregate C0 interface; no public VN25/IJ01 C0 split is claimed."),
            ("c0_generator_electricity_validation_anchor", "C0 generator interface", "electricity validation anchor", "TWh/y", 2.0 if config == C0 else "", "", generator_health["C0_generator_electricity_validation_anchor_TWh_e_y"], "validation_anchor", "context_anchor_only_not_dispatch_target", "IJ01/VN25 source card / C5p_c", "C5p_c", "Reporting/internal offset comparison only; no DA/export revenue."),
            ("c0_generator_electricity_offset_actual", "C0 generator interface", "electricity offset actual", "TWh/y", "", "", generator_health["C0_generator_electricity_actual_TWh_e_y"], "reporting_only", "residual_WAG_times_development_efficiency", "C5p_c", "C5p_c", "Actual is calculated from modelled residual WAG and development efficiency."),
            ("c0_generator_electricity_gap_to_validation_anchor", "C0 generator interface", "electricity validation-anchor gap", "TWh/y", "", "", generator_health["C0_generator_electricity_gap_to_validation_anchor_TWh_e_y"], "reporting_only", "modelled_minus_2TWh_validation_anchor", "C5p_c", "C5p_c", "Gap is reported rather than forcing electricity to the context anchor."),
            ("c0_generator_efficiency_development_only", "C0 generator interface", "development efficiency", "MWh_e/MWh_fuel", 0.34 if config == C0 else "", "", generator_health["C0_generator_electric_efficiency_dev"], "development_input", "single_value_from_0p34_0p35_source_card_range", "IJ01/VN25 source card / C5p_c", "C5p_c", "Not official Tata/Vattenfall unit efficiency."),
            ("vn25_generator_role", "VN25", "enabled/status", "status", "", "", generator_health["VN25_enabled_base"], "development_input", "primary_C1_residual_gas_generator_interface", "IJ01/VN25 source card / C5p_c", "C5p_c", "Not a Vattenfall unit-commitment model."),
            ("ij01_generator_role", "IJ01", "enabled/status", "status", "", "", generator_health["IJ01_enabled_base"], "development_input", "CHP_backup_generator_interface", "IJ01/VN25 source card / C5p_c", "C5p_c", "IJ01 steam/electricity split remains deferred."),
            ("vn24_backup_status", "VN24", "enabled/status", "status", "", "", generator_health["VN24_status"], "development_input", "cold_backup_reserve_only", "IJ01/VN25 source card / C5p_c", "C5p_c", "VN24 inactive in base."),
            ("vn25_generator_fuel", "VN25", "carrier-specific generator fuel", "PJ/y", 13.7 if config == C1 else "", 13.7 if config == C1 else "", generator_health["VN25_total_fuel_PJ_y"], "validation_anchor", "C1_preferred_anchor_interface_limited_by_governed_residual_WAG", "IJ01/VN25 source card / C5p_c", "C5p_c", "Explicit total anchor is 13.7 PJ/y; rounded carrier rows are reported separately."),
            ("ij01_generator_fuel", "IJ01", "carrier-specific generator fuel", "PJ/y", 0.8 if config == C1 else "", 0.8 if config == C1 else "", generator_health["IJ01_total_fuel_PJ_y"], "validation_anchor", "C1_preferred_anchor_interface_limited_by_governed_residual_WAG", "IJ01/VN25 source card / C5p_c", "C5p_c", "IJ01 NG is blocked in base; CHP split deferred."),
            ("generator_total_with_flare", "IJ01/VN25 generator interface", "fuel plus flare comparison", "PJ/y", 14.6 if config == C1 else "", 14.6 if config == C1 else "", generator_health["generator_total_with_flare_model_PJ_y"], "validation_anchor", "C1_preferred_total_with_visible_flaring", "IJ01/VN25 source card / C5p_c", "C5p_c", "Annual validation total, not hourly dispatch or market value."),
            ("generator_fuel_gap", "IJ01/VN25 generator interface", "fuel gap or unserved anchor", "PJ/y", "", "", generator_health["generator_fuel_gap_unserved_PJ_y"], "reporting_only", "governed_residual_WAG_does_not_create_unlimited_fuel", "C5p_c", "C5p_c", "Gap is visible when annual preferred anchors exceed governed residual carrier availability."),
            ("generator_flare_or_spill", "IJ01/VN25 generator interface", "flare/spill diagnostic", "PJ/y", 0.1 if config == C1 else "", 0.1 if config == C1 else "", generator_health["generator_flare_or_spill_PJ_y"], "validation_anchor", "explicit_flaring_anchor_reporting_only", "IJ01/VN25 source card / C5p_c", "C5p_c", "No direct WAG market value or export revenue."),
            ("generator_electricity_offset", "IJ01/VN25 generator interface", "internal electricity offset", "MWh/y", "", "", generator_elec["total_generator_electricity_offset_MWh_e_y"], "reporting_only", "internal_offset_not_DA_revenue", "C5p_c", "C5p_c", "Not full-site net grid import or export revenue."),
            ("vn25_electricity_offset", "VN25", "internal electricity offset", "MWh/y", "", "", generator_elec["VN25_electricity_offset_MWh_e_y"], "reporting_only", "VN25_development_efficiency_only", "C5p_c", "C5p_c", "VN25 efficiency is development-only."),
            ("ij01_electricity_offset", "IJ01", "internal electricity offset", "MWh/y", "", "", generator_elec["IJ01_electricity_offset_MWh_e_y"], "reporting_only", "IJ01_conversion_deferred", "C5p_c", "C5p_c", "IJ01 electricity/steam split is deferred."),
            ("remaining_wag_after_generators", "WAG ledger", "remaining WAG after generators and flare", "PJ/y", "", "", generator_health["residual_WAG_after_generators_and_flare_PJ_y"], "reporting_only", "residual_WAG_visible_not_market_value", "C5p_c", "C5p_c", "Residual WAG still needs annual C0/C1 boundary reconciliation."),
            ("process_electricity_after_generator_offset_reporting_only", "site", "modelled process electricity after generator offset", "MWh/y", "", "", generator_totals["process_electricity_after_generator_offset_reporting_only_MWh_e_y"], "reporting_only", "not_full_site_net_import", "C5p_c", "C5p_c", "Offset is reporting-only and boundary incomplete."),
            ("current_product_gas_reuse_context", "C0 context", "product gas reuse anchor", "PJ/y", 54.0 if config == C0 else "", "", generator_health["C0_product_gas_reuse_context_PJ_y"], "context_anchor", "C0_sanity_check_only", "IJ01/VN25 source card", "C5p_c", "Context only; not exact generator fuel without interpretation."),
            ("current_vattenfall_residual_gas_electricity_context", "C0 context", "residual-gas electricity anchor", "TWh/y", 2.0 if config == C0 else "", "", generator_health["C0_generator_electricity_actual_TWh_e_y"], "validation_anchor", "C0_context_comparison_only_not_target", "IJ01/VN25 source card", "C5p_c", "Used as C0 validation anchor only, not enforced output, Vattenfall profit, or digital twin."),
            ("current_tata_average_power_context", "C0 context", "average electric power anchor", "MW", 360.0 if config == C0 else "", "", generator_health["C0_tata_average_power_context_MW"], "context_anchor", "C0_sanity_check_only", "IJ01/VN25 source card", "C5p_c", "Context only; not a full-site net import claim."),
            ("transferred_power_plants_total_capacity_context", "power plants", "transferred total capacity", "MW", 770.0, "", "", "context_anchor", "not_per_unit_capacity", "IJ01/VN25 source card", "C5p_c", "770 MW is total transferred capacity context, not VN25/IJ01 unit capacity."),
            ("athanasiadis_vn25_capacity_precedent", "VN25", "development capacity precedent", "MW", 350.0, "", generator_elec["VN25_capacity_context_MW_dev"], "development_precedent", "not_public_Tata_capacity", "IJ01/VN25 source card", "C5p_c", "Athanasiadis 350 MW is development precedent only."),
            ("generator_ij01_base_variant_total_fuel", "IJ01/VN25 generator interface", "IJ01-as-base sensitivity total fuel", "PJ/y", 10.0 if config == C1 else "", "", "", "sensitivity_anchor_deferred", "not_active_base", "IJ01/VN25 source card", "C5p_c", "Variant is recorded only; base remains VN25-preferred Mode A."),
        ]
        for item in definitions:
            rows.append(_anchor_row(item[0], config, *item[1:], "Review or freeze before DA/economics if this metric is used in claims."))

    for row in payload["c5m_b_wag"]:
        if int(row["horizon_hours"]) != HORIZON:
            continue
        carrier = row["carrier"]
        config = row["configuration"]
        rows.append(_anchor_row(
            f"wag_{carrier}_generated",
            config,
            "WAG ledger",
            f"{carrier} generated",
            "MWh_LHV/y",
            "",
            "",
            row["generated_site_MWh_LHV_y"],
            "reporting_only",
            "carrier_specific_WAG_generation_ledger",
            "C5m_b WAG ledger",
            "C5m_b",
            "Separate BFG/COG/BOFG, no direct WAG market value.",
            "Boiler/generator/interface layer still needed before economics.",
        ))
        consumption = sum(_num(row[col]) for col in ("direct_use_site_MWh_LHV_y", "boiler_use_site_MWh_LHV_y", "vattenfall_use_site_MWh_LHV_y", "flared_site_MWh_LHV_y"))
        rows.append(_anchor_row(
            f"wag_{carrier}_allocated",
            config,
            "WAG ledger",
            f"{carrier} allocated or residual",
            "MWh_LHV/y",
            "",
            "",
            consumption,
            "reporting_only",
            "carrier_specific_WAG_balance_ledger",
            "C5m_b WAG ledger",
            "C5m_b",
            "Includes direct use, boiler placeholder, Vattenfall/interface placeholder and flare.",
            "Physical boiler/generator implementation needed before economics.",
        ))
    return rows


def build_decision_register() -> list[dict[str, Any]]:
    return [
        {
            "decision_id": "C5_DECISION_ACTIVE_TARGET_6P75",
            "topic": "Active production target",
            "current_choice": "C0/C1 active target fixed at 6.75 Mt/y",
            "alternatives": "Use raw MER 7.2/6.8 anchors; run target sensitivities",
            "why_current_choice_exists": "Common active target supports C0/C1 comparability in development layers.",
            "model_impact": "Scales PEFA, DRP, pellet imports and route quantities; creates anchor gaps versus raw MER.",
            "affects_physical_behaviour": "true",
            "affects_economics_later": "true",
            "sensitivity_required": "yes",
            "freeze_before_DA": "yes",
            "recommended_action": "Freeze as C5 development baseline or schedule explicit target sensitivity before DA economics.",
            "caveat": "Development-only, not Tata truth.",
        },
        {
            "decision_id": "C5_DECISION_HSM_BASE_0_50",
            "topic": "HSM hot-charge cap",
            "current_choice": "C5l_d base_0_50 is active HSM/WBW heat case",
            "alternatives": "high_0_80 sensitivity; uncapped C5l_c reference",
            "why_current_choice_exists": "Guardrail against 100% hot charging and underreported reheating.",
            "model_impact": "Increases HSM reheat demand and WAG heat allocation relative to uncapped reference.",
            "affects_physical_behaviour": "true",
            "affects_economics_later": "true",
            "sensitivity_required": "yes",
            "freeze_before_DA": "yes",
            "recommended_action": "Keep base_0_50 as base and preserve high/uncapped references.",
            "caveat": "Development guardrail, not Tata-measured hot-charge share.",
        },
        {
            "decision_id": "C5_DECISION_PELLET_PROXY",
            "topic": "Pellet burden reconciliation",
            "current_choice": "Single fired_pellets_proxy with fixed PEFA and imported pellet supply",
            "alternatives": "BF-grade/DR-grade split; pellet quality and chemistry; import sensitivity",
            "why_current_choice_exists": "Public data supports annual balance, not quality-specific burden recipes.",
            "model_impact": "Closes simplified pellet accounting but cannot validate grade-specific constraints.",
            "affects_physical_behaviour": "true",
            "affects_economics_later": "true",
            "sensitivity_required": "yes",
            "freeze_before_DA": "yes",
            "recommended_action": "Keep proxy for C5; add grade split only if required for DRP/BF feasibility claims.",
            "caveat": "BF pellet coefficient is reconciliation, not burden recipe.",
        },
        {
            "decision_id": "C5_DECISION_EAF_DRI_COEFF",
            "topic": "EAF DRI coefficient reconciliation",
            "current_choice": "Preserve C5 EAF LS target and derive active DRI coefficient from available DRP DRI",
            "alternatives": "Use raw 0.848 coefficient and add HBI/imported DRI; reduce EAF output; change DRP output",
            "why_current_choice_exists": "Avoids hidden DRI/HBI source and preserves C5 route split.",
            "model_impact": "Resolved C1 coefficient is about 0.8297 t DRI/t LS, below raw source check.",
            "affects_physical_behaviour": "true",
            "affects_economics_later": "true",
            "sensitivity_required": "yes",
            "freeze_before_DA": "yes",
            "recommended_action": "Freeze as C5 reconciliation or implement explicit HBI/import sensitivity before DA claims.",
            "caveat": "Not an EAF recipe truth.",
        },
        {
            "decision_id": "C5_DECISION_DSP_PLACEHOLDER",
            "topic": "DSP output and route origin",
            "current_choice": "Preserve C5l_d 1.35 Mt/y DSP placeholder and wrap explicit DSP process around it",
            "alternatives": "Use raw 1.5 Mt/y anchor; active-scaled anchor; explicit route-origin split",
            "why_current_choice_exists": "Avoids changing C5l_d final product and HSM/WBW outputs.",
            "model_impact": "Raw DSP gap remains -0.15 Mt/y; C1 90% EAF-origin DSP share cannot be validated.",
            "affects_physical_behaviour": "true",
            "affects_economics_later": "true",
            "sensitivity_required": "yes",
            "freeze_before_DA": "yes",
            "recommended_action": "Decide whether to keep 1.35 Mt/y active DSP or align to 1.5 Mt/y with downstream rerouting.",
            "caveat": "Route origin is pooled, not BOF/EAF-specific.",
        },
        {
            "decision_id": "C5_DECISION_COKE_RECONCILIATION",
            "topic": "Coke balance reconciliation",
            "current_choice": "C5m_f bounded coke reconciliation is the active development baseline; external/unmodelled coke is fallback-only",
            "alternatives": "Keep fallback-only external coke sensitivity; reopen only with explicit source evidence or infeasibility finding",
            "why_current_choice_exists": "Accepted follow-up to the repaired BF coke-demand driver; avoids hidden external coke while keeping KGF anchor/BF coke-rate trade-offs explicit.",
            "model_impact": "Uses bounded KGF anchor and BF coke-rate reconciliation as the active development accounting basis.",
            "affects_physical_behaviour": "true",
            "affects_economics_later": "true",
            "sensitivity_required": "yes",
            "freeze_before_DA": "yes",
            "recommended_action": "Keep C5m_f bounded reconciliation as active development baseline; do not reopen unless a later test finds inconsistency.",
            "caveat": "This is still development-only and not thesis-approved; external coke remains fallback-only.",
        },
        {
            "decision_id": "C5_DECISION_FINAL_DENOMINATOR",
            "topic": "Economics denominator",
            "current_choice": "Report liquid steel target and downstream final-product proxy separately",
            "alternatives": "Use liquid-steel equivalent; use HSM+DSP final product proxy; use raw MER final-product anchors",
            "why_current_choice_exists": "C5 has downstream losses/imported slab and DSP/HSM outputs, but no final product sales/economics layer and generator/interface plus residual electricity/NG boundaries remain incomplete.",
            "model_impact": "EUR/t results can change materially depending on denominator.",
            "affects_physical_behaviour": "false",
            "affects_economics_later": "true",
            "sensitivity_required": "yes",
            "freeze_before_DA": "yes",
            "recommended_action": "Do not choose yet; keep unresolved until generator/interface and residual electricity/NG layers are implemented and product-revenue policy is scoped.",
            "caveat": "Linde/ASU and boiler/steam are now accounting-only; product revenue remains blocked.",
        },
        {
            "decision_id": "C5_DECISION_INTERNAL_SCRAP",
            "topic": "Internal scrap loop",
            "current_choice": "HSM/DSP internal losses are reported; EAF scrap input remains explicit accounting input",
            "alternatives": "Closed internal scrap pool; external scrap import accounting; quality-specific scrap constraints",
            "why_current_choice_exists": "Avoids free scrap supply until scrap loop is governed.",
            "model_impact": "Internal scrap is visible but cannot reduce EAF external scrap requirements.",
            "affects_physical_behaviour": "false",
            "affects_economics_later": "true",
            "sensitivity_required": "yes",
            "freeze_before_DA": "yes",
            "recommended_action": "Add scrap-pool accounting before raw-material economics.",
            "caveat": "Do not connect DSP/HSM scrap to EAF without a governed loop.",
        },
    ]


def build_denominator_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        c5k = _key(payload["c5k"], config)
        c5l_d = _key(payload["c5l_d"], config)
        dsp_down = _key(payload["dsp_downstream"], config)
        eaf = _key(payload["eaf"], config)
        dsp = _key(payload["dsp"], config)
        raw_final = 6_900_000.0 if config == C0 else 7_000_000.0
        items = [
            ("liquid_steel_target", "t/y", c5k["active_total_liquid_steel_target_site_t_y"], 7_200_000.0 if config == C0 else 6_800_000.0, "Internal technical production target.", "no", "Ignores downstream yield/imported slab effects.", "Use for route consistency, not EUR/t final product."),
            ("BOF_liquid_steel", "t/y", c5k["active_bof_liquid_steel_target_site_t_y"], 7_200_000.0 if config == C0 else 3_400_000.0, "Route liquid steel output.", "no", "Intermediate route metric.", "Keep as technical diagnostic."),
            ("EAF_liquid_steel", "t/y", eaf["EAF_LS_output_site_t_y"], 0.0 if config == C0 else 3_300_000.0, "Route liquid steel output.", "no", "Intermediate route metric.", "Keep as technical diagnostic."),
            ("DSP_output", "t/y", dsp["DSP_output_site_t_y"], 1_500_000.0, "Downstream final-product component.", "maybe", "Current active value is 1.35 Mt/y, not raw anchor.", "Candidate denominator component if final-product proxy is chosen."),
            ("HSM_WBW_output", "t/y", c5l_d["hsm_output_site_t_y"], 5_400_000.0 if config == C0 else 5_500_000.0, "Downstream final-product component.", "maybe", "Reflects C5 slab input and imported slab conventions.", "Candidate denominator component if final-product proxy is chosen."),
            ("final_product_proxy_HSM_plus_DSP", "t/y", dsp_down["DSP_plus_HSM_final_product_proxy_site_t_y"], raw_final, "Current C5 downstream final-product proxy.", "not_yet", "Best current denominator candidate but policy not frozen.", "Freeze before economics."),
            ("imported_slab_to_HSM", "t/y", c5l_d["imported_cold_slab_site_t_y"], 0.0 if config == C0 else 600_000.0, "Imported slab supports HSM output in C1.", "no", "Affects final-product numerator and route comparability.", "Report separately in denominator policy."),
            ("HSM_internal_loss_or_scrap", "t/y", _num(c5l_d["hsm_slab_input_site_t_y"]) - _num(c5l_d["hsm_output_site_t_y"]), "", "HSM yield/loss diagnostic.", "no", "Not a sold-product denominator.", "Use for material accounting only."),
            ("DSP_internal_scrap_loss", "t/y", dsp["DSP_internal_scrap_loss_site_t_y"], "", "DSP yield/loss diagnostic.", "no", "Reporting-only and not closed to scrap pool.", "Use for future scrap loop."),
        ]
        for metric, unit, model, raw, interpretation, usable, risk, recommendation in items:
            rows.append({
                "configuration": config,
                "metric": metric,
                "unit": unit,
                "model_value": model,
                "raw_anchor_value": raw,
                "gap": _gap(model, "", raw)[0] if raw != "" else "",
                "interpretation": interpretation,
                "can_be_used_for_eur_per_t_now": usable,
                "risk_if_used": risk,
                "recommendation": recommendation,
            })
    return rows


def build_route_scrap_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        pellet = _key(payload["pellet"], config)
        pefa = _key(payload["pefa_material"], config)
        drp = _key(payload["drp"], config)
        drp_buffer = _key(payload["drp_buffer"], config)
        eaf = _key(payload["eaf"], config)
        eaf_handoff = _key(payload["eaf_handoff"], config)
        dsp = _key(payload["dsp"], config)
        dsp_act = _key(payload["dsp_activity"], config)
        dsp_down = _key(payload["dsp_downstream"], config)
        c5k = _key(payload["c5k"], config)
        c5l_d = _key(payload["c5l_d"], config)
        coke = _coke_case(payload, config)
        route_items = [
            ("PEFA_to_pellet_burden", "PEFA fired pellets -> pellet balance", pellet["pellet_balance_within_tolerance"], pellet["pellet_net_balance_site_t_y"], "t/y", "C5n_a/C5n_b", "gap/surplus diagnostic only", "Keep; grade split deferred.", "Single fired_pellets_proxy, no grade quality."),
            ("pellet_burden_to_DRP", "DRP pellet demand", "closed" if abs(_num(drp["pellets_to_DRP_site_t_y"]) - _num(pellet["DRP_pellet_demand_site_t_y"])) <= 1e-3 else "mismatch", drp["pellets_to_DRP_site_t_y"], "t/y", "C5n_b/C5o_a", "none if closed", "Keep; no double counting.", "C0 inactive."),
            ("DRP_to_DRI_buffer_to_EAF", "DRI buffer handoff", eaf_handoff["DRI_buffer_terminal_status"], eaf_handoff["DRI_inventory_drift_t"], "t", "C5o_a/C5o_b", "terminal violation if nonzero", "Keep terminal equality.", "Temporary DRI interface replaced."),
            ("BOF_EAF_to_DSP_HSM", "liquid steel to downstream", "closed_with_caveats", dsp_down["DSP_plus_HSM_final_product_proxy_site_t_y"], "t/y", "C5l_d/C5o_c", "route-origin pooled; gross DSP input exposed separately", "Add route-origin split only if needed for thesis route-share claim.", "No hidden LS source in C5o_c."),
            ("DSP_HSM_to_final_proxy", "final product proxy", "reported", dsp_down["DSP_plus_HSM_final_product_proxy_site_t_y"], "t/y", "C5l_d/C5o_c", "denominator not frozen", "Freeze denominator before economics.", "HSM + DSP proxy, not product revenue."),
            ("coke_balance", "KGF coke vs BF coke demand", f"gap_closed_{coke['gap_closed']}", coke["coke_balance_gap_site_t_y"], "t/y", "C5m_e/C5m_f", "bounded reconciliation is active development baseline; external coke fallback not active", "Keep C5m_f bounded reconciliation status visible in future stages.", "External coke fallback not implemented."),
            ("bulk_storage", "pellet/coke/sinter storage", "diagnostic_nonbinding_policy", "", "-", "C5n_b/C5m_b", "inventory drift can hide if not monitored", "Keep terminal/inventory diagnostics.", "Practically non-binding capacity is not free supply."),
        ]
        for topic, flow, status, value, unit, source, issue, fix, caveat in route_items:
            rows.append({
                "configuration": config,
                "topic": topic,
                "flow_or_asset": flow,
                "status": status,
                "model_value": value,
                "unit": unit,
                "source_or_anchor": source,
                "gap_or_issue": issue,
                "risk": "physical/economic claim can be overstated if caveat is ignored",
                "recommended_fix_or_defer": fix,
                "caveat": caveat,
            })

        scrap_items = [
            ("BOF_scrap_input", c5k["bof_scrap_input_site_t_y"], "active_material_demand", "C5k", "BOF scrap input is active route accounting."),
            ("EAF_scrap_input", eaf["EAF_scrap_input_site_t_y"], "active_material_demand", "C5o_b", "No hidden scrap import slack beyond explicit accounting row."),
            ("HSM_internal_loss_or_scrap", _num(c5l_d["hsm_slab_input_site_t_y"]) - _num(c5l_d["hsm_output_site_t_y"]), "reporting_only", "C5l_d", "Not connected to scrap loop."),
            ("DSP_internal_scrap_loss", dsp["DSP_internal_scrap_loss_site_t_y"], "reporting_only", "C5o_c", "Not used as free EAF input."),
            ("internal_scrap_to_EAF", 0.0, "not_represented", "C5o_c", "Future scrap loop needed before raw-material economics."),
        ]
        for flow, value, status, source, caveat in scrap_items:
            rows.append({
                "configuration": config,
                "topic": "internal_scrap",
                "flow_or_asset": flow,
                "status": status,
                "model_value": value,
                "unit": "t/y",
                "source_or_anchor": source,
                "gap_or_issue": "scrap loop not closed" if status != "active_material_demand" else "active demand visible",
                "risk": "EAF scrap economics incomplete until internal/external scrap boundary is frozen.",
                "recommended_fix_or_defer": "Add governed scrap-pool accounting later; do not connect reporting-only scrap silently.",
                "caveat": caveat,
            })
        if config == C1:
            rows.append({
                "configuration": config,
                "topic": "DSP_route_origin",
                "flow_or_asset": "EAF-origin DSP share",
                "status": dsp_act["C1_EAF_route_share_status"],
                "model_value": "",
                "unit": "fraction",
                "source_or_anchor": "DSP source card approx. 0.90 validation anchor",
                "gap_or_issue": "Current C5 has pooled liquid-steel-to-DSP interface only.",
                "risk": "Blocks thesis claim that 90% of DSP steel comes from EAF route; not a current physical feasibility blocker.",
                "recommended_fix_or_defer": "Add BOF/EAF origin-tagged downstream routing if route-share validation becomes material.",
                "caveat": "Do not invent false precision.",
            })
    return rows


def build_utility_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    c0_bof_o2 = _num(_key(payload["c5k"], C0)["bof_oxygen_input_site_kg_y"]) / 1000.0
    c1_bof_o2 = _num(_key(payload["c5k"], C1)["bof_oxygen_input_site_kg_y"]) / 1000.0
    c1_drp_o2 = _num(_key(payload["drp"], C1)["DRP_oxygen_diagnostic_site_t_y"])
    c1_eaf_o2 = _num(_key(payload["eaf"], C1)["EAF_oxygen_diagnostic_t_y"])
    c0_asu_mw = _fmt(_key(payload["linde_asu"], C0)["ASU_average_MW"])
    c1_asu_mw = _fmt(_key(payload["linde_asu"], C1)["ASU_average_MW"])
    c0_steam = (
        f"C5p_b mapped demand {_fmt(_key(payload['steam_health'], C0)['total_steam_demand_t_y'])} t/y; "
        f"spill {_fmt(_key(payload['steam_health'], C0)['total_steam_spill_t_y'])} t/y; "
        f"unserved {_fmt(_key(payload['steam_health'], C0)['total_unserved_steam_t_y'])} t/y"
    )
    c1_steam = (
        f"C5p_b mapped demand {_fmt(_key(payload['steam_health'], C1)['total_steam_demand_t_y'])} t/y; "
        f"spill {_fmt(_key(payload['steam_health'], C1)['total_steam_spill_t_y'])} t/y; "
        f"unserved {_fmt(_key(payload['steam_health'], C1)['total_unserved_steam_t_y'])} t/y; "
        "EAF steam recovery reporting-only"
    )
    c0_steam_supply = (
        f"K15/K16 {_fmt(_key(payload['steam_health'], C0)['K15K16_steam_output_t_y'])} t/y, "
        f"K23/K24 {_fmt(_key(payload['steam_health'], C0)['K23K24_steam_output_t_y'])} t/y, "
        f"K41 {_fmt(_key(payload['steam_health'], C0)['K41_steam_output_t_y'])} t/y, "
        f"STEG11 {_fmt(_key(payload['steam_health'], C0)['STEG11_steam_output_t_y'])} t/y; "
        f"STEG11+TG2 electricity {_fmt(_key(payload['steam_health'], C0)['total_steam_circuit_electricity_output_MWh_e_y'])} MWh/y accounting-only"
    )
    c1_steam_supply = (
        f"K15/K16 {_fmt(_key(payload['steam_health'], C1)['K15K16_steam_output_t_y'])} t/y, "
        f"K23/K24 {_fmt(_key(payload['steam_health'], C1)['K23K24_steam_output_t_y'])} t/y, "
        f"K41 {_fmt(_key(payload['steam_health'], C1)['K41_steam_output_t_y'])} t/y, "
        f"STEG11 {_fmt(_key(payload['steam_health'], C1)['STEG11_steam_output_t_y'])} t/y; "
        f"STEG11+TG2 electricity {_fmt(_key(payload['steam_health'], C1)['total_steam_circuit_electricity_output_MWh_e_y'])} MWh/y accounting-only"
    )
    c0_elec = _fmt(_key(payload["steam_totals"], C0)["process_electricity_after_boiler_steam_MWh_e_y"])
    c1_elec = _fmt(_key(payload["steam_totals"], C1)["process_electricity_after_boiler_steam_MWh_e_y"])
    c0_gen = (
        f"C5p_c C0 residual-WAG interface: generator fuel "
        f"{_fmt(_key(payload['generator_health'], C0)['C0_generator_total_fuel_PJ_y'])} PJ/y; "
        f"electricity offset {_fmt(_key(payload['generator_health'], C0)['C0_generator_electricity_actual_TWh_e_y'])} TWh/y; "
        f"2.0 TWh validation gap {_fmt(_key(payload['generator_health'], C0)['C0_generator_electricity_gap_to_validation_anchor_TWh_e_y'])} TWh/y; "
        f"remaining WAG {_fmt(_key(payload['generator_health'], C0)['residual_WAG_after_generators_and_flare_PJ_y'])} PJ/y"
    )
    c1_gen = (
        f"C5p_c C1 Mode A: VN25 fuel {_fmt(_key(payload['generator_health'], C1)['VN25_total_fuel_PJ_y'])} PJ/y, "
        f"IJ01 fuel {_fmt(_key(payload['generator_health'], C1)['IJ01_total_fuel_PJ_y'])} PJ/y, "
        f"gap {_fmt(_key(payload['generator_health'], C1)['generator_fuel_gap_unserved_PJ_y'])} PJ/y, "
        f"electricity offset {_fmt(_key(payload['generator_health'], C1)['total_generator_electricity_offset_MWh_e_y'])} MWh/y"
    )
    c0_elec_after_gen = _fmt(_key(payload["generator_totals"], C0)["process_electricity_after_generator_offset_reporting_only_MWh_e_y"])
    c1_elec_after_gen = _fmt(_key(payload["generator_totals"], C1)["process_electricity_after_generator_offset_reporting_only_MWh_e_y"])
    c0_ng = "PEFA/EAF/DSP NG zero or backup only; DRP inactive"
    c1_ng = f"DRP {_fmt(_key(payload['drp'], C1)['DRP_NG_total_PJ_y'])} PJ/y plus EAF {_fmt(_key(payload['eaf'], C1)['EAF_NG_PJ_y'])} PJ/y; DSP NG zero"
    return [
        {
            "utility_area": "Linde_ASU_oxygen",
            "current_demands_available": f"C0 BOF {c0_bof_o2:.0f} t/y; C1 BOF {c1_bof_o2:.0f} t/y, DRP {c1_drp_o2:.0f} t/y, EAF {c1_eaf_o2:.0f} t/y",
            "current_supply_available": f"C5p_a accounting-only ASU oxygen supply and electricity: C0 {c0_asu_mw} MW avg; C1 {c1_asu_mw} MW avg",
            "missing_assets": "ASU flexibility/unit commitment, source-backed usable O2 buffer capacity, liquid O2 dispatch, N2/Ar/dry-air active carriers",
            "current_status": "implemented_accounting_only_after_C5p_a",
            "blocker_for_physical_model": "low for oxygen accounting; medium for buffer/flexibility claims",
            "blocker_for_economics": "medium: ASU electricity now visible, but no costs/DA dispatch and DRP oxygen basis needs review",
            "recommended_stage": "review_DRP_oxygen_basis_then_C5p_b_boiler_steam",
            "risk_if_postponed": "Oxygen accounting exists, but DRP O2 basis and buffer/flexibility claims remain caveated.",
            "caveat": "C5p_a is development-only; ASU is not mFRR/DA-flexible and O2 buffer is not strategic storage.",
        },
        {
            "utility_area": "boilers_steam",
            "current_demands_available": f"C0: {c0_steam}; C1: {c1_steam}",
            "current_supply_available": f"C0: {c0_steam_supply}; C1: {c1_steam_supply}",
            "missing_assets": "source-backed residual steam demand, full thermodynamic steam model, fuel-explicit CO2 reconciliation, generator/interface boundary",
            "current_status": "implemented_accounting_only_after_C5p_b",
            "blocker_for_physical_model": "low for compact steam utility accounting; medium for pressure/enthalpy and residual-load claims",
            "blocker_for_economics": "medium: WAG/NG to steam is visible, but no prices, generator interface, product revenue or residual load boundary",
            "recommended_stage": "C5p_c_generator_interface_boundary_and_residual_load_scope",
            "risk_if_postponed": "STEG11/TG2 electricity and remaining WAG cannot be connected to full-site electricity claims.",
            "caveat": "Mass-flow steam accounting only; no artificial internal steam price or direct WAG market value.",
        },
        {
            "utility_area": "Vattenfall_IJ01_VN25_generators",
            "current_demands_available": "WAG carrier residual/interface rows exist by BFG/COG/BOFG",
            "current_supply_available": f"C0: {c0_gen}; C1: {c1_gen}",
            "missing_assets": "unit commitment, heat/power split, residual electricity loads, site import/export boundary, source-backed IJ01 conversion",
            "current_status": "implemented_accounting_only_after_C5p_c",
            "blocker_for_physical_model": "low for generator-interface accounting; high for full power-plant boundary",
            "blocker_for_economics": "high",
            "recommended_stage": "annual_C0_C1_physical_accounting_anchor_reconciliation_then_residual_electricity_NG_boundary",
            "risk_if_postponed": "Full-site electricity, import/export and WAG opportunity-cost claims remain unsupported.",
            "caveat": "No export revenue, price response, mFRR, direct WAG market valuation or Vattenfall digital-twin claim.",
        },
        {
            "utility_area": "residual_electricity",
            "current_demands_available": f"Current modelled process electricity after C5p_b: C0 {c0_elec} MWh/y; C1 {c1_elec} MWh/y",
            "current_supply_available": f"C5p_c reports generator offsets but not a full boundary: C0 after offset {c0_elec_after_gen} MWh/y; C1 after offset {c1_elec_after_gen} MWh/y",
            "missing_assets": "fixed/background loads, site import/export boundary, grid capacity, residual auxiliaries and validation against annual site electricity anchors",
            "current_status": "process_scope_plus_internal_offsets_reporting_only",
            "blocker_for_physical_model": "low for plant-ledger C5; high for full site",
            "blocker_for_economics": "high",
            "recommended_stage": "annual_C0_C1_physical_accounting_anchor_reconciliation_then_residual_electricity_boundary",
            "risk_if_postponed": "DA economics would price only modelled process loads and may be mistaken for full-site cost.",
            "caveat": "Label as current_C5_scope with reporting-only generator offset, not full_site_net_electricity.",
        },
        {
            "utility_area": "residual_NG",
            "current_demands_available": f"C0: {c0_ng}; C1: {c1_ng}",
            "current_supply_available": "external NG demand accounting only; no residual NG loads",
            "missing_assets": "residual/site NG loads, boiler NG backup, procurement boundary",
            "current_status": "partial_process_NG_only",
            "blocker_for_physical_model": "medium",
            "blocker_for_economics": "high",
            "recommended_stage": "with_boiler_and_residual_utility_boundary",
            "risk_if_postponed": "NG cost comparison excludes non-modelled utility and residual loads.",
            "caveat": "Do not use residual NG as calibration slack.",
        },
        {
            "utility_area": "consolidated_CO2",
            "current_demands_available": "BF/KGF/BOF/Sinter/PEFA/EAF/DSP diagnostic counters and DRP capture stream exist",
            "current_supply_available": "no ETS objective; no full-site emissions boundary; no fuel-explicit WAG combustion CO2 objective",
            "missing_assets": "boundary policy, fuel-explicit vs aggregate reconciliation, CCS transport/storage availability, Scope 2 policy",
            "current_status": "diagnostic_only",
            "blocker_for_physical_model": "low",
            "blocker_for_economics": "high",
            "recommended_stage": "after_utility_boundary_before_ETS_sensitivity",
            "risk_if_postponed": "CO2 values may be double-counted or overinterpreted as ETS/full-site emissions.",
            "caveat": "Keep CO2 out of objective until boundary is frozen.",
        },
    ]


def _largest_gaps(anchor_rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    candidates = []
    for row in anchor_rows:
        if row["absolute_gap"] in ("", None):
            continue
        candidates.append(row)
    return sorted(candidates, key=lambda row: abs(_num(row["absolute_gap"])), reverse=True)[:limit]


def write_report(
    anchor_rows: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    denom: list[dict[str, Any]],
    route_scrap: list[dict[str, Any]],
    utility: list[dict[str, Any]],
) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    c0_final = next(row for row in denom if row["configuration"] == C0 and row["metric"] == "final_product_proxy_HSM_plus_DSP")
    c1_final = next(row for row in denom if row["configuration"] == C1 and row["metric"] == "final_product_proxy_HSM_plus_DSP")
    largest = _largest_gaps(anchor_rows, 6)
    lines = [
        "# C5 Anchor, Route, Denominator And Material-Accounting Diagnostics",
        "",
        "## Purpose And Scope",
        "",
        "This is a diagnostic-only review of the current C5 plant-layer artifacts after KGF/BF/BOF/HSM/WBW/Sinter/PEFA/pellet burden/DRP/EAF/DSP, Linde/ASU oxygen, boiler/steam-circuit accounting and IJ01/VN25 generator-interface accounting. It does not change production targets, route shares, process coefficients or economics.",
        "",
        "The model remains a public Tata Steel IJmuiden-inspired development model. It is not a confidential digital twin and not thesis-approved.",
        "",
        "## Current C5 Coverage Summary",
        "",
        "- Active C0/C1 liquid-steel target remains 6.75 Mt/y.",
        "- C5l_d `base_0_50` remains the default HSM/WBW heat case.",
        "- PEFA, pellet burden, DRP, EAF, DSP, Linde/ASU oxygen, boiler/steam and IJ01/VN25 generators are represented as development-only accounting/physical layers with compact healthchecks.",
        "- Linde/ASU oxygen adds current-C5 process electricity accounting; C5p_b adds mass-flow steam buses, WAG/NG-to-steam allocation and STEG11/TG2 accounting-only electricity; C5p_c adds carrier-specific C1 IJ01/VN25 accounting plus a C0 residual-WAG-derived generator-interface offset with 2.0 TWh/y as validation anchor only. These are not economic objective layers.",
        "",
        "## Anchor Reconciliation Summary",
        "",
    ]
    for row in largest:
        lines.append(
            f"- {row['configuration']} `{row['anchor_id']}`: model {row['model_output']} {row['unit']}, "
            f"gap {row['absolute_gap']} versus active/raw reference. {row['caveat']}"
        )
    lines.extend([
        "",
        "The largest gaps are mostly expected consequences of the active 6.75 Mt/y target, the C5l_d downstream/HSM routing convention, and explicit development reconciliation choices. They are not fixed in this diagnostic task.",
        "",
        "## Scaling And Reconciliation Modes",
        "",
    ])
    for decision in decisions:
        lines.append(f"- `{decision['decision_id']}`: {decision['current_choice']}. Recommended action: {decision['recommended_action']}")
    lines.extend([
        "",
        "## Final-Product Denominator Discussion",
        "",
        f"- C0 final-product proxy is {_fmt(c0_final['model_value'])} t/y versus raw final-product context {_fmt(c0_final['raw_anchor_value'])} t/y.",
        f"- C1 final-product proxy is {_fmt(c1_final['model_value'])} t/y versus raw final-product context {_fmt(c1_final['raw_anchor_value'])} t/y.",
        "- Liquid steel is an internal technical target; HSM plus DSP is the current downstream final-product proxy.",
        "- A future economics denominator must be frozen before EUR/t claims. Options are liquid-steel equivalent, current final-product proxy, or an explicitly revised downstream product target.",
        "- The denominator remains unresolved after C5p_c because residual electricity/NG, consolidated grid-boundary and product-revenue layers are still incomplete.",
        "",
        "## DSP Route-Origin Status",
        "",
        "- C0 has a 20% OSF-to-DSP route-share check that passes under the current C5l_d placeholder replacement.",
        "- C1 has only a pooled liquid-steel-to-DSP interface. The approximate 90% EAF-origin DSP anchor cannot currently be validated.",
        "- This does not block current physical feasibility, but it blocks a thesis claim that 90% of DSP material is EAF-origin unless route-origin tagging is added.",
        "",
        "## Internal Scrap Status",
        "",
        "- BOF and EAF scrap inputs are active material-accounting inputs.",
        "- HSM and DSP internal losses/scrap are reporting-only diagnostics.",
        "- Internal scrap is not currently a free EAF input. A governed scrap-pool layer is needed before raw-material economics or scrap-loop claims.",
        "",
        "## Upstream/Downstream Consistency",
        "",
        "- PEFA -> pellet burden -> DRP closes in the compact pellet-balance diagnostics.",
        "- DRP -> DRI buffer -> EAF closes with terminal DRI inventory equality after C5o_b.",
        "- BOF/EAF -> DSP/HSM/WBW is coherent as pooled downstream routing, but route-origin precision is missing for C1 DSP.",
        "- DSP/HSM/WBW -> final-product proxy is reported and placeholder replacement is explicit.",
        "",
        "## Utility Readiness",
        "",
    ])
    for row in utility:
        lines.append(f"- `{row['utility_area']}`: {row['current_status']}. Recommended stage: {row['recommended_stage']}. Risk: {row['risk_if_postponed']}")
    lines.extend([
        "",
        "## Key Red Flags",
        "",
        "- No immediate model-health failure is introduced by C5o_c artifacts.",
        "- The red flags before economics are denominator ambiguity, C1 DSP route-origin opacity, missing governed scrap loop, DRP oxygen-basis review, residual electricity/NG boundary absence, and diagnostic-only CO2.",
        "",
        "## Recommended Next Decisions",
        "",
        "1. Freeze denominator policy for future EUR/t reporting: liquid-steel equivalent versus current final-product proxy versus revised downstream target.",
        "2. Decide whether C1 DSP route-origin tagging is required before thesis route-share claims.",
        "3. Keep C5p_a Linde/ASU, C5p_b boiler/steam and C5p_c generator-interface outputs as accounting-only layers until DRP oxygen basis and remaining utility boundaries are reviewed.",
        "4. Defer economics until residual electricity/NG and product-revenue boundaries are explicitly scoped.",
        "",
        "## Generated Tables",
        "",
        "- `data/03_Optimisation/inputs/assets/steel/S4/c5_anchor_route_diagnostics/c5_anchor_reconciliation_matrix.csv`",
        "- `data/03_Optimisation/inputs/assets/steel/S4/c5_anchor_route_diagnostics/c5_reconciliation_decision_register.csv`",
        "- `data/03_Optimisation/inputs/assets/steel/S4/c5_anchor_route_diagnostics/c5_final_product_denominator_diagnostics.csv`",
        "- `data/03_Optimisation/inputs/assets/steel/S4/c5_anchor_route_diagnostics/c5_route_origin_and_scrap_diagnostics.csv`",
        "- `data/03_Optimisation/inputs/assets/steel/S4/c5_anchor_route_diagnostics/c5_utility_readiness_diagnostics.csv`",
        "",
    ])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


ANCHOR_COLUMNS = [
    "anchor_id",
    "configuration",
    "asset_or_flow",
    "metric",
    "unit",
    "raw_source_anchor",
    "active_scaled_anchor",
    "model_output",
    "absolute_gap",
    "relative_gap",
    "anchor_role",
    "reconciliation_mode",
    "source_card_or_stage",
    "stage_introduced",
    "thesis_usability",
    "caveat",
    "decision_needed",
]
DECISION_COLUMNS = [
    "decision_id",
    "topic",
    "current_choice",
    "alternatives",
    "why_current_choice_exists",
    "model_impact",
    "affects_physical_behaviour",
    "affects_economics_later",
    "sensitivity_required",
    "freeze_before_DA",
    "recommended_action",
    "caveat",
]
DENOM_COLUMNS = [
    "configuration",
    "metric",
    "unit",
    "model_value",
    "raw_anchor_value",
    "gap",
    "interpretation",
    "can_be_used_for_eur_per_t_now",
    "risk_if_used",
    "recommendation",
]
ROUTE_COLUMNS = [
    "configuration",
    "topic",
    "flow_or_asset",
    "status",
    "model_value",
    "unit",
    "source_or_anchor",
    "gap_or_issue",
    "risk",
    "recommended_fix_or_defer",
    "caveat",
]
UTILITY_COLUMNS = [
    "utility_area",
    "current_demands_available",
    "current_supply_available",
    "missing_assets",
    "current_status",
    "blocker_for_physical_model",
    "blocker_for_economics",
    "recommended_stage",
    "risk_if_postponed",
    "caveat",
]


def build_outputs() -> dict[str, Any]:
    payload = _load_payload()
    anchor_rows = build_anchor_matrix(payload)
    decisions = build_decision_register()
    denom = build_denominator_rows(payload)
    route_scrap = build_route_scrap_rows(payload)
    utility = build_utility_rows(payload)
    _write_csv(OUT_DIR / "c5_anchor_reconciliation_matrix.csv", anchor_rows, ANCHOR_COLUMNS)
    _write_csv(OUT_DIR / "c5_reconciliation_decision_register.csv", decisions, DECISION_COLUMNS)
    _write_csv(OUT_DIR / "c5_final_product_denominator_diagnostics.csv", denom, DENOM_COLUMNS)
    _write_csv(OUT_DIR / "c5_route_origin_and_scrap_diagnostics.csv", route_scrap, ROUTE_COLUMNS)
    _write_csv(OUT_DIR / "c5_utility_readiness_diagnostics.csv", utility, UTILITY_COLUMNS)
    write_report(anchor_rows, decisions, denom, route_scrap, utility)
    return {
        "status": "pass_diagnostic_only",
        "report": REPORT_PATH.as_posix(),
        "output_dir": OUT_DIR.as_posix(),
        "rows": {
            "anchor_reconciliation": len(anchor_rows),
            "decision_register": len(decisions),
            "denominator": len(denom),
            "route_scrap": len(route_scrap),
            "utility": len(utility),
        },
    }


def main() -> int:
    print(json.dumps(build_outputs(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
