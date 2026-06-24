from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.wag_fixed_profile_builder import C1_PROFILE_FILENAMES, C1_ROUTE_SCENARIOS  # noqa: E402


S3_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "inputs" / "assets" / "steel" / "S3"
S3_REVIEW_ROOT = S3_ROOT / "s3_candidate_review"
S3_DEV_ROOT = S3_ROOT / "s3_provisional_dev_input"
FIXED_PROFILE_DIR = S3_DEV_ROOT / "fixed_profiles"
STATUS_REGISTER = S3_REVIEW_ROOT / "s3_downstream_implementation_status_register.csv"
BOUNDARY_REGISTER = S3_REVIEW_ROOT / "s3_downstream_accounting_boundary_register.csv"
COST_DA_READINESS = S3_REVIEW_ROOT / "s3_cost_da_integration_readiness_register.csv"
C1_READINESS = S3_REVIEW_ROOT / "s3_c1_scenario_wag_readiness_register.csv"
RUNTIME_CLOSURE = S3_REVIEW_ROOT / "s3_wag_runtime_input_closure_register.csv"
C1_ENERGY_INPUTS = S3_DEV_ROOT / "s3_c1_route_energy_inputs.csv"
C0_PROFILE = FIXED_PROFILE_DIR / "c0_wag_fixed_profile_24h_dev.csv"


DOWNSTREAM_ACTIVITY_TYPES = {
    "secondary_metallurgy_output_proxy",
    "continuous_casting_liquid_steel_input",
    "continuous_casting_slab_output_proxy",
    "slab_handling_transfer_proxy",
    "reheating_or_hot_charge_throughput_proxy",
    "hot_strip_mill_throughput_proxy",
    "finished_product_boundary_proxy",
    "oxygen_demand_auxiliary_driver",
    "residual_downstream_auxiliary_boundary_driver",
}


def _csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _profile_paths() -> list[Path]:
    return [C0_PROFILE, *[FIXED_PROFILE_DIR / filename for filename in C1_PROFILE_FILENAMES.values()]]


def test_downstream_status_register_classifies_required_assets_without_overclaiming():
    status = _csv(STATUS_REGISTER)
    required = {
        "secondary_metallurgy",
        "continuous_casting",
        "slab_handling_transfer",
        "direct_sheet_or_direct_slab_processing",
        "reheating_or_hot_charge",
        "hot_strip_mill",
        "downstream_rolling_finishing",
        "asu_oxygen_supply",
        "residual_downstream_auxiliary_electricity",
        "residual_downstream_heat_steam",
    }
    assert required == set(status["asset_or_boundary_id"])
    assert status["thesis_usability"].str.lower().eq("false").all()
    assert not status["implementation_status"].isin({"executable_accounting_present", "full_process_logic_present"}).any()
    assert status.loc[status["asset_or_boundary_id"].eq("direct_sheet_or_direct_slab_processing"), "implementation_status"].iloc[0] == "not_found"
    assert status.loc[status["asset_or_boundary_id"].eq("residual_downstream_heat_steam"), "implementation_status"].iloc[0] == "registered_boundary_only"
    driver_rows = status.loc[status["implementation_status"].eq("profile_driver_present")]
    assert driver_rows["accounting_only_asset"].str.lower().eq("true").all()
    assert driver_rows["flexible_scheduling_asset"].str.lower().eq("false").all()
    assert status["cost_da_ready"].str.lower().eq("false").all()


def test_downstream_accounting_boundary_register_is_driver_only_and_not_cost_ready():
    boundary = _csv(BOUNDARY_REGISTER)
    required = {
        "secondary_metallurgy_accounting",
        "continuous_casting_accounting",
        "slab_handling_or_transfer_accounting",
        "reheating_or_hot_charge_boundary_accounting",
        "hot_strip_mill_accounting",
        "downstream_finished_product_boundary",
        "asu_oxygen_auxiliary_accounting",
        "residual_downstream_auxiliary_electricity_boundary",
        "residual_downstream_heat_steam_boundary",
    }
    assert required == set(boundary["downstream_boundary_id"])
    assert boundary["coefficient_status"].eq("missing_or_proxy_boundary").all()
    assert boundary["model_use_status"].eq("development_only").all()
    assert boundary["cost_da_ready"].str.lower().eq("false").all()
    assert boundary["limitations"].str.lower().str.contains("no ").any()


def test_c0_and_c1_profiles_contain_downstream_drivers_without_energy_coefficients():
    for path in _profile_paths():
        profile = _csv(path)
        assert DOWNSTREAM_ACTIVITY_TYPES.issubset(set(profile["s2_activity_type"]))
        downstream = profile.loc[profile["s2_activity_type"].isin(DOWNSTREAM_ACTIVITY_TYPES)]
        assert len(downstream) == 24 * len(DOWNSTREAM_ACTIVITY_TYPES)
        assert downstream["activity_direction"].eq("accounting_driver").all()
        assert downstream["activity_unit"].eq("t_per_hour").all()
        assert not downstream["activity_unit"].isin({"MWh", "GJ", "GJ_useful"}).any()
        assert downstream["thesis_usability"].str.lower().eq("false").all()
        assert downstream["notes"].str.lower().str.contains("no |missing coefficients|driver").any()


def test_downstream_drivers_preserve_same_output_route_shares_and_drp_eaf_coefficients():
    c0 = _csv(C0_PROFILE)
    assert abs(c0.loc[c0["s2_activity_type"].eq("bof_liquid_steel_activity"), "activity_value"].astype(float).sum() - 8150.6772) <= 1e-4

    for scenario_id, filename in C1_PROFILE_FILENAMES.items():
        profile = _csv(FIXED_PROFILE_DIR / filename)
        assert set(profile["scenario_id"]) == {scenario_id}
        assert set(profile["bf_bof_share"].astype(float).round(2)) == {C1_ROUTE_SCENARIOS[scenario_id]["bf_bof_share"]}
        assert set(profile["drp_eaf_share"].astype(float).round(2)) == {C1_ROUTE_SCENARIOS[scenario_id]["drp_eaf_share"]}
        total = profile.loc[profile["s2_activity_type"].eq("total_liquid_steel_output"), "activity_value"].astype(float).sum()
        assert abs(total - 8150.6772) <= 1e-4

    energy = _csv(C1_ENERGY_INPUTS)
    values = {row["parameter_name"]: row["selected_value"] for _, row in energy.iterrows()}
    assert values["ng_drp_natural_gas_consumption"] == "195"
    assert values["ng_drp_electricity_consumption"] == "0.1"
    assert values["eaf_electricity_consumption"] == "0.5"
    assert values["ng_drp_pellets_to_dri_efficiency"] == "0.74"
    assert values["eaf_dri_to_crude_steel_efficiency"] == "0.95"


def test_downstream_readiness_flags_allow_drivers_but_block_energy_cost_da():
    for path in (COST_DA_READINESS, C1_READINESS, RUNTIME_CLOSURE):
        frame = _csv(path)
        assert frame["downstream_accounting_drivers_ready"].str.lower().eq("true").all()
        assert frame["continuous_casting_driver_ready"].str.lower().eq("true").all()
        assert frame["hsm_driver_ready"].str.lower().eq("true").all()
        assert frame["asu_oxygen_driver_ready"].str.lower().eq("true").all()
        assert frame["downstream_auxiliary_electricity_boundary_ready"].str.lower().eq("false").all()
        assert frame["downstream_heat_steam_boundary_ready"].str.lower().eq("false").all()
        assert frame["full_downstream_process_logic_ready"].str.lower().eq("false").all()
        assert frame["cost_da_ready"].str.lower().eq("false").all()


def test_no_forbidden_downstream_market_or_scheduling_logic_is_introduced():
    text = "\n".join(
        [
            _csv(STATUS_REGISTER).to_csv(index=False),
            _csv(BOUNDARY_REGISTER).to_csv(index=False),
            *[_csv(path).to_csv(index=False) for path in _profile_paths()],
        ]
    ).lower()
    forbidden = {
        "da_price",
        "settlement",
        "product_revenue",
        "gross_ets_cost",
        "route_optimisation",
        "hsm_binary",
        "slab_storage_battery",
    }
    assert forbidden.isdisjoint(text)
