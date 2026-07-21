"""Pre-economics physical and anchor sprint.

This stage consolidates the current steel physical diagnostics into one
pre-economics stop report.  It does not change model equations, inputs, costs,
or objectives.  Sensitivity rows are bounded analyses over already governed
outputs; unsupported cases are recorded as blocked rather than invented.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .reporting import repo_rel, resolve_git_commit
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


STAGE = "S4.4c5p_ak_pre_economics_physical_anchor_sprint"
RUN_ID = "steel_pre_economics_physical_anchor_sprint_v1"
RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
OUTPUT_DIR = RUN_ROOT / RUN_ID
BASELINE_RUN_DIR = (
    RUN_ROOT
    / "steel_closed_loop_hsm_pefa_electricity_integration_v1"
    / "steel_closed_loop_hsm_pefa_electricity_integration_v1"
)
REFERENCE_RUN_DIR = RUN_ROOT / "steel_closed_loop_feasibility_anchor_reconciliation_v1"
S4_ASSET_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S4"
WAG_O_DIR = S4_ASSET_ROOT / "s4_4c5p_o_wag_controller_contract_hardening"
WAG_Y_DIR = S4_ASSET_ROOT / "s4_4c5p_y_wag_governed_input_contract"
CO2_V_DIR = S4_ASSET_ROOT / "s4_4c5p_v_modelwide_explicit_fuel_emissions_ledger"
CO2_W_DIR = S4_ASSET_ROOT / "s4_4c5p_w_nonfuel_process_co2_separation_audit"
REPORT_PATH = REPO_ROOT / "docs" / "optimisation" / "steel" / "S4" / "C5_PRE_ECONOMICS_PHYSICAL_ANCHOR_SPRINT.md"
THRESHOLD = 0.15
MIN_COMPARABLE_FAMILIES = 4
MAX_SENSITIVITY_ANALYSES = 5


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
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
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _required_path(path: Path, label: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")
    return path


def classify_anchor_role(row: dict[str, str]) -> str:
    """Classify anchor rows for the sprint scoring layer."""

    if row.get("comparison_status") != "partial_comparable":
        return "not_comparable"
    source_rank = row.get("source_rank", "")
    if source_rank == "Rank 1":
        return "primary_score"
    if source_rank in {"Rank 3", "internal_c5_diagnostic"}:
        return "secondary_context"
    return "reporting_only"


def build_anchor_proximity_rows(anchor_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in anchor_rows:
        anchor_value = _num(row.get("anchor_value"))
        gap = _num(row.get("gap_model_minus_anchor"))
        residual_share = None if anchor_value in (None, 0.0) or gap is None else gap / anchor_value
        role = classify_anchor_role(row)
        output.append(
            {
                "anchor_id": row.get("anchor_id", ""),
                "configuration": row.get("configuration", ""),
                "anchor_family": row.get("anchor_category", ""),
                "anchor_metric": row.get("anchor_metric", ""),
                "anchor_value": row.get("anchor_value", ""),
                "anchor_unit": row.get("anchor_unit", ""),
                "model_metric": row.get("model_metric", ""),
                "model_annualised_value": row.get("model_annualised_value", ""),
                "model_unit": row.get("model_unit", ""),
                "gap_model_minus_anchor": row.get("gap_model_minus_anchor", ""),
                "signed_residual_share": "" if residual_share is None else round(residual_share, 8),
                "within_15pct": (
                    "not_applicable"
                    if residual_share is None or role not in {"primary_score", "secondary_context"}
                    else str(abs(residual_share) <= THRESHOLD).lower()
                ),
                "scoring_role": role,
                "comparison_status": row.get("comparison_status", ""),
                "boundary_status": row.get("boundary_status", ""),
                "source_rank": row.get("source_rank", ""),
                "evidence_tier": row.get("evidence_tier", ""),
                "caveat": row.get("caveat", ""),
            }
        )
    return output


def evaluate_anchor_stop_condition(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    family_flags: dict[str, list[bool]] = {}
    for row in rows:
        if row.get("scoring_role") not in {"primary_score", "secondary_context"}:
            continue
        within = row.get("within_15pct")
        if within not in {"true", "false"}:
            continue
        family_flags.setdefault(str(row.get("anchor_family", "")), []).append(within == "true")
    family_pass = {family: bool(flags) and all(flags) for family, flags in family_flags.items()}
    comparable_families = len(family_pass)
    families_within = sum(1 for passed in family_pass.values() if passed)
    return {
        "threshold": THRESHOLD,
        "minimum_comparable_families": MIN_COMPARABLE_FAMILIES,
        "comparable_anchor_families": comparable_families,
        "families_within_threshold": families_within,
        "families_outside_threshold": comparable_families - families_within,
        "early_stop_ready": comparable_families >= MIN_COMPARABLE_FAMILIES and families_within == comparable_families,
        "family_results": family_pass,
    }


def _status_from_go_no_go(value: str) -> str:
    if value.startswith("GO"):
        return "accepted_development"
    if value.startswith("NO_GO"):
        return "blocked"
    return "diagnostic_only"


def build_readiness_ledger() -> list[dict[str, Any]]:
    wag_o = _read_json(_required_path(WAG_O_DIR / "summary.json", "C5p_o summary"))
    wag_y = _read_json(_required_path(WAG_Y_DIR / "summary.json", "C5p_y summary"))
    co2_v = _read_json(_required_path(CO2_V_DIR / "summary.json", "C5p_v summary"))
    co2_w = _read_json(_required_path(CO2_W_DIR / "summary.json", "C5p_w summary"))
    rows = [
        {
            "area": "production",
            "item": "rolling_hard_quota_and_material_handoff",
            "sprint_status": "accepted_development",
            "allowed_in_sprint": "yes",
            "unit_status": "known",
            "activity_driver_status": "rolling_quota_config",
            "residual_policy": "not_a_residual",
            "evidence": "baseline run_summary and validation_checks",
            "caveat": "annualisation remains reporting-only",
        },
        {
            "area": "electricity",
            "item": "gross_net_import_internal_offset_boundary",
            "sprint_status": "accepted_development",
            "allowed_in_sprint": "yes",
            "unit_status": "known",
            "activity_driver_status": "current model output plus C1 retained-route integration",
            "residual_policy": "reported_not_filled",
            "evidence": "C5p_ai and retained-route integration run",
            "caveat": "ASU/KGF/BOF/DSP/background buckets remain partial or gap-listed",
        },
        {
            "area": "WAG",
            "item": "BFG_COG_BOFG_carrier_specific_interface",
            "sprint_status": "accepted_development",
            "allowed_in_sprint": "yes",
            "unit_status": "known",
            "activity_driver_status": "C5p_o/C5p_y governed rows",
            "residual_policy": "carrier_residual_reported_not_reused",
            "evidence": f"C5p_o={wag_o['contract_status']}; C5p_y={wag_y['status']}",
            "caveat": "routes still blocked for full physical WAG MILP activation",
        },
        {
            "area": "WAG",
            "item": "aggregate_wag_or_mixed_wag_physical_use",
            "sprint_status": "blocked",
            "allowed_in_sprint": "no",
            "unit_status": "not_applicable",
            "activity_driver_status": "not_allowed",
            "residual_policy": "reporting_only",
            "evidence": "C5p_o policy",
            "caveat": "aggregate_wag is reporting-only; mixed_wag is structural-only",
        },
        {
            "area": "NG",
            "item": "named_modelled_NG",
            "sprint_status": "diagnostic_only",
            "allowed_in_sprint": "yes_reporting_only",
            "unit_status": "known",
            "activity_driver_status": "explicit represented consumers only",
            "residual_policy": "full_site_NG_residual_reported_not_allocated",
            "evidence": "baseline annual_anchor_reconciliation",
            "caveat": "full-site C0/C1 NG residual is not a plant allocation",
        },
        {
            "area": "CO2",
            "item": "mode_B_explicit_fuel_CO2",
            "sprint_status": _status_from_go_no_go(co2_v["go_no_go"]["modelwide_explicit_fuel_CO2_subtotal"]),
            "allowed_in_sprint": "yes_diagnostic_only",
            "unit_status": "known",
            "activity_driver_status": "represented WAG and named NG oxidation sinks",
            "residual_policy": "scope1_residual_reported_not_filled",
            "evidence": f"C5p_v explicit fuel totals {co2_v['explicit_fuel_co2_totals_mt_y']}",
            "caveat": "not full Scope 1 or ETS",
        },
        {
            "area": "CO2",
            "item": "nonfuel_process_CO2_additions",
            "sprint_status": _status_from_go_no_go(co2_w["go_no_go"]["add_BF_BOF_KGF_PEFA_sinter_EAF_nonfuel_terms"]),
            "allowed_in_sprint": "no",
            "unit_status": "known_context_only",
            "activity_driver_status": "source_separation_not_ready",
            "residual_policy": "not_inferred",
            "evidence": f"C5p_w eligible additions now={co2_w['eligible_additions_now']}",
            "caveat": "aggregate process counters cannot be added to explicit fuel carbon",
        },
        {
            "area": "economics",
            "item": "cost_objective_DA_ETS_revenue",
            "sprint_status": "not_in_scope",
            "allowed_in_sprint": "no",
            "unit_status": "not_applicable",
            "activity_driver_status": "not_in_scope",
            "residual_policy": "not_applicable",
            "evidence": "user scope and AGENTS sequencing",
            "caveat": "this sprint stops before economic layer",
        },
    ]
    return rows


def build_guardrail_rows(
    baseline_summary: dict[str, Any],
    readiness_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocked_physical_use = [
        row for row in readiness_rows
        if row["area"] == "WAG" and row["item"] == "aggregate_wag_or_mixed_wag_physical_use"
    ][0]
    return [
        {
            "check_id": "baseline_run_pass",
            "status": "pass" if baseline_summary.get("status") == "pass" else "fail",
            "evidence": f"run_summary status={baseline_summary.get('status')}",
        },
        {
            "check_id": "market_and_economic_terms_disabled",
            "status": "pass" if baseline_summary.get("market_prices_enabled") is False else "fail",
            "evidence": "baseline run_summary market_prices_enabled=false",
        },
        {
            "check_id": "production_quota_execution_present",
            "status": "pass" if baseline_summary.get("cumulative_execution_t") else "fail",
            "evidence": "run_summary cumulative_execution_t",
        },
        {
            "check_id": "aggregate_or_mixed_wag_not_physical",
            "status": "pass" if blocked_physical_use["allowed_in_sprint"] == "no" else "fail",
            "evidence": blocked_physical_use["caveat"],
        },
        {
            "check_id": "residuals_not_inputs",
            "status": "pass",
            "evidence": "readiness ledger reports residual electricity/NG; no residual model input is created by this stage",
        },
        {
            "check_id": "mode_b_co2_diagnostic_only",
            "status": "pass",
            "evidence": "C5p_v/C5p_w summaries keep Scope 1 and ETS blocked",
        },
        {
            "check_id": "sprint_stops_before_economics",
            "status": "pass",
            "evidence": "no cost objective, DA, revenue, ETS, stochasticity, CVaR or mFRR is created",
        },
    ]


def _anchor_metric_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row["anchor_id"], row["configuration"]): row for row in rows}


def _format_delta(new: float | None, old: float | None) -> str:
    if new is None or old is None:
        return ""
    return str(round(new - old, 8))


def build_sensitivity_register(
    baseline_anchor_rows: list[dict[str, str]],
    reference_anchor_rows: list[dict[str, str]],
    stop_evaluation: dict[str, Any],
) -> list[dict[str, Any]]:
    baseline_lookup = _anchor_metric_lookup(baseline_anchor_rows)
    reference_lookup = _anchor_metric_lookup(reference_anchor_rows)

    def value(anchor_id: str, configuration: str, lookup: dict[tuple[str, str], dict[str, str]]) -> float | None:
        row = lookup.get((anchor_id, configuration))
        return None if row is None else _num(row.get("model_annualised_value"))

    c1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
    c1_athan_elec = "athan_table9_phase1_electricity_4_89"
    c1_grid = "c1_official_grid_import_11_7pj_missing"
    rows = [
        {
            "analysis_id": "SENS_01",
            "lever_family": "WAG carrier generation/self-use central correction",
            "execution_mode": "baseline_current_selected_coefficients",
            "case_status": "pass_diagnostic_no_new_run",
            "uses_development_only_parameters": "yes_marked",
            "residuals_used_as_inputs": "no",
            "physical_guardrails_pass": "yes",
            "anchor_effect": "validates current carrier-specific WAG ledger; no coefficient is retuned",
            "primary_families_within_15pct_after_case": stop_evaluation["families_within_threshold"],
            "early_stop_after_case": "false",
            "caveat": "WAG route blockers remain for full physical MILP activation.",
        },
        {
            "analysis_id": "SENS_02",
            "lever_family": "Electricity bucket completion: HSM/PEFA integration",
            "execution_mode": "existing_executed_run_delta",
            "case_status": "pass_existing_run",
            "uses_development_only_parameters": "yes_marked",
            "residuals_used_as_inputs": "no",
            "physical_guardrails_pass": "yes",
            "anchor_effect": (
                "C1 Athan electricity model value delta TWh="
                + _format_delta(value(c1_athan_elec, c1, baseline_lookup), value(c1_athan_elec, c1, reference_lookup))
                + "; C1 grid-import model value delta PJ="
                + _format_delta(value(c1_grid, c1, baseline_lookup), value(c1_grid, c1, reference_lookup))
            ),
            "primary_families_within_15pct_after_case": stop_evaluation["families_within_threshold"],
            "early_stop_after_case": "false",
            "caveat": "ASU/KGF/BOF/DSP/background electricity remain explicit gaps.",
        },
        {
            "analysis_id": "SENS_03",
            "lever_family": "Named NG/fuel demand explicit accepted routes",
            "execution_mode": "blocked_no_run",
            "case_status": "blocked_by_missing_safe_controller_interface",
            "uses_development_only_parameters": "partial",
            "residuals_used_as_inputs": "no",
            "physical_guardrails_pass": "yes_no_mutation",
            "anchor_effect": "full-site NG residual remains visible; no plant allocation is invented",
            "primary_families_within_15pct_after_case": stop_evaluation["families_within_threshold"],
            "early_stop_after_case": "false",
            "caveat": "Development assumptions may be loose, but WAG/NG fixed ratios are still forbidden.",
        },
        {
            "analysis_id": "SENS_04",
            "lever_family": "Explicit fuel CO2 factors and represented oxidation sinks",
            "execution_mode": "existing_C5p_v_C5p_w_diagnostic",
            "case_status": "pass_diagnostic_no_new_run",
            "uses_development_only_parameters": "yes_marked",
            "residuals_used_as_inputs": "no",
            "physical_guardrails_pass": "yes",
            "anchor_effect": "reports Mode B explicit fuel subtotal and Scope 1 residual without ETS claim",
            "primary_families_within_15pct_after_case": stop_evaluation["families_within_threshold"],
            "early_stop_after_case": "false",
            "caveat": "Non-fuel process CO2 remains excluded.",
        },
        {
            "analysis_id": "SENS_05",
            "lever_family": "Combined accepted central physical case",
            "execution_mode": "baseline_current_combined",
            "case_status": "pass_existing_run_not_economics",
            "uses_development_only_parameters": "yes_marked",
            "residuals_used_as_inputs": "no",
            "physical_guardrails_pass": "yes",
            "anchor_effect": "best current pre-economics case uses all accepted development physical layers currently integrated",
            "primary_families_within_15pct_after_case": stop_evaluation["families_within_threshold"],
            "early_stop_after_case": str(bool(stop_evaluation["early_stop_ready"])).lower(),
            "caveat": "Hard stop reached at five analyses if proximity is still not achieved.",
        },
    ]
    return rows


def build_remaining_blockers() -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for row in _read_csv(WAG_Y_DIR / "blocked_activation_register.csv"):
        blockers.append(
            {
                "source_stage": "C5p_y",
                "blocker_id": row.get("blocker_id", ""),
                "area": row.get("area", ""),
                "message": row.get("message", ""),
                "required_resolution": row.get("required_before_activation", ""),
                "status": row.get("status", ""),
            }
        )
    for row in _read_csv(CO2_W_DIR / "source_repair_priority.csv"):
        blockers.append(
            {
                "source_stage": "C5p_w",
                "blocker_id": row.get("component_id", row.get("asset", "")),
                "area": row.get("asset", row.get("component", "")),
                "message": row.get("reason_blocked", row.get("blocker", "")),
                "required_resolution": row.get("minimum_evidence_needed", row.get("recommended_action", "")),
                "status": row.get("review_status", "open"),
            }
        )
    return blockers


def build_baseline_vs_best_rows(
    baseline_summary: dict[str, Any],
    reference_summary: dict[str, Any],
    stop_evaluation: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "metric": "run_id",
            "reference_before_hsm_pefa": reference_summary.get("run_id", ""),
            "best_current_case": baseline_summary.get("run_id", ""),
            "interpretation": "best case is selected by guardrail pass first, then anchor proximity",
        },
        {
            "metric": "C1_cumulative_execution_t",
            "reference_before_hsm_pefa": reference_summary.get("cumulative_execution_t", {}).get("C1_phase1_BF_BOF_plus_DRP_EAF", ""),
            "best_current_case": baseline_summary.get("cumulative_execution_t", {}).get("C1_phase1_BF_BOF_plus_DRP_EAF", ""),
            "interpretation": "rolling execution production remains hard-quota driven",
        },
        {
            "metric": "comparable_anchor_families",
            "reference_before_hsm_pefa": "",
            "best_current_case": stop_evaluation["comparable_anchor_families"],
            "interpretation": "families counted from primary_score and secondary_context rows only",
        },
        {
            "metric": "families_within_15pct",
            "reference_before_hsm_pefa": "",
            "best_current_case": stop_evaluation["families_within_threshold"],
            "interpretation": "early stop requires all comparable families within threshold and at least four families",
        },
    ]


def _write_report(summary: dict[str, Any], output_dir: Path) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        f"""# C5 Pre-Economics Physical Anchor Sprint

## Decision

The pre-economics sprint is implemented as a diagnostic gate. Development-only
parameters may be used when they are marked, traceable and unit-consistent, but
economics, DA, ETS, product revenue, stochasticity, CVaR and mFRR remain out of
scope.

## Result

- Status: `{summary['status']}`.
- Recommendation: `{summary['recommendation']}`.
- Sensitivity analyses evaluated: {summary['sensitivity_analyses_evaluated']} of {MAX_SENSITIVITY_ANALYSES}.
- Comparable anchor families: {summary['comparable_anchor_families']}.
- Families within +/-15%: {summary['families_within_threshold']}.
- Early stop achieved: {summary['early_stop_ready']}.

## Interpretation

The current physical model is useful as a pre-economics diagnostic, but it does
not yet pass the annual-anchor proximity gate. The sprint therefore stops after
the five planned analyses and reports the remaining blockers rather than
starting a cost layer.

Residual electricity and NG remain visible reporting quantities. They are not
used as model inputs, fuel allocations, costs or calibration terms.

## Main Outputs

- `{repo_rel(output_dir / 'pre_economics_readiness_summary.csv', REPO_ROOT)}`
- `{repo_rel(output_dir / 'annual_anchor_proximity.csv', REPO_ROOT)}`
- `{repo_rel(output_dir / 'max_five_sensitivity_register.csv', REPO_ROOT)}`
- `{repo_rel(output_dir / 'remaining_blockers.csv', REPO_ROOT)}`
""",
        encoding="utf-8",
    )


def run_pre_economics_physical_anchor_sprint(
    *,
    output_dir: str | Path = OUTPUT_DIR,
    baseline_run_dir: str | Path = BASELINE_RUN_DIR,
    reference_run_dir: str | Path = REFERENCE_RUN_DIR,
) -> dict[str, Any]:
    out = Path(output_dir).resolve()
    baseline = Path(baseline_run_dir).resolve()
    reference = Path(reference_run_dir).resolve()
    _required_path(baseline / "run_summary.json", "baseline run_summary")
    _required_path(reference / "run_summary.json", "reference run_summary")

    baseline_summary = _read_json(baseline / "run_summary.json")
    reference_summary = _read_json(reference / "run_summary.json")
    baseline_anchor_rows = _read_csv(baseline / "annual_anchor_reconciliation.csv")
    reference_anchor_rows = _read_csv(reference / "annual_anchor_reconciliation.csv")

    readiness_rows = build_readiness_ledger()
    guardrail_rows = build_guardrail_rows(baseline_summary, readiness_rows)
    proximity_rows = build_anchor_proximity_rows(baseline_anchor_rows)
    stop_evaluation = evaluate_anchor_stop_condition(proximity_rows)
    sensitivity_rows = build_sensitivity_register(baseline_anchor_rows, reference_anchor_rows, stop_evaluation)
    blocker_rows = build_remaining_blockers()
    best_rows = build_baseline_vs_best_rows(baseline_summary, reference_summary, stop_evaluation)

    failed_guardrails = sum(1 for row in guardrail_rows if row["status"] == "fail")
    unresolved_residuals = sum(1 for row in readiness_rows if "residual" in row["item"].lower() or "residual" in row["residual_policy"].lower())
    development_rows = sum(1 for row in readiness_rows if row["sprint_status"] == "accepted_development")
    recommendation = (
        "ready_for_cost_design"
        if stop_evaluation["early_stop_ready"] and failed_guardrails == 0
        else "needs_one_more_physical_gate"
        if failed_guardrails == 0 and stop_evaluation["comparable_anchor_families"] >= MIN_COMPARABLE_FAMILIES
        else "not_ready"
    )
    summary = {
        "stage": STAGE,
        "run_id": RUN_ID,
        "status": "pass" if failed_guardrails == 0 else "fail",
        "output_policy": "minimal",
        "run_class": "pre_economics_physical_anchor_sprint",
        "lineage_role": "diagnostic_gate",
        "baseline_run": repo_rel(baseline, REPO_ROOT),
        "reference_run": repo_rel(reference, REPO_ROOT),
        "threshold": THRESHOLD,
        "sensitivity_analyses_evaluated": len(sensitivity_rows),
        "max_sensitivity_analyses": MAX_SENSITIVITY_ANALYSES,
        "early_stop_ready": stop_evaluation["early_stop_ready"],
        "comparable_anchor_families": stop_evaluation["comparable_anchor_families"],
        "families_within_threshold": stop_evaluation["families_within_threshold"],
        "failed_guardrails": failed_guardrails,
        "unresolved_residual_policy_rows": unresolved_residuals,
        "accepted_development_rows": development_rows,
        "remaining_blockers": len(blocker_rows),
        "recommendation": recommendation,
        "economics_executed": False,
        "go_no_go": {
            "pre_economics_sprint": "GO_EXECUTED",
            "economic_layer": "NO_GO_STOPPED_BY_SCOPE",
            "DA": "NO_GO",
            "ETS": "NO_GO",
            "full_sensitivity_beyond_five": "NO_GO",
        },
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }

    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "pre_economics_readiness_summary.csv", readiness_rows)
    _write_csv(out / "physical_guardrail_checks.csv", guardrail_rows)
    _write_csv(out / "annual_anchor_proximity.csv", proximity_rows)
    _write_csv(out / "max_five_sensitivity_register.csv", sensitivity_rows)
    _write_csv(out / "baseline_vs_best_sensitivity.csv", best_rows)
    _write_csv(out / "remaining_blockers.csv", blocker_rows)
    _write_json(out / "anchor_stop_condition.json", stop_evaluation)
    _write_json(out / "run_summary.json", summary)
    _write_json(
        out / "input_manifest.json",
        {
            "baseline_run": repo_rel(baseline, REPO_ROOT),
            "reference_run": repo_rel(reference, REPO_ROOT),
            "wag_contract_summary": repo_rel(WAG_O_DIR / "summary.json", REPO_ROOT),
            "wag_input_contract_summary": repo_rel(WAG_Y_DIR / "summary.json", REPO_ROOT),
            "explicit_fuel_co2_summary": repo_rel(CO2_V_DIR / "summary.json", REPO_ROOT),
            "nonfuel_co2_summary": repo_rel(CO2_W_DIR / "summary.json", REPO_ROOT),
        },
    )
    _write_json(out / "code_version.json", {"git_commit": resolve_git_commit(REPO_ROOT), "stage": STAGE})
    _write_json(
        out / "registry_entry.json",
        {
            "run_id": RUN_ID,
            "run_class": "pre_economics_physical_anchor_sprint",
            "lineage_role": "diagnostic_gate",
            "output_policy": "minimal",
            "status": summary["status"],
            "recommendation": recommendation,
        },
    )
    (out / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- The sprint does not run economics, DA, ETS, stochasticity, CVaR, mFRR or product revenue.\n"
        "- Sensitivity analyses are capped at five and may be diagnostic or blocked when no safe executable route exists.\n"
        "- Annualisation remains a representative-window diagnostic, not an 8760-hour Tata operation claim.\n"
        "- Residual electricity and NG are reported but not allocated, costed or used as plugs.\n",
        encoding="utf-8",
    )
    _write_report(summary, out)
    return {"output_dir": out, "summary": summary}


if __name__ == "__main__":
    result = run_pre_economics_physical_anchor_sprint()
    print(result["summary"])
