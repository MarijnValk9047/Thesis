"""Compile a compact, non-executable anchor/boundary decision design.

This stage deliberately does not tune coefficients or run sensitivities.  It
turns the outstanding comparison caveats from C5p_ag and C5p_o into explicit
next-step decisions, so a later sensitivity runner cannot silently target a
denominator- or boundary-mismatched annual anchor.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
STAGE = "S4.4c5p_ah_anchor_boundary_reconciliation_design"
OUTPUT_DIR = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "s4_4c5p_ah_anchor_boundary_reconciliation_design"
)
REPORT_PATH = REPO_ROOT / "docs" / "optimisation" / "steel" / "S4" / "C5_ANCHOR_BOUNDARY_RECONCILIATION_DESIGN.md"
ANCHOR_COMPARISON = REPO_ROOT / "data" / "03_Optimisation" / "runs" / "steel_intensity_anchor_diagnostic_v1" / "normalised_anchor_comparison.csv"
ANCHOR_REGISTER = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4" / "c5_model_anchor_register" / "c5_model_anchor_evidence_register.csv"
WAG_SUMMARY = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4" / "s4_4c5p_o_wag_controller_contract_hardening" / "summary.json"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(rows[0]) if rows else ["decision_id"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _comparison(rows: list[dict[str, str]], anchor_id: str) -> dict[str, str]:
    return next(row for row in rows if row["anchor_id"] == anchor_id)


def build_decision_rows() -> list[dict[str, Any]]:
    comparisons = _read_csv(ANCHOR_COMPARISON)
    register = {row["anchor_id"]: row for row in _read_csv(ANCHOR_REGISTER)}
    c0_wag = _comparison(comparisons, "athan_table8_current_wag_2_74")
    c1_wag = _comparison(comparisons, "athan_table9_phase1_wag_1_23")
    c1_electricity = _comparison(comparisons, "c1_official_total_site_electricity_17_8pj_missing")
    athan_c0 = register["athan_table8_current_wag_2_74"]
    athan_c1 = register["athan_table9_phase1_wag_1_23"]
    return [
        {
            "decision_id": "AH_01",
            "topic": "Athanasiadis_WAG_definition",
            "evidence": f"C0 ratio={c0_wag['ratio_model_to_anchor']}; C1 ratio={c1_wag['ratio_model_to_anchor']}; both remain conditional_not_a_score.",
            "status": "context_only_not_scoreable",
            "allowed_now": "Retain as Rank-3 model-precedent context and report the discrepancy.",
            "blocked_now": "Do not tune BFG/COG/BOFG coefficients or choose sensitivity targets from these rows.",
            "required_before_unlock": "Confirm metric definition, energy/electricity basis, and production denominator from a user-provided locator or source-card repair.",
            "go_no_go": "NO_GO_FOR_SCORING",
        },
        {
            "decision_id": "AH_02",
            "topic": "production_denominator_bridge",
            "evidence": "Current diagnostics divide model totals by final-product proxy; official anchors use liquid-steel or site-total annual boundaries.",
            "status": "bridge_design_required",
            "allowed_now": "Report raw totals and parallel per-final-product-proxy intensities with explicit caveats.",
            "blocked_now": "Do not turn annual ratios into a combined score or blindly scale site totals.",
            "required_before_unlock": "Map each target metric to a model numerator and a compatible liquid-steel, HRC, final-product, or site-total denominator.",
            "go_no_go": "NO_GO_FOR_COMBINED_ANCHOR_SCORE",
        },
        {
            "decision_id": "AH_03",
            "topic": "anchor_scoreability",
            "evidence": "All 15 current normalised comparisons are labelled conditional_not_a_score; official/MER anchors outrank model-precedent values.",
            "status": "reporting_only",
            "allowed_now": "Use source rank and residuals for a transparent diagnostic dashboard.",
            "blocked_now": "Do not fit parameter combinations to anchors or make anchors optimisation constraints.",
            "required_before_unlock": "For each candidate score, freeze numerator boundary, denominator, scaling rule, locator status, and no-double-counting policy.",
            "go_no_go": "NO_GO_FOR_SENSITIVITY_SCORING",
        },
        {
            "decision_id": "AH_04",
            "topic": "C1_electricity_boundary",
            "evidence": f"C1 represented electricity/official-site ratio={c1_electricity['ratio_model_to_anchor']}; current comparison is conditional because the site/downstream boundary is partial.",
            "status": "non_wag_decomposition_ready",
            "allowed_now": "Decompose non-WAG gross loads into named DRP, EAF, ASU, HSM/WBW, KGF, BOF/OSF, DSP/downstream, and background buckets.",
            "blocked_now": "Do not add a residual electricity load to the optimiser or reinterpret WAG/generator offsets outside C5p_o.",
            "required_before_unlock": "Show whether the gap is a missing named load, background residual, internal-offset issue, or overlap with an existing bucket.",
            "go_no_go": "GO_FOR_NON_WAG_DIAGNOSTIC_ONLY",
        },
        {
            "decision_id": "AH_05",
            "topic": "residual_KPI_policy",
            "evidence": "Canonical register classifies electricity and NG residuals as diagnostic/reporting objects; C5p_o keeps WAG-dependent allocation caveated.",
            "status": "diagnostic_allowed",
            "allowed_now": "Keep signed residual electricity and NG visible by configuration and metric boundary.",
            "blocked_now": "Do not allocate, cost, floor, or calibrate residuals as hidden variables.",
            "required_before_unlock": "A source-backed represented-asset boundary and accepted controller-compatible fuel logic.",
            "go_no_go": "GO_FOR_REPORTING_ONLY",
        },
        {
            "decision_id": "AH_06",
            "topic": "WAG_interface_boundary",
            "evidence": f"C5p_o status is diagnostic_interface_ready; Athanasiadis WAG rows have locator quality {athan_c0['locator_quality']}/{athan_c1['locator_quality']} and unresolved denominators.",
            "status": "C5p_o_authoritative",
            "allowed_now": "Use only carrier-specific BFG/COG/BOFG outputs from C5p_o for WAG-dependent diagnostics.",
            "blocked_now": "Do not use aggregate_wag, mixed_wag, or C5p_k for physical allocation or reconciliation.",
            "required_before_unlock": "Separate future hardening task for any additional physical WAG controller behaviour.",
            "go_no_go": "GO_WITH_WAG_CAVEAT",
        },
    ]


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    with WAG_SUMMARY.open(encoding="utf-8") as handle:
        wag = json.load(handle)
    return {
        "stage": STAGE,
        "status": "design_complete_no_model_changes",
        "output_policy": "minimal",
        "run_class": "diagnostic_design",
        "lineage_role": "diagnostic",
        "decision_rows": len(rows),
        "athanasiadis_wag_scoreability": "context_only_not_scoreable",
        "combined_anchor_scoring": "NO_GO",
        "c1_non_wag_electricity_decomposition": "GO_DIAGNOSTIC_ONLY",
        "residual_kpis": "GO_REPORTING_ONLY",
        "wag_interface": wag["contract_status"],
        "guardrails": {
            "raw_pdfs_inspected": False,
            "sensitivity_run": False,
            "coefficient_tuning": False,
            "model_equations_changed": False,
            "source_cards_changed": False,
            "executable_inputs_changed": False,
            "c5p_k_physical_use": False,
        },
        "recommended_next_action": "Run a non-WAG C1 electricity-boundary decomposition before sensitivity design.",
    }


def write_report(summary: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        """# C5 Anchor Boundary Reconciliation Design

## Purpose

This compact C5p_ah stage turns the unresolved annual-anchor comparisons into
explicit design decisions. It does not change the model, source cards,
coefficients, or executable inputs, and it does not run sensitivities.

## Decisions

- Athanasiadis Table 8/9 WAG totals remain Rank-3 model-precedent context only.
  Their metric definition and denominator are unresolved, so they cannot score
  or tune the model.
- A denominator bridge is required before any combined annual anchor score:
  model final-product proxy, liquid steel, HRC/downstream, and site totals must
  remain distinct.
- Current residual electricity and NG are signed reporting KPIs, never hidden
  loads, costs, allocations, or calibration plugs.
- C1 non-WAG electricity decomposition may proceed. It must keep gross demand,
  internal generation offsets, grid import, and WAG interpretation separate.
- C5p_o remains the authoritative diagnostic WAG interface. Aggregate WAG,
  mixed WAG, and C5p_k cannot be used for physical reconciliation.

## Gate

The next safe implementation is a non-WAG C1 electricity-boundary
decomposition. Sensitivity scoring remains blocked until a numerator,
denominator, scaling rule, locator status, and boundary are explicit for every
scored anchor.
""",
        encoding="utf-8",
    )


def run_anchor_boundary_reconciliation_design(*, output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    for path in (ANCHOR_COMPARISON, ANCHOR_REGISTER, WAG_SUMMARY):
        if not path.exists():
            raise FileNotFoundError(f"Required prior diagnostic input missing: {path}")
    rows = build_decision_rows()
    summary = build_summary(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "anchor_boundary_decision_table.csv", rows)
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "s4_4c5p_ah_stage_gate.json", {"stage": STAGE, "status": summary["status"], "go_no_go": {key: summary[key] for key in ("athanasiadis_wag_scoreability", "combined_anchor_scoring", "c1_non_wag_electricity_decomposition", "residual_kpis")}})
    write_report(summary)
    return summary


def main() -> int:
    run_anchor_boundary_reconciliation_design()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
