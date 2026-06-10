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


def _validate_da_slice(frame: pd.DataFrame, *, expected_delivery_date: str = DELIVERY_DATE) -> dict[str, Any]:
    local_dates = sorted(frame["delivery_day"].astype(str).unique().tolist())
    scenario_count = int(frame["scenario_id"].nunique())
    rows_per_scenario = frame.groupby("scenario_id").size()
    origins = sorted(frame["forecast_origin_utc"].astype(str).unique().tolist())
    return {
        "artifact_id": ARTIFACT_ID,
        "row_count": int(len(frame)),
        "scenario_count": scenario_count,
        "delivery_dates_present": local_dates,
        "has_exact_delivery_date": local_dates == [expected_delivery_date],
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
            local_dates == [expected_delivery_date]
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
    contract_isp_count_values = sorted(mfrr_input.pilot_rows["contract_isp_count"].astype(int).unique().tolist())
    return {
        "pilot_rows": int(len(mfrr_input.pilot_rows)),
        "candidate_rows": int(len(mfrr_input.candidate_summary)),
        "acceptance_rows": int(len(mfrr_input.acceptance_table)),
        "probability_sums": probability_check.to_dict(orient="records"),
        "timing_local_hours": sorted(timing_local.dt.hour.unique().tolist()),
        "contract_isp_count_values": contract_isp_count_values,
        "capacity_price_units": sorted(mfrr_input.pilot_rows["capacity_price_unit"].astype(str).unique().tolist()),
        "capacity_product_structures": sorted(
            mfrr_input.pilot_rows["capacity_product_structure"].astype(str).unique().tolist()
        ),
    }


def _validate_mfrr_revenue_coefficients(mfrr_input: Any) -> dict[str, Any]:
    summary = mfrr_input.candidate_summary.copy()
    recomputed = (
        summary["candidate_price_eur_per_mw_isp"].astype(float)
        * summary["expected_acceptance_probability"].astype(float)
        * summary["contract_isp_count"].astype(float)
    )
    actual = summary["expected_revenue_coefficient_eur_per_mw"].astype(float)
    max_abs_diff = float((actual - recomputed).abs().max())
    return {
        "candidate_row_count": int(len(summary)),
        "max_abs_diff": max_abs_diff,
        "example_formula": "2.22 EUR/MW/ISP * 35 MW * 96 ISP = 7459.20 EUR; 2.22 * 35 = 77.70 EUR is one-ISP only",
    }


def _validate_integer_offer_summary(mfrr_summary: pd.DataFrame) -> dict[str, Any]:
    if mfrr_summary.empty:
        return {
            "integer_mw_passed": True,
            "selected_minimum_mw_passed": True,
            "no_zero_volume_selected_bids_passed": True,
            "selected_zero_volume_bid_count": 0,
            "selected_below_minimum_bid_count": 0,
            "non_integer_offer_count": 0,
        }

    offered = mfrr_summary["offered_capacity_mw"].astype(float)
    selected = mfrr_summary["selected_bid_candidate"].astype(float) > 0.5
    non_integer_offer_count = int((offered - offered.round()).abs().gt(TOLERANCE).sum())
    selected_zero_volume_bid_count = int((selected & offered.abs().le(TOLERANCE)).sum())
    selected_below_minimum_bid_count = int((selected & (offered + TOLERANCE < 1.0)).sum())
    return {
        "integer_mw_passed": non_integer_offer_count == 0,
        "selected_minimum_mw_passed": selected_below_minimum_bid_count == 0,
        "no_zero_volume_selected_bids_passed": selected_zero_volume_bid_count == 0,
        "selected_zero_volume_bid_count": selected_zero_volume_bid_count,
        "selected_below_minimum_bid_count": selected_below_minimum_bid_count,
        "non_integer_offer_count": non_integer_offer_count,
    }


def _collect_mode(mode: str, result: Any) -> dict[str, Any]:
    dispatch = result.dispatch.copy()
    objective_components = result.objective_components.copy() if result.objective_components is not None else pd.DataFrame()
    mfrr_summary = result.mfrr_capacity_summary.copy() if result.mfrr_capacity_summary is not None else pd.DataFrame()

    selected = pd.DataFrame()
    if not mfrr_summary.empty:
        selected = mfrr_summary[mfrr_summary["selected_bid_candidate"].astype(float) > 0.5].copy()
        revenue_by_direction = (
            mfrr_summary.groupby("direction", as_index=False)["expected_capacity_revenue_eur"].sum().set_index("direction")
        )
        contract_isp_count_values = sorted(mfrr_summary["contract_isp_count"].astype(int).unique().tolist())
    else:
        revenue_by_direction = pd.DataFrame(columns=["expected_capacity_revenue_eur"])
        contract_isp_count_values = []
    integer_offer_validation = _validate_integer_offer_summary(mfrr_summary)

    return {
        "mode": mode,
        "solver_status": str(result.solver.status),
        "termination_condition": str(result.solver.termination_condition),
        "objective_value_eur": float(result.solver.objective_value) if result.solver.objective_value is not None else None,
        "objective_sense": "minimize",
        "production_kg": float(dispatch["H_comp_kg"].sum()) if not dispatch.empty else 0.0,
        "shortfall_kg": float(dispatch["shortfall_kg"].iloc[0]) if not dispatch.empty else 0.0,
        "expected_mfrr_capacity_revenue_eur": (
            float(objective_components["expected_mfrr_capacity_revenue_eur"].iloc[0])
            if not objective_components.empty
            else 0.0
        ),
        "expected_operational_net_cost_eur": (
            float(objective_components["expected_operational_net_cost_eur"].iloc[0])
            if not objective_components.empty
            else None
        ),
        "offered_capacity_up_mw": (
            float(mfrr_summary.loc[mfrr_summary["direction"].astype(str) == "Up", "offered_capacity_total_mw"].max())
            if not mfrr_summary.empty
            else 0.0
        ),
        "offered_capacity_down_mw": (
            float(mfrr_summary.loc[mfrr_summary["direction"].astype(str) == "Down", "offered_capacity_total_mw"].max())
            if not mfrr_summary.empty
            else 0.0
        ),
        "contract_isp_count_values": contract_isp_count_values,
        "expected_capacity_revenue_up_eur": (
            float(revenue_by_direction.loc["Up", "expected_capacity_revenue_eur"])
            if not mfrr_summary.empty and "Up" in revenue_by_direction.index
            else 0.0
        ),
        "expected_capacity_revenue_down_eur": (
            float(revenue_by_direction.loc["Down", "expected_capacity_revenue_eur"])
            if not mfrr_summary.empty and "Down" in revenue_by_direction.index
            else 0.0
        ),
        "expected_capacity_revenue_total_eur": (
            float(mfrr_summary["expected_capacity_revenue_eur"].sum()) if not mfrr_summary.empty else 0.0
        ),
        "integer_offer_validation": integer_offer_validation,
        "selected_candidates": (
            selected[
                [
                    "delivery_date_local",
                    "direction",
                    "candidate_id",
                    "candidate_price_eur_per_mw_isp",
                    "contract_isp_count",
                    "expected_acceptance_probability",
                    "offered_capacity_mw",
                    "expected_capacity_revenue_eur",
                ]
            ].to_dict(orient="records")
            if not selected.empty
            else []
        ),
        "objective_components": objective_components,
        "mfrr_capacity_summary": mfrr_summary,
        "debug_info": result.debug_info,
    }


def main() -> int:
    started = _now_utc()
    config_path = REPO_ROOT / "scripts" / "Data" / "03_Hydrogen_Test_Case" / "configs" / "base_hydrogen.yaml"
    config = load_hydrogen_config(config_path)
    exact_solver_settings = replace(config.solver, mip_gap=min(float(config.solver.mip_gap), 1e-6))

    run_id = f"{started.strftime('%Y%m%d_%H%M%S')}_mfrr_capacity_one_day_exact_comparison_v2_smoke"
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
    revenue_coefficient_validation = _validate_mfrr_revenue_coefficients(mfrr_input)
    if revenue_coefficient_validation["max_abs_diff"] > TOLERANCE:
        raise ValueError(f"mFRR revenue coefficient scaling check failed: {revenue_coefficient_validation}")

    baseline_result = solve_stochastic_dispatch(
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
        mfrr_capacity_pilot=None,
        solver_log_path=str(output_root / "solver_log_baseline.txt"),
        debug_options={"collect_objective_audit": True},
    )
    optional_result = solve_stochastic_dispatch(
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
        mfrr_capacity_pilot=mfrr_input,
        solver_log_path=str(output_root / "solver_log_mfrr_optional.txt"),
        debug_options={"collect_objective_audit": True},
    )
    forced_zero_result = solve_stochastic_dispatch(
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
        mfrr_capacity_pilot=mfrr_input,
        solver_log_path=str(output_root / "solver_log_mfrr_forced_zero.txt"),
        debug_options={"collect_objective_audit": True, "force_mfrr_offer_zero": True},
    )

    baseline = _collect_mode("no_mfrr_baseline", baseline_result)
    optional = _collect_mode("mfrr_optional", optional_result)
    forced_zero = _collect_mode("mfrr_forced_zero", forced_zero_result)

    optionality_dominance_passes = (optional["objective_value_eur"] or 0.0) <= (baseline["objective_value_eur"] or 0.0) + TOLERANCE
    forced_zero_matches_baseline = abs((forced_zero["objective_value_eur"] or 0.0) - (baseline["objective_value_eur"] or 0.0)) <= TOLERANCE
    integer_mw_validation_passed = bool(optional["integer_offer_validation"]["integer_mw_passed"])
    selected_minimum_validation_passed = bool(optional["integer_offer_validation"]["selected_minimum_mw_passed"])
    no_zero_volume_selected_bids_passed = bool(optional["integer_offer_validation"]["no_zero_volume_selected_bids_passed"])
    optional_total_offer_mw = (optional["offered_capacity_up_mw"] or 0.0) + (optional["offered_capacity_down_mw"] or 0.0)
    if optional_total_offer_mw > TOLERANCE:
        interpretation = (
            "Optional mFRR chooses positive integer MW capacity after correcting revenue to EUR/MW/ISP times contract_isp_count. "
            "This is acceptable if dominance, integer-step compliance, and feasibility still hold."
        )
    else:
        interpretation = (
            "Optional mFRR still chooses zero offered capacity for this day even after correcting revenue scaling and "
            "enforcing the 1 MW integer step."
        )

    comparison_summary = {
        "delivery_date_local": DELIVERY_DATE,
        "artifact_id": ARTIFACT_ID,
        "objective_sense": "minimize",
        "contract_isp_count_values": mfrr_validation["contract_isp_count_values"],
        "baseline_objective_value_eur": baseline["objective_value_eur"],
        "mfrr_optional_objective_value_eur": optional["objective_value_eur"],
        "mfrr_forced_zero_objective_value_eur": forced_zero["objective_value_eur"],
        "objective_difference_baseline_minus_optional_eur": (baseline["objective_value_eur"] or 0.0) - (optional["objective_value_eur"] or 0.0),
        "optionality_dominance_passes": optionality_dominance_passes,
        "forced_zero_matches_baseline": forced_zero_matches_baseline,
        "integer_mw_validation_passed": integer_mw_validation_passed,
        "selected_minimum_validation_passed": selected_minimum_validation_passed,
        "no_zero_volume_selected_bids_passed": no_zero_volume_selected_bids_passed,
        "optional_up_mw_changed_from_continuous_57_1326": abs((optional["offered_capacity_up_mw"] or 0.0) - 57.13263157894737) > TOLERANCE,
        "interpretation": interpretation,
    }

    resolved_config_payload = {
        "base_config_path": _repo_rel(config.config_path),
        "artifact_id": ARTIFACT_ID,
        "delivery_date": DELIVERY_DATE,
        "output_policy": OUTPUT_POLICY,
        "run_class": RUN_CLASS,
        "lineage_role": LINEAGE_ROLE,
        "risk_gamma_used": 0.0,
        "apply_terminal_value": True,
        "mip_gap_used": float(exact_solver_settings.mip_gap),
        "modes": ["no_mfrr_baseline", "mfrr_optional", "mfrr_forced_zero"],
        "mfrr_export_contract": "v2_eur_per_mw_per_isp_with_contract_isp_count",
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

    _write_json(output_root / "exact_comparison_summary.json", {
        "input_consistency": {
            "delivery_date_local": DELIVERY_DATE,
            "artifact_id": ARTIFACT_ID,
            "same_da_slice_all_modes": True,
            "da_validation": da_validation,
            "mfrr_validation": mfrr_validation,
            "revenue_coefficient_validation": revenue_coefficient_validation,
        },
        "comparison": comparison_summary,
        "modes": {
            baseline["mode"]: {k: v for k, v in baseline.items() if k not in {"objective_components", "mfrr_capacity_summary", "debug_info"}},
            optional["mode"]: {k: v for k, v in optional.items() if k not in {"objective_components", "mfrr_capacity_summary", "debug_info"}},
            forced_zero["mode"]: {k: v for k, v in forced_zero.items() if k not in {"objective_components", "mfrr_capacity_summary", "debug_info"}},
        },
    })

    mode_rows = []
    objective_rows = []
    objective_audit_rows = []
    for payload in [baseline, optional, forced_zero]:
        mode_rows.append(
            {
                "mode": payload["mode"],
                "solver_status": payload["solver_status"],
                "termination_condition": payload["termination_condition"],
                "objective_sense": payload["objective_sense"],
                "objective_value_eur": payload["objective_value_eur"],
                "production_kg": payload["production_kg"],
                "shortfall_kg": payload["shortfall_kg"],
                "expected_mfrr_capacity_revenue_eur": payload["expected_mfrr_capacity_revenue_eur"],
                "expected_capacity_revenue_up_eur": payload["expected_capacity_revenue_up_eur"],
                "expected_capacity_revenue_down_eur": payload["expected_capacity_revenue_down_eur"],
                "expected_capacity_revenue_total_eur": payload["expected_capacity_revenue_total_eur"],
                "offered_capacity_up_mw": payload["offered_capacity_up_mw"],
                "offered_capacity_down_mw": payload["offered_capacity_down_mw"],
                "integer_mw_passed": payload["integer_offer_validation"]["integer_mw_passed"],
                "selected_minimum_mw_passed": payload["integer_offer_validation"]["selected_minimum_mw_passed"],
                "no_zero_volume_selected_bids_passed": payload["integer_offer_validation"]["no_zero_volume_selected_bids_passed"],
            }
        )
        objective_rows.append(
            {
                "mode": payload["mode"],
                "objective_value_eur": payload["objective_value_eur"],
                "expected_operational_net_cost_eur": payload["expected_operational_net_cost_eur"],
                "expected_mfrr_capacity_revenue_eur": payload["expected_mfrr_capacity_revenue_eur"],
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
                }
            )

    pd.DataFrame(mode_rows).to_csv(output_root / "mode_summary.csv", index=False)
    pd.DataFrame(objective_rows).to_csv(output_root / "objective_component_comparison.csv", index=False)
    pd.DataFrame(objective_audit_rows).to_csv(output_root / "active_objective_audit.csv", index=False)
    optional["mfrr_capacity_summary"].to_csv(output_root / "mfrr_capacity_summary.csv", index=False)

    (output_root / "warnings_and_limitations.md").write_text(
        "\n".join(
            [
                "- One-day exact comparison only; not a weekly stochastic mFRR result.",
                "- The MILP consumes the repaired v2 incident-reserve capacity export with EUR/MW/ISP prices and contract_isp_count scaling.",
                "- Capacity offers are enforced as integer MW with a 1 MW minimum when selected.",
                "- This remains capacity-only: no activation, energy-bid optimisation, settlement, sanctions, or MARI is modelled.",
                "- Positive optional capacity after the revenue repair would not by itself prove activation feasibility or final economic value.",
            ]
        ),
        encoding="utf-8",
    )

    registry_entry = {
        "run_id": run_id,
        "timestamp": _iso(started),
        "domain": "optimisation",
        "market": "DA_plus_mFRR_capacity_exact_refresh",
        "pipeline_stage": "diagnostic",
        "granularity": "hourly",
        "horizon": "D_only",
        "model_family": "hydrogen_stochastic_dispatch",
        "feature_set": "not_applicable",
        "scenario_source": ARTIFACT_ID,
        "input_artifacts": [
            {"artifact_id": ARTIFACT_ID, "path": _repo_rel(config.models.scenario_catalog)},
            {"artifact_id": "nl_ir_capacity_milp_input_daily_direction_scenarios_v2", "path": _repo_rel(mfrr_input.export_path)},
        ],
        "output_root": _repo_rel(output_root),
        "output_policy": OUTPUT_POLICY,
        "run_class": RUN_CLASS,
        "lineage_role": LINEAGE_ROLE,
        "status": "completed",
        "thesis_usable": "conditional",
        "key_result": interpretation,
        "limitations": "One-day only; capacity-only; tightened gap used for exact dominance check.",
        "archive_location": None,
        "delete_after": None,
        "git_commit": None,
    }
    _write_json(output_root / "registry_entry.json", registry_entry)

    print(f"RUN_DIR={output_root}")
    print(f"TESTED_DELIVERY_DAY={DELIVERY_DATE}")
    print(f"CONTRACT_ISP_COUNT_VALUES={mfrr_validation['contract_isp_count_values']}")
    print(f"BASELINE_OBJECTIVE_EUR={baseline['objective_value_eur']}")
    print(f"FORCED_ZERO_OBJECTIVE_EUR={forced_zero['objective_value_eur']}")
    print(f"OPTIONAL_OBJECTIVE_EUR={optional['objective_value_eur']}")
    print(f"OPTIONAL_EXPECTED_CAPACITY_REVENUE_TOTAL_EUR={optional['expected_capacity_revenue_total_eur']}")
    print(f"OPTIONAL_EXPECTED_CAPACITY_REVENUE_UP_EUR={optional['expected_capacity_revenue_up_eur']}")
    print(f"OPTIONAL_EXPECTED_CAPACITY_REVENUE_DOWN_EUR={optional['expected_capacity_revenue_down_eur']}")
    print(f"OPTIONAL_OFFER_UP_MW={optional['offered_capacity_up_mw']}")
    print(f"OPTIONAL_OFFER_DOWN_MW={optional['offered_capacity_down_mw']}")
    print(f"OPTIONALITY_DOMINANCE_PASSES={optionality_dominance_passes}")
    print(f"FORCED_ZERO_MATCHES_BASELINE={forced_zero_matches_baseline}")
    print(f"INTEGER_MW_VALIDATION_PASSED={integer_mw_validation_passed and selected_minimum_validation_passed and no_zero_volume_selected_bids_passed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
