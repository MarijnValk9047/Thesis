from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.governance import (
    S3_0B_ACTIVITY_PROFILE_PROVENANCE_POLICY_PATH,
    S3_0B_FIXED_ACTIVITY_PROFILE_INPUT_SCHEMA_PATH,
    S3_0B_FIXED_PROFILE_WAG_DIAGNOSTIC_CONTRACT_PATH,
    S3_0B_FIXED_PROFILE_WAG_DIAGNOSTIC_INPUT_AND_CONTRACT_MEMO,
    S3_0B_WAG_COEFFICIENT_REQUIREMENT_REGISTER_PATH,
    S3_0B_WAG_DIAGNOSTIC_CALCULATION_CONTRACT_PATH,
    S3_0B_WAG_DIAGNOSTIC_OUTPUT_SCHEMA_PATH,
    S3_0B_WAG_POLICY_FREEZE_AND_DEV_INPUT_SELECTION_MEMO,
    S3_ACCOUNTING_DESIGN_MEMO,
    S3_ACCOUNTING_INPUT_SCHEMA_PATH,
    S3_ACCOUNTING_STATUS_AND_REVIEW_POLICY_PATH,
    S3_APPROVED_MODEL_INPUT_ROOT,
    S3_CANDIDATE_REVIEW_ROOT,
    S3_EVIDENCE_USE_AND_THESIS_ASSUMPTION_POLICY_MEMO,
    S3_EVIDENCE_USE_TIER_VOCABULARY_PATH,
    S3_ENERGY_COST_EMISSIONS_PARAMETER_UNIVERSE_PATH,
    S3_MATERIAL_PARAMETER_SENSITIVITY_MANDATE_PATH,
    S3_MODEL_INPUT_USE_STATUS_VOCABULARY_PATH,
    S3_REQUIRED_MAPPING_OBJECTS,
    S3_PROVISIONAL_DEV_INPUT_ROOT,
    S3_REQUIRED_EVIDENCE_TIERS,
    S3_REQUIRED_MODEL_USE_STATUSES,
    S3_REQUIRED_SENSITIVITY_PARAMETER_FAMILIES,
    SOURCE_EVIDENCE_FILE_SPECS,
    SOURCE_EVIDENCE_README_PATH,
    SOURCE_EVIDENCE_ROOT,
    STEEL_CANDIDATE_PARAMETER_EVIDENCE_REGISTER_PATH,
    STEEL_EVIDENCE_DUPLICATE_KEY_POLICY_PATH,
    STEEL_EVIDENCE_STATUS_VOCABULARY_PATH,
    STEEL_SOURCE_CARD_REGISTER_PATH,
    STEEL_SOURCE_TO_PARAMETER_MAPPING_POLICY_PATH,
    S3_WAG_DEV_INPUT_SELECTION_REVIEW_COLUMNS,
    S3_WAG_DEV_INPUT_SELECTION_REVIEW_PATH,
    S3_WAG_POLICY_DECISION_COLUMNS,
    S3_WAG_POLICY_DECISION_REGISTER_PATH,
    S3_WAG_SELECTED_DEV_INPUTS_COLUMNS,
    S3_WAG_SELECTED_DEV_INPUTS_PATH,
    S3_WAG_SENSITIVITY_PLAN_COLUMNS,
    S3_WAG_SENSITIVITY_PLAN_PATH,
    S3_THESIS_ASSUMPTION_ACCEPTANCE_POLICY_PATH,
    S3_0B_REQUIRED_ACTIVITY_PROFILE_FIELDS,
    S3_0B_REQUIRED_CALCULATION_STEPS,
    S3_0B_REQUIRED_OUTPUT_FIELDS,
    S3_0B_REQUIRED_PROVENANCE_AREAS,
    S3_0B_REQUIRED_WAG_COEFFICIENT_FAMILIES,
    S3_REQUIRED_PARAMETER_FAMILIES,
    S3_TO_S2_S212_MAPPING_REGISTER_PATH,
    load_steel_source_evidence,
    load_s3_accounting_governance,
    validate_s3_evidence_use_policy,
    validate_s3_thesis_assumption_candidates,
    validate_steel_source_evidence,
    validate_s3_accounting_governance,
    validate_s3_wag_policy_freeze,
)


def _load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_s3_accounting_design_surfaces_exist_and_validate():
    assert S3_ACCOUNTING_DESIGN_MEMO.exists()
    assert S3_0B_FIXED_PROFILE_WAG_DIAGNOSTIC_INPUT_AND_CONTRACT_MEMO.exists()
    for directory in (S3_CANDIDATE_REVIEW_ROOT, S3_PROVISIONAL_DEV_INPUT_ROOT, S3_APPROVED_MODEL_INPUT_ROOT):
        assert directory.exists()
        assert (directory / "README.md").exists()

    for path in (
        S3_ENERGY_COST_EMISSIONS_PARAMETER_UNIVERSE_PATH,
        S3_TO_S2_S212_MAPPING_REGISTER_PATH,
        S3_ACCOUNTING_INPUT_SCHEMA_PATH,
        S3_ACCOUNTING_STATUS_AND_REVIEW_POLICY_PATH,
        S3_0B_FIXED_PROFILE_WAG_DIAGNOSTIC_CONTRACT_PATH,
        S3_0B_FIXED_ACTIVITY_PROFILE_INPUT_SCHEMA_PATH,
        S3_0B_ACTIVITY_PROFILE_PROVENANCE_POLICY_PATH,
        S3_0B_WAG_COEFFICIENT_REQUIREMENT_REGISTER_PATH,
        S3_0B_WAG_DIAGNOSTIC_CALCULATION_CONTRACT_PATH,
        S3_0B_WAG_DIAGNOSTIC_OUTPUT_SCHEMA_PATH,
        S3_EVIDENCE_USE_TIER_VOCABULARY_PATH,
        S3_MODEL_INPUT_USE_STATUS_VOCABULARY_PATH,
        S3_THESIS_ASSUMPTION_ACCEPTANCE_POLICY_PATH,
        S3_MATERIAL_PARAMETER_SENSITIVITY_MANDATE_PATH,
    ):
        assert path.exists()

    payload = validate_s3_accounting_governance(load_s3_accounting_governance())
    assert payload["s3_accounting_design_memo_present"] is True
    assert payload["s3_candidate_review_files_checked"] == 14
    assert payload["s3_parameter_universe_rows_checked"] == 28
    assert payload["s3_mapping_register_rows_checked"] == 22
    assert payload["s3_accounting_schema_rows_checked"] == 23
    assert payload["s3_status_policy_rows_checked"] == 8
    assert payload["s3_0b_contract_rows_checked"] == 11
    assert payload["s3_0b_a_contract_memo_present"] is True
    assert payload["s3_0b_activity_profile_schema_rows_checked"] == 20
    assert payload["s3_0b_provenance_policy_rows_checked"] == 8
    assert payload["s3_0b_wag_coefficient_requirement_rows_checked"] == 14
    assert payload["s3_0b_calculation_contract_rows_checked"] == 11
    assert payload["s3_0b_output_schema_rows_checked"] == 38
    assert payload["s3_approved_input_csv_rows"] == 0
    assert payload["s3_approved_input_bad_rows"] == 0
    assert payload["source_evidence_files_checked"] == 5
    assert payload["steel_source_card_rows_checked"] == 29
    assert payload["steel_candidate_parameter_evidence_rows_checked"] == 82
    assert payload["steel_source_to_parameter_policy_rows_checked"] == 11
    assert payload["steel_evidence_status_vocabulary_rows_checked"] == 13
    assert payload["steel_evidence_duplicate_key_policy_rows_checked"] == 7
    assert payload["s3_wag_policy_freeze_memo_present"] is True
    assert payload["s3_wag_policy_decision_rows_checked"] == 14
    assert payload["s3_wag_dev_selection_review_rows_checked"] == 42
    assert payload["s3_wag_selected_dev_input_rows_checked"] == 22
    assert payload["s3_wag_sensitivity_plan_rows_checked"] == 7
    assert payload["s3_wag_accepted_dev_rows"] == 27
    assert payload["s3_wag_accepted_sensitivity_rows"] == 9
    assert payload["s3_wag_suspicious_or_blocked_rows"] == 5
    assert payload["s3_wag_unresolved_missing_evidence_rows"] == 9
    assert payload["s3_wag_midpoint_modelling_assumption_rows"] == 10
    assert payload["s3_evidence_use_policy_memo_present"] is True
    assert payload["s3_evidence_tier_rows_checked"] == 7
    assert payload["s3_model_use_status_rows_checked"] == 6
    assert payload["s3_thesis_assumption_policy_rows_checked"] == 8
    assert payload["s3_material_sensitivity_mandate_rows_checked"] == 15


def test_s3_evidence_use_policy_tiers_statuses_and_sensitivity_mandate_validate():
    assert S3_EVIDENCE_USE_AND_THESIS_ASSUMPTION_POLICY_MEMO.exists()
    tier_vocab = _load_csv(S3_EVIDENCE_USE_TIER_VOCABULARY_PATH)
    status_vocab = _load_csv(S3_MODEL_INPUT_USE_STATUS_VOCABULARY_PATH)
    sensitivity = _load_csv(S3_MATERIAL_PARAMETER_SENSITIVITY_MANDATE_PATH)

    payload = validate_s3_evidence_use_policy(load_s3_accounting_governance())
    assert payload["s3_evidence_tier_rows_checked"] == 7
    assert payload["s3_model_use_status_rows_checked"] == 6
    assert payload["s3_material_sensitivity_mandate_rows_checked"] == 15
    assert set(tier_vocab["evidence_tier"]) == S3_REQUIRED_EVIDENCE_TIERS
    assert set(status_vocab["model_use_status"]) == S3_REQUIRED_MODEL_USE_STATUSES
    assert set(sensitivity["parameter_family"]) == S3_REQUIRED_SENSITIVITY_PARAMETER_FAMILIES

    non_a = tier_vocab.loc[~tier_vocab["evidence_tier"].eq("A")]
    assert non_a["tata_exact_claim_allowed"].str.lower().eq("false").all()
    assert tier_vocab.loc[tier_vocab["evidence_tier"].eq("B"), "thesis_model_assumption_eligible"].iloc[0].lower() == "true"
    assert tier_vocab.loc[tier_vocab["evidence_tier"].eq("C"), "thesis_model_assumption_eligible"].iloc[0].lower() == "true"
    assert tier_vocab.loc[tier_vocab["evidence_tier"].eq("D"), "source_card_required"].iloc[0].lower() == "false"
    assert tier_vocab.loc[tier_vocab["evidence_tier"].eq("X"), "blocked"].iloc[0].lower() == "true"


def _base_s3_assumption_row(**overrides: str) -> dict[str, str]:
    row = {
        "row_id": "synthetic_policy_case",
        "evidence_tier": "B",
        "source_locator_quality": "complete",
        "model_use_status": "thesis_model_assumption",
        "source_card_ids": "STEEL-SC-0001",
        "source_locator": "table 1",
        "unit": "MWh/t",
        "activity_basis": "per tonne product",
        "energy_basis": "",
        "selected_value": "1.0",
        "tata_exact_claim_allowed": "false",
        "thesis_validation_claim_eligible": "false",
        "limitations": "Public generic assumption; not Tata-exact.",
        "sensitivity_required": "true",
        "sensitivity_class": "material_parameter",
        "sensitivity_review_status": "planned",
        "sensitivity_deferred_reason": "",
        "basis_conversion_required": "false",
        "basis_conversion_note": "",
        "formula": "",
        "input_parameter_ids": "",
        "user_decision_record": "",
        "scenario_policy_basis": "",
        "feasible_envelope_or_modelling_rationale": "",
        "technology_applicability_note": "",
        "main_caveat": "Immediate public source is secondary literature.",
        "source_provenance_class": "public_secondary",
        "zero_value_status": "not_zero",
        "evidence_confidentiality": "public",
        "empirical_claim_status": "declared_assumption_not_validation",
        "material_parameter_family": "DRP natural-gas consumption",
    }
    row.update(overrides)
    return row


def test_s3_thesis_assumption_policy_allows_tiers_a_to_e_under_requirements():
    rows = [
        _base_s3_assumption_row(
            row_id="tier_a_primary",
            evidence_tier="A",
            main_caveat="",
            material_parameter_family="non_material_public_anchor",
            tata_exact_claim_allowed="true",
            thesis_validation_claim_eligible="true",
            empirical_claim_status="site_specific_public_assumption",
            sensitivity_required="false",
            sensitivity_review_status="",
        ),
        _base_s3_assumption_row(row_id="tier_b_secondary"),
        _base_s3_assumption_row(
            row_id="tier_c_generic",
            evidence_tier="C",
            main_caveat="",
            technology_applicability_note="Applies to generic DRP/EAF technology range.",
            source_provenance_class="generic_technology_public",
            material_parameter_family="EAF electricity consumption",
            sensitivity_review_status="complete",
        ),
        _base_s3_assumption_row(
            row_id="tier_d_user_policy",
            evidence_tier="D",
            model_use_status="thesis_model_sensitivity",
            source_card_ids="",
            source_locator="",
            source_locator_quality="not_required_for_user_policy",
            user_decision_record="User selected C1 central route-share scenario.",
            scenario_policy_basis="central low high C1 route-share sensitivity design.",
            feasible_envelope_or_modelling_rationale="Inside S2 feasible route-share envelope.",
            main_caveat="",
            material_parameter_family="C1 route share",
            source_provenance_class="user_selected_scenario_policy",
        ),
        _base_s3_assumption_row(
            row_id="tier_e_derived",
            evidence_tier="E",
            model_use_status="derived_assumption",
            formula="mwh_per_t_steel = mwh_per_t_dri * dri_per_t_steel",
            input_parameter_ids="input_drp_electricity;input_dri_yield",
            basis_conversion_required="true",
            basis_conversion_note="Converted from tonne DRI to tonne steel using explicit yield.",
            main_caveat="Derived from source-backed generic inputs.",
            material_parameter_family="DRI pellets yield conversion",
            sensitivity_review_status="complete",
        ),
    ]
    payload = validate_s3_thesis_assumption_candidates(pd.DataFrame(rows))

    assert payload["s3_thesis_assumption_candidate_rows_checked"] == 5
    assert payload["s3_thesis_assumption_candidate_rows_accepted"] == 5
    assert payload["s3_thesis_assumption_final_rows"] == 5
    assert payload["s3_thesis_assumption_derived_rows"] == 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source_provenance_class": "research_memo_only"}, "blocked source provenance"),
        ({"source_provenance_class": "ai_generated_parameter"}, "blocked source provenance"),
        ({"source_locator": "", "source_locator_quality": "missing"}, "complete source locator"),
        ({"source_provenance_class": "generated_run_output"}, "blocked source provenance"),
        ({"selected_value": "0", "zero_value_status": "hidden_zero_placeholder"}, "hidden placeholder"),
        ({"basis_conversion_required": "true", "basis_conversion_note": ""}, "basis conversion"),
        (
            {
                "evidence_tier": "A",
                "main_caveat": "",
                "material_parameter_family": "non_material_public_anchor",
                "evidence_confidentiality": "redacted",
                "tata_exact_claim_allowed": "true",
                "empirical_claim_status": "exact_tata_truth",
                "thesis_validation_claim_eligible": "true",
                "sensitivity_required": "false",
                "sensitivity_review_status": "",
            },
            "confidential or redacted",
        ),
        ({"tata_exact_claim_allowed": "true"}, "Tata-exact"),
        ({"sensitivity_review_status": "", "sensitivity_required": "false"}, "sensitivity"),
        ({"model_use_status": "blocked"}, "blocked evidence tier"),
    ],
)
def test_s3_thesis_assumption_policy_blocks_invalid_cases(overrides: dict[str, str], message: str):
    row = _base_s3_assumption_row(**overrides)
    with pytest.raises(ValueError, match=message):
        validate_s3_thesis_assumption_candidates(pd.DataFrame([row]))


def test_steel_source_evidence_bootstrap_surfaces_exist_and_validate():
    assert SOURCE_EVIDENCE_ROOT.exists()
    assert SOURCE_EVIDENCE_README_PATH.exists()
    for path in (
        STEEL_SOURCE_CARD_REGISTER_PATH,
        STEEL_CANDIDATE_PARAMETER_EVIDENCE_REGISTER_PATH,
        STEEL_SOURCE_TO_PARAMETER_MAPPING_POLICY_PATH,
        STEEL_EVIDENCE_STATUS_VOCABULARY_PATH,
        STEEL_EVIDENCE_DUPLICATE_KEY_POLICY_PATH,
    ):
        assert path.exists()

    bundle = load_steel_source_evidence()
    assert set(bundle.tables) == set(SOURCE_EVIDENCE_FILE_SPECS)
    for filename, columns in SOURCE_EVIDENCE_FILE_SPECS.items():
        assert list(bundle.tables[filename].columns) == columns

    payload = validate_steel_source_evidence(bundle)
    assert payload["source_evidence_directory_present"] is True
    assert payload["steel_source_card_rows_checked"] == 29
    assert payload["steel_candidate_parameter_evidence_rows_checked"] == 82
    assert payload["steel_source_orphan_reference_count"] == 0
    assert payload["steel_candidate_approved_or_executable_rows"] == 0

    source_cards = bundle.tables["steel_source_card_register.csv"]
    athanasiadis = source_cards.loc[source_cards["source_card_id"].eq("STEEL-SC-0021")].iloc[0]
    assert athanasiadis["locator_complete"].lower() == "true"
    assert athanasiadis["eligible_for_candidate_evidence"].lower() == "true"
    assert athanasiadis["eligible_for_dev_input_review"].lower() == "true"
    assert athanasiadis["source_review_status"] == "human_verified_tier_b_locator_complete_for_eaf_and_ng_drp_tables"


def test_steel_source_evidence_policies_block_invalid_primary_and_locator_use():
    bundle = load_steel_source_evidence()
    mapping_policy = bundle.tables["steel_source_to_parameter_mapping_policy.csv"]
    status_vocabulary = bundle.tables["steel_evidence_status_vocabulary.csv"]
    duplicate_policy = bundle.tables["steel_evidence_duplicate_key_policy.csv"]

    assert set(mapping_policy["policy_id"]) == {f"STEEL-EVID-POL-{index:03d}" for index in range(1, 12)}
    assert mapping_policy["required"].str.lower().eq("true").all()
    assert mapping_policy["blocked_if_violated"].str.lower().eq("true").all()
    assert {
        "research_memo_boundary",
        "stable_locator_policy",
        "source_duplicate_control",
        "parameter_duplicate_control",
    }.issubset(set(mapping_policy["policy_area"]))

    approved_status = status_vocabulary.loc[
        status_vocabulary["status_name"].eq("approved_model_input")
    ].iloc[0]
    assert approved_status["allowed_for_source_card"].lower() == "false"
    assert approved_status["allowed_for_parameter_evidence"].lower() == "false"

    assert set(duplicate_policy["key_id"]) == {f"STEEL-EVID-DUP-{index:03d}" for index in range(1, 8)}
    assert {"source_card", "parameter_evidence"}.issubset(set(duplicate_policy["object_type"]))


def test_s3_wag_policy_freeze_and_dev_selection_packet_validate():
    assert S3_0B_WAG_POLICY_FREEZE_AND_DEV_INPUT_SELECTION_MEMO.exists()
    for path in (
        S3_WAG_POLICY_DECISION_REGISTER_PATH,
        S3_WAG_DEV_INPUT_SELECTION_REVIEW_PATH,
        S3_WAG_SELECTED_DEV_INPUTS_PATH,
        S3_WAG_SENSITIVITY_PLAN_PATH,
    ):
        assert path.exists()

    policy = _load_csv(S3_WAG_POLICY_DECISION_REGISTER_PATH)
    selection = _load_csv(S3_WAG_DEV_INPUT_SELECTION_REVIEW_PATH)
    selected_inputs = _load_csv(S3_WAG_SELECTED_DEV_INPUTS_PATH)
    sensitivity = _load_csv(S3_WAG_SENSITIVITY_PLAN_PATH)

    assert list(policy.columns) == S3_WAG_POLICY_DECISION_COLUMNS
    assert list(selection.columns) == S3_WAG_DEV_INPUT_SELECTION_REVIEW_COLUMNS
    assert list(selected_inputs.columns) == S3_WAG_SELECTED_DEV_INPUTS_COLUMNS
    assert list(sensitivity.columns) == S3_WAG_SENSITIVITY_PLAN_COLUMNS

    payload = validate_s3_wag_policy_freeze()
    assert payload["s3_wag_policy_decision_rows_checked"] == 14
    assert payload["s3_wag_dev_selection_review_rows_checked"] == 42
    assert payload["s3_wag_selected_dev_input_rows_checked"] == 22
    assert payload["s3_wag_sensitivity_plan_rows_checked"] == 7
    assert payload["s3_wag_executable_sensitivity_rows"] == 7
    assert payload["s3_wag_selected_currently_loaded_rows"] == 22
    assert payload["s3_wag_selection_review_loader_eligible"] is False

    assert policy["policy_status"].eq("frozen_for_s3_0b").all()
    assert policy["codex_may_change"].str.lower().eq("false").all()
    assert policy["thesis_usability"].str.lower().eq("false").all()

    accepted = selection.loc[selection["accepted_for_dev_use"].str.lower().eq("true")]
    assert accepted["suspicious_flag"].str.lower().eq("false").all()
    assert accepted["source_locator_complete"].str.lower().eq("true").all()
    assert accepted["human_review_required"].str.lower().eq("false").all()
    assert selected_inputs["development_only"].str.lower().eq("true").all()
    assert selected_inputs["approval_status"].eq("accepted_for_development_only").all()
    assert selected_inputs["currently_loaded"].str.lower().eq("true").all()
    assert selected_inputs["thesis_usability"].str.lower().eq("false").all()
    assert ~selected_inputs["source_card_ids"].str.contains("STEEL-SC-0019", regex=False).any()
    assert ~sensitivity["sensitivity_group"].str.lower().str.contains("hierarchy").any()
    assert sensitivity.loc[
        sensitivity["eligible_for_execution"].str.lower().eq("true"),
        ["low_input_id", "central_input_id", "high_input_id"],
    ].ne("").all().all()


def test_s3_parameter_universe_is_non_executable_and_blocks_later_logic():
    parameter_universe = _load_csv(S3_ENERGY_COST_EMISSIONS_PARAMETER_UNIVERSE_PATH)

    assert set(parameter_universe["parameter_family"]) == S3_REQUIRED_PARAMETER_FAMILIES
    assert parameter_universe["thesis_usability"].str.lower().eq("false").all()
    assert parameter_universe["may_be_executable_in_s3_0a"].str.lower().eq("false").all()
    assert parameter_universe["may_be_approved_input_in_s3_0a"].str.lower().eq("false").all()

    blocked = set(parameter_universe.loc[parameter_universe["parameter_family"].str.startswith("blocked_"), "parameter_family"])
    assert blocked == {
        "blocked_da_price_parameter",
        "blocked_stochastic_parameter",
        "blocked_cvar_parameter",
        "blocked_mfrr_parameter",
        "blocked_product_revenue_parameter",
        "blocked_downstream_flexibility_parameter",
        "blocked_new_store_parameter",
    }


def test_s3_mapping_cannot_mutate_s2_or_create_new_activity_or_stores():
    mapping = _load_csv(S3_TO_S2_S212_MAPPING_REGISTER_PATH)

    assert mapping["thesis_usability"].str.lower().eq("false").all()
    assert mapping["may_change_source_object"].str.lower().eq("false").all()
    assert mapping["may_create_new_activity_variable"].str.lower().eq("false").all()
    assert mapping["may_create_new_store"].str.lower().eq("false").all()
    assert mapping["may_drive_objective_in_s3_0a"].str.lower().eq("false").all()

    assert set(mapping["s3_accounting_object"]) == S3_REQUIRED_MAPPING_OBJECTS


def test_s3_schema_and_status_policy_require_review_before_execution():
    schema = _load_csv(S3_ACCOUNTING_INPUT_SCHEMA_PATH)
    status_policy = _load_csv(S3_ACCOUNTING_STATUS_AND_REVIEW_POLICY_PATH)

    required_fields = {
        "source_id",
        "source_status",
        "evidence_class",
        "review_status",
        "approval_status",
        "thesis_usability",
        "codex_may_decide",
        "reviewer_decision_required",
        "allowed_stage",
        "blocked_reason",
    }
    required_rows = schema.loc[schema["field_name"].isin(required_fields)]
    assert set(required_rows["field_name"]) == required_fields
    assert required_rows["required"].str.lower().eq("true").all()

    assert status_policy["may_be_used_in_loader"].str.lower().eq("false").all()
    assert status_policy["may_be_used_in_objective"].str.lower().eq("false").all()
    assert status_policy["may_be_used_in_thesis_run"].str.lower().eq("false").all()
    assert set(status_policy["status_name"]) == {
        "candidate_governance_only",
        "candidate_value_unreviewed",
        "provisional_dev_only",
        "validation_target_only",
        "sensitivity_only",
        "approved_model_input",
        "blocked",
        "deferred_future_stage",
    }


def test_s30b_contract_remains_fixed_profile_diagnostic_only():
    contract = _load_csv(S3_0B_FIXED_PROFILE_WAG_DIAGNOSTIC_CONTRACT_PATH)
    joined_rows = contract.astype(str).agg(" ".join, axis=1).str.lower()

    assert contract["thesis_usability"].str.lower().eq("false").all()
    for blocked_phrase in (
        "generated_run_folder_as_canonical_source",
        "da_price_files_or_forecast_artifacts",
        "price_responsive_dispatch_or_arbitrage",
        "wag_export_contract_or_power_market_revenue",
        "model_objective_or_dispatch_solver",
        "settlement_or_export_revenue",
    ):
        assert joined_rows.str.contains(blocked_phrase, regex=False).any()


def test_s30b_activity_profile_schema_requires_provenance_units_and_utc():
    schema = _load_csv(S3_0B_FIXED_ACTIVITY_PROFILE_INPUT_SCHEMA_PATH)

    assert set(schema["field_name"]) == S3_0B_REQUIRED_ACTIVITY_PROFILE_FIELDS
    required_fields = {
        "configuration_id",
        "timestamp_utc",
        "timestep_hours",
        "activity_unit",
        "source_artifact_id",
        "source_artifact_path",
        "source_artifact_hash",
        "review_status",
        "thesis_usability",
    }
    required_rows = schema.loc[schema["field_name"].isin(required_fields)]
    assert set(required_rows["field_name"]) == required_fields
    assert required_rows["required"].str.lower().eq("true").all()

    joined_rows = schema.astype(str).agg(" ".join, axis=1).str.lower()
    assert joined_rows.str.contains("generated run folder", regex=False).any()
    thesis_row = schema.loc[schema["field_name"].eq("thesis_usability")].iloc[0]
    assert thesis_row["allowed_values_or_format"].lower() == "false"


def test_s30b_provenance_policy_blocks_generated_runs_and_market_fields():
    policy = _load_csv(S3_0B_ACTIVITY_PROFILE_PROVENANCE_POLICY_PATH)
    joined_rows = policy.astype(str).agg(" ".join, axis=1).str.lower()

    assert set(policy["policy_area"]) == S3_0B_REQUIRED_PROVENANCE_AREAS
    assert policy["thesis_usability"].str.lower().eq("false").all()
    for blocked_phrase in (
        "generated_run_folder_as_canonical_source_blocked",
        "da_price_fields_blocked",
        "stochastic_scenario_fields_blocked",
        "product_revenue_or_order_book_fields_blocked",
        "settlement_fields_blocked",
        "s2_freeze_mutation_blocked",
    ):
        assert joined_rows.str.contains(blocked_phrase, regex=False).any()


def test_s30b_wag_coefficient_requirements_are_non_approved_and_complete():
    requirements = _load_csv(S3_0B_WAG_COEFFICIENT_REQUIREMENT_REGISTER_PATH)

    assert set(requirements["coefficient_family"]) == S3_0B_REQUIRED_WAG_COEFFICIENT_FAMILIES
    assert requirements["thesis_usability"].str.lower().eq("false").all()
    assert requirements["may_be_approved_in_s3_0b_a"].str.lower().eq("false").all()

    joined = requirements.astype(str).agg(" ".join, axis=1).str.lower()
    for required_phrase in (
        "bfg",
        "bofg",
        "cog",
        "lower heating value",
        "conversion or interface efficiency",
        "flare spill",
        "natural-gas displacement",
        "no-double-counting",
    ):
        assert joined.str.contains(required_phrase, regex=False).any()


def test_s30b_calculation_contract_is_contract_only_in_s30b_a():
    contract = _load_csv(S3_0B_WAG_DIAGNOSTIC_CALCULATION_CONTRACT_PATH)

    assert set(contract["step_name"]) == S3_0B_REQUIRED_CALCULATION_STEPS
    assert contract["thesis_usability"].str.lower().eq("false").all()
    assert contract["allowed_in_s3_0b_a"].str.lower().eq("false").all()
    assert contract["may_use_price_signal"].str.lower().eq("false").all()
    assert contract["may_optimise_objective"].str.lower().eq("false").all()
    assert contract["may_create_revenue"].str.lower().eq("false").all()


def test_s30b_output_schema_blocks_price_settlement_and_revenue_fields():
    schema = _load_csv(S3_0B_WAG_DIAGNOSTIC_OUTPUT_SCHEMA_PATH)

    assert set(schema["field_name"]) == S3_0B_REQUIRED_OUTPUT_FIELDS
    forbidden_field_tokens = ("price", "settlement", "revenue")
    assert not [
        field
        for field in schema["field_name"]
        if any(token in field.lower() for token in forbidden_field_tokens)
    ]

    joined = schema.astype(str).agg(" ".join, axis=1).str.lower()
    for blocked_phrase in ("da price field", "settlement", "revenue"):
        assert joined.str.contains(blocked_phrase, regex=False).any()
    thesis_row = schema.loc[schema["field_name"].eq("thesis_usability")].iloc[0]
    assert thesis_row["allowed_values_or_format"].lower() == "false"
