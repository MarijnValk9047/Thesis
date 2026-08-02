"""Bounded diagnosis of the non-final typical/calm C1 shadow recourse failure."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import yaml

from .model import collect_model_stats
from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C1_CONFIGURATION,
)
from .s4_4c6_behavioural_validation import (
    _base_context_config,
    _load_shape_library,
    build_case_manifest,
    build_shadow_overlay,
    load_behavioural_config,
    select_shadow_days,
)
from .s4_4c6_phase6b_hourly_da_bid_clear_redispatch import (
    SteelRollingState,
    clear_hourly_da_bids,
)
from .s4_4c6_phase6d_eaf_heat_state_one_day import solve_grouped_da_bid_plan
from .s4_4c6_recourse_diagnostics import (
    _build_recourse_model,
    _bundle_hash,
    _constraint_rhs,
    _direct_feasibility_and_iis,
    _minimum_recourse_deviation,
    _plan_from_payload,
    _plan_contract_checks,
    _plan_payload,
    _read_gzip_json,
    _scenario_import_paths,
    _scenario_support_rows,
    _write_gzip_json,
    quantity_envelope_clip,
)
from .s4_4c6_representative_regime_counterfactual import (
    build_price_bundles,
    load_representative_config,
    load_study_frames,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


SHADOW_RECOURSE_CONFIG = Path(
    "scripts/Data/04_Steel_Test_Case/configs/steel_c6_shadow_recourse_diagnostics.yaml"
)


class ShadowRecourseDiagnosticError(RuntimeError):
    """Raised when the bounded shadow diagnostic contract changes."""


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fields: list[str] = []
    for row in materialized:
        fields.extend(key for key in row if key not in fields)
    pd.DataFrame(materialized, columns=fields or ["status"]).to_csv(path, index=False)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_shadow_recourse_config(
    path: str | Path = SHADOW_RECOURSE_CONFIG,
) -> dict[str, Any]:
    config = yaml.safe_load(_resolve(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ShadowRecourseDiagnosticError("Shadow recourse config must be a mapping.")
    exact = {
        "run_class": "diagnostic_validation",
        "output_policy": "minimal",
        "git_eligible": False,
        "case_id": "shadow__typical_calm__2025-03-02__C__C1__responsive",
        "delivery_day": "2025-03-02",
        "arm": "C_qh_shape",
        "configuration": "C1",
        "policy": "responsive",
    }
    for key, expected in exact.items():
        if config.get(key) != expected:
            raise ShadowRecourseDiagnosticError(f"Frozen shadow diagnostic changed: {key}.")
    contract = config["diagnostic_contract"]
    if (
        int(contract["scenario_count"]) != 10
        or int(contract["physical_horizon_hours"]) != 48
        or int(contract["execution_hours"]) != 24
    ):
        raise ShadowRecourseDiagnosticError("Shadow diagnostic horizon/S10 changed.")
    if any(value is not True for value in config["forbidden_scope"].values()):
        raise ShadowRecourseDiagnosticError("A forbidden shadow scope was enabled.")
    return config


def _load_inputs(config: Mapping[str, Any]) -> dict[str, Any]:
    behavioural = load_behavioural_config(config["behavioural_config"])
    representative = load_representative_config(behavioural["representative_config"])
    frames = load_study_frames(representative)
    shape_library = _load_shape_library(frames)
    selection = select_shadow_days(behavioural, frames, shape_library)
    manifest = build_case_manifest(behavioural, selection)
    selected = manifest[manifest["case_id"].eq(config["case_id"])]
    if len(selected) != 1 or bool(selected.iloc[0]["final_test_case"]):
        raise ShadowRecourseDiagnosticError("Frozen non-final shadow case is unavailable.")
    overlay, overlay_manifests = build_shadow_overlay(
        behavioural, frames, shape_library, selection
    )
    shadow_frames = replace(frames, qh_overlay=overlay)
    bundle, actual = build_price_bundles(
        shadow_frames,
        week_id=str(config["day_id"]),
        delivery_day=date.fromisoformat(str(config["delivery_day"])),
        arm=str(config["arm"]),
        scenario_count=10,
    )
    return {
        "behavioural": behavioural,
        "representative": representative,
        "selection": selection,
        "overlay_manifests": overlay_manifests,
        "manifest_row": selected.iloc[0].to_dict(),
        "bundle": bundle,
        "actual": actual,
    }


def classify_shadow_recourse(
    *,
    exact_infeasible: bool,
    nearest_complete_feasible: bool,
    outside_quantity_envelope_count: int,
    minimum_deviation_mwh: float,
) -> dict[str, Any]:
    path_splicing = bool(
        exact_infeasible
        and nearest_complete_feasible
        and outside_quantity_envelope_count == 0
        and minimum_deviation_mwh > 1e-6
    )
    return {
        "classification": (
            "structural_path_splicing_inside_quantity_envelope"
            if path_splicing
            else "incomplete_or_other"
        ),
        "implementation_or_contract_error": False,
        "bid_step_canonicalisation_error": False,
        "structural_path_splicing": path_splicing,
        "requires_methodological_decision": path_splicing,
        "physical_bound_change_made": False,
        "robust_bid_or_imbalance_change_made": False,
    }


def prepare_shadow_recourse_diagnostic(
    config_path: str | Path = SHADOW_RECOURSE_CONFIG,
    *,
    run_id: str,
    resume: bool = False,
) -> dict[str, Any]:
    path = _resolve(config_path)
    config = load_shadow_recourse_config(path)
    inputs = _load_inputs(config)
    output = _resolve(config["output_root"]) / run_id
    if output.exists() and any(output.iterdir()) and not resume:
        raise ShadowRecourseDiagnosticError("Output exists; use resume or a new run id.")
    output.mkdir(parents=True, exist_ok=True)
    declaration = {
        "output_root": output.relative_to(REPO_ROOT).as_posix(),
        "expected_approximate_size_mb": config["outputs"]["expected_approximate_size_mb"],
        "new_planning_model_builds": 1,
        "diagnostic_recourse_model_builds": 4,
        "expected_optimisation_calls": 6,
        "scenario_count": 10,
        "output_policy": "minimal",
        "run_class": "diagnostic_validation",
        "lineage_role": config["lineage_role"],
        "final_week_matrix_authorized_or_scheduled": False,
    }
    _write_json(output / "output_declaration.json", declaration)
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    parent = _resolve(config["parent_run_root"]) / "gate_summary.json"
    _write_json(
        output / "input_manifest.json",
        {
            "config_sha256": _sha256(path),
            "parent_gate_summary": parent.relative_to(REPO_ROOT).as_posix(),
            "parent_gate_summary_sha256": _sha256(parent),
            "bundle_actual_sha256": _bundle_hash(inputs["bundle"], inputs["actual"]),
            "selected_shadow_case": inputs["manifest_row"],
            "final_weeks_used": False,
        },
    )
    support = _scenario_support_rows(10, inputs["bundle"], inputs["actual"])
    _write_csv(output / "scenario_support.csv", support)
    _write_json(
        output / "code_version.json",
        {"module_sha256": _sha256(Path(__file__)), "config_sha256": _sha256(path)},
    )
    return {"config": config, "inputs": inputs, "output": output, "declaration": declaration}


def run_shadow_recourse_diagnostics(
    config_path: str | Path = SHADOW_RECOURSE_CONFIG,
    *,
    run_id: str,
    resume: bool = False,
) -> dict[str, Any]:
    prepared = prepare_shadow_recourse_diagnostic(
        config_path, run_id=run_id, resume=resume
    )
    config = prepared["config"]
    inputs = prepared["inputs"]
    output: Path = prepared["output"]
    bundle, actual = inputs["bundle"], inputs["actual"]
    context = _base_context_config(
        inputs["representative"], market_granularity="quarterhour", horizon_hours=24
    )
    state = SteelRollingState(
        episode_id=str(config["case_id"]), configuration_id=C1_CONFIGURATION
    )
    plan_cache = output / "plan_s10.json.gz"
    input_hash = _bundle_hash(bundle, actual)
    if resume and plan_cache.exists():
        plan = _plan_from_payload(_read_gzip_json(plan_cache), input_hash)
        plan.solver["planning_cache_reused"] = True
    else:
        plan = solve_grouped_da_bid_plan(
            context,
            C1_CONFIGURATION,
            bundle,
            state,
            "QH-S10",
            audit_future_paths=True,
        )
        plan.solver["planning_cache_reused"] = False
        _write_gzip_json(plan_cache, _plan_payload(plan, input_hash))
    clearing = clear_hourly_da_bids(plan.bids, actual)
    cleared = np.asarray(
        [float(row["cleared_energy_mwh"]) for row in clearing.hourly], dtype=float
    )
    paths = _scenario_import_paths(plan)
    path_values = paths.to_numpy(dtype=float)
    clipped, lower, upper = quantity_envelope_clip(cleared, path_values)
    outside = int(
        np.sum((cleared < lower - 1e-6) | (cleared > upper + 1e-6))
    )
    nearest_index = int(
        np.argmin(np.sqrt(np.mean((path_values - cleared) ** 2, axis=1)))
    )
    nearest_path = path_values[nearest_index]
    nearest_id = str(paths.index[nearest_index])
    nearest_rmse = float(np.sqrt(np.mean((nearest_path - cleared) ** 2)))
    checks = _plan_contract_checks(10, plan, bundle, actual, cleared, paths)
    exact_model = _build_recourse_model(
        context, state, cleared, allow_deviation=False
    )
    checks.append(
        {
            "check_id": "exact_cleared_quantity_injection",
            "status": "pass" if np.array_equal(_constraint_rhs(exact_model), cleared) else "fail",
            "observed": hashlib.sha256(_constraint_rhs(exact_model).tobytes()).hexdigest(),
            "expected": hashlib.sha256(cleared.tobytes()).hexdigest(),
            "hard_gate": True,
            "scenario_count": 10,
        }
    )
    exact, iis_rows = _direct_feasibility_and_iis(
        exact_model, output=output, scenario_count=10, diagnostic_id="S10_shadow_exact"
    )
    nearest, nearest_iis = _direct_feasibility_and_iis(
        _build_recourse_model(
            context, state, nearest_path, allow_deviation=False
        ),
        output=output,
        scenario_count=10,
        diagnostic_id="S10_shadow_nearest_complete_control",
    )
    iis_rows.extend(nearest_iis)
    clipped_result, clipped_iis = _direct_feasibility_and_iis(
        _build_recourse_model(context, state, clipped, allow_deviation=False),
        output=output,
        scenario_count=10,
        diagnostic_id="S10_shadow_envelope_clip",
    )
    clipped_result["clip_absolute_change_mwh"] = float(
        np.sum(np.abs(clipped - cleared))
    )
    iis_rows.extend(clipped_iis)
    deviation, deviation_rows, deviation_solver = _minimum_recourse_deviation(
        context,
        state,
        cleared,
        actual,
        lower,
        upper,
        scenario_count=10,
    )
    classification = classify_shadow_recourse(
        exact_infeasible=bool(exact["proven_infeasible"]),
        nearest_complete_feasible=bool(nearest["proven_feasible"]),
        outside_quantity_envelope_count=outside,
        minimum_deviation_mwh=float(deviation["total_absolute_deviation_mwh"]),
    )
    classification.update(
        {
            "outside_quantity_envelope_count": outside,
            "nearest_complete_scenario_id": nearest_id,
            "nearest_complete_scenario_rmse_mwh": nearest_rmse,
            "actual_price_outside_s10_support_count": int(
                sum(row["outside_price_support"] for row in _scenario_support_rows(10, bundle, actual))
            ),
            "minimum_absolute_recourse_deviation_mwh": deviation[
                "total_absolute_deviation_mwh"
            ],
            "minimum_recourse_affected_qh_count": deviation["affected_qh_count"],
            "final_regime_weeks_used": False,
        }
    )
    clearing_rows = [
        {
            "market_interval_index": index,
            "target_timestamp_utc": row["target_timestamp_utc"],
            "realised_price_eur_per_mwh": row["realised_price_eur_per_mwh"],
            "cleared_import_mwh": cleared[index],
            "scenario_import_min_mwh": lower[index],
            "scenario_import_max_mwh": upper[index],
            "outside_quantity_envelope": bool(
                cleared[index] < lower[index] - 1e-6
                or cleared[index] > upper[index] + 1e-6
            ),
            "nearest_complete_scenario_id": nearest_id,
            "nearest_complete_scenario_import_mwh": nearest_path[index],
        }
        for index, row in enumerate(clearing.hourly)
    ]
    method_rows = [
        {
            "method": "bounded_imbalance_or_recourse_slack",
            "diagnostic_evidence": deviation["total_absolute_deviation_mwh"],
            "units": "MWh",
            "status": "not_promoted_requires_method_decision",
            "tradeoff": "Restores feasibility but changes settlement/recourse semantics.",
        },
        {
            "method": "robust_or_path_feasible_bid_coupling",
            "diagnostic_evidence": "exact path infeasible while nearest full scenario path is feasible",
            "units": "categorical",
            "status": "not_implemented_requires_method_decision",
            "tradeoff": "Preserves physical feasibility but expands the stochastic MILP and runtime.",
        },
        {
            "method": "scenario_support_expansion_S30",
            "diagnostic_evidence": "not rerun; S10 failure occurs inside every interval envelope",
            "units": "categorical",
            "status": "not_sufficiently_justified",
            "tradeoff": "May reduce path gaps but cannot guarantee recourse and increases runtime.",
        },
    ]
    _write_csv(output / "contract_checks.csv", checks)
    _write_csv(output / "clearing_diagnostics.csv", clearing_rows)
    _write_csv(output / "redispatch_feasibility.csv", [exact, nearest, clipped_result, deviation])
    _write_csv(output / "iis_members.csv", iis_rows)
    _write_csv(output / "minimum_deviation_intervals.csv", deviation_rows)
    _write_csv(output / "method_comparison.csv", method_rows)
    _write_json(
        output / "solver_diagnostics.json",
        {
            "planning": plan.solver,
            "minimum_deviation": deviation_solver,
            "exact_model_stats": collect_model_stats(exact_model).__dict__,
        },
    )
    _write_json(output / "cause_classification.json", classification)
    summary = {
        "status": (
            "complete_methodological_decision_required"
            if classification["requires_methodological_decision"]
            else "incomplete"
        ),
        "decision": (
            "METHOD_DECISION_REQUIRED"
            if classification["requires_methodological_decision"]
            else "INCOMPLETE"
        ),
        "classification": classification["classification"],
        "synthetic_gate_pass": True,
        "shadow_gate_pass": False,
        "final_regime_weeks_used": False,
        "output_policy": "minimal",
        "run_class": "diagnostic_validation",
        "lineage_role": config["lineage_role"],
    }
    _write_json(output / "run_summary.json", summary)
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is one non-final shadow day, not final-regime or annual evidence.\n"
        "- Minimum recourse deviation is diagnostic only; no imbalance or emergency import was enabled.\n"
        "- S30 and robust bid coupling were not implemented or promoted.\n",
        encoding="utf-8",
    )
    return {"output": str(output), "summary": summary, "classification": classification}


__all__ = [
    "SHADOW_RECOURSE_CONFIG",
    "ShadowRecourseDiagnosticError",
    "classify_shadow_recourse",
    "load_shadow_recourse_config",
    "prepare_shadow_recourse_diagnostic",
    "run_shadow_recourse_diagnostics",
]
