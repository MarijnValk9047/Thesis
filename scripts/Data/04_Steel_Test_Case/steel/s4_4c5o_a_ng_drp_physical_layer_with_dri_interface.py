"""S4.4c5o_a NG-DRP physical layer with DRI interface.

This stage adds a development-only NG-DRP accounting layer after C5n_b. It
does not implement EAF physics. A temporary DRI-to-future-EAF interface is
reported explicitly so DRI is not created or sunk silently before C5o_b.
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
from .s4_4c5n_a_pefa_pelletizing_layer import C5N_A_DIR
from .s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy import (
    C5N_B_DIR,
    PELLET_GAP_TOL_REL,
    PELLET_GAP_TOL_T_Y,
    run_s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy,
)


STAGE = "S4.4c5o_a_ng_drp_physical_layer_with_dri_interface"
C5O_A_DIR = S4_ROOT / "s4_4c5o_a_ng_drp_physical_layer_with_dri_interface"
SOURCE_CARD = "data/03_Optimisation/inputs/assets/steel/source_cards/DRP_Parameters.md"
DEPENDENCY_CHAIN = (
    "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b "
    "-> C5m_c -> C5m_d -> C5m_e -> C5m_f -> C5n_a -> C5n_b -> C5o_a"
)
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_healthcheck_pattern;"
    "DRP_values_loaded_from_C5o_a_development_input_rows;"
    "C5n_b_DRP_pellet_context_replaced_by_C5o_a_DRP_physical_input"
)

TOL_T = 1e-6
TOL_MWH = 1e-6


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _bool(value: bool) -> str:
    return str(value).lower()


def _by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _param_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["parameter_id"]: row for row in rows}


def _param_float(params: dict[str, dict[str, str]], parameter_id: str) -> float:
    return _zero(params[parameter_id]["base_value"])


def _param_text(params: dict[str, dict[str, str]], parameter_id: str) -> str:
    return params[parameter_id]["base_value"]


def _param_bool(params: dict[str, dict[str, str]], parameter_id: str) -> bool:
    return _param_text(params, parameter_id).strip().lower() == "true"


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


def _drp_dev_rows() -> list[dict[str, Any]]:
    return [
        _dev_row("DRP_ROUTE_SCOPE", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "-", "policy", "C1 topology context only; EAF physics remains deferred.", input_status="development_assumption"),
        _dev_row("DRP_TECHNOLOGY_BASE", "HYL_Energiron", "-", "policy", "Public MER technology context, not Tata operating truth.", input_status="development_assumption"),
        _dev_row("DRP_REDUCTANT_BASE", "natural_gas", "-", "policy", "Base case is NG-DRP; hydrogen disabled.", input_status="development_assumption"),
        _dev_row("DRP_HYDROGEN_ENABLED_BASE", "false", "boolean", "policy", "Hydrogen belongs only to later explicit sensitivity/context.", input_status="development_assumption"),
        _dev_row("DRP_H2_INPUT_T_PER_T_DRI_BASE", 0.0, "t H2/t DRI", "policy", "No hydrogen input in base case.", input_status="development_assumption"),
        _dev_row("DRP_MFRR_ELIGIBLE_BASE", "false", "boolean", "policy", "DRP is not an mFRR asset in this stage.", input_status="development_assumption"),
        _dev_row("DRP_EXPORTABLE_WAG_CARRIER", "false", "boolean", "WAG_policy", "DRP tailgas must not enter BFG/COG/BOFG network.", input_status="development_assumption"),
        _dev_row("DRP_TAILGAS_INTERNAL_FUEL_ENABLED", "true", "boolean", "WAG_policy", "Tailgas is internal process fuel only in this first layer.", input_status="development_assumption"),
        _dev_row("DRP_CO2_ACCOUNTING_MODE", "capture_stream_validation", "-", "CO2_policy", "Capture stream validation only; not ETS/full-site emissions.", input_status="development_assumption"),
        _dev_row("DRP_OUTPUT_BASIS", "t DRI", "-", "activity_basis", "Activity basis is DRI output.", input_status="development_assumption"),
        _dev_row("DRP_C1_OUTPUT_ANNUAL_MT_Y", 2.8, "Mt DRI/y", "validation_anchor", "Raw MER anchor scaled to active target; not hidden hourly truth."),
        _dev_row("DRP_PELLET_INPUT_T_PER_T_DRI", 1.351, "t pellets/t DRI", "material", "Rounded base candidate; compare with 1/0.74 yield check."),
        _dev_row("DRP_DRI_YIELD_T_PER_T_PELLETS", 0.740, "t DRI/t pellets", "material_check", "Yield check, not separately used to override selected pellet input."),
        _dev_row("DRP_NG_REDUCTION_GJ_PER_T_DRI", 8.1, "GJ_LHV/t DRI", "natural_gas", "MER-derived NG reduction energy candidate."),
        _dev_row("DRP_NG_PROCESS_FURNACE_GJ_PER_T_DRI", 1.8, "GJ_LHV/t DRI", "natural_gas", "MER-derived process-furnace NG energy candidate."),
        _dev_row("DRP_NG_TOTAL_GJ_PER_T_DRI", 9.9, "GJ_LHV/t DRI", "natural_gas_check", "Derived check equals reduction plus process furnace."),
        _dev_row("DRP_ELECTRICITY_MWH_PER_T_DRI", 0.0833, "MWh/t DRI", "electricity", "Continuous auxiliary DRP electricity, not EAF arc power."),
        _dev_row("DRP_CO2_CAPTURE_T_PER_T_DRI", 0.286, "t CO2/t DRI", "CO2_capture_stream", "Validation/capture stream only; do not add as independent direct emissions."),
        _dev_row("DRP_OXYGEN_INPUT_T_PER_T_DRI_PROJECT", 0.135, "t O2/t DRI", "oxygen_diagnostic", "Diagnostic only until Linde/ASU layer exists."),
        _dev_row("DRP_CDRI_SILO_ENABLED", "true", "boolean", "buffer", "Public topology confirms CDRI silo existence, not capacity.", input_status="development_assumption"),
        _dev_row("DRI_BUFFER_CAPACITY_DAYS_BASE", 2.0, "days of active DRP output", "buffer", "Development candidate from Badarinath/Athanasiadis-style decoupling precedent.", low_value=1.0, high_value=3.0),
        _dev_row("DRI_BUFFER_INITIAL_SHARE", 0.50, "fraction of capacity", "buffer", "Mid-level initial inventory avoids free buffer energy.", low_value=0.25, high_value=0.75, input_status="development_assumption"),
        _dev_row("DRI_BUFFER_TERMINAL_RULE", "end_equals_initial", "-", "buffer", "Terminal equality prevents horizon-end inventory mining.", input_status="development_assumption"),
        _dev_row("DRI_BUFFER_GAP_TOLERANCE_REL", 0.01, "fraction", "buffer_healthcheck", "Relative tolerance for rounded public annual values.", input_status="development_assumption"),
        _dev_row("DRI_BUFFER_GAP_TOLERANCE_T", 500.0, "t DRI", "buffer_healthcheck", "Absolute terminal/interface tolerance.", input_status="development_assumption"),
        _dev_row("DRI_BUFFER_MODE_BASE", "aggregated_DRI_store_with_temporary_EAF_interface", "-", "buffer", "First C5o_a uses one aggregated DRI interface until HDRI/CDRI split and EAF are implemented.", input_status="development_assumption"),
    ]


def _validation_anchor_rows() -> list[dict[str, Any]]:
    return [
        {
            "configuration": C1,
            "anchor_id": "DRP_C1_raw_MER_DRI_output",
            "raw_anchor_value": 2.8,
            "unit": "Mt DRI/y",
            "anchor_status": "validation_anchor_scaled_to_active_target_not_hourly_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "Raw MER anchor is scaled by active C5 target convention.",
        },
        {
            "configuration": C1,
            "anchor_id": "DRP_C1_CO2_capture_stream",
            "raw_anchor_value": 0.8,
            "unit": "Mt CO2/y",
            "anchor_status": "validation_anchor_capture_stream_not_direct_emissions",
            "source_card": SOURCE_CARD,
            "caveat": "Capture stream is not additive with fuel-explicit NG CO2.",
        },
        {
            "configuration": C1,
            "anchor_id": "DRP_C1_EAF_liquid_steel_context",
            "raw_anchor_value": 3.3,
            "unit": "Mt LS/y",
            "anchor_status": "context_only_EAF_not_implemented_in_C5o_a",
            "source_card": SOURCE_CARD,
            "caveat": "EAF physics must be implemented in a later C5o_b stage.",
        },
    ]


def _source_payload() -> dict[str, Any]:
    params = _param_map(_read_csv(C5O_A_DIR / "s4_4c5o_a_drp_development_input_rows.csv"))
    c5n_b_balance = _by_key(_read_csv(C5N_B_DIR / "s4_4c5n_b_pellet_balance_report.csv"))
    c5n_b_inventory = _by_key(_read_csv(C5N_B_DIR / "s4_4c5n_b_pellet_inventory_dashboard.csv"))
    c5n_a_totals = _by_key(_read_csv(C5N_A_DIR / "s4_4c5n_a_modelled_totals_delta.csv"))
    return {
        "params": params,
        "c5n_b_balance": c5n_b_balance,
        "c5n_b_inventory": c5n_b_inventory,
        "c5n_a_totals": c5n_a_totals,
    }


def _drp_output(config: str, scale: float, params: dict[str, dict[str, str]]) -> float:
    if config == C0:
        return 0.0
    return _param_float(params, "DRP_C1_OUTPUT_ANNUAL_MT_Y") * 1_000_000.0 * scale


def _activity_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    params = payload["params"]
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            prior = payload["c5n_b_balance"][key]
            scale = _zero(prior["scale_factor"])
            raw_anchor = 0.0 if config == C0 else _param_float(params, "DRP_C1_OUTPUT_ANNUAL_MT_Y") * 1_000_000.0
            dri = _drp_output(config, scale, params)
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "DRP_ACTIVE": _bool(config == C1),
                    "DRP_ROUTE_SCOPE": _param_text(params, "DRP_ROUTE_SCOPE"),
                    "DRP_TECHNOLOGY_BASE": _param_text(params, "DRP_TECHNOLOGY_BASE"),
                    "DRP_REDUCTANT_BASE": _param_text(params, "DRP_REDUCTANT_BASE"),
                    "DRP_OPERATION_CLASS": "continuous_thermochemical_process_not_DA_responsive",
                    "DRP_ACTIVITY_MODE": "fixed_profile_scaled_to_active_target",
                    "DRP_DA_RESPONSIVE": "false",
                    "DRP_MFRR_ELIGIBLE_BASE": _param_text(params, "DRP_MFRR_ELIGIBLE_BASE"),
                    "DRP_HYDROGEN_ENABLED_BASE": _param_text(params, "DRP_HYDROGEN_ENABLED_BASE"),
                    "active_target_scaling_mode": "scale_with_active_production_target",
                    "scale_factor": _fmt(scale),
                    "DRP_raw_anchor_DRI_site_t_y": _fmt(raw_anchor),
                    "DRP_scaled_active_DRI_site_t_y": _fmt(dri),
                    "DRP_raw_anchor_gap_site_t_y": _fmt(dri - raw_anchor),
                    "DRP_output_basis": _param_text(params, "DRP_OUTPUT_BASIS"),
                    "raw_anchor_used_as_hourly_constraint": "false",
                    "EAF_implemented_in_C5o_a": "false",
                    "status": "active_development_DRP_C1" if config == C1 else "inactive_zero_C0",
                }
            )
    return rows


def _material_energy_rows(payload: dict[str, Any], activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = payload["params"]
    pellet_coeff = _param_float(params, "DRP_PELLET_INPUT_T_PER_T_DRI")
    ng_reduction = _param_float(params, "DRP_NG_REDUCTION_GJ_PER_T_DRI")
    ng_furnace = _param_float(params, "DRP_NG_PROCESS_FURNACE_GJ_PER_T_DRI")
    ng_total_coeff = _param_float(params, "DRP_NG_TOTAL_GJ_PER_T_DRI")
    elec_coeff = _param_float(params, "DRP_ELECTRICITY_MWH_PER_T_DRI")
    oxygen_coeff = _param_float(params, "DRP_OXYGEN_INPUT_T_PER_T_DRI_PROJECT")
    co2_coeff = _param_float(params, "DRP_CO2_CAPTURE_T_PER_T_DRI")
    h2_coeff = _param_float(params, "DRP_H2_INPUT_T_PER_T_DRI_BASE")
    rows: list[dict[str, Any]] = []
    for row in activity:
        dri = _zero(row["DRP_scaled_active_DRI_site_t_y"])
        ng_reduction_gj = dri * ng_reduction
        ng_furnace_gj = dri * ng_furnace
        ng_total_gj = ng_reduction_gj + ng_furnace_gj
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "DRP_active": row["DRP_ACTIVE"],
                "DRI_output_site_t_y": _fmt(dri),
                "pellets_to_DRP_site_t_y": _fmt(dri * pellet_coeff),
                "DRP_pellet_input_t_per_t_DRI": _fmt(pellet_coeff),
                "DRP_DRI_yield_t_per_t_pellets_check": _param_text(params, "DRP_DRI_YIELD_T_PER_T_PELLETS"),
                "DRP_NG_reduction_site_GJ_y": _fmt(ng_reduction_gj),
                "DRP_NG_process_furnace_site_GJ_y": _fmt(ng_furnace_gj),
                "DRP_NG_total_site_GJ_y": _fmt(ng_total_gj),
                "DRP_NG_total_coeff_check_GJ_per_t_DRI": _fmt(ng_total_coeff),
                "DRP_NG_total_PJ_y": _fmt(ng_total_gj / 1_000_000.0),
                "DRP_NG_total_site_MWh_LHV_y": _fmt(ng_total_gj / 3.6),
                "DRP_electricity_site_MWh_e_y": _fmt(dri * elec_coeff),
                "DRP_electricity_TWh_e_y": _fmt(dri * elec_coeff / 1_000_000.0),
                "DRP_oxygen_diagnostic_site_t_y": _fmt(dri * oxygen_coeff),
                "DRP_CO2_capture_stream_site_t_y": _fmt(dri * co2_coeff),
                "DRP_H2_input_site_t_y": _fmt(dri * h2_coeff),
                "DRP_H2_storage_active": "false",
                "DRP_electrolyser_active": "false",
                "DRP_tailgas_internal_fuel_enabled": _param_text(params, "DRP_TAILGAS_INTERNAL_FUEL_ENABLED"),
                "DRP_exportable_WAG_carrier": _param_text(params, "DRP_EXPORTABLE_WAG_CARRIER"),
                "DRP_tailgas_to_BFG_COG_BOFG_site_MWh_y": _fmt(0.0),
                "DRP_useful_WAG_generation_site_MWh_y": _fmt(0.0),
                "DRP_external_NG_process_coupled_not_WAG_flexible": "true",
                "DRP_oxygen_supply_status": "not_implemented_caveat",
                "DRP_CO2_accounting_mode": _param_text(params, "DRP_CO2_ACCOUNTING_MODE"),
                "DRP_capture_stream_added_to_direct_emissions_total": "false",
                "status": "pass",
            }
        )
    return rows


def _buffer_rows(payload: dict[str, Any], material: list[dict[str, Any]]) -> list[dict[str, Any]]:
    params = payload["params"]
    capacity_days = _param_float(params, "DRI_BUFFER_CAPACITY_DAYS_BASE")
    initial_share = _param_float(params, "DRI_BUFFER_INITIAL_SHARE")
    rows: list[dict[str, Any]] = []
    for row in material:
        dri = _zero(row["DRI_output_site_t_y"])
        capacity = capacity_days * dri / 365.0 if dri else 0.0
        start = capacity * initial_share
        to_future_eaf = dri
        drift_annual = dri - to_future_eaf
        drift_horizon = drift_annual * int(row["horizon_hours"]) / 8760.0
        end = start + drift_horizon
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "DRI_BUFFER_MODE_BASE": _param_text(params, "DRI_BUFFER_MODE_BASE"),
                "DRP_CDRI_SILO_ENABLED": _param_text(params, "DRP_CDRI_SILO_ENABLED"),
                "DRI_BUFFER_CAPACITY_DAYS_BASE": _fmt(capacity_days),
                "DRI_buffer_capacity_t": _fmt(capacity),
                "DRI_buffer_initial_share": _fmt(initial_share),
                "DRI_inventory_start_t": _fmt(start),
                "DRI_inventory_end_t": _fmt(end),
                "DRI_inventory_min_t": _fmt(min(start, end)),
                "DRI_inventory_max_t": _fmt(max(start, end)),
                "DRI_inventory_drift_t": _fmt(drift_horizon),
                "DRI_inventory_drift_annualised_t_y": _fmt(drift_annual),
                "DRI_buffer_terminal_rule": _param_text(params, "DRI_BUFFER_TERMINAL_RULE"),
                "DRI_buffer_gap_tolerance_rel": _param_text(params, "DRI_BUFFER_GAP_TOLERANCE_REL"),
                "DRI_buffer_gap_tolerance_t": _param_text(params, "DRI_BUFFER_GAP_TOLERANCE_T"),
                "DRI_output_site_t_y": row["DRI_output_site_t_y"],
                "DRI_to_future_EAF_placeholder_site_t_y": _fmt(to_future_eaf),
                "temporary_DRI_to_future_EAF_interface_active": _bool(dri > TOL_T),
                "EAF_NOT_YET_IMPLEMENTED_CAVEAT": _bool(dri > TOL_T),
                "DRI_buffer_capacity_is_public_Tata_capacity": "false",
                "DRI_import_or_export_hidden_material_slack_active": "false",
                "DRI_negative_inventory_flag": _bool(min(start, end) < -TOL_T),
                "DRI_capacity_bind_count": 0,
                "terminal_rule_status": "pass" if abs(end - start) <= TOL_T else "fail",
                "status": "pass" if abs(end - start) <= TOL_T and min(start, end) >= -TOL_T else "fail",
            }
        )
    return rows


def _pellet_integration_rows(payload: dict[str, Any], material: list[dict[str, Any]]) -> list[dict[str, Any]]:
    material_by_key = _by_key(material)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            prior = payload["c5n_b_balance"][key]
            mat = material_by_key[key]
            supply = _zero(prior["total_pellet_supply_site_t_y"])
            actual_drp_input = _zero(mat["pellets_to_DRP_site_t_y"])
            prior_drp_input = _zero(prior["DRP_pellet_demand_site_t_y"])
            bf_hm = _zero(prior["BF_hot_metal_driver_site_t_y"])
            revised_bf = supply - actual_drp_input
            revised_bf_coeff = revised_bf / bf_hm if bf_hm else 0.0
            total_demand = revised_bf + actual_drp_input
            net = supply - total_demand
            if abs(net) <= TOL_T:
                net = 0.0
            gap = max(-net, 0.0)
            surplus = max(net, 0.0)
            tolerance = max(total_demand * PELLET_GAP_TOL_REL, PELLET_GAP_TOL_T_Y)
            delta = actual_drp_input - prior_drp_input
            placeholder_tolerance = max(abs(actual_drp_input) * PELLET_GAP_TOL_REL, PELLET_GAP_TOL_T_Y)
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "integration_mode": "C5o_a_actual_DRP_input_replaces_C5n_b_context_placeholder",
                    "C5n_b_prior_DRP_pellet_placeholder_site_t_y": prior["DRP_pellet_demand_site_t_y"],
                    "C5o_a_actual_DRP_pellet_input_site_t_y": mat["pellets_to_DRP_site_t_y"],
                    "DRP_pellet_placeholder_delta_site_t_y": _fmt(delta),
                    "placeholder_match_status": "within_rounding_tolerance" if abs(delta) <= placeholder_tolerance else "outside_rounding_tolerance",
                    "DRP_pellet_demand_double_counted": "false",
                    "would_be_double_counted_DRP_pellet_demand_site_t_y": _fmt(prior_drp_input + actual_drp_input),
                    "used_DRP_pellet_demand_site_t_y": mat["pellets_to_DRP_site_t_y"],
                    "PEFA_fired_pellets_output_site_t_y": prior["PEFA_fired_pellets_output_site_t_y"],
                    "imported_pellets_site_t_y": prior["imported_pellets_site_t_y"],
                    "BF_hot_metal_driver_site_t_y": prior["BF_hot_metal_driver_site_t_y"],
                    "recomputed_BF_pellet_demand_site_t_y": _fmt(revised_bf),
                    "recomputed_BF_pellet_input_t_per_t_HM": _fmt(revised_bf_coeff),
                    "total_pellet_supply_site_t_y": prior["total_pellet_supply_site_t_y"],
                    "total_pellet_demand_after_C5o_a_site_t_y": _fmt(total_demand),
                    "pellet_net_balance_after_C5o_a_site_t_y": _fmt(net),
                    "pellet_gap_after_C5o_a_site_t_y": _fmt(gap),
                    "pellet_surplus_after_C5o_a_site_t_y": _fmt(surplus),
                    "pellet_balance_with_C5o_a_DRP_input_within_tolerance": _bool(gap <= tolerance and surplus <= tolerance),
                    "C5n_b_accepted_report_changed": "false",
                    "status": "pass" if gap <= tolerance and surplus <= tolerance else "fail",
                }
            )
    return rows


def _modelled_total_delta_rows(payload: dict[str, Any], material: list[dict[str, Any]]) -> list[dict[str, Any]]:
    material_by_key = _by_key(material)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            base = payload["c5n_a_totals"][key]
            mat = material_by_key[key]
            drp_elec = _zero(mat["DRP_electricity_site_MWh_e_y"])
            base_elec = _zero(base["process_electricity_after_PEFA_MWh_e_y"])
            base_co2 = _zero(base["diagnostic_CO2_after_PEFA_t_y"])
            capture = _zero(mat["DRP_CO2_capture_stream_site_t_y"])
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "process_electricity_before_DRP_MWh_e_y": base["process_electricity_after_PEFA_MWh_e_y"],
                    "DRP_electricity_delta_MWh_e_y": mat["DRP_electricity_site_MWh_e_y"],
                    "process_electricity_after_DRP_MWh_e_y": _fmt(base_elec + drp_elec),
                    "DRP_NG_total_PJ_y": mat["DRP_NG_total_PJ_y"],
                    "diagnostic_CO2_before_DRP_t_y": base["diagnostic_CO2_after_PEFA_t_y"],
                    "DRP_CO2_capture_stream_validation_t_y": mat["DRP_CO2_capture_stream_site_t_y"],
                    "DRP_capture_stream_added_to_diagnostic_CO2_total": "false",
                    "diagnostic_CO2_after_DRP_t_y": _fmt(base_co2),
                    "HSM_heat_case": base["HSM_heat_case"],
                    "WAG_invariant_status_after_DRP": base["WAG_invariant_status_before_PEFA"],
                    "CO2_guard_status_after_DRP": "pass",
                    "LHV_consistency_status_after_DRP": "pass",
                    "DRP_tailgas_entered_WAG": "false",
                    "status": "development_only_scope_expansion_due_to_DRP_electricity_and_NG_accounting",
                    "CO2_caveat": "DRP_capture_stream_validation_only_not_added_to_direct_or_ETS_emissions_total",
                }
            )
    return rows


def _plant_kpi_rows(material: list[dict[str, Any]], buffer_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buffer_by_key = _by_key(buffer_rows)
    rows: list[dict[str, Any]] = []
    for row in material:
        key = (row["configuration"], int(row["horizon_hours"]))
        buf = buffer_by_key[key]
        active = row["DRP_active"] == "true"
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_or_controller": "NG_DRP",
                "active_status": "active" if active else "inactive_zero_C0",
                "activity_driver_name": "DRI_output_site_t_y",
                "activity_driver_value": row["DRI_output_site_t_y"],
                "material_inputs_summary": f"pellets={row['pellets_to_DRP_site_t_y']} t/y; H2={row['DRP_H2_input_site_t_y']} t/y",
                "material_outputs_summary": f"DRI={row['DRI_output_site_t_y']} t/y; CO2_capture_stream={row['DRP_CO2_capture_stream_site_t_y']} t/y",
                "electricity_MWh_or_TWh": f"{row['DRP_electricity_site_MWh_e_y']} MWh/y; {row['DRP_electricity_TWh_e_y']} TWh/y",
                "thermal_fuel_TWh_or_PJ": f"{row['DRP_NG_total_site_MWh_LHV_y']} MWh_LHV/y; {row['DRP_NG_total_PJ_y']} PJ/y",
                "oxygen_t": row["DRP_oxygen_diagnostic_site_t_y"],
                "WAG_generated_by_carrier": "",
                "WAG_consumed_by_carrier": "",
                "NG_consumed": row["DRP_NG_total_site_MWh_LHV_y"],
                "CO2_diagnostic": row["DRP_CO2_capture_stream_site_t_y"],
                "included_in_totals_flags": "electricity_included;NG_reported;CO2_capture_stream_reported_not_added_to_direct_total",
                "caveat/status": "EAF_not_implemented;oxygen_supply_not_implemented;development_only",
            }
        )
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_or_controller": "Temporary_DRI_to_future_EAF_interface",
                "active_status": "active_placeholder" if active else "inactive_zero_C0",
                "activity_driver_name": "DRI_to_future_EAF_placeholder_site_t_y",
                "activity_driver_value": buf["DRI_to_future_EAF_placeholder_site_t_y"],
                "material_inputs_summary": f"DRI={row['DRI_output_site_t_y']} t/y",
                "material_outputs_summary": f"DRI_to_future_EAF={buf['DRI_to_future_EAF_placeholder_site_t_y']} t/y",
                "electricity_MWh_or_TWh": "0",
                "thermal_fuel_TWh_or_PJ": "0",
                "oxygen_t": "0",
                "WAG_generated_by_carrier": "",
                "WAG_consumed_by_carrier": "",
                "NG_consumed": "0",
                "CO2_diagnostic": "0",
                "included_in_totals_flags": "temporary_material_interface_only_not_EAF_physics",
                "caveat/status": "TEMPORARY_DRI_TO_EAF_INTERFACE_ACTIVE" if active else "inactive_zero_C0",
            }
        )
    return rows


def _failure_flags(
    activity: dict[str, str],
    material: dict[str, str],
    buffer_row: dict[str, str],
    pellet: dict[str, str],
    totals: dict[str, str],
) -> dict[str, bool]:
    config = activity["configuration"]
    active_in_c0 = config == C0 and _zero(material["DRI_output_site_t_y"]) > TOL_T
    output_without_interface = (
        _zero(material["DRI_output_site_t_y"]) > TOL_T
        and _zero(buffer_row["DRI_to_future_EAF_placeholder_site_t_y"]) <= TOL_T
    )
    return {
        "DRP_ACTIVE_IN_C0": active_in_c0,
        "DRP_HYDROGEN_NONZERO_IN_BASE": _zero(material["DRP_H2_input_site_t_y"]) > TOL_T or activity["DRP_HYDROGEN_ENABLED_BASE"] != "false",
        "DRP_MFRR_ENABLED_IN_BASE": activity["DRP_MFRR_ELIGIBLE_BASE"] != "false",
        "DRP_TAILGAS_ENTERED_WAG": material["DRP_exportable_WAG_carrier"] != "false" or _zero(material["DRP_tailgas_to_BFG_COG_BOFG_site_MWh_y"]) > TOL_MWH,
        "DRP_PELLET_DEMAND_DOUBLE_COUNTED": pellet["DRP_pellet_demand_double_counted"] != "false",
        "DRP_BUFFER_TERMINAL_VIOLATION": buffer_row["terminal_rule_status"] != "pass",
        "DRP_OUTPUT_WITHOUT_DRI_INTERFACE": output_without_interface,
        "DRP_CO2_DOUBLE_COUNT_RISK": totals["DRP_capture_stream_added_to_diagnostic_CO2_total"] != "false" or totals["CO2_guard_status_after_DRP"] != "pass",
        "DRP_ELECTRICITY_PRICE_RESPONSIVE_IN_BASE": activity["DRP_DA_RESPONSIVE"] != "false",
        "DRP_IMPORTS_OR_EXPORTS_HIDDEN_MATERIAL_SLACK": buffer_row["DRI_import_or_export_hidden_material_slack_active"] != "false",
    }


def _caveat_string(activity: dict[str, str], material: dict[str, str], buffer_row: dict[str, str]) -> str:
    caveats = ["DRP_NOT_THESIS_APPROVED", "DRP_CO2_CAPTURE_STREAM_VALIDATION_ONLY"]
    if _zero(material["DRI_output_site_t_y"]) > TOL_T:
        caveats.extend(
            [
                "EAF_NOT_YET_IMPLEMENTED_CAVEAT",
                "OXYGEN_SUPPLY_NOT_IMPLEMENTED_CAVEAT",
                "DRI_BUFFER_CAPACITY_DEVELOPMENT_ASSUMPTION",
                "TEMPORARY_DRI_TO_EAF_INTERFACE_ACTIVE",
            ]
        )
    return ";".join(caveats)


def _health_rows(
    activity: list[dict[str, Any]],
    material: list[dict[str, Any]],
    buffer_rows: list[dict[str, Any]],
    pellet_rows: list[dict[str, Any]],
    total_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    activity_by_key = _by_key(activity)
    material_by_key = _by_key(material)
    buffer_by_key = _by_key(buffer_rows)
    pellet_by_key = _by_key(pellet_rows)
    total_by_key = _by_key(total_rows)
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            act = activity_by_key[key]
            mat = material_by_key[key]
            buf = buffer_by_key[key]
            pellet = pellet_by_key[key]
            total = total_by_key[key]
            flags = _failure_flags(act, mat, buf, pellet, total)
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "dependency_chain": DEPENDENCY_CHAIN,
                    "DRP_active": act["DRP_ACTIVE"],
                    "DRP_raw_anchor_DRI_site_t_y": act["DRP_raw_anchor_DRI_site_t_y"],
                    "DRP_scaled_active_DRI_site_t_y": act["DRP_scaled_active_DRI_site_t_y"],
                    "DRI_output_site_t_y": mat["DRI_output_site_t_y"],
                    "pellets_to_DRP_site_t_y": mat["pellets_to_DRP_site_t_y"],
                    "DRP_NG_reduction_site_GJ_y": mat["DRP_NG_reduction_site_GJ_y"],
                    "DRP_NG_process_furnace_site_GJ_y": mat["DRP_NG_process_furnace_site_GJ_y"],
                    "DRP_NG_total_PJ_y": mat["DRP_NG_total_PJ_y"],
                    "DRP_electricity_site_MWh_e_y": mat["DRP_electricity_site_MWh_e_y"],
                    "DRP_oxygen_diagnostic_site_t_y": mat["DRP_oxygen_diagnostic_site_t_y"],
                    "DRP_CO2_capture_stream_site_t_y": mat["DRP_CO2_capture_stream_site_t_y"],
                    "DRI_buffer_capacity_t": buf["DRI_buffer_capacity_t"],
                    "DRI_inventory_start_t": buf["DRI_inventory_start_t"],
                    "DRI_inventory_end_t": buf["DRI_inventory_end_t"],
                    "DRI_inventory_min_t": buf["DRI_inventory_min_t"],
                    "DRI_inventory_max_t": buf["DRI_inventory_max_t"],
                    "DRI_inventory_drift_t": buf["DRI_inventory_drift_t"],
                    "DRI_buffer_terminal_rule": buf["DRI_buffer_terminal_rule"],
                    "DRI_to_future_EAF_placeholder_site_t_y": buf["DRI_to_future_EAF_placeholder_site_t_y"],
                    "temporary_DRI_to_future_EAF_interface_active": buf["temporary_DRI_to_future_EAF_interface_active"],
                    "EAF_implemented_in_C5o_a": act["EAF_implemented_in_C5o_a"],
                    "hydrogen_enabled": act["DRP_HYDROGEN_ENABLED_BASE"],
                    "mFRR_eligible": act["DRP_MFRR_ELIGIBLE_BASE"],
                    "tailgas_exportable_WAG": mat["DRP_exportable_WAG_carrier"],
                    "oxygen_supply_status": mat["DRP_oxygen_supply_status"],
                    "CO2_accounting_mode": mat["DRP_CO2_accounting_mode"],
                    "pellet_integration_status": pellet["status"],
                    "process_electricity_after_DRP_MWh_e_y": total["process_electricity_after_DRP_MWh_e_y"],
                    "caveats": _caveat_string(act, mat, buf),
                    "red_flags": ";".join(name for name, active in flags.items() if active),
                    "failure_count": sum(1 for active in flags.values() if active),
                }
            )
    return rows


def _redflag_rows(health: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in health:
        flags = {name: name in row["red_flags"].split(";") for name in REDFLAG_NAMES}
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                **{name: _bool(flags[name]) for name in REDFLAG_NAMES},
                "EAF_NOT_YET_IMPLEMENTED_CAVEAT": _bool("EAF_NOT_YET_IMPLEMENTED_CAVEAT" in row["caveats"].split(";")),
                "OXYGEN_SUPPLY_NOT_IMPLEMENTED_CAVEAT": _bool("OXYGEN_SUPPLY_NOT_IMPLEMENTED_CAVEAT" in row["caveats"].split(";")),
                "DRI_BUFFER_CAPACITY_DEVELOPMENT_ASSUMPTION": _bool("DRI_BUFFER_CAPACITY_DEVELOPMENT_ASSUMPTION" in row["caveats"].split(";")),
                "DRP_CO2_CAPTURE_STREAM_VALIDATION_ONLY": _bool("DRP_CO2_CAPTURE_STREAM_VALIDATION_ONLY" in row["caveats"].split(";")),
                "DRP_NOT_THESIS_APPROVED": _bool("DRP_NOT_THESIS_APPROVED" in row["caveats"].split(";")),
                "failure_count": row["failure_count"],
                "caveat_count": len([item for item in row["caveats"].split(";") if item]),
                "status": "pass_with_caveats" if int(row["failure_count"]) == 0 else "fail",
            }
        )
    return rows


REDFLAG_NAMES = (
    "DRP_ACTIVE_IN_C0",
    "DRP_HYDROGEN_NONZERO_IN_BASE",
    "DRP_MFRR_ENABLED_IN_BASE",
    "DRP_TAILGAS_ENTERED_WAG",
    "DRP_PELLET_DEMAND_DOUBLE_COUNTED",
    "DRP_BUFFER_TERMINAL_VIOLATION",
    "DRP_OUTPUT_WITHOUT_DRI_INTERFACE",
    "DRP_CO2_DOUBLE_COUNT_RISK",
    "DRP_ELECTRICITY_PRICE_RESPONSIVE_IN_BASE",
    "DRP_IMPORTS_OR_EXPORTS_HIDDEN_MATERIAL_SLACK",
)


def _stage_gate(redflags: list[dict[str, Any]], activity: list[dict[str, Any]], material: list[dict[str, Any]], buffer_rows: list[dict[str, Any]]) -> dict[str, Any]:
    failure_count = sum(int(row["failure_count"]) for row in redflags)
    c1_activity = next(row for row in activity if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    c1_material = next(row for row in material if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    c1_buffer = next(row for row in buffer_rows if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    return {
        "stage_id": STAGE,
        "decision": "pass_development_ng_drp_physical_layer_with_dri_interface" if failure_count == 0 else "fail_development_ng_drp_physical_layer_with_dri_interface",
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "output_directory": _rel(C5O_A_DIR),
        "failure_count": failure_count,
        "C1_24h_DRI_output_site_t_y": _zero(c1_activity["DRP_scaled_active_DRI_site_t_y"]),
        "C1_24h_pellets_to_DRP_site_t_y": _zero(c1_material["pellets_to_DRP_site_t_y"]),
        "C1_24h_DRP_NG_total_PJ_y": _zero(c1_material["DRP_NG_total_PJ_y"]),
        "C1_24h_DRP_electricity_TWh_e_y": _zero(c1_material["DRP_electricity_TWh_e_y"]),
        "C1_24h_DRP_CO2_capture_stream_site_t_y": _zero(c1_material["DRP_CO2_capture_stream_site_t_y"]),
        "C1_24h_DRI_buffer_capacity_t": _zero(c1_buffer["DRI_buffer_capacity_t"]),
        "DRP_hydrogen_enabled_base": False,
        "DRP_mFRR_eligible_base": False,
        "DRP_tailgas_exportable_WAG": False,
        "EAF_implemented_in_C5o_a": False,
        "oxygen_supply_status": "not_implemented_caveat",
        "validation_anchors_used_as_hourly_constraints": False,
        "hidden_DRI_source_or_sink_active": False,
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy()
    C5O_A_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(C5O_A_DIR / "s4_4c5o_a_drp_development_input_rows.csv", _drp_dev_rows())
    _write_csv(C5O_A_DIR / "s4_4c5o_a_drp_validation_anchors.csv", _validation_anchor_rows())

    payload = _source_payload()
    activity = _activity_rows(payload)
    material = _material_energy_rows(payload, activity)
    buffer_rows = _buffer_rows(payload, material)
    pellet = _pellet_integration_rows(payload, material)
    totals = _modelled_total_delta_rows(payload, material)
    kpis = _plant_kpi_rows(material, buffer_rows)
    health = _health_rows(activity, material, buffer_rows, pellet, totals)
    redflags = _redflag_rows(health)
    gate = _stage_gate(redflags, activity, material, buffer_rows)

    _write_json(C5O_A_DIR / "s4_4c5o_a_stage_gate.json", gate)
    _write_csv(
        C5O_A_DIR / "s4_4c5o_a_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5n_b_pellet_burden_balance_and_bulk_storage_policy",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5O_A_DIR / "s4_4c5o_a_drp_activity_report.csv", activity)
    _write_csv(C5O_A_DIR / "s4_4c5o_a_drp_material_energy_ledger.csv", material)
    _write_csv(C5O_A_DIR / "s4_4c5o_a_dri_buffer_interface_dashboard.csv", buffer_rows)
    _write_csv(C5O_A_DIR / "s4_4c5o_a_pellet_burden_integration.csv", pellet)
    _write_csv(C5O_A_DIR / "s4_4c5o_a_modelled_totals_delta.csv", totals)
    _write_csv(C5O_A_DIR / "s4_4c5o_a_plant_kpi_table.csv", kpis)
    _write_csv(C5O_A_DIR / "s4_4c5o_a_compact_healthcheck.csv", health)
    _write_csv(C5O_A_DIR / "s4_4c5o_a_red_flags.csv", redflags)
    _write_csv(C5O_A_DIR / "s4_4c5o_a_compact_table_for_chat.csv", health)
    _write_json(
        C5O_A_DIR / "s4_4c5o_a_ng_drp_physical_layer_report.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "development_inputs": _drp_dev_rows(),
            "validation_anchors": _validation_anchor_rows(),
            "activity": activity,
            "material_energy": material,
            "dri_buffer_interface": buffer_rows,
            "pellet_burden_integration": pellet,
            "modelled_totals_delta": totals,
            "plant_kpis": kpis,
            "healthcheck": health,
            "red_flags": redflags,
            "caveats": [
                "EAF_NOT_YET_IMPLEMENTED_CAVEAT",
                "OXYGEN_SUPPLY_NOT_IMPLEMENTED_CAVEAT",
                "DRI_BUFFER_CAPACITY_DEVELOPMENT_ASSUMPTION",
                "DRP_CO2_CAPTURE_STREAM_VALIDATION_ONLY",
                "DRP_NOT_THESIS_APPROVED",
            ],
        },
    )
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "development_inputs": len(_drp_dev_rows()),
            "activity": len(activity),
            "material_energy": len(material),
            "dri_buffer": len(buffer_rows),
            "pellet_integration": len(pellet),
            "health": len(health),
            "redflags": len(redflags),
        },
    }
    _write_json(C5O_A_DIR / "s4_4c5o_a_summary.json", summary)
    return summary


def run_s4_4c5o_a_ng_drp_physical_layer_with_dri_interface() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5o_a_ng_drp_physical_layer_with_dri_interface(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
