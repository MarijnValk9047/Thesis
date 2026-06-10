from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent
REPO_ROOT = SCRIPT_PATH.parents[3]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from hydrogen.optimisation.input_resolver import (  # noqa: E402
    InputSliceRequest,
    load_mfrr_capacity_pilot_inputs,
    resolve_input_slice,
)
from hydrogen.optimisation_model import solve_stochastic_dispatch  # noqa: E402
from hydrogen.plant_parameters import (  # noqa: E402
    ProductionTargetEntry,
    ProductionTargetsSettings,
    load_hydrogen_config,
)
from hydrogen.production_target import PRODUCTION_TARGETS_TZ  # noqa: E402
from run_mfrr_capacity_one_day_exact_comparison_refresh_v1 import (  # noqa: E402
    ARTIFACT_ID,
    DELIVERY_DATE,
    OUTPUT_POLICY,
    TOLERANCE,
    _collect_mode,
    _validate_da_slice,
    _validate_mfrr_revenue_coefficients,
    _validate_mfrr_slice,
)

def _rolling_targets(*targets: ProductionTargetEntry, max_inventory_kg: float | None) -> ProductionTargetsSettings:
    return ProductionTargetsSettings(
        mode="rolling_deadline_envelope",
        initial_inventory_kg=0.0,
        max_inventory_kg=max_inventory_kg,
        terminal_inventory_value_mode="disabled",
        targets=tuple(targets),
    )


def _infer_binding_side(
    *,
    selected_mw: float,
    primary_bound_mw: float,
    secondary_bound_mw: float,
    primary_slack: float | None,
    secondary_slack: float | None,
    primary_label: str,
    secondary_label: str,
) -> str:
    if selected_mw <= TOLERANCE:
        return "none_selected"
    effective_continuous_bound = min(primary_bound_mw, secondary_bound_mw)
    if secondary_slack is not None and abs(secondary_slack) <= TOLERANCE and secondary_bound_mw <= primary_bound_mw + TOLERANCE:
        return secondary_label
    if primary_slack is not None and abs(primary_slack) <= TOLERANCE and primary_bound_mw <= secondary_bound_mw + TOLERANCE:
        return primary_label
    if 0.0 < (effective_continuous_bound - selected_mw) <= 1.0 + TOLERANCE:
        return "candidate_or_integer_bound"
    return "other_or_unclear"


def _enabled_reserve_feasibility_proxy(config: Any, *, activation_duration_hours: float) -> Any:
    return replace(
        config.reserve_feasibility_proxy,
        enabled=True,
        mode="conservative_output_absorption_and_recovery",
        down_activation_duration_hours=float(activation_duration_hours),
        up_activation_duration_hours=float(activation_duration_hours),
        down_output_absorption_source="rolling_production_credit_headroom",
        up_recovery_source="rolling_future_recoverable_production_headroom",
    )


def _run_case(
    *,
    case_name: str,
    config: Any,
    exact_solver_settings: Any,
    resolved_scenarios: Any,
    mfrr_input: Any,
    production_targets: ProductionTargetsSettings,
    duration_label: str,
    activation_duration_hours: float,
) -> dict[str, Any]:
    reserve_feasibility_proxy = _enabled_reserve_feasibility_proxy(
        config,
        activation_duration_hours=activation_duration_hours,
    )
    common_kwargs = dict(
        day_scenarios=resolved_scenarios,
        hydrogen=config.hydrogen_system,
        economics=config.economics,
        solver_settings=exact_solver_settings,
        delta_t_hours=config.delta_t_hours,
        inventory_start_kg=config.hydrogen_system.storage_initial_kg,
        reserve_kg=config.hydrogen_system.reserve_kg,
        daily_target_kg=config.economics.daily_target_kg,
        gamma=0.0,
        alpha=config.risk.alpha,
        production_target_mode="current_soft_target",
        production_targets=production_targets,
        reserve_feasibility_proxy=reserve_feasibility_proxy,
        apply_terminal_value=True,
        terminal_reference_start_kg=config.hydrogen_system.storage_initial_kg,
        terminal_value_per_kg=config.terminal_inventory_value_per_kg,
        solver_log_path=None,
        debug_options={"collect_objective_audit": True},
    )

    baseline_result = solve_stochastic_dispatch(mfrr_capacity_pilot=None, **common_kwargs)
    optional_result = solve_stochastic_dispatch(mfrr_capacity_pilot=mfrr_input, **common_kwargs)
    forced_zero_result = solve_stochastic_dispatch(
        mfrr_capacity_pilot=mfrr_input,
        **{**common_kwargs, "debug_options": {"collect_objective_audit": True, "force_mfrr_offer_zero": True}},
    )

    baseline = _collect_mode("no_mfrr_baseline", baseline_result)
    optional = _collect_mode("mfrr_optional", optional_result)
    forced_zero = _collect_mode("mfrr_forced_zero", forced_zero_result)

    optionality_dominance_passes = (optional["objective_value_eur"] or 0.0) <= (baseline["objective_value_eur"] or 0.0) + TOLERANCE
    forced_zero_matches_baseline = abs((forced_zero["objective_value_eur"] or 0.0) - (baseline["objective_value_eur"] or 0.0)) <= TOLERANCE
    integer_validation = optional["integer_offer_validation"]
    integer_mw_validation_passed = bool(
        integer_validation["integer_mw_passed"]
        and integer_validation["selected_minimum_mw_passed"]
        and integer_validation["no_zero_volume_selected_bids_passed"]
    )

    debug_info = optional.get("debug_info") or {}
    rolling_plan = debug_info.get("rolling_target_plan") or {}
    reserve_proxy_debug = rolling_plan.get("reserve_feasibility_proxy") or {}
    mfrr_summary = optional.get("mfrr_capacity_summary")
    terminal_guards = rolling_plan.get("terminal_guards", [])
    terminal_guard_active = any(bool(item.get("active")) for item in terminal_guards)
    terminal_inventory_disabled = bool(rolling_plan.get("effective_apply_terminal_value") is False)
    target_satisfied = abs(optional["shortfall_kg"] or 0.0) <= TOLERANCE and str(optional["solver_status"]).lower() == "optimal"
    horizon_end_local_date = str(
        pd.to_datetime(resolved_scenarios["delivery_start_utc"], utc=True, errors="raise")
        .dt.tz_convert(PRODUCTION_TARGETS_TZ)
        .dt.date.astype(str)
        .max()
    )
    due_by_horizon_end = float(
        sum(float(target.required_quantity_kg) for target in production_targets.targets if str(target.due_date) <= horizon_end_local_date)
    )
    cumulative_required_due_by_time_index_kg = [
        float(value) for value in rolling_plan.get("cumulative_required_due_by_time_index_kg", [])
    ]
    cumulative_h_comp = optional_result.dispatch["H_comp_kg"].astype(float).cumsum().tolist()
    headroom_series: list[float] = []
    if production_targets.max_inventory_kg is not None and cumulative_required_due_by_time_index_kg:
        for idx, cumulative_required in enumerate(cumulative_required_due_by_time_index_kg):
            headroom_series.append(
                float(
                    production_targets.max_inventory_kg
                    - (
                        float(production_targets.initial_inventory_kg)
                        + float(cumulative_h_comp[idx])
                        - float(cumulative_required)
                    )
                )
            )
    min_absorption_headroom_kg = float(min(headroom_series)) if headroom_series else 0.0
    up_recovery_headroom_by_time_index_kg = [
        float(value) for value in reserve_proxy_debug.get("up_recovery_headroom_by_time_index_kg", [])
    ]
    up_recovery_headroom_before_kg = (
        float(min(up_recovery_headroom_by_time_index_kg)) if up_recovery_headroom_by_time_index_kg else 0.0
    )
    down_absorption_headroom_before_kg = float(min_absorption_headroom_kg)
    down_output_kg_per_mwh = float(reserve_proxy_debug.get("down_output_kg_per_mwh", 0.0) or 0.0)
    up_output_kg_per_mwh = float(reserve_proxy_debug.get("up_output_kg_per_mwh", 0.0) or 0.0)
    down_activation_duration_hours = float(reserve_proxy_debug.get("down_activation_duration_hours", 0.0) or 0.0)
    up_activation_duration_hours = float(reserve_proxy_debug.get("up_activation_duration_hours", 0.0) or 0.0)

    selected_up_mw = float(optional["offered_capacity_up_mw"] or 0.0)
    selected_down_mw = float(optional["offered_capacity_down_mw"] or 0.0)
    up_lost_output_requirement_kg = float(selected_up_mw * up_activation_duration_hours * up_output_kg_per_mwh)
    down_output_requirement_kg = float(selected_down_mw * down_activation_duration_hours * down_output_kg_per_mwh)
    up_recovery_slack_kg = float(up_recovery_headroom_before_kg - up_lost_output_requirement_kg)
    down_absorption_slack_kg = float(down_absorption_headroom_before_kg - down_output_requirement_kg)

    if mfrr_summary is None or mfrr_summary.empty:
        min_scheduled_reducible_load_mw = 0.0
        min_electrical_headroom_mw = 0.0
    else:
        up_summary = mfrr_summary[mfrr_summary["direction"].astype(str) == "Up"].copy()
        down_summary = mfrr_summary[mfrr_summary["direction"].astype(str) == "Down"].copy()
        min_scheduled_reducible_load_mw = (
            float(up_summary["min_up_headroom_mw"].astype(float).min()) if not up_summary.empty else 0.0
        )
        min_electrical_headroom_mw = (
            float(down_summary["min_down_headroom_mw"].astype(float).min()) if not down_summary.empty else 0.0
        )

    up_recovery_bound_mw = (
        float(up_recovery_headroom_before_kg / (up_activation_duration_hours * up_output_kg_per_mwh))
        if up_activation_duration_hours > 0.0 and up_output_kg_per_mwh > 0.0
        else float("inf")
    )
    down_absorption_bound_mw = (
        float(down_absorption_headroom_before_kg / (down_activation_duration_hours * down_output_kg_per_mwh))
        if down_activation_duration_hours > 0.0 and down_output_kg_per_mwh > 0.0
        else float("inf")
    )
    up_binding_side = _infer_binding_side(
        selected_mw=selected_up_mw,
        primary_bound_mw=min_scheduled_reducible_load_mw,
        secondary_bound_mw=up_recovery_bound_mw,
        primary_slack=float(min_scheduled_reducible_load_mw - selected_up_mw),
        secondary_slack=up_recovery_slack_kg,
        primary_label="scheduled_load_bound",
        secondary_label="recovery_bound",
    )
    down_binding_side = _infer_binding_side(
        selected_mw=selected_down_mw,
        primary_bound_mw=min_electrical_headroom_mw,
        secondary_bound_mw=down_absorption_bound_mw,
        primary_slack=float(min_electrical_headroom_mw - selected_down_mw),
        secondary_slack=down_absorption_slack_kg,
        primary_label="electrical_headroom_bound",
        secondary_label="absorption_bound",
    )
    return {
        "case_name": case_name,
        "duration_label": duration_label,
        "baseline_solver_status": baseline["solver_status"],
        "baseline_termination_condition": baseline["termination_condition"],
        "baseline_objective_eur": baseline["objective_value_eur"],
        "forced_zero_solver_status": forced_zero["solver_status"],
        "forced_zero_termination_condition": forced_zero["termination_condition"],
        "forced_zero_objective_eur": forced_zero["objective_value_eur"],
        "optional_solver_status": optional["solver_status"],
        "optional_termination_condition": optional["termination_condition"],
        "optional_objective_eur": optional["objective_value_eur"],
        "forced_zero_matches_baseline": forced_zero_matches_baseline,
        "optionality_dominance_passes": optionality_dominance_passes,
        "selected_up_mw": selected_up_mw,
        "selected_down_mw": selected_down_mw,
        "expected_capacity_revenue_eur": optional["expected_capacity_revenue_total_eur"],
        "baseline_production_kg": baseline["production_kg"],
        "forced_zero_production_kg": forced_zero["production_kg"],
        "optional_production_kg": optional["production_kg"],
        "production_changed_under_optional_mfrr": abs((optional["production_kg"] or 0.0) - (baseline["production_kg"] or 0.0)) > TOLERANCE,
        "target_satisfied": target_satisfied,
        "terminal_guard_active": terminal_guard_active,
        "shortfall_kg": optional["shortfall_kg"],
        "integer_mw_validation_passed": integer_mw_validation_passed,
        "terminal_inventory_value_disabled": terminal_inventory_disabled,
        "reserve_feasibility_proxy_enabled": bool(
            reserve_proxy_debug.get("active_for_down_rolling_cap", False)
            or reserve_proxy_debug.get("active_for_up_rolling_recovery", False)
        ),
        "end_credit_inventory_kg": float(production_targets.initial_inventory_kg + (optional["production_kg"] or 0.0) - due_by_horizon_end),
        "max_inventory_kg": production_targets.max_inventory_kg,
        "minimum_remaining_absorption_headroom_kg": min_absorption_headroom_kg,
        "up_lost_output_requirement_kg": up_lost_output_requirement_kg,
        "up_recovery_headroom_before_kg": up_recovery_headroom_before_kg,
        "up_recovery_slack_kg": up_recovery_slack_kg,
        "up_binding_side": up_binding_side,
        "down_output_requirement_kg": down_output_requirement_kg,
        "down_absorption_headroom_before_kg": down_absorption_headroom_before_kg,
        "down_absorption_slack_kg": down_absorption_slack_kg,
        "down_binding_side": down_binding_side,
        "minimum_up_recovery_headroom_kg": up_recovery_headroom_before_kg,
        "target_calendar": [
            {
                "delivery_id": target.delivery_id,
                "due_date": target.due_date,
                "required_quantity_kg": target.required_quantity_kg,
            }
            for target in production_targets.targets
        ],
    }


def main() -> int:
    config_path = REPO_ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "configs" / "base_hydrogen.yaml"
    config = load_hydrogen_config(config_path)
    exact_solver_settings = replace(config.solver, mip_gap=min(float(config.solver.mip_gap), 1e-6))

    request = InputSliceRequest(
        artifact_id=ARTIFACT_ID,
        start_local_date=DELIVERY_DATE,
        end_local_date=DELIVERY_DATE,
        period_mode="custom_dates",
        dataset_split="test",
    )
    resolved_slice = resolve_input_slice(config, request=request, output_policy_name=OUTPUT_POLICY, use_cache=True)
    da_validation = _validate_da_slice(resolved_slice.scenarios, expected_delivery_date=DELIVERY_DATE)
    if not da_validation["is_d_only_compatible"]:
        raise ValueError(f"DA input is not a clean 24-hour D-only block for {DELIVERY_DATE}: {da_validation}")

    mfrr_input = load_mfrr_capacity_pilot_inputs(
        config.mfrr_capacity_pilot.export_path,
        start_local_date=DELIVERY_DATE,
        end_local_date=DELIVERY_DATE,
        capacity_offer_big_m_mw=config.mfrr_capacity_pilot.capacity_offer_big_m_mw,
        offer_continuous_mw=config.mfrr_capacity_pilot.offer_continuous_mw,
    )
    mfrr_validation = _validate_mfrr_slice(mfrr_input)
    if mfrr_validation["pilot_rows"] != 6 or mfrr_validation["candidate_rows"] != 6 or mfrr_validation["acceptance_rows"] != 18:
        raise ValueError(f"Unexpected one-day mFRR dimensions: {mfrr_validation}")
    revenue_validation = _validate_mfrr_revenue_coefficients(mfrr_input)
    if revenue_validation["max_abs_diff"] > TOLERANCE:
        raise ValueError(f"mFRR revenue coefficient scaling check failed: {revenue_validation}")

    case_specs = [
        (
            "Case A due_today_10000",
            _rolling_targets(
                ProductionTargetEntry(
                    delivery_id="due_today_10000",
                    due_date="2025-07-11",
                    required_quantity_kg=10000.0,
                ),
                max_inventory_kg=0.0,
            ),
        ),
        (
            "Case B tight_tomorrow_40000",
            _rolling_targets(
                ProductionTargetEntry(
                    delivery_id="tight_tomorrow_40000",
                    due_date="2025-07-12",
                    required_quantity_kg=40000.0,
                ),
                max_inventory_kg=20000.0,
            ),
        ),
        (
            "Case C loose_tomorrow_20000",
            _rolling_targets(
                ProductionTargetEntry(
                    delivery_id="loose_tomorrow_20000",
                    due_date="2025-07-12",
                    required_quantity_kg=20000.0,
                ),
                max_inventory_kg=0.0,
            ),
        ),
        (
            "Case D loose_tomorrow_20000_credit_20000",
            _rolling_targets(
                ProductionTargetEntry(
                    delivery_id="loose_tomorrow_20000_credit_20000",
                    due_date="2025-07-12",
                    required_quantity_kg=20000.0,
                ),
                max_inventory_kg=20000.0,
            ),
        ),
    ]
    duration_specs = [
        ("one_isp_0_25h", 0.25),
        ("double_isp_0_50h", 0.50),
    ]
    cases = []
    for duration_label, activation_duration_hours in duration_specs:
        for case_name, production_targets in case_specs:
            cases.append(
                _run_case(
                    case_name=case_name,
                    config=config,
                    exact_solver_settings=exact_solver_settings,
                    resolved_scenarios=resolved_slice.scenarios,
                    mfrr_input=mfrr_input,
                    production_targets=production_targets,
                    duration_label=duration_label,
                    activation_duration_hours=activation_duration_hours,
                )
            )

    print(json.dumps({"delivery_day": DELIVERY_DATE, "cases": cases}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
