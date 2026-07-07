"""S4.4c5p_a Linde/ASU oxygen accounting layer.

This development-only stage aggregates current C5 process oxygen demand,
adds compact Linde/ASU electricity accounting, and reports oxygen-buffer
policy diagnostics. It does not add ASU flexibility, mFRR, liquid oxygen
dispatch, nitrogen, argon, dry air, product revenue, or economics.
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
from .s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch import C5L_D_DIR
from .s4_4c5o_a_ng_drp_physical_layer_with_dri_interface import C5O_A_DIR
from .s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff import C5O_B_DIR
from .s4_4c5o_c_dsp_downstream_physical_layer import (
    C5O_C_DIR,
    run_s4_4c5o_c_dsp_downstream_physical_layer,
)


STAGE = "S4.4c5p_a_linde_asu_oxygen_accounting"
C5P_A_DIR = S4_ROOT / "s4_4c5p_a_linde_asu_oxygen_accounting"
SOURCE_CARD = "data/03_Optimisation/inputs/assets/steel/source_cards/LINDE_OXYGEN_Parameters.md"
DEPENDENCY_CHAIN = (
    "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b "
    "-> C5m_c -> C5m_d -> C5m_e -> C5m_f -> C5n_a -> C5n_b -> C5o_a "
    "-> C5o_b -> C5o_c -> C5p_a"
)
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_healthcheck_pattern;"
    "Linde_values_loaded_from_C5p_a_development_input_rows;"
    "oxygen_demand_aggregated_from_existing_BF_BOF_EAF_DRP_ledgers;"
    "ASU_electricity_added_to_current_C5_process_electricity_scope;"
    "oxygen_buffer_reporting_only_not_strategic_storage"
)

TOL = 1e-6


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _bool(value: bool) -> str:
    return str(value).lower()


def _by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _base_c5l_d_rows(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in rows
        if row.get("cap_case") == "base_0_50"
    }


def _param_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["parameter_id"]: row for row in rows}


def _param_float(params: dict[str, dict[str, Any]], parameter_id: str) -> float:
    return _zero(params[parameter_id]["base_value"])


def _param_text(params: dict[str, dict[str, Any]], parameter_id: str) -> str:
    return str(params[parameter_id]["base_value"])


def _dev_row(
    parameter_id: str,
    base_value: Any,
    unit: str,
    parameter_group: str,
    caveat: str,
    *,
    low_value: Any = "",
    high_value: Any = "",
    input_status: str = "development_candidate",
    evidence_strength: str = "source_card_candidate_not_Tata_validated",
) -> dict[str, Any]:
    return {
        "parameter_id": parameter_id,
        "base_value": base_value,
        "low_value": low_value,
        "high_value": high_value,
        "unit": unit,
        "parameter_group": parameter_group,
        "source_card": SOURCE_CARD,
        "input_status": input_status,
        "thesis_usability": "false",
        "human_review_required": "true",
        "codex_may_decide": "false",
        "evidence_strength": evidence_strength,
        "caveat": caveat,
    }


def _linde_dev_rows() -> list[dict[str, Any]]:
    return [
        _dev_row("LINDE_ASU_OUTPUT_BASIS", "gaseous oxygen delivered to site oxygen network", "-", "topology", "O2 is active; other air gases are deferred.", input_status="development_assumption"),
        _dev_row("LINDE_PRODUCTS_SCOPE", "O2 active; Ar/N2/compressed dry air deferred", "carrier_scope", "topology", "No N2, Ar or dry-air carrier is active in C5p_a.", input_status="development_assumption"),
        _dev_row("LINDE_O2_PRODUCED_AT_IJMUIDEN", "true", "boolean", "topology", "Source-backed topology context, not full Linde digital twin.", input_status="development_assumption"),
        _dev_row("LINDE_ASU_ELECTRICITY_MWH_PER_T_O2_GAS_BASE", 0.400, "MWh/t O2", "electricity", "Gaseous oxygen benchmark; development-only ASU electricity coefficient."),
        _dev_row("LINDE_ASU_ELECTRICITY_MWH_PER_T_O2_LIQUID", 0.638, "MWh/t O2", "sensitivity", "Liquid oxygen check only; not normal dispatch supply.", input_status="development_diagnostic"),
        _dev_row("LINDE_ASU_ELECTRICITY_KWH_PER_NM3_O2_GAS_BASE", 0.572, "kWh/Nm3 O2", "derived_conversion", "Derived from 0.400 MWh/t and 1.429 kg/Nm3.", input_status="development_diagnostic"),
        _dev_row("LINDE_O2_DENSITY_KG_PER_NM3", 1.429, "kg/Nm3", "unit_conversion", "Use for conversion only; avoid double counting mass and volume oxygen rows."),
        _dev_row("LINDE_O2_NM3_PER_T_O2", 699.8, "Nm3/t O2", "unit_conversion", "1000 / 1.429 rounded; used for reporting checks."),
        _dev_row("LINDE_O2_BUFFER_GEOMETRIC_VOLUME_M3", 1670.0, "m3", "buffer_structural_anchor", "Vessel geometry only; pressure/usable Nm3 capacity is not source-backed.", input_status="development_diagnostic"),
        _dev_row("LINDE_O2_BUFFER_MODE", "balancing_buffer_only", "policy", "buffer_policy", "Buffer is not strategic DA arbitrage storage.", input_status="development_assumption"),
        _dev_row("LINDE_O2_STRATEGIC_STORAGE_ALLOWED", "false", "boolean", "buffer_policy", "Prevents fake oxygen-storage flexibility.", input_status="development_assumption"),
        _dev_row("LINDE_ASU_MFRR_ELIGIBLE_BASE", "false", "boolean", "mFRR_policy", "ASU mFRR is disabled in this base layer.", input_status="development_assumption"),
        _dev_row("LINDE_LIQUID_O2_BACKUP_EXPANSION", "context/reliability only", "-", "backup_context", "Do not treat liquid O2 as normal dispatch storage.", input_status="development_diagnostic"),
        _dev_row("LINDE_LIQUID_ARGON_BACKUP_EXPANSION", "context/reliability only", "-", "backup_context", "Argon remains deferred.", input_status="development_diagnostic"),
        _dev_row("LINDE_NITROGEN_CHANGE_WITH_HERACLESS", "no major change foreseen; deferred", "-", "deferred_utility", "N2 is not active in this first O2 layer.", input_status="development_deferred"),
        _dev_row("LINDE_COMPRESSED_DRY_AIR_EXTRA_COMPRESSOR", 20000.0, "Nm3/h", "deferred_utility", "Compressed dry air is deferred and not an O2 carrier.", input_status="development_deferred"),
        _dev_row("BF_OXYGEN_INPUT_NM3_PER_T_HM", 43.0, "Nm3 O2/t hot metal", "oxygen_demand", "C5p_a canonical BF oxygen volume basis.", low_value=4.6, high_value=67.0),
        _dev_row("BOF_OXYGEN_INPUT_NM3_PER_T_LS", 55.0, "Nm3 O2/t liquid steel", "oxygen_demand", "Existing BOF C5k coefficient; volume basis is canonical for O2 bus.", low_value=49.5, high_value=70.0),
        _dev_row("EAF_OXYGEN_INPUT_NM3_PER_T_LS", 35.0, "Nm3 O2/t liquid steel", "oxygen_demand", "Existing C5o_b EAF coefficient; broad BREF range.", low_value=5.0, high_value=65.0),
        _dev_row("DRP_OXYGEN_INPUT_T_PER_T_DRI_PROJECT_ACTIVE", 0.135, "t O2/t DRI", "oxygen_demand_active", "Accepted C5o_a project-derived DRP oxygen basis; high/uncertain.", input_status="development_candidate"),
        _dev_row("DRP_OXYGEN_INPUT_NM3_PER_T_DRI_VENDOR_CROSSCHECK", 35.0, "Nm3 O2/t DRI", "oxygen_demand_crosscheck", "Vendor cross-check only; not additive to active project basis.", input_status="development_diagnostic"),
        _dev_row("DRP_OXYGEN_BASIS_REQUIRES_REVIEW", "true", "boolean", "oxygen_demand_caveat", "Project and vendor DRP oxygen bases are materially different.", input_status="development_diagnostic"),
        _dev_row("LINDE_O2_DEMAND_PRECEDENT_T_PER_H", 150.0, "t O2/h", "validation_anchor", "Athanasiadis/Badarinath modelling precedent only; not a hard capacity."),
        _dev_row("LINDE_O2_DEMAND_PRECEDENT_NM3_PER_H", 105000.0, "Nm3 O2/h", "validation_anchor", "Derived high-level sanity check only.", input_status="development_diagnostic"),
        _dev_row("LINDE_ASU_POWER_AT_150_T_H_O2", 60.0, "MW", "validation_anchor", "150 t/h times 0.400 MWh/t.", input_status="development_diagnostic"),
        _dev_row("OXYGEN_RESIDUAL_OR_UNMODELLED_USES_MODE", "reporting_only", "-", "residual_policy", "Gap to 150 t/h precedent is not hidden plant demand.", input_status="development_assumption"),
        _dev_row("DENOMINATOR_STATUS_AFTER_LINDE", "unresolved_until_utilities_complete", "-", "denominator_policy", "Do not freeze EUR/t denominator before boiler/steam and generator/interface layers.", input_status="development_assumption"),
        _dev_row("C5M_F_COKE_RECONCILIATION_BASELINE_STATUS", "active_development_baseline", "-", "coke_governance", "Bounded C5m_f reconciliation is the active development baseline; external coke is fallback only.", input_status="development_assumption"),
    ]


def _validation_anchor_rows() -> list[dict[str, Any]]:
    return [
        {
            "anchor_id": "LINDE_O2_DEMAND_PRECEDENT",
            "value": 150.0,
            "unit": "t O2/h",
            "anchor_status": "validation_precedent_not_capacity_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "High-level modelling precedent; do not hard-constrain model to 150 t/h.",
        },
        {
            "anchor_id": "LINDE_ASU_POWER_AT_150_T_H",
            "value": 60.0,
            "unit": "MW",
            "anchor_status": "derived_sanity_check_not_capacity_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "150 t/h * 0.400 MWh/t.",
        },
        {
            "anchor_id": "LINDE_O2_BUFFER_GEOMETRIC_VOLUME",
            "value": 1670.0,
            "unit": "m3 vessel geometry",
            "anchor_status": "structural_anchor_not_model_ready_Nm3_capacity",
            "source_card": SOURCE_CARD,
            "caveat": "Operating pressure and usable swing are not public/source-backed.",
        },
    ]


def _source_payload() -> dict[str, Any]:
    run_s4_4c5o_c_dsp_downstream_physical_layer()
    return {
        "params": _param_map(_linde_dev_rows()),
        "c5k": _by_key(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv")),
        "c5l_d": _base_c5l_d_rows(_read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv")),
        "drp": _by_key(_read_csv(C5O_A_DIR / "s4_4c5o_a_drp_material_energy_ledger.csv")),
        "eaf": _by_key(_read_csv(C5O_B_DIR / "s4_4c5o_b_eaf_material_energy_ledger.csv")),
        "dsp": _by_key(_read_csv(C5O_C_DIR / "s4_4c5o_c_dsp_material_energy_ledger.csv")),
        "dsp_totals": _by_key(_read_csv(C5O_C_DIR / "s4_4c5o_c_modelled_totals_delta.csv")),
    }


def _oxygen_demand_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    params = payload["params"]
    density = _param_float(params, "LINDE_O2_DENSITY_KG_PER_NM3")
    t_per_nm3 = density / 1000.0
    bf_coeff = _param_float(params, "BF_OXYGEN_INPUT_NM3_PER_T_HM")
    bof_coeff = _param_float(params, "BOF_OXYGEN_INPUT_NM3_PER_T_LS")
    eaf_coeff = _param_float(params, "EAF_OXYGEN_INPUT_NM3_PER_T_LS")
    drp_project_t = _param_float(params, "DRP_OXYGEN_INPUT_T_PER_T_DRI_PROJECT_ACTIVE")
    drp_vendor_nm3 = _param_float(params, "DRP_OXYGEN_INPUT_NM3_PER_T_DRI_VENDOR_CROSSCHECK")
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            c5k = payload["c5k"][key]
            drp = payload["drp"][key]
            eaf = payload["eaf"][key]
            bf_hm = _zero(c5k["bf_hot_metal_normalised_site_t_y"])
            bof_ls = _zero(c5k["bof_liquid_steel_site_t_y"])
            eaf_ls = _zero(eaf["EAF_LS_output_site_t_y"])
            drp_dri = _zero(drp["DRI_output_site_t_y"])
            bf_nm3 = bf_hm * bf_coeff
            bof_nm3 = _zero(c5k["bof_oxygen_input_site_Nm3_y"])
            eaf_nm3 = eaf_ls * eaf_coeff
            drp_t = _zero(drp["DRP_oxygen_diagnostic_site_t_y"])
            drp_nm3 = drp_t / t_per_nm3 if t_per_nm3 else 0.0
            drp_active_nm3_coeff = drp_nm3 / drp_dri if drp_dri else 0.0
            vendor_drp_nm3 = drp_dri * drp_vendor_nm3
            total_nm3 = bf_nm3 + bof_nm3 + eaf_nm3 + drp_nm3
            total_t = total_nm3 * t_per_nm3
            avg_t_h = total_t / 8760.0
            precedent_t_h = _param_float(params, "LINDE_O2_DEMAND_PRECEDENT_T_PER_H")
            residual_t_h = max(precedent_t_h - avg_t_h, 0.0)
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "oxygen_bus_mode": "single_O2_bus_Nm3_demand_tonne_ASU_electricity",
                    "O2_density_kg_per_Nm3": density,
                    "O2_t_per_Nm3": t_per_nm3,
                    "BF_hot_metal_site_t_y": bf_hm,
                    "BF_O2_coeff_Nm3_per_t_HM": bf_coeff,
                    "BF_oxygen_demand_Nm3_y": bf_nm3,
                    "BF_oxygen_demand_t_y": bf_nm3 * t_per_nm3,
                    "BOF_liquid_steel_site_t_y": bof_ls,
                    "BOF_O2_coeff_Nm3_per_t_LS": bof_coeff,
                    "BOF_oxygen_demand_Nm3_y": bof_nm3,
                    "BOF_oxygen_demand_t_y": bof_nm3 * t_per_nm3,
                    "BOF_oxygen_kg_row_not_added_separately": "true",
                    "EAF_liquid_steel_site_t_y": eaf_ls,
                    "EAF_O2_coeff_Nm3_per_t_LS": eaf_coeff,
                    "EAF_oxygen_demand_Nm3_y": eaf_nm3,
                    "EAF_oxygen_demand_t_y": eaf_nm3 * t_per_nm3,
                    "DRP_DRI_output_site_t_y": drp_dri,
                    "DRP_active_O2_coeff_t_per_t_DRI": drp_project_t,
                    "DRP_active_O2_coeff_Nm3_per_t_DRI": drp_active_nm3_coeff,
                    "DRP_vendor_crosscheck_O2_coeff_Nm3_per_t_DRI": drp_vendor_nm3,
                    "DRP_vendor_crosscheck_O2_demand_Nm3_y": vendor_drp_nm3,
                    "DRP_project_minus_vendor_O2_coeff_Nm3_per_t_DRI": drp_active_nm3_coeff - drp_vendor_nm3 if drp_dri else 0.0,
                    "DRP_project_minus_vendor_O2_demand_t_y": drp_t - vendor_drp_nm3 * t_per_nm3,
                    "DRP_oxygen_basis_requires_review": _bool(drp_dri > TOL and abs(drp_active_nm3_coeff - drp_vendor_nm3) > 1.0),
                    "DRP_project_and_vendor_added_together": "false",
                    "DRP_oxygen_demand_Nm3_y": drp_nm3,
                    "DRP_oxygen_demand_t_y": drp_t,
                    "total_core_oxygen_demand_Nm3_y": total_nm3,
                    "total_core_oxygen_demand_t_y": total_t,
                    "average_core_oxygen_demand_t_per_h": avg_t_h,
                    "precedent_oxygen_demand_t_per_h": precedent_t_h,
                    "precedent_oxygen_demand_Nm3_per_h": _param_float(params, "LINDE_O2_DEMAND_PRECEDENT_NM3_PER_H"),
                    "residual_or_unmodelled_uses_t_per_h_to_150_precedent": residual_t_h,
                    "residual_or_unmodelled_uses_t_y_to_150_precedent": residual_t_h * 8760.0,
                    "residual_or_unmodelled_uses_mode": "reporting_only_not_added_to_ASU_production",
                    "oxygen_demand_double_counted_kg_and_Nm3": "false",
                }
            )
    return rows


def _asu_rows(payload: dict[str, Any], oxygen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = payload["params"]
    electricity_coeff = _param_float(params, "LINDE_ASU_ELECTRICITY_MWH_PER_T_O2_GAS_BASE")
    rows: list[dict[str, Any]] = []
    for row in oxygen:
        oxygen_t = _zero(row["total_core_oxygen_demand_t_y"])
        production_nm3 = _zero(row["total_core_oxygen_demand_Nm3_y"])
        electricity = oxygen_t * electricity_coeff
        avg_mw = electricity / 8760.0
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "status": "development_only",
                "thesis_usability": "false",
                "LINDE_ASU_ACTIVE": _bool(oxygen_t > TOL),
                "LINDE_ASU_output_basis": _param_text(params, "LINDE_ASU_OUTPUT_BASIS"),
                "ASU_oxygen_production_Nm3_y": production_nm3,
                "ASU_oxygen_production_t_y": oxygen_t,
                "ASU_oxygen_production_average_t_per_h": oxygen_t / 8760.0,
                "ASU_electricity_coeff_MWh_per_t_O2": electricity_coeff,
                "ASU_electricity_MWh_y": electricity,
                "ASU_electricity_TWh_y": electricity / 1_000_000.0,
                "ASU_average_MW": avg_mw,
                "precedent_150_t_h_power_MW": _param_float(params, "LINDE_ASU_POWER_AT_150_T_H_O2"),
                "ASU_average_MW_gap_to_60MW_precedent": avg_mw - _param_float(params, "LINDE_ASU_POWER_AT_150_T_H_O2"),
                "oxygen_residual_or_unmodelled_uses_t_y_reporting_only": row["residual_or_unmodelled_uses_t_y_to_150_precedent"],
                "ASU_mFRR_eligible_base": "false",
                "ASU_DA_price_responsive": "false",
                "liquid_O2_backup_context_only": "true",
                "N2_Ar_dry_air_active": "false",
                "ASU_electricity_scope": "modelled_process_electricity_current_C5_scope_not_full_site",
            }
        )
    return rows


def _buffer_rows(payload: dict[str, Any], oxygen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = payload["params"]
    rows: list[dict[str, Any]] = []
    for row in oxygen:
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "status": "development_only",
                "thesis_usability": "false",
                "O2_buffer_mode": _param_text(params, "LINDE_O2_BUFFER_MODE"),
                "O2_buffer_geometric_volume_m3": _param_float(params, "LINDE_O2_BUFFER_GEOMETRIC_VOLUME_M3"),
                "O2_buffer_geometric_volume_status": "structural_anchor_only_not_model_ready_Nm3_capacity",
                "O2_buffer_pressure_assumption_available": "false",
                "O2_buffer_usable_capacity_Nm3": "",
                "O2_buffer_model_ready_capacity_status": "deferred_until_pressure_and_usable_swing_are_source_backed",
                "O2_buffer_charge_Nm3_y": 0.0,
                "O2_buffer_discharge_Nm3_y": 0.0,
                "O2_buffer_start_Nm3": 0.0,
                "O2_buffer_end_Nm3": 0.0,
                "O2_buffer_min_Nm3": 0.0,
                "O2_buffer_max_Nm3": 0.0,
                "O2_buffer_terminal_rule": "start_equals_end_if_represented",
                "O2_buffer_terminal_status": "pass",
                "O2_buffer_used_as_strategic_storage": "false",
                "O2_buffer_strategic_storage_allowed": "false",
                "O2_buffer_capacity_binds": "false",
            }
        )
    return rows


def _modelled_total_delta_rows(payload: dict[str, Any], asu: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in asu:
        key = (row["configuration"], int(row["horizon_hours"]))
        prior = payload["dsp_totals"][key]
        before_elec = _zero(prior["process_electricity_after_DSP_MWh_e_y"])
        asu_elec = _zero(row["ASU_electricity_MWh_y"])
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "status": "development_only_scope_expansion_due_to_Linde_ASU_electricity_accounting",
                "thesis_usability": "false",
                "process_electricity_before_Linde_ASU_MWh_e_y": before_elec,
                "LINDE_ASU_electricity_delta_MWh_e_y": asu_elec,
                "process_electricity_after_Linde_ASU_MWh_e_y": before_elec + asu_elec,
                "process_electricity_scope": "modelled_process_electricity_current_C5_scope_not_full_site",
                "diagnostic_CO2_before_Linde_ASU_t_y": prior["diagnostic_CO2_after_DSP_t_y"],
                "LINDE_ASU_direct_CO2_delta_t_y": 0.0,
                "diagnostic_CO2_after_Linde_ASU_t_y": prior["diagnostic_CO2_after_DSP_t_y"],
                "CO2_guard_status_after_Linde_ASU": prior["CO2_guard_status_after_DSP"],
                "WAG_invariant_status_after_Linde_ASU": prior["WAG_invariant_status_after_DSP"],
                "LHV_consistency_status_after_Linde_ASU": prior["LHV_consistency_status_after_DSP"],
                "HSM_heat_case": prior["HSM_heat_case"],
                "denominator_status": "unresolved_until_Linde_boilers_generators_complete",
            }
        )
    return rows


def _coke_governance_rows() -> list[dict[str, Any]]:
    return [
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": "false",
            "governance_topic": "coke_reconciliation_baseline",
            "current_status": "C5m_f_bounded_coke_reconciliation_active_development_baseline",
            "external_unmodelled_coke_status": "fallback_only_not_active_baseline",
            "sensitivity_status": "allowed_but_not_current_baseline",
            "equation_change_in_C5p_a": "false",
            "caveat": "Governance clarification only; no coke equations changed in C5p_a.",
        }
    ]


def _plant_kpi_rows(oxygen: list[dict[str, Any]], asu: list[dict[str, Any]], buffer: list[dict[str, Any]]) -> list[dict[str, Any]]:
    asu_by_key = _by_key(asu)  # type: ignore[arg-type]
    buffer_by_key = _by_key(buffer)  # type: ignore[arg-type]
    rows: list[dict[str, Any]] = []
    for row in oxygen:
        key = (row["configuration"], int(row["horizon_hours"]))
        asu_row = asu_by_key[key]
        buf = buffer_by_key[key]
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_or_controller": "LINDE_ASU",
                "active_status": "active" if asu_row["LINDE_ASU_ACTIVE"] == "true" else "inactive",
                "activity_driver_name": "oxygen_production_t_O2",
                "activity_driver_value": asu_row["ASU_oxygen_production_t_y"],
                "material_inputs_summary": "air_not_modelled;electricity_input_accounted",
                "material_outputs_summary": f"O2_t_y={_fmt(_zero(asu_row['ASU_oxygen_production_t_y']))}",
                "electricity_MWh_or_TWh": asu_row["ASU_electricity_TWh_y"],
                "steam_t_or_kt": "not_applicable",
                "oxygen_t_or_Nm3": f"t_y={_fmt(_zero(row['total_core_oxygen_demand_t_y']))};Nm3_y={_fmt(_zero(row['total_core_oxygen_demand_Nm3_y']))}",
                "thermal_fuel_TWh_or_PJ": "not_applicable",
                "WAG_generated_by_carrier": "none",
                "WAG_consumed_by_carrier": "none",
                "NG_consumed": "0",
                "CO2_diagnostic": "0_direct_ASU_CO2_in_C5p_a",
                "included_in_totals_flags": "electricity=true;oxygen_supply=true;diagnostic_CO2=false;full_site=false",
                "buffer_status": buf["O2_buffer_model_ready_capacity_status"],
                "caveat/status": "development_only_not_thesis_approved",
            }
        )
    return rows


REDFLAG_NAMES = (
    "LINDE_ASU_ACTIVE_WITHOUT_OXYGEN_DEMAND",
    "OXYGEN_DEMAND_DOUBLE_COUNTED_KG_AND_NM3",
    "OXYGEN_FREE_SUPPLY_WITHOUT_ASU_ELECTRICITY",
    "ASU_ELECTRICITY_MISSING",
    "O2_BUFFER_USED_AS_STRATEGIC_STORAGE",
    "O2_BUFFER_HAS_USABLE_NM3_FROM_GEOMETRIC_VOLUME_WITHOUT_PRESSURE_ASSUMPTION",
    "ASU_MFRR_ENABLED_IN_BASE",
    "LINDE_N2_ARGON_DRY_AIR_ACTIVE_IN_FIRST_O2_LAYER",
    "DRP_OXYGEN_BOTH_PROJECT_AND_VENDOR_ADDED",
    "BOF_DRP_EAF_BF_OUTPUTS_CHANGED_BY_LINDE_LAYER",
    "HSM_BASE_0_50_REVERTED",
    "COKE_RECONCILIATION_BASELINE_REOPENED",
    "DENOMINATOR_SILENTLY_FROZEN",
)

CAVEAT_NAMES = (
    "DRP_OXYGEN_BASIS_REQUIRES_REVIEW",
    "O2_BUFFER_PRESSURE_NOT_SOURCE_BACKED",
    "OXYGEN_RESIDUAL_UNMODELLED_USES",
    "LINDE_ASU_ELECTRICITY_NOT_FULL_SITE_ELECTRICITY",
    "LINDE_NOT_THESIS_APPROVED",
    "DENOMINATOR_UNRESOLVED_UNTIL_UTILITIES_COMPLETE",
    "N2_ARGON_DRY_AIR_DEFERRED",
    "LIQUID_O2_BACKUP_NOT_DISPATCH_STORAGE",
)


def _health_rows(
    payload: dict[str, Any],
    oxygen: list[dict[str, Any]],
    asu: list[dict[str, Any]],
    buffer: list[dict[str, Any]],
    totals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    asu_by_key = _by_key(asu)  # type: ignore[arg-type]
    buffer_by_key = _by_key(buffer)  # type: ignore[arg-type]
    total_by_key = _by_key(totals)  # type: ignore[arg-type]
    rows: list[dict[str, Any]] = []
    for row in oxygen:
        key = (row["configuration"], int(row["horizon_hours"]))
        asu_row = asu_by_key[key]
        buf = buffer_by_key[key]
        total = total_by_key[key]
        c5k = payload["c5k"][key]
        drp = payload["drp"][key]
        eaf = payload["eaf"][key]
        dsp = payload["dsp"][key]
        c5l_d = payload["c5l_d"][key]
        active = asu_row["LINDE_ASU_ACTIVE"] == "true"
        flags = {
            "LINDE_ASU_ACTIVE_WITHOUT_OXYGEN_DEMAND": active and _zero(row["total_core_oxygen_demand_t_y"]) <= TOL,
            "OXYGEN_DEMAND_DOUBLE_COUNTED_KG_AND_NM3": row["oxygen_demand_double_counted_kg_and_Nm3"] == "true",
            "OXYGEN_FREE_SUPPLY_WITHOUT_ASU_ELECTRICITY": _zero(asu_row["ASU_oxygen_production_t_y"]) > TOL and _zero(asu_row["ASU_electricity_MWh_y"]) <= TOL,
            "ASU_ELECTRICITY_MISSING": active and _zero(asu_row["ASU_electricity_MWh_y"]) <= TOL,
            "O2_BUFFER_USED_AS_STRATEGIC_STORAGE": buf["O2_buffer_used_as_strategic_storage"] == "true",
            "O2_BUFFER_HAS_USABLE_NM3_FROM_GEOMETRIC_VOLUME_WITHOUT_PRESSURE_ASSUMPTION": bool(buf["O2_buffer_usable_capacity_Nm3"]) and buf["O2_buffer_pressure_assumption_available"] != "true",
            "ASU_MFRR_ENABLED_IN_BASE": asu_row["ASU_mFRR_eligible_base"] == "true",
            "LINDE_N2_ARGON_DRY_AIR_ACTIVE_IN_FIRST_O2_LAYER": asu_row["N2_Ar_dry_air_active"] == "true",
            "DRP_OXYGEN_BOTH_PROJECT_AND_VENDOR_ADDED": row["DRP_project_and_vendor_added_together"] == "true",
            "BOF_DRP_EAF_BF_OUTPUTS_CHANGED_BY_LINDE_LAYER": False,
            "HSM_BASE_0_50_REVERTED": c5l_d["active_cap_case"] != "base_0_50",
            "COKE_RECONCILIATION_BASELINE_REOPENED": False,
            "DENOMINATOR_SILENTLY_FROZEN": False,
        }
        caveats = {
            "DRP_OXYGEN_BASIS_REQUIRES_REVIEW": row["DRP_oxygen_basis_requires_review"] == "true",
            "O2_BUFFER_PRESSURE_NOT_SOURCE_BACKED": True,
            "OXYGEN_RESIDUAL_UNMODELLED_USES": _zero(row["residual_or_unmodelled_uses_t_y_to_150_precedent"]) > TOL,
            "LINDE_ASU_ELECTRICITY_NOT_FULL_SITE_ELECTRICITY": True,
            "LINDE_NOT_THESIS_APPROVED": True,
            "DENOMINATOR_UNRESOLVED_UNTIL_UTILITIES_COMPLETE": True,
            "N2_ARGON_DRY_AIR_DEFERRED": True,
            "LIQUID_O2_BACKUP_NOT_DISPATCH_STORAGE": True,
        }
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "status": "development_only",
                "thesis_usability": "false",
                "LINDE_ASU_active": asu_row["LINDE_ASU_ACTIVE"],
                "BF_oxygen_demand_t_y": row["BF_oxygen_demand_t_y"],
                "BOF_oxygen_demand_t_y": row["BOF_oxygen_demand_t_y"],
                "EAF_oxygen_demand_t_y": row["EAF_oxygen_demand_t_y"],
                "DRP_oxygen_demand_t_y": row["DRP_oxygen_demand_t_y"],
                "total_core_oxygen_demand_Nm3_y": row["total_core_oxygen_demand_Nm3_y"],
                "total_core_oxygen_demand_t_y": row["total_core_oxygen_demand_t_y"],
                "average_core_oxygen_demand_t_per_h": row["average_core_oxygen_demand_t_per_h"],
                "ASU_electricity_MWh_y": asu_row["ASU_electricity_MWh_y"],
                "ASU_average_MW": asu_row["ASU_average_MW"],
                "ASU_60MW_precedent_gap_MW": asu_row["ASU_average_MW_gap_to_60MW_precedent"],
                "DRP_active_O2_coeff_Nm3_per_t_DRI": row["DRP_active_O2_coeff_Nm3_per_t_DRI"],
                "DRP_vendor_crosscheck_O2_coeff_Nm3_per_t_DRI": row["DRP_vendor_crosscheck_O2_coeff_Nm3_per_t_DRI"],
                "DRP_project_minus_vendor_O2_demand_t_y": row["DRP_project_minus_vendor_O2_demand_t_y"],
                "O2_buffer_mode": buf["O2_buffer_mode"],
                "O2_buffer_geometric_volume_m3": buf["O2_buffer_geometric_volume_m3"],
                "O2_buffer_model_ready_capacity_status": buf["O2_buffer_model_ready_capacity_status"],
                "ASU_mFRR_eligible_base": asu_row["ASU_mFRR_eligible_base"],
                "oxygen_strategic_storage_allowed": buf["O2_buffer_strategic_storage_allowed"],
                "N2_Ar_dry_air_active": asu_row["N2_Ar_dry_air_active"],
                "liquid_O2_backup_context_only": asu_row["liquid_O2_backup_context_only"],
                "coke_reconciliation_baseline_status": "C5m_f_bounded_coke_reconciliation_active_development_baseline",
                "external_unmodelled_coke_status": "fallback_only_not_active_baseline",
                "denominator_status": total["denominator_status"],
                "process_electricity_after_Linde_ASU_MWh_e_y": total["process_electricity_after_Linde_ASU_MWh_e_y"],
                "CO2_guard_status_after_Linde_ASU": total["CO2_guard_status_after_Linde_ASU"],
                "WAG_invariant_status_after_Linde_ASU": total["WAG_invariant_status_after_Linde_ASU"],
                "LHV_consistency_status_after_Linde_ASU": total["LHV_consistency_status_after_Linde_ASU"],
                "baseline_BOF_liquid_steel_site_t_y": c5k["bof_liquid_steel_site_t_y"],
                "baseline_DRP_DRI_output_site_t_y": drp["DRI_output_site_t_y"],
                "baseline_EAF_LS_output_site_t_y": eaf["EAF_LS_output_site_t_y"],
                "baseline_DSP_output_site_t_y": dsp["DSP_output_site_t_y"],
                "HSM_heat_case": total["HSM_heat_case"],
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
    rows: list[dict[str, Any]] = []
    for row in health:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "O2_total_kt_y": _zero(row["total_core_oxygen_demand_t_y"]) / 1000.0,
                "O2_average_t_h": row["average_core_oxygen_demand_t_per_h"],
                "ASU_electricity_TWh_y": _zero(row["ASU_electricity_MWh_y"]) / 1_000_000.0,
                "ASU_average_MW": row["ASU_average_MW"],
                "DRP_O2_basis_review": row["DRP_OXYGEN_BASIS_REQUIRES_REVIEW"] if "DRP_OXYGEN_BASIS_REQUIRES_REVIEW" in row else ("true" if "DRP_OXYGEN_BASIS_REQUIRES_REVIEW" in row["caveats"] else "false"),
                "O2_buffer_status": row["O2_buffer_model_ready_capacity_status"],
                "coke_baseline_status": row["coke_reconciliation_baseline_status"],
                "denominator_status": row["denominator_status"],
                "failure_count": row["failure_count"],
                "caveats": row["caveats"],
            }
        )
    return rows


def _stage_gate(redflags: list[dict[str, Any]], health: list[dict[str, Any]]) -> dict[str, Any]:
    failure_count = sum(int(row["failure_count"]) for row in redflags)
    c0 = next(row for row in health if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    c1 = next(row for row in health if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    return {
        "stage_id": STAGE,
        "decision": "pass_development_linde_asu_oxygen_accounting" if failure_count == 0 else "fail_development_linde_asu_oxygen_accounting",
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "output_directory": _rel(C5P_A_DIR),
        "failure_count": failure_count,
        "C0_24h_total_oxygen_t_y": _zero(c0["total_core_oxygen_demand_t_y"]),
        "C0_24h_average_oxygen_t_h": _zero(c0["average_core_oxygen_demand_t_per_h"]),
        "C0_24h_ASU_electricity_MWh_y": _zero(c0["ASU_electricity_MWh_y"]),
        "C0_24h_ASU_average_MW": _zero(c0["ASU_average_MW"]),
        "C1_24h_total_oxygen_t_y": _zero(c1["total_core_oxygen_demand_t_y"]),
        "C1_24h_average_oxygen_t_h": _zero(c1["average_core_oxygen_demand_t_per_h"]),
        "C1_24h_ASU_electricity_MWh_y": _zero(c1["ASU_electricity_MWh_y"]),
        "C1_24h_ASU_average_MW": _zero(c1["ASU_average_MW"]),
        "ASU_mFRR_eligible_base": False,
        "oxygen_strategic_storage_allowed": False,
        "N2_Ar_dry_air_active": False,
        "coke_reconciliation_baseline_status": "C5m_f_bounded_coke_reconciliation_active_development_baseline",
        "external_unmodelled_coke_status": "fallback_only_not_active_baseline",
        "denominator_status": "unresolved_until_Linde_boilers_generators_complete",
    }


def _write_outputs() -> dict[str, Any]:
    C5P_A_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(C5P_A_DIR / "s4_4c5p_a_linde_development_input_rows.csv", _linde_dev_rows())
    _write_csv(C5P_A_DIR / "s4_4c5p_a_linde_validation_anchors.csv", _validation_anchor_rows())

    payload = _source_payload()
    oxygen = _oxygen_demand_rows(payload)
    asu = _asu_rows(payload, oxygen)
    buffer = _buffer_rows(payload, oxygen)
    totals = _modelled_total_delta_rows(payload, asu)
    coke_governance = _coke_governance_rows()
    kpis = _plant_kpi_rows(oxygen, asu, buffer)
    health = _health_rows(payload, oxygen, asu, buffer, totals)
    redflags = _redflag_rows(health)
    compact = _compact_table_rows(health)
    gate = _stage_gate(redflags, health)

    _write_json(C5P_A_DIR / "s4_4c5p_a_stage_gate.json", gate)
    _write_csv(
        C5P_A_DIR / "s4_4c5p_a_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5o_c_dsp_downstream_physical_layer",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5P_A_DIR / "s4_4c5p_a_oxygen_demand_ledger.csv", oxygen)
    _write_csv(C5P_A_DIR / "s4_4c5p_a_asu_electricity_ledger.csv", asu)
    _write_csv(C5P_A_DIR / "s4_4c5p_a_oxygen_buffer_dashboard.csv", buffer)
    _write_csv(C5P_A_DIR / "s4_4c5p_a_modelled_totals_delta.csv", totals)
    _write_csv(C5P_A_DIR / "s4_4c5p_a_coke_governance_status.csv", coke_governance)
    _write_csv(C5P_A_DIR / "s4_4c5p_a_plant_kpi_table.csv", kpis)
    _write_csv(C5P_A_DIR / "s4_4c5p_a_compact_healthcheck.csv", health)
    _write_csv(C5P_A_DIR / "s4_4c5p_a_red_flags.csv", redflags)
    _write_csv(C5P_A_DIR / "s4_4c5p_a_compact_table_for_chat.csv", compact)
    _write_json(
        C5P_A_DIR / "s4_4c5p_a_linde_asu_oxygen_accounting_report.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "pattern_audit_result": PATTERN_AUDIT_RESULT,
            "stage_gate": gate,
            "baseline_preservation": {
                "C5k_route_split_changed": False,
                "C5l_d_HSM_heat_case": "base_0_50",
                "ASU_mFRR_eligible": False,
                "oxygen_strategic_storage_allowed": False,
                "N2_Ar_dry_air_active": False,
                "coke_governance_patch_only": True,
                "denominator_frozen": False,
            },
            "sections": {
                "oxygen_demand": oxygen,
                "asu_electricity": asu,
                "oxygen_buffer": buffer,
                "modelled_totals": totals,
                "coke_governance": coke_governance,
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
            "development_inputs": len(_linde_dev_rows()),
            "oxygen": len(oxygen),
            "asu": len(asu),
            "buffer": len(buffer),
            "totals": len(totals),
            "health": len(health),
            "redflags": len(redflags),
        },
    }
    _write_json(C5P_A_DIR / "s4_4c5p_a_summary.json", summary)
    return summary


def run_s4_4c5p_a_linde_asu_oxygen_accounting() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5p_a_linde_asu_oxygen_accounting(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
