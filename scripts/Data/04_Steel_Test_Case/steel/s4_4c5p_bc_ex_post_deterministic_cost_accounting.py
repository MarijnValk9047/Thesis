"""Ex-post deterministic procurement accounting on accepted executed blocks.

This module is intentionally read-only with respect to the physical model.  It
books governed prices against solved quantities from the accepted endogenous
rolling lineage and never constructs or solves a Pyomo model.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from steel.s4_4c_component_ontology import (
    COST_POLICY_MODES_PATH,
    EXTERNAL_SUPPLY_COSTS_PATH,
    FIXED_REFERENCE_SCENARIO_CONTRACT_PATH,
    FUTURE_COST_BOUNDARY_CONTRACT_PATH,
    PROCUREMENT_BOUNDARY_GAP_REGISTER_PATH,
    ROUTE_BOUNDARY_CONTRACT_PATH,
    load_cost_policy_modes,
    load_external_supply_costs,
    load_future_cost_boundary_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PHYSICAL_PARENT = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "runs"
    / "steel_s2_fixed_reference_procurement_physical_v1_20260716"
)
DEFAULT_OUTPUT_DIRECTORY = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "runs"
    / "steel_s2_complete_ex_post_procurement_cost_v1_20260716"
)
PHYSICAL_BUILDER_PATH = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "steel"
    / "s4_4c_unified_physical_modelbuilder.py"
)
RESULT_LABEL = "represented-boundary ex-post deterministic procurement cost"
ANNUALISATION_FACTOR = 8760.0 / 168.0
EXPECTED_CONFIGURATIONS = {
    "C0_current_BF_BOF_reference": "C0",
    "C1_phase1_BF_BOF_plus_DRP_EAF": "C1",
}
PARENT_FINGERPRINT_FILES = (
    "executed_hourly.csv",
    "rolling_execution.csv",
    "annual_physical_boundary_ledger.csv",
    "validation_checks.csv",
    "run_summary.json",
    "input_manifest.json",
    "resolved_config.yaml",
)
OUTPUT_FILES = (
    "cost_flow_ledger.csv",
    "cost_summary_by_configuration.csv",
    "cost_summary_by_component.csv",
    "cost_summary_by_route.csv",
    "excluded_cost_boundary.csv",
    "cost_validation_checks.csv",
    "input_manifest.json",
    "resolved_config.yaml",
    "code_version.json",
    "run_summary.json",
    "warnings_and_limitations.md",
    "registry_entry.json",
    "README.md",
)
TOLERANCE = 1e-6
ACTIVE_PROCUREMENT_PRICE_IDS = {
    "grid_electricity_flat_nl",
    "natural_gas_ttf_proxy",
    "coking_coal_hcc_proxy",
    "pci_coal_proxy",
    "iron_ore_62fe_proxy",
    "imported_dr_pellets_proxy",
    "purchased_scrap_proxy",
    "imported_slab_proxy",
}


class ExPostCostAccountingError(ValueError):
    """Raised when the accepted lineage or governed cost mapping fails closed."""


def _parent_run_id(parent: Path) -> str:
    """Return a stable run identifier for direct or nested run directories."""

    return parent.name


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ExPostCostAccountingError(f"Refusing to write an empty required artifact: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint_parent(parent: Path) -> tuple[str, list[dict[str, str]]]:
    files: list[dict[str, str]] = []
    combined = hashlib.sha256()
    for name in PARENT_FINGERPRINT_FILES:
        path = parent / name
        if not path.is_file():
            raise ExPostCostAccountingError(f"Accepted physical parent is missing {name}.")
        sha256 = _sha256(path)
        files.append({"path": name, "sha256": sha256})
        combined.update(name.encode("utf-8"))
        combined.update(sha256.encode("ascii"))
    return combined.hexdigest(), files


def _active_prices() -> dict[tuple[str, str], dict[str, str]]:
    rows = load_external_supply_costs()
    return {
        (row["price_id"], row["scenario_id"]): row
        for row in rows
        if row["model_use_status"] == "active_fixed_reference_procurement"
    }


def _component_for_attribute(contract_component: str, attribute: str) -> str:
    aliases = {
        "NG_to_PEFA_malerij_mwh": "PEFA_malerij",
        "NG_to_PEFA_branderij_mwh": "PEFA_branderij",
        "natural_gas_boiler_mwh": "represented_15bar_boiler",
        "VN25_NG_fuel_mwh": "VN25",
    }
    return aliases.get(attribute, contract_component)


def _validate_parent(
    parent: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any], list[dict[str, str]]]:
    summary = _read_json(parent / "run_summary.json")
    if summary.get("status") != "pass":
        raise ExPostCostAccountingError("Physical parent did not pass.")
    if summary.get("execution_mode") not in {
        "endogenous_feasibility",
        "fixed_reference_physical",
    }:
        raise ExPostCostAccountingError(
            "Reference-validation output cannot emit an economic cost result."
        )
    if summary.get("c0_rolling_status") != "pass" or summary.get("c1_rolling_status") != "pass":
        raise ExPostCostAccountingError("Accepted C0/C1 rolling statuses are not both pass.")
    if summary.get("market_prices_enabled") is not False:
        raise ExPostCostAccountingError("Physical parent is not price-free.")
    validation_rows = _read_csv(parent / "validation_checks.csv")
    if not validation_rows or any(row.get("status") != "pass" for row in validation_rows):
        raise ExPostCostAccountingError("Accepted physical guardrails are not all pass.")
    hourly_rows = _read_csv(parent / "executed_hourly.csv")
    execution_rows = _read_csv(parent / "rolling_execution.csv")
    expected_row_count = len(EXPECTED_CONFIGURATIONS) * 7 * 24
    if len(hourly_rows) != expected_row_count:
        raise ExPostCostAccountingError(
            f"Expected {expected_row_count} executed hourly rows; found {len(hourly_rows)}."
        )
    for configuration in EXPECTED_CONFIGURATIONS:
        selected = [row for row in hourly_rows if row.get("configuration_id") == configuration]
        if len(selected) != 7 * 24:
            raise ExPostCostAccountingError(
                f"{configuration} does not contain seven executed 24-hour blocks."
            )
        for replan_index in range(7):
            block = [
                row
                for row in selected
                if int(row.get("replan_index", -1)) == replan_index
            ]
            if len(block) != 24:
                raise ExPostCostAccountingError(
                    f"{configuration} replan {replan_index} is not a 24-hour executed block."
                )
            if sorted(int(row["hour_index"]) for row in block) != list(range(24)):
                raise ExPostCostAccountingError(
                    f"{configuration} replan {replan_index} is not the first 24 planned hours."
                )
        if sorted(int(row["executed_hour_index"]) for row in selected) != list(range(168)):
            raise ExPostCostAccountingError(
                f"{configuration} does not contain 168 unique executed hours."
            )
    if len(execution_rows) != len(EXPECTED_CONFIGURATIONS) * 7:
        raise ExPostCostAccountingError("Rolling execution register is not 2 x 7 blocks.")
    if any(int(row.get("execution_hours", 0)) != 24 for row in execution_rows):
        raise ExPostCostAccountingError("Rolling execution register contains a non-24-hour block.")
    return hourly_rows, execution_rows, summary, validation_rows


def _accounting_contracts() -> list[dict[str, str]]:
    rows = [
        row
        for row in load_future_cost_boundary_contract()
        if row["accounting_enabled"] == "true"
    ]
    if not rows:
        raise ExPostCostAccountingError("No ex-post cost mappings are enabled.")
    grid_rows = [row for row in rows if row["carrier"] == "electricity"]
    if {row["flow_id"] for row in grid_rows} != {"C0_EL_GRID", "C1_EL_GRID"}:
        raise ExPostCostAccountingError("Only C0/C1 net grid-import flows may be priced.")
    if any(row["physical_quantity_attribute"] != "net_grid_import_mwh" for row in grid_rows):
        raise ExPostCostAccountingError("Grid price mapping is not net grid import.")
    return rows


def _build_cost_ledger(
    hourly_rows: list[dict[str, str]],
    contracts: list[dict[str, str]],
    prices: dict[tuple[str, str], dict[str, str]],
    parent_run_id: str,
) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    for row in hourly_rows:
        configuration = row["configuration_id"]
        short_configuration = EXPECTED_CONFIGURATIONS[configuration]
        applicable = [
            contract
            for contract in contracts
            if contract["configuration"] in {short_configuration, "both"}
        ]
        for contract in applicable:
            price_key = (contract["price_id"], contract["price_scenario_id"])
            if price_key not in prices:
                raise ExPostCostAccountingError(
                    f"Active price is missing for cost flow {contract['flow_id']}."
                )
            price_row = prices[price_key]
            if contract["price_unit"] != price_row["unit"]:
                raise ExPostCostAccountingError(
                    f"Quantity/price contract mismatch for {contract['flow_id']}."
                )
            attributes = contract["physical_quantity_attribute"].split(";")
            for attribute in attributes:
                if attribute not in row:
                    raise ExPostCostAccountingError(
                        f"Required executed flow is missing: {contract['flow_id']}/{attribute}."
                    )
                quantity = float(row[attribute] or 0.0)
                if quantity < -TOLERANCE:
                    raise ExPostCostAccountingError(
                        f"External purchase is negative: {contract['flow_id']}/{attribute}."
                    )
                quantity = 0.0 if abs(quantity) <= TOLERANCE else quantity
                price = float(price_row["value"])
                ledger.append(
                    {
                        "configuration": configuration,
                        "execution_block": int(row["replan_index"]),
                        "timestamp_or_hour": int(row["executed_hour_index"]),
                        "flow_id": contract["flow_id"],
                        "component": _component_for_attribute(contract["component"], attribute),
                        "cost_route": contract["cost_route"],
                        "carrier_or_material": contract["carrier"],
                        "solved_quantity": round(quantity, 9),
                        "quantity_unit": contract["physical_unit"],
                        "price_id": contract["price_id"],
                        "scenario_id": contract["price_scenario_id"],
                        "price": price,
                        "price_unit": contract["price_unit"],
                        "cost_eur": round(quantity * price, 9),
                        "cost_status": "priced_ex_post_executed_quantity",
                        "parent_physical_run": parent_run_id,
                        "caveat": contract["caveat"],
                    }
                )
    return ledger


def _physical_boundary_values(
    parent: Path,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, str]]]:
    rows = _read_csv(parent / "annual_physical_boundary_ledger.csv")
    values: dict[str, dict[str, float]] = defaultdict(dict)
    units: dict[str, dict[str, str]] = defaultdict(dict)
    targets = {
        "full_site_anchor_minus_represented_gross": "electricity",
        "full_site_anchor_minus_named_NG": "natural_gas",
    }
    for row in rows:
        key = targets.get(row.get("component", ""))
        configuration = row.get("configuration_id", "")
        if key and configuration in EXPECTED_CONFIGURATIONS:
            values[configuration][key] = float(row["annual_value"])
            units[configuration][key] = row["unit"]
    for configuration in EXPECTED_CONFIGURATIONS:
        if set(values[configuration]) != set(targets.values()):
            raise ExPostCostAccountingError(
                f"Residual reporting quantities are incomplete for {configuration}."
            )
    return values, units


def _summaries(
    hourly_rows: list[dict[str, str]],
    ledger: list[dict[str, Any]],
    parent: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    residuals, residual_units = _physical_boundary_values(parent)
    configuration_rows: list[dict[str, Any]] = []
    component_rows: list[dict[str, Any]] = []
    for configuration in EXPECTED_CONFIGURATIONS:
        physical = [row for row in hourly_rows if row["configuration_id"] == configuration]
        costs = [row for row in ledger if row["configuration"] == configuration]
        grid_cost = sum(
            float(row["cost_eur"])
            for row in costs
            if row["price_id"] == "grid_electricity_flat_nl"
        )
        named_ng_cost = sum(
            float(row["cost_eur"])
            for row in costs
            if row["price_id"] == "natural_gas_ttf_proxy"
        )
        slab_cost = sum(
            float(row["cost_eur"])
            for row in costs
            if row["price_id"] == "imported_slab_proxy"
        )
        material_costs = {
            price_id: sum(
                float(row["cost_eur"])
                for row in costs
                if row["price_id"] == price_id
            )
            for price_id in {
                "coking_coal_hcc_proxy",
                "pci_coal_proxy",
                "iron_ore_62fe_proxy",
                "imported_dr_pellets_proxy",
                "purchased_scrap_proxy",
            }
        }
        total = sum(float(row["cost_eur"]) for row in costs)
        final_product = sum(float(row["final_product_output_t"]) for row in physical)
        internal_generation = sum(float(row["generator_electricity_mwh"]) for row in physical)
        configuration_rows.append(
            {
                "configuration": configuration,
                "result_label": RESULT_LABEL,
                "represented_grid_cost_eur": round(grid_cost, 6),
                "represented_named_ng_cost_eur": round(named_ng_cost, 6),
                "imported_slab_cost_eur": round(slab_cost, 6),
                "purchased_coking_coal_cost_eur": round(
                    material_costs["coking_coal_hcc_proxy"], 6
                ),
                "purchased_pci_cost_eur": round(
                    material_costs["pci_coal_proxy"], 6
                ),
                "purchased_iron_ore_cost_eur": round(
                    material_costs["iron_ore_62fe_proxy"], 6
                ),
                "purchased_dr_pellet_cost_eur": round(
                    material_costs["imported_dr_pellets_proxy"], 6
                ),
                "purchased_scrap_cost_eur": round(
                    material_costs["purchased_scrap_proxy"], 6
                ),
                "total_represented_procurement_cost_eur": round(total, 6),
                "executed_final_product_t": round(final_product, 6),
                "represented_cost_eur_per_t_final_product": round(total / final_product, 9),
                "annualised_cost_eur_y": round(total * ANNUALISATION_FACTOR, 6),
                "excluded_residual_electricity_quantity": residuals[configuration]["electricity"],
                "excluded_residual_electricity_unit": residual_units[configuration]["electricity"],
                "excluded_residual_ng_quantity": residuals[configuration]["natural_gas"],
                "excluded_residual_ng_unit": residual_units[configuration]["natural_gas"],
                "internal_generation_offset_mwh": round(internal_generation, 6),
                "route_cost_coverage_status": "adequate_represented_major_inputs_with_explicit_scope_gaps",
            }
        )
        grouped: dict[tuple[str, str, str, str, str], dict[str, float]] = defaultdict(
            lambda: {"quantity": 0.0, "cost": 0.0}
        )
        for row in costs:
            key = (
                row["flow_id"],
                row["component"],
                row["carrier_or_material"],
                row["quantity_unit"],
                row["price_id"],
            )
            grouped[key]["quantity"] += float(row["solved_quantity"])
            grouped[key]["cost"] += float(row["cost_eur"])
        for key, totals in sorted(grouped.items()):
            flow_id, component, carrier, quantity_unit, price_id = key
            component_rows.append(
                {
                    "configuration": configuration,
                    "flow_id": flow_id,
                    "component": component,
                    "carrier_or_material": carrier,
                    "executed_quantity": round(totals["quantity"], 9),
                    "quantity_unit": quantity_unit,
                    "price_id": price_id,
                    "cost_eur": round(totals["cost"], 6),
                    "result_label": RESULT_LABEL,
                }
            )
    return configuration_rows, component_rows


def _route_summaries(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"cost": 0.0}
    )
    for row in ledger:
        grouped[(row["configuration"], row["cost_route"])]["cost"] += float(
            row["cost_eur"]
        )
    return [
        {
            "configuration": configuration,
            "cost_route": route,
            "cost_eur": round(values["cost"], 6),
            "result_label": RESULT_LABEL,
        }
        for (configuration, route), values in sorted(grouped.items())
    ]


def _excluded_rows(
    parent: Path,
    contracts: list[dict[str, str]],
) -> list[dict[str, Any]]:
    excluded: list[dict[str, Any]] = []
    for row in load_future_cost_boundary_contract():
        if row["accounting_enabled"] == "false":
            excluded.append(
                {
                    "configuration": row["configuration"],
                    "flow_id": row["flow_id"],
                    "component": row["component"],
                    "carrier_or_material": row["carrier"],
                    "physical_quantity_attribute": row["physical_quantity_attribute"],
                    "cost_eur": 0.0,
                    "cost_status": "excluded",
                    "exclusion_reason": row["deferred_reason"],
                    "cost_readiness_status": row["cost_readiness_status"],
                    "parent_physical_run": _parent_run_id(parent),
                }
            )
    for row in _read_csv(parent / "annual_physical_boundary_ledger.csv"):
        if row.get("flow_role") == "boundary_gap" and row.get("carrier_or_material") in {
            "electricity",
            "NG",
        }:
            excluded.append(
                {
                    "configuration": row["configuration_id"],
                    "flow_id": "PHYSICAL_REPORTING_BOUNDARY_GAP",
                    "component": row["component"],
                    "carrier_or_material": row["carrier_or_material"],
                    "physical_quantity_attribute": row["annual_value"] + " " + row["unit"],
                    "cost_eur": 0.0,
                    "cost_status": "excluded_residual_reporting_quantity",
                    "exclusion_reason": "residual_is_reporting_gap_not_input",
                    "cost_readiness_status": "excluded_residual",
                    "parent_physical_run": _parent_run_id(parent),
                }
            )
    return excluded


def _validation_checks(
    *,
    hourly_rows: list[dict[str, str]],
    execution_rows: list[dict[str, str]],
    ledger: list[dict[str, Any]],
    configuration_rows: list[dict[str, Any]],
    component_rows: list[dict[str, Any]],
    route_rows: list[dict[str, Any]],
    contracts: list[dict[str, str]],
    prices: dict[tuple[str, str], dict[str, str]],
    policies: dict[str, dict[str, str]],
    parent_validation_rows: list[dict[str, str]],
    fingerprint_before: str,
    fingerprint_after: str,
) -> list[dict[str, str]]:
    priced_ids = {row["flow_id"] for row in ledger}
    grid_ledger = [
        row for row in ledger if row["price_id"] == "grid_electricity_flat_nl"
    ]
    named_ng_ledger = [
        row for row in ledger if row["price_id"] == "natural_gas_ttf_proxy"
    ]
    slab_ledger = [row for row in ledger if row["price_id"] == "imported_slab_proxy"]
    source_by_key = {
        (row["configuration_id"], int(row["executed_hour_index"])): row
        for row in hourly_rows
    }
    grid_identity = max(
        (
            abs(
                float(row["solved_quantity"])
                - float(source_by_key[(row["configuration"], int(row["timestamp_or_hour"]))]["net_grid_import_mwh"])
            )
            for row in grid_ledger
        ),
        default=float("inf"),
    )
    expected_named_ng_keys: set[tuple[str, int, str]] = set()
    for contract in contracts:
        if contract["price_id"] != "natural_gas_ttf_proxy":
            continue
        configurations = [
            configuration
            for configuration, short in EXPECTED_CONFIGURATIONS.items()
            if contract["configuration"] in {short, "both"}
        ]
        for configuration in configurations:
            for hour in range(168):
                for attribute in contract["physical_quantity_attribute"].split(";"):
                    expected_named_ng_keys.add((configuration, hour, attribute))
    actual_named_ng_keys = {
        (
            row["configuration"],
            int(row["timestamp_or_hour"]),
            next(
                attribute
                for contract in contracts
                if contract["flow_id"] == row["flow_id"]
                for attribute in contract["physical_quantity_attribute"].split(";")
                if _component_for_attribute(contract["component"], attribute) == row["component"]
            ),
        )
        for row in named_ng_ledger
    }
    slab_actual = sum(float(row["solved_quantity"]) for row in slab_ledger)
    physical_slab = sum(
        float(row["C1_imported_slab_to_HSM_t_h"])
        for row in hourly_rows
        if row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"
    )
    component_costs = defaultdict(float)
    for row in component_rows:
        component_costs[row["configuration"]] += float(row["cost_eur"])
    summary_costs = {
        row["configuration"]: float(row["total_represented_procurement_cost_eur"])
        for row in configuration_rows
    }
    route_costs = defaultdict(float)
    for row in route_rows:
        route_costs[row["configuration"]] += float(row["cost_eur"])
    active_price_status = all(
        price["scenario_id"] == "development_central"
        and price["model_use_status"] == "active_fixed_reference_procurement"
        for price in prices.values()
    ) and {price["price_id"] for price in prices.values()} == ACTIVE_PROCUREMENT_PRICE_IDS
    required_disabled = all(
        row["policy_value"] == "false"
        for policy_id, row in policies.items()
        if policy_id
        in {
            "product_revenue_enabled",
            "internal_wag_price_enabled",
            "mixed_or_aggregate_wag_price_enabled",
            "steam_price_enabled",
            "generator_export_revenue_enabled",
            "residual_electricity_cost_enabled",
            "residual_ng_cost_enabled",
            "ets_in_base_objective",
            "free_allocation_enabled",
            "cbam_enabled",
            "reference_bands_enabled_in_economic_mode",
        }
    )
    checks: list[tuple[str, bool, str]] = [
        ("grid_cost_uses_net_grid_import_only", grid_identity <= TOLERANCE, f"max_abs_residual={grid_identity}"),
        (
            "gross_and_named_electricity_buckets_not_priced",
            priced_ids.isdisjoint(
                {
                    row["flow_id"]
                    for row in load_future_cost_boundary_contract()
                    if row["carrier"] == "electricity" and row["flow_id"] not in {"C0_EL_GRID", "C1_EL_GRID"}
                }
            ),
            "only C0_EL_GRID and C1_EL_GRID are priced",
        ),
        (
            "named_ng_consumers_counted_exactly_once",
            actual_named_ng_keys == expected_named_ng_keys
            and len(actual_named_ng_keys) == len(named_ng_ledger),
            f"expected_keys={len(expected_named_ng_keys)} actual_rows={len(named_ng_ledger)}",
        ),
        (
            "residual_electricity_and_ng_zero_cost",
            not any("RESIDUAL" in flow_id for flow_id in priced_ids),
            "residual flows absent from cost ledger",
        ),
        (
            "wag_steam_internal_generation_zero_direct_cost",
            not any(
                row["carrier_or_material"] in {"BFG", "COG", "BOFG", "WAG", "WAG_and_NG", "steam"}
                for row in ledger
            ),
            "no internal carrier price mappings",
        ),
        (
            "imported_slab_actual_not_cap",
            abs(slab_actual - physical_slab) <= TOLERANCE,
            f"ledger_t={slab_actual} executed_t={physical_slab}",
        ),
        (
            "imported_slab_zero_upstream_burdens",
            all(row["flow_id"] == "C1_MAT_IMPORTED_SLAB" for row in slab_ledger)
            and all(row["carrier_or_material"] == "imported_slab" for row in slab_ledger),
            "slab is priced only at governed HSM delivery boundary",
        ),
        (
            "scenario_triplets_exist_central_only_active",
            active_price_status
            and all(
                len(
                    [
                        row
                        for row in load_external_supply_costs()
                        if row["price_id"] == price_id
                    ]
                )
                == 3
                for price_id in ACTIVE_PROCUREMENT_PRICE_IDS
            ),
            "three scenarios per active family and only central active",
        ),
        (
            "active_quantity_price_units_compatible",
            all(row["unit_compatibility_status"] == "compatible" for row in contracts),
            "contract validation passed",
        ),
        (
            "component_costs_equal_configuration_totals",
            all(
                abs(component_costs[configuration] - total) <= TOLERANCE
                for configuration, total in summary_costs.items()
            ),
            "component and configuration ledgers reconcile",
        ),
        (
            "route_costs_equal_configuration_totals",
            all(
                abs(route_costs[configuration] - total) <= TOLERANCE
                for configuration, total in summary_costs.items()
            ),
            "route and configuration ledgers reconcile",
        ),
        (
            "all_enabled_procurement_flows_are_booked",
            priced_ids == {row["flow_id"] for row in contracts},
            f"priced_flows={len(priced_ids)} enabled_contract_flows={len({row['flow_id'] for row in contracts})}",
        ),
        (
            "c0_c1_reported_separately",
            set(summary_costs) == set(EXPECTED_CONFIGURATIONS),
            "two configuration summaries",
        ),
        (
            "only_executed_24h_blocks_booked",
            len(execution_rows) == 14
            and all(int(row["execution_hours"]) == 24 for row in execution_rows),
            "7 x 24h per configuration",
        ),
        (
            "overlapping_168h_plans_not_summed",
            all(
                len(
                    {
                        int(row["timestamp_or_hour"])
                        for row in ledger
                        if row["configuration"] == configuration
                        and row["flow_id"] in {"C0_EL_GRID", "C1_EL_GRID"}
                    }
                )
                == 168
                for configuration in EXPECTED_CONFIGURATIONS
            ),
            "unique executed hours 0..167 only",
        ),
        (
            "reference_validation_cannot_emit_cost",
            policies["physical_parent_execution_mode"]["policy_value"]
            == "fixed_reference_physical",
            "parent execution mode accepted before ledger construction",
        ),
        (
            "physical_builder_constraints_objective_unchanged",
            policies["physical_builder_mutation_enabled"]["policy_value"] == "false",
            "accounting module does not import builder or solver",
        ),
        (
            "prices_not_hardcoded_in_accounting_module",
            all(row["price"] == float(prices[(row["price_id"], row["scenario_id"])]["value"]) for row in ledger),
            "all prices resolved from c5_external_supply_costs.csv",
        ),
        (
            "accepted_physical_guardrails_and_fingerprint_unchanged",
            all(row.get("status") == "pass" for row in parent_validation_rows)
            and fingerprint_before == fingerprint_after,
            f"parent_fingerprint={fingerprint_after}",
        ),
        (
            "cost_policy_fail_closed",
            required_disabled,
            "objective revenue residual ETS and reference-band policies disabled",
        ),
    ]
    return [
        {
            "check_id": check_id,
            "status": "pass" if passed else "fail",
            "evidence": evidence,
        }
        for check_id, passed, evidence in checks
    ]


def run_ex_post_cost_accounting(
    *,
    parent_run_directory: str | Path = DEFAULT_PHYSICAL_PARENT,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
) -> dict[str, Any]:
    """Book governed central prices against accepted executed physical flows."""

    parent = Path(parent_run_directory).resolve()
    output = Path(output_directory).resolve()
    if output.exists():
        raise ExPostCostAccountingError(f"Output directory already exists: {output}")
    fingerprint_before, parent_files = _fingerprint_parent(parent)
    builder_sha256_before = _sha256(PHYSICAL_BUILDER_PATH)
    hourly_rows, execution_rows, parent_summary, parent_validation_rows = _validate_parent(parent)
    policies = load_cost_policy_modes()
    prices = _active_prices()
    contracts = _accounting_contracts()
    parent_run_id = _parent_run_id(parent)
    ledger = _build_cost_ledger(hourly_rows, contracts, prices, parent_run_id)
    configuration_rows, component_rows = _summaries(hourly_rows, ledger, parent)
    route_rows = _route_summaries(ledger)
    excluded_rows = _excluded_rows(parent, contracts)
    fingerprint_after, parent_files_after = _fingerprint_parent(parent)
    builder_sha256_after = _sha256(PHYSICAL_BUILDER_PATH)
    checks = _validation_checks(
        hourly_rows=hourly_rows,
        execution_rows=execution_rows,
        ledger=ledger,
        configuration_rows=configuration_rows,
        component_rows=component_rows,
        route_rows=route_rows,
        contracts=contracts,
        prices=prices,
        policies=policies,
        parent_validation_rows=parent_validation_rows,
        fingerprint_before=fingerprint_before,
        fingerprint_after=fingerprint_after,
    )
    if parent_files != parent_files_after or builder_sha256_before != builder_sha256_after:
        raise ExPostCostAccountingError("Physical lineage changed during cost accounting.")
    status = "pass" if all(row["status"] == "pass" for row in checks) else "fail"
    output.mkdir(parents=True)
    _write_csv(output / "cost_flow_ledger.csv", ledger)
    _write_csv(output / "cost_summary_by_configuration.csv", configuration_rows)
    _write_csv(output / "cost_summary_by_component.csv", component_rows)
    _write_csv(output / "cost_summary_by_route.csv", route_rows)
    _write_csv(output / "excluded_cost_boundary.csv", excluded_rows)
    _write_csv(output / "cost_validation_checks.csv", checks)
    manifest = {
        "run_id": output.name,
        "run_class": "complete_ex_post_procurement_cost",
        "lineage_role": "derived_from_fixed_reference_procurement_physical_lineage",
        "output_policy": "minimal",
        "physical_parent": parent_run_id,
        "physical_parent_fingerprint_sha256": fingerprint_after,
        "physical_parent_files": parent_files_after,
        "physical_builder_path": str(PHYSICAL_BUILDER_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
        "physical_builder_sha256": builder_sha256_after,
        "governed_cost_inputs": [
            {
                "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "sha256": _sha256(path),
            }
            for path in (
                EXTERNAL_SUPPLY_COSTS_PATH,
                COST_POLICY_MODES_PATH,
                FUTURE_COST_BOUNDARY_CONTRACT_PATH,
                FIXED_REFERENCE_SCENARIO_CONTRACT_PATH,
                ROUTE_BOUNDARY_CONTRACT_PATH,
                PROCUREMENT_BOUNDARY_GAP_REGISTER_PATH,
            )
        ],
    }
    _write_json(output / "input_manifest.json", manifest)
    resolved_config = {
        "run_id": output.name,
        "physical_parent": parent_run_id,
        "accounting_mode": "complete_ex_post_procurement_cost",
        "price_scenario": "development_central",
        "executed_hours_per_configuration": 168,
        "execution_blocks_per_configuration": 7,
        "output_policy": "minimal",
        "solver_invoked": False,
        "cost_objective_enabled": False,
    }
    (output / "resolved_config.yaml").write_text(
        json.dumps(resolved_config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    parent_code_version = _read_json(parent / "code_version.json")
    _write_json(
        output / "code_version.json",
        {
            "git_commit": parent_code_version.get("git_commit"),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "accounting_module_sha256": _sha256(Path(__file__)),
        },
    )
    summary = {
        "run_id": output.name,
        "status": status,
        "result_label": RESULT_LABEL,
        "run_class": "complete_ex_post_procurement_cost",
        "lineage_role": "derived_from_fixed_reference_procurement_physical_lineage",
        "output_policy": "minimal",
        "physical_parent": parent_run_id,
        "physical_parent_status": parent_summary["status"],
        "physical_parent_execution_mode": parent_summary["execution_mode"],
        "physical_parent_fingerprint_sha256": fingerprint_after,
        "physical_builder_sha256": builder_sha256_after,
        "solver_invoked": False,
        "cost_objective_enabled": False,
        "dispatch_or_route_changed": False,
        "executed_hours_per_configuration": 168,
        "execution_blocks_per_configuration": 7,
        "accounting_price_scenarios": {
            price_id: scenario_id for price_id, scenario_id in sorted(prices)
        },
        "configuration_results": configuration_rows,
        "validation_checks_passed": sum(row["status"] == "pass" for row in checks),
        "validation_checks_total": len(checks),
        "active_procurement_price_count": len(prices),
        "priced_flow_count": len({row["flow_id"] for row in ledger}),
        "route_cost_coverage_status": "adequate_represented_major_inputs_with_explicit_scope_gaps",
        "full_procurement_cost_objective_activation": "READY_NOT_ACTIVE",
        "next_gate": "fixed_reference_lexicographic_procurement_cost_optimisation",
    }
    _write_json(output / "run_summary.json", summary)
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is ex-post accounting on solved executed blocks; no cost objective is active.\n"
        "- Costs cover represented external grid electricity, named NG, coking coal, PCI, "
        "sinter/PEFA ore, imported DR pellets, purchased scrap and imported slab.\n"
        "- BF pellets and HBI remain explicit unrepresented scope gaps and receive no zero-cost plug.\n"
        "- Residual electricity and NG are reporting gaps, never purchased inputs.\n"
        "- Internal BFG, COG, BOFG, steam and electricity generation have no transfer price.\n"
        "- No revenue, ETS, CBAM, market bidding or whole-site cost claim is included.\n",
        encoding="utf-8",
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": output.name,
            "run_class": "complete_ex_post_procurement_cost",
            "lineage_role": "derived_from_fixed_reference_procurement_physical_lineage",
            "output_policy": "minimal",
            "status": status,
        },
    )
    (output / "README.md").write_text(
        f"# {output.name}\n\n"
        f"- Result label: {RESULT_LABEL}\n"
        "- Status: " + status + "\n"
        "- Run class: complete_ex_post_procurement_cost\n"
        "- Lineage role: derived_from_fixed_reference_procurement_physical_lineage\n"
        "- Output policy: minimal\n"
        f"- Physical parent: {parent_run_id}\n"
        "- Booking basis: first 24 executed hours from each of seven replans; "
        "overlapping 168-hour plans are not summed.\n"
        "- Priced: represented net grid import, represented named NG by consumer, "
        "coking coal, PCI, sinter/PEFA ore, DR pellets, purchased scrap and actual "
        "imported slab delivered to HSM.\n"
        "- Excluded: gross/named electricity buckets, residual electricity/NG, "
        "BFG/COG/BOFG, steam, internal generation, internal inventory, product "
        "output, unrepresented BF pellets/HBI and ETS.\n"
        "- Solver and cost objective: not invoked / disabled.\n"
        "- Route-cost coverage: adequate for represented major inputs, with explicit scope gaps.\n"
        "- Next gate: fixed-reference lexicographic procurement-cost optimisation.\n",
        encoding="utf-8",
    )
    if set(path.name for path in output.iterdir()) != set(OUTPUT_FILES):
        raise ExPostCostAccountingError("Unexpected run artifacts were generated.")
    return {"run_directory": output, "summary": summary}
