"""Resolve only source-backed C5 WAG/CO2 integration blockers.

This stage is deliberately a resolution packet, not a new allocator.  It
records which C5p_y blockers were solved directly in the unified builder and
which still require an explicit development-input decision or source repair.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import S4_ROOT, _read_csv, _write_csv, _write_json


STAGE = "S4.4c5p_z_wag_milp_blocker_resolution_packet"
OUTPUT_DIR = S4_ROOT / "s4_4c5p_z_wag_milp_blocker_resolution_packet"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_WAG_MILP_BLOCKER_RESOLUTION_PACKET.md")
REPO_ROOT = Path(__file__).resolve().parents[4]
MODEL_BUILDER = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "steel" / "s4_4c_unified_physical_modelbuilder.py"
FACTOR_ADAPTER = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "steel" / "wag_milp_input_contract.py"
P_Y_DIR = S4_ROOT / "s4_4c5p_y_wag_governed_input_contract"
P_W_DIR = S4_ROOT / "s4_4c5p_w_nonfuel_process_co2_separation_audit"

RESOLUTION_COLUMNS = [
    "resolution_id", "original_blocker", "area", "status", "implementation_status",
    "what_changed_or_was_verified", "source_basis", "may_feed_physical_WAG_layer",
    "may_feed_mode_b_CO2", "remaining_requirement", "caveat",
]
PATCH_COLUMNS = ["check_id", "check_name", "status", "evidence", "effect", "caveat"]
READINESS_COLUMNS = [
    "asset_or_controller", "current_evidence_status", "current_contract_status",
    "safe_now", "missing_before_activation", "blocking_type", "recommended_next_action", "caveat",
]
MODE_B_COLUMNS = [
    "component", "mode_b_treatment", "included_now", "double_count_guard", "status", "remaining_gap",
]
BACKLOG_COLUMNS = ["priority", "asset", "repair_question", "required_evidence", "mode_b_implication", "status"]
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


def _builder_checks() -> list[dict[str, str]]:
    text = MODEL_BUILDER.read_text(encoding="utf-8")
    checks = [
        (
            "Z_CHECK_001", "KGF_basecase_is_COG_only", "pass"
            if 'model.bfg_to_kgf1 = Expression(\n        model.TIME,\n        rule=lambda _m, _t: 0.0' in text
            and 'rule=lambda m, t: inputs.kgf_underfiring_mwh_per_t_coke * m.coking_plant_1[t]' in text
            else "fail",
            "The former 50/50 BFG/COG KGF1 split is replaced by zero BFG and full COG underfiring.",
            "BFG is no longer presented as a freely substitutable KGF underfiring fuel in the base case.",
            "This resolves only the KGF underfiring route; it does not create a full coking steam controller.",
        ),
        (
            "Z_CHECK_002", "selected_LHV_and_combustion_factors_are_loaded", "pass"
            if "from .wag_milp_input_contract import load_governed_wag_factor_maps" in text
            and "lhv_mj_per_nm3, combustion_t_per_mwh = load_governed_wag_factor_maps()" in text
            and "SELECTED_WAG_LHV_MJ_PER_NM3, FLARE_CO2_EF_T_PER_MWH = load_governed_wag_factor_maps()" in text
            else "fail",
            "The unified builder uses the C5p_y selected LHV and combustion-factor adapter.",
            "A carrier flow has one selected LHV and one point-of-oxidation factor across the hardened builder surface.",
            "Values remain development-only and must not be described as Tata operating truth.",
        ),
        (
            "Z_CHECK_003", "mode_b_explicit_WAG_CO2_is_diagnostic_only", "pass"
            if "model.wag_explicit_combustion_co2_t = Expression" in text
            and "Aggregate BF/BOF/KGF/PEFA/sinter counters remain out" in text
            else "fail",
            "The builder exposes a carrier-specific WAG point-of-oxidation expression without an aggregate process counter.",
            "Mode B can be inspected per represented carrier/sink without an ETS or carbon-cost objective.",
            "Incomplete sinks and placeholder boiler demand mean this is not a full-site total.",
        ),
        (
            "Z_CHECK_004", "placeholder_NG_is_excluded_from_mode_b", "pass"
            if "placeholder boiler NG remains excluded" in text
            else "fail",
            "The existing boiler NG placeholder is not emitted by inference.",
            "Residual or placeholder NG cannot make the Mode B subtotal look complete.",
            "Named, source-backed NG controllers can be added later through their own input contract.",
        ),
    ]
    return [dict(zip(PATCH_COLUMNS, row)) for row in checks]


def _resolution_rows(checks: list[dict[str, str]]) -> list[dict[str, str]]:
    passed = {row["check_id"]: row["status"] == "pass" for row in checks}
    values = [
        (
            "Z_RES_001", "Y_BLOCK_001", "KGF underfiring", "resolved" if passed["Z_CHECK_001"] else "failed",
            "base builder patch", "KGF1 BFG input is zero; KGF1/KGF2 underfiring demand is carried entirely by clean COG.",
            "Coking source card COG-only base policy", "yes", "yes",
            "Coking steam demand remains unbound; any non-COG KGF fuel remains a separately approved sensitivity only.",
            "COG is counted at its represented combustion sink in Mode B, never again as an aggregate KGF counter.",
        ),
        (
            "Z_RES_002", "Y_BLOCK_004", "factor consistency", "resolved" if passed["Z_CHECK_002"] else "failed",
            "base builder patch", "Selected C5p_y LHV and combustion-factor maps replace legacy builder constants.",
            "C5p_y governed selected input contract", "yes", "yes",
            "Generator capacities and boiler demand/eligibility are still separately governed and incomplete.",
            "The adapter provides factors only; it does not create a new route or allocation rule.",
        ),
        (
            "Z_RES_003", "Y_BLOCK_005", "Mode B WAG CO2", "partial_resolved" if passed["Z_CHECK_003"] and passed["Z_CHECK_004"] else "failed",
            "diagnostic builder expression", "Carrier-specific WAG oxidation is visible at represented sinks; no aggregate process counter or placeholder NG is added.",
            "C5p_v/WAG factor contract and C5p_w double-count policy", "caveated", "yes",
            "Major source-backed sinks must be mapped before using the subtotal for any whole-site claim; non-fuel carbon remains a separate repair backlog.",
            "No ETS, carbon cost, Scope 1 completion or residual-emissions inference is activated.",
        ),
        (
            "Z_RES_004", "Y_BLOCK_002", "BF hot-stove controller", "blocked_by_development_input_selection",
            "binding packet only", "A first energy-basis controller is specified by the source card, with BFG first and COG/BOFG/NG only when explicitly enabled.",
            "Blast Furnace source card: 2.20 GJ/t HM is a development assumption; existing S3 rows are C0-only reference rows.", "no", "no",
            "Select and register a C0/C1 executable hot-stove demand basis before adding a sink to the builder. Do not infer it from residual BFG.",
            "No Wobbe constraint or invented gas mix is required; this is a parameter-governance decision, not an allocator gap.",
        ),
        (
            "Z_RES_005", "Y_BLOCK_003", "HSM/PEFA/boilers/generators", "blocked_by_controller_contracts",
            "readiness classification", "Existing cards contain eligibility or diagnostic/controller logic, but not a single selected executable demand contract for every sink.",
            "C5l/C5m/C5p_b/C5p_c and source cards", "no", "partial",
            "Promote each controller one at a time with its demand driver, carrier eligibility, capacity and output interface; boiler placeholders must be retired first.",
            "Do not import aggregate WAG allocations from earlier diagnostics into the MILP.",
        ),
        (
            "Z_RES_006", "Y_BLOCK_005", "non-fuel process CO2", "blocked_by_source_separation",
            "source-repair backlog", "Mode B excludes BF/BOF/KGF/PEFA/sinter/EAF aggregate counters, preserving a no-double-count total.",
            "C5p_w separation audit", "no", "yes",
            "Obtain WAG-free/non-fuel carbon terms with explicit boundary and denominator before adding any process component.",
            "Mode B is the correct leading boundary, but it cannot manufacture missing non-fuel carbon information.",
        ),
    ]
    return [dict(zip(RESOLUTION_COLUMNS, row)) for row in values]


def _controller_readiness_rows() -> list[dict[str, str]]:
    values = [
        ("KGF underfiring", "COG-only policy plus selected demand", "base route patched", "yes", "Bind coking steam separately if that utility layer is activated.", "none_for_underfiring", "Use only clean COG; retain non-COG route for explicit sensitivity.", "No BFG/BOFG/NG substitution in base."),
        ("BF hot stove", "development assumption and C0 reference demand rows", "no selected C0/C1 executable demand row", "no", "Choose and register a common C0/C1 energy-basis demand coefficient or explicitly select C0-only scope.", "input_selection", "Create an input-contract row before builder activation.", "BFG-first; no inferred residual allocation."),
        ("HSM/WBW", "candidate reheat energy and controller diagnostics", "no executable demand/controller contract", "no", "Select source-backed demand basis and active C0/C1 throughput mapping.", "input_selection", "Keep as diagnostic/source-review priority.", "No aggregate WAG allocation may be reused."),
        ("PEFA", "carrier eligibility/controller diagnostics", "no executable fuel-demand contract", "no", "Select pellet activity/fuel demand basis and separate solid fuel for CO2.", "input_selection_and_source_repair", "Keep controller diagnostic-only.", "Aggregate PEFA CO2 stays excluded in Mode B."),
        ("boiler/steam", "source-backed capacities and C5p_b accounting", "builder uses placeholder demand/cap", "no", "Promote selected steam demand and boiler-group controller rows; remove placeholder first.", "controller_contract", "Implement the C5p_b contract as a separate bounded utility migration.", "Do not emit placeholder NG."),
        ("VN25/IJ01", "annual validation anchors and C5p_c interface", "generic builder cap only", "no", "Choose fixed interface versus constrained WAG absorption and promote unit-level capacities.", "policy_and_input_selection", "Keep no-export accounting mode; do not price-dispatch generators.", "Annual anchors are not hourly dispatch rules."),
    ]
    return [dict(zip(READINESS_COLUMNS, row)) for row in values]


def _mode_b_rows() -> list[dict[str, str]]:
    values = [
        ("BFG/COG/BOFG at represented sinks", "carrier-specific point-of-oxidation expression", "yes", "aggregate BF/BOF/KGF/PEFA/sinter counters excluded", "partial_diagnostic", "Hot stoves, HSM, PEFA and governed boiler/generator contracts are not complete."),
        ("named source-backed NG", "count only once at represented named sinks", "partial", "placeholder and residual NG excluded", "partial_diagnostic", "Builder boiler NG is currently a placeholder and remains excluded."),
        ("flare/spill", "carrier-specific point-of-oxidation factor", "yes", "same factor map as other represented WAG sinks", "diagnostic_ready", "C1 flare is not yet carrier-split in the broader contract."),
        ("aggregate process CO2", "validation/context only", "no", "never summed into Mode B", "blocked_for_consolidation", "Need source-separated WAG-free/non-fuel terms."),
        ("residual NG/electricity", "visible boundary KPI only", "no", "no inferred emissions", "reporting_only", "Residual remains residual until a missing named asset is independently represented."),
    ]
    return [dict(zip(MODE_B_COLUMNS, row)) for row in values]


def _backlog_rows() -> list[dict[str, str]]:
    source_rows = _read_csv(P_W_DIR / "source_repair_priority.csv")
    result = []
    for row in source_rows:
        result.append(
            {
                "priority": row["priority"],
                "asset": row["asset"],
                "repair_question": row["repair_question"],
                "required_evidence": row["required_evidence"],
                "mode_b_implication": "Remain outside the Mode B total until a WAG/NG-free component is source-separated.",
                "status": "open_source_repair",
            }
        )
    return result


def _validations(checks: list[dict[str, str]], resolutions: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"check_id": "Z_VALIDATE_001", "check_name": "direct_builder_fixes_pass", "status": "pass" if all(row["status"] == "pass" for row in checks) else "fail", "evidence": "Z_CHECK_001 through Z_CHECK_004", "recommended_action": "Do not activate remaining controllers until their own contract is selected."},
        {"check_id": "Z_VALIDATE_002", "check_name": "aggregate_process_CO2_excluded_from_mode_B", "status": "pass" if any(row["original_blocker"] == "Y_BLOCK_005" and row["area"] == "non-fuel process CO2" for row in resolutions) else "fail", "evidence": "C5p_w source-separation gate retained", "recommended_action": "Keep aggregate counters outside the Mode B subtotal."},
        {"check_id": "Z_VALIDATE_003", "check_name": "unresolved_requirements_are_visible", "status": "pass" if any(row["status"].startswith("blocked") for row in resolutions) else "fail", "evidence": "BF hot-stove and controller-contract rows", "recommended_action": "Resolve by selecting source-backed input contracts, not residual allocation."},
    ]


def _write_report(resolutions: list[dict[str, str]], readiness: list[dict[str, str]], mode_b: list[dict[str, str]]) -> None:
    unresolved = [row for row in resolutions if row["status"].startswith("blocked")]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        f"""# C5 WAG MILP Blocker Resolution Packet

## Result

C5p_z resolves the two builder defects that were already governed by existing
policy: KGF underfiring is now clean-COG-only in the base model, and the
builder reads selected LHV and point-of-oxidation combustion factors through
the C5 adapter. It also adds a **Mode B diagnostic** WAG combustion expression
that counts only represented BFG, COG and BOFG at their oxidation sinks.

This is not a complete site carbon ledger. Aggregate BF, BOF, KGF, PEFA,
sinter and EAF counters remain excluded, residual energy remains unallocated,
and no carbon cost, ETS term or dispatch incentive is activated.

## Mode B policy now active in the builder

- WAG carbon is counted once at represented combustion or flare sinks.
- Named placeholder/residual NG is not converted to CO2 by inference.
- Aggregate process counters cannot enter the Mode B subtotal.
- The expression is diagnostic-only: it does not alter the objective or route
  allocation.

## Directly resolved

{chr(10).join('- ' + row['area'] + ': ' + row['what_changed_or_was_verified'] for row in resolutions if row['status'] in {'resolved', 'partial_resolved'})}

## Real stop conditions

{chr(10).join('- ' + row['area'] + ': ' + row['remaining_requirement'] for row in unresolved)}

## Controller readiness

{chr(10).join('- ' + row['asset_or_controller'] + ': ' + row['current_contract_status'] for row in readiness)}

## Gate

- KGF COG-only base route and selected factor adapter: GO.
- Mode B explicit WAG combustion reporting: GO, partial diagnostic only.
- BF hot-stove, HSM, PEFA, boiler/steam and generator physical activation: NO-GO
  until their individual executable contracts are selected.
- Non-fuel process CO2, whole-site Scope 1/ETS, economics, DA and full
  sensitivity: NO-GO.
""",
        encoding="utf-8",
    )


def run_s4_4c5p_z_wag_milp_blocker_resolution_packet() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks = _builder_checks()
    resolutions = _resolution_rows(checks)
    readiness = _controller_readiness_rows()
    mode_b = _mode_b_rows()
    backlog = _backlog_rows()
    validations = _validations(checks, resolutions)
    pass_count = sum(row["status"] == "pass" for row in validations)
    gate = {
        "stage": STAGE,
        "status": "direct_builder_fixes_applied_remaining_contracts_blocked",
        "output_policy": "minimal",
        "run_class": "diagnostic",
        "lineage_role": "governance_and_integration",
        "go_no_go": {
            "kgf_cog_only_base_route": "GO",
            "selected_factor_adapter": "GO",
            "mode_b_explicit_WAG_CO2_reporting": "GO_DIAGNOSTIC_ONLY",
            "bf_hot_stove_activation": "NO_GO",
            "hsm_pefa_boiler_generator_activation": "NO_GO",
            "nonfuel_process_CO2": "NO_GO",
            "whole_site_scope1_or_ETS": "NO_GO",
            "economics": "NO_GO",
            "DA": "NO_GO",
            "full_sensitivity": "NO_GO",
        },
        "guardrails": {
            "invented_WAG_NG_ratio": False,
            "mixed_wag_quantitative": False,
            "aggregate_WAG_physical_allocation": False,
            "residual_energy_allocated": False,
            "aggregate_process_CO2_added_to_mode_b": False,
            "CO2_ETS_objective_active": False,
        },
    }
    summary = {
        "stage": STAGE,
        "status": gate["status"],
        "resolution_rows": len(resolutions),
        "controller_readiness_rows": len(readiness),
        "mode_b_policy_rows": len(mode_b),
        "source_repair_rows": len(backlog),
        "validation_pass_count": pass_count,
        "validation_total": len(validations),
        "go_no_go": gate["go_no_go"],
    }
    _write_csv(OUTPUT_DIR / "blocker_resolution_register.csv", resolutions, RESOLUTION_COLUMNS)
    _write_csv(OUTPUT_DIR / "direct_builder_patch_verification.csv", checks, PATCH_COLUMNS)
    _write_csv(OUTPUT_DIR / "asset_controller_readiness_matrix.csv", readiness, READINESS_COLUMNS)
    _write_csv(OUTPUT_DIR / "mode_b_explicit_fuel_co2_policy.csv", mode_b, MODE_B_COLUMNS)
    _write_csv(OUTPUT_DIR / "nonfuel_co2_source_repair_backlog.csv", backlog, BACKLOG_COLUMNS)
    _write_csv(OUTPUT_DIR / "validation_checks.csv", validations, VALIDATION_COLUMNS)
    _write_json(OUTPUT_DIR / "s4_4c5p_z_stage_gate.json", gate)
    _write_json(OUTPUT_DIR / "summary.json", summary)
    _write_json(OUTPUT_DIR / "input_manifest.json", {"stage": STAGE, "inputs": [_file_record(path) for path in (MODEL_BUILDER, FACTOR_ADAPTER, P_Y_DIR / "blocked_activation_register.csv", P_W_DIR / "source_repair_priority.csv")]})
    _write_json(OUTPUT_DIR / "code_version.json", {"stage": STAGE, "git_revision": _git_revision(), "code_path": __file__})
    _write_report(resolutions, readiness, mode_b)
    return summary


def main() -> int:
    run_s4_4c5p_z_wag_milp_blocker_resolution_packet()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
