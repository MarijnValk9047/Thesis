from __future__ import annotations

import inspect
from pathlib import Path
import re
import sys

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.config import load_config
from steel.governance import (
    APPROVED_INPUT_FILE_SPECS,
    PROMOTION_PROTOCOL_FILE_SPECS,
    PROMOTION_REVIEW_CRITERIA_FILE_SPECS,
    PROMOTION_DECISION_TEMPLATE_COLUMNS,
    SCHEMA_ALIGNMENT_REQUIRED_GATE_NAMES,
    dry_run_validate_input_governance,
    load_s2_approved_model_input,
    load_s2_candidate_mapping,
    load_s2_candidate_review,
    load_s2_schema,
    load_s2_schema_alignment,
    validate_s2_approved_model_input,
    validate_s2_schema_alignment,
)

CONFIG_PATH = TEST_CASE_ROOT / "configs" / "candidate_review_toy_parse_only.yaml"
SCHEMA_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_schema"
MAPPING_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_mapping"
REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"

FORBIDDEN_EXECUTABLE_SCOPE_PATTERN = re.compile(
    r"phase 2|phase2|phase_2|phase 3|phase3|phase_3|full_hydrogen|on_site_electrolysis|"
    r"hydrogen_production|hydrogen_storage|saf|ccs|da_bidding|stochastic|mfrr|cvar|product_revenue|order_book|"
    r"d_only|d\+4|d_plus_4|wag",
    re.IGNORECASE,
)


def test_schema_alignment_register_exists_and_covers_required_builder_gates():
    alignment_bundle = load_s2_schema_alignment(REVIEW_ROOT)
    payload = validate_s2_schema_alignment(alignment_bundle)
    alignment = alignment_bundle.tables["s2_builder_input_schema_alignment.csv"]

    assert payload["schema_alignment_rows_checked"] == 15
    assert payload["schema_alignment_required_gate_count"] == len(SCHEMA_ALIGNMENT_REQUIRED_GATE_NAMES)
    assert set(alignment["builder_input_gate_name"]) == SCHEMA_ALIGNMENT_REQUIRED_GATE_NAMES
    assert alignment["executable_status"].eq("non_executable").all()
    assert alignment["thesis_usability"].astype(str).str.lower().eq("false").all()

    validation_row = alignment.loc[alignment["builder_input_gate_name"].eq("validation_targets")].iloc[0]
    assert validation_row["approval_status"] == "blocked"
    assert "validation_target_as_constraint" in validation_row["forbidden_status"]

    annual_rows = alignment.loc[
        alignment["builder_input_gate_name"].isin({"process_bounds", "production_targets", "validation_targets"})
    ]
    assert annual_rows["approval_blocker"].str.lower().str.contains("annual").all()
    assert annual_rows["approval_blocker"].str.lower().str.contains("hourly").all()


def test_approved_input_shell_folder_exists_and_tables_are_header_only():
    approved_input_bundle = load_s2_approved_model_input(APPROVED_INPUT_ROOT)
    payload = validate_s2_approved_model_input(approved_input_bundle)

    assert payload["approved_input_tables_checked"] == len(APPROVED_INPUT_FILE_SPECS)
    assert payload["approved_input_total_rows"] == 0
    assert payload["approved_input_approved_rows"] == 0
    assert payload["approved_input_thesis_grade_numerical_rows"] == 0
    assert payload["approved_input_executable_rows"] == 0
    assert payload["approved_input_readme_present"] is True

    for filename, required_columns in APPROVED_INPUT_FILE_SPECS.items():
        path = APPROVED_INPUT_ROOT / filename
        assert path.exists()
        raw_lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(raw_lines) == 1

        frame = approved_input_bundle.tables[filename]
        assert list(frame.columns) == required_columns
        assert len(frame) == 0
        assert {"source_ids", "approval_status", "executable_status", "thesis_usability", "approved_by", "approval_date"}.issubset(
            frame.columns
        )

    assert "constraint_usage_status" in approved_input_bundle.tables["validation_targets.csv"].columns
    assert "annual_to_hourly_translation_status" in approved_input_bundle.tables["process_bounds.csv"].columns
    assert "annual_to_hourly_translation_status" in approved_input_bundle.tables["production_targets.csv"].columns


def test_dry_run_validator_reports_alignment_and_empty_approved_input_surface():
    config = load_config(CONFIG_PATH)
    schema_bundle = load_s2_schema(SCHEMA_ROOT)
    mapping_bundle = load_s2_candidate_mapping(MAPPING_ROOT)
    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    alignment_bundle = load_s2_schema_alignment(REVIEW_ROOT)
    approved_input_bundle = load_s2_approved_model_input(APPROVED_INPUT_ROOT)

    payload = dry_run_validate_input_governance(
        config=config,
        schema_bundle=schema_bundle,
        mapping_bundle=mapping_bundle,
        review_bundle=review_bundle,
        alignment_bundle=alignment_bundle,
        approved_input_bundle=approved_input_bundle,
    )

    assert payload["input_mode"] == "candidate_review"
    assert payload["schema_alignment_rows_checked"] == 15
    assert payload["approved_input_tables_checked"] == 9
    assert payload["approved_input_total_rows"] == 0
    assert payload["approved_input_approved_rows"] == 0
    assert payload["approved_input_thesis_grade_numerical_rows"] == 0
    assert payload["approved_input_executable_rows"] == 0
    assert payload["promotion_protocol_memo_present"] is True
    assert payload["promotion_protocol_rows_checked"] == 18
    assert payload["promotion_review_criteria_files_checked"] == len(PROMOTION_REVIEW_CRITERIA_FILE_SPECS)
    assert payload["promotion_decision_template_rows"] == 0
    assert payload["human_review_packet_files_checked"] == 3
    assert payload["human_review_packet_rows_checked"] == 7
    assert payload["human_review_packet_dashboard_present"] is True
    assert payload["human_review_packet_memos_present"] == 3
    assert payload["human_policy_bundle_memo_present"] is True
    assert payload["human_policy_decision_rows_checked"] == 26
    assert payload["future_parameter_review_backlog_rows_checked"] == 12
    assert payload["numerical_review_packet_files_checked"] == 3
    assert payload["numerical_review_packet_rows_checked"] == 15
    assert payload["numerical_review_packet_dashboard_present"] is True
    assert payload["numerical_review_packet_memos_present"] == 3
    assert payload["minimal_numerical_policy_bundle_memo_present"] is True
    assert payload["minimal_numerical_policy_decision_rows_checked"] == 27
    assert payload["early_sensitivity_screening_plan_rows_checked"] == 5
    assert payload["dev_input_readiness_memo_present"] is True
    assert payload["provisional_dev_input_files_checked"] == 11
    assert payload["provisional_dev_input_index_rows_checked"] == 9
    assert payload["provisional_dev_input_approved_rows"] == 0
    assert payload["provisional_dev_input_thesis_usable_rows"] == 0
    assert payload["target_capacity_reconciliation_audit_rows_checked"] == 4
    assert payload["liquid_steel_smoke_baseline_freeze_memo_present"] is True
    assert payload["liquid_steel_smoke_baseline_rows_checked"] == 4
    assert payload["liquid_steel_smoke_infeasibility_attribution_rows_checked"] == 2
    assert payload["liquid_steel_next_scope_gate_rows_checked"] == 9
    assert payload["approved_rows"] == 0
    assert payload["thesis_grade_numerical_rows"] == 0
    assert payload["candidate_review_executable_rows"] == 0


def test_promotion_protocol_and_template_exist_and_remain_non_executable():
    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    protocol = review_bundle.tables[next(iter(PROMOTION_PROTOCOL_FILE_SPECS))]
    decision_template = (REVIEW_ROOT / "s2_promotion_decision_template.csv").read_text(encoding="utf-8").strip().splitlines()

    assert len(protocol) >= 18
    assert protocol["executable_status"].eq("non_executable").all()
    assert protocol["thesis_usability"].astype(str).str.lower().eq("false").all()
    assert protocol["approval_status"].isin({"protocol_only", "not_approved", "blocked"}).all()
    assert protocol["user_review_required"].astype(str).str.lower().eq("true").all()
    assert protocol["executable_gate_required"].astype(str).str.lower().eq("true").all()
    assert protocol["codex_may_decide"].astype(str).str.lower().eq("false").all() if "codex_may_decide" in protocol.columns else True

    assert len(decision_template) == 1
    assert decision_template[0].split(",") == PROMOTION_DECISION_TEMPLATE_COLUMNS


def test_new_governance_surface_stays_non_pyomo_and_out_of_blocked_scope():
    governance_source = inspect.getsource(sys.modules["steel.governance"]).lower()
    assert "pyomo" not in governance_source
    assert "build_model(" not in governance_source

    alignment_text = (REVIEW_ROOT / "s2_builder_input_schema_alignment.csv").read_text(encoding="utf-8").lower()
    approved_readme_text = (APPROVED_INPUT_ROOT / "README.md").read_text(encoding="utf-8").lower()
    protocol_text = (REVIEW_ROOT / "s2_approved_input_promotion_protocol.csv").read_text(encoding="utf-8").lower()

    assert "create a pyomo" not in approved_readme_text
    assert "balance equations" not in approved_readme_text
    assert "variables, constraints, objectives" not in approved_readme_text
    assert "pyomo" not in protocol_text

    for table_name, frame in load_s2_approved_model_input(APPROVED_INPUT_ROOT).tables.items():
        joined_columns = " ".join(frame.columns).lower()
        assert not FORBIDDEN_EXECUTABLE_SCOPE_PATTERN.search(table_name.lower())
        assert not FORBIDDEN_EXECUTABLE_SCOPE_PATTERN.search(joined_columns)

    allowed_alignment_hits = {"validation_targets", "production_targets", "process_bounds"}
    for row in load_s2_schema_alignment(REVIEW_ROOT).tables["s2_builder_input_schema_alignment.csv"].to_dict(orient="records"):
        row_text = " ".join(str(value).lower() for value in row.values())
        if row["builder_input_gate_name"] in allowed_alignment_hits:
            continue
        assert not FORBIDDEN_EXECUTABLE_SCOPE_PATTERN.search(row_text)
