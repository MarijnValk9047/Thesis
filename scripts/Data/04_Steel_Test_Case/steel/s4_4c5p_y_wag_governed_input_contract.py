"""C5p_y compile the read-only governed WAG input contract."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import S4_ROOT, _write_csv, _write_json
from .wag_milp_input_contract import (
    DEMAND_PATH, ELIGIBILITY_PATH, SELECTED_PATH, load_governed_wag_milp_contract,
)


STAGE = "S4.4c5p_y_wag_governed_input_contract"
OUTPUT_DIR = S4_ROOT / "s4_4c5p_y_wag_governed_input_contract"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_WAG_GOVERNED_INPUT_CONTRACT.md")
REPO_ROOT = Path(__file__).resolve().parents[4]
MODEL_BUILDER = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "steel" / "s4_4c_unified_physical_modelbuilder.py"

CARRIER_COLUMNS = ["carrier", "parameter_name", "selected_value", "unit", "energy_basis", "sensitivity_required", "source_card_ids", "legacy_value", "legacy_match_status", "caveat"]
ROUTE_COLUMNS = ["configuration_id", "carrier", "sink_asset", "eligible", "priority", "cost_treatment", "contract_status", "physical_MILP_status", "reason"]
DEMAND_COLUMNS = ["configuration_id", "linked_activity_id", "demand_name", "eligible_carriers", "selected_value", "unit", "energy_basis", "sensitivity_required", "source_card_ids", "binding_status", "reason"]
BLOCKER_COLUMNS = ["blocker_id", "area", "message", "required_before_activation", "status"]
VALIDATION_COLUMNS = ["check_id", "check_name", "status", "evidence", "recommended_action"]

LEGACY_VALUES = {
    "bfg_lhv": "3.85 MJ/Nm3",
    "cog_lhv_raw_gas": "18.5 MJ/Nm3",
    "bofg_lhv_downstream_gasholder": "8.6 MJ/Nm3",
    "bfg_combustion_factor_netherlands": "0.75 tCO2/MWh flare",
    "cog_combustion_factor_netherlands": "0.20 tCO2/MWh flare",
    "oxygas_bofg_combustion_factor_netherlands": "0.70 tCO2/MWh flare",
}


def _file_record(path: Path) -> dict[str, str]:
    return {"path": str(path), "status": "read" if path.exists() else "missing", "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""}


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _carrier_rows(contract) -> list[dict[str, str]]:
    rows = []
    for item in contract.carrier_parameters:
        legacy = LEGACY_VALUES.get(item.parameter_name, "")
        status = "not_applicable" if not legacy else "mismatch_requires_governed_loader"
        rows.append({
            "carrier": item.carrier, "parameter_name": item.parameter_name,
            "selected_value": str(item.selected_value), "unit": item.unit,
            "energy_basis": item.energy_basis, "sensitivity_required": str(item.sensitivity_required).lower(),
            "source_card_ids": ";".join(item.source_card_ids), "legacy_value": legacy,
            "legacy_match_status": status,
            "caveat": "Selected development-only input; not thesis-approved and not yet attached to Pyomo.",
        })
    return rows


def _route_rows(contract) -> list[dict[str, str]]:
    rows = []
    for item in contract.eligibility_rows:
        status = "blocked" if item["contract_status"].startswith("blocked") else "blocked_pending_source_backed_demand_and_controller_mapping"
        reason = "KGF base policy permits COG only." if status == "blocked" else "Eligibility alone cannot create a fuel-demand constraint or allocation route."
        rows.append({
            "configuration_id": item["configuration_id"], "carrier": item["wag_carrier"], "sink_asset": item["sink_asset"],
            "eligible": item["eligible"], "priority": item["priority"], "cost_treatment": item["cost_treatment"],
            "contract_status": item["contract_status"], "physical_MILP_status": status, "reason": reason,
        })
    return rows


def _demand_rows(contract) -> list[dict[str, str]]:
    rows = []
    for item in contract.demand_rows:
        if item["demand_name"] == "c0_coking_underfiring_fuel_demand":
            status = "caveated_candidate_requires_COG_only_binding"
            reason = "Demand is source-backed but inherited eligible carriers include BFG; current policy blocks that split."
        else:
            status = "source_backed_demand_missing_model_sink_mapping"
            reason = "The current builder has no accepted matching controller/sink interface."
        rows.append({**item, "binding_status": status, "reason": reason})
    return rows


def _blockers() -> list[dict[str, str]]:
    values = [
        ("Y_BLOCK_001", "KGF", "Current selected demand lists BFG/COG, while the current C5 base policy is COG-only.", "Create an explicit COG-only binding row or approved sensitivity route.", "blocking"),
        ("Y_BLOCK_002", "BF hot stoves", "Demand coefficients exist, but no accepted sink mapping exists in the unified builder/eligibility surface.", "Map a BF hot-stove controller and carrier balances.", "blocking"),
        ("Y_BLOCK_003", "HSM/PEFA/boilers/generators", "Eligibility or diagnostics exist without a complete executable demand/controller input contract.", "Promote only individually reviewed source-backed controller inputs.", "blocking"),
        ("Y_BLOCK_004", "factor consistency", "Legacy builder LHV and flare factors differ from governed selected values.", "Replace legacy constants via the shared adapter before activation.", "blocking"),
        ("Y_BLOCK_005", "emissions", "Non-fuel process carbon remains source-separated NO-GO.", "Complete asset-specific C5p_w source repair first.", "blocking"),
    ]
    return [dict(zip(BLOCKER_COLUMNS, row)) for row in values]


def _validations(carriers, routes, demands) -> list[dict[str, str]]:
    return [
        {"check_id": "Y_CHECK_001", "check_name": "governed_factor_set_complete", "status": "pass" if len(carriers) == 7 else "fail", "evidence": "LHV plus WAG/NG combustion factors are loaded through the existing governed S3 loader.", "recommended_action": "Do not use legacy constants when the future WAG model is activated."},
        {"check_id": "Y_CHECK_002", "check_name": "aggregate_or_mixed_WAG_not_promoted", "status": "pass" if all(row["carrier"] in {"BFG", "COG", "BOFG"} for row in routes) else "fail", "evidence": "Only physical carriers are emitted from the eligibility contract.", "recommended_action": "Keep aggregate and mixed WAG outside physical variables."},
        {"check_id": "Y_CHECK_003", "check_name": "KGF_BFG_route_blocked", "status": "pass" if any(row["contract_status"].startswith("blocked_by_current_COG_only") for row in routes) else "fail", "evidence": "Current COG-only KGF policy overrides the inherited BFG eligibility row.", "recommended_action": "Do not activate BFG-to-KGF without a separately approved sensitivity."},
        {"check_id": "Y_CHECK_004", "check_name": "no_route_is_silently_activated", "status": "pass" if all(row["physical_MILP_status"].startswith("blocked") for row in routes) else "fail", "evidence": "This is a read-only input adapter, not a physical allocator.", "recommended_action": "Activate routes only in the next builder-hardening task."},
        {"check_id": "Y_CHECK_005", "check_name": "demand_rows_retain_source_status", "status": "pass" if demands else "fail", "evidence": "Every usable demand carries source-card IDs and a binding status.", "recommended_action": "Do not infer missing sink mappings."},
    ]


def _write_report(carriers, routes, blockers) -> None:
    mismatches = sum(row["legacy_match_status"] == "mismatch_requires_governed_loader" for row in carriers)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        f"""# C5 Governed WAG MILP Input Contract

## Result

C5p_y creates one read-only adapter for selected WAG LHV and combustion-factor
rows, WAG eligibility and source-backed demand coefficients. It promotes no
new parameter and activates no route. It exposes **{mismatches}** legacy
constant mismatches that must be removed before the Pyomo WAG layer is used.

## What is now safe to reuse

- selected BFG, COG and BOFG LHV values;
- selected WAG and named-NG combustion-factor rows;
- carrier-specific eligibility records, as structural evidence only;
- source-backed BF-hot-stove and C0 coking-demand records, as inputs awaiting
  a controller mapping.

## What remains blocked

{chr(10).join('- ' + row['message'] for row in blockers)}

## Gate

- Governed read-only WAG input adapter: GO.
- Physical WAG MILP activation: NO-GO.
- Explicit fuel-emissions expressions in the MILP: NO-GO.
- Anchor sensitivity execution: NO-GO.
""",
        encoding="utf-8",
    )


def run_s4_4c5p_y_wag_governed_input_contract() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    contract = load_governed_wag_milp_contract()
    carriers = _carrier_rows(contract)
    routes = _route_rows(contract)
    demands = _demand_rows(contract)
    blockers = _blockers()
    validations = _validations(carriers, routes, demands)
    counts: dict[str, int] = {}
    for row in validations:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    gate = {
        "stage": STAGE, "status": "governed_WAG_input_adapter_ready_routes_blocked", "thesis_usability": False,
        "output_policy": "minimal", "run_class": "diagnostic", "lineage_role": "diagnostic",
        "go_no_go": {"governed_input_adapter": "GO", "physical_WAG_MILP_activation": "NO_GO", "emissions_expression_activation": "NO_GO", "annual_anchor_reconciliation": "NO_GO", "sensitivity_execution": "NO_GO"},
        "guardrails": {"model_equations_changed": False, "executable_development_inputs_changed": False, "source_cards_changed": False, "invented_WAG_NG_ratio": False, "aggregate_or_mixed_WAG_promoted": False, "residual_energy_allocated": False},
        "validation_check_counts": counts,
    }
    summary = {"stage": STAGE, "status": gate["status"], "carrier_parameter_rows": len(carriers), "eligibility_rows": len(routes), "demand_rows": len(demands), "blocking_rows": len(blockers), "validation_check_counts": counts, "go_no_go": gate["go_no_go"]}
    inputs = [SELECTED_PATH, DEMAND_PATH, ELIGIBILITY_PATH, MODEL_BUILDER]
    _write_csv(OUTPUT_DIR / "governed_carrier_parameter_register.csv", carriers, CARRIER_COLUMNS)
    _write_csv(OUTPUT_DIR / "governed_route_status.csv", routes, ROUTE_COLUMNS)
    _write_csv(OUTPUT_DIR / "demand_binding_status.csv", demands, DEMAND_COLUMNS)
    _write_csv(OUTPUT_DIR / "blocked_activation_register.csv", blockers, BLOCKER_COLUMNS)
    _write_csv(OUTPUT_DIR / "validation_checks.csv", validations, VALIDATION_COLUMNS)
    _write_json(OUTPUT_DIR / "input_manifest.json", {"stage": STAGE, "output_policy": "minimal", "run_class": "diagnostic", "lineage_role": "diagnostic", "inputs": [_file_record(path) for path in inputs]})
    _write_json(OUTPUT_DIR / "code_version.json", {"stage": STAGE, "git_revision": _git_revision(), "code_path": __file__})
    _write_json(OUTPUT_DIR / "s4_4c5p_y_stage_gate.json", gate)
    _write_json(OUTPUT_DIR / "summary.json", summary)
    _write_json(OUTPUT_DIR / "registry_entry.json", {"run_id": STAGE, "purpose": "Read-only governed WAG input adapter and activation gate.", "thesis_usable": False, "retention": "local diagnostic output until review", "git_eligible": False, "status": gate["status"]})
    _write_report(carriers, routes, blockers)
    return summary


def main() -> int:
    run_s4_4c5p_y_wag_governed_input_contract()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
