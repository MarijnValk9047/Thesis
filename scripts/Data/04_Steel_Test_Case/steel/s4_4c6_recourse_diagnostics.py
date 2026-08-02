"""Bounded diagnostics for the synthetic S0 C1 DA-recourse infeasibility.

This module is deliberately diagnostic-only.  It reuses the frozen physical
model, bid grid, S10/S30 scenario artifacts and held-out synthetic actual path.
It does not add imbalance settlement, emergency import, robust bids, changed
physics or any final-regime observation to the canonical experiment.
"""

from __future__ import annotations

import csv
from datetime import date
import gzip
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence

import gurobipy as gp
import numpy as np
import pandas as pd
import yaml
from pyomo.environ import (
    Constraint,
    NonNegativeReals,
    Objective,
    Set,
    Var,
    minimize,
    value,
)

from .model import collect_model_stats
from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C1_CONFIGURATION,
)
from .s4_4c6_behavioural_validation import (
    _base_context_config,
    _final_periods,
    _load_shape_library,
    _payload_sha256,
    _resolve,
    _sha256,
    build_synthetic_bundles,
    load_behavioural_config,
)
from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    STEEL_BID_GRID,
    SteelBidPlan,
    SteelRollingState,
    clear_hourly_da_bids,
)
from .s4_4c6_phase6d_eaf_heat_state_one_day import (
    Phase6DError,
    Phase6DPerformanceIncomplete,
    _build_physical_model,
    _physical_group_size,
    _solve_optimal,
    _solver_for_phase6d,
    canonical_bid_volumes_from_scenario_requirements,
    solve_grouped_da_bid_plan,
)
from .s4_4c6_representative_regime_counterfactual import (
    load_representative_config,
    load_study_frames,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RECOURSE_DIAGNOSTIC_CONFIG = Path(
    "scripts/Data/04_Steel_Test_Case/configs/steel_c6_recourse_diagnostics.yaml"
)
PLAN_CACHE_NAMES = {10: "plan_s10.json.gz", 30: "plan_s30.json.gz"}
STATIC_OUTPUTS = (
    "output_declaration.json",
    "resolved_config.yaml",
    "input_manifest.json",
    "code_version.json",
    "static_contract_checks.csv",
    "scenario_support.csv",
    "run_summary.json",
    "warnings_and_limitations.md",
)


class RecourseDiagnosticError(RuntimeError):
    """Raised when the bounded recourse diagnostic contract is violated."""


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fieldnames: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["status"])
        writer.writeheader()
        writer.writerows(materialized)


def _write_gzip_json(path: Path, payload: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, sort_keys=True, default=str, separators=(",", ":"))
        handle.write("\n")
    temporary.replace(path)


def _read_gzip_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def load_recourse_diagnostic_config(
    path: str | Path = RECOURSE_DIAGNOSTIC_CONFIG,
) -> dict[str, Any]:
    config_path = _resolve(path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise RecourseDiagnosticError("Recourse diagnostic config must be a mapping.")
    if (
        config.get("run_class") != "diagnostic_validation"
        or config.get("output_policy") != "minimal"
        or config.get("git_eligible") is not False
    ):
        raise RecourseDiagnosticError("Recourse output classification changed.")
    contract = config.get("diagnostic_contract", {})
    exact = {
        "scenario_counts": [10, 30],
        "economic_horizon_hours": 24,
        "physical_horizon_hours": 48,
        "execution_hours": 24,
        "market_granularity": "quarterhour",
        "market_time_step_hours": 0.25,
        "physical_time_step_hours": 0.25,
        "solver_seed": 0,
        "solver_time_limit_seconds": 900,
    }
    for key, expected in exact.items():
        if contract.get(key) != expected:
            raise RecourseDiagnosticError(f"Diagnostic contract changed: {key}.")
    required_true = (
        "exact_clearing_test",
        "nearest_complete_scenario_control",
        "quantity_envelope_clip_test",
        "minimum_absolute_recourse_test",
        "iis_diagnostics",
        "reuse_cached_plan",
        "cache_full_plan_locally",
    )
    if any(contract.get(key) is not True for key in required_true):
        raise RecourseDiagnosticError("A required bounded diagnostic was disabled.")
    if any(value is not True for value in config.get("forbidden_scope", {}).values()):
        raise RecourseDiagnosticError("A forbidden recourse scope is no longer forbidden.")
    if config.get("case_id") != "S0_C1_responsive":
        raise RecourseDiagnosticError("Only the frozen S0 C1 case is authorized.")
    if contract.get("retry_s30_optimal_planning_after_documented_time_limit") is not False:
        raise RecourseDiagnosticError("The documented S30 time-limit may not be retried.")
    return config


def _frozen_parent_s10_expected_cost(config: Mapping[str, Any]) -> float:
    parent = _resolve(config["parent_run_root"])
    records = json.loads(
        (parent / "solver_diagnostics.json").read_text(encoding="utf-8")
    )
    for row in records:
        diagnostic = row.get("failure_diagnostic", {})
        planning = diagnostic.get("planning_solver", {})
        if row.get("case_id") == "S0_C1_responsive" and planning.get(
            "expected_cost_optimum_eur"
        ) is not None:
            return float(planning["expected_cost_optimum_eur"])
    raise RecourseDiagnosticError("Frozen parent S10 cost optimum is unavailable.")


def _bundle_hash(bundle: Any, actual: Any) -> str:
    return _payload_sha256(
        {
            "delivery_day": bundle.delivery_day.isoformat(),
            "timestamps": [item.isoformat() for item in bundle.timestamps_utc],
            "point_prices": list(bundle.point_prices),
            "scenario_prices": bundle.scenario_prices,
            "scenario_probabilities": bundle.scenario_probabilities,
            "actual_prices": list(actual.prices),
        }
    )


def _plan_payload(plan: SteelBidPlan, input_sha256: str) -> dict[str, Any]:
    return {
        "input_sha256": input_sha256,
        "policy": plan.policy,
        "configuration_id": plan.configuration_id,
        "delivery_day": plan.delivery_day.isoformat(),
        "bids": plan.bids,
        "scenario_dispatch": plan.scenario_dispatch,
        "solver": plan.solver,
        "expected_cost_eur": plan.expected_cost_eur,
        "input_scenario_ids": list(plan.input_scenario_ids),
        "input_probabilities": dict(plan.input_probabilities),
    }


def _plan_from_payload(payload: Mapping[str, Any], expected_hash: str) -> SteelBidPlan:
    if payload.get("input_sha256") != expected_hash:
        raise RecourseDiagnosticError("Cached plan input hash differs from current input.")
    return SteelBidPlan(
        policy=str(payload["policy"]),
        configuration_id=str(payload["configuration_id"]),
        delivery_day=date.fromisoformat(str(payload["delivery_day"])),
        bids=[dict(row) for row in payload["bids"]],
        scenario_dispatch=[dict(row) for row in payload["scenario_dispatch"]],
        solver=dict(payload["solver"]),
        expected_cost_eur=float(payload["expected_cost_eur"]),
        input_scenario_ids=tuple(str(item) for item in payload["input_scenario_ids"]),
        input_probabilities={
            str(key): float(item)
            for key, item in payload["input_probabilities"].items()
        },
    )


def _status_row(check_id: str, passed: bool, observed: Any, expected: Any) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "pass" if passed else "fail",
        "observed": observed,
        "expected": expected,
        "hard_gate": True,
    }


def _load_inputs(config: Mapping[str, Any]) -> dict[str, Any]:
    behavioural = load_behavioural_config(config["behavioural_config"])
    representative = load_representative_config(behavioural["representative_config"])
    frames = load_study_frames(representative)
    shape_library = _load_shape_library(frames)
    bundles = {
        count: build_synthetic_bundles(
            behavioural,
            frames,
            shape_library,
            scenario_count=count,
        )[str(config["profile_id"])]
        for count in (10, 30)
    }
    return {
        "behavioural": behavioural,
        "representative": representative,
        "frames": frames,
        "shape_library": shape_library,
        "bundles": bundles,
    }


def _scenario_support_rows(
    scenario_count: int, bundle: Any, actual: Any
) -> list[dict[str, Any]]:
    paths = np.asarray(list(bundle.scenario_prices.values()), dtype=float)
    realised = np.asarray(actual.prices, dtype=float)
    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(actual.timestamps_utc):
        lower = float(np.min(paths[:, index]))
        upper = float(np.max(paths[:, index]))
        rows.append(
            {
                "scenario_count": scenario_count,
                "market_interval_index": index,
                "target_timestamp_utc": timestamp.isoformat(),
                "realised_price_eur_per_mwh": float(realised[index]),
                "scenario_price_min_eur_per_mwh": lower,
                "scenario_price_max_eur_per_mwh": upper,
                "outside_price_support": bool(
                    realised[index] < lower or realised[index] > upper
                ),
            }
        )
    return rows


def _static_contract_checks(config: Mapping[str, Any], inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    s10_bundle, s10_actual = inputs["bundles"][10]
    s30_bundle, s30_actual = inputs["bundles"][30]
    timestamps = tuple(s10_bundle.timestamps_utc)
    spacings = {
        int((right - left).total_seconds() / 60)
        for left, right in zip(timestamps, timestamps[1:])
    }
    periods = _final_periods(inputs["behavioural"])
    selected_days = {
        s10_bundle.delivery_day,
        date.fromisoformat(inputs["behavioural"]["synthetic"]["actual_residual_source_date"]),
    }
    context = _base_context_config(
        inputs["representative"], market_granularity="quarterhour", horizon_hours=24
    )
    checks = [
        _status_row("qh_timestamp_count", len(timestamps) == 96, len(timestamps), 96),
        _status_row(
            "qh_timestamp_unique", len(set(timestamps)) == 96, len(set(timestamps)), 96
        ),
        _status_row("qh_spacing_minutes", spacings == {15}, sorted(spacings), [15]),
        _status_row(
            "market_time_step_hours",
            s10_bundle.time_step_hours == 0.25,
            s10_bundle.time_step_hours,
            0.25,
        ),
        _status_row(
            "physical_time_step_hours",
            context.time_grid.time_step_hours == 0.25,
            context.time_grid.time_step_hours,
            0.25,
        ),
        _status_row(
            "physical_horizon_intervals",
            context.time_grid.horizon_steps == 192,
            context.time_grid.horizon_steps,
            192,
        ),
        _status_row(
            "execution_intervals",
            context.time_grid.execution_steps == 96,
            context.time_grid.execution_steps,
            96,
        ),
        _status_row(
            "split_horizon_tail_active",
            bool(context.physical_feasibility_tail_active),
            context.physical_feasibility_tail_active,
            True,
        ),
        _status_row(
            "economic_horizon_hours",
            context.economic_horizon_hours == 24,
            context.economic_horizon_hours,
            24,
        ),
        _status_row(
            "s10_s30_actual_identity",
            tuple(s10_actual.prices) == tuple(s30_actual.prices)
            and s10_actual.timestamps_utc == s30_actual.timestamps_utc,
            _payload_sha256(list(s10_actual.prices)),
            _payload_sha256(list(s30_actual.prices)),
        ),
        _status_row(
            "final_regime_periods_excluded",
            not any(start <= day <= end for day in selected_days for start, end in periods),
            sorted(day.isoformat() for day in selected_days),
            "outside_all_final_periods",
        ),
        _status_row(
            "bid_grid_units_and_sign",
            min(STEEL_BID_GRID) == -500.0 and max(STEEL_BID_GRID) == 3000.0,
            [min(STEEL_BID_GRID), max(STEEL_BID_GRID)],
            [-500.0, 3000.0],
        ),
        _status_row(
            "same_qh_actual_time_grid",
            s10_bundle.timestamps_utc == s10_actual.timestamps_utc,
            len(set(s10_bundle.timestamps_utc) & set(s10_actual.timestamps_utc)),
            96,
        ),
    ]
    return checks


def prepare_recourse_diagnostic(
    config_path: str | Path = RECOURSE_DIAGNOSTIC_CONFIG,
    *,
    run_id: str,
    resume: bool = False,
) -> dict[str, Any]:
    config = load_recourse_diagnostic_config(config_path)
    output = _resolve(config["output_root"]) / run_id
    if output.exists() and not resume:
        raise RecourseDiagnosticError(
            f"Diagnostic output already exists; use --resume: {output}"
        )
    output.mkdir(parents=True, exist_ok=True)
    parent = _resolve(config["parent_run_root"])
    parent_summary = json.loads((parent / "gate_summary.json").read_text(encoding="utf-8"))
    if (
        parent_summary.get("decision") != "BLOCK"
        or parent_summary.get("final_weeks_used_for_development") is not False
    ):
        raise RecourseDiagnosticError("Parent BLOCK/final-week contract changed.")
    inputs = _load_inputs(config)
    checks = _static_contract_checks(config, inputs)
    if any(row["status"] != "pass" for row in checks):
        raise RecourseDiagnosticError(f"Static recourse checks failed: {checks}")
    support = [
        row
        for count in (10, 30)
        for row in _scenario_support_rows(count, *inputs["bundles"][count])
    ]
    declaration = {
        "output_root": str(output.relative_to(REPO_ROOT)).replace("\\", "/"),
        "case_ids": ["S0_C1_responsive"],
        "scenario_counts": [10, 30],
        "planning_model_builds": 0,
        "planning_scenario_block_builds": 0,
        "diagnostic_recourse_model_builds_maximum": 4,
        "solver_calls_maximum": 4,
        "iis_computations_maximum": 3,
        "expected_file_count": int(config["outputs"]["expected_file_count"]),
        "expected_approximate_size_mb": int(
            config["outputs"]["expected_approximate_size_mb"]
        ),
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "final_regime_weeks_authorized_or_scheduled": False,
        "canonical_imbalance_or_robust_bids_authorized": False,
    }
    _write_json(output / "output_declaration.json", declaration)
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    _write_json(
        output / "input_manifest.json",
        {
            "parent_run": str(parent.relative_to(REPO_ROOT)).replace("\\", "/"),
            "parent_gate_summary_sha256": _sha256(parent / "gate_summary.json"),
            "behavioural_config_sha256": _sha256(_resolve(config["behavioural_config"])),
            "diagnostic_config_sha256": _sha256(_resolve(config_path)),
            "bundle_sha256": {
                str(count): _bundle_hash(*inputs["bundles"][count])
                for count in (10, 30)
            },
            "frozen_parent_s10_expected_cost_optimum_eur": (
                _frozen_parent_s10_expected_cost(config)
            ),
            "synthetic_delivery_day": inputs["bundles"][10][0].delivery_day.isoformat(),
            "synthetic_actual_residual_source_day": inputs["behavioural"]["synthetic"][
                "actual_residual_source_date"
            ],
            "final_regime_rows_selected_or_solved": False,
        },
    )
    _write_json(
        output / "code_version.json",
        {
            "git_head": __import__("subprocess").run(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "diagnostic_module_sha256": _sha256(Path(__file__)),
            "behavioural_module_sha256": _sha256(
                Path(__file__).with_name("s4_4c6_behavioural_validation.py")
            ),
            "phase6d_engine_sha256": _sha256(
                Path(__file__).with_name("s4_4c6_phase6d_eaf_heat_state_one_day.py")
            ),
        },
    )
    _write_csv(output / "static_contract_checks.csv", checks)
    _write_csv(output / "scenario_support.csv", support)
    if not (output / "run_summary.json").exists():
        _write_json(
            output / "run_summary.json",
            {
                "status": "prepared_no_solver_runs",
                "decision": None,
                "final_regime_weeks_used": False,
            },
        )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- Diagnostic-only S0 C1 evidence; no final regime week is used.\n"
        "- S30 is support-expansion diagnosis, not recalibration or promotion.\n"
        "- Deviation variables have no market settlement and do not authorize imbalance.\n"
        "- Quantity clipping is a counterfactual feasibility diagnostic only.\n"
        "- No physical bound, yield, production requirement or market objective changes.\n",
        encoding="utf-8",
    )
    return {
        "config": config,
        "inputs": inputs,
        "output": output,
        "declaration": declaration,
    }


def _scenario_import_paths(plan: SteelBidPlan) -> pd.DataFrame:
    frame = pd.DataFrame(plan.scenario_dispatch)
    frame = frame[frame["economic_horizon_active"].astype(bool)]
    paths = (
        frame.groupby(["scenario_id", "market_interval_index"])[
            "planned_net_grid_import_mwh"
        ]
        .sum()
        .unstack("market_interval_index")
        .sort_index()
    )
    if paths.shape != (len(plan.input_scenario_ids), 96):
        raise RecourseDiagnosticError(f"Planned import path matrix changed: {paths.shape}.")
    return paths


def _canonicalize_cached_plan(plan: SteelBidPlan, bundle: Any) -> SteelBidPlan:
    paths = _scenario_import_paths(plan)
    scenario_imports = {
        str(scenario_id): tuple(row.to_numpy(dtype=float))
        for scenario_id, row in paths.iterrows()
    }
    canonical = canonical_bid_volumes_from_scenario_requirements(
        bundle.scenario_prices,
        scenario_imports,
    )
    for row in plan.bids:
        key = (
            int(row["market_interval_index"]),
            float(row["bid_price_eur_per_mwh"]),
        )
        row["incremental_bid_volume_mwh"] = float(canonical[key])
    plan.solver.update(
        {
            "bid_curve_source": (
                "analytical_frozen_minimum_volume_highest_willingness_price_"
                "canonicalisation_from_feasible_incumbent"
            ),
            "bid_curve_resolve_performed": False,
            "bid_curve_canonicalisation_performed": True,
            "bid_curve_canonicalisation_requires_additional_solve": False,
            "bid_curve_canonical_tiebreak": (
                "minimum_total_volume_then_highest_willingness_price"
            ),
        }
    )
    return plan


def quantity_envelope_clip(
    cleared: Sequence[float], paths: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    realised = np.asarray(cleared, dtype=float)
    lower = np.min(np.asarray(paths, dtype=float), axis=0)
    upper = np.max(np.asarray(paths, dtype=float), axis=0)
    return np.clip(realised, lower, upper), lower, upper


def _independent_clear(plan: SteelBidPlan, actual: Any) -> np.ndarray:
    bids = pd.DataFrame(plan.bids)
    rows: list[float] = []
    for timestamp, price in zip(actual.timestamps_utc, actual.prices):
        selected = bids[bids["target_timestamp_utc"].eq(timestamp.isoformat())]
        rows.append(
            float(
                selected.loc[
                    selected["bid_price_eur_per_mwh"].astype(float) >= float(price),
                    "incremental_bid_volume_mwh",
                ]
                .astype(float)
                .sum()
            )
        )
    return np.asarray(rows, dtype=float)


def _plan_contract_checks(
    scenario_count: int,
    plan: SteelBidPlan,
    bundle: Any,
    actual: Any,
    cleared: np.ndarray,
    paths: pd.DataFrame,
) -> list[dict[str, Any]]:
    bids = pd.DataFrame(plan.bids)
    scenario_reconstruction_errors: list[float] = []
    for scenario_id, path in paths.iterrows():
        for market_t, physical_import in enumerate(path.to_numpy(dtype=float)):
            interval_bids = bids[bids["market_interval_index"].eq(market_t)]
            reconstructed = interval_bids.loc[
                interval_bids["bid_price_eur_per_mwh"].astype(float)
                >= float(bundle.scenario_prices[str(scenario_id)][market_t]),
                "incremental_bid_volume_mwh",
            ].astype(float).sum()
            scenario_reconstruction_errors.append(
                abs(float(physical_import) - float(reconstructed))
            )
    independent = _independent_clear(plan, actual)
    bid_counts = bids.groupby("market_interval_index").size()
    timestamps_by_index = (
        bids.groupby("market_interval_index")["target_timestamp_utc"].first().tolist()
    )
    return [
        {
            **_status_row(
                "scenario_count",
                len(plan.input_scenario_ids) == scenario_count,
                len(plan.input_scenario_ids),
                scenario_count,
            ),
            "scenario_count": scenario_count,
        },
        {
            **_status_row(
                "probability_mass",
                abs(sum(plan.input_probabilities.values()) - 1.0) <= 1e-10,
                sum(plan.input_probabilities.values()),
                1.0,
            ),
            "scenario_count": scenario_count,
        },
        {
            **_status_row(
                "sixteen_bid_steps_per_qh",
                len(bid_counts) == 96 and bool(bid_counts.eq(len(STEEL_BID_GRID)).all()),
                sorted(bid_counts.unique().tolist()),
                [len(STEEL_BID_GRID)],
            ),
            "scenario_count": scenario_count,
        },
        {
            **_status_row(
                "bid_timestamp_index_alignment",
                timestamps_by_index
                == [timestamp.isoformat() for timestamp in bundle.timestamps_utc],
                _payload_sha256(timestamps_by_index),
                _payload_sha256(
                    [timestamp.isoformat() for timestamp in bundle.timestamps_utc]
                ),
            ),
            "scenario_count": scenario_count,
        },
        {
            **_status_row(
                "scenario_bid_clearing_reconstruction_mwh",
                max(scenario_reconstruction_errors) <= 1e-5,
                max(scenario_reconstruction_errors),
                "<=1e-5",
            ),
            "scenario_count": scenario_count,
        },
        {
            **_status_row(
                "actual_bid_clearing_reconstruction_mwh",
                float(np.max(np.abs(independent - cleared))) <= 1e-10,
                float(np.max(np.abs(independent - cleared))),
                "<=1e-10",
            ),
            "scenario_count": scenario_count,
        },
        {
            **_status_row(
                "cleared_energy_nonnegative",
                bool(np.all(cleared >= -1e-10)),
                float(np.min(cleared)),
                ">=-1e-10 MWh",
            ),
            "scenario_count": scenario_count,
        },
    ]


def _build_recourse_model(
    context: Any,
    state: SteelRollingState,
    cleared: Sequence[float],
    *,
    allow_deviation: bool,
) -> Any:
    group_size = _physical_group_size(context.granularity)
    quantities = tuple(float(item) for item in cleared)
    if group_size != 1 or len(quantities) != context.time_grid.execution_steps:
        raise RecourseDiagnosticError("The bounded diagnostic requires 96 QH quantities.")
    model = _build_physical_model(
        context,
        C1_CONFIGURATION,
        state,
        terminal_day=False,
        planning_horizon_hours=context.time_grid.horizon_hours,
        terminal_hour_in_horizon=None,
    )
    model.RECOURSE_DIAGNOSTIC_MARKET = Set(
        initialize=tuple(range(len(quantities))), ordered=True
    )
    if allow_deviation:
        model.recourse_deviation_positive_mwh = Var(
            model.RECOURSE_DIAGNOSTIC_MARKET, domain=NonNegativeReals
        )
        model.recourse_deviation_negative_mwh = Var(
            model.RECOURSE_DIAGNOSTIC_MARKET, domain=NonNegativeReals
        )
        model.recourse_cleared_import = Constraint(
            model.RECOURSE_DIAGNOSTIC_MARKET,
            rule=lambda m, market_t: m.net_grid_import_mwh[int(market_t)]
            == quantities[int(market_t)]
            + m.recourse_deviation_positive_mwh[market_t]
            - m.recourse_deviation_negative_mwh[market_t],
        )
        model.recourse_deviation_objective = Objective(
            expr=sum(
                model.recourse_deviation_positive_mwh[market_t]
                + model.recourse_deviation_negative_mwh[market_t]
                for market_t in model.RECOURSE_DIAGNOSTIC_MARKET
            ),
            sense=minimize,
        )
    else:
        model.recourse_cleared_import = Constraint(
            model.RECOURSE_DIAGNOSTIC_MARKET,
            rule=lambda m, market_t: m.net_grid_import_mwh[int(market_t)]
            == quantities[int(market_t)],
        )
        model.recourse_progress_objective = Objective(
            expr=model.rolling_production_progress_deviation_t, sense=minimize
        )
    return model


def _constraint_rhs(model: Any) -> np.ndarray:
    return np.asarray(
        [
            float(value(model.recourse_cleared_import[index].lower))
            for index in model.RECOURSE_DIAGNOSTIC_MARKET
        ],
        dtype=float,
    )


def _iis_family(name: str) -> str:
    cleaned = re.sub(r"^(c_[elu]_)", "", name)
    return re.split(r"[\[(]", cleaned, maxsplit=1)[0]


def _direct_feasibility_and_iis(
    model: Any,
    *,
    output: Path,
    scenario_count: int,
    diagnostic_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stats = collect_model_stats(model)
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        lp_path = Path(temporary) / f"{diagnostic_id}.lp"
        model.write(str(lp_path), io_options={"symbolic_solver_labels": True})
        direct = gp.read(str(lp_path))
        direct.Params.OutputFlag = 0
        direct.Params.Seed = 0
        direct.Params.TimeLimit = 900.0
        direct.Params.MIPGap = 0.001
        direct.Params.IntFeasTol = 1e-9
        direct.optimize()
        status_names = {
            gp.GRB.OPTIMAL: "optimal",
            gp.GRB.INFEASIBLE: "infeasible",
            gp.GRB.TIME_LIMIT: "time_limit",
            gp.GRB.INF_OR_UNBD: "infeasible_or_unbounded",
        }
        status = status_names.get(direct.Status, f"gurobi_status_{direct.Status}")
        result = {
            "scenario_count": scenario_count,
            "diagnostic_id": diagnostic_id,
            "status": status,
            "proven_feasible": direct.Status == gp.GRB.OPTIMAL,
            "proven_infeasible": direct.Status == gp.GRB.INFEASIBLE,
            "runtime_seconds": float(direct.Runtime),
            "objective_value": (
                float(direct.ObjVal) if direct.SolCount > 0 else None
            ),
            "variable_count": stats.variables,
            "binary_count": stats.binaries,
            "constraint_count": stats.constraints,
            "lp_or_mps_retained": False,
        }
        iis_rows: list[dict[str, Any]] = []
        if direct.Status == gp.GRB.INFEASIBLE:
            direct.computeIIS()
            for constraint in direct.getConstrs():
                if constraint.IISConstr:
                    iis_rows.append(
                        {
                            "scenario_count": scenario_count,
                            "diagnostic_id": diagnostic_id,
                            "iis_member_type": "constraint",
                            "name": constraint.ConstrName,
                            "constraint_family": _iis_family(constraint.ConstrName),
                        }
                    )
            for variable in direct.getVars():
                for bound, active in (
                    ("lower_bound", variable.IISLB),
                    ("upper_bound", variable.IISUB),
                ):
                    if active:
                        iis_rows.append(
                            {
                                "scenario_count": scenario_count,
                                "diagnostic_id": diagnostic_id,
                                "iis_member_type": bound,
                                "name": variable.VarName,
                                "constraint_family": _iis_family(variable.VarName),
                            }
                        )
        result["iis_member_count"] = len(iis_rows)
        return result, iis_rows


def _minimum_recourse_deviation(
    context: Any,
    state: SteelRollingState,
    cleared: np.ndarray,
    actual: Any,
    lower: np.ndarray,
    upper: np.ndarray,
    *,
    scenario_count: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    model = _build_recourse_model(
        context, state, cleared, allow_deviation=True
    )
    _, solver = _solver_for_phase6d(context)
    _, solver_record = _solve_optimal(
        model, solver, "minimum_absolute_recourse_deviation", warmstart=False
    )
    intervals: list[dict[str, Any]] = []
    deviations: list[float] = []
    for index, timestamp in enumerate(actual.timestamps_utc):
        positive = float(value(model.recourse_deviation_positive_mwh[index]))
        negative = float(value(model.recourse_deviation_negative_mwh[index]))
        signed = positive - negative
        absolute = positive + negative
        deviations.append(absolute)
        if absolute > 1e-6:
            intervals.append(
                {
                    "scenario_count": scenario_count,
                    "market_interval_index": index,
                    "target_timestamp_utc": timestamp.isoformat(),
                    "cleared_import_mwh": float(cleared[index]),
                    "physical_import_mwh": float(
                        value(model.net_grid_import_mwh[index])
                    ),
                    "deviation_positive_mwh": positive,
                    "deviation_negative_mwh": negative,
                    "signed_physical_minus_cleared_mwh": signed,
                    "absolute_deviation_mwh": absolute,
                    "scenario_import_min_mwh": float(lower[index]),
                    "scenario_import_max_mwh": float(upper[index]),
                    "clearing_outside_quantity_envelope": bool(
                        cleared[index] < lower[index] - 1e-6
                        or cleared[index] > upper[index] + 1e-6
                    ),
                }
            )
    summary = {
        "scenario_count": scenario_count,
        "diagnostic_id": "minimum_absolute_recourse_deviation",
        "status": "optimal",
        "total_absolute_deviation_mwh": float(sum(deviations)),
        "maximum_qh_deviation_mwh": float(max(deviations)),
        "affected_qh_count": len(intervals),
        "objective_units": "MWh",
        "settlement_active": False,
        "canonical_imbalance_authorized": False,
    }
    return summary, intervals, solver_record


def classify_recourse_cause(
    *,
    contract_checks_pass: bool,
    nearest_controls_feasible: bool | None,
    s10_exact_infeasible: bool,
    s10_clipped_infeasible: bool,
    s30_exact_infeasible: bool | None,
    s10_price_undercoverage_count: int,
    s30_price_undercoverage_count: int,
    pre_fix_exact_infeasible: bool = False,
) -> dict[str, Any]:
    bid_step_fix_verified = pre_fix_exact_infeasible and not s10_exact_infeasible
    evidence_complete = (
        contract_checks_pass
        and nearest_controls_feasible is not None
        and (s10_exact_infeasible or bid_step_fix_verified)
    )
    implementation_error = not contract_checks_pass or nearest_controls_feasible is False
    support_undercoverage = (
        s10_price_undercoverage_count > 0
        and s30_price_undercoverage_count < s10_price_undercoverage_count
    )
    structural_splicing = s10_exact_infeasible and s10_clipped_infeasible
    if bid_step_fix_verified and contract_checks_pass and nearest_controls_feasible:
        classification = (
            "bid_step_canonicalisation_contract_error_exposed_by_support_"
            "undercoverage_resolved"
        )
        implementation_error = True
    elif implementation_error:
        classification = "implementation_or_contract_error"
    elif not evidence_complete:
        classification = "incomplete_planning_or_recourse_evidence"
    elif structural_splicing and support_undercoverage:
        classification = "combination_support_undercoverage_and_structural_path_splicing"
    elif structural_splicing:
        classification = "structural_path_splicing"
    elif support_undercoverage:
        classification = "insufficient_scenario_or_tail_coverage"
    else:
        classification = "unresolved"
    return {
        "classification": classification,
        "implementation_or_contract_error": implementation_error,
        "insufficient_scenario_or_tail_coverage": support_undercoverage,
        "structural_intervalwise_path_splicing": structural_splicing,
        "evidence_complete": evidence_complete,
        "bid_step_canonicalisation_fix_verified": bid_step_fix_verified,
        "s30_exact_infeasible": s30_exact_infeasible,
        "requires_methodological_decision": classification
        not in {
            "bid_step_canonicalisation_contract_error_exposed_by_support_"
            "undercoverage_resolved",
            "implementation_or_contract_error",
            "incomplete_planning_or_recourse_evidence",
            "unresolved",
        },
    }


def _method_comparison(
    classification: Mapping[str, Any],
    deviation_s10: Mapping[str, Any] | None,
    deviation_s30: Mapping[str, Any] | None,
    support_counts: Mapping[int, int],
    feasibility: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    local_fix_verified = bool(
        classification.get("bid_step_canonicalisation_fix_verified")
    )
    return [
        {
            "option": "bounded_imbalance_recourse",
            "quantitative_evidence": (
                None
                if deviation_s10 is None
                else (
                    f"S10 total={deviation_s10['total_absolute_deviation_mwh']:.6f} MWh; "
                    f"max_qh={deviation_s10['maximum_qh_deviation_mwh']:.6f} MWh; "
                    f"intervals={deviation_s10['affected_qh_count']}"
                )
            ),
            "runtime_quality": "one diagnostic MILP per scenario count",
            "methodological_change": "adds explicit DA-to-physical deviation and settlement choice",
            "promotion_status": (
                "not_required_after_zero_deviation_local_fix"
                if local_fix_verified
                else "not_authorized_diagnostic_only"
            ),
        },
        {
            "option": "robustly_feasible_bid_curves",
            "quantitative_evidence": (
                f"S10 exact={feasibility.get('S10_exact', {}).get('status')}; "
                f"S10 clipped={feasibility.get('S10_clipped', {}).get('status')}; "
                f"classification={classification['classification']}"
            ),
            "runtime_quality": "would add cross-price-region or recourse constraints to planning",
            "methodological_change": "changes admissible bid curves to guarantee complete recourse",
            "promotion_status": (
                "not_required_for_observed_failure_after_canonical_bid_fix"
                if local_fix_verified
                else "requires_user_decision"
            ),
        },
        {
            "option": "scenario_support_expansion",
            "quantitative_evidence": (
                f"price outside support S10={support_counts[10]}/96, "
                f"S30={support_counts[30]}/96; "
                f"S30 exact={feasibility.get('S30_exact', {}).get('status')}; "
                f"S30 recourse deviation="
                f"{None if deviation_s30 is None else deviation_s30['total_absolute_deviation_mwh']}"
            ),
            "runtime_quality": "planning scenario blocks increase from 10 to 30",
            "methodological_change": "retains sampled-scenario feasibility but cannot guarantee unseen price-region paths",
            "promotion_status": (
                "not_required_for_local_fix_s30_runtime_limit_retained"
                if local_fix_verified
                else "diagnostic_only_pending_evidence"
            ),
        },
    ]


def run_recourse_diagnostics(
    config_path: str | Path = RECOURSE_DIAGNOSTIC_CONFIG,
    *,
    run_id: str,
    resume: bool = False,
) -> dict[str, Any]:
    prepared = prepare_recourse_diagnostic(
        config_path, run_id=run_id, resume=resume
    )
    config = prepared["config"]
    inputs = prepared["inputs"]
    output = prepared["output"]
    context = _base_context_config(
        inputs["representative"], market_granularity="quarterhour", horizon_hours=24
    )
    state = SteelRollingState(
        episode_id=str(config["case_id"]), configuration_id=C1_CONFIGURATION
    )
    contract_checks = list(
        pd.read_csv(output / "static_contract_checks.csv").to_dict(orient="records")
    )
    clearing_rows: list[dict[str, Any]] = []
    feasibility_rows: list[dict[str, Any]] = []
    iis_rows: list[dict[str, Any]] = []
    deviation_rows: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    feasibility_by_id: dict[str, dict[str, Any]] = {}
    deviation_by_count: dict[int, dict[str, Any]] = {}
    support_frame = pd.read_csv(output / "scenario_support.csv")
    support_counts = {
        count: int(
            support_frame[
                support_frame["scenario_count"].eq(count)
                & support_frame["outside_price_support"].astype(bool)
            ].shape[0]
        )
        for count in (10, 30)
    }
    planning_status: dict[int, str] = {}
    frozen_s10_expected_cost = _frozen_parent_s10_expected_cost(config)
    pre_fix_rows = pd.read_csv(
        _resolve(config["pre_fix_diagnostic_root"]) / "redispatch_feasibility.csv"
    )
    pre_fix_exact_infeasible = bool(
        (
            pre_fix_rows["diagnostic_id"].eq("S10_exact")
            & pre_fix_rows["proven_infeasible"].astype(str).str.lower().eq("true")
        ).any()
    )
    for scenario_count in (10, 30):
        bundle, actual = inputs["bundles"][scenario_count]
        input_hash = _bundle_hash(bundle, actual)
        cache = output / PLAN_CACHE_NAMES[scenario_count]
        try:
            if cache.exists():
                plan = _plan_from_payload(_read_gzip_json(cache), input_hash)
                planning_status[scenario_count] = "reused_cached_optimal_plan"
            elif scenario_count == 10:
                reusable_root = _resolve(config["reusable_s10_plan_root"])
                reusable_cache = reusable_root / PLAN_CACHE_NAMES[10]
                plan = _plan_from_payload(
                    _read_gzip_json(reusable_cache), input_hash
                )
                planning_status[scenario_count] = (
                    "reused_frozen_parent_optimum_plan_from_pre_fix_diagnostic"
                )
            elif (
                scenario_count == 30
                and config["diagnostic_contract"][
                    "retry_s30_optimal_planning_after_documented_time_limit"
                ]
                is False
            ):
                prior_root = _resolve(config["prior_bounded_diagnostic_root"])
                prior_rows = json.loads(
                    (prior_root / "solver_diagnostics.json").read_text(
                        encoding="utf-8"
                    )
                )
                prior = next(
                    row
                    for row in prior_rows
                    if int(row.get("scenario_count", 0)) == 30
                    and row.get("status") == "performance_incomplete"
                )
                planning_status[scenario_count] = (
                    "reused_prior_performance_incomplete_no_retry"
                )
                solver_rows.append(
                    {
                        **prior,
                        "status": "reused_prior_performance_incomplete",
                        "source_run_root": str(
                            prior_root.relative_to(REPO_ROOT)
                        ).replace("\\", "/"),
                    }
                )
                continue
            else:
                plan = solve_grouped_da_bid_plan(
                    context,
                    C1_CONFIGURATION,
                    bundle,
                    state,
                    f"QH-S{scenario_count}",
                    audit_future_paths=True,
                    diagnostic_frozen_expected_cost_optimum_eur=(
                        frozen_s10_expected_cost
                        if scenario_count == 10
                        else None
                    ),
                )
                _write_gzip_json(cache, _plan_payload(plan, input_hash))
                planning_status[scenario_count] = (
                    "new_frozen_parent_optimum_feasibility_plan_cached"
                    if scenario_count == 10
                    else "new_optimal_plan_cached"
                )
            plan = _canonicalize_cached_plan(plan, bundle)
            _write_gzip_json(cache, _plan_payload(plan, input_hash))
            solver_rows.append(
                {
                    "scenario_count": scenario_count,
                    "diagnostic_id": "stochastic_da_plan",
                    "status": "optimal",
                    "cache_status": planning_status[scenario_count],
                    **plan.solver,
                }
            )
        except Phase6DPerformanceIncomplete as exc:
            planning_status[scenario_count] = "performance_incomplete"
            solver_rows.append(
                {
                    "scenario_count": scenario_count,
                    "diagnostic_id": "stochastic_da_plan",
                    "status": "performance_incomplete",
                    "error": str(exc),
                }
            )
            continue
        except Phase6DError as exc:
            planning_status[scenario_count] = "failed"
            solver_rows.append(
                {
                    "scenario_count": scenario_count,
                    "diagnostic_id": "stochastic_da_plan",
                    "status": "failed",
                    "error": str(exc),
                }
            )
            continue
        clearing = clear_hourly_da_bids(plan.bids, actual)
        cleared = np.asarray(
            [float(row["cleared_energy_mwh"]) for row in clearing.hourly], dtype=float
        )
        paths = _scenario_import_paths(plan)
        path_values = paths.to_numpy(dtype=float)
        clipped, lower, upper = quantity_envelope_clip(cleared, path_values)
        nearest_index = int(
            np.argmin(np.sqrt(np.mean((path_values - cleared) ** 2, axis=1)))
        )
        nearest_scenario_id = str(paths.index[nearest_index])
        nearest_path = path_values[nearest_index]
        contract_checks.extend(
            _plan_contract_checks(
                scenario_count, plan, bundle, actual, cleared, paths
            )
        )
        exact_model = _build_recourse_model(
            context, state, cleared, allow_deviation=False
        )
        injected = _constraint_rhs(exact_model)
        contract_checks.append(
            {
                **_status_row(
                    "exact_cleared_quantity_injection",
                    bool(np.array_equal(injected, cleared)),
                    _payload_sha256(injected.tolist()),
                    _payload_sha256(cleared.tolist()),
                ),
                "scenario_count": scenario_count,
            }
        )
        contract_checks.append(
            {
                **_status_row(
                    "non_terminal_24e48p_policy",
                    not hasattr(exact_model, "rolling_terminal_inventory_band"),
                    hasattr(exact_model, "rolling_terminal_inventory_band"),
                    False,
                ),
                "scenario_count": scenario_count,
            }
        )
        exact_result, exact_iis = _direct_feasibility_and_iis(
            exact_model,
            output=output,
            scenario_count=scenario_count,
            diagnostic_id=f"S{scenario_count}_exact",
        )
        feasibility_rows.append(exact_result)
        feasibility_by_id[f"S{scenario_count}_exact"] = exact_result
        iis_rows.extend(exact_iis)
        nearest_model = _build_recourse_model(
            context, state, nearest_path, allow_deviation=False
        )
        nearest_result, nearest_iis = _direct_feasibility_and_iis(
            nearest_model,
            output=output,
            scenario_count=scenario_count,
            diagnostic_id=f"S{scenario_count}_nearest_complete_scenario_control",
        )
        feasibility_rows.append(nearest_result)
        feasibility_by_id[
            f"S{scenario_count}_nearest_complete_scenario_control"
        ] = nearest_result
        iis_rows.extend(nearest_iis)
        clipped_model = _build_recourse_model(
            context, state, clipped, allow_deviation=False
        )
        clipped_result, clipped_iis = _direct_feasibility_and_iis(
            clipped_model,
            output=output,
            scenario_count=scenario_count,
            diagnostic_id=f"S{scenario_count}_clipped",
        )
        feasibility_rows.append(clipped_result)
        feasibility_by_id[f"S{scenario_count}_clipped"] = clipped_result
        iis_rows.extend(clipped_iis)
        deviation_summary, intervals, deviation_solver = _minimum_recourse_deviation(
            context,
            state,
            cleared,
            actual,
            lower,
            upper,
            scenario_count=scenario_count,
        )
        deviation_by_count[scenario_count] = deviation_summary
        feasibility_rows.append(deviation_summary)
        deviation_rows.extend(intervals)
        solver_rows.append(
            {
                "scenario_count": scenario_count,
                "diagnostic_id": "minimum_absolute_recourse_deviation",
                **deviation_solver,
            }
        )
        for index, row in enumerate(clearing.hourly):
            clearing_rows.append(
                {
                    "scenario_count": scenario_count,
                    "market_interval_index": index,
                    "target_timestamp_utc": row["target_timestamp_utc"],
                    "realised_price_eur_per_mwh": row[
                        "realised_price_eur_per_mwh"
                    ],
                    "cleared_import_mwh": float(cleared[index]),
                    "scenario_import_min_mwh": float(lower[index]),
                    "scenario_import_max_mwh": float(upper[index]),
                    "outside_quantity_envelope": bool(
                        cleared[index] < lower[index] - 1e-6
                        or cleared[index] > upper[index] + 1e-6
                    ),
                    "clipped_import_mwh": float(clipped[index]),
                    "clip_absolute_change_mwh": float(
                        abs(clipped[index] - cleared[index])
                    ),
                    "nearest_complete_scenario_id": nearest_scenario_id,
                    "nearest_complete_scenario_import_mwh": float(
                        nearest_path[index]
                    ),
                }
            )
        _write_csv(output / "contract_checks.csv", contract_checks)
        _write_csv(output / "clearing_diagnostics.csv", clearing_rows)
        _write_csv(output / "redispatch_feasibility.csv", feasibility_rows)
        _write_csv(output / "iis_members.csv", iis_rows)
        _write_csv(output / "minimum_deviation_intervals.csv", deviation_rows)
        _write_json(output / "solver_diagnostics.json", solver_rows)
    contract_pass = all(str(row.get("status")) == "pass" for row in contract_checks)
    nearest_rows = [
        row
        for key, row in feasibility_by_id.items()
        if "nearest_complete_scenario_control" in key
    ]
    nearest_feasible = (
        None
        if not nearest_rows
        else all(row.get("proven_feasible") is True for row in nearest_rows)
    )
    classification = classify_recourse_cause(
        contract_checks_pass=contract_pass,
        nearest_controls_feasible=nearest_feasible,
        s10_exact_infeasible=bool(
            feasibility_by_id.get("S10_exact", {}).get("proven_infeasible")
        ),
        s10_clipped_infeasible=bool(
            feasibility_by_id.get("S10_clipped", {}).get("proven_infeasible")
        ),
        s30_exact_infeasible=(
            None
            if "S30_exact" not in feasibility_by_id
            else bool(feasibility_by_id["S30_exact"].get("proven_infeasible"))
        ),
        pre_fix_exact_infeasible=pre_fix_exact_infeasible,
        s10_price_undercoverage_count=support_counts[10],
        s30_price_undercoverage_count=support_counts[30],
    )
    classification.update(
        {
            "planning_status": planning_status,
            "contract_checks_all_pass": contract_pass,
            "nearest_complete_scenario_controls_all_feasible": nearest_feasible,
            "final_regime_weeks_used": False,
            "canonical_imbalance_or_robust_bid_change_made": False,
        }
    )
    comparison = _method_comparison(
        classification,
        deviation_by_count.get(10),
        deviation_by_count.get(30),
        support_counts,
        feasibility_by_id,
    )
    _write_csv(output / "contract_checks.csv", contract_checks)
    _write_csv(output / "clearing_diagnostics.csv", clearing_rows)
    _write_csv(output / "redispatch_feasibility.csv", feasibility_rows)
    _write_csv(output / "iis_members.csv", iis_rows)
    _write_csv(output / "minimum_deviation_intervals.csv", deviation_rows)
    _write_json(output / "solver_diagnostics.json", solver_rows)
    _write_json(output / "cause_classification.json", classification)
    _write_csv(output / "method_comparison.csv", comparison)
    completed_counts = sorted(
        count for count in (10, 30) if f"S{count}_exact" in feasibility_by_id
    )
    local_fix_verified = bool(
        classification.get("bid_step_canonicalisation_fix_verified")
    )
    summary = {
        "status": (
            "complete_local_repair_verified"
            if local_fix_verified
            else "complete_methodological_decision_required"
            if classification["requires_methodological_decision"]
            else "complete_local_repair_required"
            if classification["implementation_or_contract_error"]
            else "incomplete"
        ),
        "decision": "LOCAL_REPAIR_VERIFIED"
        if local_fix_verified
        else "METHOD_DECISION_REQUIRED"
        if classification["requires_methodological_decision"]
        else "LOCAL_REPAIR_REQUIRED"
        if classification["implementation_or_contract_error"]
        else "INCOMPLETE",
        "classification": classification["classification"],
        "completed_scenario_counts": completed_counts,
        "planning_status": planning_status,
        "final_regime_weeks_used": False,
        "synthetic_or_shadow_gate_rerun": False,
        "reason_gate_not_rerun": (
            "Local repair verified; full synthetic and conditional shadow rerun pending."
            if local_fix_verified
            else
            "No simple implementation/contract defect was found and a methodological "
            "recourse choice requires user authorization."
            if classification["requires_methodological_decision"]
            else None
        ),
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
    }
    _write_json(output / "run_summary.json", summary)
    return {"output": str(output), "summary": summary}


__all__ = [
    "RECOURSE_DIAGNOSTIC_CONFIG",
    "RecourseDiagnosticError",
    "classify_recourse_cause",
    "load_recourse_diagnostic_config",
    "prepare_recourse_diagnostic",
    "quantity_envelope_clip",
    "run_recourse_diagnostics",
]
