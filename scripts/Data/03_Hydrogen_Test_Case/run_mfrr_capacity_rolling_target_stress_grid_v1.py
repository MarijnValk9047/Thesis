from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

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
from hydrogen.plant_parameters import (  # noqa: E402
    ProductionTargetEntry,
    load_hydrogen_config,
)
from hydrogen.production_target import conservative_future_max_deliverable_kg  # noqa: E402
from run_mfrr_capacity_one_day_exact_comparison_refresh_v1 import (  # noqa: E402
    ARTIFACT_ID,
    DELIVERY_DATE,
    OUTPUT_POLICY,
    TOLERANCE,
    _validate_da_slice,
    _validate_mfrr_revenue_coefficients,
    _validate_mfrr_slice,
)
from run_mfrr_capacity_rolling_target_overlay_smoke_v1 import (  # noqa: E402
    _rolling_targets,
    _run_case,
)


def _resolve_very_tight_required_quantity_kg(*, config: object) -> tuple[float, float | None]:
    requested_required_quantity_kg = 45000.0
    max_credit_kg = 20000.0
    future_local_day = date.fromisoformat(DELIVERY_DATE) + timedelta(days=1)
    future_max_deliverable_kg = conservative_future_max_deliverable_kg(
        hydrogen=config.hydrogen_system,
        start_local_day=future_local_day,
        end_local_day=future_local_day,
        delta_t_hours=config.delta_t_hours,
    )
    max_feasible_required_quantity_kg = float(max_credit_kg + future_max_deliverable_kg)
    if requested_required_quantity_kg <= max_feasible_required_quantity_kg + TOLERANCE:
        return requested_required_quantity_kg, None
    return max_feasible_required_quantity_kg, requested_required_quantity_kg


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

    very_tight_required_quantity_kg, adjusted_from_kg = _resolve_very_tight_required_quantity_kg(config=config)

    target_specs = [
        ("loose_tomorrow_20000", 20000.0),
        ("tight_tomorrow_40000", 40000.0),
        ("very_tight_tomorrow_45000" if adjusted_from_kg is None else "very_tight_tomorrow_adjusted", very_tight_required_quantity_kg),
    ]
    credit_specs = [
        ("credit_0", 0.0),
        ("credit_5000", 5000.0),
        ("credit_20000", 20000.0),
    ]
    duration_specs = [
        ("one_isp_0_25h", 0.25),
        ("double_isp_0_50h", 0.50),
        ("four_isp_1_00h", 1.00),
    ]

    rows: list[dict[str, object]] = []
    for target_case, required_quantity_kg in target_specs:
        for credit_cap_label, max_inventory_kg in credit_specs:
            production_targets = _rolling_targets(
                ProductionTargetEntry(
                    delivery_id=f"{target_case}_{credit_cap_label}",
                    due_date="2025-07-12",
                    required_quantity_kg=float(required_quantity_kg),
                ),
                max_inventory_kg=max_inventory_kg,
            )
            for duration_label, activation_duration_hours in duration_specs:
                case_result = _run_case(
                    case_name=f"{target_case}__{credit_cap_label}",
                    config=config,
                    exact_solver_settings=exact_solver_settings,
                    resolved_scenarios=resolved_slice.scenarios,
                    mfrr_input=mfrr_input,
                    production_targets=production_targets,
                    duration_label=duration_label,
                    activation_duration_hours=activation_duration_hours,
                )
                rows.append(
                    {
                        "target_case": target_case,
                        "credit_cap_label": credit_cap_label,
                        "credit_cap_kg": max_inventory_kg,
                        "duration_label": duration_label,
                        "status": case_result["optional_solver_status"],
                        "optional_objective_eur": case_result["optional_objective_eur"],
                        "selected_up_mw": case_result["selected_up_mw"],
                        "selected_down_mw": case_result["selected_down_mw"],
                        "expected_capacity_revenue_eur": case_result["expected_capacity_revenue_eur"],
                        "optional_production_kg": case_result["optional_production_kg"],
                        "end_credit_inventory_kg": case_result["end_credit_inventory_kg"],
                        "up_lost_output_requirement_kg": case_result["up_lost_output_requirement_kg"],
                        "up_recovery_slack_kg": case_result["up_recovery_slack_kg"],
                        "up_binding_side": case_result["up_binding_side"],
                        "down_output_requirement_kg": case_result["down_output_requirement_kg"],
                        "down_absorption_slack_kg": case_result["down_absorption_slack_kg"],
                        "down_binding_side": case_result["down_binding_side"],
                        "target_satisfied": case_result["target_satisfied"],
                        "terminal_guard_active": case_result["terminal_guard_active"],
                        "integer_mw_validation_passed": case_result["integer_mw_validation_passed"],
                        "optionality_dominance_passes": case_result["optionality_dominance_passes"],
                        "forced_zero_matches_baseline": case_result["forced_zero_matches_baseline"],
                    }
                )

    solved_rows = [row for row in rows if str(row["status"]).lower() == "optimal"]
    infeasible_rows = [row for row in rows if str(row["status"]).lower() != "optimal"]
    positive_up_rows = [row for row in solved_rows if float(row["selected_up_mw"]) > TOLERANCE]
    positive_down_rows = [row for row in solved_rows if float(row["selected_down_mw"]) > TOLERANCE]
    no_reserve_rows = [
        row for row in solved_rows if float(row["selected_up_mw"]) <= TOLERANCE and float(row["selected_down_mw"]) <= TOLERANCE
    ]
    up_binding_counts = Counter(str(row["up_binding_side"]) for row in solved_rows)
    down_binding_counts = Counter(str(row["down_binding_side"]) for row in solved_rows)
    near_zero_slack_cases = [
        f"{row['target_case']}|{row['credit_cap_label']}|{row['duration_label']}"
        for row in solved_rows
        if (
            float(row["selected_up_mw"]) > TOLERANCE
            and str(row["up_binding_side"]) == "recovery_bound"
            and abs(float(row["up_recovery_slack_kg"])) <= 1e-6
        )
        or (
            float(row["selected_down_mw"]) > TOLERANCE
            and str(row["down_binding_side"]) == "absorption_bound"
            and abs(float(row["down_absorption_slack_kg"])) <= 1e-6
        )
    ]

    positive_reserve_by_key: dict[tuple[str, str, str], bool] = {}
    for row in solved_rows:
        key = (str(row["target_case"]), str(row["credit_cap_label"]), str(row["duration_label"]))
        positive_reserve_by_key[key] = bool(
            float(row["selected_up_mw"]) > TOLERANCE or float(row["selected_down_mw"]) > TOLERANCE
        )
    disappeared_under_one_hour = []
    for target_case, _required in target_specs:
        for credit_cap_label, _credit in credit_specs:
            key_025 = (target_case, credit_cap_label, "one_isp_0_25h")
            key_100 = (target_case, credit_cap_label, "four_isp_1_00h")
            if positive_reserve_by_key.get(key_025, False) and not positive_reserve_by_key.get(key_100, False):
                disappeared_under_one_hour.append(f"{target_case}|{credit_cap_label}")

    payload = {
        "delivery_day": DELIVERY_DATE,
        "very_tight_requested_required_quantity_kg": 45000.0,
        "very_tight_effective_required_quantity_kg": very_tight_required_quantity_kg,
        "very_tight_adjusted_from_kg": adjusted_from_kg,
        "aggregate_summary": {
            "solved_cases": len(solved_rows),
            "infeasible_cases": len(infeasible_rows),
            "positive_up_cases": len(positive_up_rows),
            "positive_down_cases": len(positive_down_rows),
            "no_reserve_cases": len(no_reserve_rows),
            "up_binding_side_counts": dict(sorted(up_binding_counts.items())),
            "down_binding_side_counts": dict(sorted(down_binding_counts.items())),
            "near_zero_process_feasibility_slack_cases": near_zero_slack_cases,
            "reserve_disappears_under_1_00h_cases": disappeared_under_one_hour,
        },
        "cases": rows,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
