from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


SCHEMA_FILE_SPECS: dict[str, list[str]] = {
    "process_units_schema.csv": ["table_name", "column_name", "data_type", "required", "field_role", "notes"],
    "carriers_schema.csv": ["table_name", "column_name", "data_type", "required", "field_role", "notes"],
    "stores_schema.csv": ["table_name", "column_name", "data_type", "required", "field_role", "notes"],
    "conversion_coefficients_schema.csv": ["table_name", "column_name", "data_type", "required", "field_role", "notes"],
    "process_bounds_schema.csv": ["table_name", "column_name", "data_type", "required", "field_role", "notes"],
    "production_targets_schema.csv": ["table_name", "column_name", "data_type", "required", "field_role", "notes"],
    "initial_inventories_schema.csv": ["table_name", "column_name", "data_type", "required", "field_role", "notes"],
    "terminal_inventory_rules_schema.csv": ["table_name", "column_name", "data_type", "required", "field_role", "notes"],
    "topology_routes_schema.csv": ["table_name", "column_name", "data_type", "required", "field_role", "notes"],
    "validation_targets_schema.csv": ["table_name", "column_name", "data_type", "required", "field_role", "notes"],
}

MAPPING_FILE_SPECS: dict[str, list[str]] = {
    "s2_required_input_categories.csv": [
        "category_id",
        "category_name",
        "future_table",
        "s2_use_class",
        "review_status_required",
        "missing_before_approval",
        "notes",
    ],
    "s2_candidate_to_schema_mapping.csv": [
        "mapping_id",
        "candidate_category",
        "candidate_file",
        "future_table",
        "future_field_group",
        "s2_use_class",
        "review_status_required",
        "missing_before_approval",
        "notes",
    ],
    "s2_validation_target_mapping.csv": [
        "mapping_id",
        "validation_category",
        "candidate_file",
        "validation_table",
        "may_drive_constraints",
        "review_status_required",
        "notes",
    ],
    "s2_postponed_categories.csv": [
        "category_id",
        "category_name",
        "candidate_file",
        "postponed_until",
        "reason",
        "notes",
    ],
}


@dataclass(frozen=True)
class GovernanceTableBundle:
    root: Path
    tables: dict[str, pd.DataFrame]

    @property
    def row_counts(self) -> dict[str, int]:
        return {name: int(len(frame)) for name, frame in self.tables.items()}


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _load_bundle(root: str | Path, file_specs: dict[str, list[str]]) -> GovernanceTableBundle:
    base = Path(root).resolve()
    tables: dict[str, pd.DataFrame] = {}
    for filename, required_columns in file_specs.items():
        path = base / filename
        frame = _read_csv(path)
        missing = [column for column in required_columns if column not in frame.columns]
        if missing:
            raise ValueError(f"{filename} is missing required columns: {missing}")
        if frame.empty:
            raise ValueError(f"{filename} must contain at least one schema or mapping row.")
        for column in required_columns:
            if frame[column].astype(str).str.strip().eq("").any():
                raise ValueError(f"{filename} contains empty values in required column {column}.")
        tables[filename] = frame
    return GovernanceTableBundle(root=base, tables=tables)


def load_s2_schema(schema_root: str | Path) -> GovernanceTableBundle:
    return _load_bundle(schema_root, SCHEMA_FILE_SPECS)


def load_s2_candidate_mapping(mapping_root: str | Path) -> GovernanceTableBundle:
    return _load_bundle(mapping_root, MAPPING_FILE_SPECS)


def dry_run_validate_input_governance(
    *,
    config,
    schema_bundle: GovernanceTableBundle,
    mapping_bundle: GovernanceTableBundle,
) -> dict[str, Any]:
    return {
        "input_mode": config.input_governance.input_mode,
        "schema_files_checked": len(schema_bundle.tables),
        "mapping_files_checked": len(mapping_bundle.tables),
        "contains_toy_values": config.input_governance.contains_toy_values,
        "contains_candidate_not_approved_values": config.input_governance.contains_candidate_not_approved_values,
        "contains_validation_only_values": config.input_governance.contains_validation_only_values,
        "all_required_inputs_approved": config.input_governance.all_required_inputs_approved,
        "thesis_usable": config.input_governance.thesis_usable,
        "thesis_usability_reason": config.input_governance.thesis_usability_reason,
    }
