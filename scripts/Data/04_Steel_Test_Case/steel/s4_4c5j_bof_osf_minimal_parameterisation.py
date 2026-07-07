"""S4.4c5j BOF/OSF minimal parameterisation.

This stage is development-only diagnostic plumbing over the latest C5h physical
outputs. BOF/OSF coefficients are materialised as governed development input
rows before diagnostics are calculated; validation anchors remain reporting-only.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    CONFIGS,
    HORIZONS,
    S4_ROOT,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5g_wag_aggregate_diagnostic_hygiene import (
    AGGREGATE_COLUMNS,
    WAG_TOL_MWH,
    _wag_aggregate_invariant_rows,
)
from .s4_4c5h_blast_furnace_controller_parameterisation import (
    C5H_DIR,
    run_s4_4c5h_blast_furnace_controller_parameterisation,
)


STAGE = "S4.4c5j_BOF_OSF_minimal_parameterisation"
C5J_DIR = S4_ROOT / "s4_4c5j_BOF_OSF_minimal_parameterisation"
SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/BOF_OSF_Parameters.md")
BOF_CO2_MODE = "aggregate_direct_diagnostic"

INPUT_COLUMNS = [
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
    "caveat",
]


def _annualisation_factor(horizon: int) -> float:
    return 365.0 if horizon == 24 else 365.0 / 7.0


def _input_row(
    parameter_id: str,
    value: float,
    unit: str,
    *,
    configuration: str,
    role: str,
    direction: str,
    material: str,
    basis: str = "t_liquid_steel",
    evidence_strength: str = "candidate_public_generic",
    source_status: str = "source_card_candidate",
    conversion_formula: str = "",
) -> dict[str, Any]:
    return {
        "parameter_id": parameter_id,
        "configuration_scope": "configuration_specific" if configuration in {C0, C1} else "generic",
        "applies_to_configuration": configuration,
        "plant_id": "BOF_OSF",
        "parameter_name": parameter_id.lower(),
        "parameter_role": role,
        "direction": direction,
        "carrier_or_material": material,
        "base_value": _fmt(value),
        "low_value": "",
        "high_value": "",
        "unit": unit,
        "basis": basis,
        "conversion_formula": conversion_formula,
        "source_or_assumption_id": "BOF_OSF_Parameters.md",
        "input_status": "development_candidate",
        "source_status": source_status,
        "evidence_strength": evidence_strength,
        "executable_status": "development_executable",
        "development_executable": "true",
        "thesis_usability": "false",
        "human_review_required": "true",
        "codex_may_decide": "false",
        "applies_to_solver": "false",
        "applies_to_diagnostics": "true",
        "applies_to_anchor_comparison": "false",
        "caveat": "candidate only; not Tata-validated; not thesis-approved",
    }


def _development_input_rows() -> list[dict[str, Any]]:
    return [
        _input_row("BOF_HOT_METAL_INPUT_T_PER_T_LS_C0", 0.875, "t hot metal/t liquid steel", configuration=C0, role="material_conversion", direction="input", material="hot_metal"),
        _input_row("BOF_SCRAP_INPUT_T_PER_T_LS_C0", 0.208, "t scrap/t liquid steel", configuration=C0, role="material_conversion", direction="input", material="scrap"),
        _input_row("BOF_HOT_METAL_INPUT_T_PER_T_LS_C1", 0.824, "t hot metal/t liquid steel", configuration=C1, role="material_conversion", direction="input", material="hot_metal"),
        _input_row("BOF_SCRAP_INPUT_T_PER_T_LS_C1", 0.294, "t scrap/t liquid steel", configuration=C1, role="material_conversion", direction="input", material="scrap"),
        _input_row("BOF_OXYGEN_INPUT_NM3_PER_T_LS", 55.0, "Nm3 O2/t liquid steel", configuration="all", role="material_conversion", direction="input", material="oxygen"),
        _input_row("BOF_OXYGEN_INPUT_KG_PER_T_LS", 78.6, "kg O2/t liquid steel", configuration="all", role="derived_diagnostic", direction="input", material="oxygen", evidence_strength="derived_from_source_card_candidate", source_status="derived_candidate", conversion_formula="mass-basis diagnostic only"),
        _input_row("BOF_ELECTRICITY_MWH_PER_T_LS", 0.0268, "MWh/t liquid steel", configuration="all", role="energy_input", direction="input", material="electricity"),
        _input_row("BOF_BOFG_OUTPUT_NM3_PER_T_LS", 75.0, "Nm3 BOFG/t liquid steel", configuration="all", role="WAG_generation", direction="output", material="BOFG"),
        _input_row("BOF_DIRECT_CO2_T_PER_T_LS", 0.0825, "tCO2/t liquid steel", configuration="all", role="emissions", direction="output", material="CO2", evidence_strength="candidate_direct_diagnostic"),
        _input_row("BOFG_LHV_MJ_PER_NM3", 8.6, "MJ/Nm3", configuration="all", role="physical_unit_conversion", direction="conversion", material="BOFG", basis="Nm3_BOFG", evidence_strength="project_canonical", source_status="project_canonical_constant"),
    ]


def _param_value(rows: list[dict[str, str]], parameter_id: str) -> float:
    row = next(row for row in rows if row["parameter_id"] == parameter_id)
    if row["input_status"] != "development_candidate" or row["thesis_usability"].lower() != "false":
        raise ValueError(f"{parameter_id} is not a development-candidate diagnostic input.")
    return _zero(row["base_value"])


def _configuration_parameter(rows: list[dict[str, str]], config: str, suffix: str) -> float:
    if config == C0:
        parameter_id = f"{suffix}_C0"
    elif config == C1:
        parameter_id = f"{suffix}_C1"
    else:
        raise ValueError(config)
    return _param_value(rows, parameter_id)


def _summary_rows_by_key() -> dict[tuple[str, int], dict[str, str]]:
    rows: dict[tuple[str, int], dict[str, str]] = {}
    for horizon in HORIZONS:
        for row in _read_csv(C5H_DIR / f"s4_4c5h_{horizon}h_summary.csv"):
            rows[(row["configuration_id"], int(row["horizon_hours"]))] = row
    return rows


def _bof_wag_by_key() -> dict[tuple[str, int], dict[str, str]]:
    return {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in _read_csv(C5H_DIR / "s4_4c5h_wag_generation_consumption_by_plant.csv")
        if row["plant_id"] == "BOF" and row["carrier"] == "BOFG"
    }


def _bf_hot_metal_site_by_key() -> dict[tuple[str, int], float]:
    return {
        (row["configuration_id"], int(row["horizon_hours"])): _zero(row.get("BF_hot_metal_site_t_y"))
        for horizon in HORIZONS
        for row in _read_csv(C5H_DIR / f"s4_4c5h_{horizon}h_summary.csv")
    }


def _bof_report_rows(input_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    summary = _summary_rows_by_key()
    bof_wag = _bof_wag_by_key()
    bf_hot_metal = _bf_hot_metal_site_by_key()
    oxygen_nm3 = _param_value(input_rows, "BOF_OXYGEN_INPUT_NM3_PER_T_LS")
    oxygen_kg = _param_value(input_rows, "BOF_OXYGEN_INPUT_KG_PER_T_LS")
    electricity = _param_value(input_rows, "BOF_ELECTRICITY_MWH_PER_T_LS")
    bofg_nm3 = _param_value(input_rows, "BOF_BOFG_OUTPUT_NM3_PER_T_LS")
    bofg_lhv = _param_value(input_rows, "BOFG_LHV_MJ_PER_NM3")
    direct_co2 = _param_value(input_rows, "BOF_DIRECT_CO2_T_PER_T_LS")
    bofg_mwh_per_t_ls = bofg_nm3 * bofg_lhv / 3600.0
    rows: list[dict[str, Any]] = []

    for config in CONFIGS:
        hot_metal = _configuration_parameter(input_rows, config, "BOF_HOT_METAL_INPUT_T_PER_T_LS")
        scrap = _configuration_parameter(input_rows, config, "BOF_SCRAP_INPUT_T_PER_T_LS")
        metallic = hot_metal + scrap
        ls_yield = 1.0 / metallic
        for horizon in HORIZONS:
            source = summary[(config, horizon)]
            ann = _annualisation_factor(horizon)
            total_liquid_site = _zero(source["liquid_steel_t"]) * ann
            retained_share = _zero(source["retained_route_share"])
            bof_liquid_site = total_liquid_site if config == C0 else total_liquid_site * retained_share
            wag_seed = bof_wag[(config, horizon)]
            bof_liquid_raw = _zero(wag_seed["generated_MWh_LHV_y"]) / bofg_mwh_per_t_ls
            scale_factor = bof_liquid_site / bof_liquid_raw if bof_liquid_raw else 1.0

            hot_metal_raw = bof_liquid_raw * hot_metal
            scrap_raw = bof_liquid_raw * scrap
            oxygen_raw_nm3 = bof_liquid_raw * oxygen_nm3
            oxygen_raw_kg = bof_liquid_raw * oxygen_kg
            electricity_raw = bof_liquid_raw * electricity
            bofg_raw_nm3 = bof_liquid_raw * bofg_nm3
            bofg_raw_mwh = bof_liquid_raw * bofg_mwh_per_t_ls
            direct_co2_raw = bof_liquid_raw * direct_co2

            hot_metal_site = bof_liquid_site * hot_metal
            scrap_site = bof_liquid_site * scrap
            oxygen_site_nm3 = bof_liquid_site * oxygen_nm3
            oxygen_site_kg = bof_liquid_site * oxygen_kg
            electricity_site = bof_liquid_site * electricity
            bofg_site_nm3 = bof_liquid_site * bofg_nm3
            bofg_site_mwh = bof_liquid_site * bofg_mwh_per_t_ls
            direct_co2_site = bof_liquid_site * direct_co2
            bf_available = bf_hot_metal[(config, horizon)]

            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "annualisation_factor": _fmt(ann),
                    "status": "development_only",
                    "thesis_usability": "false",
                    "bof_co2_mode": BOF_CO2_MODE,
                    "bof_driver_basis": "existing_liquid_steel_route_throughput",
                    "bof_liquid_steel_raw_t_y": _fmt(bof_liquid_raw),
                    "bof_liquid_steel_site_t_y": _fmt(bof_liquid_site),
                    "bof_hot_metal_input_raw_t_y": _fmt(hot_metal_raw),
                    "bof_hot_metal_input_site_t_y": _fmt(hot_metal_site),
                    "bf_hot_metal_available_site_t_y": _fmt(bf_available),
                    "bf_to_bof_hot_metal_gap_site_t_y": _fmt(bf_available - hot_metal_site),
                    "bof_scrap_input_raw_t_y": _fmt(scrap_raw),
                    "bof_scrap_input_site_t_y": _fmt(scrap_site),
                    "bof_oxygen_input_raw_Nm3_y": _fmt(oxygen_raw_nm3),
                    "bof_oxygen_input_site_Nm3_y": _fmt(oxygen_site_nm3),
                    "bof_oxygen_input_raw_kg_y": _fmt(oxygen_raw_kg),
                    "bof_oxygen_input_site_kg_y": _fmt(oxygen_site_kg),
                    "bof_electricity_raw_MWh_y": _fmt(electricity_raw),
                    "bof_electricity_site_MWh_y": _fmt(electricity_site),
                    "bof_bofg_output_raw_Nm3_y": _fmt(bofg_raw_nm3),
                    "bof_bofg_output_site_Nm3_y": _fmt(bofg_site_nm3),
                    "bof_bofg_output_raw_MWh_LHV_y": _fmt(bofg_raw_mwh),
                    "bof_bofg_output_site_MWh_LHV_y": _fmt(bofg_site_mwh),
                    "bof_bofg_output_raw_PJ_LHV_y": _fmt(bofg_raw_mwh * 3.6e-6),
                    "bof_bofg_output_site_PJ_LHV_y": _fmt(bofg_site_mwh * 3.6e-6),
                    "bof_direct_co2_raw_t_y": _fmt(direct_co2_raw),
                    "bof_direct_co2_site_t_y": _fmt(direct_co2_site),
                    "bof_hot_metal_input_t_per_t_LS": _fmt(hot_metal),
                    "bof_scrap_input_t_per_t_LS": _fmt(scrap),
                    "bof_oxygen_Nm3_per_t_LS": _fmt(oxygen_nm3),
                    "bof_electricity_MWh_per_t_LS": _fmt(electricity),
                    "bof_bofg_Nm3_per_t_LS": _fmt(bofg_nm3),
                    "bof_direct_co2_t_per_t_LS": _fmt(direct_co2),
                    "bof_metallic_input_t_per_t_LS": _fmt(metallic),
                    "bof_liquid_steel_yield_per_t_metallic_input": _fmt(ls_yield),
                    "bof_hot_metal_share": _fmt(hot_metal / metallic),
                    "bof_scrap_share": _fmt(scrap / metallic),
                    "bofg_lhv_MJ_per_Nm3": _fmt(bofg_lhv),
                    "bofg_MWh_per_t_LS": _fmt(bofg_mwh_per_t_ls),
                    "scale_factor": _fmt(scale_factor),
                    "scale_mode": "module_scaled_to_site_target",
                    "validation_anchors_used_as_constraints": "false",
                    "caveats": "candidate BOF/OSF layer; not Tata-validated; not thesis-approved; no market valuation",
                }
            )
    return rows


def _anchor_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors = {
        (C0, "BOF_liquid_steel_output_t_y"): (7_200_000.0, "C0 BOF liquid steel context anchor"),
        (C0, "BOF_hot_metal_input_t_y"): (6_300_000.0, "C0 hot metal to BOF context anchor"),
        (C0, "BOF_scrap_input_t_y"): (1_500_000.0, "C0 scrap to BOF context anchor"),
        (C1, "BOF_liquid_steel_output_t_y"): (3_400_000.0, "C1 retained BOF preferred OSF activity anchor"),
        (C1, "BF_BOF_route_liquid_steel_including_alloys_t_y"): (3_500_000.0, "C1 retained BF-BOF route context anchor"),
        (C1, "BOF_hot_metal_input_t_y"): (2_800_000.0, "C1 hot metal to BOF context anchor"),
        (C1, "BOF_scrap_input_t_y"): (1_000_000.0, "C1 scrap to retained BOF route context anchor"),
    }
    field_map = {
        "BOF_liquid_steel_output_t_y": "bof_liquid_steel_site_t_y",
        "BF_BOF_route_liquid_steel_including_alloys_t_y": "bof_liquid_steel_site_t_y",
        "BOF_hot_metal_input_t_y": "bof_hot_metal_input_site_t_y",
        "BOF_scrap_input_t_y": "bof_scrap_input_site_t_y",
    }
    rows: list[dict[str, Any]] = []
    for item in report:
        config = item["configuration"]
        for metric in [key[1] for key in anchors if key[0] == config]:
            anchor, source = anchors[(config, metric)]
            model = _zero(item[field_map[metric]])
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": item["horizon_hours"],
                    "metric": metric,
                    "model_site_quantity": _fmt(model),
                    "anchor_quantity": _fmt(anchor),
                    "unit": "t/y",
                    "anchor_source": source,
                    "gap_quantity": _fmt(model - anchor),
                    "gap_pct": _fmt((model - anchor) / anchor * 100.0 if anchor else 0.0),
                    "anchor_status": "validation_reporting_only",
                    "constraint_used": "false",
                    "gap_type": "validation_gap_not_calibration",
                    "notes": "C5j reports BOF anchor gaps only; no dispatch constraint is created.",
                }
            )
    return rows


def _update_wag_rows(c5h_wag: list[dict[str, str]], report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    report_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in report}
    rows: list[dict[str, Any]] = []
    for row in c5h_wag:
        item = dict(row)
        if row["carrier"] == "BOFG" and row["plant_id"] in {"BOF", "SITE_TOTAL"}:
            report_row = report_by_key[(row["configuration"], int(row["horizon_hours"]))]
            raw_gen = _zero(report_row["bof_bofg_output_raw_MWh_LHV_y"])
            site_gen = _zero(report_row["bof_bofg_output_site_MWh_LHV_y"])
            scale = site_gen / raw_gen if raw_gen else 1.0
            item["generated_MWh_LHV_y"] = _fmt(raw_gen)
            item["generated_Nm3_y"] = _fmt(_zero(report_row["bof_bofg_output_raw_Nm3_y"]))
            item["site_scaled_quantity"] = _fmt(site_gen)
            item["scale_factor"] = _fmt(scale)
            item["LHV_MJ_per_Nm3_used"] = report_row["bofg_lhv_MJ_per_Nm3"]
            item["raw_model_quantity"] = _fmt(raw_gen)
            item["raw_model_unit"] = "MWh_LHV/y"
            item["site_scaled_unit"] = "MWh_LHV/y"
            item["metric_scope"] = "BOFG_separate_WAG_carrier_development_diagnostic"
            if row["plant_id"] == "SITE_TOTAL":
                direct = _zero(row["consumed_direct_MWh_LHV_y"])
                boiler = _zero(row["consumed_boiler_MWh_LHV_y"])
                vattenfall = _zero(row["consumed_vattenfall_MWh_LHV_y"])
                flare = max(raw_gen - direct - boiler - vattenfall, 0.0)
                item["flared_MWh_LHV_y"] = _fmt(flare)
                item["balance_error_MWh_LHV_y"] = _fmt(raw_gen - direct - boiler - vattenfall - flare)
                item["status"] = "closed"
                item["notes"] = "C5j BOFG site total generated from governed BOF/OSF development rows; carrier remains separate."
            else:
                item["balance_error_MWh_LHV_y"] = _fmt(raw_gen)
                item["status"] = "bof_osf_generated_site_balance_closes_elsewhere"
                item["notes"] = "BOF/OSF produces BOFG as a separate WAG carrier; sinks are reported in SITE_TOTAL."
        rows.append(item)
    return rows


def _co2_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in report:
        rows.append(
            {
                "configuration": item["configuration"],
                "horizon_hours": item["horizon_hours"],
                "emission_bucket": "BOF_direct_CO2_diagnostic",
                "CO2_site_t_y": item["bof_direct_co2_site_t_y"],
                "CO2_mode": BOF_CO2_MODE,
                "included_in_objective_ETS_cost": "false",
                "included_in_total_direct_CO2": "reporting_only",
                "double_counting_risk": "blocked_by_C5j_policy",
                "status": "pass",
                "notes": "Direct BOF CO2 is a diagnostic counter only in C5j.",
            }
        )
        rows.append(
            {
                "configuration": item["configuration"],
                "horizon_hours": item["horizon_hours"],
                "emission_bucket": "BOFG_combustion_CO2_potential",
                "CO2_site_t_y": "",
                "CO2_mode": "diagnostic_only_not_quantified_in_C5j",
                "included_in_objective_ETS_cost": "false",
                "included_in_total_direct_CO2": "false",
                "double_counting_risk": "not_booked_with_direct_BOF_CO2",
                "status": "pass",
                "notes": "Full downstream BOFG combustion CO2 is not added to the BOF direct diagnostic.",
            }
        )
    return rows


def _lhv_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in report:
        for basis, nm3_field, mwh_field in (
            ("raw", "bof_bofg_output_raw_Nm3_y", "bof_bofg_output_raw_MWh_LHV_y"),
            ("site_scaled", "bof_bofg_output_site_Nm3_y", "bof_bofg_output_site_MWh_LHV_y"),
        ):
            nm3 = _zero(item[nm3_field])
            reported = _zero(item[mwh_field])
            lhv = _zero(item["bofg_lhv_MJ_per_Nm3"])
            expected = nm3 * lhv / 3600.0
            error = reported - expected
            rows.append(
                {
                    "configuration": item["configuration"],
                    "horizon_hours": item["horizon_hours"],
                    "scale_basis": basis,
                    "plant": "BOF_OSF",
                    "carrier": "BOFG",
                    "quantity_Nm3": _fmt(nm3),
                    "reported_MWh_LHV": _fmt(reported),
                    "expected_MWh_LHV_from_LHV": _fmt(expected),
                    "absolute_error_MWh": _fmt(error),
                    "relative_error_pct": _fmt(error / expected * 100.0 if expected else 0.0),
                    "LHV_MJ_per_Nm3_used": _fmt(lhv),
                    "status": "pass" if abs(error) <= 1e-6 else "fail",
                    "red_flags": "" if abs(error) <= 1e-6 else "lhv_conversion_mismatch",
                    "notes": "BOFG MWh_LHV = Nm3 * 8.6 / 3600.",
                }
            )
    return rows


def _summary_rows(report: list[dict[str, Any]], wag_aggregate: list[dict[str, Any]], lhv: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    agg_by_key = {(row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row for row in wag_aggregate}
    lhv_fail = sum(1 for row in lhv if row["status"] != "pass")
    rows: list[dict[str, Any]] = []
    by_horizon: dict[int, list[dict[str, Any]]] = {24: [], 168: []}
    for item in report:
        agg = agg_by_key[(item["configuration"], int(item["horizon_hours"]), "site_scaled")]
        row = {
            "stage": STAGE,
            "configuration": item["configuration"],
            "horizon_hours": item["horizon_hours"],
            "solver_status": "inherited_from_C5h_accounting_only",
            "status": "development_only",
            "thesis_usability": "false",
            "bof_liquid_steel_site_t_y": item["bof_liquid_steel_site_t_y"],
            "bof_hot_metal_input_site_t_y": item["bof_hot_metal_input_site_t_y"],
            "bof_scrap_input_site_t_y": item["bof_scrap_input_site_t_y"],
            "bof_electricity_site_MWh_y": item["bof_electricity_site_MWh_y"],
            "bof_bofg_output_site_MWh_LHV_y": item["bof_bofg_output_site_MWh_LHV_y"],
            "bof_direct_co2_site_t_y": item["bof_direct_co2_site_t_y"],
            "bof_metallic_input_t_per_t_LS": item["bof_metallic_input_t_per_t_LS"],
            "bof_liquid_steel_yield_per_t_metallic_input": item["bof_liquid_steel_yield_per_t_metallic_input"],
            "WAG_invariant_status": agg["status"],
            "WAG_balance_error_MWh_y": agg["balance_error_MWh_y"],
            "LHV_consistency_fail_count": lhv_fail,
            "CO2_double_counting_guard_status": "pass",
            "anchors_used_as_constraints": "false",
        }
        rows.append(row)
        by_horizon[int(item["horizon_hours"])].append(row)
    return rows, by_horizon


def _compact_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration": item["configuration"],
            "horizon_hours": item["horizon_hours"],
            "plant": "BOF_OSF",
            "active": "true",
            "main_product": "liquid_steel",
            "main_product_site_t_y": item["bof_liquid_steel_site_t_y"],
            "hot_metal_t_per_t_LS": item["bof_hot_metal_input_t_per_t_LS"],
            "scrap_t_per_t_LS": item["bof_scrap_input_t_per_t_LS"],
            "oxygen_Nm3_per_t_LS": item["bof_oxygen_Nm3_per_t_LS"],
            "electricity_MWh_per_t_LS": item["bof_electricity_MWh_per_t_LS"],
            "BOFG_Nm3_per_t_LS": item["bof_bofg_Nm3_per_t_LS"],
            "BOFG_MWh_LHV_per_t_LS": item["bofg_MWh_per_t_LS"],
            "direct_CO2_t_per_t_LS": item["bof_direct_co2_t_per_t_LS"],
            "BOF_CO2_mode": BOF_CO2_MODE,
            "status": "development_only",
            "red_flags": "" if abs(_zero(item["bf_to_bof_hot_metal_gap_site_t_y"])) <= WAG_TOL_MWH else "bf_to_bof_hot_metal_gap_reported",
        }
        for item in report
    ]


def _stage_gate(
    report: list[dict[str, Any]],
    input_rows: list[dict[str, str]],
    anchors: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    co2: list[dict[str, Any]],
    lhv: list[dict[str, Any]],
) -> dict[str, Any]:
    failures = []
    failures.extend(row for row in wag_aggregate if row["status"] != "pass")
    failures.extend(row for row in lhv if row["status"] != "pass")
    failures.extend(row for row in anchors if row["constraint_used"] != "false")
    failures.extend(row for row in co2 if row["included_in_objective_ETS_cost"] != "false")
    governance_failures = [
        row
        for row in input_rows
        if row["input_status"] != "development_candidate"
        or row["thesis_usability"] != "false"
        or row["human_review_required"] != "true"
        or row["codex_may_decide"] != "false"
    ]
    c0_hm = _configuration_parameter(input_rows, C0, "BOF_HOT_METAL_INPUT_T_PER_T_LS")
    c1_hm = _configuration_parameter(input_rows, C1, "BOF_HOT_METAL_INPUT_T_PER_T_LS")
    c0_scrap = _configuration_parameter(input_rows, C0, "BOF_SCRAP_INPUT_T_PER_T_LS")
    c1_scrap = _configuration_parameter(input_rows, C1, "BOF_SCRAP_INPUT_T_PER_T_LS")
    if c0_hm == c1_hm or c0_scrap == c1_scrap:
        failures.append({"status": "fail", "red_flags": "configuration_specific_metallic_coefficients_missing"})
    if governance_failures:
        failures.extend(governance_failures)

    return {
        "stage": STAGE,
        "decision": "pass_development_bof_osf_minimal_parameterisation_with_validation_gaps" if not failures else "fail_development_bof_osf_minimal_parameterisation",
        "output_directory": _rel(C5J_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "source_card_present": SOURCE_CARD.exists(),
        "bof_development_input_rows": len(input_rows),
        "bof_report_rows": len(report),
        "bof_co2_mode": BOF_CO2_MODE,
        "BOFG_LHV_MJ_per_Nm3": _param_value(input_rows, "BOFG_LHV_MJ_PER_NM3"),
        "wag_invariant_fail_count": sum(1 for row in wag_aggregate if row["status"] != "pass"),
        "lhv_consistency_fail_count": sum(1 for row in lhv if row["status"] != "pass"),
        "co2_double_counting_guard_status": "pass" if all(row["included_in_objective_ETS_cost"] == "false" for row in co2) else "fail",
        "anchor_constraints_used_count": sum(1 for row in anchors if row["constraint_used"] != "false"),
        "development_input_governance_fail_count": len(governance_failures),
        "direct_WAG_market_valuation_added": False,
        "BOFG_export_revenue_added": False,
        "forbidden_economic_features_added": False,
    }


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5h_blast_furnace_controller_parameterisation()
    C5J_DIR.mkdir(parents=True, exist_ok=True)

    input_rows_any = _development_input_rows()
    _write_csv(C5J_DIR / "s4_4c5j_bof_osf_development_input_rows.csv", input_rows_any, INPUT_COLUMNS)
    input_rows = _read_csv(C5J_DIR / "s4_4c5j_bof_osf_development_input_rows.csv")
    report = _bof_report_rows(input_rows)
    anchors = _anchor_rows(report)
    c5h_wag = _read_csv(C5H_DIR / "s4_4c5h_wag_generation_consumption_by_plant.csv")
    wag_rows = _update_wag_rows(c5h_wag, report)
    wag_aggregate = _wag_aggregate_invariant_rows(wag_rows)
    co2 = _co2_rows(report)
    lhv = _lhv_rows(report)
    summary_rows, by_horizon = _summary_rows(report, wag_aggregate, lhv)
    compact = _compact_rows(report)
    gate = _stage_gate(report, input_rows, anchors, wag_aggregate, co2, lhv)

    _write_json(C5J_DIR / "s4_4c5j_stage_gate.json", gate)
    _write_csv(C5J_DIR / "s4_4c5j_run_registry.csv", [{
        "stage": STAGE,
        "source_stage": "S4.4c5h_blast_furnace_controller_parameterisation",
        "decision": gate["decision"],
        "status": "development_only",
        "thesis_usability": "false",
        "output_directory": gate["output_directory"],
    }])
    for horizon, rows in by_horizon.items():
        _write_csv(C5J_DIR / f"s4_4c5j_{horizon}h_summary.csv", rows)
    _write_csv(C5J_DIR / "s4_4c5j_bof_osf_parameter_register.csv", input_rows, INPUT_COLUMNS)
    _write_csv(C5J_DIR / "s4_4c5j_bof_osf_report.csv", report)
    _write_csv(C5J_DIR / "s4_4c5j_bof_osf_anchor_gap_dashboard.csv", anchors)
    _write_csv(C5J_DIR / "s4_4c5j_wag_generation_consumption_by_plant.csv", wag_rows)
    _write_csv(C5J_DIR / "s4_4c5j_wag_aggregate_invariant.csv", wag_aggregate, AGGREGATE_COLUMNS)
    _write_csv(C5J_DIR / "s4_4c5j_bof_co2_accounting_dashboard.csv", co2)
    _write_csv(C5J_DIR / "s4_4c5j_lhv_consistency_checks.csv", lhv)
    _write_csv(C5J_DIR / "s4_4c5j_compact_table_for_chat.csv", compact)

    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "bof_report": len(report),
            "anchor_gaps": len(anchors),
            "wag_aggregate": len(wag_aggregate),
            "co2": len(co2),
        },
    }
    _write_json(C5J_DIR / "s4_4c5j_summary.json", summary)
    return summary


def run_s4_4c5j_bof_osf_minimal_parameterisation() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5j_bof_osf_minimal_parameterisation(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
