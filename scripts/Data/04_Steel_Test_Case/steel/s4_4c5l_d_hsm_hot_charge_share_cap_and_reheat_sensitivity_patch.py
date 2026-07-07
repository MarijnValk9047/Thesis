"""S4.4c5l_d HSM hot-charge share cap and reheat sensitivity patch.

This development-only diagnostic layer keeps the C5l_c slab-age accounting as
the uncapped reference, then applies deterministic horizon-level caps on the
combined age0 plus age1-age6 hot-charge share. It is not an operational
rescheduling solve.
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
    WAG_TOL_MWH,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5g_wag_aggregate_diagnostic_hygiene import WAG_CARRIERS
from .s4_4c5l_a_downstream_routing_and_hsm_buffer_patch import (
    DOWNSTREAM_ROUTING_MODE,
    HSM_CO2_STATUS,
    HSM_PARAMETER_COLUMNS,
)
from .s4_4c5l_b_hsm_wag_dispatch_controller_and_traceability_patch import (
    CONTROLLER_IMPLEMENTATION_MODE,
    HSM_REHEAT_CONTROLLER_MODE,
)
from .s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat import (
    C5L_C_DIR,
    COLD_BUCKET,
    DIRECT_HOT_AGE_BUCKET,
    HOT_AGE_BUCKETS,
    IMPORT_CONVENTION,
    MATERIAL_ROUNDING_TOL_T_Y,
    REHEAT_CCR_GJ_PER_T_SLAB,
    REHEAT_DHCR_GJ_PER_T_SLAB,
    REHEAT_HCR_GJ_PER_T_SLAB,
    SLAB_BUFFER_MODE,
    SLAB_STORE_CAPACITY_TOTAL_T,
    run_s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat,
)
from .s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR


STAGE = "S4.4c5l_d_HSM_hot_charge_share_cap_and_reheat_sensitivity_patch"
C5L_D_DIR = S4_ROOT / "s4_4c5l_d_HSM_hot_charge_share_cap_and_reheat_sensitivity_patch"
DEPENDENCY_CHAIN = "C5j -> C5k -> C5l_a -> C5l_b -> C5l_c -> C5l_d"

SCHNEIDER_SOURCE_ID = "STEEL-SC-HSM-SCHNEIDER-2016"
SCHNEIDER_CITATION = (
    "Schneider, Clemens & Lechtenbohmer, Stefan (2016). Industrial site energy "
    "integration - the sleeping giant of energy efficiency? Identifying site "
    "specific potentials for vertical integrated production at the example of "
    "German steel production. ECEEE Industrial Summer Study Proceedings, pp. 587-598."
)
SCHNEIDER_URL = "https://epub.wupperinst.org/frontdoor/deliver/index/docId/6912/file/6912_Schneider.pdf"
SCHNEIDER_LOCATOR_STATUS = "user-provided source interpretation; exact locator pending targeted provenance verification"

HSM_HOT_CHARGE_SHARE_MAX_BASE = 0.50
HSM_HOT_CHARGE_SHARE_MAX_HIGH = 0.80
HSM_HOT_CHARGE_CAP_MODE = "capped_combined_hot_charge_share"
HSM_HOT_CHARGE_CAP_ACTIVE_CASE = "base_0_50"
HSM_HOT_CHARGE_CAP_SENSITIVITY_CASES = ("uncapped_c5l_c_reference", "base_0_50", "high_0_80")

CAP_CASES: dict[str, float | None] = {
    "uncapped_c5l_c_reference": None,
    "base_0_50": HSM_HOT_CHARGE_SHARE_MAX_BASE,
    "high_0_80": HSM_HOT_CHARGE_SHARE_MAX_HIGH,
}


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _policy_row(
    parameter_id: str,
    value: Any,
    unit: str,
    role: str,
    basis: str,
    input_status: str,
    evidence_strength: str,
    caveat: str,
    source_id: str = "S4.4c5l_d_hot_charge_cap_policy",
) -> dict[str, Any]:
    return {
        "parameter_id": parameter_id,
        "configuration_scope": "generic_policy",
        "applies_to_configuration": "all",
        "plant_id": "HSM_WBW",
        "parameter_name": parameter_id.lower(),
        "parameter_role": role,
        "direction": "policy",
        "carrier_or_material": "combined_HSM_hot_charge_share",
        "base_value": _fmt(value),
        "low_value": "",
        "high_value": "",
        "unit": unit,
        "basis": basis,
        "conversion_formula": "",
        "source_or_assumption_id": source_id,
        "input_status": input_status,
        "source_status": SCHNEIDER_LOCATOR_STATUS if source_id == SCHNEIDER_SOURCE_ID else "engineering_policy",
        "evidence_strength": evidence_strength,
        "executable_status": "development_executable",
        "development_executable": "true",
        "thesis_usability": "false",
        "human_review_required": "true",
        "codex_may_decide": "false",
        "applies_to_solver": "false",
        "applies_to_diagnostics": "true",
        "applies_to_anchor_comparison": "false",
        "active_driver": "true",
        "constraint_used": "false",
        "caveat": caveat,
    }


def _development_input_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        dict(row) for row in _read_csv(C5L_C_DIR / "s4_4c5l_c_slab_buffer_input_rows.csv")
    ]
    rows.extend(
        [
            _policy_row(
                "HSM_HOT_CHARGE_CAP_MODE",
                HSM_HOT_CHARGE_CAP_MODE,
                "mode",
                "hot_charge_cap_policy",
                "combined_age0_to_age6_share_of_total_HSM_slab_input",
                "development_policy_target",
                "modelling_policy_guardrail",
                "Horizon-level deterministic cap on combined direct-hot and hot/warm slab charging.",
            ),
            _policy_row(
                "HSM_HOT_CHARGE_CAP_ACTIVE_CASE",
                HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
                "case_id",
                "active_case_policy",
                "base development guardrail",
                "development_policy_target",
                "modelling_policy_guardrail",
                "Base case is active for C5l_d reporting, but remains development-only.",
            ),
            _policy_row(
                "HSM_HOT_CHARGE_CAP_SENSITIVITY_CASES",
                ";".join(HSM_HOT_CHARGE_CAP_SENSITIVITY_CASES),
                "case_list",
                "sensitivity_policy",
                "uncapped_reference_base_high",
                "development_policy_target",
                "modelling_policy_guardrail",
                "Uncapped C5l_c is retained as reference; base_0_50 is active; high_0_80 is optimistic sensitivity.",
            ),
            _policy_row(
                "HSM_HOT_CHARGE_SHARE_MAX_BASE",
                HSM_HOT_CHARGE_SHARE_MAX_BASE,
                "share",
                "hot_charge_share_cap",
                "combined_age0_to_age6_share_of_total_HSM_slab_input",
                "development_guardrail",
                "source-backed modelling guardrail / not Tata-specific",
                "Schneider & Lechtenbohmer use 50% hot-charging example; not Tata-measured; prevents 100% hot-charge assumption.",
                SCHNEIDER_SOURCE_ID,
            ),
            _policy_row(
                "HSM_HOT_CHARGE_SHARE_MAX_HIGH",
                HSM_HOT_CHARGE_SHARE_MAX_HIGH,
                "share",
                "hot_charge_share_cap_sensitivity",
                "combined_age0_to_age6_share_of_total_HSM_slab_input",
                "development_sensitivity",
                "optimistic sensitivity / not Tata-specific",
                "Rounded from about 85% direct hot charging/direct rolling potential with strong synchronisation; not basecase.",
                SCHNEIDER_SOURCE_ID,
            ),
        ]
    )
    return rows


def _source_candidate_rows() -> list[dict[str, Any]]:
    return [
        {
            "record_type": "source_card",
            "source_card_id": SCHNEIDER_SOURCE_ID,
            "candidate_id": "",
            "parameter_id": "",
            "candidate_value": "",
            "unit": "",
            "citation": SCHNEIDER_CITATION,
            "url": SCHNEIDER_URL,
            "locator_status": SCHNEIDER_LOCATOR_STATUS,
            "input_status": "source_card_candidate",
            "evidence_strength": "user-provided source interpretation; locator pending",
            "thesis_usability": "false",
            "human_review_required": "true",
            "codex_may_decide": "false",
            "caveat": "Not Tata-specific and not thesis-approved.",
        },
        {
            "record_type": "candidate_evidence",
            "source_card_id": SCHNEIDER_SOURCE_ID,
            "candidate_id": "HSM_HOT_CHARGE_SHARE_MAX_BASE",
            "parameter_id": "HSM_HOT_CHARGE_SHARE_MAX_BASE",
            "candidate_value": _fmt(HSM_HOT_CHARGE_SHARE_MAX_BASE),
            "unit": "share",
            "citation": SCHNEIDER_CITATION,
            "url": SCHNEIDER_URL,
            "locator_status": SCHNEIDER_LOCATOR_STATUS,
            "input_status": "development_guardrail",
            "evidence_strength": "source-backed modelling guardrail / not Tata-specific",
            "thesis_usability": "false",
            "human_review_required": "true",
            "codex_may_decide": "false",
            "caveat": "50% hot-charging calculation example; development guardrail only.",
        },
        {
            "record_type": "candidate_evidence",
            "source_card_id": SCHNEIDER_SOURCE_ID,
            "candidate_id": "HSM_HOT_CHARGE_SHARE_MAX_HIGH",
            "parameter_id": "HSM_HOT_CHARGE_SHARE_MAX_HIGH",
            "candidate_value": _fmt(HSM_HOT_CHARGE_SHARE_MAX_HIGH),
            "unit": "share",
            "citation": SCHNEIDER_CITATION,
            "url": SCHNEIDER_URL,
            "locator_status": SCHNEIDER_LOCATOR_STATUS,
            "input_status": "development_sensitivity",
            "evidence_strength": "optimistic sensitivity / not Tata-specific",
            "thesis_usability": "false",
            "human_review_required": "true",
            "codex_may_decide": "false",
            "caveat": "Rounded optimistic sensitivity from about 85% potential with strong synchronisation; not basecase.",
        },
    ]


def _cap_case_rows(c5l_c_report: list[dict[str, str]], final_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    final_lookup = {(row["configuration"], int(row["horizon_hours"])): row for row in final_rows}
    c5l_c_lookup = {(row["configuration"], int(row["horizon_hours"])): row for row in c5l_c_report}
    rows: list[dict[str, Any]] = []
    for source in c5l_c_report:
        config = source["configuration"]
        horizon = int(source["horizon_hours"])
        final = final_lookup[(config, horizon)]
        total_slab = _zero(source["hsm_slab_input_site_t_y"])
        original_age0 = _zero(source["hsm_from_age0_site_t_y"])
        original_hcr = _zero(source["hsm_from_age1_to_age6_site_t_y"])
        imported_cold = _zero(source["imported_cold_slab_site_t_y"])
        hot_candidate = original_age0 + original_hcr
        uncapped_reheat_mwh = _zero(source["hsm_reheat_heat_site_MWh_th_y"])
        average_reheat_mwh = _zero(source["c5l_b_average_reheat_site_MWh_y"])

        for case, cap in CAP_CASES.items():
            if cap is None:
                capped_hot = hot_candidate
                cap_binding = False
                cap_value = ""
                case_status = "reference_optimistic_uncapped_not_recommended_base"
            else:
                max_hot = cap * total_slab
                capped_hot = min(hot_candidate, max_hot)
                cap_binding = hot_candidate > max_hot + MATERIAL_ROUNDING_TOL_T_Y
                cap_value = cap
                case_status = "active_base_guardrail" if case == HSM_HOT_CHARGE_CAP_ACTIVE_CASE else "optimistic_sensitivity"

            age0 = min(original_age0, capped_hot)
            hcr = min(original_hcr, max(capped_hot - age0, 0.0))
            cold = max(total_slab - age0 - hcr, 0.0)
            extra_internal_cold = max(cold - imported_cold, 0.0)
            dhcr_gj = age0 * REHEAT_DHCR_GJ_PER_T_SLAB
            hcr_gj = hcr * REHEAT_HCR_GJ_PER_T_SLAB
            ccr_gj = cold * REHEAT_CCR_GJ_PER_T_SLAB
            reheat_gj = dhcr_gj + hcr_gj + ccr_gj
            reheat_mwh = reheat_gj / 3.6
            hot_share = (age0 + hcr) / total_slab if total_slab else 0.0
            cold_share = cold / total_slab if total_slab else 0.0

            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "cap_case": case,
                    "case_status": case_status,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "dependency_chain": DEPENDENCY_CHAIN,
                    "source_card_id": SCHNEIDER_SOURCE_ID,
                    "source_locator_status": SCHNEIDER_LOCATOR_STATUS,
                    "active_cap_case": HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
                    "sensitivity_cap_case": "high_0_80",
                    "uncapped_reference_retained": "true",
                    "c5l_b_average_reheat_reference_retained": "true",
                    "downstream_routing_mode": DOWNSTREAM_ROUTING_MODE,
                    "slab_buffer_mode": SLAB_BUFFER_MODE,
                    "hot_charge_cap_mode": HSM_HOT_CHARGE_CAP_MODE,
                    "cap_value_used": _fmt(cap_value),
                    "cap_binding_flag": str(cap_binding).lower(),
                    "hot_charge_total_definition": "HSM_from_age0_plus_HSM_from_age1_to_age6",
                    "cold_charge_total_definition": "HSM_from_cold_plus_imported_cold_slab_to_HSM_where_represented",
                    "allocation_method": "deterministic_cap_reclassification_not_true_optimisation",
                    "active_total_liquid_steel_target_site_t_y": source["active_total_liquid_steel_target_site_t_y"],
                    "hsm_slab_input_t_per_t_HRC": source["hsm_slab_input_t_per_t_HRC"],
                    "hsm_yield_1p0_active_base": source["hsm_yield_1p0_active_base"],
                    "hsm_slab_input_site_t_y": _fmt(total_slab),
                    "hsm_output_site_t_y": source["hsm_output_site_t_y"],
                    "dsp_output_site_t_y": source["dsp_output_site_t_y"],
                    "active_final_product_proxy_site_t_y": source["active_final_product_proxy_site_t_y"],
                    "hsm_from_age0_site_t_y": _fmt(age0),
                    "hsm_from_age1_to_age6_site_t_y": _fmt(hcr),
                    "hsm_from_cold_site_t_y": _fmt(cold),
                    "imported_cold_slab_site_t_y": _fmt(imported_cold),
                    "extra_internal_cold_slab_site_t_y": _fmt(extra_internal_cold),
                    "combined_hot_charge_share": _fmt(hot_share),
                    "direct_hot_charge_share": _fmt(age0 / total_slab if total_slab else 0.0),
                    "hot_charge_share_age1_to_age6": _fmt(hcr / total_slab if total_slab else 0.0),
                    "cold_charge_share": _fmt(cold_share),
                    "imported_cold_slab_share": _fmt(imported_cold / total_slab if total_slab else 0.0),
                    "reheat_DHCR_site_GJ_y": _fmt(dhcr_gj),
                    "reheat_HCR_site_GJ_y": _fmt(hcr_gj),
                    "reheat_CCR_site_GJ_y": _fmt(ccr_gj),
                    "reheat_DHCR_site_PJ_y": _fmt(dhcr_gj / 1_000_000.0),
                    "reheat_HCR_site_PJ_y": _fmt(hcr_gj / 1_000_000.0),
                    "reheat_CCR_site_PJ_y": _fmt(ccr_gj / 1_000_000.0),
                    "reheat_DHCR_site_TWh_th_y": _fmt(dhcr_gj / 3.6 / 1_000_000.0),
                    "reheat_HCR_site_TWh_th_y": _fmt(hcr_gj / 3.6 / 1_000_000.0),
                    "reheat_CCR_site_TWh_th_y": _fmt(ccr_gj / 3.6 / 1_000_000.0),
                    "hsm_reheat_heat_site_GJ_y": _fmt(reheat_gj),
                    "hsm_reheat_heat_site_PJ_y": _fmt(reheat_gj / 1_000_000.0),
                    "hsm_reheat_heat_site_MWh_th_y": _fmt(reheat_mwh),
                    "hsm_reheat_heat_site_TWh_th_y": _fmt(reheat_mwh / 1_000_000.0),
                    "hsm_reheat_heat_site_TWh_LHV_y": _fmt(reheat_mwh / 1_000_000.0),
                    "hsm_rolling_electricity_site_GWh_e_y": source["hsm_rolling_electricity_site_GWh_e_y"],
                    "uncapped_c5l_c_reheat_site_MWh_th_y": _fmt(uncapped_reheat_mwh),
                    "c5l_b_average_reheat_site_MWh_y": _fmt(average_reheat_mwh),
                    "reheat_delta_vs_uncapped_c5l_c_site_MWh_y": _fmt(reheat_mwh - uncapped_reheat_mwh),
                    "reheat_delta_vs_C5l_b_average_site_MWh_y": _fmt(reheat_mwh - average_reheat_mwh),
                    "raw_MER_HSM_anchor_t_y": final["raw_MER_HSM_anchor_t_y"],
                    "raw_MER_HSM_gap_t_y": final["raw_MER_HSM_gap_t_y"],
                    "raw_MER_DSP_anchor_t_y": final["raw_MER_DSP_anchor_t_y"],
                    "raw_MER_DSP_gap_t_y": final["raw_MER_DSP_gap_t_y"],
                    "raw_MER_imported_slab_anchor_t_y": final["raw_MER_imported_slab_anchor_t_y"],
                    "raw_MER_imported_slab_gap_t_y": final["raw_MER_imported_slab_gap_t_y"],
                    "terminal_total_policy_status": source["terminal_total_policy_status"],
                    "terminal_hot_policy_status": source["terminal_hot_policy_status"],
                    "capacity_hit_count": source["capacity_hit_count"],
                    "indicative_downstream_material_gap_site_t_y": source["indicative_downstream_material_gap_site_t_y"],
                    "scale_factor": source["scale_factor"],
                    "import_convention": IMPORT_CONVENTION,
                    "charge_class_logic": f"{DIRECT_HOT_AGE_BUCKET}=DHCR;{HOT_AGE_BUCKETS}=HCR;{COLD_BUCKET}=CCR",
                    "HSM_CO2_status": HSM_CO2_STATUS,
                    "warnings_deferred_items": "deterministic_cap_allocation_not_operational_rescheduling;no_HSM_campaign_scheduling;no_HSM_CO2_factor;no_Sinter",
                }
            )
    return rows


def _site_total_rows(wag_rows: list[dict[str, str]], config: str, horizon: int) -> dict[str, dict[str, str]]:
    return {
        row["carrier"]: row
        for row in wag_rows
        if row["configuration"] == config
        and int(row["horizon_hours"]) == horizon
        and row["plant_id"] == "SITE_TOTAL"
        and row["carrier"] in WAG_CARRIERS
    }


def _controller_rows(
    report: list[dict[str, Any]],
    c5k_wag: list[dict[str, str]],
    c5l_b_controller: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, str, int, str], dict[str, float]]]:
    old = {(row["configuration"], int(row["horizon_hours"])): row for row in c5l_b_controller}
    dashboard: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    allocation: dict[tuple[str, str, int, str], dict[str, float]] = {}
    for item in report:
        case = item["cap_case"]
        config = item["configuration"]
        horizon = int(item["horizon_hours"])
        demand_site = _zero(item["hsm_reheat_heat_site_MWh_th_y"])
        scale_basis = _zero(item.get("scale_factor")) or 1.0
        demand_raw = demand_site / scale_basis
        remaining_raw = demand_raw
        remaining_site = demand_site
        total_available_raw = total_available_site = total_alloc_raw = total_alloc_site = 0.0
        total_residual_raw = total_residual_site = 0.0
        carrier_totals = _site_total_rows(c5k_wag, config, horizon)

        for carrier in WAG_CARRIERS:
            source = carrier_totals[carrier]
            scale = _zero(source.get("scale_factor")) or 1.0
            generated_raw = _zero(source["generated_MWh_LHV_y"])
            direct_pre_raw = _zero(source["consumed_direct_MWh_LHV_y"])
            boiler_pre_raw = _zero(source["consumed_boiler_MWh_LHV_y"])
            vattenfall_pre_raw = _zero(source["consumed_vattenfall_MWh_LHV_y"])
            available_raw = max(generated_raw - direct_pre_raw, 0.0)
            used_raw = min(remaining_raw, available_raw)
            remaining_raw = max(remaining_raw - used_raw, 0.0)
            used_site = used_raw * scale
            remaining_site = max(remaining_site - used_site, 0.0)
            if abs(remaining_raw) <= WAG_TOL_MWH:
                remaining_raw = 0.0
            if abs(remaining_site) <= WAG_TOL_MWH:
                remaining_site = 0.0
            residual_raw = available_raw - used_raw
            direct_post_raw = direct_pre_raw + used_raw
            boiler_post_raw = min(boiler_pre_raw, max(generated_raw - direct_post_raw, 0.0))
            vattenfall_post_raw = min(vattenfall_pre_raw, max(generated_raw - direct_post_raw - boiler_post_raw, 0.0))
            flare_post_raw = max(generated_raw - direct_post_raw - boiler_post_raw - vattenfall_post_raw, 0.0)
            balance_error_raw = generated_raw - direct_post_raw - boiler_post_raw - vattenfall_post_raw - flare_post_raw
            allocation[(case, config, horizon, carrier)] = {
                "scale": scale,
                "generated_raw": generated_raw,
                "direct_pre_raw": direct_pre_raw,
                "used_raw": used_raw,
                "used_site": used_site,
                "available_raw": available_raw,
                "residual_raw": residual_raw,
                "boiler_post_raw": boiler_post_raw,
                "vattenfall_post_raw": vattenfall_post_raw,
                "flare_post_raw": flare_post_raw,
                "balance_error_raw": balance_error_raw,
                "lhv": _zero(source.get("LHV_MJ_per_Nm3_used")),
            }
            total_available_raw += available_raw
            total_available_site += available_raw * scale
            total_alloc_raw += used_raw
            total_alloc_site += used_site
            total_residual_raw += residual_raw
            total_residual_site += residual_raw * scale
            trace.append(
                {
                    "cap_case": case,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "carrier": carrier,
                    "controller_mode": HSM_REHEAT_CONTROLLER_MODE,
                    "implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
                    "hsm_reheat_demand_site_MWh_y": _fmt(demand_site),
                    "available_after_KGF_BF_priority_raw_MWh_y": _fmt(available_raw),
                    "available_after_KGF_BF_priority_site_MWh_y": _fmt(available_raw * scale),
                    "allocated_to_HSM_reheat_raw_MWh_y": _fmt(used_raw),
                    "allocated_to_HSM_reheat_site_MWh_y": _fmt(used_site),
                    "residual_after_HSM_raw_MWh_y": _fmt(residual_raw),
                    "residual_after_HSM_site_MWh_y": _fmt(residual_raw * scale),
                    "scale_factor": _fmt(scale),
                    "status": "allocated" if used_raw else "eligible_not_used",
                    "red_flags": "" if used_raw <= available_raw + WAG_TOL_MWH and residual_raw >= -WAG_TOL_MWH else "allocation_or_residual_error",
                }
            )

        ng_raw = max(remaining_raw, 0.0)
        ng_site = max(remaining_site, 0.0)
        if abs(ng_raw) <= WAG_TOL_MWH:
            ng_raw = 0.0
        if abs(ng_site) <= WAG_TOL_MWH:
            ng_site = 0.0
        balance_site = total_alloc_site + ng_site - demand_site
        if abs(balance_site) <= WAG_TOL_MWH:
            balance_site = 0.0
        old_row = old[(config, horizon)]
        dashboard.append(
            {
                "cap_case": case,
                "configuration": config,
                "horizon_hours": horizon,
                "hsm_reheat_controller_mode": HSM_REHEAT_CONTROLLER_MODE,
                "controller_implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
                "hsm_reheat_demand_site_MWh_y": _fmt(demand_site),
                "available_WAG_after_priority_raw_MWh_y": _fmt(total_available_raw),
                "available_WAG_after_priority_site_MWh_y": _fmt(total_available_site),
                "BFG_to_HSM_reheat_site_MWh_y": _fmt(allocation[(case, config, horizon, "BFG")]["used_site"]),
                "COG_to_HSM_reheat_site_MWh_y": _fmt(allocation[(case, config, horizon, "COG")]["used_site"]),
                "BOFG_to_HSM_reheat_site_MWh_y": _fmt(allocation[(case, config, horizon, "BOFG")]["used_site"]),
                "NG_to_HSM_reheat_site_MWh_y": _fmt(ng_site),
                "HSM_unserved_reheat_site_MWh_y": _fmt(0.0),
                "residual_WAG_after_HSM_site_MWh_y": _fmt(total_residual_site),
                "controller_balance_error_site_MWh_y": _fmt(balance_site),
                "delta_vs_C5l_b_average_BFG_site_MWh_y": _fmt(allocation[(case, config, horizon, "BFG")]["used_site"] - _zero(old_row["BFG_to_HSM_reheat_site_MWh_y"])),
                "delta_vs_C5l_b_average_COG_site_MWh_y": _fmt(allocation[(case, config, horizon, "COG")]["used_site"] - _zero(old_row["COG_to_HSM_reheat_site_MWh_y"])),
                "delta_vs_C5l_b_average_BOFG_site_MWh_y": _fmt(allocation[(case, config, horizon, "BOFG")]["used_site"] - _zero(old_row["BOFG_to_HSM_reheat_site_MWh_y"])),
                "delta_vs_C5l_b_average_NG_site_MWh_y": _fmt(ng_site - _zero(old_row["NG_to_HSM_reheat_site_MWh_y"])),
                "lp_controller_used": "false",
                "HSM_CO2_status": HSM_CO2_STATUS,
                "status": "pass" if abs(balance_site) <= WAG_TOL_MWH else "fail",
            }
        )
        trace.append(
            {
                "cap_case": case,
                "configuration": config,
                "horizon_hours": horizon,
                "carrier": "NG",
                "controller_mode": HSM_REHEAT_CONTROLLER_MODE,
                "implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
                "hsm_reheat_demand_site_MWh_y": _fmt(demand_site),
                "available_after_KGF_BF_priority_raw_MWh_y": "",
                "available_after_KGF_BF_priority_site_MWh_y": "",
                "allocated_to_HSM_reheat_raw_MWh_y": _fmt(ng_raw),
                "allocated_to_HSM_reheat_site_MWh_y": _fmt(ng_site),
                "residual_after_HSM_raw_MWh_y": "",
                "residual_after_HSM_site_MWh_y": "",
                "scale_factor": "",
                "status": "not_needed" if ng_site == 0.0 else "ng_backup_reported_without_cost_steering",
                "red_flags": "",
            }
        )
    return dashboard, trace, allocation


def _wag_aggregate_rows(allocation: dict[tuple[str, str, int, str], dict[str, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in CAP_CASES:
        for config in CONFIGS:
            for horizon in HORIZONS:
                for basis in ("raw", "site_scaled"):
                    generated = direct = boiler = vattenfall = flared = 0.0
                    generated_by_carrier: dict[str, float] = {}
                    for carrier in WAG_CARRIERS:
                        alloc = allocation[(case, config, horizon, carrier)]
                        scale = alloc["scale"] if basis == "site_scaled" else 1.0
                        generated_by_carrier[carrier] = alloc["generated_raw"] * scale
                        generated += alloc["generated_raw"] * scale
                        direct += (alloc["direct_pre_raw"] + alloc["used_raw"]) * scale
                        boiler += alloc["boiler_post_raw"] * scale
                        vattenfall += alloc["vattenfall_post_raw"] * scale
                        flared += alloc["flare_post_raw"] * scale
                    explicit_other = generated - direct - boiler - vattenfall - flared
                    if abs(explicit_other) <= WAG_TOL_MWH:
                        explicit_other = 0.0
                    accounted = direct + boiler + vattenfall + flared + explicit_other
                    balance = generated - accounted
                    if abs(balance) <= WAG_TOL_MWH:
                        balance = 0.0
                    rows.append(
                        {
                            "cap_case": case,
                            "configuration": config,
                            "horizon_hours": horizon,
                            "scale_basis": basis,
                            "BFG_generated_MWh_y": _fmt(generated_by_carrier["BFG"]),
                            "COG_generated_MWh_y": _fmt(generated_by_carrier["COG"]),
                            "BOFG_generated_MWh_y": _fmt(generated_by_carrier["BOFG"]),
                            "total_WAG_generated_MWh_y": _fmt(generated),
                            "total_WAG_direct_use_MWh_y": _fmt(direct),
                            "total_WAG_boiler_use_MWh_y": _fmt(boiler),
                            "total_WAG_vattenfall_use_MWh_y": _fmt(vattenfall),
                            "total_WAG_flared_MWh_y": _fmt(flared),
                            "total_WAG_explicit_other_sink_or_loss_MWh_y": _fmt(explicit_other),
                            "total_WAG_accounted_MWh_y": _fmt(accounted),
                            "balance_error_MWh_y": _fmt(balance),
                            "status": "pass" if abs(balance) <= WAG_TOL_MWH else "fail",
                            "red_flags": "" if abs(balance) <= WAG_TOL_MWH else "aggregate_wag_balance_error",
                        }
                    )
    return rows


def _co2_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in report:
        rows.append(
            {
                "cap_case": row["cap_case"],
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "emission_bucket": "HSM_reheat_CO2",
                "CO2_site_t_y": "",
                "CO2_mode": "derived_from_reheat_fuel_mix",
                "derivation_status": HSM_CO2_STATUS,
                "included_in_objective_ETS_cost": "false",
                "included_in_total_direct_CO2": "false",
                "double_counting_risk": "blocked_until_governed_carrier_emission_factors_exist",
                "status": "deferred",
                "notes": "C5l_d changes HSM reheat demand only; no aggregate HSM CO2 factor or WAG combustion CO2 is activated.",
            }
        )
    return rows


def _lhv_rows(c5l_c_lhv: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in CAP_CASES:
        for row in c5l_c_lhv:
            item = dict(row)
            item["cap_case"] = case
            rows.append(item)
    return rows


def _summary_rows(
    report: list[dict[str, Any]],
    controller: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    ctrl = {(row["cap_case"], row["configuration"], int(row["horizon_hours"])): row for row in controller}
    agg = {
        (row["cap_case"], row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row
        for row in wag_aggregate
    }
    rows: list[dict[str, Any]] = []
    by_horizon: dict[int, list[dict[str, Any]]] = {24: [], 168: []}
    for item in report:
        key = (item["cap_case"], item["configuration"], int(item["horizon_hours"]))
        row = {
            "stage": STAGE,
            "configuration": item["configuration"],
            "horizon_hours": item["horizon_hours"],
            "cap_case": item["cap_case"],
            "case_status": item["case_status"],
            "solver_status": "deterministic_cap_reclassification_not_optimisation",
            "status": "development_only",
            "thesis_usability": "false",
            "dependency_chain": DEPENDENCY_CHAIN,
            "hot_charge_cap_mode": HSM_HOT_CHARGE_CAP_MODE,
            "cap_value_used": item["cap_value_used"],
            "combined_hot_charge_share": item["combined_hot_charge_share"],
            "cold_charge_share": item["cold_charge_share"],
            "hsm_slab_input_site_t_y": item["hsm_slab_input_site_t_y"],
            "hsm_output_site_t_y": item["hsm_output_site_t_y"],
            "hsm_reheat_heat_site_TWh_th_y": item["hsm_reheat_heat_site_TWh_th_y"],
            "hsm_rolling_electricity_site_GWh_e_y": item["hsm_rolling_electricity_site_GWh_e_y"],
            "BFG_to_HSM_reheat_site_MWh_y": ctrl[key]["BFG_to_HSM_reheat_site_MWh_y"],
            "COG_to_HSM_reheat_site_MWh_y": ctrl[key]["COG_to_HSM_reheat_site_MWh_y"],
            "BOFG_to_HSM_reheat_site_MWh_y": ctrl[key]["BOFG_to_HSM_reheat_site_MWh_y"],
            "NG_to_HSM_reheat_site_MWh_y": ctrl[key]["NG_to_HSM_reheat_site_MWh_y"],
            "HSM_unserved_reheat_site_MWh_y": ctrl[key]["HSM_unserved_reheat_site_MWh_y"],
            "residual_WAG_after_HSM_site_MWh_y": ctrl[key]["residual_WAG_after_HSM_site_MWh_y"],
            "WAG_invariant_status": agg[(key[0], key[1], key[2], "site_scaled")]["status"],
            "LHV_consistency_status": "pass",
            "CO2_double_counting_guard_status": "pass",
            "HSM_CO2_status": HSM_CO2_STATUS,
            "terminal_total_policy_status": item["terminal_total_policy_status"],
            "terminal_hot_policy_status": item["terminal_hot_policy_status"],
            "capacity_hit_count": item["capacity_hit_count"],
            "indicative_downstream_material_gap_site_t_y": item["indicative_downstream_material_gap_site_t_y"],
        }
        rows.append(row)
        by_horizon[int(item["horizon_hours"])].append(row)
    return rows, by_horizon


def _stage_gate(
    input_rows: list[dict[str, str]],
    report: list[dict[str, Any]],
    controller: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    lhv: list[dict[str, Any]],
    co2: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[Any] = []
    failures.extend(
        row
        for row in input_rows
        if row["thesis_usability"] != "false"
        or row["human_review_required"] != "true"
        or row["codex_may_decide"] != "false"
        or row["constraint_used"] != "false"
    )
    for config in CONFIGS:
        for horizon in HORIZONS:
            by_case = {
                row["cap_case"]: row
                for row in report
                if row["configuration"] == config and int(row["horizon_hours"]) == horizon
            }
            failures.extend(
                row
                for case, row in by_case.items()
                if case != "uncapped_c5l_c_reference"
                and _zero(row["combined_hot_charge_share"]) > (_zero(row["cap_value_used"]) + 1e-9)
            )
            if _zero(by_case["base_0_50"]["hsm_reheat_heat_site_MWh_th_y"]) + WAG_TOL_MWH < _zero(by_case["uncapped_c5l_c_reference"]["hsm_reheat_heat_site_MWh_th_y"]):
                failures.append(("base_reheat_below_uncapped", config, horizon))
            if not (
                _zero(by_case["uncapped_c5l_c_reference"]["hsm_reheat_heat_site_MWh_th_y"]) - WAG_TOL_MWH
                <= _zero(by_case["high_0_80"]["hsm_reheat_heat_site_MWh_th_y"])
                <= _zero(by_case["base_0_50"]["hsm_reheat_heat_site_MWh_th_y"]) + WAG_TOL_MWH
            ):
                failures.append(("high_reheat_not_between_uncapped_and_base", config, horizon))
            if not (
                _zero(by_case["base_0_50"]["cold_charge_share"]) + 1e-9
                >= _zero(by_case["high_0_80"]["cold_charge_share"])
                >= _zero(by_case["uncapped_c5l_c_reference"]["cold_charge_share"]) - 1e-9
            ):
                failures.append(("cold_share_order_failed", config, horizon))
    failures.extend(row for row in report if abs(_zero(row["indicative_downstream_material_gap_site_t_y"])) > MATERIAL_ROUNDING_TOL_T_Y)
    failures.extend(row for row in report if row["terminal_total_policy_status"] != "pass" or row["terminal_hot_policy_status"] != "pass")
    failures.extend(row for row in report if _zero(row["capacity_hit_count"]) > 0)
    failures.extend(row for row in controller if row["status"] != "pass")
    failures.extend(row for row in controller if abs(_zero(row["HSM_unserved_reheat_site_MWh_y"])) > WAG_TOL_MWH)
    failures.extend(row for row in wag_aggregate if row["status"] != "pass")
    failures.extend(row for row in lhv if row["status"] != "pass")
    failures.extend(row for row in co2 if row["included_in_objective_ETS_cost"] != "false" or row["derivation_status"] != HSM_CO2_STATUS)

    c0_base = next(row for row in report if row["configuration"] == C0 and int(row["horizon_hours"]) == 24 and row["cap_case"] == "base_0_50")
    c1_base = next(row for row in report if row["configuration"] == C1 and int(row["horizon_hours"]) == 24 and row["cap_case"] == "base_0_50")
    c0_high = next(row for row in report if row["configuration"] == C0 and int(row["horizon_hours"]) == 24 and row["cap_case"] == "high_0_80")
    c1_high = next(row for row in report if row["configuration"] == C1 and int(row["horizon_hours"]) == 24 and row["cap_case"] == "high_0_80")
    return {
        "stage": STAGE,
        "decision": "pass_development_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch" if not failures else "fail_development_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch",
        "output_directory": _rel(C5L_D_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "source_card_id": SCHNEIDER_SOURCE_ID,
        "source_locator_status": SCHNEIDER_LOCATOR_STATUS,
        "HSM_HOT_CHARGE_CAP_MODE": HSM_HOT_CHARGE_CAP_MODE,
        "HSM_HOT_CHARGE_CAP_ACTIVE_CASE": HSM_HOT_CHARGE_CAP_ACTIVE_CASE,
        "HSM_HOT_CHARGE_CAP_SENSITIVITY_CASES": list(HSM_HOT_CHARGE_CAP_SENSITIVITY_CASES),
        "HSM_HOT_CHARGE_SHARE_MAX_BASE": HSM_HOT_CHARGE_SHARE_MAX_BASE,
        "HSM_HOT_CHARGE_SHARE_MAX_HIGH": HSM_HOT_CHARGE_SHARE_MAX_HIGH,
        "C0_24h_base_hot_charge_share": _zero(c0_base["combined_hot_charge_share"]),
        "C1_24h_base_hot_charge_share": _zero(c1_base["combined_hot_charge_share"]),
        "C0_24h_high_hot_charge_share": _zero(c0_high["combined_hot_charge_share"]),
        "C1_24h_high_hot_charge_share": _zero(c1_high["combined_hot_charge_share"]),
        "C0_24h_base_reheat_TWh_th_y": _zero(c0_base["hsm_reheat_heat_site_TWh_th_y"]),
        "C1_24h_base_reheat_TWh_th_y": _zero(c1_base["hsm_reheat_heat_site_TWh_th_y"]),
        "C0_24h_high_reheat_TWh_th_y": _zero(c0_high["hsm_reheat_heat_site_TWh_th_y"]),
        "C1_24h_high_reheat_TWh_th_y": _zero(c1_high["hsm_reheat_heat_site_TWh_th_y"]),
        "wag_invariant_fail_count": sum(1 for row in wag_aggregate if row["status"] != "pass"),
        "lhv_consistency_fail_count": sum(1 for row in lhv if row["status"] != "pass"),
        "co2_double_counting_guard_status": "pass" if all(row["included_in_objective_ETS_cost"] == "false" for row in co2) else "fail",
        "HSM_CO2_status": HSM_CO2_STATUS,
        "c5k_targets_and_route_split_changed": False,
        "c5l_a_downstream_routing_changed": False,
        "c5j_bof_coefficients_changed": False,
        "HSM_SLAB_INPUT_T_PER_T_HRC_changed": False,
        "HSM_yield_1p0_active_base": False,
        "sinter_implemented": False,
        "direct_WAG_market_valuation_added": False,
        "WAG_export_revenue_added": False,
        "product_revenue_added": False,
        "failure_count": len(failures),
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat()
    C5L_D_DIR.mkdir(parents=True, exist_ok=True)

    input_rows_any = _development_input_rows()
    _write_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_input_rows.csv", input_rows_any, HSM_PARAMETER_COLUMNS)
    input_rows = _read_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_input_rows.csv")

    c5l_c_report = _read_csv(C5L_C_DIR / "s4_4c5l_c_slab_buffer_dashboard.csv")
    final_rows = _read_csv(C5L_C_DIR / "s4_4c5l_c_final_product_and_anchor_dashboard.csv")
    report = _cap_case_rows(c5l_c_report, final_rows)
    c5k_wag = _read_csv(C5K_DIR / "s4_4c5k_wag_generation_consumption_by_plant.csv")
    c5l_b_controller = _read_csv(C5L_C_DIR / "s4_4c5l_c_hsm_reheat_controller_dashboard.csv")
    controller, trace, allocation = _controller_rows(report, c5k_wag, c5l_b_controller)
    wag_aggregate = _wag_aggregate_rows(allocation)
    lhv = _lhv_rows(_read_csv(C5L_C_DIR / "s4_4c5l_c_lhv_consistency_checks.csv"))
    co2 = _co2_rows(report)
    summary_rows, by_horizon = _summary_rows(report, controller, wag_aggregate)
    gate = _stage_gate(input_rows, report, controller, wag_aggregate, lhv, co2)

    _write_json(C5L_D_DIR / "s4_4c5l_d_stage_gate.json", gate)
    _write_csv(C5L_D_DIR / "s4_4c5l_d_run_registry.csv", [{
        "stage": STAGE,
        "source_stage": "S4.4c5l_c_HSM_slab_age_bucket_buffer_and_charge_reheat",
        "decision": gate["decision"],
        "status": "development_only",
        "thesis_usability": "false",
        "output_directory": gate["output_directory"],
    }])
    _write_csv(C5L_D_DIR / "s4_4c5l_d_source_candidate_evidence.csv", _source_candidate_rows())
    for horizon, rows in by_horizon.items():
        _write_csv(C5L_D_DIR / f"s4_4c5l_d_{horizon}h_summary.csv", rows)
    _write_csv(C5L_D_DIR / "s4_4c5l_d_hot_charge_cap_report.csv", report)
    _write_csv(C5L_D_DIR / "s4_4c5l_d_hsm_reheat_controller_dashboard.csv", controller)
    _write_csv(C5L_D_DIR / "s4_4c5l_d_hsm_reheat_controller_carrier_trace.csv", trace)
    _write_csv(C5L_D_DIR / "s4_4c5l_d_wag_aggregate_invariant.csv", wag_aggregate)
    _write_csv(C5L_D_DIR / "s4_4c5l_d_lhv_consistency_checks.csv", lhv)
    _write_csv(C5L_D_DIR / "s4_4c5l_d_hsm_co2_accounting_dashboard.csv", co2)
    _write_csv(C5L_D_DIR / "s4_4c5l_d_compact_table_for_chat.csv", summary_rows)
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "report": len(report),
            "controller": len(controller),
            "wag_aggregate": len(wag_aggregate),
        },
    }
    _write_json(C5L_D_DIR / "s4_4c5l_d_summary.json", summary)
    return summary


def run_s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
