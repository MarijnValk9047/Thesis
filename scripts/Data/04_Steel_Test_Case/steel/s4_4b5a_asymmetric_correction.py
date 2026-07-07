"""S4.4b5a asymmetric correction for C0/C1 development inputs.

The correction starts from S4.4b5 completed inputs, replaces unsafe CP2=CP1
and BF7=BF6 symmetry assumptions, and writes a corrected input package for
static physical regression. It remains development evidence only.
"""

from __future__ import annotations

import csv
import json
import shutil
import time
from pathlib import Path
from typing import Any

from .s4_4b_unified_input_validator import validate_unified_dev_inputs, write_validation_outputs


REPO_ROOT = Path(__file__).resolve().parents[4]
S4_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4"
B5_INPUT_DIR = S4_ROOT / "s4_4b5_c0_c1_assumption_completion/completed_dev_inputs"
B5A_DIR = S4_ROOT / "s4_4b5a_asymmetric_c0_c1_correction"
CORRECTED_INPUT_DIR = B5A_DIR / "corrected_dev_inputs"

C0 = "C0_current_BF_BOF_reference"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
C1_ALIAS = "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"
BF7_SCALE = 6.0 / 3.9
BF6_SHARE = 3.9 / (3.9 + 6.0)
BF7_SHARE = 6.0 / (3.9 + 6.0)
BF6_ANNUAL_MT = 7.2 * BF6_SHARE
BF7_ANNUAL_MT = 7.2 * BF7_SHARE

TABLES_16 = [
    "configuration_assets.csv",
    "process_units.csv",
    "process_io_coefficients.csv",
    "process_energy_intensities.csv",
    "process_emission_factors.csv",
    "buffers_and_stores.csv",
    "wag_generation_coefficients.csv",
    "wag_sink_eligibility.csv",
    "utility_demands.csv",
    "utility_conversion_assets.csv",
    "external_supply_costs.csv",
    "market_price_inputs.csv",
    "production_targets.csv",
    "validation_anchors.csv",
    "policy_modes.csv",
    "solver_and_horizon_config.csv",
]
EXTRA_COLUMNS = [
    "source_basis",
    "capacity_proxy_only",
    "gas_structure_role",
    "closure_conflict_status",
]


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


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


def _ensure_columns(rows: list[dict[str, str]], columns: list[str]) -> list[str]:
    for column in EXTRA_COLUMNS:
        if column not in columns:
            columns.append(column)
    for row in rows:
        for column in columns:
            row.setdefault(column, "")
    return columns


def _load_tables() -> tuple[dict[str, list[dict[str, str]]], dict[str, list[str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    columns: dict[str, list[str]] = {}
    for table in TABLES_16:
        rows, cols = _read_csv(B5_INPUT_DIR / table)
        columns[table] = _ensure_columns(rows, cols)
        tables[table] = rows
    return tables, columns


def _append_or_replace(rows: list[dict[str, str]], row: dict[str, str], keys: list[str]) -> None:
    key = tuple(row.get(k, "") for k in keys)
    for idx, existing in enumerate(rows):
        if tuple(existing.get(k, "") for k in keys) == key:
            rows[idx] = row
            return
    rows.append(row)


def _template(columns: list[str]) -> dict[str, str]:
    return {column: "" for column in columns}


def _patch_bf7(tables: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    bf7_min = 120.0 * BF7_SCALE
    bf7_max = 170.0 * BF7_SCALE
    patched = False
    for row in tables["process_units.csv"]:
        if row.get("configuration_id") == C0 and row.get("asset_id") == "blast_furnace_7":
            row["min_rate"] = f"{bf7_min:.8f}"
            row["max_rate"] = f"{bf7_max:.8f}"
            row["input_status"] = "development_only"
            row["thesis_usability"] = "false"
            row["human_review_required"] = "false"
            row["assumption_id"] = "S44B5A_BF7_EMISSIONS_SHARE_SCALED_LIMITS"
            row["derivation_method"] = "emissions_share_scaled_capacity_proxy"
            row["source_hierarchy_used"] = "Roland Berger/FNV/Tata memo BF6/BF7 CO2 split; user-supplied task values"
            row["source_basis"] = "Roland_Berger_FNV_Tata_memo_BF6_BF7_CO2_split"
            row["sensitivity_required"] = "true"
            row["caveat"] = (
                "Development proxy; assumes CO2 split tracks BF production/capacity; "
                "not Tata-measured operational capacity."
            )
            row["candidate_id"] = "S44B5A_BF7_LIMITS_FROM_CO2_SPLIT"
            patched = True
            break
    return {
        "replacement_id": "S44B5A_REPLACE_BF7_EQUALS_BF6",
        "target": "BF7 operating limits",
        "old_assumption": "BF7 inherited BF6 120-170 t_sinter/h",
        "new_assumption": f"BF7 scaled by {BF7_SCALE:.10f}: {bf7_min:.8f}-{bf7_max:.8f} t_sinter/h",
        "bf6_share": BF6_SHARE,
        "bf7_share": BF7_SHARE,
        "bf7_vs_bf6_scale": BF7_SCALE,
        "bf6_implied_liquid_steel_mton_y": BF6_ANNUAL_MT,
        "bf7_implied_liquid_steel_mton_y": BF7_ANNUAL_MT,
        "derivation_method": "emissions_share_scaled_capacity_proxy",
        "source_basis": "Roland_Berger_FNV_Tata_memo_BF6_BF7_CO2_split",
        "sensitivity_required": "true",
        "thesis_usability": "false",
        "patch_applied": str(patched).lower(),
        "caveat": "Development proxy only; not Tata-measured capacity.",
    }


def _patch_cp2_capacity(tables: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    patched = False
    for row in tables["process_units.csv"]:
        if row.get("configuration_id") == C0 and row.get("asset_id") == "coking_plant_2":
            row["min_rate"] = "150"
            row["max_rate"] = "180"
            row["rate_unit"] = "t_coal/h"
            row["input_status"] = "development_only"
            row["thesis_usability"] = "false"
            row["human_review_required"] = "false"
            row["assumption_id"] = "S44B5A_CP2_TEMPORARY_CAPACITY_PROXY_FROM_CP1"
            row["derivation_method"] = "temporary_capacity_proxy_from_CP1_only"
            row["source_hierarchy_used"] = "S4.4b3 CP1 figure value; no CP2-specific capacity found in reviewed inputs"
            row["source_basis"] = "Athanasiadis_source_card_workbook_CP1_CP2_different_gas_structure"
            row["capacity_proxy_only"] = "true"
            row["sensitivity_required"] = "true"
            row["caveat"] = (
                "Capacity proxy only; CP2 gas-input structure differs and is modelled separately. "
                "Not Tata-measured CP2 capacity."
            )
            row["candidate_id"] = "S44B5A_CP2_CAPACITY_PROXY_FROM_CP1"
            patched = True
            break
    return {
        "replacement_id": "S44B5A_REPLACE_CP2_EQUALS_CP1",
        "target": "CP2 capacity and gas structure",
        "old_assumption": "CP2 inherited CP1 without structural gas distinction",
        "new_assumption": "CP2 keeps CP1 150-180 t coal/h as capacity proxy only; CP2 process gas is pure COG.",
        "derivation_method": "temporary_capacity_proxy_from_CP1_only",
        "source_basis": "Athanasiadis_source_card_workbook_CP1_CP2_different_gas_structure",
        "sensitivity_required": "true",
        "thesis_usability": "false",
        "patch_applied": str(patched).lower(),
        "caveat": "Capacity proxy only; gas-input structure is not symmetric.",
    }


def _patch_c1_inactive_legacy_assets(
    tables: dict[str, list[dict[str, str]]],
    columns: dict[str, list[str]],
) -> dict[str, Any]:
    rows = tables["process_units.csv"]
    cols = columns["process_units.csv"]
    additions = [
        {
            "asset_id": "coking_plant_2",
            "process_id": f"{C1}__coking_plant_2__structurally_inactive",
            "rate_unit": "t_coal/h",
            "assumption_id": "S44B5A_C1_KGF2_STRUCTURALLY_INACTIVE",
            "source_basis": "S4.4c5c_topology_contract_C1_KGF2_inactive",
            "caveat": "C1 topology keeps KGF2/Coking Plant 2 inactive; retained coking route is KGF1 only.",
        },
        {
            "asset_id": "blast_furnace_7",
            "process_id": f"{C1}__blast_furnace_7__structurally_inactive",
            "rate_unit": "t_sinter/h",
            "assumption_id": "S44B5A_C1_BF7_STRUCTURALLY_INACTIVE",
            "source_basis": "S4.4c5c_topology_contract_C1_BF7_inactive",
            "caveat": "C1 topology keeps BF7 inactive; retained blast-furnace route is BF6 only.",
        },
    ]
    added = 0
    for addition in additions:
        if any(row.get("configuration_id") == C1 and row.get("asset_id") == addition["asset_id"] for row in rows):
            continue
        row = _template(cols)
        row.update(
            {
                "process_id": addition["process_id"],
                "asset_id": addition["asset_id"],
                "configuration_id": C1,
                "min_rate": "0",
                "max_rate": "0",
                "rate_unit": addition["rate_unit"],
                "ramp_up": "0",
                "ramp_down": "0",
                "commitment_type": "structurally_inactive",
                "source_card_ids": "S4.4c5c_topology_contract",
                "candidate_id": addition["assumption_id"],
                "evidence_strength": "development_topology_contract",
                "input_status": "development_only",
                "thesis_usability": "false",
                "codex_may_decide": "false",
                "human_review_required": "false",
                "caveat": addition["caveat"],
                "migration_stage": "S4.4b5a/S4.4c5c",
                "migration_source_artifacts": "docs/optimisation/steel/S4/STEEL_S4_4A_UNIFIED_C0_C1_MODEL_CONTRACT.md",
                "migration_notes": "Explicit zero-capacity retained-route inactive topology row.",
                "executable_input": "true",
                "assumption_id": addition["assumption_id"],
                "derivation_method": "topology_contract_zero_capacity_row",
                "source_hierarchy_used": "S4.4c5c user-specified C1 topology",
                "source_basis": addition["source_basis"],
                "sensitivity_required": "false",
                "human_confirmed_figure_value": "false",
                "executable_now": "true",
                "deferred_for_s4_4c_equations": "false",
            }
        )
        rows.append(row)
        added += 1
    return {
        "replacement_id": "S44B5A_C1_INACTIVE_KGF2_BF7_TOPOLOGY_ROWS",
        "target": "C1 inactive KGF2/BF7 topology visibility",
        "old_assumption": "C1 inactive KGF2 and BF7 were implied by omission.",
        "new_assumption": "C1 KGF2 and BF7 are explicit zero-capacity structurally inactive rows.",
        "derivation_method": "topology_contract_zero_capacity_row",
        "source_basis": "S4.4c5c_topology_contract",
        "sensitivity_required": "false",
        "thesis_usability": "false",
        "patch_applied": str(added > 0).lower(),
        "rows_added": added,
        "caveat": "Visibility row only; no inactive asset output or flexibility is introduced.",
    }


def _patch_cp_gas_structure(tables: dict[str, list[dict[str, str]]], columns: dict[str, list[str]]) -> list[dict[str, str]]:
    rows = tables["process_io_coefficients.csv"]
    cols = columns["process_io_coefficients.csv"]
    added: list[dict[str, str]] = []

    cp1 = {
        **_template(cols),
        "process_id": "coking_plant_1",
        "input_material": "wag_cok1_mix",
        "output_material": "process_heat",
        "coefficient": "1.0",
        "coefficient_unit": "proxy_gas_input/t_coal",
        "basis": "CP1 WAGs COK1 mixture structural process-gas input",
        "source_card_ids": "REPO-ATH-GAS-ADDENDUM",
        "candidate_id": "S44B5A_CP1_WAGS_COK1_MIX_INPUT",
        "evidence_strength": "workbook_structural_evidence",
        "input_status": "development_only",
        "thesis_usability": "false",
        "codex_may_decide": "false",
        "human_review_required": "false",
        "caveat": "CP1 has WAGs COK1 mixture input through the WAG_COK1 mixer; proxy coefficient is structural only.",
        "assumption_id": "S44B5A_CP1_WAGS_COK1_STRUCTURE",
        "derivation_method": "workbook_structural_port_migration",
        "source_hierarchy_used": "S4.4b2 compiled link_ports: coking_plant_1 wag_cok1_mix_bus",
        "source_basis": "Athanasiadis_source_card_workbook_CP1_WAGs_COK1",
        "sensitivity_required": "true",
        "human_confirmed_figure_value": "false",
        "executable_now": "true",
        "deferred_for_s4_4c_equations": "false",
        "gas_structure_role": "CP1_WAG_COK1_mixture_input",
    }
    cp2 = {
        **_template(cols),
        "process_id": "coking_plant_2",
        "input_material": "COG",
        "output_material": "process_heat",
        "coefficient": "1.0",
        "coefficient_unit": "proxy_gas_input/t_coal",
        "basis": "CP2 pure COG structural process-gas input",
        "source_card_ids": "REPO-ATH-GAS-ADDENDUM;STEEL-SC-0016",
        "candidate_id": "S44B5A_CP2_PURE_COG_INPUT",
        "evidence_strength": "workbook_structural_evidence",
        "input_status": "development_only",
        "thesis_usability": "false",
        "codex_may_decide": "false",
        "human_review_required": "false",
        "caveat": "CP2 uses pure COG as structural gas input; generic WAG mixture input is not allowed without explicit evidence.",
        "assumption_id": "S44B5A_CP2_PURE_COG_STRUCTURE",
        "derivation_method": "workbook_structural_port_migration",
        "source_hierarchy_used": "S4.4b2 compiled link_ports: coking_plant_2 COG_bus",
        "source_basis": "Athanasiadis_source_card_workbook_CP2_pure_COG",
        "sensitivity_required": "true",
        "human_confirmed_figure_value": "false",
        "executable_now": "true",
        "deferred_for_s4_4c_equations": "false",
        "gas_structure_role": "CP2_pure_COG_input",
    }
    _append_or_replace(rows, cp1, ["process_id", "input_material", "output_material"])
    _append_or_replace(rows, cp2, ["process_id", "input_material", "output_material"])
    added.extend([cp1, cp2])
    return added


def _patch_wag_sink_eligibility(tables: dict[str, list[dict[str, str]]]) -> None:
    for row in tables["wag_sink_eligibility.csv"]:
        sink = row.get("sink_asset", "")
        carrier = row.get("wag_carrier", "")
        if sink == "WAG_COK1_mixer":
            row["gas_structure_role"] = "CP1_WAG_COK1_mixture_input"
            row["source_basis"] = "Athanasiadis_source_card_workbook_CP1_WAGs_COK1"
            if carrier in {"BFG", "COG"}:
                row["eligible"] = "true"
                row["caveat"] = "CP1 WAG_COK1 mixer eligibility retained for BFG/COG; no direct WAG valuation."
            elif carrier == "BOFG":
                row["eligible"] = "false"
                row["caveat"] = "BOFG not eligible for CP1 WAG_COK1 mixer in S4.4b2 mixing rules."
        if sink == "WAG_flare_spillage":
            row["eligible"] = "true"
            row["flaring_allowed"] = "true"


def _closure_conflicts() -> list[dict[str, str]]:
    return [
        {
            "conflict_id": "S44B5A_CLOSURE_CONFLICT_001",
            "source_or_history": "Roland Berger/FNV/Tata Direct-to-DRI memo",
            "conflict_statement": "Memo describes closing Hoogoven 6 and KGF2 first.",
            "selected_default": "Project freeze keeps BF6 active, BF7 inactive, KGF1 active, KGF2 inactive in C1.",
            "decision_status": "conflict_recorded_default_unchanged",
            "human_decision_required_to_change_default": "true",
            "caveat": "Recorded as conflict; does not alter selected project default.",
        },
        {
            "conflict_id": "S44B5A_CLOSURE_CONFLICT_002",
            "source_or_history": "Athanasiadis/Badarinath/repo freeze history",
            "conflict_statement": "History contains BF7/CP1 or BF7/CP2 variants.",
            "selected_default": "Current selected model default remains project freeze.",
            "decision_status": "conflict_recorded_default_unchanged",
            "human_decision_required_to_change_default": "true",
            "caveat": "Variants remain sensitivity/history, not default topology.",
        },
    ]


def _custom_gate(tables: dict[str, list[dict[str, str]]], validation_result: dict[str, Any], conflict_rows: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    blockers: list[dict[str, str]] = []
    if validation_result["failure_count"] != 0:
        return "blocked_corrected_inputs_invalid", [{"blocker": "validator_failure", "details": str(validation_result["failure_count"])}]
    bf7 = next(
        row for row in tables["process_units.csv"]
        if row.get("configuration_id") == C0 and row.get("asset_id") == "blast_furnace_7"
    )
    if bf7.get("derivation_method") != "emissions_share_scaled_capacity_proxy" or bf7.get("min_rate") == "120":
        return "blocked_bf7_asymmetry_patch_failed", [{"blocker": "BF7 symmetry", "details": "BF7 still equals BF6 or lacks emissions proxy derivation."}]
    io = tables["process_io_coefficients.csv"]
    cp1_mix = any(row.get("process_id") == "coking_plant_1" and row.get("input_material") == "wag_cok1_mix" for row in io)
    cp2_cog = any(row.get("process_id") == "coking_plant_2" and row.get("input_material") == "COG" for row in io)
    cp2_wag = any(row.get("process_id") == "coking_plant_2" and row.get("input_material", "").lower() in {"wag_blend", "wag_cok1_mix"} for row in io)
    if not cp1_mix or not cp2_cog or cp2_wag:
        return "blocked_cp2_wag_structure_patch_failed", [{"blocker": "CP1/CP2 gas structure", "details": "CP1 mix or CP2 pure COG structure invalid."}]
    if not conflict_rows:
        return "blocked_closure_conflict_unrecorded", [{"blocker": "closure conflict", "details": "Closure conflict register empty."}]
    return "pass_to_phase2_validation", blockers


def _corrected_manifest(tables: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for table, table_rows in tables.items():
        for row in table_rows:
            if row.get("assumption_id", "").startswith("S44B5A") or row.get("candidate_id", "").startswith("S44B5A"):
                rows.append({
                    "table_name": table,
                    "row_id": row.get("process_id") or row.get("asset_id") or row.get("buffer_id") or row.get("sink_asset") or row.get("run_profile_id") or "",
                    "configuration_id": row.get("configuration_id", ""),
                    "assumption_id": row.get("assumption_id", ""),
                    "candidate_id": row.get("candidate_id", ""),
                    "derivation_method": row.get("derivation_method", ""),
                    "source_basis": row.get("source_basis", ""),
                    "sensitivity_required": row.get("sensitivity_required", ""),
                    "thesis_usability": row.get("thesis_usability", ""),
                    "caveat": row.get("caveat", ""),
                })
    return rows


def run_b5a_correction() -> dict[str, Any]:
    start = time.perf_counter()
    B5A_DIR.mkdir(parents=True, exist_ok=True)
    CORRECTED_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    tables, columns = _load_tables()
    replacements = [
        _patch_bf7(tables),
        _patch_cp2_capacity(tables),
        _patch_c1_inactive_legacy_assets(tables, columns),
    ]
    gas_rows = _patch_cp_gas_structure(tables, columns)
    _patch_wag_sink_eligibility(tables)
    conflict_rows = _closure_conflicts()

    for table in TABLES_16:
        _write_csv(CORRECTED_INPUT_DIR / table, tables[table], columns[table])
    manifest_path = B5_INPUT_DIR / "s4_4b_unified_dev_inputs_manifest.csv"
    if manifest_path.exists():
        shutil.copy2(manifest_path, CORRECTED_INPUT_DIR / manifest_path.name)

    validation_result = validate_unified_dev_inputs(CORRECTED_INPUT_DIR.resolve())
    write_validation_outputs(validation_result, CORRECTED_INPUT_DIR.resolve())
    gate, blockers = _custom_gate(tables, validation_result, conflict_rows)

    patch_report = {
        "stage": "S4.4b5a",
        "source_input_dir": _rel(B5_INPUT_DIR),
        "corrected_input_dir": _rel(CORRECTED_INPUT_DIR),
        "phase1_gate": gate,
        "bf6_share": BF6_SHARE,
        "bf7_share": BF7_SHARE,
        "bf7_vs_bf6_scale": BF7_SCALE,
        "bf6_implied_liquid_steel_mton_y": BF6_ANNUAL_MT,
        "bf7_implied_liquid_steel_mton_y": BF7_ANNUAL_MT,
        "validator_failure_count": validation_result["failure_count"],
        "validator_warning_count": validation_result["warning_count"],
        "raw_pdfs_inspected": False,
        "thesis_usable": False,
        "Tata_validated": False,
        "runtime_seconds": round(time.perf_counter() - start, 6),
        "caveat": "Development correction only; BF7 scale is an emissions-share capacity proxy and CP2 capacity is still a proxy while gas structure differs.",
    }
    assumption_rows = replacements + [
        {
            "replacement_id": "S44B5A_CP_GAS_STRUCTURE",
            "target": "CP1/CP2 gas-input structure",
            "old_assumption": "CP2 structural gas input not distinguished in executable package",
            "new_assumption": "CP1 WAG_COK1 mixture; CP2 pure COG.",
            "rows_added": str(len(gas_rows)),
            "derivation_method": "workbook_structural_port_migration",
            "source_basis": "Athanasiadis_source_card_workbook_CP1_CP2_gas_ports",
            "sensitivity_required": "true",
            "thesis_usability": "false",
            "patch_applied": "true",
            "caveat": "Structural gas ports only; coefficients are proxy placeholders for physical feasibility.",
        }
    ]
    _write_json(B5A_DIR / "s4_4b5a_asymmetry_patch_report.json", patch_report)
    _write_csv(B5A_DIR / "s4_4b5a_asymmetry_patch_report.csv", [patch_report])
    _write_csv(B5A_DIR / "s4_4b5a_assumption_replacements.csv", assumption_rows)
    _write_csv(B5A_DIR / "s4_4b5a_closure_conflict_register.csv", conflict_rows)
    _write_csv(B5A_DIR / "s4_4b5a_corrected_rows_manifest.csv", _corrected_manifest(tables))
    _write_json(B5A_DIR / "s4_4b5a_validation_report.json", validation_result)
    _write_csv(
        B5A_DIR / "s4_4b5a_validation_report.csv",
        [{
            "decision": validation_result["decision"],
            "failure_count": validation_result["failure_count"],
            "warning_count": validation_result["warning_count"],
            **validation_result["summary"],
        }],
    )
    stage_gate = {
        "stage": "S4.4b5a",
        "decision": gate,
        "may_proceed_to_phase2_validation": str(gate == "pass_to_phase2_validation").lower(),
        "validator_failure_count": str(validation_result["failure_count"]),
        "blocker_count": str(len(blockers)),
        "thesis_usable": "false",
        "Tata_validated": "false",
        "caveat": patch_report["caveat"],
    }
    _write_json(B5A_DIR / "s4_4b5a_stage_gate.json", stage_gate)
    _write_csv(B5A_DIR / "s4_4b5a_stage_gate.csv", [stage_gate])
    return patch_report


def main() -> None:
    print(json.dumps(run_b5a_correction(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
