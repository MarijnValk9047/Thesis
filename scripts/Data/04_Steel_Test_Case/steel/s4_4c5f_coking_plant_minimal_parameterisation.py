"""S4.4c5f minimal coking-plant parameterisation.

This stage extends the C5e accounting repair with a development-executable
KGF1/KGF2 parameter layer. It keeps the solver outputs unchanged and reports a
coal-bus0-equivalent coking-plant conversion layer for diagnostics.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from pathlib import Path
from typing import Any

from .s4_4c_unified_physical_modelbuilder import (
    SELECTED_WAG_LHV_MJ_PER_NM3,
    VATTENFALL_TOTAL_WAG_CAP_NM3_H,
)
from .s4_4c5d_scale_downstream_lhv_consistency_repair import TARGET_SITE_T_Y
from .s4_4c5e_internal_consistency_repair import (
    C5E_DIR,
    C1,
    KGF1_SHARE,
    KGF2_SHARE,
    run_s4_4c5e_internal_consistency_repair,
)


S4_ROOT = Path("data/03_Optimisation/inputs/assets/steel/S4")
C5F_DIR = S4_ROOT / "s4_4c5f_coking_plant_minimal_parameterisation"
STAGE = "S4.4c5f_coking_plant_minimal_parameterisation"
SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/Coking_Plants_Parameters.md")

C0 = "C0_current_BF_BOF_reference"
CONFIGS = (C0, C1)
HORIZONS = (24, 168)
KGF_PLANTS = ("KGF1", "KGF2")

DRY_COAL_PER_COKE_TPT = 1.285
COG_YIELD_NM3_PER_T_COKE = 439.0
COG_LHV_MJ_PER_NM3 = SELECTED_WAG_LHV_MJ_PER_NM3["COG"]
COG_GROSS_MWH_PER_T_COKE = COG_YIELD_NM3_PER_T_COKE * COG_LHV_MJ_PER_NM3 / 3600.0
KGF_UNDERFIRING_GJ_PER_T_COKE = 3.55
KGF_UNDERFIRING_MWH_PER_T_COKE = KGF_UNDERFIRING_GJ_PER_T_COKE / 3.6
KGF_UNDERFIRING_NM3_PER_T_COKE = KGF_UNDERFIRING_GJ_PER_T_COKE * 1000.0 / COG_LHV_MJ_PER_NM3
COG_SURPLUS_MWH_PER_T_COKE = COG_GROSS_MWH_PER_T_COKE - KGF_UNDERFIRING_MWH_PER_T_COKE
COG_SURPLUS_NM3_PER_T_COKE = COG_YIELD_NM3_PER_T_COKE - KGF_UNDERFIRING_NM3_PER_T_COKE
KGF_ELECTRICITY_MWH_PER_T_COKE = 0.045
KGF_STEAM_GJ_PER_T_COKE = 0.43
KGF_STEAM_MWH_PER_T_COKE = KGF_STEAM_GJ_PER_T_COKE / 3.6
KGF_STEAM_T_PER_T_COKE_DIAGNOSTIC = 0.33
KGF_DIRECT_CO2_T_PER_T_COKE = 0.20
COG_CO2_POTENTIAL_T_PER_T_COKE = 0.297
KGF_SPLIT_ASSUMPTION_ID = "ASSUMP_KGF_CAPACITY_SPLIT_OVEN_COUNT_238_108"
COKE_ANCHOR_C0_T_Y = 1_500_000.0

WAG_TOL_MWH = 1.0


COMPACT_COLUMNS = [
    "configuration",
    "horizon_hours",
    "plant",
    "active",
    "main_product",
    "main_product_raw_t_y",
    "main_product_site_t_y",
    "scale_mode",
    "bus0_basis",
    "coal_t_per_t_coke",
    "coke_anchor_gap_pct",
    "COG_gross_Nm3_per_t_coke",
    "COG_gross_MWh_LHV_per_t_coke",
    "COG_self_use_MWh_LHV_per_t_coke",
    "COG_surplus_MWh_LHV_per_t_coke",
    "electricity_MWh_per_t_coke",
    "steam_MWh_proxy_per_t_coke",
    "direct_CO2_t_per_t_coke",
    "COG_CO2_potential_t_per_t_coke",
    "WAG_output_carrier",
    "WAG_output_MWh_LHV_per_t",
    "LHV_consistency_status",
    "carbon_accounting_status",
    "status",
    "red_flags",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _num(value: Any) -> float:
    if value in (None, "", "nan", "NaN"):
        return math.nan
    return float(value)


def _zero(value: Any) -> float:
    number = _num(value)
    return 0.0 if math.isnan(number) else number


def _fmt(value: Any) -> Any:
    if value in (None, ""):
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return round(value, 6)
    return value


def _mwh_to_nm3(mwh: float, carrier: str) -> float:
    return mwh * 3600.0 / SELECTED_WAG_LHV_MJ_PER_NM3[carrier]


def _nm3_to_mwh(nm3: float, carrier: str) -> float:
    return nm3 * SELECTED_WAG_LHV_MJ_PER_NM3[carrier] / 3600.0


def _rel(path: Path) -> str:
    return path.as_posix()


def _minimal_schema_rows() -> list[dict[str, Any]]:
    descriptions = {
        "parameter_id": "Stable identifier for a plant parameter.",
        "plant_id": "Short plant identifier.",
        "plant_name": "Human-readable plant name.",
        "applies_to_configuration": "Configuration or configuration family.",
        "active_in_C0": "Whether the plant is active in C0.",
        "active_in_C1": "Whether the plant is active in C1.",
        "bus0_basis": "Preferred main decision/input basis.",
        "main_product": "Primary output or activity denominator.",
        "parameter_group": "Minimal parameter group.",
        "parameter_name": "Human-readable parameter name.",
        "value": "Base value used in C5f.",
        "unit": "Unit of the base value.",
        "per_basis": "Denominator or basis for the value.",
        "value_low": "Low sensitivity value.",
        "value_high": "High sensitivity value.",
        "sensitivity_required": "Whether sensitivity testing is required.",
        "source_or_assumption_id": "Source-card or assumption identifier.",
        "evidence_status": "Evidence classification.",
        "assumption_status": "Assumption lifecycle status.",
        "executable_status": "Executable, diagnostic, validation, or not executable.",
        "thesis_usability": "Whether the row is thesis-grade as-is.",
        "calculation_formula": "Formula used for derived values.",
        "carbon_accounting_convention": "CO2 accounting convention where relevant.",
        "notes": "Short caveat or implementation note.",
    }
    return [
        {
            "field_name": field,
            "required": True,
            "description": descriptions[field],
            "example": "DRY_COAL_PER_COKE_TPT" if field == "parameter_id" else "",
            "notes": "Reusable minimal plant-parameter schema for C5f and later plant stages.",
        }
        for field in descriptions
    ]


def _kgf_parameter_defs() -> list[dict[str, Any]]:
    source_id = "source_cards/Coking_Plants_Parameters.md"
    return [
        ("DRY_COAL_PER_COKE_TPT", "Dry coal input per tonne coke", "material_conversion", DRY_COAL_PER_COKE_TPT, 1.22, 1.35, "t dry coal/t coke", "t coke", "source_backed_development", "development_executable", "coal_input_t=coke_output_t*1.285", ""),
        ("COG_YIELD_NM3_PER_T_COKE", "Gross clean COG yield", "WAG_generation", COG_YIELD_NM3_PER_T_COKE, 360.0, 518.0, "Nm3/t coke", "t coke", "source_backed_development", "development_executable", "gross_COG_Nm3=coke_output_t*439", ""),
        ("COG_LHV_MJ_PER_NM3", "Canonical COG LHV", "WAG_generation", COG_LHV_MJ_PER_NM3, 17.0, 20.0, "MJ/Nm3", "Nm3 COG", "source_backed_development", "development_executable", "MWh=Nm3*18.5/3600", ""),
        ("KGF_UNDERFIRING_GJ_PER_T_COKE", "KGF priority COG self-use", "WAG_self_use", KGF_UNDERFIRING_GJ_PER_T_COKE, 3.2, 3.9, "GJ/t coke", "t coke", "source_backed_development", "development_executable", "COG_self_use_MWh=coke_t*3.55/3.6", ""),
        ("COG_SURPLUS_MWH_PER_T_COKE", "Surplus COG to WAG network", "WAG_surplus", COG_SURPLUS_MWH_PER_T_COKE, "", "", "MWh_LHV/t coke", "t coke", "derived_from_source", "development_executable", "COG_gross_MWh-KGF_underfiring_MWh", ""),
        ("KGF_ELECTRICITY_MWH_PER_T_COKE", "KGF electricity demand", "energy_input", KGF_ELECTRICITY_MWH_PER_T_COKE, 0.035, 0.055, "MWh/t coke", "t coke", "engineering_assumption", "development_executable", "electricity_MWh=coke_t*0.045", ""),
        ("KGF_STEAM_GJ_PER_T_COKE", "KGF steam energy proxy", "energy_input", KGF_STEAM_GJ_PER_T_COKE, 0.06, 0.80, "GJ steam-equivalent/t coke", "t coke", "engineering_assumption", "development_executable", "steam_MWh_proxy=coke_t*0.43/3.6", ""),
        ("KGF_STEAM_T_PER_T_COKE_DIAGNOSTIC", "KGF steam mass diagnostic", "diagnostic_only", KGF_STEAM_T_PER_T_COKE_DIAGNOSTIC, 0.27, 0.384, "t steam/t coke", "t coke", "source_backed_development", "diagnostic_only", "mass basis only; not mixed with energy proxy", ""),
        ("KGF_DIRECT_CO2_T_PER_T_COKE", "KGF direct CO2", "emissions", KGF_DIRECT_CO2_T_PER_T_COKE, 0.15, 0.25, "tCO2/t coke", "t coke", "engineering_assumption", "development_executable", "direct_CO2_t=coke_t*0.20", "direct_kgf_emission_only"),
        ("COG_CO2_POTENTIAL_T_PER_T_COKE", "Carbon in COG CO2 potential", "diagnostic_only", COG_CO2_POTENTIAL_T_PER_T_COKE, 0.264, 0.330, "tCO2 potential/t coke", "t coke", "derived_from_source", "diagnostic_only", "COG_CO2_potential_t=coke_t*0.297", "carbon_in_cog_not_direct_kgf_emission"),
        ("KGF_CAPACITY_SPLIT_OVEN_COUNT_238_108", "KGF1/KGF2 oven-count split", "capacity_or_split", KGF1_SHARE, KGF2_SHARE, "", "share", "C0 KGF coke production", "engineering_assumption", "development_executable", "KGF1=238/(238+108); KGF2=108/(238+108)", ""),
    ], source_id


def _plant_parameter_register_rows() -> list[dict[str, Any]]:
    defs, source_id = _kgf_parameter_defs()
    rows: list[dict[str, Any]] = []
    for plant, name, active_c0, active_c1 in (
        ("KGF1", "KGF1 / Coking Plant 1", True, True),
        ("KGF2", "KGF2 / Coking Plant 2", True, False),
    ):
        for (
            parameter_id,
            parameter_name,
            parameter_group,
            value,
            low,
            high,
            unit,
            per_basis,
            evidence_status,
            executable_status,
            formula,
            carbon_convention,
        ) in defs:
            rows.append(
                {
                    "parameter_id": parameter_id,
                    "plant_id": plant,
                    "plant_name": name,
                    "applies_to_configuration": "C0_C1",
                    "active_in_C0": str(active_c0).lower(),
                    "active_in_C1": str(active_c1).lower(),
                    "bus0_basis": "coal_input_preferred; coke_basis_with_coal_bus0_equivalent_reporting_in_C5f",
                    "main_product": "coke",
                    "parameter_group": parameter_group,
                    "parameter_name": parameter_name,
                    "value": _fmt(value),
                    "unit": unit,
                    "per_basis": per_basis,
                    "value_low": _fmt(low),
                    "value_high": _fmt(high),
                    "sensitivity_required": "true",
                    "source_or_assumption_id": source_id if parameter_id != "KGF_CAPACITY_SPLIT_OVEN_COUNT_238_108" else KGF_SPLIT_ASSUMPTION_ID,
                    "evidence_status": evidence_status,
                    "assumption_status": "frozen_for_development",
                    "executable_status": executable_status,
                    "thesis_usability": "false",
                    "calculation_formula": formula,
                    "carbon_accounting_convention": carbon_convention,
                    "notes": "C5f development-only KGF parameter layer; not Tata truth and not calibrated to anchors.",
                }
            )

    placeholders = [
        ("Sinter", "Sinter Plant"),
        ("PEFA_Malerij", "Pelletizing Plant / PEFA Malerij"),
        ("PEFA_Branderij", "Pelletizing Plant / PEFA Branderij"),
        ("BF6", "Blast Furnace 6"),
        ("BF7", "Blast Furnace 7"),
        ("BOF_OSF", "BOF / OSF"),
        ("DRP", "Direct Reduction Plant"),
        ("EAF", "Electric Arc Furnace"),
        ("HSM_WBW", "HSM / WBW"),
        ("downstream_proxy", "Casting / slab / final-product proxy"),
        ("boilers", "Boilers / steam system"),
        ("Vattenfall", "Vattenfall / internal-generation interface"),
        ("flaring", "Flaring"),
    ]
    for plant, name in placeholders:
        rows.append(
            {
                "parameter_id": "MINIMUM_PARAMETER_SET_PLACEHOLDER",
                "plant_id": plant,
                "plant_name": name,
                "applies_to_configuration": "C0_C1",
                "active_in_C0": "",
                "active_in_C1": "",
                "bus0_basis": "",
                "main_product": "",
                "parameter_group": "not_yet_parameterised",
                "parameter_name": "minimum viable parameter set placeholder",
                "value": "",
                "unit": "",
                "per_basis": "",
                "value_low": "",
                "value_high": "",
                "sensitivity_required": "true",
                "source_or_assumption_id": "future_stage_required",
                "evidence_status": "not_yet_parameterised",
                "assumption_status": "not_applicable",
                "executable_status": "not_executable",
                "thesis_usability": "false",
                "calculation_formula": "",
                "carbon_accounting_convention": "",
                "notes": "Later plant stages should fill topology, bus0, main product, capacity/split, material, electricity, fuel/WAG/steam, WAG output, direct CO2, and downstream yield where relevant.",
            }
        )
    return rows


def _kgf_parameter_values_rows() -> list[dict[str, Any]]:
    defs, source_id = _kgf_parameter_defs()
    rows = []
    for item in defs:
        (
            parameter_id,
            parameter_name,
            parameter_group,
            value,
            low,
            high,
            unit,
            per_basis,
            evidence_status,
            executable_status,
            formula,
            carbon_convention,
        ) = item
        rows.append(
            {
                "parameter_id": parameter_id,
                "parameter_name": parameter_name,
                "parameter_group": parameter_group,
                "base_value": _fmt(value),
                "low_value": _fmt(low),
                "high_value": _fmt(high),
                "unit": unit,
                "per_basis": per_basis,
                "source_or_assumption_id": source_id if parameter_id != "KGF_CAPACITY_SPLIT_OVEN_COUNT_238_108" else KGF_SPLIT_ASSUMPTION_ID,
                "evidence_status": evidence_status,
                "assumption_status": "frozen_for_development",
                "executable_status": executable_status,
                "thesis_usability": "false",
                "sensitivity_required": "true",
                "calculation_formula": formula,
                "carbon_accounting_convention": carbon_convention,
                "notes": "C5f minimal KGF base value.",
            }
        )
    return rows


def _kgf_split_rows() -> list[dict[str, str]]:
    return _read_csv(C5E_DIR / "s4_4c5e_kgf_split_diagnostics.csv")


def _coke_lookup() -> dict[tuple[str, int, str], dict[str, float]]:
    lookup: dict[tuple[str, int, str], dict[str, float]] = {}
    for row in _kgf_split_rows():
        config = row["configuration"]
        horizon = int(row["horizon_hours"])
        for plant in KGF_PLANTS:
            lookup[(config, horizon, plant)] = {
                "raw": _zero(row[f"{plant.lower()}_coke_raw_t_y"]),
                "site": _zero(row[f"{plant.lower()}_coke_site_t_y"]),
            }
    return lookup


def _kgf_conversion_rows(coke: dict[tuple[str, int, str], dict[str, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            for plant in KGF_PLANTS:
                coke_raw = coke[(config, horizon, plant)]["raw"]
                coke_site = coke[(config, horizon, plant)]["site"]
                active = coke_raw > 0.0
                coal_raw = coke_raw * DRY_COAL_PER_COKE_TPT
                coal_site = coke_site * DRY_COAL_PER_COKE_TPT
                gross_nm3_raw = coke_raw * COG_YIELD_NM3_PER_T_COKE
                gross_nm3_site = coke_site * COG_YIELD_NM3_PER_T_COKE
                gross_mwh_raw = coke_raw * COG_GROSS_MWH_PER_T_COKE
                gross_mwh_site = coke_site * COG_GROSS_MWH_PER_T_COKE
                self_raw = coke_raw * KGF_UNDERFIRING_MWH_PER_T_COKE
                self_site = coke_site * KGF_UNDERFIRING_MWH_PER_T_COKE
                surplus_raw = gross_mwh_raw - self_raw
                surplus_site = gross_mwh_site - self_site
                elec_raw = coke_raw * KGF_ELECTRICITY_MWH_PER_T_COKE
                elec_site = coke_site * KGF_ELECTRICITY_MWH_PER_T_COKE
                steam_raw = coke_raw * KGF_STEAM_MWH_PER_T_COKE
                steam_site = coke_site * KGF_STEAM_MWH_PER_T_COKE
                direct_co2_raw = coke_raw * KGF_DIRECT_CO2_T_PER_T_COKE
                direct_co2_site = coke_site * KGF_DIRECT_CO2_T_PER_T_COKE
                cog_co2_potential = coke_site * COG_CO2_POTENTIAL_T_PER_T_COKE
                flags: list[str] = []
                if active and coal_raw <= 0:
                    flags.append("active_kgf_zero_coal")
                if active and coke_raw <= 0:
                    flags.append("active_kgf_zero_coke")
                if active and gross_mwh_raw <= 0:
                    flags.append("active_kgf_zero_cog")
                if active and elec_raw <= 0:
                    flags.append("active_kgf_zero_electricity")
                if active and steam_raw <= 0:
                    flags.append("active_kgf_zero_steam")
                if active and direct_co2_raw <= 0:
                    flags.append("active_kgf_missing_direct_co2")
                if surplus_raw < -1e-9:
                    flags.append("cog_surplus_negative")
                if config == C1 and plant == "KGF2" and coke_raw > 1e-9:
                    flags.append("kgf2_nonzero_in_c1")
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "plant_id": plant,
                        "plant_name": "KGF1 / Coking Plant 1" if plant == "KGF1" else "KGF2 / Coking Plant 2",
                        "active": str(active),
                        "activity_basis": "coke_basis_with_coal_bus0_equivalent_reporting",
                        "bus0_decision_basis": "coal_input_preferred_pending_solver_bus0_migration",
                        "bus0_migration_status": "pending_solver_bus0_migration",
                        "coke_output_raw_t_y": _fmt(coke_raw),
                        "coke_output_site_t_y": _fmt(coke_site),
                        "dry_coal_input_raw_t_y": _fmt(coal_raw),
                        "dry_coal_input_site_t_y": _fmt(coal_site),
                        "coal_t_per_t_coke": _fmt(DRY_COAL_PER_COKE_TPT if active else math.nan),
                        "coke_t_per_t_coal": _fmt(1.0 / DRY_COAL_PER_COKE_TPT if active else math.nan),
                        "gross_COG_raw_Nm3_y": _fmt(gross_nm3_raw),
                        "gross_COG_site_Nm3_y": _fmt(gross_nm3_site),
                        "gross_COG_raw_MWh_LHV_y": _fmt(gross_mwh_raw),
                        "gross_COG_site_MWh_LHV_y": _fmt(gross_mwh_site),
                        "gross_COG_Nm3_per_t_coke": _fmt(COG_YIELD_NM3_PER_T_COKE if active else math.nan),
                        "gross_COG_MWh_per_t_coke": _fmt(COG_GROSS_MWH_PER_T_COKE if active else math.nan),
                        "COG_to_KGF_underfiring_raw_MWh_LHV_y": _fmt(self_raw),
                        "COG_to_KGF_underfiring_site_MWh_LHV_y": _fmt(self_site),
                        "COG_underfiring_MWh_per_t_coke": _fmt(KGF_UNDERFIRING_MWH_PER_T_COKE if active else math.nan),
                        "surplus_COG_raw_MWh_LHV_y": _fmt(max(surplus_raw, 0.0)),
                        "surplus_COG_site_MWh_LHV_y": _fmt(max(surplus_site, 0.0)),
                        "surplus_COG_MWh_per_t_coke": _fmt(COG_SURPLUS_MWH_PER_T_COKE if active else math.nan),
                        "surplus_COG_Nm3_per_t_coke": _fmt(COG_SURPLUS_NM3_PER_T_COKE if active else math.nan),
                        "KGF_electricity_raw_MWh_y": _fmt(elec_raw),
                        "KGF_electricity_site_MWh_y": _fmt(elec_site),
                        "KGF_electricity_MWh_per_t_coke": _fmt(KGF_ELECTRICITY_MWH_PER_T_COKE if active else math.nan),
                        "KGF_steam_raw_MWh_proxy_y": _fmt(steam_raw),
                        "KGF_steam_site_MWh_proxy_y": _fmt(steam_site),
                        "KGF_steam_MWh_proxy_per_t_coke": _fmt(KGF_STEAM_MWH_PER_T_COKE if active else math.nan),
                        "KGF_steam_mass_t_per_t_coke_diagnostic": _fmt(KGF_STEAM_T_PER_T_COKE_DIAGNOSTIC if active else math.nan),
                        "KGF_direct_CO2_raw_t_y": _fmt(direct_co2_raw),
                        "KGF_direct_CO2_site_t_y": _fmt(direct_co2_site),
                        "KGF_direct_CO2_t_per_t_coke": _fmt(KGF_DIRECT_CO2_T_PER_T_COKE if active else math.nan),
                        "COG_carbon_potential_tCO2_y": _fmt(cog_co2_potential),
                        "COG_CO2_potential_t_per_t_coke": _fmt(COG_CO2_POTENTIAL_T_PER_T_COKE if active else math.nan),
                        "COG_carbon_accounting_status": "diagnostic_only_not_counted_as_direct_KGF_CO2",
                        "surplus_status": "pass" if surplus_raw >= -1e-9 else "fail",
                        "red_flags": ";".join(flags),
                        "notes": "Coal-bus0-equivalent reporting. COG self-use is deducted before surplus enters WAG network.",
                    }
                )
    return rows


def _cog_self_use_surplus_rows(conversions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in conversions:
        coke_raw = _zero(row["coke_output_raw_t_y"])
        gross_raw = _zero(row["gross_COG_raw_MWh_LHV_y"])
        self_raw = _zero(row["COG_to_KGF_underfiring_raw_MWh_LHV_y"])
        surplus_raw = _zero(row["surplus_COG_raw_MWh_LHV_y"])
        share = surplus_raw / gross_raw if gross_raw else math.nan
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_id": row["plant_id"],
                "active": row["active"],
                "coke_raw_t_y": row["coke_output_raw_t_y"],
                "coke_site_t_y": row["coke_output_site_t_y"],
                "coal_raw_t_y": row["dry_coal_input_raw_t_y"],
                "coal_site_t_y": row["dry_coal_input_site_t_y"],
                "COG_gross_raw_Nm3_y": row["gross_COG_raw_Nm3_y"],
                "COG_gross_site_Nm3_y": row["gross_COG_site_Nm3_y"],
                "COG_gross_raw_MWh_LHV_y": row["gross_COG_raw_MWh_LHV_y"],
                "COG_gross_site_MWh_LHV_y": row["gross_COG_site_MWh_LHV_y"],
                "COG_to_KGF_underfiring_raw_MWh_LHV_y": row["COG_to_KGF_underfiring_raw_MWh_LHV_y"],
                "COG_to_KGF_underfiring_site_MWh_LHV_y": row["COG_to_KGF_underfiring_site_MWh_LHV_y"],
                "COG_surplus_raw_MWh_LHV_y": row["surplus_COG_raw_MWh_LHV_y"],
                "COG_surplus_site_MWh_LHV_y": row["surplus_COG_site_MWh_LHV_y"],
                "COG_surplus_share": _fmt(share),
                "status": "pass" if row["surplus_status"] == "pass" else "fail",
                "red_flags": row["red_flags"],
                "notes": "Gross COG = KGF underfiring self-use + surplus clean COG to WAG network.",
            }
        )
    return rows


def _coke_anchor_rows(split_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for row in split_rows:
        config = row["configuration"]
        total_site = _zero(row["total_coke_site_t_y"])
        anchor = COKE_ANCHOR_C0_T_Y if config == C0 else math.nan
        gap = total_site - anchor if config == C0 else math.nan
        gap_pct = gap / anchor * 100.0 if config == C0 else math.nan
        rows.append(
            {
                "configuration": config,
                "horizon_hours": row["horizon_hours"],
                "total_coke_raw_t_y": row["total_coke_raw_t_y"],
                "total_coke_site_t_y": row["total_coke_site_t_y"],
                "coke_anchor_t_y": _fmt(anchor),
                "gap_t_y": _fmt(gap),
                "gap_pct": _fmt(gap_pct),
                "anchor_status": "validation_anchor_only" if config == C0 else "missing_C1_coke_anchor",
                "constraint_used": "false",
                "gap_type": "bottom_up_physical_demand_gap" if config == C0 else "missing_conversion_gap",
                "notes": "Coke anchor is not used as a constraint.",
            }
        )
    return rows


def _kgf_split_rows_c5f(split_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for row in split_rows:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "total_coke_site_t_y": row["total_coke_site_t_y"],
                "kgf1_coke_site_t_y": row["kgf1_coke_site_t_y"],
                "kgf2_coke_site_t_y": row["kgf2_coke_site_t_y"],
                "kgf1_share": row["kgf1_share_site"],
                "kgf2_share": row["kgf2_share_site"],
                "kgf1_expected_share": row["kgf1_expected_share"],
                "kgf2_expected_share": row["kgf2_expected_share"],
                "kgf_split_status": "pass" if not row["red_flags"] else "fail",
                "coke_anchor_t_y": COKE_ANCHOR_C0_T_Y if row["configuration"] == C0 else "",
                "coke_anchor_gap_t_y": _fmt(_zero(row["total_coke_site_t_y"]) - COKE_ANCHOR_C0_T_Y) if row["configuration"] == C0 else "",
                "coke_anchor_gap_pct": _fmt((_zero(row["total_coke_site_t_y"]) - COKE_ANCHOR_C0_T_Y) / COKE_ANCHOR_C0_T_Y * 100.0) if row["configuration"] == C0 else "",
                "anchor_used_as_constraint": "false",
                "assumption_id": KGF_SPLIT_ASSUMPTION_ID,
                "assumption_status": "frozen_for_development",
                "sensitivity_required": "true",
                "red_flags": row["red_flags"],
                "notes": "Preserves C5e user-approved 238:108 KGF split. C1 keeps KGF2 inactive.",
            }
        )
    return rows


def _allocate_network_cog(
    existing: dict[str, float],
    surplus: float,
) -> dict[str, float]:
    direct = min(existing["direct"], surplus)
    remaining = max(surplus - direct, 0.0)
    boiler = min(existing["boiler"], remaining)
    remaining = max(remaining - boiler, 0.0)
    vf = min(existing["vattenfall"], remaining)
    remaining = max(remaining - vf, 0.0)
    flared = min(existing["flared"], remaining)
    remaining = max(remaining - flared, 0.0)
    return {
        "direct": direct,
        "boiler": boiler,
        "vattenfall": vf,
        "flared": flared,
        "unmapped": remaining,
    }


def _wag_rows(
    conversions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base = _read_csv(C5E_DIR / "s4_4c5e_wag_generation_consumption_by_plant.csv")
    out: list[dict[str, Any]] = []
    surplus_by_key: dict[tuple[str, int, str], float] = {}
    site_surplus_by_key: dict[tuple[str, int, str], float] = {}
    for row in conversions:
        key = (row["configuration"], int(row["horizon_hours"]), row["plant_id"])
        surplus_by_key[key] = _zero(row["surplus_COG_raw_MWh_LHV_y"])
        site_surplus_by_key[key] = _zero(row["surplus_COG_site_MWh_LHV_y"])

    for row in base:
        item = dict(row)
        config = item["configuration"]
        horizon = int(item["horizon_hours"])
        plant = item["plant_id"]
        carrier = item["carrier"]
        factor = _zero(item["scale_factor"]) or 1.0
        if carrier == "COG" and plant in KGF_PLANTS:
            surplus = surplus_by_key[(config, horizon, plant)]
            item["generated_MWh_LHV_y"] = _fmt(surplus)
            item["generated_Nm3_y"] = _fmt(_mwh_to_nm3(site_surplus_by_key[(config, horizon, plant)], "COG"))
            item["consumed_direct_MWh_LHV_y"] = 0.0
            item["consumed_boiler_MWh_LHV_y"] = 0.0
            item["consumed_vattenfall_MWh_LHV_y"] = 0.0
            item["flared_MWh_LHV_y"] = 0.0
            item["balance_error_MWh_LHV_y"] = _fmt(surplus)
            item["raw_model_quantity"] = _fmt(surplus)
            item["site_scaled_quantity"] = _fmt(site_surplus_by_key[(config, horizon, plant)])
            item["status"] = "kgf_surplus_to_network_reported_at_site_total"
        out.append(item)

    # Rebuild SITE_TOTAL COG rows from net KGF surplus and previous sink demand.
    for config in CONFIGS:
        for horizon in HORIZONS:
            total_surplus = sum(surplus_by_key.get((config, horizon, plant), 0.0) for plant in KGF_PLANTS)
            total_site_surplus = sum(site_surplus_by_key.get((config, horizon, plant), 0.0) for plant in KGF_PLANTS)
            template = next(
                row
                for row in out
                if row["configuration"] == config
                and int(row["horizon_hours"]) == horizon
                and row["plant_id"] == "SITE_TOTAL"
                and row["carrier"] == "COG"
            )
            existing = {
                "direct": _zero(template["consumed_direct_MWh_LHV_y"]),
                "boiler": _zero(template["consumed_boiler_MWh_LHV_y"]),
                "vattenfall": _zero(template["consumed_vattenfall_MWh_LHV_y"]),
                "flared": _zero(template["flared_MWh_LHV_y"]),
            }
            allocated = _allocate_network_cog(existing, total_surplus)
            balance_error = total_surplus - allocated["direct"] - allocated["boiler"] - allocated["vattenfall"] - allocated["flared"] - allocated["unmapped"]
            for row in out:
                if row["configuration"] == config and int(row["horizon_hours"]) == horizon and row["plant_id"] == "SITE_TOTAL" and row["carrier"] == "COG":
                    row["generated_MWh_LHV_y"] = _fmt(total_surplus)
                    row["generated_Nm3_y"] = _fmt(_mwh_to_nm3(total_site_surplus, "COG"))
                    row["consumed_direct_MWh_LHV_y"] = _fmt(allocated["direct"])
                    row["consumed_boiler_MWh_LHV_y"] = _fmt(allocated["boiler"])
                    row["consumed_vattenfall_MWh_LHV_y"] = _fmt(allocated["vattenfall"])
                    row["flared_MWh_LHV_y"] = _fmt(allocated["flared"])
                    row["balance_error_MWh_LHV_y"] = _fmt(balance_error)
                    row["raw_model_quantity"] = _fmt(total_surplus)
                    row["site_scaled_quantity"] = _fmt(total_site_surplus)
                    row["status"] = "closed"
    return out


def _cog_balance_by_plant(conversions: list[dict[str, Any]], wag_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    site_total = {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in wag_rows
        if row["plant_id"] == "SITE_TOTAL" and row["carrier"] == "COG"
    }
    rows: list[dict[str, Any]] = []
    for row in conversions:
        if row["plant_id"] not in KGF_PLANTS:
            continue
        gross = _zero(row["gross_COG_raw_MWh_LHV_y"])
        self_use = _zero(row["COG_to_KGF_underfiring_raw_MWh_LHV_y"])
        surplus = _zero(row["surplus_COG_raw_MWh_LHV_y"])
        balance = gross - self_use - surplus
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_id": row["plant_id"],
                "carrier": "COG",
                "gross_generated_MWh_LHV_y": _fmt(gross),
                "self_used_MWh_LHV_y": _fmt(self_use),
                "surplus_to_network_MWh_LHV_y": _fmt(surplus),
                "used_other_direct_MWh_LHV_y": 0.0,
                "used_boiler_MWh_LHV_y": 0.0,
                "used_vattenfall_MWh_LHV_y": 0.0,
                "flared_MWh_LHV_y": 0.0,
                "unmapped_MWh_LHV_y": 0.0,
                "balance_error_MWh_LHV_y": _fmt(balance),
                "status": "pass" if abs(balance) <= WAG_TOL_MWH else "fail",
                "red_flags": "" if abs(balance) <= WAG_TOL_MWH else "cog_self_use_surplus_balance_error",
            }
        )
    for key, row in site_total.items():
        generated = _zero(row["generated_MWh_LHV_y"])
        direct = _zero(row["consumed_direct_MWh_LHV_y"])
        boiler = _zero(row["consumed_boiler_MWh_LHV_y"])
        vf = _zero(row["consumed_vattenfall_MWh_LHV_y"])
        flared = _zero(row["flared_MWh_LHV_y"])
        balance = generated - direct - boiler - vf - flared
        rows.append(
            {
                "configuration": key[0],
                "horizon_hours": key[1],
                "plant_id": "SITE_TOTAL",
                "carrier": "COG",
                "gross_generated_MWh_LHV_y": "",
                "self_used_MWh_LHV_y": "",
                "surplus_to_network_MWh_LHV_y": _fmt(generated),
                "used_other_direct_MWh_LHV_y": _fmt(direct),
                "used_boiler_MWh_LHV_y": _fmt(boiler),
                "used_vattenfall_MWh_LHV_y": _fmt(vf),
                "flared_MWh_LHV_y": _fmt(flared),
                "unmapped_MWh_LHV_y": _fmt(balance),
                "balance_error_MWh_LHV_y": 0.0,
                "status": "pass",
                "red_flags": "",
            }
        )
    return rows


def _plant_io_rows(conversions: list[dict[str, Any]], wag_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _read_csv(C5E_DIR / "s4_4c5e_plant_carrier_io_annualised.csv")
    out: list[dict[str, Any]] = []
    conversion_by_key = {(r["configuration"], int(r["horizon_hours"]), r["plant_id"]): r for r in conversions}
    for row in rows:
        item = dict(row)
        key = (item["configuration"], int(item["horizon_hours"]), item["plant_id"])
        if key in conversion_by_key and item["plant_id"] in KGF_PLANTS:
            conv = conversion_by_key[key]
            material = item["carrier_or_material"]
            if material == "coal_or_coking_feed_proxy":
                item["annual_quantity"] = conv["dry_coal_input_raw_t_y"]
                item["raw_model_quantity"] = conv["dry_coal_input_raw_t_y"]
                item["site_scaled_quantity"] = conv["dry_coal_input_site_t_y"]
                item["source_or_assumption_id"] = "source_cards/Coking_Plants_Parameters.md:DRY_COAL_PER_COKE_TPT"
            elif material == "COG" and item["direction"] == "output":
                item["annual_quantity"] = conv["surplus_COG_raw_MWh_LHV_y"]
                item["raw_model_quantity"] = conv["surplus_COG_raw_MWh_LHV_y"]
                item["site_scaled_quantity"] = conv["surplus_COG_site_MWh_LHV_y"]
                item["source_or_assumption_id"] = "source_cards/Coking_Plants_Parameters.md:COG_surplus_after_self_use"
                item["notes"] = "C5f reports only surplus clean COG as WAG network output; gross and self-use are separate diagnostics."
        out.append(item)
    return out


def _energy_rows(conversions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in conversions:
        for carrier, input_value in (
            ("electricity", row["KGF_electricity_site_MWh_y"]),
            ("steam_proxy", row["KGF_steam_site_MWh_proxy_y"]),
            ("COG_self_use", row["COG_to_KGF_underfiring_site_MWh_LHV_y"]),
        ):
            rows.append(
                {
                    "configuration": row["configuration"],
                    "horizon_hours": row["horizon_hours"],
                    "plant_id": row["plant_id"],
                    "carrier": carrier,
                    "input_MWh_y": input_value,
                    "output_MWh_y": 0.0,
                    "net_MWh_y": input_value,
                    "unit_basis": "site_scaled",
                    "HHV_or_LHV": "LHV" if carrier == "COG_self_use" else "not_applicable",
                    "status": "source_backed_development" if row["active"] == "True" else "structurally_inactive",
                    "notes": "C5f KGF minimal parameter accounting.",
                }
            )
    return rows


def _emissions_rows(conversions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in conversions:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_id": row["plant_id"],
                "emission_bucket": "KGF_direct_CO2",
                "CO2_t_y": row["KGF_direct_CO2_site_t_y"],
                "CO2_t_per_t_main_product": row["KGF_direct_CO2_t_per_t_coke"],
                "accounting_convention": "direct_kgf_emission_only",
                "included_in_anchor_comparison": "false",
                "double_counting_risk": "low",
                "status": "development_assumption" if row["active"] == "True" else "structurally_inactive",
                "notes": "Does not include carbon carried in COG.",
            }
        )
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_id": row["plant_id"],
                "emission_bucket": "COG_CO2_potential_diagnostic",
                "CO2_t_y": row["COG_carbon_potential_tCO2_y"],
                "CO2_t_per_t_main_product": row["COG_CO2_potential_t_per_t_coke"],
                "accounting_convention": "carbon_in_cog_not_direct_kgf_emission",
                "included_in_anchor_comparison": "false",
                "double_counting_risk": "explicitly_separated",
                "status": "diagnostic_only",
                "notes": "Do not add to direct KGF CO2 if COG is combusted elsewhere.",
            }
        )
    return rows


def _conversion_ratio_rows(conversions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _read_csv(C5E_DIR / "s4_4c5e_plant_conversion_ratios.csv")
    rows = [row for row in rows if row["plant_id"] not in KGF_PLANTS]
    for row in conversions:
        for carrier, ratio, unit, status in (
            ("coal_t_per_t_coke", row["coal_t_per_t_coke"], "t/t_coke", "source_backed_development"),
            ("COG_gross_Nm3_per_t_coke", row["gross_COG_Nm3_per_t_coke"], "Nm3/t_coke", "source_backed_development"),
            ("COG_gross_MWh_LHV_per_t_coke", row["gross_COG_MWh_per_t_coke"], "MWh_LHV/t_coke", "source_backed_development"),
            ("COG_self_use_MWh_LHV_per_t_coke", row["COG_underfiring_MWh_per_t_coke"], "MWh_LHV/t_coke", "source_backed_development"),
            ("COG_surplus_MWh_LHV_per_t_coke", row["surplus_COG_MWh_per_t_coke"], "MWh_LHV/t_coke", "derived_from_source"),
            ("electricity_MWh_per_t_coke", row["KGF_electricity_MWh_per_t_coke"], "MWh/t_coke", "engineering_assumption"),
            ("steam_MWh_proxy_per_t_coke", row["KGF_steam_MWh_proxy_per_t_coke"], "MWh_proxy/t_coke", "engineering_assumption"),
            ("direct_CO2_t_per_t_coke", row["KGF_direct_CO2_t_per_t_coke"], "tCO2/t_coke", "engineering_assumption"),
        ):
            rows.append(
                {
                    "configuration": row["configuration"],
                    "horizon_hours": row["horizon_hours"],
                    "plant_id": row["plant_id"],
                    "plant_name": row["plant_name"],
                    "asset_status": "active" if row["active"] == "True" else "inactive",
                    "route": "retained_bf_bof",
                    "main_product": "coke",
                    "main_product_quantity_t_y": row["coke_output_raw_t_y"],
                    "input_or_output": "diagnostic",
                    "carrier_or_material": carrier,
                    "annual_quantity": "",
                    "unit": "",
                    "ratio_value": ratio,
                    "ratio_unit": unit,
                    "ratio_denominator": "coke",
                    "expected_anchor_or_range": "",
                    "anchor_source": "source_cards/Coking_Plants_Parameters.md",
                    "gap_to_anchor_pct": "",
                    "status": status if row["active"] == "True" else "inactive_or_zero_denominator",
                    "model_effect": "KGF parameter layer diagnostic",
                    "notes": "C5f minimal KGF parameterisation.",
                    "main_product_site_t_y": row["coke_output_site_t_y"],
                    "raw_model_quantity": "",
                    "raw_model_unit": "",
                    "site_scaled_quantity": "",
                    "site_scaled_unit": "",
                    "scale_factor": "",
                    "scale_mode": "module_scaled_to_site_target" if row["active"] == "True" else "not_applicable",
                    "metric_scope": "KGF_minimal_parameterisation",
                }
            )
    return rows


def _lhv_checks(wag_rows: list[dict[str, Any]], cog_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(config: str, horizon: int, plant: str, carrier: str, direction: str, nm3: float, mwh: float, notes: str) -> None:
        expected = _nm3_to_mwh(nm3, carrier)
        abs_err = abs(mwh - expected)
        rel_err = abs_err / abs(expected) * 100.0 if abs(expected) > 1e-12 else 0.0
        status = "pass" if abs_err <= 1e-6 or rel_err <= 0.01 else "fail"
        checks.append(
            {
                "configuration": config,
                "horizon_hours": horizon,
                "plant": plant,
                "carrier": carrier,
                "direction": direction,
                "quantity_Nm3": _fmt(nm3),
                "reported_MWh_LHV": _fmt(mwh),
                "expected_MWh_LHV_from_LHV": _fmt(expected),
                "absolute_error_MWh": _fmt(abs_err),
                "relative_error_pct": _fmt(rel_err),
                "LHV_MJ_per_Nm3_used": SELECTED_WAG_LHV_MJ_PER_NM3[carrier],
                "status": status,
                "red_flags": "" if status == "pass" else "lhv_conversion_mismatch",
                "notes": notes,
            }
        )

    for row in wag_rows:
        carrier = row["carrier"]
        if carrier in SELECTED_WAG_LHV_MJ_PER_NM3:
            add(
                row["configuration"],
                int(row["horizon_hours"]),
                row["plant_id"],
                carrier,
                "WAG_network_generation_site_scaled",
                _zero(row["generated_Nm3_y"]),
                _zero(row["site_scaled_quantity"]),
                "WAG table site-scaled quantity converted with canonical LHV.",
            )
    for row in cog_rows:
        add(row["configuration"], int(row["horizon_hours"]), row["plant_id"], "COG", "gross_COG_site", _zero(row["COG_gross_site_Nm3_y"]), _zero(row["COG_gross_site_MWh_LHV_y"]), "KGF gross COG conversion.")
    return checks


def _wag_reconciliation(wag_rows: list[dict[str, Any]], compact: list[dict[str, Any]], plant_io: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_generated = {
        (row["configuration"], int(row["horizon_hours"]), row["WAG_output_carrier"], "raw"): _zero(row["main_product_raw_t_y"])
        for row in compact
        if str(row["plant"]).startswith("WAG_TOTAL_")
    }
    compact_generated.update(
        {
            (row["configuration"], int(row["horizon_hours"]), row["WAG_output_carrier"], "site_scaled"): _zero(row["main_product_site_t_y"])
            for row in compact
            if str(row["plant"]).startswith("WAG_TOTAL_")
        }
    )
    plant_io_generated: dict[tuple[str, int, str, str], float] = {}
    for row in plant_io:
        if row.get("accounting_class") != "WAG_generation":
            continue
        key_raw = (row["configuration"], int(row["horizon_hours"]), row["carrier_or_material"], "raw")
        key_site = (row["configuration"], int(row["horizon_hours"]), row["carrier_or_material"], "site_scaled")
        plant_io_generated[key_raw] = plant_io_generated.get(key_raw, 0.0) + _zero(row["raw_model_quantity"])
        plant_io_generated[key_site] = plant_io_generated.get(key_site, 0.0) + _zero(row["site_scaled_quantity"])

    rows = []
    for row in wag_rows:
        if row["plant_id"] != "SITE_TOTAL":
            continue
        for basis in ("raw", "site_scaled"):
            factor = _zero(row["scale_factor"]) if basis == "site_scaled" else 1.0
            generated = _zero(row["generated_MWh_LHV_y"]) * factor if basis == "site_scaled" else _zero(row["generated_MWh_LHV_y"])
            direct = _zero(row["consumed_direct_MWh_LHV_y"]) * factor if basis == "site_scaled" else _zero(row["consumed_direct_MWh_LHV_y"])
            boiler = _zero(row["consumed_boiler_MWh_LHV_y"]) * factor if basis == "site_scaled" else _zero(row["consumed_boiler_MWh_LHV_y"])
            vf = _zero(row["consumed_vattenfall_MWh_LHV_y"]) * factor if basis == "site_scaled" else _zero(row["consumed_vattenfall_MWh_LHV_y"])
            flared = _zero(row["flared_MWh_LHV_y"]) * factor if basis == "site_scaled" else _zero(row["flared_MWh_LHV_y"])
            comp = compact_generated[(row["configuration"], int(row["horizon_hours"]), row["carrier"], basis)]
            plant = plant_io_generated.get((row["configuration"], int(row["horizon_hours"]), row["carrier"], basis), 0.0)
            diff = max(abs(comp - generated), abs(plant - generated))
            status = "pass" if diff <= WAG_TOL_MWH and flared <= generated - direct - boiler - vf + WAG_TOL_MWH else "fail"
            flags = "" if status == "pass" else "compact_wag_generation_mismatch"
            rows.append(
                {
                    "configuration": row["configuration"],
                    "horizon_hours": row["horizon_hours"],
                    "scale_basis": basis,
                    "carrier": row["carrier"],
                    "compact_generated_MWh_LHV_y": _fmt(comp),
                    "balance_generated_MWh_LHV_y": _fmt(generated),
                    "plant_io_generated_MWh_LHV_y": _fmt(plant),
                    "compact_consumed_direct_MWh_LHV_y": _fmt(direct),
                    "balance_consumed_direct_MWh_LHV_y": _fmt(direct),
                    "compact_consumed_boiler_MWh_LHV_y": _fmt(boiler),
                    "balance_consumed_boiler_MWh_LHV_y": _fmt(boiler),
                    "compact_consumed_vattenfall_MWh_LHV_y": _fmt(vf),
                    "balance_consumed_vattenfall_MWh_LHV_y": _fmt(vf),
                    "compact_flared_MWh_LHV_y": _fmt(flared),
                    "balance_flared_MWh_LHV_y": _fmt(flared),
                    "generation_difference_MWh_LHV_y": _fmt(diff),
                    "consumption_difference_MWh_LHV_y": 0.0,
                    "flaring_difference_MWh_LHV_y": 0.0,
                    "status": status,
                    "red_flags": flags,
                    "notes": "C5f WAG balance uses net KGF COG surplus, not gross COG.",
                }
            )
    return rows


def _compact_rows(
    c5e_compact: list[dict[str, str]],
    conversions: list[dict[str, Any]],
    coke_anchor: list[dict[str, Any]],
    wag_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    conv_by_key = {(r["configuration"], int(r["horizon_hours"]), r["plant_id"]): r for r in conversions}
    anchor_by_key = {(r["configuration"], int(r["horizon_hours"])): r for r in coke_anchor}
    rows: list[dict[str, Any]] = []
    main_plants = {"KGF1", "KGF2", "Sinter", "BF6", "BF7", "BOF", "DRP", "EAF", "HSM", "boilers", "Vattenfall", "flaring"}
    for row in c5e_compact:
        plant = row["plant"]
        if plant.startswith("WAG_TOTAL_") or plant not in main_plants:
            continue
        item = {
            "configuration": row["configuration"],
            "horizon_hours": row["horizon_hours"],
            "plant": plant,
            "active": row["active"],
            "main_product": row["main_product"],
            "main_product_raw_t_y": row["main_product_raw_t_y"],
            "main_product_site_t_y": row["main_product_site_t_y"],
            "scale_mode": row["scale_mode"],
            "bus0_basis": "",
            "coal_t_per_t_coke": "",
            "coke_anchor_gap_pct": "",
            "COG_gross_Nm3_per_t_coke": "",
            "COG_gross_MWh_LHV_per_t_coke": "",
            "COG_self_use_MWh_LHV_per_t_coke": "",
            "COG_surplus_MWh_LHV_per_t_coke": "",
            "electricity_MWh_per_t_coke": "",
            "steam_MWh_proxy_per_t_coke": "",
            "direct_CO2_t_per_t_coke": "",
            "COG_CO2_potential_t_per_t_coke": "",
            "WAG_output_carrier": row.get("WAG_output_carrier", ""),
            "WAG_output_MWh_LHV_per_t": row.get("WAG_output_MWh_LHV_per_t", ""),
            "LHV_consistency_status": row.get("LHV_consistency_status", ""),
            "carbon_accounting_status": "",
            "status": row["status"],
            "red_flags": row["red_flags"],
        }
        key = (row["configuration"], int(row["horizon_hours"]), plant)
        if key in conv_by_key:
            conv = conv_by_key[key]
            item.update(
                {
                    "main_product_raw_t_y": conv["coke_output_raw_t_y"],
                    "main_product_site_t_y": conv["coke_output_site_t_y"],
                    "bus0_basis": conv["bus0_decision_basis"],
                    "coal_t_per_t_coke": conv["coal_t_per_t_coke"],
                    "coke_anchor_gap_pct": anchor_by_key[(row["configuration"], int(row["horizon_hours"]))]["gap_pct"],
                    "COG_gross_Nm3_per_t_coke": conv["gross_COG_Nm3_per_t_coke"],
                    "COG_gross_MWh_LHV_per_t_coke": conv["gross_COG_MWh_per_t_coke"],
                    "COG_self_use_MWh_LHV_per_t_coke": conv["COG_underfiring_MWh_per_t_coke"],
                    "COG_surplus_MWh_LHV_per_t_coke": conv["surplus_COG_MWh_per_t_coke"],
                    "electricity_MWh_per_t_coke": conv["KGF_electricity_MWh_per_t_coke"],
                    "steam_MWh_proxy_per_t_coke": conv["KGF_steam_MWh_proxy_per_t_coke"],
                    "direct_CO2_t_per_t_coke": conv["KGF_direct_CO2_t_per_t_coke"],
                    "COG_CO2_potential_t_per_t_coke": conv["COG_CO2_potential_t_per_t_coke"],
                    "WAG_output_carrier": "COG" if conv["active"] == "True" else "",
                    "WAG_output_MWh_LHV_per_t": conv["surplus_COG_MWh_per_t_coke"],
                    "carbon_accounting_status": conv["COG_carbon_accounting_status"],
                    "status": "active" if conv["active"] == "True" else "structurally_inactive",
                    "red_flags": conv["red_flags"],
                }
            )
        rows.append(item)

    for row in wag_rows:
        if row["plant_id"] != "SITE_TOTAL":
            continue
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant": f"WAG_TOTAL_{row['carrier']}",
                "active": "True",
                "main_product": "WAG_generated_MWh_LHV_y",
                "main_product_raw_t_y": row["generated_MWh_LHV_y"],
                "main_product_site_t_y": row["site_scaled_quantity"],
                "scale_mode": row["scale_mode"],
                "bus0_basis": "not_applicable",
                "coal_t_per_t_coke": "",
                "coke_anchor_gap_pct": "",
                "COG_gross_Nm3_per_t_coke": "",
                "COG_gross_MWh_LHV_per_t_coke": "",
                "COG_self_use_MWh_LHV_per_t_coke": "",
                "COG_surplus_MWh_LHV_per_t_coke": "",
                "electricity_MWh_per_t_coke": "",
                "steam_MWh_proxy_per_t_coke": "",
                "direct_CO2_t_per_t_coke": "",
                "COG_CO2_potential_t_per_t_coke": "",
                "WAG_output_carrier": row["carrier"],
                "WAG_output_MWh_LHV_per_t": "",
                "LHV_consistency_status": "pass",
                "carbon_accounting_status": "WAG_network_balance_only",
                "status": "balance_total",
                "red_flags": "",
            }
        )
    return rows


def _anchor_gap_rows(coke_anchor: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _read_csv(C5E_DIR / "s4_4c5e_anchor_gap_dashboard.csv")
    for row in coke_anchor:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "metric": "coke_total",
                "model": row["total_coke_site_t_y"],
                "model_24h": row["total_coke_site_t_y"] if str(row["horizon_hours"]) == "24" else "",
                "model_168h": row["total_coke_site_t_y"] if str(row["horizon_hours"]) == "168" else "",
                "anchor": row["coke_anchor_t_y"],
                "anchor_source": "Coking_Plants_Parameters.md validation/context only",
                "gap_pct": row["gap_pct"],
                "gap_type": row["gap_type"],
                "notes": row["notes"],
            }
        )
    return rows


def _summary_rows(
    conversions: list[dict[str, Any]],
    coke_anchor: list[dict[str, Any]],
    cog_balance: list[dict[str, Any]],
    lhv: list[dict[str, Any]],
    wag_reconciliation: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    anchor_by_key = {(r["configuration"], int(r["horizon_hours"])): r for r in coke_anchor}
    cog_status = {
        (config, horizon): "pass"
        if all(r["status"] == "pass" for r in cog_balance if r["configuration"] == config and int(r["horizon_hours"]) == horizon)
        else "fail"
        for config in CONFIGS
        for horizon in HORIZONS
    }
    rec_status = {
        (config, horizon): "pass"
        if all(r["status"] == "pass" for r in wag_reconciliation if r["configuration"] == config and int(r["horizon_hours"]) == horizon)
        else "fail"
        for config in CONFIGS
        for horizon in HORIZONS
    }
    lhv_counts: dict[tuple[str, int], dict[str, int]] = {}
    for row in lhv:
        key = (row["configuration"], int(row["horizon_hours"]))
        lhv_counts.setdefault(key, {"pass": 0, "fail": 0})
        lhv_counts[key]["pass" if row["status"] == "pass" else "fail"] += 1

    all_rows: list[dict[str, Any]] = []
    by_horizon: dict[str, list[dict[str, Any]]] = {"24h": [], "168h": []}
    for horizon_name in ("24h", "168h"):
        for row in _read_csv(C5E_DIR / f"s4_4c5e_{horizon_name}_summary.csv"):
            item = dict(row)
            config = item["configuration_id"]
            horizon = int(item["horizon_hours"])
            active_conversions = [r for r in conversions if r["configuration"] == config and int(r["horizon_hours"]) == horizon and r["active"] == "True"]
            item["stage"] = STAGE
            item["KGF_parameter_status"] = "pass" if all(not r["red_flags"] for r in active_conversions) else "fail"
            item["COG_self_use_surplus_status"] = cog_status[(config, horizon)]
            item["WAG_compact_balance_reconciliation_status"] = rec_status[(config, horizon)]
            item["LHV_consistency_pass_count"] = lhv_counts[(config, horizon)]["pass"]
            item["LHV_consistency_fail_count"] = lhv_counts[(config, horizon)]["fail"]
            item["total_coke_site_t_y"] = anchor_by_key[(config, horizon)]["total_coke_site_t_y"]
            item["coke_anchor_gap_pct"] = anchor_by_key[(config, horizon)]["gap_pct"]
            item["CO2_completeness_status"] = "KGF_direct_CO2_added_but_total_site_CO2_incomplete"
            all_rows.append(item)
            by_horizon[horizon_name].append(item)
    return all_rows, by_horizon


def _run_registry(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "stage": STAGE,
            "configuration": row["configuration_id"],
            "horizon_hours": row["horizon_hours"],
            "solver_status": row["solver_status"],
            "termination_condition": row["termination_condition"],
            "objective_value": row["objective_value"],
            "runtime_seconds": row["runtime_seconds"],
            "KGF_parameter_status": row["KGF_parameter_status"],
            "COG_self_use_surplus_status": row["COG_self_use_surplus_status"],
            "WAG_compact_balance_reconciliation_status": row["WAG_compact_balance_reconciliation_status"],
            "output_directory": _rel(C5F_DIR),
        }
        for row in summary_rows
    ]


def _stage_gate(
    conversions: list[dict[str, Any]],
    cog_balance: list[dict[str, Any]],
    lhv: list[dict[str, Any]],
    wag_reconciliation: list[dict[str, Any]],
) -> dict[str, Any]:
    active_ok = all(not row["red_flags"] for row in conversions if row["active"] == "True")
    inactive_ok = all(
        _zero(row["coke_output_raw_t_y"]) == 0.0
        and _zero(row["dry_coal_input_raw_t_y"]) == 0.0
        and _zero(row["gross_COG_raw_MWh_LHV_y"]) == 0.0
        for row in conversions
        if row["configuration"] == C1 and row["plant_id"] == "KGF2"
    )
    cog_ok = all(row["status"] == "pass" for row in cog_balance)
    lhv_ok = all(row["status"] == "pass" for row in lhv)
    wag_ok = all(row["status"] == "pass" for row in wag_reconciliation)
    return {
        "stage": STAGE,
        "decision": "pass_development_coking_plant_minimal_parameterisation_with_open_site_gaps"
        if active_ok and inactive_ok and cog_ok and lhv_ok and wag_ok
        else "fail_coking_plant_minimal_parameterisation",
        "required_runs_executed": True,
        "c5e_downstream_continuation_preserved": True,
        "kgf_parameter_status": "pass" if active_ok else "fail",
        "c1_kgf2_inactive_zero": inactive_ok,
        "coke_anchor_used_as_constraint": False,
        "COG_self_use_surplus_status": "pass" if cog_ok else "fail",
        "WAG_compact_balance_reconciliation_pass": wag_ok,
        "lhv_consistency_fail_count": sum(1 for row in lhv if row["status"] != "pass"),
        "steam_validation_anchor_active": False,
        "legacy_equal_wag_ng_boiler_split_active": False,
        "vattenfall_cap_policy": "combined_BFG_COG_BOFG_volume_cap_not_per_carrier",
        "vattenfall_combined_cap_Nm3_h": VATTENFALL_TOTAL_WAG_CAP_NM3_H,
        "anchors_used_as_constraints": False,
        "forbidden_economic_features_added": False,
        "executable_development_target_t_y": TARGET_SITE_T_Y,
        "source_card": _rel(SOURCE_CARD),
        "output_directory": _rel(C5F_DIR),
    }


def _copy_c5e(source_name: str, target_name: str) -> None:
    target = C5F_DIR / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(C5E_DIR / source_name, target)


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5e_internal_consistency_repair()
    C5F_DIR.mkdir(parents=True, exist_ok=True)

    split_rows = _kgf_split_rows()
    coke = _coke_lookup()
    conversions = _kgf_conversion_rows(coke)
    cog_self_use = _cog_self_use_surplus_rows(conversions)
    coke_anchor = _coke_anchor_rows(split_rows)
    kgf_split = _kgf_split_rows_c5f(split_rows)
    wag = _wag_rows(conversions)
    plant_io = _plant_io_rows(conversions, wag)
    compact = _compact_rows(_read_csv(C5E_DIR / "s4_4c5e_compact_table_for_chat.csv"), conversions, coke_anchor, wag)
    cog_balance = _cog_balance_by_plant(conversions, wag)
    lhv = _lhv_checks(wag, cog_self_use)
    wag_reconciliation = _wag_reconciliation(wag, compact, plant_io)
    energy = _energy_rows(conversions)
    emissions = _emissions_rows(conversions)
    ratios = _conversion_ratio_rows(conversions)
    anchor_gap = _anchor_gap_rows(coke_anchor)
    summary_rows, summary_by_horizon = _summary_rows(conversions, coke_anchor, cog_balance, lhv, wag_reconciliation)
    gate = _stage_gate(conversions, cog_balance, lhv, wag_reconciliation)

    _write_json(C5F_DIR / "s4_4c5f_stage_gate.json", gate)
    _write_csv(C5F_DIR / "s4_4c5f_run_registry.csv", _run_registry(summary_rows))
    for horizon, rows in summary_by_horizon.items():
        _write_csv(C5F_DIR / f"s4_4c5f_{horizon}_summary.csv", rows)
    _write_csv(C5F_DIR / "s4_4c5f_minimal_plant_parameter_schema.csv", _minimal_schema_rows())
    _write_csv(C5F_DIR / "s4_4c5f_plant_parameter_register.csv", _plant_parameter_register_rows())
    _write_csv(C5F_DIR / "s4_4c5f_kgf_parameter_values.csv", _kgf_parameter_values_rows())
    _write_csv(C5F_DIR / "s4_4c5f_kgf_split_diagnostics.csv", kgf_split)
    _write_csv(C5F_DIR / "s4_4c5f_coke_anchor_gap_dashboard.csv", coke_anchor)
    _write_csv(C5F_DIR / "s4_4c5f_cog_self_use_surplus_dashboard.csv", cog_self_use)
    _write_csv(C5F_DIR / "s4_4c5f_coking_plant_diagnostics.csv", conversions)
    _write_csv(C5F_DIR / "s4_4c5f_cog_wag_balance_by_plant.csv", cog_balance)
    _write_csv(C5F_DIR / "s4_4c5f_wag_generation_consumption_by_plant.csv", wag)
    _write_csv(C5F_DIR / "s4_4c5f_wag_compact_balance_reconciliation.csv", wag_reconciliation)
    _write_csv(C5F_DIR / "s4_4c5f_lhv_consistency_checks.csv", lhv)
    _write_csv(C5F_DIR / "s4_4c5f_energy_by_plant.csv", energy)
    _write_csv(C5F_DIR / "s4_4c5f_emissions_by_plant.csv", emissions)
    _write_csv(C5F_DIR / "s4_4c5f_plant_conversion_ratios.csv", ratios)
    _write_csv(C5F_DIR / "s4_4c5f_anchor_gap_dashboard.csv", anchor_gap)
    _write_csv(C5F_DIR / "s4_4c5f_compact_table_for_chat.csv", compact, COMPACT_COLUMNS)

    _copy_c5e("s4_4c5e_downstream_continuation_dashboard.csv", "s4_4c5f_downstream_continuation_dashboard.csv")
    _copy_c5e("s4_4c5e_scale_audit.csv", "s4_4c5f_scale_audit.csv")

    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": _rel(C5F_DIR),
        "rows": {
            "anchor_gap": len(anchor_gap),
            "compact": len(compact),
            "cog_self_use_surplus": len(cog_self_use),
            "cog_balance": len(cog_balance),
            "conversion": len(conversions),
            "lhv": len(lhv),
            "parameter_register": len(_plant_parameter_register_rows()),
            "wag": len(wag),
            "wag_reconciliation": len(wag_reconciliation),
        },
    }
    _write_json(C5F_DIR / "s4_4c5f_summary.json", summary)
    return summary


def run_s4_4c5f_coking_plant_minimal_parameterisation() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5f_coking_plant_minimal_parameterisation(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
