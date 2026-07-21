"""Validate the user-approved development controller contract before activation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .wag_development_controller_contract import CONTRACT_PATH, load_development_controller_contracts


STAGE = "S4.4c5p_aa_development_controller_contracts"
OUTPUT_DIR = Path("data/03_Optimisation/inputs/assets/steel/S4/s4_4c5p_aa_development_controller_contracts")
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_DEVELOPMENT_MILP_CONTROLLER_CONTRACTS.md")
COLUMNS = ["controller_id", "config_scope", "driver_id", "demand_carrier", "central_value", "unit", "eligible_fuels_base", "eligible_fuels_fallback", "status", "model_use", "activation_status", "caveat"]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    import csv

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def run_s4_4c5p_aa_development_controller_contracts() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    contracts = load_development_controller_contracts()
    rows = []
    for contract in contracts.values():
        activation = "active_in_minimal_wag_layer" if contract.model_use == "active_wag_layer" else "prepared_not_active"
        rows.append(
            {
                "controller_id": contract.controller_id,
                "config_scope": ";".join(contract.config_scope),
                "driver_id": contract.driver_id,
                "demand_carrier": contract.demand_carrier,
                "central_value": str(contract.central_value),
                "unit": contract.unit,
                "eligible_fuels_base": ";".join(contract.eligible_fuels_base),
                "eligible_fuels_fallback": ";".join(contract.eligible_fuels_fallback),
                "status": contract.status,
                "model_use": contract.model_use,
                "activation_status": activation,
                "caveat": contract.caveat,
            }
        )
    checks = {
        "bf_hot_stove_c0_c1": contracts["BF_HOT_STOVE_CONTROLLER"].config_scope == ("C0", "C1"),
        "bf_hot_stove_bfg_first": contracts["BF_HOT_STOVE_CONTROLLER"].eligible_fuels_base == ("BFG",),
        "hsm_prepared_not_active": contracts["HSM_REHEAT_CONTROLLER"].model_use == "prepared_not_active",
        "pefa_total_no_invented_stage_split": contracts["PEFA_TOTAL_GAS_HEAT_CONTROLLER"].model_use == "prepared_not_active",
        "boiler_not_capacity_driven": contracts["BOILER_STEAM_DEMAND_SCAFFOLD"].driver_id == "C5PB_MODELLED_STEAM_DEMAND",
        "generator_not_free_dispatch": contracts["VN25_IJ01_FIXED_INTERFACE"].model_use == "prepared_not_active",
    }
    summary = {
        "stage": STAGE,
        "status": "bf_hot_stove_active_contract_hsm_pefa_boiler_generator_prepared",
        "contract_row_count": len(rows),
        "validation_checks": checks,
        "go_no_go": {
            "bf_hot_stove_controller": "GO_DEVELOPMENT_ONLY",
            "hsm_controller": "PREPARED_NOT_ACTIVE",
            "pefa_total_gas_controller": "PREPARED_NOT_ACTIVE",
            "boiler_steam_migration": "PREPARED_NOT_ACTIVE",
            "generator_interface": "PREPARED_NOT_ACTIVE",
            "nonfuel_process_CO2": "NO_GO",
            "ETS_or_economics": "NO_GO",
        },
    }
    _write_csv(OUTPUT_DIR / "controller_contract_register.csv", rows)
    (OUTPUT_DIR / "validation_checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        """# C5 Development MILP Controller Contracts

## Status

This compact contract records the user-approved development choices used to
continue WAG integration. It does not turn candidate values into thesis truth.

## Active now

`BF_HOT_STOVE_CONTROLLER` applies to both C0 and C1 at 2.20 GJ/t hot metal.
It is BFG-first; COG, BOFG and NG remain explicit fallback routes that are not
activated by the current minimal WAG layer.

## Prepared, not active

- HSM reheat: 1.35 GJ/t HRC, with 1.20-1.50 sensitivity range.
- PEFA total gas heat: 0.320 GJ/t pellets, without an invented Malerij/
  Branderij split.
- Boiler/steam: C5p_b demand-led scaffold, never capacity-derived demand.
- VN25/IJ01: fixed or validation-scaled internal-offset interface only.

## CO2 policy

Mode B counts named fuel at the represented oxidation sink. Aggregate process
counters and residual energy remain outside that subtotal. Solid-fuel and
non-fuel process carbon remain source-repair work.
""",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    run_s4_4c5p_aa_development_controller_contracts()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
