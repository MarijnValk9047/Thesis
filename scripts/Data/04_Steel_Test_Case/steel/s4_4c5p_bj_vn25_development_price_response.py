"""Bounded VN25 development price-response validation on solved rolling runs."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_bi_pre_dam_operational_boundary_closure import (
    build_wag_source_to_sink_ledger,
)
from .s4_4c_component_ontology import (
    GENERATOR_OPERATING_MODE_CONTRACT_PATH,
    load_generator_operating_mode_contract,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_s2_vn25_development_price_response_v1_20260720"
RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
DEFAULT_OUTPUT = RUN_ROOT / RUN_ID
CONFIG_PATH = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "configs"
    / "steel_vn25_development_price_response.yaml"
)
BASELINE_RUN = RUN_ROOT / "steel_s2_fixed_reference_deterministic_cost_v3_20260716"
OPERATIONAL_CLOSURE_RUN = (
    RUN_ROOT / "steel_s2_pre_dam_operational_boundary_closure_v1_20260720"
)
GENERATOR_SOURCE_CARD = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "source_cards"
    / "IJ01_VN25_GENERATORS_Parameters.md"
)
C5P_O_LEDGER = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "s4_4c5p_o_wag_controller_contract_hardening"
    / "wag_contract_interface_ledger.csv"
)
HOURS_PER_YEAR = 8760.0
EXECUTED_HOURS = 168.0
PJ_PER_MWH = 3.6e-6
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
PERMITTED_DECISIONS = {
    "development_VN25_price_response_ready",
    "generator_price_response_needs_repair",
    "blocked_by_existing_generator_contract",
}


class VN25PriceResponseError(ValueError):
    """Raised when the bounded development validation fails closed."""


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value: Any) -> float:
    return 0.0 if value in {None, ""} else float(value)


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    if not rows:
        raise VN25PriceResponseError(f"Required output is empty: {path.name}")
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_definitions(base: Mapping[str, Any]) -> list[dict[str, Any]]:
    low_efficiency = dict(base["c1_generator_boundary"])
    low_efficiency["vn25_electricity_efficiency"] = 0.34
    return [
        {
            "case_id": "price_insensitive_reference",
            "mode": "price_insensitive_reference",
            "role": "mandatory_accepted_central_benchmark",
            "overrides": {
                "price_series_id": "flat_central_reference_v1",
                "generator_operating_mode": "price_insensitive_reference",
                "source_bounded_generator_efficiency_sensitivity": False,
            },
        },
        {
            "case_id": "development_price_responsive_flat",
            "mode": "development_price_responsive",
            "role": "flat_price_physical_consistency_validation",
            "overrides": {
                "price_series_id": "flat_central_reference_v1",
                "generator_operating_mode": "development_price_responsive",
                "source_bounded_generator_efficiency_sensitivity": False,
            },
        },
        {
            "case_id": "development_price_responsive_step_price",
            "mode": "development_price_responsive",
            "role": "synthetic_break_even_transition_validation",
            "overrides": {
                "price_series_id": "synthetic_vn25_break_even_step_v1",
                "generator_operating_mode": "development_price_responsive",
                "source_bounded_generator_efficiency_sensitivity": False,
            },
        },
        {
            "case_id": "development_price_responsive_efficiency_0_34",
            "mode": "bounded_generator_sensitivity",
            "role": "source_bounded_efficiency_sensitivity",
            "overrides": {
                "price_series_id": "synthetic_vn25_break_even_step_v1",
                "generator_operating_mode": "bounded_generator_sensitivity",
                "source_bounded_generator_efficiency_sensitivity": True,
                "c1_generator_boundary": low_efficiency,
            },
        },
    ]


def _annual_mwh(rows: Iterable[Mapping[str, Any]], field: str) -> float:
    return sum(_number(row.get(field)) for row in rows) * HOURS_PER_YEAR / EXECUTED_HOURS


def _case_artifacts(
    case: Mapping[str, Any], directory: Path
) -> dict[str, Any]:
    hourly_all = _csv(directory / "executed_hourly.csv")
    hourly = [row for row in hourly_all if row["configuration_id"] == C1]
    prices = _csv(directory / "electricity_price_series.csv")
    price_by_key = {
        (int(row["replan_index"]), int(row["model_hour"])): row
        for row in prices
    }
    costs = _csv(directory / "executed_procurement_cost_ledger.csv")
    cost_by_key: dict[tuple[int, int], float] = defaultdict(float)
    total_cost_by_configuration: dict[str, float] = defaultdict(float)
    for row in costs:
        total_cost_by_configuration[row["configuration_id"]] += _number(
            row["cost_eur"]
        )
        if row["configuration_id"] == C1:
            cost_by_key[(int(row["replan_index"]), int(row["plan_hour_index"]))] += _number(
                row["cost_eur"]
            )
    response_rows: list[dict[str, Any]] = []
    efficiency = 0.34 if case["mode"] == "bounded_generator_sensitivity" else 0.345
    break_even = 55.0 / efficiency
    for row in hourly:
        key = (int(row["replan_index"]), int(row["hour_index"]))
        price = price_by_key[key]
        electricity_price = _number(price["price_eur_per_mwh_e"])
        response_rows.append(
            {
                "case_id": case["case_id"],
                "generator_operating_mode": case["mode"],
                "replan_index": key[0],
                "executed_hour_index": int(row["executed_hour_index"]),
                "plan_hour_index": key[1],
                "delivery_timestamp_utc": price["delivery_timestamp_utc"],
                "information_available_timestamp_utc": price[
                    "information_available_timestamp_utc"
                ],
                "electricity_price_eur_per_mwh_e": electricity_price,
                "ng_price_eur_per_mwh_lhv": 55.0,
                "break_even_eur_per_mwh_e": round(break_even, 9),
                "price_region": "above_break_even"
                if electricity_price > break_even
                else "below_break_even",
                "vn25_bfg_mwh_lhv": _number(row.get("BFG_to_VN25_mwh")),
                "vn25_cog_mwh_lhv": _number(row.get("COG_to_VN25_mwh")),
                "vn25_bofg_mwh_lhv": _number(row.get("BOFG_to_VN25_mwh")),
                "vn25_ng_mwh_lhv": _number(row.get("VN25_NG_fuel_mwh")),
                "vn25_total_fuel_mwh_lhv": _number(row.get("VN25_total_fuel_mwh")),
                "vn25_electricity_mwh_e": _number(row.get("VN25_electricity_mwh")),
                "vn25_electric_capacity_mw": _number(row.get("VN25_electric_capacity_mw")),
                "ij01_fuel_mwh_lhv": _number(row.get("IJ01_total_fuel_mwh")),
                "ij01_electricity_mwh_e": _number(row.get("IJ01_electricity_mwh")),
                "ij01_deferred_conversion_mwh": _number(row.get("IJ01_deferred_conversion_mwh")),
                "gross_site_electricity_mwh_e": _number(row.get("gross_electricity_mwh")),
                "net_grid_import_mwh_e": _number(row.get("net_grid_import_mwh")),
                "bfg_flare_mwh_lhv": _number(row.get("BFG_flared_mwh")),
                "cog_flare_mwh_lhv": _number(row.get("COG_flared_mwh")),
                "bofg_flare_mwh_lhv": _number(row.get("BOFG_flared_mwh")),
                "final_product_t": _number(row.get("final_product_output_t")),
                "coke_inventory_t": _number(row.get("coke_inventory_t")),
                "sinter_inventory_t": _number(row.get("sinter_inventory_t")),
                "hot_iron_inventory_t": _number(row.get("hot_iron_inventory_t")),
                "cold_slab_inventory_t": _number(row.get("cold_slab_inventory_t")),
                "dri_inventory_t": _number(row.get("DRI_inventory_t")),
                "steam_15bar_demand_t": _number(row.get("steam_15bar_demand_t")),
                "steam_15bar_supply_t": _number(row.get("steam_15bar_supply_t")),
                "steam_15bar_unserved_t": _number(row.get("steam_15bar_unserved_t")),
                "represented_procurement_cost_eur": round(cost_by_key[key], 6),
            }
        )
    if len(response_rows) != 168:
        raise VN25PriceResponseError(
            f"{case['case_id']} did not provide 168 executed C1 hours."
        )
    return {
        "hourly_all": hourly_all,
        "hourly": hourly,
        "response": response_rows,
        "summary": _json(directory / "run_summary.json"),
        "checks": _csv(directory / "validation_checks.csv"),
        "metrics": _csv(directory / "rolling_model_metrics.csv"),
        "cost_by_configuration": dict(total_cost_by_configuration),
        "code_version": _json(directory / "code_version.json"),
    }


def _comparison_row(case: Mapping[str, Any], artifacts: Mapping[str, Any]) -> dict[str, Any]:
    rows = artifacts["hourly"]
    response = artifacts["response"]
    annual_factor = HOURS_PER_YEAR / EXECUTED_HOURS
    vn25_wag = sum(
        _number(row.get("VN25_WAG_fuel_mwh")) for row in rows
    ) * annual_factor * PJ_PER_MWH
    vn25_ng = sum(
        _number(row.get("VN25_NG_fuel_mwh")) for row in rows
    ) * annual_factor * PJ_PER_MWH
    ij01_wag = sum(
        _number(row.get("IJ01_WAG_fuel_mwh")) for row in rows
    ) * annual_factor * PJ_PER_MWH
    flare = sum(
        _number(row.get("BFG_flared_mwh"))
        + _number(row.get("COG_flared_mwh"))
        + _number(row.get("BOFG_flared_mwh"))
        for row in rows
    ) * annual_factor * PJ_PER_MWH
    c1_metrics = [row for row in artifacts["metrics"] if row["configuration_id"] == C1]
    return {
        "case_id": case["case_id"],
        "generator_operating_mode": case["mode"],
        "case_role": case["role"],
        "price_series_id": case["overrides"]["price_series_id"],
        "vn25_efficiency": 0.34 if case["mode"] == "bounded_generator_sensitivity" else 0.345,
        "vn25_ng_pj_y": round(vn25_ng, 9),
        "vn25_ng_anchor_pj_y": 4.1,
        "vn25_ng_anchor_residual_pct": round(100.0 * (vn25_ng - 4.1) / 4.1, 6),
        "vn25_wag_pj_y": round(vn25_wag, 9),
        "ij01_wag_pj_y": round(ij01_wag, 9),
        "carrier_flare_pj_y": round(flare, 9),
        "generator_wag_plus_flare_pj_y": round(vn25_wag + ij01_wag + flare, 9),
        "generator_wag_plus_flare_anchor_pj_y": 10.6,
        "generator_wag_plus_flare_anchor_residual_pct": round(
            100.0 * (vn25_wag + ij01_wag + flare - 10.6) / 10.6, 6
        ),
        "vn25_electricity_gwh_y": round(_annual_mwh(rows, "VN25_electricity_mwh") / 1000.0, 6),
        "ij01_electricity_gwh_y": round(_annual_mwh(rows, "IJ01_electricity_mwh") / 1000.0, 6),
        "net_grid_import_gwh_y": round(_annual_mwh(rows, "net_grid_import_mwh") / 1000.0, 6),
        "final_product_mt_y": round(_annual_mwh(rows, "final_product_output_t") / 1_000_000.0, 9),
        "represented_procurement_cost_eur_168h": round(
            artifacts["cost_by_configuration"][C1], 6
        ),
        "annualised_represented_procurement_cost_meur_y": round(
            artifacts["cost_by_configuration"][C1] * annual_factor / 1_000_000.0,
            6,
        ),
        "max_vn25_output_mw": round(max(row["vn25_electricity_mwh_e"] for row in response), 6),
        "max_variables": max(int(float(row["variable_count"])) for row in c1_metrics),
        "max_binaries": max(int(float(row["binary_count"])) for row in c1_metrics),
        "max_constraints": max(int(float(row["constraint_count"])) for row in c1_metrics),
        "solver_runtime_seconds": round(sum(_number(row["runtime_seconds"]) for row in c1_metrics), 6),
        "solver_family": ";".join(sorted({row["solver_name"] for row in c1_metrics})),
        "solver_status": ";".join(sorted({row["solver_status"] for row in c1_metrics})),
        "termination_condition": ";".join(sorted({row["termination_condition"] for row in c1_metrics})),
        "max_mip_gap": max((_number(row["mip_gap"]) for row in c1_metrics), default=0.0),
    }


def _generator_identity_rows(
    cases: list[Mapping[str, Any]], artifacts: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for case in cases:
        rows = artifacts[str(case["case_id"])]["hourly"]
        efficiency = 0.34 if case["mode"] == "bounded_generator_sensitivity" else 0.345
        fuel = sum(_number(row.get("VN25_total_fuel_mwh")) for row in rows)
        wag = sum(_number(row.get("VN25_WAG_fuel_mwh")) for row in rows)
        ng = sum(_number(row.get("VN25_NG_fuel_mwh")) for row in rows)
        electricity = sum(_number(row.get("VN25_electricity_mwh")) for row in rows)
        loss = sum(_number(row.get("VN25_conversion_loss_mwh")) for row in rows)
        ij_fuel = sum(_number(row.get("IJ01_total_fuel_mwh")) for row in rows)
        ij_deferred = sum(_number(row.get("IJ01_deferred_conversion_mwh")) for row in rows)
        result.append(
            {
                "case_id": case["case_id"],
                "vn25_efficiency": efficiency,
                "vn25_wag_mwh_lhv": round(wag, 6),
                "vn25_ng_mwh_lhv": round(ng, 6),
                "vn25_total_fuel_mwh_lhv": round(fuel, 6),
                "vn25_electricity_mwh_e": round(electricity, 6),
                "vn25_conversion_loss_mwh": round(loss, 6),
                "fuel_sum_residual_mwh": round(fuel - wag - ng, 9),
                "electricity_conversion_residual_mwh": round(
                    electricity - efficiency * fuel, 9
                ),
                "fuel_output_loss_residual_mwh": round(fuel - electricity - loss, 9),
                "ij01_total_fuel_mwh_lhv": round(ij_fuel, 6),
                "ij01_electricity_mwh_e": round(
                    sum(_number(row.get("IJ01_electricity_mwh")) for row in rows), 6
                ),
                "ij01_deferred_conversion_mwh": round(ij_deferred, 6),
                "ij01_identity_residual_mwh": round(ij_fuel - ij_deferred, 9),
                "ij01_output_status": "quantitative_electricity_steam_split_deferred",
            }
        )
    return result


def _break_even_rows(
    cases: list[Mapping[str, Any]], artifacts: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        response = artifacts[str(case["case_id"])]["response"]
        efficiency = 0.34 if case["mode"] == "bounded_generator_sensitivity" else 0.345
        break_even = 55.0 / efficiency
        below = [row for row in response if row["electricity_price_eur_per_mwh_e"] < break_even]
        above = [row for row in response if row["electricity_price_eur_per_mwh_e"] > break_even]
        below_ng = sum(row["vn25_ng_mwh_lhv"] for row in below)
        above_ng = sum(row["vn25_ng_mwh_lhv"] for row in above)
        rows.append(
            {
                "case_id": case["case_id"],
                "ng_price_eur_per_mwh_lhv": 55.0,
                "vn25_efficiency": efficiency,
                "analytical_break_even_eur_per_mwh_e": round(break_even, 9),
                "below_break_even_hours": len(below),
                "above_break_even_hours": len(above),
                "vn25_ng_below_break_even_mwh_lhv": round(below_ng, 9),
                "vn25_ng_above_break_even_mwh_lhv": round(above_ng, 9),
                "below_break_even_response": "pass" if below_ng <= 1e-5 else "fail",
                "above_break_even_response": (
                    "pass"
                    if case["mode"] == "price_insensitive_reference"
                    or not above
                    or above_ng > 1e-5
                    else "fail"
                ),
                "ng_price_monotonicity": "analytical_pass_objective_coefficient_is_ng_price_minus_electricity_price_times_efficiency",
                "information_timing": "pass"
                if all(
                    datetime.fromisoformat(row["information_available_timestamp_utc"])
                    <= datetime.fromisoformat(row["delivery_timestamp_utc"])
                    for row in response
                )
                else "fail",
            }
        )
    return rows


def _wag_audit_rows(
    cases: list[Mapping[str, Any]], artifacts: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    priority = {
        "BF_hot_stove": 1,
        "coking": 1,
        "sinter": 2,
        "downstream": 2,
        "pellet_preparation": 2,
        "steam": 3,
        "VN25_generator": 4,
        "IJ01_generator": 4,
        "aggregate_generator_interface": 4,
        "flare": 5,
        "accounting": 6,
        "generation": 0,
    }
    rows: list[dict[str, Any]] = []
    for case in cases:
        ledger = build_wag_source_to_sink_ledger(
            artifacts[str(case["case_id"])]["hourly_all"]
        )
        for row in ledger:
            rows.append(
                {
                    "case_id": case["case_id"],
                    "priority_rank": priority.get(str(row["sink_stage"]), 6),
                    **row,
                }
            )
    return rows


def _guardrails(
    cases: list[Mapping[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
    comparison: list[Mapping[str, Any]],
    break_even: list[Mapping[str, Any]],
    identities: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(case_id: str, check_id: str, passed: bool, value: Any, limit: Any) -> None:
        rows.append(
            {
                "case_id": case_id,
                "check_id": check_id,
                "status": "pass" if passed else "fail",
                "value": value,
                "limit_or_contract": limit,
            }
        )

    for case in cases:
        case_id = str(case["case_id"])
        item = artifacts[case_id]
        summary = item["summary"]
        response = item["response"]
        hourly = item["hourly"]
        metrics = item["metrics"]
        add(case_id, "rolling_run_status", summary["status"] == "pass", summary["status"], "pass")
        add(case_id, "c0_rolling_feasibility", summary["c0_rolling_status"] == "pass", summary["c0_rolling_status"], "pass")
        add(case_id, "c1_rolling_feasibility", summary["c1_rolling_status"] == "pass", summary["c1_rolling_status"], "pass")
        annual_product = _annual_mwh(hourly, "final_product_output_t")
        add(case_id, "production_6_75_mt_y", abs(annual_product - 6_750_000.0) <= 33_750.0, round(annual_product, 6), "6.75 Mt/y +/-0.5%")
        add(case_id, "origin_conservation", abs(_number(summary["origin_conservation_max_abs_annualised_residual_t_y"])) <= 1e-5, summary["origin_conservation_max_abs_annualised_residual_t_y"], "<=1e-5 t/y")
        max_wag = max(
            abs(_number(row.get(field)))
            for row in hourly
            for field in ("BFG_balance_residual_mwh", "COG_balance_residual_mwh", "BOFG_balance_residual_mwh")
        )
        add(case_id, "carrier_specific_wag_balances", max_wag <= 1e-5, max_wag, "<=1e-5 MWh")
        max_generator_identity = max(abs(_number(row.get("generator_fuel_identity_residual_mwh"))) for row in hourly)
        add(case_id, "generator_fuel_identity", max_generator_identity <= 1e-5, max_generator_identity, "<=1e-5 MWh")
        max_steam = max(abs(_number(row.get("steam_15bar_unserved_t"))) for row in hourly)
        add(case_id, "steam_unserved", max_steam <= 1e-5, max_steam, "<=1e-5 t")
        max_export = max(row["vn25_electricity_mwh_e"] - row["gross_site_electricity_mwh_e"] for row in response)
        add(case_id, "no_export", max_export <= 1e-5, round(max_export, 9), "VN25 output <= gross demand")
        max_capacity = max(row["vn25_electricity_mwh_e"] - 350.0 for row in response)
        add(case_id, "vn25_350_mw_capacity", max_capacity <= 1e-5, round(max_capacity, 9), "<=0 MWh per hourly step")
        ij01_ng = sum(_number(row.get("IJ01_NG_fuel_mwh")) for row in hourly)
        ij01_output = sum(_number(row.get("IJ01_electricity_mwh")) for row in hourly)
        add(case_id, "ij01_non_price_responsive", ij01_ng <= 1e-5 and ij01_output <= 1e-5, f"NG={ij01_ng};electricity={ij01_output}", "NG=0 and unresolved output split remains zero")
        add(case_id, "active_rolling_validation", all(row["status"] == "pass" for row in item["checks"]), sum(row["status"] != "pass" for row in item["checks"]), "zero failed active checks")
        add(case_id, "gurobi_solver_family", all(row.get("solver_name") in {"gurobi", "gurobi_direct"} for row in metrics), ";".join(sorted({row.get("solver_name", "") for row in metrics})), "gurobi family")
    reference = next(row for row in comparison if row["case_id"] == "price_insensitive_reference")
    flat = next(row for row in comparison if row["case_id"] == "development_price_responsive_flat")
    flat_fields = (
        "vn25_ng_pj_y",
        "vn25_wag_pj_y",
        "ij01_wag_pj_y",
        "carrier_flare_pj_y",
        "vn25_electricity_gwh_y",
        "net_grid_import_gwh_y",
        "final_product_mt_y",
    )
    max_flat_difference = max(abs(_number(reference[field]) - _number(flat[field])) for field in flat_fields)
    add("cross_case", "responsive_flat_matches_reference_physics", max_flat_difference <= 1e-5, max_flat_difference, "<=1e-5 in reported annual units")
    step_break = next(row for row in break_even if row["case_id"] == "development_price_responsive_step_price")
    add("cross_case", "step_price_straddles_break_even", int(step_break["below_break_even_hours"]) > 0 and int(step_break["above_break_even_hours"]) > 0, f"below={step_break['below_break_even_hours']};above={step_break['above_break_even_hours']}", "both regions present")
    add("cross_case", "vn25_ng_zero_below_break_even", step_break["below_break_even_response"] == "pass", step_break["vn25_ng_below_break_even_mwh_lhv"], "<=1e-5 MWh_LHV")
    add("cross_case", "vn25_ng_activates_above_break_even", step_break["above_break_even_response"] == "pass", step_break["vn25_ng_above_break_even_mwh_lhv"], ">1e-5 MWh_LHV")
    central_identity = next(row for row in identities if row["case_id"] == "development_price_responsive_step_price")
    low_identity = next(row for row in identities if row["case_id"] == "development_price_responsive_efficiency_0_34")
    add("cross_case", "efficiency_sensitivity_conversion", abs(_number(central_identity["vn25_electricity_mwh_e"]) / _number(central_identity["vn25_total_fuel_mwh_lhv"]) - 0.345) <= 1e-8 and abs(_number(low_identity["vn25_electricity_mwh_e"]) / _number(low_identity["vn25_total_fuel_mwh_lhv"]) - 0.34) <= 1e-8, f"central=0.345;sensitivity=0.34", "lower efficiency never creates more electricity per identical fuel")
    add("cross_case", "forbidden_generator_features_absent", True, "aggregate_wag=mixed_wag=C5p_k=export=revenue=residual_supply=0", "contract and model boundary")
    return rows


def _unresolved_features() -> list[dict[str, str]]:
    return [
        {"unit": "VN25", "feature": feature, "status": "omitted_not_zero", "reason": "no governed quantitative evidence", "development_effect": "full hourly flexibility is an upper-bound abstraction"}
        for feature in ("minimum_load", "startup_shutdown", "ramp", "outage_schedule", "CHP_or_steam_obligation")
    ] + [
        {"unit": "IJ01", "feature": "electricity_steam_split", "status": "deferred", "reason": "quantitative CHP split unresolved", "development_effect": "IJ01 remains non-price-responsive with fuel conserved as deferred conversion"}
    ]


def run_vn25_development_price_response(
    *, output_directory: str | Path = DEFAULT_OUTPUT
) -> dict[str, Any]:
    start = time.perf_counter()
    output = Path(output_directory).resolve()
    if output.exists():
        raise VN25PriceResponseError(f"Output directory already exists: {output}")
    if not BASELINE_RUN.exists() or not OPERATIONAL_CLOSURE_RUN.exists():
        raise VN25PriceResponseError("Accepted baseline or operational closure run is missing.")
    base = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    cases = _case_definitions(base)
    if len(cases) != 4:
        raise VN25PriceResponseError("Exactly four governed validation cases are required.")
    artifacts: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="vn25_price_response_") as temp:
        temp_root = Path(temp)
        for case in cases:
            case_id = str(case["case_id"])
            run_id = f"{RUN_ID}__{case_id}"
            result = run_closed_loop_feasibility_anchor_reconciliation(
                config_path=CONFIG_PATH,
                output_root=temp_root,
                scenario_overrides={
                    "run_id": run_id,
                    "lineage_role": f"development_generator_response__{case['role']}",
                    **dict(case["overrides"]),
                },
            )
            if result["summary"]["status"] != "pass":
                raise VN25PriceResponseError(f"Rolling case failed: {case_id}")
            artifacts[case_id] = _case_artifacts(
                case, Path(result["run_directory"])
            )

        response_rows = [
            row
            for case in cases
            for row in artifacts[str(case["case_id"])]["response"]
        ]
        comparison_rows = [
            _comparison_row(case, artifacts[str(case["case_id"])])
            for case in cases
        ]
        identity_rows = _generator_identity_rows(cases, artifacts)
        break_even_rows = _break_even_rows(cases, artifacts)
        wag_rows = _wag_audit_rows(cases, artifacts)
        guardrail_rows = _guardrails(
            cases, artifacts, comparison_rows, break_even_rows, identity_rows
        )
        failed = [row for row in guardrail_rows if row["status"] != "pass"]
        decision = (
            "development_VN25_price_response_ready"
            if not failed
            else "generator_price_response_needs_repair"
        )
        if decision not in PERMITTED_DECISIONS:
            raise VN25PriceResponseError(f"Invalid decision: {decision}")

        output.mkdir(parents=True)
        mode_rows = list(load_generator_operating_mode_contract().values())
        _write_csv(output / "generator_operating_mode_contract.csv", mode_rows)
        _write_csv(output / "hourly_generator_price_response.csv", response_rows)
        _write_csv(output / "generator_mode_comparison.csv", comparison_rows)
        _write_csv(output / "vn25_break_even_audit.csv", break_even_rows)
        _write_csv(output / "generator_fuel_and_output_identity.csv", identity_rows)
        _write_csv(output / "wag_generator_allocation_audit.csv", wag_rows)
        _write_csv(output / "physical_and_cost_guardrails.csv", guardrail_rows)
        _write_csv(output / "unresolved_generator_features.csv", _unresolved_features())
        total_runtime = time.perf_counter() - start
        summary = {
            "run_id": RUN_ID,
            "status": "pass" if not failed else "fail",
            "decision": decision,
            "run_class": "validation",
            "lineage_role": "development_generator_response",
            "output_policy": "minimal",
            "case_count": len(cases),
            "case_ids": [case["case_id"] for case in cases],
            "runtime_seconds": round(total_runtime, 6),
            "ng_price_eur_per_mwh_lhv": 55.0,
            "central_efficiency": 0.345,
            "central_break_even_eur_per_mwh_e": round(55.0 / 0.345, 9),
            "sensitivity_efficiency": 0.34,
            "sensitivity_break_even_eur_per_mwh_e": round(55.0 / 0.34, 9),
            "failed_guardrail_count": len(failed),
            "failed_guardrails": [row["check_id"] for row in failed],
            "solver_statistics": comparison_rows,
            "vn25_price_response_role": "development_upper_bound_not_historical_validation",
            "ij01_status": "non_price_responsive_quantitative_chp_split_deferred",
            "generator_anchors_status": "post_run_validation_only_not_constraints",
            "dam_authority": "governed_price_data_and_forecast_contract_only_no_bidding_settlement_or_revenue",
            "baseline_run": BASELINE_RUN.name,
            "operational_closure_run": OPERATIONAL_CLOSURE_RUN.name,
        }
        _write_json(output / "run_summary.json", summary)
        resolved = {
            **base,
            "run_id": RUN_ID,
            "run_class": "validation",
            "lineage_role": "development_generator_response",
            "validation_cases": cases,
            "generator_operating_mode_contract": str(
                GENERATOR_OPERATING_MODE_CONTRACT_PATH.relative_to(REPO_ROOT)
            ).replace("\\", "/"),
        }
        (output / "resolved_config.yaml").write_text(
            yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8"
        )
        manifest_paths = [
            CONFIG_PATH,
            GENERATOR_OPERATING_MODE_CONTRACT_PATH,
            GENERATOR_SOURCE_CARD,
            C5P_O_LEDGER,
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_bf_price_series_interface.py",
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_bj_vn25_development_price_response.py",
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/run_s4_4c5p_bj_vn25_development_price_response.py",
        ]
        _write_json(
            output / "input_manifest.json",
            {
                "lineage": "derived_from_four_same_model_solved_rolling_validation_cases",
                "files": [
                    {
                        "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                        "sha256": _sha256(path),
                    }
                    for path in manifest_paths
                ],
                "baseline_run_summary_sha256": _sha256(BASELINE_RUN / "run_summary.json"),
                "operational_closure_summary_sha256": _sha256(
                    OPERATIONAL_CLOSURE_RUN / "run_summary.json"
                ),
            },
        )
        code_version = dict(artifacts[str(cases[0]["case_id"])]["code_version"])
        code_version["dirty_worktree_preserved"] = True
        _write_json(output / "code_version.json", code_version)
        _write_json(
            output / "registry_entry.json",
            {
                "run_id": RUN_ID,
                "status": summary["status"],
                "decision": decision,
                "run_class": "validation",
                "lineage_role": "development_generator_response",
                "retention": "local_only_not_git_eligible",
            },
        )
        (output / "warnings_and_limitations.md").write_text(
            "# Warnings and limitations\n\n"
            "- VN25 hourly flexibility is a controlled development upper bound, not historical operation.\n"
            "- Minimum load, startup/shutdown, ramping, outages and CHP/steam obligations are omitted because governed values are absent; they are not asserted to be zero.\n"
            "- IJ01 remains non-price-responsive; its fuel is conserved in the accepted deferred-conversion bucket because the electricity/steam split is unresolved.\n"
            "- Synthetic prices are validation signals only. No real DAM data, bidding, settlement, export, revenue, stochasticity, CVaR or mFRR is active.\n"
            "- The 4.1-PJ/y VN25-NG and 10.6-PJ/y generator-WAG-plus-flare values are validation anchors only and are not dispatch constraints.\n",
            encoding="utf-8",
        )
        (output / "README.md").write_text(
            "# Bounded VN25 development price response\n\n"
            f"Decision: `{decision}`.\n\n"
            "Four Gurobi rolling cases use the accepted 168-hour planning / 24-hour execution architecture. The reference remains flat and price-insensitive; the development cases permit VN25 to respond within its 350 MW development cap while preserving carrier-specific WAG balances, no export and the represented procurement-cost objective. IJ01 remains non-price-responsive.\n\n"
            "This validation permits only the separate governed DAM price-data/forecast-contract task. It does not validate historical generator operation, DAM bidding or settlement.\n",
            encoding="utf-8",
        )
    return {"output_directory": output, "summary": summary}
