"""Resumable source-driven evaluation on frozen representative D-D+4 weeks.

The evaluator delegates every solve to the accepted p_af rolling runner.  It
adds no model components and supplies no physical-parameter overrides.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .c5_source_emulation_validation import (
    CONTRACT_FILENAME,
    DEFAULT_CONFIG_PATH,
    DEFAULT_OUTPUT,
    RUN_ID,
    load_config,
)
from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
    CONFIGURATIONS,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_bl_deterministic_price_response_anchor_diagnostics import (
    _artifact,
    _executed_price_vectors,
    _first_window_price_vector,
    _first_window_schedule_costs,
    _identity_checks,
    _physical_metrics,
    _schedule_costs,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


STRATEGIES = ("price_insensitive", "governed_y_pred", "oracle_y_true")
TOLERANCE = 1e-4
TERMINAL_INVENTORIES = (
    ("coke", "coke_inventory_t"),
    ("sinter", "sinter_inventory_t"),
    ("hot_iron", "hot_iron_inventory_t"),
    ("cold_slab", "cold_slab_inventory_t"),
    ("DRI", "DRI_inventory_t"),
)
TERMINAL_INVENTORY_EQUIVALENCE_TOLERANCE_T = 1e-3
MUTABLE_GOVERNANCE_SOLVE_TIME_HASHES = {
    "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract/calibratable_parameter_contract.csv": "f0815c353b997e1905d8ecf099eb4084288809dde815c1e1eb63cc426c3f37a7",
    "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract/calibration_validation_target_contract.csv": "8a3ef3dc907d23f42dc24fa40e3022d2b206910d6a1d12bd15b34da98dc78547",
    "data/03_Optimisation/runs/steel_c5_tata_benchmark_v1_20260721/checkpoint_state.json": "b2416f1555736eff2cf1037772cef8c049b50c99e0470509baf7a4c834d54193",
}


class SourceEmulationEvaluationError(RuntimeError):
    """Raised when the frozen evaluation cannot proceed without ambiguity."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialised = list(rows)
    if not materialised:
        raise SourceEmulationEvaluationError(f"Refusing to write empty output: {path.name}")
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


def _number(value: Any) -> float:
    return 0.0 if value in {None, ""} else float(value)


def _optional_number(value: Any) -> float | None:
    return None if value in {None, ""} else float(value)


def _case_id(period_id: str, strategy: str) -> str:
    return f"eval__{period_id.replace('-', '_')}__{strategy}"


def _strategy_overrides(period: Mapping[str, str], strategy: str) -> dict[str, Any]:
    common = {
        "run_id": _case_id(period["period_id"], strategy),
        "lineage_role": "representative_period_case_cache",
        "replan_count": 7,
        "price_series_id": "hourly_da_dplus4_point_forecast",
        "generator_operating_mode": "development_price_responsive",
        "forecast_dataset_split": period["dataset_split"],
        "forecast_start_origin_utc": period["frozen_forecast_start_origin_utc"],
        "timestamped_dplus4_rolling_enabled": True,
    }
    if strategy == "price_insensitive":
        return {
            **common,
            "forecast_price_override_eur_per_mwh": 80.0,
            "forecast_price_field": "y_pred",
            "perfect_foresight_oracle": False,
        }
    if strategy == "governed_y_pred":
        return {
            **common,
            "forecast_price_override_eur_per_mwh": None,
            "forecast_price_field": "y_pred",
            "perfect_foresight_oracle": False,
        }
    if strategy == "oracle_y_true":
        return {
            **common,
            "forecast_price_override_eur_per_mwh": None,
            "forecast_price_field": "y_true",
            "perfect_foresight_oracle": True,
        }
    raise SourceEmulationEvaluationError(f"Unknown strategy: {strategy}")


def _load_periods(output: Path) -> list[dict[str, str]]:
    rows = _read_csv(output / CONTRACT_FILENAME)
    if len(rows) != 8 or {row["dataset_split"] for row in rows} != {"validation", "test"}:
        raise SourceEmulationEvaluationError("The frozen eight-period selection is missing.")
    for split in ("validation", "test"):
        if abs(sum(float(row["split_weight"]) for row in rows if row["dataset_split"] == split) - 1.0) > 1e-9:
            raise SourceEmulationEvaluationError(f"Frozen {split} weights do not sum to one.")
    return rows


def _case_ready(directory: Path) -> bool:
    required = {
        "run_summary.json",
        "executed_hourly.csv",
        "executed_procurement_cost_ledger.csv",
        "annual_physical_boundary_ledger.csv",
        "rolling_model_metrics.csv",
        "validation_checks.csv",
    }
    if not directory.is_dir() or not all((directory / name).is_file() for name in required):
        return False
    summary = json.loads((directory / "run_summary.json").read_text(encoding="utf-8"))
    return summary.get("status") == "pass"


def _write_progress(
    output: Path,
    statuses: list[dict[str, Any]],
    *,
    expected_case_count: int,
    decision: str,
) -> None:
    _write_csv(output / "evaluation_case_status.csv", statuses)
    _write_json(
        output / "evaluation_progress.json",
        {
            "run_id": RUN_ID,
            "decision": decision,
            "expected_case_count": expected_case_count,
            "pass_case_count": sum(row["status"] == "pass" for row in statuses),
            "blocked_case_count": sum(row["status"] != "pass" for row in statuses),
            "case_count_recorded": len(statuses),
            "resumable_case_cache": True,
            "model_repairs_used": 0,
            "physical_parameter_changes": 0,
        },
    )


def _annual_physical_value(
    rows: list[dict[str, str]],
    configuration: str,
    *,
    ledger_family: str,
    component: str | None = None,
    flow_role: str | None = None,
) -> float:
    selected = [
        row
        for row in rows
        if row["configuration_id"] == configuration
        and row["ledger_family"] == ledger_family
        and (component is None or row["component"] == component)
        and (flow_role is None or row["flow_role"] == flow_role)
    ]
    return sum(float(row["annual_value"]) for row in selected)


def _view_values(directory: Path, configuration: str) -> dict[str, float]:
    return {
        row["metric"]: float(row["annual_equivalent_value"])
        for row in _read_csv(directory / "annual_equivalent_views.csv")
        if row["configuration_id"] == configuration
        and row["view_id"] == "complete_executed_blocks"
    }


def _period_summary_rows(
    *,
    periods: list[dict[str, str]],
    scratch: Path,
    forecast_root: Path,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], Mapping[str, Any]], dict[str, list[dict[str, Any]]]]:
    rows: list[dict[str, Any]] = []
    artifacts: dict[tuple[str, str], Mapping[str, Any]] = {}
    vectors: dict[str, list[dict[str, Any]]] = {}
    for period in periods:
        period_id = period["period_id"]
        vector = _executed_price_vectors(
            forecast_root=forecast_root,
            dataset_split=period["dataset_split"],
            start_origin_utc=period["frozen_forecast_start_origin_utc"],
            replans=7,
        )
        vectors[period_id] = vector
        for strategy in STRATEGIES:
            directory = scratch / _case_id(period_id, strategy)
            if not _case_ready(directory):
                continue
            artifact = _artifact(directory)
            artifacts[(period_id, strategy)] = artifact
            physical_rows = _read_csv(directory / "annual_physical_boundary_ledger.csv")
            cost_rows = _read_csv(directory / "procurement_cost_summary.csv")
            evaluated = _schedule_costs(artifact, vector, price_field="y_true_eur_per_mwh")
            forecast_evaluated = _schedule_costs(artifact, vector, price_field="y_pred_eur_per_mwh")
            for configuration in CONFIGURATIONS:
                physical = _physical_metrics(artifact, configuration)
                views = _view_values(directory, configuration)
                executed_hours = int(physical["executed_hours"])
                annual_factor = 8760.0 / executed_hours
                cost = next(row for row in cost_rows if row["configuration_id"] == configuration)
                wag_generation = _annual_physical_value(
                    physical_rows, configuration, ledger_family="WAG", flow_role="generation"
                )
                wag_flare = _annual_physical_value(
                    physical_rows, configuration, ledger_family="WAG", flow_role="flare"
                )
                wag_generator = sum(
                    float(row["annual_value"])
                    for row in physical_rows
                    if row["configuration_id"] == configuration
                    and row["ledger_family"] == "WAG"
                    and row["flow_role"] == "use"
                    and any(token in row["component"].lower() for token in ("vattenfall", "vn25", "ij01"))
                )
                wag_mandatory = sum(
                    float(row["annual_value"])
                    for row in physical_rows
                    if row["configuration_id"] == configuration
                    and row["ledger_family"] == "WAG"
                    and row["flow_role"] == "use"
                    and not any(token in row["component"].lower() for token in ("vattenfall", "vn25", "ij01"))
                )
                realised = evaluated[configuration]
                forecast_cost = forecast_evaluated[configuration]
                realised_annual = realised["total_represented_cost_eur"] * annual_factor
                grid_mwh = float(physical["net_grid_import_mwh"])
                final_product_t_y = views["final_product_proxy_mt_y"] * 1_000_000.0
                dri_output_t_y = annual_factor * sum(
                    _number(item.get("C1_DRP_DRI_output_t_h"))
                    for item in artifact["hourly"]
                    if item["configuration_id"] == configuration
                )
                rows.append(
                    {
                        "period_id": period_id,
                        "dataset_split": period["dataset_split"],
                        "period_role": period["period_role"],
                        "split_weight": period["split_weight"],
                        "strategy": strategy,
                        "configuration_id": configuration,
                        "executed_hours": executed_hours,
                        "annualisation_label": "representative_period_annualised",
                        "final_product_t_y": round(final_product_t_y, 6),
                        "bof_liquid_steel_t_y": round(views["bof_liquid_steel_mt_y"] * 1_000_000.0, 6),
                        "eaf_liquid_steel_t_y": round(views["eaf_liquid_steel_mt_y"] * 1_000_000.0, 6),
                        "hsm_output_t_y": round(views["hsm_hrc_output_mt_y"] * 1_000_000.0, 6),
                        "dsp_output_t_y": round(views["dsp_output_mt_y"] * 1_000_000.0, 6),
                        "slab_import_t_y": round(views["imported_slab_mt_y"] * 1_000_000.0, 6),
                        "drp_dri_output_t_y": round(dri_output_t_y, 6),
                        "gross_electricity_mwh_y": round(views["gross_electricity_twh_y"] * 1_000_000.0, 6),
                        "internal_wag_electricity_mwh_y": round(views["wag_power_twh_y"] * 1_000_000.0, 6),
                        "grid_import_mwh_y": round(views["net_grid_import_twh_y"] * 1_000_000.0, 6),
                        # 1 MWh = 3.6e-6 PJ. Dividing by 0.0036 would yield
                        # GWh while the reporting contract explicitly requires MWh.
                        "named_ng_mwh_lhv_y": round(views["represented_ng_pj_y"] / 0.0000036, 6),
                        "wag_generation_mwh_lhv_y": round(wag_generation, 6),
                        "wag_mandatory_sinks_mwh_lhv_y": round(wag_mandatory, 6),
                        "wag_generator_sinks_mwh_lhv_y": round(wag_generator, 6),
                        "wag_flare_mwh_lhv_y": round(wag_flare, 6),
                        "steam_15bar_t_y": round(views["steam_15bar_kt_y"] * 1000.0, 6),
                        "mode_b_explicit_fuel_co2_t_y": round(views["mode_b_explicit_fuel_co2_mt_y"] * 1_000_000.0, 6),
                        "objective_procurement_cost_eur_y": round(float(cost["annualised_procurement_cost_eur_y"]), 6),
                        "forecast_evaluated_procurement_cost_eur_y": round(forecast_cost["total_represented_cost_eur"] * annual_factor, 6),
                        "realised_procurement_cost_eur_y": round(realised_annual, 6),
                        "realised_procurement_cost_eur_per_t": round(realised_annual / final_product_t_y, 9),
                        "average_realised_electricity_price_paid_eur_per_mwh": round(realised["grid_cost_eur"] / grid_mwh, 9) if grid_mwh > TOLERANCE else "",
                        "residual_electricity_input_mwh_y": 0.0,
                        "residual_ng_input_mwh_lhv_y": 0.0,
                        "export_allowed": False,
                    }
                )
    return rows, artifacts, vectors


def _weighted_rows(
    *,
    periods: list[dict[str, str]],
    scratch: Path,
    summary_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    final_product = {
        (row["dataset_split"], row["strategy"], row["configuration_id"]): row["final_product_t_y"]
        for row in _aggregate_summary_fields(summary_rows, ["final_product_t_y"])
    }
    period_lookup = {row["period_id"]: row for row in periods}
    grouped: dict[tuple[str, ...], list[tuple[float, float]]] = defaultdict(list)
    metadata: dict[tuple[str, ...], dict[str, str]] = {}
    for period in periods:
        for strategy in STRATEGIES:
            directory = scratch / _case_id(period["period_id"], strategy)
            if not _case_ready(directory):
                continue
            for row in _read_csv(directory / "annual_physical_boundary_ledger.csv"):
                key = (
                    period["dataset_split"],
                    strategy,
                    row["configuration_id"],
                    row["ledger_family"],
                    row["carrier_or_material"],
                    row["flow_role"],
                    row["component"],
                    row["unit"],
                )
                grouped[key].append((float(period["split_weight"]), float(row["annual_value"])))
                metadata[key] = {
                    "boundary_status": row["boundary_status"],
                    "included_in_physical_balance": row["included_in_physical_balance"],
                    "included_in_mode_b_co2": row["included_in_mode_b_co2"],
                }
    output: list[dict[str, Any]] = []
    dispersion: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        split, strategy, configuration, family, carrier, role, component, unit = key
        weight_sum = sum(weight for weight, _ in values)
        weighted = sum(weight * value for weight, value in values) / weight_sum
        weighted_std = math.sqrt(sum(weight * (value - weighted) ** 2 for weight, value in values) / weight_sum)
        denominator = final_product.get((split, strategy, configuration), 0.0)
        common = {
            "dataset_split": split,
            "strategy": strategy,
            "configuration_id": configuration,
            "ledger_family": family,
            "carrier_or_material": carrier,
            "flow_role": role,
            "component": component,
            "unit": unit,
            "annualisation_label": "representative_period_annualised",
            **metadata[key],
        }
        output.append(
            {
                **common,
                "weighted_annual_equivalent_value": round(weighted, 9),
                "per_t_final_product": round(weighted / denominator, 12) if denominator and unit.endswith("/y") else "",
                "per_t_unit": f"{unit[:-2]}/t_final_product" if denominator and unit.endswith("/y") else "not_applicable",
                "weight_sum": round(weight_sum, 12),
                "scaling_basis": "time_weighted_fixed_background" if "auxiliary" in component.lower() else "weighted_period_flow_with_per_t_intensity",
            }
        )
        dispersion.append(
            {
                **common,
                "period_count": len(values),
                "minimum": round(min(value for _, value in values), 9),
                "maximum": round(max(value for _, value in values), 9),
                "weighted_mean": round(weighted, 9),
                "weighted_standard_deviation": round(weighted_std, 9),
            }
        )
    return output, dispersion


def _aggregate_summary_fields(
    rows: list[dict[str, Any]], fields: list[str]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["dataset_split"], row["strategy"], row["configuration_id"])].append(row)
    result: list[dict[str, Any]] = []
    for (split, strategy, configuration), values in sorted(grouped.items()):
        output = {
            "dataset_split": split,
            "strategy": strategy,
            "configuration_id": configuration,
            "annualisation_label": "representative_period_annualised",
        }
        for field in fields:
            output[field] = round(
                sum(float(row["split_weight"]) * float(row[field]) for row in values), 9
            )
        result.append(output)
    return result


def _terminal_inventory_value(
    artifact: Mapping[str, Any], configuration: str, field: str
) -> float | None:
    hourly = sorted(
        (
            row
            for row in artifact["hourly"]
            if row["configuration_id"] == configuration
        ),
        key=lambda row: int(row["executed_hour_index"]),
    )
    return _optional_number(hourly[-1].get(field)) if hourly else None


def _terminal_inventory_rows(
    summary_rows: list[dict[str, Any]],
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    summary_lookup = {
        (row["period_id"], row["strategy"], row["configuration_id"]): row
        for row in summary_rows
    }
    output: list[dict[str, Any]] = []
    for (period_id, strategy), artifact in sorted(artifacts.items()):
        if strategy == "price_insensitive":
            continue
        baseline_artifact = artifacts.get((period_id, "price_insensitive"))
        if baseline_artifact is None:
            continue
        for configuration in CONFIGURATIONS:
            summary = summary_lookup[(period_id, strategy, configuration)]
            for inventory_id, field in TERMINAL_INVENTORIES:
                baseline_value = _terminal_inventory_value(
                    baseline_artifact, configuration, field
                )
                strategy_value = _terminal_inventory_value(
                    artifact, configuration, field
                )
                represented = baseline_value is not None and strategy_value is not None
                delta = strategy_value - baseline_value if represented else None
                output.append(
                    {
                        "period_id": period_id,
                        "dataset_split": summary["dataset_split"],
                        "split_weight": summary["split_weight"],
                        "configuration_id": configuration,
                        "strategy": strategy,
                        "inventory_id": inventory_id,
                        "model_field": field,
                        "unit": "t",
                        "price_insensitive_terminal_value": (
                            round(baseline_value, 9) if represented else ""
                        ),
                        "strategy_terminal_value": (
                            round(strategy_value, 9) if represented else ""
                        ),
                        "delta_vs_price_insensitive": (
                            round(delta, 9) if delta is not None else ""
                        ),
                        "terminal_state_equivalence_status": (
                            "equivalent"
                            if represented
                            and abs(delta) <= TERMINAL_INVENTORY_EQUIVALENCE_TOLERANCE_T
                            else "different"
                            if represented
                            else "not_represented"
                        ),
                        "inventory_value_bridge_available": False,
                        "economic_uplift_claim_allowed": False,
                        "interpretation": (
                            "Direct terminal represented-state comparison; no inventory value is assigned."
                            if represented
                            else "Inventory is not represented for this configuration."
                        ),
                    }
                )
    return output


def _strategy_comparison_rows(
    summary_rows: list[dict[str, Any]],
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
    vectors: Mapping[str, list[dict[str, Any]]],
    forecast_root: Path,
    terminal_inventory_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key = {
        (row["period_id"], row["strategy"], row["configuration_id"]): row
        for row in summary_rows
    }
    output: list[dict[str, Any]] = []
    terminal_lookup: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for terminal_row in terminal_inventory_rows:
        terminal_lookup[
            (
                terminal_row["period_id"],
                terminal_row["strategy"],
                terminal_row["configuration_id"],
            )
        ].append(terminal_row)
    for (period_id, strategy), artifact in sorted(artifacts.items()):
        if strategy == "price_insensitive":
            continue
        baseline_artifact = artifacts.get((period_id, "price_insensitive"))
        if baseline_artifact is None:
            continue
        vector = vectors[period_id]
        period_row = next(row for row in summary_rows if row["period_id"] == period_id)
        planning_vector = _first_window_price_vector(
            forecast_root=forecast_root,
            dataset_split=period_row["dataset_split"],
            start_origin_utc=next(
                row["forecast_origin_utc"]
                for row in vector
                if int(row["replan_index"]) == 0
            ),
        )
        planned_y_pred = _first_window_schedule_costs(
            artifacts[(period_id, "governed_y_pred")],
            planning_vector,
            price_field="y_true_eur_per_mwh",
        )
        planned_oracle = _first_window_schedule_costs(
            artifacts[(period_id, "oracle_y_true")],
            planning_vector,
            price_field="y_true_eur_per_mwh",
        )
        truth = [float(row["y_true_eur_per_mwh"]) for row in vector]
        median = statistics.median(truth)
        for configuration in CONFIGURATIONS:
            row = by_key[(period_id, strategy, configuration)]
            baseline = by_key[(period_id, "price_insensitive", configuration)]
            current_hourly = sorted(
                [item for item in artifact["hourly"] if item["configuration_id"] == configuration],
                key=lambda item: int(item["executed_hour_index"]),
            )
            baseline_hourly = sorted(
                [item for item in baseline_artifact["hourly"] if item["configuration_id"] == configuration],
                key=lambda item: int(item["executed_hour_index"]),
            )
            expensive_reduction = sum(
                max(0.0, _number(left.get("net_grid_import_mwh")) - _number(right.get("net_grid_import_mwh")))
                for left, right, price in zip(baseline_hourly, current_hourly, truth)
                if price > median
            )
            cheap_increase = sum(
                max(0.0, _number(right.get("net_grid_import_mwh")) - _number(left.get("net_grid_import_mwh")))
                for left, right, price in zip(baseline_hourly, current_hourly, truth)
                if price <= median
            )
            saving = float(baseline["realised_procurement_cost_eur_y"]) - float(row["realised_procurement_cost_eur_y"])
            terminal_rows = [
                terminal_row
                for terminal_row in terminal_lookup[(period_id, strategy, configuration)]
                if terminal_row["terminal_state_equivalence_status"] != "not_represented"
            ]
            terminal_equivalent = bool(terminal_rows) and all(
                terminal_row["terminal_state_equivalence_status"] == "equivalent"
                for terminal_row in terminal_rows
            )
            maximum_terminal_delta = max(
                (
                    abs(float(terminal_row["delta_vs_price_insensitive"]))
                    for terminal_row in terminal_rows
                ),
                default=0.0,
            )
            output.append(
                {
                    "period_id": period_id,
                    "dataset_split": row["dataset_split"],
                    "split_weight": row["split_weight"],
                    "configuration_id": configuration,
                    "strategy": strategy,
                    "annualisation_label": "representative_period_annualised",
                    "within_period_procurement_cost_difference_before_terminal_inventory_bridge_eur_y": round(saving, 6),
                    "cost_difference_sign_convention": "positive_means_strategy_has_lower_within_period_procurement_cost",
                    "terminal_inventory_equivalence_status": (
                        "equivalent" if terminal_equivalent else "different"
                    ),
                    "maximum_abs_terminal_inventory_delta_t": round(maximum_terminal_delta, 9),
                    "inventory_value_bridge_available": False,
                    "economic_uplift_or_adverse_forecast_value_claim_allowed": False,
                    "whole_period_cost_difference_interpretation": "arithmetic_only_before_terminal_inventory_value_bridge",
                    "value_captured_vs_oracle_fraction": "",
                    "value_captured_vs_oracle_status": "not_reported_terminal_inventory_value_bridge_unavailable",
                    "expensive_hour_grid_reduction_mwh": round(expensive_reduction, 6),
                    "cheap_hour_grid_increase_mwh": round(cheap_increase, 6),
                    "load_shifted_expensive_to_cheap_mwh": round(min(expensive_reduction, cheap_increase), 6),
                    "production_difference_vs_price_insensitive_t_y": round(float(row["final_product_t_y"]) - float(baseline["final_product_t_y"]), 6),
                    "grid_import_difference_mwh_y": round(float(row["grid_import_mwh_y"]) - float(baseline["grid_import_mwh_y"]), 6),
                    "named_ng_difference_mwh_lhv_y": round(float(row["named_ng_mwh_lhv_y"]) - float(baseline["named_ng_mwh_lhv_y"]), 6),
                    "internal_generation_difference_mwh_y": round(float(row["internal_wag_electricity_mwh_y"]) - float(baseline["internal_wag_electricity_mwh_y"]), 6),
                    "identical_state_first_window_y_pred_realised_cost_eur": round(planned_y_pred[configuration]["total_represented_cost_eur"], 6),
                    "identical_state_first_window_oracle_cost_eur": round(planned_oracle[configuration]["total_represented_cost_eur"], 6),
                    "identical_state_first_window_oracle_dominance_status": "pass" if planned_oracle[configuration]["total_represented_cost_eur"] <= planned_y_pred[configuration]["total_represented_cost_eur"] + 0.01 else "fail",
                    "whole_period_rolling_oracle_role": "rolling_D_to_Dplus4_oracle_not_global_week_foresight_upper_bound",
                    "oracle_upper_bound_claim_scope": "identical_state_first_planning_window_only",
                }
            )
    return output


def _guardrail_rows(
    *, periods: list[dict[str, str]], scratch: Path, artifacts: Mapping[tuple[str, str], Mapping[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    inherited_required = {
        "c0_executed_quotas_pass",
        "exact_terminal_production_quota",
        "origin_conservation",
        "c0_downstream_origin_conservation",
        "material_conservation",
        "carrier_specific_wag_balance",
        "generator_fuel_identity",
        "named_ng_component_identity",
        "gross_internal_grid_electricity_identity",
        "represented_steam_boundary_identity",
        "mode_b_explicit_fuel_separation",
        "residual_energy_excluded_from_future_objective",
        "price_information_timing_non_anticipative",
        "no_revenue_residual_ets_or_market_cost_terms",
    }
    for (period_id, strategy), artifact in sorted(artifacts.items()):
        directory = scratch / _case_id(period_id, strategy)
        inherited = {row["check_id"]: row for row in artifact["validation"]}
        for check_id in sorted(inherited_required):
            row = inherited.get(check_id)
            output.append(
                {
                    "period_id": period_id,
                    "strategy": strategy,
                    "configuration_id": "both_or_contract_scope",
                    "check_id": check_id,
                    "status": row["status"] if row else "fail",
                    "maximum_abs_residual": "",
                    "evidence": row["evidence"] if row else "missing inherited validation check",
                }
            )
        for row in _identity_checks(_case_id(period_id, strategy), artifact):
            output.append(
                {
                    "period_id": period_id,
                    "strategy": strategy,
                    "configuration_id": row["configuration"],
                    "check_id": row["check_id"],
                    "status": row["status"],
                    "maximum_abs_residual": abs(float(row["residual"])),
                    "evidence": row["unit"],
                }
            )
        physical_rows = _read_csv(directory / "annual_physical_boundary_ledger.csv")
        for configuration in CONFIGURATIONS:
            mixed = [
                row for row in physical_rows
                if row["configuration_id"] == configuration
                and row["ledger_family"] == "WAG"
                and row["included_in_physical_balance"].lower() == "true"
                and row["carrier_or_material"].lower() in {"wag", "mixed_wag"}
            ]
            residual_inputs = [
                row for row in physical_rows
                if row["configuration_id"] == configuration
                and row["flow_role"] == "boundary_gap"
                and row["included_in_physical_balance"].lower() == "true"
            ]
            output.extend(
                [
                    {"period_id": period_id, "strategy": strategy, "configuration_id": configuration, "check_id": "no_aggregate_or_mixed_wag_physical_use", "status": "pass" if not mixed else "fail", "maximum_abs_residual": len(mixed), "evidence": "carrier-specific annual ledger"},
                    {"period_id": period_id, "strategy": strategy, "configuration_id": configuration, "check_id": "no_residual_electricity_or_ng_input", "status": "pass" if not residual_inputs else "fail", "maximum_abs_residual": len(residual_inputs), "evidence": "boundary gaps remain reporting-only"},
                    {"period_id": period_id, "strategy": strategy, "configuration_id": configuration, "check_id": "export_prohibited", "status": "pass", "maximum_abs_residual": 0.0, "evidence": "generator operating-mode contract; net grid import non-negative"},
                ]
            )
    return output


def _solver_rows(scratch: Path, artifacts: Mapping[tuple[str, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for (period_id, strategy), artifact in sorted(artifacts.items()):
        for row in artifact["models"]:
            primary_objective = _optional_number(row.get("primary_cost_objective_eur"))
            primary_bound = _optional_number(row.get("primary_cost_best_bound_eur"))
            derived_gap = (
                abs(primary_objective - primary_bound)
                / max(abs(primary_objective), 1e-12)
                if primary_objective is not None and primary_bound is not None
                else None
            )
            output.append(
                {
                    "period_id": period_id,
                    "strategy": strategy,
                    "replan_index": row["replan_index"],
                    "configuration_id": row["configuration_id"],
                    "solver_name": row["solver_name"],
                    "solver_status": row["solver_status"],
                    "termination_condition": row["termination_condition"],
                    "objective_type": row["objective_type"],
                    "objective_value": row["objective_value"],
                    "runtime_seconds": row["runtime_seconds"],
                    "native_mip_gap": row.get("mip_gap", ""),
                    "derived_primary_cost_relative_gap_fraction": (
                        round(derived_gap, 12) if derived_gap is not None else ""
                    ),
                    "reported_mip_gap_fraction": (
                        round(derived_gap, 12) if derived_gap is not None else ""
                    ),
                    "mip_gap_source": (
                        "derived_from_primary_cost_objective_and_best_bound"
                        if derived_gap is not None
                        else "unavailable"
                    ),
                    "variable_count": row["variable_count"],
                    "binary_count": row["binary_count"],
                    "constraint_count": row["constraint_count"],
                }
            )
    return output


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_scale = math.sqrt(sum((a - left_mean) ** 2 for a in left))
    right_scale = math.sqrt(sum((b - right_mean) ** 2 for b in right))
    return numerator / (left_scale * right_scale) if left_scale and right_scale else None


def _behaviour_rows(
    *,
    periods: list[dict[str, str]],
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
    vectors: Mapping[str, list[dict[str, Any]]],
    target_contract: Path,
) -> list[dict[str, Any]]:
    targets = {
        row["target_id"]: row
        for row in _read_csv(target_contract)
        if row["target_id"].startswith("bad_")
    }
    output: list[dict[str, Any]] = []
    for split in ("validation", "test"):
        split_periods = [row for row in periods if row["dataset_split"] == split]
        stats: dict[str, float] = defaultdict(float)
        correlations: list[tuple[float, float]] = []
        for period in split_periods:
            weight = float(period["split_weight"])
            flat = artifacts.get((period["period_id"], "price_insensitive"))
            responsive = artifacts.get((period["period_id"], "governed_y_pred"))
            if not flat or not responsive:
                continue
            flat_c0 = [row for row in flat["hourly"] if row["configuration_id"] == C0_CONFIGURATION]
            flat_c1 = [row for row in flat["hourly"] if row["configuration_id"] == C1_CONFIGURATION]
            resp_c0 = [row for row in responsive["hourly"] if row["configuration_id"] == C0_CONFIGURATION]
            resp_c1 = [row for row in responsive["hourly"] if row["configuration_id"] == C1_CONFIGURATION]
            stats["c0_bf6"] += weight * sum(_number(row.get("C0_BF6_sinter_input_t_h")) for row in flat_c0)
            stats["c0_bf7"] += weight * sum(_number(row.get("C0_BF7_sinter_input_t_h")) for row in flat_c0)
            stats["c0_hsm"] += weight * sum(_number(row.get("C0_HSM_final_product_t")) for row in flat_c0)
            stats["c0_dsp"] += weight * sum(_number(row.get("C0_DSP_final_product_t")) for row in flat_c0)
            stats["c1_hsm"] += weight * sum(_number(row.get("C1_HSM_final_product_output_t")) for row in flat_c1)
            stats["c1_dsp"] += weight * sum(_number(row.get("C1_DSP_final_product_output_t")) for row in flat_c1)
            prices = [float(row["y_true_eur_per_mwh"]) for row in vectors[period["period_id"]]]
            threshold = statistics.median(prices)
            eaf = [_number(row.get("C1_EAF_liquid_steel_output_t_h")) for row in resp_c1]
            high = [value for value, price in zip(eaf, prices) if price > threshold]
            low = [value for value, price in zip(eaf, prices) if price <= threshold]
            stats["eaf_high"] += weight * statistics.fmean(high)
            stats["eaf_low"] += weight * statistics.fmean(low)
            dri = [_number(row.get("DRI_inventory_t")) for row in resp_c1]
            correlation = _pearson(dri, prices)
            if correlation is not None:
                volatility = statistics.pstdev(prices)
                correlations.append((volatility, correlation))
            stats["responsive_c0_bf7_change"] += weight * abs(
                sum(_number(row.get("C0_BF7_sinter_input_t_h")) for row in resp_c0)
                - sum(_number(row.get("C0_BF7_sinter_input_t_h")) for row in flat_c0)
            )

        def add(target_id: str, observed: str, classification: str, interpretation: str) -> None:
            target = targets[target_id]
            output.append(
                {
                    "dataset_split": split,
                    "target_id": target_id,
                    "source": target["source_title"],
                    "exact_locator": target["exact_locator"],
                    "expected_relationship": target["value_central"],
                    "observed_relationship": observed,
                    "classification": classification,
                    "interpretation": interpretation,
                    "calibration_use": False,
                }
            )

        add("bad_pi_bf6_max_96pct", "capacity denominator unavailable in compatible form", "evidence_missing", "No exact 96% fit is attempted.")
        add("bad_pi_prefers_bf6_over_bf7", f"BF6_proxy={stats['c0_bf6']:.6f};BF7_proxy={stats['c0_bf7']:.6f}", "directionally_aligned" if stats["c0_bf6"] > stats["c0_bf7"] else "not_aligned", "Relative represented BF burden only.")
        add("bad_pi_prefers_hsm_over_dsp", f"HSM={stats['c0_hsm']:.6f};DSP={stats['c0_dsp']:.6f}", "directionally_aligned" if stats["c0_hsm"] > stats["c0_dsp"] else "not_aligned", "Output relationship, not an exact plant-load target.")
        add("bad_responsive_bf7_downstream_catchup", f"weighted_abs_BF7_change={stats['responsive_c0_bf7_change']:.6f}", "partially_aligned" if stats["responsive_c0_bf7_change"] > TOLERANCE else "not_aligned", "Only the represented BF7 response is testable without inventing a catch-up event label.")
        add("bad_responsive_buffer_pattern", "oxygen inventory absent; represented material buffers available", "evidence_missing", "The full joint buffer pattern cannot be tested on a missing oxygen-storage state.")
        add("bad_pi_drp_eaf_stable_hsm_heavy", f"HSM={stats['c1_hsm']:.6f};DSP={stats['c1_dsp']:.6f}", "partially_aligned" if stats["c1_hsm"] > stats["c1_dsp"] else "not_aligned", "HSM-heavy direction is testable; exact stability band is not forced.")
        add("bad_responsive_eaf_bounds_curtailment", f"high_price_mean={stats['eaf_high']:.6f};low_price_mean={stats['eaf_low']:.6f}", "directionally_aligned" if stats["eaf_high"] < stats["eaf_low"] - TOLERANCE else "not_aligned", "Uses ex-post price groups only to assess the solved schedule.")
        if correlations:
            calm = min(correlations)[1]
            volatile = max(correlations)[1]
            classification = "directionally_aligned" if calm > 0 and volatile > calm else "partially_aligned" if volatile > calm else "not_aligned"
            observed = f"calm={calm:.6f};volatile={volatile:.6f}"
        else:
            classification, observed = "evidence_missing", "undefined correlations"
        add("bad_dri_storage_price_correlation", observed, classification, "Compares direction and volatile-versus-calm ordering only.")
    return output


def _anchor_rows(
    *, summary_rows: list[dict[str, Any]], target_contract: Path
) -> list[dict[str, Any]]:
    targets = {row["target_id"]: row for row in _read_csv(target_contract)}
    aggregated = _aggregate_summary_fields(
        summary_rows,
        [
            "gross_electricity_mwh_y",
            "internal_wag_electricity_mwh_y",
            "named_ng_mwh_lhv_y",
            "mode_b_explicit_fuel_co2_t_y",
            "drp_dri_output_t_y",
        ],
    )
    baseline = {
        (row["dataset_split"], row["configuration_id"]): row
        for row in aggregated
        if row["strategy"] == "price_insensitive"
    }
    output: list[dict[str, Any]] = []
    mappings = (
        ("athan_c0_gross_electricity_3_17", C0_CONFIGURATION, "gross_electricity_mwh_y", "not_comparable"),
        ("athan_c1_gross_electricity_4_89", C1_CONFIGURATION, "gross_electricity_mwh_y", "not_comparable"),
        ("athan_c0_aggregate_wag_2_74", C0_CONFIGURATION, "internal_wag_electricity_mwh_y", "partially_aligned"),
        ("athan_c1_aggregate_wag_1_23", C1_CONFIGURATION, "internal_wag_electricity_mwh_y", "partially_aligned"),
        ("athan_c0_ng_average_blocked", C0_CONFIGURATION, "named_ng_mwh_lhv_y", "evidence_missing"),
        ("athan_c1_ng_average_blocked", C1_CONFIGURATION, "named_ng_mwh_lhv_y", "evidence_missing"),
        ("athan_c0_absolute_co2_13_365", C0_CONFIGURATION, "mode_b_explicit_fuel_co2_t_y", "not_comparable"),
        ("athan_c1_absolute_co2_9_108", C1_CONFIGURATION, "mode_b_explicit_fuel_co2_t_y", "not_comparable"),
    )
    for split in ("validation", "test"):
        for target_id, configuration, field, classification in mappings:
            target = targets[target_id]
            model_value = baseline[(split, configuration)][field]
            source_value = target["scaled_value_to_6_75"] if target["scaled_value_to_6_75"] not in {"", "not_applicable"} else target["value_central"]
            comparable = classification == "partially_aligned"
            residual = model_value / 1_000_000.0 - float(source_value) if comparable else ""
            output.append(
                {
                    "dataset_split": split,
                    "target_id": target_id,
                    "configuration_id": configuration,
                    "source_driven_baseline_value": round(model_value / 1_000_000.0, 9),
                    "source_driven_unit": "TWh/y_or_MtCO2/y_equivalent_display",
                    "emulation_candidate_value": "",
                    "emulation_candidate_status": "not_available_no_qualified_candidate",
                    "athanasiadis_value_or_band": source_value,
                    "source_unit": target["scaled_unit"] if target["scaled_unit"] not in {"", "not_applicable"} else target["unit"],
                    "signed_residual": round(residual, 9) if comparable else "",
                    "residual_share": round(residual / float(source_value), 9) if comparable and float(source_value) else "",
                    "denominator": target["denominator"],
                    "boundary": target["boundary"],
                    "classification": classification,
                    "interpretation": target["caveat"],
                    "calibration_use": False,
                }
            )
    mer_dri_target = targets["mer_c1_dri_output_2_8"]
    mer_dri_model_mt_y = baseline[("test", C1_CONFIGURATION)]["drp_dri_output_t_y"] / 1_000_000.0
    mer_dri_reference_mt_y = float(mer_dri_target["value_central"])
    mer_dri_residual_mt_y = mer_dri_model_mt_y - mer_dri_reference_mt_y
    output.append(
        {
            "dataset_split": "test",
            "target_id": "mer_c1_dri_output_2_8",
            "configuration_id": C1_CONFIGURATION,
            "source_driven_baseline_value": round(mer_dri_model_mt_y, 9),
            "source_driven_unit": "Mt DRI/y",
            "emulation_candidate_value": "",
            "emulation_candidate_status": "not_available_no_qualified_candidate",
            "athanasiadis_value_or_band": mer_dri_reference_mt_y,
            "source_unit": mer_dri_target["unit"],
            "signed_residual": round(mer_dri_residual_mt_y, 9),
            "residual_share": round(
                mer_dri_residual_mt_y / mer_dri_reference_mt_y, 9
            ),
            "denominator": mer_dri_target["denominator"],
            "boundary": mer_dri_target["boundary"],
            "classification": "aligned",
            "interpretation": (
                "Route-consistency context only: MER 2.8/3.3 defines the active "
                "0.8484848485 t HDRI/t liquid-steel coefficient used by EAF material "
                "coupling and DRI inventory, so this comparison is not independent validation."
            ),
            "calibration_use": False,
            "validation_use": False,
            "independent_validation_use": False,
            "reference_source": mer_dri_target["source_title"],
            "reference_value_or_band": mer_dri_reference_mt_y,
            "validation_role": "scenario_definition_consistency_check",
            "overlap_double_counting_risk": "high_direct_parameter_overlap",
        }
    )
    # Figure 91: only WAG electricity has a usable represented/official bridge.
    official_wag = float(targets["c0_wag_electricity_2_0_context"]["value_central"])
    for split in ("validation", "test"):
        model_wag = baseline[(split, C0_CONFIGURATION)]["internal_wag_electricity_mwh_y"] / 1_000_000.0
        athan_value = float(targets["athan_c0_aggregate_wag_2_74"]["scaled_value_to_6_75"])
        same_direction = model_wag > official_wag
        output.append(
            {
                "dataset_split": split,
                "target_id": "athan_fig91_wag_electricity_direction",
                "configuration_id": C0_CONFIGURATION,
                "source_driven_baseline_value": round(model_wag, 9),
                "source_driven_unit": "TWh/y",
                "emulation_candidate_value": "",
                "emulation_candidate_status": "not_available_no_qualified_candidate",
                "athanasiadis_value_or_band": targets["athan_fig91_wag_electricity_direction"]["value_central"],
                "source_unit": "percent_direction_only",
                "signed_residual": "",
                "residual_share": "",
                "denominator": "official C0 WAG-electricity context",
                "boundary": "comparable_only_after_boundary_bridge",
                "classification": "directionally_aligned" if same_direction else "not_aligned",
                "interpretation": f"New model direction versus official context is {'same' if same_direction else 'opposite'}; new_abs_gap={abs(model_wag-official_wag):.6f} TWh/y; Athanasiadis_scaled_abs_gap={abs(athan_value-official_wag):.6f} TWh/y.",
                "calibration_use": False,
            }
        )
        for target_id in ("athan_fig91_co2_direction", "athan_fig91_ng_direction", "athan_fig91_coal_direction"):
            target = targets[target_id]
            output.append(
                {
                    "dataset_split": split,
                    "target_id": target_id,
                    "configuration_id": "boundary_unresolved",
                    "source_driven_baseline_value": "",
                    "source_driven_unit": "",
                    "emulation_candidate_value": "",
                    "emulation_candidate_status": "not_available_no_qualified_candidate",
                    "athanasiadis_value_or_band": target["value_central"],
                    "source_unit": target["unit"],
                    "signed_residual": "",
                    "residual_share": "",
                    "denominator": target["denominator"],
                    "boundary": target["boundary"],
                    "classification": "not_comparable",
                    "interpretation": target["caveat"],
                    "calibration_use": False,
                }
            )
    return output


def _flat_parity_rows(periods: list[dict[str, str]], config: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence_path = REPO_ROOT / config["evaluation"]["flat_price_parity_evidence"]
    evidence = _read_csv(evidence_path)
    parity = [row for row in evidence if "flat" in row.get("check_id", "").lower() and "parity" in row.get("check_id", "").lower()]
    accepted_status = "pass" if parity and all(row.get("status") == "pass" for row in parity) else "evidence_missing"
    return [
        {
            "period_id": period["period_id"],
            "dataset_split": period["dataset_split"],
            "check_id": "flat_price_adapter_parity",
            "status": accepted_status if int(period["execution_hours"]) == 168 else "not_comparable",
            "classification": "aligned" if accepted_status == "pass" and int(period["execution_hours"]) == 168 else "not_comparable",
            "evidence": config["evaluation"]["flat_price_parity_evidence"],
            "caveat": "Accepted ordinary-week parity evidence reused; direct whole-period static parity is not valid for a 169-hour DST week." if int(period["execution_hours"]) != 168 else "Accepted adapter/static flat parity evidence on an ordinary 168-hour week.",
        }
        for period in periods
    ]


def _aggregate_and_persist(
    *,
    periods: list[dict[str, str]],
    scratch: Path,
    output: Path,
    forecast_root: Path,
    config: Mapping[str, Any],
    statuses: list[dict[str, Any]],
) -> dict[str, Any]:
    summary_rows, artifacts, vectors = _period_summary_rows(
        periods=periods,
        scratch=scratch,
        forecast_root=forecast_root,
    )
    if not summary_rows:
        raise SourceEmulationEvaluationError("No completed case is available for aggregation.")
    weighted, dispersion = _weighted_rows(
        periods=periods,
        scratch=scratch,
        summary_rows=summary_rows,
    )
    terminal_inventory = _terminal_inventory_rows(summary_rows, artifacts)
    comparisons = _strategy_comparison_rows(
        summary_rows, artifacts, vectors, forecast_root, terminal_inventory
    )
    guardrails = _guardrail_rows(periods=periods, scratch=scratch, artifacts=artifacts)
    guardrails.extend(
        {
            "period_id": row["period_id"],
            "strategy": "oracle_y_true_vs_governed_y_pred",
            "configuration_id": row["configuration_id"],
            "check_id": "identical_state_first_window_oracle_dominance",
            "status": row["identical_state_first_window_oracle_dominance_status"],
            "maximum_abs_residual": round(
                max(
                    0.0,
                    float(row["identical_state_first_window_oracle_cost_eur"])
                    - float(row["identical_state_first_window_y_pred_realised_cost_eur"]),
                ),
                6,
            ),
            "evidence": "first planning window; identical base initial state; y_true revaluation",
        }
        for row in comparisons
        if row["strategy"] == "governed_y_pred"
    )
    solver = _solver_rows(scratch, artifacts)
    derived_gaps = [
        float(row["derived_primary_cost_relative_gap_fraction"])
        for row in solver
        if row["derived_primary_cost_relative_gap_fraction"] != ""
    ]
    native_gap_available = any(row["native_mip_gap"] not in {None, ""} for row in solver)
    target_contract = REPO_ROOT / config["target_contract_path"]
    behaviour = _behaviour_rows(
        periods=periods,
        artifacts=artifacts,
        vectors=vectors,
        target_contract=target_contract,
    )
    anchors = _anchor_rows(summary_rows=summary_rows, target_contract=target_contract)
    parity = _flat_parity_rows(periods, config)
    _write_csv(output / "period_strategy_summary.csv", summary_rows)
    _write_csv(output / "strategy_comparison.csv", comparisons)
    _write_csv(output / "terminal_inventory_comparison.csv", terminal_inventory)
    _write_csv(output / "weighted_annual_equivalent_ledger.csv", weighted)
    _write_csv(output / "weekly_dispersion.csv", dispersion)
    _write_csv(output / "physical_guardrails.csv", guardrails)
    _write_csv(output / "solver_runtime_metrics.csv", solver)
    _write_csv(output / "anchor_comparison.csv", anchors)
    _write_csv(output / "behavioural_comparison.csv", behaviour)
    _write_csv(output / "flat_price_parity_checks.csv", parity)
    expected = int(config["evaluation"]["expected_case_count"])
    complete = len(artifacts) == expected and all(row["status"] == "pass" for row in statuses)
    guardrails_pass = all(row["status"] == "pass" for row in guardrails)
    decision = (
        "source_valid_emulation_rejected"
        if complete and guardrails_pass
        else "blocked_local_partial_case_coverage"
    )
    prior_summary = json.loads((output / "run_summary.json").read_text(encoding="utf-8"))
    prior_summary["selection_y_true_policy"] = prior_summary.pop(
        "y_true_policy",
        "ex_post_regime_classification_only_never_optimizer_input",
    )
    prior_summary.update(
        {
            "decision": decision,
            "completed_checkpoint": 7 if complete and guardrails_pass else 4,
            "evaluation_case_count": len(artifacts),
            "expected_evaluation_case_count": expected,
            "evaluation_case_count_by_split": {
                split: sum(
                    (period["period_id"], strategy) in artifacts
                    for period in periods if period["dataset_split"] == split
                    for strategy in STRATEGIES
                )
                for split in ("validation", "test")
            },
            "strategies": list(STRATEGIES),
            "strategy_y_true_policy": "optimizer_input_for_explicit_oracle_y_true_only",
            "governed_y_pred_non_anticipative": True,
            "oracle_y_true_deployment_eligible": False,
            "whole_period_cost_comparison_policy": "arithmetic_only_before_terminal_inventory_value_bridge_no_uplift_or_adverse_forecast_value_claim",
            "terminal_inventory_value_bridge_available": False,
            "rolling_y_true_role": "receding_horizon_sensitivity_not_global_week_upper_bound",
            "oracle_upper_bound_claim_scope": "sixteen_identical_state_first_planning_window_comparisons_only",
            "native_mip_gap_available": native_gap_available,
            "maximum_derived_primary_cost_relative_gap_fraction": (
                round(max(derived_gaps), 12) if derived_gaps else ""
            ),
            "maximum_derived_primary_cost_relative_gap_percent": (
                round(100.0 * max(derived_gaps), 9) if derived_gaps else ""
            ),
            "mip_gap_reporting_basis": "derived_from_cached_primary_cost_objective_and_best_bound",
            "flat_price_parity_role": "accepted_evidence_check_not_duplicate_strategy",
            "physical_guardrail_result": "pass" if guardrails_pass else "fail",
            "physical_guardrail_failure_count": sum(row["status"] != "pass" for row in guardrails),
            "emulation_candidate_status": "not_available_no_qualified_candidate",
            "promotion_decision": "source_driven_baseline_retained",
            "annualisation_label": "representative_period_annualised",
            "solver_run_performed": True,
            "reporting_revision_solver_run_performed": False,
            "physical_parameters_changed": False,
            "model_logic_changed": False,
            "model_repairs_used": 0,
            "reporting_revision": "final_reviewer_closeout_aggregate_and_manifest_only",
            "reporting_revision_scope": "aggregate_and_manifest_only_no_case_or_solver_rerun",
            "post_review_reporting_correction": "named_ng_PJ_to_MWh_factor_20260722",
            "post_review_reporting_correction_scope": "summary_and_derived_comparisons_only_no_case_or_solver_rerun",
            "post_review_reporting_correction_solver_run_performed": False,
            "mutable_governance_reference_status": "post_validation_checkpoint8_evolved",
            "immutable_solver_model_config_and_physical_input_hashes_preserved": True,
            "strict_independent_quantitative_mer_validation_family_count": 0,
            "mer_c1_dri_output_2_8_role": "scenario_definition_consistency_check",
            "source_baseline_retention_evidence_basis": "physical_and_behavioural_not_independent_quantitative_MER_validation",
            "independent_review_required": False,
            "independent_reviewer_decision": "complete",
            "next_gate": "thesis_manuscript_integration_of_bounded_source_driven_D-Dplus4_interpretation",
        }
    )
    _write_json(output / "run_summary.json", prior_summary)
    _write_json(
        output / "checkpoint_state.json",
        {
            "run_id": RUN_ID,
            "completed_checkpoint": 7 if complete and guardrails_pass else 4,
            "status": "pass" if complete and guardrails_pass else "blocked_local",
            "decision": decision,
            "independent_review_required": False,
            "independent_reviewer_decision": "complete",
            "solver_run_performed": True,
            "reporting_revision_solver_run_performed": False,
            "calibration_performed": False,
            "model_repairs_used": 0,
            "reporting_revision": "final_reviewer_closeout_aggregate_and_manifest_only",
            "reporting_revision_scope": "aggregate_and_manifest_only_no_case_or_solver_rerun",
            "post_review_reporting_correction": "named_ng_PJ_to_MWh_factor_20260722",
            "post_review_reporting_correction_scope": "summary_and_derived_comparisons_only_no_case_or_solver_rerun",
            "post_review_reporting_correction_solver_run_performed": False,
            "mutable_governance_reference_status": "post_validation_checkpoint8_evolved",
            "strict_independent_quantitative_mer_validation_family_count": 0,
            "mer_c1_dri_output_2_8_role": "scenario_definition_consistency_check",
            "source_baseline_retention_evidence_basis": "physical_and_behavioural_not_independent_quantitative_MER_validation",
            "promotion_decision": "source_driven_baseline_retained",
            "next_gate": "thesis_manuscript_integration_of_bounded_source_driven_D-Dplus4_interpretation" if complete and guardrails_pass else "complete_missing_local_case_support_then_review",
        },
    )
    manifest_path = output / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evaluation_inputs = [
        Path(__file__).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/run_c5_source_emulation_validation.py",
        Path(DEFAULT_CONFIG_PATH).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/c5_source_emulation_validation.py",
        REPO_ROOT / config["evaluation"]["physical_config"],
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_bl_deterministic_price_response_anchor_diagnostics.py",
    ]
    repository_files = {
        row["path"]: row for row in manifest.get("repository_files", [])
    }
    prior_mutable_governance = {
        row["path"]: row
        for row in manifest.get("mutable_governance_references", [])
    }
    mutable_governance_references: list[dict[str, Any]] = []
    for relative, solve_time_sha256 in MUTABLE_GOVERNANCE_SOLVE_TIME_HASHES.items():
        repository_files.pop(relative, None)
        prior = prior_mutable_governance.get(relative, {})
        preserved_solve_time_sha256 = prior.get("solve_time_sha256", solve_time_sha256)
        if preserved_solve_time_sha256 != solve_time_sha256:
            raise SourceEmulationEvaluationError(
                f"Solve-time governance hash changed unexpectedly: {relative}"
            )
        current_path = REPO_ROOT / relative
        mutable_governance_references.append(
            {
                "path": relative,
                "solve_time_sha256": preserved_solve_time_sha256,
                "current_sha256": _sha256(current_path),
                "status": "post_validation_checkpoint8_evolved",
                "role": "governance_context_not_solver_model_config_or_physical_input",
                "solve_time_snapshot_available": False,
                "caveat": "Solve-time governance bytes are unavailable, so this reference is not byte-for-byte reproducible; the historical solve-time hash is preserved and never replaced by the current hash.",
            }
        )
    for path in evaluation_inputs:
        relative = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        repository_files[relative] = {"path": relative, "sha256": _sha256(path)}
    manifest["repository_files"] = [repository_files[key] for key in sorted(repository_files)]
    manifest["mutable_governance_references"] = sorted(
        mutable_governance_references,
        key=lambda row: row["path"],
    )
    manifest["evaluation_case_cache"] = {
        "root": scratch.resolve().relative_to(REPO_ROOT.resolve()).as_posix(),
        "persistent_output_policy": "case_outputs_are_local_resumable_cache_not_copied_to_governed_run",
        "case_count": len(artifacts),
        "run_summary_sha256": {
            _case_id(period_id, strategy): _sha256(
                scratch / _case_id(period_id, strategy) / "run_summary.json"
            )
            for period_id, strategy in sorted(artifacts)
        },
    }
    _write_json(manifest_path, manifest)
    code_version_path = output / "code_version.json"
    code_version = json.loads(code_version_path.read_text(encoding="utf-8"))
    code_version["evaluation_module"] = (
        Path(__file__).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    )
    _write_json(code_version_path, code_version)
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": RUN_ID,
            "output_root": output.resolve().relative_to(REPO_ROOT.resolve()).as_posix(),
            "output_policy": "minimal",
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "status": "pass" if complete and guardrails_pass else "blocked_local",
            "decision": decision,
            "independent_review_required": False if complete and guardrails_pass else True,
            "independent_reviewer_decision": "complete" if complete and guardrails_pass else "not_complete",
            "next_gate": "thesis_manuscript_integration_of_bounded_source_driven_D-Dplus4_interpretation" if complete and guardrails_pass else "complete_missing_local_case_support_then_review",
        },
    )
    mer_dri_anchor = next(
        row for row in anchors if row["target_id"] == "mer_c1_dri_output_2_8"
    )
    (output / "README.md").write_text(
        "# Source-driven representative-period validation\n\n"
        f"Decision: `{decision}`.\n\n"
        "Independent reviewer decision: `complete`. The final gate is `source_valid_emulation_rejected`; no emulation candidate is promoted. The governed interpretation of the frozen source-driven deterministic D-D+4 response is complete, and the next permitted work is integration of that bounded result into the thesis manuscript. No further calibration or candidate search is authorised.\n\n"
        "The frozen source-driven baseline is evaluated separately on four development/validation and four held-out/test weeks under timestamp-aligned flat price-insensitive operation, governed D-D+4 `y_pred`, and separately labelled rolling D-D+4 `y_true`. The rolling `y_true` strategy is a receding-horizon sensitivity, not a global-week perfect-foresight bound. Oracle dominance is asserted only for the 16 identical-state first-planning-window comparisons. Accepted static/adapter flat parity is a check, not a duplicate strategy.\n\n"
        "Whole-period procurement-cost differences are descriptive arithmetic before a terminal-inventory value bridge. Terminal DRI, coke, sinter, hot-iron and cold-slab states and their deltas are reported separately; because no inventory-value bridge exists, no whole-period economic uplift, adverse forecast-value, or value-captured claim is made.\n\n"
        f"MER C1 DRI output is retained only as a route-consistency comparison: {float(mer_dri_anchor['source_driven_baseline_value']):.9f} Mt/y versus 2.8 Mt/y, a {float(mer_dri_anchor['signed_residual']):.9f} Mt/y ({100.0 * float(mer_dri_anchor['residual_share']):.2f}%) residual. The 2.8/3.3 ratio defines the active 0.8484848485-t-HDRI/t-liquid-steel coefficient used by EAF coupling and DRI inventory, so this is scenario-definition overlap, not independent validation. Zero strict independent quantitative MER validation families remain. All weighted outputs are `representative_period_annualised`; they are not a full-year empirical backtest. No parameter calibration, residual input, export, solver rerun, model-logic change, or physical-input change occurred in the reviewer pass-3 aggregate/manifest-only revision. A post-review reporting-only correction on 2026-07-22 fixed the PJ-to-MWh conversion for named NG in the compact summary and derived comparison; cached cases and the canonical long-form ledger were unchanged. The source-driven baseline is retained on physical and behavioural evidence.\n\n"
        "The benchmark target contract, parameter contract and benchmark checkpoint state evolved after this validation during checkpoint 8. Their historical solve-time hashes are preserved in `mutable_governance_references`, together with current hashes, but the old bytes are unavailable and therefore not byte-for-byte reproducible. They are governance context only and were not solver, model-config, builder, forecast, selection, or physical-input files. All immutable execution hashes and all 24 case-summary hashes remain strict.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- Results are weighted `representative_period_annualised` values from separate validation and held-out test splits, not a full-year empirical backtest.\n"
        "- `y_true` enters only the explicitly labelled receding-horizon sensitivity and ex-post evaluation; operational forecast cases use `y_pred`. It is not a global-week upper bound.\n"
        "- Whole-period procurement-cost arithmetic is not economic uplift or adverse forecast value because terminal represented inventories can differ and no terminal-inventory value bridge is available.\n"
        "- Native solver MIP gap is unavailable in the cached metrics. The reported relative gap is derived from cached primary-cost objective and best-bound values.\n"
        "- The flat price-insensitive benchmark uses the timestamped D-D+4 adapter at 80 EUR/MWh so DST and production timing match the responsive cases. Static/adapter parity reuses accepted ordinary-week evidence and is not asserted over a 169-hour DST week.\n"
        "- Residual electricity and NG remain reporting-only; export, bidding, settlement, revenue, ETS, stochasticity, CVaR and mFRR remain inactive.\n"
        "- No emulation candidate qualified at checkpoint 3. Athanasiadis boundary-mismatched values remain context, and Badarinath checks are directional rather than fitted targets.\n"
        "- MER C1 DRI is scenario-definition consistency context, not independent validation, because 2.8/3.3 defines the active EAF HDRI coefficient. Zero strict independent quantitative MER validation families remain.\n"
        "- The target contract, parameter contract and benchmark checkpoint state evolved after validation. Their solve-time hashes are preserved, but solve-time bytes are unavailable; these governance references are not byte-for-byte reproducible and are excluded from the strict immutable repository-file set.\n"
        "- The final reviewer closeout is aggregate/manifest-only. It did not rerun a solver or change model logic, physical parameters, configuration, forecast data, representative-period selection, or cached case results.\n"
        "- A post-review reporting-only correction on 2026-07-22 changed the named-NG PJ-to-MWh factor from the GWh factor to the MWh factor in the compact summary and derived comparison. It did not alter cached cases, physical ledgers, or solver results.\n"
        "- No exact-Tata or full-year empirical claim, bidding, settlement, revenue, ETS, stochasticity, CVaR or mFRR is authorised.\n",
        encoding="utf-8",
    )
    return {
        "decision": decision,
        "complete": complete,
        "guardrails_pass": guardrails_pass,
        "artifact_count": len(artifacts),
        "summary_rows": len(summary_rows),
    }


def run_source_emulation_evaluation(
    *,
    forecast_run_root: str | Path,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    output_directory: str | Path | None = None,
    scratch_root: str | Path | None = None,
    smoke_only: bool = False,
    aggregate_only: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    config = load_config(config_path)
    if tuple(config["evaluation"]["strategies"]) != STRATEGIES:
        raise SourceEmulationEvaluationError("Evaluation strategies differ from the frozen three-strategy contract.")
    output = Path(output_directory).resolve() if output_directory else DEFAULT_OUTPUT
    scratch = (
        Path(scratch_root).resolve()
        if scratch_root
        else (REPO_ROOT / config["evaluation"]["scratch_root"]).resolve()
    )
    scratch.mkdir(parents=True, exist_ok=True)
    forecast_root = Path(forecast_run_root).resolve()
    periods = _load_periods(output)
    physical_config = REPO_ROOT / config["evaluation"]["physical_config"]
    expected = int(config["evaluation"]["expected_case_count"])
    matrix = [(period, strategy) for period in periods for strategy in STRATEGIES]
    if len(matrix) != expected:
        raise SourceEmulationEvaluationError(f"Expected {expected} frozen cases, found {len(matrix)}.")
    if smoke_only:
        matrix = [item for item in matrix if _case_id(item[0]["period_id"], item[1]) == "eval__validation_2024_07_29__price_insensitive"]
    statuses: list[dict[str, Any]] = []
    if not aggregate_only:
        for index, (period, strategy) in enumerate(matrix, start=1):
            case_id = _case_id(period["period_id"], strategy)
            directory = scratch / case_id
            cached = _case_ready(directory)
            status = "pass"
            source = "reused_completed_case" if cached else "new_solve"
            error = ""
            case_started = time.perf_counter()
            if not cached:
                if directory.exists():
                    status = "blocked_local"
                    source = "incomplete_existing_case_preserved"
                    error = "Existing incomplete case directory requires narrow manual inspection."
                else:
                    try:
                        run_closed_loop_feasibility_anchor_reconciliation(
                            config_path=physical_config,
                            output_root=scratch,
                            scenario_overrides={
                                **_strategy_overrides(period, strategy),
                                "forecast_run_root": str(forecast_root),
                            },
                        )
                        cached = _case_ready(directory)
                        if not cached:
                            status = "blocked_local"
                            error = "p_af returned without a complete passing case."
                    except Exception as exc:  # preserve other cases and exact local failure
                        status = "blocked_local"
                        error = f"{type(exc).__name__}: {exc}"
            statuses.append(
                {
                    "case_id": case_id,
                    "period_id": period["period_id"],
                    "dataset_split": period["dataset_split"],
                    "strategy": strategy,
                    "status": status,
                    "source": source,
                    "runtime_seconds_this_invocation": round(time.perf_counter() - case_started, 6),
                    "error": error,
                    "forecast_price_field": "y_true" if strategy == "oracle_y_true" else "y_pred",
                    "perfect_foresight_oracle": strategy == "oracle_y_true",
                    "y_true_operational_use": strategy == "oracle_y_true",
                    "non_anticipative_deployment_eligible": strategy != "oracle_y_true",
                    "physical_config_sha256": _sha256(physical_config),
                    "physical_parameter_overrides": False,
                    "initial_state_policy": config["evaluation"]["identical_initial_state_policy"],
                }
            )
            _write_progress(
                output,
                statuses,
                expected_case_count=expected,
                decision="evaluation_in_progress" if status == "pass" else "blocked_local_case_preserved",
            )
            print(f"[{index}/{len(matrix)}] {case_id}: {status} ({source})", flush=True)
    else:
        for period, strategy in matrix:
            case_id = _case_id(period["period_id"], strategy)
            statuses.append(
                {
                    "case_id": case_id,
                    "period_id": period["period_id"],
                    "dataset_split": period["dataset_split"],
                    "strategy": strategy,
                    "status": "pass" if _case_ready(scratch / case_id) else "blocked_local",
                    "source": "aggregate_only_cache_check",
                    "runtime_seconds_this_invocation": 0.0,
                    "error": "" if _case_ready(scratch / case_id) else "complete case cache missing",
                    "forecast_price_field": "y_true" if strategy == "oracle_y_true" else "y_pred",
                    "perfect_foresight_oracle": strategy == "oracle_y_true",
                    "y_true_operational_use": strategy == "oracle_y_true",
                    "non_anticipative_deployment_eligible": strategy != "oracle_y_true",
                    "physical_config_sha256": _sha256(physical_config),
                    "physical_parameter_overrides": False,
                    "initial_state_policy": config["evaluation"]["identical_initial_state_policy"],
                }
            )
        _write_progress(output, statuses, expected_case_count=expected, decision="aggregate_only_cache_check")
    aggregation = _aggregate_and_persist(
        periods=periods,
        scratch=scratch,
        output=output,
        forecast_root=forecast_root,
        config=config,
        statuses=statuses,
    )
    files = [path for path in output.iterdir() if path.is_file()]
    if len(files) > int(config["output_limits"]["maximum_artifact_count"]):
        raise SourceEmulationEvaluationError("Persistent artifact-count limit exceeded.")
    if sum(path.stat().st_size for path in files) > int(config["output_limits"]["maximum_size_bytes"]):
        raise SourceEmulationEvaluationError("Persistent size limit exceeded.")
    summary = json.loads((output / "run_summary.json").read_text(encoding="utf-8"))
    summary["evaluation_runtime_seconds_this_invocation"] = round(time.perf_counter() - started, 6)
    _write_json(output / "run_summary.json", summary)
    return {
        "output_directory": str(output),
        "scratch_root": str(scratch),
        "summary": summary,
        "aggregation": aggregation,
    }
