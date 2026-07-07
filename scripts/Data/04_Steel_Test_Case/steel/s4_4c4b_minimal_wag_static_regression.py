"""S4.4c4b minimal executable WAG/steam/gas static regression."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from .s4_4b_unified_input_validator import validate_unified_dev_inputs
from .s4_4b5a_asymmetric_correction import CORRECTED_INPUT_DIR
from .s4_4c_unified_physical_modelbuilder import (
    BOILER_TOTAL_PLACEHOLDER_MWH_H,
    BOILER_WAG_PLACEHOLDER_CAP_MWH_H,
    ETA_BOILER_STEAM,
    KGF_UNDERFIRING_MWH_PER_T_COKE,
    SELECTED_WAG_LHV_MJ_PER_NM3,
    SINTER_COG_MWH_PER_T_SINTER,
    S44CModelBuilderError,
    _build_c0_inputs,
    _load_tables,
    run_s44c_unified_physical_regression,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
S4_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4"
C4_AUDIT_DIR = S4_ROOT / "s4_4c4_wag_steam_gas_readiness_audit"
C4B_IMPL_DIR = S4_ROOT / "s4_4c4b_minimal_wag_steam_gas_implementation"
C4B_24H_DIR = S4_ROOT / "s4_4c4b_24h_wag_static_physical_regression"
C4B_168H_DIR = S4_ROOT / "s4_4c4b_168h_wag_static_physical_regression"
C0 = "C0_current_BF_BOF_reference"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
TOLERANCE = 1e-6


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _folder_stats(path: Path) -> tuple[int, int]:
    files = [candidate for candidate in path.rglob("*") if candidate.is_file()]
    return len(files), sum(candidate.stat().st_size for candidate in files)


def _safe_float(value_in: Any, default: float = 0.0) -> float:
    try:
        if value_in in {"", None}:
            return default
        return float(value_in)
    except (TypeError, ValueError):
        return default


def _stage_gate_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _phase1_equation_rows() -> list[dict[str, Any]]:
    return [
        {
            "equation_id": "BFG_balance",
            "configuration_scope": "C0 active; C1 zero in current DRP/EAF builder",
            "mathematical_form": "BFG_prod_BF6 + BFG_prod_BF7 = BFG_to_KGF1 + BFG_to_BoilerFuel + BFG_flared",
            "implemented_status": "active",
            "source_or_policy": "S4.4c4 audit; abstraction A_WAG_PROCESS_FIRST_001",
            "caveat": "C1 retained BF-BOF WAG route is not represented in the current C1 DRP/EAF builder.",
        },
        {
            "equation_id": "COG_balance",
            "configuration_scope": "C0 active; C1 zero in current DRP/EAF builder",
            "mathematical_form": "COG_prod_KGF1 + COG_prod_KGF2 = COG_to_KGF1 + COG_to_KGF2 + COG_to_Sinter + COG_to_BoilerFuel + COG_flared",
            "implemented_status": "active",
            "source_or_policy": "S4.4c4 audit; abstraction A_WAG_DIRECT_PROCESS_SINKS_001",
            "caveat": "KGF2 activity remains zero in the fixed C0 fallback schedule if not needed by material balance.",
        },
        {
            "equation_id": "BOFG_balance",
            "configuration_scope": "C0 active; C1 zero in current DRP/EAF builder",
            "mathematical_form": "BOFG_prod_BOF = BOFG_flared",
            "implemented_status": "active",
            "source_or_policy": "BOFG-to-boiler deferred by policy",
            "caveat": "BOFG-to-boiler is inactive in base.",
        },
        {
            "equation_id": "KGF1_underfiring",
            "configuration_scope": "C0 active",
            "mathematical_form": "KGF1_fuel = 0.9722 MWh/t coke * KGF1_activity, split 50% BFG and 50% COG",
            "implemented_status": "active",
            "source_or_policy": "User-selected S4.4c4b policy",
            "caveat": "Development-only fixed split; not price-responsive and not Tata-measured.",
        },
        {
            "equation_id": "KGF2_underfiring",
            "configuration_scope": "C0 active only",
            "mathematical_form": "KGF2_COG = 0.9722 MWh/t coke * KGF2_activity",
            "implemented_status": "active",
            "source_or_policy": "User-selected S4.4c4b policy",
            "caveat": "Pure COG; inactive in C1.",
        },
        {
            "equation_id": "Sinter_COG",
            "configuration_scope": "C0 active",
            "mathematical_form": "COG_to_Sinter = 0.02778 MWh/t sinter * Sinter_activity",
            "implemented_status": "active",
            "source_or_policy": "User-selected S4.4c4b policy",
            "caveat": "Development assumption from abstraction plan; sensitivity required.",
        },
        {
            "equation_id": "aggregated_boiler_placeholder",
            "configuration_scope": "C0 active; C1 reporting placeholder",
            "mathematical_form": "BFG_to_BoilerFuel + COG_to_BoilerFuel <= 95.13 MWh/h; total boiler fuel = 190.26 MWh/h with NG filling the balance",
            "implemented_status": "active_placeholder",
            "source_or_policy": "S3.3j 6 PJ/y development utility placeholder",
            "caveat": "Annual allocation context converted to flat hourly placeholder; not measured hourly Tata demand.",
        },
        {
            "equation_id": "Vattenfall_interface",
            "configuration_scope": "C0/C1",
            "mathematical_form": "Vattenfall dispatch = 0",
            "implemented_status": "inactive_reporting_only",
            "source_or_policy": "S4.4c4 policy recommendation",
            "caveat": "No electricity offset, no revenue, no NG-to-Vattenfall.",
        },
    ]


def _phase1_parameter_rows() -> list[dict[str, Any]]:
    tables = _load_tables(CORRECTED_INPUT_DIR)
    c0 = _build_c0_inputs(tables)
    return [
        {
            "parameter": "alpha_BFG_BF",
            "value_used": round(c0.bfg_nm3_per_t_hot_iron, 6),
            "converted_mwh_lhv_per_t": round(c0.bfg_mwh_per_t_hot_iron, 9),
            "unit": "Nm3/t_hot_metal",
            "source": "existing S4.4b5a migrated WAG coefficient",
            "development_placeholder": "false",
            "thesis_usability": "false",
            "caveat": "Existing migrated coefficient overrides abstraction default.",
        },
        {
            "parameter": "alpha_COG_KGF",
            "value_used": round(c0.cog_m3_per_t_dry_coal, 6),
            "converted_mwh_lhv_per_t": round(c0.cog_mwh_per_t_coke, 9),
            "unit": "m3/t_dry_coal_or_model_coke_proxy",
            "source": "existing S4.4b5a migrated WAG coefficient",
            "development_placeholder": "false",
            "thesis_usability": "false",
            "caveat": "Current C0 model uses a 1:1 dry-coal-to-coke proxy.",
        },
        {
            "parameter": "alpha_BOFG_BOF",
            "value_used": round(c0.bofg_nm3_per_t_liquid_steel, 6),
            "converted_mwh_lhv_per_t": round(c0.bofg_mwh_per_t_liquid_steel, 9),
            "unit": "Nm3/t_liquid_steel",
            "source": "existing S4.4b5a migrated WAG coefficient",
            "development_placeholder": "false",
            "thesis_usability": "false",
            "caveat": "Suppressed-combustion BOFG proxy.",
        },
        {
            "parameter": "alpha_fuel_KGF1",
            "value_used": round(KGF_UNDERFIRING_MWH_PER_T_COKE, 9),
            "converted_mwh_lhv_per_t": round(KGF_UNDERFIRING_MWH_PER_T_COKE, 9),
            "unit": "MWh_LHV/t_coke",
            "source": "S4.4c4b user-selected development policy",
            "development_placeholder": "true",
            "thesis_usability": "false",
            "caveat": "Fixed 50/50 BFG/COG energy split.",
        },
        {
            "parameter": "alpha_fuel_KGF2",
            "value_used": round(KGF_UNDERFIRING_MWH_PER_T_COKE, 9),
            "converted_mwh_lhv_per_t": round(KGF_UNDERFIRING_MWH_PER_T_COKE, 9),
            "unit": "MWh_LHV/t_coke",
            "source": "S4.4c4b user-selected development policy",
            "development_placeholder": "true",
            "thesis_usability": "false",
            "caveat": "Pure COG, C0 only.",
        },
        {
            "parameter": "alpha_fuel_Sinter_COG",
            "value_used": round(SINTER_COG_MWH_PER_T_SINTER, 9),
            "converted_mwh_lhv_per_t": round(SINTER_COG_MWH_PER_T_SINTER, 9),
            "unit": "MWh_LHV/t_sinter",
            "source": "STEEL_WAG_STEAM_GAS_NETWORK_ABSTRACTION.md",
            "development_placeholder": "true",
            "thesis_usability": "false",
            "caveat": "Sensitivity required.",
        },
        {
            "parameter": "boiler_wag_cap",
            "value_used": round(BOILER_WAG_PLACEHOLDER_CAP_MWH_H, 6),
            "converted_mwh_lhv_per_t": "",
            "unit": "MWh_LHV/h",
            "source": "3 PJ/y WAG placeholder converted to hourly average",
            "development_placeholder": "true",
            "thesis_usability": "false",
            "caveat": "Flat hourly placeholder, not measured hourly demand.",
        },
        {
            "parameter": "boiler_total_placeholder",
            "value_used": round(BOILER_TOTAL_PLACEHOLDER_MWH_H, 6),
            "converted_mwh_lhv_per_t": "",
            "unit": "MWh_LHV/h",
            "source": "6 PJ/y aggregate placeholder converted to hourly average",
            "development_placeholder": "true",
            "thesis_usability": "false",
            "caveat": "NG fills boiler demand not served by WAG up to the WAG placeholder cap.",
        },
        {
            "parameter": "eta_boiler_steam",
            "value_used": ETA_BOILER_STEAM,
            "converted_mwh_lhv_per_t": "",
            "unit": "MWh_steam/MWh_LHV",
            "source": "abstraction development assumption",
            "development_placeholder": "true",
            "thesis_usability": "false",
            "caveat": "Generic boiler proxy.",
        },
        {
            "parameter": "selected_LHV_values",
            "value_used": json.dumps(SELECTED_WAG_LHV_MJ_PER_NM3, sort_keys=True),
            "converted_mwh_lhv_per_t": "",
            "unit": "MJ/Nm3",
            "source": "S3 selected WAG development inputs",
            "development_placeholder": "false",
            "thesis_usability": "false",
            "caveat": "Used only to convert migrated volumetric WAG coefficients to MWh_LHV.",
        },
    ]


def _phase1_policy_rows() -> list[dict[str, Any]]:
    return [
        {"policy": "BOFG_to_boiler", "applied_decision": "inactive_deferred", "caveat": "Base flares BOFG unless later policy activates boiler use."},
        {"policy": "Vattenfall_interface", "applied_decision": "inactive_reporting_only", "caveat": "No physical dispatch, no electricity offset, no revenue."},
        {"policy": "boiler_steam_placeholder", "applied_decision": "6_PJy_flat_hourly_development_placeholder", "caveat": "Not measured Tata hourly demand."},
        {"policy": "KGF1_split", "applied_decision": "fixed_50_50_BFG_COG_energy_split", "caveat": "No price-responsive split."},
        {"policy": "KGF2", "applied_decision": "pure_COG_C0_only", "caveat": "Inactive in C1."},
        {"policy": "Sinter_COG", "applied_decision": "fixed_process_linked_development_assumption", "caveat": "Sensitivity required."},
        {"policy": "HSM_PEFA_fuel", "applied_decision": "not_implemented_coefficients_missing", "caveat": "Eligibility only."},
        {"policy": "WAG_steam_storage", "applied_decision": "inactive", "caveat": "No WAG or steam stores at hourly resolution."},
        {"policy": "flaring", "applied_decision": "carrier_specific_zero_economic_value", "caveat": "Tiny non-economic objective tie-breaker labels allocation only."},
        {"policy": "economics", "applied_decision": "inactive", "caveat": "No DA, revenue, ETS, grid tariff, bidding, or WAG valuation."},
    ]


def run_phase1() -> dict[str, Any]:
    C4B_IMPL_DIR.mkdir(parents=True, exist_ok=True)
    audit_gate = _stage_gate_json(C4_AUDIT_DIR / "s4_4c4_stage_gate.json")
    validation = validate_unified_dev_inputs(CORRECTED_INPUT_DIR.resolve())
    decision = "pass_to_phase2_24h_wag_rerun"
    if audit_gate.get("decision") not in {
        "ready_for_s4_4c4b_with_policy_decisions",
        "ready_for_s4_4c4b_minimal_wag_implementation",
    }:
        decision = "blocked_policy_conflict"
    elif validation["failure_count"] != 0:
        decision = "blocked_input_contract_mismatch"

    equation_rows = _phase1_equation_rows()
    parameter_rows = _phase1_parameter_rows()
    policy_rows = _phase1_policy_rows()
    gate = {
        "stage": "S4.4c4b_phase1",
        "decision": decision,
        "audit_gate": audit_gate.get("decision", "missing"),
        "validator_failure_count": validation["failure_count"],
        "model_equations_modified": True,
        "raw_pdfs_inspected": False,
        "vag_or_wag_storage_active": False,
        "steam_storage_active": False,
        "vattenfall_dispatch_active": False,
        "direct_wag_market_valuation_active": False,
        "thesis_usable": False,
        "Tata_validated": False,
        "caveat": "Development-only minimal WAG layer; not a Tata gas-network digital twin.",
    }
    _write_csv(C4B_IMPL_DIR / "s4_4c4b_implemented_wag_equations.csv", equation_rows)
    _write_csv(C4B_IMPL_DIR / "s4_4c4b_parameter_values_used.csv", parameter_rows)
    _write_csv(C4B_IMPL_DIR / "s4_4c4b_policy_decisions_applied.csv", policy_rows)
    _write_json(C4B_IMPL_DIR / "s4_4c4b_stage_gate_phase1.json", gate)
    _write_csv(C4B_IMPL_DIR / "s4_4c4b_stage_gate_phase1.csv", [gate])
    return gate


def _audit_map(audits: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["configuration_id"]: row for row in audits}


def _zero_residual(audit: dict[str, Any]) -> bool:
    return abs(_safe_float(audit.get("final_product_residual_t"), 1.0)) <= TOLERANCE


def _max_balance_residual(hourly_rows: list[dict[str, Any]]) -> float:
    max_abs = 0.0
    for row in hourly_rows:
        for field in ["BFG_balance_residual_mwh", "COG_balance_residual_mwh", "BOFG_balance_residual_mwh"]:
            max_abs = max(max_abs, abs(_safe_float(row.get(field))))
    return max_abs


def _report_rows(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = [
        "configuration_id",
        "build_status",
        "solver_name",
        "solver_status",
        "termination_condition",
        "objective_value",
        "final_product_target_t",
        "final_product_fulfilled_t",
        "final_product_residual_t",
        "WAG_generated",
        "WAG_used",
        "WAG_flared",
        "natural_gas_nm3",
        "natural_gas_boiler_mwh",
        "steam_mwh",
        "variable_count",
        "binary_count",
        "constraint_count",
        "caveat",
    ]
    return [{field: row.get(field, "") for field in fields} for row in audits]


def _wag_by_carrier(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for config_id in [C0, C1]:
        rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        for carrier in ["BFG", "COG", "BOFG"]:
            generated = sum(_safe_float(row.get(f"{carrier}_generated_mwh")) for row in rows)
            if carrier == "BFG":
                used = sum(_safe_float(row.get("BFG_to_KGF1_mwh")) + _safe_float(row.get("BFG_to_boiler_mwh")) for row in rows)
            elif carrier == "COG":
                used = sum(
                    _safe_float(row.get("COG_to_KGF1_mwh"))
                    + _safe_float(row.get("COG_to_KGF2_mwh"))
                    + _safe_float(row.get("COG_to_sinter_mwh"))
                    + _safe_float(row.get("COG_to_boiler_mwh"))
                    for row in rows
                )
            else:
                used = sum(_safe_float(row.get("BOFG_to_boiler_mwh")) for row in rows)
            flared = sum(_safe_float(row.get(f"{carrier}_flared_mwh")) for row in rows)
            residual_field = f"{carrier}_balance_residual_mwh"
            max_residual = max((abs(_safe_float(row.get(residual_field))) for row in rows), default=0.0)
            out.append(
                {
                    "configuration_id": config_id,
                    "carrier": carrier,
                    "generated_mwh": round(generated, 6),
                    "used_mwh": round(used, 6),
                    "flared_mwh": round(flared, 6),
                    "flare_share": round(flared / generated, 6) if generated else 0.0,
                    "max_abs_balance_residual_mwh": round(max_residual, 9),
                    "caveat": "C1 retained BF-BOF WAG route is not represented in current DRP/EAF builder." if config_id == C1 else "",
                }
            )
    return out


def _wag_by_sink(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sink_fields = [
        ("KGF1", "BFG", "BFG_to_KGF1_mwh"),
        ("KGF1", "COG", "COG_to_KGF1_mwh"),
        ("KGF2", "COG", "COG_to_KGF2_mwh"),
        ("Sinter", "COG", "COG_to_sinter_mwh"),
        ("BoilerFuel", "BFG", "BFG_to_boiler_mwh"),
        ("BoilerFuel", "COG", "COG_to_boiler_mwh"),
        ("BoilerFuel", "BOFG", "BOFG_to_boiler_mwh"),
        ("Flare", "BFG", "BFG_flared_mwh"),
        ("Flare", "COG", "COG_flared_mwh"),
        ("Flare", "BOFG", "BOFG_flared_mwh"),
        ("Vattenfall", "BFG_COG_BOFG", None),
    ]
    out: list[dict[str, Any]] = []
    for config_id in [C0, C1]:
        rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        for sink, carrier, field in sink_fields:
            value = 0.0 if field is None else sum(_safe_float(row.get(field)) for row in rows)
            out.append(
                {
                    "configuration_id": config_id,
                    "sink": sink,
                    "carrier": carrier,
                    "used_or_flared_mwh": round(value, 6),
                    "active_in_physical_dispatch": str(field is not None and (value > 0 or sink in {"KGF1", "KGF2", "Sinter", "BoilerFuel", "Flare"})).lower(),
                    "caveat": "Vattenfall kept inactive/reporting-only; no electricity offset or revenue." if sink == "Vattenfall" else "",
                }
            )
    return out


def _ng_and_steam_summary(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for config_id in [C0, C1]:
        rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        boiler_ng = sum(_safe_float(row.get("natural_gas_boiler_mwh")) for row in rows)
        drp_ng = sum(_safe_float(row.get("natural_gas_nm3")) for row in rows)
        steam = sum(_safe_float(row.get("steam")) for row in rows)
        boiler_wag = sum(_safe_float(row.get("BFG_to_boiler_mwh")) + _safe_float(row.get("COG_to_boiler_mwh")) for row in rows)
        out.append(
            {
                "configuration_id": config_id,
                "natural_gas_boiler_mwh": round(boiler_ng, 6),
                "natural_gas_drp_nm3": round(drp_ng, 6),
                "wag_to_boiler_mwh": round(boiler_wag, 6),
                "steam_placeholder_mwh": round(steam, 6),
                "development_placeholder": "true",
                "caveat": "Boiler/steam is flat 6 PJ/y development placeholder, not measured Tata hourly demand.",
            }
        )
    return out


def _daily_summary(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for config_id in [C0, C1]:
        rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        day_count = len(rows) // 24
        weekly_target = sum(_safe_float(row.get("final_product_output_t")) for row in rows)
        avg_daily = weekly_target / day_count if day_count else 0.0
        for day in range(day_count):
            chunk = rows[day * 24 : day * 24 + 24]
            production = [_safe_float(row.get("final_product_output_t")) for row in chunk]
            out.append(
                {
                    "configuration_id": config_id,
                    "day_index": day,
                    "production_t": round(sum(production), 6),
                    "average_daily_target_t": round(avg_daily, 6),
                    "within_80_120_guardrail": str(0.8 * avg_daily - TOLERANCE <= sum(production) <= 1.2 * avg_daily + TOLERANCE).lower(),
                    "min_hourly_production_t": round(min(production), 6) if production else 0.0,
                    "max_hourly_production_t": round(max(production), 6) if production else 0.0,
                }
            )
    return out


def _inventory_summary(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    fields = ["coke_inventory_t", "sinter_inventory_t", "hot_iron_inventory_t", "cold_slab_inventory_t", "DRI_inventory_t"]
    for config_id in [C0, C1]:
        rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        for field in fields:
            values = [_safe_float(row.get(field), default=None) for row in rows if row.get(field) not in {"", None}]
            values = [value for value in values if value is not None]
            if not values:
                continue
            out.append(
                {
                    "configuration_id": config_id,
                    "inventory": field,
                    "min_t": round(min(values), 6),
                    "max_t": round(max(values), 6),
                    "terminal_t": round(values[-1], 6),
                    "hit_zero_hours": sum(1 for value in values if abs(value) <= TOLERANCE),
                }
            )
    return out


def _analytics(
    audits: list[dict[str, Any]],
    *,
    input_validation_time: float,
    total_runtime: float,
    output_dir: Path,
    scaling_reference: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    file_count, folder_size = _folder_stats(output_dir)
    rows = []
    for audit in audits:
        variable_count = int(audit.get("variable_count") or 0)
        binary_count = int(audit.get("binary_count") or 0)
        config_id = audit["configuration_id"]
        solve_time = _safe_float(audit.get("runtime_seconds"))
        ref = (scaling_reference or {}).get(config_id, 0.0)
        rows.append(
            {
                "configuration_id": config_id,
                "input_validation_time_seconds": round(input_validation_time, 6),
                "model_build_time_seconds": audit.get("build_runtime_seconds", ""),
                "solve_time_seconds": audit.get("runtime_seconds", ""),
                "reporting_output_time_seconds": "",
                "total_runtime_seconds": round(total_runtime, 6),
                "solver_name": audit.get("solver_name", ""),
                "solver_status": audit.get("solver_status", ""),
                "termination_condition": audit.get("termination_condition", ""),
                "objective_value": audit.get("objective_value", ""),
                "variable_count": variable_count,
                "binary_count": binary_count,
                "continuous_variable_count": variable_count - binary_count,
                "constraint_count": audit.get("constraint_count", ""),
                "nonzero_count": "",
                "mip_gap": audit.get("mip_gap", ""),
                "node_count": "",
                "iteration_count": "",
                "peak_memory_mb": "",
                "output_folder_size_bytes": folder_size,
                "output_file_count": file_count,
                "runtime_scaling_ratio_vs_24h": round(solve_time / ref, 6) if ref else "",
                "caveat": "Unavailable solver internals are left blank.",
            }
        )
    return rows


def _phase_gate(
    *,
    audits: list[dict[str, Any]],
    hourly_rows: list[dict[str, Any]],
    phase: str,
    horizon_hours: int,
) -> dict[str, Any]:
    by_config = _audit_map(audits)
    c0_ok = by_config.get(C0, {}).get("build_status") == "solved" and _zero_residual(by_config[C0])
    c1_ok = by_config.get(C1, {}).get("build_status") == "solved" and _zero_residual(by_config[C1])
    balance_ok = _max_balance_residual(hourly_rows) <= TOLERANCE
    if not balance_ok:
        decision = "blocked_24h_wag_balance_failure" if phase == "24h" else "blocked_168h_wag_balance_failure"
    elif c0_ok and c1_ok and phase == "24h":
        decision = "pass_to_phase3_168h_wag_rerun"
    elif c1_ok and not c0_ok and phase == "24h":
        decision = "pass_24h_c1_only_c0_blocked"
    elif c0_ok and c1_ok and phase == "168h":
        decision = "pass_168h_with_wag_caveats"
    elif phase == "168h":
        decision = "blocked_168h_solver_failure"
    else:
        decision = "blocked_24h_solver_failure"
    return {
        "stage": f"S4.4c4b_{phase}",
        "decision": decision,
        "horizon_hours": horizon_hours,
        "c0_solved": c0_ok,
        "c1_solved": c1_ok,
        "max_abs_wag_balance_residual_mwh": round(_max_balance_residual(hourly_rows), 9),
        "daily_production_guardrail_active": True,
        "hourly_da_price_taking_active": False,
        "product_revenue_active": False,
        "export_revenue_active": False,
        "grid_tariff_objective_active": False,
        "direct_wag_market_valuation_active": False,
        "co2_ets_objective_active": False,
        "vattenfall_dispatch_active": False,
        "wag_storage_active": False,
        "steam_storage_active": False,
        "thesis_usable": False,
        "Tata_validated": False,
        "caveat": "C1 retained BF-BOF WAG route remains a caveat in this minimal implementation.",
    }


def _run_regression(
    *,
    output_dir: Path,
    prefix: str,
    horizon_hours: int,
    target_multiplier: float,
    phase: str,
    scaling_reference: dict[str, float] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    validation_start = time.perf_counter()
    validation = validate_unified_dev_inputs(CORRECTED_INPUT_DIR.resolve())
    input_validation_time = time.perf_counter() - validation_start
    if validation["failure_count"] != 0:
        gate = {
            "stage": f"S4.4c4b_{phase}",
            "decision": "blocked_input_contract_mismatch",
            "validator_failure_count": validation["failure_count"],
        }
        _write_json(output_dir / f"{prefix}_stage_gate.json", gate)
        _write_csv(output_dir / f"{prefix}_stage_gate.csv", [gate])
        return {"phase_stage_gate": gate, "configuration_build_audit": [], "hourly_rows": []}

    start = time.perf_counter()
    report = run_s44c_unified_physical_regression(
        input_dir=CORRECTED_INPUT_DIR.resolve(),
        run_id=f"s4_4c4b_{phase}_minimal_wag",
        write_report=False,
        horizon_hours_override=horizon_hours,
        target_multiplier=target_multiplier,
        fix_c0_binary_schedule=True,
        enable_minimal_wag_layer=True,
        daily_production_guardrail=True,
    )
    total_runtime = time.perf_counter() - start
    audits = report["configuration_build_audit"]
    hourly_rows = report["hourly_rows"]
    gate = _phase_gate(audits=audits, hourly_rows=hourly_rows, phase=phase, horizon_hours=horizon_hours)
    full_report = {
        **report,
        "phase_stage_gate": gate,
        "input_validation_time_seconds": round(input_validation_time, 6),
        "total_runtime_seconds": round(total_runtime, 6),
    }
    _write_json(output_dir / f"{prefix}_report.json", full_report)
    _write_csv(output_dir / f"{prefix}_report.csv", _report_rows(audits))
    _write_csv(output_dir / f"{prefix}_wag_by_carrier.csv", _wag_by_carrier(hourly_rows))
    _write_csv(output_dir / f"{prefix}_wag_by_sink.csv", _wag_by_sink(hourly_rows))
    _write_csv(output_dir / f"{prefix}_ng_and_steam_summary.csv", _ng_and_steam_summary(hourly_rows))
    _write_csv(output_dir / f"{prefix}_hourly_dispatch_c0.csv", [row for row in hourly_rows if row["configuration_id"] == C0])
    _write_csv(output_dir / f"{prefix}_hourly_dispatch_c1.csv", [row for row in hourly_rows if row["configuration_id"] == C1])
    if phase == "168h":
        _write_csv(output_dir / f"{prefix}_daily_summary.csv", _daily_summary(hourly_rows))
        _write_csv(output_dir / f"{prefix}_inventory_summary.csv", _inventory_summary(hourly_rows))
    _write_json(output_dir / f"{prefix}_stage_gate.json", gate)
    _write_csv(output_dir / f"{prefix}_stage_gate.csv", [gate])
    _write_csv(
        output_dir / f"{prefix}_computational_analytics.csv",
        _analytics(
            audits,
            input_validation_time=input_validation_time,
            total_runtime=total_runtime,
            output_dir=output_dir,
            scaling_reference=scaling_reference,
        ),
    )
    return full_report


def run_24h() -> dict[str, Any]:
    phase1_gate = _stage_gate_json(C4B_IMPL_DIR / "s4_4c4b_stage_gate_phase1.json")
    if phase1_gate.get("decision") != "pass_to_phase2_24h_wag_rerun":
        gate = {
            "stage": "S4.4c4b_24h",
            "decision": "blocked_input_contract_mismatch",
            "phase1_gate": phase1_gate.get("decision", "missing"),
        }
        C4B_24H_DIR.mkdir(parents=True, exist_ok=True)
        _write_json(C4B_24H_DIR / "s4_4c4b_24h_stage_gate.json", gate)
        _write_csv(C4B_24H_DIR / "s4_4c4b_24h_stage_gate.csv", [gate])
        return {"phase_stage_gate": gate, "configuration_build_audit": [], "hourly_rows": []}
    return _run_regression(
        output_dir=C4B_24H_DIR,
        prefix="s4_4c4b_24h",
        horizon_hours=24,
        target_multiplier=1.0,
        phase="24h",
    )


def run_168h() -> dict[str, Any]:
    gate24 = _stage_gate_json(C4B_24H_DIR / "s4_4c4b_24h_stage_gate.json")
    if gate24.get("decision") != "pass_to_phase3_168h_wag_rerun":
        gate = {
            "stage": "S4.4c4b_168h",
            "decision": "blocked_168h_solver_failure",
            "phase2_gate": gate24.get("decision", "missing"),
        }
        C4B_168H_DIR.mkdir(parents=True, exist_ok=True)
        _write_json(C4B_168H_DIR / "s4_4c4b_168h_stage_gate.json", gate)
        _write_csv(C4B_168H_DIR / "s4_4c4b_168h_stage_gate.csv", [gate])
        return {"phase_stage_gate": gate, "configuration_build_audit": [], "hourly_rows": []}
    scaling_reference = {
        row["configuration_id"]: _safe_float(row.get("solve_time_seconds"))
        for row in _read_csv(C4B_24H_DIR / "s4_4c4b_24h_computational_analytics.csv")
    }
    return _run_regression(
        output_dir=C4B_168H_DIR,
        prefix="s4_4c4b_168h",
        horizon_hours=168,
        target_multiplier=7.0,
        phase="168h",
        scaling_reference=scaling_reference,
    )


def run_s4_4c4b_minimal_wag_static_regression() -> dict[str, Any]:
    phase1 = run_phase1()
    result: dict[str, Any] = {"phase1_gate": phase1}
    if phase1["decision"] != "pass_to_phase2_24h_wag_rerun":
        return result
    phase2 = run_24h()
    result["phase2_gate"] = phase2["phase_stage_gate"]
    if phase2["phase_stage_gate"]["decision"] != "pass_to_phase3_168h_wag_rerun":
        return result
    phase3 = run_168h()
    result["phase3_gate"] = phase3["phase_stage_gate"]
    return result
