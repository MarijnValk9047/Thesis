"""S4.4c5p_m WAG balance and controller-contract diagnostics.

This stage is diagnostic-only. It reads existing C5 WAG, steam, generator,
HSM and anchor artifacts, then reports carrier balances and controller-contract
gaps. It does not create a new WAG allocation function and does not change
model equations, executable development inputs, source cards, objectives, or
dispatch behaviour.
"""

from __future__ import annotations

import json
import math
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
from .s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation import C5P_E_DIR
from .s4_4c5p_k_common_plant_ng_wag_overlay import C5P_K_DIR


STAGE = "S4.4c5p_m_wag_balance_and_controller_contract"
C5P_M_DIR = S4_ROOT / "s4_4c5p_m_wag_balance_and_controller_contract"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_WAG_BALANCE_AND_CONTROLLER_CONTRACT.md")

C5P_B_DIR = S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting"
C5P_C_DIR = S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting"
C5P_L_DIR = S4_ROOT / "s4_4c5p_l_model_wide_anchor_sensitivity_error_mode_analysis"
C5L_B_DIR = S4_ROOT / "s4_4c5l_b_HSM_WAG_dispatch_controller_and_traceability_patch"
C5L_D_DIR = S4_ROOT / "s4_4c5l_d_HSM_hot_charge_share_cap_and_reheat_sensitivity_patch"
C5M_DIR = S4_ROOT / "s4_4c5m_Sinter_minimal_parameterisation"
ANCHOR_REGISTER_PATH = S4_ROOT / "c5_model_anchor_register/c5_model_anchor_evidence_register.csv"

MWH_TO_PJ = 3.6 / 1_000_000.0
TOL_PJ = 1e-6
WAG_CARRIERS = ("BFG", "BOFG", "COG")
CONFIGS = (C0, C1)

BALANCE_COLUMNS = [
    "configuration",
    "carrier",
    "generation_PJ_y",
    "mandatory_self_use_PJ_y",
    "process_use_PJ_y",
    "hsm_wbw_use_PJ_y",
    "steam_boiler_use_PJ_y",
    "generator_use_PJ_y",
    "flare_spill_PJ_y",
    "residual_PJ_y",
    "accounted_total_PJ_y",
    "balance_residual_PJ_y",
    "balance_status",
    "source_stage_or_artifact",
    "caveat",
]

ANCHOR_COLUMNS = [
    "configuration",
    "carrier_or_metric",
    "model_metric",
    "model_value",
    "model_unit",
    "anchor_id",
    "anchor_value",
    "anchor_unit",
    "anchor_source_rank",
    "evidence_tier",
    "locator_quality",
    "comparison_basis",
    "raw_gap",
    "normalised_gap",
    "comparison_status",
    "caveat",
]

CONTROLLER_COLUMNS = [
    "function_or_module_name",
    "file_path",
    "purpose",
    "carriers_handled",
    "sinks_or_plants_affected",
    "input_artifacts",
    "output_artifacts",
    "priority_logic_if_any",
    "allocation_mode",
    "current_C5_stage_use",
    "whether_C5p_k_bypassed_or_approximated",
    "risk_if_used_for_sensitivity",
    "recommended_action",
]

PRIORITY_COLUMNS = [
    "configuration",
    "priority_order_candidate",
    "source_or_function",
    "sink",
    "carrier",
    "is_explicit",
    "is_governed",
    "is_diagnostic_only",
    "conflict_with_other_surface",
    "caveat",
]

WARNING_COLUMNS = [
    "warning_id",
    "severity",
    "configuration",
    "carrier",
    "affected_sink_or_stage",
    "issue_type",
    "message",
    "evidence_artifact",
    "recommended_action",
]

GAP_COLUMNS = [
    "gap_id",
    "gap_type",
    "affected_configuration",
    "affected_carrier",
    "affected_sink",
    "current_status",
    "why_it_matters",
    "blocker_for_next_phase",
    "recommended_fix_type",
    "recommended_next_action",
]


def _fmt(value: Any, digits: int = 6) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def _pj_from_mwh(value: Any) -> float:
    return _zero(value) * MWH_TO_PJ


def _safe_div(numerator: float, denominator: float) -> float:
    if abs(denominator) <= TOL_PJ:
        return math.nan
    return numerator / denominator


def _rows_by_config_carrier(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    rows = _read_csv(path)
    return {
        (row["configuration"], row["carrier"]): row
        for row in rows
        if row.get("carrier") in WAG_CARRIERS
    }


def _pc_residual_rows() -> dict[str, dict[str, str]]:
    path = C5P_C_DIR / "s4_4c5p_c_wag_residual_after_generators.csv"
    return {
        row["configuration"]: row
        for row in _read_csv(path)
        if row.get("horizon_hours") == "24"
    }


def _pc_alloc_rows() -> dict[tuple[str, str], dict[str, str]]:
    path = C5P_C_DIR / "s4_4c5p_c_generator_fuel_allocation.csv"
    return {
        (row["configuration"], row["unit_id"]): row
        for row in _read_csv(path)
        if row.get("horizon_hours") == "24"
    }


def _build_balance_rows() -> list[dict[str, Any]]:
    flow_rows = _rows_by_config_carrier(C5P_E_DIR / "c5_annual_flow_balance_by_carrier.csv")
    pc_rows = _pc_residual_rows()
    rows: list[dict[str, Any]] = []

    for config in CONFIGS:
        aggregates = {
            "generation": 0.0,
            "mandatory": 0.0,
            "process": 0.0,
            "steam": 0.0,
            "generator": 0.0,
            "residual": 0.0,
            "balance": 0.0,
        }
        for carrier in WAG_CARRIERS:
            source = flow_rows.get((config, carrier))
            if source is None:
                rows.append(
                    {
                        "configuration": config,
                        "carrier": carrier,
                        "balance_status": "not_available",
                        "source_stage_or_artifact": "c5_annual_flow_balance_by_carrier.csv",
                        "caveat": "Carrier row missing in current annual flow balance.",
                    }
                )
                continue

            generation = _pj_from_mwh(source["generated_or_supplied"])
            mandatory = _pj_from_mwh(source["mandatory_process_self_use"])
            process = _pj_from_mwh(source["preparation_or_process_use"])
            steam = _pj_from_mwh(source["boiler_or_steam_use"])
            generator = _pj_from_mwh(source["generator_use"])
            flare = _pj_from_mwh(source.get("flare_or_spill", ""))
            residual = _pj_from_mwh(source["residual_or_unallocated"])
            balance = _pj_from_mwh(source["model_balance_residual"])
            accounted = mandatory + process + steam + generator + flare + residual
            status = "pass" if abs(balance) <= TOL_PJ else ("warning" if abs(balance) <= 1e-3 else "fail")
            rows.append(
                {
                    "configuration": config,
                    "carrier": carrier,
                    "generation_PJ_y": _fmt(generation),
                    "mandatory_self_use_PJ_y": _fmt(mandatory),
                    "process_use_PJ_y": _fmt(process),
                    "hsm_wbw_use_PJ_y": "",
                    "steam_boiler_use_PJ_y": _fmt(steam),
                    "generator_use_PJ_y": _fmt(generator),
                    "flare_spill_PJ_y": _fmt(flare),
                    "residual_PJ_y": _fmt(residual),
                    "accounted_total_PJ_y": _fmt(accounted),
                    "balance_residual_PJ_y": _fmt(balance),
                    "balance_status": status,
                    "source_stage_or_artifact": "C5p_e:c5_annual_flow_balance_by_carrier.csv",
                    "caveat": (
                        "Carrier-specific annual diagnostic; HSM/WBW is included in preparation/process use where upstream layers supplied it. "
                        "C5p_c generator flare is not always carrier-split in this table."
                    ),
                }
            )
            aggregates["generation"] += generation
            aggregates["mandatory"] += mandatory
            aggregates["process"] += process
            aggregates["steam"] += steam
            aggregates["generator"] += generator
            aggregates["residual"] += residual
            aggregates["balance"] += balance

        pc = pc_rows.get(config, {})
        aggregate_flare = _pj_from_mwh(pc.get("generator_flare_or_spill_MWh_LHV_y", ""))
        aggregate_residual_after_flare = _zero(pc.get("residual_WAG_after_generators_and_flare_PJ_y"))
        residual_for_aggregate = aggregate_residual_after_flare if pc else aggregates["residual"]
        aggregate_accounted = (
            aggregates["mandatory"]
            + aggregates["process"]
            + aggregates["steam"]
            + aggregates["generator"]
            + aggregate_flare
            + residual_for_aggregate
        )
        aggregate_balance = aggregates["generation"] - aggregate_accounted
        rows.append(
            {
                "configuration": config,
                "carrier": "aggregate_wag",
                "generation_PJ_y": _fmt(aggregates["generation"]),
                "mandatory_self_use_PJ_y": _fmt(aggregates["mandatory"]),
                "process_use_PJ_y": _fmt(aggregates["process"]),
                "hsm_wbw_use_PJ_y": "",
                "steam_boiler_use_PJ_y": _fmt(aggregates["steam"]),
                "generator_use_PJ_y": _fmt(aggregates["generator"]),
                "flare_spill_PJ_y": _fmt(aggregate_flare),
                "residual_PJ_y": _fmt(residual_for_aggregate),
                "accounted_total_PJ_y": _fmt(aggregate_accounted),
                "balance_residual_PJ_y": _fmt(aggregate_balance),
                "balance_status": "pass" if abs(aggregate_balance) <= 1e-5 else "warning",
                "source_stage_or_artifact": "C5p_e carrier sum plus C5p_c aggregate flare/residual",
                "caveat": "Reporting total only. This is not a physical generic WAG carrier and must not be used to hide carrier gaps.",
            }
        )
        rows.append(
            {
                "configuration": config,
                "carrier": "mixed_wag",
                "balance_status": "not_available",
                "source_stage_or_artifact": "S4.4b2 structural mixing rules; no quantitative mixer output in current C5p stack",
                "caveat": "Mixed WAG exists only as structural eligibility/gas-quality concept. No quantitative Wobbe/share-constrained mixer is accepted for Phase 1.",
            }
        )
    return rows


def _anchor_by_id() -> dict[str, dict[str, str]]:
    return {row["anchor_id"]: row for row in _read_csv(ANCHOR_REGISTER_PATH)}


def _anchor_row(
    *,
    config: str,
    carrier_or_metric: str,
    model_metric: str,
    model_value: float,
    model_unit: str,
    anchor: dict[str, str],
    comparison_basis: str,
    status: str,
    caveat: str,
) -> dict[str, Any]:
    anchor_value = _zero(anchor.get("converted_value") or anchor.get("raw_value"))
    raw_gap = model_value - anchor_value
    return {
        "configuration": config,
        "carrier_or_metric": carrier_or_metric,
        "model_metric": model_metric,
        "model_value": _fmt(model_value),
        "model_unit": model_unit,
        "anchor_id": anchor.get("anchor_id", ""),
        "anchor_value": _fmt(anchor_value),
        "anchor_unit": anchor.get("converted_unit") or anchor.get("raw_unit"),
        "anchor_source_rank": anchor.get("source_trust_rank", ""),
        "evidence_tier": anchor.get("evidence_tier", ""),
        "locator_quality": anchor.get("locator_quality", ""),
        "comparison_basis": comparison_basis,
        "raw_gap": _fmt(raw_gap),
        "normalised_gap": _fmt(_safe_div(raw_gap, anchor_value)),
        "comparison_status": status,
        "caveat": caveat,
    }


def _build_anchor_comparison(balance_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors = _anchor_by_id()
    pc = _pc_residual_rows()
    pc_alloc = _pc_alloc_rows()
    aggregate = {
        (row["configuration"], row["carrier"]): row
        for row in balance_rows
        if row["carrier"] == "aggregate_wag"
    }
    rows: list[dict[str, Any]] = []

    c0_pc = pc[C0]
    rows.append(
        _anchor_row(
            config=C0,
            carrier_or_metric="generator_electricity",
            model_metric="C0 residual-WAG-derived generator electricity offset",
            model_value=_zero(c0_pc["C0_generator_electricity_actual_MWh_e_y"]) / 1_000_000.0,
            model_unit="TWh/y",
            anchor=anchors["c0_residual_gas_electricity_2twh"],
            comparison_basis="Comparable as validation anchor only; not an equality target.",
            status="comparable",
            caveat="2.0 TWh remains validation-only and must not back-calculate generator fuel.",
        )
    )
    c0_agg_pj = _zero(aggregate[(C0, "aggregate_wag")]["generation_PJ_y"])
    rows.append(
        _anchor_row(
            config=C0,
            carrier_or_metric="aggregate_wag_generation",
            model_metric="Current C5 aggregate BFG+COG+BOFG generation",
            model_value=c0_agg_pj,
            model_unit="PJ/y",
            anchor=anchors["c0_product_gas_reuse_54pj"],
            comparison_basis="Partial context comparison only; 54 PJ product-gas reuse is not exact generator fuel or WAG generation.",
            status="partial",
            caveat="Product gas reuse is context only; boundary and sinks are not identical.",
        )
    )
    rows.append(
        _anchor_row(
            config=C0,
            carrier_or_metric="aggregate_wag_generation",
            model_metric="Current C5 aggregate BFG+COG+BOFG generation",
            model_value=c0_agg_pj / 3.6,
            model_unit="TWh_LHV/y",
            anchor=anchors["athan_table8_current_wag_2_74"],
            comparison_basis="Model-precedent comparison only; denominator and basis unresolved.",
            status="partial",
            caveat="Athanasiadis value is user-supplied model precedent, not official Tata truth.",
        )
    )

    c1_agg_pj = _zero(aggregate[(C1, "aggregate_wag")]["generation_PJ_y"])
    rows.append(
        _anchor_row(
            config=C1,
            carrier_or_metric="aggregate_wag_generation",
            model_metric="Current C5 aggregate BFG+COG+BOFG generation",
            model_value=c1_agg_pj / 3.6,
            model_unit="TWh_LHV/y",
            anchor=anchors["athan_table9_phase1_wag_1_23"],
            comparison_basis="Model-precedent comparison only; denominator and basis unresolved.",
            status="partial",
            caveat="Athanasiadis value is user-supplied model precedent, not official Tata truth.",
        )
    )

    c1_pc = pc[C1]
    c1_generator_total_with_flare = (
        _zero(c1_pc["WAG_to_generators_MWh_LHV_y"])
        + _zero(c1_pc["NG_to_generators_MWh_LHV_y"])
        + _zero(c1_pc["generator_flare_or_spill_MWh_LHV_y"])
    ) * MWH_TO_PJ
    rows.append(
        _anchor_row(
            config=C1,
            carrier_or_metric="generator_fuel_plus_flare",
            model_metric="C1 modelled generator fuel plus flare",
            model_value=c1_generator_total_with_flare,
            model_unit="PJ/y",
            anchor=anchors["c1_generator_total_with_flare_14_6"],
            comparison_basis="Annual validation comparison; not hourly dispatch schedule.",
            status="comparable",
            caveat="C1 generator fuel gap remains explicit and must not be hidden by generic WAG.",
        )
    )
    for unit, anchor_id in (("VN25", "c1_vn25_total_fuel_13_7"), ("IJ01", "c1_ij01_total_fuel_0_8")):
        row = pc_alloc[(C1, unit)]
        rows.append(
            _anchor_row(
                config=C1,
                carrier_or_metric=f"{unit}_total_fuel",
                model_metric=f"C1 {unit} modelled total fuel",
                model_value=_zero(row["total_fuel_allocated_PJ_y"]),
                model_unit="PJ/y",
                anchor=anchors[anchor_id],
                comparison_basis="Annual validation comparison; unit-specific current public anchor stronger than C0 split.",
                status="comparable",
                caveat="Gap is not filled by creating fuel; preserve source review.",
            )
        )
    rows.append(
        _anchor_row(
            config=C1,
            carrier_or_metric="generator_flare",
            model_metric="C1 generator flare/spill diagnostic",
            model_value=_zero(c1_pc["generator_flare_or_spill_MWh_LHV_y"]) * MWH_TO_PJ,
            model_unit="PJ/y",
            anchor=anchors["c1_generator_flare_0_1"],
            comparison_basis="Annual validation comparison; flare is not market value.",
            status="comparable",
            caveat="Carrier split of flare is not available in C5p_e carrier rows.",
        )
    )
    return rows


def _controller_rows() -> list[dict[str, str]]:
    return [
        {
            "function_or_module_name": "wag_diagnostic.allocate_process_first",
            "file_path": "scripts/Data/04_Steel_Test_Case/steel/wag_diagnostic.py",
            "purpose": "Process-first annual WAG allocation across mandatory process use, boiler fuel, power interface, flare/residual and NG boiler substitution.",
            "carriers_handled": "BFG;COG;BOFG_LD_gas;NG",
            "sinks_or_plants_affected": "hot stoves;coking;sinter;pellet;boiler;power interface;flare;residual",
            "input_artifacts": "wag_diagnostic_inputs selected WAG inputs and demand coefficients",
            "output_artifacts": "historical S3/S4 WAG diagnostic outputs where run",
            "priority_logic_if_any": "process-first then boiler then power interface then flare/residual",
            "allocation_mode": "carrier_specific",
            "current_C5_stage_use": "existing/parallel diagnostic surface; not confirmed as single C5p authoritative contract",
            "whether_C5p_k_bypassed_or_approximated": "yes",
            "risk_if_used_for_sensitivity": "Medium unless reconciled with newer C5p_b/C5p_c layer artifacts.",
            "recommended_action": "Audit against C5p_b/C5p_c residual artifacts before sensitivity execution.",
        },
        {
            "function_or_module_name": "wag_fixed_profile_builder fixed profile builders",
            "file_path": "scripts/Data/04_Steel_Test_Case/steel/wag_fixed_profile_builder.py",
            "purpose": "Build fixed WAG profile and mandatory process-use rows.",
            "carriers_handled": "BFG;COG;BOFG_LD_gas",
            "sinks_or_plants_affected": "hot stoves;coking underfiring;coking steam",
            "input_artifacts": "selected WAG inputs and activity profiles",
            "output_artifacts": "fixed profile frames when run",
            "priority_logic_if_any": "mandatory self-use/profile construction",
            "allocation_mode": "fixed_profile",
            "current_C5_stage_use": "upstream/historical; needs lineage check",
            "whether_C5p_k_bypassed_or_approximated": "yes",
            "risk_if_used_for_sensitivity": "Medium if mandatory self-use does not reconcile with current compact ledgers.",
            "recommended_action": "Compare fixed profile mandatory self-use to C5p_e process-use rows.",
        },
        {
            "function_or_module_name": "C5l_b HSM WAG dispatch controller",
            "file_path": "scripts/Data/04_Steel_Test_Case/steel/s4_4c5l_b_HSM_WAG_dispatch_controller_and_traceability_patch.py",
            "purpose": "Deterministic physical HSM reheat WAG allocation controller.",
            "carriers_handled": "BFG;COG;BOFG;NG",
            "sinks_or_plants_affected": "HSM/WBW reheat",
            "input_artifacts": "C5k WAG generation/consumption by plant; C5l_a HSM fuel rows",
            "output_artifacts": "s4_4c5l_b_hsm_reheat_controller_carrier_trace.csv; dashboard.csv",
            "priority_logic_if_any": "availability net of inherited KGF COG self-use and BF hot-stove deductions",
            "allocation_mode": "carrier_specific",
            "current_C5_stage_use": "active C5l diagnostic/controller surface",
            "whether_C5p_k_bypassed_or_approximated": "yes",
            "risk_if_used_for_sensitivity": "Low only after C5p_m confirms linkage to later residual artifacts.",
            "recommended_action": "Use as HSM-specific controller reference; do not replace with aggregate fallback.",
        },
        {
            "function_or_module_name": "C5l_d HSM hot-charge/reheat controller",
            "file_path": "scripts/Data/04_Steel_Test_Case/steel/s4_4c5l_d_hsm_hot_charge_share_cap_and_reheat_sensitivity_patch.py",
            "purpose": "HSM hot/cold slab reheat controller surface preserving base_0_50.",
            "carriers_handled": "BFG;COG;BOFG;NG",
            "sinks_or_plants_affected": "HSM/WBW hot and cold slab reheat cases",
            "input_artifacts": "C5l/c HSM controller artifacts",
            "output_artifacts": "s4_4c5l_d_hsm_reheat_controller_carrier_trace.csv; dashboard.csv",
            "priority_logic_if_any": "case-specific HSM reheat allocation",
            "allocation_mode": "carrier_specific",
            "current_C5_stage_use": "active accepted base_0_50 adjacent surface",
            "whether_C5p_k_bypassed_or_approximated": "yes",
            "risk_if_used_for_sensitivity": "Medium because this is a sensitivity surface; do not run new cases here.",
            "recommended_action": "Preserve current base and inspect output only.",
        },
        {
            "function_or_module_name": "C5m sinter gas/WAG controller",
            "file_path": "scripts/Data/04_Steel_Test_Case/steel/s4_4c5m_sinter_minimal_parameterisation.py",
            "purpose": "Shared eligibility-constrained HSM plus sinter WAG allocation dashboard.",
            "carriers_handled": "BFG;COG;BOFG;NG",
            "sinks_or_plants_affected": "HSM/WBW;sinter",
            "input_artifacts": "C5l_d HSM outputs and sinter gas assumptions",
            "output_artifacts": "s4_4c5m_sinter_gas_wag_controller_dashboard.csv; trace.csv",
            "priority_logic_if_any": "HSM and sinter controller balance with NG backup allowed",
            "allocation_mode": "carrier_specific",
            "current_C5_stage_use": "active current C5m diagnostic surface",
            "whether_C5p_k_bypassed_or_approximated": "yes",
            "risk_if_used_for_sensitivity": "Medium until linked to C5p_b/c annual flow rows.",
            "recommended_action": "Include in process-use lineage audit before NG residual phase.",
        },
        {
            "function_or_module_name": "C5p_b boiler/steam fuel allocator",
            "file_path": "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_b_boiler_steam_circuit_accounting.py",
            "purpose": "Annual demand-led boiler/steam WAG allocation after process use.",
            "carriers_handled": "BFG;COG;NG;BOFG blocked for steam",
            "sinks_or_plants_affected": "K15/K16;K23/K24;K41;STEG11;TG2 steam circuit",
            "input_artifacts": "C5m sinter and C5n_a PEFA gas outputs; C5p_b development rows",
            "output_artifacts": "s4_4c5p_b_boiler_fuel_allocation.csv; s4_4c5p_b_wag_residual_after_steam.csv",
            "priority_logic_if_any": "steam demand-led annual allocation; BOFG blocked without governed source row",
            "allocation_mode": "carrier_specific",
            "current_C5_stage_use": "active C5p_b",
            "whether_C5p_k_bypassed_or_approximated": "partly",
            "risk_if_used_for_sensitivity": "Low for reporting; parameter sensitivity still requires source review.",
            "recommended_action": "Use C5p_b residual-after-steam as authoritative steam-stage artifact.",
        },
        {
            "function_or_module_name": "C5p_c IJ01/VN25 generator interface allocator",
            "file_path": "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_c_ij01_vn25_generator_interface_accounting.py",
            "purpose": "Annual generator interface allocation from residual WAG after steam; C0 endogenous and C1 anchor-gap reporting.",
            "carriers_handled": "BFG;BOFG;COG;NG",
            "sinks_or_plants_affected": "VN25;IJ01;generator flare/spill;residual",
            "input_artifacts": "s4_4c5p_b_wag_residual_after_steam.csv",
            "output_artifacts": "s4_4c5p_c_generator_fuel_allocation.csv; s4_4c5p_c_wag_residual_after_generators.csv",
            "priority_logic_if_any": "residual after steam to generators; C1 annual anchor gaps reported not filled",
            "allocation_mode": "carrier_specific",
            "current_C5_stage_use": "active C5p_c",
            "whether_C5p_k_bypassed_or_approximated": "partly",
            "risk_if_used_for_sensitivity": "Low if validation-anchor role remains protected.",
            "recommended_action": "Use as generator-stage artifact; keep C1 generator gap explicit.",
        },
        {
            "function_or_module_name": "S4.4b2 structural WAG mixing rules",
            "file_path": "scripts/Data/04_Steel_Test_Case/steel/s4_4b2_physical_master_workbook.py",
            "purpose": "Structural carrier and sink eligibility rules for WAG buses and mixers.",
            "carriers_handled": "BFG;COG;BOFG;mixed_WAG",
            "sinks_or_plants_affected": "COK1;HSM;PEFA;boilers;STEG11;Vattenfall",
            "input_artifacts": "physical master workbook tables",
            "output_artifacts": "review/migration artifacts",
            "priority_logic_if_any": "structural eligibility only; quantitative gas-quality limits missing",
            "allocation_mode": "mixed_gas",
            "current_C5_stage_use": "governance reference",
            "whether_C5p_k_bypassed_or_approximated": "yes",
            "risk_if_used_for_sensitivity": "High if treated as quantitative mixer.",
            "recommended_action": "Use as eligibility checklist, not physical allocation contract.",
        },
        {
            "function_or_module_name": "C5p_k common-plant NG/WAG overlay",
            "file_path": "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_k_common_plant_ng_wag_overlay.py",
            "purpose": "Exploratory common-plant fuel diagnostic using aggregate residual-WAG fallback.",
            "carriers_handled": "aggregate_WAG;NG",
            "sinks_or_plants_affected": "HSM/WBW;KGF/coking",
            "input_artifacts": "C5p_i candidates; C5p_c compact health/residual diagnostics; C5p_g NG boundary",
            "output_artifacts": "common_plant_wag_ng_allocation.csv; warnings.csv",
            "priority_logic_if_any": "WAG-priority residual fallback",
            "allocation_mode": "aggregate",
            "current_C5_stage_use": "exploratory warning only",
            "whether_C5p_k_bypassed_or_approximated": "yes",
            "risk_if_used_for_sensitivity": "High; unsuitable as physical allocation evidence.",
            "recommended_action": "Exclude from physical interpretation; keep warning context only.",
        },
    ]


def _priority_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for config in CONFIGS:
        rows.extend(
            [
                {
                    "configuration": config,
                    "priority_order_candidate": "1_existing_process_or_preparation_use",
                    "source_or_function": "C5p_e annual flow balance with upstream C5l/C5m/C5n process controllers",
                    "sink": "process_preparation_HSM_sinter_PEFA",
                    "carrier": "BFG;COG;BOFG",
                    "is_explicit": "true",
                    "is_governed": "partial",
                    "is_diagnostic_only": "false",
                    "conflict_with_other_surface": "partial_unresolved_lineage",
                    "caveat": "C5p_e keeps carriers separate, but mandatory self-use and process-use sub-splits are not fully exposed in this Phase 1 matrix.",
                },
                {
                    "configuration": config,
                    "priority_order_candidate": "2_steam_boiler_use",
                    "source_or_function": "C5p_b boiler/steam fuel allocator",
                    "sink": "steam_boiler",
                    "carrier": "BFG;COG;NG;BOFG_blocked",
                    "is_explicit": "true",
                    "is_governed": "partial",
                    "is_diagnostic_only": "false",
                    "conflict_with_other_surface": "no",
                    "caveat": "Annual demand-led steam accounting; BOFG not allowed in steam layer without governed source row.",
                },
                {
                    "configuration": config,
                    "priority_order_candidate": "3_generator_interface",
                    "source_or_function": "C5p_c IJ01/VN25 generator interface allocator",
                    "sink": "generator_interface",
                    "carrier": "BFG;COG;BOFG;NG",
                    "is_explicit": "true",
                    "is_governed": "partial",
                    "is_diagnostic_only": "false",
                    "conflict_with_other_surface": "no",
                    "caveat": "C0 generator is residual-WAG-derived; C1 fuel gaps are reported and not filled.",
                },
                {
                    "configuration": config,
                    "priority_order_candidate": "4_flare_spill_residual",
                    "source_or_function": "C5p_c generator residual after flare/spill",
                    "sink": "flare_spill_residual",
                    "carrier": "aggregate_wag_for_flare_residual_reporting",
                    "is_explicit": "partial",
                    "is_governed": "partial",
                    "is_diagnostic_only": "true",
                    "conflict_with_other_surface": "missing_carrier_split",
                    "caveat": "C1 flare is visible but not carrier-split in C5p_e carrier rows.",
                },
                {
                    "configuration": config,
                    "priority_order_candidate": "not_contract_c5p_k_common_plant_overlay",
                    "source_or_function": "C5p_k aggregate residual-WAG fallback",
                    "sink": "common_plant_fuel_overlay",
                    "carrier": "aggregate_wag",
                    "is_explicit": "true",
                    "is_governed": "false",
                    "is_diagnostic_only": "true",
                    "conflict_with_other_surface": "yes",
                    "caveat": "Exploratory warning only; not accepted model-wide physical allocation contract.",
                },
            ]
        )
    return rows


def _warning_rows(balance_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    idx = 1
    for row in balance_rows:
        if row["balance_status"] in {"warning", "fail"}:
            warnings.append(
                {
                    "warning_id": f"WAG_WARN_{idx:03d}",
                    "severity": row["balance_status"],
                    "configuration": row["configuration"],
                    "carrier": row["carrier"],
                    "affected_sink_or_stage": "carrier_balance",
                    "issue_type": "balance_residual",
                    "message": f"Carrier balance residual is {row.get('balance_residual_PJ_y', '')} PJ/y.",
                    "evidence_artifact": row["source_stage_or_artifact"],
                    "recommended_action": "Review before sensitivity execution; do not floor residual away.",
                }
            )
            idx += 1
    for config in CONFIGS:
        warnings.extend(
            [
                {
                    "warning_id": f"WAG_WARN_{idx:03d}",
                    "severity": "warning",
                    "configuration": config,
                    "carrier": "aggregate_wag",
                    "affected_sink_or_stage": "C5p_k_common_plant_overlay",
                    "issue_type": "aggregate_fallback",
                    "message": "C5p_k uses aggregate residual-WAG fallback and is unsuitable as physical allocation evidence.",
                    "evidence_artifact": "common_plant_wag_ng_allocation.csv",
                    "recommended_action": "Keep C5p_k as warning context only; use existing controller surfaces for later physical interpretation.",
                },
                {
                    "warning_id": f"WAG_WARN_{idx+1:03d}",
                    "severity": "warning",
                    "configuration": config,
                    "carrier": "mixed_wag",
                    "affected_sink_or_stage": "model_wide_contract",
                    "issue_type": "missing_carrier_split",
                    "message": "No explicit common-plant WAG/NG ratio or quantitative mixed-gas split is available.",
                    "evidence_artifact": "C5p_k summary.json; S4.4b2 structural mixing rules",
                    "recommended_action": "Create a governed contract proposal before NG residual implementation or sensitivity execution.",
                },
            ]
        )
        idx += 2
    warnings.append(
        {
            "warning_id": f"WAG_WARN_{idx:03d}",
            "severity": "warning",
            "configuration": C1,
            "carrier": "COG",
            "affected_sink_or_stage": "generator_flare_residual",
            "issue_type": "missing_carrier_split",
            "message": "C1 generator flare is visible as an aggregate anchor, but current C5p_e carrier rows do not assign flare by carrier.",
            "evidence_artifact": "s4_4c5p_c_wag_residual_after_generators.csv",
            "recommended_action": "Keep aggregate flare/residual visible; do not infer carrier split silently.",
        }
    )
    warnings.append(
        {
            "warning_id": f"WAG_WARN_{idx+1:03d}",
            "severity": "warning",
            "configuration": "both",
            "carrier": "BFG;COG;BOFG",
            "affected_sink_or_stage": "CO2_boundary",
            "issue_type": "CO2_mode_mix_risk",
            "message": "Aggregate process CO2 counters and WAG/fuel-explicit combustion CO2 must remain separate.",
            "evidence_artifact": "C5p_h/C5p_i CO2 diagnostics",
            "recommended_action": "Do not implement WAG/fuel-explicit CO2 until carbon policy and factors are repaired.",
        }
    )
    return warnings


def _gap_rows() -> list[dict[str, str]]:
    return [
        {
            "gap_id": "WAG_GAP_001",
            "gap_type": "missing_contract",
            "affected_configuration": "both",
            "affected_carrier": "BFG;COG;BOFG;mixed_wag",
            "affected_sink": "model-wide",
            "current_status": "partial controller surfaces exist but no single authoritative allocation contract",
            "why_it_matters": "Later sensitivity and NG residual phases need one governed source of allocation truth.",
            "blocker_for_next_phase": "NG_residual;CO2;sensitivity;economics;DA",
            "recommended_fix_type": "governance_decision",
            "recommended_next_action": "Formalise a non-executable WAG controller contract proposal before using WAG allocation in sensitivities.",
        },
        {
            "gap_id": "WAG_GAP_002",
            "gap_type": "missing_ratio",
            "affected_configuration": "both",
            "affected_carrier": "aggregate_wag;NG",
            "affected_sink": "common_plant_fuel_overlay",
            "current_status": "C5p_k found no explicit common-plant WAG/NG ratio",
            "why_it_matters": "Common-plant NG residual can be understated if residual WAG is too fungible.",
            "blocker_for_next_phase": "NG_residual;sensitivity",
            "recommended_fix_type": "source_review",
            "recommended_next_action": "Search source cards/registers for explicit split evidence or record no-ratio fallback as blocked.",
        },
        {
            "gap_id": "WAG_GAP_003",
            "gap_type": "missing_mixer",
            "affected_configuration": "both",
            "affected_carrier": "mixed_wag",
            "affected_sink": "mixed-gas eligible sinks",
            "current_status": "structural eligibility exists; quantitative Wobbe/gas-quality mixer missing",
            "why_it_matters": "Usable WAG may be overestimated if all carriers are treated as interchangeable heat.",
            "blocker_for_next_phase": "sensitivity;CO2;economics;DA",
            "recommended_fix_type": "later_model_implementation",
            "recommended_next_action": "Keep mixed gas blocked until source-backed limits and governance are available.",
        },
        {
            "gap_id": "WAG_GAP_004",
            "gap_type": "missing_carrier_split",
            "affected_configuration": "C1",
            "affected_carrier": "COG_or_aggregate_wag",
            "affected_sink": "generator_flare",
            "current_status": "flare anchor and residual are aggregate, not carrier split",
            "why_it_matters": "Carrier-specific CO2 and WAG residual comparisons cannot assign flare without evidence.",
            "blocker_for_next_phase": "CO2;sensitivity",
            "recommended_fix_type": "reporting_patch",
            "recommended_next_action": "Report flare as aggregate until a governed carrier split is reviewed.",
        },
        {
            "gap_id": "WAG_GAP_005",
            "gap_type": "conflict",
            "affected_configuration": "both",
            "affected_carrier": "aggregate_wag",
            "affected_sink": "C5p_k common plant fuel",
            "current_status": "C5p_k reallocates existing residual WAG before generator accounting for diagnostics",
            "why_it_matters": "This can conflict with generator and steam residual ledgers if treated as physical truth.",
            "blocker_for_next_phase": "NG_residual;sensitivity",
            "recommended_fix_type": "existing_function_reuse",
            "recommended_next_action": "Exclude C5p_k allocation from physical interpretation; use it only as warning context.",
        },
        {
            "gap_id": "WAG_GAP_006",
            "gap_type": "missing_anchor",
            "affected_configuration": "both",
            "affected_carrier": "BFG;COG;BOFG",
            "affected_sink": "carrier-specific WAG generation and availability",
            "current_status": "some Rank 1 and Rank 3 anchors exist, but denominator/boundary/locator remain partial",
            "why_it_matters": "Carrier scoring cannot be primary until comparable anchors are selected.",
            "blocker_for_next_phase": "sensitivity",
            "recommended_fix_type": "source_review",
            "recommended_next_action": "Use anchor comparisons as partial diagnostics only; do not force model values.",
        },
    ]


def _stage_gate() -> dict[str, Any]:
    return {
        "stage": STAGE,
        "status": "development_only_diagnostic",
        "sensitivity_experiment_run": False,
        "model_equations_changed": False,
        "executable_development_inputs_changed": False,
        "source_cards_changed": False,
        "new_wag_allocation_function_created": False,
        "anchors_used_as_constraints": False,
        "c5p_k_physical_allocation_evidence": False,
        "c5p_k_exploratory_warning_only": True,
        "aggregate_residual_wag_fallback_accepted_as_physics": False,
        "model_wide_wag_allocation_contract_exists": "partial_no_single_authoritative_contract",
        "thesis_usability": False,
        "economics_ready": False,
        "da_ready": False,
    }


def _summary(
    balance_rows: list[dict[str, Any]],
    controller_rows: list[dict[str, str]],
    warnings: list[dict[str, str]],
    gaps: list[dict[str, str]],
) -> dict[str, Any]:
    balance_counts = {"pass": 0, "warning": 0, "fail": 0, "not_available": 0}
    for row in balance_rows:
        balance_counts[row["balance_status"]] = balance_counts.get(row["balance_status"], 0) + 1
    aggregates = {
        row["configuration"]: {
            "generation_PJ_y": _zero(row["generation_PJ_y"]),
            "steam_boiler_use_PJ_y": _zero(row["steam_boiler_use_PJ_y"]),
            "generator_use_PJ_y": _zero(row["generator_use_PJ_y"]),
            "flare_spill_PJ_y": _zero(row["flare_spill_PJ_y"]),
            "residual_PJ_y": _zero(row["residual_PJ_y"]),
        }
        for row in balance_rows
        if row["carrier"] == "aggregate_wag"
    }
    return {
        "stage": STAGE,
        "status": "development_only_diagnostic",
        "thesis_usability": False,
        "carriers_checked": ["BFG", "BOFG", "COG", "aggregate_wag", "mixed_wag"],
        "controller_surfaces_found": len(controller_rows),
        "balance_status_counts": balance_counts,
        "double_counting_warning_count": len([row for row in warnings if row["issue_type"] == "possible_double_count"]),
        "warning_count": len(warnings),
        "contract_gap_count": len(gaps),
        "aggregate_balance_metrics": aggregates,
        "c5p_k_remains_exploratory_only": True,
        "model_wide_wag_allocation_contract_exists": "partial_no_single_authoritative_contract",
        "top_blockers": [
            "missing model-wide WAG allocation contract",
            "missing common-plant WAG/NG ratio",
            "missing quantitative mixed-gas/Wobbe controller",
            "C5p_k aggregate fallback conflicts with physical interpretation",
            "C1 flare carrier split missing",
        ],
        "go_no_go": {
            "electricity_non_wag_decomposition": "GO_WITH_WAG_CAVEAT",
            "WAG_dependent_electricity_interpretation": "NO_GO_UNTIL_CONTRACT_AUDIT",
            "NG_residual_policy": "NO_GO_UNTIL_AGGREGATE_FALLBACK_REMOVED_FROM_PHYSICAL_INTERPRETATION",
            "CO2_site_level_residual_reporting": "GO_DIAGNOSTIC_ONLY",
            "WAG_fuel_explicit_CO2": "NO_GO",
            "full_sensitivity_execution": "NO_GO",
            "economics_readiness": "NO_GO",
            "DA_readiness": "NO_GO",
        },
    }


def _write_report(
    balance_rows: list[dict[str, Any]],
    anchor_rows: list[dict[str, Any]],
    warnings: list[dict[str, str]],
    gaps: list[dict[str, str]],
    summary: dict[str, Any],
) -> None:
    aggregates = {row["configuration"]: row for row in balance_rows if row["carrier"] == "aggregate_wag"}
    c0 = aggregates[C0]
    c1 = aggregates[C1]
    report = f"""# C5 WAG Balance and Controller Contract

## A. Purpose and boundaries

This is the Phase 1 WAG diagnostic for `S4.4c5p_m_wag_balance_and_controller_contract`. It is not a sensitivity run and does not change model equations, executable development inputs, source cards, objectives, residual-load logic, economics, DA, CO2 objectives, or dispatch behaviour.

C5p_k remains exploratory warning evidence only. It used aggregate residual WAG and may bypass existing WAG/controller/mixing surfaces, so it is not accepted as physical WAG allocation evidence.

Anchors are validation/reporting objects, not constraints.

## B. Current WAG balance by configuration and carrier

Carrier-specific rows are preserved from C5p_e where available. Values below are aggregate reporting totals in PJ/y and must not be interpreted as a physical generic WAG carrier.

| Configuration | WAG generated | Process/prep use | Steam/boiler use | Generator use | Flare/spill | Residual after flare | Balance status |
|---|---:|---:|---:|---:|---:|---:|---|
| C0 | {c0['generation_PJ_y']} | {c0['process_use_PJ_y']} | {c0['steam_boiler_use_PJ_y']} | {c0['generator_use_PJ_y']} | {c0['flare_spill_PJ_y']} | {c0['residual_PJ_y']} | {c0['balance_status']} |
| C1 | {c1['generation_PJ_y']} | {c1['process_use_PJ_y']} | {c1['steam_boiler_use_PJ_y']} | {c1['generator_use_PJ_y']} | {c1['flare_spill_PJ_y']} | {c1['residual_PJ_y']} | {c1['balance_status']} |

The current annual C5p_e carrier rows close arithmetically. The remaining issue is not basic arithmetic closure; it is the absence of a single governed model-wide allocation contract tying process controllers, HSM/sinter/PEFA, steam, generator, flare and common-plant overlays together.

Mixed WAG is not available as a quantitative carrier in this phase. It remains structural eligibility only.

## C. WAG anchor comparison

The `wag_anchor_comparison.csv` file compares only where current anchors are sufficiently interpretable:

- C0 generator electricity: current model is about 2.067665 TWh/y versus 2.0 TWh/y validation anchor.
- C0 product gas reuse 54 PJ/y: partial context only, not exact generator fuel or WAG generation.
- C1 generator preferred fuel and flare anchors: comparable as annual validation, with gap still explicit.
- Athanasiadis WAG generation anchors: model-precedent only; denominator and basis unresolved.

No anchor is used as a constraint or dispatch target.

## D. Existing controller/allocation surfaces

The dependency map records {len(summary['carriers_checked'])} carrier classes and {summary['controller_surfaces_found']} controller/allocation surfaces. Key surfaces are:

- `wag_diagnostic.allocate_process_first`
- `wag_fixed_profile_builder`
- C5l HSM/WBW WAG controllers
- C5m sinter gas/WAG controller
- C5p_b boiler/steam WAG allocator
- C5p_c generator interface allocator
- S4.4b2 structural WAG mixing rules
- C5p_k common-plant overlay as exploratory warning only

These pieces are useful, but they do not yet constitute one authoritative model-wide WAG allocation contract.

## E. Does a model-wide WAG contract exist?

Decision: partial / no single authoritative contract.

Pieces exist: carrier-specific annual balances, HSM/sinter controller surfaces, boiler/steam allocation, generator allocation, and structural mixing eligibility. Missing pieces are the contract that defines precedence and interoperability between them, an explicit common-plant WAG/NG split, and quantitative mixed-gas quality constraints.

Later sensitivities must first create a governed non-executable contract proposal or explicitly call the accepted existing controller outputs. This task does not create that contract as executable logic.

## F. C5p_k status review

C5p_k remains unsuitable as physical WAG allocation evidence. It:

- used aggregate residual WAG;
- did not find an explicit common-plant WAG/NG ratio;
- can bypass or approximate HSM/steam/generator controller surfaces if treated physically;
- may reallocate WAG already accounted for in generator-interface diagnostics.

It can be reused only as warning/context evidence.

## G. WAG error-mode classification

Top warnings in this phase:

- C5p_k aggregate fallback should not be promoted to physics.
- Common-plant carrier split and WAG/NG ratios are missing.
- Mixed WAG has structural eligibility but no quantitative mixer.
- C1 generator flare is aggregate, not carrier-split.
- WAG/fuel-explicit CO2 remains blocked by carbon accounting policy and factor source repair.

`wag_double_counting_warnings.csv` and `wag_contract_gap_register.csv` contain the machine-readable warning and gap rows.

## H. Phase 1 decision gate

| Gate | Decision |
|---|---|
| WAG balance sufficient for non-WAG electricity decomposition | GO_WITH_WAG_CAVEAT |
| WAG-dependent electricity interpretation | NO-GO until controller contract audit |
| NG residual policy | NO-GO until aggregate WAG fallback is removed from physical interpretation |
| CO2 site-level residual reporting | GO_DIAGNOSTIC_ONLY |
| WAG/fuel-explicit CO2 | NO-GO |
| Full sensitivity execution | NO-GO |
| Economics / DA readiness | NO-GO |

## I. Recommended next action

Proceed to electricity boundary decomposition for non-WAG loads in parallel, but keep all WAG-dependent electricity interpretation caveated. Before NG residual policy, WAG/fuel-explicit CO2, or sensitivity execution, create a governed WAG controller contract proposal that reconciles C5l/C5m process controllers, C5p_b steam, C5p_c generators, flare/residual handling, and C5p_k warning context.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def run_s4_4c5p_m_wag_balance_and_controller_contract() -> dict[str, Any]:
    C5P_M_DIR.mkdir(parents=True, exist_ok=True)
    balance_rows = _build_balance_rows()
    anchor_rows = _build_anchor_comparison(balance_rows)
    controller_rows = _controller_rows()
    priority_rows = _priority_rows()
    warnings = _warning_rows(balance_rows)
    gaps = _gap_rows()
    summary = _summary(balance_rows, controller_rows, warnings, gaps)

    _write_csv(C5P_M_DIR / "wag_carrier_balance_matrix.csv", balance_rows, BALANCE_COLUMNS)
    _write_csv(C5P_M_DIR / "wag_anchor_comparison.csv", anchor_rows, ANCHOR_COLUMNS)
    _write_csv(C5P_M_DIR / "wag_controller_dependency_map.csv", controller_rows, CONTROLLER_COLUMNS)
    _write_csv(C5P_M_DIR / "wag_sink_priority_matrix.csv", priority_rows, PRIORITY_COLUMNS)
    _write_csv(C5P_M_DIR / "wag_double_counting_warnings.csv", warnings, WARNING_COLUMNS)
    _write_csv(C5P_M_DIR / "wag_contract_gap_register.csv", gaps, GAP_COLUMNS)
    _write_json(C5P_M_DIR / "summary.json", summary)
    _write_json(C5P_M_DIR / "s4_4c5p_m_stage_gate.json", _stage_gate())
    _write_report(balance_rows, anchor_rows, warnings, gaps, summary)
    return summary


def main() -> int:
    run_s4_4c5p_m_wag_balance_and_controller_contract()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
