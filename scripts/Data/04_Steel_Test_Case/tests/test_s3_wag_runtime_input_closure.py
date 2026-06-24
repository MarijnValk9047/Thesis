from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.wag_diagnostic import assess_wag_readiness  # noqa: E402
from steel.wag_diagnostic_inputs import (  # noqa: E402
    DEFAULT_SELECTED_WAG_INPUT_PATH,
    DEFAULT_WAG_DEMAND_COEFFICIENT_PATH,
    load_fixed_activity_profile,
    load_selected_wag_inputs,
    load_wag_demand_coefficients,
)
from steel.wag_fixed_profile_builder import (  # noqa: E402
    C1_PROFILE_FILENAMES,
    evaluate_c1_route_share_identifiability,
    route_share_register_frame,
    stable_frame_hash,
)


S3_CANDIDATE_REVIEW_ROOT = (
    REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S3" / "s3_candidate_review"
)
ROUTE_SHARE_REGISTER = S3_CANDIDATE_REVIEW_ROOT / "s3_c1_route_share_identifiability_register.csv"
RUNTIME_CLOSURE_REGISTER = S3_CANDIDATE_REVIEW_ROOT / "s3_wag_runtime_input_closure_register.csv"
C1_SCENARIO_READINESS_REGISTER = S3_CANDIDATE_REVIEW_ROOT / "s3_c1_scenario_wag_readiness_register.csv"
FIXED_PROFILE_README = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_provisional_dev_input"
    / "fixed_profiles"
    / "README.md"
)
FIXED_PROFILE_PATH = FIXED_PROFILE_README.parent / "c0_wag_fixed_profile_24h_dev.csv"
BUILDER_PATH = TEST_CASE_ROOT / "steel" / "wag_fixed_profile_builder.py"
RUNNER_PATH = TEST_CASE_ROOT / "steel" / "wag_diagnostic_runner.py"
S2_BUILDER_PATH = TEST_CASE_ROOT / "steel" / "liquid_steel_smoke_builder.py"


def test_c1_route_share_identifiability_register_blocks_arbitrary_profile():
    route = pd.read_csv(ROUTE_SHARE_REGISTER, dtype=str, keep_default_na=False)
    assert len(route) == 1
    row = route.iloc[0]
    assert row["configuration_id"] == "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF"
    assert row["route_share_identified"].lower() == "false"
    assert row["blocks_canonical_profile"].lower() == "true"
    assert float(row["max_bf_bof_share"]) - float(row["min_bf_bof_share"]) > float(row["identifiability_tolerance"])
    assert row["selected_profile_share"] == ""


def test_route_share_auxiliary_solve_does_not_modify_s2_builder():
    before = S2_BUILDER_PATH.read_bytes()
    result = evaluate_c1_route_share_identifiability()
    after = S2_BUILDER_PATH.read_bytes()
    assert before == after
    assert result["route_share_identified"] == "false"
    assert result["blocks_canonical_profile"] == "true"
    assert result["max_bf_bof_share"] > result["min_bf_bof_share"]


def test_runtime_closure_keeps_component_inputs_loader_eligible_but_full_c1_blocked():
    closure = pd.read_csv(RUNTIME_CLOSURE_REGISTER, dtype=str, keep_default_na=False)
    unresolved = closure.loc[closure["runtime_ready"].str.lower().eq("false")]
    assert unresolved.empty
    readiness = pd.read_csv(C1_SCENARIO_READINESS_REGISTER, dtype=str, keep_default_na=False)
    assert readiness["diagnostic_allowed"].eq("component_energy_boundary_diagnostic").all()
    assert readiness["full_c1_diagnostic_ready"].str.lower().eq("false").all()
    assert readiness["mandatory_process_demand_ready"].str.lower().eq("false").all()
    assert readiness["steam_boiler_demand_ready"].str.lower().eq("false").all()
    assert closure["thesis_usability"].str.lower().eq("false").all()
    assert closure.loc[
        closure["parameter_or_profile"].eq("c1_bf_bof_route_share"),
        "selection_status",
    ].iloc[0] == "accepted_user_selected_development_scenarios"
    assert closure.loc[
        closure["parameter_or_profile"].eq("c1_bf_bof_route_share"),
        "source_or_profile_id",
    ].iloc[0] == "s3_c1_route_share_policy_register.csv"


def test_demand_coefficient_surface_contains_c0_loader_safe_rows():
    demand = load_wag_demand_coefficients(DEFAULT_WAG_DEMAND_COEFFICIENT_PATH)
    assert len(demand) == 6
    demand_names = {row.demand_name for row in demand.values()}
    assert "c0_coking_underfiring_fuel_demand" in demand_names
    assert "c0_site_electricity_demand_annual_proxy" in demand_names
    frame = pd.read_csv(DEFAULT_WAG_DEMAND_COEFFICIENT_PATH, dtype=str, keep_default_na=False)
    assert len(frame) == 6
    assert frame["thesis_usability"].str.lower().eq("false").all()
    assert frame["eligible_for_s3_0b_loader"].str.lower().eq("true").all()


def test_configuration_readiness_remains_separate_and_blocked():
    selected = load_selected_wag_inputs(DEFAULT_SELECTED_WAG_INPUT_PATH)
    demand = load_wag_demand_coefficients(DEFAULT_WAG_DEMAND_COEFFICIENT_PATH)
    readiness = assess_wag_readiness(selected, demand_coefficients=demand)
    assert readiness.runtime_ready is False
    assert readiness.c0_activity_profile_ready.ready is False
    assert readiness.c1_activity_profile_ready.ready is False
    assert readiness.c0_demand_profile_ready.ready is True
    assert readiness.c1_demand_profile_ready.ready is False
    assert readiness.c0_cog_chain_ready.ready is True
    assert readiness.c1_cog_chain_ready.ready is False
    assert readiness.c0_electricity_cap_ready.ready is False
    assert readiness.c1_electricity_cap_ready.ready is False


def test_fixed_profile_directory_documents_c0_and_c1_wrapper_profiles():
    assert FIXED_PROFILE_README.exists()
    text = FIXED_PROFILE_README.read_text(encoding="utf-8")
    assert "c0_wag_fixed_profile_24h_dev.csv" in text
    assert "C1 has three development-only same-output route/material/WAG-driver profiles" in text
    assert "c0_s2_13_downstream_profile_24h_dev.csv" in text
    assert "c1_central_s2_13_downstream_profile_24h_dev.csv" in text
    fixed_profile_files = {path.name for path in FIXED_PROFILE_README.parent.iterdir() if path.name != "README.md"}
    assert fixed_profile_files == {
        "c0_wag_fixed_profile_24h_dev.csv",
        *set(C1_PROFILE_FILENAMES.values()),
        "c0_s2_13_downstream_profile_24h_dev.csv",
        "c1_central_s2_13_downstream_profile_24h_dev.csv",
    }
    profile_rows = load_fixed_activity_profile(FIXED_PROFILE_PATH)
    assert len(profile_rows) == 456
    assert {row.configuration_id for row in profile_rows} == {"C0_current_BF_BOF_reference"}


def test_route_share_register_hash_is_deterministic_for_same_payload():
    frame = route_share_register_frame(
        {
            "diagnostic_id": "test",
            "configuration_id": "C1_phase1_hybrid_BF_BOF_NG_DRP_EAF",
            "target_case": "fixture",
            "route_share_identified": "false",
            "development_only": "true",
            "thesis_usability": "false",
            "blocks_canonical_profile": "true",
        }
    )
    assert stable_frame_hash(frame) == stable_frame_hash(frame.copy())


def test_fixed_profile_builder_validate_only_writes_no_register(tmp_path: Path):
    output_path = tmp_path / "should_not_write.csv"
    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER_PATH),
            "--validate-only",
            "--route-share-register-path",
            str(output_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert not output_path.exists()
    assert '"writes_enabled": false' in result.stdout


def test_wag_cli_validation_only_loads_c0_demand_rows():
    result = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "--validate-inputs-only"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert '"demand_coefficient_rows_loaded": 6' in result.stdout
    assert '"runtime_ready": false' in result.stdout
