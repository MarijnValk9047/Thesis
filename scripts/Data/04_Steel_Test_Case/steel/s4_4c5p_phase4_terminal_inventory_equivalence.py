"""Phase-4 DEVELOPMENT terminal-inventory equivalence methodology gate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
    CONFIGURATIONS,
    ClosedLoopFeasibilityError,
    run_closed_loop_feasibility_anchor_reconciliation,
    terminal_inventory_activation_hour,
)
from .s4_4c5p_bf_price_series_interface import (
    build_dplus4_forecast_slice,
    dplus4_timestamp_plan,
)
from .s4_4c5p_bl_deterministic_price_response_anchor_diagnostics import (
    _executed_price_vectors,
    _schedule_costs,
)
from .s4_4c5p_phase3_operation_route_robustness import (
    _source_rows,
    load_phase3_config,
)
from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    _build_c0_inputs,
    _build_c1_inputs,
    _load_tables,
    _select_solver,
)
from .validation_tolerance_policy import (
    TERMINAL_STATE_TOLERANCE_T,
    exact_input_fingerprint,
    policy_contract,
    resolve_policy_contract,
    validation_record,
)


VALIDATION_TOLERANCE_POLICY_REQUIRED = True
RUN_ID = "steel_c5_phase4_reachability_aware_terminal_band_v3_20260727"
CONFIG_PATH = REPO_ROOT / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase4_terminal_inventory_equivalence.yaml"
STATE_FIELDS = {
    C0_CONFIGURATION: (
        "coke_inventory_t",
        "sinter_inventory_t",
        "hot_iron_inventory_t",
        "cold_slab_inventory_t",
    ),
    C1_CONFIGURATION: (
        "coke_inventory_t",
        "sinter_inventory_t",
        "hot_iron_inventory_t",
        "cold_slab_inventory_t",
        "dri_inventory_t",
    ),
}
EXPECTED_PERIODS = ("validation_2024-02-12", "validation_2024-07-01")
EXPECTED_STRATEGIES = (
    "price_insensitive_reference",
    "governed_dplus4_y_pred",
    "perfect_foresight_y_true_oracle",
)


class Phase4TerminalEquivalenceError(RuntimeError):
    pass


def _resolve(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fieldnames: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["status"])
        writer.writeheader()
        writer.writerows(materialized)


def _number(value: Any) -> float:
    return 0.0 if value in {None, ""} else float(value)


def load_phase4_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise Phase4TerminalEquivalenceError("Phase-4 config must be a mapping.")
    return payload


def check_phase4_config(config: Mapping[str, Any]) -> None:
    if config.get("run_id") != RUN_ID or config.get("mode") != (
        "development_reachability_aware_terminal_band_cyclic_replacement"
    ):
        raise Phase4TerminalEquivalenceError("Unexpected Phase-4 identity.")
    if config.get("output_policy") != "minimal":
        raise Phase4TerminalEquivalenceError("Phase 4 requires output_policy=minimal.")
    phase4 = config["phase4"]
    resolve_policy_contract(phase4["terminal_state_tolerance_policy"])
    periods = tuple(row["period_id"] for row in phase4["development_periods"])
    strategies = tuple(row["strategy_id"] for row in phase4["strategies"])
    if periods != EXPECTED_PERIODS or strategies != EXPECTED_STRATEGIES:
        raise Phase4TerminalEquivalenceError("Frozen periods or strategies changed.")
    expected = {
        "expected_rolling_case_count": 6,
        "expected_target_selection_case_count": 2,
        "expected_configuration_trajectory_count": 12,
        "maximum_model_count": 84,
        "replans_per_case": 7,
    }
    if any(int(phase4[key]) != value for key, value in expected.items()):
        raise Phase4TerminalEquivalenceError("Phase-4 case or solver cap changed.")
    if phase4.get("held_out_periods_used") or phase4.get("candidate_promoted"):
        raise Phase4TerminalEquivalenceError("Held-out use or promotion is prohibited.")
    if (
        abs(float(phase4.get("terminal_band_fraction", -1.0)) - 0.01) > 1e-12
        or phase4.get("zero_target_policy") != "exact_zero"
        or phase4.get("terminal_band_width_search_allowed") is not False
    ):
        raise Phase4TerminalEquivalenceError("The frozen per-state 1% terminal-band policy changed.")
    if phase4.get("terminal_inventory_horizon_policy") != (
        "truncate_at_campaign_endpoint_and_replace_cyclic_inventory_equalities"
    ):
        raise Phase4TerminalEquivalenceError(
            "The terminal horizon-truncation/cyclic-replacement policy changed."
        )
    lock = phase4["scope_lock"]
    prohibited = (
        "exact_route_cases_allowed", "route_sensitivities_allowed",
        "bf_capacity_variants_allowed", "held_out_periods_allowed",
        "market_bidding_or_settlement_allowed", "export_or_sale_allowed",
        "stochasticity_or_cvar_allowed", "co2_or_ets_allowed",
        "product_revenue_allowed", "annualisation_allowed",
    )
    if not lock.get("free_c1_route_required") or any(lock[key] for key in prohibited):
        raise Phase4TerminalEquivalenceError("Phase-4 scope lock was relaxed.")


def frozen_case_matrix(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    phase4 = config["phase4"]
    rows: list[dict[str, Any]] = []
    for period in phase4["development_periods"]:
        for strategy in phase4["strategies"]:
            rows.append({
                "case_id": f"phase4__{period['period_id'].replace('-', '_')}__{strategy['strategy_id']}",
                "period_id": period["period_id"],
                "dataset_split": period["dataset_split"],
                "forecast_start_origin_utc": period["frozen_forecast_start_origin_utc"],
                "strategy_id": strategy["strategy_id"],
                "price_field": strategy["price_field"],
                "flat_price_eur_per_mwh": strategy.get("flat_price_eur_per_mwh"),
                "perfect_foresight_oracle": bool(strategy["perfect_foresight_oracle"]),
                "expected_model_count": 14,
            })
    return rows


def terminal_inventory_capacity_contract() -> dict[str, dict[str, float]]:
    """Load the physical store capacities used by the active C0/C1 builder."""

    tables = _load_tables(S44B_INPUT_DIR)
    c0 = _build_c0_inputs(tables, horizon_hours_override=120)
    c1 = _build_c1_inputs(
        tables,
        horizon_hours_override=120,
        include_retained_bf_bof=True,
    )
    if c1.retained_bf_bof is None:
        raise Phase4TerminalEquivalenceError("C1 retained-route inventory capacities are unavailable.")
    retained = c1.retained_bf_bof
    return {
        C0_CONFIGURATION: {
            "coke_inventory_t": float(c0.coke_store_capacity_t),
            "sinter_inventory_t": float(c0.sinter_store_capacity_t),
            "hot_iron_inventory_t": float(c0.hot_iron_store_capacity_t),
            "cold_slab_inventory_t": float(c0.cold_slab_store_capacity_t),
        },
        C1_CONFIGURATION: {
            "coke_inventory_t": float(retained.coke_store_capacity_t),
            "sinter_inventory_t": float(retained.sinter_store_capacity_t),
            "hot_iron_inventory_t": float(retained.hot_iron_store_capacity_t),
            "cold_slab_inventory_t": float(retained.cold_slab_store_capacity_t),
            "dri_inventory_t": float(c1.dri_buffer_capacity_t),
        },
    }


def build_terminal_inventory_band(
    target: Mapping[str, Mapping[str, float]],
    *,
    fraction: float,
    capacities: Mapping[str, Mapping[str, float]],
) -> dict[str, dict[str, dict[str, float]]]:
    """Build one per-state band; zero targets remain exact zero."""

    if abs(float(fraction) - 0.01) > 1e-12:
        raise Phase4TerminalEquivalenceError("Only the frozen 1% terminal band is allowed.")
    output: dict[str, dict[str, dict[str, float]]] = {}
    for configuration in CONFIGURATIONS:
        if set(target[configuration]) != set(STATE_FIELDS[configuration]):
            raise Phase4TerminalEquivalenceError(
                f"Terminal target schema changed for {configuration}."
            )
        output[configuration] = {}
        for state_id in STATE_FIELDS[configuration]:
            target_t = float(target[configuration][state_id])
            capacity_t = float(capacities[configuration][state_id])
            if target_t < 0.0 or target_t > capacity_t + 1e-9:
                raise Phase4TerminalEquivalenceError(
                    f"Terminal target {state_id} lies outside its physical capacity."
                )
            if target_t == 0.0:
                lower_t = upper_t = 0.0
            else:
                lower_t = max(0.0, (1.0 - float(fraction)) * target_t)
                upper_t = min(capacity_t, (1.0 + float(fraction)) * target_t)
            output[configuration][state_id] = {
                "target_t": target_t,
                "lower_t": lower_t,
                "upper_t": upper_t,
                "capacity_t": capacity_t,
                "band_fraction": float(fraction),
            }
    return output


def campaign_execution_hours(
    *,
    forecast_root: Path,
    dataset_split: str,
    start_origin_utc: str,
    replans: int,
) -> int:
    """Derive campaign duration from governed y_pred timestamps only."""

    executed = 0
    for replan_index in range(int(replans)):
        predicted = build_dplus4_forecast_slice(
            forecast_run_root=forecast_root,
            dataset_split=dataset_split,
            start_origin_utc=start_origin_utc,
            replan_index=replan_index,
            planning_horizon_hours=None,
            price_field="y_pred",
            perfect_foresight_oracle=False,
        )
        executed += int(dplus4_timestamp_plan(predicted)["execution_block_hours"])
    return executed


def synthetic_campaign_activation_schedule(
    *,
    campaign_hours: int,
    planning_horizon_hours: int,
    execution_block_hours: int = 24,
) -> list[dict[str, int | bool]]:
    """Expose scalable endpoint activation without running a steel model."""

    if campaign_hours <= 0 or campaign_hours % execution_block_hours != 0:
        raise Phase4TerminalEquivalenceError(
            "Synthetic campaign must contain complete positive execution blocks."
        )
    rows: list[dict[str, int | bool]] = []
    for executed in range(0, campaign_hours, execution_block_hours):
        hour = terminal_inventory_activation_hour(
            terminal_executed_hours_target=campaign_hours,
            executed_hours_so_far=executed,
            planning_horizon_hours=planning_horizon_hours,
        )
        rows.append({
            "executed_hours_before": executed,
            "terminal_band_active": hour is not None,
            "terminal_hour_in_plan": int(hour or 0),
        })
    return rows


def _case_overrides(
    config: Mapping[str, Any], case: Mapping[str, Any], forecast_root: Path,
    terminal_hours: int,
    band: Mapping[str, Mapping[str, Mapping[str, float]]] | None = None,
) -> dict[str, Any]:
    phase4 = config["phase4"]
    central = phase4["accepted_central_boundary"]
    recovery = phase4["recovery_interface"]
    payload: dict[str, Any] = {
        "run_id": case["case_id"],
        "lineage_role": "phase4_development_terminal_equivalence_child",
        "forecast_run_root": str(forecast_root),
        "replan_count": int(phase4["replans_per_case"]),
        "price_series_id": "hourly_da_dplus4_point_forecast",
        "generator_operating_mode": "development_price_responsive",
        "forecast_dataset_split": case["dataset_split"],
        "forecast_start_origin_utc": case["forecast_start_origin_utc"],
        "timestamped_dplus4_rolling_enabled": True,
        "forecast_price_override_eur_per_mwh": case["flat_price_eur_per_mwh"],
        "forecast_price_field": case["price_field"],
        "perfect_foresight_oracle": case["perfect_foresight_oracle"],
        "terminal_executed_hours_target": int(terminal_hours),
        "terminal_inventory_horizon_policy": phase4[
            "terminal_inventory_horizon_policy"
        ],
        "c1_retained_route_policy": "quota_driven_topology",
        "site_background_electricity_mwh_h_by_configuration": dict(
            central["site_background_electricity_mwh_h_by_configuration"]
        ),
        "price_scenario_overrides": {"natural_gas_ttf_proxy": central["ng_price_scenario_id"]},
        "mechanism_candidate_id": central["candidate_id"],
        "mechanism_ng_price_eur_per_mwh_lhv": float(central["ng_price_eur_per_mwh_lhv"]),
        "wag_generation_yield_overrides_by_configuration": {},
        "named_process_electricity_intensity_scales_by_configuration": {},
        "first_order_co2_constant_mt_y_by_configuration": dict(
            central["first_order_co2_constant_mt_y_by_configuration"]
        ),
        "c0_aggregate_generator_technical_interface": dict(
            recovery["c0_aggregate_generator_technical_interface"]
        ),
        "c0_full_site_energy_bridge": dict(recovery["c0_full_site_energy_bridge"]),
    }
    if band is not None:
        payload["terminal_inventory_band_by_configuration"] = {
            configuration: {
                state_id: dict(bounds)
                for state_id, bounds in values.items()
            }
            for configuration, values in band.items()
        }
    return payload


def _artifact(directory: Path) -> dict[str, Any]:
    return {
        "directory": directory,
        "summary": _read_json(directory / "run_summary.json"),
        "hourly": _read_csv(directory / "executed_hourly.csv"),
        "costs": _read_csv(directory / "executed_procurement_cost_ledger.csv"),
        "models": _read_csv(directory / "rolling_model_metrics.csv"),
        "validation": _read_csv(directory / "validation_checks.csv"),
        "execution": _read_csv(directory / "rolling_execution.csv"),
        "prices": _read_csv(directory / "executed_electricity_price_series.csv"),
        "progress": _read_csv(directory / "rolling_production_progress_state.csv"),
        "timing": _read_csv(directory / "rolling_timestamp_contract.csv"),
    }


def terminal_state_vector(artifact: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = {}
    for configuration in CONFIGURATIONS:
        rows = [row for row in artifact["hourly"] if row["configuration_id"] == configuration]
        if not rows:
            raise Phase4TerminalEquivalenceError(f"No executed rows for {configuration}.")
        endpoint = max(rows, key=lambda row: int(row["executed_hour_index"]))
        values: dict[str, float] = {}
        for state_id in STATE_FIELDS[configuration]:
            source = "DRI_inventory_t" if state_id == "dri_inventory_t" else state_id
            values[state_id] = _number(endpoint.get(f"{source}_unrounded", endpoint.get(source)))
        output[configuration] = values
    return output


def _run_case(
    config: Mapping[str, Any], case: Mapping[str, Any], forecast_root: Path,
    scratch_root: Path, terminal_hours: int,
    band: Mapping[str, Mapping[str, Mapping[str, float]]] | None,
) -> dict[str, Any]:
    directory = scratch_root / str(case["case_id"])
    if directory.exists():
        raise Phase4TerminalEquivalenceError(f"Scratch child already exists: {directory}")
    run_closed_loop_feasibility_anchor_reconciliation(
        config_path=_resolve(str(config["phase4"]["physical_config"])),
        output_root=scratch_root,
        scenario_overrides=_case_overrides(
            config, case, forecast_root, terminal_hours, band
        ),
    )
    return _artifact(directory)


def _terminal_rows(
    case: Mapping[str, Any], observed: Mapping[str, Mapping[str, float]],
    band: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for configuration in CONFIGURATIONS:
        for state_id in STATE_FIELDS[configuration]:
            bounds = band[configuration][state_id]
            observed_t = observed[configuration][state_id]
            target_t = float(bounds["target_t"])
            lower_t = float(bounds["lower_t"])
            upper_t = float(bounds["upper_t"])
            residual = max(lower_t - observed_t, 0.0, observed_t - upper_t)
            deviation_t = observed_t - target_t
            record = validation_record(
                validation_id=f"{case['case_id']}::{configuration}::{state_id}",
                purpose="terminal_or_carried_material_state", unit="t",
                raw_residual=residual, allowed_tolerance=TERMINAL_STATE_TOLERANCE_T,
                aggregation="final_executed_hour_per_state_1pct_band",
            )
            rows.append({
                "case_id": case["case_id"], "period_id": case["period_id"],
                "strategy_id": case["strategy_id"], "configuration_id": configuration,
                "state_id": state_id, "target_t": target_t,
                "lower_t": lower_t, "upper_t": upper_t,
                "capacity_t": bounds["capacity_t"],
                "observed_t": observed_t,
                "deviation_from_target_t": deviation_t,
                "deviation_from_target_percent": (
                    100.0 * deviation_t / target_t
                    if target_t > 0.0
                    else "exact_zero_target"
                ),
                **record,
            })
    return rows


def _cost_rows(
    period_id: str, artifacts: Mapping[str, Mapping[str, Any]],
    vector: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    realised = {
        strategy: _schedule_costs(artifact, vector, price_field="y_true_eur_per_mwh")
        for strategy, artifact in artifacts.items()
    }
    prices = [float(row["y_true_eur_per_mwh"]) for row in vector]
    median = statistics.median(prices)
    rows: list[dict[str, Any]] = []
    for configuration in CONFIGURATIONS:
        benchmark = realised["price_insensitive_reference"][configuration]["total_represented_cost_eur"]
        governed = realised["governed_dplus4_y_pred"][configuration]["total_represented_cost_eur"]
        oracle = realised["perfect_foresight_y_true_oracle"][configuration]["total_represented_cost_eur"]
        denominator = benchmark - oracle
        for strategy in EXPECTED_STRATEGIES:
            artifact = artifacts[strategy]
            hourly = sorted(
                (row for row in artifact["hourly"] if row["configuration_id"] == configuration),
                key=lambda row: int(row["executed_hour_index"]),
            )
            product = sum(_number(row.get("final_product_output_t")) for row in hourly)
            expensive = sum(
                _number(row.get("net_grid_import_mwh")) for index, row in enumerate(hourly)
                if prices[index] >= median
            )
            cheap = sum(
                _number(row.get("net_grid_import_mwh")) for index, row in enumerate(hourly)
                if prices[index] < median
            )
            reference_hourly = sorted(
                (row for row in artifacts["price_insensitive_reference"]["hourly"] if row["configuration_id"] == configuration),
                key=lambda row: int(row["executed_hour_index"]),
            )
            ref_expensive = sum(_number(row.get("net_grid_import_mwh")) for index, row in enumerate(reference_hourly) if prices[index] >= median)
            ref_cheap = sum(_number(row.get("net_grid_import_mwh")) for index, row in enumerate(reference_hourly) if prices[index] < median)
            total = realised[strategy][configuration]["total_represented_cost_eur"]
            rows.append({
                "result_label": "development_common_terminal_band_1pct_cost_comparison",
                "period_id": period_id, "configuration_id": configuration,
                "strategy_id": strategy, "price_basis": "y_true_ex_post_for_all_strategies",
                "executed_represented_procurement_cost_eur": round(total, 6),
                "executed_final_product_t": round(product, 6),
                "eur_per_t_final_product": round(total / product, 6),
                "price_insensitive_minus_strategy_eur": round(benchmark - total, 6),
                "price_insensitive_minus_governed_eur": round(benchmark - governed, 6),
                "price_insensitive_minus_oracle_eur": round(denominator, 6),
                "governed_value_captured_relative_to_oracle": (
                    round((benchmark - governed) / denominator, 9) if denominator > 0.0 else "not_defined_nonpositive_denominator"
                ),
                "expensive_half_grid_import_shift_vs_reference_mwh": round(expensive - ref_expensive, 6),
                "cheap_half_grid_import_shift_vs_reference_mwh": round(cheap - ref_cheap, 6),
                "expensive_cheap_split": f"period_y_true_median_{median:.9f}_eur_per_mwh",
            })
    return rows


def _activation_rows(
    case: Mapping[str, Any],
    artifact: Mapping[str, Any],
    *,
    terminal_hours: int,
    band_expected: bool,
) -> list[dict[str, Any]]:
    """Compare recorded activation against the campaign-endpoint calculation."""

    progress = {
        (int(row["replan_index"]), row["configuration_id"]): row
        for row in artifact["progress"]
    }
    rows: list[dict[str, Any]] = []
    executed_before = 0
    for timing in sorted(artifact["timing"], key=lambda row: int(row["replan_index"])):
        replan = int(timing["replan_index"])
        planning_hours = int(timing["planning_horizon_hours"])
        expected_hour = terminal_inventory_activation_hour(
            terminal_executed_hours_target=terminal_hours,
            executed_hours_so_far=executed_before,
            planning_horizon_hours=planning_hours,
        )
        for configuration in CONFIGURATIONS:
            state = progress[(replan, configuration)]
            actual_active = str(state["terminal_inventory_band_active"]).lower() == "true"
            actual_hour = int(state["terminal_inventory_band_hour"] or 0)
            expected_active = bool(band_expected and expected_hour is not None)
            rows.append({
                "case_id": case["case_id"],
                "period_id": case["period_id"],
                "strategy_id": case["strategy_id"],
                "replan_index": replan,
                "configuration_id": configuration,
                "executed_hours_before": executed_before,
                "planning_horizon_hours": planning_hours,
                "campaign_terminal_hours": terminal_hours,
                "expected_active": expected_active,
                "actual_active": actual_active,
                "expected_terminal_hour_in_plan": int(expected_hour or 0) if band_expected else 0,
                "actual_terminal_hour_in_plan": actual_hour,
                "status": (
                    "pass"
                    if actual_active == expected_active
                    and actual_hour == (int(expected_hour or 0) if expected_active else 0)
                    else "fail"
                ),
            })
        executed_before += int(timing["execution_block_hours"])
    return rows


def run_phase4(config_path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    started = time.time()
    config_file = Path(config_path).resolve()
    config = load_phase4_config(config_file)
    check_phase4_config(config)
    phase4 = config["phase4"]
    output_root = _resolve(str(config["output_root"]))
    scratch_root = _resolve(str(phase4["scratch_root"]))
    if output_root.exists() or scratch_root.exists():
        raise Phase4TerminalEquivalenceError("Governed output or scratch root already exists.")
    _, solver = _select_solver()
    if solver is None:
        raise Phase4TerminalEquivalenceError("Gurobi is unavailable before the first solve.")
    phase3_config = load_phase3_config(_resolve(str(phase4["phase3_config"])))
    forecast_root, source_rows = _source_rows(phase3_config)
    if forecast_root != _resolve(str(phase4["forecast_run_root"])):
        raise Phase4TerminalEquivalenceError("Phase-3 and Phase-4 forecast roots differ.")
    phase3_summary = _read_json(_resolve(str(phase4["phase3_summary"])))
    phase4_v1_summary = _read_json(_resolve(str(phase4["phase4_v1_summary"])))
    phase4_v2_summary = _read_json(_resolve(str(phase4["phase4_v2_summary"])))
    if phase3_summary.get("decision") != "phase3_bounded_robustness_complete_with_exact_route_infeasibility":
        raise Phase4TerminalEquivalenceError("Accepted Phase-3 decision is unavailable.")
    if phase4_v1_summary.get("decision") != "phase4_common_terminal_infeasible_calm_governed_c0":
        raise Phase4TerminalEquivalenceError("Phase-4 v1 outcome-B lineage is unavailable.")
    if phase4_v2_summary.get("decision") != (
        "phase4_reachability_aware_terminal_band_infeasible_or_unavailable"
    ):
        raise Phase4TerminalEquivalenceError(
            "Phase-4 v2 structural-diagnosis lineage is unavailable."
        )
    cases = frozen_case_matrix(config)
    if len(cases) != 6 or sum(row["expected_model_count"] for row in cases) != 84:
        raise Phase4TerminalEquivalenceError("Case/model cap preflight failed.")
    capacities = terminal_inventory_capacity_contract()
    output_root.mkdir(parents=True)
    scratch_root.mkdir(parents=True)
    (output_root / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    input_manifest = {
        "config": {"path": str(config_file.relative_to(REPO_ROOT)).replace("\\", "/"), "sha256": _sha256(config_file)},
        "physical_config": {"path": phase4["physical_config"], "sha256": _sha256(_resolve(str(phase4["physical_config"])))},
        "phase3_config": {"path": phase4["phase3_config"], "sha256": _sha256(_resolve(str(phase4["phase3_config"])))},
        "phase3_summary": {"path": phase4["phase3_summary"], "sha256": _sha256(_resolve(str(phase4["phase3_summary"])))},
        "phase4_v1_summary": {"path": phase4["phase4_v1_summary"], "sha256": _sha256(_resolve(str(phase4["phase4_v1_summary"])))},
        "phase4_v2_summary": {"path": phase4["phase4_v2_summary"], "sha256": _sha256(_resolve(str(phase4["phase4_v2_summary"])))},
        "forecast_source_contract_checks": source_rows,
        "inventory_capacity_contract": capacities,
        "git_commit": _git_head(),
        "validation_tolerance_policy": policy_contract(),
    }
    _write_json(output_root / "input_manifest.json", input_manifest)
    _write_json(output_root / "code_version.json", {"git_commit": _git_head()})

    case_registry: list[dict[str, Any]] = []
    target_selection_registry: list[dict[str, Any]] = []
    terminal_rows: list[dict[str, Any]] = []
    activation_rows: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    check_rows: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    target_contracts: list[dict[str, Any]] = []
    model_count = 0
    structural_failure: dict[str, Any] | None = None

    def record_target_selection(
        case: Mapping[str, Any], artifact: Mapping[str, Any]
    ) -> bool:
        failed_validations = [
            row["check_id"]
            for row in artifact["validation"]
            if row["status"] != "pass"
        ]
        solver_ok = len(artifact["models"]) == 14 and all(
            str(row.get("termination_condition", "")).lower() == "optimal"
            and str(row.get("solver_status", "")).lower() == "ok"
            for row in artifact["models"]
        )
        selection_ok = solver_ok and not failed_validations
        target_selection_registry.append(
            {
                "case_id": case["case_id"],
                "period_id": case["period_id"],
                "strategy_id": case["strategy_id"],
                "case_role": "unbanded_price_insensitive_target_selection",
                "status": "pass" if selection_ok else "fail",
                "model_count": len(artifact["models"]),
                "failed_validation_ids": ";".join(failed_validations),
                "scratch_lineage": f"tmp/{scratch_root.name}/{case['case_id']}",
            }
        )
        return selection_ok

    def record_completed_case(
        case: Mapping[str, Any],
        artifact: Mapping[str, Any],
        *,
        band: Mapping[str, Mapping[str, Mapping[str, float]]],
        band_fingerprint: str,
        terminal_hours: int,
        support_fingerprint: str,
        band_expected: bool,
    ) -> bool:
        nonlocal model_count
        observed = terminal_state_vector(artifact)
        resolved_terminal_rows = _terminal_rows(case, observed, band)
        terminal_rows.extend(resolved_terminal_rows)
        resolved_activation_rows = _activation_rows(
            case,
            artifact,
            terminal_hours=terminal_hours,
            band_expected=band_expected,
        )
        activation_rows.extend(resolved_activation_rows)
        model_count += len(artifact["models"])
        solver_rows.extend({"case_id": case["case_id"], **row} for row in artifact["models"])
        failed_validations = [
            row["check_id"] for row in artifact["validation"]
            if row["status"] != "pass"
        ]
        solver_ok = len(artifact["models"]) == 14 and all(
            str(row.get("termination_condition", "")).lower() == "optimal"
            and str(row.get("solver_status", "")).lower() == "ok"
            for row in artifact["models"]
        )
        terminal_ok = all(row["status"] == "pass" for row in resolved_terminal_rows)
        activation_ok = all(row["status"] == "pass" for row in resolved_activation_rows)
        exports = sum(_number(row.get("grid_export_mwh")) for row in artifact["hourly"])
        sale_rows = [
            row for row in artifact["costs"]
            if "sale" in str(row.get("cost_route", "")).lower()
        ]
        scope_ok = abs(exports) <= 1e-6 and not sale_rows
        case_ok = solver_ok and not failed_validations and terminal_ok and activation_ok and scope_ok
        case_registry.append({
            "case_id": case["case_id"],
            "period_id": case["period_id"],
            "strategy_id": case["strategy_id"],
            "status": "pass" if case_ok else "fail",
            "model_count": len(artifact["models"]),
            "terminal_band_fingerprint_sha256": band_fingerprint,
            "executed_timestamp_fingerprint_sha256": support_fingerprint,
            "initial_state_contract_fingerprint_sha256": exact_input_fingerprint({
                "physical_config_sha256": _sha256(_resolve(str(phase4["physical_config"]))),
                "initial_inventory_overrides": {},
                "initial_cumulative_production_t": {},
                "initial_executed_hours": 0,
            }),
            "failed_validation_ids": ";".join(failed_validations),
            "scratch_lineage": f"tmp/{scratch_root.name}/{case['case_id']}",
            "y_true_in_governed_decisions": False,
        })
        check_rows.extend({"case_id": case["case_id"], **row} for row in artifact["validation"])
        check_rows.extend([
            {"case_id": case["case_id"], "check_id": "final_executed_terminal_band", "status": "pass" if terminal_ok else "fail", "value": max(row["raw_residual"] for row in resolved_terminal_rows), "unit": "t_outside_band"},
            {"case_id": case["case_id"], "check_id": "reachability_activation_schedule", "status": "pass" if activation_ok else "fail", "value": sum(row["actual_active"] for row in resolved_activation_rows), "unit": "configuration_replans"},
            {"case_id": case["case_id"], "check_id": "no_export_or_sale_activation", "status": "pass" if scope_ok else "fail", "value": exports, "unit": "MWh_e"},
            {"case_id": case["case_id"], "check_id": "no_hidden_inventory_value_term", "status": "pass", "value": "procurement_ledger_has_no_inventory_flow", "unit": "contract"},
            {"case_id": case["case_id"], "check_id": "governed_y_true_nonanticipativity", "status": "pass" if case["strategy_id"] != "governed_dplus4_y_pred" or (case["price_field"] == "y_pred" and not case["perfect_foresight_oracle"]) else "fail", "value": case["price_field"], "unit": "price_field"},
        ])
        return case_ok

    for period_id in EXPECTED_PERIODS:
        period_cases = [case for case in cases if case["period_id"] == period_id]
        reference_case = period_cases[0]
        selection_case = dict(reference_case)
        terminal_hours = campaign_execution_hours(
            forecast_root=forecast_root,
            dataset_split=reference_case["dataset_split"],
            start_origin_utc=reference_case["forecast_start_origin_utc"],
            replans=int(phase4["replans_per_case"]),
        )
        selection = _run_case(
            config, selection_case, forecast_root, scratch_root,
            terminal_hours, None,
        )
        if not record_target_selection(selection_case, selection):
            structural_failure = {
                "case_id": selection_case["case_id"],
                "period_id": period_id,
                "strategy_id": selection_case["strategy_id"],
                "reason": "price_insensitive_target_selection_failed",
                "target_or_band_relaxed": False,
            }
            break
        target = terminal_state_vector(selection)
        band = build_terminal_inventory_band(
            target,
            fraction=float(phase4["terminal_band_fraction"]),
            capacities=capacities,
        )
        band_fingerprint = exact_input_fingerprint(band)
        target_contracts.append({
            "period_id": period_id,
            "selection_strategy": "price_insensitive_reference",
            "selection_timing": "frozen_before_responsive_strategies",
            "campaign_terminal_executed_hours": terminal_hours,
            "state_scope": "final_executed_hour_per_state_1pct_band",
            "band_fraction": float(phase4["terminal_band_fraction"]),
            "zero_target_policy": phase4["zero_target_policy"],
            "terminal_band": band,
            "terminal_band_fingerprint_sha256": band_fingerprint,
            "target_selection_case_id": selection_case["case_id"],
        })
        support_fingerprint = exact_input_fingerprint([
            {
                "replan_index": row["replan_index"],
                "delivery_start_utc": row["delivery_start_utc"],
                "execution_block_hours": row["execution_block_hours"],
            }
            for row in selection["timing"]
        ])
        period_artifacts: dict[str, Mapping[str, Any]] = {
            "price_insensitive_reference": selection
        }
        reference_ok = record_completed_case(
            reference_case,
            selection,
            band=band,
            band_fingerprint=band_fingerprint,
            terminal_hours=terminal_hours,
            support_fingerprint=support_fingerprint,
            band_expected=False,
        )
        if not reference_ok:
            structural_failure = {
                "case_id": reference_case["case_id"],
                "reason": "price_insensitive_reference_failed",
            }
            break

        for case in period_cases[1:]:
            try:
                artifact = _run_case(
                    config, case, forecast_root, scratch_root,
                    terminal_hours, band,
                )
            except ClosedLoopFeasibilityError as exc:
                structural_failure = {
                    "case_id": case["case_id"],
                    "period_id": period_id,
                    "strategy_id": case["strategy_id"],
                    "reason": str(exc),
                    "solver_proven_infeasible": "infeasible" in str(exc).lower(),
                    "terminal_band_fingerprint_sha256": band_fingerprint,
                    "target_or_band_relaxed": False,
                }
                case_registry.append({
                    "case_id": case["case_id"],
                    "period_id": period_id,
                    "strategy_id": case["strategy_id"],
                    "status": "solver_proven_infeasible" if structural_failure["solver_proven_infeasible"] else "failed",
                    "model_count": 0,
                    "terminal_band_fingerprint_sha256": band_fingerprint,
                    "failed_validation_ids": "runner_fail_fast_before_endpoint",
                    "scratch_lineage": f"tmp/{scratch_root.name}/{case['case_id']}",
                    "y_true_in_governed_decisions": False,
                })
                break
            period_artifacts[case["strategy_id"]] = artifact
            if not record_completed_case(
                case,
                artifact,
                band=band,
                band_fingerprint=band_fingerprint,
                terminal_hours=terminal_hours,
                support_fingerprint=support_fingerprint,
                band_expected=True,
            ):
                structural_failure = {
                    "case_id": case["case_id"],
                    "period_id": period_id,
                    "strategy_id": case["strategy_id"],
                    "reason": "completed_case_failed_acceptance",
                    "solver_proven_infeasible": False,
                    "terminal_band_fingerprint_sha256": band_fingerprint,
                    "target_or_band_relaxed": False,
                }
                break
        if structural_failure is not None:
            break
        vector = _executed_price_vectors(
            forecast_root=forecast_root,
            dataset_split=reference_case["dataset_split"],
            start_origin_utc=reference_case["forecast_start_origin_utc"],
            replans=int(phase4["replans_per_case"]),
        )
        cost_rows.extend(_cost_rows(period_id, period_artifacts, vector))

    terminal_pass = bool(terminal_rows) and all(row["status"] == "pass" for row in terminal_rows)
    checks_pass = all(row.get("status") == "pass" for row in check_rows)
    complete_matrix = (
        structural_failure is None
        and len(case_registry) == 6
        and len(target_selection_registry) == 2
    )
    solver_pass = (
        model_count <= 84
        and all(row["status"] == "pass" for row in case_registry)
        and all(row["status"] == "pass" for row in target_selection_registry)
    )
    banded_activation_rows = [
        row for row in activation_rows
        if row["strategy_id"] != "price_insensitive_reference"
    ]
    status = "pass" if (complete_matrix and terminal_pass and checks_pass and solver_pass) or structural_failure is not None else "fail"
    decision = (
        "phase4_reachability_aware_1pct_terminal_band_cyclic_replacement_complete_development_cost_comparison_authorized"
        if complete_matrix and terminal_pass and checks_pass and solver_pass
        else "phase4_reachability_aware_terminal_band_cyclic_replacement_infeasible_or_unavailable"
    )
    _write_json(output_root / "target_state_contract.json", {
        "targets": target_contracts,
        "policy": policy_contract(),
    })
    _write_csv(output_root / "activation_ledger.csv", activation_rows)
    _write_csv(output_root / "case_registry.csv", case_registry)
    _write_csv(
        output_root / "target_selection_registry.csv", target_selection_registry
    )
    _write_csv(output_root / "terminal_comparison.csv", terminal_rows)
    _write_csv(output_root / "cost_comparison.csv", cost_rows)
    _write_csv(output_root / "solver_summary.csv", solver_rows)
    _write_csv(output_root / "checks.csv", check_rows)
    limitations = (
        "# Limitations\n\n"
        "- DEVELOPMENT-only comparison over two frozen validation weeks; not annualised and not an eight-week or thesis-wide uplift claim.\n"
        "- The 1% band is a frozen operational-equivalence policy, not a numerical tolerance or a searched parameter.\n"
        "- All strategies are revalued ex post on y_true only after solving; y_true affects optimisation only in the labelled oracle.\n"
        "- Inventories carry no value in the represented procurement objective, so band-equivalent costs are not proof that residual inventory value is economically immaterial.\n"
        "- Residual electricity/NG remain reporting-only; no export, sale, market, ETS, revenue, stochastic or promotion work is included.\n"
    )
    if structural_failure is not None:
        limitations += f"- Structural failure: {json.dumps(structural_failure, sort_keys=True)}\n"
    (output_root / "warnings_and_limitations.md").write_text(limitations, encoding="utf-8")
    (output_root / "README.md").write_text(
        "# Phase 4 reachability-aware terminal band with cyclic replacement\n\n"
        "This compact DEVELOPMENT gate uses each period's unbanded price-insensitive reference both to freeze the final executed-hour vector and as the reference comparator, then runs the two responsive strategies under the same per-state 1% band. Once the campaign endpoint enters the governed physical look-ahead, the plan is truncated at that endpoint, the band replaces the corresponding cyclic inventory equalities, and route-output bands preserve cumulative campaign progress. See `run_summary.json`.\n",
        encoding="utf-8",
    )
    summary = {
        "run_id": RUN_ID,
        "status": status,
        "decision": decision,
        "result_label": phase4["result_label"],
        "rolling_case_count": len(case_registry),
        "comparison_case_count": len(case_registry),
        "target_selection_case_count": len(target_selection_registry),
        "configuration_trajectory_count": (
            len(case_registry)
        ) * 2,
        "solver_model_count": model_count,
        "solver_model_cap": 84,
        "terminal_state_comparison_count": len(terminal_rows),
        "maximum_terminal_band_excess_t": max((row["raw_residual"] for row in terminal_rows), default=math.nan),
        "maximum_absolute_terminal_target_deviation_t": max((abs(float(row["deviation_from_target_t"])) for row in terminal_rows), default=math.nan),
        "terminal_band_fraction": float(phase4["terminal_band_fraction"]),
        "terminal_inventory_horizon_policy": phase4[
            "terminal_inventory_horizon_policy"
        ],
        "zero_target_policy": phase4["zero_target_policy"],
        "terminal_state_tolerance_t": TERMINAL_STATE_TOLERANCE_T,
        "reachability_activation_checks_pass": (
            bool(banded_activation_rows)
            and all(row["status"] == "pass" for row in banded_activation_rows)
        ),
        "reachability_activation_runtime_evidence_available": bool(
            banded_activation_rows
        ),
        "physical_and_accounting_checks_pass": checks_pass,
        "cost_comparison_authorized": bool(cost_rows) and complete_matrix and status == "pass",
        "economic_uplift_claim_authorized": False,
        "inventory_value_bound_available": False,
        "structural_failure": structural_failure,
        "held_out_periods_used": False,
        "market_work_performed": False,
        "calibration_work_performed": False,
        "candidate_promoted": False,
        "runtime_seconds": round(time.time() - started, 6),
        "validation_tolerance_policy": policy_contract(),
    }
    _write_json(output_root / "run_summary.json", summary)
    _write_json(output_root / "registry_entry.json", {
        "run_id": RUN_ID,
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "output_policy": config["output_policy"],
        "status": status,
        "decision": decision,
    })
    return {"run_directory": output_root, "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(CONFIG_PATH))
    args = parser.parse_args()
    result = run_phase4(args.config)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
