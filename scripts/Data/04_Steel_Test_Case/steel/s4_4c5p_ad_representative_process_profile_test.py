"""Representative fixed-profile diagnostic for the staged C5 WAG controllers.

This stage does not create a new gas allocator.  It compares the existing
fixed 24-hour schedule with a narrow, source-coupled PEFA timing diagnostic:
the already accepted BOFG-to-Malerij and COG-to-Branderij daily demands are
redistributed across the corresponding carrier-generation hours from the same
fixed schedule.  Their daily totals remain unchanged.  Boiler demand remains
continuous because the repository has no accepted boiler timing profile.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .s4_4c_unified_physical_modelbuilder import run_s44c_unified_physical_regression
from .wag_development_controller_contract import load_development_controller_profile


STAGE = "S4.4c5p_ad_representative_process_profile_test"
OUTPUT_DIR = Path("data/03_Optimisation/inputs/assets/steel/S4/s4_4c5p_ad_representative_process_profile_test")
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_REPRESENTATIVE_PROCESS_PROFILE_TEST.md")
HORIZON_HOURS = 24
CONFIGURATIONS = ("C0_current_BF_BOF_reference", "C1_phase1_BF_BOF_plus_DRP_EAF")
PROFILE_COMPONENTS = {
    "pefa_bofg": ("BOFG_generated_mwh", "BOFG", "Malerij"),
    "pefa_cog": ("COG_generated_mwh", "COG", "Branderij"),
}

RESULT_COLUMNS = [
    "configuration",
    "baseline_pefa_ng_mwh",
    "source_coupled_pefa_ng_mwh",
    "pefa_ng_change_mwh",
    "baseline_boiler_ng_mwh",
    "source_coupled_boiler_ng_mwh",
    "baseline_hsm_ng_mwh",
    "source_coupled_hsm_ng_mwh",
    "baseline_wag_flared_mwh",
    "source_coupled_wag_flared_mwh",
    "baseline_generator_fuel_mwh",
    "source_coupled_generator_fuel_mwh",
    "baseline_wag_explicit_co2_t",
    "source_coupled_wag_explicit_co2_t",
    "max_abs_carrier_balance_residual_mwh",
    "interpretation",
]
WEIGHT_COLUMNS = [
    "configuration",
    "controller_component",
    "source_carrier",
    "sink",
    "hour_index",
    "source_generation_mwh",
    "timing_weight",
    "fixed_daily_component_demand_mwh",
    "weighted_component_demand_mwh",
]
GATE_COLUMNS = ["configuration", "check_id", "status", "evidence", "caveat"]


def _write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _as_float(value: Any) -> float:
    return float(value or 0.0)


def _audit_by_configuration(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["configuration_id"]): row for row in report["configuration_build_audit"]}


def _hourly_by_configuration(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {configuration: [] for configuration in CONFIGURATIONS}
    for row in report["hourly_rows"]:
        configuration = str(row.get("configuration_id", ""))
        if configuration in grouped:
            grouped[configuration].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["hour_index"]))
    return grouped


def _normalised_generation_weights(rows: list[dict[str, Any]], field: str) -> dict[int, float]:
    if len(rows) != HORIZON_HOURS:
        raise ValueError(f"Representative profile requires {HORIZON_HOURS} rows, found {len(rows)}.")
    by_hour = {int(row["hour_index"]): _as_float(row.get(field)) for row in rows}
    total = sum(by_hour.values())
    if total <= 0.0:
        raise ValueError(f"Cannot create source-coupled timing profile: {field} has no generation.")
    return {hour: HORIZON_HOURS * value / total for hour, value in by_hour.items()}


def _build_weights_and_rows(
    configuration: str,
    hourly_rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[int, float]], list[dict[str, str]]]:
    profile = load_development_controller_profile(configuration)
    component_demands = {
        "pefa_bofg": profile.pefa_bofg_mwh_h,
        "pefa_cog": profile.pefa_cog_mwh_h,
    }
    weights: dict[str, dict[int, float]] = {}
    output_rows: list[dict[str, str]] = []
    for component, (generation_field, carrier, sink) in PROFILE_COMPONENTS.items():
        component_weights = _normalised_generation_weights(hourly_rows, generation_field)
        weights[component] = component_weights
        daily_demand = component_demands[component] * HORIZON_HOURS
        for row in hourly_rows:
            hour = int(row["hour_index"])
            output_rows.append(
                {
                    "configuration": configuration,
                    "controller_component": component,
                    "source_carrier": carrier,
                    "sink": sink,
                    "hour_index": str(hour),
                    "source_generation_mwh": str(_as_float(row.get(generation_field))),
                    "timing_weight": str(component_weights[hour]),
                    "fixed_daily_component_demand_mwh": str(daily_demand),
                    "weighted_component_demand_mwh": str(component_demands[component] * component_weights[hour]),
                }
            )
    return weights, output_rows


def _fixed_schedule_run(
    *,
    profile_weights_by_configuration: dict[str, dict[str, dict[int, float]]] | None = None,
) -> dict[str, Any]:
    return run_s44c_unified_physical_regression(
        run_id=STAGE,
        write_report=False,
        horizon_hours_override=HORIZON_HOURS,
        fix_c0_binary_schedule=True,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        fix_c1_hybrid_schedule=True,
        c1_retained_route_policy="bottom_up_fixed_retained_route",
        development_controller_activation="full",
        development_controller_profile_weights_by_configuration=profile_weights_by_configuration,
        solver_time_limit_seconds=25,
    )


def _comparison_row(baseline: dict[str, Any], coupled: dict[str, Any]) -> dict[str, str]:
    pefa_change = _as_float(coupled.get("PEFA_NG_mwh")) - _as_float(baseline.get("PEFA_NG_mwh"))
    return {
        "configuration": str(baseline["configuration_id"]),
        "baseline_pefa_ng_mwh": str(baseline.get("PEFA_NG_mwh", "")),
        "source_coupled_pefa_ng_mwh": str(coupled.get("PEFA_NG_mwh", "")),
        "pefa_ng_change_mwh": str(pefa_change),
        "baseline_boiler_ng_mwh": str(baseline.get("natural_gas_boiler_mwh", "")),
        "source_coupled_boiler_ng_mwh": str(coupled.get("natural_gas_boiler_mwh", "")),
        "baseline_hsm_ng_mwh": str(baseline.get("HSM_NG_mwh", "")),
        "source_coupled_hsm_ng_mwh": str(coupled.get("HSM_NG_mwh", "")),
        "baseline_wag_flared_mwh": str(baseline.get("WAG_flared", "")),
        "source_coupled_wag_flared_mwh": str(coupled.get("WAG_flared", "")),
        "baseline_generator_fuel_mwh": str(baseline.get("vattenfall_fuel_mwh", "")),
        "source_coupled_generator_fuel_mwh": str(coupled.get("vattenfall_fuel_mwh", "")),
        "baseline_wag_explicit_co2_t": str(baseline.get("WAG_explicit_combustion_co2_t", "")),
        "source_coupled_wag_explicit_co2_t": str(coupled.get("WAG_explicit_combustion_co2_t", "")),
        "max_abs_carrier_balance_residual_mwh": str(coupled.get("max_abs_wag_balance_residual_mwh", "")),
        "interpretation": (
            "Source-coupled PEFA timing diagnostic only; daily accepted PEFA component demand is preserved. "
            "No boiler timing profile, gas mix, WAG/NG ratio, residual allocation or annual-anchor claim is introduced."
        ),
    }


def run_s4_4c5p_ad_representative_process_profile_test() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    baseline_report = _fixed_schedule_run()
    baseline_audits = _audit_by_configuration(baseline_report)
    baseline_hourly = _hourly_by_configuration(baseline_report)

    timing_rows: list[dict[str, str]] = []
    profile_weights_by_configuration: dict[str, dict[str, dict[int, float]]] = {}
    gate_rows: list[dict[str, str]] = []
    for configuration in CONFIGURATIONS:
        weights, rows = _build_weights_and_rows(configuration, baseline_hourly[configuration])
        timing_rows.extend(rows)
        profile_weights_by_configuration[configuration] = weights

    coupled_report = _fixed_schedule_run(profile_weights_by_configuration=profile_weights_by_configuration)
    coupled_audits = _audit_by_configuration(coupled_report)
    for configuration in CONFIGURATIONS:
        weights = profile_weights_by_configuration[configuration]
        coupled_audit = coupled_audits[configuration]

        weights_normalised = all(
            abs(sum(weights[component].values()) - HORIZON_HOURS) <= 1e-8
            for component in PROFILE_COMPONENTS
        )
        solved = (
            coupled_audit.get("build_status") == "solved"
            and str(coupled_audit.get("termination_condition", "")).lower() in {"optimal", "feasible"}
        )
        balance = _as_float(coupled_audit.get("max_abs_wag_balance_residual_mwh"))
        gate_rows.extend(
            [
                {
                    "configuration": configuration,
                    "check_id": "fixed_schedule_only",
                    "status": "pass",
                    "evidence": "C0 fixed binary schedule; C1 bottom_up_fixed_retained_route.",
                    "caveat": "No free C0 binary planning or economic dispatch is used.",
                },
                {
                    "configuration": configuration,
                    "check_id": "daily_pefa_component_totals_preserved",
                    "status": "pass" if weights_normalised else "fail",
                    "evidence": "Both timing-weight sums equal 24 hours.",
                    "caveat": "The test changes only timing, not the accepted daily BOFG/COG PEFA component totals.",
                },
                {
                    "configuration": configuration,
                    "check_id": "physical_solution",
                    "status": "pass" if solved else "fail",
                    "evidence": f"{coupled_audit.get('build_status')} / {coupled_audit.get('termination_condition')}",
                    "caveat": "Only accepted feasible or optimal solutions may be compared.",
                },
                {
                    "configuration": configuration,
                    "check_id": "carrier_balance",
                    "status": "pass" if balance <= 1e-6 else "fail",
                    "evidence": str(balance),
                    "caveat": "BFG, COG and BOFG remain separate balances.",
                },
                {
                    "configuration": configuration,
                    "check_id": "boiler_profile_not_invented",
                    "status": "pass",
                    "evidence": "Boiler demand retains the accepted continuous C5p_b profile.",
                    "caveat": "No source-backed boiler operating-time profile exists in this stage.",
                },
            ]
        )

    comparison_rows = [_comparison_row(baseline_audits[configuration], coupled_audits[configuration]) for configuration in CONFIGURATIONS]
    failure_count = sum(row["status"] == "fail" for row in gate_rows)
    summary = {
        "stage": STAGE,
        "status": "pass" if failure_count == 0 else "fail",
        "horizon_hours": HORIZON_HOURS,
        "profile_cases": ["baseline_fixed_continuous", "source_coupled_pefa_timing_diagnostic"],
        "free_c0_binary_planning_used": False,
        "pefa_timing_policy": "Existing accepted PEFA BOFG/COG daily components are redistributed by same-schedule source generation only.",
        "boiler_timing_policy": "continuous_accepted_profile_unchanged",
        "annual_anchor_test": "NOT_RUN",
        "failure_count": failure_count,
        "go_no_go": {
            "representative_timing_diagnostic": "GO" if failure_count == 0 else "NO_GO",
            "annual_anchor_interpretation": "NO_GO",
            "boiler_time_profile_activation": "NO_GO_SOURCE_GAP",
            "NG_residual_allocation": "NO_GO",
            "economics_or_DA": "NO_GO",
        },
        "caveat": "This is a bounded timing diagnostic, not an annual representative operation profile or an anchor-calibration run.",
    }

    _write_csv(OUTPUT_DIR / "profile_hour_weights.csv", timing_rows, WEIGHT_COLUMNS)
    _write_csv(OUTPUT_DIR / "profile_comparison.csv", comparison_rows, RESULT_COLUMNS)
    _write_csv(OUTPUT_DIR / "profile_gate_checks.csv", gate_rows, GATE_COLUMNS)
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        """# C5 Representative Process-Profile Test

## Purpose

This diagnostic separates a fixed-schedule timing effect from a structural fuel
shortage. It compares the current 24-hour development run with a narrow
source-coupled PEFA timing profile. No free C0 binary planning, economic
dispatch, annual scaling or anchor calibration is used.

## What changes

- The accepted BOFG-to-PEFA Malerij daily demand is redistributed over the
  BOFG-generation hours from the same fixed schedule.
- The accepted COG-to-PEFA Branderij daily demand is redistributed over the
  COG-generation hours from the same fixed schedule.
- Each component's daily energy total is preserved exactly.

## What does not change

- Carrier-specific BFG/COG/BOFG balances and existing controller eligibility.
- HSM's throughput-linked demand.
- Boiler demand: it stays on its accepted continuous C5p_b profile because no
  source-backed boiler operating-time profile has been selected.
- WAG/NG ratios, mixed-gas/Wobbe logic, residual NG/electricity allocation,
  CO2 policy, model objective, economics and DA behaviour.

## Interpretation

If PEFA named-NG decreases in the source-coupled case, that demonstrates that
part of the fixed 24-hour NG result is a timing artefact. It does not prove
that the source-coupled schedule is Tata's real operating pattern. Boiler NG
remains a separate timing/source-contract question.

This stage is not an annual anchor test. The 24-hour final-product target is a
development smoke target, so annualising these rows would be misleading.
""",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    run_s4_4c5p_ad_representative_process_profile_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
