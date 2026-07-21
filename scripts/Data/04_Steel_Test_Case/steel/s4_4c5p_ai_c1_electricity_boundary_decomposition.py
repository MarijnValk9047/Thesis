"""Decompose represented C1 electricity without changing the physical model.

The stage derives only loads already implied by the closed-loop activity output
and active development-controller contract.  It leaves absent asset loads and
the remaining site gap visibly unallocated.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .wag_development_controller_contract import (
    hsm_rolling_electricity_mwh_per_t_hrc,
    load_development_controller_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
STAGE = "S4.4c5p_ai_c1_electricity_boundary_decomposition"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
INPUT_DIR = REPO_ROOT / "data" / "03_Optimisation" / "runs" / "steel_closed_loop_feasibility_anchor_reconciliation_v1"
OUTPUT_DIR = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4" / "s4_4c5p_ai_c1_electricity_boundary_decomposition"
REPORT_PATH = REPO_ROOT / "docs" / "optimisation" / "steel" / "S4" / "C5_C1_ELECTRICITY_BOUNDARY_DECOMPOSITION.md"
ENERGY_INPUTS = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4" / "s4_4b5a_asymmetric_c0_c1_correction" / "corrected_dev_inputs" / "process_energy_intensities.csv"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str | None) -> float:
    return 0.0 if value in (None, "") else float(value)


def _sum(rows: list[dict[str, str]], field: str) -> float:
    return sum(_num(row.get(field)) for row in rows)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(rows[0]) if rows else ["bucket"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _electricity_intensity(process_id: str) -> float:
    rows = _read_csv(ENERGY_INPUTS)
    row = next(
        item for item in rows
        if item["process_id"] == process_id and item["carrier"] == "electricity" and item["direction"] == "input"
    )
    return float(row["intensity"])


def build_decomposition_rows() -> tuple[list[dict[str, Any]], dict[str, float]]:
    hourly = [row for row in _read_csv(INPUT_DIR / "first_window_hourly.csv") if row["configuration_id"] == C1]
    drp = _sum(hourly, "C1_DRP_activity_t_pellets_h") * _electricity_intensity("C1_DRP")
    eaf = _sum(hourly, "C1_EAF_activity_t_DRI_h") * _electricity_intensity("C1_EAF")
    hsm = _sum(hourly, "C1_retained_HSM_input_t_h") * hsm_rolling_electricity_mwh_per_t_hrc()
    profile = load_development_controller_profile(C1)
    pefa = len(hourly) * 0.0213 * profile.pefa_pellets_t_h
    gross = _sum(hourly, "gross_electricity_mwh")
    generator_offset = _sum(hourly, "wag_electricity_mwh")
    net_import = _sum(hourly, "net_grid_import_mwh")
    # The current closed-loop gross-electricity output equals the active DRP/EAF
    # expression.  HSM and PEFA contract values exist, but are not integrated
    # into that particular C1 gross-load output and must not be double counted.
    explicit = drp + eaf
    remainder = gross - explicit
    if abs(remainder) < 1e-5:
        remainder = 0.0
    rows = [
        {
            "bucket": "DRP",
            "configuration": C1,
            "current_model_mwh": round(drp, 6),
            "contract_implied_mwh": "",
            "unit": "MWh per first 24h execution window",
            "source_or_stage": "C1_DRP activity plus existing executable development intensity",
            "boundary_status": "explicit_represented",
            "overlap_risk": "low",
            "candidate_status": "existing_development_input",
            "action": "retain as named C1 gross-electricity bucket",
        },
        {
            "bucket": "EAF",
            "configuration": C1,
            "current_model_mwh": round(eaf, 6),
            "contract_implied_mwh": "",
            "unit": "MWh per first 24h execution window",
            "source_or_stage": "C1_EAF activity plus existing executable development intensity",
            "boundary_status": "explicit_represented",
            "overlap_risk": "low",
            "candidate_status": "existing_development_input",
            "action": "retain as named C1 gross-electricity bucket",
        },
        {
            "bucket": "HSM_WBW_rolling",
            "configuration": C1,
            "current_model_mwh": "",
            "contract_implied_mwh": round(hsm, 6),
            "unit": "MWh per first 24h execution window",
            "source_or_stage": "active C5l development-controller contract",
            "boundary_status": "contract_exists_not_integrated_in_current_C1_gross_output",
            "overlap_risk": "low_in_current_gross_high_if_added_without_reconciliation",
            "candidate_status": "development_only",
            "action": "report as an absent named C1 load; do not add it until retained-route controller integration is explicitly reconciled",
        },
        {
            "bucket": "PEFA_controller",
            "configuration": C1,
            "current_model_mwh": "",
            "contract_implied_mwh": round(pefa, 6),
            "unit": "MWh per first 24h execution window",
            "source_or_stage": "active C5l development-controller contract",
            "boundary_status": "contract_exists_not_integrated_in_current_C1_gross_output",
            "overlap_risk": "low_in_current_gross_high_if_added_without_reconciliation",
            "candidate_status": "development_only",
            "action": "report as an absent named C1 load; do not add it until PEFA controller integration is explicitly reconciled",
        },
        {
            "bucket": "unattributed_represented_gross_electricity",
            "configuration": C1,
            "current_model_mwh": round(remainder, 6),
            "contract_implied_mwh": "",
            "unit": "MWh per first 24h execution window",
            "source_or_stage": "gross electricity minus explicitly reconstructed DRP/EAF",
            "boundary_status": "requires_field_level_reconciliation",
            "overlap_risk": "high",
            "candidate_status": "not_a_new_load",
            "action": "trace against model output/reporting fields before treating as a missing process load",
        },
        {
            "bucket": "ASU_oxygen",
            "configuration": C1,
            "current_model_mwh": "",
            "contract_implied_mwh": "",
            "unit": "not separately visible in current first-window output",
            "source_or_stage": "C5 anchor context only",
            "boundary_status": "not_separately_represented",
            "overlap_risk": "unknown",
            "candidate_status": "source_review_before_migration",
            "action": "keep outside gross-load sum until its model linkage and overlap are established",
        },
        {
            "bucket": "KGF_BOF_OSF_DSP_background_site",
            "configuration": C1,
            "current_model_mwh": "",
            "contract_implied_mwh": "",
            "unit": "not separately visible in current first-window output",
            "source_or_stage": "C5p_i candidate and anchor context",
            "boundary_status": "not_separately_represented",
            "overlap_risk": "unknown",
            "candidate_status": "source_review_and_boundary_reconciliation_required",
            "action": "do not infer or allocate; keep as named investigation list for later decomposition",
        },
    ]
    return rows, {
        "gross_mwh": gross,
        "explicit_reconstructed_mwh": explicit,
        "unattributed_represented_mwh": remainder,
        "generator_offset_mwh": generator_offset,
        "net_import_mwh": net_import,
    }


def build_reconciliation_rows(values: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {
            "configuration": C1,
            "gross_electricity_mwh": round(values["gross_mwh"], 6),
            "internal_generator_offset_mwh": round(values["generator_offset_mwh"], 6),
            "net_grid_import_mwh": round(values["net_import_mwh"], 6),
            "identity_residual_mwh": round(values["gross_mwh"] - values["generator_offset_mwh"] - values["net_import_mwh"], 6),
            "wag_interpretation": "C5p_o caveated diagnostic interface only",
            "status": "pass_if_identity_residual_is_zero",
        }
    ]


def build_residual_rows(values: dict[str, float]) -> list[dict[str, Any]]:
    official_site_mwh = 17.8 * 1_000_000.0 / 3.6
    annual_factor = 8760.0 / 24.0
    gross_annual = values["gross_mwh"] * annual_factor
    return [
        {
            "configuration": C1,
            "metric": "gross_electricity_site_context_residual",
            "model_value_mwh_y_proxy": round(gross_annual, 6),
            "anchor_value_mwh_y": round(official_site_mwh, 6),
            "signed_residual_mwh_y": round(official_site_mwh - gross_annual, 6),
            "status": "diagnostic_only_not_an_optimizer_load",
            "caveat": "Annualisation is a first-window proxy; the official anchor is partial-provenance site context with denominator/boundary caveats.",
        },
        {
            "configuration": C1,
            "metric": "unattributed_represented_gross_electricity",
            "model_value_mwh_per_window": round(values["unattributed_represented_mwh"], 6),
            "anchor_value_mwh_y": "",
            "signed_residual_mwh_y": "",
            "status": "trace_before_treating_as_missing_load",
            "caveat": "This is inside current gross electricity but not reconstructed by the four named explicit buckets.",
        },
    ]


def write_report(values: dict[str, float]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        f"""# C5 C1 Electricity Boundary Decomposition

## Result

The current C1 first-window gross electricity is {values['gross_mwh']:.3f} MWh.
It is fully explained by the active DRP and EAF electricity expressions.
HSM and PEFA development-controller electricity contracts exist, but are not
integrated into this closed-loop C1 gross-electricity output; their implied
values are reported separately rather than double counted.

ASU/oxygen, KGF, BOF/OSF, DSP/downstream and background site electricity are
not separately visible in this output. They therefore remain named boundary
gaps, not inferred loads. The site-level electricity residual is retained as a
signed reporting KPI only.

## Guardrails

- No model equation, input, source card or WAG allocation changed.
- Gross demand, generator offset and net import remain separate.
- C5p_o is the authoritative WAG interface; no WAG conclusion is drawn from
  the remaining electricity gap.
- The 17.8 PJ/y site anchor is validation context, not an optimisation target.
""",
        encoding="utf-8",
    )


def run_c1_electricity_boundary_decomposition(*, output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    for path in (INPUT_DIR / "first_window_hourly.csv", ENERGY_INPUTS):
        if not path.exists():
            raise FileNotFoundError(f"Required input missing: {path}")
    buckets, values = build_decomposition_rows()
    reconciliation = build_reconciliation_rows(values)
    residuals = build_residual_rows(values)
    summary = {
        "stage": STAGE,
        "status": "diagnostic_complete_no_model_changes",
        "output_policy": "minimal",
        "run_class": "diagnostic_decomposition",
        "lineage_role": "diagnostic",
        "gross_electricity_mwh_per_first_window": round(values["gross_mwh"], 6),
        "explicit_reconstructed_mwh_per_first_window": round(values["explicit_reconstructed_mwh"], 6),
        "unattributed_represented_mwh_per_first_window": round(values["unattributed_represented_mwh"], 6),
        "generator_offset_mwh_per_first_window": round(values["generator_offset_mwh"], 6),
        "net_grid_import_mwh_per_first_window": round(values["net_import_mwh"], 6),
        "named_missing_or_not_visible_buckets": ["HSM_WBW_rolling", "PEFA_controller", "ASU_oxygen", "KGF_BOF_OSF_DSP_background_site"],
        "go_no_go": {
            "non_wag_electricity_boundary_decomposition": "GO_DIAGNOSTIC_COMPLETE",
            "electricity_candidate_migration": "NO_GO",
            "residual_electricity_as_optimizer_load": "NO_GO",
            "wag_dependent_generator_interpretation": "CAVEATED_ONLY",
            "sensitivity_execution": "NO_GO",
        },
        "guardrails": {
            "model_equations_changed": False,
            "executable_inputs_changed": False,
            "source_cards_changed": False,
            "raw_pdfs_inspected": False,
            "sensitivity_run": False,
            "wag_allocation_changed": False,
        },
        "recommended_next_action": "Design a retained-route electricity integration gate for the already-defined HSM/PEFA contracts before proposing any new candidate load.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "c1_electricity_boundary_decomposition.csv", buckets)
    _write_csv(output_dir / "gross_net_offset_reconciliation.csv", reconciliation)
    _write_csv(output_dir / "residual_electricity_kpi.csv", residuals)
    _write_json(output_dir / "summary.json", summary)
    write_report(values)
    return summary


def main() -> int:
    run_c1_electricity_boundary_decomposition()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
