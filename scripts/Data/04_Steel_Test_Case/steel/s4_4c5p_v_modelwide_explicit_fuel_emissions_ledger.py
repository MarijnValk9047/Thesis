"""S4.4c5p_v model-wide, double-counting-safe CO2 coverage ledger.

The stage widens CO2 visibility across every modelled asset without pretending
that the current boundary is a full site or ETS ledger.  It counts only:

* BFG/COG/BOFG once at represented point-of-oxidation sinks; and
* NG once for already modelled, named NG consumers.

Aggregate process counters, capture streams, residual NG/electricity and Scope
2 remain separate so they cannot silently enter the explicit-fuel total.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import S4_ROOT, _read_csv, _write_csv, _write_json


STAGE = "S4.4c5p_v_modelwide_explicit_fuel_emissions_ledger"
OUTPUT_DIR = S4_ROOT / "s4_4c5p_v_modelwide_explicit_fuel_emissions_ledger"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_MODELWIDE_EXPLICIT_FUEL_EMISSIONS_LEDGER.md")

C5P_U_DIR = S4_ROOT / "s4_4c5p_u_wag_explicit_co2_anchor_reconciliation"
C5P_G_DIR = S4_ROOT / "s4_4c5p_g_residual_electricity_ng_boundary_diagnostics"
C5P_H_DIR = S4_ROOT / "s4_4c5p_h_co2_and_plant_energy_anchor_boundary_diagnostics"
ANCHOR_REGISTER_PATH = S4_ROOT / "c5_model_anchor_register" / "c5_model_anchor_evidence_register.csv"
S3_WAG_INPUT_PATH = S4_ROOT.parent / "S3" / "s3_provisional_dev_input" / "s3_wag_selected_dev_inputs.csv"

CONFIGS = ("C0_current_BF_BOF_reference", "C1_phase1_BF_BOF_plus_DRP_EAF")
WAG_CARRIERS = ("BFG", "COG", "BOFG")
NG_FACTOR_PARAMETER = "eu_ets_natural_gas_reference_factor"
MT_PER_T = 1_000_000.0

LEDGER_COLUMNS = [
    "configuration",
    "asset_or_sink",
    "emission_component_id",
    "emission_category",
    "carrier",
    "energy_PJ_y",
    "emission_factor_kgCO2_per_GJ",
    "co2_t_y",
    "included_in_explicit_fuel_total",
    "carbon_boundary",
    "source_stage_or_card",
    "overlap_key",
    "status",
    "caveat",
]
COVERAGE_COLUMNS = [
    "configuration",
    "asset_or_boundary",
    "current_co2_treatment",
    "included_in_explicit_fuel_total",
    "overlap_risk",
    "current_status",
    "next_requirement",
    "caveat",
]
TOTAL_COLUMNS = [
    "configuration",
    "wag_point_of_oxidation_co2_mt_y",
    "explicit_modelled_NG_co2_mt_y",
    "explicit_fuel_co2_total_mt_y",
    "scope1_anchor_mt_y",
    "residual_to_scope1_anchor_mt_y",
    "accounted_share_of_scope1_anchor",
    "full_site_or_ETS_ready",
    "caveat",
]
COMPONENT_COLUMNS = [
    "configuration",
    "component",
    "current_value_mt_y",
    "component_type",
    "included_in_explicit_fuel_total",
    "why_included_or_excluded",
    "overlap_key",
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
    "active_as_model_load_or_allocation",
    "co2_inferred_from_residual",
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
        raise FileNotFoundError(f"Required C5p_v input is missing: {path}")
    return _read_csv(path)


def _ng_factor() -> float:
    for row in _rows(S3_WAG_INPUT_PATH):
        if row.get("parameter_name") != NG_FACTOR_PARAMETER:
            continue
        if row.get("accepted_for_dev_use") != "true" or row.get("energy_basis") != "LHV_energy":
            raise ValueError("Selected natural-gas factor is not safe for explicit point-of-oxidation reporting.")
        return _as_float(row.get("selected_value"))
    raise ValueError("Missing selected natural-gas point-of-oxidation factor.")


def _scope1_anchors() -> dict[str, float]:
    expected = {
        "C0": "c0_official_scope1_12_6_missing",
        "C1": "c1_official_scope1_8_3_missing",
    }
    found = {row["anchor_id"]: row for row in _rows(ANCHOR_REGISTER_PATH)}
    return {
        "C0_current_BF_BOF_reference": _as_float(found[expected["C0"]]["converted_value"]),
        "C1_phase1_BF_BOF_plus_DRP_EAF": _as_float(found[expected["C1"]]["converted_value"]),
    }


def _wag_rows() -> tuple[list[dict[str, str]], dict[str, float]]:
    rows: list[dict[str, str]] = []
    totals = {configuration: 0.0 for configuration in CONFIGS}
    for source in _rows(C5P_U_DIR / "wag_point_of_oxidation_co2_ledger.csv"):
        carrier = source["carrier"]
        if carrier not in WAG_CARRIERS:
            raise ValueError(f"Unexpected carrier in C5p_u WAG ledger: {carrier}")
        co2 = _as_float(source["wag_point_of_oxidation_co2_t_y"])
        totals[source["configuration"]] += co2
        rows.append(
            {
                "configuration": source["configuration"],
                "asset_or_sink": source["sink_or_controller"],
                "emission_component_id": f"wag_oxidation_{carrier.lower()}_{source['sink_or_controller']}",
                "emission_category": "explicit_WAG_point_of_oxidation",
                "carrier": carrier,
                "energy_PJ_y": _fmt(_as_float(source["allocation_GJ_LHV_y"]) / 1_000_000.0),
                "emission_factor_kgCO2_per_GJ": source["emission_factor_kgCO2_per_GJ"],
                "co2_t_y": _fmt(co2),
                "included_in_explicit_fuel_total": "true",
                "carbon_boundary": "point_of_oxidation_once",
                "source_stage_or_card": "C5p_u / C5p_t carrier-specific controller ledger",
                "overlap_key": f"WAG_{carrier}",
                "status": "represented_controller_sink",
                "caveat": "No aggregate BF/BOF/KGF/PEFA counter, residual energy or Scope 2 is included.",
            }
        )
    return rows, totals


def _ng_rows() -> tuple[list[dict[str, str]], dict[str, float]]:
    factor = _ng_factor()
    mapping = {
        "DRP_NG_total": "NG_DRP",
        "EAF_NG": "EAF",
        "VN25_IJ01_generator_NG": "VN25_IJ01_generator_interface",
        "boiler_steam_NG_backup": "steam_boiler_controller",
        "PEFA_NG_backup": "PEFA_controller",
        "other_modelled_NG": "other_modelled_NG",
    }
    rows: list[dict[str, str]] = []
    totals = {configuration: 0.0 for configuration in CONFIGS}
    for source in _rows(C5P_G_DIR / "c5_residual_ng_component_balance.csv"):
        component = source["ng_component"]
        if component not in mapping:
            continue
        energy_pj = _as_float(source["annual_value_pj"])
        co2 = energy_pj * 1_000_000.0 * factor / 1000.0
        totals[source["configuration"]] += co2
        rows.append(
            {
                "configuration": source["configuration"],
                "asset_or_sink": mapping[component],
                "emission_component_id": f"explicit_NG_{component}",
                "emission_category": "explicit_modelled_NG_point_of_oxidation",
                "carrier": "NG",
                "energy_PJ_y": _fmt(energy_pj),
                "emission_factor_kgCO2_per_GJ": _fmt(factor),
                "co2_t_y": _fmt(co2),
                "included_in_explicit_fuel_total": "true",
                "carbon_boundary": "point_of_oxidation_once",
                "source_stage_or_card": source["source_or_stage"],
                "overlap_key": f"NG_{component}",
                "status": "represented_named_NG_consumer",
                "caveat": "Only named modelled NG is counted. Residual/full-site NG is not allocated or emitted by inference.",
            }
        )
    return rows, totals


def _separate_component_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for source in _rows(C5P_H_DIR / "c5_co2_component_inventory.csv"):
        component = source["component"]
        if component not in {
            "PEFA_diagnostic_CO2",
            "DRP_capture_stream",
            "EAF_midpoint_CO2",
            "BF_aggregate_hot_metal_CO2_counter",
            "BOF_OSF_direct_CO2_candidate",
            "KGF_coking_direct_CO2_candidate",
            "sinter_CO2_candidate",
            "NG_combustion_CO2_deferred",
            "electricity_scope2_CO2_deferred",
        }:
            continue
        if component == "DRP_capture_stream":
            category = "capture_reporting_only"
            included = "false"
            boundary = "capture_stream_separate"
            caveat = "Capture stream is reported separately and is neither added nor automatically subtracted from explicit fuel CO2."
        elif component in {"PEFA_diagnostic_CO2", "BF_aggregate_hot_metal_CO2_counter", "BOF_OSF_direct_CO2_candidate", "KGF_coking_direct_CO2_candidate", "sinter_CO2_candidate"}:
            category = "aggregate_process_validation_only"
            included = "false"
            boundary = "excluded_to_prevent_WAG_carbon_double_count"
            caveat = "Excluded because its carbon may overlap the WAG point-of-oxidation ledger."
        elif component == "EAF_midpoint_CO2":
            category = "aggregate_process_validation_only"
            included = "false"
            boundary = "excluded_pending_nonfuel_process_split"
            caveat = "EAF aggregate range is validation context only; do not add it while EAF NG is explicit unless non-fuel process carbon is separated."
        else:
            category = "unmodelled_or_out_of_scope"
            included = "false"
            boundary = "not_active"
            caveat = "Not included in the explicit-fuel ledger."
        rows.append(
            {
                "configuration": source["configuration"],
                "asset_or_sink": component,
                "emission_component_id": component,
                "emission_category": category,
                "carrier": source["fuel_or_process"],
                "energy_PJ_y": "",
                "emission_factor_kgCO2_per_GJ": "",
                "co2_t_y": _fmt(_as_float(source["co2_model_output_mt_y"]) * MT_PER_T),
                "included_in_explicit_fuel_total": included,
                "carbon_boundary": boundary,
                "source_stage_or_card": "C5p_h component inventory",
                "overlap_key": component,
                "status": "separate_context_or_gap",
                "caveat": caveat,
            }
        )
    return rows


def _asset_coverage() -> list[dict[str, str]]:
    treatments = [
        ("BF and hot stoves", "WAG carbon counted at represented downstream BFG oxidation sinks", "true", "high", "partial", "Separate non-WAG BF process carbon from the aggregate counter before inclusion."),
        ("KGF/coking", "COG carbon counted at represented downstream COG oxidation sinks", "true", "high", "partial", "Separate non-COG coking emissions before inclusion."),
        ("BOF/OSF", "BOFG carbon counted at represented downstream BOFG oxidation sinks", "true", "high", "partial", "Separate BOF non-BOFG process carbon before inclusion."),
        ("PEFA", "WAG controller fuel oxidation counted; aggregate PEFA diagnostic excluded", "true", "high", "partial", "Source-backed split of solid fuel/non-WAG emissions needed."),
        ("Sinter", "Represented COG oxidation counted; aggregate sinter counter excluded", "true", "high", "partial", "Source-backed solid-fuel and non-COG process boundary needed."),
        ("HSM/WBW", "Represented BFG/COG/BOFG oxidation counted", "true", "medium", "partial", "No aggregate HSM GHG value may be added on top."),
        ("Boiler/steam", "Represented WAG oxidation counted; current explicit NG backup is zero", "true", "low", "represented", "Maintain carrier-specific boiler rows."),
        ("Generators", "Represented WAG and named NG oxidation counted", "true", "low", "represented", "Keep no export/economic interpretation."),
        ("NG-DRP", "Named DRP NG oxidation counted", "true", "medium", "partial", "Keep capture stream separate; do not infer residual NG emissions."),
        ("EAF", "Named EAF NG oxidation counted; EAF aggregate range excluded", "true", "medium", "partial", "Separate non-fuel process carbon before adding any EAF aggregate component."),
        ("DSP", "No active fuel emissions in current boundary", "false", "medium", "not_represented", "Add only when a source-backed active fuel boundary exists."),
        ("Residual electricity and NG", "Tracked as signed boundary KPIs only", "false", "high", "not_represented", "Never allocate or infer CO2 from residuals."),
    ]
    rows: list[dict[str, str]] = []
    for configuration in CONFIGS:
        for asset, treatment, included, risk, status, next_requirement in treatments:
            rows.append(
                {
                    "configuration": configuration,
                    "asset_or_boundary": asset,
                    "current_co2_treatment": treatment,
                    "included_in_explicit_fuel_total": included,
                    "overlap_risk": risk,
                    "current_status": status,
                    "next_requirement": next_requirement,
                    "caveat": "Model-wide coverage status; not an ETS or full-site completeness claim.",
                }
            )
    return rows


def _component_register(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        if row["emission_category"] not in {"aggregate_process_validation_only", "capture_reporting_only", "unmodelled_or_out_of_scope"}:
            continue
        result.append(
            {
                "configuration": row["configuration"],
                "component": row["emission_component_id"],
                "current_value_mt_y": _fmt(_as_float(row["co2_t_y"]) / MT_PER_T),
                "component_type": row["emission_category"],
                "included_in_explicit_fuel_total": row["included_in_explicit_fuel_total"],
                "why_included_or_excluded": row["carbon_boundary"],
                "overlap_key": row["overlap_key"],
                "caveat": row["caveat"],
            }
        )
    return result


def _residual_rows() -> list[dict[str, str]]:
    electricity = {row["configuration"]: row for row in _rows(C5P_G_DIR / "c5_residual_electricity_boundary_matrix.csv")}
    ng = {row["configuration"]: row for row in _rows(C5P_G_DIR / "c5_residual_ng_boundary_matrix.csv")}
    rows: list[dict[str, str]] = []
    for configuration in CONFIGS:
        rows.extend(
            [
                {
                    "configuration": configuration,
                    "metric": "electricity_pre_floor_exposure",
                    "modelled_value": electricity[configuration]["modelled_exposure_pre_floor_twh"],
                    "unit": "TWh/y",
                    "anchor_value": "",
                    "anchor_unit": "",
                    "residual_to_anchor": "",
                    "active_as_model_load_or_allocation": "false",
                    "co2_inferred_from_residual": "false",
                    "caveat": "Reported as existing C5p_g boundary diagnostic; no Scope 2 is inferred.",
                },
                {
                    "configuration": configuration,
                    "metric": "unallocated_full_site_NG",
                    "modelled_value": ng[configuration]["total_modelled_ng_pj"],
                    "unit": "PJ/y",
                    "anchor_value": "",
                    "anchor_unit": "",
                    "residual_to_anchor": "",
                    "active_as_model_load_or_allocation": "false",
                    "co2_inferred_from_residual": "false",
                    "caveat": "Only named modelled NG receives CO2; residual/background NG remains unallocated and un-emitted.",
                },
            ]
        )
    return rows


def _totals(wag: dict[str, float], ng: dict[str, float], scope1: dict[str, float]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for configuration in CONFIGS:
        wag_mt = wag[configuration] / MT_PER_T
        ng_mt = ng[configuration] / MT_PER_T
        total = wag_mt + ng_mt
        anchor = scope1[configuration]
        rows.append(
            {
                "configuration": configuration,
                "wag_point_of_oxidation_co2_mt_y": _fmt(wag_mt),
                "explicit_modelled_NG_co2_mt_y": _fmt(ng_mt),
                "explicit_fuel_co2_total_mt_y": _fmt(total),
                "scope1_anchor_mt_y": _fmt(anchor),
                "residual_to_scope1_anchor_mt_y": _fmt(anchor - total),
                "accounted_share_of_scope1_anchor": _fmt(total / anchor if anchor else 0.0),
                "full_site_or_ETS_ready": "false",
                "caveat": "Explicit represented fuel only; aggregate process counters, capture stream, residual NG/electricity and Scope 2 are excluded.",
            }
        )
    return rows


def _warnings() -> list[dict[str, str]]:
    return [
        {
            "warning_id": "V_WARN_001",
            "configuration": "both",
            "severity": "high",
            "message": "Explicit-fuel CO2 is not a full-site Scope 1 or ETS ledger.",
            "recommended_action": "Use the Scope 1 residual as a coverage KPI, not a model input or calibration target.",
        },
        {
            "warning_id": "V_WARN_002",
            "configuration": "both",
            "severity": "high",
            "message": "BF, BOF, KGF, PEFA and sinter aggregate counters are excluded because their WAG carbon may overlap downstream oxidation.",
            "recommended_action": "Add only source-separated non-WAG process carbon in a future carbon-boundary repair.",
        },
        {
            "warning_id": "V_WARN_003",
            "configuration": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "severity": "medium",
            "message": "C1 carrier-unsplit flare is not assigned CO2 in the explicit WAG ledger.",
            "recommended_action": "Keep flare as visible missing coverage until a carrier split is available.",
        },
        {
            "warning_id": "V_WARN_004",
            "configuration": "both",
            "severity": "medium",
            "message": "DRP capture is reported separately from explicit NG CO2 and is not automatically deducted.",
            "recommended_action": "Model a capture sink and accounting boundary before claiming net emissions.",
        },
    ]


def _validations(ledger: list[dict[str, str]], totals: list[dict[str, str]], residuals: list[dict[str, str]]) -> list[dict[str, str]]:
    included = [row for row in ledger if row["included_in_explicit_fuel_total"] == "true"]
    return [
        {
            "check_id": "V_CHECK_001",
            "check_name": "included_rows_use_only_explicit_fuel_boundaries",
            "status": "pass" if all(row["emission_category"].startswith("explicit_") for row in included) else "fail",
            "evidence": "Only WAG and named modelled NG rows enter the total.",
            "recommended_action": "Do not add aggregate or residual rows to the explicit fuel total.",
        },
        {
            "check_id": "V_CHECK_002",
            "check_name": "no_aggregate_process_counter_double_count",
            "status": "pass" if not any(row["included_in_explicit_fuel_total"] == "true" and "aggregate" in row["emission_category"] for row in ledger) else "fail",
            "evidence": "Aggregate BF/BOF/KGF/PEFA/sinter/EAF context rows are separate.",
            "recommended_action": "Keep carbon-boundary modes mutually exclusive.",
        },
        {
            "check_id": "V_CHECK_003",
            "check_name": "capture_stream_not_added_or_subtracted",
            "status": "pass" if not any(row["emission_category"] == "capture_reporting_only" and row["included_in_explicit_fuel_total"] == "true" for row in ledger) else "fail",
            "evidence": "DRP capture remains separate reporting context.",
            "recommended_action": "Require explicit capture/sink modelling for any net-emissions claim.",
        },
        {
            "check_id": "V_CHECK_004",
            "check_name": "residual_energy_has_no_inferred_CO2",
            "status": "pass" if all(row["co2_inferred_from_residual"] == "false" for row in residuals) else "fail",
            "evidence": "Residual electricity and NG are reporting-only.",
            "recommended_action": "Keep residuals visible and unallocated.",
        },
        {
            "check_id": "V_CHECK_005",
            "check_name": "scope1_residuals_retain_sign",
            "status": "pass" if all(_as_float(row["residual_to_scope1_anchor_mt_y"]) >= 0.0 for row in totals) else "warning",
            "evidence": "Scope 1 residuals are anchor minus explicit total, without flooring.",
            "recommended_action": "Investigate any future negative residual as a double-counting or boundary warning.",
        },
    ]


def _file_record(path: Path) -> dict[str, str]:
    return {"path": str(path), "status": "read" if path.exists() else "missing", "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""}


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _write_report(summary: dict[str, Any]) -> None:
    totals = summary["explicit_fuel_co2_totals_mt_y"]
    report = f"""# C5 Model-Wide Explicit-Fuel Emissions Ledger

## Purpose

C5p_v gives every current model asset and boundary a CO2 coverage status. It
does not claim a full-site inventory. The only emissions added to the
model-wide explicit-fuel subtotal are carrier-specific WAG oxidation and
already modelled, named NG use. This preserves the user's WAG-first policy and
keeps unallocated residual NG/electricity out of the emissions total.

## Explicit-fuel subtotal

- C0: {totals['C0_current_BF_BOF_reference']:.6f} MtCO2/y.
- C1: {totals['C1_phase1_BF_BOF_plus_DRP_EAF']:.6f} MtCO2/y.

The remaining gap to the full-site Scope 1 anchor is reported, not allocated.

## Double-counting guard

Aggregate BF, BOF, KGF, PEFA, sinter and EAF counters are retained only as
separate validation/context rows. They do not enter the explicit-fuel total.
DRP capture is also separate: it is neither added nor subtracted until a
capture-and-sink boundary is represented.

## Gate

- Model-wide CO2 coverage and explicit-fuel subtotal: GO, diagnostic-only.
- Site Scope 1 residual reporting: GO, validation-only.
- ETS, consolidated site emissions, residual-energy allocation, economics and DA: NO-GO.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def run_s4_4c5p_v_modelwide_explicit_fuel_emissions_ledger() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    wag_rows, wag_totals = _wag_rows()
    ng_rows, ng_totals = _ng_rows()
    separate_rows = _separate_component_rows()
    ledger = wag_rows + ng_rows + separate_rows
    totals = _totals(wag_totals, ng_totals, _scope1_anchors())
    coverage = _asset_coverage()
    components = _component_register(separate_rows)
    residuals = _residual_rows()
    warnings = _warnings()
    validations = _validations(ledger, totals, residuals)
    counts: dict[str, int] = {}
    for row in validations:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    explicit_totals = {row["configuration"]: _as_float(row["explicit_fuel_co2_total_mt_y"]) for row in totals}
    stage_gate = {
        "stage": STAGE,
        "status": "modelwide_explicit_fuel_CO2_coverage_ready",
        "thesis_usability": False,
        "output_policy": "minimal",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic",
        "go_no_go": {
            "modelwide_explicit_fuel_CO2_subtotal": "GO_DIAGNOSTIC_ONLY",
            "site_scope1_residual_reporting": "GO_VALIDATION_ONLY",
            "consolidated_site_or_ETS_CO2": "NO_GO",
            "residual_NG_or_electricity_CO2": "NO_GO",
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
            "aggregate_process_counter_added_to_total": False,
            "residual_energy_allocated_or_emitted": False,
            "capture_stream_netting_active": False,
            "scope2_active": False,
            "ETS_or_economics_activated": False,
            "raw_pdfs_inspected": False,
        },
        "validation_check_counts": counts,
    }
    summary = {
        "stage": STAGE,
        "status": stage_gate["status"],
        "thesis_usability": False,
        "explicit_fuel_co2_totals_mt_y": explicit_totals,
        "scope1_residuals_mt_y": {row["configuration"]: _as_float(row["residual_to_scope1_anchor_mt_y"]) for row in totals},
        "coverage_rows": len(coverage),
        "component_context_rows": len(components),
        "validation_check_counts": counts,
        "go_no_go": stage_gate["go_no_go"],
    }
    inputs = [
        C5P_U_DIR / "wag_point_of_oxidation_co2_ledger.csv",
        C5P_G_DIR / "c5_residual_ng_component_balance.csv",
        C5P_G_DIR / "c5_residual_electricity_boundary_matrix.csv",
        C5P_H_DIR / "c5_co2_component_inventory.csv",
        ANCHOR_REGISTER_PATH,
        S3_WAG_INPUT_PATH,
    ]
    _write_csv(OUTPUT_DIR / "modelwide_emissions_ledger.csv", ledger, LEDGER_COLUMNS)
    _write_csv(OUTPUT_DIR / "asset_emissions_coverage.csv", coverage, COVERAGE_COLUMNS)
    _write_csv(OUTPUT_DIR / "explicit_fuel_total_vs_scope1.csv", totals, TOTAL_COLUMNS)
    _write_csv(OUTPUT_DIR / "separate_component_context.csv", components, COMPONENT_COLUMNS)
    _write_csv(OUTPUT_DIR / "residual_energy_policy_kpis.csv", residuals, RESIDUAL_COLUMNS)
    _write_csv(OUTPUT_DIR / "co2_warnings.csv", warnings, WARNING_COLUMNS)
    _write_csv(OUTPUT_DIR / "validation_checks.csv", validations, VALIDATION_COLUMNS)
    _write_json(OUTPUT_DIR / "input_manifest.json", {"stage": STAGE, "output_policy": "minimal", "run_class": "diagnostic", "lineage_role": "diagnostic", "inputs": [_file_record(path) for path in inputs]})
    _write_json(OUTPUT_DIR / "code_version.json", {"stage": STAGE, "git_revision": _git_revision(), "code_path": __file__})
    _write_json(OUTPUT_DIR / "s4_4c5p_v_stage_gate.json", stage_gate)
    _write_json(OUTPUT_DIR / "summary.json", summary)
    _write_json(OUTPUT_DIR / "registry_entry.json", {"run_id": STAGE, "purpose": "Model-wide explicit-fuel CO2 coverage ledger with double-count exclusions.", "thesis_usable": False, "retention": "local diagnostic output until review", "git_eligible": False, "status": stage_gate["status"]})
    _write_report(summary)
    return summary


def main() -> int:
    run_s4_4c5p_v_modelwide_explicit_fuel_emissions_ledger()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
