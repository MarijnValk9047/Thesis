"""Phase 5D source-backed, non-endogenous C0 NG mechanism closure."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
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
    _read_csv,
    _read_json,
    _resolve,
    _select_solver,
    _sha256,
    install_terminal_validation_extension,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT
from .wag_development_controller_contract import (
    hsm_reheat_mwh_per_t_hrc,
    load_development_controller_profile,
)


RUN_ID = "steel_c5_phase5d_source_backed_ng_mechanism_closure_v1_20260727"
CONFIG_PATH = REPO_ROOT / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase5d_source_backed_ng_mechanism_closure.yaml"
EXPECTED_PERIODS = ("validation_2024-02-12", "validation_2024-07-01")


class Phase5DMechanismClosureError(RuntimeError):
    pass


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


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
    phase = payload["phase5d"]
    if payload.get("run_id") != RUN_ID or payload.get("output_policy") != "minimal":
        raise Phase5DMechanismClosureError("Phase 5D identity or output policy changed.")
    if tuple(row["period_id"] for row in phase["periods"]) != EXPECTED_PERIODS:
        raise Phase5DMechanismClosureError("Phase 5D DEVELOPMENT periods changed.")
    policy = phase["policy"]
    if policy.get("flexible_ng_allocation_policy") != "normal_case_reference_exact_hourly":
        raise Phase5DMechanismClosureError("The source-emulation allocation policy changed.")
    if not math.isclose(float(policy["flexible_heat_ng_pj_lhv_y"]), 1.65, abs_tol=1e-12):
        raise Phase5DMechanismClosureError("The accepted 1.65 PJ/y normal-case value changed.")
    if not math.isclose(
        float(policy["flexible_heat_ng_pj_lhv_y"])
        + float(policy["flexible_heat_wag_pj_lhv_y"]),
        float(policy["total_flexible_heat_service_pj_lhv_y"]),
        abs_tol=1e-12,
    ):
        raise Phase5DMechanismClosureError("The conserved flexible-heat service no longer closes.")
    if any(
        bool(policy[key])
        for key in (
            "external_export_allowed",
            "changes_total_heat_demand",
            "changes_physics",
            "changes_prices",
            "changes_terminal_bands",
            "changes_production_targets",
            "held_out_periods_used",
        )
    ):
        raise Phase5DMechanismClosureError("Phase 5D scope lock changed.")
    return payload


def mechanism_candidates() -> list[dict[str, str]]:
    return [
        {
            "candidate_id": "athanasiadis_normal_case_flexible_heat_allocation",
            "decision": "execute",
            "reason": "accepted 3.07 PJ/y service and 1.65 PJ/y normal-case NG interpretation",
        },
        {
            "candidate_id": "force_hsm_or_pefa_ng_share",
            "decision": "screen_out",
            "reason": "no source-backed C0 plant-specific NG share; existing heat balances already close with WAG",
        },
        {
            "candidate_id": "force_boiler_ng_share",
            "decision": "screen_out",
            "reason": "pressure-level accounting closes with WAG and lacks observed C0 fuel-share evidence",
        },
        {
            "candidate_id": "force_generator_ng_share",
            "decision": "screen_out",
            "reason": "available unit fuel split is C1-specific and cannot be imported into C0",
        },
    ]


def _sum(rows: Iterable[Mapping[str, Any]], field: str) -> float:
    return sum(float(row.get(field) or 0.0) for row in rows)


def heat_verification_rows(period_id: str, hourly: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [row for row in hourly if row.get("configuration_id") == C0_CONFIGURATION]
    profile = load_development_controller_profile(C0_CONFIGURATION)
    hours = len(rows)
    definitions = (
        (
            "HSM_reheat",
            _sum(rows, "C0_HSM_final_product_t") * hsm_reheat_mwh_per_t_hrc(),
            _sum(rows, "BFG_to_HSM_mwh") + _sum(rows, "COG_to_HSM_mwh") + _sum(rows, "BOFG_to_HSM_mwh"),
            _sum(rows, "NG_to_HSM_mwh"),
            "BFG+COG+BOFG+NG=HSM_reheat_demand",
        ),
        (
            "PEFA_malerij",
            profile.pefa_bofg_mwh_h * hours,
            _sum(rows, "BOFG_to_PEFA_malerij_mwh"),
            _sum(rows, "NG_to_PEFA_malerij_mwh"),
            "BOFG+NG=PEFA_malerij_heat_demand",
        ),
        (
            "PEFA_branderij",
            profile.pefa_cog_mwh_h * hours,
            _sum(rows, "COG_to_PEFA_branderij_mwh"),
            _sum(rows, "NG_to_PEFA_branderij_mwh"),
            "COG+NG=PEFA_branderij_heat_demand",
        ),
    )
    return [
        {
            "period_id": period_id,
            "heat_sink": sink,
            "demand_mwh": round(demand, 6),
            "wag_supply_mwh": round(wag, 6),
            "ng_supply_mwh": round(ng, 6),
            "balance_residual_mwh": round(wag + ng - demand, 9),
            "wag_share_fraction": round(wag / demand, 9) if demand else 0.0,
            "equation": equation,
        }
        for sink, demand, wag, ng, equation in definitions
    ]


def _metrics(period_id: str, artifact: Mapping[str, Any]) -> dict[str, Any]:
    rows = [row for row in artifact["hourly"] if row.get("configuration_id") == C0_CONFIGURATION]
    hours = len(rows)
    annual = HOURS_PER_YEAR / hours
    named_ng = (
        _sum(rows, "full_site_energy_bridge_named_ng_mwh")
        + _sum(rows, "NG_to_HSM_mwh")
        + _sum(rows, "NG_to_PEFA_malerij_mwh")
        + _sum(rows, "NG_to_PEFA_branderij_mwh")
        + _sum(rows, "NG_to_boiler_mwh")
        + _sum(rows, "generator_named_ng_mwh")
    )
    core_named_ng = (
        _sum(rows, "NG_to_HSM_mwh")
        + _sum(rows, "NG_to_PEFA_malerij_mwh")
        + _sum(rows, "NG_to_PEFA_branderij_mwh")
        + _sum(rows, "NG_to_boiler_mwh")
        + _sum(rows, "generator_named_ng_mwh")
    )
    return {
        "period_id": period_id,
        "executed_hours": hours,
        "final_product_t": _sum(rows, "final_product_output_t"),
        "hsm_route_output_t": _sum(rows, "C0_HSM_final_product_t"),
        "dsp_route_output_t": _sum(rows, "C0_DSP_final_product_t"),
        "gross_grid_import_mwh": _sum(rows, "gross_grid_import_mwh"),
        "gross_grid_export_mwh": _sum(rows, "gross_grid_export_mwh"),
        "wag_generator_electricity_mwh": _sum(rows, "WAG_generator_electricity_mwh"),
        "wag_electricity_twh_e_y_annual_equivalent": _sum(rows, "WAG_generator_electricity_mwh") * annual / 1e6,
        "fixed_ng_mwh": _sum(rows, "full_site_fixed_ng_component_mwh"),
        "flexible_heat_ng_mwh": _sum(rows, "flexible_other_site_heat_ng_mwh"),
        "flexible_heat_wag_mwh": _sum(rows, "BFG_to_flexible_other_site_heat_mwh") + _sum(rows, "COG_to_flexible_other_site_heat_mwh") + _sum(rows, "BOFG_to_flexible_other_site_heat_mwh"),
        "core_named_ng_mwh": core_named_ng,
        "named_ng_pj_lhv_y_annual_equivalent": named_ng * annual * PJ_PER_MWH,
        "total_wag_pj_lhv_y_annual_equivalent": _sum(rows, "WAG_generated") * annual * PJ_PER_MWH,
    }


def _period_checks(
    config: Mapping[str, Any], metrics: Mapping[str, Any], base: Mapping[str, str],
    heat: Iterable[Mapping[str, Any]], artifact: Mapping[str, Any],
) -> list[dict[str, Any]]:
    gates = config["phase5d"]["gates"]
    tol_heat = float(gates["heat_balance_tolerance_mwh"])
    tol_prod = float(gates["production_tolerance_t"])
    expected_flexible = 1.65 / (HOURS_PER_YEAR * PJ_PER_MWH) * float(metrics["executed_hours"])
    expected_service = 3.07 / (HOURS_PER_YEAR * PJ_PER_MWH) * float(metrics["executed_hours"])
    base_hsm = float(base["hsm_route_output_t"])
    base_dsp = float(base["dsp_route_output_t"])
    checks = [
        ("all_models_optimal", len(artifact["models"]) == 14 and all(row.get("solver_status", "").lower() == "ok" and row.get("termination_condition", "").lower() == "optimal" for row in artifact["models"]), len(artifact["models"]), 14),
        ("all_child_validation_checks_pass", all(row.get("status") == "pass" for row in artifact["validation"]), sum(row.get("status") != "pass" for row in artifact["validation"]), 0),
        ("production_contained", abs(float(metrics["final_product_t"]) - float(base["final_product_t"])) <= tol_prod, float(metrics["final_product_t"]), float(base["final_product_t"])),
        ("no_export_preserved", abs(float(metrics["gross_grid_export_mwh"])) <= 1e-9, float(metrics["gross_grid_export_mwh"]), 0.0),
        ("fixed_ng_invariant", abs(float(metrics["fixed_ng_mwh"]) - float(base["fixed_ng_mwh"])) <= float(gates["fixed_ng_tolerance_mwh"]), float(metrics["fixed_ng_mwh"]), float(base["fixed_ng_mwh"])),
        ("flexible_ng_matches_source_policy", abs(float(metrics["flexible_heat_ng_mwh"]) - expected_flexible) <= tol_heat, float(metrics["flexible_heat_ng_mwh"]), expected_flexible),
        ("flexible_heat_service_conserved", abs(float(metrics["flexible_heat_ng_mwh"]) + float(metrics["flexible_heat_wag_mwh"]) - expected_service) <= tol_heat, float(metrics["flexible_heat_ng_mwh"]) + float(metrics["flexible_heat_wag_mwh"]), expected_service),
        ("core_hsm_pefa_boiler_generator_ng_remains_zero", abs(float(metrics["core_named_ng_mwh"])) <= tol_heat, float(metrics["core_named_ng_mwh"]), 0.0),
        ("route_mix_within_one_percent_of_comparator", max(abs(float(metrics["hsm_route_output_t"]) / base_hsm - 1.0), abs(float(metrics["dsp_route_output_t"]) / base_dsp - 1.0)) <= 0.01, max(abs(float(metrics["hsm_route_output_t"]) / base_hsm - 1.0), abs(float(metrics["dsp_route_output_t"]) / base_dsp - 1.0)), 0.01),
        ("total_wag_generation_invariant_within_0_01_pj_y", abs(float(metrics["total_wag_pj_lhv_y_annual_equivalent"]) - float(base["total_wag_pj_y_annual_equivalent"])) <= 0.01, float(metrics["total_wag_pj_lhv_y_annual_equivalent"]), float(base["total_wag_pj_y_annual_equivalent"])),
        ("named_ng_anchor_close", abs(float(metrics["named_ng_pj_lhv_y_annual_equivalent"]) / float(gates["anchor_ng_pj_lhv_y"]) - 1.0) <= float(gates["anchor_close_threshold_fraction"]), float(metrics["named_ng_pj_lhv_y_annual_equivalent"]), float(gates["anchor_ng_pj_lhv_y"])),
    ]
    checks.extend(
        (f"{row['heat_sink']}_balance", abs(float(row["balance_residual_mwh"])) <= tol_heat, float(row["balance_residual_mwh"]), 0.0)
        for row in heat
    )
    return [
        {"period_id": metrics["period_id"], "check_id": check_id, "status": "pass" if passed else "fail", "actual": actual, "reference_or_limit": reference}
        for check_id, passed, actual, reference in checks
    ]


def run_phase5d(config_path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    started = time.perf_counter()
    config = load_config(config_path)
    phase = config["phase5d"]
    parent = yaml.safe_load(_resolve(phase["parent_phase5b_config"]).read_text(encoding="utf-8"))
    phase4 = load_phase4_config(_resolve(parent["phase5b"]["phase4_config"]))
    check_phase4_config(phase4)
    targets = {row["period_id"]: row for row in _read_json(_resolve(parent["phase5b"]["phase4_target_contract"]))["targets"]}
    base_rows = {
        row["period_id"]: row
        for row in _read_csv(_resolve(phase["parent_phase5b_metrics"]))
        if row["policy_id"] == "accepted_no_export_comparator"
    }
    output = _resolve(config["output_root"])
    scratch = _resolve(phase["scratch_root"])
    if output.exists():
        raise Phase5DMechanismClosureError("Phase 5D governed output root already exists.")
    if _select_solver()[1] is None:
        raise Phase5DMechanismClosureError("Gurobi is unavailable before the first solve.")
    install_terminal_validation_extension()
    output.mkdir(parents=True)
    scratch.mkdir(parents=True, exist_ok=True)
    (output / "resolved_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    metrics_rows: list[dict[str, Any]] = []
    heat_rows: list[dict[str, Any]] = []
    check_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    for index, period in enumerate(phase["periods"]):
        if index == 1 and any(row["status"] != "pass" for row in check_rows):
            case_rows.append({"period_id": period["period_id"], "status": "not_started_february_gate_failed"})
            break
        target = targets[period["period_id"]]
        case = {
            "case_id": f"phase5d__{period['period_id'].replace('-', '_')}__normal_case_flexible_heat",
            "dataset_split": period["dataset_split"],
            "forecast_start_origin_utc": period["frozen_forecast_start_origin_utc"],
            "flat_price_eur_per_mwh": None,
            "price_field": "y_pred",
            "perfect_foresight_oracle": False,
        }
        overrides = _case_overrides(
            phase4,
            case,
            _resolve(parent["phase5b"]["forecast_run_root"]),
            int(target["campaign_terminal_executed_hours"]),
            target["terminal_band"],
        )
        overrides["lineage_role"] = "phase5d_source_backed_ng_mechanism_child"
        overrides["c0_full_site_energy_bridge"]["flexible_ng_allocation_policy"] = phase["policy"]["flexible_ng_allocation_policy"]
        case_directory = scratch / case["case_id"]
        if not case_directory.exists():
            run_closed_loop_feasibility_anchor_reconciliation(
                config_path=_resolve(phase4["phase4"]["physical_config"]),
                output_root=scratch,
                scenario_overrides=overrides,
            )
        artifact = _artifact(case_directory)
        metrics = _metrics(period["period_id"], artifact)
        heat = heat_verification_rows(period["period_id"], artifact["hourly"])
        checks = _period_checks(config, metrics, base_rows[period["period_id"]], heat, artifact)
        metrics_rows.append(metrics)
        heat_rows.extend(heat)
        check_rows.extend(checks)
        case_rows.append({
            "period_id": period["period_id"],
            "case_id": case["case_id"],
            "status": "pass" if all(row["status"] == "pass" for row in checks) else "fail",
            "model_count": len(artifact["models"]),
        })

    passed = len(case_rows) == 2 and all(row["status"] == "pass" for row in case_rows)
    decision = (
        "promote_source_emulation_policy_authorize_frozen_held_out_then_phase6_design"
        if passed
        else "retain_endogenous_no_export_central_and_stop"
    )
    _write_csv(output / "mechanism_candidates.csv", mechanism_candidates())
    _write_csv(output / "case_status.csv", case_rows)
    _write_csv(output / "metrics_summary.csv", metrics_rows)
    paired_rows = []
    for metrics in metrics_rows:
        base = base_rows[metrics["period_id"]]
        base_wag = float(base["wag_electricity_twh_e_y_annual_equivalent"])
        candidate_wag = float(metrics["wag_electricity_twh_e_y_annual_equivalent"])
        paired_rows.append({
            "period_id": metrics["period_id"],
            "base_named_ng_pj_lhv_y": (float(base["fixed_ng_mwh"]) + float(base["flexible_heat_ng_mwh"]) + float(base["generator_ng_mwh"])) * (HOURS_PER_YEAR / float(base["executed_hours"])) * PJ_PER_MWH,
            "candidate_named_ng_pj_lhv_y": metrics["named_ng_pj_lhv_y_annual_equivalent"],
            "real_ng_anchor_pj_lhv_y": float(phase["gates"]["anchor_ng_pj_lhv_y"]),
            "base_wag_electricity_twh_e_y": base_wag,
            "candidate_wag_electricity_twh_e_y": candidate_wag,
            "wag_electricity_change_twh_e_y": candidate_wag - base_wag,
            "wag_electricity_anchor_twh_e_y": 2.528,
            "candidate_wag_electricity_gap_fraction": abs(candidate_wag / 2.528 - 1.0),
            "base_grid_import_mwh": float(base["gross_grid_import_mwh"]),
            "candidate_grid_import_mwh": metrics["gross_grid_import_mwh"],
            "grid_import_change_mwh": float(metrics["gross_grid_import_mwh"]) - float(base["gross_grid_import_mwh"]),
            "hsm_route_change_t": float(metrics["hsm_route_output_t"]) - float(base["hsm_route_output_t"]),
            "dsp_route_change_t": float(metrics["dsp_route_output_t"]) - float(base["dsp_route_output_t"]),
        })
    _write_csv(output / "paired_anchor_and_energy_comparison.csv", paired_rows)
    _write_csv(output / "heat_demand_supply_verification.csv", heat_rows)
    _write_csv(output / "physical_and_anchor_guardrails.csv", check_rows)
    _write_csv(output / "source_basis.csv", [
        {"evidence_id": "athanasiadis_secondary_loads", "value": "mandatory electricity, natural-gas or steam loads", "role": "mechanism precedent", "source": "Athanasiadis thesis report p20"},
        {"evidence_id": "athanasiadis_normal_case_flexible_ng", "value": "1.65 PJ_LHV/y", "role": "source-emulation policy allocation", "source": "accepted interpretation of Figure 69 normal case minus low-case Figures 79 and 84"},
        {"evidence_id": "conserved_flexible_heat_service", "value": "3.07 PJ_LHV/y", "role": "unchanged physical service", "source": "accepted Phase-1 benchmark overlay"},
        {"evidence_id": "real_site_ng_anchor", "value": "9.666 PJ_LHV/y", "role": "primary comparison anchor", "source": "accepted Tata/Athanasiadis real-site context"},
        {"evidence_id": "athanasiadis_table8_ng_context", "value": "33243.63 m3 average; approximately 10.425 PJ_LHV/y", "role": "supporting model context only", "source": "Athanasiadis thesis Table 8 report p97"},
    ])
    _write_json(output / "input_manifest.json", {
        "config": {"path": str(Path(config_path).resolve().relative_to(REPO_ROOT)).replace("\\", "/"), "sha256": _sha256(Path(config_path).resolve())},
        "phase4_config": {"path": parent["phase5b"]["phase4_config"], "sha256": _sha256(_resolve(parent["phase5b"]["phase4_config"]))},
        "phase4_target_contract": {"path": parent["phase5b"]["phase4_target_contract"], "sha256": _sha256(_resolve(parent["phase5b"]["phase4_target_contract"]))},
        "parent_phase5b_metrics": {"path": phase["parent_phase5b_metrics"], "sha256": _sha256(_resolve(phase["parent_phase5b_metrics"]))},
        "policy": dict(phase["policy"]),
    })
    checkpoint = {
        "run_id": RUN_ID,
        "status": "pass" if passed else "stop",
        "decision": decision,
        "candidate_promoted": passed,
        "july_started": any(row["period_id"] == EXPECTED_PERIODS[1] and row["status"] != "not_started_february_gate_failed" for row in case_rows),
        "held_out_periods_used": False,
        "phase6_design_authorized": passed,
        "phase6_execution_authorized": False,
        "next_gate": "frozen_terminal_aware_held_out_validation_of_promoted_policy" if passed else "stop",
        "wall_time_seconds": round(time.perf_counter() - started, 3),
    }
    _write_json(output / "checkpoint_decision.json", checkpoint)
    (output / "README.md").write_text(
        "# Phase 5D source-backed NG mechanism closure\n\n"
        f"Decision: `{decision}`.\n\n"
        "The only executed change is an opt-in allocation of 1.65 PJ-LHV/y NG inside the already conserved 3.07 PJ-LHV/y flexible other-site heat service. Total heat demand, plant physics, prices, production targets, terminal bands, export economics, and held-out periods are unchanged.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- These are two DEVELOPMENT weeks and annual-equivalent rates, not an annual backtest.\n"
        "- The 1.65 PJ/y NG split is a transparent source-emulation operating policy, not an endogenously discovered burner preference.\n"
        "- HSM and both PEFA stages remain WAG-supplied; no plant-specific NG share was invented.\n"
        "- Export, ETS, settlement, stochasticity, CVaR and mFRR remain outside this run.\n",
        encoding="utf-8",
    )
    return checkpoint


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG_PATH))
    args = parser.parse_args()
    print(json.dumps(run_phase5d(args.config), indent=2))


if __name__ == "__main__":
    main()
