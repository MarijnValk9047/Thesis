"""Read-only governed input adapter for the future carrier-specific WAG MILP.

It deliberately returns source status and blocked routes rather than supplying
fallback values.  It is not an allocator and does not mutate model inputs.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .s4_4b5a_asymmetric_correction import CORRECTED_INPUT_DIR
from .wag_diagnostic_inputs import load_selected_wag_inputs, load_wag_demand_coefficients


S3_DIR = CORRECTED_INPUT_DIR.parent.parent.parent / "S3" / "s3_provisional_dev_input"
SELECTED_PATH = S3_DIR / "s3_wag_selected_dev_inputs.csv"
DEMAND_PATH = S3_DIR / "s3_wag_demand_coefficients.csv"
ELIGIBILITY_PATH = CORRECTED_INPUT_DIR / "wag_sink_eligibility.csv"

PHYSICAL_CARRIERS = {"BFG", "COG", "BOFG"}
NORMALISE_CARRIER = {"BFG": "BFG", "COG": "COG", "BOFG/LDG": "BOFG"}


class WAGMILPInputContractError(ValueError):
    """Raised when a WAG contract input violates the governed policy."""


@dataclass(frozen=True)
class GovernedCarrierParameter:
    carrier: str
    parameter_name: str
    selected_value: float
    unit: str
    energy_basis: str
    sensitivity_required: bool
    source_card_ids: tuple[str, ...]


@dataclass(frozen=True)
class GovernedWAGMILPContract:
    carrier_parameters: tuple[GovernedCarrierParameter, ...]
    eligibility_rows: tuple[dict[str, str], ...]
    demand_rows: tuple[dict[str, str], ...]


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_governed_wag_milp_contract() -> GovernedWAGMILPContract:
    selected = load_selected_wag_inputs(SELECTED_PATH)
    demand = load_wag_demand_coefficients(DEMAND_PATH)
    carrier_parameters: list[GovernedCarrierParameter] = []
    wanted = {
        ("BFG", "bfg_lhv"),
        ("COG", "cog_lhv_raw_gas"),
        ("BOFG/LDG", "bofg_lhv_downstream_gasholder"),
        ("BFG", "bfg_combustion_factor_netherlands"),
        ("COG", "cog_combustion_factor_netherlands"),
        ("BOFG/LDG", "oxygas_bofg_combustion_factor_netherlands"),
        ("NG", "eu_ets_natural_gas_reference_factor"),
    }
    for item in selected.values():
        if (item.carrier, item.parameter_name) not in wanted:
            continue
        if item.selected_number is None:
            raise WAGMILPInputContractError(f"Expected numeric selected WAG value for {item.parameter_name}.")
        carrier_parameters.append(
            GovernedCarrierParameter(
                carrier=NORMALISE_CARRIER.get(item.carrier, item.carrier),
                parameter_name=item.parameter_name,
                selected_value=item.selected_number,
                unit=item.unit,
                energy_basis=item.energy_basis,
                sensitivity_required=item.sensitivity_required,
                source_card_ids=item.source_card_ids,
            )
        )
    names = {row.parameter_name for row in carrier_parameters}
    required = {name for _, name in wanted}
    if names != required:
        raise WAGMILPInputContractError(f"Incomplete WAG MILP parameter contract: missing={sorted(required - names)}.")

    eligibility_rows: list[dict[str, str]] = []
    for row in _csv_rows(ELIGIBILITY_PATH):
        carrier = NORMALISE_CARRIER.get(row["wag_carrier"])
        if carrier not in PHYSICAL_CARRIERS:
            continue
        if row["sink_asset"] == "WAG_COK1_mixer" and carrier == "BFG":
            row = {**row, "contract_status": "blocked_by_current_COG_only_KGF_policy"}
        else:
            row = {**row, "contract_status": "structural_eligibility_only"}
        eligibility_rows.append(row)

    demand_rows = []
    for item in demand.values():
        demand_rows.append(
            {
                "configuration_id": item.configuration_id,
                "linked_activity_id": item.linked_activity_id,
                "demand_name": item.demand_name,
                "eligible_carriers": ";".join(NORMALISE_CARRIER.get(carrier, carrier) for carrier in item.eligible_carriers),
                "selected_value": str(item.selected_value),
                "unit": item.unit,
                "energy_basis": item.energy_basis,
                "sensitivity_required": str(item.sensitivity_required).lower(),
                "source_card_ids": ";".join(item.source_card_ids),
            }
        )
    return GovernedWAGMILPContract(tuple(carrier_parameters), tuple(eligibility_rows), tuple(demand_rows))


def load_governed_wag_factor_maps() -> tuple[dict[str, float], dict[str, float]]:
    """Return selected LHV and point-of-oxidation factors in model units.

    The modelbuilder may use this narrow adapter for carrier conversions and
    diagnostic combustion reporting.  It deliberately returns no allocation,
    demand or mixed-gas information.

    Returns
    -------
    tuple
        ``({carrier: MJ_per_Nm3}, {carrier: tCO2_per_MWh_LHV})`` for BFG,
        COG and BOFG.  The second map is suitable for any represented point of
        oxidation, including explicit flare reporting.
    """

    contract = load_governed_wag_milp_contract()
    values = {item.parameter_name: item for item in contract.carrier_parameters}
    lhv_names = {
        "BFG": "bfg_lhv",
        "COG": "cog_lhv_raw_gas",
        "BOFG": "bofg_lhv_downstream_gasholder",
    }
    factor_names = {
        "BFG": "bfg_combustion_factor_netherlands",
        "COG": "cog_combustion_factor_netherlands",
        "BOFG": "oxygas_bofg_combustion_factor_netherlands",
    }

    lhv: dict[str, float] = {}
    combustion_t_per_mwh: dict[str, float] = {}
    for carrier, name in lhv_names.items():
        item = values.get(name)
        if item is None or item.energy_basis != "LHV":
            raise WAGMILPInputContractError(f"Missing LHV-basis selected value for {carrier}.")
        lhv[carrier] = item.selected_value
    for carrier, name in factor_names.items():
        item = values.get(name)
        if item is None or item.energy_basis != "LHV_energy":
            raise WAGMILPInputContractError(f"Missing LHV-energy combustion factor for {carrier}.")
        # kgCO2/GJ_LHV * 3.6 GJ/MWh / 1000 kg/t
        combustion_t_per_mwh[carrier] = item.selected_value * 3.6 / 1000.0
    return lhv, combustion_t_per_mwh
