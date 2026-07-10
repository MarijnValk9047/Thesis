"""S4.4c5p_g residual electricity and natural-gas boundary diagnostics.

This stage is diagnostic-only. It reads the current C5 physical/accounting
artifacts, separates represented electricity/NG components from context
anchors and missing residual loads, and records policy options for later
boundary implementation. It does not add residual loads, costs, CO2 logic, or
market behaviour.
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
from .s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation import C5P_E_DIR
from .s4_4c5p_f_pre_economics_alignment_gate import (
    C5P_F_DIR,
    run_s4_4c5p_f_pre_economics_alignment_gate,
)


STAGE = "S4.4c5p_g_residual_electricity_ng_boundary_diagnostics"
C5P_G_DIR = S4_ROOT / "s4_4c5p_g_residual_electricity_ng_boundary_diagnostics"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_RESIDUAL_ELECTRICITY_NG_BOUNDARY_DIAGNOSTICS.md")

MWH_PER_TWH = 1_000_000.0
PJ_TO_MWH = 277_777.77777777775

ELECTRICITY_COMPONENT_COLUMNS = [
    "configuration",
    "electricity_component",
    "component_class",
    "unit",
    "annual_value",
    "sign_convention",
    "included_in_current_modelled_process_demand",
    "included_in_internal_offset",
    "included_in_full_site_claim",
    "source_or_stage",
    "boundary_status",
    "caveat",
]

ELECTRICITY_BOUNDARY_COLUMNS = [
    "configuration",
    "gross_modelled_process_demand_twh",
    "asu_demand_twh",
    "drp_demand_twh",
    "eaf_demand_twh",
    "pefa_demand_twh",
    "dsp_demand_twh",
    "other_modelled_demand_twh",
    "steam_circuit_internal_generation_twh",
    "wag_generator_offset_twh",
    "total_internal_offset_twh",
    "modelled_exposure_pre_floor_twh",
    "modelled_exposure_post_floor_twh",
    "residual_electricity_load_active",
    "full_site_net_import_claimed",
    "boundary_status",
    "caveat",
]

ELECTRICITY_ANCHOR_COLUMNS = [
    "configuration",
    "anchor_id",
    "anchor_description",
    "anchor_value",
    "unit",
    "anchor_role",
    "current_model_metric",
    "current_model_value",
    "gap",
    "interpretation",
    "residual_load_option_id",
    "option_description",
    "option_residual_value",
    "option_status",
    "recommended_action",
    "caveat",
]

ELECTRICITY_POLICY_COLUMNS = [
    "option_id",
    "policy_name",
    "description",
    "required_evidence",
    "effect_on_modelled_exposure",
    "affects_physical_behaviour",
    "affects_economics_later",
    "risk",
    "recommended_status",
    "can_implement_before_co2",
    "can_implement_before_economics",
    "caveat",
]

NG_COMPONENT_COLUMNS = [
    "configuration",
    "ng_component",
    "component_class",
    "unit",
    "annual_value_pj",
    "included_in_current_modelled_ng",
    "source_or_stage",
    "boundary_status",
    "caveat",
]

NG_BOUNDARY_COLUMNS = [
    "configuration",
    "drp_ng_pj",
    "eaf_ng_pj",
    "generator_ng_pj",
    "boiler_steam_ng_pj",
    "pefa_ng_pj",
    "other_modelled_ng_pj",
    "total_modelled_ng_pj",
    "residual_ng_load_active",
    "full_site_ng_claimed",
    "boundary_status",
    "caveat",
]

NG_ANCHOR_COLUMNS = [
    "configuration",
    "anchor_id",
    "anchor_description",
    "anchor_value",
    "unit",
    "anchor_role",
    "current_model_metric",
    "current_model_value",
    "gap",
    "interpretation",
    "residual_ng_option_id",
    "option_description",
    "option_residual_value",
    "option_status",
    "recommended_action",
    "caveat",
]

NG_POLICY_COLUMNS = [
    "option_id",
    "policy_name",
    "description",
    "required_evidence",
    "effect_on_modelled_ng",
    "affects_physical_behaviour",
    "affects_economics_later",
    "risk",
    "recommended_status",
    "can_implement_before_co2",
    "can_implement_before_economics",
    "caveat",
]

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
    "must_fix_before_co2",
    "must_fix_before_economics",
    "can_defer_to_sensitivity",
    "thesis_reporting_caveat",
    "caveat",
]

REDFLAG_COLUMNS = ["red_flag", "active", "severity", "evidence", "recommended_action"]

FAILURE_FLAGS = [
    "RESIDUAL_ELECTRICITY_LOAD_ADDED_IN_DIAGNOSTIC_STAGE",
    "RESIDUAL_NG_LOAD_ADDED_IN_DIAGNOSTIC_STAGE",
    "ELECTRICITY_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION",
    "NG_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION",
    "FULL_SITE_NET_IMPORT_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY",
    "FULL_SITE_NG_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY",
    "C0_ELECTRICITY_OVER_OFFSET_HIDDEN_BY_FLOORING",
    "GENERATOR_ELECTRICITY_COUNTED_AS_DA_REVENUE",
    "GENERATOR_EXPORT_REVENUE_ACTIVE",
    "WAG_DIRECT_MARKET_VALUE_ACTIVE",
    "DA_PRICE_OR_ECONOMICS_ACTIVE",
    "CO2_ETS_READY_CLAIMED_BEFORE_BOUNDARY",
    "DENOMINATOR_SILENTLY_FROZEN",
    "PRODUCTION_POLICY_CHANGED_DURING_BOUNDARY_DIAGNOSTIC",
    "C5L_D_BASE_0_50_REVERTED",
    "COKE_RECONCILIATION_BASELINE_REOPENED",
    "THESIS_USABILITY_TRUE_FOR_DEVELOPMENT_ROWS",
]

CAVEATS = [
    "RESIDUAL_ELECTRICITY_NG_DIAGNOSTIC_ONLY",
    "ELECTRICITY_BOUNDARY_INCOMPLETE",
    "NG_BOUNDARY_INCOMPLETE",
    "C0_ELECTRICITY_OVER_OFFSET_OR_ZERO_EXPOSURE_REQUIRES_POLICY",
    "SITE_ELECTRICITY_ANCHORS_CONTEXT_ONLY",
    "SITE_NG_ANCHORS_MISSING_OR_CONTEXT_ONLY",
    "GENERATOR_ELECTRICITY_OFFSET_REPORTING_ONLY",
    "NO_FULL_SITE_NET_IMPORT_CLAIM",
    "NO_FULL_SITE_NG_CLAIM",
    "CO2_BOUNDARY_DEPENDS_ON_ENERGY_BOUNDARY",
    "ECONOMICS_NO_GO",
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


def _twh_from_mwh(value: Any) -> float:
    return _zero(value) / MWH_PER_TWH


def _pj_from_mwh(value: Any) -> float:
    return _zero(value) / PJ_TO_MWH


def _keyed_health(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _anchor_key(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["anchor_id"], row["configuration"]): row for row in rows}


def _electricity_row(rows: list[dict[str, str]], configuration: str) -> dict[str, str]:
    return next(
        row for row in rows
        if row["configuration"] == configuration
        and row["electricity_component"] == "modelled_process_before_generator_offset"
    )


def _ng_row(rows: list[dict[str, str]], configuration: str) -> dict[str, str]:
    return next(row for row in rows if row["configuration"] == configuration)


def _anchor_mwh(anchors: dict[tuple[str, str], dict[str, str]], configuration: str, anchor_id: str) -> float:
    row = anchors[(anchor_id, configuration)]
    value = _zero(row["model_output"])
    unit = row["unit"]
    if unit == "GWh/y":
        return value * 1000.0
    if unit == "TWh/y":
        return value * MWH_PER_TWH
    return value


def _payload() -> dict[str, Any]:
    run_s4_4c5p_f_pre_economics_alignment_gate()
    return {
        "p_f_gate": json.loads((C5P_F_DIR / "s4_4c5p_f_stage_gate.json").read_text(encoding="utf-8")),
        "p_e_gate": json.loads((C5P_E_DIR / "s4_4c5p_e_stage_gate.json").read_text(encoding="utf-8")),
        "anchors": _csv(C5P_E_DIR / "c5_annual_anchor_reconciliation_matrix.csv"),
        "electricity": _csv(C5P_E_DIR / "c5_annual_electricity_boundary_diagnostics.csv"),
        "ng": _csv(C5P_E_DIR / "c5_annual_ng_boundary_diagnostics.csv"),
        "p_a": _keyed_health(_csv(C5P_A_DIR / "s4_4c5p_a_compact_healthcheck.csv")),
        "p_b": _keyed_health(_csv(C5P_B_DIR / "s4_4c5p_b_compact_healthcheck.csv")),
        "p_c": _keyed_health(_csv(C5P_C_DIR / "s4_4c5p_c_compact_healthcheck.csv")),
        "p_d_gate": json.loads((C5P_D_DIR / "s4_4c5p_d_stage_gate.json").read_text(encoding="utf-8")),
    }


def _electricity_summary(payload: dict[str, Any], configuration: str) -> dict[str, float]:
    anchors = _anchor_key(payload["anchors"])
    row = _electricity_row(payload["electricity"], configuration)
    gross = _twh_from_mwh(row["gross_modelled_process_demand"])
    asu = _twh_from_mwh(row["ASU_demand"])
    steam = _twh_from_mwh(row["boiler_steam_internal_generation"])
    gen = _twh_from_mwh(row["generator_offset"])
    post_floor = _twh_from_mwh(row["modelled_electricity_exposure"])
    components = {
        "pefa": _twh_from_mwh(_anchor_mwh(anchors, configuration, "pefa_electricity")),
        "drp": _twh_from_mwh(_anchor_mwh(anchors, configuration, "drp_electricity")),
        "eaf": _twh_from_mwh(_anchor_mwh(anchors, configuration, "eaf_electricity")),
        "dsp": _twh_from_mwh(_anchor_mwh(anchors, configuration, "dsp_electricity")),
        "sinter": _twh_from_mwh(_anchor_mwh(anchors, configuration, "sinter_electricity")),
        "hsm": _twh_from_mwh(_anchor_mwh(anchors, configuration, "boiler_hsm_rolling_electricity")),
    }
    other_boundary = gross - asu - components["pefa"] - components["drp"] - components["eaf"] - components["dsp"]
    other_unallocated = other_boundary - components["sinter"] - components["hsm"]
    return {
        "gross": gross,
        "asu": asu,
        "drp": components["drp"],
        "eaf": components["eaf"],
        "pefa": components["pefa"],
        "dsp": components["dsp"],
        "sinter": components["sinter"],
        "hsm": components["hsm"],
        "other_boundary": other_boundary,
        "other_unallocated": other_unallocated,
        "steam": steam,
        "generator": gen,
        "total_offset": steam + gen,
        "pre_floor": gross - gen,
        "post_floor": post_floor,
    }


def _electricity_component_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in [C0, C1]:
        summary = _electricity_summary(payload, configuration)
        demand_components = [
            ("PEFA_electricity", "modelled_demand", summary["pefa"], "C5n_a"),
            ("DRP_electricity", "modelled_demand", summary["drp"], "C5o_a"),
            ("EAF_electricity", "modelled_demand", summary["eaf"], "C5o_b"),
            ("DSP_electricity", "modelled_demand", summary["dsp"], "C5o_c"),
            ("Linde_ASU_electricity", "modelled_demand", summary["asu"], "C5p_a"),
            ("sinter_electricity", "modelled_demand", summary["sinter"], "C5m"),
            ("HSM_WBW_rolling_electricity", "modelled_demand", summary["hsm"], "C5l_d"),
            ("other_modelled_electricity_excluding_named_components", "modelled_demand", summary["other_unallocated"], "C5p_e derived residual within modelled scope"),
            ("gross_modelled_process_demand", "modelled_demand_total", summary["gross"], "C5p_c/C5p_e"),
        ]
        for component, component_class, value, source in demand_components:
            rows.append({
                "configuration": configuration,
                "electricity_component": component,
                "component_class": component_class,
                "unit": "TWh_e/y",
                "annual_value": _fmt(value),
                "sign_convention": "positive_demand",
                "included_in_current_modelled_process_demand": "true",
                "included_in_internal_offset": "false",
                "included_in_full_site_claim": "false",
                "source_or_stage": source,
                "boundary_status": "component_modelled_not_full_site",
                "caveat": "Current process scope only; residual/background load not modelled.",
            })
        for component, value, source in [
            ("steam_circuit_internal_generation", summary["steam"], "C5p_b"),
            ("IJ01_VN25_generator_offset", summary["generator"], "C5p_c"),
            ("total_internal_offset_reporting_only", summary["total_offset"], "C5p_g derived"),
        ]:
            rows.append({
                "configuration": configuration,
                "electricity_component": component,
                "component_class": "internal_offset_or_reporting_generation",
                "unit": "TWh_e/y",
                "annual_value": _fmt(value),
                "sign_convention": "positive_offset_subtracted_from_modelled_exposure_where_current_C5_applies_it",
                "included_in_current_modelled_process_demand": "false",
                "included_in_internal_offset": "true",
                "included_in_full_site_claim": "false",
                "source_or_stage": source,
                "boundary_status": "reporting_only_not_DA_revenue_not_full_site_claim",
                "caveat": "Internal offset only; no export revenue or DA market value.",
            })
        rows.extend([
            {
                "configuration": configuration,
                "electricity_component": "residual_electricity_load_missing",
                "component_class": "residual_missing",
                "unit": "TWh_e/y",
                "annual_value": "",
                "sign_convention": "would_be_positive_demand_if_activated_later",
                "included_in_current_modelled_process_demand": "false",
                "included_in_internal_offset": "false",
                "included_in_full_site_claim": "false",
                "source_or_stage": "C5p_g",
                "boundary_status": "not_active",
                "caveat": "Residual/background electricity is not added by this diagnostic stage.",
            },
            {
                "configuration": configuration,
                "electricity_component": "site_average_power_context_360MW",
                "component_class": "context_anchor",
                "unit": "TWh_e/y",
                "annual_value": _fmt(360.0 * 8760.0 / MWH_PER_TWH),
                "sign_convention": "positive_context_load_anchor",
                "included_in_current_modelled_process_demand": "false",
                "included_in_internal_offset": "false",
                "included_in_full_site_claim": "false",
                "source_or_stage": "source-card/context via C5p_e",
                "boundary_status": "validation_context_only",
                "caveat": "Not connection capacity and not full-site net import claim.",
            },
            {
                "configuration": configuration,
                "electricity_component": "current_total_site_consumption_context_3TWh",
                "component_class": "context_anchor",
                "unit": "TWh_e/y",
                "annual_value": _fmt(3.0),
                "sign_convention": "positive_context_load_anchor",
                "included_in_current_modelled_process_demand": "false",
                "included_in_internal_offset": "false",
                "included_in_full_site_claim": "false",
                "source_or_stage": "C5p_e context",
                "boundary_status": "validation_context_only",
                "caveat": "Context only; not executable residual load.",
            },
            {
                "configuration": configuration,
                "electricity_component": "current_residual_gas_electricity_anchor_2TWh",
                "component_class": "validation_anchor",
                "unit": "TWh_e/y",
                "annual_value": _fmt(2.0 if configuration == C0 else 0.0),
                "sign_convention": "positive_generation_validation_anchor",
                "included_in_current_modelled_process_demand": "false",
                "included_in_internal_offset": "false",
                "included_in_full_site_claim": "false",
                "source_or_stage": "IJ01/VN25 source-card via C5p_c",
                "boundary_status": "validation_anchor_only",
                "caveat": "C0 2.0 TWh is validation only and not enforced.",
            },
        ])
    return rows


def _electricity_boundary_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in [C0, C1]:
        summary = _electricity_summary(payload, configuration)
        rows.append({
            "configuration": configuration,
            "gross_modelled_process_demand_twh": _fmt(summary["gross"]),
            "asu_demand_twh": _fmt(summary["asu"]),
            "drp_demand_twh": _fmt(summary["drp"]),
            "eaf_demand_twh": _fmt(summary["eaf"]),
            "pefa_demand_twh": _fmt(summary["pefa"]),
            "dsp_demand_twh": _fmt(summary["dsp"]),
            "other_modelled_demand_twh": _fmt(summary["other_boundary"]),
            "steam_circuit_internal_generation_twh": _fmt(summary["steam"]),
            "wag_generator_offset_twh": _fmt(summary["generator"]),
            "total_internal_offset_twh": _fmt(summary["total_offset"]),
            "modelled_exposure_pre_floor_twh": _fmt(summary["pre_floor"]),
            "modelled_exposure_post_floor_twh": _fmt(summary["post_floor"]),
            "residual_electricity_load_active": "false",
            "full_site_net_import_claimed": "false",
            "boundary_status": "incomplete_reporting_only_not_full_site_net_import",
            "caveat": "Pre-floor exposure is gross current C5p_c process electricity before generator offset minus generator offset; residual electricity is not active.",
        })
    return rows


def _electricity_anchor_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    boundary = {row["configuration"]: row for row in _electricity_boundary_rows(payload)}
    rows: list[dict[str, Any]] = []
    specs = [
        ("current_tata_average_power_360MW", "current Tata/site average electric power context", 3.1536, "context_anchor", "B"),
        ("current_total_site_consumption_3TWh", "current total site electricity consumption context", 3.0, "context_anchor", "B"),
        ("current_vattenfall_residual_gas_electricity_2TWh", "C0 residual-gas electricity generation validation anchor", 2.0, "validation_anchor", "not_residual_load"),
    ]
    for configuration in [C0, C1]:
        post = _zero(boundary[configuration]["modelled_exposure_post_floor_twh"])
        pre = _zero(boundary[configuration]["modelled_exposure_pre_floor_twh"])
        for anchor_id, description, anchor, role, option in specs:
            current = pre if anchor_id == "current_vattenfall_residual_gas_electricity_2TWh" else post
            if anchor_id == "current_vattenfall_residual_gas_electricity_2TWh" and configuration == C1:
                anchor = 0.0
            residual_value = max(anchor - post, 0.0) if option == "B" else ""
            rows.append({
                "configuration": configuration,
                "anchor_id": anchor_id,
                "anchor_description": description,
                "anchor_value": _fmt(anchor),
                "unit": "TWh_e/y",
                "anchor_role": role,
                "current_model_metric": "post_floor_modelled_exposure" if option == "B" else "pre_floor_exposure_or_generator_validation",
                "current_model_value": _fmt(current),
                "gap": _fmt(current - anchor),
                "interpretation": "context_validation_only_not_executable_residual_load",
                "residual_load_option_id": option,
                "option_description": "context-anchor residual if explicitly accepted later" if option == "B" else "not a residual load option",
                "option_residual_value": _fmt(residual_value) if residual_value != "" else "",
                "option_status": "not_active",
                "recommended_action": "do not activate in C5p_g; use as context for residual electricity source review",
                "caveat": "No full-site net import claim.",
            })
    return rows


def _electricity_policy_rows() -> list[dict[str, Any]]:
    data = [
        ("A", "no_residual_electricity_load", "Keep current process-only exposure and report missing residual load.", "none", "No change; C0 remains over-offset/zero post-floor exposure.", "false", "true", "C0/C1 comparability poor for economics.", "current_diagnostic_only", "true", "false", "ELECTRICITY_BOUNDARY_INCOMPLETE"),
        ("B", "C0_context_anchor_residual", "Add residual load later to reconcile C0 to 360 MW or 3 TWh context anchor.", "explicit acceptance that context anchor can become residual-load proxy", "Raises C0 exposure from zero to context anchor basis.", "true", "true", "Can turn validation context into hidden input if not governed.", "not_recommended_without_source_review", "false", "false", "SITE_ELECTRICITY_ANCHORS_CONTEXT_ONLY"),
        ("C", "configuration_specific_source_backed_residual", "Use separate C0/C1 source-backed annual residual electricity anchors if found.", "source-backed C0 and C1 electricity boundary anchors plus policy", "Adds explicit residual load per configuration.", "true", "true", "Best economics basis but needs evidence.", "preferred_if_evidence_is_available", "true", "true", "ELECTRICITY_BOUNDARY_INCOMPLETE"),
        ("D", "common_residual_background_scaled_by_production", "Apply a common residual background load scaled by production.", "methodological sensitivity approval", "Improves comparability but not source-specific.", "true", "true", "Can mask actual C0/C1 boundary differences.", "sensitivity_only", "true", "false", "SITE_ELECTRICITY_ANCHORS_CONTEXT_ONLY"),
        ("E", "plant_category_residuals_after_source_cards", "Open source-card rows for residual plant categories, then activate only documented components.", "plant/category evidence for residual loads", "Adds transparent residual demand by category.", "true", "true", "More work but avoids one opaque residual bucket.", "recommended_next_implementation_path", "true", "true", "RESIDUAL_ELECTRICITY_NG_DIAGNOSTIC_ONLY"),
    ]
    return [
        {
            "option_id": row[0],
            "policy_name": row[1],
            "description": row[2],
            "required_evidence": row[3],
            "effect_on_modelled_exposure": row[4],
            "affects_physical_behaviour": row[5],
            "affects_economics_later": row[6],
            "risk": row[7],
            "recommended_status": row[8],
            "can_implement_before_co2": row[9],
            "can_implement_before_economics": row[10],
            "caveat": row[11],
        }
        for row in data
    ]


def _ng_summary(payload: dict[str, Any], configuration: str) -> dict[str, float]:
    row = _ng_row(payload["ng"], configuration)
    p_b = payload["p_b"][(configuration, 24)]
    p_c = payload["p_c"][(configuration, 24)]
    return {
        "drp": _zero(row["DRP_NG"]),
        "eaf": _zero(row["EAF_NG"]),
        "generator": _zero(row["generator_NG"]),
        "boiler": _pj_from_mwh(p_b["NG_backup_for_steam_MWh_LHV_y"]),
        "pefa": _zero(row["PEFA_NG_backup"]),
        "total": _zero(row["total_modelled_NG"]),
        "vn25": _pj_from_mwh(p_c.get("VN25_NG_MWh_LHV_y", 0.0)),
        "ij01": _pj_from_mwh(p_c.get("IJ01_NG_MWh_LHV_y", 0.0)),
    }


def _ng_component_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in [C0, C1]:
        summary = _ng_summary(payload, configuration)
        for component, component_class, value, source, caveat in [
            ("DRP_NG_total", "modelled_ng_demand", summary["drp"], "C5o_a", "Includes reduction and process furnace split in DRP artifact."),
            ("EAF_NG", "modelled_ng_demand", summary["eaf"], "C5o_b", "Component-level EAF NG only."),
            ("VN25_IJ01_generator_NG", "modelled_ng_demand", summary["generator"], "C5p_c", "Generator NG is interface accounting, not economics."),
            ("boiler_steam_NG_backup", "zero_or_backup_option", summary["boiler"], "C5p_b", "NG backup eligibility exists but current run is zero."),
            ("PEFA_NG_backup", "zero_or_backup_option", summary["pefa"], "C5n_a", "PEFA NG backup is zero in current artifacts."),
            ("other_modelled_NG", "modelled_ng_demand", max(summary["total"] - summary["drp"] - summary["eaf"] - summary["generator"] - summary["boiler"] - summary["pefa"], 0.0), "C5p_g derived", "No other NG component is active in current C5 boundary."),
            ("total_modelled_NG", "modelled_ng_total", summary["total"], "C5p_e", "Component-level total only; not full-site NG."),
            ("residual_or_unmodelled_NG_missing", "residual_missing", "", "C5p_g", "Residual/background NG is not added by this diagnostic stage."),
        ]:
            rows.append({
                "configuration": configuration,
                "ng_component": component,
                "component_class": component_class,
                "unit": "PJ_LHV/y",
                "annual_value_pj": _fmt(value),
                "included_in_current_modelled_ng": "true" if component_class.startswith("modelled") or component_class == "zero_or_backup_option" else "false",
                "source_or_stage": source,
                "boundary_status": "component_modelled_not_full_site" if component_class != "residual_missing" else "not_active",
                "caveat": caveat,
            })
    return rows


def _ng_boundary_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in [C0, C1]:
        summary = _ng_summary(payload, configuration)
        other = max(summary["total"] - summary["drp"] - summary["eaf"] - summary["generator"] - summary["boiler"] - summary["pefa"], 0.0)
        rows.append({
            "configuration": configuration,
            "drp_ng_pj": _fmt(summary["drp"]),
            "eaf_ng_pj": _fmt(summary["eaf"]),
            "generator_ng_pj": _fmt(summary["generator"]),
            "boiler_steam_ng_pj": _fmt(summary["boiler"]),
            "pefa_ng_pj": _fmt(summary["pefa"]),
            "other_modelled_ng_pj": _fmt(other),
            "total_modelled_ng_pj": _fmt(summary["total"]),
            "residual_ng_load_active": "false",
            "full_site_ng_claimed": "false",
            "boundary_status": "incomplete_no_full_site_NG_claim",
            "caveat": "Residual/unmodelled NG boundary is open; no costs or CO2 are added here.",
        })
    return rows


def _ng_anchor_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in [C0, C1]:
        summary = _ng_summary(payload, configuration)
        drp_anchor = 27.72 if configuration == C1 else 0.0
        vn25_ng_anchor = 4.1 if configuration == C1 else 0.0
        specs = [
            ("DRP_NG_source_anchor", "DRP NG reduction plus process furnace derived anchor", drp_anchor, summary["drp"], "validation_or_development_anchor", "B"),
            ("VN25_NG_C1_anchor", "VN25 C1 NG preferred annual anchor", vn25_ng_anchor, summary["generator"], "validation_anchor", "not_residual_load"),
            ("boiler_steam_NG_backup_eligibility", "boiler/steam NG backup eligibility", 0.0, summary["boiler"], "eligibility_not_active_demand", "C"),
            ("site_level_NG_anchor", "site-level residual/full-site NG anchor", "", summary["total"], "missing_or_context_only", "E"),
        ]
        for anchor_id, description, anchor, current, role, option in specs:
            gap = "" if anchor == "" else _fmt(current - anchor)
            rows.append({
                "configuration": configuration,
                "anchor_id": anchor_id,
                "anchor_description": description,
                "anchor_value": _fmt(anchor),
                "unit": "PJ_LHV/y",
                "anchor_role": role,
                "current_model_metric": "current_component_or_total_modelled_NG",
                "current_model_value": _fmt(current),
                "gap": gap,
                "interpretation": "component_anchor_not_full_site_NG" if anchor_id != "site_level_NG_anchor" else "site_level_anchor_missing",
                "residual_ng_option_id": option,
                "option_description": "source-backed residual NG if anchor exists" if option == "B" else "component-specific/source-card residual policy" if option == "C" else "keep blocked until evidence" if option == "E" else "not residual load",
                "option_residual_value": "",
                "option_status": "not_active",
                "recommended_action": "do not activate residual NG in C5p_g; source-card evidence required",
                "caveat": "No full-site NG claim.",
            })
    return rows


def _ng_policy_rows() -> list[dict[str, Any]]:
    data = [
        ("A", "no_residual_NG_load", "Keep current component-level NG only.", "none", "No change; C0 NG remains zero and C1 is DRP/EAF/generator only.", "false", "true", "Incomplete for economics and CO2.", "current_diagnostic_only", "true", "false", "NG_BOUNDARY_INCOMPLETE"),
        ("B", "source_backed_annual_residual_NG", "Add residual annual NG only if a full-site/source-backed anchor is found.", "source-backed annual residual/full-site NG evidence", "Adds explicit residual NG load.", "true", "true", "Best option but currently lacks source evidence.", "preferred_if_evidence_is_available", "true", "true", "SITE_NG_ANCHORS_MISSING_OR_CONTEXT_ONLY"),
        ("C", "component_specific_residual_NG", "Add boiler/HSM/other utility NG residuals only after component source-card evidence.", "component source evidence", "Adds transparent residual NG by component.", "true", "true", "Requires more source work.", "recommended_next_if_component_evidence_exists", "true", "true", "NG_BOUNDARY_INCOMPLETE"),
        ("D", "common_residual_NG_background", "Use common residual NG background load as sensitivity only.", "methodological sensitivity approval", "Adds opaque background NG.", "true", "true", "Can hide boundary gaps.", "sensitivity_only", "true", "false", "SITE_NG_ANCHORS_MISSING_OR_CONTEXT_ONLY"),
        ("E", "block_residual_NG_until_evidence", "Do not activate residual NG until source-card evidence exists.", "none", "No change; keeps full-site NG claim blocked.", "false", "true", "CO2/economics remain blocked.", "recommended_current_policy", "true", "false", "NG_BOUNDARY_INCOMPLETE"),
    ]
    return [
        {
            "option_id": row[0],
            "policy_name": row[1],
            "description": row[2],
            "required_evidence": row[3],
            "effect_on_modelled_ng": row[4],
            "affects_physical_behaviour": row[5],
            "affects_economics_later": row[6],
            "risk": row[7],
            "recommended_status": row[8],
            "can_implement_before_co2": row[9],
            "can_implement_before_economics": row[10],
            "caveat": row[11],
        }
        for row in data
    ]


def _decision_rows() -> list[dict[str, Any]]:
    return [
        {
            "decision_id": "DEC_RESIDUAL_ELECTRICITY_POLICY",
            "topic": "residual electricity boundary",
            "current_status": "not_active_boundary_incomplete",
            "evidence_status": "process demand and internal offsets are represented; residual/background site load is missing",
            "options": "A no residual; B context-anchor residual; C config-specific source-backed residual; D common scaled residual; E plant-category residuals",
            "recommended_option": "E_plant_category_residuals_after_source_cards_or_C_if_config_anchors_are_found",
            "rationale": "A source-backed/category residual layer is more transparent than forcing 360 MW or 3 TWh context anchors.",
            "affects_model_equations_now": "false",
            "affects_physical_behaviour_later": "true",
            "affects_economics_later": "true",
            "must_fix_before_commit": "false",
            "must_fix_before_co2": "false",
            "must_fix_before_economics": "true",
            "can_defer_to_sensitivity": "false",
            "thesis_reporting_caveat": "no full-site net import claim",
            "caveat": "ELECTRICITY_BOUNDARY_INCOMPLETE",
        },
        {
            "decision_id": "DEC_C0_ELECTRICITY_OVER_OFFSET",
            "topic": "C0 electricity over-offset/zero exposure",
            "current_status": "visible_in_C5p_g",
            "evidence_status": "C0 generator offset exceeds current modelled process electricity before generator offset",
            "options": "report pre-floor; add residual load later; cap generator later only with evidence",
            "recommended_option": "report_pre_floor_and_defer_policy_until_residual_load_evidence",
            "rationale": "Flooring to zero should not hide over-offset, but this diagnostic must not add a residual load.",
            "affects_model_equations_now": "false",
            "affects_physical_behaviour_later": "true",
            "affects_economics_later": "true",
            "must_fix_before_commit": "false",
            "must_fix_before_co2": "false",
            "must_fix_before_economics": "true",
            "can_defer_to_sensitivity": "true",
            "thesis_reporting_caveat": "C0 exposure is process-only and incomplete",
            "caveat": "C0_ELECTRICITY_OVER_OFFSET_OR_ZERO_EXPOSURE_REQUIRES_POLICY",
        },
        {
            "decision_id": "DEC_RESIDUAL_NG_POLICY",
            "topic": "residual natural-gas boundary",
            "current_status": "not_active_boundary_incomplete",
            "evidence_status": "C1 DRP/EAF/generator NG are modelled; site-level residual NG anchor is missing",
            "options": "A no residual; B source-backed residual; C component-specific residual; D common sensitivity; E block until evidence",
            "recommended_option": "E_block_until_evidence_with_C_if_component_source_cards_are_added",
            "rationale": "Current NG is component-level only; a common residual bucket would be too opaque before CO2/economics.",
            "affects_model_equations_now": "false",
            "affects_physical_behaviour_later": "true",
            "affects_economics_later": "true",
            "must_fix_before_commit": "false",
            "must_fix_before_co2": "true",
            "must_fix_before_economics": "true",
            "can_defer_to_sensitivity": "false",
            "thesis_reporting_caveat": "no full-site NG claim",
            "caveat": "NG_BOUNDARY_INCOMPLETE",
        },
        {
            "decision_id": "DEC_CO2_DEPENDENCY",
            "topic": "CO2 dependency on energy boundary",
            "current_status": "CO2_boundary_dependent",
            "evidence_status": "NG and WAG combustion attribution remain incomplete",
            "options": "run CO2 now with caveats; run after residual energy source review; parallel diagnostic only",
            "recommended_option": "CO2_diagnostic_can_follow_but_no_ETS_or_objective_until_energy_boundary_resolved",
            "rationale": "Fuel attribution affects emissions and double-counting risk.",
            "affects_model_equations_now": "false",
            "affects_physical_behaviour_later": "false",
            "affects_economics_later": "true",
            "must_fix_before_commit": "false",
            "must_fix_before_co2": "false",
            "must_fix_before_economics": "true",
            "can_defer_to_sensitivity": "false",
            "thesis_reporting_caveat": "component CO2 only",
            "caveat": "CO2_BOUNDARY_DEPENDS_ON_ENERGY_BOUNDARY",
        },
        {
            "decision_id": "DEC_ECONOMICS_DA_READINESS",
            "topic": "economics and DA readiness",
            "current_status": "NO_GO",
            "evidence_status": "denominator unresolved and residual energy boundaries incomplete",
            "options": "continue diagnostics; activate residual loads after evidence; economics later",
            "recommended_option": "NO_GO_until_residual_energy_CO2_and_denominator_policy_are_resolved",
            "rationale": "DA/economics need a stable load/import boundary and denominator.",
            "affects_model_equations_now": "false",
            "affects_physical_behaviour_later": "true",
            "affects_economics_later": "true",
            "must_fix_before_commit": "false",
            "must_fix_before_co2": "false",
            "must_fix_before_economics": "true",
            "can_defer_to_sensitivity": "false",
            "thesis_reporting_caveat": "not economics-ready",
            "caveat": "ECONOMICS_NO_GO",
        },
    ]


def _redflag_rows(payload: dict[str, Any], electricity_boundary: list[dict[str, Any]], ng_boundary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pc0 = payload["p_c"][(C0, 24)]
    pc1 = payload["p_c"][(C1, 24)]
    pf = payload["p_f_gate"]
    checks = {
        "RESIDUAL_ELECTRICITY_LOAD_ADDED_IN_DIAGNOSTIC_STAGE": any(row["residual_electricity_load_active"] == "true" for row in electricity_boundary),
        "RESIDUAL_NG_LOAD_ADDED_IN_DIAGNOSTIC_STAGE": any(row["residual_ng_load_active"] == "true" for row in ng_boundary),
        "ELECTRICITY_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION": False,
        "NG_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION": False,
        "FULL_SITE_NET_IMPORT_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY": any(row["full_site_net_import_claimed"] == "true" for row in electricity_boundary),
        "FULL_SITE_NG_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY": any(row["full_site_ng_claimed"] == "true" for row in ng_boundary),
        "C0_ELECTRICITY_OVER_OFFSET_HIDDEN_BY_FLOORING": False,
        "GENERATOR_ELECTRICITY_COUNTED_AS_DA_REVENUE": pc0["DA_market_revenue_active"] == "true" or pc1["DA_market_revenue_active"] == "true",
        "GENERATOR_EXPORT_REVENUE_ACTIVE": pc0["export_revenue_enabled_base"] == "true" or pc1["export_revenue_enabled_base"] == "true",
        "WAG_DIRECT_MARKET_VALUE_ACTIVE": False,
        "DA_PRICE_OR_ECONOMICS_ACTIVE": False,
        "CO2_ETS_READY_CLAIMED_BEFORE_BOUNDARY": False,
        "DENOMINATOR_SILENTLY_FROZEN": "unresolved" not in pf["denominator_status"],
        "PRODUCTION_POLICY_CHANGED_DURING_BOUNDARY_DIAGNOSTIC": False,
        "C5L_D_BASE_0_50_REVERTED": False,
        "COKE_RECONCILIATION_BASELINE_REOPENED": pc1["coke_reconciliation_baseline_status"] != "C5m_f_bounded_coke_reconciliation_active_development_baseline",
        "THESIS_USABILITY_TRUE_FOR_DEVELOPMENT_ROWS": bool(pf["thesis_usability"]),
    }
    rows: list[dict[str, Any]] = []
    for flag in FAILURE_FLAGS:
        active = checks[flag]
        rows.append({
            "red_flag": flag,
            "active": str(active).lower(),
            "severity": "failure",
            "evidence": "C5p_g residual boundary diagnostic check",
            "recommended_action": "fix before commit/economics if active" if active else "none",
        })
    for caveat in CAVEATS:
        rows.append({
            "red_flag": caveat,
            "active": "true",
            "severity": "caveat",
            "evidence": "residual electricity/NG diagnostic caveat",
            "recommended_action": "carry into CO2 and economics readiness review",
        })
    return rows


def _write_report(gate: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C5 Residual Electricity / NG Boundary Diagnostics",
        "",
        "Diagnostic-only C5p_g stage. It does not add residual electricity loads, residual NG loads, costs, CO2 logic, DA revenue, mFRR, WAG market value, or a frozen denominator.",
        "",
        "## Stage Gate",
        "",
        f"- Decision: `{gate['decision']}`",
        f"- Failure count: `{gate['failure_count']}`",
        f"- Caveat count: `{gate['caveat_count']}`",
        f"- Electricity boundary: `{gate['electricity_boundary_status']}`",
        f"- NG boundary: `{gate['ng_boundary_status']}`",
        f"- CO2 dependency: `{gate['co2_boundary_dependency_status']}`",
        "",
        "## Findings",
        "",
        f"- C0 current process-only electricity exposure pre-floor is `{_fmt(gate['C0_modelled_exposure_pre_floor_TWh_y'])}` TWh/y and post-floor is `{_fmt(gate['C0_modelled_exposure_post_floor_TWh_y'])}` TWh/y.",
        f"- C1 current process-only electricity exposure post-floor is `{_fmt(gate['C1_modelled_exposure_post_floor_TWh_y'])}` TWh/y.",
        f"- C1 modelled NG is `{_fmt(gate['C1_total_modelled_NG_PJ_y'])}` PJ/y, composed of DRP, EAF and generator NG in the current boundary.",
        "- Electricity and NG residual options are registered but not applied.",
        "- Economics and DA readiness remain NO-GO.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_outputs() -> dict[str, Any]:
    C5P_G_DIR.mkdir(parents=True, exist_ok=True)
    payload = _payload()
    electricity_components = _electricity_component_rows(payload)
    electricity_boundary = _electricity_boundary_rows(payload)
    electricity_anchors = _electricity_anchor_rows(payload)
    electricity_policies = _electricity_policy_rows()
    ng_components = _ng_component_rows(payload)
    ng_boundary = _ng_boundary_rows(payload)
    ng_anchors = _ng_anchor_rows(payload)
    ng_policies = _ng_policy_rows()
    decisions = _decision_rows()
    redflags = _redflag_rows(payload, electricity_boundary, ng_boundary)
    failure_count = sum(1 for row in redflags if row["severity"] == "failure" and row["active"] == "true")
    caveat_count = sum(1 for row in redflags if row["severity"] == "caveat" and row["active"] == "true")
    e_by_config = {row["configuration"]: row for row in electricity_boundary}
    ng_by_config = {row["configuration"]: row for row in ng_boundary}
    gate = {
        "stage_id": STAGE,
        "decision": "pass_development_residual_electricity_ng_boundary_diagnostics" if failure_count == 0 else "fail_development_residual_electricity_ng_boundary_diagnostics",
        "status": "development_only",
        "thesis_usability": False,
        "output_directory": str(C5P_G_DIR).replace("\\", "/"),
        "failure_count": failure_count,
        "caveat_count": caveat_count,
        "C0_gross_modelled_process_demand_TWh_y": _zero(e_by_config[C0]["gross_modelled_process_demand_twh"]),
        "C0_total_internal_offset_TWh_y": _zero(e_by_config[C0]["total_internal_offset_twh"]),
        "C0_modelled_exposure_pre_floor_TWh_y": _zero(e_by_config[C0]["modelled_exposure_pre_floor_twh"]),
        "C0_modelled_exposure_post_floor_TWh_y": _zero(e_by_config[C0]["modelled_exposure_post_floor_twh"]),
        "C1_gross_modelled_process_demand_TWh_y": _zero(e_by_config[C1]["gross_modelled_process_demand_twh"]),
        "C1_total_internal_offset_TWh_y": _zero(e_by_config[C1]["total_internal_offset_twh"]),
        "C1_modelled_exposure_pre_floor_TWh_y": _zero(e_by_config[C1]["modelled_exposure_pre_floor_twh"]),
        "C1_modelled_exposure_post_floor_TWh_y": _zero(e_by_config[C1]["modelled_exposure_post_floor_twh"]),
        "C0_total_modelled_NG_PJ_y": _zero(ng_by_config[C0]["total_modelled_ng_pj"]),
        "C1_total_modelled_NG_PJ_y": _zero(ng_by_config[C1]["total_modelled_ng_pj"]),
        "electricity_boundary_status": "incomplete_reporting_only_not_full_site_net_import",
        "ng_boundary_status": "incomplete_no_full_site_NG_claim",
        "co2_boundary_dependency_status": "CO2_boundary_depends_on_energy_boundary",
        "recommended_residual_electricity_policy": "plant_category_residuals_after_source_cards_or_config_specific_source_backed_residual_if_available",
        "recommended_residual_ng_policy": "block_residual_NG_until_source_evidence_or_component_specific_source_cards",
        "residual_electricity_load_active": False,
        "residual_ng_load_active": False,
        "economics_readiness": "NO_GO",
        "DA_readiness": "NO_GO",
        "denominator_status": payload["p_f_gate"]["denominator_status"],
        "generator_electricity_value_mode": payload["p_f_gate"]["generator_electricity_value_mode"],
        "electricity_accounting_status": payload["p_f_gate"]["electricity_accounting_status"],
    }

    _write_csv(C5P_G_DIR / "c5_residual_electricity_component_balance.csv", electricity_components, ELECTRICITY_COMPONENT_COLUMNS)
    _write_csv(C5P_G_DIR / "c5_residual_electricity_boundary_matrix.csv", electricity_boundary, ELECTRICITY_BOUNDARY_COLUMNS)
    _write_csv(C5P_G_DIR / "c5_residual_electricity_anchor_gap_options.csv", electricity_anchors, ELECTRICITY_ANCHOR_COLUMNS)
    _write_csv(C5P_G_DIR / "c5_residual_electricity_policy_options.csv", electricity_policies, ELECTRICITY_POLICY_COLUMNS)
    _write_csv(C5P_G_DIR / "c5_residual_ng_component_balance.csv", ng_components, NG_COMPONENT_COLUMNS)
    _write_csv(C5P_G_DIR / "c5_residual_ng_boundary_matrix.csv", ng_boundary, NG_BOUNDARY_COLUMNS)
    _write_csv(C5P_G_DIR / "c5_residual_ng_anchor_gap_options.csv", ng_anchors, NG_ANCHOR_COLUMNS)
    _write_csv(C5P_G_DIR / "c5_residual_ng_policy_options.csv", ng_policies, NG_POLICY_COLUMNS)
    _write_csv(C5P_G_DIR / "c5_residual_energy_boundary_decision_register.csv", decisions, DECISION_COLUMNS)
    _write_csv(C5P_G_DIR / "c5_residual_energy_boundary_red_flags.csv", redflags, REDFLAG_COLUMNS)
    _write_json(C5P_G_DIR / "s4_4c5p_g_stage_gate.json", gate)
    _write_csv(
        C5P_G_DIR / "s4_4c5p_g_run_registry.csv",
        [{
            "stage": STAGE,
            "source_stage": "S4.4c5p_f_pre_economics_alignment_gate",
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
            "electricity_components": len(electricity_components),
            "electricity_boundary": len(electricity_boundary),
            "electricity_anchors": len(electricity_anchors),
            "electricity_policies": len(electricity_policies),
            "ng_components": len(ng_components),
            "ng_boundary": len(ng_boundary),
            "ng_anchors": len(ng_anchors),
            "ng_policies": len(ng_policies),
            "decisions": len(decisions),
            "redflags": len(redflags),
        },
    }
    _write_json(C5P_G_DIR / "s4_4c5p_g_summary.json", summary)
    _write_report(gate)
    return summary


def run_s4_4c5p_g_residual_electricity_ng_boundary_diagnostics() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5p_g_residual_electricity_ng_boundary_diagnostics(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
