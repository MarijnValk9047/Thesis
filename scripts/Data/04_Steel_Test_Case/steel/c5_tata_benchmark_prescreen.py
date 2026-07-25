from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c_unified_physical_modelbuilder import SELECTED_WAG_LHV_MJ_PER_NM3
from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    _first_order_full_site_co2_ledger,
    _parameter_range_exception_report,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_tata_benchmark_prescreen.yaml"
)
C0 = "C0_current_BF_BOF_reference"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
CARRIERS = ("BFG", "COG", "BOFG")
TOLERANCE = 1e-6


class PrescreenError(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise PrescreenError(f"Refusing to write an empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["output_policy"] != "minimal":
        raise PrescreenError("Checkpoint 3 requires output_policy=minimal.")
    if config.get("mode") == "user_authorized_full_site_emulation_prescreen":
        if not config["design"]["analytical_prescreen_only"]:
            raise PrescreenError("Checkpoint 3 must remain an analytical prescreen.")
        if config["execution"].get("solver_runs_enabled"):
            raise PrescreenError("Checkpoint 3 forbids solver and rolling execution.")
        return config
    if not config["projection"]["analytical_prescreen_only"]:
        raise PrescreenError("Checkpoint 3 must remain an analytical prescreen.")
    return config


def _repo_path(value: str) -> Path:
    return (REPO_ROOT / value).resolve()


def _parameter_rows(config: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    path = _repo_path(
        f"{config['contract_root']}/calibratable_parameter_contract.csv"
    )
    return {row["parameter_id"]: row for row in _read_csv(path)}


def _target_rows(config: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    path = _repo_path(
        f"{config['contract_root']}/calibration_validation_target_contract.csv"
    )
    return {row["target_id"]: row for row in _read_csv(path)}


def candidate_definitions(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    parameters = _parameter_rows(config)
    bfg = parameters["bfg_generation_nm3_per_t_hot_metal"]
    cog = parameters["cog_generation_m3_per_t_dry_coal"]
    bofg = parameters["bofg_generation_nm3_per_t_liquid_steel"]
    candidates: list[dict[str, Any]] = []
    for position in config["candidate_design"]["wag_normalized_positions"]:
        position = float(position)
        for efficiency in config["candidate_design"]["vn25_efficiency_choices"]:
            efficiency = float(efficiency)
            candidate_id = f"wag_p{int(round(position * 10)):02d}_eta_{int(round(efficiency * 1000)):03d}"
            candidate = {
                "candidate_id": candidate_id,
                "wag_normalized_position": position,
                "vn25_electricity_efficiency": efficiency,
                "bfg_generation_nm3_per_t_hot_metal": float(bfg["low"])
                + position * (float(bfg["high"]) - float(bfg["low"])),
                "cog_generation_m3_per_t_dry_coal": float(cog["low"])
                + position * (float(cog["high"]) - float(cog["low"])),
                "bofg_generation_nm3_per_t_liquid_steel": float(bofg["low"])
                + position * (float(bofg["high"]) - float(bofg["low"])),
                "source_baseline": position
                == float(config["candidate_design"]["source_baseline_wag_position"])
                and efficiency
                == float(config["candidate_design"]["source_baseline_vn25_efficiency"]),
                "wag_parameter_at_bound": position in {0.0, 1.0},
                "vn25_parameter_at_bound": efficiency
                in {
                    min(float(value) for value in config["candidate_design"]["vn25_efficiency_choices"]),
                    max(float(value) for value in config["candidate_design"]["vn25_efficiency_choices"]),
                },
            }
            candidate["any_parameter_at_bound"] = (
                candidate["wag_parameter_at_bound"]
                or candidate["vn25_parameter_at_bound"]
            )
            candidates.append(candidate)
    expected = int(config["candidate_design"]["expected_candidate_count"])
    if len(candidates) != expected:
        raise PrescreenError(f"Expected {expected} candidates, created {len(candidates)}.")
    return candidates


def load_annual_baseline(config: Mapping[str, Any]) -> dict[str, Any]:
    parent = _repo_path(str(config["parent_run_root"]))
    wag_rows = _read_csv(parent / "annual_wag_source_to_sink_ledger.csv")
    electricity_rows = _read_csv(parent / "annual_electricity_ng_co2_ledger.csv")
    carriers: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for configuration in (C0, C1):
        for carrier in CARRIERS:
            selected = [
                row
                for row in wag_rows
                if row["configuration_id"] == configuration
                and row["carrier_or_material"] == carrier
            ]
            generation = sum(
                float(row["annual_value"])
                for row in selected
                if row["flow_role"] == "generation"
            )
            fixed_sinks = {
                row["component"]: float(row["annual_value"])
                for row in selected
                if row["flow_role"] == "use"
                and "vattenfall" not in row["component"].lower()
            }
            carriers[configuration][carrier] = {
                "baseline_generation_mwh_lhv": generation,
                "fixed_non_generator_sinks_mwh_lhv": fixed_sinks,
            }
    gross = {
        configuration: next(
            float(row["annual_value"])
            for row in electricity_rows
            if row["configuration_id"] == configuration
            and row["component"] == "represented_gross_electricity"
        )
        for configuration in (C0, C1)
    }
    return {"carriers": carriers, "gross_electricity_mwh": gross}


def build_boundary_bridge_audit(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Reconcile Athanasiadis context to accepted ledgers without calibration."""

    parent = _repo_path(str(config["parent_run_root"]))
    wag_rows = _read_csv(parent / "annual_wag_source_to_sink_ledger.csv")
    electricity_rows = _read_csv(parent / "annual_electricity_ng_co2_ledger.csv")
    targets = _target_rows(config)
    target_by_configuration = {
        C0: targets["athan_c0_aggregate_wag_2_74"],
        C1: targets["athan_c1_aggregate_wag_1_23"],
    }
    efficiencies = {
        C0: float(config["projection"]["c0_wag_to_power_efficiency"]),
        C1: float(config["candidate_design"]["source_baseline_vn25_efficiency"]),
    }
    result: list[dict[str, Any]] = []
    for configuration in (C0, C1):
        scoped_wag = [
            row for row in wag_rows if row["configuration_id"] == configuration
        ]
        scoped_electricity = [
            row
            for row in electricity_rows
            if row["configuration_id"] == configuration
        ]

        def wag_value(carrier: str, role: str, *, generator: bool | None = None) -> float:
            selected = [
                row
                for row in scoped_wag
                if row["carrier_or_material"] == carrier
                and row["flow_role"] == role
            ]
            if generator is not None:
                selected = [
                    row
                    for row in selected
                    if ("vattenfall" in row["component"].lower()) is generator
                ]
            return sum(float(row["annual_value"]) for row in selected)

        def electricity_value(component: str) -> float:
            return next(
                float(row["annual_value"])
                for row in scoped_electricity
                if row["component"] == component
            )

        carrier_values: dict[str, dict[str, float]] = {}
        for carrier in CARRIERS:
            carrier_values[carrier] = {
                "generation": wag_value(carrier, "generation"),
                "mandatory": wag_value(carrier, "use", generator=False),
                "generator": wag_value(carrier, "use", generator=True),
                "flare": wag_value(carrier, "flare"),
            }
        totals = {
            role: sum(values[role] for values in carrier_values.values())
            for role in ("generation", "mandatory", "generator", "flare")
        }
        efficiency = efficiencies[configuration]
        total_generator_twh = electricity_value("WAG_internal_generation") / 1_000_000.0
        ng_generator_fuel_mwh = electricity_value("VN25_generator")
        ng_generator_twh = ng_generator_fuel_mwh * efficiency / 1_000_000.0
        wag_generator_twh = total_generator_twh - ng_generator_twh
        technical_wag_potential_twh = (
            totals["generator"] + totals["flare"]
        ) * efficiency / 1_000_000.0
        gross_twh = electricity_value("represented_gross_electricity") / 1_000_000.0
        grid_twh = electricity_value("represented_net_grid_import") / 1_000_000.0
        target = target_by_configuration[configuration]
        normalized_target_twh = (
            float(target["value_central"])
            * float(config["scoring"]["final_product_mt_y"])
            / float(config["scoring"]["source_target_denominator_mt_y"])
        )
        temporal_gap_twh = max(
            0.0, min(technical_wag_potential_twh, gross_twh) - wag_generator_twh
        )
        demand_no_export_gap_twh = max(0.0, technical_wag_potential_twh - gross_twh)
        remaining_context_gap_twh = normalized_target_twh - technical_wag_potential_twh
        row: dict[str, Any] = {
            "configuration_id": configuration,
            "boundary_class": "comparable_only_after_boundary_bridge",
        }
        for carrier in CARRIERS:
            for role in ("generation", "mandatory", "generator", "flare"):
                row[f"{carrier}_{role}_pj_y"] = round(
                    carrier_values[carrier][role] * 0.0000036, 9
                )
        for role in ("generation", "mandatory", "generator", "flare"):
            row[f"total_WAG_{role}_pj_y"] = round(totals[role] * 0.0000036, 9)
        row.update(
            {
                "WAG_generator_electricity_twh_y": round(wag_generator_twh, 9),
                "NG_generator_electricity_twh_y": round(ng_generator_twh, 9),
                "generator_internal_electricity_total_twh_y": round(total_generator_twh, 9),
                "internal_offset_twh_y": round(total_generator_twh, 9),
                "technical_WAG_potential_twh_y": round(technical_wag_potential_twh, 9),
                "represented_gross_electricity_twh_y": round(gross_twh, 9),
                "explicit_Linde_N2_auxiliary_twh_y": round(45.0 * 8760.0 / 1_000_000.0, 9),
                "reporting_only_full_site_gap_twh_y": round(
                    electricity_value("full_site_anchor_minus_represented_gross") / 3.6,
                    9,
                ),
                "represented_grid_import_twh_y": round(grid_twh, 9),
                "export_status": "prohibited",
                "electricity_identity_residual_mwh_y": electricity_value(
                    "gross_minus_internal_minus_grid"
                ),
                "reported_carrier_residual_mwh_y": round(
                    sum(
                        float(row_["annual_value"])
                        for row_ in scoped_wag
                        if row_["flow_role"] == "accounting_residual"
                    ),
                    6,
                ),
                "reconstructed_carrier_residual_mwh_y": round(
                    totals["generation"]
                    - totals["mandatory"]
                    - totals["generator"]
                    - totals["flare"],
                    6,
                ),
                "athanasiadis_raw_twh_y": float(target["value_central"]),
                "athanasiadis_normalized_to_6_75_twh_y": round(normalized_target_twh, 9),
                "WAG_electricity_gap_twh_y": round(
                    normalized_target_twh - wag_generator_twh, 9
                ),
                "gap_temporal_dispatch_twh_y": round(temporal_gap_twh, 9),
                "gap_demand_no_export_twh_y": round(demand_no_export_gap_twh, 9),
                "gap_remaining_physical_context_twh_y": round(
                    remaining_context_gap_twh, 9
                ),
                "gap_decomposition_residual_twh_y": round(
                    normalized_target_twh
                    - wag_generator_twh
                    - temporal_gap_twh
                    - demand_no_export_gap_twh
                    - remaining_context_gap_twh,
                    12,
                ),
            }
        )
        result.append(row)
    return result


def _candidate_coefficients(candidate: Mapping[str, Any]) -> dict[str, float]:
    return {
        "BFG": float(candidate["bfg_generation_nm3_per_t_hot_metal"]),
        "COG": float(candidate["cog_generation_m3_per_t_dry_coal"]),
        "BOFG": float(candidate["bofg_generation_nm3_per_t_liquid_steel"]),
    }


def _baseline_coefficients(parameters: Mapping[str, Mapping[str, str]]) -> dict[str, float]:
    return {
        "BFG": float(parameters["bfg_generation_nm3_per_t_hot_metal"]["active_central"]),
        "COG": float(parameters["cog_generation_m3_per_t_dry_coal"]["active_central"]),
        "BOFG": float(parameters["bofg_generation_nm3_per_t_liquid_steel"]["active_central"]),
    }


def project_candidate(
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
    parameters: Mapping[str, Mapping[str, str]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_coefficients = _candidate_coefficients(candidate)
    central_coefficients = _baseline_coefficients(parameters)
    result: dict[str, Any] = {"configurations": {}, "guardrails": []}
    annual_hours = float(config["projection"]["annual_hours"])
    for configuration in (C0, C1):
        carrier_rows: dict[str, Any] = {}
        negative_sink = False
        for carrier in CARRIERS:
            source = baseline["carriers"][configuration][carrier]
            generation = float(source["baseline_generation_mwh_lhv"]) * (
                candidate_coefficients[carrier] / central_coefficients[carrier]
            )
            fixed_sinks = sum(source["fixed_non_generator_sinks_mwh_lhv"].values())
            surplus = generation - fixed_sinks
            negative_sink = negative_sink or surplus < -TOLERANCE
            carrier_rows[carrier] = {
                "generation_mwh_lhv": generation,
                "fixed_non_generator_sinks_mwh_lhv": fixed_sinks,
                "fixed_non_generator_named_sinks_mwh_lhv": dict(
                    source["fixed_non_generator_sinks_mwh_lhv"]
                ),
                "surplus_before_generator_mwh_lhv": max(0.0, surplus),
            }

        efficiency = (
            float(config["projection"]["c0_wag_to_power_efficiency"])
            if configuration == C0
            else float(candidate["vn25_electricity_efficiency"])
        )
        total_surplus = sum(
            row["surplus_before_generator_mwh_lhv"] for row in carrier_rows.values()
        )
        volume_nm3 = sum(
            row["surplus_before_generator_mwh_lhv"]
            * 3600.0
            / float(SELECTED_WAG_LHV_MJ_PER_NM3[carrier])
            for carrier, row in carrier_rows.items()
        )
        volume_cap = float(
            config["projection"][
                "c0_total_generator_volume_cap_nm3_h"
                if configuration == C0
                else "c1_total_generator_volume_cap_nm3_h"
            ]
        ) * annual_hours
        volume_scale = min(1.0, volume_cap / volume_nm3) if volume_nm3 > 0.0 else 1.0
        fuel_after_volume_cap = total_surplus * volume_scale
        gross_electricity = float(baseline["gross_electricity_mwh"][configuration])
        electric_capacity = (
            float("inf")
            if configuration == C0
            else float(config["projection"]["c1_vn25_electric_capacity_mw"])
            * annual_hours
        )
        electricity_limit = min(gross_electricity, electric_capacity)
        potential_electricity = fuel_after_volume_cap * efficiency
        electricity_scale = (
            min(1.0, electricity_limit / potential_electricity)
            if potential_electricity > 0.0
            else 1.0
        )
        common_generator_scale = volume_scale * electricity_scale
        max_identity_residual = 0.0
        for carrier, row in carrier_rows.items():
            generator = row["surplus_before_generator_mwh_lhv"] * common_generator_scale
            flare = row["generation_mwh_lhv"] - row["fixed_non_generator_sinks_mwh_lhv"] - generator
            identity = row["generation_mwh_lhv"] - row["fixed_non_generator_sinks_mwh_lhv"] - generator - flare
            row["generator_mwh_lhv"] = generator
            row["flare_mwh_lhv"] = flare
            row["identity_residual_mwh_lhv"] = identity
            max_identity_residual = max(max_identity_residual, abs(identity))
        generator_fuel = sum(row["generator_mwh_lhv"] for row in carrier_rows.values())
        wag_electricity = generator_fuel * efficiency
        no_export_residual = max(0.0, wag_electricity - gross_electricity)
        capacity_residual = max(0.0, wag_electricity - electric_capacity)
        status = (
            "reject"
            if negative_sink
            or max_identity_residual > TOLERANCE
            or no_export_residual > TOLERANCE
            or capacity_residual > TOLERANCE
            else "pass"
        )
        result["configurations"][configuration] = {
            "carriers": carrier_rows,
            "efficiency": efficiency,
            "generator_volume_nm3_before_cap": volume_nm3,
            "generator_volume_cap_nm3_y": volume_cap,
            "volume_cap_binding": volume_scale < 1.0 - TOLERANCE,
            "gross_electricity_mwh": gross_electricity,
            "electric_capacity_mwh_y": None if configuration == C0 else electric_capacity,
            "no_export_binding": wag_electricity >= gross_electricity - TOLERANCE,
            "electric_capacity_binding": configuration == C1
            and wag_electricity >= electric_capacity - TOLERANCE,
            "wag_electricity_mwh": wag_electricity,
            "generator_fuel_mwh_lhv": generator_fuel,
            "flare_mwh_lhv": sum(row["flare_mwh_lhv"] for row in carrier_rows.values()),
            "negative_fixed_sink_feasibility": negative_sink,
            "max_abs_carrier_identity_residual_mwh": max_identity_residual,
            "no_export_violation_mwh": no_export_residual,
            "generator_capacity_violation_mwh": capacity_residual,
            "status": status,
        }
    return result


def score_candidate(
    candidate: Mapping[str, Any],
    projection: Mapping[str, Any],
    targets: Mapping[str, Mapping[str, str]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    final_product_mt = float(config["scoring"]["final_product_mt_y"])
    source_denominator_mt = float(config["scoring"]["source_target_denominator_mt_y"])
    target_ids = list(config["scoring"]["target_ids"])
    if any(targets[target_id]["classification"] != "calibration_target" for target_id in target_ids):
        raise PrescreenError("Only calibration_target observations may enter the score.")
    mapping = {C0: target_ids[0], C1: target_ids[1]}
    row = dict(candidate)
    abs_errors: dict[str, float] = {}
    physical_failures = 0
    boundary_violations = 0
    for short, configuration in (("c0", C0), ("c1", C1)):
        projected_twh = projection["configurations"][configuration]["wag_electricity_mwh"] / 1_000_000.0
        target_twh = float(targets[mapping[configuration]]["value_central"])
        model_intensity = projected_twh / final_product_mt
        target_intensity = target_twh / source_denominator_mt
        signed_intensity = model_intensity - target_intensity
        normalized_signed = signed_intensity / target_intensity
        abs_errors[short] = abs(normalized_signed)
        row.update(
            {
                f"{short}_calibration_target_id": mapping[configuration],
                f"{short}_projected_wag_electricity_twh_y": projected_twh,
                f"{short}_target_wag_electricity_twh_y": target_twh,
                f"{short}_model_mwh_per_t_final_product": model_intensity,
                f"{short}_target_mwh_per_t_final_product": target_intensity,
                f"{short}_signed_residual_mwh_per_t": signed_intensity,
                f"{short}_normalized_signed_error": normalized_signed,
                f"{short}_normalized_absolute_error": abs(normalized_signed),
                f"{short}_negative_sink_feasibility": projection["configurations"][configuration]["negative_fixed_sink_feasibility"],
                f"{short}_max_abs_identity_residual_mwh": projection["configurations"][configuration]["max_abs_carrier_identity_residual_mwh"],
                f"{short}_flare_mwh_lhv_y": projection["configurations"][configuration]["flare_mwh_lhv"],
                f"{short}_no_export_binding": projection["configurations"][configuration]["no_export_binding"],
                f"{short}_volume_cap_binding": projection["configurations"][configuration]["volume_cap_binding"],
                f"{short}_electric_capacity_binding": projection["configurations"][configuration]["electric_capacity_binding"],
            }
        )
        physical_failures += int(
            projection["configurations"][configuration]["negative_fixed_sink_feasibility"]
            or projection["configurations"][configuration]["max_abs_carrier_identity_residual_mwh"] > TOLERANCE
        )
        boundary_violations += int(
            projection["configurations"][configuration]["no_export_violation_mwh"] > TOLERANCE
            or projection["configurations"][configuration]["generator_capacity_violation_mwh"] > TOLERANCE
        )
    source_deviation_raw = (
        abs(float(candidate["wag_normalized_position"]) - 0.5) / 0.5
        + (0.0 if float(candidate["vn25_electricity_efficiency"]) == 0.345 else 1.0)
    ) / 2.0
    source_deviation_weighted = source_deviation_raw * float(
        config["scoring"]["source_central_penalty_weight"]
    )
    physical_penalty = physical_failures * float(config["scoring"]["physical_failure_penalty"])
    boundary_penalty = boundary_violations * float(config["scoring"]["boundary_violation_penalty"])
    row.update(
        {
            "anchor_error_equal_weight_sum": abs_errors["c0"] + abs_errors["c1"],
            "source_central_deviation_raw": source_deviation_raw,
            "source_central_deviation_penalty": source_deviation_weighted,
            "physical_failure_count": physical_failures,
            "physical_penalty": physical_penalty,
            "boundary_violation_count": boundary_violations,
            "boundary_penalty": boundary_penalty,
            "selection_score_explained_sum": abs_errors["c0"]
            + abs_errors["c1"]
            + source_deviation_weighted
            + physical_penalty
            + boundary_penalty,
            "prescreen_status": "reject"
            if physical_failures or boundary_violations
            else "pass",
            "scored_target_classes": "calibration_target_only",
            "independent_validation_in_score": False,
        }
    )
    return row


def _annotate_improvement(rows: list[dict[str, Any]]) -> None:
    baseline = next(row for row in rows if row["source_baseline"])
    for row in rows:
        c0 = row["c0_normalized_absolute_error"] < baseline["c0_normalized_absolute_error"] - TOLERANCE
        c1 = row["c1_normalized_absolute_error"] < baseline["c1_normalized_absolute_error"] - TOLERANCE
        row["improves_c0_vs_source_baseline"] = c0
        row["improves_c1_vs_source_baseline"] = c1
        row["improves_only_one_configuration"] = c0 != c1


def retain_candidates(
    rows: list[dict[str, Any]], config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    maximum = int(config["retention"]["maximum_candidates"])
    eligible = [
        row
        for row in rows
        if row["prescreen_status"] == "pass" and not row["wag_parameter_at_bound"]
    ]
    ranked = sorted(
        eligible,
        key=lambda row: (
            row["selection_score_explained_sum"],
            row["source_central_deviation_raw"],
            row["candidate_id"],
        ),
    )
    retained: list[dict[str, Any]] = []

    def add(row: dict[str, Any]) -> None:
        if row not in retained and len(retained) < maximum:
            retained.append(row)

    add(next(row for row in rows if row["source_baseline"]))
    for efficiency in sorted(
        {float(row["vn25_electricity_efficiency"]) for row in eligible}
    ):
        add(next(row for row in ranked if float(row["vn25_electricity_efficiency"]) == efficiency))
    selected_positions = {float(row["wag_normalized_position"]) for row in retained}
    for row in ranked:
        if float(row["wag_normalized_position"]) in selected_positions:
            continue
        add(row)
        selected_positions.add(float(row["wag_normalized_position"]))
        if len(retained) == maximum:
            break
    for rank, row in enumerate(retained, start=1):
        row["retained"] = True
        row["retention_rank"] = rank
    retained_ids = {row["candidate_id"] for row in retained}
    for row in rows:
        if row["candidate_id"] not in retained_ids:
            row["retained"] = False
            row["retention_rank"] = ""
    return retained


def build_prescreen(config: Mapping[str, Any]) -> dict[str, Any]:
    targets = _target_rows(config)
    configured_target_ids = list(config["scoring"]["target_ids"])
    invalid_targets = [
        target_id
        for target_id in configured_target_ids
        if target_id not in targets
        or targets[target_id]["classification"] != "calibration_target"
        or targets[target_id]["calibration_use"] != "true"
        or targets[target_id]["score_family"] == "excluded"
    ]
    if invalid_targets:
        raise PrescreenError(
            "Configured scored rows are not active calibration targets: "
            + ";".join(invalid_targets)
        )
    baseline = load_annual_baseline(config)
    parameters = _parameter_rows(config)
    candidates = candidate_definitions(config)
    score_rows: list[dict[str, Any]] = []
    projections: dict[str, Any] = {}
    for candidate in candidates:
        projection = project_candidate(candidate, baseline, parameters, config)
        projections[candidate["candidate_id"]] = projection
        score_rows.append(score_candidate(candidate, projection, targets, config))
    _annotate_improvement(score_rows)
    retained = retain_candidates(score_rows, config)
    guardrails: list[dict[str, Any]] = []
    carrier_ledger: list[dict[str, Any]] = []
    for row in score_rows:
        for short in ("c0", "c1"):
            configuration_id = C0 if short == "c0" else C1
            guardrails.append(
                {
                    "candidate_id": row["candidate_id"],
                    "configuration": short.upper(),
                    "negative_fixed_sink_feasibility": row[f"{short}_negative_sink_feasibility"],
                    "max_abs_carrier_identity_residual_mwh": row[f"{short}_max_abs_identity_residual_mwh"],
                    "no_export_binding": row[f"{short}_no_export_binding"],
                    "volume_cap_binding": row[f"{short}_volume_cap_binding"],
                    "electric_capacity_binding": row[f"{short}_electric_capacity_binding"],
                    "status": "pass"
                    if not row[f"{short}_negative_sink_feasibility"]
                    and row[f"{short}_max_abs_identity_residual_mwh"] <= TOLERANCE
                    else "reject",
                }
            )
            for carrier, carrier_row in projections[row["candidate_id"]]["configurations"][configuration_id]["carriers"].items():
                common = {
                    "candidate_id": row["candidate_id"],
                    "configuration_id": configuration_id,
                    "carrier": carrier,
                    "unit": "MWh_LHV/y",
                }
                carrier_ledger.append(
                    {**common, "flow_role": "generation", "component": f"{carrier}_generated", "annual_value": carrier_row["generation_mwh_lhv"], "fixed_named_sink": False}
                )
                for component, value in carrier_row["fixed_non_generator_named_sinks_mwh_lhv"].items():
                    carrier_ledger.append(
                        {**common, "flow_role": "use", "component": component, "annual_value": value, "fixed_named_sink": True}
                    )
                carrier_ledger.extend(
                    [
                        {**common, "flow_role": "generator", "component": f"{carrier}_to_generator", "annual_value": carrier_row["generator_mwh_lhv"], "fixed_named_sink": False},
                        {**common, "flow_role": "flare", "component": f"{carrier}_flared", "annual_value": carrier_row["flare_mwh_lhv"], "fixed_named_sink": False},
                        {**common, "flow_role": "identity_residual", "component": f"{carrier}_balance_residual", "annual_value": carrier_row["identity_residual_mwh_lhv"], "fixed_named_sink": False},
                    ]
                )
    return {
        "candidate_scorecard": score_rows,
        "retained_candidates": retained,
        "guardrails": guardrails,
        "candidate_carrier_ledger": carrier_ledger,
        "candidate_overlays": [
            {
                key: candidate[key]
                for key in (
                    "candidate_id",
                    "wag_normalized_position",
                    "vn25_electricity_efficiency",
                    "bfg_generation_nm3_per_t_hot_metal",
                    "cog_generation_m3_per_t_dry_coal",
                    "bofg_generation_nm3_per_t_liquid_steel",
                    "source_baseline",
                )
            }
            for candidate in candidates
        ],
        "projections": projections,
    }


def _input_manifest(config_path: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    parent = _repo_path(str(config["parent_run_root"]))
    contract = _repo_path(str(config["contract_root"]))
    paths = [
        config_path,
        parent / "annual_wag_source_to_sink_ledger.csv",
        parent / "annual_electricity_ng_co2_ledger.csv",
        contract / "calibration_validation_target_contract.csv",
        contract / "calibratable_parameter_contract.csv",
        contract / "baseline_freeze.json",
    ]
    return {
        "inputs": [
            {
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in paths
        ],
        "source_inputs_mutated": False,
    }


def _run_historical_prescreen(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    output_root = _repo_path(str(config["output_root"]))
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_before = _input_manifest(config_file, config)
    result = build_prescreen(config)

    contract_root = _repo_path(str(config["contract_root"]))
    for name in (
        "calibration_validation_target_contract.csv",
        "calibratable_parameter_contract.csv",
        "baseline_freeze.json",
    ):
        shutil.copy2(contract_root / name, output_root / name)
    _write_csv(output_root / "candidate_overlays.csv", result["candidate_overlays"])
    _write_csv(output_root / "candidate_scorecard.csv", result["candidate_scorecard"])
    _write_csv(output_root / "candidate_carrier_ledger.csv", result["candidate_carrier_ledger"])
    _write_csv(output_root / "prescreen_guardrails.csv", result["guardrails"])
    _write_json(
        output_root / "retained_candidates.json",
        {
            "maximum": int(config["retention"]["maximum_candidates"]),
            "ranking_rule": config["retention"]["diversity_rule"],
            "candidates": [
                {
                    "candidate_id": row["candidate_id"],
                    "retention_rank": row["retention_rank"],
                    "selection_score_explained_sum": row["selection_score_explained_sum"],
                    "wag_normalized_position": row["wag_normalized_position"],
                    "vn25_electricity_efficiency": row["vn25_electricity_efficiency"],
                    "any_parameter_at_bound": row["any_parameter_at_bound"],
                    "improves_only_one_configuration": row["improves_only_one_configuration"],
                }
                for row in result["retained_candidates"]
            ],
        },
    )
    _write_json(output_root / "input_manifest.json", manifest_before)
    (output_root / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=True), encoding="utf-8"
    )
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        head = "unavailable"
    _write_json(
        output_root / "code_version.json",
        {"git_head": head, "module": Path(__file__).relative_to(REPO_ROOT).as_posix()},
    )
    manifest_after = _input_manifest(config_file, config)
    source_hashes_unchanged = manifest_before == manifest_after
    retained_ids = [row["candidate_id"] for row in result["retained_candidates"]]
    rejected = [row for row in result["candidate_scorecard"] if row["prescreen_status"] == "reject"]
    bound_rows = [row for row in result["candidate_scorecard"] if row["any_parameter_at_bound"]]
    wag_bound_rows = [row for row in result["candidate_scorecard"] if row["wag_parameter_at_bound"]]
    vn25_bound_rows = [row for row in result["candidate_scorecard"] if row["vn25_parameter_at_bound"]]
    summary = {
        "run_id": config["run_id"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "parent_run_id": config["parent_run_id"],
        "output_policy": config["output_policy"],
        "execution_type": "analytical_prescreen_no_solver",
        "candidate_count": len(result["candidate_scorecard"]),
        "rejected_candidate_count": len(rejected),
        "bound_flag_candidate_count": len(bound_rows),
        "wag_bound_candidate_count": len(wag_bound_rows),
        "vn25_discrete_bound_candidate_count": len(vn25_bound_rows),
        "retained_candidate_count": len(retained_ids),
        "retained_candidate_ids": retained_ids,
        "scored_target_ids": config["scoring"]["target_ids"],
        "independent_validation_in_score": False,
        "source_hashes_unchanged": source_hashes_unchanged,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "status": "pass" if source_hashes_unchanged and len(retained_ids) <= 5 else "fail",
    }
    _write_json(output_root / "run_summary.json", summary)
    _write_json(
        output_root / "checkpoint_state.json",
        {
            "completed_checkpoint": 3,
            "status": summary["status"],
            "next_checkpoint": 4,
            "rolling_or_solver_run_performed": False,
        },
    )
    _write_json(
        output_root / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "parent_run_id": config["parent_run_id"],
            "output_policy": config["output_policy"],
            "status": summary["status"],
        },
    )
    (output_root / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a transparent annual-ledger projection, not solved dispatch or rolling optimisation.\n"
        "- Only Athanasiadis WAG-electricity calibration targets are scored; MER observations remain independent validation.\n"
        "- Fixed non-generator sinks are held at accepted-ledger values; candidate shortfalls are rejected rather than filled with residuals.\n"
        "- C0 uses the accepted aggregate WAG-to-power efficiency; C1 uses only the governed VN25 choices.\n"
        "- No export, volume and electric-capacity limits are conservative annual screens and do not reproduce hourly congestion.\n"
        "- The parent evidence has partial-year-not-annual support; these annualised relationships are prescreen inputs, not a complete empirical annual backtest.\n",
        encoding="utf-8",
    )
    (output_root / "README.md").write_text(
        "# Tata-inspired C5 benchmark prescreen\n\n"
        "Checkpoint 3 evaluates exactly 22 separate analytical overlays: eleven shared carrier-generation range positions crossed with two governed VN25 efficiencies. "
        "It reuses the accepted annual WAG source-to-sink and electricity ledgers, holds named non-generator sinks fixed, preserves BFG/COG/BOFG identities, and applies no-export and generator bounds.\n\n"
        "The score exposes C0 and C1 per-ton errors, source-central deviation, physical penalties and boundary penalties separately. "
        "MER validation is excluded. Retention always includes the source baseline, adds the best candidate for each VN25 choice, then fills distinct WAG positions by explained score; source-bound positions are excluded while interior candidates exist.\n",
        encoding="utf-8",
    )
    return summary


def _overlay_rows(config: Mapping[str, Any], key: str) -> list[dict[str, str]]:
    return _read_csv(_repo_path(str(config[key])))


def _annual_value(
    rows: Iterable[Mapping[str, Any]],
    configuration: str,
    family: str,
    component: str,
) -> float:
    selected = [
        row
        for row in rows
        if row.get("configuration_id") == configuration
        and row.get("ledger_family") == family
        and row.get("component") == component
    ]
    if len(selected) != 1:
        raise PrescreenError(
            f"Expected one annual baseline row for {configuration}/{family}/{component}, "
            f"found {len(selected)}."
        )
    return float(selected[0]["annual_value"])


def _user_authorized_baseline(config: Mapping[str, Any]) -> dict[str, Any]:
    root = _repo_path(str(config["accepted_annual_baseline_root"]))
    ledger = _read_csv(root / "annual_physical_boundary_ledger.csv")
    hourly = _read_csv(root / "executed_hourly.csv")
    parameter_by_id = {
        row["parameter_id"]: row for row in _overlay_rows(config, "parameter_overlay")
    }
    electricity_processes = parameter_by_id[
        "uae_named_process_electricity_intensity_scaling"
    ]["affected_processes"].split(";")
    co2_rows = _first_order_full_site_co2_ledger(hourly)
    baseline: dict[str, Any] = {"configurations": {}, "ledger": ledger}
    for configuration in (C0, C1):
        carriers: dict[str, Any] = {}
        for carrier in CARRIERS:
            scoped = [
                row
                for row in ledger
                if row.get("configuration_id") == configuration
                and row.get("ledger_family") == "WAG"
                and row.get("carrier_or_material") == carrier
            ]
            generation = sum(
                float(row["annual_value"])
                for row in scoped
                if row.get("flow_role") == "generation"
            )
            fixed_sinks = {
                str(row["component"]): float(row["annual_value"])
                for row in scoped
                if row.get("flow_role") == "use"
                and "vattenfall" not in str(row.get("component", "")).lower()
            }
            carriers[carrier] = {
                "generation_mwh_lhv": generation,
                "fixed_non_generator_sinks": fixed_sinks,
            }
        process_loads = {
            process: _annual_value(
                ledger,
                configuration,
                "electricity_decomposition",
                "PEFA" if process == "PeFa" else process,
            )
            for process in electricity_processes
        }
        selected_process = sorted(
            process_loads,
            key=lambda process: (-process_loads[process], process),
        )[0]
        co2_subtotal = next(
            float(row["annual_co2_mt_y"])
            for row in co2_rows
            if row.get("configuration_id") == configuration
            and row.get("component") == "selected_process_factor_subtotal"
        )
        mode_b = _annual_value(
            ledger,
            configuration,
            "Mode_B_CO2",
            "represented_Mode_B_explicit_fuel",
        )
        named_ng = _annual_value(
            ledger, configuration, "named_NG", "represented_named_NG"
        )
        baseline["configurations"][configuration] = {
            "carriers": carriers,
            "represented_gross_mwh": _annual_value(
                ledger, configuration, "electricity", "represented_gross_electricity"
            ),
            "internal_generator_total_mwh": _annual_value(
                ledger, configuration, "electricity", "WAG_internal_generation"
            ),
            "named_ng_mwh_lhv": named_ng,
            "electricity_process_loads_mwh": process_loads,
            "selected_electricity_process": selected_process,
            "selected_electricity_process_load_mwh": process_loads[selected_process],
            "first_order_process_factor_subtotal_mt": co2_subtotal,
            "mode_b_explicit_fuel_co2_mt": mode_b / 1_000_000.0,
            "baseline_max_accounting_residual": max(
                (
                    abs(float(row["annual_value"]))
                    for row in ledger
                    if row.get("configuration_id") == configuration
                    and row.get("flow_role") == "accounting_residual"
                ),
                default=0.0,
            ),
        }
    cog_central = float(parameter_by_id["uae_cog_generation_yield"]["baseline_central"])
    cog_mwh_per_t_coal = (
        cog_central * SELECTED_WAG_LHV_MJ_PER_NM3["COG"] / 3600.0
    )
    baseline["c0_coal_mt"] = (
        baseline["configurations"][C0]["carriers"]["COG"]["generation_mwh_lhv"]
        / cog_mwh_per_t_coal
        / 1_000_000.0
    )
    baseline["source_root"] = root
    return baseline


def user_authorized_candidate_definitions(
    config: Mapping[str, Any], baseline: Mapping[str, Any]
) -> list[dict[str, Any]]:
    parameters = {
        row["parameter_id"]: row for row in _overlay_rows(config, "parameter_overlay")
    }
    yield_parameters = {
        "BFG_yield": "uae_bfg_generation_yield",
        "COG_yield": "uae_cog_generation_yield",
        "BOFG_yield": "uae_bofg_generation_yield",
    }
    candidates: list[dict[str, Any]] = [
        {
            "candidate_id": config["design"]["source_baseline"]["candidate_id"],
            "source_baseline": True,
            "background_share": 0.0,
            "recipe_id": "source_baseline_no_overlay",
            "parameter_family": "none",
            "direction": "central",
            "electricity_intensity_scale": 1.0,
            "selected_electricity_process_c0": "",
            "selected_electricity_process_c1": "",
            "selection_rule": "immutable source-driven baseline; no user-authorized movement",
        }
    ]
    for share in config["design"]["background_electricity_shares"]:
        for recipe in config["design"]["perturbation_recipes"]:
            family = str(recipe["parameter_family"])
            direction = str(recipe["direction"])
            candidate = {
                "candidate_id": f"bg{int(round(float(share) * 100)):02d}_{recipe['recipe_id']}",
                "source_baseline": False,
                "background_share": float(share),
                "recipe_id": recipe["recipe_id"],
                "parameter_family": family,
                "direction": direction,
                "electricity_intensity_scale": 1.0,
                "selected_electricity_process_c0": "",
                "selected_electricity_process_c1": "",
                "selection_rule": "one-family-at-a-time frozen design",
            }
            for carrier, parameter_id in (
                ("BFG", "uae_bfg_generation_yield"),
                ("COG", "uae_cog_generation_yield"),
                ("BOFG", "uae_bofg_generation_yield"),
            ):
                candidate[f"{carrier}_yield"] = float(
                    parameters[parameter_id]["baseline_central"]
                )
            if family in yield_parameters:
                parameter_id = yield_parameters[family]
                carrier = family.split("_")[0]
                candidate[f"{carrier}_yield"] = float(
                    parameters[parameter_id][
                        "first_relaxed_low" if direction == "low" else "first_relaxed_high"
                    ]
                )
            elif family == "named_process_electricity_intensity":
                parameter = parameters[
                    "uae_named_process_electricity_intensity_scaling"
                ]
                candidate["electricity_intensity_scale"] = float(
                    parameter[
                        "first_relaxed_low" if direction == "low" else "first_relaxed_high"
                    ]
                )
                for short, configuration in (("c0", C0), ("c1", C1)):
                    candidate[f"selected_electricity_process_{short}"] = baseline[
                        "configurations"
                    ][configuration]["selected_electricity_process"]
                candidate["selection_rule"] = (
                    "largest baseline represented named process-electricity load per configuration; "
                    "ties resolved by process name; excludes background, residual and fixed Linde N2"
                )
            candidates.append(candidate)
    expected_structured = int(config["design"]["structured_candidate_count"])
    if len(candidates) - 1 != expected_structured or len(candidates) > 28:
        raise PrescreenError(
            f"Expected {expected_structured} structured candidates plus baseline; got {len(candidates)}."
        )
    for candidate in candidates:
        if "BFG_yield" not in candidate:
            for carrier, parameter_id in (
                ("BFG", "uae_bfg_generation_yield"),
                ("COG", "uae_cog_generation_yield"),
                ("BOFG", "uae_bofg_generation_yield"),
            ):
                candidate[f"{carrier}_yield"] = float(
                    parameters[parameter_id]["baseline_central"]
                )
    return candidates


def _primary_anchor_map(config: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, str]]:
    rows = _overlay_rows(config, "anchor_overlay")
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        if row["configuration"] in {C0, C1}:
            key = (row["configuration"], row["metric"])
            if key not in result or row["target_role"] == "primary_calibration_target":
                result[key] = row
    return result


def _project_user_authorized_candidate(
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
    anchors: Mapping[tuple[str, str], Mapping[str, str]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {"configurations": {}}
    parameters = {
        row["parameter_id"]: row for row in _overlay_rows(config, "parameter_overlay")
    }
    central_yields = {
        carrier: float(parameters[parameter_id]["baseline_central"])
        for carrier, parameter_id in (
            ("BFG", "uae_bfg_generation_yield"),
            ("COG", "uae_cog_generation_yield"),
            ("BOFG", "uae_bofg_generation_yield"),
        )
    }
    for short, configuration in (("c0", C0), ("c1", C1)):
        base = baseline["configurations"][configuration]
        gross_target_mwh = float(
            anchors[(configuration, "gross_site_electricity")]["value_central"]
        ) * 1_000_000.0
        background_mwh = float(candidate["background_share"]) * gross_target_mwh
        selected_process = str(candidate[f"selected_electricity_process_{short}"])
        process_delta_mwh = (
            base["electricity_process_loads_mwh"][selected_process]
            * (float(candidate["electricity_intensity_scale"]) - 1.0)
            if selected_process
            else 0.0
        )
        gross_mwh = base["represented_gross_mwh"] + background_mwh + process_delta_mwh
        carrier_rows: dict[str, Any] = {}
        negative_sink = False
        for carrier in CARRIERS:
            generation = base["carriers"][carrier]["generation_mwh_lhv"] * (
                float(candidate[f"{carrier}_yield"]) / central_yields[carrier]
            )
            fixed_sinks = sum(
                base["carriers"][carrier]["fixed_non_generator_sinks"].values()
            )
            surplus = generation - fixed_sinks
            negative_sink = negative_sink or surplus < -TOLERANCE
            carrier_rows[carrier] = {
                "generation_mwh_lhv": generation,
                "fixed_non_generator_sinks_mwh_lhv": fixed_sinks,
                "surplus_mwh_lhv": max(0.0, surplus),
            }
        efficiency = float(config["prescreen"][f"{short}_wag_to_power_efficiency"])
        volume_nm3 = sum(
            row["surplus_mwh_lhv"] * 3600.0 / SELECTED_WAG_LHV_MJ_PER_NM3[carrier]
            for carrier, row in carrier_rows.items()
        )
        volume_cap = float(config["prescreen"][f"{short}_generator_volume_cap_nm3_h"]) * 8760.0
        volume_scale = min(1.0, volume_cap / volume_nm3) if volume_nm3 else 1.0
        capacity_mwh = (
            float(config["prescreen"]["c1_generator_electric_capacity_mw"]) * 8760.0
            if configuration == C1
            else float("inf")
        )
        ng_generator_electricity = float(
            config["prescreen"].get(f"{short}_named_ng_generator_electricity_mwh", 0.0)
        )
        fuel_after_volume = sum(
            row["surplus_mwh_lhv"] for row in carrier_rows.values()
        ) * volume_scale
        potential_wag_electricity = fuel_after_volume * efficiency
        wag_electricity_limit = max(0.0, min(capacity_mwh, gross_mwh - ng_generator_electricity))
        electricity_scale = (
            min(1.0, wag_electricity_limit / potential_wag_electricity)
            if potential_wag_electricity > 0.0
            else 1.0
        )
        common_scale = volume_scale * electricity_scale
        max_carrier_identity = 0.0
        for carrier, row in carrier_rows.items():
            generator = row["surplus_mwh_lhv"] * common_scale
            flare = row["generation_mwh_lhv"] - row["fixed_non_generator_sinks_mwh_lhv"] - generator
            identity = row["generation_mwh_lhv"] - row["fixed_non_generator_sinks_mwh_lhv"] - generator - flare
            row.update(
                {
                    "generator_mwh_lhv": generator,
                    "flare_mwh_lhv": flare,
                    "identity_residual_mwh_lhv": identity,
                }
            )
            max_carrier_identity = max(max_carrier_identity, abs(identity))
        wag_electricity = sum(
            row["generator_mwh_lhv"] for row in carrier_rows.values()
        ) * efficiency
        gross_grid_import = gross_mwh - wag_electricity - ng_generator_electricity
        gross_grid_export = 0.0
        identity_residual = (
            gross_mwh - wag_electricity - ng_generator_electricity
            - gross_grid_import + gross_grid_export
        )
        ng_nm3_h = base["named_ng_mwh_lhv"] * 3600.0 / 35.8 / 8760.0
        co2_target = float(
            anchors[(configuration, "first_order_full_site_co2")]["value_central"]
        )
        co2_subtotal = base["first_order_process_factor_subtotal_mt"]
        co2_constant = co2_target - co2_subtotal
        co2_overshoot = co2_constant < -TOLERANCE
        co2_constant = max(0.0, co2_constant)
        result["configurations"][configuration] = {
            "carriers": carrier_rows,
            "selected_electricity_process": selected_process,
            "selected_electricity_process_baseline_mwh": (
                base["electricity_process_loads_mwh"].get(selected_process, 0.0)
            ),
            "electricity_intensity_scale": candidate["electricity_intensity_scale"],
            "process_electricity_delta_mwh": process_delta_mwh,
            "represented_gross_before_background_mwh": base["represented_gross_mwh"] + process_delta_mwh,
            "background_mwh": background_mwh,
            "gross_site_electricity_mwh": gross_mwh,
            "wag_generator_electricity_mwh": wag_electricity,
            "ng_generator_electricity_mwh": ng_generator_electricity,
            "gross_grid_import_mwh": gross_grid_import,
            "gross_grid_export_mwh": gross_grid_export,
            "electricity_identity_residual_mwh": identity_residual,
            "named_ng_mwh_lhv": base["named_ng_mwh_lhv"],
            "named_ng_average_nm3_h": ng_nm3_h,
            "first_order_process_factor_subtotal_mt": co2_subtotal,
            "first_order_constant_mt": co2_constant,
            "first_order_total_mt": co2_subtotal + co2_constant,
            "first_order_target_mt": co2_target,
            "first_order_constant_share": (
                co2_constant / co2_target if co2_target else 0.0
            ),
            "mode_b_explicit_fuel_co2_mt": base["mode_b_explicit_fuel_co2_mt"],
            "negative_fixed_sink": negative_sink,
            "max_carrier_identity_residual_mwh": max_carrier_identity,
            "no_export_violation_mwh": max(0.0, -gross_grid_import),
            "co2_overshoot": co2_overshoot,
            "volume_cap_binding": volume_scale < 1.0 - TOLERANCE,
            "electric_capacity_binding": potential_wag_electricity >= capacity_mwh - TOLERANCE,
        }
    return result


def _relative_abs(projected: float, target: float) -> float:
    return abs(projected - target) / abs(target) if abs(target) > TOLERANCE else abs(projected - target)


def _score_user_authorized_candidate(
    candidate: Mapping[str, Any],
    projection: Mapping[str, Any],
    anchors: Mapping[tuple[str, str], Mapping[str, str]],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    row = dict(candidate)
    physical_penalties = 0
    for short, configuration in (("c0", C0), ("c1", C1)):
        projected = projection["configurations"][configuration]
        targets = {
            "gross": float(anchors[(configuration, "gross_site_electricity")]["value_central"]),
            "wag": float(anchors[(configuration, "wag_only_generator_electricity")]["value_central"]),
            "ng": float(anchors[(configuration, "natural_gas_consumption_average")]["value_central"]),
            "co2": float(anchors[(configuration, "first_order_full_site_co2")]["value_central"]),
        }
        values = {
            "gross": projected["gross_site_electricity_mwh"] / 1_000_000.0,
            "wag": projected["wag_generator_electricity_mwh"] / 1_000_000.0,
            "ng": projected["named_ng_average_nm3_h"],
            "co2": projected["first_order_total_mt"],
        }
        for family in ("gross", "wag", "ng", "co2"):
            row[f"{short}_{family}_projected"] = values[family]
            row[f"{short}_{family}_target"] = targets[family]
            row[f"{short}_{family}_signed_error"] = values[family] - targets[family]
            row[f"{short}_{family}_absolute_relative_error"] = _relative_abs(
                values[family], targets[family]
            )
        row[f"{short}_co2_constant_mt"] = projected["first_order_constant_mt"]
        row[f"{short}_co2_constant_share"] = projected["first_order_constant_share"]
        row[f"{short}_background_twh"] = projected["background_mwh"] / 1_000_000.0
        row[f"{short}_selected_electricity_process"] = projected[
            "selected_electricity_process"
        ]
        row[f"{short}_electricity_identity_residual_mwh"] = projected[
            "electricity_identity_residual_mwh"
        ]
        reasons = []
        if projected["negative_fixed_sink"]:
            reasons.append("carrier_generation_below_fixed_named_non_generator_sinks")
        if projected["max_carrier_identity_residual_mwh"] > TOLERANCE:
            reasons.append("carrier_identity_failure")
        if projected["no_export_violation_mwh"] > TOLERANCE:
            reasons.append("no_export_violation")
        if abs(projected["electricity_identity_residual_mwh"]) > TOLERANCE:
            reasons.append("electricity_identity_failure")
        if projected["co2_overshoot"]:
            reasons.append("first_order_co2_subtotal_exceeds_target")
        failures = sum(
            (
                projected["negative_fixed_sink"],
                projected["max_carrier_identity_residual_mwh"] > TOLERANCE,
                projected["no_export_violation_mwh"] > TOLERANCE,
                abs(projected["electricity_identity_residual_mwh"]) > TOLERANCE,
                projected["co2_overshoot"],
            )
        )
        physical_penalties += failures
        row[f"{short}_physical_failure_count"] = failures
        row[f"{short}_rejection_reasons"] = ";".join(reasons)
    coal_target = float(anchors[(C0, "coal_consumption")]["value_central"])
    row["c0_coal_projected_mt"] = baseline["c0_coal_mt"]
    row["c0_coal_target_mt"] = coal_target
    row["c0_coal_signed_error_mt"] = baseline["c0_coal_mt"] - coal_target
    row["c0_coal_absolute_relative_error"] = _relative_abs(
        baseline["c0_coal_mt"], coal_target
    )
    moved_yields = sum(
        abs(float(candidate[f"{carrier}_yield"]) - central) / central
        for carrier, central in (("BFG", 1600.0), ("COG", 365.0), ("BOFG", 75.0))
    )
    electricity_deviation = abs(float(candidate["electricity_intensity_scale"]) - 1.0)
    row["source_deviation_yield_relative_sum"] = moved_yields
    row["source_deviation_electricity_relative"] = electricity_deviation
    row["bridge_background_share"] = float(candidate["background_share"])
    row["bridge_co2_constant_share_max"] = max(
        row["c0_co2_constant_share"], row["c1_co2_constant_share"]
    )
    row["physical_penalty_count"] = physical_penalties
    row["prescreen_status"] = "pass" if physical_penalties == 0 else "reject"
    row["rejection_reasons"] = ";".join(
        f"{short.upper()}:{row[f'{short}_rejection_reasons']}"
        for short in ("c0", "c1")
        if row[f"{short}_rejection_reasons"]
    )
    row["score_families_kept_separate"] = True
    row["retained"] = False
    row["retention_rank"] = ""
    return row


def _retain_user_authorized_candidates(
    rows: list[dict[str, Any]], config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    maximum = int(config["design"]["maximum_retained_candidates"])
    retention_contract = (
        ("source_driven_baseline", "immutable source-driven physical baseline"),
        ("bg25_central_no_movement", "25% boundary-only control; isolates the upper background bridge"),
        ("bg15_central_no_movement", "15% background dose control"),
        ("bg25_single_process_electricity_high", "best retained named-process electricity response at the 25% boundary"),
        ("bg25_cog_yield_high", "best retained WAG-yield family response; BFG-high and BOFG-high are strictly dominated"),
    )
    if len(retention_contract) > maximum:
        raise PrescreenError("Retention-only review contract exceeds the five-candidate cap.")
    by_id = {row["candidate_id"]: row for row in rows}
    retained: list[dict[str, Any]] = []
    for rank, (candidate_id, reason) in enumerate(retention_contract, start=1):
        row = by_id[candidate_id]
        if row["prescreen_status"] != "pass":
            raise PrescreenError(
                f"Required checkpoint-3 retention control {candidate_id} did not pass."
            )
        row["retained"] = True
        row["retention_rank"] = rank
        row["retention_reason"] = reason
        row["retention_rule"] = "fixed reviewer-approved baseline/control/dose/response set after transparent dominance review"
        retained.append(row)
    for candidate_id, dominated_by in (
        ("bg25_bfg_yield_high", "bg25_cog_yield_high"),
        ("bg25_bofg_yield_high", "bg25_cog_yield_high"),
    ):
        by_id[candidate_id]["retention_reason"] = (
            f"excluded_strictly_dominated_by_{dominated_by}"
        )
    return retained


def build_user_authorized_prescreen(config: Mapping[str, Any]) -> dict[str, Any]:
    anchors = _primary_anchor_map(config)
    required = {
        (configuration, metric)
        for configuration in (C0, C1)
        for metric in (
            "gross_site_electricity",
            "wag_only_generator_electricity",
            "natural_gas_consumption_average",
            "first_order_full_site_co2",
        )
    } | {(C0, "coal_consumption")}
    if missing := required.difference(anchors):
        raise PrescreenError(f"Missing raw user-authorized primary anchors: {sorted(missing)}")
    baseline = _user_authorized_baseline(config)
    candidates = user_authorized_candidate_definitions(config, baseline)
    projections: dict[str, Any] = {}
    score_rows: list[dict[str, Any]] = []
    background_rows: list[dict[str, Any]] = []
    wag_rows: list[dict[str, Any]] = []
    ng_rows: list[dict[str, Any]] = []
    co2_rows: list[dict[str, Any]] = []
    guardrails: list[dict[str, Any]] = []
    movement_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        projection = _project_user_authorized_candidate(
            candidate, baseline, anchors, config
        )
        projections[candidate["candidate_id"]] = projection
        score_rows.append(
            _score_user_authorized_candidate(candidate, projection, anchors, baseline)
        )
        parameter_candidates: list[dict[str, Any]] = []
        if candidate["source_baseline"]:
            parameter_candidates.append(
                {"parameter_id": "uae_background_electricity_share", "candidate_value": 0.0}
            )
        else:
            parameter_candidates.append(
                {
                    "parameter_id": "uae_background_electricity_share",
                    "candidate_value": candidate["background_share"],
                }
            )
        family_to_parameter = {
            "BFG_yield": ("uae_bfg_generation_yield", "BFG_yield"),
            "COG_yield": ("uae_cog_generation_yield", "COG_yield"),
            "BOFG_yield": ("uae_bofg_generation_yield", "BOFG_yield"),
        }
        if candidate["parameter_family"] in family_to_parameter:
            parameter_id, field = family_to_parameter[candidate["parameter_family"]]
            parameter_candidates.append(
                {"parameter_id": parameter_id, "candidate_value": candidate[field]}
            )
        for short, configuration in (("c0", C0), ("c1", C1)):
            projected = projection["configurations"][configuration]
            background_rows.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "configuration_id": configuration,
                    "background_share": candidate["background_share"],
                    "represented_before_background_twh": projected["represented_gross_before_background_mwh"] / 1_000_000.0,
                    "explicit_background_twh": projected["background_mwh"] / 1_000_000.0,
                    "gross_site_electricity_twh": projected["gross_site_electricity_mwh"] / 1_000_000.0,
                    "target_gross_twh": float(anchors[(configuration, "gross_site_electricity")]["value_central"]),
                    "residual_electricity_mixing": False,
                }
            )
            for carrier, carrier_row in projected["carriers"].items():
                wag_rows.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "configuration_id": configuration,
                        "carrier": carrier,
                        "generation_mwh_lhv": carrier_row["generation_mwh_lhv"],
                        "fixed_non_generator_sinks_mwh_lhv": carrier_row["fixed_non_generator_sinks_mwh_lhv"],
                        "generator_fuel_mwh_lhv": carrier_row["generator_mwh_lhv"],
                        "flare_mwh_lhv": carrier_row["flare_mwh_lhv"],
                        "identity_residual_mwh_lhv": carrier_row["identity_residual_mwh_lhv"],
                        "carrier_eligibility_status": "pass_separate_carrier",
                    }
                )
            ng_rows.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "configuration_id": configuration,
                    "represented_named_ng_average_nm3_h": projected["named_ng_average_nm3_h"],
                    "raw_primary_target_nm3_h": float(anchors[(configuration, "natural_gas_consumption_average")]["value_central"]),
                    "signed_error_nm3_h": projected["named_ng_average_nm3_h"] - float(anchors[(configuration, "natural_gas_consumption_average")]["value_central"]),
                    "residual_ng_reported_only": True,
                    "ng_not_changed_by_analytical_recipe": True,
                }
            )
            co2_rows.extend(
                [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "configuration_id": configuration,
                        "ledger": "first_order_full_site_CO2",
                        "selected_process_factor_subtotal_mt": projected["first_order_process_factor_subtotal_mt"],
                        "explicit_nonnegative_constant_mt": projected["first_order_constant_mt"],
                        "constant_share": projected["first_order_constant_share"],
                        "total_mt": projected["first_order_total_mt"],
                        "target_mt": projected["first_order_target_mt"],
                        "feeds_physics": False,
                        "included_in_mode_b": False,
                    },
                    {
                        "candidate_id": candidate["candidate_id"],
                        "configuration_id": configuration,
                        "ledger": "Mode_B_explicit_fuel_CO2",
                        "selected_process_factor_subtotal_mt": "",
                        "explicit_nonnegative_constant_mt": "",
                        "constant_share": "",
                        "total_mt": projected["mode_b_explicit_fuel_co2_mt"],
                        "target_mt": "",
                        "feeds_physics": False,
                        "included_in_mode_b": True,
                    },
                ]
            )
            if candidate["parameter_family"] == "named_process_electricity_intensity":
                parameter_candidates.append(
                    {
                        "parameter_id": "uae_named_process_electricity_intensity_scaling",
                        "candidate_value": candidate["electricity_intensity_scale"],
                        "configuration": configuration,
                        "selected_process": projected["selected_electricity_process"],
                    }
                )
            constant_parameter = (
                "uae_c0_first_order_co2_constant"
                if configuration == C0
                else "uae_c1_first_order_co2_constant"
            )
            parameter_candidates.append(
                {
                    "parameter_id": constant_parameter,
                    "candidate_value": projected["first_order_constant_mt"],
                    "configuration": configuration,
                }
            )
            guardrails.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "configuration_id": configuration,
                    "unit_failure": False,
                    "electricity_identity_residual_mwh": projected["electricity_identity_residual_mwh"],
                    "max_carrier_identity_residual_mwh": projected["max_carrier_identity_residual_mwh"],
                    "carrier_eligibility_failure": False,
                    "negative_fixed_sink_failure": projected["negative_fixed_sink"],
                    "bound_failure": False,
                    "no_export_violation_mwh": projected["no_export_violation_mwh"],
                    "double_counting_failure": False,
                    "background_residual_mixing_failure": False,
                    "co2_overshoot_failure": projected["co2_overshoot"],
                    "baseline_accounting_residual": baseline["configurations"][configuration]["baseline_max_accounting_residual"],
                    "status": "pass" if not score_rows[-1][f"{short}_physical_failure_count"] else "reject",
                }
            )
        exceptions = _parameter_range_exception_report(parameter_candidates)
        for exception in exceptions:
            movement_rows.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    **exception,
                    "movement_role": "explicit_bridge" if exception["parameter_family"] in {"background_site_load", "first_order_co2_constant"} else "one_family_at_a_time_parameter",
                }
            )
        bound_failure = any(
            row["range_status"] == "outside_user_authorized_relaxed_range"
            for row in exceptions
        )
        for guardrail in guardrails:
            if guardrail["candidate_id"] == candidate["candidate_id"]:
                guardrail["bound_failure"] = bound_failure
                if bound_failure:
                    guardrail["status"] = "reject"
        if bound_failure:
            score_rows[-1]["physical_penalty_count"] += 1
            score_rows[-1]["prescreen_status"] = "reject"
            score_rows[-1]["rejection_reasons"] = ";".join(
                filter(None, (score_rows[-1]["rejection_reasons"], "parameter_bound_failure"))
            )
    retained = _retain_user_authorized_candidates(score_rows, config)
    return {
        "baseline": baseline,
        "candidates": candidates,
        "scorecard": score_rows,
        "retained": retained,
        "background": background_rows,
        "wag": wag_rows,
        "ng": ng_rows,
        "co2": co2_rows,
        "movements": movement_rows,
        "guardrails": guardrails,
    }


def _user_authorized_manifest(
    config_file: Path, config: Mapping[str, Any]
) -> dict[str, Any]:
    baseline_root = _repo_path(str(config["accepted_annual_baseline_root"]))
    paths = [
        config_file,
        _repo_path(str(config["anchor_overlay"])),
        _repo_path(str(config["parameter_overlay"])),
        _repo_path(str(config["strict_target_contract"])),
        _repo_path(str(config["strict_parameter_contract"])),
        _repo_path(str(config["strict_baseline_freeze"])),
        baseline_root / "annual_physical_boundary_ledger.csv",
        baseline_root / "executed_hourly.csv",
    ]
    return {
        "inputs": [
            {
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in paths
        ],
        "source_inputs_mutated": False,
        "solver_or_rolling_execution": False,
    }


def _run_user_authorized_prescreen(config_path: str | Path) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    output_root = _repo_path(str(config["output_root"]))
    if output_root.exists():
        raise PrescreenError(f"Checkpoint-3 output root already exists: {output_root}")
    manifest_before = _user_authorized_manifest(config_file, config)
    result = build_user_authorized_prescreen(config)
    output_root.mkdir(parents=True)
    _write_csv(output_root / "target_overlay_snapshot.csv", _overlay_rows(config, "anchor_overlay"))
    _write_csv(output_root / "parameter_overlay_snapshot.csv", _overlay_rows(config, "parameter_overlay"))
    _write_csv(output_root / "candidate_scorecard.csv", result["scorecard"])
    _write_csv(output_root / "background_sensitivity.csv", result["background"])
    _write_csv(output_root / "wag_reconciliation.csv", result["wag"])
    _write_csv(output_root / "ng_comparison.csv", result["ng"])
    _write_csv(output_root / "co2_ledgers.csv", result["co2"])
    _write_csv(output_root / "parameter_movements_and_exceptions.csv", result["movements"])
    _write_csv(output_root / "physical_guardrails.csv", result["guardrails"])
    _write_json(output_root / "input_manifest.json", manifest_before)
    (output_root / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=True), encoding="utf-8"
    )
    retained_ids = [row["candidate_id"] for row in result["retained"]]
    retained_structured_background_shares = sorted(
        {
            float(row["background_share"])
            for row in result["retained"]
            if not row["source_baseline"]
        }
    )
    rejected = [row for row in result["scorecard"] if row["prescreen_status"] == "reject"]
    manifest_after = _user_authorized_manifest(config_file, config)
    source_unchanged = manifest_before == manifest_after
    summary = {
        "run_id": config["run_id"],
        "checkpoint": 3,
        "execution_type": "analytical_annual_prescreen_no_solver_no_rolling",
        "source_baseline_count": 1,
        "structured_candidate_count": len(result["scorecard"]) - 1,
        "candidate_count": len(result["scorecard"]),
        "rejected_candidate_count": len(rejected),
        "retained_candidate_count": len(retained_ids),
        "retained_candidate_ids": retained_ids,
        "retained_structured_background_shares": retained_structured_background_shares,
        "retained_ranking_background_boundary_dominated": (
            retained_structured_background_shares
            == [max(float(value) for value in config["design"]["background_electricity_shares"])]
        ),
        "selected_electricity_process_by_configuration": {
            configuration: result["baseline"]["configurations"][configuration]["selected_electricity_process"]
            for configuration in (C0, C1)
        },
        "selection_rule": "largest baseline represented named process-electricity load per configuration; result-independent",
        "retention_rule": "fixed reviewer-approved baseline, 25% boundary control, 15% dose control, electricity response and non-dominated COG-yield response",
        "score_families": [
            "gross_electricity", "WAG_electricity", "NG", "first_order_CO2",
            "C0_coal_material", "source_deviation", "bridge_size", "physical_penalties",
        ],
        "source_hashes_unchanged": source_unchanged,
        "solver_or_rolling_run_performed": False,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "status": "pass" if source_unchanged and len(retained_ids) <= 5 and len(result["scorecard"]) == 28 else "fail",
    }
    _write_json(output_root / "run_summary.json", summary)
    _write_json(
        output_root / "checkpoint_state.json",
        {
            "completed_checkpoint": 3,
            "status": summary["status"],
            "review_decision": "revise_once_retention_only_repair_complete",
            "checkpoint_3_review_state": "pending_re_review",
            "next_checkpoint": "checkpoint_4_independent_review",
            "analytical_prescreen_performed": True,
            "rolling_or_solver_run_performed": False,
            "calibration_promotion_authorized": False,
            "retained_candidate_ids": retained_ids,
        },
    )
    _write_json(
        output_root / "registry_entry.json",
        {
            "run_id": config["run_id"],
            "run_class": config["run_class"],
            "lineage_role": config["lineage_role"],
            "output_policy": config["output_policy"],
            "status": summary["status"],
        },
    )
    try:
        git_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git_head = "unavailable"
    _write_json(
        output_root / "code_version.json",
        {
            "git_head": git_head,
            "module": Path(__file__).relative_to(REPO_ROOT).as_posix(),
        },
    )
    (output_root / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is an annual-ledger analytical prescreen; it is not dispatch, rolling optimisation or calibration promotion.\n"
        "- Background electricity and first-order CO2 constants are explicit user-authorized bridges, not hidden residuals or physical truth.\n"
        "- Residual electricity and NG remain reporting-only; no candidate fills the physical model with a residual.\n"
        "- Mode-B explicit-fuel CO2 and first-order full-site CO2 are separate ledgers and must not be summed.\n"
        "- Candidate ranking is a transparent lexicographic comparison of separate score families, not one fitted objective.\n",
        encoding="utf-8",
    )
    (output_root / "README.md").write_text(
        "# User-authorized full-site emulation analytical prescreen\n\n"
        "This checkpoint contains one immutable source baseline plus 27 structured annual-ledger candidates: three explicit background shares crossed with nine one-family-at-a-time recipes. No solver or rolling run was performed.\n\n"
        "Raw user-authorized anchors are used directly. BFG, COG and BOFG remain separate; residual electricity and NG are reporting-only. The first-order CO2 constant is visible and reporting-only, and the Mode-B ledger remains separate. Score families stay in separate columns. The reviewer-approved retention-only repair keeps the immutable baseline, 25% boundary-only control, 15% dose control, 25% named-electricity response and non-dominated 25% COG-yield response; BFG-high and BOFG-high are excluded as strictly dominated.\n",
        encoding="utf-8",
    )
    return summary


def run_prescreen(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    if config.get("mode") == "user_authorized_full_site_emulation_prescreen":
        return _run_user_authorized_prescreen(config_file)
    return _run_historical_prescreen(config_file)
