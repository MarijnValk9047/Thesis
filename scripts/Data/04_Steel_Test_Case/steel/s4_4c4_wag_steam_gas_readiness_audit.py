"""S4.4c4 WAG, steam, and gas executable-readiness audit."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
STEEL_INPUT_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel"
SOURCE_EVIDENCE = STEEL_INPUT_ROOT / "source_evidence"
S3_ROOT = STEEL_INPUT_ROOT / "S3"
S4_ROOT = STEEL_INPUT_ROOT / "S4"
B5A_INPUT_DIR = S4_ROOT / "s4_4b5a_asymmetric_c0_c1_correction/corrected_dev_inputs"
C1A_DIR = S4_ROOT / "s4_4c1a_asymmetric_24h_static_physical_regression"
C2_DIR = S4_ROOT / "s4_4c2_asymmetric_168h_static_physical_regression"
C3_DIR = S4_ROOT / "s4_4c3_static_physical_closeout"
C4_DIR = S4_ROOT / "s4_4c4_wag_steam_gas_readiness_audit"
ABSTRACTION_DOC = REPO_ROOT / "docs/optimisation/steel/S4/STEEL_WAG_STEAM_GAS_NETWORK_ABSTRACTION.md"
MODELBUILDER = REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py"
STATIC_WRAPPER = REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_asymmetric_static_regression.py"

C0 = "C0_current_BF_BOF_reference"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
GATE_DECISION = "ready_for_s4_4c4b_with_policy_decisions"


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    columns = list(fieldnames or [])
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    if not columns:
        columns = ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source_inventory() -> list[dict[str, Any]]:
    source_addendum = _relative(SOURCE_EVIDENCE / "athanasiadis_gas_network_source_card_addendum.csv")
    candidate_register = _relative(SOURCE_EVIDENCE / "steel_candidate_parameter_evidence_register.csv")
    source_card_register = _relative(SOURCE_EVIDENCE / "steel_source_card_register.csv")
    s3_selected = _relative(S3_ROOT / "s3_provisional_dev_input/s3_wag_selected_dev_inputs.csv")
    s3_demands = _relative(S3_ROOT / "s3_provisional_dev_input/s3_wag_demand_coefficients.csv")
    s3_policy = _relative(S3_ROOT / "s3_candidate_review/s3_wag_policy_decision_register.csv")
    s3_driver = _relative(S3_ROOT / "s3_candidate_review/s3_1_wag_driver_basis_reconciliation_register.csv")
    s3_power = _relative(S3_ROOT / "s3_candidate_review/s3_2_wag_power_interface_policy_register.csv")
    s3_final = _relative(S3_ROOT / "s3_candidate_review/s3_3j_final_case_assumption_register.csv")
    s3_status = _relative(S3_ROOT / "s3_candidate_review/s3_3j_source_status_update.csv")
    b5a_io = _relative(B5A_INPUT_DIR / "process_io_coefficients.csv")
    b5a_wag_gen = _relative(B5A_INPUT_DIR / "wag_generation_coefficients.csv")
    b5a_wag_sink = _relative(B5A_INPUT_DIR / "wag_sink_eligibility.csv")
    b5a_utility_demands = _relative(B5A_INPUT_DIR / "utility_demands.csv")
    b5a_utility_assets = _relative(B5A_INPUT_DIR / "utility_conversion_assets.csv")

    rows: list[dict[str, Any]] = [
        {
            "parameter_or_structure": "LHV_BFG",
            "source_file": f"{source_addendum}; {candidate_register}; {s3_selected}",
            "source_card_id": "STEEL-SC-0021; STEEL-SC-0001",
            "candidate_id": "S33I-ATH-GAS-010; STEEL-WAG-EVID-0003; S30B_WAG_DEV_002",
            "value_or_structure": "3.85 in Athanasiadis addendum; S3 central 3.35 with JRC range 2.7-4.0",
            "unit": "MJ/Nm3",
            "basis": "lower heating value",
            "status": "ready_existing_source_with_development_selection",
            "can_use_for_executable_development": "yes",
            "caveat": "Composition and basis dependent; not Tata-measured hourly gas quality.",
        },
        {
            "parameter_or_structure": "LHV_COG",
            "source_file": f"{source_addendum}; {candidate_register}; {s3_selected}",
            "source_card_id": "STEEL-SC-0021; STEEL-SC-0001",
            "candidate_id": "S33I-ATH-GAS-008; STEEL-WAG-EVID-0006; S30B_WAG_DEV_006",
            "value_or_structure": "18.5 in Athanasiadis addendum; S3 central 18.7 with JRC range 17.4-20.0",
            "unit": "MJ/Nm3",
            "basis": "lower heating value",
            "status": "ready_existing_source_with_development_selection",
            "can_use_for_executable_development": "yes",
            "caveat": "Raw/cleaned COG basis differs; use one basis consistently.",
        },
        {
            "parameter_or_structure": "LHV_BOFG",
            "source_file": f"{source_addendum}; {candidate_register}; {s3_selected}",
            "source_card_id": "STEEL-SC-0021; STEEL-SC-0001",
            "candidate_id": "S33I-ATH-GAS-009; STEEL-WAG-EVID-0009; S30B_WAG_DEV_004",
            "value_or_structure": "8.6 in Athanasiadis addendum; S3 central 9.58 downstream of gasholder",
            "unit": "MJ/Nm3",
            "basis": "lower heating value",
            "status": "ready_existing_source_with_development_selection",
            "can_use_for_executable_development": "yes",
            "caveat": "BOFG/LDG naming and gas-holder basis must remain explicit.",
        },
        {
            "parameter_or_structure": "LHV_NG",
            "source_file": source_addendum,
            "source_card_id": "STEEL-SC-0021",
            "candidate_id": "S33I-ATH-GAS-011",
            "value_or_structure": "37.5",
            "unit": "MJ/Nm3",
            "basis": "natural gas lower heating value",
            "status": "ready_existing_source_for_conversion_context",
            "can_use_for_executable_development": "yes",
            "caveat": "Conversion context only; does not approve natural-gas cost or Vattenfall electricity offset.",
        },
        {
            "parameter_or_structure": "BFG generation coefficient",
            "source_file": f"{candidate_register}; {s3_selected}; {b5a_wag_gen}; {s3_driver}",
            "source_card_id": "STEEL-SC-0001; S33_CAND_001_CALIBRATION_ANCHOR",
            "candidate_id": "STEEL-WAG-EVID-0001; S30B_WAG_DEV_001",
            "value_or_structure": "1600",
            "unit": "Nm3/t_hot_metal",
            "basis": "BF hot-metal activity",
            "status": "ready_development_assumption",
            "can_use_for_executable_development": "yes",
            "caveat": "Public generic coefficient; S3.1b fixed the driver to BF hot metal rather than BOF liquid steel.",
        },
        {
            "parameter_or_structure": "COG generation coefficient",
            "source_file": f"{candidate_register}; {s3_selected}; {b5a_wag_gen}; {s3_driver}",
            "source_card_id": "STEEL-SC-0001; S33_CAND_001_CALIBRATION_ANCHOR",
            "candidate_id": "STEEL-WAG-EVID-0004; S30B_WAG_DEV_005",
            "value_or_structure": "365",
            "unit": "m3/t_dry_coal",
            "basis": "dry coal or coking activity",
            "status": "ready_development_assumption",
            "can_use_for_executable_development": "yes",
            "caveat": "Coal-basis coefficient must not be applied to coke or liquid-steel activity without conversion.",
        },
        {
            "parameter_or_structure": "BOFG generation coefficient",
            "source_file": f"{candidate_register}; {s3_selected}; {b5a_wag_gen}; {s3_driver}",
            "source_card_id": "STEEL-SC-0001; S33_CAND_001_CALIBRATION_ANCHOR",
            "candidate_id": "STEEL-WAG-EVID-0007; S30B_WAG_DEV_003",
            "value_or_structure": "75",
            "unit": "Nm3/t_liquid_steel",
            "basis": "BOF liquid steel activity",
            "status": "ready_development_assumption",
            "can_use_for_executable_development": "yes",
            "caveat": "Suppressed-combustion recovery proxy; not a blow-transient model.",
        },
        {
            "parameter_or_structure": "Coking Plant 1 WAGs COK1 structure",
            "source_file": f"{source_addendum}; {b5a_io}; {b5a_wag_sink}",
            "source_card_id": "STEEL-SC-0021",
            "candidate_id": "S33I-ATH-GAS-003",
            "value_or_structure": "CP1 can consume BFG, COG, or WAGs COK1 mixture; B5a has wag_cok1_mix structural port.",
            "unit": "structural",
            "basis": "Athanasiadis Figure 31 structural sink",
            "status": "structural_ready_numeric_split_needed",
            "can_use_for_executable_development": "conditional",
            "caveat": "No public fixed BFG/COG split; a policy choice is needed for executable allocation.",
        },
        {
            "parameter_or_structure": "Coking Plant 2 pure COG structure",
            "source_file": b5a_io,
            "source_card_id": "STEEL-SC-0021",
            "candidate_id": "S4.4b5a CP2 gas-structure correction",
            "value_or_structure": "CP2 has COG structural gas input and no inherited generic WAG mixture.",
            "unit": "structural",
            "basis": "B5a source-card/workbook correction",
            "status": "structural_ready_capacity_proxy_only",
            "can_use_for_executable_development": "conditional",
            "caveat": "CP2-specific gas demand or capacity remains proxy-governed.",
        },
        {
            "parameter_or_structure": "Sinter COG use",
            "source_file": _relative(ABSTRACTION_DOC),
            "source_card_id": "STEEL-SC-0021",
            "candidate_id": "target_abstraction_alpha_fuel_Sinter_COG",
            "value_or_structure": "Target abstraction says Sinter Plant consumes COG; candidate alpha 0.10 GJ/t sinter.",
            "unit": "GJ/t_sinter candidate",
            "basis": "Athanasiadis Figure 31 structural sink plus abstraction candidate",
            "status": "policy_decision_required",
            "can_use_for_executable_development": "conditional",
            "caveat": "No accepted source-register coefficient found in targeted S2/S3 inputs.",
        },
        {
            "parameter_or_structure": "HSM COG/NG eligibility",
            "source_file": f"{source_addendum}; {b5a_wag_sink}",
            "source_card_id": "STEEL-SC-0021",
            "candidate_id": "S33I-ATH-GAS-002",
            "value_or_structure": "HSM can consume COG or natural gas; B5a eligibility includes WAG_HSM_mixer.",
            "unit": "structural",
            "basis": "Athanasiadis Figure 31 structural sink",
            "status": "eligibility_ready_coefficient_missing",
            "can_use_for_executable_development": "no",
            "caveat": "No accepted fuel-demand coefficient for HSM was found.",
        },
        {
            "parameter_or_structure": "Pelletizing Malerij BOFG/NG eligibility",
            "source_file": f"{source_addendum}; {_relative(ABSTRACTION_DOC)}",
            "source_card_id": "STEEL-SC-0021",
            "candidate_id": "S33I-ATH-GAS-005",
            "value_or_structure": "Malerij can consume BOFG, natural gas, or mixture.",
            "unit": "structural",
            "basis": "Athanasiadis Figure 31 structural sink",
            "status": "eligibility_ready_coefficient_missing",
            "can_use_for_executable_development": "no",
            "caveat": "No accepted fuel-demand coefficient for PEFA Malerij was found.",
        },
        {
            "parameter_or_structure": "Pelletizing Branderij COG/NG eligibility",
            "source_file": f"{source_addendum}; {_relative(ABSTRACTION_DOC)}",
            "source_card_id": "STEEL-SC-0021",
            "candidate_id": "S33I-ATH-GAS-004",
            "value_or_structure": "Branderij can consume COG, natural gas, or mixture.",
            "unit": "structural",
            "basis": "Athanasiadis Figure 31 structural sink",
            "status": "eligibility_ready_coefficient_missing",
            "can_use_for_executable_development": "no",
            "caveat": "No accepted fuel-demand coefficient for PEFA Branderij was found.",
        },
        {
            "parameter_or_structure": "Boiler and steam subsystem",
            "source_file": f"{source_addendum}; {candidate_register}; {s3_selected}; {b5a_utility_assets}",
            "source_card_id": "STEEL-SC-0021; STEEL-SC-0020; STEEL-SC-0008",
            "candidate_id": "S33I-ATH-GAS-006; STEEL-WAG-EVID-0048; S30B_WAG_DEV_018",
            "value_or_structure": "Boilers consume WAG/NG for steam; selected S3 boiler proxy 0.875 efficiency, abstraction candidate 0.90.",
            "unit": "dimensionless efficiency candidate",
            "basis": "boiler-to-steam useful energy",
            "status": "ready_sensitivity_only",
            "can_use_for_executable_development": "conditional",
            "caveat": "Boiler efficiency alone does not define hourly steam demand or boiler capacity.",
        },
        {
            "parameter_or_structure": "6 PJ/y steam/boiler placeholder and 3 PJ/y NG + 3 PJ/y WAG split",
            "source_file": f"{s3_final}; {s3_status}; {b5a_utility_demands}",
            "source_card_id": "S33J-ASSUMP-003; S33J-ASSUMP-004; S33J-ASSUMP-005",
            "candidate_id": "S4.4b4 utility demand migration",
            "value_or_structure": "6 PJ/y aggregate utility context, split internally into 3 PJ/y NG and 3 PJ/y WAG placeholders.",
            "unit": "PJ/y",
            "basis": "S3.3j boundary-allocation placeholder",
            "status": "ready_development_assumption_reporting_only",
            "can_use_for_executable_development": "conditional",
            "caveat": "Annual allocation context only; not hidden hourly dispatch truth.",
        },
        {
            "parameter_or_structure": "Vattenfall IJ01/VN24/VN25 interface",
            "source_file": f"{source_card_register}; {source_addendum}; {candidate_register}; {s3_power}; {b5a_utility_assets}",
            "source_card_id": "STEEL-SC-0014; STEEL-SC-0015; STEEL-SC-0016; STEEL-SC-0021",
            "candidate_id": "S33I-ATH-GAS-007; STEEL-WAG-EVID-0043; STEEL-WAG-EVID-0044; S32_WAG_POWER_001",
            "value_or_structure": "Vattenfall structural interface exists; selected policy is no export and no WAG revenue.",
            "unit": "structural/interface",
            "basis": "IJ01/VN24/VN25 public/source-card interface evidence",
            "status": "structural_ready_cap_policy_needed",
            "can_use_for_executable_development": "conditional",
            "caveat": "No hourly contract dispatch, transfer price, or safe base cap; keep reporting/capped only.",
        },
        {
            "parameter_or_structure": "Flaring and residual WAG spillage",
            "source_file": f"{candidate_register}; {s3_policy}; {b5a_wag_sink}",
            "source_card_id": "STEEL-SC-0007; REPO-S3-WAG-BOUNDARY",
            "candidate_id": "STEEL-WAG-EVID-0023; S30B_WAG_POL_E3",
            "value_or_structure": "Explicit flare/spillage sink is eligible for BFG/COG/BOFG and has no market value.",
            "unit": "structural",
            "basis": "residual WAG closure and complete oxidation first diagnostic",
            "status": "ready_for_carrier_specific_physical_closure",
            "can_use_for_executable_development": "yes",
            "caveat": "Flaring can close infeasibility but must be reported by carrier; optional tie-breaker needs policy.",
        },
        {
            "parameter_or_structure": "COG holder evidence",
            "source_file": f"{source_addendum}; {_relative(ABSTRACTION_DOC)}",
            "source_card_id": "STEEL-SC-0021",
            "candidate_id": "not_found_as_executable_input",
            "value_or_structure": "Gas holders are acknowledged as real gas-network detail but excluded from hourly base abstraction.",
            "unit": "structural",
            "basis": "source-card-first audit",
            "status": "not_needed_for_base_no_wag_storage",
            "can_use_for_executable_development": "no",
            "caveat": "No WAG or steam stores should be created for the hourly base model.",
        },
    ]
    return rows


def _target_component_for_input(table: str, row: dict[str, str]) -> str:
    if table == "wag_generation_coefficients.csv":
        return f"{row.get('wag_carrier', '')}_production_from_{row.get('process_id', '')}"
    if table == "wag_sink_eligibility.csv":
        sink = row.get("sink_asset", "")
        if "flare" in sink.lower():
            return "carrier_specific_flare_link"
        if "Vattenfall" in sink:
            return "Vattenfall_interface_sink"
        if "BOILER" in sink or "BOILERS" in sink:
            return "aggregated_boiler_fuel_sink"
        if "COK1" in sink:
            return "CP1_WAG_COK1_process_sink"
        if "HSM" in sink:
            return "HSM_process_fuel_sink"
        return "WAG_sink_eligibility"
    if table == "process_io_coefficients.csv":
        process_id = row.get("process_id", "")
        if "Vattenfall" in process_id:
            return "Vattenfall_reporting_conversion"
        if "BOILER" in process_id or "BOILERS" in process_id:
            return "boiler_to_steam_conversion"
        if "flare" in process_id.lower():
            return "flare_spillage_conversion"
        if process_id == "coking_plant_1":
            return "CP1_WAG_COK1_structural_port"
        if process_id == "coking_plant_2":
            return "CP2_pure_COG_structural_port"
    if table == "utility_demands.csv":
        return "annual_utility_context"
    if table == "utility_conversion_assets.csv":
        return row.get("asset_id", "utility_conversion_asset")
    return "unclassified"


def _is_row_currently_executable(table: str, row: dict[str, str]) -> bool:
    if table != "wag_generation_coefficients.csv":
        return False
    return (
        row.get("configuration_id") == C0
        and (row.get("process_id"), row.get("wag_carrier"))
        in {
            ("blast_furnace_6", "BFG"),
            ("coking_plant_1", "COG"),
            ("basic_oxygen_furnace", "BOFG"),
        }
    )


def _existing_input_mapping() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tables = [
        "wag_generation_coefficients.csv",
        "wag_sink_eligibility.csv",
        "process_io_coefficients.csv",
        "utility_demands.csv",
        "utility_conversion_assets.csv",
    ]
    for table in tables:
        for index, row in enumerate(_read_csv(B5A_INPUT_DIR / table), start=1):
            if table in {"process_io_coefficients.csv", "utility_demands.csv", "utility_conversion_assets.csv"}:
                text = " ".join(str(value) for value in row.values()).lower()
                if not any(term in text for term in ["wag", "cog", "bfg", "bofg", "steam", "boiler", "vattenfall", "flare", "natural_gas"]):
                    continue
            carrier = row.get("wag_carrier") or row.get("input_material") or row.get("utility_carrier") or row.get("input_carrier") or ""
            asset = row.get("process_id") or row.get("sink_asset") or row.get("asset_id") or ""
            executable = _is_row_currently_executable(table, row)
            rows.append(
                {
                    "current_input_table": table,
                    "row_id": row.get("candidate_id") or f"{table}:{index}",
                    "configuration": row.get("configuration_id", "both_or_not_config_specific"),
                    "carrier": carrier,
                    "asset_link_sink": asset,
                    "current_status": row.get("input_status") or row.get("cost_treatment") or "present",
                    "target_abstraction_component": _target_component_for_input(table, row),
                    "already_executable": str(executable).lower(),
                    "missing_fields": _missing_fields(table, row, executable),
                    "migration_needed": "false" if executable else "true",
                    "caveat": _input_mapping_caveat(table, row, executable),
                }
            )
    return rows


def _missing_fields(table: str, row: dict[str, str], executable: bool) -> str:
    if executable:
        return "carrier-specific balance and sink allocation still missing"
    if table == "wag_generation_coefficients.csv":
        return "not consumed by current C0/C1 WAG equations as row-specific production"
    if table == "wag_sink_eligibility.csv":
        return "sink flow variable, carrier balance equation, demand/cap where applicable"
    if table == "process_io_coefficients.csv":
        return "modelbuilder link variable and balance constraint"
    if table == "utility_demands.csv":
        return "hourly demand conversion and executable steam balance"
    if table == "utility_conversion_assets.csv":
        return "capacity/cap policy and executable conversion constraint"
    return "not assessed"


def _input_mapping_caveat(table: str, row: dict[str, str], executable: bool) -> str:
    if executable:
        return "Current C0 model reads this coefficient class but only reports aggregate WAG generated/flared, not a full carrier-specific network."
    if table == "wag_generation_coefficients.csv" and row.get("configuration_id") == C1:
        return "C1 WAG coefficients exist in inputs but current C1 static model reports WAG fields blank."
    if table == "wag_sink_eligibility.csv":
        return "Eligibility is migrated but no process, boiler, Vattenfall, or carrier-specific flare link is active in equations."
    if table == "utility_demands.csv":
        return "Reporting-only S3.3j annual context; not hidden hourly dispatch truth."
    if table == "utility_conversion_assets.csv" and "Vattenfall" in row.get("asset_id", ""):
        return "Interface row has efficiency proxy but no safe executable cap or dispatch/revenue rule."
    return "Present as development/review input only."


def _model_equation_mapping() -> list[dict[str, Any]]:
    return [
        {
            "concept": "WAG generation by carrier",
            "current_equation_status": "partial_aggregate_C0_only",
            "current_behavior": "C0 has expressions for bfg_generated, cog_generated, bofg_generated and an aggregate wag_generated expression; there are no Bus_BFG/Bus_COG/Bus_BOFG balances.",
            "code_file": _relative(MODELBUILDER),
            "line_refs": "456-470",
            "active_now": "partial",
            "caveat": "BF7 and CP2 coefficients are not read as distinct row-specific coefficients; C1 WAG fields are blank.",
        },
        {
            "concept": "WAG flare aggregate",
            "current_equation_status": "active_C0_aggregate_reporting",
            "current_behavior": "C0 audit and hourly rows set WAG_used=0 and WAG_flared=WAG_generated.",
            "code_file": _relative(MODELBUILDER),
            "line_refs": "899-901; 984-986",
            "active_now": "yes",
            "caveat": "This is a closure/reporting proxy, not carrier-specific flare links.",
        },
        {
            "concept": "Process-linked WAG sinks",
            "current_equation_status": "not_active",
            "current_behavior": "No CP1, CP2, Sinter, HSM, or PEFA process fuel sink variables are created.",
            "code_file": _relative(MODELBUILDER),
            "line_refs": "456-470; 899-901",
            "active_now": "no",
            "caveat": "Input rows exist, but all C0 generated WAG is flared.",
        },
        {
            "concept": "CP1 WAG COK1 active",
            "current_equation_status": "not_active",
            "current_behavior": "CP1 WAG_COK1 structure is present in B5a inputs but not converted into a model variable/constraint.",
            "code_file": _relative(MODELBUILDER),
            "line_refs": "no active CP1 WAG sink code",
            "active_now": "no",
            "caveat": "BFG/COG split or hierarchy decision is still needed.",
        },
        {
            "concept": "CP2 pure COG use active",
            "current_equation_status": "not_active",
            "current_behavior": "CP2 pure COG structural row exists, but no COG consumption equation exists.",
            "code_file": _relative(MODELBUILDER),
            "line_refs": "no active CP2 COG sink code",
            "active_now": "no",
            "caveat": "C0 CP2 should be pure COG if activated; C1 CP2 remains inactive.",
        },
        {
            "concept": "Sinter COG use active",
            "current_equation_status": "not_active",
            "current_behavior": "Sinter activity exists in C0 material model but no COG fuel sink is tied to it.",
            "code_file": _relative(MODELBUILDER),
            "line_refs": "no active Sinter COG sink code",
            "active_now": "no",
            "caveat": "Coefficient requires policy/development assumption acceptance.",
        },
        {
            "concept": "Boilers active",
            "current_equation_status": "not_active",
            "current_behavior": "No boiler fuel pool or boiler-to-steam conversion is created.",
            "code_file": _relative(MODELBUILDER),
            "line_refs": "no active boiler code",
            "active_now": "no",
            "caveat": "S3.3j 6 PJ/y is reporting context only.",
        },
        {
            "concept": "Steam balance active",
            "current_equation_status": "not_active",
            "current_behavior": "Hourly outputs leave steam blank; no steam bus balance exists.",
            "code_file": _relative(MODELBUILDER),
            "line_refs": "761-764; 987; 1169",
            "active_now": "no",
            "caveat": "Steam is not a store in target abstraction.",
        },
        {
            "concept": "Vattenfall interface active",
            "current_equation_status": "not_active",
            "current_behavior": "Input rows exist but no Vattenfall interface flow, cap, electricity offset, or reporting flow is solved.",
            "code_file": _relative(MODELBUILDER),
            "line_refs": "no active Vattenfall equation code",
            "active_now": "no",
            "caveat": "No revenue or merchant dispatch may be activated.",
        },
        {
            "concept": "WAG-to-electricity reporting active",
            "current_equation_status": "not_active",
            "current_behavior": "Static regression WAG summary reports generated/used/flared only.",
            "code_file": _relative(STATIC_WRAPPER),
            "line_refs": "263-279",
            "active_now": "no",
            "caveat": "Any electricity offset remains reporting-only until policy approval.",
        },
        {
            "concept": "WAG storage active",
            "current_equation_status": "inactive",
            "current_behavior": "No WAG store is created.",
            "code_file": _relative(MODELBUILDER),
            "line_refs": "no WAG store code",
            "active_now": "no",
            "caveat": "This matches the target hourly base policy.",
        },
        {
            "concept": "Direct WAG valuation active",
            "current_equation_status": "inactive_forbidden",
            "current_behavior": "FORBIDDEN_TERMS includes WAG_direct_market_value; gate flags direct WAG market valuation false.",
            "code_file": _relative(MODELBUILDER),
            "line_refs": "70-76; 1320-1324",
            "active_now": "no",
            "caveat": "Policy compliant.",
        },
    ]


def _gap_matrix() -> list[dict[str, Any]]:
    def row(component: str, target: str, inp: str, eq: str, src: str, ready: str, severity: str, action: str) -> dict[str, str]:
        return {
            "target_abstraction_component": component,
            "target_status": target,
            "current_input_status": inp,
            "current_equation_status": eq,
            "source_readiness": src,
            "implementation_readiness": ready,
            "blocker_severity": severity,
            "recommended_action": action,
        }

    return [
        row("BFG bus", "active", "BFG coefficient and eligibility rows present", "no BFG balance bus; only aggregate expression", "ready", "ready_with_schema_rows", "blocking", "Create BFG balance with production, sinks, and BFG flare."),
        row("COG bus", "active", "COG coefficient and eligibility rows present", "no COG balance bus; COG folded into aggregate WAG", "ready", "ready_with_policy_for_sinks", "blocking", "Create COG balance and keep CP2 pure COG in C0 only."),
        row("BOFG bus", "active", "BOFG coefficient and eligibility rows present", "no BOFG balance bus; BOFG folded into aggregate WAG", "ready", "ready_with_boiler_policy", "blocking", "Create BOFG balance; keep BOFG-to-boiler deferred unless approved."),
        row("natural gas bus", "active_external", "NG exists in C1/utility context and LHV candidate exists", "C1 NG-DRP active; WAG boiler/process NG not active", "ready_for_conversion_context", "partial", "warning", "Add NG fuel bus only for approved process/boiler sinks; no NG-to-Vattenfall base."),
        row("boiler fuel bus", "active_if_steam_layer_enabled", "annual placeholder and utility assets present", "absent", "partial", "policy_required", "blocking", "Do not activate until boiler/steam policy and hourly treatment are confirmed."),
        row("steam bus", "active_if_steam_layer_enabled", "6 PJ/y annual context only", "absent", "partial", "policy_required", "blocking", "Use reporting-only or approved hourly allocation; no steam store."),
        row("process fuel buses", "active_for_approved_sinks", "CP1/CP2 structural rows; HSM eligibility; PEFA target only", "absent", "partial", "policy_required", "blocking", "Implement only sinks with accepted coefficients; leave others eligibility/deferred."),
        row("carrier-specific flare links", "always_active", "flare eligibility present for BFG/COG/BOFG", "aggregate C0 flare only", "ready", "ready", "blocking", "Replace aggregate WAG_flared with carrier-specific flare variables."),
        row("BFG production BF6/BF7", "active when BF active", "BF6/BF7 BFG rows present", "C0 aggregate BF generation only; C1 blank", "ready", "ready", "warning", "Split by active BF where possible; zero BF7 in C1."),
        row("COG production KGF1/KGF2", "active when coking plant active", "KGF1/KGF2 COG rows present", "C0 aggregate coking generation only; C1 blank", "ready", "ready", "warning", "Tie COG generation to active coking plants and zero KGF2 in C1."),
        row("BOFG production BOF", "active when BOF active", "BOF BOFG rows present", "C0 aggregate BOFG expression only; C1 blank", "ready", "ready", "warning", "Use BOF activity in both configs where retained BOF is active."),
        row("CP1 WAG COK1 sink", "active", "BFG/COG eligible; BOFG not eligible", "absent", "structural_ready", "policy_required", "blocking", "Confirm fixed split or process-first hierarchy before activation."),
        row("CP2 pure COG sink", "active_C0_inactive_C1", "CP2 pure COG structural row present", "absent", "structural_ready", "policy_required", "blocking", "Use COG-only in C0; force zero in C1."),
        row("Sinter COG sink", "active_if_sinter_active", "target abstraction candidate only", "absent", "structural_ready_coefficient_missing", "policy_required", "blocking", "Confirm alpha_fuel_Sinter_COG before executable use."),
        row("HSM COG/NG eligibility", "eligibility_then_parameter_gated", "WAG_HSM_mixer eligibility present", "absent", "coefficient_missing", "deferred", "warning", "Keep eligibility rows; do not activate without fuel coefficient."),
        row("PEFA Malerij BOFG/NG eligibility", "eligibility_then_parameter_gated", "target abstraction structural support", "absent", "coefficient_missing", "deferred", "warning", "Keep as deferred eligibility unless coefficient approved."),
        row("PEFA Branderij COG/NG eligibility", "eligibility_then_parameter_gated", "target abstraction structural support", "absent", "coefficient_missing", "deferred", "warning", "Keep as deferred eligibility unless coefficient approved."),
        row("aggregated boiler fuel links", "active_if_steam_layer_enabled", "utility asset and eligibility rows present", "absent", "partial", "policy_required", "blocking", "Start with reporting-only or approved bounded boiler sink."),
        row("aggregated boiler-to-steam link", "active_if_steam_layer_enabled", "proxy conversion row present, efficiency blank in S4 input", "absent", "ready_sensitivity_only", "policy_required", "blocking", "Confirm eta and demand before activation."),
        row("steam demand/load", "active_if_steam_layer_enabled", "6 PJ/y context only", "absent", "ready_reporting_only", "policy_required", "blocking", "Do not silently convert annual placeholder into hourly truth."),
        row("Vattenfall interface links", "capped_reporting_sink_only", "eligibility and efficiency proxy present; cap absent", "absent", "structural_ready_cap_missing", "policy_required", "blocking", "Keep inactive or diagnostic-only until cap policy is approved."),
        row("WAG-to-electricity reporting", "reporting_only", "utility conversion proxy present", "absent", "partial", "policy_required", "warning", "Report potential offset only, no objective credit."),
        row("flare emissions reporting", "reporting_if_CO2_active", "emission factors ready in candidate register", "absent", "ready", "deferred", "warning", "Add only as reporting/sensitivity, not ETS objective."),
        row("no WAG stores", "inactive", "no WAG store rows found", "inactive", "not_needed_for_base", "complete", "none", "Preserve no-storage hourly base."),
        row("no steam store", "inactive", "no steam store rows found", "inactive", "not_needed_for_base", "complete", "none", "Preserve no-storage hourly base."),
        row("no direct WAG market valuation", "inactive_forbidden", "forbidden term policy present", "inactive", "ready", "complete", "none", "Keep WAG direct valuation inactive."),
    ]


def _parameter_readiness() -> list[dict[str, Any]]:
    rows = [
        ("LHV_BFG", "ready_existing_source", "3.85", "MJ/Nm3", "S33I-ATH-GAS-010; STEEL-WAG-EVID-0003; S30B_WAG_DEV_002", "Use consistent selected value; composition sensitivity remains."),
        ("LHV_COG", "ready_existing_source", "18.5 or selected 18.7", "MJ/Nm3", "S33I-ATH-GAS-008; STEEL-WAG-EVID-0006; S30B_WAG_DEV_006", "Raw/cleaned basis caveat."),
        ("LHV_BOFG", "ready_existing_source", "8.6 or selected 9.58", "MJ/Nm3", "S33I-ATH-GAS-009; STEEL-WAG-EVID-0009; S30B_WAG_DEV_004", "BOFG/LDG basis caveat."),
        ("LHV_NG", "ready_existing_source", "37.5", "MJ/Nm3", "S33I-ATH-GAS-011", "Conversion context only."),
        ("alpha_BFG_BF", "ready_development_assumption", "1600", "Nm3/t_hot_metal", "STEEL-WAG-EVID-0001; S30B_WAG_DEV_001", "S3 selected development value."),
        ("alpha_COG_KGF", "ready_development_assumption", "365", "m3/t_dry_coal", "STEEL-WAG-EVID-0004; S30B_WAG_DEV_005", "Dry-coal basis must remain explicit."),
        ("alpha_BOFG_BOF", "ready_development_assumption", "75", "Nm3/t_liquid_steel", "STEEL-WAG-EVID-0007; S30B_WAG_DEV_003", "Suppressed combustion proxy."),
        ("alpha_fuel_KGF1", "policy_decision_required", "3.55 demand candidate; split unresolved", "GJ_fuel/t_coke", "STEEL-WAG-EVID-0052; S30B_WAG_DEMAND_004", "Need fixed BFG/COG split or hierarchy."),
        ("alpha_fuel_KGF2", "policy_decision_required", "capacity proxy only; pure COG structure", "proxy", "S4.4b5a CP2 structure", "Need CP2-specific or proxy demand decision."),
        ("alpha_fuel_Sinter_COG", "policy_decision_required", "0.10 candidate in abstraction only", "GJ/t_sinter", "STEEL_WAG_STEAM_GAS_NETWORK_ABSTRACTION.md", "No accepted S2/S3 source-register coefficient found."),
        ("alpha_fuel_HSM", "blocked_missing_source", "", "", "S33I-ATH-GAS-002 structural eligibility", "Eligibility exists; coefficient missing."),
        ("alpha_fuel_PEFA_Malerij", "blocked_missing_source", "", "", "S33I-ATH-GAS-005 structural eligibility", "Eligibility exists; coefficient missing."),
        ("alpha_fuel_PEFA_Branderij", "blocked_missing_source", "", "", "S33I-ATH-GAS-004 structural eligibility", "Eligibility exists; coefficient missing."),
        ("eta_boiler_steam", "ready_sensitivity_only", "0.875 selected S3; 0.90 abstraction candidate", "dimensionless", "STEEL-WAG-EVID-0048; S30B_WAG_DEV_018", "Generic boiler proxy; not Tata-specific."),
        ("steam residual or aggregate steam demand", "ready_development_assumption", "6", "PJ/y", "S33J-ASSUMP-003", "Annual context, not hourly truth."),
        ("boiler fuel cap if used", "blocked_missing_source", "", "", "none_found", "Capacity/min-load/co-firing ratios are unavailable."),
        ("Vattenfall interface cap if used", "policy_decision_required", "no base cap; 770 MW context blocked for dispatch", "MW context", "STEEL-WAG-EVID-0044; S30B_WAG_SEL_030", "Keep inactive/diagnostic unless cap policy approved."),
        ("eta_Vattenfall if reporting electricity", "ready_sensitivity_only", "0.3715", "fraction", "S30B_WAG_DEV_011; utility_conversion_assets.csv", "Reporting only; no revenue/offset."),
        ("flare emission factors if CO2 reporting active", "ready_existing_source", "BFG 247.4; COG 42.8; BOFG 191.9", "kg CO2/GJ", "STEEL-WAG-EVID-0025; 0026; 0027", "Reporting/sensitivity only; no ETS objective."),
        ("flare tie-breaker if used", "policy_decision_required", "not_selected", "diagnostic penalty", "A_NONZERO_FLARE_PENALTY_001", "Physical base can use zero cost; any tie-breaker must be labelled diagnostic."),
    ]
    return [
        {
            "parameter": name,
            "readiness_class": readiness,
            "value_or_status": value,
            "unit": unit,
            "evidence_or_candidate": evidence,
            "executable_recommendation": "can_use_after_policy" if readiness == "policy_decision_required" else (
                "use_for_development" if readiness.startswith("ready") else "do_not_use_as_executable"
            ),
            "thesis_usability": "false",
            "sensitivity_required": str(readiness in {"ready_development_assumption", "ready_sensitivity_only", "policy_decision_required"}).lower(),
            "caveat": caveat,
        }
        for name, readiness, value, unit, evidence, caveat in rows
    ]


def _policy_decisions() -> list[dict[str, Any]]:
    return [
        {
            "decision_id": "S44C4_POLICY_001",
            "decision_topic": "BOFG_to_boiler",
            "recommended_default": "deferred_or_sensitivity_only",
            "decision_needed": "Confirm whether BOFG can feed the aggregated boiler fuel pool in base.",
            "why_it_matters": "Activating BOFG-to-boiler reduces flaring and changes gas allocation.",
            "recommended_for_base": "false",
            "fallback_if_not_decided": "BOFG_to_BoilerFuel=0; BOFG may use process/interface/flare only.",
        },
        {
            "decision_id": "S44C4_POLICY_002",
            "decision_topic": "Vattenfall_interface",
            "recommended_default": "capped_reporting_sink_only_no_revenue_no_grid_offset",
            "decision_needed": "Confirm cap policy or keep inactive/diagnostic-only.",
            "why_it_matters": "A cap or offset can absorb large WAG volumes and materially change C0 flaring.",
            "recommended_for_base": "conditional",
            "fallback_if_not_decided": "Keep Vattenfall inactive except reporting potential.",
        },
        {
            "decision_id": "S44C4_POLICY_003",
            "decision_topic": "boiler_steam_demand",
            "recommended_default": "use_6_PJy_aggregate_only_as_S3_3j_development_placeholder",
            "decision_needed": "Confirm whether to convert annual placeholder into hourly load or keep reporting-only.",
            "why_it_matters": "A boiler/steam load creates a large WAG/NG sink and changes feasibility.",
            "recommended_for_base": "conditional",
            "fallback_if_not_decided": "Keep 6 PJ/y as validation/allocation context only.",
        },
        {
            "decision_id": "S44C4_POLICY_004",
            "decision_topic": "KGF1_WAG_split",
            "recommended_default": "fixed_process_linked_demand_not_price_responsive",
            "decision_needed": "Confirm fixed 50/50 BFG/COG energy split or process-first proportional hierarchy.",
            "why_it_matters": "Split determines BFG vs COG availability and flaring.",
            "recommended_for_base": "conditional",
            "fallback_if_not_decided": "Leave CP1 process sink structural but non-executable.",
        },
        {
            "decision_id": "S44C4_POLICY_005",
            "decision_topic": "KGF2_pure_COG",
            "recommended_default": "pure_COG_fixed_process_linked_demand_in_C0_inactive_in_C1",
            "decision_needed": "Confirm CP2 capacity/fuel demand proxy if CP2 process gas sink is activated.",
            "why_it_matters": "Avoids unsafe CP2=CP1 WAG mixture inheritance.",
            "recommended_for_base": "conditional",
            "fallback_if_not_decided": "Keep CP2 pure COG structure but no executable sink demand.",
        },
        {
            "decision_id": "S44C4_POLICY_006",
            "decision_topic": "Sinter_COG",
            "recommended_default": "fixed_COG_process_linked_demand_if_parameter_accepted",
            "decision_needed": "Approve or reject alpha_fuel_Sinter_COG candidate.",
            "why_it_matters": "Omitting Sinter COG while claiming full COG balance is an abstraction anti-pattern.",
            "recommended_for_base": "conditional",
            "fallback_if_not_decided": "Do not claim full process COG balance.",
        },
        {
            "decision_id": "S44C4_POLICY_007",
            "decision_topic": "HSM_PEFA_fuel",
            "recommended_default": "eligibility_rows_now_executable_only_with_coefficients",
            "decision_needed": "Approve fuel demand coefficients or defer HSM/PEFA sinks.",
            "why_it_matters": "These sinks can shift WAG/NG allocation and flaring.",
            "recommended_for_base": "false_until_coefficients_exist",
            "fallback_if_not_decided": "Keep eligibility/deferred rows only.",
        },
        {
            "decision_id": "S44C4_POLICY_008",
            "decision_topic": "flaring",
            "recommended_default": "carrier_specific_flare_always_active_zero_economic_value",
            "decision_needed": "Confirm whether optional tiny tie-breaker is allowed as diagnostic only.",
            "why_it_matters": "Flaring is required for closure but must not hide fake economics.",
            "recommended_for_base": "true_without_cost",
            "fallback_if_not_decided": "Use carrier-specific zero-cost physical flare and report volumes.",
        },
        {
            "decision_id": "S44C4_POLICY_009",
            "decision_topic": "WAG_and_steam_storage",
            "recommended_default": "inactive_in_hourly_base",
            "decision_needed": "None unless a future gas-holder or steam-accumulator task is explicitly opened.",
            "why_it_matters": "Storage would create intertemporal flexibility not supported by current evidence.",
            "recommended_for_base": "true",
            "fallback_if_not_decided": "No WAG stores and no steam store.",
        },
        {
            "decision_id": "S44C4_POLICY_010",
            "decision_topic": "electricity_from_WAG",
            "recommended_default": "reporting_only_no_objective_revenue_no_grid_offset",
            "decision_needed": "Confirm reporting-only treatment; do not activate revenue or offset in base.",
            "why_it_matters": "Electricity offset can become hidden WAG valuation.",
            "recommended_for_base": "reporting_only",
            "fallback_if_not_decided": "Keep WAG-to-electricity inactive.",
        },
    ]


def _implementation_plan() -> list[dict[str, Any]]:
    return [
        {
            "step_id": "S44C4B_IMPL_001",
            "scope": "input_tables",
            "exact_tables": "wag_generation_coefficients.csv; wag_sink_eligibility.csv; process_io_coefficients.csv; utility_demands.csv; utility_conversion_assets.csv; policy_modes.csv",
            "change": "Add/confirm carrier-specific rows for BFG/COG/BOFG generation, flare links, approved process sinks, and explicitly deferred sinks.",
            "daily_guardrail_interaction": "No direct interaction; production guardrail constrains process activity, which drives WAG generation and demand.",
            "reports_expected": "input migration manifest; policy-decision manifest; source/caveat fields for every executable row",
            "caveat": "Do not migrate validation-only or annual placeholder rows into hourly equations without policy approval.",
        },
        {
            "step_id": "S44C4B_IMPL_002",
            "scope": "model_variables",
            "exact_tables": "wag_generation_coefficients.csv; wag_sink_eligibility.csv",
            "change": "Add non-negative flow variables by hour and carrier: BFG/COG/BOFG production, process sink use, boiler use, Vattenfall/reporting use, and flare.",
            "daily_guardrail_interaction": "Variables remain continuous and driven by production/activity; guardrail prevents implausible batching from dominating WAG pattern.",
            "reports_expected": "WAG generated/used/flared by carrier and by sink",
            "caveat": "No WAG stores, no WAG market value, no NG-to-Vattenfall base.",
        },
        {
            "step_id": "S44C4B_IMPL_003",
            "scope": "model_constraints",
            "exact_tables": "wag_generation_coefficients.csv; wag_sink_eligibility.csv; process_io_coefficients.csv",
            "change": "Add carrier balance constraints: production equals approved sinks plus carrier-specific flare; enforce CP2 inactive in C1.",
            "daily_guardrail_interaction": "Balance equations should be checked under both fixed and guarded production shapes.",
            "reports_expected": "carrier balance residuals; sink use by process/boiler/Vattenfall/flare",
            "caveat": "CP1/KGF1 and KGF2 process sinks should remain fixed/process-linked, not price-responsive.",
        },
        {
            "step_id": "S44C4B_IMPL_004",
            "scope": "steam_boiler_optional_layer",
            "exact_tables": "utility_demands.csv; utility_conversion_assets.csv; policy_modes.csv",
            "change": "If policy approved, add aggregated boiler-fuel pool and boiler-to-steam conversion; otherwise keep as reporting/deferred.",
            "daily_guardrail_interaction": "Steam demand should be tied to process activity or approved annual allocation, not used as artificial flexibility.",
            "reports_expected": "steam production, steam demand, boiler fuel by carrier, residuals",
            "caveat": "6 PJ/y placeholder is annual context only unless explicitly converted.",
        },
        {
            "step_id": "S44C4B_IMPL_005",
            "scope": "Vattenfall_reporting_interface",
            "exact_tables": "wag_sink_eligibility.csv; utility_conversion_assets.csv; policy_modes.csv",
            "change": "Implement only a capped/reporting sink if cap policy is approved; no objective revenue and no grid offset in base.",
            "daily_guardrail_interaction": "Interface use should not be allowed to mask production-shape problems.",
            "reports_expected": "Vattenfall/interface WAG use, cap hits, potential reporting electricity, no-revenue flag",
            "caveat": "Full Vattenfall dispatch and Tata-Vattenfall contract logic remain out of scope.",
        },
        {
            "step_id": "S44C4B_IMPL_006",
            "scope": "rerun_sequence",
            "exact_tables": "completed/corrected S4.4c4b input folder",
            "change": "Revalidate inputs, rerun 24h C0/C1, then rerun 168h C0/C1 only if 24h passes.",
            "daily_guardrail_interaction": "Use the S4.4c3 daily production guardrail diagnostic as a comparison or base only if accepted by policy.",
            "reports_expected": "computational analytics; WAG generated/used/flared by carrier; NG use by sink; steam residuals; warnings about development assumptions",
            "caveat": "No DA, economics, bidding, stochasticity, CVaR, mFRR, product/export revenue, ETS objective, or WAG valuation.",
        },
    ]


def _stage_gate() -> dict[str, Any]:
    return {
        "stage": "S4.4c4_wag_steam_gas_readiness_audit",
        "decision": GATE_DECISION,
        "abstraction_doc_present": ABSTRACTION_DOC.exists(),
        "raw_pdfs_inspected": False,
        "model_equations_modified": False,
        "current_wag_behavior": "C0 aggregate WAG generation is fully flared; C1 WAG fields are blank; process/boiler/Vattenfall sinks are not active.",
        "source_readiness_summary": "Source cards and S3/S4 inputs provide WAG generation, LHV, process-first policy, flaring, structural gas sinks, utility placeholders, and Vattenfall interface evidence.",
        "blocking_sources_missing": "HSM/PEFA fuel coefficients, boiler cap/min-load/co-firing ratios, safe Vattenfall cap/dispatch policy, and accepted Sinter COG coefficient.",
        "policy_decisions_required_count": 8,
        "input_model_contract_status": "schema_can_represent_target_with_existing_16_tables_but_modelbuilder_needs_new_variables_and_constraints",
        "thesis_usable": False,
        "Tata_validated": False,
        "recommended_next_stage": "S4.4c4b minimal carrier-specific WAG balance and flare implementation after policy confirmations.",
    }


def run_s4_4c4_audit() -> dict[str, Any]:
    outputs: dict[str, list[dict[str, Any]] | dict[str, Any]] = {
        "s4_4c4_wag_source_inventory.csv": _source_inventory(),
        "s4_4c4_existing_wag_input_mapping.csv": _existing_input_mapping(),
        "s4_4c4_existing_model_equation_mapping.csv": _model_equation_mapping(),
        "s4_4c4_abstraction_gap_matrix.csv": _gap_matrix(),
        "s4_4c4_parameter_readiness.csv": _parameter_readiness(),
        "s4_4c4_policy_decisions_required.csv": _policy_decisions(),
        "s4_4c4_implementation_plan.csv": _implementation_plan(),
    }
    for filename, rows in outputs.items():
        assert isinstance(rows, list)
        _write_csv(C4_DIR / filename, rows)

    gate = _stage_gate()
    _write_json(C4_DIR / "s4_4c4_stage_gate.json", gate)
    _write_csv(C4_DIR / "s4_4c4_stage_gate.csv", [gate])
    return {"stage_gate": gate, "output_dir": _relative(C4_DIR), "row_counts": {name: len(rows) for name, rows in outputs.items() if isinstance(rows, list)}}


if __name__ == "__main__":
    result = run_s4_4c4_audit()
    print(f"S4.4c4 gate: {result['stage_gate']['decision']} | output_dir: {result['output_dir']}")
