"""S4.4c5p_k common-plant NG/WAG diagnostic overlay.

This stage is diagnostic-only. It applies common-plant fuel-demand candidates
from the repaired source-card overlay to existing C5 activity outputs, then
allocates existing residual WAG before the generator layer first and reports the
remaining fuel demand as a natural-gas residual. It does not change executable
development inputs, model equations, objectives, or dispatch behaviour.
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
)
from .s4_4c5p_c_ij01_vn25_generator_interface_accounting import C5P_C_DIR
from .s4_4c5p_g_residual_electricity_ng_boundary_diagnostics import C5P_G_DIR
from .s4_4c5p_i_source_card_candidate_overlay_reconciliation import C5P_I_DIR


STAGE = "S4.4c5p_k_common_plant_ng_wag_overlay"
C5P_K_DIR = S4_ROOT / "s4_4c5p_k_common_plant_ng_wag_overlay"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_COMMON_PLANT_NG_WAG_OVERLAY.md")
ANCHOR_REGISTER_PATH = S4_ROOT / "c5_model_anchor_register/c5_model_anchor_evidence_register.csv"

COMMON_DEMAND_PARAMETER_IDS = {
    "HSM_REHEAT_FUEL_GJ_PER_T_HRC_KHALID": {
        "plant": "HSM/WBW",
        "priority": 20,
        "demand_type": "reheat_fuel_unspecified_WAG_or_NG",
    },
    "KGF_COG_FOR_HEATING_GJ_PER_T_COKE": {
        "plant": "KGF/coking",
        "priority": 10,
        "demand_type": "COG_self_use_underfiring",
    },
}

VISIBLE_DEFERRED_PARAMETER_IDS = {
    "BOF_NG_M3_PER_T_LS_BIEDA": "volume fuel candidate not converted without LHV and volume-normalisation policy",
    "BOF_COG_M3_PER_T_LS_BIEDA": "volume fuel candidate not converted without LHV and volume-normalisation policy",
    "BOILER_EFFICIENCY_BASE": "efficiency sensitivity, not a standalone residual fuel demand",
}

C1_ONLY_NEW_ASSETS = {
    "DRP": "new C1 NG-DRP route, not replicated into C0 common-plant overlay",
    "EAF": "new C1 EAF route, not replicated into C0 common-plant overlay",
}

FUEL_DEMAND_COLUMNS = [
    "configuration",
    "plant",
    "carrier_or_fuel_demand_type",
    "activity_basis",
    "activity_value",
    "intensity_value",
    "intensity_unit",
    "demand_PJ_y",
    "source_status",
    "common_or_new_asset",
    "caveat",
]

ALLOCATION_COLUMNS = [
    "configuration",
    "plant",
    "fuel_demand_PJ_y",
    "wag_allocated_PJ_y",
    "ng_residual_PJ_y",
    "unmet_fuel_PJ_y",
    "allocation_mode",
    "explicit_ratio_used",
    "ratio_source",
    "wag_carrier_basis",
    "caveat",
]

NG_SUMMARY_COLUMNS = [
    "configuration",
    "explicit_existing_ng_PJ_y",
    "new_c1_only_ng_PJ_y",
    "common_plant_ng_residual_PJ_y",
    "total_diagnostic_ng_PJ_y",
    "full_site_ng_anchor_PJ_y",
    "residual_to_anchor_PJ_y",
    "anchor_status",
    "caveat",
]

WARNING_COLUMNS = [
    "warning_id",
    "severity",
    "configuration",
    "plant",
    "issue_type",
    "message",
    "recommended_action",
]

RUN_REGISTRY_COLUMNS = [
    "stage",
    "status",
    "output_directory",
    "thesis_usability",
    "failure_count",
    "caveat",
]


def _num(value: Any) -> float:
    if value in (None, "", "nan", "NaN"):
        return math.nan
    return float(value)


def _fmt(value: float | int | str | None, digits: int = 6) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, float) and math.isnan(value):
        return ""
    return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")


def allocate_with_wag_priority(
    fuel_demand_pj: float,
    available_wag_pj: float,
    explicit_ng_share: float | None = None,
) -> dict[str, Any]:
    """Allocate fuel demand to WAG first, unless an explicit NG share exists."""

    warnings: list[str] = []
    if fuel_demand_pj < 0 or available_wag_pj < 0:
        warnings.append("NEGATIVE_OR_IMPOSSIBLE_INPUT")
        return {
            "wag_allocated_pj": 0.0,
            "ng_residual_pj": 0.0,
            "unmet_fuel_pj": max(fuel_demand_pj, 0.0),
            "remaining_wag_pj": max(available_wag_pj, 0.0),
            "warnings": warnings,
        }

    if explicit_ng_share is not None:
        if explicit_ng_share < 0 or explicit_ng_share > 1:
            warnings.append("INVALID_EXPLICIT_NG_SHARE")
            explicit_ng_share = None
        else:
            ng_residual = fuel_demand_pj * explicit_ng_share
            required_wag = fuel_demand_pj - ng_residual
            wag_allocated = min(required_wag, available_wag_pj)
            unmet = max(required_wag - wag_allocated, 0.0)
            return {
                "wag_allocated_pj": wag_allocated,
                "ng_residual_pj": ng_residual,
                "unmet_fuel_pj": unmet,
                "remaining_wag_pj": max(available_wag_pj - wag_allocated, 0.0),
                "warnings": warnings,
            }

    wag_allocated = min(fuel_demand_pj, available_wag_pj)
    ng_residual = max(fuel_demand_pj - wag_allocated, 0.0)
    return {
        "wag_allocated_pj": wag_allocated,
        "ng_residual_pj": ng_residual,
        "unmet_fuel_pj": 0.0,
        "remaining_wag_pj": max(available_wag_pj - wag_allocated, 0.0),
        "warnings": warnings,
    }


def _read_p_i_fuel_rows() -> list[dict[str, str]]:
    path = C5P_I_DIR / "c5_candidate_overlay_ng_fuel_by_plant.csv"
    if not path.exists():
        from .s4_4c5p_i_source_card_candidate_overlay_reconciliation import (
            run_s4_4c5p_i_source_card_candidate_overlay_reconciliation,
        )

        run_s4_4c5p_i_source_card_candidate_overlay_reconciliation()
    return _read_csv(path)


def _load_wag_pool_after_steam() -> dict[str, float]:
    rows = _read_csv(C5P_C_DIR / "s4_4c5p_c_compact_healthcheck.csv")
    pools: dict[str, float] = {}
    for row in rows:
        if row.get("horizon_hours") != "24":
            continue
        pools[row["configuration"]] = _num(row.get("residual_WAG_after_steam_PJ_y"))
    return pools


def _load_ng_boundary() -> dict[str, dict[str, float]]:
    rows = _read_csv(C5P_G_DIR / "c5_residual_ng_boundary_matrix.csv")
    boundary: dict[str, dict[str, float]] = {}
    for row in rows:
        boundary[row["configuration"]] = {
            "drp_ng_pj": _num(row.get("drp_ng_pj")),
            "eaf_ng_pj": _num(row.get("eaf_ng_pj")),
            "generator_ng_pj": _num(row.get("generator_ng_pj")),
            "boiler_steam_ng_pj": _num(row.get("boiler_steam_ng_pj")),
            "pefa_ng_pj": _num(row.get("pefa_ng_pj")),
            "other_modelled_ng_pj": _num(row.get("other_modelled_ng_pj")),
            "total_modelled_ng_pj": _num(row.get("total_modelled_ng_pj")),
        }
    return boundary


def _load_ng_anchor_values() -> dict[str, tuple[float, str]]:
    anchors = {C0: (math.nan, "missing"), C1: (math.nan, "missing")}
    if not ANCHOR_REGISTER_PATH.exists():
        return anchors
    rows = _read_csv(ANCHOR_REGISTER_PATH)
    by_id = {row["anchor_id"]: row for row in rows}
    mapping = {
        C0: "c0_full_site_ng_12_5pj_missing",
        C1: "c1_full_site_ng_46_5pj_missing",
    }
    for config, anchor_id in mapping.items():
        row = by_id.get(anchor_id)
        if not row:
            continue
        anchors[config] = (
            _num(row.get("raw_value")),
            f"{row.get('model_use_status', '')};{row.get('locator_quality', '')};{row.get('review_status', '')}",
        )
    return anchors


def _build_fuel_demand_rows(fuel_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for row in fuel_rows:
        parameter_id = row["candidate_parameter_id"]
        config = row["configuration"]
        plant = row["plant_or_asset"]
        if parameter_id in COMMON_DEMAND_PARAMETER_IDS:
            meta = COMMON_DEMAND_PARAMETER_IDS[parameter_id]
            demand = _num(row.get("overlay_fuel_pj_y"))
            output.append(
                {
                    "configuration": config,
                    "plant": meta["plant"],
                    "carrier_or_fuel_demand_type": meta["demand_type"],
                    "activity_basis": row.get("activity_metric", ""),
                    "activity_value": row.get("activity_value", ""),
                    "intensity_value": row.get("candidate_value", ""),
                    "intensity_unit": row.get("candidate_unit", ""),
                    "demand_PJ_y": _fmt(demand),
                    "source_status": row.get("source_status", ""),
                    "common_or_new_asset": "common_C0_C1_asset",
                    "caveat": "Diagnostic common-plant fuel demand only; WAG/NG allocation is not executable.",
                }
            )
        elif parameter_id in VISIBLE_DEFERRED_PARAMETER_IDS:
            output.append(
                {
                    "configuration": config,
                    "plant": plant,
                    "carrier_or_fuel_demand_type": row.get("fuel_or_energy_carrier", ""),
                    "activity_basis": row.get("activity_metric", ""),
                    "activity_value": row.get("activity_value", ""),
                    "intensity_value": row.get("candidate_value", ""),
                    "intensity_unit": row.get("candidate_unit", ""),
                    "demand_PJ_y": "",
                    "source_status": row.get("source_status", ""),
                    "common_or_new_asset": "common_asset_deferred_not_allocated",
                    "caveat": VISIBLE_DEFERRED_PARAMETER_IDS[parameter_id],
                }
            )
            warnings.append(
                {
                    "warning_id": f"{config}_{parameter_id}_DEFERRED",
                    "severity": "warning",
                    "configuration": config,
                    "plant": plant,
                    "issue_type": "deferred_conversion_or_sensitivity",
                    "message": VISIBLE_DEFERRED_PARAMETER_IDS[parameter_id],
                    "recommended_action": "Review source-card conversion policy before executable migration.",
                }
            )
        elif parameter_id == "KGF_COG_FOR_TRADING_GJ_PER_T_COKE":
            warnings.append(
                {
                    "warning_id": f"{config}_KGF_COG_FOR_TRADING_NOT_DEMAND",
                    "severity": "info",
                    "configuration": config,
                    "plant": "KGF/coking",
                    "issue_type": "candidate_supply_not_demand",
                    "message": "Clean COG surplus candidate is not used as a new WAG source in this overlay.",
                    "recommended_action": "Reconcile gross COG, underfiring, and clean COG surplus before migration.",
                }
            )
    for config in (C0, C1):
        for plant, reason in C1_ONLY_NEW_ASSETS.items():
            warnings.append(
                {
                    "warning_id": f"{config}_{plant}_C1_ONLY_REPLICATION_EXCLUDED",
                    "severity": "info",
                    "configuration": config,
                    "plant": plant,
                    "issue_type": "c1_only_asset_excluded",
                    "message": reason,
                    "recommended_action": "Do not copy C1-only DRP/EAF fuel demand into C0.",
                }
            )
    return output, warnings


def _build_allocation_rows(
    fuel_demand_rows: list[dict[str, Any]],
    wag_pools: dict[str, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    allocation: list[dict[str, Any]] = []
    for config in (C0, C1):
        remaining_wag = wag_pools.get(config, math.nan)
        rows = [
            row
            for row in fuel_demand_rows
            if row["configuration"] == config
            and row["common_or_new_asset"] == "common_C0_C1_asset"
            and row.get("demand_PJ_y")
        ]
        rows.sort(key=lambda row: COMMON_DEMAND_PARAMETER_IDS[
            next(k for k, meta in COMMON_DEMAND_PARAMETER_IDS.items() if meta["plant"] == row["plant"])
        ]["priority"])
        if math.isnan(remaining_wag):
            warnings.append(
                {
                    "warning_id": f"{config}_WAG_POOL_MISSING",
                    "severity": "failure",
                    "configuration": config,
                    "plant": "common_overlay",
                    "issue_type": "missing_wag_pool",
                    "message": "Could not load residual WAG after steam from C5p_c.",
                    "recommended_action": "Re-run or inspect C5p_c generator-interface diagnostics.",
                }
            )
            remaining_wag = 0.0
        warnings.append(
            {
                "warning_id": f"{config}_AGGREGATE_WAG_POOL_USED",
                "severity": "warning",
                "configuration": config,
                "plant": "common_overlay",
                "issue_type": "aggregate_wag_pool",
                "message": "No explicit common-plant WAG/NG split was found; allocation uses aggregate residual WAG after steam.",
                "recommended_action": "Repair carrier-specific common-plant fuel eligibility before executable migration.",
            }
        )
        for row in rows:
            demand = _num(row["demand_PJ_y"])
            result = allocate_with_wag_priority(demand, remaining_wag)
            remaining_wag = result["remaining_wag_pj"]
            for issue in result["warnings"]:
                warnings.append(
                    {
                        "warning_id": f"{config}_{row['plant']}_{issue}",
                        "severity": "failure",
                        "configuration": config,
                        "plant": row["plant"],
                        "issue_type": issue,
                        "message": "Negative or impossible fuel/WAG input detected in overlay allocation.",
                        "recommended_action": "Inspect candidate fuel demand and WAG pool before using this overlay.",
                    }
                )
            allocation.append(
                {
                    "configuration": config,
                    "plant": row["plant"],
                    "fuel_demand_PJ_y": _fmt(demand),
                    "wag_allocated_PJ_y": _fmt(result["wag_allocated_pj"]),
                    "ng_residual_PJ_y": _fmt(result["ng_residual_pj"]),
                    "unmet_fuel_PJ_y": _fmt(result["unmet_fuel_pj"]),
                    "allocation_mode": "wag_priority_residual_fallback",
                    "explicit_ratio_used": "false",
                    "ratio_source": "",
                    "wag_carrier_basis": "aggregate_residual_WAG_after_steam_from_C5p_c; BFG/COG/BOFG not silently collapsed in source ledgers but common-plant split is underparameterised",
                    "caveat": "Reporting-only overlay; it reallocates existing post-steam residual WAG before generator accounting for diagnostics.",
                }
            )
    return allocation, warnings


def _build_ng_summary(
    allocation_rows: list[dict[str, Any]],
    ng_boundary: dict[str, dict[str, float]],
    anchors: dict[str, tuple[float, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in (C0, C1):
        existing = ng_boundary.get(config, {}).get("total_modelled_ng_pj", 0.0)
        drp = ng_boundary.get(config, {}).get("drp_ng_pj", 0.0)
        eaf = ng_boundary.get(config, {}).get("eaf_ng_pj", 0.0)
        common_residual = sum(
            _num(row.get("ng_residual_PJ_y"))
            for row in allocation_rows
            if row["configuration"] == config
        )
        anchor, anchor_status = anchors.get(config, (math.nan, "missing"))
        total = existing + common_residual
        residual_to_anchor = math.nan if math.isnan(anchor) else anchor - total
        rows.append(
            {
                "configuration": config,
                "explicit_existing_ng_PJ_y": _fmt(existing),
                "new_c1_only_ng_PJ_y": _fmt(drp + eaf),
                "common_plant_ng_residual_PJ_y": _fmt(common_residual),
                "total_diagnostic_ng_PJ_y": _fmt(total),
                "full_site_ng_anchor_PJ_y": _fmt(anchor),
                "residual_to_anchor_PJ_y": _fmt(residual_to_anchor),
                "anchor_status": anchor_status,
                "caveat": "Full-site NG anchor has partial provenance and is diagnostic-only; total is not executable full-site NG.",
            }
        )
    return rows


def _write_report(
    fuel_rows: list[dict[str, Any]],
    allocation_rows: list[dict[str, Any]],
    ng_summary_rows: list[dict[str, Any]],
    warning_rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    common_plants = sorted({row["plant"] for row in fuel_rows if row["common_or_new_asset"] == "common_C0_C1_asset"})
    excluded = ", ".join(sorted(C1_ONLY_NEW_ASSETS))
    lines = [
        "# C5 Common-Plant NG/WAG Overlay",
        "",
        "This report is a diagnostic-only C5p_k overlay. It explains why C0 modelled NG was previously zero: current C5 explicit NG counts only represented NG consumers inside the executable/diagnostic boundary, not full-site residual gas use.",
        "",
        "No executable development inputs, model equations, objective terms, residual load variables, CO2 objective terms, economics, DA bidding logic, or source cards are changed by this stage.",
        "",
        "## Scope",
        "",
        f"Common C0/C1 fuel-using plants included: {', '.join(common_plants)}.",
        f"C1-only/new assets excluded from C0 replication: {excluded}.",
        "",
        "No explicit common-plant WAG/NG ratio was found in the current candidate/register artifacts. The overlay therefore uses a labelled WAG-priority residual fallback: existing post-steam residual WAG is allocated first, and any remaining candidate fuel demand is reported as diagnostic NG residual.",
        "",
        "## Summary Metrics",
        "",
        "| Configuration | Common fuel demand PJ/y | WAG allocated PJ/y | Common NG residual PJ/y | Total diagnostic NG PJ/y | Full-site NG anchor PJ/y | Residual to anchor PJ/y |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for config in (C0, C1):
        config_allocation = [row for row in allocation_rows if row["configuration"] == config]
        demand = sum(_num(row["fuel_demand_PJ_y"]) for row in config_allocation)
        wag = sum(_num(row["wag_allocated_PJ_y"]) for row in config_allocation)
        ng = sum(_num(row["ng_residual_PJ_y"]) for row in config_allocation)
        ng_summary = next(row for row in ng_summary_rows if row["configuration"] == config)
        lines.append(
            f"| {config} | {_fmt(demand)} | {_fmt(wag)} | {_fmt(ng)} | {ng_summary['total_diagnostic_ng_PJ_y']} | {ng_summary['full_site_ng_anchor_PJ_y']} | {ng_summary['residual_to_anchor_PJ_y']} |"
        )
    lines.extend(
        [
            "",
            "## Caveats",
            "",
            "- Residual NG remains diagnostic/reporting-only, not a plug variable and not a dispatch decision.",
            "- WAG allocation uses an aggregate residual-WAG pool because common-plant carrier splits are underparameterised.",
            "- BOF volume fuel candidates remain visible but unconverted because the source unit and LHV/normalisation policy are not executable.",
            "- CO2 remains not ETS-ready and this overlay does not compute CO2 from residual NG/WAG.",
            "- Economics and DA readiness remain NO-GO.",
            "",
            "## GO/NO-GO",
            "",
            f"- Residual NG reporting: {summary['go_no_go']['residual_ng_reporting']}.",
            f"- Migration to executable inputs: {summary['go_no_go']['candidate_migration_to_executable_inputs']}.",
            f"- CO2 implementation: {summary['go_no_go']['co2_implementation']}.",
            f"- Economics readiness: {summary['go_no_go']['economics_readiness']}.",
            f"- DA readiness: {summary['go_no_go']['da_readiness']}.",
            "",
            f"Warnings emitted: {len(warning_rows)}.",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_s4_4c5p_k_common_plant_ng_wag_overlay() -> dict[str, Any]:
    fuel_rows_from_i = _read_p_i_fuel_rows()
    wag_pools = _load_wag_pool_after_steam()
    ng_boundary = _load_ng_boundary()
    anchors = _load_ng_anchor_values()

    fuel_rows, warnings_a = _build_fuel_demand_rows(fuel_rows_from_i)
    allocation_rows, warnings_b = _build_allocation_rows(fuel_rows, wag_pools)
    ng_summary_rows = _build_ng_summary(allocation_rows, ng_boundary, anchors)
    warning_rows = warnings_a + warnings_b

    totals = {
        config: {
            "common_plant_fuel_demand_PJ_y": sum(
                _num(row["fuel_demand_PJ_y"]) for row in allocation_rows if row["configuration"] == config
            ),
            "wag_allocated_PJ_y": sum(
                _num(row["wag_allocated_PJ_y"]) for row in allocation_rows if row["configuration"] == config
            ),
            "common_plant_ng_residual_PJ_y": sum(
                _num(row["ng_residual_PJ_y"]) for row in allocation_rows if row["configuration"] == config
            ),
            "total_diagnostic_ng_PJ_y": _num(
                next(row for row in ng_summary_rows if row["configuration"] == config)["total_diagnostic_ng_PJ_y"]
            ),
            "full_site_ng_anchor_PJ_y": _num(
                next(row for row in ng_summary_rows if row["configuration"] == config)["full_site_ng_anchor_PJ_y"]
            ),
            "residual_to_anchor_PJ_y": _num(
                next(row for row in ng_summary_rows if row["configuration"] == config)["residual_to_anchor_PJ_y"]
            ),
        }
        for config in (C0, C1)
    }

    failure_count = sum(1 for row in warning_rows if row["severity"] == "failure")
    summary = {
        "stage": STAGE,
        "status": "development_only",
        "thesis_usability": False,
        "output_directory": C5P_K_DIR.as_posix(),
        "common_plants_included": sorted(
            {row["plant"] for row in fuel_rows if row["common_or_new_asset"] == "common_C0_C1_asset"}
        ),
        "c1_only_new_assets_excluded": sorted(C1_ONLY_NEW_ASSETS),
        "explicit_wag_ng_ratio_found": False,
        "allocation_mode": "wag_priority_residual_fallback",
        "totals": totals,
        "warning_count": len(warning_rows),
        "failure_count": failure_count,
        "go_no_go": {
            "residual_ng_reporting": "GO_DIAGNOSTIC_ONLY_WITH_PARTIAL_PROVENANCE",
            "candidate_migration_to_executable_inputs": "NO_GO",
            "co2_implementation": "NO_GO",
            "economics_readiness": "NO_GO",
            "da_readiness": "NO_GO",
        },
        "caveats": [
            "COMMON_PLANT_NG_WAG_OVERLAY_DIAGNOSTIC_ONLY",
            "RESIDUAL_NG_REPORTING_ONLY_NOT_EXECUTABLE_INPUT",
            "AGGREGATE_WAG_POOL_FALLBACK_USED",
            "COMMON_PLANT_CARRIER_SPLIT_UNDERPARAMETERISED",
            "CO2_NOT_ETS_READY",
            "ECONOMICS_NO_GO",
            "DA_NO_GO",
            "NOT_THESIS_APPROVED",
        ],
    }
    gate = {
        "stage": STAGE,
        "decision": "pass_development_common_plant_ng_wag_overlay" if failure_count == 0 else "fail_development_common_plant_ng_wag_overlay",
        "status": "development_only",
        "thesis_usability": False,
        "failure_count": failure_count,
        "candidate_values_migrated_to_executable_inputs": False,
        "model_equations_changed": False,
        "source_cards_changed": False,
        "residual_ng_load_added": False,
        "residual_electricity_load_added": False,
        "co2_ets_ready": False,
        "economics_readiness": "NO_GO",
        "DA_readiness": "NO_GO",
        "denominator_status": "unresolved",
        "explicit_wag_ng_ratio_found": False,
        "output_directory": C5P_K_DIR.as_posix(),
    }

    _write_csv(C5P_K_DIR / "common_plant_fuel_demand_overlay.csv", fuel_rows, FUEL_DEMAND_COLUMNS)
    _write_csv(C5P_K_DIR / "common_plant_wag_ng_allocation.csv", allocation_rows, ALLOCATION_COLUMNS)
    _write_csv(C5P_K_DIR / "common_plant_ng_residual_summary.csv", ng_summary_rows, NG_SUMMARY_COLUMNS)
    _write_csv(C5P_K_DIR / "common_plant_warnings.csv", warning_rows, WARNING_COLUMNS)
    _write_json(C5P_K_DIR / "summary.json", summary)
    _write_json(C5P_K_DIR / "s4_4c5p_k_stage_gate.json", gate)
    _write_csv(
        C5P_K_DIR / "s4_4c5p_k_run_registry.csv",
        [
            {
                "stage": STAGE,
                "status": "development_only",
                "output_directory": C5P_K_DIR.as_posix(),
                "thesis_usability": "false",
                "failure_count": failure_count,
                "caveat": ";".join(summary["caveats"]),
            }
        ],
        RUN_REGISTRY_COLUMNS,
    )
    _write_report(fuel_rows, allocation_rows, ng_summary_rows, warning_rows, summary)
    return summary


def main() -> int:
    summary = run_s4_4c5p_k_common_plant_ng_wag_overlay()
    print(json.dumps({"stage": STAGE, "failure_count": summary["failure_count"]}, sort_keys=True))
    return 0 if summary["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
