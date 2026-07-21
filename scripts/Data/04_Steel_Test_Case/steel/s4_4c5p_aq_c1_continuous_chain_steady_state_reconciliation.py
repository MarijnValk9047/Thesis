"""Bounded fifth physical sensitivity for the C1 continuous coke/sinter/BF chain."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from pyomo.environ import Objective, maximize, value

from .s4_4c5p_am_downstream_origin_route_ledger import build_c1_uniform_import_routing, load_source_values
from .s4_4c_component_ontology import ONTOLOGY_DIR, continuous_must_run_activities
from .s4_4c_unified_physical_modelbuilder import (
    REPO_ROOT,
    S44B_INPUT_DIR,
    _apply_solver_time_limit,
    _build_c1_inputs,
    _build_c1_model,
    _load_tables,
    _select_solver,
)


RUN_ID = "steel_c1_continuous_chain_steady_state_reconciliation_v1"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
SCENARIO_PATH = ONTOLOGY_DIR / "c1_coke_chain_development_scenario.csv"
C1 = "C1_phase1_BF_BOF_plus_DRP_EAF"
HORIZON_HOURS = 168
TARGET_T_HORIZON = 6_750_000.0 / 365.0 * 7.0


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _candidate() -> dict[str, Any]:
    with SCENARIO_PATH.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    return {**row, "dry_coal_t_per_t_coke": float(row["dry_coal_t_per_t_coke"]), "bf_coke_t_per_t_hot_metal": float(row["bf_coke_t_per_t_hot_metal"])}


def build_steady_state_interval_rows(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive interval overlap directly from the active C1 equations."""

    retained = _build_c1_inputs(_load_tables(S44B_INPUT_DIR), horizon_hours_override=HORIZON_HOURS, include_retained_bf_bof=True).retained_bf_bof
    assert retained is not None
    coke_low, coke_high = retained.process_limits["coking_plant_1"]
    sinter_low, sinter_high = retained.process_limits["sintering_plant"]
    bf_low, bf_high = retained.process_limits["blast_furnace_6"]
    bof_low, bof_high = retained.process_limits["basic_oxygen_furnace"]
    legacy_supply = (coke_low, coke_high)
    legacy_demand = (retained.coke_per_t_sinter * bf_low, retained.coke_per_t_sinter * bf_high)
    reconciled_supply = (coke_low / candidate["dry_coal_t_per_t_coke"], coke_high / candidate["dry_coal_t_per_t_coke"])
    reconciled_demand = (
        bf_low * retained.bf_hot_iron_per_t_sinter * candidate["bf_coke_t_per_t_hot_metal"],
        bf_high * retained.bf_hot_iron_per_t_sinter * candidate["bf_coke_t_per_t_hot_metal"],
    )
    def row(case: str, supply: tuple[float, float], demand: tuple[float, float], equation: str) -> dict[str, Any]:
        lower, upper = max(supply[0], demand[0]), min(supply[1], demand[1])
        return {
            "check_id": case, "equation": equation,
            "supply_low_t_h": round(supply[0], 6), "supply_high_t_h": round(supply[1], 6),
            "demand_low_t_h": round(demand[0], 6), "demand_high_t_h": round(demand[1], 6),
            "overlap_low_t_h": round(lower, 6), "overlap_high_t_h": round(upper, 6),
            "steady_state_possible": str(lower <= upper).lower(),
        }
    rows = [
        row("legacy_coke_balance", legacy_supply, legacy_demand, "coke_inventory += coking_activity - 0.5 * BF_sinter_input"),
        row("source_candidate_coke_balance", reconciled_supply, reconciled_demand, "coke_inventory += coal_input/dry_coal_per_coke - BF_hot_metal*bf_coke_rate"),
        {
            "check_id": "BF_to_BOF_direct_rate_overlap", "equation": "BF_hot_metal = sinter * HM_per_sinter; BOF consumes hot metal when a batch runs",
            "supply_low_t_h": round(bf_low * retained.bf_hot_iron_per_t_sinter, 6),
            "supply_high_t_h": round(bf_high * retained.bf_hot_iron_per_t_sinter, 6),
            "demand_low_t_h": bof_low, "demand_high_t_h": bof_high,
            "overlap_low_t_h": round(max(bf_low * retained.bf_hot_iron_per_t_sinter, bof_low), 6),
            "overlap_high_t_h": round(min(bf_high * retained.bf_hot_iron_per_t_sinter, bof_high), 6),
            "steady_state_possible": "not_required_batch_equivalent",
        },
        {
            "check_id": "sinter_to_BF_direct_rate_overlap", "equation": "sinter output equals BF sinter input at steady state",
            "supply_low_t_h": sinter_low, "supply_high_t_h": sinter_high,
            "demand_low_t_h": bf_low, "demand_high_t_h": bf_high,
            "overlap_low_t_h": max(sinter_low, bf_low), "overlap_high_t_h": min(sinter_high, bf_high),
            "steady_state_possible": str(max(sinter_low, bf_low) <= min(sinter_high, bf_high)).lower(),
        },
    ]
    return rows


def _capacity_utilisation_rows(model: Any, inputs: Any, *, case_id: str) -> list[dict[str, Any]]:
    """Report the active source-bounded capacities; do not infer new limits."""

    retained = inputs.retained_bf_bof
    assert retained is not None
    activity_rows = (
        ("coking_plant_1_dry_coal_input", model.coking_plant_1, retained.process_limits["coking_plant_1"]),
        ("sintering_plant_output", model.sintering_plant, retained.process_limits["sintering_plant"]),
        ("blast_furnace_6_sinter_input", model.blast_furnace_6, retained.process_limits["blast_furnace_6"]),
        ("basic_oxygen_furnace_hot_metal_input", model.basic_oxygen_furnace, retained.process_limits["basic_oxygen_furnace"]),
        ("hot_strip_mill_slab_input", model.hot_strip_mill, retained.process_limits["hot_strip_mill"]),
        ("DRP_pellet_input", model.drp_pellet_input, (inputs.drp_min_t_pellets_h, inputs.drp_max_t_pellets_h)),
        ("EAF_DRI_input", model.eaf_dri_input, (inputs.eaf_min_t_dri_h, inputs.eaf_max_t_dri_h)),
    )
    rows: list[dict[str, Any]] = []
    for asset, activity, limits in activity_rows:
        values = [float(value(activity[t])) for t in model.TIME]
        average = sum(values) / len(values)
        maximum = max(values)
        rows.append(
            {
                "case_id": case_id,
                "asset_or_driver": asset,
                "average_t_h": round(average, 6),
                "peak_t_h": round(maximum, 6),
                "minimum_t_h": round(min(values), 6),
                "source_min_t_h": round(float(limits[0]), 6),
                "source_max_t_h": round(float(limits[1]), 6),
                "average_utilisation_share": round(average / float(limits[1]), 8),
                "peak_utilisation_share": round(maximum / float(limits[1]), 8),
                "caveat": "Observed utilisation of existing source-bounded model capacity; not a capacity calibration.",
            }
        )
    return rows


def _solve_case(*, name: str, coke_chain: dict[str, float] | None, enforce_continuous: bool, target_required: bool) -> dict[str, Any]:
    tables = _load_tables(S44B_INPUT_DIR)
    multiplier = TARGET_T_HORIZON / 5_905.2
    inputs = _build_c1_inputs(tables, horizon_hours_override=HORIZON_HOURS, target_multiplier=multiplier, include_retained_bf_bof=True)
    model = _build_c1_model(
        inputs, enable_minimal_wag_layer=True, enable_c1_retained_bf_bof_route=True,
        enable_internal_wag_power=True, development_controller_activation="full",
        c1_retained_route_policy="quota_driven_topology", commitment_granularity="daily_binary_hourly_throughput",
        downstream_origin_routing=build_c1_uniform_import_routing(load_source_values(), horizon_hours=HORIZON_HOURS),
        continuous_must_run_activities=continuous_must_run_activities(C1) if enforce_continuous else (),
        c1_coke_chain_reconciliation=coke_chain,
    )
    if not target_required:
        model.final_product_fulfilment.deactivate()
        model.static_price_naive_objective.deactivate()
        model.capacity_probe_objective = Objective(expr=sum(model.final_product_output[t] for t in model.TIME), sense=maximize)
    solver_name, solver = _select_solver()
    _apply_solver_time_limit(solver_name, solver, 60.0)
    try:
        result = solver.solve(model)
    except RuntimeError as exc:
        return {"case_id": name, "status": "infeasible", "solver_name": solver_name, "caveat": str(exc), "capacity_utilisation_rows": []}
    termination = str(result.solver.termination_condition)
    if termination.lower() not in {"optimal", "feasible"}:
        return {"case_id": name, "status": "infeasible", "solver_name": solver_name, "termination_condition": termination, "capacity_utilisation_rows": []}
    output = sum(float(value(model.final_product_output[t])) for t in model.TIME)
    factor = 8760.0 / HORIZON_HOURS
    return {
        "case_id": name, "status": "pass", "solver_name": solver_name, "termination_condition": termination,
        "continuous_enforced": str(enforce_continuous).lower(), "coke_chain_reconciliation_active": str(coke_chain is not None).lower(),
        "target_required": str(target_required).lower(), "final_product_t_horizon": round(output, 6),
        "annualised_final_product_mt_y": round(output * factor / 1_000_000.0, 6),
        "gap_to_6_75_mt_y_share": round((output * factor - 6_750_000.0) / 6_750_000.0, 8),
        "coke_output_t_h": round(float(value(model.coke_output[0])), 6),
        "bf_coke_demand_t_h": round(float(value(model.bf_coke_demand[0])), 6),
        "capacity_utilisation_rows": _capacity_utilisation_rows(model, inputs, case_id=name),
        "caveat": "No capacity, WAG/NG allocation, residual or economics parameter was changed.",
    }


def run_c1_continuous_chain_steady_state_reconciliation(
    *,
    output_root: str | Path = DEFAULT_RUN_ROOT,
    run_id: str = RUN_ID,
) -> dict[str, Any]:
    out = Path(output_root).resolve() / run_id
    if out.exists():
        raise ValueError(f"Run directory already exists: {out}")
    candidate = _candidate()
    interval_rows = build_steady_state_interval_rows(candidate)
    candidate_map = {"dry_coal_t_per_t_coke": candidate["dry_coal_t_per_t_coke"], "bf_coke_t_per_t_hot_metal": candidate["bf_coke_t_per_t_hot_metal"]}
    case_rows = [
        _solve_case(name="legacy_continuous_capacity_probe", coke_chain=None, enforce_continuous=True, target_required=False),
        _solve_case(name="source_coke_chain_continuous_capacity_probe", coke_chain=candidate_map, enforce_continuous=True, target_required=False),
        _solve_case(name="source_coke_chain_continuous_6_75_target", coke_chain=candidate_map, enforce_continuous=True, target_required=True),
    ]
    capacity_rows = [
        row
        for case in case_rows
        for row in case.pop("capacity_utilisation_rows", [])
    ]
    status = "pass" if any(row["case_id"] == "source_coke_chain_continuous_capacity_probe" and row["status"] == "pass" for row in case_rows) else "fail"
    summary = {
        "run_id": run_id, "status": status, "output_policy": "diagnostics",
        "run_class": "physical_feasibility_diagnostic", "lineage_role": "diagnostic", "git_eligible": False,
        "bounded_sensitivity_number": 5, "maximum_sensitivities": 5,
        "legacy_coke_overlap": next(row for row in interval_rows if row["check_id"] == "legacy_coke_balance")["steady_state_possible"],
        "source_candidate_coke_overlap": next(row for row in interval_rows if row["check_id"] == "source_candidate_coke_balance")["steady_state_possible"],
        "economics_executed": False,
        "go_no_go": {"source_coke_chain_development_sensitivity": "GO_EXECUTED", "capacity_migration": "NO_GO", "economics": "NO_GO"},
    }
    out.mkdir(parents=True)
    _write_csv(out / "source_candidate_register.csv", [candidate])
    _write_csv(out / "steady_state_interval_check.csv", interval_rows)
    _write_csv(out / "model_case_summary.csv", case_rows)
    _write_csv(out / "capacity_utilisation.csv", capacity_rows)
    _write_json(out / "summary.json", summary)
    _write_json(out / "input_manifest.json", {"scenario": str(SCENARIO_PATH.relative_to(REPO_ROOT)), "source_cards": ["data/03_Optimisation/inputs/assets/steel/source_cards/Coking_Plants_Parameters.md", "data/03_Optimisation/inputs/assets/steel/source_cards/Blast_Furnace_Parameters.md"]})
    _write_json(out / "registry_entry.json", {"run_id": RUN_ID, "run_class": "physical_feasibility_diagnostic", "lineage_role": "diagnostic", "output_policy": "diagnostics", "git_eligible": False})
    _write_json(out / "code_version.json", {"stage": "S4.4c5p_aq"})
    (out / "resolved_config.yaml").write_text("horizon_hours: 168\ncontinuous_assets: coking_plant_1,sintering_plant,blast_furnace_6,drp_pellet_input\n", encoding="utf-8")
    (out / "warnings_and_limitations.md").write_text("# Limitations\n\n- This is the fifth and final bounded physical sensitivity.\n- Candidate coal-to-coke and BF coke-rate values are not migrated to development inputs.\n- WAG/NG ratios, Wobbe quality, residual allocation and economics remain unchanged.\n", encoding="utf-8")
    return {"run_directory": out, "summary": summary, "case_rows": case_rows, "capacity_rows": capacity_rows}
