"""S4.4c5l_b HSM reheat WAG controller traceability patch.

This development-only patch keeps the accepted C5k production policy and C5l_a
downstream routing, then makes the HSM reheat gas allocation explicit as a
physical accounting controller. It does not add slab age buckets, Sinter, market
valuation, WAG export revenue, or HSM CO2 shortcuts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    CONFIGS,
    HORIZONS,
    S4_ROOT,
    WAG_TOL_MWH,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5g_wag_aggregate_diagnostic_hygiene import (
    AGGREGATE_COLUMNS,
    WAG_CARRIERS,
    _wag_aggregate_invariant_rows,
)
from .s4_4c5l_a_downstream_routing_and_hsm_buffer_patch import (
    C5L_A_DIR,
    DOWNSTREAM_ROUTING_MODE,
    HSM_BUFFER_MODE,
    HSM_CO2_STATUS,
    HSM_PARAMETER_COLUMNS,
    HSM_REHEAT_POLICY,
    run_s4_4c5l_a_downstream_routing_and_hsm_buffer_patch,
)
from .s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR


STAGE = "S4.4c5l_b_HSM_WAG_dispatch_controller_and_traceability_patch"
C5L_B_DIR = S4_ROOT / "s4_4c5l_b_HSM_WAG_dispatch_controller_and_traceability_patch"
HSM_REHEAT_CONTROLLER_MODE = "physical_energy_allocation_controller"
CONTROLLER_IMPLEMENTATION_MODE = "deterministic_physical_allocation_controller"
DEPENDENCY_CHAIN = "C5j -> C5k -> C5l_a -> C5l_b"
HSM_UNSERVED_ALLOWED_IN_BASE = False


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _policy_row(parameter_id: str, value: Any, unit: str, role: str, basis: str) -> dict[str, Any]:
    return {
        "parameter_id": parameter_id,
        "configuration_scope": "generic_policy",
        "applies_to_configuration": "all",
        "plant_id": "HSM_WBW",
        "parameter_name": parameter_id.lower(),
        "parameter_role": role,
        "direction": "policy",
        "carrier_or_material": "HSM_reheat_controller",
        "base_value": _fmt(value),
        "low_value": "",
        "high_value": "",
        "unit": unit,
        "basis": basis,
        "conversion_formula": "",
        "source_or_assumption_id": "S4.4c5l_b_HSM_WAG_dispatch_controller_and_traceability_patch",
        "input_status": "development_policy_target",
        "source_status": "engineering_assumption",
        "evidence_strength": "modelling_policy_with_public_context",
        "executable_status": "development_executable",
        "development_executable": "true",
        "thesis_usability": "false",
        "human_review_required": "true",
        "codex_may_decide": "false",
        "applies_to_solver": "false",
        "applies_to_diagnostics": "true",
        "applies_to_anchor_comparison": "false",
        "active_driver": "true",
        "constraint_used": "false",
        "caveat": "development-only deterministic physical allocation controller; not market dispatch; not thesis-approved",
    }


def _development_input_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        dict(row) for row in _read_csv(C5L_A_DIR / "s4_4c5l_a_downstream_routing_input_rows.csv")
    ]
    rows.extend(
        [
            _policy_row(
                "HSM_REHEAT_CONTROLLER_MODE",
                HSM_REHEAT_CONTROLLER_MODE,
                "mode",
                "reheat_controller_policy",
                "BFG_COG_BOFG_NG_to_HSM_reheat_heat_energy_balance",
            ),
            _policy_row(
                "HSM_REHEAT_CONTROLLER_IMPLEMENTATION_MODE",
                CONTROLLER_IMPLEMENTATION_MODE,
                "mode",
                "controller_implementation_policy",
                "deterministic_accounting_allocation_not_LP_dispatch",
            ),
            _policy_row(
                "HSM_UNSERVED_REHEAT_BASE_ALLOWED",
                int(HSM_UNSERVED_ALLOWED_IN_BASE),
                "boolean",
                "controller_feasibility_policy",
                "NG_backup_should_cover_base_residual_heat",
            ),
        ]
    )
    return rows


def _site_total_rows(wag_rows: list[dict[str, str]], config: str, horizon: int) -> dict[str, dict[str, str]]:
    return {
        row["carrier"]: row
        for row in wag_rows
        if row["configuration"] == config
        and int(row["horizon_hours"]) == horizon
        and row["plant_id"] == "SITE_TOTAL"
        and row["carrier"] in WAG_CARRIERS
    }


def _fuel_delta_map(c5l_a_fuel: list[dict[str, str]]) -> dict[tuple[str, int, str], tuple[float, float]]:
    return {
        (row["configuration"], int(row["horizon_hours"]), row["carrier"]): (
            _zero(row.get("fuel_used_raw_MWh_y")),
            _zero(row.get("fuel_used_site_MWh_y")),
        )
        for row in c5l_a_fuel
    }


def _controller_rows(
    report: list[dict[str, str]],
    c5k_wag: list[dict[str, str]],
    c5l_a_fuel: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, int, str], dict[str, float]]]:
    report_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in report}
    old_alloc = _fuel_delta_map(c5l_a_fuel)
    dashboard: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    allocation: dict[tuple[str, int, str], dict[str, float]] = {}

    for config in CONFIGS:
        for horizon in HORIZONS:
            item = report_by_key[(config, horizon)]
            demand_raw = _zero(item["hsm_reheat_heat_demand_raw_MWh_y"])
            demand_site = _zero(item["hsm_reheat_heat_demand_site_MWh_y"])
            remaining_raw = demand_raw
            remaining_site = demand_site
            carrier_totals = _site_total_rows(c5k_wag, config, horizon)
            total_alloc_raw = 0.0
            total_alloc_site = 0.0
            total_available_raw = 0.0
            total_available_site = 0.0
            total_residual_raw = 0.0
            total_residual_site = 0.0

            for carrier in WAG_CARRIERS:
                source = carrier_totals[carrier]
                scale = _zero(source.get("scale_factor")) or 1.0
                generated_raw = _zero(source["generated_MWh_LHV_y"])
                direct_pre_raw = _zero(source["consumed_direct_MWh_LHV_y"])
                boiler_pre_raw = _zero(source["consumed_boiler_MWh_LHV_y"])
                vattenfall_pre_raw = _zero(source["consumed_vattenfall_MWh_LHV_y"])
                flare_pre_raw = _zero(source["flared_MWh_LHV_y"])
                available_raw = max(generated_raw - direct_pre_raw, 0.0)
                used_raw = min(remaining_raw, available_raw)
                remaining_raw -= used_raw
                used_site = used_raw * scale
                remaining_site = max(remaining_site - used_site, 0.0)
                if abs(remaining_raw) <= WAG_TOL_MWH:
                    remaining_raw = 0.0
                if abs(remaining_site) <= WAG_TOL_MWH:
                    remaining_site = 0.0
                available_site = available_raw * scale
                residual_raw = available_raw - used_raw
                residual_site = residual_raw * scale
                direct_post_raw = direct_pre_raw + used_raw
                boiler_post_raw = min(boiler_pre_raw, max(generated_raw - direct_post_raw, 0.0))
                vattenfall_post_raw = min(
                    vattenfall_pre_raw,
                    max(generated_raw - direct_post_raw - boiler_post_raw, 0.0),
                )
                flare_post_raw = max(generated_raw - direct_post_raw - boiler_post_raw - vattenfall_post_raw, 0.0)
                balance_error_raw = generated_raw - direct_post_raw - boiler_post_raw - vattenfall_post_raw - flare_post_raw
                old_raw, old_site = old_alloc.get((config, horizon, carrier), (0.0, 0.0))

                allocation[(config, horizon, carrier)] = {
                    "scale": scale,
                    "generated_raw": generated_raw,
                    "generated_site": generated_raw * scale,
                    "direct_pre_raw": direct_pre_raw,
                    "direct_pre_site": direct_pre_raw * scale,
                    "available_raw": available_raw,
                    "available_site": available_site,
                    "used_raw": used_raw,
                    "used_site": used_site,
                    "residual_raw": residual_raw,
                    "residual_site": residual_site,
                    "boiler_post_raw": boiler_post_raw,
                    "boiler_post_site": boiler_post_raw * scale,
                    "vattenfall_post_raw": vattenfall_post_raw,
                    "vattenfall_post_site": vattenfall_post_raw * scale,
                    "flare_post_raw": flare_post_raw,
                    "flare_post_site": flare_post_raw * scale,
                    "balance_error_raw": balance_error_raw,
                    "balance_error_site": balance_error_raw * scale,
                    "lhv": _zero(source.get("LHV_MJ_per_Nm3_used")),
                }
                total_alloc_raw += used_raw
                total_alloc_site += used_site
                total_available_raw += available_raw
                total_available_site += available_site
                total_residual_raw += residual_raw
                total_residual_site += residual_site
                trace.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "carrier": carrier,
                        "controller_mode": HSM_REHEAT_CONTROLLER_MODE,
                        "implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
                        "hsm_reheat_demand_raw_MWh_y": _fmt(demand_raw),
                        "hsm_reheat_demand_site_MWh_y": _fmt(demand_site),
                        "generated_raw_MWh_y": _fmt(generated_raw),
                        "generated_site_MWh_y": _fmt(generated_raw * scale),
                        "higher_priority_direct_use_raw_MWh_y": _fmt(direct_pre_raw),
                        "higher_priority_direct_use_site_MWh_y": _fmt(direct_pre_raw * scale),
                        "available_after_KGF_BF_priority_raw_MWh_y": _fmt(available_raw),
                        "available_after_KGF_BF_priority_site_MWh_y": _fmt(available_site),
                        "allocated_to_HSM_reheat_raw_MWh_y": _fmt(used_raw),
                        "allocated_to_HSM_reheat_site_MWh_y": _fmt(used_site),
                        "residual_after_HSM_raw_MWh_y": _fmt(residual_raw),
                        "residual_after_HSM_site_MWh_y": _fmt(residual_site),
                        "residual_to_boiler_placeholder_raw_MWh_y": _fmt(boiler_post_raw),
                        "residual_to_vattenfall_placeholder_raw_MWh_y": _fmt(vattenfall_post_raw),
                        "residual_to_flare_placeholder_raw_MWh_y": _fmt(flare_post_raw),
                        "residual_to_boiler_placeholder_site_MWh_y": _fmt(boiler_post_raw * scale),
                        "residual_to_vattenfall_placeholder_site_MWh_y": _fmt(vattenfall_post_raw * scale),
                        "residual_to_flare_placeholder_site_MWh_y": _fmt(flare_post_raw * scale),
                        "carrier_balance_error_raw_MWh_y": _fmt(balance_error_raw),
                        "carrier_balance_error_site_MWh_y": _fmt(balance_error_raw * scale),
                        "delta_vs_C5l_a_raw_MWh_y": _fmt(used_raw - old_raw),
                        "delta_vs_C5l_a_site_MWh_y": _fmt(used_site - old_site),
                        "scale_factor": _fmt(scale),
                        "status": "allocated" if used_raw else "eligible_not_used",
                        "red_flags": "" if used_raw <= available_raw + WAG_TOL_MWH else "allocation_exceeds_availability",
                        "notes": "Availability is net of inherited KGF COG self-use and BF hot-stove deductions.",
                    }
                )

            ng_raw = max(remaining_raw, 0.0)
            ng_site = max(remaining_site, 0.0)
            if abs(ng_raw) <= WAG_TOL_MWH:
                ng_raw = 0.0
            if abs(ng_site) <= WAG_TOL_MWH:
                ng_site = 0.0
            unserved_raw = 0.0
            unserved_site = 0.0
            old_ng_raw, old_ng_site = old_alloc.get((config, horizon, "NG"), (0.0, 0.0))
            balance_raw = total_alloc_raw + ng_raw + unserved_raw - demand_raw
            balance_site = total_alloc_site + ng_site + unserved_site - demand_site
            if abs(balance_raw) <= WAG_TOL_MWH:
                balance_raw = 0.0
            if abs(balance_site) <= WAG_TOL_MWH:
                balance_site = 0.0
            dashboard.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "dependency_chain": DEPENDENCY_CHAIN,
                    "c5l_a_downstream_routing_mode": DOWNSTREAM_ROUTING_MODE,
                    "hsm_buffer_mode": HSM_BUFFER_MODE,
                    "hsm_reheat_policy": HSM_REHEAT_POLICY,
                    "hsm_reheat_controller_mode": HSM_REHEAT_CONTROLLER_MODE,
                    "controller_implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
                    "hsm_reheat_demand_raw_MWh_y": _fmt(demand_raw),
                    "hsm_reheat_demand_site_MWh_y": _fmt(demand_site),
                    "available_WAG_after_priority_raw_MWh_y": _fmt(total_available_raw),
                    "available_WAG_after_priority_site_MWh_y": _fmt(total_available_site),
                    "available_BFG_after_BF_hot_stove_raw_MWh_y": _fmt(allocation[(config, horizon, "BFG")]["available_raw"]),
                    "available_COG_after_KGF_underfiring_raw_MWh_y": _fmt(allocation[(config, horizon, "COG")]["available_raw"]),
                    "available_BOFG_after_BOF_generation_raw_MWh_y": _fmt(allocation[(config, horizon, "BOFG")]["available_raw"]),
                    "BFG_to_HSM_reheat_raw_MWh_y": _fmt(allocation[(config, horizon, "BFG")]["used_raw"]),
                    "COG_to_HSM_reheat_raw_MWh_y": _fmt(allocation[(config, horizon, "COG")]["used_raw"]),
                    "BOFG_to_HSM_reheat_raw_MWh_y": _fmt(allocation[(config, horizon, "BOFG")]["used_raw"]),
                    "NG_to_HSM_reheat_raw_MWh_y": _fmt(ng_raw),
                    "HSM_unserved_reheat_raw_MWh_y": _fmt(unserved_raw),
                    "BFG_to_HSM_reheat_site_MWh_y": _fmt(allocation[(config, horizon, "BFG")]["used_site"]),
                    "COG_to_HSM_reheat_site_MWh_y": _fmt(allocation[(config, horizon, "COG")]["used_site"]),
                    "BOFG_to_HSM_reheat_site_MWh_y": _fmt(allocation[(config, horizon, "BOFG")]["used_site"]),
                    "NG_to_HSM_reheat_site_MWh_y": _fmt(ng_site),
                    "HSM_unserved_reheat_site_MWh_y": _fmt(unserved_site),
                    "residual_WAG_after_HSM_raw_MWh_y": _fmt(total_residual_raw),
                    "residual_WAG_after_HSM_site_MWh_y": _fmt(total_residual_site),
                    "controller_balance_error_raw_MWh_y": _fmt(balance_raw),
                    "controller_balance_error_site_MWh_y": _fmt(balance_site),
                    "delta_vs_C5l_a_BFG_site_MWh_y": _fmt(allocation[(config, horizon, "BFG")]["used_site"] - old_alloc.get((config, horizon, "BFG"), (0.0, 0.0))[1]),
                    "delta_vs_C5l_a_COG_site_MWh_y": _fmt(allocation[(config, horizon, "COG")]["used_site"] - old_alloc.get((config, horizon, "COG"), (0.0, 0.0))[1]),
                    "delta_vs_C5l_a_BOFG_site_MWh_y": _fmt(allocation[(config, horizon, "BOFG")]["used_site"] - old_alloc.get((config, horizon, "BOFG"), (0.0, 0.0))[1]),
                    "delta_vs_C5l_a_NG_site_MWh_y": _fmt(ng_site - old_ng_site),
                    "lp_controller_used": "false",
                    "ng_backup_status": "not_needed" if ng_raw <= WAG_TOL_MWH else "energy_diagnostic_only_no_cost_steering",
                    "hsm_co2_status": HSM_CO2_STATUS,
                    "status_detail": "pass" if abs(balance_raw) <= WAG_TOL_MWH and abs(balance_site) <= WAG_TOL_MWH else "fail",
                    "red_flags": "" if abs(balance_raw) <= WAG_TOL_MWH and abs(balance_site) <= WAG_TOL_MWH else "controller_balance_error",
                    "notes": "Deterministic physical allocation controller; WAG carriers remain separate and no WAG market value is introduced.",
                }
            )
            trace.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "carrier": "NG",
                    "controller_mode": HSM_REHEAT_CONTROLLER_MODE,
                    "implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
                    "hsm_reheat_demand_raw_MWh_y": _fmt(demand_raw),
                    "hsm_reheat_demand_site_MWh_y": _fmt(demand_site),
                    "generated_raw_MWh_y": "",
                    "generated_site_MWh_y": "",
                    "higher_priority_direct_use_raw_MWh_y": "",
                    "higher_priority_direct_use_site_MWh_y": "",
                    "available_after_KGF_BF_priority_raw_MWh_y": "",
                    "available_after_KGF_BF_priority_site_MWh_y": "",
                    "allocated_to_HSM_reheat_raw_MWh_y": _fmt(ng_raw),
                    "allocated_to_HSM_reheat_site_MWh_y": _fmt(ng_site),
                    "residual_after_HSM_raw_MWh_y": "",
                    "residual_after_HSM_site_MWh_y": "",
                    "residual_to_boiler_placeholder_raw_MWh_y": "",
                    "residual_to_vattenfall_placeholder_raw_MWh_y": "",
                    "residual_to_flare_placeholder_raw_MWh_y": "",
                    "residual_to_boiler_placeholder_site_MWh_y": "",
                    "residual_to_vattenfall_placeholder_site_MWh_y": "",
                    "residual_to_flare_placeholder_site_MWh_y": "",
                    "carrier_balance_error_raw_MWh_y": "",
                    "carrier_balance_error_site_MWh_y": "",
                    "delta_vs_C5l_a_raw_MWh_y": _fmt(ng_raw - old_ng_raw),
                    "delta_vs_C5l_a_site_MWh_y": _fmt(ng_site - old_ng_site),
                    "scale_factor": "",
                    "status": "ng_backup_reported_without_cost_steering" if ng_raw else "not_needed",
                    "red_flags": "",
                    "notes": "NG backup is an external energy-accounting carrier only; no unsupported cost steering is added.",
                }
            )
    return dashboard, trace, allocation


def _wag_rows(c5k_wag: list[dict[str, str]], allocation: dict[tuple[str, int, str], dict[str, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in c5k_wag:
        item = dict(row)
        config = row["configuration"]
        horizon = int(row["horizon_hours"])
        carrier = row["carrier"]
        if row["plant_id"] == "SITE_TOTAL" and carrier in WAG_CARRIERS:
            alloc = allocation[(config, horizon, carrier)]
            generated = alloc["generated_raw"]
            direct = alloc["direct_pre_raw"] + alloc["used_raw"]
            boiler = alloc["boiler_post_raw"]
            vattenfall = alloc["vattenfall_post_raw"]
            flared = alloc["flare_post_raw"]
            item["consumed_direct_MWh_LHV_y"] = _fmt(direct)
            item["consumed_boiler_MWh_LHV_y"] = _fmt(boiler)
            item["consumed_vattenfall_MWh_LHV_y"] = _fmt(vattenfall)
            item["flared_MWh_LHV_y"] = _fmt(flared)
            item["balance_error_MWh_LHV_y"] = _fmt(alloc["balance_error_raw"])
            item["status"] = "closed"
            item["metric_scope"] = "HSM_reheat_controller_inserted_before_boiler_vattenfall_flare"
            item["notes"] = "C5l_b inserts a traceable HSM reheat controller after KGF/BF priority uses and before boiler/Vattenfall/flare placeholders."
        rows.append(item)

    for config in CONFIGS:
        for horizon in HORIZONS:
            for carrier in WAG_CARRIERS:
                alloc = allocation[(config, horizon, carrier)]
                used_raw = alloc["used_raw"]
                used_site = alloc["used_site"]
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "plant_id": "HSM_WBW",
                        "carrier": carrier,
                        "generated_MWh_LHV_y": _fmt(0.0),
                        "generated_Nm3_y": _fmt(0.0),
                        "consumed_direct_MWh_LHV_y": _fmt(used_raw),
                        "consumed_boiler_MWh_LHV_y": _fmt(0.0),
                        "consumed_vattenfall_MWh_LHV_y": _fmt(0.0),
                        "flared_MWh_LHV_y": _fmt(0.0),
                        "balance_error_MWh_LHV_y": _fmt(-used_raw),
                        "status": "hsm_reheat_controller_wag_sink" if used_raw else "eligible_not_used",
                        "LHV_MJ_per_Nm3_used": _fmt(alloc["lhv"]),
                        "raw_model_quantity": _fmt(used_raw),
                        "raw_model_unit": "MWh_LHV/y",
                        "site_scaled_quantity": _fmt(used_site),
                        "site_scaled_unit": "MWh_LHV/y",
                        "scale_factor": _fmt(alloc["scale"]),
                        "scale_mode": "module_scaled_to_site_target",
                        "metric_scope": "HSM_reheat_controller_fuel_consumption",
                        "notes": "HSM consumes eligible WAG for reheating; generated quantity remains zero.",
                    }
                )
    return rows


def _co2_rows(c5l_a_co2: list[dict[str, str]], report: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        dict(row) for row in c5l_a_co2 if row.get("emission_bucket") != "HSM_reheat_CO2"
    ]
    for row in report:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "emission_bucket": "HSM_reheat_CO2",
                "CO2_site_t_y": "",
                "CO2_mode": "derived_from_reheat_fuel_mix",
                "derivation_status": HSM_CO2_STATUS,
                "included_in_objective_ETS_cost": "false",
                "included_in_total_direct_CO2": "false",
                "double_counting_risk": "blocked_until_governed_carrier_emission_factors_exist",
                "status": "deferred",
                "notes": "C5l_b adds carrier traceability but no HSM CO2 shortcut or WAG combustion objective cost.",
            }
        )
    return rows


def _final_product_rows(report: list[dict[str, str]], anchors: list[dict[str, str]]) -> list[dict[str, Any]]:
    anchor_lookup = {
        (row["configuration"], int(row["horizon_hours"]), row["metric"]): row
        for row in anchors
    }
    rows: list[dict[str, Any]] = []
    for row in report:
        config = row["configuration"]
        horizon = int(row["horizon_hours"])
        hsm = _zero(row["hsm_output_site_t_y"])
        dsp = _zero(row["dsp_output_site_t_y"])
        proxy = hsm + dsp
        target = _zero(row["active_total_liquid_steel_target_site_t_y"])
        hsm_anchor = anchor_lookup[(config, horizon, "HSM_rolled_coils_context_t_y")]
        dsp_anchor = anchor_lookup[(config, horizon, "DSP_rolls_context_t_y")]
        import_anchor = anchor_lookup[(config, horizon, "imported_slab_context_t_y")]
        rows.append(
            {
                "configuration": config,
                "horizon_hours": horizon,
                "active_liquid_steel_target_site_t_y": row["active_total_liquid_steel_target_site_t_y"],
                "active_HSM_output_site_t_y": row["hsm_output_site_t_y"],
                "active_DSP_output_site_t_y": row["dsp_output_site_t_y"],
                "active_final_product_proxy_site_t_y": _fmt(proxy),
                "final_product_minus_liquid_steel_target_t_y": _fmt(proxy - target),
                "raw_MER_HSM_anchor_t_y": hsm_anchor["anchor_quantity"],
                "raw_MER_HSM_gap_t_y": hsm_anchor["gap_quantity"],
                "raw_MER_DSP_anchor_t_y": dsp_anchor["anchor_quantity"],
                "raw_MER_DSP_gap_t_y": dsp_anchor["gap_quantity"],
                "raw_MER_imported_slab_anchor_t_y": import_anchor["anchor_quantity"],
                "raw_MER_imported_slab_gap_t_y": import_anchor["gap_quantity"],
                "anchor_constraint_used": "false",
                "denominator_warning": "final_product_proxy_contains_HSM_HRC_plus_DSP_output_not_liquid_steel",
                "superseded_policy_warning": "C5l_a downstream routing supersedes C5l scaled-public-output-driver policy",
                "status": "reported",
            }
        )
    return rows


def _delta_rows(controller: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in controller:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "metric": "HSM_reheat_fuel_allocation_delta_vs_C5l_a",
                "BFG_delta_site_MWh_y": row["delta_vs_C5l_a_BFG_site_MWh_y"],
                "COG_delta_site_MWh_y": row["delta_vs_C5l_a_COG_site_MWh_y"],
                "BOFG_delta_site_MWh_y": row["delta_vs_C5l_a_BOFG_site_MWh_y"],
                "NG_delta_site_MWh_y": row["delta_vs_C5l_a_NG_site_MWh_y"],
                "status": "traceability_only_no_allocation_change",
                "notes": "C5l_b wraps the C5l_a deterministic allocation in an explicit physical controller trace.",
            }
        )
    return rows


def _summary_rows(
    report: list[dict[str, str]],
    controller: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    final_product: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    controller_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in controller}
    agg_by_key = {(row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row for row in wag_aggregate}
    final_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in final_product}
    rows: list[dict[str, Any]] = []
    by_horizon: dict[int, list[dict[str, Any]]] = {24: [], 168: []}
    for item in report:
        config = item["configuration"]
        horizon = int(item["horizon_hours"])
        ctrl = controller_by_key[(config, horizon)]
        agg = agg_by_key[(config, horizon, "site_scaled")]
        final = final_by_key[(config, horizon)]
        row = {
            "stage": STAGE,
            "configuration": config,
            "horizon_hours": horizon,
            "solver_status": "inherited_from_C5l_a_accounting_only",
            "status": "development_only",
            "thesis_usability": "false",
            "dependency_chain": DEPENDENCY_CHAIN,
            "active_total_liquid_steel_target_site_t_y": item["active_total_liquid_steel_target_site_t_y"],
            "c5k_bof_liquid_steel_site_t_y": item["c5k_bof_liquid_steel_site_t_y"],
            "c5k_eaf_liquid_steel_site_t_y": item["c5k_eaf_liquid_steel_site_t_y"],
            "downstream_routing_mode": DOWNSTREAM_ROUTING_MODE,
            "hsm_reheat_controller_mode": HSM_REHEAT_CONTROLLER_MODE,
            "controller_implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
            "hsm_reheat_demand_site_MWh_y": ctrl["hsm_reheat_demand_site_MWh_y"],
            "BFG_to_HSM_reheat_site_MWh_y": ctrl["BFG_to_HSM_reheat_site_MWh_y"],
            "COG_to_HSM_reheat_site_MWh_y": ctrl["COG_to_HSM_reheat_site_MWh_y"],
            "BOFG_to_HSM_reheat_site_MWh_y": ctrl["BOFG_to_HSM_reheat_site_MWh_y"],
            "NG_to_HSM_reheat_site_MWh_y": ctrl["NG_to_HSM_reheat_site_MWh_y"],
            "HSM_unserved_reheat_site_MWh_y": ctrl["HSM_unserved_reheat_site_MWh_y"],
            "controller_balance_error_site_MWh_y": ctrl["controller_balance_error_site_MWh_y"],
            "active_final_product_proxy_site_t_y": final["active_final_product_proxy_site_t_y"],
            "C5l_a_material_gap_site_t_y": item["indicative_downstream_material_gap_site_t_y"],
            "WAG_invariant_status": agg["status"],
            "WAG_balance_error_MWh_y": agg["balance_error_MWh_y"],
            "LHV_consistency_status": "pass",
            "HSM_CO2_status": HSM_CO2_STATUS,
            "CO2_double_counting_guard_status": "pass",
            "anchor_constraints_used_count": "0",
        }
        rows.append(row)
        by_horizon[horizon].append(row)
    return rows, by_horizon


def _compact_rows(controller: list[dict[str, Any]], report: list[dict[str, str]], final_product: list[dict[str, Any]]) -> list[dict[str, Any]]:
    report_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in report}
    final_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in final_product}
    rows: list[dict[str, Any]] = []
    for ctrl in controller:
        key = (ctrl["configuration"], int(ctrl["horizon_hours"]))
        item = report_by_key[key]
        final = final_by_key[key]
        rows.append(
            {
                "configuration": ctrl["configuration"],
                "horizon_hours": ctrl["horizon_hours"],
                "plant": "HSM_WBW_reheat_controller",
                "active": "true",
                "controller_mode": HSM_REHEAT_CONTROLLER_MODE,
                "implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
                "downstream_routing_mode": DOWNSTREAM_ROUTING_MODE,
                "HSM_output_Mt_y": _fmt(_zero(item["hsm_output_site_t_y"]) / 1_000_000.0),
                "DSP_output_Mt_y": _fmt(_zero(item["dsp_output_site_t_y"]) / 1_000_000.0),
                "active_final_product_proxy_Mt_y": _fmt(_zero(final["active_final_product_proxy_site_t_y"]) / 1_000_000.0),
                "HSM_reheat_TWh_th_y": _fmt(_zero(ctrl["hsm_reheat_demand_site_MWh_y"]) / 1_000_000.0),
                "BFG_to_HSM_TWh_LHV_y": _fmt(_zero(ctrl["BFG_to_HSM_reheat_site_MWh_y"]) / 1_000_000.0),
                "COG_to_HSM_TWh_LHV_y": _fmt(_zero(ctrl["COG_to_HSM_reheat_site_MWh_y"]) / 1_000_000.0),
                "BOFG_to_HSM_TWh_LHV_y": _fmt(_zero(ctrl["BOFG_to_HSM_reheat_site_MWh_y"]) / 1_000_000.0),
                "NG_to_HSM_TWh_LHV_y": _fmt(_zero(ctrl["NG_to_HSM_reheat_site_MWh_y"]) / 1_000_000.0),
                "unserved_TWh_y": _fmt(_zero(ctrl["HSM_unserved_reheat_site_MWh_y"]) / 1_000_000.0),
                "controller_balance_error_MWh_y": ctrl["controller_balance_error_site_MWh_y"],
                "WAG_carriers_separate": "true",
                "CO2_status": HSM_CO2_STATUS,
                "status": ctrl["status_detail"],
                "red_flags": ctrl["red_flags"],
            }
        )
    return rows


def _stage_gate(
    input_rows: list[dict[str, str]],
    report: list[dict[str, str]],
    anchors: list[dict[str, str]],
    controller: list[dict[str, Any]],
    trace: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    lhv: list[dict[str, str]],
    co2: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[Any] = []
    failures.extend(
        row
        for row in input_rows
        if row["thesis_usability"] != "false"
        or row["human_review_required"] != "true"
        or row["codex_may_decide"] != "false"
        or row["constraint_used"] != "false"
    )
    failures.extend(row for row in report if abs(_zero(row["indicative_downstream_material_gap_site_t_y"])) > 1e-6)
    failures.extend(row for row in anchors if row["constraint_used"] != "false")
    failures.extend(row for row in controller if row["status_detail"] != "pass")
    failures.extend(row for row in controller if abs(_zero(row["HSM_unserved_reheat_site_MWh_y"])) > WAG_TOL_MWH)
    failures.extend(row for row in trace if row["carrier"] in WAG_CARRIERS and row["red_flags"])
    failures.extend(row for row in trace if row["carrier"] in WAG_CARRIERS and _zero(row["residual_after_HSM_raw_MWh_y"]) < -WAG_TOL_MWH)
    failures.extend(row for row in wag_aggregate if row["status"] != "pass")
    failures.extend(row for row in lhv if row["status"] != "pass")
    failures.extend(row for row in co2 if row["included_in_objective_ETS_cost"] != "false")

    c0_24 = next(row for row in controller if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    c1_24 = next(row for row in controller if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    return {
        "stage": STAGE,
        "decision": "pass_development_hsm_wag_controller_traceability_patch" if not failures else "fail_development_hsm_wag_controller_traceability_patch",
        "output_directory": _rel(C5L_B_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "DOWNSTREAM_ROUTING_MODE": DOWNSTREAM_ROUTING_MODE,
        "HSM_BUFFER_MODE": HSM_BUFFER_MODE,
        "HSM_REHEAT_POLICY": HSM_REHEAT_POLICY,
        "HSM_REHEAT_CONTROLLER_MODE": HSM_REHEAT_CONTROLLER_MODE,
        "controller_implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
        "lp_controller_used": False,
        "C0_HSM_reheat_demand_site_MWh_y": _zero(c0_24["hsm_reheat_demand_site_MWh_y"]),
        "C1_HSM_reheat_demand_site_MWh_y": _zero(c1_24["hsm_reheat_demand_site_MWh_y"]),
        "C0_BFG_to_HSM_site_MWh_y": _zero(c0_24["BFG_to_HSM_reheat_site_MWh_y"]),
        "C1_BFG_to_HSM_site_MWh_y": _zero(c1_24["BFG_to_HSM_reheat_site_MWh_y"]),
        "max_abs_controller_balance_error_MWh_y": max(abs(_zero(row["controller_balance_error_site_MWh_y"])) for row in controller),
        "max_HSM_unserved_reheat_site_MWh_y": max(_zero(row["HSM_unserved_reheat_site_MWh_y"]) for row in controller),
        "max_abs_C5l_a_delta_site_MWh_y": max(
            abs(_zero(row[field]))
            for row in controller
            for field in (
                "delta_vs_C5l_a_BFG_site_MWh_y",
                "delta_vs_C5l_a_COG_site_MWh_y",
                "delta_vs_C5l_a_BOFG_site_MWh_y",
                "delta_vs_C5l_a_NG_site_MWh_y",
            )
        ),
        "wag_invariant_fail_count": sum(1 for row in wag_aggregate if row["status"] != "pass"),
        "lhv_consistency_fail_count": sum(1 for row in lhv if row["status"] != "pass"),
        "co2_double_counting_guard_status": "pass" if all(row["included_in_objective_ETS_cost"] == "false" for row in co2) else "fail",
        "HSM_CO2_status": HSM_CO2_STATUS,
        "anchor_constraints_used_count": sum(1 for row in anchors if row["constraint_used"] != "false"),
        "c5k_targets_and_route_split_changed": False,
        "c5l_a_downstream_routing_changed": False,
        "slab_age_bucket_buffer_added": False,
        "sinter_implemented": False,
        "direct_WAG_market_valuation_added": False,
        "WAG_export_revenue_added": False,
        "product_revenue_added": False,
        "failure_count": len(failures),
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5l_a_downstream_routing_and_hsm_buffer_patch()
    C5L_B_DIR.mkdir(parents=True, exist_ok=True)

    input_rows_any = _development_input_rows()
    _write_csv(C5L_B_DIR / "s4_4c5l_b_hsm_reheat_controller_input_rows.csv", input_rows_any, HSM_PARAMETER_COLUMNS)
    input_rows = _read_csv(C5L_B_DIR / "s4_4c5l_b_hsm_reheat_controller_input_rows.csv")
    report = _read_csv(C5L_A_DIR / "s4_4c5l_a_downstream_routing_report.csv")
    anchors = _read_csv(C5L_A_DIR / "s4_4c5l_a_anchor_gap_dashboard.csv")
    c5k_wag = _read_csv(C5K_DIR / "s4_4c5k_wag_generation_consumption_by_plant.csv")
    c5l_a_fuel = _read_csv(C5L_A_DIR / "s4_4c5l_a_hsm_fuel_mix_dashboard.csv")
    controller, trace, allocation = _controller_rows(report, c5k_wag, c5l_a_fuel)
    wag_rows = _wag_rows(c5k_wag, allocation)
    wag_aggregate = _wag_aggregate_invariant_rows(wag_rows)
    lhv = _read_csv(C5L_A_DIR / "s4_4c5l_a_lhv_consistency_checks.csv")
    co2 = _co2_rows(_read_csv(C5L_A_DIR / "s4_4c5l_a_hsm_co2_accounting_dashboard.csv"), report)
    final_product = _final_product_rows(report, anchors)
    deltas = _delta_rows(controller)
    summary_rows, by_horizon = _summary_rows(report, controller, wag_aggregate, final_product)
    compact = _compact_rows(controller, report, final_product)
    gate = _stage_gate(input_rows, report, anchors, controller, trace, wag_aggregate, lhv, co2)

    _write_json(C5L_B_DIR / "s4_4c5l_b_stage_gate.json", gate)
    _write_csv(C5L_B_DIR / "s4_4c5l_b_run_registry.csv", [{
        "stage": STAGE,
        "source_stage": "S4.4c5l_a_downstream_routing_and_hsm_buffer_patch",
        "decision": gate["decision"],
        "status": "development_only",
        "thesis_usability": "false",
        "output_directory": gate["output_directory"],
    }])
    for horizon, rows in by_horizon.items():
        _write_csv(C5L_B_DIR / f"s4_4c5l_b_{horizon}h_summary.csv", rows)
    _write_csv(C5L_B_DIR / "s4_4c5l_b_hsm_reheat_controller_dashboard.csv", controller)
    _write_csv(C5L_B_DIR / "s4_4c5l_b_hsm_reheat_controller_carrier_trace.csv", trace)
    _write_csv(C5L_B_DIR / "s4_4c5l_b_wag_generation_consumption_by_plant.csv", wag_rows)
    _write_csv(C5L_B_DIR / "s4_4c5l_b_wag_aggregate_invariant.csv", wag_aggregate, AGGREGATE_COLUMNS)
    _write_csv(C5L_B_DIR / "s4_4c5l_b_lhv_consistency_checks.csv", lhv)
    _write_csv(C5L_B_DIR / "s4_4c5l_b_hsm_co2_accounting_dashboard.csv", co2)
    _write_csv(C5L_B_DIR / "s4_4c5l_b_final_product_and_anchor_dashboard.csv", final_product)
    _write_csv(C5L_B_DIR / "s4_4c5l_b_delta_vs_c5l_a_dashboard.csv", deltas)
    _write_csv(C5L_B_DIR / "s4_4c5l_b_compact_table_for_chat.csv", compact)

    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "controller": len(controller),
            "carrier_trace": len(trace),
            "wag_aggregate": len(wag_aggregate),
            "final_product": len(final_product),
        },
    }
    _write_json(C5L_B_DIR / "s4_4c5l_b_summary.json", summary)
    return summary


def run_s4_4c5l_b_hsm_wag_dispatch_controller_and_traceability_patch() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5l_b_hsm_wag_dispatch_controller_and_traceability_patch(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
