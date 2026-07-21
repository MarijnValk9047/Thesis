from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pyomo.environ import (
    ConcreteModel,
    Constraint,
    NonNegativeReals,
    Objective,
    RangeSet,
    SolverFactory,
    Var,
    minimize,
    value,
)


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.rolling_production_quota import (
    build_timestamped_rolling_production_quota_plan,
)
from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    CONFIGURATIONS,
    _rolling_production_progress_contract,
)
from steel.s4_4c5p_bf_price_series_interface import (
    PriceSeriesInterfaceError,
    dplus4_timestamp_plan,
)
from steel.s4_4c5p_bl_deterministic_price_response_anchor_diagnostics import (
    _first_window_schedule_costs,
    _schedule_costs,
)
from steel.s4_4c_unified_physical_modelbuilder import (
    _add_rolling_production_progress_tracking,
    _solve_with_optional_lexicographic_cost,
)


def test_timestamped_quota_uses_actual_25_hour_execution_day() -> None:
    plan = build_timestamped_rolling_production_quota_plan(
        planning_horizon_hours=121,
        execution_block_hours=25,
        cumulative_deadline_hours=[25, 49, 73, 97, 121],
        quota_per_hour_t=6_750_000.0 / 8760.0,
    )
    assert plan.quota_per_execution_block_t == pytest.approx(
        25.0 * 6_750_000.0 / 8760.0
    )
    assert plan.total_quota_t == pytest.approx(121.0 * 6_750_000.0 / 8760.0)


def test_timestamped_quota_rejects_incomplete_local_days() -> None:
    with pytest.raises(ValueError, match="deadline hours"):
        build_timestamped_rolling_production_quota_plan(
            planning_horizon_hours=121,
            execution_block_hours=25,
            cumulative_deadline_hours=[25, 49, 73, 97, 120],
            quota_per_hour_t=1.0,
        )


def test_dplus4_timestamp_plan_preserves_local_day_lengths() -> None:
    rows = []
    for day, hours in enumerate([25, 24, 24, 24, 24]):
        rows.extend(
            {
                "target_delivery_local_date": f"2024-10-{27 + day:02d}",
            }
            for _ in range(hours)
        )
    timing = dplus4_timestamp_plan(rows)
    assert timing["planning_horizon_hours"] == 121
    assert timing["execution_block_hours"] == 25
    assert timing["cumulative_deadline_hours"] == [25, 49, 73, 97, 121]


def test_dplus4_timestamp_plan_rejects_non_dst_duration() -> None:
    rows = [
        {"target_delivery_local_date": f"d{day}"}
        for day, hours in enumerate([22, 24, 24, 24, 24])
        for _ in range(hours)
    ]
    with pytest.raises(PriceSeriesInterfaceError, match="duration"):
        dplus4_timestamp_plan(rows)


def test_global_progress_contract_carries_timestamp_credit_without_creation() -> None:
    rate = 6_750_000.0 / 8760.0
    plan = build_timestamped_rolling_production_quota_plan(
        planning_horizon_hours=121,
        execution_block_hours=25,
        cumulative_deadline_hours=[25, 49, 73, 97, 121],
        quota_per_hour_t=rate,
    )
    central_before = 48.0 * rate
    cumulative = {configuration: central_before + 10.0 for configuration in CONFIGURATIONS}
    contract = _rolling_production_progress_contract(
        plan=plan,
        replan_index=2,
        cumulative_before=cumulative,
        base_target_multiplier=plan.total_quota_t / 5905.2,
        enabled=True,
        central_target_before_t=central_before,
    )
    for configuration in CONFIGURATIONS:
        assert contract["progress_target_by_configuration_t"][configuration] == pytest.approx(
            25.0 * rate - 10.0
        )
        assert contract["state_by_configuration"][configuration][
            "next_cumulative_central_target_t"
        ] == pytest.approx(73.0 * rate)


def test_future_terminal_quota_is_enforced_inside_planning_horizon() -> None:
    model = ConcreteModel()
    model.TIME = RangeSet(0, 119)
    model.final_product_output = Var(model.TIME, domain=NonNegativeReals)
    for hour in model.TIME:
        model.final_product_output[hour].fix(1.0)
    _add_rolling_production_progress_tracking(
        model,
        execution_block_hours=24,
        next_execution_target_t=24.0,
        exact_deadline_hour=72,
        exact_deadline_target_t=72.0,
    )
    constraint = model.rolling_production_future_terminal_quota_equality
    assert value(constraint.body) == pytest.approx(72.0)
    assert constraint.lower == pytest.approx(72.0)
    assert constraint.upper == pytest.approx(72.0)


def test_physical_progress_precedes_represented_cost() -> None:
    solver = SolverFactory("appsi_highs")
    if not solver.available(exception_flag=False):
        pytest.skip("HiGHS is unavailable for the lexicographic unit test.")
    model = ConcreteModel()
    model.TIME = RangeSet(0, 0)
    model.final_product_output = Var(model.TIME, domain=NonNegativeReals)
    model.priced_flow = Var(model.TIME, domain=NonNegativeReals)
    model.balance = Constraint(
        expr=model.final_product_output[0] + model.priced_flow[0] == 10.0
    )
    model.static_price_naive_objective = Objective(
        expr=model.final_product_output[0], sense=minimize
    )
    _add_rolling_production_progress_tracking(
        model,
        execution_block_hours=1,
        next_execution_target_t=5.0,
    )
    _, metadata = _solve_with_optional_lexicographic_cost(
        model,
        solver=solver,
        configuration_id="C0_current_BF_BOF_reference",
        deterministic_cost_policy={
            "objective_tolerance_eur": 0.0,
            "flows": [
                {
                    "configuration": "C0",
                    "flow_id": "test_flow",
                    "model_component_attribute": "priced_flow",
                    "price_eur_by_hour": [1.0],
                }
            ],
        },
    )
    assert value(model.final_product_output[0]) == pytest.approx(5.0)
    assert metadata["production_progress_optimum_deviation_t"] == pytest.approx(0.0)
    assert metadata["primary_cost_objective_eur"] == pytest.approx(5.0)


def _tiny_artifact() -> dict[str, object]:
    hourly = []
    costs = []
    for configuration in CONFIGURATIONS:
        hourly.extend(
            [
                {
                    "configuration_id": configuration,
                    "executed_hour_index": 0,
                    "net_grid_import_mwh": 2.0,
                },
                {
                    "configuration_id": configuration,
                    "executed_hour_index": 1,
                    "net_grid_import_mwh": 1.0,
                },
            ]
        )
        costs.extend(
            [
                {
                    "configuration_id": configuration,
                    "price_id": "grid_electricity_flat_nl",
                    "cost_eur": 240.0,
                },
                {
                    "configuration_id": configuration,
                    "price_id": "purchased_scrap_proxy",
                    "cost_eur": 50.0,
                },
            ]
        )
    return {"hourly": hourly, "costs": costs}


def test_price_insensitive_schedule_is_revalued_on_same_y_pred() -> None:
    vector = [
        {"y_pred_eur_per_mwh": 10.0},
        {"y_pred_eur_per_mwh": 100.0},
    ]
    result = _schedule_costs(
        _tiny_artifact(), vector, price_field="y_pred_eur_per_mwh"
    )
    for configuration in CONFIGURATIONS:
        assert result[configuration]["grid_cost_eur"] == pytest.approx(120.0)
        assert result[configuration]["total_represented_cost_eur"] == pytest.approx(170.0)


def test_native_flat_grid_cost_is_not_reused_in_forecast_comparison() -> None:
    vector = [
        {"y_pred_eur_per_mwh": 80.0},
        {"y_pred_eur_per_mwh": 80.0},
    ]
    result = _schedule_costs(
        _tiny_artifact(), vector, price_field="y_pred_eur_per_mwh"
    )
    for configuration in CONFIGURATIONS:
        assert result[configuration]["grid_cost_eur"] == pytest.approx(240.0)


def test_first_window_comparator_revalues_complete_identical_state_plan() -> None:
    ledger = []
    for configuration in CONFIGURATIONS:
        ledger.extend(
            [
                {
                    "configuration_id": configuration,
                    "plan_hour_index": hour,
                    "price_id": "grid_electricity_flat_nl",
                    "quantity": quantity,
                    "cost_eur": 80.0 * quantity,
                }
                for hour, quantity in enumerate((2.0, 1.0))
            ]
        )
        ledger.append(
            {
                "configuration_id": configuration,
                "plan_hour_index": 0,
                "price_id": "purchased_scrap_proxy",
                "quantity": 1.0,
                "cost_eur": 50.0,
            }
        )
    result = _first_window_schedule_costs(
        {"first_window_costs": ledger},
        [
            {"y_pred_eur_per_mwh": 10.0},
            {"y_pred_eur_per_mwh": 100.0},
        ],
        price_field="y_pred_eur_per_mwh",
    )
    for configuration in CONFIGURATIONS:
        assert result[configuration]["total_represented_cost_eur"] == pytest.approx(170.0)
