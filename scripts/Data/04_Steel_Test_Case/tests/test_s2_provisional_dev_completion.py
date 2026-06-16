from __future__ import annotations

import inspect
from pathlib import Path
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

import steel.governance as governance_module
from steel.governance import (
    DEV_INPUT_READINESS_MEMO,
    BUFFER_ACTIVATION_READINESS_PATH,
    PROCESS_BOUND_TRANSLATION_AUDIT_PATH,
    PROVISIONAL_DEV_INPUT_ROOT,
    PROVISIONAL_DEV_VALUE_COMPLETION_AUDIT_PATH,
    STORE_CAPACITY_TRANSLATION_AUDIT_PATH,
    load_s2_provisional_dev_input,
    validate_s2_provisional_dev_input,
)

APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"
PROMOTION_TEMPLATE = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review" / "s2_promotion_decision_template.csv"

BLOCKED_EXECUTABLE_TERMS = (
    "phase 2",
    "phase 3",
    "full hydrogen",
    "on-site electrolysis",
    "hydrogen production",
    "hydrogen storage",
    "saf",
    "ccs",
    "d-only",
    "d+4",
    "da bidding",
    "stochastic",
    "mfrr",
    "cvar",
    "product revenue",
    "order book",
)


def _load_dev_table(filename: str) -> pd.DataFrame:
    return pd.read_csv(PROVISIONAL_DEV_INPUT_ROOT / filename, dtype=str, keep_default_na=False)


def test_s28b_completion_audit_exists_and_validation_reports_it():
    assert PROVISIONAL_DEV_VALUE_COMPLETION_AUDIT_PATH.exists()
    assert PROCESS_BOUND_TRANSLATION_AUDIT_PATH.exists()
    assert STORE_CAPACITY_TRANSLATION_AUDIT_PATH.exists()
    assert BUFFER_ACTIVATION_READINESS_PATH.exists()

    bundle = load_s2_provisional_dev_input(PROVISIONAL_DEV_INPUT_ROOT)
    payload = validate_s2_provisional_dev_input(bundle)

    assert payload["provisional_dev_value_completion_audit_rows_checked"] == 27
    assert payload["process_bound_translation_audit_rows_checked"] == 10
    assert payload["target_capacity_reconciliation_audit_rows_checked"] == 4
    assert payload["store_capacity_translation_audit_rows_checked"] == 7
    assert payload["buffer_activation_readiness_rows_checked"] == 9
    assert payload["provisional_dev_input_formula_only_rows"] == 13
    assert payload["provisional_dev_input_approved_rows"] == 0
    assert payload["provisional_dev_input_thesis_usable_rows"] == 0
    assert payload["store_capacity_translation_review_memo_present"] is True
    assert payload["store_capacity_dev_executable_rows"] == 3
    assert payload["store_capacity_formula_only_rows"] == 2
    assert payload["store_capacity_excluded_or_deferred_rows"] == 4
    assert payload["buffer_activation_ready_rows"] == 3
    assert payload["process_bound_dev_executable_rows"] == 9
    assert payload["process_bound_non_executable_rows"] == 1


def test_s28b_dev_pack_rows_remain_non_approved_and_non_thesis():
    for csv_path in PROVISIONAL_DEV_INPUT_ROOT.glob("*.csv"):
        frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        if "approval_status" in frame.columns:
            assert not frame["approval_status"].str.lower().eq("approved").any()
        if "thesis_usability" in frame.columns:
            assert frame["thesis_usability"].str.lower().eq("false").all()
        if "executable_status" in frame.columns:
            dev_rows = frame["executable_status"].str.lower().eq("dev_executable_only")
            if dev_rows.any():
                assert frame.loc[dev_rows, "approval_status"].str.lower().eq("provisional_development_only").all()


def test_s28c_process_bounds_have_positive_dev_executable_translations():
    bounds = _load_dev_table("process_bounds.csv")
    dev_rows = bounds["executable_status"].str.lower().eq("dev_executable_only")
    blocked_rows = bounds["executable_status"].str.lower().eq("not_executable")

    assert dev_rows.sum() == 9
    assert blocked_rows.sum() == 1
    assert bounds.loc[dev_rows, "unit"].str.lower().eq("t_per_hour").all()
    assert pd.to_numeric(bounds.loc[dev_rows, "value"], errors="coerce").gt(0).all()
    assert bounds.loc[dev_rows, "value_basis"].str.lower().str.contains("process_class=").all()
    assert bounds.loc[dev_rows, "translation_basis"].str.lower().str.contains("annual_anchor=").all()
    assert bounds.loc[dev_rows, "translation_basis"].str.lower().str.contains("effective_hours=8760").all()
    assert bounds.loc[dev_rows, "translation_basis"].str.lower().str.contains("envelope_case=").all()
    assert bounds.loc[dev_rows, "translation_basis"].str.lower().str.contains("annual_anchor_requires_translation").all()
    assert bounds.loc[blocked_rows, "notes"].str.lower().str.contains("deferred").all()


def test_s28b_conversion_coefficients_are_positive_and_role_explicit():
    coeffs = _load_dev_table("conversion_coefficients.csv")
    assert set(coeffs["coefficient_role"]) == {"output_production", "input_consumption", "yield"}
    numeric_values = pd.to_numeric(coeffs["value"], errors="coerce")
    assert numeric_values.notna().all()
    assert (numeric_values > 0).all()
    assert coeffs["unit"].str.lower().isin(
        {"t_output_per_t_activity", "t_input_per_t_activity", "dimensionless_yield"}
    ).all()
    assert coeffs["notes"].str.lower().str.contains("positive|midpoint|yield|derived").any()


def test_s28b_production_targets_are_horizon_total_and_route_neutral():
    targets = _load_dev_table("production_targets.csv")
    numeric_values = pd.to_numeric(targets["value"], errors="coerce")
    assert numeric_values.notna().all()
    assert (numeric_values > 0).all()
    assert targets["carrier_id"].str.lower().eq("liquid_steel").all()
    assert targets["target_name"].str.lower().str.contains("horizon_total_target").all()
    assert targets["target_variant"].astype(str).str.strip().ne("").all()
    assert targets["value_basis"].str.lower().str.contains("route_neutral").all()
    assert not targets["notes"].str.lower().str.contains("route-specific").any()


def test_s29c_target_variants_are_reconciled_and_guarded():
    targets = _load_dev_table("production_targets.csv")
    audit = pd.read_csv(
        governance_module.TARGET_CAPACITY_RECONCILIATION_AUDIT_PATH,
        dtype=str,
        keep_default_na=False,
    )

    for configuration_id in ("C0_current_BF_BOF_reference", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"):
        config_rows = targets.loc[
            targets["configuration_id"].eq(configuration_id)
            & targets["target_name"].eq("horizon_total_target_24h_debug")
        ]
        assert {"feasible_smoke", "stress_infeasible_original"}.issubset(set(config_rows["target_variant"]))

    feasible_rows = audit.loc[audit["target_variant"].eq("feasible_smoke")].copy()
    stress_rows = audit.loc[audit["target_variant"].eq("stress_infeasible_original")].copy()
    assert (pd.to_numeric(feasible_rows["reconciled_target_t"], errors="coerce") < pd.to_numeric(feasible_rows["max_implied_liquid_steel_t"], errors="coerce")).all()
    assert (pd.to_numeric(stress_rows["reconciled_target_t"], errors="coerce") > pd.to_numeric(stress_rows["max_implied_liquid_steel_t"], errors="coerce")).all()
    assert pd.to_numeric(feasible_rows["target_fraction_of_capacity"], errors="coerce").eq(0.85).all()


def test_s28b_existing_policy_guardrails_remain_intact():
    inventory_text = _load_dev_table("inventory_endpoint_policies.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")
    store_text = _load_dev_table("store_capacities.csv").astype(str).agg(" ".join, axis=1).str.lower().str.cat(sep=" ")

    assert "cyc50" in inventory_text
    assert "not_capacity_approval" in inventory_text
    assert "multi_hour_or_multi_day" in store_text


def test_s28c_readiness_memo_states_restricted_smoke_builder_is_now_possible():
    memo = DEV_INPUT_READINESS_MEMO.read_text(encoding="utf-8").lower()
    assert "smoke solving is now possible" in memo
    assert "restricted first smoke scope" in memo
    assert "store capacities remain relative structures" in memo
    assert "what the next lp-builder prompt may consume" in memo
    assert "what the lp-builder must refuse" in memo


def test_s28b_approved_inputs_and_template_remain_zero_row():
    assert len(PROMOTION_TEMPLATE.read_text(encoding="utf-8").strip().splitlines()) == 1
    for csv_path in APPROVED_INPUT_ROOT.glob("*.csv"):
        assert len(csv_path.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_s28b_surface_stays_non_pyomo_and_blocked_terms_non_executable():
    source = inspect.getsource(governance_module).lower()
    assert "import pyomo" not in source
    assert "from pyomo" not in source
    assert "build_model(" not in source

    combined_text = (
        DEV_INPUT_READINESS_MEMO.read_text(encoding="utf-8").lower()
        + PROVISIONAL_DEV_VALUE_COMPLETION_AUDIT_PATH.read_text(encoding="utf-8").lower()
    )
    for blocked_term in BLOCKED_EXECUTABLE_TERMS:
        if blocked_term in combined_text:
            bundle = load_s2_provisional_dev_input(PROVISIONAL_DEV_INPUT_ROOT)
            for frame in bundle.tables.values():
                if "executable_status" in frame.columns:
                    assert not frame["executable_status"].str.lower().eq("executable").any()
