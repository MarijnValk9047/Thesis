"""Governed Phase-5B C0 no-export/export DEVELOPMENT sensitivity."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_c0_athanasiadis_sale_sensitivity import (
    _validate_containment_records,
    cross_policy_state_guardrails,
    electricity_guardrails,
    policy_overrides,
    trajectory_metrics,
)
from .s4_4c5p_phase4_terminal_inventory_equivalence import (
    _case_overrides,
    _terminal_rows,
    check_phase4_config,
    load_phase4_config,
    terminal_state_vector,
)
from . import s4_4c_unified_physical_modelbuilder as physical_modelbuilder
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT, _select_solver
from .validation_tolerance_policy import (
    CONSTRAINT_FAMILY_REGISTRY,
    SOLVER_NUMERICAL_TOLERANCE,
    TERMINAL_STATE_TOLERANCE_T,
    ValidationRule,
    constraint_family_rule,
    policy_contract,
)


RUN_ID = "steel_c5_phase5b_c0_export_sensitivity_v2_20260727"
CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase5b_c0_export_sensitivity.yaml"
)
EXPECTED_HEAD = "d565ff94a45328750ecee6c2e2818eaa6e6eb616"
EXPECTED_PERIODS = ("validation_2024-02-12", "validation_2024-07-01")
EXPECTED_POLICIES = ("accepted_no_export_comparator", "athanasiadis_sale_enabled")
MATERIAL_THRESHOLD_TWH_E_Y = 0.015014
NG_BREAK_EVEN_EUR_PER_MWH_E = 159.42029
ELECTRICITY_TOLERANCE_MWH = 1e-6
PHASE5B_TERMINAL_VALIDATION_FAMILIES = frozenset({
    "rolling_terminal_inventory_lower_bounds",
    "rolling_terminal_inventory_upper_bounds",
})
PHASE5B_STRICT_VALIDATION_FAMILIES = frozenset({
    "full_site_fixed_ng_component_nonnegative",
    "hsm_source_mix_constraints",
})


class Phase5BExportSensitivityError(RuntimeError):
    pass


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("run_id") != RUN_ID:
        raise Phase5BExportSensitivityError("Unexpected Phase-5B run_id.")
    if config.get("output_policy") != "minimal":
        raise Phase5BExportSensitivityError("Phase 5B requires output_policy=minimal.")
    phase5b = config["phase5b"]
    if phase5b.get("expected_parent_head") != EXPECTED_HEAD:
        raise Phase5BExportSensitivityError("The frozen Phase-5B parent HEAD changed.")
    if tuple(row["period_id"] for row in phase5b["development_periods"]) != EXPECTED_PERIODS:
        raise Phase5BExportSensitivityError("The accepted DEVELOPMENT weeks changed.")
    if tuple(row["policy_id"] for row in phase5b["policies"]) != EXPECTED_POLICIES:
        raise Phase5BExportSensitivityError("The no-export/export policy pair changed.")
    if (
        int(phase5b.get("expected_case_count", -1)) != 4
        or int(phase5b.get("expected_model_count", -1)) != 56
        or int(phase5b.get("replans_per_case", -1)) != 7
        or bool(phase5b.get("held_out_periods_used"))
    ):
        raise Phase5BExportSensitivityError("Phase 5B requires four DEVELOPMENT cases and 56 models.")
    if not math.isclose(
        float(phase5b.get("material_threshold_twh_e_y", math.nan)),
        MATERIAL_THRESHOLD_TWH_E_Y,
        abs_tol=1e-12,
    ):
        raise Phase5BExportSensitivityError("The predeclared material threshold changed.")
    if phase5b.get("validation_tolerance_policy") != policy_contract():
        raise Phase5BExportSensitivityError("The validation-tolerance policy changed.")


def frozen_case_matrix(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_config(config)
    return [
        {
            "case_id": (
                f"phase5b__{period['period_id'].replace('-', '_')}__{policy['policy_id']}"
            ),
            "period_id": period["period_id"],
            "dataset_split": period["dataset_split"],
            "forecast_start_origin_utc": period["frozen_forecast_start_origin_utc"],
            "strategy_id": "governed_dplus4_y_pred",
            "price_field": "y_pred",
            "flat_price_eur_per_mwh": None,
            "perfect_foresight_oracle": False,
            "policy_id": policy["policy_id"],
            "sale_enabled": bool(policy["sale_enabled"]),
            "expected_model_count": 14,
        }
        for period in config["phase5b"]["development_periods"]
        for policy in config["phase5b"]["policies"]
    ]


def _portable(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise Phase5BExportSensitivityError(
            f"Persistent path must be repository-relative: {resolved}"
        ) from exc


def _fingerprintable_overrides(overrides: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {
        "run_id", "lineage_role", "normal_solution_capture",
        "c0_electricity_sale_sensitivity", "phase5b_export_switch",
    }
    return {key: value for key, value in overrides.items() if key not in excluded}


def install_terminal_validation_extension() -> dict[str, Any]:
    """Register validation-only rows for the isolated sale-containment clone.

    The extension uses the canonical terminal-state rule and changes neither a
    physical row nor the frozen base policy identity. It is local to this
    dedicated process and is fingerprinted in the Phase-5B manifest.
    """

    rule = ValidationRule(
        purpose="terminal_or_carried_material_state",
        unit="t",
        tolerance=TERMINAL_STATE_TOLERANCE_T,
        aggregation="terminal_snapshot",
        relaxation_allowed=True,
    )
    strict_rule = ValidationRule(
        purpose="physical_bound_capacity_or_operating_rule",
        unit="model_unit",
        tolerance=SOLVER_NUMERICAL_TOLERANCE,
        aggregation="per_row_solver_numeric",
        relaxation_allowed=False,
    )
    manifest = {
        "scope": "isolated_sale_containment_validation_clone_only",
        "families": sorted(PHASE5B_TERMINAL_VALIDATION_FAMILIES),
        "rule": {
            "purpose": rule.purpose, "unit": rule.unit,
            "tolerance": rule.tolerance, "aggregation": rule.aggregation,
            "relaxation_allowed": rule.relaxation_allowed,
        },
        "strict_families": sorted(PHASE5B_STRICT_VALIDATION_FAMILIES),
        "strict_rule": {
            "purpose": strict_rule.purpose,
            "unit": strict_rule.unit,
            "tolerance": strict_rule.tolerance,
            "aggregation": strict_rule.aggregation,
            "relaxation_allowed": strict_rule.relaxation_allowed,
        },
        "base_policy": policy_contract(),
    }
    for family in PHASE5B_TERMINAL_VALIDATION_FAMILIES:
        existing = CONSTRAINT_FAMILY_REGISTRY.get(family)
        if existing is not None and existing != rule:
            raise Phase5BExportSensitivityError(
                f"Conflicting validation rule already registered for {family}."
            )
        CONSTRAINT_FAMILY_REGISTRY[family] = rule
    for family in PHASE5B_STRICT_VALIDATION_FAMILIES:
        existing = CONSTRAINT_FAMILY_REGISTRY.get(family)
        if existing is not None and existing != strict_rule:
            raise Phase5BExportSensitivityError(
                f"Conflicting validation rule already registered for {family}."
            )
        CONSTRAINT_FAMILY_REGISTRY[family] = strict_rule
    # Verify through both import paths used by the containment implementation.
    for family in PHASE5B_TERMINAL_VALIDATION_FAMILIES:
        if constraint_family_rule(family) != rule:
            raise Phase5BExportSensitivityError(
                f"Phase-5B validation extension did not register {family}."
            )
        physical_modelbuilder.constraint_family_rule(family)
    for family in PHASE5B_STRICT_VALIDATION_FAMILIES:
        if constraint_family_rule(family) != strict_rule:
            raise Phase5BExportSensitivityError(
                f"Phase-5B strict validation extension did not register {family}."
            )
        physical_modelbuilder.constraint_family_rule(family)
    return manifest


def _c0_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if row.get("configuration_id") == C0_CONFIGURATION]


def _sum(rows: Iterable[Mapping[str, Any]], field: str) -> float:
    return sum(float(row.get(field) or 0.0) for row in rows)


def _case_metrics(artifact: Mapping[str, Any]) -> dict[str, float]:
    hourly = _c0_rows(artifact["hourly"])
    base = trajectory_metrics(artifact["hourly"], artifact["costs"])
    hours = len(hourly)
    annual = 8760.0 / hours
    base.update(
        {
            "gross_generator_electricity_mwh": _sum(hourly, "total_generator_electricity_mwh"),
            "internal_generator_offset_mwh": _sum(hourly, "total_generator_electricity_mwh")
            - _sum(hourly, "gross_grid_export_mwh"),
            "bfg_generator_fuel_mwh_lhv": _sum(hourly, "BFG_to_vattenfall_mwh"),
            "cog_generator_fuel_mwh_lhv": _sum(hourly, "COG_to_vattenfall_mwh"),
            "bofg_generator_fuel_mwh_lhv": _sum(hourly, "BOFG_to_vattenfall_mwh"),
            "wag_flared_mwh_lhv": _sum(hourly, "WAG_flared"),
            "hsm_route_output_t": _sum(hourly, "C0_HSM_final_product_t"),
            "dsp_route_output_t": _sum(hourly, "C0_DSP_final_product_t"),
            "total_wag_pj_y_annual_equivalent": _sum(hourly, "WAG_generated") * annual * 3.6e-6,
            "wag_electricity_twh_e_y_annual_equivalent": (
                _sum(hourly, "WAG_generator_electricity_mwh") * annual / 1_000_000.0
            ),
            "ng_generator_pj_y_annual_equivalent": (
                _sum(hourly, "generator_named_ng_mwh") * annual * 3.6e-6
            ),
        }
    )
    return base


def _hourly_rows(case: Mapping[str, Any], artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = (
        "replan_index", "executed_hour_index", "hour_index",
        "electricity_sale_price_eur_per_mwh", "gross_total_electricity_mwh",
        "gross_grid_import_mwh", "gross_grid_export_mwh", "net_grid_exchange_mwh",
        "total_generator_electricity_mwh", "WAG_generator_electricity_mwh",
        "NG_generator_electricity_mwh", "BFG_to_vattenfall_mwh",
        "COG_to_vattenfall_mwh", "BOFG_to_vattenfall_mwh",
        "generator_named_ng_mwh", "WAG_generated", "WAG_used", "WAG_flared",
        "electricity_export_revenue_eur", "gross_site_electricity_identity_residual_mwh",
    )
    return [
        {
            "case_id": case["case_id"], "period_id": case["period_id"],
            "policy_id": case["policy_id"],
            **{field: row.get(field, "") for field in fields},
        }
        for row in _c0_rows(artifact["hourly"])
    ]


def _pair_guardrails(
    period_id: str,
    comparator: Mapping[str, Any],
    sale: Mapping[str, Any],
    comparator_metrics: Mapping[str, float],
    sale_metrics: Mapping[str, float],
) -> list[dict[str, Any]]:
    rows = [
        {"period_id": period_id, "guardrail": "gross_grid_import_weakly_nonincreasing",
         "status": "pass" if sale_metrics["gross_grid_import_mwh"] <= comparator_metrics["gross_grid_import_mwh"] + ELECTRICITY_TOLERANCE_MWH else "fail",
         "raw_residual": max(0.0, sale_metrics["gross_grid_import_mwh"] - comparator_metrics["gross_grid_import_mwh"])},
        {"period_id": period_id, "guardrail": "total_wag_within_10pct_of_54_pj_y",
         "status": "pass" if abs(sale_metrics["total_wag_pj_y_annual_equivalent"] - 54.0) <= 5.4 else "fail",
         "raw_residual": abs(sale_metrics["total_wag_pj_y_annual_equivalent"] - 54.0)},
    ]
    for row in cross_policy_state_guardrails(
        comparator["execution"], sale["execution"], comparator["handoff"],
        sale["handoff"], comparator["progress"], sale["progress"],
    ):
        rows.append({"period_id": period_id, **row})

    comp_hourly = {
        int(row["executed_hour_index"]): row for row in _c0_rows(comparator["hourly"])
    }
    below_break_even_ng_increase = 0.0
    for row in _c0_rows(sale["hourly"]):
        price = float(row.get("electricity_sale_price_eur_per_mwh") or 0.0)
        if price < NG_BREAK_EVEN_EUR_PER_MWH_E:
            comp = comp_hourly[int(row["executed_hour_index"])]
            below_break_even_ng_increase = max(
                below_break_even_ng_increase,
                float(row.get("NG_generator_electricity_mwh") or 0.0)
                - float(comp.get("NG_generator_electricity_mwh") or 0.0),
            )
    rows.append(
        {"period_id": period_id, "guardrail": "no_ng_generation_increase_below_breakeven",
         "status": "pass" if below_break_even_ng_increase <= ELECTRICITY_TOLERANCE_MWH else "fail",
         "raw_residual": max(0.0, below_break_even_ng_increase),
         "break_even_eur_per_mwh_e": NG_BREAK_EVEN_EUR_PER_MWH_E}
    )
    return rows


def run_phase5b(config_path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    validate_config(config)
    if _git_head() != EXPECTED_HEAD:
        raise Phase5BExportSensitivityError("Phase 5B requires the frozen Phase-4 HEAD.")
    phase5b = config["phase5b"]
    phase4_path = _resolve(phase5b["phase4_config"])
    phase4_config = load_phase4_config(phase4_path)
    check_phase4_config(phase4_config)
    phase4_summary = _read_json(_resolve(phase5b["phase4_summary"]))
    if phase4_summary.get("status") != "pass" or phase4_summary.get(
        "maximum_terminal_band_excess_t"
    ) != 0.0:
        raise Phase5BExportSensitivityError("The accepted Phase-4 parent is not a clean PASS.")
    phase5a = _read_json(_resolve(phase5b["phase5a_candidate_decision"]))
    if phase5a.get("decision") != "continue_to_phase5b" or phase5a.get("go_phase5b") is not True:
        raise Phase5BExportSensitivityError("Phase 5A did not authorize this pair.")
    target_contract = _read_json(_resolve(phase5b["phase4_target_contract"]))
    targets = {row["period_id"]: row for row in target_contract["targets"]}
    if tuple(targets) != EXPECTED_PERIODS:
        raise Phase5BExportSensitivityError("The accepted Phase-4 target periods changed.")

    output_root = _resolve(config["output_root"])
    scratch_root = _resolve(phase5b["scratch_root"])
    if output_root.exists() or scratch_root.exists():
        raise Phase5BExportSensitivityError("Governed output or scratch root already exists.")
    _, solver = _select_solver()
    if solver is None:
        raise Phase5BExportSensitivityError("Gurobi is unavailable before the first solve.")
    validation_extension = install_terminal_validation_extension()
    output_root.mkdir(parents=True)
    scratch_root.mkdir(parents=True)
    load_runtime = time.perf_counter() - started
    (output_root / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    implementation_files = (
        config_file,
        Path(__file__).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/run_s4_4c5p_phase5b_c0_export_sensitivity.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_phase4_terminal_inventory_equivalence.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_c0_athanasiadis_sale_sensitivity.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/validation_tolerance_policy.py",
    )
    implementation_manifest = [
        {"path": _portable(path), "sha256": _sha256(path)}
        for path in implementation_files
    ]
    implementation_sha256 = _payload_sha256(implementation_manifest)

    cases = frozen_case_matrix(config)
    artifacts: dict[tuple[str, str], dict[str, Any]] = {}
    statuses: list[dict[str, Any]] = []
    solver_rows: list[dict[str, Any]] = []
    guardrails: list[dict[str, Any]] = []
    terminal_rows: list[dict[str, Any]] = []
    hourly_rows: list[dict[str, Any]] = []
    override_fingerprints: dict[tuple[str, str], str] = {}
    build_runtime = 0.0

    for case in cases:
        period_target = targets[case["period_id"]]
        band = period_target["terminal_band"]
        capture = scratch_root / f"capture__{case['period_id'].replace('-', '_')}"
        provenance = {
            "schema_version": "steel_phase5b_no_export_capture_v1",
            "period_id": case["period_id"], "expected_parent_head": EXPECTED_HEAD,
            "implementation_sha256": implementation_sha256,
            "phase4_terminal_band_fingerprint_sha256": period_target[
                "terminal_band_fingerprint_sha256"
            ],
        }
        overrides = _case_overrides(
            phase4_config, case, _resolve(phase5b["forecast_run_root"]),
            int(period_target["campaign_terminal_executed_hours"]), band,
        )
        overrides.update({
            "run_id": case["case_id"],
            "lineage_role": "phase5b_c0_export_sensitivity_child",
            "phase2_implementation_sha256": implementation_sha256,
            "phase5b_export_switch": case["sale_enabled"],
        })
        if case["sale_enabled"]:
            sale_policy = policy_overrides(case["policy_id"])["c0_electricity_sale_sensitivity"]
            sale_policy.update({
                "incumbent_capture_directory": str(capture),
                "incumbent_provenance": provenance,
                "containment_oracle_root": str(
                    scratch_root / case["case_id"] / "sale_containment"
                ),
            })
            overrides["c0_electricity_sale_sensitivity"] = sale_policy
        else:
            overrides["normal_solution_capture"] = {
                "enabled": True, "structural_inactive_exclusion_enabled": True,
                "directory": str(capture), "provenance": provenance,
            }
        override_fingerprints[(case["period_id"], case["policy_id"])] = _payload_sha256(
            _fingerprintable_overrides(overrides)
        )
        child_started = time.perf_counter()
        run_closed_loop_feasibility_anchor_reconciliation(
            config_path=_resolve(phase4_config["phase4"]["physical_config"]),
            output_root=scratch_root,
            scenario_overrides=overrides,
        )
        build_runtime += time.perf_counter() - child_started
        directory = scratch_root / case["case_id"]
        artifact = {
            "directory": directory,
            "summary": _read_json(directory / "run_summary.json"),
            "hourly": _read_csv(directory / "executed_hourly.csv"),
            "costs": _read_csv(directory / "executed_procurement_cost_ledger.csv"),
            "models": _read_csv(directory / "rolling_model_metrics.csv"),
            "validation": _read_csv(directory / "validation_checks.csv"),
            "execution": _read_csv(directory / "rolling_execution.csv"),
            "handoff": _read_csv(directory / "inventory_handoff.csv"),
            "progress": _read_csv(directory / "rolling_production_progress_state.csv"),
        }
        artifacts[(case["period_id"], case["policy_id"])] = artifact
        failed_child_checks = [
            row["check_id"] for row in artifact["validation"] if row.get("status") != "pass"
        ]
        model_ok = len(artifact["models"]) == 14 and all(
            row.get("solver_status", "").lower() == "ok"
            and row.get("termination_condition", "").lower() == "optimal"
            for row in artifact["models"]
        )
        statuses.append({
            "case_id": case["case_id"], "period_id": case["period_id"],
            "policy_id": case["policy_id"],
            "status": "pass" if model_ok and not failed_child_checks else "fail",
            "model_count": len(artifact["models"]),
            "failed_child_checks": ";".join(failed_child_checks),
            "cache_directory": _portable(directory),
        })
        solver_rows.extend(
            {"case_id": case["case_id"], "period_id": case["period_id"],
             "policy_id": case["policy_id"], **row}
            for row in artifact["models"]
        )
        guardrails.extend(
            {"case_id": case["case_id"], "period_id": case["period_id"], **row}
            for row in electricity_guardrails(
                artifact["hourly"], sale_enabled=case["sale_enabled"]
            )
        )
        resolved_terminal = _terminal_rows(
            case, terminal_state_vector(artifact), band
        )
        terminal_rows.extend(resolved_terminal)
        guardrails.append({
            "case_id": case["case_id"], "period_id": case["period_id"],
            "guardrail": "zero_terminal_band_excess",
            "status": "pass" if all(row["raw_residual"] == 0.0 for row in resolved_terminal) else "fail",
            "max_residual": max(row["raw_residual"] for row in resolved_terminal),
        })
        hourly_rows.extend(_hourly_rows(case, artifact))

    metrics_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    production_rows: list[dict[str, Any]] = []
    economics_rows: list[dict[str, Any]] = []
    for period_id in EXPECTED_PERIODS:
        comparator = artifacts[(period_id, EXPECTED_POLICIES[0])]
        sale = artifacts[(period_id, EXPECTED_POLICIES[1])]
        comp_metrics = _case_metrics(comparator)
        sale_metrics = _case_metrics(sale)
        metrics_rows.extend([
            {"period_id": period_id, "policy_id": EXPECTED_POLICIES[0], **comp_metrics},
            {"period_id": period_id, "policy_id": EXPECTED_POLICIES[1], **sale_metrics},
        ])
        improvement = (
            sale_metrics["wag_electricity_twh_e_y_annual_equivalent"]
            - comp_metrics["wag_electricity_twh_e_y_annual_equivalent"]
        )
        pair_fingerprint_equal = (
            override_fingerprints[(period_id, EXPECTED_POLICIES[0])]
            == override_fingerprints[(period_id, EXPECTED_POLICIES[1])]
        )
        comparison_rows.append({
            "period_id": period_id,
            "wag_electricity_improvement_twh_e_y_annual_equivalent": improvement,
            "material_threshold_twh_e_y": MATERIAL_THRESHOLD_TWH_E_Y,
            "threshold_pass": improvement >= MATERIAL_THRESHOLD_TWH_E_Y,
            "gross_generator_electricity_delta_mwh": sale_metrics["gross_generator_electricity_mwh"] - comp_metrics["gross_generator_electricity_mwh"],
            "internal_generator_offset_delta_mwh": sale_metrics["internal_generator_offset_mwh"] - comp_metrics["internal_generator_offset_mwh"],
            "gross_grid_export_delta_mwh": sale_metrics["gross_grid_export_mwh"] - comp_metrics["gross_grid_export_mwh"],
            "gross_grid_import_delta_mwh": sale_metrics["gross_grid_import_mwh"] - comp_metrics["gross_grid_import_mwh"],
            "wag_flare_delta_mwh_lhv": sale_metrics["wag_flared_mwh_lhv"] - comp_metrics["wag_flared_mwh_lhv"],
            "generator_ng_delta_mwh_lhv": sale_metrics["generator_ng_mwh"] - comp_metrics["generator_ng_mwh"],
            "physical_override_fingerprint_equal": pair_fingerprint_equal,
        })
        guardrails.append({
            "period_id": period_id, "guardrail": "physical_input_fingerprint_equal_except_export_switch",
            "status": "pass" if pair_fingerprint_equal else "fail", "max_residual": 0 if pair_fingerprint_equal else 1,
        })
        guardrails.extend(_pair_guardrails(period_id, comparator, sale, comp_metrics, sale_metrics))
        containment = _validate_containment_records(
            sale["directory"] / "sale_containment", expected_replan_indices=range(7)
        )
        guardrails.append({
            "period_id": period_id, "guardrail": "real_model_containment_oracle_all_replans",
            **containment,
        })
        production_rows.append({
            "period_id": period_id,
            "final_product_delta_t": sale_metrics["final_product_t"] - comp_metrics["final_product_t"],
            "hsm_route_output_delta_t": sale_metrics["hsm_route_output_t"] - comp_metrics["hsm_route_output_t"],
            "dsp_route_output_delta_t": sale_metrics["dsp_route_output_t"] - comp_metrics["dsp_route_output_t"],
            "terminal_band_fingerprint_sha256": targets[period_id]["terminal_band_fingerprint_sha256"],
        })
        economics_rows.append({
            "period_id": period_id,
            "no_export_import_cost_eur": comp_metrics["import_cost_eur"],
            "export_enabled_import_cost_eur": sale_metrics["import_cost_eur"],
            "export_revenue_eur": sale_metrics["export_revenue_eur"],
            "no_export_represented_net_cost_eur": comp_metrics["represented_net_cost_eur"],
            "export_enabled_represented_net_cost_eur": sale_metrics["represented_net_cost_eur"],
            "represented_net_cost_delta_eur": sale_metrics["represented_net_cost_eur"] - comp_metrics["represented_net_cost_eur"],
        })

    failures = [row for row in guardrails if row.get("status") != "pass"]
    cases_pass = len(statuses) == 4 and all(row["status"] == "pass" for row in statuses)
    threshold_pass = all(row["threshold_pass"] for row in comparison_rows)
    successful = cases_pass and not failures and threshold_pass
    decision = (
        "phase5b_successful_development_sensitivity_only_no_promotion"
        if successful
        else "phase5b_threshold_or_guardrail_failed_retain_and_freeze_no_export_central"
    )
    mechanism = {
        row["period_id"]: (
            "export absorbs additional WAG generation and reduces flare/curtailment"
            if row["gross_grid_export_delta_mwh"] > ELECTRICITY_TOLERANCE_MWH
            and row["wag_flare_delta_mwh_lhv"] < -ELECTRICITY_TOLERANCE_MWH
            else "export does not materially unlock curtailed WAG generation"
        )
        for row in comparison_rows
    }

    _write_csv(output_root / "case_status.csv", statuses)
    _write_csv(output_root / "solver_summary.csv", solver_rows)
    _write_csv(output_root / "physical_guardrails.csv", guardrails)
    _write_csv(output_root / "metrics_summary.csv", metrics_rows)
    _write_csv(output_root / "paired_electricity_wag_ng_comparison.csv", comparison_rows)
    _write_csv(output_root / "hourly_import_export_diagnostics.csv", hourly_rows)
    _write_csv(output_root / "terminal_comparison.csv", terminal_rows)
    _write_csv(output_root / "production_route_inventory_comparison.csv", production_rows)
    _write_csv(output_root / "economic_comparison.csv", economics_rows)
    input_manifest = {
        "schema_version": "steel_phase5b_input_manifest_v1",
        "phase4_config": {"path": _portable(phase4_path), "sha256": _sha256(phase4_path)},
        "phase4_summary": {"path": phase5b["phase4_summary"], "sha256": _sha256(_resolve(phase5b["phase4_summary"]))},
        "phase4_target_contract": {"path": phase5b["phase4_target_contract"], "sha256": _sha256(_resolve(phase5b["phase4_target_contract"]))},
        "phase5a_candidate_decision": {"path": phase5b["phase5a_candidate_decision"], "sha256": _sha256(_resolve(phase5b["phase5a_candidate_decision"]))},
        "physical_config": {"path": phase4_config["phase4"]["physical_config"], "sha256": _sha256(_resolve(phase4_config["phase4"]["physical_config"]))},
        "pair_physical_override_fingerprints": {
            period: override_fingerprints[(period, EXPECTED_POLICIES[0])]
            for period in EXPECTED_PERIODS
        },
        "implementation": implementation_manifest,
        "implementation_sha256": implementation_sha256,
        "terminal_validation_extension": validation_extension,
        "terminal_validation_extension_sha256": _payload_sha256(validation_extension),
    }
    _write_json(output_root / "input_manifest.json", input_manifest)
    _write_json(output_root / "code_version.json", {
        "git_commit": _git_head(), "implementation_sha256": implementation_sha256,
    })
    checkpoint = {
        "run_id": RUN_ID, "status": "pass" if successful else "stop",
        "decision": decision, "successful_development_sensitivity": successful,
        "central_model_boundary": "accepted_no_export_retained",
        "candidate_promoted": False, "held_out_validation_authorized": False,
        "material_threshold_twh_e_y": MATERIAL_THRESHOLD_TWH_E_Y,
        "period_results": comparison_rows, "mechanism": mechanism,
        "guardrail_failure_count": len(failures),
    }
    _write_json(output_root / "checkpoint_decision.json", checkpoint)
    _write_json(output_root / "registry_entry.json", {
        "run_id": RUN_ID, "run_class": config["run_class"],
        "lineage_role": config["lineage_role"], "output_policy": "minimal",
        "retention_status": "local_ignored", "git_eligible": False,
        "status": checkpoint["status"], "decision": decision,
    })
    (output_root / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- Exactly one paired C0 no-export/export sensitivity over two DEVELOPMENT weeks; not held-out or annual evidence.\n"
        "- Annual-equivalent values scale representative weeks and are not empirical annual results.\n"
        "- The same governed `y_pred` values purchase and sale; no floor, cap, spread, premium, bid, settlement or realised-price claim is present.\n"
        "- Export remains sensitivity-only. The accepted central model remains no-export regardless of this gate result.\n"
        "- Named-NG break-even is diagnostic only; carrier-specific generation and fuel remain separate.\n",
        encoding="utf-8",
    )
    (output_root / "README.md").write_text(
        "# Phase 5B C0 export sensitivity\n\n"
        f"Decision: `{decision}`.\n\n"
        "The governed pair changes only the opt-in C0 export switch and its revenue term. Both accepted Phase-4 DEVELOPMENT weeks retain the same physical inputs, rolling state, reachability-aware 1% terminal band, WAG/NG coefficients, shared 770 MW and 900,000 Nm3/h caps, and governed `y_pred` price series. The accepted central model remains no-export; held-out validation, promotion, bidding and settlement are not authorized. See `checkpoint_decision.json` and the paired comparison CSV.\n",
        encoding="utf-8",
    )
    write_runtime = time.perf_counter() - started - load_runtime - build_runtime
    summary = {
        "run_id": RUN_ID, "status": "pass" if successful else "stop",
        "decision": decision, "case_count": len(statuses),
        "solver_model_count": len(solver_rows), "solver_model_cap": 56,
        "guardrail_count": len(guardrails), "guardrail_failure_count": len(failures),
        "material_threshold_pass_all_periods": threshold_pass,
        "minimum_wag_electricity_improvement_twh_e_y": min(
            row["wag_electricity_improvement_twh_e_y_annual_equivalent"]
            for row in comparison_rows
        ),
        "maximum_terminal_band_excess_t": max(row["raw_residual"] for row in terminal_rows),
        "held_out_periods_used": False, "candidate_promoted": False,
        "market_settlement_claim": False, "load_runtime_seconds": load_runtime,
        "build_and_solve_runtime_seconds": build_runtime,
        "write_runtime_seconds": write_runtime,
        "runtime_seconds": time.perf_counter() - started,
        "validation_tolerance_policy": policy_contract(),
    }
    _write_json(output_root / "run_summary.json", summary)
    return {"run_directory": output_root, "summary": summary}


def finalize_existing_failure(config_path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    """Persist a zero-solve stop checkpoint from a preserved failed attempt."""

    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    validate_config(config)
    if _git_head() != EXPECTED_HEAD:
        raise Phase5BExportSensitivityError("Failure finalization requires the frozen HEAD.")
    validation_extension = install_terminal_validation_extension()
    phase5b = config["phase5b"]
    output_root = _resolve(config["output_root"])
    scratch_root = _resolve(phase5b["scratch_root"])
    if not output_root.is_dir() or not scratch_root.is_dir():
        raise Phase5BExportSensitivityError("No preserved Phase-5B attempt is available.")

    feb_normal_id = "phase5b__validation_2024_02_12__accepted_no_export_comparator"
    feb_sale_id = "phase5b__validation_2024_02_12__athanasiadis_sale_enabled"
    comparator_dir = scratch_root / feb_normal_id
    containment_root = scratch_root / feb_sale_id / "sale_containment"
    required_comparator = (
        "run_summary.json", "executed_hourly.csv", "executed_procurement_cost_ledger.csv",
        "rolling_model_metrics.csv", "validation_checks.csv", "rolling_execution.csv",
        "inventory_handoff.csv", "rolling_production_progress_state.csv",
    )
    if not all((comparator_dir / name).is_file() for name in required_comparator):
        raise Phase5BExportSensitivityError("The preserved no-export comparator is incomplete.")
    containment_paths = sorted(containment_root.glob("replan_*/sale_incumbent_containment.json"))
    containment_records = [_read_json(path) for path in containment_paths]
    failed = [row for row in containment_records if row.get("status") != "pass"]
    if len(containment_records) != 4 or len(failed) != 1:
        raise Phase5BExportSensitivityError("Unexpected preserved containment failure shape.")
    failure = failed[0]
    if (
        failure.get("failure_stage") != "native_gurobi_reread"
        or failure.get("pyomo_termination_condition") != "infeasible"
        or failure.get("native_gurobi", {}).get("status") != "infeasible"
    ):
        raise Phase5BExportSensitivityError("The preserved failure is not dual-solver proven.")
    failed_rows = [
        row for row in failure["registered_validation_evidence"]["rows"]
        if row.get("status") != "pass"
    ]
    if len(failed_rows) != 1:
        raise Phase5BExportSensitivityError("Expected exactly one failed validation row.")
    failed_row = failed_rows[0]
    if (
        failed_row.get("constraint_family")
        != "c0_reference_deadline_hsm_final_output_72h_upper"
        or float(failed_row.get("raw_residual", 0.0)) <= float(
            failed_row.get("allowed_tolerance", math.inf)
        )
    ):
        raise Phase5BExportSensitivityError("Unexpected containment failure mechanism.")

    comparator = {
        "directory": comparator_dir,
        "summary": _read_json(comparator_dir / "run_summary.json"),
        "hourly": _read_csv(comparator_dir / "executed_hourly.csv"),
        "costs": _read_csv(comparator_dir / "executed_procurement_cost_ledger.csv"),
        "models": _read_csv(comparator_dir / "rolling_model_metrics.csv"),
        "validation": _read_csv(comparator_dir / "validation_checks.csv"),
        "execution": _read_csv(comparator_dir / "rolling_execution.csv"),
        "handoff": _read_csv(comparator_dir / "inventory_handoff.csv"),
        "progress": _read_csv(comparator_dir / "rolling_production_progress_state.csv"),
    }
    comparator_metrics = _case_metrics(comparator)
    model_ok = len(comparator["models"]) == 14 and all(
        row.get("solver_status", "").lower() == "ok"
        and row.get("termination_condition", "").lower() == "optimal"
        for row in comparator["models"]
    )
    child_checks_ok = all(row.get("status") == "pass" for row in comparator["validation"])
    target_contract_path = _resolve(phase5b["phase4_target_contract"])
    target_contract = _read_json(target_contract_path)
    feb_target = next(
        row for row in target_contract["targets"]
        if row["period_id"] == "validation_2024-02-12"
    )
    normal_case = next(
        row for row in frozen_case_matrix(config)
        if row["case_id"] == feb_normal_id
    )
    terminal_rows = _terminal_rows(
        normal_case, terminal_state_vector(comparator), feb_target["terminal_band"]
    )
    statuses = [
        {"case_id": feb_normal_id, "period_id": "validation_2024-02-12",
         "policy_id": EXPECTED_POLICIES[0],
         "status": "pass" if model_ok and child_checks_ok else "fail",
         "model_count": len(comparator["models"]), "failure": ""},
        {"case_id": feb_sale_id, "period_id": "validation_2024-02-12",
         "policy_id": EXPECTED_POLICIES[1], "status": "fail_closed",
         "model_count": 0,
         "failure": "sale_incumbent_containment_infeasible_replan_03"},
        {"case_id": "phase5b__validation_2024_07_01__accepted_no_export_comparator",
         "period_id": "validation_2024-07-01", "policy_id": EXPECTED_POLICIES[0],
         "status": "not_started_after_stop_rule", "model_count": 0,
         "failure": "february_pair_failed_closed"},
        {"case_id": "phase5b__validation_2024_07_01__athanasiadis_sale_enabled",
         "period_id": "validation_2024-07-01", "policy_id": EXPECTED_POLICIES[1],
         "status": "not_started_after_stop_rule", "model_count": 0,
         "failure": "february_pair_failed_closed"},
    ]
    guardrails = [
        {"period_id": "validation_2024-02-12",
         "guardrail": "no_export_comparator_optimal_and_valid",
         "status": "pass" if model_ok and child_checks_ok else "fail",
         "raw_residual": 0.0 if model_ok and child_checks_ok else 1.0},
        {"period_id": "validation_2024-02-12",
         "guardrail": "real_model_containment_oracle_all_replans",
         "status": "fail", "raw_residual": float(failed_row["raw_residual"]),
         "allowed_tolerance": float(failed_row["allowed_tolerance"]),
         "failed_constraint_family": failed_row["constraint_family"],
         "pyomo_termination_condition": failure["pyomo_termination_condition"],
         "native_gurobi_status": failure["native_gurobi"]["status"]},
        {"period_id": "validation_2024-02-12",
         "guardrail": "zero_terminal_band_excess_no_export_comparator",
         "status": "pass" if all(row["raw_residual"] == 0.0 for row in terminal_rows) else "fail",
         "raw_residual": max(row["raw_residual"] for row in terminal_rows)},
    ]
    comparison_rows = [
        {"period_id": period, "status": "not_computable_export_trajectory_incomplete",
         "wag_electricity_improvement_twh_e_y_annual_equivalent": "",
         "material_threshold_twh_e_y": MATERIAL_THRESHOLD_TWH_E_Y,
         "threshold_pass": False,
         "failure": "february_containment_failed" if period == EXPECTED_PERIODS[0]
         else "not_started_after_stop_rule"}
        for period in EXPECTED_PERIODS
    ]
    solver_rows = [
        {"case_id": feb_normal_id, "evidence_type": "rolling_model",
         "replan_index": row.get("replan_index"),
         "configuration_id": row.get("configuration_id"),
         "solver_status": row.get("solver_status"),
         "termination_condition": row.get("termination_condition"),
         "primary_objective_eur": row.get("primary_cost_objective_eur"),
         "runtime_seconds": row.get("runtime_seconds"),
         "mip_gap": row.get("mip_gap"),
         "variable_count": row.get("variable_count"),
         "binary_count": row.get("binary_count"),
         "constraint_count": row.get("constraint_count")}
        for row in comparator["models"]
    ] + [
        {"case_id": feb_sale_id, "evidence_type": "containment_validation",
         "replan_index": index, "configuration_id": C0_CONFIGURATION,
         "solver_status": record.get("pyomo_solver_status"),
         "termination_condition": record.get("pyomo_termination_condition"),
         "native_gurobi_status": record.get("native_gurobi", {}).get("status"),
         "containment_status": record.get("status")}
        for index, record in enumerate(containment_records)
    ]
    metrics_rows = [{
        "period_id": "validation_2024-02-12", "policy_id": EXPECTED_POLICIES[0],
        "status": "complete", **comparator_metrics,
    }, {
        "period_id": "validation_2024-02-12", "policy_id": EXPECTED_POLICIES[1],
        "status": "incomplete_containment_failed", "executed_hours": "",
    }]
    economics = [{
        "period_id": "validation_2024-02-12",
        "status": "export_comparison_not_computable",
        "no_export_import_cost_eur": comparator_metrics["import_cost_eur"],
        "no_export_represented_net_cost_eur": comparator_metrics["represented_net_cost_eur"],
        "export_revenue_eur": "", "represented_net_cost_delta_eur": "",
    }]
    production = [{
        "period_id": "validation_2024-02-12",
        "status": "export_comparison_not_computable",
        "no_export_final_product_t": comparator_metrics["final_product_t"],
        "final_product_delta_t": "", "hsm_route_output_delta_t": "",
        "dsp_route_output_delta_t": "",
        "terminal_band_fingerprint_sha256": feb_target[
            "terminal_band_fingerprint_sha256"
        ],
    }]
    _write_csv(output_root / "case_status.csv", statuses)
    _write_csv(output_root / "solver_summary.csv", solver_rows)
    _write_csv(output_root / "physical_guardrails.csv", guardrails)
    _write_csv(output_root / "metrics_summary.csv", metrics_rows)
    _write_csv(output_root / "paired_electricity_wag_ng_comparison.csv", comparison_rows)
    _write_csv(output_root / "hourly_import_export_diagnostics.csv", _hourly_rows(normal_case, comparator))
    _write_csv(output_root / "terminal_comparison.csv", terminal_rows)
    _write_csv(output_root / "production_route_inventory_comparison.csv", production)
    _write_csv(output_root / "economic_comparison.csv", economics)
    failure_evidence = {
        "status": failure["status"], "failure_stage": failure["failure_stage"],
        "failed_replan_index": 3, "failed_constraint": failed_row,
        "pyomo_solver_status": failure["pyomo_solver_status"],
        "pyomo_termination_condition": failure["pyomo_termination_condition"],
        "native_gurobi": {
            key: value for key, value in failure["native_gurobi"].items()
            if key != "iis_path"
        },
        "native_gurobi_iis_path": _portable(Path(failure["native_gurobi"]["iis_path"])),
        "containment_record_path": _portable(containment_paths[-1]),
        "containment_record_sha256": _sha256(containment_paths[-1]),
        "passing_containment_replans": [0, 1, 2],
    }
    _write_json(output_root / "failure_evidence.json", failure_evidence)
    implementation_files = (
        config_file, Path(__file__).resolve(),
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/run_s4_4c5p_phase5b_c0_export_sensitivity.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/validation_tolerance_policy.py",
    )
    implementation = [
        {"path": _portable(path), "sha256": _sha256(path)} for path in implementation_files
    ]
    _write_json(output_root / "input_manifest.json", {
        "schema_version": "steel_phase5b_failed_input_manifest_v1",
        "phase4_config": {"path": phase5b["phase4_config"], "sha256": _sha256(_resolve(phase5b["phase4_config"]))},
        "phase4_summary": {"path": phase5b["phase4_summary"], "sha256": _sha256(_resolve(phase5b["phase4_summary"]))},
        "phase4_target_contract": {"path": phase5b["phase4_target_contract"], "sha256": _sha256(target_contract_path)},
        "phase5a_candidate_decision": {"path": phase5b["phase5a_candidate_decision"], "sha256": _sha256(_resolve(phase5b["phase5a_candidate_decision"]))},
        "implementation": implementation,
        "execution_implementation_sha256": failure["provenance"]["implementation_sha256"],
        "zero_solve_finalizer_implementation_sha256": _payload_sha256(implementation),
        "terminal_validation_extension": validation_extension,
        "terminal_validation_extension_sha256": _payload_sha256(validation_extension),
        "preserved_failed_containment": failure_evidence,
    })
    _write_json(output_root / "code_version.json", {
        "git_commit": _git_head(),
        "execution_implementation_sha256": failure["provenance"]["implementation_sha256"],
        "zero_solve_finalizer_implementation_sha256": _payload_sha256(implementation),
    })
    decision = "phase5b_execution_failed_closed_retain_and_freeze_no_export_central"
    checkpoint = {
        "run_id": RUN_ID, "status": "stop", "decision": decision,
        "successful_development_sensitivity": False,
        "central_model_boundary": "accepted_no_export_retained_and_frozen",
        "candidate_promoted": False, "held_out_validation_authorized": False,
        "material_threshold_twh_e_y": MATERIAL_THRESHOLD_TWH_E_Y,
        "material_threshold_evaluable": False,
        "failure_mechanism": (
            "The captured no-export incumbent exceeds the governed 72-hour C0 HSM "
            "reference upper bound by 52.369865 t in February replan 3. The allowed "
            "1.0 t validation relaxation is insufficient; Pyomo and native Gurobi "
            "both prove the containment validation model infeasible."
        ),
        "guardrail_failure_count": 1, "july_started": False,
    }
    _write_json(output_root / "checkpoint_decision.json", checkpoint)
    _write_json(output_root / "registry_entry.json", {
        "run_id": RUN_ID, "run_class": config["run_class"],
        "lineage_role": config["lineage_role"], "output_policy": "minimal",
        "retention_status": "local_ignored", "git_eligible": False,
        "status": "stop", "decision": decision,
    })
    (output_root / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- The paired export trajectory did not complete; WAG-electricity improvement and economics are not computable.\n"
        "- February stopped at export replan 3 after dual-solver containment infeasibility; July was not started under the stop rule.\n"
        "- The 1.0 t governed validation allowance was not widened and containment was not bypassed.\n"
        "- The accepted central model remains no-export and is frozen. Held-out validation, promotion, bidding and settlement remain unauthorized.\n",
        encoding="utf-8",
    )
    (output_root / "README.md").write_text(
        "# Phase 5B C0 export sensitivity — fail-closed checkpoint\n\n"
        f"Decision: `{decision}`.\n\n"
        "The no-export comparator completed optimally, but the export-enabled path failed its required incumbent-containment oracle in February replan 3. The captured comparator exceeded the registered 72-hour HSM reference upper bound by 52.369865 t versus a 1.0 t allowance; both Pyomo and native Gurobi returned infeasible. No tolerance was widened, the export trajectory was not treated as evidence, July was not started, and the no-export central model remains frozen. See `failure_evidence.json` and `checkpoint_decision.json`.\n",
        encoding="utf-8",
    )
    summary = {
        "run_id": RUN_ID, "status": "stop", "decision": decision,
        "completed_no_export_trajectory_count": 1,
        "completed_export_trajectory_count": 0,
        "completed_rolling_model_count": len(comparator["models"]),
        "containment_record_count": len(containment_records),
        "passing_containment_record_count": len(containment_records) - len(failed),
        "guardrail_failure_count": 1, "material_threshold_evaluable": False,
        "held_out_periods_used": False, "candidate_promoted": False,
        "market_settlement_claim": False,
        "maximum_terminal_band_excess_t_no_export": max(row["raw_residual"] for row in terminal_rows),
        "runtime_seconds_zero_solve_finalization": time.perf_counter() - started,
        "validation_tolerance_policy": policy_contract(),
    }
    _write_json(output_root / "run_summary.json", summary)
    return {"run_directory": output_root, "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--finalize-existing-failure", action="store_true")
    args = parser.parse_args()
    result = (
        finalize_existing_failure(args.config)
        if args.finalize_existing_failure
        else run_phase5b(args.config)
    )
    print(json.dumps(result["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
