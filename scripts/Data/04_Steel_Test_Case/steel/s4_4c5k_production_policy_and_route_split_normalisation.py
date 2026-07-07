"""S4.4c5k production-policy and route-split normalisation.

This stage is a development-only accounting layer over C5j. It freezes the
active site comparison target at 6.75 Mt/y for C0 and C1, normalises the C1
retained BOF/EAF split, and enforces annual BF hot metal = BOF hot-metal input
while no explicit BF-to-BOF hot-metal buffer exists.
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
from .s4_4c5h_blast_furnace_controller_parameterisation import (
    BF_BFG_OUTPUT_MWH_PER_T_HM,
    BF_HOT_STOVE_DEMAND_MWH_PER_T_HM,
    BFG_LHV_MJ_PER_NM3,
)
from .s4_4c5j_bof_osf_minimal_parameterisation import (
    BOF_CO2_MODE,
    C5J_DIR,
    INPUT_COLUMNS as C5J_INPUT_COLUMNS,
    run_s4_4c5j_bof_osf_minimal_parameterisation,
)


STAGE = "S4.4c5k_production_policy_and_route_split_normalisation"
C5K_DIR = S4_ROOT / "s4_4c5k_production_policy_and_route_split_normalisation"

ACTIVE_TARGETS_T_Y = {
    C0: {"total": 6_750_000.0, "bof": 6_750_000.0, "eaf": 0.0},
    C1: {"total": 6_750_000.0, "bof": 3_400_000.0, "eaf": 3_350_000.0},
}

CONTEXT_ANCHORS_T_Y = {
    (C0, "MER_reference_liquid_steel_context_t_y"): (7_200_000.0, "public MER current/reference context anchor"),
    (C0, "MER_heracless_liquid_steel_context_t_y"): (6_800_000.0, "public Heracless production context anchor"),
    (C1, "MER_reference_liquid_steel_context_t_y"): (7_200_000.0, "public MER current/reference context anchor"),
    (C1, "MER_heracless_liquid_steel_context_t_y"): (6_800_000.0, "public Heracless production context anchor"),
    (C1, "C1_retained_BOF_OSF_activity_context_t_y"): (3_400_000.0, "public retained BOF/OSF activity context anchor"),
    (C1, "C1_retained_BF_hot_metal_context_t_y"): (2_800_000.0, "public retained BF hot-metal context anchor"),
}

POLICY_INPUT_COLUMNS = [
    "parameter_id",
    "configuration_scope",
    "applies_to_configuration",
    "plant_id",
    "parameter_name",
    "parameter_role",
    "direction",
    "carrier_or_material",
    "base_value",
    "unit",
    "basis",
    "source_or_assumption_id",
    "input_status",
    "evidence_strength",
    "executable_status",
    "development_executable",
    "thesis_usability",
    "human_review_required",
    "codex_may_decide",
    "applies_to_solver",
    "applies_to_diagnostics",
    "applies_to_anchor_comparison",
    "active_target",
    "constraint_used",
    "caveat",
]


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _bof_coefficients() -> list[dict[str, str]]:
    rows = _read_csv(C5J_DIR / "s4_4c5j_bof_osf_development_input_rows.csv")
    missing = [
        row
        for row in rows
        if row.get("input_status") != "development_candidate"
        or row.get("thesis_usability") != "false"
        or row.get("human_review_required") != "true"
        or row.get("codex_may_decide") != "false"
    ]
    if missing:
        raise ValueError("C5j BOF coefficient rows failed development-governance checks.")
    return rows


def _param(rows: list[dict[str, str]], parameter_id: str) -> float:
    row = next(row for row in rows if row["parameter_id"] == parameter_id)
    return _zero(row["base_value"])


def _config_param(rows: list[dict[str, str]], config: str, base_id: str) -> float:
    suffix = "C0" if config == C0 else "C1"
    return _param(rows, f"{base_id}_{suffix}")


def _policy_row(
    parameter_id: str,
    config: str,
    value: float,
    unit: str,
    *,
    role: str,
    basis: str,
    active_target: bool = True,
    plant_id: str = "SITE_POLICY",
) -> dict[str, Any]:
    return {
        "parameter_id": parameter_id,
        "configuration_scope": "configuration_specific" if config in {C0, C1} else "generic_policy",
        "applies_to_configuration": config,
        "plant_id": plant_id,
        "parameter_name": parameter_id.lower(),
        "parameter_role": role,
        "direction": "policy",
        "carrier_or_material": "liquid_steel" if "LIQUID_STEEL" in parameter_id else "hot_metal_policy",
        "base_value": _fmt(value),
        "unit": unit,
        "basis": basis,
        "source_or_assumption_id": "S4.4c5k_active_model_production_policy",
        "input_status": "development_policy_target" if active_target else "validation_context_anchor",
        "evidence_strength": "modelling_policy_with_public_context",
        "executable_status": "development_executable" if active_target else "validation_only",
        "development_executable": "true" if active_target else "false",
        "thesis_usability": "false",
        "human_review_required": "true",
        "codex_may_decide": "false",
        "applies_to_solver": "false",
        "applies_to_diagnostics": "true",
        "applies_to_anchor_comparison": "false" if active_target else "true",
        "active_target": "true" if active_target else "false",
        "constraint_used": "false",
        "caveat": "active thesis model target; not exact Tata truth; public MER values remain validation/context anchors",
    }


def _production_policy_rows() -> list[dict[str, Any]]:
    rows = [
        _policy_row("C0_TOTAL_LIQUID_STEEL_TARGET_MT_Y", C0, 6.75, "Mt liquid steel/y", role="active_total_production_target", basis="site_annual_liquid_steel"),
        _policy_row("C0_BOF_LIQUID_STEEL_TARGET_MT_Y", C0, 6.75, "Mt liquid steel/y", role="active_route_split_target", basis="site_annual_retained_BOF_liquid_steel"),
        _policy_row("C0_EAF_LIQUID_STEEL_TARGET_MT_Y", C0, 0.0, "Mt liquid steel/y", role="active_route_split_target", basis="site_annual_EAF_liquid_steel"),
        _policy_row("C1_TOTAL_LIQUID_STEEL_TARGET_MT_Y", C1, 6.75, "Mt liquid steel/y", role="active_total_production_target", basis="site_annual_liquid_steel"),
        _policy_row("C1_RETAINED_BOF_LIQUID_STEEL_TARGET_MT_Y", C1, 3.40, "Mt liquid steel/y", role="active_route_split_target", basis="site_annual_retained_BOF_liquid_steel"),
        _policy_row("C1_EAF_LIQUID_STEEL_TARGET_MT_Y", C1, 3.35, "Mt liquid steel/y", role="active_route_split_target", basis="site_annual_EAF_liquid_steel"),
        _policy_row("BF_TO_BOF_HOT_METAL_BUFFER_ACTIVE", "all", 0.0, "boolean", role="hot_metal_coupling_policy", basis="no_explicit_hot_metal_buffer", plant_id="BF_BOF_INTERFACE"),
        _policy_row("BF_HM_EQUALS_BOF_HM_INPUT_NO_BUFFER", "all", 1.0, "boolean", role="hot_metal_coupling_policy", basis="annual_equality_no_buffer", plant_id="BF_BOF_INTERFACE"),
    ]
    for (config, metric), (value, source) in CONTEXT_ANCHORS_T_Y.items():
        rows.append(
            {
                **_policy_row(metric, config, value / 1_000_000.0, "Mt/y", role="validation_context_anchor", basis=source, active_target=False),
                "base_value": _fmt(value),
                "unit": "t/y",
                "carrier_or_material": "liquid_steel_or_hot_metal_context",
                "source_or_assumption_id": source,
                "caveat": "validation/context anchor only; not an active target and not a dispatch constraint",
            }
        )
    return rows


def _scale_factors_from_c5j() -> dict[tuple[str, int], float]:
    factors: dict[tuple[str, int], float] = {}
    for row in _read_csv(C5J_DIR / "s4_4c5j_bof_osf_report.csv"):
        factors[(row["configuration"], int(row["horizon_hours"]))] = _zero(row["scale_factor"]) or 1.0
    return factors


def _pre_normalisation_bf_hot_metal() -> dict[tuple[str, int], float]:
    return {
        (row["configuration"], int(row["horizon_hours"])): _zero(row["bf_hot_metal_available_site_t_y"])
        for row in _read_csv(C5J_DIR / "s4_4c5j_bof_osf_report.csv")
    }


def _normalised_report_rows(input_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    scale_factors = _scale_factors_from_c5j()
    pre_bf = _pre_normalisation_bf_hot_metal()
    oxygen_nm3 = _param(input_rows, "BOF_OXYGEN_INPUT_NM3_PER_T_LS")
    oxygen_kg = _param(input_rows, "BOF_OXYGEN_INPUT_KG_PER_T_LS")
    electricity = _param(input_rows, "BOF_ELECTRICITY_MWH_PER_T_LS")
    bofg_nm3 = _param(input_rows, "BOF_BOFG_OUTPUT_NM3_PER_T_LS")
    bofg_lhv = _param(input_rows, "BOFG_LHV_MJ_PER_NM3")
    direct_co2 = _param(input_rows, "BOF_DIRECT_CO2_T_PER_T_LS")
    bofg_mwh_per_t_ls = bofg_nm3 * bofg_lhv / 3600.0

    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        hot_metal = _config_param(input_rows, config, "BOF_HOT_METAL_INPUT_T_PER_T_LS")
        scrap = _config_param(input_rows, config, "BOF_SCRAP_INPUT_T_PER_T_LS")
        metallic = hot_metal + scrap
        for horizon in HORIZONS:
            scale_factor = scale_factors[(config, horizon)]
            bof_site = ACTIVE_TARGETS_T_Y[config]["bof"]
            eaf_site = ACTIVE_TARGETS_T_Y[config]["eaf"]
            total_site = ACTIVE_TARGETS_T_Y[config]["total"]
            bof_raw = bof_site / scale_factor
            eaf_raw = eaf_site / scale_factor
            total_raw = total_site / scale_factor
            hot_metal_site = bof_site * hot_metal
            scrap_site = bof_site * scrap
            oxygen_site_nm3 = bof_site * oxygen_nm3
            oxygen_site_kg = bof_site * oxygen_kg
            electricity_site = bof_site * electricity
            bofg_site_nm3 = bof_site * bofg_nm3
            bofg_site_mwh = bof_site * bofg_mwh_per_t_ls
            co2_site = bof_site * direct_co2
            hot_metal_raw = hot_metal_site / scale_factor
            scrap_raw = scrap_site / scale_factor
            oxygen_raw_nm3 = oxygen_site_nm3 / scale_factor
            oxygen_raw_kg = oxygen_site_kg / scale_factor
            electricity_raw = electricity_site / scale_factor
            bofg_raw_nm3 = bofg_site_nm3 / scale_factor
            bofg_raw_mwh = bofg_site_mwh / scale_factor
            co2_raw = co2_site / scale_factor
            rows.append(
                {
                    "stage_id": STAGE,
                    "configuration": config,
                    "horizon_hours": horizon,
                    "status": "development_only",
                    "thesis_usability": "false",
                    "active_total_liquid_steel_target_site_t_y": _fmt(total_site),
                    "active_bof_liquid_steel_target_site_t_y": _fmt(bof_site),
                    "active_eaf_liquid_steel_target_site_t_y": _fmt(eaf_site),
                    "active_total_liquid_steel_raw_t_y": _fmt(total_raw),
                    "bof_liquid_steel_raw_t_y": _fmt(bof_raw),
                    "bof_liquid_steel_site_t_y": _fmt(bof_site),
                    "eaf_liquid_steel_raw_t_y": _fmt(eaf_raw),
                    "eaf_liquid_steel_site_t_y": _fmt(eaf_site),
                    "route_split_sum_site_t_y": _fmt(bof_site + eaf_site),
                    "route_split_sum_matches_target": "true" if abs((bof_site + eaf_site) - total_site) <= 1e-6 else "false",
                    "bof_hot_metal_input_raw_t_y": _fmt(hot_metal_raw),
                    "bof_hot_metal_input_site_t_y": _fmt(hot_metal_site),
                    "bf_hot_metal_pre_normalisation_site_t_y": _fmt(pre_bf[(config, horizon)]),
                    "bf_hot_metal_normalised_site_t_y": _fmt(hot_metal_site),
                    "bf_hot_metal_surplus_pre_normalisation_site_t_y": _fmt(pre_bf[(config, horizon)] - hot_metal_site),
                    "remaining_bf_hot_metal_surplus_site_t_y": _fmt(0.0),
                    "bf_to_bof_hot_metal_buffer_active": "false",
                    "bf_hm_equals_bof_hm_input_no_buffer": "true",
                    "bf_bof_coupling_mode": "annual_equality_no_buffer_diagnostic",
                    "hourly_bf_bof_buffer_status": "deferred_until_explicit_hot_metal_buffer_stage",
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
                    "bof_direct_co2_raw_t_y": _fmt(co2_raw),
                    "bof_direct_co2_site_t_y": _fmt(co2_site),
                    "bof_hot_metal_input_t_per_t_LS": _fmt(hot_metal),
                    "bof_scrap_input_t_per_t_LS": _fmt(scrap),
                    "bof_oxygen_Nm3_per_t_LS": _fmt(oxygen_nm3),
                    "bof_electricity_MWh_per_t_LS": _fmt(electricity),
                    "bof_bofg_Nm3_per_t_LS": _fmt(bofg_nm3),
                    "bof_direct_co2_t_per_t_LS": _fmt(direct_co2),
                    "bof_metallic_input_t_per_t_LS": _fmt(metallic),
                    "bof_liquid_steel_yield_per_t_metallic_input": _fmt(1.0 / metallic),
                    "bof_hot_metal_share": _fmt(hot_metal / metallic),
                    "bof_scrap_share": _fmt(scrap / metallic),
                    "bofg_lhv_MJ_per_Nm3": _fmt(bofg_lhv),
                    "bofg_MWh_per_t_LS": _fmt(bofg_mwh_per_t_ls),
                    "scale_factor": _fmt(scale_factor),
                    "scale_mode": "module_scaled_to_site_target",
                    "anchor_constraints_used": "0",
                    "caveats": "development production-policy normalisation; HSM/WBW not implemented; hourly hot-metal buffer deferred",
                }
            )
    return rows


def _anchor_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    field_map = {
        "MER_reference_liquid_steel_context_t_y": "active_total_liquid_steel_target_site_t_y",
        "MER_heracless_liquid_steel_context_t_y": "active_total_liquid_steel_target_site_t_y",
        "C1_retained_BOF_OSF_activity_context_t_y": "bof_liquid_steel_site_t_y",
        "C1_retained_BF_hot_metal_context_t_y": "bof_hot_metal_input_site_t_y",
    }
    rows: list[dict[str, Any]] = []
    for item in report:
        config = item["configuration"]
        for (anchor_config, metric), (anchor, source) in CONTEXT_ANCHORS_T_Y.items():
            if anchor_config != config:
                continue
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
                    "anchor_status": "validation_context_only",
                    "constraint_used": "false",
                    "gap_type": "public_context_gap_not_calibration",
                    "notes": "C5k keeps MER public values as context anchors while active target remains 6.75 Mt/y.",
                }
            )
    return rows


def _bf_split_shares(c5j_wag: list[dict[str, str]], config: str, horizon: int) -> dict[str, float]:
    bf_rows = [
        row
        for row in c5j_wag
        if row["configuration"] == config
        and int(row["horizon_hours"]) == horizon
        and row["carrier"] == "BFG"
        and row["plant_id"] in {"BF6", "BF7"}
    ]
    generated = {row["plant_id"]: _zero(row["site_scaled_quantity"]) for row in bf_rows}
    total = sum(generated.values())
    if config == C1:
        return {"BF6": 1.0, "BF7": 0.0}
    if total <= 0.0:
        return {"BF6": 0.5, "BF7": 0.5}
    return {"BF6": generated.get("BF6", 0.0) / total, "BF7": generated.get("BF7", 0.0) / total}


def _scaled_consumption(row: dict[str, Any], field: str) -> float:
    return _zero(row[field]) * (_zero(row.get("scale_factor")) or 1.0)


def _set_site_total_closed(item: dict[str, Any], generated_raw: float, generated_site: float, lhv: float, metric_scope: str) -> None:
    scale = generated_site / generated_raw if generated_raw else 1.0
    item["generated_MWh_LHV_y"] = _fmt(generated_raw)
    item["generated_Nm3_y"] = _fmt(generated_raw * 3600.0 / lhv if lhv else 0.0)
    item["site_scaled_quantity"] = _fmt(generated_site)
    item["scale_factor"] = _fmt(scale)
    item["LHV_MJ_per_Nm3_used"] = _fmt(lhv)
    item["raw_model_quantity"] = _fmt(generated_raw)
    item["raw_model_unit"] = "MWh_LHV/y"
    item["site_scaled_unit"] = "MWh_LHV/y"
    item["metric_scope"] = metric_scope
    direct = _zero(item["consumed_direct_MWh_LHV_y"])
    boiler = _zero(item["consumed_boiler_MWh_LHV_y"])
    max_vattenfall = max(generated_raw - direct - boiler, 0.0)
    item["consumed_vattenfall_MWh_LHV_y"] = _fmt(min(_zero(item["consumed_vattenfall_MWh_LHV_y"]), max_vattenfall))
    flare = max(generated_raw - direct - boiler - _zero(item["consumed_vattenfall_MWh_LHV_y"]), 0.0)
    item["flared_MWh_LHV_y"] = _fmt(flare)
    item["balance_error_MWh_LHV_y"] = _fmt(generated_raw - direct - boiler - _zero(item["consumed_vattenfall_MWh_LHV_y"]) - flare)
    item["status"] = "closed"


def _update_wag_rows(c5j_wag: list[dict[str, str]], report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    report_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in report}
    bf_shares = {
        (config, horizon): _bf_split_shares(c5j_wag, config, horizon)
        for config in CONFIGS
        for horizon in HORIZONS
    }
    bfg_surplus_per_t_hm = BF_BFG_OUTPUT_MWH_PER_T_HM - BF_HOT_STOVE_DEMAND_MWH_PER_T_HM
    rows: list[dict[str, Any]] = []
    for row in c5j_wag:
        item = dict(row)
        key = (row["configuration"], int(row["horizon_hours"]))
        report_row = report_by_key[key]
        scale = _zero(report_row["scale_factor"]) or 1.0
        if row["carrier"] == "BFG" and row["plant_id"] in {"BF6", "BF7"}:
            share = bf_shares[key][row["plant_id"]]
            hm_site = _zero(report_row["bf_hot_metal_normalised_site_t_y"]) * share
            generated_site = hm_site * bfg_surplus_per_t_hm
            generated_raw = generated_site / scale
            item["generated_MWh_LHV_y"] = _fmt(generated_raw)
            item["generated_Nm3_y"] = _fmt(generated_raw * 3600.0 / BFG_LHV_MJ_PER_NM3)
            item["site_scaled_quantity"] = _fmt(generated_site)
            item["scale_factor"] = _fmt(scale if generated_raw else 0.0)
            item["raw_model_quantity"] = _fmt(generated_raw)
            item["LHV_MJ_per_Nm3_used"] = _fmt(BFG_LHV_MJ_PER_NM3)
            item["balance_error_MWh_LHV_y"] = _fmt(generated_raw)
            item["status"] = "bf_surplus_to_wag_network_after_C5k_BF_BOF_no_buffer_normalisation" if generated_raw else "structurally_inactive"
            item["notes"] = "BFG surplus recomputed from BF hot metal normalised to BOF hot-metal input in no-buffer mode."
        elif row["carrier"] == "BFG" and row["plant_id"] == "SITE_TOTAL":
            generated_site = _zero(report_row["bf_hot_metal_normalised_site_t_y"]) * bfg_surplus_per_t_hm
            generated_raw = generated_site / scale
            _set_site_total_closed(
                item,
                generated_raw,
                generated_site,
                BFG_LHV_MJ_PER_NM3,
                "BFG_surplus_after_hot_stove_and_BF_BOF_no_buffer_normalisation",
            )
            item["notes"] = "BFG site total closes after reducing BF output to BOF hot-metal input in no-buffer mode; Vattenfall allocation is residual diagnostic, not economic dispatch."
        elif row["carrier"] == "BOFG" and row["plant_id"] == "BOF":
            generated_raw = _zero(report_row["bof_bofg_output_raw_MWh_LHV_y"])
            generated_site = _zero(report_row["bof_bofg_output_site_MWh_LHV_y"])
            item["generated_MWh_LHV_y"] = _fmt(generated_raw)
            item["generated_Nm3_y"] = report_row["bof_bofg_output_raw_Nm3_y"]
            item["site_scaled_quantity"] = _fmt(generated_site)
            item["scale_factor"] = _fmt(scale)
            item["raw_model_quantity"] = _fmt(generated_raw)
            item["LHV_MJ_per_Nm3_used"] = report_row["bofg_lhv_MJ_per_Nm3"]
            item["balance_error_MWh_LHV_y"] = _fmt(generated_raw)
            item["status"] = "bof_osf_generated_site_balance_closes_elsewhere"
            item["notes"] = "BOFG generated from normalised BOF liquid-steel target."
        elif row["carrier"] == "BOFG" and row["plant_id"] == "SITE_TOTAL":
            generated_raw = _zero(report_row["bof_bofg_output_raw_MWh_LHV_y"])
            generated_site = _zero(report_row["bof_bofg_output_site_MWh_LHV_y"])
            _set_site_total_closed(
                item,
                generated_raw,
                generated_site,
                _zero(report_row["bofg_lhv_MJ_per_Nm3"]),
                "BOFG_separate_WAG_carrier_after_C5k_route_split_normalisation",
            )
            item["notes"] = "BOFG site total generated from normalised BOF retained route and kept as separate WAG carrier."
        rows.append(item)
    return rows


def _coupling_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "configuration": row["configuration"],
            "horizon_hours": row["horizon_hours"],
            "bf_to_bof_hot_metal_buffer_active": row["bf_to_bof_hot_metal_buffer_active"],
            "bf_hm_equals_bof_hm_input_no_buffer": row["bf_hm_equals_bof_hm_input_no_buffer"],
            "coupling_mode": row["bf_bof_coupling_mode"],
            "pre_normalisation_bf_hot_metal_site_t_y": row["bf_hot_metal_pre_normalisation_site_t_y"],
            "bof_hot_metal_input_site_t_y": row["bof_hot_metal_input_site_t_y"],
            "normalised_bf_hot_metal_output_site_t_y": row["bf_hot_metal_normalised_site_t_y"],
            "pre_normalisation_surplus_site_t_y": row["bf_hot_metal_surplus_pre_normalisation_site_t_y"],
            "remaining_surplus_site_t_y": row["remaining_bf_hot_metal_surplus_site_t_y"],
            "hourly_buffer_status": row["hourly_bf_bof_buffer_status"],
            "status": "pass" if abs(_zero(row["remaining_bf_hot_metal_surplus_site_t_y"])) <= 1e-6 else "fail",
            "red_flags": "" if abs(_zero(row["remaining_bf_hot_metal_surplus_site_t_y"])) <= 1e-6 else "remaining_hot_metal_surplus_in_no_buffer_mode",
            "notes": "Annual equality is the strongest coupling available in the current diagnostic C5 architecture.",
        }
        for row in report
    ]


def _co2_rows(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in report:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "emission_bucket": "BOF_direct_CO2_diagnostic",
                "CO2_site_t_y": row["bof_direct_co2_site_t_y"],
                "CO2_mode": BOF_CO2_MODE,
                "included_in_objective_ETS_cost": "false",
                "included_in_total_direct_CO2": "reporting_only",
                "double_counting_risk": "blocked_by_C5k_policy",
                "status": "pass",
                "notes": "BOF direct CO2 remains a diagnostic counter; no ETS objective steering is added.",
            }
        )
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "emission_bucket": "BOFG_combustion_CO2_potential",
                "CO2_site_t_y": "",
                "CO2_mode": "diagnostic_only_not_quantified_in_C5k",
                "included_in_objective_ETS_cost": "false",
                "included_in_total_direct_CO2": "false",
                "double_counting_risk": "not_booked_with_direct_BOF_CO2",
                "status": "pass",
                "notes": "Full downstream BOFG combustion CO2 is not added with direct BOF CO2.",
            }
        )
    return rows


def _lhv_rows(report: list[dict[str, Any]], wag_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    for row in wag_rows:
        if row["plant_id"] != "SITE_TOTAL" or row["carrier"] != "BFG":
            continue
        nm3 = _zero(row["generated_Nm3_y"])
        reported = _zero(row["generated_MWh_LHV_y"])
        expected = nm3 * BFG_LHV_MJ_PER_NM3 / 3600.0
        error = reported - expected
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "scale_basis": "raw",
                "plant": "SITE_TOTAL",
                "carrier": "BFG",
                "quantity_Nm3": _fmt(nm3),
                "reported_MWh_LHV": _fmt(reported),
                "expected_MWh_LHV_from_LHV": _fmt(expected),
                "absolute_error_MWh": _fmt(error),
                "relative_error_pct": _fmt(error / expected * 100.0 if expected else 0.0),
                "LHV_MJ_per_Nm3_used": _fmt(BFG_LHV_MJ_PER_NM3),
                "status": "pass" if abs(error) <= 1e-6 else "fail",
                "red_flags": "" if abs(error) <= 1e-6 else "lhv_conversion_mismatch",
                "notes": "BFG surplus MWh_LHV = Nm3 * 3.85 / 3600 after BF-BOF normalisation.",
            }
        )
    return rows


def _summary_rows(report: list[dict[str, Any]], wag_aggregate: list[dict[str, Any]], lhv_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    agg_by_key = {(row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row for row in wag_aggregate}
    lhv_fail_count = sum(1 for row in lhv_rows if row["status"] != "pass")
    rows: list[dict[str, Any]] = []
    by_horizon: dict[int, list[dict[str, Any]]] = {24: [], 168: []}
    for item in report:
        agg = agg_by_key[(item["configuration"], int(item["horizon_hours"]), "site_scaled")]
        row = {
            "stage": STAGE,
            "configuration": item["configuration"],
            "horizon_hours": item["horizon_hours"],
            "solver_status": "inherited_from_C5j_accounting_only",
            "status": "development_only",
            "thesis_usability": "false",
            "active_total_liquid_steel_target_site_t_y": item["active_total_liquid_steel_target_site_t_y"],
            "bof_liquid_steel_site_t_y": item["bof_liquid_steel_site_t_y"],
            "eaf_liquid_steel_site_t_y": item["eaf_liquid_steel_site_t_y"],
            "bof_hot_metal_input_site_t_y": item["bof_hot_metal_input_site_t_y"],
            "bf_hot_metal_normalised_site_t_y": item["bf_hot_metal_normalised_site_t_y"],
            "remaining_bf_hot_metal_surplus_site_t_y": item["remaining_bf_hot_metal_surplus_site_t_y"],
            "bof_scrap_input_site_t_y": item["bof_scrap_input_site_t_y"],
            "bof_oxygen_input_site_Nm3_y": item["bof_oxygen_input_site_Nm3_y"],
            "bof_electricity_site_MWh_y": item["bof_electricity_site_MWh_y"],
            "bof_bofg_output_site_MWh_LHV_y": item["bof_bofg_output_site_MWh_LHV_y"],
            "bof_bofg_output_site_PJ_LHV_y": item["bof_bofg_output_site_PJ_LHV_y"],
            "bof_direct_co2_site_t_y": item["bof_direct_co2_site_t_y"],
            "route_split_sum_matches_target": item["route_split_sum_matches_target"],
            "WAG_invariant_status": agg["status"],
            "WAG_balance_error_MWh_y": agg["balance_error_MWh_y"],
            "LHV_consistency_fail_count": lhv_fail_count,
            "CO2_double_counting_guard_status": "pass",
            "anchor_constraints_used_count": "0",
            "HSM_WBW_implemented": "false",
        }
        rows.append(row)
        by_horizon[int(item["horizon_hours"])].append(row)
    return rows, by_horizon


def _compact_rows(report: list[dict[str, Any]], wag_aggregate: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    agg_by_key = {(row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row for row in wag_aggregate}
    for item in report:
        rows.append(
            {
                "configuration": item["configuration"],
                "horizon_hours": item["horizon_hours"],
                "plant": "BOF_OSF",
                "active": "true",
                "main_product": "liquid_steel",
                "active_total_LS_target_Mt_y": _fmt(_zero(item["active_total_liquid_steel_target_site_t_y"]) / 1_000_000.0),
                "BOF_LS_Mt_y": _fmt(_zero(item["bof_liquid_steel_site_t_y"]) / 1_000_000.0),
                "EAF_LS_Mt_y": _fmt(_zero(item["eaf_liquid_steel_site_t_y"]) / 1_000_000.0),
                "BOF_HM_input_Mt_y": _fmt(_zero(item["bof_hot_metal_input_site_t_y"]) / 1_000_000.0),
                "BF_HM_normalised_Mt_y": _fmt(_zero(item["bf_hot_metal_normalised_site_t_y"]) / 1_000_000.0),
                "BF_HM_surplus_Mt_y": _fmt(_zero(item["remaining_bf_hot_metal_surplus_site_t_y"]) / 1_000_000.0),
                "BOF_scrap_Mt_y": _fmt(_zero(item["bof_scrap_input_site_t_y"]) / 1_000_000.0),
                "BOFG_PJ_y": item["bof_bofg_output_site_PJ_LHV_y"],
                "BOF_CO2_Mt_y": _fmt(_zero(item["bof_direct_co2_site_t_y"]) / 1_000_000.0),
                "anchor_constraints_used": item["anchor_constraints_used"],
                "status": "development_only_no_buffer_normalised",
                "red_flags": "",
            }
        )
        site_agg = agg_by_key[(item["configuration"], int(item["horizon_hours"]), "site_scaled")]
        rows.append(
            {
                "configuration": item["configuration"],
                "horizon_hours": item["horizon_hours"],
                "plant": "WAG_TOTAL_ALL",
                "active": "true",
                "main_product": "WAG_accounting_same_basis",
                "active_total_LS_target_Mt_y": "",
                "BOF_LS_Mt_y": "",
                "EAF_LS_Mt_y": "",
                "BOF_HM_input_Mt_y": "",
                "BF_HM_normalised_Mt_y": "",
                "BF_HM_surplus_Mt_y": "",
                "BOF_scrap_Mt_y": "",
                "BOFG_PJ_y": "",
                "BOF_CO2_Mt_y": "",
                "anchor_constraints_used": "0",
                "status": site_agg["status"],
                "red_flags": site_agg["red_flags"],
            }
        )
    return rows


def _stage_gate(
    policy_rows: list[dict[str, Any]],
    report: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    co2: list[dict[str, Any]],
    lhv: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[Any] = []
    failures.extend(row for row in report if row["route_split_sum_matches_target"] != "true")
    failures.extend(row for row in report if abs(_zero(row["remaining_bf_hot_metal_surplus_site_t_y"])) > 1e-6)
    failures.extend(row for row in anchors if row["constraint_used"] != "false")
    failures.extend(row for row in wag_aggregate if row["status"] != "pass")
    failures.extend(row for row in co2 if row["included_in_objective_ETS_cost"] != "false")
    failures.extend(row for row in lhv if row["status"] != "pass")
    policy_failures = [
        row
        for row in policy_rows
        if row["thesis_usability"] != "false"
        or row["human_review_required"] != "true"
        or row["codex_may_decide"] != "false"
        or row["constraint_used"] != "false"
    ]
    failures.extend(policy_failures)
    c1_24 = next(row for row in report if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    c0_24 = next(row for row in report if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    return {
        "stage": STAGE,
        "decision": "pass_development_production_policy_and_route_split_normalisation" if not failures else "fail_development_production_policy_and_route_split_normalisation",
        "output_directory": _rel(C5K_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "active_C0_total_liquid_steel_target_t_y": ACTIVE_TARGETS_T_Y[C0]["total"],
        "active_C1_total_liquid_steel_target_t_y": ACTIVE_TARGETS_T_Y[C1]["total"],
        "active_C1_retained_BOF_liquid_steel_target_t_y": ACTIVE_TARGETS_T_Y[C1]["bof"],
        "active_C1_EAF_liquid_steel_target_t_y": ACTIVE_TARGETS_T_Y[C1]["eaf"],
        "C0_BOF_hot_metal_input_site_t_y": _zero(c0_24["bof_hot_metal_input_site_t_y"]),
        "C1_BOF_hot_metal_input_site_t_y": _zero(c1_24["bof_hot_metal_input_site_t_y"]),
        "C1_BOF_scrap_input_site_t_y": _zero(c1_24["bof_scrap_input_site_t_y"]),
        "BF_TO_BOF_HOT_METAL_BUFFER_ACTIVE": False,
        "BF_HM_EQUALS_BOF_HM_INPUT_NO_BUFFER": True,
        "remaining_BF_hot_metal_surplus_max_abs_t_y": max(abs(_zero(row["remaining_bf_hot_metal_surplus_site_t_y"])) for row in report),
        "anchor_constraints_used_count": sum(1 for row in anchors if row["constraint_used"] != "false"),
        "wag_invariant_fail_count": sum(1 for row in wag_aggregate if row["status"] != "pass"),
        "lhv_consistency_fail_count": sum(1 for row in lhv if row["status"] != "pass"),
        "co2_double_counting_guard_status": "pass" if all(row["included_in_objective_ETS_cost"] == "false" for row in co2) else "fail",
        "policy_governance_fail_count": len(policy_failures),
        "HSM_WBW_implemented": False,
        "forbidden_economic_features_added": False,
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5j_bof_osf_minimal_parameterisation()
    C5K_DIR.mkdir(parents=True, exist_ok=True)

    input_rows = _bof_coefficients()
    policy_rows = _production_policy_rows()
    report = _normalised_report_rows(input_rows)
    anchors = _anchor_rows(report)
    c5j_wag = _read_csv(C5J_DIR / "s4_4c5j_wag_generation_consumption_by_plant.csv")
    wag_rows = _update_wag_rows(c5j_wag, report)
    wag_aggregate = _wag_aggregate_invariant_rows(wag_rows)
    co2 = _co2_rows(report)
    lhv = _lhv_rows(report, wag_rows)
    coupling = _coupling_rows(report)
    summary_rows, by_horizon = _summary_rows(report, wag_aggregate, lhv)
    compact = _compact_rows(report, wag_aggregate)
    gate = _stage_gate(policy_rows, report, anchors, wag_aggregate, co2, lhv)

    _write_json(C5K_DIR / "s4_4c5k_stage_gate.json", gate)
    _write_csv(
        C5K_DIR / "s4_4c5k_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5j_BOF_OSF_minimal_parameterisation",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5K_DIR / "s4_4c5k_production_policy_input_rows.csv", policy_rows, POLICY_INPUT_COLUMNS)
    _write_csv(C5K_DIR / "s4_4c5k_bof_osf_coefficient_rows_inherited_from_c5j.csv", input_rows, C5J_INPUT_COLUMNS)
    for horizon, rows in by_horizon.items():
        _write_csv(C5K_DIR / f"s4_4c5k_{horizon}h_summary.csv", rows)
    _write_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv", report)
    _write_csv(C5K_DIR / "s4_4c5k_bf_bof_hot_metal_coupling_dashboard.csv", coupling)
    _write_csv(C5K_DIR / "s4_4c5k_validation_anchor_gap_dashboard.csv", anchors)
    _write_csv(C5K_DIR / "s4_4c5k_wag_generation_consumption_by_plant.csv", wag_rows)
    _write_csv(C5K_DIR / "s4_4c5k_wag_aggregate_invariant.csv", wag_aggregate, AGGREGATE_COLUMNS)
    _write_csv(C5K_DIR / "s4_4c5k_bof_co2_accounting_dashboard.csv", co2)
    _write_csv(C5K_DIR / "s4_4c5k_lhv_consistency_checks.csv", lhv)
    _write_csv(C5K_DIR / "s4_4c5k_compact_table_for_chat.csv", compact)

    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "policy": len(policy_rows),
            "route_split_report": len(report),
            "anchor_gaps": len(anchors),
            "wag_aggregate": len(wag_aggregate),
            "co2": len(co2),
        },
    }
    _write_json(C5K_DIR / "s4_4c5k_summary.json", summary)
    return summary


def run_s4_4c5k_production_policy_and_route_split_normalisation() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5k_production_policy_and_route_split_normalisation(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
