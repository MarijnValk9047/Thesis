"""S4.4c5m_c coke-balance root-cause and resolution-options audit.

This stage is diagnostic only. It reads the accepted C5m_b baseline reports,
explains the open BF/KGF coke-balance gap, and computes what-if resolution
options without changing any baseline model equations, coefficients, targets,
route splits, WAG allocation, or CO2 accounting.
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
    WAG_TOL_MWH,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5h_blast_furnace_controller_parameterisation import (
    BF_CARBON_ACCOUNTING_MODE,
    BF_COKE_RATE_T_PER_T_HM,
    C5H_DIR,
)
from .s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration import (
    C5M_B_DIR,
    run_s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration,
)


STAGE = "S4.4c5m_c_coke_balance_root_cause_and_resolution_options_audit"
C5M_C_DIR = S4_ROOT / "s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit"
DEPENDENCY_CHAIN = "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b -> C5m_c"
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_table_and_redflag_report_pattern;"
    "what_if_rows_are_diagnostic_only"
)

BF_COKE_RATE_LOW = 0.282
BF_COKE_RATE_HIGH = 0.515
KGF_PUBLIC_COKE_ANCHOR_T_Y = {C0: 1_800_000.0, C1: 1_000_000.0}
KGF_PUBLIC_ANCHOR_STATUS = {
    C0: "MER/source-card public anchor: KGF1+KGF2 approximately 1.8 Mt coke/y in reference topology",
    C1: "MER/source-card public anchor: retained KGF1 approximately 1.0 Mt coke/y; KGF2 inactive",
}
TOL_T = 1.0
TOL = 1e-9


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _rows_by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], list[dict[str, str]]]:
    out: dict[tuple[str, int], list[dict[str, str]]] = {}
    for row in rows:
        out.setdefault((row["configuration"], int(row["horizon_hours"])), []).append(row)
    return out


def _param_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["parameter_id"]: row for row in rows}


def _status_in_range(value: float, low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "missing_source_range"
    if value < low - 1e-12:
        return "below_candidate_range"
    if value > high + 1e-12:
        return "above_candidate_range"
    return "within_candidate_range"


def _range_low_high(row: dict[str, str]) -> tuple[float | None, float | None]:
    low = row.get("low_value", "")
    high = row.get("high_value", "")
    return (_zero(low) if low not in ("", None) else None, _zero(high) if high not in ("", None) else None)


def _active_kgf_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("active") in {"True", "true"} and _zero(row["coke_output_site_t_y"]) > TOL_T]


def _sum(rows: list[dict[str, str]], field: str) -> float:
    return sum(_zero(row.get(field, "")) for row in rows)


def _source_payload() -> dict[str, Any]:
    current = _by_key(_read_csv(C5M_B_DIR / "s4_4c5m_b_coke_balance_diagnostic.csv"))
    totals = _by_key(_read_csv(C5M_B_DIR / "s4_4c5m_b_modelled_totals.csv"))
    c5m_b_redflags = _by_key(_read_csv(C5M_B_DIR / "s4_4c5m_b_red_flags.csv"))
    c5m_b_change = _read_csv(C5M_B_DIR / "s4_4c5m_b_change_detection.csv")
    kgf = _rows_by_key(_read_csv(C5F_DIR / "s4_4c5f_coking_plant_diagnostics.csv"))
    kgf_params = _param_map(_read_csv(C5F_DIR / "s4_4c5f_kgf_parameter_values.csv"))
    bf = _rows_by_key(_read_csv(C5H_DIR / "s4_4c5h_bf_process_diagnostics.csv"))
    bf_params = _param_map(_read_csv(C5H_DIR / "s4_4c5h_bf_parameter_values.csv"))
    return locals()


def _source_range_summary(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "parameter_id": "BF_COKE_RATE_T_PER_T_HM",
            "base_value": _fmt(BF_COKE_RATE_T_PER_T_HM),
            "low_value": _fmt(BF_COKE_RATE_LOW),
            "high_value": _fmt(BF_COKE_RATE_HIGH),
            "unit": "t coke/t HM",
            "source_or_assumption_id": "source_cards/Blast_Furnace_Parameters.md",
            "status": "source_backed_development_assumption_not_thesis_approved",
            "notes": "C5h active value; source card explicitly says coke-balance gaps should be reported, not hidden.",
        },
        {
            "parameter_id": "KGF_COKE_OUTPUT_PUBLIC_ANCHOR_C0",
            "base_value": _fmt(KGF_PUBLIC_COKE_ANCHOR_T_Y[C0]),
            "low_value": "",
            "high_value": "",
            "unit": "t coke/y",
            "source_or_assumption_id": "source_cards/Coking_Plants_Parameters.md",
            "status": "validation_context_anchor_not_dispatch_constraint",
            "notes": KGF_PUBLIC_ANCHOR_STATUS[C0],
        },
        {
            "parameter_id": "KGF_COKE_OUTPUT_PUBLIC_ANCHOR_C1",
            "base_value": _fmt(KGF_PUBLIC_COKE_ANCHOR_T_Y[C1]),
            "low_value": "",
            "high_value": "",
            "unit": "t coke/y",
            "source_or_assumption_id": "source_cards/Coking_Plants_Parameters.md",
            "status": "validation_context_anchor_not_dispatch_constraint",
            "notes": KGF_PUBLIC_ANCHOR_STATUS[C1],
        },
    ]
    for pid in (
        "DRY_COAL_PER_COKE_TPT",
        "COG_YIELD_NM3_PER_T_COKE",
        "COG_LHV_MJ_PER_NM3",
        "KGF_UNDERFIRING_GJ_PER_T_COKE",
        "KGF_ELECTRICITY_MWH_PER_T_COKE",
        "KGF_STEAM_GJ_PER_T_COKE",
        "KGF_STEAM_T_PER_T_COKE_DIAGNOSTIC",
        "KGF_DIRECT_CO2_T_PER_T_COKE",
    ):
        row = payload["kgf_params"][pid]
        rows.append(
            {
                "parameter_id": pid,
                "base_value": row["base_value"],
                "low_value": row["low_value"],
                "high_value": row["high_value"],
                "unit": row["unit"],
                "source_or_assumption_id": row["source_or_assumption_id"],
                "status": f"{row['evidence_status']};{row['executable_status']};thesis_usability={row['thesis_usability']}",
                "notes": row["notes"],
            }
        )
    return rows


def _current_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        anchor = KGF_PUBLIC_COKE_ANCHOR_T_Y[config]
        for horizon in HORIZONS:
            key = (config, horizon)
            current = payload["current"][key]
            kgf_rows = payload["kgf"][key]
            bf_rows = payload["bf"][key]
            active_kgf = _active_kgf_rows(kgf_rows)
            bf_hm = _sum(bf_rows, "hot_metal_site_t_y")
            bf_coke = _zero(current["BF_coke_demand_site_t_y"])
            kgf_coke = _zero(current["KGF_coke_production_site_t_y"])
            gap = _zero(current["coke_balance_gap_site_t_y"])
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "BF_hot_metal_output_site_t_y": _fmt(bf_hm),
                    "BF_COKE_RATE_T_PER_T_HM_active_value": _fmt(BF_COKE_RATE_T_PER_T_HM),
                    "BF_coke_demand_site_t_y": _fmt(bf_coke),
                    "active_KGF_units": ";".join(row["plant_id"] for row in active_kgf),
                    "KGF1_coke_output_site_t_y": _fmt(next((_zero(row["coke_output_site_t_y"]) for row in kgf_rows if row["plant_id"] == "KGF1"), 0.0)),
                    "KGF2_coke_output_site_t_y": _fmt(next((_zero(row["coke_output_site_t_y"]) for row in kgf_rows if row["plant_id"] == "KGF2"), 0.0)),
                    "total_KGF_coke_output_site_t_y": _fmt(kgf_coke),
                    "coke_balance_gap_site_t_y": _fmt(gap),
                    "coke_gap_pct_of_BF_coke_demand": _fmt(gap / bf_coke * 100.0 if bf_coke else 0.0),
                    "coke_gap_pct_of_KGF_coke_output": _fmt(gap / kgf_coke * 100.0 if kgf_coke else 0.0),
                    "KGF_public_anchor_t_y": _fmt(anchor),
                    "KGF_production_anchor_gap_t_y": _fmt(kgf_coke - anchor),
                    "KGF_production_anchor_gap_pct": _fmt((kgf_coke - anchor) / anchor * 100.0),
                    "BF_coke_rate_source_range_status": "base=0.359;low=0.282;high=0.515;source_backed_development_not_Tata_specific",
                    "KGF_coke_output_anchor_source_status": KGF_PUBLIC_ANCHOR_STATUS[config],
                    "caused_by_BF_coke_demand_too_high_relative_to_KGF_anchor": str(bf_coke > anchor + TOL_T).lower(),
                    "caused_by_KGF_output_too_low_relative_to_BF_demand": str(kgf_coke < bf_coke - TOL_T).lower(),
                    "caused_by_active_production_target_scaling": str(kgf_coke < anchor - TOL_T).lower(),
                    "caused_by_C0_C1_topology_closure": str(config == C1).lower(),
                    "caused_by_missing_external_coke_import_policy": "true",
                    "caused_by_missing_pellet_or_burden_substitution_logic": "true",
                    "reporting_only_issue": "false",
                    "root_cause_summary": "BF coke demand exceeds both current KGF output and the public KGF anchor; no external coke/import or burden-substitution closure policy is active.",
                }
            )
    return rows


def _option_a_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        anchor = KGF_PUBLIC_COKE_ANCHOR_T_Y[config]
        for horizon in HORIZONS:
            key = (config, horizon)
            current = payload["current"][key]
            totals = payload["totals"][key]
            kgf_rows = _active_kgf_rows(payload["kgf"][key])
            bf_coke = _zero(current["BF_coke_demand_site_t_y"])
            kgf_coke = _zero(current["KGF_coke_production_site_t_y"])
            scale = bf_coke / kgf_coke if kgf_coke else 0.0
            add_coke = max(bf_coke - kgf_coke, 0.0)
            add_coal = _sum(kgf_rows, "dry_coal_input_site_t_y") * (scale - 1.0)
            add_elec = _sum(kgf_rows, "KGF_electricity_site_MWh_y") * (scale - 1.0)
            add_steam_mwh = _sum(kgf_rows, "KGF_steam_site_MWh_proxy_y") * (scale - 1.0)
            add_steam_t = sum(_zero(row["coke_output_site_t_y"]) * _zero(row["KGF_steam_mass_t_per_t_coke_diagnostic"]) for row in kgf_rows) * (scale - 1.0)
            add_cog_gross = _sum(kgf_rows, "gross_COG_site_MWh_LHV_y") * (scale - 1.0)
            add_under = _sum(kgf_rows, "COG_to_KGF_underfiring_site_MWh_LHV_y") * (scale - 1.0)
            add_surplus = _sum(kgf_rows, "surplus_COG_site_MWh_LHV_y") * (scale - 1.0)
            add_co2 = _sum(kgf_rows, "KGF_direct_CO2_site_t_y") * (scale - 1.0)
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "option_id": "A_scale_KGF_output_to_BF_coke_demand",
                    "required_KGF_coke_output_site_t_y": _fmt(bf_coke),
                    "current_KGF_coke_output_site_t_y": _fmt(kgf_coke),
                    "required_increase_t_y": _fmt(add_coke),
                    "required_increase_Mt_y": _fmt(add_coke / 1_000_000.0),
                    "scaling_factor": _fmt(scale),
                    "KGF_public_anchor_t_y": _fmt(anchor),
                    "gap_to_KGF_public_anchor_t_y": _fmt(bf_coke - anchor),
                    "required_output_exceeds_source_anchor": str(bf_coke > anchor + TOL_T).lower(),
                    "exceeds_active_unit_topology": str(config == C1 and bf_coke > anchor + TOL_T).lower(),
                    "additional_dry_coal_input_t_y": _fmt(add_coal),
                    "additional_KGF_electricity_MWh_y": _fmt(add_elec),
                    "additional_KGF_steam_proxy_MWh_y": _fmt(add_steam_mwh),
                    "additional_KGF_steam_mass_t_y": _fmt(add_steam_t),
                    "additional_raw_clean_COG_generation_MWh_LHV_y": _fmt(add_cog_gross),
                    "additional_KGF_underfiring_MWh_LHV_y": _fmt(add_under),
                    "additional_net_COG_surplus_MWh_LHV_y": _fmt(add_surplus),
                    "additional_KGF_CO2_t_y": _fmt(add_co2),
                    "changed_total_WAG_generation_MWh_y": _fmt(add_surplus),
                    "changed_process_electricity_total_MWh_y": _fmt(_zero(totals["new_process_electricity_including_BF_KGF_site_MWh_e_y"]) + add_elec),
                    "changed_diagnostic_CO2_total_t_y": _fmt(_zero(totals["new_diagnostic_CO2_including_KGF_site_t_y"]) + add_co2),
                    "changed_WAG_controller_residual_or_interface_MWh_y": _fmt(add_surplus),
                    "coke_gap_after_option_t_y": _fmt(0.0),
                    "WAG_invariant_feasibility_status": "not_reoptimised;accounting_feasible_if_residual_or_interface_absorbs_extra_net_COG",
                    "baseline_changed": "false",
                }
            )
    return rows


def _option_b_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            current = payload["current"][key]
            bf_hm = _sum(payload["bf"][key], "hot_metal_site_t_y")
            kgf_coke = _zero(current["KGF_coke_production_site_t_y"])
            required = kgf_coke / bf_hm if bf_hm else 0.0
            status = _status_in_range(required, BF_COKE_RATE_LOW, BF_COKE_RATE_HIGH)
            pct_reduction = (BF_COKE_RATE_T_PER_T_HM - required) / BF_COKE_RATE_T_PER_T_HM * 100.0 if BF_COKE_RATE_T_PER_T_HM else 0.0
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "option_id": "B_reduce_BF_coke_rate_to_existing_KGF_output",
                    "active_BF_coke_rate_t_per_t_HM": _fmt(BF_COKE_RATE_T_PER_T_HM),
                    "required_BF_coke_rate_t_per_t_HM": _fmt(required),
                    "absolute_reduction_t_per_t_HM": _fmt(BF_COKE_RATE_T_PER_T_HM - required),
                    "percentage_reduction": _fmt(pct_reduction),
                    "BF_coke_rate_low": _fmt(BF_COKE_RATE_LOW),
                    "BF_coke_rate_high": _fmt(BF_COKE_RATE_HIGH),
                    "required_rate_range_status": status,
                    "implied_HM_per_t_coke_active": _fmt(1.0 / BF_COKE_RATE_T_PER_T_HM),
                    "implied_HM_per_t_coke_required": _fmt(1.0 / required if required else 0.0),
                    "implied_coke_efficiency_improvement_pct": _fmt((1.0 / required) / (1.0 / BF_COKE_RATE_T_PER_T_HM) * 100.0 - 100.0 if required else 0.0),
                    "BF_coke_demand_after_option_t_y": _fmt(kgf_coke),
                    "KGF_coke_output_unchanged_t_y": _fmt(kgf_coke),
                    "COG_generation_changed": "false",
                    "KGF_electricity_steam_CO2_changed": "false",
                    "BF_CO2_current_mode": BF_CARBON_ACCOUNTING_MODE,
                    "BF_CO2_change_under_current_mode": "unchanged_under_aggregate_hot_metal_counter",
                    "BF_CO2_if_coke_carbon_explicit_mode": "blocked_missing_governed_reaccounting_layer",
                    "WAG_totals_changed_under_current_model": "false",
                    "coke_gap_after_option_t_y": _fmt(0.0),
                    "baseline_changed": "false",
                    "recommendation_role": "unsupported_without_new_evidence" if status == "below_candidate_range" else "candidate_sensitivity_not_base",
                }
            )
    return rows


def _option_c_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            current = payload["current"][key]
            totals = payload["totals"][key]
            external = max(_zero(current["BF_coke_demand_site_t_y"]) - _zero(current["KGF_coke_production_site_t_y"]), 0.0)
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "option_id": "C_explicit_external_or_unmodelled_coke_supply",
                    "external_coke_supply_to_BF_t_y": _fmt(external),
                    "external_coke_supply_to_BF_Mt_y": _fmt(external / 1_000_000.0),
                    "KGF_coke_output_unchanged_t_y": current["KGF_coke_production_site_t_y"],
                    "BF_coke_demand_unchanged_t_y": current["BF_coke_demand_site_t_y"],
                    "coke_balance_residual_after_external_supply_t_y": _fmt(0.0),
                    "process_electricity_changed": "false",
                    "onsite_COG_generation_changed": "false",
                    "onsite_KGF_CO2_changed": "false",
                    "BF_aggregate_CO2_changed_under_current_mode": "false",
                    "process_electricity_total_MWh_y": totals["new_process_electricity_including_BF_KGF_site_MWh_e_y"],
                    "diagnostic_CO2_total_t_y": totals["new_diagnostic_CO2_including_KGF_site_t_y"],
                    "external_coke_scope3_cost_emissions_status": "deferred_not_included_without_governed_external_coke_policy",
                    "interpretation": "explicit_material_balance_closure_through_external_or_unmodelled_coke_supply_not_public_Tata_truth",
                    "baseline_changed": "false",
                }
            )
    return rows


def _option_d_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = [
        ("DRY_COAL_PER_COKE_TPT", "required_dry_coal_per_t_coke_if_coal_constant", "coal_input_t_per_t_coke"),
        ("COG_YIELD_NM3_PER_T_COKE", "required_COG_yield_Nm3_per_t_coke_if_COG_constant", "COG_yield_Nm3_per_t_coke"),
        ("KGF_UNDERFIRING_GJ_PER_T_COKE", "required_underfiring_GJ_per_t_coke_if_underfiring_constant", "underfiring_GJ_per_t_coke"),
        ("KGF_ELECTRICITY_MWH_PER_T_COKE", "required_electricity_MWh_per_t_coke_if_electricity_constant", "electricity_MWh_per_t_coke"),
        ("KGF_STEAM_GJ_PER_T_COKE", "required_steam_GJ_per_t_coke_if_steam_energy_constant", "steam_GJ_per_t_coke"),
        ("KGF_STEAM_T_PER_T_COKE_DIAGNOSTIC", "required_steam_t_per_t_coke_if_steam_mass_constant", "steam_mass_t_per_t_coke"),
        ("KGF_DIRECT_CO2_T_PER_T_COKE", "required_CO2_t_per_t_coke_if_CO2_constant", "direct_CO2_t_per_t_coke"),
    ]
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            current = payload["current"][key]
            kgf_coke = _zero(current["KGF_coke_production_site_t_y"])
            required_coke = _zero(current["BF_coke_demand_site_t_y"])
            scale = required_coke / kgf_coke if kgf_coke else 0.0
            for pid, label, metric in metrics:
                param = payload["kgf_params"][pid]
                active = _zero(param["base_value"])
                required = active / scale if scale else 0.0
                low, high = _range_low_high(param)
                status = _status_in_range(required, low, high)
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "option_id": "D_more_coke_same_KGF_KPIs_efficiency_what_if",
                        "metric": metric,
                        "required_intensity_field": label,
                        "active_value": _fmt(active),
                        "required_value": _fmt(required),
                        "low_value": _fmt(low) if low is not None else "",
                        "high_value": _fmt(high) if high is not None else "",
                        "unit": param["unit"],
                        "scaling_factor_to_close_gap": _fmt(scale),
                        "candidate_range_status": status,
                        "source_or_assumption_id": param["source_or_assumption_id"],
                        "evidence_status": param["evidence_status"],
                        "baseline_changed": "false",
                    }
                )
    return rows


def _comparison_rows(
    current: list[dict[str, Any]],
    option_a: list[dict[str, Any]],
    option_b: list[dict[str, Any]],
    option_c: list[dict[str, Any]],
    option_d: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    outside_d = any(row["candidate_range_status"] != "within_candidate_range" for row in option_d)
    option_b_below = any(row["required_rate_range_status"] == "below_candidate_range" for row in option_b)
    option_a_exceeds = any(row["required_output_exceeds_source_anchor"] == "true" for row in option_a)
    rows.append(
        {
            "option_id": "Current_C5m_b_baseline",
            "coke_gap_closed": "false",
            "changes_onsite_KGF_production": "false",
            "changes_coal_input": "false",
            "changes_COG_generation": "false",
            "changes_KGF_electricity": "false",
            "changes_KGF_steam": "false",
            "changes_diagnostic_CO2": "false",
            "changes_WAG_surplus": "false",
            "violates_or_overshoots_KGF_anchors": "not_applicable",
            "requires_coefficient_change": "false",
            "source_support_level": "accepted_development_baseline_with_open_gap",
            "thesis_risk": "material_balance_gap_remains_visible",
            "recommended_role": "current_reference_only_not_final_material_closure",
        }
    )
    rows.append(
        {
            "option_id": "A_scale_KGF_output_to_BF_coke_demand",
            "coke_gap_closed": "true",
            "changes_onsite_KGF_production": "true",
            "changes_coal_input": "true",
            "changes_COG_generation": "true",
            "changes_KGF_electricity": "true",
            "changes_KGF_steam": "true",
            "changes_diagnostic_CO2": "true",
            "changes_WAG_surplus": "true",
            "violates_or_overshoots_KGF_anchors": str(option_a_exceeds).lower(),
            "requires_coefficient_change": "false_but_requires_output_anchor_override_or_capacity_policy",
            "source_support_level": "weak_for_base_if_anchor_exceeded",
            "thesis_risk": "large_scope_expansion_and_WAG_CO2_reconciliation_risk",
            "recommended_role": "not_base_without_explicit_source_support;possible_stress_sensitivity",
        }
    )
    rows.append(
        {
            "option_id": "B_reduce_BF_coke_rate_to_existing_KGF_output",
            "coke_gap_closed": "true",
            "changes_onsite_KGF_production": "false",
            "changes_coal_input": "false_for_KGF",
            "changes_COG_generation": "false",
            "changes_KGF_electricity": "false",
            "changes_KGF_steam": "false",
            "changes_diagnostic_CO2": "false_under_current_BF_aggregate_mode",
            "changes_WAG_surplus": "false_under_current_BFG_by_HM_model",
            "violates_or_overshoots_KGF_anchors": "false",
            "requires_coefficient_change": "true_BF_coke_rate",
            "source_support_level": "unsupported_if_required_rate_below_low_range" if option_b_below else "candidate_sensitivity",
            "thesis_risk": "coefficient_tuning_risk_if_used_to_close_gap",
            "recommended_role": "reject_as_base_current_required_rate_below_supported_range" if option_b_below else "labelled_sensitivity",
        }
    )
    rows.append(
        {
            "option_id": "C_explicit_external_or_unmodelled_coke_supply",
            "coke_gap_closed": "true",
            "changes_onsite_KGF_production": "false",
            "changes_coal_input": "false_onsite",
            "changes_COG_generation": "false_onsite",
            "changes_KGF_electricity": "false",
            "changes_KGF_steam": "false",
            "changes_diagnostic_CO2": "false_onsite_current_scope",
            "changes_WAG_surplus": "false",
            "violates_or_overshoots_KGF_anchors": "false",
            "requires_coefficient_change": "false_requires_new_explicit_material_policy",
            "source_support_level": "clean_modelling_closure_but_external_coke_evidence_deferred",
            "thesis_risk": "must_not_be_claimed_as_Tata_import_truth;external_cost_scope3_deferred",
            "recommended_role": "lowest_governance_risk_next_development_patch_as_explicit_closure_policy",
        }
    )
    rows.append(
        {
            "option_id": "D_KGF_efficiency_improvement_more_coke_same_KPIs",
            "coke_gap_closed": "true_if_all_intensities_changed",
            "changes_onsite_KGF_production": "true",
            "changes_coal_input": "held_constant_by_assumption",
            "changes_COG_generation": "held_constant_by_assumption",
            "changes_KGF_electricity": "held_constant_by_assumption",
            "changes_KGF_steam": "held_constant_by_assumption",
            "changes_diagnostic_CO2": "held_constant_by_assumption",
            "changes_WAG_surplus": "held_constant_by_assumption",
            "violates_or_overshoots_KGF_anchors": str(option_a_exceeds).lower(),
            "requires_coefficient_change": "true_multiple_KGF_intensities",
            "source_support_level": "unsupported_for_base" if outside_d else "possible_sensitivity",
            "thesis_risk": "high_if_more_coke_is_assumed_without_matching_material_energy_emissions_changes",
            "recommended_role": "reject_as_base;only_reopen_if_new_evidence_supports_efficiency_package",
        }
    )
    return rows


def _redflag_rows(
    payload: dict[str, Any],
    current: list[dict[str, Any]],
    option_a: list[dict[str, Any]],
    option_b: list[dict[str, Any]],
    option_d: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    non_scope_changes = [
        row for row in payload["c5m_b_change"]
        if row["expected_total_scope_expansion_due_to_BF_KGF_ledger_inclusion"] != "true" and row["status"] != "pass"
    ]
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            a = next(row for row in option_a if row["configuration"] == config and int(row["horizon_hours"]) == horizon)
            b = next(row for row in option_b if row["configuration"] == config and int(row["horizon_hours"]) == horizon)
            d_rows = [row for row in option_d if row["configuration"] == config and int(row["horizon_hours"]) == horizon]
            flags = {
                "redflag_baseline_changed": False,
                "redflag_bf_coke_rate_changed": False,
                "redflag_kgf_coke_output_changed": False,
                "redflag_c5k_targets_changed": bool(non_scope_changes),
                "redflag_c5m_b_kpis_changed": bool(non_scope_changes),
                "redflag_option_A_exceeds_KGF_anchor": a["required_output_exceeds_source_anchor"] == "true",
                "redflag_option_B_required_coke_rate_below_supported_range": b["required_rate_range_status"] == "below_candidate_range",
                "redflag_option_D_required_intensity_outside_supported_range": any(row["candidate_range_status"] != "within_candidate_range" for row in d_rows),
                "redflag_missing_source_range_for_efficiency_claim": any(row["candidate_range_status"] == "missing_source_range" for row in d_rows),
                "redflag_unexplained_coke_gap_still_hidden": False,
                "redflag_WAG_invariant_failed": payload["totals"][key]["WAG_invariant_status"] != "pass",
                "redflag_CO2_guard_failed": payload["totals"][key]["CO2_double_counting_guard_status"] != "pass",
            }
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    **{name: str(value).lower() for name, value in flags.items()},
                    "baseline_hard_redflag_count": sum(
                        1
                        for name, value in flags.items()
                        if value
                        and name
                        in {
                            "redflag_baseline_changed",
                            "redflag_bf_coke_rate_changed",
                            "redflag_kgf_coke_output_changed",
                            "redflag_c5k_targets_changed",
                            "redflag_c5m_b_kpis_changed",
                            "redflag_unexplained_coke_gap_still_hidden",
                            "redflag_WAG_invariant_failed",
                            "redflag_CO2_guard_failed",
                        }
                    ),
                    "option_redflag_count": sum(
                        1
                        for name, value in flags.items()
                        if value
                        and name
                        in {
                            "redflag_option_A_exceeds_KGF_anchor",
                            "redflag_option_B_required_coke_rate_below_supported_range",
                            "redflag_option_D_required_intensity_outside_supported_range",
                            "redflag_missing_source_range_for_efficiency_claim",
                        }
                    ),
                    "status": "pass_baseline_unchanged_with_option_caveats",
                    "explanation": "Option red flags describe unsupported what-if choices; accepted C5m_b baseline artifacts remain unchanged.",
                }
            )
    return rows


def _stage_gate(redflags: list[dict[str, Any]], comparison: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_hard = sum(int(row["baseline_hard_redflag_count"]) for row in redflags)
    option_redflags = sum(int(row["option_redflag_count"]) for row in redflags)
    c0 = next(row for row in current if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    c1 = next(row for row in current if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    return {
        "stage": STAGE,
        "decision": "pass_development_coke_balance_audit_no_baseline_change" if baseline_hard == 0 else "fail_development_coke_balance_audit",
        "output_directory": _rel(C5M_C_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "no_baseline_change_confirmation": True,
        "baseline_hard_redflag_count": baseline_hard,
        "option_redflag_count": option_redflags,
        "failure_count": baseline_hard,
        "C0_24h_coke_gap_Mt_y": _zero(c0["coke_balance_gap_site_t_y"]) / 1_000_000.0,
        "C1_24h_coke_gap_Mt_y": _zero(c1["coke_balance_gap_site_t_y"]) / 1_000_000.0,
        "recommended_next_implementation_path": "Option_C_explicit_external_or_unmodelled_coke_supply_as_development_closure_policy;keep_Option_B_as_unsupported_until_new_BF_coke_rate_evidence",
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration()
    C5M_C_DIR.mkdir(parents=True, exist_ok=True)
    payload = _source_payload()
    source_summary = _source_range_summary(payload)
    current = _current_rows(payload)
    option_a = _option_a_rows(payload)
    option_b = _option_b_rows(payload)
    option_c = _option_c_rows(payload)
    option_d = _option_d_rows(payload)
    comparison = _comparison_rows(current, option_a, option_b, option_c, option_d)
    redflags = _redflag_rows(payload, current, option_a, option_b, option_d)
    gate = _stage_gate(redflags, comparison, current)

    _write_json(C5M_C_DIR / "s4_4c5m_c_stage_gate.json", gate)
    _write_csv(
        C5M_C_DIR / "s4_4c5m_c_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5M_C_DIR / "s4_4c5m_c_current_coke_balance_root_cause.csv", current)
    _write_csv(C5M_C_DIR / "s4_4c5m_c_source_range_summary.csv", source_summary)
    _write_csv(C5M_C_DIR / "s4_4c5m_c_option_A_kgf_scaling_impacts.csv", option_a)
    _write_csv(C5M_C_DIR / "s4_4c5m_c_option_B_bf_coke_rate_sensitivity.csv", option_b)
    _write_csv(C5M_C_DIR / "s4_4c5m_c_option_C_external_coke_supply.csv", option_c)
    _write_csv(C5M_C_DIR / "s4_4c5m_c_option_D_kgf_efficiency_intensity_what_if.csv", option_d)
    _write_csv(C5M_C_DIR / "s4_4c5m_c_option_comparison.csv", comparison)
    _write_csv(C5M_C_DIR / "s4_4c5m_c_red_flags.csv", redflags)
    _write_csv(C5M_C_DIR / "s4_4c5m_c_compact_table_for_chat.csv", current)
    _write_json(
        C5M_C_DIR / "s4_4c5m_c_coke_balance_audit_report.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "no_baseline_change_confirmation": True,
            "recommended_next_implementation_path": gate["recommended_next_implementation_path"],
            "current_coke_balance": current,
            "source_range_summary": source_summary,
            "option_comparison": comparison,
            "red_flags": redflags,
            "caveats": [
                "All options are what-if diagnostics only.",
                "No baseline coefficient, production target, route split, WAG allocation or CO2 accounting was changed.",
                "External/unmodelled coke supply is a material-balance closure option, not a public Tata import claim.",
            ],
        },
    )
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "recommended_next_implementation_path": gate["recommended_next_implementation_path"],
        "rows": {
            "current": len(current),
            "source_summary": len(source_summary),
            "option_A": len(option_a),
            "option_B": len(option_b),
            "option_C": len(option_c),
            "option_D": len(option_d),
            "comparison": len(comparison),
            "redflags": len(redflags),
        },
    }
    _write_json(C5M_C_DIR / "s4_4c5m_c_summary.json", summary)
    return summary


def run_s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
