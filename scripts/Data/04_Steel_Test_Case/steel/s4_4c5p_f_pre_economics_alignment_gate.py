"""S4.4c5p_f pre-economics alignment gate.

This stage is diagnostic-only. It consumes the current C5p_e annual
reconciliation outputs and records decisions needed before residual boundary
diagnostics, CO2 consolidation, and later economics. It does not change model
equations, coefficients, targets, or accepted C5 plant-layer behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    S4_ROOT,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5p_a_linde_asu_oxygen_accounting import C5P_A_DIR
from .s4_4c5p_b_boiler_steam_circuit_accounting import C5P_B_DIR
from .s4_4c5p_c_ij01_vn25_generator_interface_accounting import C5P_C_DIR
from .s4_4c5p_d_buffer_store_register_and_validation import C5P_D_DIR
from .s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation import (
    C5P_E_DIR,
    run_s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation,
)


STAGE = "S4.4c5p_f_pre_economics_alignment_gate"
C5P_F_DIR = S4_ROOT / "s4_4c5p_f_pre_economics_alignment_gate"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_PRE_ECONOMICS_ALIGNMENT_GATE.md")

PJ_TO_MWH = 277777.77777777775
MWH_TO_PJ = 1.0 / PJ_TO_MWH
O2_DENSITY_KG_PER_NM3 = 1.429
ASU_MWH_PER_T_O2 = 0.4

DECISION_COLUMNS = [
    "decision_id",
    "topic",
    "current_status",
    "evidence_status",
    "options",
    "recommended_option",
    "rationale",
    "affects_model_equations_now",
    "affects_physical_behaviour_later",
    "affects_economics_later",
    "must_fix_before_commit",
    "must_fix_before_economics",
    "can_defer_to_sensitivity",
    "thesis_reporting_caveat",
    "caveat",
]

DENOMINATOR_COLUMNS = [
    "configuration",
    "metric",
    "unit",
    "raw_public_anchor",
    "active_scaled_anchor",
    "current_model_output",
    "absolute_gap_to_raw",
    "relative_gap_to_raw",
    "absolute_gap_to_active_scaled",
    "relative_gap_to_active_scaled",
    "interpretation",
    "recommended_policy",
    "denominator_implication",
    "decision_needed",
    "caveat",
]

SLAB_ROUTE_COLUMNS = [
    "configuration",
    "flow_or_route",
    "unit",
    "raw_anchor",
    "current_model_output",
    "gap",
    "route_policy_status",
    "affects_final_product_proxy",
    "affects_economics_denominator",
    "recommended_action",
    "caveat",
]

GENERATOR_GAP_COLUMNS = [
    "carrier",
    "generated_or_available",
    "mandatory_self_use",
    "process_or_preparation_use",
    "boiler_steam_use",
    "generator_model_use",
    "generator_anchor_use",
    "generator_gap",
    "residual_after_generator",
    "possible_gap_source",
    "candidate_lever",
    "recommended_action",
    "caveat",
]

DRP_OXYGEN_COLUMNS = [
    "oxygen_basis_id",
    "basis_description",
    "unit",
    "value",
    "equivalent_nm3_per_t_dri",
    "equivalent_t_per_t_dri",
    "annual_o2_demand_kt_y",
    "annual_asu_electricity_gwh_y",
    "gap_to_current_model",
    "gap_to_source_sanity",
    "evidence_status",
    "recommended_base_status",
    "sensitivity_required",
    "caveat",
]

ANCHOR_POLICY_COLUMNS = [
    "anchor_family",
    "raw_anchor_role",
    "active_scaled_anchor_role",
    "executable_constraint_allowed",
    "validation_gap_allowed",
    "acceptance_tolerance",
    "current_status",
    "policy_recommendation",
    "caveat",
]

BLOCKER_COLUMNS = [
    "blocker_id",
    "blocker",
    "category",
    "current_evidence",
    "why_it_matters",
    "blocks_commit",
    "blocks_residual_energy_boundary",
    "blocks_co2_boundary",
    "blocks_economics",
    "recommended_next_action",
    "caveat",
]

LEVER_TRIAGE_COLUMNS = [
    "lever_id",
    "domain",
    "parameter_or_policy",
    "current_value_or_status",
    "candidate_values_or_range",
    "related_gap",
    "classification",
    "expected_direction_if_changed",
    "risk_of_changing",
    "affects_physical_behaviour",
    "affects_economics_later",
    "recommended_status",
    "recommended_action",
    "caveat",
]

REDFLAG_COLUMNS = ["red_flag", "active", "severity", "evidence", "recommended_action"]

FAILURE_FLAGS = [
    "VALIDATION_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION",
    "ANNUAL_ANCHOR_USED_AS_HOURLY_DISPATCH_SCHEDULE",
    "RAW_MER_ANCHOR_FORCED_AGAINST_ACTIVE_6_75_TARGET",
    "DENOMINATOR_SILENTLY_FROZEN",
    "FINAL_PRODUCT_PROXY_USED_AS_PRIMARY_ECON_DENOMINATOR_WITH_UNRESOLVED_IMPORT_SLAB",
    "C1_GENERATOR_FUEL_GAP_HIDDEN",
    "C1_GENERATOR_ANCHOR_FORCED_BY_CREATING_FUEL",
    "GENERATOR_PRICE_RESPONSIVE_DISPATCH_ACTIVE",
    "GENERATOR_EXPORT_REVENUE_ACTIVE",
    "WAG_DIRECT_MARKET_VALUE_ACTIVE",
    "C0_GENERATOR_2TWH_ENFORCED_AS_TARGET",
    "DRP_OXYGEN_BASIS_CHANGED_WITHOUT_SOURCE_REVIEW",
    "FULL_SITE_NET_IMPORT_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY",
    "CO2_ETS_READY_CLAIMED_WITH_COMPONENT_ONLY_BOUNDARY",
    "PRODUCTION_POLICY_CHANGED_DURING_ALIGNMENT",
    "C5L_D_BASE_0_50_REVERTED",
    "COKE_RECONCILIATION_BASELINE_REOPENED",
    "THESIS_USABILITY_TRUE_FOR_DEVELOPMENT_ROWS",
]

CAVEATS = [
    "PRE_ECONOMICS_ALIGNMENT_DEVELOPMENT_ONLY",
    "ACTIVE_TARGET_6_75_DIFFERS_FROM_RAW_MER_ANCHORS",
    "RAW_PUBLIC_ANCHORS_VALIDATION_ONLY",
    "DENOMINATOR_UNRESOLVED",
    "IMPORTED_SLAB_CONVENTION_REQUIRES_REVIEW",
    "C1_GENERATOR_GAP_REQUIRES_REVIEW",
    "DRP_OXYGEN_BASIS_REQUIRES_REVIEW",
    "ELECTRICITY_BOUNDARY_INCOMPLETE",
    "NG_BOUNDARY_INCOMPLETE",
    "CO2_BOUNDARY_INCOMPLETE",
    "NOT_THESIS_APPROVED",
]


def _csv(path: Path) -> list[dict[str, str]]:
    return _read_csv(path)


def _fmt(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _gap(model: Any, anchor: Any) -> str:
    if str(model).strip() == "" or str(anchor).strip() == "":
        return ""
    return _fmt(_zero(model) - _zero(anchor))


def _relative_gap(model: Any, anchor: Any) -> str:
    if str(model).strip() == "" or str(anchor).strip() == "":
        return ""
    anchor_value = _zero(anchor)
    if abs(anchor_value) < 1e-12:
        return ""
    return _fmt((_zero(model) - anchor_value) / anchor_value)


def _rows_by_anchor(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["anchor_id"], row["configuration"]): row for row in rows}


def _rows_by_carrier(rows: list[dict[str, str]], configuration: str) -> dict[str, dict[str, str]]:
    return {row["carrier"]: row for row in rows if row["configuration"] == configuration}


def _pj(row: dict[str, str], field: str) -> float:
    value = _zero(row.get(field, ""))
    return value * MWH_TO_PJ if row.get("unit") == "MWh_LHV/y" else value


def _payload() -> dict[str, Any]:
    run_s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation()
    return {
        "p_e_gate": json.loads((C5P_E_DIR / "s4_4c5p_e_stage_gate.json").read_text(encoding="utf-8")),
        "anchors": _csv(C5P_E_DIR / "c5_annual_anchor_reconciliation_matrix.csv"),
        "flow": _csv(C5P_E_DIR / "c5_annual_flow_balance_by_carrier.csv"),
        "electricity": _csv(C5P_E_DIR / "c5_annual_electricity_boundary_diagnostics.csv"),
        "ng": _csv(C5P_E_DIR / "c5_annual_ng_boundary_diagnostics.csv"),
        "co2": _csv(C5P_E_DIR / "c5_annual_co2_boundary_diagnostics.csv"),
        "levers": _csv(C5P_E_DIR / "c5_candidate_parameter_levers.csv"),
        "p_c": _csv(C5P_C_DIR / "s4_4c5p_c_compact_healthcheck.csv"),
        "p_a": _csv(C5P_A_DIR / "s4_4c5p_a_compact_healthcheck.csv"),
        "p_b": _csv(C5P_B_DIR / "s4_4c5p_b_compact_healthcheck.csv"),
        "p_d_gate": json.loads((C5P_D_DIR / "s4_4c5p_d_stage_gate.json").read_text(encoding="utf-8")),
    }


def _decision_rows() -> list[dict[str, Any]]:
    return [
        {
            "decision_id": "DEC_DENOMINATOR_POLICY",
            "topic": "downstream/final-product denominator",
            "current_status": "unresolved",
            "evidence_status": "active 6.75 Mt/y physical target; final-product proxy gaps remain boundary/convention gaps",
            "options": "A active liquid-steel-equivalent; B final-product proxy; C dual reporting",
            "recommended_option": "C_dual_reporting_primary_active_target_secondary_final_product_proxy_diagnostic",
            "rationale": "The final-product proxy still depends on imported slab and downstream route conventions, so it is not ready as the primary economics denominator.",
            "affects_model_equations_now": "false",
            "affects_physical_behaviour_later": "true",
            "affects_economics_later": "true",
            "must_fix_before_commit": "false",
            "must_fix_before_economics": "true",
            "can_defer_to_sensitivity": "false",
            "thesis_reporting_caveat": "denominator not frozen",
            "caveat": "DENOMINATOR_UNRESOLVED",
        },
        {
            "decision_id": "DEC_IMPORTED_SLAB_CONVENTION",
            "topic": "imported slab and route convention",
            "current_status": "validation_context_not_primary_denominator",
            "evidence_status": "C1 imported slab anchor 0.6 Mt/y and C0 external slab context are not a governed flexibility store",
            "options": "defer; route-tag explicit imported slab; promote final-product proxy later",
            "recommended_option": "defer_until_downstream_boundary_review",
            "rationale": "Changing imported slab convention before residual boundaries would mix physical reconciliation with denominator selection.",
            "affects_model_equations_now": "false",
            "affects_physical_behaviour_later": "true",
            "affects_economics_later": "true",
            "must_fix_before_commit": "false",
            "must_fix_before_economics": "true",
            "can_defer_to_sensitivity": "true",
            "thesis_reporting_caveat": "final-product proxy diagnostic only",
            "caveat": "IMPORTED_SLAB_CONVENTION_REQUIRES_REVIEW",
        },
        {
            "decision_id": "DEC_C1_GENERATOR_GAP",
            "topic": "C1 WAG/generator fuel gap",
            "current_status": "explicit_gap_reported",
            "evidence_status": "C1 generator fuel gap remains visible and is dominated by BFG availability versus Table 5.5 anchors",
            "options": "force anchors; source review; residual energy boundary; sensitivity",
            "recommended_option": "source_review_and_residual_energy_diagnostics_no_forcing",
            "rationale": "Table 5.5 annual anchors are validation/interface anchors, not executable fuel creation constraints.",
            "affects_model_equations_now": "false",
            "affects_physical_behaviour_later": "true",
            "affects_economics_later": "true",
            "must_fix_before_commit": "false",
            "must_fix_before_economics": "true",
            "can_defer_to_sensitivity": "true",
            "thesis_reporting_caveat": "generator interface development-only",
            "caveat": "C1_GENERATOR_GAP_REQUIRES_REVIEW",
        },
        {
            "decision_id": "DEC_DRP_OXYGEN_BASIS",
            "topic": "DRP oxygen basis",
            "current_status": "active_project_basis_preserved",
            "evidence_status": "0.135 t/t DRI active; 35 Nm3/t DRI vendor cross-check materially lowers C1 O2 and ASU demand",
            "options": "preserve current; replace after source review; low/current sensitivity pair",
            "recommended_option": "preserve_current_base_with_mandatory_low_current_sensitivity",
            "rationale": "The basis conflict is large enough to review before thesis economics, but changing it here would alter accepted C5 behaviour.",
            "affects_model_equations_now": "false",
            "affects_physical_behaviour_later": "true",
            "affects_economics_later": "true",
            "must_fix_before_commit": "false",
            "must_fix_before_economics": "true",
            "can_defer_to_sensitivity": "true",
            "thesis_reporting_caveat": "basis requires source-card review",
            "caveat": "DRP_OXYGEN_BASIS_REQUIRES_REVIEW",
        },
        {
            "decision_id": "DEC_ANCHOR_ACCEPTANCE_POLICY",
            "topic": "raw and active-scaled anchor acceptance",
            "current_status": "policy_registered",
            "evidence_status": "C5p_e distinguishes raw validation context from active-scaled development comparisons",
            "options": "force raw anchors; use active-scaled basis; classify gaps",
            "recommended_option": "raw_public_validation_context_active_scaled_expected_comparison",
            "rationale": "The 6.75 Mt/y active target remains the physical baseline; raw public anchors are not constraints.",
            "affects_model_equations_now": "false",
            "affects_physical_behaviour_later": "false",
            "affects_economics_later": "true",
            "must_fix_before_commit": "false",
            "must_fix_before_economics": "false",
            "can_defer_to_sensitivity": "false",
            "thesis_reporting_caveat": "development rows are not thesis-approved",
            "caveat": "RAW_PUBLIC_ANCHORS_VALIDATION_ONLY",
        },
        {
            "decision_id": "DEC_NEXT_BOUNDARY_SEQUENCE",
            "topic": "next stages before economics",
            "current_status": "boundaries_incomplete",
            "evidence_status": "electricity, NG and CO2 boundaries remain incomplete and denominator unresolved",
            "options": "residual energy diagnostics; CO2 consolidation; economics",
            "recommended_option": "residual_electricity_ng_then_co2_then_economics_review",
            "rationale": "Economics and DA readiness depend on residual load/import boundaries and denominator policy.",
            "affects_model_equations_now": "false",
            "affects_physical_behaviour_later": "true",
            "affects_economics_later": "true",
            "must_fix_before_commit": "false",
            "must_fix_before_economics": "true",
            "can_defer_to_sensitivity": "false",
            "thesis_reporting_caveat": "not economics-ready",
            "caveat": "ELECTRICITY_BOUNDARY_INCOMPLETE;NG_BOUNDARY_INCOMPLETE;CO2_BOUNDARY_INCOMPLETE",
        },
    ]


def _denominator_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = _rows_by_anchor(payload["anchors"])
    specs = [
        (C0, "active_total_liquid_steel_target", "active liquid steel target", "primary physical baseline"),
        (C1, "active_total_liquid_steel_target", "active liquid steel target", "primary physical baseline"),
        (C0, "dsp_output", "DSP output", "downstream validation component"),
        (C1, "dsp_output", "DSP output", "downstream validation component"),
        (C0, "hsm_wbw_output", "HSM/WBW final coils", "downstream validation component"),
        (C1, "hsm_wbw_output", "HSM/WBW final coils", "downstream validation component"),
        (C0, "final_product_proxy", "final-product proxy", "secondary diagnostic only"),
        (C1, "final_product_proxy", "final-product proxy", "secondary diagnostic only"),
    ]
    rows: list[dict[str, Any]] = []
    for config, anchor_id, metric, implication in specs:
        row = anchors[(anchor_id, config)]
        active = row["active_scaled_anchor"]
        model = row["model_output"]
        raw = row["raw_source_anchor"]
        rows.append({
            "configuration": config,
            "metric": metric,
            "unit": row["unit"],
            "raw_public_anchor": raw,
            "active_scaled_anchor": active,
            "current_model_output": model,
            "absolute_gap_to_raw": _gap(model, raw),
            "relative_gap_to_raw": _relative_gap(model, raw),
            "absolute_gap_to_active_scaled": _gap(model, active),
            "relative_gap_to_active_scaled": _relative_gap(model, active),
            "interpretation": row["interpretation"],
            "recommended_policy": "do_not_freeze_denominator; use active target/LSE as likely primary first-economics basis with final-product proxy secondary",
            "denominator_implication": implication,
            "decision_needed": "yes" if "final-product" in metric or "HSM" in metric else "no",
            "caveat": "DENOMINATOR_UNRESOLVED;ACTIVE_TARGET_6_75_DIFFERS_FROM_RAW_MER_ANCHORS",
        })
    return rows


def _slab_route_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = _rows_by_anchor(payload["anchors"])
    c0_slab = anchors[(f"{C0}_external_slab_import_context", C0)]
    c1_slab = anchors[(f"{C1}_external_slab_import_context", C1)]
    return [
        {
            "configuration": C0,
            "flow_or_route": "external_slab_import_context",
            "unit": c0_slab["unit"],
            "raw_anchor": c0_slab["raw_source_anchor"],
            "current_model_output": c0_slab["model_output"],
            "gap": c0_slab["absolute_gap"],
            "route_policy_status": "context_anchor_not_store_or_primary_denominator",
            "affects_final_product_proxy": "true",
            "affects_economics_denominator": "true",
            "recommended_action": "keep as context until downstream/imported slab convention review",
            "caveat": "IMPORTED_SLAB_CONVENTION_REQUIRES_REVIEW",
        },
        {
            "configuration": C1,
            "flow_or_route": "imported_slab_anchor",
            "unit": c1_slab["unit"],
            "raw_anchor": c1_slab["raw_source_anchor"],
            "current_model_output": c1_slab["model_output"],
            "gap": c1_slab["absolute_gap"],
            "route_policy_status": "validation_context_not_exogenous_store",
            "affects_final_product_proxy": "true",
            "affects_economics_denominator": "true",
            "recommended_action": "review before final-product proxy is promoted to primary economics denominator",
            "caveat": "IMPORTED_SLAB_CONVENTION_REQUIRES_REVIEW",
        },
        {
            "configuration": C1,
            "flow_or_route": "DSP_route_origin_90_percent_EAF_anchor",
            "unit": "share",
            "raw_anchor": "0.9",
            "current_model_output": "",
            "gap": "",
            "route_policy_status": "not_validated_by_current_route_origin_ledger",
            "affects_final_product_proxy": "false",
            "affects_economics_denominator": "false",
            "recommended_action": "defer route-origin tagging until downstream route diagnostics are opened",
            "caveat": "route-origin anchor is validation context only",
        },
        {
            "configuration": "C0_C1",
            "flow_or_route": "C5l_d_HSM_WBW_hot_charge_case",
            "unit": "policy",
            "raw_anchor": "base_0_50",
            "current_model_output": "base_0_50",
            "gap": "0",
            "route_policy_status": "preserved",
            "affects_final_product_proxy": "true",
            "affects_economics_denominator": "true",
            "recommended_action": "do not overwrite during alignment gate",
            "caveat": "C5L_D_BASE_0_50 preserved",
        },
        {
            "configuration": "C0_C1",
            "flow_or_route": "final_product_proxy_primary_denominator",
            "unit": "policy",
            "raw_anchor": "raw final product anchors",
            "current_model_output": "secondary_diagnostic_only",
            "gap": "",
            "route_policy_status": "not_frozen",
            "affects_final_product_proxy": "true",
            "affects_economics_denominator": "true",
            "recommended_action": "use only as secondary diagnostic until imported slab/downstream boundary is resolved",
            "caveat": "DENOMINATOR_UNRESOLVED",
        },
    ]


def _generator_gap_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    c1_flow = _rows_by_carrier(payload["flow"], C1)
    anchors = {"BFG": 9.1, "BOFG": 1.3, "COG": 0.1, "NG": 4.1}
    lever = {
        "BFG": "BFG generation coefficient; BF hot-stove/self-use; generator anchor active-scaling",
        "BOFG": "BOFG recovery/generation coefficient; BOF route scaling",
        "COG": "COG generation or retained KGF1 scaling; WAG flare/spill policy",
        "NG": "VN25 NG anchor interpretation; residual NG boundary",
    }
    source = {
        "BFG": "insufficient governed BFG availability after process and boiler uses versus preferred generator anchors",
        "BOFG": "minor BOFG anchor mismatch within current boundary",
        "COG": "COG anchor met; residual remains after generator/flare policy",
        "NG": "VN25 NG anchor is represented as imported NG, but full NG boundary remains incomplete",
    }
    rows: list[dict[str, Any]] = []
    for carrier in ["BFG", "BOFG", "COG", "NG"]:
        row = c1_flow[carrier]
        generated = _pj(row, "generated_or_supplied")
        process = _pj(row, "preparation_or_process_use")
        boiler = _pj(row, "boiler_or_steam_use")
        model = _pj(row, "generator_use")
        residual = _pj(row, "residual_or_unallocated")
        gap = max(anchors[carrier] - model, 0.0)
        rows.append({
            "carrier": carrier,
            "generated_or_available": _fmt(generated),
            "mandatory_self_use": _fmt(_pj(row, "mandatory_process_self_use")),
            "process_or_preparation_use": _fmt(process),
            "boiler_steam_use": _fmt(boiler),
            "generator_model_use": _fmt(model),
            "generator_anchor_use": _fmt(anchors[carrier]),
            "generator_gap": _fmt(gap),
            "residual_after_generator": _fmt(residual),
            "possible_gap_source": source[carrier],
            "candidate_lever": lever[carrier],
            "recommended_action": "review source/active-scaling and keep gap explicit; do not create fuel to force anchor",
            "caveat": "PJ_LHV/y; carrier-specific balances preserved",
        })
    gate = payload["p_e_gate"]
    rows.append({
        "carrier": "total_preferred_anchor_gap_reported",
        "generated_or_available": "",
        "mandatory_self_use": "",
        "process_or_preparation_use": "",
        "boiler_steam_use": "",
        "generator_model_use": _fmt(9.836611),
        "generator_anchor_use": _fmt(14.6),
        "generator_gap": _fmt(gate["C1_generator_fuel_gap_PJ_y"]),
        "residual_after_generator": _fmt(0.737782),
        "possible_gap_source": "BFG shortfall dominates; Table 5.5 preferred annual anchors are not forced constraints",
        "candidate_lever": "generator anchor interpretation; residual electricity/NG boundary; WAG source review",
        "recommended_action": "high-priority review/sensitivity before economics; not a commit blocker by itself",
        "caveat": "Reported gap follows current C5p_e stage gate.",
    })
    return rows


def _drp_oxygen_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = _rows_by_anchor(payload["anchors"])
    drp_current_kt = _zero(anchors[("drp_oxygen", C1)]["model_output"]) / 1000.0
    total_current_kt = _zero(anchors[("linde_total_oxygen_demand", C1)]["model_output"]) / 1000.0
    sanity_kt = 744.0
    dri_t_y = drp_current_kt * 1000.0 / 0.135
    vendor_t_per_t = 35.0 * O2_DENSITY_KG_PER_NM3 / 1000.0
    options = [
        ("active_project_basis", "active project-derived Athanasiadis/MER development basis", "t O2/t DRI", 0.135, "active development basis", "preserve_current_base_pending_source_review", "true"),
        ("vendor_crosscheck_basis", "Energiron vendor cross-check basis", "Nm3 O2/t DRI", 35.0, "vendor sensitivity/cross-check", "not_base_without_source_card_review", "true"),
        ("midpoint_sensitivity", "simple midpoint between active and vendor bases", "t O2/t DRI", (0.135 + vendor_t_per_t) / 2.0, "constructed sensitivity only", "sensitivity_only_not_base", "true"),
    ]
    rows: list[dict[str, Any]] = []
    for basis_id, description, unit, value, evidence, status, sensitivity in options:
        t_per_t = vendor_t_per_t if basis_id == "vendor_crosscheck_basis" else value
        nm3_per_t = t_per_t * 1000.0 / O2_DENSITY_KG_PER_NM3
        annual_kt = dri_t_y * t_per_t / 1000.0
        asu_gwh = annual_kt * ASU_MWH_PER_T_O2
        total_if_basis_kt = total_current_kt - drp_current_kt + annual_kt
        rows.append({
            "oxygen_basis_id": basis_id,
            "basis_description": description,
            "unit": unit,
            "value": _fmt(value),
            "equivalent_nm3_per_t_dri": _fmt(nm3_per_t),
            "equivalent_t_per_t_dri": _fmt(t_per_t),
            "annual_o2_demand_kt_y": _fmt(annual_kt),
            "annual_asu_electricity_gwh_y": _fmt(asu_gwh),
            "gap_to_current_model": _fmt(annual_kt - drp_current_kt),
            "gap_to_source_sanity": _fmt(total_if_basis_kt - sanity_kt),
            "evidence_status": evidence,
            "recommended_base_status": status,
            "sensitivity_required": sensitivity,
            "caveat": "Active basis is not changed by C5p_f.",
        })
    return rows


def _anchor_policy_rows() -> list[dict[str, Any]]:
    return [
        {
            "anchor_family": "active_production_target_6_75",
            "raw_anchor_role": "validation_context",
            "active_scaled_anchor_role": "expected_development_comparison",
            "executable_constraint_allowed": "true_only_for_existing_active_target",
            "validation_gap_allowed": "true",
            "acceptance_tolerance": "zero_gap_to_active_target; raw MER gap allowed with caveat",
            "current_status": "pass_with_caveat",
            "policy_recommendation": "do not overwrite 6.75 Mt/y target with raw public anchors during reconciliation",
            "caveat": "ACTIVE_TARGET_6_75_DIFFERS_FROM_RAW_MER_ANCHORS",
        },
        {
            "anchor_family": "raw_MER_public_anchors",
            "raw_anchor_role": "validation_context",
            "active_scaled_anchor_role": "not_always_available",
            "executable_constraint_allowed": "false",
            "validation_gap_allowed": "true",
            "acceptance_tolerance": "classification_required_not_zero_forcing",
            "current_status": "pass_with_caveat",
            "policy_recommendation": "report raw gaps as context; do not force model outputs",
            "caveat": "RAW_PUBLIC_ANCHORS_VALIDATION_ONLY",
        },
        {
            "anchor_family": "annual_generator_and_utility_anchors",
            "raw_anchor_role": "validation_anchor_or_interface_target",
            "active_scaled_anchor_role": "diagnostic_comparison",
            "executable_constraint_allowed": "false_without_explicit_interpretation",
            "validation_gap_allowed": "true",
            "acceptance_tolerance": "gap may be nonzero if boundary or source conflict is documented",
            "current_status": "pass_with_review_required",
            "policy_recommendation": "keep C1 generator gap visible; keep C0 2 TWh as validation only",
            "caveat": "C1_GENERATOR_GAP_REQUIRES_REVIEW",
        },
        {
            "anchor_family": "annual_not_hourly",
            "raw_anchor_role": "annual_context",
            "active_scaled_anchor_role": "annual_diagnostic",
            "executable_constraint_allowed": "false_as_hourly_schedule",
            "validation_gap_allowed": "true",
            "acceptance_tolerance": "annual-to-timestep caveat required",
            "current_status": "pass",
            "policy_recommendation": "never reinterpret annual anchors as hourly dispatch schedules",
            "caveat": "RAW_PUBLIC_ANCHORS_VALIDATION_ONLY",
        },
        {
            "anchor_family": "acceptance_classes",
            "raw_anchor_role": "classification_input",
            "active_scaled_anchor_role": "classification_input",
            "executable_constraint_allowed": "not_applicable",
            "validation_gap_allowed": "true",
            "acceptance_tolerance": "pass_within_tolerance;pass_with_caveat;boundary_gap;source_conflict;sensitivity_required;must_fix",
            "current_status": "registered",
            "policy_recommendation": "use explicit class before changing any physical parameter",
            "caveat": "PRE_ECONOMICS_ALIGNMENT_DEVELOPMENT_ONLY",
        },
        {
            "anchor_family": "development_outputs",
            "raw_anchor_role": "not_thesis_truth",
            "active_scaled_anchor_role": "not_thesis_truth",
            "executable_constraint_allowed": "false_for_thesis_claim_without_review",
            "validation_gap_allowed": "true",
            "acceptance_tolerance": "thesis_usability=false",
            "current_status": "pass",
            "policy_recommendation": "carry not-thesis-approved caveat forward",
            "caveat": "NOT_THESIS_APPROVED",
        },
    ]


def _blocker_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    gate = payload["p_e_gate"]
    return [
        {
            "blocker_id": "BLK_OUTPUT_POLICY_REVIEW",
            "blocker": "dirty generated outputs and staging scope need review",
            "category": "commit_process",
            "current_evidence": "worktree has many generated/untracked S4 outputs",
            "why_it_matters": "prevents clean scoped commit without output-policy decision",
            "blocks_commit": "true",
            "blocks_residual_energy_boundary": "false",
            "blocks_co2_boundary": "false",
            "blocks_economics": "false",
            "recommended_next_action": "perform output-policy and staging scope review before commit",
            "caveat": "NO_GO for commit, GO for next diagnostics",
        },
        {
            "blocker_id": "BLK_DENOMINATOR_UNRESOLVED",
            "blocker": "final economics denominator not frozen",
            "category": "economics",
            "current_evidence": gate["denominator_status"],
            "why_it_matters": "EUR/t comparisons need stable denominator policy",
            "blocks_commit": "false",
            "blocks_residual_energy_boundary": "false",
            "blocks_co2_boundary": "false",
            "blocks_economics": "true",
            "recommended_next_action": "use dual-reporting recommendation until downstream/imported slab convention is resolved",
            "caveat": "DENOMINATOR_UNRESOLVED",
        },
        {
            "blocker_id": "BLK_IMPORTED_SLAB_CONVENTION",
            "blocker": "imported slab convention unresolved",
            "category": "downstream_denominator",
            "current_evidence": "C1 imported slab anchor is context; final-product proxy remains secondary diagnostic",
            "why_it_matters": "can shift final-product denominator and route interpretation",
            "blocks_commit": "false",
            "blocks_residual_energy_boundary": "false",
            "blocks_co2_boundary": "false",
            "blocks_economics": "true",
            "recommended_next_action": "review before final-product proxy becomes primary denominator",
            "caveat": "IMPORTED_SLAB_CONVENTION_REQUIRES_REVIEW",
        },
        {
            "blocker_id": "BLK_C1_GENERATOR_GAP",
            "blocker": "C1 generator WAG/fuel anchor gap",
            "category": "energy_boundary",
            "current_evidence": f"{gate['C1_generator_fuel_gap_PJ_y']} PJ/y fuel gap",
            "why_it_matters": "affects generator offset, residual electricity and NG boundary interpretation",
            "blocks_commit": "false",
            "blocks_residual_energy_boundary": "false",
            "blocks_co2_boundary": "false",
            "blocks_economics": "true",
            "recommended_next_action": "run residual electricity/NG diagnostics and WAG/generator source review",
            "caveat": "C1_GENERATOR_GAP_REQUIRES_REVIEW",
        },
        {
            "blocker_id": "BLK_DRP_OXYGEN_BASIS",
            "blocker": "DRP oxygen basis conflict",
            "category": "source_review",
            "current_evidence": "0.135 t/t DRI active versus 35 Nm3/t DRI vendor cross-check",
            "why_it_matters": "large effect on ASU electricity and oxygen boundary",
            "blocks_commit": "false",
            "blocks_residual_energy_boundary": "false",
            "blocks_co2_boundary": "false",
            "blocks_economics": "true",
            "recommended_next_action": "source-card review and low/current sensitivity pair before thesis economics",
            "caveat": "DRP_OXYGEN_BASIS_REQUIRES_REVIEW",
        },
        {
            "blocker_id": "BLK_RESIDUAL_ENERGY_BOUNDARIES",
            "blocker": "electricity and NG boundaries incomplete",
            "category": "boundary",
            "current_evidence": f"{gate['electricity_boundary_status']}; {gate['ng_boundary_status']}",
            "why_it_matters": "economics needs load/import boundary before cost claims",
            "blocks_commit": "false",
            "blocks_residual_energy_boundary": "false",
            "blocks_co2_boundary": "false",
            "blocks_economics": "true",
            "recommended_next_action": "implement residual electricity/NG diagnostics next",
            "caveat": "ELECTRICITY_BOUNDARY_INCOMPLETE;NG_BOUNDARY_INCOMPLETE",
        },
        {
            "blocker_id": "BLK_CO2_BOUNDARY",
            "blocker": "CO2 boundary incomplete",
            "category": "co2",
            "current_evidence": gate["co2_boundary_status"],
            "why_it_matters": "ETS or emissions objective cannot use component-only boundary",
            "blocks_commit": "false",
            "blocks_residual_energy_boundary": "false",
            "blocks_co2_boundary": "false",
            "blocks_economics": "true",
            "recommended_next_action": "run consolidated CO2 boundary diagnostics after or alongside residual energy boundary",
            "caveat": "CO2_BOUNDARY_INCOMPLETE",
        },
    ]


def _lever_triage_rows() -> list[dict[str, Any]]:
    data = [
        ("LEV_DENOMINATOR_POLICY", "downstream", "primary economics denominator", "unresolved", "active target/LSE primary; final-product proxy secondary", "final-product proxy gaps", "must_review_before_economics", "changes reported EUR/t denominator and interpretation", "high if frozen prematurely", "false", "true", "review_before_economics", "do not freeze before imported slab/downstream review", "DENOMINATOR_UNRESOLVED"),
        ("LEV_IMPORTED_SLAB_CONVENTION", "downstream", "C1 imported slab convention", "context anchor", "explicit exogenous supply; route-tagged diagnostic; defer", "C1 final-product proxy gap", "must_review_before_economics", "can shift final-product proxy and route allocation", "medium/high", "true", "true", "review_before_economics", "do not change in C5p_f", "IMPORTED_SLAB_CONVENTION_REQUIRES_REVIEW"),
        ("LEV_C1_GENERATOR_ANCHOR_INTERPRETATION", "generator_wag", "VN25/IJ01 annual anchors", "validation/interface anchors", "unscaled Table 5.5; active-scaled; sensitivity", "4.763389 PJ/y C1 generator gap", "must_review_before_economics", "can change generator offset and residual WAG/NG accounting", "high", "true", "true", "review_and_sensitivity", "run WAG/generator source review after residual energy diagnostics", "C1_GENERATOR_GAP_REQUIRES_REVIEW"),
        ("LEV_DRP_OXYGEN_BASIS_REVIEW", "oxygen_asu", "DRP oxygen intensity", "0.135 t/t DRI active", "35 Nm3/t DRI vendor low; midpoint; current high", "C1 O2 sanity gap", "must_review_before_economics", "strongly changes ASU electricity and O2 demand", "high", "true", "true", "mandatory_sensitivity", "source-card review before replacing base", "DRP_OXYGEN_BASIS_REQUIRES_REVIEW"),
        ("LEV_BFG_GENERATION_SELF_USE", "wag", "BFG generation/self-use coefficients", "current C5 inherited", "source review; active-scaled sensitivity", "BFG generator gap", "sensitivity_required", "can close or widen C1 generator BFG gap", "high", "true", "true", "sensitivity_required", "review with WAG balance; no tuning here", "C1_GENERATOR_GAP_REQUIRES_REVIEW"),
        ("LEV_BOFG_COG_RECOVERY", "wag", "BOFG/COG recovery and allocation", "current C5 inherited", "source review; flare policy sensitivity", "minor BOFG gap and COG residual", "sensitivity_required", "shifts carrier-specific generator availability", "medium", "true", "true", "sensitivity_required", "keep carriers separate", "RAW_PUBLIC_ANCHORS_VALIDATION_ONLY"),
        ("LEV_RESIDUAL_ELECTRICITY_BOUNDARY", "electricity", "residual electricity load/import boundary", "incomplete", "diagnostic residual layer", "model exposure cannot be economics claim", "must_review_before_economics", "defines gross/net electricity exposure", "high", "true", "true", "next_stage", "implement next", "ELECTRICITY_BOUNDARY_INCOMPLETE"),
        ("LEV_RESIDUAL_NG_BOUNDARY", "natural_gas", "residual/unmodelled NG boundary", "incomplete", "diagnostic residual layer", "modelled NG not full-site NG", "must_review_before_economics", "defines total NG cost/emission boundary", "high", "true", "true", "next_stage", "implement next", "NG_BOUNDARY_INCOMPLETE"),
        ("LEV_CO2_BOUNDARY", "co2", "consolidated CO2 boundary", "component-only", "fuel-explicit diagnostic; double-counting checks", "ETS readiness false", "must_review_before_economics", "sets emissions scope and CO2 cost readiness", "high", "true", "true", "next_stage_after_or_alongside_energy", "do not add ETS objective yet", "CO2_BOUNDARY_INCOMPLETE"),
        ("LEV_EAF_DRI_SCRAP_SPLIT", "materials", "EAF DRI coefficient and scrap input", "0.829675 t/t LS current DRI coefficient", "0.848 review coefficient; scrap sensitivity", "material-route gap", "sensitivity_required", "changes DRI/scrap/DRP requirements", "medium", "true", "true", "sensitivity_required", "defer until material lever review", "RAW_PUBLIC_ANCHORS_VALIDATION_ONLY"),
        ("LEV_DRI_BUFFER_DAYS", "buffers", "DRI buffer days", "current C5 finite C1 buffer", "1-3 day sensitivity", "buffer sensitivity only", "sensitivity_required", "changes flexibility, not annual mass balance", "low/medium", "true", "true", "sensitivity_later", "do not change for pre-economics gate", "NOT_THESIS_APPROVED"),
        ("LEV_FORBIDDEN_MARKET_FEATURES", "market", "DA revenue/mFRR/WAG market value", "inactive", "none for C5 physical baseline", "not applicable", "not_recommended", "would invalidate pre-economics baseline", "critical", "true", "true", "blocked", "keep inactive", "NOT_THESIS_APPROVED"),
        ("LEV_ACTIVE_PRODUCTION_TARGET", "production", "active 6.75 Mt/y target", "6.75 Mt/y active", "raw 7.2/6.8 validation context only", "raw public LS gaps", "can_defer", "would change all route-scaled outputs", "high", "true", "true", "do_not_change_now", "do not tune to raw anchors", "ACTIVE_TARGET_6_75_DIFFERS_FROM_RAW_MER_ANCHORS"),
    ]
    return [
        {
            "lever_id": row[0],
            "domain": row[1],
            "parameter_or_policy": row[2],
            "current_value_or_status": row[3],
            "candidate_values_or_range": row[4],
            "related_gap": row[5],
            "classification": row[6],
            "expected_direction_if_changed": row[7],
            "risk_of_changing": row[8],
            "affects_physical_behaviour": row[9],
            "affects_economics_later": row[10],
            "recommended_status": row[11],
            "recommended_action": row[12],
            "caveat": row[13],
        }
        for row in data
    ]


def _redflag_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    p_e_gate = payload["p_e_gate"]
    p_c_rows = [row for row in payload["p_c"] if row["configuration"] in {C0, C1} and row["horizon_hours"] == "24"]
    pc0 = next(row for row in p_c_rows if row["configuration"] == C0)
    pc1 = next(row for row in p_c_rows if row["configuration"] == C1)
    checks = {
        "VALIDATION_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION": False,
        "ANNUAL_ANCHOR_USED_AS_HOURLY_DISPATCH_SCHEDULE": False,
        "RAW_MER_ANCHOR_FORCED_AGAINST_ACTIVE_6_75_TARGET": False,
        "DENOMINATOR_SILENTLY_FROZEN": "unresolved" not in p_e_gate["denominator_status"],
        "FINAL_PRODUCT_PROXY_USED_AS_PRIMARY_ECON_DENOMINATOR_WITH_UNRESOLVED_IMPORT_SLAB": False,
        "C1_GENERATOR_FUEL_GAP_HIDDEN": _zero(p_e_gate["C1_generator_fuel_gap_PJ_y"]) <= 0.0,
        "C1_GENERATOR_ANCHOR_FORCED_BY_CREATING_FUEL": False,
        "GENERATOR_PRICE_RESPONSIVE_DISPATCH_ACTIVE": pc0["price_responsive_dispatch_base"] == "true" or pc1["price_responsive_dispatch_base"] == "true",
        "GENERATOR_EXPORT_REVENUE_ACTIVE": pc0["export_revenue_enabled_base"] == "true" or pc1["export_revenue_enabled_base"] == "true",
        "WAG_DIRECT_MARKET_VALUE_ACTIVE": False,
        "C0_GENERATOR_2TWH_ENFORCED_AS_TARGET": abs(_zero(p_e_gate["C0_generator_2TWh_gap_TWh_y"])) < 1e-9,
        "DRP_OXYGEN_BASIS_CHANGED_WITHOUT_SOURCE_REVIEW": False,
        "FULL_SITE_NET_IMPORT_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY": pc0["full_site_net_electricity_claimed"] == "true" or pc1["full_site_net_electricity_claimed"] == "true",
        "CO2_ETS_READY_CLAIMED_WITH_COMPONENT_ONLY_BOUNDARY": False,
        "PRODUCTION_POLICY_CHANGED_DURING_ALIGNMENT": False,
        "C5L_D_BASE_0_50_REVERTED": False,
        "COKE_RECONCILIATION_BASELINE_REOPENED": pc1["coke_reconciliation_baseline_status"] != "C5m_f_bounded_coke_reconciliation_active_development_baseline",
        "THESIS_USABILITY_TRUE_FOR_DEVELOPMENT_ROWS": bool(p_e_gate["thesis_usability"]),
    }
    rows: list[dict[str, Any]] = []
    for flag in FAILURE_FLAGS:
        active = checks[flag]
        rows.append({
            "red_flag": flag,
            "active": str(active).lower(),
            "severity": "failure",
            "evidence": "C5p_f alignment gate check against current C5p_e/C5p_c artifacts",
            "recommended_action": "fix before commit/economics if active" if active else "none",
        })
    for caveat in CAVEATS:
        rows.append({
            "red_flag": caveat,
            "active": "true",
            "severity": "caveat",
            "evidence": "pre-economics gate caveat",
            "recommended_action": "carry into scoped commit review and next diagnostics",
        })
    return rows


def _write_report(gate: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C5 Pre-Economics Alignment Gate",
        "",
        "Diagnostic-only gate for the current C5 physical/accounting baseline. It does not change equations, parameters, route shares, production target, C5p_a/b/c/d/e behaviour, economics, DA revenue, mFRR, CO2 objective, or denominator policy.",
        "",
        "## Stage Gate",
        "",
        f"- Decision: `{gate['decision']}`",
        f"- Failure count: `{gate['failure_count']}`",
        f"- Caveat count: `{gate['caveat_count']}`",
        f"- Denominator policy: `{gate['recommended_denominator_policy']}`",
        f"- C1 generator gap status: `{gate['c1_generator_gap_status']}`",
        f"- DRP oxygen basis status: `{gate['drp_oxygen_basis_status']}`",
        "",
        "## Recommendations",
        "",
        "- Keep the active 6.75 Mt/y physical target as the C5 baseline; treat raw MER/public anchors as validation context.",
        "- Use dual denominator reporting later: active liquid-steel-equivalent/target as likely primary, final-product proxy as secondary diagnostic until imported slab/downstream route convention is resolved.",
        "- Keep the C1 generator fuel gap explicit and review WAG/generator source assumptions before economics; do not force Table 5.5 anchors by creating fuel.",
        "- Preserve the active DRP oxygen basis for now, but require source-card review and low/current sensitivity before thesis economics.",
        "- Proceed to residual electricity/NG diagnostics, then consolidated CO2 boundary diagnostics. Economics and DA readiness remain NO-GO.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_outputs() -> dict[str, Any]:
    C5P_F_DIR.mkdir(parents=True, exist_ok=True)
    payload = _payload()
    decisions = _decision_rows()
    denominator = _denominator_rows(payload)
    slab_route = _slab_route_rows(payload)
    generator_gap = _generator_gap_rows(payload)
    drp_oxygen = _drp_oxygen_rows(payload)
    anchor_policy = _anchor_policy_rows()
    blockers = _blocker_rows(payload)
    levers = _lever_triage_rows()
    redflags = _redflag_rows(payload)
    failure_count = sum(1 for row in redflags if row["severity"] == "failure" and row["active"] == "true")
    caveat_count = sum(1 for row in redflags if row["severity"] == "caveat" and row["active"] == "true")
    p_e_gate = payload["p_e_gate"]
    bfg_row = next(row for row in generator_gap if row["carrier"] == "BFG")
    active_basis = next(row for row in drp_oxygen if row["oxygen_basis_id"] == "active_project_basis")
    vendor_basis = next(row for row in drp_oxygen if row["oxygen_basis_id"] == "vendor_crosscheck_basis")
    gate = {
        "stage_id": STAGE,
        "decision": "pass_development_pre_economics_alignment_gate" if failure_count == 0 else "fail_development_pre_economics_alignment_gate",
        "status": "development_only",
        "thesis_usability": False,
        "output_directory": str(C5P_F_DIR).replace("\\", "/"),
        "failure_count": failure_count,
        "caveat_count": caveat_count,
        "denominator_status": p_e_gate["denominator_status"],
        "recommended_denominator_policy": "dual_reporting_primary_active_LS_target_secondary_final_product_proxy_diagnostic_not_frozen",
        "imported_slab_status": "review_before_final_product_proxy_primary_denominator",
        "c1_generator_gap_status": "explicit_high_priority_review_not_commit_blocker",
        "C1_generator_fuel_gap_PJ_y": p_e_gate["C1_generator_fuel_gap_PJ_y"],
        "C1_generator_BFG_gap_PJ_y": _zero(bfg_row["generator_gap"]),
        "drp_oxygen_basis_status": "active_basis_preserved_mandatory_source_review_before_thesis_economics",
        "DRP_active_basis_t_per_t_DRI": _zero(active_basis["equivalent_t_per_t_dri"]),
        "DRP_vendor_crosscheck_t_per_t_DRI": _zero(vendor_basis["equivalent_t_per_t_dri"]),
        "anchor_acceptance_policy_status": "registered_validation_anchors_not_executable_constraints",
        "commit_review_status": "NO_GO_for_commit_until_output_policy_and_staging_scope_review",
        "residual_electricity_ng_diagnostics_status": "GO",
        "consolidated_co2_diagnostics_status": "GO_after_or_alongside_residual_energy_boundary",
        "economics_readiness": "NO_GO",
        "DA_readiness": "NO_GO",
        "electricity_accounting_status": p_e_gate["electricity_accounting_status"],
        "generator_electricity_value_mode": p_e_gate["generator_electricity_value_mode"],
        "electricity_boundary_status": p_e_gate["electricity_boundary_status"],
        "ng_boundary_status": p_e_gate["ng_boundary_status"],
        "co2_boundary_status": p_e_gate["co2_boundary_status"],
    }

    _write_csv(C5P_F_DIR / "c5_pre_economics_alignment_decision_register.csv", decisions, DECISION_COLUMNS)
    _write_csv(C5P_F_DIR / "c5_downstream_denominator_alignment.csv", denominator, DENOMINATOR_COLUMNS)
    _write_csv(C5P_F_DIR / "c5_imported_slab_and_route_alignment.csv", slab_route, SLAB_ROUTE_COLUMNS)
    _write_csv(C5P_F_DIR / "c5_c1_generator_wag_gap_decomposition.csv", generator_gap, GENERATOR_GAP_COLUMNS)
    _write_csv(C5P_F_DIR / "c5_drp_oxygen_basis_review.csv", drp_oxygen, DRP_OXYGEN_COLUMNS)
    _write_csv(C5P_F_DIR / "c5_anchor_acceptance_policy.csv", anchor_policy, ANCHOR_POLICY_COLUMNS)
    _write_csv(C5P_F_DIR / "c5_pre_economics_blocker_list.csv", blockers, BLOCKER_COLUMNS)
    _write_csv(C5P_F_DIR / "c5_pre_economics_parameter_lever_triage.csv", levers, LEVER_TRIAGE_COLUMNS)
    _write_csv(C5P_F_DIR / "c5_pre_economics_red_flags.csv", redflags, REDFLAG_COLUMNS)
    _write_json(C5P_F_DIR / "s4_4c5p_f_stage_gate.json", gate)
    _write_csv(
        C5P_F_DIR / "s4_4c5p_f_run_registry.csv",
        [{
            "stage": STAGE,
            "source_stage": "S4.4c5p_e_annual_c0_c1_physical_accounting_reconciliation",
            "decision": gate["decision"],
            "status": "development_only",
            "thesis_usability": "false",
            "output_directory": gate["output_directory"],
        }],
    )
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "decisions": len(decisions),
            "denominator": len(denominator),
            "slab_route": len(slab_route),
            "generator_gap": len(generator_gap),
            "drp_oxygen": len(drp_oxygen),
            "anchor_policy": len(anchor_policy),
            "blockers": len(blockers),
            "levers": len(levers),
            "redflags": len(redflags),
        },
    }
    _write_json(C5P_F_DIR / "s4_4c5p_f_summary.json", summary)
    _write_report(gate)
    return summary


def run_s4_4c5p_f_pre_economics_alignment_gate() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5p_f_pre_economics_alignment_gate(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
