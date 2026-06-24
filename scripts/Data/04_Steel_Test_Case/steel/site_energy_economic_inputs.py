from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .wag_diagnostic_inputs import DEFAULT_SELECTED_WAG_INPUT_PATH, load_selected_wag_inputs


REPO_ROOT = Path(__file__).resolve().parents[4]
S3_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S3"
S3_DEV_ROOT = S3_ROOT / "s3_provisional_dev_input"
DEFAULT_S3_1_ENERGY_INPUT_PATH = S3_DEV_ROOT / "s3_1_selected_energy_emissions_inputs.csv"
DEFAULT_S3_1_PRICE_INPUT_PATH = S3_DEV_ROOT / "s3_1_selected_static_price_inputs.csv"
DEFAULT_C1_ROUTE_ENERGY_INPUT_PATH = S3_DEV_ROOT / "s3_c1_route_energy_inputs.csv"
DEFAULT_C0_WAG_FIXED_PROFILE_PATH = (
    S3_DEV_ROOT / "fixed_profiles" / "c0_wag_fixed_profile_24h_dev.csv"
)

GJ_PER_MWH = 3.6
WAG_CARRIERS = ("BFG", "COG", "BOFG_LD_gas")

S3_1_SELECTED_ENERGY_INPUT_COLUMNS = [
    "input_id",
    "parameter_family",
    "parameter_name",
    "asset",
    "carrier",
    "selected_value",
    "selected_lower",
    "selected_upper",
    "unit",
    "activity_basis",
    "energy_basis",
    "source_card_ids",
    "candidate_evidence_ids",
    "evidence_tier",
    "model_use_status",
    "selection_method",
    "sensitivity_required",
    "tata_exact_claim_allowed",
    "thesis_validation_claim_eligible",
    "zero_value_status",
    "limitations",
    "notes",
]

S3_1_SELECTED_STATIC_PRICE_COLUMNS = [
    "price_input_id",
    "price_name",
    "selected_value",
    "selected_lower",
    "selected_upper",
    "unit",
    "activity_basis",
    "source_card_ids",
    "candidate_evidence_ids",
    "evidence_tier",
    "model_use_status",
    "selection_method",
    "sensitivity_required",
    "tata_exact_claim_allowed",
    "thesis_validation_claim_eligible",
    "missing_blocks",
    "limitations",
    "notes",
]


class SiteEnergyEconomicInputError(ValueError):
    """Raised when governed S3.1 input rows are missing or unsafe."""


@dataclass(frozen=True)
class C1RouteEnergyCoefficients:
    drp_natural_gas_m3_per_t_steel: float
    drp_electricity_mwh_per_t_steel: float
    eaf_electricity_mwh_per_t_steel: float
    drp_direct_co2_t_per_t_steel: float
    dri_required_per_t_steel: float
    pellets_required_per_t_steel: float
    eaf_oxygen_t_per_t_dri: float
    drp_oxygen_t_per_t_pellets: float


@dataclass(frozen=True)
class WAGCoefficients:
    bf_hot_metal_t_per_t_bof_liquid_steel: float
    dry_coal_t_per_t_hot_metal: float
    bfg_gj_per_t_hot_metal: float
    cog_gj_per_t_dry_coal: float
    bofg_gj_per_t_liquid_steel: float
    bfg_hot_stove_gj_per_t_hot_metal: float
    cog_hot_stove_pci_gj_per_t_hot_metal: float
    coking_underfire_gj_per_t_hot_metal: float
    coking_steam_useful_gj_per_t_hot_metal: float
    bfg_co2_t_per_gj: float
    cog_co2_t_per_gj: float
    bofg_co2_t_per_gj: float
    natural_gas_co2_t_per_gj: float
    boiler_efficiency: float
    wag_to_power_efficiency: float
    wag_power_base_mode: str


@dataclass(frozen=True)
class SiteEnergyEconomicAssumptions:
    assumption_set_id: str
    sensitivity_case: str
    secondary_metallurgy_electricity_mwh_per_t: float
    casting_electricity_mwh_per_t: float
    slab_handling_electricity_mwh_per_t: float
    dsp_electricity_mwh_per_t: float
    reheating_heat_gj_per_t_cold_slab: float
    reheating_aux_electricity_mwh_per_t: float
    hsm_electricity_mwh_per_t: float
    asu_electricity_mwh_per_t_o2: float
    bof_oxygen_t_per_t_bof: float
    residual_auxiliary_electricity_mwh_per_t_final: float
    natural_gas_energy_content_gj_per_m3: float
    downstream_light_side_utility_heat_demand_gj_per_h: float
    downstream_light_side_minimum_ng_gj_per_h: float
    wag: WAGCoefficients
    c1_route: C1RouteEnergyCoefficients
    monetary_values_ready: bool
    selected_prices: dict[str, float]
    missing_price_inputs: tuple[str, ...]
    complete_direct_emissions_ready: bool
    scope2_electricity_counted: bool
    ets_ready: bool


def _read_csv(path: Path, required_columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise SiteEnergyEconomicInputError(f"Required S3.1 input file is missing: {path}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise SiteEnergyEconomicInputError(f"{path.name} is missing columns: {missing}")
    return frame


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _numeric(value: Any, *, parameter_name: str) -> float:
    text = str(value).strip()
    if text == "":
        raise SiteEnergyEconomicInputError(f"Parameter {parameter_name} has no selected numeric value.")
    try:
        return float(text)
    except ValueError as exc:
        raise SiteEnergyEconomicInputError(f"Parameter {parameter_name} must be numeric; got {value!r}.") from exc


def _optional_numeric(value: Any) -> float | None:
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _profile_activity_total(path: Path, activity_type: str) -> float:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    matches = frame.loc[frame["s2_activity_type"].eq(activity_type)]
    if matches.empty:
        raise SiteEnergyEconomicInputError(f"{path.name} has no activity_type={activity_type!r}.")
    return float(matches["activity_value"].astype(float).sum())


def validate_wag_activity_basis(driver_unit: str, coefficient_unit: str) -> None:
    driver = driver_unit.strip()
    coefficient = coefficient_unit.strip()
    allowed = {
        ("t_hot_metal", "Nm3/t_hot_metal"),
        ("t_dry_coal", "m3/t_dry_coal"),
        ("t_liquid_steel", "Nm3/t_liquid_steel"),
    }
    if (driver, coefficient) not in allowed:
        raise SiteEnergyEconomicInputError(
            f"Incompatible WAG activity basis: driver {driver!r} cannot use coefficient {coefficient!r}."
        )


def _select_value(row: pd.Series, *, parameter_name: str, sensitivity_case: str) -> float:
    value_column = {
        "central": "selected_value",
        "low": "selected_lower",
        "high": "selected_upper",
    }.get(sensitivity_case)
    if value_column is None:
        raise SiteEnergyEconomicInputError(f"Unsupported sensitivity_case={sensitivity_case!r}.")
    raw = row[value_column]
    if str(raw).strip() == "" and value_column != "selected_value":
        raw = row["selected_value"]
    return _numeric(raw, parameter_name=parameter_name)


def _validate_energy_inputs(frame: pd.DataFrame) -> None:
    if frame["input_id"].duplicated().any():
        duplicates = frame.loc[frame["input_id"].duplicated(), "input_id"].tolist()
        raise SiteEnergyEconomicInputError(f"S3.1 selected energy inputs have duplicate input_id rows: {duplicates}")
    if frame["parameter_name"].duplicated().any():
        duplicates = frame.loc[frame["parameter_name"].duplicated(), "parameter_name"].tolist()
        raise SiteEnergyEconomicInputError(f"S3.1 selected energy inputs have duplicate parameter_name rows: {duplicates}")
    active = frame.loc[~frame["model_use_status"].isin(("not_selected_missing", "blocked"))]
    if active["tata_exact_claim_allowed"].map(_as_bool).any():
        raise SiteEnergyEconomicInputError("S3.1 selected inputs must not claim Tata-exact status.")
    if active["thesis_validation_claim_eligible"].map(_as_bool).any():
        raise SiteEnergyEconomicInputError("S3.1 selected inputs must not be validation-claim eligible.")
    tier_d = active.loc[active["evidence_tier"].eq("D")]
    if not tier_d.empty and (~tier_d["sensitivity_required"].map(_as_bool)).any():
        ids = tier_d.loc[~tier_d["sensitivity_required"].map(_as_bool), "input_id"].tolist()
        raise SiteEnergyEconomicInputError(f"Tier-D S3.1 selected inputs require sensitivity: {ids}")
    zero_rows = active.loc[active["selected_value"].astype(str).str.strip().isin({"0", "0.0", "0.00"})]
    hidden_zero = zero_rows.loc[zero_rows["zero_value_status"].astype(str).str.strip().ne("explicit_zero_valid")]
    if not hidden_zero.empty:
        raise SiteEnergyEconomicInputError("Zero selected values require zero_value_status=explicit_zero_valid.")


def _row(frame: pd.DataFrame, parameter_name: str) -> pd.Series:
    selected = frame.loc[frame["parameter_name"].eq(parameter_name)]
    if selected.empty:
        raise SiteEnergyEconomicInputError(f"Missing S3.1 selected energy input {parameter_name!r}.")
    return selected.iloc[0]


def _selected(frame: pd.DataFrame, parameter_name: str, *, sensitivity_case: str) -> float:
    return _select_value(_row(frame, parameter_name), parameter_name=parameter_name, sensitivity_case=sensitivity_case)


def _c1_row(frame: pd.DataFrame, parameter_name: str) -> pd.Series:
    selected = frame.loc[frame["parameter_name"].eq(parameter_name)]
    if selected.empty:
        raise SiteEnergyEconomicInputError(f"Missing C1 route energy input {parameter_name!r}.")
    return selected.iloc[0]


def _c1_value(frame: pd.DataFrame, parameter_name: str) -> float:
    return _numeric(_c1_row(frame, parameter_name)["selected_value"], parameter_name=parameter_name)


def _selected_wag_number(selected_inputs: dict[tuple[str, str, str, str], Any], parameter_name: str) -> float:
    matches = [row.selected_number for key, row in selected_inputs.items() if key[3] == parameter_name]
    numeric = [value for value in matches if value is not None]
    if len(numeric) != 1:
        raise SiteEnergyEconomicInputError(f"Expected one selected WAG numeric value for {parameter_name!r}.")
    return float(numeric[0])


def _load_wag_coefficients(energy_frame: pd.DataFrame, *, sensitivity_case: str) -> WAGCoefficients:
    selected_wag = load_selected_wag_inputs(DEFAULT_SELECTED_WAG_INPUT_PATH)
    validate_wag_activity_basis("t_hot_metal", "Nm3/t_hot_metal")
    validate_wag_activity_basis("t_dry_coal", "m3/t_dry_coal")
    validate_wag_activity_basis("t_liquid_steel", "Nm3/t_liquid_steel")
    c0_hot_metal = _profile_activity_total(DEFAULT_C0_WAG_FIXED_PROFILE_PATH, "bf_hot_metal_activity")
    c0_bof_liquid = _profile_activity_total(DEFAULT_C0_WAG_FIXED_PROFILE_PATH, "bof_liquid_steel_activity")
    if c0_bof_liquid <= 0.0:
        raise SiteEnergyEconomicInputError("C0 fixed WAG profile has non-positive BOF liquid steel activity.")
    hot_metal_per_bof_liquid = c0_hot_metal / c0_bof_liquid
    bfg_gj = (
        _selected_wag_number(selected_wag, "bfg_generation_per_tonne_hot_metal")
        * _selected_wag_number(selected_wag, "bfg_lhv")
        / 1000.0
    )
    bofg_gj = (
        _selected_wag_number(selected_wag, "bofg_generation_suppressed_combustion")
        * _selected_wag_number(selected_wag, "bofg_lhv_downstream_gasholder")
        / 1000.0
    )
    coke_rate = _selected_wag_number(selected_wag, "coke_rate_per_t_hot_metal")
    dry_coal_per_coke = _selected_wag_number(selected_wag, "dry_coal_input_per_t_coke")
    dry_coal_per_hot_metal = coke_rate * dry_coal_per_coke
    cog_gj = (
        _selected_wag_number(selected_wag, "cog_raw_yield_per_tonne_dry_coal")
        * _selected_wag_number(selected_wag, "cog_lhv_raw_gas")
        / 1000.0
    )
    bfg_hot_stove = 479.2 * _selected_wag_number(selected_wag, "bfg_lhv") / 1000.0
    cog_hot_stove_pci = (7.2 + 1.4) * _selected_wag_number(selected_wag, "cog_lhv_raw_gas") / 1000.0
    coking_underfire = coke_rate * 3.55
    coking_steam_useful = coke_rate * 0.43
    return WAGCoefficients(
        bf_hot_metal_t_per_t_bof_liquid_steel=hot_metal_per_bof_liquid,
        dry_coal_t_per_t_hot_metal=dry_coal_per_hot_metal,
        bfg_gj_per_t_hot_metal=bfg_gj,
        cog_gj_per_t_dry_coal=cog_gj,
        bofg_gj_per_t_liquid_steel=bofg_gj,
        bfg_hot_stove_gj_per_t_hot_metal=bfg_hot_stove,
        cog_hot_stove_pci_gj_per_t_hot_metal=cog_hot_stove_pci,
        coking_underfire_gj_per_t_hot_metal=coking_underfire,
        coking_steam_useful_gj_per_t_hot_metal=coking_steam_useful,
        bfg_co2_t_per_gj=_selected_wag_number(selected_wag, "bfg_combustion_factor_netherlands") / 1000.0,
        cog_co2_t_per_gj=_selected_wag_number(selected_wag, "cog_combustion_factor_netherlands") / 1000.0,
        bofg_co2_t_per_gj=_selected_wag_number(selected_wag, "oxygas_bofg_combustion_factor_netherlands") / 1000.0,
        natural_gas_co2_t_per_gj=_selected_wag_number(selected_wag, "eu_ets_natural_gas_reference_factor") / 1000.0,
        boiler_efficiency=_selected_wag_number(selected_wag, "boiler_steam_useful_energy_efficiency"),
        wag_to_power_efficiency=_selected(
            energy_frame,
            "wag_to_power_efficiency_fraction",
            sensitivity_case=sensitivity_case,
        ),
        wag_power_base_mode=str(_row(energy_frame, "wag_to_power_base_dispatch_mode")["selected_value"]).strip(),
    )


def _load_c1_route_coefficients(path: Path = DEFAULT_C1_ROUTE_ENERGY_INPUT_PATH) -> C1RouteEnergyCoefficients:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    return C1RouteEnergyCoefficients(
        drp_natural_gas_m3_per_t_steel=_c1_value(frame, "drp_natural_gas_per_t_steel"),
        drp_electricity_mwh_per_t_steel=_c1_value(frame, "drp_electricity_per_t_steel"),
        eaf_electricity_mwh_per_t_steel=_c1_value(frame, "eaf_electricity_per_t_steel"),
        drp_direct_co2_t_per_t_steel=_c1_value(frame, "drp_direct_co2_proxy_per_t_steel"),
        dri_required_per_t_steel=_c1_value(frame, "dri_required_per_t_steel"),
        pellets_required_per_t_steel=_c1_value(frame, "pellets_required_per_t_steel"),
        eaf_oxygen_t_per_t_dri=_c1_value(frame, "eaf_oxygen_consumption"),
        drp_oxygen_t_per_t_pellets=_c1_value(frame, "ng_drp_oxygen_consumption"),
    )


def _load_prices(path: Path) -> tuple[bool, dict[str, float], tuple[str, ...]]:
    frame = _read_csv(path, S3_1_SELECTED_STATIC_PRICE_COLUMNS)
    if frame["price_input_id"].duplicated().any() or frame["price_name"].duplicated().any():
        raise SiteEnergyEconomicInputError("S3.1 static price inputs must not contain duplicate IDs or names.")
    selected: dict[str, float] = {}
    missing: list[str] = []
    for row in frame.to_dict(orient="records"):
        value = _optional_numeric(row["selected_value"])
        if value is None:
            missing.append(str(row["price_name"]).strip())
            continue
        selected[str(row["price_name"]).strip()] = value
    required = {"grid_electricity_price", "natural_gas_price", "gross_co2_price"}
    monetary_ready = required.issubset(set(selected))
    missing_required = tuple(sorted(required - set(selected)))
    return monetary_ready, selected, tuple(sorted(set(missing) | set(missing_required)))


def load_site_energy_economic_assumptions(
    *,
    sensitivity_case: str = "central",
    energy_input_path: str | Path = DEFAULT_S3_1_ENERGY_INPUT_PATH,
    price_input_path: str | Path = DEFAULT_S3_1_PRICE_INPUT_PATH,
) -> SiteEnergyEconomicAssumptions:
    energy_frame = _read_csv(Path(energy_input_path), S3_1_SELECTED_ENERGY_INPUT_COLUMNS)
    _validate_energy_inputs(energy_frame)
    monetary_ready, selected_prices, missing_prices = _load_prices(Path(price_input_path))
    wag = _load_wag_coefficients(energy_frame, sensitivity_case=sensitivity_case)
    c1_route = _load_c1_route_coefficients()
    return SiteEnergyEconomicAssumptions(
        assumption_set_id="S3_1_DOWNSTREAM_AWARE_ENERGY_EMISSIONS_CENTRAL_DEV",
        sensitivity_case=sensitivity_case,
        secondary_metallurgy_electricity_mwh_per_t=_selected(
            energy_frame, "secondary_metallurgy_electricity_mwh_per_t", sensitivity_case=sensitivity_case
        ),
        casting_electricity_mwh_per_t=_selected(
            energy_frame, "continuous_casting_electricity_mwh_per_t", sensitivity_case=sensitivity_case
        ),
        slab_handling_electricity_mwh_per_t=_selected(
            energy_frame, "slab_handling_electricity_mwh_per_t", sensitivity_case=sensitivity_case
        ),
        dsp_electricity_mwh_per_t=_selected(energy_frame, "dsp_electricity_mwh_per_t", sensitivity_case=sensitivity_case),
        reheating_heat_gj_per_t_cold_slab=_selected(
            energy_frame, "reheating_heat_gj_per_t_cold_slab", sensitivity_case=sensitivity_case
        ),
        reheating_aux_electricity_mwh_per_t=_selected(
            energy_frame, "reheating_aux_electricity_mwh_per_t", sensitivity_case=sensitivity_case
        ),
        hsm_electricity_mwh_per_t=_selected(energy_frame, "hsm_electricity_mwh_per_t", sensitivity_case=sensitivity_case),
        asu_electricity_mwh_per_t_o2=_selected(energy_frame, "asu_electricity_mwh_per_t_o2", sensitivity_case=sensitivity_case),
        bof_oxygen_t_per_t_bof=_selected(energy_frame, "bof_oxygen_t_per_t_liquid_steel", sensitivity_case=sensitivity_case),
        residual_auxiliary_electricity_mwh_per_t_final=_selected(
            energy_frame, "residual_auxiliary_electricity_mwh_per_t_final", sensitivity_case=sensitivity_case
        ),
        natural_gas_energy_content_gj_per_m3=_selected(
            energy_frame, "natural_gas_energy_content_gj_per_m3", sensitivity_case=sensitivity_case
        ),
        downstream_light_side_utility_heat_demand_gj_per_h=0.0,
        downstream_light_side_minimum_ng_gj_per_h=0.0,
        wag=wag,
        c1_route=c1_route,
        monetary_values_ready=monetary_ready,
        selected_prices=selected_prices,
        missing_price_inputs=missing_prices,
        complete_direct_emissions_ready=False,
        scope2_electricity_counted=False,
        ets_ready=False,
    )
