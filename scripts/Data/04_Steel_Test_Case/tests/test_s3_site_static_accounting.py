from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.site_static_accounting import (  # noqa: E402
    ELECTRICITY_BOUNDARY_SENSITIVITY_REGISTER,
    SITE_STATIC_ACCOUNTING_BOUNDARY_REGISTER,
    SITE_STATIC_ACCOUNTING_RESULT_REGISTER,
    STATIC_ACCOUNTING_PARAMETER_STATUS_REGISTER,
)
from steel.wag_fixed_profile_builder import C1_ROUTE_SCENARIOS  # noqa: E402


S3_DEV_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S3/s3_provisional_dev_input"
FIXED_PROFILE_ROOT = S3_DEV_ROOT / "fixed_profiles"
C1_ENERGY_INPUTS = S3_DEV_ROOT / "s3_c1_route_energy_inputs.csv"


def _csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_site_static_accounting_boundary_rows_exist_without_overclaiming():
    boundary = _csv(SITE_STATIC_ACCOUNTING_BOUNDARY_REGISTER)

    assert set(boundary["scenario_id"]) == {"c0_reference", *C1_ROUTE_SCENARIOS}
    assert len(boundary) == 4
    assert boundary["included_physical_components"].str.len().gt(0).all()
    assert boundary["excluded_components"].str.len().gt(0).all()
    assert boundary["plant_level_claim_allowed"].str.lower().eq("false").all()
    assert boundary["cost_result_allowed"].str.lower().eq("false").all()
    assert boundary["da_market_result_allowed"].str.lower().eq("false").all()
    assert boundary["complete_direct_emissions_ready"].str.lower().eq("false").all()
    assert boundary["complete_site_energy_ready"].str.lower().eq("false").all()


def test_static_accounting_parameter_status_blocks_missing_coefficients_and_prices():
    status = _csv(STATIC_ACCOUNTING_PARAMETER_STATUS_REGISTER)
    required = {
        "WAG generation coefficients",
        "WAG LHV",
        "WAG power conversion efficiency",
        "DRP natural-gas coefficient",
        "DRP electricity coefficient",
        "EAF electricity coefficient",
        "downstream accounting drivers",
        "downstream electricity coefficient",
        "ASU/oxygen electricity coefficient",
        "heat/steam/reheating coefficient",
        "residual electricity boundary policy",
        "WAG CO2 factors",
        "DRP direct CO2 proxy",
        "natural-gas CO2 factor",
        "electricity scope-2 factor",
        "downstream emissions factors",
        "complete direct-emissions ledger policy",
        "electricity price input",
        "natural-gas price input",
        "CO2/ETS price input",
        "tariff/network cost input",
        "WAG avoided-cost valuation policy",
        "product revenue input",
    }
    assert required == set(status["parameter_name"])

    missing = status.loc[status["current_status"].str.contains("missing|out_of_scope", case=False, regex=True)]
    assert not missing.empty
    assert missing["selected_value"].eq("").all()

    price_rows = status.loc[status["parameter_name"].isin({"electricity price input", "natural-gas price input", "CO2/ETS price input"})]
    assert price_rows["blocks_monetary_ledger"].str.lower().eq("true").all()
    assert price_rows["model_use_status"].eq("formula_hook_only").all()

    material = status.loc[
        status["parameter_name"].isin(
            {
                "WAG generation coefficients",
                "WAG power conversion efficiency",
                "DRP natural-gas coefficient",
                "DRP electricity coefficient",
                "EAF electricity coefficient",
                "residual electricity boundary policy",
            }
        )
    ]
    assert material["sensitivity_required"].str.lower().eq("true").all()
    assert status.loc[status["parameter_name"].eq("downstream electricity coefficient"), "limitations"].iloc[0].lower().find("zero") >= 0


def test_electricity_boundary_sensitivity_register_is_proxy_only():
    boundary = _csv(ELECTRICITY_BOUNDARY_SENSITIVITY_REGISTER)

    assert set(boundary["boundary_case_id"]) == {
        "low_proxy_site_electricity_boundary",
        "central_proxy_site_electricity_boundary",
        "high_proxy_site_electricity_boundary",
    }
    assert boundary["not_tata_exact"].str.lower().eq("true").all()
    assert boundary["validation_claim_eligible"].str.lower().eq("false").all()
    assert boundary["cost_da_ready"].str.lower().eq("false").all()
    assert boundary["plant_level_claim_allowed"].str.lower().eq("false").all()
    central = boundary.loc[boundary["boundary_case_id"].eq("central_proxy_site_electricity_boundary")].iloc[0]
    assert float(central["annual_mwh"]) == 3_000_000.0
    assert abs(float(central["mwh_24h"]) - (3_000_000.0 / 365.0)) <= 1e-6


def test_static_accounting_results_have_physical_emissions_and_blocked_monetary_values():
    results = _csv(SITE_STATIC_ACCOUNTING_RESULT_REGISTER)

    assert len(results) == 12
    assert set(results["scenario_id"]) == {"c0_reference", *C1_ROUTE_SCENARIOS}
    assert results.groupby("scenario_id")["boundary_case_id"].nunique().eq(3).all()
    assert results["monetary_values_ready"].str.lower().eq("false").all()
    assert results["complete_direct_emissions_ready"].str.lower().eq("false").all()
    assert results["plant_level_claim_allowed"].str.lower().eq("false").all()
    assert results["cost_da_ready"].str.lower().eq("false").all()
    for column in ("electricity_cost_eur_24h", "natural_gas_cost_eur_24h", "co2_cost_eur_24h", "total_static_cost_proxy_eur_24h"):
        assert results[column].eq("").all()
    assert not [column for column in results.columns if "revenue" in column.lower()]


def test_static_accounting_result_invariants_preserve_c0_c1_relationships():
    results = _csv(SITE_STATIC_ACCOUNTING_RESULT_REGISTER)
    central = results.loc[results["boundary_case_id"].eq("central_proxy_site_electricity_boundary")].copy()
    for column in (
        "total_wag_gj_24h",
        "drp_natural_gas_m3_24h",
        "drp_electricity_mwh_24h",
        "eaf_electricity_mwh_24h",
        "component_electricity_mwh_24h",
        "gross_proxy_electricity_boundary_mwh_24h",
        "wag_offset_mwh_24h",
        "residual_proxy_grid_import_mwh_24h",
        "wag_co2_t_24h",
        "drp_direct_co2_proxy_t_24h",
        "total_partial_direct_co2_proxy_t_24h",
    ):
        central[column] = pd.to_numeric(central[column], errors="coerce")

    c0_total_wag = central.loc[central["scenario_id"].eq("c0_reference"), "total_wag_gj_24h"].iloc[0]
    c1_total_wag = central.loc[central["scenario_id"].isin(C1_ROUTE_SCENARIOS), "total_wag_gj_24h"]
    assert (c0_total_wag > c1_total_wag).all()

    ordered = central.set_index("scenario_id")
    assert ordered.loc["c1_high_drp_eaf", "drp_natural_gas_m3_24h"] > ordered.loc["c1_central", "drp_natural_gas_m3_24h"]
    assert ordered.loc["c1_central", "drp_natural_gas_m3_24h"] > ordered.loc["c1_low_drp_eaf", "drp_natural_gas_m3_24h"]
    assert ordered.loc["c1_high_drp_eaf", "component_electricity_mwh_24h"] > ordered.loc["c1_central", "component_electricity_mwh_24h"]
    assert ordered.loc["c1_central", "component_electricity_mwh_24h"] > ordered.loc["c1_low_drp_eaf", "component_electricity_mwh_24h"]

    all_results = results.copy()
    all_results["gross_proxy_electricity_boundary_mwh_24h"] = pd.to_numeric(all_results["gross_proxy_electricity_boundary_mwh_24h"])
    all_results["wag_offset_mwh_24h"] = pd.to_numeric(all_results["wag_offset_mwh_24h"])
    all_results["residual_proxy_grid_import_mwh_24h"] = pd.to_numeric(all_results["residual_proxy_grid_import_mwh_24h"])
    assert (all_results["wag_offset_mwh_24h"] <= all_results["gross_proxy_electricity_boundary_mwh_24h"]).all()
    assert (all_results["residual_proxy_grid_import_mwh_24h"] >= 0.0).all()

    co2_residual = (
        central["total_partial_direct_co2_proxy_t_24h"]
        - central["wag_co2_t_24h"]
        - central["drp_direct_co2_proxy_t_24h"]
    ).abs()
    assert (co2_residual <= 1e-6).all()


def test_static_accounting_regression_inputs_remain_frozen():
    assert C1_ROUTE_SCENARIOS["c1_high_drp_eaf"] == {"bf_bof_share": 0.55, "drp_eaf_share": 0.45}
    assert C1_ROUTE_SCENARIOS["c1_central"] == {"bf_bof_share": 0.61, "drp_eaf_share": 0.39}
    assert C1_ROUTE_SCENARIOS["c1_low_drp_eaf"] == {"bf_bof_share": 0.68, "drp_eaf_share": 0.32}

    energy = _csv(C1_ENERGY_INPUTS)
    selected = energy.set_index("parameter_name")
    assert selected.loc["ng_drp_natural_gas_consumption", "selected_value"] == "195"
    assert selected.loc["ng_drp_electricity_consumption", "selected_value"] == "0.1"
    assert selected.loc["eaf_electricity_consumption", "selected_value"] == "0.5"

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


def test_static_accounting_outputs_do_not_add_forbidden_market_logic():
    results = _csv(SITE_STATIC_ACCOUNTING_RESULT_REGISTER)
    allowed_columns = {"boundary_case_id", "gross_proxy_electricity_boundary_mwh_24h", "cost_da_ready"}
    forbidden_column_tokens = (
        "da_price",
        "bid",
        "clearing",
        "settlement",
        "cvar",
        "mfrr",
        "tariff",
        "gross_ets",
        "route_optimisation",
        "revenue",
        "product",
    )
    assert not [
        column
        for column in results.columns
        if column not in allowed_columns and any(token in column.lower() for token in forbidden_column_tokens)
    ]
    assert results["notes"].str.lower().str.contains("not revenue").all()

    boundary = _csv(SITE_STATIC_ACCOUNTING_BOUNDARY_REGISTER)
    assert boundary["excluded_components"].str.lower().str.contains("settlement").all()
    assert boundary["da_market_result_allowed"].str.lower().eq("false").all()
