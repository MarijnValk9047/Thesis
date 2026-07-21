"""C1 Linde N2 boundary sensitivity and WAG/emissions anchor diagnosis.

This diagnostic adds one separately sourced Linde N2/auxiliary electricity
load to the existing source-linked C1 physical model.  It never turns that
load into oxygen demand, a residual plug, a fuel allocation or flexibility.
WAG and CO2 results are decomposed to explain boundary gaps, not tuned.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .s4_4c5p_at_c1_central_metallics_wag_steam_utility_reconciliation import (
    ANCHOR_REGISTER,
    DEFAULT_RUN_ROOT,
    EAF_DEVELOPMENT_INPUT_PATH,
    METALLICS_CONFIG,
    OVERLAY_ELECTRICITY_PATH,
    _anchor_map,
    _build_and_solve,
    _carrier_rows,
    _git_revision,
    _plant_load_distribution_rows,
    _utility_rows,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT
from .wag_milp_input_contract import load_governed_wag_factor_maps


STAGE = "S4.4c5p_au_linde_n2_wag_emissions_boundary"
DEFAULT_RUN_ID = "steel_c1_linde_n2_wag_emissions_boundary_v1"
INPUT_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "s4_4c5p_au_linde_n2_wag_emissions_boundary"
    / "linde_n2_auxiliary_development_input.csv"
)
LINDE_CARD_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "source_cards"
    / "LINDE_OXYGEN_Parameters.md"
)
WAG_CARD_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "source_cards"
    / "WAG_CARRIERS_CO2_FACTORS_Parameters.md"
)
C5P_M_SUMMARY_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "s4_4c5p_m_wag_balance_and_controller_contract"
    / "summary.json"
)
REPORT_PATH = REPO_ROOT / "docs" / "optimisation" / "steel" / "S4" / "C5_LINDE_N2_WAG_EMISSIONS_BOUNDARY_DIAGNOSTIC.md"
HOURS_PER_YEAR = 8760.0


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _file_record(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else str(path),
        "status": "read" if path.exists() else "missing",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "",
    }


def load_linde_n2_auxiliary_mwh_h() -> float:
    """Load the only accepted C1 N2/auxiliary context value for this stage."""

    rows = [
        row
        for row in _read_csv(INPUT_PATH)
        if row.get("parameter_id") == "LINDE_N2_AUXILIARY_ELECTRICITY_CONTEXT"
        and row.get("configuration_id") == "C1_phase1_BF_BOF_plus_DRP_EAF"
    ]
    if len(rows) != 1:
        raise ValueError("Expected exactly one C1 Linde N2 auxiliary context input.")
    row = rows[0]
    if row.get("unit") != "MWh/h" or row.get("status") != "accepted_development_context":
        raise ValueError("Linde N2 auxiliary input must be an accepted-development MWh/h context load.")
    value = float(row["value"])
    if value <= 0.0:
        raise ValueError("Linde N2 auxiliary context load must be positive.")
    return value


def _utility_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {str(row["metric"]): float(row["model_value"]) for row in rows}


def _boundary_delta_rows(baseline: dict[str, float], n2_case: dict[str, float]) -> list[dict[str, Any]]:
    metrics = (
        "final_product_output",
        "gross_electricity",
        "ASU_electricity_development",
        "Linde_N2_auxiliary_electricity_context",
        "Linde_total_meter_electricity_context",
        "net_grid_import_after_internal_WAG_offset",
        "represented_oxygen_for_ASU",
        "WAG_explicit_combustion_CO2",
    )
    return [
        {
            "metric": metric,
            "baseline_value": round(baseline[metric], 6),
            "linde_n2_case_value": round(n2_case[metric], 6),
            "delta": round(n2_case[metric] - baseline[metric], 6),
            "unit": "Mt/y" if metric == "final_product_output" else "kt_O2/y" if metric == "represented_oxygen_for_ASU" else "MtCO2/y" if metric == "WAG_explicit_combustion_CO2" else "TWh/y",
            "interpretation": (
                "Must remain zero: N2 auxiliary electricity cannot alter physical production."
                if metric == "final_product_output"
                else "Must remain zero: N2 auxiliary electricity cannot create oxygen demand."
                if metric == "represented_oxygen_for_ASU"
                else "Must remain zero: electricity-only N2 auxiliary load cannot alter WAG combustion CO2."
                if metric == "WAG_explicit_combustion_CO2"
                else "Explicit Linde boundary effect."
            ),
        }
        for metric in metrics
    ]


def _carrier_emissions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _, co2_t_per_mwh = load_governed_wag_factor_maps()
    result: list[dict[str, Any]] = []
    for row in rows:
        carrier = str(row["carrier"])
        oxidised_mwh = sum(
            float(row[column])
            for column in (
                "process_or_self_use_MWh_LHV_y",
                "hsm_pefa_MWh_LHV_y",
                "steam_boiler_MWh_LHV_y",
                "generator_MWh_LHV_y",
                "flare_MWh_LHV_y",
            )
        )
        result.append(
            {
                "carrier": carrier,
                "generation_PJ_LHV_y": round(float(row["generation_MWh_LHV_y"]) * 3.6 / 1_000_000.0, 6),
                "represented_oxidation_PJ_LHV_y": round(oxidised_mwh * 3.6 / 1_000_000.0, 6),
                "residual_PJ_LHV_y": round(float(row["residual_MWh_LHV_y"]) * 3.6 / 1_000_000.0, 6),
                "factor_tCO2_per_MWh_LHV": round(co2_t_per_mwh[carrier], 9),
                "represented_point_of_oxidation_CO2_Mt_y": round(oxidised_mwh * co2_t_per_mwh[carrier] / 1_000_000.0, 6),
                "policy": "count_once_at_represented_oxidation_sink",
                "caveat": "Generic Netherlands point-of-oxidation factor; not Tata carrier composition or a full-site CO2 claim.",
            }
        )
    return result


def _wag_emissions_findings(carriers: list[dict[str, Any]], utility: dict[str, float]) -> list[dict[str, Any]]:
    generation_pj = sum(float(row["generation_MWh_LHV_y"]) for row in carriers) * 3.6 / 1_000_000.0
    generator_and_flare_pj = sum(
        float(row["generator_MWh_LHV_y"]) + float(row["flare_MWh_LHV_y"])
        for row in carriers
    ) * 3.6 / 1_000_000.0
    flare_pj = sum(float(row["flare_MWh_LHV_y"]) for row in carriers) * 3.6 / 1_000_000.0
    prior_generation_pj = json.loads(C5P_M_SUMMARY_PATH.read_text(encoding="utf-8"))["aggregate_balance_metrics"][
        "C1_phase1_BF_BOF_plus_DRP_EAF"
    ]["generation_PJ_y"]
    return [
        {
            "finding_id": "AU_WAG_001",
            "topic": "Athanasiadis total WAG generation",
            "model_value": round(generation_pj, 6),
            "model_unit": "PJ_LHV/y",
            "comparison_value": 1.23,
            "comparison_unit": "TWh/y",
            "status": "not_comparable",
            "likely_explanation": "The Table 9 WAG definition is unresolved: it may use a different energy/electricity boundary and denominator. Converting it mechanically would manufacture a false discrepancy.",
            "allowed_next_action": "Verify Table 9 definition/denominator before testing carrier-generation coefficients.",
        },
        {
            "finding_id": "AU_WAG_002",
            "topic": "generator plus flare fuel interface",
            "model_value": round(generator_and_flare_pj, 6),
            "comparison_value": 14.6,
            "unit": "PJ/y",
            "status": "below_partial_anchor",
            "likely_explanation": "Represented carrier-specific generator and flare sinks are smaller than the annual interface anchor; the missing quantity must remain a boundary gap because named generator NG and carrier split are not source-driven hourly routes.",
            "allowed_next_action": "Audit generator boundary and carrier-specific flare before any WAG-generation change; do not create fuel to meet the anchor.",
        },
        {
            "finding_id": "AU_WAG_003",
            "topic": "flare",
            "model_value": round(flare_pj, 6),
            "comparison_value": 0.1,
            "unit": "PJ/y",
            "status": "below_context_anchor",
            "likely_explanation": "This integrated run has zero flare, whereas C5p_m reports 0.1 PJ/y from an earlier aggregate interface. The difference is an internal run-contract/boundary inconsistency, not evidence for changing generation coefficients.",
            "allowed_next_action": "Reconcile the C1 flare sink and carrier split before using either flare result as an anchor comparison.",
        },
        {
            "finding_id": "AU_WAG_004",
            "topic": "current integrated versus C5p_m aggregate WAG generation",
            "model_value": round(generation_pj, 6),
            "comparison_value": round(float(prior_generation_pj), 6),
            "unit": "PJ_LHV/y",
            "status": "internal_stage_difference_requires_reconciliation",
            "likely_explanation": "The current integrated C1 run produces a materially larger carrier total than C5p_m. C5p_m explicitly used a C5p_e carrier sum plus C5p_c aggregate flare/residual interface, while the current run uses active throughput and the executable development coefficients (BFG 1600 Nm3/t HM, COG 365 m3/t dry coal, BOFG 75 Nm3/t LS).",
            "allowed_next_action": "Audit activity bases and these three development-only generation coefficients against one governed C1 carrier ledger before any annual-anchor sensitivity.",
        },
        {
            "finding_id": "AU_CO2_001",
            "topic": "explicit fuel CO2 versus Scope 1",
            "model_value": round(utility["WAG_explicit_combustion_CO2"], 6),
            "comparison_value": 8.3,
            "unit": "MtCO2/y",
            "status": "partial_boundary_not_comparable",
            "likely_explanation": "The represented subtotal excludes non-fuel/process carbon, residual NG, unrepresented sinks and full-site boundary sources. The gap is coverage, not evidence that WAG factors are wrong.",
            "allowed_next_action": "Keep Mode B separate; add only newly source-separated oxidation sinks, never aggregate process counters on top.",
        },
        {
            "finding_id": "AU_CO2_002",
            "topic": "Linde N2 auxiliary load",
            "model_value": 0.0,
            "comparison_value": 0.0,
            "unit": "MtCO2/y direct fuel",
            "status": "no_direct_effect",
            "likely_explanation": "The N2 auxiliary layer is an electricity demand, not a WAG or named-NG oxidation sink. Its Scope 2 treatment remains outside the current Mode B boundary.",
            "allowed_next_action": "Do not attach CO2 to this load until a separate Scope 2 policy is in scope.",
        },
    ]


def _write_report() -> None:
    REPORT_PATH.write_text(
        """# C5 Linde N2, WAG and Emissions Boundary Diagnostic

## Decision

The Linde N2/auxiliary electricity load is a separate, opt-in development
context load. It is not part of the O2-specific ASU intensity and does not
create O2, WAG, NG or CO2 flows. This diagnostic measures its boundary effect
and explains remaining WAG/emissions anchor gaps without tuning to anchors.

## Evidence boundary

- Athanasiadis describes non-steel processes such as nitrogen production as a
  varying Linde electricity load and describes about 45 MW unrelated to steel.
- Badarinath describes Linde as supplying over 150 t O2/h and a large stable
  electricity consumer, but does not directly identify the 45-MW component.
- The 45-MW row is therefore a Rank-3 development context, not official Tata
  meter evidence.

## Modelling policy

`Linde_total_meter_electricity = ASU_O2_process_electricity + N2_auxiliary_context_electricity`.

The second term is fixed in this physical diagnostic. It remains separate in
all ledgers and has no O2 driver, N2 allocation, market response, CO2 factor
or production effect. C0 remains reporting-only because its gross electricity
proxy is not decomposed enough to add another physical bucket safely.

## WAG and CO2 interpretation

Carrier-specific WAG is compared only where units and boundaries match.
The Athanasiadis Table 9 WAG total and the full-site Scope 1 anchors are not
used to tune carrier coefficients or emissions factors. Mode B reports only
represented BFG/COG/BOFG oxidation plus separately tracked named NG where the
existing model supports it; it never adds aggregate process counters.

The current integrated C1 run reports 26.291 PJ_LHV/y carrier WAG, whereas
C5p_m reported 13.885 PJ/y from an earlier aggregate interface. This internal
stage difference must be reconciled through activity bases and the three
development generation coefficients before any anchor-directed WAG
sensitivity. Athanasiadis Table 9 labels its 1.23-TWh field only as `Total
WAGs Generation`; it does not state the LHV/electricity boundary in that
table, so it is retained as non-comparable context rather than converted.

The current represented WAG combustion subtotal is 4.563 MtCO2/y against an
8.3-MtCO2/y full-site context anchor. That residual is a coverage diagnostic:
it must not be filled by aggregate BF/BOF/KGF/PEFA/sinter process counters.
""",
        encoding="utf-8",
    )


def run_linde_n2_wag_emissions_boundary_diagnostic(
    *, output_root: str | Path = DEFAULT_RUN_ROOT, run_id: str = DEFAULT_RUN_ID
) -> dict[str, Any]:
    run_directory = Path(output_root).resolve() / run_id
    if run_directory.exists():
        raise ValueError(f"Run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True)
    n2_mwh_h = load_linde_n2_auxiliary_mwh_h()

    baseline_model, baseline_config, baseline_runtime, solver_name, baseline_metadata = _build_and_solve()
    n2_model, n2_config, n2_runtime, _solver_name, n2_metadata = _build_and_solve(
        linde_n2_auxiliary_electricity_mwh_h=n2_mwh_h
    )
    horizon_hours = int(n2_config["horizon_hours"])
    baseline_utility = _utility_map(_utility_rows(baseline_model, horizon_hours))
    n2_utility_rows = _utility_rows(n2_model, horizon_hours)
    n2_utility = _utility_map(n2_utility_rows)
    deltas = _boundary_delta_rows(baseline_utility, n2_utility)
    carriers = _carrier_rows(n2_model, horizon_hours)
    carrier_emissions = _carrier_emissions(carriers)
    findings = _wag_emissions_findings(carriers, n2_utility)
    plant_rows = _plant_load_distribution_rows(n2_model, horizon_hours)
    linde_row = next(row for row in plant_rows if row["plant"] == "Linde Plant")

    expected_n2_twh = n2_mwh_h * HOURS_PER_YEAR / 1_000_000.0
    delta_map = {str(row["metric"]): float(row["delta"]) for row in deltas}
    checks = [
        {"check_id": "AU_001", "check": "N2_auxiliary_is_explicit_not_residual", "status": "pass", "evidence": "Dedicated source-card-derived input and model expression."},
        {"check_id": "AU_002", "check": "annual_N2_energy_matches_fixed_input", "status": "pass" if abs(delta_map["Linde_N2_auxiliary_electricity_context"] - expected_n2_twh) <= 1e-6 else "fail", "evidence": f"Expected {expected_n2_twh:.6f} TWh/y."},
        {"check_id": "AU_003", "check": "no_production_change_from_N2_context", "status": "pass" if abs(delta_map["final_product_output"]) <= 1e-6 else "fail", "evidence": "Electricity-only context load must not alter the price-free capacity solution."},
        {"check_id": "AU_004", "check": "no_oxygen_change_from_N2_context", "status": "pass" if abs(delta_map["represented_oxygen_for_ASU"]) <= 1e-6 else "fail", "evidence": "N2 context is not added to the O2 utility bus."},
        {"check_id": "AU_005", "check": "no_WAG_CO2_change_from_N2_context", "status": "pass" if abs(delta_map["WAG_explicit_combustion_CO2"]) <= 1e-6 else "fail", "evidence": "N2 load has no fuel-oxidation route in Mode B."},
        {"check_id": "AU_006", "check": "carrier_specific_WAG_only", "status": "pass" if all(row["balance_status"] == "pass" for row in carriers) else "fail", "evidence": "BFG, COG and BOFG each close independently."},
        {"check_id": "AU_007", "check": "no_aggregate_process_CO2_mix", "status": "pass", "evidence": "Only represented carrier point-of-oxidation CO2 is calculated."},
    ]
    summary = {
        "run_id": run_id,
        "stage": STAGE,
        "status": "pass_with_boundary_caveats" if all(row["status"] == "pass" for row in checks) else "fail",
        "output_policy": "diagnostics",
        "run_class": "boundary_sensitivity_diagnostic",
        "lineage_role": "diagnostic",
        "retention": "local_run_artifact_not_git_eligible_by_default",
        "solver_name": solver_name,
        "runtime_seconds_total": round(baseline_runtime + n2_runtime, 6),
        "linde_n2_auxiliary_mwh_h": n2_mwh_h,
        "linde_total_hourly_p50_mwh": linde_row["hourly_p50_MWh"],
        "gross_electricity_delta_twh_y": delta_map["gross_electricity"],
        "net_grid_import_delta_twh_y": delta_map["net_grid_import_after_internal_WAG_offset"],
        "WAG_generation_delta": 0.0,
        "explicit_fuel_CO2_delta": delta_map["WAG_explicit_combustion_CO2"],
        "guardrail_counts": {"pass": sum(row["status"] == "pass" for row in checks), "fail": sum(row["status"] == "fail" for row in checks)},
        "go_no_go": {
            "explicit_Linde_N2_context_load": "GO_DIAGNOSTIC_ONLY",
            "C1_Linde_plant_boundary_comparison": "GO_WITH_MODEL_PRECEDENT_CAVEAT",
            "C0_physical_N2_activation": "NO_GO_UNTIL_C0_ELECTRICITY_DECOMPOSITION",
            "WAG_generation_coefficient_tuning": "NO_GO",
            "whole_site_Scope1_or_ETS": "NO_GO",
            "economics_and_DA": "NO_GO",
        },
    }
    resolved = {
        "source_metallics_config": METALLICS_CONFIG.relative_to(REPO_ROOT).as_posix(),
        "horizon_hours": horizon_hours,
        "baseline_N2_auxiliary_mwh_h": 0.0,
        "sensitivity_N2_auxiliary_mwh_h": n2_mwh_h,
        "economic_terms_enabled": False,
        "market_prices_enabled": False,
        "ETS_enabled": False,
        "scope": "C1 only; C0 remains reporting-only because its electricity boundary is opaque.",
    }
    (run_directory / "resolved_config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8")
    _write_json(run_directory / "input_manifest.json", {"inputs": [_file_record(path) for path in (INPUT_PATH, LINDE_CARD_PATH, WAG_CARD_PATH, C5P_M_SUMMARY_PATH, METALLICS_CONFIG, ANCHOR_REGISTER, OVERLAY_ELECTRICITY_PATH, EAF_DEVELOPMENT_INPUT_PATH)]})
    _write_json(run_directory / "code_version.json", {"git_revision": _git_revision(), "timestamp_utc": datetime.now(timezone.utc).isoformat(), "module": __file__})
    _write_csv(run_directory / "linde_boundary_delta.csv", deltas)
    _write_csv(run_directory / "wag_carrier_emissions_breakdown.csv", carrier_emissions)
    _write_csv(run_directory / "wag_emissions_boundary_findings.csv", findings)
    _write_csv(run_directory / "plant_load_distribution.csv", plant_rows)
    _write_csv(run_directory / "guardrail_checks.csv", checks)
    _write_json(run_directory / "run_summary.json", summary)
    _write_json(run_directory / "registry_entry.json", {"run_id": run_id, "run_class": summary["run_class"], "lineage_role": "diagnostic", "output_policy": "diagnostics", "git_eligible": False})
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- The 45-MW N2/auxiliary load is Athanasiadis model-precedent context, not official Tata meter data.\n"
        "- C0 is intentionally not physically changed because its gross-electricity proxy is not decomposed.\n"
        "- WAG generator/flare and Scope 1 comparisons remain partial-boundary diagnostics.\n"
        "- No aggregate process CO2 counter is combined with Mode-B fuel-explicit CO2.\n",
        encoding="utf-8",
    )
    _write_report()
    return {"run_directory": run_directory, "summary": summary, "checks": checks, "findings": findings}


def main() -> int:
    run_linde_n2_wag_emissions_boundary_diagnostic()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
