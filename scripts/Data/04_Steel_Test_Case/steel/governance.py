from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
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

COMMON_REVIEW_COLUMNS = [
    "input_id",
    "input_value_raw",
    "input_unit_raw",
    "target_unit",
    "unit_conversion_needed",
    "hourly_cap_guard",
    "sign_convention",
    "sign_check_status",
    "unit_check_status",
    "source_id",
    "source_class",
    "candidate_source_file",
    "evidence_quality",
    "public_reportability",
    "source_status",
    "approval_status",
    "intended_use",
    "required_phase",
    "review_status",
    "promotion_status",
    "missing_evidence_before_approval",
    "approval_blocker",
    "reviewer_notes",
    "notes",
]

REVIEW_FILE_SPECS: dict[str, list[str]] = {
    "process_units_candidate_review.csv": COMMON_REVIEW_COLUMNS + ["process_id", "configuration", "process_name", "route_id"],
    "carriers_candidate_review.csv": COMMON_REVIEW_COLUMNS + ["carrier_id", "configuration", "carrier_group"],
    "stores_candidate_review.csv": COMMON_REVIEW_COLUMNS + ["store_id", "configuration", "carrier_id", "store_class"],
    "conversion_coefficients_candidate_review.csv": COMMON_REVIEW_COLUMNS + ["process_id", "configuration", "carrier_id", "coefficient_role"],
    "process_bounds_candidate_review.csv": COMMON_REVIEW_COLUMNS + ["process_id", "configuration", "bound_name", "bound_interpretation"],
    "production_targets_candidate_review.csv": COMMON_REVIEW_COLUMNS + ["target_id", "configuration", "carrier_id", "target_name"],
    "initial_inventories_candidate_review.csv": COMMON_REVIEW_COLUMNS + ["store_id", "configuration", "carrier_id"],
    "terminal_inventory_rules_candidate_review.csv": COMMON_REVIEW_COLUMNS + ["store_id", "configuration", "carrier_id", "rule_type"],
    "topology_routes_candidate_review.csv": COMMON_REVIEW_COLUMNS + ["route_id", "configuration", "process_id", "route_sequence"],
    "validation_targets_candidate_review.csv": COMMON_REVIEW_COLUMNS + ["validation_target_id", "configuration", "metric"],
    "s2_deepsearch_f_source_index.csv": [
        "source_id",
        "canonical_title",
        "author_or_institution",
        "year",
        "source_type",
        "url_or_doi",
        "local_file_reference",
        "public_reportability",
        "vendor_or_neutral_status",
        "stage_relevance",
        "supported_parameter_rows",
        "modelling_role",
        "source_card_path",
        "metadata_status",
        "limitations",
        "executable_approval_status",
    ],
    "s2_deepsearch_f_candidate_assumption_register.csv": [
        "parameter_id",
        "category",
        "subcategory",
        "process_or_buffer",
        "carrier_input",
        "carrier_output",
        "candidate_value",
        "candidate_min",
        "candidate_max",
        "unit",
        "relative_unit_basis",
        "source_ids",
        "evidence_strength",
        "modelling_role",
        "recommended_status",
        "sensitivity_required",
        "stage_relevance",
        "approval_blocker",
        "executable_status",
        "thesis_usability",
        "notes",
    ],
    "s2_deepsearch_f_assumption_sensitivity_matrix.csv": [
        "category",
        "parameter_group",
        "conservative_assumption",
        "central_assumption",
        "flexible_assumption",
        "unit",
        "source_ids",
        "evidence_strength",
        "base_case_eligible_later",
        "sensitivity_required",
        "approval_blocker",
        "notes",
    ],
    "s2_configuration_scope_register.csv": [
        "configuration_id",
        "configuration_name",
        "role",
        "implementation_status",
        "thesis_role",
        "stage_relevance",
        "topology_scope",
        "included_routes",
        "excluded_routes_or_assets",
        "hydrogen_treatment",
        "flexibility_sources",
        "sensitivity_dimensions_allowed",
        "main_case_flag",
        "sensitivity_only_flag",
        "optional_later_flag",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "notes",
    ],
    "s2_promotion_checklist.csv": [
        "input_category",
        "target_schema_table",
        "required_for_s2",
        "current_review_status",
        "candidate_rows_available",
        "validation_target_available",
        "unit_review_complete",
        "sign_review_complete",
        "source_review_complete",
        "structural_review_complete",
        "numerical_review_complete",
        "structural_ready_for_structure_only_use",
        "numerical_ready_for_approved_input",
        "thesis_grade_numerical_ready",
        "candidate_review_executable",
        "approval_ready",
        "approval_blocker",
        "next_review_action",
    ],
    "s2_review_summary.csv": [
        "review_table",
        "row_count",
        "candidate_not_approved_rows",
        "validation_only_rows",
        "sensitivity_only_rows",
        "missing_evidence_rows",
        "postponed_rows",
        "approved_rows",
        "structural_only_rows",
        "numerical_candidate_rows",
        "thesis_grade_numerical_rows",
        "candidate_review_executable_rows",
        "key_blockers",
    ],
    "s2_structural_numerical_classification.csv": [
        "table_name",
        "category",
        "structural_status",
        "numerical_status",
        "model_role",
        "approval_status",
        "executable_status",
        "thesis_grade_numerical_eligibility",
        "annual_value_status",
        "constraint_driver_status",
        "allowed_use",
        "approval_blocker",
        "notes",
    ],
    "s2_numerical_promotion_packet_index.csv": [
        "category",
        "source_candidate_table",
        "packet_file",
        "rows_covered",
        "unit_review_status",
        "sign_review_status",
        "source_review_status",
        "annual_to_hourly_status",
        "validation_use_status",
        "executable_use_status",
        "approval_status",
        "thesis_grade_numerical_eligibility",
        "approval_blocker",
        "next_review_action",
    ],
}

REVIEW_DATA_FILES = [
    "process_units_candidate_review.csv",
    "carriers_candidate_review.csv",
    "stores_candidate_review.csv",
    "conversion_coefficients_candidate_review.csv",
    "process_bounds_candidate_review.csv",
    "production_targets_candidate_review.csv",
    "initial_inventories_candidate_review.csv",
    "terminal_inventory_rules_candidate_review.csv",
    "topology_routes_candidate_review.csv",
    "validation_targets_candidate_review.csv",
]

FORBIDDEN_REVIEW_TOKENS = ("wag", "bfg", "cog", "ets", "tariff", "da_", "market", "mfrr", "cvar", "revenue")
APPROVAL_BANNED_VALUES = {"approved", "approved_model_input", "thesis_grade", "base_case_truth"}
EXECUTABLE_BANNED_VALUES = {"s2_executable", "approved_model_input_executable", "thesis_grade_executable"}
REQUIRED_PROMOTION_TABLES = {
    "process_units_schema.csv",
    "carriers_schema.csv",
    "stores_schema.csv",
    "conversion_coefficients_schema.csv",
    "process_bounds_schema.csv",
    "production_targets_schema.csv",
    "initial_inventories_schema.csv",
    "terminal_inventory_rules_schema.csv",
    "topology_routes_schema.csv",
    "validation_targets_schema.csv",
}
RISKY_NUMERICAL_CATEGORIES = {
    "process_bounds",
    "conversion_coefficients",
    "production_targets",
    "initial_inventories",
    "terminal_inventory_rules",
}
PACKET_INDEX_REQUIRED_CATEGORIES = {
    "process_bounds",
    "conversion_coefficients",
    "production_targets",
    "initial_inventories",
    "terminal_inventory_rules",
}
CONFIGURATION_SCOPE_REQUIRED_IDS = {
    "C0_current_BF_BOF_reference",
    "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
    "C1S_phase1_sensitivity_variants",
    "C2_exogenous_hydrogen_sensitivity_optional_later",
}
CONFIGURATION_SCOPE_MAIN_IDS = {
    "C0_current_BF_BOF_reference",
    "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
}
CONFIGURATION_SCOPE_SENSITIVITY_ONLY_IDS = {
    "C1S_phase1_sensitivity_variants",
    "C2_exogenous_hydrogen_sensitivity_optional_later",
}
CONFIGURATION_SCOPE_OPTIONAL_LATER_ID = "C2_exogenous_hydrogen_sensitivity_optional_later"
CONFIGURATION_SCOPE_ALLOWED_EXECUTABLE_STATUSES = {"non_executable", "not_implemented"}
CONFIGURATION_SCOPE_ALLOWED_APPROVAL_STATUSES = {"not_approved", "scope_freeze_only"}
CONFIGURATION_SCOPE_BLOCKED_MAIN_PATTERNS = (
    "phase 2",
    "phase2",
    "phase_2",
    "phase 3",
    "phase3",
    "phase_3",
    "full hydrogen",
    "full_hydrogen",
    "on-site electrolysis",
    "on_site_electrolysis",
    "on-site electrolyser",
    "on_site_electrolyser",
    "on-site electrolyzer",
    "on_site_electrolyzer",
)
CONFIGURATION_SCOPE_FORBIDDEN_HORIZON_PATTERNS = (r"d-only", r"d_only", r"d\+4", r"d_plus_4")
DEEPSEARCH_F_REQUIRED_SOURCE_IDS = {f"F{index:02d}" for index in range(1, 21)}
DEEPSEARCH_F_ALLOWED_EXECUTABLE_STATUSES = {"not_approved", "not_executable"}
DEEPSEARCH_F_ALLOWED_RECOMMENDED_STATUSES = {
    "methodological_policy_candidate",
    "assumption_backed_candidate",
    "sensitivity_only",
    "validation_target_only",
    "topology_support_only",
    "governance_only",
    "missing_or_ambiguous",
}
DEEPSEARCH_F_FORBIDDEN_SCOPE_TOKENS = (
    "d_only",
    "d+4",
    "d_plus_4",
    "rolling_lookahead_comparison",
    "s3",
    "wag",
    "internal_energy",
    "ets",
    "free_allocation",
    "cbam",
    "tariff",
    "da_bidding",
    "stochastic",
    "scenario_probability",
    "mfrr",
    "cvar",
    "product_revenue",
    "order_book",
    "deadline_production",
)
REPO_ROOT = Path(__file__).resolve().parents[4]
UNIT_SIGN_ENDPOINT_NOTE = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_UNIT_SIGN_AND_ENDPOINT_CONVENTIONS.md"


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
            if column == "notes":
                continue
            if frame[column].astype(str).str.strip().eq("").any():
                raise ValueError(f"{filename} contains empty values in required column {column}.")
        tables[filename] = frame
    return GovernanceTableBundle(root=base, tables=tables)


def load_s2_schema(schema_root: str | Path) -> GovernanceTableBundle:
    return _load_bundle(schema_root, SCHEMA_FILE_SPECS)


def load_s2_candidate_mapping(mapping_root: str | Path) -> GovernanceTableBundle:
    return _load_bundle(mapping_root, MAPPING_FILE_SPECS)


def load_s2_candidate_review(review_root: str | Path) -> GovernanceTableBundle:
    return _load_bundle(review_root, REVIEW_FILE_SPECS)


def _count_status(frame: pd.DataFrame, status_name: str) -> int:
    if "source_status" not in frame.columns:
        return 0
    return int(frame["source_status"].astype(str).str.strip().eq(status_name).sum())


def validate_s2_candidate_review(review_bundle: GovernanceTableBundle) -> dict[str, Any]:
    tables = review_bundle.tables
    summary = tables["s2_review_summary.csv"]
    checklist = tables["s2_promotion_checklist.csv"]
    classification = tables["s2_structural_numerical_classification.csv"]
    packet_index = tables["s2_numerical_promotion_packet_index.csv"]
    deepsearch_f_source_index = tables["s2_deepsearch_f_source_index.csv"]
    deepsearch_f_register = tables["s2_deepsearch_f_candidate_assumption_register.csv"]
    deepsearch_f_matrix = tables["s2_deepsearch_f_assumption_sensitivity_matrix.csv"]
    configuration_scope_register = tables["s2_configuration_scope_register.csv"]

    approved_rows = 0
    for filename in REVIEW_DATA_FILES:
        frame = tables[filename]
        approval_values = set(frame["approval_status"].astype(str).str.strip().str.lower())
        if approval_values & APPROVAL_BANNED_VALUES:
            raise ValueError(f"{filename} contains forbidden approval-style values: {sorted(approval_values & APPROVAL_BANNED_VALUES)}")

        for column in ("candidate_source_file", "notes", "reviewer_notes"):
            lowered = frame[column].astype(str).str.lower()
            if lowered.str.contains("approved_model_input|thesis_grade|base_case_truth").any():
                raise ValueError(f"{filename} contains forbidden executable-approval language in {column}.")

        forbidden_pattern = "|".join(
            rf"(?:^|[;/_]){re.escape(token)}(?:[;/_.]|$)"
            for token in FORBIDDEN_REVIEW_TOKENS
        )
        if frame["candidate_source_file"].astype(str).str.lower().str.contains(forbidden_pattern, regex=True).any():
            raise ValueError(f"{filename} references forbidden S3/market/risk candidate files.")

        validation_rows = frame["source_status"].astype(str).str.strip().eq("validation_only")
        if validation_rows.any() and frame.loc[validation_rows, "intended_use"].astype(str).str.lower().str.contains("constraint").any():
            raise ValueError(f"{filename} contains validation_only rows marked as constraints.")

        annual_rows = frame["input_unit_raw"].astype(str).str.contains("/y", regex=False) | frame["input_unit_raw"].astype(str).str.contains("Mt/y", regex=False) | frame["input_unit_raw"].astype(str).str.contains("PJ/y", regex=False)
        if annual_rows.any():
            if frame.loc[annual_rows, "hourly_cap_guard"].astype(str).str.lower().eq("hourly_cap_allowed").any():
                raise ValueError(f"{filename} marks annual values as hourly-cap-allowed.")
            if frame.loc[annual_rows, "intended_use"].astype(str).str.lower().str.contains("hourly_cap").any():
                raise ValueError(f"{filename} labels annual values as hourly caps.")

        approved_rows += int(frame["approval_status"].astype(str).str.strip().str.lower().isin(APPROVAL_BANNED_VALUES).sum())

    checklist_tables = set(checklist["target_schema_table"].astype(str).str.strip())
    if checklist_tables != REQUIRED_PROMOTION_TABLES:
        missing = sorted(REQUIRED_PROMOTION_TABLES - checklist_tables)
        extra = sorted(checklist_tables - REQUIRED_PROMOTION_TABLES)
        raise ValueError(f"s2_promotion_checklist.csv does not match required S2 categories. missing={missing} extra={extra}")

    if checklist["approval_ready"].astype(str).str.strip().str.lower().eq("true").any():
        raise ValueError("s2_promotion_checklist.csv must not mark any category approval_ready=true at S2.4.")
    if checklist["thesis_grade_numerical_ready"].astype(str).str.strip().str.lower().eq("true").any():
        raise ValueError("s2_promotion_checklist.csv must not mark any category thesis_grade_numerical_ready=true at S2.5.")
    if checklist["candidate_review_executable"].astype(str).str.strip().str.lower().eq("true").any():
        raise ValueError("s2_promotion_checklist.csv must not mark any category candidate_review_executable=true at S2.5.")

    risky_rows = checklist[checklist["input_category"].isin(RISKY_NUMERICAL_CATEGORIES)]
    if risky_rows.empty or set(risky_rows["input_category"]) != RISKY_NUMERICAL_CATEGORIES:
        raise ValueError("s2_promotion_checklist.csv must cover every risky numerical S2 category.")
    if risky_rows["numerical_ready_for_approved_input"].astype(str).str.strip().str.lower().eq("true").any():
        raise ValueError("Risky numerical categories must remain blocked from approved numerical use at S2.5.")

    summary_rows = {str(row["review_table"]): row for row in summary.to_dict(orient="records")}
    for filename in REVIEW_DATA_FILES:
        if filename not in summary_rows:
            raise ValueError(f"s2_review_summary.csv is missing row for {filename}.")
        frame = tables[filename]
        row = summary_rows[filename]
        expected = {
            "row_count": len(frame),
            "candidate_not_approved_rows": _count_status(frame, "candidate_not_approved"),
            "validation_only_rows": _count_status(frame, "validation_only"),
            "sensitivity_only_rows": _count_status(frame, "sensitivity_only"),
            "missing_evidence_rows": _count_status(frame, "missing_evidence"),
            "postponed_rows": _count_status(frame, "postponed"),
            "approved_rows": 0,
        }
        for key, expected_value in expected.items():
            actual_value = int(row[key])
            if actual_value != expected_value:
                raise ValueError(f"s2_review_summary.csv mismatch for {filename} field {key}: expected {expected_value}, found {actual_value}")
        if int(row["thesis_grade_numerical_rows"]) != 0:
            raise ValueError(f"{filename} must report zero thesis-grade numerical rows at S2.5.")
        if int(row["candidate_review_executable_rows"]) != 0:
            raise ValueError(f"{filename} must report zero candidate-review executable rows at S2.5.")
        if int(row["structural_only_rows"]) + int(row["numerical_candidate_rows"]) != int(row["row_count"]):
            raise ValueError(f"{filename} must partition row_count into structural_only_rows + numerical_candidate_rows.")

    total_row = summary_rows.get("TOTAL")
    if total_row is None:
        raise ValueError("s2_review_summary.csv must include a TOTAL row.")
    total_expected = {
        "row_count": sum(len(tables[name]) for name in REVIEW_DATA_FILES),
        "candidate_not_approved_rows": sum(_count_status(tables[name], "candidate_not_approved") for name in REVIEW_DATA_FILES),
        "validation_only_rows": sum(_count_status(tables[name], "validation_only") for name in REVIEW_DATA_FILES),
        "sensitivity_only_rows": sum(_count_status(tables[name], "sensitivity_only") for name in REVIEW_DATA_FILES),
        "missing_evidence_rows": sum(_count_status(tables[name], "missing_evidence") for name in REVIEW_DATA_FILES),
        "postponed_rows": sum(_count_status(tables[name], "postponed") for name in REVIEW_DATA_FILES),
        "approved_rows": 0,
    }
    for key, expected_value in total_expected.items():
        if int(total_row[key]) != expected_value:
            raise ValueError(f"s2_review_summary.csv TOTAL mismatch for {key}: expected {expected_value}, found {total_row[key]}")
    if int(total_row["thesis_grade_numerical_rows"]) != 0:
        raise ValueError("s2_review_summary.csv TOTAL must report zero thesis-grade numerical rows at S2.5.")
    if int(total_row["candidate_review_executable_rows"]) != 0:
        raise ValueError("s2_review_summary.csv TOTAL must report zero candidate-review executable rows at S2.5.")

    classification_approval_values = set(classification["approval_status"].astype(str).str.strip().str.lower())
    if classification_approval_values & APPROVAL_BANNED_VALUES:
        raise ValueError(
            "s2_structural_numerical_classification.csv contains forbidden approval-style values: "
            f"{sorted(classification_approval_values & APPROVAL_BANNED_VALUES)}"
        )
    if classification["thesis_grade_numerical_eligibility"].astype(str).str.strip().str.lower().eq("true").any():
        raise ValueError("s2_structural_numerical_classification.csv must report zero thesis-grade numerical rows.")
    if classification["executable_status"].astype(str).str.strip().str.lower().isin(EXECUTABLE_BANNED_VALUES).any():
        raise ValueError("s2_structural_numerical_classification.csv contains forbidden executable S2 rows.")
    validation_class_rows = classification["model_role"].astype(str).str.strip().str.lower().eq("validation_target")
    if validation_class_rows.any():
        bad = classification.loc[validation_class_rows, "constraint_driver_status"].astype(str).str.strip().str.lower() != "cannot_drive_constraints"
        if bad.any():
            raise ValueError("Validation-target classification rows must be marked cannot_drive_constraints.")
    if classification["annual_value_status"].astype(str).str.strip().str.lower().eq("may_become_hourly_cap").any():
        raise ValueError("Annual public values must not be classified as hourly caps.")
    structural_approved_mask = classification["structural_status"].astype(str).str.contains(
        r"(?:^|_)approved(?:$|_)",
        case=False,
        regex=True,
    )
    if structural_approved_mask.any():
        bad_numeric = ~classification.loc[structural_approved_mask, "numerical_status"].astype(str).str.contains("not_approved|not_applicable|blocked", case=False, regex=True)
        if bad_numeric.any():
            raise ValueError("Structural approval language cannot imply approved numerical status.")
    later_stage_mask = classification["category"].astype(str).str.lower().str.contains(
        "wag|internal_energy|emissions|ets|tariff|da|market|stochastic|mfrr|cvar|product_revenue|revenue|order_book|deadline|15_minute|d_plus_4",
        regex=True,
    )
    if later_stage_mask.any():
        if classification.loc[later_stage_mask, "executable_status"].astype(str).str.strip().str.lower().isin({"s2_executable"}).any():
            raise ValueError("Later-stage categories must not be classified as S2 executable.")

    packet_categories = set(packet_index["category"].astype(str).str.strip())
    if packet_categories != PACKET_INDEX_REQUIRED_CATEGORIES:
        missing = sorted(PACKET_INDEX_REQUIRED_CATEGORIES - packet_categories)
        extra = sorted(packet_categories - PACKET_INDEX_REQUIRED_CATEGORIES)
        raise ValueError(f"s2_numerical_promotion_packet_index.csv does not match required categories. missing={missing} extra={extra}")
    if packet_index["approval_status"].astype(str).str.strip().str.lower().isin(APPROVAL_BANNED_VALUES).any():
        raise ValueError("s2_numerical_promotion_packet_index.csv must not mark any category approved.")
    if (~packet_index["approval_status"].astype(str).str.strip().str.lower().isin({"blocked", "not_approved"})).any():
        raise ValueError("s2_numerical_promotion_packet_index.csv must keep approval_status as blocked or not_approved.")
    if packet_index["thesis_grade_numerical_eligibility"].astype(str).str.strip().str.lower().eq("true").any():
        raise ValueError("s2_numerical_promotion_packet_index.csv must report zero thesis-grade numerical eligibility rows.")
    if (~packet_index["executable_use_status"].astype(str).str.strip().str.lower().eq("non_executable")).any():
        raise ValueError("s2_numerical_promotion_packet_index.csv must keep all categories non_executable.")
    if (~packet_index["validation_use_status"].astype(str).str.strip().str.lower().eq("cannot_drive_constraints")).any():
        raise ValueError("s2_numerical_promotion_packet_index.csv must not allow validation-driven constraints.")
    if packet_index["annual_to_hourly_status"].astype(str).str.strip().str.lower().str.contains("hourly_cap_allowed|may_become_hourly_cap").any():
        raise ValueError("s2_numerical_promotion_packet_index.csv must not allow hidden hourly caps.")
    if not UNIT_SIGN_ENDPOINT_NOTE.exists():
        raise ValueError("Shared S2 unit/sign/endpoint convention note is missing.")
    for row in packet_index.to_dict(orient="records"):
        packet_file = REPO_ROOT / str(row["packet_file"])
        if not packet_file.exists():
            raise ValueError(f"Promotion packet file does not exist: {row['packet_file']}")
        source_table = str(row["source_candidate_table"]).strip()
        if source_table not in REVIEW_DATA_FILES:
            raise ValueError(f"Promotion packet index references unknown candidate-review table: {source_table}")
        expected_rows = len(tables[source_table])
        if int(row["rows_covered"]) != expected_rows:
            raise ValueError(
                f"Promotion packet index rows_covered mismatch for {row['category']}: expected {expected_rows}, found {row['rows_covered']}"
            )

    source_id_set = set(deepsearch_f_source_index["source_id"].astype(str).str.strip())
    if source_id_set != DEEPSEARCH_F_REQUIRED_SOURCE_IDS:
        missing = sorted(DEEPSEARCH_F_REQUIRED_SOURCE_IDS - source_id_set)
        extra = sorted(source_id_set - DEEPSEARCH_F_REQUIRED_SOURCE_IDS)
        raise ValueError(f"s2_deepsearch_f_source_index.csv does not match F01-F20. missing={missing} extra={extra}")
    if (~deepsearch_f_source_index["executable_approval_status"].astype(str).str.strip().isin(DEEPSEARCH_F_ALLOWED_EXECUTABLE_STATUSES)).any():
        raise ValueError("s2_deepsearch_f_source_index.csv contains executable approval statuses outside not_approved/not_executable.")
    for row in deepsearch_f_source_index.to_dict(orient="records"):
        source_card_path = REPO_ROOT / str(row["source_card_path"])
        if not source_card_path.exists():
            raise ValueError(f"Deepsearch F source card path does not exist: {row['source_card_path']}")
    f07 = deepsearch_f_source_index.loc[deepsearch_f_source_index["source_id"].eq("F07")]
    if len(f07) != 1:
        raise ValueError("s2_deepsearch_f_source_index.csv must contain exactly one F07 row.")
    f07_row = f07.iloc[0]
    if str(f07_row["canonical_title"]).strip() != "ENERGIRON: DRI Technology by Tenova and Danieli":
        raise ValueError("F07 title does not match the corrected ENERGIRON metadata.")
    if str(f07_row["url_or_doi"]).strip() != "https://tenova.com/sites/default/files/files/solutions/2026/ENERGIRON_Brochure_ENG.pdf":
        raise ValueError("F07 URL does not match the corrected ENERGIRON metadata.")
    if "ENERGIRON_Brochure_ENG.pdf" not in str(f07_row["local_file_reference"]):
        raise ValueError("F07 must record the ENERGIRON brochure local-file reference.")
    f15 = deepsearch_f_source_index.loc[deepsearch_f_source_index["source_id"].eq("F15")]
    if len(f15) != 1:
        raise ValueError("s2_deepsearch_f_source_index.csv must contain exactly one F15 row.")
    f15_row = f15.iloc[0]
    if str(f15_row["author_or_institution"]).strip() != "Geani Kasselman":
        raise ValueError("F15 author does not match the corrected Kasselman metadata.")
    if str(f15_row["year"]).strip() != "2011":
        raise ValueError("F15 year does not match the corrected Kasselman metadata.")
    if "Kasselman_Operations(2011).pdf" not in str(f15_row["local_file_reference"]):
        raise ValueError("F15 must record the corrected Kasselman local-file reference.")
    if str(f15_row["metadata_status"]).strip() not in {"complete_or_reviewed", "complete_metadata_local_reference_unverified"}:
        raise ValueError("F15 metadata_status must be complete_or_reviewed or local-reference-unverified.")

    if (~deepsearch_f_register["recommended_status"].astype(str).str.strip().isin(DEEPSEARCH_F_ALLOWED_RECOMMENDED_STATUSES)).any():
        raise ValueError("s2_deepsearch_f_candidate_assumption_register.csv contains unsupported recommended_status values.")
    if (~deepsearch_f_register["executable_status"].astype(str).str.strip().eq("non_executable")).any():
        raise ValueError("Deepsearch F candidate assumption rows must remain non_executable.")
    if (~deepsearch_f_register["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("Deepsearch F candidate assumption rows must keep thesis_usability=false.")
    if deepsearch_f_register["recommended_status"].astype(str).str.strip().str.lower().eq("validation_target_only").any():
        bad_validation = deepsearch_f_register.loc[
            deepsearch_f_register["recommended_status"].astype(str).str.strip().str.lower().eq("validation_target_only"),
            "modelling_role",
        ].astype(str).str.strip().str.lower().ne("validation_target")
        if bad_validation.any():
            raise ValueError("Deepsearch F validation-target-only rows must use modelling_role=validation_target.")
    annual_register_rows = deepsearch_f_register["unit"].astype(str).str.contains("per_year|/y", case=False, regex=True)
    if annual_register_rows.any():
        blockers = deepsearch_f_register.loc[annual_register_rows, "approval_blocker"].astype(str).str.strip().str.lower()
        if (~blockers.str.contains("hourly cap|hourly_caps|hourly", regex=True)).any():
            raise ValueError("Annual Deepsearch F rows must state that annual values cannot become hourly caps.")
        annual_statuses = deepsearch_f_register.loc[annual_register_rows, "recommended_status"].astype(str).str.strip().str.lower()
        if (~annual_statuses.eq("validation_target_only")).any():
            raise ValueError("Annual Deepsearch F rows must remain validation_target_only.")
    forbidden_scope_pattern = "|".join(re.escape(token) for token in DEEPSEARCH_F_FORBIDDEN_SCOPE_TOKENS)
    scope_scan = deepsearch_f_register[["category", "subcategory", "process_or_buffer"]].astype(str).agg(" ".join, axis=1).str.lower()
    if scope_scan.str.contains(forbidden_scope_pattern, regex=True).any():
        raise ValueError("Deepsearch F candidate assumption register introduces forbidden later-stage or D-only/D+4 comparison categories.")

    if deepsearch_f_matrix.empty:
        raise ValueError("s2_deepsearch_f_assumption_sensitivity_matrix.csv must contain review rows.")
    if (~deepsearch_f_matrix["base_case_eligible_later"].astype(str).str.strip().str.lower().isin({"true", "false"})).any():
        raise ValueError("Deepsearch F assumption sensitivity matrix must keep boolean-style base_case_eligible_later values.")
    if (~deepsearch_f_matrix["sensitivity_required"].astype(str).str.strip().str.lower().isin({"true", "false"})).any():
        raise ValueError("Deepsearch F assumption sensitivity matrix must keep boolean-style sensitivity_required values.")
    matrix_scan = deepsearch_f_matrix[["category", "parameter_group", "notes"]].astype(str).agg(" ".join, axis=1).str.lower()
    if matrix_scan.str.contains(r"d\+4|d_plus_4|d_only", regex=True).any():
        raise ValueError("Deepsearch F assumption sensitivity matrix must not introduce D-only/D+4 comparison categories.")

    configuration_ids = set(configuration_scope_register["configuration_id"].astype(str).str.strip())
    if configuration_ids != CONFIGURATION_SCOPE_REQUIRED_IDS:
        missing = sorted(CONFIGURATION_SCOPE_REQUIRED_IDS - configuration_ids)
        extra = sorted(configuration_ids - CONFIGURATION_SCOPE_REQUIRED_IDS)
        raise ValueError(f"s2_configuration_scope_register.csv does not match the frozen configuration set. missing={missing} extra={extra}")

    configuration_scope_register = configuration_scope_register.set_index("configuration_id", drop=False)
    main_case_mask = configuration_scope_register["main_case_flag"].astype(str).str.strip().str.lower().eq("true")
    main_case_ids = set(configuration_scope_register.loc[main_case_mask, "configuration_id"].astype(str).str.strip())
    if main_case_ids != CONFIGURATION_SCOPE_MAIN_IDS:
        raise ValueError("s2_configuration_scope_register.csv must keep C0 and C1 as the only main physical configurations.")

    sensitivity_only_mask = configuration_scope_register["sensitivity_only_flag"].astype(str).str.strip().str.lower().eq("true")
    sensitivity_only_ids = set(configuration_scope_register.loc[sensitivity_only_mask, "configuration_id"].astype(str).str.strip())
    if not CONFIGURATION_SCOPE_SENSITIVITY_ONLY_IDS.issubset(sensitivity_only_ids):
        raise ValueError("s2_configuration_scope_register.csv must keep C1S and C2 marked sensitivity-only.")
    if configuration_scope_register.loc["C0_current_BF_BOF_reference", "sensitivity_only_flag"].strip().lower() != "false":
        raise ValueError("C0 must not be marked sensitivity-only.")
    if configuration_scope_register.loc["C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "sensitivity_only_flag"].strip().lower() != "false":
        raise ValueError("C1 must not be marked sensitivity-only.")
    if configuration_scope_register.loc["C1S_phase1_sensitivity_variants", "main_case_flag"].strip().lower() != "false":
        raise ValueError("C1S must not be marked as a main physical configuration.")
    if configuration_scope_register.loc["C2_exogenous_hydrogen_sensitivity_optional_later", "main_case_flag"].strip().lower() != "false":
        raise ValueError("C2 must not be marked as a main physical configuration.")

    optional_later_mask = configuration_scope_register["optional_later_flag"].astype(str).str.strip().str.lower().eq("true")
    optional_later_ids = set(configuration_scope_register.loc[optional_later_mask, "configuration_id"].astype(str).str.strip())
    if optional_later_ids != {CONFIGURATION_SCOPE_OPTIONAL_LATER_ID}:
        raise ValueError("s2_configuration_scope_register.csv must keep C2 as the only optional-later configuration.")

    executable_statuses = set(configuration_scope_register["executable_status"].astype(str).str.strip().str.lower())
    if not executable_statuses.issubset(CONFIGURATION_SCOPE_ALLOWED_EXECUTABLE_STATUSES):
        raise ValueError("s2_configuration_scope_register.csv contains executable statuses outside non_executable/not_implemented.")
    if (~configuration_scope_register["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_configuration_scope_register.csv must keep thesis_usability=false for all candidate-review rows.")
    approval_statuses = set(configuration_scope_register["approval_status"].astype(str).str.strip().str.lower())
    if not approval_statuses.issubset(CONFIGURATION_SCOPE_ALLOWED_APPROVAL_STATUSES):
        raise ValueError("s2_configuration_scope_register.csv contains approval statuses outside not_approved/scope_freeze_only.")

    c2_hydrogen_treatment = str(configuration_scope_register.loc["C2_exogenous_hydrogen_sensitivity_optional_later", "hydrogen_treatment"]).strip().lower()
    if "exogenous" not in c2_hydrogen_treatment or "no_on_site_electrolysis" not in c2_hydrogen_treatment:
        raise ValueError("C2 must remain an exogenous-hydrogen sensitivity with no on-site electrolysis.")
    c1_hydrogen_treatment = str(configuration_scope_register.loc["C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "hydrogen_treatment"]).strip().lower()
    if "no_endogenous_production" not in c1_hydrogen_treatment:
        raise ValueError("C1 must not imply endogenous hydrogen production.")

    main_scope_scan = configuration_scope_register.loc[
        main_case_mask,
        ["configuration_name", "role", "topology_scope", "included_routes"],
    ].astype(str).agg(" ".join, axis=1).str.lower()
    blocked_main_pattern = "|".join(re.escape(token) for token in CONFIGURATION_SCOPE_BLOCKED_MAIN_PATTERNS)
    if main_scope_scan.str.contains(blocked_main_pattern, regex=True).any():
        raise ValueError("Main configuration rows must not be defined as Phase 2/Phase 3/full-hydrogen/on-site-electrolysis cases.")

    configuration_scope_scan = configuration_scope_register.astype(str).agg(" ".join, axis=1).str.lower()
    forbidden_horizon_pattern = "|".join(CONFIGURATION_SCOPE_FORBIDDEN_HORIZON_PATTERNS)
    if configuration_scope_scan.str.contains(forbidden_horizon_pattern, regex=True).any():
        raise ValueError("s2_configuration_scope_register.csv must not introduce D-only/D+4 comparison categories.")

    return {
        "candidate_review_files_checked": len(REVIEW_FILE_SPECS),
        "candidate_review_data_files_checked": len(REVIEW_DATA_FILES),
        "candidate_review_total_rows": total_expected["row_count"],
        "candidate_not_approved_rows": total_expected["candidate_not_approved_rows"],
        "validation_only_rows": total_expected["validation_only_rows"],
        "sensitivity_only_rows": total_expected["sensitivity_only_rows"],
        "missing_evidence_rows": total_expected["missing_evidence_rows"],
        "postponed_rows": total_expected["postponed_rows"],
        "approved_rows": approved_rows,
        "classification_rows_checked": int(len(classification)),
        "promotion_packet_rows_checked": int(len(packet_index)),
        "unit_sign_endpoint_note_present": UNIT_SIGN_ENDPOINT_NOTE.exists(),
        "deepsearch_f_source_rows_checked": int(len(deepsearch_f_source_index)),
        "deepsearch_f_candidate_assumption_rows_checked": int(len(deepsearch_f_register)),
        "deepsearch_f_matrix_rows_checked": int(len(deepsearch_f_matrix)),
        "configuration_rows_checked": int(len(configuration_scope_register)),
        "main_configuration_rows": int(main_case_mask.sum()),
        "thesis_grade_numerical_rows": int(classification["thesis_grade_numerical_eligibility"].astype(str).str.strip().str.lower().eq("true").sum()),
        "candidate_review_executable_rows": int(classification["executable_status"].astype(str).str.strip().str.lower().isin(EXECUTABLE_BANNED_VALUES).sum()),
        "later_stage_s2_executable_rows": int(
            classification.loc[
                later_stage_mask,
                "executable_status",
            ].astype(str).str.strip().str.lower().isin({"s2_executable"}).sum()
        ),
    }


def dry_run_validate_input_governance(
    *,
    config,
    schema_bundle: GovernanceTableBundle,
    mapping_bundle: GovernanceTableBundle,
    review_bundle: GovernanceTableBundle | None = None,
) -> dict[str, Any]:
    payload = {
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
    if review_bundle is not None:
        payload.update(validate_s2_candidate_review(review_bundle))
    return payload
