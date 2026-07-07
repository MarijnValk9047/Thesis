"""S4.4c5l_a downstream routing and HSM buffer scaffold patch.

This development-only patch keeps the accepted C5k production policy and C5l
HSM coefficients, but replaces the scaled-public HSM/DSP output drivers with an
explicit liquid-steel routing policy: 20% DSP and 80% internal slab to HSM, with
C1 imported slab still visible. The HSM buffer layer is a routing scaffold only;
it does not create slab storage or flexibility.
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
    _wag_aggregate_invariant_rows,
)
from .s4_4c5l_hsm_wbw_minimal_integration import (
    C5L_DIR,
    CONTEXT,
    HSM_CO2_STATUS,
    HSM_PARAMETER_COLUMNS,
    SOURCE_CARD,
    _allocate_hsm_fuel,
    _anchor_rows,
    _co2_rows,
    _param,
    run_s4_4c5l_hsm_wbw_minimal_integration,
)


STAGE = "S4.4c5l_a_downstream_routing_and_hsm_buffer_patch"
C5L_A_DIR = S4_ROOT / "s4_4c5l_a_downstream_routing_and_hsm_buffer_patch"
DOWNSTREAM_ROUTING_MODE = "liquid_steel_80_20_to_DSP_HSM_with_imported_slab"
HSM_BUFFER_MODE = "simple_hot_cold_slab_routing_scaffold"
HSM_REHEAT_POLICY = "average_reheat_all_HSM_output"
DSP_LS_SHARE = 0.20
HSM_INTERNAL_SLAB_SHARE = 0.80
HOT_CHARGE_SHARE = 1.0
HOT_CHARGE_ENERGY_SAVING_STATUS = "blocked_missing_governed_parameter"


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
        "carrier_or_material": "downstream_routing",
        "base_value": _fmt(value),
        "low_value": "",
        "high_value": "",
        "unit": unit,
        "basis": basis,
        "conversion_formula": "",
        "source_or_assumption_id": "S4.4c5l_a_downstream_routing_policy",
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
        "caveat": "development-only routing assumption; not Tata-validated; not thesis-approved",
    }


def _development_input_rows() -> list[dict[str, Any]]:
    inherited = _read_csv(C5L_DIR / "s4_4c5l_hsm_wbw_development_input_rows.csv")
    rows: list[dict[str, Any]] = [dict(row) for row in inherited]
    rows.extend(
        [
            _policy_row("DOWNSTREAM_ROUTING_MODE", DOWNSTREAM_ROUTING_MODE, "mode", "downstream_routing_policy", "liquid_steel_to_DSP_and_HSM_internal_slab"),
            _policy_row("DSP_LS_SHARE", DSP_LS_SHARE, "share", "downstream_routing_policy", "active_total_liquid_steel_target"),
            _policy_row("HSM_INTERNAL_SLAB_SHARE", HSM_INTERNAL_SLAB_SHARE, "share", "downstream_routing_policy", "active_total_liquid_steel_target"),
            _policy_row("HSM_BUFFER_MODE", HSM_BUFFER_MODE, "mode", "buffer_scaffold_policy", "routing_scaffold_no_storage"),
            _policy_row("HOT_CHARGE_SHARE", HOT_CHARGE_SHARE, "share", "buffer_scaffold_policy", "internal_slab_to_hsm"),
            _policy_row("HSM_REHEAT_POLICY", HSM_REHEAT_POLICY, "mode", "reheat_policy", "all_HSM_output_average_reheat"),
            _policy_row("HOT_CHARGE_ENERGY_SAVING_STATUS", HOT_CHARGE_ENERGY_SAVING_STATUS, "status", "blocked_parameter", "no_governed_hot_charge_saving_parameter"),
        ]
    )
    return rows


def _c5k_report_by_key() -> dict[tuple[str, int], dict[str, str]]:
    c5k_dir = S4_ROOT / "s4_4c5k_production_policy_and_route_split_normalisation"
    return {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in _read_csv(c5k_dir / "s4_4c5k_route_split_normalisation_report.csv")
    }


def _report_rows(input_rows: list[dict[str, str]], c5k_report: dict[tuple[str, int], dict[str, str]]) -> list[dict[str, Any]]:
    slab_rate = _param(input_rows, "HSM_SLAB_INPUT_T_PER_T_HRC")
    reheat_gj = _param(input_rows, "HSM_REHEAT_ENERGY_GJ_PER_T_HRC")
    electricity = _param(input_rows, "HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC")
    dsp_share = _param(input_rows, "DSP_LS_SHARE")
    hsm_internal_share = _param(input_rows, "HSM_INTERNAL_SLAB_SHARE")
    hot_charge_share = _param(input_rows, "HOT_CHARGE_SHARE")

    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        imported_slab = _param(input_rows, f"{config}_IMPORTED_SLAB_DRIVER_T_Y")
        for horizon in HORIZONS:
            c5k = c5k_report[(config, horizon)]
            scale_factor = _zero(c5k["scale_factor"]) or 1.0
            active_ls = _zero(c5k["active_total_liquid_steel_target_site_t_y"])
            dsp_site = active_ls * dsp_share
            internal_slab_site = active_ls * hsm_internal_share
            hot_slab_site = internal_slab_site * hot_charge_share
            cold_slab_site = internal_slab_site - hot_slab_site
            imported_cold_slab_site = imported_slab
            total_slab_site = hot_slab_site + cold_slab_site + imported_cold_slab_site
            hsm_output_site = total_slab_site / slab_rate
            loss_site = total_slab_site - hsm_output_site
            gap_site = active_ls + imported_slab - dsp_site - total_slab_site
            heat_gj_site = hsm_output_site * reheat_gj
            heat_mwh_site = heat_gj_site / 3.6
            electricity_site = hsm_output_site * electricity
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "dependency_stage": "S4.4c5l_HSM_WBW_minimal_integration",
                    "downstream_routing_mode": DOWNSTREAM_ROUTING_MODE,
                    "hsm_buffer_mode": HSM_BUFFER_MODE,
                    "hsm_reheat_policy": HSM_REHEAT_POLICY,
                    "active_total_liquid_steel_target_site_t_y": _fmt(active_ls),
                    "c5k_bof_liquid_steel_site_t_y": c5k["bof_liquid_steel_site_t_y"],
                    "c5k_eaf_liquid_steel_site_t_y": c5k["eaf_liquid_steel_site_t_y"],
                    "dsp_ls_share": _fmt(dsp_share),
                    "hsm_internal_slab_share": _fmt(hsm_internal_share),
                    "dsp_output_raw_t_y": _fmt(dsp_site / scale_factor),
                    "dsp_output_site_t_y": _fmt(dsp_site),
                    "internal_slab_to_hsm_raw_t_y": _fmt(internal_slab_site / scale_factor),
                    "internal_slab_to_hsm_site_t_y": _fmt(internal_slab_site),
                    "imported_slab_raw_t_y": _fmt(imported_slab / scale_factor),
                    "imported_slab_site_t_y": _fmt(imported_slab),
                    "hsm_hot_slab_input_raw_t_y": _fmt(hot_slab_site / scale_factor),
                    "hsm_hot_slab_input_site_t_y": _fmt(hot_slab_site),
                    "hsm_cold_slab_input_raw_t_y": _fmt(cold_slab_site / scale_factor),
                    "hsm_cold_slab_input_site_t_y": _fmt(cold_slab_site),
                    "hsm_imported_cold_slab_input_raw_t_y": _fmt(imported_cold_slab_site / scale_factor),
                    "hsm_imported_cold_slab_input_site_t_y": _fmt(imported_cold_slab_site),
                    "hsm_total_slab_input_raw_t_y": _fmt(total_slab_site / scale_factor),
                    "hsm_total_slab_input_site_t_y": _fmt(total_slab_site),
                    "hsm_output_raw_t_y": _fmt(hsm_output_site / scale_factor),
                    "hsm_output_site_t_y": _fmt(hsm_output_site),
                    "hsm_internal_loss_or_scrap_raw_t_y": _fmt(loss_site / scale_factor),
                    "hsm_internal_loss_or_scrap_site_t_y": _fmt(loss_site),
                    "indicative_downstream_material_gap_raw_t_y": _fmt(gap_site / scale_factor),
                    "indicative_downstream_material_gap_site_t_y": _fmt(gap_site),
                    "hsm_reheat_heat_demand_raw_GJ_y": _fmt(heat_gj_site / scale_factor),
                    "hsm_reheat_heat_demand_site_GJ_y": _fmt(heat_gj_site),
                    "hsm_reheat_heat_demand_raw_MWh_y": _fmt(heat_mwh_site / scale_factor),
                    "hsm_reheat_heat_demand_site_MWh_y": _fmt(heat_mwh_site),
                    "hsm_reheat_heat_demand_raw_MWh_th_y": _fmt(heat_mwh_site / scale_factor),
                    "hsm_reheat_heat_demand_site_MWh_th_y": _fmt(heat_mwh_site),
                    "hsm_reheat_heat_demand_site_TWh_th_y": _fmt(heat_mwh_site / 1_000_000.0),
                    "hsm_reheat_heat_demand_site_TWh_LHV_y": _fmt(heat_mwh_site / 1_000_000.0),
                    "hsm_reheat_heat_demand_site_PJ_y": _fmt(heat_gj_site * 1e-6),
                    "hsm_rolling_electricity_raw_MWh_e_y": _fmt(electricity_site / scale_factor),
                    "hsm_rolling_electricity_site_MWh_e_y": _fmt(electricity_site),
                    "hsm_rolling_electricity_site_GWh_e_y": _fmt(electricity_site / 1000.0),
                    "hsm_total_energy_site_MWh_equiv_y": _fmt(heat_mwh_site + electricity_site),
                    "hsm_slab_input_t_per_t_HRC": _fmt(slab_rate),
                    "hsm_reheat_energy_GJ_per_t_HRC": _fmt(reheat_gj),
                    "hsm_rolling_electricity_MWh_per_t_HRC": _fmt(electricity),
                    "hot_charge_share": _fmt(hot_charge_share),
                    "hot_charge_energy_saving_status": HOT_CHARGE_ENERGY_SAVING_STATUS,
                    "scale_factor": _fmt(scale_factor),
                    "scale_mode": "module_scaled_to_site_target",
                    "hsm_is_wag_producer": "false",
                    "hsm_co2_status": HSM_CO2_STATUS,
                    "co2_double_counting_guard_status": "pass",
                    "no_unbounded_slab_storage_status": "pass_routing_scaffold_only_no_storage_state",
                    "caveats": "routing scaffold only; hot/cold timing, slab age buckets, thermal decay and real HSM flexibility deferred",
                }
            )
    return rows


def _anchor_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = {
        "MER_liquid_steel_context_t_y": "active_total_liquid_steel_target_site_t_y",
        "HSM_rolled_coils_context_t_y": "hsm_output_site_t_y",
        "DSP_rolls_context_t_y": "dsp_output_site_t_y",
        "imported_slab_context_t_y": "imported_slab_site_t_y",
    }
    context_fields = {
        "MER_liquid_steel_context_t_y": "liquid_steel_context_t_y",
        "HSM_rolled_coils_context_t_y": "hsm_output_context_t_y",
        "DSP_rolls_context_t_y": "dsp_output_context_t_y",
        "imported_slab_context_t_y": "imported_slab_context_t_y",
    }
    rows: list[dict[str, Any]] = []
    for item in report:
        config = item["configuration"]
        for metric, model_field in fields.items():
            anchor = CONTEXT[config][context_fields[metric]]
            model = _zero(item[model_field])
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": item["horizon_hours"],
                    "metric": metric,
                    "model_site_quantity": _fmt(model),
                    "anchor_quantity": _fmt(anchor),
                    "unit": "t/y",
                    "anchor_status": "validation_context_only",
                    "constraint_used": "false",
                    "gap_quantity": _fmt(model - anchor),
                    "gap_pct": _fmt((model - anchor) / anchor * 100.0 if anchor else 0.0),
                    "gap_type": "routing_policy_driver_vs_raw_context_anchor",
                    "notes": "C5l_a routes active liquid steel to DSP and HSM internal slab; raw MER values remain context anchors.",
                }
            )
    return rows


def _buffer_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in report:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "hsm_buffer_mode": row["hsm_buffer_mode"],
                "hot_charge_share": row["hot_charge_share"],
                "hsm_hot_slab_input_site_t_y": row["hsm_hot_slab_input_site_t_y"],
                "hsm_cold_slab_input_site_t_y": row["hsm_cold_slab_input_site_t_y"],
                "hsm_imported_cold_slab_input_site_t_y": row["hsm_imported_cold_slab_input_site_t_y"],
                "hsm_total_slab_input_site_t_y": row["hsm_total_slab_input_site_t_y"],
                "hsm_output_site_t_y": row["hsm_output_site_t_y"],
                "storage_state_created": "false",
                "storage_capacity_t": "",
                "terminal_inventory_policy": "not_applicable_no_storage_state",
                "hot_charge_energy_saving_status": row["hot_charge_energy_saving_status"],
                "status": "routing_scaffold_only_no_unbounded_storage",
                "red_flags": "hot_cold_timing_deferred;thermal_decay_deferred",
                "notes": "Imported slab defaults to cold slab; internal slab classified as hot by development assumption.",
            }
        )
    return rows


def _slab_balance_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration": row["configuration"],
            "horizon_hours": row["horizon_hours"],
            "downstream_routing_mode": row["downstream_routing_mode"],
            "active_total_liquid_steel_target_site_t_y": row["active_total_liquid_steel_target_site_t_y"],
            "dsp_output_driver_site_t_y": row["dsp_output_site_t_y"],
            "internal_slab_to_hsm_site_t_y": row["internal_slab_to_hsm_site_t_y"],
            "imported_slab_driver_site_t_y": row["imported_slab_site_t_y"],
            "hsm_total_slab_input_site_t_y": row["hsm_total_slab_input_site_t_y"],
            "hsm_output_site_t_y": row["hsm_output_site_t_y"],
            "hsm_internal_loss_or_scrap_site_t_y": row["hsm_internal_loss_or_scrap_site_t_y"],
            "indicative_downstream_material_gap_site_t_y": row["indicative_downstream_material_gap_site_t_y"],
            "status": "pass_rounding_level_gap" if abs(_zero(row["indicative_downstream_material_gap_site_t_y"])) <= 1e-6 else "gap_reported_not_forced",
            "red_flags": "" if abs(_zero(row["indicative_downstream_material_gap_site_t_y"])) <= 1e-6 else "downstream_material_gap_reported",
            "notes": "Gap is computed from active LS + imported slab - DSP output - HSM slab input; no yield tuning is used.",
        }
        for row in report
    ]


def _summary_rows(report: list[dict[str, Any]], wag_aggregate: list[dict[str, Any]], fuel: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    agg_by_key = {(row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row for row in wag_aggregate}
    fuel_by_key: dict[tuple[str, int], dict[str, float]] = {}
    for row in fuel:
        key = (row["configuration"], int(row["horizon_hours"]))
        fuel_by_key.setdefault(key, {"wag_site": 0.0, "ng_site": 0.0})
        if row["carrier"] == "NG":
            fuel_by_key[key]["ng_site"] += _zero(row["fuel_used_site_MWh_y"])
        else:
            fuel_by_key[key]["wag_site"] += _zero(row["fuel_used_site_MWh_y"])

    rows: list[dict[str, Any]] = []
    by_horizon: dict[int, list[dict[str, Any]]] = {24: [], 168: []}
    for item in report:
        key = (item["configuration"], int(item["horizon_hours"]))
        agg = agg_by_key[(item["configuration"], int(item["horizon_hours"]), "site_scaled")]
        row = {
            "stage": STAGE,
            "configuration": item["configuration"],
            "horizon_hours": item["horizon_hours"],
            "solver_status": "inherited_from_C5l_accounting_only",
            "status": "development_only",
            "thesis_usability": "false",
            "downstream_routing_mode": item["downstream_routing_mode"],
            "hsm_buffer_mode": item["hsm_buffer_mode"],
            "hsm_reheat_policy": item["hsm_reheat_policy"],
            "active_total_liquid_steel_target_site_t_y": item["active_total_liquid_steel_target_site_t_y"],
            "c5k_bof_liquid_steel_site_t_y": item["c5k_bof_liquid_steel_site_t_y"],
            "c5k_eaf_liquid_steel_site_t_y": item["c5k_eaf_liquid_steel_site_t_y"],
            "dsp_output_site_t_y": item["dsp_output_site_t_y"],
            "internal_slab_to_hsm_site_t_y": item["internal_slab_to_hsm_site_t_y"],
            "imported_slab_site_t_y": item["imported_slab_site_t_y"],
            "hsm_total_slab_input_site_t_y": item["hsm_total_slab_input_site_t_y"],
            "hsm_output_site_t_y": item["hsm_output_site_t_y"],
            "indicative_downstream_material_gap_site_t_y": item["indicative_downstream_material_gap_site_t_y"],
            "hsm_reheat_heat_demand_site_TWh_th_y": item["hsm_reheat_heat_demand_site_TWh_th_y"],
            "hsm_reheat_heat_demand_site_TWh_LHV_y": item["hsm_reheat_heat_demand_site_TWh_LHV_y"],
            "hsm_rolling_electricity_site_GWh_e_y": item["hsm_rolling_electricity_site_GWh_e_y"],
            "hsm_wag_reheat_site_MWh_y": _fmt(fuel_by_key[key]["wag_site"]),
            "hsm_ng_backup_site_MWh_y": _fmt(fuel_by_key[key]["ng_site"]),
            "hot_charge_energy_saving_status": item["hot_charge_energy_saving_status"],
            "WAG_invariant_status": agg["status"],
            "WAG_balance_error_MWh_y": agg["balance_error_MWh_y"],
            "HSM_CO2_status": HSM_CO2_STATUS,
            "CO2_double_counting_guard_status": "pass",
            "no_unbounded_slab_storage_status": item["no_unbounded_slab_storage_status"],
            "anchor_constraints_used_count": "0",
        }
        rows.append(row)
        by_horizon[int(item["horizon_hours"])].append(row)
    return rows, by_horizon


def _compact_rows(report: list[dict[str, Any]], fuel: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fuel_by_key: dict[tuple[str, int], dict[str, float]] = {}
    for row in fuel:
        key = (row["configuration"], int(row["horizon_hours"]))
        fuel_by_key.setdefault(key, {"BFG": 0.0, "COG": 0.0, "BOFG": 0.0, "NG": 0.0})
        fuel_by_key[key][row["carrier"]] += _zero(row["fuel_used_site_MWh_y"])
    rows: list[dict[str, Any]] = []
    for item in report:
        key = (item["configuration"], int(item["horizon_hours"]))
        rows.append(
            {
                "configuration": item["configuration"],
                "horizon_hours": item["horizon_hours"],
                "plant": "HSM_WBW",
                "active": "true",
                "downstream_routing_mode": item["downstream_routing_mode"],
                "DSP_output_Mt_y": _fmt(_zero(item["dsp_output_site_t_y"]) / 1_000_000.0),
                "internal_slab_to_HSM_Mt_y": _fmt(_zero(item["internal_slab_to_hsm_site_t_y"]) / 1_000_000.0),
                "imported_cold_slab_Mt_y": _fmt(_zero(item["hsm_imported_cold_slab_input_site_t_y"]) / 1_000_000.0),
                "total_HSM_slab_input_Mt_y": _fmt(_zero(item["hsm_total_slab_input_site_t_y"]) / 1_000_000.0),
                "HSM_output_Mt_y": _fmt(_zero(item["hsm_output_site_t_y"]) / 1_000_000.0),
                "material_gap_Mt_y": _fmt(_zero(item["indicative_downstream_material_gap_site_t_y"]) / 1_000_000.0),
                "reheat_TWh_th_y": item["hsm_reheat_heat_demand_site_TWh_th_y"],
                "rolling_electricity_GWh_e_y": item["hsm_rolling_electricity_site_GWh_e_y"],
                "BFG_to_HSM_MWh_y": _fmt(fuel_by_key[key]["BFG"]),
                "COG_to_HSM_MWh_y": _fmt(fuel_by_key[key]["COG"]),
                "BOFG_to_HSM_MWh_y": _fmt(fuel_by_key[key]["BOFG"]),
                "NG_backup_MWh_y": _fmt(fuel_by_key[key]["NG"]),
                "buffer_mode": item["hsm_buffer_mode"],
                "CO2_status": HSM_CO2_STATUS,
                "status": "development_only",
                "red_flags": "hot_cold_timing_deferred;thermal_decay_deferred",
            }
        )
    return rows


def _stage_gate(
    input_rows: list[dict[str, str]],
    report: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    co2: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[Any] = []
    failures.extend(row for row in input_rows if row["thesis_usability"] != "false" or row["human_review_required"] != "true" or row["codex_may_decide"] != "false" or row["constraint_used"] != "false")
    failures.extend(row for row in report if abs(_zero(row["indicative_downstream_material_gap_site_t_y"])) > 1e-6)
    failures.extend(row for row in report if row["hsm_is_wag_producer"] != "false")
    failures.extend(row for row in anchors if row["constraint_used"] != "false")
    failures.extend(row for row in wag_aggregate if row["status"] != "pass")
    failures.extend(row for row in co2 if row["included_in_objective_ETS_cost"] != "false")
    c0_24 = next(row for row in report if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    c1_24 = next(row for row in report if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    return {
        "stage": STAGE,
        "decision": "pass_development_downstream_routing_and_hsm_buffer_patch" if not failures else "fail_development_downstream_routing_and_hsm_buffer_patch",
        "output_directory": _rel(C5L_A_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "dependency_stage": "S4.4c5l_HSM_WBW_minimal_integration",
        "DOWNSTREAM_ROUTING_MODE": DOWNSTREAM_ROUTING_MODE,
        "DSP_LS_SHARE": DSP_LS_SHARE,
        "HSM_INTERNAL_SLAB_SHARE": HSM_INTERNAL_SLAB_SHARE,
        "HSM_BUFFER_MODE": HSM_BUFFER_MODE,
        "HSM_REHEAT_POLICY": HSM_REHEAT_POLICY,
        "C0_HSM_output_site_t_y": _zero(c0_24["hsm_output_site_t_y"]),
        "C1_HSM_output_site_t_y": _zero(c1_24["hsm_output_site_t_y"]),
        "C1_imported_slab_driver_site_t_y": _zero(c1_24["imported_slab_site_t_y"]),
        "max_abs_downstream_material_gap_t_y": max(abs(_zero(row["indicative_downstream_material_gap_site_t_y"])) for row in report),
        "no_unbounded_slab_storage_status": "pass_routing_scaffold_only_no_storage_state",
        "hot_charge_energy_saving_status": HOT_CHARGE_ENERGY_SAVING_STATUS,
        "wag_invariant_fail_count": sum(1 for row in wag_aggregate if row["status"] != "pass"),
        "co2_double_counting_guard_status": "pass" if all(row["included_in_objective_ETS_cost"] == "false" for row in co2) else "fail",
        "HSM_CO2_status": HSM_CO2_STATUS,
        "anchor_constraints_used_count": sum(1 for row in anchors if row["constraint_used"] != "false"),
        "forbidden_market_features_added": False,
        "forbidden_next_plant_work_included": False,
        "failure_count": len(failures),
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5l_hsm_wbw_minimal_integration()
    C5L_A_DIR.mkdir(parents=True, exist_ok=True)

    input_rows_any = _development_input_rows()
    _write_csv(C5L_A_DIR / "s4_4c5l_a_downstream_routing_input_rows.csv", input_rows_any, HSM_PARAMETER_COLUMNS)
    input_rows = _read_csv(C5L_A_DIR / "s4_4c5l_a_downstream_routing_input_rows.csv")
    c5k_report = _c5k_report_by_key()
    report = _report_rows(input_rows, c5k_report)
    anchors = _anchor_rows(report)
    c5k_wag = _read_csv(S4_ROOT / "s4_4c5k_production_policy_and_route_split_normalisation" / "s4_4c5k_wag_generation_consumption_by_plant.csv")
    wag_rows, fuel = _allocate_hsm_fuel(report, c5k_wag)
    wag_aggregate = _wag_aggregate_invariant_rows(wag_rows)
    buffer = _buffer_rows(report)
    slab = _slab_balance_rows(report)
    c5l_co2 = [
        row
        for row in _read_csv(C5L_DIR / "s4_4c5l_hsm_co2_accounting_dashboard.csv")
        if row.get("emission_bucket") != "HSM_reheat_CO2"
    ]
    co2 = _co2_rows(report, c5l_co2)
    c5l_lhv = _read_csv(C5L_DIR / "s4_4c5l_lhv_consistency_checks.csv")
    summary_rows, by_horizon = _summary_rows(report, wag_aggregate, fuel)
    compact = _compact_rows(report, fuel)
    gate = _stage_gate(input_rows, report, anchors, wag_aggregate, co2)

    _write_json(C5L_A_DIR / "s4_4c5l_a_stage_gate.json", gate)
    _write_csv(C5L_A_DIR / "s4_4c5l_a_run_registry.csv", [{
        "stage": STAGE,
        "source_stage": "S4.4c5l_HSM_WBW_minimal_integration",
        "decision": gate["decision"],
        "status": "development_only",
        "thesis_usability": "false",
        "output_directory": gate["output_directory"],
    }])
    for horizon, rows in by_horizon.items():
        _write_csv(C5L_A_DIR / f"s4_4c5l_a_{horizon}h_summary.csv", rows)
    _write_csv(C5L_A_DIR / "s4_4c5l_a_downstream_routing_report.csv", report)
    _write_csv(C5L_A_DIR / "s4_4c5l_a_hsm_buffer_scaffold_dashboard.csv", buffer)
    _write_csv(C5L_A_DIR / "s4_4c5l_a_slab_balance_dashboard.csv", slab)
    _write_csv(C5L_A_DIR / "s4_4c5l_a_anchor_gap_dashboard.csv", anchors)
    _write_csv(C5L_A_DIR / "s4_4c5l_a_hsm_fuel_mix_dashboard.csv", fuel)
    _write_csv(C5L_A_DIR / "s4_4c5l_a_wag_generation_consumption_by_plant.csv", wag_rows)
    _write_csv(C5L_A_DIR / "s4_4c5l_a_wag_aggregate_invariant.csv", wag_aggregate, AGGREGATE_COLUMNS)
    _write_csv(C5L_A_DIR / "s4_4c5l_a_lhv_consistency_checks.csv", c5l_lhv)
    _write_csv(C5L_A_DIR / "s4_4c5l_a_hsm_co2_accounting_dashboard.csv", co2)
    _write_csv(C5L_A_DIR / "s4_4c5l_a_compact_table_for_chat.csv", compact)
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "routing_report": len(report),
            "anchor_gaps": len(anchors),
            "wag_aggregate": len(wag_aggregate),
            "co2": len(co2),
        },
    }
    _write_json(C5L_A_DIR / "s4_4c5l_a_summary.json", summary)
    return summary


def run_s4_4c5l_a_downstream_routing_and_hsm_buffer_patch() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5l_a_downstream_routing_and_hsm_buffer_patch(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
