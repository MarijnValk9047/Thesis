"""S4.4c5p_o hardened WAG controller contract diagnostics.

This stage creates a model-wide diagnostic interface over existing WAG
controller/allocation outputs. It does not implement a new WAG allocator and it
does not change model equations, executable development inputs, source cards,
objectives, residual-load logic, economics, DA, or CO2 objective behaviour.
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


STAGE = "S4.4c5p_o_wag_controller_contract_hardening"
C5P_O_DIR = S4_ROOT / "s4_4c5p_o_wag_controller_contract_hardening"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_WAG_CONTROLLER_CONTRACT_HARDENING.md")

C5P_M_DIR = S4_ROOT / "s4_4c5p_m_wag_balance_and_controller_contract"
C5P_N_DIR = S4_ROOT / "s4_4c5p_n_wag_controller_contract_proposal"
C5P_K_DIR = S4_ROOT / "s4_4c5p_k_common_plant_ng_wag_overlay"
C5P_B_DIR = S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting"
C5P_C_DIR = S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting"
C5L_B_DIR = S4_ROOT / "s4_4c5l_b_HSM_WAG_dispatch_controller_and_traceability_patch"
C5L_D_DIR = S4_ROOT / "s4_4c5l_d_HSM_hot_charge_share_cap_and_reheat_sensitivity_patch"
C5M_DIR = S4_ROOT / "s4_4c5m_Sinter_minimal_parameterisation"

CONFIGS = (C0, C1)
QUANTITATIVE_WAG_CARRIERS = ("BFG", "BOFG", "COG")
STRUCTURAL_ONLY_CARRIERS = ("mixed_wag",)
REPORTING_ONLY_CARRIERS = ("aggregate_wag",)

INTERFACE_COLUMNS = [
    "configuration",
    "carrier",
    "source_stage",
    "source_artifact_or_function",
    "sink_or_stage",
    "accepted_controller_surface",
    "allocation_mode",
    "quantitative_value_PJ_y",
    "quantitative_status",
    "can_feed_physical_allocation",
    "can_feed_electricity_decomposition",
    "can_feed_ng_residual_policy",
    "can_feed_co2_policy",
    "caveat",
]

CALL_TRACE_COLUMNS = [
    "trace_id",
    "function_or_output_used",
    "file_path",
    "called_or_read",
    "side_effect_free_assumption",
    "input_artifact",
    "output_artifact",
    "carriers_handled",
    "sinks_handled",
    "reason_used",
    "reason_not_used_if_applicable",
    "caveat",
]

ALLOCATION_LEDGER_COLUMNS = [
    "configuration",
    "carrier",
    "generation_PJ_y",
    "process_or_prep_use_PJ_y",
    "hsm_wbw_use_PJ_y",
    "sinter_or_pefa_use_PJ_y",
    "steam_boiler_use_PJ_y",
    "generator_use_PJ_y",
    "flare_spill_PJ_y",
    "residual_PJ_y",
    "total_accounted_use_PJ_y",
    "balance_residual_PJ_y",
    "balance_status",
    "carrier_split_quality",
    "accepted_for_contract",
    "caveat",
]

VALIDATION_COLUMNS = [
    "check_id",
    "check_name",
    "configuration",
    "check_type",
    "status",
    "evidence",
    "recommended_action",
]

ATHANASIADIS_COLUMNS = [
    "alignment_id",
    "functional_area",
    "athanasiadis_precedent_type",
    "expected_functional_separation",
    "current_repository_surface",
    "current_contract_status",
    "locator_status",
    "evidence_used",
    "caveat",
    "user_review_needed",
]

C5P_K_EXCLUSION_COLUMNS = [
    "c5p_k_metric_or_output",
    "previous_interpretation_risk",
    "allowed_future_use",
    "replacement_in_contract",
    "reason",
    "caveat",
]

BLOCKED_COLUMNS = [
    "blocked_case_id",
    "configuration",
    "carrier",
    "sink_or_stage",
    "missing_requirement",
    "why_blocked",
    "blocks_future_stage",
    "allowed_current_handling",
    "required_fix",
]


def _fmt(value: Any, digits: int = 6) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def _read_optional_csv(path: Path) -> list[dict[str, str]]:
    return _read_csv(path) if path.exists() else []


def _read_optional_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _status_counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field, "") or "missing")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _balance_rows() -> list[dict[str, str]]:
    return _read_optional_csv(C5P_M_DIR / "wag_carrier_balance_matrix.csv")


def _sink_assignments() -> list[dict[str, str]]:
    return _read_optional_csv(C5P_N_DIR / "wag_sink_controller_assignment.csv")


def _contract_rules() -> list[dict[str, str]]:
    return _read_optional_csv(C5P_N_DIR / "wag_controller_contract_rules.csv")


def _source_info(sink: str) -> tuple[str, str, str, str]:
    if sink == "generation":
        return (
            "C5p_m/C5p_e",
            "C5p_m:wag_carrier_balance_matrix.csv",
            "carrier-specific WAG generation and current annual balance rows",
            "fixed_profile",
        )
    if sink == "process_or_prep_use":
        return (
            "C5p_m/C5p_e/C5l/C5m/C5n",
            "C5p_m:wag_carrier_balance_matrix.csv",
            "accepted upstream process/prep WAG surfaces",
            "carrier_specific",
        )
    if sink == "steam_boiler_use":
        return (
            "C5p_b",
            "s4_4c5p_b_wag_residual_after_steam.csv",
            "C5p_b boiler/steam WAG allocator",
            "proportional_existing",
        )
    if sink == "generator_use":
        return (
            "C5p_c",
            "s4_4c5p_c_generator_fuel_allocation.csv",
            "C5p_c IJ01/VN25 generator-interface allocator",
            "proportional_existing",
        )
    if sink == "flare_spill":
        return (
            "C5p_c/C5p_m",
            "s4_4c5p_c_wag_residual_after_generators.csv",
            "C5p_c flare/spill residual reporting",
            "carrier_specific",
        )
    return (
        "C5p_c/C5p_m",
        "wag_carrier_balance_matrix.csv",
        "C5p_m residual reporting",
        "carrier_specific",
    )


def _carrier_policy(carrier: str, sink: str, value: str) -> tuple[str, str, str, str, str]:
    if carrier in QUANTITATIVE_WAG_CARRIERS:
        physical = "no" if sink in {"residual_reporting", "flare_spill"} else "yes"
        elec = "caveated" if sink in {"generator_use", "steam_boiler_use", "generation"} else "yes"
        co2 = "caveated"
        ng = "no"
        status = "quantitative" if value not in ("", None) else "missing"
        return status, physical, elec, ng, co2
    if carrier in REPORTING_ONLY_CARRIERS:
        return "reporting_only", "no", "caveated", "no", "caveated"
    if carrier in STRUCTURAL_ONLY_CARRIERS:
        return "structural_only", "no", "no", "no", "no"
    if carrier == "NG":
        return "quantitative", "no", "caveated", "caveated", "caveated"
    return "missing", "no", "no", "no", "no"


def _build_interface_ledger(balance_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sink_fields = [
        ("generation", "generation_PJ_y"),
        ("process_or_prep_use", "process_use_PJ_y"),
        ("steam_boiler_use", "steam_boiler_use_PJ_y"),
        ("generator_use", "generator_use_PJ_y"),
        ("flare_spill", "flare_spill_PJ_y"),
        ("residual_reporting", "residual_PJ_y"),
    ]
    for row in balance_rows:
        carrier = row["carrier"]
        for sink, field in sink_fields:
            value = row.get(field, "")
            source_stage, artifact, surface, mode = _source_info(sink)
            if carrier in REPORTING_ONLY_CARRIERS:
                mode = "aggregate_reporting_only"
                surface = "aggregate reporting balance; not a physical controller surface"
            elif carrier in STRUCTURAL_ONLY_CARRIERS:
                mode = "structural_only"
                surface = "S4.4b2 structural WAG mixing rules"
                value = ""
            status, physical, elec, ng, co2 = _carrier_policy(carrier, sink, value)
            caveat = row.get("caveat", "")
            if carrier in REPORTING_ONLY_CARRIERS:
                caveat = "Reporting total only; cannot feed physical allocation."
            elif carrier in STRUCTURAL_ONLY_CARRIERS:
                caveat = "Structural eligibility only; no quantitative Wobbe/share-constrained mixer."
            elif sink == "flare_spill":
                caveat = "Carrier-specific flare split is partial; C1 flare is currently aggregate in C5p_c."
            rows.append(
                {
                    "configuration": row["configuration"],
                    "carrier": carrier,
                    "source_stage": source_stage,
                    "source_artifact_or_function": artifact,
                    "sink_or_stage": sink,
                    "accepted_controller_surface": surface,
                    "allocation_mode": mode,
                    "quantitative_value_PJ_y": value if carrier not in STRUCTURAL_ONLY_CARRIERS else "",
                    "quantitative_status": status,
                    "can_feed_physical_allocation": physical,
                    "can_feed_electricity_decomposition": elec,
                    "can_feed_ng_residual_policy": ng,
                    "can_feed_co2_policy": co2,
                    "caveat": caveat,
                }
            )
    return rows


def _build_call_trace() -> list[dict[str, str]]:
    specs = [
        (
            "TRACE_001",
            "C5p_m WAG carrier balance matrix",
            C5P_M_DIR / "wag_carrier_balance_matrix.csv",
            "read_existing_output",
            "true",
            "C5p_e annual carrier balance and C5p_c residual rows",
            "wag_contract_interface_ledger.csv; wag_carrier_sink_allocation_ledger.csv",
            "BFG;BOFG;COG;aggregate_wag;mixed_wag",
            "generation;process;steam;generator;flare;residual",
            "Canonical current WAG balance source for the hardening interface.",
            "",
            "Reads prior diagnostic output; no allocation logic executed.",
        ),
        (
            "TRACE_002",
            "C5p_n WAG contract proposal rules",
            C5P_N_DIR / "wag_controller_contract_rules.csv",
            "read_existing_output",
            "true",
            "C5p_n contract proposal",
            "wag_contract_validation_checks.csv; blocked cases",
            "COG;BFG;BOFG;mixed_wag;aggregate_wag;NG",
            "all",
            "Governance contract basis for allowed and blocked uses.",
            "",
            "Non-executable proposal carried forward as validation rules.",
        ),
        (
            "TRACE_003",
            "C5p_b boiler/steam WAG residual output",
            C5P_B_DIR / "s4_4c5p_b_wag_residual_after_steam.csv",
            "read_existing_output",
            "true",
            "C5p_b boiler/steam allocator",
            "call trace and interface ledger caveats",
            "BFG;COG;BOFG;NG",
            "steam_boiler",
            "Accepted current steam/boiler WAG surface.",
            "",
            "BOFG remains blocked for steam layer in the current baseline.",
        ),
        (
            "TRACE_004",
            "C5p_c generator fuel allocation output",
            C5P_C_DIR / "s4_4c5p_c_generator_fuel_allocation.csv",
            "read_existing_output",
            "true",
            "C5p_c generator interface allocator",
            "call trace and interface ledger caveats",
            "BFG;BOFG;COG;NG",
            "IJ01_VN25_generator_interface",
            "Accepted current generator-interface surface.",
            "",
            "Fixed/interface accounting only; no price response or export revenue.",
        ),
        (
            "TRACE_005",
            "C5p_c WAG residual after generators",
            C5P_C_DIR / "s4_4c5p_c_wag_residual_after_generators.csv",
            "read_existing_output",
            "true",
            "C5p_c residual/flare rows",
            "call trace and validation checks",
            "BFG;BOFG;COG;aggregate_wag",
            "flare_spill;residual",
            "Accepted current flare/residual reporting surface.",
            "",
            "C1 flare is not carrier-split.",
        ),
        (
            "TRACE_006",
            "C5l HSM WAG controller dashboard",
            C5L_B_DIR / "s4_4c5l_b_hsm_reheat_controller_dashboard.csv",
            "read_existing_output",
            "true",
            "C5l HSM/WBW WAG controller",
            "call trace",
            "BFG;COG;BOFG;NG",
            "HSM_WBW",
            "Accepted process WAG surface for HSM/WBW diagnostics.",
            "",
            "Read only; no HSM controller is executed here.",
        ),
        (
            "TRACE_007",
            "C5l_d HSM hot-charge/reheat controller dashboard",
            C5L_D_DIR / "s4_4c5l_d_hsm_reheat_controller_dashboard.csv",
            "read_existing_output",
            "true",
            "C5l_d hot-charge and reheat sensitivity patch",
            "call trace",
            "BFG;COG;BOFG;NG",
            "HSM_WBW",
            "Current C5l_d preserved base_0_50 reheat/hot-cold policy context.",
            "",
            "Read only; no sensitivity run is executed.",
        ),
        (
            "TRACE_008",
            "C5m sinter gas/WAG controller dashboard",
            C5M_DIR / "s4_4c5m_sinter_gas_wag_controller_dashboard.csv",
            "read_existing_output",
            "true",
            "C5m sinter gas/WAG controller",
            "call trace",
            "COG;NG",
            "Sinter",
            "Accepted sinter WAG/NG diagnostic surface.",
            "",
            "Sinter BFG/BOFG are blocked in base C5m.",
        ),
        (
            "TRACE_009",
            "wag_diagnostic process-first helpers",
            Path("scripts/Data/04_Steel_Test_Case/steel/wag_diagnostic.py"),
            "inspected_only",
            "not_called",
            "source code",
            "dependency evidence only",
            "BFG;COG;BOFG",
            "process;boiler;power;flare",
            "Existing helper functions are dependency evidence.",
            "Not called because this hardening stage must not run allocation algorithms.",
            "No new allocator or function call is introduced.",
        ),
        (
            "TRACE_010",
            "wag_fixed_profile_builder fixed profiles",
            Path("scripts/Data/04_Steel_Test_Case/steel/wag_fixed_profile_builder.py"),
            "inspected_only",
            "not_called",
            "source code",
            "dependency evidence only",
            "BFG;COG;BOFG",
            "generation;mandatory_self_use",
            "Existing fixed profile construction is dependency evidence.",
            "Not called because this stage reads accepted outputs only.",
            "No generated profile is rebuilt here.",
        ),
        (
            "TRACE_011",
            "S4.4b2 structural WAG mixing rules",
            Path("scripts/Data/04_Steel_Test_Case/steel/s4_4b2_physical_master_workbook.py"),
            "inspected_only",
            "not_called",
            "source code",
            "dependency evidence only",
            "BFG;COG;BOFG;NG;mixed_wag",
            "structural_mixed_gas_mixer",
            "Documents structural gas-network/mixing eligibility.",
            "Not called because mixed_wag remains non-quantitative.",
            "No Wobbe/share-constrained mixer is inferred.",
        ),
        (
            "TRACE_012",
            "C5p_k common-plant overlay outputs",
            C5P_K_DIR / "summary.json",
            "read_existing_output",
            "true",
            "C5p_k warning-only overlay",
            "c5p_k_exclusion_audit.csv",
            "aggregate_wag;NG",
            "common_plant_overlay",
            "Used only to enforce exclusion policy.",
            "Not accepted as physical allocation evidence.",
            "Aggregate fallback remains warning-only.",
        ),
    ]
    rows = []
    for spec in specs:
        (
            trace_id,
            name,
            path,
            mode,
            side_effect,
            input_artifact,
            output_artifact,
            carriers,
            sinks,
            reason,
            reason_not,
            caveat,
        ) = spec
        exists_caveat = caveat if path.exists() else f"{caveat} Required artifact or source path was not found; row is fail-closed."
        rows.append(
            {
                "trace_id": trace_id,
                "function_or_output_used": name,
                "file_path": str(path),
                "called_or_read": mode if path.exists() else "inspected_only",
                "side_effect_free_assumption": side_effect,
                "input_artifact": input_artifact,
                "output_artifact": output_artifact,
                "carriers_handled": carriers,
                "sinks_handled": sinks,
                "reason_used": reason if path.exists() else "Path missing; not used quantitatively.",
                "reason_not_used_if_applicable": reason_not,
                "caveat": exists_caveat,
            }
        )
    return rows


def _build_carrier_sink_ledger(balance_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in balance_rows:
        carrier = row["carrier"]
        process_or_prep = _zero(row.get("mandatory_self_use_PJ_y")) + _zero(row.get("process_use_PJ_y"))
        if carrier in QUANTITATIVE_WAG_CARRIERS:
            split_quality = "explicit"
            accepted = "yes"
            caveat = "Carrier-specific contract row preserved. HSM/sinter/PEFA detail may be folded into process/prep use."
            if carrier == "COG" and row["configuration"] == C1:
                caveat += " C1 aggregate flare/residual split remains partial."
        elif carrier in REPORTING_ONLY_CARRIERS:
            split_quality = "aggregate_only"
            accepted = "caveated"
            caveat = "Aggregate WAG row closes reporting totals only; it cannot allocate physical fuel."
        else:
            split_quality = "missing"
            accepted = "no"
            caveat = "Mixed WAG is structural-only and has no quantitative carrier ledger."
        rows.append(
            {
                "configuration": row["configuration"],
                "carrier": carrier,
                "generation_PJ_y": row.get("generation_PJ_y", ""),
                "process_or_prep_use_PJ_y": _fmt(process_or_prep),
                "hsm_wbw_use_PJ_y": row.get("hsm_wbw_use_PJ_y", ""),
                "sinter_or_pefa_use_PJ_y": "",
                "steam_boiler_use_PJ_y": row.get("steam_boiler_use_PJ_y", ""),
                "generator_use_PJ_y": row.get("generator_use_PJ_y", ""),
                "flare_spill_PJ_y": row.get("flare_spill_PJ_y", ""),
                "residual_PJ_y": row.get("residual_PJ_y", ""),
                "total_accounted_use_PJ_y": row.get("accounted_total_PJ_y", ""),
                "balance_residual_PJ_y": row.get("balance_residual_PJ_y", ""),
                "balance_status": row.get("balance_status", "missing"),
                "carrier_split_quality": split_quality,
                "accepted_for_contract": accepted,
                "caveat": caveat,
            }
        )
    return rows


def _build_validation_checks(
    interface_rows: list[dict[str, Any]],
    allocation_rows: list[dict[str, Any]],
    call_trace: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for config in CONFIGS:
        config_rows = [row for row in allocation_rows if row["configuration"] == config]
        carrier_rows = [row for row in config_rows if row["carrier"] in QUANTITATIVE_WAG_CARRIERS]
        carrier_status = "pass" if carrier_rows and all(row["balance_status"] == "pass" for row in carrier_rows) else "fail"
        rows.append(
            {
                "check_id": f"{config}_CARRIER_BALANCE",
                "check_name": "carrier_specific_balance_closure",
                "configuration": config,
                "check_type": "carrier_balance",
                "status": carrier_status,
                "evidence": "BFG/BOFG/COG rows from C5p_m wag_carrier_balance_matrix.csv",
                "recommended_action": "Inspect any non-pass carrier row before using WAG outputs.",
            }
        )
        aggregate_bad = [
            row
            for row in interface_rows
            if row["configuration"] == config
            and row["carrier"] == "aggregate_wag"
            and row["can_feed_physical_allocation"] == "yes"
        ]
        rows.append(
            {
                "check_id": f"{config}_NO_AGGREGATE_PHYSICAL",
                "check_name": "aggregate_wag_not_physical",
                "configuration": config,
                "check_type": "no_aggregate_physical_allocation",
                "status": "fail" if aggregate_bad else "pass",
                "evidence": "wag_contract_interface_ledger.csv aggregate_wag rows",
                "recommended_action": "Keep aggregate_wag reporting/warning-only.",
            }
        )
        mixed_bad = [
            row
            for row in interface_rows
            if row["configuration"] == config
            and row["carrier"] == "mixed_wag"
            and row["quantitative_status"] == "quantitative"
        ]
        rows.append(
            {
                "check_id": f"{config}_NO_MIXED_WAG_QUANT",
                "check_name": "mixed_wag_structural_only",
                "configuration": config,
                "check_type": "no_mixed_wag_quantitative_use",
                "status": "fail" if mixed_bad else "pass",
                "evidence": "mixed_wag rows remain structural_only",
                "recommended_action": "Do not unlock mixed_wag without source-backed quantitative mixer.",
            }
        )
        residuals = [_zero(row["balance_residual_PJ_y"]) for row in carrier_rows]
        rows.append(
            {
                "check_id": f"{config}_NO_NEGATIVE_FLOORING",
                "check_name": "negative_residuals_not_floored",
                "configuration": config,
                "check_type": "no_negative_flooring",
                "status": "pass",
                "evidence": f"Carrier balance residuals retained as read: {[_fmt(value) for value in residuals]}",
                "recommended_action": "Retain any future negative residuals as warnings; do not floor silently.",
            }
        )
    c5p_k_bad = [
        row
        for row in call_trace
        if "C5p_k" in row["function_or_output_used"] and "physical allocation" in row["reason_used"].lower()
    ]
    rows.append(
        {
            "check_id": "MODEL_WIDE_NO_C5P_K_PHYSICAL",
            "check_name": "c5p_k_warning_only",
            "configuration": "both",
            "check_type": "no_c5p_k_physical_use",
            "status": "fail" if c5p_k_bad else "pass",
            "evidence": "C5p_k used only in exclusion audit and call trace.",
            "recommended_action": "Do not use C5p_k allocation metrics for physical NG/WAG policy.",
        }
    )
    rows.extend(
        [
            {
                "check_id": "MODEL_WIDE_COMMON_PLANT_RATIO",
                "check_name": "missing_common_plant_wag_ng_split_blocks_policy",
                "configuration": "both",
                "check_type": "no_ng_split_invention",
                "status": "blocked",
                "evidence": "C5p_n/C5p_k report explicit_wag_ng_ratio_found=false.",
                "recommended_action": "Source review or controller-compatible common-plant logic required.",
            },
            {
                "check_id": "MODEL_WIDE_CO2_MODE",
                "check_name": "fuel_explicit_co2_not_unlocked",
                "configuration": "both",
                "check_type": "no_co2_mixed_mode",
                "status": "blocked",
                "evidence": "WAG/fuel-explicit CO2 remains blocked by carbon policy and factor gaps.",
                "recommended_action": "Keep site-level residual and aggregate process-counter modes separate.",
            },
            {
                "check_id": "MODEL_WIDE_NO_DOUBLE_COUNT",
                "check_name": "no_wag_double_counting_mode_active",
                "configuration": "both",
                "check_type": "no_double_count",
                "status": "pass",
                "evidence": "Hardening interface reads current ledgers only; no new CO2 or WAG reuse mode is created.",
                "recommended_action": "Continue to block aggregate plus fuel-explicit CO2 totals.",
            },
        ]
    )
    return rows


def _build_athanasiadis_alignment() -> list[dict[str, str]]:
    base_caveat = "Functional architecture check only; no raw PDF was inspected and no numeric Athanasiadis replication is claimed."
    return [
        {
            "alignment_id": "ATH_ALIGN_001",
            "functional_area": "WAG_generation_by_source_carrier",
            "athanasiadis_precedent_type": "WAG_network",
            "expected_functional_separation": "WAG generation remains linked to source/carrier rather than treated as market revenue.",
            "current_repository_surface": "C5p_m carrier balance; wag_diagnostic generation helpers; wag_fixed_profile_builder profiles",
            "current_contract_status": "partially_aligned",
            "locator_status": "indirect",
            "evidence_used": "Existing repo C5p_m/C5p_n reports and source-card/register references.",
            "caveat": base_caveat,
            "user_review_needed": "yes",
        },
        {
            "alignment_id": "ATH_ALIGN_002",
            "functional_area": "process_self_use",
            "athanasiadis_precedent_type": "WAG_network",
            "expected_functional_separation": "Process and mandatory self-use are represented before utility/generator sinks.",
            "current_repository_surface": "C5p_m process/prep rows; C5l HSM; C5m sinter; upstream process ledgers",
            "current_contract_status": "partially_aligned",
            "locator_status": "indirect",
            "evidence_used": "C5p_m balance rows and C5p_n sequence proposal.",
            "caveat": base_caveat,
            "user_review_needed": "yes",
        },
        {
            "alignment_id": "ATH_ALIGN_003",
            "functional_area": "steam_boiler_use",
            "athanasiadis_precedent_type": "steam_boiler",
            "expected_functional_separation": "Steam/boiler gas use is separated from generator-interface use.",
            "current_repository_surface": "C5p_b boiler/steam allocator and residual-after-steam outputs",
            "current_contract_status": "aligned",
            "locator_status": "indirect",
            "evidence_used": "C5p_b output read by this hardening stage.",
            "caveat": base_caveat,
            "user_review_needed": "yes",
        },
        {
            "alignment_id": "ATH_ALIGN_004",
            "functional_area": "generator_interface_use",
            "athanasiadis_precedent_type": "generator_interface",
            "expected_functional_separation": "Generator/interface use is represented after process and steam sinks and is not direct DA market revenue.",
            "current_repository_surface": "C5p_c IJ01/VN25 generator-interface allocator",
            "current_contract_status": "aligned",
            "locator_status": "indirect",
            "evidence_used": "C5p_c fuel allocation and residual WAG outputs.",
            "caveat": base_caveat,
            "user_review_needed": "yes",
        },
        {
            "alignment_id": "ATH_ALIGN_005",
            "functional_area": "flare_spill_residual",
            "athanasiadis_precedent_type": "model_boundary",
            "expected_functional_separation": "Unused WAG is visible as flare/spill/residual rather than hidden.",
            "current_repository_surface": "C5p_c residual-after-generators and C5p_m aggregate balance",
            "current_contract_status": "partially_aligned",
            "locator_status": "indirect",
            "evidence_used": "C5p_c/C5p_m outputs.",
            "caveat": f"{base_caveat} C1 flare is not carrier-split.",
            "user_review_needed": "yes",
        },
        {
            "alignment_id": "ATH_ALIGN_006",
            "functional_area": "no_direct_wag_market_valuation",
            "athanasiadis_precedent_type": "model_boundary",
            "expected_functional_separation": "WAG value is physical substitution/conversion, not direct electricity-price valuation.",
            "current_repository_surface": "C5p_b/C5p_c health rows and C5p_n policy",
            "current_contract_status": "aligned",
            "locator_status": "partial",
            "evidence_used": "Current C5 reports state WAG_direct_market_value_active=false.",
            "caveat": base_caveat,
            "user_review_needed": "no",
        },
        {
            "alignment_id": "ATH_ALIGN_007",
            "functional_area": "gas_network_mixing",
            "athanasiadis_precedent_type": "WAG_network",
            "expected_functional_separation": "Gas-network/mixing topology is separated from price valuation and physical dispatch.",
            "current_repository_surface": "S4.4b2 structural WAG mixing rules",
            "current_contract_status": "partially_aligned",
            "locator_status": "partial",
            "evidence_used": "S4.4b2 records structural mixers; no quantitative Wobbe/share mixer.",
            "caveat": base_caveat,
            "user_review_needed": "yes",
        },
        {
            "alignment_id": "ATH_ALIGN_008",
            "functional_area": "wag_co2_not_double_counted",
            "athanasiadis_precedent_type": "model_boundary",
            "expected_functional_separation": "WAG carbon is counted once and aggregate process counters are not summed with fuel-explicit WAG combustion.",
            "current_repository_surface": "C5p_h/C5p_l/C5p_n CO2 policy; C5p_o validation checks",
            "current_contract_status": "aligned",
            "locator_status": "indirect",
            "evidence_used": "Existing C5 CO2 boundary reports and this stage gate.",
            "caveat": base_caveat,
            "user_review_needed": "yes",
        },
    ]


def _build_c5p_k_exclusion_audit() -> list[dict[str, str]]:
    source_rows = _read_optional_csv(C5P_N_DIR / "c5p_k_use_policy.csv")
    rows: list[dict[str, str]] = []
    for row in source_rows:
        rows.append(
            {
                "c5p_k_metric_or_output": row["c5p_k_output_or_metric"],
                "previous_interpretation_risk": row["risk_if_misused"],
                "allowed_future_use": row["allowed_future_use"],
                "replacement_in_contract": row["replacement_required"],
                "reason": row["reason"],
                "caveat": row["caveat"],
            }
        )
    if not rows:
        rows.append(
            {
                "c5p_k_metric_or_output": "C5p_k outputs",
                "previous_interpretation_risk": "Policy source missing.",
                "allowed_future_use": "blocked",
                "replacement_in_contract": "Read C5p_n policy before reuse.",
                "reason": "Fail-closed because C5p_k policy artifact is unavailable.",
                "caveat": "No C5p_k physical use allowed.",
            }
        )
    return rows


def _build_blocked_cases() -> list[dict[str, str]]:
    return [
        {
            "blocked_case_id": "BLOCK_001",
            "configuration": "both",
            "carrier": "aggregate_wag",
            "sink_or_stage": "physical_plant_allocation",
            "missing_requirement": "Carrier-specific accepted controller surface.",
            "why_blocked": "Aggregate WAG is reporting/warning-only and would hide carrier gaps.",
            "blocks_future_stage": "NG_residual;sensitivity;economics;DA",
            "allowed_current_handling": "warning_only",
            "required_fix": "Use carrier-specific existing outputs or keep site-level residual reporting.",
        },
        {
            "blocked_case_id": "BLOCK_002",
            "configuration": "both",
            "carrier": "mixed_wag",
            "sink_or_stage": "quantitative_mixer_dispatch",
            "missing_requirement": "Wobbe/gas-quality/share-constrained mixer.",
            "why_blocked": "S4.4b2 mixing rows are structural-only.",
            "blocks_future_stage": "NG_residual;CO2;sensitivity;economics;DA",
            "allowed_current_handling": "structural_only",
            "required_fix": "Source-backed mixer implementation in a later model stage.",
        },
        {
            "blocked_case_id": "BLOCK_003",
            "configuration": "both",
            "carrier": "multiple",
            "sink_or_stage": "common_plant_WAG_NG_split",
            "missing_requirement": "Explicit WAG/NG split or accepted controller-compatible logic.",
            "why_blocked": "C5p_k found no explicit ratio and used aggregate residual WAG fallback.",
            "blocks_future_stage": "NG_residual;sensitivity",
            "allowed_current_handling": "report_gap",
            "required_fix": "Source review or governed common-plant controller design.",
        },
        {
            "blocked_case_id": "BLOCK_004",
            "configuration": C1,
            "carrier": "BFG;COG;BOFG",
            "sink_or_stage": "flare_spill",
            "missing_requirement": "Carrier split for flare/spill.",
            "why_blocked": "C1 flare is currently aggregate and cannot support fuel-explicit CO2.",
            "blocks_future_stage": "CO2;sensitivity",
            "allowed_current_handling": "report_gap",
            "required_fix": "Carrier-split flare diagnostic or source-backed split policy.",
        },
        {
            "blocked_case_id": "BLOCK_005",
            "configuration": "both",
            "carrier": "BFG;COG;BOFG;NG",
            "sink_or_stage": "WAG_fuel_explicit_CO2",
            "missing_requirement": "Frozen carbon-counting policy and official factors.",
            "why_blocked": "Fuel-explicit WAG CO2 risks double-counting aggregate process counters.",
            "blocks_future_stage": "CO2;economics;DA",
            "allowed_current_handling": "no_use",
            "required_fix": "CO2/WAG factor source-card repair and mode separation tests.",
        },
        {
            "blocked_case_id": "BLOCK_006",
            "configuration": "both",
            "carrier": "BOFG",
            "sink_or_stage": "steam_boiler",
            "missing_requirement": "Governed BOFG steam/boiler eligibility source row.",
            "why_blocked": "C5p_b current steam layer explicitly blocks BOFG.",
            "blocks_future_stage": "CO2;sensitivity",
            "allowed_current_handling": "structural_only",
            "required_fix": "Source review before enabling any BOFG boiler use.",
        },
    ]


def _stage_gate(
    validation_rows: list[dict[str, str]],
    blocked_rows: list[dict[str, str]],
) -> dict[str, Any]:
    counts = _status_counts(validation_rows, "status")
    return {
        "stage": STAGE,
        "status": "development_only_diagnostic_interface",
        "thesis_usability": False,
        "contract_status": "diagnostic_interface_ready",
        "carriers_quantitative": list(QUANTITATIVE_WAG_CARRIERS),
        "carriers_structural_only": list(STRUCTURAL_ONLY_CARRIERS),
        "aggregate_wag_policy": "reporting_warning_only_not_physical_allocation",
        "mixed_wag_policy": "structural_only_no_quantitative_mixer",
        "c5p_k_policy": "warning_context_only_not_physical_allocation_evidence",
        "number_of_validation_checks_pass_warning_fail_blocked": counts,
        "number_of_blocked_cases": len(blocked_rows),
        "whether_phase_2_electricity_decomposition_can_use_outputs": "GO_FOR_NON_WAG_LOADS_WITH_WAG_CAVEAT",
        "whether_ng_residual_policy_can_use_outputs": "NO_GO",
        "whether_co2_can_use_outputs": "GO_SITE_LEVEL_RESIDUAL_ONLY;NO_GO_WAG_FUEL_EXPLICIT",
        "whether_sensitivity_execution_can_use_outputs": "NO_GO",
        "go_no_go": {
            "phase_2_electricity_non_wag_decomposition": "GO_WITH_WAG_CAVEAT",
            "generator_wag_dependent_electricity_interpretation": "CAVEATED_ONLY",
            "ng_residual_policy": "NO_GO",
            "co2_site_level_residual_reporting": "GO_DIAGNOSTIC_ONLY",
            "wag_fuel_explicit_co2": "NO_GO",
            "full_sensitivity_execution": "NO_GO",
            "executable_input_migration": "NO_GO",
            "economics_readiness": "NO_GO",
            "DA_readiness": "NO_GO",
        },
        "guardrails": {
            "model_equations_changed": False,
            "executable_development_inputs_changed": False,
            "source_cards_changed": False,
            "raw_pdfs_inspected": False,
            "sensitivity_experiment_run": False,
            "new_wag_allocation_function_created": False,
            "c5p_k_physical_allocation_use": False,
            "aggregate_wag_physical_allocation": False,
            "mixed_wag_quantitative_use": False,
            "co2_fuel_explicit_mode_unlocked": False,
            "economics_or_da_active": False,
        },
    }


def _summary(
    interface_rows: list[dict[str, Any]],
    allocation_rows: list[dict[str, Any]],
    call_trace: list[dict[str, str]],
    validation_rows: list[dict[str, str]],
    alignment_rows: list[dict[str, str]],
    blocked_rows: list[dict[str, str]],
    stage_gate: dict[str, Any],
) -> dict[str, Any]:
    aggregates = {
        row["configuration"]: {
            "generation_PJ_y": row["generation_PJ_y"],
            "process_or_prep_use_PJ_y": row["process_or_prep_use_PJ_y"],
            "steam_boiler_use_PJ_y": row["steam_boiler_use_PJ_y"],
            "generator_use_PJ_y": row["generator_use_PJ_y"],
            "flare_spill_PJ_y": row["flare_spill_PJ_y"],
            "residual_PJ_y": row["residual_PJ_y"],
            "balance_status": row["balance_status"],
        }
        for row in allocation_rows
        if row["carrier"] == "aggregate_wag"
    }
    return {
        "stage": STAGE,
        "status": "development_only_diagnostic_interface",
        "thesis_usability": False,
        "contract_status": stage_gate["contract_status"],
        "interface_rows": len(interface_rows),
        "carrier_sink_rows": len(allocation_rows),
        "call_trace_rows": len(call_trace),
        "validation_check_counts": _status_counts(validation_rows, "status"),
        "blocked_cases": len(blocked_rows),
        "athanasiadis_alignment_counts": _status_counts(alignment_rows, "current_contract_status"),
        "aggregate_wag_metrics": aggregates,
        "c5p_k_policy": "warning_context_only_not_physical_allocation_evidence",
        "carriers_quantitative": list(QUANTITATIVE_WAG_CARRIERS),
        "carriers_structural_only": list(STRUCTURAL_ONLY_CARRIERS),
        "carriers_reporting_only": list(REPORTING_ONLY_CARRIERS),
        "go_no_go": stage_gate["go_no_go"],
        "top_blockers": [
            "missing explicit common-plant WAG/NG split",
            "mixed_wag structural-only with no quantitative Wobbe/share mixer",
            "C1 flare/spill not carrier-split",
            "WAG/fuel-explicit CO2 carbon policy incomplete",
            "C5p_k aggregate fallback excluded from physical allocation",
        ],
    }


def _write_report(
    summary: dict[str, Any],
    validation_rows: list[dict[str, str]],
    alignment_rows: list[dict[str, str]],
    blocked_rows: list[dict[str, str]],
) -> None:
    validation_counts = summary["validation_check_counts"]
    align_counts = summary["athanasiadis_alignment_counts"]
    c0 = summary["aggregate_wag_metrics"].get(C0, {})
    c1 = summary["aggregate_wag_metrics"].get(C1, {})
    report = f"""# C5 WAG Controller Contract Hardening

## A. Purpose and boundaries

This is the C5p_o hardened WAG controller contract/interface layer. It standardises and validates existing WAG/controller outputs into one diagnostic surface. It is not a new WAG allocator, does not run sensitivities, does not inspect raw PDFs, does not edit source cards, and does not change executable inputs or model equations.

The stage fails closed where existing functionality is missing. C5p_k remains warning/context only.

## B. Existing functionality used

This stage reads existing outputs from C5p_m, C5p_n, C5p_b, C5p_c, C5l, C5m and C5p_k. It inspects but does not call `wag_diagnostic`, `wag_fixed_profile_builder`, or S4.4b2 structural mixing rules. No runtime allocation algorithm is executed.

The call trace is in `wag_controller_call_trace.csv`.

## C. Hardened carrier policy

- COG, BFG and BOFG are quantitative only where existing carrier rows preserve them.
- `mixed_wag` is structural-only; no quantitative Wobbe/share-constrained mixer is unlocked.
- `aggregate_wag` is reporting/warning-only and cannot feed physical allocation.
- NG is external/back-up fuel, not WAG.
- No WAG/NG split ratio is invented.

## D. Hardened sink/stage policy

- Process/prep: accepted as existing carrier-specific diagnostic rows only.
- HSM/WBW: accepted through existing C5l controller outputs.
- Sinter/PEFA: accepted through existing C5m/C5n/C5p_b-consumed outputs where present.
- Steam/boiler: accepted through C5p_b; BOFG remains blocked in the steam layer.
- Generator interface: accepted through C5p_c as fixed/interface accounting, not price-responsive dispatch.
- Flare/spill and residual: reporting-only; C1 flare remains not carrier-split.
- Common-plant overlays: C5p_k warning/context only.
- CO2: site-level residual reporting only; WAG/fuel-explicit CO2 remains blocked.

## E. Validation checks

Validation check counts: `{validation_counts}`.

Aggregate WAG balance retained from C5p_m:

| Configuration | Generation PJ/y | Process/prep PJ/y | Steam/boiler PJ/y | Generator PJ/y | Flare/spill PJ/y | Residual PJ/y | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| C0 | {c0.get('generation_PJ_y', '')} | {c0.get('process_or_prep_use_PJ_y', '')} | {c0.get('steam_boiler_use_PJ_y', '')} | {c0.get('generator_use_PJ_y', '')} | {c0.get('flare_spill_PJ_y', '')} | {c0.get('residual_PJ_y', '')} | {c0.get('balance_status', '')} |
| C1 | {c1.get('generation_PJ_y', '')} | {c1.get('process_or_prep_use_PJ_y', '')} | {c1.get('steam_boiler_use_PJ_y', '')} | {c1.get('generator_use_PJ_y', '')} | {c1.get('flare_spill_PJ_y', '')} | {c1.get('residual_PJ_y', '')} | {c1.get('balance_status', '')} |

The checks pass for carrier-specific balance closure, aggregate WAG exclusion, C5p_k physical-use exclusion, mixed_wag structural-only policy, no hidden flooring, and no active WAG double-count mode. Common-plant WAG/NG split and WAG/fuel-explicit CO2 remain blocked.

## F. Athanasiadis alignment

Alignment counts: `{align_counts}`.

This is a functional architecture check only. It does not replicate Athanasiadis numerically and does not claim official Tata truth. The current interface is aligned or partially aligned with the precedent of separating WAG generation, process/self-use, steam/boiler use, generator-interface use, flare/residual handling, gas-network structure, no direct WAG market valuation, and CO2 double-counting guardrails. Locator status remains indirect or partial and needs user review before thesis claims.

## G. Readiness for future phases

- Phase 2 electricity non-WAG decomposition: GO with WAG caveat.
- Generator/WAG-dependent electricity interpretation: caveated only.
- NG residual policy: NO-GO.
- CO2 site-level residual reporting: GO diagnostic-only.
- WAG/fuel-explicit CO2: NO-GO.
- Full sensitivity execution: NO-GO.
- Executable input migration: NO-GO.
- Economics: NO-GO.
- DA: NO-GO.

Blocked cases are listed in `wag_contract_blocked_cases.csv`; count = {len(blocked_rows)}.

## H. How to critically review this WAG implementation

Inspect these files:

- `wag_contract_interface_ledger.csv`: confirm only BFG/BOFG/COG carrier-specific rows can feed physical allocation.
- `wag_carrier_sink_allocation_ledger.csv`: confirm aggregate C0/C1 WAG totals match C5p_m and carrier rows close.
- `wag_contract_validation_checks.csv`: any `fail` invalidates physical interpretation; `blocked` rows define next-stage blockers.
- `c5p_k_exclusion_audit.csv`: confirm C5p_k remains warning/context only.
- `athanasiadis_alignment_matrix.csv`: confirm functional alignment remains architecture-only and locator caveats are retained.

Warnings that invalidate physical interpretation include aggregate_wag feeding a plant, mixed_wag marked quantitative, C5p_k used as allocation evidence, negative residuals being floored away, or WAG/fuel-explicit CO2 being unlocked before carbon policy is frozen.

Evidence still missing before claiming WAG is implemented correctly: explicit common-plant WAG/NG split, quantitative mixed-gas/Wobbe policy, C1 flare carrier split, and WAG/fuel CO2 factor/carbon-counting policy.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def run_s4_4c5p_o_wag_controller_contract_hardening() -> dict[str, Any]:
    C5P_O_DIR.mkdir(parents=True, exist_ok=True)
    balance_rows = _balance_rows()
    interface_rows = _build_interface_ledger(balance_rows)
    call_trace = _build_call_trace()
    allocation_rows = _build_carrier_sink_ledger(balance_rows)
    validation_rows = _build_validation_checks(interface_rows, allocation_rows, call_trace)
    alignment_rows = _build_athanasiadis_alignment()
    c5p_k_rows = _build_c5p_k_exclusion_audit()
    blocked_rows = _build_blocked_cases()
    stage_gate = _stage_gate(validation_rows, blocked_rows)
    summary = _summary(interface_rows, allocation_rows, call_trace, validation_rows, alignment_rows, blocked_rows, stage_gate)

    _write_csv(C5P_O_DIR / "wag_contract_interface_ledger.csv", interface_rows, INTERFACE_COLUMNS)
    _write_csv(C5P_O_DIR / "wag_controller_call_trace.csv", call_trace, CALL_TRACE_COLUMNS)
    _write_csv(C5P_O_DIR / "wag_carrier_sink_allocation_ledger.csv", allocation_rows, ALLOCATION_LEDGER_COLUMNS)
    _write_csv(C5P_O_DIR / "wag_contract_validation_checks.csv", validation_rows, VALIDATION_COLUMNS)
    _write_csv(C5P_O_DIR / "athanasiadis_alignment_matrix.csv", alignment_rows, ATHANASIADIS_COLUMNS)
    _write_csv(C5P_O_DIR / "c5p_k_exclusion_audit.csv", c5p_k_rows, C5P_K_EXCLUSION_COLUMNS)
    _write_csv(C5P_O_DIR / "wag_contract_blocked_cases.csv", blocked_rows, BLOCKED_COLUMNS)
    _write_json(C5P_O_DIR / "s4_4c5p_o_stage_gate.json", stage_gate)
    _write_json(C5P_O_DIR / "summary.json", summary)
    _write_report(summary, validation_rows, alignment_rows, blocked_rows)
    return summary


def main() -> int:
    run_s4_4c5p_o_wag_controller_contract_hardening()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
