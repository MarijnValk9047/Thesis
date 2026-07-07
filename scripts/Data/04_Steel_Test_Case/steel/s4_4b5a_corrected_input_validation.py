"""Phase 2 validation for S4.4b5a corrected development inputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .s4_4b_unified_input_validator import validate_unified_dev_inputs
from .s4_4b5a_asymmetric_correction import B5A_DIR, C0, C1, CORRECTED_INPUT_DIR, TABLES_16


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns: list[str] = []
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


def _load_tables() -> dict[str, list[dict[str, str]]]:
    return {name: _read_csv(CORRECTED_INPUT_DIR / name) for name in TABLES_16}


def _route_ok(tables: dict[str, list[dict[str, str]]], config_id: str) -> bool:
    units = [
        row for row in tables["process_units.csv"]
        if row.get("configuration_id") == config_id and row.get("input_status") == "development_only"
    ]
    if config_id == C0:
        required = {
            "coking_plant_1",
            "coking_plant_2",
            "sintering_plant",
            "blast_furnace_6",
            "blast_furnace_7",
            "basic_oxygen_furnace",
            "hot_strip_mill",
        }
        return required.issubset({row.get("asset_id") for row in units})
    return {row.get("process_id") for row in units}.issuperset({"C1_DRP", "C1_EAF"})


def _store_ok(tables: dict[str, list[dict[str, str]]]) -> bool:
    for row in tables["buffers_and_stores.csv"]:
        if row.get("input_status") != "development_only":
            continue
        if row.get("executable_now") == "false":
            continue
        if not row.get("capacity") or not row.get("terminal_rule"):
            return False
    return True


def _cp_structure_ok(tables: dict[str, list[dict[str, str]]]) -> bool:
    io = tables["process_io_coefficients.csv"]
    cp1_mix = any(row.get("process_id") == "coking_plant_1" and row.get("input_material") == "wag_cok1_mix" for row in io)
    cp2_cog = any(row.get("process_id") == "coking_plant_2" and row.get("input_material") == "COG" for row in io)
    cp2_wag = any(row.get("process_id") == "coking_plant_2" and row.get("input_material") in {"wag_cok1_mix", "WAG_blend", "wag_blend"} for row in io)
    return cp1_mix and cp2_cog and not cp2_wag


def _bf_structure_ok(tables: dict[str, list[dict[str, str]]]) -> bool:
    units = tables["process_units.csv"]
    bf6 = next(row for row in units if row.get("configuration_id") == C0 and row.get("asset_id") == "blast_furnace_6")
    bf7 = next(row for row in units if row.get("configuration_id") == C0 and row.get("asset_id") == "blast_furnace_7")
    return bf7.get("derivation_method") == "emissions_share_scaled_capacity_proxy" and bf7.get("min_rate") != bf6.get("min_rate")


def _wag_ok(tables: dict[str, list[dict[str, str]]]) -> bool:
    carriers = {row.get("wag_carrier") for row in tables["wag_generation_coefficients.csv"]}
    if not {"BFG", "COG", "BOFG"}.issubset(carriers):
        return False
    costs = tables["external_supply_costs.csv"]
    return all(
        row.get("active_in_objective") == "false"
        for row in costs
        if row.get("carrier_or_material") in {"WAG_direct_market_value", "product_revenue", "export_revenue", "CO2_ETS", "grid_tariff"}
    )


def run_phase2_validation() -> dict[str, Any]:
    tables = _load_tables()
    validation = validate_unified_dev_inputs(CORRECTED_INPUT_DIR.resolve())
    blockers: list[dict[str, str]] = []
    if validation["failure_count"] != 0:
        decision = "blocked_validation_failed"
        blockers.append({"blocker": "validator", "details": str(validation["failure_count"])})
    elif not _route_ok(tables, C0):
        decision = "blocked_c0_route_incomplete"
    elif not _route_ok(tables, C1):
        decision = "blocked_c1_route_incomplete"
    elif not _cp_structure_ok(tables):
        decision = "blocked_cp1_cp2_wag_structure_invalid"
    elif not _bf_structure_ok(tables):
        decision = "blocked_bf6_bf7_capacity_structure_invalid"
    elif not _store_ok(tables):
        decision = "blocked_store_policy_incomplete"
    elif not _wag_ok(tables):
        decision = "blocked_validation_failed"
        blockers.append({"blocker": "WAG/economic policy", "details": "WAG separation or forbidden economics invalid."})
    elif any(row.get("input_status") == "missing_blocker" for rows in tables.values() for row in rows):
        decision = "blocked_validation_failed"
        blockers.append({"blocker": "missing_blocker", "details": "Missing blocker rows remain."})
    else:
        decision = "pass_to_phase3_24h_rerun"

    report = {
        "stage": "S4.4b5a_phase2_validation",
        "decision": decision,
        "validator_failure_count": validation["failure_count"],
        "validator_warning_count": validation["warning_count"],
        "missing_blocker_rows": validation["summary"].get("missing_blocker_rows", ""),
        "c0_route_ok": str(_route_ok(tables, C0)).lower(),
        "c1_route_ok": str(_route_ok(tables, C1)).lower(),
        "cp1_cp2_wag_structure_ok": str(_cp_structure_ok(tables)).lower(),
        "bf6_bf7_capacity_structure_ok": str(_bf_structure_ok(tables)).lower(),
        "store_policy_ok": str(_store_ok(tables)).lower(),
        "wag_policy_ok": str(_wag_ok(tables)).lower(),
        "thesis_usable": "false",
        "Tata_validated": "false",
        "caveat": "Corrected development inputs only; validation confirms structure, not Tata truth.",
    }
    _write_json(B5A_DIR / "s4_4b5a_phase2_validation_gate.json", report)
    _write_csv(B5A_DIR / "s4_4b5a_phase2_validation_gate.csv", [report])
    if blockers:
        _write_csv(B5A_DIR / "s4_4b5a_phase2_blockers.csv", blockers)
    return report


def main() -> None:
    print(json.dumps(run_phase2_validation(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
