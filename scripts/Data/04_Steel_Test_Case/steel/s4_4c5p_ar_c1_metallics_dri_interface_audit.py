"""Source-backed C1 metallics and DRI-buffer audit.

This diagnostic does not alter capacities, source cards, or executable input
tables.  It records the separate BOF/EAF scrap evidence and proves whether the
already-present DRI inventory equation can absorb one controlled DRP-to-EAF
timing shift without terminal inventory leakage.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from pyomo.environ import ConstraintList, value

from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    _apply_solver_time_limit,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
    _select_solver,
)


RUN_ID = "steel_c1_metallics_and_dri_interface_audit_v1"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
EVIDENCE_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "c5_component_ontology"
    / "c1_metallics_dri_interface_evidence.csv"
)
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
HORIZON_HOURS = 24


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_metallics_evidence(path: Path = EVIDENCE_PATH) -> dict[str, dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "C1_BOF_SCRAP",
        "C1_EAF_SCRAP",
        "C1_SITE_TOTAL_SCRAP",
        "C1_EXTERNAL_SCRAP_IMPORT",
        "C1_INTERNAL_SCRAP_REUSE",
        "C1_DRP_OUTPUT",
        "C1_DRI_BUFFER",
        "C1_DRI_BUFFER_INITIAL",
    }
    evidence = {row["evidence_id"]: row for row in rows}
    missing = required.difference(evidence)
    if missing:
        raise ValueError(f"Metallics/DRI evidence is missing required rows: {sorted(missing)}")
    return evidence


def _number(row: dict[str, Any], field: str) -> float:
    raw = row.get(field, "")
    if raw in {"", None}:
        raise ValueError(f"{row['evidence_id']} has no {field} value")
    return float(raw)


def build_scrap_reconciliation_rows(evidence: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    bof = evidence["C1_BOF_SCRAP"]
    eaf = evidence["C1_EAF_SCRAP"]
    total = evidence["C1_SITE_TOTAL_SCRAP"]
    external = evidence["C1_EXTERNAL_SCRAP_IMPORT"]
    internal = evidence["C1_INTERNAL_SCRAP_REUSE"]
    bof_value = _number(bof, "central_value")
    eaf_low, eaf_high = _number(eaf, "lower_value"), _number(eaf, "upper_value")
    total_low, total_high = _number(total, "lower_value"), _number(total, "upper_value")
    external_value, internal_value = _number(external, "central_value"), _number(internal, "central_value")
    return [
        {
            "check_id": "separate_named_consumers",
            "result": "pass",
            "bof_scrap_mt_y": bof_value,
            "eaf_scrap_range_mt_y": f"{eaf_low}-{eaf_high}",
            "interpretation": "BOF and EAF have separate scrap consumption streams; do not collapse them into one process coefficient.",
            "model_action": "A future material model may use separate BOF/EAF variables only with a governed site supply ledger.",
        },
        {
            "check_id": "process_streams_match_site_total_envelope",
            "result": "pass" if abs((bof_value + eaf_low) - total_low) < 1e-9 and abs((bof_value + eaf_high) - total_high) < 1e-9 else "warning",
            "process_total_low_mt_y": round(bof_value + eaf_low, 6),
            "process_total_high_mt_y": round(bof_value + eaf_high, 6),
            "site_total_low_mt_y": total_low,
            "site_total_high_mt_y": total_high,
            "interpretation": "The official process-stream envelope closes to the official site total after rounded values.",
            "model_action": "Do not create a shared free scrap pool; reconcile external and internal supply categories separately.",
        },
        {
            "check_id": "external_plus_internal_matches_lower_site_total",
            "result": "pass" if abs((external_value + internal_value) - total_low) < 1e-9 else "warning",
            "external_scrap_mt_y": external_value,
            "internal_scrap_mt_y": internal_value,
            "site_total_lower_mt_y": total_low,
            "interpretation": "The lower public site total is explained by reported external scrap plus internal reuse.",
            "model_action": "Keep internal reuse reporting-only until a source-backed internal scrap-generation ledger exists.",
        },
        {
            "check_id": "athanasiadis_equal_scrap_ratio_claim",
            "result": "unverified",
            "interpretation": "No executable source-card row establishes a common 20% BOF/EAF scrap ratio. The current 0.2 t scrap/t DRI EAF value is a development assumption, not proof of an Athanasiadis-equivalent physical recipe.",
            "model_action": "Use official MER C1 BOF/EAF streams for physical validation; retain any shared-ratio precedent only as a separately labelled comparison case.",
        },
    ]


def run_dri_buffer_forced_shift() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Prove the current generic DRI buffer can store and release material.

    DRP is fixed at its existing upper operating bound.  EAF is forced off in
    hour 0 and at its existing upper DRI-input bound in hour 1.  The existing
    balance and terminal equality must find the remaining schedule; no buffer
    capacity or initial inventory value is modified.
    """

    inputs = _build_c1_inputs(_load_tables(S44B_INPUT_DIR), horizon_hours_override=HORIZON_HOURS)
    model = _build_c1_model(inputs, enable_minimal_wag_layer=False)
    model.final_product_fulfilment.deactivate()
    model.audit_fixed_drp = ConstraintList()
    model.audit_eaf_shift = ConstraintList()
    for t in model.TIME:
        model.audit_fixed_drp.add(model.drp_pellet_input[t] == inputs.drp_max_t_pellets_h)
    model.audit_eaf_shift.add(model.eaf_dri_input[0] == 0.0)
    model.audit_eaf_shift.add(model.eaf_dri_input[1] == inputs.eaf_max_t_dri_h)
    solver_name, solver = _select_solver()
    if solver is None or solver_name is None:
        return {"status": "blocked", "reason": "No configured solver is available."}, []
    _apply_solver_time_limit(solver_name, solver, 30.0)
    try:
        result = solver.solve(model)
    except RuntimeError as exc:
        return {"status": "blocked", "solver_name": solver_name, "reason": str(exc)}, []
    termination = str(result.solver.termination_condition).lower()
    if termination not in {"optimal", "feasible"}:
        return {"status": "blocked", "solver_name": solver_name, "termination_condition": termination}, []
    rows = [
        {
            "hour": int(t),
            "drp_pellet_input_t_h": round(float(value(model.drp_pellet_input[t])), 6),
            "drp_dri_output_t_h": round(float(value(model.drp_dri_output[t])), 6),
            "eaf_dri_input_t_h": round(float(value(model.eaf_dri_input[t])), 6),
            "dri_inventory_t": round(float(value(model.dri_inventory[t])), 6),
        }
        for t in model.TIME
    ]
    inventories = [row["dri_inventory_t"] for row in rows]
    summary = {
        "status": "pass",
        "solver_name": solver_name,
        "termination_condition": termination,
        "horizon_hours": HORIZON_HOURS,
        "buffer_capacity_t": inputs.dri_buffer_capacity_t,
        "buffer_initial_t": inputs.dri_buffer_initial_t,
        "buffer_max_t": max(inventories),
        "buffer_terminal_t": inventories[-1],
        "terminal_residual_t": round(inventories[-1] - inputs.dri_buffer_initial_t, 9),
        "forced_hour_0_eaf_dri_input_t_h": rows[0]["eaf_dri_input_t_h"],
        "forced_hour_1_eaf_dri_input_t_h": rows[1]["eaf_dri_input_t_h"],
        "finding": "The existing generic DRI inventory balance stores in hour 0, releases in subsequent hours, respects capacity, and returns to its initial inventory.",
    }
    return summary, rows


def build_route_factor_rows(evidence: dict[str, dict[str, Any]], buffer_summary: dict[str, Any]) -> list[dict[str, Any]]:
    source_buffer_central_t = _number(evidence["C1_DRI_BUFFER"], "central_value")
    model_buffer_t = float(buffer_summary.get("buffer_capacity_t", 0.0))
    return [
        {
            "factor_id": "BOF_metallics_missing_named_balance",
            "priority": "P0",
            "status": "development_candidate_ready_not_active",
            "failure_mode": "Current retained-route builder maps hot metal 1:1 to BOF liquid steel and does not apply the source-carded BOF scrap/hot-metal recipe.",
            "why_it_matters": "It can understate BOF liquid-steel output at fixed BF hot-metal output and obscures the separate BOF scrap stream.",
            "safe_next_action": "Add a separate BOF metallics ledger with named BOF scrap supply; retain a site-total reconciliation check.",
        },
        {
            "factor_id": "EAF_capacity_basis_mismatch",
            "priority": "P0",
            "status": "open",
            "failure_mode": "The model EAF capacity is expressed as DRI input per hour, whereas the MER energy-balance design rate is liquid-steel output per hour.",
            "why_it_matters": "A direct comparison can falsely label DRP or EAF as the binding asset.",
            "safe_next_action": "Audit EAF input/output capacity using the named DRI and scrap recipe before changing either capacity.",
        },
        {
            "factor_id": "DRP_annual_anchor_vs_operating_ceiling",
            "priority": "P1",
            "status": "open",
            "failure_mode": "The 2.8 Mt/y MER DRI anchor is an annual validation value, while the model upper rate derives from an operating-band maximum.",
            "why_it_matters": "Annualising an hourly maximum over 8,760 h overstates plausible annual availability without proving a capacity error.",
            "safe_next_action": "Report annual utilisation/availability separately from capacity; do not lower the source operating ceiling to fit an annual anchor.",
        },
        {
            "factor_id": "DRI_buffer_physical_detail",
            "priority": "P1",
            "status": "partial",
            "failure_mode": "The current buffer is one generic DRI inventory. It does not distinguish HDRI direct transfer from CDRI silo inventory, and its current initial level is zero.",
            "why_it_matters": "The generic buffer works mathematically but cannot yet support claims about thermal state, cooling/reoxidation, or exact silo capacity.",
            "safe_next_action": "Keep generic DRI buffer for deterministic feasibility; add HDRI/CDRI split only when a controller/energy basis is source-backed.",
        },
        {
            "factor_id": "DRI_buffer_capacity_provenance_difference",
            "priority": "P1",
            "status": "open",
            "failure_mode": f"The active development input capacity is {model_buffer_t:.0f} t while the source-card two-day central candidate is {source_buffer_central_t:.0f} t.",
            "why_it_matters": "Both are development proxies rather than public silo measurements; the difference affects timing flexibility, not the 24-hour balance identity.",
            "safe_next_action": "Reconcile the derivation in the buffer register before any buffer sensitivity; do not present either number as a measured Tata silo capacity.",
        },
        {
            "factor_id": "downstream_origin_and_slab_boundary",
            "priority": "P1",
            "status": "open",
            "failure_mode": "Imported slab, HSM, and DSP routing can affect final-product capacity independently of upstream liquid steel.",
            "why_it_matters": "A final-product deficit can be a downstream-boundary issue rather than an upstream capacity shortfall.",
            "safe_next_action": "Retain explicit bounded imported slab and route-specific yields; compare all results on final-product proxy basis.",
        },
        {
            "factor_id": "scrap_supply_ledger",
            "priority": "P0",
            "status": "required_before_activation",
            "failure_mode": "BOF and EAF scrap are separately evidenced but external imports and internal reuse are not yet allocated through an executable site supply ledger.",
            "why_it_matters": "Without it, separate scrap consumers could double count the same site resource.",
            "safe_next_action": "Build a named external/BOF/EAF scrap ledger; keep internal reuse reporting-only until it has a material origin.",
        },
        {
            "factor_id": "DRI_buffer_forced_shift",
            "priority": "P1",
            "status": buffer_summary.get("status", "blocked"),
            "failure_mode": "Not a failure: this row records the existing buffer proof rather than a new flexibility assumption.",
            "why_it_matters": "It separates a genuine DRI-to-EAF timing interface from an alleged missing-buffer diagnosis.",
            "safe_next_action": "Use the existing terminally closed buffer in later feasibility work; do not treat it as an unbounded source of DRI.",
        },
    ]


def run_c1_metallics_dri_interface_audit(run_root: Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    output_dir = run_root / RUN_ID
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = load_metallics_evidence()
    scrap_rows = build_scrap_reconciliation_rows(evidence)
    buffer_summary, buffer_rows = run_dri_buffer_forced_shift()
    route_rows = build_route_factor_rows(evidence, buffer_summary)
    warnings = [row for row in route_rows if row["status"] not in {"pass", "development_candidate_ready_not_active"}]
    summary = {
        "run_id": RUN_ID,
        "output_policy": "diagnostics",
        "run_class": "physical_feasibility_diagnostic",
        "lineage_role": "diagnostic",
        "retention": "local_run_artifact_not_git_eligible_by_default",
        "scrap_streams_are_separate": True,
        "site_scrap_envelope_closes": all(row["result"] == "pass" for row in scrap_rows[:3]),
        "athanasiadis_common_scrap_ratio_status": "unverified_in_current_source_cards",
        "dri_buffer": buffer_summary,
        "route_factor_count": len(route_rows),
        "open_or_partial_factor_count": len(warnings),
        "go_no_go": {
            "separate_bof_eaf_scrap_audit": "GO: source-backed as separate streams.",
            "activate_named_scrap_in_model": "NO-GO: requires a governed site scrap supply ledger.",
            "dri_buffer_exists_and_closes": "GO: generic buffer is active and terminally closed.",
            "claim_hdrI_cdri_physical_detail": "NO-GO: generic buffer lacks separate HDRI/CDRI states and a public silo capacity.",
            "change_capacity_values": "NO-GO: this audit identifies basis checks, not capacity revisions.",
        },
    }
    _write_csv(output_dir / "scrap_stream_reconciliation.csv", scrap_rows)
    _write_csv(output_dir / "dri_buffer_forced_shift_trace.csv", buffer_rows)
    _write_csv(output_dir / "route_factor_register.csv", route_rows)
    _write_json(output_dir / "input_manifest.json", {"evidence_path": str(EVIDENCE_PATH.relative_to(REPO_ROOT)), "input_surface": str(S44B_INPUT_DIR.relative_to(REPO_ROOT))})
    _write_json(output_dir / "run_summary.json", summary)
    (output_dir / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a diagnostic audit, not a sensitivity run or input migration.\n"
        "- The generic DRI buffer is not separate HDRI-direct and CDRI-silo physics.\n"
        "- BOF and EAF scrap may not be activated as a pooled resource until a named supply ledger exists.\n"
        "- No common Athanasiadis BOF/EAF scrap ratio was verified from the current source-card evidence.\n",
        encoding="utf-8",
    )
    return {"output_dir": output_dir, "summary": summary}
