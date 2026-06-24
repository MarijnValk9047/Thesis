from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SELECTED_WAG_INPUT_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_provisional_dev_input"
    / "s3_wag_selected_dev_inputs.csv"
)
DEFAULT_WAG_DEMAND_COEFFICIENT_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_provisional_dev_input"
    / "s3_wag_demand_coefficients.csv"
)

SELECTED_WAG_INPUT_COLUMNS = [
    "input_id",
    "parameter_family",
    "parameter_name",
    "carrier",
    "configuration_id",
    "linked_activity_or_node",
    "selected_value",
    "unit",
    "activity_basis",
    "energy_basis",
    "selected_lower",
    "selected_upper",
    "selection_method",
    "source_card_ids",
    "candidate_evidence_ids",
    "development_only",
    "approval_status",
    "accepted_for_dev_use",
    "eligible_for_s3_0b_loader",
    "currently_loaded",
    "sensitivity_required",
    "sensitivity_group",
    "thesis_usability",
    "limitations",
    "notes",
]

PROFILE_REQUIRED_COLUMNS = [
    "profile_package_id",
    "profile_row_id",
    "configuration_id",
    "scenario_label",
    "time_index",
    "timestamp_utc",
    "timestep_hours",
    "s2_activity_id",
    "s2_activity_type",
    "activity_value",
    "activity_unit",
    "activity_direction",
    "source_stage",
    "source_artifact_id",
    "source_artifact_path",
    "source_artifact_hash",
    "profile_extraction_method",
    "review_status",
    "thesis_usability",
]

WAG_DEMAND_COEFFICIENT_COLUMNS = [
    "demand_input_id",
    "demand_family",
    "demand_name",
    "configuration_id",
    "linked_activity_id",
    "eligible_carriers",
    "selected_value",
    "unit",
    "activity_basis",
    "energy_basis",
    "selected_lower",
    "selected_upper",
    "selection_method",
    "source_card_ids",
    "candidate_evidence_ids",
    "development_only",
    "accepted_for_dev_use",
    "eligible_for_s3_0b_loader",
    "sensitivity_required",
    "sensitivity_group",
    "thesis_usability",
    "limitations",
    "notes",
]

SUPPORTED_SELECTED_UNITS = {
    "Nm3/t_hot_metal",
    "MJ/Nm3",
    "Nm3/t_liquid_steel",
    "m3/t_dry_coal",
    "kg CO2/GJ",
    "% net_electric_efficiency",
    "dimensionless_efficiency",
    "accounting_rule",
    "t_coke/t_hot_metal",
    "t_dry_coal/t_coke",
    "t_coke/year",
    "MWh/year",
}

SUPPORTED_PROFILE_UNITS = {
    "t_per_hour",
    "tonnes",
    "timestep_total_tonnes",
    "MWh",
    "GJ",
    "GJ_useful",
    "MW",
    "m3_NG_per_hour",
    "t_CO2_per_hour",
}


class WAGInputError(ValueError):
    """Raised when governed WAG input surfaces violate loader policy."""


@dataclass(frozen=True)
class SelectedWAGInput:
    input_id: str
    parameter_family: str
    parameter_name: str
    carrier: str
    configuration_id: str
    linked_activity_or_node: str
    selected_value: str
    selected_number: float | None
    unit: str
    activity_basis: str
    energy_basis: str
    selected_lower: str
    selected_upper: str
    selection_method: str
    source_card_ids: tuple[str, ...]
    candidate_evidence_ids: tuple[str, ...]
    sensitivity_required: bool
    sensitivity_group: str
    limitations: str
    notes: str


@dataclass(frozen=True)
class FixedActivityProfileRow:
    profile_package_id: str
    profile_row_id: str
    configuration_id: str
    scenario_label: str
    time_index: int
    timestamp_utc: pd.Timestamp
    timestep_hours: float
    s2_activity_id: str
    s2_activity_type: str
    activity_value: float
    activity_unit: str
    activity_direction: str
    source_stage: str
    source_artifact_id: str
    source_artifact_path: str
    source_artifact_hash: str
    profile_extraction_method: str
    review_status: str
    thesis_usability: bool


@dataclass(frozen=True)
class WAGDemandCoefficient:
    demand_input_id: str
    demand_family: str
    demand_name: str
    configuration_id: str
    linked_activity_id: str
    eligible_carriers: tuple[str, ...]
    selected_value: float
    unit: str
    activity_basis: str
    energy_basis: str
    selected_lower: str
    selected_upper: str
    selection_method: str
    source_card_ids: tuple[str, ...]
    candidate_evidence_ids: tuple[str, ...]
    sensitivity_required: bool
    sensitivity_group: str
    limitations: str
    notes: str


def parse_bool(value: Any, *, field_name: str) -> bool:
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    raise WAGInputError(f"{field_name} must be a strict true/false value, got {value!r}.")


def _split_ids(value: Any) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value).split(";") if part.strip())


def _parse_optional_float(value: Any) -> float | None:
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _reject_generated_run_path(path: Path) -> None:
    lowered_parts = {part.lower() for part in path.parts}
    if "runs" in lowered_parts:
        raise WAGInputError("Generated run folders are not accepted as canonical WAG inputs.")


def load_selected_wag_inputs(
    path: str | Path = DEFAULT_SELECTED_WAG_INPUT_PATH,
) -> dict[tuple[str, str, str, str], SelectedWAGInput]:
    input_path = Path(path)
    _reject_generated_run_path(input_path)
    if input_path.name != "s3_wag_selected_dev_inputs.csv":
        raise WAGInputError("The WAG loader accepts only s3_wag_selected_dev_inputs.csv, not review surfaces.")
    frame = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    if list(frame.columns) != SELECTED_WAG_INPUT_COLUMNS:
        raise WAGInputError("Selected WAG input CSV has unexpected columns or column order.")

    loaded: dict[tuple[str, str, str, str], SelectedWAGInput] = {}
    for row_index, row in frame.iterrows():
        if not parse_bool(row["development_only"], field_name="development_only"):
            raise WAGInputError(f"Row {row_index} is not development_only=true.")
        if not parse_bool(row["accepted_for_dev_use"], field_name="accepted_for_dev_use"):
            raise WAGInputError(f"Row {row_index} is not accepted_for_dev_use=true.")
        if not parse_bool(row["eligible_for_s3_0b_loader"], field_name="eligible_for_s3_0b_loader"):
            raise WAGInputError(f"Row {row_index} is not eligible_for_s3_0b_loader=true.")
        if parse_bool(row["thesis_usability"], field_name="thesis_usability"):
            raise WAGInputError(f"Row {row_index} is thesis-usable and cannot be loaded.")
        if str(row["approval_status"]).strip() != "accepted_for_development_only":
            raise WAGInputError(f"Row {row_index} has unsupported approval_status.")
        if str(row["selected_value"]).strip() == "":
            raise WAGInputError(f"Row {row_index} has no selected_value.")
        if str(row["unit"]).strip() == "":
            raise WAGInputError(f"Row {row_index} has no unit.")
        if row["unit"] not in SUPPORTED_SELECTED_UNITS:
            raise WAGInputError(f"Row {row_index} uses unsupported unit {row['unit']!r}.")
        source_ids = _split_ids(row["source_card_ids"])
        if "STEEL-SC-0019" in source_ids:
            raise WAGInputError("STEEL-SC-0019 is locator-incomplete and cannot feed selected WAG inputs.")
        if not source_ids or not _split_ids(row["candidate_evidence_ids"]):
            raise WAGInputError(f"Row {row_index} must reference source and candidate evidence IDs.")

        key = (
            str(row["configuration_id"]).strip(),
            str(row["carrier"]).strip(),
            str(row["linked_activity_or_node"]).strip(),
            str(row["parameter_name"]).strip(),
        )
        if key in loaded:
            raise WAGInputError(f"Duplicate effective selected-input key: {key}.")
        loaded[key] = SelectedWAGInput(
            input_id=str(row["input_id"]).strip(),
            parameter_family=str(row["parameter_family"]).strip(),
            parameter_name=key[3],
            carrier=key[1],
            configuration_id=key[0],
            linked_activity_or_node=key[2],
            selected_value=str(row["selected_value"]).strip(),
            selected_number=_parse_optional_float(row["selected_value"]),
            unit=str(row["unit"]).strip(),
            activity_basis=str(row["activity_basis"]).strip(),
            energy_basis=str(row["energy_basis"]).strip(),
            selected_lower=str(row["selected_lower"]).strip(),
            selected_upper=str(row["selected_upper"]).strip(),
            selection_method=str(row["selection_method"]).strip(),
            source_card_ids=source_ids,
            candidate_evidence_ids=_split_ids(row["candidate_evidence_ids"]),
            sensitivity_required=parse_bool(row["sensitivity_required"], field_name="sensitivity_required"),
            sensitivity_group=str(row["sensitivity_group"]).strip(),
            limitations=str(row["limitations"]).strip(),
            notes=str(row["notes"]).strip(),
        )
    return loaded


def load_fixed_activity_profile(path: str | Path) -> list[FixedActivityProfileRow]:
    profile_path = Path(path)
    _reject_generated_run_path(profile_path)
    frame = pd.read_csv(profile_path, dtype=str, keep_default_na=False)
    missing_columns = [column for column in PROFILE_REQUIRED_COLUMNS if column not in frame.columns]
    if missing_columns:
        raise WAGInputError(f"Fixed activity profile is missing required columns: {missing_columns}.")

    rows: list[FixedActivityProfileRow] = []
    seen: set[tuple[str, str]] = set()
    for row_index, row in frame.iterrows():
        key = (str(row["profile_package_id"]).strip(), str(row["profile_row_id"]).strip())
        if key in seen:
            raise WAGInputError(f"Duplicate fixed-profile row key: {key}.")
        seen.add(key)
        thesis_usability = parse_bool(row["thesis_usability"], field_name="thesis_usability")
        if thesis_usability:
            raise WAGInputError(f"Profile row {row_index} is thesis-usable and cannot be used as a dev fixture.")
        if row["activity_unit"] not in SUPPORTED_PROFILE_UNITS:
            raise WAGInputError(f"Profile row {row_index} has unsupported activity_unit {row['activity_unit']!r}.")
        if "runs" in str(row["source_artifact_path"]).lower().replace("\\", "/").split("/"):
            raise WAGInputError("Generated run-folder artifacts are not canonical fixed-profile inputs.")
        timestamp = pd.Timestamp(str(row["timestamp_utc"]).strip())
        if timestamp.tzinfo is None or timestamp.tz_convert("UTC") != timestamp:
            raise WAGInputError(f"Profile row {row_index} timestamp_utc must be timezone-aware UTC.")
        timestep_hours = float(row["timestep_hours"])
        if timestep_hours <= 0:
            raise WAGInputError(f"Profile row {row_index} timestep_hours must be positive.")
        rows.append(
            FixedActivityProfileRow(
                profile_package_id=key[0],
                profile_row_id=key[1],
                configuration_id=str(row["configuration_id"]).strip(),
                scenario_label=str(row["scenario_label"]).strip(),
                time_index=int(row["time_index"]),
                timestamp_utc=timestamp,
                timestep_hours=timestep_hours,
                s2_activity_id=str(row["s2_activity_id"]).strip(),
                s2_activity_type=str(row["s2_activity_type"]).strip(),
                activity_value=float(row["activity_value"]),
                activity_unit=str(row["activity_unit"]).strip(),
                activity_direction=str(row["activity_direction"]).strip(),
                source_stage=str(row["source_stage"]).strip(),
                source_artifact_id=str(row["source_artifact_id"]).strip(),
                source_artifact_path=str(row["source_artifact_path"]).strip(),
                source_artifact_hash=str(row["source_artifact_hash"]).strip(),
                profile_extraction_method=str(row["profile_extraction_method"]).strip(),
                review_status=str(row["review_status"]).strip(),
                thesis_usability=thesis_usability,
            )
        )
    return rows


def load_wag_demand_coefficients(
    path: str | Path = DEFAULT_WAG_DEMAND_COEFFICIENT_PATH,
) -> dict[tuple[str, str, str], WAGDemandCoefficient]:
    demand_path = Path(path)
    _reject_generated_run_path(demand_path)
    if demand_path.name != "s3_wag_demand_coefficients.csv":
        raise WAGInputError("The WAG demand loader accepts only s3_wag_demand_coefficients.csv.")
    frame = pd.read_csv(demand_path, dtype=str, keep_default_na=False)
    if list(frame.columns) != WAG_DEMAND_COEFFICIENT_COLUMNS:
        raise WAGInputError("WAG demand coefficient CSV has unexpected columns or column order.")

    loaded: dict[tuple[str, str, str], WAGDemandCoefficient] = {}
    for row_index, row in frame.iterrows():
        if not parse_bool(row["development_only"], field_name="development_only"):
            raise WAGInputError(f"Demand row {row_index} is not development_only=true.")
        if not parse_bool(row["accepted_for_dev_use"], field_name="accepted_for_dev_use"):
            raise WAGInputError(f"Demand row {row_index} is not accepted_for_dev_use=true.")
        if not parse_bool(row["eligible_for_s3_0b_loader"], field_name="eligible_for_s3_0b_loader"):
            raise WAGInputError(f"Demand row {row_index} is not eligible_for_s3_0b_loader=true.")
        if parse_bool(row["thesis_usability"], field_name="thesis_usability"):
            raise WAGInputError(f"Demand row {row_index} is thesis-usable and cannot be loaded.")
        if str(row["selected_value"]).strip() == "" or str(row["unit"]).strip() == "":
            raise WAGInputError(f"Demand row {row_index} must carry selected_value and unit.")
        source_ids = _split_ids(row["source_card_ids"])
        candidate_ids = _split_ids(row["candidate_evidence_ids"])
        if "STEEL-SC-0019" in source_ids:
            raise WAGInputError("STEEL-SC-0019 is locator-incomplete and cannot feed demand coefficients.")
        if not source_ids or not candidate_ids:
            raise WAGInputError(f"Demand row {row_index} must reference source and candidate evidence IDs.")
        key = (
            str(row["configuration_id"]).strip(),
            str(row["linked_activity_id"]).strip(),
            str(row["demand_name"]).strip(),
        )
        if key in loaded:
            raise WAGInputError(f"Duplicate effective demand coefficient key: {key}.")
        loaded[key] = WAGDemandCoefficient(
            demand_input_id=str(row["demand_input_id"]).strip(),
            demand_family=str(row["demand_family"]).strip(),
            demand_name=key[2],
            configuration_id=key[0],
            linked_activity_id=key[1],
            eligible_carriers=_split_ids(str(row["eligible_carriers"]).replace("|", ";")),
            selected_value=float(row["selected_value"]),
            unit=str(row["unit"]).strip(),
            activity_basis=str(row["activity_basis"]).strip(),
            energy_basis=str(row["energy_basis"]).strip(),
            selected_lower=str(row["selected_lower"]).strip(),
            selected_upper=str(row["selected_upper"]).strip(),
            selection_method=str(row["selection_method"]).strip(),
            source_card_ids=source_ids,
            candidate_evidence_ids=candidate_ids,
            sensitivity_required=parse_bool(row["sensitivity_required"], field_name="sensitivity_required"),
            sensitivity_group=str(row["sensitivity_group"]).strip(),
            limitations=str(row["limitations"]).strip(),
            notes=str(row["notes"]).strip(),
        )
    return loaded
