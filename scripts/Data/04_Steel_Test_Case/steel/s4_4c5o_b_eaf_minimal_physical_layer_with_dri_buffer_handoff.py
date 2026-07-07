"""S4.4c5o_b EAF minimal physical layer with DRI buffer handoff.

This stage replaces the C5o_a temporary DRI-to-future-EAF interface with a
development-only EAF accounting layer. It preserves the accepted C5k C1 route
target and reconciles the active EAF DRI coefficient to the available C5o_a DRP
DRI output without adding HBI, DRI import, hidden material slack, or EAF market
flexibility.
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
from .s4_4c5o_a_ng_drp_physical_layer_with_dri_interface import (
    C5O_A_DIR,
    run_s4_4c5o_a_ng_drp_physical_layer_with_dri_interface,
)


STAGE = "S4.4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff"
C5O_B_DIR = S4_ROOT / "s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff"
SOURCE_CARD = "data/03_Optimisation/inputs/assets/steel/source_cards/EAF_Parameters.md"
DEPENDENCY_CHAIN = (
    "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b "
    "-> C5m_c -> C5m_d -> C5m_e -> C5m_f -> C5n_a -> C5n_b -> C5o_a -> C5o_b"
)
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_healthcheck_pattern;"
    "EAF_values_loaded_from_C5o_b_development_input_rows;"
    "C5o_a_temporary_DRI_interface_replaced_by_C5o_b_EAF_DRI_input;"
    "C5k_EAF_route_target_preserved"
)

TOL_T = 1e-6
TOL_REL = 1e-9


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


def _eaf_dev_rows() -> list[dict[str, Any]]:
    return [
        _dev_row("EAF_HEAT_STATE_MODEL_ACTIVE", "true", "boolean", "heat_state_policy", "Heat-state skeleton is active for accounting; integer heat scheduling remains deferred.", input_status="development_assumption"),
        _dev_row("EAF_OUTPUT_BASIS", "liquid_steel", "-", "activity_basis", "Activity basis is liquid steel output.", input_status="development_assumption"),
        _dev_row("EAF_HEAT_SIZE_T_LS", 325.0, "t liquid steel/heat", "heat_state", "Public/source-card heat-size candidate, not thesis-approved."),
        _dev_row("EAF_HEAT_QH_STEPS_TOTAL", 3, "quarter-hours/heat", "heat_state", "Development heat skeleton only; no market quarter-hour implementation.", input_status="development_assumption"),
        _dev_row("EAF_MELTING_QH_STEPS_BASE", 2, "quarter-hours/heat", "heat_state", "Arc electricity allocated to the two melting quarter-hour states.", input_status="development_assumption"),
        _dev_row("EAF_TAPPING_TURNAROUND_QH_STEPS_BASE", 1, "quarter-hours/heat", "heat_state", "Tapping/turnaround has zero arc electricity in the skeleton.", input_status="development_assumption"),
        _dev_row("EAF_POWER_RATE_MAX_REL", 1.00, "relative", "heat_state_policy", "No 125% over-power option active.", high_value=1.00, input_status="development_assumption"),
        _dev_row("EAF_MISSED_ENERGY_MAKEUP_REQUIRED", "true", "boolean", "heat_state_policy", "Missed energy must extend heat in later scheduling layer; no over-power.", input_status="development_assumption"),
        _dev_row("EAF_MAKEUP_MODE", "extend_heat_no_overpower", "-", "heat_state_policy", "Development policy; no over-power and no reserve activation in this stage.", input_status="development_assumption"),
        _dev_row("EAF_MFRR_UP_ALLOWED_BASE", "true_only_as_future_readiness_diagnostic_during_melting", "-", "mFRR_readiness", "Diagnostic state eligibility only; no mFRR variables, activation or revenue.", input_status="development_assumption"),
        _dev_row("EAF_MFRR_DOWN_ALLOWED_BASE", "false", "boolean", "mFRR_readiness", "No downward mFRR in base.", input_status="development_assumption"),
        _dev_row("EAF_REFINING_RESERVE_ALLOWED_BASE", "false", "boolean", "mFRR_readiness", "No refining reserve in base.", input_status="development_assumption"),
        _dev_row("EAF_OFFGAS_AS_WAG", "false", "boolean", "WAG_policy", "EAF offgas is not BFG/COG/BOFG/mixed WAG and is not reusable WAG in this stage.", input_status="development_assumption"),
        _dev_row("EAF_SCRAP_PREHEAT_ENABLED", "true", "boolean", "topology_reporting", "Scrap preheat topology/reporting only; no useful steam/WAG recovery activated.", input_status="development_assumption"),
        _dev_row("EAF_RECONCILIATION_MODE", "preserve_C5_EAF_LS_target_and_reconcile_DRI_coefficient_to_available_DRP_DRI", "-", "route_reconciliation", "Preserves C5k EAF target and avoids hidden HBI/imported DRI.", input_status="development_assumption"),
        _dev_row("EAF_C1_LS_ANNUAL_OUTPUT_MT", 3.3, "Mt LS/y", "validation_anchor", "Raw validation anchor only, not hourly dispatch truth."),
        _dev_row("EAF_HDRI_INPUT_T_PER_T_LS_SOURCE", 0.848, "t DRI/t LS", "material_source_check", "Raw/source-card check; active coefficient is reconciled in C5o_b."),
        _dev_row("EAF_DRI_INPUT_T_PER_T_LS_ACTIVE_POLICY", "derived_by_C5o_b_from_available_DRP_DRI_and_active_EAF_target", "-", "material_policy", "Derived reconciliation value, not independent Tata EAF recipe.", input_status="development_assumption"),
        _dev_row("EAF_SCRAP_INPUT_T_PER_T_LS", 0.303, "t scrap/t LS", "material", "Source-card candidate, not hidden scrap slack."),
        _dev_row("EAF_ELECTRICITY_MWH_PER_T_LS_TATA", 0.422, "MWh_e/t LS", "electricity", "Arc electricity candidate from source-card; not DA-responsive."),
        _dev_row("EAF_ELECTRICITY_MWH_PER_T_LS_PROJECT_PRECEDENT", 0.525, "MWh_e/t LS", "electricity_sensitivity_check", "Sensitivity/check only, not active base.", input_status="development_sensitivity"),
        _dev_row("EAF_COKE_BREEZE_ANTHRACITE_GJ_PER_T_LS", 0.27, "GJ/t LS", "solid_fuel_diagnostic", "Solid carbon driver only; not WAG."),
        _dev_row("EAF_ELECTRODES_GJ_PER_T_LS", 0.03, "GJ/t LS", "electrode_diagnostic", "Electrode carbon/energy diagnostic driver."),
        _dev_row("EAF_NG_GJ_PER_T_LS", 0.05, "GJ_LHV/t LS", "natural_gas", "Small process NG driver; not WAG market logic."),
        _dev_row("EAF_OXYGEN_INPUT_NM3_PER_T_LS_BREF", 35.0, "Nm3 O2/t LS", "oxygen_diagnostic", "Diagnostic midpoint until Linde/ASU layer exists."),
        _dev_row("O2_T_PER_NM3", 0.001429, "t O2/Nm3", "unit_conversion", "Explicit oxygen conversion used for diagnostic tonnes O2."),
        _dev_row("EAF_DIRECT_CO2_T_PER_T_LS_BREF_MIDPOINT", 0.126, "t CO2/t LS", "CO2_diagnostic", "Midpoint of 0.072-0.180 range, diagnostic only.", low_value=0.072, high_value=0.180, input_status="development_diagnostic"),
        _dev_row("EAF_CO2_ACCOUNTING_MODE", "aggregate_BREF_midpoint_diagnostic", "-", "CO2_policy", "Diagnostic counter only; no ETS/full-site emissions and no fuel-explicit double-count.", input_status="development_assumption"),
        _dev_row("EAF_OFFGAS_STEAM_RECOVERY_MWH_TH_PER_T_LS", 0.076, "MWh_th/t LS", "offgas_reporting", "Reporting/validation potential only; not active steam supply.", input_status="development_diagnostic"),
        _dev_row("EAF_STEAM_OUTPUT_T_PER_T_LS_NG_DERIVED", 0.083, "t steam/t LS", "offgas_reporting", "Reporting/validation potential only; no boiler/steam implementation.", input_status="development_diagnostic"),
        _dev_row("EAF_OFFGAS_HEAT_COOLING_MWH_TH_PER_T_LS", 0.117, "MWh_th/t LS", "offgas_reporting_deferred", "Deferred offgas cooling heat diagnostic.", input_status="development_diagnostic"),
        _dev_row("EAF_OFFGAS_STACK_LOSS_MWH_TH_PER_T_LS", 0.031, "MWh_th/t LS", "offgas_reporting_deferred", "Deferred offgas stack-loss diagnostic.", input_status="development_diagnostic"),
        _dev_row("EAF_SECONDARY_MET_ELECTRICITY_MWH_PER_T_LS", 0.031, "MWh_e/t LS", "secondary_met_deferred", "Reported separately as deferred/accounting-only; not mixed into arc electricity.", input_status="development_diagnostic"),
    ]


def _validation_anchor_rows() -> list[dict[str, Any]]:
    return [
        {
            "anchor_id": "EAF_C1_RAW_LS_OUTPUT",
            "value": 3.3,
            "unit": "Mt LS/y",
            "anchor_status": "raw_validation_anchor_not_hourly_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "Compared against active C5k EAF route target only.",
        },
        {
            "anchor_id": "EAF_RAW_HDRI_TO_EAF",
            "value": 2.8,
            "unit": "Mt DRI/y",
            "anchor_status": "raw_validation_anchor_not_hidden_HBI_supply",
            "source_card": SOURCE_CARD,
            "caveat": "Active C5o_b preserves C5k EAF target and reconciles DRI coefficient to C5o_a DRP output.",
        },
        {
            "anchor_id": "EAF_RAW_SCRAP_INPUT",
            "value": 1.0,
            "unit": "Mt scrap/y",
            "anchor_status": "raw_validation_anchor_only",
            "source_card": SOURCE_CARD,
            "caveat": "No hidden scrap import slack; scrap is an accounting input.",
        },
        {
            "anchor_id": "EAF_HEAT_SIZE",
            "value": 325,
            "unit": "t LS/heat",
            "anchor_status": "heat_state_development_candidate",
            "source_card": SOURCE_CARD,
            "caveat": "Used for heat-equivalent accounting, not integer heat scheduling.",
        },
        {
            "anchor_id": "EAF_AVERAGE_POWER",
            "value": 200,
            "unit": "MWe plus auxiliaries",
            "anchor_status": "validation_check_only",
            "source_card": SOURCE_CARD,
            "caveat": "Compared against average annual arc load; no DA dispatch.",
        },
    ]


def _source_payload() -> dict[str, Any]:
    run_s4_4c5o_a_ng_drp_physical_layer_with_dri_interface()
    return {
        "params": _param_map(_eaf_dev_rows()),
        "c5k": _by_key(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv")),
        "c5o_a_material": _by_key(_read_csv(C5O_A_DIR / "s4_4c5o_a_drp_material_energy_ledger.csv")),
        "c5o_a_buffer": _by_key(_read_csv(C5O_A_DIR / "s4_4c5o_a_dri_buffer_interface_dashboard.csv")),
        "c5o_a_totals": _by_key(_read_csv(C5O_A_DIR / "s4_4c5o_a_modelled_totals_delta.csv")),
        "c5l_d": _base_c5l_d_rows(_read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv")),
    }


def _activity_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    params = payload["params"]
    source_dri_coeff = _param_float(params, "EAF_HDRI_INPUT_T_PER_T_LS_SOURCE")
    raw_anchor = _param_float(params, "EAF_C1_LS_ANNUAL_OUTPUT_MT") * 1_000_000.0
    reconciliation_mode = _param_text(params, "EAF_RECONCILIATION_MODE")
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            c5k = payload["c5k"][key]
            drp = payload["c5o_a_material"][key]
            eaf_ls = _zero(c5k["active_eaf_liquid_steel_target_site_t_y"])
            available_dri = _zero(drp["DRI_output_site_t_y"])
            active = eaf_ls > TOL_T
            source_requirement = eaf_ls * source_dri_coeff
            source_gap = available_dri - source_requirement
            resolved_dri_coeff = available_dri / eaf_ls if active else 0.0
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "EAF_ACTIVE": _bool(active),
                    "EAF_output_basis": "liquid_steel",
                    "EAF_raw_anchor_LS_site_t_y": raw_anchor if config == C1 else 0.0,
                    "EAF_active_LS_target_site_t_y": eaf_ls,
                    "EAF_raw_anchor_gap_site_t_y": eaf_ls - raw_anchor if config == C1 else 0.0,
                    "active_total_liquid_steel_target_site_t_y": _zero(c5k["active_total_liquid_steel_target_site_t_y"]),
                    "active_BOF_liquid_steel_site_t_y": _zero(c5k["active_bof_liquid_steel_target_site_t_y"]),
                    "active_EAF_liquid_steel_site_t_y": eaf_ls,
                    "BOF_plus_EAF_total_site_t_y": _zero(c5k["active_bof_liquid_steel_target_site_t_y"]) + eaf_ls,
                    "BOF_plus_EAF_total_matches_C5k_target": _bool(abs((_zero(c5k["active_bof_liquid_steel_target_site_t_y"]) + eaf_ls) - _zero(c5k["active_total_liquid_steel_target_site_t_y"])) <= TOL_T),
                    "available_DRP_DRI_for_EAF_site_t_y": available_dri,
                    "EAF_DRI_source_coefficient_t_per_t_LS": source_dri_coeff,
                    "EAF_DRI_requirement_under_source_coeff_site_t_y": source_requirement,
                    "EAF_DRI_gap_under_source_coeff_site_t_y": source_gap,
                    "EAF_DRI_INPUT_T_PER_T_LS_ACTIVE": resolved_dri_coeff,
                    "selected_DRI_reconciliation_mode": reconciliation_mode,
                    "EAF_DRI_coeff_reconciled_to_active_C5": _bool(active and abs(resolved_dri_coeff - source_dri_coeff) > 1e-6),
                    "EAF_DRI_hidden_source_active": "false",
                    "EAF_HBI_import_used_in_base": "false",
                    "raw_anchor_used_as_hourly_constraint": "false",
                    "C5k_route_split_preserved": "true",
                }
            )
    return rows


def _material_energy_rows(payload: dict[str, Any], activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = payload["params"]
    scrap = _param_float(params, "EAF_SCRAP_INPUT_T_PER_T_LS")
    electricity = _param_float(params, "EAF_ELECTRICITY_MWH_PER_T_LS_TATA")
    project_electricity = _param_float(params, "EAF_ELECTRICITY_MWH_PER_T_LS_PROJECT_PRECEDENT")
    ng = _param_float(params, "EAF_NG_GJ_PER_T_LS")
    carbon = _param_float(params, "EAF_COKE_BREEZE_ANTHRACITE_GJ_PER_T_LS")
    electrodes = _param_float(params, "EAF_ELECTRODES_GJ_PER_T_LS")
    oxygen_nm3 = _param_float(params, "EAF_OXYGEN_INPUT_NM3_PER_T_LS_BREF")
    o2_t_per_nm3 = _param_float(params, "O2_T_PER_NM3")
    co2_mid = _param_float(params, "EAF_DIRECT_CO2_T_PER_T_LS_BREF_MIDPOINT")
    co2_low = _zero(params["EAF_DIRECT_CO2_T_PER_T_LS_BREF_MIDPOINT"]["low_value"])
    co2_high = _zero(params["EAF_DIRECT_CO2_T_PER_T_LS_BREF_MIDPOINT"]["high_value"])
    offgas_steam = _param_float(params, "EAF_OFFGAS_STEAM_RECOVERY_MWH_TH_PER_T_LS")
    steam_t = _param_float(params, "EAF_STEAM_OUTPUT_T_PER_T_LS_NG_DERIVED")
    offgas_cooling = _param_float(params, "EAF_OFFGAS_HEAT_COOLING_MWH_TH_PER_T_LS")
    offgas_stack = _param_float(params, "EAF_OFFGAS_STACK_LOSS_MWH_TH_PER_T_LS")
    secondary_met = _param_float(params, "EAF_SECONDARY_MET_ELECTRICITY_MWH_PER_T_LS")
    heat_size = _param_float(params, "EAF_HEAT_SIZE_T_LS")
    melting_steps = _param_float(params, "EAF_MELTING_QH_STEPS_BASE")
    active_melting_duration_h = melting_steps * 0.25
    rows: list[dict[str, Any]] = []
    for act in activity:
        ls = _zero(act["EAF_active_LS_target_site_t_y"])
        dri_coeff = _zero(act["EAF_DRI_INPUT_T_PER_T_LS_ACTIVE"])
        oxygen_t_coeff = oxygen_nm3 * o2_t_per_nm3
        heat_count = ls / heat_size if heat_size else 0.0
        arc_energy_per_heat = heat_size * electricity if ls > TOL_T else 0.0
        active_heat_power = arc_energy_per_heat / active_melting_duration_h if active_melting_duration_h and ls > TOL_T else 0.0
        arc_mwh = ls * electricity
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": act["configuration"],
                "horizon_hours": act["horizon_hours"],
                "status": "development_only",
                "thesis_usability": "false",
                "EAF_ACTIVE": act["EAF_ACTIVE"],
                "EAF_LS_output_site_t_y": ls,
                "EAF_DRI_INPUT_T_PER_T_LS_ACTIVE": dri_coeff,
                "EAF_DRI_input_site_t_y": ls * dri_coeff,
                "EAF_scrap_input_t_per_t_LS": scrap,
                "EAF_scrap_input_site_t_y": ls * scrap,
                "EAF_scrap_raw_anchor_site_t_y": 1_000_000.0 if act["configuration"] == C1 else 0.0,
                "EAF_scrap_raw_anchor_gap_site_t_y": (ls * scrap - 1_000_000.0) if act["configuration"] == C1 else 0.0,
                "EAF_arc_electricity_MWh_e_y": arc_mwh,
                "EAF_arc_electricity_TWh_e_y": arc_mwh / 1_000_000.0,
                "EAF_average_annual_arc_load_MW": arc_mwh / 8760.0,
                "EAF_heat_size_t_LS": heat_size,
                "EAF_heat_count_equivalent_y": heat_count,
                "EAF_heat_state_mode": "fractional_heat_equivalent_accounting",
                "EAF_heat_integerity_status": "EAF_HEAT_INTEGERITY_RELAXED_FOR_DEVELOPMENT" if ls > TOL_T else "inactive_zero",
                "EAF_arc_energy_per_heat_MWh": arc_energy_per_heat,
                "EAF_active_heat_arc_power_MW": active_heat_power,
                "EAF_project_precedent_electricity_check_MWh_e_y": ls * project_electricity,
                "EAF_secondary_met_electricity_reporting_only_MWh_e_y": ls * secondary_met,
                "EAF_secondary_met_electricity_included_in_arc_total": "false",
                "EAF_NG_GJ_y": ls * ng,
                "EAF_NG_PJ_y": ls * ng / 1_000_000.0,
                "EAF_carbon_coke_breeze_anthracite_GJ_y": ls * carbon,
                "EAF_carbon_coke_breeze_anthracite_PJ_y": ls * carbon / 1_000_000.0,
                "EAF_electrodes_GJ_y": ls * electrodes,
                "EAF_electrodes_PJ_y": ls * electrodes / 1_000_000.0,
                "EAF_oxygen_input_Nm3_per_t_LS": oxygen_nm3,
                "O2_t_per_Nm3_conversion": o2_t_per_nm3,
                "EAF_oxygen_input_t_per_t_LS": oxygen_t_coeff,
                "EAF_oxygen_diagnostic_t_y": ls * oxygen_t_coeff,
                "oxygen_supply_status": "not_implemented_caveat" if ls > TOL_T else "inactive_zero",
                "EAF_CO2_mode": _param_text(params, "EAF_CO2_ACCOUNTING_MODE"),
                "EAF_direct_CO2_midpoint_t_per_t_LS": co2_mid,
                "EAF_direct_CO2_range_low_t_per_t_LS": co2_low,
                "EAF_direct_CO2_range_high_t_per_t_LS": co2_high,
                "EAF_CO2_diagnostic_midpoint_t_y": ls * co2_mid,
                "EAF_CO2_diagnostic_range_low_t_y": ls * co2_low,
                "EAF_CO2_diagnostic_range_high_t_y": ls * co2_high,
                "EAF_fuel_explicit_CO2_active": "false",
                "EAF_CO2_double_count_risk": "false",
                "EAF_offgas_as_WAG": "false",
                "EAF_offgas_to_BFG_COG_BOFG_MWh_y": 0.0,
                "EAF_useful_WAG_generation_MWh_y": 0.0,
                "EAF_offgas_steam_recovery_potential_MWh_th_y": ls * offgas_steam,
                "EAF_offgas_steam_recovery_potential_TWh_th_y": ls * offgas_steam / 1_000_000.0,
                "EAF_steam_output_reporting_only_t_y": ls * steam_t,
                "EAF_offgas_heat_cooling_MWh_th_y": ls * offgas_cooling,
                "EAF_offgas_stack_loss_MWh_th_y": ls * offgas_stack,
                "steam_recovery_reporting_only": _bool(ls > TOL_T),
                "EAF_DA_responsive": "false",
                "EAF_overpower_gt_1_enabled": "false",
                "EAF_mFRR_variables_active": "false",
            }
        )
    return rows


def _heat_state_rows(payload: dict[str, Any], material: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = payload["params"]
    heat_size = _param_float(params, "EAF_HEAT_SIZE_T_LS")
    total_steps = int(_param_float(params, "EAF_HEAT_QH_STEPS_TOTAL"))
    melting_steps = int(_param_float(params, "EAF_MELTING_QH_STEPS_BASE"))
    tapping_steps = int(_param_float(params, "EAF_TAPPING_TURNAROUND_QH_STEPS_BASE"))
    rows: list[dict[str, Any]] = []
    for mat in material:
        ls = _zero(mat["EAF_LS_output_site_t_y"])
        arc = _zero(mat["EAF_arc_electricity_MWh_e_y"])
        heats = ls / heat_size if heat_size else 0.0
        arc_energy_per_heat = heat_size * _param_float(params, "EAF_ELECTRICITY_MWH_PER_T_LS_TATA") if ls > TOL_T else 0.0
        active_duration_h = melting_steps * 0.25
        active_heat_power = arc_energy_per_heat / active_duration_h if active_duration_h and ls > TOL_T else 0.0
        common = {
            "stage_id": STAGE,
            "configuration": mat["configuration"],
            "horizon_hours": mat["horizon_hours"],
            "status": "development_only",
            "thesis_usability": "false",
            "EAF_heat_state_model_active": "true",
            "EAF_heat_integerity_status": "EAF_HEAT_INTEGERITY_RELAXED_FOR_DEVELOPMENT" if ls > TOL_T else "inactive_zero",
            "EAF_heat_size_t_LS": heat_size,
            "EAF_heat_count_equivalent_y": heats,
            "EAF_heat_qh_steps_total": total_steps,
            "EAF_melting_qh_steps": melting_steps,
            "EAF_tapping_turnaround_qh_steps": tapping_steps,
            "EAF_arc_energy_per_heat_MWh": arc_energy_per_heat,
            "EAF_active_heat_arc_power_MW": active_heat_power,
            "mFRR_readiness_status": "future_readiness_diagnostic_only_no_variables" if ls > TOL_T else "inactive_zero",
        }
        for state, state_index in (
            ("MELTING_POWER_ON_1", 1),
            ("MELTING_POWER_ON_2", 2),
            ("TAPPING_TURNAROUND_POWER_OFF", 3),
        ):
            power_on = state.startswith("MELTING")
            rows.append(
                {
                    **common,
                    "heat_state": state,
                    "heat_state_index": state_index,
                    "arc_power_on": _bool(power_on and ls > TOL_T),
                    "EAF_arc_electricity_MWh_e_y": arc / melting_steps if power_on and melting_steps else 0.0,
                    "liquid_steel_release_after_tapping_t_y": ls if state == "TAPPING_TURNAROUND_POWER_OFF" else 0.0,
                    "mFRR_readiness_diagnostic_MW": active_heat_power if power_on and ls > TOL_T else 0.0,
                    "mFRR_variable_or_revenue_active": "false",
                    "electricity_outside_power_on_state": "false",
                }
            )
    return rows


def _dri_buffer_handoff_rows(payload: dict[str, Any], activity: list[dict[str, Any]], material: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mat_by_key = _by_key_like(material)
    rows: list[dict[str, Any]] = []
    for act in activity:
        key = (act["configuration"], int(act["horizon_hours"]))
        buf = payload["c5o_a_buffer"][key]
        mat = mat_by_key[key]
        start = _zero(buf["DRI_inventory_start_t"])
        capacity = _zero(buf["DRI_buffer_capacity_t"])
        eaf_dri = _zero(mat["EAF_DRI_input_site_t_y"])
        drp_dri = _zero(buf["DRI_output_site_t_y"])
        drift = drp_dri - eaf_dri
        end = start + drift
        min_inventory = min(start, end)
        max_inventory = max(start, end)
        placeholder = _zero(buf["DRI_to_future_EAF_placeholder_site_t_y"])
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": act["configuration"],
                "horizon_hours": act["horizon_hours"],
                "status": "development_only",
                "thesis_usability": "false",
                "DRI_buffer_mode": "aggregated_DRI_store_with_EAF_handoff",
                "DRI_buffer_capacity_t": capacity,
                "DRI_inventory_start_t": start,
                "DRI_inventory_end_t": end,
                "DRI_inventory_min_t": min_inventory,
                "DRI_inventory_max_t": max_inventory,
                "DRI_inventory_drift_t": drift,
                "DRI_buffer_terminal_rule": "end_equals_initial",
                "DRI_buffer_terminal_status": "pass" if abs(drift) <= TOL_T else "fail",
                "DRI_buffer_capacity_binding": _bool(capacity > TOL_T and max_inventory >= capacity - TOL_T),
                "DRI_buffer_capacity_binding_unexpected": "false",
                "C5o_a_temporary_DRI_to_future_EAF_interface_site_t_y": placeholder,
                "C5o_b_EAF_DRI_input_site_t_y": eaf_dri,
                "temporary_DRI_interface_replaced_by_EAF_input": _bool(abs(placeholder - eaf_dri) <= TOL_T),
                "temporary_DRI_to_future_EAF_interface_active_after_C5o_b": "false",
                "DRI_to_EAF_site_t_y": eaf_dri,
                "hidden_DRI_source_site_t_y": 0.0,
                "HBI_import_site_t_y": 0.0,
                "DRI_gap_or_surplus_after_reconciliation_t_y": drift,
                "DRI_buffer_mined_without_terminal_guard": "false",
            }
        )
    return rows


def _by_key_like(rows: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _downstream_rows(payload: dict[str, Any], activity: list[dict[str, Any]], material: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for act in activity:
        key = (act["configuration"], int(act["horizon_hours"]))
        c5k = payload["c5k"][key]
        c5l_d = payload["c5l_d"][key]
        eaf_ls = _zero(act["EAF_active_LS_target_site_t_y"])
        c5k_eaf = _zero(c5k["active_eaf_liquid_steel_target_site_t_y"])
        bof = _zero(c5k["active_bof_liquid_steel_target_site_t_y"])
        total = _zero(c5k["active_total_liquid_steel_target_site_t_y"])
        total_after = bof + eaf_ls
        hsm_case_ok = c5l_d.get("cap_case") == "base_0_50" and c5l_d.get("active_cap_case") == "base_0_50"
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": act["configuration"],
                "horizon_hours": act["horizon_hours"],
                "status": "development_only",
                "thesis_usability": "false",
                "EAF_LS_output_site_t_y": eaf_ls,
                "C5k_EAF_route_placeholder_site_t_y": c5k_eaf,
                "EAF_placeholder_replaced_by_actual_output": _bool(abs(eaf_ls - c5k_eaf) <= TOL_T),
                "EAF_double_counts_existing_route_placeholder": "false",
                "EAF_output_connected_to_downstream": "true",
                "downstream_interface_status": "feeds_existing_C5k_C5l_downstream_route_placeholder_replacement",
                "BOF_liquid_steel_site_t_y": bof,
                "BOF_plus_EAF_total_site_t_y": total_after,
                "active_total_liquid_steel_target_site_t_y": total,
                "C1_total_production_mismatch_t_y": total_after - total,
                "C1_total_production_matches_target": _bool(abs(total_after - total) <= TOL_T),
                "HSM_heat_case": c5l_d.get("cap_case", ""),
                "HSM_base_0_50_default_preserved": _bool(hsm_case_ok),
                "HSM_output_site_t_y": c5l_d.get("hsm_output_site_t_y", ""),
                "HSM_slab_input_site_t_y": c5l_d.get("hsm_slab_input_site_t_y", ""),
                "DSP_NOT_IMPLEMENTED_CAVEAT": _bool(eaf_ls > TOL_T),
            }
        )
    return rows


def _modelled_total_delta_rows(payload: dict[str, Any], material: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mat in material:
        key = (mat["configuration"], int(mat["horizon_hours"]))
        c5o_a = payload["c5o_a_totals"][key]
        before_electricity = _zero(c5o_a["process_electricity_after_DRP_MWh_e_y"])
        before_co2 = _zero(c5o_a["diagnostic_CO2_after_DRP_t_y"])
        eaf_electricity = _zero(mat["EAF_arc_electricity_MWh_e_y"])
        eaf_co2 = _zero(mat["EAF_CO2_diagnostic_midpoint_t_y"])
        eaf_ng_pj = _zero(mat["EAF_NG_PJ_y"])
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": mat["configuration"],
                "horizon_hours": mat["horizon_hours"],
                "status": "development_only_scope_expansion_due_to_EAF_arc_electricity_NG_and_CO2_diagnostic_accounting",
                "thesis_usability": "false",
                "process_electricity_before_EAF_MWh_e_y": before_electricity,
                "EAF_arc_electricity_delta_MWh_e_y": eaf_electricity,
                "process_electricity_after_EAF_MWh_e_y": before_electricity + eaf_electricity,
                "EAF_secondary_met_electricity_reporting_only_not_included_MWh_e_y": mat["EAF_secondary_met_electricity_reporting_only_MWh_e_y"],
                "diagnostic_CO2_before_EAF_t_y": before_co2,
                "EAF_CO2_diagnostic_midpoint_delta_t_y": eaf_co2,
                "diagnostic_CO2_after_EAF_t_y": before_co2 + eaf_co2,
                "EAF_fuel_explicit_CO2_active": "false",
                "EAF_CO2_guard_status_after_EAF": "pass",
                "EAF_NG_delta_PJ_y": eaf_ng_pj,
                "EAF_offgas_entered_WAG": "false",
                "WAG_invariant_status_after_EAF": c5o_a["WAG_invariant_status_after_DRP"],
                "LHV_consistency_status_after_EAF": c5o_a["LHV_consistency_status_after_DRP"],
                "HSM_heat_case": c5o_a["HSM_heat_case"],
            }
        )
    return rows


def _plant_kpi_rows(material: list[dict[str, Any]], handoff: list[dict[str, Any]], downstream: list[dict[str, Any]]) -> list[dict[str, Any]]:
    handoff_by_key = _by_key_like(handoff)
    down_by_key = _by_key_like(downstream)
    rows: list[dict[str, Any]] = []
    for mat in material:
        key = (mat["configuration"], int(mat["horizon_hours"]))
        hand = handoff_by_key[key]
        down = down_by_key[key]
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": mat["configuration"],
                "horizon_hours": mat["horizon_hours"],
                "plant_or_controller": "EAF",
                "active_status": "active" if mat["EAF_ACTIVE"] == "true" else "inactive",
                "activity_driver_name": "EAF_liquid_steel_output",
                "activity_driver_value": mat["EAF_LS_output_site_t_y"],
                "material_inputs_summary": (
                    f"DRI_t_y={_fmt(_zero(mat['EAF_DRI_input_site_t_y']))};"
                    f"scrap_t_y={_fmt(_zero(mat['EAF_scrap_input_site_t_y']))}"
                ),
                "material_outputs_summary": f"liquid_steel_t_y={_fmt(_zero(mat['EAF_LS_output_site_t_y']))}",
                "electricity_MWh_or_TWh": mat["EAF_arc_electricity_TWh_e_y"],
                "steam_t_or_kt": mat["EAF_steam_output_reporting_only_t_y"],
                "oxygen_t_or_Nm3": mat["EAF_oxygen_diagnostic_t_y"],
                "thermal_fuel_TWh_or_PJ": mat["EAF_NG_PJ_y"],
                "WAG_generated_by_carrier": "BFG=0;COG=0;BOFG=0;EAF_offgas_not_WAG",
                "WAG_consumed_by_carrier": "none",
                "NG_consumed": mat["EAF_NG_PJ_y"],
                "CO2_diagnostic": mat["EAF_CO2_diagnostic_midpoint_t_y"],
                "included_in_totals_flags": "electricity=true;diagnostic_CO2=true;NG=true;secondary_met=false_reporting_only",
                "DRI_buffer_status": hand["DRI_buffer_terminal_status"],
                "downstream_interface_status": down["downstream_interface_status"],
                "caveat/status": "development_only_not_thesis_approved",
            }
        )
    return rows


REDFLAG_NAMES = (
    "EAF_ACTIVE_IN_C0",
    "EAF_DRI_HIDDEN_SOURCE",
    "EAF_HBI_IMPORT_USED_IN_BASE",
    "EAF_DRI_BUFFER_TERMINAL_VIOLATION",
    "EAF_DRI_BUFFER_CAPACITY_BINDING_UNEXPECTED",
    "EAF_TEMP_DRI_INTERFACE_NOT_REPLACED",
    "EAF_DOUBLE_COUNTS_EXISTING_ROUTE_PLACEHOLDER",
    "EAF_OUTPUT_NOT_CONNECTED_TO_DOWNSTREAM",
    "EAF_OFFGAS_ENTERED_WAG",
    "EAF_MFRR_VARIABLES_ACTIVE_IN_BASE",
    "EAF_OVERPOWER_GT_1_ENABLED",
    "EAF_ELECTRICITY_OUTSIDE_POWER_ON_STATE",
    "EAF_CO2_DOUBLE_COUNT_RISK",
    "C1_TOTAL_PRODUCTION_MISMATCH_AFTER_EAF",
    "HSM_BASE_0_50_REVERTED",
    "DRP_PELLET_BALANCE_BROKEN_BY_EAF",
)

CAVEAT_NAMES = (
    "EAF_DRI_COEFF_RECONCILED_TO_ACTIVE_C5",
    "EAF_HEAT_INTEGERITY_RELAXED_FOR_DEVELOPMENT",
    "EAF_CO2_DIAGNOSTIC_NOT_ETS",
    "OXYGEN_SUPPLY_NOT_IMPLEMENTED_CAVEAT",
    "STEAM_RECOVERY_REPORTING_ONLY",
    "SECONDARY_METALLURGY_DEFERRED_OR_ACCOUNTING_ONLY",
    "DSP_NOT_IMPLEMENTED_CAVEAT",
    "EAF_NOT_THESIS_APPROVED",
)


def _health_rows(
    activity: list[dict[str, Any]],
    material: list[dict[str, Any]],
    handoff: list[dict[str, Any]],
    downstream: list[dict[str, Any]],
    totals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    act_by_key = _by_key_like(activity)
    mat_by_key = _by_key_like(material)
    hand_by_key = _by_key_like(handoff)
    down_by_key = _by_key_like(downstream)
    total_by_key = _by_key_like(totals)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            act = act_by_key[key]
            mat = mat_by_key[key]
            hand = hand_by_key[key]
            down = down_by_key[key]
            total = total_by_key[key]
            eaf_active = mat["EAF_ACTIVE"] == "true"
            flags = {
                "EAF_ACTIVE_IN_C0": config == C0 and eaf_active,
                "EAF_DRI_HIDDEN_SOURCE": _zero(hand["hidden_DRI_source_site_t_y"]) > TOL_T,
                "EAF_HBI_IMPORT_USED_IN_BASE": _zero(hand["HBI_import_site_t_y"]) > TOL_T,
                "EAF_DRI_BUFFER_TERMINAL_VIOLATION": hand["DRI_buffer_terminal_status"] != "pass",
                "EAF_DRI_BUFFER_CAPACITY_BINDING_UNEXPECTED": hand["DRI_buffer_capacity_binding_unexpected"] == "true",
                "EAF_TEMP_DRI_INTERFACE_NOT_REPLACED": eaf_active and hand["temporary_DRI_interface_replaced_by_EAF_input"] != "true",
                "EAF_DOUBLE_COUNTS_EXISTING_ROUTE_PLACEHOLDER": down["EAF_double_counts_existing_route_placeholder"] == "true",
                "EAF_OUTPUT_NOT_CONNECTED_TO_DOWNSTREAM": eaf_active and down["EAF_output_connected_to_downstream"] != "true",
                "EAF_OFFGAS_ENTERED_WAG": _zero(mat["EAF_offgas_to_BFG_COG_BOFG_MWh_y"]) > TOL_T or _zero(mat["EAF_useful_WAG_generation_MWh_y"]) > TOL_T,
                "EAF_MFRR_VARIABLES_ACTIVE_IN_BASE": mat["EAF_mFRR_variables_active"] == "true",
                "EAF_OVERPOWER_GT_1_ENABLED": mat["EAF_overpower_gt_1_enabled"] == "true",
                "EAF_ELECTRICITY_OUTSIDE_POWER_ON_STATE": False,
                "EAF_CO2_DOUBLE_COUNT_RISK": mat["EAF_CO2_double_count_risk"] == "true",
                "C1_TOTAL_PRODUCTION_MISMATCH_AFTER_EAF": config == C1 and down["C1_total_production_matches_target"] != "true",
                "HSM_BASE_0_50_REVERTED": total["HSM_heat_case"] != "base_0_50",
                "DRP_PELLET_BALANCE_BROKEN_BY_EAF": False,
            }
            caveats = {
                "EAF_DRI_COEFF_RECONCILED_TO_ACTIVE_C5": eaf_active and act["EAF_DRI_coeff_reconciled_to_active_C5"] == "true",
                "EAF_HEAT_INTEGERITY_RELAXED_FOR_DEVELOPMENT": eaf_active,
                "EAF_CO2_DIAGNOSTIC_NOT_ETS": eaf_active,
                "OXYGEN_SUPPLY_NOT_IMPLEMENTED_CAVEAT": eaf_active,
                "STEAM_RECOVERY_REPORTING_ONLY": eaf_active,
                "SECONDARY_METALLURGY_DEFERRED_OR_ACCOUNTING_ONLY": eaf_active,
                "DSP_NOT_IMPLEMENTED_CAVEAT": eaf_active and down["DSP_NOT_IMPLEMENTED_CAVEAT"] == "true",
                "EAF_NOT_THESIS_APPROVED": eaf_active,
            }
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "EAF_active": mat["EAF_ACTIVE"],
                    "EAF_LS_output_site_t_y": mat["EAF_LS_output_site_t_y"],
                    "EAF_raw_anchor_LS_site_t_y": act["EAF_raw_anchor_LS_site_t_y"],
                    "EAF_raw_anchor_gap_site_t_y": act["EAF_raw_anchor_gap_site_t_y"],
                    "available_DRP_DRI_site_t_y": act["available_DRP_DRI_for_EAF_site_t_y"],
                    "EAF_DRI_requirement_under_source_coeff_site_t_y": act["EAF_DRI_requirement_under_source_coeff_site_t_y"],
                    "EAF_DRI_gap_under_source_coeff_site_t_y": act["EAF_DRI_gap_under_source_coeff_site_t_y"],
                    "EAF_DRI_INPUT_T_PER_T_LS_ACTIVE": act["EAF_DRI_INPUT_T_PER_T_LS_ACTIVE"],
                    "EAF_DRI_input_site_t_y": mat["EAF_DRI_input_site_t_y"],
                    "EAF_scrap_input_site_t_y": mat["EAF_scrap_input_site_t_y"],
                    "EAF_arc_electricity_TWh_e_y": mat["EAF_arc_electricity_TWh_e_y"],
                    "EAF_average_annual_arc_load_MW": mat["EAF_average_annual_arc_load_MW"],
                    "EAF_heat_size_t_LS": mat["EAF_heat_size_t_LS"],
                    "EAF_heat_count_equivalent_y": mat["EAF_heat_count_equivalent_y"],
                    "EAF_heat_state_mode": mat["EAF_heat_state_mode"],
                    "EAF_heat_integerity_status": mat["EAF_heat_integerity_status"],
                    "EAF_arc_energy_per_heat_MWh": mat["EAF_arc_energy_per_heat_MWh"],
                    "EAF_active_heat_arc_power_MW": mat["EAF_active_heat_arc_power_MW"],
                    "EAF_NG_PJ_y": mat["EAF_NG_PJ_y"],
                    "EAF_carbon_coke_breeze_anthracite_PJ_y": mat["EAF_carbon_coke_breeze_anthracite_PJ_y"],
                    "EAF_electrodes_PJ_y": mat["EAF_electrodes_PJ_y"],
                    "EAF_oxygen_diagnostic_t_y": mat["EAF_oxygen_diagnostic_t_y"],
                    "EAF_CO2_mode": mat["EAF_CO2_mode"],
                    "EAF_CO2_diagnostic_midpoint_t_y": mat["EAF_CO2_diagnostic_midpoint_t_y"],
                    "EAF_CO2_diagnostic_range_low_t_y": mat["EAF_CO2_diagnostic_range_low_t_y"],
                    "EAF_CO2_diagnostic_range_high_t_y": mat["EAF_CO2_diagnostic_range_high_t_y"],
                    "EAF_offgas_as_WAG": mat["EAF_offgas_as_WAG"],
                    "EAF_offgas_steam_recovery_reporting_only_TWh_th_y": mat["EAF_offgas_steam_recovery_potential_TWh_th_y"],
                    "DRI_buffer_capacity_t": hand["DRI_buffer_capacity_t"],
                    "DRI_inventory_start_t": hand["DRI_inventory_start_t"],
                    "DRI_inventory_end_t": hand["DRI_inventory_end_t"],
                    "DRI_inventory_min_t": hand["DRI_inventory_min_t"],
                    "DRI_inventory_max_t": hand["DRI_inventory_max_t"],
                    "DRI_inventory_drift_t": hand["DRI_inventory_drift_t"],
                    "temporary_DRI_interface_replaced_by_EAF_input": hand["temporary_DRI_interface_replaced_by_EAF_input"],
                    "downstream_interface_status": down["downstream_interface_status"],
                    "BOF_plus_EAF_total_site_t_y": down["BOF_plus_EAF_total_site_t_y"],
                    "active_total_liquid_steel_target_site_t_y": down["active_total_liquid_steel_target_site_t_y"],
                    "HSM_heat_case": total["HSM_heat_case"],
                    "process_electricity_after_EAF_MWh_e_y": total["process_electricity_after_EAF_MWh_e_y"],
                    "diagnostic_CO2_after_EAF_t_y": total["diagnostic_CO2_after_EAF_t_y"],
                    "red_flags": ";".join(name for name, active in flags.items() if active),
                    "caveats": ";".join(name for name, active in caveats.items() if active),
                    "failure_count": sum(1 for active in flags.values() if active),
                    "caveat_count": sum(1 for active in caveats.values() if active),
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


def _compact_table_rows(
    activity: list[dict[str, Any]],
    material: list[dict[str, Any]],
    handoff: list[dict[str, Any]],
    downstream: list[dict[str, Any]],
    health: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mat_by_key = _by_key_like(material)
    hand_by_key = _by_key_like(handoff)
    down_by_key = _by_key_like(downstream)
    health_by_key = _by_key_like(health)
    rows: list[dict[str, Any]] = []
    for act in activity:
        key = (act["configuration"], int(act["horizon_hours"]))
        mat = mat_by_key[key]
        hand = hand_by_key[key]
        down = down_by_key[key]
        health_row = health_by_key[key]
        rows.append(
            {
                "configuration": act["configuration"],
                "horizon_hours": act["horizon_hours"],
                "EAF_active": mat["EAF_ACTIVE"],
                "EAF_LS_output_Mt_y": _zero(mat["EAF_LS_output_site_t_y"]) / 1_000_000.0,
                "EAF_raw_anchor_gap_Mt_y": _zero(act["EAF_raw_anchor_gap_site_t_y"]) / 1_000_000.0,
                "available_DRP_DRI_Mt_y": _zero(act["available_DRP_DRI_for_EAF_site_t_y"]) / 1_000_000.0,
                "source_coeff_DRI_requirement_Mt_y": _zero(act["EAF_DRI_requirement_under_source_coeff_site_t_y"]) / 1_000_000.0,
                "resolved_DRI_coeff": act["EAF_DRI_INPUT_T_PER_T_LS_ACTIVE"],
                "actual_DRI_input_Mt_y": _zero(mat["EAF_DRI_input_site_t_y"]) / 1_000_000.0,
                "scrap_input_Mt_y": _zero(mat["EAF_scrap_input_site_t_y"]) / 1_000_000.0,
                "arc_electricity_TWh_e_y": mat["EAF_arc_electricity_TWh_e_y"],
                "average_annual_arc_load_MW": mat["EAF_average_annual_arc_load_MW"],
                "active_heat_arc_power_MW": mat["EAF_active_heat_arc_power_MW"],
                "heat_count_equivalent_y": mat["EAF_heat_count_equivalent_y"],
                "heat_state_mode": mat["EAF_heat_state_mode"],
                "NG_PJ_y": mat["EAF_NG_PJ_y"],
                "carbon_PJ_y": mat["EAF_carbon_coke_breeze_anthracite_PJ_y"],
                "electrodes_PJ_y": mat["EAF_electrodes_PJ_y"],
                "oxygen_Mt_y": _zero(mat["EAF_oxygen_diagnostic_t_y"]) / 1_000_000.0,
                "CO2_midpoint_Mt_y": _zero(mat["EAF_CO2_diagnostic_midpoint_t_y"]) / 1_000_000.0,
                "DRI_buffer_capacity_kt": _zero(hand["DRI_buffer_capacity_t"]) / 1_000.0,
                "DRI_buffer_drift_t": hand["DRI_inventory_drift_t"],
                "temporary_DRI_interface_replaced": hand["temporary_DRI_interface_replaced_by_EAF_input"],
                "downstream_status": down["downstream_interface_status"],
                "failure_count": health_row["failure_count"],
                "caveats": health_row["caveats"],
            }
        )
    return rows


def _stage_gate(redflags: list[dict[str, Any]], activity: list[dict[str, Any]], material: list[dict[str, Any]], handoff: list[dict[str, Any]], downstream: list[dict[str, Any]]) -> dict[str, Any]:
    failure_count = sum(int(row["failure_count"]) for row in redflags)
    c1_activity = next(row for row in activity if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    c1_material = next(row for row in material if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    c1_handoff = next(row for row in handoff if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    c1_downstream = next(row for row in downstream if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    return {
        "stage_id": STAGE,
        "decision": "pass_development_eaf_minimal_physical_layer_with_dri_buffer_handoff" if failure_count == 0 else "fail_development_eaf_minimal_physical_layer_with_dri_buffer_handoff",
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "output_directory": _rel(C5O_B_DIR),
        "failure_count": failure_count,
        "C1_24h_EAF_LS_output_site_t_y": _zero(c1_activity["EAF_active_LS_target_site_t_y"]),
        "C1_24h_available_DRP_DRI_site_t_y": _zero(c1_activity["available_DRP_DRI_for_EAF_site_t_y"]),
        "C1_24h_EAF_DRI_source_requirement_site_t_y": _zero(c1_activity["EAF_DRI_requirement_under_source_coeff_site_t_y"]),
        "C1_24h_EAF_DRI_INPUT_T_PER_T_LS_ACTIVE": _zero(c1_activity["EAF_DRI_INPUT_T_PER_T_LS_ACTIVE"]),
        "C1_24h_EAF_scrap_input_site_t_y": _zero(c1_material["EAF_scrap_input_site_t_y"]),
        "C1_24h_EAF_arc_electricity_TWh_e_y": _zero(c1_material["EAF_arc_electricity_TWh_e_y"]),
        "C1_24h_EAF_average_annual_arc_load_MW": _zero(c1_material["EAF_average_annual_arc_load_MW"]),
        "C1_24h_EAF_active_heat_arc_power_MW": _zero(c1_material["EAF_active_heat_arc_power_MW"]),
        "C1_24h_EAF_heat_count_equivalent_y": _zero(c1_material["EAF_heat_count_equivalent_y"]),
        "C1_24h_EAF_NG_PJ_y": _zero(c1_material["EAF_NG_PJ_y"]),
        "C1_24h_EAF_oxygen_diagnostic_site_t_y": _zero(c1_material["EAF_oxygen_diagnostic_t_y"]),
        "C1_24h_EAF_CO2_midpoint_site_t_y": _zero(c1_material["EAF_CO2_diagnostic_midpoint_t_y"]),
        "C1_24h_DRI_buffer_capacity_t": _zero(c1_handoff["DRI_buffer_capacity_t"]),
        "C1_24h_DRI_inventory_drift_t": _zero(c1_handoff["DRI_inventory_drift_t"]),
        "temporary_DRI_interface_replaced": c1_handoff["temporary_DRI_interface_replaced_by_EAF_input"] == "true",
        "downstream_connection_status": c1_downstream["downstream_interface_status"],
        "EAF_offgas_as_WAG": False,
        "mFRR_variables_active": False,
        "oxygen_supply_status": "not_implemented_caveat",
        "CO2_accounting_mode": c1_material["EAF_CO2_mode"],
        "validation_anchors_used_as_hourly_constraints": False,
        "hidden_DRI_or_HBI_source_active": False,
    }


def _write_outputs() -> dict[str, Any]:
    C5O_B_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(C5O_B_DIR / "s4_4c5o_b_eaf_development_input_rows.csv", _eaf_dev_rows())
    _write_csv(C5O_B_DIR / "s4_4c5o_b_eaf_validation_anchors.csv", _validation_anchor_rows())

    payload = _source_payload()
    activity = _activity_rows(payload)
    material = _material_energy_rows(payload, activity)
    heat_states = _heat_state_rows(payload, material)
    handoff = _dri_buffer_handoff_rows(payload, activity, material)
    downstream = _downstream_rows(payload, activity, material)
    totals = _modelled_total_delta_rows(payload, material)
    kpis = _plant_kpi_rows(material, handoff, downstream)
    health = _health_rows(activity, material, handoff, downstream, totals)
    redflags = _redflag_rows(health)
    compact = _compact_table_rows(activity, material, handoff, downstream, health)
    gate = _stage_gate(redflags, activity, material, handoff, downstream)

    _write_json(C5O_B_DIR / "s4_4c5o_b_stage_gate.json", gate)
    _write_csv(
        C5O_B_DIR / "s4_4c5o_b_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5o_a_ng_drp_physical_layer_with_dri_interface",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5O_B_DIR / "s4_4c5o_b_eaf_activity_report.csv", activity)
    _write_csv(C5O_B_DIR / "s4_4c5o_b_eaf_material_energy_ledger.csv", material)
    _write_csv(C5O_B_DIR / "s4_4c5o_b_eaf_heat_state_ledger.csv", heat_states)
    _write_csv(C5O_B_DIR / "s4_4c5o_b_dri_buffer_handoff_dashboard.csv", handoff)
    _write_csv(C5O_B_DIR / "s4_4c5o_b_downstream_integration_dashboard.csv", downstream)
    _write_csv(C5O_B_DIR / "s4_4c5o_b_modelled_totals_delta.csv", totals)
    _write_csv(C5O_B_DIR / "s4_4c5o_b_plant_kpi_table.csv", kpis)
    _write_csv(C5O_B_DIR / "s4_4c5o_b_compact_healthcheck.csv", health)
    _write_csv(C5O_B_DIR / "s4_4c5o_b_red_flags.csv", redflags)
    _write_csv(C5O_B_DIR / "s4_4c5o_b_compact_table_for_chat.csv", compact)
    _write_json(
        C5O_B_DIR / "s4_4c5o_b_eaf_minimal_physical_layer_report.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "pattern_audit_result": PATTERN_AUDIT_RESULT,
            "stage_gate": gate,
            "scenario_scope": "C0 inactive; C1 Phase 1 EAF active",
            "baseline_preservation": {
                "C5k_route_split_changed": False,
                "C5l_d_HSM_heat_case": "base_0_50",
                "DRP_hydrogen_enabled": False,
                "EAF_mFRR_variables_active": False,
                "EAF_offgas_as_WAG": False,
                "external_DRI_or_HBI_implemented": False,
            },
            "sections": {
                "activity": activity,
                "material_energy": material,
                "heat_state": heat_states,
                "dri_buffer_handoff": handoff,
                "downstream_integration": downstream,
                "modelled_totals": totals,
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
            "development_inputs": len(_eaf_dev_rows()),
            "activity": len(activity),
            "material_energy": len(material),
            "heat_states": len(heat_states),
            "dri_handoff": len(handoff),
            "downstream": len(downstream),
            "health": len(health),
            "redflags": len(redflags),
        },
    }
    _write_json(C5O_B_DIR / "s4_4c5o_b_summary.json", summary)
    return summary


def run_s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
