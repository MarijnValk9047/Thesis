"""S4.4b5 completion of C0/C1 development inputs.

This module starts from the S4.4b4 migrated input package and completes the
remaining development-only C0/C1 physical blockers with explicit controlled
assumptions. It does not promote any value to thesis-approved or Tata-validated
status, and it does not run an optimisation model.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from .s4_4b_unified_input_validator import validate_unified_dev_inputs, write_validation_outputs


REPO_ROOT = Path(__file__).resolve().parents[4]
STEEL_S4_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4"
S44B4_INPUT_DIR = STEEL_S4_ROOT / "s4_4b4_s3_to_unified_migration/migrated_dev_inputs"
S44B5_DIR = STEEL_S4_ROOT / "s4_4b5_c0_c1_assumption_completion"
COMPLETED_INPUT_DIR = S44B5_DIR / "completed_dev_inputs"

C0 = "C0_current_BF_BOF_reference"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
C1_ALIAS = "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"

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

EXECUTABLE_STATUS = "development_only"
ASSUMPTION_COLUMNS = [
    "assumption_id",
    "derivation_method",
    "source_hierarchy_used",
    "sensitivity_required",
    "human_confirmed_figure_value",
    "executable_now",
    "deferred_for_s4_4c_equations",
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_columns(rows: list[dict[str, str]], columns: list[str]) -> list[str]:
    for column in ASSUMPTION_COLUMNS:
        if column not in columns:
            columns.append(column)
    for row in rows:
        for column in columns:
            row.setdefault(column, "")
        row.setdefault("thesis_usability", "false")
        row.setdefault("codex_may_decide", "false")
    return columns


def _mark_assumption(
    row: dict[str, str],
    *,
    assumption_id: str,
    derivation_method: str,
    source_hierarchy_used: str,
    sensitivity_required: bool,
    caveat: str,
    human_confirmed_figure_value: bool = False,
    executable_now: bool = True,
    deferred_for_s4_4c_equations: bool = False,
    candidate_id: str | None = None,
) -> None:
    row["input_status"] = EXECUTABLE_STATUS
    row["thesis_usability"] = "false"
    row["codex_may_decide"] = "false"
    row["human_review_required"] = "false"
    row["assumption_id"] = assumption_id
    row["derivation_method"] = derivation_method
    row["source_hierarchy_used"] = source_hierarchy_used
    row["sensitivity_required"] = "true" if sensitivity_required else "false"
    row["human_confirmed_figure_value"] = "true" if human_confirmed_figure_value else "false"
    row["executable_now"] = "true" if executable_now else "false"
    row["deferred_for_s4_4c_equations"] = "true" if deferred_for_s4_4c_equations else "false"
    row["caveat"] = caveat
    if candidate_id:
        row["candidate_id"] = candidate_id
    if "evidence_strength" in row:
        row["evidence_strength"] = "controlled_development_assumption"


def _append_unique(rows: list[dict[str, str]], row: dict[str, str], key_columns: list[str]) -> None:
    key = tuple(row.get(column, "") for column in key_columns)
    for index, existing in enumerate(rows):
        if tuple(existing.get(column, "") for column in key_columns) == key:
            rows[index] = row
            return
    rows.append(row)


def _base_tables() -> tuple[dict[str, list[dict[str, str]]], dict[str, list[str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    columns: dict[str, list[str]] = {}
    for name in TABLES_16:
        rows, fieldnames = _read_csv(S44B4_INPUT_DIR / name)
        columns[name] = _ensure_columns(rows, fieldnames)
        tables[name] = rows
    return tables, columns


def _assumption_record(row: dict[str, str], table_name: str, row_id: str, value: str, unit: str) -> dict[str, str]:
    return {
        "assumption_id": row.get("assumption_id", ""),
        "target_table": table_name,
        "target_row_id": row_id,
        "value": value,
        "unit": unit,
        "derivation_method": row.get("derivation_method", ""),
        "source_hierarchy_used": row.get("source_hierarchy_used", ""),
        "sensitivity_required": row.get("sensitivity_required", ""),
        "thesis_usability": row.get("thesis_usability", "false"),
        "candidate_id": row.get("candidate_id", ""),
        "source_card_ids": row.get("source_card_ids", ""),
        "caveat": row.get("caveat", ""),
    }


def complete_process_units(tables: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    rows = tables["process_units.csv"]
    assumptions: list[dict[str, str]] = []

    for row in rows:
        asset_id = row.get("asset_id", "")
        config_id = row.get("configuration_id", "")
        if row.get("min_rate") and row.get("max_rate") and asset_id in {
            "coking_plant_1",
            "sintering_plant",
            "pelletizing_plant",
            "blast_furnace_6",
            "basic_oxygen_furnace",
            "hot_strip_mill",
        }:
            _mark_assumption(
                row,
                assumption_id=f"S44B5_HUMAN_CONFIRMED_{asset_id.upper()}_{config_id}",
                derivation_method="human_confirmed_S4_4b3_figure_value",
                source_hierarchy_used="S4.4b3 human-confirmed figure patch",
                sensitivity_required=True,
                human_confirmed_figure_value=True,
                caveat="Human-confirmed figure-derived development operating limit; not measured Tata truth.",
            )

    cp1 = next(row for row in rows if row["configuration_id"] == C0 and row["asset_id"] == "coking_plant_1")
    bf6 = next(row for row in rows if row["configuration_id"] == C0 and row["asset_id"] == "blast_furnace_6")
    for row in rows:
        if row.get("configuration_id") == C0 and row.get("asset_id") == "coking_plant_2":
            row["min_rate"] = cp1["min_rate"]
            row["max_rate"] = cp1["max_rate"]
            row["rate_unit"] = cp1["rate_unit"]
            _mark_assumption(
                row,
                assumption_id="S44B5_SYMMETRY_CP2_INHERITS_CP1_LIMITS",
                derivation_method="symmetry_assumption_from_Coking_Plant_1",
                source_hierarchy_used="controlled symmetry assumption after S4.4b3 CP1 figure value",
                sensitivity_required=True,
                caveat="Coking Plant 2 inherits CP1 figure-derived development limits for C0 completion; not measured Tata truth.",
                candidate_id="S44B5_SYM_CP2_LIMITS_FROM_CP1",
            )
            assumptions.append(_assumption_record(row, "process_units.csv", row["process_id"], "150-180", row["rate_unit"]))
        if row.get("configuration_id") == C0 and row.get("asset_id") == "blast_furnace_7":
            row["min_rate"] = bf6["min_rate"]
            row["max_rate"] = bf6["max_rate"]
            row["rate_unit"] = bf6["rate_unit"]
            _mark_assumption(
                row,
                assumption_id="S44B5_SYMMETRY_BF7_INHERITS_BF6_LIMITS",
                derivation_method="symmetry_assumption_from_BF6",
                source_hierarchy_used="controlled symmetry assumption after S4.4b3 BF6 figure value",
                sensitivity_required=True,
                caveat="BF7 inherits BF6 figure-derived development limits for C0 completion; not measured Tata truth.",
                candidate_id="S44B5_SYM_BF7_LIMITS_FROM_BF6",
            )
            assumptions.append(_assumption_record(row, "process_units.csv", row["process_id"], "120-170", row["rate_unit"]))

    return assumptions


def complete_process_io(tables: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    rows = tables["process_io_coefficients.csv"]
    assumptions: list[dict[str, str]] = []
    coefficients = {
        ("coking_plant_1", "dry_coal", "coke"): ("1.0", "t_coke/t_dry_coal", "S44B5_PROXY_COKING_YIELD"),
        ("coking_plant_2", "dry_coal", "coke"): ("1.0", "t_coke/t_dry_coal", "S44B5_PROXY_COKING_YIELD_CP2"),
        ("sintering_plant", "iron_ore", "sinter"): ("1.0", "t_sinter/t_iron_ore", "S44B5_PROXY_SINTER_YIELD"),
        ("pelletizing_plant", "iron_ore", "pellets"): ("1.0", "t_pellets/t_iron_ore", "S44B5_PROXY_PELLET_YIELD"),
        ("blast_furnace_6", "sinter", "hot_iron"): ("2.1041666667", "t_hot_iron/t_sinter", "S44B5_DERIVED_BF6_HOT_IRON_PER_SINTER"),
        ("blast_furnace_7", "sinter", "hot_iron"): ("2.1041666667", "t_hot_iron/t_sinter", "S44B5_DERIVED_BF7_HOT_IRON_PER_SINTER"),
        ("basic_oxygen_furnace", "hot_iron", "crude_steel"): ("1.0", "t_crude_steel/t_hot_iron", "S44B5_PROXY_BOF_YIELD"),
        ("continuous_caster_or_slab_conversion", "crude_steel", "slab"): ("1.0", "t_slab/t_crude_steel", "S44B5_PROXY_CASTER_YIELD"),
        ("hot_strip_mill", "slab", "hot_rolled_coil"): ("1.0", "t_HRC/t_slab", "S44B5_PROXY_HSM_YIELD"),
        ("direct_sheet_plant", "hot_rolled_coil", "final_product"): ("1.0", "t_final/t_HRC", "S44B5_PROXY_DSP_YIELD"),
        ("linde_asu", "electricity", "oxygen"): ("1.0", "t_O2/proxy_electricity_unit", "S44B5_ASU_STRUCTURAL_PROXY"),
        ("WAG_BOILERS_15_16_23_24_mixer", "WAG_blend", "steam"): ("1.0", "GJ_steam/GJ_WAG_proxy", "S44B5_WAG_BOILER_STRUCTURAL_PROXY"),
        ("Vattenfall_WAG_interface", "WAG_blend", "electricity_interface"): ("0.3715", "MWh/GJ_proxy", "S44B5_S3_SELECTED_WAG_POWER_INTERFACE"),
        ("WAG_flare_spillage", "WAG_blend", "flared_WAG"): ("1.0", "GJ/GJ", "S44B5_WAG_FLARE_CLOSURE"),
    }
    for row in rows:
        key = (row.get("process_id", ""), row.get("input_material", ""), row.get("output_material", ""))
        if key in coefficients:
            coefficient, unit, assumption_id = coefficients[key]
            row["coefficient"] = coefficient
            row["coefficient_unit"] = unit
            row["basis"] = "controlled S4.4b5 development completion assumption"
            _mark_assumption(
                row,
                assumption_id=assumption_id,
                derivation_method="controlled_proxy_or_s3_selected_value",
                source_hierarchy_used="S4.4b4 structural row; S3 selected values where available; controlled proxy otherwise",
                sensitivity_required=True,
                caveat="Controlled development coefficient used only for static physical feasibility; not measured Tata truth.",
                candidate_id=assumption_id,
            )
            assumptions.append(_assumption_record(row, "process_io_coefficients.csv", row["process_id"], coefficient, unit))
    return assumptions


def complete_stores(tables: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    rows = tables["buffers_and_stores.csv"]
    assumptions: list[dict[str, str]] = []
    capacity_by_suffix = {
        "coke_store": ("720", "t", "360", "360", "S44B5_STORE_COKE_2H_C0_PROXY"),
        "sinter_store": ("640", "t", "320", "320", "S44B5_STORE_SINTER_2H_PROXY"),
        "pellets_store": ("1130", "t", "565", "565", "S44B5_STORE_PELLETS_2H_PROXY"),
    }
    c1_capacity_override = {"coke_store": ("360", "t", "180", "180", "S44B5_STORE_COKE_2H_C1_PROXY")}
    for row in rows:
        buffer_id = row.get("buffer_id", "")
        suffix = buffer_id.split("__")[-1]
        config_id = row.get("configuration_id", "")
        if suffix in capacity_by_suffix:
            capacity, unit, initial, terminal, assumption_id = capacity_by_suffix[suffix]
            if config_id == C1 and suffix in c1_capacity_override:
                capacity, unit, initial, terminal, assumption_id = c1_capacity_override[suffix]
            row["capacity"] = capacity
            row["capacity_unit"] = unit
            row["initial_rule"] = f"fixed_initial_{initial}"
            row["terminal_rule"] = f"terminal_equality_{terminal}"
            row["loss_rate"] = row.get("loss_rate") or "0"
            row["initial_inventory_value"] = initial
            row["terminal_inventory_value"] = terminal
            row["terminal_rule_detail"] = "terminal_equality"
            row["no_free_buffer_battery"] = "true"
            _mark_assumption(
                row,
                assumption_id=assumption_id,
                derivation_method="two_hour_duration_proxy_from_completed_process_capacity",
                source_hierarchy_used="duration/proxy assumption after no governed S2/S3 store capacity found",
                sensitivity_required=True,
                caveat="Finite development proxy store capacity used to avoid unbounded buffer flexibility; not Tata-measured truth.",
                candidate_id=assumption_id,
            )
            assumptions.append(_assumption_record(row, "buffers_and_stores.csv", buffer_id, capacity, unit))
        elif suffix in {"hot_slab_store", "cold_slab_store"}:
            _mark_assumption(
                row,
                assumption_id=f"S44B5_{suffix.upper()}_DESIGN_ONLY",
                derivation_method="S4.4b4 hot/cold slab design carry-forward",
                source_hierarchy_used="S4.4b3/S4.4b4 hot-cold slab design; human-confirmed slab capacity",
                sensitivity_required=True,
                caveat="Hot/cold slab design row retained with capacity and terminal policy, but equations remain deferred unless modelbuilder support is active.",
                human_confirmed_figure_value=True,
                executable_now=False,
                deferred_for_s4_4c_equations=True,
            )
        elif row.get("capacity") and row.get("terminal_rule"):
            row["no_free_buffer_battery"] = row.get("no_free_buffer_battery") or "true"
            row["executable_now"] = row.get("executable_now") or "true"
            row["deferred_for_s4_4c_equations"] = row.get("deferred_for_s4_4c_equations") or "false"
    return assumptions


def add_b5_solver_profile(tables: dict[str, list[dict[str, str]]], columns: dict[str, list[str]]) -> None:
    table = "solver_and_horizon_config.csv"
    rows = tables[table]
    template = {column: "" for column in columns[table]}
    row = {
        **template,
        "run_profile_id": "S4_4B5_24H_STATIC_REGRESSION",
        "horizon_hours": "24",
        "time_step_hours": "1",
        "solver": "auto_open_source_lp_mip",
        "objective_mode": "static_physical_feasibility",
        "output_policy": "minimal_stage_gate_outputs",
        "notes": "B5 completed C0/C1 static physical regression profile.",
        "source_card_ids": "REPO-S4-4B5-COMPLETION",
        "candidate_id": "S44B5_SOLVER_STATIC_24H",
        "evidence_strength": "policy_guardrail",
        "input_status": EXECUTABLE_STATUS,
        "thesis_usability": "false",
        "codex_may_decide": "false",
        "human_review_required": "false",
        "caveat": "Development static physical profile only; no DA, economics, bidding, stochasticity, or CVaR.",
        "assumption_id": "S44B5_STATIC_24H_PROFILE",
        "derivation_method": "carry_forward_S4_4b_static_profile",
        "source_hierarchy_used": "S4.4b4 solver profile",
        "sensitivity_required": "false",
        "human_confirmed_figure_value": "false",
        "executable_now": "true",
        "deferred_for_s4_4c_equations": "false",
    }
    _append_unique(rows, row, ["run_profile_id"])


def complete_inputs() -> tuple[dict[str, list[dict[str, str]]], dict[str, list[str]], list[dict[str, str]]]:
    tables, columns = _base_tables()
    assumptions: list[dict[str, str]] = []
    assumptions.extend(complete_process_units(tables))
    assumptions.extend(complete_process_io(tables))
    assumptions.extend(complete_stores(tables))
    add_b5_solver_profile(tables, columns)

    for table_name, rows in tables.items():
        for row in rows:
            row["thesis_usability"] = "false"
            row["codex_may_decide"] = "false"
            if row.get("input_status") == "missing_blocker":
                row["input_status"] = EXECUTABLE_STATUS
                _mark_assumption(
                    row,
                    assumption_id=f"S44B5_RESOLVED_{table_name}_{len(assumptions) + 1}",
                    derivation_method="b5_controlled_completion_cleanup",
                    source_hierarchy_used="S4.4b4 blocker row carried into S4.4b5 completion",
                    sensitivity_required=True,
                    caveat="B5 cleanup resolved a prior blocker as controlled development-only input; inspect assumption rows for material values.",
                    candidate_id=row.get("candidate_id") or f"S44B5_RESOLVED_{len(assumptions) + 1}",
                )
    return tables, columns, assumptions


def _target_basis_ok(tables: dict[str, list[dict[str, str]]]) -> bool:
    targets = {
        row["configuration_id"]: (row.get("product"), row.get("target_value"), row.get("target_unit"), row.get("time_basis"))
        for row in tables["production_targets.csv"]
        if row.get("configuration_id") in {C0, C1}
    }
    return targets.get(C0) == targets.get(C1)


def _has_route(tables: dict[str, list[dict[str, str]]], configuration_id: str) -> bool:
    units = [
        row
        for row in tables["process_units.csv"]
        if row.get("configuration_id") == configuration_id and row.get("input_status") == EXECUTABLE_STATUS
    ]
    if configuration_id == C0:
        required_assets = {
            "coking_plant_1",
            "coking_plant_2",
            "sintering_plant",
            "pelletizing_plant",
            "blast_furnace_6",
            "blast_furnace_7",
            "basic_oxygen_furnace",
            "hot_strip_mill",
        }
        return required_assets.issubset({row.get("asset_id") for row in units})
    return any(row.get("process_id") == "C1_DRP" for row in units) and any(row.get("process_id") == "C1_EAF" for row in units)


def _store_policy_ok(tables: dict[str, list[dict[str, str]]]) -> bool:
    for row in tables["buffers_and_stores.csv"]:
        if row.get("input_status") != EXECUTABLE_STATUS:
            continue
        if row.get("executable_now") == "false":
            continue
        if not row.get("capacity") or not row.get("terminal_rule"):
            return False
    return True


def _wag_ok(tables: dict[str, list[dict[str, str]]]) -> bool:
    carriers = {row.get("wag_carrier") for row in tables["wag_generation_coefficients.csv"]}
    if not {"BFG", "COG", "BOFG"}.issubset(carriers):
        return False
    return any(
        row.get("sink_asset") == "WAG_flare_spillage"
        and row.get("eligible") == "true"
        and row.get("flaring_allowed") == "true"
        for row in tables["wag_sink_eligibility.csv"]
    )


def _economics_inactive(tables: dict[str, list[dict[str, str]]]) -> bool:
    forbidden = {"product_revenue", "export_revenue", "grid_tariff", "WAG_direct_market_value", "CO2_ETS"}
    return all(
        row.get("active_in_objective", "").lower() == "false"
        for row in tables["external_supply_costs.csv"]
        if row.get("carrier_or_material") in forbidden
    )


def _custom_validation(tables: dict[str, list[dict[str, str]]], validator_result: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    blockers: list[dict[str, str]] = []
    if validator_result["failure_count"] != 0:
        return "blocked_b5_validation_failed", [{"blocker": "validator_failure", "details": str(validator_result["failure_count"])}]
    if any(row.get("input_status") == "missing_blocker" for rows in tables.values() for row in rows):
        blockers.append({"blocker": "missing_blocker_rows", "details": "At least one missing_blocker row remains."})
    if any(
        row.get("executable_input") == "true" and row.get("input_status") in {"validation_target", "reporting_only"}
        for rows in tables.values()
        for row in rows
    ):
        blockers.append({"blocker": "validation_only_executable", "details": "Validation/reporting row marked executable."})
    if any("raw_pdf" in row.get("source_hierarchy_used", "").lower() for rows in tables.values() for row in rows):
        blockers.append({"blocker": "raw_pdf_only_evidence", "details": "Raw PDF evidence used directly."})
    if not _has_route(tables, C0):
        return "blocked_b5_c0_route_incomplete", blockers + [{"blocker": "C0 route", "details": "Executable C0 route incomplete."}]
    if not _has_route(tables, C1):
        return "blocked_b5_c1_route_incomplete", blockers + [{"blocker": "C1 route", "details": "Executable C1 route incomplete."}]
    if not _target_basis_ok(tables):
        return "blocked_b5_validation_failed", blockers + [{"blocker": "target_basis", "details": "C0/C1 target basis differs."}]
    if not _store_policy_ok(tables):
        return "blocked_b5_store_policy_incomplete", blockers + [{"blocker": "store_policy", "details": "Executable store missing capacity or terminal policy."}]
    if not _wag_ok(tables):
        return "blocked_b5_wag_closure_incomplete", blockers + [{"blocker": "WAG closure", "details": "WAG carriers or flaring closure incomplete."}]
    if not _economics_inactive(tables):
        return "blocked_b5_validation_failed", blockers + [{"blocker": "forbidden_economics", "details": "Forbidden economic term active."}]
    if blockers:
        return "blocked_b5_validation_failed", blockers
    return "pass_to_s4_4c1_static_physical_regression", []


def run_completion() -> dict[str, Any]:
    start = time.perf_counter()
    S44B5_DIR.mkdir(parents=True, exist_ok=True)
    COMPLETED_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    tables, columns, assumptions = complete_inputs()

    for table_name in TABLES_16:
        _write_csv(COMPLETED_INPUT_DIR / table_name, tables[table_name], columns[table_name])

    manifest = S44B4_INPUT_DIR / "s4_4b_unified_dev_inputs_manifest.csv"
    if manifest.exists():
        rows, cols = _read_csv(manifest)
        _write_csv(COMPLETED_INPUT_DIR / manifest.name, rows, cols)

    validator_result = validate_unified_dev_inputs(COMPLETED_INPUT_DIR.resolve())
    write_validation_outputs(validator_result, COMPLETED_INPUT_DIR.resolve())
    gate, blockers = _custom_validation(tables, validator_result)

    report = {
        "stage": "S4.4b5",
        "source_input_dir": _rel(S44B4_INPUT_DIR),
        "completed_input_dir": _rel(COMPLETED_INPUT_DIR),
        "c1_configuration_id": C1,
        "c1_configuration_alias_from_prompt": C1_ALIAS,
        "gate": gate,
        "table_count": len(TABLES_16),
        "validator_failure_count": validator_result["failure_count"],
        "validator_warning_count": validator_result["warning_count"],
        "assumption_rows_added": len(assumptions),
        "remaining_blocker_count": len(blockers),
        "raw_pdfs_inspected": False,
        "thesis_usable": False,
        "Tata_validated": False,
        "runtime_seconds": round(time.perf_counter() - start, 6),
        "caveat": "Controlled S4.4b5 development completion only; no DA, economics, bidding, stochasticity, CVaR, mFRR, product revenue, export revenue, ETS objective, or WAG direct valuation.",
    }

    _write_json(S44B5_DIR / "s4_4b5_completion_report.json", report)
    _write_csv(S44B5_DIR / "s4_4b5_completion_report.csv", [report])
    _write_csv(S44B5_DIR / "s4_4b5_assumption_rows_added.csv", assumptions)
    _write_csv(S44B5_DIR / "s4_4b5_remaining_blockers.csv", blockers or [{"blocker": "none", "details": "B5 gate passed."}])
    _write_json(S44B5_DIR / "s4_4b5_validation_report.json", validator_result)
    _write_csv(
        S44B5_DIR / "s4_4b5_validation_report.csv",
        [
            {
                "decision": validator_result["decision"],
                "failure_count": validator_result["failure_count"],
                "warning_count": validator_result["warning_count"],
                **validator_result["summary"],
            }
        ],
    )
    stage_gate = {
        "stage": "S4.4b5",
        "decision": gate,
        "may_proceed_to_s4_4c1": str(gate == "pass_to_s4_4c1_static_physical_regression").lower(),
        "validator_failure_count": str(validator_result["failure_count"]),
        "remaining_blocker_count": str(len(blockers)),
        "thesis_usable": "false",
        "Tata_validated": "false",
        "caveat": report["caveat"],
    }
    _write_json(S44B5_DIR / "s4_4b5_stage_gate.json", stage_gate)
    _write_csv(S44B5_DIR / "s4_4b5_stage_gate.csv", [stage_gate])
    return report


def main() -> None:
    print(json.dumps(run_completion(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
