"""Phase 5H dependency-aware four-residual effect and final-selection gate."""

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
    HOURS_PER_YEAR,
    PJ_PER_MWH,
)
from .s4_4c5p_phase5b_c0_export_sensitivity import (
    _git_head, _read_csv, _select_solver, _sha256,
    install_terminal_validation_extension,
)
from .s4_4c5p_phase5e_source_backed_anchor_closure import load_source_contract
from .s4_4c5p_phase5g_final_deterministic_freeze import (
    BUILDER_CONFIGURATION,
    CONFIGURATIONS,
    _actual_totals,
    _dependencies,
    _flow_summary,
    _pool_totals,
    _primary_anchors,
    _stage_artifacts,
    candidate_percentages,
    load_config as load_phase5g_config,
    load_overlap_contract as load_phase5g_overlap_contract,
    source_service_pools,
    validate_overlap_against_source,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_c5_phase5h_four_residual_final_selection_gate_v1_20260728"
CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase5h_four_residual_effect_gate.yaml"
)
FAMILIES = ("electricity", "natural_gas", "residual_steam", "residual_direct_co2")
OLD_OPENED_HELD_OUT = {
    "test_2025-09-08", "test_2024-10-21", "test_2024-12-09", "test_2025-01-13"
}


class Phase5HGateError(RuntimeError):
    pass


def _resolve(path: str | Path) -> Path:
    value = Path(path)
    return value.resolve() if value.is_absolute() else (REPO_ROOT / value).resolve()


def _portable(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise Phase5HGateError(f"Persistent path is not repository-relative: {path}") from exc


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
        raise Phase5HGateError("Phase-5H identity or minimal-output policy changed.")
    phase = payload.get("phase5h")
    if not isinstance(phase, Mapping):
        raise Phase5HGateError("Phase-5H configuration is missing.")
    if tuple(float(value) for value in phase.get("percentage_grid", ())) != candidate_percentages():
        raise Phase5HGateError("Residual candidate grid must be exactly 10%-90%.")
    policy = phase.get("policy", {})
    required_false = (
        "phase5g_failed_baseload_active", "legacy_ng_bridge_active",
        "residual_ng_wag_substitutable", "residual_co2_dispatchable",
        "residual_co2_in_cost_or_ets", "annual_value_is_varying_hourly_profile",
        "held_out_reselection_allowed", "production_physics_changes_allowed",
        "wag_yield_changes_allowed", "market_logic_allowed",
    )
    if any(bool(policy.get(key)) for key in required_false):
        raise Phase5HGateError("Phase-5H bounded residual policy changed.")
    if not all(bool(policy.get(key)) for key in (
        "all_four_required_for_promotion",
        "steam_branch_fail_closed_without_maximum",
        "continue_electricity_ng_co2_diagnostics_after_steam_failure",
    )):
        raise Phase5HGateError("Phase-5H fail-closed dependency policy changed.")
    periods = list(phase.get("validation_periods", ()))
    if len(periods) != 4 or any(row.get("dataset_split") != "validation" for row in periods):
        raise Phase5HGateError("Four unchanged validation periods are required.")
    if not math.isclose(sum(float(row["split_weight"]) for row in periods), 1.0, abs_tol=2e-12):
        raise Phase5HGateError("Validation weights must sum to one.")
    return payload


def load_four_residual_overlap(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_csv(Path(path))
    required = {
        "mapping_id", "family", "configuration", "source_component", "source_value",
        "original_unit", "dynamic_overlap_fields", "residual_eligible",
        "overlap_classification", "source_id", "source_locator", "activity_basis",
        "energy_or_mass_basis", "time_basis", "nonoverlap_rule",
    }
    if not rows or required.difference(rows[0]):
        raise Phase5HGateError("Four-residual overlap schema is incomplete.")
    if {row["family"] for row in rows} != set(FAMILIES):
        raise Phase5HGateError("Every residual family must occur in the overlap contract.")
    seen_ids: set[str] = set()
    seen_fields: set[tuple[str, str, str]] = set()
    for row in rows:
        if not row["mapping_id"] or row["mapping_id"] in seen_ids:
            raise Phase5HGateError(f"Duplicate overlap mapping: {row['mapping_id']}")
        seen_ids.add(row["mapping_id"])
        if not row["source_id"] or not row["source_locator"]:
            raise Phase5HGateError(f"Missing source locator: {row['mapping_id']}")
        row["residual_eligible"] = row["residual_eligible"].lower() == "true"
        row["source_value"] = None if row["source_value"] == "" else float(row["source_value"])
        fields = tuple(field for field in row["dynamic_overlap_fields"].split(";") if field)
        row["dynamic_overlap_fields"] = fields
        for field in fields:
            key = (row["configuration"], row["family"], field)
            if key in seen_fields:
                raise Phase5HGateError(f"Explicit field maps more than once: {key}")
            seen_fields.add(key)
    prohibited = {
        "boundary_remainder_ineligible", "overlapping_aggregate_counter_ineligible",
        "scope2_excluded", "avoided_captured_and_ets_excluded",
    }
    if any(row["residual_eligible"] for row in rows if row["overlap_classification"] in prohibited):
        raise Phase5HGateError("An expressly excluded overlap row became eligible.")
    return rows


def steam_evidence_gate(path: str | Path) -> dict[str, Any]:
    rows = _read_csv(Path(path))
    if not rows or any(not row.get(field) for row in rows for field in (
        "source_id", "exact_locator", "original_unit", "pressure_level",
        "temperature_or_enthalpy_basis", "annual_operating_basis",
        "condensate_return_treatment", "explicit_overlap", "normal_or_startup", "status",
    )):
        raise Phase5HGateError("Steam evidence gate is incomplete.")
    eligible = [
        row for row in rows
        if row["status"] == "eligible_normal_operation_maximum" and row["eligible_maximum_t_y"]
    ]
    return {
        "status": "pass" if eligible else "fail",
        "defensible_maximum_exists": bool(eligible),
        "eligible_row_count": len(eligible),
        "decision": (
            "steam_percentage_sweep_authorized" if eligible
            else "steam_branch_stopped_no_defensible_normal_operation_maximum"
        ),
        "prohibited_bases_present": sorted({
            row["gate_id"] for row in rows if row["status"] == "prohibited_numerical_basis"
        }),
    }


def held_out_contract(path: str | Path) -> tuple[list[dict[str, Any]], str]:
    rows = _read_csv(Path(path))
    if len(rows) != 4 or any(row["dataset_split"] != "test" for row in rows):
        raise Phase5HGateError("Exactly four fresh test periods must be frozen.")
    ids = {row["period_id"] for row in rows}
    if len(ids) != 4 or ids & OLD_OPENED_HELD_OUT:
        raise Phase5HGateError("Fresh held-out periods overlap a previously opened period.")
    if any(row["status"] != "frozen_unopened" for row in rows):
        raise Phase5HGateError("Fresh held-out periods must remain unopened at preflight.")
    if not math.isclose(sum(float(row["split_weight"]) for row in rows), 1.0, abs_tol=1e-12):
        raise Phase5HGateError("Fresh held-out weights must sum to one.")
    return rows, _sha256(Path(path))


def _configuration_rows(artifact: Mapping[str, Any], configuration: str) -> list[dict[str, Any]]:
    builder = BUILDER_CONFIGURATION[configuration]
    rows = [row for row in artifact["hourly"] if row.get("configuration_id") == builder]
    if not rows:
        raise Phase5HGateError(f"Missing hourly rows for {configuration}.")
    return rows


def weighted_annual_equivalent(
    artifacts: Mapping[str, Mapping[str, Any]], periods: Iterable[Mapping[str, Any]],
    configuration: str, field: str, scale: float,
) -> float:
    return sum(
        float(period["split_weight"])
        * sum(float(row.get(field) or 0.0) for row in _configuration_rows(
            artifacts[str(period["period_id"])], configuration
        ))
        * HOURS_PER_YEAR
        / len(_configuration_rows(artifacts[str(period["period_id"])], configuration))
        * scale
        for period in periods
    )


def weighted_annual_procurement_cost_eur(
    artifacts: Mapping[str, Mapping[str, Any]], periods: Iterable[Mapping[str, Any]],
    configuration: str,
) -> float:
    builder = BUILDER_CONFIGURATION[configuration]
    return sum(
        float(period["split_weight"])
        * sum(
            float(row.get("cost_eur") or 0.0)
            for row in artifacts[str(period["period_id"])]["costs"]
            if row.get("configuration_id") == builder
        )
        * HOURS_PER_YEAR
        / len(_configuration_rows(artifacts[str(period["period_id"])], configuration))
        for period in periods
    )


def procurement_cost_rows(
    stage: str, artifacts: Mapping[str, Mapping[str, Any]],
    periods: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    periods = tuple(periods)
    return [{
        "stage": stage, "configuration": configuration,
        "metric": "represented_procurement_cost_eur_y",
        "value": weighted_annual_procurement_cost_eur(
            artifacts, periods, configuration
        ),
        "unit": "EUR/y_annual_equivalent",
        "caveat": "fixed-reference represented procurement boundary; not a market backtest",
    } for configuration in ("C0", "C1")]


def steam_and_emissions_rows(
    stage: str, artifacts: Mapping[str, Mapping[str, Any]],
    periods: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    periods = tuple(periods)
    definitions = {
        "WAG_to_boiler_mwh": (("BFG_to_boiler_mwh", "COG_to_boiler_mwh", "BOFG_to_boiler_mwh"), PJ_PER_MWH, "PJ/y_annual_equivalent"),
        "steam_15bar_explicit_demand": (("steam_15bar_explicit_demand_t",), 1.0 / 1000.0, "kt/y_annual_equivalent"),
        "residual_steam_15bar_demand": (("residual_steam_15bar_demand_t",), 1.0 / 1000.0, "kt/y_annual_equivalent"),
        "steam_15bar_unserved": (("steam_15bar_unserved_t",), 1.0 / 1000.0, "kt/y_annual_equivalent"),
        "steam_15bar_spill": (("steam_15bar_spill_t",), 1.0 / 1000.0, "kt/y_annual_equivalent"),
        "flaring_co2": (("flaring_co2_t",), 1.0 / 1_000_000.0, "MtCO2/y_annual_equivalent"),
        "WAG_explicit_combustion_co2": (("WAG_explicit_combustion_co2_t",), 1.0 / 1_000_000.0, "MtCO2/y_annual_equivalent"),
        "explicit_NG_combustion_co2": (("explicit_NG_combustion_co2_t",), 1.0 / 1_000_000.0, "MtCO2/y_annual_equivalent"),
        "residual_unmodelled_direct_co2": (("residual_unmodelled_direct_co2_t",), 1.0 / 1_000_000.0, "MtCO2/y_annual_equivalent"),
    }
    rows: list[dict[str, Any]] = []
    for configuration in ("C0", "C1"):
        for metric, (fields, scale, unit) in definitions.items():
            rows.append({
                "stage": stage, "configuration": configuration, "metric": metric,
                "value": sum(weighted_annual_equivalent(
                    artifacts, periods, configuration, field, scale
                ) for field in fields),
                "unit": unit,
            })
    return rows


def _scope1_anchors(source_rows: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    values = {
        str(row["configuration"]): float(row["value"])
        for row in source_rows
        if row["family"] == "scope1_co2" and row["record_kind"] == "primary_total"
    }
    if set(values) != {"C0", "C1"}:
        raise Phase5HGateError("C0/C1 Scope-1 comparison anchors are required.")
    return values


def _co2_components(source_rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], float]:
    return {
        (str(row["configuration"]), str(row["component"])): float(row["value"])
        for row in source_rows
        if row["family"] == "scope1_co2" and row["record_kind"] == "component"
    }


def _best_share(
    conditional_zero: Mapping[str, float], pools: Mapping[str, float],
    anchors: Mapping[str, float], tolerance: float = 1e-12,
) -> tuple[float | None, list[dict[str, Any]]]:
    baseline = {
        configuration: abs(conditional_zero[configuration] / anchors[configuration] - 1.0)
        for configuration in ("C0", "C1")
    }
    rows: list[dict[str, Any]] = []
    for alpha in candidate_percentages():
        errors = {
            configuration: abs(
                (conditional_zero[configuration] + alpha * pools[configuration])
                / anchors[configuration] - 1.0
            )
            for configuration in ("C0", "C1")
        }
        eligible = all(errors[c] < baseline[c] - tolerance for c in ("C0", "C1"))
        rows.append({
            "share": alpha, "eligible": eligible,
            "C0_error": errors["C0"], "C1_error": errors["C1"],
            "maximum_error": max(errors.values()),
            "mean_error": sum(errors.values()) / 2.0,
        })
    eligible_rows = [row for row in rows if row["eligible"]]
    if not eligible_rows:
        return None, rows
    selected = min(eligible_rows, key=lambda row: (
        row["maximum_error"], row["mean_error"], row["share"]
    ))
    return float(selected["share"]), rows


def component_exceedances(
    pool_rows: Iterable[Mapping[str, Any]], tolerance_pj: float,
    baseline_mapped_by_id: Mapping[str, float] | None = None,
) -> list[Mapping[str, Any]]:
    """Reject a source exceedance caused or enlarged by the physical candidate."""
    baseline = dict(baseline_mapped_by_id or {})
    return [
        row for row in pool_rows
        if row["dynamic_overlap_fields"]
        and float(row["mapped_explicit_model_pj_y"])
        > float(row["source_value_pj_y"]) + tolerance_pj
        and (
            not baseline
            or float(row["mapped_explicit_model_pj_y"])
            > float(baseline.get(str(row["mapping_id"]), 0.0)) + tolerance_pj
        )
    ]


def conditional_residual_scores(
    stage: str, artifacts: Mapping[str, Mapping[str, Any]],
    periods: Iterable[Mapping[str, Any]], source_rows: list[dict[str, Any]],
    ng_overlap: list[dict[str, Any]], electricity_alpha: float,
    component_tolerance_pj: float, ng_factor_kg_gj: float,
    baseline_ng_mapped_by_id: Mapping[str, float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    periods = tuple(periods)
    energy_anchors = _primary_anchors(source_rows)
    actual = _actual_totals(artifacts, periods)
    physical_cost = {
        c: weighted_annual_procurement_cost_eur(artifacts, periods, c)
        for c in ("C0", "C1")
    }
    ng_prices = {
        float(row["price_eur_per_unit"])
        for artifact in artifacts.values() for row in artifact["costs"]
        if row.get("quantity_unit") == "MWh_LHV"
        and row.get("price_id") == "natural_gas_ttf_proxy"
    }
    if len(ng_prices) != 1:
        raise Phase5HGateError("Conditional NG costing requires one frozen NG price.")
    ng_price_eur_mwh = next(iter(ng_prices))
    ng_pool_rows = source_service_pools(artifacts, periods, ng_overlap)
    ng_pools_all = _pool_totals(ng_pool_rows)
    ng_pools = {c: ng_pools_all[(c, "natural_gas")] for c in ("C0", "C1")}
    ng_zero = {c: actual[(c, "natural_gas")] for c in ("C0", "C1")}
    ng_anchors = {c: energy_anchors[(c, "natural_gas")] for c in ("C0", "C1")}
    exceed = component_exceedances(
        ng_pool_rows, component_tolerance_pj, baseline_ng_mapped_by_id
    )
    ng_alpha, ng_grid = _best_share(ng_zero, ng_pools, ng_anchors)
    grid_rows = [
        {"stage": stage, "electricity_share": electricity_alpha, "family": "natural_gas", **row}
        for row in ng_grid
    ]
    if ng_alpha is None or exceed:
        return {
            "stage": stage, "electricity_share": electricity_alpha,
            "component_overlap_pass": not exceed,
            "exceeded_components": ";".join(row["mapping_id"] for row in exceed),
            "selected_ng_share": "", "selected_co2_share": "",
            "eligible_three_family_diagnostic": False,
            "C0_physical_procurement_cost_eur_y": physical_cost["C0"],
            "C1_physical_procurement_cost_eur_y": physical_cost["C1"],
        }, grid_rows

    residual_ng = {c: ng_alpha * ng_pools[c] for c in ("C0", "C1")}
    final_ng = {c: ng_zero[c] + residual_ng[c] for c in ("C0", "C1")}
    wag_co2 = {
        c: weighted_annual_equivalent(
            artifacts, periods, c, "WAG_explicit_combustion_co2_t", 1.0 / 1_000_000.0
        ) for c in ("C0", "C1")
    }
    explicit_ng_co2 = {
        c: weighted_annual_equivalent(
            artifacts, periods, c, "explicit_NG_combustion_co2_t", 1.0 / 1_000_000.0
        ) for c in ("C0", "C1")
    }
    residual_ng_co2 = {c: residual_ng[c] * ng_factor_kg_gj / 1000.0 for c in ("C0", "C1")}
    co2_zero = {
        c: wag_co2[c] + explicit_ng_co2[c] + residual_ng_co2[c] for c in ("C0", "C1")
    }
    components = _co2_components(source_rows)
    co2_pools = {
        "C0": (
            max(0.0, components[("C0", "coal_and_other_carbon")] - wag_co2["C0"])
            + max(0.0, components[("C0", "natural_gas")] - explicit_ng_co2["C0"] - residual_ng_co2["C0"])
            + components[("C0", "iron_bearing_material")]
            + components[("C0", "fluxes")]
        ),
        "C1": (
            max(0.0, components[("C1", "coal_and_other_carbon")] - wag_co2["C1"])
            + max(0.0, components[("C1", "natural_gas")] - explicit_ng_co2["C1"] - residual_ng_co2["C1"])
            + components[("C1", "fluxes")]
        ),
    }
    co2_anchors = _scope1_anchors(source_rows)
    co2_alpha, co2_grid = _best_share(co2_zero, co2_pools, co2_anchors)
    grid_rows.extend(
        {"stage": stage, "electricity_share": electricity_alpha, "family": "residual_direct_co2", **row}
        for row in co2_grid
    )
    electricity_errors = {
        c: abs(actual[(c, "electricity")] / energy_anchors[(c, "electricity")] - 1.0)
        for c in ("C0", "C1")
    }
    ng_errors = {c: abs(final_ng[c] / ng_anchors[c] - 1.0) for c in ("C0", "C1")}
    final_co2 = {
        c: co2_zero[c] + (co2_alpha or 0.0) * co2_pools[c] for c in ("C0", "C1")
    }
    co2_errors = {c: abs(final_co2[c] / co2_anchors[c] - 1.0) for c in ("C0", "C1")}
    all_errors = (*electricity_errors.values(), *ng_errors.values(), *co2_errors.values())
    return {
        "stage": stage, "electricity_share": electricity_alpha,
        "component_overlap_pass": True, "exceeded_components": "",
        "selected_ng_share": ng_alpha,
        "selected_co2_share": "" if co2_alpha is None else co2_alpha,
        "eligible_three_family_diagnostic": co2_alpha is not None,
        "C0_electricity_error": electricity_errors["C0"],
        "C1_electricity_error": electricity_errors["C1"],
        "C0_ng_error": ng_errors["C0"], "C1_ng_error": ng_errors["C1"],
        "C0_co2_error": co2_errors["C0"], "C1_co2_error": co2_errors["C1"],
        "maximum_three_family_error": max(all_errors),
        "mean_three_family_error": sum(all_errors) / len(all_errors),
        "C0_ng_pool_pj_y": ng_pools["C0"], "C1_ng_pool_pj_y": ng_pools["C1"],
        "C0_co2_pool_mt_y": co2_pools["C0"], "C1_co2_pool_mt_y": co2_pools["C1"],
        "C0_wag_combustion_mt_y": wag_co2["C0"], "C1_wag_combustion_mt_y": wag_co2["C1"],
        "C0_explicit_ng_combustion_mt_y": explicit_ng_co2["C0"],
        "C1_explicit_ng_combustion_mt_y": explicit_ng_co2["C1"],
        "C0_physical_procurement_cost_eur_y": physical_cost["C0"],
        "C1_physical_procurement_cost_eur_y": physical_cost["C1"],
        "conditional_ng_price_eur_per_mwh_lhv": ng_price_eur_mwh,
        "C0_conditional_residual_ng_cost_eur_y": residual_ng["C0"] / PJ_PER_MWH * ng_price_eur_mwh,
        "C1_conditional_residual_ng_cost_eur_y": residual_ng["C1"] / PJ_PER_MWH * ng_price_eur_mwh,
        "C0_conditional_total_procurement_cost_eur_y": physical_cost["C0"] + residual_ng["C0"] / PJ_PER_MWH * ng_price_eur_mwh,
        "C1_conditional_total_procurement_cost_eur_y": physical_cost["C1"] + residual_ng["C1"] / PJ_PER_MWH * ng_price_eur_mwh,
    }, grid_rows


def _persist(
    config_file: Path, config: Mapping[str, Any], phase: Mapping[str, Any],
    steam_gate: Mapping[str, Any], heldout_sha: str, source_pool: list[dict[str, Any]],
    case_status: list[dict[str, Any]], flow_rows: list[dict[str, Any]],
    diagnostic_rows: list[dict[str, Any]], algebraic_rows: list[dict[str, Any]],
    overlap_checks: list[dict[str, Any]], started: float,
) -> dict[str, Any]:
    output = _resolve(config["output_root"])
    if output.exists():
        raise Phase5HGateError("Phase-5H governed output root already exists.")
    output.mkdir(parents=True)
    _write_csv(output / "source_service_pool.csv", source_pool)
    _write_csv(output / "case_status.csv", case_status)
    _write_csv(output / "physical_effect_waterfall.csv", flow_rows)
    _write_csv(output / "three_family_diagnostic_scorecard.csv", diagnostic_rows)
    _write_csv(output / "conditional_ng_co2_grids.csv", algebraic_rows)
    _write_csv(output / "overlap_validation.csv", overlap_checks)
    _write_json(output / "steam_evidence_gate.json", steam_gate)
    eligible = [row for row in diagnostic_rows if row.get("eligible_three_family_diagnostic") is True]
    best = min(eligible, key=lambda row: (
        float(row["maximum_three_family_error"]),
        float(row["mean_three_family_error"]),
        float(row["electricity_share"]) + float(row["selected_ng_share"]) + float(row["selected_co2_share"]),
        float(row["electricity_share"]), str(row["stage"]),
    )) if eligible else None
    checkpoint = {
        "run_id": RUN_ID,
        "decision": phase["decision_on_fail"],
        "status": "fail",
        "failure_reason": "no_defensible_normal_operation_residual_steam_maximum",
        "steam_branch_models": 0,
        "coupled_interaction_models": 0,
        "selected_validation_models": 0,
        "fresh_held_out_models": 0,
        "fresh_held_out_status": "frozen_unopened_gate_order_preserved",
        "total_diagnostic_models": sum(int(row["model_count"]) for row in case_status),
        "four_residual_contract_promoted": False,
        "deterministic_model_frozen_for_phase6": False,
        "phase6_authorization": "blocked",
        "best_nonpromotable_three_family_diagnostic": best,
        "reselection_after_held_out": False,
        "failure_count": 1,
    }
    _write_json(output / "checkpoint_decision.json", checkpoint)
    inputs = [
        config_file, _resolve(phase["source_contract"]), _resolve(phase["overlap_contract"]),
        _resolve(phase["phase5g_overlap_contract"]),
        _resolve(phase["steam_evidence_gate"]), _resolve(phase["fresh_held_out_contract"]),
        _resolve(phase["selected_contract"]), Path(__file__).resolve(),
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/F18_athanasiadis_tata_ijmuiden_thesis.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_cards/BOILER_STEAM_CIRCUIT_Parameters.md",
        REPO_ROOT / "data/03_Optimisation/inputs/assets/steel/source_evidence/steel_source_card_register.csv",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
    ]
    manifest = [{"path": _portable(path), "sha256": _sha256(path), "size_bytes": path.stat().st_size} for path in inputs]
    _write_json(output / "input_manifest.json", {"files": manifest})
    fingerprints = {
        "git_head": _git_head(),
        "model_fingerprint_sha256": _payload_sha256({row["path"]: row["sha256"] for row in manifest if row["path"].endswith(".py")}),
        "input_contract_fingerprint_sha256": _payload_sha256({row["path"]: row["sha256"] for row in manifest if not row["path"].endswith(".py")}),
        "fresh_held_out_contract_sha256": heldout_sha,
        "phase5g_failed_baseload_active": False,
    }
    _write_json(output / "fingerprint_manifest.json", fingerprints)
    summary = {
        **checkpoint, "runtime_seconds": time.perf_counter() - started,
        "output_policy": config["output_policy"], "run_class": config["run_class"],
        "lineage_role": config["lineage_role"], "fingerprints": fingerprints,
    }
    _write_json(output / "run_summary.json", summary)
    (output / "README.md").write_text(
        "# C5 Phase 5H four-residual effect gate\n\n"
        "Decision: `four_residual_gate_failed_residual_layer_not_promoted`. The required "
        "normal-operation residual-steam maximum was not found. Electricity, NG and direct-CO2 "
        "results are bounded diagnostics only; no residual contract was activated and fresh held-out "
        "periods remained unopened.\n", encoding="utf-8"
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\nAthanasiadis supports the existence and constant modelling role of four residual terms, not their Tata-specific magnitudes. The diagnostic shares are not observed profiles, process allocations, approved Tata inputs or ETS-ready emissions. No exact anchor closure is required or permitted.\n",
        encoding="utf-8",
    )
    return summary


def run_phase5h(config_path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    phase = config["phase5h"]
    if _git_head() != str(phase["expected_parent_head"]):
        raise Phase5HGateError("Phase-5H requires the preserved C5 parent HEAD.")
    source_rows = load_source_contract(_resolve(phase["source_contract"]))
    overlap_rows = load_four_residual_overlap(_resolve(phase["overlap_contract"]))
    steam_gate = steam_evidence_gate(_resolve(phase["steam_evidence_gate"]))
    _, heldout_sha = held_out_contract(_resolve(phase["fresh_held_out_contract"]))
    if steam_gate["defensible_maximum_exists"]:
        raise Phase5HGateError("This bounded runner expects the reviewed public-evidence steam gate result.")

    phase5g_config = load_phase5g_config(_resolve(phase["phase5g_config"]))
    phase5g = dict(phase5g_config["phase5g"])
    phase5g["scratch_root"] = phase["scratch_root"]
    phase5g["validation_periods"] = phase["validation_periods"]
    phase5g_overlap = load_phase5g_overlap_contract(_resolve(phase["phase5g_overlap_contract"]))
    validate_overlap_against_source(phase5g_overlap, source_rows)
    parent, phase4, terminal_target = _dependencies(phase5g)
    if _select_solver()[1] is None:
        raise Phase5HGateError("Gurobi is unavailable before the diagnostic branch.")
    install_terminal_validation_extension()
    scratch = _resolve(phase["scratch_root"])
    scratch.mkdir(parents=True, exist_ok=True)
    zero = {configuration: 0.0 for configuration in CONFIGURATIONS}

    baseline_artifacts, baseline_status = _stage_artifacts(
        "phase5h_explicit_benchmark", phase["validation_periods"], phase5g,
        parent, phase4, terminal_target, zero, zero,
    )
    baseline_pools = source_service_pools(baseline_artifacts, phase["validation_periods"], phase5g_overlap)
    pool_totals = _pool_totals(baseline_pools)
    energy_anchors = _primary_anchors(source_rows)
    baseline_totals = _actual_totals(baseline_artifacts, phase["validation_periods"])
    baseline_el_errors = {
        c: abs(baseline_totals[(c, "electricity")] / energy_anchors[(c, "electricity")] - 1.0)
        for c in ("C0", "C1")
    }
    flow_rows = _flow_summary(
        "phase5h_explicit_benchmark", baseline_artifacts, phase["validation_periods"],
        float(phase["ng_combustion_factor_kg_co2_per_gj"]),
    )
    flow_rows.extend(procurement_cost_rows(
        "phase5h_explicit_benchmark", baseline_artifacts, phase["validation_periods"]
    ))
    flow_rows.extend(steam_and_emissions_rows(
        "phase5h_explicit_benchmark", baseline_artifacts, phase["validation_periods"]
    ))
    case_status = list(baseline_status)
    diagnostic_rows: list[dict[str, Any]] = []
    algebraic_rows: list[dict[str, Any]] = []
    ng_overlap = [row for row in phase5g_overlap if row["carrier"] == "natural_gas"]
    baseline_ng_mapped_by_id = {
        str(row["mapping_id"]): float(row["mapped_explicit_model_pj_y"])
        for row in baseline_pools if row["carrier"] == "natural_gas"
    }
    baseline_source_exceedances = component_exceedances(
        [row for row in baseline_pools if row["carrier"] == "natural_gas"],
        float(phase["component_exceedance_tolerance_pj"]),
    )
    overlap_checks = [{
        "check_id": "four_families_present", "status": "pass",
        "observed": ";".join(sorted({row["family"] for row in overlap_rows})),
    }, {
        "check_id": "steam_maximum_established", "status": "fail",
        "observed": steam_gate["decision"],
    }, {
        "check_id": "fresh_heldout_excludes_previously_opened", "status": "pass",
        "observed": heldout_sha,
    }, {
        "check_id": "explicit_benchmark_component_compatibility", "status": "caveat",
        "observed": ";".join(row["mapping_id"] for row in baseline_source_exceedances),
        "notes": "Pre-existing source-row mismatch is reported but is not attributed to a residual candidate unless that candidate enlarges it.",
    }]

    for alpha in candidate_percentages():
        electricity = {
            BUILDER_CONFIGURATION[c]: alpha * pool_totals[(c, "electricity")]
            / (HOURS_PER_YEAR * PJ_PER_MWH)
            for c in ("C0", "C1")
        }
        stage = f"phase5h_electricity_{int(round(alpha * 100)):02d}pct"
        artifacts, status = _stage_artifacts(
            stage, phase["validation_periods"], phase5g, parent, phase4,
            terminal_target, electricity, zero,
        )
        case_status.extend(status)
        flow_rows.extend(_flow_summary(
            stage, artifacts, phase["validation_periods"],
            float(phase["ng_combustion_factor_kg_co2_per_gj"]),
        ))
        flow_rows.extend(procurement_cost_rows(
            stage, artifacts, phase["validation_periods"]
        ))
        flow_rows.extend(steam_and_emissions_rows(
            stage, artifacts, phase["validation_periods"]
        ))
        row, grids = conditional_residual_scores(
            stage, artifacts, phase["validation_periods"], source_rows,
            ng_overlap, alpha, float(phase["component_exceedance_tolerance_pj"]),
            float(phase["ng_combustion_factor_kg_co2_per_gj"]),
            baseline_ng_mapped_by_id,
        )
        actual = _actual_totals(artifacts, phase["validation_periods"])
        el_errors = {
            c: abs(actual[(c, "electricity")] / energy_anchors[(c, "electricity")] - 1.0)
            for c in ("C0", "C1")
        }
        row.update({
            "electricity_improves_both": all(el_errors[c] < baseline_el_errors[c] - 1e-12 for c in ("C0", "C1")),
            "steam_share": "", "steam_gate_status": "blocked_no_defensible_maximum",
            "four_residual_candidate_eligible": False,
        })
        if not row["electricity_improves_both"]:
            row["eligible_three_family_diagnostic"] = False
        diagnostic_rows.append(row)
        algebraic_rows.extend(grids)

    if sum(int(row["model_count"]) for row in case_status) != 560:
        raise Phase5HGateError("Fail-closed diagnostic branch must contain 56 + 504 models.")
    return _persist(
        config_file, config, phase, steam_gate, heldout_sha, baseline_pools,
        case_status, flow_rows, diagnostic_rows, algebraic_rows, overlap_checks, started,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()
    print(json.dumps(run_phase5h(args.config), indent=2))


if __name__ == "__main__":
    main()
