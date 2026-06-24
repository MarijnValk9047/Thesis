from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.site_static_accounting import (  # noqa: E402
    CURRENT_EMISSIONS_POLICY,
    EMISSIONS_BOUNDARY_POLICY_REGISTER,
    EMISSIONS_COMPONENT_STATUS_REGISTER,
    SITE_STATIC_ACCOUNTING_RESULT_REGISTER,
    StaticEmissionsPolicy,
    emissions_double_counting_warning,
)
from steel.wag_fixed_profile_builder import C1_ROUTE_SCENARIOS  # noqa: E402


S3_DEV_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input"
FIXED_PROFILE_ROOT = S3_DEV_ROOT / "fixed_profiles"
C1_ENERGY_INPUTS = S3_DEV_ROOT / "s3_c1_route_energy_inputs.csv"


def _csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _central_results() -> pd.DataFrame:
    results = _csv(SITE_STATIC_ACCOUNTING_RESULT_REGISTER)
    return results.loc[results["boundary_case_id"].eq("central_proxy_site_electricity_boundary")].copy()


def test_emissions_boundary_policy_register_selects_partial_direct_proxy_policy():
    policy = _csv(EMISSIONS_BOUNDARY_POLICY_REGISTER)

    assert {
        "current_partial_direct_proxy_policy",
        "future_explicit_ng_combustion_policy",
        "future_complete_direct_emissions_policy",
    } == set(policy["emissions_policy_id"])
    current = policy.loc[policy["emissions_policy_id"].eq("current_partial_direct_proxy_policy")].iloc[0]
    assert current["model_use_status"] == "selected_current_policy"
    assert current["wag_generation_counted"] == "false"
    assert current["wag_use_counted"] == "true"
    assert current["drp_direct_co2_proxy_counted"] == "true"
    assert current["drp_ng_combustion_co2_counted"] == "false"
    assert current["electricity_scope2_counted"] == "false"
    assert current["downstream_emissions_counted"] == "false"
    assert current["complete_direct_emissions_ready"] == "false"
    assert current["ets_ready"] == "false"


def test_emissions_component_status_keeps_missing_components_blocked_not_zero():
    components = _csv(EMISSIONS_COMPONENT_STATUS_REGISTER)
    required = {
        "bfg_oxidation",
        "cog_oxidation",
        "bofg_oxidation",
        "wag_flare_spill",
        "drp_direct_co2_proxy",
        "drp_ng_combustion_co2",
        "retained_bf_bof_non_wag_process",
        "coking_non_wag_process",
        "downstream_reheating_emissions",
        "electricity_scope2",
        "oxygen_asu_emissions",
        "residual_site_emissions",
        "gross_ets_cost_basis",
    }
    assert required == set(components["component_id"])

    counted = set(components.loc[components["counted_in_current_policy"].eq("true"), "component_id"])
    assert {"bfg_oxidation", "cog_oxidation", "bofg_oxidation", "wag_flare_spill", "drp_direct_co2_proxy"} <= counted
    assert "drp_ng_combustion_co2" not in counted
    assert "electricity_scope2" not in counted
    assert "downstream_reheating_emissions" not in counted

    blocked = components.loc[
        components["component_id"].isin(
            {
                "drp_ng_combustion_co2",
                "retained_bf_bof_non_wag_process",
                "coking_non_wag_process",
                "downstream_reheating_emissions",
                "oxygen_asu_emissions",
                "residual_site_emissions",
                "gross_ets_cost_basis",
            }
        )
    ]
    assert blocked["blocks_complete_direct_emissions"].eq("true").all()
    assert blocked["limitations"].str.lower().str.contains("not physically zero|missing|blocked|not closed|not represented").any()


def test_static_results_expose_current_emissions_policy_flags():
    results = _csv(SITE_STATIC_ACCOUNTING_RESULT_REGISTER)

    assert results["emissions_policy_id"].eq(CURRENT_EMISSIONS_POLICY.emissions_policy_id).all()
    assert results["wag_generation_emissions_counted"].eq("false").all()
    assert results["wag_use_emissions_counted"].eq("true").all()
    assert results["drp_ng_combustion_co2_counted"].eq("false").all()
    assert results["electricity_scope2_counted"].eq("false").all()
    assert results["downstream_emissions_counted"].eq("false").all()
    assert results["complete_direct_emissions_ready"].eq("false").all()
    assert results["ets_ready"].eq("false").all()
    assert results["double_counting_warning"].eq("").all()

    c1 = results.loc[results["scenario_id"].isin(C1_ROUTE_SCENARIOS)]
    assert c1["drp_direct_co2_proxy_counted"].eq("true").all()
    c0 = results.loc[results["scenario_id"].eq("c0_reference")]
    assert c0["drp_direct_co2_proxy_counted"].eq("false").all()


def test_partial_direct_proxy_excludes_policy_blocked_and_missing_emissions():
    results = _csv(SITE_STATIC_ACCOUNTING_RESULT_REGISTER).copy()
    for column in (
        "wag_co2_t_24h",
        "drp_direct_co2_proxy_t_24h",
        "total_partial_direct_co2_proxy_t_24h",
    ):
        results[column] = pd.to_numeric(results[column], errors="raise")

    assert results["drp_ng_combustion_co2_t_24h"].eq("").all()
    assert results["electricity_scope2_t_24h"].eq("").all()
    assert results["downstream_co2_t_24h"].eq("").all()

    c1 = results.loc[results["scenario_id"].isin(C1_ROUTE_SCENARIOS)]
    c1_residual = (
        c1["total_partial_direct_co2_proxy_t_24h"]
        - c1["wag_co2_t_24h"]
        - c1["drp_direct_co2_proxy_t_24h"]
    ).abs()
    assert c1_residual.le(1e-6).all()
    c0 = results.loc[results["scenario_id"].eq("c0_reference")]
    assert c0["total_partial_direct_co2_proxy_t_24h"].eq(c0["wag_co2_t_24h"]).all()


def test_double_counting_warning_catches_drp_direct_proxy_and_ng_combustion_fixture():
    risky_policy = StaticEmissionsPolicy(
        emissions_policy_id="fixture_invalid_policy",
        policy_name="fixture invalid policy",
        wag_generation_emissions_counted=False,
        wag_use_emissions_counted=True,
        drp_direct_co2_proxy_counted=True,
        drp_ng_combustion_co2_counted=True,
        electricity_scope2_counted=False,
        downstream_emissions_counted=False,
        complete_direct_emissions_ready=False,
        ets_ready=False,
    )
    assert emissions_double_counting_warning(risky_policy) == "drp_direct_proxy_and_ng_combustion_both_counted"


def test_physical_energy_results_remain_unchanged_from_s30e_a():
    central = _central_results()
    expected = {
        "c0_reference": (57391.510570, 0.0, 0.0, 0.0),
        "c1_high_drp_eaf": (31565.330813, 1017385.383073, 521.736094, 1930.423547),
        "c1_central": (35008.821447, 881733.998663, 452.171281, 1673.033741),
        "c1_low_drp_eaf": (39026.227187, 723474.050185, 371.012334, 1372.745634),
    }
    for scenario_id, values in expected.items():
        row = central.loc[central["scenario_id"].eq(scenario_id)].iloc[0]
        assert float(row["total_wag_gj_24h"]) == pytest.approx(values[0])
        assert float(row["drp_natural_gas_m3_24h"]) == pytest.approx(values[1])
        assert float(row["drp_electricity_mwh_24h"]) == pytest.approx(values[2])
        assert float(row["eaf_electricity_mwh_24h"]) == pytest.approx(values[3])


def test_monetary_values_remain_blank_and_forbidden_logic_absent():
    results = _csv(SITE_STATIC_ACCOUNTING_RESULT_REGISTER)
    for column in (
        "electricity_cost_eur_24h",
        "natural_gas_cost_eur_24h",
        "co2_cost_eur_24h",
        "total_static_cost_proxy_eur_24h",
    ):
        assert results[column].eq("").all()
    assert results["monetary_values_ready"].eq("false").all()
    assert results["cost_da_ready"].eq("false").all()
    text = "\n".join(results.astype(str).agg(" ".join, axis=1)).lower()
    forbidden = {"da_price", "settlement result", "product_revenue", "tariff result", "route_optimisation"}
    assert forbidden.isdisjoint(text)


def test_regression_inputs_and_downstream_drivers_remain_frozen():
    assert C1_ROUTE_SCENARIOS["c1_high_drp_eaf"] == {"bf_bof_share": 0.55, "drp_eaf_share": 0.45}
    assert C1_ROUTE_SCENARIOS["c1_central"] == {"bf_bof_share": 0.61, "drp_eaf_share": 0.39}
    assert C1_ROUTE_SCENARIOS["c1_low_drp_eaf"] == {"bf_bof_share": 0.68, "drp_eaf_share": 0.32}

    energy = _csv(C1_ENERGY_INPUTS).set_index("parameter_name")
    assert energy.loc["ng_drp_natural_gas_consumption", "selected_value"] == "195"
    assert energy.loc["ng_drp_electricity_consumption", "selected_value"] == "0.1"
    assert energy.loc["eaf_electricity_consumption", "selected_value"] == "0.5"
    assert energy.loc["ng_drp_direct_co2_factor", "selected_value"] == "0.5"

    downstream = {
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
    for path in FIXED_PROFILE_ROOT.glob("*.csv"):
        if "s2_13_downstream" in path.name:
            continue
        profile = _csv(path)
        assert downstream.issubset(set(profile["s2_activity_type"]))
