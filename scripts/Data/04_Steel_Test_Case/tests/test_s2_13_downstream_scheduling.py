from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
import pytest
from pyomo.environ import value

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.downstream_scheduling_builder import (  # noqa: E402
    DownstreamCaseOptions,
    build_downstream_scheduling_model,
)
from steel.downstream_scheduling_inputs import load_downstream_assumptions  # noqa: E402
from steel.downstream_scheduling_runner import (  # noqa: E402
    DEFAULT_RESULT_REGISTER,
    required_smoke_cases,
    run_required_smoke_suite,
    solve_downstream_case,
)
from steel.governance import (  # noqa: E402
    PROVISIONAL_DEV_INPUT_ROOT,
    load_s2_candidate_review,
    validate_s2_candidate_review,
)
from steel.liquid_steel_smoke_builder import build_liquid_steel_smoke_model  # noqa: E402


S2_REVIEW_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S2/s2_candidate_review"
S3_FIXED_PROFILE_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input/fixed_profiles"
SELECTED_INPUT_PATH = PROVISIONAL_DEV_INPUT_ROOT / "s2_13_downstream_selected_dev_inputs.csv"
TOPOLOGY_REGISTER = S2_REVIEW_ROOT / "s2_13_downstream_topology_and_sequence_register.csv"
PARAMETER_REVIEW = S2_REVIEW_ROOT / "s2_13_downstream_parameter_selection_review.csv"
STAGE_GATE = S2_REVIEW_ROOT / "s2_13_downstream_stage_gate_checklist.csv"
PROFILE_PATHS = (
    S3_FIXED_PROFILE_ROOT / "c0_s2_13_downstream_profile_24h_dev.csv",
    S3_FIXED_PROFILE_ROOT / "c1_central_s2_13_downstream_profile_24h_dev.csv",
)


def _csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


@pytest.fixture(scope="module")
def smoke_payload() -> dict:
    return run_required_smoke_suite(write_outputs=False)


def test_s2_13_governed_inputs_and_registers_exist_with_required_schema():
    required_input_columns = {
        "input_id",
        "configuration_scope",
        "asset",
        "parameter_name",
        "selected_value",
        "selected_lower",
        "selected_upper",
        "unit",
        "activity_basis",
        "source_card_ids",
        "candidate_evidence_ids",
        "evidence_tier",
        "model_use_status",
        "selection_method",
        "sensitivity_required",
        "tata_exact_claim_allowed",
        "thesis_validation_claim_eligible",
        "limitations",
        "notes",
    }
    selected = _csv(SELECTED_INPUT_PATH)
    assert required_input_columns.issubset(selected.columns)
    assert selected["tata_exact_claim_allowed"].str.lower().eq("false").all()
    assert selected["thesis_validation_claim_eligible"].str.lower().eq("false").all()
    tier_d = selected.loc[selected["evidence_tier"].str.startswith("D_")]
    assert not tier_d.empty
    assert tier_d["sensitivity_required"].str.lower().eq("true").all()

    for path in (TOPOLOGY_REGISTER, PARAMETER_REVIEW, DEFAULT_RESULT_REGISTER, STAGE_GATE):
        assert path.exists()
        assert not _csv(path).empty


def test_s2_13_governance_validator_reports_artifacts():
    payload = validate_s2_candidate_review(load_s2_candidate_review(S2_REVIEW_ROOT))
    assert payload["s2_13_downstream_selected_input_rows_checked"] > 0
    assert payload["s2_13_downstream_topology_rows_checked"] > 0
    assert payload["s2_13_downstream_smoke_result_rows_checked"] >= 5
    assert payload["s2_13_downstream_stage_gate_rows_checked"] >= 14
    assert payload["s2_13_downstream_modules_present"] is True


def test_frozen_liquid_steel_core_remains_unchanged_when_extension_is_not_active():
    c0 = build_liquid_steel_smoke_model(configuration_id="C0_current_BF_BOF_reference", horizon_hours=24)
    c1 = build_liquid_steel_smoke_model(configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", horizon_hours=24)

    assert c0.s2_model_stats.variables == 49
    assert c0.s2_model_stats.binaries == 0
    assert c0.s2_model_stats.constraints == 122
    assert c1.s2_model_stats.variables == 97
    assert c1.s2_model_stats.binaries == 0
    assert c1.s2_model_stats.constraints == 242
    assert c0.s2_metadata["downstream_scope_active"] is False
    assert c1.s2_metadata["downstream_scope_active"] is False


def test_downstream_model_topology_and_forbidden_slack_are_explicit():
    model = build_downstream_scheduling_model(
        configuration_id="C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
        horizon_hours=24,
        case_options=DownstreamCaseOptions(smoke_case_id="unit_topology"),
    )
    component_names = set(model.component_map().keys())
    required_components = {
        "secondary_metallurgy_input",
        "secondary_metallurgy_output",
        "caster_input",
        "cast_slab_output",
        "hot_slab_age_inventory_balance",
        "hot_slab_expiry_to_cold_yard",
        "cold_slab_inventory_balance",
        "reheated_slab_queue_balance",
        "dsp_hot_slab_input",
        "hsm_hot_slab_input",
        "hsm_reheated_slab_input",
        "final_product_output",
        "final_product_target",
    }
    assert required_components.issubset(component_names)
    assert not any("shortfall" in name.lower() and "metadata" not in name.lower() for name in component_names)
    assert model.s2_13_metadata["shortfall_slack_active"] is False
    assert model.s2_13_metadata["market_logic_active"] is False
    assert model.s2_13_metadata["thesis_usability"] is False


def test_required_smoke_cases_have_expected_outcomes(smoke_payload: dict):
    rows = {row["smoke_case"]: row for row in smoke_payload["results"]}
    assert smoke_payload["all_required_outcomes_met"] is True
    assert set(rows) == {case.smoke_case for case in required_smoke_cases()}

    for case_id in ("c0_base_downstream", "c1_central_downstream", "recoverable_hsm_outage"):
        row = rows[case_id]
        assert row["termination_condition"] == "optimal"
        assert abs(float(row["final_product_output_t"]) - float(row["final_product_target_t"])) <= 1e-6
        assert float(row["dsp_output_t"]) == pytest.approx(0.20 * float(row["final_product_target_t"]), abs=1e-6)
        assert float(row["terminal_cold_slab_deviation_t"]) == pytest.approx(0.0, abs=1e-8)
        assert float(row["terminal_hot_slab_t"]) == pytest.approx(0.0, abs=1e-8)
        assert float(row["terminal_reheated_queue_t"]) == pytest.approx(0.0, abs=1e-8)
        assert row["shortfall_slack_present"] == "false"

    assert rows["cold_slab_anti_free_battery"]["termination_condition"] == "infeasible"
    assert rows["cold_slab_anti_free_battery"]["infeasibility_class"] == "cold_slab_reheating_disabled_bypass_blocked"
    assert rows["hard_target_stress_infeasible"]["termination_condition"] == "infeasible"


def test_recoverable_outage_uses_buffering_and_reheating(smoke_payload: dict):
    outage = next(row for row in smoke_payload["results"] if row["smoke_case"] == "recoverable_hsm_outage")
    assert float(outage["reheated_t"]) > 0.0
    assert float(outage["hot_charge_t"]) < float(outage["final_product_output_t"])
    assert float(outage["max_cold_slab_inventory_t"]) + 1e-6 >= float(outage["dsp_output_t"])
    assert float(outage["max_material_balance_residual_t"]) <= 1e-6


def test_c1_route_shares_preserved_in_solved_downstream_case():
    case = next(case for case in required_smoke_cases() if case.smoke_case == "c1_central_downstream")
    row, model = solve_downstream_case(case)
    assert row["termination_condition"] == "optimal"
    assert model is not None
    bof_total = sum(value(model.bof_liquid_steel_output[t]) for t in model.TIME)
    eaf_total = sum(value(model.eaf_liquid_steel_output[t]) for t in model.TIME)
    total = bof_total + eaf_total
    assert bof_total / total == pytest.approx(0.61, abs=1e-8)
    assert eaf_total / total == pytest.approx(0.39, abs=1e-8)


def test_profiles_are_governed_snapshots_with_reproducible_hashes():
    required_columns = {
        "timestamp_utc",
        "source_model_stage",
        "profile_content_hash",
        "profile_extraction_method",
        "s2_13_assumption_set_id",
        "route_share_policy",
        "final_product_output_t",
        "continuous_casting_electricity_driver_t",
        "reheating_fuel_heat_driver_t",
        "hsm_electricity_driver_t",
        "hot_charge_tonnage_t",
        "cold_charge_reheated_tonnage_t",
        "wag_compatible_reheating_fuel_demand_hook_t",
        "thesis_usability",
        "limitations",
    }
    for path in PROFILE_PATHS:
        profile = _csv(path)
        assert len(profile) == 24
        assert required_columns.issubset(profile.columns)
        assert profile["timestamp_utc"].str.endswith("Z").all()
        assert profile["source_model_stage"].eq("S2.13_downstream_scheduling_extension").all()
        assert profile["thesis_usability"].str.lower().eq("false").all()
        assert profile["limitations"].str.contains("no prices", case=False).all()
        stored_hashes = set(profile["profile_content_hash"])
        assert len(stored_hashes) == 1
        rows = profile.to_dict(orient="records")
        digest = hashlib.sha256(
            json.dumps(
                [{k: str(v) for k, v in row.items() if k != "profile_content_hash"} for row in rows],
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        assert stored_hashes == {digest}


def test_stage_gate_records_pass_after_smoke_validation():
    gates = _csv(STAGE_GATE)
    assert gates["pass_fail_or_blocked"].eq("pass").all()
    assert set(gates["gate_id"]) >= {f"S213_GATE_{idx:03d}" for idx in range(1, 15)}
