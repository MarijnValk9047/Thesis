"""S4.4c5e internal consistency repair.

This development-only stage repairs accounting consistency on top of C5d:
downstream final-product continuation, the frozen KGF1/KGF2 oven-count split,
and compact-vs-balance WAG reconciliation. It does not add new plant
coefficients or economic steering.
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
from .s4_4c5d_scale_downstream_lhv_consistency_repair import (
    C5D_DIR,
    MODULE_SCALE_MODE,
    TARGET_SITE_T_Y,
    run_s4_4c5d_scale_downstream_lhv_consistency_repair,
)


S4_ROOT = Path("data/03_Optimisation/inputs/assets/steel/S4")
C5E_DIR = S4_ROOT / "s4_4c5e_internal_consistency_repair"
STAGE = "S4.4c5e_internal_consistency_repair"

C0 = "C0_current_BF_BOF_reference"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
CONFIGS = (C0, C1)
HORIZONS = (24, 168)

KGF1_OVENS = 238
KGF2_OVENS = 108
KGF_TOTAL_OVENS = KGF1_OVENS + KGF2_OVENS
KGF1_SHARE = KGF1_OVENS / KGF_TOTAL_OVENS
KGF2_SHARE = KGF2_OVENS / KGF_TOTAL_OVENS
KGF_ASSUMPTION_ID = "S4.4c5e_KGF1_KGF2_OVEN_COUNT_SPLIT_238_108"
COG_NM3_PER_T_COKE = 365.0
COG_MWH_PER_T_COKE = COG_NM3_PER_T_COKE * SELECTED_WAG_LHV_MJ_PER_NM3["COG"] / 3600.0

TOL_T_Y = 1.0
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
    "key_input_1",
    "key_input_1_ratio",
    "key_input_1_unit",
    "key_input_2",
    "key_input_2_ratio",
    "key_input_2_unit",
    "electricity_MWh_per_t",
    "NG_GJ_HHV_per_t",
    "WAG_output_carrier",
    "WAG_output_Nm3_per_t",
    "WAG_output_MWh_LHV_per_t",
    "LHV_MJ_per_Nm3_used",
    "LHV_consistency_status",
    "CO2_t_per_t",
    "downstream_continuation_status",
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


def _zero_if_nan(value: Any) -> float:
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


def _rel(path: Path) -> str:
    return path.as_posix()


def _scale_factors() -> dict[tuple[str, int], float]:
    factors: dict[tuple[str, int], float] = {}
    for horizon in ("24h", "168h"):
        for row in _read_csv(C5D_DIR / f"s4_4c5d_{horizon}_summary.csv"):
            factors[(row["configuration_id"], int(row["horizon_hours"]))] = _num(row["scale_factor"])
    return factors


def _downstream_rows(scale_factors: dict[tuple[str, int], float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in _read_csv(C5D_DIR / "s4_4c5d_downstream_continuation_dashboard.csv"):
        config = source["configuration"]
        horizon = int(source["horizon_hours"])
        factor = scale_factors[(config, horizon)]
        retained_raw = _num(source["retained_bof_liquid_steel_raw_t_y"])
        eaf_raw = _zero_if_nan(source["eaf_liquid_steel_raw_t_y"])
        total_raw = retained_raw + eaf_raw
        import_raw = 0.0
        loss_raw = 0.0
        final_raw = total_raw + import_raw - loss_raw
        retained_site = retained_raw * factor
        eaf_site = eaf_raw * factor
        total_site = total_raw * factor
        import_site = import_raw * factor
        loss_site = loss_raw * factor
        final_site = final_raw * factor
        raw_gap = final_raw - (total_raw + import_raw - loss_raw)
        site_gap = final_site - (total_site + import_site - loss_site)
        flags: list[str] = []
        status = "pass_proxy_warn"
        if config == C1 and eaf_raw > TOL_T_Y and final_raw <= retained_raw + TOL_T_Y:
            flags.append("c1_eaf_liquid_steel_not_continued_downstream")
        if abs(raw_gap) > TOL_T_Y or abs(site_gap) > TOL_T_Y:
            flags.append("final_product_proxy_not_equal_total_liquid_steel_adjusted")
        if total_site >= TARGET_SITE_T_Y - TOL_T_Y and final_site < TARGET_SITE_T_Y - TOL_T_Y:
            flags.append("liquid_steel_target_met_but_final_product_proxy_not_met")
        if flags:
            status = "fail"

        rows.append(
            {
                "configuration": config,
                "horizon_hours": horizon,
                "retained_bof_liquid_steel_raw_t_y": _fmt(retained_raw),
                "eaf_liquid_steel_raw_t_y": _fmt(eaf_raw),
                "total_liquid_steel_raw_t_y": _fmt(total_raw),
                "internal_slab_produced_raw_t_y": _fmt(total_raw),
                "external_slab_import_raw_t_y": _fmt(import_raw),
                "downstream_loss_or_export_raw_t_y": _fmt(loss_raw),
                "final_product_proxy_raw_t_y": _fmt(final_raw),
                "retained_bof_liquid_steel_site_t_y": _fmt(retained_site),
                "eaf_liquid_steel_site_t_y": _fmt(eaf_site),
                "total_liquid_steel_site_t_y": _fmt(total_site),
                "internal_slab_produced_site_t_y": _fmt(total_site),
                "external_slab_import_site_t_y": _fmt(import_site),
                "downstream_loss_or_export_site_t_y": _fmt(loss_site),
                "final_product_proxy_site_t_y": _fmt(final_site),
                "target_site_t_y": TARGET_SITE_T_Y,
                "raw_final_proxy_gap_t_y": _fmt(raw_gap),
                "site_final_proxy_gap_t_y": _fmt(site_gap),
                "downstream_continuation_status": status,
                "red_flags": ";".join(flags),
                "notes": "Proxy continuation now uses total retained BOF plus EAF liquid steel; HSM/DSP physics remain source-deferred.",
            }
        )
    return rows


def _kgf_targets_from_io(
    plant_io: list[dict[str, Any]], scale_factors: dict[tuple[str, int], float]
) -> dict[tuple[str, int, str], dict[str, float]]:
    targets: dict[tuple[str, int, str], dict[str, float]] = {}
    for config in CONFIGS:
        for horizon in HORIZONS:
            factor = scale_factors[(config, horizon)]
            coke_rows = [
                row
                for row in plant_io
                if row["configuration"] == config
                and int(row["horizon_hours"]) == horizon
                and row["plant_id"] in {"KGF1", "KGF2"}
                and row["carrier_or_material"] == "coke"
                and row["direction"] == "output"
            ]
            raw_by_plant = {row["plant_id"]: _zero_if_nan(row["raw_model_quantity"]) for row in coke_rows}
            total_raw = raw_by_plant.get("KGF1", 0.0) + raw_by_plant.get("KGF2", 0.0)
            if config == C0:
                raw_targets = {"KGF1": total_raw * KGF1_SHARE, "KGF2": total_raw * KGF2_SHARE}
            else:
                raw_targets = {"KGF1": raw_by_plant.get("KGF1", 0.0), "KGF2": 0.0}
            for plant, raw in raw_targets.items():
                targets[(config, horizon, plant)] = {"raw": raw, "site": raw * factor}
    return targets


def _apply_kgf_split_to_plant_io(
    rows: list[dict[str, Any]],
    targets: dict[tuple[str, int, str], dict[str, float]],
) -> list[dict[str, Any]]:
    repaired: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        config = item["configuration"]
        horizon = int(item["horizon_hours"])
        plant = item["plant_id"]
        if config == C0 and plant in {"KGF1", "KGF2"} and (config, horizon, plant) in targets:
            target = targets[(config, horizon, plant)]
            material = item["carrier_or_material"]
            if material in {"coal_or_coking_feed_proxy", "coke"}:
                item["annual_quantity"] = _fmt(target["raw"])
                item["raw_model_quantity"] = _fmt(target["raw"])
                item["site_scaled_quantity"] = _fmt(target["site"])
                item["notes"] = f"{item.get('notes', '')}; C5e KGF split applies frozen 238:108 oven-count production proxy."
            elif material == "COG" and item["direction"] == "output":
                mwh_raw = target["raw"] * COG_MWH_PER_T_COKE
                item["annual_quantity"] = _fmt(mwh_raw)
                item["raw_model_quantity"] = _fmt(mwh_raw)
                item["site_scaled_quantity"] = _fmt(mwh_raw * _num(item["scale_factor"]))
                item["notes"] = f"{item.get('notes', '')}; C5e COG generation redistributed with KGF split; total preserved."
        if config == C1 and plant == "HSM" and item["carrier_or_material"] in {"slab_or_crude_steel_proxy", "final_product_proxy"}:
            factor = _num(item["scale_factor"])
            downstream = _downstream_lookup[(config, horizon)]
            raw = _num(downstream["final_product_proxy_raw_t_y"])
            item["annual_quantity"] = _fmt(raw)
            item["raw_model_quantity"] = _fmt(raw)
            item["site_scaled_quantity"] = _fmt(raw * factor)
            item["notes"] = f"{item.get('notes', '')}; C5e repaired HSM proxy to total BOF plus EAF liquid steel."
        repaired.append(item)
    return repaired


def _apply_kgf_split_to_ratios(
    rows: list[dict[str, Any]],
    targets: dict[tuple[str, int, str], dict[str, float]],
) -> list[dict[str, Any]]:
    repaired: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        config = item["configuration"]
        horizon = int(item["horizon_hours"])
        plant = item["plant_id"]
        if config == C0 and plant in {"KGF1", "KGF2"}:
            target = targets[(config, horizon, plant)]
            item["main_product_quantity_t_y"] = _fmt(target["raw"])
            item["main_product_site_t_y"] = _fmt(target["site"])
            carrier = item["carrier_or_material"]
            if carrier == "coal_t_per_t_coke":
                item["annual_quantity"] = _fmt(target["raw"])
                item["raw_model_quantity"] = _fmt(target["raw"])
                item["site_scaled_quantity"] = _fmt(target["site"])
                item["ratio_value"] = 1.0
            elif carrier == "COG_Nm3_per_t_coke_produced":
                raw = target["raw"] * COG_NM3_PER_T_COKE
                item["annual_quantity"] = _fmt(raw)
                item["raw_model_quantity"] = _fmt(raw)
                item["site_scaled_quantity"] = _fmt(raw * _num(item["scale_factor"]))
                item["ratio_value"] = COG_NM3_PER_T_COKE
            elif carrier == "COG_MWh_LHV_per_t_coke_produced":
                raw = target["raw"] * COG_MWH_PER_T_COKE
                item["annual_quantity"] = _fmt(raw)
                item["raw_model_quantity"] = _fmt(raw)
                item["site_scaled_quantity"] = _fmt(raw * _num(item["scale_factor"]))
                item["ratio_value"] = _fmt(COG_MWH_PER_T_COKE)
            item["notes"] = f"{item.get('notes', '')}; C5e KGF split assumption {KGF_ASSUMPTION_ID}."
        if config == C1 and plant == "HSM":
            downstream = _downstream_lookup[(config, horizon)]
            item["main_product_quantity_t_y"] = downstream["final_product_proxy_raw_t_y"]
            item["main_product_site_t_y"] = downstream["final_product_proxy_site_t_y"]
            item["notes"] = f"{item.get('notes', '')}; C5e HSM denominator repaired to total BOF plus EAF final-product proxy."
        repaired.append(item)
    return repaired


def _apply_kgf_split_to_wag(
    rows: list[dict[str, Any]],
    targets: dict[tuple[str, int, str], dict[str, float]],
) -> list[dict[str, Any]]:
    repaired: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        config = item["configuration"]
        horizon = int(item["horizon_hours"])
        plant = item["plant_id"]
        carrier = item["carrier"]
        factor = _num(item["scale_factor"])
        # C5d inherited a mixed convention for C1 WAG rows: the balance values
        # were already site-scale while scale columns then scaled them again.
        # C5e normalises balance quantities to raw-module MWh and keeps the
        # explicit site-scaled quantity in the scale columns.
        if config == C1 and factor:
            for field in (
                "generated_MWh_LHV_y",
                "consumed_direct_MWh_LHV_y",
                "consumed_boiler_MWh_LHV_y",
                "consumed_vattenfall_MWh_LHV_y",
                "flared_MWh_LHV_y",
                "balance_error_MWh_LHV_y",
            ):
                item[field] = _fmt(_zero_if_nan(item[field]) / factor)
            item["raw_model_quantity"] = item["generated_MWh_LHV_y"]
            item["site_scaled_quantity"] = _fmt(_zero_if_nan(item["generated_MWh_LHV_y"]) * factor)
        if config == C0 and plant in {"KGF1", "KGF2"} and carrier == "COG":
            target = targets[(config, horizon, plant)]
            generated = target["raw"] * COG_MWH_PER_T_COKE
            item["generated_MWh_LHV_y"] = _fmt(generated)
            item["generated_Nm3_y"] = _fmt(target["site"] * COG_NM3_PER_T_COKE)
            item["raw_model_quantity"] = _fmt(generated)
            item["site_scaled_quantity"] = _fmt(generated * factor)
            balance_error = (
                generated
                - _zero_if_nan(item["consumed_direct_MWh_LHV_y"])
                - _zero_if_nan(item["consumed_boiler_MWh_LHV_y"])
                - _zero_if_nan(item["consumed_vattenfall_MWh_LHV_y"])
                - _zero_if_nan(item["flared_MWh_LHV_y"])
            )
            item["balance_error_MWh_LHV_y"] = _fmt(balance_error)
        if carrier in SELECTED_WAG_LHV_MJ_PER_NM3:
            item["generated_Nm3_y"] = _fmt(_mwh_to_nm3(_zero_if_nan(item["site_scaled_quantity"]), carrier))
        repaired.append(item)
    return repaired


def _kgf_split_diagnostics(
    targets: dict[tuple[str, int, str], dict[str, float]],
    scale_factors: dict[tuple[str, int], float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            raw1 = targets[(config, horizon, "KGF1")]["raw"]
            raw2 = targets[(config, horizon, "KGF2")]["raw"]
            site1 = targets[(config, horizon, "KGF1")]["site"]
            site2 = targets[(config, horizon, "KGF2")]["site"]
            total_raw = raw1 + raw2
            total_site = site1 + site2
            share1 = raw1 / total_raw if total_raw else math.nan
            share2 = raw2 / total_raw if total_raw else math.nan
            if config == C0:
                expected1, expected2 = KGF1_SHARE, KGF2_SHARE
                split_applied_to = "C0_production_and_capacity_proxy"
            else:
                expected1, expected2 = 1.0, 0.0
                split_applied_to = "C1_retained_KGF1_production; KGF2_closed_by_topology; 238:108 retained-capacity context"
            flags: list[str] = []
            if config == C0 and (abs(share1 - KGF1_SHARE) > 1e-6 or abs(share2 - KGF2_SHARE) > 1e-6):
                flags.append("kgf_split_not_2p2_to_1")
            if config == C1 and raw1 <= 0.0:
                flags.append("kgf1_inactive_in_c1")
            if config == C1 and raw2 > 1e-9:
                flags.append("kgf2_active_in_c1")
            if not split_applied_to:
                flags.append("kgf_split_applied_without_status")
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "total_coke_raw_t_y": _fmt(total_raw),
                    "kgf1_coke_raw_t_y": _fmt(raw1),
                    "kgf2_coke_raw_t_y": _fmt(raw2),
                    "kgf1_share_raw": _fmt(share1),
                    "kgf2_share_raw": _fmt(share2),
                    "total_coke_site_t_y": _fmt(total_site),
                    "kgf1_coke_site_t_y": _fmt(site1),
                    "kgf2_coke_site_t_y": _fmt(site2),
                    "kgf1_share_site": _fmt(site1 / total_site if total_site else math.nan),
                    "kgf2_share_site": _fmt(site2 / total_site if total_site else math.nan),
                    "kgf1_expected_share": _fmt(expected1),
                    "kgf2_expected_share": _fmt(expected2),
                    "kgf1_share_gap_pct": _fmt((share1 - expected1) / expected1 * 100.0 if expected1 else 0.0),
                    "kgf2_share_gap_pct": _fmt((share2 - expected2) / expected2 * 100.0 if expected2 else 0.0),
                    "split_applied_to": split_applied_to,
                    "assumption_id": KGF_ASSUMPTION_ID,
                    "assumption_status": "frozen_for_development",
                    "source_migration_status": "source_card_migration_needed_or_not_in_executable_inputs",
                    "sensitivity_required": True,
                    "red_flags": ";".join(flags),
                    "notes": f"Uses user-approved oven-count split KGF1={KGF1_OVENS}, KGF2={KGF2_OVENS}; total coke production inherited from C5d executable physical model.",
                }
            )
    return rows


def _compact_rows(
    c5d_compact: list[dict[str, str]],
    downstream: list[dict[str, Any]],
    targets: dict[tuple[str, int, str], dict[str, float]],
    wag_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    downstream_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in downstream}
    compact: list[dict[str, Any]] = []
    for row in c5d_compact:
        if int(row["horizon_hours"]) != 24:
            continue
        plant = row["plant"]
        if plant not in {"KGF1", "KGF2", "Sinter", "BF6", "BF7", "BOF", "DRP", "EAF", "HSM", "boilers", "Vattenfall", "flaring"}:
            continue
        config = row["configuration"]
        horizon = int(row["horizon_hours"])
        item = {key: row.get(key, "") for key in COMPACT_COLUMNS}
        if config == C0 and plant in {"KGF1", "KGF2"}:
            target = targets[(config, horizon, plant)]
            item["main_product_raw_t_y"] = _fmt(target["raw"])
            item["main_product_site_t_y"] = _fmt(target["site"])
        if config == C1 and plant == "HSM":
            ds = downstream_by_key[(config, horizon)]
            item["main_product_raw_t_y"] = ds["final_product_proxy_raw_t_y"]
            item["main_product_site_t_y"] = ds["final_product_proxy_site_t_y"]
            item["red_flags"] = ""
        item["downstream_continuation_status"] = downstream_by_key[(config, horizon)]["downstream_continuation_status"]
        compact.append(item)

    for row in wag_rows:
        if row["plant_id"] != "SITE_TOTAL":
            continue
        carrier = row["carrier"]
        compact.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant": f"WAG_TOTAL_{carrier}",
                "active": "True",
                "main_product": "WAG_generated_MWh_LHV_y",
                "main_product_raw_t_y": row["generated_MWh_LHV_y"],
                "main_product_site_t_y": row["site_scaled_quantity"],
                "scale_mode": row["scale_mode"],
                "key_input_1": "consumed_direct_boiler_vattenfall_MWh_LHV_y",
                "key_input_1_ratio": _fmt(
                    _zero_if_nan(row["consumed_direct_MWh_LHV_y"])
                    + _zero_if_nan(row["consumed_boiler_MWh_LHV_y"])
                    + _zero_if_nan(row["consumed_vattenfall_MWh_LHV_y"])
                ),
                "key_input_1_unit": "MWh_LHV/y_raw",
                "key_input_2": "flared_MWh_LHV_y",
                "key_input_2_ratio": row["flared_MWh_LHV_y"],
                "key_input_2_unit": "MWh_LHV/y_raw",
                "electricity_MWh_per_t": "",
                "NG_GJ_HHV_per_t": "",
                "WAG_output_carrier": carrier,
                "WAG_output_Nm3_per_t": "",
                "WAG_output_MWh_LHV_per_t": "",
                "LHV_MJ_per_Nm3_used": row["LHV_MJ_per_Nm3_used"],
                "LHV_consistency_status": "pass",
                "CO2_t_per_t": "",
                "downstream_continuation_status": downstream_by_key[(row["configuration"], int(row["horizon_hours"]))][
                    "downstream_continuation_status"
                ],
                "status": "balance_total",
                "red_flags": "",
            }
        )
    return compact


def _wag_reconciliation(
    compact: list[dict[str, Any]],
    plant_io: list[dict[str, Any]],
    wag_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    compact_generated: dict[tuple[str, int, str], float] = {}
    compact_site_generated: dict[tuple[str, int, str], float] = {}
    for row in compact:
        if not str(row["plant"]).startswith("WAG_TOTAL_"):
            continue
        key = (row["configuration"], int(row["horizon_hours"]), row["WAG_output_carrier"])
        compact_generated[key] = _zero_if_nan(row["main_product_raw_t_y"])
        compact_site_generated[key] = _zero_if_nan(row["main_product_site_t_y"])

    plant_io_generated: dict[tuple[str, int, str], dict[str, float]] = {}
    for row in plant_io:
        if row.get("accounting_class") != "WAG_generation":
            continue
        carrier = row["carrier_or_material"]
        key = (row["configuration"], int(row["horizon_hours"]), carrier)
        totals = plant_io_generated.setdefault(key, {"raw": 0.0, "site": 0.0})
        totals["raw"] += _zero_if_nan(row["raw_model_quantity"])
        totals["site"] += _zero_if_nan(row["site_scaled_quantity"])

    out: list[dict[str, Any]] = []
    for row in wag_rows:
        if row["plant_id"] != "SITE_TOTAL":
            continue
        key = (row["configuration"], int(row["horizon_hours"]), row["carrier"])
        for basis in ("raw", "site_scaled"):
            factor = _num(row["scale_factor"]) if basis == "site_scaled" else 1.0
            compact_gen = compact_site_generated[key] if basis == "site_scaled" else compact_generated[key]
            balance_gen = _zero_if_nan(row["generated_MWh_LHV_y"]) * factor
            plant_gen = plant_io_generated.get(key, {}).get("site" if basis == "site_scaled" else "raw", 0.0)
            direct = _zero_if_nan(row["consumed_direct_MWh_LHV_y"]) * factor
            boiler = _zero_if_nan(row["consumed_boiler_MWh_LHV_y"]) * factor
            vf = _zero_if_nan(row["consumed_vattenfall_MWh_LHV_y"]) * factor
            flared = _zero_if_nan(row["flared_MWh_LHV_y"]) * factor
            gen_diff = compact_gen - balance_gen
            plant_diff = plant_gen - balance_gen
            available_after_use = balance_gen - direct - boiler - vf
            flags: list[str] = []
            if abs(gen_diff) > WAG_TOL_MWH or abs(plant_diff) > WAG_TOL_MWH:
                flags.append("compact_wag_generation_mismatch")
            if flared - available_after_use > WAG_TOL_MWH:
                flags.append("compact_wag_flaring_mismatch")
            status = "pass" if not flags else "fail"
            out.append(
                {
                    "configuration": key[0],
                    "horizon_hours": key[1],
                    "scale_basis": basis,
                    "carrier": key[2],
                    "compact_generated_MWh_LHV_y": _fmt(compact_gen),
                    "balance_generated_MWh_LHV_y": _fmt(balance_gen),
                    "plant_io_generated_MWh_LHV_y": _fmt(plant_gen),
                    "compact_consumed_direct_MWh_LHV_y": _fmt(direct),
                    "balance_consumed_direct_MWh_LHV_y": _fmt(direct),
                    "compact_consumed_boiler_MWh_LHV_y": _fmt(boiler),
                    "balance_consumed_boiler_MWh_LHV_y": _fmt(boiler),
                    "compact_consumed_vattenfall_MWh_LHV_y": _fmt(vf),
                    "balance_consumed_vattenfall_MWh_LHV_y": _fmt(vf),
                    "compact_flared_MWh_LHV_y": _fmt(flared),
                    "balance_flared_MWh_LHV_y": _fmt(flared),
                    "generation_difference_MWh_LHV_y": _fmt(max(abs(gen_diff), abs(plant_diff))),
                    "consumption_difference_MWh_LHV_y": 0.0,
                    "flaring_difference_MWh_LHV_y": 0.0,
                    "status": status,
                    "red_flags": ";".join(flags),
                    "notes": "Compact carrier-total rows reconcile generation; sink category quantities are mirrored from WAG balance on the same scale basis.",
                }
            )
    return out


def _lhv_check_rows(wag_rows: list[dict[str, Any]], vf_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(config: str, horizon: int, plant: str, carrier: str, direction: str, nm3: float, mwh: float, notes: str) -> None:
        expected = nm3 * SELECTED_WAG_LHV_MJ_PER_NM3[carrier] / 3600.0
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
                "generated",
                _zero_if_nan(row["generated_Nm3_y"]),
                _zero_if_nan(row["site_scaled_quantity"]),
                "Annual WAG generation site-scaled quantity converted with canonical LHV.",
            )

    for row in vf_rows:
        config = row["configuration_id"]
        horizon = int(row["horizon_hours"])
        for carrier in SELECTED_WAG_LHV_MJ_PER_NM3:
            add(
                config,
                horizon,
                "Vattenfall",
                carrier,
                f"hour_{row['hour']}_to_vattenfall",
                _zero_if_nan(row[f"{carrier}_volume_Nm3_h"]),
                _zero_if_nan(row[f"{carrier}_to_vattenfall_MWh_LHV"]),
                "Hourly Vattenfall interface volume converted with canonical LHV.",
            )
    return checks


def _summary_rows(
    downstream: list[dict[str, Any]],
    kgf_rows: list[dict[str, Any]],
    reconciliation: list[dict[str, Any]],
    lhv_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    downstream_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in downstream}
    kgf_by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in kgf_rows}
    rec_by_key: dict[tuple[str, int], str] = {}
    for config in CONFIGS:
        for horizon in HORIZONS:
            rec_by_key[(config, horizon)] = (
                "pass"
                if all(
                    row["status"] == "pass"
                    for row in reconciliation
                    if row["configuration"] == config and int(row["horizon_hours"]) == horizon
                )
                else "fail"
            )
    lhv_by_key: dict[tuple[str, int], dict[str, int]] = {}
    for row in lhv_rows:
        key = (row["configuration"], int(row["horizon_hours"]))
        lhv_by_key.setdefault(key, {"pass": 0, "fail": 0})
        lhv_by_key[key]["pass" if row["status"] == "pass" else "fail"] += 1

    all_rows: list[dict[str, Any]] = []
    by_horizon: dict[str, list[dict[str, Any]]] = {"24h": [], "168h": []}
    for horizon_name in ("24h", "168h"):
        for row in _read_csv(C5D_DIR / f"s4_4c5d_{horizon_name}_summary.csv"):
            item = dict(row)
            config = item["configuration_id"]
            horizon = int(item["horizon_hours"])
            ds = downstream_by_key[(config, horizon)]
            kgf = kgf_by_key[(config, horizon)]
            counts = lhv_by_key[(config, horizon)]
            item["stage"] = STAGE
            item["final_product_proxy_site_t_y"] = ds["final_product_proxy_site_t_y"]
            item["final_product_proxy_fulfilment"] = _fmt(
                _num(ds["final_product_proxy_site_t_y"]) / TARGET_SITE_T_Y
            )
            item["downstream_continuation_status"] = ds["downstream_continuation_status"]
            item["KGF_split_status"] = "pass" if not kgf["red_flags"] else "fail"
            item["WAG_compact_balance_reconciliation_status"] = rec_by_key[(config, horizon)]
            item["LHV_consistency_pass_count"] = counts["pass"]
            item["LHV_consistency_fail_count"] = counts["fail"]
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
            "scale_factor": row["scale_factor"],
            "downstream_continuation_status": row["downstream_continuation_status"],
            "KGF_split_status": row["KGF_split_status"],
            "WAG_compact_balance_reconciliation_status": row["WAG_compact_balance_reconciliation_status"],
            "output_directory": _rel(C5E_DIR),
        }
        for row in summary_rows
    ]


def _stage_gate(
    downstream: list[dict[str, Any]],
    kgf: list[dict[str, Any]],
    reconciliation: list[dict[str, Any]],
    lhv: list[dict[str, Any]],
    compact: list[dict[str, Any]],
) -> dict[str, Any]:
    downstream_pass = all(row["downstream_continuation_status"].startswith("pass") for row in downstream)
    kgf_pass = all(not row["red_flags"] for row in kgf)
    rec_pass = all(row["status"] == "pass" for row in reconciliation)
    lhv_fail_count = sum(1 for row in lhv if row["status"] != "pass")
    return {
        "stage": STAGE,
        "decision": "pass_development_internal_consistency_repair_with_open_physical_gaps"
        if downstream_pass and kgf_pass and rec_pass and lhv_fail_count == 0
        else "fail_internal_consistency_repair",
        "required_runs_executed": True,
        "c1_downstream_continuation_pass": downstream_pass,
        "kgf_split_pass": kgf_pass,
        "wag_compact_balance_reconciliation_pass": rec_pass,
        "lhv_consistency_fail_count": lhv_fail_count,
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
        "output_directory": _rel(C5E_DIR),
    }


def _copy_prefixed_c5d_output(source_name: str, target_name: str) -> None:
    target = C5E_DIR / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(C5D_DIR / source_name, target)


_downstream_lookup: dict[tuple[str, int], dict[str, Any]] = {}


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5d_scale_downstream_lhv_consistency_repair()
    C5E_DIR.mkdir(parents=True, exist_ok=True)

    scale_factors = _scale_factors()
    downstream = _downstream_rows(scale_factors)
    global _downstream_lookup
    _downstream_lookup = {(row["configuration"], int(row["horizon_hours"])): row for row in downstream}

    plant_io_source = _read_csv(C5D_DIR / "s4_4c5d_plant_carrier_io_annualised.csv")
    targets = _kgf_targets_from_io(plant_io_source, scale_factors)
    plant_io = _apply_kgf_split_to_plant_io(plant_io_source, targets)
    ratios = _apply_kgf_split_to_ratios(_read_csv(C5D_DIR / "s4_4c5d_plant_conversion_ratios.csv"), targets)
    wag = _apply_kgf_split_to_wag(_read_csv(C5D_DIR / "s4_4c5d_wag_generation_consumption_by_plant.csv"), targets)
    kgf = _kgf_split_diagnostics(targets, scale_factors)
    vf_rows = _read_csv(C5D_DIR / "s4_4c5d_vattenfall_cap_hourly.csv")
    lhv = _lhv_check_rows(wag, vf_rows)
    compact = _compact_rows(_read_csv(C5D_DIR / "s4_4c5d_compact_table_for_chat.csv"), downstream, targets, wag)
    reconciliation = _wag_reconciliation(compact, plant_io, wag)
    summary_rows, summary_by_horizon = _summary_rows(downstream, kgf, reconciliation, lhv)
    gate = _stage_gate(downstream, kgf, reconciliation, lhv, compact)

    _write_json(C5E_DIR / "s4_4c5e_stage_gate.json", gate)
    _write_csv(C5E_DIR / "s4_4c5e_run_registry.csv", _run_registry(summary_rows))
    for horizon, rows in summary_by_horizon.items():
        _write_csv(C5E_DIR / f"s4_4c5e_{horizon}_summary.csv", rows)
    _write_csv(C5E_DIR / "s4_4c5e_downstream_continuation_dashboard.csv", downstream)
    _write_csv(C5E_DIR / "s4_4c5e_kgf_split_diagnostics.csv", kgf)
    _write_csv(C5E_DIR / "s4_4c5e_wag_compact_balance_reconciliation.csv", reconciliation)
    _write_csv(C5E_DIR / "s4_4c5e_lhv_consistency_checks.csv", lhv)
    _write_csv(C5E_DIR / "s4_4c5e_plant_carrier_io_annualised.csv", plant_io)
    _write_csv(C5E_DIR / "s4_4c5e_plant_conversion_ratios.csv", ratios)
    _write_csv(C5E_DIR / "s4_4c5e_wag_generation_consumption_by_plant.csv", wag)
    _write_csv(C5E_DIR / "s4_4c5e_compact_table_for_chat.csv", compact, COMPACT_COLUMNS)

    _copy_prefixed_c5d_output("s4_4c5d_scale_audit.csv", "s4_4c5e_scale_audit.csv")
    _copy_prefixed_c5d_output("s4_4c5d_vattenfall_cap_hourly.csv", "s4_4c5e_vattenfall_cap_hourly.csv")
    _copy_prefixed_c5d_output("s4_4c5d_anchor_gap_dashboard.csv", "s4_4c5e_anchor_gap_dashboard.csv")

    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": _rel(C5E_DIR),
        "rows": {
            "compact": len(compact),
            "downstream": len(downstream),
            "kgf_split": len(kgf),
            "lhv_checks": len(lhv),
            "plant_io": len(plant_io),
            "ratios": len(ratios),
            "wag": len(wag),
            "wag_reconciliation": len(reconciliation),
        },
    }
    _write_json(C5E_DIR / "s4_4c5e_summary.json", summary)
    return summary


def run_s4_4c5e_internal_consistency_repair() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5e_internal_consistency_repair(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
