from __future__ import annotations

from pathlib import Path
import sys

import pytest
from pyomo.environ import ConcreteModel, Constraint, RangeSet, Var, value


STEEL_ROOT = Path(__file__).resolve().parents[1]
if str(STEEL_ROOT) not in sys.path:
    sys.path.insert(0, str(STEEL_ROOT))

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
    _rolling_production_progress_contract,
    campaign_terminal_timestamp_plan,
)
from steel.s4_4c5p_phase4_terminal_inventory_equivalence import (
    CONFIG_PATH,
    _case_overrides,
    build_terminal_inventory_band,
    check_phase4_config,
    frozen_case_matrix,
    load_phase4_config,
    synthetic_campaign_activation_schedule,
    terminal_inventory_capacity_contract,
    terminal_state_vector,
)
from steel.rolling_production_quota import build_rolling_production_quota_plan
from steel.s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44CModelBuilderError,
    _add_rolling_terminal_inventory_band,
)
from steel.validation_tolerance_policy import (
    policy_contract,
    require_new_file_policy_registration,
)


def test_frozen_phase4_matrix_and_policy_caps() -> None:
    config = load_phase4_config()
    check_phase4_config(config)
    rows = frozen_case_matrix(config)
    assert len(rows) == 6
    assert sum(row["expected_model_count"] for row in rows) == 84
    assert config["phase4"]["expected_target_selection_case_count"] == 2
    assert config["phase4"]["maximum_model_count"] == 84
    assert {row["dataset_split"] for row in rows} == {"validation"}
    assert config["phase4"]["terminal_state_tolerance_policy"] == policy_contract()
    assert config["phase4"]["terminal_band_fraction"] == 0.01
    assert config["phase4"]["zero_target_policy"] == "exact_zero"
    assert config["phase4"]["terminal_band_width_search_allowed"] is False
    assert config["phase4"]["terminal_inventory_horizon_policy"] == (
        "truncate_at_campaign_endpoint_and_replace_cyclic_inventory_equalities"
    )
    assert not config["phase4"]["held_out_periods_used"]


def test_targets_are_extracted_from_final_executed_hour_unrounded_values() -> None:
    hourly = []
    for configuration in (C0_CONFIGURATION, C1_CONFIGURATION):
        for executed_hour in (0, 167):
            hourly.append({
                "configuration_id": configuration,
                "executed_hour_index": str(executed_hour),
                "coke_inventory_t": "1.0", "coke_inventory_t_unrounded": "1.25",
                "sinter_inventory_t": "2.0", "sinter_inventory_t_unrounded": "2.25",
                "hot_iron_inventory_t": "3.0", "hot_iron_inventory_t_unrounded": "3.25",
                "cold_slab_inventory_t": "4.0", "cold_slab_inventory_t_unrounded": "4.25",
                "DRI_inventory_t": "5.0", "DRI_inventory_t_unrounded": "5.25",
            })
    targets = terminal_state_vector({"hourly": hourly})
    assert targets[C0_CONFIGURATION] == {
        "coke_inventory_t": 1.25,
        "sinter_inventory_t": 2.25,
        "hot_iron_inventory_t": 3.25,
        "cold_slab_inventory_t": 4.25,
    }
    assert targets[C1_CONFIGURATION]["dri_inventory_t"] == 5.25


def test_one_percent_bands_clip_capacity_and_keep_zero_targets_exact() -> None:
    capacities = terminal_inventory_capacity_contract()
    target = {
        configuration: {
            state_id: (0.0 if state_id == "dri_inventory_t" else capacity)
            for state_id, capacity in states.items()
        }
        for configuration, states in capacities.items()
    }
    band = build_terminal_inventory_band(
        target, fraction=0.01, capacities=capacities
    )
    assert band[C0_CONFIGURATION]["coke_inventory_t"]["lower_t"] == (
        0.99 * target[C0_CONFIGURATION]["coke_inventory_t"]
    )
    assert band[C0_CONFIGURATION]["coke_inventory_t"]["upper_t"] == (
        capacities[C0_CONFIGURATION]["coke_inventory_t"]
    )
    assert band[C1_CONFIGURATION]["dri_inventory_t"]["lower_t"] == 0.0
    assert band[C1_CONFIGURATION]["dri_inventory_t"]["upper_t"] == 0.0


def test_responsive_overrides_share_band_and_keep_oracle_separate() -> None:
    config = load_phase4_config()
    rows = frozen_case_matrix(config)
    band = {
        C0_CONFIGURATION: {
            "coke_inventory_t": {"target_t": 1.0, "lower_t": 0.99, "upper_t": 1.01}
        },
        C1_CONFIGURATION: {
            "dri_inventory_t": {"target_t": 0.0, "lower_t": 0.0, "upper_t": 0.0}
        },
    }
    governed = _case_overrides(config, rows[1], REPO_ROOT, 168, band)
    oracle = _case_overrides(config, rows[2], REPO_ROOT, 168, band)
    assert governed["terminal_inventory_band_by_configuration"] == band
    assert governed["terminal_executed_hours_target"] == 168
    assert governed["terminal_inventory_horizon_policy"] == (
        "truncate_at_campaign_endpoint_and_replace_cyclic_inventory_equalities"
    )
    assert governed["forecast_price_field"] == "y_pred"
    assert governed["perfect_foresight_oracle"] is False
    assert oracle["forecast_price_field"] == "y_true"
    assert oracle["perfect_foresight_oracle"] is True
    assert "c1_liquid_steel_route_band" not in governed


def test_builder_hook_replaces_cyclic_equality_at_effective_horizon_end() -> None:
    model = ConcreteModel()
    model.TIME = RangeSet(0, 4)
    model.coke_inventory = Var(model.TIME)
    model.coke_terminal = Constraint(expr=model.coke_inventory[4] == 2.0)
    _add_rolling_terminal_inventory_band(
        model,
        terminal_hour=5,
        bounds_t={
            "coke_inventory_t": {"target_t": 7.0, "lower_t": 6.0, "upper_t": 8.0}
        },
    )
    model.coke_inventory[4].set_value(7.0)
    lower = next(iter(model.rolling_terminal_inventory_lower_bounds.values()))
    upper = next(iter(model.rolling_terminal_inventory_upper_bounds.values()))
    assert value(lower.body) == 7.0
    assert value(lower.lower) == 6.0
    assert value(upper.body) == 7.0
    assert value(upper.upper) == 8.0
    assert model.rolling_terminal_inventory_target_hour == 4
    assert not model.coke_terminal.active
    assert model.rolling_terminal_inventory_replaced_cyclic_constraints == (
        "coke_terminal",
    )


def test_builder_hook_rejects_a_post_campaign_planning_tail() -> None:
    model = ConcreteModel()
    model.TIME = RangeSet(0, 4)
    model.coke_inventory = Var(model.TIME)
    with pytest.raises(S44CModelBuilderError, match="effective end"):
        _add_rolling_terminal_inventory_band(
            model,
            terminal_hour=3,
            bounds_t={
                "coke_inventory_t": {
                    "target_t": 7.0,
                    "lower_t": 6.0,
                    "upper_t": 8.0,
                }
            },
        )


def test_campaign_terminal_timestamp_plan_truncates_to_complete_days() -> None:
    nominal = {
        "planning_horizon_hours": 120,
        "execution_block_hours": 24,
        "cumulative_deadline_hours": [24, 48, 72, 96, 120],
        "local_delivery_dates": ["d0", "d1", "d2", "d3", "d4"],
        "local_delivery_day_hours": [24, 24, 24, 24, 24],
    }
    resolved = campaign_terminal_timestamp_plan(
        nominal, remaining_terminal_hours=72
    )
    assert resolved["planning_horizon_hours"] == 72
    assert resolved["cumulative_deadline_hours"] == [24, 48, 72]
    assert resolved["local_delivery_dates"] == ["d0", "d1", "d2"]
    assert resolved["campaign_terminal_endpoint_active"] is True
    assert resolved["campaign_terminal_horizon_truncated"] is True


def test_campaign_terminal_timestamp_plan_preserves_dst_day_boundaries() -> None:
    nominal = {
        "planning_horizon_hours": 121,
        "execution_block_hours": 25,
        "cumulative_deadline_hours": [25, 49, 73, 97, 121],
        "local_delivery_dates": ["d0", "d1", "d2", "d3", "d4"],
        "local_delivery_day_hours": [25, 24, 24, 24, 24],
    }
    resolved = campaign_terminal_timestamp_plan(
        nominal, remaining_terminal_hours=97
    )
    assert resolved["planning_horizon_hours"] == 97
    assert resolved["execution_block_hours"] == 25
    assert resolved["cumulative_deadline_hours"] == [25, 49, 73, 97]


def test_terminal_activation_scales_to_week_month_and_year_campaigns() -> None:
    for campaign_hours in (168, 30 * 24, 365 * 24):
        rows = synthetic_campaign_activation_schedule(
            campaign_hours=campaign_hours,
            planning_horizon_hours=120,
        )
        active = [row for row in rows if row["terminal_band_active"]]
        assert len(active) == 5
        assert [row["terminal_hour_in_plan"] for row in active] == [120, 96, 72, 48, 24]
        assert all(not row["terminal_band_active"] for row in rows[:-5])


def test_dst_sized_horizons_activate_at_the_correct_boundary() -> None:
    expected_first_hour = {119: 96, 120: 120, 121: 120}
    for horizon, expected in expected_first_hour.items():
        rows = synthetic_campaign_activation_schedule(
            campaign_hours=10 * 24,
            planning_horizon_hours=horizon,
        )
        active = [row for row in rows if row["terminal_band_active"]]
        assert active[0]["terminal_hour_in_plan"] == expected


def test_long_campaign_production_credit_and_debt_remain_carried() -> None:
    plan = build_rolling_production_quota_plan(
        planning_horizon_hours=120,
        execution_block_hours=24,
        quota_per_execution_block_t=100.0,
    )
    executed_before = 200 * 24
    central_before = 200 * 100.0
    contract = _rolling_production_progress_contract(
        plan=plan,
        replan_index=200,
        cumulative_before={
            C0_CONFIGURATION: central_before + 10.0,
            C1_CONFIGURATION: central_before - 20.0,
        },
        base_target_multiplier=1.0,
        enabled=True,
        envelope_fraction=0.005,
        terminal_exact=False,
        central_target_before_t=central_before,
        terminal_recoverability_enabled=False,
    )
    c0 = contract["state_by_configuration"][C0_CONFIGURATION]
    c1 = contract["state_by_configuration"][C1_CONFIGURATION]
    assert c0["carried_credit_before_t"] == 10.0
    assert c1["carried_debt_before_t"] == 20.0
    assert executed_before == 4800


def test_new_module_is_registered_with_shared_policy() -> None:
    module_path = STEEL_ROOT / "steel/s4_4c5p_phase4_terminal_inventory_equivalence.py"
    require_new_file_policy_registration(
        str(module_path.relative_to(STEEL_ROOT)).replace("\\", "/"),
        module_path.read_text(encoding="utf-8"),
    )
    assert CONFIG_PATH.is_file()
