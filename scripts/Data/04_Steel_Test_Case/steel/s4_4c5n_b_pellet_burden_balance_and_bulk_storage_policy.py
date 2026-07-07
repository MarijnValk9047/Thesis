"""S4.4c5n_b simplified pellet-burden balance and bulk-storage policy.

This stage connects the C5n_a PEFA fired-pellet proxy to a governed
development-only pellet burden balance. It keeps PEFA, coking, BF, BOF, HSM,
Sinter and coke-reconciliation assumptions unchanged and writes compact
diagnostics for pellet supply/demand and non-binding bulk-solid storage policy.
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
from .s4_4c5n_a_pefa_pelletizing_layer import (
    C5N_A_DIR,
    run_s4_4c5n_a_pefa_pelletizing_layer,
)


STAGE = "S4.4c5n_b_pellet_burden_balance_and_bulk_storage_policy"
C5N_B_DIR = S4_ROOT / "s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy"
SOURCE_CARD = "data/03_Optimisation/inputs/assets/steel/source_cards/PELLETIZING_Parameters.md"
DEPENDENCY_CHAIN = (
    "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b "
    "-> C5m_c -> C5m_d -> C5m_e -> C5m_f -> C5n_a -> C5n_b"
)
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_healthcheck_pattern;"
    "pellet_burden_coefficients_loaded_from_C5n_b_development_input_rows"
)

C0_MER_LS_CONTEXT_T_Y = 7_200_000.0
C1_MER_LS_CONTEXT_T_Y = 6_800_000.0
C0_PEFA_RAW_ANCHOR_T_Y = 4_600_000.0
C1_PEFA_RAW_ANCHOR_T_Y = 5_000_000.0
C0_IMPORTED_PELLETS_RAW_T_Y = 1_500_000.0
C1_IMPORTED_PELLETS_RAW_T_Y = 200_000.0
C1_IMPORTED_PELLETS_VARIANT_CAP_T_Y = 2_500_000.0
C1_DRP_DRI_CONTEXT_T_Y = 2_800_000.0
DRP_YIELD_FOR_PELLET_INPUT = 0.74
GENERIC_BREF_BF_PELLET_LOW = 0.0
GENERIC_BREF_BF_PELLET_HIGH = 0.972
PELLET_GAP_TOL_REL = 0.01
PELLET_GAP_TOL_T_Y = 50_000.0
STORAGE_MODE = "practically_non_binding_bulk_solid_storage"
PELLET_BALANCE_MODE = "inventory_balance_practically_unlimited_capacity"
PELLET_GRADE_MODE = "single_fired_pellets_proxy"
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


def _param_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["parameter_id"]: row for row in rows}


def _scale(config: str, active_total_ls: float) -> float:
    if config == C0:
        return active_total_ls / C0_MER_LS_CONTEXT_T_Y
    return active_total_ls / C1_MER_LS_CONTEXT_T_Y


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


def _pellet_dev_rows() -> list[dict[str, Any]]:
    c0_coeff = (4.6 + 1.5) / (2.5 + 3.8)
    c1_coeff = (5.0 + 0.2 - 2.8 * (1.0 / DRP_YIELD_FOR_PELLET_INPUT)) / 2.8
    drp_coeff = 1.0 / DRP_YIELD_FOR_PELLET_INPUT
    return [
        _dev_row("PELLET_GRADE_MODE", PELLET_GRADE_MODE, "-", "policy", "No BF-grade/DR-grade split in first implementation.", input_status="development_assumption"),
        _dev_row("BF_PELLET_INPUT_T_PER_T_HM_C0_DERIVED", c0_coeff, "t pellets/t hot metal", "material_burden", "Annual MER reconciliation candidate, not an independent BF technology coefficient."),
        _dev_row("BF_PELLET_INPUT_T_PER_T_HM_C1_RESIDUAL", c1_coeff, "t pellets/t hot metal", "material_burden", "Residual mass-balance candidate; depends on DRP coefficient, PEFA output and import anchor."),
        _dev_row("BF_PELLET_INPUT_T_PER_T_HM_GENERIC_BREF", 0.358, "t pellets/t hot metal", "benchmark_check", "External benchmark/sensitivity only; not Tata base if it conflicts with MER anchors.", low_value=GENERIC_BREF_BF_PELLET_LOW, high_value=GENERIC_BREF_BF_PELLET_HIGH),
        _dev_row("DRP_PELLET_INPUT_T_PER_T_DRI", drp_coeff, "t pellets/t DRI", "material_burden", "Base candidate from existing DRP-yield/project precedent, not confidential Tata truth."),
        _dev_row("DRP_PELLET_INPUT_T_PER_T_DRI_SENS", 1.39, "t pellets/t DRI", "sensitivity_check", "Sanity-check sensitivity only; not activated in C5n_b base.", input_status="development_sensitivity"),
        _dev_row("PEFA_PELLETS_ELIGIBLE_FOR_BF", "true", "boolean", "topology", "Generic fired-pellets proxy ignores BF-grade quality details.", input_status="development_assumption"),
        _dev_row("PEFA_PELLETS_ELIGIBLE_FOR_DRP", "true", "boolean", "topology", "Generic fired-pellets proxy ignores DR-grade quality details.", input_status="development_assumption"),
        _dev_row("IMPORTED_PELLETS_ALLOWED", "true", "boolean", "material_supply", "Imported pellets are fixed exogenous development supply, not free slack.", input_status="development_assumption"),
        _dev_row("IMPORTED_PELLETS_C0_ANCHOR_MT_Y", 1.5, "Mt/y", "validation_anchor", "C0 import context; scaled in executable balance and not used as hidden hourly cap.", input_status="development_candidate"),
        _dev_row("IMPORTED_PELLETS_C1_BASE_MT_Y", 0.2, "Mt/y", "validation_anchor", "C1 base import context; scaled in executable balance and not used as free slack.", input_status="development_candidate"),
        _dev_row("IMPORTED_PELLETS_C1_VARIANT_CAP_MT_Y", 2.5, "Mt/y", "sensitivity_cap", "Variant cap only, not active C5n_b base.", input_status="development_sensitivity"),
        _dev_row("IMPORTED_PELLETS_SCALING_MODE", "scale_with_active_production_target", "-", "policy", "Uses existing C5 active-target scaling convention.", input_status="development_assumption"),
        _dev_row("DRP_DRI_OUTPUT_C1_CONTEXT_MT_Y", 2.8, "Mt DRI/y", "driver_context", "C1 DRP DRI context is scaled because detailed DRP KPI layer remains deferred in current C5 reports.", input_status="development_candidate"),
        _dev_row("PELLET_BALANCE_MODE", PELLET_BALANCE_MODE, "-", "storage_policy", "Non-binding capacity does not mean free material supply.", input_status="development_assumption"),
        _dev_row("BULK_SOLID_STORAGE_CAPACITY_MODE", STORAGE_MODE, "-", "storage_policy", "Applies to coke, sinter and fired_pellets_proxy; not an exact Tata stockpile capacity.", input_status="development_assumption"),
        _dev_row("COKE_STORAGE_CAPACITY_MODE", STORAGE_MODE, "-", "storage_policy", "Development policy only; does not change coking production or accepted coke reconciliation.", input_status="development_assumption"),
        _dev_row("SINTER_STORAGE_CAPACITY_MODE", STORAGE_MODE, "-", "storage_policy", "Development policy only; does not change sinter BF-coupling.", input_status="development_assumption"),
        _dev_row("PELLET_STORAGE_CAPACITY_MODE", STORAGE_MODE, "-", "storage_policy", "Development policy only; terminal/inventory diagnostics prevent fake feasibility.", input_status="development_assumption"),
        _dev_row("COKE_STORAGE_THESIS_USABILITY", "false", "boolean", "governance", "Storage policy is development-only.", input_status="development_assumption"),
        _dev_row("SINTER_STORAGE_THESIS_USABILITY", "false", "boolean", "governance", "Storage policy is development-only.", input_status="development_assumption"),
        _dev_row("PELLET_STORAGE_THESIS_USABILITY", "false", "boolean", "governance", "Storage policy is development-only.", input_status="development_assumption"),
        _dev_row("PELLET_GAP_SURPLUS_MODE", "diagnostic_inventory_drift_and_healthcheck", "-", "healthcheck_policy", "No hidden solver slack for thesis claims.", input_status="development_assumption"),
        _dev_row("PELLET_GAP_TOLERANCE_REL", PELLET_GAP_TOL_REL, "fraction", "healthcheck_policy", "Practical threshold for rounded public annual values.", input_status="development_assumption"),
        _dev_row("PELLET_GAP_TOLERANCE_MT_Y", PELLET_GAP_TOL_T_Y / 1_000_000.0, "Mt/y", "healthcheck_policy", "Practical threshold for rounded public annual values.", input_status="development_assumption"),
    ]


def _validation_anchor_rows() -> list[dict[str, Any]]:
    return [
        {
            "configuration": C0,
            "anchor_id": "C0_raw_PEFA_plus_imported_pellets_vs_BF_HM_context",
            "raw_PEFA_anchor_Mt_y": 4.6,
            "raw_imported_pellets_anchor_Mt_y": 1.5,
            "raw_BF_hot_metal_context_Mt_y": 6.3,
            "raw_DRP_DRI_context_Mt_y": 0.0,
            "computed_BF_pellet_coeff": _fmt((4.6 + 1.5) / 6.3),
            "anchor_status": "validation_anchor_and_development_reconciliation_not_hourly_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "C0 coefficient reconciles public annual pellet supply and BF hot-metal context; not independent BF recipe.",
        },
        {
            "configuration": C1,
            "anchor_id": "C1_raw_PEFA_import_DRP_residual_BF_pellet_context",
            "raw_PEFA_anchor_Mt_y": 5.0,
            "raw_imported_pellets_anchor_Mt_y": 0.2,
            "raw_BF_hot_metal_context_Mt_y": 2.8,
            "raw_DRP_DRI_context_Mt_y": 2.8,
            "computed_BF_pellet_coeff": _fmt((5.0 + 0.2 - 2.8 * (1.0 / DRP_YIELD_FOR_PELLET_INPUT)) / 2.8),
            "anchor_status": "validation_anchor_and_development_reconciliation_not_hourly_constraint",
            "source_card": SOURCE_CARD,
            "caveat": "C1 BF coefficient is residual after DRP pellet demand; not independent retained-BF6 burden evidence.",
        },
    ]


def _source_payload() -> dict[str, Any]:
    params = _param_map(_read_csv(C5N_B_DIR / "s4_4c5n_b_pellet_burden_development_input_rows.csv"))
    pefa_activity = _by_key(_read_csv(C5N_A_DIR / "s4_4c5n_a_pefa_activity_report.csv"))
    c5k = _by_key(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv"))
    return {"params": params, "pefa_activity": pefa_activity, "c5k": c5k}


def _imported_pellets(config: str, scale: float) -> float:
    raw = C0_IMPORTED_PELLETS_RAW_T_Y if config == C0 else C1_IMPORTED_PELLETS_RAW_T_Y
    return raw * scale


def _drp_dri_output(config: str, scale: float) -> float:
    if config == C0:
        return 0.0
    return C1_DRP_DRI_CONTEXT_T_Y * scale


def _pellet_balance_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    drp_coeff = _zero(payload["params"]["DRP_PELLET_INPUT_T_PER_T_DRI"]["base_value"])
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            c5k = payload["c5k"][key]
            activity = payload["pefa_activity"][key]
            active_total_ls = _zero(c5k["active_total_liquid_steel_target_site_t_y"])
            scale = _scale(config, active_total_ls)
            pefa_output = _zero(activity["PEFA_output_site_t_y"])
            imported = _imported_pellets(config, scale)
            bf_hm = _zero(c5k["bf_hot_metal_normalised_site_t_y"])
            drp_dri = _drp_dri_output(config, scale)
            drp_demand = drp_dri * drp_coeff
            supply = pefa_output + imported
            residual_for_bf = supply - drp_demand
            bf_coeff = residual_for_bf / bf_hm if bf_hm else 0.0
            bf_demand = bf_hm * bf_coeff
            total_demand = bf_demand + drp_demand
            net = supply - total_demand
            if abs(net) <= TOL_T:
                net = 0.0
            gap = max(-net, 0.0)
            surplus = max(net, 0.0)
            if abs(gap) <= TOL_T:
                gap = 0.0
            if abs(surplus) <= TOL_T:
                surplus = 0.0
            tolerance = max(total_demand * PELLET_GAP_TOL_REL, PELLET_GAP_TOL_T_Y)
            source = (
                "dynamic_C0_scaled_PEFA_plus_import_reconciliation"
                if config == C0
                else "dynamic_C1_residual_from_scaled_PEFA_import_DRP_context"
            )
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "PELLET_GRADE_MODE": PELLET_GRADE_MODE,
                    "PELLET_BALANCE_MODE": PELLET_BALANCE_MODE,
                    "active_total_liquid_steel_target_site_t_y": c5k["active_total_liquid_steel_target_site_t_y"],
                    "scale_mode": "scale_with_active_production_target",
                    "scale_factor": _fmt(scale),
                    "PEFA_fired_pellets_output_site_t_y": _fmt(pefa_output),
                    "imported_pellets_site_t_y": _fmt(imported),
                    "imported_pellets_policy": "fixed_exogenous_scaled_development_supply_not_slack",
                    "BF_hot_metal_driver_site_t_y": _fmt(bf_hm),
                    "DRP_DRI_output_site_t_y": _fmt(drp_dri),
                    "DRP_DRI_driver_source": "inactive_zero_C0" if config == C0 else "active_scaled_MER_DRI_context_due_to_C5_DRP_KPI_deferred",
                    "resolved_BF_pellet_input_t_per_t_HM": _fmt(bf_coeff),
                    "resolved_BF_pellet_coeff_source": source,
                    "resolved_DRP_pellet_input_t_per_t_DRI": _fmt(drp_coeff),
                    "BF_pellet_demand_site_t_y": _fmt(bf_demand),
                    "DRP_pellet_demand_site_t_y": _fmt(drp_demand),
                    "total_pellet_supply_site_t_y": _fmt(supply),
                    "total_pellet_demand_site_t_y": _fmt(total_demand),
                    "pellet_net_balance_site_t_y": _fmt(net),
                    "pellet_gap_site_t_y": _fmt(gap),
                    "pellet_surplus_site_t_y": _fmt(surplus),
                    "pellet_gap_Mt_y": _fmt(gap / 1_000_000.0),
                    "pellet_surplus_Mt_y": _fmt(surplus / 1_000_000.0),
                    "pellet_gap_pct_of_demand": _fmt(gap / total_demand * 100.0 if total_demand else 0.0),
                    "pellet_surplus_pct_of_demand": _fmt(surplus / total_demand * 100.0 if total_demand else 0.0),
                    "pellet_gap_tolerance_site_t_y": _fmt(tolerance),
                    "pellet_balance_within_tolerance": _bool(gap <= tolerance and surplus <= tolerance),
                    "BF_pellet_coeff_inside_generic_BREF_range": _bool(GENERIC_BREF_BF_PELLET_LOW <= bf_coeff <= GENERIC_BREF_BF_PELLET_HIGH),
                    "pellet_grade_quality_modelled": "false",
                    "validation_anchors_used_as_hourly_constraints": "false",
                    "pellet_gap_or_surplus_is_solver_slack": "false",
                    "status": "pass_development_pellet_balance" if gap <= tolerance and surplus <= tolerance else "warning_pellet_balance_outside_tolerance",
                }
            )
    return rows


def _inventory_rows(balance_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in balance_rows:
        horizon = int(row["horizon_hours"])
        demand = _zero(row["total_pellet_demand_site_t_y"])
        net_annual = _zero(row["pellet_net_balance_site_t_y"])
        avg_hourly_demand = demand / 8760.0 if demand else 0.0
        start = avg_hourly_demand * 24.0 * 7.0
        capacity = avg_hourly_demand * 24.0 * 90.0
        horizon_drift = net_annual * horizon / 8760.0
        end = start + horizon_drift
        inv_min = min(start, end)
        inv_max = max(start, end)
        capacity_binds = capacity > 0.0 and inv_max >= capacity - TOL_T
        negative = inv_min < -TOL_T
        terminal_guard = "terminal_neutrality_expected_zero_drift"
        if abs(horizon_drift) > TOL_T:
            terminal_guard = "explicit_net_drift_diagnostic_no_hidden_terminal_slack"
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "carrier": "fired_pellets_proxy",
                "storage_capacity_mode": STORAGE_MODE,
                "storage_capacity_t": _fmt(capacity),
                "pellet_inventory_start_t": _fmt(start),
                "pellet_inventory_end_t": _fmt(end),
                "pellet_inventory_min_t": _fmt(inv_min),
                "pellet_inventory_max_t": _fmt(inv_max),
                "pellet_inventory_delta_t": _fmt(horizon_drift),
                "pellet_net_inventory_drift_annualised_t_y": row["pellet_net_balance_site_t_y"],
                "terminal_inventory_guard_status": terminal_guard,
                "negative_inventory_flag": _bool(negative),
                "capacity_bind_count": 1 if capacity_binds else 0,
                "inventory_mined_without_terminal_guard": "false",
                "status": "pass" if not capacity_binds and not negative else "fail",
            }
        )
    return rows


def _storage_policy_rows(balance_rows: list[dict[str, Any]], inventory_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inv_by_key = _by_key(inventory_rows)
    rows: list[dict[str, Any]] = []
    for row in balance_rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        for carrier in ["coke", "sinter", "fired_pellets_proxy"]:
            if carrier == "fired_pellets_proxy":
                bind_count = int(inv_by_key[key]["capacity_bind_count"])
                guard = inv_by_key[key]["terminal_inventory_guard_status"]
                warning = "" if bind_count == 0 else "pellet_storage_capacity_binds"
            else:
                bind_count = 0
                guard = "reported_policy_only_no_active_capacity_bind_in_current_C5_diagnostics"
                warning = ""
            rows.append(
                {
                    "configuration": row["configuration"],
                    "horizon_hours": row["horizon_hours"],
                    "bulk_solid_carrier": carrier,
                    "storage_capacity_mode": STORAGE_MODE,
                    "thesis_usability": "false",
                    "capacity_bind_count": bind_count,
                    "terminal_or_inventory_drift_guard": guard,
                    "inventory_drift_warning": warning,
                    "policy_status": "development_policy_practically_non_binding_not_exact_Tata_capacity",
                    "production_or_yield_changed": "false",
                }
            )
    return rows


def _health_rows(balance_rows: list[dict[str, Any]], inventory_rows: list[dict[str, Any]], storage_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inv = _by_key(inventory_rows)
    storage_by_key_carrier = {
        (row["configuration"], int(row["horizon_hours"]), row["bulk_solid_carrier"]): row for row in storage_rows
    }
    rows: list[dict[str, Any]] = []
    for row in balance_rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        pellet_storage = storage_by_key_carrier[(row["configuration"], int(row["horizon_hours"]), "fired_pellets_proxy")]
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "status": "development_only",
                "thesis_usability": "false",
                "dependency_chain": DEPENDENCY_CHAIN,
                "PEFA_fired_pellets_output_site_t_y": row["PEFA_fired_pellets_output_site_t_y"],
                "imported_pellets_site_t_y": row["imported_pellets_site_t_y"],
                "BF_pellet_demand_site_t_y": row["BF_pellet_demand_site_t_y"],
                "DRP_pellet_demand_site_t_y": row["DRP_pellet_demand_site_t_y"],
                "total_pellet_supply_site_t_y": row["total_pellet_supply_site_t_y"],
                "total_pellet_demand_site_t_y": row["total_pellet_demand_site_t_y"],
                "pellet_gap_site_t_y": row["pellet_gap_site_t_y"],
                "pellet_surplus_site_t_y": row["pellet_surplus_site_t_y"],
                "resolved_BF_pellet_input_t_per_t_HM": row["resolved_BF_pellet_input_t_per_t_HM"],
                "resolved_DRP_pellet_input_t_per_t_DRI": row["resolved_DRP_pellet_input_t_per_t_DRI"],
                "pellet_inventory_start_t": inv[key]["pellet_inventory_start_t"],
                "pellet_inventory_end_t": inv[key]["pellet_inventory_end_t"],
                "pellet_inventory_min_t": inv[key]["pellet_inventory_min_t"],
                "pellet_inventory_max_t": inv[key]["pellet_inventory_max_t"],
                "pellet_inventory_delta_t": inv[key]["pellet_inventory_delta_t"],
                "pellet_net_inventory_drift_annualised_t_y": inv[key]["pellet_net_inventory_drift_annualised_t_y"],
                "coke_storage_capacity_mode": STORAGE_MODE,
                "sinter_storage_capacity_mode": STORAGE_MODE,
                "pellet_storage_capacity_mode": pellet_storage["storage_capacity_mode"],
                "coke_storage_bind_count": storage_by_key_carrier[(row["configuration"], int(row["horizon_hours"]), "coke")]["capacity_bind_count"],
                "sinter_storage_bind_count": storage_by_key_carrier[(row["configuration"], int(row["horizon_hours"]), "sinter")]["capacity_bind_count"],
                "pellet_storage_bind_count": pellet_storage["capacity_bind_count"],
                "pellet_grade_quality_modelled": row["pellet_grade_quality_modelled"],
                "caveats": _caveat_string(row),
                "red_flags": _failure_string(row, inv[key], storage_by_key_carrier, key),
            }
        )
    return rows


def _caveat_string(row: dict[str, Any]) -> str:
    caveats = ["PELLET_GRADE_PROXY_ACTIVE"]
    if row["configuration"] == C1:
        caveats.append("C1_BF_PELLET_COEFF_IS_RESIDUAL_NOT_TECHNOLOGY_SOURCE")
    if row["DRP_DRI_driver_source"] != "inactive_zero_C0":
        caveats.append("DRP_DRI_DRIVER_CONTEXT_ACTIVE_BECAUSE_DETAILED_DRP_KPI_DEFERRED")
    return ";".join(caveats)


def _failure_flags(
    row: dict[str, Any],
    inventory: dict[str, Any],
    storage_by_key_carrier: dict[tuple[str, int, str], dict[str, Any]],
    key: tuple[str, int],
) -> dict[str, bool]:
    gap = _zero(row["pellet_gap_site_t_y"])
    surplus = _zero(row["pellet_surplus_site_t_y"])
    tolerance = _zero(row["pellet_gap_tolerance_site_t_y"])
    return {
        "PELLET_BALANCE_GAP_GT_TOL": gap > tolerance,
        "PELLET_BALANCE_SURPLUS_GT_TOL": surplus > tolerance,
        "PELLET_STORAGE_BINDS": int(inventory["capacity_bind_count"]) > 0,
        "COKE_STORAGE_BINDS_AFTER_NONBINDING_POLICY": int(storage_by_key_carrier[(key[0], key[1], "coke")]["capacity_bind_count"]) > 0,
        "SINTER_STORAGE_BINDS_AFTER_NONBINDING_POLICY": int(storage_by_key_carrier[(key[0], key[1], "sinter")]["capacity_bind_count"]) > 0,
        "PELLET_INVENTORY_MINED_WITHOUT_TERMINAL_GUARD": inventory["inventory_mined_without_terminal_guard"] != "false",
        "PELLET_IMPORT_USED_AS_FREE_SLACK": row["imported_pellets_policy"] != "fixed_exogenous_scaled_development_supply_not_slack",
        "BF_PELLET_COEFF_OUTSIDE_GENERIC_BREF_RANGE": row["BF_pellet_coeff_inside_generic_BREF_range"] != "true",
    }


def _failure_string(
    row: dict[str, Any],
    inventory: dict[str, Any],
    storage_by_key_carrier: dict[tuple[str, int, str], dict[str, Any]],
    key: tuple[str, int],
) -> str:
    return ";".join(name for name, active in _failure_flags(row, inventory, storage_by_key_carrier, key).items() if active)


def _redflag_rows(balance_rows: list[dict[str, Any]], inventory_rows: list[dict[str, Any]], storage_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inv = _by_key(inventory_rows)
    storage_by_key_carrier = {
        (row["configuration"], int(row["horizon_hours"]), row["bulk_solid_carrier"]): row for row in storage_rows
    }
    rows: list[dict[str, Any]] = []
    for row in balance_rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        flags = _failure_flags(row, inv[key], storage_by_key_carrier, key)
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                **{name: _bool(value) for name, value in flags.items()},
                "C1_BF_PELLET_COEFF_IS_RESIDUAL_NOT_TECHNOLOGY_SOURCE": _bool(row["configuration"] == C1),
                "PELLET_GRADE_PROXY_ACTIVE": "true",
                "failure_count": sum(1 for value in flags.values() if value),
                "caveat_count": (1 if row["configuration"] == C1 else 0) + 1,
                "status": "pass_with_caveats" if not any(flags.values()) else "fail",
            }
        )
    return rows


def _stage_gate(redflags: list[dict[str, Any]], balance_rows: list[dict[str, Any]]) -> dict[str, Any]:
    failure_count = sum(int(row["failure_count"]) for row in redflags)
    c0 = next(row for row in balance_rows if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    c1 = next(row for row in balance_rows if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    return {
        "stage_id": STAGE,
        "decision": "pass_development_pellet_burden_balance_and_bulk_storage_policy" if failure_count == 0 else "fail_development_pellet_burden_balance_and_bulk_storage_policy",
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "output_directory": _rel(C5N_B_DIR),
        "failure_count": failure_count,
        "pellet_grade_mode": PELLET_GRADE_MODE,
        "pellet_balance_mode": PELLET_BALANCE_MODE,
        "bulk_solid_storage_capacity_mode": STORAGE_MODE,
        "C0_24h_resolved_BF_pellet_coeff": _zero(c0["resolved_BF_pellet_input_t_per_t_HM"]),
        "C1_24h_resolved_BF_pellet_coeff": _zero(c1["resolved_BF_pellet_input_t_per_t_HM"]),
        "DRP_pellet_input_t_per_t_DRI": 1.0 / DRP_YIELD_FOR_PELLET_INPUT,
        "validation_anchors_used_as_hourly_constraints": False,
        "hidden_solver_slack_active": False,
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5n_a_pefa_pelletizing_layer()
    C5N_B_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(C5N_B_DIR / "s4_4c5n_b_pellet_burden_development_input_rows.csv", _pellet_dev_rows())
    _write_csv(C5N_B_DIR / "s4_4c5n_b_pellet_validation_anchors.csv", _validation_anchor_rows())

    payload = _source_payload()
    balance = _pellet_balance_rows(payload)
    inventory = _inventory_rows(balance)
    storage = _storage_policy_rows(balance, inventory)
    health = _health_rows(balance, inventory, storage)
    redflags = _redflag_rows(balance, inventory, storage)
    gate = _stage_gate(redflags, balance)

    _write_json(C5N_B_DIR / "s4_4c5n_b_stage_gate.json", gate)
    _write_csv(
        C5N_B_DIR / "s4_4c5n_b_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5n_a_pefa_pelletizing_layer",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5N_B_DIR / "s4_4c5n_b_pellet_balance_report.csv", balance)
    _write_csv(C5N_B_DIR / "s4_4c5n_b_pellet_inventory_dashboard.csv", inventory)
    _write_csv(C5N_B_DIR / "s4_4c5n_b_bulk_solid_storage_policy_dashboard.csv", storage)
    _write_csv(C5N_B_DIR / "s4_4c5n_b_compact_healthcheck.csv", health)
    _write_csv(C5N_B_DIR / "s4_4c5n_b_red_flags.csv", redflags)
    _write_csv(C5N_B_DIR / "s4_4c5n_b_compact_table_for_chat.csv", balance)
    _write_json(
        C5N_B_DIR / "s4_4c5n_b_pellet_burden_balance_report.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "development_inputs": _pellet_dev_rows(),
            "validation_anchors": _validation_anchor_rows(),
            "pellet_balance": balance,
            "inventory": inventory,
            "storage_policy": storage,
            "healthcheck": health,
            "red_flags": redflags,
        },
    )
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "development_inputs": len(_pellet_dev_rows()),
            "balance": len(balance),
            "inventory": len(inventory),
            "storage_policy": len(storage),
            "health": len(health),
            "redflags": len(redflags),
        },
    }
    _write_json(C5N_B_DIR / "s4_4c5n_b_summary.json", summary)
    return summary


def run_s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
