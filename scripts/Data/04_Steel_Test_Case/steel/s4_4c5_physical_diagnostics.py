"""S4.4c5 physical diagnostics and calibration-readiness reports."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from .s4_4b_unified_input_validator import validate_unified_dev_inputs
from .s4_4b5a_asymmetric_correction import CORRECTED_INPUT_DIR
from .s4_4c4c_full_wag_static_regression import (
    C0,
    C1,
    C4C_DIR,
    TOLERANCE,
    _analytics,
    _co2_flaring_summary,
    _daily_summary,
    _electricity_summary,
    _max_balance_residual,
    _ng_steam_summary,
    _read_csv,
    _read_json,
    _report_rows,
    _safe_float,
    _wag_by_carrier,
    _wag_by_sink,
    _write_csv,
    _write_json,
)
from .s4_4c_unified_physical_modelbuilder import (
    BOILER_TOTAL_PLACEHOLDER_MWH_H,
    BOILER_WAG_PLACEHOLDER_CAP_MWH_H,
    C1_EMISSIONS_PROXY_RETAINED_BFBOF_SHARE,
    C1_RETAINED_BFBOF_TARGET_SHARE,
    FLARING_CO2_DIAGNOSTIC_EUR_PER_T,
    VATTENFALL_IJM01_WAG_CAP_NM3_H,
    VATTENFALL_TOTAL_WAG_CAP_NM3_H,
    VATTENFALL_VELSEN25_WAG_CAP_NM3_H,
    _build_c0_inputs,
    _build_c1_inputs,
    _load_tables,
    run_s44c_unified_physical_regression,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
S4_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4"
C5_DIR = S4_ROOT / "s4_4c5_full_scope_physical_diagnostics"
SOURCE_REGISTER = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_evidence/steel_source_card_register.csv"
CANDIDATE_REGISTER = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_evidence/steel_candidate_parameter_evidence_register.csv"

FULL_SITE_PRODUCT_ANCHOR_T_Y = 7_200_000.0
PJ_TO_MWH = 277_777.77777777775
ANCHORS = {
    "C0_gross_electricity": {
        "annual_value": 11.0 * PJ_TO_MWH,
        "unit": "MWh/y",
        "basis": "11 PJ/y full-site electricity validation candidate",
        "source": "assumption_register:S4_ECON_ELEC_REF_TOTAL_11_PJY_VALIDATION",
        "basis_warning": "11 PJ/y equals 348.8 MW average; user context says around 360-375 MW.",
    },
    "C1_gross_electricity": {
        "annual_value": 16.0 * PJ_TO_MWH,
        "unit": "MWh/y",
        "basis": "16 PJ/y C1 electricity validation candidate",
        "source": "assumption_register:S4_ECON_ELEC_C1_TOTAL_16_PJY_VALIDATION",
        "basis_warning": "16 PJ/y equals 507.4 MW average; user context says around 565-580 MW.",
    },
    "C1_wag_internal_electricity": {
        "annual_value": 6.0 * PJ_TO_MWH,
        "unit": "MWh/y",
        "basis": "6 PJ/y internal/Vattenfall generation validation context",
        "source": "candidate_register:S4_ECON_ELEC_C1_INTERNAL_GENERATION_6_PJY_VALIDATION",
        "basis_warning": "Validation context only, not dispatch truth.",
    },
    "C0_wag_reuse": {
        "annual_value": 54.0 * PJ_TO_MWH,
        "unit": "MWh_LHV/y",
        "basis": "54 PJ/y C0 WAG/electricity/steam reuse validation context",
        "source": "candidate_register:S4_ECON_WAG_REUSE_54_PJY_VALIDATION",
        "basis_warning": "Validation context only; not all reuse destinations are represented.",
    },
    "boiler_steam_placeholder": {
        "annual_value": 6.0 * PJ_TO_MWH,
        "unit": "MWh_LHV/y",
        "basis": "6 PJ/y aggregate boiler/steam placeholder",
        "source": "S3.3j/S4.4 development placeholder",
        "basis_warning": "Flat placeholder, not measured hourly steam demand.",
    },
    "CH4_HHV": {
        "annual_value": 292_000_000.0,
        "unit": "Nm3/y",
        "basis": "11.4% of 102 PJ = 11.628 PJ/y HHV, about 292 million Nm3/y",
        "source": "user_supplied_validation_candidate",
        "basis_warning": "HHV natural gas accounting; do not mix with LHV WAG balances.",
    },
}


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _sum(rows: list[dict[str, Any]], field: str) -> float:
    return sum(_safe_float(row.get(field)) for row in rows)


def _by_config(hourly_rows: list[dict[str, Any]], config_id: str) -> list[dict[str, Any]]:
    return [row for row in hourly_rows if row.get("configuration_id") == config_id]


def _production_scale(final_product_t: float, horizon_hours: int) -> float:
    annualised_product = final_product_t * 8760.0 / horizon_hours
    return annualised_product / FULL_SITE_PRODUCT_ANCHOR_T_Y if FULL_SITE_PRODUCT_ANCHOR_T_Y else 0.0


def _phase1_source_summary() -> dict[str, Any]:
    candidate_rows = _read_rows(CANDIDATE_REGISTER)
    source_rows = _read_rows(SOURCE_REGISTER)
    terms = ("WAG", "BFG", "COG", "BOFG", "steam", "Vattenfall", "electric", "CH4", "gas")
    matched_candidates = [
        row for row in candidate_rows if any(term.lower() in json.dumps(row, sort_keys=True).lower() for term in terms)
    ]
    matched_sources = [
        row for row in source_rows if any(term.lower() in json.dumps(row, sort_keys=True).lower() for term in terms)
    ]
    return {
        "candidate_register_rows_targeted": len(matched_candidates),
        "source_card_rows_targeted": len(matched_sources),
        "candidate_register_path": str(CANDIDATE_REGISTER.relative_to(REPO_ROOT)),
        "source_register_path": str(SOURCE_REGISTER.relative_to(REPO_ROOT)),
    }


def run_phase1_audit() -> dict[str, Any]:
    C5_DIR.mkdir(parents=True, exist_ok=True)
    validation = validate_unified_dev_inputs(CORRECTED_INPUT_DIR.resolve())
    c4c_gate = _read_json(C4C_DIR / "s4_4c4c_168h_stage_gate.json")
    c4c_c0_rows = _read_rows(C4C_DIR / "s4_4c4c_168h_hourly_dispatch_c0.csv")
    c4c_c1_rows = _read_rows(C4C_DIR / "s4_4c4c_168h_hourly_dispatch_c1.csv")

    c0_cp2_reported = any("C0_KGF2_input_t_h" in row for row in c4c_c0_rows)
    c0_cp2_total = _sum(c4c_c0_rows, "C0_KGF2_input_t_h") if c0_cp2_reported else ""
    c1_retained_bf6_total = _sum(c4c_c1_rows, "C1_retained_BF6_sinter_input_t_h")
    c1_kgf2_total = _sum(c4c_c1_rows, "C1_KGF2_activity_t_h")
    c1_bf7_total = _sum(c4c_c1_rows, "C1_BF7_activity_t_h")

    audit_rows = [
        {
            "audit_item": "C0_active_plants",
            "status": "C0 topology includes KGF1/KGF2, sinter, BF6/BF7, BOF, HSM",
            "current_c4c_observation": "C4C hourly output did not expose KGF1/KGF2 split"
            if not c0_cp2_reported
            else f"C0 KGF2 total={c0_cp2_total}",
            "c5_action": "C5 output exposes KGF1/KGF2 split and activates CP2 in the WAG-compatible fixed schedule.",
        },
        {
            "audit_item": "C1_retained_route",
            "status": "active" if c1_retained_bf6_total > TOLERANCE else "not_active",
            "current_c4c_observation": f"BF6 retained route sinter input total={round(c1_retained_bf6_total, 6)}",
            "c5_action": "C5 replaces route-share equality with bottom-up fixed retained process rates.",
        },
        {
            "audit_item": "C1_closure_default",
            "status": "valid" if c1_kgf2_total <= TOLERANCE and c1_bf7_total <= TOLERANCE else "invalid",
            "current_c4c_observation": f"KGF2 total={round(c1_kgf2_total, 6)}, BF7 total={round(c1_bf7_total, 6)}",
            "c5_action": "BF7 and KGF2 remain inactive in C1.",
        },
        {
            "audit_item": "Vattenfall_WAG_cap",
            "status": "combined_volume_cap",
            "current_c4c_observation": "BFG_volume + COG_volume + BOFG_volume <= total cap",
            "Velsen_25_Nm3_h": VATTENFALL_VELSEN25_WAG_CAP_NM3_H,
            "IJmuiden_01_Nm3_h": VATTENFALL_IJM01_WAG_CAP_NM3_H,
            "total_Nm3_h": VATTENFALL_TOTAL_WAG_CAP_NM3_H,
            "c5_action": "Do not apply 900000 Nm3/h separately to each carrier.",
        },
        {
            "audit_item": "schedule_status",
            "status": "fixed_development_schedules",
            "current_c4c_observation": "C0 and C1 use deterministic fixed binary schedules.",
            "c5_action": "Fixed schedules remain labelled as development diagnostics.",
        },
        {
            "audit_item": "source_registers",
            "status": "targeted_inventory",
            "current_c4c_observation": json.dumps(_phase1_source_summary(), sort_keys=True),
            "c5_action": "No raw PDFs inspected.",
        },
    ]
    decision = "pass_to_phase2_bottom_up_24h"
    if validation["failure_count"] != 0:
        decision = "blocked_c5_input_validation_failed"
    elif c4c_gate.get("decision") not in {
        "pass_168h_static_physical_with_full_wag_caveats",
        "pass_168h_static_physical_with_minimal_wag_layer",
    }:
        decision = "blocked_c4c_prerequisite_missing"
    elif c1_kgf2_total > TOLERANCE or c1_bf7_total > TOLERANCE:
        decision = "blocked_c1_closure_invalid"

    gate = {
        "stage": "S4.4c5_phase1_structure_audit",
        "decision": decision,
        "validator_failure_count": validation["failure_count"],
        "current_c4c_168h_gate": c4c_gate.get("decision", "missing"),
        "c0_cp2_explicitly_reported_in_c4c_hourly": c0_cp2_reported,
        "c1_retained_route_active_in_c4c": c1_retained_bf6_total > TOLERANCE,
        "c1_bf7_inactive": c1_bf7_total <= TOLERANCE,
        "c1_kgf2_inactive": c1_kgf2_total <= TOLERANCE,
        "vattenfall_cap_policy": "combined_volume_cap",
        "raw_pdf_inspected": False,
        "thesis_usable": False,
        "caveat": "C4C is accepted as prerequisite context only; C5 reruns with explicit C0 CP2 split and bottom-up C1 retained route.",
    }
    _write_csv(C5_DIR / "s4_4c5_phase1_structure_audit.csv", audit_rows)
    _write_json(C5_DIR / "s4_4c5_phase1_structure_audit.json", {"gate": gate, "rows": audit_rows})
    _write_json(C5_DIR / "s4_4c5_phase1_stage_gate.json", gate)
    _write_csv(C5_DIR / "s4_4c5_phase1_stage_gate.csv", [gate])
    return gate


def _route_split_rows(audits: list[dict[str, Any]], horizon: str) -> list[dict[str, Any]]:
    rows = []
    for audit in audits:
        target = _safe_float(audit.get("final_product_target_t"))
        retained = _safe_float(audit.get("retained_bf_bof_final_product_t"))
        eaf = _safe_float(audit.get("eaf_final_product_t"))
        rows.append(
            {
                "horizon": horizon,
                "configuration_id": audit["configuration_id"],
                "final_product_target_t": target,
                "retained_bf_bof_final_product_t": retained if audit["configuration_id"] == C1 else "",
                "drp_eaf_final_product_t": eaf if audit["configuration_id"] == C1 else "",
                "retained_route_share": round(retained / target, 9) if target and audit["configuration_id"] == C1 else "",
                "drp_eaf_route_share": round(eaf / target, 9) if target and audit["configuration_id"] == C1 else "",
                "policy": "bottom_up_fixed_retained_route" if audit["configuration_id"] == C1 else "C0_reference_route",
                "emissions_proxy_share_reference": C1_EMISSIONS_PROXY_RETAINED_BFBOF_SHARE if audit["configuration_id"] == C1 else "",
                "prior_top_down_share_reference": C1_RETAINED_BFBOF_TARGET_SHARE if audit["configuration_id"] == C1 else "",
                "caveat": "Retained route volume is implied by fixed process rates; DRP/EAF fills remaining target."
                if audit["configuration_id"] == C1
                else "C0 reference route; CP1 and CP2 both exposed in C5 plant diagnostics.",
            }
        )
    return rows


def _plant_rows(hourly_rows: list[dict[str, Any]], horizon: str) -> list[dict[str, Any]]:
    tables = _load_tables(CORRECTED_INPUT_DIR)
    c0_inputs = _build_c0_inputs(tables, horizon_hours_override=24)
    c1_inputs = _build_c1_inputs(tables, horizon_hours_override=24, include_retained_bf_bof=True)
    retained = c1_inputs.retained_bf_bof
    assert retained is not None
    rows: list[dict[str, Any]] = []

    def add(
        source_row: dict[str, Any],
        *,
        plant_id: str,
        activity: float,
        on_state: float | str,
        material_input: float,
        material_output: float,
        electricity: float | str = "",
        natural_gas_nm3: float | str = "",
        oxygen_t: float | str = "",
        steam_boiler_mwh: float | str = "",
        bfg_generated: float = 0.0,
        cog_generated: float = 0.0,
        bofg_generated: float = 0.0,
        bfg_consumed: float = 0.0,
        cog_consumed: float = 0.0,
        bofg_consumed: float = 0.0,
        wag_to_electricity: float = 0.0,
        bfg_flared: float = 0.0,
        cog_flared: float = 0.0,
        bofg_flared: float = 0.0,
        process_co2_t: float | str = "",
        combustion_co2_t: float | str = "",
        capacity_upper: float | None = None,
        schedule_status: str = "fixed_development_schedule",
        caveat: str = "",
    ) -> None:
        bfg_flare_co2 = (
            _safe_float(source_row.get("BFG_flare_co2_t"))
            * (bfg_flared / max(_safe_float(source_row.get("BFG_flared_mwh")), TOLERANCE))
            if bfg_flared
            else 0.0
        )
        cog_flare_co2 = (
            _safe_float(source_row.get("COG_flare_co2_t"))
            * (cog_flared / max(_safe_float(source_row.get("COG_flared_mwh")), TOLERANCE))
            if cog_flared
            else 0.0
        )
        bofg_flare_co2 = (
            _safe_float(source_row.get("BOFG_flare_co2_t"))
            * (bofg_flared / max(_safe_float(source_row.get("BOFG_flared_mwh")), TOLERANCE))
            if bofg_flared
            else 0.0
        )
        rows.append(
            {
                "horizon": horizon,
                "hour_index": source_row["hour_index"],
                "configuration_id": source_row["configuration_id"],
                "plant_id": plant_id,
                "activity_or_on_state": on_state,
                "activity_t_h": round(activity, 6),
                "material_input_t": round(material_input, 6),
                "material_output_t": round(material_output, 6),
                "electricity_use_mwh": electricity,
                "natural_gas_use_nm3": natural_gas_nm3,
                "oxygen_use_t": oxygen_t,
                "steam_or_boiler_use_mwh": steam_boiler_mwh,
                "BFG_generated_mwh": round(bfg_generated, 6),
                "COG_generated_mwh": round(cog_generated, 6),
                "BOFG_generated_mwh": round(bofg_generated, 6),
                "BFG_consumed_mwh": round(bfg_consumed, 6),
                "COG_consumed_mwh": round(cog_consumed, 6),
                "BOFG_consumed_mwh": round(bofg_consumed, 6),
                "WAG_to_electricity_mwh": round(wag_to_electricity, 6),
                "BFG_flared_mwh": round(bfg_flared, 6),
                "COG_flared_mwh": round(cog_flared, 6),
                "BOFG_flared_mwh": round(bofg_flared, 6),
                "process_co2_t": process_co2_t,
                "combustion_co2_t": combustion_co2_t,
                "flaring_co2_t": round(bfg_flare_co2 + cog_flare_co2 + bofg_flare_co2, 6),
                "capacity_utilisation": round(activity / capacity_upper, 6) if capacity_upper else "",
                "schedule_status": schedule_status,
                "caveat": caveat,
            }
        )

    for row in hourly_rows:
        if row["configuration_id"] == C0:
            kgf1 = _safe_float(row.get("C0_KGF1_input_t_h"))
            kgf2 = _safe_float(row.get("C0_KGF2_input_t_h"))
            sinter = _safe_float(row.get("C0_sintering_input_t_h"))
            bf6 = _safe_float(row.get("C0_BF6_sinter_input_t_h"))
            bf7 = _safe_float(row.get("C0_BF7_sinter_input_t_h"))
            bof = _safe_float(row.get("C0_BOF_hot_iron_input_t_h"))
            hsm = _safe_float(row.get("C0_HSM_input_t_h"))
            add(
                row,
                plant_id="KGF1_CokingPlant1",
                activity=kgf1,
                on_state=row.get("C0_KGF1_on", ""),
                material_input=kgf1,
                material_output=kgf1,
                cog_generated=kgf1 * c0_inputs.cog_mwh_per_t_coke,
                bfg_consumed=_safe_float(row.get("BFG_to_KGF1_mwh")),
                cog_consumed=_safe_float(row.get("COG_to_KGF1_mwh")),
                capacity_upper=c0_inputs.process_limits["coking_plant_1"][1],
                caveat="CP1 uses mixed BFG/COG underfiring in C5.",
            )
            add(
                row,
                plant_id="KGF2_CokingPlant2",
                activity=kgf2,
                on_state=row.get("C0_KGF2_on", ""),
                material_input=kgf2,
                material_output=kgf2,
                cog_generated=kgf2 * c0_inputs.cog_mwh_per_t_coke,
                cog_consumed=_safe_float(row.get("COG_to_KGF2_mwh")),
                capacity_upper=c0_inputs.process_limits["coking_plant_2"][1],
                caveat="CP2 uses pure COG underfiring; C0 only.",
            )
            add(
                row,
                plant_id="SinteringPlant",
                activity=sinter,
                on_state=row.get("C0_sintering_on", ""),
                material_input=sinter,
                material_output=sinter,
                cog_consumed=_safe_float(row.get("COG_to_sinter_mwh")),
                capacity_upper=c0_inputs.process_limits["sintering_plant"][1],
                caveat="Fixed COG process sink.",
            )
            add(
                row,
                plant_id="BF6",
                activity=bf6,
                on_state=row.get("C0_BF6_on", ""),
                material_input=bf6,
                material_output=bf6 * c0_inputs.bf_hot_iron_per_t_sinter,
                bfg_generated=bf6 * c0_inputs.bf_hot_iron_per_t_sinter * c0_inputs.bfg_mwh_per_t_hot_iron,
                capacity_upper=c0_inputs.process_limits["blast_furnace_6"][1],
                caveat="BF6 figure-derived development capacity.",
            )
            add(
                row,
                plant_id="BF7",
                activity=bf7,
                on_state=row.get("C0_BF7_on", ""),
                material_input=bf7,
                material_output=bf7 * c0_inputs.bf_hot_iron_per_t_sinter,
                bfg_generated=bf7 * c0_inputs.bf_hot_iron_per_t_sinter * c0_inputs.bfg_mwh_per_t_hot_iron,
                capacity_upper=c0_inputs.process_limits["blast_furnace_7"][1],
                caveat="BF7 capacity is emissions-share-scaled development proxy.",
            )
            add(
                row,
                plant_id="BOF",
                activity=bof,
                on_state=row.get("C0_BOF_on", ""),
                material_input=bof,
                material_output=bof * c0_inputs.bof_crude_steel_per_t_hot_iron,
                bofg_generated=bof * c0_inputs.bofg_mwh_per_t_liquid_steel,
                capacity_upper=c0_inputs.process_limits["basic_oxygen_furnace"][1],
                caveat="BOFG can go to internal generation or flare; no BOFG-to-boiler base use.",
            )
            add(
                row,
                plant_id="HSM",
                activity=hsm,
                on_state=row.get("C0_HSM_on", ""),
                material_input=hsm,
                material_output=_safe_float(row.get("final_product_output_t")),
                electricity="not_modelled_separately",
                capacity_upper=c0_inputs.process_limits["hot_strip_mill"][1],
                caveat="HSM direct electricity/fuel split is calibration-readiness item.",
            )
        else:
            kgf1 = _safe_float(row.get("C1_retained_coking_input_t_h"))
            sinter = _safe_float(row.get("C1_retained_sintering_input_t_h"))
            bf6 = _safe_float(row.get("C1_retained_BF6_sinter_input_t_h"))
            bof = _safe_float(row.get("C1_retained_BOF_hot_iron_input_t_h"))
            hsm = _safe_float(row.get("C1_retained_HSM_input_t_h"))
            drp = _safe_float(row.get("C1_DRP_activity_t_pellets_h"))
            eaf = _safe_float(row.get("C1_EAF_activity_t_DRI_h"))
            add(
                row,
                plant_id="KGF1_CokingPlant1",
                activity=kgf1,
                on_state=row.get("C1_KGF1_on", ""),
                material_input=kgf1,
                material_output=kgf1,
                cog_generated=kgf1 * retained.cog_mwh_per_t_coke,
                bfg_consumed=_safe_float(row.get("BFG_to_KGF1_mwh")),
                cog_consumed=_safe_float(row.get("COG_to_KGF1_mwh")),
                capacity_upper=retained.process_limits["coking_plant_1"][1],
                caveat="C1 retained KGF1 active; KGF2 inactive.",
            )
            add(
                row,
                plant_id="SinteringPlant",
                activity=sinter,
                on_state=row.get("C1_sintering_on", ""),
                material_input=sinter,
                material_output=sinter,
                cog_consumed=_safe_float(row.get("COG_to_sinter_mwh")),
                capacity_upper=retained.process_limits["sintering_plant"][1],
                caveat="Retained BF-BOF route process sink.",
            )
            add(
                row,
                plant_id="BF6",
                activity=bf6,
                on_state=row.get("C1_BF6_on", ""),
                material_input=bf6,
                material_output=bf6 * retained.bf_hot_iron_per_t_sinter,
                bfg_generated=bf6 * retained.bf_hot_iron_per_t_sinter * retained.bfg_mwh_per_t_hot_iron,
                capacity_upper=retained.process_limits["blast_furnace_6"][1],
                caveat="Bottom-up retained BF6 route; BF7 inactive.",
            )
            add(
                row,
                plant_id="BOF",
                activity=bof,
                on_state=row.get("C1_BOF_on", ""),
                material_input=bof,
                material_output=bof,
                bofg_generated=bof * retained.bofg_mwh_per_t_liquid_steel,
                capacity_upper=retained.process_limits["basic_oxygen_furnace"][1],
                caveat="Retained BOF route.",
            )
            add(
                row,
                plant_id="HSM",
                activity=hsm,
                on_state=row.get("C1_HSM_on", ""),
                material_input=hsm,
                material_output=_safe_float(row.get("C1_retained_final_product_output_t")),
                capacity_upper=retained.process_limits["hot_strip_mill"][1],
                caveat="Retained HSM pass-through; HSM fuel coefficient still not calibrated.",
            )
            add(
                row,
                plant_id="DRP",
                activity=drp,
                on_state=row.get("C1_DRP_on", ""),
                material_input=drp,
                material_output=drp * c1_inputs.drp_yield_t_dri_per_t_pellets,
                electricity=round(drp * c1_inputs.drp_electricity_mwh_per_t_pellets, 6),
                natural_gas_nm3=round(drp * c1_inputs.drp_ng_nm3_per_t_pellets, 6),
                oxygen_t=round(drp * c1_inputs.drp_o2_t_per_t_pellets, 6),
                capacity_upper=c1_inputs.drp_max_t_pellets_h,
                process_co2_t=round(0.5 * drp, 6),
                caveat="DRP direct CO2 is development diagnostic placeholder.",
            )
            add(
                row,
                plant_id="EAF",
                activity=eaf,
                on_state=row.get("C1_EAF_on", ""),
                material_input=eaf,
                material_output=eaf * c1_inputs.eaf_yield_t_final_per_t_dri,
                electricity=round(eaf * c1_inputs.eaf_electricity_mwh_per_t_dri, 6),
                oxygen_t=round(eaf * c1_inputs.eaf_o2_t_per_t_dri, 6),
                capacity_upper=c1_inputs.eaf_max_t_dri_h,
                caveat="EAF development row; no scrap economics.",
            )
    return rows


def _residual_load_report(audits: list[dict[str, Any]], hourly_rows: list[dict[str, Any]], horizon: str, horizon_hours: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_config = {row["configuration_id"]: row for row in audits}
    for config_id in (C0, C1):
        config_rows = _by_config(hourly_rows, config_id)
        audit = by_config[config_id]
        final_product = _safe_float(audit.get("final_product_fulfilled_t"))
        scale = _production_scale(final_product, horizon_hours)
        gross = _sum(config_rows, "gross_electricity_mwh")
        wag_elec = _sum(config_rows, "wag_electricity_mwh")
        net_import = _sum(config_rows, "net_grid_import_mwh")
        drp_ng_nm3 = _sum(config_rows, "natural_gas_nm3")
        wag_used = _sum(config_rows, "WAG_used")
        steam = _sum(config_rows, "steam")
        metrics = [
            ("gross_electricity", gross, ANCHORS["C0_gross_electricity" if config_id == C0 else "C1_gross_electricity"]),
            ("wag_internal_electricity", wag_elec, ANCHORS["C1_wag_internal_electricity"]),
            ("net_grid_import", net_import, ANCHORS["C0_gross_electricity" if config_id == C0 else "C1_gross_electricity"]),
            ("natural_gas_CH4_HHV_basis", drp_ng_nm3, ANCHORS["CH4_HHV"]),
            ("WAG_used_or_reused", wag_used, ANCHORS["C0_wag_reuse"]),
            ("boiler_steam_placeholder", steam, ANCHORS["boiler_steam_placeholder"]),
        ]
        for metric, model_value, anchor in metrics:
            unscaled_horizon_anchor = anchor["annual_value"] * horizon_hours / 8760.0
            production_scaled_anchor = unscaled_horizon_anchor * scale
            residual = production_scaled_anchor - model_value
            rows.append(
                {
                    "horizon": horizon,
                    "configuration_id": config_id,
                    "metric": metric,
                    "model_value": round(model_value, 6),
                    "unit": anchor["unit"].replace("/y", f"/{horizon}"),
                    "full_site_anchor_annual": round(anchor["annual_value"], 6),
                    "unscaled_horizon_anchor": round(unscaled_horizon_anchor, 6),
                    "production_scale_factor": round(scale, 9),
                    "production_scaled_anchor": round(production_scaled_anchor, 6),
                    "residual_load_or_gap": round(residual, 6),
                    "negative_residual_overcount_flag": residual < -TOLERANCE,
                    "basis": anchor["basis"],
                    "source": anchor["source"],
                    "basis_warning": anchor["basis_warning"],
                    "caveat": "Diagnostic only; residual is not hidden inside optimiser.",
                }
            )
    return rows


def _validation_dashboard(
    audits: list[dict[str, Any]],
    hourly_rows: list[dict[str, Any]],
    horizon: str,
    horizon_hours: int,
    residual_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    residual_lookup = {
        (row["configuration_id"], row["metric"]): row for row in residual_rows if row["horizon"] == horizon
    }
    rows: list[dict[str, Any]] = []
    by_config = {row["configuration_id"]: row for row in audits}
    metric_fields = {
        "final_product": ("final_product_output_t", "t"),
        "gross_electricity": ("gross_electricity_mwh", "MWh"),
        "wag_internal_electricity": ("wag_electricity_mwh", "MWh"),
        "net_grid_import": ("net_grid_import_mwh", "MWh"),
        "natural_gas_CH4_HHV_basis": ("natural_gas_nm3", "Nm3"),
        "WAG_generated": ("WAG_generated", "MWh_LHV"),
        "WAG_used_or_reused": ("WAG_used", "MWh_LHV"),
        "WAG_flared": ("WAG_flared", "MWh_LHV"),
        "boiler_steam_placeholder": ("steam", "MWh_steam_proxy"),
        "flaring_CO2": ("flaring_co2_t", "tCO2"),
        "flaring_CO2_diagnostic_cost": ("flaring_co2_diagnostic_cost_eur", "EUR"),
    }
    for config_id in (C0, C1):
        config_rows = _by_config(hourly_rows, config_id)
        final_product = _safe_float(by_config[config_id].get("final_product_fulfilled_t"))
        for metric, (field, unit) in metric_fields.items():
            model_value = final_product if metric == "final_product" else _sum(config_rows, field)
            residual = residual_lookup.get((config_id, metric), {})
            rows.append(
                {
                    "horizon": horizon,
                    "configuration_id": config_id,
                    "metric": metric,
                    "model_value": round(model_value, 6),
                    "unit": unit,
                    "per_t_final_product": round(model_value / final_product, 9) if final_product else "",
                    "annualised_value": round(model_value * 8760.0 / horizon_hours, 6),
                    "production_scaled_anchor": residual.get("production_scaled_anchor", ""),
                    "residual_to_production_scaled_anchor": residual.get("residual_load_or_gap", ""),
                    "basis_flag": residual.get("basis_warning", ""),
                    "caveat": "Diagnostic validation dashboard; not calibration or thesis validation.",
                }
            )
    return rows


def _calibration_readiness(
    audits: list[dict[str, Any]],
    hourly_rows: list[dict[str, Any]],
    residual_rows: list[dict[str, Any]],
    horizon: str,
) -> list[dict[str, Any]]:
    by_config = {row["configuration_id"]: row for row in audits}
    return [
        {
            "horizon": horizon,
            "calibration_knob": "residual_electricity_load",
            "current_value": "see residual_load_report:gross_electricity",
            "source_evidence_status": "validation_anchor_available",
            "target_anchor_affected": "gross electricity and net grid import",
            "safe_calibration_range": "not_set",
            "sensitivity_required": "true",
            "recommended_next_step": "decide whether residual should be fixed non-flexible Load or remain validation residual.",
        },
        {
            "horizon": horizon,
            "calibration_knob": "DRP_EAF_auxiliary_electricity",
            "current_value": round(_sum(_by_config(hourly_rows, C1), "gross_electricity_mwh"), 6),
            "source_evidence_status": "development_assumption",
            "target_anchor_affected": "C1 electricity",
            "safe_calibration_range": "existing S3/S4 rows only; no new range invented",
            "sensitivity_required": "true",
            "recommended_next_step": "calibrate against C1 gross/net electricity after residual loads are separated.",
        },
        {
            "horizon": horizon,
            "calibration_knob": "retained_BF6_route_scaling",
            "current_value": by_config.get(C1, {}).get("retained_bf_bof_final_product_t", ""),
            "source_evidence_status": "bottom_up_development_policy",
            "target_anchor_affected": "C1 route split, WAG generation, CO2",
            "safe_calibration_range": "emissions proxy to feasible fixed-block range",
            "sensitivity_required": "true",
            "recommended_next_step": "test retained route policy variants before economics.",
        },
        {
            "horizon": horizon,
            "calibration_knob": "Vattenfall_utilisation_efficiency",
            "current_value": f"eta internal power implicit; total cap {VATTENFALL_TOTAL_WAG_CAP_NM3_H} Nm3/h",
            "source_evidence_status": "figure_derived_development_candidate",
            "target_anchor_affected": "WAG electricity, net import, flaring",
            "safe_calibration_range": "not_set",
            "sensitivity_required": "true",
            "recommended_next_step": "calibrate against internal-generation anchor without adding revenue.",
        },
        {
            "horizon": horizon,
            "calibration_knob": "boiler_WAG_NG_allocation",
            "current_value": f"WAG cap {BOILER_WAG_PLACEHOLDER_CAP_MWH_H} MWh/h, total {BOILER_TOTAL_PLACEHOLDER_MWH_H} MWh/h",
            "source_evidence_status": "S3.3j_development_placeholder",
            "target_anchor_affected": "steam, WAG use, NG use",
            "safe_calibration_range": "not_set",
            "sensitivity_required": "true",
            "recommended_next_step": "decide if 6 PJ/y should remain placeholder or become fixed non-flexible Load.",
        },
        {
            "horizon": horizon,
            "calibration_knob": "HSM_PEFA_gas_coefficients",
            "current_value": "inactive/deferred",
            "source_evidence_status": "policy_decision_or_source_needed",
            "target_anchor_affected": "WAG/NG sink realism",
            "safe_calibration_range": "not_available",
            "sensitivity_required": "true",
            "recommended_next_step": "approve coefficients before enabling executable process sinks.",
        },
        {
            "horizon": horizon,
            "calibration_knob": "background_NG_steam_load",
            "current_value": "diagnostic residual only",
            "source_evidence_status": "HHV validation candidate available",
            "target_anchor_affected": "CH4/NG validation",
            "safe_calibration_range": "not_set",
            "sensitivity_required": "true",
            "recommended_next_step": "keep HHV NG accounting separate from LHV WAG balances.",
        },
    ]


def _stage_gate(audits: list[dict[str, Any]], hourly_rows: list[dict[str, Any]], *, phase: str) -> dict[str, Any]:
    by_config = {row["configuration_id"]: row for row in audits}
    c0_ok = by_config.get(C0, {}).get("build_status") == "solved" and abs(_safe_float(by_config[C0].get("final_product_residual_t"), 1.0)) <= TOLERANCE
    c1_ok = by_config.get(C1, {}).get("build_status") == "solved" and abs(_safe_float(by_config[C1].get("final_product_residual_t"), 1.0)) <= TOLERANCE
    balance_ok = _max_balance_residual(hourly_rows) <= TOLERANCE
    c0_cp2_active = _sum(_by_config(hourly_rows, C0), "C0_KGF2_input_t_h") > TOLERANCE
    c1_retained_active = _safe_float(by_config.get(C1, {}).get("retained_bf_bof_final_product_t")) > TOLERANCE
    if not balance_ok:
        decision = f"blocked_{phase}_carrier_balance_failure"
    elif not c0_cp2_active:
        decision = f"blocked_{phase}_c0_cp2_inactive"
    elif not c1_retained_active:
        decision = f"blocked_{phase}_c1_retained_route_inactive"
    elif c0_ok and c1_ok and phase == "24h":
        decision = "pass_to_168h_c5_diagnostics"
    elif c0_ok and c1_ok:
        decision = "pass_s4_4c5_calibration_readiness_with_caveats"
    else:
        decision = f"blocked_{phase}_physical_regression_failed"
    return {
        "stage": f"S4.4c5_{phase}",
        "decision": decision,
        "c0_solved": c0_ok,
        "c1_solved": c1_ok,
        "c0_cp2_active": c0_cp2_active,
        "c1_retained_bf6_kgf1_bof_route_active": c1_retained_active,
        "c1_route_policy": by_config.get(C1, {}).get("retained_route_policy", ""),
        "max_abs_wag_balance_residual_mwh": round(_max_balance_residual(hourly_rows), 9),
        "vattenfall_cap_policy": "combined_volume_cap",
        "daily_production_guardrail_active": True,
        "raw_pdf_inspected": False,
        "economics_active": False,
        "thesis_usable": False,
        "Tata_validated": False,
        "caveat": "Development static physical diagnostics only; residual loads are not optimisation inputs.",
    }


def _run_regression(
    *,
    prefix: str,
    horizon: str,
    horizon_hours: int,
    target_multiplier: float,
    scaling_reference: dict[str, float] | None = None,
) -> dict[str, Any]:
    validation_start = time.perf_counter()
    validation = validate_unified_dev_inputs(CORRECTED_INPUT_DIR.resolve())
    validation_time = time.perf_counter() - validation_start
    if validation["failure_count"] != 0:
        gate = {
            "stage": f"S4.4c5_{horizon}",
            "decision": "blocked_c5_input_validation_failed",
            "validator_failure_count": validation["failure_count"],
        }
        _write_json(C5_DIR / f"{prefix}_stage_gate.json", gate)
        _write_csv(C5_DIR / f"{prefix}_stage_gate.csv", [gate])
        return {"phase_stage_gate": gate, "configuration_build_audit": [], "hourly_rows": []}

    start = time.perf_counter()
    report = run_s44c_unified_physical_regression(
        input_dir=CORRECTED_INPUT_DIR.resolve(),
        run_id=f"s4_4c5_{horizon}_diagnostics",
        write_report=False,
        horizon_hours_override=horizon_hours,
        target_multiplier=target_multiplier,
        fix_c0_binary_schedule=True,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        enable_internal_wag_power=True,
        daily_production_guardrail=True,
        fix_c1_hybrid_schedule=False,
        c1_retained_route_policy="bottom_up_fixed_retained_route",
    )
    total_runtime = time.perf_counter() - start
    audits = report["configuration_build_audit"]
    hourly_rows = report["hourly_rows"]
    gate = _stage_gate(audits, hourly_rows, phase=horizon)
    residual_rows = _residual_load_report(audits, hourly_rows, horizon, horizon_hours)
    plant_rows = _plant_rows(hourly_rows, horizon)
    dashboard_rows = _validation_dashboard(audits, hourly_rows, horizon, horizon_hours, residual_rows)
    readiness_rows = _calibration_readiness(audits, hourly_rows, residual_rows, horizon)
    full_report = {
        **report,
        "phase_stage_gate": gate,
        "input_validation_time_seconds": round(validation_time, 6),
        "total_runtime_seconds": round(total_runtime, 6),
        "c5_policy": "bottom_up_fixed_retained_route_and_c0_cp2_active_schedule",
    }
    _write_json(C5_DIR / f"{prefix}_report.json", full_report)
    _write_csv(C5_DIR / f"{prefix}_report.csv", _report_rows(audits))
    _write_csv(C5_DIR / f"{prefix}_hourly_dispatch_c0.csv", [row for row in hourly_rows if row["configuration_id"] == C0])
    _write_csv(C5_DIR / f"{prefix}_hourly_dispatch_c1.csv", [row for row in hourly_rows if row["configuration_id"] == C1])
    _write_csv(C5_DIR / f"{prefix}_route_split.csv", _route_split_rows(audits, horizon))
    _write_csv(C5_DIR / f"{prefix}_plant_diagnostics.csv", plant_rows)
    _write_csv(C5_DIR / f"{prefix}_wag_by_carrier.csv", _wag_by_carrier(hourly_rows))
    _write_csv(C5_DIR / f"{prefix}_wag_by_sink.csv", _wag_by_sink(hourly_rows))
    _write_csv(C5_DIR / f"{prefix}_electricity_summary.csv", _electricity_summary(hourly_rows))
    _write_csv(C5_DIR / f"{prefix}_ng_and_steam_summary.csv", _ng_steam_summary(hourly_rows))
    _write_csv(C5_DIR / f"{prefix}_co2_flaring_summary.csv", _co2_flaring_summary(hourly_rows))
    _write_csv(C5_DIR / f"{prefix}_residual_load_report.csv", residual_rows)
    _write_csv(C5_DIR / f"{prefix}_validation_dashboard.csv", dashboard_rows)
    _write_csv(C5_DIR / f"{prefix}_calibration_readiness.csv", readiness_rows)
    _write_csv(
        C5_DIR / f"{prefix}_computational_analytics.csv",
        _analytics(
            audits,
            validation_time=validation_time,
            total_runtime=total_runtime,
            output_dir=C5_DIR,
            scaling_reference=scaling_reference,
        ),
    )
    if horizon == "168h":
        _write_csv(C5_DIR / f"{prefix}_daily_summary.csv", _daily_summary(hourly_rows))
    _write_json(C5_DIR / f"{prefix}_stage_gate.json", gate)
    _write_csv(C5_DIR / f"{prefix}_stage_gate.csv", [gate])
    return full_report


def run_24h() -> dict[str, Any]:
    phase1_gate = _read_json(C5_DIR / "s4_4c5_phase1_stage_gate.json")
    if phase1_gate.get("decision") != "pass_to_phase2_bottom_up_24h":
        gate = {
            "stage": "S4.4c5_24h",
            "decision": "blocked_phase1_gate",
            "phase1_gate": phase1_gate.get("decision", "missing"),
        }
        _write_json(C5_DIR / "s4_4c5_24h_stage_gate.json", gate)
        _write_csv(C5_DIR / "s4_4c5_24h_stage_gate.csv", [gate])
        return {"phase_stage_gate": gate, "configuration_build_audit": [], "hourly_rows": []}
    return _run_regression(prefix="s4_4c5_24h", horizon="24h", horizon_hours=24, target_multiplier=1.0)


def run_168h() -> dict[str, Any]:
    gate24 = _read_json(C5_DIR / "s4_4c5_24h_stage_gate.json")
    if gate24.get("decision") != "pass_to_168h_c5_diagnostics":
        gate = {
            "stage": "S4.4c5_168h",
            "decision": "blocked_24h_gate",
            "phase2_gate": gate24.get("decision", "missing"),
        }
        _write_json(C5_DIR / "s4_4c5_168h_stage_gate.json", gate)
        _write_csv(C5_DIR / "s4_4c5_168h_stage_gate.csv", [gate])
        return {"phase_stage_gate": gate, "configuration_build_audit": [], "hourly_rows": []}
    scaling_reference = {
        row["configuration_id"]: _safe_float(row.get("solve_time_seconds"))
        for row in _read_csv(C5_DIR / "s4_4c5_24h_computational_analytics.csv")
    }
    return _run_regression(
        prefix="s4_4c5_168h",
        horizon="168h",
        horizon_hours=168,
        target_multiplier=7.0,
        scaling_reference=scaling_reference,
    )


def run_s4_4c5_physical_diagnostics() -> dict[str, Any]:
    phase1 = run_phase1_audit()
    result: dict[str, Any] = {"phase1_gate": phase1}
    if phase1["decision"] != "pass_to_phase2_bottom_up_24h":
        _write_combined_stage_gate(result)
        return result
    phase2 = run_24h()
    result["phase2_gate"] = phase2["phase_stage_gate"]
    if phase2["phase_stage_gate"]["decision"] != "pass_to_168h_c5_diagnostics":
        _write_combined_stage_gate(result)
        return result
    phase3 = run_168h()
    result["phase3_gate"] = phase3["phase_stage_gate"]
    _write_combined_stage_gate(result)
    return result


def _write_combined_stage_gate(result: dict[str, Any]) -> None:
    final_gate = result.get("phase3_gate") or result.get("phase2_gate") or result["phase1_gate"]
    row = {
        "stage": "S4.4c5_full_scope_physical_diagnostics",
        "decision": final_gate.get("decision", "missing"),
        "phase1_gate": result.get("phase1_gate", {}).get("decision", "missing"),
        "phase2_gate": result.get("phase2_gate", {}).get("decision", "not_run"),
        "phase3_gate": result.get("phase3_gate", {}).get("decision", "not_run"),
        "raw_pdf_inspected": False,
        "economics_active": False,
        "thesis_usable": False,
        "Tata_validated": False,
        "caveat": "S4.4c5 diagnostics only; calibration and economics remain future work.",
    }
    _write_json(C5_DIR / "s4_4c5_stage_gate.json", row)
    _write_csv(C5_DIR / "s4_4c5_stage_gate.csv", [row])


def main() -> int:
    result = run_s4_4c5_physical_diagnostics()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
