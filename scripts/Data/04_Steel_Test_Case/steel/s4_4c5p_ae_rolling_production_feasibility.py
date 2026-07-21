"""Deterministic rolling-window steel production-feasibility runner.

This stage deliberately reuses the existing C0/C1 physical builder.  It adds
hard cumulative production deadlines and a governed run contract; it does not
add prices, product revenue, DA bidding, an ETS objective, or a new WAG
allocator.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .rolling_production_quota import build_rolling_production_quota_plan
from .s4_4c_component_ontology import OVERRIDE_PATH, continuous_must_run_activities
from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    _build_c0_inputs,
    _build_c1_inputs,
    _load_tables,
    run_s44c_unified_physical_regression,
)


DEFAULT_CONFIG_PATH = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "configs" / "steel_quota_driven_physical_feasibility.yaml"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
TOLERANCE_T = 1e-5
C0_CONFIGURATION_ID = "C0_current_BF_BOF_reference"
C1_CONFIGURATION_ID = "C1_phase1_BF_BOF_plus_DRP_EAF"
REQUIRED_C0_CONTINUOUS_ACTIVITIES = {
    "coking_plant_1",
    "coking_plant_2",
    "sintering_plant",
    "blast_furnace_6",
    "blast_furnace_7",
}


class RollingFeasibilityError(ValueError):
    """Raised when the rolling-feasibility configuration is inconsistent."""


def _source_coke_chain(config: dict[str, Any]) -> dict[str, float]:
    payload = config.get("source_coke_chain")
    required = {"dry_coal_t_per_t_coke", "bf_coke_t_per_t_hot_metal"}
    if not isinstance(payload, dict) or required.difference(payload):
        raise RollingFeasibilityError(
            "source_coke_chain must provide dry_coal_t_per_t_coke and bf_coke_t_per_t_hot_metal."
        )
    resolved = {key: float(payload[key]) for key in required}
    if any(value <= 0.0 for value in resolved.values()):
        raise RollingFeasibilityError("source_coke_chain values must be positive.")
    return resolved


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_config(config_path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RollingFeasibilityError("Rolling-feasibility YAML must contain a mapping.")
    required = {"run_id", "planning_horizon_hours", "execution_block_hours", "quota_per_execution_block_t"}
    missing = sorted(required.difference(payload))
    if missing:
        raise RollingFeasibilityError(f"Missing rolling-feasibility configuration fields: {missing}")
    if payload.get("market_prices_enabled") is not False:
        raise RollingFeasibilityError("The deterministic feasibility runner forbids market prices.")
    if payload.get("energy_cost_objective_enabled") is not False:
        raise RollingFeasibilityError("The deterministic feasibility runner forbids energy costs.")
    if payload.get("product_revenue_enabled") is not False or payload.get("co2_ets_objective_enabled") is not False:
        raise RollingFeasibilityError("Product revenue and ETS objectives are out of scope for this runner.")
    _source_coke_chain(payload)
    return payload


def _availability_controls(config: dict[str, Any]) -> dict[str, Any]:
    """Map an explicit availability policy to existing model controls.

    The quota-driven option deliberately fixes no plant hours and selects no
    C1 route share. Capacity, min-rate, material, WAG, steam and utility
    constraints remain the governing physical conditions.
    """
    policy = config.get("availability_policy")
    if not isinstance(policy, dict):
        raise RollingFeasibilityError("availability_policy must map C0 and C1 policies.")
    c0_policy = str(policy.get("c0", ""))
    c1_policy = str(policy.get("c1", ""))
    if c0_policy == "fixed_static_binary_schedule":
        fix_c0 = True
        commitment_granularity = "hourly_binary"
    elif c0_policy == "quota_driven_binary_capacity":
        fix_c0 = False
        commitment_granularity = "daily_binary_hourly_throughput"
    else:
        raise RollingFeasibilityError(f"Unsupported C0 availability policy: {c0_policy}")
    if c1_policy == "bottom_up_fixed_retained_route":
        fix_c1 = True
        c1_route_policy = "bottom_up_fixed_retained_route"
    elif c1_policy == "quota_driven_topology":
        fix_c1 = False
        c1_route_policy = "quota_driven_topology"
    else:
        raise RollingFeasibilityError(f"Unsupported C1 availability policy: {c1_policy}")
    return {
        "c0_policy": c0_policy,
        "c1_policy": c1_policy,
        "fix_c0_binary_schedule": fix_c0,
        "fix_c1_hybrid_schedule": fix_c1,
        "c1_retained_route_policy": c1_route_policy,
        "commitment_granularity": commitment_granularity,
    }


def _continuous_operation_activities() -> dict[str, tuple[str, ...]]:
    """Resolve the governed operation classes required by the active quota path."""

    c0_activities = continuous_must_run_activities(C0_CONFIGURATION_ID)
    if set(c0_activities) != REQUIRED_C0_CONTINUOUS_ACTIVITIES:
        raise RollingFeasibilityError(
            "The C0 component ontology must enforce exactly KGF1, KGF2, sinter, BF6 and BF7 as "
            f"continuous must-run activities; resolved={sorted(c0_activities)}"
        )
    return {
        "c0": c0_activities,
    }


def _model_target_multiplier(config: dict[str, Any], plan: Any) -> float:
    base_quota = config.get("base_quota_per_execution_block_t")
    if base_quota in (None, ""):
        return float(plan.planning_horizon_hours) / float(plan.execution_block_hours)
    base_value = float(base_quota)
    if base_value <= 0.0:
        raise RollingFeasibilityError("base_quota_per_execution_block_t must be positive when supplied.")
    return float(plan.total_quota_t) / base_value


def _as_float(value: Any) -> float:
    return float(value) if value not in (None, "") else 0.0


def _c0_continuous_operation_diagnosis(
    *,
    report: dict[str, Any],
    planning_horizon_hours: int,
    target_multiplier: float,
    continuous_activities: tuple[str, ...],
    source_coke_chain: dict[str, float],
) -> dict[str, Any] | None:
    """Prove target-specific C0 capacity conflicts without relaxing the model."""

    c0_audit = next(
        row for row in report["configuration_build_audit"] if row.get("configuration_id") == C0_CONFIGURATION_ID
    )
    if str(c0_audit.get("build_status", "")).startswith("solved"):
        return None

    tables = _load_tables(S44B_INPUT_DIR)
    inputs = _build_c0_inputs(
        tables,
        horizon_hours_override=planning_horizon_hours,
        target_multiplier=target_multiplier,
    )
    horizon = float(planning_horizon_hours)
    yield_chain = (
        inputs.bf_hot_iron_per_t_sinter
        * inputs.bof_crude_steel_per_t_hot_iron
        * inputs.hsm_final_per_t_crude_steel
    )
    downstream_yield = inputs.bof_crude_steel_per_t_hot_iron * inputs.hsm_final_per_t_crude_steel
    dry_coal_per_t_coke = source_coke_chain["dry_coal_t_per_t_coke"]
    bf_coke_per_t_hot_metal = source_coke_chain["bf_coke_t_per_t_hot_metal"]

    def envelope(names: tuple[str, ...]) -> tuple[float, float]:
        return (
            horizon * sum(inputs.process_limits[name][0] for name in names),
            horizon * sum(inputs.process_limits[name][1] for name in names),
        )

    kgf_dry_coal_envelope = envelope(("coking_plant_1", "coking_plant_2"))
    kgf_coke_envelope = tuple(value / dry_coal_per_t_coke for value in kgf_dry_coal_envelope)
    bf_sinter_envelope = envelope(("blast_furnace_6", "blast_furnace_7"))
    sinter_iron_ore_feed_envelope = envelope(("sintering_plant",))
    sinter_output_envelope = tuple(
        value * inputs.sinter_output_per_t_iron_ore for value in sinter_iron_ore_feed_envelope
    )
    bf_product_envelope = tuple(value * yield_chain for value in bf_sinter_envelope)
    sinter_product_envelope = tuple(value * yield_chain for value in sinter_output_envelope)
    kgf_product_envelope = tuple(
        value / bf_coke_per_t_hot_metal * downstream_yield for value in kgf_coke_envelope
    )
    combined_product_envelope = (
        max(bf_product_envelope[0], sinter_product_envelope[0], kgf_product_envelope[0]),
        min(bf_product_envelope[1], sinter_product_envelope[1], kgf_product_envelope[1]),
    )
    conflicts: list[dict[str, Any]] = []

    if combined_product_envelope[0] > combined_product_envelope[1] + TOLERANCE_T:
        conflicts.append(
            {
                "conflict_id": "continuous_c0_rate_envelopes_do_not_intersect",
                "constraint_chain": [
                    "KGF1/KGF2, sinter and BF6/BF7 process_min/process_max with on=1",
                    "sinter iron-ore feed converted to sinter output on the active model coefficient",
                    "source-backed dry-coal-to-coke and BF-coke-to-hot-metal conversions",
                    "coke, sinter, hot-iron and cold-slab terminal balances",
                ],
                "combined_lower_bound_t": round(combined_product_envelope[0], 6),
                "combined_upper_bound_t": round(combined_product_envelope[1], 6),
                "envelope_overlap_gap_t": round(combined_product_envelope[1] - combined_product_envelope[0], 6),
            }
        )
    elif inputs.final_product_target_t > combined_product_envelope[1] + TOLERANCE_T:
        upper_envelopes = {
            "BF6_BF7_capacity": bf_product_envelope[1],
            "sinter_capacity": sinter_product_envelope[1],
            "KGF1_KGF2_source_coke_chain_capacity": kgf_product_envelope[1],
        }
        binding_upper = min(upper_envelopes, key=upper_envelopes.get)
        conflicts.append(
            {
                "conflict_id": "continuous_c0_horizon_quota_exceeds_capacity",
                "constraint_chain": [
                    "continuous source/governed process_max bounds",
                    "sinter iron-ore feed converted to sinter output on the active model coefficient",
                    "source-backed coke conversion interface",
                    "coke, sinter, hot-iron and cold-slab terminal balances",
                    "cumulative final-product quota lower bound",
                ],
                "required_horizon_quota_t": round(inputs.final_product_target_t, 6),
                "maximum_terminal_balanced_final_product_t": round(combined_product_envelope[1], 6),
                "capacity_shortfall_t": round(inputs.final_product_target_t - combined_product_envelope[1], 6),
                "binding_upper_envelope": binding_upper,
                "upper_envelopes_t": {key: round(value, 6) for key, value in upper_envelopes.items()},
                "terminal_balanced_daily_equivalent_capacity_t": round(
                    combined_product_envelope[1] / horizon * 24.0, 6
                ),
            }
        )

    process_rows = [
        {
            "asset_id": row["asset_id"],
            "min_rate": _as_float(row["min_rate"]),
            "max_rate": _as_float(row["max_rate"]),
            "rate_unit": row["rate_unit"],
            "source_card_ids": row["source_card_ids"],
            "candidate_id": row["candidate_id"],
            "evidence_strength": row["evidence_strength"],
            "caveat": row["caveat"],
        }
        for row in tables.tables["process_units.csv"]
        if row.get("configuration_id") == C0_CONFIGURATION_ID
        and row.get("asset_id") in set(continuous_activities)
    ]
    return {
        "configuration_id": C0_CONFIGURATION_ID,
        "diagnosis_status": "focused_structural_infeasibility_proof" if conflicts else "no_rate_envelope_conflict_found",
        "solver_status": c0_audit.get("solver_status"),
        "termination_condition": c0_audit.get("termination_condition"),
        "planning_horizon_hours": planning_horizon_hours,
        "final_product_quota_t": round(inputs.final_product_target_t, 6),
        "quota_semantics": "cumulative_lower_bound; overproduction_allowed_and_reported",
        "continuous_must_run_activities": list(continuous_activities),
        "throughput_fixed": False,
        "governed_continuous_rate_bounds": process_rows,
        "model_coefficients": {
            "sinter_output_per_t_iron_ore": inputs.sinter_output_per_t_iron_ore,
            "bf_hot_iron_per_t_sinter": inputs.bf_hot_iron_per_t_sinter,
            "bof_crude_steel_per_t_hot_iron": inputs.bof_crude_steel_per_t_hot_iron,
            "hsm_final_per_t_crude_steel": inputs.hsm_final_per_t_crude_steel,
            "dry_coal_t_per_t_coke": dry_coal_per_t_coke,
            "bf_coke_t_per_t_hot_metal": bf_coke_per_t_hot_metal,
        },
        "component_final_product_envelopes_t": {
            "BF6_BF7": [round(value, 6) for value in bf_product_envelope],
            "sinter": [round(value, 6) for value in sinter_product_envelope],
            "KGF1_KGF2_source_coke_chain": [round(value, 6) for value in kgf_product_envelope],
            "combined_terminal_balanced": [round(value, 6) for value in combined_product_envelope],
        },
        "sinter_material_basis": {
            "activity": "iron_ore_feed_t",
            "activity_envelope_t": [round(value, 6) for value in sinter_iron_ore_feed_envelope],
            "converted_output": "sinter_t",
            "converted_output_envelope_t": [round(value, 6) for value in sinter_output_envelope],
        },
        "conflicts": conflicts,
        "guardrail_interpretation": "The diagnosis preserves continuous availability, bounded unfixed throughput, cumulative quota semantics, source-backed coke conversion and terminal material balances. Residual coke, WAG, NG, electricity, route shares or fixed hours were not introduced; WAG/steam/utility constraints cannot repair a proven upstream capacity shortfall.",
    }


def _c1_capacity_diagnosis(
    *,
    report: dict[str, Any],
    planning_horizon_hours: int,
    target_multiplier: float,
    source_coke_chain: dict[str, float],
) -> dict[str, Any] | None:
    """Prove a target-specific C1 capacity shortfall on the active model basis."""

    c1_audit = next(
        row for row in report["configuration_build_audit"] if row.get("configuration_id") == C1_CONFIGURATION_ID
    )
    if str(c1_audit.get("build_status", "")).startswith("solved"):
        return None

    tables = _load_tables(S44B_INPUT_DIR)
    inputs = _build_c1_inputs(
        tables,
        horizon_hours_override=planning_horizon_hours,
        target_multiplier=target_multiplier,
        include_retained_bf_bof=True,
    )
    retained = inputs.retained_bf_bof
    if retained is None:
        raise RollingFeasibilityError("C1 capacity diagnosis requires the active retained BF-BOF route.")

    horizon = float(planning_horizon_hours)
    downstream_yield = retained.bof_crude_steel_per_t_hot_iron * retained.hsm_final_per_t_crude_steel
    dry_coal_per_t_coke = source_coke_chain["dry_coal_t_per_t_coke"]
    bf_coke_per_t_hot_metal = source_coke_chain["bf_coke_t_per_t_hot_metal"]
    retained_upper_envelopes = {
        "retained_BF6_capacity": (
            horizon
            * retained.process_limits["blast_furnace_6"][1]
            * retained.bf_hot_iron_per_t_sinter
            * downstream_yield
        ),
        "retained_sinter_capacity": (
            horizon
            * retained.process_limits["sintering_plant"][1]
            * retained.sinter_output_per_t_iron_ore
            * retained.bf_hot_iron_per_t_sinter
            * downstream_yield
        ),
        "retained_KGF1_source_coke_chain_capacity": (
            horizon
            * retained.process_limits["coking_plant_1"][1]
            / dry_coal_per_t_coke
            / bf_coke_per_t_hot_metal
            * downstream_yield
        ),
        "retained_BOF_capacity": (
            horizon
            * retained.process_limits["basic_oxygen_furnace"][1]
            * downstream_yield
        ),
        "retained_HSM_capacity": (
            horizon
            * retained.process_limits["hot_strip_mill"][1]
            * retained.hsm_final_per_t_crude_steel
        ),
    }
    retained_upper = min(retained_upper_envelopes.values())
    retained_binding = min(retained_upper_envelopes, key=retained_upper_envelopes.get)

    drp_dri_upper_t = horizon * inputs.drp_max_t_pellets_h * inputs.drp_yield_t_dri_per_t_pellets
    eaf_dri_upper_t = horizon * inputs.eaf_max_t_dri_h
    eaf_route_upper = min(drp_dri_upper_t, eaf_dri_upper_t) * inputs.eaf_yield_t_final_per_t_dri
    eaf_binding = "C1_DRP_capacity" if drp_dri_upper_t <= eaf_dri_upper_t else "C1_EAF_capacity"
    combined_upper = retained_upper + eaf_route_upper

    conflicts: list[dict[str, Any]] = []
    if inputs.final_product_target_t > combined_upper + TOLERANCE_T:
        conflicts.append(
            {
                "conflict_id": "c1_horizon_quota_exceeds_combined_route_capacity",
                "constraint_chain": [
                    "retained BF-BOF and DRP-EAF governed process_max bounds",
                    "sinter iron-ore feed converted to sinter output on the active model coefficient",
                    "source-backed coke conversion and terminal material balances",
                    "DRP pellets-to-DRI and EAF DRI-to-final-product conversions",
                    "cumulative final-product quota lower bound",
                ],
                "required_horizon_quota_t": round(inputs.final_product_target_t, 6),
                "maximum_terminal_balanced_final_product_t": round(combined_upper, 6),
                "capacity_shortfall_t": round(inputs.final_product_target_t - combined_upper, 6),
                "retained_route_binding_upper_envelope": retained_binding,
                "eaf_route_binding_upper_envelope": eaf_binding,
                "terminal_balanced_daily_equivalent_capacity_t": round(
                    combined_upper / horizon * 24.0, 6
                ),
            }
        )

    return {
        "configuration_id": C1_CONFIGURATION_ID,
        "diagnosis_status": "focused_structural_infeasibility_proof" if conflicts else "no_capacity_conflict_found",
        "solver_status": c1_audit.get("solver_status"),
        "termination_condition": c1_audit.get("termination_condition"),
        "planning_horizon_hours": planning_horizon_hours,
        "final_product_quota_t": round(inputs.final_product_target_t, 6),
        "quota_semantics": "cumulative_lower_bound; overproduction_allowed_and_reported",
        "endogenous_origin_t": "all represented C1 production; imported slab input is inactive in this runner",
        "imported_origin_t": 0.0,
        "model_coefficients": {
            "sinter_output_per_t_iron_ore": retained.sinter_output_per_t_iron_ore,
            "bf_hot_iron_per_t_sinter": retained.bf_hot_iron_per_t_sinter,
            "bof_crude_steel_per_t_hot_iron": retained.bof_crude_steel_per_t_hot_iron,
            "hsm_final_per_t_crude_steel": retained.hsm_final_per_t_crude_steel,
            "dry_coal_t_per_t_coke": dry_coal_per_t_coke,
            "bf_coke_t_per_t_hot_metal": bf_coke_per_t_hot_metal,
            "drp_dri_per_t_pellets": inputs.drp_yield_t_dri_per_t_pellets,
            "eaf_final_per_t_dri": inputs.eaf_yield_t_final_per_t_dri,
        },
        "component_final_product_upper_envelopes_t": {
            **{key: round(value, 6) for key, value in retained_upper_envelopes.items()},
            "retained_route_terminal_balanced": round(retained_upper, 6),
            "DRP_EAF_route_terminal_balanced": round(eaf_route_upper, 6),
            "combined_terminal_balanced": round(combined_upper, 6),
        },
        "conflicts": conflicts,
        "guardrail_interpretation": "This is a capacity proof from the active quota-driven C1 topology. It adds no imports, residual material, fixed route share, gas ratio, WAG aggregation or economic term.",
    }


def _deadline_rows(
    hourly_rows: list[dict[str, Any]],
    *,
    deadline_targets_t: dict[int, float],
) -> list[dict[str, Any]]:
    by_configuration: dict[str, list[dict[str, Any]]] = {}
    for row in hourly_rows:
        if row.get("build_status") in {"blocked_missing_inputs", "solver_failed", "solver_stopped_without_accepted_solution"}:
            continue
        by_configuration.setdefault(str(row["configuration_id"]), []).append(row)

    rows: list[dict[str, Any]] = []
    for configuration_id, configuration_rows in sorted(by_configuration.items()):
        ordered = sorted(configuration_rows, key=lambda row: int(row["hour_index"]))
        for deadline_hour, target_t in deadline_targets_t.items():
            fulfilled_t = sum(_as_float(row.get("final_product_output_t")) for row in ordered if int(row["hour_index"]) < deadline_hour)
            residual_t = fulfilled_t - target_t
            rows.append(
                {
                    "configuration_id": configuration_id,
                    "deadline_hour": deadline_hour,
                    "cumulative_required_final_product_t": round(target_t, 6),
                    "cumulative_fulfilled_final_product_t": round(fulfilled_t, 6),
                    "residual_t": round(residual_t, 6),
                    "status": "pass" if residual_t >= -TOLERANCE_T else "fail",
                    "quota_denominator": "final_product_proxy",
                }
            )
    return rows


def _execution_block_rows(
    hourly_rows: list[dict[str, Any]],
    *,
    execution_block_hours: int,
) -> list[dict[str, Any]]:
    by_configuration: dict[str, list[dict[str, Any]]] = {}
    for row in hourly_rows:
        if row.get("build_status") not in {"solved", "optimal", "feasible"}:
            continue
        by_configuration.setdefault(str(row["configuration_id"]), []).append(row)

    rows: list[dict[str, Any]] = []
    for configuration_id, configuration_rows in sorted(by_configuration.items()):
        first_block = [row for row in configuration_rows if int(row["hour_index"]) < execution_block_hours]
        if not first_block:
            continue
        endpoint = max(first_block, key=lambda row: int(row["hour_index"]))
        rows.append(
            {
                "configuration_id": configuration_id,
                "execution_block_hours": execution_block_hours,
                "planned_final_product_t": round(sum(_as_float(row.get("final_product_output_t")) for row in first_block), 6),
                "gross_electricity_mwh": round(sum(_as_float(row.get("gross_electricity_mwh")) for row in first_block), 6),
                "net_grid_import_mwh": round(sum(_as_float(row.get("net_grid_import_mwh")) for row in first_block), 6),
                "named_ng_nm3": round(sum(_as_float(row.get("natural_gas_nm3")) for row in first_block), 6),
                "named_ng_boiler_mwh": round(sum(_as_float(row.get("NG_to_boiler_mwh")) for row in first_block), 6),
                "steam_mwh": round(sum(_as_float(row.get("steam")) for row in first_block), 6),
                "wag_generated_mwh": round(sum(_as_float(row.get("WAG_generated")) for row in first_block), 6),
                "wag_used_mwh": round(sum(_as_float(row.get("WAG_used")) for row in first_block), 6),
                "wag_flared_mwh": round(sum(_as_float(row.get("WAG_flared")) for row in first_block), 6),
                "end_coke_inventory_t": round(_as_float(endpoint.get("coke_inventory_t")), 6),
                "end_sinter_inventory_t": round(_as_float(endpoint.get("sinter_inventory_t")), 6),
                "end_hot_iron_inventory_t": round(_as_float(endpoint.get("hot_iron_inventory_t")), 6),
                "end_cold_slab_inventory_t": round(_as_float(endpoint.get("cold_slab_inventory_t")), 6),
                "end_dri_inventory_t": round(_as_float(endpoint.get("DRI_inventory_t")), 6),
                "execution_status": "planned_first_block_only",
                "caveat": "This run solves one rolling planning window. It does not yet advance inventories into a second re-optimisation window.",
            }
        )
    return rows


def _validation_rows(
    report: dict[str, Any],
    deadline_rows: list[dict[str, Any]],
    availability: dict[str, Any],
    continuous_activities: dict[str, tuple[str, ...]],
    c0_diagnosis: dict[str, Any] | None,
    c1_diagnosis: dict[str, Any] | None,
    source_coke_chain: dict[str, float],
) -> list[dict[str, Any]]:
    build_audits = report["configuration_build_audit"]
    expected_configurations = {str(row["configuration_id"]) for row in build_audits}
    deadline_configurations = {str(row["configuration_id"]) for row in deadline_rows}
    rows = [
        {
            "check_id": "hard_cumulative_quota_deadlines",
            "status": "pass" if (
                deadline_rows
                and deadline_configurations == expected_configurations
                and all(row["status"] == "pass" for row in deadline_rows)
            ) else "fail",
            "evidence": "rolling_quota_deadlines.csv",
        },
        {
            "check_id": "both_configurations_solved",
            "status": "pass" if all(str(row.get("build_status", "")).startswith("solved") for row in build_audits) else "fail",
            "evidence": "model_build_audit",
        },
        {
            "check_id": "market_terms_disabled",
            "status": "pass" if not any(report["forbidden_terms_active"].values()) else "fail",
            "evidence": "run_summary.json",
        },
        {
            "check_id": "availability_policy_applied",
            "status": "pass" if (
                report.get("fix_c0_binary_schedule") == availability["fix_c0_binary_schedule"]
                and report.get("fix_c1_hybrid_schedule") == availability["fix_c1_hybrid_schedule"]
                and report.get("c1_retained_route_policy") == availability["c1_retained_route_policy"]
                and report.get("commitment_granularity") == availability["commitment_granularity"]
            ) else "fail",
            "evidence": "run_summary.json",
        },
        {
            "check_id": "quota_lower_bound_and_source_coke_basis_applied",
            "status": "pass" if (
                report.get("final_product_requirement_sense") == "cumulative_quota_lower_bound"
                and report.get("c0_coke_chain_reconciliation") == source_coke_chain
                and report.get("c1_coke_chain_reconciliation") == source_coke_chain
            ) else "fail",
            "evidence": "run_summary.json and model-build contract",
        },
        {
            "check_id": "c0_continuous_operation_class_enforced",
            "status": "pass" if (
                report.get("c0_continuous_must_run_activities") == sorted(continuous_activities["c0"])
                and all(
                    set(str(row.get("continuous_must_run_activities", "")).split(";")).difference({""})
                    == set(continuous_activities["c0"])
                    and row.get("continuous_must_run_throughput_fixed") == "false"
                    for row in build_audits
                    if row.get("configuration_id") == C0_CONFIGURATION_ID
                )
            ) else "fail",
            "evidence": "component ontology plus C0 model-build audit; on variables fixed to 1 while throughput variables remain unfixed",
        },
        {
            "check_id": "c0_result_or_focused_infeasibility_diagnosis",
            "status": "pass" if (
                any(
                    str(row.get("build_status", "")).startswith("solved")
                    for row in build_audits
                    if row.get("configuration_id") == C0_CONFIGURATION_ID
                )
                or (
                    c0_diagnosis is not None
                    and c0_diagnosis.get("diagnosis_status") == "focused_structural_infeasibility_proof"
                    and bool(c0_diagnosis.get("conflicts"))
                )
            ) else "fail",
            "evidence": "c0_continuous_operation_diagnosis.json when the active C0 solve is infeasible",
        },
        {
            "check_id": "c1_result_or_focused_infeasibility_diagnosis",
            "status": "pass" if (
                any(
                    str(row.get("build_status", "")).startswith("solved")
                    for row in build_audits
                    if row.get("configuration_id") == C1_CONFIGURATION_ID
                )
                or (
                    c1_diagnosis is not None
                    and c1_diagnosis.get("diagnosis_status") == "focused_structural_infeasibility_proof"
                    and bool(c1_diagnosis.get("conflicts"))
                )
            ) else "fail",
            "evidence": "c1_capacity_diagnosis.json when the active C1 solve is infeasible",
        },
        {
            "check_id": "carrier_specific_wag_layer",
            "status": "pass" if report.get("enable_minimal_wag_layer") else "fail",
            "evidence": "model_build_audit",
        },
        {
            "check_id": "residual_policy",
            "status": "pass",
            "evidence": "Residual electricity and NG are reported only; this runner does not fill, allocate or cost them.",
        },
    ]
    return rows


def run_rolling_production_feasibility(
    *,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    output_root: str | Path = DEFAULT_RUN_ROOT,
    run_id_override: str | None = None,
    quota_per_execution_block_t_override: float | None = None,
) -> dict[str, Any]:
    config_file = Path(config_path).resolve()
    config = _load_config(config_file)
    config = dict(config)
    configured_base_quota = float(config["quota_per_execution_block_t"])
    if run_id_override is not None:
        config["run_id"] = run_id_override
    if quota_per_execution_block_t_override is not None:
        if quota_per_execution_block_t_override <= 0.0:
            raise RollingFeasibilityError("quota_per_execution_block_t_override must be positive.")
        config["base_quota_per_execution_block_t"] = float(
            config.get("base_quota_per_execution_block_t", configured_base_quota)
        )
        config["quota_per_execution_block_t"] = quota_per_execution_block_t_override
    plan = build_rolling_production_quota_plan(
        planning_horizon_hours=int(config["planning_horizon_hours"]),
        execution_block_hours=int(config["execution_block_hours"]),
        quota_per_execution_block_t=float(config["quota_per_execution_block_t"]),
    )
    availability = _availability_controls(config)
    continuous_activities = _continuous_operation_activities()
    source_coke_chain = _source_coke_chain(config)
    target_multiplier = _model_target_multiplier(config, plan)
    run_directory = Path(output_root).resolve() / str(config["run_id"])
    if run_directory.exists():
        raise RollingFeasibilityError(f"Run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True)

    report = run_s44c_unified_physical_regression(
        run_id=str(config["run_id"]),
        write_report=False,
        horizon_hours_override=plan.planning_horizon_hours,
        target_multiplier=target_multiplier,
        fix_c0_binary_schedule=availability["fix_c0_binary_schedule"],
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        enable_internal_wag_power=True,
        development_controller_activation=str(config.get("development_controller_activation", "full")),
        daily_production_guardrail=False,
        rolling_production_deadline_targets_t=plan.cumulative_deadline_targets_t,
        fix_c1_hybrid_schedule=availability["fix_c1_hybrid_schedule"],
        c1_retained_route_policy=availability["c1_retained_route_policy"],
        commitment_granularity=availability["commitment_granularity"],
        solver_time_limit_seconds=float(config.get("solver_time_limit_seconds", 120)),
        c0_continuous_must_run_activities=continuous_activities["c0"],
        c0_coke_chain_reconciliation=source_coke_chain,
        c1_coke_chain_reconciliation=source_coke_chain,
    )
    c0_diagnosis = _c0_continuous_operation_diagnosis(
        report=report,
        planning_horizon_hours=plan.planning_horizon_hours,
        target_multiplier=target_multiplier,
        continuous_activities=continuous_activities["c0"],
        source_coke_chain=source_coke_chain,
    )
    c1_diagnosis = _c1_capacity_diagnosis(
        report=report,
        planning_horizon_hours=plan.planning_horizon_hours,
        target_multiplier=target_multiplier,
        source_coke_chain=source_coke_chain,
    )
    deadline_rows = _deadline_rows(report["hourly_rows"], deadline_targets_t=plan.cumulative_deadline_targets_t)
    execution_rows = _execution_block_rows(report["hourly_rows"], execution_block_hours=plan.execution_block_hours)
    validation_rows = _validation_rows(
        report,
        deadline_rows,
        availability,
        continuous_activities,
        c0_diagnosis,
        c1_diagnosis,
        source_coke_chain,
    )
    status = "pass" if all(row["status"] == "pass" for row in validation_rows) else "fail"

    resolved_config = dict(config)
    resolved_config["deadline_targets_t"] = plan.cumulative_deadline_targets_t
    resolved_config["model_target_multiplier"] = target_multiplier
    resolved_config["rolling_execution_implemented"] = False
    resolved_config["rolling_execution_note"] = "First planning window only; execute-and-replan inventory handoff is a later extension."
    resolved_config["c0_coke_chain_reconciliation_active"] = True
    resolved_config["c1_coke_chain_reconciliation_active"] = True
    resolved_config["final_product_requirement"] = "cumulative_quota_lower_bound"
    resolved_config["continuous_operation_enforcement"] = {
        "c0": list(continuous_activities["c0"]),
        "rule": "fix_on_over_horizon_with_unfixed_bounded_throughput",
        "scope": "C0_gate_1_only; existing C1 builder enforcement interface unchanged",
    }
    (run_directory / "config_resolved.yaml").write_text(yaml.safe_dump(resolved_config, sort_keys=False), encoding="utf-8")
    _write_json(
        run_directory / "input_manifest.json",
        {
            "config_path": str(config_file.relative_to(REPO_ROOT)),
            "config_sha256": hashlib.sha256(config_file.read_bytes()).hexdigest(),
            "run_id_override": run_id_override,
            "quota_per_execution_block_t_override": quota_per_execution_block_t_override,
            "modelbuilder": "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
            "quota_helper": "scripts/Data/04_Steel_Test_Case/steel/rolling_production_quota.py",
            "operation_class_overrides_path": str(OVERRIDE_PATH.relative_to(REPO_ROOT)),
            "operation_class_overrides_sha256": hashlib.sha256(OVERRIDE_PATH.read_bytes()).hexdigest(),
            "input_directory": report["input_directory"],
        },
    )
    _write_json(run_directory / "code_version.json", {"git_commit": report["git_commit"], "timestamp_utc": datetime.now(timezone.utc).isoformat()})
    _write_csv(
        run_directory / "rolling_quota_deadlines.csv",
        deadline_rows,
        [
            "configuration_id", "deadline_hour", "cumulative_required_final_product_t",
            "cumulative_fulfilled_final_product_t", "residual_t", "status", "quota_denominator",
        ],
    )
    _write_csv(run_directory / "execution_block_metrics.csv", execution_rows)
    _write_csv(run_directory / "validation_checks.csv", validation_rows, ["check_id", "status", "evidence"])
    _write_csv(run_directory / "metrics_summary.csv", report["configuration_build_audit"])
    if c0_diagnosis is not None:
        _write_json(run_directory / "c0_continuous_operation_diagnosis.json", c0_diagnosis)
    if c1_diagnosis is not None:
        _write_json(run_directory / "c1_capacity_diagnosis.json", c1_diagnosis)
    warnings = """# Warnings and limitations\n\n- This is a deterministic, price-free feasibility run; it is not a DA, stochastic, economic or ETS model.\n- The run contains one 168-hour planning window and reports its first 24-hour execution candidate. It does not yet carry realised inventories into a second re-optimisation window.\n- Production deadlines are hard cumulative lower-bound quotas. Overproduction is allowed and reported; no flat or exact production profile is imposed.\n- Source-classified continuous assets are fixed on over the horizon, but their throughput is not fixed; the quota, governed min/max rates, material, WAG, steam and utility constraints determine throughput. BOF remains batch-equivalent and downstream remains bounded.\n- The C0/C1 coke interface uses the governed development values 1.285 t dry coal/t coke and 0.359 t coke/t hot metal; these are generic source-backed candidates, not Tata-measured truth.\n- The non-economic objective is only a compact-schedule tie-breaker, not an operating-cost claim.\n- BFG, COG and BOFG remain separate where existing rows preserve them. Aggregate WAG and mixed-gas quantities do not feed physical allocation.\n- Electricity and NG residuals remain reporting diagnostics; they are not filled, allocated, costed or calibrated.\n- WAG-explicit combustion CO2 is not converted into a full Scope 1 or ETS claim.\n"""
    (run_directory / "warnings_and_limitations.md").write_text(warnings, encoding="utf-8")
    _write_json(
        run_directory / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "run_class": config.get("run_class", "deterministic_feasibility_smoke"),
            "lineage_role": config.get("lineage_role", "canonical_steel_path"),
            "output_policy": config.get("output_policy", "minimal"), "status": status,
            "market_prices_enabled": False, "rolling_execution_implemented": False,
            "c0_diagnosis_status": c0_diagnosis.get("diagnosis_status") if c0_diagnosis is not None else "not_required",
            "c1_diagnosis_status": c1_diagnosis.get("diagnosis_status") if c1_diagnosis is not None else "not_required",
        },
    )
    summary = {
        "run_id": config["run_id"], "status": status, "planning_horizon_hours": plan.planning_horizon_hours,
        "execution_block_hours": plan.execution_block_hours, "quota_per_execution_block_t": plan.quota_per_execution_block_t,
        "total_horizon_quota_t": plan.total_quota_t, "rolling_execution_implemented": False,
        "availability_policy": {"c0": availability["c0_policy"], "c1": availability["c1_policy"]},
        "continuous_operation_enforcement": {
            "c0": list(continuous_activities["c0"]),
            "rule": "fix_on_over_horizon_with_unfixed_bounded_throughput",
            "scope": "C0_gate_1_only; existing C1 builder enforcement interface unchanged",
        },
        "commitment_granularity": availability["commitment_granularity"],
        "final_product_requirement": "cumulative_quota_lower_bound",
        "source_coke_chain": source_coke_chain,
        "model_target_multiplier": target_multiplier,
        "c0_diagnosis_status": c0_diagnosis.get("diagnosis_status") if c0_diagnosis is not None else "not_required",
        "c1_diagnosis_status": c1_diagnosis.get("diagnosis_status") if c1_diagnosis is not None else "not_required",
        "physical_builder_runtime_seconds": report["runtime_seconds"], "validation_checks": validation_rows,
        "market_prices_enabled": False, "energy_cost_objective_enabled": False,
        "caveat": "A hard rolling planning envelope is implemented. Closed-loop inventory handoff across repeated re-optimisations is deliberately deferred.",
    }
    _write_json(run_directory / "run_summary.json", summary)
    return {"run_directory": run_directory, "summary": summary, "report": report}
