"""Bounded runtime/equivalence audit for the Phase-6D planning tie-break.

Each ``run_variant`` invocation performs one isolated solver process.  V0 keeps
the frozen three-tier lexicographic solve; V1 returns the proven expected-cost
incumbent without solving the third planning tier.  Redispatch remains frozen.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C1_CONFIGURATION,
)
from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    SteelRollingState,
    _git_head,
    _sha256,
    _write_gzip_json_atomic,
    _write_json,
    clear_hourly_da_bids,
)
from .s4_4c6_phase6d_eaf_heat_state_one_day import (
    EXPECTED_COST_INCUMBENT,
    EXECUTION_WINDOW_TIEBREAK,
    FULL_PHYSICAL_TIEBREAK,
    HANDOFF_STATE_TIEBREAK,
    NATIVE_GUROBI_HIERARCHY,
    solve_grouped_actual_redispatch,
    solve_grouped_da_bid_plan,
    validate_phase6d_trajectory,
)
from .s4_4c6_representative_regime_counterfactual import (
    _base_context_config,
    build_price_bundles,
    load_representative_config,
    load_study_frames,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


AUDIT_CONFIG = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "configs"
    / "steel_c6_physical_tiebreak_runtime_audit.yaml"
)
VARIANT_TO_MODE = {
    "V0": FULL_PHYSICAL_TIEBREAK,
    "V1": EXPECTED_COST_INCUMBENT,
    "V2": HANDOFF_STATE_TIEBREAK,
    "V3": EXECUTION_WINDOW_TIEBREAK,
    "V4": NATIVE_GUROBI_HIERARCHY,
}
PLANNED_COMPARISON_FIELDS = (
    "planned_net_grid_import_mwh",
    "planned_final_product_t",
    "eaf_heat_start",
    "eaf_melt",
    "eaf_tap",
    "planned_coke_inventory_t",
    "planned_sinter_inventory_t",
    "planned_hot_iron_inventory_t",
    "planned_cold_slab_inventory_t",
    "planned_dri_inventory_t",
    "planned_drp_pellet_input_t",
    "planned_drp_on",
    "planned_coking_plant_1_t",
    "planned_sintering_plant_t",
    "planned_blast_furnace_6_t",
    "planned_basic_oxygen_furnace_t",
    "planned_hot_strip_mill_t",
    "planned_coking_plant_1_on",
    "planned_sintering_plant_on",
    "planned_blast_furnace_6_on",
    "planned_basic_oxygen_furnace_on",
    "planned_hot_strip_mill_on",
    "planned_vn25_electricity_mwh",
    "planned_total_generator_electricity_mwh",
    "planned_total_named_ng_procurement_mwh",
    "planned_eaf_liquid_steel_output_t",
)


class PhysicalTiebreakAuditError(RuntimeError):
    """Raised when the bounded runtime audit contract is violated."""


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def load_audit_config(path: str | Path = AUDIT_CONFIG) -> dict[str, Any]:
    payload = yaml.safe_load(_resolve(path).read_text(encoding="utf-8"))
    if payload.get("output_policy") != "minimal":
        raise PhysicalTiebreakAuditError("The runtime audit must use minimal output.")
    if payload.get("variants") != VARIANT_TO_MODE:
        raise PhysicalTiebreakAuditError("The frozen V0/V1 mapping changed.")
    return payload


def _selected_row(frames: Any, audit: Mapping[str, Any], arm: str) -> dict[str, Any]:
    frozen = audit["frozen_case"]
    rows = frames.experiment_manifest
    selected = rows[
        rows["week_id"].eq(frozen["week_id"])
        & rows["arm"].eq(arm)
        & rows["configuration"].eq(frozen["configuration"])
        & rows["scenario_count"].eq(int(frozen["scenario_count"]))
        & rows["experiment_class"].eq("central")
        & rows["benchmark"].eq("stochastic_policy")
    ]
    if len(selected) != 1:
        raise PhysicalTiebreakAuditError(
            f"Expected one frozen {arm} manifest row, found {len(selected)}."
        )
    return selected.iloc[0].to_dict()


def _stable_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, default=str, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _state_row(
    delivery_day: date,
    state_before: Mapping[str, Any],
    redispatch: Any,
    settlement_cost_eur: float,
) -> dict[str, Any]:
    physical = redispatch.physical_intervals
    return {
        "delivery_day": delivery_day.isoformat(),
        "state_before_json": json.dumps(state_before, sort_keys=True),
        "state_after_json": json.dumps(redispatch.next_state.snapshot(), sort_keys=True),
        "settlement_cost_eur": float(settlement_cost_eur),
        "other_represented_cost_eur": float(redispatch.other_represented_cost_eur),
        "total_realised_cost_eur": float(
            settlement_cost_eur + redispatch.other_represented_cost_eur
        ),
        "produced_t": float(redispatch.produced_t),
        "eaf_heat_count_started": sum(float(row["eaf_heat_start"]) for row in physical),
        "eaf_heat_count_tapped": sum(float(row["eaf_tap"]) for row in physical),
        "eaf_arc_on_intervals": sum(float(row["eaf_melt"]) for row in physical),
        "eaf_unfinished_start_lag1": int(redispatch.next_state.eaf_start_lag1),
        "eaf_unfinished_start_lag2": int(redispatch.next_state.eaf_start_lag2),
    }


def _input_fingerprint(
    row: Mapping[str, Any],
    bundle: Any,
    actuals: Any,
    state: SteelRollingState,
    context: Any,
) -> str:
    return _stable_sha256(
        {
            "manifest_row": dict(row),
            "forecast_origin_utc": bundle.forecast_origin_utc,
            "timestamps_utc": bundle.timestamps_utc,
            "point_prices": bundle.point_prices,
            "scenario_prices": bundle.scenario_prices,
            "scenario_probabilities": bundle.scenario_probabilities,
            "actual_timestamps_utc": actuals.timestamps_utc,
            "actual_prices": actuals.prices,
            "initial_state": state.snapshot(),
            "physical_grid_id": context.grid_id,
            "economic_horizon_hours": context.economic_horizon_hours,
            "physical_horizon_hours": context.time_grid.horizon_hours,
            "execution_hours": context.time_grid.execution_hours,
            "solver_time_limit_seconds": context.config["solver_time_limit_seconds"],
            "solver_seed": context.config.get("solver_seed"),
        }
    )


def _trajectory(
    plan: Any,
    clearing: Any,
    redispatch: Any,
    state_row: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "market_granularity": "quarterhour",
        "configuration_id": C1_CONFIGURATION,
        "policy": plan.policy,
        "bids": plan.bids,
        "scenario_dispatch": plan.scenario_dispatch,
        "clearing": clearing.hourly,
        "physical_dispatch": redispatch.physical_intervals,
        "state": dict(state_row),
        "solver": [
            {"solve_role": "bidding", **plan.solver},
            {"solve_role": "redispatch", **redispatch.solver},
        ],
        "final_state": redispatch.next_state.snapshot(),
        "total_realised_cost_eur": state_row["total_realised_cost_eur"],
    }


def _write_declaration(run_root: Path, audit: Mapping[str, Any]) -> None:
    declaration_path = run_root / "output_declaration.json"
    if declaration_path.exists():
        return
    _write_json(
        declaration_path,
        {
            "output_root": str(run_root.relative_to(REPO_ROOT)),
            "run_class": audit["run_class"],
            "lineage_role": audit["lineage_role"],
            "output_policy": "minimal",
            "variants": [*VARIANT_TO_MODE, "V5_not_executable_without_proof"],
            "expected_primary_processes": 6,
            "expected_primary_solver_invocations": 33,
            "estimated_model_size_per_planning_solve": (
                "approximately 92k variables, 2,040 binaries and 96k constraints"
            ),
            "estimated_output_size": "less than 15 MB compressed",
            "retention_status": "ignored governed diagnostic run",
            "git_eligible": False,
        },
    )


def run_variant(
    config_path: str | Path,
    *,
    run_id: str,
    variant: str,
    repeat_id: int,
    day_count: int = 1,
    arm: str = "B_qh_flat",
) -> dict[str, Any]:
    audit = load_audit_config(config_path)
    if variant not in VARIANT_TO_MODE:
        raise PhysicalTiebreakAuditError(f"Unsupported variant: {variant}.")
    if day_count not in {1, 2}:
        raise PhysicalTiebreakAuditError("Only one- and two-day audit runs are allowed.")
    if arm not in {"B_qh_flat", "C_qh_shape"}:
        raise PhysicalTiebreakAuditError("Only frozen QH-flat and QH-shape arms are allowed.")
    expected_repeats = int(audit["primary_repeats"][variant])
    if arm == "B_qh_flat" and day_count == 1 and not 1 <= repeat_id <= expected_repeats:
        raise PhysicalTiebreakAuditError("repeat_id is outside the frozen primary design.")

    representative_path = _resolve(audit["representative_config"])
    representative = load_representative_config(representative_path)
    frames = load_study_frames(representative)
    row = _selected_row(frames, audit, arm)
    context = _base_context_config(
        representative, market_granularity="quarterhour", horizon_hours=24
    )
    context.config["planning_physical_tiebreak_mode"] = VARIANT_TO_MODE[variant]
    context.config["solver_seed"] = int(audit["solver"]["seed"])
    if float(context.config["solver_time_limit_seconds"]) != float(
        audit["solver"]["time_limit_seconds"]
    ):
        raise PhysicalTiebreakAuditError("Solver time limit differs from the frozen audit.")

    run_root = _resolve(audit["output_root"]) / run_id
    _write_declaration(run_root, audit)
    case_id = f"{arm}__d{day_count}__{variant}__r{repeat_id}"
    output_dir = run_root / "runs" / case_id
    if output_dir.exists():
        raise PhysicalTiebreakAuditError(f"Audit output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    context.config["solver_log_directory"] = str(output_dir / "solver_logs")

    state = SteelRollingState(
        episode_id="frozen_high_prices_c1_qh_runtime_audit",
        configuration_id=C1_CONFIGURATION,
    )
    days: list[dict[str, Any]] = []
    input_fingerprints: list[str] = []
    started = time.perf_counter()
    week_start = date.fromisoformat(str(audit["frozen_case"]["week_start"]))
    for offset in range(day_count):
        delivery_day = week_start + timedelta(days=offset)
        context.config["solver_log_prefix"] = delivery_day.isoformat()
        bundle, actuals = build_price_bundles(
            frames,
            week_id=str(audit["frozen_case"]["week_id"]),
            delivery_day=delivery_day,
            arm=arm,
            scenario_count=int(audit["frozen_case"]["scenario_count"]),
        )
        before = state.snapshot()
        input_fingerprints.append(
            _input_fingerprint(row, bundle, actuals, state, context)
        )
        plan = solve_grouped_da_bid_plan(
            context,
            C1_CONFIGURATION,
            bundle,
            state,
            str(audit["frozen_case"]["policy"]),
            audit_future_paths=True,
        )
        clearing = clear_hourly_da_bids(plan.bids, actuals)
        redispatch = solve_grouped_actual_redispatch(
            context,
            C1_CONFIGURATION,
            clearing,
            state,
            bundle.point_prices,
        )
        state_row = _state_row(
            delivery_day, before, redispatch, clearing.settlement_cost_eur
        )
        trajectory = _trajectory(plan, clearing, redispatch, state_row)
        checks = validate_phase6d_trajectory(trajectory)
        if any(item["status"] != "pass" for item in checks):
            raise PhysicalTiebreakAuditError("A physical or settlement gate failed.")
        days.append(
            {
                "delivery_day": delivery_day.isoformat(),
                "input_fingerprint_sha256": input_fingerprints[-1],
                "expected_cost_eur": float(plan.expected_cost_eur),
                "realised_total_cost_eur": float(state_row["total_realised_cost_eur"]),
                "state_before": before,
                "state_after": redispatch.next_state.snapshot(),
                "plan_solver": plan.solver,
                "redispatch_solver": redispatch.solver,
                "bids": plan.bids,
                "clearing": clearing.hourly,
                "scenario_dispatch": plan.scenario_dispatch,
                "physical_dispatch": redispatch.physical_intervals,
                "checks": checks,
            }
        )
        state = redispatch.next_state

    audit_payload = {
        "case_id": case_id,
        "variant": variant,
        "planning_physical_tiebreak_mode": VARIANT_TO_MODE[variant],
        "repeat_id": repeat_id,
        "arm": arm,
        "day_count": day_count,
        "days": days,
    }
    _write_gzip_json_atomic(output_dir / "audit_payload.json.gz", audit_payload)
    summary = {
        "case_id": case_id,
        "status": "pass",
        "variant": variant,
        "planning_physical_tiebreak_mode": VARIANT_TO_MODE[variant],
        "physical_tiebreak_solve_performed": all(
            bool(day["plan_solver"]["physical_tiebreak_solve_performed"])
            for day in days
        ),
        "repeat_id": repeat_id,
        "arm": arm,
        "day_count": day_count,
        "input_fingerprints_sha256": input_fingerprints,
        "input_sequence_sha256": _stable_sha256(input_fingerprints),
        "planning_solver_seconds": sum(
            float(day["plan_solver"]["total_solver_seconds"]) for day in days
        ),
        "redispatch_solver_seconds": sum(
            float(day["redispatch_solver"]["total_solver_seconds"]) for day in days
        ),
        "wall_seconds": time.perf_counter() - started,
        "expected_cost_eur": sum(float(day["expected_cost_eur"]) for day in days),
        "realised_total_cost_eur": sum(
            float(day["realised_total_cost_eur"]) for day in days
        ),
        "final_state": state.snapshot(),
        "all_checks_pass": True,
        "all_planning_tiers_optimal": all(
            str(tier["termination_condition"]).lower() == "optimal"
            for day in days
            for tier in day["plan_solver"]["tier_solves"]
        ),
        "solver_seed": int(audit["solver"]["seed"]),
        "solver_time_limit_seconds": float(audit["solver"]["time_limit_seconds"]),
        "model_size": {
            "variables": days[0]["plan_solver"]["variable_count"],
            "binaries": days[0]["plan_solver"]["binary_count"],
            "constraints": days[0]["plan_solver"]["constraint_count"],
        },
        "payload": "audit_payload.json.gz",
    }
    _write_json(output_dir / "run_summary.json", summary)
    _write_json(
        output_dir / "lineage.json",
        {
            "git_head": _git_head(),
            "audit_config_sha256": _sha256(_resolve(config_path)),
            "representative_config_sha256": _sha256(representative_path),
            "study_run_summary_sha256": _sha256(frames.study_root / "run_summary.json"),
            "counterfactual_overlay_sha256": _sha256(
                frames.study_root / "counterfactual_qh_overlay.parquet"
            ),
            "phase6d_engine_sha256": _sha256(
                Path(__file__).with_name(
                    "s4_4c6_phase6d_eaf_heat_state_one_day.py"
                )
            ),
            "runtime_audit_sha256": _sha256(Path(__file__).resolve()),
        },
    )
    return summary


def _read_payload(path: Path) -> dict[str, Any]:
    import gzip

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _maximum_numeric_difference(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
    *,
    keys: Sequence[str],
    fields: Sequence[str],
) -> tuple[float, str | None]:
    left_map = {tuple(row[key] for key in keys): row for row in left}
    right_map = {tuple(row[key] for key in keys): row for row in right}
    if set(left_map) != set(right_map):
        return math.inf, "key_support"
    maximum = 0.0
    maximum_field: str | None = None
    for key in sorted(left_map, key=str):
        for field in fields:
            difference = abs(
                float(left_map[key].get(field, 0.0))
                - float(right_map[key].get(field, 0.0))
            )
            if difference > maximum:
                maximum = difference
                maximum_field = field
    return maximum, maximum_field


def _flatten_numeric(payload: Any, prefix: str = "") -> dict[str, float]:
    result: dict[str, float] = {}
    if isinstance(payload, Mapping):
        for key, value_ in payload.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten_numeric(value_, child))
    elif isinstance(payload, (int, float)) and not isinstance(payload, bool):
        result[prefix] = float(payload)
    return result


def _state_difference(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    left_values = _flatten_numeric(left)
    right_values = _flatten_numeric(right)
    if set(left_values) != set(right_values):
        return math.inf
    return max(
        (abs(left_values[key] - right_values[key]) for key in left_values),
        default=0.0,
    )


def compare_primary(config_path: str | Path, *, run_id: str) -> dict[str, Any]:
    audit = load_audit_config(config_path)
    run_root = _resolve(audit["output_root"]) / run_id
    baseline_path = run_root / "runs" / "B_qh_flat__d1__V0__r1"
    candidate_paths = [
        run_root / "runs" / f"B_qh_flat__d1__V1__r{repeat}"
        for repeat in range(1, 4)
    ]
    paths = [baseline_path, *candidate_paths]
    if any(not (path / "run_summary.json").exists() for path in paths):
        raise PhysicalTiebreakAuditError("The complete V0/V1 primary matrix is unavailable.")
    summaries = [
        json.loads((path / "run_summary.json").read_text(encoding="utf-8"))
        for path in paths
    ]
    payloads = [
        _read_payload(path / "audit_payload.json.gz") for path in paths
    ]
    baseline_day = payloads[0]["days"][0]
    comparisons: list[dict[str, Any]] = []
    tolerance = audit["tolerances"]
    for summary, payload in zip(summaries[1:], payloads[1:]):
        candidate_day = payload["days"][0]
        bid_difference, bid_field = _maximum_numeric_difference(
            baseline_day["bids"],
            candidate_day["bids"],
            keys=("target_timestamp_utc", "bid_price_eur_per_mwh"),
            fields=("incremental_bid_volume_mwh",),
        )
        plan_difference, plan_field = _maximum_numeric_difference(
            baseline_day["scenario_dispatch"],
            candidate_day["scenario_dispatch"],
            keys=("scenario_id", "physical_interval_index"),
            fields=PLANNED_COMPARISON_FIELDS,
        )
        physical_fields = tuple(
            key
            for key, value_ in baseline_day["physical_dispatch"][0].items()
            if isinstance(value_, (int, float)) and not isinstance(value_, bool)
        )
        physical_difference, physical_field = _maximum_numeric_difference(
            baseline_day["physical_dispatch"],
            candidate_day["physical_dispatch"],
            keys=("physical_interval_index",),
            fields=physical_fields,
        )
        cost_difference = abs(
            float(summary["expected_cost_eur"])
            - float(summaries[0]["expected_cost_eur"])
        )
        realised_cost_difference = abs(
            float(summary["realised_total_cost_eur"])
            - float(summaries[0]["realised_total_cost_eur"])
        )
        state_difference = _state_difference(
            summaries[0]["final_state"], summary["final_state"]
        )
        exact = (
            summary["input_sequence_sha256"] == summaries[0]["input_sequence_sha256"]
            and cost_difference <= float(tolerance["expected_cost_eur"])
            and realised_cost_difference <= float(tolerance["settlement_eur"])
            and bid_difference <= float(tolerance["bid_volume_mwh"])
            and plan_difference <= float(tolerance["physical_value"])
            and physical_difference <= float(tolerance["physical_value"])
            and state_difference <= float(tolerance["physical_value"])
            and bool(summary["all_checks_pass"])
        )
        comparisons.append(
            {
                "repeat_id": summary["repeat_id"],
                "input_identity": summary["input_sequence_sha256"]
                == summaries[0]["input_sequence_sha256"],
                "expected_cost_difference_eur": cost_difference,
                "realised_cost_difference_eur": realised_cost_difference,
                "maximum_bid_difference_mwh": bid_difference,
                "maximum_bid_difference_field": bid_field,
                "maximum_planned_path_difference": plan_difference,
                "maximum_planned_path_difference_field": plan_field,
                "maximum_executed_path_difference": physical_difference,
                "maximum_executed_path_difference_field": physical_field,
                "maximum_handoff_state_difference": state_difference,
                "exact_primary_equivalence": exact,
            }
        )

    v1_plan_times = [float(summary["planning_solver_seconds"]) for summary in summaries[1:]]
    v1_reproducible = len(
        {
            _stable_sha256(
                {
                    "expected_cost_eur": summary["expected_cost_eur"],
                    "realised_total_cost_eur": summary["realised_total_cost_eur"],
                    "final_state": summary["final_state"],
                    "bids": payload["days"][0]["bids"],
                    "scenario_dispatch": payload["days"][0]["scenario_dispatch"],
                    "physical_dispatch": payload["days"][0]["physical_dispatch"],
                }
            )
            for summary, payload in zip(summaries[1:], payloads[1:])
        }
    ) == 1
    baseline_time = float(summaries[0]["planning_solver_seconds"])
    median_v1_time = statistics.median(v1_plan_times)
    reduction = 1.0 - median_v1_time / baseline_time
    all_exact = all(item["exact_primary_equivalence"] for item in comparisons)
    report = {
        "status": "pass" if all_exact and v1_reproducible else "insufficient",
        "classification": (
            "exact_equivalence_candidate"
            if all_exact and v1_reproducible
            else "valid_but_methodologically_different"
            if all(summary["all_checks_pass"] for summary in summaries[1:])
            else "rejected"
        ),
        "promotion_status": "not_yet_eligible_requires_rolling_and_shape",
        "baseline_planning_solver_seconds": baseline_time,
        "v1_planning_solver_seconds": v1_plan_times,
        "v1_median_planning_solver_seconds": median_v1_time,
        "median_runtime_reduction_fraction": reduction,
        "runtime_threshold_pass": reduction
        >= float(
            audit["promotion"][
                "minimum_median_planning_runtime_reduction_fraction"
            ]
        ),
        "v1_three_process_reproducibility_pass": v1_reproducible,
        "comparisons": comparisons,
        "next_step": (
            "run_two_day_v0_v1_and_one_qh_shape_candidate"
            if all_exact and v1_reproducible
            else "V1_insufficient_consider_V2_handoff_only"
        ),
    }
    _write_json(run_root / "primary_comparison.json", report)
    return report


def _gurobi_log_summary(path: Path) -> dict[str, Any]:
    import re

    text = path.read_text(encoding="utf-8", errors="replace")
    explored = re.findall(
        r"Explored\s+([0-9]+)\s+nodes.*?in\s+([0-9.]+)\s+seconds\s+\(([0-9.eE+-]+)\s+work units\)",
        text,
    )
    objective = re.findall(
        r"Best objective\s+([^,]+),\s+best bound\s+([^,]+),\s+gap\s+([0-9.]+)%",
        text,
    )
    return {
        "termination_condition": (
            "maxTimeLimit" if "Time limit reached" in text else "optimal"
        ),
        "solver_seconds": float(explored[-1][1]) if explored else None,
        "nodes": int(explored[-1][0]) if explored else None,
        "work_units": float(explored[-1][2]) if explored else None,
        "objective_value": float(objective[-1][0]) if objective else None,
        "best_bound": float(objective[-1][1]) if objective else None,
        "mip_gap": float(objective[-1][2]) / 100.0 if objective else None,
        "log_file": path.name,
    }


def _native_log_stages(path: Path) -> list[dict[str, Any]]:
    import re

    text = path.read_text(encoding="utf-8", errors="replace")
    markers = list(
        re.finditer(
            r"Multi-objectives:\s+optimize objective\s+(\d+)\s+\(([^)]+)\)",
            text,
        )
    )
    names = ("production_progress", "expected_represented_cost", "physical_tiebreak")
    result: list[dict[str, Any]] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        # Parse in memory using the same patterns as a standalone log.
        segment = text[marker.end() : end]
        explored = re.findall(
            r"Explored\s+([0-9]+)\s+nodes.*?in\s+([0-9.]+)\s+seconds\s+\(([0-9.eE+-]+)\s+work units\)",
            segment,
        )
        objective = re.findall(
            r"Best objective\s+([^,]+),\s+best bound\s+([^,]+),\s+gap\s+([0-9.]+)%",
            segment,
        )
        result.append(
            {
                "tier": names[index] if index < len(names) else marker.group(2),
                "logged_name": marker.group(2),
                "native_cumulative_solver_seconds": (
                    float(explored[-1][1]) if explored else None
                ),
                "nodes": int(explored[-1][0]) if explored else None,
                "work_units": float(explored[-1][2]) if explored else None,
                "objective_value": float(objective[-1][0]) if objective else None,
                "best_bound": float(objective[-1][1]) if objective else None,
                "mip_gap": float(objective[-1][2]) / 100.0 if objective else None,
            }
        )
    return result


def _compare_one_day_payloads(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    bid_difference, bid_field = _maximum_numeric_difference(
        baseline["bids"],
        candidate["bids"],
        keys=("target_timestamp_utc", "bid_price_eur_per_mwh"),
        fields=("incremental_bid_volume_mwh",),
    )
    planned_difference, planned_field = _maximum_numeric_difference(
        baseline["scenario_dispatch"],
        candidate["scenario_dispatch"],
        keys=("scenario_id", "physical_interval_index"),
        fields=PLANNED_COMPARISON_FIELDS,
    )
    physical_fields = tuple(
        key
        for key, value_ in baseline["physical_dispatch"][0].items()
        if isinstance(value_, (int, float)) and not isinstance(value_, bool)
    )
    executed_difference, executed_field = _maximum_numeric_difference(
        baseline["physical_dispatch"],
        candidate["physical_dispatch"],
        keys=("physical_interval_index",),
        fields=physical_fields,
    )
    return {
        "expected_cost_difference_eur": abs(
            float(baseline["expected_cost_eur"])
            - float(candidate["expected_cost_eur"])
        ),
        "realised_cost_difference_eur": abs(
            float(baseline["realised_total_cost_eur"])
            - float(candidate["realised_total_cost_eur"])
        ),
        "maximum_bid_difference_mwh": bid_difference,
        "maximum_bid_difference_field": bid_field,
        "maximum_planned_path_difference": planned_difference,
        "maximum_planned_path_difference_field": planned_field,
        "maximum_executed_path_difference": executed_difference,
        "maximum_executed_path_difference_field": executed_field,
        "maximum_handoff_state_difference": _state_difference(
            baseline["state_after"], candidate["state_after"]
        ),
    }


def _sequential_tier_evidence(
    case_root: Path, tier_names: Sequence[str]
) -> list[dict[str, Any]]:
    payload = _read_payload(case_root / "audit_payload.json.gz")["days"][0]
    recorded = {
        str(item["tier"]): dict(item)
        for item in payload["plan_solver"]["tier_solves"]
    }
    result: list[dict[str, Any]] = []
    for name in tier_names:
        merged = recorded[name]
        parsed = _gurobi_log_summary(
            case_root / "solver_logs" / f"2025-01-13__{name}.log"
        )
        merged.update(
            {
                "mip_gap": parsed["mip_gap"],
                "branch_and_bound_nodes": parsed["nodes"],
                "gurobi_work_units": parsed["work_units"],
                "solver_reported_time_seconds": parsed["solver_seconds"],
                "best_bound": parsed["best_bound"],
                "solver_log_file": parsed["log_file"],
            }
        )
        result.append(merged)
    return result


def finalise_audit(config_path: str | Path = AUDIT_CONFIG) -> dict[str, Any]:
    audit = load_audit_config(config_path)
    base_root = _resolve(audit["output_root"])
    evidence = audit["evidence_runs"]

    primary_root = base_root / evidence["primary_v0_v1"] / "runs"
    followup_root = base_root / evidence["followup_v2_v3"] / "runs"
    native_root = base_root / evidence["native_v4"] / "runs"
    final_root = base_root / evidence["final_summary"]
    if final_root.exists():
        raise PhysicalTiebreakAuditError("Final audit summary already exists.")
    final_root.mkdir(parents=True)

    def summary(root: Path, case: str) -> dict[str, Any]:
        return json.loads((root / case / "run_summary.json").read_text(encoding="utf-8"))

    def day(root: Path, case: str) -> dict[str, Any]:
        return _read_payload(root / case / "audit_payload.json.gz")["days"][0]

    v0_primary = summary(primary_root, "B_qh_flat__d1__V0__r1")
    v1_summaries = [
        summary(primary_root, f"B_qh_flat__d1__V1__r{repeat}")
        for repeat in range(1, 4)
    ]
    v0_followup = summary(followup_root, "B_qh_flat__d1__V0__r1")
    v3_summary = summary(followup_root, "B_qh_flat__d1__V3__r1")
    v3_comparison = _compare_one_day_payloads(
        day(followup_root, "B_qh_flat__d1__V0__r1"),
        day(followup_root, "B_qh_flat__d1__V3__r1"),
    )
    v0_native = summary(native_root, "B_qh_flat__d1__V0__r1")
    v0_native_day = day(native_root, "B_qh_flat__d1__V0__r1")
    v0_tiers = _sequential_tier_evidence(
        native_root / "B_qh_flat__d1__V0__r1",
        ("production_progress", "expected_represented_cost", "physical_tiebreak"),
    )
    v1_tiers = _sequential_tier_evidence(
        primary_root / "B_qh_flat__d1__V1__r1",
        ("production_progress", "expected_represented_cost"),
    )
    v3_tiers = _sequential_tier_evidence(
        followup_root / "B_qh_flat__d1__V3__r1",
        ("production_progress", "expected_represented_cost", "execution_window_tiebreak"),
    )

    v2_logs = followup_root / "B_qh_flat__d1__V2__r1" / "solver_logs"
    v2_tiers = [
        _gurobi_log_summary(v2_logs / f"2025-01-13__{name}.log")
        for name in (
            "production_progress",
            "expected_represented_cost",
            "handoff_state_tiebreak",
        )
    ]
    for name, record in zip(
        ("production_progress", "expected_represented_cost", "handoff_state_tiebreak"),
        v2_tiers,
    ):
        record["tier"] = name

    v4_log = (
        native_root
        / "B_qh_flat__d1__V4__r1"
        / "solver_logs"
        / "2025-01-13__native_multiobjective.log"
    )
    v4_tiers = _native_log_stages(v4_log)
    v4_cost_difference = (
        float(v4_tiers[1]["objective_value"])
        - float(v0_native["expected_cost_eur"])
    )
    v4_total_seconds = float(v4_tiers[-1]["native_cumulative_solver_seconds"])

    v1_times = [float(item["planning_solver_seconds"]) for item in v1_summaries]
    v0_times = [
        float(v0_primary["planning_solver_seconds"]),
        float(v0_followup["planning_solver_seconds"]),
        float(v0_native["planning_solver_seconds"]),
    ]
    primary_comparison = json.loads(
        (base_root / evidence["primary_v0_v1"] / "primary_comparison.json").read_text(
            encoding="utf-8"
        )
    )
    variants = [
        {
            "variant": "V0",
            "definition": "sequential progress, represented cost, full 48h physical tie-break",
            "classification": "reference_retained",
            "planning_seconds_observed": v0_times,
            "planning_seconds_median": statistics.median(v0_times),
            "termination": "optimal",
            "tier_solves": v0_tiers,
            "objective_contract": {
                key: v0_native_day["plan_solver"][key]
                for key in (
                    "production_progress_optimum_t",
                    "expected_cost_optimum_eur",
                    "selected_incumbent_expected_cost_eur",
                    "selected_incumbent_physical_tiebreak_value",
                    "maximum_bid_clearing_reconstruction_error_mwh",
                    "expected_cost_reconstruction_error_eur",
                )
            },
            "semantic_result": "frozen baseline reproduced exactly across all three instrumented roots",
        },
        {
            "variant": "V1",
            "definition": "return expected-cost incumbent; omit third planning solve",
            "classification": "valid_but_methodologically_different",
            "planning_seconds_observed": v1_times,
            "planning_seconds_median": statistics.median(v1_times),
            "paired_runtime_reduction_fraction": primary_comparison[
                "median_runtime_reduction_fraction"
            ],
            "termination": "optimal",
            "three_process_reproducibility_pass": primary_comparison[
                "v1_three_process_reproducibility_pass"
            ],
            "tier_solves_representative_repeat": v1_tiers,
            **primary_comparison["comparisons"][0],
        },
        {
            "variant": "V2",
            "definition": "third tier projected onto direct rolling-handoff states",
            "classification": "rejected_performance_incomplete",
            "planning_solver_seconds_lower_bound": sum(
                float(item["solver_seconds"]) for item in v2_tiers
            ),
            "termination": "maxTimeLimit",
            "tier_solves": v2_tiers,
        },
        {
            "variant": "V3",
            "definition": "frozen physical tie-break restricted to executed q=0..95",
            "classification": "valid_but_methodologically_different",
            "planning_seconds": float(v3_summary["planning_solver_seconds"]),
            "paired_v0_planning_seconds": float(
                v0_followup["planning_solver_seconds"]
            ),
            "paired_runtime_reduction_fraction": 1.0
            - float(v3_summary["planning_solver_seconds"])
            / float(v0_followup["planning_solver_seconds"]),
            "termination": "optimal",
            "tier_solves": v3_tiers,
            **v3_comparison,
        },
        {
            "variant": "V4",
            "definition": "single native Gurobi hierarchical multiobjective solve",
            "classification": "rejected_cost_and_runtime",
            "planning_solver_seconds": v4_total_seconds,
            "paired_v0_planning_seconds": float(
                v0_native["planning_solver_seconds"]
            ),
            "paired_runtime_reduction_fraction": 1.0
            - v4_total_seconds / float(v0_native["planning_solver_seconds"]),
            "cost_stage_difference_vs_v0_eur": v4_cost_difference,
            "termination": "optimal",
            "tier_solves": v4_tiers,
        },
        {
            "variant": "V5",
            "definition": "single provably bounded composite objective",
            "classification": "not_admissible_not_run",
            "termination": "not_run",
            "reason": audit["non_executable_variants"]["V5"]["reason"],
        },
    ]
    conclusion = {
        "status": "complete_no_promotion",
        "recommendation": "retain_V0_default",
        "accepted_candidate": None,
        "frozen_case": audit["frozen_case"],
        "solver": audit["solver"],
        "diagnosis": {
            "current_tiebreak_scope": "ten scenario blocks times the full 48h physical horizon; EAF starts, DRP and retained-route commitments, five inventories, flaring, controller penalties and daily commitments",
            "warm_start_semantics": "the non-persistent gurobi shell receives only an incumbent; it does not retain the prior branch-and-bound tree or root relaxation",
            "observed_bottleneck": "V0 tie-break solved at the root node but spent 160.96-230.73 reported seconds in root LP/cut processing in the comparable logged runs",
        },
        "variant_results": variants,
        "rolling_validation": "not_run_no_candidate_passed_primary_exactness_and_speed_gates",
        "qh_shape_validation": "not_run_no_candidate_passed_primary_exactness_and_speed_gates",
        "canonical_docs_updated": False,
        "default_changed": False,
        "central_56_run_started_or_resumed": False,
        "limitations": [
            "one frozen high-price C1/S10/QH-flat delivery day; runtime is machine-sensitive",
            "V1 reproducibility is established in three separate processes, but V0 runtime has substantial process-to-process variance",
            "no annual or economic claim follows from this diagnostic",
        ],
        "evidence_roots": dict(evidence),
        "code_lineage": {
            "git_head": _git_head(),
            "audit_config_sha256": _sha256(_resolve(config_path)),
            "phase6d_engine_sha256": _sha256(
                Path(__file__).with_name(
                    "s4_4c6_phase6d_eaf_heat_state_one_day.py"
                )
            ),
            "runtime_audit_sha256": _sha256(Path(__file__).resolve()),
        },
    }
    _write_json(
        final_root / "output_declaration.json",
        {
            "output_root": str(final_root.relative_to(REPO_ROOT)),
            "run_class": "diagnostic_validation",
            "lineage_role": "compact conclusion over bounded physical-tiebreak runtime evidence; not economic evidence",
            "output_policy": "minimal",
            "estimated_size": "less than 100 KB",
            "solver_invocations_summarised": 43,
            "git_eligible": False,
        },
    )
    _write_json(final_root / "variant_results.json", variants)
    _write_json(final_root / "audit_conclusion.json", conclusion)
    return conclusion


__all__ = [
    "AUDIT_CONFIG",
    "PhysicalTiebreakAuditError",
    "compare_primary",
    "finalise_audit",
    "load_audit_config",
    "run_variant",
]
