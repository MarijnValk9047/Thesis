"""S4.4c5p_i source-card candidate overlay reconciliation.

This stage is diagnostic-only. It applies selected repaired source-card
candidate values to current annual C5 activity outputs as a post-processing
overlay. It does not migrate values to executable development inputs, change
model equations, add residual electricity/NG loads, create CO2 costs, or change
the current C5 physical/accounting baseline.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    S4_ROOT,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5p_a_linde_asu_oxygen_accounting import C5P_A_DIR
from .s4_4c5p_b_boiler_steam_circuit_accounting import C5P_B_DIR
from .s4_4c5p_c_ij01_vn25_generator_interface_accounting import C5P_C_DIR
from .s4_4c5p_d_buffer_store_register_and_validation import C5P_D_DIR
from .s4_4c5p_e_annual_c0_c1_physical_accounting_reconciliation import C5P_E_DIR
from .s4_4c5p_f_pre_economics_alignment_gate import C5P_F_DIR
from .s4_4c5p_g_residual_electricity_ng_boundary_diagnostics import C5P_G_DIR
from .s4_4c5p_h_co2_and_plant_energy_anchor_boundary_diagnostics import C5P_H_DIR


STAGE = "S4.4c5p_i_source_card_candidate_overlay_reconciliation"
C5P_I_DIR = S4_ROOT / "s4_4c5p_i_source_card_candidate_overlay_reconciliation"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_SOURCE_CARD_CANDIDATE_OVERLAY_RECONCILIATION.md")
SOURCE_CARD_DIR = Path("data/03_Optimisation/inputs/assets/steel/source_cards")

TWH_PER_MWH = 1.0 / 1_000_000.0
PJ_PER_GJ = 1.0 / 1_000_000.0
PUBLIC_SCOPE1_ANCHORS_MT = {C0: 12.6, C1: 8.3}
FULL_SITE_ELECTRICITY_CONTEXT_TWH = 3.0
SITE_AVERAGE_POWER_CONTEXT_TWH = 3.1536
DRP_ONLY_NG_CONTEXT_PJ_C1 = 27.72

ACTIVITY_COLUMNS = [
    "configuration",
    "plant_or_asset",
    "activity_metric",
    "activity_value",
    "unit",
    "source_artifact_or_stage",
    "overlay_eligible",
    "caveat",
]

ELECTRICITY_COLUMNS = [
    "configuration",
    "plant_or_asset",
    "activity_metric",
    "activity_value",
    "candidate_parameter_id",
    "candidate_value",
    "candidate_unit",
    "source_status",
    "recommended_model_use",
    "overlay_electricity_twh_y",
    "current_model_electricity_twh_y",
    "delta_vs_current_twh_y",
    "source_card",
    "caveat",
]

NG_FUEL_COLUMNS = [
    "configuration",
    "plant_or_asset",
    "fuel_or_energy_carrier",
    "activity_metric",
    "activity_value",
    "candidate_parameter_id",
    "candidate_value",
    "candidate_unit",
    "source_status",
    "recommended_model_use",
    "overlay_fuel_pj_y",
    "current_model_fuel_pj_y",
    "delta_vs_current_pj_y",
    "source_card",
    "caveat",
]

ELECTRICITY_GAP_COLUMNS = [
    "configuration",
    "scenario",
    "current_modelled_process_demand_twh",
    "candidate_overlay_gross_demand_twh",
    "internal_offsets_twh",
    "pre_floor_exposure_twh",
    "post_floor_exposure_twh",
    "full_site_total_electricity_anchor_twh",
    "grid_import_anchor_twh",
    "residual_to_total_anchor_twh",
    "residual_to_grid_import_anchor_twh",
    "interpretation",
    "caveat",
]

NG_GAP_COLUMNS = [
    "configuration",
    "scenario",
    "current_modelled_ng_pj",
    "candidate_overlay_ng_pj",
    "full_site_ng_anchor_pj",
    "residual_to_ng_anchor_pj",
    "category_anchor_gap_pj",
    "interpretation",
    "caveat",
]

CO2_COLUMNS = [
    "configuration",
    "co2_mode",
    "included_components",
    "excluded_components",
    "process_aggregate_co2_mt",
    "fuel_explicit_co2_mt",
    "captured_co2_stream_mt",
    "scope2_reporting_co2_mt",
    "diagnostic_total_mt",
    "public_scope1_anchor_mt",
    "gap_to_scope1_anchor_mt",
    "double_counting_risk",
    "ets_ready",
    "interpretation",
    "caveat",
]

MIGRATION_COLUMNS = [
    "candidate_parameter_id",
    "source_card",
    "domain",
    "current_status",
    "recommended_model_use",
    "overlay_effect",
    "improves_anchor_fit",
    "introduces_new_risk",
    "source_strength",
    "local_locator_verified",
    "migration_recommendation",
    "required_before_migration",
    "sensitivity_required",
    "caveat",
]

REDFLAG_COLUMNS = ["red_flag", "active", "severity", "evidence", "recommended_action"]

FAILURE_FLAGS = [
    "SOURCE_CARD_VALUES_MIGRATED_TO_EXECUTABLE_INPUTS",
    "MODEL_EQUATIONS_CHANGED",
    "RESIDUAL_LOAD_ADDED",
    "VALIDATION_ANCHOR_FORCED",
    "ANNUAL_ANCHOR_USED_AS_HOURLY_SCHEDULE",
    "GENERIC_VALUE_PROMOTED_TO_THESIS_TRUTH",
    "WAG_CARBON_DOUBLE_COUNTED",
    "DRP_CAPTURE_STREAM_COUNTED_AS_DIRECT_EMISSION",
    "AGGREGATE_AND_FUEL_EXPLICIT_CO2_SUMMED_TOGETHER",
    "SCOPE2_CLAIMED_WITHOUT_ELECTRICITY_BOUNDARY",
    "ETS_READY_CLAIMED",
    "ECONOMICS_ACTIVE",
    "DA_PRICE_RESPONSE_ACTIVE",
    "GENERATOR_EXPORT_REVENUE_ACTIVE",
    "MFRR_ACTIVE",
    "DENOMINATOR_FROZEN",
    "C5L_D_BASE_0_50_REVERTED",
    "COKE_RECONCILIATION_BASELINE_REOPENED",
    "THESIS_USABILITY_TRUE_FOR_DEVELOPMENT_ROWS",
]

CAVEATS = [
    "CANDIDATE_OVERLAY_DIAGNOSTIC_ONLY",
    "SOURCE_CARD_VALUES_NOT_EXECUTABLE",
    "SOME_SOURCE_LOCATORS_NOT_LOCALLY_VERIFIED",
    "RESIDUAL_ELECTRICITY_REMAINS_DIAGNOSTIC",
    "RESIDUAL_NG_REMAINS_DIAGNOSTIC",
    "CO2_BOUNDARY_NOT_ETS_READY",
    "WAG_CARBON_POLICY_REQUIRED",
    "C0_GENERATOR_SPLIT_NOT_FOUND",
    "C1_GENERATOR_GAP_REQUIRES_REVIEW",
    "DENOMINATOR_UNRESOLVED",
    "NOT_THESIS_APPROVED",
]

REQUIRED_SOURCE_CARDS = [
    "HSM_Parameters.md",
    "BOF_OSF_Parameters.md",
    "Coking_Plants_Parameters.md",
    "DSP_Parameters.md",
    "BOILER_STEAM_CIRCUIT_Parameters.md",
    "IJ01_VN25_GENERATORS_Parameters.md",
    "WAG_CARRIERS_CO2_FACTORS_Parameters.md",
]


def _num(value: Any, default: float = math.nan) -> float:
    if value in (None, "", "nan", "NaN"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _blank_nan(value: float | None, digits: int = 6) -> float | str:
    if value is None or math.isnan(value):
        return ""
    return round(value, digits)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _annual_rows() -> list[dict[str, str]]:
    return _read_csv(C5P_E_DIR / "c5_annual_anchor_reconciliation_matrix.csv")


def _annual_value(rows: list[dict[str, str]], configuration: str, anchor_id: str) -> float:
    for row in rows:
        if row["configuration"] == configuration and row["anchor_id"] == anchor_id:
            return _num(row["model_output"], 0.0)
    raise KeyError((configuration, anchor_id))


def _electricity_summary() -> dict[tuple[str, str], float]:
    rows = _read_csv(C5P_H_DIR / "c5_plant_electricity_anchor_summary.csv")
    return {
        (row["configuration"], row["plant_or_asset"]): _num(row["current_model_electricity_twh_y"], 0.0)
        for row in rows
    }


def _ng_summary() -> dict[tuple[str, str], float]:
    rows = _read_csv(C5P_H_DIR / "c5_plant_ng_anchor_summary.csv")
    return {(row["configuration"], row["plant_or_asset"]): _num(row["current_model_ng_pj_y"], 0.0) for row in rows}


def _electricity_boundary() -> dict[str, dict[str, str]]:
    rows = _read_csv(C5P_G_DIR / "c5_residual_electricity_boundary_matrix.csv")
    return {row["configuration"]: row for row in rows}


def _ng_boundary() -> dict[str, dict[str, str]]:
    rows = _read_csv(C5P_G_DIR / "c5_residual_ng_boundary_matrix.csv")
    return {row["configuration"]: row for row in rows}


def _co2_boundary() -> dict[str, dict[str, str]]:
    rows = _read_csv(C5P_H_DIR / "c5_co2_boundary_matrix.csv")
    return {row["configuration"]: row for row in rows}


def _build_activity_basis(annual: list[dict[str, str]], p_a_gate: dict[str, Any], p_c_gate: dict[str, Any]) -> list[dict[str, Any]]:
    activity_specs = [
        ("KGF/coking", "kgf_coke_output", "coke production", "t/y", "C5p_e annual reconciliation", True),
        ("BF", "bf_hot_metal", "hot metal driver", "t/y", "C5p_e annual reconciliation", True),
        ("BOF/OSF", "bof_liquid_steel", "BOF liquid steel output", "t/y", "C5p_e annual reconciliation", True),
        ("EAF", "eaf_liquid_steel", "EAF liquid steel output", "t/y", "C5p_e annual reconciliation", True),
        ("DRP", "drp_dri_output", "DRI output", "t/y", "C5p_e annual reconciliation", True),
        ("PEFA/pelletizing", "pefa_output", "fired pellets output", "t/y", "C5p_e annual reconciliation", True),
        ("Sinter", "sinter_output", "sinter output", "t/y", "C5p_e annual reconciliation", True),
        ("DSP", "dsp_output", "DSP coil output", "t/y", "C5p_e annual reconciliation", True),
        ("HSM/WBW", "hsm_wbw_output", "HSM/WBW rolled coil output", "t/y", "C5p_e annual reconciliation", True),
        ("steam circuit", "steam_total_demand", "modelled steam demand", "t steam/y", "C5p_e annual reconciliation", True),
    ]
    rows: list[dict[str, Any]] = []
    for configuration in (C0, C1):
        for plant, anchor_id, metric, unit, source, eligible in activity_specs:
            rows.append(
                {
                    "configuration": configuration,
                    "plant_or_asset": plant,
                    "activity_metric": metric,
                    "activity_value": _annual_value(annual, configuration, anchor_id),
                    "unit": unit,
                    "source_artifact_or_stage": source,
                    "overlay_eligible": str(eligible).lower(),
                    "caveat": "Annualized activity basis only; not an hourly dispatch schedule.",
                }
            )
        oxygen_key = "C0_24h_total_oxygen_t_y" if configuration == C0 else "C1_24h_total_oxygen_t_y"
        rows.append(
            {
                "configuration": configuration,
                "plant_or_asset": "Linde/ASU",
                "activity_metric": "oxygen demand/production",
                "activity_value": p_a_gate[oxygen_key],
                "unit": "t O2/y",
                "source_artifact_or_stage": "C5p_a stage gate",
                "overlay_eligible": "true",
                "caveat": "ASU electricity is already modelled; overlay is a reference only.",
            }
        )
        generator_key = (
            "C0_24h_generator_fuel_PJ_y" if configuration == C0 else "C1_24h_VN25_total_fuel_PJ_y"
        )
        rows.append(
            {
                "configuration": configuration,
                "plant_or_asset": "IJ01/VN25 generator interface",
                "activity_metric": "generator fuel interface",
                "activity_value": p_c_gate[generator_key],
                "unit": "PJ_LHV/y",
                "source_artifact_or_stage": "C5p_c stage gate",
                "overlay_eligible": "true",
                "caveat": "Generator electricity remains internal offset/reporting only.",
            }
        )
    return rows


def _candidate_electricity_rows(
    annual: list[dict[str, str]], current_electricity: dict[tuple[str, str], float]
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], float]]:
    rows: list[dict[str, Any]] = []
    overlay_lookup: dict[tuple[str, str], float] = {}

    def add(
        configuration: str,
        plant: str,
        activity_anchor: str,
        candidate_id: str,
        value: float,
        unit: str,
        source_status: str,
        use: str,
        source_card: str,
        caveat: str,
        overlay_twh: float | None = None,
    ) -> None:
        activity = _annual_value(annual, configuration, activity_anchor)
        if overlay_twh is None:
            overlay_twh = activity * value * TWH_PER_MWH
        current = current_electricity.get((configuration, plant), 0.0)
        overlay_lookup[(configuration, candidate_id)] = overlay_twh
        rows.append(
            {
                "configuration": configuration,
                "plant_or_asset": plant,
                "activity_metric": activity_anchor,
                "activity_value": activity,
                "candidate_parameter_id": candidate_id,
                "candidate_value": value,
                "candidate_unit": unit,
                "source_status": source_status,
                "recommended_model_use": use,
                "overlay_electricity_twh_y": overlay_twh,
                "current_model_electricity_twh_y": current,
                "delta_vs_current_twh_y": overlay_twh - current,
                "source_card": source_card,
                "caveat": caveat,
            }
        )

    for configuration in (C0, C1):
        add(
            configuration,
            "HSM/WBW",
            "hsm_wbw_output",
            "HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID",
            0.104,
            "MWh/t HRC",
            "source_backed_candidate",
            "development_input_candidate / sensitivity_range",
            "HSM_Parameters.md",
            "Khalid value is not locally locator-verified and is not Tata WBW-specific.",
        )
        add(
            configuration,
            "DSP",
            "dsp_output",
            "DSP_ELECTRICITY_MWH_PER_T_DSP_COIL_SENS_HIGH",
            0.104,
            "MWh/t DSP coil",
            "source_backed_candidate / sensitivity_only",
            "sensitivity_range",
            "DSP_Parameters.md",
            "HSM proxy, not DSP-specific; use as high sensitivity only.",
        )
        add(
            configuration,
            "BOF/OSF",
            "bof_liquid_steel",
            "BOF_ELECTRICITY_MWH_PER_T_LS_BIEDA",
            0.02682,
            "MWh/t liquid steel",
            "source_backed_candidate",
            "development_input_candidate / cross-check",
            "BOF_OSF_Parameters.md",
            "Polish BOF LCI candidate, not Tata; source locator not locally verified.",
        )
        add(
            configuration,
            "KGF/coking",
            "kgf_coke_output",
            "KGF_ELECTRICITY_PURCHASED_GJ_PER_T_COKE",
            0.0667,
            "MWh/t coke",
            "source_backed_candidate",
            "development_input_candidate / sensitivity_range",
            "Coking_Plants_Parameters.md",
            "Converted from 0.24 GJ/t; non-Tata LCI and local locator not verified.",
        )
        add(
            configuration,
            "KGF/coking",
            "kgf_coke_output",
            "KGF_ELECTRICITY_GROSS_SERVICE_GJ_PER_T_COKE",
            0.0972,
            "MWh/t coke",
            "derived_candidate",
            "sensitivity_range / gross auxiliary demand candidate",
            "Coking_Plants_Parameters.md",
            "Gross before internal recovery; do not net without CDQ/recovery representation.",
        )
        add(
            configuration,
            "DSP",
            "dsp_output",
            "DSP_ELECTRICITY_MWH_PER_T_DSP_COIL_BASE",
            0.056,
            "MWh/t DSP coil",
            "governed_assumption",
            "current_baseline_reference",
            "DSP_Parameters.md",
            "Current compact C5 DSP assumption; not a measured DSP source.",
        )

    return rows, overlay_lookup


def _candidate_ng_fuel_rows(
    annual: list[dict[str, str]], current_ng: dict[tuple[str, str], float]
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], float]]:
    rows: list[dict[str, Any]] = []
    overlay_lookup: dict[tuple[str, str], float] = {}

    def add(
        configuration: str,
        plant: str,
        carrier: str,
        activity_anchor: str,
        candidate_id: str,
        value: float | str,
        unit: str,
        source_status: str,
        use: str,
        source_card: str,
        caveat: str,
        overlay_pj: float | None,
        current_pj: float | None = None,
    ) -> None:
        activity = _annual_value(annual, configuration, activity_anchor)
        if current_pj is None:
            current_pj = current_ng.get((configuration, plant), 0.0)
        if overlay_pj is not None:
            overlay_lookup[(configuration, candidate_id)] = overlay_pj
        rows.append(
            {
                "configuration": configuration,
                "plant_or_asset": plant,
                "fuel_or_energy_carrier": carrier,
                "activity_metric": activity_anchor,
                "activity_value": activity,
                "candidate_parameter_id": candidate_id,
                "candidate_value": value,
                "candidate_unit": unit,
                "source_status": source_status,
                "recommended_model_use": use,
                "overlay_fuel_pj_y": _blank_nan(overlay_pj),
                "current_model_fuel_pj_y": _blank_nan(current_pj),
                "delta_vs_current_pj_y": _blank_nan(None if overlay_pj is None else overlay_pj - (current_pj or 0.0)),
                "source_card": source_card,
                "caveat": caveat,
            }
        )

    for configuration in (C0, C1):
        hsm_output = _annual_value(annual, configuration, "hsm_wbw_output")
        hsm_khalid = hsm_output * 1.268 * PJ_PER_GJ
        hsm_current = _annual_value(annual, configuration, "boiler_hsm_reheat")
        add(
            configuration,
            "HSM/WBW",
            "reheat_fuel_unspecified_WAG_or_NG",
            "hsm_wbw_output",
            "HSM_REHEAT_FUEL_GJ_PER_T_HRC_KHALID",
            1.268,
            "GJ/t HRC",
            "source_backed_candidate",
            "development_input_candidate / sensitivity_range",
            "HSM_Parameters.md",
            "Fuel carrier is not fixed; treating this as NG would be a policy scenario, not base truth.",
            hsm_khalid,
            hsm_current,
        )
        coke = _annual_value(annual, configuration, "kgf_coke_output")
        kgf_heating = coke * 4.30 * PJ_PER_GJ
        kgf_current_underfiring = coke * 3.55 * PJ_PER_GJ
        add(
            configuration,
            "KGF/coking",
            "COG_self_use_underfiring",
            "kgf_coke_output",
            "KGF_COG_FOR_HEATING_GJ_PER_T_COKE",
            4.30,
            "GJ/t coke",
            "source_backed_candidate",
            "development_input_candidate / sensitivity_range",
            "Coking_Plants_Parameters.md",
            "Use as self-use candidate only; do not also treat same COG energy as surplus.",
            kgf_heating,
            kgf_current_underfiring,
        )
        kgf_trading = coke * 3.74 * PJ_PER_GJ
        add(
            configuration,
            "KGF/coking",
            "clean_COG_surplus_candidate",
            "kgf_coke_output",
            "KGF_COG_FOR_TRADING_GJ_PER_T_COKE",
            3.74,
            "GJ/t coke",
            "source_backed_candidate",
            "WAG surplus sanity check",
            "Coking_Plants_Parameters.md",
            "Treat as site WAG-network candidate only, not external revenue.",
            kgf_trading,
            0.0,
        )
        add(
            configuration,
            "BOF/OSF",
            "natural_gas_volume",
            "bof_liquid_steel",
            "BOF_NG_M3_PER_T_LS_BIEDA",
            6.36,
            "m3/t liquid steel",
            "source_backed_candidate",
            "sensitivity_range / auxiliary fuel candidate",
            "BOF_OSF_Parameters.md",
            "Not converted to PJ because source unit is m3 and normalisation/LHV is not locally verified.",
            None,
            current_ng.get((configuration, "BOF/OSF"), 0.0),
        )
        add(
            configuration,
            "BOF/OSF",
            "COG_volume",
            "bof_liquid_steel",
            "BOF_COG_M3_PER_T_LS_BIEDA",
            7.88,
            "m3/t liquid steel",
            "source_backed_candidate",
            "sensitivity_range / auxiliary fuel candidate",
            "BOF_OSF_Parameters.md",
            "Not converted to PJ without reviewed LHV and volume-normalisation convention.",
            None,
            0.0,
        )
        add(
            configuration,
            "boiler/steam",
            "boiler_efficiency_sensitivity",
            "steam_total_demand",
            "BOILER_EFFICIENCY_BASE",
            0.85,
            "fraction fuel energy to useful steam energy",
            "governed_assumption",
            "development_input_candidate / sensitivity_range",
            "BOILER_STEAM_CIRCUIT_Parameters.md",
            "Governed sensitivity only; not used to retune WAG balances in this overlay.",
            None,
            0.0,
        )

    return rows, overlay_lookup


def _electricity_anchor_gap_rows(
    boundary: dict[str, dict[str, str]], elec_lookup: dict[tuple[str, str], float]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in (C0, C1):
        current = _num(boundary[configuration]["gross_modelled_process_demand_twh"], 0.0)
        reported_offsets = _num(boundary[configuration]["total_internal_offset_twh"], 0.0)
        exposure_offset = _num(boundary[configuration]["wag_generator_offset_twh"], 0.0)
        hsm_delta = elec_lookup[(configuration, "HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID")] - _num(
            boundary[configuration]["other_modelled_demand_twh"], 0.0
        )
        # The HSM delta must compare against the current HSM component, not the
        # full "other" bucket. Use the component rows already embedded in p_g.
        hsm_current = next(
            _num(row["annual_value"], 0.0)
            for row in _read_csv(C5P_G_DIR / "c5_residual_electricity_component_balance.csv")
            if row["configuration"] == configuration and row["electricity_component"] == "HSM_WBW_rolling_electricity"
        )
        hsm_delta = elec_lookup[(configuration, "HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID")] - hsm_current
        dsp_current = next(
            _num(row["annual_value"], 0.0)
            for row in _read_csv(C5P_G_DIR / "c5_residual_electricity_component_balance.csv")
            if row["configuration"] == configuration and row["electricity_component"] == "DSP_electricity"
        )
        dsp_delta = elec_lookup[(configuration, "DSP_ELECTRICITY_MWH_PER_T_DSP_COIL_SENS_HIGH")] - dsp_current
        bof_overlay = elec_lookup[(configuration, "BOF_ELECTRICITY_MWH_PER_T_LS_BIEDA")]
        kgf_overlay = elec_lookup[(configuration, "KGF_ELECTRICITY_PURCHASED_GJ_PER_T_COKE")]
        scenarios = [
            (
                "scenario0_current_C5_baseline",
                current,
                "Current C5p_g/h process-only electricity boundary.",
                "No overlay values applied.",
            ),
            (
                "scenario1_conservative_candidate_overlay",
                current,
                "Conservative overlay keeps current C5 modelled plant electricity only.",
                "Higher-risk repaired source-card values remain sensitivity-only.",
            ),
            (
                "scenario2_expanded_generic_overlay",
                current + hsm_delta + dsp_delta + bof_overlay + kgf_overlay,
                "Expanded overlay adds HSM Khalid, DSP high sensitivity, BOF Bieda and KGF Rado-Foty purchased-electricity candidates.",
                "Diagnostic overlay only; possible overlap with unresolved other-modelled electricity bucket must be reviewed.",
            ),
        ]
        for scenario, gross, interpretation, caveat in scenarios:
            pre_floor = gross - exposure_offset
            rows.append(
                {
                    "configuration": configuration,
                    "scenario": scenario,
                    "current_modelled_process_demand_twh": current,
                    "candidate_overlay_gross_demand_twh": gross,
                    "internal_offsets_twh": reported_offsets,
                    "pre_floor_exposure_twh": pre_floor,
                    "post_floor_exposure_twh": max(pre_floor, 0.0),
                    "full_site_total_electricity_anchor_twh": FULL_SITE_ELECTRICITY_CONTEXT_TWH,
                    "grid_import_anchor_twh": "",
                    "residual_to_total_anchor_twh": FULL_SITE_ELECTRICITY_CONTEXT_TWH - gross,
                    "residual_to_grid_import_anchor_twh": "",
                    "interpretation": interpretation,
                    "caveat": f"{caveat} 360 MW context equals {SITE_AVERAGE_POWER_CONTEXT_TWH} TWh/y and remains validation/context only.",
                }
            )
    return rows


def _ng_anchor_gap_rows(
    boundary: dict[str, dict[str, str]], fuel_lookup: dict[tuple[str, str], float]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in (C0, C1):
        current = _num(boundary[configuration]["total_modelled_ng_pj"], 0.0)
        hsm_overlay = fuel_lookup[(configuration, "HSM_REHEAT_FUEL_GJ_PER_T_HRC_KHALID")]
        scenarios = [
            (
                "scenario0_current_C5_baseline",
                current,
                "Current component-level NG boundary.",
                "No full-site NG anchor is active.",
            ),
            (
                "scenario1_conservative_candidate_overlay",
                current,
                "Conservative overlay does not add residual NG or unverified fuel conversions.",
                "Residual NG remains diagnostic only.",
            ),
            (
                "scenario2_expanded_generic_fuel_overlay_if_HSM_reheat_all_NG_equivalent",
                current + hsm_overlay,
                "Expanded fuel overlay shows HSM reheating fuel scale if interpreted as NG-equivalent.",
                "This is a stress diagnostic only; HSM fuel may be WAG/NG mix and is not activated.",
            ),
        ]
        for scenario, ng_total, interpretation, caveat in scenarios:
            category_gap = ng_total - DRP_ONLY_NG_CONTEXT_PJ_C1 if configuration == C1 else math.nan
            rows.append(
                {
                    "configuration": configuration,
                    "scenario": scenario,
                    "current_modelled_ng_pj": current,
                    "candidate_overlay_ng_pj": ng_total,
                    "full_site_ng_anchor_pj": "",
                    "residual_to_ng_anchor_pj": "",
                    "category_anchor_gap_pj": _blank_nan(category_gap),
                    "interpretation": interpretation,
                    "caveat": caveat,
                }
            )
    return rows


def _co2_mode_rows(annual: list[dict[str, str]], p_h_co2: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in (C0, C1):
        current_direct = _num(p_h_co2[configuration]["direct_process_co2_mt"], 0.0)
        captured = _num(p_h_co2[configuration]["captured_co2_stream_mt"], 0.0)
        public_anchor = PUBLIC_SCOPE1_ANCHORS_MT[configuration]
        bof_ls = _annual_value(annual, configuration, "bof_liquid_steel")
        coke = _annual_value(annual, configuration, "kgf_coke_output")
        pefa = _annual_value(annual, configuration, "pefa_co2") / 1_000_000.0
        eaf = _annual_value(annual, configuration, "eaf_co2") / 1_000_000.0
        bof = bof_ls * 0.0825 / 1_000_000.0
        kgf = coke * 0.4595 / 1_000_000.0
        aggregate_total = pefa + eaf + bof + kgf
        mode_specs = [
            (
                "scenario0_current_component_diagnostic",
                "PEFA/EAF/DSP current component diagnostics",
                "WAG combustion; NG combustion; scope2; BF/BOF/KGF aggregate candidates",
                current_direct,
                math.nan,
                math.nan,
                current_direct,
                "risk_reported_not_summed",
                "Current C5p_h component diagnostic only; not full-site Scope 1.",
                "Current mode preserves C5p_h boundary and ETS-ready remains false.",
            ),
            (
                "scenario3_aggregate_process_counter_mode",
                "PEFA aggregate; EAF midpoint; BOF Bieda aggregate; KGF Rado-Foty aggregate",
                "WAG combustion; NG combustion; scope2; DRP captured stream as direct emission",
                aggregate_total,
                math.nan,
                math.nan,
                aggregate_total,
                "controlled_by_excluding_WAG_fuel_explicit_CO2",
                "Aggregate process-counter overlay increases visible direct-process diagnostics but still misses BF and other full-site Scope 1 elements.",
                "Do not combine with WAG/fuel-explicit combustion in a consolidated total.",
            ),
            (
                "scenario4_WAG_fuel_explicit_mode_deferred",
                "none computed because official WAG/NG factors are not source-carded as active factors",
                "aggregate BF/BOF/KGF counters; scope2; DRP captured stream as direct emission",
                math.nan,
                math.nan,
                math.nan,
                math.nan,
                "not_computed_missing_factor_source",
                "Fuel-explicit CO2 mode is deferred until official factors and WAG carbon counting policy are frozen.",
                "No invented RVO/National factor URL or unverified Cavaliere-derived factor is used.",
            ),
        ]
        for mode, included, excluded, process, fuel, scope2, total, risk, interpretation, caveat in mode_specs:
            gap = total - public_anchor if not math.isnan(total) else math.nan
            rows.append(
                {
                    "configuration": configuration,
                    "co2_mode": mode,
                    "included_components": included,
                    "excluded_components": excluded,
                    "process_aggregate_co2_mt": _blank_nan(process),
                    "fuel_explicit_co2_mt": _blank_nan(fuel),
                    "captured_co2_stream_mt": captured,
                    "scope2_reporting_co2_mt": _blank_nan(scope2),
                    "diagnostic_total_mt": _blank_nan(total),
                    "public_scope1_anchor_mt": public_anchor,
                    "gap_to_scope1_anchor_mt": _blank_nan(gap),
                    "double_counting_risk": risk,
                    "ets_ready": "false",
                    "interpretation": interpretation,
                    "caveat": caveat,
                }
            )
    return rows


def _migration_rows() -> list[dict[str, Any]]:
    specs = [
        (
            "HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC_KHALID",
            "HSM_Parameters.md",
            "electricity",
            "source_backed_candidate",
            "development_input_candidate / sensitivity_range",
            "Raises HSM electricity versus current 0.070 MWh/t coefficient and reduces C0 over-offset.",
            "yes_for_electricity_boundary_transparency",
            "higher C1 exposure; not Tata-specific",
            "medium_pending_local_locator",
            "false",
            "source_review_required_before_migration",
            "Verify Khalid table/figure locator; reconcile with MER/HSM current assumptions and other-modelled electricity bucket.",
            "true",
            "value_from_reviewed_research_note_not_locally_verified",
        ),
        (
            "HSM_REHEAT_FUEL_GJ_PER_T_HRC_KHALID",
            "HSM_Parameters.md",
            "NG/fuel",
            "source_backed_candidate",
            "development_input_candidate / sensitivity_range",
            "Shows HSM reheating fuel scale but does not identify Tata WAG/NG carrier mix.",
            "partial_for_fuel_boundary",
            "could create false NG demand if treated as all-NG",
            "medium_pending_local_locator",
            "false",
            "use_as_sensitivity_only",
            "Verify source locator; decide WAG/NG carrier policy before migration.",
            "true",
            "do_not_activate_as_residual_NG",
        ),
        (
            "BOF_ELECTRICITY_MWH_PER_T_LS_BIEDA",
            "BOF_OSF_Parameters.md",
            "electricity",
            "source_backed_candidate",
            "development_input_candidate / cross-check",
            "Adds visible BOF electricity candidate where current plant-level value is not separated.",
            "yes_if_other_modelled_bucket_is_decomposed",
            "possible overlap with current other-modelled electricity bucket",
            "medium_pending_local_locator",
            "false",
            "source_review_required_before_migration",
            "Verify Bieda table locator and decompose current other-modelled electricity first.",
            "true",
            "Polish BOF LCI, not Tata.",
        ),
        (
            "BOF_NG_M3_PER_T_LS_BIEDA",
            "BOF_OSF_Parameters.md",
            "NG/fuel",
            "source_backed_candidate",
            "sensitivity_range / auxiliary fuel candidate",
            "Cannot be converted to PJ without verified volume/LHV basis.",
            "no",
            "unit-normalisation and carrier-boundary risk",
            "low_until_volume_basis_verified",
            "false",
            "source_review_required_before_migration",
            "Verify source unit and LHV/normal conditions before any energy conversion.",
            "true",
            "source unit m3 preserved; no PJ overlay computed.",
        ),
        (
            "KGF_ELECTRICITY_PURCHASED_GJ_PER_T_COKE",
            "Coking_Plants_Parameters.md",
            "electricity",
            "source_backed_candidate",
            "development_input_candidate / sensitivity_range",
            "Adds KGF electricity candidate where current plant-level value is not separated.",
            "yes_for_residual_electricity_explanation",
            "non-Tata LCI and possible boundary overlap with other-modelled electricity",
            "medium_pending_local_locator",
            "false",
            "source_review_required_before_migration",
            "Verify Rado-Foty table locator and reconcile KGF electricity boundary.",
            "true",
            "value_from_reviewed_research_note_not_locally_verified",
        ),
        (
            "KGF_COG_FOR_HEATING_GJ_PER_T_COKE",
            "Coking_Plants_Parameters.md",
            "WAG/fuel",
            "source_backed_candidate",
            "development_input_candidate / sensitivity_range",
            "Raises KGF COG self-use relative to current 3.55 GJ/t coke candidate.",
            "not_for_NG_but_relevant_for_WAG_gap",
            "can reduce available surplus COG if applied without reconciliation",
            "medium_pending_local_locator",
            "false",
            "use_as_sensitivity_only",
            "Reconcile gross COG generation, self-use and surplus before migration.",
            "true",
            "do not also treat same COG energy as surplus.",
        ),
        (
            "KGF_DIRECT_CO2_T_PER_T_COKE_AGGREGATE",
            "Coking_Plants_Parameters.md",
            "CO2",
            "source_backed_candidate",
            "aggregate CO2 validation/sensitivity",
            "Raises aggregate process-counter CO2 in scenario 3.",
            "partial_for_scope1_gap_visibility",
            "high double-counting risk with COG combustion",
            "medium_pending_local_locator",
            "false",
            "use_as_validation_only",
            "Freeze WAG carbon policy and verify local source locator before any CO2 migration.",
            "true",
            "Use aggregate KGF counter or WAG-explicit COG combustion, not both.",
        ),
        (
            "BOF_DIRECT_CO2_T_PER_T_LS_BIEDA",
            "BOF_OSF_Parameters.md",
            "CO2",
            "source_backed_candidate",
            "aggregate CO2 validation/sensitivity",
            "Raises aggregate process-counter CO2 in scenario 3.",
            "partial_for_scope1_gap_visibility",
            "double-counting risk with BOFG combustion",
            "medium_pending_local_locator",
            "false",
            "use_as_validation_only",
            "Freeze BOFG carbon policy and verify source locator.",
            "true",
            "Use aggregate BOF counter or BOFG combustion, not both.",
        ),
        (
            "BOILER_EFFICIENCY_BASE",
            "BOILER_STEAM_CIRCUIT_Parameters.md",
            "NG/fuel",
            "governed_assumption",
            "development_input_candidate / sensitivity_range",
            "Frames boiler fuel-to-steam sensitivity but does not retune current WAG balance.",
            "no_direct_anchor_fit_claim",
            "could become hidden calibration if misused",
            "governed_assumption_not_source_backed",
            "true",
            "use_as_sensitivity_only",
            "Do not migrate until residual steam demand and boiler fuel allocation policy are reviewed.",
            "true",
            "No Tata-specific boiler efficiency source.",
        ),
        (
            "WAG_OFFICIAL_CO2_FACTOR_SOURCE_REPAIR",
            "WAG_CARRIERS_CO2_FACTORS_Parameters.md",
            "CO2",
            "not_found",
            "source_card_repair_needed / deferred",
            "Blocks fuel-explicit WAG/NG CO2 computation.",
            "not_until_source_repair",
            "invented factors would invalidate ETS/economics claims",
            "not_found",
            "false",
            "deferred",
            "Add official factor source and freeze WAG carbon-counting policy.",
            "true",
            "No factor computed in p_i.",
        ),
    ]
    return [
        {
            "candidate_parameter_id": row[0],
            "source_card": row[1],
            "domain": row[2],
            "current_status": row[3],
            "recommended_model_use": row[4],
            "overlay_effect": row[5],
            "improves_anchor_fit": row[6],
            "introduces_new_risk": row[7],
            "source_strength": row[8],
            "local_locator_verified": row[9],
            "migration_recommendation": row[10],
            "required_before_migration": row[11],
            "sensitivity_required": row[12],
            "caveat": row[13],
        }
        for row in specs
    ]


def _red_flags() -> list[dict[str, str]]:
    return [
        {
            "red_flag": flag,
            "active": "false",
            "severity": "failure" if flag in FAILURE_FLAGS else "caveat",
            "evidence": "p_i is diagnostic-only and writes only overlay artifacts.",
            "recommended_action": "Keep candidate overlay separate from executable input migration.",
        }
        for flag in FAILURE_FLAGS
    ] + [
        {
            "red_flag": caveat,
            "active": "true",
            "severity": "caveat",
            "evidence": "Overlay diagnostics use source-card candidates and incomplete current C5 boundaries.",
            "recommended_action": "Resolve source verification, residual energy boundary and WAG carbon policy before economics.",
        }
        for caveat in CAVEATS
    ]


def _write_report(
    electricity_gap: list[dict[str, Any]],
    ng_gap: list[dict[str, Any]],
    co2_rows: list[dict[str, Any]],
    migration_rows: list[dict[str, Any]],
) -> None:
    def row_for(rows: list[dict[str, Any]], configuration: str, scenario: str) -> dict[str, Any]:
        return next(row for row in rows if row["configuration"] == configuration and row["scenario"] == scenario)

    c0_current = row_for(electricity_gap, C0, "scenario0_current_C5_baseline")
    c0_expanded = row_for(electricity_gap, C0, "scenario2_expanded_generic_overlay")
    c1_current = row_for(electricity_gap, C1, "scenario0_current_C5_baseline")
    c1_expanded = row_for(electricity_gap, C1, "scenario2_expanded_generic_overlay")
    c1_ng_expanded = row_for(ng_gap, C1, "scenario2_expanded_generic_fuel_overlay_if_HSM_reheat_all_NG_equivalent")
    migrate_later = [
        row["candidate_parameter_id"]
        for row in migration_rows
        if row["migration_recommendation"] == "source_review_required_before_migration"
    ]
    sensitivity = [
        row["candidate_parameter_id"]
        for row in migration_rows
        if row["migration_recommendation"] == "use_as_sensitivity_only"
    ]
    report = f"""# C5 Source-Card Candidate Overlay Reconciliation

Status: development-only diagnostic report.

Thesis usability: false.

This report summarizes `S4.4c5p_i_source_card_candidate_overlay_reconciliation`.
The stage applies repaired source-card candidate values to current annualized
C5 activity outputs as post-processing diagnostics only. It does not migrate
values into executable inputs, add residual loads, change model equations,
create CO2 costs, or activate economics/DA behaviour.

## Electricity overlay

- C0 current gross modelled demand: {c0_current['candidate_overlay_gross_demand_twh']:.6f} TWh/y.
- C0 expanded generic overlay gross demand: {c0_expanded['candidate_overlay_gross_demand_twh']:.6f} TWh/y.
- C0 expanded pre-floor exposure after internal offsets: {c0_expanded['pre_floor_exposure_twh']:.6f} TWh/y.
- C1 current gross modelled demand: {c1_current['candidate_overlay_gross_demand_twh']:.6f} TWh/y.
- C1 expanded generic overlay gross demand: {c1_expanded['candidate_overlay_gross_demand_twh']:.6f} TWh/y.
- C1 expanded pre-floor exposure after internal offsets: {c1_expanded['pre_floor_exposure_twh']:.6f} TWh/y.

The expanded electricity overlay reduces the C0 over-offset but does not solve
the residual electricity boundary. The 3 TWh/y and 360 MW context anchors remain
validation/context only.

## NG and fuel overlay

- C1 current modelled NG: {row_for(ng_gap, C1, 'scenario0_current_C5_baseline')['candidate_overlay_ng_pj']:.6f} PJ/y.
- C1 expanded HSM NG-equivalent fuel stress: {c1_ng_expanded['candidate_overlay_ng_pj']:.6f} PJ/y.

The HSM fuel overlay is a fuel-scale stress diagnostic. It is not an active NG
load because the HSM carrier split between WAG and NG is not source-frozen.
BOF volume-fuel candidates are not converted to PJ without verified LHV and
normalization.

## CO2 overlay

CO2 remains component-diagnostic only. Aggregate process-counter mode and
fuel-explicit WAG/NG mode are separated. Fuel-explicit WAG/NG CO2 is not
computed because official factors are not source-carded as active factors.
ETS readiness remains false.

## Migration recommendations

Source review required before migration:

{chr(10).join(f'- `{item}`' for item in migrate_later)}

Sensitivity-only:

{chr(10).join(f'- `{item}`' for item in sensitivity)}

## Gate decision

- Migration proposal to executable development inputs: NO-GO until source
  locators, duplicate-boundary checks and sensitivity decisions are complete.
- Residual electricity/NG implementation: NO-GO.
- Consolidated CO2 implementation: NO-GO until WAG carbon policy and official
  factors are frozen.
- Economics and DA readiness: NO-GO.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def run_s4_4c5p_i_source_card_candidate_overlay_reconciliation() -> dict[str, Any]:
    missing_cards = [name for name in REQUIRED_SOURCE_CARDS if not (SOURCE_CARD_DIR / name).exists()]
    if missing_cards:
        raise FileNotFoundError(f"Missing required repaired source cards: {missing_cards}")

    annual = _annual_rows()
    p_a_gate = _load_json(C5P_A_DIR / "s4_4c5p_a_stage_gate.json")
    p_c_gate = _load_json(C5P_C_DIR / "s4_4c5p_c_stage_gate.json")
    p_f_gate = _load_json(C5P_F_DIR / "s4_4c5p_f_stage_gate.json")
    p_g_gate = _load_json(C5P_G_DIR / "s4_4c5p_g_stage_gate.json")
    p_h_gate = _load_json(C5P_H_DIR / "s4_4c5p_h_stage_gate.json")

    activity = _build_activity_basis(annual, p_a_gate, p_c_gate)
    elec_rows, elec_lookup = _candidate_electricity_rows(annual, _electricity_summary())
    fuel_rows, fuel_lookup = _candidate_ng_fuel_rows(annual, _ng_summary())
    elec_gap = _electricity_anchor_gap_rows(_electricity_boundary(), elec_lookup)
    ng_gap = _ng_anchor_gap_rows(_ng_boundary(), fuel_lookup)
    co2_rows = _co2_mode_rows(annual, _co2_boundary())
    migration = _migration_rows()
    red_flags = _red_flags()

    _write_csv(C5P_I_DIR / "c5_candidate_overlay_activity_basis.csv", activity, ACTIVITY_COLUMNS)
    _write_csv(C5P_I_DIR / "c5_candidate_overlay_electricity_by_plant.csv", elec_rows, ELECTRICITY_COLUMNS)
    _write_csv(C5P_I_DIR / "c5_candidate_overlay_ng_fuel_by_plant.csv", fuel_rows, NG_FUEL_COLUMNS)
    _write_csv(C5P_I_DIR / "c5_candidate_overlay_electricity_anchor_gap.csv", elec_gap, ELECTRICITY_GAP_COLUMNS)
    _write_csv(C5P_I_DIR / "c5_candidate_overlay_ng_anchor_gap.csv", ng_gap, NG_GAP_COLUMNS)
    _write_csv(C5P_I_DIR / "c5_candidate_overlay_co2_mode_comparison.csv", co2_rows, CO2_COLUMNS)
    _write_csv(C5P_I_DIR / "c5_candidate_overlay_migration_recommendations.csv", migration, MIGRATION_COLUMNS)
    _write_csv(C5P_I_DIR / "c5_candidate_overlay_red_flags.csv", red_flags, REDFLAG_COLUMNS)
    _write_report(elec_gap, ng_gap, co2_rows, migration)

    c0_expanded = next(
        row for row in elec_gap if row["configuration"] == C0 and row["scenario"] == "scenario2_expanded_generic_overlay"
    )
    c1_expanded = next(
        row for row in elec_gap if row["configuration"] == C1 and row["scenario"] == "scenario2_expanded_generic_overlay"
    )
    c1_ng_expanded = next(
        row
        for row in ng_gap
        if row["configuration"] == C1
        and row["scenario"] == "scenario2_expanded_generic_fuel_overlay_if_HSM_reheat_all_NG_equivalent"
    )
    aggregate_c0 = next(
        row for row in co2_rows if row["configuration"] == C0 and row["co2_mode"] == "scenario3_aggregate_process_counter_mode"
    )
    aggregate_c1 = next(
        row for row in co2_rows if row["configuration"] == C1 and row["co2_mode"] == "scenario3_aggregate_process_counter_mode"
    )

    gate = {
        "stage_id": STAGE,
        "status": "development_only",
        "thesis_usability": False,
        "decision": "pass_development_source_card_candidate_overlay_reconciliation",
        "failure_count": sum(1 for row in red_flags if row["severity"] == "failure" and row["active"] == "true"),
        "caveat_count": sum(1 for row in red_flags if row["severity"] == "caveat" and row["active"] == "true"),
        "denominator_status": p_f_gate["denominator_status"],
        "electricity_boundary_status": p_g_gate["electricity_boundary_status"],
        "ng_boundary_status": p_g_gate["ng_boundary_status"],
        "co2_boundary_status": p_h_gate["co2_boundary_status"],
        "generator_electricity_accounting_status": p_h_gate["generator_electricity_accounting_status"],
        "residual_electricity_implementation": "NO_GO",
        "residual_ng_implementation": "NO_GO",
        "co2_implementation": "NO_GO",
        "economics_readiness": "NO_GO",
        "DA_readiness": "NO_GO",
        "candidate_values_migrated_to_executable_inputs": False,
        "C0_expanded_overlay_gross_electricity_TWh_y": c0_expanded["candidate_overlay_gross_demand_twh"],
        "C1_expanded_overlay_gross_electricity_TWh_y": c1_expanded["candidate_overlay_gross_demand_twh"],
        "C1_expanded_fuel_overlay_if_HSM_all_NG_PJ_y": c1_ng_expanded["candidate_overlay_ng_pj"],
        "C0_aggregate_process_counter_CO2_Mt_y": aggregate_c0["diagnostic_total_mt"],
        "C1_aggregate_process_counter_CO2_Mt_y": aggregate_c1["diagnostic_total_mt"],
        "output_directory": str(C5P_I_DIR),
    }
    _write_json(C5P_I_DIR / "s4_4c5p_i_stage_gate.json", gate)
    _write_json(
        C5P_I_DIR / "s4_4c5p_i_summary.json",
        {
            "stage": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "electricity_overlay_scenarios": 3,
            "ng_overlay_scenarios": 3,
            "co2_modes": 3,
            "migration_recommendation_rows": len(migration),
            "failure_count": gate["failure_count"],
            "caveats": CAVEATS,
        },
    )
    _write_csv(
        C5P_I_DIR / "s4_4c5p_i_run_registry.csv",
        [
            {
                "stage": STAGE,
                "output_directory": str(C5P_I_DIR),
                "source": "C5p_e_C5p_g_C5p_h_artifacts_plus_repaired_source_cards",
                "model_behavior_changed": "false",
                "thesis_usability": "false",
            }
        ],
    )
    return gate


def main() -> int:
    run_s4_4c5p_i_source_card_candidate_overlay_reconciliation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
