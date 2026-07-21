"""Source-card readiness audit for the WAG/NG process-user hardening path.

This stage does not allocate fuel, alter a carrier balance, or promote any
parameter.  It reconciles the source-card evidence with the accepted C5p_o/q
diagnostic interfaces and records exactly which next controller adapters are
safe to design.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
STAGE = "S4.4c5p_r_remaining_process_user_controller_source_audit"
OUTPUT_DIR = ROOT / "data/03_Optimisation/inputs/assets/steel/S4/s4_4c5p_r_remaining_process_user_controller_source_audit"
REPORT_PATH = ROOT / "docs/optimisation/steel/S4/C5_REMAINING_PROCESS_USER_CONTROLLER_SOURCE_AUDIT.md"
SOURCE_CARD_DIR = ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards"
C5P_P_DIR = ROOT / "data/03_Optimisation/inputs/assets/steel/S4/s4_4c5p_p_wag_ng_controller_design"
C5P_Q_DIR = ROOT / "data/03_Optimisation/inputs/assets/steel/S4/s4_4c5p_q_wag_ng_controller_diagnostic_allocator"
C5P_O_DIR = ROOT / "data/03_Optimisation/inputs/assets/steel/S4/s4_4c5p_o_wag_controller_contract_hardening"

AUDIT_COLUMNS = [
    "process_user_id",
    "configuration_scope",
    "plant_function",
    "physical_role",
    "source_card",
    "source_locator",
    "activity_basis",
    "demand_basis",
    "allowed_carriers",
    "blocked_or_deferred_carriers",
    "current_controller_surface",
    "current_output_status",
    "source_strength",
    "minimum_hardening_level",
    "readiness_status",
    "recommended_action",
    "caveat",
]
EVIDENCE_COLUMNS = [
    "evidence_id",
    "process_user_id",
    "source_card",
    "source_locator",
    "evidence_statement",
    "evidence_type",
    "quantitative_candidate",
    "numeric_range_or_value",
    "unit",
    "model_use_status",
    "unresolved_condition",
]
READINESS_COLUMNS = [
    "process_user_id",
    "source_evidence_ready",
    "activity_mapping_ready",
    "carrier_eligibility_ready",
    "quantitative_demand_ready",
    "current_controller_output_ready",
    "priority_position_ready",
    "source_approved_for_migration",
    "allowed_next_step",
    "physical_allocation_status",
    "gating_reason",
]
UNRESOLVED_COLUMNS = [
    "configuration",
    "carrier",
    "unclassified_process_use_PJ_y",
    "possible_source_backed_contributors",
    "proven_contributor_now",
    "required_before_assignment",
    "current_handling",
]
ACTION_COLUMNS = [
    "priority",
    "action_id",
    "target_process_user",
    "action_type",
    "what_to_do",
    "expected_effect_on_wag_accounting",
    "must_not_do",
    "precondition",
    "success_criterion",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _file_record(path: Path) -> dict[str, str]:
    if not path.exists():
        return {"path": str(path.relative_to(ROOT)), "status": "missing", "sha256": ""}
    return {
        "path": str(path.relative_to(ROOT)),
        "status": "read",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _source_keyword_status() -> list[dict[str, str]]:
    requirements = [
        ("Coking_Plants_Parameters.md", "KGF_UNDERFIRING_GJ_PER_T_COKE", "SRC_CHECK_001"),
        ("Blast_Furnace_Parameters.md", "BF_hot_stove_heat_demand", "SRC_CHECK_002"),
        ("PELLETIZING_Parameters.md", "PEFA_GAS_FUEL_TOTAL_GJ_PER_T", "SRC_CHECK_003"),
        ("HSM_Parameters.md", "reheat", "SRC_CHECK_004"),
        ("SINTER_Parameters.md", "SINTER_COG_INPUT_GJ_PER_T_SINTER", "SRC_CHECK_005"),
    ]
    rows: list[dict[str, str]] = []
    for card, keyword, check_id in requirements:
        text = (SOURCE_CARD_DIR / card).read_text(encoding="utf-8")
        rows.append(
            {
                "check_id": check_id,
                "check_name": "required_source_card_keyword_present",
                "status": "pass" if keyword.casefold() in text.casefold() else "fail",
                "evidence": f"{card}: required source-card term '{keyword}'.",
                "recommended_action": "Do not harden this controller if the source-card evidence disappears or changes scope.",
            }
        )
    return rows


def _audit_rows() -> list[dict[str, str]]:
    return [
        {
            "process_user_id": "KGF_underfiring",
            "configuration_scope": "C0;C1 (KGF1); C0 only (KGF2)",
            "plant_function": "coke-oven heating / COG self-use",
            "physical_role": "mandatory self-use before clean COG surplus",
            "source_card": "Coking_Plants_Parameters.md",
            "source_locator": "Core conclusion; §§3.1-3.2; §5 recommended first implementation",
            "activity_basis": "t coke from active KGF route",
            "demand_basis": "3.2-3.9 GJ_LHV/t coke; central 3.55 candidate",
            "allowed_carriers": "COG only in Tata-inspired base",
            "blocked_or_deferred_carriers": "BFG; BOFG; NG blocked in base",
            "current_controller_surface": "C5m_b active-plant ledger KGF self-use output",
            "current_output_status": "implemented upstream; not yet reconciled into the authoritative C5p_o/q contract ledger",
            "source_strength": "high candidate / Tata topology plus JRC conversion range",
            "minimum_hardening_level": "carrier-specific COG self-use adapter coupled to coking activity",
            "readiness_status": "implemented_upstream_reconciliation_required",
            "recommended_action": "Reconcile the implemented gross COG, KGF self-use and clean COG surplus boundary before adding any KGF row to the accepted ledger.",
            "caveat": "Do not reuse historical BFG/COG split or add NG substitution; the same COG cannot be both self-use and surplus.",
        },
        {
            "process_user_id": "BF_hot_stove",
            "configuration_scope": "C0;C1 active BF route only",
            "plant_function": "hot-blast heat / blast-furnace auxiliary controller",
            "physical_role": "deduct hot-stove demand before BFG surplus enters site WAG network",
            "source_card": "Blast_Furnace_Parameters.md",
            "source_locator": "§1 controller convention; §6 surplus convention; §7 first energy-only implementation",
            "activity_basis": "t hot metal by active BF6/BF7 topology",
            "demand_basis": "2.20 GJ_LHV/t hot metal development candidate",
            "allowed_carriers": "BFG first; COG/BOFG enrichment only if explicitly enabled; NG backup",
            "blocked_or_deferred_carriers": "raw/dirty gas; free direct reactor WAG injection",
            "current_controller_surface": "C5m_b active-plant ledger Controller_Blast_Furnace output",
            "current_output_status": "implemented upstream; not yet reconciled into the authoritative C5p_o/q contract ledger",
            "source_strength": "high topology; development-only quantitative demand",
            "minimum_hardening_level": "energy-basis hot-stove demand adapter with BFG-first policy",
            "readiness_status": "implemented_upstream_reconciliation_required",
            "recommended_action": "Reconcile the implemented BF hot-metal and BFG-first hot-stove output to the C5p_o carrier boundary before reusing it.",
            "caveat": "The 2.20 GJ/t value is not site-approved; keep it diagnostic/sensitivity-only and do not enable COG/BOFG enrichment by default.",
        },
        {
            "process_user_id": "PEFA_total_gas_heat",
            "configuration_scope": "C0;C1",
            "plant_function": "pellet drying/grinding and induration/firing",
            "physical_role": "total gas-heat demand with structural sub-controller eligibility",
            "source_card": "PELLETIZING_Parameters.md",
            "source_locator": "WAG-controller implementation choice Option A; candidate parameter set; controller eligibility parameters",
            "activity_basis": "t fired pellets",
            "demand_basis": "0.320 GJ/t total gas heat candidate (0.306 COG/BOF gas + 0.014 NG)",
            "allowed_carriers": "total: COG/BOFG/NG; structural: BOFG/NG Malerij, COG/NG Branderij",
            "blocked_or_deferred_carriers": "BFG blocked in base; fixed Malerij/Branderij split deferred",
            "current_controller_surface": "C5n_a PEFA Option-A gas-controller dashboard",
            "current_output_status": "implemented upstream; its 24-hour annualised COG/BOFG rows match the C5p_q unclassified process-use gaps",
            "source_strength": "medium-high generic JRC candidate; Athanasiadis structure only",
            "minimum_hardening_level": "total PEFA gas-heat diagnostic with carrier mix report and no invented stage split",
            "readiness_status": "implemented_upstream_horizon_reconciliation_required",
            "recommended_action": "Integrate the existing total PEFA controller only after recording its 24-hour annualisation basis; retain Malerij/Branderij as structural labels.",
            "caveat": "Do not route all energy to one sub-controller or create a 0.35/0.65 split as a base input.",
        },
        {
            "process_user_id": "HSM_WBW",
            "configuration_scope": "C0;C1",
            "plant_function": "slab reheat / hot rolling",
            "physical_role": "existing WAG process controller",
            "source_card": "HSM_Parameters.md",
            "source_locator": "HSM reheat candidate and source-status sections",
            "activity_basis": "t HRC / active downstream output proxy",
            "demand_basis": "candidate reheat fuel; current accepted C5m output is BFG-only",
            "allowed_carriers": "BFG; COG; BOFG candidates; NG backup",
            "blocked_or_deferred_carriers": "fixed WAG/NG split; mixed_wag numeric use",
            "current_controller_surface": "C5m combined HSM/sinter controller dashboard",
            "current_output_status": "accepted existing diagnostic output; BFG process use reconciles",
            "source_strength": "medium candidate",
            "minimum_hardening_level": "retain existing output; source-review any carrier expansion separately",
            "readiness_status": "accepted_diagnostic_only",
            "recommended_action": "Do not replace the current HSM output; only test alternative carriers in a later isolated sensitivity after electricity/fuel boundary review.",
            "caveat": "HSM carrier split is not a Tata-truth parameter and cannot be inferred from residual WAG.",
        },
        {
            "process_user_id": "Sinter",
            "configuration_scope": "C0;C1",
            "plant_function": "continuous sinter process",
            "physical_role": "existing COG process sink",
            "source_card": "SINTER_Parameters.md",
            "source_locator": "First implementation scope; core candidate coefficients; sensitivity metadata",
            "activity_basis": "t sinter",
            "demand_basis": "0.067 GJ_LHV/t sinter COG candidate; NG sensitivity only",
            "allowed_carriers": "COG; NG only as diagnostic sensitivity",
            "blocked_or_deferred_carriers": "BFG; BOFG; generic WAG; useful WAG output",
            "current_controller_surface": "C5m combined HSM/sinter controller dashboard",
            "current_output_status": "accepted existing diagnostic output",
            "source_strength": "medium candidate",
            "minimum_hardening_level": "retain existing controller output and source status",
            "readiness_status": "accepted_diagnostic_only",
            "recommended_action": "Keep current COG controller output; do not widen fuel eligibility before a separate source review.",
            "caveat": "NG range remains diagnostic and no sinter off-gas may be returned to the WAG pool.",
        },
        {
            "process_user_id": "BOF_auxiliary_fuel",
            "configuration_scope": "C0;C1 retained BF-BOF route",
            "plant_function": "BOF/OSF auxiliary fuel context",
            "physical_role": "not a required base WAG sink; BOF remains primary BOFG producer",
            "source_card": "BOF_OSF_Parameters.md",
            "source_locator": "2026 Bieda LCI candidate table",
            "activity_basis": "t liquid steel",
            "demand_basis": "non-Tata BFG/COG/NG auxiliary candidates",
            "allowed_carriers": "only future explicit sensitivity rows",
            "blocked_or_deferred_carriers": "all base physical allocation",
            "current_controller_surface": "none",
            "current_output_status": "not required for current base allocation",
            "source_strength": "medium non-Tata sensitivity evidence",
            "minimum_hardening_level": "future isolated auxiliary-fuel sensitivity",
            "readiness_status": "sensitivity_only",
            "recommended_action": "Do not use BOF auxiliary fuel to explain current unclassified BOFG/COG; retain BOF as a carrier source in the base.",
            "caveat": "Adding BOF fuel now risks overlap with aggregate process counters and WAG generation accounting.",
        },
        {
            "process_user_id": "C1_flare_spill",
            "configuration_scope": "C1",
            "plant_function": "terminal reporting sink",
            "physical_role": "carrier-specific terminal accounting needed before fuel-explicit CO2",
            "source_card": "WAG_CARRIERS_CO2_FACTORS_Parameters.md",
            "source_locator": "Scope and abstraction level; WAG carbon-boundary policy",
            "activity_basis": "annual carrier residual / flare output",
            "demand_basis": "not applicable",
            "allowed_carriers": "BFG; COG; BOFG only if observed as separate rows",
            "blocked_or_deferred_carriers": "aggregate flare as carrier-specific physical evidence",
            "current_controller_surface": "C5p_o aggregate C1 flare warning",
            "current_output_status": "aggregate only",
            "source_strength": "governance policy",
            "minimum_hardening_level": "carrier-split reporting adapter",
            "readiness_status": "blocked_missing_carrier_split",
            "recommended_action": "Do not assign the C1 aggregate flare to a carrier. Keep it as a reporting gap until a carrier-split output exists.",
            "caveat": "This blocks fuel-explicit CO2 but not non-WAG electricity decomposition.",
        },
    ]


def _evidence_rows() -> list[dict[str, str]]:
    return [
        {
            "evidence_id": "R_EVID_001",
            "process_user_id": "KGF_underfiring",
            "source_card": "Coking_Plants_Parameters.md",
            "source_locator": "lines 90-104; 162-185",
            "evidence_statement": "Clean COG is priority KGF self-use; BFG/BOFG/NG are zero in the Tata-inspired base; surplus follows self-use.",
            "evidence_type": "topology_and_energy_candidate",
            "quantitative_candidate": "3.2-3.9; central 3.55",
            "numeric_range_or_value": "3.2-3.9",
            "unit": "GJ_LHV/t coke",
            "model_use_status": "diagnostic_controller_candidate",
            "unresolved_condition": "Reconcile current coking activity and gross COG generation before emitting an accepted ledger row.",
        },
        {
            "evidence_id": "R_EVID_002",
            "process_user_id": "BF_hot_stove",
            "source_card": "Blast_Furnace_Parameters.md",
            "source_locator": "lines 21-35; 131-156; 229-232",
            "evidence_statement": "Hot-stove demand is a separate controller; BFG is deducted before surplus and NG is backup only.",
            "evidence_type": "controller_structure_and_development_demand",
            "quantitative_candidate": "2.20",
            "numeric_range_or_value": "2.20",
            "unit": "GJ_LHV/t hot metal",
            "model_use_status": "diagnostic_controller_candidate",
            "unresolved_condition": "Candidate is development-only, so demand must remain diagnostic/sensitivity until reviewed.",
        },
        {
            "evidence_id": "R_EVID_003",
            "process_user_id": "PEFA_total_gas_heat",
            "source_card": "PELLETIZING_Parameters.md",
            "source_locator": "lines 46-73; candidate parameter and controller-eligibility tables",
            "evidence_statement": "Total PEFA gas heat is source-backed while Malerij/Branderij eligibility is structural and their numeric split is not.",
            "evidence_type": "total_demand_plus_structural_eligibility",
            "quantitative_candidate": "0.320",
            "numeric_range_or_value": "0.320 = 0.306 COG/BOF gas + 0.014 NG",
            "unit": "GJ/t fired pellets",
            "model_use_status": "total_only_diagnostic_candidate",
            "unresolved_condition": "No source-backed Malerij/Branderij heat split; avoid a synthetic stage split.",
        },
        {
            "evidence_id": "R_EVID_004",
            "process_user_id": "HSM_WBW",
            "source_card": "HSM_Parameters.md",
            "source_locator": "reheat candidate and source-status sections; C5m output reference",
            "evidence_statement": "HSM has a current BFG-only diagnostic output, but broader WAG/NG carrier splits remain candidate/sensitivity material.",
            "evidence_type": "accepted_output_plus_candidate_range",
            "quantitative_candidate": "existing C5m BFG output only",
            "numeric_range_or_value": "not promoted",
            "unit": "carrier mix",
            "model_use_status": "accepted_diagnostic_only",
            "unresolved_condition": "Do not change the carrier mix based on residual WAG or an anchor fit.",
        },
        {
            "evidence_id": "R_EVID_005",
            "process_user_id": "Sinter",
            "source_card": "SINTER_Parameters.md",
            "source_locator": "First implementation scope and core candidate coefficient table",
            "evidence_statement": "Sinter is a COG/NG consumer only; its current COG output is already reconciled by the accepted C5m controller.",
            "evidence_type": "candidate_demand_plus_accepted_output",
            "quantitative_candidate": "0.067",
            "numeric_range_or_value": "0.067",
            "unit": "GJ_LHV/t sinter",
            "model_use_status": "accepted_diagnostic_only",
            "unresolved_condition": "NG stays sensitivity-only and BFG/BOFG remain blocked.",
        },
        {
            "evidence_id": "R_EVID_006",
            "process_user_id": "BOF_auxiliary_fuel",
            "source_card": "BOF_OSF_Parameters.md",
            "source_locator": "2026 Bieda LCI candidate table",
            "evidence_statement": "Auxiliary BFG/COG/NG values are non-Tata candidates and must not be introduced to close a WAG balance.",
            "evidence_type": "non_tata_sensitivity_candidate",
            "quantitative_candidate": "available but not selected",
            "numeric_range_or_value": "non-Tata volume-basis candidates",
            "unit": "m3/t liquid steel",
            "model_use_status": "sensitivity_only",
            "unresolved_condition": "Needs boundary review and separate CO2-mode protection.",
        },
    ]


def _readiness_rows() -> list[dict[str, str]]:
    return [
        {
            "process_user_id": "KGF_underfiring",
            "source_evidence_ready": "yes_candidate",
            "activity_mapping_ready": "partial",
            "carrier_eligibility_ready": "yes",
            "quantitative_demand_ready": "yes_candidate",
            "current_controller_output_ready": "no",
            "priority_position_ready": "yes",
            "source_approved_for_migration": "no",
            "allowed_next_step": "build diagnostic COG-self-use adapter after COG-generation reconciliation",
            "physical_allocation_status": "implemented_upstream_not_yet_contract_reconciled",
            "gating_reason": "Current KGF self-use exists upstream but must not be added again to the C5p_o COG boundary.",
        },
        {
            "process_user_id": "BF_hot_stove",
            "source_evidence_ready": "yes_candidate",
            "activity_mapping_ready": "partial",
            "carrier_eligibility_ready": "yes",
            "quantitative_demand_ready": "development_candidate",
            "current_controller_output_ready": "no",
            "priority_position_ready": "yes",
            "source_approved_for_migration": "no",
            "allowed_next_step": "build BFG-first diagnostic adapter against active hot-metal activity",
            "physical_allocation_status": "implemented_upstream_not_yet_contract_reconciled",
            "gating_reason": "Current hot-stove use exists upstream but needs a denominator/boundary reconciliation to C5p_o.",
        },
        {
            "process_user_id": "PEFA_total_gas_heat",
            "source_evidence_ready": "yes_candidate",
            "activity_mapping_ready": "partial",
            "carrier_eligibility_ready": "yes_structural",
            "quantitative_demand_ready": "yes_total_only",
            "current_controller_output_ready": "yes_upstream",
            "priority_position_ready": "partial",
            "source_approved_for_migration": "no",
            "allowed_next_step": "reconcile the existing total-PEFA controller with the C5p_o/q horizon basis",
            "physical_allocation_status": "implemented_upstream_horizon_reconciliation_required",
            "gating_reason": "A total demand exists but the C5p_q ledger mixes a 168-hour label with PEFA values that map to its 24-hour annualisation.",
        },
        {
            "process_user_id": "HSM_WBW",
            "source_evidence_ready": "partial_candidate",
            "activity_mapping_ready": "yes_diagnostic",
            "carrier_eligibility_ready": "partial",
            "quantitative_demand_ready": "partial",
            "current_controller_output_ready": "yes",
            "priority_position_ready": "yes_existing",
            "source_approved_for_migration": "no",
            "allowed_next_step": "retain accepted C5m output; isolate any carrier expansion as sensitivity",
            "physical_allocation_status": "accepted_diagnostic_only",
            "gating_reason": "Current BFG output reconciles, but expanded carrier mix remains source-weak.",
        },
        {
            "process_user_id": "Sinter",
            "source_evidence_ready": "yes_candidate",
            "activity_mapping_ready": "yes_diagnostic",
            "carrier_eligibility_ready": "yes",
            "quantitative_demand_ready": "yes_candidate",
            "current_controller_output_ready": "yes",
            "priority_position_ready": "yes_existing",
            "source_approved_for_migration": "no",
            "allowed_next_step": "retain accepted C5m output; no eligibility expansion",
            "physical_allocation_status": "accepted_diagnostic_only",
            "gating_reason": "Only the existing COG controller output is reconciled.",
        },
        {
            "process_user_id": "BOF_auxiliary_fuel",
            "source_evidence_ready": "sensitivity_only",
            "activity_mapping_ready": "not_needed_now",
            "carrier_eligibility_ready": "not_accepted_base",
            "quantitative_demand_ready": "non_tata_candidate",
            "current_controller_output_ready": "no",
            "priority_position_ready": "no",
            "source_approved_for_migration": "no",
            "allowed_next_step": "defer to isolated source/boundary sensitivity",
            "physical_allocation_status": "blocked_base",
            "gating_reason": "Not needed to explain the accepted base WAG topology.",
        },
        {
            "process_user_id": "C1_flare_spill",
            "source_evidence_ready": "governance_only",
            "activity_mapping_ready": "aggregate_only",
            "carrier_eligibility_ready": "not_applicable",
            "quantitative_demand_ready": "not_applicable",
            "current_controller_output_ready": "aggregate_only",
            "priority_position_ready": "terminal_only",
            "source_approved_for_migration": "no",
            "allowed_next_step": "preserve as carrier-split reporting gap",
            "physical_allocation_status": "blocked",
            "gating_reason": "An aggregate flare cannot be turned into a carrier-specific split.",
        },
    ]


def _unresolved_rows() -> list[dict[str, str]]:
    rows = _read_csv(C5P_Q_DIR / "process_controller_reconciliation.csv")
    mapping = {
        "COG": "KGF underfiring; PEFA Branderij; HSM carrier expansion only as a later sensitivity",
        "BOFG": "PEFA Malerij total-heat candidate; do not assume BOF auxiliary use",
        "BFG": "none; existing HSM output already reconciles the reported BFG process use",
    }
    output: list[dict[str, str]] = []
    for row in rows:
        unclassified = float(row["unclassified_process_use_PJ_y"])
        output.append(
            {
                "configuration": row["configuration"],
                "carrier": row["carrier"],
                "unclassified_process_use_PJ_y": row["unclassified_process_use_PJ_y"],
                "possible_source_backed_contributors": mapping[row["carrier"]] if unclassified else "none",
                "proven_contributor_now": "no" if unclassified else "yes; accepted HSM controller",
                "required_before_assignment": "controller-compatible activity and demand reconciliation; no aggregate residual allocation" if unclassified else "none",
                "current_handling": "visible gap; not reallocated" if unclassified else "already reconciled",
            }
        )
    return output


def _action_rows() -> list[dict[str, str]]:
    return [
        {
            "priority": "P0",
            "action_id": "R_ACTION_001",
            "target_process_user": "KGF_underfiring",
            "action_type": "diagnostic_adapter_design",
            "what_to_do": "Connect current coking activity to clean COG generation, mandatory COG self-use, and carrier-specific surplus reporting.",
            "expected_effect_on_wag_accounting": "May explain part of unclassified COG use while reducing COG declared available for later sinks.",
            "must_not_do": "Do not import the old 50/50 BFG/COG static assumption or treat COG self-use as additional surplus.",
            "precondition": "Coking activity and gross COG production map to the same C0/C1 topology as C5p_o.",
            "success_criterion": "KGF COG self-use is explicit and carrier balance still closes without C5p_k or aggregate WAG.",
        },
        {
            "priority": "P0",
            "action_id": "R_ACTION_002",
            "target_process_user": "BF_hot_stove",
            "action_type": "diagnostic_adapter_design",
            "what_to_do": "Map active BF hot-metal activity to a BFG-first hot-stove demand row; report NG backup only when BFG is insufficient.",
            "expected_effect_on_wag_accounting": "Reduces BFG available to boilers/generators and tests whether current BFG surplus is overestimated.",
            "must_not_do": "Do not allow all gross BFG to remain surplus or enable COG/BOFG enrichment by default.",
            "precondition": "Treat 2.20 GJ/t HM as a development diagnostic candidate, not a thesis-approved parameter.",
            "success_criterion": "Hot-stove use appears as a separate carrier-specific ledger row and negative BFG residuals remain visible.",
        },
        {
            "priority": "P0",
            "action_id": "R_ACTION_003",
            "target_process_user": "PEFA_total_gas_heat",
            "action_type": "total_demand_controller_design",
            "what_to_do": "Add only a total PEFA gas-heat diagnostic tied to pellet activity, with carrier mix tracking and structural Malerij/Branderij labels.",
            "expected_effect_on_wag_accounting": "Can test whether missing PEFA demand explains unclassified COG/BOFG without inventing a stage split.",
            "must_not_do": "Do not set a fixed stage share or freely route all PEFA demand through the cheapest gas path.",
            "precondition": "PEFA activity basis must be reconciled to the active C0/C1 route output proxy.",
            "success_criterion": "Total PEFA demand is visible; any remaining stage allocation ambiguity is reported as structural-only.",
        },
        {
            "priority": "P1",
            "action_id": "R_ACTION_004",
            "target_process_user": "HSM_WBW;Sinter",
            "action_type": "preserve_and_review",
            "what_to_do": "Keep accepted C5m controller output as the baseline and retain existing BFG/COG reconciliation.",
            "expected_effect_on_wag_accounting": "Prevents loss of the only currently reconciled process outputs.",
            "must_not_do": "Do not broaden carrier mixes merely to improve an anchor fit.",
            "precondition": "Any new source candidate runs as isolated sensitivity after the P0 controllers are audited.",
            "success_criterion": "Existing reconciled rows remain unchanged and separately traceable.",
        },
        {
            "priority": "P1",
            "action_id": "R_ACTION_005",
            "target_process_user": "C1_flare_spill;mixed_wag",
            "action_type": "reporting_gap_repair",
            "what_to_do": "Find or produce carrier-split flare reporting; retain mixed_wag as structural-only.",
            "expected_effect_on_wag_accounting": "Improves terminal balance visibility but does not create a new fuel source.",
            "must_not_do": "Do not infer carrier flare shares or create a quantitative Wobbe mixer.",
            "precondition": "Existing controller surfaces must emit the split or a later source-backed policy must be accepted.",
            "success_criterion": "No aggregate terminal flow is used in a physical mix or fuel-explicit CO2 total.",
        },
    ]


def _validation_rows(audit_rows: list[dict[str, str]], readiness_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = _source_keyword_status()
    q_gate = json.loads((C5P_Q_DIR / "s4_4c5p_q_stage_gate.json").read_text(encoding="utf-8"))
    o_gate = json.loads((C5P_O_DIR / "s4_4c5p_o_stage_gate.json").read_text(encoding="utf-8"))
    rows.extend(
        [
            {
                "check_id": "R_CHECK_006",
                "check_name": "c5p_o_remains_authoritative_wag_guardrail",
                "status": "pass" if o_gate["contract_status"] == "diagnostic_interface_ready" else "fail",
                "evidence": "C5p_o stage gate is read, not modified.",
                "recommended_action": "Keep aggregate_wag reporting-only and mixed_wag structural-only.",
            },
            {
                "check_id": "R_CHECK_007",
                "check_name": "c5p_q_unclassified_use_remains_visible",
                "status": "pass" if q_gate["status"] == "partial_diagnostic_allocation" else "fail",
                "evidence": "C5p_q process reconciliation is copied as a gap map, without a new allocation.",
                "recommended_action": "Do not use residual WAG to fill the listed process gaps.",
            },
            {
                "check_id": "R_CHECK_008",
                "check_name": "no_process_user_marked_executable",
                "status": "pass" if all(row["source_approved_for_migration"] == "no" for row in readiness_rows) else "fail",
                "evidence": "All audit rows remain diagnostic, design, sensitivity or blocked status.",
                "recommended_action": "Use a later migration gate only after a controller implementation and review.",
            },
            {
                "check_id": "R_CHECK_009",
            "check_name": "pefa_stage_split_not_invented",
            "status": "pass" if any(row["process_user_id"] == "PEFA_total_gas_heat" and row["readiness_status"] == "implemented_upstream_horizon_reconciliation_required" for row in audit_rows) else "fail",
                "evidence": "PEFA is represented only as total gas heat in the next design step.",
                "recommended_action": "Keep Malerij/Branderij numerical shares out of the base controller.",
            },
        ]
    )
    return rows


def _write_report(summary: dict[str, Any]) -> None:
    report = f"""# C5 Remaining Process-User Controller Source Audit

## Purpose

C5p_r answers a narrow implementation question: whether the existing source
cards and upstream C5 layers contain enough information to reconcile the
remaining WAG/NG process users without reviving the aggregate-WAG fallback. It
is a source-to-controller readiness audit only. It does not create a new
allocator, alter C5p_o balances, edit source cards, or promote inputs.

## Answer

The repository has enough evidence for **three existing controlled diagnostic
controller surfaces**, but they must be reconciled before they can be used by
the newer authoritative C5p_o/q contract ledger:

- **KGF underfiring:** upstream COG self-use is explicit and quantitatively
  bounded, but its COG boundary must be reconciled before it is reflected in
  the newer contract ledger.
- **BF hot stove:** upstream BFG-first heat demand exists. Its 2.20 GJ/t HM
  demand remains development/sensitivity-only and needs a denominator/boundary
  reconciliation.
- **PEFA:** a total-gas controller exists upstream and its 24-hour annualised
  values explain the COG/BOFG gaps in C5p_q. Its horizon label must be made
  explicit before contract integration; no fixed stage split is allowed.

HSM/WBW and sinter already have accepted diagnostic outputs and should be
preserved. BOF auxiliary fuel remains sensitivity-only. C1 flare and
`mixed_wag` remain blocked for physical allocation.

## What this does not permit

- no `aggregate_wag` allocation;
- no numeric `mixed_wag` allocation or Wobbe claim;
- no C5p_k reuse as physical evidence;
- no invented WAG/NG ratio;
- no WAG/fuel-explicit CO2, economics, DA, or full sensitivity execution.

## Critical review

Review `process_user_controller_source_audit.csv` first. The critical rows are
KGF underfiring, BF hot stove and total PEFA gas heat. Then inspect
`unresolved_process_use_mapping.csv`: it shows that COG and BOFG gaps are still
gaps, not assignments. A future controller adapter is acceptable only if it
preserves C5p_o carrier balance and produces an explicit source/activity/mix
trace.

## Gate

- Existing-controller reconciliation for KGF, BF hot stove and total PEFA: GO,
  diagnostic-only.
- Physical allocation, NG residual policy, WAG/fuel-explicit CO2, sensitivity,
  migration, economics and DA: NO-GO.

Status: `{summary['status']}`. Thesis usability: `false`.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def run_s4_4c5p_r_remaining_process_user_controller_source_audit() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    audit_rows = _audit_rows()
    evidence_rows = _evidence_rows()
    readiness_rows = _readiness_rows()
    unresolved_rows = _unresolved_rows()
    action_rows = _action_rows()
    validation_rows = _validation_rows(audit_rows, readiness_rows)
    counts: dict[str, int] = {}
    for row in validation_rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    stage_gate = {
        "stage": STAGE,
        "status": "source_to_controller_readiness_audited",
        "thesis_usability": False,
        "output_policy": "minimal",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic_governance",
        "guardrails": {
            "new_physical_allocator_created": False,
            "model_equations_changed": False,
            "executable_development_inputs_changed": False,
            "source_cards_changed": False,
            "raw_pdfs_inspected": False,
            "aggregate_wag_physical_allocation": False,
            "mixed_wag_quantitative_allocation": False,
            "invented_wag_ng_ratio": False,
            "c5p_k_used_as_physical_evidence": False,
        },
        "go_no_go": {
            "KGF_diagnostic_adapter_design": "GO_DIAGNOSTIC_ONLY",
            "BF_hot_stove_diagnostic_adapter_design": "GO_DIAGNOSTIC_ONLY",
            "PEFA_total_gas_diagnostic_design": "GO_DIAGNOSTIC_ONLY",
            "complete_physical_WAG_NG_allocation": "NO_GO",
            "NG_residual_policy": "NO_GO",
            "WAG_fuel_explicit_CO2": "NO_GO",
            "full_sensitivity_execution": "NO_GO",
            "executable_input_migration": "NO_GO",
            "economics_readiness": "NO_GO",
            "DA_readiness": "NO_GO",
        },
        "validation_check_counts": counts,
        "source_card_conclusion": "enough for controlled diagnostic adapter design, not enough for executable plant-level allocation",
    }
    summary = {
        "stage": STAGE,
        "status": stage_gate["status"],
        "thesis_usability": False,
        "process_users_audited": len(audit_rows),
        "upstream_controller_reconciliation_ready": ["KGF_underfiring", "BF_hot_stove", "PEFA_total_gas_heat"],
        "accepted_existing_outputs_to_preserve": ["HSM_WBW", "Sinter"],
        "blocked_or_sensitivity_only": ["BOF_auxiliary_fuel", "C1_flare_spill", "mixed_wag"],
        "unclassified_process_gap_rows": sum(1 for row in unresolved_rows if float(row["unclassified_process_use_PJ_y"]) > 0),
        "validation_check_counts": counts,
        "go_no_go": stage_gate["go_no_go"],
    }
    inputs = [
        C5P_P_DIR / "wag_controller_eligibility_matrix.csv",
        C5P_P_DIR / "wag_sink_demand_basis.csv",
        C5P_Q_DIR / "process_controller_reconciliation.csv",
        C5P_Q_DIR / "s4_4c5p_q_stage_gate.json",
        C5P_O_DIR / "s4_4c5p_o_stage_gate.json",
        SOURCE_CARD_DIR / "Coking_Plants_Parameters.md",
        SOURCE_CARD_DIR / "Blast_Furnace_Parameters.md",
        SOURCE_CARD_DIR / "PELLETIZING_Parameters.md",
        SOURCE_CARD_DIR / "HSM_Parameters.md",
        SOURCE_CARD_DIR / "SINTER_Parameters.md",
        SOURCE_CARD_DIR / "BOF_OSF_Parameters.md",
        SOURCE_CARD_DIR / "WAG_CARRIERS_CO2_FACTORS_Parameters.md",
    ]
    manifest = {
        "stage": STAGE,
        "output_policy": "minimal",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic_governance",
        "inputs": [_file_record(path) for path in inputs],
    }
    registry_entry = {
        "run_id": STAGE,
        "purpose": "Audit source-card readiness for remaining WAG/NG process-user controller adapters.",
        "thesis_usable": False,
        "retention": "local diagnostic output until review",
        "git_eligible": False,
        "status": stage_gate["status"],
    }
    _write_csv(OUTPUT_DIR / "process_user_controller_source_audit.csv", audit_rows, AUDIT_COLUMNS)
    _write_csv(OUTPUT_DIR / "source_card_evidence_matrix.csv", evidence_rows, EVIDENCE_COLUMNS)
    _write_csv(OUTPUT_DIR / "controller_activation_readiness.csv", readiness_rows, READINESS_COLUMNS)
    _write_csv(OUTPUT_DIR / "unresolved_process_use_mapping.csv", unresolved_rows, UNRESOLVED_COLUMNS)
    _write_csv(OUTPUT_DIR / "next_hardening_actions.csv", action_rows, ACTION_COLUMNS)
    _write_json(OUTPUT_DIR / "input_manifest.json", manifest)
    _write_json(OUTPUT_DIR / "code_version.json", {"stage": STAGE, "git_revision": _git_revision(), "code_path": __file__})
    _write_json(OUTPUT_DIR / "s4_4c5p_r_stage_gate.json", stage_gate)
    _write_json(OUTPUT_DIR / "summary.json", summary)
    _write_json(OUTPUT_DIR / "registry_entry.json", registry_entry)
    _write_report(summary)
    return summary


def main() -> int:
    run_s4_4c5p_r_remaining_process_user_controller_source_audit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
