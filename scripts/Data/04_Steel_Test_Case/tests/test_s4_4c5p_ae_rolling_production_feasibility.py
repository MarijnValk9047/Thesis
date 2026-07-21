from __future__ import annotations

from copy import deepcopy
import inspect
from pathlib import Path
import sys

import pytest
from pyomo.environ import ConcreteModel, Expression, RangeSet, value


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.rolling_production_quota import build_rolling_production_quota_plan
from steel.s4_4b5a_asymmetric_correction import (
    _load_tables as _load_b5a_source_tables,
    _patch_gate1_sinter_material_basis,
)
from steel.s4_4c5p_ae_rolling_production_feasibility import (
    REQUIRED_C0_CONTINUOUS_ACTIVITIES,
    RollingFeasibilityError,
    _availability_controls,
    _c0_continuous_operation_diagnosis,
    _c1_capacity_diagnosis,
    _continuous_operation_activities,
    _load_config,
    _source_coke_chain,
    _validation_rows,
)
from steel.s4_4c_component_ontology import load_builder_component_ontology
from steel.s4_4c_unified_physical_modelbuilder import (
    S44B_INPUT_DIR,
    S44CModelBuilderError,
    _add_final_product_requirement,
    _add_rolling_production_deadline_envelope,
    _build_c0_inputs,
    _build_c0_model,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
    _solve_c0_configuration,
    run_s44c_unified_physical_regression,
)
from steel.wag_development_controller_contract import hsm_reheat_mwh_per_t_hrc


SOURCE_COKE_CHAIN = {
    "dry_coal_t_per_t_coke": 1.285,
    "bf_coke_t_per_t_hot_metal": 0.359,
}


def test_public_builder_accepts_c0_coke_chain_reconciliation() -> None:
    assert "c0_coke_chain_reconciliation" in inspect.signature(
        run_s44c_unified_physical_regression
    ).parameters


def test_quota_plan_has_cumulative_daily_deadlines() -> None:
    plan = build_rolling_production_quota_plan(
        planning_horizon_hours=168,
        execution_block_hours=24,
        quota_per_execution_block_t=5905.2,
    )
    assert tuple(plan.cumulative_deadline_targets_t) == (24, 48, 72, 96, 120, 144, 168)
    assert plan.cumulative_deadline_targets_t[24] == pytest.approx(5905.2)
    assert plan.total_quota_t == pytest.approx(41336.4)


def test_quota_plan_rejects_non_divisible_horizon() -> None:
    with pytest.raises(ValueError, match="exact multiple"):
        build_rolling_production_quota_plan(
            planning_horizon_hours=25,
            execution_block_hours=24,
            quota_per_execution_block_t=1.0,
        )


def test_deadline_envelope_requires_final_target_match() -> None:
    model = ConcreteModel()
    model.TIME = RangeSet(0, 23)
    model.final_product_output = Expression(model.TIME, rule=lambda _m, _t: 1.0)
    with pytest.raises(S44CModelBuilderError, match="equal the model final-product target"):
        _add_rolling_production_deadline_envelope(
            model,
            horizon_hours=24,
            final_product_target_t=24.0,
            deadline_targets_t={24: 23.0},
        )


def test_deadline_envelope_adds_hard_constraint() -> None:
    model = ConcreteModel()
    model.TIME = RangeSet(0, 23)
    model.final_product_output = Expression(model.TIME, rule=lambda _m, _t: 1.0)
    _add_rolling_production_deadline_envelope(
        model,
        horizon_hours=24,
        final_product_target_t=24.0,
        deadline_targets_t={24: 24.0},
    )
    assert len(model.rolling_production_deadline) == 1


def test_rolling_final_product_requirement_is_a_lower_bound_not_an_exact_profile() -> None:
    quota_model = ConcreteModel()
    quota_model.TIME = RangeSet(0, 23)
    quota_model.final_product_output = Expression(quota_model.TIME, rule=lambda _m, _t: 1.0)
    _add_final_product_requirement(
        quota_model,
        final_product_target_t=24.0,
        quota_lower_bound=True,
    )
    assert value(quota_model.final_product_fulfilment.lower) == pytest.approx(24.0)
    assert quota_model.final_product_fulfilment.upper is None

    exact_model = ConcreteModel()
    exact_model.TIME = RangeSet(0, 23)
    exact_model.final_product_output = Expression(exact_model.TIME, rule=lambda _m, _t: 1.0)
    _add_final_product_requirement(
        exact_model,
        final_product_target_t=24.0,
        quota_lower_bound=False,
    )
    assert value(exact_model.final_product_fulfilment.lower) == pytest.approx(24.0)
    assert value(exact_model.final_product_fulfilment.upper) == pytest.approx(24.0)


def test_runner_config_rejects_market_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda _self, **_kwargs: """run_id: invalid\nplanning_horizon_hours: 24\nexecution_block_hours: 24\nquota_per_execution_block_t: 1\nmarket_prices_enabled: true\nenergy_cost_objective_enabled: false\nproduct_revenue_enabled: false\nco2_ets_objective_enabled: false\n""",
    )
    with pytest.raises(RollingFeasibilityError, match="forbids market prices"):
        _load_config(Path("invalid.yaml"))


def test_runner_config_requires_source_coke_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda _self, **_kwargs: """run_id: invalid\nplanning_horizon_hours: 24\nexecution_block_hours: 24\nquota_per_execution_block_t: 1\nmarket_prices_enabled: false\nenergy_cost_objective_enabled: false\nproduct_revenue_enabled: false\nco2_ets_objective_enabled: false\n""",
    )
    with pytest.raises(RollingFeasibilityError, match="source_coke_chain"):
        _load_config(Path("invalid.yaml"))


def test_quota_driven_availability_does_not_fix_schedules_or_route_share() -> None:
    controls = _availability_controls(
        {"availability_policy": {"c0": "quota_driven_binary_capacity", "c1": "quota_driven_topology"}}
    )
    assert controls["fix_c0_binary_schedule"] is False
    assert controls["fix_c1_hybrid_schedule"] is False
    assert controls["c1_retained_route_policy"] == "quota_driven_topology"
    assert controls["commitment_granularity"] == "daily_binary_hourly_throughput"


def test_c0_continuous_operation_classes_resolve_from_component_ontology() -> None:
    activities = _continuous_operation_activities()
    assert set(activities["c0"]) == REQUIRED_C0_CONTINUOUS_ACTIVITIES

    c0_rows = {
        row["builder_activity_name"]: row
        for row in load_builder_component_ontology()
        if row["configuration_id"] == "C0_current_BF_BOF_reference"
    }
    assert all(c0_rows[name]["enforcement"] == "fix_on_over_horizon" for name in activities["c0"])
    assert c0_rows["basic_oxygen_furnace"]["operation_class"] == "batch_equivalent"
    assert c0_rows["basic_oxygen_furnace"]["enforcement"] == "no_extra_commitment"
    assert c0_rows["hot_strip_mill"]["operation_class"] == "bounded_downstream"
    assert c0_rows["hot_strip_mill"]["enforcement"] == "no_extra_commitment"


def test_c0_continuous_enforcement_fixes_on_only_and_leaves_throughput_bounded() -> None:
    inputs = _build_c0_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=24,
        target_multiplier=1.0,
    )
    activities = _continuous_operation_activities()["c0"]
    model = _build_c0_model(
        inputs,
        commitment_granularity="daily_binary_hourly_throughput",
        continuous_must_run_activities=activities,
    )

    for activity_name in activities:
        activity = getattr(model, activity_name)
        on_var = getattr(model, f"{activity_name}_on")
        assert all(on_var[t].fixed and value(on_var[t]) == pytest.approx(1.0) for t in model.TIME)
        assert all(not activity[t].fixed for t in model.TIME)

    assert all(not model.basic_oxygen_furnace_on[t].fixed for t in model.TIME)
    assert all(not model.basic_oxygen_furnace[t].fixed for t in model.TIME)
    assert all(not model.hot_strip_mill_on[t].fixed for t in model.TIME)
    assert all(not model.hot_strip_mill[t].fixed for t in model.TIME)


def test_c0_continuous_enforcement_rejects_unknown_activity() -> None:
    inputs = _build_c0_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=24,
        target_multiplier=1.0,
    )
    with pytest.raises(S44CModelBuilderError, match="Unknown or non-continuous activity"):
        _build_c0_model(
            inputs,
            continuous_must_run_activities=("basic_oxygen_furnace", "not_a_process"),
        )


def test_sinter_iron_ore_feed_is_converted_to_sinter_output_and_energy_denominators() -> None:
    inputs = _build_c0_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=1,
        target_multiplier=1.0,
    )
    assert inputs.sinter_output_per_t_iron_ore == pytest.approx(1.230)
    model = _build_c0_model(
        inputs,
        enable_minimal_wag_layer=True,
        development_controller_activation="full",
    )
    model.sintering_plant[0].set_value(100.0)
    assert value(model.sinter_output[0]) == pytest.approx(123.0)
    assert value(model.cog_to_sinter[0]) == pytest.approx((0.067 / 3.6) * 123.0)

    c1_inputs = _build_c1_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=1,
        include_retained_bf_bof=True,
    )
    c1_model = _build_c1_model(
        c1_inputs,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        development_controller_activation="full_electricity_boundary",
    )
    c1_model.sintering_plant[0].set_value(100.0)
    assert value(c1_model.sinter_output[0]) == pytest.approx(123.0)
    assert value(c1_model.sinter_electricity_mwh[0]) == pytest.approx(0.0343 * 123.0)


def test_b5a_regeneration_preserves_gate1_sinter_material_basis() -> None:
    tables, _ = _load_b5a_source_tables()
    replacement = _patch_gate1_sinter_material_basis(tables)
    row = next(
        candidate
        for candidate in tables["process_io_coefficients.csv"]
        if candidate.get("process_id") == "sintering_plant"
        and candidate.get("input_material") == "iron_ore"
        and candidate.get("output_material") == "sinter"
    )
    assert row["coefficient"] == "1.230"
    assert row["coefficient_unit"] == "t_sinter/t_iron_ore"
    assert row["assumption_id"] == "C5_GATE1_SINTER_BUS0_CONVERSION"
    assert replacement["patch_applied"] == "true"


def test_c0_rolling_inventory_override_is_applied_before_model_build() -> None:
    source = inspect.getsource(_solve_c0_configuration)
    assert source.index("_apply_c0_initial_inventory_overrides") < source.index("model = _build_c0_model")


def test_reference_c0_hsm_energy_uses_hrc_output_not_slab_input() -> None:
    inputs = _build_c0_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=1,
        target_multiplier=1.0,
    )
    routing = {
        "hsm_final_t_per_t_slab": 1 / 1.06,
            "dsp_liquid_steel_input_t_per_t_coil": 1.05,
            "dsp_final_product_horizon_cap_t": 1_000_000.0,
            "dsp_final_product_max_t_h": 1_000_000.0,
            "bof_hot_metal_t_per_t_liquid_steel": 0.875,
            "bof_scrap_t_per_t_liquid_steel": 0.208,
            "bof_total_scrap_horizon_cap_t": 1_000_000.0,
            "bof_total_scrap_max_t_h": 1_000_000.0,
        "reference_validation_bands": {
            "bof_liquid_steel": {"lower_t": 0.0, "upper_t": 1_000_000.0},
            "hsm_final_output": {"lower_t": 0.0, "upper_t": 1_000_000.0},
            "dsp_final_output": {"lower_t": 0.0, "upper_t": 1_000_000.0},
        },
    }
    model = _build_c0_model(
        inputs,
        enable_minimal_wag_layer=True,
        development_controller_activation="hsm",
        c0_downstream_reference_routing=routing,
    )
    model.hot_strip_mill[0].set_value(106.0)
    model.c0_dsp_liquid_steel_input[0].set_value(0.0)
    assert value(model.c0_hsm_final_product_output[0]) == pytest.approx(100.0)
    assert value(model.hsm_reheat_demand_mwh[0]) == pytest.approx(
        hsm_reheat_mwh_per_t_hrc() * 100.0
    )


@pytest.mark.parametrize(
    ("table_name", "selector", "field", "bad_value", "error_match"),
    [
        (
            "process_units.csv",
            {"configuration_id": "C0_current_BF_BOF_reference", "asset_id": "sintering_plant"},
            "rate_unit",
            "t_sinter/h",
            "must use t_iron_ore/h",
        ),
        (
            "process_io_coefficients.csv",
            {"process_id": "sintering_plant", "input_material": "iron_ore", "output_material": "sinter"},
            "coefficient_unit",
            "t_iron_ore/t_sinter",
            "must use t_sinter/t_iron_ore",
        ),
    ],
)
def test_sinter_basis_validation_fails_closed_on_wrong_units(
    table_name: str,
    selector: dict[str, str],
    field: str,
    bad_value: str,
    error_match: str,
) -> None:
    tables = deepcopy(_load_tables(S44B_INPUT_DIR))
    row = next(
        candidate
        for candidate in tables.tables[table_name]
        if all(candidate.get(key) == expected for key, expected in selector.items())
    )
    row[field] = bad_value
    with pytest.raises(S44CModelBuilderError, match=error_match):
        _build_c0_inputs(tables, horizon_hours_override=24)


@pytest.mark.parametrize(
    ("target_multiplier", "expected_status", "expected_conflicts"),
    [
        (7.0, "no_rate_envelope_conflict_found", set()),
        (129452.0547945205 / 5905.2, "no_rate_envelope_conflict_found", set()),
        (135000.0 / 5905.2, "focused_structural_infeasibility_proof", {"continuous_c0_horizon_quota_exceeds_capacity"}),
    ],
)
def test_c0_continuous_diagnosis_identifies_target_specific_binding_envelopes(
    target_multiplier: float,
    expected_status: str,
    expected_conflicts: set[str],
) -> None:
    diagnosis = _c0_continuous_operation_diagnosis(
        report={
            "configuration_build_audit": [
                {
                    "configuration_id": "C0_current_BF_BOF_reference",
                    "build_status": "solver_failed",
                    "solver_status": "exception_no_solution_loaded",
                    "termination_condition": "infeasible_or_no_accepted_solution",
                }
            ]
        },
        planning_horizon_hours=168,
        target_multiplier=target_multiplier,
        continuous_activities=_continuous_operation_activities()["c0"],
        source_coke_chain=SOURCE_COKE_CHAIN,
    )
    assert diagnosis is not None
    assert diagnosis["diagnosis_status"] == expected_status
    conflict_ids = {row["conflict_id"] for row in diagnosis["conflicts"]}
    assert conflict_ids == expected_conflicts
    assert len(diagnosis["governed_continuous_rate_bounds"]) == 5
    activity_upper = diagnosis["sinter_material_basis"]["activity_envelope_t"][1]
    output_upper = diagnosis["sinter_material_basis"]["converted_output_envelope_t"][1]
    assert output_upper == pytest.approx(
        activity_upper * diagnosis["model_coefficients"]["sinter_output_per_t_iron_ore"]
    )
    if expected_conflicts:
        assert diagnosis["conflicts"][0]["binding_upper_envelope"] == "KGF1_KGF2_source_coke_chain_capacity"


def test_c1_capacity_diagnosis_reproduces_active_model_conversion_and_binding_routes() -> None:
    diagnosis = _c1_capacity_diagnosis(
        report={
            "configuration_build_audit": [
                {
                    "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
                    "build_status": "solver_failed",
                    "solver_status": "exception_no_solution_loaded",
                    "termination_condition": "infeasible_or_no_accepted_solution",
                }
            ]
        },
        planning_horizon_hours=168,
        target_multiplier=129452.0547945205 / 5905.2,
        source_coke_chain=SOURCE_COKE_CHAIN,
    )
    assert diagnosis is not None
    assert diagnosis["diagnosis_status"] == "focused_structural_infeasibility_proof"
    assert diagnosis["model_coefficients"]["sinter_output_per_t_iron_ore"] == pytest.approx(1.230)
    conflict = diagnosis["conflicts"][0]
    assert conflict["retained_route_binding_upper_envelope"] == "retained_BF6_capacity"
    assert conflict["eaf_route_binding_upper_envelope"] == "C1_DRP_capacity"


def test_quota_validation_fails_when_one_configuration_has_no_solution_rows() -> None:
    continuous = _continuous_operation_activities()
    availability = _availability_controls(
        {"availability_policy": {"c0": "quota_driven_binary_capacity", "c1": "quota_driven_topology"}}
    )
    checks = _validation_rows(
        {
            "configuration_build_audit": [
                {
                    "configuration_id": "C0_current_BF_BOF_reference",
                    "build_status": "solver_failed",
                    "continuous_must_run_activities": ";".join(sorted(continuous["c0"])),
                    "continuous_must_run_throughput_fixed": "false",
                },
                {"configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF", "build_status": "solved"},
            ],
            "forbidden_terms_active": {"product_revenue": False},
            "fix_c0_binary_schedule": False,
            "fix_c1_hybrid_schedule": False,
            "c1_retained_route_policy": "quota_driven_topology",
            "commitment_granularity": "daily_binary_hourly_throughput",
            "c0_continuous_must_run_activities": sorted(continuous["c0"]),
            "final_product_requirement_sense": "cumulative_quota_lower_bound",
            "c0_coke_chain_reconciliation": SOURCE_COKE_CHAIN,
            "c1_coke_chain_reconciliation": SOURCE_COKE_CHAIN,
            "enable_minimal_wag_layer": True,
        },
        [
            {
                "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
                "status": "pass",
            }
        ],
        availability,
        continuous,
        {"diagnosis_status": "focused_structural_infeasibility_proof", "conflicts": [{"conflict_id": "x"}]},
        None,
        SOURCE_COKE_CHAIN,
    )
    assert next(row for row in checks if row["check_id"] == "hard_cumulative_quota_deadlines")["status"] == "fail"


def test_reconciled_coking_chain_uses_coke_output_for_kgf_underfiring() -> None:
    inputs = _build_c1_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=1,
        include_retained_bf_bof=True,
    )
    model = _build_c1_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        c1_coke_chain_reconciliation=SOURCE_COKE_CHAIN,
    )
    model.coking_plant_1[0].set_value(128.5)
    assert value(model.coke_output[0]) == pytest.approx(100.0)
    assert value(model.cog_to_kgf1[0]) == pytest.approx(inputs.retained_bf_bof.kgf_underfiring_mwh_per_t_coke * 100.0)
