from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import pandas as pd

from .topology_loader import (
    TopologyTableBundle,
    load_topology_skeleton as _load_topology_skeleton_bundle,
    validate_topology_skeleton as _validate_topology_skeleton_bundle,
)
from .topology_objects import SteelTopology, build_steel_topology as _build_steel_topology
from .topology_queries import TopologyAssemblyBundle, assemble_topology_views as _assemble_topology_views


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

SCHEMA_ALIGNMENT_FILE_SPECS: dict[str, list[str]] = {
    "s2_builder_input_schema_alignment.csv": [
        "builder_input_gate_id",
        "builder_input_gate_name",
        "contract_item_id",
        "future_approved_table",
        "candidate_review_source_table",
        "existing_schema_reference",
        "new_schema_created_flag",
        "applies_to_configuration",
        "applies_to_stage",
        "required_before_executable_builder",
        "allowed_status",
        "forbidden_status",
        "approval_blocker",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "notes",
    ],
}

PROMOTION_PROTOCOL_FILE_SPECS: dict[str, list[str]] = {
    "s2_approved_input_promotion_protocol.csv": [
        "protocol_rule_id",
        "category",
        "target_approved_table",
        "required_evidence",
        "required_metadata",
        "required_review_decision",
        "allowed_status_before_review",
        "allowed_status_after_review",
        "forbidden_action",
        "codex_allowed_role",
        "codex_forbidden_role",
        "user_review_required",
        "executable_gate_required",
        "sensitivity_required_rule",
        "approval_blocker",
        "applies_to_configuration",
        "stage_relevance",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "notes",
    ],
}

PROMOTION_REVIEW_CRITERIA_COMMON_COLUMNS = [
    "criterion_id",
    "criterion",
    "why_it_matters",
    "required_evidence_or_check",
    "pass_condition",
    "fail_or_defer_condition",
    "sensitivity_required_if_uncertain",
    "reviewer_decision_required",
    "codex_may_check",
    "codex_may_decide",
    "approval_status",
    "notes",
]

PROMOTION_REVIEW_CRITERIA_FILE_SPECS: dict[str, list[str]] = {
    "s2_promotion_review_criteria/inventory_endpoint_policies_review_criteria.csv": PROMOTION_REVIEW_CRITERIA_COMMON_COLUMNS,
    "s2_promotion_review_criteria/terminal_inventory_rules_review_criteria.csv": PROMOTION_REVIEW_CRITERIA_COMMON_COLUMNS,
    "s2_promotion_review_criteria/initial_inventories_review_criteria.csv": PROMOTION_REVIEW_CRITERIA_COMMON_COLUMNS,
    "s2_promotion_review_criteria/conversion_coefficients_review_criteria.csv": PROMOTION_REVIEW_CRITERIA_COMMON_COLUMNS,
    "s2_promotion_review_criteria/process_bounds_review_criteria.csv": PROMOTION_REVIEW_CRITERIA_COMMON_COLUMNS,
    "s2_promotion_review_criteria/store_capacities_review_criteria.csv": PROMOTION_REVIEW_CRITERIA_COMMON_COLUMNS,
    "s2_promotion_review_criteria/production_targets_review_criteria.csv": PROMOTION_REVIEW_CRITERIA_COMMON_COLUMNS,
    "s2_promotion_review_criteria/validation_targets_review_criteria.csv": PROMOTION_REVIEW_CRITERIA_COMMON_COLUMNS,
}

PROMOTION_DECISION_TEMPLATE_COLUMNS = [
    "decision_id",
    "candidate_row_id",
    "candidate_source_table",
    "target_approved_table",
    "proposed_parameter_id",
    "reviewer_decision",
    "reviewer_name_or_role",
    "decision_date",
    "approved_value",
    "approved_unit",
    "approved_basis",
    "source_ids",
    "sensitivity_required",
    "thesis_use_allowed",
    "executable_allowed",
    "conditions_or_limitations",
    "rejection_or_deferral_reason",
    "notes",
]

APPROVED_INPUT_FILE_SPECS: dict[str, list[str]] = {
    "process_bounds.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "process_unit_id",
        "bound_name",
        "bound_value",
        "unit",
        "time_basis",
        "annual_to_hourly_translation_status",
        "source_ids",
        "evidence_status",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "approved_by",
        "approval_date",
        "notes",
    ],
    "conversion_coefficients.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "process_unit_id",
        "carrier_id",
        "coefficient_name",
        "coefficient_value",
        "unit",
        "source_ids",
        "evidence_status",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "approved_by",
        "approval_date",
        "notes",
    ],
    "store_capacities.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "store_id",
        "carrier_id",
        "capacity_name",
        "capacity_value",
        "unit",
        "source_ids",
        "evidence_status",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "approved_by",
        "approval_date",
        "notes",
    ],
    "initial_inventories.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "store_id",
        "carrier_id",
        "inventory_basis",
        "initial_inventory_value",
        "unit",
        "source_ids",
        "evidence_status",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "approved_by",
        "approval_date",
        "notes",
    ],
    "terminal_inventory_rules.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "store_id",
        "carrier_id",
        "rule_type",
        "rule_value",
        "unit",
        "horizon_applicability",
        "source_ids",
        "evidence_status",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "approved_by",
        "approval_date",
        "notes",
    ],
    "production_targets.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "target_id",
        "carrier_id",
        "target_type",
        "target_value",
        "unit",
        "horizon_applicability",
        "annual_to_hourly_translation_status",
        "source_ids",
        "evidence_status",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "approved_by",
        "approval_date",
        "notes",
    ],
    "validation_targets.csv": [
        "row_id",
        "configuration_id",
        "validation_target_id",
        "metric_name",
        "target_value_or_range",
        "unit",
        "constraint_usage_status",
        "annual_to_hourly_translation_status",
        "source_ids",
        "evidence_status",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "approved_by",
        "approval_date",
        "notes",
    ],
    "inventory_endpoint_policies.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "store_id",
        "endpoint_policy_id",
        "initial_inventory_policy",
        "terminal_inventory_policy",
        "policy_value",
        "unit",
        "source_ids",
        "evidence_status",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "approved_by",
        "approval_date",
        "notes",
    ],
    "run_reporting_requirements.csv": [
        "row_id",
        "configuration_id",
        "report_field_id",
        "report_field_name",
        "metric_definition",
        "unit_or_format",
        "stage_applicability",
        "required_for_run_contract",
        "source_ids",
        "evidence_status",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "approved_by",
        "approval_date",
        "notes",
    ],
}

TOPOLOGY_SKELETON_FILE_SPECS: dict[str, list[str]] = {
    "configurations.csv": [
        "configuration_id",
        "configuration_name",
        "role",
        "main_case_flag",
        "sensitivity_only_flag",
        "optional_later_flag",
        "topology_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "notes",
    ],
    "routes.csv": [
        "route_id",
        "configuration_id",
        "route_name",
        "route_role",
        "included_in_main_case",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
        "notes",
    ],
    "process_units.csv": [
        "process_unit_id",
        "configuration_id",
        "route_id",
        "process_unit_name",
        "process_class",
        "continuity_class",
        "structural_role",
        "included_in_s2",
        "postponed_to_stage",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
        "notes",
    ],
    "carriers.csv": [
        "carrier_id",
        "carrier_name",
        "carrier_class",
        "material_or_energy",
        "s2_in_scope",
        "external_supply_flag",
        "internal_carrier_flag",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
        "notes",
    ],
    "stores.csv": [
        "store_id",
        "configuration_id",
        "route_id",
        "carrier_id",
        "store_name",
        "store_class",
        "flexibility_role",
        "endpoint_policy",
        "initial_inventory_policy",
        "bounded_store_required",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
        "notes",
    ],
    "topology_arcs.csv": [
        "arc_id",
        "configuration_id",
        "route_id",
        "from_node",
        "to_node",
        "carrier_id",
        "arc_role",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
        "notes",
    ],
    "inventory_policy.csv": [
        "policy_id",
        "store_class",
        "endpoint_policy",
        "initial_inventory_policy",
        "terminal_inventory_policy",
        "allowed_use",
        "forbidden_use",
        "structural_status",
        "numerical_status",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "source_ids",
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
    "s2_configuration_tag_mapping.csv": [
        "legacy_tag",
        "legacy_context",
        "mapped_configuration_id",
        "mapped_configuration_role",
        "allowed_use",
        "forbidden_use",
        "stage_relevance",
        "executable_status",
        "thesis_usability",
        "approval_status",
        "notes",
    ],
    "s2_model_builder_interface_contract.csv": [
        "contract_item_id",
        "contract_layer",
        "required_input_or_rule",
        "expected_source",
        "applies_to_configuration",
        "applies_to_stage",
        "allowed_status",
        "forbidden_status",
        "required_governance_check",
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
    "s2_human_policy_decision_bundle.csv": [
        "decision_id",
        "decision_cluster",
        "decision_item",
        "human_decision",
        "modelling_interpretation",
        "applies_to_configuration",
        "applies_to_stage",
        "affected_future_approved_table",
        "evidence_basis",
        "sensitivity_implication",
        "unresolved_blocker",
        "codex_allowed_role",
        "codex_forbidden_role",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "notes",
    ],
    "s2_future_parameter_review_backlog.csv": [
        "backlog_item_id",
        "parameter_category",
        "review_priority",
        "why_review_needed",
        "current_policy_status",
        "future_decision_needed",
        "affected_model_risk",
        "suggested_review_stage",
        "candidate_sources_available",
        "sensitivity_likely_required",
        "notes",
    ],
    **PROMOTION_PROTOCOL_FILE_SPECS,
    **PROMOTION_REVIEW_CRITERIA_FILE_SPECS,
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
CONFIGURATION_SCOPE_FORBIDDEN_HORIZON_PATTERNS = (
    r"(?:^|[^a-z0-9])d-only(?:[^a-z0-9]|$)",
    r"(?:^|[^a-z0-9])d_only(?:[^a-z0-9]|$)",
    r"(?:^|[^a-z0-9])d\+4(?:[^a-z0-9]|$)",
    r"(?:^|[^a-z0-9])d_plus_4(?:[^a-z0-9]|$)",
)
CONFIGURATION_TAG_MAPPING_ALLOWED_CONFIG_IDS = CONFIGURATION_SCOPE_REQUIRED_IDS | {"postponed_or_blocked"}
CONFIGURATION_TAG_MAPPING_ALLOWED_APPROVAL_STATUSES = {"not_approved", "scope_mapping_only", "blocked"}
CONFIGURATION_TAG_MAPPING_REQUIRED_BLOCKED_TAGS = {
    "Phase 2",
    "Phase 3",
    "full_hydrogen",
    "on_site_electrolysis",
    "hydrogen_production_optimisation",
    "hydrogen_storage",
    "SAF",
    "CCS",
}
CONFIGURATION_TAG_MAPPING_REQUIRED_LEGACY_TAGS = {
    "baseline_bf_bof",
    "phase1_hybrid_bf_bof_plus_dri_eaf",
    "PHASE1_DRP_EAF",
    "flag_high_scrap_eaf_variant",
    "flag_h2_backbone_available",
}
CONFIGURATION_TAG_MAPPING_BLOCKED_ID = "postponed_or_blocked"
CONFIGURATION_TAG_MAPPING_REQUIRED_ROLE_BY_ID = {
    "C0_current_BF_BOF_reference": "reference_configuration",
    "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF": "main_configuration",
    "C1S_phase1_sensitivity_variants": "sensitivity_only_within_C1",
    "C2_exogenous_hydrogen_sensitivity_optional_later": "optional_later_sensitivity_only",
    "postponed_or_blocked": "postponed_or_blocked",
}
CONFIGURATION_TAG_MAPPING_FORBIDDEN_HORIZON_PATTERNS = CONFIGURATION_SCOPE_FORBIDDEN_HORIZON_PATTERNS
MODEL_BUILDER_CONTRACT_REQUIRED_IDS = {
    "MBIC01",
    "MBIC02",
    "MBIC03",
    "MBIC04",
    "MBIC05",
    "MBIC06",
    "MBIC07",
    "MBIC08",
    "MBIC09",
    "MBIC10",
    "MBIC11",
    "MBIC12",
    "MBIC13",
    "MBIC14",
    "MBIC15",
    "MBIC16",
    "MBIC17",
    "MBIC18",
    "MBIC19",
    "MBIC20",
    "MBIC21",
    "MBIC22",
    "MBIC23",
    "MBIC24",
    "MBIC25",
    "MBIC26",
    "MBIC27",
    "MBIC28",
    "MBIC29",
}
MODEL_BUILDER_CONTRACT_REQUIRED_NUMERICAL_TABLE_ROWS = {
    "future_process_bounds_table",
    "future_conversion_coefficients_table",
    "future_store_capacity_table",
    "future_initial_inventory_table",
    "future_terminal_inventory_rule_table",
    "future_production_target_table",
    "future_validation_target_table",
}
MODEL_BUILDER_CONTRACT_REQUIRED_REPORTING_ROWS = {
    "solver_status_reporting",
    "objective_reporting",
    "runtime_reporting",
    "variable_constraint_count_reporting",
    "infeasibility_diagnostics",
}
MODEL_BUILDER_CONTRACT_REQUIRED_REFUSAL_ROWS = {
    "refusal_of_candidate_review_values_unless_approved_later",
    "refusal_of_validation_targets_as_constraints",
    "refusal_of_annual_public_anchors_as_hourly_caps",
    "refusal_of_S3_DA_stochastic_mFRR_CVaR_product_revenue_order_book_logic",
    "refusal_of_D_only_D_plus_4_comparison_logic",
}
MODEL_BUILDER_CONTRACT_ALLOWED_APPROVAL_STATUSES = {"interface_contract_only", "not_approved", "blocked"}
MODEL_BUILDER_CONTRACT_ALLOWED_CONFIG_TOKENS = CONFIGURATION_SCOPE_REQUIRED_IDS | {"all"}
MODEL_BUILDER_CONTRACT_MAIN_CONFIG_TOKENS = {
    "C0_current_BF_BOF_reference",
    "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
}
SCHEMA_ALIGNMENT_REQUIRED_GATE_NAMES = {
    "topology_view_selection",
    "inventory_endpoint_policy",
    "fixed_production_target_policy",
    "process_bounds",
    "conversion_coefficients",
    "store_capacities",
    "initial_inventories",
    "terminal_inventory_rules",
    "production_targets",
    "validation_targets",
    "solver_status_reporting",
    "objective_reporting",
    "runtime_reporting",
    "variable_constraint_count_reporting",
    "infeasibility_diagnostics",
}
SCHEMA_ALIGNMENT_ALLOWED_APPROVAL_STATUSES = {"schema_alignment_only", "not_approved", "blocked", "template_only"}
SCHEMA_ALIGNMENT_ALLOWED_NEW_SCHEMA_FLAGS = {"true", "false"}
SCHEMA_ALIGNMENT_REQUIRED_BLOCKED_GATE = "validation_targets"
SCHEMA_ALIGNMENT_REQUIRED_ANNUAL_BLOCKED_GATES = {"process_bounds", "production_targets", "validation_targets"}
APPROVED_INPUT_REQUIRED_TABLES = set(APPROVED_INPUT_FILE_SPECS)
APPROVED_INPUT_REQUIRED_ZERO_ROW_TABLES = APPROVED_INPUT_REQUIRED_TABLES
APPROVED_INPUT_ALLOWED_APPROVAL_STATUSES = {"approved"}
APPROVED_INPUT_ALLOWED_EXECUTABLE_STATUSES = {"executable"}
APPROVED_INPUT_ALLOWED_THESIS_USABILITY = {"true"}
APPROVED_INPUT_REQUIRED_METADATA_COLUMNS = {
    "source_ids",
    "approval_status",
    "executable_status",
    "thesis_usability",
    "approved_by",
    "approval_date",
    "notes",
}
APPROVED_INPUT_TABLES_REQUIRING_TRANSLATION_STATUS = {
    "process_bounds.csv",
    "production_targets.csv",
    "validation_targets.csv",
}
APPROVED_INPUT_FORBIDDEN_SCOPE_PATTERNS = (
    r"phase 2",
    r"phase2",
    r"phase_2",
    r"phase 3",
    r"phase3",
    r"phase_3",
    r"full_hydrogen",
    r"full hydrogen",
    r"on_site_electrolysis",
    r"on-site electrolysis",
    r"hydrogen_production",
    r"hydrogen storage",
    r"hydrogen_storage",
    r"saf",
    r"ccs",
    r"da_bidding",
    r"stochastic",
    r"mfrr",
    r"cvar",
    r"product_revenue",
    r"order_book",
    r"d_only",
    r"d\+4",
    r"d_plus_4",
    r"wag",
)
TOPOLOGY_SKELETON_DIRNAME = "s2_topology_skeleton"
TOPOLOGY_REQUIRED_CONFIGURATION_IDS = {
    "C0_current_BF_BOF_reference",
    "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
}
TOPOLOGY_REQUIRED_ROUTE_ROWS = {
    ("C0_current_BF_BOF_reference", "C0_ROUTE_BF_BOF"),
    ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "C1_ROUTE_RETAINED_BF_BOF"),
    ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "C1_ROUTE_NG_DRP_EAF"),
}
TOPOLOGY_ALLOWED_NUMERICAL_STATUSES = {"no_numerical_value", "candidate_not_approved", "not_applicable"}
TOPOLOGY_ALLOWED_EXECUTABLE_STATUSES = {"non_executable"}
TOPOLOGY_ALLOWED_APPROVAL_STATUSES = {"structural_candidate", "scope_freeze_only", "not_approved", "blocked"}
TOPOLOGY_REQUIRED_EXTERNAL_BOUNDARY_CARRIERS = {
    "coal_or_coke_input_boundary",
    "iron_ore_or_pellet_input_boundary",
    "scrap_input_boundary",
    "flux_input_boundary",
}
TOPOLOGY_FORBIDDEN_SCOPE_PATTERNS = (
    r"phase 2",
    r"phase2",
    r"phase_2",
    r"phase 3",
    r"phase3",
    r"phase_3",
    r"full_hydrogen",
    r"full hydrogen",
    r"on_site_electrolysis",
    r"on-site electrolysis",
    r"hydrogen_production",
    r"hydrogen storage",
    r"hydrogen_storage",
    r"saf",
    r"ccs",
)
TOPOLOGY_FORBIDDEN_STAGE_PATTERNS = (
    r"wag",
    r"internal_energy",
    r"stochastic",
    r"mfrr",
    r"cvar",
    r"order_book",
    r"deadline",
)
TOPOLOGY_FORBIDDEN_COLUMN_PATTERNS = (
    r"(?:^|_)capacity(?:_|$)",
    r"(?:^|_)coefficient(?:_|$)",
    r"(?:^|_)cost(?:_|$)",
    r"(?:^|_)emission(?:_|$)",
    r"(?:^|_)tariff(?:_|$)",
    r"(?:^|_)bid_quantity(?:_|$)",
    r"(?:^|_)objective_value(?:_|$)",
)
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
APPROVED_INPUT_README = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input" / "README.md"
PROMOTION_PROTOCOL_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_APPROVED_INPUT_PROMOTION_PROTOCOL.md"
PROMOTION_DECISION_TEMPLATE = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_promotion_decision_template.csv"
PROMOTION_REVIEW_CRITERIA_DIR = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_promotion_review_criteria"

PROMOTION_PROTOCOL_ALLOWED_APPROVAL_STATUSES = {"protocol_only", "not_approved", "blocked"}
PROMOTION_PROTOCOL_REQUIRED_CATEGORIES = {
    "process_bounds",
    "conversion_coefficients",
    "store_capacities",
    "initial_inventories",
    "terminal_inventory_rules",
    "production_targets",
    "validation_targets",
    "inventory_endpoint_policies",
    "run_reporting_requirements",
    "annual_to_hourly_translation",
    "source_card_completeness",
    "unit_sign_convention_compliance",
    "configuration_applicability_c0_c1",
    "c1s_sensitivity_overlay",
    "c2_optional_later_exogenous_hydrogen",
    "codex_role_limits",
    "explicit_user_approval_requirement",
    "executable_gate_separation",
}
PROMOTION_PROTOCOL_REQUIRED_TARGET_TABLES_BY_CATEGORY = {
    "process_bounds": "process_bounds.csv",
    "conversion_coefficients": "conversion_coefficients.csv",
    "store_capacities": "store_capacities.csv",
    "initial_inventories": "initial_inventories.csv",
    "terminal_inventory_rules": "terminal_inventory_rules.csv",
    "production_targets": "production_targets.csv",
    "validation_targets": "validation_targets.csv",
    "inventory_endpoint_policies": "inventory_endpoint_policies.csv",
    "run_reporting_requirements": "run_reporting_requirements.csv",
    "annual_to_hourly_translation": "all_applicable_tables",
    "source_card_completeness": "all_applicable_tables",
    "unit_sign_convention_compliance": "all_applicable_tables",
    "configuration_applicability_c0_c1": "all_applicable_tables",
    "c1s_sensitivity_overlay": "all_applicable_tables",
    "c2_optional_later_exogenous_hydrogen": "all_applicable_tables",
    "codex_role_limits": "all_applicable_tables",
    "explicit_user_approval_requirement": "all_applicable_tables",
    "executable_gate_separation": "all_applicable_tables",
}
PROMOTION_REVIEW_CRITERIA_ALLOWED_APPROVAL_STATUSES = {"protocol_only", "not_approved", "blocked"}
PROMOTION_REVIEW_CRITERIA_REQUIRED_BASE_FILENAMES = {
    "inventory_endpoint_policies_review_criteria.csv",
    "terminal_inventory_rules_review_criteria.csv",
    "initial_inventories_review_criteria.csv",
    "conversion_coefficients_review_criteria.csv",
    "process_bounds_review_criteria.csv",
    "store_capacities_review_criteria.csv",
    "production_targets_review_criteria.csv",
    "validation_targets_review_criteria.csv",
}
HUMAN_REVIEW_PACKET_DOC_DIR = REPO_ROOT / "docs" / "optimisation" / "steel" / "s2_human_review_packets"
HUMAN_REVIEW_PACKET_DATA_DIR_NAME = "s2_human_review_packets"
HUMAN_REVIEW_PACKET_SUMMARY_COLUMNS = [
    "review_packet_id",
    "review_category",
    "candidate_row_id",
    "candidate_source_table",
    "target_approved_table",
    "parameter_or_rule_name",
    "candidate_value_or_rule_summary",
    "unit_or_basis",
    "source_ids",
    "evidence_status",
    "modelling_interpretation",
    "affects_model_component",
    "main_risk",
    "sensitivity_required",
    "approval_blockers",
    "codex_preliminary_assessment",
    "possible_reviewer_outcomes",
    "reviewer_decision_required",
    "codex_may_decide",
    "approval_status",
    "executable_status",
    "thesis_usability",
    "notes",
]
HUMAN_REVIEW_PACKET_SUMMARY_FILE_SPECS: dict[str, dict[str, str]] = {
    "inventory_endpoint_policy_review_packet.csv": {
        "review_category": "inventory_endpoint_policy",
        "target_approved_table": "inventory_endpoint_policies.csv",
    },
    "terminal_inventory_rules_review_packet.csv": {
        "review_category": "terminal_inventory_rules",
        "target_approved_table": "terminal_inventory_rules.csv",
    },
    "initial_inventory_rules_review_packet.csv": {
        "review_category": "initial_inventory_rules",
        "target_approved_table": "initial_inventories.csv",
    },
}
HUMAN_REVIEW_PACKET_ALLOWED_APPROVAL_STATUSES = {
    "review_packet_only",
    "not_approved",
    "blocked",
    "defer_pending_review",
}
HUMAN_REVIEW_PACKET_DASHBOARD_COLUMNS = [
    "review_category",
    "candidate_count",
    "high_confidence_candidate_count",
    "sensitivity_required_count",
    "blocked_or_defer_count",
    "missing_source_count",
    "missing_unit_or_basis_count",
    "human_decision_needed_count",
    "recommended_review_priority",
    "main_blocker",
    "next_human_action",
]
HUMAN_REVIEW_PACKET_MEMO_REQUIRED_PHRASES: dict[str, tuple[str, ...]] = {
    "S2_7D_INVENTORY_ENDPOINT_POLICY_REVIEW_PACKET.md": (
        "review purpose",
        "relevant approved-input target table",
        "relevant candidate-review sources",
        "relevant source-card ids",
        "relevant promotion criteria",
        "candidate evidence summary",
        "modelling interpretation options",
        "what the rule would affect in the later lp",
        "red flags and blockers",
        "sensitivity implications",
        "suggested human review questions",
        "possible reviewer outcomes",
        "codex is not approving any row",
        "approved-input tables remain empty",
        "cyc50",
        "anti-gaming",
        "buffer capacity",
        "operational truth",
        "base-case policy",
        "sensitivity policy",
        "deferred",
    ),
    "S2_7D_TERMINAL_INVENTORY_RULES_REVIEW_PACKET.md": (
        "review purpose",
        "relevant approved-input target table",
        "relevant candidate-review sources",
        "relevant source-card ids",
        "relevant promotion criteria",
        "candidate evidence summary",
        "modelling interpretation options",
        "what the rule would affect in the later lp",
        "red flags and blockers",
        "sensitivity implications",
        "suggested human review questions",
        "possible reviewer outcomes",
        "codex is not approving any row",
        "approved-input tables remain empty",
        "terminal equality",
        "cyclic rule",
        "loose terminal band",
        "terminal value penalty",
        "fake flexibility",
        "horizon borrowing",
        "capacity values",
    ),
    "S2_7D_INITIAL_INVENTORY_RULES_REVIEW_PACKET.md": (
        "review purpose",
        "relevant approved-input target table",
        "relevant candidate-review sources",
        "relevant source-card ids",
        "relevant promotion criteria",
        "candidate evidence summary",
        "modelling interpretation options",
        "what the rule would affect in the later lp",
        "red flags and blockers",
        "sensitivity implications",
        "suggested human review questions",
        "possible reviewer outcomes",
        "codex is not approving any row",
        "approved-input tables remain empty",
        "percentage-of-capacity",
        "absolute site inventory",
        "cannot be finalised before store-capacity rows exist",
        "formula or policy",
        "absolute site inventory quantity",
    ),
}
HUMAN_REVIEW_PACKET_DASHBOARD = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_first_promotion_review_dashboard.csv"
HUMAN_POLICY_DECISION_BUNDLE_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_HUMAN_POLICY_DECISION_BUNDLE.md"
HUMAN_POLICY_DECISION_BUNDLE_COLUMNS = REVIEW_FILE_SPECS["s2_human_policy_decision_bundle.csv"]
HUMAN_POLICY_DECISION_BUNDLE_ALLOWED_APPROVAL_STATUSES = {
    "human_policy_recorded",
    "convention_recorded",
    "sensitivity_strategy_recorded",
    "not_approved_numerical",
    "blocked_until_later_review",
}
HUMAN_POLICY_DECISION_BUNDLE_REQUIRED_CLUSTERS = {
    "inventory_endpoint_policy",
    "buffer_classification",
    "buffer_sizing_basis",
    "conversion_coefficient_convention",
    "process_bound_policy",
    "production_target_policy",
    "sensitivity_strategy",
}
HUMAN_POLICY_DECISION_BUNDLE_REQUIRED_ITEMS = {
    "CYC50_endpoint_policy_base_case",
    "initial_inventory_formula",
    "terminal_equality_rule",
    "non_negative_inventory_state_convention",
    "HDRI_DRI_surge_main_flexibility_buffer",
    "cold_slab_WIP_main_flexibility_buffer",
    "hot_metal_synchronisation_secondary_buffer",
    "hot_slab_WIP_thermal_transfer_classification",
    "liquid_steel_ladle_tundish_feasibility_only",
    "coke_sinter_pellet_excluded_from_base_flexibility",
    "finished_goods_order_book_excluded",
    "heat_based_relative_sizing_convention",
    "days_of_throughput_relative_sizing_convention",
    "positive_magnitude_coefficients",
    "coefficient_role_taxonomy",
    "carrier_per_activity_unit_convention",
    "process_output_activity_basis_default",
    "BF_near_must_run_policy",
    "DRP_continuous_turndown_policy",
    "BOF_EAF_batch_equivalent_hourly_policy",
    "annual_to_hourly_translation_required",
    "horizon_total_production_target_policy",
    "single_sink_carrier_target_basis_required",
    "no_route_specific_base_target",
    "early_sensitivity_screening_strategy",
    "final_thesis_sensitivity_selection_strategy",
}
HUMAN_POLICY_DECISION_BUNDLE_MEMO_REQUIRED_PHRASES = (
    "purpose and scope",
    "records the current human modelling-policy decisions",
    "not a codex approval artifact",
    "approved-input tables remain empty",
    "endpoint policy decision",
    "buffer classification decision",
    "buffer sizing-basis decision",
    "conversion-coefficient convention decision",
    "process-bound policy decision",
    "production target policy decision",
    "sensitivity strategy decision",
    "what remains undecided",
    "what is still blocked from executable use",
    "how future codex tasks should use this bundle",
    "why this does not approve exact numerical values",
)
HUMAN_POLICY_NUMERIC_FORBIDDEN_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:tonnes|t/h|mt/y|pj/y|€/mwh|€/kg|eur/mwh|eur/kg|mw|mwh|kg)\b",
    re.IGNORECASE,
)
FUTURE_PARAMETER_REVIEW_BACKLOG_COLUMNS = REVIEW_FILE_SPECS["s2_future_parameter_review_backlog.csv"]
FUTURE_PARAMETER_REVIEW_BACKLOG_REQUIRED_CATEGORIES = {
    "exact_DRI_HDRI_surge_capacity",
    "exact_cold_slab_WIP_capacity",
    "exact_hot_metal_buffer_capacity",
    "exact_hot_slab_WIP_treatment_or_capacity",
    "exact_conversion_coefficients",
    "process_bounds_and_annual_to_hourly_translation",
    "production_target_basis_and_scale",
    "store_capacity_sensitivity_ranges",
    "DRP_turndown",
    "BF_near_must_run_band",
    "BOF_EAF_batch_equivalent_capacity",
    "validation_target_selection",
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


def _load_bundle(
    root: str | Path,
    file_specs: dict[str, list[str]],
    *,
    require_non_empty: bool = True,
) -> GovernanceTableBundle:
    base = Path(root).resolve()
    tables: dict[str, pd.DataFrame] = {}
    for filename, required_columns in file_specs.items():
        path = base / filename
        frame = _read_csv(path)
        missing = [column for column in required_columns if column not in frame.columns]
        if missing:
            raise ValueError(f"{filename} is missing required columns: {missing}")
        if require_non_empty and frame.empty:
            raise ValueError(f"{filename} must contain at least one schema or mapping row.")
        for column in required_columns:
            if column == "notes":
                continue
            if not frame.empty and frame[column].astype(str).str.strip().eq("").any():
                raise ValueError(f"{filename} contains empty values in required column {column}.")
        tables[filename] = frame
    return GovernanceTableBundle(root=base, tables=tables)


def load_s2_schema(schema_root: str | Path) -> GovernanceTableBundle:
    return _load_bundle(schema_root, SCHEMA_FILE_SPECS)


def load_s2_candidate_mapping(mapping_root: str | Path) -> GovernanceTableBundle:
    return _load_bundle(mapping_root, MAPPING_FILE_SPECS)


def load_s2_candidate_review(review_root: str | Path) -> GovernanceTableBundle:
    return _load_bundle(review_root, REVIEW_FILE_SPECS)


def load_s2_schema_alignment(review_root: str | Path) -> GovernanceTableBundle:
    return _load_bundle(review_root, SCHEMA_ALIGNMENT_FILE_SPECS)


def load_s2_approved_model_input(approved_input_root: str | Path) -> GovernanceTableBundle:
    return _load_bundle(approved_input_root, APPROVED_INPUT_FILE_SPECS, require_non_empty=False)


def load_s2_topology_skeleton(review_root: str | Path) -> TopologyTableBundle:
    return _load_topology_skeleton_bundle(review_root)


def _count_status(frame: pd.DataFrame, status_name: str) -> int:
    if "source_status" not in frame.columns:
        return 0
    return int(frame["source_status"].astype(str).str.strip().eq(status_name).sum())


def _split_multi_value_field(raw_value: str) -> list[str]:
    return [token.strip() for token in str(raw_value).split(";") if token.strip()]


def validate_s2_topology_skeleton(topology_bundle: TopologyTableBundle) -> dict[str, Any]:
    return _validate_topology_skeleton_bundle(topology_bundle)


def build_s2_topology_objects(topology_bundle: TopologyTableBundle) -> SteelTopology:
    return _build_steel_topology(topology_bundle, validate=True)


def build_s2_topology_views(topology: SteelTopology) -> TopologyAssemblyBundle:
    return _assemble_topology_views(topology)


def validate_s2_schema_alignment(alignment_bundle: GovernanceTableBundle) -> dict[str, Any]:
    alignment = alignment_bundle.tables["s2_builder_input_schema_alignment.csv"]
    if alignment["builder_input_gate_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_builder_input_schema_alignment.csv must not contain duplicate builder_input_gate_id values.")
    if alignment["builder_input_gate_name"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_builder_input_schema_alignment.csv must not contain duplicate builder_input_gate_name values.")

    gate_names = set(alignment["builder_input_gate_name"].astype(str).str.strip())
    if gate_names != SCHEMA_ALIGNMENT_REQUIRED_GATE_NAMES:
        missing = sorted(SCHEMA_ALIGNMENT_REQUIRED_GATE_NAMES - gate_names)
        extra = sorted(gate_names - SCHEMA_ALIGNMENT_REQUIRED_GATE_NAMES)
        raise ValueError(f"s2_builder_input_schema_alignment.csv does not match required builder gates. missing={missing} extra={extra}")

    contract_ids = set(alignment["contract_item_id"].astype(str).str.strip())
    if not contract_ids.issubset(MODEL_BUILDER_CONTRACT_REQUIRED_IDS):
        raise ValueError(
            "s2_builder_input_schema_alignment.csv references unknown contract_item_id values: "
            f"{sorted(contract_ids - MODEL_BUILDER_CONTRACT_REQUIRED_IDS)}"
        )

    new_schema_flags = set(alignment["new_schema_created_flag"].astype(str).str.strip().str.lower())
    if not new_schema_flags.issubset(SCHEMA_ALIGNMENT_ALLOWED_NEW_SCHEMA_FLAGS):
        raise ValueError(
            "s2_builder_input_schema_alignment.csv contains unsupported new_schema_created_flag values: "
            f"{sorted(new_schema_flags - SCHEMA_ALIGNMENT_ALLOWED_NEW_SCHEMA_FLAGS)}"
        )
    if (~alignment["executable_status"].astype(str).str.strip().str.lower().eq("non_executable")).any():
        raise ValueError("s2_builder_input_schema_alignment.csv must keep executable_status=non_executable for all rows.")
    if (~alignment["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_builder_input_schema_alignment.csv must keep thesis_usability=false for all rows.")
    approval_values = set(alignment["approval_status"].astype(str).str.strip().str.lower())
    if not approval_values.issubset(SCHEMA_ALIGNMENT_ALLOWED_APPROVAL_STATUSES):
        raise ValueError(
            "s2_builder_input_schema_alignment.csv contains unsupported approval_status values: "
            f"{sorted(approval_values - SCHEMA_ALIGNMENT_ALLOWED_APPROVAL_STATUSES)}"
        )

    valid_config_tokens = CONFIGURATION_SCOPE_REQUIRED_IDS | {"all", "C0_current_BF_BOF_reference;C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"}
    for raw_value in alignment["applies_to_configuration"].astype(str).str.strip():
        if raw_value in valid_config_tokens:
            continue
        tokens = {token.strip() for token in raw_value.split(";") if token.strip()}
        if not tokens or not tokens.issubset(CONFIGURATION_SCOPE_REQUIRED_IDS | {"all"}):
            raise ValueError(f"s2_builder_input_schema_alignment.csv contains unsupported applies_to_configuration value: {raw_value}")

    blocked_row = alignment.loc[alignment["builder_input_gate_name"].eq(SCHEMA_ALIGNMENT_REQUIRED_BLOCKED_GATE)]
    if blocked_row.empty:
        raise ValueError("s2_builder_input_schema_alignment.csv must include a validation_targets gate row.")
    blocked_row = blocked_row.iloc[0]
    if blocked_row["approval_status"] != "blocked":
        raise ValueError("validation_targets schema-alignment row must remain blocked.")
    if "validation_target_as_constraint" not in str(blocked_row["forbidden_status"]):
        raise ValueError("validation_targets schema-alignment row must explicitly forbid validation_target_as_constraint.")

    annual_block_rows = alignment[alignment["builder_input_gate_name"].isin(SCHEMA_ALIGNMENT_REQUIRED_ANNUAL_BLOCKED_GATES)]
    if annual_block_rows.empty or set(annual_block_rows["builder_input_gate_name"]) != SCHEMA_ALIGNMENT_REQUIRED_ANNUAL_BLOCKED_GATES:
        raise ValueError("s2_builder_input_schema_alignment.csv must cover every annual-anchor blocker gate.")
    if (~annual_block_rows["approval_blocker"].astype(str).str.lower().str.contains("annual|hourly")).any():
        raise ValueError("Annual-anchor schema-alignment rows must mention annual/hourly blockers explicitly.")

    reporting_rows = alignment[alignment["future_approved_table"].astype(str).str.strip().eq("run_reporting_requirements.csv")]
    if len(reporting_rows) != 5:
        raise ValueError("s2_builder_input_schema_alignment.csv must map five reporting fields to run_reporting_requirements.csv.")

    alignment_scan = alignment.astype(str).agg(" ".join, axis=1).str.lower()
    forbidden_scope_pattern = "|".join(APPROVED_INPUT_FORBIDDEN_SCOPE_PATTERNS)
    allowed_optional_scope_rows = alignment["builder_input_gate_name"].astype(str).str.strip().isin({"validation_targets"})
    if (alignment_scan.str.contains(forbidden_scope_pattern, regex=True) & ~allowed_optional_scope_rows).any():
        raise ValueError("s2_builder_input_schema_alignment.csv must not introduce blocked later-stage or horizon scope in executable gate rows.")

    return {
        "schema_alignment_rows_checked": int(len(alignment)),
        "schema_alignment_required_gate_count": int(len(SCHEMA_ALIGNMENT_REQUIRED_GATE_NAMES)),
    }


def validate_s2_approved_model_input(approved_input_bundle: GovernanceTableBundle) -> dict[str, Any]:
    tables = approved_input_bundle.tables
    table_names = set(tables)
    if table_names != APPROVED_INPUT_REQUIRED_TABLES:
        missing = sorted(APPROVED_INPUT_REQUIRED_TABLES - table_names)
        extra = sorted(table_names - APPROVED_INPUT_REQUIRED_TABLES)
        raise ValueError(f"s2_approved_model_input tables do not match the required shell set. missing={missing} extra={extra}")

    if not APPROVED_INPUT_README.exists():
        raise ValueError("s2_approved_model_input/README.md must exist.")
    readme_text = APPROVED_INPUT_README.read_text(encoding="utf-8").lower()
    required_readme_phrases = (
        "currently empty",
        "no value may be copied",
        "validation targets cannot be used as constraints",
        "annual values cannot become hourly caps",
        "not yet thesis-usable or executable",
        "promotion protocol",
        "codex cannot approve values",
        "approved and executable statuses are separate",
        "promotion decision records",
    )
    for phrase in required_readme_phrases:
        if phrase not in readme_text:
            raise ValueError(f"s2_approved_model_input/README.md is missing required phrase: {phrase}")

    approved_row_count = 0
    thesis_grade_numerical_row_count = 0
    executable_row_count = 0
    total_data_rows = 0
    forbidden_scope_pattern = "|".join(APPROVED_INPUT_FORBIDDEN_SCOPE_PATTERNS)

    for filename, required_columns in APPROVED_INPUT_FILE_SPECS.items():
        frame = tables[filename]
        if set(required_columns) - set(frame.columns):
            raise ValueError(f"{filename} is missing required approved-input columns.")
        total_data_rows += int(len(frame))
        if len(frame) != 0:
            raise ValueError(f"{filename} must remain an empty approved-input shell with headers only.")

        lower_columns = [column.lower() for column in frame.columns]
        if any(re.search(forbidden_scope_pattern, column) for column in lower_columns):
            raise ValueError(f"{filename} contains forbidden later-stage or blocked-scope column names.")
        if not APPROVED_INPUT_REQUIRED_METADATA_COLUMNS.issubset(frame.columns):
            missing_columns = sorted(APPROVED_INPUT_REQUIRED_METADATA_COLUMNS - set(frame.columns))
            raise ValueError(f"{filename} is missing required governance metadata columns: {missing_columns}")

        if filename in APPROVED_INPUT_TABLES_REQUIRING_TRANSLATION_STATUS and "annual_to_hourly_translation_status" not in frame.columns:
            raise ValueError(f"{filename} must carry annual_to_hourly_translation_status.")
        if filename == "validation_targets.csv" and "constraint_usage_status" not in frame.columns:
            raise ValueError("validation_targets.csv must carry constraint_usage_status.")

        if not frame.empty:
            approved_row_count += int(frame["approval_status"].astype(str).str.strip().str.lower().eq("approved").sum())
            thesis_grade_numerical_row_count += int(frame["thesis_usability"].astype(str).str.strip().str.lower().eq("true").sum())
            executable_row_count += int(frame["executable_status"].astype(str).str.strip().str.lower().eq("executable").sum())
            required_non_empty_columns = {"source_ids", "unit", "approval_status", "executable_status", "thesis_usability", "approved_by", "approval_date"}
            missing_columns = required_non_empty_columns - set(frame.columns)
            if missing_columns:
                raise ValueError(f"{filename} is missing required non-empty columns for future approved rows: {sorted(missing_columns)}")
            for column in required_non_empty_columns:
                if frame[column].astype(str).str.strip().eq("").any():
                    raise ValueError(f"{filename} contains empty values in required future approved-row column {column}.")
            if (~frame["approval_status"].astype(str).str.strip().str.lower().isin(APPROVED_INPUT_ALLOWED_APPROVAL_STATUSES)).any():
                raise ValueError(f"{filename} contains non-approved approval_status values.")
            if (~frame["executable_status"].astype(str).str.strip().str.lower().isin(APPROVED_INPUT_ALLOWED_EXECUTABLE_STATUSES)).any():
                raise ValueError(f"{filename} contains non-executable executable_status values.")
            if (~frame["thesis_usability"].astype(str).str.strip().str.lower().isin(APPROVED_INPUT_ALLOWED_THESIS_USABILITY)).any():
                raise ValueError(f"{filename} contains non-thesis-usable rows.")

    return {
        "approved_input_tables_checked": int(len(tables)),
        "approved_input_total_rows": total_data_rows,
        "approved_input_approved_rows": approved_row_count,
        "approved_input_thesis_grade_numerical_rows": thesis_grade_numerical_row_count,
        "approved_input_executable_rows": executable_row_count,
        "approved_input_readme_present": True,
    }


def validate_s2_human_review_packets(review_root: str | Path) -> dict[str, Any]:
    review_root = Path(review_root).resolve()
    data_dir = review_root / HUMAN_REVIEW_PACKET_DATA_DIR_NAME
    if not data_dir.exists():
        raise ValueError("s2_human_review_packets data folder must exist.")
    if not HUMAN_REVIEW_PACKET_DOC_DIR.exists():
        raise ValueError("docs/optimisation/steel/s2_human_review_packets must exist.")

    total_rows = 0
    frames_by_category: dict[str, pd.DataFrame] = {}

    for filename, spec in HUMAN_REVIEW_PACKET_SUMMARY_FILE_SPECS.items():
        path = data_dir / filename
        if not path.exists():
            raise ValueError(f"{filename} must exist in s2_human_review_packets.")
        frame = _read_csv(path)
        if list(frame.columns) != HUMAN_REVIEW_PACKET_SUMMARY_COLUMNS:
            raise ValueError(f"{filename} must match the required S2.7d review-packet column order.")
        if frame.empty:
            raise ValueError(f"{filename} must contain at least one review-packet row.")
        if frame["review_packet_id"].astype(str).str.strip().duplicated().any():
            raise ValueError(f"{filename} must not contain duplicate review_packet_id values.")
        if (~frame["review_category"].astype(str).str.strip().eq(spec["review_category"])).any():
            raise ValueError(f"{filename} must use review_category={spec['review_category']} for every row.")
        if (~frame["target_approved_table"].astype(str).str.strip().eq(spec["target_approved_table"])).any():
            raise ValueError(f"{filename} must target {spec['target_approved_table']} for every row.")
        if (~frame["reviewer_decision_required"].astype(str).str.strip().str.lower().eq("true")).any():
            raise ValueError(f"{filename} must keep reviewer_decision_required=true for every row.")
        if (~frame["codex_may_decide"].astype(str).str.strip().str.lower().eq("false")).any():
            raise ValueError(f"{filename} must keep codex_may_decide=false for every row.")
        if (~frame["executable_status"].astype(str).str.strip().str.lower().eq("non_executable")).any():
            raise ValueError(f"{filename} must keep executable_status=non_executable for every row.")
        if (~frame["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
            raise ValueError(f"{filename} must keep thesis_usability=false for every row.")
        if (~frame["approval_status"].astype(str).str.strip().str.lower().isin(HUMAN_REVIEW_PACKET_ALLOWED_APPROVAL_STATUSES)).any():
            raise ValueError(f"{filename} contains invalid review-packet approval_status values.")
        if frame["approval_status"].astype(str).str.strip().str.lower().eq("approved").any():
            raise ValueError(f"{filename} must not mark any row approved.")
        if frame["candidate_source_table"].astype(str).str.lower().str.contains("validation_targets_candidate_review.csv").any():
            raise ValueError(f"{filename} must not repurpose validation targets as live review-packet candidates.")
        outcomes = frame["possible_reviewer_outcomes"].astype(str).str.lower()
        required_outcome_tokens = ("approve_later", "approve_only_as_sensitivity", "defer", "reject")
        for token in required_outcome_tokens:
            if (~outcomes.str.contains(token)).any():
                raise ValueError(f"{filename} must enumerate reviewer outcome token {token} on every row.")

        frame_text = " ".join(frame.astype(str).agg(" ".join, axis=1).str.lower())
        if spec["review_category"] == "inventory_endpoint_policy":
            for phrase in ("cyc50", "capacity", "operational_truth"):
                if phrase not in frame_text:
                    raise ValueError(f"{filename} must keep CYC50 policy review separate from capacity approval and operational truth claims.")
        elif spec["review_category"] == "terminal_inventory_rules":
            for phrase in ("fake_flexibility", "horizon_borrowing", "penalty"):
                if phrase not in frame_text:
                    raise ValueError(f"{filename} must flag fake flexibility and horizon borrowing risk explicitly.")
        elif spec["review_category"] == "initial_inventory_rules":
            for phrase in ("percentage_of_capacity", "absolute_quantity", "store_capacity_approval"):
                if phrase not in frame_text:
                    raise ValueError(f"{filename} must keep formula review separate from absolute quantity approval.")

        total_rows += int(len(frame))
        frames_by_category[spec["review_category"]] = frame

    if not HUMAN_REVIEW_PACKET_DASHBOARD.exists():
        raise ValueError("s2_first_promotion_review_dashboard.csv must exist.")
    dashboard = _read_csv(HUMAN_REVIEW_PACKET_DASHBOARD)
    if list(dashboard.columns) != HUMAN_REVIEW_PACKET_DASHBOARD_COLUMNS:
        raise ValueError("s2_first_promotion_review_dashboard.csv must match the required S2.7d dashboard column order.")
    expected_categories = {spec["review_category"] for spec in HUMAN_REVIEW_PACKET_SUMMARY_FILE_SPECS.values()}
    actual_categories = set(dashboard["review_category"].astype(str).str.strip())
    if actual_categories != expected_categories:
        missing = sorted(expected_categories - actual_categories)
        extra = sorted(actual_categories - expected_categories)
        raise ValueError(f"s2_first_promotion_review_dashboard.csv category mismatch. missing={missing} extra={extra}")

    for record in dashboard.to_dict(orient="records"):
        category = str(record["review_category"]).strip()
        frame = frames_by_category[category]
        expected_candidate_count = len(frame)
        expected_high_confidence_count = int(frame["evidence_status"].astype(str).str.strip().str.lower().str.startswith("high_").sum())
        expected_sensitivity_required_count = int(frame["sensitivity_required"].astype(str).str.strip().str.lower().eq("true").sum())
        expected_blocked_or_defer_count = int(frame["approval_status"].astype(str).str.strip().str.lower().isin({"blocked", "defer_pending_review"}).sum())
        expected_missing_source_count = int(frame["evidence_status"].astype(str).str.strip().str.lower().str.contains("missing_reviewed_evidence").sum())
        expected_missing_unit_or_basis_count = int(frame["unit_or_basis"].astype(str).str.strip().str.lower().str.contains("unresolved").sum())
        expected_human_decision_needed_count = int(frame["reviewer_decision_required"].astype(str).str.strip().str.lower().eq("true").sum())
        numeric_expectations = {
            "candidate_count": expected_candidate_count,
            "high_confidence_candidate_count": expected_high_confidence_count,
            "sensitivity_required_count": expected_sensitivity_required_count,
            "blocked_or_defer_count": expected_blocked_or_defer_count,
            "missing_source_count": expected_missing_source_count,
            "missing_unit_or_basis_count": expected_missing_unit_or_basis_count,
            "human_decision_needed_count": expected_human_decision_needed_count,
        }
        for field_name, expected_value in numeric_expectations.items():
            if int(record[field_name]) != expected_value:
                raise ValueError(f"s2_first_promotion_review_dashboard.csv mismatch for {category} field {field_name}: expected {expected_value} found {record[field_name]}")
        for field_name in ("recommended_review_priority", "main_blocker", "next_human_action"):
            if str(record[field_name]).strip() == "":
                raise ValueError(f"s2_first_promotion_review_dashboard.csv must keep {field_name} non-empty for {category}.")

    for filename, phrases in HUMAN_REVIEW_PACKET_MEMO_REQUIRED_PHRASES.items():
        path = HUMAN_REVIEW_PACKET_DOC_DIR / filename
        if not path.exists():
            raise ValueError(f"{filename} must exist in docs/optimisation/steel/s2_human_review_packets.")
        text = path.read_text(encoding="utf-8").lower()
        for phrase in phrases:
            if phrase not in text:
                raise ValueError(f"{filename} is missing required review-packet phrase: {phrase}")

    return {
        "human_review_packet_files_checked": int(len(HUMAN_REVIEW_PACKET_SUMMARY_FILE_SPECS)),
        "human_review_packet_rows_checked": int(total_rows),
        "human_review_packet_dashboard_present": True,
        "human_review_packet_memos_present": int(len(HUMAN_REVIEW_PACKET_MEMO_REQUIRED_PHRASES)),
    }


def validate_s2_human_policy_bundle(review_bundle: GovernanceTableBundle) -> dict[str, Any]:
    if not HUMAN_POLICY_DECISION_BUNDLE_MEMO.exists():
        raise ValueError("STEEL_S2_HUMAN_POLICY_DECISION_BUNDLE.md must exist.")
    memo_text = HUMAN_POLICY_DECISION_BUNDLE_MEMO.read_text(encoding="utf-8").lower()
    for phrase in HUMAN_POLICY_DECISION_BUNDLE_MEMO_REQUIRED_PHRASES:
        if phrase not in memo_text:
            raise ValueError(f"STEEL_S2_HUMAN_POLICY_DECISION_BUNDLE.md is missing required phrase: {phrase}")

    decision_bundle = review_bundle.tables["s2_human_policy_decision_bundle.csv"]
    if list(decision_bundle.columns) != HUMAN_POLICY_DECISION_BUNDLE_COLUMNS:
        raise ValueError("s2_human_policy_decision_bundle.csv must match the required column order.")
    if decision_bundle["decision_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_human_policy_decision_bundle.csv must not contain duplicate decision_id values.")
    if not HUMAN_POLICY_DECISION_BUNDLE_REQUIRED_CLUSTERS.issubset(set(decision_bundle["decision_cluster"].astype(str).str.strip())):
        missing = sorted(HUMAN_POLICY_DECISION_BUNDLE_REQUIRED_CLUSTERS - set(decision_bundle["decision_cluster"].astype(str).str.strip()))
        raise ValueError(f"s2_human_policy_decision_bundle.csv is missing required decision clusters: {missing}")
    if not HUMAN_POLICY_DECISION_BUNDLE_REQUIRED_ITEMS.issubset(set(decision_bundle["decision_item"].astype(str).str.strip())):
        missing = sorted(HUMAN_POLICY_DECISION_BUNDLE_REQUIRED_ITEMS - set(decision_bundle["decision_item"].astype(str).str.strip()))
        raise ValueError(f"s2_human_policy_decision_bundle.csv is missing required decision items: {missing}")
    if (~decision_bundle["approval_status"].astype(str).str.strip().str.lower().isin(HUMAN_POLICY_DECISION_BUNDLE_ALLOWED_APPROVAL_STATUSES)).any():
        raise ValueError("s2_human_policy_decision_bundle.csv contains invalid approval_status values.")
    if (~decision_bundle["executable_status"].astype(str).str.strip().str.lower().eq("non_executable")).any():
        raise ValueError("s2_human_policy_decision_bundle.csv must keep executable_status=non_executable for every row.")
    if (~decision_bundle["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_human_policy_decision_bundle.csv must keep thesis_usability=false for every row.")
    if decision_bundle["approval_status"].astype(str).str.lower().str.contains("approved").any():
        raise ValueError("s2_human_policy_decision_bundle.csv must not mark any row approved.")
    if (~decision_bundle["codex_allowed_role"].astype(str).str.lower().str.contains("record")).any():
        raise ValueError("Every human policy decision row must limit Codex to recording/applying explicit policy only.")
    if (~decision_bundle["codex_forbidden_role"].astype(str).str.lower().str.contains("approve|promote|populate")).any():
        raise ValueError("Every human policy decision row must explicitly forbid approval/promotion/population actions.")

    forbidden_numeric_text_columns = [
        "human_decision",
        "modelling_interpretation",
        "unresolved_blocker",
        "notes",
    ]
    for column in forbidden_numeric_text_columns:
        if decision_bundle[column].astype(str).str.contains(HUMAN_POLICY_NUMERIC_FORBIDDEN_PATTERN).any():
            raise ValueError(f"s2_human_policy_decision_bundle.csv contains exact numerical executable-style values in {column}.")

    decision_text = " ".join(decision_bundle.astype(str).agg(" ".join, axis=1).str.lower())
    for required_phrase in (
        "capacity_approval",
        "not_main_strategic_flexibility",
        "positive_magnitudes_with_explicit_role_fields",
        "annual_public_values_are_validation_or_scaling_anchors_only",
        "no_route_specific_production_target",
    ):
        if required_phrase not in decision_text:
            raise ValueError(f"s2_human_policy_decision_bundle.csv must include policy phrase: {required_phrase}")

    backlog = review_bundle.tables["s2_future_parameter_review_backlog.csv"]
    if list(backlog.columns) != FUTURE_PARAMETER_REVIEW_BACKLOG_COLUMNS:
        raise ValueError("s2_future_parameter_review_backlog.csv must match the required column order.")
    if backlog["backlog_item_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_future_parameter_review_backlog.csv must not contain duplicate backlog_item_id values.")
    backlog_categories = set(backlog["parameter_category"].astype(str).str.strip())
    if not FUTURE_PARAMETER_REVIEW_BACKLOG_REQUIRED_CATEGORIES.issubset(backlog_categories):
        missing = sorted(FUTURE_PARAMETER_REVIEW_BACKLOG_REQUIRED_CATEGORIES - backlog_categories)
        raise ValueError(f"s2_future_parameter_review_backlog.csv is missing required backlog categories: {missing}")
    if (~backlog["review_priority"].astype(str).str.strip().isin({"high", "medium", "low"})).any():
        raise ValueError("s2_future_parameter_review_backlog.csv must use high/medium/low review priorities only.")
    if (~backlog["sensitivity_likely_required"].astype(str).str.strip().str.lower().isin({"true", "false"})).any():
        raise ValueError("s2_future_parameter_review_backlog.csv must keep sensitivity_likely_required as true/false.")
    if backlog["parameter_category"].astype(str).str.strip().eq("store_capacity_sensitivity_ranges").sum() != 1:
        raise ValueError("s2_future_parameter_review_backlog.csv must include exactly one store_capacity_sensitivity_ranges row.")
    if backlog["parameter_category"].astype(str).str.strip().eq("validation_target_selection").sum() != 1:
        raise ValueError("s2_future_parameter_review_backlog.csv must include exactly one validation_target_selection row.")

    return {
        "human_policy_bundle_memo_present": True,
        "human_policy_decision_rows_checked": int(len(decision_bundle)),
        "future_parameter_review_backlog_rows_checked": int(len(backlog)),
    }


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
    configuration_tag_mapping = tables["s2_configuration_tag_mapping.csv"]
    model_builder_contract = tables["s2_model_builder_interface_contract.csv"]
    promotion_protocol = tables["s2_approved_input_promotion_protocol.csv"]
    promotion_review_criteria = {
        name: tables[name]
        for name in PROMOTION_REVIEW_CRITERIA_FILE_SPECS
    }
    decision_template_path = review_bundle.root / PROMOTION_DECISION_TEMPLATE.name
    decision_template = _read_csv(decision_template_path)
    topology_bundle = load_s2_topology_skeleton(review_bundle.root)
    human_review_packet_payload = validate_s2_human_review_packets(review_bundle.root)
    human_policy_bundle_payload = validate_s2_human_policy_bundle(review_bundle)

    if not PROMOTION_PROTOCOL_MEMO.exists():
        raise ValueError("STEEL_S2_APPROVED_INPUT_PROMOTION_PROTOCOL.md must exist.")
    memo_text = PROMOTION_PROTOCOL_MEMO.read_text(encoding="utf-8").lower()
    required_memo_phrases = (
        "candidate-review",
        "approved assumption",
        "thesis-grade numerical input",
        "executable model input",
        "codex may prepare review packets but may not approve rows",
        "explicit user/thesis-review approval is required",
        "approval and executable status are separate gates",
        "annual-to-hourly translation approval",
        "deepsearch f",
        "cyc50",
    )
    for phrase in required_memo_phrases:
        if phrase not in memo_text:
            raise ValueError(f"STEEL_S2_APPROVED_INPUT_PROMOTION_PROTOCOL.md is missing required phrase: {phrase}")

    if not PROMOTION_REVIEW_CRITERIA_DIR.exists():
        raise ValueError("s2_promotion_review_criteria folder must exist.")
    criteria_basenames = {Path(name).name for name in promotion_review_criteria}
    if criteria_basenames != PROMOTION_REVIEW_CRITERIA_REQUIRED_BASE_FILENAMES:
        missing = sorted(PROMOTION_REVIEW_CRITERIA_REQUIRED_BASE_FILENAMES - criteria_basenames)
        extra = sorted(criteria_basenames - PROMOTION_REVIEW_CRITERIA_REQUIRED_BASE_FILENAMES)
        raise ValueError(f"s2_promotion_review_criteria file set mismatch. missing={missing} extra={extra}")

    if list(decision_template.columns) != PROMOTION_DECISION_TEMPLATE_COLUMNS:
        raise ValueError("s2_promotion_decision_template.csv does not match the required header.")
    if len(decision_template) != 0:
        raise ValueError("s2_promotion_decision_template.csv must remain header-only with zero data rows.")

    protocol_categories = set(promotion_protocol["category"].astype(str).str.strip())
    if not PROMOTION_PROTOCOL_REQUIRED_CATEGORIES.issubset(protocol_categories):
        missing = sorted(PROMOTION_PROTOCOL_REQUIRED_CATEGORIES - protocol_categories)
        raise ValueError(f"s2_approved_input_promotion_protocol.csv is missing required categories: {missing}")
    if promotion_protocol["protocol_rule_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_approved_input_promotion_protocol.csv must not contain duplicate protocol_rule_id values.")
    if (~promotion_protocol["executable_status"].astype(str).str.strip().str.lower().eq("non_executable")).any():
        raise ValueError("s2_approved_input_promotion_protocol.csv must keep every row non_executable.")
    if (~promotion_protocol["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_approved_input_promotion_protocol.csv must keep thesis_usability=false for all rows.")
    protocol_approval_statuses = set(promotion_protocol["approval_status"].astype(str).str.strip().str.lower())
    if not protocol_approval_statuses.issubset(PROMOTION_PROTOCOL_ALLOWED_APPROVAL_STATUSES):
        raise ValueError("s2_approved_input_promotion_protocol.csv contains invalid approval_status values.")
    if (~promotion_protocol["user_review_required"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("Every promotion protocol row must require explicit user/reviewer approval.")
    if (~promotion_protocol["executable_gate_required"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("Every promotion protocol row must preserve the separate executable gate.")
    if promotion_protocol["codex_allowed_role"].astype(str).str.lower().str.contains("approve|select_base_case|select_value|populate_approved_table", regex=True).any():
        raise ValueError("s2_approved_input_promotion_protocol.csv must not grant Codex approval or value-selection authority.")
    if (~promotion_protocol["codex_forbidden_role"].astype(str).str.lower().str.contains("approve|promote_without_decision|populate_approved_table", regex=True)).any():
        raise ValueError("Every promotion protocol row must explicitly forbid Codex approval or silent promotion.")
    if promotion_protocol["forbidden_action"].astype(str).str.lower().str.contains("make_executable_now|approve_numerical_value_now", regex=True).sum() < 2:
        raise ValueError("Promotion protocol must explicitly forbid immediate approval and executable activation.")

    for category, expected_target_table in PROMOTION_PROTOCOL_REQUIRED_TARGET_TABLES_BY_CATEGORY.items():
        matching_rows = promotion_protocol["category"].astype(str).str.strip().eq(category)
        if not matching_rows.any():
            continue
        actual_targets = set(promotion_protocol.loc[matching_rows, "target_approved_table"].astype(str).str.strip())
        if actual_targets != {expected_target_table}:
            raise ValueError(
                f"s2_approved_input_promotion_protocol.csv must map {category} to {expected_target_table}. found={sorted(actual_targets)}"
            )

    validation_protocol_rows = promotion_protocol["category"].astype(str).str.strip().eq("validation_targets")
    if validation_protocol_rows.any():
        row_text = promotion_protocol.loc[validation_protocol_rows].astype(str).agg(" ".join, axis=1).str.lower()
        if (~row_text.str.contains("constraint")).any():
            raise ValueError("validation_targets promotion protocol row must explicitly block constraint use.")

    annual_protocol_rows = promotion_protocol["category"].astype(str).str.strip().eq("annual_to_hourly_translation")
    if annual_protocol_rows.any():
        annual_text = promotion_protocol.loc[annual_protocol_rows].astype(str).agg(" ".join, axis=1).str.lower()
        if (~annual_text.str.contains("explicit")).any() or (~annual_text.str.contains("annual")).any() or (~annual_text.str.contains("hourly")).any():
            raise ValueError("annual_to_hourly_translation protocol row must require explicit annual-to-hourly approval.")

    c1s_protocol_rows = promotion_protocol["category"].astype(str).str.strip().eq("c1s_sensitivity_overlay")
    if c1s_protocol_rows.any():
        c1s_text = promotion_protocol.loc[c1s_protocol_rows].astype(str).agg(" ".join, axis=1).str.lower()
        if (~c1s_text.str.contains("overlay")).any():
            raise ValueError("c1s_sensitivity_overlay protocol row must keep C1S as overlay-only.")

    c2_protocol_rows = promotion_protocol["category"].astype(str).str.strip().eq("c2_optional_later_exogenous_hydrogen")
    if c2_protocol_rows.any():
        c2_text = promotion_protocol.loc[c2_protocol_rows].astype(str).agg(" ".join, axis=1).str.lower()
        if (~c2_text.str.contains("optional later")).any() or (~c2_text.str.contains("exogenous")).any():
            raise ValueError("c2_optional_later_exogenous_hydrogen protocol row must keep C2 optional-later and exogenous only.")

    for criteria_name, criteria_frame in promotion_review_criteria.items():
        if criteria_frame.empty:
            raise ValueError(f"{criteria_name} must contain at least one review criterion row.")
        if criteria_frame["criterion_id"].astype(str).str.strip().duplicated().any():
            raise ValueError(f"{criteria_name} must not contain duplicate criterion_id values.")
        if (~criteria_frame["reviewer_decision_required"].astype(str).str.strip().str.lower().eq("true")).any():
            raise ValueError(f"{criteria_name} must require reviewer_decision_required=true for every row.")
        if (~criteria_frame["codex_may_decide"].astype(str).str.strip().str.lower().eq("false")).any():
            raise ValueError(f"{criteria_name} must keep codex_may_decide=false for every row.")
        if (~criteria_frame["codex_may_check"].astype(str).str.strip().str.lower().eq("true")).any():
            raise ValueError(f"{criteria_name} must keep codex_may_check=true for every row.")
        criteria_approval_statuses = set(criteria_frame["approval_status"].astype(str).str.strip().str.lower())
        if not criteria_approval_statuses.issubset(PROMOTION_REVIEW_CRITERIA_ALLOWED_APPROVAL_STATUSES):
            raise ValueError(f"{criteria_name} contains invalid approval_status values.")

    validation_criteria_text = promotion_review_criteria["s2_promotion_review_criteria/validation_targets_review_criteria.csv"].astype(str).agg(" ".join, axis=1).str.lower()
    if (~validation_criteria_text.str.contains("constraint")).all():
        raise ValueError("validation_targets_review_criteria.csv must explicitly block constraint use.")
    production_criteria_text = promotion_review_criteria["s2_promotion_review_criteria/production_targets_review_criteria.csv"].astype(str).agg(" ".join, axis=1).str.lower()
    if (~production_criteria_text.str.contains("target basis|target_basis", regex=True)).all():
        raise ValueError("production_targets_review_criteria.csv must require target-basis clarity.")
    process_bounds_criteria_text = promotion_review_criteria["s2_promotion_review_criteria/process_bounds_review_criteria.csv"].astype(str).agg(" ".join, axis=1).str.lower()
    if (~process_bounds_criteria_text.str.contains("annual-to-hourly|annual to hourly", regex=True)).all():
        raise ValueError("process_bounds_review_criteria.csv must require annual-to-hourly review.")
    if (~process_bounds_criteria_text.str.contains("operating envelope")).all():
        raise ValueError("process_bounds_review_criteria.csv must require operating-envelope review.")
    store_capacities_criteria_text = promotion_review_criteria["s2_promotion_review_criteria/store_capacities_review_criteria.csv"].astype(str).agg(" ".join, axis=1).str.lower()
    if (~store_capacities_criteria_text.str.contains("flexibility")).all() or (~store_capacities_criteria_text.str.contains("risk")).all():
        raise ValueError("store_capacities_review_criteria.csv must flag flexibility-value risk.")
    inventory_endpoint_criteria_text = promotion_review_criteria["s2_promotion_review_criteria/inventory_endpoint_policies_review_criteria.csv"].astype(str).agg(" ".join, axis=1).str.lower()
    if (~inventory_endpoint_criteria_text.str.contains("endpoint policy")).all() or (~inventory_endpoint_criteria_text.str.contains("capacity")).all():
        raise ValueError("inventory_endpoint_policies_review_criteria.csv must distinguish endpoint-policy logic from capacity approval.")

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

    mapping_ids = set(configuration_tag_mapping["mapped_configuration_id"].astype(str).str.strip())
    if not mapping_ids.issubset(CONFIGURATION_TAG_MAPPING_ALLOWED_CONFIG_IDS):
        invalid = sorted(mapping_ids - CONFIGURATION_TAG_MAPPING_ALLOWED_CONFIG_IDS)
        raise ValueError(f"s2_configuration_tag_mapping.csv contains unsupported mapped_configuration_id values: {invalid}")

    legacy_tags = set(configuration_tag_mapping["legacy_tag"].astype(str).str.strip())
    if not CONFIGURATION_TAG_MAPPING_REQUIRED_LEGACY_TAGS.issubset(legacy_tags):
        missing = sorted(CONFIGURATION_TAG_MAPPING_REQUIRED_LEGACY_TAGS - legacy_tags)
        raise ValueError(f"s2_configuration_tag_mapping.csv is missing required legacy tags: {missing}")
    if not CONFIGURATION_TAG_MAPPING_REQUIRED_BLOCKED_TAGS.issubset(legacy_tags):
        missing = sorted(CONFIGURATION_TAG_MAPPING_REQUIRED_BLOCKED_TAGS - legacy_tags)
        raise ValueError(f"s2_configuration_tag_mapping.csv is missing required blocked legacy tags: {missing}")
    if not CONFIGURATION_SCOPE_REQUIRED_IDS.issubset(mapping_ids):
        missing = sorted(CONFIGURATION_SCOPE_REQUIRED_IDS - mapping_ids)
        raise ValueError(f"s2_configuration_tag_mapping.csv does not recognise every frozen configuration ID. missing={missing}")

    if (~configuration_tag_mapping["executable_status"].astype(str).str.strip().str.lower().eq("non_executable")).any():
        raise ValueError("s2_configuration_tag_mapping.csv must keep every mapping row non_executable.")
    if (~configuration_tag_mapping["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_configuration_tag_mapping.csv must keep thesis_usability=false for all rows.")
    mapping_approval_statuses = set(configuration_tag_mapping["approval_status"].astype(str).str.strip().str.lower())
    if not mapping_approval_statuses.issubset(CONFIGURATION_TAG_MAPPING_ALLOWED_APPROVAL_STATUSES):
        raise ValueError("s2_configuration_tag_mapping.csv contains approval statuses outside not_approved/scope_mapping_only/blocked.")

    for mapped_id, expected_role in CONFIGURATION_TAG_MAPPING_REQUIRED_ROLE_BY_ID.items():
        id_rows = configuration_tag_mapping["mapped_configuration_id"].astype(str).str.strip().eq(mapped_id)
        if id_rows.any():
            actual_roles = set(configuration_tag_mapping.loc[id_rows, "mapped_configuration_role"].astype(str).str.strip())
            if actual_roles != {expected_role}:
                raise ValueError(
                    f"s2_configuration_tag_mapping.csv must keep mapped_configuration_role={expected_role} for every {mapped_id} row."
                )

    blocked_rows = configuration_tag_mapping["approval_status"].astype(str).str.strip().str.lower().eq("blocked")
    if blocked_rows.any():
        bad_blocked_ids = configuration_tag_mapping.loc[blocked_rows, "mapped_configuration_id"].astype(str).str.strip().ne(CONFIGURATION_TAG_MAPPING_BLOCKED_ID)
        if bad_blocked_ids.any():
            raise ValueError("Blocked configuration-tag mapping rows must map to postponed_or_blocked.")

    if configuration_tag_mapping["mapped_configuration_role"].astype(str).str.strip().isin({"main_configuration", "reference_configuration"}).sum() < 2:
        raise ValueError("s2_configuration_tag_mapping.csv must preserve the main/reference mapping for C0 and C1.")
    non_main_role_rows = configuration_tag_mapping["mapped_configuration_id"].astype(str).str.strip().isin({"C1S_phase1_sensitivity_variants", "C2_exogenous_hydrogen_sensitivity_optional_later", "postponed_or_blocked"})
    if configuration_tag_mapping.loc[non_main_role_rows, "mapped_configuration_role"].astype(str).str.strip().isin({"main_configuration", "reference_configuration"}).any():
        raise ValueError("C1S, C2, and blocked mapping rows must not be labelled as main/reference configurations.")

    c1s_rows = configuration_tag_mapping["mapped_configuration_id"].astype(str).str.strip().eq("C1S_phase1_sensitivity_variants")
    if c1s_rows.any():
        if (~configuration_tag_mapping.loc[c1s_rows, "mapped_configuration_role"].astype(str).str.strip().eq("sensitivity_only_within_C1")).any():
            raise ValueError("C1S mapping rows must remain sensitivity-only within C1.")
    c2_rows = configuration_tag_mapping["mapped_configuration_id"].astype(str).str.strip().eq("C2_exogenous_hydrogen_sensitivity_optional_later")
    if c2_rows.any():
        if (~configuration_tag_mapping.loc[c2_rows, "mapped_configuration_role"].astype(str).str.strip().eq("optional_later_sensitivity_only")).any():
            raise ValueError("C2 mapping rows must remain optional-later sensitivity-only.")

    blocked_legacy_rows = configuration_tag_mapping["legacy_tag"].astype(str).str.strip().isin(CONFIGURATION_TAG_MAPPING_REQUIRED_BLOCKED_TAGS)
    if blocked_legacy_rows.any():
        if (~configuration_tag_mapping.loc[blocked_legacy_rows, "mapped_configuration_id"].astype(str).str.strip().eq(CONFIGURATION_TAG_MAPPING_BLOCKED_ID)).any():
            raise ValueError("Phase 2/Phase 3/full-hydrogen/electrolysis/hydrogen-storage/SAF/CCS tags must map to postponed_or_blocked.")

    mapping_scan = configuration_tag_mapping.astype(str).agg(" ".join, axis=1).str.lower()
    mapping_forbidden_horizon_pattern = "|".join(CONFIGURATION_TAG_MAPPING_FORBIDDEN_HORIZON_PATTERNS)
    if mapping_scan.str.contains(mapping_forbidden_horizon_pattern, regex=True).any():
        raise ValueError("s2_configuration_tag_mapping.csv must not introduce D-only/D+4 comparison categories.")

    contract_ids = set(model_builder_contract["contract_item_id"].astype(str).str.strip())
    if contract_ids != MODEL_BUILDER_CONTRACT_REQUIRED_IDS:
        missing = sorted(MODEL_BUILDER_CONTRACT_REQUIRED_IDS - contract_ids)
        extra = sorted(contract_ids - MODEL_BUILDER_CONTRACT_REQUIRED_IDS)
        raise ValueError(f"s2_model_builder_interface_contract.csv does not match required contract rows. missing={missing} extra={extra}")
    if model_builder_contract["contract_item_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_model_builder_interface_contract.csv must not contain duplicate contract_item_id values.")
    if (~model_builder_contract["executable_status"].astype(str).str.strip().str.lower().eq("non_executable")).any():
        raise ValueError("s2_model_builder_interface_contract.csv must keep every row non_executable.")
    if (~model_builder_contract["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_model_builder_interface_contract.csv must keep thesis_usability=false for all rows.")
    contract_approval_statuses = set(model_builder_contract["approval_status"].astype(str).str.strip().str.lower())
    if not contract_approval_statuses.issubset(MODEL_BUILDER_CONTRACT_ALLOWED_APPROVAL_STATUSES):
        raise ValueError("s2_model_builder_interface_contract.csv contains approval statuses outside interface_contract_only/not_approved/blocked.")
    if model_builder_contract["allowed_status"].astype(str).str.strip().str.lower().str.contains("thesis_grade|executable|approved_model_input").any():
        raise ValueError("s2_model_builder_interface_contract.csv must not describe thesis-grade or executable model behaviour.")

    numerical_rows = set(
        model_builder_contract.loc[
            model_builder_contract["contract_layer"].astype(str).str.strip().eq("future_numerical_input_gate"),
            "required_input_or_rule",
        ].astype(str).str.strip()
    )
    if numerical_rows != MODEL_BUILDER_CONTRACT_REQUIRED_NUMERICAL_TABLE_ROWS:
        missing = sorted(MODEL_BUILDER_CONTRACT_REQUIRED_NUMERICAL_TABLE_ROWS - numerical_rows)
        extra = sorted(numerical_rows - MODEL_BUILDER_CONTRACT_REQUIRED_NUMERICAL_TABLE_ROWS)
        raise ValueError(f"s2_model_builder_interface_contract.csv numerical gate rows do not match required inputs. missing={missing} extra={extra}")

    reporting_rows = set(
        model_builder_contract.loc[
            model_builder_contract["contract_layer"].astype(str).str.strip().eq("reporting_contract"),
            "required_input_or_rule",
        ].astype(str).str.strip()
    )
    if reporting_rows != MODEL_BUILDER_CONTRACT_REQUIRED_REPORTING_ROWS:
        missing = sorted(MODEL_BUILDER_CONTRACT_REQUIRED_REPORTING_ROWS - reporting_rows)
        extra = sorted(reporting_rows - MODEL_BUILDER_CONTRACT_REQUIRED_REPORTING_ROWS)
        raise ValueError(f"s2_model_builder_interface_contract.csv reporting rows do not match required outputs. missing={missing} extra={extra}")

    refusal_rows = set(
        model_builder_contract.loc[
            model_builder_contract["contract_layer"].astype(str).str.strip().eq("refusal_rule"),
            "required_input_or_rule",
        ].astype(str).str.strip()
    )
    if refusal_rows != MODEL_BUILDER_CONTRACT_REQUIRED_REFUSAL_ROWS:
        missing = sorted(MODEL_BUILDER_CONTRACT_REQUIRED_REFUSAL_ROWS - refusal_rows)
        extra = sorted(refusal_rows - MODEL_BUILDER_CONTRACT_REQUIRED_REFUSAL_ROWS)
        raise ValueError(f"s2_model_builder_interface_contract.csv refusal rows do not match required refusal rules. missing={missing} extra={extra}")

    for row in model_builder_contract.to_dict(orient="records"):
        config_tokens = set(_split_multi_value_field(row["applies_to_configuration"]))
        if not config_tokens:
            raise ValueError("s2_model_builder_interface_contract.csv must define applies_to_configuration for every row.")
        if not config_tokens.issubset(MODEL_BUILDER_CONTRACT_ALLOWED_CONFIG_TOKENS):
            invalid = sorted(config_tokens - MODEL_BUILDER_CONTRACT_ALLOWED_CONFIG_TOKENS)
            raise ValueError(f"s2_model_builder_interface_contract.csv contains unsupported configuration tokens: {invalid}")

    main_config_rows = model_builder_contract["required_input_or_rule"].astype(str).str.strip().isin(
        {
            "configuration_selection",
            "topology_view_consumption",
            "route_membership",
            "process_unit_membership",
            "carrier_membership",
            "store_membership",
            "arc_membership",
            "inventory_endpoint_policy",
            "fixed_production_target_policy",
        }
    )
    for raw_value in model_builder_contract.loc[main_config_rows, "applies_to_configuration"]:
        config_tokens = set(_split_multi_value_field(raw_value))
        if config_tokens != MODEL_BUILDER_CONTRACT_MAIN_CONFIG_TOKENS:
            raise ValueError("Main deterministic S2 contract rows must apply only to C0 and C1.")

    c1s_rows = model_builder_contract["applies_to_configuration"].astype(str).str.strip().eq("C1S_phase1_sensitivity_variants")
    if c1s_rows.any():
        if (~model_builder_contract.loc[c1s_rows, "allowed_status"].astype(str).str.strip().eq("sensitivity_overlay_metadata_only")).any():
            raise ValueError("C1S contract rows must remain sensitivity-overlay-only.")
    c2_rows = model_builder_contract["applies_to_configuration"].astype(str).str.strip().eq("C2_exogenous_hydrogen_sensitivity_optional_later")
    if c2_rows.any():
        if (~model_builder_contract.loc[c2_rows, "allowed_status"].astype(str).str.strip().eq("optional_later_metadata_only")).any():
            raise ValueError("C2 contract rows must remain optional-later-only.")

    if (~model_builder_contract.loc[
        model_builder_contract["required_input_or_rule"].astype(str).str.strip().eq("future_validation_target_table"),
        "approval_status",
    ].astype(str).str.strip().str.lower().eq("blocked")).any():
        raise ValueError("future_validation_target_table must remain blocked in the interface contract.")
    if (~model_builder_contract.loc[
        model_builder_contract["required_input_or_rule"].astype(str).str.strip().eq("future_validation_target_table"),
        "forbidden_status",
    ].astype(str).str.contains("validation_target_as_constraint", case=False, regex=False)).any():
        raise ValueError("future_validation_target_table must explicitly forbid validation-target-as-constraint use.")
    if (~model_builder_contract.loc[
        model_builder_contract["required_input_or_rule"].astype(str).str.strip().eq("refusal_of_annual_public_anchors_as_hourly_caps"),
        "forbidden_status",
    ].astype(str).str.contains("annual_public_anchor_as_hourly_cap", case=False, regex=False)).any():
        raise ValueError("Annual public anchors must remain blocked from hourly-cap use in the interface contract.")

    contract_scan = model_builder_contract.astype(str).agg(" ".join, axis=1).str.lower()
    contract_horizon_pattern = "|".join(CONFIGURATION_SCOPE_FORBIDDEN_HORIZON_PATTERNS)
    horizon_rows = contract_scan.str.contains(contract_horizon_pattern, regex=True)
    allowed_horizon_rows = model_builder_contract["required_input_or_rule"].astype(str).str.strip().eq("refusal_of_D_only_D_plus_4_comparison_logic")
    if (horizon_rows & ~allowed_horizon_rows).any():
        raise ValueError("s2_model_builder_interface_contract.csv must not introduce D-only/D+4 scope outside the refusal row.")

    payload = {
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
        "configuration_tag_mapping_rows_checked": int(len(configuration_tag_mapping)),
        "model_builder_contract_rows_checked": int(len(model_builder_contract)),
        "promotion_protocol_memo_present": True,
        "promotion_protocol_rows_checked": int(len(promotion_protocol)),
        "promotion_review_criteria_files_checked": int(len(promotion_review_criteria)),
        "promotion_review_criteria_rows_checked": int(sum(len(frame) for frame in promotion_review_criteria.values())),
        "promotion_decision_template_rows": int(len(decision_template)),
        "thesis_grade_numerical_rows": int(classification["thesis_grade_numerical_eligibility"].astype(str).str.strip().str.lower().eq("true").sum()),
        "candidate_review_executable_rows": int(classification["executable_status"].astype(str).str.strip().str.lower().isin(EXECUTABLE_BANNED_VALUES).sum()),
        "later_stage_s2_executable_rows": int(
            classification.loc[
                later_stage_mask,
                "executable_status",
            ].astype(str).str.strip().str.lower().isin({"s2_executable"}).sum()
        ),
    }
    payload.update(validate_s2_topology_skeleton(topology_bundle))
    topology_objects = build_s2_topology_objects(topology_bundle)
    topology_object_counts = topology_objects.summary_counts()
    payload.update(
        {
            "topology_object_configuration_count": topology_object_counts["configurations"],
            "topology_object_route_count": topology_object_counts["routes"],
            "topology_object_process_unit_count": topology_object_counts["process_units"],
            "topology_object_carrier_count": topology_object_counts["carriers"],
            "topology_object_store_count": topology_object_counts["stores"],
            "topology_object_arc_count": topology_object_counts["arcs"],
            "topology_object_inventory_policy_count": topology_object_counts["inventory_policies"],
            "topology_object_warnings": list(topology_objects.warnings),
        }
    )
    topology_views = build_s2_topology_views(topology_objects)
    payload.update(
        {
            "topology_view_configuration_count": len(topology_views.configuration_views),
            "topology_view_route_count": len(topology_views.route_views),
            "topology_view_warnings": list(topology_views.warnings),
        }
    )
    payload.update(human_review_packet_payload)
    payload.update(human_policy_bundle_payload)
    return payload


def dry_run_validate_input_governance(
    *,
    config,
    schema_bundle: GovernanceTableBundle,
    mapping_bundle: GovernanceTableBundle,
    review_bundle: GovernanceTableBundle | None = None,
    alignment_bundle: GovernanceTableBundle | None = None,
    approved_input_bundle: GovernanceTableBundle | None = None,
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
    if alignment_bundle is not None:
        payload.update(validate_s2_schema_alignment(alignment_bundle))
    if approved_input_bundle is not None:
        payload.update(validate_s2_approved_model_input(approved_input_bundle))
    return payload
