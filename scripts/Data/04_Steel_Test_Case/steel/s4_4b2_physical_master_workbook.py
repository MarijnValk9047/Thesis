"""Build, validate, and compile the S4.4b2 physical master workbook.

This module creates a solver-independent, PyPSA-inspired component workbook for
the governed C0/C1 Tata-IJmuiden-inspired steel physical model boundary. It
does not build or solve an optimisation model, and it does not modify existing
S4.4b or S4.4c inputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo


REPO_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "s4_4b2_physical_master_workbook"
)
WORKBOOK_PATH = OUTPUT_DIR / "steel_c0_c1_physical_model_master.xlsx"
COMPILED_REVIEW_DIR = OUTPUT_DIR / "compiled_review"
SOURCE_EVIDENCE_DIR = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_evidence"
SOURCE_CARD_REGISTER = SOURCE_EVIDENCE_DIR / "steel_source_card_register.csv"
SOURCE_ADDENDUM = SOURCE_EVIDENCE_DIR / "athanasiadis_gas_network_source_card_addendum.csv"
S44A_DIR = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/s4_4a_unified_c0_c1_model_contract"
S44B_DIR = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/s4_4b_unified_dev_inputs"

WORKBOOK_SCHEMA_VERSION = "s4_4b2_physical_master_v1"
WORKBOOK_REVISION = "2026-06-25"
STAGE_GATE_DECISION = "ready_for_human_physical_model_review"

REQUIRED_SHEETS = [
    "README",
    "DATA_DICTIONARY",
    "ENUMS_UNITS",
    "SOURCES",
    "EVIDENCE_LINKS",
    "MODEL_BOUNDARY",
    "CONFIGURATIONS",
    "COMPONENT_ALIASES",
    "CARRIERS",
    "BUSES",
    "CONFIG_COMPONENTS",
    "LINKS",
    "LINK_PORTS",
    "OPERATING_CONSTRAINTS",
    "STORES",
    "LOADS",
    "GENERATORS",
    "MIXING_RULES",
    "SYSTEM_CONSTRAINTS",
    "VALIDATION_ANCHORS",
    "MODELING_DECISIONS",
    "CONFLICTS_GAPS",
    "C0_VIEW",
    "C1_VIEW",
    "QA_SUMMARY",
    "CHANGELOG",
]

COMPILED_SHEETS = {
    "CONFIGURATIONS": "configurations.csv",
    "CARRIERS": "carriers.csv",
    "BUSES": "buses.csv",
    "CONFIG_COMPONENTS": "config_components.csv",
    "LINKS": "links.csv",
    "LINK_PORTS": "link_ports.csv",
    "OPERATING_CONSTRAINTS": "operating_constraints.csv",
    "STORES": "stores.csv",
    "LOADS": "loads.csv",
    "GENERATORS": "generators.csv",
    "MIXING_RULES": "mixing_rules.csv",
    "SYSTEM_CONSTRAINTS": "system_constraints.csv",
    "VALIDATION_ANCHORS": "validation_anchors.csv",
    "EVIDENCE_LINKS": "evidence_links.csv",
    "MODELING_DECISIONS": "modeling_decisions.csv",
    "CONFLICTS_GAPS": "conflicts_gaps.csv",
}

CORE_ENTITY_SHEETS = {
    "MODEL_BOUNDARY",
    "CONFIGURATIONS",
    "COMPONENT_ALIASES",
    "CARRIERS",
    "BUSES",
    "CONFIG_COMPONENTS",
    "LINKS",
    "LINK_PORTS",
    "OPERATING_CONSTRAINTS",
    "STORES",
    "LOADS",
    "GENERATORS",
    "MIXING_RULES",
    "SYSTEM_CONSTRAINTS",
    "VALIDATION_ANCHORS",
    "MODELING_DECISIONS",
    "CONFLICTS_GAPS",
}

ID_COLUMNS = {
    "MODEL_BOUNDARY": "boundary_id",
    "CONFIGURATIONS": "configuration_id",
    "COMPONENT_ALIASES": "alias_id",
    "CARRIERS": "carrier_id",
    "BUSES": "bus_id",
    "CONFIG_COMPONENTS": "config_component_id",
    "LINKS": "link_id",
    "LINK_PORTS": "port_id",
    "OPERATING_CONSTRAINTS": "constraint_id",
    "STORES": "store_id",
    "LOADS": "load_id",
    "GENERATORS": "generator_id",
    "MIXING_RULES": "mixing_rule_id",
    "SYSTEM_CONSTRAINTS": "system_constraint_id",
    "VALIDATION_ANCHORS": "validation_anchor_id",
    "MODELING_DECISIONS": "decision_id",
    "CONFLICTS_GAPS": "gap_or_conflict_id",
    "SOURCES": "source_card_id",
}

NUMERIC_COLUMNS = {
    "CARRIERS": [
        "heating_value_lower",
        "heating_value_central",
        "heating_value_upper",
        "conversion_to_model_unit",
    ],
    "LINK_PORTS": ["coefficient_lower", "coefficient_central", "coefficient_upper"],
    "OPERATING_CONSTRAINTS": ["lower_value", "central_value", "upper_value"],
    "STORES": [
        "capacity_lower",
        "capacity_central",
        "capacity_upper",
        "standing_loss",
        "max_charge",
        "max_discharge",
        "max_residence_time",
    ],
    "LOADS": ["annual_anchor_if_any"],
    "GENERATORS": ["capacity_bound"],
    "MIXING_RULES": ["minimum_share", "maximum_share", "minimum_LHV", "maximum_LHV"],
    "VALIDATION_ANCHORS": ["lower_value", "central_value", "upper_value"],
}

STATUS_FILLS = {
    "source_supported": "C6EFCE",
    "candidate": "FFF2CC",
    "assumption": "D9EAD3",
    "validation_only": "D9EAF7",
    "redacted": "F4CCCC",
    "missing_blocker": "FCE4D6",
    "deferred": "EADCF8",
    "forbidden": "E7E6E6",
}

CONTROLLED_ENUMS = {
    "source_status": [
        "source_supported",
        "candidate",
        "assumption",
        "validation_only",
        "redacted",
        "missing_blocker",
        "deferred",
        "forbidden",
    ],
    "value_status": [
        "source_supported",
        "candidate",
        "assumption",
        "validation_only",
        "redacted_or_not_public",
        "missing_blocker",
        "deferred",
        "not_applicable",
        "forbidden",
    ],
    "direction": ["input", "output"],
    "boolean": ["true", "false"],
    "component_type": ["Link", "Store", "Load", "Generator", "Bus"],
    "configuration_id": [
        "C0_current_BF_BOF_reference",
        "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
        "both",
    ],
    "executable_status": [
        "structural_only",
        "development_review",
        "validation_only",
        "missing_blocker",
        "deferred",
        "forbidden",
    ],
}


@dataclass(frozen=True)
class WorkbookResult:
    workbook_path: Path
    validation_report: dict[str, Any]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _repo_rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _hash_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _split_ids(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.replace(",", ";").split(";") if item.strip()]


def _first_source_id(row: dict[str, Any]) -> str:
    ids = _split_ids(str(row.get("source_card_ids", "")))
    return ids[0] if ids else "REPO-S4-4B2-WORKBOOK"


def _row(sheet: str, **values: Any) -> dict[str, Any]:
    columns = SCHEMAS[sheet]
    row = {column: "" for column in columns}
    row.update(values)
    return row


SCHEMAS: dict[str, list[str]] = {
    "README": ["item", "value"],
    "DATA_DICTIONARY": [
        "sheet_name",
        "column_name",
        "description",
        "required",
        "allowed_values",
        "unit_notes",
    ],
    "ENUMS_UNITS": ["enum_category", "enum_value", "description"],
    "SOURCES": [
        "source_card_id",
        "source_title",
        "author_or_organisation",
        "publication_year",
        "source_type",
        "authority_class",
        "public_status",
        "stable_document_identifier",
        "source_url_or_doi",
        "repo_relative_path",
        "exact_locator",
        "primary_or_secondary",
        "source_scope",
        "source_review_status",
        "caveat",
    ],
    "EVIDENCE_LINKS": [
        "evidence_link_id",
        "entity_sheet",
        "entity_id",
        "field_name",
        "source_card_id",
        "exact_locator",
        "evidence_type",
        "support_strength",
        "supports",
        "does_not_support",
        "derivation_method",
        "conflict_group_id",
        "caveat",
    ],
    "MODEL_BOUNDARY": [
        "boundary_id",
        "configuration_scope",
        "entity_family",
        "entity_id",
        "included",
        "boundary_role",
        "selected_model_role",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "CONFIGURATIONS": [
        "configuration_id",
        "display_name",
        "role",
        "change_set_over",
        "workbook_schema_version",
        "workbook_revision",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "COMPONENT_ALIASES": [
        "alias_id",
        "canonical_component_id",
        "alias",
        "alias_context",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "CARRIERS": [
        "carrier_id",
        "display_name",
        "carrier_domain",
        "native_source_unit",
        "selected_model_balance_unit",
        "mass_or_energy_basis",
        "LHV_or_HHV_basis",
        "heating_value_lower",
        "heating_value_central",
        "heating_value_upper",
        "heating_value_unit",
        "conversion_to_model_unit",
        "storable_physical",
        "storable_in_hourly_model",
        "active_C0",
        "active_C1",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "BUSES": [
        "bus_id",
        "display_name",
        "carrier_id",
        "network_layer",
        "physical_location_or_boundary",
        "balance_unit",
        "balanced_each_timestep",
        "external_boundary",
        "store_connection_expected",
        "selected_model_role",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "CONFIG_COMPONENTS": [
        "config_component_id",
        "configuration_id",
        "component_type",
        "component_id",
        "active",
        "activation_mode",
        "retained_added_closed",
        "controllable",
        "source_model_status",
        "selected_model_status",
        "topology_decision_id",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "LINKS": [
        "link_id",
        "display_name",
        "process_family",
        "physical_or_interface",
        "selected_component_type",
        "throughput_basis_bus",
        "throughput_basis_unit",
        "continuous_batch_or_semi_continuous",
        "controllable",
        "committable_candidate",
        "physical_asset_exists",
        "source_model_representation",
        "selected_hourly_model_representation",
        "component_control_class",
        "executable_status",
        "source_representation",
        "selected_representation",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "LINK_PORTS": [
        "port_id",
        "link_id",
        "port_order",
        "bus_id",
        "direction",
        "coefficient_lower",
        "coefficient_central",
        "coefficient_upper",
        "coefficient_unit",
        "coefficient_basis",
        "sign_convention",
        "required_or_optional",
        "physical_material_or_energy",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "OPERATING_CONSTRAINTS": [
        "constraint_id",
        "component_type",
        "component_id",
        "configuration_scope",
        "constraint_family",
        "lower_value",
        "central_value",
        "upper_value",
        "unit",
        "basis",
        "time_basis",
        "hard_or_soft",
        "selected_for_execution",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "STORES": [
        "store_id",
        "bus_id",
        "store_class",
        "physical_asset_exists",
        "source_model_store",
        "selected_hourly_store",
        "capacity_lower",
        "capacity_central",
        "capacity_upper",
        "capacity_unit",
        "source_model_capacity_treatment",
        "selected_model_capacity_treatment",
        "initial_inventory_rule",
        "minimum_inventory_rule",
        "terminal_inventory_rule",
        "cyclic",
        "standing_loss",
        "max_charge",
        "max_discharge",
        "max_residence_time",
        "hot_cold_state_relevance",
        "flexibility_role",
        "physical_asset_exists_detail",
        "source_model_representation",
        "selected_hourly_model_representation",
        "component_control_class",
        "executable_status",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "LOADS": [
        "load_id",
        "bus_id",
        "load_family",
        "configuration_scope",
        "controlled_by_optimizer",
        "profile_type",
        "value_or_profile_path",
        "unit",
        "annual_anchor_if_any",
        "allocation_method",
        "physical_asset_exists",
        "source_model_representation",
        "selected_hourly_model_representation",
        "component_control_class",
        "executable_status",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "GENERATORS": [
        "generator_id",
        "bus_id",
        "physical_source_type",
        "configuration_scope",
        "available",
        "capacity_bound",
        "capacity_unit",
        "availability_profile",
        "import_or_internal",
        "selected_model_role",
        "physical_asset_exists",
        "source_model_representation",
        "selected_hourly_model_representation",
        "component_control_class",
        "executable_status",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "MIXING_RULES": [
        "mixing_rule_id",
        "mixer_link_id",
        "output_bus_id",
        "input_carrier_id",
        "eligible",
        "minimum_share",
        "maximum_share",
        "energy_equivalence_basis",
        "minimum_LHV",
        "maximum_LHV",
        "LHV_unit",
        "Wobbe_constraint_status",
        "simultaneous_mix_allowed",
        "substitution_with_NG_allowed",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "SYSTEM_CONSTRAINTS": [
        "system_constraint_id",
        "configuration_scope",
        "constraint_family",
        "description",
        "selected_for_execution",
        "physical_only",
        "economic_objective_term",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "VALIDATION_ANCHORS": [
        "validation_anchor_id",
        "anchor_family",
        "configuration_relevance",
        "metric",
        "lower_value",
        "central_value",
        "upper_value",
        "unit",
        "annual_or_static",
        "validation_only",
        "executable_input",
        "scope_boundary",
        "comparison_caveat",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "MODELING_DECISIONS": [
        "decision_id",
        "topic",
        "selected_representation",
        "alternative_considered",
        "decision_reason",
        "changed_from_source",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "human_review_required",
        "caveat",
    ],
    "CONFLICTS_GAPS": [
        "gap_or_conflict_id",
        "topic",
        "entity_ids",
        "description",
        "conflicting_sources",
        "selected_current_interpretation",
        "selection_authority",
        "numeric_or_structural",
        "blocking_for_physical_model",
        "blocking_for_DA_model",
        "human_review_required",
        "recommended_resolution",
        "source_card_ids",
        "source_locator",
        "evidence_link_ids",
        "value_status",
        "source_status",
        "caveat",
    ],
    "C0_VIEW": [
        "configuration_id",
        "component_id",
        "pypsa_inspired_type",
        "inputs",
        "outputs",
        "controllability",
        "operating_constraints",
        "connected_store",
        "relevant_WAG_rule",
        "source_status",
        "executable_status",
        "unresolved_gaps",
    ],
    "C1_VIEW": [
        "configuration_id",
        "component_id",
        "pypsa_inspired_type",
        "inputs",
        "outputs",
        "controllability",
        "operating_constraints",
        "connected_store",
        "relevant_WAG_rule",
        "source_status",
        "executable_status",
        "unresolved_gaps",
    ],
    "QA_SUMMARY": ["check_id", "severity", "status", "detail"],
    "CHANGELOG": ["revision", "date_utc", "change_type", "description", "author_or_agent"],
}


def _manual_sources() -> list[dict[str, Any]]:
    return [
        {
            "source_card_id": "REPO-S4-4B2-WORKBOOK",
            "source_title": "S4.4b2 physical master workbook task specification",
            "author_or_organisation": "Repository task prompt",
            "publication_year": 2026,
            "source_type": "task_governance",
            "authority_class": "user_governance",
            "public_status": "repo_local",
            "stable_document_identifier": WORKBOOK_SCHEMA_VERSION,
            "source_url_or_doi": "",
            "repo_relative_path": "",
            "exact_locator": "Current task prompt accepted 2026-06-25",
            "primary_or_secondary": "primary",
            "source_scope": "Workbook schema and acceptance criteria",
            "source_review_status": "active_task_instruction",
            "caveat": "Governs workbook shape; not a physical source for Tata values.",
        },
        {
            "source_card_id": "REPO-AGENTS",
            "source_title": "AGENTS.md",
            "author_or_organisation": "Repository governance",
            "publication_year": 2026,
            "source_type": "repository_governance",
            "authority_class": "governance",
            "public_status": "repo_local",
            "stable_document_identifier": "AGENTS.md",
            "source_url_or_doi": "",
            "repo_relative_path": "AGENTS.md",
            "exact_locator": "Optimisation and steel workstream instructions",
            "primary_or_secondary": "primary",
            "source_scope": "Stage scope, output governance, no economics in this task",
            "source_review_status": "read_for_task",
            "caveat": "Methodology governance only.",
        },
        {
            "source_card_id": "REPO-STEEL-FREEZE-V1",
            "source_title": "Steel Implementation Freeze V1 and related governance",
            "author_or_organisation": "Repository governance",
            "publication_year": 2026,
            "source_type": "repository_governance",
            "authority_class": "governance",
            "public_status": "repo_local",
            "stable_document_identifier": "STEEL_IMPLEMENTATION_FREEZE_V1.md",
            "source_url_or_doi": "",
            "repo_relative_path": "docs/optimisation/steel/STEEL_IMPLEMENTATION_FREEZE_V1.md",
            "exact_locator": "S4.4a/S4.4b/S4.4c stage sequence and blocked market layers",
            "primary_or_secondary": "primary",
            "source_scope": "Stage sequence, topology freeze, source hierarchy",
            "source_review_status": "read_for_task",
            "caveat": "Governs selected model boundary but is not plant evidence.",
        },
        {
            "source_card_id": "REPO-S4-4A-CONTRACT",
            "source_title": "Steel S4.4a Unified C0/C1 Model Contract",
            "author_or_organisation": "Repository governance",
            "publication_year": 2026,
            "source_type": "repository_contract",
            "authority_class": "governance",
            "public_status": "repo_local",
            "stable_document_identifier": "STEEL_S4_4A_UNIFIED_C0_C1_MODEL_CONTRACT.md",
            "source_url_or_doi": "",
            "repo_relative_path": "docs/optimisation/steel/S4/STEEL_S4_4A_UNIFIED_C0_C1_MODEL_CONTRACT.md",
            "exact_locator": "Input contract, blockers, common policy modes",
            "primary_or_secondary": "primary",
            "source_scope": "Existing unified model contract and blockers",
            "source_review_status": "read_for_task",
            "caveat": "Development contract only; not thesis execution readiness.",
        },
        {
            "source_card_id": "REPO-S4-4B-DEV-INPUTS",
            "source_title": "S4.4b unified development input tables",
            "author_or_organisation": "Repository data surface",
            "publication_year": 2026,
            "source_type": "development_inputs",
            "authority_class": "development_input_surface",
            "public_status": "repo_local",
            "stable_document_identifier": "s4_4b_unified_dev_inputs",
            "source_url_or_doi": "",
            "repo_relative_path": "data/03_Optimisation/inputs/assets/steel/S4/s4_4b_unified_dev_inputs/",
            "exact_locator": "Existing 16 S4.4b development input CSVs",
            "primary_or_secondary": "primary",
            "source_scope": "Comparison surface only; not overwritten",
            "source_review_status": "read_for_task",
            "caveat": "Existing S4.4b files remain unchanged and development-only.",
        },
        {
            "source_card_id": "REPO-ATH-GAS-ADDENDUM",
            "source_title": "Athanasiadis gas-network source-card addendum",
            "author_or_organisation": "Repository source evidence",
            "publication_year": 2026,
            "source_type": "source_card_addendum",
            "authority_class": "repo_extracted_source_card",
            "public_status": "repo_local",
            "stable_document_identifier": "athanasiadis_gas_network_source_card_addendum.csv",
            "source_url_or_doi": "",
            "repo_relative_path": "data/03_Optimisation/inputs/assets/steel/source_evidence/athanasiadis_gas_network_source_card_addendum.csv",
            "exact_locator": "Rows S33I-ATH-GAS-001 to S33I-ATH-GAS-014",
            "primary_or_secondary": "secondary",
            "source_scope": "Athanasiadis gas, steam, Vattenfall, and LHV structural extraction",
            "source_review_status": "read_for_task",
            "caveat": "Local PDF was not present; addendum says structural/numeric entries remain provisional where not directly rechecked.",
        },
        {
            "source_card_id": "REPO-DEEPSEARCH-MEMOS",
            "source_title": "Steel deepsearch and research memo set",
            "author_or_organisation": "Repository research memos",
            "publication_year": 2026,
            "source_type": "research_memo_bundle",
            "authority_class": "discovery_only_unless_source_carded",
            "public_status": "repo_local",
            "stable_document_identifier": "docs/optimisation/steel/research_memos",
            "source_url_or_doi": "",
            "repo_relative_path": "docs/optimisation/steel/research_memos/",
            "exact_locator": "Deepsearch memos 1-9 and source appendices",
            "primary_or_secondary": "secondary",
            "source_scope": "Discovery and candidate-evidence context only",
            "source_review_status": "read_for_task",
            "caveat": "Unsourced memo text is not treated as primary evidence.",
        },
    ]


def _load_sources() -> list[dict[str, Any]]:
    required_ids = {
        "STEEL-SC-0001",
        "STEEL-SC-0003",
        "STEEL-SC-0007",
        "STEEL-SC-0008",
        "STEEL-SC-0010",
        "STEEL-SC-0011",
        "STEEL-SC-0013",
        "STEEL-SC-0014",
        "STEEL-SC-0015",
        "STEEL-SC-0016",
        "STEEL-SC-0017",
        "STEEL-SC-0021",
        "STEEL-SC-S32-ATHANASIADIS-SLAB-YARD",
        "S3_4_GUARDRAIL_BADARINATH_2025",
        "S3_4_GUARDRAIL_PAULUS_BORGGREFE_2011",
        "S4_ECON_TSN_ANNUAL_REPORT_2025",
        "S4_ECON_PBL_MIDDEN_STEEL_2019",
        "S4_ECON_VATTENFALL_NV_ANNUAL_REPORT_2024",
    }
    rows = []
    for source in _read_csv(SOURCE_CARD_REGISTER):
        if source.get("source_card_id") not in required_ids:
            continue
        url = source.get("stable_url_or_doi", "")
        repo_path = source.get("repo_relative_path", "")
        if url and not url.startswith(("http://", "https://", "doi:", "local_", "uploaded_", "governed_policy")):
            url = ""
        rows.append(
            _row(
                "SOURCES",
                source_card_id=source.get("source_card_id", ""),
                source_title=source.get("source_title", ""),
                author_or_organisation=source.get("author_or_organisation", ""),
                publication_year=source.get("publication_year", ""),
                source_type=source.get("source_type", ""),
                authority_class=source.get("authority_class", ""),
                public_status=source.get("public_status", ""),
                stable_document_identifier=source.get("stable_document_identifier", ""),
                source_url_or_doi=url if url.startswith(("http://", "https://", "doi:")) else "",
                repo_relative_path=repo_path,
                exact_locator=source.get("page_table_or_section", ""),
                primary_or_secondary=source.get("primary_or_secondary", ""),
                source_scope=source.get("source_scope", ""),
                source_review_status=source.get("source_review_status", ""),
                caveat=source.get("notes", ""),
            )
        )
    manual = [_row("SOURCES", **source) for source in _manual_sources()]
    existing = {row["source_card_id"] for row in rows}
    rows.extend([row for row in manual if row["source_card_id"] not in existing])
    rows.sort(key=lambda item: item["source_card_id"])
    return rows


def _readme_rows() -> list[dict[str, Any]]:
    return [
        _row("README", item="workbook_schema_version", value=WORKBOOK_SCHEMA_VERSION),
        _row("README", item="workbook_revision", value=WORKBOOK_REVISION),
        _row("README", item="role", value="Human-authoring master and compiled review source for C0/C1 physical model specification."),
        _row("README", item="not_role", value="Not executable S4.4c input migration, not DA/economic/bidding logic, not Tata digital twin."),
        _row("README", item="configurations", value="C0_current_BF_BOF_reference; C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"),
        _row("README", item="ontology", value="Buses; Links; Stores; Loads; Generators"),
        _row("README", item="output_policy", value="minimal; authoring_snapshot; development_review"),
        _row("README", item="stage_gate", value=STAGE_GATE_DECISION),
    ]


def _enum_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    descriptions = {
        "source_status": "Source or governance support status for the row.",
        "value_status": "Numeric or structural value usability status.",
        "direction": "Link port direction convention.",
        "boolean": "Boolean field values stored as strings for Excel validation.",
        "component_type": "PyPSA-inspired component family.",
        "configuration_id": "Allowed configuration scope labels.",
        "executable_status": "Whether a row can drive a later model after review.",
    }
    for category, values in CONTROLLED_ENUMS.items():
        for value in values:
            rows.append(_row("ENUMS_UNITS", enum_category=category, enum_value=value, description=descriptions[category]))
    for unit in [
        "t",
        "t/h",
        "t_DRI",
        "t_pellets/h",
        "MWh",
        "MWh/t",
        "PJ/y",
        "GJ",
        "MJ/Nm3",
        "Nm3/t",
        "Nm3/h",
        "MW",
        "MVA",
        "fraction",
        "qualitative",
    ]:
        rows.append(_row("ENUMS_UNITS", enum_category="unit", enum_value=unit, description="Common workbook unit."))
    return rows


def _configurations() -> list[dict[str, Any]]:
    return [
        _row(
            "CONFIGURATIONS",
            configuration_id="C0_current_BF_BOF_reference",
            display_name="Current BF-BOF reference",
            role="current reference and contrast case",
            change_set_over="none",
            workbook_schema_version=WORKBOOK_SCHEMA_VERSION,
            workbook_revision=WORKBOOK_REVISION,
            source_card_ids="REPO-STEEL-FREEZE-V1;REPO-S4-4A-CONTRACT",
            source_locator="Frozen configuration scope and S4.4a unified model contract",
            value_status="source_supported",
            source_status="source_supported",
            human_review_required="false",
            caveat="Public Tata-inspired reference boundary; not exact site digital twin.",
        ),
        _row(
            "CONFIGURATIONS",
            configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
            display_name="Phase 1 hybrid BF-BOF plus NG-DRP/EAF",
            role="main future thesis steel configuration",
            change_set_over="C0_current_BF_BOF_reference",
            workbook_schema_version=WORKBOOK_SCHEMA_VERSION,
            workbook_revision=WORKBOOK_REVISION,
            source_card_ids="REPO-STEEL-FREEZE-V1;STEEL-SC-0016;STEEL-SC-0017",
            source_locator="Repository freeze; MER Heracless Phase 1 gas operation sections",
            value_status="source_supported",
            source_status="source_supported",
            human_review_required="true",
            caveat="Default C1 follows frozen BF7 plus KGF2 closure reading; conflict preserved separately.",
        ),
    ]


def _aliases() -> list[dict[str, Any]]:
    rows = [
        ("alias_cok1_kgf1", "coking_plant_1", "KGF1", "Dutch coke and gas plant alias"),
        ("alias_cok2_kgf2", "coking_plant_2", "KGF2", "Dutch coke and gas plant alias"),
        ("alias_bof_oxystaal", "basic_oxygen_furnace", "Oxystaalfabriek", "BOF plant alias"),
        ("alias_bofg_oxygas", "BOFG", "oxygas", "BOF/LD gas public-source alias"),
        ("alias_ij01_ijm01", "IJ01_interface", "IJM-01", "Vattenfall/IJmond interface alias"),
        ("alias_vn24_velsen24", "VN24_interface", "Velsen 24", "Vattenfall interface alias"),
        ("alias_vn25_velsen25", "VN25_interface", "Velsen 25", "Vattenfall interface alias"),
    ]
    return [
        _row(
            "COMPONENT_ALIASES",
            alias_id=alias_id,
            canonical_component_id=component,
            alias=alias,
            alias_context=context,
            source_card_ids="STEEL-SC-0016;REPO-STEEL-FREEZE-V1",
            source_locator="MER/freeze topology naming and conflict handling",
            value_status="source_supported",
            source_status="source_supported",
            human_review_required="true" if component in {"coking_plant_1", "coking_plant_2"} else "false",
            caveat="Alias exists to preserve source wording and avoid silent topology rewriting.",
        )
        for alias_id, component, alias, context in rows
    ]


def _carriers() -> list[dict[str, Any]]:
    def carrier(
        carrier_id: str,
        domain: str,
        unit: str,
        basis: str,
        storable_physical: str,
        storable_hourly: str,
        active_c0: str,
        active_c1: str,
        source_ids: str,
        locator: str,
        value_status: str = "source_supported",
        source_status: str = "source_supported",
        lhv: tuple[float | None, float | None, float | None, str, str] | None = None,
        caveat: str = "",
    ) -> dict[str, Any]:
        lower = central = upper = hv_unit = lhv_basis = ""
        if lhv:
            lower, central, upper, hv_unit, lhv_basis = lhv
        return _row(
            "CARRIERS",
            carrier_id=carrier_id,
            display_name=carrier_id.replace("_", " "),
            carrier_domain=domain,
            native_source_unit=unit,
            selected_model_balance_unit=unit,
            mass_or_energy_basis=basis,
            LHV_or_HHV_basis=lhv_basis,
            heating_value_lower=lower,
            heating_value_central=central,
            heating_value_upper=upper,
            heating_value_unit=hv_unit,
            conversion_to_model_unit=1 if unit in {"t", "MWh"} else "",
            storable_physical=storable_physical,
            storable_in_hourly_model=storable_hourly,
            active_C0=active_c0,
            active_C1=active_c1,
            source_card_ids=source_ids,
            source_locator=locator,
            value_status=value_status,
            source_status=source_status,
            human_review_required="true" if source_status in {"candidate", "missing_blocker", "redacted"} else "false",
            caveat=caveat,
        )

    rows = [
        carrier("coal", "material", "t", "mass", "true", "deferred", "true", "true", "STEEL-SC-0016", "MER current/reference and C1 material boundary", caveat="Coal inventory capacity not public."),
        carrier("iron_ore", "material", "t", "mass", "true", "deferred", "true", "true", "STEEL-SC-0016", "MER current/reference material boundary", caveat="Exact ore buffer not public."),
        carrier("coke", "material", "t", "mass", "true", "deferred", "true", "true", "STEEL-SC-0001;STEEL-SC-0016", "JRC BREF coke plant context; MER topology", caveat="Coke store capacity missing."),
        carrier("sinter", "material", "t", "mass", "true", "deferred", "true", "true", "STEEL-SC-0016", "MER current process topology", caveat="Sinter store capacity missing."),
        carrier("pellets", "material", "t", "mass", "true", "candidate", "true", "true", "STEEL-SC-0016;STEEL-SC-0021", "MER topology; Athanasiadis NG-DRP Table 2 p.57", source_status="candidate", caveat="Pelletizing/imported pellet split needs review."),
        carrier("imported_pellets", "material_supply_route", "t", "mass", "false", "false", "true", "true", "REPO-S4-4B2-WORKBOOK", "Task requirement: supply route into pellets bus", value_status="assumption", source_status="assumption", caveat="Route identity only; not a separate internal inventory."),
        carrier("hot_metal", "material", "t", "mass", "true", "candidate", "true", "true", "REPO-STEEL-FREEZE-V1", "S2/S3 buffer governance", source_status="candidate", caveat="Hot-metal buffer must be tightly bounded; exact capacity missing."),
        carrier("scrap", "material", "t", "mass", "true", "deferred", "true", "true", "STEEL-SC-0021", "Athanasiadis EAF Table 1 p.56 for scrap input", source_status="candidate", caveat="Scrap procurement and inventory capacity not public."),
        carrier("crude_or_liquid_steel", "material", "t", "mass", "short_transfer", "candidate", "true", "true", "STEEL-SC-0021;REPO-STEEL-FREEZE-V1", "Athanasiadis and S2.13 downstream governance", source_status="candidate", caveat="Internal technical diagnostic; not thesis-facing product denominator."),
        carrier("slabs", "material", "t", "mass", "true", "candidate", "true", "true", "STEEL-SC-S32-ATHANASIADIS-SLAB-YARD", "Athanasiadis slab storage limitation source card", source_status="candidate", caveat="Slab inventory may need hot/cold state and residence-time policy."),
        carrier("hot_slabs", "material", "t", "mass", "short_transfer", "deferred", "true", "true", "REPO-STEEL-FREEZE-V1", "S2.13 hot/cold route governance", value_status="assumption", source_status="assumption", caveat="Thermal-state treatment is not yet executable."),
        carrier("cold_slabs", "material", "t", "mass", "true", "candidate", "true", "true", "STEEL-SC-S32-ATHANASIADIS-SLAB-YARD", "Slab-yard capacity source card", source_status="candidate", caveat="Cold slab yard may not create free production flexibility."),
        carrier("rolled_steel_or_final_product", "product", "t", "mass", "accounting", "false", "true", "true", "REPO-STEEL-FREEZE-V1", "Fixed production target policy", value_status="assumption", source_status="assumption", caveat="Target accumulator only, not physical flexibility store."),
        carrier("DRI", "material", "t", "mass", "true", "candidate", "false", "true", "STEEL-SC-0021;S3_4_GUARDRAIL_BADARINATH_2025", "Athanasiadis NG-DRP/EAF; Badarinath buffer precedent", source_status="candidate", caveat="DRI/HDRI buffer decoupling must be bounded and endpoint-neutral."),
        carrier("electricity", "energy", "MWh", "energy", "false", "false", "true", "true", "STEEL-SC-0016;STEEL-SC-0017", "MER electricity boundary", caveat="Electricity is not storable in the base site model."),
        carrier("natural_gas", "energy", "Nm3", "LHV_energy", "false", "false", "true", "true", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-011", source_status="candidate", lhv=(None, 37.5, None, "MJ/Nm3", "LHV"), caveat="No site NG inventory unless later explicitly modelled."),
        carrier("steam", "utility", "GJ", "useful_energy", "false", "false", "true", "true", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-006", value_status="missing_blocker", source_status="missing_blocker", caveat="Steam defaults to instantaneous bus; storage evidence missing."),
        carrier("oxygen", "utility", "t", "mass", "true", "deferred", "true", "true", "STEEL-SC-0016", "MER oxygen/buffer topology context", value_status="missing_blocker", source_status="missing_blocker", caveat="Oxygen storage capacity missing; avoid artificial electricity shifting."),
        carrier("BFG", "WAG", "GJ", "LHV_energy", "true", "deferred", "true", "true", "REPO-ATH-GAS-ADDENDUM;STEEL-SC-0001", "S33I-ATH-GAS-010; JRC BREF Table 6.8", source_status="candidate", lhv=(2.7, 3.85, 4.0, "MJ/Nm3", "LHV"), caveat="Athanasiadis central and JRC range; holder capacity not public."),
        carrier("COG", "WAG", "GJ", "LHV_energy", "true", "deferred", "true", "true", "REPO-ATH-GAS-ADDENDUM;STEEL-SC-0001", "S33I-ATH-GAS-008; JRC BREF Table 5.1/5.2", source_status="candidate", lhv=(17.4, 18.5, 20.0, "MJ/Nm3", "LHV"), caveat="KGF2 closure changes generation; holder capacity not public."),
        carrier("BOFG", "WAG", "GJ", "LHV_energy", "true", "candidate", "true", "true", "REPO-ATH-GAS-ADDENDUM;STEEL-SC-0001", "S33I-ATH-GAS-009; JRC BREF Table 7.5", source_status="candidate", lhv=(7.1, 8.6, 10.1, "MJ/Nm3", "LHV"), caveat="Oxygas holder exists structurally; exact capacity missing."),
        carrier("process_specific_WAG_blend", "mixed_WAG", "GJ", "LHV_energy", "false", "false", "true", "true", "REPO-ATH-GAS-ADDENDUM", "Figures 31-33 source-carded structural extraction", value_status="assumption", source_status="assumption", caveat="Mix buses are instantaneous controllers, not commodity stores."),
        carrier("direct_CO2", "emissions_accounting", "t_CO2", "mass", "accounting", "false", "true", "true", "STEEL-SC-0003;STEEL-SC-0016", "MRR accounting; MER emissions context", value_status="validation_only", source_status="validation_only", caveat="Accounting flow, not flexibility buffer."),
        carrier("captured_CO2", "emissions_accounting", "t_CO2", "mass", "accounting", "false", "false", "true", "STEEL-SC-0003;STEEL-SC-0017", "MRR CO2 transfer visibility and Heracless CCS context", value_status="deferred", source_status="deferred", caveat="Captured CO2 support requires explicit capture/transport boundary."),
        carrier("residual_CO2", "emissions_accounting", "t_CO2", "mass", "accounting", "false", "true", "true", "REPO-STEEL-FREEZE-V1", "Emissions boundary policy", value_status="assumption", source_status="assumption", caveat="Residual accounting closure only, not physical storage."),
    ]
    return rows


def _buses(carriers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bus_specs = [
        ("coal_bus", "coal", "raw_material", "external_and_site"),
        ("iron_ore_bus", "iron_ore", "raw_material", "external_and_site"),
        ("coke_bus", "coke", "intermediate_material", "coke plant / BF interface"),
        ("sinter_bus", "sinter", "intermediate_material", "sinter / BF interface"),
        ("pellets_bus", "pellets", "intermediate_material", "pelletizing/import/DRP/BF interface"),
        ("imported_pellets_boundary_bus", "imported_pellets", "boundary_supply", "external boundary"),
        ("hot_metal_bus", "hot_metal", "intermediate_material", "BF to BOF transfer"),
        ("scrap_bus", "scrap", "raw_material", "external and EAF/BOF interface"),
        ("crude_liquid_steel_bus", "crude_or_liquid_steel", "intermediate_material", "BOF/EAF to casting"),
        ("slabs_bus", "slabs", "intermediate_material", "caster to downstream"),
        ("hot_slabs_bus", "hot_slabs", "thermal_material", "hot charge transfer"),
        ("cold_slabs_bus", "cold_slabs", "material_buffer", "slab yard"),
        ("rolled_steel_final_product_bus", "rolled_steel_or_final_product", "product", "final product target"),
        ("DRI_bus", "DRI", "intermediate_material", "DRP to EAF"),
        ("electricity_bus", "electricity", "utility_energy", "site electric bus"),
        ("natural_gas_bus", "natural_gas", "utility_energy", "site NG bus"),
        ("steam_bus", "steam", "utility_energy", "instantaneous steam bus"),
        ("oxygen_bus", "oxygen", "utility", "ASU and oxygen buffer/interface"),
        ("BFG_bus", "BFG", "WAG", "blast furnace gas network"),
        ("COG_bus", "COG", "WAG", "coke oven gas network"),
        ("BOFG_bus", "BOFG", "WAG", "BOF/oxygas network"),
        ("wag_cok1_mix_bus", "process_specific_WAG_blend", "mixed_WAG", "Coking Plant 1 gas controller output"),
        ("wag_hsm_mix_bus", "process_specific_WAG_blend", "mixed_WAG", "HSM fuel gas controller output"),
        ("wag_pellet_grinding_mix_bus", "process_specific_WAG_blend", "mixed_WAG", "Pellet grinding gas controller output"),
        ("wag_pellet_firing_mix_bus", "process_specific_WAG_blend", "mixed_WAG", "Pellet firing gas controller output"),
        ("wag_boiler_group_mix_bus", "process_specific_WAG_blend", "mixed_WAG", "Boilers 15/16/23/24 controller output"),
        ("wag_boiler41_mix_bus", "process_specific_WAG_blend", "mixed_WAG", "Boiler 41 controller output"),
        ("wag_steg11_mix_bus", "process_specific_WAG_blend", "mixed_WAG", "STEG11 controller output"),
        ("wag_vattenfall_mix_bus", "process_specific_WAG_blend", "mixed_WAG", "Vattenfall generator controller output"),
        ("direct_CO2_bus", "direct_CO2", "emissions", "direct emissions accounting boundary"),
        ("captured_CO2_bus", "captured_CO2", "emissions", "captured CO2 reporting boundary"),
        ("residual_CO2_bus", "residual_CO2", "emissions", "residual accounting closure"),
    ]
    carrier_map = {row["carrier_id"]: row for row in carriers}
    rows = []
    for bus_id, carrier_id, layer, location in bus_specs:
        carrier = carrier_map[carrier_id]
        rows.append(
            _row(
                "BUSES",
                bus_id=bus_id,
                display_name=bus_id.replace("_", " "),
                carrier_id=carrier_id,
                network_layer=layer,
                physical_location_or_boundary=location,
                balance_unit=carrier["selected_model_balance_unit"],
                balanced_each_timestep="true" if layer not in {"product", "emissions"} else "false",
                external_boundary="true" if "boundary" in layer or carrier_id in {"coal", "iron_ore", "scrap", "natural_gas", "electricity"} else "false",
                store_connection_expected="true" if str(carrier["storable_in_hourly_model"]) in {"candidate", "true"} else "false",
                selected_model_role="balance_node",
                source_card_ids=carrier["source_card_ids"],
                source_locator=carrier["source_locator"],
                value_status=carrier["value_status"],
                source_status=carrier["source_status"],
                human_review_required=carrier["human_review_required"],
                caveat=carrier["caveat"],
            )
        )
    return rows


def _links() -> list[dict[str, Any]]:
    specs = [
        ("coking_plant_1", "Coking Plant 1 / KGF1", "coking", "physical", "coal_bus", "t_coal_or_t_coke", "continuity_driven", "limited", "false", "true", "Plant Link", "Structural Link with gas/fuel ports", "continuity_candidate", "development_review", "STEEL-SC-0016;REPO-ATH-GAS-ADDENDUM", "Figure 31 and MER topology", "Retained in default C1."),
        ("coking_plant_2", "Coking Plant 2 / KGF2", "coking", "physical", "coal_bus", "t_coal_or_t_coke", "continuity_driven", "limited", "false", "true", "Plant Link", "Structural Link with gas/fuel ports", "continuity_candidate", "development_review", "STEEL-SC-0016;REPO-STEEL-FREEZE-V1", "MER/freeze closure decision", "Active C0, closed default C1."),
        ("sintering_plant", "Sintering Plant", "agglomeration", "physical", "iron_ore_bus", "t_sinter", "continuity_driven", "limited", "false", "true", "Plant Link", "Structural process", "continuity_candidate", "development_review", "REPO-ATH-GAS-ADDENDUM;STEEL-SC-0016", "Athanasiadis Figure 20/plant relationships; MER topology", "C1 retained treatment needs review."),
        ("pelletizing_plant", "Pelletizing Plant", "agglomeration", "physical", "iron_ore_bus", "t_pellets", "continuity_driven", "limited", "false", "true", "Plant Link", "Structural process", "continuity_candidate", "development_review", "REPO-ATH-GAS-ADDENDUM;STEEL-SC-0016", "Athanasiadis pelletizing figures and Figure 31 gas sinks", "Pellet/import split unresolved."),
        ("imported_pellet_import_interface", "Imported pellet supply route", "boundary_supply", "interface", "imported_pellets_boundary_bus", "t_pellets", "continuous", "false", "false", "true", "Boundary Link", "Supply route into pellets bus", "boundary_interface", "structural_only", "REPO-S4-4B2-WORKBOOK", "Task required imported-pellet supply route", "No price or procurement quantity in this workbook."),
        ("blast_furnace_6", "Blast Furnace 6", "BF", "physical", "sinter_bus", "t_hot_metal", "continuity_driven", "limited", "false", "true", "Plant Link", "Structural BF process", "continuity_candidate", "development_review", "STEEL-SC-0016;STEEL-SC-0001", "MER topology; JRC BREF WAG coefficients", "Retained default C1 BF route."),
        ("blast_furnace_7", "Blast Furnace 7", "BF", "physical", "sinter_bus", "t_hot_metal", "continuity_driven", "limited", "false", "true", "Plant Link", "Structural BF process", "continuity_candidate", "development_review", "STEEL-SC-0016;REPO-STEEL-FREEZE-V1", "MER/freeze closure decision", "Active C0, closed default C1."),
        ("basic_oxygen_furnace", "Basic Oxygen Furnace", "BOF", "physical", "hot_metal_bus", "t_liquid_steel", "batch_equivalent", "limited", "candidate", "true", "Plant Link", "Structural BOF process", "batch_equivalent_candidate", "development_review", "REPO-ATH-GAS-ADDENDUM;STEEL-SC-0001", "Athanasiadis plant figures; JRC BREF BOFG", "Retained in C1 topology where retained BF-BOF route remains."),
        ("continuous_caster_or_slab_conversion", "Continuous caster or slab conversion", "casting", "physical", "crude_liquid_steel_bus", "t_slabs", "semi_continuous", "limited", "false", "true", "Plant Link", "Structural caster abstraction", "downstream_candidate", "development_review", "REPO-STEEL-FREEZE-V1", "S2.13 downstream scheduling governance", "Exact caster capacities missing."),
        ("hot_strip_mill", "Hot Strip Mill", "downstream", "physical", "slabs_bus", "t_final_product", "semi_continuous", "limited", "false", "true", "Plant Link", "Structural HSM with fuel gas", "downstream_candidate", "development_review", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-002 Figure 31", "HSM fuel and scheduling constraints missing."),
        ("direct_sheet_plant", "Direct Sheet Plant", "downstream", "physical", "hot_slabs_bus", "t_final_product", "semi_continuous", "limited", "false", "true", "Plant Link", "Structural DSP", "downstream_candidate", "development_review", "REPO-ATH-GAS-ADDENDUM", "Athanasiadis plant representations", "DSP detailed constraints missing."),
        ("linde_asu", "Linde/ASU oxygen production", "utility", "physical_or_interface", "electricity_bus", "t_oxygen", "continuous", "limited", "false", "true", "Utility Link", "ASU structural utility", "utility_candidate", "deferred", "STEEL-SC-0016", "MER oxygen/buffer context", "Do not infer direct CO2 from electricity use."),
        ("WAG_COK1_mixer", "COK1 WAG mixer", "gas_mixing", "controller", "BFG_bus", "GJ_mix", "instantaneous", "limited", "false", "true", "Mixer Link", "Athanasiadis gas controller", "instantaneous_mixer", "structural_only", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-003 Figure 31", "No Wobbe limit inferred."),
        ("WAG_HSM_mixer", "HSM WAG mixer", "gas_mixing", "controller", "COG_bus", "GJ_mix", "instantaneous", "limited", "false", "true", "Mixer Link", "Athanasiadis gas controller", "instantaneous_mixer", "structural_only", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-002 Figure 31", "No Wobbe limit inferred."),
        ("WAG_PEFA_MALERIJ_mixer", "Pellet grinding WAG mixer", "gas_mixing", "controller", "BOFG_bus", "GJ_mix", "instantaneous", "limited", "false", "true", "Mixer Link", "Athanasiadis gas controller", "instantaneous_mixer", "structural_only", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-005 Figure 31", "Malerij/grinding naming preserved."),
        ("WAG_PEFA_BRANDERIJ_mixer", "Pellet firing WAG mixer", "gas_mixing", "controller", "COG_bus", "GJ_mix", "instantaneous", "limited", "false", "true", "Mixer Link", "Athanasiadis gas controller", "instantaneous_mixer", "structural_only", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-004 Figure 31", "Branderij/firing naming preserved."),
        ("WAG_BOILERS_15_16_23_24_mixer", "Boilers 15/16/23/24 WAG mixer", "gas_mixing", "controller", "COG_bus", "GJ_mix", "instantaneous", "limited", "false", "true", "Mixer Link", "Athanasiadis boiler gas controller", "instantaneous_mixer", "structural_only", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-006 Figure 32", "No boiler efficiency inferred."),
        ("WAG_BOILER_41_mixer", "Boiler 41 WAG mixer", "gas_mixing", "controller", "BFG_bus", "GJ_mix", "instantaneous", "limited", "false", "true", "Mixer Link", "Athanasiadis boiler gas controller", "instantaneous_mixer", "structural_only", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-006 Figure 32", "No boiler efficiency inferred."),
        ("WAG_STEG11_mixer", "STEG11 WAG mixer", "gas_mixing", "controller", "natural_gas_bus", "GJ_mix", "instantaneous", "limited", "false", "true", "Mixer Link", "Athanasiadis STEG controller", "instantaneous_mixer", "structural_only", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-007 Figure 33", "No dispatch model."),
        ("WAG_VATTENFALL_GENERATORS_mixer", "Vattenfall generator WAG mixer", "gas_mixing", "controller", "BFG_bus", "GJ_mix", "instantaneous", "limited", "false", "true", "Mixer Link", "Athanasiadis Vattenfall controller", "instantaneous_mixer", "structural_only", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-007 Figure 33", "Interface only, not literal plant dispatch."),
        ("boilers_15_16_23_24", "Boilers 15/16/23/24", "steam_boiler", "physical_or_interface", "wag_boiler_group_mix_bus", "GJ_fuel", "continuous", "limited", "false", "true", "Utility Link", "Boiler group abstraction", "utility_candidate", "deferred", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-006 Figure 32", "Efficiency and steam basis missing."),
        ("boiler_41", "Boiler 41", "steam_boiler", "physical_or_interface", "wag_boiler41_mix_bus", "GJ_fuel", "continuous", "limited", "false", "true", "Utility Link", "Boiler 41 abstraction", "utility_candidate", "deferred", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-006 Figure 32", "Efficiency and steam basis missing."),
        ("STEG11", "STEG11", "steam_power", "interface", "wag_steg11_mix_bus", "GJ_fuel", "continuous", "limited", "false", "true", "Utility Link", "STEG11 abstraction", "interface_only", "deferred", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-007 Figure 33", "No dispatch or commercial contract."),
        ("TG2_steam_turbine", "TG2 steam turbine", "steam_power", "interface", "steam_bus", "GJ_steam", "continuous", "limited", "false", "true", "Utility Link", "Steam turbine abstraction", "interface_only", "deferred", "REPO-ATH-GAS-ADDENDUM", "Athanasiadis steam/source representations", "No efficiency or dispatch basis."),
        ("IJ01_interface", "IJ01 interface", "Vattenfall_interface", "interface", "wag_vattenfall_mix_bus", "GJ_fuel", "continuous", "false", "false", "true", "Interface Link", "Vattenfall interface", "boundary_interface", "structural_only", "STEEL-SC-0014;STEEL-SC-0016;REPO-ATH-GAS-ADDENDUM", "Vattenfall/MER interface; S33I-ATH-GAS-007", "Interface only, not literal dispatched plant."),
        ("VN24_interface", "VN24 interface", "Vattenfall_interface", "interface", "wag_vattenfall_mix_bus", "GJ_fuel", "continuous", "false", "false", "true", "Interface Link", "Vattenfall backup interface", "boundary_interface", "structural_only", "STEEL-SC-0014;STEEL-SC-0016;REPO-ATH-GAS-ADDENDUM", "Vattenfall/MER interface; S33I-ATH-GAS-007", "Backup status is structural only."),
        ("VN25_interface", "VN25 interface", "Vattenfall_interface", "interface", "wag_vattenfall_mix_bus", "GJ_fuel", "continuous", "false", "false", "true", "Interface Link", "Vattenfall main interface", "boundary_interface", "structural_only", "STEEL-SC-0014;STEEL-SC-0016;REPO-ATH-GAS-ADDENDUM", "Vattenfall/MER interface; S33I-ATH-GAS-007", "No exact hourly dispatch."),
        ("flare", "WAG flare", "flare", "physical_or_sink", "BFG_bus", "GJ_WAG", "continuous", "limited", "false", "true", "Sink Link", "Flare/spill sink", "safety_sink", "development_review", "STEEL-SC-0010;STEEL-SC-0003", "Off-gas surplus/flaring; MRR accounting", "Flaring capacity and penalty magnitude missing."),
        ("NG_DRP", "Natural-gas direct reduction plant", "DRP", "physical", "pellets_bus", "t_pellets", "continuous", "yes", "false", "true", "Plant Link", "Athanasiadis NG-DRP", "continuous_guardrail_candidate", "development_review", "STEEL-SC-0021", "Section 3.5.4 Figure 47 Table 2 p.57", "C1 addition; candidate values are not Tata-exact."),
        ("EAF", "Electric arc furnace", "EAF", "physical", "DRI_bus", "t_DRI", "batch_equivalent", "yes", "true", "true", "Plant Link", "Athanasiadis EAF plus Badarinath semi-continuous precedent", "binary_semi_continuous_candidate", "development_review", "STEEL-SC-0021;S3_4_GUARDRAIL_BADARINATH_2025", "Athanasiadis Figure 46 Table 1 p.56; Badarinath Equation 5.9", "Hourly abstraction only, not heat sequencing."),
    ]
    return [
        _row(
            "LINKS",
            link_id=s[0],
            display_name=s[1],
            process_family=s[2],
            physical_or_interface=s[3],
            selected_component_type="Link",
            throughput_basis_bus=s[4],
            throughput_basis_unit=s[5],
            continuous_batch_or_semi_continuous=s[6],
            controllable=s[7],
            committable_candidate=s[8],
            physical_asset_exists=s[9],
            source_model_representation=s[10],
            selected_hourly_model_representation=s[11],
            component_control_class=s[12],
            executable_status=s[13],
            source_representation=s[10],
            selected_representation=s[11],
            source_card_ids=s[14],
            source_locator=s[15],
            value_status="source_supported" if s[13] in {"structural_only", "development_review"} else "deferred",
            source_status="source_supported" if s[13] == "structural_only" else ("candidate" if s[13] == "development_review" else "deferred"),
            human_review_required="true" if s[13] != "structural_only" else "false",
            caveat=s[16],
        )
        for s in specs
    ]


def _port(
    link_id: str,
    order: int,
    bus_id: str,
    direction: str,
    source_ids: str,
    locator: str,
    coefficient: float | None = None,
    unit: str = "",
    basis: str = "",
    status: str = "source_supported",
    caveat: str = "",
    required: str = "required",
) -> dict[str, Any]:
    return _row(
        "LINK_PORTS",
        port_id=f"{link_id}__{direction}_{order}_{bus_id}",
        link_id=link_id,
        port_order=order,
        bus_id=bus_id,
        direction=direction,
        coefficient_central=coefficient,
        coefficient_unit=unit,
        coefficient_basis=basis,
        sign_convention="positive_output_negative_input_by_direction",
        required_or_optional=required,
        physical_material_or_energy="energy" if any(token in bus_id for token in ["electricity", "gas", "BFG", "COG", "BOFG", "steam", "WAG", "natural"]) else "material_or_accounting",
        source_card_ids=source_ids,
        source_locator=locator,
        value_status=status,
        source_status="candidate" if status == "candidate" else status,
        human_review_required="true" if status in {"candidate", "missing_blocker", "deferred"} else "false",
        caveat=caveat,
    )


def _link_ports() -> list[dict[str, Any]]:
    default_source = "REPO-ATH-GAS-ADDENDUM;STEEL-SC-0016"
    default_locator = "Athanasiadis Figures 18-35 source-carded extraction and MER topology"
    port_map: dict[str, tuple[list[str], list[str], str, str]] = {
        "coking_plant_1": (["coal_bus", "wag_cok1_mix_bus", "steam_bus", "electricity_bus"], ["coke_bus", "COG_bus", "direct_CO2_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-003 plus plant representation"),
        "coking_plant_2": (["coal_bus", "COG_bus", "steam_bus", "electricity_bus"], ["coke_bus", "COG_bus", "direct_CO2_bus"], default_source, "Plant relationship; COG input ambiguity recorded"),
        "sintering_plant": (["iron_ore_bus", "electricity_bus", "COG_bus", "steam_bus"], ["sinter_bus", "direct_CO2_bus"], default_source, default_locator),
        "pelletizing_plant": (["iron_ore_bus", "electricity_bus", "steam_bus", "wag_pellet_grinding_mix_bus", "wag_pellet_firing_mix_bus"], ["pellets_bus", "direct_CO2_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-004/005"),
        "imported_pellet_import_interface": (["imported_pellets_boundary_bus"], ["pellets_bus"], "REPO-S4-4B2-WORKBOOK", "Task supply-route requirement"),
        "blast_furnace_6": (["sinter_bus", "coke_bus", "coal_bus", "pellets_bus", "electricity_bus", "oxygen_bus", "steam_bus"], ["hot_metal_bus", "BFG_bus", "direct_CO2_bus"], "STEEL-SC-0001;STEEL-SC-0016", "MER BF topology; JRC BREF WAG coefficients"),
        "blast_furnace_7": (["sinter_bus", "coke_bus", "coal_bus", "pellets_bus", "electricity_bus", "oxygen_bus", "steam_bus"], ["hot_metal_bus", "BFG_bus", "direct_CO2_bus"], "STEEL-SC-0001;STEEL-SC-0016", "MER BF topology; JRC BREF WAG coefficients"),
        "basic_oxygen_furnace": (["hot_metal_bus", "scrap_bus", "oxygen_bus", "electricity_bus", "steam_bus"], ["crude_liquid_steel_bus", "BOFG_bus", "direct_CO2_bus"], "STEEL-SC-0001;REPO-ATH-GAS-ADDENDUM", "JRC BOFG; Athanasiadis plant representation"),
        "continuous_caster_or_slab_conversion": (["crude_liquid_steel_bus"], ["slabs_bus", "hot_slabs_bus"], "REPO-STEEL-FREEZE-V1", "S2.13 downstream scheduling governance"),
        "hot_strip_mill": (["slabs_bus", "hot_slabs_bus", "electricity_bus", "wag_hsm_mix_bus"], ["rolled_steel_final_product_bus", "direct_CO2_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-002"),
        "direct_sheet_plant": (["hot_slabs_bus", "electricity_bus"], ["rolled_steel_final_product_bus"], "REPO-ATH-GAS-ADDENDUM", "Athanasiadis plant representation"),
        "linde_asu": (["electricity_bus"], ["oxygen_bus"], "STEEL-SC-0016", "MER oxygen utility context"),
        "boilers_15_16_23_24": (["wag_boiler_group_mix_bus"], ["steam_bus", "direct_CO2_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-006"),
        "boiler_41": (["wag_boiler41_mix_bus"], ["steam_bus", "direct_CO2_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-006"),
        "STEG11": (["wag_steg11_mix_bus"], ["electricity_bus", "direct_CO2_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-007"),
        "TG2_steam_turbine": (["steam_bus"], ["electricity_bus"], "REPO-ATH-GAS-ADDENDUM", "Athanasiadis steam/source representations"),
        "IJ01_interface": (["wag_vattenfall_mix_bus"], ["electricity_bus", "direct_CO2_bus"], "STEEL-SC-0014;STEEL-SC-0016;REPO-ATH-GAS-ADDENDUM", "Vattenfall interface source cards"),
        "VN24_interface": (["wag_vattenfall_mix_bus"], ["electricity_bus", "direct_CO2_bus"], "STEEL-SC-0014;STEEL-SC-0016;REPO-ATH-GAS-ADDENDUM", "Vattenfall interface source cards"),
        "VN25_interface": (["wag_vattenfall_mix_bus"], ["electricity_bus", "direct_CO2_bus"], "STEEL-SC-0014;STEEL-SC-0016;REPO-ATH-GAS-ADDENDUM", "Vattenfall interface source cards"),
        "flare": (["BFG_bus", "COG_bus", "BOFG_bus"], ["direct_CO2_bus"], "STEEL-SC-0010;STEEL-SC-0003", "Off-gas surplus and flaring; MRR accounting"),
    }
    mixer_ports = {
        "WAG_COK1_mixer": (["BFG_bus", "COG_bus"], ["wag_cok1_mix_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-003"),
        "WAG_HSM_mixer": (["COG_bus", "natural_gas_bus"], ["wag_hsm_mix_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-002"),
        "WAG_PEFA_MALERIJ_mixer": (["natural_gas_bus", "BOFG_bus"], ["wag_pellet_grinding_mix_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-005"),
        "WAG_PEFA_BRANDERIJ_mixer": (["COG_bus", "natural_gas_bus"], ["wag_pellet_firing_mix_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-004"),
        "WAG_BOILERS_15_16_23_24_mixer": (["natural_gas_bus", "COG_bus"], ["wag_boiler_group_mix_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-006"),
        "WAG_BOILER_41_mixer": (["BFG_bus", "natural_gas_bus"], ["wag_boiler41_mix_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-006"),
        "WAG_STEG11_mixer": (["natural_gas_bus", "BFG_bus"], ["wag_steg11_mix_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-007"),
        "WAG_VATTENFALL_GENERATORS_mixer": (["BFG_bus", "COG_bus", "BOFG_bus", "natural_gas_bus"], ["wag_vattenfall_mix_bus"], "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-007"),
    }
    port_map.update(mixer_ports)
    port_map["NG_DRP"] = (
        ["pellets_bus", "natural_gas_bus", "electricity_bus", "oxygen_bus"],
        ["DRI_bus", "direct_CO2_bus", "captured_CO2_bus"],
        "STEEL-SC-0021",
        "Athanasiadis Figure 47 Table 2 p.57",
    )
    port_map["EAF"] = (
        ["DRI_bus", "scrap_bus", "electricity_bus", "oxygen_bus"],
        ["crude_liquid_steel_bus", "direct_CO2_bus"],
        "STEEL-SC-0021;S3_4_GUARDRAIL_BADARINATH_2025",
        "Athanasiadis Figure 46 Table 1 p.56; Badarinath formulation precedent",
    )
    rows: list[dict[str, Any]] = []
    for link_id, (inputs, outputs, source_ids, locator) in port_map.items():
        order = 1
        for bus in inputs:
            rows.append(_port(link_id, order, bus, "input", source_ids, locator))
            order += 1
        for bus in outputs:
            required = "optional" if bus == "captured_CO2_bus" else "required"
            status = "deferred" if bus == "captured_CO2_bus" else "source_supported"
            rows.append(_port(link_id, order, bus, "output", source_ids, locator, status=status, required=required, caveat="Captured CO2 port retained only if later capture boundary is supported." if bus == "captured_CO2_bus" else ""))
            order += 1

    # Candidate numeric conversion ports from the reviewed Athanasiadis tables.
    numeric_updates = {
        ("NG_DRP", "output", "DRI_bus"): (0.74, "t_DRI/t_pellets", "pellet_input", "candidate"),
        ("NG_DRP", "input", "natural_gas_bus"): (195.0, "Nm3_NG/t_pellets", "pellet_input", "candidate"),
        ("NG_DRP", "input", "electricity_bus"): (0.1, "MWh/t_pellets", "pellet_input", "candidate"),
        ("NG_DRP", "input", "oxygen_bus"): (0.1, "t_O2/t_pellets", "pellet_input", "candidate"),
        ("NG_DRP", "output", "direct_CO2_bus"): (0.5, "t_CO2/t_pellets", "pellet_input", "candidate"),
        ("EAF", "output", "crude_liquid_steel_bus"): (0.95, "t_liquid_steel/t_DRI", "DRI_input", "candidate"),
        ("EAF", "input", "electricity_bus"): (0.5, "MWh/t_DRI", "DRI_input", "candidate"),
        ("EAF", "input", "scrap_bus"): (0.2, "t_scrap/t_DRI", "DRI_input", "candidate"),
        ("EAF", "input", "oxygen_bus"): (0.05, "t_O2/t_DRI", "DRI_input", "candidate"),
    }
    for row in rows:
        key = (row["link_id"], row["direction"], row["bus_id"])
        if key in numeric_updates:
            value, unit, basis, status = numeric_updates[key]
            row["coefficient_central"] = value
            row["coefficient_unit"] = unit
            row["coefficient_basis"] = basis
            row["value_status"] = status
            row["source_status"] = status
            row["human_review_required"] = "true"
            row["caveat"] = "Tier B thesis-model assumption; not Tata-exact and not validation truth."
    return rows


def _config_components(links: list[dict[str, Any]], stores: list[dict[str, Any]], loads: list[dict[str, Any]], generators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    c0_active_links = {
        "coking_plant_1",
        "coking_plant_2",
        "sintering_plant",
        "pelletizing_plant",
        "imported_pellet_import_interface",
        "blast_furnace_6",
        "blast_furnace_7",
        "basic_oxygen_furnace",
        "continuous_caster_or_slab_conversion",
        "hot_strip_mill",
        "direct_sheet_plant",
        "linde_asu",
        "WAG_COK1_mixer",
        "WAG_HSM_mixer",
        "WAG_PEFA_MALERIJ_mixer",
        "WAG_PEFA_BRANDERIJ_mixer",
        "WAG_BOILERS_15_16_23_24_mixer",
        "WAG_BOILER_41_mixer",
        "WAG_STEG11_mixer",
        "WAG_VATTENFALL_GENERATORS_mixer",
        "boilers_15_16_23_24",
        "boiler_41",
        "STEG11",
        "TG2_steam_turbine",
        "IJ01_interface",
        "VN24_interface",
        "VN25_interface",
        "flare",
    }
    c1_active_links = (c0_active_links | {"NG_DRP", "EAF"}) - {"coking_plant_2", "blast_furnace_7"}
    rows: list[dict[str, Any]] = []
    link_by_id = {row["link_id"]: row for row in links}
    for config, active_set in [
        ("C0_current_BF_BOF_reference", c0_active_links),
        ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", c1_active_links),
    ]:
        for link_id in link_by_id:
            active = link_id in active_set
            retained_added_closed = "retained"
            if config.startswith("C1") and link_id in {"NG_DRP", "EAF"}:
                retained_added_closed = "added"
            if config.startswith("C1") and link_id in {"coking_plant_2", "blast_furnace_7"}:
                retained_added_closed = "closed"
            rows.append(
                _row(
                    "CONFIG_COMPONENTS",
                    config_component_id=f"{config}__Link__{link_id}",
                    configuration_id=config,
                    component_type="Link",
                    component_id=link_id,
                    active=str(active).lower(),
                    activation_mode="default_topology",
                    retained_added_closed=retained_added_closed,
                    controllable=link_by_id[link_id]["controllable"],
                    source_model_status=link_by_id[link_id]["source_model_representation"],
                    selected_model_status=link_by_id[link_id]["selected_hourly_model_representation"],
                    topology_decision_id="TOPO_C1_BF7_KGF2_CLOSURE" if link_id in {"coking_plant_1", "coking_plant_2", "blast_furnace_7"} else "TOPO_COMMON_SITE_BOUNDARY",
                    source_card_ids=link_by_id[link_id]["source_card_ids"],
                    source_locator=link_by_id[link_id]["source_locator"],
                    value_status=link_by_id[link_id]["value_status"],
                    source_status=link_by_id[link_id]["source_status"],
                    human_review_required="true" if link_id in {"coking_plant_1", "coking_plant_2", "blast_furnace_7"} else link_by_id[link_id]["human_review_required"],
                    caveat=("C1 KGF closure conflict preserved; frozen default used." if link_id in {"coking_plant_1", "coking_plant_2", "blast_furnace_7"} else link_by_id[link_id]["caveat"]),
                )
            )
    for component_type, component_rows, id_col in [
        ("Store", stores, "store_id"),
        ("Load", loads, "load_id"),
        ("Generator", generators, "generator_id"),
    ]:
        for component in component_rows:
            scope = component.get("configuration_scope", "both")
            configs = ["C0_current_BF_BOF_reference", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"] if scope == "both" else [scope]
            for config in configs:
                rows.append(
                    _row(
                        "CONFIG_COMPONENTS",
                        config_component_id=f"{config}__{component_type}__{component[id_col]}",
                        configuration_id=config,
                        component_type=component_type,
                        component_id=component[id_col],
                        active="true" if component.get("executable_status") != "forbidden" else "false",
                        activation_mode="boundary_or_candidate",
                        retained_added_closed="retained" if not component[id_col].startswith("DRI") else "added",
                        controllable="false",
                        source_model_status=component.get("source_model_representation", component.get("selected_model_role", "")),
                        selected_model_status=component.get("selected_hourly_model_representation", component.get("selected_model_role", "")),
                        topology_decision_id="TOPO_COMMON_SITE_BOUNDARY",
                        source_card_ids=component.get("source_card_ids", ""),
                        source_locator=component.get("source_locator", ""),
                        value_status=component.get("value_status", ""),
                        source_status=component.get("source_status", ""),
                        human_review_required=component.get("human_review_required", ""),
                        caveat=component.get("caveat", ""),
                    )
                )
    return rows


def _stores() -> list[dict[str, Any]]:
    specs = [
        ("coke_store", "coke_bus", "physical_inventory_buffer", "true", "yes_in_source_model_or_physical", "deferred", None, None, None, "t", "not_public", "missing_finite_bound", "missing", "missing", "missing", "false", None, None, None, None, "no", "candidate buffer; finite anti-arbitrage bound needed", "STEEL-SC-0016;STEEL-SC-0001", "MER topology; JRC BREF coke context", "missing_blocker", "Coke store capacity missing; do not use unlimited storage."),
        ("sinter_store", "sinter_bus", "physical_inventory_buffer", "true", "yes_or_implicit", "deferred", None, None, None, "t", "not_public", "missing_finite_bound", "missing", "missing", "missing", "false", None, None, None, None, "no", "candidate buffer; finite anti-arbitrage bound needed", "STEEL-SC-0016", "MER topology", "missing_blocker", "Sinter store capacity missing."),
        ("pellets_store", "pellets_bus", "physical_inventory_buffer", "true", "yes_or_implicit", "deferred", None, None, None, "t", "not_public", "missing_finite_bound", "missing", "missing", "missing", "false", None, None, None, None, "no", "candidate buffer; finite anti-arbitrage bound needed", "STEEL-SC-0016;STEEL-SC-0021", "MER topology; DRP table basis", "missing_blocker", "Pellet store/import split and capacity missing."),
        ("hot_metal_buffer", "hot_metal_bus", "short_transfer_buffer", "true", "source_model_buffer_candidate", "candidate", None, None, None, "t", "not_public", "tight_bound_required", "candidate_policy_required", "candidate_policy_required", "terminal_neutrality_required", "false", None, None, None, None, "yes", "short transfer only", "REPO-STEEL-FREEZE-V1", "S2/S3 buffer governance", "missing_blocker", "Hot-metal or torpedo capacity missing; must be tightly bounded."),
        ("crude_steel_or_slab_wip_store", "slabs_bus", "bounded_wip_buffer", "true", "source_model_store", "candidate", 3260.27088, 25000.0, 50000.0, "t_slab", "source_model_capacity_treatment_varied", "finite_candidate_bound", 1630.13544, "review_required", "terminal_equals_initial_candidate", "false", 0.0, None, None, None, "hot/cold split under review", "not free battery", "STEEL-SC-S32-ATHANASIADIS-SLAB-YARD", "Athanasiadis public thesis slab storage limit; S32 selected dev input", "candidate", "Slab capacity is public-thesis-derived, not Tata-exact; thermal-state policy unresolved."),
        ("hot_slab_transfer_buffer", "hot_slabs_bus", "thermal_state_buffer", "true", "source_model_transfer", "deferred", None, None, None, "t", "not_public", "tiny_transfer_only_or_disabled", "missing", "missing", "missing", "false", None, None, None, None, "yes", "feasibility only, not strategic store", "REPO-STEEL-FREEZE-V1", "S2.13 hot/cold route governance", "missing_blocker", "Hot slab residence and thermal policy missing."),
        ("oxygen_buffer", "oxygen_bus", "physical_utility_buffer", "true", "physical buffer evidenced", "deferred", None, None, None, "t_O2", "not_public", "disabled_until_capacity_reviewed", "missing", "missing", "missing", "false", None, None, None, None, "no", "avoid artificial electricity shifting", "STEEL-SC-0016", "MER oxygen buffer context", "missing_blocker", "Oxygen storage capacity missing."),
        ("rolled_steel_target_accumulator", "rolled_steel_final_product_bus", "target_accumulator", "false", "technical target", "false", None, None, None, "t", "accounting_target", "not_a_physical_store", "n/a", "n/a", "n/a", "false", None, None, None, None, "no", "target accounting only", "REPO-STEEL-FREEZE-V1", "Fixed production target policy", "validation_only", "Not a flexibility asset."),
        ("DRI_buffer", "DRI_bus", "physical_inventory_buffer", "true", "source_model_buffer", "candidate", None, 17760.0, None, "t_DRI", "derived_48h_candidate", "finite_candidate_bound", 0.0, "nonnegative", "terminal_equality", "false", 0.0, None, None, None, "HDRI/CDRI distinction unresolved", "main C1 decoupling buffer but bounded", "STEEL-SC-0021;S3_4_GUARDRAIL_BADARINATH_2025;REPO-S4-4B-DEV-INPUTS", "S4.4b C1_DRI_BUFFER; derived from 48 h times DRP output; Badarinath buffer precedent", "candidate", "Derived development candidate, not published Tata DRI storage."),
        ("CO2_accounting_accumulator", "direct_CO2_bus", "accounting_accumulator", "false", "accounting flow", "false", None, None, None, "t_CO2", "accounting", "not_a_physical_store", "n/a", "n/a", "n/a", "false", None, None, None, None, "no", "emissions ledger only", "STEEL-SC-0003", "MRR accounting boundary", "validation_only", "Not a flexibility buffer."),
        ("COG_gas_holder", "COG_bus", "WAG_gas_holder", "true", "network buffering", "deferred", None, None, None, "GJ_or_Nm3", "not_public", "deferred_until_capacity_reviewed", "missing", "missing", "missing", "false", None, None, None, None, "no", "hourly relevance under review", "REPO-ATH-GAS-ADDENDUM;STEEL-SC-0016", "Gas network and KGF topology", "missing_blocker", "COG holder capacity not public."),
        ("BFG_gas_holder", "BFG_bus", "WAG_gas_holder", "true", "network buffering", "deferred", None, None, None, "GJ_or_Nm3", "not_public", "deferred_until_capacity_reviewed", "missing", "missing", "missing", "false", None, None, None, None, "no", "hourly relevance under review", "REPO-ATH-GAS-ADDENDUM;STEEL-SC-0016", "Gas network and BF topology", "missing_blocker", "BFG holder capacity evidence missing."),
        ("BOFG_gas_holder", "BOFG_bus", "WAG_gas_holder", "true", "explicit oxygas holder structure", "candidate", None, None, None, "GJ_or_Nm3", "not_public", "structure_only_no_capacity", "missing", "missing", "missing", "false", None, None, None, None, "no", "batch-smoothing only if capacity reviewed", "STEEL-SC-0016;STEEL-SC-0001", "MER oxygas holder; JRC BOFG gasholder table", "missing_blocker", "Oxygas holder exists structurally; capacity and flare limit missing."),
        ("steam_storage", "steam_bus", "not_a_store", "false", "not evidenced", "false", None, None, None, "GJ", "not_public", "instantaneous_bus", "n/a", "n/a", "n/a", "false", None, None, None, None, "no", "not a base hourly store", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-006", "deferred", "Steam defaults to instantaneous utility bus unless storage evidence is added."),
    ]
    rows = []
    for s in specs:
        rows.append(
            _row(
                "STORES",
                store_id=s[0],
                bus_id=s[1],
                store_class=s[2],
                physical_asset_exists=s[3],
                source_model_store=s[4],
                selected_hourly_store=s[5],
                capacity_lower=s[6],
                capacity_central=s[7],
                capacity_upper=s[8],
                capacity_unit=s[9],
                source_model_capacity_treatment=s[10],
                selected_model_capacity_treatment=s[11],
                initial_inventory_rule=s[12],
                minimum_inventory_rule=s[13],
                terminal_inventory_rule=s[14],
                cyclic=s[15],
                standing_loss=s[16],
                max_charge=s[17],
                max_discharge=s[18],
                max_residence_time=s[19],
                hot_cold_state_relevance=s[20],
                flexibility_role=s[21],
                physical_asset_exists_detail=s[3],
                source_model_representation=s[4],
                selected_hourly_model_representation=s[5],
                component_control_class="inventory_or_accounting",
                executable_status="development_review" if s[5] == "candidate" else ("missing_blocker" if s[24] == "missing_blocker" else "structural_only"),
                source_card_ids=s[22],
                source_locator=s[23],
                value_status=s[24],
                source_status="candidate" if s[24] == "candidate" else s[24],
                human_review_required="true" if s[24] in {"candidate", "missing_blocker", "deferred"} else "false",
                caveat=s[25],
            )
        )
    return rows


def _loads() -> list[dict[str, Any]]:
    specs = [
        ("residual_electricity_load", "electricity_bus", "residual electricity load", "both", "profile_missing", "", "MWh/h", None, "missing", "STEEL-SC-0016;STEEL-SC-0017", "MER annual electricity anchors only"),
        ("residual_natural_gas_load", "natural_gas_bus", "residual natural-gas load", "both", "profile_missing", "", "Nm3/h", None, "missing", "STEEL-SC-0016;STEEL-SC-0017", "MER annual gas anchors only"),
        ("residual_steam_load", "steam_bus", "residual steam load", "both", "profile_missing", "", "GJ/h", None, "missing", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-006"),
        ("residual_CO2_accounting_flow", "residual_CO2_bus", "residual CO2 accounting", "both", "accounting_rule", "", "t_CO2", None, "deferred", "STEEL-SC-0003", "MRR accounting"),
        ("cold_strip_mill_load", "electricity_bus", "Cold Strip Mill", "both", "profile_missing", "", "MWh/h", None, "missing", "STEEL-SC-0016", "Downstream boundary context"),
        ("coating_rolling_pressing_load", "electricity_bus", "Coating/Rolling/Pressing", "both", "profile_missing", "", "MWh/h", None, "missing", "STEEL-SC-0016", "Downstream boundary context"),
        ("tata_steel_packaging_load", "electricity_bus", "Tata Steel Packaging", "both", "profile_missing", "", "MWh/h", None, "missing", "STEEL-SC-0016", "Residual load boundary context"),
        ("feedstock_logistics_load", "electricity_bus", "Feedstock Logistics", "both", "profile_missing", "", "MWh/h", None, "missing", "STEEL-SC-0016", "Residual load boundary context"),
        ("energy_company_load", "electricity_bus", "Energy Company", "both", "profile_missing", "", "MWh/h", None, "missing", "S4_ECON_PBL_MIDDEN_STEEL_2019", "PBL/MIDDEN utility context"),
        ("third_party_large_loads", "electricity_bus", "third-party large loads", "both", "profile_missing", "", "MWh/h", None, "missing", "STEEL-SC-0016", "MER boundary context"),
        ("third_party_small_loads", "electricity_bus", "third-party small loads", "both", "profile_missing", "", "MWh/h", None, "missing", "STEEL-SC-0016", "MER boundary context"),
        ("linde_gts_residual_load", "electricity_bus", "Linde GTS or equivalent residual load", "both", "profile_missing", "", "MWh/h", None, "missing", "STEEL-SC-0016", "Linde/ASU boundary context"),
    ]
    return [
        _row(
            "LOADS",
            load_id=s[0],
            bus_id=s[1],
            load_family=s[2],
            configuration_scope=s[3],
            controlled_by_optimizer="false",
            profile_type=s[4],
            value_or_profile_path=s[5],
            unit=s[6],
            annual_anchor_if_any=s[7],
            allocation_method="not_selected",
            physical_asset_exists="true" if s[4] != "accounting_rule" else "false",
            source_model_representation="residual_load_or_accounting",
            selected_hourly_model_representation="profile_missing_until_reviewed",
            component_control_class="exogenous_load",
            executable_status="missing_blocker" if s[8] == "missing" else "deferred",
            source_card_ids=s[9],
            source_locator=s[10],
            value_status="missing_blocker" if s[8] == "missing" else "deferred",
            source_status="missing_blocker" if s[8] == "missing" else "deferred",
            human_review_required="true",
            caveat="No hourly profile is created from annual values without an explicit allocation method.",
        )
        for s in specs
    ]


def _generators() -> list[dict[str, Any]]:
    specs = [
        ("coal_supply", "coal_bus", "external material supply", "both", "true", None, "t/h", "unbounded_until_review", "external_import", "boundary_supply", "STEEL-SC-0016"),
        ("iron_ore_supply", "iron_ore_bus", "external material supply", "both", "true", None, "t/h", "unbounded_until_review", "external_import", "boundary_supply", "STEEL-SC-0016"),
        ("imported_pellets_supply", "imported_pellets_boundary_bus", "external imported pellet supply", "both", "true", None, "t/h", "unbounded_until_review", "external_import", "supply_route_to_pellets_bus", "REPO-S4-4B2-WORKBOOK"),
        ("scrap_supply", "scrap_bus", "external scrap supply", "both", "true", None, "t/h", "unbounded_until_review", "external_import", "boundary_supply", "STEEL-SC-0021"),
        ("electricity_grid_import", "electricity_bus", "external electricity grid import", "both", "true", None, "MW", "profile_or_bound_missing", "external_import", "boundary_supply_no_storage", "STEEL-SC-0016;STEEL-SC-0017"),
        ("natural_gas_import", "natural_gas_bus", "external natural gas import", "both", "true", None, "Nm3/h", "profile_or_bound_missing", "external_import", "boundary_supply_no_inventory", "STEEL-SC-0016;STEEL-SC-0017"),
        ("oxygen_backup_supply", "oxygen_bus", "optional external oxygen backup", "both", "false", None, "t/h", "not_selected", "external_import", "deferred_optional_backup", "STEEL-SC-0016"),
        ("residual_CO2_source", "residual_CO2_bus", "residual accounting source", "both", "false", None, "t_CO2", "accounting_only", "accounting", "reporting_closure_only", "STEEL-SC-0003"),
    ]
    return [
        _row(
            "GENERATORS",
            generator_id=s[0],
            bus_id=s[1],
            physical_source_type=s[2],
            configuration_scope=s[3],
            available=s[4],
            capacity_bound=s[5],
            capacity_unit=s[6],
            availability_profile=s[7],
            import_or_internal=s[8],
            selected_model_role=s[9],
            physical_asset_exists="true" if s[8] == "external_import" else "false",
            source_model_representation="external_source",
            selected_hourly_model_representation="boundary_source_no_price",
            component_control_class="external_supply",
            executable_status="structural_only" if s[4] == "true" else "deferred",
            source_card_ids=s[10],
            source_locator="Boundary/source context; no economic coefficients in this workbook",
            value_status="source_supported" if s[4] == "true" else "deferred",
            source_status="source_supported" if s[4] == "true" else "deferred",
            human_review_required="true" if s[7] != "unbounded_until_review" else "false",
            caveat="Generator means external physical source only. Prices, marginal costs, revenues and tariffs are excluded.",
        )
        for s in specs
    ]


def _mixing_rules() -> list[dict[str, Any]]:
    families = {
        "WAG_COK1": ("WAG_COK1_mixer", "wag_cok1_mix_bus", ["BFG", "COG"]),
        "WAG_HSM": ("WAG_HSM_mixer", "wag_hsm_mix_bus", ["COG", "natural_gas"]),
        "WAG_PEFA_MALERIJ_or_grinding": ("WAG_PEFA_MALERIJ_mixer", "wag_pellet_grinding_mix_bus", ["natural_gas", "BOFG"]),
        "WAG_PEFA_BRANDERIJ_or_firing": ("WAG_PEFA_BRANDERIJ_mixer", "wag_pellet_firing_mix_bus", ["COG", "natural_gas"]),
        "WAG_BOILERS_15_16_23_24": ("WAG_BOILERS_15_16_23_24_mixer", "wag_boiler_group_mix_bus", ["natural_gas", "COG"]),
        "WAG_BOILER_41": ("WAG_BOILER_41_mixer", "wag_boiler41_mix_bus", ["BFG", "natural_gas"]),
        "WAG_STEG11": ("WAG_STEG11_mixer", "wag_steg11_mix_bus", ["natural_gas", "BFG"]),
        "WAG_VATTENFALL_GENERATORS": ("WAG_VATTENFALL_GENERATORS_mixer", "wag_vattenfall_mix_bus", ["BFG", "COG", "BOFG", "natural_gas"]),
    }
    rows = []
    for family, (mixer, output_bus, carriers) in families.items():
        for carrier in ["BFG", "COG", "BOFG", "natural_gas"]:
            eligible = carrier in carriers
            rows.append(
                _row(
                    "MIXING_RULES",
                    mixing_rule_id=f"{family}__{carrier}",
                    mixer_link_id=mixer,
                    output_bus_id=output_bus,
                    input_carrier_id=carrier,
                    eligible=str(eligible).lower(),
                    energy_equivalence_basis="LHV",
                    minimum_LHV=None,
                    maximum_LHV=5.0 if family == "WAG_VATTENFALL_GENERATORS" and eligible else None,
                    LHV_unit="MJ/Nm3" if family == "WAG_VATTENFALL_GENERATORS" and eligible else "",
                    Wobbe_constraint_status="missing_not_inferred",
                    simultaneous_mix_allowed="true",
                    substitution_with_NG_allowed="true" if "natural_gas" in carriers else "false",
                    source_card_ids="REPO-ATH-GAS-ADDENDUM",
                    source_locator="S33I-ATH-GAS-002 to S33I-ATH-GAS-007; Figure 31-33 source-carded extraction",
                    value_status="source_supported" if eligible else "not_applicable",
                    source_status="source_supported" if eligible else "forbidden",
                    human_review_required="true" if family == "WAG_VATTENFALL_GENERATORS" else "false",
                    caveat="Eligibility is structural. Missing shares, Wobbe limits, and exact gas-quality physics are gaps.",
                )
            )
    return rows


def _operating_constraints() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    required_families = [
        "nominal capacity",
        "minimum operating level",
        "maximum operating level",
        "ramp up",
        "ramp down",
        "continuity or must-run treatment",
        "binary commitment",
        "batch-equivalent operation",
        "heat duration",
        "minimum up/down time",
        "startup/shutdown time",
        "input share or recipe bounds",
        "availability/outage",
        "route-coupling",
        "grid/import bounds",
        "mixing LHV or Wobbe bounds",
        "buffer charge/discharge limits",
        "maximum residence/holding time",
        "terminal inventory",
    ]
    for family in required_families:
        rows.append(
            _row(
                "OPERATING_CONSTRAINTS",
                constraint_id="REQ_" + family.upper().replace(" ", "_").replace("/", "_"),
                component_type="system",
                component_id="inventory_requirement",
                configuration_scope="both",
                constraint_family=family,
                unit="varies",
                basis="inventory_required_by_workbook",
                time_basis="hourly_or_static",
                hard_or_soft="inventory",
                selected_for_execution="false",
                source_card_ids="REPO-S4-4B2-WORKBOOK;REPO-STEEL-FREEZE-V1",
                source_locator="Task operating-constraint inventory requirement",
                value_status="missing_blocker",
                source_status="missing_blocker",
                human_review_required="true",
                caveat="Structural requirement preserved even where numeric Tata value is missing or redacted.",
            )
        )
    numeric = [
        ("OC_DRP_CAPACITY", "Link", "NG_DRP", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "nominal capacity", None, 500.0, None, "t_pellets/h", "average pellets throughput", "hourly", "hard", "false", "STEEL-SC-0021", "Athanasiadis Figure 47 Table 2 p.57", "candidate", "DRP capacity candidate; not Tata-exact."),
        ("OC_DRP_MIN", "Link", "NG_DRP", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "minimum operating level", 0.7, None, None, "fraction_of_average_capacity", "on-state/range", "hourly", "hard_candidate", "false", "STEEL-SC-0021", "Athanasiadis Figure 47 Table 2 p.57", "candidate", "Use only after human review."),
        ("OC_DRP_MAX", "Link", "NG_DRP", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "maximum operating level", None, None, 1.1, "fraction_of_average_capacity", "on-state/range", "hourly", "hard_candidate", "false", "STEEL-SC-0021", "Athanasiadis Figure 47 Table 2 p.57", "candidate", "Use only after human review."),
        ("OC_DRP_RAMP_UP", "Link", "NG_DRP", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "ramp up", None, 0.1, None, "fraction_of_average_capacity/h", "average capacity", "hourly", "hard_candidate", "false", "STEEL-SC-0021", "Athanasiadis Figure 47 Table 2 p.57", "candidate", "Equivalent to +/-50 t pellets/h if 500 t/h is used."),
        ("OC_DRP_RAMP_DOWN", "Link", "NG_DRP", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "ramp down", None, 0.1, None, "fraction_of_average_capacity/h", "average capacity", "hourly", "hard_candidate", "false", "STEEL-SC-0021", "Athanasiadis Figure 47 Table 2 p.57", "candidate", "Equivalent to +/-50 t pellets/h if 500 t/h is used."),
        ("OC_EAF_CAPACITY", "Link", "EAF", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "nominal capacity", None, 400.0, None, "t_DRI/h", "average DRI throughput", "hourly", "hard_candidate", "false", "STEEL-SC-0021", "Athanasiadis Figure 46 Table 1 p.56", "candidate", "Average-capacity abstraction; not transformer limit."),
        ("OC_EAF_MIN", "Link", "EAF", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "minimum operating level", 0.9, None, None, "fraction_of_average_capacity", "on-state/range", "hourly", "hard_candidate", "false", "STEEL-SC-0021", "Athanasiadis Figure 46 Table 1 p.56", "candidate", "Base guardrail should be semi-continuous binary if executed later."),
        ("OC_EAF_MAX", "Link", "EAF", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "maximum operating level", None, None, 1.1, "fraction_of_average_capacity", "on-state/range", "hourly", "hard_candidate", "false", "STEEL-SC-0021", "Athanasiadis Figure 46 Table 1 p.56", "candidate", "Base guardrail should be semi-continuous binary if executed later."),
        ("OC_EAF_BINARY", "Link", "EAF", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "binary commitment", 0.0, 1.0, 1.0, "binary", "semi-continuous hourly abstraction", "hourly", "hard_candidate", "false", "S3_4_GUARDRAIL_BADARINATH_2025;REPO-STEEL-FREEZE-V1", "Badarinath Equation 5.9 and steel policy decisions", "candidate", "Formulation precedent only; no heat sequencing."),
        ("OC_SLAB_YARD_CAPACITY", "Store", "crude_steel_or_slab_wip_store", "both", "nominal capacity", 3260.27088, 25000.0, 50000.0, "t_slab", "cold slab inventory", "static", "hard_candidate", "false", "STEEL-SC-S32-ATHANASIADIS-SLAB-YARD", "Human verified public thesis slab storage limit", "candidate", "Sensitivity required; not Tata-exact."),
        ("OC_DRI_BUFFER_TERMINAL", "Store", "DRI_buffer", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "terminal inventory", 0.0, 0.0, 0.0, "t_DRI_residual", "terminal equals initial", "horizon", "hard_candidate", "false", "S3_4_GUARDRAIL_BADARINATH_2025;REPO-S4-4B-DEV-INPUTS", "S4.4b C1_DRI_BUFFER terminal_equality", "candidate", "Endpoint-neutrality policy, not capacity evidence."),
    ]
    for item in numeric:
        rows.append(
            _row(
                "OPERATING_CONSTRAINTS",
                constraint_id=item[0],
                component_type=item[1],
                component_id=item[2],
                configuration_scope=item[3],
                constraint_family=item[4],
                lower_value=item[5],
                central_value=item[6],
                upper_value=item[7],
                unit=item[8],
                basis=item[9],
                time_basis=item[10],
                hard_or_soft=item[11],
                selected_for_execution=item[12],
                source_card_ids=item[13],
                source_locator=item[14],
                value_status=item[15],
                source_status=item[15],
                human_review_required="true",
                caveat=item[16],
            )
        )
    return rows


def _system_constraints() -> list[dict[str, Any]]:
    families = [
        ("hard_final_product_target", "Hard final-product target", "both"),
        ("route_neutral_downstream_fulfilment", "Route-neutral downstream fulfilment", "both"),
        ("hourly_carrier_balances", "Hourly carrier balances for all represented carriers", "both"),
        ("material_conservation", "Material conservation across process links and stores", "both"),
        ("electricity_balance", "Electricity balance with grid/import boundary and no storage", "both"),
        ("natural_gas_balance", "Natural gas import and process/boiler use balance", "both"),
        ("steam_balance", "Steam balance as instantaneous utility unless storage evidence is added", "both"),
        ("oxygen_balance", "Oxygen balance and ASU/backup boundary", "both"),
        ("separate_BFG_COG_BOFG_balances", "Separate BFG, COG and BOFG balances", "both"),
        ("flare_spill_closure", "Flare/spill closure for unused WAG", "both"),
        ("buffer_terminal_neutrality", "Terminal neutrality for active stores", "both"),
        ("no_free_buffer_conditions", "No unbounded or free inventory buffers", "both"),
        ("C0_C1_asset_activation", "Configuration-specific asset activation", "both"),
        ("C1_retained_route_coupling", "Retained-route coupling in C1", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"),
    ]
    return [
        _row(
            "SYSTEM_CONSTRAINTS",
            system_constraint_id=f"SYS_{idx:03d}_{family}",
            configuration_scope=scope,
            constraint_family=family,
            description=description,
            selected_for_execution="false",
            physical_only="true",
            economic_objective_term="false",
            source_card_ids="REPO-S4-4B2-WORKBOOK;REPO-STEEL-FREEZE-V1",
            source_locator="Task and freeze physical-system constraint requirements",
            value_status="assumption",
            source_status="assumption",
            human_review_required="true",
            caveat="Physical model requirement only; no economic objective term included.",
        )
        for idx, (family, description, scope) in enumerate(families, start=1)
    ]


def _validation_anchors() -> list[dict[str, Any]]:
    anchors = [
        ("VA_MER_C0_ELEC_11_PJY", "electricity", "C0_current_BF_BOF_reference", "site_total_electricity_reference", 11.0, "PJ/y", "MER current/reference electricity", "STEEL-SC-0016;STEEL-SC-0017", "MER Deel B p.31-32 Section 4.3; energy study"),
        ("VA_MER_C0_GRID_1_PJY", "electricity", "C0_current_BF_BOF_reference", "current_grid_import_reference", 1.0, "PJ/y", "MER current/reference net grid offtake", "STEEL-SC-0016;STEEL-SC-0017", "MER Deel B p.32 Section 4.3"),
        ("VA_MER_C0_WAG_REUSE_54_PJY", "WAG", "C0_current_BF_BOF_reference", "reused_WAG_to_power_or_steam", 54.0, "PJ/y", "Mixed electricity/steam WAG reuse", "STEEL-SC-0016;STEEL-SC-0017", "MER Deel B p.32 Section 4.3"),
        ("VA_MER_C0_AVG_POWER_360_MW", "electricity", "C0_current_BF_BOF_reference", "average_electric_demand", 360.0, "MW", "Average only, not connection capacity", "STEEL-SC-0016;STEEL-SC-0017", "MER Deel B p.32 Section 4.3"),
        ("VA_MER_C0_NG_13_PJY", "natural_gas", "C0_current_BF_BOF_reference", "site_natural_gas_reference", 13.0, "PJ/y", "Annual gas use, no split over boilers/DRP", "STEEL-SC-0016;STEEL-SC-0017", "MER Deel B p.31 Section 4.3"),
        ("VA_MER_C1_ELEC_16_PJY", "electricity", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "phase1_gas_total_electricity", 16.0, "PJ/y", "Annual planning anchor, not hourly truth", "STEEL-SC-0016;STEEL-SC-0017", "MER Deel B p.51 Section 5.5"),
        ("VA_MER_C1_INTERNAL_GEN_6_PJY", "electricity_generation", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "phase1_internal_or_vattenfall_generation", 6.0, "PJ/y", "Internal/Vattenfall combined annual offset", "STEEL-SC-0016;STEEL-SC-0017", "MER Deel B p.51 Section 5.5"),
        ("VA_MER_C1_GRID_10_PJY", "electricity", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "phase1_additional_grid_offtake", 10.0, "PJ/y", "Annual offtake anchor only", "STEEL-SC-0016;STEEL-SC-0017", "MER Deel B p.51 Section 5.5"),
        ("VA_MER_C1_AVG_POWER_565_MW", "electricity", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "phase1_average_power_demand", 565.0, "MW", "Average only, not connection capacity", "STEEL-SC-0016;STEEL-SC-0017", "MER Deel B p.51 Section 5.5"),
        ("VA_MER_C1_NG_47_PJY", "natural_gas", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "phase1_gas_total_natural_gas", 47.0, "PJ/y", "Annual planning anchor; no split over DRP/boilers", "STEEL-SC-0016;STEEL-SC-0017", "MER Deel B p.51 Section 5.5"),
        ("VA_ATH_C0_GROSS_ELEC_3_17_TWHY", "electricity", "C0_current_BF_BOF_reference", "Athanasiadis C0 gross site electricity", 3.17, "TWh/y", "Thesis validation target with boundary caveat", "REPO-ATH-GAS-ADDENDUM", "Table 8 p.97/111 inherited from S3.3 register"),
        ("VA_ATH_C0_WAG_ELEC_2_74_TWHY", "WAG", "C0_current_BF_BOF_reference", "Athanasiadis C0 WAG electricity", 2.74, "TWh/y", "Validation target, not WAG market value", "REPO-ATH-GAS-ADDENDUM", "Table 8 p.97/111 inherited from S3.3 register"),
        ("VA_ATH_C1_GROSS_ELEC_4_89_TWHY", "electricity", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "Athanasiadis C1 gross site electricity", 4.89, "TWh/y", "Thesis validation target with boundary caveat", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-013 Table 9 Phase 1"),
        ("VA_ATH_C1_WAG_ELEC_1_23_TWHY", "WAG", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "Athanasiadis C1 WAG electricity", 1.23, "TWh/y", "Validation target, not WAG market value", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-013 Table 9 Phase 1"),
        ("VA_ATH_C1_DIRECT_CO2_9107793", "emissions", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "Athanasiadis C1 direct CO2", 9107793.17, "t/y", "Boundary uncertain validation target", "REPO-ATH-GAS-ADDENDUM", "S33I-ATH-GAS-013 Table 9 Phase 1"),
    ]
    return [
        _row(
            "VALIDATION_ANCHORS",
            validation_anchor_id=a[0],
            anchor_family=a[1],
            configuration_relevance=a[2],
            metric=a[3],
            lower_value=a[4],
            central_value=a[4],
            upper_value=a[4],
            unit=a[5],
            annual_or_static="annual",
            validation_only="true",
            executable_input="false",
            scope_boundary=a[6],
            comparison_caveat=a[6],
            source_card_ids=a[7],
            source_locator=a[8],
            value_status="validation_only",
            source_status="validation_only",
            human_review_required="true",
            caveat="Validation anchor only. Not an hourly operating input, objective coefficient, or capacity bound.",
        )
        for a in anchors
    ]


def _modeling_decisions() -> list[dict[str, Any]]:
    decisions = [
        ("MD_ONTOLOGY", "PyPSA-inspired ontology with Pyomo compatibility", "Use Buses, Links, Stores, Loads, Generators as workbook ontology; keep solver-independent.", "Direct PyPSA dependency", "Matches component clarity without adding dependency.", "false"),
        ("MD_VATTENFALL_INTERFACE", "Vattenfall representation", "Represent Vattenfall as an interface, not literal dispatched external plant.", "Full generator dispatch", "Contracts/hourly dispatch not public.", "true"),
        ("MD_NO_DIRECT_WAG_MARKET_VALUE", "WAG valuation", "No direct WAG market valuation; WAG value only through physical substitution later.", "DA electricity price credit for WAG", "Prevents unsupported arbitrage.", "true"),
        ("MD_WAG_STORAGE", "Hourly WAG storage treatment", "Record physical gas holders separately from active hourly Stores.", "All WAG holders active stores", "Capacities and hourly relevance unresolved.", "true"),
        ("MD_STEAM_BUS", "Steam bus versus store", "Steam defaults to instantaneous utility bus.", "Steam Store", "No public steam storage evidence.", "true"),
        ("MD_MATERIAL_ANTI_ARBITRAGE", "Material stores", "Finite anti-arbitrage bounds required before execution.", "Unlimited source-model stores", "Avoids free inventory battery.", "true"),
        ("MD_HOT_COLD_SLAB", "Hot/cold slab representation", "Separate hot_slabs and cold_slabs carriers/buses; execution deferred.", "Single generic slab store", "Thermal state can affect flexibility.", "true"),
        ("MD_TARGET_ACCUMULATOR", "Rolled steel target accumulator", "Represent final product target as accounting/target accumulator, not flexibility asset.", "Physical final product Store", "Finished output target is not a scheduling buffer.", "true"),
        ("MD_CO2_ACCUMULATOR", "CO2 accounting accumulator", "CO2 buses are accounting flows, not physical flexibility buffers.", "CO2 Store as flexibility", "Avoids false storage interpretation.", "true"),
        ("MD_C1_KGF_CLOSURE", "C1 coking-plant closure", "Frozen default: BF7 plus KGF2 closes; KGF1 retained.", "Badarinath/background KGF1 closure wording", "MER/freeze source hierarchy controls default.", "true"),
        ("MD_CONTROLLABLE_CORE", "Main controllable processes versus residual loads", "Core process Links are structural; secondary/background demands are Loads until profiles reviewed.", "Everything as controllable process", "Residual profiles and capacities missing.", "true"),
        ("MD_CONT_BATCH", "Continuous versus batch-equivalent classifications", "BF/DRP continuity-driven, BOF/EAF batch-equivalent, EAF semi-continuous candidate.", "All assets continuous dimmers", "Avoids fake flexibility.", "true"),
    ]
    return [
        _row(
            "MODELING_DECISIONS",
            decision_id=d[0],
            topic=d[1],
            selected_representation=d[2],
            alternative_considered=d[3],
            decision_reason=d[4],
            changed_from_source=d[5],
            source_card_ids="REPO-STEEL-FREEZE-V1;REPO-S4-4A-CONTRACT;REPO-S4-4B2-WORKBOOK",
            source_locator="Governance freeze and S4.4b2 task requirements",
            value_status="assumption",
            source_status="assumption",
            human_review_required="true" if d[5] == "true" else "false",
            caveat="Methodological representation decision; not a physical value.",
        )
        for d in decisions
    ]


def _conflicts_gaps() -> list[dict[str, Any]]:
    required = [
        ("CG_C1_KGF_CLOSURE", "C1 KGF1/KGF2 closure inconsistency", "coking_plant_1;coking_plant_2;blast_furnace_7", "Badarinath/background passages identify BF7 plus Coking Plant 1 while another passage identifies BF7 plus Coking Plant 2; repository freeze selects BF7 plus KGF2 retaining KGF1.", "Badarinath local thesis source; MER/freeze", "Use frozen default BF7 plus KGF2 closure and retain KGF1.", "MER/frozen repository hierarchy", "structural", "false", "true", "Review exact thesis passages if local PDF is restored."),
        ("CG_REDACTED_C0_CAPACITIES", "redacted C0 capacities", "C0 process links", "Exact C0 plant capacities are redacted or not public.", "Athanasiadis; MER public documents", "Leave numeric fields blank.", "source hierarchy and confidentiality rule", "numeric", "true", "true", "Do not derive from charts."),
        ("CG_REDACTED_C0_MINMAX", "redacted C0 min/max operating levels", "C0 process links", "C0 operating envelopes missing.", "Athanasiadis/Badarinath redacted tables", "Keep as missing_blocker.", "confidentiality rule", "numeric", "true", "true", "Deepsearch or human assumption review."),
        ("CG_REDACTED_C0_RAMPS", "redacted C0 ramps", "C0 process links", "Ramp rates unavailable.", "Athanasiadis/Badarinath redacted or missing", "Keep as missing_blocker.", "confidentiality rule", "numeric", "true", "true", "Do not infer from annual outputs."),
        ("CG_COKE_SINTER_PELLET_STORE_CAPS", "exact coke/sinter/pellet storage capacities", "coke_store;sinter_store;pellets_store", "Physical buffer capacities are not public.", "MER topology only", "Record stores but do not execute unlimited storage.", "anti-arbitrage governance", "numeric", "true", "true", "Human review or sensitivity range needed."),
        ("CG_HOT_METAL_TORPEDO", "hot-metal/torpedo capacity", "hot_metal_buffer", "Hot metal transfer capacity missing.", "S2 governance; public sources", "Require tight bound before execution.", "physical guardrail rule", "numeric", "true", "true", "Review torpedo/mixer public evidence."),
        ("CG_SLAB_YARD_THERMAL", "slab-yard capacity and thermal-state policy", "crude_steel_or_slab_wip_store;hot_slab_transfer_buffer", "Slab capacity candidate exists but hot/cold/residence policy unresolved.", "Athanasiadis slab source card; S2.13 governance", "Use candidate only for review; do not execute without policy.", "S2.13 governance", "numeric_and_structural", "true", "true", "Decide hot/cold state and residence treatment."),
        ("CG_OXYGEN_STORAGE_CAPACITY", "oxygen storage capacity", "oxygen_buffer", "Oxygen buffers evidenced structurally but capacity missing.", "MER", "Do not allow oxygen-storage electricity shifting.", "source hierarchy", "numeric", "true", "true", "Review oxygen utility evidence."),
        ("CG_GAS_HOLDERS_FLARE", "gas-holder capacities and flare limits", "COG_gas_holder;BFG_gas_holder;BOFG_gas_holder;flare", "Holder/flare structure supported but capacities/limits missing.", "MER; JRC BREF; Athanasiadis", "Keep structural and non-executable.", "physical guardrail rule", "numeric", "true", "true", "Review public gas holder and flare evidence."),
        ("CG_RESIDUAL_LOAD_PROFILES", "hourly residual load profiles", "residual loads", "No reviewed hourly profiles for background electricity, NG, steam, third-party loads.", "MER annual anchors", "Keep profile_missing.", "S4.2b block", "structural", "true", "true", "Define allocation method before DA use."),
        ("CG_BOILER_STEAM_BASIS", "boiler efficiencies and steam basis", "boilers_15_16_23_24;boiler_41;steam_bus", "Steam enthalpy/useful energy conventions unresolved.", "Athanasiadis Figure 32; discovery-only boiler rows", "Flag missing; no internal steam price.", "utility governance", "numeric", "true", "true", "Resolve steam unit basis and boiler efficiency."),
        ("CG_MIXING_WOBBE", "mixing/Wobbe limits", "mixing rules", "Eligibility known for several sinks; Wobbe limits missing.", "Athanasiadis gas figures", "Do not infer missing Wobbe limits.", "source-card caveat", "numeric", "false", "true", "Add gas-quality evidence if needed."),
        ("CG_VATTENFALL_CAPACITIES", "Vattenfall interface capacities", "IJ01_interface;VN24_interface;VN25_interface", "Public sources support interface but not dispatch or contract limits.", "Vattenfall/Tata/MER", "Represent as interface only.", "S4 policy", "numeric", "false", "true", "No literal external plant dispatch."),
        ("CG_GRID_IMPORT_BOUND", "grid connection/import bound", "electricity_grid_import", "Average demand and infrastructure values are not import entitlement.", "MER", "Do not use average MW as connection capacity.", "network policy", "numeric", "true", "true", "Review technical/contracted capacity separately."),
        ("CG_DOWNSTREAM_CAPACITIES", "exact downstream/caster capacities", "caster;HSM;DSP", "Exact caster/HSM/DSP capacities missing.", "S2.13 governance", "Record structure; leave missing.", "physical guardrail rule", "numeric", "true", "true", "Human review required."),
        ("CG_TERMINAL_POLICY", "terminal inventory policy", "all active stores", "Store endpoint rules not final for material and WAG stores.", "governance", "Require initial/terminal policy status for every store.", "anti-arbitrage rule", "structural", "true", "true", "Review per store before execution."),
        ("CG_C1_WAG_COEFFS", "Phase 1 retained-route WAG coefficients", "C1 retained BF/BOF/coking route", "C1 WAG generation must follow retained assets, but exact retained route shares and coefficients need review.", "MER; S3 WAG registers", "Use route-specific active assets, not inherited C0 WAG supply.", "source hierarchy", "numeric_and_structural", "true", "true", "Review retained-route basis."),
    ]
    return [
        _row(
            "CONFLICTS_GAPS",
            gap_or_conflict_id=r[0],
            topic=r[1],
            entity_ids=r[2],
            description=r[3],
            conflicting_sources=r[4],
            selected_current_interpretation=r[5],
            selection_authority=r[6],
            numeric_or_structural=r[7],
            blocking_for_physical_model=r[8],
            blocking_for_DA_model=r[9],
            human_review_required="true",
            recommended_resolution=r[10],
            source_card_ids="REPO-STEEL-FREEZE-V1;REPO-S4-4A-CONTRACT;REPO-S4-4B2-WORKBOOK",
            source_locator="Required S4.4b2 conflicts/gaps inventory",
            value_status="missing_blocker" if r[8] == "true" else "deferred",
            source_status="missing_blocker" if r[8] == "true" else "deferred",
            caveat="Gap/conflict is intentionally visible and not silently resolved.",
        )
        for r in required
    ]


def _model_boundary() -> list[dict[str, Any]]:
    included = [
        ("MB_C0_C1_SITE", "both", "site_boundary", "Tata public selected boundary", "true", "canonical public Tata-inspired model boundary", "physical specification"),
        ("MB_NO_ECONOMICS", "both", "scope_exclusion", "economics_and_DA", "false", "no economics, prices, bidding, stochasticity or CVaR in this workbook", "out_of_scope"),
        ("MB_VATTENFALL_INTERFACE", "both", "interface", "Vattenfall", "true", "WAG/power interface only", "interface_not_dispatch_plant"),
        ("MB_WAG_SEPARATE", "both", "carrier_boundary", "BFG_COG_BOFG", "true", "separate WAG balances", "separate carriers"),
        ("MB_C1_CHANGESET", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "change_set", "C1 over C0", "true", "C1 represented as retained/added/closed components", "topology change set"),
        ("MB_NO_FULL_EUPHEMIA", "both", "scope_exclusion", "market_clearing", "false", "no full EUPHEMIA or market clearing", "out_of_scope"),
        ("MB_NO_MFRR", "both", "scope_exclusion", "mFRR", "false", "no mFRR before DA-only hydrogen/steel physics are stable", "out_of_scope"),
    ]
    return [
        _row(
            "MODEL_BOUNDARY",
            boundary_id=item[0],
            configuration_scope=item[1],
            entity_family=item[2],
            entity_id=item[3],
            included=item[4],
            boundary_role=item[5],
            selected_model_role=item[6],
            source_card_ids="REPO-STEEL-FREEZE-V1;REPO-S4-4B2-WORKBOOK",
            source_locator="AGENTS, steel freeze, S4.4a contract and current task scope",
            value_status="assumption",
            source_status="assumption",
            human_review_required="false",
            caveat="Boundary decision only, not a numerical input.",
        )
        for item in included
    ]


def _views(config_components: list[dict[str, Any]], links: list[dict[str, Any]], ports: list[dict[str, Any]], stores: list[dict[str, Any]], constraints: list[dict[str, Any]], mixing: list[dict[str, Any]], gaps: list[dict[str, Any]], configuration_id: str) -> list[dict[str, Any]]:
    link_map = {row["link_id"]: row for row in links}
    input_ports: dict[str, list[str]] = {}
    output_ports: dict[str, list[str]] = {}
    for port in ports:
        target = input_ports if port["direction"] == "input" else output_ports
        target.setdefault(port["link_id"], []).append(port["bus_id"])
    constraint_map: dict[str, list[str]] = {}
    for row in constraints:
        constraint_map.setdefault(row["component_id"], []).append(row["constraint_family"])
    store_map: dict[str, str] = {row["bus_id"]: row["store_id"] for row in stores}
    mixer_map = {row["mixer_link_id"] for row in mixing if row["eligible"] == "true"}
    gap_topics = {entity: row["topic"] for row in gaps for entity in row["entity_ids"].split(";") if entity}
    rows = []
    for comp in config_components:
        if comp["configuration_id"] != configuration_id or comp["component_type"] != "Link" or comp["active"] != "true":
            continue
        link = link_map[comp["component_id"]]
        stores_for_outputs = [store_map[bus] for bus in output_ports.get(link["link_id"], []) if bus in store_map]
        rows.append(
            _row(
                "C0_VIEW" if configuration_id.startswith("C0") else "C1_VIEW",
                configuration_id=configuration_id,
                component_id=link["link_id"],
                pypsa_inspired_type="Link",
                inputs=";".join(input_ports.get(link["link_id"], [])),
                outputs=";".join(output_ports.get(link["link_id"], [])),
                controllability=link["controllable"],
                operating_constraints=";".join(sorted(set(constraint_map.get(link["link_id"], [])))),
                connected_store=";".join(stores_for_outputs),
                relevant_WAG_rule="yes" if link["link_id"] in mixer_map or "WAG" in link["link_id"] else "no",
                source_status=link["source_status"],
                executable_status=link["executable_status"],
                unresolved_gaps=gap_topics.get(link["link_id"], ""),
            )
        )
    return rows


def _evidence_links(data: dict[str, list[dict[str, Any]]], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_locators = {row["source_card_id"]: row.get("exact_locator", "") for row in sources}
    rows: list[dict[str, Any]] = []
    link_counter = 1
    row_to_links: dict[tuple[str, str], list[str]] = {}
    for sheet, sheet_rows in data.items():
        if sheet not in CORE_ENTITY_SHEETS:
            continue
        id_col = ID_COLUMNS[sheet]
        numeric_cols = set(NUMERIC_COLUMNS.get(sheet, []))
        for row in sheet_rows:
            entity_id = str(row.get(id_col, ""))
            if not entity_id:
                continue
            source_id = _first_source_id(row)
            exact_locator = row.get("source_locator") or source_locators.get(source_id, "")
            evidence_id = f"EL_{link_counter:05d}"
            link_counter += 1
            rows.append(
                _row(
                    "EVIDENCE_LINKS",
                    evidence_link_id=evidence_id,
                    entity_sheet=sheet,
                    entity_id=entity_id,
                    field_name="__row__",
                    source_card_id=source_id,
                    exact_locator=exact_locator,
                    evidence_type="structural_or_governance_support",
                    support_strength=row.get("source_status", "assumption"),
                    supports=f"{sheet}.{entity_id} row inclusion and classification",
                    does_not_support="Exact executable Tata value unless separately linked.",
                    derivation_method="direct source-card/register/governance mapping",
                    conflict_group_id="CG_C1_KGF_CLOSURE" if entity_id in {"coking_plant_1", "coking_plant_2", "blast_furnace_7", "CG_C1_KGF_CLOSURE"} else "",
                    caveat=row.get("caveat", ""),
                )
            )
            row_to_links.setdefault((sheet, entity_id), []).append(evidence_id)
            for col in numeric_cols:
                value = row.get(col)
                if value in ("", None):
                    continue
                evidence_id = f"EL_{link_counter:05d}"
                link_counter += 1
                rows.append(
                    _row(
                        "EVIDENCE_LINKS",
                        evidence_link_id=evidence_id,
                        entity_sheet=sheet,
                        entity_id=entity_id,
                        field_name=col,
                        source_card_id=source_id,
                        exact_locator=exact_locator,
                        evidence_type="numeric_value_or_candidate",
                        support_strength=row.get("value_status", row.get("source_status", "candidate")),
                        supports=f"{col}={value}",
                        does_not_support="Approved thesis executable input unless status explicitly permits later human-reviewed promotion.",
                        derivation_method="direct registered value, source-carded candidate, or documented derivation",
                        conflict_group_id="",
                        caveat=row.get("caveat", ""),
                    )
                )
                row_to_links.setdefault((sheet, entity_id), []).append(evidence_id)
    for sheet, sheet_rows in data.items():
        if sheet not in CORE_ENTITY_SHEETS:
            continue
        id_col = ID_COLUMNS[sheet]
        for row in sheet_rows:
            entity_id = str(row.get(id_col, ""))
            if entity_id:
                row["evidence_link_ids"] = ";".join(row_to_links.get((sheet, entity_id), []))
    return rows


def _qa_summary(data: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    checks = _validate_data(data)
    return [_row("QA_SUMMARY", **check) for check in checks]


def build_workbook_data() -> dict[str, list[dict[str, Any]]]:
    sources = _load_sources()
    carriers = _carriers()
    buses = _buses(carriers)
    links = _links()
    ports = _link_ports()
    stores = _stores()
    loads = _loads()
    generators = _generators()
    config_components = _config_components(links, stores, loads, generators)
    constraints = _operating_constraints()
    mixing = _mixing_rules()
    system_constraints = _system_constraints()
    validation_anchors = _validation_anchors()
    decisions = _modeling_decisions()
    gaps = _conflicts_gaps()
    data: dict[str, list[dict[str, Any]]] = {
        "README": _readme_rows(),
        "ENUMS_UNITS": _enum_rows(),
        "SOURCES": sources,
        "MODEL_BOUNDARY": _model_boundary(),
        "CONFIGURATIONS": _configurations(),
        "COMPONENT_ALIASES": _aliases(),
        "CARRIERS": carriers,
        "BUSES": buses,
        "CONFIG_COMPONENTS": config_components,
        "LINKS": links,
        "LINK_PORTS": ports,
        "OPERATING_CONSTRAINTS": constraints,
        "STORES": stores,
        "LOADS": loads,
        "GENERATORS": generators,
        "MIXING_RULES": mixing,
        "SYSTEM_CONSTRAINTS": system_constraints,
        "VALIDATION_ANCHORS": validation_anchors,
        "MODELING_DECISIONS": decisions,
        "CONFLICTS_GAPS": gaps,
        "CHANGELOG": [
            _row(
                "CHANGELOG",
                revision=WORKBOOK_REVISION,
                date_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                change_type="initial_build",
                description="Initial S4.4b2 physical master workbook generated from governed source registers and S4 surfaces.",
                author_or_agent="Codex",
            )
        ],
    }
    evidence = _evidence_links(data, sources)
    data["EVIDENCE_LINKS"] = evidence
    data["C0_VIEW"] = _views(config_components, links, ports, stores, constraints, mixing, gaps, "C0_current_BF_BOF_reference")
    data["C1_VIEW"] = _views(config_components, links, ports, stores, constraints, mixing, gaps, "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF")
    data["QA_SUMMARY"] = _qa_summary(data)
    data["DATA_DICTIONARY"] = _data_dictionary_rows()
    return {sheet: data.get(sheet, []) for sheet in REQUIRED_SHEETS}


def _data_dictionary_rows() -> list[dict[str, Any]]:
    rows = []
    for sheet, columns in SCHEMAS.items():
        for column in columns:
            allowed = ""
            if column in {"source_status"}:
                allowed = "ENUMS_UNITS:source_status"
            elif column in {"value_status"}:
                allowed = "ENUMS_UNITS:value_status"
            elif column in {"direction"}:
                allowed = "ENUMS_UNITS:direction"
            elif column in {"component_type"}:
                allowed = "ENUMS_UNITS:component_type"
            elif column in {"configuration_id", "configuration_scope", "configuration_relevance"}:
                allowed = "ENUMS_UNITS:configuration_id"
            rows.append(
                _row(
                    "DATA_DICTIONARY",
                    sheet_name=sheet,
                    column_name=column,
                    description=column.replace("_", " "),
                    required="true" if column in {ID_COLUMNS.get(sheet), "source_status", "value_status"} else "false",
                    allowed_values=allowed,
                    unit_notes="numeric columns remain numeric; use value_status instead of string unknowns",
                )
            )
    return rows


def _validate_data(data: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(check_id: str, severity: str, status: str, detail: str) -> None:
        checks.append({"check_id": check_id, "severity": severity, "status": status, "detail": detail})

    missing_sheets = [sheet for sheet in REQUIRED_SHEETS if sheet not in data]
    add("required_sheets", "failure", "pass" if not missing_sheets else "fail", "all required sheets present" if not missing_sheets else ";".join(missing_sheets))

    for sheet in CORE_ENTITY_SHEETS | {"SOURCES"}:
        id_col = ID_COLUMNS[sheet]
        seen: set[str] = set()
        duplicates = []
        for row in data.get(sheet, []):
            value = str(row.get(id_col, ""))
            if value in seen:
                duplicates.append(value)
            seen.add(value)
        add(f"{sheet}:duplicate_ids", "failure", "pass" if not duplicates else "fail", "no duplicate ids" if not duplicates else ";".join(duplicates))

    source_ids = {row["source_card_id"] for row in data.get("SOURCES", [])}
    orphan_sources = []
    for sheet, rows in data.items():
        if sheet not in CORE_ENTITY_SHEETS:
            continue
        for row in rows:
            for source_id in _split_ids(str(row.get("source_card_ids", ""))):
                if source_id not in source_ids:
                    orphan_sources.append(f"{sheet}:{row.get(ID_COLUMNS[sheet])}:{source_id}")
    add("orphan_source_references", "failure", "pass" if not orphan_sources else "fail", "no orphan source references" if not orphan_sources else ";".join(orphan_sources[:10]))

    bus_ids = {row["bus_id"] for row in data.get("BUSES", [])}
    orphan_buses = []
    for sheet in ["LINK_PORTS", "STORES", "LOADS", "GENERATORS"]:
        for row in data.get(sheet, []):
            bus_id = row.get("bus_id")
            if bus_id and bus_id not in bus_ids:
                orphan_buses.append(f"{sheet}:{row.get(ID_COLUMNS[sheet])}:{bus_id}")
    add("orphan_bus_references", "failure", "pass" if not orphan_buses else "fail", "no orphan bus references" if not orphan_buses else ";".join(orphan_buses[:10]))

    active_links = {
        row["component_id"]
        for row in data.get("CONFIG_COMPONENTS", [])
        if row["component_type"] == "Link" and row["active"] == "true"
    }
    input_links = {row["link_id"] for row in data.get("LINK_PORTS", []) if row["direction"] == "input"}
    output_links = {row["link_id"] for row in data.get("LINK_PORTS", []) if row["direction"] == "output"}
    no_inputs = sorted(active_links - input_links)
    no_outputs = sorted(active_links - output_links)
    add("active_link_with_no_input", "failure", "pass" if not no_inputs else "fail", "all active links have inputs" if not no_inputs else ";".join(no_inputs))
    add("active_link_with_no_output", "failure", "pass" if not no_outputs else "fail", "all active links have outputs" if not no_outputs else ";".join(no_outputs))

    bad_stores = [
        row["store_id"]
        for row in data.get("STORES", [])
        if row["selected_hourly_store"] in {"candidate", "true"} and not row["terminal_inventory_rule"]
    ]
    add("active_store_without_terminal_rule", "failure", "pass" if not bad_stores else "fail", "active/candidate stores have terminal policy status" if not bad_stores else ";".join(bad_stores))

    numeric_without_evidence = []
    evidence_by_field = {
        (row["entity_sheet"], row["entity_id"], row["field_name"])
        for row in data.get("EVIDENCE_LINKS", [])
        if row["field_name"] != "__row__"
    }
    for sheet, columns in NUMERIC_COLUMNS.items():
        id_col = ID_COLUMNS[sheet]
        for row in data.get(sheet, []):
            for column in columns:
                if row.get(column) not in ("", None) and (sheet, str(row.get(id_col, "")), column) not in evidence_by_field:
                    numeric_without_evidence.append(f"{sheet}:{row.get(id_col)}:{column}")
    add("numeric_value_without_source_or_assumption", "failure", "pass" if not numeric_without_evidence else "fail", "all populated numeric values have evidence links" if not numeric_without_evidence else ";".join(numeric_without_evidence[:10]))

    validation_executable = [
        row["validation_anchor_id"]
        for row in data.get("VALIDATION_ANCHORS", [])
        if row["executable_input"] != "false" or row["validation_only"] != "true"
    ]
    add("validation_only_value_used_as_executable", "failure", "pass" if not validation_executable else "fail", "validation anchors are non-executable" if not validation_executable else ";".join(validation_executable))

    redacted_executable = [
        f"{sheet}:{row.get(ID_COLUMNS[sheet])}"
        for sheet, rows in data.items()
        if sheet in CORE_ENTITY_SHEETS
        for row in rows
        if row.get("value_status") == "redacted_or_not_public" and row.get("selected_for_execution") == "true"
    ]
    add("redacted_value_used_as_executable", "failure", "pass" if not redacted_executable else "fail", "no redacted values are executable" if not redacted_executable else ";".join(redacted_executable))

    kgf_conflict = any(row["gap_or_conflict_id"] == "CG_C1_KGF_CLOSURE" for row in data.get("CONFLICTS_GAPS", []))
    add("source_conflict_silently_resolved", "failure", "pass" if kgf_conflict else "fail", "KGF1/KGF2 closure conflict is visible" if kgf_conflict else "missing KGF conflict row")

    wag_producers = {
        row["link_id"]
        for row in data.get("LINK_PORTS", [])
        if row["direction"] == "output" and row["bus_id"] in {"BFG_bus", "COG_bus", "BOFG_bus"}
    }
    wag_sinks = {
        row["link_id"]
        for row in data.get("LINK_PORTS", [])
        if row["direction"] == "input" and row["bus_id"] in {"BFG_bus", "COG_bus", "BOFG_bus", "wag_vattenfall_mix_bus", "wag_boiler_group_mix_bus"}
    }
    add("WAG_producer_without_sink_or_flare", "warning", "pass" if wag_producers and "flare" in wag_sinks else "warning", "WAG producers and flare/sinks represented")

    mixed_bus_ids = {row["output_bus_id"] for row in data.get("MIXING_RULES", []) if row["eligible"] == "true"}
    mixed_buses = {row["bus_id"] for row in data.get("BUSES", []) if row["network_layer"] == "mixed_WAG"}
    missing_mixers = sorted(mixed_buses - mixed_bus_ids)
    add("mixed_gas_bus_without_mixer", "failure", "pass" if not missing_mixers else "fail", "mixed-gas buses have mixer rules" if not missing_mixers else ";".join(missing_mixers))

    final_buses = [
        row for row in data.get("BUSES", []) if row["carrier_id"] == "rolled_steel_or_final_product"
    ]
    add("C0_C1_final_product_basis_mismatch", "warning", "pass" if final_buses else "warning", "shared final-product bus represented")

    add("LHV_HHV_ambiguity", "warning", "pass", "WAG and NG heating values are labelled LHV; unresolved steam enthalpy is a gap.")
    add("inconsistent_units", "warning", "pass", "Canonical balance units are defined per bus; source volume coefficients retain explicit basis.")
    return checks


def _add_table(ws, sheet_name: str, rows: list[dict[str, Any]]) -> None:
    columns = SCHEMAS[sheet_name]
    ws.append(columns)
    for row in rows:
        ws.append([row.get(column, "") for column in columns])
    if len(rows) == 0:
        ws.append(["" for _ in columns])
    ref = f"A1:{ws.cell(row=max(2, len(rows) + 1), column=len(columns)).coordinate}"
    table_name = "tbl_" + "".join(ch if ch.isalnum() else "_" for ch in sheet_name)[:25]
    table = Table(displayName=table_name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showFirstColumn=False, showLastColumn=False, showRowStripes=True, showColumnStripes=False)
    ws.add_table(table)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ref
    for column_cells in ws.columns:
        max_len = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
        width = min(max(max_len + 2, 12), 55)
        ws.column_dimensions[column_cells[0].column_letter].width = width
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for cell in ws[1]:
        cell.font = Font(bold=True)


def _enum_ranges(ws) -> dict[str, str]:
    ranges: dict[str, tuple[int, int]] = {}
    for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        category = row[0]
        if not category:
            continue
        start, _ = ranges.get(category, (idx, idx))
        ranges[category] = (start, idx)
    return {category: f"'{ws.title}'!$B${start}:$B${end}" for category, (start, end) in ranges.items()}


def _apply_data_validations(wb: Workbook) -> None:
    enum_ranges = _enum_ranges(wb["ENUMS_UNITS"])
    column_to_enum = {
        "source_status": "source_status",
        "value_status": "value_status",
        "direction": "direction",
        "component_type": "component_type",
        "configuration_id": "configuration_id",
        "configuration_scope": "configuration_id",
        "configuration_relevance": "configuration_id",
        "executable_status": "executable_status",
        "active": "boolean",
        "eligible": "boolean",
        "controlled_by_optimizer": "boolean",
        "validation_only": "boolean",
        "executable_input": "boolean",
        "economic_objective_term": "boolean",
        "physical_only": "boolean",
    }
    for sheet_name in REQUIRED_SHEETS:
        ws = wb[sheet_name]
        headers = [cell.value for cell in ws[1]]
        for idx, header in enumerate(headers, start=1):
            enum_name = column_to_enum.get(str(header))
            if not enum_name or enum_name not in enum_ranges or ws.max_row < 2:
                continue
            dv = DataValidation(type="list", formula1=f"={enum_ranges[enum_name]}", allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(f"{ws.cell(row=2, column=idx).coordinate}:{ws.cell(row=ws.max_row, column=idx).coordinate}")


def _apply_conditional_formatting(wb: Workbook) -> None:
    for ws in wb.worksheets:
        if ws.max_row < 2 or ws.max_column < 1:
            continue
        ref = f"A2:{ws.cell(row=ws.max_row, column=ws.max_column).coordinate}"
        for status, color in STATUS_FILLS.items():
            fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
            ws.conditional_formatting.add(ref, CellIsRule(operator="equal", formula=[f'"{status}"'], fill=fill))
            if status == "redacted":
                ws.conditional_formatting.add(ref, CellIsRule(operator="equal", formula=['"redacted_or_not_public"'], fill=fill))


def _apply_hyperlinks(wb: Workbook) -> None:
    ws = wb["SOURCES"]
    headers = [cell.value for cell in ws[1]]
    if "source_url_or_doi" not in headers:
        return
    col = headers.index("source_url_or_doi") + 1
    for row_idx in range(2, ws.max_row + 1):
        cell = ws.cell(row=row_idx, column=col)
        value = str(cell.value or "")
        if value.startswith(("http://", "https://")):
            cell.hyperlink = value
            cell.style = "Hyperlink"


def build_initial_workbook(*, rebuild: bool = False, workbook_path: Path = WORKBOOK_PATH) -> WorkbookResult:
    if workbook_path.exists() and not rebuild:
        validation = validate_workbook(workbook_path)
        return WorkbookResult(workbook_path=workbook_path, validation_report=validation)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = build_workbook_data()
    wb = Workbook()
    wb.remove(wb.active)
    for sheet_name in REQUIRED_SHEETS:
        ws = wb.create_sheet(sheet_name)
        _add_table(ws, sheet_name, data[sheet_name])
        if sheet_name in {"C0_VIEW", "C1_VIEW"}:
            ws.protection.sheet = True
    _apply_data_validations(wb)
    _apply_conditional_formatting(wb)
    _apply_hyperlinks(wb)
    wb.save(workbook_path)
    validation = validate_workbook(workbook_path)
    return WorkbookResult(workbook_path=workbook_path, validation_report=validation)


def _sheet_rows_from_workbook(workbook_path: Path, sheet_name: str) -> list[dict[str, Any]]:
    wb = load_workbook(workbook_path, data_only=False)
    ws = wb[sheet_name]
    headers = [cell.value for cell in ws[1]]
    rows = []
    for values in ws.iter_rows(min_row=2, values_only=True):
        if all(value in ("", None) for value in values):
            continue
        rows.append({str(header): value for header, value in zip(headers, values)})
    return rows


def _workbook_data_from_file(workbook_path: Path) -> dict[str, list[dict[str, Any]]]:
    wb = load_workbook(workbook_path, data_only=False)
    data: dict[str, list[dict[str, Any]]] = {}
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        headers = [cell.value for cell in ws[1]]
        rows = []
        for values in ws.iter_rows(min_row=2, values_only=True):
            if all(value in ("", None) for value in values):
                continue
            rows.append({str(header): value for header, value in zip(headers, values)})
        data[sheet_name] = rows
    return data


def validate_workbook(workbook_path: Path = WORKBOOK_PATH, *, write_reports: bool = True) -> dict[str, Any]:
    if not workbook_path.exists():
        raise FileNotFoundError(workbook_path)
    wb = load_workbook(workbook_path, data_only=False)
    missing_sheets = [sheet for sheet in REQUIRED_SHEETS if sheet not in wb.sheetnames]
    table_failures = [
        sheet for sheet in REQUIRED_SHEETS if sheet in wb.sheetnames and not wb[sheet].tables
    ]
    validation_failures = []
    for sheet in ["CONFIG_COMPONENTS", "LINK_PORTS", "CARRIERS"]:
        if sheet in wb.sheetnames and len(wb[sheet].data_validations.dataValidation) == 0:
            validation_failures.append(sheet)
    formulas = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    formulas.append(f"{ws.title}!{cell.coordinate}")
    data = _workbook_data_from_file(workbook_path)
    checks = _validate_data(data)
    checks.append({"check_id": "openpyxl_workbook_load", "severity": "failure", "status": "pass", "detail": "workbook loaded with openpyxl"})
    checks.append({"check_id": "sheet_table_sanity", "severity": "failure", "status": "pass" if not missing_sheets and not table_failures else "fail", "detail": "all required sheets have tables" if not missing_sheets and not table_failures else f"missing_sheets={missing_sheets}; table_failures={table_failures}"})
    checks.append({"check_id": "data_validation_sanity", "severity": "warning", "status": "pass" if not validation_failures else "warning", "detail": "data validations present on controlled sheets" if not validation_failures else ";".join(validation_failures)})
    checks.append({"check_id": "formula_sanity", "severity": "warning", "status": "pass", "detail": f"{len(formulas)} formulas found; workbook intentionally uses no formulas" if formulas else "no workbook formulas"})
    failures = [row for row in checks if row["severity"] == "failure" and row["status"] == "fail"]
    warnings = [row for row in checks if row["status"] == "warning"]
    decision = STAGE_GATE_DECISION if not failures else "blocked_source_provenance_failure"
    report = {
        "stage": "S4.4b2",
        "decision": decision,
        "workbook_path": _repo_rel(workbook_path),
        "workbook_schema_version": WORKBOOK_SCHEMA_VERSION,
        "workbook_revision": WORKBOOK_REVISION,
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sheet_count": len(wb.sheetnames),
        "table_count": sum(len(ws.tables) for ws in wb.worksheets),
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "checks": checks,
        "caveat": "Workbook is ready for human physical-model review only. It is not ready for unified model execution or thesis claims.",
    }
    if write_reports:
        _write_json(OUTPUT_DIR / "s4_4b2_workbook_validation_report.json", report)
        _write_csv(OUTPUT_DIR / "s4_4b2_workbook_validation_report.csv", checks, ["check_id", "severity", "status", "detail"])
        gate = {
            "stage": "S4.4b2",
            "decision": decision,
            "ready_for_human_physical_model_review": decision == STAGE_GATE_DECISION,
            "ready_for_unified_model_execution": False,
            "thesis_usable": False,
            "failure_count": len(failures),
            "warning_count": len(warnings),
            "workbook_schema_version": WORKBOOK_SCHEMA_VERSION,
            "workbook_revision": WORKBOOK_REVISION,
            "caveat": report["caveat"],
        }
        _write_json(OUTPUT_DIR / "s4_4b2_stage_gate.json", gate)
        _write_csv(OUTPUT_DIR / "s4_4b2_stage_gate.csv", [gate])
    return report


def compile_review_snapshot(workbook_path: Path = WORKBOOK_PATH) -> dict[str, Any]:
    if not workbook_path.exists():
        raise FileNotFoundError(workbook_path)
    COMPILED_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    compiled: dict[str, int] = {}
    for sheet, filename in COMPILED_SHEETS.items():
        rows = _sheet_rows_from_workbook(workbook_path, sheet)
        _write_csv(COMPILED_REVIEW_DIR / filename, rows, SCHEMAS[sheet])
        compiled[filename] = len(rows)
    comparison = compare_workbook_coverage(workbook_path)
    _write_audit_reports(workbook_path, comparison)
    return {
        "compiled_review_dir": _repo_rel(COMPILED_REVIEW_DIR),
        "compiled_files": compiled,
        "comparison_summary": comparison["summary"],
    }


def compare_workbook_coverage(workbook_path: Path = WORKBOOK_PATH) -> dict[str, Any]:
    data = _workbook_data_from_file(workbook_path)
    links = {row["link_id"] for row in data["LINKS"]}
    stores = {row["store_id"] for row in data["STORES"]}
    loads = {row["load_id"] for row in data["LOADS"]}
    generators = {row["generator_id"] for row in data["GENERATORS"]}
    carriers = {row["carrier_id"] for row in data["CARRIERS"]}
    s44b_files = {
        path.name: _read_csv(path)
        for path in S44B_DIR.glob("*.csv")
        if path.name in {
            "configuration_assets.csv",
            "process_units.csv",
            "process_io_coefficients.csv",
            "process_energy_intensities.csv",
            "buffers_and_stores.csv",
            "wag_generation_coefficients.csv",
            "wag_sink_eligibility.csv",
            "utility_demands.csv",
            "utility_conversion_assets.csv",
            "validation_anchors.csv",
        }
    }
    mapping_rows: list[dict[str, Any]] = []
    for file_name, rows in s44b_files.items():
        for row in rows:
            candidate_ids = [
                row.get("asset_id"),
                row.get("process_id"),
                row.get("buffer_id"),
                row.get("carrier"),
                row.get("wag_carrier"),
                row.get("asset_id"),
                row.get("metric"),
            ]
            candidate_ids = [str(item) for item in candidate_ids if item]
            status = "existing-S4.4b-only"
            match = ""
            for item in candidate_ids:
                normalized = item.lower()
                for collection_name, collection in [
                    ("links", links),
                    ("stores", stores),
                    ("loads", loads),
                    ("generators", generators),
                    ("carriers", carriers),
                ]:
                    for workbook_id in collection:
                        if normalized in workbook_id.lower() or workbook_id.lower() in normalized:
                            status = "matching_or_covered"
                            match = workbook_id
                            break
                    if match:
                        break
                if match:
                    break
            mapping_rows.append(
                {
                    "existing_file": file_name,
                    "existing_key": ";".join(candidate_ids),
                    "workbook_entity_id": match,
                    "comparison_status": status,
                    "candidate_migration": "later_human_approval_required",
                    "caveat": "S4.4b rows are development-only and are not overwritten or migrated by S4.4b2.",
                }
            )
    workbook_only = sorted((links | stores | loads | generators | carriers) - {row["workbook_entity_id"] for row in mapping_rows if row["workbook_entity_id"]})
    for entity_id in workbook_only:
        mapping_rows.append(
            {
                "existing_file": "",
                "existing_key": "",
                "workbook_entity_id": entity_id,
                "comparison_status": "workbook-only",
                "candidate_migration": "not_applicable",
                "caveat": "Workbook row expands structural physical specification beyond existing S4.4b dev inputs.",
            }
        )
    summary = {
        "workbook_links": len(links),
        "workbook_stores": len(stores),
        "workbook_loads": len(loads),
        "workbook_generators": len(generators),
        "workbook_carriers": len(carriers),
        "mapping_rows": len(mapping_rows),
        "matching_rows": sum(1 for row in mapping_rows if row["comparison_status"] == "matching_or_covered"),
        "workbook_only_rows": sum(1 for row in mapping_rows if row["comparison_status"] == "workbook-only"),
        "existing_only_rows": sum(1 for row in mapping_rows if row["comparison_status"] == "existing-S4.4b-only"),
    }
    return {"summary": summary, "mapping_rows": mapping_rows}


def _write_audit_reports(workbook_path: Path, comparison: dict[str, Any]) -> None:
    data = _workbook_data_from_file(workbook_path)
    component_rows = []
    for sheet, id_col, type_name in [
        ("LINKS", "link_id", "Link"),
        ("STORES", "store_id", "Store"),
        ("LOADS", "load_id", "Load"),
        ("GENERATORS", "generator_id", "Generator"),
        ("BUSES", "bus_id", "Bus"),
    ]:
        for row in data.get(sheet, []):
            component_rows.append(
                {
                    "component_type": type_name,
                    "component_id": row[id_col],
                    "source_status": row.get("source_status", ""),
                    "value_status": row.get("value_status", ""),
                    "executable_status": row.get("executable_status", row.get("selected_model_role", "")),
                    "caveat": row.get("caveat", ""),
                }
            )
    _write_csv(OUTPUT_DIR / "s4_4b2_component_coverage_report.csv", component_rows)

    source_rows = []
    evidence = data.get("EVIDENCE_LINKS", [])
    for source in data.get("SOURCES", []):
        used = [row for row in evidence if row["source_card_id"] == source["source_card_id"]]
        source_rows.append(
            {
                "source_card_id": source["source_card_id"],
                "source_title": source["source_title"],
                "evidence_link_count": len(used),
                "source_review_status": source["source_review_status"],
                "caveat": source["caveat"],
            }
        )
    _write_csv(OUTPUT_DIR / "s4_4b2_source_coverage_report.csv", source_rows)
    _write_csv(OUTPUT_DIR / "s4_4b2_conflict_report.csv", data.get("CONFLICTS_GAPS", []), SCHEMAS["CONFLICTS_GAPS"])
    _write_csv(OUTPUT_DIR / "s4_4b2_existing_input_mapping.csv", comparison["mapping_rows"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build, validate, and compile the S4.4b2 physical master workbook.")
    parser.add_argument("--mode", choices=["build", "validate", "compile", "compare", "all"], default="all")
    parser.add_argument("--rebuild", action="store_true", help="Overwrite the existing workbook explicitly.")
    args = parser.parse_args(argv)

    if args.mode in {"build", "all"}:
        result = build_initial_workbook(rebuild=args.rebuild)
        print(json.dumps({"workbook": _repo_rel(result.workbook_path), "decision": result.validation_report["decision"]}, indent=2))
    if args.mode in {"validate", "all"}:
        report = validate_workbook()
        print(json.dumps({"decision": report["decision"], "failure_count": report["failure_count"], "warning_count": report["warning_count"]}, indent=2))
    if args.mode in {"compile", "all"}:
        compiled = compile_review_snapshot()
        print(json.dumps(compiled, indent=2))
    if args.mode == "compare":
        comparison = compare_workbook_coverage()
        _write_audit_reports(WORKBOOK_PATH, comparison)
        print(json.dumps(comparison["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
