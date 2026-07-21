"""Small C5 adapter for the existing S4.4b2 PyPSA-inspired component registry.

This is deliberately not a second ontology.  It adds only the operational
classification needed by the active C5 Pyomo builder and preserves the S4.4b2
component registry as the authoritative topology record.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
S4_ASSET_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4"
COMPONENT_REGISTRY_PATH = S4_ASSET_ROOT / "s4_4b2_physical_master_workbook" / "compiled_review" / "config_components.csv"
ONTOLOGY_DIR = S4_ASSET_ROOT / "c5_component_ontology"
OVERRIDE_PATH = ONTOLOGY_DIR / "c5_builder_operation_class_overrides.csv"
ROUTE_SCENARIO_PATH = ONTOLOGY_DIR / "c1_liquid_steel_route_policy_scenarios.csv"
ROUTE_BOUNDARY_CONTRACT_PATH = ONTOLOGY_DIR / "c5_route_boundary_contract.csv"
FUTURE_COST_BOUNDARY_CONTRACT_PATH = ONTOLOGY_DIR / "c5_future_cost_boundary_contract.csv"
EXTERNAL_SUPPLY_COSTS_PATH = ONTOLOGY_DIR / "c5_external_supply_costs.csv"
COST_POLICY_MODES_PATH = ONTOLOGY_DIR / "c5_cost_policy_modes.csv"
FIXED_REFERENCE_SCENARIO_CONTRACT_PATH = (
    ONTOLOGY_DIR / "c5_fixed_reference_scenario_contract.csv"
)
PROCUREMENT_BOUNDARY_GAP_REGISTER_PATH = (
    ONTOLOGY_DIR / "c5_procurement_boundary_gap_register.csv"
)
GENERATOR_OPERATING_MODE_CONTRACT_PATH = (
    ONTOLOGY_DIR / "c5_generator_operating_mode_contract.csv"
)

BUILDER_TO_REGISTRY_CONFIGURATION = {
    "C0_current_BF_BOF_reference": "C0_current_BF_BOF_reference",
    "C1_phase1_BF_BOF_plus_DRP_EAF": "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
}
ALLOWED_OPERATION_CLASSES = {
    "continuous_must_run",
    "batch_equivalent",
    "bounded_downstream",
    "route_interface",
    "utility_following",
    "reporting_only",
}
ALLOWED_COST_PARAMETER_STATUSES = {
    "source_backed_central",
    "boundary_reconciled_development",
    "accepted_development",
    "sensitivity_only",
    "blocked",
    "not_in_first_cost_layer",
}
FUTURE_DETERMINISTIC_COST_RESULT_FIELDS = (
    "electricity_cost_eur",
    "natural_gas_cost_eur",
    "coking_coal_cost_eur",
    "pci_cost_eur",
    "iron_ore_cost_eur",
    "dr_pellet_cost_eur",
    "purchased_scrap_cost_eur",
    "imported_slab_cost_eur",
    "total_represented_energy_cost_eur",
    "total_represented_procurement_cost_eur",
    "represented_energy_cost_eur_per_t_final_product",
    "represented_procurement_cost_eur_per_t_final_product",
    "cost_by_component_eur",
    "cost_by_carrier_eur",
    "cost_by_route_eur",
    "residual_electricity_mwh_excluded_from_cost",
    "residual_natural_gas_mwh_lhv_excluded_from_cost",
    "internal_generation_offset_mwh",
    "solver_status",
    "termination_condition",
    "objective_value",
    "runtime_seconds",
    "mip_gap",
    "variable_count",
    "binary_count",
    "constraint_count",
)


class ComponentOntologyError(ValueError):
    """Raised when a C5 operation-class override conflicts with topology."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_builder_component_ontology() -> list[dict[str, str]]:
    """Return operation classes after checking each override against S4.4b2."""

    registry_rows = _read_csv(COMPONENT_REGISTRY_PATH)
    overrides = _read_csv(OVERRIDE_PATH)
    active_registry = {
        (row["configuration_id"], row["component_id"])
        for row in registry_rows
        if row.get("active", "").strip().lower() == "true"
    }
    seen: set[tuple[str, str]] = set()
    resolved: list[dict[str, str]] = []
    for row in overrides:
        key = (row.get("configuration_id", ""), row.get("asset_id", ""))
        if key in seen:
            raise ComponentOntologyError(f"Duplicate C5 operation-class override: {key}")
        seen.add(key)
        if row.get("operation_class") not in ALLOWED_OPERATION_CLASSES:
            raise ComponentOntologyError(f"Unsupported operation class for {key}: {row.get('operation_class')}")
        registry_configuration = BUILDER_TO_REGISTRY_CONFIGURATION.get(key[0], key[0])
        if (registry_configuration, key[1]) not in active_registry:
            raise ComponentOntologyError(
                f"C5 override is not an active S4.4b2 component: {registry_configuration}/{key[1]}"
            )
        if row.get("active_builder_scope") == "yes" and not row.get("builder_activity_name"):
            raise ComponentOntologyError(f"Active builder scope needs a builder activity name: {key}")
        resolved.append({**row, "registry_configuration_id": registry_configuration})
    return resolved


def continuous_must_run_activities(configuration_id: str) -> tuple[str, ...]:
    """Return only source-classified continuous activities represented by C5."""

    rows = load_builder_component_ontology()
    return tuple(
        row["builder_activity_name"]
        for row in rows
        if row.get("configuration_id") == configuration_id
        and row.get("active_builder_scope") == "yes"
        and row.get("operation_class") == "continuous_must_run"
        and row.get("enforcement") == "fix_on_over_horizon"
    )


def load_route_policy_scenarios() -> list[dict[str, Any]]:
    """Load bounded diagnostic scenarios; no scenario is a global default."""

    rows = _read_csv(ROUTE_SCENARIO_PATH)
    for row in rows:
        for field in ("bof_lower_share", "bof_upper_share"):
            if row.get(field):
                row[field] = float(row[field])
        for field in ("hdri_t_per_t_liquid_steel", "scrap_t_per_t_liquid_steel", "annual_scrap_supply_t_y"):
            if row.get(field):
                row[field] = float(row[field])
    return rows


def load_route_boundary_contract() -> list[dict[str, str]]:
    """Load the governed C0/C1 route and denominator contract."""

    rows = _read_csv(ROUTE_BOUNDARY_CONTRACT_PATH)
    required = {
        "route_id",
        "configuration",
        "process",
        "input_carrier_material",
        "output_carrier_material",
        "input_unit",
        "output_unit",
        "conversion_factor",
        "capacity_basis",
        "operating_class",
        "origin_tag",
        "reference_mode_rule",
        "endogenous_mode_rule",
        "activity_driver",
        "source_evidence_status",
        "cost_design_inclusion_status",
        "caveat",
    }
    if not rows or not required.issubset(rows[0]):
        raise ComponentOntologyError("C5 route-boundary contract is missing required fields.")
    seen: set[str] = set()
    for row in rows:
        route_id = row.get("route_id", "")
        if not route_id or route_id in seen:
            raise ComponentOntologyError(f"Duplicate or empty route-boundary id: {route_id}")
        seen.add(route_id)
        if row.get("configuration") not in {"C0", "C1"}:
            raise ComponentOntologyError(f"Unsupported route configuration: {row.get('configuration')}")
        if row.get("operating_class") not in ALLOWED_OPERATION_CLASSES:
            raise ComponentOntologyError(
                f"Unsupported route operating class for {route_id}: {row.get('operating_class')}"
            )
        if row.get("source_evidence_status") not in ALLOWED_COST_PARAMETER_STATUSES:
            raise ComponentOntologyError(
                f"Unsupported route evidence status for {route_id}: {row.get('source_evidence_status')}"
            )
        if not all(row.get(field, "").strip() for field in required - {"caveat"}):
            raise ComponentOntologyError(f"Incomplete route-boundary row: {route_id}")
        if "band" in row.get("endogenous_mode_rule", "").lower():
            raise ComponentOntologyError(
                f"Endogenous route rule must not inherit a reference band: {route_id}"
            )
    return rows


def load_fixed_reference_scenario_contract(
    scenario_id: str | None = None,
) -> list[dict[str, str]]:
    """Load cumulative fixed-reference definitions without creating hourly profiles."""

    rows = _read_csv(FIXED_REFERENCE_SCENARIO_CONTRACT_PATH)
    required = {
        "scenario_id",
        "configuration",
        "metric",
        "raw_source_value_mt_y",
        "active_central_mt_y",
        "annual_lower_mt_y",
        "annual_upper_mt_y",
        "band_relative_tolerance",
        "physical_quantity_attribute",
        "model_expression",
        "scenario_definition_status",
        "constraint_status",
        "independent_validation_status",
        "reporting_context_status",
        "source_status",
        "source_locator",
        "unit",
        "caveat",
    }
    if not rows or not required.issubset(rows[0]):
        raise ComponentOntologyError(
            "C5 fixed-reference scenario contract is missing required fields."
        )
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (
            row.get("scenario_id", ""),
            row.get("configuration", ""),
            row.get("metric", ""),
        )
        if not all(key) or key in seen:
            raise ComponentOntologyError(
                f"Duplicate or empty fixed-reference scenario row: {key}"
            )
        seen.add(key)
        if row["configuration"] not in {"C0", "C1"}:
            raise ComponentOntologyError(
                f"Unsupported fixed-reference configuration: {key}"
            )
        if row["unit"] != "Mt/y":
            raise ComponentOntologyError(
                f"Fixed-reference annual unit must be Mt/y: {key}"
            )
        if row["source_status"] not in ALLOWED_COST_PARAMETER_STATUSES:
            raise ComponentOntologyError(
                f"Unsupported fixed-reference evidence status: {key}"
            )
        for field in ("raw_source_value_mt_y", "active_central_mt_y"):
            try:
                value = float(row[field])
            except ValueError as exc:
                raise ComponentOntologyError(
                    f"Non-numeric fixed-reference value {field}: {key}"
                ) from exc
            if value < 0.0:
                raise ComponentOntologyError(
                    f"Negative fixed-reference value {field}: {key}"
                )
        if row["constraint_status"] == "cumulative_reference_band":
            if row["scenario_definition_status"] != "scenario_definition":
                raise ComponentOntologyError(
                    f"Reference band must be a scenario definition: {key}"
                )
            if row["independent_validation_status"] != "excluded_scenario_definition":
                raise ComponentOntologyError(
                    f"Scenario definition cannot count as validation: {key}"
                )
            lower = float(row["annual_lower_mt_y"])
            central = float(row["active_central_mt_y"])
            upper = float(row["annual_upper_mt_y"])
            if not 0.0 <= lower <= central <= upper:
                raise ComponentOntologyError(
                    f"Invalid fixed-reference band ordering: {key}"
                )
    selected = rows if scenario_id is None else [
        row for row in rows if row["scenario_id"] == scenario_id
    ]
    if scenario_id is not None and not selected:
        raise ComponentOntologyError(
            f"Unknown fixed-reference scenario: {scenario_id}"
        )
    return selected


def load_future_cost_boundary_contract() -> list[dict[str, str]]:
    """Load and fail-close the deterministic cost-boundary mapping."""

    rows = _read_csv(FUTURE_COST_BOUNDARY_CONTRACT_PATH)
    required = {
        "flow_id",
        "configuration",
        "component",
        "carrier",
        "flow_direction",
        "physical_unit",
        "activity_driver",
        "physical_constraint",
        "future_price_unit",
        "future_cost_treatment",
        "internal_external",
        "source_status",
        "source_locator",
        "residual_status",
        "included_in_first_deterministic_cost_layer",
        "explicitly_deferred",
        "caveat",
        "price_id",
        "price_scenario_id",
        "objective_enabled",
        "accounting_enabled",
        "objective_mode",
        "external_purchase_status",
        "origin_status",
        "physical_quantity_attribute",
        "price_unit",
        "unit_compatibility_status",
        "double_count_group",
        "cost_readiness_status",
        "deferred_reason",
        "cost_route",
        "model_component_attribute",
    }
    if not rows or not required.issubset(rows[0]):
        raise ComponentOntologyError("C5 future-cost boundary contract is missing required fields.")
    seen: set[str] = set()
    for row in rows:
        flow_id = row.get("flow_id", "")
        if not flow_id or flow_id in seen:
            raise ComponentOntologyError(f"Duplicate or empty future-cost flow id: {flow_id}")
        seen.add(flow_id)
        if row.get("configuration") not in {"C0", "C1", "both"}:
            raise ComponentOntologyError(f"Unsupported future-cost configuration: {row.get('configuration')}")
        if row.get("source_status") not in ALLOWED_COST_PARAMETER_STATUSES:
            raise ComponentOntologyError(
                f"Unsupported cost-parameter status for {flow_id}: {row.get('source_status')}"
            )
        included = row.get("included_in_first_deterministic_cost_layer") == "yes"
        residual = row.get("residual_status") != "not_residual"
        if included and residual:
            raise ComponentOntologyError(f"Residual flow cannot enter future objective: {flow_id}")
        if included and row.get("source_status") in {"blocked", "not_in_first_cost_layer", "sensitivity_only"}:
            raise ComponentOntologyError(f"Unaccepted parameter cannot enter future objective: {flow_id}")
        if included and not all(
            row.get(field, "").strip()
            for field in ("physical_unit", "activity_driver", "physical_constraint", "future_price_unit", "source_locator")
        ):
            raise ComponentOntologyError(f"Future priced flow is missing unit/source/activity basis: {flow_id}")
        if row.get("carrier") in {"BFG", "COG", "BOFG", "WAG_and_NG"} and row.get("future_price_unit") not in {"", "not_applicable"}:
            raise ComponentOntologyError(f"WAG cannot receive a direct external price: {flow_id}")
        if row.get("objective_enabled") not in {"true", "false"}:
            raise ComponentOntologyError(f"Invalid objective flag for {flow_id}.")
        if row.get("accounting_enabled") not in {"true", "false"}:
            raise ComponentOntologyError(f"Invalid accounting flag for {flow_id}.")
        if row.get("objective_enabled") == "true" and row.get(
            "objective_mode"
        ) != "fixed_reference_procurement_cost":
            raise ComponentOntologyError(
                f"Cost objective is outside the authorised fixed-reference mode: {flow_id}"
            )
        if row.get("accounting_enabled") == "true":
            accounting_fields = {
                "price_id",
                "price_scenario_id",
                "external_purchase_status",
                "origin_status",
                "physical_quantity_attribute",
                "price_unit",
                "unit_compatibility_status",
                "double_count_group",
                "cost_readiness_status",
                "cost_route",
            }
            if not all(row.get(field, "").strip() for field in accounting_fields):
                raise ComponentOntologyError(
                    f"Ex-post cost mapping is incomplete for {flow_id}."
                )
            if residual:
                raise ComponentOntologyError(
                    f"Residual flow cannot enter ex-post accounting: {flow_id}"
                )
            if row.get("external_purchase_status") != "external_purchase":
                raise ComponentOntologyError(
                    f"Only external purchases can enter ex-post accounting: {flow_id}"
                )
            if row.get("unit_compatibility_status") != "compatible":
                raise ComponentOntologyError(
                    f"Priced flow has no compatible price unit: {flow_id}"
                )
        if row.get("objective_enabled") == "true" and row.get(
            "accounting_enabled"
        ) != "true":
            raise ComponentOntologyError(
                f"Objective flow must also support ex-post accounting: {flow_id}"
            )
        if row.get("objective_enabled") == "true" and not row.get(
            "model_component_attribute", ""
        ).strip():
            raise ComponentOntologyError(
                f"Objective flow has no model-component mapping: {flow_id}"
            )
    return rows


def load_external_supply_costs() -> list[dict[str, str]]:
    """Load governed price scenarios without selecting or embedding price values."""

    rows = _read_csv(EXTERNAL_SUPPLY_COSTS_PATH)
    required = {
        "price_id",
        "scenario_id",
        "carrier_or_material",
        "value",
        "unit",
        "currency",
        "price_type",
        "valid_from",
        "valid_to",
        "observation_date",
        "delivery_basis",
        "quality_basis",
        "source_title",
        "source_url",
        "source_locator",
        "source_status",
        "thesis_usability",
        "model_use_status",
        "caveat",
    }
    if not rows or not required.issubset(rows[0]):
        raise ComponentOntologyError("C5 external-supply cost input is missing required fields.")
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.get("price_id", ""), row.get("scenario_id", ""))
        if not all(key) or key in seen:
            raise ComponentOntologyError(f"Duplicate or empty price scenario: {key}")
        seen.add(key)
        if not all(row.get(field, "").strip() for field in required):
            raise ComponentOntologyError(f"Incomplete price scenario: {key}")
        try:
            value = float(row["value"])
        except ValueError as exc:
            raise ComponentOntologyError(f"Non-numeric price for {key}.") from exc
        if value < 0:
            raise ComponentOntologyError(f"Negative price is not governed for {key}.")
        if row.get("currency") != "EUR":
            raise ComponentOntologyError(f"Non-EUR executable price: {key}")
    active_ids = {
        row["price_id"]
        for row in rows
        if row.get("model_use_status") == "active_fixed_reference_procurement"
    }
    if active_ids != {
        "grid_electricity_flat_nl",
        "natural_gas_ttf_proxy",
        "coking_coal_hcc_proxy",
        "pci_coal_proxy",
        "iron_ore_62fe_proxy",
        "imported_dr_pellets_proxy",
        "purchased_scrap_proxy",
        "imported_slab_proxy",
    } or any(
        row.get("scenario_id") != "development_central"
        for row in rows
        if row.get("model_use_status") == "active_fixed_reference_procurement"
    ):
        raise ComponentOntologyError(
            "Exactly the governed central represented-procurement prices must be active."
        )
    return rows


def load_cost_policy_modes() -> dict[str, dict[str, str]]:
    """Load the fail-closed ex-post accounting policy."""

    rows = _read_csv(COST_POLICY_MODES_PATH)
    required = {
        "policy_id",
        "policy_value",
        "value_type",
        "accounting_status",
        "objective_status",
        "source_status",
        "source_locator",
        "caveat",
    }
    if not rows or not required.issubset(rows[0]):
        raise ComponentOntologyError("C5 cost-policy input is missing required fields.")
    policies: dict[str, dict[str, str]] = {}
    for row in rows:
        policy_id = row.get("policy_id", "")
        if not policy_id or policy_id in policies:
            raise ComponentOntologyError(f"Duplicate or empty cost policy: {policy_id}")
        if not all(row.get(field, "").strip() for field in required):
            raise ComponentOntologyError(f"Incomplete cost policy: {policy_id}")
        policies[policy_id] = row
    disabled = {
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
        "reference_validation_cost_output_enabled",
        "physical_builder_mutation_enabled",
    }
    for policy_id in disabled:
        if policies.get(policy_id, {}).get("policy_value") != "false":
            raise ComponentOntologyError(f"Cost policy must remain disabled: {policy_id}")
    if policies.get("ex_post_cost_accounting_enabled", {}).get("policy_value") != "true":
        raise ComponentOntologyError("Ex-post cost accounting is not enabled.")
    if policies.get("cost_objective_enabled", {}).get("policy_value") != "true":
        raise ComponentOntologyError(
            "Fixed-reference deterministic cost objective is not enabled."
        )
    if policies.get("raw_material_costs_enabled", {}).get("policy_value") != "true":
        raise ComponentOntologyError(
            "Represented raw-material procurement costs are not enabled."
        )
    if policies.get("cost_objective_scope", {}).get(
        "policy_value"
    ) != "fixed_reference_cost_only":
        raise ComponentOntologyError("Cost objective scope is not fail-closed.")
    return policies


def load_generator_operating_mode_contract() -> dict[str, dict[str, str]]:
    """Load the bounded VN25 development operating-mode contract."""

    rows = _read_csv(GENERATOR_OPERATING_MODE_CONTRACT_PATH)
    required = {
        "mode_id",
        "mode_role",
        "price_series_policy",
        "hourly_price_response",
        "vn25_electric_capacity_mw",
        "vn25_efficiency",
        "allowed_efficiencies",
        "vn25_allowed_fuels",
        "ij01_price_response",
        "export_allowed",
        "revenue_allowed",
        "minimum_load",
        "startup_shutdown",
        "ramp",
        "outage_schedule",
        "chp_steam_obligation",
        "availability_policy",
        "source_status",
        "source_locator",
        "caveat",
    }
    if not rows or not required.issubset(rows[0]):
        raise ComponentOntologyError(
            "C5 generator operating-mode contract is missing required fields."
        )
    modes: dict[str, dict[str, str]] = {}
    for row in rows:
        mode_id = row.get("mode_id", "")
        if not mode_id or mode_id in modes:
            raise ComponentOntologyError(
                f"Duplicate or empty generator operating mode: {mode_id}"
            )
        if not all(row.get(field, "").strip() for field in required):
            raise ComponentOntologyError(
                f"Incomplete generator operating mode: {mode_id}"
            )
        if float(row["vn25_electric_capacity_mw"]) != 350.0:
            raise ComponentOntologyError(
                "VN25 development electric capacity must remain 350 MW."
            )
        if row["vn25_allowed_fuels"] != "BFG;COG;BOFG;NG":
            raise ComponentOntologyError(
                "VN25 fuel eligibility must remain carrier-specific."
            )
        if any(
            row[field] != "false"
            for field in ("ij01_price_response", "export_allowed", "revenue_allowed")
        ):
            raise ComponentOntologyError(
                "IJ01 price response, export and generator revenue must remain disabled."
            )
        if any(
            row[field] != "omitted_not_zero"
            for field in (
                "minimum_load",
                "startup_shutdown",
                "ramp",
                "outage_schedule",
                "chp_steam_obligation",
            )
        ):
            raise ComponentOntologyError(
                "Missing generator operating features must be omitted, not invented as zero."
            )
        modes[mode_id] = row
    expected_modes = {
        "price_insensitive_reference",
        "development_price_responsive",
        "bounded_generator_sensitivity",
    }
    if set(modes) != expected_modes:
        raise ComponentOntologyError(
            f"Generator operating modes must be exactly {sorted(expected_modes)}."
        )
    return modes


def load_procurement_boundary_gap_register() -> list[dict[str, str]]:
    """Load explicit represented-boundary coverage and future scope gaps."""

    rows = _read_csv(PROCUREMENT_BOUNDARY_GAP_REGISTER_PATH)
    required = {
        "gap_id",
        "configuration",
        "route",
        "procurement_family",
        "active_physical_flow_status",
        "cost_coverage_status",
        "base_policy",
        "source_evidence_status",
        "source_locator",
        "blocks_fixed_reference_cost",
        "blocks_future_extension",
        "resolution_or_caveat",
    }
    if not rows or not required.issubset(rows[0]):
        raise ComponentOntologyError(
            "C5 procurement-boundary gap register is missing required fields."
        )
    seen: set[str] = set()
    for row in rows:
        gap_id = row.get("gap_id", "")
        if not gap_id or gap_id in seen:
            raise ComponentOntologyError(
                f"Duplicate or empty procurement gap id: {gap_id}"
            )
        seen.add(gap_id)
        if row.get("blocks_fixed_reference_cost") not in {"yes", "no"}:
            raise ComponentOntologyError(
                f"Invalid fixed-reference blocking status: {gap_id}"
            )
        if row.get("blocks_future_extension") not in {"yes", "no"}:
            raise ComponentOntologyError(
                f"Invalid future blocking status: {gap_id}"
            )
    if any(row["blocks_fixed_reference_cost"] == "yes" for row in rows):
        raise ComponentOntologyError(
            "A blocking procurement gap remains for the fixed-reference objective."
        )
    return rows
