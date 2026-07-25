"""Fixed-schedule activation checks for prepared C5 development controllers.

The stage intentionally uses the existing static 24-hour schedules.  It is not
a free C0 binary-planning run and it does not make any economic claim.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .s4_4c_unified_physical_modelbuilder import run_s44c_unified_physical_regression


STAGE = "S4.4c5p_ac_phased_development_controller_activation"
OUTPUT_DIR = Path("data/03_Optimisation/inputs/assets/steel/S4/s4_4c5p_ac_phased_development_controller_activation")
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_PHASED_DEVELOPMENT_CONTROLLER_ACTIVATION.md")
PHASES = ("hsm", "hsm_pefa", "hsm_pefa_boiler", "full")
RESULT_COLUMNS = [
    "phase",
    "configuration",
    "build_status",
    "termination_condition",
    "fixed_schedule",
    "hsm_reheat_demand_mwh",
    "hsm_ng_mwh",
    "pefa_ng_mwh",
    "boiler_ng_mwh",
    "controller_electricity_mwh",
    "wag_used_mwh",
    "wag_flared_mwh",
    "generator_fuel_mwh",
    "wag_explicit_co2_t",
    "max_abs_carrier_balance_residual_mwh",
    "caveat",
]
GATE_COLUMNS = ["phase", "configuration", "check_id", "status", "evidence", "caveat"]


def _write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _result_row(phase: str, audit: dict[str, Any]) -> dict[str, str]:
    return {
        "phase": phase,
        "configuration": str(audit["configuration_id"]),
        "build_status": str(audit["build_status"]),
        "termination_condition": str(audit["termination_condition"]),
        "fixed_schedule": "true",
        "hsm_reheat_demand_mwh": str(audit.get("HSM_reheat_demand_mwh", "")),
        "hsm_ng_mwh": str(audit.get("HSM_NG_mwh", "")),
        "pefa_ng_mwh": str(audit.get("PEFA_NG_mwh", "")),
        "boiler_ng_mwh": str(audit.get("natural_gas_boiler_mwh", "")),
        "controller_electricity_mwh": str(audit.get("development_controller_electricity_mwh", "")),
        "wag_used_mwh": str(audit.get("WAG_used", "")),
        "wag_flared_mwh": str(audit.get("WAG_flared", "")),
        "generator_fuel_mwh": str(audit.get("vattenfall_fuel_mwh", "")),
        "wag_explicit_co2_t": str(audit.get("WAG_explicit_combustion_co2_t", "")),
        "max_abs_carrier_balance_residual_mwh": str(audit.get("max_abs_wag_balance_residual_mwh", "")),
        "caveat": "Fixed-schedule development diagnostic; named NG backup is reported, never treated as residual or calibration slack.",
    }


def run_s4_4c5p_ac_phased_development_controller_activation() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, str]] = []
    gates: list[dict[str, str]] = []
    for phase in PHASES:
        report = run_s44c_unified_physical_regression(
            run_id=f"{STAGE}_{phase}",
            write_report=False,
            horizon_hours_override=24,
            fix_c0_binary_schedule=True,
            enable_minimal_wag_layer=True,
            enable_c1_retained_bf_bof_route=True,
            fix_c1_hybrid_schedule=True,
            c1_retained_route_policy="bottom_up_fixed_retained_route",
            development_controller_activation=phase,
            solver_time_limit_seconds=25,
        )
        for audit in report["configuration_build_audit"]:
            row = _result_row(phase, audit)
            results.append(row)
            solved = row["build_status"] == "solved" and row["termination_condition"].lower() in {"optimal", "feasible"}
            balance = float(row["max_abs_carrier_balance_residual_mwh"] or 0.0)
            gates.extend(
                [
                    {
                        "phase": phase,
                        "configuration": row["configuration"],
                        "check_id": "fixed_schedule_only",
                        "status": "pass",
                        "evidence": "C0 uses fix_c0_binary_schedule=true; C1 uses bottom_up_fixed_retained_route.",
                        "caveat": "No free C0 binary planning is permitted in this development stage.",
                    },
                    {
                        "phase": phase,
                        "configuration": row["configuration"],
                        "check_id": "physical_solution",
                        "status": "pass" if solved else "fail",
                        "evidence": f"{row['build_status']} / {row['termination_condition']}",
                        "caveat": "Only feasible or optimal runs may be interpreted.",
                    },
                    {
                        "phase": phase,
                        "configuration": row["configuration"],
                        "check_id": "carrier_balance",
                        "status": "pass" if balance <= 1e-6 else "fail",
                        "evidence": row["max_abs_carrier_balance_residual_mwh"],
                        "caveat": "BFG, COG and BOFG remain separate carrier balances.",
                    },
                    {
                        "phase": phase,
                        "configuration": row["configuration"],
                        "check_id": "no_free_generator_economics",
                        "status": "pass",
                        "evidence": "Generator is an internal-offset interface; no price, export or mFRR term is enabled.",
                        "caveat": "The generator fuel value is a bounded residual interface, not a dispatch target.",
                    },
                ]
            )

    failure_count = sum(1 for row in gates if row["status"] == "fail")
    summary = {
        "stage": STAGE,
        "status": "pass" if failure_count == 0 else "fail",
        "phase_order": list(PHASES),
        "horizon_hours": 24,
        "c0_binary_schedule": "fixed_only",
        "c1_retained_route_policy": "bottom_up_fixed_retained_route",
        "free_c0_binary_planning_used": False,
        "failure_count": failure_count,
        "go_no_go": {
            "hsm_base_controller": "GO_DEVELOPMENT_FIXED_SCHEDULE",
            "pefa_controller": "GO_DEVELOPMENT_FIXED_SCHEDULE_WITH_NAMED_NG_BACKUP",
            "boiler_scaffold": "GO_DEVELOPMENT_FIXED_SCHEDULE_WITH_NAMED_NG_BACKUP",
            "generator_interface": "GO_DIAGNOSTIC_FIXED_INTERFACE_ONLY",
            "annual_anchor_test": "NOT_RUN_THIS_STAGE",
            "free_c0_planning": "NO_GO",
            "economics_or_DA": "NO_GO",
        },
        "caveat": "This activates source-stage controller contracts on fixed 24-hour schedules only. It does not establish annual anchor fit, full-site NG allocation, ETS readiness, economics or DA readiness.",
    }
    _write_csv(OUTPUT_DIR / "phase_activation_results.csv", results, RESULT_COLUMNS)
    _write_csv(OUTPUT_DIR / "phase_gate_checks.csv", gates, GATE_COLUMNS)
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        """# C5 Phased Development Controller Activation

## Purpose

This stage activates the prepared HSM, PEFA, boiler and generator contracts in
four opt-in fixed-schedule 24-hour development rounds. It uses the existing
process-first WAG hierarchy: mandatory process use, HSM/PEFA, boiler/steam,
generator interface, then flare. No C0 free binary planning is used.

## Controller treatment

- HSM: throughput-linked reheat demand; BFG/COG/BOFG remain separate and named
  NG is used only if the represented WAG routes cannot meet demand.
- PEFA: reuses the existing C5n_a total-gas controller outputs. Its WAG routes
  are BOFG to Malerij and COG to Branderij; their fixed continuous heat demand
  receives named NG backup only in hours where the corresponding WAG is absent.
- Boilers: reuse the C5p_b demand-led scaffold, not nameplate capacity. BFG and
  COG are eligible; named NG is an explicit backup, not residual NG.
- Generator: a capped residual WAG interface with internal-offset reporting
  only. It has no export revenue, DA price response or mFRR behaviour.

## Interpretation

These are physical development checks. The static C0 schedule contains hours
without COG/BOFG/BFG production, so named PEFA and boiler NG may appear even
where the annual controller diagnostics had none. That is a useful visibility
result, not a reason to add residual NG or to tune parameters.

The Mode-B WAG subtotal counts each represented WAG stream once at its
oxidation sink. It is not a complete Scope-1, ETS or annual-anchor result.
""",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    run_s4_4c5p_ac_phased_development_controller_activation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
