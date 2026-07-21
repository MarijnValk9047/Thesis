"""Execute the bounded physical route scenarios promised by the pre-economics sprint.

The stage reuses the C5 closed-loop runner, the S4.4b2 component registry and
the existing C5 downstream interface.  It does not change development inputs
or turn the scenario route policies into the global C5 default.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from pyomo.environ import Objective, maximize, value

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    DEFAULT_CONFIG_PATH,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_am_downstream_origin_route_ledger import build_c1_uniform_import_routing, load_source_values
from .s4_4c_component_ontology import (
    COMPONENT_REGISTRY_PATH,
    OVERRIDE_PATH,
    ROUTE_SCENARIO_PATH,
    continuous_must_run_activities,
    load_builder_component_ontology,
    load_route_policy_scenarios,
)
from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    _apply_solver_time_limit,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
    _select_solver,
)


RUN_ID = "steel_component_ontology_route_reconciliation_v5"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
HOURS_PER_YEAR = 8760.0
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(value: Any) -> float:
    return 0.0 if value in (None, "") else float(value)


def _annual(value: float, horizon_hours: int) -> float:
    return value * HOURS_PER_YEAR / float(horizon_hours)


def _scenario_overrides(row: dict[str, Any], *, horizon_hours: int) -> dict[str, Any]:
    overrides: dict[str, Any] = {
        "run_id": f"{RUN_ID}_{row['scenario_id']}",
        "c1_retained_route_policy": "quota_driven_topology",
        "commitment_granularity": "daily_binary_hourly_throughput",
        "use_c1_component_ontology_continuous_classes": True,
        "use_c1_downstream_origin_interface": True,
    }
    if row.get("bof_lower_share") not in (None, ""):
        overrides["c1_liquid_steel_route_band"] = {
            "bof_lower_share": float(row["bof_lower_share"]),
            "bof_upper_share": float(row["bof_upper_share"]),
        }
    if row.get("material_balance_mode") == "named_hdri_scrap":
        overrides["eaf_material_balance"] = {
            "hdri_t_per_t_liquid_steel": float(row["hdri_t_per_t_liquid_steel"]),
            "scrap_t_per_t_liquid_steel": float(row["scrap_t_per_t_liquid_steel"]),
            "scrap_supply_cap_t": float(row["annual_scrap_supply_t_y"]) * horizon_hours / HOURS_PER_YEAR,
        }
    return overrides


def _route_metrics(run_dir: Path, *, horizon_hours: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    hourly_path = run_dir / "first_window_hourly.csv"
    hourly = [row for row in _read_csv(hourly_path) if row.get("configuration_id") == C1] if hourly_path.exists() else []
    if not hourly or summary.get("status") != "pass":
        return {
            "status": summary.get("status", "fail"),
            "route_bof_liquid_steel_share": "not_available",
            "caveat": "No accepted C1 closed-loop dispatch; annual comparisons are not reported.",
        }, []
    totals = {
        "final_product_t": sum(_float(row.get("final_product_output_t")) for row in hourly),
        "bof_liquid_steel_t": sum(_float(row.get("C1_BOF_liquid_steel_output_t_h")) for row in hourly),
        "eaf_liquid_steel_t": sum(_float(row.get("C1_EAF_liquid_steel_output_t_h")) for row in hourly),
        "drp_pellets_t": sum(_float(row.get("C1_DRP_activity_t_pellets_h")) for row in hourly),
        "eaf_dri_t": sum(_float(row.get("C1_EAF_activity_t_DRI_h")) for row in hourly),
        "scrap_t": sum(_float(row.get("scrap_t")) for row in hourly),
        "gross_electricity_mwh": sum(_float(row.get("gross_electricity_mwh")) for row in hourly),
        "net_grid_import_mwh": sum(_float(row.get("net_grid_import_mwh")) for row in hourly),
        "wag_generated_mwh": sum(_float(row.get("WAG_generated")) for row in hourly),
        "wag_flared_mwh": sum(_float(row.get("WAG_flared")) for row in hourly),
        "explicit_fuel_co2_t": sum(_float(row.get("WAG_explicit_combustion_co2_t")) for row in hourly),
    }
    endogenous_ls = totals["bof_liquid_steel_t"] + totals["eaf_liquid_steel_t"]
    metrics = {
        "status": "pass",
        **{f"annual_{key}": round(_annual(value, horizon_hours), 6) for key, value in totals.items()},
        "route_bof_liquid_steel_share": round(totals["bof_liquid_steel_t"] / endogenous_ls, 8) if endogenous_ls else "not_available",
        "route_eaf_liquid_steel_share": round(totals["eaf_liquid_steel_t"] / endogenous_ls, 8) if endogenous_ls else "not_available",
    }
    anchors = [
        ("active_final_product_proxy", "production", "final_product", 6_750_000.0, metrics["annual_final_product_t"], "secondary_context"),
        ("c1_retained_bof_liquid_steel_policy", "production", "BOF_liquid_steel", 3_400_000.0, metrics["annual_bof_liquid_steel_t"], "secondary_context"),
        ("c1_eaf_liquid_steel_policy", "production", "EAF_liquid_steel", 3_350_000.0, metrics["annual_eaf_liquid_steel_t"], "secondary_context"),
        ("mer_c1_hdri_context", "material", "EAF_HDRI_input", 2_800_000.0, metrics["annual_eaf_dri_t"], "primary_context"),
    ]
    if totals["scrap_t"] > 0.0:
        anchors.append(("mer_c1_named_scrap_context", "material", "EAF_named_scrap_input", 1_000_000.0, metrics["annual_scrap_t"], "primary_context"))
    anchor_rows = [
        {
            "anchor_id": anchor_id,
            "anchor_family": family,
            "metric": metric,
            "anchor_value_t_y": anchor,
            "model_annualised_value_t_y": model_value,
            "signed_residual_t_y": round(model_value - anchor, 6),
            "signed_residual_share": round((model_value - anchor) / anchor, 8),
            "within_15pct": str(abs((model_value - anchor) / anchor) <= 0.15).lower(),
            "scoring_role": role,
            "comparison_status": "partial_comparable",
            "caveat": "Annualisation is a representative-window diagnostic; policy targets and MER material context are not dispatch constraints.",
        }
        for anchor_id, family, metric, anchor, model_value, role in anchors
    ]
    return metrics, anchor_rows


def _capacity_probe(
    scenario: dict[str, Any], *, horizon_hours: int, solver_time_limit_seconds: float,
    operating_class_mode: str,
) -> dict[str, Any]:
    """Maximise C1 output with all capacities and conversions held fixed."""

    overrides = _scenario_overrides(scenario, horizon_hours=horizon_hours)
    tables = _load_tables(S44B_INPUT_DIR)
    inputs = _build_c1_inputs(tables, horizon_hours_override=horizon_hours, include_retained_bf_bof=True)
    model = _build_c1_model(
        inputs,
        enable_minimal_wag_layer=True,
        enable_c1_retained_bf_bof_route=True,
        enable_internal_wag_power=True,
        development_controller_activation="full",
        c1_retained_route_policy="quota_driven_topology",
        commitment_granularity="daily_binary_hourly_throughput",
        downstream_origin_routing=build_c1_uniform_import_routing(load_source_values(), horizon_hours=horizon_hours),
        eaf_material_balance=overrides.get("eaf_material_balance"),
        c1_liquid_steel_route_band=overrides.get("c1_liquid_steel_route_band"),
        continuous_must_run_activities=(
            continuous_must_run_activities(C1) if operating_class_mode == "continuous_enforced" else ()
        ),
    )
    model.final_product_fulfilment.deactivate()
    model.static_price_naive_objective.deactivate()
    model.capacity_probe_objective = Objective(
        expr=sum(model.final_product_output[t] for t in model.TIME), sense=maximize
    )
    solver_name, solver = _select_solver()
    _apply_solver_time_limit(solver_name, solver, solver_time_limit_seconds)
    try:
        result = solver.solve(model)
    except RuntimeError as exc:
        return {
            "scenario_id": scenario["scenario_id"], "operating_class_mode": operating_class_mode, "solver_name": solver_name,
            "status": "infeasible", "caveat": f"No maximum-output solution: {exc}",
        }
    termination = str(result.solver.termination_condition)
    if termination.lower() not in {"optimal", "feasible"}:
        return {
            "scenario_id": scenario["scenario_id"], "operating_class_mode": operating_class_mode, "solver_name": solver_name,
            "status": "infeasible", "termination_condition": termination,
            "caveat": "No accepted maximum-output solution.",
        }
    output = sum(float(value(model.final_product_output[t])) for t in model.TIME)
    bof = float(value(model.bof_liquid_steel_total))
    eaf = float(value(model.eaf_liquid_steel_total))
    annual = _annual(output, horizon_hours)
    return {
        "scenario_id": scenario["scenario_id"], "operating_class_mode": operating_class_mode, "solver_name": solver_name, "status": "pass",
        "termination_condition": termination,
        "max_final_product_t_horizon": round(output, 6),
        "annualised_max_final_product_t_y": round(annual, 6),
        "gap_to_6_75_mt_y_t_y": round(annual - 6_750_000.0, 6),
        "gap_to_6_75_mt_y_share": round((annual - 6_750_000.0) / 6_750_000.0, 8),
        "bof_liquid_steel_share": round(bof / (bof + eaf), 8) if bof + eaf else "not_available",
        "capacity_probe_policy": "existing_constraints_only_no_parameter_change",
        "caveat": "Diagnostic only; it does not validate annual availability or authorise capacity/conversion changes.",
    }


def run_component_ontology_route_reconciliation(
    *,
    output_root: str | Path = DEFAULT_RUN_ROOT,
    horizon_hours: int = 168,
    execution_block_hours: int = 24,
    replan_count: int = 3,
    solver_time_limit_seconds: float = 60.0,
) -> dict[str, Any]:
    """Run four bounded C1 route/material scenarios under one component contract."""

    run_directory = Path(output_root).resolve() / RUN_ID
    if run_directory.exists():
        raise ValueError(f"Run directory already exists: {run_directory}")
    ontology_rows = load_builder_component_ontology()
    continuous = continuous_must_run_activities(C1)
    scenarios = load_route_policy_scenarios()
    run_directory.mkdir(parents=True)
    scenario_rows: list[dict[str, Any]] = []
    anchor_rows: list[dict[str, Any]] = []
    enforcement_rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        overrides = _scenario_overrides(scenario, horizon_hours=horizon_hours)
        overrides.update({
            "planning_horizon_hours": horizon_hours,
            "execution_block_hours": execution_block_hours,
            "replan_count": replan_count,
            "solver_time_limit_seconds": solver_time_limit_seconds,
            "quota_per_execution_block_t": 6_750_000.0 / 365.0,
            # The builder's compact source target remains 5,905.2 t/24h.
            # The multiplier bridges it to the user-selected 6.75 Mt/y
            # final-product day quantity without altering source inputs.
            "base_quota_per_execution_block_t": 5_905.2,
            "availability_policy": {"c0": "fixed_static_binary_schedule", "c1": "quota_driven_topology"},
        })
        result = run_closed_loop_feasibility_anchor_reconciliation(
            config_path=DEFAULT_CONFIG_PATH,
            output_root=run_directory,
            scenario_overrides=overrides,
        )
        child = Path(result["run_directory"])
        metrics, scenario_anchor_rows = _route_metrics(child, horizon_hours=horizon_hours)
        scenario_rows.append({
            **scenario,
            **metrics,
            "run_directory": str(child.relative_to(run_directory)),
            "run_status": result["summary"].get("status"),
            "replan_count": replan_count,
            "physical_guardrails_pass": str(result["summary"].get("status") == "pass").lower(),
        })
        anchor_rows.extend({**row, "scenario_id": scenario["scenario_id"]} for row in scenario_anchor_rows)

    free_route = next(row for row in scenarios if row["scenario_id"] == "free_route_reference")
    named_scrap = next(row for row in scenarios if row["scenario_id"] == "central_source_ratio_named_scrap")
    capacity_rows = [
        _capacity_probe(
            free_route, horizon_hours=horizon_hours, solver_time_limit_seconds=solver_time_limit_seconds,
            operating_class_mode="continuous_enforced",
        ),
        _capacity_probe(
            free_route, horizon_hours=horizon_hours, solver_time_limit_seconds=solver_time_limit_seconds,
            operating_class_mode="classification_only_reference",
        ),
        _capacity_probe(
            named_scrap, horizon_hours=horizon_hours, solver_time_limit_seconds=solver_time_limit_seconds,
            operating_class_mode="classification_only_reference",
        ),
    ]

    for row in ontology_rows:
        enforcement_rows.append({
            "configuration_id": row["configuration_id"],
            "asset_id": row["asset_id"],
            "builder_activity_name": row["builder_activity_name"],
            "operation_class": row["operation_class"],
            "enforcement": row["enforcement"],
            "active_builder_scope": row["active_builder_scope"],
            "enforced_in_this_stage": str(
                row["configuration_id"] == C1 and row["builder_activity_name"] in continuous
            ).lower(),
            "caveat": row["caveat"],
        })
    passed = [row for row in scenario_rows if row["run_status"] == "pass"]
    best = max(
        passed,
        key=lambda row: sum(
            1 for anchor in anchor_rows
            if anchor["scenario_id"] == row["scenario_id"] and anchor["within_15pct"] == "true"
        ),
        default=None,
    )
    summary = {
        "run_id": RUN_ID,
        "status": "pass" if len(passed) == len(scenarios) else "pass_with_infeasible_scenarios",
        "output_policy": "diagnostics",
        "run_class": "deterministic_feasibility",
        "lineage_role": "diagnostic",
        "scenario_count": len(scenarios),
        "sensitivity_analyses_executed": len(scenarios),
        "max_sensitivity_analyses": 5,
        "continuous_must_run_activities": list(continuous),
        "best_guardrail_passing_scenario": best["scenario_id"] if best else "",
        "capacity_probe_cases": len(capacity_rows),
        "aggregate_wag_physical_use": 0,
        "mixed_wag_quantitative_use": 0,
        "c5p_k_physical_use": 0,
        "economics_executed": False,
        "go_no_go": {
            "component_ontology_adapter": "GO",
            "source_banded_route_scenarios": "GO_DIAGNOSTIC_ONLY",
            "capacity_parameter_change": "NO_GO",
            "economics": "NO_GO_OUT_OF_SCOPE",
        },
    }
    _write_csv(run_directory / "ontology_adoption_audit.csv", ontology_rows)
    _write_csv(run_directory / "scenario_policy_register.csv", scenarios)
    _write_csv(run_directory / "operating_class_enforcement.csv", enforcement_rows)
    _write_csv(run_directory / "scenario_comparison.csv", scenario_rows)
    _write_csv(run_directory / "annualised_anchor_reconciliation.csv", anchor_rows)
    _write_csv(run_directory / "bounded_capacity_conversion_probe.csv", capacity_rows)
    _write_json(run_directory / "summary.json", summary)
    _write_json(run_directory / "input_manifest.json", {
        "s4_4b2_component_registry": str(COMPONENT_REGISTRY_PATH.relative_to(REPO_ROOT)),
        "c5_operation_class_overrides": str(OVERRIDE_PATH.relative_to(REPO_ROOT)),
        "c1_route_scenarios": str(ROUTE_SCENARIO_PATH.relative_to(REPO_ROOT)),
        "base_closed_loop_config": str(DEFAULT_CONFIG_PATH.relative_to(REPO_ROOT)),
    })
    _write_json(run_directory / "registry_entry.json", {
        "run_id": RUN_ID, "run_class": "deterministic_feasibility", "lineage_role": "diagnostic",
        "output_policy": "diagnostics", "git_eligible": False,
    })
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Limitations\n\n"
        "- The S4.4b2 registry remains the authoritative topology record; this stage only adds C5 operation classes.\n"
        "- Continuous assets are fixed on over the planning horizon but retain their existing source-card min/max throughput range.\n"
        "- BOF/EAF remain batch-equivalent; no heat calendar is invented. HSM/DSP remain endogenous downstream routes.\n"
        "- Route bands and MER named-scrap context are explicit diagnostic scenarios, not the global model default or anchor constraints.\n"
        "- Maximum-output probes keep physical inputs fixed and explain infeasibility; they are not a capacity calibration.\n"
        "- No capacity, WAG/NG ratio, Wobbe model, residual allocation, economics, DA, ETS or full Scope 1 claim is introduced.\n",
        encoding="utf-8",
    )
    return {"run_directory": run_directory, "summary": summary}
