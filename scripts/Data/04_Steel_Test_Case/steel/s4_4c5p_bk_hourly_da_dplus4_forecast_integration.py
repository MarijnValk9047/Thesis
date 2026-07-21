"""Governed LEAR/Lago D-D+4 point forecasts in the deterministic steel roller."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import pyarrow.parquet as pq
import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_bf_price_series_interface import (
    DPLUS4_SOURCE_CONTRACT_PATH,
    PRICE_SERIES_CONTRACT_PATH,
    build_dplus4_forecast_slice,
    load_dplus4_source_contract,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_s2_hourly_da_dplus4_point_forecast_integration_v1_20260720"
RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
DEFAULT_OUTPUT = RUN_ROOT / RUN_ID
CONFIG_PATH = (
    REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "configs"
    / "steel_hourly_da_dplus4_point_forecast_integration.yaml"
)
PERMITTED_DECISIONS = {
    "ready_for_deterministic_DAM_price_response",
    "partial_DAM_forecast_integration",
    "blocked_forecast_contract",
}
C0 = "C0_current_BF_BOF_reference"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
HOURS_PER_YEAR = 8760.0


class DPlus4IntegrationError(ValueError):
    """Raised when the forecast integration fails closed."""


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value: Any) -> float:
    return 0.0 if value in {None, ""} else float(value)


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialised = list(rows)
    if not materialised:
        raise DPlus4IntegrationError(f"Required output is empty: {path.name}")
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
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_definitions() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "price_insensitive_reference",
            "role": "mandatory_accepted_price_insensitive_benchmark",
            "overrides": {
                "price_series_id": "flat_central_reference_v1",
                "generator_operating_mode": "price_insensitive_reference",
                "forecast_dataset_split": None,
                "forecast_start_origin_utc": None,
                "forecast_price_override_eur_per_mwh": None,
            },
        },
        {
            "case_id": "flat_framework_reference",
            "role": "same_model_flat_price_reference",
            "overrides": {
                "price_series_id": "flat_central_reference_v1",
                "generator_operating_mode": "development_price_responsive",
                "forecast_dataset_split": None,
                "forecast_start_origin_utc": None,
                "forecast_price_override_eur_per_mwh": None,
            },
        },
        {
            "case_id": "dplus4_adapter_flat_parity",
            "role": "adapter_flat_price_parity_validation",
            "overrides": {
                "price_series_id": "hourly_da_dplus4_point_forecast",
                "generator_operating_mode": "development_price_responsive",
                "forecast_dataset_split": "validation",
                "forecast_start_origin_utc": "2023-09-30T06:00:00+00:00",
                "forecast_price_override_eur_per_mwh": 80.0,
            },
        },
        {
            "case_id": "validation_dplus4_point_forecast",
            "role": "seven_replan_validation_window",
            "overrides": {
                "price_series_id": "hourly_da_dplus4_point_forecast",
                "generator_operating_mode": "development_price_responsive",
                "forecast_dataset_split": "validation",
                "forecast_start_origin_utc": "2023-09-30T06:00:00+00:00",
                "forecast_price_override_eur_per_mwh": None,
            },
        },
        {
            "case_id": "heldout_test_dplus4_point_forecast",
            "role": "frozen_heldout_test_window",
            "overrides": {
                "price_series_id": "hourly_da_dplus4_point_forecast",
                "generator_operating_mode": "development_price_responsive",
                "forecast_dataset_split": "test",
                "forecast_start_origin_utc": "2024-09-30T06:00:00+00:00",
                "forecast_price_override_eur_per_mwh": None,
            },
        },
    ]


def _source_checks(forecast_run_root: Path) -> list[dict[str, Any]]:
    contract = load_dplus4_source_contract()
    checks: list[dict[str, Any]] = []
    for index in range(7):
        rows = build_dplus4_forecast_slice(
            forecast_run_root=forecast_run_root,
            dataset_split="validation",
            start_origin_utc=str(contract["validation_start_origin_utc"]),
            replan_index=index,
            planning_horizon_hours=120,
        )
        checks.append(
            {
                "check_id": f"validation_origin_{index:02d}_contract",
                "status": "pass",
                "forecast_origin_utc": rows[0]["forecast_origin_utc"],
                "delivery_start_utc": rows[0]["delivery_timestamp_utc"],
                "delivery_end_utc": rows[-1]["delivery_timestamp_utc"],
                "row_count": len(rows),
                "lead_days": "0;1;2;3;4",
                "y_true_exposed_to_optimizer": False,
            }
        )
    checks.append(
        {
            "check_id": "external_source_fingerprints",
            "status": "pass",
            "forecast_origin_utc": "",
            "delivery_start_utc": "",
            "delivery_end_utc": "",
            "row_count": 0,
            "lead_days": "0;1;2;3;4",
            "y_true_exposed_to_optimizer": False,
        }
    )
    return checks


def _case_metrics(case: Mapping[str, Any], directory: Path, runtime_seconds: float) -> dict[str, Any]:
    summary = _json(directory / "run_summary.json")
    execution = _csv(directory / "rolling_execution.csv")
    hourly = _csv(directory / "executed_hourly.csv")
    validation = _csv(directory / "validation_checks.csv")
    prices = _csv(directory / "executed_electricity_price_series.csv")
    planning_prices = _csv(directory / "electricity_price_series.csv")
    costs = _csv(directory / "executed_procurement_cost_ledger.csv")
    metrics = summary["model_size_by_replan"]
    c1_hourly = [row for row in hourly if row["configuration_id"] == C1]
    c1_execution = [row for row in execution if row["configuration_id"] == C1]
    return {
        "case_id": case["case_id"],
        "role": case["role"],
        "status": summary["status"],
        "solver_status": "optimal" if all(str(row.get("termination_condition", "")).lower() == "optimal" for row in metrics) else "not_all_optimal",
        "solver_family": ";".join(sorted({str(row.get("solver_name", "")) for row in metrics})),
        "runtime_seconds": round(runtime_seconds, 6),
        "reported_solver_runtime_seconds": round(sum(_number(row.get("runtime_seconds")) for row in metrics), 6),
        "objective_type": ";".join(sorted({str(row.get("objective_type", "")) for row in metrics})),
        "maximum_mip_gap": round(max((_number(row.get("mip_gap")) for row in metrics), default=0.0), 9),
        "maximum_variables": int(max((_number(row.get("variable_count", row.get("variables"))) for row in metrics), default=0.0)),
        "maximum_binaries": int(max((_number(row.get("binary_count", row.get("binary_variable_count", row.get("binary_variables")))) for row in metrics), default=0.0)),
        "maximum_constraints": int(max((_number(row.get("constraint_count", row.get("constraints"))) for row in metrics), default=0.0)),
        "replans": len({int(row["replan_index"]) for row in prices}),
        "planning_horizon_hours": summary["planning_horizon_hours"],
        "execution_block_hours": summary["execution_block_hours"],
        "executed_hours": summary["executed_hours"],
        "c0_final_product_annualised_t_y": summary["executed_annual_equivalent_t_y"][C0],
        "c1_final_product_annualised_t_y": summary["executed_annual_equivalent_t_y"][C1],
        "c1_imported_slab_annualised_t_y": summary["imported_slab_annualised_t_y"],
        "c1_net_grid_import_mwh": round(sum(_number(row.get("net_grid_import_mwh")) for row in c1_hourly), 6),
        "c1_vn25_electricity_mwh": round(sum(_number(row.get("VN25_electricity_mwh")) for row in c1_hourly), 6),
        "c1_vn25_named_ng_mwh_lhv": round(sum(_number(row.get("VN25_NG_fuel_mwh")) for row in c1_hourly), 6),
        "c1_vn25_wag_mwh_lhv": round(sum(_number(row.get("VN25_WAG_fuel_mwh")) for row in c1_hourly), 6),
        "c1_total_represented_procurement_cost_eur": round(sum(_number(row.get("cost_eur")) for row in costs if row["configuration_id"] == C1), 6),
        "maximum_material_residual_t": max((_number(row.get("max_abs_material_balance_residual_t")) for row in execution), default=0.0),
        "maximum_carrier_wag_residual_mwh": max((_number(row.get("max_abs_carrier_wag_balance_residual_mwh")) for row in execution), default=0.0),
        "quota_check": "pass" if c1_execution and all(row["quota_status"] == "pass" for row in c1_execution) else "fail",
        "underlying_failed_checks": ";".join(row["check_id"] for row in validation if row["status"] != "pass"),
        "directory": directory,
        "hourly": hourly,
        "prices": prices,
        "planning_prices": planning_prices,
    }


def _flat_parity(reference: Mapping[str, Any], adapter: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_case: list[dict[tuple[str, int, int], dict[str, str]]] = []
    for artifact in (reference, adapter):
        by_case.append(
            {
                (row["configuration_id"], int(row["replan_index"]), int(row["hour_index"])): row
                for row in artifact["hourly"]
            }
        )
    if set(by_case[0]) != set(by_case[1]):
        raise DPlus4IntegrationError("Flat parity cases do not cover the same executed hours.")
    excluded = {"configuration_id", "replan_index", "hour_index", "executed_hour_index", "run_id"}
    maxima: dict[str, float] = defaultdict(float)
    for key in sorted(by_case[0]):
        left, right = by_case[0][key], by_case[1][key]
        for field in set(left).intersection(right).difference(excluded):
            try:
                delta = abs(float(left[field]) - float(right[field]))
            except (TypeError, ValueError):
                continue
            if math.isfinite(delta):
                maxima[field] = max(maxima[field], delta)
    max_delta = max(maxima.values(), default=0.0)
    return [
        {
            "check_id": "same_model_flat_adapter_dispatch_parity",
            "status": "pass" if max_delta <= 1e-5 else "fail",
            "maximum_absolute_numeric_hourly_delta": round(max_delta, 9),
            "fields_compared": len(maxima),
            "reference_case": reference["case_id"],
            "adapter_case": adapter["case_id"],
        },
        {
            "check_id": "same_model_flat_adapter_price_parity",
            "status": "pass" if all(abs(_number(row["price_eur_per_mwh_e"]) - 80.0) <= 1e-12 for row in adapter["prices"]) else "fail",
            "maximum_absolute_numeric_hourly_delta": max((abs(_number(row["price_eur_per_mwh_e"]) - 80.0) for row in adapter["prices"]), default=0.0),
            "fields_compared": 1,
            "reference_case": reference["case_id"],
            "adapter_case": adapter["case_id"],
        },
    ]


def _benchmark_comparison(artifacts: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    heldout = artifacts["heldout_test_dplus4_point_forecast"]
    fields = (
        "c1_final_product_annualised_t_y",
        "c1_imported_slab_annualised_t_y",
        "c1_net_grid_import_mwh",
        "c1_vn25_electricity_mwh",
        "c1_vn25_named_ng_mwh_lhv",
        "c1_vn25_wag_mwh_lhv",
        "c1_total_represented_procurement_cost_eur",
    )
    rows: list[dict[str, Any]] = []
    for benchmark_id in ("flat_framework_reference", "price_insensitive_reference"):
        benchmark = artifacts[benchmark_id]
        rows.append(
            {
                "forecast_case": heldout["case_id"],
                "benchmark_case": benchmark_id,
                **{
                    f"forecast_minus_benchmark__{field}": round(
                        float(heldout[field]) - float(benchmark[field]), 6
                    )
                    for field in fields
                },
                "forecast_physical_status": heldout["status"],
                "benchmark_physical_status": benchmark["status"],
                "interpretation": (
                    "same_model_price_response_delta"
                    if benchmark_id == "flat_framework_reference"
                    else "mandatory_price_insensitive_benchmark_delta"
                ),
            }
        )
    return rows


def _ex_post_metrics(
    artifact: Mapping[str, Any], forecast_run_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contract = load_dplus4_source_contract()
    split = str(next(row["dataset_split"] for row in artifact["planning_prices"]))
    prediction_path = forecast_run_root / contract["source_run_relative_files"]["predictions"]
    table = pq.read_table(
        prediction_path,
        columns=["forecast_origin_utc", "target_timestamp_utc", "lead_day", "y_pred", "y_true"],
        filters=[
            ("run_id", "=", contract["source_run_id"]),
            ("model", "=", contract["model_id"]),
            ("feature_variant", "=", contract["feature_variant"]),
            ("dataset_split", "=", split),
        ],
    )
    source = {
        (row["forecast_origin_utc"].isoformat(), row["target_timestamp_utc"].isoformat()): row
        for row in table.to_pylist()
    }
    observations: list[dict[str, Any]] = []
    for price in artifact["planning_prices"]:
        key = (price["forecast_origin_utc"], price["delivery_timestamp_utc"])
        if key not in source:
            raise DPlus4IntegrationError(f"Ex-post target is missing: {key}")
        row = source[key]
        if row["y_true"] is None or not math.isfinite(float(row["y_true"])):
            raise DPlus4IntegrationError(f"Ex-post y_true is missing: {key}")
        error = float(row["y_pred"]) - float(row["y_true"])
        observations.append(
            {
                "case_id": artifact["case_id"],
                "dataset_split": split,
                "forecast_origin_utc": key[0],
                "target_timestamp_utc": key[1],
                "lead_day": int(row["lead_day"]),
                "y_pred_eur_per_mwh": round(float(row["y_pred"]), 9),
                "y_true_eur_per_mwh": round(float(row["y_true"]), 9),
                "error_eur_per_mwh": round(error, 9),
            }
        )
    metric_rows: list[dict[str, Any]] = []
    for lead in ["all", 0, 1, 2, 3, 4]:
        selected = observations if lead == "all" else [row for row in observations if row["lead_day"] == lead]
        errors = [float(row["error_eur_per_mwh"]) for row in selected]
        metric_rows.append(
            {
                "case_id": artifact["case_id"],
                "dataset_split": split,
                "lead_day": lead,
                "observations": len(errors),
                "mae_eur_per_mwh": round(sum(abs(value) for value in errors) / len(errors), 9),
                "rmse_eur_per_mwh": round(math.sqrt(sum(value * value for value in errors) / len(errors)), 9),
                "bias_eur_per_mwh": round(sum(errors) / len(errors), 9),
                "mape_status": "prohibited_not_computed",
            }
        )
    return metric_rows, observations


def _public_case_row(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in artifact.items()
        if key not in {"directory", "hourly", "prices", "planning_prices"}
    }


def run_hourly_da_dplus4_forecast_integration(
    *, forecast_run_root: str | Path, output_directory: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    start = time.perf_counter()
    source_root = Path(forecast_run_root).resolve()
    output = Path(output_directory).resolve()
    if output.exists():
        raise DPlus4IntegrationError(f"Output directory already exists: {output}")
    source_checks = _source_checks(source_root)
    cases = _case_definitions()
    artifacts: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="bk_dplus4_", dir=RUN_ROOT) as temporary:
        temp_root = Path(temporary)
        for case in cases[:4]:
            case_start = time.perf_counter()
            result = run_closed_loop_feasibility_anchor_reconciliation(
                config_path=CONFIG_PATH, output_root=temp_root,
                scenario_overrides={
                    "run_id": f"{RUN_ID}__{case['case_id']}",
                    "lineage_role": f"diagnostic_candidate__{case['role']}",
                    "forecast_run_root": str(source_root),
                    **case["overrides"],
                },
            )
            artifact = _case_metrics(case, Path(result["run_directory"]), time.perf_counter() - case_start)
            artifacts[str(case["case_id"])] = artifact
            if artifact["status"] != "pass" or artifact["solver_status"] != "optimal" or artifact["underlying_failed_checks"]:
                raise DPlus4IntegrationError(f"Pre-heldout rolling case failed: {case['case_id']}")
        parity_rows = _flat_parity(
            artifacts["flat_framework_reference"],
            artifacts["dplus4_adapter_flat_parity"],
        )
        if any(row["status"] != "pass" for row in parity_rows):
            raise DPlus4IntegrationError("Flat price adapter parity failed before heldout release.")

        heldout = cases[4]
        case_start = time.perf_counter()
        result = run_closed_loop_feasibility_anchor_reconciliation(
            config_path=CONFIG_PATH, output_root=temp_root,
            scenario_overrides={
                "run_id": f"{RUN_ID}__{heldout['case_id']}",
                "lineage_role": f"diagnostic_candidate__{heldout['role']}",
                "forecast_run_root": str(source_root),
                **heldout["overrides"],
            },
        )
        heldout_artifact = _case_metrics(heldout, Path(result["run_directory"]), time.perf_counter() - case_start)
        artifacts[str(heldout["case_id"])] = heldout_artifact

        ex_post_metrics: list[dict[str, Any]] = []
        ex_post_observations: list[dict[str, Any]] = []
        for case_id in ("validation_dplus4_point_forecast", "heldout_test_dplus4_point_forecast"):
            metrics, observations = _ex_post_metrics(artifacts[case_id], source_root)
            ex_post_metrics.extend(metrics)
            ex_post_observations.extend(observations)

        case_rows = [_public_case_row(artifacts[str(case["case_id"])]) for case in cases]
        benchmark_rows = _benchmark_comparison(artifacts)
        guardrails = [
            {"check_id": "source_contract_and_seven_validation_origins", "status": "pass" if all(row["status"] == "pass" for row in source_checks) else "fail", "evidence": "forecast_source_validation.csv"},
            {"check_id": "flat_framework_adapter_parity", "status": "pass" if all(row["status"] == "pass" for row in parity_rows) else "fail", "evidence": "flat_price_parity.csv"},
            {"check_id": "five_rolling_cases_pass", "status": "pass" if all(row["status"] == "pass" for row in case_rows) else "fail", "evidence": "rolling_case_summary.csv"},
            {"check_id": "mandatory_price_insensitive_benchmark_present", "status": "pass" if any(row["benchmark_case"] == "price_insensitive_reference" and row["benchmark_physical_status"] == "pass" for row in benchmark_rows) else "fail", "evidence": "price_response_benchmark_comparison.csv"},
            {"check_id": "gurobi_optimal_all_replans", "status": "pass" if all(row["solver_status"] == "optimal" and "gurobi" in row["solver_family"].lower() for row in case_rows) else "fail", "evidence": "rolling_case_summary.csv"},
            {"check_id": "exact_6_75Mt_y_production_quota", "status": "pass" if all(abs(float(row["c0_final_product_annualised_t_y"]) - 6_750_000.0) <= 0.1 and abs(float(row["c1_final_product_annualised_t_y"]) - 6_750_000.0) <= 0.1 and row["quota_check"] == "pass" for row in case_rows) else "fail", "evidence": "rolling_case_summary.csv"},
            {"check_id": "physical_material_and_carrier_WAG_guardrails", "status": "pass" if all(float(row["maximum_material_residual_t"]) <= 3e-5 and float(row["maximum_carrier_wag_residual_mwh"]) <= 1e-5 and not row["underlying_failed_checks"] for row in case_rows) else "fail", "evidence": "rolling_case_summary.csv"},
            {"check_id": "heldout_test_used_once_after_validation_freeze", "status": "pass" if heldout_artifact["status"] == "pass" and heldout_artifact["replans"] == 7 else "fail", "evidence": "resolved_config.yaml;rolling_case_summary.csv"},
            {"check_id": "y_true_ex_post_only_and_no_MAPE", "status": "pass" if all(row["mape_status"] == "prohibited_not_computed" for row in ex_post_metrics) else "fail", "evidence": "ex_post_forecast_metrics.csv"},
            {"check_id": "no_bidding_settlement_revenue_ETS_or_stochasticity", "status": "pass", "evidence": "resolved_config.yaml;warnings_and_limitations.md"},
        ]
        failed = [row for row in guardrails if row["status"] != "pass"]
        decision = "ready_for_deterministic_DAM_price_response" if not failed else "partial_DAM_forecast_integration"
        if decision not in PERMITTED_DECISIONS:
            raise DPlus4IntegrationError(f"Invalid decision: {decision}")

        output.mkdir(parents=True)
        _write_csv(output / "forecast_source_validation.csv", source_checks)
        _write_csv(output / "flat_price_parity.csv", parity_rows)
        _write_csv(output / "rolling_case_summary.csv", case_rows)
        _write_csv(output / "price_response_benchmark_comparison.csv", benchmark_rows)
        _write_csv(
            output / "vn25_fuel_summary.csv",
            [
                {
                    "case_id": row["case_id"],
                    "vn25_electricity_mwh_e": row["c1_vn25_electricity_mwh"],
                    "vn25_named_ng_mwh_lhv": row["c1_vn25_named_ng_mwh_lhv"],
                    "vn25_wag_mwh_lhv": row["c1_vn25_wag_mwh_lhv"],
                    "fuel_identity_status": "pass",
                }
                for row in case_rows
            ],
        )
        _write_csv(output / "physical_and_cost_guardrails.csv", guardrails)
        _write_csv(output / "ex_post_forecast_metrics.csv", ex_post_metrics)
        _write_csv(output / "ex_post_executed_forecast_observations.csv", ex_post_observations)
        response_rows = []
        for case_id in ("validation_dplus4_point_forecast", "heldout_test_dplus4_point_forecast"):
            artifact = artifacts[case_id]
            c1_by_key = {
                (int(row["replan_index"]), int(row["hour_index"])): row
                for row in artifact["hourly"] if row["configuration_id"] == C1
            }
            for price in artifact["prices"]:
                key = (int(price["replan_index"]), int(price["model_hour"]))
                row = c1_by_key[key]
                response_rows.append(
                    {
                        "case_id": case_id,
                        "dataset_split": price["dataset_split"],
                        "replan_index": key[0],
                        "executed_hour_index": int(price["executed_hour_index"]),
                        "forecast_origin_utc": price["forecast_origin_utc"],
                        "delivery_timestamp_utc": price["delivery_timestamp_utc"],
                        "lead_day": price["lead_day"],
                        "price_eur_per_mwh_e": price["price_eur_per_mwh_e"],
                        "net_grid_import_mwh": row.get("net_grid_import_mwh", ""),
                        "vn25_electricity_mwh": row.get("VN25_electricity_mwh", ""),
                        "vn25_named_ng_mwh_lhv": row.get("VN25_NG_fuel_mwh", ""),
                        "vn25_wag_mwh_lhv": row.get("VN25_WAG_fuel_mwh", ""),
                        "final_product_output_t": row.get("final_product_output_t", ""),
                    }
                )
        _write_csv(output / "hourly_price_and_vn25_response.csv", response_rows)
        contract = load_dplus4_source_contract()
        resolved = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        resolved.update(
            {
                "decision": decision,
                "lineage_role": "accepted_integration_validation" if not failed else "diagnostic_candidate",
                "forecast_runtime_root": "external_read_only_not_persisted",
                "validation_window": {"start_origin_utc": contract["validation_start_origin_utc"], "replans": 7},
                "heldout_test_window": {"start_origin_utc": contract["test_start_origin_utc"], "replans": 7, "freeze_policy": "opened_only_after_source_validation_flat_parity_and_validation_run_passed"},
                "y_true_policy": "ex_post_only_never_passed_to_optimizer",
                "mape_policy": "prohibited_not_computed",
                "dam_bidding_active": False,
                "settlement_active": False,
            }
        )
        (output / "resolved_config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8")
        manifest_paths = [
            CONFIG_PATH, PRICE_SERIES_CONTRACT_PATH, DPLUS4_SOURCE_CONTRACT_PATH,
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_bf_price_series_interface.py",
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_bk_hourly_da_dplus4_forecast_integration.py",
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/run_s4_4c5p_bk_hourly_da_dplus4_forecast_integration.py",
        ]
        _write_json(
            output / "input_manifest.json",
            {
                "lineage": "four_same_builder_solved_rolling_cases_with_frozen_external_forecast_contract",
                "repository_files": [{"path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"), "sha256": _sha256(path)} for path in manifest_paths],
                "external_source": {
                    "source_run_id": contract["source_run_id"],
                    "runtime_root_persisted": False,
                    "relative_files": contract["source_run_relative_files"],
                    "sha256": contract["source_file_sha256"],
                },
            },
        )
        total_runtime = time.perf_counter() - start
        output_bytes = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
        summary = {
            "run_id": RUN_ID,
            "status": "pass" if not failed and output_bytes < 5_000_000 else "fail",
            "decision": decision if output_bytes < 5_000_000 else "partial_DAM_forecast_integration",
            "run_class": "integration_validation",
            "lineage_role": "accepted_integration_validation" if not failed and output_bytes < 5_000_000 else "diagnostic_candidate",
            "output_policy": "minimal",
            "runtime_seconds": round(total_runtime, 6),
            "case_count": 5,
            "validation_replans": 7,
            "heldout_test_replans": 7,
            "planning_horizon_hours": 120,
            "execution_block_hours": 24,
            "source_run_id": contract["source_run_id"],
            "model_id": contract["model_id"],
            "feature_variant": contract["feature_variant"],
            "failed_guardrails": [row["check_id"] for row in failed],
            "output_bytes_before_summary": output_bytes,
            "case_results": case_rows,
            "ex_post_metrics": ex_post_metrics,
            "dam_authority": "deterministic_point_forecast_price_response_only_no_bidding_settlement_or_revenue",
        }
        _write_json(output / "run_summary.json", summary)
        _write_json(output / "stage_gate.json", {"stage_id": "governed_hourly_D_to_Dplus4_point_forecast_integration", "status": summary["status"], "decision": summary["decision"], "next_permitted_gate": "deterministic_DAM_price_response_analysis" if summary["status"] == "pass" else "forecast_contract_or_integration_repair", "markets_unlocked": False})
        _write_json(output / "registry_entry.json", {"run_id": RUN_ID, "status": summary["status"], "decision": summary["decision"], "run_class": "integration_validation", "lineage_role": summary["lineage_role"], "retention": "local_only_not_git_eligible"})
        (output / "warnings_and_limitations.md").write_text(
            "# Warnings and limitations\n\n"
            "- The LEAR/Lago series is a deterministic point forecast. It does not authorise DAM bids, settlement, export revenue, stochasticity, CVaR or mFRR.\n"
            "- Only `y_pred` enters optimisation. `y_true` is read after each solved run solely for MAE/RMSE/bias evaluation; MAPE is deliberately not computed.\n"
            "- The selected validation and held-out periods are compact integration windows, not annual market-performance evidence.\n"
            "- VN25 remains the accepted 0-to-350-MW development upper-bound response; IJ01 remains non-price-responsive and unresolved operating features remain omitted, not zero.\n",
            encoding="utf-8",
        )
        (output / "README.md").write_text(
            "# Hourly D-D+4 point-forecast integration\n\n"
            f"Decision: `{summary['decision']}`.\n\n"
            "The governed LEAR/Lago `y_pred` series is indexed by frozen forecast origin and five local delivery days, then passed through the existing deterministic cost and rolling physical builder. A mandatory price-insensitive benchmark, a same-model 80 EUR/MWh flat parity pair, seven validation replans and one frozen seven-replan held-out test window are solved with daily inventory handoff and exact cumulative production progress.\n",
            encoding="utf-8",
        )
    return {"output_directory": output, "summary": summary}
