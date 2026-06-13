from __future__ import annotations

import hashlib
import json
import os
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
RUN_CLASS = "smoke"
LINEAGE_ROLE = "diagnostic"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _fingerprint_file(path: Path) -> dict[str, Any]:
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": _repo_rel(path),
        "size_bytes": int(stat.st_size),
        "sha256": digest,
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _boolish_all_false(frame: pd.DataFrame, columns: list[str]) -> bool:
    for column in columns:
        values = frame[column].astype(str).str.strip().str.lower().unique().tolist()
        if any(value not in {"false", "0"} for value in values):
            return False
    return True


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


def _build_selected_candidate_summary(mfrr_summary: pd.DataFrame) -> list[dict[str, Any]]:
    if mfrr_summary is None or mfrr_summary.empty:
        return []
    selected = mfrr_summary[mfrr_summary["selected_bid_candidate"].astype(float) > 0.5].copy()
    if selected.empty:
        return []
    cols = [
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
    return selected[cols].to_dict(orient="records")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


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


def main() -> int:
    started = _now_utc()
    config_path = REPO_ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "configs" / "base_hydrogen.yaml"
    config = load_hydrogen_config(config_path)

    run_id = f"{started.strftime('%Y%m%d_%H%M%S')}_mfrr_capacity_one_day_smoke_v1"
    output_root = (config.run_output_root / run_id).resolve()
    output_root.mkdir(parents=True, exist_ok=False)

    solver_log_path = output_root / "solver_log.txt"
    warnings: list[str] = [
        "One-day smoke test only; not a coherent weekly stochastic pilot.",
        "Dutch incident reserve / mFRRda capacity only; no activation, MARI, aFRR, or imbalance settlement.",
        "Expected mFRR capacity revenue uses fixed coefficients from the frozen accepted-threshold proxy export.",
    ]

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
        mfrr_capacity_pilot=mfrr_input,
        solver_log_path=str(solver_log_path),
    )

    dispatch = result.dispatch.copy()
    shortfall_kg = float(dispatch["shortfall_kg"].iloc[0]) if not dispatch.empty else float("nan")
    production_kg = float(dispatch["H_comp_kg"].sum()) if not dispatch.empty else float("nan")
    objective_value = float(result.solver.objective_value) if result.solver.objective_value is not None else None
    expected_mfrr_capacity_revenue = 0.0
    if result.objective_components is not None and not result.objective_components.empty:
        expected_mfrr_capacity_revenue = float(result.objective_components["expected_mfrr_capacity_revenue_eur"].iloc[0])

    mfrr_summary = result.mfrr_capacity_summary.copy() if result.mfrr_capacity_summary is not None else pd.DataFrame()
    selected_candidate_summary = _build_selected_candidate_summary(mfrr_summary)
    direction_offers = {}
    direction_margin = {}
    direction_binding = {}
    if not mfrr_summary.empty:
        grouped_offer = (
            mfrr_summary.groupby("direction", as_index=False)["offered_capacity_total_mw"]
            .max()
            .set_index("direction")["offered_capacity_total_mw"]
            .to_dict()
        )
        grouped_margin = (
            mfrr_summary.groupby("direction", as_index=False)["min_deliverability_margin_mw"]
            .min()
            .set_index("direction")["min_deliverability_margin_mw"]
            .to_dict()
        )
        direction_offers = {str(k): float(v) for k, v in grouped_offer.items()}
        direction_margin = {str(k): float(v) for k, v in grouped_margin.items()}
        direction_binding = {str(k): bool(abs(float(v)) <= 1e-6) for k, v in grouped_margin.items()}

    no_capacity_revenue_when_zero_offer = True
    if direction_offers:
        total_offer = float(sum(direction_offers.values()))
        if abs(total_offer) <= 1e-9:
            no_capacity_revenue_when_zero_offer = abs(expected_mfrr_capacity_revenue) <= 1e-9

    status_text = str(result.solver.status)
    termination = str(result.solver.termination_condition) if result.solver.termination_condition is not None else None
    is_solved = status_text.lower() in {"optimal", "feasible"}

    resolved_config_payload = {
        "base_config_path": _repo_rel(config.config_path),
        "artifact_id": ARTIFACT_ID,
        "delivery_date": DELIVERY_DATE,
        "output_policy": OUTPUT_POLICY,
        "run_class": RUN_CLASS,
        "lineage_role": LINEAGE_ROLE,
        "risk_gamma_used": 0.0,
        "apply_terminal_value": True,
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

    run_summary = {
        "run_id": run_id,
        "timestamp_utc": _iso(started),
        "status": "completed" if is_solved else "failed",
        "solver_status": status_text,
        "termination_condition": termination,
        "objective_value_eur": objective_value,
        "expected_mfrr_capacity_revenue_eur": expected_mfrr_capacity_revenue,
        "production_kg": production_kg,
        "shortfall_kg": shortfall_kg,
        "offered_capacity_by_direction_mw": direction_offers,
        "selected_candidates": selected_candidate_summary,
        "deliverability_min_margin_by_direction_mw": direction_margin,
        "deliverability_binding_by_direction": direction_binding,
        "no_capacity_revenue_when_zero_offer": no_capacity_revenue_when_zero_offer,
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
                "expected_mfrr_capacity_revenue_eur": expected_mfrr_capacity_revenue,
                "offered_capacity_up_mw": float(direction_offers.get("Up", 0.0)),
                "offered_capacity_down_mw": float(direction_offers.get("Down", 0.0)),
                "production_kg": production_kg,
                "shortfall_kg": shortfall_kg,
            }
        ]
    )
    metrics_summary.to_csv(output_root / "metrics_summary.csv", index=False)

    warnings_path = output_root / "warnings_and_limitations.md"
    warnings_path.write_text("\n".join(f"- {item}" for item in warnings) + "\n", encoding="utf-8")

    registry_entry = {
        "run_id": run_id,
        "timestamp": _iso(started),
        "domain": "optimisation",
        "market": "DA_plus_mFRR_capacity_smoke",
        "pipeline_stage": "smoke_run",
        "granularity": "hourly",
        "horizon": "D_only_one_day",
        "model_family": "hydrogen_stochastic_dispatch",
        "feature_set": "none",
        "scenario_source": ARTIFACT_ID,
        "input_artifacts": [
            {"artifact_id": ARTIFACT_ID, "path": _repo_rel(resolved_slice.spec.path)},
            {"artifact_id": "nl_ir_capacity_milp_input_daily_direction_scenarios_v1", "path": _repo_rel(mfrr_input.export_path)},
        ],
        "output_root": _repo_rel(output_root),
        "output_policy": OUTPUT_POLICY,
        "run_class": RUN_CLASS,
        "lineage_role": LINEAGE_ROLE,
        "status": "completed" if is_solved else "failed",
        "thesis_usable": "no",
        "key_result": f"One-day mFRR capacity smoke test status={status_text}, termination={termination}.",
        "limitations": "; ".join(warnings),
        "archive_location": None,
        "delete_after": None,
        "git_commit": None,
    }
    _write_json(output_root / "registry_entry.json", registry_entry)

    if not mfrr_summary.empty:
        mfrr_summary.to_csv(output_root / "mfrr_capacity_summary.csv", index=False)
    if result.objective_components is not None and not result.objective_components.empty:
        result.objective_components.to_csv(output_root / "objective_components.csv", index=False)

    compact = {
        "RUN_DIR": str(output_root),
        "DA_ROWS": da_validation["row_count"],
        "DA_SCENARIOS": da_validation["scenario_count"],
        "MFRR_ROWS": mfrr_validation["pilot_rows"],
        "MFRR_CANDIDATES": mfrr_validation["candidate_rows"],
        "MFRR_ACCEPTANCE_ROWS": mfrr_validation["acceptance_rows"],
        "SOLVER_STATUS": status_text,
        "TERMINATION": termination,
        "OBJECTIVE_EUR": objective_value,
        "EXPECTED_MFRR_REVENUE_EUR": expected_mfrr_capacity_revenue,
        "OFFERED_UP_MW": float(direction_offers.get("Up", 0.0)),
        "OFFERED_DOWN_MW": float(direction_offers.get("Down", 0.0)),
        "SHORTFALL_KG": shortfall_kg,
        "PRODUCTION_KG": production_kg,
        "DELIVERABILITY_MIN_MARGIN": direction_margin,
    }
    for key, value in compact.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
