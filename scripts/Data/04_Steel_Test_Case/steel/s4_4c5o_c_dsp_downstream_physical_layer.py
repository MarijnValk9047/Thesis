"""S4.4c5o_c DSP downstream physical layer.

This stage converts the existing C5l_d DSP downstream placeholder into an
explicit development-only Direct Sheet Plant accounting layer. It preserves the
accepted C5k production target, C5l_d base_0_50 HSM/WBW case, and C5o_b EAF/DRP
handoff while adding DSP material, electricity, internal scrap, and healthcheck
visibility.
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
from .s4_4c5l_a_downstream_routing_and_hsm_buffer_patch import C5L_A_DIR
from .s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch import C5L_D_DIR
from .s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff import (
    C5O_B_DIR,
    run_s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff,
)


STAGE = "S4.4c5o_c_dsp_downstream_physical_layer"
C5O_C_DIR = S4_ROOT / "s4_4c5o_c_dsp_downstream_physical_layer"
SOURCE_CARD = "data/03_Optimisation/inputs/assets/steel/source_cards/DSP_Parameters.md"
DEPENDENCY_CHAIN = (
    "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b "
    "-> C5m_c -> C5m_d -> C5m_e -> C5m_f -> C5n_a -> C5n_b -> C5o_a -> C5o_b -> C5o_c"
)
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_healthcheck_pattern;"
    "DSP_values_loaded_from_C5o_c_development_input_rows;"
    "C5l_d_DSP_placeholder_replaced_by_explicit_DSP_process_output;"
    "C5k_route_split_and_C5l_d_base_0_50_preserved"
)

TOL_T = 1e-6


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _bool(value: bool) -> str:
    return str(value).lower()


def _by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _by_key_like(rows: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
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


def _dsp_dev_rows() -> list[dict[str, Any]]:
    return [
        _dev_row("DSP_OUTPUT_BASIS", "t DSP hot-rolled coil", "-", "activity_basis", "Activity basis is final DSP coil output.", input_status="development_assumption"),
        _dev_row("DSP_RECONCILIATION_MODE", "preserve_current_C5_downstream_routing_and_replace_DSP_placeholder", "-", "downstream_policy", "Use existing C5l_d DSP placeholder as active output and wrap it in explicit DSP process accounting.", input_status="development_assumption"),
        _dev_row("DSP_C0_OUTPUT_ANNUAL_MT_Y", 1.5, "Mt/y", "validation_anchor", "Raw MER anchor only; not hourly dispatch truth."),
        _dev_row("DSP_C1_OUTPUT_ANNUAL_MT_Y", 1.5, "Mt/y", "validation_anchor", "Raw MER anchor only; not hourly dispatch truth."),
        _dev_row("DSP_C0_SHARE_OF_OSF_TO_DSP", 0.20, "fraction", "route_share_anchor", "C0 route-share validation anchor; not a hidden constraint."),
        _dev_row("DSP_C1_EAF_ROUTE_SHARE_OF_DSP", 0.90, "fraction", "route_share_anchor", "C1 EAF-route share validation anchor; current C5 pooled route cannot fully track origin."),
        _dev_row("DSP_C0_ACTIVE_TARGET_SCALING_DENOMINATOR_MT_Y", 7.2, "Mt liquid steel/y", "anchor_scaling_context", "Used only to report active-scaled anchor gap."),
        _dev_row("DSP_C1_ACTIVE_TARGET_SCALING_DENOMINATOR_MT_Y", 6.8, "Mt liquid steel/y", "anchor_scaling_context", "Used only to report active-scaled anchor gap."),
        _dev_row("DSP_PROCESS_CHANGED_IN_C1", "false", "boolean", "topology_anchor", "Public MER states DSP process remains structurally unchanged.", input_status="development_assumption"),
        _dev_row("DSP_ALLOWED_INPUT_C0", "BOF/OSF liquid steel", "carrier", "topology", "C0 input topology only; route-origin shares are validation checks.", input_status="development_assumption"),
        _dev_row("DSP_ALLOWED_INPUT_C1", "BOF/OSF liquid steel + EAF-route liquid steel", "carrier", "topology", "C1 input topology only; pooled C5 interface cannot yet prove exact origin split.", input_status="development_assumption"),
        _dev_row("DSP_LIQUID_STEEL_INPUT_T_PER_T_COIL_BASE", 1.05, "t liquid steel/t coil", "material", "Compact yield assumption, not Tata-validated.", low_value=1.03, high_value=1.07),
        _dev_row("DSP_COIL_YIELD_T_PER_T_LS_DERIVED", 1.0 / 1.05, "t coil/t liquid steel", "material_check", "Derived inverse check only.", input_status="development_diagnostic"),
        _dev_row("DSP_INTERNAL_SCRAP_LOSS_T_PER_T_COIL_DERIVED", 0.05, "t/t coil", "material_diagnostic", "Internal route loss/cutting loss reporting; not free EAF scrap.", input_status="development_diagnostic"),
        _dev_row("DSP_INTERNAL_SCRAP_RECYCLED", "true", "boolean", "scrap_topology_reporting", "Topology/reporting only unless governed internal scrap loop is active.", input_status="development_assumption"),
        _dev_row("DSP_ELECTRICITY_MWH_PER_T_COIL_BASE", 0.056, "MWh_e/t coil", "electricity", "Development rolling/casting electricity candidate; not DA-responsive.", low_value=0.028, high_value=0.111),
        _dev_row("DSP_TOTAL_FINAL_ENERGY_GJ_PER_T_BEST_PRACTICE", 0.20, "GJ/t coil", "validation_check", "Best-practice cross-check only; not additive to active electricity.", input_status="development_diagnostic"),
        _dev_row("DSP_TUNNEL_FURNACE_PRESENT", "true", "boolean", "topology", "Tunnel furnace topology is reported, but no heat coefficient is active.", input_status="development_assumption"),
        _dev_row("DSP_TUNNEL_FURNACE_LENGTH_M", 320.0, "m", "technical_context", "Plant fact-sheet context only, not an energy coefficient.", input_status="development_diagnostic"),
        _dev_row("DSP_TUNNEL_FURNACE_HEAT_GJ_PER_T", "deferred", "GJ/t coil", "fuel_heat_deferred", "No robust public Tata-specific heat coefficient; do not create WAG/NG sink.", input_status="development_deferred"),
        _dev_row("DSP_FUEL_GAS_BASE_ACTIVE", "false", "boolean", "fuel_policy", "Avoid fake WAG/NG demand in base.", input_status="development_assumption"),
        _dev_row("DSP_ALLOWED_FUEL_CARRIERS_IF_HEAT_ACTIVE", "COG,BFG,BOFG,NG", "carriers", "fuel_policy_deferred", "Eligibility only; no demand without active heat coefficient.", input_status="development_deferred"),
        _dev_row("DSP_DIRECT_CO2_MODE_BASE", "fuel-derived only", "-", "CO2_policy", "Direct CO2 is zero only because no direct fuel term is active.", input_status="development_assumption"),
        _dev_row("DSP_DIRECT_CO2_T_PER_T_COIL_BASE", 0.0, "t CO2/t coil", "CO2_diagnostic", "Accounting zero, not physical zero-emissions claim.", input_status="development_diagnostic"),
        _dev_row("DSP_OPERATION_CLASS", "bounded_downstream_scheduling_asset", "-", "operation_policy", "Downstream asset is bounded by liquid-steel routing and final-product fulfilment.", input_status="development_assumption"),
        _dev_row("DSP_MFRR_PROVIDER_BASE", "false", "boolean", "mFRR_policy", "DSP is not an mFRR provider in this stage.", input_status="development_assumption"),
        _dev_row("DSP_DA_FLEXIBILITY_BASE", "not_price_responsive_in_C5o_c", "-", "operation_policy", "No DA price response in this physical/accounting layer.", input_status="development_assumption"),
        _dev_row("DSP_LIQUID_STEEL_ROUTING_BALANCE_REQUIRED", "true", "boolean", "material_guardrail", "DSP must not consume unavailable liquid steel.", input_status="development_assumption"),
        _dev_row("DSP_OUTPUT_COUNTS_TOWARD_FINAL_PRODUCT_TARGET", "true", "boolean", "final_product_policy", "DSP output remains part of C5 final-product proxy.", input_status="development_assumption"),
    ]


def _validation_anchor_rows() -> list[dict[str, Any]]:
    return [
        {
            "anchor_id": "DSP_C0_RAW_OUTPUT",
            "value": 1.5,
            "unit": "Mt/y",
            "anchor_status": "raw_validation_anchor_not_hourly_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "Compared against active C5l_d DSP output placeholder replacement.",
        },
        {
            "anchor_id": "DSP_C1_RAW_OUTPUT",
            "value": 1.5,
            "unit": "Mt/y",
            "anchor_status": "raw_validation_anchor_not_hourly_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "Compared against active C5l_d DSP output placeholder replacement.",
        },
        {
            "anchor_id": "DSP_C0_OSF_TO_DSP_SHARE",
            "value": 0.20,
            "unit": "fraction",
            "anchor_status": "route_share_validation_anchor_not_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "C5l_a legacy route uses 20% DSP output share; C5o_c reports gross DSP input separately.",
        },
        {
            "anchor_id": "DSP_C1_EAF_ROUTE_SHARE",
            "value": 0.90,
            "unit": "fraction",
            "anchor_status": "route_share_validation_anchor_not_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "Current pooled downstream interface cannot prove exact BOF/EAF origin split.",
        },
        {
            "anchor_id": "C0_FINAL_PRODUCT_RAW_CONTEXT",
            "value": 6.9,
            "unit": "Mt/y",
            "anchor_status": "raw_final_product_validation_context",
            "source_card": SOURCE_CARD,
            "caveat": "5.4 Mt HSM rolled coils plus 1.5 Mt DSP rolls; not active target constraint.",
        },
        {
            "anchor_id": "C1_FINAL_PRODUCT_RAW_CONTEXT",
            "value": 7.0,
            "unit": "Mt/y",
            "anchor_status": "raw_final_product_validation_context",
            "source_card": SOURCE_CARD,
            "caveat": "5.5 Mt HSM rolled coils plus 1.5 Mt DSP rolls; not active target constraint.",
        },
    ]


def _source_payload() -> dict[str, Any]:
    run_s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff()
    return {
        "params": _param_map(_dsp_dev_rows()),
        "c5k": _by_key(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv")),
        "c5l_a": _by_key(_read_csv(C5L_A_DIR / "s4_4c5l_a_downstream_routing_report.csv")),
        "c5l_d": _base_c5l_d_rows(_read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv")),
        "c5o_b_downstream": _by_key(_read_csv(C5O_B_DIR / "s4_4c5o_b_downstream_integration_dashboard.csv")),
        "c5o_b_totals": _by_key(_read_csv(C5O_B_DIR / "s4_4c5o_b_modelled_totals_delta.csv")),
    }


def _scaled_anchor(config: str, active_target_t_y: float, params: dict[str, dict[str, Any]]) -> float:
    raw_anchor_t_y = 1_500_000.0
    if config == C0:
        denominator = _param_float(params, "DSP_C0_ACTIVE_TARGET_SCALING_DENOMINATOR_MT_Y") * 1_000_000.0
    else:
        denominator = _param_float(params, "DSP_C1_ACTIVE_TARGET_SCALING_DENOMINATOR_MT_Y") * 1_000_000.0
    return raw_anchor_t_y * active_target_t_y / denominator if denominator else raw_anchor_t_y


def _activity_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    params = payload["params"]
    reconciliation_mode = _param_text(params, "DSP_RECONCILIATION_MODE")
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            c5k = payload["c5k"][key]
            c5l_a = payload["c5l_a"][key]
            c5l_d = payload["c5l_d"][key]
            active_target = _zero(c5k["active_total_liquid_steel_target_site_t_y"])
            dsp_output = _zero(c5l_d["dsp_output_site_t_y"])
            raw_anchor = 1_500_000.0
            scaled_anchor = _scaled_anchor(config, active_target, params)
            bof_ls = _zero(c5k["active_bof_liquid_steel_target_site_t_y"])
            eaf_ls = _zero(c5k["active_eaf_liquid_steel_target_site_t_y"])
            c0_share = dsp_output / bof_ls if config == C0 and bof_ls else 0.0
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "DSP_ACTIVE": _bool(dsp_output > TOL_T),
                    "DSP_output_basis": "t DSP hot-rolled coil",
                    "DSP_reconciliation_mode": reconciliation_mode,
                    "C5l_d_DSP_placeholder_site_t_y": dsp_output,
                    "DSP_active_output_site_t_y": dsp_output,
                    "DSP_placeholder_replaced_by_actual_output": "true",
                    "DSP_output_double_counts_placeholder": "false",
                    "DSP_raw_anchor_site_t_y": raw_anchor,
                    "DSP_raw_anchor_gap_site_t_y": dsp_output - raw_anchor,
                    "DSP_scaled_anchor_site_t_y": scaled_anchor,
                    "DSP_scaled_anchor_gap_site_t_y": dsp_output - scaled_anchor,
                    "raw_anchor_used_as_hourly_constraint": "false",
                    "active_total_liquid_steel_target_site_t_y": active_target,
                    "BOF_liquid_steel_site_t_y": bof_ls,
                    "EAF_liquid_steel_site_t_y": eaf_ls,
                    "BOF_plus_EAF_total_site_t_y": bof_ls + eaf_ls,
                    "BOF_plus_EAF_total_matches_C5k_target": _bool(abs((bof_ls + eaf_ls) - active_target) <= TOL_T),
                    "C5l_a_dsp_ls_share_legacy": c5l_a["dsp_ls_share"],
                    "C0_OSF_to_DSP_route_share_anchor": 0.20 if config == C0 else "",
                    "C0_OSF_to_DSP_route_share_observed": c0_share if config == C0 else "",
                    "C0_OSF_to_DSP_route_share_status": "pass" if config == C0 and abs(c0_share - 0.20) <= 1e-9 else ("not_applicable" if config != C0 else "warning"),
                    "C1_EAF_route_share_anchor": 0.90 if config == C1 else "",
                    "C1_EAF_route_share_observed": "",
                    "C1_EAF_route_share_status": "route_origin_not_fully_tracked" if config == C1 else "not_applicable",
                    "DSP_route_origin_tracking_status": "pooled_liquid_steel_interface_origin_not_fully_tracked" if config == C1 else "BOF_OSF_only_route_context",
                    "DSP_ROUTE_ORIGIN_NOT_FULLY_TRACKED_CAVEAT": _bool(config == C1 and dsp_output > TOL_T),
                    "C5k_route_split_preserved": "true",
                    "C5l_d_base_0_50_preserved": _bool(c5l_d["active_cap_case"] == "base_0_50"),
                }
            )
    return rows


def _material_energy_rows(payload: dict[str, Any], activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = payload["params"]
    ls_rate = _param_float(params, "DSP_LIQUID_STEEL_INPUT_T_PER_T_COIL_BASE")
    electricity = _param_float(params, "DSP_ELECTRICITY_MWH_PER_T_COIL_BASE")
    scrap_rate = _param_float(params, "DSP_INTERNAL_SCRAP_LOSS_T_PER_T_COIL_DERIVED")
    co2_rate = _param_float(params, "DSP_DIRECT_CO2_T_PER_T_COIL_BASE")
    rows: list[dict[str, Any]] = []
    for act in activity:
        output = _zero(act["DSP_active_output_site_t_y"])
        ls_input = output * ls_rate
        scrap_loss = output * scrap_rate
        # The legacy C5 placeholder was net DSP coil output. C5o_c exposes the
        # gross liquid-steel requirement and the internal scrap/loss separately.
        routed_liquid_steel_available = output + scrap_loss
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": act["configuration"],
                "horizon_hours": act["horizon_hours"],
                "status": "development_only",
                "thesis_usability": "false",
                "DSP_ACTIVE": act["DSP_ACTIVE"],
                "DSP_output_site_t_y": output,
                "DSP_liquid_steel_input_t_per_t_coil": ls_rate,
                "DSP_liquid_steel_input_site_t_y": ls_input,
                "DSP_available_routed_liquid_steel_for_DSP_site_t_y": routed_liquid_steel_available,
                "DSP_available_routed_liquid_steel_basis": "C5l_d_DSP_output_placeholder_plus_reported_internal_scrap_loss",
                "DSP_liquid_steel_exceeds_available_routed_steel": _bool(ls_input > routed_liquid_steel_available + TOL_T),
                "DSP_liquid_steel_exceeds_total_liquid_steel_pool": _bool(ls_input > _zero(act["BOF_plus_EAF_total_site_t_y"]) + TOL_T),
                "DSP_hidden_liquid_steel_source_site_t_y": 0.0,
                "DSP_internal_scrap_loss_t_per_t_coil": scrap_rate,
                "DSP_internal_scrap_loss_site_t_y": scrap_loss,
                "DSP_internal_scrap_recycled_topology": "true",
                "DSP_internal_scrap_handling_status": "reporting_only_not_connected_to_EAF_scrap_loop",
                "DSP_internal_scrap_used_as_free_EAF_input": "false",
                "DSP_electricity_MWh_e_y": output * electricity,
                "DSP_electricity_TWh_e_y": output * electricity / 1_000_000.0,
                "DSP_electricity_price_responsive": "false",
                "DSP_FUEL_GAS_BASE_ACTIVE": "false",
                "DSP_tunnel_furnace_present": "true",
                "DSP_tunnel_furnace_heat_status": "deferred_no_active_heat_coefficient",
                "DSP_WAG_consumption_MWh_y": 0.0,
                "DSP_NG_consumption_GJ_y": 0.0,
                "DSP_NG_consumption_PJ_y": 0.0,
                "DSP_WAG_consumption_active_without_heat_coefficient": "false",
                "DSP_NG_consumption_active_without_heat_coefficient": "false",
                "DSP_direct_CO2_mode": "fuel-derived only",
                "DSP_direct_CO2_t_per_t_coil": co2_rate,
                "DSP_direct_CO2_t_y": output * co2_rate,
                "DSP_direct_CO2_double_count": "false",
                "DSP_direct_CO2_zero_accounting_caveat": _bool(output > TOL_T),
                "DSP_mFRR_provider_base": "false",
                "DSP_output_counts_toward_final_product_target": "true",
            }
        )
    return rows


def _downstream_rows(payload: dict[str, Any], activity: list[dict[str, Any]], material: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mat_by_key = _by_key_like(material)
    rows: list[dict[str, Any]] = []
    for act in activity:
        key = (act["configuration"], int(act["horizon_hours"]))
        mat = mat_by_key[key]
        c5l_d = payload["c5l_d"][key]
        c5o_b = payload["c5o_b_downstream"][key]
        dsp = _zero(mat["DSP_output_site_t_y"])
        hsm = _zero(c5l_d["hsm_output_site_t_y"])
        final_proxy = _zero(c5l_d["active_final_product_proxy_site_t_y"])
        target = _zero(act["active_total_liquid_steel_target_site_t_y"])
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": act["configuration"],
                "horizon_hours": act["horizon_hours"],
                "status": "development_only",
                "thesis_usability": "false",
                "DSP_output_site_t_y": dsp,
                "HSM_WBW_output_site_t_y": hsm,
                "DSP_plus_HSM_final_product_proxy_site_t_y": dsp + hsm,
                "C5l_d_active_final_product_proxy_site_t_y": final_proxy,
                "DSP_output_in_final_product_ledger": _bool(abs((dsp + hsm) - final_proxy) <= 1e-3),
                "DSP_output_not_added_on_top_of_placeholder": "true",
                "DSP_placeholder_replacement_status": "replaced_C5l_d_DSP_placeholder_with_explicit_DSP_process_layer",
                "active_total_liquid_steel_target_site_t_y": target,
                "final_product_proxy_minus_active_target_t_y": final_proxy - target,
                "raw_MER_HSM_anchor_t_y": c5l_d["raw_MER_HSM_anchor_t_y"],
                "raw_MER_DSP_anchor_t_y": c5l_d["raw_MER_DSP_anchor_t_y"],
                "raw_MER_DSP_gap_t_y": c5l_d["raw_MER_DSP_gap_t_y"],
                "raw_MER_final_product_anchor_t_y": 6_900_000.0 if act["configuration"] == C0 else 7_000_000.0,
                "raw_MER_final_product_gap_t_y": final_proxy - (6_900_000.0 if act["configuration"] == C0 else 7_000_000.0),
                "BOF_plus_EAF_total_site_t_y": act["BOF_plus_EAF_total_site_t_y"],
                "BOF_plus_EAF_total_matches_C5k_target": act["BOF_plus_EAF_total_matches_C5k_target"],
                "EAF_output_remains_connected_downstream": c5o_b["EAF_output_connected_to_downstream"],
                "HSM_heat_case": c5l_d["cap_case"],
                "HSM_WBW_C5l_d_base_0_50_preserved": _bool(c5l_d["cap_case"] == "base_0_50" and c5l_d["active_cap_case"] == "base_0_50"),
                "upstream_downstream_mismatch_after_DSP": "false",
            }
        )
    return rows


def _modelled_total_delta_rows(payload: dict[str, Any], material: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mat in material:
        key = (mat["configuration"], int(mat["horizon_hours"]))
        c5o_b = payload["c5o_b_totals"][key]
        before_elec = _zero(c5o_b["process_electricity_after_EAF_MWh_e_y"])
        dsp_elec = _zero(mat["DSP_electricity_MWh_e_y"])
        before_co2 = _zero(c5o_b["diagnostic_CO2_after_EAF_t_y"])
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": mat["configuration"],
                "horizon_hours": mat["horizon_hours"],
                "status": "development_only_scope_expansion_due_to_DSP_electricity_accounting",
                "thesis_usability": "false",
                "process_electricity_before_DSP_MWh_e_y": before_elec,
                "DSP_electricity_delta_MWh_e_y": dsp_elec,
                "process_electricity_after_DSP_MWh_e_y": before_elec + dsp_elec,
                "diagnostic_CO2_before_DSP_t_y": before_co2,
                "DSP_direct_CO2_delta_t_y": _zero(mat["DSP_direct_CO2_t_y"]),
                "diagnostic_CO2_after_DSP_t_y": before_co2 + _zero(mat["DSP_direct_CO2_t_y"]),
                "DSP_direct_CO2_mode": mat["DSP_direct_CO2_mode"],
                "DSP_direct_CO2_zero_accounting_caveat": mat["DSP_direct_CO2_zero_accounting_caveat"],
                "DSP_NG_delta_PJ_y": 0.0,
                "DSP_WAG_consumption_delta_MWh_y": 0.0,
                "WAG_invariant_status_after_DSP": c5o_b["WAG_invariant_status_after_EAF"],
                "LHV_consistency_status_after_DSP": c5o_b["LHV_consistency_status_after_EAF"],
                "CO2_guard_status_after_DSP": c5o_b["EAF_CO2_guard_status_after_EAF"],
                "HSM_heat_case": c5o_b["HSM_heat_case"],
            }
        )
    return rows


def _plant_kpi_rows(material: list[dict[str, Any]], downstream: list[dict[str, Any]]) -> list[dict[str, Any]]:
    down_by_key = _by_key_like(downstream)
    rows: list[dict[str, Any]] = []
    for mat in material:
        key = (mat["configuration"], int(mat["horizon_hours"]))
        down = down_by_key[key]
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": mat["configuration"],
                "horizon_hours": mat["horizon_hours"],
                "plant_or_controller": "DSP",
                "active_status": "active" if mat["DSP_ACTIVE"] == "true" else "inactive",
                "activity_driver_name": "DSP_hot_rolled_coil_output",
                "activity_driver_value": mat["DSP_output_site_t_y"],
                "material_inputs_summary": f"liquid_steel_t_y={_fmt(_zero(mat['DSP_liquid_steel_input_site_t_y']))}",
                "material_outputs_summary": f"DSP_coil_t_y={_fmt(_zero(mat['DSP_output_site_t_y']))};internal_scrap_t_y={_fmt(_zero(mat['DSP_internal_scrap_loss_site_t_y']))}",
                "electricity_MWh_or_TWh": mat["DSP_electricity_TWh_e_y"],
                "steam_t_or_kt": "not_applicable",
                "oxygen_t_or_Nm3": "not_applicable",
                "thermal_fuel_TWh_or_PJ": "fuel_gas_inactive",
                "WAG_generated_by_carrier": "none",
                "WAG_consumed_by_carrier": "none",
                "NG_consumed": mat["DSP_NG_consumption_PJ_y"],
                "CO2_diagnostic": mat["DSP_direct_CO2_t_y"],
                "included_in_totals_flags": "electricity=true;diagnostic_CO2=true_zero;NG=false;WAG=false",
                "downstream_interface_status": down["DSP_placeholder_replacement_status"],
                "caveat/status": "development_only_not_thesis_approved",
            }
        )
    return rows


REDFLAG_NAMES = (
    "DSP_ACTIVE_WITHOUT_LIQUID_STEEL_INPUT",
    "DSP_HIDDEN_LIQUID_STEEL_SOURCE",
    "DSP_OUTPUT_DOUBLE_COUNTS_PLACEHOLDER",
    "DSP_OUTPUT_NOT_IN_FINAL_PRODUCT_LEDGER",
    "DSP_LIQUID_STEEL_EXCEEDS_AVAILABLE_ROUTED_STEEL",
    "DSP_BREAKS_C1_TOTAL_PRODUCTION",
    "DSP_BREAKS_HSM_WBW_C5L_D_BASE",
    "DSP_WAG_CONSUMPTION_ACTIVE_WITHOUT_HEAT_COEFFICIENT",
    "DSP_NG_CONSUMPTION_ACTIVE_WITHOUT_HEAT_COEFFICIENT",
    "DSP_MFRR_ENABLED_IN_BASE",
    "DSP_DIRECT_CO2_DOUBLE_COUNT",
    "DSP_ELECTRICITY_PRICE_RESPONSIVE_IN_BASE",
    "DSP_INTERNAL_SCRAP_USED_AS_FREE_EAF_INPUT",
    "UPSTREAM_DOWNSTREAM_MISMATCH_AFTER_DSP",
)

CAVEAT_NAMES = (
    "DSP_ROUTE_ORIGIN_NOT_FULLY_TRACKED_CAVEAT",
    "DSP_TUNNEL_FURNACE_HEAT_DEFERRED_CAVEAT",
    "DSP_FUEL_GAS_NOT_MODELLED_CAVEAT",
    "DSP_DIRECT_CO2_ZERO_ONLY_BECAUSE_FUEL_INACTIVE",
    "DSP_INTERNAL_SCRAP_REPORTING_ONLY",
    "DSP_NOT_THESIS_APPROVED",
)


def _health_rows(
    activity: list[dict[str, Any]],
    material: list[dict[str, Any]],
    downstream: list[dict[str, Any]],
    totals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    act_by_key = _by_key_like(activity)
    mat_by_key = _by_key_like(material)
    down_by_key = _by_key_like(downstream)
    total_by_key = _by_key_like(totals)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            act = act_by_key[key]
            mat = mat_by_key[key]
            down = down_by_key[key]
            total = total_by_key[key]
            dsp_active = mat["DSP_ACTIVE"] == "true"
            flags = {
                "DSP_ACTIVE_WITHOUT_LIQUID_STEEL_INPUT": dsp_active and _zero(mat["DSP_liquid_steel_input_site_t_y"]) <= TOL_T,
                "DSP_HIDDEN_LIQUID_STEEL_SOURCE": _zero(mat["DSP_hidden_liquid_steel_source_site_t_y"]) > TOL_T,
                "DSP_OUTPUT_DOUBLE_COUNTS_PLACEHOLDER": act["DSP_output_double_counts_placeholder"] == "true",
                "DSP_OUTPUT_NOT_IN_FINAL_PRODUCT_LEDGER": down["DSP_output_in_final_product_ledger"] != "true",
                "DSP_LIQUID_STEEL_EXCEEDS_AVAILABLE_ROUTED_STEEL": mat["DSP_liquid_steel_exceeds_available_routed_steel"] == "true",
                "DSP_BREAKS_C1_TOTAL_PRODUCTION": config == C1 and act["BOF_plus_EAF_total_matches_C5k_target"] != "true",
                "DSP_BREAKS_HSM_WBW_C5L_D_BASE": down["HSM_WBW_C5l_d_base_0_50_preserved"] != "true",
                "DSP_WAG_CONSUMPTION_ACTIVE_WITHOUT_HEAT_COEFFICIENT": mat["DSP_WAG_consumption_active_without_heat_coefficient"] == "true",
                "DSP_NG_CONSUMPTION_ACTIVE_WITHOUT_HEAT_COEFFICIENT": mat["DSP_NG_consumption_active_without_heat_coefficient"] == "true",
                "DSP_MFRR_ENABLED_IN_BASE": mat["DSP_mFRR_provider_base"] == "true",
                "DSP_DIRECT_CO2_DOUBLE_COUNT": mat["DSP_direct_CO2_double_count"] == "true",
                "DSP_ELECTRICITY_PRICE_RESPONSIVE_IN_BASE": mat["DSP_electricity_price_responsive"] == "true",
                "DSP_INTERNAL_SCRAP_USED_AS_FREE_EAF_INPUT": mat["DSP_internal_scrap_used_as_free_EAF_input"] == "true",
                "UPSTREAM_DOWNSTREAM_MISMATCH_AFTER_DSP": down["upstream_downstream_mismatch_after_DSP"] == "true",
            }
            caveats = {
                "DSP_ROUTE_ORIGIN_NOT_FULLY_TRACKED_CAVEAT": act["DSP_ROUTE_ORIGIN_NOT_FULLY_TRACKED_CAVEAT"] == "true",
                "DSP_TUNNEL_FURNACE_HEAT_DEFERRED_CAVEAT": dsp_active,
                "DSP_FUEL_GAS_NOT_MODELLED_CAVEAT": dsp_active,
                "DSP_DIRECT_CO2_ZERO_ONLY_BECAUSE_FUEL_INACTIVE": mat["DSP_direct_CO2_zero_accounting_caveat"] == "true",
                "DSP_INTERNAL_SCRAP_REPORTING_ONLY": dsp_active,
                "DSP_NOT_THESIS_APPROVED": dsp_active,
            }
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "DSP_active": mat["DSP_ACTIVE"],
                    "DSP_output_site_t_y": mat["DSP_output_site_t_y"],
                    "DSP_raw_anchor_site_t_y": act["DSP_raw_anchor_site_t_y"],
                    "DSP_raw_anchor_gap_site_t_y": act["DSP_raw_anchor_gap_site_t_y"],
                    "DSP_scaled_anchor_site_t_y": act["DSP_scaled_anchor_site_t_y"],
                    "DSP_scaled_anchor_gap_site_t_y": act["DSP_scaled_anchor_gap_site_t_y"],
                    "DSP_liquid_steel_input_site_t_y": mat["DSP_liquid_steel_input_site_t_y"],
                    "DSP_electricity_TWh_e_y": mat["DSP_electricity_TWh_e_y"],
                    "DSP_internal_scrap_loss_site_t_y": mat["DSP_internal_scrap_loss_site_t_y"],
                    "DSP_internal_scrap_handling_status": mat["DSP_internal_scrap_handling_status"],
                    "DSP_WAG_consumption_MWh_y": mat["DSP_WAG_consumption_MWh_y"],
                    "DSP_NG_consumption_PJ_y": mat["DSP_NG_consumption_PJ_y"],
                    "DSP_direct_CO2_t_y": mat["DSP_direct_CO2_t_y"],
                    "DSP_direct_CO2_mode": mat["DSP_direct_CO2_mode"],
                    "C0_OSF_to_DSP_route_share_observed": act["C0_OSF_to_DSP_route_share_observed"],
                    "C0_OSF_to_DSP_route_share_status": act["C0_OSF_to_DSP_route_share_status"],
                    "C1_EAF_route_share_status": act["C1_EAF_route_share_status"],
                    "DSP_route_origin_tracking_status": act["DSP_route_origin_tracking_status"],
                    "DSP_plus_HSM_final_product_proxy_site_t_y": down["DSP_plus_HSM_final_product_proxy_site_t_y"],
                    "final_product_proxy_minus_active_target_t_y": down["final_product_proxy_minus_active_target_t_y"],
                    "raw_MER_final_product_gap_t_y": down["raw_MER_final_product_gap_t_y"],
                    "DSP_output_in_final_product_ledger": down["DSP_output_in_final_product_ledger"],
                    "DSP_placeholder_replacement_status": down["DSP_placeholder_replacement_status"],
                    "HSM_heat_case": down["HSM_heat_case"],
                    "process_electricity_after_DSP_MWh_e_y": total["process_electricity_after_DSP_MWh_e_y"],
                    "diagnostic_CO2_after_DSP_t_y": total["diagnostic_CO2_after_DSP_t_y"],
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


def _compact_table_rows(activity: list[dict[str, Any]], material: list[dict[str, Any]], downstream: list[dict[str, Any]], health: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mat_by_key = _by_key_like(material)
    down_by_key = _by_key_like(downstream)
    health_by_key = _by_key_like(health)
    rows: list[dict[str, Any]] = []
    for act in activity:
        key = (act["configuration"], int(act["horizon_hours"]))
        mat = mat_by_key[key]
        down = down_by_key[key]
        health_row = health_by_key[key]
        rows.append(
            {
                "configuration": act["configuration"],
                "horizon_hours": act["horizon_hours"],
                "DSP_active": mat["DSP_ACTIVE"],
                "DSP_output_Mt_y": _zero(mat["DSP_output_site_t_y"]) / 1_000_000.0,
                "DSP_raw_anchor_gap_Mt_y": _zero(act["DSP_raw_anchor_gap_site_t_y"]) / 1_000_000.0,
                "DSP_scaled_anchor_gap_Mt_y": _zero(act["DSP_scaled_anchor_gap_site_t_y"]) / 1_000_000.0,
                "DSP_liquid_steel_input_Mt_y": _zero(mat["DSP_liquid_steel_input_site_t_y"]) / 1_000_000.0,
                "DSP_electricity_TWh_e_y": mat["DSP_electricity_TWh_e_y"],
                "DSP_internal_scrap_loss_Mt_y": _zero(mat["DSP_internal_scrap_loss_site_t_y"]) / 1_000_000.0,
                "DSP_WAG_MWh_y": mat["DSP_WAG_consumption_MWh_y"],
                "DSP_NG_PJ_y": mat["DSP_NG_consumption_PJ_y"],
                "DSP_direct_CO2_t_y": mat["DSP_direct_CO2_t_y"],
                "C0_route_share": act["C0_OSF_to_DSP_route_share_observed"],
                "C1_EAF_route_share_status": act["C1_EAF_route_share_status"],
                "final_product_proxy_Mt_y": _zero(down["DSP_plus_HSM_final_product_proxy_site_t_y"]) / 1_000_000.0,
                "placeholder_replacement_status": down["DSP_placeholder_replacement_status"],
                "failure_count": health_row["failure_count"],
                "caveats": health_row["caveats"],
            }
        )
    return rows


def _stage_gate(redflags: list[dict[str, Any]], activity: list[dict[str, Any]], material: list[dict[str, Any]], downstream: list[dict[str, Any]]) -> dict[str, Any]:
    failure_count = sum(int(row["failure_count"]) for row in redflags)
    c0_activity = next(row for row in activity if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    c1_activity = next(row for row in activity if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    c1_material = next(row for row in material if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    c1_downstream = next(row for row in downstream if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    return {
        "stage_id": STAGE,
        "decision": "pass_development_dsp_downstream_physical_layer" if failure_count == 0 else "fail_development_dsp_downstream_physical_layer",
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "output_directory": _rel(C5O_C_DIR),
        "failure_count": failure_count,
        "C0_24h_DSP_output_site_t_y": _zero(c0_activity["DSP_active_output_site_t_y"]),
        "C0_24h_OSF_to_DSP_route_share_observed": _zero(c0_activity["C0_OSF_to_DSP_route_share_observed"]),
        "C1_24h_DSP_output_site_t_y": _zero(c1_activity["DSP_active_output_site_t_y"]),
        "C1_24h_DSP_liquid_steel_input_site_t_y": _zero(c1_material["DSP_liquid_steel_input_site_t_y"]),
        "C1_24h_DSP_electricity_TWh_e_y": _zero(c1_material["DSP_electricity_TWh_e_y"]),
        "C1_24h_DSP_internal_scrap_loss_site_t_y": _zero(c1_material["DSP_internal_scrap_loss_site_t_y"]),
        "C1_24h_final_product_proxy_site_t_y": _zero(c1_downstream["DSP_plus_HSM_final_product_proxy_site_t_y"]),
        "DSP_WAG_consumption_active": False,
        "DSP_NG_consumption_active": False,
        "DSP_mFRR_provider_base": False,
        "DSP_direct_CO2_mode": "fuel-derived only",
        "validation_anchors_used_as_hourly_constraints": False,
        "hidden_liquid_steel_source_active": False,
    }


def _write_outputs() -> dict[str, Any]:
    C5O_C_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(C5O_C_DIR / "s4_4c5o_c_dsp_development_input_rows.csv", _dsp_dev_rows())
    _write_csv(C5O_C_DIR / "s4_4c5o_c_dsp_validation_anchors.csv", _validation_anchor_rows())

    payload = _source_payload()
    activity = _activity_rows(payload)
    material = _material_energy_rows(payload, activity)
    downstream = _downstream_rows(payload, activity, material)
    totals = _modelled_total_delta_rows(payload, material)
    kpis = _plant_kpi_rows(material, downstream)
    health = _health_rows(activity, material, downstream, totals)
    redflags = _redflag_rows(health)
    compact = _compact_table_rows(activity, material, downstream, health)
    gate = _stage_gate(redflags, activity, material, downstream)

    _write_json(C5O_C_DIR / "s4_4c5o_c_stage_gate.json", gate)
    _write_csv(
        C5O_C_DIR / "s4_4c5o_c_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5O_C_DIR / "s4_4c5o_c_dsp_activity_report.csv", activity)
    _write_csv(C5O_C_DIR / "s4_4c5o_c_dsp_material_energy_ledger.csv", material)
    _write_csv(C5O_C_DIR / "s4_4c5o_c_downstream_integration_dashboard.csv", downstream)
    _write_csv(C5O_C_DIR / "s4_4c5o_c_modelled_totals_delta.csv", totals)
    _write_csv(C5O_C_DIR / "s4_4c5o_c_plant_kpi_table.csv", kpis)
    _write_csv(C5O_C_DIR / "s4_4c5o_c_compact_healthcheck.csv", health)
    _write_csv(C5O_C_DIR / "s4_4c5o_c_red_flags.csv", redflags)
    _write_csv(C5O_C_DIR / "s4_4c5o_c_compact_table_for_chat.csv", compact)
    _write_json(
        C5O_C_DIR / "s4_4c5o_c_dsp_downstream_physical_layer_report.json",
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
                "DSP_fuel_gas_active": False,
                "DSP_WAG_or_NG_sink_active": False,
                "DSP_mFRR_provider": False,
                "DSP_direct_CO2_zero_is_accounting_convention": True,
            },
            "sections": {
                "activity": activity,
                "material_energy": material,
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
            "development_inputs": len(_dsp_dev_rows()),
            "activity": len(activity),
            "material_energy": len(material),
            "downstream": len(downstream),
            "health": len(health),
            "redflags": len(redflags),
        },
    }
    _write_json(C5O_C_DIR / "s4_4c5o_c_summary.json", summary)
    return summary


def run_s4_4c5o_c_dsp_downstream_physical_layer() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5o_c_dsp_downstream_physical_layer(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
