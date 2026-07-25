"""Frozen Checkpoint-4 development-week evaluation for five emulation cases.

Every optimisation delegates to the accepted p_af rolling runner.  This module
only freezes the candidate/scenario matrix and emits compact comparison tables.
"""

from __future__ import annotations

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
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_bl_deterministic_price_response_anchor_diagnostics import (
    _artifact,
    _identity_checks,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


EXPECTED_CANDIDATES = (
    "source_driven_baseline",
    "bg15_central_no_movement",
    "bg25_central_no_movement",
    "bg25_single_process_electricity_high",
    "bg25_cog_yield_high",
)
EXPECTED_SCENARIOS = (
    "calm_price_insensitive",
    "calm_flat_low",
    "calm_flat_high",
    "calm_governed_y_pred",
    "volatile_negative_governed_y_pred",
    "volatile_negative_oracle_y_true",
)
TOLERANCE = 1e-4


class Checkpoint4Error(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialised = list(rows)
    if not materialised:
        raise Checkpoint4Error(f"Refusing to write empty output: {path.name}")
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


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _case_id(candidate_id: str, scenario_id: str) -> str:
    return f"cp4__{candidate_id}__{scenario_id}".replace("-", "_")


def _case_ready(directory: Path) -> bool:
    required = {
        "run_summary.json",
        "executed_hourly.csv",
        "annual_physical_boundary_ledger.csv",
        "first_order_full_site_co2_ledger.csv",
        "rolling_model_metrics.csv",
        "validation_checks.csv",
    }
    if not directory.is_dir() or not all((directory / name).is_file() for name in required):
        return False
    return json.loads((directory / "run_summary.json").read_text(encoding="utf-8")).get("status") == "pass"


def _validate_config(config: Mapping[str, Any]) -> None:
    if config.get("mode") != "user_authorized_full_site_emulation_checkpoint4":
        raise Checkpoint4Error("Checkpoint 4 requires its frozen execution mode.")
    if config.get("output_policy") != "minimal":
        raise Checkpoint4Error("Checkpoint 4 requires output_policy=minimal.")
    candidate_ids = tuple(row["candidate_id"] for row in config["checkpoint_4"]["candidates"])
    scenario_ids = tuple(row["scenario_id"] for row in config["checkpoint_4"]["scenarios"])
    if candidate_ids != EXPECTED_CANDIDATES:
        raise Checkpoint4Error(f"Frozen candidate order differs: {candidate_ids}.")
    if scenario_ids != EXPECTED_SCENARIOS:
        raise Checkpoint4Error(f"Frozen scenario order differs: {scenario_ids}.")
    periods = config["checkpoint_4"]["development_periods"]
    if len(periods) != 2 or {row["dataset_split"] for row in periods} != {"validation"}:
        raise Checkpoint4Error("Exactly two validation/development periods must be frozen.")
    if any(row.get("period_role") != "development" for row in periods):
        raise Checkpoint4Error("Held-out periods are prohibited at Checkpoint 4.")
    if int(config["checkpoint_4"]["expected_rolling_case_count"]) != 30:
        raise Checkpoint4Error("Checkpoint 4 must freeze exactly 30 rolling cases.")
    if int(config["checkpoint_4"]["expected_model_count"]) != 420:
        raise Checkpoint4Error("Checkpoint 4 must freeze exactly 420 C0/C1 models.")


def _candidate_overrides(candidate: Mapping[str, Any]) -> dict[str, Any]:
    share = float(candidate["background_share"])
    five_percent = {
        C0_CONFIGURATION: 18.0936073059,
        C1_CONFIGURATION: 27.9109589041,
    }
    overrides: dict[str, Any] = {
        "site_background_electricity_mwh_h_by_configuration": {
            configuration: value * share / 0.05
            for configuration, value in five_percent.items()
        },
        "wag_generation_yield_overrides_by_configuration": {},
        "named_process_electricity_intensity_scales_by_configuration": {},
        "first_order_co2_constant_mt_y_by_configuration": {
            C0_CONFIGURATION: 0.0,
            C1_CONFIGURATION: 0.0,
        },
        "user_authorized_parameter_candidates": [],
    }
    if share:
        overrides["user_authorized_parameter_candidates"].append(
            {
                "parameter_id": "uae_background_electricity_share",
                "configuration": "both",
                "candidate_value": share,
            }
        )
    cog_yield = candidate.get("cog_yield_m3_per_t_dry_coal")
    if cog_yield not in {None, ""}:
        overrides["wag_generation_yield_overrides_by_configuration"] = {
            C0_CONFIGURATION: {"COG": float(cog_yield)},
            C1_CONFIGURATION: {"COG": float(cog_yield)},
        }
        overrides["user_authorized_parameter_candidates"].append(
            {
                "parameter_id": "uae_cog_generation_yield",
                "configuration": "both",
                "candidate_value": float(cog_yield),
            }
        )
    electricity_scale = candidate.get("named_process_electricity_scale")
    if electricity_scale not in {None, ""}:
        overrides["named_process_electricity_intensity_scales_by_configuration"] = {
            C0_CONFIGURATION: {"BF": float(electricity_scale)},
            C1_CONFIGURATION: {"EAF_arc": float(electricity_scale)},
        }
        for configuration, process in (
            (C0_CONFIGURATION, "BF"),
            (C1_CONFIGURATION, "EAF_arc"),
        ):
            overrides["user_authorized_parameter_candidates"].append(
                {
                    "parameter_id": "uae_named_process_electricity_intensity_scaling",
                    "configuration": configuration,
                    "candidate_value": float(electricity_scale),
                    "selected_process": process,
                }
            )
    return overrides


def _scenario_overrides(
    scenario: Mapping[str, Any], periods: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    period = periods[str(scenario["period_id"])]
    price_field = str(scenario["price_field"])
    oracle = bool(scenario["perfect_foresight_oracle"])
    if (price_field == "y_true") != oracle:
        raise Checkpoint4Error("Only the explicitly labelled oracle may use y_true.")
    return {
        "replan_count": 7,
        "price_series_id": "hourly_da_dplus4_point_forecast",
        "generator_operating_mode": "development_price_responsive",
        "forecast_dataset_split": period["dataset_split"],
        "forecast_start_origin_utc": period["frozen_forecast_start_origin_utc"],
        "timestamped_dplus4_rolling_enabled": True,
        "forecast_price_override_eur_per_mwh": scenario.get("flat_price_eur_per_mwh"),
        "forecast_price_field": price_field,
        "perfect_foresight_oracle": oracle,
    }


def _expectation_rows(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "expectation_id": row["expectation_id"],
            "scope": row["scope"],
            "expected_direction_before_solving": row["expected_direction"],
            "assessment_rule": row["assessment_rule"],
            "frozen_before_solver_execution": "true",
        }
        for row in config["checkpoint_4"]["expected_directions"]
    ]


def _annual_component(rows: list[dict[str, str]], configuration: str, component: str) -> float:
    matches = [
        row for row in rows
        if row["configuration_id"] == configuration and row["component"] == component
    ]
    return _number(matches[0]["annual_value"]) if matches else 0.0


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    lm, rm = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((a - lm) * (b - rm) for a, b in zip(left, right))
    scale = math.sqrt(sum((a - lm) ** 2 for a in left) * sum((b - rm) ** 2 for b in right))
    return numerator / scale if scale else None


def _summary_rows(
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for (candidate_id, scenario_id), artifact in sorted(artifacts.items()):
        physical = artifact["physical"]
        co2 = _read_csv(Path(artifact["directory"]) / "first_order_full_site_co2_ledger.csv")
        price_by_key = {
            (int(row["replan_index"]), int(row["hour_index"])): _number(row["price_eur_per_mwh_e"])
            for row in artifact["prices"]
        }
        for configuration in CONFIGURATIONS:
            hourly = [row for row in artifact["hourly"] if row["configuration_id"] == configuration]
            prices = [price_by_key[(int(row["replan_index"]), int(row["hour_index"]))] for row in hourly]
            median_price = statistics.median(prices)
            eaf = [_number(row.get("C1_EAF_liquid_steel_output_t_h")) for row in hourly]
            high = [value for value, price in zip(eaf, prices) if price > median_price]
            low = [value for value, price in zip(eaf, prices) if price <= median_price]
            dri = [_number(row.get("DRI_inventory_t")) for row in hourly]
            annual_factor = 8760.0 / len(hourly)
            gross = _annual_component(physical, configuration, "gross_total_electricity")
            if not gross:
                gross = _annual_component(physical, configuration, "represented_gross_electricity")
            first_order_total = next(
                (
                    _number(row.get("annual_co2_t_y"))
                    for row in co2
                    if row["configuration_id"] == configuration
                    and row["component"] == "first_order_full_site_CO2_total"
                ),
                0.0,
            )
            coking_field = (
                "C0_coking_input_t_h"
                if configuration == C0_CONFIGURATION
                else "C1_retained_coking_input_t_h"
            )
            output.append(
                {
                    "candidate_id": candidate_id,
                    "scenario_id": scenario_id,
                    "configuration_id": configuration,
                    "executed_hours": len(hourly),
                    "mean_price_eur_per_mwh": round(statistics.fmean(prices), 6),
                    "price_volatility_eur_per_mwh": round(statistics.pstdev(prices), 6),
                    "negative_price_share": round(sum(value < 0 for value in prices) / len(prices), 9),
                    "final_product_t_y": _annual_component(physical, configuration, "site_final_product"),
                    "gross_site_electricity_mwh_y": gross,
                    "wag_generator_electricity_mwh_y": _annual_component(physical, configuration, "WAG_generator_electricity"),
                    "ng_generator_electricity_mwh_y": _annual_component(physical, configuration, "NG_generator_electricity"),
                    "gross_grid_import_mwh_y": _annual_component(physical, configuration, "gross_grid_import"),
                    "gross_grid_export_mwh_y": _annual_component(physical, configuration, "gross_grid_export"),
                    "named_ng_mwh_lhv_y": _annual_component(physical, configuration, "represented_named_NG"),
                    "first_order_full_site_co2_t_y": first_order_total,
                    "coking_input_t_y": round(sum(_number(row.get(coking_field)) for row in hourly) * annual_factor, 6),
                    "bf6_activity_t": round(sum(_number(row.get("C0_BF6_sinter_input_t_h")) for row in hourly), 6),
                    "bf7_activity_t": round(sum(_number(row.get("C0_BF7_sinter_input_t_h")) for row in hourly), 6),
                    "hsm_output_t": round(sum(_number(row.get("C0_HSM_final_product_t" if configuration == C0_CONFIGURATION else "C1_HSM_final_product_output_t")) for row in hourly), 6),
                    "dsp_output_t": round(sum(_number(row.get("C0_DSP_final_product_t" if configuration == C0_CONFIGURATION else "C1_DSP_final_product_output_t")) for row in hourly), 6),
                    "drp_dri_output_t": round(sum(_number(row.get("C1_DRP_DRI_output_t_h")) for row in hourly), 6),
                    "eaf_liquid_steel_output_t": round(sum(eaf), 6),
                    "eaf_high_price_mean_t_h": round(statistics.fmean(high), 6) if high else "",
                    "eaf_low_price_mean_t_h": round(statistics.fmean(low), 6) if low else "",
                    "dri_inventory_price_correlation": round(_pearson(dri, prices), 9) if _pearson(dri, prices) is not None else "",
                    "dri_inventory_min_t": round(min(dri), 6),
                    "dri_inventory_max_t": round(max(dri), 6),
                    "sinter_inventory_range_t": round(max(_number(row.get("sinter_inventory_t")) for row in hourly) - min(_number(row.get("sinter_inventory_t")) for row in hourly), 6),
                }
            )
    return output


def _anchor_rows(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    targets = {
        C0_CONFIGURATION: {
            "gross_site_electricity_mwh_y": 3.17e6,
            "wag_generator_electricity_mwh_y": 2.74e6,
            "named_ng_average_m3_h": 33243.63,
            "first_order_full_site_co2_t_y": 13.24e6,
            "coking_input_t_y": 3.66e6,
        },
        C1_CONFIGURATION: {
            "gross_site_electricity_mwh_y": 4.89e6,
            "wag_generator_electricity_mwh_y": 1.23e6,
            "named_ng_average_m3_h": 151673.52,
            "first_order_full_site_co2_t_y": 9.107793e6,
        },
    }
    output: list[dict[str, Any]] = []
    for row in summary_rows:
        configuration = row["configuration_id"]
        for metric, target in targets[configuration].items():
            value = (
                float(row["named_ng_mwh_lhv_y"]) * 3600.0 / 35.8 / 8760.0
                if metric == "named_ng_average_m3_h"
                else float(row[metric])
            )
            output.append(
                {
                    "candidate_id": row["candidate_id"],
                    "scenario_id": row["scenario_id"],
                    "configuration_id": configuration,
                    "anchor_family": metric,
                    "model_value": round(value, 6),
                    "target_value": target,
                    "absolute_relative_error": round(abs(value - target) / target, 9),
                    "comparison_basis": "representative_development_week_annualised",
                }
            )
    baseline = {
        (row["scenario_id"], row["configuration_id"], row["anchor_family"]): row
        for row in output
        if row["candidate_id"] == "source_driven_baseline"
    }
    for row in output:
        base = baseline[(row["scenario_id"], row["configuration_id"], row["anchor_family"])]
        row["error_movement_vs_source_baseline"] = round(
            float(row["absolute_relative_error"]) - float(base["absolute_relative_error"]), 9
        )
    return output


def _behaviour_rows(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {
        (row["candidate_id"], row["scenario_id"], row["configuration_id"]): row
        for row in summary_rows
    }
    output: list[dict[str, Any]] = []

    def add(candidate: str, check: str, observed: str, status: str, caveat: str) -> None:
        output.append(
            {
                "candidate_id": candidate,
                "check_id": check,
                "observed": observed,
                "status": status,
                "caveat": caveat,
            }
        )

    for candidate in EXPECTED_CANDIDATES:
        pi0 = by_key[(candidate, "calm_price_insensitive", C0_CONFIGURATION)]
        pi1 = by_key[(candidate, "calm_price_insensitive", C1_CONFIGURATION)]
        low1 = by_key[(candidate, "calm_flat_low", C1_CONFIGURATION)]
        high1 = by_key[(candidate, "calm_flat_high", C1_CONFIGURATION)]
        calm1 = by_key[(candidate, "calm_governed_y_pred", C1_CONFIGURATION)]
        volatile0 = by_key[(candidate, "volatile_negative_governed_y_pred", C0_CONFIGURATION)]
        volatile1 = by_key[(candidate, "volatile_negative_governed_y_pred", C1_CONFIGURATION)]
        add(candidate, "bf_exact_96pct_utilisation", "capacity-compatible denominator unavailable", "structurally_unobservable", "No BF6/BF7 nameplate detail is invented.")
        add(candidate, "c0_bf6_over_bf7_ordering", f"BF6={pi0['bf6_activity_t']};BF7={pi0['bf7_activity_t']}", "pass" if float(pi0["bf6_activity_t"]) > float(pi0["bf7_activity_t"]) else "fail", "Observable represented C0 burden only.")
        add(candidate, "c0_hsm_over_dsp", f"HSM={pi0['hsm_output_t']};DSP={pi0['dsp_output_t']}", "pass" if float(pi0["hsm_output_t"]) > float(pi0["dsp_output_t"]) else "fail", "Directional, not fitted.")
        add(candidate, "c1_hsm_over_dsp", f"HSM={pi1['hsm_output_t']};DSP={pi1['dsp_output_t']}", "pass" if float(pi1["hsm_output_t"]) > float(pi1["dsp_output_t"]) else "fail", "Directional, not fitted.")
        flat_difference = abs(float(low1["eaf_liquid_steel_output_t"]) - float(high1["eaf_liquid_steel_output_t"]))
        add(candidate, "drp_eaf_flat_level_stability", f"EAF_low_minus_high={flat_difference:.6f} t", "pass" if flat_difference <= TOLERANCE else "fail", "Flat-low/high share the same temporal shape.")
        eaf_high = float(volatile1["eaf_high_price_mean_t_h"])
        eaf_low = float(volatile1["eaf_low_price_mean_t_h"])
        add(candidate, "eaf_reduces_in_expensive_hours", f"high={eaf_high:.6f};low={eaf_low:.6f}", "pass" if eaf_high < eaf_low - TOLERANCE else "fail", "Price groups use the optimiser-visible scenario series.")
        add(candidate, "eaf_and_dri_bounds", f"EAF_total={volatile1['eaf_liquid_steel_output_t']};DRI_min={volatile1['dri_inventory_min_t']};DRI_max={volatile1['dri_inventory_max_t']}", "pass" if float(volatile1["eaf_liquid_steel_output_t"]) >= 0 and float(volatile1["dri_inventory_min_t"]) >= -TOLERANCE else "fail", "Existing model bounds only.")
        calm_corr = calm1["dri_inventory_price_correlation"]
        volatile_corr = volatile1["dri_inventory_price_correlation"]
        corr_pass = calm_corr != "" and volatile_corr != "" and float(volatile_corr) > float(calm_corr)
        add(candidate, "dri_storage_volatile_vs_calm", f"calm={calm_corr};volatile={volatile_corr}", "pass" if corr_pass else "fail", "Direction only; exact Badarinath correlations are not fitted.")
        bf7_change = abs(float(volatile0["bf7_activity_t"]) - float(pi0["bf7_activity_t"]))
        add(candidate, "c0_catchup_and_buffer_pattern", f"BF7_abs_change={bf7_change:.6f};sinter_range={volatile0['sinter_inventory_range_t']}", "partial" if bf7_change > TOLERANCE else "not_observed", "Sinter buffer is observable; oxygen storage is structurally absent.")
    return output


def _guardrail_rows(
    artifacts: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for (candidate, scenario), artifact in sorted(artifacts.items()):
        for row in artifact["validation"]:
            output.append(
                {
                    "candidate_id": candidate,
                    "scenario_id": scenario,
                    "configuration_id": "contract_scope",
                    "check_id": row["check_id"],
                    "status": row["status"],
                    "maximum_abs_residual": "",
                    "evidence": row.get("evidence", ""),
                }
            )
        for row in _identity_checks(_case_id(candidate, scenario), artifact):
            output.append(
                {
                    "candidate_id": candidate,
                    "scenario_id": scenario,
                    "configuration_id": row["configuration"],
                    "check_id": row["check_id"],
                    "status": row["status"],
                    "maximum_abs_residual": abs(float(row["residual"])),
                    "evidence": row["unit"],
                }
            )
        for configuration in CONFIGURATIONS:
            physical = [row for row in artifact["physical"] if row["configuration_id"] == configuration]
            residuals = [
                abs(_number(row["annual_value"]))
                for row in physical
                if row["flow_role"] == "accounting_residual"
            ]
            exports = [
                abs(_number(row["annual_value"]))
                for row in physical
                if row["component"] == "gross_grid_export"
            ]
            mixed = [
                row for row in physical
                if row["ledger_family"] == "WAG" and row["carrier_or_material"] not in {"BFG", "COG", "BOFG"}
            ]
            output.extend(
                [
                    {"candidate_id": candidate, "scenario_id": scenario, "configuration_id": configuration, "check_id": "checkpoint2_accounting_identities", "status": "pass" if max(residuals or [0.0]) <= 0.01 else "fail", "maximum_abs_residual": max(residuals or [0.0]), "evidence": "annual carrier/material/electricity residual rows"},
                    {"candidate_id": candidate, "scenario_id": scenario, "configuration_id": configuration, "check_id": "gross_export_zero", "status": "pass" if max(exports or [0.0]) <= 0.01 else "fail", "maximum_abs_residual": max(exports or [0.0]), "evidence": "explicit gross-grid-export row"},
                    {"candidate_id": candidate, "scenario_id": scenario, "configuration_id": configuration, "check_id": "carrier_specific_wag_only", "status": "pass" if not mixed else "fail", "maximum_abs_residual": len(mixed), "evidence": "BFG/COG/BOFG remain separate"},
                ]
            )
    return output


def _solver_rows(artifacts: Mapping[tuple[str, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for (candidate, scenario), artifact in sorted(artifacts.items()):
        for row in artifact["models"]:
            output.append({"candidate_id": candidate, "scenario_id": scenario, **row})
    return output


def _selection_rows(
    anchor_rows: list[dict[str, Any]],
    behaviour_rows: list[dict[str, Any]],
    guardrail_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    operational = set(EXPECTED_SCENARIOS).difference({"volatile_negative_oracle_y_true"})
    output: list[dict[str, Any]] = []
    baseline_errors: dict[str, float] = {}
    for candidate in EXPECTED_CANDIDATES:
        rows = [row for row in anchor_rows if row["candidate_id"] == candidate and row["scenario_id"] in operational]
        family_errors: dict[str, list[float]] = {}
        for row in rows:
            family_errors.setdefault(row["anchor_family"], []).append(float(row["absolute_relative_error"]))
        family_means = {family: statistics.fmean(values) for family, values in family_errors.items()}
        if candidate == "source_driven_baseline":
            baseline_errors = family_means
        improved = sum(
            family_means[family] < baseline_errors.get(family, math.inf) - 1e-9
            for family in family_means
        ) if baseline_errors else 0
        behaviour = [row for row in behaviour_rows if row["candidate_id"] == candidate]
        guardrails_pass = all(row["status"] == "pass" for row in guardrail_rows if row["candidate_id"] == candidate)
        output.append(
            {
                "candidate_id": candidate,
                "mean_anchor_relative_error": round(statistics.fmean(family_means.values()), 9),
                "anchor_families_improved_vs_source": improved,
                "behaviour_pass_count": sum(row["status"] == "pass" for row in behaviour),
                "behaviour_fail_count": sum(row["status"] == "fail" for row in behaviour),
                "physical_guardrails_pass": str(guardrails_pass).lower(),
                "selection_eligible": str(candidate != "source_driven_baseline" and improved >= 2 and guardrails_pass).lower(),
                "selection_role": "candidate_only_not_promoted",
            }
        )
    eligible = [row for row in output if row["selection_eligible"] == "true"]
    eligible.sort(key=lambda row: (row["behaviour_fail_count"], row["mean_anchor_relative_error"], row["candidate_id"]))
    selected = eligible[0]["candidate_id"] if eligible else None
    for row in output:
        row["athanasiadis_emulation_candidate"] = str(row["candidate_id"] == selected).lower()
    return output, selected


def run_checkpoint4(
    config_path: str | Path,
    *,
    forecast_run_root: str | Path,
    scratch_root: str | Path | None = None,
    aggregate_only: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    _validate_config(config)
    output = (REPO_ROOT / config["output_root"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = Path(scratch_root).resolve() if scratch_root else (REPO_ROOT / config["checkpoint_4"]["scratch_root"]).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    forecast_root = Path(forecast_run_root).resolve()
    physical_config = (REPO_ROOT / config["checkpoint_4"]["physical_config"]).resolve()

    # This file is deliberately persisted before the first solve.
    _write_csv(output / "scenario_response_expectations.csv", _expectation_rows(config))
    periods = {row["period_id"]: row for row in config["checkpoint_4"]["development_periods"]}
    candidates = list(config["checkpoint_4"]["candidates"])
    scenarios = list(config["checkpoint_4"]["scenarios"])
    _write_csv(output / "frozen_development_week_selection.csv", periods.values())
    statuses: list[dict[str, Any]] = []
    artifacts: dict[tuple[str, str], dict[str, Any]] = {}
    matrix = [(candidate, scenario) for candidate in candidates for scenario in scenarios]
    for index, (candidate, scenario) in enumerate(matrix, start=1):
        candidate_id, scenario_id = candidate["candidate_id"], scenario["scenario_id"]
        case_id = _case_id(candidate_id, scenario_id)
        directory = scratch / case_id
        cached = _case_ready(directory)
        source = "reused_completed_case" if cached else "new_solve"
        case_started = time.perf_counter()
        error = ""
        status = "pass"
        if not cached and not aggregate_only:
            if directory.exists():
                raise Checkpoint4Error(f"Incomplete existing case preserved for inspection: {directory}")
            overrides = {
                "run_id": case_id,
                "lineage_role": "checkpoint4_development_case_cache",
                "forecast_run_root": str(forecast_root),
                **_scenario_overrides(scenario, periods),
                **_candidate_overrides(candidate),
            }
            try:
                run_closed_loop_feasibility_anchor_reconciliation(
                    config_path=physical_config,
                    output_root=scratch,
                    scenario_overrides=overrides,
                )
            except Exception as exc:
                status, error = "fail", f"{type(exc).__name__}: {exc}"
            cached = _case_ready(directory)
            if not cached:
                status = "fail"
                error = error or "p_af returned without a complete passing case"
        elif not cached:
            status, source, error = "fail", "aggregate_only_cache_check", "complete case cache missing"
        statuses.append(
            {
                "candidate_id": candidate_id,
                "scenario_id": scenario_id,
                "case_id": case_id,
                "status": status,
                "source": source,
                "runtime_seconds_this_invocation": round(time.perf_counter() - case_started, 6),
                "error": error,
            }
        )
        _write_csv(output / "checkpoint4_case_status.csv", statuses)
        _write_json(output / "checkpoint4_progress.json", {
            "expected_case_count": 30,
            "completed_case_count": sum(row["status"] == "pass" for row in statuses),
            "failed_case_count": sum(row["status"] != "pass" for row in statuses),
            "latest_case_id": case_id,
            "decision": "in_progress" if status == "pass" and index < len(matrix) else status,
        })
        print(f"[{index}/{len(matrix)}] {case_id}: {status} ({source})", flush=True)
        if status != "pass":
            raise Checkpoint4Error(f"Checkpoint 4 stopped on {case_id}: {error}")
        artifact = _artifact(directory)
        artifact["physical"] = _read_csv(directory / "annual_physical_boundary_ledger.csv")
        artifact["directory"] = str(directory)
        artifacts[(candidate_id, scenario_id)] = artifact

    summary_rows = _summary_rows(artifacts)
    anchors = _anchor_rows(summary_rows)
    behaviour = _behaviour_rows(summary_rows)
    guardrails = _guardrail_rows(artifacts)
    solver = _solver_rows(artifacts)
    if len(solver) != 420:
        raise Checkpoint4Error(f"Expected 420 solved models, found {len(solver)}.")
    failures = [row for row in guardrails if row["status"] != "pass"]
    if failures:
        raise Checkpoint4Error(f"Physical/identity guardrails failed: {len(failures)} rows.")
    selection, selected = _selection_rows(anchors, behaviour, guardrails)
    _write_csv(output / "strategy_candidate_comparison.csv", summary_rows)
    _write_csv(output / "anchor_movements.csv", anchors)
    _write_csv(output / "scenario_response_checks.csv", behaviour)
    _write_csv(output / "checkpoint4_physical_guardrails.csv", guardrails)
    _write_csv(output / "checkpoint4_solver_runtime_metrics.csv", solver)
    _write_csv(output / "checkpoint4_candidate_selection.csv", selection)

    prior_manifest = output / "input_manifest.json"
    prior_manifest_sha = _sha256(prior_manifest) if prior_manifest.is_file() else ""
    repository_files = [
        config_file,
        physical_config,
        Path(__file__).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract/user_authorized_emulation_anchor_overlay.csv",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract/user_authorized_emulation_parameter_overlay.csv",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/S4/c5_tata_benchmark_target_contract/representative_week_selection_contract.csv",
    ]
    _write_json(output / "input_manifest.json", {
        "run_id": config["run_id"],
        "checkpoint": 4,
        "prior_checkpoint3_manifest_sha256": prior_manifest_sha,
        "forecast_source_run_id": "20260706_024807_lago_lear_six_year_benchmark",
        "forecast_runtime_root_persisted": False,
        "held_out_periods_used": False,
        "repository_files": [
            {"path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"), "sha256": _sha256(path)}
            for path in repository_files
        ],
        "case_cache": {"root": str(scratch.relative_to(REPO_ROOT)).replace("\\", "/"), "case_count": len(artifacts), "persistent_output_policy": "local_resumable_cache_not_git_eligible"},
    })
    resolved = dict(config)
    resolved["checkpoint_4_runtime"] = {
        "forecast_source_run_id": "20260706_024807_lago_lear_six_year_benchmark",
        "forecast_runtime_root_persisted": False,
        "case_count": len(artifacts),
        "model_count": len(solver),
    }
    (output / "resolved_config.yaml").write_text(yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8")
    _write_json(output / "code_version.json", {"git_commit": _git_head(), "checkpoint": 4})
    total_runtime = sum(_number(row.get("runtime_seconds")) for row in solver)
    run_summary = {
        "run_id": config["run_id"],
        "status": "pass",
        "checkpoint_id": "checkpoint_4_frozen_development_week_behavioural_evaluation",
        "development_period_ids": list(periods),
        "held_out_periods_used": False,
        "candidate_count": len(candidates),
        "scenario_profile_count": len(scenarios),
        "rolling_case_count": len(artifacts),
        "model_count": len(solver),
        "optimal_model_count": sum(row.get("termination_condition") == "optimal" for row in solver),
        "physical_guardrail_failure_count": 0,
        "behaviour_failure_count": sum(row["status"] == "fail" for row in behaviour),
        "athanasiadis_emulation_candidate": selected,
        "candidate_promotion_status": "not_promoted_checkpoint4_development_only",
        "solver_runtime_seconds_sum": round(total_runtime, 6),
        "wall_runtime_seconds_this_invocation": round(time.perf_counter() - started, 6),
        "maximum_variables": max(int(float(row["variable_count"])) for row in solver),
        "maximum_binaries": max(int(float(row["binary_count"])) for row in solver),
        "maximum_constraints": max(int(float(row["constraint_count"])) for row in solver),
        "next_checkpoint": "independent_review_before_any_held_out_final_evaluation",
    }
    _write_json(output / "run_summary.json", run_summary)
    _write_json(output / "checkpoint_state.json", {
        "run_id": config["run_id"],
        "completed_checkpoint": 4,
        "checkpoint_4_status": "complete_pending_independent_review",
        "athanasiadis_emulation_candidate": selected,
        "promotion_status": "not_promoted",
        "held_out_final_weeks_status": "frozen_not_used",
        "next_checkpoint": "independent_review",
    })
    _write_json(output / "registry_entry.json", {
        "run_id": config["run_id"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "output_policy": "minimal",
        "status": "pass",
        "git_eligible": False,
    })
    (output / "README.md").write_text(
        "# User-authorized full-site emulation — Checkpoint 4\n\n"
        "Five frozen cases were evaluated on the pre-existing calm and volatile/negative validation weeks. "
        "The six profiles consolidate the negative-price observation with the volatile validation week and its separately labelled rolling y_true oracle. "
        "All outputs are representative-development-week diagnostics; no final held-out week was opened. "
        f"The selected development-only `athanasiadis_emulation_candidate` is `{selected or 'none'}` and is not promoted.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a Tata IJmuiden-inspired emulation, not an exact digital twin.\n"
        "- The two weeks are development/validation periods, not a full-year empirical backtest.\n"
        "- The rolling y_true case is a receding D-D+4 oracle sensitivity; only identical-state first-window comparisons can be called an upper bound.\n"
        "- BF6/BF7 exact utilization is structurally unobservable without a compatible capacity denominator; oxygen-buffer detail is absent.\n"
        "- Residual electricity and NG remain reporting-only; export, bidding, settlement, revenue, ETS, stochasticity, CVaR and mFRR remain excluded.\n",
        encoding="utf-8",
    )
    return run_summary
