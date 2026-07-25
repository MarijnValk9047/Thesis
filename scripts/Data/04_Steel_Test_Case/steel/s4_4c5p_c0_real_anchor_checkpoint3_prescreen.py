"""Non-solver Checkpoint 3 preparation for the C0 real-anchor screen."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Mapping

from steel.s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    _annual_model_metrics,
    _c0_real_anchor_energy_recovery_interfaces,
    _config,
    _deterministic_cost_policy,
    _electricity_boundary_levers,
    _external_procurement_flow_coefficients,
    _first_order_full_site_co2_ledger,
    _model_target_multiplier,
    _procurement_cost_ledger,
    _reference_definition,
    _rolling_production_progress_contract,
    _rolling_plans_from_config,
    _source_coke_chain,
)
from steel.s4_4c_component_ontology import (
    continuous_must_run_activities,
    load_future_cost_boundary_contract,
    load_route_boundary_contract,
)
from steel.s4_4c_unified_physical_modelbuilder import (
    S44B_INPUT_DIR,
    _load_tables,
    _solve_c0_configuration,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_real_anchor_energy_recovery.yaml"
)
DEFAULT_RUN_ROOT = (
    REPO_ROOT
    / "data/03_Optimisation/runs/steel_c5_real_anchor_energy_recovery_v1_20260722"
)
WEEK_CONTRACT_PATH = (
    REPO_ROOT
    / "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract"
    / "representative_week_selection_contract.csv"
)
FROZEN_PERIOD_ID = "validation_2024-02-12"
HOURS_PER_YEAR = 8760.0
PJ_PER_MWH = 3.6e-6
GROSS_ELECTRICITY_CONTEXT_LOW_TWH_Y = 3.0
GROSS_ELECTRICITY_CONTEXT_CENTRAL_TWH_Y = 3.17
GROSS_ELECTRICITY_CONTEXT_HIGH_TWH_Y = 3.17
MATERIAL_RELATIVE_ERROR_IMPROVEMENT = 0.001


CASE_DEFINITIONS = (
    ("source_driven_baseline", False, 0.0, "source_driven_baseline_boundary", False),
    ("recovery_bg00", True, 0.0, "repaired_real_anchor_no_background", False),
    ("recovery_bg15", True, 0.4755, "user_authorized_central_background_bridge", False),
    ("recovery_bg25", True, 0.7925, "user_authorized_central_background_bridge", False),
    (
        "recovery_bg30_stress",
        True,
        0.9510,
        "user_authorized_boundary_stress_outside_prior_5_25_not_source_calibrated",
        True,
    ),
)


class Checkpoint3PrescreenError(RuntimeError):
    """Raised when the frozen dry-run contract is internally inconsistent."""


def load_frozen_development_week() -> dict[str, Any]:
    with WEEK_CONTRACT_PATH.open(encoding="utf-8", newline="") as handle:
        matches = [
            row for row in csv.DictReader(handle) if row["period_id"] == FROZEN_PERIOD_ID
        ]
    if len(matches) != 1:
        raise Checkpoint3PrescreenError("Frozen development week must resolve exactly once.")
    row = matches[0]
    required = {
        "dataset_split": "validation",
        "period_role": "development",
        "execution_hours": "168",
        "dst_status": "ordinary_168_hour_week",
        "operational_price_field": "y_pred",
        "optimisation_result_inputs_used": "False",
        "anchor_residual_inputs_used": "False",
        "selection_status": "frozen",
    }
    for key, expected in required.items():
        if row[key] != expected:
            raise Checkpoint3PrescreenError(
                f"Frozen development-week field {key} must remain {expected}."
            )
    return {
        **row,
        "delivery_start_utc": "2024-02-11T23:00:00+00:00",
        "delivery_end_exclusive_utc": "2024-02-18T23:00:00+00:00",
        "timezone": "Europe/Amsterdam",
        "final_eight_held_out_selection_eligible": False,
        "selection_used_optimization_results": False,
        "selection_used_anchor_residuals": False,
    }


def resolve_candidate_manifest(
    config: Mapping[str, Any], *, run_root: Path = DEFAULT_RUN_ROOT
) -> list[dict[str, Any]]:
    if config.get("execution_authorized") not in {True, False}:
        raise Checkpoint3PrescreenError(
            "execution_authorized must be an explicit boolean."
        )
    if config.get("required_solver_family") != "gurobi":
        raise Checkpoint3PrescreenError("Checkpoint 3 requires Gurobi.")
    if config.get("rolling_production_progress_state_enabled") is not True:
        raise Checkpoint3PrescreenError("Cumulative production progress must remain enabled.")
    if abs(float(config.get("production_envelope_tolerance_fraction", -1.0)) - 0.005) > 1e-12:
        raise Checkpoint3PrescreenError("Production envelope tolerance must remain 0.005.")
    plans, _ = _rolling_plans_from_config(config)
    plan = plans[0]
    if plan.planning_horizon_hours != 168 or plan.execution_block_hours != 24:
        raise Checkpoint3PrescreenError("Checkpoint 3 requires the governed 168h/24h plan.")
    generator, bridge = _c0_real_anchor_energy_recovery_interfaces(config)
    if generator is None or bridge is None:
        raise Checkpoint3PrescreenError("Reviewed real-anchor interfaces must resolve.")

    rows: list[dict[str, Any]] = []
    for order, (case_id, repair_active, background_twh_y, role, outside_prior) in enumerate(
        CASE_DEFINITIONS, start=1
    ):
        rows.append(
            {
                "case_order": order,
                "candidate_id": case_id,
                "repair_interface_active": repair_active,
                "explicit_background_twh_y": background_twh_y,
                "explicit_background_mwh_h": background_twh_y * 1_000_000.0 / HOURS_PER_YEAR,
                "boundary_role": role,
                "outside_prior_5_25_range": outside_prior,
                "generator_efficiency": generator["electricity_efficiency"],
                "generator_mixed_volume_cap_nm3_h": generator[
                    "total_fuel_volume_cap_nm3_h"
                ],
                "generator_electrical_capacity_mw": generator["electrical_capacity_mw"],
                "natural_gas_lhv_mj_per_nm3": generator["natural_gas_lhv_mj_per_nm3"],
                "no_export": not generator["export_allowed"],
                "inferred_low_case_ng_floor_pj_y": float(
                    config["c0_full_site_energy_bridge"][
                        "inferred_low_case_full_site_ng_floor_pj_y"
                    ]
                ),
                "already_represented_fixed_ng_pj_y": float(
                    config["c0_full_site_energy_bridge"][
                        "already_represented_fixed_ng_pj_y"
                    ]
                ),
                "flexible_heat_service_envelope_pj_y": float(
                    config["c0_full_site_energy_bridge"][
                        "flexible_other_site_heat_service_envelope_pj_y"
                    ]
                ),
                "normal_case_flexible_ng_validation_reference_pj_y": float(
                    config["c0_full_site_energy_bridge"][
                        "normal_case_flexible_ng_validation_reference_pj_y"
                    ]
                ),
                "production_policy": "cumulative_progress_0p005_envelope",
                "initial_state_policy": "identical_reviewed_successor_default_initial_state",
                "material_coefficients_policy": "identical_reviewed_successor_config",
                "wag_yields_policy": "identical_source_driven_no_override",
                "price_policy": "price_insensitive_flat_central_reference_v1",
                "planning_horizon_hours": 168,
                "output_subdirectory": str(run_root / "checkpoint3_cases" / case_id),
                "solver_required": "gurobi",
                "solver_invoked": False,
                "execution_status": "prepared_license_blocked",
                "empirical_annual_result": False,
            }
        )
    if len(rows) != 5 or tuple(row["candidate_id"] for row in rows) != tuple(
        item[0] for item in CASE_DEFINITIONS
    ):
        raise Checkpoint3PrescreenError("Exactly the five governed candidates are required.")
    repaired_signatures = {
        (
            row["generator_efficiency"],
            row["generator_mixed_volume_cap_nm3_h"],
            row["generator_electrical_capacity_mw"],
            row["natural_gas_lhv_mj_per_nm3"],
            row["inferred_low_case_ng_floor_pj_y"],
            row["flexible_heat_service_envelope_pj_y"],
            row["normal_case_flexible_ng_validation_reference_pj_y"],
            row["production_policy"],
            row["initial_state_policy"],
            row["material_coefficients_policy"],
            row["wag_yields_policy"],
        )
        for row in rows
        if row["repair_interface_active"]
    }
    if len(repaired_signatures) != 1:
        raise Checkpoint3PrescreenError(
            "Repaired candidates may differ only by the declared background bridge."
        )
    if len({row["output_subdirectory"] for row in rows}) != 5:
        raise Checkpoint3PrescreenError("Candidate output directories must be unique.")
    return rows


def dry_run_prescreen(
    *, config_path: Path = DEFAULT_CONFIG_PATH, run_root: Path = DEFAULT_RUN_ROOT
) -> dict[str, Any]:
    config = _config(config_path)
    candidates = resolve_candidate_manifest(config, run_root=run_root)
    week = load_frozen_development_week()
    return {
        "status": "checkpoint3_prepared_license_blocked",
        "candidate_count": len(candidates),
        "candidate_ids": [row["candidate_id"] for row in candidates],
        "planning_horizon_hours": 168,
        "cumulative_production_progress_enabled": True,
        "production_envelope_tolerance_fraction": 0.005,
        "identical_initial_state_policy": True,
        "only_declared_background_moves_across_repaired_candidates": True,
        "frozen_period_id": week["period_id"],
        "final_eight_held_out_selection_eligible": False,
        "gurobi_required": True,
        "gurobi_invoked": False,
        "model_built": False,
        "candidate_scorecard_created": False,
        "output_root": str(run_root),
        "checks_passed": 12,
        "failure_count": 0,
    }


def _number(value: Any) -> float:
    return 0.0 if value in {None, ""} else float(value)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise Checkpoint3PrescreenError(f"Refusing to write empty output: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _c0_progress_execution_arguments(progress: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_multiplier": progress["target_multiplier_by_configuration"][
            C0_CONFIGURATION
        ],
        "deadline_targets": progress["deadline_targets_by_configuration_t"][
            C0_CONFIGURATION
        ],
        "progress_target": progress["progress_target_by_configuration_t"][
            C0_CONFIGURATION
        ],
        "progress_lower": progress[
            "progress_lower_bound_by_configuration_t"
        ].get(C0_CONFIGURATION),
        "progress_upper": progress[
            "progress_upper_bound_by_configuration_t"
        ].get(C0_CONFIGURATION),
    }


def gross_electricity_band_score(value_twh_y: float) -> dict[str, float]:
    signed_central_residual = (
        float(value_twh_y) - GROSS_ELECTRICITY_CONTEXT_CENTRAL_TWH_Y
    )
    if value_twh_y < GROSS_ELECTRICITY_CONTEXT_LOW_TWH_Y:
        band_distance = GROSS_ELECTRICITY_CONTEXT_LOW_TWH_Y - float(value_twh_y)
    elif value_twh_y > GROSS_ELECTRICITY_CONTEXT_HIGH_TWH_Y:
        band_distance = float(value_twh_y) - GROSS_ELECTRICITY_CONTEXT_HIGH_TWH_Y
    else:
        band_distance = 0.0
    return {
        "gross_electricity_central_signed_residual_twh_y": signed_central_residual,
        "gross_electricity_band_distance_twh_y": band_distance,
        "gross_electricity_band_relative_error": (
            band_distance / GROSS_ELECTRICITY_CONTEXT_LOW_TWH_Y
        ),
        "gross_electricity_band_relative_error_denominator_twh_y": (
            GROSS_ELECTRICITY_CONTEXT_LOW_TWH_Y
        ),
    }


def is_material_relative_error_improvement(
    baseline_error: float,
    candidate_error: float,
    *,
    threshold: float = MATERIAL_RELATIVE_ERROR_IMPROVEMENT,
) -> bool:
    return float(baseline_error) - float(candidate_error) >= threshold


def score_and_select_checkpoint3_rows(
    source_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in source_rows]
    if {str(row["candidate_id"]) for row in rows} != {
        case[0] for case in CASE_DEFINITIONS
    }:
        raise Checkpoint3PrescreenError(
            "Solved score refresh requires exactly the frozen five candidates."
        )
    for row in rows:
        value = float(row["gross_electricity_twh_y"])
        row.update(gross_electricity_band_score(value))
        row["gross_electricity_relative_error"] = abs(
            value - GROSS_ELECTRICITY_CONTEXT_CENTRAL_TWH_Y
        ) / GROSS_ELECTRICITY_CONTEXT_CENTRAL_TWH_Y
        row["material_improvement_threshold_absolute_relative_error"] = (
            MATERIAL_RELATIVE_ERROR_IMPROVEMENT
        )
        row["energy_anchor_use"] = "screening_calibration_target"
        row["independent_energy_validation_reuse_allowed"] = False
        row["candidate_classification"] = (
            "source_driven_reference_baseline"
            if row["candidate_id"] == "source_driven_baseline"
            else "emulation_sensitivity_only"
        )
        row["promotable_central_from_checkpoint3"] = False
        row["selected_for_checkpoint4"] = False

    baseline = next(
        row for row in rows if row["candidate_id"] == "source_driven_baseline"
    )
    comparison_fields = {
        "gross_electricity": "gross_electricity_band_relative_error",
        "wag_only_electricity": "wag_only_electricity_relative_error",
        "named_ng": "named_ng_relative_error",
        "coal": "coal_relative_error",
        "first_order_co2": "first_order_co2_relative_error",
    }
    for row in rows:
        improvement_flags = {
            family: is_material_relative_error_improvement(
                float(baseline[field]), float(row[field])
            )
            for family, field in comparison_fields.items()
        }
        for family, improved in improvement_flags.items():
            row[f"{family}_material_improvement_vs_baseline"] = improved
        row["improved_energy_family_count_vs_baseline"] = sum(
            improvement_flags[family]
            for family in ("gross_electricity", "wag_only_electricity", "named_ng")
        )
        row["improved_independent_validation_family_count_vs_baseline"] = sum(
            improvement_flags[family] for family in ("coal", "first_order_co2")
        )
        row["improved_family_count_vs_baseline"] = sum(improvement_flags.values())
        non_gross_fields = (
            "wag_only_electricity_relative_error",
            "named_ng_relative_error",
            "coal_relative_error",
            "first_order_co2_relative_error",
        )
        row["non_gross_mean_relative_error"] = sum(
            float(row[field]) for field in non_gross_fields
        ) / len(non_gross_fields)
        row["all_family_mean_relative_error"] = (
            float(row["gross_electricity_band_relative_error"])
            + sum(float(row[field]) for field in non_gross_fields)
        ) / 5
        row["all_family_central_point_mean_relative_error"] = (
            float(row["gross_electricity_relative_error"])
            + sum(float(row[field]) for field in non_gross_fields)
        ) / 5

    baseline["selected_for_checkpoint4"] = True
    baseline["selection_reason"] = "mandatory_source_driven_reference_baseline"
    eligible = [
        row
        for row in rows
        if row["candidate_id"]
        not in {"source_driven_baseline", "recovery_bg30_stress"}
        and row["guardrail_status"] == "pass"
    ]
    eligible.sort(
        key=lambda row: (
            -int(row["improved_energy_family_count_vs_baseline"]),
            float(row["gross_electricity_band_relative_error"]),
            float(row["source_deviation_background_share_of_3p17"]),
            str(row["candidate_id"]),
        )
    )
    if eligible and int(eligible[0]["improved_energy_family_count_vs_baseline"]) >= 2:
        selected = eligible[0]
        selected["selected_for_checkpoint4"] = True
        selected["selection_reason"] = (
            "retained_emulation_sensitivity_only_best_gross_band_fit_among_"
            "materially_equal_non_stress_recovery_cases"
        )
    for row in rows:
        if row["selected_for_checkpoint4"]:
            continue
        if row["candidate_id"] == "recovery_bg30_stress":
            row["selection_reason"] = (
                "excluded_stress_boundary_fit_not_promotable_central"
            )
        elif row["candidate_id"] == "recovery_bg15":
            row["selection_reason"] = (
                "not_selected_material_energy_tie_larger_gross_band_distance_"
                "than_recovery_bg25"
            )
        else:
            row["selection_reason"] = (
                "not_selected_fewer_material_energy_family_improvements"
            )
    return rows


def _checkpoint3_readme(
    score_rows: list[dict[str, Any]], week: Mapping[str, Any]
) -> str:
    retained = [
        str(row["candidate_id"])
        for row in score_rows
        if str(row["selected_for_checkpoint4"]).lower() == "true"
        or row["selected_for_checkpoint4"] is True
    ]
    return (
        "# C0 real-anchor energy-recovery Checkpoint 3 result\n\n"
        "Status: `checkpoint3_solved`; reporting correction applied and reviewer "
        "confirmation pending.\n\n"
        f"Exactly five frozen C0 cases solved optimally with Gurobi on the 168-hour "
        f"development period `{week['period_id']}` "
        f"({week['delivery_start_utc']} through "
        f"{week['delivery_end_exclusive_utc']}, end-exclusive). The scorecard and "
        "solver summaries are present. No hourly dispatch file was persisted under "
        "the minimal output policy.\n\n"
        "For this bounded recovery cycle, the real C0 gross-electricity band, "
        "WAG-only generator electricity, and named NG observations are screening "
        "calibration targets. They cannot later be reused as independent validation. "
        "Coal and first-order CO2 remain independent non-deterioration/directional "
        "checks; controlled behaviour remains a separate directional validation "
        "gate.\n\n"
        "Gross electricity is reported both against the 3.17 TWh/y central context "
        "point and the comparable 3.00-3.17 TWh/y band. Band-relative error uses "
        "3.00 TWh/y as its denominator. Material improvement requires an absolute "
        "relative-error reduction of at least 0.001 (0.1 percentage point).\n\n"
        f"Retained comparison pair: `{retained[0]}` and `{retained[1]}`. "
        "`recovery_bg25` is classified `emulation_sensitivity_only` and is never "
        "promotable to a central case from this checkpoint. It beats `recovery_bg15` "
        "solely through the gross background bridge after WAG-only electricity and "
        "named NG are materially tied. `recovery_bg30_stress` is a boundary-fit "
        "stress case and is excluded from central selection.\n\n"
        "All reported annual values are annualized development-week screening "
        "metrics, not empirical annual results. The frozen `candidate_manifest.csv` "
        "is preserved as pre-execution input provenance; `candidate_configs/*.json` "
        "contains the corrected solved execution snapshots. No controlled-behaviour "
        "run or Checkpoint 4 run has started.\n"
    )


def refresh_checkpoint3_reporting(
    *, run_root: Path = DEFAULT_RUN_ROOT
) -> dict[str, Any]:
    """Refresh solved Checkpoint 3 reporting without building or solving a model."""

    score_path = run_root / "candidate_scorecard.csv"
    runtime_path = run_root / "solver_runtime_metrics.csv"
    guardrail_path = run_root / "physical_guardrails.csv"
    with score_path.open(encoding="utf-8", newline="") as handle:
        score_rows = score_and_select_checkpoint3_rows(list(csv.DictReader(handle)))
    with runtime_path.open(encoding="utf-8", newline="") as handle:
        runtime_rows = [dict(row) for row in csv.DictReader(handle)]
    with guardrail_path.open(encoding="utf-8", newline="") as handle:
        guardrail_rows = [dict(row) for row in csv.DictReader(handle)]
    if len(runtime_rows) != 5 or any(
        str(row["termination_condition"]).lower() != "optimal"
        for row in runtime_rows
    ):
        raise Checkpoint3PrescreenError(
            "Reporting refresh requires five existing optimal solver records."
        )
    if len(guardrail_rows) != 5 or any(
        str(row["status"]).lower() != "pass" for row in guardrail_rows
    ):
        raise Checkpoint3PrescreenError(
            "Reporting refresh requires five passing physical guardrail records."
        )

    runtime_by_candidate: dict[str, dict[str, Any]] = {}
    for row in runtime_rows:
        raw_gap = row.get("mip_gap")
        if raw_gap in {None, ""}:
            row["mip_gap"] = 0.0
            row["mip_gap_basis"] = (
                "optimal_termination_no_numeric_gap_reported"
            )
        else:
            row["mip_gap_basis"] = "solver_reported_numeric_gap"
        runtime_by_candidate[str(row["candidate_id"])] = row

    _write_csv(score_path, score_rows)
    _write_csv(runtime_path, runtime_rows)
    selected = {
        str(row["candidate_id"]): row
        for row in score_rows
    }
    snapshot_root = run_root / "candidate_configs"
    for case_id, score_row in selected.items():
        snapshot_path = snapshot_root / f"{case_id}.json"
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        candidate = dict(payload["candidate"])
        candidate.update(
            {
                "execution_status": "solved_optimal",
                "solver_invoked": True,
                "candidate_classification": score_row[
                    "candidate_classification"
                ],
                "promotable_central_from_checkpoint3": False,
                "selected_for_checkpoint4": score_row[
                    "selected_for_checkpoint4"
                ],
            }
        )
        runtime = runtime_by_candidate[case_id]
        payload.update(
            {
                "candidate": candidate,
                "execution_status": "solved_optimal",
                "solver_invoked": True,
                "solver_status": runtime["solver_status"],
                "termination_condition": runtime["termination_condition"],
                "mip_gap": float(runtime["mip_gap"]),
                "mip_gap_basis": runtime["mip_gap_basis"],
                "candidate_classification": score_row[
                    "candidate_classification"
                ],
                "promotable_central_from_checkpoint3": False,
                "selected_for_checkpoint4": score_row[
                    "selected_for_checkpoint4"
                ],
            }
        )
        _write_json(snapshot_path, payload)

    retained = [
        str(row["candidate_id"])
        for row in score_rows
        if row["selected_for_checkpoint4"] is True
        or str(row["selected_for_checkpoint4"]).lower() == "true"
    ]
    state_path = run_root / "checkpoint_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "status": "checkpoint3_solved",
            "review_status": "checkpoint3_solved_review_correction_pending",
            "dispatch_results_present": False,
            "score_results_present": True,
            "candidate_scorecard_present": True,
            "solver_runtime_metrics_present": True,
            "checkpoint3_reporting_correction_applied": True,
            "checkpoint3_retained_candidates": retained,
            "gurobi_license_blocked": False,
        }
    )
    _write_json(state_path, state)
    week = load_frozen_development_week()
    (run_root / "README.md").write_text(
        _checkpoint3_readme(score_rows, week), encoding="utf-8"
    )
    return {
        "candidate_scorecard": score_rows,
        "solver_runtime_metrics": runtime_rows,
        "retained_candidates": retained,
        "period": week,
    }


def execute_checkpoint3(
    *, config_path: Path = DEFAULT_CONFIG_PATH, run_root: Path = DEFAULT_RUN_ROOT
) -> dict[str, Any]:
    """Run exactly the frozen five C0 cases through the existing C0 solver path."""

    config = _config(config_path)
    if config.get("execution_authorized") is not True:
        raise Checkpoint3PrescreenError("Checkpoint 3 execution is not authorized in config.")
    candidates = resolve_candidate_manifest(config, run_root=run_root)
    week = load_frozen_development_week()
    plans, _ = _rolling_plans_from_config(config)
    plan = plans[0]
    base_target_multiplier = _model_target_multiplier(config, plan)
    progress = _rolling_production_progress_contract(
        plan=plan,
        replan_index=0,
        cumulative_before={C0_CONFIGURATION: 0.0},
        base_target_multiplier=base_target_multiplier,
        enabled=True,
        envelope_fraction=0.005,
        central_target_before_t=0.0,
        terminal_exact=False,
    )
    progress_arguments = _c0_progress_execution_arguments(progress)
    target_multiplier = progress_arguments["target_multiplier"]
    deadline_targets = progress_arguments["deadline_targets"]
    progress_target = progress_arguments["progress_target"]
    progress_lower = progress_arguments["progress_lower"]
    progress_upper = progress_arguments["progress_upper"]
    _, c0_reference_routing, _ = _reference_definition(
        config, horizon_hours=plan.planning_horizon_hours
    )
    source_coke_chain = _source_coke_chain(config)
    external_coefficients = _external_procurement_flow_coefficients(
        config, load_route_boundary_contract()
    )
    (
        linde_n2_mwh_h,
        _eaf_secondary,
        _dsp_electricity,
        _base_background,
        _background_by_configuration,
    ) = _electricity_boundary_levers(config)
    tables = _load_tables(S44B_INPUT_DIR)
    cost_contract = load_future_cost_boundary_contract()
    generator_interface, energy_bridge = _c0_real_anchor_energy_recovery_interfaces(config)
    commitment_day_lengths = [24] * 7

    score_rows: list[dict[str, Any]] = []
    guardrail_rows: list[dict[str, Any]] = []
    runtime_rows: list[dict[str, Any]] = []
    movement_rows: list[dict[str, Any]] = []
    snapshots: dict[str, Any] = {}
    anchor_values = {
        "gross_electricity_twh_y": 3.17,
        "wag_power_twh_y": 2.528,
        "represented_ng_pj_y": 9.666,
        "coal_mt_y": 3.66,
        "first_order_co2_mt_y": 12.24,
    }
    execution_start = time.perf_counter()
    for candidate in candidates:
        case_id = str(candidate["candidate_id"])
        repair_active = bool(candidate["repair_interface_active"])
        case_config = dict(config)
        if not repair_active:
            case_config.pop("c0_aggregate_generator_technical_interface", None)
            case_config.pop("c0_full_site_energy_bridge", None)
        deterministic_cost_policy = _deterministic_cost_policy(
            case_config,
            cost_contract,
            horizon_hours=168,
            replan_index=0,
            execution_block_hours=24,
        )
        case_start = time.perf_counter()
        audit, _constraint_rows, hourly = _solve_c0_configuration(
            tables,
            horizon_hours_override=168,
            target_multiplier=target_multiplier,
            fix_binary_schedule=False,
            enable_minimal_wag_layer=True,
            enable_internal_wag_power=True,
            development_controller_activation=str(
                config.get("development_controller_activation", "full_electricity_boundary")
            ),
            daily_production_guardrail=False,
            rolling_production_deadline_targets_t=deadline_targets,
            rolling_production_progress_target_t=progress_target,
            rolling_production_progress_lower_bound_t=progress_lower,
            rolling_production_progress_upper_bound_t=progress_upper,
            rolling_production_execution_block_hours=24,
            rolling_production_hard_exact_execution_target=False,
            commitment_granularity=str(config["commitment_granularity"]),
            commitment_day_lengths=commitment_day_lengths,
            solver_time_limit_seconds=float(config["solver_time_limit_seconds"]),
            continuous_must_run_activities=continuous_must_run_activities(C0_CONFIGURATION),
            c0_coke_chain_reconciliation=source_coke_chain,
            c0_downstream_reference_routing=c0_reference_routing,
            linde_n2_auxiliary_electricity_mwh_h=linde_n2_mwh_h,
            site_background_electricity_mwh_h=float(
                candidate["explicit_background_mwh_h"]
            ),
            external_procurement_flow_coefficients=external_coefficients,
            deterministic_cost_policy=deterministic_cost_policy,
            bf_electricity_intensity_scale=1.0,
            aggregate_generator_technical_interface=(
                generator_interface if repair_active else None
            ),
            full_site_energy_bridge=energy_bridge if repair_active else None,
        )
        wall_runtime = time.perf_counter() - case_start
        if audit.get("build_status") != "solved" or str(
            audit.get("termination_condition", "")
        ).lower() != "optimal":
            raise Checkpoint3PrescreenError(
                f"{case_id} stopped Checkpoint 3: {audit.get('build_status')}/"
                f"{audit.get('termination_condition')}."
            )
        metrics_by_configuration, _ = _annual_model_metrics(hourly)
        metrics = metrics_by_configuration[C0_CONFIGURATION]
        factor = HOURS_PER_YEAR / len(hourly)
        total = lambda field: sum(_number(row.get(field)) for row in hourly)
        flex_wag_mwh = sum(
            total(field)
            for field in (
                "BFG_to_flexible_other_site_heat_mwh",
                "COG_to_flexible_other_site_heat_mwh",
                "BOFG_to_flexible_other_site_heat_mwh",
            )
        )
        generator_wag_mwh = total("vattenfall_fuel_mwh")
        process_wag_mwh = total("WAG_used") - generator_wag_mwh - flex_wag_mwh
        coal_mt_y = float(audit["coking_input_total_t"]) * factor / 1_000_000.0
        first_order_rows = _first_order_full_site_co2_ledger(hourly)
        first_order_total = next(
            _number(row.get("annual_co2_mt_y"))
            for row in first_order_rows
            if row.get("configuration_id") == C0_CONFIGURATION
            and row.get("component") == "first_order_full_site_CO2_total"
        )
        cost_ledger = _procurement_cost_ledger(
            hourly,
            deterministic_cost_policy,
            run_id=f"{config['run_id']}::{case_id}",
            replan_index=0,
        )
        ledger_cost = sum(_number(row.get("cost_eur")) for row in cost_ledger)
        objective_cost = _number(audit.get("primary_cost_objective_eur"))
        material_residual = max(
            (
                abs(_number(value))
                for row in hourly
                for key, value in row.items()
                if key.endswith("balance_residual_t")
                or "material_balance_residual" in key
            ),
            default=0.0,
        )
        wag_residual = max(
            (
                abs(_number(row.get(field)))
                for row in hourly
                for field in (
                    "BFG_balance_residual_mwh",
                    "COG_balance_residual_mwh",
                    "BOFG_balance_residual_mwh",
                )
            ),
            default=0.0,
        )
        electricity_residual = max(
            (
                abs(_number(row.get("gross_site_electricity_identity_residual_mwh")))
                for row in hourly
            ),
            default=0.0,
        )
        no_export_violation = max(
            (
                max(
                    0.0,
                    _number(row.get("total_generator_electricity_mwh"))
                    - _number(row.get("gross_total_electricity_mwh")),
                )
                for row in hourly
            ),
            default=0.0,
        )
        ng_split_sum = sum(
            metrics[key]
            for key in (
                "drp_named_ng_pj_y",
                "eaf_named_ng_pj_y",
                "hsm_named_ng_pj_y",
                "pefa_named_ng_pj_y",
                "boiler_named_ng_pj_y",
                "generator_named_ng_pj_y",
                "fixed_bridge_named_ng_pj_y",
                "flexible_bridge_named_ng_pj_y",
            )
        )
        ng_identity_residual = metrics["represented_ng_pj_y"] - ng_split_sum
        cost_identity_residual = objective_cost - ledger_cost
        guardrail_pass = (
            abs(_number(audit.get("final_product_residual_t"))) <= 1e-5
            and material_residual <= 1e-6
            and wag_residual <= 1e-6
            and electricity_residual <= 1e-6
            and abs(ng_identity_residual) <= 1e-6
            and abs(cost_identity_residual) <= 0.05
            and no_export_violation <= 1e-6
        )
        guardrail_rows.append(
            {
                "candidate_id": case_id,
                "status": "pass" if guardrail_pass else "fail",
                "production_residual_t": audit.get("final_product_residual_t"),
                "max_material_balance_residual_t": material_residual,
                "max_carrier_wag_balance_residual_mwh": wag_residual,
                "max_electricity_identity_residual_mwh": electricity_residual,
                "named_ng_subtotal_identity_residual_pj_y": ng_identity_residual,
                "cost_objective_minus_ledger_eur": cost_identity_residual,
                "max_no_export_violation_mwh": no_export_violation,
            }
        )
        if not guardrail_pass:
            raise Checkpoint3PrescreenError(
                f"{case_id} stopped Checkpoint 3 on physical/accounting guardrails."
            )
        volume_binding_hours = (
            sum(
                _number(row.get("aggregate_generator_volume_unused_nm3_h")) <= 1e-3
                for row in hourly
            )
            if repair_active
            else 0
        )
        electrical_binding_hours = (
            sum(
                abs(
                    _number(row.get("total_generator_electricity_mwh")) - 770.0
                )
                <= 1e-6
                for row in hourly
            )
            if repair_active
            else 0
        )
        no_export_binding_hours = sum(
            abs(
                _number(row.get("total_generator_electricity_mwh"))
                - _number(row.get("gross_total_electricity_mwh"))
            )
            <= 1e-6
            for row in hourly
        )
        values = {
            "gross_electricity_twh_y": metrics["gross_electricity_twh_y"],
            "wag_power_twh_y": metrics["wag_power_twh_y"],
            "represented_ng_pj_y": metrics["represented_ng_pj_y"],
            "coal_mt_y": coal_mt_y,
            "first_order_co2_mt_y": first_order_total,
        }
        errors = {
            key: abs(values[key] - anchor) / anchor
            for key, anchor in anchor_values.items()
        }
        score_rows.append(
            {
                "candidate_id": case_id,
                "boundary_role": candidate["boundary_role"],
                "guardrail_status": "pass",
                "gross_electricity_twh_y": values["gross_electricity_twh_y"],
                "gross_electricity_relative_error": errors["gross_electricity_twh_y"],
                "wag_only_generator_electricity_twh_y": values["wag_power_twh_y"],
                "wag_only_electricity_relative_error": errors["wag_power_twh_y"],
                "ng_generator_electricity_twh_y": metrics["ng_generator_electricity_twh_y"],
                "total_generator_electricity_twh_y": metrics["generator_electricity_twh_y"],
                "grid_import_twh_y": metrics["net_grid_import_twh_y"],
                "wag_generated_pj_y": metrics["wag_generation_pj_y"],
                "wag_to_processes_pj_y": process_wag_mwh * factor * PJ_PER_MWH,
                "wag_to_generator_pj_y": generator_wag_mwh * factor * PJ_PER_MWH,
                "wag_to_flexible_heat_pj_y": flex_wag_mwh * factor * PJ_PER_MWH,
                "wag_flare_pj_y": metrics["wag_flare_pj_y"],
                "named_ng_total_pj_y": values["represented_ng_pj_y"],
                "named_ng_relative_error": errors["represented_ng_pj_y"],
                "ng_generator_pj_y": metrics["generator_named_ng_pj_y"],
                "ng_fixed_bridge_pj_y": metrics["fixed_bridge_named_ng_pj_y"],
                "ng_flexible_heat_pj_y": metrics["flexible_bridge_named_ng_pj_y"],
                "coal_mt_y": coal_mt_y,
                "coal_relative_error": errors["coal_mt_y"],
                "first_order_co2_mt_y": first_order_total,
                "first_order_co2_relative_error": errors["first_order_co2_mt_y"],
                "generator_volume_cap_binding_hours": volume_binding_hours,
                "generator_electrical_cap_binding_hours": electrical_binding_hours,
                "no_export_binding_hours": no_export_binding_hours,
                "represented_procurement_cost_eur": objective_cost,
                "explicit_background_twh_y": candidate["explicit_background_twh_y"],
                "source_deviation_repair_activation": int(repair_active),
                "source_deviation_background_share_of_3p17": float(
                    candidate["explicit_background_twh_y"]
                )
                / 3.17,
                "empirical_annual_result": False,
                "selected_for_checkpoint4": False,
                "selection_reason": "pending_multi_family_selection",
            }
        )
        reported_mip_gap = audit.get("mip_gap")
        runtime_rows.append(
            {
                "candidate_id": case_id,
                "solver_name": audit.get("solver_name"),
                "solver_status": audit.get("solver_status"),
                "termination_condition": audit.get("termination_condition"),
                "mip_gap": 0.0 if reported_mip_gap is None else reported_mip_gap,
                "mip_gap_basis": (
                    "optimal_termination_no_numeric_gap_reported"
                    if reported_mip_gap is None
                    else "solver_reported_numeric_gap"
                ),
                "solver_runtime_seconds": audit.get("runtime_seconds"),
                "wall_runtime_seconds": wall_runtime,
                "variable_count": audit.get("variable_count"),
                "binary_count": audit.get("binary_count"),
                "constraint_count": audit.get("constraint_count"),
                "objective_type": audit.get("objective_type"),
                "primary_cost_objective_eur": objective_cost,
            }
        )
        for parameter, baseline, candidate_value, unit, movement_role in (
            ("repair_interface_active", 0, int(repair_active), "boolean", "governed_case_boundary"),
            (
                "explicit_background_electricity",
                0.0,
                candidate["explicit_background_twh_y"],
                "TWh/y",
                "only_numeric_candidate_movement",
            ),
        ):
            movement_rows.append(
                {
                    "candidate_id": case_id,
                    "parameter": parameter,
                    "baseline_value": baseline,
                    "candidate_value": candidate_value,
                    "unit": unit,
                    "movement_role": movement_role,
                    "within_frozen_contract": True,
                }
            )
        snapshots[case_id] = {
            "candidate": {
                **candidate,
                "execution_status": "solved_optimal",
                "solver_invoked": True,
            },
            "frozen_period": week,
            "target_multiplier": target_multiplier,
            "deadline_targets_t": deadline_targets,
            "progress_target_t": progress_target,
            "progress_lower_bound_t": progress_lower,
            "progress_upper_bound_t": progress_upper,
            "solver_required": "gurobi",
            "execution_status": "solved_optimal",
            "solver_invoked": True,
            "solver_status": audit.get("solver_status"),
            "termination_condition": audit.get("termination_condition"),
            "empirical_annual_result": False,
        }
        print(
            "checkpoint3_candidate_complete "
            f"candidate_id={case_id} "
            f"termination_condition={audit.get('termination_condition')} "
            f"wall_runtime_seconds={wall_runtime:.3f}",
            flush=True,
        )

    score_rows = score_and_select_checkpoint3_rows(score_rows)

    _write_csv(run_root / "candidate_scorecard.csv", score_rows)
    _write_csv(run_root / "parameter_movements.csv", movement_rows)
    _write_csv(run_root / "physical_guardrails.csv", guardrail_rows)
    _write_csv(run_root / "solver_runtime_metrics.csv", runtime_rows)
    snapshot_root = run_root / "candidate_configs"
    score_by_candidate = {
        str(row["candidate_id"]): row for row in score_rows
    }
    for case_id, payload in snapshots.items():
        score_row = score_by_candidate[case_id]
        payload["candidate"].update(
            {
                "candidate_classification": score_row[
                    "candidate_classification"
                ],
                "promotable_central_from_checkpoint3": False,
                "selected_for_checkpoint4": score_row[
                    "selected_for_checkpoint4"
                ],
            }
        )
        payload.update(
            {
                "candidate_classification": score_row[
                    "candidate_classification"
                ],
                "promotable_central_from_checkpoint3": False,
                "selected_for_checkpoint4": score_row[
                    "selected_for_checkpoint4"
                ],
            }
        )
        _write_json(snapshot_root / f"{case_id}.json", payload)
    input_manifest = {
        "run_id": config["run_id"],
        "checkpoint": 3,
        "config_path": str(config_path),
        "config_sha256": _sha256(config_path),
        "candidate_manifest_path": str(run_root / "candidate_manifest.csv"),
        "candidate_manifest_sha256": _sha256(run_root / "candidate_manifest.csv"),
        "development_week_contract_path": str(WEEK_CONTRACT_PATH),
        "development_week_contract_sha256": _sha256(WEEK_CONTRACT_PATH),
        "period_id": week["period_id"],
        "candidate_count": 5,
        "solver_family": "gurobi",
        "execution_authorized": True,
        "empirical_annual_result": False,
    }
    _write_json(run_root / "input_manifest.json", input_manifest)
    retained = [row["candidate_id"] for row in score_rows if row["selected_for_checkpoint4"]]
    state_path = run_root / "checkpoint_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        {
            "status": "checkpoint3_solved",
            "review_status": "checkpoint3_solved_review_correction_pending",
            "completed_checkpoints": [1, 2, 3],
            "rolling_optimization_executed": True,
            "solver_invoked": True,
            "dispatch_results_present": False,
            "score_results_present": True,
            "candidate_scorecard_present": True,
            "solver_runtime_metrics_present": True,
            "checkpoint3_reporting_correction_applied": True,
            "checkpoint3_candidate_count": 5,
            "checkpoint3_retained_candidates": retained,
            "gurobi_license_blocked": False,
            "checkpoint3_runtime_seconds": time.perf_counter() - execution_start,
            "caveat": "One 168-hour development week annualized for screening; not an empirical annual result.",
        }
    )
    _write_json(state_path, state)
    (run_root / "README.md").write_text(
        _checkpoint3_readme(score_rows, week), encoding="utf-8"
    )
    return {
        "candidate_scorecard": score_rows,
        "physical_guardrails": guardrail_rows,
        "solver_runtime_metrics": runtime_rows,
        "retained_candidates": retained,
        "period": week,
    }
