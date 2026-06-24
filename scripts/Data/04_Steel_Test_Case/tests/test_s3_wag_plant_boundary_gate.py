from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.wag_diagnostic import run_c1_component_energy_diagnostic  # noqa: E402
from steel.wag_diagnostic_inputs import load_fixed_activity_profile, load_selected_wag_inputs  # noqa: E402
from steel.wag_fixed_profile_builder import C1_PROFILE_FILENAMES, C1_ROUTE_SCENARIOS  # noqa: E402


S3_REVIEW_ROOT = (
    REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S3" / "s3_candidate_review"
)
S3_DEV_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S3" / "s3_provisional_dev_input"
FIXED_PROFILE_DIR = S3_DEV_ROOT / "fixed_profiles"
BOUNDARY_POLICY = S3_REVIEW_ROOT / "s3_energy_boundary_policy_register.csv"
COST_DA_READINESS = S3_REVIEW_ROOT / "s3_cost_da_integration_readiness_register.csv"
C1_READINESS = S3_REVIEW_ROOT / "s3_c1_scenario_wag_readiness_register.csv"
C1_ENERGY_INPUTS = S3_DEV_ROOT / "s3_c1_route_energy_inputs.csv"


def _csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _flatten_keys(payload: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            keys.add(str(key).lower())
            keys.update(_flatten_keys(value))
    elif isinstance(payload, list):
        for value in payload:
            keys.update(_flatten_keys(value))
    return keys


def test_energy_boundary_policy_register_freezes_component_only_as_non_financial():
    policy = _csv(BOUNDARY_POLICY)
    assert set(policy["boundary_name"]) == {
        "component_only_lower_bound",
        "scaled_public_site_electricity_anchor_sensitivity",
        "component_plus_residual_site_load_assumption",
        "full_component_accounting_boundary",
    }
    component = policy.loc[policy["boundary_name"].eq("component_only_lower_bound")].iloc[0]
    assert component["plant_level_interpretation_allowed"].lower() == "false"
    assert component["cost_integration_allowed"].lower() == "false"
    assert component["da_market_integration_allowed"].lower() == "false"

    scaled = policy.loc[policy["boundary_name"].eq("scaled_public_site_electricity_anchor_sensitivity")].iloc[0]
    assert scaled["sensitivity_required"].lower() == "true"
    assert scaled["cost_integration_allowed"].lower() == "false"

    full = policy.loc[policy["boundary_name"].eq("full_component_accounting_boundary")].iloc[0]
    assert "downstream" in full["included_loads_or_sinks"]
    assert "heat/steam" in full["included_loads_or_sinks"]
    assert full["plant_level_interpretation_allowed"].lower() == "true"


def test_cost_da_readiness_register_blocks_current_c0_c1_plant_interpretation():
    readiness = _csv(COST_DA_READINESS)
    assert set(readiness["scenario_id"]) == {"c0_reference", *C1_ROUTE_SCENARIOS.keys()}
    c1_rows = readiness.loc[readiness["configuration_id"].eq("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF")]
    assert c1_rows["diagnostic_level"].eq("component_energy_boundary_diagnostic").all()
    assert c1_rows["component_zero_import_warning"].str.lower().eq("true").all()
    assert c1_rows["plant_level_import_interpretation_ready"].str.lower().eq("false").all()
    assert c1_rows["plant_level_cost_accounting_ready"].str.lower().eq("false").all()
    assert c1_rows["da_market_integration_ready"].str.lower().eq("false").all()
    assert c1_rows["gross_ets_ready"].str.lower().eq("false").all()
    assert c1_rows["blocking_reason"].str.contains("Zero residual component import").all()


def test_c1_readiness_rows_flag_zero_import_without_cost_or_da_readiness():
    readiness = _csv(C1_READINESS)
    assert readiness["diagnostic_allowed"].eq("component_energy_boundary_diagnostic").all()
    assert readiness["component_zero_import_warning"].str.lower().eq("true").all()
    assert readiness["plant_level_import_interpretation_ready"].str.lower().eq("false").all()
    assert readiness["plant_level_cost_accounting_ready"].str.lower().eq("false").all()
    assert readiness["da_market_integration_ready"].str.lower().eq("false").all()
    assert readiness["plant_level_power_offset_interpretation_ready"].str.lower().eq("false").all()
    assert readiness["wag_offset_interpretation_status"].str.contains("not_actual_dispatch").all()


def test_c1_component_diagnostic_output_contains_boundary_safeguards_and_no_market_fields():
    selected = load_selected_wag_inputs()
    forbidden = {"export", "revenue", "settlement", "da_price", "gross_ets_cost", "route_optimisation"}
    for filename in C1_PROFILE_FILENAMES.values():
        rows = load_fixed_activity_profile(FIXED_PROFILE_DIR / filename)
        diagnostic = run_c1_component_energy_diagnostic(selected_inputs=selected, profile_rows=rows)
        component = diagnostic["component_energy"]
        assert diagnostic["diagnostic_level"] == "component_energy_boundary_diagnostic"
        assert diagnostic["component_boundary_only"] is True
        assert diagnostic["component_zero_import_warning"] is True
        assert diagnostic["plant_level_import_interpretation_ready"] is False
        assert diagnostic["plant_level_power_offset_interpretation_ready"] is False
        assert diagnostic["plant_level_cost_accounting_ready"] is False
        assert diagnostic["cost_integration_ready"] is False
        assert diagnostic["da_market_integration_ready"] is False
        assert diagnostic["potential_wag_offset_capped_by_represented_component_electricity"] is True
        assert component["potential_net_import_offset_mwh"] <= component["component_electricity_demand_before_wag_offset_mwh"] + 1e-6
        assert component["residual_component_grid_import_mwh"] >= 0.0
        assert forbidden.isdisjoint(_flatten_keys(diagnostic))


def test_s3_0d_gate_does_not_change_route_shares_or_drp_eaf_coefficients():
    assert C1_ROUTE_SCENARIOS["c1_high_drp_eaf"] == {"bf_bof_share": 0.55, "drp_eaf_share": 0.45}
    assert C1_ROUTE_SCENARIOS["c1_central"] == {"bf_bof_share": 0.61, "drp_eaf_share": 0.39}
    assert C1_ROUTE_SCENARIOS["c1_low_drp_eaf"] == {"bf_bof_share": 0.68, "drp_eaf_share": 0.32}

    energy = _csv(C1_ENERGY_INPUTS)
    values = {row["parameter_name"]: row["selected_value"] for _, row in energy.iterrows()}
    assert values["ng_drp_natural_gas_consumption"] == "195"
    assert values["ng_drp_electricity_consumption"] == "0.1"
    assert values["eaf_electricity_consumption"] == "0.5"
    assert values["ng_drp_pellets_to_dri_efficiency"] == "0.74"
    assert values["eaf_dri_to_crude_steel_efficiency"] == "0.95"
