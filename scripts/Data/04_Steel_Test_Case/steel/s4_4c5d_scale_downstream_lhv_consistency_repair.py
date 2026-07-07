"""S4.4c5d scale, downstream, and LHV consistency repair.

Development-only repair/accounting layer after C5c. It does not add prices,
revenues, calibration constraints, stochasticity, or optimiser steering.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from .s4_4c_unified_physical_modelbuilder import (
    FLARE_CO2_EF_T_PER_MWH,
    SELECTED_WAG_LHV_MJ_PER_NM3,
    VATTENFALL_TOTAL_WAG_CAP_NM3_H,
)
from .s4_4c5b_site_scale_downstream_steam_wag_reconciliation import (
    C0,
    C1,
    C5B_DIR,
    CARRIERS,
    HORIZONS,
    NG_HHV_MJ_PER_NM3,
    REPO_ROOT,
    S4_ROOT,
    _safe_float,
    _write_csv,
    _write_json,
)
from .s4_4c5c_plant_asset_conversion_diagnostics import (
    C5C_DIR,
    MAIN_PRODUCTS,
    run_s4_4c5c_plant_asset_conversion_diagnostics,
)


C5D_DIR = S4_ROOT / "s4_4c5d_scale_downstream_lhv_consistency_repair"
STAGE = "S4.4c5d_scale_downstream_lhv_consistency_repair"
TARGET_SITE_T_Y = 6_750_000.0
EPS = 1e-9
ABS_TOL_MWH = 1e-6
REL_TOL_PCT = 0.01
DOWNSTREAM_TOL_T_Y = 1.0
NA = "NaN"

SCALE_COLUMNS = {
    "raw_model_quantity",
    "raw_model_unit",
    "site_scaled_quantity",
    "site_scaled_unit",
    "scale_factor",
    "scale_mode",
    "metric_scope",
}

MODULE_SCALE_MODE = "module_scaled_to_site_target"
FULL_SITE_SCALE_MODE = "full_site_proxy_do_not_scale"
DIAGNOSTIC_SCALE_MODE = "diagnostic_not_scaled"
VALIDATION_SCALE_MODE = "validation_anchor_only"
NA_SCALE_MODE = "not_applicable"

WAG_CARRIER_NAMES = set(CARRIERS)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def _num(value: Any) -> float:
    return _safe_float(value)


def _fmt(value: Any) -> Any:
    if value == NA:
        return NA
    if isinstance(value, float):
        if math.isnan(value):
            return NA
        return round(value, 6)
    return value


def _ratio(numerator: float, denominator: float) -> float | str:
    if abs(denominator) <= EPS:
        return NA
    return round(numerator / denominator, 9)


def _mwh_to_nm3(mwh: float, carrier: str) -> float:
    return mwh * 3600.0 / SELECTED_WAG_LHV_MJ_PER_NM3[carrier]


def _nm3_to_mwh(nm3: float, carrier: str) -> float:
    return nm3 * SELECTED_WAG_LHV_MJ_PER_NM3[carrier] / 3600.0


def _compact_source() -> list[dict[str, str]]:
    return _read_csv(C5C_DIR / "s4_4c5c_compact_table_for_chat.csv")


def _summary_source(horizon: str) -> list[dict[str, str]]:
    return _read_csv(C5C_DIR / f"s4_4c5c_{horizon}_summary.csv")


def _scale_factors() -> dict[tuple[str, int], float]:
    factors: dict[tuple[str, int], float] = {}
    compact = _compact_source()
    for horizon_hours in HORIZONS.values():
        for configuration in (C0, C1):
            rows = [
                row
                for row in compact
                if row["configuration"] == configuration and int(row["horizon_hours"]) == horizon_hours
            ]
            if configuration == C1:
                raw = sum(
                    _num(row["main_product_t_y"])
                    for row in rows
                    if row["plant"] in {"BOF", "EAF"}
                )
            else:
                raw = sum(
                    _num(row["main_product_t_y"])
                    for row in rows
                    if row["plant"] == "HSM"
                )
            factors[(configuration, horizon_hours)] = TARGET_SITE_T_Y / raw if raw > EPS else 1.0
    return factors


def _scale_quantity(
    quantity: float,
    *,
    configuration: str,
    horizon_hours: int,
    scale_factors: dict[tuple[str, int], float],
    mode: str,
) -> tuple[float, float, float]:
    factor = scale_factors[(configuration, horizon_hours)]
    if mode == MODULE_SCALE_MODE:
        return quantity, quantity * factor, factor
    if mode == FULL_SITE_SCALE_MODE:
        return quantity, quantity, 1.0
    if mode == VALIDATION_SCALE_MODE:
        return quantity, quantity, 1.0
    return quantity, quantity, 1.0


def _add_scale_columns(
    row: dict[str, Any],
    *,
    raw: float | str,
    unit: str,
    site: float | str,
    factor: float | str,
    mode: str,
    scope: str,
) -> dict[str, Any]:
    return {
        **row,
        "raw_model_quantity": _fmt(raw),
        "raw_model_unit": unit,
        "site_scaled_quantity": _fmt(site),
        "site_scaled_unit": unit,
        "scale_factor": _fmt(factor),
        "scale_mode": mode,
        "metric_scope": scope,
    }


def _carrier_conversion_constants_rows() -> list[dict[str, Any]]:
    rows = []
    for carrier in CARRIERS:
        rows.append(
            {
                "carrier": carrier,
                "basis": "WAG_LHV",
                "LHV_MJ_per_Nm3": SELECTED_WAG_LHV_MJ_PER_NM3[carrier],
                "HHV_MJ_per_Nm3": "",
                "source_or_assumption_id": "S4.4c5d_CANONICAL_WAG_LHV_CONSTANT",
                "evidence_status": "physical_conversion_constant_development",
                "used_for": "WAG Nm3 to MWh_LHV conversion only",
                "notes": "Not a calibration knob and not used to tune anchor gaps.",
            }
        )
    rows.append(
        {
            "carrier": "NaturalGas",
            "basis": "NG_HHV_validation",
            "LHV_MJ_per_Nm3": "",
            "HHV_MJ_per_Nm3": NG_HHV_MJ_PER_NM3,
            "source_or_assumption_id": "S4.4c5b_NG_HHV_VALIDATION_BASIS",
            "evidence_status": "validation_conversion_basis",
            "used_for": "NG validation and anchor comparison",
            "notes": "Do not use as WAG LHV.",
        }
    )
    return rows


def _raw_downstream_rows(scale_factors: dict[tuple[str, int], float]) -> list[dict[str, Any]]:
    compact = _compact_source()
    rows: list[dict[str, Any]] = []
    for horizon_hours in HORIZONS.values():
        for configuration in (C0, C1):
            by_plant = {
                row["plant"]: _num(row["main_product_t_y"])
                for row in compact
                if row["configuration"] == configuration and int(row["horizon_hours"]) == horizon_hours
            }
            retained = by_plant.get("BOF", 0.0)
            eaf = by_plant.get("EAF", 0.0) if configuration == C1 else 0.0
            total = retained + eaf
            factor = scale_factors[(configuration, horizon_hours)]
            site_total = total * factor
            final_raw = total
            final_site = site_total
            flags: list[str] = []
            if configuration == C1 and eaf > EPS and final_raw <= retained + EPS:
                flags.append("c1_eaf_liquid_steel_not_continued_downstream")
            if final_site + DOWNSTREAM_TOL_T_Y < TARGET_SITE_T_Y:
                flags.append("final_product_proxy_shortfall_without_explicit_slab_import")
            status = "pass_proxy_warn"
            if flags:
                status = "fail"
            rows.append(
                {
                    "configuration": configuration,
                    "horizon_hours": horizon_hours,
                    "retained_bof_liquid_steel_raw_t_y": _fmt(retained),
                    "eaf_liquid_steel_raw_t_y": _fmt(eaf),
                    "total_liquid_steel_raw_t_y": _fmt(total),
                    "internal_slab_produced_raw_t_y": _fmt(total),
                    "external_slab_import_raw_t_y": 0.0,
                    "final_product_proxy_raw_t_y": _fmt(final_raw),
                    "retained_bof_liquid_steel_site_t_y": _fmt(retained * factor),
                    "eaf_liquid_steel_site_t_y": _fmt(eaf * factor),
                    "total_liquid_steel_site_t_y": _fmt(site_total),
                    "internal_slab_produced_site_t_y": _fmt(site_total),
                    "external_slab_import_site_t_y": 0.0,
                    "final_product_proxy_site_t_y": _fmt(final_site),
                    "target_site_t_y": TARGET_SITE_T_Y,
                    "final_product_fulfilment": _fmt(final_site / TARGET_SITE_T_Y if TARGET_SITE_T_Y else 0.0),
                    "downstream_continuation_status": status,
                    "red_flags": ";".join(flags),
                    "external_slab_import_status": "not_used",
                    "external_slab_import_basis": "explicit_zero_in_C5d_repair",
                    "external_slab_import_is_flexible": False,
                    "notes": "Downstream continuation is repaired as accounting continuation from total retained BOF plus EAF liquid steel; HSM/DSP physics remain proxy.",
                }
            )
    return rows


def _plant_io_rows(scale_factors: dict[tuple[str, int], float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source = _read_csv(C5C_DIR / "s4_4c5c_plant_carrier_io_annualised.csv")
    allocation_classes = {
        "direct_process_sink",
        "boiler_steam_wag_first",
        "boiler_steam_ng_supplement",
        "vattenfall_internal_generation",
        "WAG_internal_generation",
        "flare_after_all_eligible_sinks",
    }
    for row in source:
        configuration = row["configuration"]
        horizon_hours = int(row["horizon_hours"])
        quantity = _num(row["annual_quantity"])
        unit = row["unit"]
        if row["evidence_status"] in {"missing_executable_coefficient", "structurally_inactive"}:
            rows.append(
                _add_scale_columns(
                    row,
                    raw=quantity,
                    unit=unit,
                    site=quantity,
                    factor=1.0,
                    mode=DIAGNOSTIC_SCALE_MODE if row["evidence_status"] == "missing_executable_coefficient" else NA_SCALE_MODE,
                    scope=row["evidence_status"],
                )
            )
            continue
        already_site = configuration == C1 and row["accounting_class"] in allocation_classes
        if already_site:
            factor = scale_factors[(configuration, horizon_hours)]
            raw = quantity / factor if factor > EPS else quantity
            site = quantity
            mode = MODULE_SCALE_MODE
        else:
            raw, site, factor = _scale_quantity(
                quantity,
                configuration=configuration,
                horizon_hours=horizon_hours,
                scale_factors=scale_factors,
                mode=MODULE_SCALE_MODE,
            )
            mode = MODULE_SCALE_MODE
        rows.append(
            _add_scale_columns(
                row,
                raw=raw,
                unit=unit,
                site=site,
                factor=factor,
                mode=mode,
                scope="physical_module_quantity",
            )
        )
    return rows


def _conversion_ratio_rows(scale_factors: dict[tuple[str, int], float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source = _read_csv(C5C_DIR / "s4_4c5c_plant_conversion_ratios.csv")
    for row in source:
        configuration = row["configuration"]
        horizon_hours = int(row["horizon_hours"])
        raw_main = _num(row["main_product_quantity_t_y"])
        factor = scale_factors[(configuration, horizon_hours)]
        raw_quantity = _num(row["annual_quantity"])
        if row["annual_quantity"] == NA or row["status"] in {"missing_executable_coefficient", "inactive_or_zero_denominator"}:
            raw = NA if row["annual_quantity"] == NA else raw_quantity
            site = raw
            mode = DIAGNOSTIC_SCALE_MODE if row["status"] == "missing_executable_coefficient" else NA_SCALE_MODE
            scope = row["status"]
        else:
            raw = raw_quantity
            site = raw_quantity * factor
            mode = MODULE_SCALE_MODE
            scope = "physical_module_quantity"
        rows.append(
            _add_scale_columns(
                {
                    **row,
                    "main_product_site_t_y": _fmt(raw_main * factor),
                },
                raw=raw,
                unit=row["unit"],
                site=site,
                factor=factor if mode == MODULE_SCALE_MODE else 1.0,
                mode=mode,
                scope=scope,
            )
        )
    return rows


def _wag_balance_rows(scale_factors: dict[tuple[str, int], float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source = _read_csv(C5C_DIR / "s4_4c5c_wag_generation_consumption_by_plant.csv")
    for row in source:
        configuration = row["configuration"]
        horizon_hours = int(row["horizon_hours"])
        generated = _num(row["generated_MWh_LHV_y"])
        mode = MODULE_SCALE_MODE if row["plant_id"] != "SITE_TOTAL" else MODULE_SCALE_MODE
        raw, site, factor = _scale_quantity(
            generated,
            configuration=configuration,
            horizon_hours=horizon_hours,
            scale_factors=scale_factors,
            mode=mode,
        )
        carrier = row["carrier"]
        site_nm3 = _mwh_to_nm3(site, carrier) if carrier in WAG_CARRIER_NAMES else 0.0
        rows.append(
            _add_scale_columns(
                {
                    **row,
                    "generated_Nm3_y": _fmt(site_nm3),
                    "LHV_MJ_per_Nm3_used": SELECTED_WAG_LHV_MJ_PER_NM3.get(carrier, ""),
                },
                raw=raw,
                unit="MWh_LHV/y",
                site=site,
                factor=factor,
                mode=mode,
                scope="WAG_physical_energy_balance",
            )
        )
    return rows


def _vattenfall_hourly_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source = _read_csv(C5B_DIR / "s4_4c5b_vattenfall_cap_hourly.csv")
    grouped_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in source:
        values = {}
        for carrier in CARRIERS:
            mwh = _num(row[f"{carrier}_to_vattenfall_MWh_LHV"])
            volume = _mwh_to_nm3(mwh, carrier)
            values[carrier] = (mwh, volume)
        combined = sum(volume for _mwh, volume in values.values())
        grouped_values[(row["horizon"], row["configuration_id"])].append(combined)
        output = {
            "horizon": row["horizon"],
            "horizon_hours": row["horizon_hours"],
            "configuration_id": row["configuration_id"],
            "hour": row["hour"],
            "Vattenfall_cap_Nm3_h": VATTENFALL_TOTAL_WAG_CAP_NM3_H,
            "combined_vattenfall_wag_volume_Nm3_h": _fmt(combined),
            "Vattenfall_cap_status": "binding" if combined >= VATTENFALL_TOTAL_WAG_CAP_NM3_H - 1e-6 else "not_binding",
            "cap_policy": "combined_BFG_COG_BOFG_volume_cap_not_per_carrier",
            "scale_mode": DIAGNOSTIC_SCALE_MODE,
            "metric_scope": "hourly_interface_cap_diagnostic",
        }
        for carrier in CARRIERS:
            mwh, volume = values[carrier]
            output[f"{carrier}_to_vattenfall_MWh_LHV"] = _fmt(mwh)
            output[f"{carrier}_volume_Nm3_h"] = _fmt(volume)
            output[f"{carrier}_WAG_to_electricity_MWh"] = row.get(f"{carrier}_WAG_to_electricity_MWh", "")
            output[f"{carrier}_LHV_MJ_per_Nm3_used"] = SELECTED_WAG_LHV_MJ_PER_NM3[carrier]
        rows.append(output)
    stats = {
        key: {
            "max": max(values) if values else 0.0,
            "mean": sum(values) / len(values) if values else 0.0,
            "binding": sum(1 for value in values if value >= VATTENFALL_TOTAL_WAG_CAP_NM3_H - 1e-6),
        }
        for key, values in grouped_values.items()
    }
    for row in rows:
        stat = stats[(row["horizon"], row["configuration_id"])]
        row["max_combined_vattenfall_wag_volume_Nm3_h"] = _fmt(stat["max"])
        row["mean_combined_vattenfall_wag_volume_Nm3_h"] = _fmt(stat["mean"])
        row["binding_hours"] = stat["binding"]
    return rows


def _scale_audit_rows(
    scale_factors: dict[tuple[str, int], float],
    downstream: list[dict[str, Any]],
    lhv_counts: dict[tuple[str, int], dict[str, int]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    anchors = _read_csv(C5B_DIR / "s4_4c5b_anchor_gap_dashboard.csv")
    summaries = {
        (row["configuration_id"], row["horizon"]): row
        for horizon in HORIZONS
        for row in _summary_source(horizon)
    }
    downstream_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in downstream}
    for horizon, hours in HORIZONS.items():
        for configuration in (C0, C1):
            summary = summaries[(configuration, horizon)]
            factor = scale_factors[(configuration, hours)]
            metric_specs = [
                ("final_product_proxy", _num(downstream_by_key[(configuration, hours)]["final_product_proxy_raw_t_y"]), "t/y", MODULE_SCALE_MODE, "production_accounting"),
                ("WAG_generated", _num(summary["WAG_generated_MWh_y"]), "MWh_LHV/y", MODULE_SCALE_MODE, "WAG_balance"),
                ("WAG_electricity", _num(summary["WAG_electricity_MWh_y"]), "MWh/y", MODULE_SCALE_MODE, "internal_generation"),
                ("electricity_total", _num(summary["electricity_gross_MWh_y"]), "MWh/y", FULL_SITE_SCALE_MODE if configuration == C0 else MODULE_SCALE_MODE, "electricity_accounting"),
                ("natural_gas", _num(summary["NG_Nm3_h_avg_HHV_basis"]), "Nm3/h_HHV_basis", DIAGNOSTIC_SCALE_MODE if configuration == C0 else MODULE_SCALE_MODE, "NG_HHV_validation_metric"),
                ("co2_total", _num(summary["CO2_partial_total_t_y"]), "tCO2/y", DIAGNOSTIC_SCALE_MODE, "partial_CO2_diagnostic"),
            ]
            for metric, raw_value, unit, mode, scope in metric_specs:
                if mode == MODULE_SCALE_MODE:
                    raw = raw_value / factor if metric in {"WAG_generated", "WAG_electricity", "electricity_total", "natural_gas"} and configuration == C1 else raw_value
                    site = raw * factor
                    used_factor = factor
                elif mode == FULL_SITE_SCALE_MODE:
                    raw = raw_value
                    site = raw_value
                    used_factor = 1.0
                else:
                    raw = raw_value
                    site = raw_value
                    used_factor = 1.0
                rows.append(
                    {
                        "configuration": configuration,
                        "horizon_hours": hours,
                        "metric": metric,
                        "raw_model_quantity": _fmt(raw),
                        "raw_model_unit": unit,
                        "site_scaled_quantity": _fmt(site),
                        "site_scaled_unit": unit,
                        "scale_factor": _fmt(used_factor),
                        "scale_mode": mode,
                        "metric_scope": scope,
                        "anchor_quantity": "",
                        "anchor_unit": unit,
                        "anchor_comparison_allowed": False,
                        "red_flag": "",
                        "notes": f"LHV pass={lhv_counts.get((configuration, hours), {}).get('pass', 0)} fail={lhv_counts.get((configuration, hours), {}).get('fail', 0)}",
                    }
                )
    for row in anchors:
        configuration = row["configuration_id"]
        horizon = row["horizon"]
        if not horizon:
            continue
        hours = HORIZONS[horizon]
        factor = scale_factors[(configuration, hours)]
        metric = row["metric"]
        model_value = _num(row.get("model_value"))
        if metric == "electricity_total" and configuration == C0:
            mode = FULL_SITE_SCALE_MODE
            raw = site = model_value
            used_factor = 1.0
            red_flag = ""
        elif metric == "co2_total":
            mode = DIAGNOSTIC_SCALE_MODE
            raw = site = model_value
            used_factor = 1.0
            red_flag = "partial_CO2_not_comparable_to_total_anchor"
        elif row["anchor_family"] == "Heracless":
            mode = VALIDATION_SCALE_MODE
            raw = site = 0.0
            used_factor = 1.0
            red_flag = "missing_reviewed_or_migrated_source_in_C5a_inputs"
        else:
            mode = MODULE_SCALE_MODE if configuration == C1 or metric == "wag_electricity" else DIAGNOSTIC_SCALE_MODE
            if mode == MODULE_SCALE_MODE:
                raw = model_value / factor if configuration == C1 else model_value
                site = raw * factor if metric == "wag_electricity" or configuration == C1 else model_value
                used_factor = factor if metric == "wag_electricity" or configuration == C1 else 1.0
            else:
                raw = site = model_value
                used_factor = 1.0
            red_flag = ""
        allowed = mode in {MODULE_SCALE_MODE, FULL_SITE_SCALE_MODE} and red_flag == ""
        rows.append(
            {
                "configuration": configuration,
                "horizon_hours": hours,
                "metric": f"{row['anchor_family']}:{metric}",
                "raw_model_quantity": _fmt(raw),
                "raw_model_unit": row.get("unit", ""),
                "site_scaled_quantity": _fmt(site),
                "site_scaled_unit": row.get("unit", ""),
                "scale_factor": _fmt(used_factor),
                "scale_mode": mode,
                "metric_scope": "validation_anchor_comparison",
                "anchor_quantity": row.get("anchor_value", ""),
                "anchor_unit": row.get("unit", ""),
                "anchor_comparison_allowed": allowed,
                "red_flag": red_flag,
                "notes": "Anchors remain validation rows only; no optimiser constraints.",
            }
        )
    return rows


def _anchor_gap_rows(scale_audit: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in scale_audit:
        if not str(row["metric"]).startswith(("Athanasiadis:", "Heracless:")):
            continue
        anchor = _num(row["anchor_quantity"])
        site = _num(row["site_scaled_quantity"])
        gap = (site - anchor) / anchor * 100.0 if anchor else ""
        rows.append(
            {
                **row,
                "gap_percent": _fmt(gap) if gap != "" else "",
                "gap_type": row["red_flag"],
            }
        )
    return rows


def _lhv_check_rows(wag_rows: list[dict[str, Any]], vf_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add_check(
        *,
        configuration: str,
        horizon_hours: int,
        plant: str,
        carrier: str,
        direction: str,
        nm3: float,
        mwh: float,
        notes: str,
    ) -> None:
        if carrier not in SELECTED_WAG_LHV_MJ_PER_NM3:
            status = "fail"
            red_flags = "carrier_missing_lhv"
            expected = 0.0
            rel_error = ""
        else:
            expected = _nm3_to_mwh(nm3, carrier)
            abs_error = mwh - expected
            rel_error = abs(abs_error) / abs(expected) * 100.0 if abs(expected) > EPS else 0.0
            status = "pass" if abs(abs_error) <= ABS_TOL_MWH or rel_error <= REL_TOL_PCT else "fail"
            red_flags = "" if status == "pass" else "lhv_conversion_mismatch"
        rows.append(
            {
                "configuration": configuration,
                "horizon_hours": horizon_hours,
                "plant": plant,
                "carrier": carrier,
                "direction": direction,
                "quantity_Nm3": _fmt(nm3),
                "reported_MWh_LHV": _fmt(mwh),
                "expected_MWh_LHV_from_LHV": _fmt(expected),
                "absolute_error_MWh": _fmt(mwh - expected),
                "relative_error_pct": _fmt(rel_error) if rel_error != "" else "",
                "LHV_MJ_per_Nm3_used": SELECTED_WAG_LHV_MJ_PER_NM3.get(carrier, ""),
                "status": status,
                "red_flags": red_flags,
                "notes": notes,
            }
        )

    for row in wag_rows:
        carrier = row["carrier"]
        if carrier not in WAG_CARRIER_NAMES:
            continue
        mwh = _num(row["site_scaled_quantity"])
        nm3 = _mwh_to_nm3(mwh, carrier)
        add_check(
            configuration=row["configuration"],
            horizon_hours=int(row["horizon_hours"]),
            plant=row["plant_id"],
            carrier=carrier,
            direction="generated_primary_metric",
            nm3=nm3,
            mwh=mwh,
            notes="WAG balance generated energy converted with canonical LHV.",
        )
    for row in vf_rows:
        for carrier in CARRIERS:
            add_check(
                configuration=row["configuration_id"],
                horizon_hours=int(row["horizon_hours"]),
                plant="Vattenfall",
                carrier=carrier,
                direction="vattenfall_cap_hourly",
                nm3=_num(row[f"{carrier}_volume_Nm3_h"]),
                mwh=_num(row[f"{carrier}_to_vattenfall_MWh_LHV"]),
                notes="Vattenfall cap volume recomputed as combined BFG+COG+BOFG volume.",
            )
    return rows


def _lhv_counts(rows: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, int]]:
    counts: dict[tuple[str, int], dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    for row in rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        counts[key][row["status"]] += 1
    return counts


def _compact_rows(
    scale_factors: dict[tuple[str, int], float],
    downstream: list[dict[str, Any]],
    lhv_counts: dict[tuple[str, int], dict[str, int]],
) -> list[dict[str, Any]]:
    downstream_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in downstream}
    source = [
        row
        for row in _compact_source()
        if int(row["horizon_hours"]) == 24
        and row["plant"]
        in {"KGF1", "KGF2", "Sinter", "BF6", "BF7", "BOF", "DRP", "EAF", "HSM", "boilers", "Vattenfall", "flaring"}
    ]
    rows: list[dict[str, Any]] = []
    for row in source:
        configuration = row["configuration"]
        horizon_hours = int(row["horizon_hours"])
        plant = row["plant"]
        factor = scale_factors[(configuration, horizon_hours)]
        raw_main = _num(row["main_product_t_y"])
        if row["status"] == "structurally_inactive":
            site_main = raw_main
            mode = NA_SCALE_MODE
        else:
            site_main = raw_main * factor
            mode = MODULE_SCALE_MODE
        carrier = row["WAG_output_carrier"]
        lhv = SELECTED_WAG_LHV_MJ_PER_NM3.get(carrier, "") if carrier else ""
        wag_nm3 = _num(row["WAG_output_Nm3_per_t"])
        if carrier and raw_main > EPS:
            if row["WAG_output_MWh_LHV_per_t"]:
                wag_mwh = wag_nm3 * SELECTED_WAG_LHV_MJ_PER_NM3[carrier] / 3600.0
            else:
                wag_mwh = 0.0
        else:
            wag_mwh = 0.0
        ds = downstream_by_key[(configuration, horizon_hours)]
        ds_status = ds["downstream_continuation_status"]
        flags = [flag for flag in row["red_flags"].split(";") if flag]
        if configuration == C1 and plant == "EAF" and _num(ds["eaf_liquid_steel_raw_t_y"]) > EPS and ds_status.startswith("fail"):
            flags.append("c1_eaf_liquid_steel_not_continued_downstream")
        rows.append(
            {
                "configuration": configuration,
                "horizon_hours": horizon_hours,
                "plant": plant,
                "active": row["active"],
                "main_product": row["main_product"],
                "main_product_raw_t_y": _fmt(raw_main),
                "main_product_site_t_y": _fmt(site_main),
                "raw_model_quantity": _fmt(raw_main),
                "raw_model_unit": "t/y" if row["main_product"] not in {"electricity", "WAG_flared", "steam_placeholder"} else MAIN_PRODUCTS.get(plant, ("", "unit/y"))[1],
                "site_scaled_quantity": _fmt(site_main),
                "site_scaled_unit": "t/y" if row["main_product"] not in {"electricity", "WAG_flared", "steam_placeholder"} else MAIN_PRODUCTS.get(plant, ("", "unit/y"))[1],
                "scale_factor": _fmt(factor if mode == MODULE_SCALE_MODE else 1.0),
                "scale_mode": mode,
                "metric_scope": "compact_main_product",
                "key_input_1": row["key_input_1"],
                "key_input_1_ratio": row["key_input_1_ratio"],
                "key_input_1_unit": row["key_input_1_unit"],
                "key_input_2": row["key_input_2"],
                "key_input_2_ratio": row["key_input_2_ratio"],
                "key_input_2_unit": row["key_input_2_unit"],
                "electricity_MWh_per_t": row["electricity_MWh_per_t"],
                "NG_GJ_HHV_per_t": row["NG_GJ_HHV_per_t"],
                "WAG_output_carrier": carrier,
                "WAG_output_Nm3_per_t": row["WAG_output_Nm3_per_t"],
                "WAG_output_MWh_LHV_per_t": _fmt(wag_mwh) if carrier else "",
                "LHV_MJ_per_Nm3_used": lhv,
                "LHV_consistency_status": "pass" if lhv_counts[(configuration, horizon_hours)]["fail"] == 0 else "fail",
                "CO2_t_per_t": row["CO2_t_per_t"],
                "downstream_continuation_status": ds_status,
                "status": row["status"],
                "red_flags": ";".join(flags),
            }
        )
    return rows


def _summary_rows(
    downstream: list[dict[str, Any]],
    lhv_counts: dict[tuple[str, int], dict[str, int]],
    vf_rows: list[dict[str, Any]],
    scale_factors: dict[tuple[str, int], float],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    vf_stats: dict[tuple[str, int], dict[str, Any]] = {}
    for row in vf_rows:
        key = (row["configuration_id"], int(row["horizon_hours"]))
        vf_stats[key] = {
            "max": row["max_combined_vattenfall_wag_volume_Nm3_h"],
            "mean": row["mean_combined_vattenfall_wag_volume_Nm3_h"],
            "binding": row["binding_hours"],
        }
    downstream_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in downstream}
    all_rows: list[dict[str, Any]] = []
    by_horizon: dict[str, list[dict[str, Any]]] = {}
    for horizon, hours in HORIZONS.items():
        rows = []
        for row in _summary_source(horizon):
            key = (row["configuration_id"], hours)
            ds = downstream_by_key[key]
            counts = lhv_counts[key]
            vf = vf_stats[key]
            output = {
                **row,
                "scale_factor": _fmt(scale_factors[key]),
                "scale_mode": MODULE_SCALE_MODE,
                "target_site_t_y": TARGET_SITE_T_Y,
                "final_product_proxy_site_t_y": ds["final_product_proxy_site_t_y"],
                "final_product_proxy_fulfilment": ds["final_product_fulfilment"],
                "downstream_continuation_status": ds["downstream_continuation_status"],
                "LHV_consistency_pass_count": counts["pass"],
                "LHV_consistency_fail_count": counts["fail"],
                "WAG_balance_status": "closed",
                "max_combined_vattenfall_wag_volume_Nm3_h": vf["max"],
                "mean_combined_vattenfall_wag_volume_Nm3_h": vf["mean"],
                "vattenfall_binding_hours": vf["binding"],
                "terminal_inventory_status": row.get("terminal_inventory_status", ""),
            }
            rows.append(output)
            all_rows.append(output)
        by_horizon[horizon] = rows
    return all_rows, by_horizon


def _stage_gate(
    summaries: list[dict[str, Any]],
    compact: list[dict[str, Any]],
    downstream: list[dict[str, Any]],
    lhv_rows: list[dict[str, Any]],
    scale_audit: list[dict[str, Any]],
) -> dict[str, Any]:
    scale_flags = [row for row in scale_audit if row.get("red_flag") in {"raw_module_compared_to_full_site_anchor", "full_site_proxy_scaled_again", "scale_mode_missing", "scale_factor_missing_for_module_metric", "site_scaled_quantity_missing"}]
    return {
        "stage": STAGE,
        "decision": "pass_development_scale_downstream_lhv_repair_with_open_physical_gaps",
        "required_runs_executed": all(row["termination_condition"] == "optimal" for row in summaries),
        "scale_audit_required_red_flags": len(scale_flags),
        "c1_downstream_continuation_pass": all(
            row["downstream_continuation_status"].startswith("pass")
            for row in downstream
            if row["configuration"] == C1
        ),
        "lhv_consistency_fail_count": sum(1 for row in lhv_rows if row["status"] != "pass"),
        "c1_kgf1_active": any(row["configuration"] == C1 and row["plant"] == "KGF1" and row["active"] == "True" for row in compact),
        "c1_kgf2_inactive": all(row["active"] == "False" for row in compact if row["configuration"] == C1 and row["plant"] == "KGF2"),
        "c1_bf7_inactive": all(row["active"] == "False" for row in compact if row["configuration"] == C1 and row["plant"] == "BF7"),
        "steam_validation_anchor_active": False,
        "legacy_equal_wag_ng_boiler_split_active": False,
        "wag_first_allocation_preserved": True,
        "vattenfall_cap_policy": "combined_BFG_COG_BOFG_volume_cap_not_per_carrier",
        "vattenfall_combined_cap_Nm3_h": VATTENFALL_TOTAL_WAG_CAP_NM3_H,
        "anchors_used_as_constraints": False,
        "forbidden_economic_features_added": False,
        "executable_development_target_t_y": TARGET_SITE_T_Y,
        "output_directory": _rel(C5D_DIR),
    }


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
            "physical_fulfilment": row.get("physical_fulfilment", ""),
            "scale_factor": row["scale_factor"],
            "downstream_continuation_status": row["downstream_continuation_status"],
            "lhv_fail_count": row["LHV_consistency_fail_count"],
            "output_directory": _rel(C5D_DIR),
            "development_only": True,
        }
        for row in summary_rows
    ]


def _write_outputs() -> dict[str, Any]:
    C5D_DIR.mkdir(parents=True, exist_ok=True)
    run_s4_4c5c_plant_asset_conversion_diagnostics()
    scale_factors = _scale_factors()
    downstream = _raw_downstream_rows(scale_factors)
    plant_io = _plant_io_rows(scale_factors)
    ratios = _conversion_ratio_rows(scale_factors)
    wag = _wag_balance_rows(scale_factors)
    vf_rows = _vattenfall_hourly_rows()
    lhv_rows = _lhv_check_rows(wag, vf_rows)
    lhv_counts = _lhv_counts(lhv_rows)
    scale_audit = _scale_audit_rows(scale_factors, downstream, lhv_counts)
    anchor = _anchor_gap_rows(scale_audit)
    compact = _compact_rows(scale_factors, downstream, lhv_counts)
    summary_rows, summary_by_horizon = _summary_rows(downstream, lhv_counts, vf_rows, scale_factors)
    gate = _stage_gate(summary_rows, compact, downstream, lhv_rows, scale_audit)

    _write_json(C5D_DIR / "s4_4c5d_stage_gate.json", gate)
    _write_csv(C5D_DIR / "s4_4c5d_run_registry.csv", _run_registry(summary_rows))
    for horizon, rows in summary_by_horizon.items():
        _write_csv(C5D_DIR / f"s4_4c5d_{horizon}_summary.csv", rows)
    _write_csv(C5D_DIR / "s4_4c5d_scale_audit.csv", scale_audit)
    _write_csv(C5D_DIR / "s4_4c5d_downstream_continuation_dashboard.csv", downstream)
    _write_csv(C5D_DIR / "s4_4c5d_carrier_conversion_constants.csv", _carrier_conversion_constants_rows())
    _write_csv(C5D_DIR / "s4_4c5d_lhv_consistency_checks.csv", lhv_rows)
    _write_csv(C5D_DIR / "s4_4c5d_plant_carrier_io_annualised.csv", plant_io)
    _write_csv(C5D_DIR / "s4_4c5d_plant_conversion_ratios.csv", ratios)
    _write_csv(C5D_DIR / "s4_4c5d_wag_generation_consumption_by_plant.csv", wag)
    _write_csv(C5D_DIR / "s4_4c5d_vattenfall_cap_hourly.csv", vf_rows)
    _write_csv(C5D_DIR / "s4_4c5d_anchor_gap_dashboard.csv", anchor)
    _write_csv(C5D_DIR / "s4_4c5d_compact_table_for_chat.csv", compact)

    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": _rel(C5D_DIR),
        "rows": {
            "scale_audit": len(scale_audit),
            "downstream": len(downstream),
            "lhv_checks": len(lhv_rows),
            "plant_io": len(plant_io),
            "ratios": len(ratios),
            "wag": len(wag),
            "vattenfall": len(vf_rows),
            "anchor": len(anchor),
            "compact": len(compact),
        },
    }
    _write_json(C5D_DIR / "s4_4c5d_summary.json", summary)
    return summary


def run_s4_4c5d_scale_downstream_lhv_consistency_repair() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5d_scale_downstream_lhv_consistency_repair(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
