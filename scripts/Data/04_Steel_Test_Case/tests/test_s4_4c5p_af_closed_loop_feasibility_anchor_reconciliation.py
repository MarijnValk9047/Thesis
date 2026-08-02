from __future__ import annotations

from pathlib import Path
import sys
from collections import defaultdict

import pytest

STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    _annual_accounting_residuals_close,
    _annual_anchor_family_summary,
    _annual_equivalent_views,
    _annual_model_metrics,
    _annual_physical_boundary_ledger,
    _first_order_full_site_co2_ledger,
    _full_site_coverage_share_rows,
    _generator_electricity_reporting_split,
    _parameter_range_exception_report,
    _annual_origin_ledger,
    _annual_c0_downstream_origin_ledger,
    _anchor_rows,
    _campaign_progress_reference_routing,
    _downstream_origin_routing,
    _execution_material_residuals,
    _file_fingerprints,
    _input_manifest,
    _model_target_multiplier,
    _planning_horizon_cost_preservation_validation,
    _rolling_production_progress_contract,
    _mode_comparison_rows,
    _next_inventory_overrides,
    _reference_definition,
    _scrap_supply_ledger,
    _source_bounded_sensitivity_levers,
    _c0_downstream_routing,
    HOURLY_REPORTING_MATERIAL_TOLERANCE_T,
    _generator_unit_interface,
    _electricity_boundary_levers,
    _c1_source_backed_energy_boundary,
    _user_authorized_emulation_overlays,
    _config,
    _deterministic_cost_policy,
    _external_procurement_flow_coefficients,
    _governed_cost_ledger_validation,
    _procurement_cost_ledger,
    _procurement_cost_summaries,
    _validate_required_solver_family,
)
import steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation as closed_loop
from steel.validation_tolerance_policy import hourly_money_identity_record
from steel.s4_4c_component_ontology import (
    FUTURE_DETERMINISTIC_COST_RESULT_FIELDS,
    load_future_cost_boundary_contract,
    load_route_boundary_contract,
)
from steel.rolling_production_quota import build_rolling_production_quota_plan


def test_handoff_uses_only_represented_inventory_fields() -> None:
    overrides = _next_inventory_overrides(
        {
            "C0_current_BF_BOF_reference": {
                "coke_inventory_t": "1", "sinter_inventory_t": "2", "hot_iron_inventory_t": "3", "cold_slab_inventory_t": "4",
            },
            "C1_phase1_BF_BOF_plus_DRP_EAF": {
                "coke_inventory_t": "5", "sinter_inventory_t": "6", "hot_iron_inventory_t": "7", "cold_slab_inventory_t": "8", "DRI_inventory_t": "9",
            },
        }
    )
    assert overrides["C0_current_BF_BOF_reference"]["cold_slab_store_initial_t"] == 4.0
    assert overrides["C1_phase1_BF_BOF_plus_DRP_EAF"]["dri_buffer_initial_t"] == 9.0


def test_planning_horizon_cost_preservation_uses_aggregate_tolerance() -> None:
    primary = 27_073_308.555103
    accepted = _planning_horizon_cost_preservation_validation(
        primary_cost_eur=primary,
        tie_break_cost_eur=27_073_308.565104,
        endpoint_cost_eur=27_073_308.565102998,
    )
    assert accepted["status"] == "pass"
    assert accepted["tie_break"]["raw_residual"] == pytest.approx(0.010001)
    aggregate_tolerance = accepted["tie_break"]["allowed_tolerance"]
    rejected = _planning_horizon_cost_preservation_validation(
        primary_cost_eur=primary,
        tie_break_cost_eur=primary + aggregate_tolerance + 1e-6,
        endpoint_cost_eur=primary,
    )
    assert rejected["status"] == "fail"
    assert hourly_money_identity_record("hour[0]", 0.010001)["status"] == "fail"


def test_handoff_prefers_unrounded_controller_state() -> None:
    overrides = _next_inventory_overrides(
        {
            "C0_current_BF_BOF_reference": {
                "coke_inventory_t": "1.0",
                "coke_inventory_t_unrounded": "1.0000004",
                "sinter_inventory_t": "2.0",
                "sinter_inventory_t_unrounded": "2.0000004",
                "hot_iron_inventory_t": "3.0",
                "hot_iron_inventory_t_unrounded": "3.0000004",
                "cold_slab_inventory_t": "4.0",
                "cold_slab_inventory_t_unrounded": "4.0000004",
            },
            "C1_phase1_BF_BOF_plus_DRP_EAF": {
                "coke_inventory_t": "5.0",
                "coke_inventory_t_unrounded": "5.0000004",
                "sinter_inventory_t": "6.0",
                "sinter_inventory_t_unrounded": "6.0000004",
                "hot_iron_inventory_t": "7.0",
                "hot_iron_inventory_t_unrounded": "7.0000004",
                "cold_slab_inventory_t": "8.0",
                "cold_slab_inventory_t_unrounded": "8.0000004",
                "DRI_inventory_t": "9.0",
                "DRI_inventory_t_unrounded": "9.0000004",
            },
        }
    )
    assert (
        overrides["C0_current_BF_BOF_reference"]["coke_store_initial_t"]
        == 1.0000004
    )
    assert (
        overrides["C1_phase1_BF_BOF_plus_DRP_EAF"][
            "dri_buffer_initial_t"
        ]
        == 9.0000004
    )


def test_anchor_register_keeps_active_target_as_denominator_warning() -> None:
    metrics = {
        "C0_current_BF_BOF_reference": defaultdict(float, {"endogenous_liquid_steel_mt_y": 2.0}),
        "C1_phase1_BF_BOF_plus_DRP_EAF": defaultdict(float, {"endogenous_liquid_steel_mt_y": 2.0}),
    }
    rows = _anchor_rows(metrics)
    target_rows = [row for row in rows if row.get("anchor_id") == "active_steel_target_6_75"]
    assert len(target_rows) == 2
    assert all(row["comparability_status"] == "scenario_definition" for row in target_rows)
    assert all(row["scenario_definition_status"] == "scenario_definition" for row in target_rows)


def test_explicit_thesis_scale_quota_aligns_model_target_with_final_deadline() -> None:
    plan = build_rolling_production_quota_plan(
        planning_horizon_hours=168,
        execution_block_hours=24,
        quota_per_execution_block_t=18493.1506849315,
    )
    multiplier = _model_target_multiplier({"base_quota_per_execution_block_t": 5905.2}, plan)
    assert abs(5905.2 * multiplier - plan.total_quota_t) < 1e-6


def test_rolling_production_progress_carries_credit_into_next_window() -> None:
    plan = build_rolling_production_quota_plan(
        planning_horizon_hours=168,
        execution_block_hours=24,
        quota_per_execution_block_t=18493.1506849315,
    )
    base_multiplier = _model_target_multiplier(
        {"base_quota_per_execution_block_t": 5905.2}, plan
    )
    credit = 0.005 * plan.quota_per_execution_block_t
    cumulative_before = {
        configuration: 2.0 * plan.quota_per_execution_block_t + credit
        for configuration in (
            "C0_current_BF_BOF_reference",
            "C1_phase1_BF_BOF_plus_DRP_EAF",
        )
    }

    contract = _rolling_production_progress_contract(
        plan=plan,
        replan_index=2,
        cumulative_before=cumulative_before,
        base_target_multiplier=base_multiplier,
        enabled=True,
    )

    for configuration in cumulative_before:
        state = contract["state_by_configuration"][configuration]
        deadlines = contract["deadline_targets_by_configuration_t"][configuration]
        assert state["carried_credit_before_t"] == pytest.approx(credit)
        assert state["next_execution_target_t"] == pytest.approx(
            plan.quota_per_execution_block_t - credit
        )
        assert deadlines[24] == pytest.approx(
            plan.quota_per_execution_block_t - credit
        )
        assert deadlines[168] == pytest.approx(
            plan.total_quota_t - credit
        )
        assert (
            5905.2
            * contract["target_multiplier_by_configuration"][configuration]
        ) == pytest.approx(plan.total_quota_t - credit)


def test_disabled_rolling_production_progress_preserves_legacy_window_targets() -> None:
    plan = build_rolling_production_quota_plan(
        planning_horizon_hours=168,
        execution_block_hours=24,
        quota_per_execution_block_t=18493.1506849315,
    )
    base_multiplier = _model_target_multiplier(
        {"base_quota_per_execution_block_t": 5905.2}, plan
    )
    contract = _rolling_production_progress_contract(
        plan=plan,
        replan_index=3,
        cumulative_before={
            "C0_current_BF_BOF_reference": 4.0
            * plan.quota_per_execution_block_t,
            "C1_phase1_BF_BOF_plus_DRP_EAF": 4.0
            * plan.quota_per_execution_block_t,
        },
        base_target_multiplier=base_multiplier,
        enabled=False,
    )

    assert contract["progress_target_by_configuration_t"] == {}
    assert all(
        multiplier == pytest.approx(base_multiplier)
        for multiplier in contract["target_multiplier_by_configuration"].values()
    )
    assert all(
        deadlines == plan.cumulative_deadline_targets_t
        for deadlines in contract[
            "deadline_targets_by_configuration_t"
        ].values()
    )


def test_gate2_cases_keep_zero_import_and_mer_cap_separate() -> None:
    endogenous = _downstream_origin_routing(
        {"c1_boundary_case": "endogenous_6_75", "imported_slab_annual_cap_mt_y": 0.0},
        horizon_hours=168,
    )
    mer = _downstream_origin_routing(
        {"c1_boundary_case": "mer_site_product", "imported_slab_annual_cap_mt_y": 0.6},
        horizon_hours=168,
    )
    assert endogenous["imported_slab_max_t_h"] == 0.0
    assert endogenous["imported_slab_horizon_cap_t"] == 0.0
    assert endogenous["minimize_imported_slab"] is False
    assert abs(float(mer["imported_slab_horizon_cap_t"]) - 600_000.0 * 168 / 8760) < 1e-9
    assert mer["minimize_imported_slab"] is True
    assert "eaf_dsp_share" not in mer


def test_campaign_progress_reference_bands_subtract_executed_route_output() -> None:
    routing = {
        "reference_validation_bands": {
            "bof_liquid_steel": {"lower_t": 1.0, "upper_t": 2.0},
        }
    }
    definitions = [
        {
            "configuration": "C0",
            "metric": "bof_liquid_steel",
            "annual_band_lower_mt_y": 7.0,
            "annual_band_upper_mt_y": 7.1,
        }
    ]
    executed = 7_000_000.0 * 48.0 / 8760.0 - 10.0
    resolved = _campaign_progress_reference_routing(
        routing,
        definition_rows=definitions,
        configuration="C0_current_BF_BOF_reference",
        executed_rows=[
            {
                "configuration_id": "C0_current_BF_BOF_reference",
                "C0_BOF_crude_steel_output_t": executed,
            }
        ],
        executed_hours_before=48,
        deadline_hours=[24, 48],
    )

    assert resolved is not None
    first = resolved["reference_deadline_bands"]["bof_liquid_steel"][24]
    final = resolved["reference_deadline_bands"]["bof_liquid_steel"][48]
    assert first["lower_t"] == pytest.approx(
        7_000_000.0 * 72.0 / 8760.0 - executed
    )
    assert final["upper_t"] == pytest.approx(
        7_100_000.0 * 96.0 / 8760.0 - executed
    )
    assert resolved["reference_validation_bands"]["bof_liquid_steel"] == final


def test_gate2_downstream_overrides_stay_inside_governed_source_ranges() -> None:
    routing = _downstream_origin_routing(
        {
            "c1_boundary_case": "mer_site_product",
            "imported_slab_annual_cap_mt_y": 0.6,
            "hsm_slab_input_t_per_t_hrc": 1.07,
            "dsp_liquid_steel_input_t_per_t_coil": 1.03,
        },
        horizon_hours=168,
    )
    assert abs(float(routing["hsm_final_t_per_t_slab"]) - 1 / 1.07) < 1e-12
    assert routing["dsp_liquid_steel_input_t_per_t_coil"] == 1.03
    with pytest.raises(ValueError, match="Gate-2 development range"):
        _downstream_origin_routing(
            {
                "c1_boundary_case": "mer_site_product",
                "imported_slab_annual_cap_mt_y": 0.6,
                "hsm_slab_input_t_per_t_hrc": 1.10,
            },
            horizon_hours=168,
        )


def test_gate2_named_scrap_caps_convert_from_annual_to_rolling_horizon() -> None:
    ledger = _scrap_supply_ledger(
        {
            "scrap_supply_ledger": {
                "annual_site_scrap_cap_t_y": 1_900_000.0,
                "annual_bof_scrap_cap_t_y": 1_000_000.0,
                "annual_eaf_scrap_cap_t_y": 1_800_000.0,
            }
        },
        horizon_hours=168,
    )
    assert ledger is not None
    assert abs(ledger["site_total_scrap_supply_cap_t"] - 1_900_000.0 * 168 / 8760) < 1e-9
    assert abs(ledger["bof_scrap_supply_cap_t"] - 1_000_000.0 * 168 / 8760) < 1e-9
    assert abs(ledger["eaf_scrap_supply_cap_t"] - 1_800_000.0 * 168 / 8760) < 1e-9
    assert (
        ledger["bof_scrap_supply_cap_t"] + ledger["eaf_scrap_supply_cap_t"]
        > ledger["site_total_scrap_supply_cap_t"]
    )
    assert abs(
        ledger["site_total_scrap_supply_deadline_caps_t"][24]
        - 1_900_000.0 * 24 / 8760
    ) < 1e-9
    assert 168 not in ledger["site_total_scrap_supply_deadline_caps_t"]


def test_single_execution_day_scrap_ledger_uses_only_static_horizon_caps() -> None:
    ledger = _scrap_supply_ledger(
        {
            "scrap_supply_ledger": {
                "annual_site_scrap_cap_t_y": 1_900_000.0,
                "annual_bof_scrap_cap_t_y": 1_000_000.0,
                "annual_eaf_scrap_cap_t_y": 1_800_000.0,
            }
        },
        horizon_hours=24,
        execution_block_hours=24,
        deadline_hours=[24],
    )
    assert ledger is not None
    assert "site_total_scrap_supply_deadline_caps_t" not in ledger
    assert ledger["site_total_scrap_supply_cap_t"] == pytest.approx(
        1_900_000.0 * 24 / 8760
    )


def test_gate3_boundary_ledger_keeps_residuals_and_mode_b_out_of_dispatch() -> None:
    ledger = _annual_physical_boundary_ledger(
        [
            {
                "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
                "final_product_output_t": 10.0,
                "C1_imported_slab_to_HSM_t_h": 1.0,
                "C1_BOF_scrap_input_t_h": 2.0,
                "C1_EAF_scrap_input_t_h": 3.0,
                "BFG_generated_mwh": 5.0,
                "BFG_to_BF_hot_stove_mwh": 3.0,
                "BFG_flared_mwh": 2.0,
                "BFG_balance_residual_mwh": 0.0,
                "gross_electricity_mwh": 10.0,
                "wag_electricity_mwh": 2.0,
                "net_grid_import_mwh": 8.0,
                "ASU_oxygen_electricity_mwh": 2.0,
                "Linde_N2_auxiliary_electricity_mwh": 1.0,
                "linde_split_residual_mwh": 0.0,
                "electricity_bucket_sum_residual_mwh": 0.0,
                "generator_unit_interface_active": 1.0,
                "generator_named_ng_mwh": 2.0,
                "VN25_total_fuel_mwh": 10.0,
                "VN25_electricity_mwh": 3.45,
                "VN25_conversion_loss_mwh": 6.55,
                "IJ01_total_fuel_mwh": 1.0,
                "IJ01_electricity_mwh": 0.0,
                "IJ01_deferred_conversion_mwh": 1.0,
                "natural_gas_nm3": 100.0,
                "NG_to_HSM_mwh": 1.0,
                "BFG_explicit_combustion_co2_t": 4.0,
                "BFG_flare_co2_t": 1.0,
            }
        ]
    )
    keyed = {(row["ledger_family"], row["component"]): row for row in ledger}
    assert keyed[("electricity", "gross_total_minus_internal_minus_import_plus_export")]["annual_value"] == 0.0
    assert keyed[("electricity", "full_site_anchor_minus_represented_gross")]["included_in_physical_balance"] == "false"
    assert keyed[("named_NG", "full_site_anchor_minus_named_NG")]["included_in_mode_b_co2"] == "false"
    assert keyed[("Mode_B_CO2", "represented_Mode_B_explicit_fuel")]["annual_value"] > keyed[("Mode_B_CO2", "represented_WAG_combustion_and_flare")]["annual_value"]
    assert keyed[("Mode_B_CO2", "full_site_Scope1_anchor_minus_Mode_B")]["included_in_mode_b_co2"] == "false"
    assert keyed[("generator", "VN25_fuel_minus_electricity_minus_loss")]["annual_value"] == 0.0
    assert keyed[("generator", "IJ01_fuel_minus_electricity_minus_deferred")]["annual_value"] == 0.0
    assert keyed[("named_NG", "VN25_generator")]["annual_value"] > 0.0
    assert keyed[("electricity_decomposition", "ASU_oxygen")]["annual_value"] == 2.0 * 8760
    assert keyed[("electricity_decomposition", "Linde_N2_auxiliary")]["annual_value"] == 1.0 * 8760
    assert keyed[("electricity_decomposition", "Linde_total_minus_ASU_minus_N2")]["annual_value"] == 0.0


def test_gate3_annualised_accounting_tolerance_accepts_only_roundoff() -> None:
    row = {"flow_role": "accounting_residual", "annual_value": 0.00876}
    assert _annual_accounting_residuals_close([row])
    row["annual_value"] = 0.01001
    assert not _annual_accounting_residuals_close([row])


def test_gate3_input_fingerprints_are_stable_and_repo_relative() -> None:
    repo_path = STEEL_ROOT / "configs" / "steel_gate3_annual_physical_anchor_reconciliation.yaml"
    first = _file_fingerprints([repo_path])
    second = _file_fingerprints([repo_path])
    assert first == second
    assert not Path(first[0]["path"]).is_absolute()
    assert len(first[0]["sha256"]) == 64
    manifest = _input_manifest(repo_path)
    assert len(manifest["active_model_input_files"]) >= 16
    assert len(manifest["direct_source_evidence_files"]) >= 13
    assert any(
        row["path"].replace("\\", "/").endswith(
            "c5_component_ontology/c5_fixed_reference_scenario_contract.csv"
        )
        for row in manifest["direct_source_evidence_files"]
    )
    evidence_names = {Path(row["path"]).name for row in manifest["direct_source_evidence_files"]}
    assert {"c5_route_boundary_contract.csv", "c5_future_cost_boundary_contract.csv", "DRP_Parameters.md"}.issubset(evidence_names)


def test_fixed_reference_cost_config_activates_only_governed_procurement_costs() -> None:
    config_path = STEEL_ROOT / "configs" / "steel_fixed_reference_deterministic_cost.yaml"
    config = _config(config_path)
    contracts = load_future_cost_boundary_contract()
    policy = _deterministic_cost_policy(config, contracts, horizon_hours=168)
    assert config["execution_mode"] == "fixed_reference_cost"
    assert config["market_prices_enabled"] is False
    assert config["product_revenue_enabled"] is False
    assert config["co2_ets_objective_enabled"] is False
    assert policy is not None
    assert len(policy["flows"]) == sum(
        row["objective_enabled"] == "true" for row in contracts
    )
    assert {
        row["price_id"] for row in policy["flows"]
    } == {
        "grid_electricity_flat_nl",
        "natural_gas_ttf_proxy",
        "coking_coal_hcc_proxy",
        "pci_coal_proxy",
        "iron_ore_62fe_proxy",
        "imported_dr_pellets_proxy",
        "purchased_scrap_proxy",
        "imported_slab_proxy",
    }
    assert all(len(row["price_eur_by_hour"]) == 168 for row in policy["flows"])


def test_c0_generator_ng_cost_does_not_depend_on_legacy_site_bridge() -> None:
    config = _config(
        STEEL_ROOT / "configs" / "steel_fixed_reference_deterministic_cost.yaml"
    )
    config["c0_aggregate_generator_technical_interface"] = {"enabled": True}
    config["c0_full_site_energy_bridge"] = {"enabled": False}
    policy = _deterministic_cost_policy(
        config, load_future_cost_boundary_contract(), horizon_hours=168
    )
    assert policy is not None
    flow_ids = {row["flow_id"] for row in policy["flows"]}
    assert "C0_NG_GENERATOR" in flow_ids
    assert "C0_NG_FIXED_FULL_SITE" not in flow_ids
    assert "C0_NG_FLEXIBLE_OTHER_SITE_HEAT" not in flow_ids


def test_external_procurement_coefficients_resolve_from_route_contract() -> None:
    coefficients = _external_procurement_flow_coefficients(
        {"external_procurement_flows_enabled": True},
        load_route_boundary_contract(),
    )
    assert coefficients == {
        "pci_t_per_t_hot_metal": pytest.approx(0.162),
        "pefa_iron_ore_t_per_t_pellets": pytest.approx(0.95),
    }


def test_procurement_cost_ledger_reconciles_component_route_and_configuration() -> None:
    config = _config(
        STEEL_ROOT / "configs" / "steel_fixed_reference_deterministic_cost.yaml"
    )
    policy = _deterministic_cost_policy(
        config, load_future_cost_boundary_contract(), horizon_hours=168
    )
    assert policy is not None
    row = {
        "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
        "replan_index": 0,
        "hour_index": 0,
        "executed_hour_index": 0,
        "final_product_output_t": 10.0,
    }
    for flow in policy["flows"]:
        if flow["configuration"] in {"C1", "both"}:
            for attribute in flow["physical_quantity_attribute"].split(";"):
                row[attribute] = 1.0
    ledger = _procurement_cost_ledger([row], policy, run_id="test")
    validation = _governed_cost_ledger_validation(config, ledger)
    assert validation["status"] == "pass"
    mutated = [dict(item) for item in ledger]
    natural_gas_row = next(
        item for item in mutated if item["price_id"] == "natural_gas_ttf_proxy"
    )
    natural_gas_row["price_eur_per_unit"] = (
        float(natural_gas_row["price_eur_per_unit"]) + 1.0
    )
    mutated_validation = _governed_cost_ledger_validation(config, mutated)
    assert mutated_validation["status"] == "fail"
    assert mutated_validation["price_input_fingerprints_valid"] is False
    summaries, components, routes = _procurement_cost_summaries(ledger, [row])
    assert ledger
    assert summaries[0]["executed_final_product_t"] == 10.0
    assert summaries[0]["executed_procurement_cost_eur"] == pytest.approx(
        sum(float(item["cost_eur"]) for item in ledger)
    )
    assert sum(float(item["cost_eur"]) for item in components) == pytest.approx(
        summaries[0]["executed_procurement_cost_eur"]
    )
    assert sum(float(item["cost_eur"]) for item in routes) == pytest.approx(
        summaries[0]["executed_procurement_cost_eur"]
    )


def test_cost_policy_validates_full_forecast_then_uses_truncated_prefix(
    monkeypatch,
) -> None:
    config = _config(
        STEEL_ROOT / "configs" / "steel_hourly_da_dplus4_point_forecast_integration.yaml"
    )
    captured: dict[str, int] = {}

    def fake_price_slice(**kwargs):
        captured["planning_horizon_hours"] = int(
            kwargs["planning_horizon_hours"]
        )
        return [
            {"price_eur_per_mwh_e": float(hour)} for hour in range(120)
        ]

    monkeypatch.setattr(closed_loop, "build_rolling_price_slice", fake_price_slice)
    policy = _deterministic_cost_policy(
        config,
        load_future_cost_boundary_contract(),
        horizon_hours=96,
        nominal_forecast_horizon_hours=120,
        replan_index=3,
    )
    assert policy is not None
    assert captured["planning_horizon_hours"] == 120
    grid_flows = [
        row for row in policy["flows"]
        if row["price_id"] == "grid_electricity_flat_nl"
    ]
    assert grid_flows
    assert all(len(row["price_eur_by_hour"]) == 96 for row in grid_flows)
    assert all(row["price_eur_by_hour"][-1] == 95.0 for row in grid_flows)


def test_gate3_anchor_family_summary_counts_primary_and_context_separately() -> None:
    summaries = {
        (row["configuration"], row["independent_anchor_family"]): row
        for row in _annual_anchor_family_summary(
            [
                {
                    "anchor_id": "primary",
                    "configuration": "C0",
                    "anchor_category": "HSM",
                    "comparability_status": "directly_comparable",
                    "scenario_definition_status": "validation_candidate",
                    "signed_residual_pct": -5.0,
                    "source_rank": "Rank 1",
                    "use_in_primary_score": "yes",
                },
                {
                    "anchor_id": "context",
                    "configuration": "C1",
                    "anchor_category": "electricity",
                    "comparability_status": "partially_comparable_reporting_only",
                    "scenario_definition_status": "validation_candidate",
                    "signed_residual_pct": -4.0,
                    "source_rank": "Rank 3",
                    "use_in_primary_score": "no",
                },
                {
                    "anchor_id": "active_steel_target_6_75",
                    "configuration": "C0",
                    "anchor_category": "production",
                    "comparability_status": "scenario_definition",
                    "scenario_definition_status": "scenario_definition",
                    "signed_residual_pct": 0.0,
                    "source_rank": "Rank 1",
                    "use_in_primary_score": "yes",
                },
            ]
        )
    }
    assert summaries[("C0", "HSM")]["primary_pair_below_7_5pct"] == "yes"
    assert summaries[("C1", "electricity")]["primary_pair_below_7_5pct"] == "no"
    assert summaries[("C1", "electricity")]["contextual_pair_below_7_5pct"] == "yes"
    assert summaries[("C0", "production")]["coverage_status"] == "coverage_gap"


def test_hsm_slab_input_cannot_be_labelled_as_hrc_output() -> None:
    metrics, _ = _annual_model_metrics(
        [
            {
                "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
                "C1_retained_HSM_input_t_h": 106.0,
                "C1_HSM_final_product_output_t": 100.0,
                "C1_HSM_material_loss_t": 6.0,
            }
        ]
    )
    assert metrics["C1_phase1_BF_BOF_plus_DRP_EAF"]["hsm_slab_input_mt_y"] == pytest.approx(0.92856)
    assert metrics["C1_phase1_BF_BOF_plus_DRP_EAF"]["hsm_hrc_output_mt_y"] == pytest.approx(0.876)
    hsm_row = next(
        row for row in _anchor_rows(metrics)
        if row.get("anchor_id") == "c1_hsm_wbw_raw_output_5_5"
    )
    assert hsm_row["model_metric"] == "hsm_hrc_output_mt_y"
    assert hsm_row["model_annualised_value"] == pytest.approx(0.876)


def test_unit_match_alone_does_not_make_site_electricity_comparable() -> None:
    metrics = {
        "C0_current_BF_BOF_reference": defaultdict(float, {
            "gross_electricity_twh_y": 3.0,
            "endogenous_liquid_steel_mt_y": 7.0,
        })
    }
    row = next(
        row for row in _anchor_rows(metrics)
        if row.get("anchor_id") == "c0_total_site_electricity_3twh_context"
    )
    assert row["unit_match"] == "true"
    assert row["comparability_status"] == "partially_comparable_reporting_only"
    assert row["absolute_residual_pct"] == 0.0
    c0_official = next(
        row for row in _anchor_rows({
            "C0_current_BF_BOF_reference": defaultdict(float, {
                "gross_electricity_pj_y": 8.0,
                "endogenous_liquid_steel_mt_y": 7.0,
            })
        })
        if row.get("anchor_id") == "c0_official_total_site_electricity_13_7pj_missing"
    )
    assert c0_official["model_metric"] == "gross_electricity_pj_y"
    assert c0_official["unit_match"] == "true"
    assert c0_official["comparability_status"] == "partially_comparable_reporting_only"


def test_generator_fuel_anchor_cannot_use_all_named_site_ng() -> None:
    metrics = {
        "C1_phase1_BF_BOF_plus_DRP_EAF": defaultdict(float, {
            "generator_wag_pj_y": 10.5,
            "represented_ng_pj_y": 40.0,
            "endogenous_liquid_steel_mt_y": 6.5,
        })
    }
    row = next(
        row for row in _anchor_rows(metrics)
        if row.get("anchor_id") == "c1_generator_total_with_flare_14_6"
    )
    assert row["model_metric"] == "generator_wag_pj_y"
    assert row["comparability_status"] == "not_comparable"
    assert "generator NG" in row["explicit_exclusion_reason"]


def test_reference_definition_rows_cannot_qualify_as_validation() -> None:
    metrics = {
        "C0_current_BF_BOF_reference": defaultdict(float, {
            "endogenous_liquid_steel_mt_y": 7.2,
            "hsm_hrc_output_mt_y": 5.4,
            "dsp_output_mt_y": 1.5,
            "dsp_topology_active": True,
        }),
        "C1_phase1_BF_BOF_plus_DRP_EAF": defaultdict(float, {
            "endogenous_liquid_steel_mt_y": 6.8,
            "hsm_hrc_output_mt_y": 5.5,
            "dsp_output_mt_y": 1.5,
            "dsp_topology_active": True,
            "imported_slab_mt_y": 0.6,
        }),
    }
    rows = _anchor_rows(metrics, execution_mode="reference_validation")
    defined = [row for row in rows if row.get("scenario_definition_status") == "scenario_definition"]
    assert defined
    assert all(row["comparability_status"] == "scenario_definition" for row in defined)
    summaries = _annual_anchor_family_summary(rows)
    c1_summaries = [row for row in summaries if row["configuration"] == "C1_phase1_BF_BOF_plus_DRP_EAF"]
    assert all(row["primary_pair_below_7_5pct"] == "no" for row in c1_summaries)
    assert next(
        row for row in rows
        if row.get("anchor_id") == "c0_public_liquid_steel_7_2"
    )["scenario_definition_status"] == "validation_candidate"
    c0_defined = _anchor_rows(
        metrics,
        execution_mode="reference_validation",
        additional_reference_definition_ids={
            "c0_public_liquid_steel_7_2",
            "c0_hsm_wbw_raw_output_5_4",
            "c0_dsp_raw_output_1_5",
        },
    )
    assert next(
        row for row in c0_defined
        if row.get("anchor_id") == "c0_public_liquid_steel_7_2"
    )["comparability_status"] == "scenario_definition"

    propagated = _anchor_rows(
        metrics,
        execution_mode="endogenous_feasibility",
        additional_reference_definition_ids={
            "c0_public_liquid_steel_7_2",
            "c1_public_liquid_steel_6_8",
            "c1_final_product_proxy_7_0",
        },
    )
    for anchor_id in {
        "c0_public_liquid_steel_7_2",
        "c1_public_liquid_steel_6_8",
        "c1_final_product_proxy_7_0",
    }:
        row = next(item for item in propagated if item.get("anchor_id") == anchor_id)
        assert row["scenario_definition_status"] == "scenario_definition"
        assert row["comparability_status"] == "scenario_definition"


def test_configuration_family_scoring_does_not_mask_c0_with_c1() -> None:
    summaries = _annual_anchor_family_summary(
        [
            {"anchor_id": "c0", "configuration": "C0", "anchor_category": "WAG", "comparability_status": "directly_comparable", "scenario_definition_status": "validation_candidate", "signed_residual_pct": 10.0, "source_rank": "Rank 1", "use_in_primary_score": "yes"},
            {"anchor_id": "c1", "configuration": "C1", "anchor_category": "WAG", "comparability_status": "directly_comparable", "scenario_definition_status": "validation_candidate", "signed_residual_pct": 1.0, "source_rank": "Rank 1", "use_in_primary_score": "yes"},
        ]
    )
    keyed = {(row["configuration"], row["independent_anchor_family"]): row for row in summaries}
    assert keyed[("C0", "WAG")]["primary_pair_below_7_5pct"] == "no"
    assert keyed[("C1", "WAG")]["primary_pair_below_7_5pct"] == "yes"


def test_annual_equivalent_views_never_label_transient_as_annual_truth() -> None:
    executed = [
        {"configuration_id": "C0_current_BF_BOF_reference", "replan_index": index, "final_product_output_t": 1.0}
        for index in range(7)
    ]
    planned = [{"configuration_id": "C0_current_BF_BOF_reference", "final_product_output_t": 1.0}]
    rows = _annual_equivalent_views(executed, planned)
    assert {row["view_id"] for row in rows} == {
        "complete_executed_blocks", "first_block_transient", "stable_executed_blocks", "first_planned_168h_horizon"
    }
    assert all(row["truth_status"] == "representative_deterministic_annual_equivalent_not_simulated_year" for row in rows)


def test_annual_accounting_residual_check_covers_steam_and_energy_units() -> None:
    assert _annual_accounting_residuals_close(
        [
            {"flow_role": "accounting_residual", "annual_value": 0.009, "unit": "MWh/y"},
            {"flow_role": "accounting_residual", "annual_value": -0.009, "unit": "t/y"},
        ]
    )
    assert not _annual_accounting_residuals_close(
        [{"flow_role": "accounting_residual", "annual_value": 0.011, "unit": "t/y"}]
    )
    assert HOURLY_REPORTING_MATERIAL_TOLERANCE_T == 3e-5


def test_reference_definition_scales_raw_mer_rows_and_uses_cumulative_bands() -> None:
    config = {
        "execution_mode": "reference_validation",
        "annual_reference_target_mt_y": 6.75,
        "hsm_slab_input_t_per_t_hrc": 1.06,
        "dsp_liquid_steel_input_t_per_t_coil": 1.05,
        "reference_validation": {
            "band_relative_tolerance": 0.005,
            "c1_liquid_steel_raw_mt_y": 6.8,
            "c1_bof_raw_mt_y": 3.4,
            "c1_eaf_raw_mt_y": 3.3,
            "c1_hsm_raw_mt_y": 5.5,
            "c1_dsp_raw_mt_y": 1.5,
            "c1_imported_slab_raw_mt_y": 0.6,
        },
    }
    rows, c0_routing, c1_bands = _reference_definition(config, horizon_hours=168)
    assert len(rows) == 5
    assert c0_routing is None and c1_bands is not None
    c1_hsm = next(row for row in rows if row["configuration"] == "C1" and row["metric"] == "hsm_final_output")
    assert c1_hsm["active_scaled_central_mt_y"] == pytest.approx(6.75 * 5.5 / 7.0)
    assert c1_bands["imported_slab"]["upper_t"] <= 600_000 * 168 / 8760
    assert all(row["scenario_definition_status"] == "scenario_definition_excluded_from_validation" for row in rows)


def test_c0_downstream_route_derives_one_material_identity_without_raw_anchor_double_use() -> None:
    config = {
        "annual_reference_target_mt_y": 6.75,
        "c0_downstream_routing": {
            "raw_liquid_steel_mt_y": 7.2,
            "raw_hsm_final_mt_y": 5.4,
            "raw_dsp_final_mt_y": 1.5,
            "bof_hot_metal_t_per_t_liquid_steel": 0.875,
            "bof_scrap_t_per_t_liquid_steel": 0.208,
            "annual_bof_scrap_cap_mt_y": 1.5,
            "dsp_liquid_steel_input_t_per_t_coil": 1.05,
        },
    }
    routing, central = _c0_downstream_routing(
        config, horizon_hours=168, reference_tolerance=0.005
    )
    assert routing is not None and central is not None
    assert routing["hsm_slab_input_t_per_t_hrc"] == pytest.approx(1.0416666666666667)
    assert routing["hsm_final_t_per_t_slab"] == pytest.approx(0.96)
    assert routing["dsp_final_product_max_t_h"] == pytest.approx(1_500_000 / 8760)
    assert routing["bof_total_scrap_max_t_h"] == pytest.approx(1_500_000 / 8760)
    assert central["hsm_final_output"] + central["dsp_final_output"] == pytest.approx(6.75)
    assert central["bof_liquid_steel"] == pytest.approx(6.75 * 7.2 / 6.9)
    assert routing["raw_anchor_use_policy"] == "derive_conversion_once_not_three_simultaneous_targets"


def test_c0_downstream_route_modes_keep_endogenous_free_and_reference_cumulative() -> None:
    base = {
        "annual_reference_target_mt_y": 6.75,
        "c0_downstream_routing": {
            "raw_liquid_steel_mt_y": 7.2,
            "raw_hsm_final_mt_y": 5.4,
            "raw_dsp_final_mt_y": 1.5,
            "bof_hot_metal_t_per_t_liquid_steel": 0.875,
            "bof_scrap_t_per_t_liquid_steel": 0.208,
            "annual_bof_scrap_cap_mt_y": 1.5,
            "dsp_liquid_steel_input_t_per_t_coil": 1.05,
        },
    }
    rows, endogenous, c1 = _reference_definition(
        {**base, "execution_mode": "endogenous_feasibility"}, horizon_hours=168
    )
    assert rows == [] and c1 is None
    assert endogenous is not None and "reference_validation_bands" not in endogenous


def test_generator_boundary_keeps_carriers_units_and_ng_provenance_separate() -> None:
    source = {
        "vn25_bfg_pj_y": 8.4, "vn25_bofg_pj_y": 1.2, "vn25_cog_pj_y": 0.1,
        "vn25_ng_cap_pj_y": 4.1, "vn25_total_fuel_pj_y": 13.7,
        "vn25_electricity_efficiency": 0.345, "vn25_volume_cap_nm3_h": 600000,
        "ij01_bfg_pj_y": 0.7, "ij01_bofg_pj_y": 0.1, "ij01_cog_pj_y": 0.0,
        "ij01_total_fuel_pj_y": 0.8, "ij01_volume_cap_nm3_h": 300000,
    }
    endogenous = _generator_unit_interface(
        {"repair_stage": "generator", "execution_mode": "endogenous_feasibility", "c1_generator_boundary": source},
        horizon_hours=168,
    )
    assert endogenous is not None
    assert endogenous["ij01_ng_allowed"] is False
    assert endogenous["validation_anchors_pj_y"]["ij01"]["COG"] == 0.0
    reference = _generator_unit_interface(
        {
            "repair_stage": "generator", "execution_mode": "reference_validation",
            "reference_validation": {"band_relative_tolerance": 0.005},
            "c1_generator_boundary": source,
        },
        horizon_hours=168,
    )
    assert reference is not None
    assert reference["validation_anchors_pj_y"]["vn25"]["NG"] == 4.1
    assert reference["ij01_total_fuel_horizon_cap_mwh"] == pytest.approx(
        0.8 * 168 / 8760 / 3.6e-6
    )
    assert reference["ij01_total_fuel_deadline_caps_mwh"][24] == pytest.approx(
        0.8 * 24 / 8760 / 3.6e-6
    )
    assert reference["boundary_role"].endswith("no_fixed_mix")


def test_generator_efficiency_sensitivity_requires_explicit_source_bounded_flag() -> None:
    source = {
        "vn25_bfg_pj_y": 8.4, "vn25_bofg_pj_y": 1.2, "vn25_cog_pj_y": 0.1,
        "vn25_ng_cap_pj_y": 4.1, "vn25_total_fuel_pj_y": 13.7,
        "vn25_electricity_efficiency": 0.34, "vn25_volume_cap_nm3_h": 600000,
        "ij01_bfg_pj_y": 0.7, "ij01_bofg_pj_y": 0.1, "ij01_cog_pj_y": 0.0,
        "ij01_total_fuel_pj_y": 0.8, "ij01_volume_cap_nm3_h": 300000,
    }
    with pytest.raises(Exception, match="must remain"):
        _generator_unit_interface(
            {"repair_stage": "generator", "c1_generator_boundary": source},
            horizon_hours=168,
        )
    resolved = _generator_unit_interface(
        {
            "repair_stage": "generator",
            "c1_generator_boundary": source,
            "source_bounded_generator_efficiency_sensitivity": True,
        },
        horizon_hours=168,
    )
    assert resolved is not None
    assert resolved["vn25_electricity_efficiency"] == 0.34


def test_electricity_boundary_keeps_linde_n2_separate_and_eaf_secondary_named() -> None:
    linde, eaf_secondary, dsp, background, background_by_configuration = _electricity_boundary_levers(
        {
            "repair_stage": "electricity",
            "represented_electricity_boundary": {
                "linde_n2_auxiliary_mw": 45.0,
                "eaf_secondary_electricity_mwh_per_t_ls": 0.031,
                "dsp_electricity_mwh_per_t_coil": 0.056,
            },
        }
    )
    assert linde == 45.0 and eaf_secondary == 0.031 and dsp == 0.056
    assert background == 0.0
    assert set(background_by_configuration.values()) == {0.0}
    with pytest.raises(Exception, match="must remain"):
        _electricity_boundary_levers(
            {
                "repair_stage": "electricity",
                "represented_electricity_boundary": {
                    "linde_n2_auxiliary_mw": 45.0,
                    "eaf_secondary_electricity_mwh_per_t_ls": 0.04,
                },
            }
        )


def test_checkpoint2_background_and_generator_reporting_are_explicit() -> None:
    rows = [
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "represented_gross_electricity_before_background_mwh": 10.0,
            "site_background_electricity_mwh": 2.0,
            "gross_total_electricity_mwh": 12.0,
            "WAG_generator_electricity_mwh": 2.76,
            "NG_generator_electricity_mwh": 0.69,
            "total_generator_electricity_mwh": 3.45,
            "gross_grid_import_mwh": 8.55,
            "gross_grid_export_mwh": 0.0,
            "net_grid_exchange_mwh": 8.55,
            "generator_named_ng_mwh": 2.0,
        }
    ]
    split = _generator_electricity_reporting_split(rows)
    assert split["WAG_generator_electricity_mwh"] == pytest.approx(2.76)
    assert split["NG_generator_electricity_mwh"] == pytest.approx(0.69)
    assert split["generator_internal_electricity_total_mwh"] == pytest.approx(3.45)
    assert split["sum_identity_residual_mwh"] == pytest.approx(0.0)

    ledger = _annual_physical_boundary_ledger(rows)
    keyed = {(row["ledger_family"], row["component"]): row for row in ledger}
    assert keyed[("electricity", "represented_gross_before_background")]["annual_value"] == 87_600.0
    assert keyed[("electricity", "explicit_site_background_electricity")]["annual_value"] == 17_520.0
    assert keyed[("electricity", "gross_total_electricity")]["annual_value"] == 105_120.0
    assert keyed[("electricity", "gross_total_minus_internal_minus_import_plus_export")]["annual_value"] == pytest.approx(0.0)


def test_checkpoint2_first_order_co2_is_separate_and_excludes_drp_capture() -> None:
    rows = [
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "C1_retained_BF_hot_iron_output_t_h": 100.0,
            "C1_BOF_liquid_steel_output_t_h": 80.0,
            "C1_retained_coke_output_t_h": 40.0,
            "C1_retained_sinter_output_t_h": 90.0,
            "PEFA_pellet_output_t": 20.0,
            "C1_EAF_liquid_steel_output_t_h": 30.0,
            "C1_DRP_DRI_output_t_h": 35.0,
            "represented_gross_electricity_before_background_mwh": 10.0,
            "site_background_electricity_mwh": 2.0,
        }
    ]
    ledger = _first_order_full_site_co2_ledger(
        rows,
        constant_mt_y_by_configuration={
            "C1_phase1_BF_BOF_plus_DRP_EAF": 1.0,
        },
    )
    keyed = {row["component"]: row for row in ledger}
    expected_hourly = 1.495 * 100 + 0.0825 * 80 + 0.20 * 40 + 0.248 * 90 + 0.105 * 20 + 0.126 * 30
    assert keyed["selected_process_factor_subtotal"]["annual_co2_t_y"] == pytest.approx(expected_hourly * 8760)
    assert keyed["DRP_capture_stream_CO2"]["annual_co2_t_y"] == 0.0
    assert keyed["DRP_capture_stream_CO2"]["inclusion_status"] == "excluded_capture_stream_not_direct_CO2"
    assert all(row["included_in_mode_b_co2"] == "false" for row in ledger)
    assert keyed["explicit_nonnegative_constant"]["constant_share_of_total"] > 0.0

    coverage = _full_site_coverage_share_rows(rows, ledger)
    electricity = next(row for row in coverage if row["coverage_family"] == "gross_site_electricity")
    co2 = next(row for row in coverage if row["coverage_family"] == "first_order_full_site_CO2")
    assert electricity["physically_represented_share"] == pytest.approx(10 / 12)
    assert electricity["explicit_bridge_share"] == pytest.approx(2 / 12)
    assert co2["explicit_bridge_share"] > 0.0


def test_checkpoint2_first_order_co2_forbids_negative_constant_and_overshoot() -> None:
    rows = [{"configuration_id": "C0_current_BF_BOF_reference", "C0_BF_hot_iron_output_t": 1.0}]
    with pytest.raises(Exception, match="non-negative"):
        _first_order_full_site_co2_ledger(
            rows,
            constant_mt_y_by_configuration={"C0_current_BF_BOF_reference": -0.1},
        )
    with pytest.raises(Exception, match="negative constant is forbidden"):
        _first_order_full_site_co2_ledger(
            rows,
            target_mt_y_by_configuration={"C0_current_BF_BOF_reference": 0.000001},
        )
    with pytest.raises(Exception, match="subtotal plus constant"):
        _first_order_full_site_co2_ledger(
            rows,
            constant_mt_y_by_configuration={"C0_current_BF_BOF_reference": 13.24},
        )


def test_checkpoint2_parameter_range_exceptions_are_traceable() -> None:
    report = _parameter_range_exception_report(
        [
            {
                "parameter_id": "uae_bfg_generation_yield",
                "candidate_value": 2200.0,
                "selected_process": "BF6",
            }
        ]
    )
    assert report[0]["range_status"] == "within_user_authorized_relaxed_range"
    assert report[0]["prior_range_exception_magnitude"] == 200.0
    assert report[0]["relaxed_range_exception_magnitude"] == 0.0
    assert report[0]["user_authorized_sensitivity"] == "true"
    assert report[0]["selection_rule"]

    accepted = _parameter_range_exception_report(
        [{
            "parameter_id": "uae_named_process_electricity_intensity_scaling",
            "candidate_value": 1.1,
            "selected_process": "HSM_rolling",
        }]
    )
    assert accepted[0]["selected_process"] == "HSM_rolling"
    accepted_coking = _parameter_range_exception_report(
        [{
            "parameter_id": "uae_coal_coking_input_scaling",
            "candidate_value": 0.9,
            "selected_process": "KGF1",
        }]
    )
    assert accepted_coking[0]["selected_process"] == "KGF1"
    for parameter_id, selected_process in (
        ("uae_named_process_electricity_intensity_scaling", ""),
        ("uae_named_process_electricity_intensity_scaling", "background"),
        ("uae_coal_coking_input_scaling", ""),
        ("uae_coal_coking_input_scaling", "all_KGF"),
    ):
        with pytest.raises(Exception, match="selected_process"):
            _parameter_range_exception_report(
                [{
                    "parameter_id": parameter_id,
                    "candidate_value": 1.0,
                    "selected_process": selected_process,
                }]
            )


def test_checkpoint2_configuration_specific_background_is_validated() -> None:
    *_, scalar, by_configuration = _electricity_boundary_levers(
        {
            "site_background_electricity_mwh_h": 3.0,
            "site_background_electricity_mwh_h_by_configuration": {
                "C0_current_BF_BOF_reference": 18.0936073059,
                "C1_phase1_BF_BOF_plus_DRP_EAF": 27.9109589041,
            },
        }
    )
    assert scalar == 3.0
    assert by_configuration == {
        "C0_current_BF_BOF_reference": 18.0936073059,
        "C1_phase1_BF_BOF_plus_DRP_EAF": 27.9109589041,
    }
    with pytest.raises(Exception, match="non-negative"):
        _electricity_boundary_levers(
            {
                "site_background_electricity_mwh_h_by_configuration": {
                    "C0_current_BF_BOF_reference": -1.0,
                }
            }
        )


def test_source_backed_drp_eaf_energy_boundary_uses_primary_activity_bases() -> None:
    boundary = _c1_source_backed_energy_boundary(
        {
            "repair_stage": "electricity",
            "c1_source_backed_energy_boundary": {
                "drp_ng_gj_per_t_dri": 9.9,
                "drp_electricity_mwh_per_t_dri": 0.3 / 3.6,
                "eaf_arc_electricity_mwh_per_t_liquid_steel": 1.52 / 3.6,
                "eaf_ng_gj_per_t_liquid_steel": 0.05,
                "natural_gas_lhv_mj_per_nm3": 35.8,
            },
        }
    )
    assert boundary is not None
    assert boundary["drp_ng_gj_per_t_dri"] == 9.9
    assert boundary["drp_electricity_mwh_per_t_dri"] == pytest.approx(0.0833333333)
    assert boundary["eaf_arc_electricity_mwh_per_t_liquid_steel"] == pytest.approx(0.4222222222)


def test_final_acceptance_requires_gurobi_without_highs_fallback() -> None:
    _validate_required_solver_family(
        {"required_solver_family": "gurobi"},
        [{"solver_name": "gurobi"}, {"solver_name": "gurobi_direct"}],
    )
    with pytest.raises(Exception, match="requires"):
        _validate_required_solver_family(
            {"required_solver_family": "gurobi"},
            [{"solver_name": "appsi_highs"}],
        )


def test_route_and_future_cost_contracts_fail_closed_on_objective_inputs() -> None:
    routes = load_route_boundary_contract()
    costs = load_future_cost_boundary_contract()
    assert {row["configuration"] for row in routes} == {"C0", "C1"}
    assert any(row["route_id"] == "C0_FINAL_DENOMINATOR" for row in routes)
    assert any(row["route_id"] == "C1_ORIGIN" for row in routes)
    assert all("band" not in row["endogenous_mode_rule"].lower() for row in routes)

    priced = [row for row in costs if row["included_in_first_deterministic_cost_layer"] == "yes"]
    assert priced
    assert {row["carrier"] for row in priced} == {
        "electricity",
        "NG",
        "coking_coal",
        "PCI",
        "iron_ore",
        "DR_pellets",
        "scrap",
        "imported_slab",
    }
    assert all(row["physical_unit"] and row["activity_driver"] and row["source_locator"] for row in priced)
    assert all(row["residual_status"] == "not_residual" for row in priced)
    assert all(
        row["included_in_first_deterministic_cost_layer"] == "no"
        for row in costs
        if row["residual_status"] != "not_residual"
    )
    assert all(
        row["future_price_unit"] in {"", "not_applicable"}
        for row in costs
        if row["carrier"] in {"BFG", "COG", "BOFG", "WAG_and_NG"}
    )
    assert "total_represented_energy_cost_eur" in FUTURE_DETERMINISTIC_COST_RESULT_FIELDS
    assert "total_represented_procurement_cost_eur" in FUTURE_DETERMINISTIC_COST_RESULT_FIELDS
    assert "cost_by_route_eur" in FUTURE_DETERMINISTIC_COST_RESULT_FIELDS


def test_c0_hsm_anchor_stays_non_comparable_without_output_contract() -> None:
    metrics = {
        "C0_current_BF_BOF_reference": defaultdict(float, {
            "hsm_hrc_output_mt_y": 6.75,
            "hsm_output_contract_active": False,
        })
    }
    row = next(row for row in _anchor_rows(metrics) if row.get("anchor_id") == "c0_hsm_wbw_raw_output_5_4")
    assert row["comparability_status"] == "not_comparable"
    assert row["model_annualised_value"] == ""


def test_mode_comparison_uses_the_two_solved_ledger_values() -> None:
    base = [{
        "configuration_id": "C1", "ledger_family": "WAG", "carrier_or_material": "BFG",
        "flow_role": "generation", "component": "BFG_generated", "annual_value": "10", "unit": "MWh_LHV/y",
    }]
    reference = [{**base[0], "annual_value": "12"}]
    rows = _mode_comparison_rows(
        base, reference, endogenous_run_id="base", reference_run_id="reference"
    )
    assert rows[0]["reference_minus_endogenous"] == 2.0
    assert rows[0]["reference_minus_endogenous_pct"] == 20.0
    assert rows[0]["comparison_basis"].startswith("same p_af solved")


def test_source_bounded_sensitivity_levers_reject_unsupported_values() -> None:
    assert _source_bounded_sensitivity_levers({}) == ("inherited_profile", None)
    assert _source_bounded_sensitivity_levers({
        "generator_interface_cap_mode": "volume_envelope_only",
        "hsm_rolling_electricity_mwh_per_t_hrc": 0.104,
    }) == ("volume_envelope_only", 0.104)
    with pytest.raises(Exception, match="0.028-0.111"):
        _source_bounded_sensitivity_levers({"hsm_rolling_electricity_mwh_per_t_hrc": 0.2})


def test_execution_material_residual_reconstructs_c1_inventory_handoffs() -> None:
    rows = [
        {
            "coke_inventory_t": 11.0,
            "C1_retained_coke_output_t_h": 2.0,
            "C1_retained_BF_coke_demand_t_h": 1.0,
            "sinter_inventory_t": 21.0,
            "C1_retained_sinter_output_t_h": 3.0,
            "C1_retained_BF6_sinter_input_t_h": 2.0,
            "hot_iron_inventory_t": 31.0,
            "C1_retained_BF_hot_iron_output_t_h": 4.0,
            "C1_retained_BOF_hot_iron_input_t_h": 3.0,
            "cold_slab_inventory_t": 41.0,
            "C1_BOF_to_HSM_slab_t_h": 5.0,
            "C1_cold_slab_draw_to_HSM_t_h": 4.0,
            "DRI_inventory_t": 51.0,
            "C1_DRP_DRI_output_t_h": 6.0,
            "C1_EAF_activity_t_DRI_h": 5.0,
        },
        {
            "coke_inventory_t": 12.0,
            "C1_retained_coke_output_t_h": 2.0,
            "C1_retained_BF_coke_demand_t_h": 1.0,
            "sinter_inventory_t": 22.0,
            "C1_retained_sinter_output_t_h": 3.0,
            "C1_retained_BF6_sinter_input_t_h": 2.0,
            "hot_iron_inventory_t": 32.0,
            "C1_retained_BF_hot_iron_output_t_h": 4.0,
            "C1_retained_BOF_hot_iron_input_t_h": 3.0,
            "cold_slab_inventory_t": 42.0,
            "C1_BOF_to_HSM_slab_t_h": 5.0,
            "C1_cold_slab_draw_to_HSM_t_h": 4.0,
            "DRI_inventory_t": 52.0,
            "C1_DRP_DRI_output_t_h": 6.0,
            "C1_EAF_activity_t_DRI_h": 5.0,
        },
    ]
    assert all(abs(value) < 1e-12 for value in _execution_material_residuals("C1_phase1_BF_BOF_plus_DRP_EAF", rows).values())


def test_rolling_origin_ledger_conserves_origins_and_excludes_import_upstream_burdens() -> None:
    rows = [
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "C1_retained_HSM_input_t_h": 11.0,
            "C1_cold_slab_draw_to_HSM_t_h": 6.0,
            "C1_EAF_to_HSM_slab_t_h": 3.0,
            "C1_imported_slab_to_HSM_t_h": 2.0,
            "C1_DSP_final_product_output_t": 1.0,
            "final_product_output_t": 11.0,
        }
    ]
    ledger = _annual_origin_ledger(
        rows,
        {"hsm_final_t_per_t_slab": 10 / 11},
        case_id="mer_site_product",
    )
    by_metric = {row["metric"]: row for row in ledger}
    assert by_metric["HSM_origin_input_balance_residual"]["annualised_value"] == 0.0
    assert by_metric["site_final_product_origin_residual"]["annualised_value"] == 0.0
    burden_rows = [row for row in ledger if row["boundary"] == "upstream_external_burden_excluded"]
    assert len(burden_rows) == 4
    assert all(row["annualised_value"] == 0.0 for row in burden_rows)


def test_c0_downstream_origin_ledger_closes_routes_inventory_and_final_product() -> None:
    rows = [
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "C0_BOF_crude_steel_output_t": 11.0,
            "C0_HSM_input_t_h": 8.0,
            "C0_DSP_liquid_steel_input_t": 2.0,
            "C0_HSM_final_product_t": 7.5,
            "C0_DSP_final_product_t": 1.5,
            "final_product_output_t": 9.0,
            "cold_slab_inventory_t": 6.0,
        },
        {
            "configuration_id": "C0_current_BF_BOF_reference",
            "C0_BOF_crude_steel_output_t": 11.0,
            "C0_HSM_input_t_h": 8.0,
            "C0_DSP_liquid_steel_input_t": 2.0,
            "C0_HSM_final_product_t": 7.5,
            "C0_DSP_final_product_t": 1.5,
            "final_product_output_t": 9.0,
            "cold_slab_inventory_t": 7.0,
        },
    ]
    ledger = {row["metric"]: row for row in _annual_c0_downstream_origin_ledger(rows)}
    assert ledger["BOF_route_origin_residual"]["annualised_value_t_y"] == 0.0
    assert ledger["site_final_product_origin_residual"]["annualised_value_t_y"] == 0.0


def test_origin_ledger_clamps_only_six_decimal_reporting_noise() -> None:
    rows = [
        {
            "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
            "C1_retained_HSM_input_t_h": 3.000001,
            "C1_cold_slab_draw_to_HSM_t_h": 1.0,
            "C1_EAF_to_HSM_slab_t_h": 1.0,
            "C1_imported_slab_to_HSM_t_h": 1.0,
            "C1_DSP_final_product_output_t": 1.0,
            "final_product_output_t": 3.727274,
        }
    ]
    ledger = _annual_origin_ledger(
        rows,
        {"hsm_final_t_per_t_slab": 10 / 11},
        case_id="mer_site_product",
    )
    by_metric = {row["metric"]: row for row in ledger}
    assert by_metric["HSM_origin_input_balance_residual"]["annualised_value"] == 0.0
    assert by_metric["site_final_product_origin_residual"]["annualised_value"] == 0.0


def test_user_authorized_emulation_overlays_preserve_carrier_and_named_process_scope() -> None:
    c1_energy = {
        "drp_ng_gj_per_t_dri": 9.9,
        "drp_electricity_mwh_per_t_dri": 1 / 12,
        "eaf_arc_electricity_mwh_per_t_liquid_steel": 19 / 45,
        "eaf_ng_gj_per_t_liquid_steel": 0.05,
        "natural_gas_lhv_mj_per_nm3": 35.8,
    }
    yields, bf_scales, resolved_energy = _user_authorized_emulation_overlays(
        {
            "wag_generation_yield_overrides_by_configuration": {
                "C0_current_BF_BOF_reference": {"COG": 562.5},
                "C1_phase1_BF_BOF_plus_DRP_EAF": {"COG": 562.5},
            },
            "named_process_electricity_intensity_scales_by_configuration": {
                "C0_current_BF_BOF_reference": {"BF": 1.25},
                "C1_phase1_BF_BOF_plus_DRP_EAF": {"EAF_arc": 1.25},
            },
        },
        c1_energy,
    )
    assert yields == {
        "C0_current_BF_BOF_reference": {"COG": 562.5},
        "C1_phase1_BF_BOF_plus_DRP_EAF": {"COG": 562.5},
    }
    assert bf_scales == {
        "C0_current_BF_BOF_reference": 1.25,
        "C1_phase1_BF_BOF_plus_DRP_EAF": 1.0,
    }
    assert resolved_energy is not c1_energy
    assert resolved_energy["eaf_arc_electricity_mwh_per_t_liquid_steel"] == pytest.approx(
        19 / 36
    )
    assert c1_energy["eaf_arc_electricity_mwh_per_t_liquid_steel"] == pytest.approx(
        19 / 45
    )


def test_user_authorized_emulation_overlays_reject_unfrozen_processes() -> None:
    with pytest.raises(ValueError, match="Unsupported named-process electricity"):
        _user_authorized_emulation_overlays(
            {
                "named_process_electricity_intensity_scales_by_configuration": {
                    "C0_current_BF_BOF_reference": {"HSM_rolling": 1.25}
                }
            },
            None,
        )
