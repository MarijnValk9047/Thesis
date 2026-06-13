from __future__ import annotations

import json
import platform
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

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
from hydrogen.plant_parameters import load_hydrogen_config  # noqa: E402
from run_mfrr_capacity_one_day_exact_comparison_refresh_v1 import (  # noqa: E402
    ARTIFACT_ID,
    LINEAGE_ROLE,
    OUTPUT_POLICY,
    RUN_CLASS,
    TOLERANCE,
    _collect_mode,
    _fingerprint_file,
    _iso,
    _now_utc,
    _relativize_paths,
    _repo_rel,
    _validate_da_slice,
    _validate_integer_offer_summary,
    _validate_mfrr_revenue_coefficients,
    _validate_mfrr_slice,
    _write_json,
    _write_yaml,
)


START_DATE = "2025-07-07"
END_DATE = "2025-07-13"


def _solve_day(config, exact_solver_settings, *, delivery_date: str) -> dict[str, object]:
    request = InputSliceRequest(
        artifact_id=ARTIFACT_ID,
        start_local_date=delivery_date,
        end_local_date=delivery_date,
        period_mode="custom_dates",
        dataset_split="test",
    )
    resolved_slice = resolve_input_slice(config, request=request, output_policy_name=OUTPUT_POLICY, use_cache=True)
    da_validation = _validate_da_slice(resolved_slice.scenarios, expected_delivery_date=delivery_date)
    if not da_validation["is_d_only_compatible"]:
        raise ValueError(f"DA input is not a clean 24-hour D-only block for {delivery_date}: {da_validation}")

    mfrr_input = load_mfrr_capacity_pilot_inputs(
        config.mfrr_capacity_pilot.export_path,
        start_local_date=delivery_date,
        end_local_date=delivery_date,
        capacity_offer_big_m_mw=config.mfrr_capacity_pilot.capacity_offer_big_m_mw,
        offer_continuous_mw=config.mfrr_capacity_pilot.offer_continuous_mw,
    )
    mfrr_validation = _validate_mfrr_slice(mfrr_input)
    if mfrr_validation["pilot_rows"] != 6 or mfrr_validation["candidate_rows"] != 6 or mfrr_validation["acceptance_rows"] != 18:
        raise ValueError(f"Unexpected one-day mFRR dimensions for {delivery_date}: {mfrr_validation}")

    revenue_coefficient_validation = _validate_mfrr_revenue_coefficients(mfrr_input)
    if revenue_coefficient_validation["max_abs_diff"] > TOLERANCE:
        raise ValueError(
            f"mFRR revenue coefficient scaling check failed for {delivery_date}: {revenue_coefficient_validation}"
        )

    common_kwargs = dict(
        day_scenarios=resolved_slice.scenarios,
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
    production_changed = abs((optional["production_kg"] or 0.0) - (baseline["production_kg"] or 0.0)) > TOLERANCE
    shortfall_present = any(
        abs((payload["shortfall_kg"] or 0.0)) > TOLERANCE for payload in (baseline, optional, forced_zero)
    )

    return {
        "delivery_date_local": delivery_date,
        "da_validation": da_validation,
        "mfrr_validation": mfrr_validation,
        "revenue_coefficient_validation": revenue_coefficient_validation,
        "baseline": baseline,
        "optional": optional,
        "forced_zero": forced_zero,
        "optionality_dominance_passes": optionality_dominance_passes,
        "forced_zero_matches_baseline": forced_zero_matches_baseline,
        "integer_mw_validation_passed": integer_mw_validation_passed,
        "production_changed": production_changed,
        "shortfall_present": shortfall_present,
        "all_modes_optimal": all(
            str(payload["solver_status"]).lower() == "optimal" for payload in (baseline, optional, forced_zero)
        ),
    }


def main() -> int:
    started = _now_utc()
    config_path = REPO_ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "configs" / "base_hydrogen.yaml"
    config = load_hydrogen_config(config_path)
    exact_solver_settings = replace(config.solver, mip_gap=min(float(config.solver.mip_gap), 1e-6))

    run_id = f"{started.strftime('%Y%m%d_%H%M%S')}_mfrr_capacity_integer_week_diagnostic_v1"
    output_root = (config.run_output_root / run_id).resolve()
    output_root.mkdir(parents=True, exist_ok=False)

    delivery_days = [day.date().isoformat() for day in pd.date_range(START_DATE, END_DATE, freq="D")]
    day_results = [_solve_day(config, exact_solver_settings, delivery_date=delivery_day) for delivery_day in delivery_days]

    metrics_rows: list[dict[str, object]] = []
    unique_contract_isp_count_values: set[int] = set()
    positive_up_days = 0
    positive_down_days = 0
    up_positive_values: list[float] = []
    down_positive_values: list[float] = []
    total_expected_capacity_revenue_eur = 0.0
    production_change_days: list[str] = []
    shortfall_days: list[str] = []
    dominance_fail_days: list[str] = []
    forced_zero_fail_days: list[str] = []
    integer_fail_days: list[str] = []

    for day_result in day_results:
        delivery_date = str(day_result["delivery_date_local"])
        baseline = day_result["baseline"]
        optional = day_result["optional"]
        forced_zero = day_result["forced_zero"]
        contract_isp_count_values = [int(v) for v in day_result["mfrr_validation"]["contract_isp_count_values"]]
        unique_contract_isp_count_values.update(contract_isp_count_values)

        optional_up = float(optional["offered_capacity_up_mw"] or 0.0)
        optional_down = float(optional["offered_capacity_down_mw"] or 0.0)
        optional_revenue = float(optional["expected_capacity_revenue_total_eur"] or 0.0)
        total_expected_capacity_revenue_eur += optional_revenue
        if optional_up > TOLERANCE:
            positive_up_days += 1
            up_positive_values.append(optional_up)
        if optional_down > TOLERANCE:
            positive_down_days += 1
            down_positive_values.append(optional_down)
        if bool(day_result["production_changed"]):
            production_change_days.append(delivery_date)
        if bool(day_result["shortfall_present"]):
            shortfall_days.append(delivery_date)
        if not bool(day_result["optionality_dominance_passes"]):
            dominance_fail_days.append(delivery_date)
        if not bool(day_result["forced_zero_matches_baseline"]):
            forced_zero_fail_days.append(delivery_date)
        if not bool(day_result["integer_mw_validation_passed"]):
            integer_fail_days.append(delivery_date)

        metrics_rows.append(
            {
                "delivery_date_local": delivery_date,
                "contract_isp_count": contract_isp_count_values[0] if contract_isp_count_values else None,
                "baseline_objective_eur": baseline["objective_value_eur"],
                "forced_zero_objective_eur": forced_zero["objective_value_eur"],
                "optional_objective_eur": optional["objective_value_eur"],
                "optional_up_mw": optional_up,
                "optional_down_mw": optional_down,
                "optional_expected_capacity_revenue_total_eur": optional_revenue,
                "baseline_production_kg": baseline["production_kg"],
                "optional_production_kg": optional["production_kg"],
                "forced_zero_production_kg": forced_zero["production_kg"],
                "baseline_shortfall_kg": baseline["shortfall_kg"],
                "optional_shortfall_kg": optional["shortfall_kg"],
                "forced_zero_shortfall_kg": forced_zero["shortfall_kg"],
                "optionality_dominance_passes": bool(day_result["optionality_dominance_passes"]),
                "forced_zero_matches_baseline": bool(day_result["forced_zero_matches_baseline"]),
                "integer_mw_validation_passed": bool(day_result["integer_mw_validation_passed"]),
                "production_changed_vs_baseline": bool(day_result["production_changed"]),
                "shortfall_present_any_mode": bool(day_result["shortfall_present"]),
            }
        )

    successful_solve_days = sum(1 for day_result in day_results if bool(day_result["all_modes_optimal"]))
    run_summary = {
        "period_start_local_date": START_DATE,
        "period_end_local_date": END_DATE,
        "days_solved": int(len(day_results)),
        "successful_solve_days": int(successful_solve_days),
        "positive_up_days": int(positive_up_days),
        "positive_down_days": int(positive_down_days),
        "average_selected_up_mw_on_positive_up_days": float(sum(up_positive_values) / len(up_positive_values)) if up_positive_values else 0.0,
        "average_selected_down_mw_on_positive_down_days": float(sum(down_positive_values) / len(down_positive_values)) if down_positive_values else 0.0,
        "total_expected_capacity_revenue_eur": float(total_expected_capacity_revenue_eur),
        "production_change_days": production_change_days,
        "shortfall_days": shortfall_days,
        "optionality_dominance_passed_for_all_days": len(dominance_fail_days) == 0,
        "forced_zero_matched_baseline_for_all_days": len(forced_zero_fail_days) == 0,
        "integer_mw_validation_passed_for_all_days": len(integer_fail_days) == 0,
        "unique_contract_isp_count_values": sorted(unique_contract_isp_count_values),
        "dominance_fail_days": dominance_fail_days,
        "forced_zero_fail_days": forced_zero_fail_days,
        "integer_fail_days": integer_fail_days,
        "example_formula": "2.22 EUR/MW/ISP * 35 MW * 96 ISP = 7459.20 EUR; 2.22 * 35 = 77.70 EUR is one-ISP only",
    }

    resolved_config_payload = {
        "base_config_path": _repo_rel(config.config_path),
        "artifact_id": ARTIFACT_ID,
        "period_start_local_date": START_DATE,
        "period_end_local_date": END_DATE,
        "output_policy": OUTPUT_POLICY,
        "run_class": RUN_CLASS,
        "lineage_role": LINEAGE_ROLE,
        "risk_gamma_used": 0.0,
        "apply_terminal_value": True,
        "mip_gap_used": float(exact_solver_settings.mip_gap),
        "modes": ["no_mfrr_baseline", "mfrr_optional", "mfrr_forced_zero"],
        "mfrr_export_contract": "v2_eur_per_mw_per_isp_with_contract_isp_count",
        "integer_mw_bids_enforced": True,
    }
    _write_yaml(output_root / "resolved_config.yaml", resolved_config_payload)

    input_manifest = {
        "da_artifact_id": ARTIFACT_ID,
        "da_scenario_catalog": _fingerprint_file(config.models.scenario_catalog),
        "da_config": _fingerprint_file(config.config_path),
        "mfrr_export": _fingerprint_file(Path(config.mfrr_capacity_pilot.export_path)),
        "selected_period": {"start_local_date": START_DATE, "end_local_date": END_DATE},
    }
    _write_json(output_root / "input_manifest.json", _relativize_paths(input_manifest))

    code_version = {
        "timestamp_utc": _iso(_now_utc()),
        "runner": _repo_rel(SCRIPT_PATH),
        "python_version": sys.version,
        "platform": platform.platform(),
        "git_commit": None,
    }
    _write_json(output_root / "code_version.json", code_version)

    _write_json(output_root / "run_summary.json", run_summary)
    pd.DataFrame(metrics_rows).to_csv(output_root / "metrics_summary.csv", index=False)

    (output_root / "warnings_and_limitations.md").write_text(
        "\n".join(
            [
                "- Small multi-day diagnostic only; not a thesis-ready campaign.",
                "- Capacity offers are enforced as integer MW with a 1 MW minimum when selected.",
                "- The MILP consumes the repaired v2 incident-reserve capacity export with EUR/MW/ISP prices and contract_isp_count scaling.",
                "- This remains capacity-only: no activation, energy-bid optimisation, settlement, sanctions, or MARI is modelled.",
                "- Positive optional capacity or production changes are diagnostic signals only and do not by themselves prove activation feasibility or final economic value.",
            ]
        ),
        encoding="utf-8",
    )

    registry_entry = {
        "run_id": run_id,
        "timestamp": _iso(started),
        "domain": "optimisation",
        "market": "DA_plus_mFRR_capacity_integer_week_diagnostic",
        "pipeline_stage": "diagnostic",
        "granularity": "hourly",
        "horizon": "D_only",
        "model_family": "hydrogen_stochastic_dispatch",
        "feature_set": "not_applicable",
        "scenario_source": ARTIFACT_ID,
        "input_artifacts": [
            {"artifact_id": ARTIFACT_ID, "path": _repo_rel(config.models.scenario_catalog)},
            {"artifact_id": "nl_ir_capacity_milp_input_daily_direction_scenarios_v2", "path": _repo_rel(config.mfrr_capacity_pilot.export_path)},
        ],
        "output_root": _repo_rel(output_root),
        "output_policy": OUTPUT_POLICY,
        "run_class": RUN_CLASS,
        "lineage_role": LINEAGE_ROLE,
        "status": "completed",
        "thesis_usable": "conditional",
        "key_result": (
            "Small multi-day diagnostic completed with integer MW bids, 1 MW minimum when selected, and v2 ISP-scaled revenue."
        ),
        "limitations": "Small diagnostic only; capacity-only; no activation; no settlement; no production-first refactor.",
        "archive_location": None,
        "delete_after": None,
        "git_commit": None,
    }
    _write_json(output_root / "registry_entry.json", registry_entry)

    print(f"RUN_DIR={output_root}")
    print(f"PERIOD={START_DATE}_to_{END_DATE}")
    print(f"DAYS_SOLVED={run_summary['days_solved']}")
    print(f"SUCCESSFUL_SOLVE_DAYS={run_summary['successful_solve_days']}")
    print(f"POSITIVE_UP_DAYS={run_summary['positive_up_days']}")
    print(f"POSITIVE_DOWN_DAYS={run_summary['positive_down_days']}")
    print(f"TOTAL_EXPECTED_CAPACITY_REVENUE_EUR={run_summary['total_expected_capacity_revenue_eur']}")
    print(f"OPTIONALITY_DOMINANCE_ALL_DAYS={run_summary['optionality_dominance_passed_for_all_days']}")
    print(f"FORCED_ZERO_ALL_DAYS={run_summary['forced_zero_matched_baseline_for_all_days']}")
    print(f"INTEGER_MW_ALL_DAYS={run_summary['integer_mw_validation_passed_for_all_days']}")
    print(f"UNIQUE_CONTRACT_ISP_COUNT_VALUES={run_summary['unique_contract_isp_count_values']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
