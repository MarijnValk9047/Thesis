"""Phase 5K final user-authorized represented-boundary freeze gate."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_phase4_terminal_inventory_equivalence import _artifact
from .s4_4c5p_phase5b_c0_export_sensitivity import _git_head, _read_csv, _select_solver, _sha256, install_terminal_validation_extension
from .s4_4c5p_phase5e_source_backed_anchor_closure import load_source_contract
from .s4_4c5p_phase5g_final_deterministic_freeze import (
    BUILDER_CONFIGURATION,
    CONFIGURATIONS,
    _actual_totals,
    _anchor_rows,
    _dependencies,
    _flow_summary,
    _hsm_checks,
    _physical_checks,
    _primary_anchors,
    _stage_artifacts,
    load_config as load_phase5g_config,
    load_overlap_contract,
    validate_overlap_against_source,
)
from .s4_4c5p_phase5h_four_residual_effect_gate import (
    _scope1_anchors,
    held_out_contract,
    procurement_cost_rows,
    steam_and_emissions_rows,
    weighted_annual_equivalent,
)
from .s4_4c5p_phase5i_electricity_only_heldout_freeze import (
    _payload_sha256,
    _portable,
    _resolve,
    _write_csv,
    _write_json,
    component_checks,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_c5_phase5k_final_user_authorized_boundary_freeze_v1_20260729"
CONFIG_PATH = REPO_ROOT / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase5k_final_user_authorized_boundary_freeze.yaml"
CLASSIFICATION = "user_authorized_represented_boundary_development_abstraction"
WAG_FIELDS = {"BFG": "BFG_generated_mwh", "COG": "COG_generated_mwh", "BOFG": "BOFG_generated_mwh"}


class Phase5KGateError(RuntimeError):
    pass


def load_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    phase = payload.get("phase5k")
    if payload.get("run_id") != RUN_ID or payload.get("output_policy") != "minimal" or not isinstance(phase, Mapping):
        raise Phase5KGateError("Phase-5K identity or output policy changed.")
    policy = phase.get("policy", {})
    required_true = (
        "user_authorized_methodological_flexibility",
        "c0_uniform_wag_fallback_active",
        "common_absolute_ng_service_across_configurations",
        "common_absolute_co2_residual_across_configurations",
        "residual_co2_reporting_only",
        "flare_is_reporting_warning_not_hard_freeze_gate",
    )
    prohibited = (
        "c1_wag_yields_changed",
        "residual_co2_in_cost_or_ets",
        "residual_steam_active",
        "export_allowed",
        "legacy_ng_bridges_active",
        "hsm_policy_changed",
        "production_physics_changed",
        "adaptive_parameter_sweep_allowed",
        "heldout_reselection_allowed",
    )
    if not all(bool(policy.get(key)) for key in required_true) or any(bool(policy.get(key)) for key in prohibited):
        raise Phase5KGateError("Phase-5K bounded policy changed.")
    if float(phase["common_ng_residual_pj_y"]) != 7.0 or float(phase["predeclared_common_co2_mt_y"]) != 2.0:
        raise Phase5KGateError("The user-authorized common residual quantities changed.")
    return payload


def load_wag_audit_contract(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_csv(Path(path))
    if len(rows) != 6 or {(row["configuration"], row["carrier"]) for row in rows} != {
        (configuration, carrier) for configuration in ("C0", "C1") for carrier in WAG_FIELDS
    }:
        raise Phase5KGateError("The carrier-specific WAG audit contract must contain six unique rows.")
    for row in rows:
        for field in ("mer_source_production_pj_y", "current_yield", "documented_range_low", "documented_range_high", "selected_yield", "selected_multiplier"):
            row[field] = float(row[field])
        if not row["documented_range_low"] <= row["selected_yield"] <= row["documented_range_high"]:
            raise Phase5KGateError("A selected WAG yield lies outside its documented development range.")
        expected = 0.95 if row["configuration"] == "C0" else 1.0
        if not math.isclose(row["selected_multiplier"], expected, abs_tol=1e-12):
            raise Phase5KGateError("The C0-only fixed WAG fallback changed.")
        if not math.isclose(row["selected_yield"], row["current_yield"] * expected, abs_tol=1e-12):
            raise Phase5KGateError("A selected WAG yield does not match its predeclared multiplier.")
    return rows


def load_final_contract(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_csv(Path(path))
    if len(rows) != 8:
        raise Phase5KGateError("The final boundary contract requires C0/C1 rows for four residual families.")
    for row in rows:
        row["annual_quantity"] = float(row["annual_quantity"])
        row["hourly_quantity"] = float(row["hourly_quantity"])
    for configuration in ("C0", "C1"):
        by_family = {row["residual_family"]: row for row in rows if row["configuration"] == configuration}
        if set(by_family) != {"electricity", "natural_gas", "residual_steam", "residual_direct_co2"}:
            raise Phase5KGateError("Every configuration needs all four boundary rows.")
        electricity = by_family["electricity"]
        ng = by_family["natural_gas"]
        steam = by_family["residual_steam"]
        co2 = by_family["residual_direct_co2"]
        if float(electricity["selected_share"]) != 0.9:
            raise Phase5KGateError("The frozen electricity share must remain 90 percent.")
        if not math.isclose(ng["annual_quantity"], 7.0, abs_tol=1e-12) or not math.isclose(
            ng["hourly_quantity"], 7.0 / (8760.0 * 3.6e-6), abs_tol=1e-12
        ):
            raise Phase5KGateError("The common 7-PJ/y NG service identity failed.")
        if steam["annual_quantity"] != 0.0 or steam["hourly_quantity"] != 0.0:
            raise Phase5KGateError("Residual steam must remain zero.")
        if not math.isclose(co2["annual_quantity"], 2.0, abs_tol=1e-12) or not math.isclose(
            co2["hourly_quantity"], 2_000_000.0 / 8760.0, abs_tol=1e-12
        ):
            raise Phase5KGateError("The common residual-CO2 identity failed.")
    return rows


def boundary_maps(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    electricity: dict[str, float] = {}
    ng: dict[str, float] = {}
    co2: dict[str, float] = {}
    for row in rows:
        builder = BUILDER_CONFIGURATION[str(row["configuration"])]
        family = str(row["residual_family"])
        if family == "electricity":
            electricity[builder] = float(row["hourly_quantity"])
        elif family == "natural_gas":
            ng[builder] = float(row["hourly_quantity"])
        elif family == "residual_direct_co2":
            co2[builder] = float(row["hourly_quantity"])
    if set(electricity) != set(CONFIGURATIONS) or set(ng) != set(CONFIGURATIONS) or set(co2) != set(CONFIGURATIONS):
        raise Phase5KGateError("Boundary maps are incomplete.")
    return electricity, ng, co2


def wag_yield_overrides(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        if row["configuration"] == "C0":
            result.setdefault(BUILDER_CONFIGURATION["C0"], {})[str(row["carrier"])] = float(row["selected_yield"])
    return result


def select_common_co2_increment(
    fuel_co2_mt_y: Mapping[str, float], anchors_mt_y: Mapping[str, float], grid_mt_y: Iterable[float]
) -> tuple[float, list[dict[str, Any]]]:
    scores: list[dict[str, Any]] = []
    for candidate in grid_mt_y:
        q = float(candidate)
        errors = {configuration: abs((fuel_co2_mt_y[configuration] + q) / anchors_mt_y[configuration] - 1.0) for configuration in ("C0", "C1")}
        scores.append({
            "candidate_common_residual_co2_mt_y": q,
            "C0_total_mt_y": fuel_co2_mt_y["C0"] + q,
            "C1_total_mt_y": fuel_co2_mt_y["C1"] + q,
            "C0_absolute_relative_error": errors["C0"],
            "C1_absolute_relative_error": errors["C1"],
            "maximum_absolute_relative_error": max(errors.values()),
            "mean_absolute_relative_error": sum(errors.values()) / 2.0,
        })
    winner = min(scores, key=lambda row: (row["maximum_absolute_relative_error"], row["mean_absolute_relative_error"], row["candidate_common_residual_co2_mt_y"]))
    return float(winner["candidate_common_residual_co2_mt_y"]), scores


def _load_phase5j_artifacts(root: Path, periods: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    artifacts: dict[str, Mapping[str, Any]] = {}
    for period in periods:
        period_id = str(period["period_id"])
        directory = root / f"phase5g__phase5j_heldout__{period_id.replace('-', '_')}"
        if not (directory / "run_summary.json").exists():
            raise Phase5KGateError(f"Complete Phase-5J carrier-audit cache is missing: {directory.name}")
        artifacts[period_id] = _artifact(directory)
    return artifacts


def carrier_audit_rows(
    stage: str, artifacts: Mapping[str, Mapping[str, Any]], periods: Iterable[Mapping[str, Any]],
    wag_contract: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    periods = tuple(periods)
    source = {(str(row["configuration"]), str(row["carrier"])): float(row["mer_source_production_pj_y"]) for row in wag_contract}
    rows: list[dict[str, Any]] = []
    for configuration in ("C0", "C1"):
        total_model = 0.0
        total_source = 0.0
        for carrier, field in WAG_FIELDS.items():
            model = weighted_annual_equivalent(artifacts, periods, configuration, field, 3.6e-6)
            anchor = source[(configuration, carrier)]
            total_model += model
            total_source += anchor
            rows.append({"stage": stage, "configuration": configuration, "carrier": carrier, "model_production_pj_y": model, "source_production_pj_y": anchor, "signed_relative_error": model / anchor - 1.0})
        rows.append({"stage": stage, "configuration": configuration, "carrier": "TOTAL", "model_production_pj_y": total_model, "source_production_pj_y": total_source, "signed_relative_error": total_model / total_source - 1.0})
    return rows


def _flow_value(rows: Iterable[Mapping[str, Any]], configuration: str, metric: str) -> float:
    matches = [float(row["value"]) for row in rows if row.get("configuration") == configuration and row.get("metric") == metric]
    if len(matches) != 1:
        raise Phase5KGateError(f"Expected one {configuration} {metric} flow row.")
    return matches[0]


def _fuel_co2(
    artifacts: Mapping[str, Mapping[str, Any]], periods: Iterable[Mapping[str, Any]], ng_factor: float,
) -> dict[str, float]:
    periods = tuple(periods)
    result: dict[str, float] = {}
    for configuration in ("C0", "C1"):
        wag = weighted_annual_equivalent(artifacts, periods, configuration, "WAG_explicit_combustion_co2_t", 1.0 / 1_000_000.0)
        explicit_ng = weighted_annual_equivalent(artifacts, periods, configuration, "explicit_NG_combustion_co2_t", 1.0 / 1_000_000.0)
        # The builder's explicit-NG expression already uses total named NG
        # procurement, including the common site baseload. Do not add the
        # separately reported first-order baseload proxy a second time.
        result[configuration] = wag + explicit_ng
    return result


def _phase5k_checks(
    stage: str, artifacts: Mapping[str, Mapping[str, Any]], periods: Iterable[Mapping[str, Any]],
    flow_rows: list[dict[str, Any]], carrier_rows: list[dict[str, Any]], co2_selected: float,
    co2_anchors: Mapping[str, float], phase: Mapping[str, Any], tolerance: float,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for period_id, artifact in artifacts.items():
        for configuration in ("C0", "C1"):
            builder = BUILDER_CONFIGURATION[configuration]
            hourly = [row for row in artifact["hourly"] if row.get("configuration_id") == builder]
            steam = max(abs(float(row.get("residual_steam_15bar_demand_t") or 0.0)) for row in hourly)
            co2_spread = max(abs(float(row.get("residual_unmodelled_direct_co2_t") or 0.0) - co2_selected * 1_000_000.0 / 8760.0) for row in hourly)
            checks.extend([
                {"stage": stage, "period_id": period_id, "configuration": configuration, "check_id": "residual_steam_zero", "actual": steam, "limit": tolerance, "status": "pass" if steam <= tolerance else "fail"},
                {"stage": stage, "period_id": period_id, "configuration": configuration, "check_id": "common_residual_co2_constant", "actual": co2_spread, "limit": tolerance, "status": "pass" if co2_spread <= tolerance else "fail"},
            ])
    totals = {row["configuration"]: row for row in carrier_rows if row["carrier"] == "TOTAL"}
    for configuration in ("C0", "C1"):
        wag_error = abs(float(totals[configuration]["signed_relative_error"]))
        wag_limit = 0.05 if configuration == "C0" else 0.02
        electricity_error = abs(_flow_value(flow_rows, configuration, "gross_electricity_mwh") / (13.7 if configuration == "C0" else 17.8) - 1.0)
        ng_total = _flow_value(flow_rows, configuration, "total_named_ng_procurement_mwh")
        ng_anchor = 12.5 if configuration == "C0" else 46.7
        represented_co2 = _flow_value(flow_rows, configuration, "WAG_explicit_combustion_co2") + _flow_value(flow_rows, configuration, "explicit_NG_combustion_co2") + co2_selected
        co2_error = abs(represented_co2 / co2_anchors[configuration] - 1.0)
        checks.extend([
            {"stage": stage, "configuration": configuration, "check_id": "direct_wag_total_bounded", "actual": wag_error, "limit": wag_limit, "status": "pass" if wag_error <= wag_limit else "fail"},
            {"stage": stage, "configuration": configuration, "check_id": "electricity_anchor_error_bounded", "actual": electricity_error, "limit": float(phase["electricity_anchor_error_limits"][configuration]), "status": "pass" if electricity_error <= float(phase["electricity_anchor_error_limits"][configuration]) else "fail"},
            {"stage": stage, "configuration": configuration, "check_id": "ng_anchor_materially_improved", "actual": abs(ng_total / ng_anchor - 1.0), "limit": 0.15, "status": "pass" if abs(ng_total / ng_anchor - 1.0) <= 0.15 else "fail"},
            {"stage": stage, "configuration": configuration, "check_id": "co2_anchor_error_bounded", "actual": co2_error, "limit": float(phase["co2_anchor_error_limit"]), "status": "pass" if co2_error <= float(phase["co2_anchor_error_limit"]) else "fail"},
            {"stage": stage, "configuration": configuration, "check_id": "wag_flare_reporting_warning", "actual": _flow_value(flow_rows, configuration, "WAG_flared"), "limit": float(phase["flare_reporting_reference_pj_y"][configuration]), "status": "pass", "notes": "Reporting warning only under the prospectively revised Phase-5K freeze scope."},
        ])
    return checks


def _run_stage(
    stage: str, periods: list[dict[str, Any]], phase5g: dict[str, Any], parent: Mapping[str, Any],
    phase4: Mapping[str, Any], terminal_target: Mapping[str, Any], electricity: Mapping[str, float],
    ng: Mapping[str, float], co2: Mapping[str, float], yields: Mapping[str, Mapping[str, float]],
    phase: Mapping[str, Any], source_rows: list[dict[str, Any]], overlap_rows: list[dict[str, Any]],
    wag_contract: list[dict[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    artifacts, case_status = _stage_artifacts(
        stage, periods, phase5g, parent, phase4, terminal_target, electricity, ng,
        extra_overrides={
            "site_residual_steam_t_h_by_configuration": {configuration: 0.0 for configuration in CONFIGURATIONS},
            "site_residual_direct_co2_t_h_by_configuration": dict(co2),
            "wag_generation_yield_overrides_by_configuration": {key: dict(value) for key, value in yields.items()},
            "phase5k_user_authorized_boundary_active": True,
        },
    )
    tolerance = float(phase["physical_balance_tolerance_mwh"])
    checks = _physical_checks(stage, artifacts, electricity, ng, tolerance)
    checks += _hsm_checks(stage, artifacts, phase5g, tolerance)
    component_rows, component_gate = component_checks(
        artifacts, periods, overlap_rows, _resolve(phase["component_reference"]),
        float(phase["component_exceedance_tolerance_pj"]),
    )
    flows = _flow_summary(stage, artifacts, periods, float(phase["ng_combustion_factor_kg_co2_per_gj"]))
    flows += procurement_cost_rows(stage, artifacts, periods)
    flows += steam_and_emissions_rows(stage, artifacts, periods)
    carriers = carrier_audit_rows(stage, artifacts, periods, wag_contract)
    checks += _phase5k_checks(stage, artifacts, periods, flows, carriers, float(phase["predeclared_common_co2_mt_y"]), _scope1_anchors(source_rows), phase, tolerance)
    return artifacts, case_status, checks, component_rows, component_gate, flows + carriers


def _persist(
    config_file: Path, config: Mapping[str, Any], phase: Mapping[str, Any], input_paths: list[Path],
    contract_rows: list[dict[str, Any]], baseline_carriers: list[dict[str, Any]], validation_payload: tuple,
    heldout_payload: tuple, co2_grid: list[dict[str, Any]], checkpoint: Mapping[str, Any], started: float,
) -> dict[str, Any]:
    output = _resolve(config["output_root"])
    if output.exists():
        raise Phase5KGateError("Phase-5K governed output root already exists.")
    output.mkdir(parents=True)
    (output / "resolved_config.yaml").write_text(yaml.safe_dump(dict(config), sort_keys=False), encoding="utf-8")
    validation_artifacts, validation_status, validation_checks, validation_components, validation_component_gate, validation_flows = validation_payload
    heldout_artifacts, heldout_status, heldout_checks, heldout_components, heldout_component_gate, heldout_flows = heldout_payload
    _write_csv(output / "contract_verification.csv", contract_rows)
    _write_csv(output / "wag_carrier_source_audit.csv", baseline_carriers + [row for row in validation_flows + heldout_flows if row.get("carrier")])
    _write_csv(output / "case_status.csv", validation_status + heldout_status)
    _write_csv(output / "physical_and_external_validity_checks.csv", validation_checks + heldout_checks)
    _write_csv(output / "component_overlap_checks.csv", validation_component_gate + heldout_component_gate)
    _write_csv(output / "component_overlap_waterfall.csv", validation_components + heldout_components)
    _write_csv(output / "flow_and_anchor_summary.csv", [row for row in validation_flows + heldout_flows if not row.get("carrier")])
    _write_csv(output / "common_residual_co2_grid.csv", co2_grid)
    _write_json(output / "checkpoint_decision.json", checkpoint)
    manifest = [{"path": _portable(path), "sha256": _sha256(path), "size_bytes": path.stat().st_size} for path in input_paths]
    _write_json(output / "input_manifest.json", {"files": manifest})
    fingerprints = {
        "git_head": _git_head(),
        "model_fingerprint_sha256": _payload_sha256({row["path"]: row["sha256"] for row in manifest if row["path"].endswith(".py")}),
        "input_contract_fingerprint_sha256": _payload_sha256({row["path"]: row["sha256"] for row in manifest if not row["path"].endswith(".py")}),
        "final_boundary_contract_sha256": _sha256(_resolve(phase["final_boundary_contract"])),
        "fresh_heldout_contract_sha256": _sha256(_resolve(phase["held_out_contract"])),
    }
    _write_json(output / "fingerprint_manifest.json", fingerprints)
    _write_json(output / "code_version.json", {"git_head": _git_head(), "model_fingerprint_sha256": fingerprints["model_fingerprint_sha256"]})
    _write_json(output / "registry_entry.json", {"run_id": RUN_ID, "run_class": config["run_class"], "lineage_role": config["lineage_role"], "output_policy": config["output_policy"], "decision": checkpoint["decision"]})
    summary = {**dict(checkpoint), "runtime_seconds": time.perf_counter() - started, "fingerprints": fingerprints}
    _write_json(output / "run_summary.json", summary)
    (output / "README.md").write_text(f"# Phase 5K final represented-boundary freeze\n\nDecision: `{checkpoint['decision']}`.\n", encoding="utf-8")
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\nThe C0 WAG fallback, 90% electricity load, common 7-PJ/y NG service and common residual direct-CO2 term are user-authorized development abstractions. The result is not a full-site digital twin or ETS-ready inventory. Flare is reported as external-validity evidence rather than a hard freeze blocker.\n",
        encoding="utf-8",
    )
    return summary


def run_phase5k(config_path: str | Path = CONFIG_PATH, *, resume_from_complete_cache: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    phase = config["phase5k"]
    if _git_head() != str(phase["expected_parent_head"]):
        raise Phase5KGateError("Phase-5K requires the preserved campaign parent HEAD.")
    if _select_solver()[1] is None:
        raise Phase5KGateError("Gurobi is unavailable before Phase-5K execution.")
    wag_path = _resolve(phase["wag_carrier_audit_contract"])
    boundary_path = _resolve(phase["final_boundary_contract"])
    heldout_path = _resolve(phase["held_out_contract"])
    wag_contract = load_wag_audit_contract(wag_path)
    contract_rows = load_final_contract(boundary_path)
    electricity, ng, co2 = boundary_maps(contract_rows)
    yields = wag_yield_overrides(wag_contract)
    heldout_periods, _ = held_out_contract(heldout_path)
    if len(heldout_periods) != int(phase["expected_period_count"]):
        raise Phase5KGateError("Fresh held-out period count changed.")
    phase5j_periods, _ = held_out_contract(_resolve(phase["phase5j_held_out_contract"]))
    old_origins = {row["frozen_forecast_start_origin_utc"] for row in phase5j_periods}
    if old_origins.intersection(row["frozen_forecast_start_origin_utc"] for row in heldout_periods):
        raise Phase5KGateError("Phase-5K fresh held-out origins overlap Phase-5J.")
    phase5g = dict(load_phase5g_config(_resolve(phase["phase5g_config"]))["phase5g"])
    validation_periods = [dict(row) for row in phase5g["validation_periods"]]
    phase5g["scratch_root"] = phase["scratch_root"]
    scratch = _resolve(phase["scratch_root"])
    if scratch.exists() and not resume_from_complete_cache:
        raise Phase5KGateError("Phase-5K scratch exists; use explicit complete-cache resume.")
    scratch.mkdir(parents=True, exist_ok=True)
    parent, phase4, terminal_target = _dependencies(phase5g)
    install_terminal_validation_extension()
    source_rows = load_source_contract(_resolve(phase["source_contract"]))
    overlap_rows = load_overlap_contract(_resolve(phase["phase5g_overlap_contract"]))
    validate_overlap_against_source(overlap_rows, source_rows)
    baseline_artifacts = _load_phase5j_artifacts(_resolve(phase["phase5j_case_cache"]), phase5j_periods)
    baseline_carriers = carrier_audit_rows("phase5j_fresh_heldout_baseline", baseline_artifacts, phase5j_periods, wag_contract)
    validation = _run_stage("phase5k_validation", validation_periods, phase5g, parent, phase4, terminal_target, electricity, ng, co2, yields, phase, source_rows, overlap_rows, wag_contract)
    fuel = _fuel_co2(validation[0], validation_periods, float(phase["ng_combustion_factor_kg_co2_per_gj"]))
    selected, co2_grid = select_common_co2_increment(fuel, _scope1_anchors(source_rows), phase["common_co2_grid_mt_y"])
    validation_pass = all(row["status"] == "pass" for row in validation[1] + validation[2] + validation[4])
    if not math.isclose(selected, float(phase["predeclared_common_co2_mt_y"]), abs_tol=1e-12):
        validation_pass = False
    if not validation_pass:
        raise Phase5KGateError("Phase-5K validation failed before fresh held-out opening.")
    heldout = _run_stage("phase5k_fresh_heldout", heldout_periods, phase5g, parent, phase4, terminal_target, electricity, ng, co2, yields, phase, source_rows, overlap_rows, wag_contract)
    heldout_pass = all(row["status"] == "pass" for row in heldout[1] + heldout[2] + heldout[4])
    validation_models = sum(int(row["model_count"]) for row in validation[1])
    heldout_models = sum(int(row["model_count"]) for row in heldout[1])
    passed = validation_pass and heldout_pass and validation_models == int(phase["expected_validation_models"]) and heldout_models == int(phase["expected_heldout_models"])
    checkpoint = {
        "run_id": RUN_ID,
        "decision": phase["decision_on_pass"] if passed else phase["decision_on_fail"],
        "status": "pass" if passed else "fail",
        "validation_models": validation_models,
        "fresh_heldout_models": heldout_models,
        "contract_promoted": passed,
        "selected_electricity_share": 0.9,
        "c0_wag_yield_multiplier": 0.95,
        "c1_wag_yield_multiplier": 1.0,
        "common_site_ng_service_pj_y": 7.0,
        "selected_common_residual_co2_mt_y": selected,
        "residual_steam": 0.0,
        "fresh_heldout_opened_once": True,
        "reselection_after_heldout": False,
        "phase6_authorization": phase["next_gate_on_pass"] if passed else "blocked",
        "scope": "user_authorized_represented_boundary_not_full_site_digital_twin_not_ets_ready",
        "classification": CLASSIFICATION,
        "failure_count": 0 if passed else 1,
    }
    input_paths = [
        config_file, wag_path, boundary_path, heldout_path, _resolve(phase["source_contract"]),
        _resolve(phase["phase5g_overlap_contract"]), Path(__file__).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_phase5g_final_deterministic_freeze.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
    ]
    return _persist(config_file, config, phase, input_paths, contract_rows, baseline_carriers, validation, heldout, co2_grid, checkpoint, started)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--resume-from-complete-cache", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_phase5k(args.config, resume_from_complete_cache=args.resume_from_complete_cache), indent=2))


if __name__ == "__main__":
    main()
