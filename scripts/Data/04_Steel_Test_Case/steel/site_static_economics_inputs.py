from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
S3_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S3"
S3_DEV_ROOT = S3_ROOT / "s3_provisional_dev_input"
S3_REVIEW_ROOT = S3_ROOT / "s3_candidate_review"
DEFAULT_S3_2_MATERIAL_INPUT_PATH = S3_DEV_ROOT / "s3_2_selected_material_inputs.csv"
DEFAULT_S3_2_STATIC_PRICE_PATH = S3_DEV_ROOT / "s3_2_selected_static_prices.csv"

S3_2_MATERIAL_COLUMNS = [
    "input_id",
    "parameter_family",
    "parameter_name",
    "asset",
    "route_scope",
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
    "zero_value_status",
    "limitations",
    "notes",
]

S3_2_PRICE_COLUMNS = [
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
    "applies_to_cost_category",
    "limitations",
    "notes",
]


class S32StaticEconomicsInputError(ValueError):
    """Raised when S3.2 governed input rows are missing or unsafe."""


@dataclass(frozen=True)
class S32MaterialAssumptions:
    coking_coal_price_eur_per_t: float
    iron_ore_sinter_feed_t_per_t_bof: float
    iron_ore_sinter_feed_price_eur_per_t: float
    bf_pellets_t_per_t_bof: float
    bf_pellets_price_eur_per_t: float
    bof_scrap_t_per_t_bof: float
    scrap_price_eur_per_t: float
    bf_bof_flux_t_per_t_bof: float
    flux_price_eur_per_t: float
    purchased_coke_t_per_t_bof: float
    purchased_coke_price_eur_per_t: float
    dr_pellets_price_eur_per_t: float
    eaf_scrap_t_per_t_eaf: float
    eaf_flux_t_per_t_eaf: float
    electrode_t_per_t_eaf: float
    electrode_price_eur_per_t: float
    bf_bof_aggregate_direct_co2_t_per_t_bof: float


@dataclass(frozen=True)
class S32StaticPriceAssumptions:
    electricity_price_eur_per_mwh: float
    natural_gas_price_eur_per_mwh_th: float
    natural_gas_price_eur_per_gj: float
    gross_co2_price_eur_per_t: float
    scope2_operational_tco2_per_mwh: float
    grid_lifecycle_tco2e_per_mwh: float
    wag_power_residual_utilisation_fraction: float


@dataclass(frozen=True)
class S32StaticEconomicsAssumptions:
    assumption_set_id: str
    sensitivity_case: str
    materials: S32MaterialAssumptions
    prices: S32StaticPriceAssumptions
    route_cost_coverage_complete: bool
    complete_direct_emissions_ready: bool
    static_cost_ready: bool
    thesis_usability: bool


def _read_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise S32StaticEconomicsInputError(f"Required S3.2 input file is missing: {path}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise S32StaticEconomicsInputError(f"{path.name} is missing columns: {missing}")
    return frame


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _numeric(value: Any, *, parameter_name: str) -> float:
    text = str(value).strip()
    if text == "":
        raise S32StaticEconomicsInputError(f"S3.2 parameter {parameter_name} has no selected value.")
    try:
        return float(text)
    except ValueError as exc:
        raise S32StaticEconomicsInputError(
            f"S3.2 parameter {parameter_name} must be numeric; got {value!r}."
        ) from exc


def _select_value(row: pd.Series, *, name: str, sensitivity_case: str) -> float:
    value_column = {
        "central": "selected_value",
        "low": "selected_lower",
        "high": "selected_upper",
    }.get(sensitivity_case)
    if value_column is None:
        raise S32StaticEconomicsInputError(f"Unsupported S3.2 sensitivity_case={sensitivity_case!r}.")
    raw = row[value_column]
    if str(raw).strip() == "":
        raw = row["selected_value"]
    return _numeric(raw, parameter_name=name)


def _validate_selected_rows(frame: pd.DataFrame, *, id_column: str, name_column: str, label: str) -> None:
    if frame[id_column].duplicated().any():
        duplicates = frame.loc[frame[id_column].duplicated(), id_column].tolist()
        raise S32StaticEconomicsInputError(f"{label} has duplicate {id_column} rows: {duplicates}")
    if frame[name_column].duplicated().any():
        duplicates = frame.loc[frame[name_column].duplicated(), name_column].tolist()
        raise S32StaticEconomicsInputError(f"{label} has duplicate {name_column} rows: {duplicates}")
    active = frame.loc[~frame["model_use_status"].isin(("blocked", "not_selected_missing"))]
    if active["tata_exact_claim_allowed"].map(_as_bool).any():
        raise S32StaticEconomicsInputError(f"{label} must not claim Tata-exact status.")
    if active["thesis_validation_claim_eligible"].map(_as_bool).any():
        raise S32StaticEconomicsInputError(f"{label} must not claim thesis-validation eligibility.")
    tier_d = active.loc[active["evidence_tier"].astype(str).str.startswith("D")]
    if not tier_d.empty and (~tier_d["sensitivity_required"].map(_as_bool)).any():
        ids = tier_d.loc[~tier_d["sensitivity_required"].map(_as_bool), id_column].tolist()
        raise S32StaticEconomicsInputError(f"Tier-D {label} rows require sensitivity: {ids}")


def _row(frame: pd.DataFrame, parameter_name: str) -> pd.Series:
    selected = frame.loc[frame["parameter_name"].eq(parameter_name)]
    if selected.empty:
        raise S32StaticEconomicsInputError(f"Missing S3.2 material input {parameter_name!r}.")
    return selected.iloc[0]


def _price_row(frame: pd.DataFrame, price_name: str) -> pd.Series:
    selected = frame.loc[frame["price_name"].eq(price_name)]
    if selected.empty:
        raise S32StaticEconomicsInputError(f"Missing S3.2 static price input {price_name!r}.")
    return selected.iloc[0]


def _material(frame: pd.DataFrame, parameter_name: str, *, sensitivity_case: str) -> float:
    return _select_value(_row(frame, parameter_name), name=parameter_name, sensitivity_case=sensitivity_case)


def _price(frame: pd.DataFrame, price_name: str, *, sensitivity_case: str) -> float:
    return _select_value(_price_row(frame, price_name), name=price_name, sensitivity_case=sensitivity_case)


def load_s3_2_static_economics_assumptions(
    *,
    sensitivity_case: str = "central",
    material_input_path: str | Path = DEFAULT_S3_2_MATERIAL_INPUT_PATH,
    static_price_path: str | Path = DEFAULT_S3_2_STATIC_PRICE_PATH,
) -> S32StaticEconomicsAssumptions:
    materials_frame = _read_csv(Path(material_input_path), S3_2_MATERIAL_COLUMNS)
    prices_frame = _read_csv(Path(static_price_path), S3_2_PRICE_COLUMNS)
    _validate_selected_rows(
        materials_frame,
        id_column="input_id",
        name_column="parameter_name",
        label="S3.2 material inputs",
    )
    _validate_selected_rows(
        prices_frame,
        id_column="price_input_id",
        name_column="price_name",
        label="S3.2 static prices",
    )

    materials = S32MaterialAssumptions(
        coking_coal_price_eur_per_t=_material(materials_frame, "coking_coal_price_eur_per_t", sensitivity_case=sensitivity_case),
        iron_ore_sinter_feed_t_per_t_bof=_material(materials_frame, "iron_ore_sinter_feed_t_per_t_bof", sensitivity_case=sensitivity_case),
        iron_ore_sinter_feed_price_eur_per_t=_material(materials_frame, "iron_ore_sinter_feed_price_eur_per_t", sensitivity_case=sensitivity_case),
        bf_pellets_t_per_t_bof=_material(materials_frame, "bf_pellets_t_per_t_bof", sensitivity_case=sensitivity_case),
        bf_pellets_price_eur_per_t=_material(materials_frame, "bf_pellets_price_eur_per_t", sensitivity_case=sensitivity_case),
        bof_scrap_t_per_t_bof=_material(materials_frame, "bof_scrap_t_per_t_bof", sensitivity_case=sensitivity_case),
        scrap_price_eur_per_t=_material(materials_frame, "scrap_price_eur_per_t", sensitivity_case=sensitivity_case),
        bf_bof_flux_t_per_t_bof=_material(materials_frame, "bf_bof_flux_t_per_t_bof", sensitivity_case=sensitivity_case),
        flux_price_eur_per_t=_material(materials_frame, "flux_price_eur_per_t", sensitivity_case=sensitivity_case),
        purchased_coke_t_per_t_bof=_material(materials_frame, "purchased_coke_t_per_t_bof", sensitivity_case=sensitivity_case),
        purchased_coke_price_eur_per_t=_material(materials_frame, "purchased_coke_price_eur_per_t", sensitivity_case=sensitivity_case),
        dr_pellets_price_eur_per_t=_material(materials_frame, "dr_pellets_price_eur_per_t", sensitivity_case=sensitivity_case),
        eaf_scrap_t_per_t_eaf=_material(materials_frame, "eaf_scrap_t_per_t_eaf", sensitivity_case=sensitivity_case),
        eaf_flux_t_per_t_eaf=_material(materials_frame, "eaf_flux_t_per_t_eaf", sensitivity_case=sensitivity_case),
        electrode_t_per_t_eaf=_material(materials_frame, "electrode_t_per_t_eaf", sensitivity_case=sensitivity_case),
        electrode_price_eur_per_t=_material(materials_frame, "electrode_price_eur_per_t", sensitivity_case=sensitivity_case),
        bf_bof_aggregate_direct_co2_t_per_t_bof=_material(
            materials_frame,
            "bf_bof_aggregate_direct_co2_t_per_t_bof",
            sensitivity_case=sensitivity_case,
        ),
    )
    prices = S32StaticPriceAssumptions(
        electricity_price_eur_per_mwh=_price(prices_frame, "grid_electricity_price_eur_per_mwh", sensitivity_case=sensitivity_case),
        natural_gas_price_eur_per_mwh_th=_price(prices_frame, "natural_gas_price_eur_per_mwh_th", sensitivity_case=sensitivity_case),
        natural_gas_price_eur_per_gj=_price(prices_frame, "natural_gas_price_eur_per_gj", sensitivity_case=sensitivity_case),
        gross_co2_price_eur_per_t=_price(prices_frame, "gross_co2_price_eur_per_t", sensitivity_case=sensitivity_case),
        scope2_operational_tco2_per_mwh=_price(prices_frame, "scope2_operational_tco2_per_mwh", sensitivity_case=sensitivity_case),
        grid_lifecycle_tco2e_per_mwh=_price(prices_frame, "grid_lifecycle_tco2e_per_mwh", sensitivity_case=sensitivity_case),
        wag_power_residual_utilisation_fraction=_price(
            prices_frame,
            "wag_power_residual_utilisation_fraction",
            sensitivity_case=sensitivity_case,
        ),
    )
    return S32StaticEconomicsAssumptions(
        assumption_set_id="S3_2_STATIC_MATERIAL_ENERGY_CARBON_ECONOMICS_CENTRAL_DEV",
        sensitivity_case=sensitivity_case,
        materials=materials,
        prices=prices,
        route_cost_coverage_complete=True,
        complete_direct_emissions_ready=True,
        static_cost_ready=True,
        thesis_usability=False,
    )
