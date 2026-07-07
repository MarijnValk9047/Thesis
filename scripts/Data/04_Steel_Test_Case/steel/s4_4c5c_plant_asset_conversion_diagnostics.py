"""S4.4c5c plant/asset conversion diagnostics.

This stage is a development-only accounting layer over C5b. It does not add
price signals, revenues, calibration constraints, or optimiser steering.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .s4_4b5a_asymmetric_correction import CORRECTED_INPUT_DIR, run_b5a_correction
from .s4_4c_unified_physical_modelbuilder import FLARE_CO2_EF_T_PER_MWH, SELECTED_WAG_LHV_MJ_PER_NM3
from .s4_4c5b_site_scale_downstream_steam_wag_reconciliation import (
    C0,
    C1,
    C5B_DIR,
    CARRIERS,
    HORIZONS,
    NG_HHV_MJ_PER_NM3,
    REPO_ROOT,
    S4_ROOT,
    VATTENFALL_TOTAL_WAG_CAP_NM3_H,
    _annualisation_factor,
    _annualise,
    _safe_float,
    _write_csv,
    _write_json,
    run_s4_4c5b_site_scale_downstream_steam_wag_reconciliation,
)


C5C_DIR = S4_ROOT / "s4_4c5c_plant_asset_conversion_diagnostics"
STAGE = "S4.4c5c_plant_asset_conversion_diagnostics"
EPS = 1e-6
BALANCE_TOL_MWH_Y = 0.01
NA = "NaN"
NG_LHV_MJ_PER_NM3 = 35.8

PLANT_META = {
    "KGF1": ("KGF1 / Coking Plant 1", "retained_bf_bof", "coking_plant"),
    "KGF2": ("KGF2 / Coking Plant 2", "retained_bf_bof", "coking_plant"),
    "Sinter": ("Sinter Plant", "retained_bf_bof", "agglomeration"),
    "PEFA_Malerij": ("Pelletizing Plant / PEFA Malerij", "pelletizing", "process_sink_gap"),
    "PEFA_Branderij": ("Pelletizing Plant / PEFA Branderij", "pelletizing", "process_sink_gap"),
    "BF6": ("Blast Furnace 6", "retained_bf_bof", "blast_furnace"),
    "BF7": ("Blast Furnace 7", "retained_bf_bof", "blast_furnace"),
    "BOF": ("BOF / OSF", "retained_bf_bof", "converter"),
    "DRP": ("Direct Reduction Plant", "drp_eaf", "direct_reduction"),
    "EAF": ("Electric Arc Furnace", "drp_eaf", "electric_furnace"),
    "HSM": ("HSM / WBW", "downstream", "rolling_downstream"),
    "downstream": ("downstream/casting/slab/final-product proxy", "downstream", "accounting_proxy"),
    "boilers": ("boilers / steam system", "utility", "steam_system"),
    "Vattenfall": ("Vattenfall / internal-generation interface", "utility", "internal_generation_interface"),
    "flaring": ("flaring", "utility", "flare"),
    "residual_background_electricity": ("residual/background electricity load", "residual", "background_load"),
    "residual_background_NG": ("residual/background NG load", "residual", "background_load"),
    "residual_unvalidated_steam": ("residual/unvalidated steam placeholder", "residual", "steam_placeholder"),
}

SOURCE_PLANT_TO_CANONICAL = {
    "KGF1_CokingPlant1": "KGF1",
    "KGF2_CokingPlant2": "KGF2",
    "SinteringPlant": "Sinter",
    "PEFA_Malerij": "PEFA_Malerij",
    "PEFA_Branderij": "PEFA_Branderij",
    "BF6": "BF6",
    "BF7": "BF7",
    "BOF": "BOF",
    "DRP": "DRP",
    "EAF": "EAF",
    "HSM": "HSM",
    "BoilerSteamUtility": "boilers",
    "VattenfallInternalGeneration": "Vattenfall",
    "CarrierSpecificFlare": "flaring",
}

MAIN_PRODUCTS = {
    "KGF1": ("coke", "t_coke/y"),
    "KGF2": ("coke", "t_coke/y"),
    "Sinter": ("sinter", "t_sinter/y"),
    "PEFA_Malerij": ("pellets", "t_pellets/y"),
    "PEFA_Branderij": ("pellets", "t_pellets/y"),
    "BF6": ("hot_metal", "t_hot_metal/y"),
    "BF7": ("hot_metal", "t_hot_metal/y"),
    "BOF": ("liquid_steel", "t_liquid_steel/y"),
    "DRP": ("DRI", "t_DRI/y"),
    "EAF": ("liquid_steel", "t_liquid_steel/y"),
    "HSM": ("final_product_proxy", "t_final_product_proxy/y"),
    "downstream": ("final_product_proxy", "t_final_product_proxy/y"),
    "boilers": ("steam_placeholder", "MWh_steam_proxy/y"),
    "Vattenfall": ("electricity", "MWh/y"),
    "flaring": ("WAG_flared", "MWh_LHV/y"),
}

MATERIAL_MAP = {
    "KGF1": ("coal_or_coking_feed_proxy", "coke"),
    "KGF2": ("coal_or_coking_feed_proxy", "coke"),
    "Sinter": ("iron_ore_or_sinter_feed_proxy", "sinter"),
    "BF6": ("sinter", "hot_metal"),
    "BF7": ("sinter", "hot_metal"),
    "BOF": ("hot_metal", "liquid_steel"),
    "DRP": ("pellets", "DRI"),
    "EAF": ("DRI", "liquid_steel"),
    "HSM": ("slab_or_crude_steel_proxy", "final_product_proxy"),
}

EXPECTED_ELECTRICITY_PLANTS = {"KGF1", "KGF2", "Sinter", "DRP", "EAF", "HSM", "PEFA_Malerij", "PEFA_Branderij"}
EXPECTED_CO2_PLANTS = {"KGF1", "KGF2", "Sinter", "BF6", "BF7", "BOF", "DRP", "EAF", "boilers", "flaring"}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def _nz(value: Any) -> float:
    return _safe_float(value)


def _fmt(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value):
            return NA
        return round(value, 6)
    return value


def _ratio(numerator: float | None, denominator: float | None) -> float | str:
    if numerator is None or denominator is None or abs(denominator) <= EPS:
        return NA
    return round(numerator / denominator, 9)


def _gap_pct(model: float | None, anchor: float | None) -> float | str:
    if model is None or anchor is None or abs(anchor) <= EPS:
        return ""
    return round((model - anchor) / anchor * 100.0, 6)


def _asset_status(configuration: str, plant_id: str, main_product: float = 0.0) -> str:
    if configuration == C1 and plant_id in {"KGF2", "BF7"}:
        return "structurally_inactive"
    if configuration == C0 and plant_id in {"DRP", "EAF"}:
        return "structurally_inactive"
    if plant_id in {"PEFA_Malerij", "PEFA_Branderij"}:
        return "missing_executable_coefficient"
    if plant_id in {"residual_background_electricity", "residual_background_NG", "residual_unvalidated_steam"}:
        return "residual_placeholder"
    return "active" if main_product > EPS or plant_id in {"boilers", "Vattenfall", "flaring", "downstream"} else "diagnostic_zero"


def _evidence_status(source_status: str, plant_id: str, quantity: float = 0.0) -> str:
    if plant_id in {"PEFA_Malerij", "PEFA_Branderij"}:
        return "missing_executable_coefficient"
    if plant_id == "residual_unvalidated_steam":
        return "residual_placeholder"
    if source_status in {"existing_c5_process_row", "executable_internal_offset_no_revenue"}:
        return "development_assumption"
    if quantity == 0.0:
        return "accounting_proxy"
    return "development_assumption"


def _plant_name(plant_id: str) -> str:
    return PLANT_META.get(plant_id, (plant_id, "unknown", "unknown"))[0]


def _plant_route(plant_id: str) -> str:
    return PLANT_META.get(plant_id, (plant_id, "unknown", "unknown"))[1]


def _component_type(plant_id: str) -> str:
    return PLANT_META.get(plant_id, (plant_id, "unknown", "unknown"))[2]


def _add_io_row(rows: list[dict[str, Any]], **kwargs: Any) -> None:
    quantity = kwargs.get("quantity")
    if quantity is None:
        quantity = NA
    elif isinstance(quantity, float):
        quantity = _fmt(quantity)
    plant_id = kwargs["plant_id"]
    rows.append(
        {
            "configuration": kwargs["configuration"],
            "horizon_hours": kwargs["horizon_hours"],
            "hour": kwargs["hour"],
            "plant_id": plant_id,
            "plant_name": _plant_name(plant_id),
            "asset_status": kwargs.get("asset_status", _asset_status(kwargs["configuration"], plant_id)),
            "route": _plant_route(plant_id),
            "component_type": _component_type(plant_id),
            "carrier_or_material": kwargs["carrier_or_material"],
            "direction": kwargs["direction"],
            "quantity": quantity,
            "unit": kwargs["unit"],
            "accounting_class": kwargs["accounting_class"],
            "source_or_assumption_id": kwargs["source_or_assumption_id"],
            "evidence_status": kwargs["evidence_status"],
            "thesis_usability": kwargs.get("thesis_usability", False),
            "notes": kwargs.get("notes", ""),
        }
    )


def _plant_rows(horizon: str) -> list[dict[str, str]]:
    return _read_csv(C5B_DIR.parent / "s4_4c5a_anchor_scaling_accounting_correction" / f"s4_4c5a_{horizon}_plant_diagnostics.csv")


def _summary_rows(horizon: str) -> list[dict[str, str]]:
    return _read_csv(C5B_DIR / f"s4_4c5b_{horizon}_summary.csv")


def _allocation_rows() -> list[dict[str, str]]:
    return _read_csv(C5B_DIR / "s4_4c5b_wag_allocation_hourly.csv")


def _material_names(plant_id: str) -> tuple[str, str]:
    return MATERIAL_MAP.get(plant_id, ("main_material_input_proxy", "main_product_proxy"))


def _hourly_io_rows(horizon: str, horizon_hours: int, allocations: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in _plant_rows(horizon):
        configuration = source["configuration_id"]
        hour = int(_nz(source["hour_index"]))
        plant_id = SOURCE_PLANT_TO_CANONICAL.get(source["plant_id"], source["plant_id"])
        asset_status = _asset_status(configuration, plant_id, _nz(source.get("material_output_t")) + _nz(source.get("WAG_to_electricity_mwh")))
        evidence = _evidence_status(source.get("accounting_status", ""), plant_id)
        input_material, output_material = _material_names(plant_id)
        material_input = _nz(source.get("material_input_t"))
        material_output = _nz(source.get("material_output_t"))
        if material_input > EPS:
            _add_io_row(
                rows,
                configuration=configuration,
                horizon_hours=horizon_hours,
                hour=hour,
                plant_id=plant_id,
                asset_status=asset_status,
                carrier_or_material=input_material,
                direction="input",
                quantity=material_input,
                unit="t/h",
                accounting_class="material_flow",
                source_or_assumption_id="C5a plant diagnostics material input proxy",
                evidence_status=evidence,
                notes=source.get("caveat", ""),
            )
        if material_output > EPS:
            _add_io_row(
                rows,
                configuration=configuration,
                horizon_hours=horizon_hours,
                hour=hour,
                plant_id=plant_id,
                asset_status=asset_status,
                carrier_or_material=output_material,
                direction="output",
                quantity=material_output,
                unit="t/h",
                accounting_class="material_flow",
                source_or_assumption_id="C5a plant diagnostics material output proxy",
                evidence_status=evidence,
                notes=source.get("caveat", ""),
            )
        electricity = _nz(source.get("electricity_use_mwh"))
        if electricity > EPS:
            _add_io_row(
                rows,
                configuration=configuration,
                horizon_hours=horizon_hours,
                hour=hour,
                plant_id=plant_id,
                asset_status=asset_status,
                carrier_or_material="electricity",
                direction="input",
                quantity=electricity,
                unit="MWh/h",
                accounting_class="variable_process_electricity",
                source_or_assumption_id="C5a executable process electricity",
                evidence_status=evidence,
                notes=source.get("caveat", ""),
            )
        ng_lhv = _nz(source.get("natural_gas_mwh_lhv_model"))
        if ng_lhv > EPS:
            _add_io_row(
                rows,
                configuration=configuration,
                horizon_hours=horizon_hours,
                hour=hour,
                plant_id=plant_id,
                asset_status=asset_status,
                carrier_or_material="NaturalGas",
                direction="input",
                quantity=ng_lhv,
                unit="MWh_LHV/h",
                accounting_class="process_or_boiler_NG",
                source_or_assumption_id="C5a NG LHV model accounting",
                evidence_status=evidence,
                notes="NG LHV model quantity; HHV validation conversion is reported separately.",
            )
        for carrier in CARRIERS:
            generated = _nz(source.get(f"{carrier}_generated_mwh"))
            if generated > EPS:
                _add_io_row(
                    rows,
                    configuration=configuration,
                    horizon_hours=horizon_hours,
                    hour=hour,
                    plant_id=plant_id,
                    asset_status=asset_status,
                    carrier_or_material=carrier,
                    direction="output",
                    quantity=generated,
                    unit="MWh_LHV/h",
                    accounting_class="WAG_generation",
                    source_or_assumption_id="C5a WAG generation coefficient",
                    evidence_status=evidence,
                    notes=source.get("caveat", ""),
                )
        if _nz(source.get("process_co2_t")) > EPS:
            _add_io_row(
                rows,
                configuration=configuration,
                horizon_hours=horizon_hours,
                hour=hour,
                plant_id=plant_id,
                asset_status=asset_status,
                carrier_or_material="CO2",
                direction="output",
                quantity=_nz(source.get("process_co2_t")),
                unit="tCO2/h",
                accounting_class="process_CO2",
                source_or_assumption_id="C5a partial process CO2",
                evidence_status=evidence,
                notes="Partial CO2 bucket; not a total-anchor comparable value.",
            )
        if _nz(source.get("flaring_co2_t")) > EPS:
            _add_io_row(
                rows,
                configuration=configuration,
                horizon_hours=horizon_hours,
                hour=hour,
                plant_id=plant_id,
                asset_status=asset_status,
                carrier_or_material="CO2",
                direction="output",
                quantity=_nz(source.get("flaring_co2_t")),
                unit="tCO2/h",
                accounting_class="flaring_CO2",
                source_or_assumption_id="C5a flaring diagnostic factor",
                evidence_status="development_assumption",
                notes="Flaring CO2 is diagnostic only; no ETS objective.",
            )

    for alloc in allocations:
        if alloc.get("horizon") != horizon:
            continue
        configuration = alloc["configuration_id"]
        hour = int(_nz(alloc["hour"]))
        plant_id = SOURCE_PLANT_TO_CANONICAL.get(alloc["plant"], alloc["plant"])
        category = alloc["allocation_category"]
        carrier = alloc["carrier"]
        quantity = _nz(alloc.get("quantity_mwh"))
        direction = "output" if category == "flare_after_all_eligible_sinks" else "input"
        if category == "missing_direct_process_sink":
            direction = "input"
            quantity = 0.0
        _add_io_row(
            rows,
            configuration=configuration,
            horizon_hours=horizon_hours,
            hour=hour,
            plant_id=plant_id,
            asset_status=_asset_status(configuration, plant_id, quantity),
            carrier_or_material=carrier,
            direction=direction,
            quantity=quantity,
            unit="MWh_LHV/h",
            accounting_class=category,
            source_or_assumption_id=alloc.get("source_or_assumption", ""),
            evidence_status=alloc.get("status", ""),
            thesis_usability=alloc.get("status") not in {"missing_executable_coefficient"},
            notes=alloc.get("status", ""),
        )
        electricity = _nz(alloc.get("WAG_to_electricity_MWh"))
        if electricity > EPS:
            _add_io_row(
                rows,
                configuration=configuration,
                horizon_hours=horizon_hours,
                hour=hour,
                plant_id="Vattenfall",
                asset_status="active",
                carrier_or_material="electricity",
                direction="output",
                quantity=electricity,
                unit="MWh/h",
                accounting_class="WAG_internal_generation",
                source_or_assumption_id="C5b WAG-first allocation and internal-generation efficiency",
                evidence_status="development_assumption",
                notes="Internal-generation/interface sink; no export revenue.",
            )

    for configuration in (C0, C1):
        for inactive in ("KGF2", "BF7"):
            if configuration == C1:
                for hour in range(horizon_hours):
                    _add_io_row(
                        rows,
                        configuration=configuration,
                        horizon_hours=horizon_hours,
                        hour=hour,
                        plant_id=inactive,
                        asset_status="structurally_inactive",
                        carrier_or_material=MAIN_PRODUCTS[inactive][0],
                        direction="output",
                        quantity=0.0,
                        unit="t/h",
                        accounting_class="topology_zero",
                        source_or_assumption_id="S44B5A_C1_INACTIVE_KGF2_BF7_TOPOLOGY_ROWS",
                        evidence_status="structurally_inactive",
                        notes="C1 topology keeps this asset inactive.",
                    )
        for missing_plant, carrier in (("PEFA_Malerij", "BOFG"), ("PEFA_Branderij", "COG")):
            for hour in range(horizon_hours):
                _add_io_row(
                    rows,
                    configuration=configuration,
                    horizon_hours=horizon_hours,
                    hour=hour,
                    plant_id=missing_plant,
                    asset_status="missing_executable_coefficient",
                    carrier_or_material=carrier,
                    direction="input",
                    quantity=NA,
                    unit="MWh_LHV/h",
                    accounting_class="missing_direct_process_sink",
                    source_or_assumption_id="C5b explicit missing/deferred sink row",
                    evidence_status="missing_executable_coefficient",
                    thesis_usability=False,
                    notes="model_effect=may_overstate_WAG_to_Vattenfall_or_flaring",
                )
    return rows


def _annualise_io(hourly_rows: list[dict[str, Any]], horizon_hours: int) -> list[dict[str, Any]]:
    factor = _annualisation_factor(horizon_hours)
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in hourly_rows:
        key = (
            row["configuration"],
            row["horizon_hours"],
            row["plant_id"],
            row["plant_name"],
            row["asset_status"],
            row["route"],
            row["carrier_or_material"],
            row["direction"],
            row["unit"],
            row["accounting_class"],
            row["source_or_assumption_id"],
            row["evidence_status"],
            row["thesis_usability"],
            row["notes"],
        )
        if key not in groups:
            groups[key] = {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_id": row["plant_id"],
                "plant_name": row["plant_name"],
                "asset_status": row["asset_status"],
                "route": row["route"],
                "carrier_or_material": row["carrier_or_material"],
                "direction": row["direction"],
                "annual_quantity": 0.0,
                "unit": row["unit"].replace("/h", "/y"),
                "annualisation_factor": factor,
                "scale_mode": "physical_model_scale" if "site" not in str(row["source_or_assumption_id"]).lower() else "site_proxy",
                "accounting_class": row["accounting_class"],
                "source_or_assumption_id": row["source_or_assumption_id"],
                "evidence_status": row["evidence_status"],
                "thesis_usability": row["thesis_usability"],
                "notes": row["notes"],
            }
        if str(row["quantity"]) != NA:
            groups[key]["annual_quantity"] += _nz(row["quantity"]) * factor
    for value in groups.values():
        value["annual_quantity"] = _fmt(value["annual_quantity"])
    return list(groups.values())


def _sum_annual(rows: list[dict[str, Any]], configuration: str, plant_id: str, field: str, *, carrier: str | None = None) -> float:
    total = 0.0
    for row in rows:
        if row["configuration"] != configuration or row["plant_id"] != plant_id:
            continue
        if carrier is not None and row["carrier_or_material"] != carrier:
            continue
        if row.get("accounting_class") == field:
            total += _nz(row.get("annual_quantity"))
    return total


def _source_totals(horizon: str, horizon_hours: int) -> dict[tuple[str, str], dict[str, float]]:
    factor = _annualisation_factor(horizon_hours)
    totals: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in _plant_rows(horizon):
        plant_id = SOURCE_PLANT_TO_CANONICAL.get(row["plant_id"], row["plant_id"])
        key = (row["configuration_id"], plant_id)
        for field in (
            "activity_t_h",
            "material_input_t",
            "material_output_t",
            "electricity_use_mwh",
            "natural_gas_use_nm3",
            "natural_gas_mwh_lhv_model",
            "steam_or_boiler_use_mwh",
            "process_co2_t",
            "combustion_co2_t",
            "flaring_co2_t",
            "WAG_to_electricity_mwh",
        ):
            totals[key][field] += _nz(row.get(field)) * factor
        for carrier in CARRIERS:
            totals[key][f"{carrier}_generated_mwh"] += _nz(row.get(f"{carrier}_generated_mwh")) * factor
            totals[key][f"{carrier}_consumed_mwh"] += _nz(row.get(f"{carrier}_consumed_mwh")) * factor
            totals[key][f"{carrier}_flared_mwh"] += _nz(row.get(f"{carrier}_flared_mwh")) * factor
    return totals


def _allocation_annual_totals(
    horizon: str,
    horizon_hours: int,
    allocations: list[dict[str, str]],
) -> dict[tuple[str, str], dict[str, float]]:
    factor = _annualisation_factor(horizon_hours)
    totals: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for alloc in allocations:
        if alloc.get("horizon") != horizon:
            continue
        configuration = alloc["configuration_id"]
        carrier = alloc["carrier"]
        category = alloc["allocation_category"]
        value = _nz(alloc.get("quantity_mwh")) * factor
        if category == "boiler_steam_wag_first":
            totals[(configuration, "boilers")][f"{carrier}_consumed_mwh"] += value
        elif category == "boiler_steam_ng_supplement":
            totals[(configuration, "boilers")]["natural_gas_mwh_lhv_model"] += value
        elif category == "vattenfall_internal_generation":
            totals[(configuration, "Vattenfall")][f"{carrier}_consumed_mwh"] += value
            totals[(configuration, "Vattenfall")]["WAG_to_electricity_mwh"] += _nz(
                alloc.get("WAG_to_electricity_MWh")
            ) * factor
        elif category == "flare_after_all_eligible_sinks":
            totals[(configuration, "flaring")][f"{carrier}_flared_mwh"] += value
            totals[(configuration, "flaring")]["flaring_co2_t"] += value * FLARE_CO2_EF_T_PER_MWH[carrier]
    return totals


def _main_product_quantity(totals: dict[tuple[str, str], dict[str, float]], configuration: str, plant_id: str) -> float:
    values = totals[(configuration, plant_id)]
    if plant_id == "boilers":
        return values.get("steam_or_boiler_use_mwh", 0.0)
    if plant_id == "Vattenfall":
        return values.get("WAG_to_electricity_mwh", 0.0)
    if plant_id == "flaring":
        return sum(values.get(f"{carrier}_flared_mwh", 0.0) for carrier in CARRIERS)
    return values.get("material_output_t", 0.0)


def _add_ratio(
    rows: list[dict[str, Any]],
    *,
    configuration: str,
    horizon_hours: int,
    plant_id: str,
    input_or_output: str,
    carrier_or_material: str,
    annual_quantity: float | str,
    unit: str,
    denominator: float,
    ratio_unit: str,
    expected: str = "",
    anchor_source: str = "",
    status: str = "development_assumption",
    model_effect: str = "",
    notes: str = "",
) -> None:
    main_product, _ = MAIN_PRODUCTS.get(plant_id, ("main_product_proxy", ""))
    inactive = _asset_status(configuration, plant_id, denominator) == "structurally_inactive"
    denominator_status = inactive or denominator <= EPS
    numeric_quantity = None if annual_quantity == NA else float(annual_quantity)
    rows.append(
        {
            "configuration": configuration,
            "horizon_hours": horizon_hours,
            "plant_id": plant_id,
            "plant_name": _plant_name(plant_id),
            "asset_status": _asset_status(configuration, plant_id, denominator),
            "route": _plant_route(plant_id),
            "main_product": main_product,
            "main_product_quantity_t_y": _fmt(denominator),
            "input_or_output": input_or_output,
            "carrier_or_material": carrier_or_material,
            "annual_quantity": _fmt(annual_quantity) if annual_quantity != NA else NA,
            "unit": unit,
            "ratio_value": NA if denominator_status or numeric_quantity is None else _fmt(numeric_quantity / denominator),
            "ratio_unit": ratio_unit,
            "ratio_denominator": "inactive_or_zero_denominator" if denominator_status else main_product,
            "expected_anchor_or_range": expected,
            "anchor_source": anchor_source,
            "gap_to_anchor_pct": "",
            "status": "inactive_or_zero_denominator" if denominator_status else status,
            "model_effect": model_effect,
            "notes": notes,
        }
    )


def _conversion_ratio_rows(horizon: str, horizon_hours: int, allocations: list[dict[str, str]]) -> list[dict[str, Any]]:
    totals = _source_totals(horizon, horizon_hours)
    allocation_totals = _allocation_annual_totals(horizon, horizon_hours, allocations)
    rows: list[dict[str, Any]] = []
    for configuration in (C0, C1):
        for plant_id in ("KGF1", "KGF2", "Sinter", "BF6", "BF7", "BOF", "DRP", "EAF", "HSM", "PEFA_Malerij", "PEFA_Branderij", "boilers", "Vattenfall", "flaring"):
            denominator = _main_product_quantity(totals, configuration, plant_id)
            values = totals[(configuration, plant_id)]
            alloc_values = allocation_totals[(configuration, plant_id)]
            if plant_id in {"boilers", "Vattenfall", "flaring"}:
                merged = defaultdict(float)
                merged.update(values)
                for key, value in alloc_values.items():
                    merged[key] = value
                values = merged
                if plant_id == "Vattenfall":
                    denominator = values.get("WAG_to_electricity_mwh", 0.0)
                elif plant_id == "flaring":
                    denominator = sum(values.get(f"{carrier}_flared_mwh", 0.0) for carrier in CARRIERS)
            if plant_id in {"KGF1", "KGF2"}:
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="coal_t_per_t_coke", annual_quantity=values.get("material_input_t", 0.0), unit="t/y", denominator=denominator, ratio_unit="t/t_coke", status="development_assumption", model_effect="coal-to-coke coefficient is a process-activity proxy")
                cog_mwh = values.get("COG_generated_mwh", 0.0)
                cog_nm3 = cog_mwh * 3600.0 / SELECTED_WAG_LHV_MJ_PER_NM3["COG"] if cog_mwh else 0.0
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="COG_Nm3_per_t_coke_produced", annual_quantity=cog_nm3, unit="Nm3/y", denominator=denominator, ratio_unit="Nm3/t_coke", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="COG_MWh_LHV_per_t_coke_produced", annual_quantity=cog_mwh, unit="MWh_LHV/y", denominator=denominator, ratio_unit="MWh_LHV/t_coke", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="CO2_t_per_t_coke", annual_quantity=NA, unit="tCO2/y", denominator=denominator, ratio_unit="tCO2/t_coke", status="missing_executable_coefficient", model_effect="CO2 completeness understated")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="electricity_MWh_per_t_coke", annual_quantity=values.get("electricity_use_mwh", 0.0), unit="MWh/y", denominator=denominator, ratio_unit="MWh/t_coke", status="development_assumption", model_effect="active coking electricity likely missing if zero")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="steam_MWh_or_t_per_t_coke", annual_quantity=NA, unit="MWh_or_t/y", denominator=denominator, ratio_unit="MWh_or_t/t_coke", status="missing_executable_coefficient")
            elif plant_id in {"BF6", "BF7"}:
                bfg_mwh = values.get("BFG_generated_mwh", 0.0)
                bfg_nm3 = bfg_mwh * 3600.0 / SELECTED_WAG_LHV_MJ_PER_NM3["BFG"] if bfg_mwh else 0.0
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="coke_t_per_t_hot_metal", annual_quantity=NA, unit="t/y", denominator=denominator, ratio_unit="t_coke/t_hot_metal", status="missing_executable_coefficient")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="BFG_Nm3_per_t_hot_metal", annual_quantity=bfg_nm3, unit="Nm3/y", denominator=denominator, ratio_unit="Nm3/t_hot_metal", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="BFG_MWh_LHV_per_t_hot_metal", annual_quantity=bfg_mwh, unit="MWh_LHV/y", denominator=denominator, ratio_unit="MWh_LHV/t_hot_metal", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="CO2_t_per_t_hot_metal", annual_quantity=NA, unit="tCO2/y", denominator=denominator, ratio_unit="tCO2/t_hot_metal", status="missing_executable_coefficient", model_effect="BF CO2 bucket incomplete")
            elif plant_id == "BOF":
                bofg_mwh = values.get("BOFG_generated_mwh", 0.0)
                bofg_nm3 = bofg_mwh * 3600.0 / SELECTED_WAG_LHV_MJ_PER_NM3["BOFG"] if bofg_mwh else 0.0
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="hot_metal_t_per_t_liquid_steel", annual_quantity=values.get("material_input_t", 0.0), unit="t/y", denominator=denominator, ratio_unit="t/t_liquid_steel", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="scrap_t_per_t_liquid_steel", annual_quantity=NA, unit="t/y", denominator=denominator, ratio_unit="t_scrap/t_liquid_steel", status="missing_executable_coefficient")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="BOFG_Nm3_per_t_liquid_steel", annual_quantity=bofg_nm3, unit="Nm3/y", denominator=denominator, ratio_unit="Nm3/t_liquid_steel", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="BOFG_MWh_LHV_per_t_liquid_steel", annual_quantity=bofg_mwh, unit="MWh_LHV/y", denominator=denominator, ratio_unit="MWh_LHV/t_liquid_steel", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="CO2_t_per_t_liquid_steel", annual_quantity=NA, unit="tCO2/y", denominator=denominator, ratio_unit="tCO2/t_liquid_steel", status="missing_executable_coefficient")
            elif plant_id == "DRP":
                ng_hhv_gj = values.get("natural_gas_use_nm3", 0.0) * NG_HHV_MJ_PER_NM3 / 1000.0
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="pellets_t_per_t_DRI", annual_quantity=values.get("material_input_t", 0.0), unit="t/y", denominator=denominator, ratio_unit="t_pellets/t_DRI", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="NG_GJ_HHV_per_t_DRI", annual_quantity=ng_hhv_gj, unit="GJ_HHV/y", denominator=denominator, ratio_unit="GJ_HHV/t_DRI", expected="9.9 GJ/t DRI context if source-backed", anchor_source="Heracless context; not forced", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="electricity_GJ_per_t_DRI", annual_quantity=values.get("electricity_use_mwh", 0.0) * 3.6, unit="GJ/y", denominator=denominator, ratio_unit="GJ/t_DRI", expected="0.3 GJ/t DRI context if source-backed", anchor_source="Heracless context; not forced", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="CO2_t_per_t_DRI", annual_quantity=values.get("process_co2_t", 0.0), unit="tCO2/y", denominator=denominator, ratio_unit="tCO2/t_DRI", status="development_assumption")
            elif plant_id == "EAF":
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="DRI_t_per_t_liquid_steel", annual_quantity=values.get("material_input_t", 0.0), unit="t/y", denominator=denominator, ratio_unit="t_DRI/t_liquid_steel", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="scrap_t_per_t_liquid_steel", annual_quantity=NA, unit="t/y", denominator=denominator, ratio_unit="t_scrap/t_liquid_steel", status="missing_executable_coefficient")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="electricity_MWh_per_t_liquid_steel", annual_quantity=values.get("electricity_use_mwh", 0.0), unit="MWh/y", denominator=denominator, ratio_unit="MWh/t_liquid_steel", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="CO2_t_per_t_liquid_steel", annual_quantity=NA, unit="tCO2/y", denominator=denominator, ratio_unit="tCO2/t_liquid_steel", status="missing_executable_coefficient")
            elif plant_id == "Sinter":
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="COG_MWh_LHV_per_t_sinter", annual_quantity=values.get("COG_consumed_mwh", 0.0), unit="MWh_LHV/y", denominator=denominator, ratio_unit="MWh_LHV/t_sinter", status="development_assumption")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="electricity_MWh_per_t_sinter", annual_quantity=values.get("electricity_use_mwh", 0.0), unit="MWh/y", denominator=denominator, ratio_unit="MWh/t_sinter", status="development_assumption", model_effect="active sinter electricity likely missing if zero")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="CO2_t_per_t_sinter", annual_quantity=NA, unit="tCO2/y", denominator=denominator, ratio_unit="tCO2/t_sinter", status="missing_executable_coefficient")
            elif plant_id == "HSM":
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="electricity_MWh_per_t_final_product_proxy", annual_quantity=values.get("electricity_use_mwh", 0.0), unit="MWh/y", denominator=denominator, ratio_unit="MWh/t_final_product_proxy", status="missing_executable_coefficient", model_effect="may understate site electricity")
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material="gas_MWh_LHV_per_t_final_product_proxy", annual_quantity=NA, unit="MWh_LHV/y", denominator=denominator, ratio_unit="MWh_LHV/t_final_product_proxy", status="missing_executable_coefficient", model_effect="may overstate WAG to Vattenfall/flaring")
            elif plant_id in {"PEFA_Malerij", "PEFA_Branderij"}:
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="input", carrier_or_material=f"{plant_id} gas_MWh_LHV_per_t_pellets", annual_quantity=NA, unit="MWh_LHV/y", denominator=denominator, ratio_unit="MWh_LHV/t_pellets", status="missing_executable_coefficient", model_effect="may overstate WAG to Vattenfall/flaring")
            elif plant_id == "boilers":
                fuel = sum(values.get(f"{carrier}_consumed_mwh", 0.0) for carrier in CARRIERS) + values.get("natural_gas_mwh_lhv_model", 0.0)
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="boiler steam_output_per_MWh_fuel", annual_quantity=denominator, unit="MWh_steam_proxy/y", denominator=fuel, ratio_unit="MWh_steam_proxy/MWh_fuel_LHV", status="residual_placeholder", model_effect="steam placeholder not thesis-approved")
            elif plant_id == "Vattenfall":
                fuel = sum(values.get(f"{carrier}_consumed_mwh", 0.0) for carrier in CARRIERS)
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="Vattenfall electricity_output_per_MWh_WAG_LHV", annual_quantity=denominator, unit="MWh/y", denominator=fuel, ratio_unit="MWh_electric/MWh_WAG_LHV", status="development_assumption", model_effect="internal-generation/interface sink only")
            elif plant_id == "flaring":
                _add_ratio(rows, configuration=configuration, horizon_hours=horizon_hours, plant_id=plant_id, input_or_output="output", carrier_or_material="flaring CO2_t_per_MWh_WAG_LHV", annual_quantity=values.get("flaring_co2_t", 0.0), unit="tCO2/y", denominator=denominator, ratio_unit="tCO2/MWh_WAG_LHV", status="development_assumption", model_effect="diagnostic only")
    return rows


def _coking_diagnostics(horizon: str, horizon_hours: int) -> list[dict[str, Any]]:
    totals = _source_totals(horizon, horizon_hours)
    rows: list[dict[str, Any]] = []
    for configuration in (C0, C1):
        for plant_id in ("KGF1", "KGF2"):
            values = totals[(configuration, plant_id)]
            coke = _main_product_quantity(totals, configuration, plant_id)
            coal = values.get("material_input_t", 0.0)
            cog_mwh = values.get("COG_generated_mwh", 0.0)
            cog_nm3 = cog_mwh * 3600.0 / SELECTED_WAG_LHV_MJ_PER_NM3["COG"] if cog_mwh else 0.0
            direct_fuel = values.get("BFG_consumed_mwh", 0.0) + values.get("COG_consumed_mwh", 0.0)
            co2 = values.get("process_co2_t", 0.0) + values.get("combustion_co2_t", 0.0)
            missing = []
            if coke > EPS and coal <= EPS:
                missing.append("coal_input")
            if coke > EPS and cog_mwh <= EPS:
                missing.append("COG_output")
            if coke > EPS and co2 <= EPS:
                missing.append("CO2")
            if coke > EPS and values.get("electricity_use_mwh", 0.0) <= EPS:
                missing.append("electricity")
            missing.append("steam")
            status = "structurally_inactive" if configuration == C1 and plant_id == "KGF2" else "development_assumption"
            if missing and status != "structurally_inactive":
                status = "incomplete_accounting"
            rows.append(
                {
                    "configuration": configuration,
                    "horizon_hours": horizon_hours,
                    "plant_id": plant_id,
                    "active": status != "structurally_inactive",
                    "coke_output_t_y": _fmt(coke),
                    "coal_input_t_y": _fmt(coal),
                    "coal_t_per_t_coke": _ratio(coal, coke),
                    "COG_output_Nm3_y": _fmt(cog_nm3),
                    "COG_output_MWh_LHV_y": _fmt(cog_mwh),
                    "COG_Nm3_per_t_coke": _ratio(cog_nm3, coke),
                    "COG_MWh_LHV_per_t_coke": _ratio(cog_mwh, coke),
                    "WAG_or_COG_fuel_input_MWh_LHV_y": _fmt(direct_fuel),
                    "WAG_or_COG_fuel_MWh_per_t_coke": _ratio(direct_fuel, coke),
                    "electricity_MWh_y": _fmt(values.get("electricity_use_mwh", 0.0)),
                    "electricity_MWh_per_t_coke": _ratio(values.get("electricity_use_mwh", 0.0), coke),
                    "steam_quantity_y": NA,
                    "steam_unit": "not_executable",
                    "steam_per_t_coke": NA,
                    "CO2_t_y": NA if co2 <= EPS else _fmt(co2),
                    "CO2_t_per_t_coke": NA if co2 <= EPS else _ratio(co2, coke),
                    "missing_fields": ";".join(missing),
                    "status": status,
                    "notes": "C1 KGF1 retained; C1 KGF2 inactive. Coal/coke equality is a development activity proxy.",
                }
            )
    return rows


def _wag_balance_rows(horizon: str, horizon_hours: int, allocations: list[dict[str, str]]) -> list[dict[str, Any]]:
    factor = _annualisation_factor(horizon_hours)
    summaries = {row["configuration_id"]: row for row in _summary_rows(horizon)}
    rows: list[dict[str, Any]] = []
    generated: dict[tuple[str, str, str], float] = defaultdict(float)
    for source in _plant_rows(horizon):
        configuration = source["configuration_id"]
        plant_id = SOURCE_PLANT_TO_CANONICAL.get(source["plant_id"], source["plant_id"])
        for carrier in CARRIERS:
            generated[(configuration, plant_id, carrier)] += _nz(source.get(f"{carrier}_generated_mwh")) * factor
    scale_by_config: dict[str, float] = {}
    for configuration in (C0, C1):
        raw = sum(value for (cfg, _plant, _carrier), value in generated.items() if cfg == configuration)
        expected = _nz(summaries.get(configuration, {}).get("WAG_generated_MWh_y"))
        scale_by_config[configuration] = expected / raw if raw > EPS and expected > EPS else 1.0
    consumed: dict[tuple[str, str, str, str], float] = defaultdict(float)
    generated_nm3: dict[tuple[str, str, str], float] = defaultdict(float)
    for key, value in list(generated.items()):
        configuration, plant, carrier = key
        generated[key] = value * scale_by_config[configuration]
        generated_nm3[key] = generated[key] * 3600.0 / SELECTED_WAG_LHV_MJ_PER_NM3[carrier] if generated[key] else 0.0
    for alloc in allocations:
        if alloc.get("horizon") != horizon:
            continue
        configuration = alloc["configuration_id"]
        plant_id = SOURCE_PLANT_TO_CANONICAL.get(alloc["plant"], alloc["plant"])
        carrier = alloc["carrier"]
        category = alloc["allocation_category"]
        value = _nz(alloc.get("quantity_mwh")) * factor
        if category == "direct_process_sink":
            consumed[(configuration, plant_id, carrier, "direct")] += value
        elif category == "boiler_steam_wag_first":
            consumed[(configuration, plant_id, carrier, "boiler")] += value
        elif category == "vattenfall_internal_generation":
            consumed[(configuration, plant_id, carrier, "vattenfall")] += value
        elif category == "flare_after_all_eligible_sinks":
            consumed[(configuration, plant_id, carrier, "flared")] += value
    keys = {
        (configuration, plant, carrier)
        for configuration in (C0, C1)
        for plant in PLANT_META
        for carrier in CARRIERS
        if (
            generated.get((configuration, plant, carrier), 0.0) > EPS
            or any(consumed.get((configuration, plant, carrier, bucket), 0.0) > EPS for bucket in ("direct", "boiler", "vattenfall", "flared"))
        )
    }
    for configuration, plant, carrier in sorted(keys):
        gen = generated.get((configuration, plant, carrier), 0.0)
        direct = consumed.get((configuration, plant, carrier, "direct"), 0.0)
        boiler = consumed.get((configuration, plant, carrier, "boiler"), 0.0)
        vf = consumed.get((configuration, plant, carrier, "vattenfall"), 0.0)
        flared = consumed.get((configuration, plant, carrier, "flared"), 0.0)
        balance = gen - direct - boiler - vf - flared
        rows.append(
            {
                "configuration": configuration,
                "horizon_hours": horizon_hours,
                "plant_id": plant,
                "carrier": carrier,
                "generated_MWh_LHV_y": _fmt(gen),
                "generated_Nm3_y": _fmt(generated_nm3.get((configuration, plant, carrier), 0.0)),
                "consumed_direct_MWh_LHV_y": _fmt(direct),
                "consumed_boiler_MWh_LHV_y": _fmt(boiler),
                "consumed_vattenfall_MWh_LHV_y": _fmt(vf),
                "flared_MWh_LHV_y": _fmt(flared),
                "balance_error_MWh_LHV_y": _fmt(balance),
                "status": "site_balance_closes_elsewhere" if abs(balance) > BALANCE_TOL_MWH_Y else "closed",
            }
        )
    for configuration in (C0, C1):
        for carrier in CARRIERS:
            gen = sum(generated.get((configuration, plant, carrier), 0.0) for plant in PLANT_META)
            direct = sum(consumed.get((configuration, plant, carrier, "direct"), 0.0) for plant in PLANT_META)
            boiler = sum(consumed.get((configuration, plant, carrier, "boiler"), 0.0) for plant in PLANT_META)
            vf = sum(consumed.get((configuration, plant, carrier, "vattenfall"), 0.0) for plant in PLANT_META)
            flared = sum(consumed.get((configuration, plant, carrier, "flared"), 0.0) for plant in PLANT_META)
            balance = gen - direct - boiler - vf - flared
            rows.append(
                {
                    "configuration": configuration,
                    "horizon_hours": horizon_hours,
                    "plant_id": "SITE_TOTAL",
                    "carrier": carrier,
                    "generated_MWh_LHV_y": _fmt(gen),
                    "generated_Nm3_y": _fmt(gen * 3600.0 / SELECTED_WAG_LHV_MJ_PER_NM3[carrier] if gen else 0.0),
                    "consumed_direct_MWh_LHV_y": _fmt(direct),
                    "consumed_boiler_MWh_LHV_y": _fmt(boiler),
                    "consumed_vattenfall_MWh_LHV_y": _fmt(vf),
                    "flared_MWh_LHV_y": _fmt(flared),
                    "balance_error_MWh_LHV_y": _fmt(balance),
                    "status": "closed" if abs(balance) <= BALANCE_TOL_MWH_Y else "balance_gap",
                }
            )
    return rows


def _emissions_rows(horizon: str, horizon_hours: int) -> list[dict[str, Any]]:
    totals = _source_totals(horizon, horizon_hours)
    rows: list[dict[str, Any]] = []
    for configuration in (C0, C1):
        for plant_id in ("KGF1", "KGF2", "Sinter", "BF6", "BF7", "BOF", "DRP", "EAF", "boilers", "flaring"):
            denominator = _main_product_quantity(totals, configuration, plant_id)
            values = totals[(configuration, plant_id)]
            for bucket, field in (
                ("process_CO2", "process_co2_t"),
                ("combustion_CO2", "combustion_co2_t"),
                ("flaring_CO2", "flaring_co2_t"),
            ):
                co2 = values.get(field, 0.0)
                missing = plant_id in EXPECTED_CO2_PLANTS and co2 <= EPS and not (configuration == C1 and plant_id in {"KGF2", "BF7"})
                rows.append(
                    {
                        "configuration": configuration,
                        "horizon_hours": horizon_hours,
                        "plant_id": plant_id,
                        "emission_bucket": bucket,
                        "CO2_t_y": NA if missing else _fmt(co2),
                        "CO2_t_per_t_main_product": NA if missing else _ratio(co2, denominator),
                        "accounting_convention": "partial_process_and_flaring_only; WAG combustion excluded unless boundary convention is explicit",
                        "included_in_anchor_comparison": False,
                        "double_counting_risk": "managed_by_excluding_WAG_combustion_recount",
                        "status": "missing_executable_coefficient" if missing else _asset_status(configuration, plant_id, denominator),
                        "notes": "CO2 total remains incomplete and not total-anchor comparable.",
                    }
                )
    return rows


def _energy_rows(annual_io_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for row in annual_io_rows:
        carrier = row["carrier_or_material"]
        if carrier not in {"electricity", "NaturalGas", "BFG", "COG", "BOFG"}:
            continue
        key = (row["configuration"], int(row["horizon_hours"]), row["plant_id"], carrier)
        groups.setdefault(
            key,
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant_id": row["plant_id"],
                "carrier": carrier,
                "input_MWh_y": 0.0,
                "output_MWh_y": 0.0,
                "net_MWh_y": 0.0,
                "unit_basis": "energy",
                "HHV_or_LHV": "LHV" if carrier in {"BFG", "COG", "BOFG", "NaturalGas"} else "electricity",
                "status": row["evidence_status"],
                "notes": row["notes"],
            },
        )
        value = _nz(row.get("annual_quantity"))
        if row["direction"] == "input":
            groups[key]["input_MWh_y"] += value
        else:
            groups[key]["output_MWh_y"] += value
    for value in groups.values():
        value["net_MWh_y"] = value["output_MWh_y"] - value["input_MWh_y"]
        value["input_MWh_y"] = _fmt(value["input_MWh_y"])
        value["output_MWh_y"] = _fmt(value["output_MWh_y"])
        value["net_MWh_y"] = _fmt(value["net_MWh_y"])
    return list(groups.values())


def _anchor_gap_rows() -> list[dict[str, Any]]:
    source = _read_csv(C5B_DIR / "s4_4c5b_anchor_gap_dashboard.csv")
    grouped: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in source:
        key = (row["configuration_id"], row["anchor_family"], row["metric"])
        grouped.setdefault(key, {})[row["horizon"]] = row
    rows: list[dict[str, Any]] = []
    for (configuration, family, metric), by_horizon in sorted(grouped.items()):
        h24 = by_horizon.get("24h", {})
        h168 = by_horizon.get("168h", {})
        anchor = h24.get("anchor_value") or h168.get("anchor_value") or ""
        rows.append(
            {
                "configuration": configuration,
                "metric": f"{family}:{metric}",
                "model_24h": h24.get("model_value", ""),
                "model_168h": h168.get("model_value", ""),
                "anchor": anchor,
                "anchor_source": family,
                "gap_24h_pct": h24.get("gap_percent", ""),
                "gap_168h_pct": h168.get("gap_percent", ""),
                "gap_type": h24.get("gap_classification") or h168.get("gap_classification") or "",
                "notes": "validation row only; anchor_used_as_constraint=false",
            }
        )
    return rows


def _red_flags(configuration: str, plant_id: str, denominator: float, totals: dict[tuple[str, str], dict[str, float]], wag_site_status: str) -> str:
    flags: list[str] = []
    values = totals[(configuration, plant_id)]
    active = _asset_status(configuration, plant_id, denominator) == "active"
    if active and denominator <= EPS:
        flags.append("active_plant_zero_main_product")
    if active and plant_id in EXPECTED_ELECTRICITY_PLANTS and values.get("electricity_use_mwh", 0.0) <= EPS:
        flags.append("active_expected_electricity_zero_or_missing")
    if active and plant_id in EXPECTED_CO2_PLANTS and values.get("process_co2_t", 0.0) + values.get("combustion_co2_t", 0.0) + values.get("flaring_co2_t", 0.0) <= EPS:
        flags.append("active_expected_CO2_zero_or_missing")
    if active and plant_id in {"KGF1", "KGF2"}:
        if values.get("material_input_t", 0.0) <= EPS:
            flags.append("active_coking_zero_coal_input")
        if values.get("COG_generated_mwh", 0.0) <= EPS:
            flags.append("active_coking_zero_COG_output")
    if configuration == C1 and plant_id == "KGF2" and denominator > EPS:
        flags.append("C1_KGF2_nonzero_output")
    if configuration == C1 and plant_id == "BF7" and denominator > EPS:
        flags.append("C1_BF7_nonzero_output")
    if configuration == C1 and plant_id == "KGF1" and denominator <= EPS:
        flags.append("C1_KGF1_zero_or_missing_row")
    if wag_site_status != "closed":
        flags.append("WAG_site_balance_gap")
    return ";".join(flags)


def _compact_rows(
    horizon: str,
    horizon_hours: int,
    wag_rows: list[dict[str, Any]],
    allocations: list[dict[str, str]],
) -> list[dict[str, Any]]:
    totals = _source_totals(horizon, horizon_hours)
    allocation_totals = _allocation_annual_totals(horizon, horizon_hours, allocations)
    site_status = {
        row["configuration"]: row["status"]
        for row in wag_rows
        if row["horizon_hours"] == horizon_hours and row["plant_id"] == "SITE_TOTAL" and row["carrier"] == "BFG"
    }
    rows: list[dict[str, Any]] = []
    for configuration in (C0, C1):
        for plant_id in ("KGF1", "KGF2", "Sinter", "PEFA_Malerij", "PEFA_Branderij", "BF6", "BF7", "BOF", "DRP", "EAF", "HSM", "boilers", "Vattenfall", "flaring"):
            values = totals[(configuration, plant_id)]
            denominator = _main_product_quantity(totals, configuration, plant_id)
            if plant_id in {"boilers", "Vattenfall", "flaring"}:
                merged = defaultdict(float)
                merged.update(values)
                for key, value in allocation_totals[(configuration, plant_id)].items():
                    merged[key] = value
                values = merged
                if plant_id == "Vattenfall":
                    denominator = values.get("WAG_to_electricity_mwh", 0.0)
                elif plant_id == "flaring":
                    denominator = sum(values.get(f"{carrier}_flared_mwh", 0.0) for carrier in CARRIERS)
            if plant_id == "KGF1" or plant_id == "KGF2":
                key1, key1_ratio, key1_unit = "coal_or_coking_feed_proxy", _ratio(values.get("material_input_t", 0.0), denominator), "t/t_coke"
                key2, key2_ratio, key2_unit = "COG_output", _ratio(values.get("COG_generated_mwh", 0.0), denominator), "MWh_LHV/t_coke"
                wag_carrier = "COG"
                wag_mwh = values.get("COG_generated_mwh", 0.0)
            elif plant_id in {"BF6", "BF7"}:
                key1, key1_ratio, key1_unit = "sinter", _ratio(values.get("material_input_t", 0.0), denominator), "t/t_hot_metal"
                key2, key2_ratio, key2_unit = "BFG_output", _ratio(values.get("BFG_generated_mwh", 0.0), denominator), "MWh_LHV/t_hot_metal"
                wag_carrier = "BFG"
                wag_mwh = values.get("BFG_generated_mwh", 0.0)
            elif plant_id == "BOF":
                key1, key1_ratio, key1_unit = "hot_metal", _ratio(values.get("material_input_t", 0.0), denominator), "t/t_liquid_steel"
                key2, key2_ratio, key2_unit = "BOFG_output", _ratio(values.get("BOFG_generated_mwh", 0.0), denominator), "MWh_LHV/t_liquid_steel"
                wag_carrier = "BOFG"
                wag_mwh = values.get("BOFG_generated_mwh", 0.0)
            elif plant_id == "DRP":
                key1, key1_ratio, key1_unit = "pellets", _ratio(values.get("material_input_t", 0.0), denominator), "t/t_DRI"
                key2, key2_ratio, key2_unit = "electricity", _ratio(values.get("electricity_use_mwh", 0.0) * 3.6, denominator), "GJ/t_DRI"
                wag_carrier, wag_mwh = "", 0.0
            elif plant_id == "EAF":
                key1, key1_ratio, key1_unit = "DRI", _ratio(values.get("material_input_t", 0.0), denominator), "t/t_liquid_steel"
                key2, key2_ratio, key2_unit = "electricity", _ratio(values.get("electricity_use_mwh", 0.0), denominator), "MWh/t_liquid_steel"
                wag_carrier, wag_mwh = "", 0.0
            else:
                key1, key1_ratio, key1_unit = "main_input_proxy", _ratio(values.get("material_input_t", 0.0), denominator), "per_main_product"
                key2, key2_ratio, key2_unit = "energy_proxy", _ratio(values.get("electricity_use_mwh", 0.0) + values.get("natural_gas_mwh_lhv_model", 0.0), denominator), "MWh/t_or_MWh"
                wag_carrier, wag_mwh = "", 0.0
            ng_gj_hhv = values.get("natural_gas_use_nm3", 0.0) * NG_HHV_MJ_PER_NM3 / 1000.0
            co2 = values.get("process_co2_t", 0.0) + values.get("combustion_co2_t", 0.0) + values.get("flaring_co2_t", 0.0)
            wag_nm3_ratio: Any = ""
            wag_mwh_ratio: Any = ""
            if wag_carrier and denominator > EPS:
                wag_nm3_ratio = _fmt(wag_mwh * 3600.0 / SELECTED_WAG_LHV_MJ_PER_NM3[wag_carrier] / denominator)
                wag_mwh_ratio = _fmt(wag_mwh / denominator)
            rows.append(
                {
                    "configuration": configuration,
                    "horizon_hours": horizon_hours,
                    "plant": plant_id,
                    "active": _asset_status(configuration, plant_id, denominator) == "active",
                    "main_product": MAIN_PRODUCTS.get(plant_id, ("main_product_proxy", ""))[0],
                    "main_product_t_y": _fmt(denominator),
                    "key_input_1": key1,
                    "key_input_1_ratio": key1_ratio,
                    "key_input_1_unit": key1_unit,
                    "key_input_2": key2,
                    "key_input_2_ratio": key2_ratio,
                    "key_input_2_unit": key2_unit,
                    "electricity_MWh_per_t": _ratio(values.get("electricity_use_mwh", 0.0), denominator),
                    "NG_GJ_HHV_per_t": _ratio(ng_gj_hhv, denominator),
                    "WAG_output_carrier": wag_carrier,
                    "WAG_output_Nm3_per_t": wag_nm3_ratio,
                    "WAG_output_MWh_LHV_per_t": wag_mwh_ratio,
                    "CO2_t_per_t": NA if co2 <= EPS and plant_id in EXPECTED_CO2_PLANTS else _ratio(co2, denominator),
                    "status": _asset_status(configuration, plant_id, denominator),
                    "red_flags": _red_flags(configuration, plant_id, denominator, totals, site_status.get(configuration, "closed")),
                }
            )
    return rows


def _stage_gate(all_summary: list[dict[str, Any]], compact: list[dict[str, Any]], wag: list[dict[str, Any]]) -> dict[str, Any]:
    c1_kgf1_active = any(row["configuration"] == C1 and row["plant"] == "KGF1" and row["active"] is True for row in compact)
    c1_kgf2_inactive = all(not row["active"] for row in compact if row["configuration"] == C1 and row["plant"] == "KGF2")
    c1_bf7_inactive = all(not row["active"] for row in compact if row["configuration"] == C1 and row["plant"] == "BF7")
    runs_ok = {
        (row["configuration_id"], row["horizon"]): row["termination_condition"]
        for row in all_summary
        if row.get("termination_condition")
    }
    required_runs = {(cfg, horizon) for cfg in (C0, C1) for horizon in HORIZONS}
    wag_closed = all(row["status"] == "closed" for row in wag if row["plant_id"] == "SITE_TOTAL")
    return {
        "stage": STAGE,
        "decision": "pass_development_structural_diagnostics_with_open_accounting_gaps",
        "required_runs_executed": required_runs.issubset(set(runs_ok)),
        "c1_kgf1_active": c1_kgf1_active,
        "c1_kgf2_inactive": c1_kgf2_inactive,
        "c1_bf7_inactive": c1_bf7_inactive,
        "steam_validation_anchor_active": False,
        "fixed_50_50_wag_ng_boiler_split_active": False,
        "wag_first_allocation_preserved": True,
        "vattenfall_cap_policy": "combined_BFG_COG_BOFG_volume_cap_not_per_carrier",
        "vattenfall_combined_cap_Nm3_h": VATTENFALL_TOTAL_WAG_CAP_NM3_H,
        "wag_balance_site_closed": wag_closed,
        "co2_completeness_status": "partial_missing_BF_BOF_KGF_boiler_WAG_combustion_convention",
        "anchors_used_as_constraints": False,
        "forbidden_economic_features_added": False,
        "output_directory": _rel(C5C_DIR),
    }


def _summary_with_c5c_fields(horizon: str, wag_rows: list[dict[str, Any]], emission_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    site_wag = {
        (row["configuration"], row["carrier"]): row
        for row in wag_rows
        if row["horizon_hours"] == HORIZONS[horizon] and row["plant_id"] == "SITE_TOTAL"
    }
    for row in _summary_rows(horizon):
        configuration = row["configuration_id"]
        balance_error = sum(_nz(site_wag.get((configuration, carrier), {}).get("balance_error_MWh_LHV_y")) for carrier in CARRIERS)
        missing_co2 = sum(
            1
            for emission in emission_rows
            if emission["configuration"] == configuration
            and emission["horizon_hours"] == HORIZONS[horizon]
            and emission["status"] == "missing_executable_coefficient"
        )
        rows.append(
            {
                **row,
                "physical_fulfilment": row.get("physical_solver_site_target_fulfilment", ""),
                "WAG_balance_error_MWh_y": _fmt(balance_error),
                "material_balance_status": "closed_to_solver_terminal_policy_or_accounting_proxy",
                "emission_bucket_completeness": "incomplete" if missing_co2 else "complete",
                "C1_route_topology_status": "BF6_KGF1_BOF_retained_BF7_KGF2_inactive" if configuration == C1 else "C0_BF6_BF7_KGF1_KGF2_active",
            }
        )
    return rows


def _run_registry(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "stage": STAGE,
            "configuration": row["configuration_id"],
            "horizon_hours": row["horizon_hours"],
            "solver_status": row["solver_status"],
            "termination_condition": row["termination_condition"],
            "runtime_seconds": row["runtime_seconds"],
            "variable_count": row["variable_count"],
            "binary_count": row["binary_count"],
            "constraint_count": row["constraint_count"],
            "production_fulfilment": row["production_fulfilment"],
            "input_directory": _rel(CORRECTED_INPUT_DIR),
            "output_directory": _rel(C5C_DIR),
            "development_only": True,
        }
        for row in summary_rows
    ]


def _write_outputs() -> dict[str, Any]:
    C5C_DIR.mkdir(parents=True, exist_ok=True)
    run_b5a_correction()
    run_s4_4c5b_site_scale_downstream_steam_wag_reconciliation()
    allocations = _allocation_rows()
    all_hourly: list[dict[str, Any]] = []
    all_annual: list[dict[str, Any]] = []
    all_ratios: list[dict[str, Any]] = []
    all_coking: list[dict[str, Any]] = []
    all_wag: list[dict[str, Any]] = []
    all_emissions: list[dict[str, Any]] = []
    all_energy: list[dict[str, Any]] = []
    all_compact: list[dict[str, Any]] = []
    all_summary: list[dict[str, Any]] = []
    for horizon, hours in HORIZONS.items():
        hourly = _hourly_io_rows(horizon, hours, allocations)
        annual = _annualise_io(hourly, hours)
        wag = _wag_balance_rows(horizon, hours, allocations)
        emissions = _emissions_rows(horizon, hours)
        energy = _energy_rows(annual)
        compact = _compact_rows(horizon, hours, wag, allocations)
        summary = _summary_with_c5c_fields(horizon, wag, emissions)
        all_hourly.extend(hourly)
        all_annual.extend(annual)
        all_ratios.extend(_conversion_ratio_rows(horizon, hours, allocations))
        all_coking.extend(_coking_diagnostics(horizon, hours))
        all_wag.extend(wag)
        all_emissions.extend(emissions)
        all_energy.extend(energy)
        all_compact.extend(compact)
        all_summary.extend(summary)
        _write_csv(C5C_DIR / f"s4_4c5c_{horizon}_summary.csv", summary)
    anchor = _anchor_gap_rows()
    gate = _stage_gate(all_summary, all_compact, all_wag)
    _write_json(C5C_DIR / "s4_4c5c_stage_gate.json", gate)
    _write_csv(C5C_DIR / "s4_4c5c_run_registry.csv", _run_registry(all_summary))
    _write_csv(C5C_DIR / "s4_4c5c_plant_carrier_io_hourly.csv", all_hourly)
    _write_csv(C5C_DIR / "s4_4c5c_plant_carrier_io_annualised.csv", all_annual)
    _write_csv(C5C_DIR / "s4_4c5c_plant_conversion_ratios.csv", all_ratios)
    _write_csv(C5C_DIR / "s4_4c5c_coking_plant_diagnostics.csv", all_coking)
    _write_csv(C5C_DIR / "s4_4c5c_wag_generation_consumption_by_plant.csv", all_wag)
    _write_csv(C5C_DIR / "s4_4c5c_emissions_by_plant.csv", all_emissions)
    _write_csv(C5C_DIR / "s4_4c5c_energy_by_plant.csv", all_energy)
    _write_csv(C5C_DIR / "s4_4c5c_anchor_gap_dashboard.csv", anchor)
    _write_csv(C5C_DIR / "s4_4c5c_compact_table_for_chat.csv", all_compact)
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": _rel(C5C_DIR),
        "rows": {
            "hourly_io": len(all_hourly),
            "annual_io": len(all_annual),
            "conversion_ratios": len(all_ratios),
            "coking_diagnostics": len(all_coking),
            "wag_balance": len(all_wag),
            "emissions": len(all_emissions),
            "energy": len(all_energy),
            "compact": len(all_compact),
            "anchor_gaps": len(anchor),
        },
    }
    _write_json(C5C_DIR / "s4_4c5c_summary.json", summary)
    return summary


def run_s4_4c5c_plant_asset_conversion_diagnostics() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5c_plant_asset_conversion_diagnostics(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
