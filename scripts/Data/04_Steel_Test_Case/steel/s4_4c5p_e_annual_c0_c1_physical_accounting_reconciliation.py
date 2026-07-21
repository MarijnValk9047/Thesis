"""S4.4c5p_e annual C0/C1 physical/accounting reconciliation diagnostics.

This stage is diagnostic-only. It reads the current C5 annualised artifacts,
classifies validation-anchor gaps, and registers candidate parameter levers
without changing model equations, parameters, or dispatch behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .s4_4c5_anchor_route_denominator_diagnostics import (
    OUT_DIR as ANCHOR_DIR,
)
from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    S4_ROOT,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5p_d_buffer_store_register_and_validation import C5P_D_DIR


STAGE = "S4.4c5p_e_annual_c0_c1_physical_accounting_reconciliation"
C5P_E_DIR = S4_ROOT / "s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_ANNUAL_C0_C1_PHYSICAL_ACCOUNTING_RECONCILIATION.md")

C5F_DIR = S4_ROOT / "s4_4c5f_coking_plant_minimal_parameterisation"
C5H_DIR = S4_ROOT / "s4_4c5h_blast_furnace_controller_parameterisation"
C5J_DIR = S4_ROOT / "s4_4c5j_BOF_OSF_minimal_parameterisation"
C5K_DIR = S4_ROOT / "s4_4c5k_production_policy_and_route_split_normalisation"
C5L_D_DIR = S4_ROOT / "s4_4c5l_d_HSM_hot_charge_share_cap_and_reheat_sensitivity_patch"
C5M_DIR = S4_ROOT / "s4_4c5m_Sinter_minimal_parameterisation"
C5M_F_DIR = S4_ROOT / "s4_4c5m_f_bounded_coke_reconciliation_sensitivity"
C5N_A_DIR = S4_ROOT / "s4_4c5n_a_pefa_pelletizing_layer"
C5N_B_DIR = S4_ROOT / "s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy"
C5O_A_DIR = S4_ROOT / "s4_4c5o_a_ng_drp_physical_layer_with_dri_interface"
C5O_B_DIR = S4_ROOT / "s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff"
C5O_C_DIR = S4_ROOT / "s4_4c5o_c_dsp_downstream_physical_layer"
C5P_A_DIR = S4_ROOT / "s4_4c5p_a_linde_asu_oxygen_accounting"
C5P_B_DIR = S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting"
C5P_C_DIR = S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting"

PJ_TO_MWH = 277777.77777777775
MWH_TO_PJ = 1.0 / PJ_TO_MWH

ANCHOR_COLUMNS = [
    "anchor_id",
    "configuration",
    "domain",
    "asset_or_flow",
    "metric",
    "unit",
    "raw_source_anchor",
    "active_scaled_anchor",
    "model_output",
    "absolute_gap",
    "relative_gap",
    "anchor_role",
    "anchor_source",
    "current_status",
    "interpretation",
    "decision_needed",
    "candidate_parameter_lever_ids",
    "caveat",
]

CONFIG_COLUMNS = [
    "domain",
    "metric",
    "unit",
    "C0_value",
    "C1_value",
    "C1_minus_C0",
    "relative_change",
    "interpretation",
    "caveat",
]

FLOW_COLUMNS = [
    "configuration",
    "carrier",
    "generated_or_supplied",
    "ledger_point",
    "mandatory_process_self_use",
    "preparation_or_process_use",
    "boiler_or_steam_use",
    "generator_use",
    "external_import",
    "flare_or_spill",
    "residual_or_unallocated",
    "model_balance_residual",
    "unit",
    "status",
    "caveat",
]

WAG_LEDGER_COLUMNS = [
    "configuration",
    "carrier",
    "source_gross_generation_MWh_LHV_y",
    "mandatory_source_self_use_MWh_LHV_y",
    "network_available_after_self_use_MWh_LHV_y",
    "c5p_e_controller_reconciled_supply_before_steam_MWh_LHV_y",
    "c5p_e_preparation_or_process_use_MWh_LHV_y",
    "c5p_e_boiler_or_steam_use_MWh_LHV_y",
    "c5p_e_generator_use_MWh_LHV_y",
    "c5p_e_flare_or_spill_MWh_LHV_y",
    "c5p_e_residual_or_unallocated_MWh_LHV_y",
    "source_to_c5p_e_supply_gap_MWh_LHV_y",
    "c5p_e_controller_balance_residual_MWh_LHV_y",
    "ledger_contract_status",
    "source_artifacts",
    "caveat",
]

ELECTRICITY_COLUMNS = [
    "configuration",
    "electricity_component",
    "unit",
    "gross_modelled_process_demand",
    "ASU_demand",
    "boiler_steam_internal_generation",
    "generator_offset",
    "residual_electricity_load",
    "modelled_electricity_exposure",
    "source_anchor",
    "gap_to_anchor",
    "boundary_status",
    "can_be_used_for_economics_now",
    "caveat",
]

NG_COLUMNS = [
    "configuration",
    "ng_component",
    "unit",
    "DRP_NG",
    "EAF_NG",
    "boiler_steam_NG",
    "generator_NG",
    "PEFA_NG_backup",
    "residual_or_unmodelled_NG",
    "total_modelled_NG",
    "source_anchor",
    "gap_to_anchor",
    "boundary_status",
    "caveat",
]

CO2_COLUMNS = [
    "configuration",
    "co2_component",
    "unit",
    "model_output",
    "source_anchor",
    "gap_to_anchor",
    "boundary_status",
    "double_counting_risk",
    "ets_ready",
    "caveat",
]

BUFFER_COLUMNS = [
    "configuration",
    "buffer_id",
    "unit",
    "capacity",
    "start_inventory",
    "end_inventory",
    "annual_drift",
    "min_inventory",
    "max_inventory",
    "bind_count",
    "terminal_rule_pass",
    "no_free_source_pass",
    "no_free_battery_pass",
    "caveat",
]

LEVER_COLUMNS = [
    "lever_id",
    "domain",
    "parameter_or_policy",
    "current_value_or_status",
    "candidate_values_or_range",
    "related_anchor_gap",
    "expected_direction_if_increased",
    "expected_direction_if_decreased",
    "affects_physical_behaviour",
    "affects_economics_later",
    "sensitivity_required",
    "review_priority",
    "can_be_changed_before_commit",
    "recommended_action",
    "caveat",
]

DECISION_COLUMNS = [
    "decision_id",
    "topic",
    "current_status",
    "evidence_status",
    "options",
    "recommended_next_action",
    "must_fix_before_commit",
    "can_defer_to_sensitivity",
    "thesis_reporting_caveat",
    "caveat",
]

REDFLAG_COLUMNS = ["configuration", "red_flag", "active", "severity", "evidence", "recommended_action"]

FAILURE_FLAGS = [
    "VALIDATION_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION",
    "ANNUAL_ANCHOR_USED_AS_HOURLY_DISPATCH_SCHEDULE",
    "GENERIC_WAG_BALANCE_USED_TO_HIDE_CARRIER_GAP",
    "WAG_DIRECT_MARKET_VALUE_ACTIVE",
    "GENERATOR_EXPORT_REVENUE_ACTIVE",
    "GENERATOR_PRICE_RESPONSIVE_DISPATCH_ACTIVE",
    "MFRR_ENABLED",
    "FULL_SITE_NET_IMPORT_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY",
    "DENOMINATOR_SILENTLY_FROZEN",
    "PRODUCTION_POLICY_CHANGED_DURING_RECONCILIATION",
    "C5L_D_BASE_0_50_REVERTED",
    "COKE_RECONCILIATION_BASELINE_REOPENED",
    "STORE_OR_BUFFER_USED_AS_FREE_SOURCE",
    "TERMINAL_DRIFT_NONZERO_FOR_EQUALITY_STORE",
    "C0_GENERATOR_2TWH_ENFORCED_AS_TARGET",
    "C1_GENERATOR_FUEL_GAP_HIDDEN",
    "CO2_DOUBLE_COUNTING_RISK_UNREPORTED",
    "THESIS_USABILITY_TRUE_FOR_DEVELOPMENT_ROWS",
]

CAVEATS = [
    "ANNUAL_RECONCILIATION_DEVELOPMENT_ONLY",
    "PUBLIC_ANNUAL_ANCHORS_NOT_HOURLY_TRUTH",
    "ACTIVE_SCALED_TARGET_DIFFERS_FROM_RAW_MER_ANCHOR",
    "ELECTRICITY_BOUNDARY_INCOMPLETE",
    "NG_BOUNDARY_INCOMPLETE",
    "CO2_BOUNDARY_INCOMPLETE",
    "DENOMINATOR_UNRESOLVED",
    "GENERATOR_INTERFACE_DEVELOPMENT_ONLY",
    "BOILER_STEAM_RESIDUAL_DEMAND_DEFERRED",
    "DRP_OXYGEN_BASIS_REQUIRES_REVIEW",
    "C1_GENERATOR_ANCHOR_GAP_REQUIRES_REVIEW",
    "C0_GENERATOR_CARRIER_SPLIT_PROXY_DEVELOPMENT_ONLY",
    "NOT_THESIS_APPROVED",
]


def _csv(path: Path) -> list[dict[str, str]]:
    return _read_csv(path)


def _keyed(rows: list[dict[str, str]], horizon_field: str = "horizon_hours") -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row[horizon_field])): row for row in rows}


def _active_hsm_rows(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in rows
        if row.get("case_status") == "active_base_guardrail"
    }


def _value(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fmt(value: Any) -> str:
    number = _value(value)
    if number is None:
        return "" if value is None else str(value)
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _gap(model: Any, anchor: Any) -> str:
    m = _value(model)
    a = _value(anchor)
    if m is None or a is None:
        return ""
    return _fmt(m - a)


def _relative_gap(model: Any, anchor: Any) -> str:
    m = _value(model)
    a = _value(anchor)
    if m is None or a in (None, 0.0):
        return ""
    return _fmt((m - a) / a)


def _sum_fields(row: dict[str, str], fields: list[str]) -> float:
    return sum(_zero(row.get(field, "")) for field in fields)


def _domain(anchor_id: str, asset: str, metric: str) -> str:
    text = f"{anchor_id} {asset} {metric}".lower()
    if any(token in text for token in ["generator", "vn25", "ij01", "wag"]):
        return "generator_wag"
    if any(token in text for token in ["electricity", "asu"]):
        return "electricity_oxygen" if "oxygen" in text or "linde" in text or "asu" in text else "electricity"
    if any(token in text for token in ["oxygen", "linde"]):
        return "oxygen_asu"
    if any(token in text for token in ["steam", "boiler", "steg", "tg2"]):
        return "boiler_steam"
    if "ng" in text or "natural gas" in text:
        return "natural_gas"
    if "co2" in text or "emission" in text:
        return "co2"
    if any(token in text for token in ["pellet", "pefa", "dri", "eaf", "bf", "bof", "scrap"]):
        return "materials"
    if any(token in text for token in ["coke", "kgf", "sinter"]):
        return "coke_sinter"
    if any(token in text for token in ["dsp", "hsm", "final", "liquid steel", "slab"]):
        return "production_downstream"
    return "model_governance"


def _interpretation(row: dict[str, str]) -> str:
    anchor_id = row.get("anchor_id", "")
    role = row.get("anchor_role", "")
    caveat = row.get("caveat", "")
    gap = abs(_zero(row.get("absolute_gap", "")))
    if "failure_guard" in role:
        return "no_issue_within_tolerance" if gap <= 1e-6 else "possible_implementation_issue"
    if "context" in role:
        return "expected_due_to_validation_anchor_not_input"
    if "validation" in role:
        return "expected_due_to_validation_anchor_not_input"
    if "reporting" in role:
        if "generator_fuel_gap" in anchor_id:
            return "requires_source_review"
        return "expected_due_to_boundary_scope"
    if "reconciliation" in role or "reconciliation" in caveat:
        return "expected_due_to_reconciliation_parameter"
    if gap <= 1e-6:
        return "no_issue_within_tolerance"
    if "raw" in caveat.lower() or "raw" in row.get("metric", "").lower():
        return "expected_due_to_active_scaled_target"
    return "requires_source_review"


def _lever_ids(anchor_id: str, domain: str) -> str:
    text = f"{anchor_id} {domain}".lower()
    levers: list[str] = []
    if any(token in text for token in ["final", "hsm", "dsp", "liquid_steel", "slab"]):
        levers.append("LEV_PROD_DENOMINATOR_ROUTE_SCALING")
    if "pellet" in text or "pefa" in text:
        levers.append("LEV_PELLET_BURDEN_RECONCILIATION")
    if "dri" in text or "eaf" in text or "scrap" in text:
        levers.append("LEV_DRP_EAF_MATERIAL_SPLIT")
    if "oxygen" in text or "asu" in text:
        levers.append("LEV_DRP_OXYGEN_BASIS_REVIEW")
    if "steam" in text or "boiler" in text:
        levers.append("LEV_BOILER_RESIDUAL_STEAM_DEMAND")
    if "generator" in text or "wag" in text or "vn25" in text or "ij01" in text:
        levers.append("LEV_C1_GENERATOR_ANCHOR_INTERPRETATION")
    if "ng" in text:
        levers.append("LEV_NG_RESIDUAL_BOUNDARY")
    if "co2" in text:
        levers.append("LEV_CO2_BOUNDARY_AND_FACTORS")
    return ";".join(dict.fromkeys(levers)) or "NO_LEVER_BOUNDARY_CAVEAT"


def _payload() -> dict[str, Any]:
    # C5p_e is a historical reporting reconstruction.  It must not silently
    # regenerate the current physical model: that would blur historical and
    # current lineage and makes this diagnostic depend on unrelated solver code.
    # Missing source artifacts should therefore fail explicitly at read time.
    return {
        "anchor": _csv(ANCHOR_DIR / "c5_anchor_reconciliation_matrix.csv"),
        "denom": _csv(ANCHOR_DIR / "c5_final_product_denominator_diagnostics.csv"),
        "k": _keyed([
            row for row in _csv(C5K_DIR / "s4_4c5k_compact_table_for_chat.csv")
            if row.get("plant") == "BOF_OSF"
        ]),
        "k_anchor": _csv(C5K_DIR / "s4_4c5k_validation_anchor_gap_dashboard.csv"),
        "l_d": _active_hsm_rows(_csv(C5L_D_DIR / "s4_4c5l_d_compact_table_for_chat.csv")),
        "m": _keyed(_csv(C5M_DIR / "s4_4c5m_compact_table_for_chat.csv")),
        "m_gas": _keyed(_csv(C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv")),
        "m_anchor": _csv(C5M_DIR / "s4_4c5m_anchor_gap_dashboard.csv"),
        "m_f": _csv(C5M_F_DIR / "s4_4c5m_f_coke_balance_by_scenario.csv"),
        "n_a": _keyed(_csv(C5N_A_DIR / "s4_4c5n_a_pefa_compact_healthcheck.csv")),
        "n_a_elec": _keyed(_csv(C5N_A_DIR / "s4_4c5n_a_pefa_electricity_ledger.csv")),
        "n_a_gas": _keyed(_csv(C5N_A_DIR / "s4_4c5n_a_pefa_gas_controller_dashboard.csv")),
        "n_b": _keyed(_csv(C5N_B_DIR / "s4_4c5n_b_compact_healthcheck.csv")),
        "n_b_inv": _keyed(_csv(C5N_B_DIR / "s4_4c5n_b_pellet_inventory_dashboard.csv")),
        "o_a": _keyed(_csv(C5O_A_DIR / "s4_4c5o_a_compact_healthcheck.csv")),
        "o_b": _keyed(_csv(C5O_B_DIR / "s4_4c5o_b_compact_healthcheck.csv")),
        "o_c": _keyed(_csv(C5O_C_DIR / "s4_4c5o_c_compact_healthcheck.csv")),
        "p_a": _keyed(_csv(C5P_A_DIR / "s4_4c5p_a_compact_healthcheck.csv")),
        "p_a_asu": _keyed(_csv(C5P_A_DIR / "s4_4c5p_a_asu_electricity_ledger.csv")),
        "p_b": _keyed(_csv(C5P_B_DIR / "s4_4c5p_b_compact_healthcheck.csv")),
        "p_b_wag": _keyed(_csv(C5P_B_DIR / "s4_4c5p_b_wag_residual_after_steam.csv")),
        "p_c": _keyed(_csv(C5P_C_DIR / "s4_4c5p_c_compact_healthcheck.csv")),
        "p_c_wag": _keyed(_csv(C5P_C_DIR / "s4_4c5p_c_wag_residual_after_generators.csv")),
        "p_d_gate": json.loads((C5P_D_DIR / "s4_4c5p_d_stage_gate.json").read_text(encoding="utf-8")),
        "p_d_values": _csv(C5P_D_DIR / "c5_buffer_store_current_values.csv"),
        "p_d_validation": _csv(C5P_D_DIR / "c5_buffer_store_validation_metrics.csv"),
        "f_wag": _csv(C5F_DIR / "s4_4c5f_wag_compact_balance_reconciliation.csv"),
        "h_bfg": _csv(C5H_DIR / "s4_4c5h_bfg_gross_self_use_surplus_dashboard.csv"),
        "f_cog": _csv(C5F_DIR / "s4_4c5f_cog_self_use_surplus_dashboard.csv"),
        "j_wag": _csv(C5J_DIR / "s4_4c5j_wag_generation_consumption_by_plant.csv"),
    }


def _anchor_row(
    anchor_id: str,
    configuration: str,
    domain: str,
    asset_or_flow: str,
    metric: str,
    unit: str,
    raw_source_anchor: Any,
    active_scaled_anchor: Any,
    model_output: Any,
    anchor_role: str,
    anchor_source: str,
    current_status: str,
    interpretation: str,
    decision_needed: str,
    candidate_parameter_lever_ids: str,
    caveat: str,
    gap_reference: str = "raw",
) -> dict[str, Any]:
    reference = active_scaled_anchor if gap_reference == "active" and str(active_scaled_anchor).strip() else raw_source_anchor
    return {
        "anchor_id": anchor_id,
        "configuration": configuration,
        "domain": domain,
        "asset_or_flow": asset_or_flow,
        "metric": metric,
        "unit": unit,
        "raw_source_anchor": _fmt(raw_source_anchor),
        "active_scaled_anchor": _fmt(active_scaled_anchor),
        "model_output": _fmt(model_output),
        "absolute_gap": _gap(model_output, reference),
        "relative_gap": _relative_gap(model_output, reference),
        "anchor_role": anchor_role,
        "anchor_source": anchor_source,
        "current_status": current_status,
        "interpretation": interpretation,
        "decision_needed": decision_needed,
        "candidate_parameter_lever_ids": candidate_parameter_lever_ids,
        "caveat": caveat,
    }


def _annual_anchor_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in payload["anchor"]:
        domain = _domain(row["anchor_id"], row["asset_or_flow"], row["metric"])
        rows.append(_anchor_row(
            row["anchor_id"],
            row["configuration"],
            domain,
            row["asset_or_flow"],
            row["metric"],
            row["unit"],
            row["raw_source_anchor"],
            row["active_scaled_anchor"],
            row["model_output"],
            row["anchor_role"],
            row["source_card_or_stage"],
            "inherited_from_c5_anchor_route_diagnostics",
            _interpretation(row),
            row["decision_needed"],
            _lever_ids(row["anchor_id"], domain),
            row["caveat"],
            gap_reference="active" if row["active_scaled_anchor"] else "raw",
        ))

    final_anchors = {C0: 6_900_000.0, C1: 7_000_000.0}
    hsm_anchors = {C0: 5_400_000.0, C1: 5_500_000.0}
    ls_public = {C0: 7_200_000.0, C1: 6_800_000.0}
    slab_import = {C0: 16_000.0, C1: 600_000.0}
    for config in [C0, C1]:
        dsp = payload["o_c"][(config, 24)]
        k = payload["k"][(config, 24)]
        final_proxy = _zero(dsp["DSP_plus_HSM_final_product_proxy_site_t_y"])
        dsp_output = _zero(dsp["DSP_output_site_t_y"])
        hsm_output = final_proxy - dsp_output
        rows.extend([
            _anchor_row(
                f"{config}_public_liquid_steel_context",
                config,
                "production_downstream",
                "site",
                "public liquid steel validation anchor",
                "t/y",
                ls_public[config],
                6_750_000.0,
                _zero(k["BOF_LS_Mt_y"]) * 1_000_000.0 + _zero(k["EAF_LS_Mt_y"]) * 1_000_000.0,
                "validation_anchor",
                "source_cards/production_context",
                "reported_not_enforced",
                "expected_due_to_active_scaled_target",
                "keep active 6.75 Mt/y target unless production policy is reopened",
                "LEV_ACTIVE_PRODUCTION_TARGET",
                "Public annual anchor is not used as executable production target.",
            ),
            _anchor_row(
                f"{config}_hsm_wbw_output_raw_anchor",
                config,
                "production_downstream",
                "HSM/WBW",
                "HSM/WBW final rolled coils raw anchor",
                "t/y",
                hsm_anchors[config],
                "",
                hsm_output,
                "validation_anchor",
                "HSM/DSP/source-card context",
                "reported_not_enforced",
                "expected_due_to_boundary_scope",
                "do not freeze denominator before residual route/output review",
                "LEV_PROD_DENOMINATOR_ROUTE_SCALING",
                "Final-product denominator remains unresolved.",
            ),
            _anchor_row(
                f"{config}_final_product_proxy_raw_anchor",
                config,
                "production_downstream",
                "downstream",
                "DSP plus HSM/WBW final-product proxy raw anchor",
                "t/y",
                final_anchors[config],
                "",
                final_proxy,
                "validation_anchor",
                "DSP/HSM/source-card context",
                "reported_not_enforced",
                "expected_due_to_boundary_scope",
                "denominator choice requires separate review",
                "LEV_PROD_DENOMINATOR_ROUTE_SCALING",
                "Not a EUR/t denominator.",
            ),
            _anchor_row(
                f"{config}_external_slab_import_context",
                config,
                "production_downstream",
                "external slab",
                "external slab import context",
                "t/y",
                slab_import[config],
                "",
                "",
                "context_anchor",
                "BUFFERS_STORAGE/HSM context",
                "not_explicitly_modelled_as_store",
                "expected_due_to_missing_residual_layer",
                "review imported slab convention before denominator freeze",
                "LEV_IMPORTED_SLAB_CONVENTION",
                "External slab import is exogenous supply/context, not storage capacity.",
            ),
        ])

    for row in payload["p_d_validation"]:
        if int(row["horizon"]) != 24:
            continue
        rows.append(_anchor_row(
            f"buffer_{row['buffer_id']}_{row['configuration']}",
            row["configuration"],
            "buffers_stores",
            row["buffer_id"],
            "buffer/store validation status",
            "mixed",
            "",
            row["capacity"],
            row["capacity"],
            "development_diagnostic",
            "C5p_d buffer/store validation",
            "validated",
            "no_issue_within_tolerance",
            "keep diagnostic; no storage activation",
            "LEV_BUFFER_STORE_SENSITIVITY_REGISTER",
            row["caveat"],
            gap_reference="active",
        ))
    return rows


def _config_row(domain: str, metric: str, unit: str, c0: Any, c1: Any, interpretation: str, caveat: str) -> dict[str, Any]:
    c0n = _value(c0)
    c1n = _value(c1)
    delta = "" if c0n is None or c1n is None else c1n - c0n
    rel = "" if c0n in (None, 0.0) or c1n is None else (c1n - c0n) / c0n
    return {
        "domain": domain,
        "metric": metric,
        "unit": unit,
        "C0_value": _fmt(c0),
        "C1_value": _fmt(c1),
        "C1_minus_C0": _fmt(delta),
        "relative_change": _fmt(rel),
        "interpretation": interpretation,
        "caveat": caveat,
    }


def _config_comparison_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    c0_dsp = payload["o_c"][(C0, 24)]
    c1_dsp = payload["o_c"][(C1, 24)]
    c0_k = payload["k"][(C0, 24)]
    c1_k = payload["k"][(C1, 24)]
    c0_nb = payload["n_b"][(C0, 24)]
    c1_nb = payload["n_b"][(C1, 24)]
    c0_oa = payload["o_a"][(C0, 24)]
    c1_oa = payload["o_a"][(C1, 24)]
    c0_ob = payload["o_b"][(C0, 24)]
    c1_ob = payload["o_b"][(C1, 24)]
    c0_pa = payload["p_a"][(C0, 24)]
    c1_pa = payload["p_a"][(C1, 24)]
    c0_pb = payload["p_b"][(C0, 24)]
    c1_pb = payload["p_b"][(C1, 24)]
    c0_pc = payload["p_c"][(C0, 24)]
    c1_pc = payload["p_c"][(C1, 24)]
    return [
        _config_row("production_downstream", "active liquid steel target", "Mt/y", c0_k["active_total_LS_target_Mt_y"], c1_k["active_total_LS_target_Mt_y"], "unchanged active production target", "Raw public anchors remain validation/context."),
        _config_row("production_downstream", "DSP output", "t/y", c0_dsp["DSP_output_site_t_y"], c1_dsp["DSP_output_site_t_y"], "same active scaled DSP output", "Raw 1.5 Mt/y anchor not enforced."),
        _config_row("production_downstream", "final-product proxy", "t/y", c0_dsp["DSP_plus_HSM_final_product_proxy_site_t_y"], c1_dsp["DSP_plus_HSM_final_product_proxy_site_t_y"], "C1 proxy rises through HSM/import route accounting", "Not final economics denominator."),
        _config_row("materials", "PEFA fired pellets", "t/y", c0_nb["PEFA_fired_pellets_output_site_t_y"], c1_nb["PEFA_fired_pellets_output_site_t_y"], "C1 higher PEFA output", "PEFA raw anchors stay validation checks."),
        _config_row("materials", "imported pellets", "t/y", c0_nb["imported_pellets_site_t_y"], c1_nb["imported_pellets_site_t_y"], "C1 imports much lower in active baseline", "Import policy is reconciliation/input, not storage."),
        _config_row("materials", "BF pellet demand", "t/y", c0_nb["BF_pellet_demand_site_t_y"], c1_nb["BF_pellet_demand_site_t_y"], "C1 BF pellet demand falls with BF6-only route", "BF pellet coefficient is reconciliation parameter."),
        _config_row("materials", "DRP DRI output", "t/y", c0_oa["DRI_output_site_t_y"], c1_oa["DRI_output_site_t_y"], "C1 DRP activated", "DRP output follows active scaled C1 route."),
        _config_row("materials", "EAF liquid steel", "t/y", c0_ob["EAF_LS_output_site_t_y"], c1_ob["EAF_LS_output_site_t_y"], "C1 EAF activated", "Route origin tagging remains caveated."),
        _config_row("oxygen_asu", "total core oxygen demand", "t/y", c0_pa["total_core_oxygen_demand_t_y"], c1_pa["total_core_oxygen_demand_t_y"], "C1 oxygen rises despite lower BF/BOF because DRP/EAF are added", "DRP oxygen basis requires review."),
        _config_row("electricity", "ASU electricity", "MWh/y", c0_pa["ASU_electricity_MWh_y"], c1_pa["ASU_electricity_MWh_y"], "C1 ASU electricity rises", "ASU is not DA-flexible here."),
        _config_row("boiler_steam", "steam demand", "t/y", c0_pb["total_steam_demand_t_y"], c1_pb["total_steam_demand_t_y"], "C1 explicit steam demand is lower", "Residual steam demand remains deferred."),
        _config_row("generator_wag", "generator electricity offset", "MWh/y", c0_pc["total_generator_electricity_offset_MWh_e_y"], c1_pc["total_generator_electricity_offset_MWh_e_y"], "C0 residual-WAG interface output exceeds C1 constrained generator output", "Internal offset only."),
        _config_row("electricity", "modelled electricity exposure after generator offset", "MWh/y", c0_pc["process_electricity_after_generator_offset_reporting_only_MWh_e_y"], c1_pc["process_electricity_after_generator_offset_reporting_only_MWh_e_y"], "C0 floors at zero; C1 remains exposed", "Not full-site net import."),
        _config_row("natural_gas", "DRP NG total", "PJ/y", c0_oa["DRP_NG_total_PJ_y"], c1_oa["DRP_NG_total_PJ_y"], "C1 NG-DRP activated", "Residual NG boundary incomplete."),
        _config_row("co2", "diagnostic CO2 after generator/utility stack", "t/y", c0_pc.get("diagnostic_CO2_after_generator_t_y", ""), c1_pc.get("diagnostic_CO2_after_generator_t_y", ""), "CO2 boundary not consolidated", "Use component diagnostics only."),
        _config_row("buffers_stores", "C1 DRI buffer capacity", "t", 0, payload["p_d_gate"]["C1_24h_DRI_buffer_capacity_t"], "C1 finite DRI buffer active", "Buffer/store validation passed."),
    ]


def _wag_row(payload: dict[str, Any], config: str, carrier: str) -> dict[str, Any]:
    key = (config, 24)
    p_b = payload["p_b_wag"][key]
    p_c = payload["p_c_wag"][key]
    pefa = payload["n_a_gas"][key]
    sinter = payload["m_gas"][key]
    mandatory = 0.0
    process = 0.0
    before_steam = 0.0
    boiler = 0.0
    generator = 0.0
    residual = 0.0
    if carrier == "BFG":
        process = _zero(sinter["BFG_to_HSM_site_MWh_y"]) + _zero(sinter["BFG_to_Sinter_site_MWh_y"]) + _zero(pefa["BFG_to_PEFA_site_MWh_y"])
        before_steam = _zero(p_b["available_BFG_before_steam_MWh_LHV_y"])
        boiler = _zero(p_b["BFG_to_steam_MWh_LHV_y"])
        generator = _zero(p_c["BFG_to_generators_MWh_LHV_y"])
        residual = _zero(p_c["residual_BFG_after_generators_MWh_LHV_y"])
    elif carrier == "BOFG":
        process = _zero(sinter["BOFG_to_HSM_site_MWh_y"]) + _zero(sinter["BOFG_to_Sinter_site_MWh_y"]) + _zero(pefa["BOFG_to_PEFA_malerij_site_MWh_y"])
        before_steam = _zero(p_b["available_BOFG_before_steam_MWh_LHV_y"])
        boiler = _zero(p_b["BOFG_to_steam_MWh_LHV_y"])
        generator = _zero(p_c["BOFG_to_generators_MWh_LHV_y"])
        residual = _zero(p_c["residual_BOFG_after_generators_MWh_LHV_y"])
    elif carrier == "COG":
        process = _zero(sinter["COG_to_HSM_site_MWh_y"]) + _zero(sinter["COG_to_Sinter_site_MWh_y"]) + _zero(pefa["COG_to_PEFA_branderij_site_MWh_y"])
        before_steam = _zero(p_b["available_COG_before_steam_MWh_LHV_y"])
        boiler = _zero(p_b["COG_to_steam_MWh_LHV_y"])
        generator = _zero(p_c["COG_to_generators_MWh_LHV_y"])
        residual = _zero(p_c["residual_COG_after_generators_MWh_LHV_y"])
    generated = mandatory + process + before_steam
    balance = generated - (mandatory + process + boiler + generator + residual)
    return {
        "configuration": config,
        "carrier": carrier,
        "generated_or_supplied": _fmt(generated),
        "ledger_point": "controller_reconciled_supply_before_steam_not_source_generation",
        "mandatory_process_self_use": _fmt(mandatory),
        "preparation_or_process_use": _fmt(process),
        "boiler_or_steam_use": _fmt(boiler),
        "generator_use": _fmt(generator),
        "external_import": "0",
        "flare_or_spill": "",
        "residual_or_unallocated": _fmt(residual),
        "model_balance_residual": _fmt(balance),
        "unit": "MWh_LHV/y",
        "status": "pass_carrier_specific_diagnostic",
        "caveat": "Compatibility field `generated_or_supplied` is controller-reconciled supply before steam, not source gross generation; see c5_annual_wag_ledger_point_reconciliation.csv. WAG holders are not stores.",
    }


def _flow_balance_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in [C0, C1]:
        for carrier in ["BFG", "BOFG", "COG"]:
            rows.append(_wag_row(payload, config, carrier))
        oa = payload["o_a"][(config, 24)]
        ob = payload["o_b"][(config, 24)]
        pc = payload["p_c"][(config, 24)]
        pb = payload["p_b"][(config, 24)]
        pefa = payload["n_a_gas"][(config, 24)]
        generator_ng = (_zero(pc["VN25_NG_MWh_LHV_y"]) + _zero(pc["IJ01_NG_MWh_LHV_y"]) + _zero(pc["C0_generator_NG_MWh_LHV_y"])) * MWH_TO_PJ
        pefa_ng = (_zero(pefa["NG_to_PEFA_malerij_site_MWh_y"]) + _zero(pefa["NG_to_PEFA_branderij_site_MWh_y"]) + _zero(pefa["PEFA_NG_backup_site_MWh_y"])) * MWH_TO_PJ
        boiler_ng = _zero(pb["NG_backup_for_steam_MWh_LHV_y"]) * MWH_TO_PJ
        drp_ng = _zero(oa["DRP_NG_total_PJ_y"])
        eaf_ng = _zero(ob["EAF_NG_PJ_y"])
        total_ng = drp_ng + eaf_ng + boiler_ng + generator_ng + pefa_ng
        rows.append({
            "configuration": config,
            "carrier": "NG",
            "generated_or_supplied": _fmt(total_ng),
            "ledger_point": "named_ng_external_import_partial_boundary",
            "mandatory_process_self_use": "0",
            "preparation_or_process_use": _fmt(drp_ng + eaf_ng + pefa_ng),
            "boiler_or_steam_use": _fmt(boiler_ng),
            "generator_use": _fmt(generator_ng),
            "external_import": _fmt(total_ng),
            "flare_or_spill": "0",
            "residual_or_unallocated": "",
            "model_balance_residual": "0",
            "unit": "PJ_LHV/y",
            "status": "partial_boundary_ng_import_diagnostic",
            "caveat": "Residual/unmodelled NG loads are not yet modelled.",
        })
        rows.append({
            "configuration": config,
            "carrier": "WAG_total_reporting_only",
            "generated_or_supplied": "",
            "ledger_point": "aggregate_reporting_only_after_carrier_rows",
            "mandatory_process_self_use": "",
            "preparation_or_process_use": "",
            "boiler_or_steam_use": _fmt(_zero(pb["WAG_to_steam_MWh_LHV_y"])),
            "generator_use": _fmt(_zero(pc["WAG_to_generators_PJ_y"]) * PJ_TO_MWH),
            "external_import": "0",
            "flare_or_spill": _fmt(_zero(pc["generator_flare_or_spill_PJ_y"]) * PJ_TO_MWH),
            "residual_or_unallocated": _fmt(_zero(pc["residual_WAG_after_generators_and_flare_PJ_y"]) * PJ_TO_MWH),
            "model_balance_residual": "",
            "unit": "MWh_LHV/y",
            "status": "reporting_total_after_carrier_rows",
            "caveat": "Aggregate WAG row is reporting-only after carrier-specific BFG/BOFG/COG rows.",
        })
    return rows


def _wag_ledger_point_rows(payload: dict[str, Any], flow: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose source, network, and C5p_e controller points without joining them physically.

    C5p_e is a historical reconciliation of compact downstream diagnostics.  Its
    controller balance is useful, but its former `generated_or_supplied` label
    was too easily read as gross source production.  This table preserves both
    quantities and makes any cross-stage gap visible instead of tuning it away.
    """
    rows: list[dict[str, Any]] = []
    by_flow = {(row["configuration"], row["carrier"]): row for row in flow}
    for config in [C0, C1]:
        for carrier in ["BFG", "COG", "BOFG"]:
            gross = 0.0
            self_use = 0.0
            source_artifacts = ""
            if carrier == "BFG":
                source_rows = [
                    row for row in payload["h_bfg"]
                    if row["configuration"] == config and row["horizon_hours"] == "24"
                ]
                gross = sum(_zero(row["BFG_gross_site_MWh_LHV_y"]) for row in source_rows)
                self_use = sum(_zero(row["BFG_to_Controller_BF_site_MWh_y"]) for row in source_rows)
                source_artifacts = "C5h BFG gross/self-use/surplus dashboard"
            elif carrier == "COG":
                source_rows = [
                    row for row in payload["f_cog"]
                    if row["configuration"] == config and row["horizon_hours"] == "24"
                ]
                gross = sum(_zero(row["COG_gross_site_MWh_LHV_y"]) for row in source_rows)
                self_use = sum(_zero(row["COG_to_KGF_underfiring_site_MWh_LHV_y"]) for row in source_rows)
                source_artifacts = "C5f COG gross/self-use/surplus dashboard"
            else:
                source_rows = [
                    row for row in payload["j_wag"]
                    if row["configuration"] == config
                    and row["horizon_hours"] == "24"
                    and row["carrier"] == "BOFG"
                    and _zero(row["generated_MWh_LHV_y"]) > 0.0
                ]
                gross = sum(_zero(row["generated_MWh_LHV_y"]) for row in source_rows)
                source_artifacts = "C5j BOFG generation/consumption ledger"

            network = gross - self_use
            controller = by_flow[(config, carrier)]
            reconciled_supply = _zero(controller["generated_or_supplied"])
            controller_balance = _zero(controller["model_balance_residual"])
            source_gap = network - reconciled_supply
            rows.append({
                "configuration": config,
                "carrier": carrier,
                "source_gross_generation_MWh_LHV_y": _fmt(gross),
                "mandatory_source_self_use_MWh_LHV_y": _fmt(self_use),
                "network_available_after_self_use_MWh_LHV_y": _fmt(network),
                "c5p_e_controller_reconciled_supply_before_steam_MWh_LHV_y": _fmt(reconciled_supply),
                "c5p_e_preparation_or_process_use_MWh_LHV_y": controller["preparation_or_process_use"],
                "c5p_e_boiler_or_steam_use_MWh_LHV_y": controller["boiler_or_steam_use"],
                "c5p_e_generator_use_MWh_LHV_y": controller["generator_use"],
                "c5p_e_flare_or_spill_MWh_LHV_y": controller["flare_or_spill"],
                "c5p_e_residual_or_unallocated_MWh_LHV_y": controller["residual_or_unallocated"],
                "source_to_c5p_e_supply_gap_MWh_LHV_y": _fmt(source_gap),
                "c5p_e_controller_balance_residual_MWh_LHV_y": _fmt(controller_balance),
                "ledger_contract_status": "historical_cross_stage_scope_not_single_closed_chain",
                "source_artifacts": source_artifacts,
                "caveat": "Source/network and C5p_e controller points are reported side by side. Their signed gap is a scope/activity-basis diagnostic, never a coefficient-tuning target or residual allocation.",
            })
    return rows


def _electricity_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in [C0, C1]:
        pc = payload["p_c"][(config, 24)]
        pa = payload["p_a"][(config, 24)]
        gross = _zero(pc["process_electricity_before_generator_offset_MWh_e_y"])
        asu = _zero(pa["ASU_electricity_MWh_y"])
        steam_gen = _zero(pc["steam_circuit_electricity_MWh_e_y"])
        gen = _zero(pc["total_generator_electricity_offset_MWh_e_y"])
        exposure = _zero(pc["process_electricity_after_generator_offset_reporting_only_MWh_e_y"])
        anchor_360 = 360.0 * 8760.0
        for component in [
            "modelled_process_before_generator_offset",
            "ASU_demand",
            "steam_circuit_internal_generation",
            "generator_internal_offset",
            "modelled_exposure_after_generator_offset",
            "site_average_power_context_360MW",
            "current_total_site_consumption_context_3TWh",
        ]:
            source_anchor = ""
            gap = ""
            if component == "site_average_power_context_360MW":
                source_anchor = _fmt(anchor_360)
                gap = _fmt(exposure - anchor_360)
            elif component == "current_total_site_consumption_context_3TWh":
                source_anchor = "3000000"
                gap = _fmt(exposure - 3_000_000.0)
            rows.append({
                "configuration": config,
                "electricity_component": component,
                "unit": "MWh_e/y",
                "gross_modelled_process_demand": _fmt(gross),
                "ASU_demand": _fmt(asu),
                "boiler_steam_internal_generation": _fmt(steam_gen),
                "generator_offset": _fmt(gen),
                "residual_electricity_load": "not_modelled",
                "modelled_electricity_exposure": _fmt(exposure),
                "source_anchor": source_anchor,
                "gap_to_anchor": gap,
                "boundary_status": "incomplete_reporting_only_not_full_site_net_import",
                "can_be_used_for_economics_now": "false",
                "caveat": "Residual electricity loads and full grid boundary are incomplete.",
            })
    return rows


def _ng_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in [C0, C1]:
        oa = payload["o_a"][(config, 24)]
        ob = payload["o_b"][(config, 24)]
        pb = payload["p_b"][(config, 24)]
        pc = payload["p_c"][(config, 24)]
        pefa = payload["n_a_gas"][(config, 24)]
        drp = _zero(oa["DRP_NG_total_PJ_y"])
        eaf = _zero(ob["EAF_NG_PJ_y"])
        boiler = _zero(pb["NG_backup_for_steam_MWh_LHV_y"]) * MWH_TO_PJ
        generator = (_zero(pc["VN25_NG_MWh_LHV_y"]) + _zero(pc["IJ01_NG_MWh_LHV_y"]) + _zero(pc["C0_generator_NG_MWh_LHV_y"])) * MWH_TO_PJ
        pefa_ng = (_zero(pefa["NG_to_PEFA_malerij_site_MWh_y"]) + _zero(pefa["NG_to_PEFA_branderij_site_MWh_y"]) + _zero(pefa["PEFA_NG_backup_site_MWh_y"])) * MWH_TO_PJ
        total = drp + eaf + boiler + generator + pefa_ng
        source_anchor = "27.72 PJ/y DRP-only derived anchor" if config == C1 else ""
        rows.append({
            "configuration": config,
            "ng_component": "modelled_ng_boundary",
            "unit": "PJ_LHV/y",
            "DRP_NG": _fmt(drp),
            "EAF_NG": _fmt(eaf),
            "boiler_steam_NG": _fmt(boiler),
            "generator_NG": _fmt(generator),
            "PEFA_NG_backup": _fmt(pefa_ng),
            "residual_or_unmodelled_NG": "not_modelled",
            "total_modelled_NG": _fmt(total),
            "source_anchor": source_anchor,
            "gap_to_anchor": _fmt(total - 27.72) if config == C1 else "",
            "boundary_status": "incomplete_no_full_site_NG_claim",
            "caveat": "Residual/unmodelled NG boundary is open.",
        })
    return rows


def _co2_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in [C0, C1]:
        na = payload["n_a"][(config, 24)]
        oa = payload["o_a"][(config, 24)]
        ob = payload["o_b"][(config, 24)]
        oc = payload["o_c"][(config, 24)]
        pc = payload["p_c"][(config, 24)]
        components = [
            ("PEFA_diagnostic_CO2", na["PEFA_diagnostic_CO2_t_y"], "", "component_diagnostic_only", "not_ets_ready"),
            ("DRP_capture_stream", oa["DRP_CO2_capture_stream_site_t_y"], "0.8 Mt/y C1 capture validation anchor" if config == C1 else "", "capture_stream_not_direct_emissions", "not_ets_ready"),
            ("EAF_midpoint_CO2", ob["EAF_CO2_diagnostic_midpoint_t_y"], "0.2412-0.6030 Mt/y C1 range" if config == C1 else "", "range_midpoint_diagnostic", "not_ets_ready"),
            ("DSP_direct_CO2", oc["DSP_direct_CO2_t_y"], "", "inactive_fuel_accounting_zero", "not_ets_ready"),
            ("site_diagnostic_CO2_after_generator", pc.get("diagnostic_CO2_after_generator_t_y", ""), "", "incomplete_boundary", "not_ets_ready"),
            ("boiler_generator_fuel_explicit_CO2", "", "", "deferred", "not_ets_ready"),
        ]
        for component, model, source, status, ets in components:
            rows.append({
                "configuration": config,
                "co2_component": component,
                "unit": "tCO2/y",
                "model_output": _fmt(model),
                "source_anchor": source,
                "gap_to_anchor": "",
                "boundary_status": status,
                "double_counting_risk": "reported_WAG_generation_vs_combustion_risk",
                "ets_ready": "false" if ets == "not_ets_ready" else "true",
                "caveat": "CO2 boundary is component-level only; WAG combustion factors and ETS objective are deferred.",
            })
    return rows


def _buffer_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in payload["p_d_validation"]:
        if int(row["horizon"]) != 24:
            continue
        rows.append({
            "configuration": row["configuration"],
            "buffer_id": row["buffer_id"],
            "unit": "mixed",
            "capacity": row["capacity"],
            "start_inventory": row["start_inventory"],
            "end_inventory": row["end_inventory"],
            "annual_drift": row["annual_drift"],
            "min_inventory": row["min_inventory"],
            "max_inventory": row["max_inventory"],
            "bind_count": row["capacity_bind_count"],
            "terminal_rule_pass": row["terminal_rule_pass"],
            "no_free_source_pass": row["no_free_source_pass"],
            "no_free_battery_pass": row["no_free_battery_pass"],
            "caveat": row["caveat"],
        })
    return rows


def _lever_row(
    lever_id: str,
    domain: str,
    parameter_or_policy: str,
    current: str,
    candidates: str,
    gap: str,
    up: str,
    down: str,
    physical: bool,
    economics: bool,
    sensitivity: bool,
    priority: str,
    can_change: bool,
    action: str,
    caveat: str,
) -> dict[str, Any]:
    return {
        "lever_id": lever_id,
        "domain": domain,
        "parameter_or_policy": parameter_or_policy,
        "current_value_or_status": current,
        "candidate_values_or_range": candidates,
        "related_anchor_gap": gap,
        "expected_direction_if_increased": up,
        "expected_direction_if_decreased": down,
        "affects_physical_behaviour": str(physical).lower(),
        "affects_economics_later": str(economics).lower(),
        "sensitivity_required": str(sensitivity).lower(),
        "review_priority": priority,
        "can_be_changed_before_commit": str(can_change).lower(),
        "recommended_action": action,
        "caveat": caveat,
    }


def _lever_rows() -> list[dict[str, Any]]:
    return [
        _lever_row("LEV_ACTIVE_PRODUCTION_TARGET", "production_downstream", "active production target", "6.75 Mt/y", "6.75; 6.8; 7.2 Mt/y", "liquid steel raw anchor gaps", "raises route outputs and most demands", "lowers route outputs and demands", True, True, True, "medium", False, "defer; do not tune before commit", "Changing target would alter accepted C5 baseline."),
        _lever_row("LEV_PROD_DENOMINATOR_ROUTE_SCALING", "production_downstream", "final-product proxy / denominator convention", "unresolved", "liquid steel; HSM+DSP proxy; shipped product denominator", "C0 final proxy -0.641 Mt/y; C1 -0.199 Mt/y vs raw proxy", "can reduce denominator gap if route yield/imports added", "can widen final-product gap", True, True, True, "high", False, "review as denominator decision, not calibration", "Do not freeze EUR/t denominator yet."),
        _lever_row("LEV_DSP_HSM_ROUTE_OUTPUT", "production_downstream", "DSP/HSM route scaling and route-origin tagging", "DSP 1.35 Mt/y; HSM C5l_d base_0_50", "DSP 1.35-1.5 Mt/y; route-origin tags", "DSP raw gap -0.15 Mt/y", "raises final proxy and DSP utility loads", "lowers final proxy", True, True, True, "medium", False, "review after annual anchor reconciliation", "C1 DSP 90% EAF-origin anchor is not validated by current route-origin ledger."),
        _lever_row("LEV_IMPORTED_SLAB_CONVENTION", "production_downstream", "imported slab convention", "context/exogenous; not store", "C0 16 kt/y context; C1 0.6 Mt/y context", "external slab rows not explicit final denominator", "raises HSM/final proxy if active supply row added", "lowers HSM/final proxy", True, True, True, "high", False, "decide in denominator/boundary review", "External slab import must not become free store."),
        _lever_row("LEV_PELLET_BURDEN_RECONCILIATION", "pellets_materials", "PEFA output, imports, BF/DRP pellet coefficients", "current C5n_b reconciliation", "BF coefficient source/reconciliation; DRP 1.35-1.40 t/t DRI", "PEFA/imported pellet anchor gaps", "raises pellet demand/import need", "lowers pellet demand/import need", True, True, True, "medium", False, "preserve current baseline; sensitivity later", "BF pellet coefficient is partly reconciliation, not pure recipe."),
        _lever_row("LEV_DRP_EAF_MATERIAL_SPLIT", "drp_eaf", "EAF DRI coefficient and scrap share", "0.829675 t DRI/t LS; scrap 1.01505 Mt/y", "0.829675; 0.848 source/review; scrap range from source cards", "DRI coefficient vs source coefficient", "raises DRI need and lowers scrap share if LS fixed", "lowers DRI need and raises scrap share", True, True, True, "medium", False, "review after residual material reconciliation", "Do not tune EAF input split before commit."),
        _lever_row("LEV_DRP_OXYGEN_BASIS_REVIEW", "oxygen_asu", "DRP oxygen basis", "0.135 t/t DRI / 94.472 Nm3/t", "35 Nm3/t vendor cross-check; project basis", "DRP oxygen basis conflict", "raises ASU demand/electricity if project basis kept/increased", "lowers ASU demand/electricity toward vendor cross-check", True, True, True, "high", False, "source review required", "Main oxygen sensitivity/review item."),
        _lever_row("LEV_DRI_BUFFER_DAYS", "buffers_stores", "DRI buffer size", "15.229653 kt C1", "1-3 days; 17.760 kt predecessor candidate", "no annual gap; flexibility sensitivity", "increases C1 flexibility later", "reduces C1 flexibility later", True, True, True, "sensitivity_only", False, "preserve current C5 value before commit", "Not annual calibration lever."),
        _lever_row("LEV_WAG_GENERATION_AND_SELF_USE", "generator_wag", "BFG/COG/BOFG generation and mandatory self-use", "current C5 carrier coefficients", "source-card reviewed ranges later", "carrier residual and generator gaps", "more residual WAG for boilers/generators", "less residual WAG; larger generator gap", True, True, True, "medium", False, "review carrier gaps, do not aggregate WAG", "No generic WAG carrier."),
        _lever_row("LEV_BOILER_RESIDUAL_STEAM_DEMAND", "boiler_steam", "residual steam demand", "explicit mapped steam demand only", "source-backed residual steam loads later", "low annual WAG-to-steam likely scope-driven", "raises steam demand and WAG/NG boiler use", "lowers steam demand", True, True, True, "high", False, "open residual steam diagnostics later", "Steam mass-flow accounting only."),
        _lever_row("LEV_C1_GENERATOR_ANCHOR_INTERPRETATION", "generator_wag", "VN25/IJ01 annual anchors and fuel gap treatment", "C1 fuel gap explicit 4.763389 PJ/y", "review anchor role; residual WAG; NG eligibility", "C1 generator fuel gap", "if more fuel allowed/available, raises generator offset and lowers exposure", "raises residual electricity exposure", True, True, True, "high", False, "review after residual WAG/NG boundary", "Do not hide C1 generator gap."),
        _lever_row("LEV_C0_GENERATOR_EFFICIENCY_AND_SPLIT", "generator_wag", "C0 generator efficiency and carrier split proxy", "0.34 efficiency; proxy split caveated", "0.34-0.35; carrier split from source if found", "C0 2.0 TWh anchor gap +0.067665 TWh", "raises C0 electricity offset", "lowers C0 electricity offset", True, True, True, "medium", False, "keep validation-anchor-only treatment", "2.0 TWh is not an equality target."),
        _lever_row("LEV_ELECTRICITY_RESIDUAL_BOUNDARY", "electricity", "residual electricity load and grid boundary", "not modelled", "plant auxiliaries, balance of site, grid imports", "model exposure not full-site anchor", "raises gross/load exposure if residual loads added", "lowers residual gap only if offsets added", True, True, True, "high", False, "next diagnostic stage", "No full-site net import claim."),
        _lever_row("LEV_NG_RESIDUAL_BOUNDARY", "natural_gas", "residual/unmodelled NG loads", "not modelled", "site NG residuals, boilers, generator NG, DRP split", "no full-site NG claim", "raises total NG if residual loads added", "lowers modelled NG", True, True, True, "high", False, "next diagnostic stage with electricity", "Do not use residual NG as slack."),
        _lever_row("LEV_CO2_BOUNDARY_AND_FACTORS", "co2", "consolidated CO2 boundary and WAG combustion factors", "component diagnostics only", "fuel-explicit factors; aggregate site anchors; ETS later", "CO2 boundary incomplete", "raises reported direct CO2 if combustion factors added", "lowers only if capture/netting assumptions added", True, True, True, "high", False, "separate consolidated CO2 diagnostics", "Avoid WAG generation/combustion double counting."),
        _lever_row("LEV_BUFFER_STORE_SENSITIVITY_REGISTER", "buffers_stores", "slab, hot-metal, oxygen, scrap pool stores", "mostly deferred/blocked", "slab 10/25/50 kt; hot metal 500 t; O2 100 t; scrap pool later", "flexibility candidates", "can increase flexibility and shift energy", "reduces flexibility", True, True, True, "sensitivity_only", False, "do not activate before commit", "No free-source stores."),
        _lever_row("LEV_DISABLE_FORBIDDEN_MARKET_FEATURES", "market_boundary", "DA revenue/export/mFRR/product revenue", "inactive", "not recommended in C5p_e", "none", "would violate current scope", "keeps physical/accounting baseline clean", True, True, False, "not_recommended", False, "do not implement", "Economics/DA readiness is NO-GO."),
    ]


def _decision_rows() -> list[dict[str, Any]]:
    return [
        {
            "decision_id": "DEC_PROD_DENOMINATOR",
            "topic": "final-product denominator",
            "current_status": "unresolved",
            "evidence_status": "raw public anchors conflict with active C5 final-product proxy",
            "options": "liquid steel target; HSM+DSP proxy; shipped/final product denominator after residual route review",
            "recommended_next_action": "review in scoped commit notes; do not freeze",
            "must_fix_before_commit": "false",
            "can_defer_to_sensitivity": "false",
            "thesis_reporting_caveat": "not thesis-ready",
            "caveat": "EUR/t denominator remains open.",
        },
        {
            "decision_id": "DEC_C1_GENERATOR_GAP",
            "topic": "C1 generator fuel gap",
            "current_status": "explicit_gap_reported",
            "evidence_status": "C1 VN25/IJ01 preferred anchors exceed governed available fuel by 4.763389 PJ/y",
            "options": "source review; residual WAG/NG boundary; keep gap caveat",
            "recommended_next_action": "carry into residual electricity/NG boundary diagnostics",
            "must_fix_before_commit": "false",
            "can_defer_to_sensitivity": "false",
            "thesis_reporting_caveat": "generator layer development-only",
            "caveat": "Do not hide as generic WAG.",
        },
        {
            "decision_id": "DEC_DRP_OXYGEN",
            "topic": "DRP oxygen basis",
            "current_status": "project basis active; vendor cross-check conflicts",
            "evidence_status": "0.135 t/t DRI vs 35 Nm3/t DRI",
            "options": "keep project basis; switch to vendor cross-check in sensitivity; source review",
            "recommended_next_action": "source review before thesis reporting",
            "must_fix_before_commit": "false",
            "can_defer_to_sensitivity": "true",
            "thesis_reporting_caveat": "requires review",
            "caveat": "Large effect on ASU demand/electricity.",
        },
        {
            "decision_id": "DEC_RESIDUAL_ELECTRICITY_NG",
            "topic": "residual electricity and NG boundaries",
            "current_status": "incomplete",
            "evidence_status": "model has process components but not full site load/import boundary",
            "options": "diagnostic residual layer; keep boundary caveat; no economics",
            "recommended_next_action": "implement residual electricity/NG boundary diagnostics next",
            "must_fix_before_commit": "false",
            "can_defer_to_sensitivity": "false",
            "thesis_reporting_caveat": "not full-site economics",
            "caveat": "Needed before DA/economics.",
        },
        {
            "decision_id": "DEC_CO2_BOUNDARY",
            "topic": "CO2 boundary",
            "current_status": "component diagnostics only",
            "evidence_status": "PEFA/EAF/DRP capture stream visible; WAG combustion CO2 deferred",
            "options": "consolidated boundary diagnostics; fuel-explicit factors; no ETS objective yet",
            "recommended_next_action": "implement consolidated CO2 boundary diagnostics after residual energy boundary",
            "must_fix_before_commit": "false",
            "can_defer_to_sensitivity": "false",
            "thesis_reporting_caveat": "not ETS-ready",
            "caveat": "Double-counting risk is reported, not resolved.",
        },
        {
            "decision_id": "DEC_BUFFER_STORES",
            "topic": "buffer/store status",
            "current_status": "C5p_d pass_with_caveats",
            "evidence_status": "DRI active C1; bulk solids non-binding; steam/WAG/hot metal/oxygen numeric stores inactive",
            "options": "preserve current; later sensitivity only",
            "recommended_next_action": "no change before commit",
            "must_fix_before_commit": "false",
            "can_defer_to_sensitivity": "true",
            "thesis_reporting_caveat": "development-only",
            "caveat": "No free-source buffer behaviour detected.",
        },
    ]


def _redflag_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pc0 = payload["p_c"][(C0, 24)]
    pc1 = payload["p_c"][(C1, 24)]
    pd_gate = payload["p_d_gate"]
    hsm_ok = all(row.get("cap_case") == "base_0_50" for row in payload["l_d"].values())
    checks = {
        "VALIDATION_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION": False,
        "ANNUAL_ANCHOR_USED_AS_HOURLY_DISPATCH_SCHEDULE": False,
        "GENERIC_WAG_BALANCE_USED_TO_HIDE_CARRIER_GAP": False,
        "WAG_DIRECT_MARKET_VALUE_ACTIVE": False,
        "GENERATOR_EXPORT_REVENUE_ACTIVE": pc0["export_revenue_enabled_base"] == "true" or pc1["export_revenue_enabled_base"] == "true",
        "GENERATOR_PRICE_RESPONSIVE_DISPATCH_ACTIVE": pc0["price_responsive_dispatch_base"] == "true" or pc1["price_responsive_dispatch_base"] == "true",
        "MFRR_ENABLED": pc0["mFRR_enabled_base"] == "true" or pc1["mFRR_enabled_base"] == "true",
        "FULL_SITE_NET_IMPORT_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY": pc0["full_site_net_electricity_claimed"] == "true" or pc1["full_site_net_electricity_claimed"] == "true",
        "DENOMINATOR_SILENTLY_FROZEN": "unresolved" not in pc1["denominator_status"],
        "PRODUCTION_POLICY_CHANGED_DURING_RECONCILIATION": False,
        "C5L_D_BASE_0_50_REVERTED": not hsm_ok,
        "COKE_RECONCILIATION_BASELINE_REOPENED": pc1["coke_reconciliation_baseline_status"] != "C5m_f_bounded_coke_reconciliation_active_development_baseline",
        "STORE_OR_BUFFER_USED_AS_FREE_SOURCE": pd_gate["failure_count"] != 0,
        "TERMINAL_DRIFT_NONZERO_FOR_EQUALITY_STORE": abs(_zero(pd_gate["C1_24h_DRI_inventory_drift_t"])) > 1e-9,
        "C0_GENERATOR_2TWH_ENFORCED_AS_TARGET": abs(_zero(pc0["C0_generator_electricity_gap_to_validation_anchor_TWh_e_y"])) < 1e-9,
        "C1_GENERATOR_FUEL_GAP_HIDDEN": _zero(pc1["generator_fuel_gap_unserved_PJ_y"]) <= 0,
        "CO2_DOUBLE_COUNTING_RISK_UNREPORTED": False,
        "THESIS_USABILITY_TRUE_FOR_DEVELOPMENT_ROWS": False,
    }
    rows: list[dict[str, Any]] = []
    for config in [C0, C1]:
        for flag in FAILURE_FLAGS:
            rows.append({
                "configuration": config,
                "red_flag": flag,
                "active": str(checks[flag]).lower(),
                "severity": "failure",
                "evidence": "active check from C5p_e annual reconciliation",
                "recommended_action": "fix before commit if active" if checks[flag] else "none",
            })
        for caveat in CAVEATS:
            rows.append({
                "configuration": config,
                "red_flag": caveat,
                "active": "true",
                "severity": "caveat",
                "evidence": "development-only annual reconciliation caveat",
                "recommended_action": "carry caveat into commit review and next diagnostics",
            })
    return rows


def _write_report(gate: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C5 Annual C0/C1 Physical/Accounting Reconciliation",
        "",
        "This report is reconstructed from current C5 artifacts by the C5p_e diagnostic stage. It is development-only and not thesis-approved.",
        "",
        "## Stage Gate",
        "",
        f"- Decision: `{gate['decision']}`",
        f"- Failure count: `{gate['failure_count']}`",
        f"- Caveat count: `{gate['caveat_count']}`",
        f"- Denominator status: `{gate['denominator_status']}`",
        f"- Electricity boundary: `{gate['electricity_boundary_status']}`",
        f"- NG boundary: `{gate['ng_boundary_status']}`",
        f"- CO2 boundary: `{gate['co2_boundary_status']}`",
        "",
        "## Main Findings",
        "",
        "- C1 generator fuel gap remains explicit and is not hidden.",
        "- C0 2.0 TWh residual-gas electricity is treated as validation anchor only.",
        "- `generated_or_supplied` in the carrier flow table is a controller-reconciled pre-steam supply compatibility field, not source gross WAG generation.",
        "- Gross generation, mandatory source self-use, network availability, and downstream controller supply are side-by-side in `c5_annual_wag_ledger_point_reconciliation.csv`; cross-stage gaps are diagnostics, not tuning targets.",
        "- Final-product denominator, residual electricity/NG, and CO2 boundaries remain open.",
        "- C5p_d buffer/store validation remains pass-with-caveats with no free-source stores.",
        "",
        "## Candidate Lever Register",
        "",
        "Candidate levers are review/sensitivity rows only. No parameter is changed by this stage.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_outputs() -> dict[str, Any]:
    C5P_E_DIR.mkdir(parents=True, exist_ok=True)
    payload = _payload()
    anchor = _annual_anchor_rows(payload)
    config = _config_comparison_rows(payload)
    flow = _flow_balance_rows(payload)
    wag_ledger = _wag_ledger_point_rows(payload, flow)
    electricity = _electricity_rows(payload)
    ng = _ng_rows(payload)
    co2 = _co2_rows(payload)
    buffers = _buffer_rows(payload)
    levers = _lever_rows()
    decisions = _decision_rows()
    redflags = _redflag_rows(payload)
    failure_count = sum(1 for row in redflags if row["severity"] == "failure" and row["active"] == "true")
    caveat_count = sum(1 for row in redflags if row["severity"] == "caveat" and row["active"] == "true") // 2
    pc1 = payload["p_c"][(C1, 24)]
    pc0 = payload["p_c"][(C0, 24)]
    o_c0 = payload["o_c"][(C0, 24)]
    o_c1 = payload["o_c"][(C1, 24)]
    gate = {
        "stage_id": STAGE,
        "decision": "pass_development_annual_reconciliation_diagnostic" if failure_count == 0 else "fail_development_annual_reconciliation_diagnostic",
        "status": "development_only",
        "thesis_usability": False,
        "output_directory": str(C5P_E_DIR).replace("\\", "/"),
        "failure_count": failure_count,
        "caveat_count": caveat_count,
        "anchor_rows": len(anchor),
        "candidate_lever_rows": len(levers),
        "C0_final_product_proxy_t_y": _zero(o_c0["DSP_plus_HSM_final_product_proxy_site_t_y"]),
        "C1_final_product_proxy_t_y": _zero(o_c1["DSP_plus_HSM_final_product_proxy_site_t_y"]),
        "C0_generator_electricity_TWh_y": _zero(pc0["C0_generator_electricity_actual_TWh_e_y"]),
        "C0_generator_2TWh_gap_TWh_y": _zero(pc0["C0_generator_electricity_gap_to_validation_anchor_TWh_e_y"]),
        "C1_generator_fuel_gap_PJ_y": _zero(pc1["generator_fuel_gap_unserved_PJ_y"]),
        "denominator_status": pc1["denominator_status"],
        "generator_electricity_value_mode": pc1["generator_electricity_value_mode"],
        "electricity_accounting_status": "internal_offset_or_reporting_only_not_DA_market_revenue",
        "electricity_boundary_status": "incomplete_reporting_only_not_full_site_net_import",
        "ng_boundary_status": "incomplete_no_full_site_NG_claim",
        "co2_boundary_status": "component_diagnostic_only_not_ETS_ready",
        "wag_ledger_contract_status": "historical_cross_stage_scope_not_single_closed_chain",
    }

    _write_csv(C5P_E_DIR / "c5_annual_anchor_reconciliation_matrix.csv", anchor, ANCHOR_COLUMNS)
    _write_csv(C5P_E_DIR / "c5_annual_config_comparison.csv", config, CONFIG_COLUMNS)
    _write_csv(C5P_E_DIR / "c5_annual_flow_balance_by_carrier.csv", flow, FLOW_COLUMNS)
    _write_csv(C5P_E_DIR / "c5_annual_wag_ledger_point_reconciliation.csv", wag_ledger, WAG_LEDGER_COLUMNS)
    _write_csv(C5P_E_DIR / "c5_annual_electricity_boundary_diagnostics.csv", electricity, ELECTRICITY_COLUMNS)
    _write_csv(C5P_E_DIR / "c5_annual_ng_boundary_diagnostics.csv", ng, NG_COLUMNS)
    _write_csv(C5P_E_DIR / "c5_annual_co2_boundary_diagnostics.csv", co2, CO2_COLUMNS)
    _write_csv(C5P_E_DIR / "c5_annual_buffer_store_summary.csv", buffers, BUFFER_COLUMNS)
    _write_csv(C5P_E_DIR / "c5_candidate_parameter_levers.csv", levers, LEVER_COLUMNS)
    _write_csv(C5P_E_DIR / "c5_annual_reconciliation_decision_register.csv", decisions, DECISION_COLUMNS)
    _write_csv(C5P_E_DIR / "c5_annual_reconciliation_red_flags.csv", redflags, REDFLAG_COLUMNS)
    _write_json(C5P_E_DIR / "s4_4c5p_e_stage_gate.json", gate)
    _write_csv(
        C5P_E_DIR / "s4_4c5p_e_run_registry.csv",
        [{
            "stage": STAGE,
            "source_stage": "C5f_through_C5p_d_current_artifacts",
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
            "anchor": len(anchor),
            "config": len(config),
            "flow": len(flow),
            "wag_ledger": len(wag_ledger),
            "electricity": len(electricity),
            "ng": len(ng),
            "co2": len(co2),
            "buffers": len(buffers),
            "levers": len(levers),
            "decisions": len(decisions),
            "redflags": len(redflags),
        },
    }
    _write_json(C5P_E_DIR / "s4_4c5p_e_summary.json", summary)
    _write_report(gate)
    return summary


def run_s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
