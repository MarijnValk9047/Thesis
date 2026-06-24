from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest
from pyomo.environ import value

TEST_CASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_CASE_ROOT.parents[2]
if str(TEST_CASE_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_CASE_ROOT))

from steel.downstream_scheduling_builder import DownstreamCaseOptions, build_downstream_scheduling_model  # noqa: E402
from steel.site_energy_economic_builder import C0_CONFIGURATION_ID, C1_CONFIGURATION_ID, IntegratedCaseOptions, build_site_energy_economic_model  # noqa: E402
from steel.site_energy_economic_inputs import (  # noqa: E402
    DEFAULT_S3_1_ENERGY_INPUT_PATH,
    DEFAULT_S3_1_PRICE_INPUT_PATH,
    SiteEnergyEconomicInputError,
    WAG_CARRIERS,
    load_site_energy_economic_assumptions,
    validate_wag_activity_basis,
)
from steel.site_energy_economic_runner import (  # noqa: E402
    DEFAULT_RESULT_REGISTER,
    required_integrated_smoke_cases,
    run_integrated_smoke_suite,
    solve_integrated_case,
)


S3_REVIEW_ROOT = REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S3/s3_candidate_review"
INTEGRATION_CONTRACT = S3_REVIEW_ROOT / "s3_1_integration_contract_register.csv"
ENERGY_REVIEW = S3_REVIEW_ROOT / "s3_1_downstream_energy_emissions_selection_review.csv"
EMISSIONS_REGISTER = S3_REVIEW_ROOT / "s3_1_direct_emissions_component_register.csv"
PRICE_REVIEW = S3_REVIEW_ROOT / "s3_1_static_price_selection_review.csv"
STAGE_GATE = S3_REVIEW_ROOT / "s3_1_stage_gate_checklist.csv"
WAG_RECONCILIATION = S3_REVIEW_ROOT / "s3_1_wag_driver_basis_reconciliation_register.csv"
STATIC_ACCOUNTING_RESULTS = S3_REVIEW_ROOT / "s3_site_static_accounting_result_register.csv"


def _csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


@pytest.fixture(scope="module")
def smoke_payload() -> dict:
    return run_integrated_smoke_suite(write_outputs=False)


def test_s3_1_governed_inputs_and_registers_exist():
    selected = _csv(DEFAULT_S3_1_ENERGY_INPUT_PATH)
    prices = _csv(DEFAULT_S3_1_PRICE_INPUT_PATH)
    for path in (
        INTEGRATION_CONTRACT,
        ENERGY_REVIEW,
        EMISSIONS_REGISTER,
        PRICE_REVIEW,
        DEFAULT_RESULT_REGISTER,
        STAGE_GATE,
        WAG_RECONCILIATION,
    ):
        assert path.exists()
        assert not _csv(path).empty

    assert selected["tata_exact_claim_allowed"].str.lower().eq("false").all()
    assert selected["thesis_validation_claim_eligible"].str.lower().eq("false").all()
    tier_d = selected.loc[selected["evidence_tier"].eq("D")]
    assert not tier_d.empty
    assert tier_d["sensitivity_required"].str.lower().eq("true").all()
    assert not selected.loc[
        selected["selected_value"].isin(("0", "0.0", "0.00"))
        & ~selected["zero_value_status"].eq("explicit_zero_valid")
    ].shape[0]

    assert prices["selected_value"].eq("").all()
    assert prices["model_use_status"].eq("not_selected_missing").all()
    assert set(prices["missing_blocks"]) == {"static_monetary_ledger"}


def test_wag_driver_basis_validation_rejects_incompatible_pairs():
    validate_wag_activity_basis("t_hot_metal", "Nm3/t_hot_metal")
    validate_wag_activity_basis("t_dry_coal", "m3/t_dry_coal")
    validate_wag_activity_basis("t_liquid_steel", "Nm3/t_liquid_steel")
    with pytest.raises(SiteEnergyEconomicInputError):
        validate_wag_activity_basis("t_liquid_steel", "Nm3/t_hot_metal")
    with pytest.raises(SiteEnergyEconomicInputError):
        validate_wag_activity_basis("t_final_product", "m3/t_dry_coal")


def test_frozen_s2_13_model_is_unchanged_when_s3_1_wrapper_is_not_used():
    model = build_downstream_scheduling_model(
        configuration_id=C1_CONFIGURATION_ID,
        horizon_hours=24,
        case_options=DownstreamCaseOptions(smoke_case_id="s3_1_regression_probe"),
    )
    assert model.s2_13_model_stats.variables == 865
    assert model.s2_13_model_stats.binaries == 216
    assert model.s2_13_model_stats.constraints == 1294
    assert model.s2_13_metadata["market_logic_active"] is False
    assert model.s2_13_metadata["shortfall_slack_active"] is False


def test_s3_1_wrapper_adds_energy_topology_without_forbidden_markets():
    model = build_site_energy_economic_model(
        configuration_id=C1_CONFIGURATION_ID,
        horizon_hours=24,
        case_options=IntegratedCaseOptions(smoke_case_id="unit_topology"),
    )
    component_names = set(model.component_map().keys())
    required = {
        "grid_import_mwh",
        "natural_gas_import_gj",
        "bfg_generated_gj",
        "cog_generated_gj",
        "bofg_generated_gj",
        "wag_process_use_gj",
        "wag_steam_boiler_use_gj",
        "wag_reheating_use_gj",
        "wag_power_output_mwh",
        "flare_spill_gj",
        "secondary_metallurgy_electricity_mwh",
        "casting_electricity_mwh",
        "dsp_electricity_mwh",
        "reheating_heat_gj",
        "hsm_electricity_mwh",
        "asu_electricity_mwh",
        "residual_auxiliary_electricity_mwh",
        "total_direct_co2_t",
    }
    assert required.issubset(component_names)
    assert model.s3_1_metadata["market_logic_active"] is False
    assert model.s3_1_metadata["product_revenue_active"] is False
    assert model.s3_1_metadata["wag_power_base_mode"] == "potential_only_no_base_dispatch"
    assert model.s3_1_metadata["scope2_electricity_counted"] is False
    assert not any("settlement" in name.lower() or "cvar" in name.lower() or "mfrr" in name.lower() for name in component_names)


def test_input_loader_keeps_monetary_values_blocked_without_prices():
    assumptions = load_site_energy_economic_assumptions()
    assert assumptions.monetary_values_ready is False
    assert {"grid_electricity_price", "natural_gas_price", "gross_co2_price"}.issubset(
        set(assumptions.missing_price_inputs)
    )
    assert assumptions.complete_direct_emissions_ready is False
    assert assumptions.scope2_electricity_counted is False
    assert assumptions.ets_ready is False


def test_required_integrated_smokes_have_expected_outcomes(smoke_payload: dict):
    rows = {row["smoke_case"]: row for row in smoke_payload["results"]}
    assert smoke_payload["all_required_outcomes_met"] is True
    for case in required_integrated_smoke_cases():
        assert case.smoke_case in rows
        termination = rows[case.smoke_case]["termination_condition"].lower()
        if case.expected_outcome == "optimal":
            assert termination == "optimal"
            assert float(rows[case.smoke_case]["final_product_output_t"]) == pytest.approx(
                float(rows[case.smoke_case]["final_product_target_t"]),
                abs=1e-6,
            )
            assert rows[case.smoke_case]["shortfall_slack_present"] == "false"
        else:
            assert "infeasible" in termination


def test_c0_c1_energy_and_route_relationships(smoke_payload: dict):
    rows = {row["smoke_case"]: row for row in smoke_payload["results"]}
    c0 = rows["c0_integrated_central"]
    c1 = rows["c1_central_integrated"]

    assert float(c1["bf_bof_share"]) == pytest.approx(0.61, abs=1e-8)
    assert float(c1["drp_eaf_share"]) == pytest.approx(0.39, abs=1e-8)
    assert float(c1["final_product_output_t"]) == pytest.approx(float(c0["final_product_output_t"]), abs=1e-6)
    assert float(c0["total_wag_generated_gj"]) > float(c1["total_wag_generated_gj"])
    assert float(c1["grid_import_mwh"]) > float(c0["grid_import_mwh"])
    assert float(c1["drp_natural_gas_m3"]) > 0.0
    assert float(c1["drp_electricity_mwh"]) > 0.0
    assert float(c1["eaf_electricity_mwh"]) > 0.0
    assert float(c1["drp_direct_co2_proxy_t"]) > 0.0


def test_wag_grid_ng_and_emissions_balances_close(smoke_payload: dict):
    for row in smoke_payload["results"]:
        if row["termination_condition"] != "optimal":
            continue
        assert float(row["max_material_balance_residual_t"]) <= 1e-6
        assert float(row["max_wag_balance_residual_gj"]) <= 1e-6
        assert float(row["max_electricity_balance_residual_mwh"]) <= 1e-6
        assert float(row["max_reheating_balance_residual_gj"]) <= 1e-6
        assert float(row["wag_power_output_mwh"]) == pytest.approx(0.0, abs=1e-9)
        assert float(row["potential_wag_power_output_mwh"]) >= 0.0
        assert float(row["grid_import_mwh"]) >= 0.0
        assert row["drp_ng_combustion_co2_t"] == ""
        assert row["double_counting_warning"] == ""
        assert row["complete_direct_emissions_ready"] == "false"
        assert row["scope2_electricity_counted"] == "false"
        assert row["ets_ready"] == "false"


def test_reheating_energy_follows_cold_slab_scheduling(smoke_payload: dict):
    rows = {row["smoke_case"]: row for row in smoke_payload["results"]}
    all_hot = rows["all_hot_reference"]
    outage = rows["recoverable_hsm_outage_integrated"]
    cold_heavy = rows["cold_heavy_diagnostic"]

    assert float(all_hot["reheated_t"]) == pytest.approx(0.0, abs=1e-9)
    assert float(all_hot["reheating_heat_gj"]) == pytest.approx(0.0, abs=1e-9)
    assert float(outage["reheated_t"]) > 0.0
    assert float(outage["reheating_heat_gj"]) > float(all_hot["reheating_heat_gj"])
    assert float(outage["reheating_co2_t"]) > float(all_hot["reheating_co2_t"])
    assert float(cold_heavy["reheated_t"]) > 0.0
    assert float(cold_heavy["reheating_heat_gj"]) > 0.0
    assert float(cold_heavy["grid_import_mwh"]) > float(all_hot["grid_import_mwh"])


def test_monetary_columns_remain_blank_and_no_revenue_columns(smoke_payload: dict):
    for row in smoke_payload["results"]:
        for column in (
            "electricity_cost_eur",
            "natural_gas_cost_eur",
            "gross_co2_cost_eur",
            "flare_cost_eur",
            "startup_cost_eur",
            "tariff_cost_eur",
            "total_static_operating_cost_eur",
            "eur_per_t_final_product",
        ):
            assert row[column] == ""
        assert row["monetary_values_ready"] == "false"
    assert not [column for column in smoke_payload["results"][0] if "revenue" in column.lower()]


def test_stress_case_remains_infeasible_and_accounting_does_not_create_shortfall():
    stress_case = next(
        case for case in required_integrated_smoke_cases() if case.smoke_case == "hard_target_stress_infeasible_integrated"
    )
    row, model = solve_integrated_case(stress_case)
    assert model is None
    assert row["termination_condition"] == "infeasible"
    assert row["shortfall_slack_present"] == "false"
    assert row["infeasibility_class"] == "hard_final_product_target_infeasible_accounting_layer_no_fake_feasibility"


def test_selected_coefficients_map_to_physical_variables_after_solve():
    case = next(case for case in required_integrated_smoke_cases() if case.smoke_case == "c0_integrated_central")
    row, model = solve_integrated_case(case)
    assert row["termination_condition"] == "optimal"
    assert model is not None
    t = 5
    assumptions = model.s3_1_assumptions
    assert value(model.reheating_heat_gj[t]) == pytest.approx(
        assumptions.reheating_heat_gj_per_t_cold_slab * value(model.reheat_cold_slab_input[t]),
        abs=1e-8,
    )
    assert value(model.hsm_electricity_mwh[t]) == pytest.approx(
        assumptions.hsm_electricity_mwh_per_t * value(model.hsm_total_slab_input[t]),
        abs=1e-8,
    )
    assert value(model.asu_electricity_mwh[t]) == pytest.approx(
        assumptions.asu_electricity_mwh_per_t_o2 * value(model.oxygen_demand_t[t]),
        abs=1e-8,
    )
    for carrier in WAG_CARRIERS:
        lhs = value(model.wag_generated_gj[carrier, t])
        rhs = (
            value(model.wag_process_use_gj[carrier, t])
            + value(model.wag_steam_boiler_use_gj[carrier, t])
            + value(model.wag_reheating_use_gj[carrier, t])
            + value(model.wag_power_use_gj[carrier, t])
            + value(model.flare_spill_gj[carrier, t])
        )
        assert lhs == pytest.approx(rhs, abs=1e-8)


def test_wag_generation_uses_reconciled_activity_drivers():
    case = next(case for case in required_integrated_smoke_cases() if case.smoke_case == "c0_integrated_central")
    row, model = solve_integrated_case(case)
    assert row["termination_condition"] == "optimal"
    assert model is not None
    assumptions = model.s3_1_assumptions

    bf_hot_metal = sum(value(model.bf_hot_metal_driver_t[t]) for t in model.TIME)
    dry_coal = sum(value(model.cog_dry_coal_driver_t[t]) for t in model.TIME)
    bof_liquid = value(model.bof_route_total)

    assert bf_hot_metal == pytest.approx(
        assumptions.wag.bf_hot_metal_t_per_t_bof_liquid_steel * bof_liquid,
        abs=1e-8,
    )
    assert dry_coal == pytest.approx(assumptions.wag.dry_coal_t_per_t_hot_metal * bf_hot_metal, abs=1e-8)
    assert float(row["bfg_generated_gj"]) == pytest.approx(assumptions.wag.bfg_gj_per_t_hot_metal * bf_hot_metal)
    assert float(row["cog_generated_gj"]) == pytest.approx(assumptions.wag.cog_gj_per_t_dry_coal * dry_coal)
    assert float(row["bofg_generated_gj"]) == pytest.approx(assumptions.wag.bofg_gj_per_t_liquid_steel * bof_liquid)
    assert float(row["bfg_generated_gj"]) != pytest.approx(
        assumptions.wag.bfg_gj_per_t_hot_metal * value(model.horizon_final_product_output),
        abs=1e-6,
    )


def test_integrated_wag_totals_reconcile_to_static_accounting_snapshot(smoke_payload: dict):
    static = _csv(STATIC_ACCOUNTING_RESULTS)
    rows = {row["smoke_case"]: row for row in smoke_payload["results"]}
    comparisons = {
        "c0_integrated_central": ("C0_current_BF_BOF_reference", "c0_reference"),
        "c1_central_integrated": ("C1_phase1_hybrid_BF_BOF_NG_DRP_EAF", "c1_central"),
    }
    for smoke_case, (configuration_id, scenario_id) in comparisons.items():
        expected = static.loc[
            static["configuration_id"].eq(configuration_id)
            & static["scenario_id"].eq(scenario_id)
            & static["boundary_case_id"].eq("central_proxy_site_electricity_boundary")
        ].iloc[0]
        row = rows[smoke_case]
        assert float(row["bfg_generated_gj"]) == pytest.approx(float(expected["bfg_gj_24h"]), abs=1e-6)
        assert float(row["cog_generated_gj"]) == pytest.approx(float(expected["cog_gj_24h"]), abs=1e-6)
        assert float(row["bofg_generated_gj"]) == pytest.approx(float(expected["bofg_gj_24h"]), abs=1e-6)
        assert float(row["total_wag_generated_gj"]) == pytest.approx(float(expected["total_wag_gj_24h"]), abs=1e-6)


def test_objective_flags_are_not_monetary_without_prices(smoke_payload: dict):
    for row in smoke_payload["results"]:
        assert row["objective_type"] == "energy_emissions_diagnostic"
        assert row["static_cost_result"] == "false"
        assert row["monetary_values_ready"] == "false"
        assert row["wag_driver_basis_status"] == "reconciled_s3_1_b"
