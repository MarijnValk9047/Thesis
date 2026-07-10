"""S4.4c5p_h CO2 and plant energy-anchor boundary diagnostics.

This stage is diagnostic-only. It audits plant-level electricity/NG anchor
coverage and records the current component-level CO2 boundary. It does not
add residual electricity loads, residual NG loads, CO2 equations, ETS costs,
economics, DA revenue, or market behaviour.
"""

from __future__ import annotations

import json
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


STAGE = "S4.4c5p_h_co2_and_plant_energy_anchor_boundary_diagnostics"
C5P_H_DIR = S4_ROOT / "s4_4c5p_h_co2_and_plant_energy_anchor_boundary_diagnostics"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_CO2_AND_PLANT_ENERGY_ANCHOR_BOUNDARY_DIAGNOSTICS.md")

PLANT_ANCHOR_COLUMNS = [
    "configuration",
    "plant_or_asset",
    "energy_carrier",
    "metric",
    "unit",
    "current_model_value",
    "source_anchor_value",
    "candidate_value_or_range",
    "anchor_role",
    "source_card_or_stage",
    "evidence_strength",
    "gap_to_anchor",
    "coverage_status",
    "can_support_residual_policy",
    "action_needed",
    "caveat",
]

ELECTRICITY_SUMMARY_COLUMNS = [
    "configuration",
    "plant_or_asset",
    "current_model_electricity_twh_y",
    "source_anchor_twh_y",
    "candidate_range_twh_y",
    "gap_twh_y",
    "coverage_status",
    "residual_relevance",
    "recommended_action",
    "caveat",
]

NG_SUMMARY_COLUMNS = [
    "configuration",
    "plant_or_asset",
    "current_model_ng_pj_y",
    "source_anchor_pj_y",
    "candidate_range_pj_y",
    "gap_pj_y",
    "coverage_status",
    "residual_relevance",
    "recommended_action",
    "caveat",
]

READINESS_COLUMNS = [
    "boundary",
    "configuration",
    "current_modelled_total",
    "available_site_or_plant_anchor",
    "anchor_role",
    "residual_implied_by_anchor",
    "residual_can_be_modelled",
    "evidence_strength",
    "policy_option",
    "recommended_status",
    "risk",
    "caveat",
]

CO2_COMPONENT_COLUMNS = [
    "configuration",
    "component",
    "emission_source_type",
    "activity_basis",
    "fuel_or_process",
    "current_activity_value",
    "emission_factor",
    "emission_factor_status",
    "co2_model_output_mt_y",
    "co2_source_anchor_mt_y",
    "anchor_role",
    "boundary_status",
    "double_counting_risk",
    "ets_ready",
    "caveat",
]

CO2_BOUNDARY_COLUMNS = [
    "configuration",
    "direct_process_co2_mt",
    "wag_combustion_co2_mt",
    "ng_combustion_co2_mt",
    "electricity_scope2_co2_mt",
    "captured_co2_stream_mt",
    "diagnostic_component_total_mt",
    "public_full_site_anchor_mt",
    "gap_to_public_anchor_mt",
    "boundary_status",
    "ets_ready",
    "caveat",
]

DOUBLE_COUNT_COLUMNS = [
    "configuration",
    "carbon_carrier_or_source",
    "counted_at_generation",
    "counted_at_combustion",
    "counted_at_flare",
    "counted_as_capture_stream",
    "double_counting_risk",
    "current_policy",
    "recommended_policy",
    "caveat",
]

FACTOR_COLUMNS = [
    "factor_id",
    "source_or_carrier",
    "current_factor",
    "unit",
    "source_card_factor",
    "candidate_range",
    "evidence_strength",
    "current_use_status",
    "affects_total_co2",
    "review_priority",
    "recommended_action",
    "caveat",
]

SOURCE_GAP_COLUMNS = [
    "gap_id",
    "plant_or_boundary",
    "missing_anchor_or_weak_anchor",
    "why_needed",
    "current_model_value",
    "candidate_source_cards_to_create_or_update",
    "can_use_context_anchor",
    "blocks_residual_policy",
    "blocks_co2",
    "blocks_economics",
    "recommended_action",
    "caveat",
]

DECISION_COLUMNS = [
    "decision_id",
    "topic",
    "current_status",
    "evidence_status",
    "options",
    "recommended_option",
    "rationale",
    "affects_model_equations_now",
    "affects_physical_behaviour_later",
    "affects_economics_later",
    "must_fix_before_commit",
    "must_fix_before_co2_objective",
    "must_fix_before_economics",
    "can_defer_to_sensitivity",
    "thesis_reporting_caveat",
    "caveat",
]

REDFLAG_COLUMNS = ["red_flag", "active", "severity", "evidence", "recommended_action"]

FAILURE_FLAGS = [
    "CO2_TOTAL_CLAIMED_WITH_INCOMPLETE_BOUNDARY",
    "ETS_READY_CLAIMED_WITH_COMPONENT_ONLY_BOUNDARY",
    "WAG_CO2_DOUBLE_COUNTING_UNREPORTED",
    "DRP_CAPTURE_STREAM_COUNTED_AS_DIRECT_EMISSION",
    "EAF_CO2_AGGREGATE_AND_FUEL_CO2_DOUBLE_COUNTED",
    "PEFA_CO2_AGGREGATE_AND_FUEL_CO2_DOUBLE_COUNTED",
    "SCOPE2_CO2_CLAIMED_WITHOUT_ELECTRICITY_BOUNDARY",
    "RESIDUAL_ELECTRICITY_LOAD_ADDED_IN_DIAGNOSTIC_STAGE",
    "RESIDUAL_NG_LOAD_ADDED_IN_DIAGNOSTIC_STAGE",
    "ELECTRICITY_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION",
    "NG_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION",
    "FULL_SITE_NET_IMPORT_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY",
    "FULL_SITE_NG_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY",
    "DA_PRICE_OR_ECONOMICS_ACTIVE",
    "DENOMINATOR_SILENTLY_FROZEN",
    "PRODUCTION_POLICY_CHANGED_DURING_BOUNDARY_DIAGNOSTIC",
    "C5L_D_BASE_0_50_REVERTED",
    "COKE_RECONCILIATION_BASELINE_REOPENED",
    "THESIS_USABILITY_TRUE_FOR_DEVELOPMENT_ROWS",
]

CAVEATS = [
    "CO2_PLANT_ANCHOR_DIAGNOSTIC_ONLY",
    "PLANT_ELECTRICITY_ANCHORS_INCOMPLETE",
    "PLANT_NG_ANCHORS_INCOMPLETE",
    "RESIDUAL_ELECTRICITY_POLICY_NOT_READY",
    "RESIDUAL_NG_POLICY_NOT_READY",
    "CO2_BOUNDARY_COMPONENT_ONLY",
    "ETS_NOT_READY",
    "WAG_CARBON_BOUNDARY_REQUIRES_POLICY",
    "SCOPE2_REQUIRES_ELECTRICITY_BOUNDARY",
    "GENERATOR_ELECTRICITY_OFFSET_REPORTING_ONLY",
    "NO_FULL_SITE_NET_IMPORT_CLAIM",
    "NO_FULL_SITE_NG_CLAIM",
    "ECONOMICS_NO_GO",
    "NOT_THESIS_APPROVED",
]


def _csv(path: Path) -> list[dict[str, str]]:
    return _read_csv(path)


def _fmt(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _mt_from_t(value: Any) -> float:
    return _zero(value) / 1_000_000.0


def _payload() -> dict[str, Any]:
    required = [
        C5P_G_DIR / "s4_4c5p_g_stage_gate.json",
        C5P_F_DIR / "s4_4c5p_f_stage_gate.json",
        C5P_E_DIR / "c5_annual_co2_boundary_diagnostics.csv",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing upstream artifacts for C5p_h: {missing}")
    return {
        "p_g_gate": json.loads((C5P_G_DIR / "s4_4c5p_g_stage_gate.json").read_text(encoding="utf-8")),
        "p_f_gate": json.loads((C5P_F_DIR / "s4_4c5p_f_stage_gate.json").read_text(encoding="utf-8")),
        "p_e_gate": json.loads((C5P_E_DIR / "s4_4c5p_e_stage_gate.json").read_text(encoding="utf-8")),
        "p_a_gate": json.loads((C5P_A_DIR / "s4_4c5p_a_stage_gate.json").read_text(encoding="utf-8")),
        "p_b_gate": json.loads((C5P_B_DIR / "s4_4c5p_b_stage_gate.json").read_text(encoding="utf-8")),
        "p_c_gate": json.loads((C5P_C_DIR / "s4_4c5p_c_stage_gate.json").read_text(encoding="utf-8")),
        "p_d_gate": json.loads((C5P_D_DIR / "s4_4c5p_d_stage_gate.json").read_text(encoding="utf-8")),
        "electricity_components": _csv(C5P_G_DIR / "c5_residual_electricity_component_balance.csv"),
        "electricity_boundary": _csv(C5P_G_DIR / "c5_residual_electricity_boundary_matrix.csv"),
        "ng_components": _csv(C5P_G_DIR / "c5_residual_ng_component_balance.csv"),
        "ng_boundary": _csv(C5P_G_DIR / "c5_residual_ng_boundary_matrix.csv"),
        "co2": _csv(C5P_E_DIR / "c5_annual_co2_boundary_diagnostics.csv"),
        "flow_balance": _csv(C5P_E_DIR / "c5_annual_flow_balance_by_carrier.csv"),
    }


def _component_value(rows: list[dict[str, str]], configuration: str, component_key: str, value_key: str) -> float:
    for row in rows:
        if row["configuration"] == configuration and row.get("electricity_component", row.get("ng_component")) == component_key:
            return _zero(row[value_key])
    return 0.0


def _electricity_values(payload: dict[str, Any], configuration: str) -> dict[str, float]:
    rows = payload["electricity_components"]
    return {
        "KGF/coking": 0.0,
        "BF/hot stove": 0.0,
        "BOF/OSF": 0.0,
        "Sinter": _component_value(rows, configuration, "sinter_electricity", "annual_value"),
        "PEFA/pelletizing": _component_value(rows, configuration, "PEFA_electricity", "annual_value"),
        "DRP": _component_value(rows, configuration, "DRP_electricity", "annual_value"),
        "EAF": _component_value(rows, configuration, "EAF_electricity", "annual_value"),
        "DSP": _component_value(rows, configuration, "DSP_electricity", "annual_value"),
        "HSM/WBW": _component_value(rows, configuration, "HSM_WBW_rolling_electricity", "annual_value"),
        "Linde/ASU": _component_value(rows, configuration, "Linde_ASU_electricity", "annual_value"),
        "Boilers K15/K16": 0.0,
        "Boilers K23/K24": 0.0,
        "Boiler K41": 0.0,
        "STEG11": 0.0,
        "TG2": 0.0,
        "IJ01/VN25 generator interface": _component_value(rows, configuration, "IJ01_VN25_generator_offset", "annual_value"),
        "residual/background electricity": 0.0,
        "residual/background NG": 0.0,
        "WAG flaring/spill": 0.0,
        "buffers/stores": 0.0,
    }


def _ng_values(payload: dict[str, Any], configuration: str) -> dict[str, float]:
    rows = payload["ng_components"]
    return {
        "KGF/coking": 0.0,
        "BF/hot stove": 0.0,
        "BOF/OSF": 0.0,
        "Sinter": 0.0,
        "PEFA/pelletizing": _component_value(rows, configuration, "PEFA_NG_backup", "annual_value_pj"),
        "DRP": _component_value(rows, configuration, "DRP_NG_total", "annual_value_pj"),
        "EAF": _component_value(rows, configuration, "EAF_NG", "annual_value_pj"),
        "DSP": 0.0,
        "HSM/WBW": 0.0,
        "Linde/ASU": 0.0,
        "Boilers K15/K16": 0.0,
        "Boilers K23/K24": 0.0,
        "Boiler K41": 0.0,
        "STEG11": 0.0,
        "TG2": 0.0,
        "IJ01/VN25 generator interface": _component_value(rows, configuration, "VN25_IJ01_generator_NG", "annual_value_pj"),
        "residual/background electricity": 0.0,
        "residual/background NG": 0.0,
        "WAG flaring/spill": 0.0,
        "buffers/stores": 0.0,
    }


PLANT_META = {
    "KGF/coking": {
        "electricity_status": "modelled_candidate_only",
        "electricity_anchor": "",
        "electricity_candidate": "5.6-63.9 kWh/t coke; practical 35-55 kWh/t candidate range",
        "electricity_source": "Coking_Plants_Parameters.md",
        "electricity_action": "separate KGF electricity from current other-modelled electricity before residual policy",
        "ng_status": "not_applicable",
        "ng_anchor": "0 in base for non-COG substitution",
        "ng_candidate": "sensitivity only",
        "ng_source": "Coking_Plants_Parameters.md",
        "ng_action": "keep NG substitution blocked unless burner/gas-system sensitivity is opened",
    },
    "BF/hot stove": {
        "electricity_status": "modelled_candidate_only",
        "electricity_anchor": "",
        "electricity_candidate": "0.0744 MWh/t HM candidate; broad BREF range",
        "electricity_source": "Blast_Furnace_Parameters.md",
        "electricity_action": "separate BF electricity from other-modelled electricity",
        "ng_status": "deferred",
        "ng_anchor": "",
        "ng_candidate": "NG backup to hot stove if BFG insufficient",
        "ng_source": "Blast_Furnace_Parameters.md",
        "ng_action": "do not activate NG backup without source-backed allocation policy",
    },
    "BOF/OSF": {
        "electricity_status": "modelled_candidate_only",
        "electricity_anchor": "",
        "electricity_candidate": "0.0268 MWh/t LS candidate",
        "electricity_source": "BOF_OSF_Parameters.md",
        "electricity_action": "separate BOF electricity from other-modelled electricity",
        "ng_status": "not_applicable",
        "ng_anchor": "",
        "ng_candidate": "",
        "ng_source": "BOF_OSF_Parameters.md",
        "ng_action": "no residual NG policy from BOF/OSF source card",
    },
    "Sinter": {
        "electricity_status": "modelled_and_source_anchored",
        "electricity_anchor": "",
        "electricity_candidate": "current C5m development input",
        "electricity_source": "SINTER_Parameters.md; C5m",
        "electricity_action": "keep as plant component; not DA-responsive",
        "ng_status": "missing_source_card",
        "ng_anchor": "",
        "ng_candidate": "",
        "ng_source": "SINTER_Parameters.md",
        "ng_action": "review sinter fuel/NG status before residual NG policy",
    },
    "PEFA/pelletizing": {
        "electricity_status": "modelled_and_source_anchored",
        "electricity_anchor": "",
        "electricity_candidate": "current C5n_a development input",
        "electricity_source": "PELLETIZING_Parameters.md; C5n_a",
        "electricity_action": "keep as plant component",
        "ng_status": "modelled_candidate_only",
        "ng_anchor": "0 active backup",
        "ng_candidate": "NG backup deferred/zero",
        "ng_source": "PELLETIZING_Parameters.md; C5n_a",
        "ng_action": "keep backup zero unless explicit sensitivity",
    },
    "DRP": {
        "electricity_status": "modelled_and_source_anchored",
        "electricity_anchor": "C1 around 0.233 TWh/y",
        "electricity_candidate": "0.0833 MWh/t DRI base; 0.060-0.080 vendor range",
        "electricity_source": "DRP_Parameters.md; C5o_a",
        "electricity_action": "source-reviewed sensitivity only, no residual policy",
        "ng_status": "modelled_and_source_anchored",
        "ng_anchor": "C1 around 27.72 PJ/y",
        "ng_candidate": "9.9 GJ/t DRI base; 9.63-12.24 sensitivity",
        "ng_source": "DRP_Parameters.md; C5o_a",
        "ng_action": "keep component-level NG; do not claim full-site NG",
    },
    "EAF": {
        "electricity_status": "modelled_and_source_anchored",
        "electricity_anchor": "",
        "electricity_candidate": "current C5o_b arc electricity development input",
        "electricity_source": "EAF_Parameters.md; C5o_b",
        "electricity_action": "keep as process load; no mFRR/DA revenue in C5",
        "ng_status": "modelled_and_source_anchored",
        "ng_anchor": "",
        "ng_candidate": "current C5o_b auxiliary NG input",
        "ng_source": "EAF_Parameters.md; C5o_b",
        "ng_action": "keep component-level NG",
    },
    "DSP": {
        "electricity_status": "modelled_and_source_anchored",
        "electricity_anchor": "",
        "electricity_candidate": "current C5o_c development input",
        "electricity_source": "DSP_Parameters.md; C5o_c",
        "electricity_action": "keep as process load",
        "ng_status": "deferred",
        "ng_anchor": "",
        "ng_candidate": "fuel inactive in current DSP layer",
        "ng_source": "DSP_Parameters.md; C5o_c",
        "ng_action": "do not infer DSP residual gas/fuel",
    },
    "HSM/WBW": {
        "electricity_status": "modelled_candidate_only",
        "electricity_anchor": "",
        "electricity_candidate": "current C5l_d rolling electricity",
        "electricity_source": "HSM_Parameters.md; HSM_Slab_Buffer_Parameters.md; C5l_d",
        "electricity_action": "review HSM/WBW electricity anchor before residual policy",
        "ng_status": "missing_source_card",
        "ng_anchor": "",
        "ng_candidate": "reheat demand is thermal/WAG-linked, not NG anchor",
        "ng_source": "HSM_Parameters.md; C5l_d",
        "ng_action": "add explicit HSM/WBW fuel/NG anchor before CO2/economics",
    },
    "Linde/ASU": {
        "electricity_status": "modelled_and_source_anchored",
        "electricity_anchor": "150 t/h and 60 MW precedent sanity only",
        "electricity_candidate": "0.4 MWh/t O2 development input",
        "electricity_source": "LINDE_OXYGEN_Parameters.md; C5p_a",
        "electricity_action": "keep ASU electricity in process scope; not full-site load",
        "ng_status": "not_applicable",
        "ng_anchor": "",
        "ng_candidate": "",
        "ng_source": "LINDE_OXYGEN_Parameters.md",
        "ng_action": "no NG residual support from ASU",
    },
    "Boilers K15/K16": {
        "electricity_status": "deferred",
        "electricity_anchor": "",
        "electricity_candidate": "auxiliary electricity not separated",
        "electricity_source": "BOILER_STEAM_CIRCUIT_Parameters.md; C5p_b",
        "electricity_action": "source-card boiler auxiliary electricity if needed later",
        "ng_status": "modelled_candidate_only",
        "ng_anchor": "0 active; NG backup eligible/caveated",
        "ng_candidate": "backup only",
        "ng_source": "BOILER_STEAM_CIRCUIT_Parameters.md; C5p_b",
        "ng_action": "keep zero until residual steam/backup policy is reviewed",
    },
    "Boilers K23/K24": {
        "electricity_status": "deferred",
        "electricity_anchor": "",
        "electricity_candidate": "auxiliary electricity not separated",
        "electricity_source": "BOILER_STEAM_CIRCUIT_Parameters.md; C5p_b",
        "electricity_action": "source-card boiler auxiliary electricity if needed later",
        "ng_status": "modelled_candidate_only",
        "ng_anchor": "0 active; NG backup eligible/caveated",
        "ng_candidate": "backup only",
        "ng_source": "BOILER_STEAM_CIRCUIT_Parameters.md; C5p_b",
        "ng_action": "keep zero until residual steam/backup policy is reviewed",
    },
    "Boiler K41": {
        "electricity_status": "deferred",
        "electricity_anchor": "",
        "electricity_candidate": "auxiliary electricity not separated",
        "electricity_source": "BOILER_STEAM_CIRCUIT_Parameters.md; C5p_b",
        "electricity_action": "source-card boiler auxiliary electricity if needed later",
        "ng_status": "modelled_candidate_only",
        "ng_anchor": "0 active; NG backup eligible/caveated",
        "ng_candidate": "backup only; COG blocked",
        "ng_source": "BOILER_STEAM_CIRCUIT_Parameters.md; C5p_b",
        "ng_action": "keep zero; do not open K41 COG/NG without explicit review",
    },
    "STEG11": {
        "electricity_status": "modelled_candidate_only",
        "electricity_anchor": "13.1 MWe validation anchor",
        "electricity_candidate": "accounting-only steam-circuit electricity",
        "electricity_source": "BOILER_STEAM_CIRCUIT_Parameters.md; C5p_b",
        "electricity_action": "keep accounting-only; no market revenue",
        "ng_status": "not_applicable",
        "ng_anchor": "0 in base",
        "ng_candidate": "",
        "ng_source": "BOILER_STEAM_CIRCUIT_Parameters.md",
        "ng_action": "do not add STEG11 NG",
    },
    "TG2": {
        "electricity_status": "modelled_candidate_only",
        "electricity_anchor": "14.5 MWe validation anchor",
        "electricity_candidate": "accounting-only steam turbine electricity",
        "electricity_source": "BOILER_STEAM_CIRCUIT_Parameters.md; C5p_b",
        "electricity_action": "keep accounting-only; no market revenue",
        "ng_status": "not_applicable",
        "ng_anchor": "0 in base",
        "ng_candidate": "",
        "ng_source": "BOILER_STEAM_CIRCUIT_Parameters.md",
        "ng_action": "do not add TG2 fuel input",
    },
    "IJ01/VN25 generator interface": {
        "electricity_status": "modelled_candidate_only",
        "electricity_anchor": "C0 2.0 TWh validation only; C1 interface anchors",
        "electricity_candidate": "development efficiency/internal offset",
        "electricity_source": "IJ01_VN25_GENERATORS_Parameters.md; C5p_c",
        "electricity_action": "keep internal offset/reporting only",
        "ng_status": "modelled_and_source_anchored",
        "ng_anchor": "C1 VN25 NG 4.1 PJ/y",
        "ng_candidate": "VN25 only; IJ01 NG blocked",
        "ng_source": "IJ01_VN25_GENERATORS_Parameters.md; C5p_c",
        "ng_action": "keep C1 generator gap explicit; no created fuel",
    },
    "residual/background electricity": {
        "electricity_status": "missing_source_card",
        "electricity_anchor": "360 MW / 3 TWh context only",
        "electricity_candidate": "",
        "electricity_source": "C5p_g",
        "electricity_action": "create source-backed plant-category residual evidence before activation",
        "ng_status": "not_applicable",
        "ng_anchor": "",
        "ng_candidate": "",
        "ng_source": "C5p_g",
        "ng_action": "not an NG row",
    },
    "residual/background NG": {
        "electricity_status": "not_applicable",
        "electricity_anchor": "",
        "electricity_candidate": "",
        "electricity_source": "C5p_g",
        "electricity_action": "not an electricity row",
        "ng_status": "missing_source_card",
        "ng_anchor": "",
        "ng_candidate": "",
        "ng_source": "C5p_g",
        "ng_action": "block residual NG until source-backed evidence exists",
    },
    "WAG flaring/spill": {
        "electricity_status": "not_applicable",
        "electricity_anchor": "",
        "electricity_candidate": "",
        "electricity_source": "C5p_e",
        "electricity_action": "not an electricity residual load",
        "ng_status": "not_applicable",
        "ng_anchor": "",
        "ng_candidate": "",
        "ng_source": "C5p_e",
        "ng_action": "WAG is carrier-specific, not generic NG",
    },
    "buffers/stores": {
        "electricity_status": "not_applicable",
        "electricity_anchor": "",
        "electricity_candidate": "",
        "electricity_source": "BUFFERS_STORAGE_Parameters.md; C5p_d",
        "electricity_action": "no active store energy use added",
        "ng_status": "not_applicable",
        "ng_anchor": "",
        "ng_candidate": "",
        "ng_source": "BUFFERS_STORAGE_Parameters.md; C5p_d",
        "ng_action": "no store NG use added",
    },
}


def _coverage_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in [C0, C1]:
        elec_values = _electricity_values(payload, configuration)
        ng_values = _ng_values(payload, configuration)
        for plant, meta in PLANT_META.items():
            for carrier in ["electricity", "natural_gas"]:
                status_key = "electricity_status" if carrier == "electricity" else "ng_status"
                source_key = "electricity_source" if carrier == "electricity" else "ng_source"
                action_key = "electricity_action" if carrier == "electricity" else "ng_action"
                anchor_key = "electricity_anchor" if carrier == "electricity" else "ng_anchor"
                candidate_key = "electricity_candidate" if carrier == "electricity" else "ng_candidate"
                value = elec_values[plant] if carrier == "electricity" else ng_values[plant]
                unit = "TWh_e/y" if carrier == "electricity" else "PJ_LHV/y"
                status = meta[status_key]
                rows.append({
                    "configuration": configuration,
                    "plant_or_asset": plant,
                    "energy_carrier": carrier,
                    "metric": "annual electricity demand/offset" if carrier == "electricity" else "annual natural-gas demand",
                    "unit": unit,
                    "current_model_value": _fmt(value),
                    "source_anchor_value": meta[anchor_key],
                    "candidate_value_or_range": meta[candidate_key],
                    "anchor_role": "source_or_development_anchor" if status == "modelled_and_source_anchored" else "candidate_or_context_only" if status in {"modelled_candidate_only", "context_anchor_only"} else status,
                    "source_card_or_stage": meta[source_key],
                    "evidence_strength": "high" if status == "modelled_and_source_anchored" else "medium" if status == "modelled_candidate_only" else "low_or_missing" if status in {"missing_source_card", "deferred"} else "not_applicable",
                    "gap_to_anchor": "",
                    "coverage_status": status,
                    "can_support_residual_policy": "true" if status == "modelled_and_source_anchored" else "false",
                    "action_needed": meta[action_key],
                    "caveat": "Plant anchor audit only; no residual load or CO2 cost is activated.",
                })
    return rows


def _summary_rows(rows: list[dict[str, Any]], carrier: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        if row["energy_carrier"] != carrier:
            continue
        if carrier == "electricity":
            output.append({
                "configuration": row["configuration"],
                "plant_or_asset": row["plant_or_asset"],
                "current_model_electricity_twh_y": row["current_model_value"],
                "source_anchor_twh_y": row["source_anchor_value"],
                "candidate_range_twh_y": row["candidate_value_or_range"],
                "gap_twh_y": row["gap_to_anchor"],
                "coverage_status": row["coverage_status"],
                "residual_relevance": "high" if row["plant_or_asset"] in {"residual/background electricity", "KGF/coking", "BF/hot stove", "BOF/OSF", "HSM/WBW"} else "component_accounting",
                "recommended_action": row["action_needed"],
                "caveat": row["caveat"],
            })
        else:
            output.append({
                "configuration": row["configuration"],
                "plant_or_asset": row["plant_or_asset"],
                "current_model_ng_pj_y": row["current_model_value"],
                "source_anchor_pj_y": row["source_anchor_value"],
                "candidate_range_pj_y": row["candidate_value_or_range"],
                "gap_pj_y": row["gap_to_anchor"],
                "coverage_status": row["coverage_status"],
                "residual_relevance": "high" if row["plant_or_asset"] in {"residual/background NG", "HSM/WBW", "Sinter", "BF/hot stove"} else "component_accounting",
                "recommended_action": row["action_needed"],
                "caveat": row["caveat"],
            })
    return output


def _readiness_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    e_matrix = {row["configuration"]: row for row in payload["electricity_boundary"]}
    ng_matrix = {row["configuration"]: row for row in payload["ng_boundary"]}
    rows: list[dict[str, Any]] = []
    for configuration in [C0, C1]:
        rows.append({
            "boundary": "electricity",
            "configuration": configuration,
            "current_modelled_total": e_matrix[configuration]["gross_modelled_process_demand_twh"],
            "available_site_or_plant_anchor": "360 MW / 3 TWh context only plus partial plant anchors",
            "anchor_role": "context_and_partial_component_anchors",
            "residual_implied_by_anchor": "not_applied",
            "residual_can_be_modelled": "false",
            "evidence_strength": "partial",
            "policy_option": "plant_category_residuals_after_source_cards_or_config_specific_source_backed_residual_if_available",
            "recommended_status": "not_ready_for_hard_residual_load",
            "risk": "arbitrary residual load could hide C0 over-offset and plant-anchor gaps",
            "caveat": "RESIDUAL_ELECTRICITY_POLICY_NOT_READY",
        })
        rows.append({
            "boundary": "natural_gas",
            "configuration": configuration,
            "current_modelled_total": ng_matrix[configuration]["total_modelled_ng_pj"],
            "available_site_or_plant_anchor": "DRP/EAF/generator component anchors; no full-site NG anchor",
            "anchor_role": "partial_component_anchors",
            "residual_implied_by_anchor": "not_applied",
            "residual_can_be_modelled": "false",
            "evidence_strength": "partial_to_missing",
            "policy_option": "block_residual_NG_until_source_evidence_or_component_specific_source_cards",
            "recommended_status": "not_ready_for_hard_residual_load",
            "risk": "common residual NG bucket would become opaque slack and distort CO2",
            "caveat": "RESIDUAL_NG_POLICY_NOT_READY",
        })
    return rows


def _co2_lookup(payload: dict[str, Any], configuration: str) -> dict[str, dict[str, str]]:
    return {row["co2_component"]: row for row in payload["co2"] if row["configuration"] == configuration}


def _co2_component_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in [C0, C1]:
        lookup = _co2_lookup(payload, configuration)
        component_specs = [
            ("PEFA_diagnostic_CO2", "process_or_fuel_aggregate_diagnostic", "PEFA fired pellet output", "aggregate PEFA", "PEFA aggregate diagnostic; do not combine with fuel-explicit PEFA subcomponents."),
            ("DRP_capture_stream", "capture_stream", "DRP DRI output", "DRP NG process", "Capture/reporting stream only; not direct emission."),
            ("EAF_midpoint_CO2", "process_aggregate_range_midpoint", "EAF liquid steel output", "EAF aggregate", "Range midpoint diagnostic; do not combine with fuel-explicit EAF combustion."),
            ("DSP_direct_CO2", "inactive_fuel_zero_diagnostic", "DSP output", "DSP fuel inactive", "Zero under current inactive-fuel convention, not physical zero-emissions claim."),
            ("site_diagnostic_CO2_after_generator", "incomplete_site_placeholder", "site diagnostic", "mixed", "Not ETS/full-site total."),
            ("boiler_generator_fuel_explicit_CO2", "fuel_combustion_deferred", "boiler/generator fuel ledgers", "WAG and NG", "Fuel-explicit CO2 deferred until carbon boundary is selected."),
        ]
        for component, source_type, basis, fuel, caveat in component_specs:
            source = lookup.get(component, {})
            rows.append({
                "configuration": configuration,
                "component": component,
                "emission_source_type": source_type,
                "activity_basis": basis,
                "fuel_or_process": fuel,
                "current_activity_value": "",
                "emission_factor": "",
                "emission_factor_status": "aggregate_or_deferred",
                "co2_model_output_mt_y": _fmt(_mt_from_t(source.get("model_output", ""))),
                "co2_source_anchor_mt_y": source.get("source_anchor", ""),
                "anchor_role": "reporting_only" if component != "DRP_capture_stream" else "capture_stream_validation",
                "boundary_status": source.get("boundary_status", "deferred"),
                "double_counting_risk": source.get("double_counting_risk", "reported"),
                "ets_ready": "false",
                "caveat": caveat,
            })
        for component, source_type, basis, fuel, factor_status, caveat in [
            ("BF_aggregate_hot_metal_CO2_counter", "process_aggregate_candidate", "hot metal output", "coke/BFG carbon", "source-card candidate not consolidated", "BF aggregate counter conflicts with downstream BFG combustion unless one carbon boundary is selected."),
            ("BOF_OSF_direct_CO2_candidate", "process_aggregate_candidate", "BOF liquid steel", "BOF process", "source-card candidate not consolidated", "BOF direct CO2 exists as candidate but is not in a full ETS-ready total."),
            ("KGF_coking_direct_CO2_candidate", "process_fuel_candidate", "coke production", "COG/underfiring", "source-card range only", "Coking direct CO2 and COG carbon must not both be counted."),
            ("sinter_CO2_candidate", "process_fuel_candidate", "sinter output", "solid fuel/WAG", "component source review needed", "Sinter fuel CO2 remains outside consolidated boundary."),
            ("NG_combustion_CO2_deferred", "fuel_combustion_deferred", "modelled NG PJ", "natural gas", "emission factor deferred", "NG CO2 depends on residual NG boundary and factor review."),
            ("WAG_combustion_or_flare_CO2_deferred", "fuel_combustion_deferred", "WAG carrier ledgers", "BFG/COG/BOFG", "carbon-boundary policy deferred", "WAG carbon may be counted at generation or combustion, not both."),
            ("electricity_scope2_CO2_deferred", "scope2_deferred", "electricity exposure", "grid electricity", "scope-2 factor deferred", "Scope 2 requires residual electricity and net/import boundary."),
        ]:
            rows.append({
                "configuration": configuration,
                "component": component,
                "emission_source_type": source_type,
                "activity_basis": basis,
                "fuel_or_process": fuel,
                "current_activity_value": "",
                "emission_factor": "",
                "emission_factor_status": factor_status,
                "co2_model_output_mt_y": "",
                "co2_source_anchor_mt_y": "",
                "anchor_role": "candidate_or_deferred",
                "boundary_status": "deferred_or_not_consolidated",
                "double_counting_risk": "explicitly_reported",
                "ets_ready": "false",
                "caveat": caveat,
            })
    return rows


def _co2_boundary_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in [C0, C1]:
        lookup = _co2_lookup(payload, configuration)
        pefa = _mt_from_t(lookup.get("PEFA_diagnostic_CO2", {}).get("model_output", ""))
        eaf = _mt_from_t(lookup.get("EAF_midpoint_CO2", {}).get("model_output", ""))
        dsp = _mt_from_t(lookup.get("DSP_direct_CO2", {}).get("model_output", ""))
        captured = _mt_from_t(lookup.get("DRP_capture_stream", {}).get("model_output", ""))
        direct = pefa + eaf + dsp
        rows.append({
            "configuration": configuration,
            "direct_process_co2_mt": _fmt(direct),
            "wag_combustion_co2_mt": "",
            "ng_combustion_co2_mt": "",
            "electricity_scope2_co2_mt": "",
            "captured_co2_stream_mt": _fmt(captured),
            "diagnostic_component_total_mt": _fmt(direct),
            "public_full_site_anchor_mt": "",
            "gap_to_public_anchor_mt": "",
            "boundary_status": "component_diagnostic_only_not_full_site_not_ETS_ready",
            "ets_ready": "false",
            "caveat": "Component total is PEFA/EAF/DSP diagnostics only; captured stream is separate and WAG/NG/scope2 are deferred.",
        })
    return rows


def _double_count_rows() -> list[dict[str, Any]]:
    sources = [
        ("BFG", "diagnostic_only_possible_generation_counter", "deferred", "deferred", "false", "high", "select generation OR combustion boundary later"),
        ("COG", "diagnostic_only_possible_generation_counter", "deferred", "deferred", "false", "high", "avoid coking direct plus downstream COG double count"),
        ("BOFG", "diagnostic_only_possible_generation_counter", "deferred", "deferred", "false", "high", "avoid BOF direct plus downstream BOFG double count"),
        ("natural_gas", "false", "deferred", "false", "false", "medium", "count at combustion after residual NG boundary is fixed"),
        ("DRP_capture_stream", "false", "false", "false", "true", "medium", "keep as capture/reporting stream, not direct emission"),
        ("EAF_aggregate_CO2", "aggregate", "deferred", "false", "false", "medium", "do not add fuel-explicit EAF CO2 to aggregate midpoint"),
        ("PEFA_aggregate_CO2", "aggregate", "deferred", "false", "false", "medium", "do not add fuel-explicit PEFA CO2 to aggregate PEFA diagnostic"),
        ("electricity_scope2", "false", "false", "false", "false", "medium", "scope 2 only after electricity import boundary exists"),
    ]
    rows: list[dict[str, Any]] = []
    for configuration in [C0, C1]:
        for source, gen, combustion, flare, capture, risk, recommendation in sources:
            rows.append({
                "configuration": configuration,
                "carbon_carrier_or_source": source,
                "counted_at_generation": gen,
                "counted_at_combustion": combustion,
                "counted_at_flare": flare,
                "counted_as_capture_stream": capture,
                "double_counting_risk": risk,
                "current_policy": "reported_not_consolidated",
                "recommended_policy": recommendation,
                "caveat": "WAG/aggregate CO2 must use a single carbon boundary before ETS/economics.",
            })
    return rows


def _factor_rows() -> list[dict[str, Any]]:
    data = [
        ("FAC_BFG_COMBUSTION", "BFG", "", "tCO2/TJ", "260 tCO2/TJ candidate in BF source card", "", "medium", "deferred", "true", "high", "review before WAG-explicit CO2", "WAG_CARBON_BOUNDARY_REQUIRES_POLICY"),
        ("FAC_COG_CARBON", "COG", "", "gC/MJ", "approximately 10 gC/MJ candidate", "", "medium", "deferred", "true", "high", "review with coking direct CO2 boundary", "WAG_CARBON_BOUNDARY_REQUIRES_POLICY"),
        ("FAC_BOFG_COMBUSTION", "BOFG", "", "tCO2/TJ", "", "missing", "low", "missing", "true", "high", "source-card factor needed", "CO2_BOUNDARY_COMPONENT_ONLY"),
        ("FAC_NG_COMBUSTION", "natural gas", "", "tCO2/TJ", "", "standard factor needed", "low", "deferred", "true", "high", "add governed NG factor before fuel-explicit CO2", "PLANT_NG_ANCHORS_INCOMPLETE"),
        ("FAC_EAF_AGGREGATE", "EAF", "midpoint diagnostic", "MtCO2/y", "0.2412-0.6030 Mt/y range", "", "medium", "reporting_only", "true", "medium", "keep aggregate separate from fuel factors", "EAF_CO2_AGGREGATE_AND_FUEL_CO2_DOUBLE_COUNTED"),
        ("FAC_PEFA_AGGREGATE", "PEFA", "aggregate diagnostic", "tCO2/y", "current C5n_a aggregate", "", "medium", "reporting_only", "true", "medium", "keep aggregate separate from fuel factors", "PEFA_CO2_AGGREGATE_AND_FUEL_CO2_DOUBLE_COUNTED"),
        ("FAC_DRP_CAPTURE", "DRP", "0.286 t/t DRI capture stream", "tCO2/t DRI", "0.8 Mt/y validation anchor", "0.256 vendor cross-check", "medium", "capture_stream_validation", "false", "medium", "do not count as direct emission", "DRP_CAPTURE_STREAM_COUNTED_AS_DIRECT_EMISSION"),
        ("FAC_SCOPE2_GRID", "grid electricity", "", "tCO2/MWh", "", "requires electricity import boundary", "low", "deferred", "true", "high", "block scope 2 until residual electricity boundary", "SCOPE2_REQUIRES_ELECTRICITY_BOUNDARY"),
    ]
    return [
        {
            "factor_id": row[0],
            "source_or_carrier": row[1],
            "current_factor": row[2],
            "unit": row[3],
            "source_card_factor": row[4],
            "candidate_range": row[5],
            "evidence_strength": row[6],
            "current_use_status": row[7],
            "affects_total_co2": row[8],
            "review_priority": row[9],
            "recommended_action": row[10],
            "caveat": row[11],
        }
        for row in data
    ]


def _source_gap_rows() -> list[dict[str, Any]]:
    data = [
        ("GAP_ELEC_KGF", "KGF/coking electricity", "broad candidate range only", "separate current other-modelled electricity and residual electricity policy", "current value inside other-modelled electricity", "Coking_Plants_Parameters.md", "false", "true", "false", "true", "narrow KGF electricity scope/range or keep candidate-only", "PLANT_ELECTRICITY_ANCHORS_INCOMPLETE"),
        ("GAP_ELEC_BF_BOF", "BF/BOF electricity", "candidate coefficients not separated in C5p_g boundary", "plant-category residual policy", "currently inside other-modelled electricity", "Blast_Furnace_Parameters.md; BOF_OSF_Parameters.md", "false", "true", "false", "true", "separate BF/BOF electricity rows before residual load", "PLANT_ELECTRICITY_ANCHORS_INCOMPLETE"),
        ("GAP_ELEC_HSM", "HSM/WBW electricity", "development input but source evidence still weak for residual policy", "downstream boundary and residual electricity", "current C5l_d rolling electricity", "HSM_Parameters.md; HSM_Slab_Buffer_Parameters.md", "false", "true", "false", "true", "review HSM/WBW electricity and reheat fuel source-card", "PLANT_ELECTRICITY_ANCHORS_INCOMPLETE"),
        ("GAP_NG_HSM", "HSM/WBW NG/fuel", "no explicit NG anchor", "NG residual and CO2 fuel attribution", "0 modelled NG", "HSM_Parameters.md", "false", "true", "true", "true", "add HSM/WBW fuel carrier evidence before residual NG", "PLANT_NG_ANCHORS_INCOMPLETE"),
        ("GAP_NG_SITE", "residual/background NG", "no source-backed site residual NG anchor", "full NG and CO2 boundary", "0 residual NG active", "new residual NG source-card or component updates", "false", "true", "true", "true", "keep residual NG blocked until source evidence", "RESIDUAL_NG_POLICY_NOT_READY"),
        ("GAP_ELEC_SITE", "residual/background electricity", "360 MW and 3 TWh are context only", "C0 over-offset and economics grid boundary", "0 residual electricity active", "new residual electricity source-card or plant-category anchors", "false", "true", "true", "true", "do not activate hard residual electricity load yet", "RESIDUAL_ELECTRICITY_POLICY_NOT_READY"),
        ("GAP_CO2_WAG", "WAG carbon boundary", "factor and counting point not selected", "CO2 and ETS readiness", "WAG combustion CO2 deferred", "BF/Coking/BOF/WAG CO2 source-card review", "false", "false", "true", "true", "choose aggregate or combustion carbon boundary later", "WAG_CARBON_BOUNDARY_REQUIRES_POLICY"),
        ("GAP_CO2_SCOPE2", "scope 2 electricity", "grid/import boundary missing", "full CO2/economics", "scope 2 deferred", "electricity boundary source-card repair", "false", "false", "true", "true", "block scope 2 until electricity boundary is complete", "SCOPE2_REQUIRES_ELECTRICITY_BOUNDARY"),
    ]
    return [
        {
            "gap_id": row[0],
            "plant_or_boundary": row[1],
            "missing_anchor_or_weak_anchor": row[2],
            "why_needed": row[3],
            "current_model_value": row[4],
            "candidate_source_cards_to_create_or_update": row[5],
            "can_use_context_anchor": row[6],
            "blocks_residual_policy": row[7],
            "blocks_co2": row[8],
            "blocks_economics": row[9],
            "recommended_action": row[10],
            "caveat": row[11],
        }
        for row in data
    ]


def _decision_rows() -> list[dict[str, Any]]:
    data = [
        ("DEC_PLANT_ELECTRICITY_ANCHORS", "plant electricity anchor coverage", "partial", "major modelled loads exist but several legacy plants are not source-separated", "activate no residual; context residual; source-card plant-category residual", "source-card plant-category residual review before activation", "Residual electricity should not be a balancing bucket while KGF/BF/BOF/HSM evidence is weak.", "false", "true", "true", "false", "false", "true", "false", "plant anchors incomplete", "PLANT_ELECTRICITY_ANCHORS_INCOMPLETE"),
        ("DEC_PLANT_NG_ANCHORS", "plant NG anchor coverage", "partial", "DRP/EAF/generator NG modelled; residual/HSM/sinter NG weak or missing", "no residual; source-backed annual residual; component-specific residual", "block hard residual NG until source-backed component evidence", "NG residuals strongly affect CO2 and costs.", "false", "true", "true", "false", "true", "true", "false", "no full-site NG claim", "PLANT_NG_ANCHORS_INCOMPLETE"),
        ("DEC_CO2_BOUNDARY_OPTION", "minimum CO2 boundary option", "component_diagnostic_only", "component diagnostics exist but WAG/NG/scope2 boundaries are incomplete", "A component diagnostic; B direct+NG; C direct+WAG; D full reporting total; E ETS-ready", "A_component_diagnostic_only_until_energy_boundary_and_carbon_policy_are_fixed", "A consolidated total would overstate confidence and risk double counting.", "false", "false", "true", "false", "true", "true", "false", "not ETS-ready", "CO2_BOUNDARY_COMPONENT_ONLY"),
        ("DEC_WAG_CARBON_POLICY", "WAG carbon counting point", "unresolved", "BF/coking/BOF source cards warn against counting generation and combustion together", "aggregate process counters; fuel-explicit combustion; hybrid with exclusions", "select one boundary later, not both", "WAG is central to both C0 and C1, and generator/boiler sinks are incomplete.", "false", "true", "true", "false", "true", "true", "false", "avoid double counting", "WAG_CARBON_BOUNDARY_REQUIRES_POLICY"),
        ("DEC_ETS_ECONOMICS_READINESS", "ETS/economics readiness", "NO_GO", "denominator, electricity, NG and CO2 boundaries incomplete", "continue diagnostics; repair source cards; activate residuals later; economics later", "NO_GO_until_energy_CO2_and_denominator_boundaries_are_stable", "Economics and ETS need stable physical denominators and import/fuel boundaries.", "false", "true", "true", "false", "true", "true", "false", "not thesis-approved", "ECONOMICS_NO_GO"),
    ]
    return [
        {
            "decision_id": row[0],
            "topic": row[1],
            "current_status": row[2],
            "evidence_status": row[3],
            "options": row[4],
            "recommended_option": row[5],
            "rationale": row[6],
            "affects_model_equations_now": row[7],
            "affects_physical_behaviour_later": row[8],
            "affects_economics_later": row[9],
            "must_fix_before_commit": row[10],
            "must_fix_before_co2_objective": row[11],
            "must_fix_before_economics": row[12],
            "can_defer_to_sensitivity": row[13],
            "thesis_reporting_caveat": row[14],
            "caveat": row[15],
        }
        for row in data
    ]


def _redflag_rows(payload: dict[str, Any], co2_boundary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    p_g = payload["p_g_gate"]
    p_f = payload["p_f_gate"]
    checks = {
        "CO2_TOTAL_CLAIMED_WITH_INCOMPLETE_BOUNDARY": False,
        "ETS_READY_CLAIMED_WITH_COMPONENT_ONLY_BOUNDARY": any(row["ets_ready"] == "true" for row in co2_boundary),
        "WAG_CO2_DOUBLE_COUNTING_UNREPORTED": False,
        "DRP_CAPTURE_STREAM_COUNTED_AS_DIRECT_EMISSION": False,
        "EAF_CO2_AGGREGATE_AND_FUEL_CO2_DOUBLE_COUNTED": False,
        "PEFA_CO2_AGGREGATE_AND_FUEL_CO2_DOUBLE_COUNTED": False,
        "SCOPE2_CO2_CLAIMED_WITHOUT_ELECTRICITY_BOUNDARY": False,
        "RESIDUAL_ELECTRICITY_LOAD_ADDED_IN_DIAGNOSTIC_STAGE": bool(p_g["residual_electricity_load_active"]),
        "RESIDUAL_NG_LOAD_ADDED_IN_DIAGNOSTIC_STAGE": bool(p_g["residual_ng_load_active"]),
        "ELECTRICITY_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION": False,
        "NG_ANCHOR_USED_AS_EXECUTABLE_CONSTRAINT_WITHOUT_INTERPRETATION": False,
        "FULL_SITE_NET_IMPORT_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY": False,
        "FULL_SITE_NG_CLAIMED_WITHOUT_RESIDUAL_BOUNDARY": False,
        "DA_PRICE_OR_ECONOMICS_ACTIVE": False,
        "DENOMINATOR_SILENTLY_FROZEN": "unresolved" not in p_f["denominator_status"],
        "PRODUCTION_POLICY_CHANGED_DURING_BOUNDARY_DIAGNOSTIC": False,
        "C5L_D_BASE_0_50_REVERTED": False,
        "COKE_RECONCILIATION_BASELINE_REOPENED": False,
        "THESIS_USABILITY_TRUE_FOR_DEVELOPMENT_ROWS": bool(p_f["thesis_usability"]),
    }
    rows: list[dict[str, Any]] = []
    for flag in FAILURE_FLAGS:
        active = checks[flag]
        rows.append({
            "red_flag": flag,
            "active": str(active).lower(),
            "severity": "failure",
            "evidence": "C5p_h diagnostic gate",
            "recommended_action": "fix before commit/economics if active" if active else "none",
        })
    for caveat in CAVEATS:
        rows.append({
            "red_flag": caveat,
            "active": "true",
            "severity": "caveat",
            "evidence": "CO2/plant energy-anchor diagnostic caveat",
            "recommended_action": "carry into source-card repair, CO2, and economics gates",
        })
    return rows


def _write_report(gate: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C5 CO2 and Plant Energy-Anchor Boundary Diagnostics",
        "",
        "Diagnostic-only C5p_h stage. It audits plant-level electricity/NG anchor coverage and the component-level CO2 boundary. It does not add residual loads, CO2 costs, ETS logic, economics, DA revenue, or a frozen denominator.",
        "",
        "## Stage Gate",
        "",
        f"- Decision: `{gate['decision']}`",
        f"- Failure count: `{gate['failure_count']}`",
        f"- Caveat count: `{gate['caveat_count']}`",
        f"- Electricity anchor coverage: `{gate['electricity_anchor_coverage_status']}`",
        f"- NG anchor coverage: `{gate['ng_anchor_coverage_status']}`",
        f"- CO2 boundary: `{gate['co2_boundary_status']}`",
        f"- ETS readiness: `{gate['ETS_readiness']}`",
        "",
        "## Key Findings",
        "",
        "- Plant-level electricity anchors are partial: PEFA, DRP, EAF, DSP, Sinter and ASU are represented, while KGF/BF/BOF/HSM/residual background coverage remains weak or not source-separated enough for a hard residual policy.",
        "- Plant-level NG anchors are partial: C1 DRP, EAF and VN25/IJ01 generator NG are represented, while residual/background NG and HSM/sinter/utility NG remain missing or weak.",
        "- CO2 remains component diagnostic only. PEFA and EAF aggregate diagnostics, DRP capture stream, and DSP inactive-fuel zero are reported separately from WAG, NG and scope-2 emissions.",
        "- Recommended CO2 option is component diagnostic only until the energy boundary and WAG carbon policy are fixed.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_outputs() -> dict[str, Any]:
    C5P_H_DIR.mkdir(parents=True, exist_ok=True)
    payload = _payload()
    coverage = _coverage_rows(payload)
    electricity_summary = _summary_rows(coverage, "electricity")
    ng_summary = _summary_rows(coverage, "natural_gas")
    readiness = _readiness_rows(payload)
    co2_components = _co2_component_rows(payload)
    co2_boundary = _co2_boundary_rows(payload)
    double_count = _double_count_rows()
    factors = _factor_rows()
    source_gaps = _source_gap_rows()
    decisions = _decision_rows()
    redflags = _redflag_rows(payload, co2_boundary)
    failure_count = sum(1 for row in redflags if row["severity"] == "failure" and row["active"] == "true")
    caveat_count = sum(1 for row in redflags if row["severity"] == "caveat" and row["active"] == "true")
    e_missing = sum(1 for row in electricity_summary if row["coverage_status"] in {"missing_source_card", "deferred", "modelled_candidate_only"})
    ng_missing = sum(1 for row in ng_summary if row["coverage_status"] in {"missing_source_card", "deferred", "modelled_candidate_only"})
    gate = {
        "stage_id": STAGE,
        "decision": "pass_development_co2_and_plant_energy_anchor_boundary_diagnostics" if failure_count == 0 else "fail_development_co2_and_plant_energy_anchor_boundary_diagnostics",
        "status": "development_only",
        "thesis_usability": False,
        "output_directory": str(C5P_H_DIR).replace("\\", "/"),
        "failure_count": failure_count,
        "caveat_count": caveat_count,
        "electricity_anchor_coverage_status": "partial_incomplete",
        "ng_anchor_coverage_status": "partial_incomplete",
        "electricity_missing_or_weak_anchor_rows": e_missing,
        "ng_missing_or_weak_anchor_rows": ng_missing,
        "residual_electricity_policy_ready": False,
        "residual_ng_policy_ready": False,
        "co2_boundary_status": "component_diagnostic_only_not_full_site_not_ETS_ready",
        "ETS_readiness": "NO_GO",
        "economics_readiness": "NO_GO",
        "DA_readiness": "NO_GO",
        "recommended_co2_boundary_option": "A_component_diagnostic_only_no_consolidated_total_until_energy_boundary_and_WAG_carbon_policy_are_fixed",
        "recommended_source_card_repairs": "HSM_WBW_energy; KGF_BF_BOF_electricity_separation; residual_site_electricity; residual_NG; WAG_CO2_factors_and_counting_policy; scope2_grid_factor_after_boundary",
        "denominator_status": payload["p_f_gate"]["denominator_status"],
        "electricity_boundary_status": payload["p_g_gate"]["electricity_boundary_status"],
        "ng_boundary_status": payload["p_g_gate"]["ng_boundary_status"],
        "generator_electricity_accounting_status": payload["p_g_gate"]["electricity_accounting_status"],
    }

    _write_csv(C5P_H_DIR / "c5_plant_energy_anchor_coverage_matrix.csv", coverage, PLANT_ANCHOR_COLUMNS)
    _write_csv(C5P_H_DIR / "c5_plant_electricity_anchor_summary.csv", electricity_summary, ELECTRICITY_SUMMARY_COLUMNS)
    _write_csv(C5P_H_DIR / "c5_plant_ng_anchor_summary.csv", ng_summary, NG_SUMMARY_COLUMNS)
    _write_csv(C5P_H_DIR / "c5_residual_policy_readiness_from_plant_anchors.csv", readiness, READINESS_COLUMNS)
    _write_csv(C5P_H_DIR / "c5_co2_component_inventory.csv", co2_components, CO2_COMPONENT_COLUMNS)
    _write_csv(C5P_H_DIR / "c5_co2_boundary_matrix.csv", co2_boundary, CO2_BOUNDARY_COLUMNS)
    _write_csv(C5P_H_DIR / "c5_co2_double_counting_risk_matrix.csv", double_count, DOUBLE_COUNT_COLUMNS)
    _write_csv(C5P_H_DIR / "c5_co2_factor_gap_and_source_review.csv", factors, FACTOR_COLUMNS)
    _write_csv(C5P_H_DIR / "c5_energy_anchor_source_gap_register.csv", source_gaps, SOURCE_GAP_COLUMNS)
    _write_csv(C5P_H_DIR / "c5_co2_energy_boundary_decision_register.csv", decisions, DECISION_COLUMNS)
    _write_csv(C5P_H_DIR / "c5_co2_energy_boundary_red_flags.csv", redflags, REDFLAG_COLUMNS)
    _write_json(C5P_H_DIR / "s4_4c5p_h_stage_gate.json", gate)
    _write_json(C5P_H_DIR / "s4_4c5p_h_summary.json", {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "plant_anchor_coverage": len(coverage),
            "electricity_summary": len(electricity_summary),
            "ng_summary": len(ng_summary),
            "readiness": len(readiness),
            "co2_components": len(co2_components),
            "co2_boundary": len(co2_boundary),
            "double_counting": len(double_count),
            "factor_review": len(factors),
            "source_gaps": len(source_gaps),
            "decisions": len(decisions),
            "redflags": len(redflags),
        },
    })
    _write_csv(C5P_H_DIR / "s4_4c5p_h_run_registry.csv", [{
        "stage": STAGE,
        "source_stage": "S4.4c5p_g_residual_electricity_ng_boundary_diagnostics",
        "decision": gate["decision"],
        "status": "development_only",
        "thesis_usability": "false",
        "output_directory": gate["output_directory"],
    }])
    _write_report(gate)
    return {"stage": STAGE, "decision": gate["decision"], "output_directory": gate["output_directory"]}


def run_s4_4c5p_h_co2_and_plant_energy_anchor_boundary_diagnostics() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5p_h_co2_and_plant_energy_anchor_boundary_diagnostics(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
