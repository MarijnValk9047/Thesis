from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.downstream_scheduling_inputs import load_downstream_assumptions  # noqa: E402
from steel.site_static_economics_builder import C1_CONFIGURATION_ID  # noqa: E402
from steel.site_static_economics_inputs import (  # noqa: E402
    DEFAULT_S3_2_MATERIAL_INPUT_PATH,
    DEFAULT_S3_2_STATIC_PRICE_PATH,
    load_s3_2_static_economics_assumptions,
)
from steel.site_static_economics_runner import (  # noqa: E402
    run_s3_2_smoke_suite,
    s3_2_sensitivity_cases,
    solve_s3_2_case,
)


S3_REVIEW_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review"
REQUIRED_REGISTERS = (
    S3_REVIEW_ROOT / "s3_2_slab_yard_capacity_amendment_register.csv",
    S3_REVIEW_ROOT / "s3_2_material_recipe_and_cost_review.csv",
    S3_REVIEW_ROOT / "s3_2_route_cost_coverage_register.csv",
    S3_REVIEW_ROOT / "s3_2_carbon_boundary_and_decomposition_register.csv",
    S3_REVIEW_ROOT / "s3_2_emissions_completeness_register.csv",
    S3_REVIEW_ROOT / "s3_2_wag_power_interface_policy_register.csv",
    S3_REVIEW_ROOT / "s3_2_endogenous_route_choice_register.csv",
    S3_REVIEW_ROOT / "s3_2_stage_gate_checklist.csv",
)


def _csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


@pytest.fixture(scope="module")
def s3_2_payload() -> dict:
    return run_s3_2_smoke_suite(write_outputs=False, include_168h=True, include_sensitivities=False)


def test_s3_2_governed_inputs_and_registers_exist():
    materials = _csv(DEFAULT_S3_2_MATERIAL_INPUT_PATH)
    prices = _csv(DEFAULT_S3_2_STATIC_PRICE_PATH)
    assert not materials.empty
    assert not prices.empty
    for path in REQUIRED_REGISTERS:
        assert path.exists()
        assert not _csv(path).empty
    for frame in (materials, prices):
        active = frame.loc[~frame["model_use_status"].isin(("blocked", "not_selected_missing"))]
        assert active["tata_exact_claim_allowed"].str.lower().eq("false").all()
        assert active["thesis_validation_claim_eligible"].str.lower().eq("false").all()
    assert set(prices["price_name"]) >= {
        "grid_electricity_price_eur_per_mwh",
        "natural_gas_price_eur_per_gj",
        "gross_co2_price_eur_per_t",
        "scope2_operational_tco2_per_mwh",
        "wag_power_residual_utilisation_fraction",
    }


def test_slab_yard_capacity_amendment_preserves_initial_inventory():
    assumptions = load_downstream_assumptions(
        configuration_id=C1_CONFIGURATION_ID,
        horizon_hours=24,
    )
    assert assumptions.slab_yard_capacity_t == pytest.approx(25000.0)
    assert assumptions.initial_cold_slab_inventory_t == pytest.approx(1630.13544)
    assert assumptions.initial_cold_slab_inventory_t != pytest.approx(12500.0)
    weekly = load_downstream_assumptions(configuration_id=C1_CONFIGURATION_ID, horizon_hours=168)
    assert weekly.final_product_target_t == pytest.approx(7.0 * assumptions.final_product_target_t)
    assert weekly.q_avg_hsm_tph == pytest.approx(assumptions.q_avg_hsm_tph)


def test_static_price_and_emissions_assumptions_are_loaded():
    assumptions = load_s3_2_static_economics_assumptions()
    assert assumptions.static_cost_ready is True
    assert assumptions.route_cost_coverage_complete is True
    assert assumptions.prices.electricity_price_eur_per_mwh == pytest.approx(77.29)
    assert assumptions.prices.natural_gas_price_eur_per_gj == pytest.approx(33.50 / 3.6)
    assert assumptions.prices.gross_co2_price_eur_per_t == pytest.approx(65.0)
    assert assumptions.prices.scope2_operational_tco2_per_mwh == pytest.approx(0.20)
    assert assumptions.prices.grid_lifecycle_tco2e_per_mwh == pytest.approx(0.268)
    assert assumptions.prices.wag_power_residual_utilisation_fraction == pytest.approx(0.50)


def test_s3_2_mandatory_24h_and_168h_cases_pass(s3_2_payload: dict):
    assert s3_2_payload["all_required_24h_outcomes_met"] is True
    assert s3_2_payload["all_required_168h_outcomes_met"] is True
    rows = {row["smoke_case"]: row for row in s3_2_payload["results"]}
    for case_id in (
        "c0_static_economic_24h",
        "c1_fixed_61_39_static_economic_24h",
        "c1_endogenous_route_static_economics_24h",
        "c0_static_economic_168h",
        "c1_fixed_61_39_static_economic_168h",
        "c1_endogenous_route_static_economics_168h",
    ):
        row = rows[case_id]
        assert row["termination_condition"] == "optimal"
        assert float(row["final_product_output_t"]) == pytest.approx(float(row["final_product_target_t"]), abs=1e-5)
        assert float(row["terminal_cold_slab_deviation_t"]) == pytest.approx(0.0, abs=1e-8)
        assert float(row["terminal_hot_slab_t"]) == pytest.approx(0.0, abs=1e-8)
        assert float(row["max_material_balance_residual_t"]) <= 1e-5
        assert float(row["max_wag_balance_residual_gj"]) <= 1e-6
        assert float(row["max_electricity_balance_residual_mwh"]) <= 1e-6
        assert float(row["max_cost_sum_residual_eur"]) <= 1e-6


def test_material_costs_and_no_double_purchase_rules(s3_2_payload: dict):
    c0 = {row["smoke_case"]: row for row in s3_2_payload["results"]}["c0_static_economic_24h"]
    c1 = {row["smoke_case"]: row for row in s3_2_payload["results"]}["c1_fixed_61_39_static_economic_24h"]
    assert float(c0["coking_coal_t"]) > 0.0
    assert float(c0["purchased_coke_t"]) == pytest.approx(0.0)
    assert float(c1["dr_pellets_t"]) > 0.0
    assert float(c1["scrap_t"]) > 0.0
    assert float(c1["natural_gas_import_gj"]) > 0.0
    assert float(c1["material_cost_eur"]) > 0.0
    assert float(c1["total_static_operating_cost_eur"]) > float(c1["material_cost_eur"])


def test_wag_power_interface_has_no_export_or_revenue(s3_2_payload: dict):
    rows = {row["smoke_case"]: row for row in s3_2_payload["results"]}
    for row in rows.values():
        if row["termination_condition"] != "optimal":
            continue
        assert float(row["wag_power_output_mwh"]) >= 0.0
        assert float(row["grid_import_mwh"]) >= 0.0
        assert float(row["flare_spill_gj"]) >= 0.0
        assert "revenue" not in " ".join(row.keys()).lower()


def test_direct_scope2_and_cost_accounting_are_separated(s3_2_payload: dict):
    row = {row["smoke_case"]: row for row in s3_2_payload["results"]}["c1_fixed_61_39_static_economic_24h"]
    direct = float(row["total_direct_co2_t"])
    scope2 = float(row["scope2_operational_co2_t"])
    total = float(row["total_direct_plus_scope2_t"])
    assert float(row["drp_ng_combustion_co2_t"]) > 0.0
    assert float(row["drp_residual_process_co2_t"]) > 0.0
    assert total == pytest.approx(direct + scope2, abs=1e-5)
    assert float(row["gross_direct_co2_cost_eur"]) == pytest.approx(65.0 * direct, abs=1e-4)
    assert row["scope2_ets_costed"] == "false"
    assert row["double_counting_warning"] == ""


def test_endogenous_route_choice_is_bounded_and_not_a_wag_decision(s3_2_payload: dict):
    row = {row["smoke_case"]: row for row in s3_2_payload["results"]}["c1_endogenous_route_static_economics_24h"]
    bf_share = float(row["bf_bof_share"])
    drp_share = float(row["drp_eaf_share"])
    assert bf_share != pytest.approx(0.61)
    assert 0.5471962 <= bf_share <= 0.67988981
    assert bf_share + drp_share == pytest.approx(1.0, abs=1e-8)
    assert float(row["wag_share_vs_c0"]) == pytest.approx(bf_share, abs=1e-8)
    assert row["route_mode"] == "endogenous_bounded"


def test_outage_cold_heavy_and_stress_behaviour(s3_2_payload: dict):
    rows = {row["smoke_case"]: row for row in s3_2_payload["results"]}
    base = rows["c1_fixed_61_39_static_economic_24h"]
    outage = rows["recoverable_hsm_outage_static_economics_24h"]
    cold = rows["cold_heavy_static_economics_24h"]
    stress = rows["hard_target_stress_infeasible_static_economics_24h"]
    assert float(outage["reheated_t"]) > float(base["reheated_t"])
    assert float(outage["reheating_heat_gj"]) > float(base["reheating_heat_gj"])
    assert float(outage["total_static_operating_cost_eur"]) > float(base["total_static_operating_cost_eur"])
    assert float(cold["reheated_t"]) > 0.0
    assert stress["termination_condition"] == "infeasible"
    assert stress["shortfall_slack_present"] == "false"


def test_selected_sensitivities_are_available_and_solve():
    smoke_ids = {case.smoke_case for case in s3_2_sensitivity_cases()}
    assert {
        "sensitivity_slab_yard_legacy_24h",
        "sensitivity_slab_yard_upper_50000t_24h",
        "sensitivity_low_static_prices_and_coefficients_24h",
        "sensitivity_high_static_prices_and_coefficients_24h",
        "sensitivity_fixed_route_055_bf_bof_24h",
        "sensitivity_fixed_route_068_bf_bof_24h",
    }.issubset(smoke_ids)
    case = next(case for case in s3_2_sensitivity_cases() if case.smoke_case == "sensitivity_fixed_route_055_bf_bof_24h")
    row, _ = solve_s3_2_case(case)
    assert row["termination_condition"] == "optimal"
    assert float(row["bf_bof_share"]) == pytest.approx(0.55, abs=1e-8)
