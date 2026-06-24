from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.governance import (
    PROMOTION_DECISION_TEMPLATE,
    S2_ARTIFACT_INVENTORY_AND_DIRECTORY_AUDIT_PATH,
    S2_CONFIGURATION_ASSET_AND_ASSUMPTION_SUMMARY_MEMO,
    S2_CONFIGURATION_ASSET_ASSUMPTION_MATRIX_PATH,
    S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT_MEMO,
    S2_TO_S3_INPUT_CONTRACT_REGISTER_PATH,
    S3_ENTRY_GATE_CHECKLIST_PATH,
    load_s2_candidate_review,
    validate_s2_candidate_review,
)

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"


def _load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_s211_freeze_artifacts_exist_and_validate():
    assert S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT_MEMO.exists()
    assert S2_CONFIGURATION_ASSET_AND_ASSUMPTION_SUMMARY_MEMO.exists()
    assert S2_ARTIFACT_INVENTORY_AND_DIRECTORY_AUDIT_PATH.exists()
    assert S2_CONFIGURATION_ASSET_ASSUMPTION_MATRIX_PATH.exists()
    assert S2_TO_S3_INPUT_CONTRACT_REGISTER_PATH.exists()
    assert S3_ENTRY_GATE_CHECKLIST_PATH.exists()

    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)
    assert payload["s2_material_flow_freeze_memo_present"] is True
    assert payload["s2_configuration_asset_summary_memo_present"] is True
    assert payload["s2_artifact_inventory_rows_checked"] == 54
    assert payload["s2_configuration_asset_assumption_rows_checked"] == 26
    assert payload["s2_to_s3_contract_rows_checked"] == 14
    assert payload["s3_entry_gate_rows_checked"] == 13


def test_s211_artifact_audit_and_asset_matrix_preserve_non_thesis_and_first_buffer_limits():
    artifact_audit = _load_csv(S2_ARTIFACT_INVENTORY_AND_DIRECTORY_AUDIT_PATH)
    asset_matrix = _load_csv(S2_CONFIGURATION_ASSET_ASSUMPTION_MATRIX_PATH)

    assert len(artifact_audit) == 54
    assert artifact_audit["thesis_usability"].str.lower().eq("false").all()
    generated_row = artifact_audit.loc[artifact_audit["artifact_id"].eq("GENERATED_SMOKE_RUN_POLICY")].iloc[0]
    assert generated_row["should_be_committed"].lower() == "false"
    assert "generated" in generated_row["source_or_generated"].lower()

    assert len(asset_matrix) == 26
    assert asset_matrix["thesis_usability"].str.lower().eq("false").all()
    active_first_buffer = set(
        asset_matrix.loc[
            asset_matrix["active_in_first_buffer_model"].str.lower().eq("true"),
            "asset_id",
        ]
    )
    assert active_first_buffer == {"c0_hot_metal_buffer", "c1_hot_metal_buffer", "c1_dri_hdri_buffer"}
    blocked_assets = asset_matrix.loc[
        asset_matrix["asset_id"].isin(
            {
                "c0_slab_wip_buffer",
                "c1_slab_wip_buffer",
                "c0_hot_slab_transfer_buffer",
                "c1_hot_slab_transfer_buffer",
                "c0_excluded_bulk_stocks",
                "c1_excluded_bulk_stocks",
            }
        )
    ]
    assert blocked_assets["active_in_s2_lp"].str.lower().eq("false").all()


def test_s211_s3_contract_and_gate_checklist_keep_scope_limited():
    contract = _load_csv(S2_TO_S3_INPUT_CONTRACT_REGISTER_PATH)
    checklist = _load_csv(S3_ENTRY_GATE_CHECKLIST_PATH)

    assert len(contract) == 14
    assert contract["thesis_usability_status"].str.lower().eq("false").all()
    active_store_row = contract.loc[contract["input_or_artifact"].eq("active_stores")].iloc[0]
    assert "c0_hot_metal_buffer" in active_store_row["required_guard"]
    assert "c1_dri_hdri_buffer" in active_store_row["required_guard"]

    blocked_store_row = contract.loc[contract["input_or_artifact"].eq("blocked_stores")].iloc[0]
    assert blocked_store_row["may_s3_consume"] == "reference_only"
    assert "activate" in blocked_store_row["forbidden_use_in_s3"].lower()

    assert len(checklist) == 13
    assert checklist.loc[
        checklist["gate_name"].eq("S3_scope_limited_to_energy_cost_emissions_first"),
        "pass_fail_or_blocked",
    ].iloc[0] == "pass_with_scope_limit"
    assert checklist.loc[
        checklist["gate_name"].eq("no_DA_stochastic_mfrr_in_S3_0"),
        "pass_fail_or_blocked",
    ].iloc[0] == "pass_with_scope_limit"


def test_s211_memos_record_s3_contract_boundary_and_non_thesis_status():
    freeze_text = S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT_MEMO.read_text(encoding="utf-8").lower()
    asset_text = S2_CONFIGURATION_ASSET_AND_ASSUMPTION_SUMMARY_MEMO.read_text(encoding="utf-8").lower()

    assert "what s3 may consume" in freeze_text
    assert "what s3 must not reinterpret" in freeze_text
    assert "red flags that must block s3 if violated" in freeze_text
    assert "thesis_usability=false" in freeze_text

    for phrase in (
        "assets/process units in c0",
        "assets/process units in c1",
        "which stores are active",
        "which stores are blocked/deferred",
    ):
        assert phrase in asset_text


def test_s211_zero_row_approved_surface_and_template_remain_intact():
    assert len(PROMOTION_DECISION_TEMPLATE.read_text(encoding="utf-8").strip().splitlines()) == 1
    for csv_path in APPROVED_INPUT_ROOT.glob("*.csv"):
        assert len(csv_path.read_text(encoding="utf-8").strip().splitlines()) == 1
