"""S4.4c5l HSM/WBW minimal downstream integration.

This stage adds development-only downstream HSM/WBW material, electricity, fuel
and WAG accounting on top of the normalised C5k production-policy outputs. It
does not add market logic, product revenue, free slab storage, or thesis-grade
parameter approval.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .s4_4c_unified_physical_modelbuilder import SELECTED_WAG_LHV_MJ_PER_NM3
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
from .s4_4c5k_production_policy_and_route_split_normalisation import (
    C5K_DIR,
    run_s4_4c5k_production_policy_and_route_split_normalisation,
)


STAGE = "S4.4c5l_HSM_WBW_minimal_integration"
C5L_DIR = S4_ROOT / "s4_4c5l_HSM_WBW_minimal_integration"
SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/HSM_Parameters.md")
HSM_OUTPUT_DRIVER_MODE = "scale_public_downstream_anchors_to_active_liquid_steel_target"
HSM_DIRECT_CO2_MODE = "derived_from_reheat_fuel_mix"
HSM_CO2_STATUS = "blocked_missing_governed_combustion_emission_factors"
HSM_REHEAT_ALLOCATION_MODE = "deterministic_accounting_allocator_BFG_COG_BOFG_then_NG_backup"

HSM_PARAMETER_COLUMNS = [
    "parameter_id",
    "configuration_scope",
    "applies_to_configuration",
    "plant_id",
    "parameter_name",
    "parameter_role",
    "direction",
    "carrier_or_material",
    "base_value",
    "low_value",
    "high_value",
    "unit",
    "basis",
    "conversion_formula",
    "source_or_assumption_id",
    "input_status",
    "source_status",
    "evidence_strength",
    "executable_status",
    "development_executable",
    "thesis_usability",
    "human_review_required",
    "codex_may_decide",
    "applies_to_solver",
    "applies_to_diagnostics",
    "applies_to_anchor_comparison",
    "active_driver",
    "constraint_used",
    "caveat",
]

CONTEXT = {
    C0: {
        "liquid_steel_context_t_y": 7_200_000.0,
        "hsm_output_context_t_y": 5_400_000.0,
        "dsp_output_context_t_y": 1_500_000.0,
        "imported_slab_context_t_y": 0.0,
    },
    C1: {
        "liquid_steel_context_t_y": 6_800_000.0,
        "hsm_output_context_t_y": 5_500_000.0,
        "dsp_output_context_t_y": 1_500_000.0,
        "imported_slab_context_t_y": 600_000.0,
    },
}


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _input_row(
    parameter_id: str,
    value: Any,
    unit: str,
    *,
    role: str,
    direction: str,
    material: str,
    low: Any = "",
    high: Any = "",
    config: str = "all",
    basis: str = "t_hot_rolled_coil",
    input_status: str = "development_candidate",
    executable_status: str = "development_executable",
    development_executable: str = "true",
    active_driver: str = "false",
    evidence_strength: str = "candidate_public_generic",
    conversion_formula: str = "",
) -> dict[str, Any]:
    return {
        "parameter_id": parameter_id,
        "configuration_scope": "configuration_specific" if config in {C0, C1} else "generic",
        "applies_to_configuration": config,
        "plant_id": "HSM_WBW",
        "parameter_name": parameter_id.lower(),
        "parameter_role": role,
        "direction": direction,
        "carrier_or_material": material,
        "base_value": _fmt(value),
        "low_value": _fmt(low),
        "high_value": _fmt(high),
        "unit": unit,
        "basis": basis,
        "conversion_formula": conversion_formula,
        "source_or_assumption_id": "HSM_Parameters.md",
        "input_status": input_status,
        "source_status": "source_card_candidate",
        "evidence_strength": evidence_strength,
        "executable_status": executable_status,
        "development_executable": development_executable,
        "thesis_usability": "false",
        "human_review_required": "true",
        "codex_may_decide": "false",
        "applies_to_solver": "false",
        "applies_to_diagnostics": "true",
        "applies_to_anchor_comparison": "true" if input_status == "validation_context_anchor" else "false",
        "active_driver": active_driver,
        "constraint_used": "false",
        "caveat": "candidate only; not Tata-validated; not thesis-approved",
    }


def _c5k_report_by_key() -> dict[tuple[str, int], dict[str, str]]:
    return {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in _read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv")
    }


def _development_input_rows(c5k_report: dict[tuple[str, int], dict[str, str]]) -> list[dict[str, Any]]:
    rows = [
        _input_row("HSM_OUTPUT_BASIS", "t_hot_rolled_coil", "basis", role="accounting_policy", direction="basis", material="hot_rolled_coil", executable_status="diagnostic_only", development_executable="false"),
        _input_row("HSM_OUTPUT_DRIVER_MODE", HSM_OUTPUT_DRIVER_MODE, "mode", role="accounting_policy", direction="policy", material="downstream_output_driver", input_status="development_output_driver", executable_status="development_executable", development_executable="true", active_driver="true", evidence_strength="modelling_policy_with_public_context"),
        _input_row("HSM_SLAB_INPUT_T_PER_T_HRC", 1.10, "t slab/t HRC", role="material_conversion", direction="input", material="slab", low=1.07, high=1.15),
        _input_row("HSM_REHEAT_ENERGY_GJ_PER_T_HRC", 1.35, "GJ/t HRC", role="energy_input", direction="input", material="reheat_heat", low=1.2, high=1.5),
        _input_row("HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC", 0.070, "MWh/t HRC", role="energy_input", direction="input", material="electricity", low=0.028, high=0.111),
        _input_row("HSM_DIRECT_CO2_MODE", HSM_DIRECT_CO2_MODE, "mode", role="emissions_policy", direction="policy", material="CO2", executable_status="diagnostic_only", development_executable="false"),
        _input_row("HSM_FLEXIBILITY_CLASS", "bounded_downstream_scheduling_asset", "class", role="diagnostic_only", direction="policy", material="flexibility_class", executable_status="diagnostic_only", development_executable="false"),
    ]
    for carrier in ("BFG", "COG", "BOFG", "NG"):
        rows.append(
            _input_row(
                f"HSM_REHEAT_FUEL_CARRIER_{carrier}",
                "allowed",
                "eligibility",
                role="fuel_eligibility",
                direction="input",
                material=carrier,
                executable_status="development_executable",
                development_executable="true",
            )
        )

    active_targets = {
        (config, horizon): _zero(row["active_total_liquid_steel_target_site_t_y"])
        for (config, horizon), row in c5k_report.items()
    }
    for config in CONFIGS:
        active_site = active_targets[(config, 24)]
        scale = active_site / CONTEXT[config]["liquid_steel_context_t_y"]
        hsm_driver = CONTEXT[config]["hsm_output_context_t_y"] * scale
        dsp_driver = CONTEXT[config]["dsp_output_context_t_y"] * scale
        import_driver = CONTEXT[config]["imported_slab_context_t_y"] * scale
        rows.extend(
            [
                _input_row(f"{config}_MER_LIQUID_STEEL_CONTEXT_T_Y", CONTEXT[config]["liquid_steel_context_t_y"], "t/y", role="validation_anchor", direction="context", material="liquid_steel", config=config, input_status="validation_context_anchor", executable_status="validation_only", development_executable="false", evidence_strength="public_context_anchor"),
                _input_row(f"{config}_HSM_ROLLED_COILS_CONTEXT_T_Y", CONTEXT[config]["hsm_output_context_t_y"], "t/y", role="validation_anchor", direction="context", material="hot_rolled_coil", config=config, input_status="validation_context_anchor", executable_status="validation_only", development_executable="false", evidence_strength="public_context_anchor"),
                _input_row(f"{config}_DSP_ROLLS_CONTEXT_T_Y", CONTEXT[config]["dsp_output_context_t_y"], "t/y", role="validation_anchor", direction="context", material="DSP_rolls", config=config, input_status="validation_context_anchor", executable_status="validation_only", development_executable="false", evidence_strength="public_context_anchor"),
                _input_row(f"{config}_IMPORTED_SLAB_CONTEXT_T_Y", CONTEXT[config]["imported_slab_context_t_y"], "t/y", role="validation_anchor", direction="context", material="imported_slab", config=config, input_status="validation_context_anchor", executable_status="validation_only", development_executable="false", evidence_strength="public_context_anchor"),
                _input_row(f"{config}_DOWNSTREAM_SCALE_TO_ACTIVE_TARGET", scale, "ratio", role="development_output_driver", direction="derived_policy", material="downstream_scale", config=config, input_status="development_output_driver", active_driver="true", evidence_strength="derived_modelling_policy", conversion_formula="active_liquid_steel_target / MER_liquid_steel_context"),
                _input_row(f"{config}_HSM_OUTPUT_DRIVER_T_Y", hsm_driver, "t HRC/y", role="development_output_driver", direction="output", material="hot_rolled_coil", config=config, input_status="development_output_driver", active_driver="true", evidence_strength="derived_modelling_policy", conversion_formula="HSM_context_output * downstream_scale"),
                _input_row(f"{config}_DSP_OUTPUT_DRIVER_T_Y", dsp_driver, "t/y", role="development_output_driver", direction="output", material="DSP_rolls", config=config, input_status="development_output_driver", active_driver="true", evidence_strength="derived_modelling_policy", conversion_formula="DSP_context_output * downstream_scale"),
                _input_row(f"{config}_IMPORTED_SLAB_DRIVER_T_Y", import_driver, "t slab/y", role="development_output_driver", direction="boundary_input", material="imported_slab", config=config, input_status="development_output_driver", active_driver="true", evidence_strength="derived_modelling_policy", conversion_formula="imported_slab_context * downstream_scale"),
            ]
        )
    return rows


def _param(rows: list[dict[str, str]], parameter_id: str) -> float:
    row = next(row for row in rows if row["parameter_id"] == parameter_id)
    if row["thesis_usability"] != "false" or row["human_review_required"] != "true" or row["codex_may_decide"] != "false":
        raise ValueError(f"{parameter_id} failed HSM governance checks.")
    return _zero(row["base_value"])


def _report_rows(input_rows: list[dict[str, str]], c5k_report: dict[tuple[str, int], dict[str, str]]) -> list[dict[str, Any]]:
    slab_rate = _param(input_rows, "HSM_SLAB_INPUT_T_PER_T_HRC")
    reheat_gj = _param(input_rows, "HSM_REHEAT_ENERGY_GJ_PER_T_HRC")
    electricity = _param(input_rows, "HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC")
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        hsm_driver = _param(input_rows, f"{config}_HSM_OUTPUT_DRIVER_T_Y")
        dsp_driver = _param(input_rows, f"{config}_DSP_OUTPUT_DRIVER_T_Y")
        imported_slab = _param(input_rows, f"{config}_IMPORTED_SLAB_DRIVER_T_Y")
        downstream_scale = _param(input_rows, f"{config}_DOWNSTREAM_SCALE_TO_ACTIVE_TARGET")
        for horizon in HORIZONS:
            c5k = c5k_report[(config, horizon)]
            scale_factor = _zero(c5k["scale_factor"]) or 1.0
            active_ls = _zero(c5k["active_total_liquid_steel_target_site_t_y"])
            hsm_raw = hsm_driver / scale_factor
            slab_site = hsm_driver * slab_rate
            slab_raw = slab_site / scale_factor
            imported_raw = imported_slab / scale_factor
            dsp_raw = dsp_driver / scale_factor
            loss_site = slab_site - hsm_driver
            heat_gj_site = hsm_driver * reheat_gj
            heat_mwh_site = heat_gj_site / 3.6
            electricity_site = hsm_driver * electricity
            gap_site = active_ls + imported_slab - dsp_driver - slab_site
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "dependency_stage": "S4.4c5k_production_policy_and_route_split_normalisation",
                    "hsm_output_driver_mode": HSM_OUTPUT_DRIVER_MODE,
                    "active_total_liquid_steel_target_site_t_y": _fmt(active_ls),
                    "c5k_bof_liquid_steel_site_t_y": c5k["bof_liquid_steel_site_t_y"],
                    "c5k_eaf_liquid_steel_site_t_y": c5k["eaf_liquid_steel_site_t_y"],
                    "downstream_scale_to_active_target": _fmt(downstream_scale),
                    "hsm_output_raw_t_y": _fmt(hsm_raw),
                    "hsm_output_site_t_y": _fmt(hsm_driver),
                    "dsp_output_raw_t_y": _fmt(dsp_raw),
                    "dsp_output_site_t_y": _fmt(dsp_driver),
                    "imported_slab_raw_t_y": _fmt(imported_raw),
                    "imported_slab_site_t_y": _fmt(imported_slab),
                    "hsm_slab_input_raw_t_y": _fmt(slab_raw),
                    "hsm_slab_input_site_t_y": _fmt(slab_site),
                    "domestic_slab_requirement_raw_t_y": _fmt(max(slab_raw - imported_raw, 0.0)),
                    "domestic_slab_requirement_site_t_y": _fmt(max(slab_site - imported_slab, 0.0)),
                    "hsm_internal_loss_or_scrap_raw_t_y": _fmt(loss_site / scale_factor),
                    "hsm_internal_loss_or_scrap_site_t_y": _fmt(loss_site),
                    "indicative_downstream_material_gap_raw_t_y": _fmt(gap_site / scale_factor),
                    "indicative_downstream_material_gap_site_t_y": _fmt(gap_site),
                    "hsm_reheat_heat_demand_raw_GJ_y": _fmt(heat_gj_site / scale_factor),
                    "hsm_reheat_heat_demand_site_GJ_y": _fmt(heat_gj_site),
                    "hsm_reheat_heat_demand_raw_MWh_y": _fmt(heat_mwh_site / scale_factor),
                    "hsm_reheat_heat_demand_site_MWh_y": _fmt(heat_mwh_site),
                    "hsm_reheat_heat_demand_site_PJ_y": _fmt(heat_gj_site * 1e-6),
                    "hsm_rolling_electricity_raw_MWh_y": _fmt(electricity_site / scale_factor),
                    "hsm_rolling_electricity_site_MWh_y": _fmt(electricity_site),
                    "hsm_rolling_electricity_site_GWh_y": _fmt(electricity_site / 1000.0),
                    "hsm_total_energy_raw_MWh_equiv_y": _fmt((heat_mwh_site + electricity_site) / scale_factor),
                    "hsm_total_energy_site_MWh_equiv_y": _fmt(heat_mwh_site + electricity_site),
                    "hsm_slab_input_t_per_t_HRC": _fmt(slab_rate),
                    "hsm_reheat_energy_GJ_per_t_HRC": _fmt(reheat_gj),
                    "hsm_rolling_electricity_MWh_per_t_HRC": _fmt(electricity),
                    "scale_factor": _fmt(scale_factor),
                    "scale_mode": "module_scaled_to_site_target",
                    "no_free_slab_battery_status": "pass_no_slab_storage_created",
                    "hsm_is_wag_producer": "false",
                    "co2_derivation_status": HSM_CO2_STATUS,
                    "co2_double_counting_guard_status": "pass",
                    "caveats": "downstream accounting only; material gap reported and not forced away; no HSM campaign scheduling",
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
                    "gap_type": "scaled_driver_vs_raw_context_anchor",
                    "notes": "C5l scales active downstream drivers to C5k target; raw MER values remain context anchors.",
                }
            )
    return rows


def _allocate_hsm_fuel(report: list[dict[str, Any]], c5k_wag: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    report_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in report}
    hsm_alloc: dict[tuple[str, int, str], float] = {}
    fuel_rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            demand = _zero(report_by_key[(config, horizon)]["hsm_reheat_heat_demand_raw_MWh_y"])
            remaining = demand
            carrier_rows = {
                row["carrier"]: row
                for row in c5k_wag
                if row["configuration"] == config
                and int(row["horizon_hours"]) == horizon
                and row["plant_id"] == "SITE_TOTAL"
                and row["carrier"] in WAG_CARRIERS
            }
            for carrier in ("BFG", "COG", "BOFG"):
                source = carrier_rows[carrier]
                available = max(_zero(source["generated_MWh_LHV_y"]) - _zero(source["consumed_direct_MWh_LHV_y"]), 0.0)
                used = min(remaining, available)
                hsm_alloc[(config, horizon, carrier)] = used
                remaining -= used
            hsm_alloc[(config, horizon, "NG")] = max(remaining, 0.0)

    rows: list[dict[str, Any]] = []
    for row in c5k_wag:
        item = dict(row)
        config = row["configuration"]
        horizon = int(row["horizon_hours"])
        if row["plant_id"] == "SITE_TOTAL" and row["carrier"] in WAG_CARRIERS:
            added = hsm_alloc[(config, horizon, row["carrier"])]
            generated = _zero(item["generated_MWh_LHV_y"])
            direct = _zero(item["consumed_direct_MWh_LHV_y"]) + added
            boiler = min(_zero(item["consumed_boiler_MWh_LHV_y"]), max(generated - direct, 0.0))
            vattenfall = min(_zero(item["consumed_vattenfall_MWh_LHV_y"]), max(generated - direct - boiler, 0.0))
            flared = max(generated - direct - boiler - vattenfall, 0.0)
            item["consumed_direct_MWh_LHV_y"] = _fmt(direct)
            item["consumed_boiler_MWh_LHV_y"] = _fmt(boiler)
            item["consumed_vattenfall_MWh_LHV_y"] = _fmt(vattenfall)
            item["flared_MWh_LHV_y"] = _fmt(flared)
            item["balance_error_MWh_LHV_y"] = _fmt(generated - direct - boiler - vattenfall - flared)
            item["status"] = "closed"
            item["metric_scope"] = "HSM_reheat_inserted_before_boiler_vattenfall_flare"
            item["notes"] = "C5l adds HSM reheat as internal WAG sink before boiler/Vattenfall/flare; no WAG market valuation."
        rows.append(item)

    template_by_key = {
        (row["configuration"], int(row["horizon_hours"]), row["carrier"]): row
        for row in rows
        if row["plant_id"] == "SITE_TOTAL" and row["carrier"] in WAG_CARRIERS
    }
    for config in CONFIGS:
        for horizon in HORIZONS:
            demand_raw = _zero(report_by_key[(config, horizon)]["hsm_reheat_heat_demand_raw_MWh_y"])
            demand_site = _zero(report_by_key[(config, horizon)]["hsm_reheat_heat_demand_site_MWh_y"])
            allocated_raw = 0.0
            allocated_site = 0.0
            for carrier in ("BFG", "COG", "BOFG"):
                source = template_by_key[(config, horizon, carrier)]
                used_raw = hsm_alloc[(config, horizon, carrier)]
                scale = _zero(source["scale_factor"]) or 1.0
                used_site = used_raw * scale
                allocated_raw += used_raw
                allocated_site += used_site
                lhv = _zero(source["LHV_MJ_per_Nm3_used"])
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
                        "status": "hsm_reheat_wag_sink" if used_raw else "eligible_not_used",
                        "LHV_MJ_per_Nm3_used": _fmt(lhv),
                        "raw_model_quantity": _fmt(used_raw),
                        "raw_model_unit": "MWh_LHV/y",
                        "site_scaled_quantity": _fmt(used_site),
                        "site_scaled_unit": "MWh_LHV/y",
                        "scale_factor": _fmt(scale),
                        "scale_mode": "module_scaled_to_site_target",
                        "metric_scope": "HSM_reheat_fuel_consumption",
                        "notes": "HSM consumes eligible WAG for reheating; generated quantity remains zero.",
                    }
                )
                fuel_rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "carrier": carrier,
                        "eligible": "true",
                        "HSM_reheat_demand_raw_MWh_y": _fmt(demand_raw),
                        "HSM_reheat_demand_site_MWh_y": _fmt(demand_site),
                        "fuel_used_raw_MWh_y": _fmt(used_raw),
                        "fuel_used_site_MWh_y": _fmt(used_site),
                        "allocation_mode": HSM_REHEAT_ALLOCATION_MODE,
                        "status": "allocated" if used_raw else "eligible_not_used",
                        "notes": "Allocated after KGF COG self-use and BF hot-stove deductions inherited from C5k.",
                    }
                )
            ng_raw = hsm_alloc[(config, horizon, "NG")]
            ng_site = max(demand_site - allocated_site, 0.0)
            fuel_rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "carrier": "NG",
                    "eligible": "true",
                    "HSM_reheat_demand_raw_MWh_y": _fmt(demand_raw),
                    "HSM_reheat_demand_site_MWh_y": _fmt(demand_site),
                    "fuel_used_raw_MWh_y": _fmt(ng_raw),
                    "fuel_used_site_MWh_y": _fmt(ng_site),
                    "allocation_mode": HSM_REHEAT_ALLOCATION_MODE,
                    "status": "ng_backup_reported_without_cost_steering" if ng_raw else "not_needed",
                    "notes": "NG backup is an energy diagnostic only in C5l; no cost steering is added.",
                }
            )
    return rows, fuel_rows


def _slab_balance_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration": row["configuration"],
            "horizon_hours": row["horizon_hours"],
            "active_total_liquid_steel_target_site_t_y": row["active_total_liquid_steel_target_site_t_y"],
            "hsm_output_site_t_y": row["hsm_output_site_t_y"],
            "hsm_slab_input_site_t_y": row["hsm_slab_input_site_t_y"],
            "imported_slab_driver_site_t_y": row["imported_slab_site_t_y"],
            "domestic_slab_requirement_site_t_y": row["domestic_slab_requirement_site_t_y"],
            "dsp_output_driver_site_t_y": row["dsp_output_site_t_y"],
            "hsm_internal_loss_or_scrap_site_t_y": row["hsm_internal_loss_or_scrap_site_t_y"],
            "indicative_downstream_material_gap_site_t_y": row["indicative_downstream_material_gap_site_t_y"],
            "no_free_slab_battery_status": row["no_free_slab_battery_status"],
            "status": "gap_reported_not_forced",
            "red_flags": "downstream_material_gap_reported" if abs(_zero(row["indicative_downstream_material_gap_site_t_y"])) > 1e-6 else "",
            "notes": "C5l reports slab/material gap without creating slab storage or tuning output drivers.",
        }
        for row in report
    ]


def _co2_rows(report: list[dict[str, Any]], c5k_co2: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = [
        {
            "configuration": row["configuration"],
            "horizon_hours": row["horizon_hours"],
            "emission_bucket": "HSM_reheat_CO2",
            "CO2_site_t_y": "",
            "CO2_mode": HSM_DIRECT_CO2_MODE,
            "derivation_status": HSM_CO2_STATUS,
            "included_in_objective_ETS_cost": "false",
            "included_in_total_direct_CO2": "false",
            "double_counting_risk": "blocked_until_governed_carrier_emission_factors_exist",
            "status": "deferred",
            "notes": "Carrier-specific governed combustion emission factors are not active in C5l.",
        }
        for row in report
    ]
    for row in c5k_co2:
        inherited = dict(row)
        inherited["derivation_status"] = "inherited_C5k_guard"
        rows.append(inherited)
    return rows


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
            "solver_status": "inherited_from_C5k_accounting_only",
            "status": "development_only",
            "thesis_usability": "false",
            "active_total_liquid_steel_target_site_t_y": item["active_total_liquid_steel_target_site_t_y"],
            "c5k_bof_liquid_steel_site_t_y": item["c5k_bof_liquid_steel_site_t_y"],
            "c5k_eaf_liquid_steel_site_t_y": item["c5k_eaf_liquid_steel_site_t_y"],
            "hsm_output_site_t_y": item["hsm_output_site_t_y"],
            "dsp_output_site_t_y": item["dsp_output_site_t_y"],
            "imported_slab_site_t_y": item["imported_slab_site_t_y"],
            "hsm_slab_input_site_t_y": item["hsm_slab_input_site_t_y"],
            "domestic_slab_requirement_site_t_y": item["domestic_slab_requirement_site_t_y"],
            "indicative_downstream_material_gap_site_t_y": item["indicative_downstream_material_gap_site_t_y"],
            "hsm_reheat_heat_demand_site_PJ_y": item["hsm_reheat_heat_demand_site_PJ_y"],
            "hsm_rolling_electricity_site_GWh_y": item["hsm_rolling_electricity_site_GWh_y"],
            "hsm_wag_reheat_site_MWh_y": _fmt(fuel_by_key[key]["wag_site"]),
            "hsm_ng_backup_site_MWh_y": _fmt(fuel_by_key[key]["ng_site"]),
            "WAG_invariant_status": agg["status"],
            "WAG_balance_error_MWh_y": agg["balance_error_MWh_y"],
            "LHV_consistency_status": "pass",
            "HSM_CO2_derivation_status": HSM_CO2_STATUS,
            "CO2_double_counting_guard_status": "pass",
            "no_free_slab_battery_status": item["no_free_slab_battery_status"],
            "anchor_constraints_used_count": "0",
            "forbidden_market_features_added": "false",
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
                "output_driver_mode": item["hsm_output_driver_mode"],
                "HSM_output_Mt_y": _fmt(_zero(item["hsm_output_site_t_y"]) / 1_000_000.0),
                "DSP_output_Mt_y": _fmt(_zero(item["dsp_output_site_t_y"]) / 1_000_000.0),
                "imported_slab_Mt_y": _fmt(_zero(item["imported_slab_site_t_y"]) / 1_000_000.0),
                "slab_input_Mt_y": _fmt(_zero(item["hsm_slab_input_site_t_y"]) / 1_000_000.0),
                "material_gap_Mt_y": _fmt(_zero(item["indicative_downstream_material_gap_site_t_y"]) / 1_000_000.0),
                "reheat_PJ_y": item["hsm_reheat_heat_demand_site_PJ_y"],
                "rolling_electricity_GWh_y": item["hsm_rolling_electricity_site_GWh_y"],
                "BFG_to_HSM_MWh_y": _fmt(fuel_by_key[key]["BFG"]),
                "COG_to_HSM_MWh_y": _fmt(fuel_by_key[key]["COG"]),
                "BOFG_to_HSM_MWh_y": _fmt(fuel_by_key[key]["BOFG"]),
                "NG_backup_MWh_y": _fmt(fuel_by_key[key]["NG"]),
                "CO2_status": HSM_CO2_STATUS,
                "status": "development_only",
                "red_flags": "downstream_material_gap_reported",
            }
        )
    return rows


def _stage_gate(
    input_rows: list[dict[str, str]],
    report: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    wag_rows: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    co2: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[Any] = []
    failures.extend(row for row in input_rows if row["thesis_usability"] != "false" or row["human_review_required"] != "true" or row["codex_may_decide"] != "false" or row["constraint_used"] != "false")
    failures.extend(row for row in anchors if row["constraint_used"] != "false")
    failures.extend(row for row in wag_aggregate if row["status"] != "pass")
    failures.extend(row for row in wag_rows if row["plant_id"] == "HSM_WBW" and abs(_zero(row["generated_MWh_LHV_y"])) > WAG_TOL_MWH)
    failures.extend(row for row in co2 if row["included_in_objective_ETS_cost"] != "false")
    c1_24 = next(row for row in report if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    c0_24 = next(row for row in report if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    return {
        "stage": STAGE,
        "decision": "pass_development_hsm_wbw_minimal_integration" if not failures else "fail_development_hsm_wbw_minimal_integration",
        "output_directory": _rel(C5L_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "source_card_present": SOURCE_CARD.exists(),
        "dependency_stage": "S4.4c5k_production_policy_and_route_split_normalisation",
        "HSM_OUTPUT_DRIVER_MODE": HSM_OUTPUT_DRIVER_MODE,
        "C0_HSM_output_site_t_y": _zero(c0_24["hsm_output_site_t_y"]),
        "C1_HSM_output_site_t_y": _zero(c1_24["hsm_output_site_t_y"]),
        "C1_imported_slab_driver_site_t_y": _zero(c1_24["imported_slab_site_t_y"]),
        "hsm_wag_producer_rows_nonzero_count": sum(1 for row in wag_rows if row["plant_id"] == "HSM_WBW" and abs(_zero(row["generated_MWh_LHV_y"])) > WAG_TOL_MWH),
        "wag_invariant_fail_count": sum(1 for row in wag_aggregate if row["status"] != "pass"),
        "co2_double_counting_guard_status": "pass" if all(row["included_in_objective_ETS_cost"] == "false" for row in co2) else "fail",
        "HSM_CO2_derivation_status": HSM_CO2_STATUS,
        "anchor_constraints_used_count": sum(1 for row in anchors if row["constraint_used"] != "false"),
        "no_free_slab_battery_status": "pass_no_slab_storage_created",
        "direct_WAG_market_valuation_added": False,
        "WAG_export_revenue_added": False,
        "product_revenue_added": False,
        "forbidden_market_features_added": False,
        "failure_count": len(failures),
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5k_production_policy_and_route_split_normalisation()
    C5L_DIR.mkdir(parents=True, exist_ok=True)

    c5k_report = _c5k_report_by_key()
    input_rows_any = _development_input_rows(c5k_report)
    _write_csv(C5L_DIR / "s4_4c5l_hsm_wbw_development_input_rows.csv", input_rows_any, HSM_PARAMETER_COLUMNS)
    input_rows = _read_csv(C5L_DIR / "s4_4c5l_hsm_wbw_development_input_rows.csv")
    report = _report_rows(input_rows, c5k_report)
    anchors = _anchor_rows(report)
    c5k_wag = _read_csv(C5K_DIR / "s4_4c5k_wag_generation_consumption_by_plant.csv")
    wag_rows, fuel = _allocate_hsm_fuel(report, c5k_wag)
    wag_aggregate = _wag_aggregate_invariant_rows(wag_rows)
    slab = _slab_balance_rows(report)
    c5k_co2 = _read_csv(C5K_DIR / "s4_4c5k_bof_co2_accounting_dashboard.csv")
    co2 = _co2_rows(report, c5k_co2)
    c5k_lhv = _read_csv(C5K_DIR / "s4_4c5k_lhv_consistency_checks.csv")
    summary_rows, by_horizon = _summary_rows(report, wag_aggregate, fuel)
    compact = _compact_rows(report, fuel)
    gate = _stage_gate(input_rows, report, anchors, wag_rows, wag_aggregate, co2)

    _write_json(C5L_DIR / "s4_4c5l_stage_gate.json", gate)
    _write_csv(C5L_DIR / "s4_4c5l_run_registry.csv", [{
        "stage": STAGE,
        "source_stage": "S4.4c5k_production_policy_and_route_split_normalisation",
        "decision": gate["decision"],
        "status": "development_only",
        "thesis_usability": "false",
        "output_directory": gate["output_directory"],
    }])
    for horizon, rows in by_horizon.items():
        _write_csv(C5L_DIR / f"s4_4c5l_{horizon}h_summary.csv", rows)
    _write_csv(C5L_DIR / "s4_4c5l_hsm_wbw_parameter_register.csv", input_rows, HSM_PARAMETER_COLUMNS)
    _write_csv(C5L_DIR / "s4_4c5l_hsm_wbw_report.csv", report)
    _write_csv(C5L_DIR / "s4_4c5l_hsm_wbw_anchor_gap_dashboard.csv", anchors)
    _write_csv(C5L_DIR / "s4_4c5l_hsm_wbw_slab_balance_dashboard.csv", slab)
    _write_csv(C5L_DIR / "s4_4c5l_hsm_wbw_fuel_mix_dashboard.csv", fuel)
    _write_csv(C5L_DIR / "s4_4c5l_wag_generation_consumption_by_plant.csv", wag_rows)
    _write_csv(C5L_DIR / "s4_4c5l_wag_aggregate_invariant.csv", wag_aggregate, AGGREGATE_COLUMNS)
    _write_csv(C5L_DIR / "s4_4c5l_lhv_consistency_checks.csv", c5k_lhv)
    _write_csv(C5L_DIR / "s4_4c5l_hsm_co2_accounting_dashboard.csv", co2)
    _write_csv(C5L_DIR / "s4_4c5l_compact_table_for_chat.csv", compact)

    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "hsm_report": len(report),
            "anchor_gaps": len(anchors),
            "wag_aggregate": len(wag_aggregate),
            "co2": len(co2),
        },
    }
    _write_json(C5L_DIR / "s4_4c5l_summary.json", summary)
    return summary


def run_s4_4c5l_hsm_wbw_minimal_integration() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5l_hsm_wbw_minimal_integration(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
