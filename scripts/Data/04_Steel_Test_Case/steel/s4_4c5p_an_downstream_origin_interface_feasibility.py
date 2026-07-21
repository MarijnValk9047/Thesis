"""Run the opt-in C1 downstream origin-tagged material-interface feasibility check."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection

from .s4_4c5p_am_downstream_origin_route_ledger import build_c1_uniform_import_routing, load_source_values
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT, _build_c1_inputs, _load_tables, _solve_c1_configuration


RUN_ID = "steel_downstream_origin_interface_feasibility_v5"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
HOURS_PER_YEAR = 8760.0


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_c1_case_definitions(
    values: dict[str, float],
    *,
    horizon_hours: int,
    base_final_product_target_t: float,
) -> dict[str, dict[str, Any]]:
    """Define separate annual-boundary cases using the existing origin interface."""
    if horizon_hours <= 0 or base_final_product_target_t <= 0:
        raise ValueError("C1 case definitions require positive horizon and base target.")
    base_routing = build_c1_uniform_import_routing(values, horizon_hours=horizon_hours)

    def _case(
        annual_site_final_product_mt_y: float,
        imported_slab_cap_mt_y: float,
        boundary_role: str,
    ) -> dict[str, Any]:
        horizon_target_t = annual_site_final_product_mt_y * 1_000_000.0 * horizon_hours / HOURS_PER_YEAR
        routing = dict(base_routing)
        routing["imported_slab_max_t_h"] = imported_slab_cap_mt_y * 1_000_000.0 / HOURS_PER_YEAR
        return {
            "annual_site_final_product_target_mt_y": annual_site_final_product_mt_y,
            "annual_endogenous_liquid_steel_context_mt_y": values["c1_liquid_steel"],
            "imported_slab_annual_cap_mt_y": imported_slab_cap_mt_y,
            "target_multiplier": horizon_target_t / base_final_product_target_t,
            "boundary_role": boundary_role,
            "downstream_origin_routing": routing,
        }

    return {
        "endogenous_6_75": _case(6.75, 0.0, "all_endogenous_development_stress_case"),
        "mer_site_product": _case(values["c1_final_product"], values["c1_imported_slab"], "MER_site_final_product_boundary_case"),
    }


def build_origin_boundary_rows(
    *, case_id: str, case: dict[str, Any], audit: dict[str, Any], horizon_hours: int
) -> list[dict[str, Any]]:
    """Keep external-slab upstream attribution explicitly outside the site ledger."""
    solved = audit.get("build_status") == "solved"
    imported_t = float(audit.get("imported_slab_to_HSM_t", 0.0)) if solved else 0.0
    annual_import_mt_y = imported_t * HOURS_PER_YEAR / horizon_hours / 1_000_000.0
    imported_cap_mt_y = float(case["imported_slab_annual_cap_mt_y"])
    return [
        {
            "case_id": case_id,
            "origin": "imported_slab",
            "origin_scope": "external_upstream__HSM_boundary_entry",
            "annual_cap_mt_y": imported_cap_mt_y,
            "horizon_routed_t": round(imported_t, 6) if solved else "not_solved",
            "annualised_routed_mt_y": round(annual_import_mt_y, 9) if solved else "not_solved",
            "upstream_electricity_attribution_mwh": 0.0,
            "upstream_wag_attribution_mwh": 0.0,
            "upstream_named_ng_attribution_pj": 0.0,
            "upstream_direct_fuel_co2_attribution_t": 0.0,
            "cap_status": (
                "pass" if solved and annual_import_mt_y <= imported_cap_mt_y + 1e-9
                else "not_evaluated_no_solution" if not solved else "fail"
            ),
            "caveat": "External slab may enter only at HSM/WBW. Upstream energy, WAG, named NG and direct-fuel CO2 are outside the site boundary; downstream handling stays in scope.",
        },
        {
            "case_id": case_id,
            "origin": "endogenous_liquid_steel",
            "origin_scope": "IJmuiden_upstream_and_downstream",
            "annual_cap_mt_y": case["annual_endogenous_liquid_steel_context_mt_y"],
            "horizon_routed_t": audit.get("endogenous_liquid_steel_t", "not_solved"),
            "annualised_routed_mt_y": (
                round(float(audit["endogenous_liquid_steel_t"]) * HOURS_PER_YEAR / horizon_hours / 1_000_000.0, 9)
                if solved else "not_solved"
            ),
            "upstream_electricity_attribution_mwh": "represented_by_endogenous_processes",
            "upstream_wag_attribution_mwh": "represented_by_endogenous_processes",
            "upstream_named_ng_attribution_pj": "represented_by_endogenous_processes",
            "upstream_direct_fuel_co2_attribution_t": "represented_by_endogenous_processes",
            "cap_status": "not_an_import_cap",
            "caveat": "Endogenous liquid steel remains distinct from the site-final-product target.",
        },
    ]


def run_downstream_origin_interface_feasibility(
    *,
    output_root: str | Path = DEFAULT_RUN_ROOT,
    horizon_hours: int = 24,
    solver_time_limit_seconds: float = 60.0,
    case_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    run_directory = Path(output_root).resolve() / RUN_ID
    if run_directory.exists():
        raise ValueError(f"Run directory already exists: {run_directory}")
    run_directory.mkdir(parents=True)
    values = load_source_values()
    tables = _load_tables()
    base_inputs = _build_c1_inputs(tables, horizon_hours_override=horizon_hours, include_retained_bf_bof=True)
    cases = build_c1_case_definitions(
        values,
        horizon_hours=horizon_hours,
        base_final_product_target_t=base_inputs.final_product_target_t,
    )
    selected_case_ids = tuple(case_ids or cases.keys())
    unknown = set(selected_case_ids).difference(cases)
    if unknown:
        raise ValueError(f"Unknown C1 origin-boundary case IDs: {sorted(unknown)}")
    audits: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    hourly: list[dict[str, Any]] = []
    boundary_rows: list[dict[str, Any]] = []
    for scenario_id in selected_case_ids:
        case = cases[scenario_id]
        routing = case["downstream_origin_routing"]
        audit, scenario_constraints, scenario_hourly = _solve_c1_configuration(
            tables,
            horizon_hours_override=horizon_hours,
            target_multiplier=float(case["target_multiplier"]),
            enable_c1_retained_bf_bof_route=True,
            c1_retained_route_policy="quota_driven_topology",
            commitment_granularity="daily_binary_hourly_throughput",
            downstream_origin_routing=routing,
            solver_time_limit_seconds=solver_time_limit_seconds,
        )
        audit["scenario_id"] = scenario_id
        audit["boundary_role"] = case["boundary_role"]
        audit["annual_site_final_product_target_mt_y"] = case["annual_site_final_product_target_mt_y"]
        audit["annual_endogenous_liquid_steel_context_mt_y"] = case["annual_endogenous_liquid_steel_context_mt_y"]
        audit["imported_slab_annual_cap_mt_y"] = case["imported_slab_annual_cap_mt_y"]
        audit["imported_slab_max_t_h"] = routing["imported_slab_max_t_h"]
        if audit["build_status"] == "solved":
            dsp_liquid = float(audit.get("BOF_to_DSP_liquid_steel_t", 0.0)) + float(audit.get("EAF_to_DSP_liquid_steel_t", 0.0))
            audit["C1_DSP_EAF_origin_share"] = round(float(audit.get("EAF_to_DSP_liquid_steel_t", 0.0)) / dsp_liquid, 6) if dsp_liquid else "not_available"
        else:
            audit["C1_DSP_EAF_origin_share"] = "not_solved"
        audits.append(audit)
        boundary_rows.extend(build_origin_boundary_rows(case_id=scenario_id, case=case, audit=audit, horizon_hours=horizon_hours))
        constraints.extend({**row, "scenario_id": scenario_id} for row in scenario_constraints)
        hourly.extend({**row, "scenario_id": scenario_id} for row in scenario_hourly)
    status = "pass" if all(audit["build_status"] == "solved" for audit in audits) else "no_accepted_solution"
    summary = {
        "run_id": RUN_ID,
        "status": status,
        "output_policy": "minimal",
        "run_class": "feasibility",
        "lineage_role": "diagnostic",
        "horizon_hours": horizon_hours,
        "case_ids": selected_case_ids,
        "imported_slab_profile_policy": "uniform_annual_average_development_scenario",
        "source_backed_imported_slab_annual_cap_mt_y": values["c1_imported_slab"],
        "c1_dsp_eaf_share_constraint_active": False,
        "aggregate_wag_physical_use": 0,
        "mixed_wag_quantitative_use": 0,
        "scenario_audits": audits,
        "next_gate": "compare the route-tagged result with the annual ledger; do not turn the 90% EAF DSP anchor into a constraint",
    }
    _write_csv(run_directory / "configuration_build_audit.csv", audits)
    _write_csv(run_directory / "constraint_audit.csv", constraints)
    _write_csv(run_directory / "hourly_origin_tagged_dispatch.csv", hourly)
    _write_csv(run_directory / "origin_boundary_attribution_ledger.csv", boundary_rows)
    (run_directory / "resolved_config.yaml").write_text(
        "run_id: steel_downstream_origin_interface_feasibility_v5\n"
        "output_policy: minimal\nrun_class: feasibility\nlineage_role: diagnostic\n"
        f"horizon_hours: {horizon_hours}\nsolver_time_limit_seconds: {solver_time_limit_seconds}\n"
        "c1_retained_route_policy: quota_driven_topology\n"
        "commitment_granularity: daily_binary_hourly_throughput\n"
        "case_policy: separate_endogenous_6_75_and_mer_site_product\n"
        "dsp_capacity_policy: annual_output_anchor_normalised_to_horizon\n"
        "imported_slab_profile_policy: uniform_annual_average_development_scenario\n",
        encoding="utf-8",
    )
    _write_json(
        run_directory / "input_manifest.json",
        {
            "source_values": values,
            "case_definitions": {case_id: cases[case_id] for case_id in selected_case_ids},
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
    )
    _write_json(run_directory / "code_version.json", {"timestamp_utc": datetime.now(timezone.utc).isoformat()})
    _write_json(run_directory / "run_summary.json", summary)
    _write_json(run_directory / "registry_entry.json", {"run_id": RUN_ID, "output_policy": "minimal", "run_class": "feasibility", "lineage_role": "diagnostic", "git_eligible": False})
    (run_directory / "warnings_and_limitations.md").write_text(
        "# Limitations\n\n- This is an opt-in development scenario, not the default physical baseline.\n"
        "- The imported-slab limit is a uniform annual-average profile derived from the MER annual context; it is not an observed delivery profile.\n"
        "- The DSP output cap is the MER annual output anchor normalised to the horizon; it is not an observed hourly operating limit.\n"
        "- C1 EAF-origin DSP share remains reporting-only.\n"
        "- No WAG allocation, Wobbe rule, NG residual allocation, economics, or fuel-explicit CO2 expansion is changed.\n",
        encoding="utf-8",
    )
    return {"run_directory": run_directory, "summary": summary, "constraints": constraints, "hourly": hourly}
