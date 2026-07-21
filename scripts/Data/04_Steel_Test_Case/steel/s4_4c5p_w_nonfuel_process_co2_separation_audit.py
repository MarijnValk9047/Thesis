"""C5p_w audit for source-separated non-fuel process CO2 additions.

The current C5p_v ledger intentionally counts only carrier-specific WAG at
represented oxidation sinks and named, modelled NG consumers.  This stage does
not broaden that subtotal.  It records whether the remaining aggregate process
cards contain a source-separated component that can safely sit beside the
explicit-fuel boundary without double counting carbon already carried in WAG.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import S4_ROOT, _read_csv, _write_csv, _write_json


STAGE = "S4.4c5p_w_nonfuel_process_co2_separation_audit"
OUTPUT_DIR = S4_ROOT / "s4_4c5p_w_nonfuel_process_co2_separation_audit"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_NONFUEL_PROCESS_CO2_SEPARATION_AUDIT.md")

C5P_V_DIR = S4_ROOT / "s4_4c5p_v_modelwide_explicit_fuel_emissions_ledger"
SOURCE_CARD_DIR = S4_ROOT.parent / "source_cards"

REGISTER_COLUMNS = [
    "asset",
    "configuration_scope",
    "current_carbon_mode",
    "aggregate_or_context_candidate",
    "candidate_basis",
    "existing_explicit_overlap",
    "source_separated_nonfuel_component_available",
    "eligible_for_current_explicit_total",
    "decision",
    "source_card",
    "source_status",
    "reason",
    "required_before_reopen",
]
BOUNDARY_COLUMNS = [
    "asset",
    "current_explicit_boundary",
    "aggregate_context_boundary",
    "overlap_or_exclusion_reason",
    "allowed_current_use",
    "forbidden_current_use",
    "future_safe_addition_requirement",
]
PRIORITY_COLUMNS = [
    "priority",
    "asset",
    "repair_question",
    "why_it_matters",
    "required_evidence",
    "current_gate_effect",
    "recommended_next_action",
]
ELIGIBILITY_COLUMNS = [
    "asset",
    "candidate_component",
    "may_enter_c5p_v_explicit_total_now",
    "why",
    "would_change_current_total",
    "current_total_preserved",
    "status",
]
VALIDATION_COLUMNS = ["check_id", "check_name", "status", "evidence", "recommended_action"]


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Required C5p_w input is missing: {path}")
    return _read_csv(path)


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


def _register() -> list[dict[str, str]]:
    """Return deliberately conservative asset decisions from existing cards."""
    rows = [
        (
            "BF and hot stoves", "C0 and C1", "WAG-explicit point of oxidation",
            "BF_CO2_COUNTER_AGG_T_PER_T_HM = 1.495 tCO2e/t HM", "aggregate hot-metal counter",
            "BFG carbon is already counted at represented downstream sinks", "no", "no", "exclude",
            "Blast_Furnace_Parameters.md", "source-backed aggregate candidate; no separated process split",
            "The card defines aggregate-counter mode or WAG-explicit mode as mutually exclusive.",
            "Source-separated BF reduction/solid-carbon/process component plus a carbon balance that excludes BFG carbon.",
        ),
        (
            "BOF/OSF", "C0 and C1", "WAG-explicit point of oxidation",
            "BOF_DIRECT_CO2_T_PER_T_LS_BIEDA ≈ 0.0825 tCO2/t LS", "aggregate/direct diagnostic",
            "BOFG carbon is already counted at represented downstream sinks", "no", "no", "exclude",
            "BOF_OSF_Parameters.md", "source-backed candidate; locator not verified in repo",
            "The source card explicitly forbids adding the candidate when BOFG carbon is downstream-counted.",
            "A BOF non-BOFG direct-process component with a clear boundary and verified locator.",
        ),
        (
            "KGF/coking", "C0 and C1", "WAG-explicit point of oxidation",
            "KGF_DIRECT_CO2_T_PER_T_COKE_AGGREGATE = 0.4595 tCO2/t coke", "aggregate coking counter",
            "COG carbon is already counted at KGF underfiring and downstream COG sinks", "no", "no", "exclude",
            "Coking_Plants_Parameters.md", "source-backed aggregate candidate; broad alternatives also exist",
            "The source card requires aggregate KGF or WAG-explicit COG combustion, never both.",
            "Source-separated non-COG coking emissions with energy/carbon basis reconciled to COG self-use and surplus.",
        ),
        (
            "PEFA", "C0 and C1", "WAG-explicit point of oxidation plus named NG if modelled",
            "PEFA diagnostic midpoint = 0.105 tCO2/t pellet", "aggregate pellet-process diagnostic",
            "Represented BOFG/COG controller fuel and named NG are already explicit", "partial", "no", "exclude",
            "PELLETIZING_Parameters.md", "solid-fuel energy candidate exists; no governed factor/split",
            "The aggregate diagnostic can contain WAG and solid-fuel carbon; the card does not isolate a usable non-fuel term.",
            "Pellet solid-fuel quantity plus source-backed factor and proof that it excludes represented WAG/NG fuel.",
        ),
        (
            "Sinter", "C0 and C1", "WAG-explicit point of oxidation plus named NG if modelled",
            "SINTER_DIRECT_CO2_T_PER_T_SINTER = 0.248 tCO2e/t sinter", "aggregate sinter counter",
            "Represented COG oxidation may overlap the aggregate counter", "partial", "no", "exclude",
            "SINTER_Parameters.md", "development aggregate diagnostic; detailed solid-fuel chemistry excluded",
            "The card forbids adding full COG/NG combustion beside the aggregate counter until the carbon boundary is resolved.",
            "Source-separated coke-breeze/solid-carbon process component and an explicit WAG/NG exclusion boundary.",
        ),
        (
            "EAF", "C1 only", "Named EAF NG point of oxidation",
            "EAF aggregate direct-emission range 72-180 kgCO2/t LS", "aggregate range validation",
            "Named EAF NG is explicit; coke-breeze, electrodes and other direct carbon are not yet explicit", "partial", "no", "exclude",
            "EAF_Parameters.md", "fuel-component energy candidates exist; no carbon-factor/boundary selection is frozen",
            "The aggregate range overlaps explicit NG and cannot identify the remaining non-NG carbon safely.",
            "Separate coke-breeze/anthracite, electrodes and other direct-process carbon factors with a non-overlap decision.",
        ),
        (
            "DRP", "C1 only", "Named DRP NG point of oxidation", "DRP capture stream", "capture reporting stream",
            "DRP NG is explicit; capture is not a direct-emission add-on", "no", "no", "report separately",
            "DRP_Parameters.md", "policy card states capture-stream validation first",
            "Capture must neither be added nor automatically subtracted without a represented capture-and-sink boundary.",
            "Governed capture, transport and storage/use sink accounting before any net-emissions claim.",
        ),
    ]
    return [dict(zip(REGISTER_COLUMNS, row)) for row in rows]


def _boundary_matrix(register: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "asset": row["asset"],
            "current_explicit_boundary": row["current_carbon_mode"],
            "aggregate_context_boundary": row["aggregate_or_context_candidate"],
            "overlap_or_exclusion_reason": row["reason"],
            "allowed_current_use": "Keep explicit named WAG/NG where represented; retain aggregate/capture row as separate context.",
            "forbidden_current_use": "Add the aggregate/context candidate to C5p_v's explicit-fuel total.",
            "future_safe_addition_requirement": row["required_before_reopen"],
        }
        for row in register
    ]


def _priorities() -> list[dict[str, str]]:
    values = [
        ("P0", "EAF", "Separate coke-breeze/anthracite, electrodes and other direct carbon from already explicit NG.", "C1 has explicit NG and a relevant aggregate range, but no safe non-NG carbon term.", "Component-specific factors and basis; no use of BREF aggregate as a plug.", "Blocks EAF non-fuel addition and full C1 coverage.", "Source-card repair/audit only; do not add to totals."),
        ("P0", "PEFA and sinter", "Separate solid-fuel/process carbon from represented WAG/NG combustion.", "These can materially affect both configurations and present an aggregate-counter overlap risk.", "Fuel quantity, factor and a boundary statement excluding WAG/NG.", "Blocks non-fuel additions for both routes.", "Targeted source review; keep aggregate counters context-only."),
        ("P1", "BF and hot stoves", "Separate BF reduction/solid carbon from BFG carbon at downstream sinks.", "BF aggregate counter dominates C0 but is incompatible with current WAG-explicit boundary.", "Complete source-backed carbon mass/boundary split.", "Blocks BF non-fuel addition and full C0 Scope 1 claim.", "Do not derive by subtraction from the aggregate counter."),
        ("P1", "BOF/OSF", "Identify direct process carbon that excludes BOFG carbon.", "Current direct candidate explicitly overlaps BOFG downstream accounting.", "Verified locator and separated BOFG-free process component.", "Blocks BOF non-fuel addition.", "Keep candidate as validation-only."),
        ("P1", "KGF/coking", "Separate coking process emissions from COG carbon.", "COG self-use and surplus are now carrier-accounted, so aggregate coking CO2 would double count.", "Coking non-COG split reconciled to COG production/self-use/surplus.", "Blocks KGF non-fuel addition.", "Keep aggregate range/context separate."),
        ("P2", "DRP capture", "Define capture-and-sink accounting.", "Capture is a reporting stream, not an automatic emissions reduction.", "Captured amount, destination, permanence and boundary policy.", "Blocks net-emissions and ETS claims.", "Retain separate reporting only."),
    ]
    return [dict(zip(PRIORITY_COLUMNS, row)) for row in values]


def _eligibility(register: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "asset": row["asset"],
            "candidate_component": row["aggregate_or_context_candidate"],
            "may_enter_c5p_v_explicit_total_now": row["eligible_for_current_explicit_total"],
            "why": row["reason"],
            "would_change_current_total": "false",
            "current_total_preserved": "true",
            "status": "blocked_pending_source_separation" if row["eligible_for_current_explicit_total"] != "yes" else "eligible",
        }
        for row in register
    ]


def _validations(register: list[dict[str, str]], eligibility: list[dict[str, str]], totals: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "check_id": "W_CHECK_001",
            "check_name": "no_aggregate_or_capture_component_added_to_current_total",
            "status": "pass" if all(row["may_enter_c5p_v_explicit_total_now"] != "yes" for row in eligibility) else "fail",
            "evidence": "Every reviewed candidate remains outside the C5p_v explicit-fuel total.",
            "recommended_action": "Require a source-separated non-fuel component before any addition.",
        },
        {
            "check_id": "W_CHECK_002",
            "check_name": "existing_explicit_fuel_totals_preserved",
            "status": "pass" if len(totals) == 2 else "fail",
            "evidence": "C5p_w reads C5p_v totals and writes no replacement total.",
            "recommended_action": "Treat C5p_v as the authoritative current subtotal.",
        },
        {
            "check_id": "W_CHECK_003",
            "check_name": "DRP_capture_stays_separate",
            "status": "pass" if any(row["asset"] == "DRP" and row["decision"] == "report separately" for row in register) else "fail",
            "evidence": "DRP capture has no current total eligibility.",
            "recommended_action": "Do not net capture before a capture-and-sink boundary exists.",
        },
        {
            "check_id": "W_CHECK_004",
            "check_name": "no_residual_energy_or_CO2_inference",
            "status": "pass",
            "evidence": "The audit has no residual allocation, combustion or emissions calculation.",
            "recommended_action": "Keep residual electricity and NG as signed reporting KPIs.",
        },
    ]


def _write_report(register: list[dict[str, str]], totals: list[dict[str, str]]) -> None:
    c0 = next(row for row in totals if row["configuration"] == "C0_current_BF_BOF_reference")
    c1 = next(row for row in totals if row["configuration"] == "C1_phase1_BF_BOF_plus_DRP_EAF")
    report = f"""# C5 Non-Fuel Process CO2 Separation Audit

## Purpose

C5p_w tests whether any aggregate BF, BOF, KGF, PEFA, sinter, EAF or DRP
context component can safely be added beside the current C5p_v explicit-fuel
ledger. It does not create a process-emissions estimator and does not alter
the ledger. The answer for every reviewed component is currently **no**:
available values are aggregate counters, overlap explicit WAG/NG, or lack a
source-backed non-fuel carbon split.

## Current explicit-fuel subtotal remains unchanged

- C0: {c0['explicit_fuel_co2_total_mt_y']} MtCO2/y.
- C1: {c1['explicit_fuel_co2_total_mt_y']} MtCO2/y.

These remain carrier-specific WAG oxidation plus named modelled NG oxidation.
No residual energy, aggregate process counter or capture stream is used to
fill the remaining Scope 1 gap.

## Decision

The following are retained as separate validation/context information only:
BF aggregate hot-metal counter, BOF direct candidate, KGF aggregate counter,
PEFA diagnostic midpoint, sinter aggregate counter, EAF aggregate range and
DRP capture stream. In particular, this audit does not derive a supposedly
non-fuel component by subtracting WAG/NG emissions from an aggregate value.
That would hide boundary mismatch as a physical parameter.

## Next source-repair priorities

1. EAF: separately source coke-breeze/anthracite, electrodes and other direct
   carbon before adding anything beside named NG.
2. PEFA and sinter: separate solid-fuel/process carbon from WAG/NG combustion.
3. BF, BOF and KGF: obtain carbon-boundary splits that exclude BFG, BOFG and
   COG respectively.

## Gate

- Current C5p_v explicit-fuel ledger: GO, diagnostic-only.
- Source-separation audit: GO.
- Adding reviewed non-fuel/process terms now: NO-GO.
- Full Scope 1/ETS, residual-emissions inference, economics and DA: NO-GO.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def run_s4_4c5p_w_nonfuel_process_co2_separation_audit() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    totals = _rows(C5P_V_DIR / "explicit_fuel_total_vs_scope1.csv")
    register = _register()
    boundary = _boundary_matrix(register)
    priorities = _priorities()
    eligibility = _eligibility(register)
    validations = _validations(register, eligibility, totals)
    counts: dict[str, int] = {}
    for row in validations:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    stage_gate = {
        "stage": STAGE,
        "status": "nonfuel_process_CO2_audited_no_safe_additions",
        "thesis_usability": False,
        "output_policy": "minimal",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic",
        "go_no_go": {
            "current_explicit_fuel_ledger": "GO_DIAGNOSTIC_ONLY",
            "source_separation_audit": "GO",
            "add_BF_BOF_KGF_PEFA_sinter_EAF_nonfuel_terms": "NO_GO",
            "DRP_capture_netting": "NO_GO",
            "full_site_or_ETS_CO2": "NO_GO",
            "residual_energy_CO2_inference": "NO_GO",
            "economics_readiness": "NO_GO",
            "DA_readiness": "NO_GO",
        },
        "guardrails": {
            "model_equations_changed": False,
            "executable_development_inputs_changed": False,
            "source_cards_changed": False,
            "aggregate_process_counter_added_to_total": False,
            "residual_energy_allocated_or_emitted": False,
            "capture_stream_netting_active": False,
            "raw_pdfs_inspected": False,
        },
        "validation_check_counts": counts,
    }
    summary = {
        "stage": STAGE,
        "status": stage_gate["status"],
        "reviewed_assets": [row["asset"] for row in register],
        "eligible_additions_now": sum(row["eligible_for_current_explicit_total"] == "yes" for row in register),
        "explicit_fuel_totals_mt_y": {row["configuration"]: float(row["explicit_fuel_co2_total_mt_y"]) for row in totals},
        "validation_check_counts": counts,
        "go_no_go": stage_gate["go_no_go"],
    }
    inputs = [
        C5P_V_DIR / "explicit_fuel_total_vs_scope1.csv",
        SOURCE_CARD_DIR / "Blast_Furnace_Parameters.md",
        SOURCE_CARD_DIR / "BOF_OSF_Parameters.md",
        SOURCE_CARD_DIR / "Coking_Plants_Parameters.md",
        SOURCE_CARD_DIR / "PELLETIZING_Parameters.md",
        SOURCE_CARD_DIR / "SINTER_Parameters.md",
        SOURCE_CARD_DIR / "EAF_Parameters.md",
        SOURCE_CARD_DIR / "DRP_Parameters.md",
    ]
    _write_csv(OUTPUT_DIR / "nonfuel_process_co2_separation_register.csv", register, REGISTER_COLUMNS)
    _write_csv(OUTPUT_DIR / "carbon_boundary_decision_matrix.csv", boundary, BOUNDARY_COLUMNS)
    _write_csv(OUTPUT_DIR / "source_repair_priority.csv", priorities, PRIORITY_COLUMNS)
    _write_csv(OUTPUT_DIR / "modelwide_ledger_addition_eligibility.csv", eligibility, ELIGIBILITY_COLUMNS)
    _write_csv(OUTPUT_DIR / "validation_checks.csv", validations, VALIDATION_COLUMNS)
    _write_json(OUTPUT_DIR / "input_manifest.json", {"stage": STAGE, "output_policy": "minimal", "run_class": "diagnostic", "lineage_role": "diagnostic", "inputs": [_file_record(path) for path in inputs]})
    _write_json(OUTPUT_DIR / "code_version.json", {"stage": STAGE, "git_revision": _git_revision(), "code_path": __file__})
    _write_json(OUTPUT_DIR / "s4_4c5p_w_stage_gate.json", stage_gate)
    _write_json(OUTPUT_DIR / "summary.json", summary)
    _write_json(OUTPUT_DIR / "registry_entry.json", {"run_id": STAGE, "purpose": "Source separation audit for non-fuel process CO2 without changing the explicit-fuel ledger.", "thesis_usable": False, "retention": "local diagnostic output until review", "git_eligible": False, "status": stage_gate["status"]})
    _write_report(register, totals)
    return summary


def main() -> int:
    run_s4_4c5p_w_nonfuel_process_co2_separation_audit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
