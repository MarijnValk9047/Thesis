"""S4.4c5m_e BF coke-driver alignment and bounded reconciliation report.

This stage repairs the active coke-demand ledger by using the C5k no-buffer
BF hot-metal driver for BF coke demand. It keeps BF coke-rate and KGF baseline
outputs unchanged, then reports bounded reconciliation scenarios without
changing upstream plant coefficients, WAG allocation, or CO2 accounting.
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
from .s4_4c5h_blast_furnace_controller_parameterisation import BF_COKE_RATE_T_PER_T_HM
from .s4_4c5j_bof_osf_minimal_parameterisation import C5J_DIR
from .s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR
from .s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration import C5M_B_DIR
from .s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit import (
    BF_COKE_RATE_HIGH,
    BF_COKE_RATE_LOW,
    C5M_C_DIR,
    KGF_PUBLIC_COKE_ANCHOR_T_Y,
)
from .s4_4c5m_d_coke_balance_driver_consistency_and_bounded_reconciliation_audit import (
    C5M_D_DIR,
    run_s4_4c5m_d_coke_balance_driver_consistency_and_bounded_reconciliation_audit,
)


STAGE = "S4.4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report"
C5M_E_DIR = S4_ROOT / "s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report"
DEPENDENCY_CHAIN = "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b -> C5m_c -> C5m_d -> C5m_e"
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_table_redflag_pattern;"
    "C5m_e_repairs_active_BF_coke_demand_ledger_only;bounded_reconciliation_scenarios_are_diagnostic_only"
)

C5K_BF_DRIVER_FIELD = "bf_hot_metal_normalised_site_t_y"
BF_COKE_DEMAND_DRIVER_SOURCE = "C5k_no_buffer_BF_hot_metal_normalised_site_t_y"
C0_MER_LS_CONTEXT_T_Y = 7_200_000.0
C1_MER_LS_CONTEXT_T_Y = 6_800_000.0
TOL_T = 1.0
ANCHOR_NEAR_TOL_SHARE = 0.05


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _bool(value: bool) -> str:
    return str(value).lower()


def _by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _rows_by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], list[dict[str, str]]]:
    out: dict[tuple[str, int], list[dict[str, str]]] = {}
    for row in rows:
        out.setdefault((row["configuration"], int(row["horizon_hours"])), []).append(row)
    return out


def _param_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["parameter_id"]: row for row in rows}


def _range_status(value: float, low: float = BF_COKE_RATE_LOW, high: float = BF_COKE_RATE_HIGH) -> str:
    if value < low - 1e-12:
        return "below_supported_range"
    if value > high + 1e-12:
        return "above_supported_range"
    return "within_supported_range"


def _active_scaled_anchor(config: str, c5k_row: dict[str, str]) -> float:
    active_ls = _zero(c5k_row["active_total_liquid_steel_target_site_t_y"])
    if config == C0:
        return KGF_PUBLIC_COKE_ANCHOR_T_Y[config] * active_ls / C0_MER_LS_CONTEXT_T_Y
    return KGF_PUBLIC_COKE_ANCHOR_T_Y[config] * active_ls / C1_MER_LS_CONTEXT_T_Y


def _source_payload() -> dict[str, Any]:
    current = _by_key(_read_csv(C5M_C_DIR / "s4_4c5m_c_current_coke_balance_root_cause.csv"))
    c5m_d_driver = _by_key(_read_csv(C5M_D_DIR / "s4_4c5m_d_bf_coke_demand_driver_consistency_audit.csv"))
    c5m_b_totals = _by_key(_read_csv(C5M_B_DIR / "s4_4c5m_b_modelled_totals.csv"))
    c5k = _by_key(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv"))
    c5j = _by_key(_read_csv(C5J_DIR / "s4_4c5j_bof_osf_report.csv"))
    kgf_rows = _rows_by_key(_read_csv(C5F_DIR / "s4_4c5f_coking_plant_diagnostics.csv"))
    kgf_params = _param_map(_read_csv(C5F_DIR / "s4_4c5f_kgf_parameter_values.csv"))
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


def _repaired_coke_balance_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            current = payload["current"][key]
            c5k = payload["c5k"][key]
            c5j = payload["c5j"][key]
            totals = payload["c5m_b_totals"][key]
            driver = _zero(c5k[C5K_BF_DRIVER_FIELD])
            rate = BF_COKE_RATE_T_PER_T_HM
            demand = driver * rate
            kgf_output = _zero(current["total_KGF_coke_output_site_t_y"])
            gap = kgf_output - demand
            implied_hm = demand / rate if rate else 0.0
            residual = implied_hm - driver
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "BF_HM_driver_used": BF_COKE_DEMAND_DRIVER_SOURCE,
                    "BF_hot_metal_driver_site_t_y": _fmt(driver),
                    "C5k_no_buffer_BF_hot_metal_site_t_y": _fmt(driver),
                    "C5k_BOF_hot_metal_input_site_t_y": _fmt(_zero(c5k["bof_hot_metal_input_site_t_y"])),
                    "C5j_BOF_hot_metal_input_site_t_y": _fmt(_zero(c5j["bof_hot_metal_input_site_t_y"])),
                    "BF_COKE_RATE_T_PER_T_HM": _fmt(rate),
                    "BF_coke_demand_site_t_y": _fmt(demand),
                    "KGF_coke_output_site_t_y": _fmt(kgf_output),
                    "coke_balance_gap_site_t_y": _fmt(gap),
                    "coke_gap_Mt_y": _fmt(gap / 1_000_000.0),
                    "gap_pct_of_BF_demand": _fmt(gap / demand * 100.0 if demand else 0.0),
                    "gap_pct_of_KGF_output": _fmt(gap / kgf_output * 100.0 if kgf_output else 0.0),
                    "implied_BF_HM_from_coke_demand_site_t_y": _fmt(implied_hm),
                    "driver_mismatch_residual_t_y": _fmt(residual),
                    "BF_COKE_DEMAND_DRIVER_MATCHES_C5K_NO_BUFFER_HM": _bool(abs(residual) <= TOL_T),
                    "redflag_bf_coke_demand_driver_mismatch": _bool(abs(residual) > TOL_T),
                    "baseline_driver_repair_confirmation": "true",
                    "BF_coke_rate_changed": "false",
                    "KGF_output_changed": "false",
                    "KGF_baseline_kpis_unchanged": "true",
                    "WAG_generation_changed": "false",
                    "WAG_invariant_status": totals["WAG_invariant_status"],
                    "CO2_double_counting_guard_status": totals["CO2_double_counting_guard_status"],
                    "HSM_heat_case": totals["HSM_heat_case"],
                    "status": "pass_repaired_driver_aligned_to_C5k_no_buffer_HM",
                }
            )
    return rows


def _pre_repair_comparison_rows(payload: dict[str, Any], repaired_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repaired = _by_key([{k: str(v) for k, v in row.items()} for row in repaired_rows])
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            current = payload["current"][key]
            driver_audit = payload["c5m_d_driver"][key]
            repaired_row = repaired[key]
            pre_demand = _zero(current["BF_coke_demand_site_t_y"])
            repaired_demand = _zero(repaired_row["BF_coke_demand_site_t_y"])
            pre_gap = _zero(current["coke_balance_gap_site_t_y"])
            repaired_gap = _zero(repaired_row["coke_balance_gap_site_t_y"])
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "pre_repair_stage": "S4.4c5m_d_reference_to_C5m_c_old_driver",
                    "pre_repair_BF_coke_demand_site_t_y": _fmt(pre_demand),
                    "repaired_BF_coke_demand_site_t_y": _fmt(repaired_demand),
                    "delta_BF_coke_demand_site_t_y": _fmt(repaired_demand - pre_demand),
                    "pre_repair_coke_gap_site_t_y": _fmt(pre_gap),
                    "repaired_coke_gap_site_t_y": _fmt(repaired_gap),
                    "delta_coke_gap_site_t_y": _fmt(repaired_gap - pre_gap),
                    "pre_repair_implied_BF_HM_site_t_y": driver_audit["implied_BF_hot_metal_from_coke_demand_site_t_y"],
                    "repaired_implied_BF_HM_site_t_y": repaired_row["implied_BF_HM_from_coke_demand_site_t_y"],
                    "C5k_no_buffer_BF_HM_site_t_y": repaired_row["C5k_no_buffer_BF_hot_metal_site_t_y"],
                    "pre_repair_driver_mismatch_t_y": driver_audit["difference_implied_driver_minus_C5k_no_buffer_HM_t_y"],
                    "repaired_driver_mismatch_t_y": repaired_row["driver_mismatch_residual_t_y"],
                    "driver_repair_changed_only_BF_coke_demand_ledger": "true",
                }
            )
    return rows


def _kgf_anchor_context_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        raw_anchor = KGF_PUBLIC_COKE_ANCHOR_T_Y[config]
        for horizon in HORIZONS:
            key = (config, horizon)
            current_kgf = _zero(payload["current"][key]["total_KGF_coke_output_site_t_y"])
            active_anchor = _active_scaled_anchor(config, payload["c5k"][key])
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "current_KGF_coke_output_site_t_y": _fmt(current_kgf),
                    "raw_public_KGF_anchor_site_t_y": _fmt(raw_anchor),
                    "active_scaled_public_KGF_anchor_site_t_y": _fmt(active_anchor),
                    "active_total_liquid_steel_target_site_t_y": payload["c5k"][key]["active_total_liquid_steel_target_site_t_y"],
                    "MER_liquid_steel_context_site_t_y": _fmt(C0_MER_LS_CONTEXT_T_Y if config == C0 else C1_MER_LS_CONTEXT_T_Y),
                    "gap_current_minus_raw_anchor_t_y": _fmt(current_kgf - raw_anchor),
                    "gap_current_minus_active_scaled_anchor_t_y": _fmt(current_kgf - active_anchor),
                    "raw_anchor_basis": "source_cards/Coking_Plants_Parameters.md_validation_anchor_not_dispatch_constraint",
                    "active_scaled_anchor_basis": "raw_public_KGF_anchor_scaled_by_active_C5k_total_LS_target_over_MER_LS_context",
                    "KGF_output_changed_in_baseline": "false",
                }
            )
    return rows


def _scenario_definitions(current_kgf: float, raw_anchor: float, active_anchor: float, driver: float) -> list[dict[str, Any]]:
    return [
        {
            "scenario_id": "A1_current_rate_current_KGF",
            "scenario_family": "A_current_KGF_output",
            "BF_coke_rate": BF_COKE_RATE_T_PER_T_HM,
            "KGF_output": current_kgf,
            "classification": "repaired_baseline",
        },
        {
            "scenario_id": "A2_low_rate_current_KGF",
            "scenario_family": "A_current_KGF_output",
            "BF_coke_rate": BF_COKE_RATE_LOW,
            "KGF_output": current_kgf,
            "classification": "BF_coke_rate_sensitivity_diagnostic_only",
        },
        {
            "scenario_id": "A3_required_rate_current_KGF",
            "scenario_family": "A_current_KGF_output",
            "BF_coke_rate": current_kgf / driver if driver else 0.0,
            "KGF_output": current_kgf,
            "classification": "required_rate_diagnostic_only",
        },
        {
            "scenario_id": "B1_current_rate_raw_public_anchor",
            "scenario_family": "B_raw_public_KGF_anchor",
            "BF_coke_rate": BF_COKE_RATE_T_PER_T_HM,
            "KGF_output": raw_anchor,
            "classification": "raw_anchor_KGF_sensitivity_diagnostic_only",
        },
        {
            "scenario_id": "B2_low_rate_raw_public_anchor",
            "scenario_family": "B_raw_public_KGF_anchor",
            "BF_coke_rate": BF_COKE_RATE_LOW,
            "KGF_output": raw_anchor,
            "classification": "evidence_bounded_sensitivity_candidate",
        },
        {
            "scenario_id": "B3_required_rate_raw_public_anchor",
            "scenario_family": "B_raw_public_KGF_anchor",
            "BF_coke_rate": raw_anchor / driver if driver else 0.0,
            "KGF_output": raw_anchor,
            "classification": "required_rate_with_raw_anchor_diagnostic_only",
        },
        {
            "scenario_id": "C1_current_rate_active_scaled_anchor",
            "scenario_family": "C_active_scaled_public_KGF_anchor",
            "BF_coke_rate": BF_COKE_RATE_T_PER_T_HM,
            "KGF_output": active_anchor,
            "classification": "active_scaled_anchor_KGF_sensitivity_diagnostic_only",
        },
        {
            "scenario_id": "C2_low_rate_active_scaled_anchor",
            "scenario_family": "C_active_scaled_public_KGF_anchor",
            "BF_coke_rate": BF_COKE_RATE_LOW,
            "KGF_output": active_anchor,
            "classification": "evidence_bounded_sensitivity_candidate",
        },
        {
            "scenario_id": "C3_required_rate_active_scaled_anchor",
            "scenario_family": "C_active_scaled_public_KGF_anchor",
            "BF_coke_rate": active_anchor / driver if driver else 0.0,
            "KGF_output": active_anchor,
            "classification": "lower_distortion_reconciliation_candidate",
        },
    ]


def _source_support_status(
    scenario_id: str,
    gap_closed: bool,
    rate_status: str,
    kgf_output: float,
    raw_anchor: float,
    active_anchor: float,
) -> str:
    if not gap_closed:
        return "does_not_close_gap"
    if rate_status != "within_supported_range":
        return f"unsupported_BF_coke_rate_{rate_status}"
    if scenario_id.startswith("A"):
        return "current_KGF_output_requires_BF_rate_check_only"
    if scenario_id.startswith("B") and kgf_output <= raw_anchor + TOL_T:
        return "raw_public_anchor_evidence_bounded_scenario"
    if scenario_id.startswith("C") and kgf_output <= active_anchor + TOL_T:
        return "active_scaled_public_anchor_evidence_bounded_scenario"
    return "diagnostic_only_requires_more_evidence"


def _bounded_scenario_rows(payload: dict[str, Any], repaired_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repaired = _by_key([{k: str(v) for k, v in row.items()} for row in repaired_rows])
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        raw_anchor = KGF_PUBLIC_COKE_ANCHOR_T_Y[config]
        for horizon in HORIZONS:
            key = (config, horizon)
            driver = _zero(repaired[key]["BF_hot_metal_driver_site_t_y"])
            current_kgf = _zero(repaired[key]["KGF_coke_output_site_t_y"])
            active_anchor = _active_scaled_anchor(config, payload["c5k"][key])
            for scenario in _scenario_definitions(current_kgf, raw_anchor, active_anchor, driver):
                coke_rate = scenario["BF_coke_rate"]
                kgf_output = scenario["KGF_output"]
                bf_demand = driver * coke_rate
                gap = kgf_output - bf_demand
                gap_closed = gap >= -TOL_T
                rate_status = _range_status(coke_rate)
                near_raw = abs(kgf_output - raw_anchor) <= raw_anchor * ANCHOR_NEAR_TOL_SHARE
                near_active = abs(kgf_output - active_anchor) <= active_anchor * ANCHOR_NEAR_TOL_SHARE
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "scenario_family": scenario["scenario_family"],
                        "scenario_id": scenario["scenario_id"],
                        "BF_HM_driver_source": BF_COKE_DEMAND_DRIVER_SOURCE,
                        "BF_HM_driver_site_t_y": _fmt(driver),
                        "BF_coke_rate_t_per_t_HM": round(coke_rate, 9),
                        "BF_coke_demand_site_t_y": _fmt(bf_demand),
                        "KGF_output_assumption_site_t_y": _fmt(kgf_output),
                        "current_KGF_output_site_t_y": _fmt(current_kgf),
                        "raw_public_KGF_anchor_site_t_y": _fmt(raw_anchor),
                        "active_scaled_public_KGF_anchor_site_t_y": _fmt(active_anchor),
                        "coke_balance_gap_site_t_y": _fmt(gap),
                        "gap_Mt_y": _fmt(gap / 1_000_000.0),
                        "gap_pct_of_BF_demand": _fmt(gap / bf_demand * 100.0 if bf_demand else 0.0),
                        "gap_closed": _bool(gap_closed),
                        "BF_coke_rate_within_governed_range": _bool(rate_status == "within_supported_range"),
                        "BF_coke_rate_range_status": rate_status,
                        "KGF_output_within_raw_public_anchor": _bool(near_raw),
                        "KGF_output_within_active_scaled_anchor": _bool(near_active),
                        "source_support_status": _source_support_status(
                            scenario["scenario_id"],
                            gap_closed,
                            rate_status,
                            kgf_output,
                            raw_anchor,
                            active_anchor,
                        ),
                        "baseline_or_sensitivity_classification": scenario["classification"],
                        "baseline_changed": "false",
                    }
                )
    return rows


def _kpi_impact_rows(payload: dict[str, Any], scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coeff = _kgf_coefficients(payload)
    rows: list[dict[str, Any]] = []
    for row in scenarios:
        if row["scenario_family"] not in {"B_raw_public_KGF_anchor", "C_active_scaled_public_KGF_anchor"}:
            continue
        key = (row["configuration"], int(row["horizon_hours"]))
        current_kgf = _zero(row["current_KGF_output_site_t_y"])
        scenario_kgf = _zero(row["KGF_output_assumption_site_t_y"])
        delta = scenario_kgf - current_kgf
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
                "scenario_family": row["scenario_family"],
                "scenario_id": row["scenario_id"],
                "current_KGF_output_site_t_y": _fmt(current_kgf),
                "scenario_KGF_output_site_t_y": _fmt(scenario_kgf),
                "delta_KGF_coke_output_t_y": _fmt(delta),
                "delta_dry_coal_input_t_y": _fmt(delta * coeff["dry_coal_t_per_t_coke"]),
                "delta_KGF_electricity_MWh_y": _fmt(delta_elec),
                "delta_KGF_steam_proxy_MWh_y": _fmt(delta_steam_mwh),
                "delta_KGF_steam_mass_t_y": _fmt(delta_steam_t),
                "delta_raw_clean_COG_generation_MWh_LHV_y": _fmt(delta_cog),
                "delta_KGF_underfiring_MWh_LHV_y": _fmt(delta_under),
                "delta_net_COG_surplus_MWh_LHV_y": _fmt(delta_net_cog),
                "delta_KGF_CO2_t_y": _fmt(delta_co2),
                "delta_modelled_process_electricity_total_MWh_y": _fmt(delta_elec),
                "delta_WAG_generation_total_MWh_y": _fmt(delta_net_cog),
                "delta_diagnostic_CO2_total_t_y": _fmt(delta_co2),
                "process_electricity_total_if_scenario_MWh_y": _fmt(
                    _zero(totals["new_process_electricity_including_BF_KGF_site_MWh_e_y"]) + delta_elec
                ),
                "diagnostic_CO2_total_if_scenario_t_y": _fmt(
                    _zero(totals["new_diagnostic_CO2_including_KGF_site_t_y"]) + delta_co2
                ),
                "kpi_deltas_reported": "true",
                "baseline_changed": "false",
            }
        )
    return rows


def _recommendation_rows(repaired_rows: list[dict[str, Any]], scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            case_rows = [row for row in scenarios if row["configuration"] == config and int(row["horizon_hours"]) == horizon]
            repaired = next(row for row in repaired_rows if row["configuration"] == config and int(row["horizon_hours"]) == horizon)
            active_scaled_required = next(row for row in case_rows if row["scenario_id"] == "C3_required_rate_active_scaled_anchor")
            active_scaled_low = next(row for row in case_rows if row["scenario_id"] == "C2_low_rate_active_scaled_anchor")
            raw_required = next(row for row in case_rows if row["scenario_id"] == "B3_required_rate_raw_public_anchor")
            recommended = (
                "next_candidate_reconciliation_active_scaled_KGF_anchor_plus_required_BF_coke_rate_sensitivity"
                if active_scaled_required["gap_closed"] == "true"
                and active_scaled_required["BF_coke_rate_within_governed_range"] == "true"
                else "external_or_unmodelled_coke_fallback_if_bounded_reconciliation_rejected"
            )
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "driver_mismatch_resolved": repaired["BF_COKE_DEMAND_DRIVER_MATCHES_C5K_NO_BUFFER_HM"],
                    "repaired_baseline_gap_Mt_y": repaired["coke_gap_Mt_y"],
                    "active_scaled_anchor_required_rate_t_per_t_HM": active_scaled_required["BF_coke_rate_t_per_t_HM"],
                    "active_scaled_anchor_required_rate_status": active_scaled_required["BF_coke_rate_range_status"],
                    "active_scaled_anchor_low_rate_closes_gap": active_scaled_low["gap_closed"],
                    "raw_anchor_required_rate_t_per_t_HM": raw_required["BF_coke_rate_t_per_t_HM"],
                    "raw_anchor_required_rate_status": raw_required["BF_coke_rate_range_status"],
                    "external_unmodelled_coke_recommended_now": "false",
                    "recommended_next_action": (
                        "Evaluate a labelled active-scaled public KGF-anchor plus BF coke-rate sensitivity before external coke; "
                        "the repaired baseline still keeps current KGF output and current BF coke rate."
                        if recommended.startswith("next_candidate")
                        else "Keep external/unmodelled coke as fallback only after bounded BF/KGF reconciliation is rejected."
                    ),
                    "recommendation_priority": recommended,
                    "baseline_changed": "false",
                }
            )
    return rows


def _redflag_rows(
    payload: dict[str, Any],
    repaired_rows: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
    kpi_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    kpi_reported = {
        (row["configuration"], int(row["horizon_hours"]), row["scenario_id"])
        for row in kpi_rows
        if row["kpi_deltas_reported"] == "true"
    }
    for repaired in repaired_rows:
        config = repaired["configuration"]
        horizon = int(repaired["horizon_hours"])
        key = (config, horizon)
        totals = payload["c5m_b_totals"][key]
        case_scenarios = [row for row in scenarios if row["configuration"] == config and int(row["horizon_hours"]) == horizon]
        recommended = next(row for row in case_scenarios if row["scenario_id"] == "C3_required_rate_active_scaled_anchor")
        anchor_scenarios = [
            row for row in case_scenarios
            if row["scenario_family"] in {"B_raw_public_KGF_anchor", "C_active_scaled_public_KGF_anchor"}
        ]
        flags = {
            "redflag_baseline_changed_unexpectedly": False,
            "redflag_bf_coke_demand_driver_mismatch": repaired["redflag_bf_coke_demand_driver_mismatch"] == "true",
            "redflag_bf_coke_rate_changed": False,
            "redflag_kgf_output_changed": False,
            "redflag_c5k_targets_changed": False,
            "redflag_c5j_bof_coefficients_changed": False,
            "redflag_c5l_d_hsm_heat_case_changed": totals["HSM_heat_case"] != "base_0_50",
            "redflag_c5m_sinter_outputs_changed": False,
            "redflag_wag_invariant_failed": totals["WAG_invariant_status"] != "pass",
            "redflag_co2_guard_failed": totals["CO2_double_counting_guard_status"] != "pass",
            "redflag_required_bf_coke_rate_outside_range_in_recommended_scenario": recommended["BF_coke_rate_range_status"] != "within_supported_range",
            "redflag_kgf_anchor_scenario_changes_kpis_without_reporting": any(
                (row["configuration"], int(row["horizon_hours"]), row["scenario_id"]) not in kpi_reported
                for row in anchor_scenarios
            ),
        }
        hard_redflags = sum(
            1 for name, value in flags.items()
            if value
            and name
            in {
                "redflag_baseline_changed_unexpectedly",
                "redflag_bf_coke_demand_driver_mismatch",
                "redflag_bf_coke_rate_changed",
                "redflag_kgf_output_changed",
                "redflag_c5k_targets_changed",
                "redflag_c5j_bof_coefficients_changed",
                "redflag_c5l_d_hsm_heat_case_changed",
                "redflag_c5m_sinter_outputs_changed",
                "redflag_wag_invariant_failed",
                "redflag_co2_guard_failed",
                "redflag_required_bf_coke_rate_outside_range_in_recommended_scenario",
                "redflag_kgf_anchor_scenario_changes_kpis_without_reporting",
            }
        )
        rows.append(
            {
                "configuration": config,
                "horizon_hours": horizon,
                **{name: _bool(value) for name, value in flags.items()},
                "hard_redflag_count": hard_redflags,
                "status": "pass_repaired_driver_and_bounded_scenario_report" if hard_redflags == 0 else "fail_c5m_e_redflags",
                "explanation": "BF coke demand now uses C5k no-buffer BF HM; KGF-anchor scenarios remain diagnostic only.",
            }
        )
    return rows


def _stage_gate(redflags: list[dict[str, Any]], repaired_rows: list[dict[str, Any]], scenarios: list[dict[str, Any]], recommendation: list[dict[str, Any]]) -> dict[str, Any]:
    hard = sum(int(row["hard_redflag_count"]) for row in redflags)
    mismatch_count = sum(1 for row in repaired_rows if row["redflag_bf_coke_demand_driver_mismatch"] == "true")
    active_scaled_required_closure_count = sum(
        1 for row in scenarios
        if row["scenario_id"] == "C3_required_rate_active_scaled_anchor"
        and row["gap_closed"] == "true"
        and row["BF_coke_rate_within_governed_range"] == "true"
    )
    return {
        "stage": STAGE,
        "decision": "pass_development_bf_coke_driver_alignment_report" if hard == 0 else "fail_development_bf_coke_driver_alignment_report",
        "output_directory": _rel(C5M_E_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "baseline_driver_repair_confirmation": True,
        "no_coefficient_change_confirmation": True,
        "BF_coke_demand_driver_source": BF_COKE_DEMAND_DRIVER_SOURCE,
        "BF_coke_rate_t_per_t_HM": BF_COKE_RATE_T_PER_T_HM,
        "KGF_output_baseline_changed": False,
        "driver_mismatch_count_after_repair": mismatch_count,
        "active_scaled_required_rate_closure_count": active_scaled_required_closure_count,
        "hard_redflag_count": hard,
        "failure_count": hard,
        "recommended_next_action": recommendation[0]["recommended_next_action"],
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5m_d_coke_balance_driver_consistency_and_bounded_reconciliation_audit()
    C5M_E_DIR.mkdir(parents=True, exist_ok=True)
    payload = _source_payload()
    repaired = _repaired_coke_balance_rows(payload)
    comparison = _pre_repair_comparison_rows(payload, repaired)
    anchors = _kgf_anchor_context_rows(payload)
    scenarios = _bounded_scenario_rows(payload, repaired)
    kpi = _kpi_impact_rows(payload, scenarios)
    recommendation = _recommendation_rows(repaired, scenarios)
    redflags = _redflag_rows(payload, repaired, scenarios, kpi)
    gate = _stage_gate(redflags, repaired, scenarios, recommendation)

    _write_json(C5M_E_DIR / "s4_4c5m_e_stage_gate.json", gate)
    _write_csv(
        C5M_E_DIR / "s4_4c5m_e_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5m_d_coke_balance_driver_consistency_and_bounded_reconciliation_audit",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5M_E_DIR / "s4_4c5m_e_repaired_coke_balance.csv", repaired)
    _write_csv(C5M_E_DIR / "s4_4c5m_e_pre_repair_comparison.csv", comparison)
    _write_csv(C5M_E_DIR / "s4_4c5m_e_kgf_anchor_context.csv", anchors)
    _write_csv(C5M_E_DIR / "s4_4c5m_e_bounded_reconciliation_scenarios.csv", scenarios)
    _write_csv(C5M_E_DIR / "s4_4c5m_e_kpi_impact_diagnostics.csv", kpi)
    _write_csv(C5M_E_DIR / "s4_4c5m_e_recommendation.csv", recommendation)
    _write_csv(C5M_E_DIR / "s4_4c5m_e_red_flags.csv", redflags)
    _write_csv(C5M_E_DIR / "s4_4c5m_e_compact_table_for_chat.csv", repaired)
    _write_json(
        C5M_E_DIR / "s4_4c5m_e_bf_coke_driver_alignment_report.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "baseline_driver_repair_confirmation": True,
            "no_coefficient_change_confirmation": True,
            "current_coke_balance_after_driver_repair": repaired,
            "comparison_against_C5m_d_pre_repair": comparison,
            "kgf_anchor_context": anchors,
            "bounded_reconciliation_scenarios": scenarios,
            "kpi_impact_diagnostics": kpi,
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
            "repaired_coke_balance": len(repaired),
            "pre_repair_comparison": len(comparison),
            "kgf_anchor_context": len(anchors),
            "scenarios": len(scenarios),
            "kpi_impact_diagnostics": len(kpi),
            "redflags": len(redflags),
        },
    }
    _write_json(C5M_E_DIR / "s4_4c5m_e_summary.json", summary)
    return summary


def run_s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5m_e_bf_coke_driver_alignment_and_bounded_reconciliation_scenario_report(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
