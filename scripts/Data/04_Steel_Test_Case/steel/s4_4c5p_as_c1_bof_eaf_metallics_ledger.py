"""Bounded C1 BOF/EAF metallics-ledger capacity diagnostic.

The ledger is optional and source-backed.  It corrects the retained BOF
hot-metal-to-liquid-steel proxy only when separate BOF/EAF scrap demand caps
and a bounded site total are supplied.  It is not a free scrap pool and does
not alter the active development-input tables.
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pyomo.environ import Objective, maximize, value

from .model import collect_model_stats
from .s4_4c5p_am_downstream_origin_route_ledger import build_c1_uniform_import_routing, load_source_values
from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    _apply_solver_time_limit,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
    _select_solver,
)


DEFAULT_CONFIG = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "configs" / "steel_c1_bof_eaf_metallics_ledger.yaml"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
HOURS_PER_YEAR = 8760.0


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _annualise(value_horizon: float, horizon_hours: int) -> float:
    return value_horizon * HOURS_PER_YEAR / float(horizon_hours)


def _scaled_cap(annual_t_y: float, horizon_hours: int) -> float:
    return annual_t_y * horizon_hours / HOURS_PER_YEAR


def _load_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("scenarios"), list):
        raise ValueError("C1 BOF/EAF metallics-ledger config requires a mapping with scenarios.")
    return payload


def _scenario_maps(config: dict[str, Any], scenario: dict[str, Any], horizon_hours: int) -> tuple[dict[str, float] | None, dict[str, float] | None, dict[str, float] | None]:
    if not bool(scenario.get("apply_bof_eaf_ledger")):
        return None, None, None
    eaf = {key: float(value) for key, value in config["eaf_material_balance"].items()}
    bof = {key: float(value) for key, value in config["bof_material_balance"].items()}
    ledger = {
        "site_total_scrap_supply_cap_t": _scaled_cap(float(scenario["annual_site_scrap_cap_t_y"]), horizon_hours),
        "bof_scrap_supply_cap_t": _scaled_cap(float(scenario["annual_bof_scrap_cap_t_y"]), horizon_hours),
        "eaf_scrap_supply_cap_t": _scaled_cap(float(scenario["annual_eaf_scrap_cap_t_y"]), horizon_hours),
    }
    return eaf, bof, ledger


def _sum(model: Any, name: str) -> float:
    component = getattr(model, name)
    return sum(float(value(component[t])) for t in model.TIME)


def solve_capacity_case(config: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    horizon_hours = int(config["horizon_hours"])
    eaf_map, bof_map, ledger = _scenario_maps(config, scenario, horizon_hours)
    annual_target_mt_y = scenario.get("annual_target_mt_y")
    base_inputs = _build_c1_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=horizon_hours,
        include_retained_bf_bof=True,
    )
    target_multiplier = 1.0
    if annual_target_mt_y not in (None, ""):
        annual_target_t_y = float(annual_target_mt_y) * 1_000_000.0
        if annual_target_t_y <= 0.0:
            raise ValueError("annual_target_mt_y must be positive when supplied.")
        target_horizon_t = annual_target_t_y * horizon_hours / HOURS_PER_YEAR
        target_multiplier = target_horizon_t / base_inputs.final_product_target_t
    inputs = _build_c1_inputs(
        _load_tables(S44B_INPUT_DIR),
        horizon_hours_override=horizon_hours,
        target_multiplier=target_multiplier,
        include_retained_bf_bof=True,
    )
    model = _build_c1_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        enable_internal_wag_power=True,
        development_controller_activation="full",
        c1_retained_route_policy="quota_driven_topology",
        commitment_granularity="daily_binary_hourly_throughput",
        downstream_origin_routing=build_c1_uniform_import_routing(load_source_values(), horizon_hours=horizon_hours),
        eaf_material_balance=eaf_map,
        bof_material_balance=bof_map,
        scrap_supply_ledger=ledger,
        c1_coke_chain_reconciliation={key: float(value) for key, value in config["source_coke_chain"].items()},
    )
    target_required = annual_target_mt_y not in (None, "")
    if not target_required:
        model.final_product_fulfilment.deactivate()
        model.static_price_naive_objective.deactivate()
        model.capacity_probe_objective = Objective(expr=sum(model.final_product_output[t] for t in model.TIME), sense=maximize)
    solver_name, solver = _select_solver()
    if solver_name is None or solver is None:
        return {"scenario_id": scenario["scenario_id"], "status": "blocked", "caveat": "No configured solver is available."}
    _apply_solver_time_limit(solver_name, solver, float(config["solver_time_limit_seconds"]))
    start = time.perf_counter()
    try:
        result = solver.solve(model)
    except RuntimeError as exc:
        stats = collect_model_stats(model)
        return {
            "scenario_id": scenario["scenario_id"], "status": "infeasible", "solver_name": solver_name,
            "runtime_seconds": round(time.perf_counter() - start, 6), "variable_count": stats.variables,
            "binary_count": stats.binaries, "constraint_count": stats.constraints, "caveat": str(exc),
        }
    runtime = time.perf_counter() - start
    termination = str(result.solver.termination_condition).lower()
    stats = collect_model_stats(model)
    if termination not in {"optimal", "feasible"}:
        return {
            "scenario_id": scenario["scenario_id"], "status": "infeasible", "solver_name": solver_name,
            "termination_condition": termination, "runtime_seconds": round(runtime, 6),
            "variable_count": stats.variables, "binary_count": stats.binaries, "constraint_count": stats.constraints,
            "caveat": "No accepted capacity solution.",
        }
    final_product = _sum(model, "final_product_output")
    bof_ls = float(value(model.bof_liquid_steel_total))
    eaf_ls = float(value(model.eaf_liquid_steel_total))
    hsm = _sum(model, "hot_strip_mill")
    dsp = _sum(model, "dsp_final_product_output")
    imported_slab = _sum(model, "imported_slab_to_hsm")
    result_row: dict[str, Any] = {
        "scenario_id": scenario["scenario_id"],
        "source_status": scenario["source_status"],
        "apply_bof_eaf_ledger": str(bool(scenario.get("apply_bof_eaf_ledger"))).lower(),
        "status": "pass", "solver_name": solver_name, "termination_condition": termination,
        "runtime_seconds": round(runtime, 6), "variable_count": stats.variables,
        "binary_count": stats.binaries, "constraint_count": stats.constraints,
        "annualised_final_product_mt_y": round(_annualise(final_product, horizon_hours) / 1_000_000.0, 6),
        "annualised_bof_liquid_steel_mt_y": round(_annualise(bof_ls, horizon_hours) / 1_000_000.0, 6),
        "annualised_eaf_liquid_steel_mt_y": round(_annualise(eaf_ls, horizon_hours) / 1_000_000.0, 6),
        "annualised_hsm_input_mt_y": round(_annualise(hsm, horizon_hours) / 1_000_000.0, 6),
        "annualised_dsp_final_product_mt_y": round(_annualise(dsp, horizon_hours) / 1_000_000.0, 6),
        "annualised_imported_slab_mt_y": round(_annualise(imported_slab, horizon_hours) / 1_000_000.0, 6),
        "annual_target_mt_y": float(annual_target_mt_y) if target_required else "",
        "target_required": str(target_required).lower(),
        "annualised_target_residual_t_y": round(
            _annualise(final_product, horizon_hours) - float(annual_target_mt_y) * 1_000_000.0,
            6,
        ) if target_required else "",
        "gap_to_6_75_mt_y_share": round((_annualise(final_product, horizon_hours) - 6_750_000.0) / 6_750_000.0, 8),
        "caveat": scenario.get("caveat", ""),
    }
    if ledger is not None:
        bof_scrap = _sum(model, "bof_scrap_supply_t")
        eaf_scrap = _sum(model, "eaf_scrap_supply_t")
        total_scrap = float(value(model.site_scrap_supply_total_t))
        result_row.update(
            annualised_bof_scrap_mt_y=round(_annualise(bof_scrap, horizon_hours) / 1_000_000.0, 6),
            annualised_eaf_scrap_mt_y=round(_annualise(eaf_scrap, horizon_hours) / 1_000_000.0, 6),
            annualised_site_scrap_mt_y=round(_annualise(total_scrap, horizon_hours) / 1_000_000.0, 6),
            site_scrap_cap_binding=str(abs(total_scrap - ledger["site_total_scrap_supply_cap_t"]) < 1e-5).lower(),
        )
    return result_row


def run_c1_bof_eaf_metallics_ledger(*, config_path: str | Path = DEFAULT_CONFIG, output_root: str | Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    config_file = Path(config_path).resolve()
    config = _load_config(config_file)
    run_directory = Path(output_root).resolve() / str(config["run_id"])
    if run_directory.exists():
        raise ValueError(f"Run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True)
    rows = [solve_capacity_case(config, scenario) for scenario in config["scenarios"]]
    baseline = next((row for row in rows if row["scenario_id"] == "legacy_no_named_metallics"), None)
    central = next((row for row in rows if row["scenario_id"] == "rounded_central_named_consumption"), None)
    exact_target_cases = [row for row in rows if row.get("target_required") == "true"]
    exact_target_pass = bool(exact_target_cases) and all(row.get("status") == "pass" for row in exact_target_cases)
    improvement = (
        float(central["annualised_final_product_mt_y"]) - float(baseline["annualised_final_product_mt_y"])
        if baseline is not None and central is not None and baseline.get("status") == "pass" and central.get("status") == "pass" else None
    )
    summary = {
        "run_id": config["run_id"], "output_policy": config["output_policy"],
        "run_class": "physical_feasibility_diagnostic", "lineage_role": "diagnostic",
        "retention": "local_run_artifact_not_git_eligible_by_default",
        "baseline_annualised_final_product_mt_y": baseline.get("annualised_final_product_mt_y") if baseline is not None else "not_run",
        "central_annualised_final_product_mt_y": central.get("annualised_final_product_mt_y") if central is not None else "not_run",
        "central_minus_baseline_mt_y": round(improvement, 6) if improvement is not None else "not_available",
        "central_gap_to_6_75_mt_y_share": central.get("gap_to_6_75_mt_y_share") if central is not None else "not_run",
        "exact_target_case_count": len(exact_target_cases),
        "exact_target_cases_pass": exact_target_pass if exact_target_cases else "not_run",
        "selection": (
            "The exact target case tests source-envelope feasibility only; it does not select an active central scrap assumption."
            if exact_target_cases
            else "rounded_central_named_consumption is the source-bounded central diagnostic, not a promoted executable input."
        ),
        "go_no_go": {
            "separate_bof_eaf_metallics_ledger": "GO diagnostic-only",
            "use_upper_envelope_for_active_target": "NO-GO unless DRP availability and source boundary are reconciled simultaneously",
            "change_process_capacity": "NO-GO: no capacity value was changed",
            "6_75_mt_y_exact_quota": "GO diagnostic-only under an explicit source-envelope case" if exact_target_pass else "NO-GO from this capacity probe alone; inspect the remaining central gap as a downstream/availability issue",
        },
    }
    (run_directory / "resolved_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    _write_json(run_directory / "input_manifest.json", {"config_sha256": hashlib.sha256(config_file.read_bytes()).hexdigest(), "input_directory": str(S44B_INPUT_DIR.relative_to(REPO_ROOT))})
    _write_json(run_directory / "code_version.json", {"timestamp_utc": datetime.now(timezone.utc).isoformat()})
    _write_csv(run_directory / "metrics_summary.csv", rows)
    _write_json(run_directory / "run_summary.json", summary)
    _write_json(run_directory / "registry_entry.json", {"run_id": config["run_id"], "run_class": "physical_feasibility_diagnostic", "lineage_role": "diagnostic", "output_policy": config["output_policy"], "git_eligible": False})
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- BOF/EAF scrap consumption is separate and site-bounded; external versus internal source allocation is not yet modelled.\n"
        "- The central 2.0-Mt/y consumption case is within the public site envelope but differs by 0.1 Mt/y from the rounded 1.3 + 0.6 Mt/y supply breakdown.\n"
        "- The upper-envelope case is context only and must not be selected for anchor fitting.\n"
        "- Capacity probes annualise a representative week and are not annual availability claims.\n",
        encoding="utf-8",
    )
    return {"run_directory": run_directory, "summary": summary, "rows": rows}
