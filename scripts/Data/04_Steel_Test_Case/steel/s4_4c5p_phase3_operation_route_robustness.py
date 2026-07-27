"""Bounded Phase-3 operation/route robustness audit.

The audit delegates every solve to the accepted closed-loop C5 runner.  It
freezes three C1 route policies over two development weeks, keeps Phase-2
physics untouched, and emits only compact diagnostic summaries.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
    CONFIGURATIONS,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT
from .validation_tolerance_policy import (
    policy_contract,
    resolve_policy_contract,
)


VALIDATION_TOLERANCE_POLICY_REQUIRED = True
RUN_ID = "steel_c5_phase3_operation_route_robustness_v1_20260727"
CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase3_operation_route_robustness.yaml"
)
EXPECTED_ROUTE_POLICIES = (
    "free_route_reference",
    "source_informed_band",
    "central_source_ratio",
)
EXPECTED_PRICE_SCENARIOS = (
    "calm_price_insensitive",
    "volatile_governed_y_pred",
)


class Phase3RobustnessError(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialised = list(rows)
    if not materialised:
        raise Phase3RobustnessError(f"Required compact output is empty: {path.name}")
    fields: list[str] = []
    for row in materialised:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialised)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: Any) -> float:
    return 0.0 if value in {None, ""} else float(value)


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_phase3_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise Phase3RobustnessError("Phase-3 config must be a mapping.")
    return config


def check_phase3_config(config: Mapping[str, Any]) -> None:
    if config.get("run_id") != RUN_ID:
        raise Phase3RobustnessError("Unexpected Phase-3 run id.")
    if config.get("mode") != "bounded_phase3_operation_route_robustness":
        raise Phase3RobustnessError("Unexpected Phase-3 execution mode.")
    if config.get("output_policy") != "minimal":
        raise Phase3RobustnessError("Phase 3 requires output_policy=minimal.")
    phase3 = config["phase3"]
    resolve_policy_contract(phase3["validation_tolerance_policy"])
    route_ids = tuple(row["route_policy_id"] for row in phase3["route_policies"])
    scenario_ids = tuple(row["scenario_id"] for row in phase3["price_scenarios"])
    if route_ids != EXPECTED_ROUTE_POLICIES:
        raise Phase3RobustnessError(f"Frozen route policy order differs: {route_ids}.")
    if scenario_ids != EXPECTED_PRICE_SCENARIOS:
        raise Phase3RobustnessError(f"Frozen price scenario order differs: {scenario_ids}.")
    if len(phase3["development_periods"]) != 2 or any(
        row.get("dataset_split") != "validation"
        or row.get("period_role") != "development"
        for row in phase3["development_periods"]
    ):
        raise Phase3RobustnessError("Exactly two development/validation periods are required.")
    expected = {
        "expected_rolling_case_count": 6,
        "expected_configuration_trajectory_count": 12,
        "expected_model_count": 84,
        "replans_per_case": 7,
    }
    for key, value in expected.items():
        if int(phase3[key]) != value:
            raise Phase3RobustnessError(f"Frozen cap differs for {key}.")
    if phase3.get("held_out_periods_used") or phase3.get("y_true_used"):
        raise Phase3RobustnessError("Held-out data and y_true are prohibited.")
    if phase3.get("candidate_promoted"):
        raise Phase3RobustnessError("This diagnostic cannot promote a candidate.")
    lock = phase3["scope_lock"]
    prohibited = (
        "phase2_or_modelbuilder_changes_allowed",
        "tolerance_policy_changes_allowed",
        "calibration_allowed",
        "held_out_or_y_true_allowed",
        "market_bidding_or_settlement_allowed",
        "stochasticity_or_cvar_allowed",
        "co2_or_ets_claims_allowed",
        "economic_uplift_claim_allowed",
    )
    if any(bool(lock[key]) for key in prohibited):
        raise Phase3RobustnessError("The Phase-3 scope lock was relaxed.")
    if int(lock["maximum_narrow_repairs"]) != 1:
        raise Phase3RobustnessError("Phase 3 permits at most one narrow repair.")
    central = phase3["accepted_central_boundary"]
    if central["candidate_id"] != "recovery_bg30_ng55":
        raise Phase3RobustnessError("The accepted central boundary must remain frozen.")
    if central["wag_generation_yield_overrides_by_configuration"]:
        raise Phase3RobustnessError("WAG yield overrides are outside Phase 3.")
    if central["named_process_electricity_intensity_scales_by_configuration"]:
        raise Phase3RobustnessError("Process electricity scaling is outside Phase 3.")
    for scenario in phase3["price_scenarios"]:
        if scenario["price_field"] != "y_pred" or scenario["perfect_foresight_oracle"]:
            raise Phase3RobustnessError("Only governed y_pred development cases are allowed.")


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _source_rows(config: Mapping[str, Any]) -> tuple[Path, list[dict[str, Any]]]:
    phase3 = config["phase3"]
    contract_path = _resolve_repo_path(str(phase3["forecast_contract"]))
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    forecast_root = _resolve_repo_path(str(phase3["forecast_run_root"]))
    if forecast_root.name != str(contract["source_run_id"]):
        raise Phase3RobustnessError("Forecast root does not match the source contract.")
    rows: list[dict[str, Any]] = []
    for source_id, relative in contract["source_run_relative_files"].items():
        path = forecast_root / str(relative)
        expected_hash = str(contract["source_file_sha256"][source_id])
        expected_size = int(contract["source_file_size_bytes"][source_id])
        if not path.is_file():
            raise Phase3RobustnessError(f"Forecast source file is missing: {source_id}.")
        observed_hash = _sha256(path)
        observed_size = path.stat().st_size
        status = "pass" if observed_hash == expected_hash and observed_size == expected_size else "fail"
        rows.append(
            {
                "source_id": source_id,
                "portable_relative_file": str(relative).replace("\\", "/"),
                "expected_sha256": expected_hash,
                "observed_sha256": observed_hash,
                "expected_size_bytes": expected_size,
                "observed_size_bytes": observed_size,
                "status": status,
            }
        )
    if any(row["status"] != "pass" for row in rows):
        raise Phase3RobustnessError("Forecast source contract mismatch.")
    return forecast_root, rows


def frozen_case_matrix(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    phase3 = config["phase3"]
    periods = {row["period_id"]: row for row in phase3["development_periods"]}
    rows: list[dict[str, Any]] = []
    for route in phase3["route_policies"]:
        for scenario in phase3["price_scenarios"]:
            period = periods[scenario["period_id"]]
            rows.append(
                {
                    "case_id": f"phase3__{route['route_policy_id']}__{scenario['scenario_id']}",
                    "route_policy_id": route["route_policy_id"],
                    "route_role": route["role"],
                    "route_band": route.get("c1_liquid_steel_route_band"),
                    "scenario_id": scenario["scenario_id"],
                    "period_id": scenario["period_id"],
                    "dataset_split": period["dataset_split"],
                    "forecast_start_origin_utc": period["frozen_forecast_start_origin_utc"],
                    "price_field": scenario["price_field"],
                    "flat_price_eur_per_mwh": scenario.get("flat_price_eur_per_mwh"),
                    "perfect_foresight_oracle": scenario["perfect_foresight_oracle"],
                    "expected_model_count": 14,
                }
            )
    return rows


def _case_overrides(
    config: Mapping[str, Any], case: Mapping[str, Any], forecast_root: Path
) -> dict[str, Any]:
    phase3 = config["phase3"]
    central = phase3["accepted_central_boundary"]
    recovery = phase3["recovery_interface"]
    payload: dict[str, Any] = {
        "run_id": case["case_id"],
        "lineage_role": "phase3_development_physical_robustness_child",
        "forecast_run_root": str(forecast_root),
        "replan_count": int(phase3["replans_per_case"]),
        "price_series_id": "hourly_da_dplus4_point_forecast",
        "generator_operating_mode": "development_price_responsive",
        "forecast_dataset_split": case["dataset_split"],
        "forecast_start_origin_utc": case["forecast_start_origin_utc"],
        "timestamped_dplus4_rolling_enabled": True,
        "forecast_price_override_eur_per_mwh": case["flat_price_eur_per_mwh"],
        "forecast_price_field": case["price_field"],
        "perfect_foresight_oracle": False,
        "site_background_electricity_mwh_h_by_configuration": dict(
            central["site_background_electricity_mwh_h_by_configuration"]
        ),
        "price_scenario_overrides": {
            "natural_gas_ttf_proxy": central["ng_price_scenario_id"]
        },
        "mechanism_candidate_id": central["candidate_id"],
        "mechanism_ng_price_eur_per_mwh_lhv": float(
            central["ng_price_eur_per_mwh_lhv"]
        ),
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
    if case["route_band"] is not None:
        payload["c1_liquid_steel_route_band"] = dict(case["route_band"])
    return payload


def _case_files(directory: Path) -> dict[str, Any]:
    required = (
        "run_summary.json",
        "executed_hourly.csv",
        "rolling_model_metrics.csv",
        "validation_checks.csv",
    )
    if not directory.is_dir() or any(not (directory / name).is_file() for name in required):
        raise Phase3RobustnessError(f"Incomplete child output: {directory.name}.")
    return {
        "directory": directory,
        "summary": _read_json(directory / "run_summary.json"),
        "hourly": _read_csv(directory / "executed_hourly.csv"),
        "models": _read_csv(directory / "rolling_model_metrics.csv"),
        "checks": _read_csv(directory / "validation_checks.csv"),
    }


def _case_disposition(
    case: Mapping[str, Any], artifact: Mapping[str, Any]
) -> tuple[str, list[str]]:
    models = artifact["models"]
    c0_models = [row for row in models if row.get("configuration_id") == C0_CONFIGURATION]
    c1_models = [row for row in models if row.get("configuration_id") == C1_CONFIGURATION]
    exact_route_infeasibility = (
        case["route_policy_id"] == "central_source_ratio"
        and len(c0_models) == 7
        and all(
            row.get("termination_condition") == "optimal"
            and row.get("solver_status") in {"ok", "warning"}
            for row in c0_models
        )
        and len(c1_models) == 7
        and all(
            row.get("termination_condition") == "infeasible"
            and row.get("solver_status") == "warning"
            for row in c1_models
        )
        and artifact["summary"].get("c0_rolling_status") == "pass"
        and artifact["summary"].get("c1_rolling_status") == "infeasible"
    )
    if exact_route_infeasibility:
        return (
            "physically_explained_infeasible",
            [
                "exact_0.503703704_BOF_share_isolated_as_C1_infeasibility;"
                "C0_optimal_7_of_7;C1_solver_proven_infeasible_7_of_7;"
                "free_and_0.45_to_0.55_controls_solve"
            ],
        )
    bad_models = [
        f"model:{row.get('replan_index')}:{row.get('configuration_id')}"
        for row in models
        if row.get("termination_condition") != "optimal"
        or row.get("solver_status") not in {"ok", "warning"}
    ]
    allowed = {"no_fixed_route_split"} if case["route_band"] is not None else set()
    bad_checks = [
        str(row.get("check_id"))
        for row in artifact["checks"]
        if row.get("status") != "pass" and row.get("check_id") not in allowed
    ]
    expected_route_signal = [
        row for row in artifact["checks"] if row.get("check_id") == "no_fixed_route_split"
    ]
    if case["route_band"] is None and (
        not expected_route_signal or expected_route_signal[0].get("status") != "pass"
    ):
        bad_checks.append("no_fixed_route_split")
    if case["route_band"] is not None and (
        not expected_route_signal or expected_route_signal[0].get("status") != "fail"
    ):
        bad_checks.append("expected_route_sensitivity_signal_missing")
    if len(models) != int(case["expected_model_count"]):
        bad_models.append(f"model_count:{len(models)}")
    counts = {
        configuration: len(
            {int(row["replan_index"]) for row in models if row["configuration_id"] == configuration}
        )
        for configuration in CONFIGURATIONS
    }
    if any(value != 7 for value in counts.values()):
        bad_models.append(f"replan_counts:{counts}")
    failures = bad_models + bad_checks
    return ("pass" if not failures else "implementation_failure", failures)


def _sum(rows: Iterable[Mapping[str, Any]], field: str) -> float:
    return sum(_number(row.get(field)) for row in rows)


def _configuration_rows(
    case: Mapping[str, Any], artifact: Mapping[str, Any]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for configuration in CONFIGURATIONS:
        hourly = [row for row in artifact["hourly"] if row["configuration_id"] == configuration]
        if len(hourly) != 168:
            raise Phase3RobustnessError(
                f"{case['case_id']} has {len(hourly)} executed hours for {configuration}."
            )
        factor = 8760.0 / len(hourly)
        c0 = configuration == C0_CONFIGURATION
        bof = _sum(hourly, "C0_BOF_crude_steel_output_t" if c0 else "C1_BOF_liquid_steel_output_t_h")
        eaf = _sum(hourly, "C1_EAF_liquid_steel_output_t_h") if not c0 else 0.0
        liquid = bof + eaf
        output.append(
            {
                "case_id": case["case_id"],
                "route_policy_id": case["route_policy_id"],
                "scenario_id": case["scenario_id"],
                "configuration_id": configuration,
                "executed_hours": len(hourly),
                "annualisation_factor": factor,
                "annual_equivalent_role": "development_week_not_empirical_annual_result",
                "final_product_t": _sum(hourly, "final_product_output_t"),
                "annual_equivalent_final_product_t_y": _sum(hourly, "final_product_output_t") * factor,
                "bof_liquid_steel_t": bof,
                "eaf_liquid_steel_t": eaf,
                "bof_liquid_steel_share": bof / liquid if liquid else None,
                "bf6_sinter_input_t": _sum(hourly, "C0_BF6_sinter_input_t_h" if c0 else "C1_retained_BF6_sinter_input_t_h"),
                "bf7_sinter_input_t": _sum(hourly, "C0_BF7_sinter_input_t_h" if c0 else "C1_BF7_activity_t_h"),
                "bf6_on_hours": _sum(hourly, "C0_BF6_on" if c0 else "C1_BF6_on"),
                "bf7_on_hours": _sum(hourly, "C0_BF7_on") if c0 else 0.0,
                "dry_coal_input_t": _sum(hourly, "C0_coking_input_t_h" if c0 else "C1_retained_coking_input_t_h"),
                "coke_output_t": _sum(hourly, "C0_coke_output_t_h" if c0 else "C1_retained_coke_output_t_h"),
                "dri_output_t": _sum(hourly, "C1_DRP_DRI_output_t_h") if not c0 else 0.0,
                "scrap_input_t": _sum(hourly, "scrap_t") + _sum(hourly, "bof_scrap_t") if not c0 else 0.0,
                "bfg_generated_mwh": _sum(hourly, "BFG_generated_mwh"),
                "cog_generated_mwh": _sum(hourly, "COG_generated_mwh"),
                "bofg_generated_mwh": _sum(hourly, "BOFG_generated_mwh"),
                "wag_generator_electricity_mwh": _sum(hourly, "WAG_generator_electricity_mwh"),
                "wag_flared_mwh": _sum(hourly, "BFG_flared_mwh") + _sum(hourly, "COG_flared_mwh") + _sum(hourly, "BOFG_flared_mwh"),
                "grid_import_mwh": _sum(hourly, "gross_grid_import_mwh"),
                "grid_export_mwh": _sum(hourly, "gross_grid_export_mwh"),
                "named_ng_mwh": _sum(hourly, "DRP_named_NG_mwh") + _sum(hourly, "EAF_named_NG_mwh") + _sum(hourly, "generator_named_ng_mwh") + _sum(hourly, "natural_gas_boiler_mwh"),
                "hsm_output_t": _sum(hourly, "C0_HSM_final_product_t" if c0 else "C1_HSM_final_product_output_t"),
                "dsp_output_t": _sum(hourly, "C0_DSP_final_product_t" if c0 else "C1_DSP_final_product_output_t"),
                "dri_inventory_min_t": min((_number(row.get("DRI_inventory_t")) for row in hourly), default=0.0),
                "dri_inventory_max_t": max((_number(row.get("DRI_inventory_t")) for row in hourly), default=0.0),
            }
        )
    return output


def _behavior_rows(
    config: Mapping[str, Any], metrics: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    bf = config["phase3"]["bf_source_contract"]
    rows.append(
        {
            "assessment_id": "bf6_bf7_capacity_variant_robustness",
            "scope": "C0_BF6_BF7_capacity_or_rate_variants",
            "outcome": bf["disposition"],
            "hard_gate": "false",
            "reason": bf["missing_interface"],
        }
    )
    for metric in metrics:
        if metric["configuration_id"] == C0_CONFIGURATION:
            bf6 = float(metric["bf6_sinter_input_t"])
            bf7 = float(metric["bf7_sinter_input_t"])
            rows.append(
                {
                    "assessment_id": f"central_bf_loading__{metric['case_id']}",
                    "scope": "C0_central_BF6_BF7_behavior",
                    "outcome": "supports_bf7_larger_than_bf6" if bf7 > bf6 else "contradicts_bf7_larger_than_bf6",
                    "hard_gate": "false",
                    "reason": f"executed BF6 sinter={bf6:.6f} t; BF7 sinter={bf7:.6f} t",
                }
            )
        else:
            share = metric["bof_liquid_steel_share"]
            rows.append(
                {
                    "assessment_id": f"route_response__{metric['case_id']}",
                    "scope": "C1_BF_BOF_DRP_EAF_route_and_energy_consequences",
                    "outcome": "observed",
                    "hard_gate": "false",
                    "reason": f"BOF share={share:.9f}; DRI={metric['dri_output_t']:.3f} t; coke={metric['coke_output_t']:.3f} t; WAG electricity={metric['wag_generator_electricity_mwh']:.3f} MWh",
                }
            )
    return rows


def _bf_source_availability(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    bf = config["phase3"]["bf_source_contract"]
    return [
        {
            "variant_id": "active_central_bf6_bf7_behavior",
            "status": "evaluable",
            "execution_action": "included_in_all_C0_trajectories",
            "source_basis": "active corrected-input process limits",
        },
        {
            "variant_id": "bf6_bf7_capacity_or_rate_perturbations",
            "status": bf["disposition"],
            "execution_action": "not_run",
            "source_basis": bf["missing_interface"],
        },
    ]


def run_phase3(
    config_path: str | Path = CONFIG_PATH,
    *,
    prepare_only: bool = False,
    finalize_existing: bool = False,
) -> dict[str, Any]:
    started = time.time()
    config_file = Path(config_path).resolve()
    config = load_phase3_config(config_file)
    check_phase3_config(config)
    phase3 = config["phase3"]
    output_root = _resolve_repo_path(str(config["output_root"]))
    scratch_root = _resolve_repo_path(str(phase3["scratch_root"]))
    if output_root.exists() and not finalize_existing:
        raise Phase3RobustnessError(f"Governed output root already exists: {output_root}")
    output_root.mkdir(parents=True, exist_ok=finalize_existing)
    scratch_root.mkdir(parents=True, exist_ok=True)
    forecast_root, source_rows = _source_rows(config)
    cases = frozen_case_matrix(config)
    portable_cases = [
        {**row, "route_band": json.dumps(row["route_band"], sort_keys=True) if row["route_band"] else "none"}
        for row in cases
    ]
    (output_root / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    _write_csv(output_root / "scenario_matrix.csv", portable_cases)
    _write_csv(output_root / "forecast_source_checks.csv", source_rows)
    _write_csv(output_root / "bf_source_availability.csv", _bf_source_availability(config))
    _write_json(
        output_root / "input_manifest.json",
        {
            "config": {"path": str(config_file.relative_to(REPO_ROOT)).replace("\\", "/"), "sha256": _sha256(config_file)},
            "physical_config": {"path": str(phase3["physical_config"]), "sha256": _sha256(_resolve_repo_path(str(phase3["physical_config"])))},
            "forecast_contract": {"path": str(phase3["forecast_contract"]), "sha256": _sha256(_resolve_repo_path(str(phase3["forecast_contract"])))},
            "route_policy_contract": {"path": str(phase3["route_policy_contract"]), "sha256": _sha256(_resolve_repo_path(str(phase3["route_policy_contract"])))},
            "forecast_source_contract_checks": source_rows,
        },
    )
    _write_json(
        output_root / "code_version.json",
        {"git_commit": _git_head(), "policy": policy_contract()},
    )
    if prepare_only:
        summary = {
            "run_id": RUN_ID,
            "status": "prepared",
            "rolling_case_cap": 6,
            "configuration_trajectory_cap": 12,
            "model_cap": 84,
            "held_out_periods_used": False,
            "candidate_promoted": False,
        }
        _write_json(output_root / "run_summary.json", summary)
        return {"run_directory": output_root, "summary": summary}

    case_registry: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    implementation_failures: list[str] = []
    for case in cases:
        directory = scratch_root / str(case["case_id"])
        try:
            if directory.exists():
                artifact = _case_files(directory)
            else:
                run_closed_loop_feasibility_anchor_reconciliation(
                    config_path=_resolve_repo_path(str(phase3["physical_config"])),
                    output_root=scratch_root,
                    scenario_overrides=_case_overrides(config, case, forecast_root),
                )
                artifact = _case_files(directory)
            disposition, failures = _case_disposition(case, artifact)
            if disposition == "implementation_failure":
                implementation_failures.extend(f"{case['case_id']}:{item}" for item in failures)
            case_registry.append(
                {
                    "case_id": case["case_id"],
                    "route_policy_id": case["route_policy_id"],
                    "scenario_id": case["scenario_id"],
                    "status": disposition,
                    "child_status": artifact["summary"].get("status"),
                    "expected_route_sensitivity_reclassification": "not_applicable_expected_route_sensitivity" if case["route_band"] is not None else "not_applicable",
                    "model_count": len(artifact["models"]),
                    "failure_ids": ";".join(failures),
                    "scratch_lineage": f"tmp/{scratch_root.name}/{case['case_id']}",
                }
            )
            for row in artifact["models"]:
                solver_rows.append(
                    {
                        "case_id": case["case_id"],
                        "route_policy_id": case["route_policy_id"],
                        "scenario_id": case["scenario_id"],
                        "replan_index": row["replan_index"],
                        "configuration_id": row["configuration_id"],
                        "solver_name": row.get("solver_name"),
                        "solver_status": row.get("solver_status"),
                        "termination_condition": row.get("termination_condition"),
                        "runtime_seconds": row.get("runtime_seconds"),
                        "mip_gap": row.get("mip_gap"),
                        "variable_count": row.get("variable_count"),
                        "binary_count": row.get("binary_count"),
                        "constraint_count": row.get("constraint_count"),
                    }
                )
            if disposition == "pass":
                metric_rows.extend(_configuration_rows(case, artifact))
        except Exception as exc:
            implementation_failures.append(f"{case['case_id']}:{type(exc).__name__}:{exc}")
            case_registry.append(
                {
                    "case_id": case["case_id"],
                    "route_policy_id": case["route_policy_id"],
                    "scenario_id": case["scenario_id"],
                    "status": "implementation_failure",
                    "child_status": "exception",
                    "expected_route_sensitivity_reclassification": "not_applied",
                    "model_count": 0,
                    "failure_ids": f"{type(exc).__name__}:{exc}",
                    "scratch_lineage": f"tmp/{scratch_root.name}/{case['case_id']}",
                }
            )
            break

    _write_csv(output_root / "case_registry.csv", case_registry)
    if solver_rows:
        _write_csv(output_root / "solver_summary.csv", solver_rows)
    if metric_rows:
        _write_csv(output_root / "configuration_metrics.csv", metric_rows)
        _write_csv(output_root / "behavior_assessments.csv", _behavior_rows(config, metric_rows))
    actual_models = len(solver_rows)
    passed_cases = sum(row["status"] == "pass" for row in case_registry)
    physically_infeasible_cases = sum(
        row["status"] == "physically_explained_infeasible" for row in case_registry
    )
    accepted_outcomes = passed_cases + physically_infeasible_cases
    status = (
        "pass"
        if not implementation_failures and accepted_outcomes == 6 and actual_models == 84
        else "fail"
    )
    summary = {
        "run_id": RUN_ID,
        "status": status,
        "decision": (
            "phase3_bounded_robustness_complete_with_exact_route_infeasibility"
            if status == "pass" and physically_infeasible_cases
            else "phase3_bounded_robustness_complete"
            if status == "pass"
            else "phase3_bounded_robustness_not_complete"
        ),
        "lineage_role": "development_physical_robustness_diagnostic_nonpromoted",
        "output_policy": "minimal",
        "completed_rolling_case_count": len(case_registry),
        "passed_rolling_case_count": passed_cases,
        "physically_explained_infeasible_case_count": physically_infeasible_cases,
        "accepted_outcome_case_count": accepted_outcomes,
        "configuration_trajectory_count": accepted_outcomes * len(CONFIGURATIONS),
        "solver_model_count": actual_models,
        "rolling_case_cap": 6,
        "configuration_trajectory_cap": 12,
        "solver_model_cap": 84,
        "hard_failure_count": len(implementation_failures),
        "hard_failure_ids": implementation_failures,
        "bf_capacity_variants_status": phase3["bf_source_contract"]["disposition"],
        "route_sensitivity_count": 2,
        "development_price_scenario_count": 2,
        "held_out_periods_used": False,
        "y_true_used": False,
        "candidate_promoted": False,
        "economic_uplift_claimed": False,
        "market_bidding_or_settlement_enabled": False,
        "co2_or_ets_claimed": False,
        "validation_tolerance_policy": policy_contract(),
        "runtime_seconds": round(time.time() - started, 6),
    }
    _write_json(output_root / "run_summary.json", summary)
    _write_json(
        output_root / "registry_entry.json",
        {
            "run_id": RUN_ID,
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "output_policy": config["output_policy"],
            "status": status,
        },
    )
    (output_root / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- These are two 168-hour development trajectories and annual-equivalent reporting views, not empirical annual results.\n"
        "- The audit does not use held-out data, y_true, bidding, settlement, stochasticity, CVaR, ETS, or CO2 claims.\n"
        "- BF6/BF7 capacity or rate perturbations are not run because the active runner has no permitted runtime interface; changing the model builder or canonical inputs is outside scope.\n"
        "- Route-band cases intentionally make the inherited `no_fixed_route_split` check inapplicable; no other inherited physical or accounting failure is reclassified.\n"
        "- Behavioral direction is interpretive. Only solver, physical, accounting, lineage, and scope failures are hard failures.\n"
        "- No economic-uplift or candidate-promotion conclusion is made.\n",
        encoding="utf-8",
    )
    (output_root / "README.md").write_text(
        f"# {RUN_ID}\n\n"
        f"Status: {status}. This is a bounded DEVELOPMENT physical robustness diagnostic with {actual_models}/84 permitted model solves. "
        "Large child-run artifacts remain under ignored `tmp/`; this governed root contains compact summaries only.\n",
        encoding="utf-8",
    )
    return {"run_directory": output_root, "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--finalize-existing", action="store_true")
    args = parser.parse_args()
    result = run_phase3(
        args.config,
        prepare_only=args.prepare_only,
        finalize_existing=args.finalize_existing,
    )
    print(json.dumps({"run_directory": str(result["run_directory"]), "summary": result["summary"]}, indent=2))


if __name__ == "__main__":
    main()
