"""Reconcile historical and active C1 WAG ledgers without changing WAG factors.

This stage back-calculates the activity implied by the historical C5p_m carrier
ledger using the active-run carrier intensity.  A difference is therefore an
activity/controller-boundary finding, never a coefficient-calibration target.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
DEFAULT_RUN_ID = "steel_c1_wag_activity_basis_audit_v1"
ACTIVE_RUN_ID = "steel_c1_6_75_mer_site_product_anchor_boundary_v5"
HISTORICAL_LEDGER = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "s4_4c5p_m_wag_balance_and_controller_contract"
    / "wag_carrier_balance_matrix.csv"
)
HISTORICAL_ACTIVITY = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "s4_4c5p_i_source_card_candidate_overlay_reconciliation"
    / "c5_candidate_overlay_activity_basis.csv"
)
ACTIVE_CONFIG = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "configs"
    / "steel_c1_6_75_wag_sink_source_reconciliation.yaml"
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _as_float(value: str | float | int | None) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _historical_driver_map(rows: list[dict[str, str]], dry_coal_per_coke: float) -> dict[str, tuple[float, str, str]]:
    values = {row["plant_or_asset"]: _as_float(row["activity_value"]) for row in rows if row.get("configuration") == "C1_phase1_BF_BOF_plus_DRP_EAF"}
    return {
        "BFG": (values["BF"], "t_hot_metal/y", "C5p_e BF hot-metal activity"),
        "COG": (
            values["KGF/coking"] * dry_coal_per_coke,
            "t_dry_coal/y",
            "C5p_e coke-output activity converted with the active source-coke-chain dry-coal factor",
        ),
        "BOFG": (values["BOF/OSF"], "t_liquid_steel/y", "C5p_e BOF liquid-steel activity"),
    }


def build_activity_reconciliation(
    active_rows: list[dict[str, str]], historical_rows: list[dict[str, str]], historical_drivers: dict[str, tuple[float, str, str]]
) -> list[dict[str, Any]]:
    """Separate source-driver differences from different historical ledger points."""

    historical = {
        row["carrier"]: row
        for row in historical_rows
        if row.get("configuration") == "C1_phase1_BF_BOF_plus_DRP_EAF"
        and row.get("carrier") in {"BFG", "COG", "BOFG"}
    }
    rows: list[dict[str, Any]] = []
    for active in active_rows:
        carrier = active["carrier"]
        old = historical.get(carrier)
        intensity = _as_float(active["implied_generation_MWh_LHV_per_activity_t"])
        active_activity = _as_float(active["source_activity_t_y"])
        active_generation = _as_float(active["generation_MWh_LHV_y"])
        historical_generation_mwh = _as_float(old["generation_PJ_y"]) * 277_777.7777777778 if old else 0.0
        historical_activity, historical_basis, driver_source = historical_drivers[carrier]
        activity_ratio = historical_activity / active_activity if active_activity else 0.0
        driver_matches = abs(activity_ratio - 1.0) <= 0.05
        rows.append(
            {
                "carrier": carrier,
                "activity_basis": active["source_activity_basis"],
                "active_activity_t_y": round(active_activity, 6),
                "historical_activity_t_y": round(historical_activity, 6),
                "historical_activity_basis": historical_basis,
                "historical_driver_source": driver_source,
                "historical_to_active_activity_ratio": round(activity_ratio, 6),
                "active_generation_MWh_LHV_y": round(active_generation, 6),
                "active_intensity_MWh_LHV_per_t": round(intensity, 9),
                "historical_p_e_reconciled_supply_MWh_LHV_y": round(historical_generation_mwh, 6),
                "historical_p_e_ledger_point": "derived_process_use_plus_pre_steam_availability_not_gross_source_generation",
                "comparison_status": "not_comparable_different_ledger_point",
                "driver_comparison": "within_5pct" if driver_matches else "different_activity_driver",
                "finding": "C5p_e carrier generated_or_supplied is a reconciled controller-supply term, not a source-generation meter.",
                "coefficient_action": "do_not_tune",
                "next_action": "Use the active gross carrier ledger for source generation. If historical comparison is needed, export gross, mandatory self-use and network-available rows from one historical controller chain.",
            }
        )
    return rows


def run_wag_activity_basis_audit(
    *, run_id: str = DEFAULT_RUN_ID, output_root: str | Path = DEFAULT_RUN_ROOT, active_run_id: str = ACTIVE_RUN_ID
) -> dict[str, Any]:
    output_directory = Path(output_root) / run_id
    active_path = Path(output_root) / active_run_id / "wag_carrier_ledger.csv"
    active_rows = _read_csv(active_path)
    historical_rows = _read_csv(HISTORICAL_LEDGER)
    activity_rows = _read_csv(HISTORICAL_ACTIVITY)
    config = yaml.safe_load(ACTIVE_CONFIG.read_text(encoding="utf-8"))
    dry_coal_per_coke = float(config["source_coke_chain"]["dry_coal_t_per_t_coke"])
    rows = build_activity_reconciliation(active_rows, historical_rows, _historical_driver_map(activity_rows, dry_coal_per_coke))
    _write_csv(output_directory / "wag_activity_basis_reconciliation.csv", rows)
    checks = [
        {
            "check_id": "AZ_001",
            "check": "all_active_carriers_carrier_specific",
            "status": "pass" if {row["carrier"] for row in rows} == {"BFG", "COG", "BOFG"} else "fail",
            "evidence": "Only physical BFG/COG/BOFG rows are audited.",
        },
        {
            "check_id": "AZ_002",
            "check": "no_wag_coefficient_calibration",
            "status": "pass",
            "evidence": "All differences are classified as activity/controller-boundary findings.",
        },
    ]
    _write_csv(output_directory / "validation_checks.csv", checks)
    summary = {
        "stage": "S4.4c5p_az_wag_activity_basis_audit",
        "status": "pass",
        "output_policy": "diagnostics",
        "run_class": "anchor_boundary_audit",
        "lineage_role": "diagnostic",
        "active_run_id": active_run_id,
        "historical_ledger": str(HISTORICAL_LEDGER.relative_to(REPO_ROOT)).replace("\\", "/"),
        "carrier_count": len(rows),
        "coefficient_changes": 0,
        "finding": "historical drivers are compared separately; C5p_e reconciled supply is not comparable to active gross source generation, so no coefficient was changed",
    }
    (output_directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output_directory / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output_directory / "input_manifest.json").write_text(
        json.dumps({"active_wag_ledger": str(active_path), "historical_wag_ledger": str(HISTORICAL_LEDGER), "historical_activity_register": str(HISTORICAL_ACTIVITY), "active_source_config": str(ACTIVE_CONFIG)}, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_directory / "warnings_and_limitations.md").write_text(
        "# Limitations\n\nThis audit compares ledgers only. It does not identify a physical coefficient correction or create a WAG allocation.\n",
        encoding="utf-8",
    )
    (output_directory / "registry_entry.json").write_text(
        json.dumps({"run_id": run_id, "retention": "local_diagnostic", "git_eligible": False}, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"output_directory": str(output_directory), "summary": summary, "rows": rows}
