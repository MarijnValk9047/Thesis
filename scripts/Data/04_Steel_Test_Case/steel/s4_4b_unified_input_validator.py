"""Validate S4.4b unified C0/C1 development input tables.

This module checks the input contract only. It does not build or solve an
optimisation model.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
INPUT_DIR = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/s4_4b_unified_dev_inputs"
S44A_DIR = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/s4_4a_unified_c0_c1_model_contract"
S44A_MANIFEST_PATH = S44A_DIR / "s4_4a_required_input_tables_manifest.csv"
S44A_BLOCKERS_PATH = S44A_DIR / "s4_4a_missing_inputs_and_blockers.csv"

GOVERNANCE_COLUMNS = [
    "source_card_ids",
    "candidate_id",
    "evidence_strength",
    "input_status",
    "thesis_usability",
    "codex_may_decide",
    "human_review_required",
    "caveat",
]

PRIMARY_KEYS = {
    "configuration_assets.csv": ["configuration_id", "asset_id"],
    "process_units.csv": ["configuration_id", "process_id"],
    "process_io_coefficients.csv": ["process_id", "input_material", "output_material"],
    "process_energy_intensities.csv": ["process_id", "carrier", "direction"],
    "process_emission_factors.csv": ["process_id", "emission_scope"],
    "buffers_and_stores.csv": ["configuration_id", "buffer_id"],
    "wag_generation_coefficients.csv": ["configuration_id", "process_id", "wag_carrier"],
    "wag_sink_eligibility.csv": ["configuration_id", "wag_carrier", "sink_asset"],
    "utility_demands.csv": ["configuration_id", "asset_id", "utility_carrier"],
    "utility_conversion_assets.csv": ["asset_id", "input_carrier", "output_carrier"],
    "external_supply_costs.csv": ["carrier_or_material", "time_basis"],
    "market_price_inputs.csv": ["market", "window_start", "window_end"],
    "production_targets.csv": ["configuration_id", "target_id"],
    "validation_anchors.csv": ["configuration_id", "metric", "time_basis"],
    "policy_modes.csv": ["policy_id", "policy_mode"],
    "solver_and_horizon_config.csv": ["run_profile_id"],
}

REQUIRED_CONFIGURATIONS = {
    "C0_current_BF_BOF_reference",
    "C1_phase1_BF_BOF_plus_DRP_EAF",
}

REQUIRED_POLICY_MODES = {
    "price_naive_static_or_cost_smoothed",
    "deterministic_da_price_taking",
}

REAL_DAM_PRICE_FILE = "data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv"
FORBIDDEN_COST_ROWS = {
    "product_revenue",
    "export_revenue",
    "grid_tariff",
    "WAG_direct_market_value",
}


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    status: str
    detail: str


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _load_required_tables() -> dict[str, list[str]]:
    rows = _read_csv(S44A_MANIFEST_PATH)
    required: dict[str, list[str]] = {}
    for row in rows:
        required[row["table_name"]] = [
            column for column in row["required_columns"].split(";") if column
        ]
    return required


def _has_duplicate_key(rows: list[dict[str, str]], key_columns: list[str]) -> bool:
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key = tuple(row.get(column, "") for column in key_columns)
        if key in seen:
            return True
        seen.add(key)
    return False


def _boolish_false(value: str) -> bool:
    return value.strip().lower() in {"false", "no", "0", "inactive"}


def _boolish_true(value: str) -> bool:
    return value.strip().lower() in {"true", "yes", "1", "active"}


def _check_tables_exist(input_dir: Path, required_tables: dict[str, list[str]]) -> list[CheckResult]:
    results = []
    missing = [table for table in required_tables if not (input_dir / table).exists()]
    status = "pass" if not missing else "fail"
    detail = "all required tables exist" if not missing else f"missing tables: {';'.join(missing)}"
    results.append(CheckResult("required_tables_exist", status, detail))
    return results


def _check_table_columns(
    input_dir: Path, required_tables: dict[str, list[str]]
) -> tuple[list[CheckResult], dict[str, list[dict[str, str]]]]:
    results = []
    table_rows: dict[str, list[dict[str, str]]] = {}
    for table_name, required_columns in required_tables.items():
        path = input_dir / table_name
        if not path.exists():
            continue
        rows = _read_csv(path)
        table_rows[table_name] = rows
        columns = set(rows[0].keys() if rows else _read_header(path))
        missing_columns = [
            column
            for column in [*required_columns, *GOVERNANCE_COLUMNS]
            if column not in columns
        ]
        status = "pass" if not missing_columns else "fail"
        detail = "columns complete" if not missing_columns else f"missing columns: {';'.join(missing_columns)}"
        results.append(CheckResult(f"{table_name}:columns", status, detail))
    return results, table_rows


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        return next(reader)


def _check_duplicate_keys(table_rows: dict[str, list[dict[str, str]]]) -> list[CheckResult]:
    results = []
    for table_name, rows in table_rows.items():
        key_columns = PRIMARY_KEYS[table_name]
        duplicate = _has_duplicate_key(rows, key_columns)
        status = "fail" if duplicate else "pass"
        detail = "duplicate primary key found" if duplicate else "primary keys unique"
        results.append(CheckResult(f"{table_name}:primary_keys", status, detail))
    return results


def _check_core_contract(table_rows: dict[str, list[dict[str, str]]], input_dir: Path) -> list[CheckResult]:
    results: list[CheckResult] = []

    assets = table_rows.get("configuration_assets.csv", [])
    active_configs = {
        row["configuration_id"]
        for row in assets
        if _boolish_true(row.get("active", ""))
    }
    missing_asset_configs = sorted(REQUIRED_CONFIGURATIONS - active_configs)
    results.append(
        CheckResult(
            "active_configurations_have_assets",
            "pass" if not missing_asset_configs else "fail",
            "both configurations have active assets"
            if not missing_asset_configs
            else f"missing active assets for: {';'.join(missing_asset_configs)}",
        )
    )

    targets = table_rows.get("production_targets.csv", [])
    target_configs = {
        row["configuration_id"]
        for row in targets
        if _boolish_true(row.get("hard_target", ""))
    }
    missing_target_configs = sorted(REQUIRED_CONFIGURATIONS - target_configs)
    results.append(
        CheckResult(
            "production_targets_present",
            "pass" if not missing_target_configs else "fail",
            "both configurations have hard production target rows"
            if not missing_target_configs
            else f"missing targets for: {';'.join(missing_target_configs)}",
        )
    )

    policies = table_rows.get("policy_modes.csv", [])
    policy_modes = {row["policy_mode"] for row in policies}
    missing_policies = sorted(REQUIRED_POLICY_MODES - policy_modes)
    results.append(
        CheckResult(
            "required_policy_modes_present",
            "pass" if not missing_policies else "fail",
            "required policy modes present"
            if not missing_policies
            else f"missing policies: {';'.join(missing_policies)}",
        )
    )

    price_rows = table_rows.get("market_price_inputs.csv", [])
    matching_price_rows = [
        row for row in price_rows if row.get("price_file") == REAL_DAM_PRICE_FILE
    ]
    results.append(
        CheckResult(
            "real_dam_price_file_configured",
            "pass" if matching_price_rows else "fail",
            REAL_DAM_PRICE_FILE if matching_price_rows else "real DAM price file not configured",
        )
    )

    costs = table_rows.get("external_supply_costs.csv", [])
    active_forbidden = [
        row["carrier_or_material"]
        for row in costs
        if row.get("carrier_or_material") in FORBIDDEN_COST_ROWS
        and not _boolish_false(row.get("active_in_objective", ""))
    ]
    co2_active = [
        row["carrier_or_material"]
        for row in costs
        if row.get("carrier_or_material") == "CO2_ETS"
        and not _boolish_false(row.get("active_in_objective", ""))
    ]
    forbidden_failures = [*active_forbidden, *co2_active]
    results.append(
        CheckResult(
            "forbidden_terms_inactive",
            "pass" if not forbidden_failures else "fail",
            "product revenue export revenue grid tariffs WAG valuation and CO2 objective inactive"
            if not forbidden_failures
            else f"active forbidden terms: {';'.join(forbidden_failures)}",
        )
    )

    validation_rows = table_rows.get("validation_anchors.csv", [])
    executable_anchor_rows = [
        row
        for row in validation_rows
        if row.get("input_status") not in {"validation_target", "reporting_only"}
    ]
    results.append(
        CheckResult(
            "validation_anchors_not_executable_inputs",
            "pass" if not executable_anchor_rows else "fail",
            "validation anchors remain validation or reporting rows"
            if not executable_anchor_rows
            else f"bad validation anchor rows: {len(executable_anchor_rows)}",
        )
    )

    manifest_path = input_dir / "s4_4b_unified_dev_inputs_manifest.csv"
    manifest_rows = _read_csv(manifest_path) if manifest_path.exists() else []
    blocker_ids = {row["blocker_id"] for row in _read_csv(S44A_BLOCKERS_PATH)}
    preserved_ids: set[str] = set()
    for row in manifest_rows:
        for value in row.get("related_s4_4a_blockers", "").split(";"):
            if value:
                preserved_ids.add(value)
    missing_blocker_ids = sorted(blocker_ids - preserved_ids)
    results.append(
        CheckResult(
            "s4_4a_blockers_preserved",
            "pass" if not missing_blocker_ids else "fail",
            f"preserved blocker ids: {len(preserved_ids)}"
            if not missing_blocker_ids
            else f"missing blocker ids: {';'.join(missing_blocker_ids)}",
        )
    )

    return results


def _summarize(table_rows: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    all_rows = [row for rows in table_rows.values() for row in rows]
    status_counts: dict[str, int] = {}
    for row in all_rows:
        status = row.get("input_status", "missing_status")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "table_count": len(table_rows),
        "total_rows": len(all_rows),
        "input_status_counts": status_counts,
        "missing_blocker_rows": status_counts.get("missing_blocker", 0),
        "deferred_rows": status_counts.get("deferred", 0),
        "validation_target_rows": status_counts.get("validation_target", 0),
        "forbidden_inactive_rows": status_counts.get("forbidden_inactive", 0),
    }


def validate_unified_dev_inputs(input_dir: Path = INPUT_DIR) -> dict[str, Any]:
    required_tables = _load_required_tables()
    checks: list[CheckResult] = []
    checks.extend(_check_tables_exist(input_dir, required_tables))
    column_checks, table_rows = _check_table_columns(input_dir, required_tables)
    checks.extend(column_checks)
    checks.extend(_check_duplicate_keys(table_rows))
    checks.extend(_check_core_contract(table_rows, input_dir))

    failures = [check for check in checks if check.status == "fail"]
    warnings = [check for check in checks if check.status == "warning"]
    summary = _summarize(table_rows)
    decision = "pass_to_s4_4c_with_limitations" if not failures else "blocked"

    return {
        "stage": "S4.4b",
        "validator": "s4_4b_unified_input_validator",
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_directory": str(input_dir.relative_to(REPO_ROOT)),
        "decision": decision,
        "may_proceed_to_s4_4c": not failures,
        "thesis_usable": False,
        "model_behaviour_changed": False,
        "summary": summary,
        "checks": [check.__dict__ for check in checks],
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "caveat": "Structural input validation only. Development-only and missing-blocker rows are intentionally preserved and are not thesis-approved executable inputs.",
}


def write_validation_outputs(result: dict[str, Any], input_dir: Path = INPUT_DIR) -> None:
    report_json = input_dir / "s4_4b_input_validation_report.json"
    report_csv = input_dir / "s4_4b_input_validation_report.csv"
    gate_json = input_dir / "s4_4b_stage_gate.json"
    gate_csv = input_dir / "s4_4b_stage_gate.csv"

    report_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    _write_csv(
        report_csv,
        result["checks"],
        ["check_id", "status", "detail"],
    )

    gate = {
        "stage": result["stage"],
        "decision": result["decision"],
        "may_proceed_to_s4_4c": result["may_proceed_to_s4_4c"],
        "model_behaviour_changed": result["model_behaviour_changed"],
        "thesis_usable": result["thesis_usable"],
        "table_count": result["summary"]["table_count"],
        "total_rows": result["summary"]["total_rows"],
        "missing_blocker_rows": result["summary"]["missing_blocker_rows"],
        "deferred_rows": result["summary"]["deferred_rows"],
        "validation_target_rows": result["summary"]["validation_target_rows"],
        "failure_count": result["failure_count"],
        "warning_count": result["warning_count"],
        "caveat": result["caveat"],
    }
    gate_json.write_text(json.dumps(gate, indent=2), encoding="utf-8")
    _write_csv(gate_csv, [gate], list(gate))


def main() -> int:
    result = validate_unified_dev_inputs()
    write_validation_outputs(result)
    print(
        json.dumps(
            {
                "decision": result["decision"],
                "may_proceed_to_s4_4c": result["may_proceed_to_s4_4c"],
                "failure_count": result["failure_count"],
                "warning_count": result["warning_count"],
                "summary": result["summary"],
            },
            indent=2,
        )
    )
    return 0 if result["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
