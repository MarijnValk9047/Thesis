"""Validated development-controller contract for the staged C5 WAG MILP.

The contract is intentionally narrower than a full source-card universe.  It
contains only user-approved development rows and exposes no gas allocation or
fallback decision by itself.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

S4_ROOT = Path("data/03_Optimisation/inputs/assets/steel/S4")
CONTRACT_PATH = S4_ROOT / "s4_4c5p_aa_development_controller_contracts" / "controller_contract_inputs.csv"
PEFA_CONTROLLER_PATH = S4_ROOT / "s4_4c5n_a_pefa_pelletizing_layer" / "s4_4c5n_a_pefa_gas_controller_dashboard.csv"
PEFA_ACTIVITY_PATH = S4_ROOT / "s4_4c5n_a_pefa_pelletizing_layer" / "s4_4c5n_a_pefa_activity_report.csv"
BOILER_FUEL_PATH = S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_boiler_fuel_allocation.csv"
BOILER_STEAM_DEMAND_PATH = S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting" / "s4_4c5p_b_steam_demand_by_pressure.csv"
GENERATOR_FUEL_PATH = S4_ROOT / "s4_4c5p_c_ij01_vn25_generator_interface_accounting" / "s4_4c5p_c_generator_fuel_allocation.csv"
BOF_ELECTRICITY_PATH = S4_ROOT / "s4_4c5j_BOF_OSF_minimal_parameterisation" / "s4_4c5j_bof_osf_parameter_register.csv"
KGF_ELECTRICITY_PATH = S4_ROOT / "s4_4c5p_i_source_card_candidate_overlay_reconciliation" / "c5_candidate_overlay_electricity_by_plant.csv"
DSP_ELECTRICITY_PATH = S4_ROOT / "s4_4c5o_c_dsp_downstream_physical_layer" / "s4_4c5o_c_dsp_development_input_rows.csv"
ASU_ELECTRICITY_PATH = S4_ROOT / "s4_4c5p_a_linde_asu_oxygen_accounting" / "s4_4c5p_a_linde_development_input_rows.csv"
SINTER_ELECTRICITY_PATH = S4_ROOT / "s4_4c5m_Sinter_minimal_parameterisation" / "s4_4c5m_sinter_development_input_rows.csv"
BF_PARAMETER_PATH = S4_ROOT / "s4_4c5h_blast_furnace_controller_parameterisation" / "s4_4c5h_bf_parameter_values.csv"
HOURS_PER_YEAR = 8760.0

CONFIGURATION_LABELS = {
    "C0_current_BF_BOF_reference": "C0_current_BF_BOF_reference",
    "C1_phase1_BF_BOF_plus_DRP_EAF": "C1_phase1_BF_BOF_plus_DRP_EAF",
}


class DevelopmentControllerContractError(ValueError):
    """Raised when a selected development contract is incomplete or unsafe."""


@dataclass(frozen=True)
class DevelopmentControllerContract:
    controller_id: str
    config_scope: tuple[str, ...]
    driver_id: str
    demand_carrier: str
    central_value: float
    unit: str
    eligible_fuels_base: tuple[str, ...]
    eligible_fuels_fallback: tuple[str, ...]
    status: str
    model_use: str
    caveat: str


@dataclass(frozen=True)
class DevelopmentControllerProfile:
    """Read-only hourly profile compiled from accepted C5 controller outputs.

    The profile deliberately preserves source-stage allocations rather than
    deriving demand from nameplate capacity or inventing gas-mix ratios.
    """

    configuration_id: str
    pefa_pellets_t_h: float
    pefa_bofg_mwh_h: float
    pefa_cog_mwh_h: float
    boiler_fuel_mwh_h: float
    boiler_bfg_mwh_h: float
    boiler_cog_mwh_h: float
    boiler_steam_15bar_demand_t_h: float
    boiler_fuel_mwh_per_t_steam: float
    generator_wag_interface_cap_mwh_h: float
    bof_electricity_mwh_per_t_ls: float
    kgf_electricity_mwh_per_t_coke: float
    dsp_electricity_mwh_per_t_coil: float
    asu_electricity_mwh_per_t_o2: float
    sinter_electricity_mwh_per_t_sinter: float
    bof_oxygen_t_per_t_ls: float
    bf_electricity_mwh_per_t_hot_metal: float
    bf_oxygen_t_per_t_hot_metal: float


def _split(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(";") if item.strip())


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise DevelopmentControllerContractError(f"Missing accepted controller output: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _first_row(rows: list[dict[str, str]], **criteria: str) -> dict[str, str]:
    matches = [row for row in rows if all(row.get(key) == value for key, value in criteria.items())]
    if len(matches) != 1:
        raise DevelopmentControllerContractError(f"Expected one controller-output row for {criteria}, found {len(matches)}")
    return matches[0]


def _as_float(row: dict[str, str], field: str) -> float:
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise DevelopmentControllerContractError(f"Invalid {field} in controller output") from exc


def load_development_controller_contracts() -> dict[str, DevelopmentControllerContract]:
    if not CONTRACT_PATH.exists():
        raise DevelopmentControllerContractError(f"Missing development controller contract: {CONTRACT_PATH}")
    with CONTRACT_PATH.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    contracts: dict[str, DevelopmentControllerContract] = {}
    for row in rows:
        try:
            central_value = float(row["central_value"])
        except (KeyError, ValueError) as exc:
            raise DevelopmentControllerContractError(f"Invalid central value for {row.get('controller_id', 'unknown')}") from exc
        controller_id = row["controller_id"]
        if controller_id in contracts:
            raise DevelopmentControllerContractError(f"Duplicate controller contract: {controller_id}")
        contracts[controller_id] = DevelopmentControllerContract(
            controller_id=controller_id,
            config_scope=_split(row["config_scope"]),
            driver_id=row["driver_id"],
            demand_carrier=row["demand_carrier"],
            central_value=central_value,
            unit=row["unit"],
            eligible_fuels_base=_split(row["eligible_fuels_base"]),
            eligible_fuels_fallback=_split(row["eligible_fuels_fallback"]),
            status=row["status"],
            model_use=row["model_use"],
            caveat=row["caveat"],
        )
    hot_stove = contracts.get("BF_HOT_STOVE_CONTROLLER")
    if hot_stove is None or hot_stove.config_scope != ("C0", "C1"):
        raise DevelopmentControllerContractError("BF hot-stove contract must explicitly cover C0 and C1.")
    if hot_stove.unit != "GJ/t_HM" or hot_stove.eligible_fuels_base != ("BFG",):
        raise DevelopmentControllerContractError("BF hot-stove base policy must be BFG-first on a GJ/t_HM basis.")
    return contracts


def bf_hot_stove_mwh_per_t_hot_metal() -> float:
    """Return the user-approved C0/C1 development demand in MWh_LHV/t HM."""

    contract = load_development_controller_contracts()["BF_HOT_STOVE_CONTROLLER"]
    return contract.central_value / 3.6


def hsm_reheat_mwh_per_t_hrc() -> float:
    """Return the approved central HSM reheat demand on an LHV-energy basis."""

    contract = load_development_controller_contracts()["HSM_REHEAT_CONTROLLER"]
    return contract.central_value / 3.6


def hsm_rolling_electricity_mwh_per_t_hrc() -> float:
    """Return the separate, throughput-linked HSM electricity diagnostic."""

    contract = load_development_controller_contracts()["HSM_ROLLING_ELECTRICITY"]
    return contract.central_value


def load_development_controller_profile(configuration_id: str) -> DevelopmentControllerProfile:
    """Compile accepted annual controller outputs to fixed hourly development rows.

    This is intentionally a read-only adapter.  It never turns the annual
    source-stage values into an hourly dispatch target: PEFA and boiler rows
    are fixed continuous development demands; the generator value is a cap
    and validation interface only.
    """

    if configuration_id not in CONFIGURATION_LABELS:
        raise DevelopmentControllerContractError(f"Unsupported configuration: {configuration_id}")
    label = CONFIGURATION_LABELS[configuration_id]

    pefa = _first_row(_read_rows(PEFA_CONTROLLER_PATH), configuration=label, horizon_hours="24")
    pefa_activity = _first_row(_read_rows(PEFA_ACTIVITY_PATH), configuration=label, horizon_hours="24")
    boiler_rows = [
        row
        for row in _read_rows(BOILER_FUEL_PATH)
        if row.get("configuration") == label and row.get("horizon_hours") == "24"
    ]
    if not boiler_rows:
        raise DevelopmentControllerContractError(f"No C5p_b boiler rows for {configuration_id}")
    steam_demand = _first_row(
        _read_rows(BOILER_STEAM_DEMAND_PATH),
        configuration=label,
        horizon_hours="24",
        pressure_level="steam_15bar",
    )
    steam_demand_t_y = _as_float(steam_demand, "total_demand_t_y")
    if steam_demand_t_y <= 0.0:
        raise DevelopmentControllerContractError(f"C5p_b 15-bar steam demand must be positive for {configuration_id}")
    boiler_fuel_mwh_y = sum(_as_float(row, "fuel_required_MWh_LHV_y") for row in boiler_rows)
    generator_rows = [
        row
        for row in _read_rows(GENERATOR_FUEL_PATH)
        if row.get("configuration") == label
        and row.get("horizon_hours") == "24"
        and (
            row.get("unit_id") == "C0_CURRENT_GENERATOR_INTERFACE"
            if configuration_id.startswith("C0")
            else row.get("unit_id") in {"VN25", "IJ01"}
        )
    ]
    if not generator_rows:
        raise DevelopmentControllerContractError(f"No C5p_c generator rows for {configuration_id}")
    bof_electricity = _first_row(
        _read_rows(BOF_ELECTRICITY_PATH),
        parameter_id="BOF_ELECTRICITY_MWH_PER_T_LS",
    )
    kgf_electricity = _first_row(
        _read_rows(KGF_ELECTRICITY_PATH),
        configuration=label,
        candidate_parameter_id="KGF_ELECTRICITY_PURCHASED_GJ_PER_T_COKE",
    )
    dsp_electricity = _first_row(
        _read_rows(DSP_ELECTRICITY_PATH),
        parameter_id="DSP_ELECTRICITY_MWH_PER_T_COIL_BASE",
    )
    asu_electricity = _first_row(
        _read_rows(ASU_ELECTRICITY_PATH),
        parameter_id="LINDE_ASU_ELECTRICITY_MWH_PER_T_O2_GAS_BASE",
    )
    sinter_electricity = _first_row(
        _read_rows(SINTER_ELECTRICITY_PATH),
        parameter_id="SINTER_ELECTRICITY_MWH_PER_T_SINTER",
    )
    bof_oxygen = _first_row(
        _read_rows(BOF_ELECTRICITY_PATH),
        parameter_id="BOF_OXYGEN_INPUT_KG_PER_T_LS",
    )
    bf_electricity = _first_row(
        _read_rows(BF_PARAMETER_PATH),
        parameter_id="BF_ELECTRICITY_MWH_PER_T_HM",
    )
    bf_oxygen = _first_row(
        _read_rows(BF_PARAMETER_PATH),
        parameter_id="BF_OXYGEN_INPUT_KG_PER_T_HM",
    )

    return DevelopmentControllerProfile(
        configuration_id=configuration_id,
        pefa_pellets_t_h=_as_float(pefa_activity, "PEFA_output_site_t_y") / HOURS_PER_YEAR,
        pefa_bofg_mwh_h=_as_float(pefa, "BOFG_to_PEFA_malerij_site_MWh_y") / HOURS_PER_YEAR,
        pefa_cog_mwh_h=_as_float(pefa, "COG_to_PEFA_branderij_site_MWh_y") / HOURS_PER_YEAR,
        boiler_fuel_mwh_h=boiler_fuel_mwh_y / HOURS_PER_YEAR,
        boiler_bfg_mwh_h=sum(_as_float(row, "BFG_MWh_LHV_y") for row in boiler_rows) / HOURS_PER_YEAR,
        boiler_cog_mwh_h=sum(_as_float(row, "COG_MWh_LHV_y") for row in boiler_rows) / HOURS_PER_YEAR,
        boiler_steam_15bar_demand_t_h=steam_demand_t_y / HOURS_PER_YEAR,
        boiler_fuel_mwh_per_t_steam=boiler_fuel_mwh_y / steam_demand_t_y,
        generator_wag_interface_cap_mwh_h=sum(
            _as_float(row, "BFG_MWh_LHV_y")
            + _as_float(row, "BOFG_MWh_LHV_y")
            + _as_float(row, "COG_MWh_LHV_y")
            for row in generator_rows
        )
        / HOURS_PER_YEAR,
        bof_electricity_mwh_per_t_ls=_as_float(bof_electricity, "base_value"),
        kgf_electricity_mwh_per_t_coke=_as_float(kgf_electricity, "candidate_value"),
        dsp_electricity_mwh_per_t_coil=_as_float(dsp_electricity, "base_value"),
        asu_electricity_mwh_per_t_o2=_as_float(asu_electricity, "base_value"),
        sinter_electricity_mwh_per_t_sinter=_as_float(sinter_electricity, "base_value"),
        bof_oxygen_t_per_t_ls=_as_float(bof_oxygen, "base_value") / 1_000.0,
        bf_electricity_mwh_per_t_hot_metal=_as_float(bf_electricity, "base_value"),
        bf_oxygen_t_per_t_hot_metal=_as_float(bf_oxygen, "base_value") / 1_000.0,
    )
