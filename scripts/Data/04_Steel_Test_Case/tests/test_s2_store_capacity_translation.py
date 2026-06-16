from __future__ import annotations

from pathlib import Path
import inspect
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.governance import (
    BUFFER_ACTIVATION_READINESS_PATH,
    PROMOTION_DECISION_TEMPLATE,
    STORE_CAPACITY_TRANSLATION_AUDIT_PATH,
    STORE_CAPACITY_TRANSLATION_REVIEW_MEMO,
    load_s2_candidate_review,
    load_s2_provisional_dev_input,
    validate_s2_candidate_review,
    validate_s2_provisional_dev_input,
)
from steel import liquid_steel_smoke_builder as smoke_builder_module

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
PROVISIONAL_DEV_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_provisional_dev_input"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"


def _load_dev_table(filename: str) -> pd.DataFrame:
    return pd.read_csv(PROVISIONAL_DEV_INPUT_ROOT / filename, dtype=str, keep_default_na=False)


def test_s210a_store_capacity_artifacts_exist_and_validate():
    assert STORE_CAPACITY_TRANSLATION_REVIEW_MEMO.exists()
    assert STORE_CAPACITY_TRANSLATION_AUDIT_PATH.exists()
    assert BUFFER_ACTIVATION_READINESS_PATH.exists()

    bundle = load_s2_provisional_dev_input(PROVISIONAL_DEV_INPUT_ROOT)
    payload = validate_s2_provisional_dev_input(bundle)
    assert payload["store_capacity_translation_review_memo_present"] is True
    assert payload["store_capacity_translation_audit_rows_checked"] == 7
    assert payload["buffer_activation_readiness_rows_checked"] == 9
    assert payload["store_capacity_dev_executable_rows"] == 3
    assert payload["store_capacity_formula_only_rows"] == 2
    assert payload["buffer_activation_ready_rows"] == 3


def test_s210a_store_capacities_are_bounded_and_non_strategic():
    stores = _load_dev_table("store_capacities.csv")
    dev_rows = stores["executable_status"].str.lower().eq("dev_executable_only")
    formula_rows = stores["value_basis"].str.lower().str.contains("formula")

    assert pd.to_numeric(stores.loc[dev_rows, "value"], errors="coerce").gt(0).all()
    assert stores.loc[dev_rows, "unit"].str.lower().eq("t").all()
    assert stores.loc[formula_rows, "executable_status"].str.lower().eq("not_executable").all()
    assert not stores.astype(str).agg(" ".join, axis=1).str.lower().str.contains("unbounded").any()
    assert stores.loc[stores["store_id"].str.contains("hot_slab", case=False), "notes"].str.lower().str.contains("multi_hour_or_multi_day").all()


def test_s210a_initial_and_terminal_rows_follow_capacity_readiness():
    stores = _load_dev_table("store_capacities.csv")
    initial = _load_dev_table("initial_inventories.csv")
    terminal = _load_dev_table("terminal_inventory_rules.csv")
    endpoint = _load_dev_table("inventory_endpoint_policies.csv")

    for _, store_row in stores.iterrows():
        key = (store_row["configuration_id"], store_row["store_id"])
        initial_row = initial.loc[
            initial["configuration_id"].eq(key[0]) & initial["store_id"].eq(key[1])
        ].iloc[0]
        terminal_row = terminal.loc[
            terminal["configuration_id"].eq(key[0]) & terminal["store_id"].eq(key[1])
        ].iloc[0]
        endpoint_row = endpoint.loc[
            endpoint["configuration_id"].eq(key[0]) & endpoint["store_id"].eq(key[1])
        ].iloc[0]

        if store_row["executable_status"].lower() == "dev_executable_only":
            capacity = float(store_row["value"])
            assert abs(float(initial_row["value"]) - 0.5 * capacity) < 1e-6
            assert terminal_row["value"] == "1.0"
            assert endpoint_row["value"] == "CYC50"
            assert initial_row["executable_status"].lower() == "dev_executable_only"
            assert terminal_row["executable_status"].lower() == "dev_executable_only"
            assert endpoint_row["executable_status"].lower() == "dev_executable_only"
        else:
            assert initial_row["executable_status"].lower() == "not_executable"
            assert terminal_row["executable_status"].lower() == "not_executable"
            assert endpoint_row["executable_status"].lower() == "not_executable"

    inventory_text = endpoint.astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")
    assert "cyc50" in inventory_text
    assert "not_capacity_approval" in inventory_text


def test_s210a_readiness_register_covers_activation_and_exclusions():
    readiness = pd.read_csv(BUFFER_ACTIVATION_READINESS_PATH, dtype=str, keep_default_na=False)
    assert {"hot_metal_buffer", "dri_hdri_surge_buffer", "cold_slab_slab_wip", "hot_slab_wip", "liquid_steel_ladle_tundish", "excluded_scope_stocks"}.issubset(set(readiness["buffer_type"]))
    assert readiness["thesis_usability"].str.lower().eq("false").all()
    assert readiness.loc[readiness["activation_status"].eq("guarded_ready"), "candidate_for_s2_10b_activation"].str.lower().eq("true").all()
    assert readiness.loc[readiness["buffer_type"].eq("excluded_scope_stocks"), "activation_status"].eq("excluded").all()
    assert readiness.loc[readiness["buffer_type"].eq("hot_slab_wip"), "activation_status"].eq("deferred_non_executable").all()


def test_s210a_candidate_review_and_zero_row_surfaces_remain_intact():
    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)
    assert payload["approved_rows"] == 0
    assert payload["thesis_grade_numerical_rows"] == 0
    assert len(PROMOTION_DECISION_TEMPLATE.read_text(encoding="utf-8").strip().splitlines()) == 1
    for csv_path in APPROVED_INPUT_ROOT.glob("*.csv"):
        assert len(csv_path.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_s210a_does_not_introduce_inventory_builder_logic():
    source = inspect.getsource(smoke_builder_module).lower()
    assert "inventory_balance" not in source
    assert "cyc50_constraint" not in source
    assert "store_capacity_activation" not in source
