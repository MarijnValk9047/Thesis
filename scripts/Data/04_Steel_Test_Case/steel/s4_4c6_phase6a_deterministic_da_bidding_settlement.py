"""Phase 6A deterministic day-ahead quantity bidding and realised-price settlement."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_phase4_terminal_inventory_equivalence import _artifact, _case_overrides
from .s4_4c5p_phase5b_c0_export_sensitivity import (
    _git_head,
    _read_csv,
    _read_json,
    _resolve,
    _select_solver,
    _sha256,
    install_terminal_validation_extension,
)
from .s4_4c5p_phase5g_final_deterministic_freeze import (
    _dependencies,
    _hsm_checks,
    _physical_checks,
    load_config as load_phase5g_config,
)
from .s4_4c5p_phase5h_four_residual_effect_gate import held_out_contract
from .s4_4c5p_phase5i_electricity_only_heldout_freeze import (
    electricity_maps,
    load_selected_contract,
    residual_zero_checks,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_c6_phase6a_deterministic_da_bidding_settlement_v1_20260728"
CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c6_phase6a_deterministic_da_bidding_settlement.yaml"
)
CONFIGURATIONS = (C0_CONFIGURATION, C1_CONFIGURATION)
SHORT_CONFIGURATION = {C0_CONFIGURATION: "C0", C1_CONFIGURATION: "C1"}
STRATEGIES = ("deterministic_point_forecast", "price_insensitive_benchmark", "perfect_foresight_oracle")


class Phase6AGateError(RuntimeError):
    pass


def _portable(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise Phase6AGateError(f"Persistent path must be repository-relative: {path}") from exc


def _number(value: Any) -> float:
    return 0.0 if value in {None, ""} else float(value)


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialised = list(rows)
    if not materialised:
        raise Phase6AGateError(f"Required output is empty: {path.name}")
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


def load_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload["run_id"] != RUN_ID or payload["output_policy"] != "minimal":
        raise Phase6AGateError("Phase-6A run identity or output policy changed.")
    phase = payload["phase6a"]
    policy = phase["policy"]
    prohibited = (
        "electricity_baseload_dispatchable", "electricity_baseload_price_responsive",
        "export_allowed", "stochastic_scenarios_allowed", "cvar_allowed", "mfrr_allowed",
        "ets_allowed", "product_revenue_allowed", "residual_ng_steam_co2_cost_allowed",
        "physical_flexibility_changed",
    )
    if any(bool(policy[key]) for key in prohibited):
        raise Phase6AGateError("Phase-6A scope lock was relaxed.")
    if policy["realised_price_use"] != "settlement_and_isolated_oracle_only":
        raise Phase6AGateError("Realised-price timing policy changed.")
    return payload


def load_da_contract(path: str | Path) -> list[dict[str, str]]:
    rows = _read_csv(Path(path))
    if [row["case_role"] for row in rows] != list(STRATEGIES):
        raise Phase6AGateError("The three deterministic DA roles changed.")
    point, flat, oracle = rows
    if point["physical_price_basis"] != "governed_D_Dplus4_y_pred":
        raise Phase6AGateError("The executable bid must use the governed point forecast.")
    if flat["physical_price_basis"] != "flat_80_EUR_per_MWh":
        raise Phase6AGateError("The price-insensitive benchmark must remain flat.")
    if oracle["oracle"] != "true" or oracle["bid_type"] != "not_submitted_counterfactual":
        raise Phase6AGateError("Perfect foresight must remain an isolated non-submitted oracle.")
    if any(row["baseload_treatment"] != "fixed_non_dispatchable_non_price_responsive_net_demand" for row in rows):
        raise Phase6AGateError("The frozen electricity baseload was made flexible.")
    return rows


def load_realised_price_gap_supplement(path: str | Path) -> dict[str, float]:
    rows = _read_csv(Path(path))
    expected = {
        "2025-07-13T11:00:00+00:00",
        "2025-07-13T12:00:00+00:00",
        "2025-07-13T13:00:00+00:00",
    }
    if {row["delivery_timestamp_utc"] for row in rows} != expected:
        raise Phase6AGateError("The governed realised-price gap supplement changed support.")
    if any(
        row["source_provider"] != "Fraunhofer_ISE_Energy_Charts"
        or row["status"] != "source_crosschecked_gap_supplement"
        or row["allowed_use"] != "settlement_and_explicit_perfect_foresight_oracle_only"
        or row["overlap_crosscheck"] != "21_of_21_nonmissing_hours_exact_max_abs_difference_0"
        or not math.isclose(float(row["price_eur_per_mwh"]), 0.0, abs_tol=1e-12)
        for row in rows
    ):
        raise Phase6AGateError("The realised-price supplement lost its source or scope guardrail.")
    return {
        row["delivery_timestamp_utc"]: float(row["price_eur_per_mwh"])
        for row in rows
    }


def settle_hour(
    *, bid_quantity_mwh: float, realised_price_eur_per_mwh: float,
    negative_tolerance_mwh: float = 1e-6,
) -> dict[str, float]:
    if bid_quantity_mwh < -abs(float(negative_tolerance_mwh)):
        raise Phase6AGateError("Purchase bids cannot be negative or become export.")
    quantity = max(0.0, float(bid_quantity_mwh))
    price = float(realised_price_eur_per_mwh)
    return {
        "cleared_quantity_mwh": quantity,
        "settled_quantity_mwh": quantity,
        "imbalance_mwh": 0.0,
        "electricity_procurement_cost_eur": quantity * price,
    }


def _case_directory(root: Path, period_id: str) -> Path:
    return root / f"phase5g__phase5i_heldout__{period_id.replace('-', '_')}"


def _load_phase5i_artifacts(root: Path, periods: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    artifacts: dict[str, Mapping[str, Any]] = {}
    for period in periods:
        path = _case_directory(root, str(period["period_id"]))
        if not path.exists():
            raise Phase6AGateError(f"Frozen Phase-5I case cache is missing: {path.name}")
        artifact = _artifact(path)
        if artifact["summary"].get("status") != "pass":
            raise Phase6AGateError(f"Frozen Phase-5I case did not pass: {path.name}")
        artifacts[str(period["period_id"])] = artifact
    return artifacts


def _benchmark_case(
    *, strategy: str, period: Mapping[str, Any], phase: Mapping[str, Any],
    phase5g: Mapping[str, Any], parent: Mapping[str, Any], phase4: Mapping[str, Any],
    terminal_target: Mapping[str, Any], electricity: Mapping[str, float], allow_solve_missing: bool,
    realised_price_gap_patch: Mapping[str, float],
    ng: Mapping[str, float] | None = None,
    residual_co2: Mapping[str, float] | None = None,
    wag_yields: Mapping[str, Mapping[str, float]] | None = None,
) -> tuple[str, Mapping[str, Any], bool]:
    if strategy not in {"price_insensitive_benchmark", "perfect_foresight_oracle"}:
        raise Phase6AGateError(f"Unsupported benchmark strategy: {strategy}")
    case_id = f"phase6a__{strategy}__{str(period['period_id']).replace('-', '_')}"
    oracle = strategy == "perfect_foresight_oracle"
    case = {
        "case_id": case_id,
        "period_id": period["period_id"],
        "dataset_split": period["dataset_split"],
        "forecast_start_origin_utc": period["frozen_forecast_start_origin_utc"],
        "flat_price_eur_per_mwh": None if oracle else float(phase["flat_reference_price_eur_per_mwh"]),
        "price_field": "y_true" if oracle else "y_pred",
        "perfect_foresight_oracle": oracle,
    }
    overrides = _case_overrides(
        phase4, case, _resolve(parent["phase5b"]["forecast_run_root"]),
        int(period["terminal_executed_hours"]), terminal_target["terminal_band"],
    )
    overrides.update({
        "run_id": case_id,
        "lineage_role": f"phase6a_{strategy}_terminal_aware_child",
        "site_background_electricity_mwh_h": 0.0,
        "site_background_electricity_mwh_h_by_configuration": dict(electricity),
        "site_baseload_ng_mwh_h_by_configuration": (
            dict(ng) if ng is not None else {configuration: 0.0 for configuration in CONFIGURATIONS}
        ),
        "site_residual_steam_t_h_by_configuration": {configuration: 0.0 for configuration in CONFIGURATIONS},
        "site_residual_direct_co2_t_h_by_configuration": (
            dict(residual_co2)
            if residual_co2 is not None
            else {configuration: 0.0 for configuration in CONFIGURATIONS}
        ),
        "wag_generation_yield_overrides_by_configuration": {
            key: dict(value) for key, value in (wag_yields or {}).items()
        },
        "c0_full_site_energy_bridge": None,
        "phase5g_generator_without_legacy_bridge": True,
        "hsm_source_mix_policy_by_configuration": {
            key: dict(value) for key, value in phase5g["hsm_source_mix_policy_by_configuration"].items()
        },
        "phase6a_case_role": strategy,
        "phase6a_market_bidding_or_settlement_layer": False,
        "phase6a_baseload_price_responsive": False,
        "phase6a_export_allowed": False,
        "realised_price_gap_patch_by_timestamp_utc": (
            dict(realised_price_gap_patch) if oracle else None
        ),
    })
    scratch = _resolve(phase["scratch_root"])
    directory = scratch / case_id
    reused = directory.exists() and (directory / "run_summary.json").exists()
    if directory.exists() and not reused:
        raise Phase6AGateError(f"Incomplete benchmark cache must be removed before resume: {case_id}")
    if not directory.exists():
        if not allow_solve_missing:
            raise Phase6AGateError(f"Benchmark cache is incomplete: {case_id}")
        run_closed_loop_feasibility_anchor_reconciliation(
            config_path=_resolve(phase4["phase4"]["physical_config"]),
            output_root=scratch,
            scenario_overrides=overrides,
        )
    artifact = _artifact(directory)
    return case_id, artifact, reused


def _sorted_hourly(artifact: Mapping[str, Any], configuration: str) -> list[Mapping[str, Any]]:
    return sorted(
        (row for row in artifact["hourly"] if row["configuration_id"] == configuration),
        key=lambda row: int(row["executed_hour_index"]),
    )


def _sorted_prices(artifact: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return sorted(artifact["prices"], key=lambda row: int(row["executed_hour_index"]))


def _non_grid_cost(artifact: Mapping[str, Any], configuration: str) -> float:
    return sum(
        _number(row.get("cost_eur"))
        for row in artifact["costs"]
        if row["configuration_id"] == configuration
        and row["price_id"] != "grid_electricity_flat_nl"
    )


def build_settlement_rows(
    *, period: Mapping[str, Any], strategy: str, artifact: Mapping[str, Any],
    point_artifact: Mapping[str, Any], oracle_artifact: Mapping[str, Any],
    quantity_tolerance_mwh: float,
) -> list[dict[str, Any]]:
    point_prices = _sorted_prices(point_artifact)
    oracle_prices = _sorted_prices(oracle_artifact)
    strategy_prices = _sorted_prices(artifact)
    if not (len(point_prices) == len(oracle_prices) == len(strategy_prices)):
        raise Phase6AGateError("Executed price supports differ across deterministic cases.")
    rows: list[dict[str, Any]] = []
    for configuration in CONFIGURATIONS:
        hourly = _sorted_hourly(artifact, configuration)
        if len(hourly) != len(point_prices):
            raise Phase6AGateError("Executed quantity and price supports differ.")
        for index, physical in enumerate(hourly):
            point_price = point_prices[index]
            oracle_price = oracle_prices[index]
            role_price = strategy_prices[index]
            delivery = str(point_price["delivery_timestamp_utc"])
            if delivery != str(oracle_price["delivery_timestamp_utc"]):
                raise Phase6AGateError("Forecast and realised delivery timestamps diverge.")
            realised = _number(oracle_price["price_eur_per_mwh_e"])
            forecast = _number(role_price["price_eur_per_mwh_e"])
            raw_quantity = _number(physical["net_grid_import_mwh"])
            settled = settle_hour(
                bid_quantity_mwh=raw_quantity,
                realised_price_eur_per_mwh=realised,
                negative_tolerance_mwh=quantity_tolerance_mwh,
            )
            quantity = settled["settled_quantity_mwh"]
            info_time = str(role_price["information_available_timestamp_utc"])
            rows.append({
                "period_id": period["period_id"],
                "case_role": strategy,
                "configuration_id": configuration,
                "configuration": SHORT_CONFIGURATION[configuration],
                "replan_index": int(point_price["replan_index"]),
                "executed_hour_index": int(point_price["executed_hour_index"]),
                "delivery_timestamp_utc": delivery,
                "information_available_timestamp_utc": info_time,
                "information_timing": "ex_post_oracle" if strategy == "perfect_foresight_oracle" else "forecast_origin_only",
                "bid_status": "not_submitted_counterfactual" if strategy == "perfect_foresight_oracle" else "submitted_price_taking_purchase_quantity",
                "explicit_process_demand_mwh": _number(physical["represented_gross_electricity_before_background_mwh"]),
                "electricity_baseload_mwh": _number(physical["site_background_electricity_mwh"]),
                "internal_wag_electricity_mwh": _number(physical["WAG_generator_electricity_mwh"]),
                "internal_ng_electricity_mwh": _number(physical["NG_generator_electricity_mwh"]),
                "total_internal_generation_mwh": _number(physical["total_generator_electricity_mwh"]),
                "raw_net_grid_import_mwh": raw_quantity,
                "net_grid_purchase_mwh": quantity,
                "bid_quantity_mwh": quantity,
                **settled,
                "forecast_price_eur_per_mwh": forecast,
                "realised_price_eur_per_mwh": realised,
                "grid_export_mwh": _number(physical["gross_grid_export_mwh"]),
                "quantity_identity_residual_mwh": settled["settled_quantity_mwh"] - raw_quantity,
                "settlement_cost_identity_residual_eur": settled["electricity_procurement_cost_eur"] - quantity * realised,
            })
    return rows


def _case_status(strategy: str, period_id: str, artifact: Mapping[str, Any], reused: bool) -> dict[str, Any]:
    models = artifact["summary"].get("model_size_by_replan", [])
    optimal = all(str(row.get("termination_condition", "")).lower() == "optimal" for row in models)
    return {
        "period_id": period_id,
        "case_role": strategy,
        "case_cache_reused": reused,
        "model_count": len(models),
        "all_models_optimal": optimal,
        "status": "pass" if artifact["summary"].get("status") == "pass" and optimal else "fail",
    }


def _benchmark_summary(rows: Iterable[Mapping[str, Any]], artifacts: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> list[dict[str, Any]]:
    settlement = list(rows)
    output: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        for configuration in CONFIGURATIONS:
            selected = [row for row in settlement if row["case_role"] == strategy and row["configuration_id"] == configuration]
            grid_cost = sum(_number(row["electricity_procurement_cost_eur"]) for row in selected)
            non_grid = sum(
                _non_grid_cost(artifact, configuration)
                for artifact in artifacts[strategy].values()
            )
            output.append({
                "case_role": strategy,
                "configuration_id": configuration,
                "configuration": SHORT_CONFIGURATION[configuration],
                "executed_hours": len(selected),
                "net_grid_purchase_mwh": sum(_number(row["net_grid_purchase_mwh"]) for row in selected),
                "electricity_procurement_cost_eur": grid_cost,
                "other_represented_procurement_cost_eur": non_grid,
                "total_represented_settlement_cost_eur": grid_cost + non_grid,
                "bid_quantity_identity_max_abs_mwh": max(abs(_number(row["quantity_identity_residual_mwh"])) for row in selected),
                "settlement_cost_identity_max_abs_eur": max(abs(_number(row["settlement_cost_identity_residual_eur"])) for row in selected),
            })
    return output


def _benchmark_comparison(summary: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    lookup = {(row["case_role"], row["configuration"]): row for row in summary}
    rows: list[dict[str, Any]] = []
    for configuration in ("C0", "C1"):
        point = lookup[("deterministic_point_forecast", configuration)]
        for benchmark in ("price_insensitive_benchmark", "perfect_foresight_oracle"):
            other = lookup[(benchmark, configuration)]
            rows.append({
                "configuration": configuration,
                "benchmark": benchmark,
                "point_forecast_total_cost_eur": point["total_represented_settlement_cost_eur"],
                "benchmark_total_cost_eur": other["total_represented_settlement_cost_eur"],
                "point_minus_benchmark_eur": _number(point["total_represented_settlement_cost_eur"]) - _number(other["total_represented_settlement_cost_eur"]),
                "interpretation": "oracle_is_ex_post_upper_bound_performance" if benchmark == "perfect_foresight_oracle" else "mandatory_price_insensitive_comparator",
            })
    return rows


def _accounting_checks(rows: Iterable[Mapping[str, Any]], summary: Iterable[Mapping[str, Any]], tolerance: float) -> list[dict[str, Any]]:
    hourly = list(rows)
    summaries = list(summary)
    by_case = {(row["case_role"], row["configuration"]): row for row in summaries}
    checks = [
        {"check_id": "bid_quantity_equals_frozen_net_grid_purchase", "status": "pass" if max(abs(_number(row["quantity_identity_residual_mwh"])) for row in hourly) <= tolerance else "fail"},
        {"check_id": "settlement_quantity_equals_cleared_bid", "status": "pass" if all(math.isclose(_number(row["settled_quantity_mwh"]), _number(row["cleared_quantity_mwh"]), abs_tol=tolerance) for row in hourly) else "fail"},
        {"check_id": "settlement_cost_equals_quantity_times_realised_price", "status": "pass" if max(abs(_number(row["settlement_cost_identity_residual_eur"])) for row in hourly) <= tolerance else "fail"},
        {"check_id": "deterministic_imbalance_is_zero", "status": "pass" if max(abs(_number(row["imbalance_mwh"])) for row in hourly) <= tolerance else "fail"},
        {"check_id": "zero_export_preserved", "status": "pass" if max(abs(_number(row["grid_export_mwh"])) for row in hourly) <= tolerance else "fail"},
        {"check_id": "baseload_constant_and_fixed", "status": "pass" if all(len({round(_number(row["electricity_baseload_mwh"]), 12) for row in hourly if row["configuration"] == configuration}) == 1 for configuration in ("C0", "C1")) else "fail"},
        {"check_id": "executable_bid_information_available_no_later_than_delivery", "status": "pass" if all(datetime.fromisoformat(str(row["information_available_timestamp_utc"])) <= datetime.fromisoformat(str(row["delivery_timestamp_utc"])) for row in hourly if row["case_role"] != "perfect_foresight_oracle") else "fail"},
        {"check_id": "realised_prices_excluded_from_executable_bid_information", "status": "pass" if all(row["information_timing"] == "forecast_origin_only" and datetime.fromisoformat(str(row["information_available_timestamp_utc"])) < datetime.fromisoformat(str(row["delivery_timestamp_utc"])) for row in hourly if row["case_role"] == "deterministic_point_forecast") else "fail"},
        {"check_id": "oracle_information_is_delivery_time", "status": "pass" if all(datetime.fromisoformat(str(row["information_available_timestamp_utc"])) == datetime.fromisoformat(str(row["delivery_timestamp_utc"])) for row in hourly if row["case_role"] == "perfect_foresight_oracle") else "fail"},
        {"check_id": "oracle_is_not_submitted", "status": "pass" if all(row["bid_status"] == "not_submitted_counterfactual" for row in hourly if row["case_role"] == "perfect_foresight_oracle") else "fail"},
        {"check_id": "three_required_cases_present", "status": "pass" if {row["case_role"] for row in summaries} == set(STRATEGIES) else "fail"},
        {"check_id": "point_forecast_not_worse_than_price_insensitive", "status": "pass" if all(_number(by_case[("deterministic_point_forecast", configuration)]["total_represented_settlement_cost_eur"]) <= _number(by_case[("price_insensitive_benchmark", configuration)]["total_represented_settlement_cost_eur"]) + tolerance for configuration in ("C0", "C1")) else "fail"},
        {"check_id": "perfect_foresight_not_worse_than_point_forecast", "status": "pass" if all(_number(by_case[("perfect_foresight_oracle", configuration)]["total_represented_settlement_cost_eur"]) <= _number(by_case[("deterministic_point_forecast", configuration)]["total_represented_settlement_cost_eur"]) + tolerance for configuration in ("C0", "C1")) else "fail"},
    ]
    return checks


def _persist(
    *, config_path: Path, config: Mapping[str, Any], phase: Mapping[str, Any],
    da_contract_path: Path, electricity_contract_path: Path, heldout_path: Path,
    realised_price_gap_supplement_path: Path,
    case_status: list[dict[str, Any]], physical_checks: list[dict[str, Any]],
    accounting_checks: list[dict[str, Any]], settlement_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]], comparison_rows: list[dict[str, Any]],
    checkpoint: Mapping[str, Any], started: float,
) -> dict[str, Any]:
    output = _resolve(config["output_root"])
    if output.exists():
        raise Phase6AGateError("Phase-6A governed output root already exists.")
    output.mkdir(parents=True)
    (output / "resolved_config.yaml").write_text(yaml.safe_dump(dict(config), sort_keys=False), encoding="utf-8")
    _write_csv(output / "deterministic_da_contract_snapshot.csv", load_da_contract(da_contract_path))
    _write_csv(output / "case_status.csv", case_status)
    _write_csv(output / "physical_checks.csv", physical_checks)
    _write_csv(output / "timing_and_accounting_checks.csv", accounting_checks)
    _write_csv(output / "da_bid_settlement_hourly.csv", settlement_rows)
    _write_csv(output / "benchmark_summary.csv", summary_rows)
    _write_csv(output / "benchmark_comparison.csv", comparison_rows)
    _write_json(output / "checkpoint_decision.json", checkpoint)
    manifest_paths = {
        "config": config_path,
        "da_contract": da_contract_path,
        "electricity_contract": electricity_contract_path,
        "heldout_period_contract": heldout_path,
        "realised_price_gap_supplement": realised_price_gap_supplement_path,
        "phase5i_checkpoint": _resolve(phase["phase5i_checkpoint"]),
        "phase5i_fingerprint_manifest": _resolve(phase["phase5i_fingerprint_manifest"]),
    }
    _write_json(output / "input_manifest.json", {
        "inputs": [{"role": role, "path": _portable(path), "sha256": _sha256(path)} for role, path in manifest_paths.items()]
    })
    phase5i_fingerprints = _read_json(
        _resolve(phase["phase5i_fingerprint_manifest"])
    )
    fingerprint = {
        "git_head": _git_head(),
        "phase5i_model_fingerprint_sha256": phase5i_fingerprints["model_fingerprint_sha256"],
        "phase5i_hsm_policy_fingerprint_sha256": phase5i_fingerprints["hsm_policy_fingerprint_sha256"],
        "phase5i_forecast_input_fingerprints_sha256": phase5i_fingerprints["forecast_input_fingerprints_sha256"],
        "electricity_baseload_contract_sha256": _sha256(electricity_contract_path),
        "da_contract_sha256": _sha256(da_contract_path),
        "phase6a_runner_sha256": _sha256(Path(__file__).resolve()),
        "physical_runner_sha256": _sha256(
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation.py"
        ),
        "price_interface_sha256": _sha256(
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c5p_bf_price_series_interface.py"
        ),
        "physical_builder_sha256": _sha256(
            REPO_ROOT / "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py"
        ),
        "heldout_period_contract_sha256": _sha256(heldout_path),
        "realised_price_gap_supplement_sha256": _sha256(
            realised_price_gap_supplement_path
        ),
    }
    _write_json(output / "fingerprint_manifest.json", fingerprint)
    _write_json(output / "code_version.json", {"git_head": _git_head(), "dirty_worktree_preserved": True})
    _write_json(output / "registry_entry.json", {
        "run_id": RUN_ID, "run_class": config["run_class"], "output_policy": config["output_policy"],
        "lineage_role": config["lineage_role"], "decision": checkpoint["decision"],
    })
    warnings = (
        "- The bid is a deterministic price-taking purchase quantity with full acceptance; no bid-price curve or imbalance market is represented.\n"
        "- The 10% electricity baseload is a validation-selected aggregate abstraction, not observed demand or flexibility.\n"
        "- Perfect foresight is an ex-post performance oracle only. Stochasticity, CVaR, mFRR, ETS, export and product revenue remain outside scope.\n"
    )
    (output / "warnings_and_limitations.md").write_text(warnings, encoding="utf-8")
    (output / "README.md").write_text(
        "# Phase 6A deterministic DA gate\n\nPoint-forecast quantity bids are settled at realised DA prices and compared with flat-price and perfect-foresight physical schedules around the frozen Phase-5I boundary.\n",
        encoding="utf-8",
    )
    result = {
        **dict(checkpoint),
        "runtime_seconds": time.perf_counter() - started,
        "governed_output_size_bytes": sum(path.stat().st_size for path in output.iterdir() if path.is_file()),
        "fingerprints": fingerprint,
    }
    _write_json(output / "run_summary.json", result)
    return result


def run_phase6a(
    config_path: str | Path = CONFIG_PATH, *, refresh_from_cache: bool = False,
    resume_incomplete: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    phase = config["phase6a"]
    if _git_head() != str(phase["expected_parent_head"]):
        raise Phase6AGateError("Phase-6A requires the preserved parent HEAD.")
    checkpoint5i = _read_json(_resolve(phase["phase5i_checkpoint"]))
    if checkpoint5i["decision"] != "represented_boundary_deterministic_model_frozen_for_phase6" or checkpoint5i["status"] != "pass":
        raise Phase6AGateError("Phase-5I did not authorize Phase 6A.")
    da_contract_path = _resolve(phase["da_contract"])
    load_da_contract(da_contract_path)
    realised_price_gap_supplement_path = _resolve(
        phase["realised_price_gap_supplement"]
    )
    realised_price_gap_patch = load_realised_price_gap_supplement(
        realised_price_gap_supplement_path
    )
    electricity_contract_path = _resolve(phase["electricity_contract"])
    contract_rows = load_selected_contract(electricity_contract_path)
    electricity = electricity_maps(contract_rows)
    if any(row["residual_family"] == "electricity" and (row["status"] != "heldout_validated_promoted" or row["executable"] != "true") for row in contract_rows):
        raise Phase6AGateError("Only the promoted Phase-5I electricity contract may enter Phase 6A.")
    heldout_path = _resolve(phase["held_out_contract"])
    periods, _ = held_out_contract(heldout_path)
    if len(periods) != int(phase["expected_period_count"]):
        raise Phase6AGateError("Frozen held-out period count changed.")
    phase5i_artifacts = _load_phase5i_artifacts(_resolve(phase["phase5i_case_cache"]), periods)
    scratch = _resolve(phase["scratch_root"])
    if refresh_from_cache and resume_incomplete:
        raise Phase6AGateError("Cache refresh and incomplete-run resume are mutually exclusive.")
    if scratch.exists() and not (refresh_from_cache or resume_incomplete):
        raise Phase6AGateError("Phase-6A benchmark scratch already exists.")
    scratch.mkdir(parents=True, exist_ok=True)
    phase5g_config = load_phase5g_config(_resolve(phase["phase5g_config"]))
    phase5g = dict(phase5g_config["phase5g"])
    phase5g["scratch_root"] = phase["scratch_root"]
    parent, phase4, terminal_target = _dependencies(phase5g)
    if _select_solver()[1] is None:
        raise Phase6AGateError("Gurobi is unavailable before Phase-6A benchmark execution.")
    install_terminal_validation_extension()
    artifacts: dict[str, dict[str, Mapping[str, Any]]] = {
        "deterministic_point_forecast": dict(phase5i_artifacts),
        "price_insensitive_benchmark": {},
        "perfect_foresight_oracle": {},
    }
    case_status = [
        _case_status("deterministic_point_forecast", period_id, artifact, True)
        for period_id, artifact in phase5i_artifacts.items()
    ]
    for strategy in ("price_insensitive_benchmark", "perfect_foresight_oracle"):
        for period in periods:
            _, artifact, reused = _benchmark_case(
                strategy=strategy, period=period, phase=phase, phase5g=phase5g,
                parent=parent, phase4=phase4, terminal_target=terminal_target,
                electricity=electricity, allow_solve_missing=not refresh_from_cache,
                realised_price_gap_patch=realised_price_gap_patch,
            )
            artifacts[strategy][str(period["period_id"])] = artifact
            case_status.append(_case_status(strategy, str(period["period_id"]), artifact, reused))
    zero = {configuration: 0.0 for configuration in CONFIGURATIONS}
    physical: list[dict[str, Any]] = []
    for strategy, strategy_artifacts in artifacts.items():
        physical += _physical_checks(strategy, strategy_artifacts, electricity, zero, float(phase["physical_balance_tolerance_mwh"]))
        physical += _hsm_checks(strategy, strategy_artifacts, phase5g, float(phase["physical_balance_tolerance_mwh"]))
        physical += residual_zero_checks(strategy_artifacts, float(phase["physical_balance_tolerance_mwh"]))
    settlement_rows: list[dict[str, Any]] = []
    period_lookup = {str(row["period_id"]): row for row in periods}
    for strategy in STRATEGIES:
        for period_id, artifact in artifacts[strategy].items():
            settlement_rows += build_settlement_rows(
                period=period_lookup[period_id], strategy=strategy, artifact=artifact,
                point_artifact=artifacts["deterministic_point_forecast"][period_id],
                oracle_artifact=artifacts["perfect_foresight_oracle"][period_id],
                quantity_tolerance_mwh=float(phase["physical_balance_tolerance_mwh"]),
            )
    summary_rows = _benchmark_summary(settlement_rows, artifacts)
    comparison_rows = _benchmark_comparison(summary_rows)
    accounting = _accounting_checks(settlement_rows, summary_rows, float(phase["settlement_tolerance_eur"]))
    evaluated_models = sum(int(row["model_count"]) for row in case_status)
    new_models = sum(int(row["model_count"]) for row in case_status if not row["case_cache_reused"])
    passed = (
        evaluated_models == int(phase["expected_evaluated_models"])
        and all(row["status"] == "pass" for row in case_status + physical + accounting)
    )
    checkpoint = {
        "run_id": RUN_ID,
        "decision": phase["decision_on_pass"] if passed else phase["decision_on_fail"],
        "status": "pass" if passed else "fail",
        "phase5i_freeze_decision_preserved": checkpoint5i["decision"],
        "evaluated_models": evaluated_models,
        "new_benchmark_models": int(phase["expected_new_benchmark_models"]),
        "models_solved_this_invocation": new_models,
        "all_models_optimal": all(row["all_models_optimal"] for row in case_status),
        "deterministic_point_forecast_bid": True,
        "price_insensitive_benchmark": True,
        "perfect_foresight_oracle": True,
        "realised_prices_used_by_executable_bid": False,
        "settlement_uses_realised_prices": True,
        "electricity_baseload_fixed_net_demand": True,
        "residual_ng_steam_co2_zero": True,
        "export_zero": True,
        "stochasticity_cvar_mfrr_absent": True,
        "next_gate": phase["next_gate_on_pass"] if passed else "blocked",
        "failure_count": sum(row["status"] != "pass" for row in case_status + physical + accounting),
        "evidence_regenerated_from_completed_cache": refresh_from_cache,
    }
    return _persist(
        config_path=config_file, config=config, phase=phase, da_contract_path=da_contract_path,
        electricity_contract_path=electricity_contract_path, heldout_path=heldout_path,
        realised_price_gap_supplement_path=realised_price_gap_supplement_path,
        case_status=case_status, physical_checks=physical, accounting_checks=accounting,
        settlement_rows=settlement_rows, summary_rows=summary_rows,
        comparison_rows=comparison_rows, checkpoint=checkpoint, started=started,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--refresh-from-cache", action="store_true")
    parser.add_argument("--resume-incomplete", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_phase6a(
        args.config, refresh_from_cache=args.refresh_from_cache,
        resume_incomplete=args.resume_incomplete,
    ), indent=2))


if __name__ == "__main__":
    main()
