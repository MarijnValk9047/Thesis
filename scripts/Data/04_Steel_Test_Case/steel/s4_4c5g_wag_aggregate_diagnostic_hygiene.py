"""S4.4c5g WAG aggregate diagnostic hygiene.

This stage leaves the C5f accounting layer intact and adds an aggregate WAG
invariant plus a corrected compact table. The fix is diagnostic-only: C5f's
per-carrier WAG balance closes, but its compact flaring row was still inherited
from C5e and was not on the same net-surplus semantic basis.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C5F_DIR,
    COMPACT_COLUMNS,
    CONFIGS,
    HORIZONS,
    KGF_PLANTS,
    S4_ROOT,
    WAG_TOL_MWH,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
    run_s4_4c5f_coking_plant_minimal_parameterisation,
)


C5G_DIR = S4_ROOT / "s4_4c5g_wag_aggregate_diagnostic_hygiene"
STAGE = "S4.4c5g_wag_aggregate_diagnostic_hygiene"
WAG_CARRIERS = ("BFG", "COG", "BOFG")

AGGREGATE_COLUMNS = [
    "configuration",
    "horizon_hours",
    "scale_basis",
    "BFG_generated_MWh_y",
    "COG_generated_MWh_y",
    "BOFG_generated_MWh_y",
    "total_WAG_generated_MWh_y",
    "total_WAG_direct_use_MWh_y",
    "total_WAG_boiler_use_MWh_y",
    "total_WAG_vattenfall_use_MWh_y",
    "total_WAG_flared_MWh_y",
    "total_WAG_explicit_other_sink_or_loss_MWh_y",
    "total_WAG_accounted_MWh_y",
    "balance_error_MWh_y",
    "balance_error_pct",
    "status",
    "red_flags",
    "notes",
]


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _scaled(row: dict[str, str], field: str, basis: str) -> float:
    raw = _zero(row[field])
    if basis == "raw":
        return raw
    factor = _zero(row.get("scale_factor")) or 1.0
    if field == "generated_MWh_LHV_y" and row.get("site_scaled_quantity") not in (None, ""):
        return _zero(row["site_scaled_quantity"])
    return raw * factor


def _site_total_rows(wag_rows: list[dict[str, str]], config: str, horizon: int) -> dict[str, dict[str, str]]:
    rows = {
        row["carrier"]: row
        for row in wag_rows
        if row["configuration"] == config
        and int(row["horizon_hours"]) == horizon
        and row["plant_id"] == "SITE_TOTAL"
        and row["carrier"] in WAG_CARRIERS
    }
    return rows


def _wag_aggregate_invariant_rows(wag_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            carrier_rows = _site_total_rows(wag_rows, config, horizon)
            for basis in ("raw", "site_scaled"):
                flags: list[str] = []
                generated_by_carrier: dict[str, float] = {}
                direct = boiler = vattenfall = flared = 0.0

                for carrier in WAG_CARRIERS:
                    row = carrier_rows.get(carrier)
                    if row is None:
                        flags.append(f"{carrier}_missing_from_site_total_wag_balance")
                        generated_by_carrier[carrier] = 0.0
                        continue
                    generated_by_carrier[carrier] = _scaled(row, "generated_MWh_LHV_y", basis)
                    direct += _scaled(row, "consumed_direct_MWh_LHV_y", basis)
                    boiler += _scaled(row, "consumed_boiler_MWh_LHV_y", basis)
                    vattenfall += _scaled(row, "consumed_vattenfall_MWh_LHV_y", basis)
                    flared += _scaled(row, "flared_MWh_LHV_y", basis)

                generated = sum(generated_by_carrier.values())
                explicit_other = generated - direct - boiler - vattenfall - flared
                if abs(explicit_other) <= WAG_TOL_MWH:
                    explicit_other = 0.0
                elif explicit_other > 0:
                    flags.append("explicit_other_sink_or_loss_present")
                else:
                    flags.append("explicit_other_source_or_import_needed")

                accounted = direct + boiler + vattenfall + flared + explicit_other
                balance_error = generated - accounted
                balance_error_pct = balance_error / generated * 100.0 if abs(generated) > 1e-12 else 0.0
                if flared > generated + max(0.0, -explicit_other) + WAG_TOL_MWH:
                    flags.append("total_wag_flared_exceeds_generated")
                if abs(balance_error) > WAG_TOL_MWH:
                    flags.append("aggregate_wag_balance_error")

                status = "pass" if not flags else "fail"
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "scale_basis": basis,
                        "BFG_generated_MWh_y": _fmt(generated_by_carrier["BFG"]),
                        "COG_generated_MWh_y": _fmt(generated_by_carrier["COG"]),
                        "BOFG_generated_MWh_y": _fmt(generated_by_carrier["BOFG"]),
                        "total_WAG_generated_MWh_y": _fmt(generated),
                        "total_WAG_direct_use_MWh_y": _fmt(direct),
                        "total_WAG_boiler_use_MWh_y": _fmt(boiler),
                        "total_WAG_vattenfall_use_MWh_y": _fmt(vattenfall),
                        "total_WAG_flared_MWh_y": _fmt(flared),
                        "total_WAG_explicit_other_sink_or_loss_MWh_y": _fmt(explicit_other),
                        "total_WAG_accounted_MWh_y": _fmt(accounted),
                        "balance_error_MWh_y": _fmt(balance_error),
                        "balance_error_pct": _fmt(balance_error_pct),
                        "status": status,
                        "red_flags": ";".join(flags),
                        "notes": "Aggregates C5f SITE_TOTAL WAG rows on one scale basis. COG generated is net surplus after KGF self-use.",
                    }
                )
    return rows


def _aggregate_by_key(aggregate: list[dict[str, Any]]) -> dict[tuple[str, int, str], dict[str, Any]]:
    return {
        (row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row
        for row in aggregate
    }


def _compact_template(config: str, horizon: int, plant: str, main_product: str, raw: float, site: float, status: str) -> dict[str, Any]:
    return {
        "configuration": config,
        "horizon_hours": horizon,
        "plant": plant,
        "active": "True",
        "main_product": main_product,
        "main_product_raw_t_y": _fmt(raw),
        "main_product_site_t_y": _fmt(site),
        "scale_mode": "module_scaled_to_site_target",
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
        "WAG_output_carrier": "ALL_WAG",
        "WAG_output_MWh_LHV_per_t": "",
        "LHV_consistency_status": "pass",
        "carbon_accounting_status": "WAG_network_balance_only",
        "status": status,
        "red_flags": "",
    }


def _fixed_compact_rows(c5f_compact: list[dict[str, str]], aggregate: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in c5f_compact:
        plant = row["plant"]
        if plant.startswith("WAG_TOTAL_") or plant == "flaring":
            continue
        rows.append(dict(row))

    aggregate_by_key = _aggregate_by_key(aggregate)
    for config in CONFIGS:
        for horizon in HORIZONS:
            raw = aggregate_by_key[(config, horizon, "raw")]
            site = aggregate_by_key[(config, horizon, "site_scaled")]
            for carrier in WAG_CARRIERS:
                rows.append(
                    {
                        **_compact_template(
                            config,
                            horizon,
                            f"WAG_TOTAL_{carrier}_GENERATED",
                            "WAG_generated_MWh_LHV_y_same_basis",
                            _zero(raw[f"{carrier}_generated_MWh_y"]),
                            _zero(site[f"{carrier}_generated_MWh_y"]),
                            "generated_total_same_basis",
                        ),
                        "WAG_output_carrier": carrier,
                    }
                )

            rows.append(
                _compact_template(
                    config,
                    horizon,
                    "WAG_TOTAL_ALL_GENERATED",
                    "WAG_generated_MWh_LHV_y_same_basis",
                    _zero(raw["total_WAG_generated_MWh_y"]),
                    _zero(site["total_WAG_generated_MWh_y"]),
                    "generated_total_same_basis",
                )
            )
            rows.append(
                _compact_template(
                    config,
                    horizon,
                    "WAG_TOTAL_ALL_ACCOUNTED",
                    "WAG_accounted_MWh_LHV_y_same_basis",
                    _zero(raw["total_WAG_accounted_MWh_y"]),
                    _zero(site["total_WAG_accounted_MWh_y"]),
                    "balance_total_same_basis",
                )
            )
            rows.append(
                _compact_template(
                    config,
                    horizon,
                    "flaring",
                    "WAG_flared_MWh_LHV_y_same_basis",
                    _zero(raw["total_WAG_flared_MWh_y"]),
                    _zero(site["total_WAG_flared_MWh_y"]),
                    "flared_total_same_basis",
                )
            )
    return rows


def _compact_aggregate_reconciliation(compact: list[dict[str, Any]], aggregate: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    aggregate_by_key = _aggregate_by_key(aggregate)
    compact_by_key = {(row["configuration"], int(row["horizon_hours"]), row["plant"]): row for row in compact}
    for config in CONFIGS:
        for horizon in HORIZONS:
            raw = aggregate_by_key[(config, horizon, "raw")]
            site = aggregate_by_key[(config, horizon, "site_scaled")]
            checks = [
                ("WAG_TOTAL_ALL_GENERATED", "total_WAG_generated_MWh_y"),
                ("WAG_TOTAL_ALL_ACCOUNTED", "total_WAG_accounted_MWh_y"),
                ("flaring", "total_WAG_flared_MWh_y"),
            ]
            checks.extend((f"WAG_TOTAL_{carrier}_GENERATED", f"{carrier}_generated_MWh_y") for carrier in WAG_CARRIERS)
            for plant, field in checks:
                compact_row = compact_by_key[(config, horizon, plant)]
                raw_diff = _zero(compact_row["main_product_raw_t_y"]) - _zero(raw[field])
                site_diff = _zero(compact_row["main_product_site_t_y"]) - _zero(site[field])
                max_abs = max(abs(raw_diff), abs(site_diff))
                status = "pass" if max_abs <= WAG_TOL_MWH else "fail"
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "compact_row": plant,
                        "aggregate_field": field,
                        "raw_difference_MWh_y": _fmt(raw_diff),
                        "site_scaled_difference_MWh_y": _fmt(site_diff),
                        "status": status,
                        "red_flags": "" if status == "pass" else "compact_aggregate_mismatch",
                        "notes": "C5g compact WAG rows are regenerated from the aggregate invariant table.",
                    }
                )
    return rows


def _copy_c5f(filename: str, output_name: str | None = None) -> None:
    target = C5G_DIR / (output_name or filename.replace("s4_4c5f_", "s4_4c5g_"))
    shutil.copyfile(C5F_DIR / filename, target)


def _stage_gate(aggregate: list[dict[str, Any]], reconciliation: list[dict[str, Any]], lhv: list[dict[str, str]]) -> dict[str, Any]:
    aggregate_failures = [row for row in aggregate if row["status"] != "pass"]
    reconciliation_failures = [row for row in reconciliation if row["status"] != "pass"]
    lhv_failures = [row for row in lhv if row["status"] != "pass"]
    c1_24_raw = next(
        row
        for row in aggregate
        if row["configuration"].startswith("C1") and int(row["horizon_hours"]) == 24 and row["scale_basis"] == "raw"
    )
    c1_24_site = next(
        row
        for row in aggregate
        if row["configuration"].startswith("C1") and int(row["horizon_hours"]) == 24 and row["scale_basis"] == "site_scaled"
    )
    return {
        "stage": STAGE,
        "decision": "pass_development_wag_aggregate_diagnostic_hygiene" if not aggregate_failures and not reconciliation_failures and not lhv_failures else "fail_development_wag_aggregate_diagnostic_hygiene",
        "output_directory": _rel(C5G_DIR),
        "aggregate_invariant_rows": len(aggregate),
        "aggregate_invariant_fail_count": len(aggregate_failures),
        "compact_aggregate_reconciliation_fail_count": len(reconciliation_failures),
        "lhv_consistency_fail_count": len(lhv_failures),
        "c1_24_total_wag_generated_raw_MWh_y": _zero(c1_24_raw["total_WAG_generated_MWh_y"]),
        "c1_24_total_wag_flared_raw_MWh_y": _zero(c1_24_raw["total_WAG_flared_MWh_y"]),
        "c1_24_total_wag_generated_site_MWh_y": _zero(c1_24_site["total_WAG_generated_MWh_y"]),
        "c1_24_total_wag_flared_site_MWh_y": _zero(c1_24_site["total_WAG_flared_MWh_y"]),
        "diagnosis": "C5f per-carrier WAG balances close; visible inconsistency came from a stale compact flaring row inherited from C5e.",
        "anchors_used_as_constraints": False,
        "forbidden_economic_features_added": False,
    }


def _run_registry(gate: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "stage": STAGE,
            "configuration": config,
            "horizon_hours": horizon,
            "solver_status": "not_rerun_accounting_hygiene_only",
            "source_stage": "S4.4c5f_coking_plant_minimal_parameterisation",
            "aggregate_invariant_status": "pass" if gate["aggregate_invariant_fail_count"] == 0 else "fail",
            "compact_reconciliation_status": "pass" if gate["compact_aggregate_reconciliation_fail_count"] == 0 else "fail",
            "output_directory": gate["output_directory"],
            "notes": "Diagnostic hygiene run; solver outputs are inherited from C5f.",
        }
        for config in CONFIGS
        for horizon in HORIZONS
    ]


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5f_coking_plant_minimal_parameterisation()
    C5G_DIR.mkdir(parents=True, exist_ok=True)

    wag = _read_csv(C5F_DIR / "s4_4c5f_wag_generation_consumption_by_plant.csv")
    c5f_compact = _read_csv(C5F_DIR / "s4_4c5f_compact_table_for_chat.csv")
    lhv = _read_csv(C5F_DIR / "s4_4c5f_lhv_consistency_checks.csv")
    aggregate = _wag_aggregate_invariant_rows(wag)
    compact = _fixed_compact_rows(c5f_compact, aggregate)
    compact_reconciliation = _compact_aggregate_reconciliation(compact, aggregate)
    gate = _stage_gate(aggregate, compact_reconciliation, lhv)

    _write_json(C5G_DIR / "s4_4c5g_stage_gate.json", gate)
    _write_csv(C5G_DIR / "s4_4c5g_run_registry.csv", _run_registry(gate))
    _write_csv(C5G_DIR / "s4_4c5g_wag_aggregate_invariant.csv", aggregate, AGGREGATE_COLUMNS)
    _write_csv(C5G_DIR / "s4_4c5g_compact_table_for_chat.csv", compact, COMPACT_COLUMNS)
    _write_csv(C5G_DIR / "s4_4c5g_compact_aggregate_reconciliation.csv", compact_reconciliation)

    _copy_c5f("s4_4c5f_wag_generation_consumption_by_plant.csv")
    _copy_c5f("s4_4c5f_cog_wag_balance_by_plant.csv")
    _copy_c5f("s4_4c5f_cog_self_use_surplus_dashboard.csv")
    _copy_c5f("s4_4c5f_lhv_consistency_checks.csv")
    _copy_c5f("s4_4c5f_kgf_split_diagnostics.csv")

    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": _rel(C5G_DIR),
        "rows": {
            "aggregate_invariant": len(aggregate),
            "compact": len(compact),
            "compact_aggregate_reconciliation": len(compact_reconciliation),
        },
    }
    _write_json(C5G_DIR / "s4_4c5g_summary.json", summary)
    return summary


def run_s4_4c5g_wag_aggregate_diagnostic_hygiene() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5g_wag_aggregate_diagnostic_hygiene(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
