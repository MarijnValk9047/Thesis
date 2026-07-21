"""S4.4c5p_u annual WAG-explicit CO2 anchor reconciliation.

This diagnostic does not change fuel allocation, production, executable inputs
or model equations.  It assembles the existing 24-hour C5p_t controller ledger
into a point-of-oxidation WAG CO2 subtotal, compares that subtotal against
site-level validation anchors and keeps every remaining gap visible.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import S4_ROOT, _read_csv, _write_csv, _write_json


STAGE = "S4.4c5p_u_wag_explicit_co2_anchor_reconciliation"
OUTPUT_DIR = S4_ROOT / "s4_4c5p_u_wag_explicit_co2_anchor_reconciliation"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_WAG_EXPLICIT_CO2_ANCHOR_RECONCILIATION.md")

C5P_T_DIR = S4_ROOT / "s4_4c5p_t_horizon_and_gross_net_boundary_bridge"
C5P_H_DIR = S4_ROOT / "s4_4c5p_h_co2_and_plant_energy_anchor_boundary_diagnostics"
C5P_G_DIR = S4_ROOT / "s4_4c5p_g_residual_electricity_ng_boundary_diagnostics"
ANCHOR_REGISTER_PATH = S4_ROOT / "c5_model_anchor_register" / "c5_model_anchor_evidence_register.csv"
S3_WAG_INPUT_PATH = S4_ROOT.parent / "S3" / "s3_provisional_dev_input" / "s3_wag_selected_dev_inputs.csv"

CONFIGS = ("C0_current_BF_BOF_reference", "C1_phase1_BF_BOF_plus_DRP_EAF")
CONFIG_TO_REGISTER = {
    "C0_current_BF_BOF_reference": "C0",
    "C1_phase1_BF_BOF_plus_DRP_EAF": "C1",
}
WAG_CARRIERS = ("BFG", "COG", "BOFG")
MT_PER_T = 1_000_000.0

MODE_COLUMNS = [
    "configuration",
    "co2_mode",
    "wag_explicit_co2_mt_y",
    "non_wag_process_co2_mt_y",
    "accounted_co2_mt_y",
    "scope1_anchor_mt_y",
    "residual_to_scope1_anchor_mt_y",
    "accounted_share_of_scope1_anchor",
    "comparison_status",
    "caveat",
]
POLICY_COLUMNS = [
    "component",
    "configuration_scope",
    "treatment_in_wag_explicit_mode",
    "may_be_added_to_wag_explicit_total",
    "reason",
    "current_source_or_stage",
    "caveat",
]
ANCHOR_COLUMNS = [
    "configuration",
    "anchor_id",
    "anchor_name",
    "anchor_value_mt_y",
    "anchor_role",
    "source_rank",
    "comparison_mode",
    "gap_to_wag_explicit_mt_y",
    "comparison_status",
    "caveat",
]
RESIDUAL_COLUMNS = [
    "configuration",
    "metric",
    "modelled_value",
    "unit",
    "anchor_value",
    "anchor_unit",
    "residual_to_anchor",
    "residual_status",
    "active_as_model_load_or_allocation",
    "caveat",
]
WAG_LEDGER_COLUMNS = [
    "configuration",
    "sink_or_controller",
    "carrier",
    "allocation_MWh_LHV_y",
    "allocation_GJ_LHV_y",
    "emission_factor_kgCO2_per_GJ",
    "wag_point_of_oxidation_co2_t_y",
    "source_stage",
    "ledger_status",
    "caveat",
]
WARNING_COLUMNS = ["warning_id", "configuration", "severity", "message", "recommended_action"]
VALIDATION_COLUMNS = ["check_id", "check_name", "status", "evidence", "recommended_action"]


def _as_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _fmt(value: float | str | None, digits: int = 6) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value
    if math.isclose(value, 0.0, abs_tol=1e-12):
        return "0"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Required C5p_u input is missing: {path}")
    return _read_csv(path)


def _wag_factors() -> dict[str, float]:
    parameter_to_carrier = {
        "bfg_combustion_factor_netherlands": "BFG",
        "cog_combustion_factor_netherlands": "COG",
        "oxygas_bofg_combustion_factor_netherlands": "BOFG",
    }
    factors: dict[str, float] = {}
    for row in _rows(S3_WAG_INPUT_PATH):
        carrier = parameter_to_carrier.get(row.get("parameter_name", ""))
        if carrier is None:
            continue
        if row.get("accepted_for_dev_use") != "true" or row.get("energy_basis") != "LHV_energy":
            raise ValueError(f"Unsafe WAG CO2 factor row for {carrier}.")
        factors[carrier] = _as_float(row.get("selected_value"))
    if set(factors) != set(WAG_CARRIERS):
        raise ValueError("The governed BFG/COG/BOFG factor set is incomplete.")
    return factors


def _anchor_map() -> dict[str, dict[str, dict[str, str]]]:
    wanted = {
        "c0_official_scope1_12_6_missing",
        "c1_official_scope1_8_3_missing",
        "athan_table8_current_co2_13_365",
        "athan_table9_phase1_co2_9_108",
        "c0_full_site_ng_12_5pj_missing",
        "c1_full_site_ng_46_5pj_missing",
        "c0_official_total_site_electricity_13_7pj_missing",
        "c1_official_total_site_electricity_17_8pj_missing",
    }
    return {row["anchor_id"]: {"row": row} for row in _rows(ANCHOR_REGISTER_PATH) if row["anchor_id"] in wanted}


def _wag_ledger() -> tuple[list[dict[str, str]], dict[str, float]]:
    factors = _wag_factors()
    ledger: list[dict[str, str]] = []
    totals = {configuration: 0.0 for configuration in CONFIGS}
    for row in _rows(C5P_T_DIR / "controller_mix_24h_contract_candidate.csv"):
        carrier = row["carrier"]
        if carrier not in factors:
            continue
        energy_mwh = _as_float(row["allocation_MWh_LHV_y"])
        energy_gj = energy_mwh * 3.6
        co2_t = energy_gj * factors[carrier] / 1000.0
        totals[row["configuration"]] += co2_t
        ledger.append(
            {
                "configuration": row["configuration"],
                "sink_or_controller": row["sink_or_controller"],
                "carrier": carrier,
                "allocation_MWh_LHV_y": _fmt(energy_mwh),
                "allocation_GJ_LHV_y": _fmt(energy_gj),
                "emission_factor_kgCO2_per_GJ": _fmt(factors[carrier]),
                "wag_point_of_oxidation_co2_t_y": _fmt(co2_t),
                "source_stage": "C5p_t 24-hour candidate contract ledger",
                "ledger_status": "represented_carrier_specific_sink_only",
                "caveat": "No NG, aggregate process counter, residual energy term, Scope 2 or carrier-unsplit C1 flare is included.",
            }
        )
    return ledger, totals


def _component_policy() -> list[dict[str, str]]:
    return [
        {
            "component": "BFG/COG/BOFG combustion or carrier-split flare",
            "configuration_scope": "both",
            "treatment_in_wag_explicit_mode": "include once at represented oxidation sink",
            "may_be_added_to_wag_explicit_total": "yes",
            "reason": "Selected RVO factors and carrier-specific C5p_t rows are available.",
            "current_source_or_stage": "S3 selected WAG inputs; C5p_t",
            "caveat": "C1 aggregate flare remains excluded because its carrier split is unknown.",
        },
        {
            "component": "PEFA aggregate diagnostic CO2",
            "configuration_scope": "both",
            "treatment_in_wag_explicit_mode": "exclude",
            "may_be_added_to_wag_explicit_total": "no",
            "reason": "PEFA fuel is now represented through BOFG/COG controller rows; aggregate PEFA risks double counting.",
            "current_source_or_stage": "C5p_h component inventory; C5p_t PEFA controller",
            "caveat": "Keep as a separate historical component diagnostic only.",
        },
        {
            "component": "BF/BOF/KGF aggregate CO2 candidates",
            "configuration_scope": "both",
            "treatment_in_wag_explicit_mode": "exclude",
            "may_be_added_to_wag_explicit_total": "no",
            "reason": "These counters include carbon that may later appear as BFG/BOFG/COG oxidation.",
            "current_source_or_stage": "C5p_h component inventory",
            "caveat": "Do not add until a complete alternative carbon boundary is frozen.",
        },
        {
            "component": "EAF aggregate midpoint CO2",
            "configuration_scope": "C1 only",
            "treatment_in_wag_explicit_mode": "separate optional non-WAG context mode",
            "may_be_added_to_wag_explicit_total": "caveated",
            "reason": "EAF has no WAG fuel carrier in the current route; it does not overlap with the WAG ledger.",
            "current_source_or_stage": "C5p_h component inventory",
            "caveat": "Range-midpoint diagnostic only; not a full direct-emissions component or ETS input.",
        },
        {
            "component": "DRP capture stream",
            "configuration_scope": "C1 only",
            "treatment_in_wag_explicit_mode": "report separately",
            "may_be_added_to_wag_explicit_total": "no",
            "reason": "Capture stream is not a direct-emission total.",
            "current_source_or_stage": "C5p_h component inventory",
            "caveat": "Never subtract automatically from Scope 1 without a governed capture-and-sink boundary.",
        },
        {
            "component": "NG and electricity residuals",
            "configuration_scope": "both",
            "treatment_in_wag_explicit_mode": "track only",
            "may_be_added_to_wag_explicit_total": "no",
            "reason": "Residuals represent unresolved site boundary coverage, not allocated fuel or load.",
            "current_source_or_stage": "C5p_g residual diagnostics",
            "caveat": "No inferred NG combustion or Scope 2 is added.",
        },
    ]


def _eaf_non_wag_component() -> dict[str, float]:
    values = {configuration: 0.0 for configuration in CONFIGS}
    for row in _rows(C5P_H_DIR / "c5_co2_component_inventory.csv"):
        if row["component"] == "EAF_midpoint_CO2":
            values[row["configuration"]] = _as_float(row["co2_model_output_mt_y"])
    return values


def _modes(wag_totals_t: dict[str, float], anchors: dict[str, dict[str, dict[str, str]]]) -> list[dict[str, str]]:
    scope_anchor_ids = {
        "C0_current_BF_BOF_reference": "c0_official_scope1_12_6_missing",
        "C1_phase1_BF_BOF_plus_DRP_EAF": "c1_official_scope1_8_3_missing",
    }
    eaf = _eaf_non_wag_component()
    rows: list[dict[str, str]] = []
    for configuration in CONFIGS:
        scope = _as_float(anchors[scope_anchor_ids[configuration]]["row"]["converted_value"])
        wag_mt = wag_totals_t[configuration] / MT_PER_T
        for mode, non_wag_mt, caveat in (
            (
                "wag_explicit_represented_only",
                0.0,
                "Partial WAG-only ledger: represented BFG/COG/BOFG oxidation; excludes all residuals and non-WAG components.",
            ),
            (
                "wag_explicit_plus_eaf_non_wag_context",
                eaf[configuration],
                "Adds only EAF's non-WAG aggregate midpoint where present; still partial, not ETS-ready and not a consolidated site total.",
            ),
        ):
            accounted = wag_mt + non_wag_mt
            residual = scope - accounted
            rows.append(
                {
                    "configuration": configuration,
                    "co2_mode": mode,
                    "wag_explicit_co2_mt_y": _fmt(wag_mt),
                    "non_wag_process_co2_mt_y": _fmt(non_wag_mt),
                    "accounted_co2_mt_y": _fmt(accounted),
                    "scope1_anchor_mt_y": _fmt(scope),
                    "residual_to_scope1_anchor_mt_y": _fmt(residual),
                    "accounted_share_of_scope1_anchor": _fmt(accounted / scope if scope else 0.0),
                    "comparison_status": "partial_validation_only",
                    "caveat": caveat,
                }
            )
    return rows


def _anchor_comparisons(wag_totals_t: dict[str, float], anchors: dict[str, dict[str, dict[str, str]]]) -> list[dict[str, str]]:
    mapping = {
        "C0_current_BF_BOF_reference": ("c0_official_scope1_12_6_missing", "athan_table8_current_co2_13_365"),
        "C1_phase1_BF_BOF_plus_DRP_EAF": ("c1_official_scope1_8_3_missing", "athan_table9_phase1_co2_9_108"),
    }
    rows: list[dict[str, str]] = []
    for configuration, ids in mapping.items():
        wag_mt = wag_totals_t[configuration] / MT_PER_T
        for anchor_id in ids:
            anchor = anchors[anchor_id]["row"]
            value = _as_float(anchor["converted_value"])
            is_official = anchor_id.startswith(("c0_official", "c1_official"))
            rows.append(
                {
                    "configuration": configuration,
                    "anchor_id": anchor_id,
                    "anchor_name": anchor["anchor_name"],
                    "anchor_value_mt_y": _fmt(value),
                    "anchor_role": anchor["anchor_role"],
                    "source_rank": anchor["source_trust_rank"],
                    "comparison_mode": "site_residual_validation" if is_official else "raw_model_precedent_context_only",
                    "gap_to_wag_explicit_mt_y": _fmt(value - wag_mt),
                    "comparison_status": "partial_validation_only" if is_official else "not_scaled_not_scored",
                    "caveat": anchor["caveat"],
                }
            )
    return rows


def _residual_kpis(anchors: dict[str, dict[str, dict[str, str]]]) -> list[dict[str, str]]:
    electricity = {row["configuration"]: row for row in _rows(C5P_G_DIR / "c5_residual_electricity_boundary_matrix.csv")}
    ng = {row["configuration"]: row for row in _rows(C5P_G_DIR / "c5_residual_ng_boundary_matrix.csv")}
    electricity_ids = {
        "C0_current_BF_BOF_reference": "c0_official_total_site_electricity_13_7pj_missing",
        "C1_phase1_BF_BOF_plus_DRP_EAF": "c1_official_total_site_electricity_17_8pj_missing",
    }
    ng_ids = {
        "C0_current_BF_BOF_reference": "c0_full_site_ng_12_5pj_missing",
        "C1_phase1_BF_BOF_plus_DRP_EAF": "c1_full_site_ng_46_5pj_missing",
    }
    rows: list[dict[str, str]] = []
    for configuration in CONFIGS:
        electric_modelled = _as_float(electricity[configuration]["gross_modelled_process_demand_twh"])
        electric_anchor_pj = _as_float(anchors[electricity_ids[configuration]]["row"]["converted_value"])
        electric_anchor_twh = electric_anchor_pj / 3.6
        rows.append(
            {
                "configuration": configuration,
                "metric": "gross_electricity_boundary_residual",
                "modelled_value": _fmt(electric_modelled),
                "unit": "TWh/y",
                "anchor_value": _fmt(electric_anchor_twh),
                "anchor_unit": "TWh/y",
                "residual_to_anchor": _fmt(electric_anchor_twh - electric_modelled),
                "residual_status": "visible_partial_provenance_kpi",
                "active_as_model_load_or_allocation": "false",
                "caveat": "Gross-demand comparison only; generator/internal offsets remain separate and no residual electricity load is added.",
            }
        )
        ng_modelled = _as_float(ng[configuration]["total_modelled_ng_pj"])
        ng_anchor = _as_float(anchors[ng_ids[configuration]]["row"]["converted_value"])
        rows.append(
            {
                "configuration": configuration,
                "metric": "full_site_NG_boundary_residual",
                "modelled_value": _fmt(ng_modelled),
                "unit": "PJ/y",
                "anchor_value": _fmt(ng_anchor),
                "anchor_unit": "PJ/y",
                "residual_to_anchor": _fmt(ng_anchor - ng_modelled),
                "residual_status": "visible_partial_provenance_kpi",
                "active_as_model_load_or_allocation": "false",
                "caveat": "No residual NG is allocated, combusted or costed; exact public locator remains open.",
            }
        )
    return rows


def _warnings() -> list[dict[str, str]]:
    return [
        {
            "warning_id": "U_WARN_001",
            "configuration": "both",
            "severity": "high",
            "message": "WAG-explicit CO2 is a represented-sink subtotal, not a full-site Scope 1 total.",
            "recommended_action": "Report the residual to the Scope 1 anchor; do not fill it with inferred process or residual fuel emissions.",
        },
        {
            "warning_id": "U_WARN_002",
            "configuration": "both",
            "severity": "high",
            "message": "BF, BOF, KGF and PEFA aggregate counters are excluded to prevent WAG-carbon double counting.",
            "recommended_action": "Keep aggregate-process mode separate from point-of-oxidation WAG mode.",
        },
        {
            "warning_id": "U_WARN_003",
            "configuration": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "severity": "medium",
            "message": "C1 flare is known only in aggregate and has no carrier split, so no flare CO2 is inferred.",
            "recommended_action": "Retain as an explicit missing-coverage warning until a carrier split exists.",
        },
        {
            "warning_id": "U_WARN_004",
            "configuration": "both",
            "severity": "medium",
            "message": "Full-site electricity, NG and Scope 1 anchors retain partial provenance and are validation-only.",
            "recommended_action": "Use for residual reporting, not primary scoring or executable constraints, until exact locators are confirmed.",
        },
    ]


def _validations(modes: list[dict[str, str]], ledger: list[dict[str, str]], residuals: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "check_id": "U_CHECK_001",
            "check_name": "WAG_explicit_ledger_is_carrier_specific",
            "status": "pass" if {row["carrier"] for row in ledger} <= set(WAG_CARRIERS) else "fail",
            "evidence": "C5p_t controller rows and S3 factor set use BFG, COG and BOFG only.",
            "recommended_action": "Keep mixed_wag and aggregate_wag out of physical CO2 rows.",
        },
        {
            "check_id": "U_CHECK_002",
            "check_name": "no_aggregate_process_counter_in_WAG_mode",
            "status": "pass",
            "evidence": "Component policy excludes PEFA, BF, BOF and KGF aggregate counters from WAG-explicit modes.",
            "recommended_action": "Do not consolidate accounting modes.",
        },
        {
            "check_id": "U_CHECK_003",
            "check_name": "residuals_are_visible_and_not_activated",
            "status": "pass" if all(row["active_as_model_load_or_allocation"] == "false" for row in residuals) else "fail",
            "evidence": "Residual KPI rows retain the raw gap to source anchors.",
            "recommended_action": "Keep residual electricity and NG as reporting-only boundary diagnostics.",
        },
        {
            "check_id": "U_CHECK_004",
            "check_name": "Scope1_residuals_retain_sign",
            "status": "pass" if all(_as_float(row["residual_to_scope1_anchor_mt_y"]) >= 0.0 for row in modes) else "warning",
            "evidence": "Residuals are calculated as anchor minus accounted subtotal without flooring.",
            "recommended_action": "Investigate any future negative residual as a coverage or double-counting warning.",
        },
        {
            "check_id": "U_CHECK_005",
            "check_name": "no_ETS_or_economics_unlock",
            "status": "pass",
            "evidence": "All output modes are partial validation diagnostics; no prices or ETS terms are read.",
            "recommended_action": "Keep ETS, economics and DA blocked.",
        },
    ]


def _file_record(path: Path) -> dict[str, str]:
    return {
        "path": str(path),
        "status": "read" if path.exists() else "missing",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "",
    }


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _write_report(summary: dict[str, Any]) -> None:
    totals = summary["wag_explicit_co2_mt_y"]
    report = f"""# C5 WAG-Explicit CO2 Anchor Reconciliation

## Purpose

C5p_u is an annual, diagnostic-only reconciliation. It books represented
BFG/COG/BOFG oxidation once at existing C5p_t controller sinks, compares the
subtotal with C0/C1 Scope 1 validation anchors and retains the remainder as a
visible boundary residual. It does not allocate residual electricity or NG,
change fuel allocation, or create an ETS/economics layer.

## Result

- C0 represented WAG-explicit subtotal: {totals['C0_current_BF_BOF_reference']:.6f} MtCO2/y.
- C1 represented WAG-explicit subtotal: {totals['C1_phase1_BF_BOF_plus_DRP_EAF']:.6f} MtCO2/y.

These subtotals use the coherent 24-hour C5p_t candidate contract ledger, not
C5p_q's historical 168-hour partial compilation. PEFA's carrier-specific
controller use is therefore represented. Carrier-unsplit C1 flare, residual
NG, residual electricity, Scope 2, DRP capture and aggregate BF/BOF/KGF/PEFA
counters are excluded.

## Carbon-boundary policy

The WAG-explicit mode is point-of-oxidation accounting. It is mutually
exclusive with aggregate process counters that contain the same WAG carbon.
The optional EAF context row is reported separately because the current EAF
route has no WAG fuel carrier; it remains a range-midpoint diagnostic, not an
ETS component.

## Residual policy

Electricity, NG and CO2 residuals are signed reporting KPIs. They are neither
loads nor allocated fuel, and they are not used to fit the model to anchors.

## Gate

- WAG-explicit point-of-oxidation CO2 subtotal: GO, diagnostic-only.
- Site Scope 1 residual reporting: GO, validation-only.
- Consolidated site/ETS CO2, NG residual allocation, sensitivity, economics and DA: NO-GO.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def run_s4_4c5p_u_wag_explicit_co2_anchor_reconciliation() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    anchors = _anchor_map()
    ledger, wag_totals_t = _wag_ledger()
    modes = _modes(wag_totals_t, anchors)
    policy = _component_policy()
    comparisons = _anchor_comparisons(wag_totals_t, anchors)
    residuals = _residual_kpis(anchors)
    warnings = _warnings()
    validations = _validations(modes, ledger, residuals)
    counts: dict[str, int] = {}
    for row in validations:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    wag_totals_mt = {configuration: value / MT_PER_T for configuration, value in wag_totals_t.items()}
    stage_gate = {
        "stage": STAGE,
        "status": "partial_wag_explicit_co2_anchor_reconciled",
        "thesis_usability": False,
        "output_policy": "minimal",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic",
        "go_no_go": {
            "WAG_explicit_CO2_subtotal": "GO_DIAGNOSTIC_ONLY",
            "site_scope1_residual_reporting": "GO_VALIDATION_ONLY",
            "consolidated_site_or_ETS_CO2": "NO_GO",
            "NG_residual_allocation_or_CO2": "NO_GO",
            "electricity_residual_allocation_or_scope2": "NO_GO",
            "full_sensitivity_execution": "NO_GO",
            "economics_readiness": "NO_GO",
            "DA_readiness": "NO_GO",
        },
        "guardrails": {
            "model_equations_changed": False,
            "executable_development_inputs_changed": False,
            "new_physical_allocator_created": False,
            "invented_wag_ng_ratio": False,
            "mixed_wag_quantitative_use": False,
            "aggregate_process_counter_added_to_wag_mode": False,
            "residual_energy_allocated": False,
            "raw_pdfs_inspected": False,
            "ETS_or_economics_activated": False,
        },
        "validation_check_counts": counts,
    }
    summary = {
        "stage": STAGE,
        "status": stage_gate["status"],
        "thesis_usability": False,
        "wag_explicit_co2_mt_y": wag_totals_mt,
        "scope1_residuals_by_mode": [
            {
                "configuration": row["configuration"],
                "mode": row["co2_mode"],
                "residual_mt_y": _as_float(row["residual_to_scope1_anchor_mt_y"]),
            }
            for row in modes
        ],
        "validation_check_counts": counts,
        "go_no_go": stage_gate["go_no_go"],
    }
    inputs = [
        C5P_T_DIR / "controller_mix_24h_contract_candidate.csv",
        C5P_H_DIR / "c5_co2_component_inventory.csv",
        C5P_G_DIR / "c5_residual_electricity_boundary_matrix.csv",
        C5P_G_DIR / "c5_residual_ng_boundary_matrix.csv",
        ANCHOR_REGISTER_PATH,
        S3_WAG_INPUT_PATH,
    ]
    _write_csv(OUTPUT_DIR / "wag_point_of_oxidation_co2_ledger.csv", ledger, WAG_LEDGER_COLUMNS)
    _write_csv(OUTPUT_DIR / "co2_reconciliation_by_mode.csv", modes, MODE_COLUMNS)
    _write_csv(OUTPUT_DIR / "co2_component_inclusion_policy.csv", policy, POLICY_COLUMNS)
    _write_csv(OUTPUT_DIR / "co2_anchor_comparison.csv", comparisons, ANCHOR_COLUMNS)
    _write_csv(OUTPUT_DIR / "residual_boundary_kpis.csv", residuals, RESIDUAL_COLUMNS)
    _write_csv(OUTPUT_DIR / "co2_warnings.csv", warnings, WARNING_COLUMNS)
    _write_csv(OUTPUT_DIR / "validation_checks.csv", validations, VALIDATION_COLUMNS)
    _write_json(OUTPUT_DIR / "input_manifest.json", {"stage": STAGE, "output_policy": "minimal", "run_class": "diagnostic", "lineage_role": "diagnostic", "inputs": [_file_record(path) for path in inputs]})
    _write_json(OUTPUT_DIR / "code_version.json", {"stage": STAGE, "git_revision": _git_revision(), "code_path": __file__})
    _write_json(OUTPUT_DIR / "s4_4c5p_u_stage_gate.json", stage_gate)
    _write_json(OUTPUT_DIR / "summary.json", summary)
    _write_json(OUTPUT_DIR / "registry_entry.json", {"run_id": STAGE, "purpose": "Annual WAG-explicit CO2 anchor reconciliation with visible residuals.", "thesis_usable": False, "retention": "local diagnostic output until review", "git_eligible": False, "status": stage_gate["status"]})
    _write_report(summary)
    return summary


def main() -> int:
    run_s4_4c5p_u_wag_explicit_co2_anchor_reconciliation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
