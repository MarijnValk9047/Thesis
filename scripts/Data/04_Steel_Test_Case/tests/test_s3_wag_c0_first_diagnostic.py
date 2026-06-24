from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.wag_diagnostic import (  # noqa: E402
    WAGDiagnosticError,
    calculate_cog_generation,
    run_c0_wag_diagnostic,
)
from steel.wag_diagnostic_inputs import (  # noqa: E402
    DEFAULT_SELECTED_WAG_INPUT_PATH,
    DEFAULT_WAG_DEMAND_COEFFICIENT_PATH,
    load_fixed_activity_profile,
    load_selected_wag_inputs,
    load_wag_demand_coefficients,
)
from steel.wag_fixed_profile_builder import build_c0_fixed_profile_frame  # noqa: E402


PROFILE_PATH = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S3"
    / "s3_provisional_dev_input"
    / "fixed_profiles"
    / "c0_wag_fixed_profile_24h_dev.csv"
)
FIXED_PROFILE_DIR = PROFILE_PATH.parent


def test_capacity_capped_coking_proxy_does_not_need_share_and_blocks_conflicts():
    result = calculate_cog_generation(
        hot_metal_activity_tonnes=100.0,
        coke_rate_per_t_hot_metal=0.5,
        onsite_coking_share=None,
        coking_supply_mode="capacity_capped",
        coking_capacity_tonnes_per_timestep=40.0,
        dry_coal_t_per_t_coke=1.2,
        cog_yield_m3_per_t_dry_coal=300.0,
        cog_lhv_mj_per_m3=18.0,
        mandatory_cog_self_use_fraction=None,
    )
    assert result.blocked is False
    assert result.onsite_coke_tonnes == pytest.approx(40.0)
    assert result.external_or_imported_coke_tonnes == pytest.approx(10.0)
    assert result.dry_coal_input_tonnes == pytest.approx(48.0)
    assert result.gross_cog_volume_m3 == pytest.approx(14400.0)
    assert result.coking_supply_mode == "capacity_capped"

    with pytest.raises(WAGDiagnosticError, match="capacity_capped"):
        calculate_cog_generation(
            hot_metal_activity_tonnes=100.0,
            coke_rate_per_t_hot_metal=0.5,
            onsite_coking_share=0.8,
            coking_supply_mode="capacity_capped",
            coking_capacity_tonnes_per_timestep=40.0,
            dry_coal_t_per_t_coke=1.2,
            cog_yield_m3_per_t_dry_coal=300.0,
            cog_lhv_mj_per_m3=18.0,
            mandatory_cog_self_use_fraction=None,
        )


def test_governed_c0_profile_exists_and_c1_wrapper_profiles_do_not_change_c0():
    assert PROFILE_PATH.exists()
    rows = load_fixed_activity_profile(PROFILE_PATH)
    assert len(rows) == 456
    assert {row.configuration_id for row in rows} == {"C0_current_BF_BOF_reference"}
    frame = pd.read_csv(PROFILE_PATH, dtype=str, keep_default_na=False)
    assert frame["thesis_usability"].str.lower().eq("false").all()
    assert frame["profile_is_synthetic_or_diagnostic"].str.lower().eq("true").all()
    assert frame["annual_average_electricity_proxy"].str.lower().isin({"true", "false"}).all()
    c1_profiles = [path for path in FIXED_PROFILE_DIR.glob("c1_*_same_output_profile_24h_dev.csv")]
    assert len(c1_profiles) == 3
    for path in c1_profiles:
        c1_frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        assert set(c1_frame["profile_extraction_method"]) == {"s3_same_output_route_share_wrapper_not_s2_solver_split"}


def test_c0_profile_rebuild_hash_is_deterministic():
    rebuilt = build_c0_fixed_profile_frame()
    existing = pd.read_csv(PROFILE_PATH, dtype=str, keep_default_na=False)
    assert set(rebuilt["profile_content_hash"]) == set(existing["profile_content_hash"])
    assert len(set(existing["profile_content_hash"])) == 1


def test_central_c0_diagnostic_closes_balances_and_keeps_partial_ledger():
    selected = load_selected_wag_inputs(DEFAULT_SELECTED_WAG_INPUT_PATH)
    demand = load_wag_demand_coefficients(DEFAULT_WAG_DEMAND_COEFFICIENT_PATH)
    profile = load_fixed_activity_profile(PROFILE_PATH)
    result = run_c0_wag_diagnostic(selected_inputs=selected, demand_coefficients=demand, profile_rows=profile)

    assert result["validation_status"] == "valid"
    assert result["generation"]["COG"]["energy_GJ"] > 0.0
    assert result["coke"]["external_or_imported_coke_t"] == pytest.approx(0.0)
    assert result["residual_grid_import_mwh"] >= 0.0
    assert result["potential_net_import_offset_mwh"] > 0.0
    assert result["max_balance_residual_gj"] <= 1e-6
    assert result["total_balance_residual_gj"] <= 1e-6
    assert result["direct_emissions_ledger_complete"] is False
    assert result["gross_ets_cost_eligible"] is False
    assert result["thesis_usability"] is False
    assert "downstream heat sinks omitted" in result["limitations"]


def test_permitted_sensitivities_run_without_hierarchy_or_c1_scope():
    selected = load_selected_wag_inputs(DEFAULT_SELECTED_WAG_INPUT_PATH)
    demand = load_wag_demand_coefficients(DEFAULT_WAG_DEMAND_COEFFICIENT_PATH)
    profile = load_fixed_activity_profile(PROFILE_PATH)
    groups = {
        "cog_chain",
        "coking_process_demand",
        "coking_utility_demand",
        "bfg_generation",
        "bofg_generation",
        "conversion_efficiency",
    }
    central = run_c0_wag_diagnostic(selected_inputs=selected, demand_coefficients=demand, profile_rows=profile)
    for group in groups:
        low = run_c0_wag_diagnostic(
            selected_inputs=selected,
            demand_coefficients=demand,
            profile_rows=profile,
            sensitivity_group=group,
            sensitivity_variant="low",
        )
        high = run_c0_wag_diagnostic(
            selected_inputs=selected,
            demand_coefficients=demand,
            profile_rows=profile,
            sensitivity_group=group,
            sensitivity_variant="high",
        )
        assert low["configuration_id"] == "C0_current_BF_BOF_reference"
        assert high["configuration_id"] == "C0_current_BF_BOF_reference"
        assert low["validation_status"] == "valid"
        assert high["validation_status"] == "valid"
        assert low["max_balance_residual_gj"] <= 1e-6
        assert high["max_balance_residual_gj"] <= 1e-6
        assert "hierarchy" not in group
        assert low["potential_net_import_offset_mwh"] >= 0.0
        assert high["potential_net_import_offset_mwh"] >= 0.0
    assert central["validation_status"] == "valid"
