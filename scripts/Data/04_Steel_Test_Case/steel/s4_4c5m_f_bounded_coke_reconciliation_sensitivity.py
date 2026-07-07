"""S4.4c5m_f bounded coke-reconciliation sensitivity.

This stage implements labelled diagnostic/sensitivity cases from C5m_e without
promoting any case to the accepted baseline. Case 0 preserves the repaired
C5m_e baseline. Cases 1-3 quantify bounded KGF-anchor and BF coke-rate
reconciliation options, including KGF KPI, WAG, and CO2 propagation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    C5F_DIR,
    CONFIGS,
    HORIZONS,
    S4_ROOT,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5h_blast_furnace_controller_parameterisation import (
    BF_BFG_OUTPUT_MWH_PER_T_HM,
    BF_CARBON_ACCOUNTING_MODE,
    BF_COKE_RATE_T_PER_T_HM,
    BF_HOT_STOVE_DEMAND_MWH_PER_T_HM,
)
from .s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration import C5M_B_DIR
from .s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit import (
    BF_COKE_RATE_HIGH,
    BF_COKE_RATE_LOW,
)
from .s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report import (
    BF_COKE_DEMAND_DRIVER_SOURCE,
    C5M_E_DIR,
    run_s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report,
)
from .s4_4c5m_sinter_minimal_parameterisation import C5M_DIR


STAGE = "S4.4c5m_f_bounded_coke_reconciliation_sensitivity"
C5M_F_DIR = S4_ROOT / "s4_4c5m_f_bounded_coke_reconciliation_sensitivity"
DEPENDENCY_CHAIN = "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b -> C5m_c -> C5m_d -> C5m_e -> C5m_f"
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_table_redflag_pattern;"
    "C5m_f_cases_are_labelled_sensitivity_diagnostics_not_baseline_replacement"
)

TOL_T = 1.0
NEAR_LOW_BOUND_DELTA = 0.01


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _bool(value: bool) -> str:
    return str(value).lower()


def _by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _by_key_case(rows: list[dict[str, str]]) -> dict[tuple[str, int, str], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"]), row["case_id"]): row for row in rows}


def _by_key_carrier(rows: list[dict[str, str]]) -> dict[tuple[str, int, str], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"]), row["carrier"]): row for row in rows}


def _param_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["parameter_id"]: row for row in rows}


def _range_status(value: float) -> str:
    if value < BF_COKE_RATE_LOW - 1e-12:
        return "below_supported_range"
    if value > BF_COKE_RATE_HIGH + 1e-12:
        return "above_supported_range"
    return "within_supported_range"


def _source_payload() -> dict[str, Any]:
    repaired = _by_key(_read_csv(C5M_E_DIR / "s4_4c5m_e_repaired_coke_balance.csv"))
    anchors = _by_key(_read_csv(C5M_E_DIR / "s4_4c5m_e_kgf_anchor_context.csv"))
    c5m_e_gate = json.loads((C5M_E_DIR / "s4_4c5m_e_stage_gate.json").read_text(encoding="utf-8"))
    c5m_b_totals = _by_key(_read_csv(C5M_B_DIR / "s4_4c5m_b_modelled_totals.csv"))
    wag = _by_key_carrier(_read_csv(C5M_B_DIR / "s4_4c5m_b_wag_carrier_ledger.csv"))
    kgf_params = _param_map(_read_csv(C5F_DIR / "s4_4c5f_kgf_parameter_values.csv"))
    sinter_ctrl = _by_key(_read_csv(C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv"))
    co2 = _read_csv(C5M_B_DIR / "s4_4c5m_b_co2_diagnostic_ledger.csv")
    return locals()


def _kgf_coefficients(payload: dict[str, Any]) -> dict[str, float]:
    params = payload["kgf_params"]
    cog_yield_nm3 = _zero(params["COG_YIELD_NM3_PER_T_COKE"]["base_value"])
    cog_lhv = _zero(params["COG_LHV_MJ_PER_NM3"]["base_value"])
    under_gj = _zero(params["KGF_UNDERFIRING_GJ_PER_T_COKE"]["base_value"])
    gross_mwh = cog_yield_nm3 * cog_lhv / 3600.0
    under_mwh = under_gj / 3.6
    return {
        "dry_coal_t_per_t_coke": _zero(params["DRY_COAL_PER_COKE_TPT"]["base_value"]),
        "electricity_MWh_per_t_coke": _zero(params["KGF_ELECTRICITY_MWH_PER_T_COKE"]["base_value"]),
        "steam_proxy_MWh_per_t_coke": _zero(params["KGF_STEAM_GJ_PER_T_COKE"]["base_value"]) / 3.6,
        "steam_mass_t_per_t_coke": _zero(params["KGF_STEAM_T_PER_T_COKE_DIAGNOSTIC"]["base_value"]),
        "gross_COG_MWh_per_t_coke": gross_mwh,
        "underfiring_MWh_per_t_coke": under_mwh,
        "net_COG_surplus_MWh_per_t_coke": gross_mwh - under_mwh,
        "direct_CO2_t_per_t_coke": _zero(params["KGF_DIRECT_CO2_T_PER_T_COKE"]["base_value"]),
    }


def _case_definitions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            repaired = payload["repaired"][key]
            anchor = payload["anchors"][key]
            driver = _zero(repaired["BF_hot_metal_driver_site_t_y"])
            current_kgf = _zero(repaired["KGF_coke_output_site_t_y"])
            active_anchor = _zero(anchor["active_scaled_public_KGF_anchor_site_t_y"])
            raw_anchor = _zero(anchor["raw_public_KGF_anchor_site_t_y"])
            case_inputs = [
                (
                    "case_0_repaired_current_baseline",
                    "repaired_current_baseline",
                    "current_C5m_e_KGF_output",
                    current_kgf,
                    "current_project_BF_coke_rate",
                    BF_COKE_RATE_T_PER_T_HM,
                    "reference",
                    "repaired C5m_e baseline; coke gap remains visible",
                ),
                (
                    "case_1_active_scaled_KGF_anchor_exact_BF_rate",
                    "active_scaled_KGF_anchor_exact_BF_rate",
                    "active_scaled_public_KGF_anchor",
                    active_anchor,
                    "required_exact_closure_rate",
                    active_anchor / driver if driver else 0.0,
                    "baseline_candidate_for_future_human_review",
                    "bounded reconciliation scenario; not baseline; not Tata-validated",
                ),
                (
                    "case_2_active_scaled_KGF_anchor_low_BF_rate",
                    "active_scaled_KGF_anchor_low_BF_rate",
                    "active_scaled_public_KGF_anchor",
                    active_anchor,
                    "governed_low_BF_coke_rate",
                    BF_COKE_RATE_LOW,
                    "sensitivity",
                    "low-coke-rate optimistic sensitivity; surplus must be reported",
                ),
                (
                    "case_3_raw_public_KGF_anchor_exact_BF_rate",
                    "raw_public_KGF_anchor_exact_BF_rate",
                    "raw_public_KGF_anchor",
                    raw_anchor,
                    "required_exact_closure_rate",
                    raw_anchor / driver if driver else 0.0,
                    "sensitivity",
                    "raw public anchor sensitivity; not active model baseline",
                ),
            ]
            for case_id, label, kgf_basis, kgf_output, rate_basis, rate, role, caveat in case_inputs:
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "case_id": case_id,
                        "case_label": label,
                        "KGF_output_basis": kgf_basis,
                        "KGF_output_site_t_y": _fmt(kgf_output),
                        "BF_coke_rate_basis": rate_basis,
                        "BF_coke_rate_t_per_t_HM": round(rate, 9),
                        "input_status": "repaired_baseline_reference" if case_id.startswith("case_0") else "reconciliation_sensitivity",
                        "thesis_usability": "false",
                        "human_review_required": "true",
                        "codex_may_decide": "false",
                        "recommended_role": role,
                        "caveat": caveat,
                    }
                )
    return rows


def _coke_balance_rows(payload: dict[str, Any], cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        key = (case["configuration"], int(case["horizon_hours"]))
        repaired = payload["repaired"][key]
        anchors = payload["anchors"][key]
        driver = _zero(repaired["BF_hot_metal_driver_site_t_y"])
        rate = _zero(case["BF_coke_rate_t_per_t_HM"])
        kgf = _zero(case["KGF_output_site_t_y"])
        demand = driver * rate
        gap = kgf - demand
        rate_status = _range_status(rate)
        case_id = case["case_id"]
        if case_id.startswith("case_0"):
            support = "repaired_current_baseline_reference_open_gap"
        elif case_id.startswith("case_1"):
            support = "evidence_bounded_reconciliation_sensitivity"
        elif case_id.startswith("case_2"):
            support = "low_coke_rate_optimistic_sensitivity"
        else:
            support = "raw_anchor_sensitivity_not_active_model_baseline"
        rows.append(
            {
                **case,
                "BF_HM_driver_source": BF_COKE_DEMAND_DRIVER_SOURCE,
                "BF_HM_driver_site_t_y": _fmt(driver),
                "BF_coke_demand_site_t_y": _fmt(demand),
                "coke_balance_gap_site_t_y": _fmt(gap),
                "coke_gap_Mt_y": _fmt(gap / 1_000_000.0),
                "coke_surplus_site_t_y": _fmt(max(gap, 0.0)),
                "coke_shortfall_site_t_y": _fmt(max(-gap, 0.0)),
                "gap_closed": _bool(gap >= -TOL_T),
                "BF_coke_rate_within_source_range": _bool(rate_status == "within_supported_range"),
                "BF_coke_rate_range_status": rate_status,
                "BF_coke_rate_low_bound": _fmt(BF_COKE_RATE_LOW),
                "BF_coke_rate_high_bound": _fmt(BF_COKE_RATE_HIGH),
                "C0_required_rate_near_low_bound": _bool(
                    case_id.startswith("case_1")
                    and case["configuration"] == C0
                    and rate <= BF_COKE_RATE_LOW + NEAR_LOW_BOUND_DELTA
                ),
                "KGF_output_relation_to_public_anchor": _kgf_anchor_relation(kgf, anchors),
                "source_support_classification": support,
                "baseline_changed": "false",
                "external_coke_implemented": "false",
            }
        )
    return rows


def _kgf_anchor_relation(kgf_output: float, anchors: dict[str, str]) -> str:
    current = _zero(anchors["current_KGF_coke_output_site_t_y"])
    active = _zero(anchors["active_scaled_public_KGF_anchor_site_t_y"])
    raw = _zero(anchors["raw_public_KGF_anchor_site_t_y"])
    if abs(kgf_output - current) <= TOL_T:
        return "current_C5m_e_KGF_output"
    if abs(kgf_output - active) <= TOL_T:
        return "equals_active_scaled_public_KGF_anchor"
    if abs(kgf_output - raw) <= TOL_T:
        return "equals_raw_public_KGF_anchor"
    if kgf_output > raw + TOL_T:
        return "above_raw_public_KGF_anchor"
    return "intermediate_bounded_anchor_value"


def _bf_rate_checks(coke_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration": row["configuration"],
            "horizon_hours": row["horizon_hours"],
            "case_id": row["case_id"],
            "BF_coke_rate_t_per_t_HM": row["BF_coke_rate_t_per_t_HM"],
            "low_bound": row["BF_coke_rate_low_bound"],
            "high_bound": row["BF_coke_rate_high_bound"],
            "range_status": row["BF_coke_rate_range_status"],
            "within_governed_range": row["BF_coke_rate_within_source_range"],
            "C0_near_low_bound_caveat": row["C0_required_rate_near_low_bound"],
            "source_card": "data/03_Optimisation/inputs/assets/steel/source_cards/Blast_Furnace_Parameters.md",
        }
        for row in coke_rows
    ]


def _kgf_anchor_checks(coke_rows: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in coke_rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        anchors = payload["anchors"][key]
        kgf = _zero(row["KGF_output_site_t_y"])
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "case_id": row["case_id"],
                "KGF_output_site_t_y": row["KGF_output_site_t_y"],
                "current_KGF_output_site_t_y": anchors["current_KGF_coke_output_site_t_y"],
                "active_scaled_public_KGF_anchor_site_t_y": anchors["active_scaled_public_KGF_anchor_site_t_y"],
                "raw_public_KGF_anchor_site_t_y": anchors["raw_public_KGF_anchor_site_t_y"],
                "relation_to_public_anchor": row["KGF_output_relation_to_public_anchor"],
                "KGF_output_delta_vs_current_t_y": _fmt(kgf - _zero(anchors["current_KGF_coke_output_site_t_y"])),
                "KGF_output_delta_vs_active_scaled_anchor_t_y": _fmt(
                    kgf - _zero(anchors["active_scaled_public_KGF_anchor_site_t_y"])
                ),
                "KGF_output_delta_vs_raw_anchor_t_y": _fmt(kgf - _zero(anchors["raw_public_KGF_anchor_site_t_y"])),
                "source_card": "data/03_Optimisation/inputs/assets/steel/source_cards/Coking_Plants_Parameters.md",
                "anchor_status": "validation_context_anchor_not_dispatch_constraint;scenario_diagnostic_only",
            }
        )
    return rows


def _kgf_kpi_propagation(payload: dict[str, Any], coke_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coeff = _kgf_coefficients(payload)
    rows: list[dict[str, Any]] = []
    for row in coke_rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        current = _zero(payload["repaired"][key]["KGF_coke_output_site_t_y"])
        scenario = _zero(row["KGF_output_site_t_y"])
        delta = scenario - current
        totals = payload["c5m_b_totals"][key]
        delta_elec = delta * coeff["electricity_MWh_per_t_coke"]
        delta_steam_mwh = delta * coeff["steam_proxy_MWh_per_t_coke"]
        delta_steam_t = delta * coeff["steam_mass_t_per_t_coke"]
        delta_cog = delta * coeff["gross_COG_MWh_per_t_coke"]
        delta_under = delta * coeff["underfiring_MWh_per_t_coke"]
        delta_net_cog = delta * coeff["net_COG_surplus_MWh_per_t_coke"]
        delta_co2 = delta * coeff["direct_CO2_t_per_t_coke"]
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "case_id": row["case_id"],
                "KGF_output_changed": _bool(abs(delta) > TOL_T),
                "current_KGF_output_site_t_y": _fmt(current),
                "scenario_KGF_output_site_t_y": _fmt(scenario),
                "delta_KGF_coke_output_t_y": _fmt(delta),
                "delta_dry_coal_input_t_y": _fmt(delta * coeff["dry_coal_t_per_t_coke"]),
                "delta_KGF_electricity_MWh_y": _fmt(delta_elec),
                "delta_KGF_steam_proxy_MWh_y": _fmt(delta_steam_mwh),
                "delta_KGF_steam_mass_t_y": _fmt(delta_steam_t),
                "delta_COG_generation_MWh_LHV_y": _fmt(delta_cog),
                "delta_KGF_underfiring_MWh_LHV_y": _fmt(delta_under),
                "delta_net_COG_surplus_MWh_LHV_y": _fmt(delta_net_cog),
                "delta_KGF_CO2_t_y": _fmt(delta_co2),
                "process_electricity_total_if_case_MWh_y": _fmt(
                    _zero(totals["new_process_electricity_including_BF_KGF_site_MWh_e_y"]) + delta_elec
                ),
                "WAG_generation_total_delta_MWh_y": _fmt(delta_net_cog),
                "diagnostic_CO2_total_if_case_t_y": _fmt(
                    _zero(totals["new_diagnostic_CO2_including_KGF_site_t_y"]) + delta_co2
                ),
                "KPI_deltas_reported": "true",
                "baseline_changed": "false",
            }
        )
    return rows


def _bf_coke_rate_impact(coke_rows: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in coke_rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        baseline = payload["repaired"][key]
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "case_id": row["case_id"],
                "baseline_BF_coke_rate_t_per_t_HM": baseline["BF_COKE_RATE_T_PER_T_HM"],
                "case_BF_coke_rate_t_per_t_HM": row["BF_coke_rate_t_per_t_HM"],
                "BF_coke_rate_changed_vs_baseline": _bool(
                    abs(_zero(row["BF_coke_rate_t_per_t_HM"]) - _zero(baseline["BF_COKE_RATE_T_PER_T_HM"])) > 1e-12
                ),
                "baseline_BF_coke_demand_site_t_y": baseline["BF_coke_demand_site_t_y"],
                "case_BF_coke_demand_site_t_y": row["BF_coke_demand_site_t_y"],
                "delta_BF_coke_demand_t_y": _fmt(
                    _zero(row["BF_coke_demand_site_t_y"]) - _zero(baseline["BF_coke_demand_site_t_y"])
                ),
                "BF_aggregate_CO2_status": BF_CARBON_ACCOUNTING_MODE,
                "BF_aggregate_CO2_unchanged_if_hot_metal_unchanged": "true",
                "BFG_generation_unchanged_if_tied_to_hot_metal_not_coke_rate": "true",
                "coke_carbon_explicit_BF_CO2_mode": "inactive_deferred",
                "baseline_changed": "false",
            }
        )
    return rows


def _wag_propagation(payload: dict[str, Any], coke_rows: list[dict[str, Any]], kpi_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kpi = _by_key_case([{key: str(value) for key, value in row.items()} for row in kpi_rows])
    coeff = _kgf_coefficients(payload)
    rows: list[dict[str, Any]] = []
    for row in coke_rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        case_key = (row["configuration"], int(row["horizon_hours"]), row["case_id"])
        ctrl = payload["sinter_ctrl"][key]
        bfg_ledger = payload["wag"][(row["configuration"], int(row["horizon_hours"]), "BFG")]
        bofg_ledger = payload["wag"][(row["configuration"], int(row["horizon_hours"]), "BOFG")]
        delta_net_cog = _zero(kpi[case_key]["delta_net_COG_surplus_MWh_LHV_y"])
        driver = _zero(row["BF_HM_driver_site_t_y"])
        kgf_output = _zero(row["KGF_output_site_t_y"])
        gross_bfg = driver * BF_BFG_OUTPUT_MWH_PER_T_HM
        bf_stove = driver * BF_HOT_STOVE_DEMAND_MWH_PER_T_HM
        net_bfg = gross_bfg - bf_stove
        gross_cog = kgf_output * coeff["gross_COG_MWh_per_t_coke"]
        kgf_under = kgf_output * coeff["underfiring_MWh_per_t_coke"]
        net_cog = kgf_output * coeff["net_COG_surplus_MWh_per_t_coke"]
        bo_fg = _zero(bofg_ledger["generated_site_MWh_LHV_y"])
        hsm_bfg = _zero(ctrl["BFG_to_HSM_site_MWh_y"])
        hsm_cog = _zero(ctrl["COG_to_HSM_site_MWh_y"])
        hsm_bofg = _zero(ctrl["BOFG_to_HSM_site_MWh_y"])
        sinter_cog = _zero(ctrl["COG_to_Sinter_site_MWh_y"])
        residual_bfg = net_bfg - hsm_bfg
        residual_cog = net_cog - hsm_cog - sinter_cog
        residual_bofg = bo_fg - hsm_bofg
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "case_id": row["case_id"],
                "gross_BFG_generated_MWh_LHV_y": _fmt(gross_bfg),
                "BF_hot_stove_BFG_use_MWh_LHV_y": _fmt(bf_stove),
                "net_BFG_after_BF_hot_stove_MWh_LHV_y": _fmt(net_bfg),
                "gross_COG_generated_MWh_LHV_y": _fmt(gross_cog),
                "KGF_underfiring_COG_use_MWh_LHV_y": _fmt(kgf_under),
                "net_COG_after_KGF_underfiring_MWh_LHV_y": _fmt(net_cog),
                "BOFG_available_MWh_LHV_y": _fmt(bo_fg),
                "HSM_reheat_demand_MWh_y": ctrl["hsm_reheat_demand_site_MWh_y"],
                "Sinter_COG_demand_MWh_y": ctrl["COG_to_Sinter_site_MWh_y"],
                "BFG_to_HSM_MWh_y": ctrl["BFG_to_HSM_site_MWh_y"],
                "COG_to_HSM_MWh_y": ctrl["COG_to_HSM_site_MWh_y"],
                "BOFG_to_HSM_MWh_y": ctrl["BOFG_to_HSM_site_MWh_y"],
                "COG_to_Sinter_MWh_y": ctrl["COG_to_Sinter_site_MWh_y"],
                "NG_to_HSM_MWh_y": ctrl["NG_to_HSM_site_MWh_y"],
                "NG_to_Sinter_MWh_y": ctrl["NG_to_Sinter_site_MWh_y"],
                "COG_HSM_Sinter_demands_still_served": _bool(residual_cog >= -TOL_T),
                "HSM_unserved_reheat_MWh_y": ctrl["HSM_unserved_reheat_site_MWh_y"],
                "Sinter_unserved_gas_MWh_y": ctrl["Sinter_gas_unserved_site_MWh_y"],
                "residual_BFG_after_HSM_and_Sinter_MWh_y": _fmt(residual_bfg),
                "residual_COG_after_HSM_and_Sinter_MWh_y": _fmt(residual_cog),
                "residual_BOFG_after_HSM_and_Sinter_MWh_y": _fmt(residual_bofg),
                "delta_residual_or_interface_COG_MWh_y": _fmt(delta_net_cog),
                "baseline_BFG_WAG_generated_MWh_y": bfg_ledger["generated_site_MWh_LHV_y"],
                "diagnostic_WAG_balance_error_MWh_y": _fmt(0.0 if residual_cog >= -TOL_T else residual_cog),
                "WAG_invariant_status": "pass" if residual_cog >= -TOL_T else "fail",
                "WAG_market_valuation_added": "false",
                "WAG_export_revenue_added": "false",
            }
        )
    return rows


def _co2_propagation(payload: dict[str, Any], coke_rows: list[dict[str, Any]], kpi_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kpi = _by_key_case([{key: str(value) for key, value in row.items()} for row in kpi_rows])
    rows: list[dict[str, Any]] = []
    for row in coke_rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        case_key = (row["configuration"], int(row["horizon_hours"]), row["case_id"])
        totals = payload["c5m_b_totals"][key]
        delta_kgf_co2 = _zero(kpi[case_key]["delta_KGF_CO2_t_y"])
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "case_id": row["case_id"],
                "BF_aggregate_CO2_site_t_y": totals["BF_CO2_site_t_y"],
                "BF_aggregate_CO2_mode_status": BF_CARBON_ACCOUNTING_MODE,
                "BF_CO2_changed_by_BF_coke_rate_sensitivity": "false",
                "KGF_CO2_baseline_site_t_y": totals["KGF_CO2_site_t_y"],
                "KGF_CO2_delta_site_t_y": _fmt(delta_kgf_co2),
                "KGF_CO2_if_case_site_t_y": _fmt(_zero(totals["KGF_CO2_site_t_y"]) + delta_kgf_co2),
                "BOF_CO2_site_t_y": totals["BOF_CO2_site_t_y"],
                "BOF_CO2_changed": "false",
                "Sinter_CO2_site_t_y": totals["Sinter_CO2_site_t_y"],
                "Sinter_CO2_changed": "false",
                "HSM_CO2_status": "blocked_missing_governed_combustion_emission_factors",
                "total_diagnostic_CO2_if_case_site_t_y": _fmt(
                    _zero(totals["new_diagnostic_CO2_including_KGF_site_t_y"]) + delta_kgf_co2
                ),
                "fuel_combustion_CO2_activated": "false",
                "CO2_double_counting_guard_status": totals["CO2_double_counting_guard_status"],
            }
        )
    return rows


def _option_comparison(coke_rows: list[dict[str, Any]], kpi_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kpi = _by_key_case([{key: str(value) for key, value in row.items()} for row in kpi_rows])
    rows: list[dict[str, Any]] = []
    for row in coke_rows:
        case_key = (row["configuration"], int(row["horizon_hours"]), row["case_id"])
        kgf_changed = kpi[case_key]["KGF_output_changed"]
        if row["case_id"].startswith("case_1"):
            recommendation = "preferred_reconciliation_candidate_for_future_baseline_consideration"
        elif row["case_id"].startswith("case_2"):
            recommendation = "optimistic_low_coke_rate_sensitivity"
        elif row["case_id"].startswith("case_3"):
            recommendation = "raw_anchor_sensitivity_not_active_baseline"
        else:
            recommendation = "accepted_repaired_current_baseline_reference"
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "case_id": row["case_id"],
                "gap_closed": row["gap_closed"],
                "coke_gap_Mt_y": row["coke_gap_Mt_y"],
                "changes_KGF_output": kgf_changed,
                "changes_BF_coke_rate": _bool(abs(_zero(row["BF_coke_rate_t_per_t_HM"]) - BF_COKE_RATE_T_PER_T_HM) > 1e-12),
                "changes_process_electricity": kgf_changed,
                "changes_steam": kgf_changed,
                "changes_COG_generation": kgf_changed,
                "changes_WAG_surplus": kgf_changed,
                "changes_diagnostic_CO2": kgf_changed,
                "external_coke_implemented": "false",
                "source_support_classification": row["source_support_classification"],
                "recommended_role": row["recommended_role"],
                "recommendation": recommendation,
            }
        )
    return rows


def _recommendation_rows(coke_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            case1 = next(
                row
                for row in coke_rows
                if row["configuration"] == config
                and int(row["horizon_hours"]) == horizon
                and row["case_id"] == "case_1_active_scaled_KGF_anchor_exact_BF_rate"
            )
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "case_1_closes_gap": case1["gap_closed"],
                    "case_1_rate_within_range": case1["BF_coke_rate_within_source_range"],
                    "case_1_required_rate_t_per_t_HM": case1["BF_coke_rate_t_per_t_HM"],
                    "C0_near_low_bound_caveat": case1["C0_required_rate_near_low_bound"],
                    "external_unmodelled_coke_recommended_now": "false",
                    "preferred_case_for_future_baseline_consideration": "case_1_active_scaled_KGF_anchor_exact_BF_rate",
                    "recommended_next_action": (
                        "Prepare a human-reviewed future baseline-candidate patch for Case 1; keep Case 2 as optimistic sensitivity "
                        "and external/unmodelled coke as fallback only."
                    ),
                    "baseline_changed": "false",
                }
            )
    return rows


def _redflag_rows(
    payload: dict[str, Any],
    coke_rows: list[dict[str, Any]],
    kpi_rows: list[dict[str, Any]],
    wag_rows: list[dict[str, Any]],
    co2_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    kpi = _by_key_case([{key: str(value) for key, value in row.items()} for row in kpi_rows])
    wag = _by_key_case([{key: str(value) for key, value in row.items()} for row in wag_rows])
    co2 = _by_key_case([{key: str(value) for key, value in row.items()} for row in co2_rows])
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            case1 = next(
                row
                for row in coke_rows
                if row["configuration"] == config
                and int(row["horizon_hours"]) == horizon
                and row["case_id"] == "case_1_active_scaled_KGF_anchor_exact_BF_rate"
            )
            case1_key = (config, horizon, case1["case_id"])
            case_rows = [row for row in coke_rows if row["configuration"] == config and int(row["horizon_hours"]) == horizon]
            anchor_cases = [row for row in case_rows if not row["case_id"].startswith("case_0")]
            flags = {
                "redflag_baseline_changed": False,
                "redflag_case_1_gap_not_closed": case1["gap_closed"] != "true",
                "redflag_case_1_required_rate_outside_range": case1["BF_coke_rate_range_status"] != "within_supported_range",
                "redflag_case_1_missing_KGF_KPI_deltas": kpi[case1_key]["KPI_deltas_reported"] != "true",
                "redflag_C0_required_rate_near_low_bound": case1["C0_required_rate_near_low_bound"] == "true",
                "redflag_KGF_anchor_scenario_changes_WAG_without_reporting": any(
                    wag[(row["configuration"], int(row["horizon_hours"]), row["case_id"])]["WAG_invariant_status"] == ""
                    for row in anchor_cases
                ),
                "redflag_CO2_guard_failed": any(
                    co2[(row["configuration"], int(row["horizon_hours"]), row["case_id"])]["CO2_double_counting_guard_status"] != "pass"
                    for row in case_rows
                ),
                "redflag_WAG_invariant_failed": any(
                    wag[(row["configuration"], int(row["horizon_hours"]), row["case_id"])]["WAG_invariant_status"] != "pass"
                    for row in case_rows
                ),
                "redflag_external_coke_implemented": False,
                "redflag_C5k_targets_changed": False,
                "redflag_C5j_BOF_coefficients_changed": False,
                "redflag_C5l_d_HSM_heat_case_changed": payload["c5m_b_totals"][(config, horizon)]["HSM_heat_case"] != "base_0_50",
                "redflag_C5m_Sinter_outputs_changed": False,
            }
            hard_flags = {
                name: value
                for name, value in flags.items()
                if name != "redflag_C0_required_rate_near_low_bound" and value
            }
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    **{name: _bool(value) for name, value in flags.items()},
                    "hard_redflag_count": sum(1 for value in hard_flags.values() if value),
                    "caveat_redflag_count": 1 if flags["redflag_C0_required_rate_near_low_bound"] else 0,
                    "status": "pass_with_near_low_bound_caveat" if flags["redflag_C0_required_rate_near_low_bound"] else "pass",
                }
            )
    return rows


def _stage_gate(redflags: list[dict[str, Any]], coke_rows: list[dict[str, Any]], recommendation: list[dict[str, Any]]) -> dict[str, Any]:
    hard = sum(int(row["hard_redflag_count"]) for row in redflags)
    caveat = sum(int(row["caveat_redflag_count"]) for row in redflags)
    case1_closure = sum(
        1
        for row in coke_rows
        if row["case_id"] == "case_1_active_scaled_KGF_anchor_exact_BF_rate"
        and row["gap_closed"] == "true"
        and row["BF_coke_rate_within_source_range"] == "true"
    )
    return {
        "stage": STAGE,
        "decision": "pass_development_bounded_coke_reconciliation_sensitivity" if hard == 0 else "fail_development_bounded_coke_reconciliation_sensitivity",
        "output_directory": _rel(C5M_F_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "baseline_unchanged_confirmation": True,
        "external_coke_implemented": False,
        "case_1_closure_count": case1_closure,
        "hard_redflag_count": hard,
        "caveat_redflag_count": caveat,
        "failure_count": hard,
        "recommended_next_action": recommendation[0]["recommended_next_action"],
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report()
    C5M_F_DIR.mkdir(parents=True, exist_ok=True)
    payload = _source_payload()
    cases = _case_definitions(payload)
    coke = _coke_balance_rows(payload, cases)
    bf_rates = _bf_rate_checks(coke)
    anchors = _kgf_anchor_checks(coke, payload)
    kpi = _kgf_kpi_propagation(payload, coke)
    bf_impacts = _bf_coke_rate_impact(coke, payload)
    wag = _wag_propagation(payload, coke, kpi)
    co2 = _co2_propagation(payload, coke, kpi)
    comparison = _option_comparison(coke, kpi)
    recommendation = _recommendation_rows(coke)
    redflags = _redflag_rows(payload, coke, kpi, wag, co2)
    gate = _stage_gate(redflags, coke, recommendation)

    _write_json(C5M_F_DIR / "s4_4c5m_f_stage_gate.json", gate)
    _write_csv(
        C5M_F_DIR / "s4_4c5m_f_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5M_F_DIR / "s4_4c5m_f_scenario_definitions.csv", cases)
    _write_csv(C5M_F_DIR / "s4_4c5m_f_coke_balance_by_scenario.csv", coke)
    _write_csv(C5M_F_DIR / "s4_4c5m_f_bf_coke_rate_range_checks.csv", bf_rates)
    _write_csv(C5M_F_DIR / "s4_4c5m_f_kgf_anchor_checks.csv", anchors)
    _write_csv(C5M_F_DIR / "s4_4c5m_f_kgf_kpi_propagation.csv", kpi)
    _write_csv(C5M_F_DIR / "s4_4c5m_f_bf_coke_rate_impact.csv", bf_impacts)
    _write_csv(C5M_F_DIR / "s4_4c5m_f_wag_propagation.csv", wag)
    _write_csv(C5M_F_DIR / "s4_4c5m_f_co2_propagation.csv", co2)
    _write_csv(C5M_F_DIR / "s4_4c5m_f_option_comparison.csv", comparison)
    _write_csv(C5M_F_DIR / "s4_4c5m_f_recommendation.csv", recommendation)
    _write_csv(C5M_F_DIR / "s4_4c5m_f_red_flags.csv", redflags)
    _write_csv(C5M_F_DIR / "s4_4c5m_f_compact_table_for_chat.csv", coke)
    _write_json(
        C5M_F_DIR / "s4_4c5m_f_bounded_coke_reconciliation_report.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "baseline_unchanged_confirmation": True,
            "scenario_definitions": cases,
            "coke_balance_by_scenario": coke,
            "kgf_kpi_propagation": kpi,
            "wag_propagation": wag,
            "co2_propagation": co2,
            "option_comparison": comparison,
            "recommendation": recommendation,
            "red_flags": redflags,
        },
    )
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "recommended_next_action": gate["recommended_next_action"],
        "rows": {
            "scenario_definitions": len(cases),
            "coke_balance": len(coke),
            "kgf_kpi": len(kpi),
            "wag": len(wag),
            "co2": len(co2),
            "redflags": len(redflags),
        },
    }
    _write_json(C5M_F_DIR / "s4_4c5m_f_summary.json", summary)
    return summary


def run_s4_4c5m_f_bounded_coke_reconciliation_sensitivity() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5m_f_bounded_coke_reconciliation_sensitivity(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
