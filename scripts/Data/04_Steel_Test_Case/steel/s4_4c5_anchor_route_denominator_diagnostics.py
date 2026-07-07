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
    model_value = _num(model)
    denominator = active if active not in ("", None) else raw
    if denominator in ("", None):
        return "", ""
    denom = _num(denominator)
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
            ("process_electricity_total", "site", "modelled process electricity after Linde/ASU", "MWh/y", "", "", totals["process_electricity_after_Linde_ASU_MWh_e_y"], "reporting_only", "current_C5_scope_not_full_site", "C5p_a", "C5p_a", "Not full-site electricity boundary."),
            ("diagnostic_co2_total", "site", "diagnostic CO2 after Linde/ASU", "t/y", "", "", totals["diagnostic_CO2_after_Linde_ASU_t_y"], "reporting_only", "current_C5_diagnostic_scope_not_ETS", "C5p_a", "C5p_a", "Not ETS/full-site emissions; ASU direct CO2 not added."),
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
            "why_current_choice_exists": "C5 has downstream losses/imported slab and DSP/HSM outputs, but no final product sales/economics layer and remaining utility/interface layers are incomplete.",
            "model_impact": "EUR/t results can change materially depending on denominator.",
            "affects_physical_behaviour": "false",
            "affects_economics_later": "true",
            "sensitivity_required": "yes",
            "freeze_before_DA": "yes",
            "recommended_action": "Do not choose yet; keep unresolved until C5p_a Linde/ASU is reviewed and boiler/steam plus generator/interface layers are implemented.",
            "caveat": "Linde/ASU is now accounting-only; product revenue remains blocked.",
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
    c0_steam = f"BF steam proxy and KGF steam proxy available in C5m_b; Sinter steam proxy {_fmt(_key(payload['sinter_utility'], C0)['steam_demand_site_t_y'])} t/y"
    c1_steam = f"BF/KGF steam proxy available in C5m_b; Sinter steam proxy {_fmt(_key(payload['sinter_utility'], C1)['steam_demand_site_t_y'])} t/y; EAF steam recovery reporting-only"
    c0_elec = _fmt(_key(payload["dsp_totals"], C0)["process_electricity_after_DSP_MWh_e_y"])
    c1_elec = _fmt(_key(payload["dsp_totals"], C1)["process_electricity_after_DSP_MWh_e_y"])
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
            "current_supply_available": "Sinter proxy supply; WAG boiler/interface placeholders in WAG ledger",
            "missing_assets": "physical boilers, steam bus, steam supply/demand balance, boiler NG backup, steam emissions",
            "current_status": "partial_proxy_only",
            "blocker_for_physical_model": "medium: steam proxies avoid silence but no utility closure",
            "blocker_for_economics": "high: WAG/NG boiler economics cannot be claimed",
            "recommended_stage": "C5p_b_boiler_steam_proxy_hardening",
            "risk_if_postponed": "WAG residuals and steam demands cannot be valued or balanced physically.",
            "caveat": "No artificial internal steam price.",
        },
        {
            "utility_area": "Vattenfall_IJ01_VN25_generators",
            "current_demands_available": "WAG carrier residual/interface rows exist by BFG/COG/BOFG",
            "current_supply_available": "no generator dispatch, efficiency, electricity output or site import/export balance",
            "missing_assets": "generator links, electricity output, fuel eligibility, heat/power split, import/export boundary",
            "current_status": "interface_placeholder_only",
            "blocker_for_physical_model": "medium",
            "blocker_for_economics": "high",
            "recommended_stage": "C5p_c_generator_interface_boundary",
            "risk_if_postponed": "Full-site electricity and WAG opportunity-cost claims remain unsupported.",
            "caveat": "No WAG export revenue or direct WAG market valuation.",
        },
        {
            "utility_area": "residual_electricity",
            "current_demands_available": f"Current modelled process electricity after DSP: C0 {c0_elec} MWh/y; C1 {c1_elec} MWh/y",
            "current_supply_available": "none; not a full-site import/export convention",
            "missing_assets": "fixed/background loads, site import/export boundary, onsite generation offsets, grid capacity",
            "current_status": "process_scope_only",
            "blocker_for_physical_model": "low for plant-ledger C5; high for full site",
            "blocker_for_economics": "high",
            "recommended_stage": "after_Linde_boilers_generators_boundary",
            "risk_if_postponed": "DA economics would price only modelled process loads and may be mistaken for full-site cost.",
            "caveat": "Label as current_C5_scope, not full_site_electricity.",
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
        "This is a diagnostic-only review of the current C5 plant-layer artifacts after KGF/BF/BOF/HSM/WBW/Sinter/PEFA/pellet burden/DRP/EAF/DSP. It does not change model equations, parameters, targets, route shares, coefficients, utility layers, or economics.",
        "",
        "The model remains a public Tata Steel IJmuiden-inspired development model. It is not a confidential digital twin and not thesis-approved.",
        "",
        "## Current C5 Coverage Summary",
        "",
        "- Active C0/C1 liquid-steel target remains 6.75 Mt/y.",
        "- C5l_d `base_0_50` remains the default HSM/WBW heat case.",
        "- PEFA, pellet burden, DRP, EAF, DSP and Linde/ASU oxygen are represented as development-only accounting/physical layers with compact healthchecks.",
        "- Linde/ASU oxygen now adds current-C5 process electricity accounting, but WAG, CO2 and steam remain diagnostic or partial utility layers, not economic objective layers.",
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
        "- The denominator remains unresolved after C5p_a because boiler/steam and generator/interface layers are still incomplete. Product revenue remains blocked.",
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
        "- The red flags before economics are denominator ambiguity, C1 DSP route-origin opacity, missing governed scrap loop, DRP oxygen-basis review, boiler/steam proxy status, generator/interface absence, residual electricity/NG boundary absence, and diagnostic-only CO2.",
        "",
        "## Recommended Next Decisions",
        "",
        "1. Freeze denominator policy for future EUR/t reporting: liquid-steel equivalent versus current final-product proxy versus revised downstream target.",
        "2. Decide whether C1 DSP route-origin tagging is required before thesis route-share claims.",
        "3. Keep C5p_a Linde/ASU as oxygen accounting only until DRP oxygen basis is reviewed and remaining utility boundaries are scoped.",
        "4. Defer economics until boiler/steam, generator/interface and residual electricity/NG boundaries are explicitly scoped.",
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
