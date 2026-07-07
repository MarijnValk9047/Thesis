"""S4.4c4c full WAG/steam/internal-generation static regression."""

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
    C1_EMISSIONS_PROXY_RETAINED_BFBOF_SHARE,
    C1_RETAINED_BFBOF_TARGET_SHARE,
    C0_SITE_ELECTRICITY_PROXY_MWH_H,
    ETA_BOILER_STEAM,
    FLARE_CO2_EF_T_PER_MWH,
    FLARING_CO2_DIAGNOSTIC_EUR_PER_T,
    KGF_UNDERFIRING_MWH_PER_T_COKE,
    SELECTED_WAG_LHV_MJ_PER_NM3,
    SINTER_COG_MWH_PER_T_SINTER,
    VATTENFALL_IJM01_WAG_CAP_NM3_H,
    VATTENFALL_TOTAL_WAG_CAP_NM3_H,
    VATTENFALL_VELSEN25_WAG_CAP_NM3_H,
    WAG_TO_POWER_EFFICIENCY,
    _build_c0_inputs,
    _load_tables,
    run_s44c_unified_physical_regression,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
S4_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4"
C4B_IMPL_DIR = S4_ROOT / "s4_4c4b_minimal_wag_steam_gas_implementation"
C4C_DIR = S4_ROOT / "s4_4c4c_full_wag_steam_internal_generation"
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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value_in: Any, default: float = 0.0) -> float:
    try:
        if value_in in {"", None}:
            return default
        return float(value_in)
    except (TypeError, ValueError):
        return default


def _folder_stats(path: Path) -> tuple[int, int]:
    files = [candidate for candidate in path.rglob("*") if candidate.is_file()]
    return len(files), sum(candidate.stat().st_size for candidate in files)


def _phase1_equation_rows() -> list[dict[str, Any]]:
    return [
        {
            "equation_id": "C1_retained_BF_BOF_route",
            "pypsa_terms": "Links KGF1, Sinter, BF6, BOF, HSM active in C1; BF7 and KGF2 inactive",
            "implemented_status": "active",
            "configuration_scope": "C1",
            "caveat": "Retained route share uses nearest feasible on-state block above the BF6 emissions-share proxy; development-only.",
        },
        {
            "equation_id": "carrier_specific_WAG_balances",
            "pypsa_terms": "Bus_BFG, Bus_COG, Bus_BOFG; process Links, boiler Links, Vattenfall Links, flare Links",
            "implemented_status": "active",
            "configuration_scope": "C0 and C1",
            "caveat": "No WAG storage; balances close hourly by carrier.",
        },
        {
            "equation_id": "process_WAG_sinks",
            "pypsa_terms": "KGF1 BFG/COG 50/50, KGF2 pure COG in C0 only, Sinter fixed COG",
            "implemented_status": "active",
            "configuration_scope": "C0 and C1 with topology activation",
            "caveat": "HSM and PEFA remain inactive eligibility rows because coefficients are not approved.",
        },
        {
            "equation_id": "aggregated_boiler_steam",
            "pypsa_terms": "BFG/COG/NG to Bus_BoilerFuel; Bus_BoilerFuel to Bus_Steam",
            "implemented_status": "active_placeholder",
            "configuration_scope": "C0 and C1",
            "caveat": "6 PJ/y flat hourly development placeholder; no steam storage.",
        },
        {
            "equation_id": "Mode_B_internal_generation",
            "pypsa_terms": "BFG/COG/BOFG to VattenfallFuel; VattenfallFuel to internal electricity offset",
            "implemented_status": "active_reporting_and_net_import_offset",
            "configuration_scope": "C0 and C1",
            "caveat": "No export revenue, product revenue, tariff revenue, or WAG market valuation.",
        },
        {
            "equation_id": "carrier_specific_flaring_CO2",
            "pypsa_terms": "Flare_BFG, Flare_COG, Flare_BOFG to CO2 reporting",
            "implemented_status": "active_reporting",
            "configuration_scope": "C0 and C1",
            "caveat": "CO2 cost is diagnostic only; objective uses only a tiny non-economic flare allocation tie-breaker.",
        },
    ]


def _phase1_parameter_rows() -> list[dict[str, Any]]:
    tables = _load_tables(CORRECTED_INPUT_DIR)
    c0 = _build_c0_inputs(tables)
    carrier_cap_rows = []
    for carrier, lhv in SELECTED_WAG_LHV_MJ_PER_NM3.items():
        carrier_cap_rows.append(
            {
                "parameter": f"vattenfall_total_cap_if_all_{carrier}",
                "value_used": round(VATTENFALL_TOTAL_WAG_CAP_NM3_H * lhv / 3600.0, 6),
                "unit": "MWh_LHV/h",
                "source_or_method": "user_supplied_figure_candidate converted with selected carrier LHV",
                "thesis_usability": "false",
                "sensitivity_required": "true",
                "caveat": "Carrier-specific equivalent cap for reporting; dispatch uses one total volumetric cap.",
            }
        )
    return [
        {
            "parameter": "alpha_BFG_BF",
            "value_used": c0.bfg_nm3_per_t_hot_iron,
            "converted_value": c0.bfg_mwh_per_t_hot_iron,
            "unit": "Nm3/t_hot_metal and MWh_LHV/t_hot_metal",
            "source_or_method": "existing migrated S4.4b5a WAG coefficient",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "Development-only, not Tata-measured truth.",
        },
        {
            "parameter": "alpha_COG_KGF",
            "value_used": c0.cog_m3_per_t_dry_coal,
            "converted_value": c0.cog_mwh_per_t_coke,
            "unit": "m3/t_model_coke_proxy and MWh_LHV/t",
            "source_or_method": "existing migrated S4.4b5a WAG coefficient",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "Development-only, not Tata-measured truth.",
        },
        {
            "parameter": "alpha_BOFG_BOF",
            "value_used": c0.bofg_nm3_per_t_liquid_steel,
            "converted_value": c0.bofg_mwh_per_t_liquid_steel,
            "unit": "Nm3/t_liquid_steel and MWh_LHV/t",
            "source_or_method": "existing migrated S4.4b5a WAG coefficient",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "Development-only, not Tata-measured truth.",
        },
        {
            "parameter": "C1_retained_BF_BOF_share",
            "value_used": C1_RETAINED_BFBOF_TARGET_SHARE,
            "unit": "fraction_of_final_product_target",
            "source_or_method": "nearest_feasible_on_state_block_above_emissions_proxy",
            "emissions_proxy_share": C1_EMISSIONS_PROXY_RETAINED_BFBOF_SHARE,
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "Feasibility block preserves process minima and terminal inventory; not a route-planning truth.",
        },
        {
            "parameter": "alpha_fuel_KGF",
            "value_used": KGF_UNDERFIRING_MWH_PER_T_COKE,
            "unit": "MWh_LHV/t_coke",
            "source_or_method": "WAG abstraction development assumption",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "KGF1 fixed 50/50 BFG/COG energy split; KGF2 pure COG in C0 only.",
        },
        {
            "parameter": "alpha_fuel_Sinter_COG",
            "value_used": SINTER_COG_MWH_PER_T_SINTER,
            "unit": "MWh_LHV/t_sinter",
            "source_or_method": "WAG abstraction development assumption",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "Fixed process-linked COG demand.",
        },
        {
            "parameter": "boiler_placeholder",
            "value_used": BOILER_TOTAL_PLACEHOLDER_MWH_H,
            "wag_cap_mwh_h": BOILER_WAG_PLACEHOLDER_CAP_MWH_H,
            "unit": "MWh_LHV/h",
            "source_or_method": "6 PJ/y and 3 PJ/y placeholder conversion",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "Flat annual-to-hourly development placeholder, not measured hourly steam demand.",
        },
        {
            "parameter": "eta_boiler_steam",
            "value_used": ETA_BOILER_STEAM,
            "unit": "MWh_steam/MWh_LHV",
            "source_or_method": "WAG abstraction development assumption",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "Generic boiler proxy.",
        },
        {
            "parameter": "wag_to_power_efficiency_mode_b",
            "value_used": WAG_TO_POWER_EFFICIENCY,
            "unit": "MWh_e/MWh_LHV",
            "source_or_method": "user_supplied_existing_value_for_Mode_B_if_available",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "Internal offset only; no export, revenue, or direct WAG valuation.",
        },
        {
            "parameter": "vattenfall_caps",
            "Velsen_25_nm3_h": VATTENFALL_VELSEN25_WAG_CAP_NM3_H,
            "IJmuiden_01_nm3_h": VATTENFALL_IJM01_WAG_CAP_NM3_H,
            "total_nm3_h": VATTENFALL_TOTAL_WAG_CAP_NM3_H,
            "unit": "Nm3/h WAG interface cap",
            "source_or_method": "user_supplied_figure_candidate",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "Development-only figure-derived cap; no Vattenfall merchant dispatch model.",
        },
        {
            "parameter": "flare_CO2_factors",
            "value_used": json.dumps(FLARE_CO2_EF_T_PER_MWH, sort_keys=True),
            "unit": "tCO2/MWh_LHV",
            "source_or_method": "development_placeholder",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "Reporting-only placeholder; not approved ETS factor.",
        },
        {
            "parameter": "flaring_CO2_diagnostic_price",
            "value_used": FLARING_CO2_DIAGNOSTIC_EUR_PER_T,
            "unit": "EUR/tCO2",
            "source_or_method": "diagnostic_placeholder",
            "thesis_usability": "false",
            "sensitivity_required": "true",
            "caveat": "Separate diagnostic cost, not objective ETS steering.",
        },
    ] + carrier_cap_rows


def _phase1_policy_rows() -> list[dict[str, Any]]:
    return [
        {"policy": "C1_topology", "decision": "BF6/KGF1 retained; BF7/KGF2 inactive", "caveat": "Frozen project default."},
        {"policy": "DRP_on_state", "decision": "C4C hybrid treats 0.7-1.1 as on-state range", "caveat": "Replaces prior always-on DRP shortcut only for hybrid WAG run."},
        {"policy": "Vattenfall_Mode_B", "decision": "internal net-import offset only", "caveat": "No export revenue or market valuation."},
        {"policy": "BOFG_to_boiler", "decision": "inactive", "caveat": "BOFG can go to Vattenfall interface or flare in this run."},
        {"policy": "WAG_and_steam_storage", "decision": "inactive", "caveat": "Hourly WAG and steam must balance without stores."},
        {"policy": "flaring_CO2_cost", "decision": "diagnostic_reporting_only", "caveat": "Objective uses non-economic flare allocation tie-breaker only."},
        {"policy": "DA_and_economics", "decision": "inactive", "caveat": "No DA, bidding, stochasticity, CVaR, mFRR, product/export revenue, tariffs, or ETS objective."},
    ]


def run_phase1() -> dict[str, Any]:
    C4C_DIR.mkdir(parents=True, exist_ok=True)
    c4b_gate = _read_json(C4B_IMPL_DIR / "s4_4c4b_stage_gate_phase1.json")
    validation = validate_unified_dev_inputs(CORRECTED_INPUT_DIR.resolve())
    decision = "pass_to_phase2_24h_full_wag_rerun"
    if c4b_gate.get("decision") != "pass_to_phase2_24h_wag_rerun":
        decision = "blocked_c4b_prerequisite_missing"
    elif validation["failure_count"] != 0:
        decision = "blocked_input_contract_mismatch"
    gate = {
        "stage": "S4.4c4c_phase1",
        "decision": decision,
        "c4b_phase1_gate": c4b_gate.get("decision", "missing"),
        "validator_failure_count": validation["failure_count"],
        "retained_c1_bf_bof_route_active": True,
        "internal_generation_mode_b_active": True,
        "direct_wag_market_valuation_active": False,
        "export_revenue_active": False,
        "product_revenue_active": False,
        "co2_ets_objective_active": False,
        "wag_storage_active": False,
        "steam_storage_active": False,
        "thesis_usable": False,
        "Tata_validated": False,
        "caveat": "Development-only full WAG/steam/internal-generation implementation.",
    }
    _write_csv(C4C_DIR / "s4_4c4c_implemented_equations.csv", _phase1_equation_rows())
    _write_csv(C4C_DIR / "s4_4c4c_parameter_values_used.csv", _phase1_parameter_rows())
    _write_csv(C4C_DIR / "s4_4c4c_policy_decisions_applied.csv", _phase1_policy_rows())
    _write_json(C4C_DIR / "s4_4c4c_stage_gate_phase1.json", gate)
    _write_csv(C4C_DIR / "s4_4c4c_stage_gate_phase1.csv", [gate])
    return gate


def _audit_map(audits: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["configuration_id"]: row for row in audits}


def _zero_residual(audit: dict[str, Any]) -> bool:
    return abs(_safe_float(audit.get("final_product_residual_t"), 1.0)) <= TOLERANCE


def _max_balance_residual(hourly_rows: list[dict[str, Any]]) -> float:
    max_abs = 0.0
    for row in hourly_rows:
        for field in ("BFG_balance_residual_mwh", "COG_balance_residual_mwh", "BOFG_balance_residual_mwh"):
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
        "retained_bf_bof_final_product_t",
        "eaf_final_product_t",
        "WAG_generated",
        "WAG_used",
        "WAG_flared",
        "wag_electricity_mwh",
        "gross_electricity_mwh",
        "net_grid_import_mwh",
        "flaring_co2_t",
        "flaring_co2_diagnostic_cost_eur",
        "variable_count",
        "binary_count",
        "constraint_count",
        "caveat",
    ]
    return [{field: row.get(field, "") for field in fields} for row in audits]


def _wag_by_carrier(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config_id in (C0, C1):
        config_rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        for carrier in ("BFG", "COG", "BOFG"):
            generated = sum(_safe_float(row.get(f"{carrier}_generated_mwh")) for row in config_rows)
            flared = sum(_safe_float(row.get(f"{carrier}_flared_mwh")) for row in config_rows)
            if carrier == "BFG":
                used = sum(
                    _safe_float(row.get("BFG_to_KGF1_mwh"))
                    + _safe_float(row.get("BFG_to_boiler_mwh"))
                    + _safe_float(row.get("BFG_to_vattenfall_mwh"))
                    for row in config_rows
                )
            elif carrier == "COG":
                used = sum(
                    _safe_float(row.get("COG_to_KGF1_mwh"))
                    + _safe_float(row.get("COG_to_KGF2_mwh"))
                    + _safe_float(row.get("COG_to_sinter_mwh"))
                    + _safe_float(row.get("COG_to_boiler_mwh"))
                    + _safe_float(row.get("COG_to_vattenfall_mwh"))
                    for row in config_rows
                )
            else:
                used = sum(_safe_float(row.get("BOFG_to_vattenfall_mwh")) for row in config_rows)
            rows.append(
                {
                    "configuration_id": config_id,
                    "carrier": carrier,
                    "generated_mwh": round(generated, 6),
                    "used_mwh": round(used, 6),
                    "flared_mwh": round(flared, 6),
                    "flare_share": round(flared / generated, 6) if generated else 0.0,
                    "max_abs_balance_residual_mwh": round(
                        max((abs(_safe_float(row.get(f"{carrier}_balance_residual_mwh"))) for row in config_rows), default=0.0),
                        9,
                    ),
                }
            )
    return rows


def _wag_by_sink(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sink_fields = [
        ("KGF1", "BFG", "BFG_to_KGF1_mwh"),
        ("KGF1", "COG", "COG_to_KGF1_mwh"),
        ("KGF2", "COG", "COG_to_KGF2_mwh"),
        ("Sinter", "COG", "COG_to_sinter_mwh"),
        ("BoilerFuel", "BFG", "BFG_to_boiler_mwh"),
        ("BoilerFuel", "COG", "COG_to_boiler_mwh"),
        ("Vattenfall_internal_generation", "BFG", "BFG_to_vattenfall_mwh"),
        ("Vattenfall_internal_generation", "COG", "COG_to_vattenfall_mwh"),
        ("Vattenfall_internal_generation", "BOFG", "BOFG_to_vattenfall_mwh"),
        ("Flare", "BFG", "BFG_flared_mwh"),
        ("Flare", "COG", "COG_flared_mwh"),
        ("Flare", "BOFG", "BOFG_flared_mwh"),
    ]
    rows: list[dict[str, Any]] = []
    for config_id in (C0, C1):
        config_rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        for sink, carrier, field in sink_fields:
            value = sum(_safe_float(row.get(field)) for row in config_rows)
            rows.append(
                {
                    "configuration_id": config_id,
                    "sink": sink,
                    "carrier": carrier,
                    "mwh": round(value, 6),
                    "active_in_physical_dispatch": str(value > TOLERANCE).lower(),
                    "caveat": "No revenue or export; internal offset only." if "Vattenfall" in sink else "",
                }
            )
    return rows


def _electricity_summary(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config_id in (C0, C1):
        config_rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        gross = sum(
            _safe_float(
                row.get("gross_electricity_mwh")
                if row.get("gross_electricity_mwh") not in {"", None}
                else row.get("electricity_mwh")
            )
            for row in config_rows
        )
        wag_electricity = sum(_safe_float(row.get("wag_electricity_mwh")) for row in config_rows)
        net = sum(
            _safe_float(
                row.get("net_grid_import_mwh")
                if row.get("net_grid_import_mwh") not in {"", None}
                else row.get("electricity_mwh")
            )
            for row in config_rows
        )
        rows.append(
            {
                "configuration_id": config_id,
                "gross_electricity_demand_mwh": round(gross, 6),
                "wag_internal_generation_mwh": round(wag_electricity, 6),
                "net_grid_import_mwh": round(net, 6),
                "offset_share_of_gross": round(wag_electricity / gross, 6) if gross else 0.0,
                "export_revenue_active": "false",
                "direct_wag_market_valuation_active": "false",
                "caveat": "Mode B internal offset; no export or revenue.",
            }
        )
    return rows


def _ng_steam_summary(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config_id in (C0, C1):
        config_rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        rows.append(
            {
                "configuration_id": config_id,
                "natural_gas_boiler_mwh": round(sum(_safe_float(row.get("natural_gas_boiler_mwh")) for row in config_rows), 6),
                "natural_gas_drp_nm3": round(sum(_safe_float(row.get("natural_gas_nm3")) for row in config_rows), 6),
                "steam_placeholder_mwh": round(sum(_safe_float(row.get("steam")) for row in config_rows), 6),
                "boiler_placeholder_active": "true",
                "steam_storage_active": "false",
                "caveat": "6 PJ/y boiler/steam placeholder converted to flat hourly demand.",
            }
        )
    return rows


def _co2_flaring_summary(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config_id in (C0, C1):
        config_rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        for carrier in ("BFG", "COG", "BOFG"):
            flared = sum(_safe_float(row.get(f"{carrier}_flared_mwh")) for row in config_rows)
            co2 = sum(_safe_float(row.get(f"{carrier}_flare_co2_t")) for row in config_rows)
            rows.append(
                {
                    "configuration_id": config_id,
                    "carrier": carrier,
                    "flared_mwh": round(flared, 6),
                    "flaring_co2_t": round(co2, 6),
                    "diagnostic_cost_eur": round(co2 * FLARING_CO2_DIAGNOSTIC_EUR_PER_T, 6),
                    "co2_cost_objective_active": "false",
                    "allocation_tiebreaker_active": "true",
                    "caveat": "CO2 and cost are diagnostic placeholders, not ETS objective steering.",
                }
            )
    return rows


def _daily_summary(hourly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config_id in (C0, C1):
        config_rows = [row for row in hourly_rows if row["configuration_id"] == config_id]
        for day in range(len(config_rows) // 24):
            chunk = config_rows[day * 24 : day * 24 + 24]
            production = sum(_safe_float(row.get("final_product_output_t")) for row in chunk)
            rows.append(
                {
                    "configuration_id": config_id,
                    "day_index": day,
                    "production_t": round(production, 6),
                    "wag_generated_mwh": round(sum(_safe_float(row.get("WAG_generated")) for row in chunk), 6),
                    "wag_electricity_mwh": round(sum(_safe_float(row.get("wag_electricity_mwh")) for row in chunk), 6),
                    "net_grid_import_mwh": round(sum(_safe_float(row.get("net_grid_import_mwh")) for row in chunk), 6),
                }
            )
    return rows


def _analytics(
    audits: list[dict[str, Any]],
    *,
    validation_time: float,
    total_runtime: float,
    output_dir: Path,
    scaling_reference: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    file_count, folder_size = _folder_stats(output_dir)
    rows: list[dict[str, Any]] = []
    for audit in audits:
        variable_count = int(audit.get("variable_count") or 0)
        binary_count = int(audit.get("binary_count") or 0)
        config_id = audit["configuration_id"]
        solve_time = _safe_float(audit.get("runtime_seconds"))
        ref = (scaling_reference or {}).get(config_id, 0.0)
        rows.append(
            {
                "configuration_id": config_id,
                "input_validation_time_seconds": round(validation_time, 6),
                "model_build_time_seconds": audit.get("build_runtime_seconds", ""),
                "solve_time_seconds": audit.get("runtime_seconds", ""),
                "total_runtime_seconds": round(total_runtime, 6),
                "solver_name": audit.get("solver_name", ""),
                "solver_status": audit.get("solver_status", ""),
                "termination_condition": audit.get("termination_condition", ""),
                "objective_value": audit.get("objective_value", ""),
                "variable_count": variable_count,
                "binary_count": binary_count,
                "continuous_variable_count": variable_count - binary_count,
                "constraint_count": audit.get("constraint_count", ""),
                "mip_gap": audit.get("mip_gap", ""),
                "output_folder_size_bytes": folder_size,
                "output_file_count": file_count,
                "runtime_scaling_ratio_vs_24h": round(solve_time / ref, 6) if ref else "",
            }
        )
    return rows


def _stage_gate(audits: list[dict[str, Any]], hourly_rows: list[dict[str, Any]], *, phase: str) -> dict[str, Any]:
    by_config = _audit_map(audits)
    c0_ok = by_config.get(C0, {}).get("build_status") == "solved" and _zero_residual(by_config[C0])
    c1_ok = by_config.get(C1, {}).get("build_status") == "solved" and _zero_residual(by_config[C1])
    balance_ok = _max_balance_residual(hourly_rows) <= TOLERANCE
    if not balance_ok:
        decision = f"blocked_{phase}_wag_balance_failure"
    elif c0_ok and c1_ok and phase == "24h":
        decision = "pass_to_phase3_168h_full_wag_rerun"
    elif c0_ok and c1_ok:
        decision = "pass_168h_static_physical_with_full_wag_caveats"
    else:
        decision = f"blocked_{phase}_solver_or_production_failure"
    return {
        "stage": f"S4.4c4c_{phase}",
        "decision": decision,
        "c0_solved": c0_ok,
        "c1_solved": c1_ok,
        "max_abs_wag_balance_residual_mwh": round(_max_balance_residual(hourly_rows), 9),
        "daily_production_guardrail_active": True,
        "retained_c1_bf_bof_route_active": True,
        "internal_generation_mode_b_active": True,
        "direct_wag_market_valuation_active": False,
        "export_revenue_active": False,
        "product_revenue_active": False,
        "co2_ets_objective_active": False,
        "wag_storage_active": False,
        "steam_storage_active": False,
        "thesis_usable": False,
        "Tata_validated": False,
        "caveat": "Static physical development run with C4C-specific fixed C0 and C1 schedules.",
    }


def _run_regression(
    *,
    prefix: str,
    horizon_hours: int,
    target_multiplier: float,
    phase: str,
    scaling_reference: dict[str, float] | None = None,
) -> dict[str, Any]:
    validation_start = time.perf_counter()
    validation = validate_unified_dev_inputs(CORRECTED_INPUT_DIR.resolve())
    validation_time = time.perf_counter() - validation_start
    if validation["failure_count"] != 0:
        gate = {"stage": f"S4.4c4c_{phase}", "decision": "blocked_input_contract_mismatch", "validator_failure_count": validation["failure_count"]}
        _write_json(C4C_DIR / f"{prefix}_stage_gate.json", gate)
        _write_csv(C4C_DIR / f"{prefix}_stage_gate.csv", [gate])
        return {"phase_stage_gate": gate, "configuration_build_audit": [], "hourly_rows": []}

    start = time.perf_counter()
    report = run_s44c_unified_physical_regression(
        input_dir=CORRECTED_INPUT_DIR.resolve(),
        run_id=f"s4_4c4c_{phase}_full_wag",
        write_report=False,
        horizon_hours_override=horizon_hours,
        target_multiplier=target_multiplier,
        fix_c0_binary_schedule=True,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        enable_internal_wag_power=True,
        daily_production_guardrail=True,
        fix_c1_hybrid_schedule=True,
    )
    total_runtime = time.perf_counter() - start
    audits = report["configuration_build_audit"]
    hourly_rows = report["hourly_rows"]
    gate = _stage_gate(audits, hourly_rows, phase=phase)
    full_report = {
        **report,
        "phase_stage_gate": gate,
        "input_validation_time_seconds": round(validation_time, 6),
        "total_runtime_seconds": round(total_runtime, 6),
    }
    _write_json(C4C_DIR / f"{prefix}_report.json", full_report)
    _write_csv(C4C_DIR / f"{prefix}_report.csv", _report_rows(audits))
    _write_csv(C4C_DIR / f"{prefix}_hourly_dispatch_c0.csv", [row for row in hourly_rows if row["configuration_id"] == C0])
    _write_csv(C4C_DIR / f"{prefix}_hourly_dispatch_c1.csv", [row for row in hourly_rows if row["configuration_id"] == C1])
    _write_csv(C4C_DIR / f"{prefix}_wag_by_carrier.csv", _wag_by_carrier(hourly_rows))
    _write_csv(C4C_DIR / f"{prefix}_wag_by_sink.csv", _wag_by_sink(hourly_rows))
    _write_csv(C4C_DIR / f"{prefix}_electricity_summary.csv", _electricity_summary(hourly_rows))
    _write_csv(C4C_DIR / f"{prefix}_ng_and_steam_summary.csv", _ng_steam_summary(hourly_rows))
    _write_csv(C4C_DIR / f"{prefix}_co2_flaring_summary.csv", _co2_flaring_summary(hourly_rows))
    if phase == "168h":
        _write_csv(C4C_DIR / f"{prefix}_daily_summary.csv", _daily_summary(hourly_rows))
    _write_csv(
        C4C_DIR / f"{prefix}_computational_analytics.csv",
        _analytics(
            audits,
            validation_time=validation_time,
            total_runtime=total_runtime,
            output_dir=C4C_DIR,
            scaling_reference=scaling_reference,
        ),
    )
    _write_json(C4C_DIR / f"{prefix}_stage_gate.json", gate)
    _write_csv(C4C_DIR / f"{prefix}_stage_gate.csv", [gate])
    return full_report


def run_24h() -> dict[str, Any]:
    phase1_gate = _read_json(C4C_DIR / "s4_4c4c_stage_gate_phase1.json")
    if phase1_gate.get("decision") != "pass_to_phase2_24h_full_wag_rerun":
        gate = {
            "stage": "S4.4c4c_24h",
            "decision": "blocked_phase1_gate",
            "phase1_gate": phase1_gate.get("decision", "missing"),
        }
        _write_json(C4C_DIR / "s4_4c4c_24h_stage_gate.json", gate)
        _write_csv(C4C_DIR / "s4_4c4c_24h_stage_gate.csv", [gate])
        return {"phase_stage_gate": gate, "configuration_build_audit": [], "hourly_rows": []}
    return _run_regression(prefix="s4_4c4c_24h", horizon_hours=24, target_multiplier=1.0, phase="24h")


def run_168h() -> dict[str, Any]:
    gate24 = _read_json(C4C_DIR / "s4_4c4c_24h_stage_gate.json")
    if gate24.get("decision") != "pass_to_phase3_168h_full_wag_rerun":
        gate = {
            "stage": "S4.4c4c_168h",
            "decision": "blocked_24h_gate",
            "phase2_gate": gate24.get("decision", "missing"),
        }
        _write_json(C4C_DIR / "s4_4c4c_168h_stage_gate.json", gate)
        _write_csv(C4C_DIR / "s4_4c4c_168h_stage_gate.csv", [gate])
        return {"phase_stage_gate": gate, "configuration_build_audit": [], "hourly_rows": []}
    scaling_reference = {
        row["configuration_id"]: _safe_float(row.get("solve_time_seconds"))
        for row in _read_csv(C4C_DIR / "s4_4c4c_24h_computational_analytics.csv")
    }
    return _run_regression(
        prefix="s4_4c4c_168h",
        horizon_hours=168,
        target_multiplier=7.0,
        phase="168h",
        scaling_reference=scaling_reference,
    )


def run_s4_4c4c_full_wag_static_regression() -> dict[str, Any]:
    phase1 = run_phase1()
    result: dict[str, Any] = {"phase1_gate": phase1}
    if phase1["decision"] != "pass_to_phase2_24h_full_wag_rerun":
        return result
    phase2 = run_24h()
    result["phase2_gate"] = phase2["phase_stage_gate"]
    if phase2["phase_stage_gate"]["decision"] != "pass_to_phase3_168h_full_wag_rerun":
        return result
    phase3 = run_168h()
    result["phase3_gate"] = phase3["phase_stage_gate"]
    return result
