"""Capacity-boundary audit for the quota-driven C0/C1 physical models.

The audit maximises final-product output under the existing physical model
constraints.  It does not change capacities, introduce residual supply, or
activate economic terms.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml
from pyomo.environ import Objective, maximize, value

from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    _apply_solver_time_limit,
    _build_c0_inputs,
    _build_c0_model,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
    _select_solver,
)


DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
RUN_ID = "steel_capacity_boundary_audit_v2"
HORIZON_HOURS = 168
ANNUAL_TARGET_MT_Y = 6.75


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"])
        writer.writeheader()
        writer.writerows(rows)


def _capacity_rows(
    model: Any,
    process_limits: dict[str, tuple[float, float]],
    configuration_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for process_name, (_minimum, maximum) in process_limits.items():
        actual = sum(value(getattr(model, process_name)[t]) for t in model.TIME)
        capacity = maximum * len(model.TIME)
        rows.append(
            {
                "configuration_id": configuration_id,
                "process_or_route": process_name,
                "throughput_t_7d": round(actual, 6),
                "maximum_throughput_t_7d": round(capacity, 6),
                "utilisation_share": round(actual / capacity, 8) if capacity else "",
                "boundary_role": "physical_process_capacity",
            }
        )
    return rows


def _solve_capacity_case(
    *,
    configuration_id: str,
    model_builder: Callable[[], Any],
    process_limits: dict[str, tuple[float, float]],
    annual_target_t_day: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    model = model_builder()
    model.final_product_fulfilment.deactivate()
    model.static_price_naive_objective.deactivate()
    model.capacity_probe_objective = Objective(
        expr=sum(model.final_product_output[t] for t in model.TIME),
        sense=maximize,
    )
    solver_name, solver = _select_solver()
    _apply_solver_time_limit(solver_name, solver, 120.0)
    result = solver.solve(model)
    output_t_7d = sum(value(model.final_product_output[t]) for t in model.TIME)
    output_t_day = output_t_7d / 7.0
    retained_output = (
        sum(value(model.retained_bf_bof_final_product_output[t]) for t in model.TIME)
        if hasattr(model, "retained_bf_bof_final_product_output")
        else 0.0
    )
    eaf_output = (
        sum(value(model.eaf_final_product_output[t]) for t in model.TIME)
        if hasattr(model, "eaf_final_product_output")
        else 0.0
    )
    utilisation_rows = _capacity_rows(model, process_limits, configuration_id)
    return (
        {
            "configuration_id": configuration_id,
            "solver_name": solver_name,
            "termination_condition": str(result.solver.termination_condition),
            "max_final_product_t_7d": round(output_t_7d, 6),
            "max_final_product_t_day": round(output_t_day, 6),
            "retained_bf_bof_final_product_t_7d": round(retained_output, 6),
            "eaf_final_product_t_7d": round(eaf_output, 6),
            "annualised_final_product_mt_y": round(output_t_day * 365.0 / 1_000_000.0, 6),
            "target_final_product_t_day": round(annual_target_t_day, 6),
            "gap_to_target_t_day": round(output_t_day - annual_target_t_day, 6),
            "gap_to_target_share": round((output_t_day - annual_target_t_day) / annual_target_t_day, 8),
            "capacity_probe_policy": "existing_physical_constraints_only",
            "caveat": "A maximum-output probe identifies binding model boundary/capacity combinations; it does not validate annual site capacity or authorise parameter changes.",
        },
        utilisation_rows,
    )


def run_capacity_boundary_audit(*, output_root: str | Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    run_directory = Path(output_root).resolve() / RUN_ID
    if run_directory.exists():
        raise ValueError(f"Run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True)
    annual_target_t_day = ANNUAL_TARGET_MT_Y * 1_000_000.0 / 365.0
    tables = _load_tables(S44B_INPUT_DIR)
    c0_inputs = _build_c0_inputs(tables, horizon_hours_override=HORIZON_HOURS)
    c1_inputs = _build_c1_inputs(tables, horizon_hours_override=HORIZON_HOURS, include_retained_bf_bof=True)
    assert c1_inputs.retained_bf_bof is not None

    c0_summary, c0_rows = _solve_capacity_case(
        configuration_id="C0_current_BF_BOF_reference",
        model_builder=lambda: _build_c0_model(
            c0_inputs,
            enable_minimal_wag_layer=True,
            enable_internal_wag_power=True,
            development_controller_activation="full",
            commitment_granularity="daily_binary_hourly_throughput",
        ),
        process_limits=c0_inputs.process_limits,
        annual_target_t_day=annual_target_t_day,
    )
    c1_limits = {
        **c1_inputs.retained_bf_bof.process_limits,
        "drp_pellet_input": (c1_inputs.drp_min_t_pellets_h, c1_inputs.drp_max_t_pellets_h),
        "eaf_dri_input": (c1_inputs.eaf_min_t_dri_h, c1_inputs.eaf_max_t_dri_h),
    }
    c1_summary, c1_rows = _solve_capacity_case(
        configuration_id="C1_phase1_BF_BOF_plus_DRP_EAF",
        model_builder=lambda: _build_c1_model(
            c1_inputs,
            enable_minimal_wag_layer=True,
            enable_c1_retained_bf_bof_route=True,
            enable_internal_wag_power=True,
            development_controller_activation="full",
            c1_retained_route_policy="quota_driven_topology",
            commitment_granularity="daily_binary_hourly_throughput",
        ),
        process_limits=c1_limits,
        annual_target_t_day=annual_target_t_day,
    )
    summaries = [c0_summary, c1_summary]
    _write_csv(run_directory / "capacity_summary.csv", summaries)
    _write_csv(run_directory / "process_capacity_utilisation.csv", c0_rows + c1_rows)
    resolved_config = {
        "run_id": RUN_ID,
        "horizon_hours": HORIZON_HOURS,
        "annual_target_mt_y": ANNUAL_TARGET_MT_Y,
        "annual_target_final_product_t_day": annual_target_t_day,
        "commitment_granularity": "daily_binary_hourly_throughput",
        "output_policy": "diagnostics",
        "market_prices_enabled": False,
        "economic_terms_enabled": False,
    }
    (run_directory / "config_resolved.yaml").write_text(yaml.safe_dump(resolved_config, sort_keys=False), encoding="utf-8")
    _write_json(
        run_directory / "input_manifest.json",
        {
            "input_directory": str(S44B_INPUT_DIR.relative_to(REPO_ROOT)),
            "input_directory_name": S44B_INPUT_DIR.name,
            "modelbuilder": "scripts/Data/04_Steel_Test_Case/steel/s4_4c_unified_physical_modelbuilder.py",
        },
    )
    _write_json(run_directory / "code_version.json", {"timestamp_utc": datetime.now(timezone.utc).isoformat()})
    _write_json(
        run_directory / "registry_entry.json",
        {
            "run_id": RUN_ID,
            "run_class": "capacity_boundary_audit",
            "lineage_role": "diagnostic",
            "output_policy": "diagnostics",
            "git_eligible": False,
        },
    )
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a capacity probe, not an annual site-capacity claim.\n"
        "- It changes neither capacities nor physical parameters.\n"
        "- It does not use prices, costs, residual supply, aggregate WAG or mixed WAG as physical carriers.\n"
        "- Binding constraints need a later targeted relaxation audit before any parameter change.\n",
        encoding="utf-8",
    )
    _write_json(run_directory / "run_summary.json", {"run_id": RUN_ID, "status": "pass", "summaries": summaries})
    return {"run_directory": run_directory, "summaries": summaries}
