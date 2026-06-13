from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

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


ARTIFACT_ID = "hourly_lear_strict_donly_1092_repaired_support_tail_calibrated_v1"
DELIVERY_DATE = "2025-07-11"
OUTPUT_POLICY = "minimal"
RUN_CLASS = "diagnostic"
LINEAGE_ROLE = "diagnostic"
TOLERANCE = 1e-6


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _repo_rel(path: Path | str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        return str(candidate).replace("\\", "/")
    try:
        return str(candidate.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(candidate).replace("\\", "/")


def _relativize_paths(payload: Any) -> Any:
    if isinstance(payload, dict):
        adjusted: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                adjusted[key] = _relativize_paths(value)
            elif isinstance(value, str) and (":\\" in value or value.startswith("\\\\")):
                adjusted[key] = _repo_rel(value)
            else:
                adjusted[key] = value
        return adjusted
    if isinstance(payload, list):
        return [_relativize_paths(item) for item in payload]
    return payload


def _fingerprint_file(path: Path) -> dict[str, Any]:
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": _repo_rel(path),
        "size_bytes": int(stat.st_size),
        "sha256": digest,
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _validate_da_slice(frame: pd.DataFrame) -> dict[str, Any]:
    local_dates = sorted(frame["delivery_day"].astype(str).unique().tolist())
    scenario_count = int(frame["scenario_id"].nunique())
    rows_per_scenario = frame.groupby("scenario_id").size()
    origins = sorted(frame["forecast_origin_utc"].astype(str).unique().tolist())
    return {
        "artifact_id": ARTIFACT_ID,
        "row_count": int(len(frame)),
        "scenario_count": scenario_count,
        "delivery_dates_present": local_dates,
        "has_exact_delivery_date": local_dates == [DELIVERY_DATE],
        "rows_per_scenario_min": int(rows_per_scenario.min()) if not rows_per_scenario.empty else 0,
        "rows_per_scenario_max": int(rows_per_scenario.max()) if not rows_per_scenario.empty else 0,
        "origin_count": int(len(origins)),
        "origins": origins,
        "is_24h_block": bool(
            not rows_per_scenario.empty
            and int(rows_per_scenario.min()) == 24
            and int(rows_per_scenario.max()) == 24
        ),
        "is_d_only_compatible": bool(
            local_dates == [DELIVERY_DATE]
            and not rows_per_scenario.empty
            and int(rows_per_scenario.min()) == 24
            and int(rows_per_scenario.max()) == 24
            and len(origins) == 1
        ),
    }


def _validate_mfrr_slice(mfrr_input: Any) -> dict[str, Any]:
    probability_check = (
        mfrr_input.pilot_rows.groupby(["delivery_date_local", "direction"], as_index=False)["scenario_probability"]
        .sum()
        .rename(columns={"scenario_probability": "probability_sum"})
    )
    timing_local = pd.to_datetime(mfrr_input.pilot_rows["forecast_origin_local"], errors="raise")
    return {
        "pilot_rows": int(len(mfrr_input.pilot_rows)),
        "candidate_rows": int(len(mfrr_input.candidate_summary)),
        "acceptance_rows": int(len(mfrr_input.acceptance_table)),
        "probability_sums": probability_check.to_dict(orient="records"),
        "expected_revenue_coefficient_min": float(mfrr_input.candidate_summary["expected_revenue_coefficient"].min()),
        "expected_revenue_coefficient_max": float(mfrr_input.candidate_summary["expected_revenue_coefficient"].max()),
        "timing_local_hours": sorted(timing_local.dt.hour.unique().tolist()),
    }


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return None


def _collect_mode_summary(mode: str, result: Any) -> dict[str, Any]:
    dispatch = result.dispatch.copy()
    objective_components = result.objective_components.copy() if result.objective_components is not None else pd.DataFrame()
    mfrr_summary = result.mfrr_capacity_summary.copy() if result.mfrr_capacity_summary is not None else pd.DataFrame()

    objective_value = _safe_float(result.solver.objective_value)
    production_kg = float(dispatch["H_comp_kg"].sum()) if not dispatch.empty else 0.0
    shortfall_kg = float(dispatch["shortfall_kg"].iloc[0]) if not dispatch.empty else 0.0
    electrolyser_mwh = float(dispatch["P_el_mw"].sum())
    compressor_mwh = float(dispatch["P_comp_mw"].sum())

    selected = pd.DataFrame()
    if not mfrr_summary.empty:
        selected = mfrr_summary[mfrr_summary["selected_bid_candidate"].astype(float) > 0.5].copy()

    selected_candidates = []
    if not selected.empty:
        selected_candidates = selected[
            [
                "delivery_date_local",
                "direction",
                "candidate_id",
                "candidate_price",
                "expected_acceptance_probability",
                "offered_capacity_mw",
                "offered_capacity_total_mw",
                "expected_capacity_revenue_eur",
                "min_deliverability_margin_mw",
            ]
        ].to_dict(orient="records")

    offered_up = 0.0
    offered_down = 0.0
    if not mfrr_summary.empty:
        offers = (
            mfrr_summary.groupby("direction", as_index=False)["offered_capacity_total_mw"]
            .max()
            .set_index("direction")["offered_capacity_total_mw"]
            .to_dict()
        )
        offered_up = float(offers.get("Up", 0.0))
        offered_down = float(offers.get("Down", 0.0))

    expected_mfrr_revenue = (
        float(objective_components["expected_mfrr_capacity_revenue_eur"].iloc[0])
        if not objective_components.empty
        else 0.0
    )
    expected_operational_net_cost = (
        float(objective_components["expected_operational_net_cost_eur"].iloc[0])
        if not objective_components.empty
        else None
    )
    cvar_term = float(objective_components["cvar_term_eur"].iloc[0]) if not objective_components.empty else None

    computed_mfrr_revenue = (
        float(mfrr_summary["expected_capacity_revenue_eur"].sum())
        if not mfrr_summary.empty
        else 0.0
    )
    zero_volume_selected_candidates = []
    if not selected.empty:
        nuisance = selected[selected["offered_capacity_mw"].astype(float).abs() <= TOLERANCE]
        zero_volume_selected_candidates = nuisance["candidate_id"].astype(str).tolist()

    return {
        "mode": mode,
        "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "objective_value_eur": objective_value,
        "production_kg": production_kg,
        "shortfall_kg": shortfall_kg,
        "total_electrolyser_consumption_mwh": electrolyser_mwh,
        "total_compressor_consumption_mwh": compressor_mwh,
        "expected_operational_net_cost_eur": expected_operational_net_cost,
        "expected_mfrr_capacity_revenue_eur": expected_mfrr_revenue,
        "computed_mfrr_capacity_revenue_eur": computed_mfrr_revenue,
        "cvar_term_eur": cvar_term,
        "offered_capacity_up_mw": offered_up,
        "offered_capacity_down_mw": offered_down,
        "selected_candidates": selected_candidates,
        "zero_volume_selected_candidates": zero_volume_selected_candidates,
        "objective_components": objective_components,
        "mfrr_capacity_summary": mfrr_summary,
        "dispatch": dispatch,
        "model_stats": asdict(result.model_stats),
        "debug_info": result.debug_info,
    }


def main() -> int:
    started = _now_utc()
    config_path = REPO_ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "configs" / "base_hydrogen.yaml"
    config = load_hydrogen_config(config_path)
    audit_solver_settings = replace(config.solver, mip_gap=min(float(config.solver.mip_gap), 1e-6))

    run_id = f"{started.strftime('%Y%m%d_%H%M%S')}_mfrr_capacity_optionality_dominance_audit_v1"
    output_root = (config.run_output_root / run_id).resolve()
    output_root.mkdir(parents=True, exist_ok=False)

    request = InputSliceRequest(
        artifact_id=ARTIFACT_ID,
        start_local_date=DELIVERY_DATE,
        end_local_date=DELIVERY_DATE,
        period_mode="custom_dates",
        dataset_split="test",
    )
    resolved_slice = resolve_input_slice(config, request=request, output_policy_name=OUTPUT_POLICY, use_cache=True)
    da_validation = _validate_da_slice(resolved_slice.scenarios)
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
        raise ValueError(f"Unexpected one-day mFRR input dimensions: {mfrr_validation}")

    baseline_result = solve_stochastic_dispatch(
        day_scenarios=resolved_slice.scenarios,
        hydrogen=config.hydrogen_system,
        economics=config.economics,
        solver_settings=audit_solver_settings,
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
        mfrr_capacity_pilot=None,
        solver_log_path=str(output_root / "solver_log_baseline.txt"),
        debug_options={"collect_objective_audit": True},
    )
    forced_zero_result = solve_stochastic_dispatch(
        day_scenarios=resolved_slice.scenarios,
        hydrogen=config.hydrogen_system,
        economics=config.economics,
        solver_settings=audit_solver_settings,
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
        mfrr_capacity_pilot=mfrr_input,
        solver_log_path=str(output_root / "solver_log_mfrr_forced_zero.txt"),
        debug_options={"collect_objective_audit": True, "force_mfrr_offer_zero": True},
    )
    optional_result = solve_stochastic_dispatch(
        day_scenarios=resolved_slice.scenarios,
        hydrogen=config.hydrogen_system,
        economics=config.economics,
        solver_settings=audit_solver_settings,
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
        mfrr_capacity_pilot=mfrr_input,
        solver_log_path=str(output_root / "solver_log_mfrr_optional.txt"),
        debug_options={"collect_objective_audit": True},
    )

    baseline = _collect_mode_summary("no_mfrr_baseline", baseline_result)
    forced_zero = _collect_mode_summary("mfrr_forced_zero", forced_zero_result)
    optional = _collect_mode_summary("mfrr_optional", optional_result)

    objective_sense = "minimize"
    dominance_inequality = "mfrr_optional objective <= mfrr_forced_zero objective <= no_mfrr_baseline objective"

    forced_zero_matches_baseline = (
        abs((forced_zero["objective_value_eur"] or 0.0) - (baseline["objective_value_eur"] or 0.0)) <= TOLERANCE
        and abs(forced_zero["production_kg"] - baseline["production_kg"]) <= TOLERANCE
        and abs(forced_zero["shortfall_kg"] - baseline["shortfall_kg"]) <= TOLERANCE
        and abs(forced_zero["total_electrolyser_consumption_mwh"] - baseline["total_electrolyser_consumption_mwh"]) <= TOLERANCE
        and abs(forced_zero["total_compressor_consumption_mwh"] - baseline["total_compressor_consumption_mwh"]) <= TOLERANCE
    )
    optional_dominates_forced_zero = (
        (optional["objective_value_eur"] or 0.0) <= (forced_zero["objective_value_eur"] or 0.0) + TOLERANCE
    )
    dominance_passes = forced_zero_matches_baseline and optional_dominates_forced_zero

    revenue_zero_when_forced_zero = abs(forced_zero["expected_mfrr_capacity_revenue_eur"]) <= TOLERANCE
    revenue_matches_computed_optional = (
        abs(optional["expected_mfrr_capacity_revenue_eur"] - optional["computed_mfrr_capacity_revenue_eur"]) <= TOLERANCE
    )
    revenue_matches_computed_forced_zero = (
        abs(forced_zero["expected_mfrr_capacity_revenue_eur"] - forced_zero["computed_mfrr_capacity_revenue_eur"]) <= TOLERANCE
    )

    objective_component_consistency = {
        "baseline_vs_forced_zero_operational_net_cost_match": abs(
            (baseline["expected_operational_net_cost_eur"] or 0.0) - (forced_zero["expected_operational_net_cost_eur"] or 0.0)
        ) <= TOLERANCE,
        "baseline_vs_forced_zero_objective_match": abs(
            (baseline["objective_value_eur"] or 0.0) - (forced_zero["objective_value_eur"] or 0.0)
        ) <= TOLERANCE,
        "baseline_vs_forced_zero_cvar_match": abs(
            (baseline["cvar_term_eur"] or 0.0) - (forced_zero["cvar_term_eur"] or 0.0)
        ) <= TOLERANCE,
        "operational_cost_difference_baseline_minus_optional_eur": (
            (baseline["expected_operational_net_cost_eur"] or 0.0) - (optional["expected_operational_net_cost_eur"] or 0.0)
        ),
    }

    production_target_interpretation = {
        "production_target_mode": "current_soft_target",
        "daily_target_kg": float(config.economics.daily_target_kg),
        "shortfall_penalty_eur_per_kg": float(config.economics.shortfall_penalty_eur_per_kg),
        "hydrogen_sale_price_eur_per_kg": float(config.economics.h2_sale_price_eur_per_kg),
        "surplus_production_treatment": (
            "rewarded via hydrogen sale revenue because production above the lower-bound target remains in the revenue term"
        ),
    }
    mode_equivalence = {
        "delivery_date_local": DELIVERY_DATE,
        "artifact_id": ARTIFACT_ID,
        "scenario_count": da_validation["scenario_count"],
        "daily_target_kg": float(config.economics.daily_target_kg),
        "hydrogen_sale_price_eur_per_kg": float(config.economics.h2_sale_price_eur_per_kg),
        "shortfall_penalty_eur_per_kg": float(config.economics.shortfall_penalty_eur_per_kg),
        "risk_gamma": 0.0,
        "risk_alpha": float(config.risk.alpha),
        "solver_package_preference": str(config.solver.package_preference),
        "solver_name": str(config.solver.solver_name),
        "time_limit_seconds": float(audit_solver_settings.time_limit_seconds),
        "mip_gap": float(audit_solver_settings.mip_gap),
        "same_base_model_except_mfrr": True,
    }

    run_summary = {
        "run_id": run_id,
        "timestamp_utc": _iso(started),
        "status": "completed",
        "objective_sense": objective_sense,
        "dominance_inequality": dominance_inequality,
        "dominance_passes": dominance_passes,
        "forced_zero_matches_baseline": forced_zero_matches_baseline,
        "optional_dominates_forced_zero": optional_dominates_forced_zero,
        "diagnosis": "optionality/formulation bug" if not dominance_passes else "pass",
        "limitations": [
            "One-day audit only; not a weekly stochastic result.",
            "No activation is modelled; the audit only checks capacity optionality and objective accounting in the base schedule.",
            "Forced-zero mode is implemented as diagnostic equality constraints on mFRR offered-capacity variables only.",
            "This audit tightens the solver MIP gap to enforce a stronger dominance check than the default smoke setting.",
        ],
    }
    _write_json(output_root / "run_summary.json", run_summary)

    resolved_config_payload = {
        "base_config_path": _repo_rel(config.config_path),
        "artifact_id": ARTIFACT_ID,
        "delivery_date": DELIVERY_DATE,
        "output_policy": OUTPUT_POLICY,
        "run_class": RUN_CLASS,
        "lineage_role": LINEAGE_ROLE,
        "risk_gamma_used": 0.0,
        "apply_terminal_value": True,
        "audit_modes": ["no_mfrr_baseline", "mfrr_forced_zero", "mfrr_optional"],
    }
    _write_yaml(output_root / "resolved_config.yaml", resolved_config_payload)

    input_manifest = {
        "da_artifact_id": ARTIFACT_ID,
        "da_scenario_catalog": _fingerprint_file(config.models.scenario_catalog),
        "da_config": _fingerprint_file(config.config_path),
        "mfrr_export": _fingerprint_file(mfrr_input.export_path),
        "selected_period": {"start_local_date": DELIVERY_DATE, "end_local_date": DELIVERY_DATE},
        "da_cache_status": resolved_slice.cache_status,
        "da_source_fingerprints": resolved_slice.source_fingerprints,
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

    mode_summary_rows = []
    objective_audit_rows = []
    for payload in [baseline, forced_zero, optional]:
        mode_summary_rows.append(
            {
                "mode": payload["mode"],
                "solver_status": payload["solver_status"],
                "termination_condition": payload["termination_condition"],
                "objective_value_eur": payload["objective_value_eur"],
                "expected_operational_net_cost_eur": payload["expected_operational_net_cost_eur"],
                "expected_mfrr_capacity_revenue_eur": payload["expected_mfrr_capacity_revenue_eur"],
                "computed_mfrr_capacity_revenue_eur": payload["computed_mfrr_capacity_revenue_eur"],
                "production_kg": payload["production_kg"],
                "shortfall_kg": payload["shortfall_kg"],
                "total_electrolyser_consumption_mwh": payload["total_electrolyser_consumption_mwh"],
                "total_compressor_consumption_mwh": payload["total_compressor_consumption_mwh"],
                "offered_capacity_up_mw": payload["offered_capacity_up_mw"],
                "offered_capacity_down_mw": payload["offered_capacity_down_mw"],
                "zero_volume_selected_candidates": "|".join(payload["zero_volume_selected_candidates"]),
            }
        )
        debug_info = payload.get("debug_info") or {}
        for objective_info in debug_info.get("active_objectives", []):
            objective_audit_rows.append(
                {
                    "mode": payload["mode"],
                    "active_objective_count": debug_info.get("active_objective_count"),
                    "objective_name": objective_info.get("name"),
                    "objective_sense": objective_info.get("sense"),
                    "pyomo_objective_value_eur": objective_info.get("value"),
                    "reported_objective_value_eur": debug_info.get("reported_objective_value_eur"),
                    "objective_value_matches_reported": abs(
                        float(objective_info.get("value") or 0.0) - float(debug_info.get("reported_objective_value_eur") or 0.0)
                    ) <= TOLERANCE,
                    "force_mfrr_offer_zero": bool(debug_info.get("force_mfrr_offer_zero", False)),
                    "gurobi_best_bound": (debug_info.get("solver_diagnostics") or {}).get("gurobi_best_bound"),
                    "gurobi_incumbent": (debug_info.get("solver_diagnostics") or {}).get("gurobi_incumbent"),
                    "gurobi_node_count": (debug_info.get("solver_diagnostics") or {}).get("gurobi_node_count"),
                    "gurobi_iteration_count": (debug_info.get("solver_diagnostics") or {}).get("gurobi_iteration_count"),
                }
            )
    pd.DataFrame(mode_summary_rows).to_csv(output_root / "mode_summary.csv", index=False)
    pd.DataFrame(objective_audit_rows).to_csv(output_root / "active_objective_audit.csv", index=False)

    objective_comparison_rows = []
    for payload in [baseline, forced_zero, optional]:
        objective_comparison_rows.append(
            {
                "mode": payload["mode"],
                "objective_value_eur": payload["objective_value_eur"],
                "expected_operational_net_cost_eur": payload["expected_operational_net_cost_eur"],
                "expected_mfrr_capacity_revenue_eur": payload["expected_mfrr_capacity_revenue_eur"],
                "computed_mfrr_capacity_revenue_eur": payload["computed_mfrr_capacity_revenue_eur"],
                "cvar_term_eur": payload["cvar_term_eur"],
            }
        )
    pd.DataFrame(objective_comparison_rows).to_csv(output_root / "objective_component_comparison.csv", index=False)

    optional["mfrr_capacity_summary"].to_csv(output_root / "mfrr_optional_capacity_summary.csv", index=False)
    forced_zero["mfrr_capacity_summary"].to_csv(output_root / "mfrr_forced_zero_capacity_summary.csv", index=False)

    audit_summary = {
        "objective_sense": objective_sense,
        "dominance_inequality": dominance_inequality,
        "input_consistency": {
            "delivery_date_local": DELIVERY_DATE,
            "artifact_id": ARTIFACT_ID,
            "same_da_slice_all_modes": True,
            "da_validation": da_validation,
            "mfrr_validation": mfrr_validation,
        },
        "modes": {
            "no_mfrr_baseline": {
                "solver_status": baseline["solver_status"],
                "termination_condition": baseline["termination_condition"],
                "objective_value_eur": baseline["objective_value_eur"],
                "production_kg": baseline["production_kg"],
                "shortfall_kg": baseline["shortfall_kg"],
                "total_electrolyser_consumption_mwh": baseline["total_electrolyser_consumption_mwh"],
                "total_compressor_consumption_mwh": baseline["total_compressor_consumption_mwh"],
            },
            "mfrr_forced_zero": {
                "solver_status": forced_zero["solver_status"],
                "termination_condition": forced_zero["termination_condition"],
                "objective_value_eur": forced_zero["objective_value_eur"],
                "production_kg": forced_zero["production_kg"],
                "shortfall_kg": forced_zero["shortfall_kg"],
                "total_electrolyser_consumption_mwh": forced_zero["total_electrolyser_consumption_mwh"],
                "total_compressor_consumption_mwh": forced_zero["total_compressor_consumption_mwh"],
                "offered_capacity_up_mw": forced_zero["offered_capacity_up_mw"],
                "offered_capacity_down_mw": forced_zero["offered_capacity_down_mw"],
                "expected_mfrr_capacity_revenue_eur": forced_zero["expected_mfrr_capacity_revenue_eur"],
                "selected_candidates": forced_zero["selected_candidates"],
            },
            "mfrr_optional": {
                "solver_status": optional["solver_status"],
                "termination_condition": optional["termination_condition"],
                "objective_value_eur": optional["objective_value_eur"],
                "production_kg": optional["production_kg"],
                "shortfall_kg": optional["shortfall_kg"],
                "total_electrolyser_consumption_mwh": optional["total_electrolyser_consumption_mwh"],
                "total_compressor_consumption_mwh": optional["total_compressor_consumption_mwh"],
                "offered_capacity_up_mw": optional["offered_capacity_up_mw"],
                "offered_capacity_down_mw": optional["offered_capacity_down_mw"],
                "expected_mfrr_capacity_revenue_eur": optional["expected_mfrr_capacity_revenue_eur"],
                "selected_candidates": optional["selected_candidates"],
            },
        },
        "revenue_linkage": {
            "forced_zero_revenue_is_zero": revenue_zero_when_forced_zero,
            "optional_revenue_matches_summary_sum": revenue_matches_computed_optional,
            "forced_zero_revenue_matches_summary_sum": revenue_matches_computed_forced_zero,
            "candidate_selection_alone_generates_revenue": bool(
                abs(forced_zero["expected_mfrr_capacity_revenue_eur"]) > TOLERANCE
            ),
        },
        "candidate_volume_optionality": {
            "selection_constraint_form": "sum_k bid_select[d,r,k] <= 1",
            "big_m_offer_link": "offered_capacity_mw[d,r,k] <= capacity_offer_big_m_mw * bid_select[d,r,k]",
            "zero_volume_selected_candidates_forced_zero": forced_zero["zero_volume_selected_candidates"],
            "zero_capacity_is_feasible": True,
        },
        "mode_equivalence": mode_equivalence,
        "objective_component_consistency": objective_component_consistency,
        "production_target_interpretation": production_target_interpretation,
        "dominance_checks": {
            "forced_zero_matches_baseline": forced_zero_matches_baseline,
            "optional_dominates_forced_zero": optional_dominates_forced_zero,
            "dominance_passes": dominance_passes,
            "baseline_minus_forced_zero_objective_eur": (baseline["objective_value_eur"] or 0.0) - (forced_zero["objective_value_eur"] or 0.0),
            "forced_zero_minus_optional_objective_eur": (forced_zero["objective_value_eur"] or 0.0) - (optional["objective_value_eur"] or 0.0),
        },
        "activation_caveat": (
            "This audit does not validate performance under activation; it only checks optional capacity participation "
            "and base-schedule availability accounting."
        ),
        "active_objective_audit": {
            "all_modes_have_single_active_objective": all(
                int((payload.get("debug_info") or {}).get("active_objective_count", 0)) == 1
                for payload in [baseline, forced_zero, optional]
            ),
            "all_modes_objective_matches_reported": all(
                abs(
                    float(((payload.get("debug_info") or {}).get("active_objectives", [{}])[0].get("value") or 0.0))
                    - float((payload.get("debug_info") or {}).get("reported_objective_value_eur") or 0.0)
                ) <= TOLERANCE
                for payload in [baseline, forced_zero, optional]
            ),
        },
        "diagnosis": "optionality/formulation bug" if not dominance_passes else "pass",
    }
    _write_json(output_root / "dominance_audit_summary.json", audit_summary)

    warnings = [
        "One-day audit only; not a weekly stochastic result.",
        "No activation is modelled; current checks only cover capacity availability in the base schedule.",
        "Forced-zero mode is diagnostic-only and does not alter the base formulation on disk.",
    ]
    (output_root / "warnings_and_limitations.md").write_text("\n".join(f"- {item}" for item in warnings), encoding="utf-8")

    registry_entry = {
        "run_id": run_id,
        "timestamp": _iso(started),
        "domain": "optimisation",
        "market": "DA_plus_mFRR_capacity_audit",
        "pipeline_stage": "diagnostic",
        "granularity": "hourly",
        "horizon": "D_only",
        "model_family": "hydrogen_stochastic_dispatch",
        "feature_set": "not_applicable",
        "scenario_source": ARTIFACT_ID,
        "input_artifacts": [
            {"artifact_id": ARTIFACT_ID, "path": _repo_rel(config.models.scenario_catalog)},
            {"artifact_id": "nl_ir_capacity_milp_input_daily_direction_scenarios_v1", "path": _repo_rel(mfrr_input.export_path)},
        ],
        "output_root": _repo_rel(output_root),
        "output_policy": OUTPUT_POLICY,
        "run_class": RUN_CLASS,
        "lineage_role": LINEAGE_ROLE,
        "status": "completed",
        "thesis_usable": "conditional",
        "key_result": "Optional mFRR audit completed on one day with baseline, forced-zero, and optional modes.",
        "limitations": "One-day only; no activation; objective optionality audited only for 2025-07-11.",
        "archive_location": None,
        "delete_after": None,
        "git_commit": None,
    }
    _write_json(output_root / "registry_entry.json", registry_entry)

    print(f"RUN_DIR={output_root}")
    print(f"OBJECTIVE_SENSE={objective_sense}")
    print(f"BASELINE_OBJECTIVE_EUR={baseline['objective_value_eur']}")
    print(f"FORCED_ZERO_OBJECTIVE_EUR={forced_zero['objective_value_eur']}")
    print(f"OPTIONAL_OBJECTIVE_EUR={optional['objective_value_eur']}")
    print(f"FORCED_ZERO_MATCHES_BASELINE={forced_zero_matches_baseline}")
    print(f"OPTIONAL_DOMINATES_FORCED_ZERO={optional_dominates_forced_zero}")
    print(f"OPTIONAL_EXPECTED_MFRR_REVENUE_EUR={optional['expected_mfrr_capacity_revenue_eur']}")
    print(f"FORCED_ZERO_EXPECTED_MFRR_REVENUE_EUR={forced_zero['expected_mfrr_capacity_revenue_eur']}")
    print(f"DIAGNOSIS={audit_summary['diagnosis']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
