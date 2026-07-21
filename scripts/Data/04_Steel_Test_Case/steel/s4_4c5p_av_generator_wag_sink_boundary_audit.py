"""Read-only C1 generator/WAG-sink boundary audit.

This module does not allocate gas or change the physical model.  It compiles
the exact 6.75-Mt/y WAG ledger into a carrier-specific explanation of the
published generator-fuel gap.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SOURCE_RUN = REPO_ROOT / "data/03_Optimisation/runs/steel_c1_6_75_wag_anchor_reconciliation_v4"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/03_Optimisation/runs"
DEFAULT_RUN_ID = "steel_c1_6_75_generator_wag_sink_boundary_audit_v1"
INHERITED_GENERATOR_PROFILE_PATH = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/s4_4c5p_c_ij01_vn25_generator_interface_accounting/s4_4c5p_c_generator_fuel_allocation.csv"
HOURS_PER_YEAR = 8_760.0
MWH_PER_PJ = 1_000_000.0 / 3.6
GENERATOR_WAG_ANCHORS_PJ_Y = {"BFG": 9.1, "BOFG": 1.3, "COG": 0.1}
GENERATOR_FLARE_ANCHOR_PJ_Y = 0.1


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0]) if rows else ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _as_float(row: dict[str, str], field: str) -> float:
    return float(row[field])


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _manifest(paths: list[Path]) -> list[dict[str, str]]:
    return [
        {
            "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in paths
    ]


def audit_rows(
    carrier_rows: list[dict[str, str]],
    interface_cap_mwh_h: float,
    *,
    interface_cap_active: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return generator comparison, WAG sink inventory and evidence-based gap rows."""

    by_carrier = {row["carrier"]: row for row in carrier_rows if row["carrier"] in GENERATOR_WAG_ANCHORS_PJ_Y}
    if set(by_carrier) != set(GENERATOR_WAG_ANCHORS_PJ_Y):
        raise ValueError("Carrier ledger must contain BFG, COG and BOFG rows.")

    comparison: list[dict[str, Any]] = []
    sink_rows: list[dict[str, Any]] = []
    total_generation_pj = 0.0
    total_non_generator_pj = 0.0
    total_generator_pj = 0.0
    for carrier in ("BFG", "COG", "BOFG"):
        row = by_carrier[carrier]
        generation_pj = _as_float(row, "generation_MWh_LHV_y") / MWH_PER_PJ
        generator_pj = _as_float(row, "generator_MWh_LHV_y") / MWH_PER_PJ
        non_generator_pj = generation_pj - generator_pj
        anchor_pj = GENERATOR_WAG_ANCHORS_PJ_Y[carrier]
        comparison.append(
            {
                "carrier": carrier,
                "model_generator_fuel_PJ_y": round(generator_pj, 6),
                "MER_generator_fuel_anchor_PJ_y": anchor_pj,
                "signed_gap_PJ_y": round(generator_pj - anchor_pj, 6),
                "signed_gap_share": round((generator_pj - anchor_pj) / anchor_pj, 6),
                "comparison_status": "secondary_context_partial_boundary",
                "caveat": "Annual MER fuel anchor; not an hourly dispatch constraint.",
            }
        )
        sink_rows.append(
            {
                "carrier": carrier,
                "generation_PJ_y": round(generation_pj, 6),
                "mandatory_process_or_self_use_PJ_y": round(_as_float(row, "process_or_self_use_MWh_LHV_y") / MWH_PER_PJ, 6),
                "HSM_PEFA_use_PJ_y": round(_as_float(row, "hsm_pefa_MWh_LHV_y") / MWH_PER_PJ, 6),
                "steam_boiler_use_PJ_y": round(_as_float(row, "steam_boiler_MWh_LHV_y") / MWH_PER_PJ, 6),
                "generator_use_PJ_y": round(generator_pj, 6),
                "flare_PJ_y": round(_as_float(row, "flare_MWh_LHV_y") / MWH_PER_PJ, 6),
                "residual_PJ_y": round(_as_float(row, "residual_MWh_LHV_y") / MWH_PER_PJ, 6),
                "physical_status": row["physical_carrier_status"],
            }
        )
        total_generation_pj += generation_pj
        total_non_generator_pj += non_generator_pj
        total_generator_pj += generator_pj

    realised_mwh_h = total_generator_pj * MWH_PER_PJ / HOURS_PER_YEAR
    generator_anchor_pj = sum(GENERATOR_WAG_ANCHORS_PJ_Y.values())
    cap_tolerance_mwh_h = 1e-6
    cap_finding = (
        {
            "finding_id": "AV_001",
            "finding": "The inherited generator profile cap is intentionally not active in this source-envelope sensitivity.",
            "evidence": f"Realised generator fuel {realised_mwh_h:.3f} MWh_LHV/h exceeds the inherited profile cap {interface_cap_mwh_h:.3f} MWh_LHV/h, while resolved_config selects volume_envelope_only.",
            "strength": "strong",
            "implication": "The structural volume envelope, not the historical allocation-derived profile cap, governs this run.",
            "allowed_next_action": "Do not call the inherited profile cap non-binding or promote the volume envelope to a base case without separate review.",
        }
        if not interface_cap_active
        else {
            "finding_id": "AV_001",
            "finding": "Current generator interface fuel cap is active at numerical equality.",
            "evidence": f"Realised generator fuel {realised_mwh_h:.3f} MWh_LHV/h equals the inherited interface cap {interface_cap_mwh_h:.3f} MWh_LHV/h within {cap_tolerance_mwh_h:.1e} MWh_LHV/h.",
            "strength": "strong",
            "implication": "The current run cannot establish that the inherited cap is non-binding; it may be constraining the represented generator interface.",
            "allowed_next_action": "Audit the source basis of the inherited profile cap before any bounded capacity sensitivity; do not increase it merely to close an annual anchor gap.",
        }
        if abs(realised_mwh_h - interface_cap_mwh_h) <= cap_tolerance_mwh_h
        else {
            "finding_id": "AV_001",
            "finding": "Current generator interface cap is not binding.",
            "evidence": f"Realised generator fuel {realised_mwh_h:.3f} MWh_LHV/h versus inherited interface cap {interface_cap_mwh_h:.3f} MWh_LHV/h.",
            "strength": "strong",
            "implication": "Increasing this inherited cap alone cannot close the annual generator-fuel gap.",
            "allowed_next_action": "Keep cap as an inherited diagnostic bound until a source-backed unit envelope is selected.",
        }
    )
    gap_rows = [
        cap_finding,
        {
            "finding_id": "AV_002",
            "finding": "The identical-boundary generator anchor would require more gas than remains after represented non-generator sinks.",
            "evidence": f"Model gross WAG {total_generation_pj:.6f} PJ/y; represented non-generator WAG use {total_non_generator_pj:.6f} PJ/y; MER generator WAG anchor {generator_anchor_pj:.6f} PJ/y.",
            "strength": "strong_arithmetic_but_boundary_limited",
            "implication": "At least one of generation, sink coverage/priority, or annual anchor boundary differs; this is not evidence to reallocate gas automatically.",
            "allowed_next_action": "Audit source-backed process-sink demand bases before any bounded controller sensitivity.",
        },
        {
            "finding_id": "AV_003",
            "finding": "No flare in the represented run does not validate the MER flare row.",
            "evidence": f"Model flare 0 PJ/y versus MER context {GENERATOR_FLARE_ANCHOR_PJ_Y:.3f} PJ/y; MER flare has no carrier split in this boundary.",
            "strength": "moderate",
            "implication": "Do not assign the 0.1 PJ/y to a carrier or add flare CO2.",
            "allowed_next_action": "Retain an unsplit flare reporting gap only.",
        },
    ]
    return comparison, sink_rows, gap_rows


def _inherited_interface_cap_mwh_h(rows: list[dict[str, str]]) -> float:
    """Reconstruct the read-only cap source rather than treating it as a nameplate."""

    selected = [
        row
        for row in rows
        if row.get("configuration") == "C1_phase1_BF_BOF_plus_DRP_EAF"
        and row.get("horizon_hours") == "24"
        and row.get("unit_id") in {"VN25", "IJ01"}
    ]
    if not selected:
        raise ValueError("No C1 VN25/IJ01 rows found in the inherited generator-profile artifact.")
    annual_mwh = sum(
        _as_float(row, "BFG_MWh_LHV_y") + _as_float(row, "BOFG_MWh_LHV_y") + _as_float(row, "COG_MWh_LHV_y")
        for row in selected
    )
    return annual_mwh / HOURS_PER_YEAR


def run_generator_wag_sink_boundary_audit(
    source_run: Path = DEFAULT_SOURCE_RUN,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    source_run = Path(source_run).resolve()
    output_dir = Path(output_root).resolve() / run_id
    if output_dir.exists():
        raise ValueError(f"Run directory already exists: {output_dir}")

    ledger_path = source_run / "wag_carrier_ledger.csv"
    resolved_path = source_run / "resolved_config.yaml"
    source_card_path = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/IJ01_VN25_GENERATORS_Parameters.md"
    rows = _read_csv(ledger_path)
    # The source run records the selected policy, while the inherited C5p_c
    # generator rows are the actual origin of the current interface cap.
    resolved = yaml.safe_load(resolved_path.read_text(encoding="utf-8")) or {}
    interface_cap = _inherited_interface_cap_mwh_h(_read_csv(INHERITED_GENERATOR_PROFILE_PATH))
    interface_cap_active = resolved.get("generator_interface_cap_mode", "inherited_profile") == "inherited_profile"
    comparison, sink_rows, gap_rows = audit_rows(rows, interface_cap, interface_cap_active=interface_cap_active)

    output_dir.mkdir(parents=True)
    _write_csv(output_dir / "generator_anchor_reconciliation.csv", comparison)
    _write_csv(output_dir / "wag_sink_inventory.csv", sink_rows)
    _write_csv(output_dir / "boundary_findings.csv", gap_rows)
    total_model_generator_pj = sum(row["model_generator_fuel_PJ_y"] for row in comparison)
    summary = {
        "stage_id": "S4.4c5p_av_generator_wag_sink_boundary_audit",
        "status": "pass_with_boundary_findings",
        "output_policy": "diagnostics",
        "run_class": "read_only_audit",
        "lineage_role": "diagnostic",
        "source_run": source_run.name,
        "model_generator_WAG_PJ_y": total_model_generator_pj,
        "MER_generator_WAG_anchor_PJ_y": sum(GENERATOR_WAG_ANCHORS_PJ_Y.values()),
        "generator_interface_cap_MWh_LHV_h": interface_cap,
        "generator_interface_profile_cap_status": "active" if interface_cap_active else "not_active",
        "physical_allocation_changed": False,
        "recommended_next_gate": "process_sink_demand_basis_audit_before_any_controller_sensitivity",
    }
    _write_json(output_dir / "run_summary.json", summary)
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "resolved_config.yaml").write_text(
        yaml.safe_dump(
            {
                "source_run": source_run.as_posix(),
                "generator_anchor_PJ_y": GENERATOR_WAG_ANCHORS_PJ_Y,
                "generator_flare_anchor_PJ_y": GENERATOR_FLARE_ANCHOR_PJ_Y,
                "output_policy": "diagnostics",
                "physical_allocation_changed": False,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _write_json(output_dir / "input_manifest.json", {"inputs": _manifest([ledger_path, resolved_path, source_card_path, INHERITED_GENERATOR_PROFILE_PATH])})
    _write_json(output_dir / "code_version.json", {"git_revision": _git_revision(), "timestamp_utc": datetime.now(timezone.utc).isoformat()})
    _write_json(
        output_dir / "registry_entry.json",
        {"stage_id": summary["stage_id"], "output_policy": "diagnostics", "lineage_role": "diagnostic", "git_eligible": False},
    )
    (output_dir / "warnings_and_limitations.md").write_text(
        "# Limitations\n\n"
        "This is a read-only boundary audit.  MER annual generator rows are validation context, not hourly constraints. "
        "No WAG flow, generator capacity, NG use, flare allocation or CO2 factor was changed.\n",
        encoding="utf-8",
    )
    return summary
