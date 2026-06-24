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

PROVISIONAL_DEV_INPUT_FILE_SPECS: dict[str, list[str]] = {
    "process_bounds.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "process_unit_id",
        "parameter_name",
        "value",
        "unit",
        "value_basis",
        "translation_basis",
        "source_ids",
        "evidence_status",
        "sensitivity_case",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "reviewer_decision_required",
        "codex_may_decide",
        "notes",
    ],
    "conversion_coefficients.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "process_unit_id",
        "carrier_id",
        "coefficient_role",
        "parameter_name",
        "value",
        "unit",
        "value_basis",
        "source_ids",
        "evidence_status",
        "sensitivity_case",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "reviewer_decision_required",
        "codex_may_decide",
        "notes",
    ],
    "store_capacities.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "store_id",
        "carrier_id",
        "capacity_name",
        "value",
        "unit",
        "value_basis",
        "source_ids",
        "evidence_status",
        "sensitivity_case",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "reviewer_decision_required",
        "codex_may_decide",
        "notes",
    ],
    "initial_inventories.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "store_id",
        "carrier_id",
        "inventory_basis",
        "value",
        "unit",
        "value_basis",
        "source_ids",
        "evidence_status",
        "sensitivity_case",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "reviewer_decision_required",
        "codex_may_decide",
        "notes",
    ],
    "terminal_inventory_rules.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "store_id",
        "carrier_id",
        "rule_type",
        "value",
        "unit",
        "value_basis",
        "source_ids",
        "evidence_status",
        "sensitivity_case",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "reviewer_decision_required",
        "codex_may_decide",
        "notes",
    ],
    "production_targets.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "carrier_id",
        "target_name",
        "target_variant",
        "value",
        "unit",
        "value_basis",
        "source_ids",
        "evidence_status",
        "sensitivity_case",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "reviewer_decision_required",
        "codex_may_decide",
        "notes",
    ],
    "inventory_endpoint_policies.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "store_id",
        "carrier_id",
        "policy_name",
        "value",
        "unit",
        "value_basis",
        "source_ids",
        "evidence_status",
        "sensitivity_case",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "reviewer_decision_required",
        "codex_may_decide",
        "notes",
    ],
    "validation_targets.csv": [
        "row_id",
        "configuration_id",
        "route_id",
        "carrier_id",
        "validation_target_name",
        "value",
        "unit",
        "value_basis",
        "source_ids",
        "evidence_status",
        "sensitivity_case",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "reviewer_decision_required",
        "codex_may_decide",
        "constraint_usage_status",
        "notes",
    ],
    "sensitivity_variants.csv": [
        "row_id",
        "configuration_id",
        "sensitivity_parameter",
        "base_structure",
        "low_case_structure",
        "high_case_structure",
        "source_ids",
        "evidence_status",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "reviewer_decision_required",
        "codex_may_decide",
        "notes",
    ],
    "dev_input_completeness_report.csv": [
        "input_category",
        "required_for_first_dev_lp",
        "row_count",
        "provisional_value_count",
        "missing_required_value_count",
        "sensitivity_row_count",
        "dev_executable_row_count",
        "not_executable_row_count",
        "main_blocker",
        "readiness_status",
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
    "s2_minimal_numerical_policy_decision_bundle.csv": [
        "numerical_policy_decision_id",
        "decision_cluster",
        "decision_item",
        "human_decision",
        "provisional_base_structure",
        "provisional_sensitivity_structure",
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
    "s2_early_sensitivity_screening_plan.csv": [
        "screening_item_id",
        "sensitivity_parameter",
        "baseline_structure",
        "low_case_structure",
        "high_case_structure",
        "model_risk_tested",
        "expected_diagnostic_metric",
        "required_before_screening",
        "thesis_use_status",
        "executable_status",
        "approval_status",
        "notes",
    ],
    "s2_provisional_dev_input_index.csv": [
        "dev_input_file",
        "input_category",
        "row_count",
        "provisional_value_count",
        "formula_only_row_count",
        "missing_required_value_count",
        "sensitivity_row_count",
        "dev_executable_row_count",
        "thesis_usable_row_count",
        "approved_row_count",
        "main_blocker",
        "next_action",
    ],
    "s2_provisional_dev_value_completion_audit.csv": [
        "audit_id",
        "input_file",
        "row_id",
        "parameter_name",
        "previous_status",
        "new_status",
        "value_or_formula_added",
        "value_basis",
        "source_ids",
        "evidence_status",
        "translation_or_derivation_basis",
        "sensitivity_required",
        "thesis_usability",
        "approval_status",
        "executable_status",
        "reviewer_decision_required",
        "codex_may_decide",
        "remaining_blocker",
        "notes",
    ],
    "s2_process_bound_translation_audit.csv": [
        "audit_id",
        "process_unit_or_asset",
        "configuration_id",
        "route_id",
        "previous_row_status",
        "new_row_status",
        "annual_anchor_used",
        "translation_formula",
        "effective_hours_or_batch_basis",
        "translated_value_tph",
        "bound_type",
        "envelope_case",
        "source_ids",
        "evidence_status",
        "sensitivity_required",
        "thesis_usability",
        "approval_status",
        "executable_status",
        "reviewer_decision_required",
        "codex_may_decide",
        "remaining_blocker",
        "notes",
    ],
    "s2_target_capacity_reconciliation_audit.csv": [
        "audit_id",
        "configuration_id",
        "horizon_hours",
        "target_variant",
        "original_target_t",
        "max_implied_liquid_steel_t",
        "target_fraction_of_capacity",
        "reconciled_target_t",
        "feasibility_expectation",
        "source_diagnostic_run_or_basis",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "reviewer_decision_required",
        "codex_may_decide",
        "notes",
    ],
    "s2_store_capacity_translation_audit.csv": [
        "audit_id",
        "store_id",
        "configuration_id",
        "store_class",
        "carrier",
        "previous_status",
        "new_status",
        "capacity_value_t",
        "sizing_formula",
        "sizing_basis",
        "heat_or_throughput_assumption",
        "sensitivity_case",
        "activation_recommendation",
        "source_ids",
        "evidence_status",
        "reviewer_decision_required",
        "codex_may_decide",
        "thesis_usability",
        "remaining_blocker",
        "notes",
    ],
    "s2_buffer_activation_readiness_register.csv": [
        "buffer_gate_id",
        "store_id",
        "configuration_id",
        "buffer_type",
        "candidate_for_s2_10b_activation",
        "capacity_ready",
        "initial_inventory_ready",
        "terminal_rule_ready",
        "expected_model_role",
        "fake_flexibility_risk",
        "required_builder_guard",
        "activation_status",
        "next_action",
        "thesis_usability",
    ],
    "s2_liquid_steel_smoke_baseline_summary.csv": [
        "case_id",
        "configuration_id",
        "horizon_hours",
        "target_variant",
        "target_t",
        "solve_status",
        "achieved_liquid_steel_t",
        "overproduction_t",
        "variable_count",
        "constraint_count",
        "binary_count",
        "objective_type",
        "shortfall_slack_active",
        "inventory_active",
        "downstream_active",
        "input_surface",
        "approved_input_used",
        "thesis_usability",
        "interpretation",
        "next_use",
    ],
    "s2_buffer_inventory_smoke_summary.csv": [
        "case_id",
        "configuration_id",
        "horizon_hours",
        "target_variant",
        "inventory_mode",
        "active_store_ids",
        "solve_status",
        "target_t",
        "achieved_liquid_steel_t",
        "overproduction_t",
        "variable_count",
        "constraint_count",
        "binary_count",
        "inventory_active",
        "active_store_count",
        "min_inventory_t",
        "max_inventory_t",
        "terminal_inventory_satisfied",
        "shortfall_slack_active",
        "downstream_active",
        "thesis_usability",
        "interpretation",
        "next_action",
    ],
    "s2_inventory_use_interpretation_register.csv": [
        "interpretation_id",
        "configuration_id",
        "target_variant",
        "horizon_hours",
        "inventory_mode",
        "store_id",
        "store_class",
        "carrier",
        "capacity_t",
        "initial_inventory_t",
        "min_inventory_t",
        "max_inventory_t",
        "terminal_inventory_t",
        "terminal_target_t",
        "hit_zero",
        "hit_capacity",
        "terminal_satisfied",
        "interpretation",
        "fake_flexibility_risk",
        "acceptable_for_24h_smoke",
        "acceptable_for_one_week_without_more_checks",
        "required_next_check",
        "thesis_usability",
    ],
    "s2_first_buffer_aware_baseline_summary.csv": [
        "case_id",
        "configuration_id",
        "horizon_hours",
        "target_variant",
        "inventory_mode",
        "solve_status",
        "target_t",
        "achieved_liquid_steel_t",
        "overproduction_t",
        "variable_count",
        "constraint_count",
        "binary_count",
        "active_store_count",
        "active_store_ids",
        "any_store_hit_zero",
        "all_terminal_inventory_satisfied",
        "shortfall_slack_active",
        "downstream_active",
        "thesis_usability",
        "interpretation",
        "next_action",
    ],
    "s2_buffer_aware_next_check_register.csv": [
        "check_id",
        "next_check",
        "purpose",
        "required_before",
        "current_status",
        "blocking_risk",
        "allowed_action",
        "forbidden_shortcut",
        "acceptance_signal",
        "thesis_relevance",
    ],
    "s2_buffer_sensitivity_plan.csv": [
        "sensitivity_id",
        "sensitivity_group",
        "configuration_id",
        "target_variant",
        "inventory_mode",
        "store_id",
        "initial_inventory_fraction",
        "capacity_multiplier",
        "expected_purpose",
        "expected_risk",
        "allowed_action",
        "thesis_usability",
        "notes",
    ],
    "s2_buffer_sensitivity_result_summary.csv": [
        "result_id",
        "sensitivity_id",
        "configuration_id",
        "horizon_hours",
        "target_variant",
        "inventory_mode",
        "solve_status",
        "target_t",
        "achieved_liquid_steel_t",
        "overproduction_t",
        "active_store_ids",
        "capacity_multiplier_summary",
        "initial_inventory_fraction_summary",
        "any_store_hit_zero",
        "any_store_hit_capacity",
        "all_terminal_inventory_satisfied",
        "min_inventory_summary",
        "max_inventory_summary",
        "variable_count",
        "constraint_count",
        "binary_count",
        "shortfall_slack_active",
        "thesis_usability",
        "interpretation",
        "next_action",
    ],
    "s2_zero_hit_attribution_register.csv": [
        "attribution_id",
        "configuration_id",
        "horizon_hours",
        "target_variant",
        "inventory_mode",
        "objective_type",
        "solve_status",
        "active_store_ids",
        "any_store_hit_zero",
        "zero_hit_reduced_vs_default",
        "all_terminal_inventory_satisfied",
        "stress_case_preserved_if_applicable",
        "likely_explanation",
        "benign_gate_result",
        "one_week_allowed",
        "thesis_usability",
        "notes",
    ],
    "s2_weekly_smoke_target_audit.csv": [
        "audit_id",
        "configuration_id",
        "horizon_hours",
        "target_variant",
        "original_target_t",
        "max_implied_liquid_steel_t",
        "target_fraction_of_capacity",
        "reconciled_target_t",
        "feasibility_expectation",
        "source_diagnostic_run_or_basis",
        "approval_status",
        "executable_status",
        "thesis_usability",
        "reviewer_decision_required",
        "codex_may_decide",
        "notes",
    ],
    "s2_one_week_buffer_smoke_summary.csv": [
        "case_id",
        "configuration_id",
        "horizon_hours",
        "target_variant",
        "inventory_mode",
        "objective_type",
        "solve_status",
        "target_t",
        "achieved_liquid_steel_t",
        "overproduction_t",
        "variable_count",
        "constraint_count",
        "binary_count",
        "active_store_count",
        "active_store_ids",
        "any_store_hit_zero",
        "any_store_hit_capacity",
        "all_terminal_inventory_satisfied",
        "shortfall_slack_active",
        "downstream_active",
        "thesis_usability",
        "interpretation",
        "next_action",
    ],
    "s2_artifact_inventory_and_directory_audit.csv": [
        "artifact_id",
        "path",
        "artifact_type",
        "s2_stage",
        "expected_directory",
        "current_directory_status",
        "source_or_generated",
        "should_be_committed",
        "thesis_usability",
        "governance_role",
        "action_required",
        "notes",
    ],
    "s2_configuration_asset_assumption_matrix.csv": [
        "row_id",
        "configuration_id",
        "asset_id",
        "asset_name",
        "asset_type",
        "route_or_scope",
        "active_in_s2_lp",
        "active_in_first_buffer_model",
        "carrier_or_material",
        "main_assumption",
        "numerical_input_source",
        "numerical_status",
        "flexibility_role",
        "capacity_or_bound_status",
        "conversion_status",
        "inventory_status",
        "validation_role",
        "thesis_usability",
        "remaining_risk",
        "next_required_review",
    ],
    "s2_to_s3_input_contract_register.csv": [
        "contract_id",
        "input_or_artifact",
        "may_s3_consume",
        "allowed_use_in_s3",
        "forbidden_use_in_s3",
        "thesis_usability_status",
        "required_guard",
        "current_status",
        "action_before_s3",
        "notes",
    ],
    "s3_entry_gate_checklist.csv": [
        "gate_id",
        "gate_name",
        "required_for_s3",
        "current_status",
        "pass_fail_or_blocked",
        "evidence_artifact",
        "risk_if_ignored",
        "required_action",
        "notes",
    ],
    "s2_liquid_steel_infeasibility_attribution.csv": [
        "attribution_id",
        "configuration_id",
        "target_variant",
        "horizon_hours",
        "target_t",
        "max_implied_output_t",
        "infeasibility_gap_t",
        "likely_primary_cause",
        "supporting_diagnostic",
        "model_scope_limitation",
        "interpretation",
        "action_required",
        "thesis_usability",
    ],
    "s2_next_scope_gate_register.csv": [
        "gate_id",
        "next_stage",
        "gate_name",
        "required_before_stage",
        "current_status",
        "blocking_risk",
        "required_artifact_or_decision",
        "allowed_next_action",
        "forbidden_shortcut",
        "thesis_relevance",
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
NUMERICAL_REVIEW_PACKET_DOC_DIR = REPO_ROOT / "docs" / "optimisation" / "steel" / "s2_numerical_review_packets"
NUMERICAL_REVIEW_PACKET_DATA_DIR_NAME = "s2_numerical_review_packets"
NUMERICAL_REVIEW_PACKET_SUMMARY_COLUMNS = [
    "review_packet_id",
    "review_category",
    "parameter_or_rule_name",
    "candidate_row_id",
    "candidate_source_table",
    "target_approved_table",
    "candidate_value_or_range_summary",
    "unit_or_basis",
    "source_ids",
    "evidence_status",
    "modelling_interpretation",
    "applies_to_configuration",
    "affects_model_component",
    "affected_flexibility_risk",
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
NUMERICAL_REVIEW_PACKET_SUMMARY_FILE_SPECS: dict[str, dict[str, str]] = {
    "buffer_capacity_review_packet.csv": {
        "review_category": "buffer_capacity",
        "target_approved_table": "store_capacities.csv",
    },
    "process_bounds_translation_review_packet.csv": {
        "review_category": "process_bounds_translation",
        "target_approved_table": "process_bounds.csv",
    },
    "production_target_review_packet.csv": {
        "review_category": "production_target",
        "target_approved_table": "production_targets.csv",
    },
}
NUMERICAL_REVIEW_PACKET_ALLOWED_APPROVAL_STATUSES = {
    "review_packet_only",
    "not_approved",
    "blocked",
    "defer_pending_review",
}
NUMERICAL_REVIEW_PACKET_DASHBOARD_COLUMNS = [
    "review_category",
    "decision_item",
    "candidate_count",
    "evidence_strength_summary",
    "recommended_nonbinding_option",
    "sensitivity_required",
    "high_risk_flag",
    "blocker_before_promotion",
    "blocker_before_executable_use",
    "next_human_decision_needed",
    "notes",
]
NUMERICAL_REVIEW_PACKET_MEMO_REQUIRED_PHRASES: dict[str, tuple[str, ...]] = {
    "S2_7F_BUFFER_CAPACITY_REVIEW_PACKET.md": (
        "review purpose",
        "relevant approved-input target table",
        "relevant candidate-review source tables",
        "relevant source-card ids",
        "candidate evidence summary",
        "modelling interpretation options",
        "model components affected",
        "red flags and blockers",
        "sensitivity implications",
        "human review questions",
        "possible reviewer outcomes",
        "codex is not approving any value",
        "approved-input tables remain empty",
        "hdri/dri",
        "cold slab",
        "hot metal",
        "hot slab",
        "liquid steel",
        "cyc50",
        "does not approve any store capacity",
    ),
    "S2_7F_PROCESS_BOUNDS_TRANSLATION_REVIEW_PACKET.md": (
        "review purpose",
        "relevant approved-input target table",
        "relevant candidate-review source tables",
        "relevant source-card ids",
        "candidate evidence summary",
        "modelling interpretation options",
        "model components affected",
        "red flags and blockers",
        "sensitivity implications",
        "human review questions",
        "possible reviewer outcomes",
        "codex is not approving any value",
        "approved-input tables remain empty",
        "annual-to-hourly",
        "bf",
        "drp",
        "bof",
        "eaf",
        "annual public anchors cannot become hourly caps directly",
        "online hours",
        "availability",
        "utilisation",
    ),
    "S2_7F_PRODUCTION_TARGET_REVIEW_PACKET.md": (
        "review purpose",
        "relevant approved-input target table",
        "relevant candidate-review source tables",
        "relevant source-card ids",
        "candidate evidence summary",
        "modelling interpretation options",
        "model components affected",
        "red flags and blockers",
        "sensitivity implications",
        "human review questions",
        "possible reviewer outcomes",
        "codex is not approving any value",
        "approved-input tables remain empty",
        "target sink or carrier basis",
        "horizon-total",
        "route-specific",
        "validation or scaling evidence",
        "shortfall",
    ),
}
NUMERICAL_REVIEW_PACKET_DASHBOARD = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_minimal_numerical_review_dashboard.csv"
NUMERICAL_REVIEW_PACKET_REQUIRED_DASHBOARD_ITEMS = {
    "buffer_capacity": {
        "HDRI_DRI_surge_capacity",
        "cold_slab_WIP_capacity",
        "hot_metal_synchronisation_capacity",
        "hot_slab_WIP_treatment",
        "liquid_steel_ladle_tundish_treatment",
    },
    "process_bounds_translation": {
        "annual_to_hourly_translation_method",
        "BF_near_must_run_band",
        "DRP_turndown_interpretation",
        "BOF_batch_equivalent_hourly_capacity",
        "EAF_batch_equivalent_hourly_capacity",
    },
    "production_target": {
        "target_basis_choice",
        "horizon_total_target_scale_translation",
        "route_specific_annual_anchors",
        "shortfall_treatment",
    },
}
MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE.md"
MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE_COLUMNS = REVIEW_FILE_SPECS["s2_minimal_numerical_policy_decision_bundle.csv"]
MINIMAL_NUMERICAL_POLICY_ALLOWED_APPROVAL_STATUSES = {
    "human_policy_recorded",
    "numerical_policy_recorded",
    "provisional_structure_recorded",
    "sensitivity_strategy_recorded",
    "not_approved_numerical",
    "blocked_until_later_review",
}
MINIMAL_NUMERICAL_POLICY_REQUIRED_CLUSTERS = {
    "process_bounds_translation_policy",
    "buffer_capacity_treatment",
    "production_target_policy",
    "sensitivity_screening_strategy",
}
MINIMAL_NUMERICAL_POLICY_REQUIRED_ITEMS = {
    "annual_public_anchors_not_direct_hourly_caps",
    "positive_t_per_hour_future_process_bound_unit",
    "effective_hours_availability_utilisation_translation_requirement",
    "BF_continuous_near_must_run_envelope",
    "DRP_continuous_turndown_envelope",
    "BOF_batch_equivalent_hourly_treatment",
    "EAF_batch_equivalent_hourly_treatment",
    "casting_HSM_bounded_sink_treatment",
    "HDRI_DRI_surge_included_as_main_flexibility_buffer",
    "HDRI_DRI_surge_heat_equivalent_sizing_basis",
    "HDRI_DRI_provisional_base_and_sensitivity_structure",
    "cold_slab_WIP_included_as_main_downstream_flexibility_buffer",
    "cold_slab_WIP_days_of_throughput_sizing_basis",
    "cold_slab_WIP_provisional_base_and_sensitivity_structure",
    "hot_metal_small_synchronisation_only",
    "hot_slab_WIP_omitted_or_tiny_thermal_transfer_only",
    "liquid_steel_ladle_tundish_omitted_or_tiny_feasibility_only",
    "coke_sinter_pellet_and_finished_goods_excluded_from_base_flexibility",
    "CYC50_not_capacity_approval",
    "one_horizon_total_production_target",
    "last_modelled_metallic_sink_target_basis",
    "no_route_specific_base_target",
    "annual_to_horizon_target_translation_requirement",
    "one_day_debugging_vs_one_week_serious_interpretation",
    "explicit_reportable_shortfall_only_if_later_allowed",
    "early_sensitivity_screening_priorities",
    "final_thesis_sensitivity_selected_by_materiality",
}
MINIMAL_NUMERICAL_POLICY_MEMO_REQUIRED_PHRASES = (
    "purpose and scope",
    "records human numerical-policy decisions",
    "not a codex approval artifact",
    "s2_approved_model_input remains empty",
    "provisional development pack is development-only and not thesis-usable",
    "process-bounds and annual-to-hourly translation policy",
    "buffer-capacity treatment",
    "production-target basis and translation policy",
    "early sensitivity-screening strategy",
    "what remains undecided",
    "what is still blocked from thesis or executable use",
    "why provisional base and sensitivity structures are not thesis-grade exact values",
    "how future codex tasks should use this bundle",
    "why this does not approve exact numerical values",
)
MINIMAL_NUMERICAL_POLICY_NUMERIC_FORBIDDEN_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:tonnes|t/h|mt/y|pj/y|mw|mwh|eur/mwh|eur/kg|â‚¬/mwh|â‚¬/kg)\b",
    re.IGNORECASE,
)
EARLY_SENSITIVITY_SCREENING_PLAN_COLUMNS = REVIEW_FILE_SPECS["s2_early_sensitivity_screening_plan.csv"]
EARLY_SENSITIVITY_REQUIRED_PARAMETERS = {
    "HDRI_DRI_surge_size",
    "cold_slab_slab_WIP_capacity",
    "DRP_turndown",
    "BF_near_must_run_band",
    "production_target_level_or_basis",
}
EARLY_SENSITIVITY_ALLOWED_APPROVAL_STATUSES = {"screening_plan_only"}
PROVISIONAL_DEV_INPUT_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_provisional_dev_input"
PROVISIONAL_DEV_INPUT_README = PROVISIONAL_DEV_INPUT_ROOT / "README.md"
PROVISIONAL_DEV_INPUT_REQUIRED_TABLES = set(PROVISIONAL_DEV_INPUT_FILE_SPECS)
PROVISIONAL_DEV_INPUT_INDEX_COLUMNS = REVIEW_FILE_SPECS["s2_provisional_dev_input_index.csv"]
PROVISIONAL_DEV_INPUT_INDEX_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_provisional_dev_input_index.csv"
PROVISIONAL_DEV_VALUE_COMPLETION_AUDIT_COLUMNS = REVIEW_FILE_SPECS["s2_provisional_dev_value_completion_audit.csv"]
PROVISIONAL_DEV_VALUE_COMPLETION_AUDIT_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_provisional_dev_value_completion_audit.csv"
PROCESS_BOUND_TRANSLATION_AUDIT_COLUMNS = REVIEW_FILE_SPECS["s2_process_bound_translation_audit.csv"]
PROCESS_BOUND_TRANSLATION_AUDIT_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_process_bound_translation_audit.csv"
TARGET_CAPACITY_RECONCILIATION_AUDIT_COLUMNS = REVIEW_FILE_SPECS["s2_target_capacity_reconciliation_audit.csv"]
TARGET_CAPACITY_RECONCILIATION_AUDIT_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_target_capacity_reconciliation_audit.csv"
STORE_CAPACITY_TRANSLATION_AUDIT_COLUMNS = REVIEW_FILE_SPECS["s2_store_capacity_translation_audit.csv"]
STORE_CAPACITY_TRANSLATION_AUDIT_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_store_capacity_translation_audit.csv"
BUFFER_ACTIVATION_READINESS_COLUMNS = REVIEW_FILE_SPECS["s2_buffer_activation_readiness_register.csv"]
BUFFER_ACTIVATION_READINESS_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_buffer_activation_readiness_register.csv"
PROVISIONAL_DEV_INPUT_ALLOWED_APPROVAL_STATUSES = {"provisional_development_only", "missing_required_dev_value"}
PROVISIONAL_DEV_INPUT_ALLOWED_EXECUTABLE_STATUSES = {"dev_executable_only", "not_executable"}
PROVISIONAL_DEV_INPUT_README_REQUIRED_PHRASES = (
    "development and smoke-testing input pack",
    "not thesis-grade",
    "not approved",
    "must not be cited as final model input",
    "separate from `s2_approved_model_input`",
    "future lp outputs that consume this pack must report `thesis_usability=false`",
    "require later review before any thesis use",
    "annual public anchors cannot become hourly caps",
    "validation targets must not drive constraints",
    "`cyc50` is endpoint policy only and not buffer-capacity approval",
)
DEV_INPUT_READINESS_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_PROVISIONAL_DEV_INPUT_READINESS.md"
STORE_CAPACITY_TRANSLATION_REVIEW_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_STORE_CAPACITY_TRANSLATION_REVIEW.md"
DEV_INPUT_READINESS_MEMO_REQUIRED_PHRASES = (
    "structurally complete enough for a future deterministic `s2` smoke-lp builder prompt",
    "not numerically complete enough",
    "process bounds",
    "conversion coefficients",
    "production-target quantities",
    "dev-executable only",
    "not thesis-usable",
    "what the next lp-builder prompt may consume",
    "what the lp-builder must refuse",
)
STORE_CAPACITY_TRANSLATION_REVIEW_REQUIRED_PHRASES = (
    "purpose",
    "what was translated",
    "which buffers may be activated first",
    "which buffers remain excluded or deferred",
    "why cyc50 is not capacity evidence",
    "why hot slab wip is not strategic flexibility",
    "why coke, sinter, pellet, and finished goods are excluded",
    "why outputs remain non-thesis-usable",
    "what s2.10b may activate",
    "what s2.10b must still refuse",
)
BUFFER_ACTIVATION_REQUIRED_BUFFER_TYPES = {
    "hot_metal_buffer",
    "dri_hdri_surge_buffer",
    "cold_slab_slab_wip",
    "hot_slab_wip",
    "liquid_steel_ladle_tundish",
    "excluded_scope_stocks",
}
LIQUID_STEEL_SMOKE_BUILDER_MODULE = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "steel" / "liquid_steel_smoke_builder.py"
LIQUID_STEEL_SMOKE_BUILDER_SCOPE_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_LIQUID_STEEL_SMOKE_BUILDER_SCOPE.md"
LIQUID_STEEL_SMOKE_RUNNER_MODULE = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "steel" / "liquid_steel_smoke_runner.py"
LIQUID_STEEL_SMOKE_DIAGNOSTICS_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_LIQUID_STEEL_SMOKE_DIAGNOSTICS.md"
LIQUID_STEEL_SMOKE_BASELINE_FREEZE_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_LIQUID_STEEL_SMOKE_BASELINE_FREEZE.md"
LIQUID_STEEL_FIRST_BUFFER_INVENTORY_ACTIVATION_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_FIRST_BUFFER_INVENTORY_ACTIVATION.md"
LIQUID_STEEL_FIRST_BUFFER_AWARE_BASELINE_FREEZE_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_FIRST_BUFFER_AWARE_BASELINE_FREEZE.md"
BUFFER_SENSITIVITY_DIAGNOSTICS_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_BUFFER_SENSITIVITY_DIAGNOSTICS.md"
LIQUID_STEEL_SMOKE_BUILDER_SCOPE_REQUIRED_PHRASES = (
    "restricted deterministic `s2` liquid-steel material-flow lp scaffold",
    "development-only smoke builder",
    "not a thesis-result model",
    "inputs consumed",
    "inputs refused",
    "s2_provisional_dev_input",
    "s2_approved_model_input",
    "store inventories are not active yet",
    "downstream `hsm` and slab scope remain outside the executable `s2.9a` boundary",
    "all model metadata must report `thesis_usability=false`",
    "what s2.9b should test",
)
LIQUID_STEEL_SMOKE_DIAGNOSTICS_REQUIRED_PHRASES = (
    "purpose of s2.9b",
    "c0_current_bf_bof_reference",
    "c1_phase1_hybrid_bf_bof_ng_drp_eaf",
    "24h",
    "no hidden shortfall slack",
    "solve_status=not_attempted_solver_unavailable",
    "thesis_usability=false",
    "what should happen in s2.9c",
)
LIQUID_STEEL_SMOKE_BASELINE_SUMMARY_COLUMNS = REVIEW_FILE_SPECS["s2_liquid_steel_smoke_baseline_summary.csv"]
LIQUID_STEEL_SMOKE_BASELINE_SUMMARY_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_liquid_steel_smoke_baseline_summary.csv"
BUFFER_INVENTORY_SMOKE_SUMMARY_COLUMNS = REVIEW_FILE_SPECS["s2_buffer_inventory_smoke_summary.csv"]
BUFFER_INVENTORY_SMOKE_SUMMARY_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_buffer_inventory_smoke_summary.csv"
INVENTORY_USE_INTERPRETATION_COLUMNS = REVIEW_FILE_SPECS["s2_inventory_use_interpretation_register.csv"]
INVENTORY_USE_INTERPRETATION_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_inventory_use_interpretation_register.csv"
FIRST_BUFFER_AWARE_BASELINE_SUMMARY_COLUMNS = REVIEW_FILE_SPECS["s2_first_buffer_aware_baseline_summary.csv"]
FIRST_BUFFER_AWARE_BASELINE_SUMMARY_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_first_buffer_aware_baseline_summary.csv"
BUFFER_AWARE_NEXT_CHECK_REGISTER_COLUMNS = REVIEW_FILE_SPECS["s2_buffer_aware_next_check_register.csv"]
BUFFER_AWARE_NEXT_CHECK_REGISTER_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_buffer_aware_next_check_register.csv"
BUFFER_SENSITIVITY_PLAN_COLUMNS = REVIEW_FILE_SPECS["s2_buffer_sensitivity_plan.csv"]
BUFFER_SENSITIVITY_PLAN_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_buffer_sensitivity_plan.csv"
BUFFER_SENSITIVITY_RESULT_SUMMARY_COLUMNS = REVIEW_FILE_SPECS["s2_buffer_sensitivity_result_summary.csv"]
BUFFER_SENSITIVITY_RESULT_SUMMARY_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_buffer_sensitivity_result_summary.csv"
LIQUID_STEEL_INFEASIBILITY_ATTRIBUTION_COLUMNS = REVIEW_FILE_SPECS["s2_liquid_steel_infeasibility_attribution.csv"]
LIQUID_STEEL_INFEASIBILITY_ATTRIBUTION_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_liquid_steel_infeasibility_attribution.csv"
S2_NEXT_SCOPE_GATE_REGISTER_COLUMNS = REVIEW_FILE_SPECS["s2_next_scope_gate_register.csv"]
S2_NEXT_SCOPE_GATE_REGISTER_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_next_scope_gate_register.csv"
LIQUID_STEEL_SMOKE_BASELINE_FREEZE_REQUIRED_PHRASES = (
    "summary of s2.9a-s2.9d",
    "feasible_smoke",
    "stress_infeasible_original",
    "minimise_overproduction_dev_only",
    "not a tata annual-production target",
    "no shortfall slack",
    "inventory inactive",
    "not thesis results",
    "required next gates before buffer-aware s2",
    "required next gates before s3",
)
LIQUID_STEEL_FIRST_BUFFER_INVENTORY_ACTIVATION_REQUIRED_PHRASES = (
    "purpose of s2.10b",
    "which stores are activated",
    "which stores remain refused",
    "capacity, initial, and terminal policy",
    "how store flows are coupled to process flows",
    "how cyc50 is applied",
    "why cyc50 is not capacity evidence",
    "why hot slab/slab/wip and downstream are still inactive",
    "why outputs remain non-thesis",
    "how to interpret feasible/stress runs",
    "what must be checked before one-week s2 or s3",
)
LIQUID_STEEL_FIRST_BUFFER_AWARE_BASELINE_FREEZE_REQUIRED_PHRASES = (
    "s2.10b scope and non-scope",
    "activated stores and refused stores",
    "feasible and stress run outcomes",
    "inventory capacity/initial/min/max/terminal summary",
    "interpretation of buffers hitting zero",
    "net horizon borrowing but does not prove physical credibility",
    "hot metal remains only a synchronisation buffer",
    "short-term surge buffer",
    "blocked/deferred",
    "no economic flexibility value is claimed yet",
    "outputs remain `thesis_usability=false`",
    "acceptable as a 24h smoke baseline",
    "required next gates before one-week buffer-aware runs",
    "required next gates before s3",
)
BUFFER_SENSITIVITY_DIAGNOSTICS_REQUIRED_PHRASES = (
    "purpose of s2.10d",
    "sensitivity cases tested",
    "50% initial inventory",
    "hot metal buffer size",
    "dri/hdri buffer size",
    "cyc50",
    "stress targets remain infeasible",
    "zero-inventory hits persist",
    "no thesis-use claim is made",
    "one-week buffer-aware runs",
)
BUFFER_SENSITIVITY_ALLOWED_CONFIGURATION_IDS = {
    "C0_current_BF_BOF_reference",
    "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
}
ZERO_HIT_ATTRIBUTION_REGISTER_COLUMNS = REVIEW_FILE_SPECS["s2_zero_hit_attribution_register.csv"]
ZERO_HIT_ATTRIBUTION_REGISTER_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_zero_hit_attribution_register.csv"
WEEKLY_SMOKE_TARGET_AUDIT_COLUMNS = REVIEW_FILE_SPECS["s2_weekly_smoke_target_audit.csv"]
WEEKLY_SMOKE_TARGET_AUDIT_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_weekly_smoke_target_audit.csv"
ONE_WEEK_BUFFER_SMOKE_SUMMARY_COLUMNS = REVIEW_FILE_SPECS["s2_one_week_buffer_smoke_summary.csv"]
ONE_WEEK_BUFFER_SMOKE_SUMMARY_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_one_week_buffer_smoke_summary.csv"
ZERO_HIT_WEEK_GATE_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_ZERO_HIT_ATTRIBUTION_AND_WEEK_GATE.md"
S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT.md"
S2_CONFIGURATION_ASSET_AND_ASSUMPTION_SUMMARY_MEMO = REPO_ROOT / "docs" / "optimisation" / "steel" / "STEEL_S2_CONFIGURATION_ASSET_AND_ASSUMPTION_SUMMARY.md"
S2_ARTIFACT_INVENTORY_AND_DIRECTORY_AUDIT_COLUMNS = REVIEW_FILE_SPECS["s2_artifact_inventory_and_directory_audit.csv"]
S2_ARTIFACT_INVENTORY_AND_DIRECTORY_AUDIT_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_artifact_inventory_and_directory_audit.csv"
S2_CONFIGURATION_ASSET_ASSUMPTION_MATRIX_COLUMNS = REVIEW_FILE_SPECS["s2_configuration_asset_assumption_matrix.csv"]
S2_CONFIGURATION_ASSET_ASSUMPTION_MATRIX_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_configuration_asset_assumption_matrix.csv"
S2_TO_S3_INPUT_CONTRACT_REGISTER_COLUMNS = REVIEW_FILE_SPECS["s2_to_s3_input_contract_register.csv"]
S2_TO_S3_INPUT_CONTRACT_REGISTER_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_to_s3_input_contract_register.csv"
S3_ENTRY_GATE_CHECKLIST_COLUMNS = REVIEW_FILE_SPECS["s3_entry_gate_checklist.csv"]
S3_ENTRY_GATE_CHECKLIST_PATH = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s3_entry_gate_checklist.csv"
ZERO_HIT_WEEK_GATE_REQUIRED_PHRASES = (
    "why zero-hit attribution was needed",
    "diagnostic objective used",
    "whether zero hits appear to be degeneracy or structurally forced",
    "whether the s2.10e result is benign, ambiguous, or non-benign",
    "whether one-week was opened",
    "if one-week was opened",
    "why outputs remain non-thesis",
    "why s3 is still not entered in this task",
)
S2_MATERIAL_FLOW_FREEZE_REQUIRED_PHRASES = (
    "s2 purpose and scope",
    "c0 and c1 configuration definitions",
    "what s2 has implemented",
    "what s2 has explicitly not implemented",
    "s2 smoke/buffer/one-week results summary",
    "why s2 results remain non-thesis",
    "what s3 may consume",
    "what s3 must not reinterpret",
    "remaining s2 limitations",
    "s3 entry conditions",
    "red flags that must block s3 if violated",
)
S2_CONFIGURATION_ASSET_SUMMARY_REQUIRED_PHRASES = (
    "assets/process units in c0",
    "assets/process units in c1",
    "what changes between c0 and c1",
    "which assets are active in the lp",
    "which are structural only",
    "which are exogenous supply boundaries",
    "which stores are active",
    "which stores are blocked/deferred",
    "what assumptions are used per asset",
    "what assumptions remain provisional",
    "what each asset contributes to flexibility or non-flexibility",
)
FIRST_BUFFER_ACTIVE_STORE_IDS = {
    "c0_hot_metal_buffer",
    "c1_hot_metal_buffer",
    "c1_dri_hdri_buffer",
}
S2_NEXT_SCOPE_REQUIRED_GATES = {
    "dev_only_store_capacity_translation",
    "hot_metal_buffer_activation",
    "dri_hdri_surge_buffer_activation",
    "cyc50_inventory_dynamics_activation",
    "cold_slab_slab_wip_decision",
    "downstream_hsm_slab_scope_decision",
    "one_week_s2_run",
    "validation_against_public_annual_anchors",
    "s3_energy_cost_emissions_entry",
}
S211_REQUIRED_ARTIFACT_IDS = {
    "DOC_IMPL_FREEZE_V1",
    "DOC_IMPL_ROADMAP",
    "DOC_STAGE_GATE_PLAN",
    "DOC_TRACTABILITY_CONTROL",
    "DOC_SCOPE_FREEZE",
    "DOC_S2_TOPOLOGY_REGISTRY",
    "DOC_S2_DEV_INPUT_READINESS",
    "DOC_S2_SMOKE_BASELINE",
    "DOC_S2_FIRST_BUFFER_BASELINE",
    "DOC_S2_ZERO_HIT_GATE",
    "DOC_S211_FREEZE_CONTRACT",
    "DOC_S211_ASSET_SUMMARY",
    "TOPO_CONFIGS",
    "TOPO_ROUTES",
    "TOPO_PROCESS_UNITS",
    "TOPO_CARRIERS",
    "TOPO_STORES",
    "TOPO_ARCS",
    "TOPO_INVENTORY_POLICY",
    "DEV_PROCESS_BOUNDS",
    "DEV_CONVERSION_COEFFICIENTS",
    "DEV_STORE_CAPACITIES",
    "DEV_INITIAL_INVENTORIES",
    "DEV_TERMINAL_RULES",
    "DEV_INVENTORY_ENDPOINT_POLICIES",
    "DEV_PRODUCTION_TARGETS",
    "DEV_VALIDATION_TARGETS",
    "DEV_SENSITIVITY_VARIANTS",
    "DEV_COMPLETENESS_REPORT",
    "APPROVED_README",
    "APPROVED_PROCESS_BOUNDS",
    "APPROVED_CONVERSION_COEFFICIENTS",
    "APPROVED_STORE_CAPACITIES",
    "APPROVED_INITIAL_INVENTORIES",
    "APPROVED_TERMINAL_RULES",
    "APPROVED_INVENTORY_ENDPOINT_POLICIES",
    "APPROVED_PRODUCTION_TARGETS",
    "APPROVED_VALIDATION_TARGETS",
    "APPROVED_REPORTING_REQUIREMENTS",
    "REVIEW_TARGET_RECONCILIATION",
    "REVIEW_STORE_CAPACITY_TRANSLATION",
    "REVIEW_BUFFER_ACTIVATION_READINESS",
    "REVIEW_ZERO_HIT_ATTRIBUTION",
    "REVIEW_ONE_WEEK_BUFFER_SMOKE",
    "REVIEW_S211_ARTIFACT_AUDIT",
    "REVIEW_S211_ASSET_MATRIX",
    "REVIEW_S211_S3_CONTRACT",
    "REVIEW_S211_S3_GATE_CHECKLIST",
    "CODE_SMOKE_BUILDER",
    "CODE_SMOKE_RUNNER",
    "CODE_GOVERNANCE",
    "CODE_VALIDATE_GOVERNANCE",
    "TEST_S211_FREEZE",
    "GENERATED_SMOKE_RUN_POLICY",
}
S211_REQUIRED_ASSET_MATRIX_IDS = {
    "c0_external_iron_burden_supply_boundary",
    "c0_external_scrap_flux_supply_boundary",
    "c0_coke_supply_or_coke_oven_boundary",
    "c0_burden_prep_boundary",
    "c0_blast_furnace",
    "c0_hot_metal_buffer",
    "c0_bof_converter",
    "c0_cast_slab_handling",
    "c0_liquid_steel_target_sink",
    "c0_slab_wip_buffer",
    "c0_hot_slab_transfer_buffer",
    "c0_excluded_bulk_stocks",
    "c1_retained_bf_bof_supply_boundary",
    "c1_ng_drp_eaf_supply_boundary",
    "c1_retained_blast_furnace",
    "c1_hot_metal_buffer",
    "c1_retained_bof_converter",
    "c1_ng_drp",
    "c1_dri_hdri_buffer",
    "c1_eaf",
    "c1_new_secondary_met",
    "c1_liquid_steel_target_sink",
    "c1_slab_wip_buffer",
    "c1_hot_slab_transfer_buffer",
    "c1_casting_downstream_boundary",
    "c1_excluded_bulk_stocks",
}
S211_REQUIRED_CONTRACT_INPUTS = {
    "topology",
    "process_activity_variables",
    "carrier_balances",
    "process_bounds",
    "conversion_coefficients",
    "production_targets",
    "active_stores",
    "blocked_stores",
    "CYC50_policy",
    "one_week_smoke_results",
    "S2_run_folders",
    "validation_targets",
    "approved_input_shells",
    "provisional_dev_inputs",
}
S211_REQUIRED_S3_GATES = {
    "S2_topology_frozen",
    "C0_C1_configurations_frozen",
    "liquid_steel_LP_solves",
    "first_buffer_inventory_solves",
    "one_week_smoke_solved",
    "no_hidden_shortfall_slack",
    "no_fake_free_buffers",
    "blocked_deferred_stores_remain_blocked",
    "production_target_status_understood",
    "public_annual_targets_not_used_as_executable_truth",
    "approved_input_tables_zero_row",
    "S3_scope_limited_to_energy_cost_emissions_first",
    "no_DA_stochastic_mfrr_in_S3_0",
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


def load_s2_provisional_dev_input(provisional_dev_input_root: str | Path) -> GovernanceTableBundle:
    return _load_bundle(provisional_dev_input_root, PROVISIONAL_DEV_INPUT_FILE_SPECS, require_non_empty=False)


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


def _count_formula_only_rows(frame: pd.DataFrame) -> int:
    formula_columns = [column for column in ("value_basis", "translation_basis") if column in frame.columns]
    if not formula_columns:
        return 0
    combined = frame[formula_columns].astype(str).agg(" ".join, axis=1).str.strip().str.lower()
    return int(combined.str.contains("formula").sum())


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


def validate_s2_numerical_review_packets(review_root: str | Path) -> dict[str, Any]:
    review_root = Path(review_root).resolve()
    data_dir = review_root / NUMERICAL_REVIEW_PACKET_DATA_DIR_NAME
    if not data_dir.exists():
        raise ValueError("s2_numerical_review_packets data folder must exist.")
    if not NUMERICAL_REVIEW_PACKET_DOC_DIR.exists():
        raise ValueError("docs/optimisation/steel/s2_numerical_review_packets must exist.")

    total_rows = 0
    frames_by_category: dict[str, pd.DataFrame] = {}

    for filename, spec in NUMERICAL_REVIEW_PACKET_SUMMARY_FILE_SPECS.items():
        path = data_dir / filename
        if not path.exists():
            raise ValueError(f"{filename} must exist in s2_numerical_review_packets.")
        frame = _read_csv(path)
        if list(frame.columns) != NUMERICAL_REVIEW_PACKET_SUMMARY_COLUMNS:
            raise ValueError(f"{filename} must match the required S2.7f review-packet column order.")
        if frame.empty:
            raise ValueError(f"{filename} must contain at least one review-packet row.")
        if frame["review_packet_id"].astype(str).str.strip().duplicated().any():
            raise ValueError(f"{filename} must not contain duplicate review_packet_id values.")
        if (~frame["review_category"].astype(str).str.strip().eq(spec["review_category"])).any():
            raise ValueError(f"{filename} must use review_category={spec['review_category']} for every row.")
        target_tables = frame["target_approved_table"].astype(str).str.strip()
        if spec["review_category"] == "process_bounds_translation":
            allowed_targets = {"process_bounds.csv", "process_bounds.csv;production_targets.csv"}
            if (~target_tables.isin(allowed_targets)).any():
                raise ValueError(f"{filename} must target process_bounds.csv or process_bounds.csv;production_targets.csv for every row.")
        else:
            if (~target_tables.eq(spec["target_approved_table"])).any():
                raise ValueError(f"{filename} must target {spec['target_approved_table']} for every row.")
        if (~frame["reviewer_decision_required"].astype(str).str.strip().str.lower().eq("true")).any():
            raise ValueError(f"{filename} must keep reviewer_decision_required=true for every row.")
        if (~frame["codex_may_decide"].astype(str).str.strip().str.lower().eq("false")).any():
            raise ValueError(f"{filename} must keep codex_may_decide=false for every row.")
        if (~frame["executable_status"].astype(str).str.strip().str.lower().eq("non_executable")).any():
            raise ValueError(f"{filename} must keep executable_status=non_executable for every row.")
        if (~frame["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
            raise ValueError(f"{filename} must keep thesis_usability=false for every row.")
        if (~frame["approval_status"].astype(str).str.strip().str.lower().isin(NUMERICAL_REVIEW_PACKET_ALLOWED_APPROVAL_STATUSES)).any():
            raise ValueError(f"{filename} contains invalid review-packet approval_status values.")
        if frame["approval_status"].astype(str).str.strip().str.lower().eq("approved").any():
            raise ValueError(f"{filename} must not mark any row approved.")
        outcomes = frame["possible_reviewer_outcomes"].astype(str).str.lower()
        required_outcome_tokens = ("later_base_assumption", "sensitivity-only", "defer", "reject")
        for token in required_outcome_tokens:
            if (~outcomes.str.contains(token, regex=False)).any():
                raise ValueError(f"{filename} must enumerate reviewer outcome token {token} on every row.")

        frame_text = " ".join(frame.astype(str).agg(" ".join, axis=1).str.lower())
        if spec["review_category"] == "buffer_capacity":
            for phrase in ("capacity_approval", "multi_hour_or_multi_day", "liquid_steel", "cyc50"):
                if phrase not in frame_text:
                    raise ValueError(f"{filename} must keep CYC50 and buffer-capacity review separate from strategic or hidden-slack claims.")
        elif spec["review_category"] == "process_bounds_translation":
            for phrase in ("annual_anchor", "hourly_cap", "online_hours", "availability", "utilisation"):
                if phrase not in frame_text:
                    raise ValueError(f"{filename} must keep annual-to-hourly translation blockers explicit.")
        elif spec["review_category"] == "production_target":
            for phrase in ("route_specific", "validation_only", "shortfall"):
                if phrase not in frame_text:
                    raise ValueError(f"{filename} must keep route-specific and shortfall guardrails explicit.")

        total_rows += int(len(frame))
        frames_by_category[spec["review_category"]] = frame

    if not NUMERICAL_REVIEW_PACKET_DASHBOARD.exists():
        raise ValueError("s2_minimal_numerical_review_dashboard.csv must exist.")
    dashboard = _read_csv(NUMERICAL_REVIEW_PACKET_DASHBOARD)
    if list(dashboard.columns) != NUMERICAL_REVIEW_PACKET_DASHBOARD_COLUMNS:
        raise ValueError("s2_minimal_numerical_review_dashboard.csv must match the required S2.7f dashboard column order.")
    expected_categories = {spec["review_category"] for spec in NUMERICAL_REVIEW_PACKET_SUMMARY_FILE_SPECS.values()}
    actual_categories = set(dashboard["review_category"].astype(str).str.strip())
    if actual_categories != expected_categories:
        missing = sorted(expected_categories - actual_categories)
        extra = sorted(actual_categories - expected_categories)
        raise ValueError(f"s2_minimal_numerical_review_dashboard.csv category mismatch. missing={missing} extra={extra}")
    for record in dashboard.to_dict(orient="records"):
        category = str(record["review_category"]).strip()
        if category not in NUMERICAL_REVIEW_PACKET_REQUIRED_DASHBOARD_ITEMS:
            raise ValueError(f"s2_minimal_numerical_review_dashboard.csv contains unexpected category {category}.")
        if str(record["decision_item"]).strip() not in NUMERICAL_REVIEW_PACKET_REQUIRED_DASHBOARD_ITEMS[category]:
            raise ValueError(f"s2_minimal_numerical_review_dashboard.csv contains unexpected decision_item {record['decision_item']} for {category}.")
        if int(record["candidate_count"]) <= 0:
            raise ValueError(f"s2_minimal_numerical_review_dashboard.csv must keep candidate_count positive for {category}/{record['decision_item']}.")
        if str(record["recommended_nonbinding_option"]).strip() == "":
            raise ValueError(f"s2_minimal_numerical_review_dashboard.csv must keep recommended_nonbinding_option non-empty for {category}/{record['decision_item']}.")
        if str(record["sensitivity_required"]).strip().lower() not in {"true", "false"}:
            raise ValueError(f"s2_minimal_numerical_review_dashboard.csv must keep sensitivity_required as true/false for {category}/{record['decision_item']}.")
        if str(record["high_risk_flag"]).strip().lower() not in {"true", "false"}:
            raise ValueError(f"s2_minimal_numerical_review_dashboard.csv must keep high_risk_flag as true/false for {category}/{record['decision_item']}.")
        for field_name in ("evidence_strength_summary", "blocker_before_promotion", "blocker_before_executable_use", "next_human_decision_needed", "notes"):
            if str(record[field_name]).strip() == "":
                raise ValueError(f"s2_minimal_numerical_review_dashboard.csv must keep {field_name} non-empty for {category}/{record['decision_item']}.")

    for filename, phrases in NUMERICAL_REVIEW_PACKET_MEMO_REQUIRED_PHRASES.items():
        path = NUMERICAL_REVIEW_PACKET_DOC_DIR / filename
        if not path.exists():
            raise ValueError(f"{filename} must exist in docs/optimisation/steel/s2_numerical_review_packets.")
        text = path.read_text(encoding="utf-8").lower()
        for phrase in phrases:
            if phrase not in text:
                raise ValueError(f"{filename} is missing required review-packet phrase: {phrase}")

    return {
        "numerical_review_packet_files_checked": int(len(NUMERICAL_REVIEW_PACKET_SUMMARY_FILE_SPECS)),
        "numerical_review_packet_rows_checked": int(total_rows),
        "numerical_review_packet_dashboard_present": True,
        "numerical_review_packet_memos_present": int(len(NUMERICAL_REVIEW_PACKET_MEMO_REQUIRED_PHRASES)),
    }


def validate_s2_minimal_numerical_policy_bundle(review_bundle: GovernanceTableBundle) -> dict[str, Any]:
    if not MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE_MEMO.exists():
        raise ValueError("STEEL_S2_MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE.md must exist.")
    memo_text = MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE_MEMO.read_text(encoding="utf-8").lower()
    for phrase in MINIMAL_NUMERICAL_POLICY_MEMO_REQUIRED_PHRASES:
        if phrase not in memo_text:
            raise ValueError(f"STEEL_S2_MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE.md is missing required phrase: {phrase}")

    decision_bundle = review_bundle.tables["s2_minimal_numerical_policy_decision_bundle.csv"]
    if list(decision_bundle.columns) != MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE_COLUMNS:
        raise ValueError("s2_minimal_numerical_policy_decision_bundle.csv must match the required column order.")
    if decision_bundle["numerical_policy_decision_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_minimal_numerical_policy_decision_bundle.csv must not contain duplicate numerical_policy_decision_id values.")
    if not MINIMAL_NUMERICAL_POLICY_REQUIRED_CLUSTERS.issubset(set(decision_bundle["decision_cluster"].astype(str).str.strip())):
        missing = sorted(MINIMAL_NUMERICAL_POLICY_REQUIRED_CLUSTERS - set(decision_bundle["decision_cluster"].astype(str).str.strip()))
        raise ValueError(f"s2_minimal_numerical_policy_decision_bundle.csv is missing required decision clusters: {missing}")
    if not MINIMAL_NUMERICAL_POLICY_REQUIRED_ITEMS.issubset(set(decision_bundle["decision_item"].astype(str).str.strip())):
        missing = sorted(MINIMAL_NUMERICAL_POLICY_REQUIRED_ITEMS - set(decision_bundle["decision_item"].astype(str).str.strip()))
        raise ValueError(f"s2_minimal_numerical_policy_decision_bundle.csv is missing required decision items: {missing}")
    if (~decision_bundle["approval_status"].astype(str).str.strip().str.lower().isin(MINIMAL_NUMERICAL_POLICY_ALLOWED_APPROVAL_STATUSES)).any():
        raise ValueError("s2_minimal_numerical_policy_decision_bundle.csv contains invalid approval_status values.")
    if (~decision_bundle["executable_status"].astype(str).str.strip().str.lower().eq("non_executable")).any():
        raise ValueError("s2_minimal_numerical_policy_decision_bundle.csv must keep executable_status=non_executable for every row.")
    if (~decision_bundle["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_minimal_numerical_policy_decision_bundle.csv must keep thesis_usability=false for every row.")
    if decision_bundle["approval_status"].astype(str).str.strip().str.lower().eq("approved").any():
        raise ValueError("s2_minimal_numerical_policy_decision_bundle.csv must not mark any row approved.")
    if (~decision_bundle["codex_allowed_role"].astype(str).str.lower().str.contains("record")).any():
        raise ValueError("Every minimal numerical-policy row must limit Codex to recording/applying explicit policy only.")
    if (~decision_bundle["codex_forbidden_role"].astype(str).str.lower().str.contains("approve|promote|populate")).any():
        raise ValueError("Every minimal numerical-policy row must explicitly forbid approval/promotion/population actions.")
    for column in ("human_decision", "provisional_base_structure", "provisional_sensitivity_structure", "modelling_interpretation", "unresolved_blocker", "notes"):
        if decision_bundle[column].astype(str).str.contains(MINIMAL_NUMERICAL_POLICY_NUMERIC_FORBIDDEN_PATTERN).any():
            raise ValueError(f"s2_minimal_numerical_policy_decision_bundle.csv contains exact executable-style quantities in {column}.")

    decision_text = " ".join(decision_bundle.astype(str).agg(" ".join, axis=1).str.lower())
    for required_phrase in (
        "annual_public_anchors_are_validation_or_scaling_evidence_not_direct_hourly_caps",
        "around_one_eaf_heat_equivalent",
        "around_one_to_two_days_of_downstream_throughput",
        "last_modelled_metallic_sink",
        "not_capacity_approval",
        "multi_hour_or_multi_day",
    ):
        if required_phrase not in decision_text:
            raise ValueError(f"s2_minimal_numerical_policy_decision_bundle.csv must include policy phrase: {required_phrase}")

    screening_plan = review_bundle.tables["s2_early_sensitivity_screening_plan.csv"]
    if list(screening_plan.columns) != EARLY_SENSITIVITY_SCREENING_PLAN_COLUMNS:
        raise ValueError("s2_early_sensitivity_screening_plan.csv must match the required column order.")
    if screening_plan["screening_item_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_early_sensitivity_screening_plan.csv must not contain duplicate screening_item_id values.")
    if not EARLY_SENSITIVITY_REQUIRED_PARAMETERS.issubset(set(screening_plan["sensitivity_parameter"].astype(str).str.strip())):
        missing = sorted(EARLY_SENSITIVITY_REQUIRED_PARAMETERS - set(screening_plan["sensitivity_parameter"].astype(str).str.strip()))
        raise ValueError(f"s2_early_sensitivity_screening_plan.csv is missing required sensitivity parameters: {missing}")
    if (~screening_plan["thesis_use_status"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_early_sensitivity_screening_plan.csv must keep thesis_use_status=false for every row.")
    if (~screening_plan["executable_status"].astype(str).str.strip().str.lower().eq("non_executable")).any():
        raise ValueError("s2_early_sensitivity_screening_plan.csv must keep executable_status=non_executable for every row.")
    if (~screening_plan["approval_status"].astype(str).str.strip().str.lower().isin(EARLY_SENSITIVITY_ALLOWED_APPROVAL_STATUSES)).any():
        raise ValueError("s2_early_sensitivity_screening_plan.csv contains invalid approval_status values.")

    return {
        "minimal_numerical_policy_bundle_memo_present": True,
        "minimal_numerical_policy_decision_rows_checked": int(len(decision_bundle)),
        "early_sensitivity_screening_plan_rows_checked": int(len(screening_plan)),
    }


def validate_s2_provisional_dev_input(provisional_dev_input_bundle: GovernanceTableBundle) -> dict[str, Any]:
    tables = provisional_dev_input_bundle.tables
    table_names = set(tables)
    if table_names != PROVISIONAL_DEV_INPUT_REQUIRED_TABLES:
        missing = sorted(PROVISIONAL_DEV_INPUT_REQUIRED_TABLES - table_names)
        extra = sorted(table_names - PROVISIONAL_DEV_INPUT_REQUIRED_TABLES)
        raise ValueError(f"s2_provisional_dev_input tables do not match the required set. missing={missing} extra={extra}")

    if not PROVISIONAL_DEV_INPUT_README.exists():
        raise ValueError("s2_provisional_dev_input/README.md must exist.")
    readme_text = PROVISIONAL_DEV_INPUT_README.read_text(encoding="utf-8").lower()
    for phrase in PROVISIONAL_DEV_INPUT_README_REQUIRED_PHRASES:
        if phrase not in readme_text:
            raise ValueError(f"s2_provisional_dev_input/README.md is missing required phrase: {phrase}")

    if not DEV_INPUT_READINESS_MEMO.exists():
        raise ValueError("STEEL_S2_PROVISIONAL_DEV_INPUT_READINESS.md must exist.")
    readiness_text = DEV_INPUT_READINESS_MEMO.read_text(encoding="utf-8").lower()
    for phrase in DEV_INPUT_READINESS_MEMO_REQUIRED_PHRASES:
        if phrase not in readiness_text:
            raise ValueError(f"STEEL_S2_PROVISIONAL_DEV_INPUT_READINESS.md is missing required phrase: {phrase}")
    if not STORE_CAPACITY_TRANSLATION_REVIEW_MEMO.exists():
        raise ValueError("STEEL_S2_STORE_CAPACITY_TRANSLATION_REVIEW.md must exist.")
    store_review_text = STORE_CAPACITY_TRANSLATION_REVIEW_MEMO.read_text(encoding="utf-8").lower()
    for phrase in STORE_CAPACITY_TRANSLATION_REVIEW_REQUIRED_PHRASES:
        if phrase not in store_review_text:
            raise ValueError(f"STEEL_S2_STORE_CAPACITY_TRANSLATION_REVIEW.md is missing required phrase: {phrase}")

    dev_input_index = _read_csv(PROVISIONAL_DEV_INPUT_INDEX_PATH)
    if list(dev_input_index.columns) != PROVISIONAL_DEV_INPUT_INDEX_COLUMNS:
        raise ValueError("s2_provisional_dev_input_index.csv must match the required column order.")
    dev_value_completion_audit = _read_csv(PROVISIONAL_DEV_VALUE_COMPLETION_AUDIT_PATH)
    if list(dev_value_completion_audit.columns) != PROVISIONAL_DEV_VALUE_COMPLETION_AUDIT_COLUMNS:
        raise ValueError("s2_provisional_dev_value_completion_audit.csv must match the required column order.")
    process_bound_translation_audit = _read_csv(PROCESS_BOUND_TRANSLATION_AUDIT_PATH)
    if list(process_bound_translation_audit.columns) != PROCESS_BOUND_TRANSLATION_AUDIT_COLUMNS:
        raise ValueError("s2_process_bound_translation_audit.csv must match the required column order.")
    target_capacity_reconciliation_audit = _read_csv(TARGET_CAPACITY_RECONCILIATION_AUDIT_PATH)
    if list(target_capacity_reconciliation_audit.columns) != TARGET_CAPACITY_RECONCILIATION_AUDIT_COLUMNS:
        raise ValueError("s2_target_capacity_reconciliation_audit.csv must match the required column order.")
    store_capacity_translation_audit = _read_csv(STORE_CAPACITY_TRANSLATION_AUDIT_PATH)
    if list(store_capacity_translation_audit.columns) != STORE_CAPACITY_TRANSLATION_AUDIT_COLUMNS:
        raise ValueError("s2_store_capacity_translation_audit.csv must match the required column order.")
    buffer_activation_readiness = _read_csv(BUFFER_ACTIVATION_READINESS_PATH)
    if list(buffer_activation_readiness.columns) != BUFFER_ACTIVATION_READINESS_COLUMNS:
        raise ValueError("s2_buffer_activation_readiness_register.csv must match the required column order.")

    total_rows = 0
    approved_row_count = 0
    thesis_usable_row_count = 0
    dev_executable_row_count = 0
    missing_required_row_count = 0
    formula_only_row_count = 0

    for filename, required_columns in PROVISIONAL_DEV_INPUT_FILE_SPECS.items():
        frame = tables[filename]
        if list(frame.columns) != required_columns:
            raise ValueError(f"{filename} must match the required provisional dev input column order.")
        if frame.empty:
            raise ValueError(f"{filename} must contain at least one provisional dev input row.")
        total_rows += int(len(frame))
        formula_only_row_count += _count_formula_only_rows(frame)

        if "approval_status" in frame.columns:
            if (~frame["approval_status"].astype(str).str.strip().str.lower().isin(PROVISIONAL_DEV_INPUT_ALLOWED_APPROVAL_STATUSES)).any():
                raise ValueError(f"{filename} contains invalid provisional dev approval_status values.")
            approved_row_count += int(frame["approval_status"].astype(str).str.strip().str.lower().eq("approved").sum())
            missing_required_row_count += int(frame["approval_status"].astype(str).str.strip().str.lower().eq("missing_required_dev_value").sum())
        if "executable_status" in frame.columns:
            if (~frame["executable_status"].astype(str).str.strip().str.lower().isin(PROVISIONAL_DEV_INPUT_ALLOWED_EXECUTABLE_STATUSES)).any():
                raise ValueError(f"{filename} contains invalid provisional dev executable_status values.")
            dev_executable_row_count += int(frame["executable_status"].astype(str).str.strip().str.lower().eq("dev_executable_only").sum())
        if "thesis_usability" in frame.columns:
            if (~frame["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
                raise ValueError(f"{filename} must keep thesis_usability=false for every row.")
            thesis_usable_row_count += int(frame["thesis_usability"].astype(str).str.strip().str.lower().eq("true").sum())
        if "reviewer_decision_required" in frame.columns:
            if (~frame["reviewer_decision_required"].astype(str).str.strip().str.lower().eq("true")).any():
                raise ValueError(f"{filename} must keep reviewer_decision_required=true for every row.")
        if "codex_may_decide" in frame.columns:
            if (~frame["codex_may_decide"].astype(str).str.strip().str.lower().eq("false")).any():
                raise ValueError(f"{filename} must keep codex_may_decide=false for every row.")

        if "executable_status" in frame.columns and "approval_status" in frame.columns:
            dev_rows = frame["executable_status"].astype(str).str.strip().str.lower().eq("dev_executable_only")
            if dev_rows.any():
                if (~frame.loc[dev_rows, "approval_status"].astype(str).str.strip().str.lower().eq("provisional_development_only")).any():
                    raise ValueError(f"{filename} dev_executable_only rows must also be provisional_development_only.")

    inventory_endpoint_policies = tables["inventory_endpoint_policies.csv"]
    store_capacities = tables["store_capacities.csv"]
    initial_inventories = tables["initial_inventories.csv"]
    terminal_inventory_rules = tables["terminal_inventory_rules.csv"]
    inventory_text = " ".join(inventory_endpoint_policies.astype(str).agg(" ".join, axis=1).str.lower())
    store_text = " ".join(store_capacities.astype(str).agg(" ".join, axis=1).str.lower())
    process_text = " ".join(tables["process_bounds.csv"].astype(str).agg(" ".join, axis=1).str.lower())
    production_targets = tables["production_targets.csv"]
    target_text = " ".join(production_targets.astype(str).agg(" ".join, axis=1).str.lower())
    validation_text = " ".join(tables["validation_targets.csv"].astype(str).agg(" ".join, axis=1).str.lower())
    process_bounds = tables["process_bounds.csv"]

    for phrase in ("cyc50", "not_capacity_approval"):
        if phrase not in inventory_text:
            raise ValueError("inventory_endpoint_policies.csv must keep CYC50 separate from capacity approval.")
    if "multi_hour_or_multi_day" not in store_text:
        raise ValueError("store_capacities.csv must keep hot slab WIP separate from strategic multi-hour or multi-day flexibility.")
    if "unbounded" in store_text:
        raise ValueError("store_capacities.csv must not introduce unbounded store language.")
    if "annual_anchor_requires_translation" not in process_text:
        raise ValueError("process_bounds.csv must explicitly record annual-anchor translation blockers.")
    if "route_neutral" not in target_text:
        raise ValueError("production_targets.csv must keep production targets route-neutral in the base case.")
    if "must_not_drive_constraints" not in validation_text:
        raise ValueError("validation_targets.csv must keep validation anchors out of live constraints.")
    if production_targets["target_name"].astype(str).str.strip().str.lower().str.contains("horizon_total_target").sum() != len(production_targets):
        raise ValueError("production_targets.csv must keep every target row horizon-total.")
    if production_targets["target_variant"].astype(str).str.strip().eq("").any():
        raise ValueError("production_targets.csv must define target_variant for every row.")
    if production_targets.duplicated(subset=["configuration_id", "target_name", "target_variant"]).any():
        raise ValueError("production_targets.csv must not duplicate configuration_id/target_name/target_variant combinations.")

    required_target_variants = {
        ("C0_current_BF_BOF_reference", "horizon_total_target_24h_debug", "feasible_smoke"),
        ("C0_current_BF_BOF_reference", "horizon_total_target_24h_debug", "stress_infeasible_original"),
        ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "horizon_total_target_24h_debug", "feasible_smoke"),
        ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "horizon_total_target_24h_debug", "stress_infeasible_original"),
    }
    actual_target_variants = {
        (
            str(row["configuration_id"]).strip(),
            str(row["target_name"]).strip(),
            str(row["target_variant"]).strip(),
        )
        for row in production_targets.to_dict(orient="records")
    }
    if not required_target_variants.issubset(actual_target_variants):
        missing = sorted(required_target_variants - actual_target_variants)
        raise ValueError(f"production_targets.csv is missing required 24h target variants: {missing}")

    process_dev_rows = process_bounds["executable_status"].astype(str).str.strip().str.lower().eq("dev_executable_only")
    if process_dev_rows.any():
        numeric_values = pd.to_numeric(process_bounds.loc[process_dev_rows, "value"], errors="coerce")
        if numeric_values.isna().any() or (numeric_values <= 0).any():
            raise ValueError("process_bounds.csv dev_executable_only rows must contain positive numeric t/h values.")
        if (~process_bounds.loc[process_dev_rows, "unit"].astype(str).str.strip().str.lower().eq("t_per_hour")).any():
            raise ValueError("process_bounds.csv dev_executable_only rows must use unit t_per_hour.")
        translation_text = process_bounds.loc[process_dev_rows, "translation_basis"].astype(str).str.strip().str.lower()
        if (~translation_text.str.contains("annual_anchor=")).any():
            raise ValueError("process_bounds.csv dev_executable_only rows must record annual_anchor= in translation_basis.")
        if (~translation_text.str.contains("effective_hours=8760")).any():
            raise ValueError("process_bounds.csv dev_executable_only rows must record effective_hours=8760 in translation_basis.")
        if (~translation_text.str.contains("envelope_case=")).any():
            raise ValueError("process_bounds.csv dev_executable_only rows must record envelope_case= in translation_basis.")
        value_basis_text = process_bounds.loc[process_dev_rows, "value_basis"].astype(str).str.strip().str.lower()
        if (~value_basis_text.str.contains("process_class=")).any():
            raise ValueError("process_bounds.csv dev_executable_only rows must record process_class= in value_basis.")

    store_dev_rows = store_capacities["executable_status"].astype(str).str.strip().str.lower().eq("dev_executable_only")
    store_formula_rows = store_capacities["value_basis"].astype(str).str.strip().str.lower().str.contains("formula")
    if store_dev_rows.any():
        store_values = pd.to_numeric(store_capacities.loc[store_dev_rows, "value"], errors="coerce")
        if store_values.isna().any() or (store_values <= 0).any():
            raise ValueError("store_capacities.csv dev_executable_only rows must contain positive numeric tonnes.")
        if (~store_capacities.loc[store_dev_rows, "unit"].astype(str).str.strip().str.lower().eq("t")).any():
            raise ValueError("store_capacities.csv dev_executable_only rows must use unit t.")
        if (~store_capacities.loc[store_dev_rows, "value_basis"].astype(str).str.strip().str.lower().str.contains("store_class=")).any():
            raise ValueError("store_capacities.csv dev_executable_only rows must record store_class= in value_basis.")
    if (store_formula_rows & store_dev_rows).any():
        raise ValueError("store_capacities.csv formula-only rows must not be dev_executable_only.")

    store_lookup = {
        (str(row["configuration_id"]).strip(), str(row["store_id"]).strip()): row
        for row in store_capacities.to_dict(orient="records")
    }
    initial_lookup = {
        (str(row["configuration_id"]).strip(), str(row["store_id"]).strip()): row
        for row in initial_inventories.to_dict(orient="records")
    }
    terminal_lookup = {
        (str(row["configuration_id"]).strip(), str(row["store_id"]).strip()): row
        for row in terminal_inventory_rules.to_dict(orient="records")
    }
    endpoint_lookup = {
        (str(row["configuration_id"]).strip(), str(row["store_id"]).strip()): row
        for row in inventory_endpoint_policies.to_dict(orient="records")
    }
    for key, store_row in store_lookup.items():
        if key not in initial_lookup or key not in terminal_lookup or key not in endpoint_lookup:
            raise ValueError(f"store-capacity inventory linkage is missing for {key}.")
        initial_row = initial_lookup[key]
        terminal_row = terminal_lookup[key]
        endpoint_row = endpoint_lookup[key]
        if str(store_row["executable_status"]).strip().lower() == "dev_executable_only":
            capacity_value = float(store_row["value"])
            initial_value = float(initial_row["value"])
            if abs(initial_value - (0.5 * capacity_value)) > 1e-6:
                raise ValueError(f"initial_inventories.csv must keep initial inventory at 50 percent of capacity for {key}.")
            if str(initial_row["executable_status"]).strip().lower() != "dev_executable_only":
                raise ValueError(f"initial_inventories.csv must keep executable status aligned for {key}.")
            if str(terminal_row["executable_status"]).strip().lower() != "dev_executable_only":
                raise ValueError(f"terminal_inventory_rules.csv must keep executable status aligned for {key}.")
            if str(endpoint_row["executable_status"]).strip().lower() != "dev_executable_only":
                raise ValueError(f"inventory_endpoint_policies.csv must keep executable status aligned for {key}.")
            if str(endpoint_row["value"]).strip() != "CYC50":
                raise ValueError(f"inventory_endpoint_policies.csv must keep CYC50 endpoint policy for executable stores {key}.")
            if abs(float(terminal_row["value"]) - 1.0) > 1e-9:
                raise ValueError(f"terminal_inventory_rules.csv must keep terminal equals beginning for executable stores {key}.")
        else:
            if str(initial_row["executable_status"]).strip().lower() != "not_executable":
                raise ValueError(f"initial_inventories.csv must keep non-executable status aligned for blocked stores {key}.")
            if str(terminal_row["executable_status"]).strip().lower() != "not_executable":
                raise ValueError(f"terminal_inventory_rules.csv must keep non-executable status aligned for blocked stores {key}.")
            if str(endpoint_row["executable_status"]).strip().lower() != "not_executable":
                raise ValueError(f"inventory_endpoint_policies.csv must keep non-executable status aligned for blocked stores {key}.")

    audited_process_row_ids = set(process_bound_translation_audit["process_unit_or_asset"].astype(str).str.strip() + "||" + process_bound_translation_audit["configuration_id"].astype(str).str.strip() + "||" + process_bound_translation_audit["route_id"].astype(str).str.strip() + "||" + process_bound_translation_audit["bound_type"].astype(str).str.strip())
    expected_process_row_ids = set(process_bounds["process_unit_id"].astype(str).str.strip() + "||" + process_bounds["configuration_id"].astype(str).str.strip() + "||" + process_bounds["route_id"].astype(str).str.strip() + "||" + process_bounds["parameter_name"].astype(str).str.strip())
    if audited_process_row_ids != expected_process_row_ids:
        missing = sorted(expected_process_row_ids - audited_process_row_ids)
        extra = sorted(audited_process_row_ids - expected_process_row_ids)
        raise ValueError(f"s2_process_bound_translation_audit.csv process-bound coverage mismatch. missing={missing} extra={extra}")
    if (~process_bound_translation_audit["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_process_bound_translation_audit.csv must keep thesis_usability=false.")
    if (~process_bound_translation_audit["reviewer_decision_required"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("s2_process_bound_translation_audit.csv must keep reviewer_decision_required=true.")
    if (~process_bound_translation_audit["codex_may_decide"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_process_bound_translation_audit.csv must keep codex_may_decide=false.")

    if target_capacity_reconciliation_audit["audit_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_target_capacity_reconciliation_audit.csv must not contain duplicate audit_id values.")
    if (~target_capacity_reconciliation_audit["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_target_capacity_reconciliation_audit.csv must keep thesis_usability=false.")
    if (~target_capacity_reconciliation_audit["reviewer_decision_required"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("s2_target_capacity_reconciliation_audit.csv must keep reviewer_decision_required=true.")
    if (~target_capacity_reconciliation_audit["codex_may_decide"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_target_capacity_reconciliation_audit.csv must keep codex_may_decide=false.")
    if (~target_capacity_reconciliation_audit["approval_status"].astype(str).str.strip().str.lower().eq("provisional_development_only")).any():
        raise ValueError("s2_target_capacity_reconciliation_audit.csv must keep approval_status=provisional_development_only.")
    if (~target_capacity_reconciliation_audit["executable_status"].astype(str).str.strip().str.lower().eq("dev_executable_only")).any():
        raise ValueError("s2_target_capacity_reconciliation_audit.csv must keep executable_status=dev_executable_only.")

    audited_variants = {
        (
            str(row["configuration_id"]).strip(),
            f"horizon_total_target_{str(row['horizon_hours']).strip()}h_debug",
            str(row["target_variant"]).strip(),
        )
        for row in target_capacity_reconciliation_audit.to_dict(orient="records")
    }
    if audited_variants != required_target_variants:
        missing = sorted(required_target_variants - audited_variants)
        extra = sorted(audited_variants - required_target_variants)
        raise ValueError(f"s2_target_capacity_reconciliation_audit.csv must cover the required 24h target variants exactly. missing={missing} extra={extra}")

    target_lookup = {
        (
            str(row["configuration_id"]).strip(),
            str(row["target_name"]).strip(),
            str(row["target_variant"]).strip(),
        ): row
        for row in production_targets.to_dict(orient="records")
    }
    for row in target_capacity_reconciliation_audit.to_dict(orient="records"):
        key = (
            str(row["configuration_id"]).strip(),
            f"horizon_total_target_{str(row['horizon_hours']).strip()}h_debug",
            str(row["target_variant"]).strip(),
        )
        if key not in target_lookup:
            raise ValueError(f"s2_target_capacity_reconciliation_audit.csv references a missing production-target row: {key}")
        target_row = target_lookup[key]
        target_value = float(target_row["value"])
        reconciled_target = float(row["reconciled_target_t"])
        max_capacity = float(row["max_implied_liquid_steel_t"])
        if abs(target_value - reconciled_target) > 1e-6:
            raise ValueError(f"s2_target_capacity_reconciliation_audit.csv reconciled target does not match production_targets.csv for {key}.")
        if row["target_variant"] == "feasible_smoke":
            if not target_value < max_capacity:
                raise ValueError(f"feasible_smoke target must remain below max implied capacity for {key}.")
            if abs(float(row["target_fraction_of_capacity"]) - 0.85) > 1e-9:
                raise ValueError(f"feasible_smoke target fraction must equal 0.85 for {key}.")
        if row["target_variant"] == "stress_infeasible_original":
            if not target_value > max_capacity:
                raise ValueError(f"stress_infeasible_original target must remain above max implied capacity for {key}.")

    audited_store_keys = {
        (str(row["configuration_id"]).strip(), str(row["store_id"]).strip())
        for row in store_capacity_translation_audit.to_dict(orient="records")
    }
    expected_store_keys = set(store_lookup)
    if audited_store_keys != expected_store_keys:
        missing = sorted(expected_store_keys - audited_store_keys)
        extra = sorted(audited_store_keys - expected_store_keys)
        raise ValueError(f"s2_store_capacity_translation_audit.csv store coverage mismatch. missing={missing} extra={extra}")
    if (~store_capacity_translation_audit["reviewer_decision_required"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("s2_store_capacity_translation_audit.csv must keep reviewer_decision_required=true.")
    if (~store_capacity_translation_audit["codex_may_decide"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_store_capacity_translation_audit.csv must keep codex_may_decide=false.")
    if (~store_capacity_translation_audit["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_store_capacity_translation_audit.csv must keep thesis_usability=false.")
    store_audit_text = " ".join(store_capacity_translation_audit.astype(str).agg(" ".join, axis=1).str.lower())
    for phrase in ("not_capacity_approval", "multi_hour_or_multi_day", "downstream", "hot_metal", "dri"):
        if phrase not in store_audit_text:
            raise ValueError(f"s2_store_capacity_translation_audit.csv is missing required diagnostic phrase: {phrase}")

    if buffer_activation_readiness["buffer_gate_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_buffer_activation_readiness_register.csv must not contain duplicate buffer_gate_id values.")
    if (~buffer_activation_readiness["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_buffer_activation_readiness_register.csv must keep thesis_usability=false.")
    if not BUFFER_ACTIVATION_REQUIRED_BUFFER_TYPES.issubset(set(buffer_activation_readiness["buffer_type"].astype(str).str.strip())):
        missing = sorted(BUFFER_ACTIVATION_REQUIRED_BUFFER_TYPES - set(buffer_activation_readiness["buffer_type"].astype(str).str.strip()))
        raise ValueError(f"s2_buffer_activation_readiness_register.csv is missing required buffer types: {missing}")
    readiness_lookup = {
        (str(row["configuration_id"]).strip(), str(row["store_id"]).strip()): row
        for row in buffer_activation_readiness.to_dict(orient="records")
        if str(row["store_id"]).strip() in set(store_capacities["store_id"].astype(str).str.strip())
    }
    for key, store_row in store_lookup.items():
        if key not in readiness_lookup:
            raise ValueError(f"s2_buffer_activation_readiness_register.csv is missing readiness coverage for {key}.")
        readiness_row = readiness_lookup[key]
        expected_ready = str(store_row["executable_status"]).strip().lower() == "dev_executable_only"
        if str(readiness_row["capacity_ready"]).strip().lower() != str(expected_ready).lower():
            raise ValueError(f"s2_buffer_activation_readiness_register.csv capacity_ready mismatch for {key}.")
    activation_ready_rows = buffer_activation_readiness["activation_status"].astype(str).str.strip().eq("guarded_ready")
    if activation_ready_rows.sum() != 3:
        raise ValueError("s2_buffer_activation_readiness_register.csv must identify exactly three guarded_ready buffer rows in S2.10a.")
    activation_text = " ".join(buffer_activation_readiness.astype(str).agg(" ".join, axis=1).str.lower())
    for phrase in ("coke", "sinter", "pellet", "finished_goods", "liquid_steel_ladle_tundish", "hot_slab_wip"):
        if phrase not in activation_text:
            raise ValueError(f"s2_buffer_activation_readiness_register.csv is missing required scope text: {phrase}")

    expected_index_files = set(PROVISIONAL_DEV_INPUT_FILE_SPECS) - {"dev_input_completeness_report.csv"}
    actual_index_files = set(dev_input_index["dev_input_file"].astype(str).str.strip())
    if actual_index_files != expected_index_files:
        missing = sorted(expected_index_files - actual_index_files)
        extra = sorted(actual_index_files - expected_index_files)
        raise ValueError(f"s2_provisional_dev_input_index.csv file set mismatch. missing={missing} extra={extra}")
    for record in dev_input_index.to_dict(orient="records"):
        filename = str(record["dev_input_file"]).strip()
        frame = tables[filename]
        expected_counts = {
            "row_count": int(len(frame)),
            "provisional_value_count": int(frame["approval_status"].astype(str).str.strip().str.lower().eq("provisional_development_only").sum()),
            "formula_only_row_count": int(_count_formula_only_rows(frame)),
            "missing_required_value_count": int(frame["approval_status"].astype(str).str.strip().str.lower().eq("missing_required_dev_value").sum()),
            "sensitivity_row_count": int(len(frame) if filename == "sensitivity_variants.csv" else (0 if "sensitivity_case" not in frame.columns else frame["sensitivity_case"].astype(str).str.strip().str.lower().isin({"low", "high", "sensitivity"}).sum())),
            "dev_executable_row_count": int(0 if "executable_status" not in frame.columns else frame["executable_status"].astype(str).str.strip().str.lower().eq("dev_executable_only").sum()),
            "thesis_usable_row_count": int(0),
            "approved_row_count": int(0),
        }
        for field_name, expected_value in expected_counts.items():
            if int(record[field_name]) != expected_value:
                raise ValueError(f"s2_provisional_dev_input_index.csv mismatch for {filename} field {field_name}: expected {expected_value} found {record[field_name]}")

    completeness = tables["dev_input_completeness_report.csv"]
    expected_categories = {
        "process_bounds",
        "conversion_coefficients",
        "store_capacities",
        "initial_inventories",
        "terminal_inventory_rules",
        "production_targets",
        "inventory_endpoint_policies",
        "validation_targets",
        "sensitivity_variants",
    }
    if set(completeness["input_category"].astype(str).str.strip()) != expected_categories:
        raise ValueError("dev_input_completeness_report.csv must cover every required provisional dev input category exactly once.")

    audited_row_ids = set(dev_value_completion_audit["row_id"].astype(str).str.strip())
    updated_rows = set()
    for filename in ("process_bounds.csv", "conversion_coefficients.csv", "production_targets.csv"):
        frame = tables[filename]
        updated_rows.update(frame["row_id"].astype(str).str.strip())
    if audited_row_ids != updated_rows:
        missing = sorted(updated_rows - audited_row_ids)
        extra = sorted(audited_row_ids - updated_rows)
        raise ValueError(f"s2_provisional_dev_value_completion_audit.csv row coverage mismatch. missing={missing} extra={extra}")
    if (~dev_value_completion_audit["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_provisional_dev_value_completion_audit.csv must keep thesis_usability=false.")
    if (~dev_value_completion_audit["reviewer_decision_required"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("s2_provisional_dev_value_completion_audit.csv must keep reviewer_decision_required=true.")
    if (~dev_value_completion_audit["codex_may_decide"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_provisional_dev_value_completion_audit.csv must keep codex_may_decide=false.")

    return {
        "dev_input_readiness_memo_present": True,
        "store_capacity_translation_review_memo_present": True,
        "provisional_dev_input_files_checked": int(len(PROVISIONAL_DEV_INPUT_FILE_SPECS) + 1),
        "provisional_dev_input_rows_checked": int(total_rows),
        "provisional_dev_input_index_rows_checked": int(len(dev_input_index)),
        "provisional_dev_input_formula_only_rows": int(formula_only_row_count),
        "provisional_dev_input_approved_rows": int(approved_row_count),
        "provisional_dev_input_thesis_usable_rows": int(thesis_usable_row_count),
        "provisional_dev_input_dev_executable_rows": int(dev_executable_row_count),
        "provisional_dev_input_missing_required_rows": int(missing_required_row_count),
        "provisional_dev_value_completion_audit_rows_checked": int(len(dev_value_completion_audit)),
        "process_bound_translation_audit_rows_checked": int(len(process_bound_translation_audit)),
        "target_capacity_reconciliation_audit_rows_checked": int(len(target_capacity_reconciliation_audit)),
        "store_capacity_translation_audit_rows_checked": int(len(store_capacity_translation_audit)),
        "buffer_activation_readiness_rows_checked": int(len(buffer_activation_readiness)),
        "process_bound_dev_executable_rows": int(process_dev_rows.sum()),
        "process_bound_non_executable_rows": int((~process_dev_rows).sum()),
        "store_capacity_dev_executable_rows": int(store_dev_rows.sum()),
        "store_capacity_formula_only_rows": int(store_formula_rows.sum()),
        "store_capacity_excluded_or_deferred_rows": int((~store_dev_rows).sum()),
        "buffer_activation_ready_rows": int(activation_ready_rows.sum()),
    }


def validate_s2_liquid_steel_smoke_builder_artifacts() -> dict[str, Any]:
    if not LIQUID_STEEL_SMOKE_BUILDER_MODULE.exists():
        raise ValueError("liquid_steel_smoke_builder.py must exist for S2.9a.")
    if not LIQUID_STEEL_SMOKE_BUILDER_SCOPE_MEMO.exists():
        raise ValueError("STEEL_S2_LIQUID_STEEL_SMOKE_BUILDER_SCOPE.md must exist for S2.9a.")

    scope_text = LIQUID_STEEL_SMOKE_BUILDER_SCOPE_MEMO.read_text(encoding="utf-8").lower()
    for phrase in LIQUID_STEEL_SMOKE_BUILDER_SCOPE_REQUIRED_PHRASES:
        if phrase not in scope_text:
            raise ValueError(f"STEEL_S2_LIQUID_STEEL_SMOKE_BUILDER_SCOPE.md is missing required phrase: {phrase}")

    builder_source = LIQUID_STEEL_SMOKE_BUILDER_MODULE.read_text(encoding="utf-8").lower()
    required_builder_tokens = (
        "s2_provisional_dev_input",
        "s2_approved_model_input",
        "thesis_usability",
        "dev_executable_only",
        "not_executable",
        "target_variant",
        "inventory_mode",
        "first_buffers",
        "store_inventory",
        "inventory_balance",
        "terminal_inventory",
        "overproduction",
        "minimise_overproduction_dev_only",
        "shortfall_slack_active",
    )
    for token in required_builder_tokens:
        if token not in builder_source:
            raise ValueError(f"liquid_steel_smoke_builder.py is missing required guard token: {token}")

    return {
        "liquid_steel_smoke_builder_module_present": True,
        "liquid_steel_smoke_builder_scope_memo_present": True,
    }


def validate_s2_liquid_steel_smoke_runner_artifacts() -> dict[str, Any]:
    if not LIQUID_STEEL_SMOKE_RUNNER_MODULE.exists():
        raise ValueError("liquid_steel_smoke_runner.py must exist for S2.9b.")
    if not LIQUID_STEEL_SMOKE_DIAGNOSTICS_MEMO.exists():
        raise ValueError("STEEL_S2_LIQUID_STEEL_SMOKE_DIAGNOSTICS.md must exist for S2.9b.")

    memo_text = LIQUID_STEEL_SMOKE_DIAGNOSTICS_MEMO.read_text(encoding="utf-8").lower()
    for phrase in LIQUID_STEEL_SMOKE_DIAGNOSTICS_REQUIRED_PHRASES:
        if phrase not in memo_text:
            raise ValueError(f"STEEL_S2_LIQUID_STEEL_SMOKE_DIAGNOSTICS.md is missing required phrase: {phrase}")

    runner_source = LIQUID_STEEL_SMOKE_RUNNER_MODULE.read_text(encoding="utf-8").lower()
    required_tokens = (
        "s2_provisional_dev_input",
        "s2_approved_model_input",
        "thesis_usability",
        "dev_executable_only",
        "not_attempted_solver_unavailable",
        "target_variant",
        "inventory_mode",
        "first_buffers",
        "active_store_ids",
        "overproduction",
        "minimise_overproduction_dev_only",
        "shortfall_slack_active",
        "inventory_active",
        "downstream_active",
    )
    for token in required_tokens:
        if token not in runner_source:
            raise ValueError(f"liquid_steel_smoke_runner.py is missing required guard token: {token}")

    return {
        "liquid_steel_smoke_runner_module_present": True,
        "liquid_steel_smoke_diagnostics_memo_present": True,
    }


def validate_s2_liquid_steel_smoke_baseline_artifacts(review_bundle: GovernanceTableBundle) -> dict[str, Any]:
    if not LIQUID_STEEL_SMOKE_BASELINE_FREEZE_MEMO.exists():
        raise ValueError("STEEL_S2_LIQUID_STEEL_SMOKE_BASELINE_FREEZE.md must exist for S2.9e.")
    memo_text = LIQUID_STEEL_SMOKE_BASELINE_FREEZE_MEMO.read_text(encoding="utf-8").lower()
    for phrase in LIQUID_STEEL_SMOKE_BASELINE_FREEZE_REQUIRED_PHRASES:
        if phrase not in memo_text:
            raise ValueError(f"STEEL_S2_LIQUID_STEEL_SMOKE_BASELINE_FREEZE.md is missing required phrase: {phrase}")

    baseline = review_bundle.tables["s2_liquid_steel_smoke_baseline_summary.csv"]
    if list(baseline.columns) != LIQUID_STEEL_SMOKE_BASELINE_SUMMARY_COLUMNS:
        raise ValueError("s2_liquid_steel_smoke_baseline_summary.csv must match the required column order.")
    if baseline["case_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_liquid_steel_smoke_baseline_summary.csv must not contain duplicate case_id values.")
    required_case_keys = {
        ("C0_current_BF_BOF_reference", "feasible_smoke"),
        ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "feasible_smoke"),
        ("C0_current_BF_BOF_reference", "stress_infeasible_original"),
        ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "stress_infeasible_original"),
    }
    actual_case_keys = {
        (str(row["configuration_id"]).strip(), str(row["target_variant"]).strip())
        for row in baseline.to_dict(orient="records")
    }
    if actual_case_keys != required_case_keys:
        missing = sorted(required_case_keys - actual_case_keys)
        extra = sorted(actual_case_keys - required_case_keys)
        raise ValueError(f"s2_liquid_steel_smoke_baseline_summary.csv case coverage mismatch. missing={missing} extra={extra}")
    if (~baseline["input_surface"].astype(str).str.strip().eq("s2_provisional_dev_input")).any():
        raise ValueError("s2_liquid_steel_smoke_baseline_summary.csv must keep input_surface=s2_provisional_dev_input.")
    for column in ("shortfall_slack_active", "inventory_active", "downstream_active", "approved_input_used", "thesis_usability"):
        if (~baseline[column].astype(str).str.strip().str.lower().eq("false")).any():
            raise ValueError(f"s2_liquid_steel_smoke_baseline_summary.csv must keep {column}=false for every row.")
    if (~baseline["objective_type"].astype(str).str.strip().eq("minimise_overproduction_dev_only")).any():
        raise ValueError("s2_liquid_steel_smoke_baseline_summary.csv must keep objective_type=minimise_overproduction_dev_only.")
    if (~baseline["binary_count"].astype(str).str.strip().eq("0")).any():
        raise ValueError("s2_liquid_steel_smoke_baseline_summary.csv must keep binary_count=0 for every row.")
    feasible_rows = baseline["target_variant"].astype(str).str.strip().eq("feasible_smoke")
    stress_rows = baseline["target_variant"].astype(str).str.strip().eq("stress_infeasible_original")
    if (~baseline.loc[feasible_rows, "solve_status"].astype(str).str.strip().eq("optimal")).any():
        raise ValueError("feasible_smoke rows must be marked optimal in s2_liquid_steel_smoke_baseline_summary.csv.")
    if (~baseline.loc[stress_rows, "solve_status"].astype(str).str.strip().eq("infeasible")).any():
        raise ValueError("stress_infeasible_original rows must be marked infeasible in s2_liquid_steel_smoke_baseline_summary.csv.")

    attribution = review_bundle.tables["s2_liquid_steel_infeasibility_attribution.csv"]
    if list(attribution.columns) != LIQUID_STEEL_INFEASIBILITY_ATTRIBUTION_COLUMNS:
        raise ValueError("s2_liquid_steel_infeasibility_attribution.csv must match the required column order.")
    if attribution["attribution_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_liquid_steel_infeasibility_attribution.csv must not contain duplicate attribution_id values.")
    required_attribution_configs = {"C0_current_BF_BOF_reference", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"}
    if set(attribution["configuration_id"].astype(str).str.strip()) != required_attribution_configs:
        raise ValueError("s2_liquid_steel_infeasibility_attribution.csv must include exactly the C0 and C1 stress cases.")
    if (~attribution["target_variant"].astype(str).str.strip().eq("stress_infeasible_original")).any():
        raise ValueError("s2_liquid_steel_infeasibility_attribution.csv must cover stress_infeasible_original only.")
    if (~attribution["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_liquid_steel_infeasibility_attribution.csv must keep thesis_usability=false.")
    attribution_text = " ".join(attribution.astype(str).agg(" ".join, axis=1).str.lower())
    for phrase in ("dri", "eaf", "bf_bof", "diagnostic", "not yet an executable"):
        if phrase not in attribution_text:
            raise ValueError(f"s2_liquid_steel_infeasibility_attribution.csv is missing diagnostic phrase: {phrase}")

    gates = review_bundle.tables["s2_next_scope_gate_register.csv"]
    if list(gates.columns) != S2_NEXT_SCOPE_GATE_REGISTER_COLUMNS:
        raise ValueError("s2_next_scope_gate_register.csv must match the required column order.")
    if gates["gate_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_next_scope_gate_register.csv must not contain duplicate gate_id values.")
    actual_gates = set(gates["gate_name"].astype(str).str.strip())
    if actual_gates != S2_NEXT_SCOPE_REQUIRED_GATES:
        missing = sorted(S2_NEXT_SCOPE_REQUIRED_GATES - actual_gates)
        extra = sorted(actual_gates - S2_NEXT_SCOPE_REQUIRED_GATES)
        raise ValueError(f"s2_next_scope_gate_register.csv gate coverage mismatch. missing={missing} extra={extra}")
    if (~gates["current_status"].astype(str).str.strip().eq("blocked")).any():
        raise ValueError("s2_next_scope_gate_register.csv must keep current_status=blocked for every row.")
    if (~gates["blocking_risk"].astype(str).str.strip().isin({"high", "medium", "low"})).any():
        raise ValueError("s2_next_scope_gate_register.csv must keep blocking_risk within high/medium/low.")

    return {
        "liquid_steel_smoke_baseline_freeze_memo_present": True,
        "liquid_steel_smoke_baseline_rows_checked": int(len(baseline)),
        "liquid_steel_smoke_infeasibility_attribution_rows_checked": int(len(attribution)),
        "liquid_steel_next_scope_gate_rows_checked": int(len(gates)),
    }


def validate_s2_first_buffer_inventory_activation_artifacts(review_bundle: GovernanceTableBundle) -> dict[str, Any]:
    if not LIQUID_STEEL_FIRST_BUFFER_INVENTORY_ACTIVATION_MEMO.exists():
        raise ValueError("STEEL_S2_FIRST_BUFFER_INVENTORY_ACTIVATION.md must exist for S2.10b.")
    memo_text = LIQUID_STEEL_FIRST_BUFFER_INVENTORY_ACTIVATION_MEMO.read_text(encoding="utf-8").lower()
    for phrase in LIQUID_STEEL_FIRST_BUFFER_INVENTORY_ACTIVATION_REQUIRED_PHRASES:
        if phrase not in memo_text:
            raise ValueError(
                f"STEEL_S2_FIRST_BUFFER_INVENTORY_ACTIVATION.md is missing required phrase: {phrase}"
            )

    summary = review_bundle.tables["s2_buffer_inventory_smoke_summary.csv"]
    if list(summary.columns) != BUFFER_INVENTORY_SMOKE_SUMMARY_COLUMNS:
        raise ValueError("s2_buffer_inventory_smoke_summary.csv must match the required column order.")
    if summary["case_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_buffer_inventory_smoke_summary.csv must not contain duplicate case_id values.")
    required_case_keys = {
        ("C0_current_BF_BOF_reference", "feasible_smoke"),
        ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "feasible_smoke"),
        ("C0_current_BF_BOF_reference", "stress_infeasible_original"),
        ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "stress_infeasible_original"),
    }
    actual_case_keys = {
        (str(row["configuration_id"]).strip(), str(row["target_variant"]).strip())
        for row in summary.to_dict(orient="records")
    }
    if actual_case_keys != required_case_keys:
        missing = sorted(required_case_keys - actual_case_keys)
        extra = sorted(actual_case_keys - required_case_keys)
        raise ValueError(f"s2_buffer_inventory_smoke_summary.csv case coverage mismatch. missing={missing} extra={extra}")
    if (~summary["inventory_mode"].astype(str).str.strip().eq("first_buffers")).any():
        raise ValueError("s2_buffer_inventory_smoke_summary.csv must keep inventory_mode=first_buffers.")
    for column in ("inventory_active", "thesis_usability"):
        if (~summary[column].astype(str).str.strip().str.lower().eq("true" if column == "inventory_active" else "false")).any():
            raise ValueError(f"s2_buffer_inventory_smoke_summary.csv must keep {column} consistent for every row.")
    for column in ("shortfall_slack_active", "downstream_active"):
        if (~summary[column].astype(str).str.strip().str.lower().eq("false")).any():
            raise ValueError(f"s2_buffer_inventory_smoke_summary.csv must keep {column}=false for every row.")
    if (~summary["binary_count"].astype(str).str.strip().eq("0")).any():
        raise ValueError("s2_buffer_inventory_smoke_summary.csv must keep binary_count=0 for every row.")
    if (~summary["active_store_count"].astype(str).str.strip().isin({"1", "2"})).any():
        raise ValueError("s2_buffer_inventory_smoke_summary.csv must keep active_store_count within {1,2}.")

    for row in summary.to_dict(orient="records"):
        active_store_ids = {token for token in str(row["active_store_ids"]).split(";") if token and token != "none"}
        if not active_store_ids:
            raise ValueError("Each first-buffer inventory summary row must include at least one active store.")
        if not active_store_ids.issubset(FIRST_BUFFER_ACTIVE_STORE_IDS):
            invalid = sorted(active_store_ids - FIRST_BUFFER_ACTIVE_STORE_IDS)
            raise ValueError(f"s2_buffer_inventory_smoke_summary.csv contains unsupported active store IDs: {invalid}")
        if str(row["configuration_id"]).strip() == "C0_current_BF_BOF_reference" and active_store_ids != {"c0_hot_metal_buffer"}:
            raise ValueError("C0 first-buffer runs must activate only c0_hot_metal_buffer.")
        if str(row["configuration_id"]).strip() == "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF" and active_store_ids != {"c1_hot_metal_buffer", "c1_dri_hdri_buffer"}:
            raise ValueError("C1 first-buffer runs must activate only c1_hot_metal_buffer and c1_dri_hdri_buffer.")

    feasible_rows = summary["target_variant"].astype(str).str.strip().eq("feasible_smoke")
    stress_rows = summary["target_variant"].astype(str).str.strip().eq("stress_infeasible_original")
    if (~summary.loc[feasible_rows, "solve_status"].astype(str).str.strip().isin({"optimal", "feasible"})).any():
        raise ValueError("Feasible first-buffer rows must be marked optimal or feasible.")
    if (~summary.loc[stress_rows, "solve_status"].astype(str).str.strip().eq("infeasible")).any():
        raise ValueError("Stress first-buffer rows must remain infeasible.")

    summary_text = " ".join(summary.astype(str).agg(" ".join, axis=1).str.lower())
    for phrase in ("c0_hot_metal_buffer", "c1_hot_metal_buffer", "c1_dri_hdri_buffer"):
        if phrase not in summary_text:
            raise ValueError(f"s2_buffer_inventory_smoke_summary.csv is missing required active-store phrase: {phrase}")

    return {
        "liquid_steel_first_buffer_inventory_activation_memo_present": True,
        "buffer_inventory_smoke_summary_rows_checked": int(len(summary)),
        "buffer_inventory_active_store_rows_checked": int(summary["active_store_count"].astype(int).sum()),
    }


def validate_s2_first_buffer_aware_baseline_artifacts(review_bundle: GovernanceTableBundle) -> dict[str, Any]:
    if not LIQUID_STEEL_FIRST_BUFFER_AWARE_BASELINE_FREEZE_MEMO.exists():
        raise ValueError("STEEL_S2_FIRST_BUFFER_AWARE_BASELINE_FREEZE.md must exist for S2.10c.")
    memo_text = LIQUID_STEEL_FIRST_BUFFER_AWARE_BASELINE_FREEZE_MEMO.read_text(encoding="utf-8").lower()
    for phrase in LIQUID_STEEL_FIRST_BUFFER_AWARE_BASELINE_FREEZE_REQUIRED_PHRASES:
        if phrase not in memo_text:
            raise ValueError(
                f"STEEL_S2_FIRST_BUFFER_AWARE_BASELINE_FREEZE.md is missing required phrase: {phrase}"
            )

    interpretation = review_bundle.tables["s2_inventory_use_interpretation_register.csv"]
    if list(interpretation.columns) != INVENTORY_USE_INTERPRETATION_COLUMNS:
        raise ValueError("s2_inventory_use_interpretation_register.csv must match the required column order.")
    if interpretation["interpretation_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_inventory_use_interpretation_register.csv must not contain duplicate interpretation_id values.")
    if len(interpretation) != 3:
        raise ValueError("s2_inventory_use_interpretation_register.csv must contain exactly 3 feasible-store rows.")
    required_stores = {"c0_hot_metal_buffer", "c1_hot_metal_buffer", "c1_dri_hdri_buffer"}
    if set(interpretation["store_id"].astype(str).str.strip()) != required_stores:
        raise ValueError("s2_inventory_use_interpretation_register.csv must cover only the three activated feasible stores.")
    for column in ("hit_zero", "terminal_satisfied", "acceptable_for_24h_smoke"):
        if (~interpretation[column].astype(str).str.strip().str.lower().eq("true")).any():
            raise ValueError(f"s2_inventory_use_interpretation_register.csv must keep {column}=true for every row.")
    for column in ("hit_capacity", "acceptable_for_one_week_without_more_checks", "thesis_usability"):
        if (~interpretation[column].astype(str).str.strip().str.lower().eq("false")).any():
            raise ValueError(f"s2_inventory_use_interpretation_register.csv must keep {column}=false for every row.")
    interpretation_text = " ".join(interpretation.astype(str).agg(" ".join, axis=1).str.lower())
    for phrase in (
        "synchronisation only",
        "short-term surge only",
        "initial inventory sensitivity",
        "one-week gate review",
    ):
        if phrase not in interpretation_text:
            raise ValueError(f"s2_inventory_use_interpretation_register.csv is missing required interpretation phrase: {phrase}")

    baseline = review_bundle.tables["s2_first_buffer_aware_baseline_summary.csv"]
    if list(baseline.columns) != FIRST_BUFFER_AWARE_BASELINE_SUMMARY_COLUMNS:
        raise ValueError("s2_first_buffer_aware_baseline_summary.csv must match the required column order.")
    if baseline["case_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_first_buffer_aware_baseline_summary.csv must not contain duplicate case_id values.")
    if len(baseline) != 4:
        raise ValueError("s2_first_buffer_aware_baseline_summary.csv must contain exactly 4 baseline rows.")
    if (~baseline["inventory_mode"].astype(str).str.strip().eq("first_buffers")).any():
        raise ValueError("s2_first_buffer_aware_baseline_summary.csv must keep inventory_mode=first_buffers.")
    for column in ("shortfall_slack_active", "downstream_active", "thesis_usability"):
        if (~baseline[column].astype(str).str.strip().str.lower().eq("false")).any():
            raise ValueError(f"s2_first_buffer_aware_baseline_summary.csv must keep {column}=false for every row.")
    if (~baseline["binary_count"].astype(str).str.strip().eq("0")).any():
        raise ValueError("s2_first_buffer_aware_baseline_summary.csv must keep binary_count=0 for every row.")
    feasible_rows = baseline["target_variant"].astype(str).str.strip().eq("feasible_smoke")
    stress_rows = baseline["target_variant"].astype(str).str.strip().eq("stress_infeasible_original")
    if (~baseline.loc[feasible_rows, "solve_status"].astype(str).str.strip().eq("optimal")).any():
        raise ValueError("Feasible first-buffer baseline rows must be marked optimal.")
    if (~baseline.loc[stress_rows, "solve_status"].astype(str).str.strip().eq("infeasible")).any():
        raise ValueError("Stress first-buffer baseline rows must be marked infeasible.")
    if (~baseline.loc[feasible_rows, "any_store_hit_zero"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("Feasible first-buffer baseline rows must record any_store_hit_zero=true.")
    if (~baseline.loc[feasible_rows, "all_terminal_inventory_satisfied"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("Feasible first-buffer baseline rows must keep all_terminal_inventory_satisfied=true.")

    next_checks = review_bundle.tables["s2_buffer_aware_next_check_register.csv"]
    if list(next_checks.columns) != BUFFER_AWARE_NEXT_CHECK_REGISTER_COLUMNS:
        raise ValueError("s2_buffer_aware_next_check_register.csv must match the required column order.")
    if next_checks["check_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_buffer_aware_next_check_register.csv must not contain duplicate check_id values.")
    if len(next_checks) != 9:
        raise ValueError("s2_buffer_aware_next_check_register.csv must contain exactly 9 next-check rows.")
    required_checks = {
        "24h_inventory_min_max_interpretation",
        "initial_inventory_sensitivity",
        "no_initial_stock_diagnostic_gate",
        "one_week_buffer_aware_run_gate",
        "dri_hdri_buffer_size_sensitivity",
        "hot_metal_buffer_size_sensitivity",
        "cold_slab_slab_wip_tonne_grounding",
        "downstream_hsm_activation_gate",
        "s3_energy_cost_emissions_entry_gate",
    }
    if set(next_checks["next_check"].astype(str).str.strip()) != required_checks:
        raise ValueError("s2_buffer_aware_next_check_register.csv does not match the required S2.10c check coverage.")
    if (~next_checks["current_status"].astype(str).str.strip().eq("blocked_pending_review")).any():
        raise ValueError("s2_buffer_aware_next_check_register.csv must keep current_status=blocked_pending_review.")

    return {
        "liquid_steel_first_buffer_aware_baseline_freeze_memo_present": True,
        "inventory_use_interpretation_rows_checked": int(len(interpretation)),
        "first_buffer_aware_baseline_rows_checked": int(len(baseline)),
        "buffer_aware_next_check_rows_checked": int(len(next_checks)),
    }


def validate_s2_buffer_sensitivity_artifacts(review_bundle: GovernanceTableBundle) -> dict[str, Any]:
    if not BUFFER_SENSITIVITY_DIAGNOSTICS_MEMO.exists():
        raise ValueError("STEEL_S2_BUFFER_SENSITIVITY_DIAGNOSTICS.md must exist for S2.10d.")
    memo_text = BUFFER_SENSITIVITY_DIAGNOSTICS_MEMO.read_text(encoding="utf-8").lower()
    for phrase in BUFFER_SENSITIVITY_DIAGNOSTICS_REQUIRED_PHRASES:
        if phrase not in memo_text:
            raise ValueError(
                f"STEEL_S2_BUFFER_SENSITIVITY_DIAGNOSTICS.md is missing required phrase: {phrase}"
            )

    plan = review_bundle.tables["s2_buffer_sensitivity_plan.csv"]
    if list(plan.columns) != BUFFER_SENSITIVITY_PLAN_COLUMNS:
        raise ValueError("s2_buffer_sensitivity_plan.csv must match the required column order.")
    if plan["sensitivity_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_buffer_sensitivity_plan.csv must not contain duplicate sensitivity_id values.")
    if len(plan) != 21:
        raise ValueError("s2_buffer_sensitivity_plan.csv must contain exactly 21 planned sensitivity rows.")
    if (~plan["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_buffer_sensitivity_plan.csv must keep thesis_usability=false for every row.")
    if (~plan["inventory_mode"].astype(str).str.strip().eq("first_buffers")).any():
        raise ValueError("s2_buffer_sensitivity_plan.csv must keep inventory_mode=first_buffers.")
    if (~plan["configuration_id"].astype(str).str.strip().isin(BUFFER_SENSITIVITY_ALLOWED_CONFIGURATION_IDS)).any():
        raise ValueError("s2_buffer_sensitivity_plan.csv contains unsupported configuration_id values.")

    results = review_bundle.tables["s2_buffer_sensitivity_result_summary.csv"]
    if list(results.columns) != BUFFER_SENSITIVITY_RESULT_SUMMARY_COLUMNS:
        raise ValueError("s2_buffer_sensitivity_result_summary.csv must match the required column order.")
    if results["result_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_buffer_sensitivity_result_summary.csv must not contain duplicate result_id values.")
    if len(results) != 21:
        raise ValueError("s2_buffer_sensitivity_result_summary.csv must contain exactly 21 result rows.")
    if (~results["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_buffer_sensitivity_result_summary.csv must keep thesis_usability=false for every row.")
    if (~results["inventory_mode"].astype(str).str.strip().eq("first_buffers")).any():
        raise ValueError("s2_buffer_sensitivity_result_summary.csv must keep inventory_mode=first_buffers.")
    if (~results["shortfall_slack_active"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_buffer_sensitivity_result_summary.csv must keep shortfall_slack_active=false.")
    if (~results["binary_count"].astype(str).str.strip().eq("0")).any():
        raise ValueError("s2_buffer_sensitivity_result_summary.csv must keep binary_count=0.")
    expected_result_ids = set(plan["sensitivity_id"].astype(str).str.strip())
    actual_result_ids = set(results["sensitivity_id"].astype(str).str.strip())
    if actual_result_ids != expected_result_ids:
        missing = sorted(expected_result_ids - actual_result_ids)
        extra = sorted(actual_result_ids - expected_result_ids)
        raise ValueError(f"s2_buffer_sensitivity_result_summary.csv coverage mismatch. missing={missing} extra={extra}")

    return {
        "buffer_sensitivity_diagnostics_memo_present": True,
        "buffer_sensitivity_plan_rows_checked": int(len(plan)),
        "buffer_sensitivity_result_rows_checked": int(len(results)),
    }


def validate_s210e_week_gate_artifacts(review_bundle: GovernanceTableBundle) -> dict[str, Any]:
    if not ZERO_HIT_WEEK_GATE_MEMO.exists():
        raise ValueError("STEEL_S2_ZERO_HIT_ATTRIBUTION_AND_WEEK_GATE.md must exist for S2.10e/S2.10f.")
    memo_text = ZERO_HIT_WEEK_GATE_MEMO.read_text(encoding="utf-8").lower()
    for phrase in ZERO_HIT_WEEK_GATE_REQUIRED_PHRASES:
        if phrase not in memo_text:
            raise ValueError(f"STEEL_S2_ZERO_HIT_ATTRIBUTION_AND_WEEK_GATE.md is missing required phrase: {phrase}")

    zero_hit = review_bundle.tables["s2_zero_hit_attribution_register.csv"]
    if list(zero_hit.columns) != ZERO_HIT_ATTRIBUTION_REGISTER_COLUMNS:
        raise ValueError("s2_zero_hit_attribution_register.csv must match the required column order.")
    if len(zero_hit) != 6:
        raise ValueError("s2_zero_hit_attribution_register.csv must contain exactly six S2.10e attribution rows.")
    if (~zero_hit["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_zero_hit_attribution_register.csv must keep thesis_usability=false.")
    if (~zero_hit["inventory_mode"].astype(str).str.strip().eq("first_buffers")).any():
        raise ValueError("s2_zero_hit_attribution_register.csv must keep inventory_mode=first_buffers.")
    if (~zero_hit["configuration_id"].astype(str).str.strip().isin(BUFFER_SENSITIVITY_ALLOWED_CONFIGURATION_IDS)).any():
        raise ValueError("s2_zero_hit_attribution_register.csv contains unsupported configuration_id values.")

    diagnostic_rows = zero_hit.loc[zero_hit["objective_type"].eq("diagnostic_maximise_min_inventory_margin")]
    if len(diagnostic_rows) != 2:
        raise ValueError("s2_zero_hit_attribution_register.csv must contain two diagnostic objective rows.")
    if (~diagnostic_rows["zero_hit_reduced_vs_default"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("S2.10e diagnostic rows must prove zero_hit_reduced_vs_default=true before weekly opening.")
    if (~diagnostic_rows["benign_gate_result"].astype(str).str.strip().eq("passed")).any():
        raise ValueError("S2.10e diagnostic rows must record benign_gate_result=passed when one-week is opened.")
    if (~diagnostic_rows["one_week_allowed"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("S2.10e diagnostic rows must record one_week_allowed=true when one-week is opened.")

    stress_rows = zero_hit.loc[zero_hit["target_variant"].eq("stress_infeasible_original")]
    if len(stress_rows) != 2:
        raise ValueError("s2_zero_hit_attribution_register.csv must contain two stress safeguard rows.")
    if (~stress_rows["stress_case_preserved_if_applicable"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("S2.10e stress rows must keep stress_case_preserved_if_applicable=true.")
    if (~stress_rows["solve_status"].astype(str).str.strip().str.lower().eq("infeasible")).any():
        raise ValueError("S2.10e stress rows must remain infeasible.")

    weekly_audit = review_bundle.tables["s2_weekly_smoke_target_audit.csv"]
    if list(weekly_audit.columns) != WEEKLY_SMOKE_TARGET_AUDIT_COLUMNS:
        raise ValueError("s2_weekly_smoke_target_audit.csv must match the required column order.")
    if len(weekly_audit) != 2:
        raise ValueError("s2_weekly_smoke_target_audit.csv must contain exactly two weekly feasible_smoke_168h rows.")
    for column, required_value in (
        ("approval_status", "provisional_development_only"),
        ("executable_status", "dev_executable_only"),
        ("thesis_usability", "false"),
        ("reviewer_decision_required", "true"),
        ("codex_may_decide", "false"),
    ):
        if (~weekly_audit[column].astype(str).str.strip().str.lower().eq(required_value)).any():
            raise ValueError(f"s2_weekly_smoke_target_audit.csv must keep {column}={required_value}.")
    if (~weekly_audit["target_variant"].astype(str).str.strip().eq("feasible_smoke_168h")).any():
        raise ValueError("s2_weekly_smoke_target_audit.csv must keep target_variant=feasible_smoke_168h.")

    one_week_summary = review_bundle.tables["s2_one_week_buffer_smoke_summary.csv"]
    if list(one_week_summary.columns) != ONE_WEEK_BUFFER_SMOKE_SUMMARY_COLUMNS:
        raise ValueError("s2_one_week_buffer_smoke_summary.csv must match the required column order.")
    if len(one_week_summary) != 2:
        raise ValueError("s2_one_week_buffer_smoke_summary.csv must contain exactly two one-week feasible smoke rows.")
    if (~one_week_summary["horizon_hours"].astype(str).str.strip().eq("168")).any():
        raise ValueError("s2_one_week_buffer_smoke_summary.csv must keep horizon_hours=168.")
    if (~one_week_summary["target_variant"].astype(str).str.strip().eq("feasible_smoke_168h")).any():
        raise ValueError("s2_one_week_buffer_smoke_summary.csv must keep target_variant=feasible_smoke_168h.")
    if (~one_week_summary["objective_type"].astype(str).str.strip().eq("diagnostic_maximise_min_inventory_margin")).any():
        raise ValueError("s2_one_week_buffer_smoke_summary.csv must record the diagnostic weekly objective explicitly.")
    if (~one_week_summary["solve_status"].astype(str).str.strip().str.lower().eq("optimal")).any():
        raise ValueError("s2_one_week_buffer_smoke_summary.csv must keep both one-week cases optimal.")
    for column in ("shortfall_slack_active", "downstream_active", "thesis_usability", "any_store_hit_zero", "any_store_hit_capacity"):
        if (~one_week_summary[column].astype(str).str.strip().str.lower().eq("false")).any():
            raise ValueError(f"s2_one_week_buffer_smoke_summary.csv must keep {column}=false.")
    if (~one_week_summary["all_terminal_inventory_satisfied"].astype(str).str.strip().str.lower().eq("true")).any():
        raise ValueError("s2_one_week_buffer_smoke_summary.csv must keep all_terminal_inventory_satisfied=true.")

    production_targets = _read_csv(PROVISIONAL_DEV_INPUT_ROOT / "production_targets.csv")
    weekly_targets = production_targets.loc[
        production_targets["target_variant"].astype(str).str.strip().eq("feasible_smoke_168h")
    ].copy()
    if len(weekly_targets) != 2:
        raise ValueError("production_targets.csv must contain exactly two feasible_smoke_168h rows after weekly gate opening.")
    if (~weekly_targets["target_name"].astype(str).str.strip().eq("horizon_total_target_168h_one_week")).any():
        raise ValueError("feasible_smoke_168h rows must use target_name=horizon_total_target_168h_one_week.")
    if (~weekly_targets["approval_status"].astype(str).str.strip().str.lower().eq("provisional_development_only")).any():
        raise ValueError("feasible_smoke_168h rows must remain provisional_development_only.")
    if (~weekly_targets["executable_status"].astype(str).str.strip().str.lower().eq("dev_executable_only")).any():
        raise ValueError("feasible_smoke_168h rows must remain dev_executable_only.")
    if (~weekly_targets["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("feasible_smoke_168h rows must remain thesis_usability=false.")

    target_lookup = {
        (str(row["configuration_id"]).strip(), str(row["target_variant"]).strip()): float(row["value"])
        for row in weekly_targets.to_dict(orient="records")
    }
    for row in weekly_audit.to_dict(orient="records"):
        key = (str(row["configuration_id"]).strip(), str(row["target_variant"]).strip())
        if key not in target_lookup:
            raise ValueError(f"s2_weekly_smoke_target_audit.csv references a missing weekly target row: {key}")
        if abs(float(row["reconciled_target_t"]) - target_lookup[key]) > 1e-6:
            raise ValueError(f"s2_weekly_smoke_target_audit.csv does not match production_targets.csv for {key}.")
        if abs(float(row["target_fraction_of_capacity"]) - 0.85) > 1e-9:
            raise ValueError(f"s2_weekly_smoke_target_audit.csv must keep target_fraction_of_capacity=0.85 for {key}.")
        if not float(row["reconciled_target_t"]) < float(row["max_implied_liquid_steel_t"]):
            raise ValueError(f"s2_weekly_smoke_target_audit.csv must remain capacity-consistent for {key}.")

    if "one-week was opened" not in memo_text and "one week was opened" not in memo_text:
        raise ValueError("STEEL_S2_ZERO_HIT_ATTRIBUTION_AND_WEEK_GATE.md must explicitly record that one-week was opened.")
    if "benign" not in memo_text:
        raise ValueError("STEEL_S2_ZERO_HIT_ATTRIBUTION_AND_WEEK_GATE.md must explicitly record the benign gate evidence.")

    return {
        "zero_hit_week_gate_memo_present": True,
        "zero_hit_attribution_rows_checked": int(len(zero_hit)),
        "weekly_smoke_target_audit_rows_checked": int(len(weekly_audit)),
        "one_week_buffer_smoke_rows_checked": int(len(one_week_summary)),
    }


def validate_s211_material_flow_freeze_artifacts(review_bundle: GovernanceTableBundle) -> dict[str, Any]:
    if not S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT_MEMO.exists():
        raise ValueError("STEEL_S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT.md must exist for S2.11.")
    freeze_text = S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT_MEMO.read_text(encoding="utf-8").lower()
    for phrase in S2_MATERIAL_FLOW_FREEZE_REQUIRED_PHRASES:
        if phrase not in freeze_text:
            raise ValueError(
                f"STEEL_S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT.md is missing required phrase: {phrase}"
            )

    if not S2_CONFIGURATION_ASSET_AND_ASSUMPTION_SUMMARY_MEMO.exists():
        raise ValueError("STEEL_S2_CONFIGURATION_ASSET_AND_ASSUMPTION_SUMMARY.md must exist for S2.11.")
    asset_text = S2_CONFIGURATION_ASSET_AND_ASSUMPTION_SUMMARY_MEMO.read_text(encoding="utf-8").lower()
    for phrase in S2_CONFIGURATION_ASSET_SUMMARY_REQUIRED_PHRASES:
        if phrase not in asset_text:
            raise ValueError(
                f"STEEL_S2_CONFIGURATION_ASSET_AND_ASSUMPTION_SUMMARY.md is missing required phrase: {phrase}"
            )

    artifact_audit = review_bundle.tables["s2_artifact_inventory_and_directory_audit.csv"]
    if list(artifact_audit.columns) != S2_ARTIFACT_INVENTORY_AND_DIRECTORY_AUDIT_COLUMNS:
        raise ValueError("s2_artifact_inventory_and_directory_audit.csv must match the required column order.")
    if artifact_audit["artifact_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_artifact_inventory_and_directory_audit.csv must not contain duplicate artifact_id values.")
    artifact_ids = set(artifact_audit["artifact_id"].astype(str).str.strip())
    if artifact_ids != S211_REQUIRED_ARTIFACT_IDS:
        missing = sorted(S211_REQUIRED_ARTIFACT_IDS - artifact_ids)
        extra = sorted(artifact_ids - S211_REQUIRED_ARTIFACT_IDS)
        raise ValueError(f"s2_artifact_inventory_and_directory_audit.csv coverage mismatch. missing={missing} extra={extra}")
    if (~artifact_audit["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_artifact_inventory_and_directory_audit.csv must keep thesis_usability=false for every row.")
    run_policy_row = artifact_audit.loc[artifact_audit["artifact_id"].eq("GENERATED_SMOKE_RUN_POLICY")].iloc[0]
    if str(run_policy_row["should_be_committed"]).strip().lower() != "false":
        raise ValueError("Generated smoke-run directories must remain uncommitted in the S2.11 artifact audit.")
    if "generated" not in str(run_policy_row["source_or_generated"]).strip().lower():
        raise ValueError("Generated smoke-run directory row must be marked as generated output in the S2.11 artifact audit.")

    asset_matrix = review_bundle.tables["s2_configuration_asset_assumption_matrix.csv"]
    if list(asset_matrix.columns) != S2_CONFIGURATION_ASSET_ASSUMPTION_MATRIX_COLUMNS:
        raise ValueError("s2_configuration_asset_assumption_matrix.csv must match the required column order.")
    if asset_matrix["row_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_configuration_asset_assumption_matrix.csv must not contain duplicate row_id values.")
    asset_ids = set(asset_matrix["asset_id"].astype(str).str.strip())
    if asset_ids != S211_REQUIRED_ASSET_MATRIX_IDS:
        missing = sorted(S211_REQUIRED_ASSET_MATRIX_IDS - asset_ids)
        extra = sorted(asset_ids - S211_REQUIRED_ASSET_MATRIX_IDS)
        raise ValueError(f"s2_configuration_asset_assumption_matrix.csv coverage mismatch. missing={missing} extra={extra}")
    if (~asset_matrix["thesis_usability"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_configuration_asset_assumption_matrix.csv must keep thesis_usability=false for every row.")
    active_first_buffer_rows = asset_matrix.loc[
        asset_matrix["active_in_first_buffer_model"].astype(str).str.strip().str.lower().eq("true")
    ]
    active_first_buffer_ids = set(active_first_buffer_rows["asset_id"].astype(str).str.strip())
    if active_first_buffer_ids != FIRST_BUFFER_ACTIVE_STORE_IDS:
        raise ValueError("s2_configuration_asset_assumption_matrix.csv must limit first-buffer activation to the three approved store IDs.")
    blocked_store_rows = asset_matrix.loc[
        asset_matrix["asset_id"].astype(str).str.strip().isin(
            {"c0_slab_wip_buffer", "c1_slab_wip_buffer", "c0_hot_slab_transfer_buffer", "c1_hot_slab_transfer_buffer"}
        )
    ]
    if (~blocked_store_rows["active_in_first_buffer_model"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("Deferred slab and hot-slab buffers must remain inactive in the S2.11 asset matrix.")

    s2_to_s3_contract = review_bundle.tables["s2_to_s3_input_contract_register.csv"]
    if list(s2_to_s3_contract.columns) != S2_TO_S3_INPUT_CONTRACT_REGISTER_COLUMNS:
        raise ValueError("s2_to_s3_input_contract_register.csv must match the required column order.")
    if s2_to_s3_contract["contract_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s2_to_s3_input_contract_register.csv must not contain duplicate contract_id values.")
    contract_inputs = set(s2_to_s3_contract["input_or_artifact"].astype(str).str.strip())
    if contract_inputs != S211_REQUIRED_CONTRACT_INPUTS:
        missing = sorted(S211_REQUIRED_CONTRACT_INPUTS - contract_inputs)
        extra = sorted(contract_inputs - S211_REQUIRED_CONTRACT_INPUTS)
        raise ValueError(f"s2_to_s3_input_contract_register.csv coverage mismatch. missing={missing} extra={extra}")
    if (~s2_to_s3_contract["thesis_usability_status"].astype(str).str.strip().str.lower().eq("false")).any():
        raise ValueError("s2_to_s3_input_contract_register.csv must keep thesis_usability_status=false for every row.")

    s3_gate_checklist = review_bundle.tables["s3_entry_gate_checklist.csv"]
    if list(s3_gate_checklist.columns) != S3_ENTRY_GATE_CHECKLIST_COLUMNS:
        raise ValueError("s3_entry_gate_checklist.csv must match the required column order.")
    if s3_gate_checklist["gate_id"].astype(str).str.strip().duplicated().any():
        raise ValueError("s3_entry_gate_checklist.csv must not contain duplicate gate_id values.")
    gate_names = set(s3_gate_checklist["gate_name"].astype(str).str.strip())
    if gate_names != S211_REQUIRED_S3_GATES:
        missing = sorted(S211_REQUIRED_S3_GATES - gate_names)
        extra = sorted(gate_names - S211_REQUIRED_S3_GATES)
        raise ValueError(f"s3_entry_gate_checklist.csv coverage mismatch. missing={missing} extra={extra}")
    if not s3_gate_checklist.loc[
        s3_gate_checklist["gate_name"].astype(str).str.strip().eq("S3_scope_limited_to_energy_cost_emissions_first"),
        "pass_fail_or_blocked",
    ].astype(str).str.strip().eq("pass_with_scope_limit").all():
        raise ValueError("s3_entry_gate_checklist.csv must keep the S3 scope gate limited to energy/cost/emissions first.")
    if not s3_gate_checklist.loc[
        s3_gate_checklist["gate_name"].astype(str).str.strip().eq("no_DA_stochastic_mfrr_in_S3_0"),
        "pass_fail_or_blocked",
    ].astype(str).str.strip().eq("pass_with_scope_limit").all():
        raise ValueError("s3_entry_gate_checklist.csv must preserve the no-DA/stochastic/mFRR block for S3.0.")

    return {
        "s2_material_flow_freeze_memo_present": True,
        "s2_configuration_asset_summary_memo_present": True,
        "s2_artifact_inventory_rows_checked": int(len(artifact_audit)),
        "s2_configuration_asset_assumption_rows_checked": int(len(asset_matrix)),
        "s2_to_s3_contract_rows_checked": int(len(s2_to_s3_contract)),
        "s3_entry_gate_rows_checked": int(len(s3_gate_checklist)),
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
    numerical_review_packet_payload = validate_s2_numerical_review_packets(review_bundle.root)
    minimal_numerical_policy_payload = validate_s2_minimal_numerical_policy_bundle(review_bundle)
    provisional_dev_input_payload = validate_s2_provisional_dev_input(load_s2_provisional_dev_input(PROVISIONAL_DEV_INPUT_ROOT))
    liquid_steel_smoke_builder_payload = validate_s2_liquid_steel_smoke_builder_artifacts()
    liquid_steel_smoke_runner_payload = validate_s2_liquid_steel_smoke_runner_artifacts()
    liquid_steel_smoke_baseline_payload = validate_s2_liquid_steel_smoke_baseline_artifacts(review_bundle)
    first_buffer_inventory_payload = validate_s2_first_buffer_inventory_activation_artifacts(review_bundle)
    first_buffer_aware_baseline_payload = validate_s2_first_buffer_aware_baseline_artifacts(review_bundle)
    buffer_sensitivity_payload = validate_s2_buffer_sensitivity_artifacts(review_bundle)
    zero_hit_week_gate_payload = validate_s210e_week_gate_artifacts(review_bundle)
    s211_freeze_payload = validate_s211_material_flow_freeze_artifacts(review_bundle)

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
    payload.update(numerical_review_packet_payload)
    payload.update(minimal_numerical_policy_payload)
    payload.update(provisional_dev_input_payload)
    payload.update(liquid_steel_smoke_builder_payload)
    payload.update(liquid_steel_smoke_runner_payload)
    payload.update(liquid_steel_smoke_baseline_payload)
    payload.update(first_buffer_inventory_payload)
    payload.update(first_buffer_aware_baseline_payload)
    payload.update(buffer_sensitivity_payload)
    payload.update(zero_hit_week_gate_payload)
    payload.update(s211_freeze_payload)
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
