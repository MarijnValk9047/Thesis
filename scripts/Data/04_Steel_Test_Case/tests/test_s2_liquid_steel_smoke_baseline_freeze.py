from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.governance import (
    LIQUID_STEEL_INFEASIBILITY_ATTRIBUTION_PATH,
    LIQUID_STEEL_SMOKE_BASELINE_FREEZE_MEMO,
    LIQUID_STEEL_SMOKE_BASELINE_SUMMARY_PATH,
    PROMOTION_DECISION_TEMPLATE,
    S2_NEXT_SCOPE_GATE_REGISTER_PATH,
    load_s2_candidate_review,
    validate_s2_candidate_review,
)

REVIEW_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_candidate_review"
APPROVED_INPUT_ROOT = TEST_CASE_ROOT.parents[2] / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "s2_approved_model_input"


def _load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_s29e_freeze_artifacts_exist_and_validate():
    assert LIQUID_STEEL_SMOKE_BASELINE_FREEZE_MEMO.exists()
    assert LIQUID_STEEL_SMOKE_BASELINE_SUMMARY_PATH.exists()
    assert LIQUID_STEEL_INFEASIBILITY_ATTRIBUTION_PATH.exists()
    assert S2_NEXT_SCOPE_GATE_REGISTER_PATH.exists()

    review_bundle = load_s2_candidate_review(REVIEW_ROOT)
    payload = validate_s2_candidate_review(review_bundle)
    assert payload["liquid_steel_smoke_baseline_freeze_memo_present"] is True
    assert payload["liquid_steel_smoke_baseline_rows_checked"] == 4
    assert payload["liquid_steel_smoke_infeasibility_attribution_rows_checked"] == 2
    assert payload["liquid_steel_next_scope_gate_rows_checked"] == 9


def test_s29e_baseline_summary_keeps_non_thesis_restricted_smoke_status():
    frame = _load_csv(LIQUID_STEEL_SMOKE_BASELINE_SUMMARY_PATH)
    assert len(frame) == 4
    assert {"C0_current_BF_BOF_reference", "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"} == set(frame["configuration_id"])
    assert {"feasible_smoke", "stress_infeasible_original"} == set(frame["target_variant"])
    assert frame["thesis_usability"].str.lower().eq("false").all()
    assert frame["approved_input_used"].str.lower().eq("false").all()
    assert frame["shortfall_slack_active"].str.lower().eq("false").all()
    assert frame["inventory_active"].str.lower().eq("false").all()
    assert frame["downstream_active"].str.lower().eq("false").all()
    assert frame["input_surface"].eq("s2_provisional_dev_input").all()
    assert frame["objective_type"].eq("minimise_overproduction_dev_only").all()

    feasible = frame.loc[frame["target_variant"].eq("feasible_smoke")]
    stress = frame.loc[frame["target_variant"].eq("stress_infeasible_original")]
    assert feasible["solve_status"].eq("optimal").all()
    assert stress["solve_status"].eq("infeasible").all()


def test_s29e_infeasibility_attribution_and_gate_register_capture_blockers():
    attribution = _load_csv(LIQUID_STEEL_INFEASIBILITY_ATTRIBUTION_PATH)
    gates = _load_csv(S2_NEXT_SCOPE_GATE_REGISTER_PATH)

    assert len(attribution) == 2
    assert attribution["thesis_usability"].str.lower().eq("false").all()
    assert attribution["target_variant"].eq("stress_infeasible_original").all()
    c1_row = attribution.loc[attribution["configuration_id"].eq("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF")].iloc[0]
    assert "dri_to_eaf" in c1_row["likely_primary_cause"].lower()

    assert len(gates) == 9
    assert gates["current_status"].eq("blocked").all()
    assert "dev_only_store_capacity_translation" in set(gates["gate_name"])
    assert "s3_energy_cost_emissions_entry" in set(gates["gate_name"])


def test_s29e_zero_row_approved_surface_and_template_remain_intact():
    assert len(PROMOTION_DECISION_TEMPLATE.read_text(encoding="utf-8").strip().splitlines()) == 1
    for csv_path in APPROVED_INPUT_ROOT.glob("*.csv"):
        assert len(csv_path.read_text(encoding="utf-8").strip().splitlines()) == 1
