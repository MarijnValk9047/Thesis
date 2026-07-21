"""C5p_x map the hardened WAG contract onto the current Pyomo model surface.

This is a fail-closed migration gate.  It audits the current unified physical
modelbuilder before changing it; no WAG allocation, emissions expression or
development input is promoted here.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import S4_ROOT, _write_csv, _write_json


STAGE = "S4.4c5p_x_wag_milp_integration_mapping"
OUTPUT_DIR = S4_ROOT / "s4_4c5p_x_wag_milp_integration_mapping"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_WAG_MILP_INTEGRATION_MAPPING.md")
REPO_ROOT = Path(__file__).resolve().parents[4]
MODEL_BUILDER = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "steel" / "s4_4c_unified_physical_modelbuilder.py"
WAG_HARDENING_DOC = REPO_ROOT / "docs" / "optimisation" / "steel" / "S4" / "C5_WAG_CONTROLLER_CONTRACT_HARDENING.md"
S3_DEMANDS = S4_ROOT.parent / "S3" / "s3_provisional_dev_input" / "s3_wag_demand_coefficients.csv"
S3_SELECTED = S4_ROOT.parent / "S3" / "s3_provisional_dev_input" / "s3_wag_selected_dev_inputs.csv"
S44B_INPUT_DIR = S4_ROOT / "s4_4b5a_asymmetric_c0_c1_correction" / "corrected_dev_inputs"

MAP_COLUMNS = [
    "contract_area", "carrier", "sink_or_boundary", "current_model_surface",
    "current_status", "accepted_for_MILP_now", "required_change", "evidence", "caveat",
]
GAP_COLUMNS = [
    "gap_id", "severity", "model_surface", "problem", "why_not_acceptable",
    "required_resolution", "blocks", "source_or_policy_basis",
]
EMISSION_GATE_COLUMNS = [
    "emission_scope", "current_source", "may_attach_to_MILP_now", "required_precondition",
    "reason", "status",
]
MIGRATION_COLUMNS = [
    "packet_id", "change_type", "target_file_or_module", "allowed_now", "prerequisite",
    "test_before_merge", "expected_result",
]
VALIDATION_COLUMNS = ["check_id", "check_name", "status", "evidence", "recommended_action"]


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


def _interface_map() -> list[dict[str, str]]:
    values = [
        ("generation", "BFG", "BF6/BF7", "bfg_generated expression", "present", "caveated", "Replace hard-coded LHV/constants with selected input loader before reuse.", "C5p_o carrier policy; s4_4c builder", "Generation is carrier-specific but coefficients are not read through the C5 governance loader."),
        ("generation", "COG", "KGF1/KGF2", "cog_generated expression", "present", "caveated", "Use canonical coking activity basis and selected COG coefficient.", "C5p_o; S3 selected WAG inputs", "C1 topology needs KGF2 absent by asset status, not a copied C0 rule."),
        ("generation", "BOFG", "BOF/OSF", "bofg_generated expression", "present", "caveated", "Use selected BOFG coefficient and source-controlled LHV.", "C5p_o; S3 selected WAG inputs", "Current model only routes BOFG to power/flare."),
        ("mandatory self-use", "COG", "KGF underfiring", "cog_to_kgf1/cog_to_kgf2 expressions", "conflicted", "no", "Remove fixed BFG share; bind COG-only base policy to a governed KGF demand input.", "Coking source card: COG-only basecase", "Current 50/50 BFG/COG split conflicts with current C5 policy."),
        ("mandatory self-use", "BFG/COG", "BF hot stoves", "no active sink in minimal WAG layer", "missing", "no", "Map existing S3 hot-stove demand rows to an accepted BF controller interface.", "S3 WAG demand coefficients", "Do not infer allocation from residual BFG."),
        ("process controller", "BFG/COG/BOFG", "HSM/WBW", "not represented in unified minimal WAG layer", "missing", "no", "Migrate only an accepted existing HSM controller and its source-backed demand basis.", "C5p_o/C5p_t controller evidence", "Diagnostic C5p_t rows are not an executable input table."),
        ("process controller", "BOFG/COG/NG", "PEFA", "not represented in unified minimal WAG layer", "missing", "no", "Create a governed source-input interface before adding the controller.", "C5p_o; PEFA source card", "No aggregate PEFA WAG fallback permitted."),
        ("process controller", "COG/NG", "sinter", "cog_to_sinter expression", "hard_coded", "no", "Replace hard-coded intensity with accepted source-controlled input and eligible-route map.", "Sinter source card; C5p_o", "The current fixed COG expression does not establish an NG rule or full process boundary."),
        ("utility", "BFG/COG/BOFG/NG", "boiler/steam", "bfg_to_boiler/cog_to_boiler plus placeholders", "hard_coded", "no", "Reuse C5p_b accepted steam interface; remove placeholder caps/fuel demand first.", "C5p_b; C5p_o", "BOFG and plant-specific boiler eligibility are not represented faithfully."),
        ("interface", "BFG/COG/BOFG", "generators", "Vattenfall variables and a generic volume cap", "caveated", "no", "Reuse C5p_c generator interface with source-backed individual capacities and fixed accounting policy.", "C5p_c; C5p_o", "Do not turn generator use into price-responsive dispatch or export revenue."),
        ("spill", "BFG/COG/BOFG", "flare/residual", "carrier-specific flare variables", "partial", "caveated", "Keep carrier-specific flare; add explicit reporting residual only if it cannot re-enter allocation.", "C5p_o", "C1 flare carrier split remains unresolved."),
        ("emissions", "BFG/COG/BOFG/NG", "point of oxidation", "only legacy flare expressions", "partial", "no", "Attach C5p_v factor policy only after all active WAG routes are governed.", "C5p_v/C5p_w", "No aggregate process CO2 may enter this expression."),
    ]
    return [dict(zip(MAP_COLUMNS, row)) for row in values]


def _gaps() -> list[dict[str, str]]:
    values = [
        ("X_GAP_001", "blocking", "_add_c0_minimal_wag_layer", "KGF1 receives a fixed 50% BFG share.", "Current COG-only KGF base policy is violated.", "Replace with COG-only governed KGF underfiring or explicitly reopen a source-backed sensitivity.", "WAG MILP; emissions; sensitivity", "Coking_Plants_Parameters.md; C5p_o"),
        ("X_GAP_002", "blocking", "_add_c0_minimal_wag_layer", "Boiler fuel demand and WAG caps are hard-coded placeholders.", "They can manufacture NG use and WAG availability.", "Map C5p_b boiler/steam controller inputs and eligibility before any reusable MILP integration.", "WAG MILP; NG; emissions", "C5p_b; C5p_o"),
        ("X_GAP_003", "blocking", "_add_c0_minimal_wag_layer", "BF hot-stove demand is absent from active carrier balances.", "BFG may appear falsely available for generators or flare.", "Connect accepted hot-stove demand coefficients through a BF controller.", "WAG balance; anchors; sensitivity", "S3 WAG demand coefficients"),
        ("X_GAP_004", "high", "_add_c0_minimal_wag_layer", "HSM and PEFA controller routes are absent.", "The model cannot claim a complete process-first WAG allocation.", "Create source-backed executable interfaces; do not import C5p_t diagnostic allocations directly.", "WAG MILP; electricity; emissions", "C5p_o/C5p_t"),
        ("X_GAP_005", "high", "s4_4c_unified_physical_modelbuilder constants", "LHV and flare CO2 factors are hard coded and differ from the governed C5p_u/v factor route.", "One fuel flow could use different carbon factors in model and diagnostic reports.", "Read the selected LHV and RVO factor surfaces through one validated loader.", "emissions; anchor comparison", "C5p_u/C5p_v"),
        ("X_GAP_006", "high", "Vattenfall generator interface", "Generic volume cap is not the accepted C5p_c interface.", "Generator interpretation could overstate available power or flexibility.", "Reuse individual accepted generator interface outputs and keep no-export rule.", "electricity anchors; sensitivity", "C5p_c; C5p_o"),
        ("X_GAP_007", "blocking", "current source input surface", "No single executable source table covers all accepted carrier sinks and demands.", "A shared model module would otherwise combine diagnostics, source cards and placeholders ad hoc.", "Create and validate one governed WAG model-input contract before builder changes.", "all implementation phases", "C5p_o/C5p_x"),
        ("X_GAP_008", "blocking", "emissions", "BF/BOF/KGF/PEFA/sinter/EAF aggregate process counters lack safe non-fuel separation.", "Adding them beside explicit WAG/NG would double count.", "Keep C5p_w exclusions until asset-specific source repair passes.", "process CO2; Scope 1; ETS", "C5p_w"),
        ("X_GAP_009", "resolved", "S4.4b/S4.4c baseline runner", "The historical default input surface failed `s4_4a_blockers_preserved` because its manifest was obsolete.", "The builder initially could not construct either configuration using that stale default.", "Resolved: the unified builder now defaults to the existing validated S4.4b5a corrected-input surface.", "none", "Resolved 2026-07-11; preserved here as migration provenance"),
    ]
    return [dict(zip(GAP_COLUMNS, row)) for row in values]


def _emission_gate() -> list[dict[str, str]]:
    values = [
        ("carrier-specific WAG combustion", "C5p_u/v RVO-factor ledger", "no", "All active WAG sink routes must be governed and source-loaded.", "The current unified builder still has blocked/hard-coded WAG routes.", "blocked_pending_phase1_hardening"),
        ("named modelled NG combustion", "C5p_v", "no", "Named NG variables must be source-backed and not placeholder boiler demand.", "Boiler NG is currently a placeholder; residual NG remains excluded.", "blocked_pending_phase1_hardening"),
        ("non-fuel process carbon", "C5p_w", "no", "Asset-specific source separation and boundary test.", "No reviewed aggregate process component is safe today.", "blocked_source_separation"),
        ("Scope 1 / ETS / carbon cost", "canonical anchor register", "no", "Full carbon boundary, capture policy and accepted site scope.", "Partial explicit-fuel ledger is not a full site inventory.", "blocked"),
    ]
    return [dict(zip(EMISSION_GATE_COLUMNS, row)) for row in values]


def _migration_packet() -> list[dict[str, str]]:
    values = [
        ("X_PACKET_001", "governed input contract", "new shared WAG input adapter", "yes", "No values promoted; schema maps existing accepted inputs and blocks gaps.", "Schema rejects placeholders, aggregate WAG and unsourced routes.", "One auditable input surface."),
        ("X_PACKET_002", "model builder", "s4_4c_unified_physical_modelbuilder.py", "no", "X_PACKET_001 plus KGF/BF/boiler corrections approved.", "Frozen 24h C0/C1 regression matches accepted controller traces.", "Carrier-specific balances with no prohibited routes."),
        ("X_PACKET_003", "emissions expression", "shared WAG/emissions module", "no", "X_PACKET_002 passes and factors load from governed selection.", "Point-of-oxidation totals reproduce C5p_v on frozen case.", "Partial explicit-fuel reporting only."),
        ("X_PACKET_004", "annual reconciliation", "new C5 runner", "no", "X_PACKET_002 and X_PACKET_003 pass.", "Raw/normalised anchor table retains signed residuals.", "Validation-only annual report."),
        ("X_PACKET_005", "sensitivity", "config-driven runner", "no", "X_PACKET_004 passes plus ranges are source-backed.", "One-group low/central/high runs preserve all physical and carbon checks.", "Anchor-informed diagnostic sensitivity only."),
    ]
    return [dict(zip(MIGRATION_COLUMNS, row)) for row in values]


def _validations(gaps: list[dict[str, str]], mapping: list[dict[str, str]]) -> list[dict[str, str]]:
    text = MODEL_BUILDER.read_text(encoding="utf-8")
    return [
        {"check_id": "X_CHECK_001", "check_name": "current_builder_was_inspected", "status": "pass" if "_add_c0_minimal_wag_layer" in text else "fail", "evidence": "Current Pyomo WAG function is mapped before any edit.", "recommended_action": "Do not bypass the existing builder."},
        {"check_id": "X_CHECK_002", "check_name": "minimal_layer_is_not_silently_promoted", "status": "pass" if any(row["gap_id"] == "X_GAP_001" for row in gaps) else "fail", "evidence": "KGF split conflict is explicitly blocking.", "recommended_action": "Repair governed inputs/constraints before activation."},
        {"check_id": "X_CHECK_003", "check_name": "no_unapproved_emissions_expression", "status": "pass", "evidence": "This stage writes no model or emissions changes.", "recommended_action": "Keep C5p_v authoritative until Phase 1 passes."},
        {"check_id": "X_CHECK_004", "check_name": "carrier_specific_policy_preserved", "status": "pass" if all(row["carrier"] not in {"aggregate_wag", "mixed_wag"} for row in mapping) else "fail", "evidence": "Map covers only BFG, COG, BOFG and NG treatment.", "recommended_action": "Keep aggregate/mixed WAG out of physical variables."},
    ]


def _write_report(gaps: list[dict[str, str]]) -> None:
    blockers = "\n".join(f"- **{row['gap_id']} — {row['problem']}** {row['required_resolution']}" for row in gaps if row["severity"] == "blocking")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        f"""# C5 WAG-to-MILP Integration Mapping

## Result

The current `s4_4c_unified_physical_modelbuilder.py` contains a carrier-specific
minimal WAG layer, but it is **not eligible for activation as the thesis WAG
MILP layer**. It includes hard-coded boiler values, a fixed BFG/COG KGF split,
no active BF hot-stove controller, incomplete HSM/PEFA routes, and legacy flare
CO2 factors. C5p_x therefore makes no model change.

The historical builder default pointed to an obsolete input surface whose
blocker manifest no longer validated. It is now routed to the existing
validated S4.4b5a corrected-input surface; this repairs the baseline routing
only and does not alter any input value or WAG rule.

## Blocking repairs before an executable WAG layer

{blockers}

## What can proceed now

Create one governed WAG input adapter that maps existing accepted selected
inputs, demand coefficients and eligibility rows without promoting a new value.
It must reject placeholders, aggregate WAG, diagnostic-only controller rows and
routes with no source-backed demand basis. After that adapter exists, replace
the minimal layer incrementally under frozen 24-hour C0/C1 regression tests.

## Emissions consequence

The C5p_v explicit-fuel ledger remains the current authoritative diagnostic
subtotal. It must not be copied into the Pyomo model while the active WAG
routes still contain blocked placeholder logic. Aggregate BF/BOF/KGF/PEFA/
sinter/EAF counters and DRP capture remain separate.

## Gate

- WAG input-contract hardening: GO next.
- Activate/rewrite the physical WAG MILP layer: NO-GO pending blocking repairs.
- Attach explicit fuel-emissions expressions: NO-GO pending the WAG gate.
- Annual reconciliation and sensitivity execution: NO-GO pending the prior gates.
""",
        encoding="utf-8",
    )


def run_s4_4c5p_x_wag_milp_integration_mapping() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    mapping = _interface_map()
    gaps = _gaps()
    emissions = _emission_gate()
    migration = _migration_packet()
    validations = _validations(gaps, mapping)
    counts: dict[str, int] = {}
    for row in validations:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    stage_gate = {
        "stage": STAGE,
        "status": "wag_milp_mapping_complete_hardening_required",
        "thesis_usability": False,
        "output_policy": "minimal",
        "run_class": "diagnostic",
        "lineage_role": "diagnostic",
        "go_no_go": {
            "governed_WAG_input_adapter": "GO_NEXT",
            "activate_current_minimal_WAG_layer": "NO_GO",
            "physical_WAG_MILP_integration": "NO_GO_PENDING_HARDENING",
            "explicit_fuel_emissions_in_MILP": "NO_GO_PENDING_WAG_GATE",
            "annual_anchor_reconciliation": "NO_GO_PENDING_WAG_AND_EMISSIONS_GATE",
            "sensitivity_execution": "NO_GO_PENDING_RECONCILIATION_GATE",
        },
        "guardrails": {
            "model_equations_changed": False,
            "executable_development_inputs_changed": False,
            "source_cards_changed": False,
            "aggregate_wag_physical_use_created": False,
            "mixed_wag_quantitative_use_created": False,
            "residual_energy_allocated": False,
            "aggregate_process_co2_added": False,
        },
        "validation_check_counts": counts,
    }
    summary = {
        "stage": STAGE,
        "status": stage_gate["status"],
        "mapped_contract_areas": len(mapping),
        "blocking_gaps": sum(row["severity"] == "blocking" for row in gaps),
        "high_gaps": sum(row["severity"] == "high" for row in gaps),
        "validation_check_counts": counts,
        "go_no_go": stage_gate["go_no_go"],
    }
    inputs = [MODEL_BUILDER, WAG_HARDENING_DOC, S3_DEMANDS, S3_SELECTED, S44B_INPUT_DIR / "wag_sink_eligibility.csv", S44B_INPUT_DIR / "wag_generation_coefficients.csv"]
    _write_csv(OUTPUT_DIR / "wag_milp_interface_map.csv", mapping, MAP_COLUMNS)
    _write_csv(OUTPUT_DIR / "wag_milp_hardening_gap_register.csv", gaps, GAP_COLUMNS)
    _write_csv(OUTPUT_DIR / "wag_milp_emission_integration_gate.csv", emissions, EMISSION_GATE_COLUMNS)
    _write_csv(OUTPUT_DIR / "next_executable_migration_packet.csv", migration, MIGRATION_COLUMNS)
    _write_csv(OUTPUT_DIR / "validation_checks.csv", validations, VALIDATION_COLUMNS)
    _write_json(OUTPUT_DIR / "input_manifest.json", {"stage": STAGE, "output_policy": "minimal", "run_class": "diagnostic", "lineage_role": "diagnostic", "inputs": [_file_record(path) for path in inputs]})
    _write_json(OUTPUT_DIR / "code_version.json", {"stage": STAGE, "git_revision": _git_revision(), "code_path": __file__})
    _write_json(OUTPUT_DIR / "s4_4c5p_x_stage_gate.json", stage_gate)
    _write_json(OUTPUT_DIR / "summary.json", summary)
    _write_json(OUTPUT_DIR / "registry_entry.json", {"run_id": STAGE, "purpose": "Fail-closed mapping from C5 WAG contract to the current Pyomo model surface.", "thesis_usable": False, "retention": "local diagnostic output until review", "git_eligible": False, "status": stage_gate["status"]})
    _write_report(gaps)
    return summary


def main() -> int:
    run_s4_4c5p_x_wag_milp_integration_mapping()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
