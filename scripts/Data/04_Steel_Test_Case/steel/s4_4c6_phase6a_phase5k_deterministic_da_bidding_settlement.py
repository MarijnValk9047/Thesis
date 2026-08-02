"""Phase 6A deterministic DA gate around the frozen Phase-5K boundary."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping

import yaml

from .s4_4c5p_phase4_terminal_inventory_equivalence import _artifact
from .s4_4c5p_phase5b_c0_export_sensitivity import _git_head, _read_csv, _read_json, _select_solver, _sha256, install_terminal_validation_extension
from .s4_4c5p_phase5g_final_deterministic_freeze import CONFIGURATIONS, _dependencies, _hsm_checks, _physical_checks, load_config as load_phase5g_config
from .s4_4c5p_phase5h_four_residual_effect_gate import held_out_contract
from .s4_4c5p_phase5i_electricity_only_heldout_freeze import _payload_sha256, _portable, _resolve, _write_csv, _write_json
from .s4_4c5p_phase5k_final_user_authorized_boundary_freeze import boundary_maps, load_final_contract, load_wag_audit_contract, wag_yield_overrides
from .s4_4c6_phase6a_deterministic_da_bidding_settlement import (
    STRATEGIES,
    _accounting_checks,
    _benchmark_case,
    _benchmark_comparison,
    _benchmark_summary,
    _case_status,
    build_settlement_rows,
    load_da_contract,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_c6_phase6a_phase5k_deterministic_da_bidding_settlement_v2_20260729"
CONFIG_PATH = REPO_ROOT / "scripts/Data/04_Steel_Test_Case/configs/steel_c6_phase6a_phase5k_deterministic_da_bidding_settlement.yaml"


class Phase6APhase5KGateError(RuntimeError):
    pass


def load_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    phase = payload.get("phase6a_phase5k")
    if payload.get("run_id") != RUN_ID or payload.get("output_policy") != "minimal" or not isinstance(phase, Mapping):
        raise Phase6APhase5KGateError("Phase-6A/5K identity or output policy changed.")
    policy = phase["policy"]
    required_true = ("electricity_baseload_fixed", "common_ng_site_service_fixed", "residual_co2_reporting_only")
    prohibited = ("residual_co2_in_cost_or_ets", "export_allowed", "stochastic_scenarios_allowed", "cvar_allowed", "mfrr_allowed", "ets_allowed", "product_revenue_allowed", "physical_flexibility_changed")
    if not all(bool(policy[key]) for key in required_true) or any(bool(policy[key]) for key in prohibited):
        raise Phase6APhase5KGateError("Phase-6A/5K scope lock changed.")
    if policy["realised_price_use"] != "settlement_and_isolated_oracle_only":
        raise Phase6APhase5KGateError("Realised-price timing policy changed.")
    return payload


def load_phase5k_realised_price_gap_supplement(path: str | Path) -> dict[str, float]:
    rows = _read_csv(Path(path))
    expected = {
        "2025-04-27T00:00:00+00:00",
        "2025-04-27T01:00:00+00:00",
        "2025-04-27T02:00:00+00:00",
    }
    if {row["delivery_timestamp_utc"] for row in rows} != expected:
        raise Phase6APhase5KGateError("The Phase-5K realised-price supplement support changed.")
    if any(
        row["source_provider"] != "Fraunhofer_ISE_Energy_Charts"
        or row["status"] != "source_crosschecked_gap_supplement"
        or row["allowed_use"] != "settlement_and_explicit_perfect_foresight_oracle_only"
        or row["overlap_crosscheck"] != "21_of_21_nonmissing_hours_exact_max_abs_difference_0"
        or not math.isclose(float(row["price_eur_per_mwh"]), 95.6, abs_tol=1e-12)
        for row in rows
    ):
        raise Phase6APhase5KGateError("The Phase-5K realised-price supplement lost its source or scope guardrail.")
    return {row["delivery_timestamp_utc"]: float(row["price_eur_per_mwh"]) for row in rows}


def _load_point_artifacts(root: Path, periods: list[dict[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for period in periods:
        period_id = str(period["period_id"])
        directory = root / f"phase5g__phase5k_fresh_heldout__{period_id.replace('-', '_')}"
        if not (directory / "run_summary.json").exists():
            raise Phase6APhase5KGateError(f"Frozen Phase-5K point-forecast cache is missing: {directory.name}")
        artifact = _artifact(directory)
        if artifact["summary"].get("status") != "pass":
            raise Phase6APhase5KGateError(f"Frozen Phase-5K point case did not pass: {directory.name}")
        result[period_id] = artifact
    return result


def _residual_boundary_checks(
    strategy: str, artifacts: Mapping[str, Mapping[str, Any]], residual_co2: Mapping[str, float], tolerance: float,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for period_id, artifact in artifacts.items():
        for configuration in CONFIGURATIONS:
            rows = [row for row in artifact["hourly"] if row.get("configuration_id") == configuration]
            steam = max(abs(float(row.get("residual_steam_15bar_demand_t") or 0.0)) for row in rows)
            co2 = max(abs(float(row.get("residual_unmodelled_direct_co2_t") or 0.0) - float(residual_co2[configuration])) for row in rows)
            checks.extend([
                {"strategy": strategy, "period_id": period_id, "configuration_id": configuration, "check_id": "residual_steam_zero", "actual": steam, "limit": tolerance, "status": "pass" if steam <= tolerance else "fail"},
                {"strategy": strategy, "period_id": period_id, "configuration_id": configuration, "check_id": "residual_co2_reporting_constant", "actual": co2, "limit": tolerance, "status": "pass" if co2 <= tolerance else "fail"},
            ])
    return checks


def _persist(
    config_file: Path, config: Mapping[str, Any], phase: Mapping[str, Any], inputs: list[Path],
    case_status: list[dict[str, Any]], physical: list[dict[str, Any]], accounting: list[dict[str, Any]],
    settlement: list[dict[str, Any]], summary_rows: list[dict[str, Any]], comparisons: list[dict[str, Any]],
    checkpoint: Mapping[str, Any], started: float,
) -> dict[str, Any]:
    output = _resolve(config["output_root"])
    if output.exists():
        raise Phase6APhase5KGateError("Phase-6A/5K governed output already exists.")
    output.mkdir(parents=True)
    (output / "resolved_config.yaml").write_text(yaml.safe_dump(dict(config), sort_keys=False), encoding="utf-8")
    _write_csv(output / "deterministic_da_contract_snapshot.csv", load_da_contract(_resolve(phase["da_contract"])))
    _write_csv(output / "case_status.csv", case_status)
    _write_csv(output / "physical_checks.csv", physical)
    _write_csv(output / "timing_and_accounting_checks.csv", accounting)
    _write_csv(output / "da_bid_settlement_hourly.csv", settlement)
    _write_csv(output / "benchmark_summary.csv", summary_rows)
    _write_csv(output / "benchmark_comparison.csv", comparisons)
    _write_json(output / "checkpoint_decision.json", checkpoint)
    manifest = [{"path": _portable(path), "sha256": _sha256(path), "size_bytes": path.stat().st_size} for path in inputs]
    _write_json(output / "input_manifest.json", {"files": manifest})
    phase5k_fingerprints = _read_json(_resolve(phase["phase5k_fingerprint_manifest"]))
    fingerprints = {
        "git_head": _git_head(),
        "phase5k_model_fingerprint_sha256": phase5k_fingerprints["model_fingerprint_sha256"],
        "phase5k_input_contract_fingerprint_sha256": phase5k_fingerprints["input_contract_fingerprint_sha256"],
        "phase5k_final_boundary_contract_sha256": phase5k_fingerprints["final_boundary_contract_sha256"],
        "phase6a_runner_sha256": _sha256(Path(__file__).resolve()),
        "da_contract_sha256": _sha256(_resolve(phase["da_contract"])),
        "heldout_period_contract_sha256": _sha256(_resolve(phase["held_out_contract"])),
        "combined_fingerprint_sha256": _payload_sha256({row["path"]: row["sha256"] for row in manifest}),
    }
    _write_json(output / "fingerprint_manifest.json", fingerprints)
    _write_json(output / "code_version.json", {"git_head": _git_head(), "dirty_worktree_preserved": True})
    _write_json(output / "registry_entry.json", {"run_id": RUN_ID, "run_class": config["run_class"], "lineage_role": config["lineage_role"], "output_policy": config["output_policy"], "decision": checkpoint["decision"]})
    (output / "README.md").write_text("# Phase 6A on frozen Phase-5K boundary\n\nDeterministic point-forecast purchase quantities are settled at realised DA prices and compared with flat-price and isolated perfect-foresight schedules.\n", encoding="utf-8")
    (output / "warnings_and_limitations.md").write_text("# Warnings and limitations\n\nThe electricity and NG site services are fixed user-authorized abstractions. Residual direct CO2 is reporting-only and absent from cost and ETS. Perfect foresight is an ex-post oracle; stochasticity, CVaR and mFRR remain absent.\n", encoding="utf-8")
    result = {**dict(checkpoint), "runtime_seconds": time.perf_counter() - started, "fingerprints": fingerprints}
    _write_json(output / "run_summary.json", result)
    return result


def run_phase6a_phase5k(config_path: str | Path = CONFIG_PATH, *, resume_incomplete: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    phase = config["phase6a_phase5k"]
    if _git_head() != str(phase["expected_parent_head"]):
        raise Phase6APhase5KGateError("Phase-6A/5K requires the preserved campaign parent HEAD.")
    checkpoint5k = _read_json(_resolve(phase["phase5k_checkpoint"]))
    if checkpoint5k.get("decision") != "user_authorized_represented_boundary_deterministic_model_frozen_for_phase6" or checkpoint5k.get("status") != "pass":
        raise Phase6APhase5KGateError("Phase 5K did not authorize the Phase-6A rerun.")
    load_da_contract(_resolve(phase["da_contract"]))
    realised_patch = load_phase5k_realised_price_gap_supplement(_resolve(phase["realised_price_gap_supplement"]))
    contract_rows = load_final_contract(_resolve(phase["boundary_contract"]))
    electricity, ng, residual_co2 = boundary_maps(contract_rows)
    wag_yields = wag_yield_overrides(load_wag_audit_contract(_resolve(phase["wag_audit_contract"])))
    periods, _ = held_out_contract(_resolve(phase["held_out_contract"]))
    if len(periods) != int(phase["expected_period_count"]):
        raise Phase6APhase5KGateError("Frozen Phase-5K period count changed.")
    point_artifacts = _load_point_artifacts(_resolve(phase["phase5k_case_cache"]), periods)
    scratch = _resolve(phase["scratch_root"])
    if scratch.exists() and not resume_incomplete:
        raise Phase6APhase5KGateError("Phase-6A/5K scratch exists; use explicit resume.")
    scratch.mkdir(parents=True, exist_ok=True)
    phase5g = dict(load_phase5g_config(_resolve(phase["phase5g_config"]))["phase5g"])
    phase5g["scratch_root"] = phase["scratch_root"]
    parent, phase4, terminal_target = _dependencies(phase5g)
    if _select_solver()[1] is None:
        raise Phase6APhase5KGateError("Gurobi is unavailable before benchmark execution.")
    install_terminal_validation_extension()
    artifacts: dict[str, dict[str, Mapping[str, Any]]] = {"deterministic_point_forecast": dict(point_artifacts), "price_insensitive_benchmark": {}, "perfect_foresight_oracle": {}}
    case_status = [_case_status("deterministic_point_forecast", period_id, artifact, True) for period_id, artifact in point_artifacts.items()]
    for strategy in ("price_insensitive_benchmark", "perfect_foresight_oracle"):
        for period in periods:
            _, artifact, reused = _benchmark_case(
                strategy=strategy, period=period, phase=phase, phase5g=phase5g, parent=parent,
                phase4=phase4, terminal_target=terminal_target, electricity=electricity,
                allow_solve_missing=True, realised_price_gap_patch=realised_patch, ng=ng,
                residual_co2=residual_co2, wag_yields=wag_yields,
            )
            artifacts[strategy][str(period["period_id"])] = artifact
            case_status.append(_case_status(strategy, str(period["period_id"]), artifact, reused))
    physical: list[dict[str, Any]] = []
    for strategy, values in artifacts.items():
        physical += _physical_checks(strategy, values, electricity, ng, float(phase["physical_balance_tolerance_mwh"]))
        physical += _hsm_checks(strategy, values, phase5g, float(phase["physical_balance_tolerance_mwh"]))
        physical += _residual_boundary_checks(strategy, values, residual_co2, float(phase["physical_balance_tolerance_mwh"]))
    settlement: list[dict[str, Any]] = []
    period_lookup = {str(row["period_id"]): row for row in periods}
    for strategy in STRATEGIES:
        for period_id, artifact in artifacts[strategy].items():
            settlement += build_settlement_rows(period=period_lookup[period_id], strategy=strategy, artifact=artifact, point_artifact=artifacts["deterministic_point_forecast"][period_id], oracle_artifact=artifacts["perfect_foresight_oracle"][period_id], quantity_tolerance_mwh=float(phase["physical_balance_tolerance_mwh"]))
    summary_rows = _benchmark_summary(settlement, artifacts)
    comparisons = _benchmark_comparison(summary_rows)
    accounting = _accounting_checks(settlement, summary_rows, float(phase["settlement_tolerance_eur"]))
    evaluated_models = sum(int(row["model_count"]) for row in case_status)
    passed = evaluated_models == int(phase["expected_evaluated_models"]) and all(row["status"] == "pass" for row in case_status + physical + accounting)
    checkpoint = {
        "run_id": RUN_ID,
        "decision": phase["decision_on_pass"] if passed else phase["decision_on_fail"],
        "status": "pass" if passed else "fail",
        "phase5k_freeze_decision_preserved": checkpoint5k["decision"],
        "evaluated_models": evaluated_models,
        "point_forecast_models_reused": int(phase["expected_point_models_reused"]),
        "new_benchmark_models": int(phase["expected_new_benchmark_models"]),
        "all_models_optimal": all(bool(row["all_models_optimal"]) for row in case_status),
        "deterministic_point_forecast_bid": True,
        "price_insensitive_benchmark": True,
        "perfect_foresight_oracle": True,
        "realised_prices_used_by_executable_bid": False,
        "settlement_uses_realised_prices": True,
        "electricity_and_ng_baseloads_fixed": True,
        "residual_co2_reporting_only": True,
        "export_zero": True,
        "stochasticity_cvar_mfrr_absent": True,
        "next_gate": phase["next_gate_on_pass"] if passed else "blocked",
        "failure_count": sum(row["status"] != "pass" for row in case_status + physical + accounting),
    }
    inputs = [config_file, _resolve(phase["phase5k_checkpoint"]), _resolve(phase["phase5k_fingerprint_manifest"]), _resolve(phase["boundary_contract"]), _resolve(phase["wag_audit_contract"]), _resolve(phase["da_contract"]), _resolve(phase["held_out_contract"]), Path(__file__).resolve()]
    return _persist(config_file, config, phase, inputs, case_status, physical, accounting, settlement, summary_rows, comparisons, checkpoint, started)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--resume-incomplete", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_phase6a_phase5k(args.config, resume_incomplete=args.resume_incomplete), indent=2))


if __name__ == "__main__":
    main()
