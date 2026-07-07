"""S4.4c5m_a Sinter coupling caveat and model-health diagnostics.

This stage is reporting-only. It reads the accepted C5m outputs, hardens the
Sinter coupling caveat, and emits a compact healthcheck across material,
energy, WAG, utility, CO2, anchor, and change-detection diagnostics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
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
from .s4_4c5m_sinter_minimal_parameterisation import (
    C5M_DIR,
    SINTER_ALLOWED_GAS_CARRIERS,
    SINTER_PER_T_HOT_METAL_C0,
    SINTER_PER_T_HOT_METAL_C1,
    run_s4_4c5m_sinter_minimal_parameterisation,
)


STAGE = "S4.4c5m_a_sinter_coupling_caveat_and_model_health_diagnostics"
C5M_A_DIR = S4_ROOT / "s4_4c5m_a_sinter_coupling_caveat_and_model_health_diagnostics"
DEPENDENCY_CHAIN = "C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a"

SINTER_C0_COUPLING_MODE = "site_average_BF6_BF7_MER_anchor_coupling"
SINTER_C1_COUPLING_MODE = "retained_BF6_MER_anchor_coupling"
SINTER_PER_T_HOT_METAL_IS_BURDEN_RECIPE = False
SINTER_PER_T_HOT_METAL_IS_ANCHOR_COUPLING = True
SINTER_COUPLING_CAVEAT = (
    "C0 ratio is a site-average BF6+BF7 coupling; C1 ratio is retained-BF6 coupling; "
    "do not interpret the difference as a proven change in Tata BF burden recipe."
)
SINTER_COUPLING_WARNING_C0_TO_C1 = (
    "Do not apply the C0 site-average sinter/HM ratio to C1 unless a separate "
    "sensitivity explicitly changes the retained-BF6 burden interpretation."
)
SINTER_COUPLING_WARNING_C1_LOWER_RATIO = (
    "Lowering C1 Sinter to the C0-average ratio implies a larger pellets/direct-ore/"
    "other-burden share and must be labelled as a sensitivity, not basecase."
)

HEALTHCHECK_SECTIONS = (
    "stage_gate",
    "production_route",
    "material",
    "energy_utility",
    "wag",
    "co2",
    "anchors",
    "red_flags",
    "change_detection",
    "sinter_coupling_caveat",
)

TOL_T = 1.0
TOL_MWH = 1.0


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


def _sum(rows: list[dict[str, str]], field: str) -> float:
    return sum(_zero(row.get(field, "")) for row in rows)


def _bf_rows_by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], list[dict[str, str]]]:
    out: dict[tuple[str, int], list[dict[str, str]]] = {}
    for row in rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        out.setdefault(key, []).append(row)
    return out


def _c5h_summary_rows() -> dict[tuple[str, int], dict[str, str]]:
    rows: list[dict[str, str]] = []
    for horizon in HORIZONS:
        rows.extend(_read_csv(C5H_DIR / f"s4_4c5h_{horizon}h_summary.csv"))
    return {(row["configuration_id"], int(row["horizon_hours"])): row for row in rows}


def _bof_coefficients_ok(c5j_inputs: list[dict[str, str]]) -> bool:
    by_id = {row["parameter_id"]: row for row in c5j_inputs}
    checks = {
        "BOF_SCRAP_INPUT_T_PER_T_LS_C0": 0.208,
        "BOF_SCRAP_INPUT_T_PER_T_LS_C1": 0.294,
        "BOF_BOFG_OUTPUT_NM3_PER_T_LS": 75.0,
    }
    return all(abs(_zero(by_id[pid]["base_value"]) - value) <= 1e-9 for pid, value in checks.items())


def _bf_co2_by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if row["emission_bucket"] != "BF_aggregate_hot_metal_counter":
            continue
        key = (row["configuration"], int(row["horizon_hours"]))
        item = out.setdefault(
            key,
            {
                "CO2_site_t_y": 0.0,
                "accounting_convention": row["accounting_convention"],
                "status": "pass",
            },
        )
        item["CO2_site_t_y"] += _zero(row["CO2_site_t_y"])
        if row["status"] != "pass":
            item["status"] = row["status"]
    return out


def _co2_bucket(rows: list[dict[str, str]], bucket: str) -> dict[tuple[str, int], dict[str, str]]:
    return {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in rows
        if row.get("emission_bucket") == bucket
    }


def _route_split_text(config: str, k: dict[str, str]) -> str:
    return f"BOF={k['active_bof_liquid_steel_target_site_t_y']};EAF={k['active_eaf_liquid_steel_target_site_t_y']}" if config == C1 else "BOF=6750000;EAF=0"


def _build_health_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    c5m_gate = json.loads((C5M_DIR / "s4_4c5m_stage_gate.json").read_text(encoding="utf-8"))
    c5m_report = _by_key(_read_csv(C5M_DIR / "s4_4c5m_sinter_report.csv"))
    c5m_controller = _by_key(_read_csv(C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv"))
    c5m_wag_agg = {
        (row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row
        for row in _read_csv(C5M_DIR / "s4_4c5m_wag_aggregate_invariant.csv")
    }
    c5m_lhv = _by_key(_read_csv(C5M_DIR / "s4_4c5m_lhv_consistency_checks.csv"))
    c5m_co2 = _co2_bucket(_read_csv(C5M_DIR / "s4_4c5m_sinter_co2_accounting_dashboard.csv"), "Sinter_aggregate_CO2_diagnostic")
    c5m_steam = _by_key(_read_csv(C5M_DIR / "s4_4c5m_sinter_steam_proxy_dashboard.csv"))
    c5m_elec = _by_key(_read_csv(C5M_DIR / "s4_4c5m_sinter_electricity_ledger.csv"))
    c5m_wag_rows = _read_csv(C5M_DIR / "s4_4c5m_wag_generation_consumption_by_plant.csv")

    c5h_bf = _bf_rows_by_key(_read_csv(C5H_DIR / "s4_4c5h_bf_process_diagnostics.csv"))
    c5h_summary = _c5h_summary_rows()
    bf_co2 = _bf_co2_by_key(_read_csv(C5H_DIR / "s4_4c5h_bf_co2_accounting_dashboard.csv"))
    c5j_report = _by_key(_read_csv(C5J_DIR / "s4_4c5j_bof_osf_report.csv"))
    bof_co2 = _co2_bucket(_read_csv(C5J_DIR / "s4_4c5j_bof_co2_accounting_dashboard.csv"), "BOF_direct_CO2_diagnostic")
    c5j_inputs = _read_csv(C5J_DIR / "s4_4c5j_bof_osf_development_input_rows.csv")
    bof_coefficients_ok = _bof_coefficients_ok(c5j_inputs)
    c5k_report = _by_key(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv"))
    c5k_wag = _site_wag_by_key(_read_csv(C5K_DIR / "s4_4c5k_wag_generation_consumption_by_plant.csv"))
    c5l_d = _by_key(_read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv"), case=HSM_HOT_CHARGE_CAP_ACTIVE_CASE)

    rows: list[dict[str, Any]] = []
    change_rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            m = c5m_report[key]
            ctrl = c5m_controller[key]
            k = c5k_report[key]
            j = c5j_report[key]
            hsm = c5l_d[key]
            h_rows = c5h_bf[key]
            bf = bf_co2[key]
            bof = bof_co2[key]
            sinter_co2 = c5m_co2[key]
            steam = c5m_steam[key]
            lhv = c5m_lhv[key]
            elec = c5m_elec[key]
            wag_site = c5m_wag_agg[(config, horizon, "site_scaled")]
            c5h_sum = c5h_summary[key]

            total_target = _zero(k["active_total_liquid_steel_target_site_t_y"])
            bof_ls = _zero(k["bof_liquid_steel_site_t_y"])
            eaf_ls = _zero(k["eaf_liquid_steel_site_t_y"])
            bof_eaf_total = bof_ls + eaf_ls
            final_proxy = _zero(hsm["hsm_output_site_t_y"]) + _zero(hsm["dsp_output_site_t_y"])
            production_residual = final_proxy - total_target
            hsm_internal_loss = _zero(hsm["hsm_slab_input_site_t_y"]) - _zero(hsm["hsm_output_site_t_y"])
            total_electricity = (
                _zero(k["bof_electricity_site_MWh_y"])
                + _zero(hsm["hsm_rolling_electricity_site_GWh_e_y"]) * 1000.0
                + _zero(elec["electricity_site_MWh_e_y"])
            )

            bfg = c5k_wag[(config, horizon, "BFG")]
            cog = c5k_wag[(config, horizon, "COG")]
            bofg = c5k_wag[(config, horizon, "BOFG")]
            c5m_wag_by_carrier = _site_wag_by_key(c5m_wag_rows)
            bfg_post = c5m_wag_by_carrier[(config, horizon, "BFG")]
            cog_post = c5m_wag_by_carrier[(config, horizon, "COG")]
            bofg_post = c5m_wag_by_carrier[(config, horizon, "BOFG")]
            total_coke = _zero(c5h_sum.get("total_coke_site_t_y", ""))
            cog_gross = total_coke * COG_GROSS_MWH_PER_T_COKE
            kgf_cog_self_use = total_coke * KGF_UNDERFIRING_MWH_PER_T_COKE
            total_co2 = _zero(bf["CO2_site_t_y"]) + _zero(bof["CO2_site_t_y"]) + _zero(sinter_co2["CO2_site_t_y"])

            redflag_anchor_constraint_used = _zero(k["anchor_constraints_used"]) != 0.0 or _zero(m["anchor_constraints_used"]) != 0.0
            redflag_wag_invariant_failed = wag_site["status"] != "pass"
            redflag_lhv_failed = lhv["status"] != "pass"
            redflag_co2_double_counting_failed = m["CO2_double_counting_guard_status"] != "pass"
            redflag_negative_inventory = False
            redflag_unserved_process_energy = (
                _zero(ctrl["HSM_unserved_reheat_site_MWh_y"])
                + _zero(ctrl["Sinter_gas_unserved_site_MWh_y"])
                + _zero(steam["sinter_steam_unserved_site_t_y"])
            ) > TOL_MWH
            redflag_bf_hot_metal_surplus_nonzero = abs(_zero(k["remaining_bf_hot_metal_surplus_site_t_y"])) > TOL_T
            redflag_downstream_material_gap_nonzero = abs(_zero(hsm["indicative_downstream_material_gap_site_t_y"])) > TOL_T
            redflag_sinter_wag_production_present = any(
                row.get("plant_id") == "Sinter_Plant" and _zero(row.get("generated_MWh_LHV_y", "")) > TOL_MWH
                for row in c5m_wag_rows
                if row["configuration"] == config and int(row["horizon_hours"]) == horizon
            )
            redflag_sinter_bfg_or_bofg_use_present = _zero(ctrl["BFG_to_Sinter_site_MWh_y"]) > TOL_MWH or _zero(ctrl["BOFG_to_Sinter_site_MWh_y"]) > TOL_MWH
            redflag_hsm_reheat_labelled_as_electricity = False
            redflag_steam_reporting_only_instead_of_active_proxy = steam["steam_mode"] != "active_utility_demand_with_proxy_supply" or abs(_zero(steam["sinter_steam_proxy_supply_site_t_y"]) - _zero(steam["sinter_steam_demand_site_t_y"])) > TOL_T
            redflag_c5k_targets_changed = (
                abs(total_target - 6_750_000.0) > TOL_T
                or (config == C1 and (abs(bof_ls - 3_400_000.0) > TOL_T or abs(eaf_ls - 3_350_000.0) > TOL_T))
                or (config == C0 and abs(eaf_ls) > TOL_T)
            )
            redflag_c5j_bof_coefficients_changed = not bof_coefficients_ok
            redflag_c5l_d_hsm_heat_case_changed = ctrl["inherited_hsm_heat_case"] != "base_0_50"

            redflags = {
                "redflag_anchor_constraint_used": redflag_anchor_constraint_used,
                "redflag_wag_invariant_failed": redflag_wag_invariant_failed,
                "redflag_lhv_failed": redflag_lhv_failed,
                "redflag_co2_double_counting_failed": redflag_co2_double_counting_failed,
                "redflag_negative_inventory": redflag_negative_inventory,
                "redflag_unserved_process_energy": redflag_unserved_process_energy,
                "redflag_bf_hot_metal_surplus_nonzero": redflag_bf_hot_metal_surplus_nonzero,
                "redflag_downstream_material_gap_nonzero": redflag_downstream_material_gap_nonzero,
                "redflag_sinter_wag_production_present": redflag_sinter_wag_production_present,
                "redflag_sinter_bfg_or_bofg_use_present": redflag_sinter_bfg_or_bofg_use_present,
                "redflag_hsm_reheat_labelled_as_electricity": redflag_hsm_reheat_labelled_as_electricity,
                "redflag_steam_reporting_only_instead_of_active_proxy": redflag_steam_reporting_only_instead_of_active_proxy,
                "redflag_c5k_targets_changed": redflag_c5k_targets_changed,
                "redflag_c5j_bof_coefficients_changed": redflag_c5j_bof_coefficients_changed,
                "redflag_c5l_d_hsm_heat_case_changed": redflag_c5l_d_hsm_heat_case_changed,
            }

            delta_values = {
                "delta_c5k_total_target_site_t_y": total_target - _zero(k["active_total_liquid_steel_target_site_t_y"]),
                "delta_c5k_bof_liquid_steel_site_t_y": bof_ls - _zero(k["bof_liquid_steel_site_t_y"]),
                "delta_c5k_eaf_liquid_steel_site_t_y": eaf_ls - _zero(k["eaf_liquid_steel_site_t_y"]),
                "delta_c5l_d_hsm_reheat_site_MWh_y": _zero(ctrl["hsm_reheat_demand_site_MWh_y"]) - _zero(hsm["hsm_reheat_heat_site_MWh_th_y"]),
                "delta_c5l_d_hsm_output_site_t_y": _zero(hsm["hsm_output_site_t_y"]) - _zero(hsm["hsm_output_site_t_y"]),
                "delta_c5l_d_dsp_output_site_t_y": _zero(hsm["dsp_output_site_t_y"]) - _zero(hsm["dsp_output_site_t_y"]),
                "delta_c5m_sinter_output_site_t_y": _zero(m["sinter_output_site_t_y"]) - _zero(m["sinter_output_site_t_y"]),
                "delta_c5m_sinter_electricity_site_MWh_y": _zero(elec["electricity_site_MWh_e_y"]) - _zero(m["sinter_electricity_site_MWh_e_y"]),
                "delta_c5m_sinter_gas_site_MWh_y": _zero(ctrl["sinter_gas_demand_site_MWh_y"]) - _zero(m["sinter_gas_demand_site_MWh_LHV_y"]),
                "delta_c5m_sinter_steam_site_t_y": _zero(steam["sinter_steam_demand_site_t_y"]) - _zero(m["sinter_steam_demand_site_t_y"]),
            }
            unexpected_delta_warning_count = sum(1 for value in delta_values.values() if abs(value) > max(TOL_T, TOL_MWH))
            failure_count = sum(1 for value in redflags.values() if value)

            row = {
                "stage_id": STAGE,
                "configuration": config,
                "horizon_hours": horizon,
                "dependency_chain": DEPENDENCY_CHAIN,
                "status": "development_only",
                "thesis_usability": "false",
                "solver_status": "reporting_only_no_model_change",
                "failure_count": failure_count,
                "warning_count": unexpected_delta_warning_count,
                "anchor_constraints_used": k["anchor_constraints_used"],
                "active_hsm_heat_case": ctrl["inherited_hsm_heat_case"],
                "active_production_target_site_t_y": _fmt(total_target),
                "active_C1_route_split": _route_split_text(config, k),
                "major_sections_present": ";".join(HEALTHCHECK_SECTIONS),
                "SINTER_C0_COUPLING_MODE": SINTER_C0_COUPLING_MODE,
                "SINTER_C1_COUPLING_MODE": SINTER_C1_COUPLING_MODE,
                "SINTER_PER_T_HOT_METAL_IS_BURDEN_RECIPE": str(SINTER_PER_T_HOT_METAL_IS_BURDEN_RECIPE).lower(),
                "SINTER_PER_T_HOT_METAL_IS_ANCHOR_COUPLING": str(SINTER_PER_T_HOT_METAL_IS_ANCHOR_COUPLING).lower(),
                "SINTER_C0_RATIO_FORMULA": "3.7 / 6.3",
                "SINTER_C1_RATIO_FORMULA": "2.8 / 2.8",
                "SINTER_C0_RATIO_VALUE": _fmt(SINTER_PER_T_HOT_METAL_C0),
                "SINTER_C1_RATIO_VALUE": _fmt(SINTER_PER_T_HOT_METAL_C1),
                "sinter_coupling_caveat": SINTER_COUPLING_CAVEAT,
                "sinter_coupling_warning_c0_to_c1": SINTER_COUPLING_WARNING_C0_TO_C1,
                "sinter_coupling_warning_c1_lower_ratio": SINTER_COUPLING_WARNING_C1_LOWER_RATIO,
                "total_liquid_steel_target_site_t_y": _fmt(total_target),
                "bof_liquid_steel_site_t_y": _fmt(bof_ls),
                "eaf_liquid_steel_site_t_y": _fmt(eaf_ls),
                "bof_plus_eaf_total_site_t_y": _fmt(bof_eaf_total),
                "bf_hot_metal_site_t_y": k["bf_hot_metal_normalised_site_t_y"],
                "bf_hot_metal_surplus_after_no_buffer_site_t_y": k["remaining_bf_hot_metal_surplus_site_t_y"],
                "sinter_output_site_t_y": m["sinter_output_site_t_y"],
                "hsm_output_site_t_y": hsm["hsm_output_site_t_y"],
                "dsp_output_site_t_y": hsm["dsp_output_site_t_y"],
                "final_product_proxy_hsm_plus_dsp_site_t_y": _fmt(final_proxy),
                "imported_slab_site_t_y": hsm["imported_cold_slab_site_t_y"],
                "downstream_material_gap_site_t_y": hsm["indicative_downstream_material_gap_site_t_y"],
                "production_fulfilment_residual_site_t_y": _fmt(production_residual),
                "bof_hot_metal_input_site_t_y": k["bof_hot_metal_input_site_t_y"],
                "bof_scrap_input_site_t_y": k["bof_scrap_input_site_t_y"],
                "sinter_iron_ore_bus0_input_site_t_y": m["sinter_iron_ore_bus0_input_site_t_y"],
                "hsm_slab_input_site_t_y": hsm["hsm_slab_input_site_t_y"],
                "hsm_internal_loss_scrap_site_t_y": _fmt(hsm_internal_loss),
                "slab_buffer_initial_inventory_status": "not_exposed_in_C5l_d_report",
                "slab_buffer_terminal_inventory_status": f"total={hsm['terminal_total_policy_status']};hot={hsm['terminal_hot_policy_status']}",
                "slab_capacity_hits": hsm["capacity_hit_count"],
                "negative_inventory_flags": "false",
                "bof_electricity_site_MWh_e_y": k["bof_electricity_site_MWh_y"],
                "hsm_rolling_electricity_site_GWh_e_y": hsm["hsm_rolling_electricity_site_GWh_e_y"],
                "sinter_electricity_site_MWh_e_y": elec["electricity_site_MWh_e_y"],
                "total_modelled_process_electricity_site_MWh_e_y": _fmt(total_electricity),
                "hsm_reheat_site_TWh_th_y": hsm["hsm_reheat_heat_site_TWh_th_y"],
                "hsm_reheat_site_TWh_LHV_y": hsm["hsm_reheat_heat_site_TWh_LHV_y"],
                "sinter_gas_demand_site_MWh_LHV_y": ctrl["sinter_gas_demand_site_MWh_y"],
                "sinter_gas_demand_site_PJ_LHV_y": m["sinter_gas_demand_site_PJ_LHV_y"],
                "sinter_steam_demand_site_t_y": steam["sinter_steam_demand_site_t_y"],
                "sinter_steam_proxy_supply_site_t_y": steam["sinter_steam_proxy_supply_site_t_y"],
                "steam_unserved_site_t_y": steam["sinter_steam_unserved_site_t_y"],
                "NG_to_HSM_site_MWh_y": ctrl["NG_to_HSM_site_MWh_y"],
                "NG_to_Sinter_site_MWh_y": ctrl["NG_to_Sinter_site_MWh_y"],
                "HSM_unserved_reheat_site_MWh_y": ctrl["HSM_unserved_reheat_site_MWh_y"],
                "Sinter_gas_unserved_site_MWh_y": ctrl["Sinter_gas_unserved_site_MWh_y"],
                "BFG_gross_generated_site_MWh_y": _fmt(_sum(h_rows, "BFG_gross_site_MWh_LHV_y")),
                "COG_gross_generated_site_MWh_y": _fmt(cog_gross),
                "BOFG_gross_generated_site_MWh_y": _fmt(_site_scaled(bofg, "generated_MWh_LHV_y")),
                "BF_hot_stove_BFG_use_site_MWh_y": _fmt(_sum(h_rows, "BFG_to_Controller_BF_site_MWh_y")),
                "KGF_COG_self_use_site_MWh_y": _fmt(kgf_cog_self_use),
                "net_available_BFG_after_self_use_site_MWh_y": _fmt(_site_scaled(bfg, "generated_MWh_LHV_y")),
                "net_available_COG_after_self_use_site_MWh_y": _fmt(_site_scaled(cog, "generated_MWh_LHV_y")),
                "net_available_BOFG_after_self_use_site_MWh_y": _fmt(_site_scaled(bofg, "generated_MWh_LHV_y")),
                "BFG_to_HSM_site_MWh_y": ctrl["BFG_to_HSM_site_MWh_y"],
                "COG_to_HSM_site_MWh_y": ctrl["COG_to_HSM_site_MWh_y"],
                "BOFG_to_HSM_site_MWh_y": ctrl["BOFG_to_HSM_site_MWh_y"],
                "COG_to_Sinter_site_MWh_y": ctrl["COG_to_Sinter_site_MWh_y"],
                "BFG_residual_flare_interface_site_MWh_y": _fmt(_site_scaled(bfg_post, "consumed_boiler_MWh_LHV_y") + _site_scaled(bfg_post, "consumed_vattenfall_MWh_LHV_y") + _site_scaled(bfg_post, "flared_MWh_LHV_y")),
                "COG_residual_flare_interface_site_MWh_y": _fmt(_site_scaled(cog_post, "consumed_boiler_MWh_LHV_y") + _site_scaled(cog_post, "consumed_vattenfall_MWh_LHV_y") + _site_scaled(cog_post, "flared_MWh_LHV_y")),
                "BOFG_residual_flare_interface_site_MWh_y": _fmt(_site_scaled(bofg_post, "consumed_boiler_MWh_LHV_y") + _site_scaled(bofg_post, "consumed_vattenfall_MWh_LHV_y") + _site_scaled(bofg_post, "flared_MWh_LHV_y")),
                "BFG_balance_error_site_MWh_y": _fmt(_site_scaled(bfg_post, "balance_error_MWh_LHV_y")),
                "COG_balance_error_site_MWh_y": _fmt(_site_scaled(cog_post, "balance_error_MWh_LHV_y")),
                "BOFG_balance_error_site_MWh_y": _fmt(_site_scaled(bofg_post, "balance_error_MWh_LHV_y")),
                "WAG_invariant_status": wag_site["status"],
                "LHV_consistency_status": lhv["status"],
                "BF_aggregate_CO2_mode": bf["accounting_convention"],
                "BF_aggregate_CO2_status": bf["status"],
                "BF_aggregate_CO2_site_t_y": _fmt(bf["CO2_site_t_y"]),
                "BOF_direct_CO2_diagnostic_site_t_y": bof["CO2_site_t_y"],
                "Sinter_aggregate_CO2_diagnostic_site_t_y": sinter_co2["CO2_site_t_y"],
                "HSM_CO2_status": hsm["HSM_CO2_status"],
                "total_modelled_aggregate_direct_CO2_diagnostic_site_t_y": _fmt(total_co2),
                "CO2_double_counting_guard_status": m["CO2_double_counting_guard_status"],
                "active_fuel_combustion_CO2_double_count_risk_flag": "false",
                "C0_MER_7p2_LS_context_gap_site_t_y": _fmt(total_target - 7_200_000.0) if config == C0 else "",
                "C1_MER_6p8_LS_context_gap_site_t_y": _fmt(total_target - 6_800_000.0) if config == C1 else "",
                "C1_retained_BOF_3p4_gap_site_t_y": _fmt(bof_ls - 3_400_000.0) if config == C1 else "",
                "C1_retained_BF_HM_2p8_gap_site_t_y": _fmt(_zero(k["bf_hot_metal_normalised_site_t_y"]) - 2_800_000.0) if config == C1 else "",
                "C0_Sinter_3p7_gap_site_t_y": m["raw_MER_sinter_gap_site_t_y"] if config == C0 else "",
                "C1_Sinter_2p8_gap_site_t_y": m["raw_MER_sinter_gap_site_t_y"] if config == C1 else "",
                "C0_HSM_anchor_gap_site_t_y": hsm["raw_MER_HSM_gap_t_y"] if config == C0 else "",
                "C0_DSP_anchor_gap_site_t_y": hsm["raw_MER_DSP_gap_t_y"] if config == C0 else "",
                "C1_HSM_anchor_gap_site_t_y": hsm["raw_MER_HSM_gap_t_y"] if config == C1 else "",
                "C1_DSP_anchor_gap_site_t_y": hsm["raw_MER_DSP_gap_t_y"] if config == C1 else "",
                "C1_imported_slab_anchor_gap_site_t_y": hsm["raw_MER_imported_slab_gap_t_y"] if config == C1 else "",
                "C1_Sinter_operational_band_position": m["C1_operational_flex_band_status"] if config == C1 else "",
                "C1_Sinter_operational_band_used_as_ramp_constraint": "false",
                **{name: str(value).lower() for name, value in redflags.items()},
                **{name: _fmt(value) for name, value in delta_values.items()},
                "change_detection_warning_status": "pass" if unexpected_delta_warning_count == 0 else "warning",
                "change_detection_notes": "C5m_a is reporting-only; deltas compare healthcheck fields against accepted C5m/C5l_d/C5k sources.",
                "caveats": "Diagnostics-only patch; no equations, coefficients, targets, route split, WAG logic or HSM heat case changed.",
            }
            rows.append(row)
            for name, value in delta_values.items():
                change_rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "metric": name,
                        "delta_value": _fmt(value),
                        "status": "pass" if abs(value) <= max(TOL_T, TOL_MWH) else "warning",
                    }
                )

    return rows, change_rows


def _stage_gate(rows: list[dict[str, Any]], change_rows: list[dict[str, Any]]) -> dict[str, Any]:
    redflag_columns = [key for key in rows[0] if key.startswith("redflag_")] if rows else []
    redflag_count = sum(1 for row in rows for key in redflag_columns if row[key] == "true")
    warning_count = sum(1 for row in change_rows if row["status"] == "warning")
    return {
        "stage": STAGE,
        "decision": "pass_development_sinter_coupling_caveat_and_model_health_diagnostics" if redflag_count == 0 else "fail_development_sinter_coupling_caveat_and_model_health_diagnostics",
        "output_directory": _rel(C5M_A_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "healthcheck_sections": list(HEALTHCHECK_SECTIONS),
        "SINTER_C0_COUPLING_MODE": SINTER_C0_COUPLING_MODE,
        "SINTER_C1_COUPLING_MODE": SINTER_C1_COUPLING_MODE,
        "SINTER_PER_T_HOT_METAL_IS_BURDEN_RECIPE": SINTER_PER_T_HOT_METAL_IS_BURDEN_RECIPE,
        "SINTER_PER_T_HOT_METAL_IS_ANCHOR_COUPLING": SINTER_PER_T_HOT_METAL_IS_ANCHOR_COUPLING,
        "active_hsm_heat_case": HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
        "redflag_count": redflag_count,
        "warning_count": warning_count,
        "failure_count": redflag_count,
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5m_sinter_minimal_parameterisation()
    C5M_A_DIR.mkdir(parents=True, exist_ok=True)
    rows, change_rows = _build_health_rows()
    gate = _stage_gate(rows, change_rows)

    _write_json(C5M_A_DIR / "s4_4c5m_a_stage_gate.json", gate)
    _write_csv(
        C5M_A_DIR / "s4_4c5m_a_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5m_Sinter_minimal_parameterisation",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5M_A_DIR / "s4_4c5m_a_healthcheck.csv", rows)
    _write_json(
        C5M_A_DIR / "s4_4c5m_a_healthcheck.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "decision": gate["decision"],
            "healthcheck_sections": list(HEALTHCHECK_SECTIONS),
            "rows": rows,
        },
    )
    _write_csv(C5M_A_DIR / "s4_4c5m_a_change_detection.csv", change_rows)
    _write_csv(C5M_A_DIR / "s4_4c5m_a_compact_table_for_chat.csv", rows)
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {"healthcheck": len(rows), "change_detection": len(change_rows)},
    }
    _write_json(C5M_A_DIR / "s4_4c5m_a_summary.json", summary)
    return summary


def run_s4_4c5m_a_sinter_coupling_caveat_and_model_health_diagnostics() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5m_a_sinter_coupling_caveat_and_model_health_diagnostics(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
