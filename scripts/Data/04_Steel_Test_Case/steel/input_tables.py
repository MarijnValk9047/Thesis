from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


METADATA_COLUMNS = [
    "input_id",
    "source_status",
    "approval_status",
    "intended_use",
    "scenario_or_config",
    "notes",
]
ALLOWED_INPUT_MODES = {
    "toy_scaffold",
    "candidate_review",
    "approved_model_input",
}
ALLOWED_SOURCE_STATUS = {
    "toy_scaffold",
    "candidate_not_approved",
    "validation_only",
    "sensitivity_only",
    "approved_model_input",
    "approved_later",
}
ALLOWED_APPROVAL_STATUS = {
    "not_approved",
    "candidate_not_approved",
    "validation_only",
    "sensitivity_only",
    "approved_model_input",
    "approved_later",
}
APPROVED_INPUT_APPROVAL_STATUSES = {"approved_model_input"}
FORBIDDEN_COLUMN_TOKENS = (
    "mfrr",
    "cvar",
    "emission",
    "tariff",
    "revenue",
    "da_price",
    "scenario_probability",
    "wag",
)

TABLE_SPECS: dict[str, dict[str, Any]] = {
    "carriers": {
        "file": "carriers_toy.csv",
        "required_columns": ["carrier_id", "description", "default_unit"],
        "key_columns": ["carrier_id"],
    },
    "process_units": {
        "file": "process_units_toy.csv",
        "required_columns": [
            "process_id",
            "route",
            "capacity_min_tph",
            "capacity_max_tph",
            "operating_cost_per_tonne",
            "throughput_unit",
            "cost_unit",
        ],
        "key_columns": ["process_id"],
    },
    "conversion_coefficients": {
        "file": "conversion_coefficients_toy.csv",
        "required_columns": ["process_id", "carrier_id", "coefficient", "unit"],
        "key_columns": ["process_id", "carrier_id"],
    },
    "sources": {
        "file": "sources_toy.csv",
        "required_columns": [
            "source_id",
            "carrier_id",
            "unit_cost_per_tonne",
            "max_supply_tph",
            "supply_unit",
            "cost_unit",
        ],
        "key_columns": ["source_id"],
    },
    "sinks": {
        "file": "sinks_toy.csv",
        "required_columns": ["sink_id", "carrier_id", "description"],
        "key_columns": ["sink_id"],
    },
    "stores": {
        "file": "stores_toy.csv",
        "required_columns": [
            "store_id",
            "carrier_id",
            "capacity_tonnes",
            "charge_max_tph",
            "discharge_max_tph",
            "throughput_cost_per_tonne",
            "anti_free_battery",
            "capacity_unit",
            "throughput_unit",
            "cost_unit",
        ],
        "key_columns": ["store_id"],
    },
    "initial_inventories": {
        "file": "initial_inventories_toy.csv",
        "required_columns": ["store_id", "initial_inventory_tonnes", "unit"],
        "key_columns": ["store_id"],
    },
    "terminal_inventory_rules": {
        "file": "terminal_inventory_rules_toy.csv",
        "required_columns": ["store_id", "terminal_min_tonnes", "terminal_max_tonnes", "unit"],
        "key_columns": ["store_id"],
    },
    "production_targets": {
        "file": "production_targets_toy.csv",
        "required_columns": ["target_id", "sink_id", "carrier_id", "total_tonnes", "unit"],
        "key_columns": ["target_id"],
    },
}

NUMERIC_COLUMNS = {
    "process_units": ["capacity_min_tph", "capacity_max_tph", "operating_cost_per_tonne"],
    "conversion_coefficients": ["coefficient"],
    "sources": ["unit_cost_per_tonne", "max_supply_tph"],
    "stores": ["capacity_tonnes", "charge_max_tph", "discharge_max_tph", "throughput_cost_per_tonne"],
    "initial_inventories": ["initial_inventory_tonnes"],
    "terminal_inventory_rules": ["terminal_min_tonnes", "terminal_max_tonnes"],
    "production_targets": ["total_tonnes"],
}


@dataclass(frozen=True)
class GovernedToyTables:
    table_root: Path
    scenario_or_config: str
    tables: dict[str, pd.DataFrame]
    table_paths: dict[str, Path]

    @property
    def row_counts(self) -> dict[str, int]:
        return {name: int(len(frame)) for name, frame in self.tables.items()}


@dataclass(frozen=True)
class InputGovernanceSummary:
    input_mode: str
    contains_toy_values: bool
    contains_candidate_not_approved_values: bool
    contains_validation_only_values: bool
    contains_sensitivity_only_values: bool
    all_required_inputs_approved: bool
    thesis_usable: bool
    thesis_usability_reason: str


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _ensure_required_columns(frame: pd.DataFrame, table_name: str, required_columns: list[str]) -> None:
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{table_name} is missing required columns: {missing}")


def _ensure_no_forbidden_columns(frame: pd.DataFrame, table_name: str) -> None:
    lower_columns = [column.lower() for column in frame.columns]
    bad = [column for column in lower_columns if any(token in column for token in FORBIDDEN_COLUMN_TOKENS)]
    if bad:
        raise ValueError(f"{table_name} contains forbidden S3/DA/stochastic column names: {bad}")


def _filter_scenario_rows(frame: pd.DataFrame, scenario_or_config: str, table_name: str) -> pd.DataFrame:
    filtered = frame[frame["scenario_or_config"] == scenario_or_config].copy()
    if filtered.empty:
        raise ValueError(f"{table_name} has no rows for scenario_or_config={scenario_or_config}.")
    return filtered


def _ensure_non_empty(frame: pd.DataFrame, table_name: str, columns: list[str]) -> None:
    for column in columns:
        if frame[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"{table_name} contains empty values in required column {column}.")


def _ensure_allowed_statuses(frame: pd.DataFrame, table_name: str) -> None:
    source_values = set(frame["source_status"].astype(str).str.strip())
    approval_values = set(frame["approval_status"].astype(str).str.strip())
    if not source_values.issubset(ALLOWED_SOURCE_STATUS):
        raise ValueError(f"{table_name} has unsupported source_status values: {sorted(source_values - ALLOWED_SOURCE_STATUS)}")
    if not approval_values.issubset(ALLOWED_APPROVAL_STATUS):
        raise ValueError(f"{table_name} has unsupported approval_status values: {sorted(approval_values - ALLOWED_APPROVAL_STATUS)}")


def _coerce_columns(frame: pd.DataFrame, table_name: str) -> pd.DataFrame:
    coerced = frame.copy()
    for column in NUMERIC_COLUMNS.get(table_name, []):
        coerced[column] = pd.to_numeric(coerced[column], errors="raise")
    if table_name == "stores":
        coerced["anti_free_battery"] = (
            coerced["anti_free_battery"].astype(str).str.strip().str.lower().map({"true": True, "false": False})
        )
        if coerced["anti_free_battery"].isna().any():
            raise ValueError("stores contains invalid anti_free_battery values.")
    return coerced


def _ensure_unique_keys(frame: pd.DataFrame, table_name: str, key_columns: list[str]) -> None:
    if frame.duplicated(subset=key_columns).any():
        duplicates = frame.loc[frame.duplicated(subset=key_columns, keep=False), key_columns]
        raise ValueError(f"{table_name} contains duplicate keys: {duplicates.to_dict(orient='records')}")


def _validate_references(tables: dict[str, pd.DataFrame]) -> None:
    carriers = set(tables["carriers"]["carrier_id"])
    processes = set(tables["process_units"]["process_id"])
    stores = set(tables["stores"]["store_id"])
    sinks = set(tables["sinks"]["sink_id"])

    for table_name in ("sources", "sinks", "stores", "conversion_coefficients", "production_targets"):
        if "carrier_id" in tables[table_name].columns:
            unknown = set(tables[table_name]["carrier_id"]) - carriers
            if unknown:
                raise ValueError(f"{table_name} references unknown carriers: {sorted(unknown)}")

    unknown_processes = set(tables["conversion_coefficients"]["process_id"]) - processes
    if unknown_processes:
        raise ValueError(f"conversion_coefficients references unknown processes: {sorted(unknown_processes)}")

    unknown_initial = set(tables["initial_inventories"]["store_id"]) - stores
    unknown_terminal = set(tables["terminal_inventory_rules"]["store_id"]) - stores
    if unknown_initial:
        raise ValueError(f"initial_inventories references unknown stores: {sorted(unknown_initial)}")
    if unknown_terminal:
        raise ValueError(f"terminal_inventory_rules references unknown stores: {sorted(unknown_terminal)}")

    unknown_target_sinks = set(tables["production_targets"]["sink_id"]) - sinks
    if unknown_target_sinks:
        raise ValueError(f"production_targets references unknown sinks: {sorted(unknown_target_sinks)}")


def _validate_input_mode(input_mode: str) -> None:
    if input_mode not in ALLOWED_INPUT_MODES:
        raise ValueError(f"Unsupported input_mode={input_mode}. Allowed modes: {sorted(ALLOWED_INPUT_MODES)}")


def _collect_input_governance_summary(tables: dict[str, pd.DataFrame], input_mode: str) -> InputGovernanceSummary:
    _validate_input_mode(input_mode)
    source_statuses = {
        str(value).strip()
        for frame in tables.values()
        for value in frame["source_status"].tolist()
    }
    approval_statuses = {
        str(value).strip()
        for frame in tables.values()
        for value in frame["approval_status"].tolist()
    }

    contains_toy_values = "toy_scaffold" in source_statuses
    contains_candidate_not_approved_values = (
        "candidate_not_approved" in source_statuses or "candidate_not_approved" in approval_statuses
    )
    contains_validation_only_values = (
        "validation_only" in source_statuses or "validation_only" in approval_statuses
    )
    contains_sensitivity_only_values = (
        "sensitivity_only" in source_statuses or "sensitivity_only" in approval_statuses
    )
    all_required_inputs_approved = approval_statuses.issubset(APPROVED_INPUT_APPROVAL_STATUSES)

    if input_mode == "toy_scaffold":
        if not contains_toy_values:
            raise ValueError("toy_scaffold mode requires toy_scaffold source_status rows.")
        thesis_usable = False
        thesis_reason = (
            "toy_scaffold mode uses scaffold values only; runs remain non-thesis-usable structural evidence."
        )
    elif input_mode == "candidate_review":
        thesis_usable = False
        thesis_reason = (
            "candidate_review mode is structural validation only; candidate, toy, validation-only, and not-approved values are not thesis-usable."
        )
    else:
        disallowed_approval = sorted(approval_statuses - APPROVED_INPUT_APPROVAL_STATUSES)
        if disallowed_approval:
            raise ValueError(
                "approved_model_input mode requires every executable row to be approval_status=approved_model_input. "
                f"Found non-approved statuses: {disallowed_approval}"
            )
        if contains_toy_values or contains_candidate_not_approved_values or contains_validation_only_values or contains_sensitivity_only_values:
            raise ValueError(
                "approved_model_input mode cannot include toy_scaffold, candidate_not_approved, validation_only, or sensitivity_only rows."
            )
        thesis_usable = True
        thesis_reason = "All required executable input rows are approved_model_input."

    return InputGovernanceSummary(
        input_mode=input_mode,
        contains_toy_values=contains_toy_values,
        contains_candidate_not_approved_values=contains_candidate_not_approved_values,
        contains_validation_only_values=contains_validation_only_values,
        contains_sensitivity_only_values=contains_sensitivity_only_values,
        all_required_inputs_approved=all_required_inputs_approved,
        thesis_usable=thesis_usable,
        thesis_usability_reason=thesis_reason,
    )


def load_governed_toy_tables(table_root: str | Path, scenario_or_config: str, *, input_mode: str) -> GovernedToyTables:
    root = Path(table_root).resolve()
    tables: dict[str, pd.DataFrame] = {}
    table_paths: dict[str, Path] = {}
    for table_name, spec in TABLE_SPECS.items():
        path = root / spec["file"]
        frame = _read_csv(path)
        _ensure_required_columns(frame, table_name, METADATA_COLUMNS + spec["required_columns"])
        _ensure_no_forbidden_columns(frame, table_name)
        frame = _filter_scenario_rows(frame, scenario_or_config, table_name)
        _ensure_non_empty(frame, table_name, METADATA_COLUMNS + spec["required_columns"])
        _ensure_allowed_statuses(frame, table_name)
        frame = _coerce_columns(frame, table_name)
        _ensure_unique_keys(frame, table_name, spec["key_columns"])
        tables[table_name] = frame
        table_paths[table_name] = path

    _validate_references(tables)
    _collect_input_governance_summary(tables, input_mode)
    return GovernedToyTables(
        table_root=root,
        scenario_or_config=scenario_or_config,
        tables=tables,
        table_paths=table_paths,
    )


def summarize_input_governance(tables: dict[str, pd.DataFrame], *, input_mode: str) -> InputGovernanceSummary:
    return _collect_input_governance_summary(tables, input_mode)
