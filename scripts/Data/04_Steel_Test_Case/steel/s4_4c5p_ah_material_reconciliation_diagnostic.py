"""Source-backed material reconciliation before capacity/yield migration."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .s4_4c5p_ag_capacity_boundary_audit import DEFAULT_RUN_ROOT


RUN_ID = "steel_material_reconciliation_v1"
HOURS_PER_WEEK = 168.0
DAYS_PER_YEAR = 365.0
TARGET_MT_Y = 6.75


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _annualise(weekly_t: float) -> float:
    return weekly_t / 7.0 * DAYS_PER_YEAR / 1_000_000.0


def run_material_reconciliation_diagnostic(*, output_root: str | Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    run_directory = Path(output_root).resolve() / RUN_ID
    if run_directory.exists():
        raise ValueError(f"Run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True)

    source_rows = [
        {
            "bundle_id": "active_c0_chain",
            "parameter_group": "C0 iron_ore_to_sinter_to_hot_metal",
            "values": "iron_ore_to_sinter=1.0; hot_metal_per_sinter=2.1041666667",
            "source_status": "development_only",
            "allowed_use": "current executable baseline only",
            "decision": "do_not_promote",
        },
        {
            "bundle_id": "sinter_bf_candidate_comparison",
            "parameter_group": "C0 iron_ore_to_sinter_to_hot_metal",
            "values": "sinter_per_iron_ore=1.230; sinter_per_hot_metal=1.088",
            "source_status": "development_candidate",
            "allowed_use": "comparison only; not a coherent executable bundle",
            "decision": "blocked_pending_bf_sinter_basis_reconciliation",
        },
        {
            "bundle_id": "mer_c1_eaf_material_context",
            "parameter_group": "HDRI_plus_scrap_to_liquid_steel",
            "values": "HDRI=2.8 Mt/y; scrap≈1.0 Mt/y; liquid_steel≈3.3 Mt/y",
            "source_status": "primary_public_validation_context",
            "allowed_use": "diagnostic material-balance target",
            "decision": "eligible_for_named_scrap_balance_design",
        },
        {
            "bundle_id": "athanasiadis_drp_operating_band",
            "parameter_group": "DRP pellets_to_DRI",
            "values": "average=500 t_pellets/h; range=0.7–1.1; DRI_yield=0.74",
            "source_status": "model_precedent_development",
            "allowed_use": "hourly guardrail/sensitivity only",
            "decision": "not_nameplate_or_annual_availability",
        },
    ]

    c0_active_week = 320.0 * HOURS_PER_WEEK * 1.0 * 2.1041666667
    c0_candidate_comparison_week = 320.0 * HOURS_PER_WEEK * 1.230 / 1.088
    bf_rows = [
        {
            "case_id": "active_executable_chain",
            "iron_ore_capacity_t_h": 320.0,
            "sinter_per_iron_ore": 1.0,
            "hot_metal_per_sinter": 2.1041666667,
            "final_product_t_week": round(c0_active_week, 6),
            "annualised_final_product_mt_y": round(_annualise(c0_active_week), 6),
            "status": "baseline_only",
            "caveat": "Exact current capacity-probe chain; all rows are development-only.",
        },
        {
            "case_id": "candidate_rows_combined_for_scale_check",
            "iron_ore_capacity_t_h": 320.0,
            "sinter_per_iron_ore": 1.230,
            "hot_metal_per_sinter": round(1.0 / 1.088, 8),
            "final_product_t_week": round(c0_candidate_comparison_week, 6),
            "annualised_final_product_mt_y": round(_annualise(c0_candidate_comparison_week), 6),
            "status": "not_executable",
            "caveat": "Scale comparison only. Sinter output factor omits raw-mix inputs; BF candidate requires burden reconciliation.",
        },
    ]

    weekly_hdri = 2_800_000.0 / DAYS_PER_YEAR * 7.0
    weekly_scrap = 1_000_000.0 / DAYS_PER_YEAR * 7.0
    weekly_ls = 3_300_000.0 / DAYS_PER_YEAR * 7.0
    c1_current_drp_max_dri = 550.0 * 0.74 * HOURS_PER_WEEK
    c1_current_eaf_proxy_output = c1_current_drp_max_dri * 0.95
    c1_retained_capacity_output = 60_095.000001
    eaf_rows = [
        {
            "case_id": "current_dri_only_proxy_at_drp_upper_band",
            "weekly_hdri_t": round(c1_current_drp_max_dri, 6),
            "weekly_scrap_t": 0.0,
            "weekly_liquid_steel_or_final_t": round(c1_current_eaf_proxy_output, 6),
            "hdri_per_t_output": round(1.0 / 0.95, 6),
            "scrap_per_t_output": 0.0,
            "status": "current_executable_proxy",
            "caveat": "Scrap is reported but not an output-contributing material in the current compact EAF equation.",
        },
        {
            "case_id": "mer_annual_material_context_scaled_to_week",
            "weekly_hdri_t": round(weekly_hdri, 6),
            "weekly_scrap_t": round(weekly_scrap, 6),
            "weekly_liquid_steel_or_final_t": round(weekly_ls, 6),
            "hdri_per_t_output": round(2.8 / 3.3, 6),
            "scrap_per_t_output": round(1.0 / 3.3, 6),
            "status": "primary_validation_context",
            "caveat": "Annual planning context, not hourly dispatch capacity. Requires named scrap supply and liquid-steel/final-product boundary before implementation.",
        },
    ]
    c1_mer_context_total = c1_retained_capacity_output + weekly_ls
    sensitivity_rows = [
        {
            "scenario_id": "baseline_capacity_probe",
            "configuration": "C1",
            "route_t_week": round(c1_retained_capacity_output + c1_current_eaf_proxy_output, 6),
            "annualised_mt_y": round(_annualise(c1_retained_capacity_output + c1_current_eaf_proxy_output), 6),
            "target_gap_mt_y": round(_annualise(c1_retained_capacity_output + c1_current_eaf_proxy_output) - TARGET_MT_Y, 6),
            "status": "solved_capacity_probe",
            "decision": "baseline",
        },
        {
            "scenario_id": "mer_annual_context_not_hourly_capacity",
            "configuration": "C1",
            "route_t_week": round(c1_mer_context_total, 6),
            "annualised_mt_y": round(_annualise(c1_mer_context_total), 6),
            "target_gap_mt_y": round(_annualise(c1_mer_context_total) - TARGET_MT_Y, 6),
            "status": "comparison_only",
            "decision": "does_not_authorise_capacity_or_yield_change",
        },
        {
            "scenario_id": "bf_sinter_candidate_scale_check",
            "configuration": "C0",
            "route_t_week": round(c0_candidate_comparison_week, 6),
            "annualised_mt_y": round(_annualise(c0_candidate_comparison_week), 6),
            "target_gap_mt_y": round(_annualise(c0_candidate_comparison_week) - TARGET_MT_Y, 6),
            "status": "comparison_only",
            "decision": "blocked_pending_bf_sinter_basis_reconciliation",
        },
    ]

    _write_csv(run_directory / "source_bundle_register.csv", source_rows)
    _write_csv(run_directory / "bf_sinter_basis_matrix.csv", bf_rows)
    _write_csv(run_directory / "c1_eaf_material_balance.csv", eaf_rows)
    _write_csv(run_directory / "coherent_sensitivity_screen.csv", sensitivity_rows)
    _write_json(
        run_directory / "summary.json",
        {
            "run_id": RUN_ID,
            "status": "pass_with_implementation_gates",
            "c1_eaf_named_scrap_balance_ready_for_design": True,
            "c1_eaf_equation_change_approved": False,
            "bf_sinter_parameter_change_approved": False,
            "full_sensitivity_execution_approved": False,
            "next_gate": "implement C1 named HDRI+scrap-to-liquid-steel diagnostic before changing capacity or yield",
        },
    )
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a source-basis and scale diagnostic, not an optimiser run.\n"
        "- It does not change capacity, conversion, topology, WAG, steam, NG or CO2 logic.\n"
        "- MER annual context is not silently converted into an hourly capacity.\n"
        "- Candidate BF/Sinter rows are intentionally not combined as executable inputs.\n",
        encoding="utf-8",
    )
    return {"run_directory": run_directory, "sensitivity_rows": sensitivity_rows}
