"""Phase 5G validation-selected baseload integration and final C5 freeze gate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
    HOURS_PER_YEAR,
    PJ_PER_MWH,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_phase4_terminal_inventory_equivalence import (
    _artifact,
    _case_overrides,
    check_phase4_config,
    load_phase4_config,
)
from .s4_4c5p_phase5b_c0_export_sensitivity import (
    _git_head,
    _read_csv,
    _read_json,
    _resolve,
    _select_solver,
    _sha256,
    install_terminal_validation_extension,
)
from .s4_4c5p_phase5e_source_backed_anchor_closure import load_source_contract
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_c5_phase5g_final_deterministic_freeze_v1_20260728"
CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase5g_final_deterministic_freeze.yaml"
)
CONFIGURATIONS = (C0_CONFIGURATION, C1_CONFIGURATION)
SHORT_CONFIGURATION = {C0_CONFIGURATION: "C0", C1_CONFIGURATION: "C1"}
BUILDER_CONFIGURATION = {value: key for key, value in SHORT_CONFIGURATION.items()}
CARRIERS = ("electricity", "natural_gas")


class Phase5GFreezeError(RuntimeError):
    pass


def _portable(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise Phase5GFreezeError(f"Persistent path must be repository-relative: {path}") from exc


def _float(row: Mapping[str, Any], field: str) -> float:
    return float(row.get(field) or 0.0)


def _sum(rows: Iterable[Mapping[str, Any]], field: str) -> float:
    return sum(_float(row, field) for row in rows)


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fields: list[str] = []
    for row in materialized:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)


def load_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload.get("run_id") != RUN_ID or payload.get("output_policy") != "minimal":
        raise Phase5GFreezeError("Phase-5G identity or output policy changed.")
    phase = payload.get("phase5g")
    if not isinstance(phase, Mapping):
        raise Phase5GFreezeError("Phase-5G config section is missing.")
    if int(phase.get("hours_per_year", 0)) != 8760:
        raise Phase5GFreezeError("Phase-5G requires an 8,760-hour annual basis.")
    grid = tuple(float(value) for value in phase.get("percentage_grid", ()))
    if grid != tuple(index / 10.0 for index in range(1, 10)):
        raise Phase5GFreezeError("Phase-5G percentage grid must be 10%-90%.")
    validation = list(phase.get("validation_periods", ()))
    held_out = list(phase.get("held_out_periods", ()))
    expected = int(phase.get("expected_periods_per_split", -1))
    if len(validation) != expected or len(held_out) != expected:
        raise Phase5GFreezeError("Phase-5G requires four frozen periods per split.")
    for split, periods in (("validation", validation), ("test", held_out)):
        if any(row.get("dataset_split") != split for row in periods):
            raise Phase5GFreezeError(f"Phase-5G {split} period labels changed.")
        if not math.isclose(
            sum(float(row["split_weight"]) for row in periods), 1.0, abs_tol=2e-12
        ):
            raise Phase5GFreezeError(f"Phase-5G {split} weights must sum to one.")
        if any(int(row.get("terminal_executed_hours", 0)) not in {168, 169} for row in periods):
            raise Phase5GFreezeError(
                f"Phase-5G {split} periods require seven complete local delivery days."
            )
    policy = phase.get("policy", {})
    forbidden_true = (
        "legacy_c0_fixed_bridge_active",
        "legacy_c0_flexible_heat_bridge_active",
        "external_export_allowed",
        "residual_dispatch_allowed",
        "annual_values_used_as_hourly_constraints",
        "baseload_observed_hourly_profile",
        "baseload_price_responsive",
        "wag_substitution_for_ng_baseload",
        "held_out_reselection_allowed",
        "market_bidding_allowed",
        "stochasticity_or_cvar_allowed",
    )
    if any(bool(policy.get(key)) for key in forbidden_true):
        raise Phase5GFreezeError("Phase-5G scope or baseload policy changed.")
    if not bool(policy.get("baseload_shared_carrier_percentage_across_configurations")):
        raise Phase5GFreezeError("Each carrier share must be shared across C0/C1.")
    return payload


def load_overlap_contract(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_csv(Path(path))
    required = {
        "mapping_id", "source_record_id", "configuration", "carrier",
        "source_component", "source_value_pj_y", "dynamic_overlap_fields",
        "baseload_eligible", "overlap_classification", "source_id",
        "source_locator", "original_unit", "activity_basis", "energy_basis",
        "time_basis", "model_field_nonoverlap_rule",
    }
    if not rows or required.difference(rows[0]):
        raise Phase5GFreezeError("Phase-5G overlap contract schema is incomplete.")
    seen_ids: set[str] = set()
    seen_source: set[str] = set()
    seen_fields: set[tuple[str, str, str]] = set()
    for row in rows:
        mapping_id = row["mapping_id"]
        if not mapping_id or mapping_id in seen_ids:
            raise Phase5GFreezeError(f"Duplicate or empty overlap mapping: {mapping_id}")
        seen_ids.add(mapping_id)
        source_key = row["source_record_id"]
        if source_key in seen_source:
            raise Phase5GFreezeError(f"Source component mapped more than once: {source_key}")
        seen_source.add(source_key)
        if row["configuration"] not in {"C0", "C1"} or row["carrier"] not in CARRIERS:
            raise Phase5GFreezeError(f"Unsupported overlap row: {mapping_id}")
        if row["source_id"] != "STEEL-SC-0017" or not row["source_locator"].strip():
            raise Phase5GFreezeError(f"Canonical source identity/locator missing: {mapping_id}")
        if row["original_unit"] != "PJ/y" or row["time_basis"] != "annual":
            raise Phase5GFreezeError(f"Units/time basis changed: {mapping_id}")
        eligible = row["baseload_eligible"].lower() == "true"
        if row["overlap_classification"] == "boundary_remainder_ineligible" and eligible:
            raise Phase5GFreezeError(f"Boundary remainder became eligible: {mapping_id}")
        row["baseload_eligible"] = eligible
        row["source_value_pj_y"] = float(row["source_value_pj_y"])
        row["dynamic_overlap_fields"] = tuple(
            field for field in row["dynamic_overlap_fields"].split(";") if field
        )
        for field in row["dynamic_overlap_fields"]:
            field_key = (row["configuration"], row["carrier"], field)
            if field_key in seen_fields:
                raise Phase5GFreezeError(f"Model field mapped more than once: {field_key}")
            seen_fields.add(field_key)
    return rows


def validate_overlap_against_source(
    overlap_rows: Iterable[Mapping[str, Any]], source_rows: Iterable[Mapping[str, Any]]
) -> None:
    source = {
        str(row["record_id"]): row
        for row in source_rows
        if row["family"] in CARRIERS
        and row["record_kind"] in {"component", "boundary_component"}
    }
    overlap = {str(row["source_record_id"]): row for row in overlap_rows}
    if set(overlap) != set(source):
        raise Phase5GFreezeError("Overlap contract must map every Phase-5E NG/electricity component once.")
    for record_id, mapped in overlap.items():
        original = source[record_id]
        expected = (
            str(original["configuration"]), str(original["family"]),
            str(original["component"]), float(original["value"]),
        )
        actual = (
            str(mapped["configuration"]), str(mapped["carrier"]),
            str(mapped["source_component"]), float(mapped["source_value_pj_y"]),
        )
        if actual != expected:
            raise Phase5GFreezeError(f"Overlap/source mismatch for {record_id}.")


def candidate_percentages() -> tuple[float, ...]:
    return tuple(index / 10.0 for index in range(1, 10))


def planned_outage_availability_context() -> dict[str, tuple[float, float]]:
    """Return HERACLES annual context, never representative-week calendars."""

    dri_monthly_hours = 12.0 * 24.0
    dri_annual_hours = 21.0 * 24.0
    eaf_weekly_hours = 52.0 * 8.0
    eaf_annual_hours = 14.0 * 24.0
    return {
        "DRI": (
            1.0 - (dri_monthly_hours + dri_annual_hours) / HOURS_PER_YEAR,
            1.0 - max(dri_monthly_hours, dri_annual_hours) / HOURS_PER_YEAR,
        ),
        "EAF": (
            1.0 - (eaf_weekly_hours + eaf_annual_hours) / HOURS_PER_YEAR,
            1.0 - max(eaf_weekly_hours, eaf_annual_hours) / HOURS_PER_YEAR,
        ),
    }


def _configuration_rows(artifact: Mapping[str, Any], short: str) -> list[dict[str, Any]]:
    configuration = BUILDER_CONFIGURATION[short]
    rows = [
        row for row in artifact["hourly"]
        if row.get("configuration_id") == configuration
    ]
    if len(rows) not in {168, 169}:
        raise Phase5GFreezeError(
            f"Expected seven complete local delivery days for {short}, got {len(rows)} hours."
        )
    return rows


def weighted_annual_equivalent_pj(
    artifacts: Mapping[str, Mapping[str, Any]],
    periods: Iterable[Mapping[str, Any]],
    configuration: str,
    fields: Iterable[str],
) -> float:
    fields = tuple(fields)
    return sum(
        float(period["split_weight"])
        * _sum(_configuration_rows(artifacts[str(period["period_id"])], configuration), field)
        * HOURS_PER_YEAR
        / float(len(_configuration_rows(artifacts[str(period["period_id"])], configuration)))
        * PJ_PER_MWH
        for period in periods
        for field in fields
    )


def source_service_pools(
    artifacts: Mapping[str, Mapping[str, Any]],
    periods: Iterable[Mapping[str, Any]],
    overlap_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in overlap_rows:
        mapped = weighted_annual_equivalent_pj(
            artifacts, periods, str(row["configuration"]), row["dynamic_overlap_fields"]
        ) if row["dynamic_overlap_fields"] else 0.0
        unmodelled = max(0.0, float(row["source_value_pj_y"]) - mapped)
        eligible_value = unmodelled if bool(row["baseload_eligible"]) else 0.0
        results.append(
            {
                "mapping_id": row["mapping_id"],
                "source_record_id": row["source_record_id"],
                "configuration": row["configuration"],
                "carrier": row["carrier"],
                "source_component": row["source_component"],
                "source_value_pj_y": row["source_value_pj_y"],
                "mapped_explicit_model_pj_y": mapped,
                "unmodelled_component_pj_y": unmodelled,
                "eligible_service_pool_pj_y": eligible_value,
                "baseload_eligible": row["baseload_eligible"],
                "overlap_classification": row["overlap_classification"],
                "dynamic_overlap_fields": ";".join(row["dynamic_overlap_fields"]),
                "source_id": row["source_id"],
                "source_locator": row["source_locator"],
            }
        )
    return results


def _pool_totals(pool_rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], float]:
    totals = {(configuration, carrier): 0.0 for configuration in ("C0", "C1") for carrier in CARRIERS}
    for row in pool_rows:
        totals[(str(row["configuration"]), str(row["carrier"]))] += float(
            row["eligible_service_pool_pj_y"]
        )
    return totals


def _primary_anchors(source_rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], float]:
    anchors = {
        (str(row["configuration"]), str(row["family"])): float(row["value"])
        for row in source_rows
        if row["family"] in CARRIERS and row["record_kind"] == "primary_total"
    }
    if set(anchors) != {(configuration, carrier) for configuration in ("C0", "C1") for carrier in CARRIERS}:
        raise Phase5GFreezeError("Exactly one C0/C1 primary anchor is required per carrier.")
    return anchors


def explicit_baseline_totals(
    artifacts: Mapping[str, Mapping[str, Any]], periods: Iterable[Mapping[str, Any]]
) -> dict[tuple[str, str], float]:
    periods = tuple(periods)
    return {
        (configuration, carrier): weighted_annual_equivalent_pj(
            artifacts,
            periods,
            configuration,
            (
                "represented_gross_electricity_before_background_mwh"
                if carrier == "electricity" else "total_named_ng_procurement_mwh",
            ),
        )
        for configuration in ("C0", "C1")
        for carrier in CARRIERS
    }


def select_shared_percentages(
    explicit_totals: Mapping[tuple[str, str], float],
    pool_totals: Mapping[tuple[str, str], float],
    anchors: Mapping[tuple[str, str], float],
    grid: Iterable[float] = candidate_percentages(),
    tolerance: float = 1e-12,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    selections: dict[str, float] = {}
    score_rows: list[dict[str, Any]] = []
    for carrier in CARRIERS:
        baseline_errors = {
            configuration: abs(
                explicit_totals[(configuration, carrier)]
                / anchors[(configuration, carrier)] - 1.0
            )
            for configuration in ("C0", "C1")
        }
        carrier_rows: list[dict[str, Any]] = []
        for alpha in (0.0, *tuple(grid), 1.0):
            errors = {
                configuration: abs(
                    (explicit_totals[(configuration, carrier)]
                     + alpha * pool_totals[(configuration, carrier)])
                    / anchors[(configuration, carrier)] - 1.0
                )
                for configuration in ("C0", "C1")
            }
            eligible = (
                0.0 < alpha < 1.0
                and all(errors[c] < baseline_errors[c] - tolerance for c in ("C0", "C1"))
            )
            carrier_rows.append(
                {
                    "carrier": carrier,
                    "candidate_share": alpha,
                    "candidate_role": (
                        "explicit_model_benchmark" if alpha == 0.0
                        else "source_account_context_only" if alpha == 1.0
                        else "eligible_grid_candidate"
                    ),
                    "eligible_after_both_configuration_improvement_gate": eligible,
                    "C0_predicted_pj_y": explicit_totals[("C0", carrier)] + alpha * pool_totals[("C0", carrier)],
                    "C1_predicted_pj_y": explicit_totals[("C1", carrier)] + alpha * pool_totals[("C1", carrier)],
                    "C0_absolute_relative_error": errors["C0"],
                    "C1_absolute_relative_error": errors["C1"],
                    "maximum_absolute_relative_error": max(errors.values()),
                    "mean_absolute_relative_error": sum(errors.values()) / 2.0,
                }
            )
        eligible_rows = [row for row in carrier_rows if row["eligible_after_both_configuration_improvement_gate"]]
        if not eligible_rows:
            raise Phase5GFreezeError(
                f"No nonzero {carrier} share improves both C0 and C1 over the explicit baseline."
            )
        selected = min(
            eligible_rows,
            key=lambda row: (
                float(row["maximum_absolute_relative_error"]),
                float(row["mean_absolute_relative_error"]),
                float(row["candidate_share"]),
            ),
        )
        selections[carrier] = float(selected["candidate_share"])
        for row in carrier_rows:
            row["selected"] = math.isclose(
                float(row["candidate_share"]), selections[carrier], abs_tol=tolerance
            )
        score_rows.extend(carrier_rows)
    return selections, score_rows


def selected_contract_rows(
    selections: Mapping[str, float], pool_totals: Mapping[tuple[str, str], float]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for carrier in CARRIERS:
        for configuration in ("C0", "C1"):
            alpha = float(selections[carrier])
            pool = float(pool_totals[(configuration, carrier)])
            annual = alpha * pool
            rows.append(
                {
                    "contract_id": f"P5G-{configuration}-{'EL' if carrier == 'electricity' else 'NG'}",
                    "configuration": configuration,
                    "carrier": carrier,
                    "selected_share": alpha,
                    "source_service_pool_pj_y": pool,
                    "hourly_baseload_mwh_h": annual / (HOURS_PER_YEAR * PJ_PER_MWH),
                    "annual_baseload_pj_y": annual,
                    "selection_status": "selected_validation_frozen",
                    "source_id": "STEEL-SC-0017",
                    "unit": "MWh_e/h" if carrier == "electricity" else "MWh_LHV/h",
                    "activity_basis": "source-backed unmodelled service",
                    "energy_basis": "electricity" if carrier == "electricity" else "LHV",
                    "time_basis": "constant 8760-hour basis",
                    "observed_profile": "false",
                    "price_responsive": "false",
                    "notes": (
                        "Validation-selected shared carrier percentage; constant configuration-specific load."
                        if carrier == "electricity"
                        else "Validation-selected shared carrier percentage; NG-only and not HSM/WAG-displaceable."
                    ),
                }
            )
    return rows


def load_selected_contract(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_csv(Path(path))
    required = {
        "contract_id", "configuration", "carrier", "selected_share",
        "source_service_pool_pj_y", "hourly_baseload_mwh_h",
        "annual_baseload_pj_y", "selection_status", "source_id", "unit",
        "activity_basis", "energy_basis", "time_basis", "observed_profile",
        "price_responsive",
    }
    if len(rows) != 4 or required.difference(rows[0]):
        raise Phase5GFreezeError("Selected baseload contract must contain four complete rows.")
    for row in rows:
        for field in (
            "selected_share", "source_service_pool_pj_y", "hourly_baseload_mwh_h",
            "annual_baseload_pj_y",
        ):
            row[field] = float(row[field])
    return rows


def validate_selected_contract(
    actual: Iterable[Mapping[str, Any]], expected: Iterable[Mapping[str, Any]], tolerance: float
) -> None:
    actual_by_id = {str(row["contract_id"]): row for row in actual}
    expected_by_id = {str(row["contract_id"]): row for row in expected}
    if set(actual_by_id) != set(expected_by_id):
        raise Phase5GFreezeError("Selected baseload contract row identity changed.")
    for contract_id, expected_row in expected_by_id.items():
        row = actual_by_id[contract_id]
        if row["selection_status"] not in {
            "selected_validation_frozen",
            "selected_validation_failed_not_promoted",
        }:
            raise Phase5GFreezeError("Selected baseload contract status is not governed.")
        if row["source_id"] != "STEEL-SC-0017" or row["observed_profile"] != "false" or row["price_responsive"] != "false":
            raise Phase5GFreezeError(f"Selected baseload classification changed: {contract_id}")
        for field in (
            "selected_share", "source_service_pool_pj_y", "hourly_baseload_mwh_h",
            "annual_baseload_pj_y",
        ):
            if not math.isclose(float(row[field]), float(expected_row[field]), abs_tol=tolerance):
                raise Phase5GFreezeError(f"Selected baseload {field} mismatch: {contract_id}")
        annual = float(row["hourly_baseload_mwh_h"]) * HOURS_PER_YEAR * PJ_PER_MWH
        if not math.isclose(annual, float(row["annual_baseload_pj_y"]), abs_tol=tolerance):
            raise Phase5GFreezeError(f"Selected baseload annual identity failed: {contract_id}")
    for carrier in CARRIERS:
        shares = {float(row["selected_share"]) for row in actual_by_id.values() if row["carrier"] == carrier}
        if len(shares) != 1 or next(iter(shares)) not in candidate_percentages():
            raise Phase5GFreezeError(f"{carrier} share must be one shared eligible grid value.")


def _baseload_maps(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, float], dict[str, float]]:
    electricity: dict[str, float] = {}
    ng: dict[str, float] = {}
    for row in rows:
        target = electricity if row["carrier"] == "electricity" else ng
        target[BUILDER_CONFIGURATION[str(row["configuration"])]] = float(row["hourly_baseload_mwh_h"])
    return electricity, ng


def _run_case(
    *, stage: str, phase: Mapping[str, Any], parent: Mapping[str, Any],
    phase4: Mapping[str, Any], terminal_target: Mapping[str, Any],
    period: Mapping[str, Any], electricity: Mapping[str, float], ng: Mapping[str, float],
    extra_overrides: Mapping[str, Any] | None = None,
) -> tuple[str, Mapping[str, Any]]:
    case_id = f"phase5g__{stage}__{str(period['period_id']).replace('-', '_')}"
    case = {
        "case_id": case_id,
        "period_id": period["period_id"],
        "dataset_split": period["dataset_split"],
        "forecast_start_origin_utc": period["frozen_forecast_start_origin_utc"],
        "flat_price_eur_per_mwh": None,
        "price_field": "y_pred",
        "perfect_foresight_oracle": False,
    }
    overrides = _case_overrides(
        phase4, case, _resolve(parent["phase5b"]["forecast_run_root"]),
        int(period["terminal_executed_hours"]),
        terminal_target["terminal_band"],
    )
    overrides.update(
        {
            "run_id": case_id,
            "lineage_role": f"phase5g_{stage}_terminal_aware_child",
            "site_background_electricity_mwh_h": 0.0,
            "site_background_electricity_mwh_h_by_configuration": dict(electricity),
            "site_baseload_ng_mwh_h_by_configuration": dict(ng),
            "c0_full_site_energy_bridge": None,
            "phase5g_generator_without_legacy_bridge": True,
            "hsm_source_mix_policy_by_configuration": {
                key: dict(value)
                for key, value in phase["hsm_source_mix_policy_by_configuration"].items()
            },
            "phase5g_stage": stage,
            "phase5g_residual_dispatch_allowed": False,
            "phase5g_baseload_price_responsive": False,
        }
    )
    if extra_overrides:
        overrides.update(dict(extra_overrides))
    scratch = _resolve(phase["scratch_root"])
    directory = scratch / case_id
    if not directory.exists():
        run_closed_loop_feasibility_anchor_reconciliation(
            config_path=_resolve(phase4["phase4"]["physical_config"]),
            output_root=scratch,
            scenario_overrides=overrides,
        )
    return case_id, _artifact(directory)


def _stage_artifacts(
    stage: str, periods: Iterable[Mapping[str, Any]], phase: Mapping[str, Any],
    parent: Mapping[str, Any], phase4: Mapping[str, Any],
    terminal_target: Mapping[str, Any], electricity: Mapping[str, float], ng: Mapping[str, float],
    extra_overrides: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Mapping[str, Any]], list[dict[str, Any]]]:
    artifacts: dict[str, Mapping[str, Any]] = {}
    status: list[dict[str, Any]] = []
    for period in periods:
        case_id, artifact = _run_case(
            stage=stage, phase=phase, parent=parent, phase4=phase4,
            terminal_target=terminal_target, period=period,
            electricity=electricity, ng=ng,
            extra_overrides=extra_overrides,
        )
        period_id = str(period["period_id"])
        artifacts[period_id] = artifact
        optimal = len(artifact["models"]) == 14 and all(
            str(row.get("solver_status", "")).lower() == "ok"
            and str(row.get("termination_condition", "")).lower() == "optimal"
            for row in artifact["models"]
        )
        validation_pass = bool(artifact["validation"]) and all(
            row.get("status") == "pass" for row in artifact["validation"]
        )
        status.append(
            {
                "stage": stage,
                "period_id": period_id,
                "dataset_split": period["dataset_split"],
                "case_id": case_id,
                "model_count": len(artifact["models"]),
                "all_models_optimal": optimal,
                "all_child_validation_checks_pass": validation_pass,
                "status": "pass" if optimal and validation_pass else "fail",
            }
        )
        if status[-1]["status"] != "pass":
            raise Phase5GFreezeError(f"{stage} physical gate failed for {period_id}.")
    return artifacts, status


def _actual_totals(
    artifacts: Mapping[str, Mapping[str, Any]], periods: Iterable[Mapping[str, Any]]
) -> dict[tuple[str, str], float]:
    periods = tuple(periods)
    return {
        (configuration, carrier): weighted_annual_equivalent_pj(
            artifacts, periods, configuration,
            ("gross_electricity_mwh" if carrier == "electricity" else "total_named_ng_procurement_mwh",),
        )
        for configuration in ("C0", "C1") for carrier in CARRIERS
    }


def _anchor_rows(
    stage: str, totals: Mapping[tuple[str, str], float], anchors: Mapping[tuple[str, str], float]
) -> list[dict[str, Any]]:
    return [
        {
            "stage": stage,
            "configuration": configuration,
            "carrier": carrier,
            "model_annual_equivalent_pj_y": totals[(configuration, carrier)],
            "source_anchor_pj_y": anchors[(configuration, carrier)],
            "signed_error_pj_y": totals[(configuration, carrier)] - anchors[(configuration, carrier)],
            "absolute_relative_error": abs(totals[(configuration, carrier)] / anchors[(configuration, carrier)] - 1.0),
            "interpretation": "representative-period annual-equivalent validation evidence",
        }
        for carrier in CARRIERS for configuration in ("C0", "C1")
    ]


def _physical_checks(
    stage: str, artifacts: Mapping[str, Mapping[str, Any]],
    expected_electricity: Mapping[str, float], expected_ng: Mapping[str, float],
    tolerance: float,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for period_id, artifact in artifacts.items():
        for configuration in ("C0", "C1"):
            rows = _configuration_rows(artifact, configuration)
            builder_id = BUILDER_CONFIGURATION[configuration]
            max_balance = max(
                abs(_float(row, field))
                for row in rows
                for field in (
                    "BFG_balance_residual_mwh", "COG_balance_residual_mwh",
                    "BOFG_balance_residual_mwh", "generator_fuel_identity_residual_mwh",
                )
            )
            max_el = max(abs(_float(row, "site_background_electricity_mwh") - float(expected_electricity[builder_id])) for row in rows)
            max_ng = max(abs(_float(row, "site_baseload_ng_mwh") - float(expected_ng[builder_id])) for row in rows)
            electricity_identity = max(
                abs(
                    _float(row, "gross_electricity_mwh")
                    - _float(row, "represented_gross_electricity_before_background_mwh")
                    - _float(row, "site_background_electricity_mwh")
                )
                for row in rows
            )
            ng_identity = max(
                abs(
                    _float(row, "total_named_ng_procurement_mwh")
                    - sum(
                        _float(row, field)
                        for field in (
                            "NG_to_HSM_mwh", "NG_to_PEFA_malerij_mwh",
                            "NG_to_PEFA_branderij_mwh", "natural_gas_boiler_mwh",
                            "generator_named_ng_mwh", "full_site_energy_bridge_named_ng_mwh",
                            "site_baseload_ng_mwh", "DRP_named_NG_mwh", "EAF_named_NG_mwh",
                        )
                    )
                )
                for row in rows
            )
            checks.extend(
                {
                    "stage": stage, "period_id": period_id, "configuration": configuration,
                    "check_id": check_id, "actual": actual, "limit": limit,
                    "status": "pass" if passed else "fail",
                }
                for check_id, passed, actual, limit in (
                    ("executed_hours_complete_seven_local_days", len(rows) in {168, 169}, len(rows), "168_or_169_DST_aware"),
                    ("carrier_and_generator_balances_close", max_balance <= tolerance, max_balance, tolerance),
                    ("zero_export", abs(_sum(rows, "gross_grid_export_mwh")) <= tolerance, _sum(rows, "gross_grid_export_mwh"), tolerance),
                    ("steam_unserved_zero", abs(_sum(rows, "steam_15bar_unserved_t")) <= tolerance, _sum(rows, "steam_15bar_unserved_t"), tolerance),
                    ("electricity_baseload_constant", max_el <= tolerance, max_el, tolerance),
                    ("electricity_gross_demand_identity", electricity_identity <= tolerance, electricity_identity, tolerance),
                    ("ng_baseload_constant", max_ng <= tolerance, max_ng, tolerance),
                    ("ng_procurement_identity_once", ng_identity <= tolerance, ng_identity, tolerance),
                    ("legacy_ng_bridge_zero", abs(_sum(rows, "full_site_energy_bridge_named_ng_mwh")) <= tolerance, _sum(rows, "full_site_energy_bridge_named_ng_mwh"), tolerance),
                    ("hsm_did_not_displace_ng_baseload", abs(_sum(rows, "site_baseload_ng_mwh") - len(rows) * float(expected_ng[builder_id])) <= tolerance, _sum(rows, "site_baseload_ng_mwh"), len(rows) * float(expected_ng[builder_id])),
                )
            )
    return checks


def _cross_stage_invariants(
    baseline: Mapping[str, Mapping[str, Any]],
    selected: Mapping[str, Mapping[str, Any]],
    periods: Iterable[Mapping[str, Any]],
    tolerance_pj: float,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for configuration in ("C0", "C1"):
        baseline_wag = weighted_annual_equivalent_pj(
            baseline, periods, configuration, ("WAG_generated",)
        )
        selected_wag = weighted_annual_equivalent_pj(
            selected, periods, configuration, ("WAG_generated",)
        )
        residual = abs(selected_wag - baseline_wag)
        checks.append(
            {
                "stage": "selected_validation",
                "period_id": "weighted_validation_set",
                "configuration": configuration,
                "check_id": "wag_production_unchanged_not_anchor_calibrated",
                "actual": residual,
                "limit": tolerance_pj,
                "status": "pass" if residual <= tolerance_pj else "fail",
            }
        )
    return checks


def _hsm_checks(
    stage: str, artifacts: Mapping[str, Mapping[str, Any]], phase: Mapping[str, Any], tolerance: float
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for period_id, artifact in artifacts.items():
        for configuration in ("C0", "C1"):
            rows = _configuration_rows(artifact, configuration)
            policy = phase["hsm_source_mix_policy_by_configuration"][BUILDER_CONFIGURATION[configuration]]
            target = (
                float(policy["ng_volume_fraction"]) * float(policy["ng_lhv_mj_per_nm3"])
                / (
                    float(policy["ng_volume_fraction"]) * float(policy["ng_lhv_mj_per_nm3"])
                    + float(policy["cog_volume_fraction"]) * float(policy["cog_lhv_mj_per_nm3"])
                )
            )
            residuals = []
            prohibited = 0.0
            for start in range(0, len(rows), 24):
                block = rows[start:start + 24]
                heat = _sum(block, "HSM_reheat_demand_mwh")
                ng = _sum(block, "NG_to_HSM_mwh")
                if heat > tolerance:
                    residuals.append(abs(ng / heat - target))
                prohibited += _sum(block, "BFG_to_HSM_mwh") + _sum(block, "BOFG_to_HSM_mwh")
            max_residual = max(residuals, default=0.0)
            checks.extend(
                [
                    {"stage": stage, "period_id": period_id, "configuration": configuration, "check_id": "hsm_24h_ng_energy_share", "actual": max_residual, "limit": tolerance, "status": "pass" if max_residual <= tolerance else "fail"},
                    {"stage": stage, "period_id": period_id, "configuration": configuration, "check_id": "hsm_bfg_bofg_excluded", "actual": prohibited, "limit": tolerance, "status": "pass" if abs(prohibited) <= tolerance else "fail"},
                ]
            )
    return checks


def _heracless_rows(
    artifacts: Mapping[str, Mapping[str, Any]], gates: Mapping[str, Any]
) -> list[dict[str, Any]]:
    c1_rows = [
        row for artifact in artifacts.values()
        for row in _configuration_rows(artifact, "C1")
    ]
    dri_output = _sum(c1_rows, "C1_DRP_DRI_output_t_h")
    split_residual = max(abs(_float(row, "DRP_HERACLES_NG_split_residual_mwh")) for row in c1_rows)
    electricity_intensity = 3.6 * _sum(c1_rows, "DRP_electricity_mwh") / dri_output
    availability = planned_outage_availability_context()
    return [
        {"evidence_id": "dri_ng_reduction_8_1_gj_per_t", "value": 8.1, "unit": "GJ_LHV/t_DRI", "role": "reporting_component", "dispatch_constraint": False, "status": "pass"},
        {"evidence_id": "dri_ng_furnace_1_8_gj_per_t", "value": 1.8, "unit": "GJ_LHV/t_DRI", "role": "reporting_component", "dispatch_constraint": False, "status": "pass"},
        {"evidence_id": "dri_ng_split_equals_existing_9_9", "value": split_residual, "unit": "MWh_LHV_max_abs_residual", "role": "validation_identity", "dispatch_constraint": False, "status": "pass" if split_residual <= float(gates["dri_ng_split_tolerance_mwh"]) else "fail"},
        {"evidence_id": "dri_electricity_0_3_gj_per_t", "value": electricity_intensity, "unit": "GJ_e/t_DRI", "role": "validation_identity", "dispatch_constraint": False, "status": "pass" if math.isclose(electricity_intensity, float(gates["dri_electricity_gj_per_t"]), abs_tol=float(gates["dri_ng_split_tolerance_mwh"])) else "fail"},
        {"evidence_id": "vn25_ij01_85_15_operating_time", "value": "85/15", "unit": "operating_time_context", "role": "validation_only_not_output_fuel_or_capacity_allocation", "dispatch_constraint": False, "status": "pass"},
        {"evidence_id": "dri_planned_outage_availability", "value": availability["DRI"][0], "upper_value": availability["DRI"][1], "unit": "annual_capacity_fraction_context", "role": "validation_only_not_calendar", "dispatch_constraint": False, "status": "pass"},
        {"evidence_id": "eaf_planned_outage_availability", "value": availability["EAF"][0], "upper_value": availability["EAF"][1], "unit": "annual_capacity_fraction_context", "role": "validation_only_not_calendar", "dispatch_constraint": False, "status": "pass"},
        {"evidence_id": "cold_dri_decoupling", "value": "finite_inventory_balance_and_terminal_handoff", "unit": "method", "role": "existing_physical_representation", "dispatch_constraint": True, "status": "pass"},
    ]


def _flow_summary(
    stage: str, artifacts: Mapping[str, Mapping[str, Any]], periods: Iterable[Mapping[str, Any]],
    ng_factor: float,
) -> list[dict[str, Any]]:
    periods = tuple(periods)
    fields = (
        "represented_gross_electricity_before_background_mwh", "site_background_electricity_mwh",
        "gross_electricity_mwh", "WAG_generator_electricity_mwh",
        "NG_generator_electricity_mwh", "total_generator_electricity_mwh",
        "gross_grid_import_mwh", "NG_to_HSM_mwh", "NG_to_PEFA_malerij_mwh",
        "NG_to_PEFA_branderij_mwh", "natural_gas_boiler_mwh",
        "generator_named_ng_mwh", "DRP_named_NG_mwh", "EAF_named_NG_mwh",
        "site_baseload_ng_mwh", "total_named_ng_procurement_mwh", "WAG_generated", "WAG_flared",
    )
    rows: list[dict[str, Any]] = []
    for configuration in ("C0", "C1"):
        values = {
            field: weighted_annual_equivalent_pj(artifacts, periods, configuration, (field,))
            for field in fields
        }
        for field, value in values.items():
            rows.append({"stage": stage, "configuration": configuration, "metric": field, "value": value, "unit": "PJ/y_annual_equivalent"})
        rows.append({
            "stage": stage,
            "configuration": configuration,
            "metric": "explicit_named_ng_procurement_excluding_site_baseload_mwh",
            "value": values["total_named_ng_procurement_mwh"] - values["site_baseload_ng_mwh"],
            "unit": "PJ/y_annual_equivalent",
            "caveat": "all named model NG consumers excluding the constant site baseload",
        })
        baseload_co2_t = values["site_baseload_ng_mwh"] * 1_000_000.0 * ng_factor / 1000.0
        rows.append({"stage": stage, "configuration": configuration, "metric": "site_baseload_ng_first_order_combustion_co2_proxy", "value": baseload_co2_t, "unit": "tCO2/y_annual_equivalent", "caveat": "separate first-order proxy; not ETS-ready Scope 1"})
    return rows


def _period_config_crosscheck(phase: Mapping[str, Any]) -> None:
    frozen = yaml.safe_load(_resolve(phase["frozen_period_selection_config"]).read_text(encoding="utf-8"))
    expected = {
        row["period_id"]: (row["frozen_forecast_start_origin_utc"], float(row["split_weight"]))
        for row in frozen["frozen_selection"]
    }
    actual = {
        row["period_id"]: (row["frozen_forecast_start_origin_utc"], float(row["split_weight"]))
        for row in (*phase["validation_periods"], *phase["held_out_periods"])
    }
    if actual != expected:
        raise Phase5GFreezeError("Phase-5G periods/weights differ from the frozen selection contract.")


def _dependencies(phase: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    parent = yaml.safe_load(_resolve(phase["parent_phase5b_config"]).read_text(encoding="utf-8"))
    phase4 = load_phase4_config(_resolve(parent["phase5b"]["phase4_config"]))
    check_phase4_config(phase4)
    targets = {
        row["period_id"]: row
        for row in _read_json(_resolve(parent["phase5b"]["phase4_target_contract"]))["targets"]
    }
    source_period = str(phase["frozen_terminal_target_source_period"])
    if source_period not in targets:
        raise Phase5GFreezeError("Frozen common terminal target source is unavailable.")
    return parent, phase4, targets[source_period]


def _persist_gate_output(
    *, config_file: Path, config: Mapping[str, Any], phase: Mapping[str, Any],
    source_path: Path, overlap_path: Path, selected_path: Path,
    pool_rows: Iterable[Mapping[str, Any]], score_rows: Iterable[Mapping[str, Any]],
    selected_rows: Iterable[Mapping[str, Any]], case_status: Iterable[Mapping[str, Any]],
    physical_checks: Iterable[Mapping[str, Any]], anchor_rows: Iterable[Mapping[str, Any]],
    flow_rows: Iterable[Mapping[str, Any]], heracless: Iterable[Mapping[str, Any]],
    checkpoint: Mapping[str, Any], started: float, warning: str,
) -> dict[str, Any]:
    output = _resolve(config["output_root"])
    if output.exists():
        raise Phase5GFreezeError("Phase-5G governed output root already exists.")
    output.mkdir(parents=True)
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(dict(config), sort_keys=False), encoding="utf-8"
    )
    _write_csv(output / "source_service_pool.csv", pool_rows)
    _write_csv(output / "baseload_candidate_scorecard.csv", score_rows)
    _write_csv(output / "selected_baseload_verification.csv", selected_rows)
    _write_csv(output / "case_status.csv", case_status)
    _write_csv(output / "physical_checks.csv", physical_checks)
    _write_csv(output / "annual_anchor_comparison.csv", anchor_rows)
    _write_csv(output / "carrier_flow_summary.csv", flow_rows)
    _write_csv(output / "heracless_validation.csv", heracless)
    input_files = [
        config_file, source_path, overlap_path, selected_path,
        _resolve(phase["source_card"]), _resolve(phase["heracless_source_card"]),
        Path(__file__).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
    ]
    manifest = [
        {"path": _portable(path), "sha256": _sha256(path), "size_bytes": path.stat().st_size}
        for path in input_files
    ]
    model_files = [
        path for path in input_files
        if "scripts/Data/04_Steel_Test_Case" in _portable(path)
    ]
    fingerprints = {
        "git_head": _git_head(),
        "model_fingerprint_sha256": _payload_sha256(
            {_portable(path): _sha256(path) for path in model_files}
        ),
        "input_contract_fingerprint_sha256": _payload_sha256(
            {_portable(path): _sha256(path) for path in input_files if path not in model_files}
        ),
        "hsm_policy_fingerprint_sha256": _payload_sha256(
            phase["hsm_source_mix_policy_by_configuration"]
        ),
        "selected_baseload_contract_sha256": _sha256(selected_path),
        "selected_shares": checkpoint["selected_shares"],
    }
    _write_json(output / "input_manifest.json", {"files": manifest})
    _write_json(output / "fingerprint_manifest.json", fingerprints)
    _write_json(output / "checkpoint_decision.json", checkpoint)
    summary = {
        **dict(checkpoint),
        "elapsed_seconds": time.perf_counter() - started,
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "fingerprints": fingerprints,
    }
    _write_json(output / "run_summary.json", summary)
    (output / "README.md").write_text(
        "# C5 Phase 5G deterministic freeze gate\n\n"
        f"Decision: `{checkpoint['decision']}`. This ignored governed run contains compact gate evidence only. The flat loads are validation-selected source-bounded development abstractions, not observed profiles.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "Annual-equivalent anchors are representative-period evidence, not annual backtests. The NG baseload CO2 row is a first-order combustion proxy, not ETS-ready Scope 1. WAG production is never calibrated to its annual anchor. VN25/IJM-01 85/15 and DRI/EAF outage ranges remain validation context only.\n\n"
        + warning + "\n",
        encoding="utf-8",
    )
    return summary


def run_phase5g(
    config_path: str | Path = CONFIG_PATH, *, selection_only: bool = False
) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    phase = config["phase5g"]
    if _git_head() != str(phase["expected_parent_head"]):
        raise Phase5GFreezeError("Phase-5G requires the preserved C5 parent HEAD.")
    _period_config_crosscheck(phase)
    source_path = _resolve(phase["source_contract"])
    overlap_path = _resolve(phase["overlap_contract"])
    selected_path = _resolve(phase["selected_baseload_contract"])
    source_rows = load_source_contract(source_path)
    overlap_rows = load_overlap_contract(overlap_path)
    validate_overlap_against_source(overlap_rows, source_rows)
    parent, phase4, terminal_target = _dependencies(phase)
    if _select_solver()[1] is None:
        raise Phase5GFreezeError("Gurobi is unavailable before the first Phase-5G solve.")
    install_terminal_validation_extension()
    _resolve(phase["scratch_root"]).mkdir(parents=True, exist_ok=True)

    zero = {configuration: 0.0 for configuration in CONFIGURATIONS}
    baseline_artifacts, baseline_status = _stage_artifacts(
        "baseline", phase["validation_periods"], phase, parent, phase4,
        terminal_target, zero, zero,
    )
    pool_rows = source_service_pools(
        baseline_artifacts, phase["validation_periods"], overlap_rows
    )
    pool_totals = _pool_totals(pool_rows)
    anchors = _primary_anchors(source_rows)
    explicit = explicit_baseline_totals(baseline_artifacts, phase["validation_periods"])
    selections, score_rows = select_shared_percentages(
        explicit, pool_totals, anchors, phase["percentage_grid"],
        float(phase["gates"]["percentage_tolerance"]),
    )
    expected_contract = selected_contract_rows(selections, pool_totals)

    if selection_only:
        preview = _resolve(phase["selection_preview_root"])
        if preview.exists():
            raise Phase5GFreezeError("Phase-5G selection preview root already exists.")
        preview.mkdir(parents=True)
        _write_csv(preview / "source_service_pool.csv", pool_rows)
        _write_csv(preview / "baseload_candidate_scorecard.csv", score_rows)
        _write_csv(preview / "selected_site_baseload_contract_preview.csv", expected_contract)
        _write_json(preview / "selection_summary.json", {"run_id": RUN_ID, "selection_only": True, "selected_shares": selections, "baseline_model_count": sum(row["model_count"] for row in baseline_status), "selected_contract_preview_sha256": _sha256(preview / "selected_site_baseload_contract_preview.csv")})
        return {"status": "selection_ready", "selected_shares": selections, "preview_root": _portable(preview), "selected_contract_rows": expected_contract}

    selected_rows = load_selected_contract(selected_path)
    validate_selected_contract(
        selected_rows, expected_contract, float(phase["gates"]["annual_identity_tolerance_pj"])
    )
    electricity, ng = _baseload_maps(selected_rows)
    selected_artifacts, selected_status = _stage_artifacts(
        "selected_validation", phase["validation_periods"], phase, parent, phase4,
        terminal_target, electricity, ng,
    )
    baseline_totals = _actual_totals(baseline_artifacts, phase["validation_periods"])
    selected_totals = _actual_totals(selected_artifacts, phase["validation_periods"])
    anchor_rows = (
        _anchor_rows("baseline", baseline_totals, anchors)
        + _anchor_rows("selected_validation", selected_totals, anchors)
    )
    baseline_errors = {(row["configuration"], row["carrier"]): row["absolute_relative_error"] for row in anchor_rows if row["stage"] == "baseline"}
    selected_errors = {(row["configuration"], row["carrier"]): row["absolute_relative_error"] for row in anchor_rows if row["stage"] == "selected_validation"}
    tolerance = float(phase["gates"]["dynamic_balance_tolerance_mwh"])
    physical_checks = (
        _physical_checks("baseline", baseline_artifacts, zero, zero, tolerance)
        + _physical_checks("selected_validation", selected_artifacts, electricity, ng, tolerance)
        + _hsm_checks("baseline", baseline_artifacts, phase, tolerance)
        + _hsm_checks("selected_validation", selected_artifacts, phase, tolerance)
        + _cross_stage_invariants(
            baseline_artifacts, selected_artifacts, phase["validation_periods"],
            float(phase["gates"]["annual_identity_tolerance_pj"]),
        )
    )
    heracless = _heracless_rows(selected_artifacts, phase["gates"])
    flow_rows = (
        _flow_summary("baseline", baseline_artifacts, phase["validation_periods"], float(phase["gates"]["ng_combustion_factor_kg_co2_per_gj"]))
        + _flow_summary("selected_validation", selected_artifacts, phase["validation_periods"], float(phase["gates"]["ng_combustion_factor_kg_co2_per_gj"]))
    )
    case_status = baseline_status + selected_status
    anchor_improvement_pass = all(
        selected_errors[key] < baseline_errors[key] - 1e-12 for key in baseline_errors
    )
    selected_validation_pass = (
        anchor_improvement_pass
        and all(row["status"] == "pass" for row in physical_checks + heracless)
    )
    if not selected_validation_pass:
        checkpoint = {
            "run_id": RUN_ID,
            "decision": "baseload_selection_gate_failed_model_not_frozen",
            "status": "fail",
            "model_count": sum(int(row["model_count"]) for row in case_status),
            "baseline_models": int(phase["expected_models_per_stage"]),
            "selected_validation_models": int(phase["expected_models_per_stage"]),
            "held_out_models": 0,
            "selected_shares": selections,
            "anchor_improvement_gate_pass": anchor_improvement_pass,
            "failed_anchor_keys": [
                {"configuration": key[0], "carrier": key[1]}
                for key in baseline_errors
                if selected_errors[key] >= baseline_errors[key] - 1e-12
            ],
            "phase6_authorization": "blocked",
            "reselection_after_held_out": False,
            "failure_count": 1,
        }
        return _persist_gate_output(
            config_file=config_file, config=config, phase=phase,
            source_path=source_path, overlap_path=overlap_path,
            selected_path=selected_path, pool_rows=pool_rows,
            score_rows=score_rows, selected_rows=selected_rows,
            case_status=case_status, physical_checks=physical_checks,
            anchor_rows=anchor_rows, flow_rows=flow_rows, heracless=heracless,
            checkpoint=checkpoint, started=started,
            warning=(
                "The independently selected electricity baseload activated C0 generator NG, "
                "so C0 NG anchor error worsened. Held-out evaluation is prohibited by the "
                "corrected runner after this failed selected-validation gate. A prior local "
                "orchestration attempt opened held-out scratch cases before this ordering defect "
                "was corrected; those cases are excluded and cannot support a pristine held-out claim."
            ),
        )

    if any(
        row["selection_status"] != "selected_validation_frozen"
        for row in selected_rows
    ):
        raise Phase5GFreezeError(
            "A previously failed baseload contract cannot enter held-out validation."
        )

    held_out_artifacts, held_out_status = _stage_artifacts(
        "held_out", phase["held_out_periods"], phase, parent, phase4,
        terminal_target, electricity, ng,
    )
    held_out_totals = _actual_totals(held_out_artifacts, phase["held_out_periods"])
    anchor_rows += _anchor_rows("held_out", held_out_totals, anchors)
    physical_checks += (
        _physical_checks("held_out", held_out_artifacts, electricity, ng, tolerance)
        + _hsm_checks("held_out", held_out_artifacts, phase, tolerance)
    )
    flow_rows += _flow_summary(
        "held_out", held_out_artifacts, phase["held_out_periods"],
        float(phase["gates"]["ng_combustion_factor_kg_co2_per_gj"]),
    )
    case_status += held_out_status
    if any(row["status"] != "pass" for row in physical_checks):
        raise Phase5GFreezeError("Phase-5G held-out physical gate failed.")
    if sum(int(row["model_count"]) for row in case_status) != int(phase["expected_total_models"]):
        raise Phase5GFreezeError("Phase-5G campaign model count changed.")

    checkpoint = {
        "run_id": RUN_ID,
        "decision": "deterministic_physical_model_frozen_for_phase6",
        "status": "pass",
        "model_count": int(phase["expected_total_models"]),
        "baseline_models": int(phase["expected_models_per_stage"]),
        "selected_validation_models": int(phase["expected_models_per_stage"]),
        "held_out_models": int(phase["expected_models_per_stage"]),
        "selected_shares": selections,
        "phase6_authorization": "phase6a_deterministic_day_ahead_bid_and_settlement_accounting_only",
        "reselection_after_held_out": False,
        "failure_count": 0,
    }
    return _persist_gate_output(
        config_file=config_file, config=config, phase=phase,
        source_path=source_path, overlap_path=overlap_path,
        selected_path=selected_path, pool_rows=pool_rows,
        score_rows=score_rows, selected_rows=selected_rows,
        case_status=case_status, physical_checks=physical_checks,
        anchor_rows=anchor_rows, flow_rows=flow_rows, heracless=heracless,
        checkpoint=checkpoint, started=started,
        warning=(
            "Held-out anchor deviations are generalisation evidence only and were not tuned."
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--selection-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_phase5g(args.config, selection_only=args.selection_only), indent=2))


if __name__ == "__main__":
    main()
