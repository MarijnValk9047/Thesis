from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import asdict
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

from hydrogen.optimisation.input_resolver import InputSliceRequest, resolve_input_slice  # noqa: E402
from hydrogen.optimisation_model import solve_stochastic_dispatch  # noqa: E402
from hydrogen.plant_parameters import load_hydrogen_config  # noqa: E402


ARTIFACT_ID = "hourly_lear_strict_donly_1092_repaired_support_tail_calibrated_v1"
DELIVERY_DATE = "2025-07-11"
OUTPUT_POLICY = "minimal"
RUN_CLASS = "smoke"
LINEAGE_ROLE = "diagnostic"
MFRR_RUN_DIR = REPO_ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "runs" / "20260606_195136_mfrr_capacity_one_day_smoke_v1"


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


def _load_previous_mfrr_run() -> dict[str, Any]:
    if not MFRR_RUN_DIR.exists():
        raise FileNotFoundError(f"Previous mFRR smoke-test run folder is missing: {MFRR_RUN_DIR}")
    run_summary = json.loads((MFRR_RUN_DIR / "run_summary.json").read_text(encoding="utf-8"))
    objective_components = pd.read_csv(MFRR_RUN_DIR / "objective_components.csv")
    metrics_summary = pd.read_csv(MFRR_RUN_DIR / "metrics_summary.csv")
    mfrr_capacity_summary = pd.read_csv(MFRR_RUN_DIR / "mfrr_capacity_summary.csv")
    return {
        "run_summary": run_summary,
        "objective_components": objective_components,
        "metrics_summary": metrics_summary,
        "mfrr_capacity_summary": mfrr_capacity_summary,
    }


def main() -> int:
    started = _now_utc()
    config_path = REPO_ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "configs" / "base_hydrogen.yaml"
    config = load_hydrogen_config(config_path)
    previous = _load_previous_mfrr_run()

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

    run_id = f"{started.strftime('%Y%m%d_%H%M%S')}_mfrr_capacity_one_day_baseline_compare_v1"
    output_root = (config.run_output_root / run_id).resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    solver_log_path = output_root / "solver_log.txt"

    warnings = [
        "One-day baseline comparison only; not a coherent weekly stochastic pilot.",
        "No-mFRR baseline uses the same DA slice and omits the mFRR capacity block entirely.",
        "Physical schedule comparison is limited by the previously saved mFRR run bundle, which does not include full dispatch totals.",
    ]

    result = solve_stochastic_dispatch(
        day_scenarios=resolved_slice.scenarios,
        hydrogen=config.hydrogen_system,
        economics=config.economics,
        solver_settings=config.solver,
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
        solver_log_path=str(solver_log_path),
    )

    dispatch = result.dispatch.copy()
    status_text = str(result.solver.status)
    termination = str(result.solver.termination_condition) if result.solver.termination_condition is not None else None
    objective_value = float(result.solver.objective_value) if result.solver.objective_value is not None else None
    production_kg = float(dispatch["H_comp_kg"].sum()) if not dispatch.empty else float("nan")
    shortfall_kg = float(dispatch["shortfall_kg"].iloc[0]) if not dispatch.empty else float("nan")
    total_electrolyser_consumption_mwh = float(dispatch["P_el_mw"].sum() * config.delta_t_hours) if not dispatch.empty else float("nan")
    total_compressor_consumption_mwh = float(dispatch["P_comp_mw"].sum() * config.delta_t_hours) if not dispatch.empty else float("nan")

    baseline_objective_components = result.objective_components.copy() if result.objective_components is not None else pd.DataFrame()
    baseline_expected_mfrr_capacity_revenue = (
        float(baseline_objective_components["expected_mfrr_capacity_revenue_eur"].iloc[0])
        if not baseline_objective_components.empty
        else 0.0
    )

    mfrr_run_summary = previous["run_summary"]
    mfrr_objective_components = previous["objective_components"]
    mfrr_metrics_summary = previous["metrics_summary"]
    mfrr_expected_revenue = float(mfrr_objective_components["expected_mfrr_capacity_revenue_eur"].iloc[0])
    mfrr_objective = float(mfrr_run_summary["objective_value_eur"])
    mfrr_production_kg = float(mfrr_run_summary["production_kg"])
    mfrr_shortfall_kg = float(mfrr_run_summary["shortfall_kg"])

    objective_uplift_eur = objective_value - mfrr_objective if objective_value is not None else None
    production_difference_kg = production_kg - mfrr_production_kg
    shortfall_difference_kg = shortfall_kg - mfrr_shortfall_kg
    expected_revenue_difference_eur = baseline_expected_mfrr_capacity_revenue - mfrr_expected_revenue

    operational_net_cost_baseline = (
        float(baseline_objective_components["expected_operational_net_cost_eur"].iloc[0])
        if not baseline_objective_components.empty
        else None
    )
    operational_net_cost_mfrr = float(mfrr_objective_components["expected_operational_net_cost_eur"].iloc[0])
    operational_net_cost_difference_eur = (
        operational_net_cost_baseline - operational_net_cost_mfrr
        if operational_net_cost_baseline is not None
        else None
    )
    objective_change_explained_by_mfrr_revenue = (
        objective_uplift_eur is not None and abs(objective_uplift_eur - mfrr_expected_revenue) <= 1e-6
    )
    schedule_materially_changed = not (
        abs(production_difference_kg) <= 1e-9
        and abs(shortfall_difference_kg) <= 1e-9
        and objective_change_explained_by_mfrr_revenue
    )

    resolved_config_payload = {
        "base_config_path": _repo_rel(config.config_path),
        "artifact_id": ARTIFACT_ID,
        "delivery_date": DELIVERY_DATE,
        "output_policy": OUTPUT_POLICY,
        "run_class": RUN_CLASS,
        "lineage_role": LINEAGE_ROLE,
        "risk_gamma_used": 0.0,
        "apply_terminal_value": True,
        "mfrr_capacity_pilot_enabled": False,
        "comparison_target_run": _repo_rel(MFRR_RUN_DIR),
    }
    _write_yaml(output_root / "resolved_config.yaml", resolved_config_payload)

    input_manifest = {
        "da_artifact_id": ARTIFACT_ID,
        "da_scenario_catalog": _fingerprint_file(config.models.scenario_catalog),
        "da_config": _fingerprint_file(config.config_path),
        "selected_period": {"start_local_date": DELIVERY_DATE, "end_local_date": DELIVERY_DATE},
        "da_cache_status": resolved_slice.cache_status,
        "da_source_fingerprints": resolved_slice.source_fingerprints,
        "comparison_run_root": _repo_rel(MFRR_RUN_DIR),
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

    run_summary = {
        "run_id": run_id,
        "timestamp_utc": _iso(started),
        "status": "completed" if status_text.lower() in {"optimal", "feasible"} else "failed",
        "solver_status": status_text,
        "termination_condition": termination,
        "objective_value_eur": objective_value,
        "expected_mfrr_capacity_revenue_eur": baseline_expected_mfrr_capacity_revenue,
        "production_kg": production_kg,
        "shortfall_kg": shortfall_kg,
        "total_electrolyser_consumption_mwh": total_electrolyser_consumption_mwh,
        "total_compressor_consumption_mwh": total_compressor_consumption_mwh,
        "offered_capacity_by_direction_mw": {},
        "selected_candidates": [],
        "deliverability_min_margin_by_direction_mw": {},
        "deliverability_binding_by_direction": {},
        "model_stats": asdict(result.model_stats),
        "limitations": warnings,
    }
    _write_json(output_root / "run_summary.json", run_summary)

    metrics_summary = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "delivery_date_local": DELIVERY_DATE,
                "solver_status": status_text,
                "termination_condition": termination,
                "objective_value_eur": objective_value,
                "expected_mfrr_capacity_revenue_eur": baseline_expected_mfrr_capacity_revenue,
                "production_kg": production_kg,
                "shortfall_kg": shortfall_kg,
                "total_electrolyser_consumption_mwh": total_electrolyser_consumption_mwh,
                "total_compressor_consumption_mwh": total_compressor_consumption_mwh,
            }
        ]
    )
    metrics_summary.to_csv(output_root / "metrics_summary.csv", index=False)

    comparison_summary = {
        "comparison_target_run": _repo_rel(MFRR_RUN_DIR),
        "delivery_date_local": DELIVERY_DATE,
        "artifact_id": ARTIFACT_ID,
        "baseline_objective_value_eur": objective_value,
        "mfrr_objective_value_eur": mfrr_objective,
        "objective_difference_baseline_minus_mfrr_eur": objective_uplift_eur,
        "baseline_expected_mfrr_capacity_revenue_eur": baseline_expected_mfrr_capacity_revenue,
        "mfrr_expected_mfrr_capacity_revenue_eur": mfrr_expected_revenue,
        "expected_mfrr_capacity_revenue_difference_baseline_minus_mfrr_eur": expected_revenue_difference_eur,
        "baseline_production_kg": production_kg,
        "mfrr_production_kg": mfrr_production_kg,
        "production_difference_baseline_minus_mfrr_kg": production_difference_kg,
        "baseline_shortfall_kg": shortfall_kg,
        "mfrr_shortfall_kg": mfrr_shortfall_kg,
        "shortfall_difference_baseline_minus_mfrr_kg": shortfall_difference_kg,
        "baseline_total_electrolyser_consumption_mwh": total_electrolyser_consumption_mwh,
        "baseline_total_compressor_consumption_mwh": total_compressor_consumption_mwh,
        "mfrr_total_electrolyser_consumption_mwh": None,
        "mfrr_total_compressor_consumption_mwh": None,
        "operational_net_cost_baseline_eur": operational_net_cost_baseline,
        "operational_net_cost_mfrr_eur": operational_net_cost_mfrr,
        "operational_net_cost_difference_baseline_minus_mfrr_eur": operational_net_cost_difference_eur,
        "objective_change_explained_by_mfrr_revenue": objective_change_explained_by_mfrr_revenue,
        "schedule_materially_changed": schedule_materially_changed,
        "interpretation": (
            "No material operational difference is visible in the persisted comparison metrics."
            if not schedule_materially_changed
            else "Persisted metrics suggest an operational difference beyond the mFRR revenue term."
        ),
    }
    _write_json(output_root / "comparison_summary.json", comparison_summary)

    warnings_path = output_root / "warnings_and_limitations.md"
    warnings_path.write_text("\n".join(f"- {item}" for item in warnings) + "\n", encoding="utf-8")

    registry_entry = {
        "run_id": run_id,
        "timestamp": _iso(started),
        "domain": "optimisation",
        "market": "DA_baseline_vs_mFRR_capacity_smoke",
        "pipeline_stage": "smoke_run",
        "granularity": "hourly",
        "horizon": "D_only_one_day",
        "model_family": "hydrogen_stochastic_dispatch",
        "feature_set": "none",
        "scenario_source": ARTIFACT_ID,
        "input_artifacts": [
            {"artifact_id": ARTIFACT_ID, "path": _repo_rel(resolved_slice.spec.path)},
            {"artifact_id": "comparison_target_run", "path": _repo_rel(MFRR_RUN_DIR)},
        ],
        "output_root": _repo_rel(output_root),
        "output_policy": OUTPUT_POLICY,
        "run_class": RUN_CLASS,
        "lineage_role": LINEAGE_ROLE,
        "status": "completed" if status_text.lower() in {"optimal", "feasible"} else "failed",
        "thesis_usable": "no",
        "key_result": f"One-day baseline solved with status={status_text}; objective delta vs mFRR run={objective_uplift_eur}.",
        "limitations": "; ".join(warnings),
        "archive_location": None,
        "delete_after": None,
        "git_commit": None,
    }
    _write_json(output_root / "registry_entry.json", registry_entry)

    if not baseline_objective_components.empty:
        baseline_objective_components.to_csv(output_root / "objective_components.csv", index=False)

    compact = {
        "RUN_DIR": str(output_root),
        "DA_ROWS": da_validation["row_count"],
        "DA_SCENARIOS": da_validation["scenario_count"],
        "SOLVER_STATUS": status_text,
        "TERMINATION": termination,
        "BASELINE_OBJECTIVE_EUR": objective_value,
        "MFRR_OBJECTIVE_EUR": mfrr_objective,
        "OBJECTIVE_DIFF_BASELINE_MINUS_MFRR_EUR": objective_uplift_eur,
        "BASELINE_PRODUCTION_KG": production_kg,
        "MFRR_PRODUCTION_KG": mfrr_production_kg,
        "PRODUCTION_DIFF_KG": production_difference_kg,
        "BASELINE_SHORTFALL_KG": shortfall_kg,
        "MFRR_SHORTFALL_KG": mfrr_shortfall_kg,
        "EXPECTED_MFRR_REVENUE_EUR": mfrr_expected_revenue,
        "OBJECTIVE_CHANGE_EXPLAINED_BY_REVENUE": objective_change_explained_by_mfrr_revenue,
        "SCHEDULE_MATERIALLY_CHANGED": schedule_materially_changed,
    }
    for key, value in compact.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
