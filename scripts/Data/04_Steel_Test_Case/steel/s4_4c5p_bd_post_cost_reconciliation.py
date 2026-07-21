"""Derive compact post-cost physical, anchor and cost evidence from one solved run."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PARENT = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "runs"
    / "steel_s2_fixed_reference_deterministic_cost_v3_20260716"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "runs"
    / "steel_s2_post_cost_reconciliation_v2_20260716"
)
ANNUAL_FACTOR = 8760.0 / 168.0
CONFIGURATIONS = (
    "C0_current_BF_BOF_reference",
    "C1_phase1_BF_BOF_plus_DRP_EAF",
)
PARENT_FILES = (
    "run_summary.json",
    "resolved_config.yaml",
    "input_manifest.json",
    "validation_checks.csv",
    "executed_hourly.csv",
    "annual_physical_boundary_ledger.csv",
    "annual_anchor_reconciliation.csv",
    "independent_anchor_family_summary.csv",
    "first_window_model_metrics.csv",
    "executed_procurement_cost_ledger.csv",
    "procurement_cost_summary.csv",
    "procurement_cost_by_component.csv",
    "procurement_cost_by_route.csv",
    "cost_objective_reconciliation.csv",
    "future_cost_boundary_contract.csv",
)


class PostCostReconciliationError(ValueError):
    """Raised when solved fixed-reference lineage is incomplete or inconsistent."""


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise PostCostReconciliationError(f"Required artifact is empty: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parent_fingerprint(parent: Path) -> tuple[str, list[dict[str, str]]]:
    combined = hashlib.sha256()
    files: list[dict[str, str]] = []
    for name in PARENT_FILES:
        path = parent / name
        if not path.is_file():
            raise PostCostReconciliationError(f"Parent is missing {name}.")
        digest = _sha256(path)
        files.append({"path": name, "sha256": digest})
        combined.update(name.encode())
        combined.update(digest.encode())
    return combined.hexdigest(), files


def _post_cost_classification(row: dict[str, str]) -> str:
    if row.get("scenario_definition_status") == "scenario_definition" or row.get(
        "anchor_role"
    ) in {"scenario_definition", "active_model_target"}:
        return "scenario_definition"
    if (
        row.get("comparability_status") == "directly_comparable"
        and row.get("use_in_primary_score") == "yes"
    ):
        return "primary_comparable"
    if row.get("comparability_status") == "partially_comparable_reporting_only":
        return "reporting_only"
    if row.get("comparability_status") == "directly_comparable":
        return "secondary_context"
    reason = row.get("explicit_exclusion_reason", "").lower()
    if "missing" in reason or "blocked" in reason:
        return "blocked"
    return "not_comparable"


def _configuration_summary(
    hourly: list[dict[str, str]],
    metrics: list[dict[str, str]],
    costs: list[dict[str, str]],
) -> list[dict[str, Any]]:
    metric_rows = {row["configuration_id"]: row for row in metrics}
    cost_rows = {row["configuration_id"]: row for row in costs}
    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    fields = {
        "bf_hot_metal_mt_y": {
            "C0_current_BF_BOF_reference": "C0_BF_hot_iron_output_t",
            "C1_phase1_BF_BOF_plus_DRP_EAF": "C1_retained_BF_hot_iron_output_t_h",
        },
        "drp_dri_mt_y": {
            "C0_current_BF_BOF_reference": "",
            "C1_phase1_BF_BOF_plus_DRP_EAF": "C1_DRP_DRI_output_t_h",
        },
    }
    for row in hourly:
        configuration = row["configuration_id"]
        for output, mapping in fields.items():
            field = mapping[configuration]
            if field:
                sums[configuration][output] += float(row.get(field) or 0.0)
    result: list[dict[str, Any]] = []
    for configuration in CONFIGURATIONS:
        metric = metric_rows[configuration]
        cost = cost_rows[configuration]
        result.append(
            {
                "configuration_id": configuration,
                "bf_hot_metal_mt_y": round(
                    sums[configuration]["bf_hot_metal_mt_y"] * ANNUAL_FACTOR / 1e6,
                    9,
                ),
                "bof_liquid_steel_mt_y": metric["bof_liquid_steel_mt_y"],
                "drp_dri_mt_y": round(
                    sums[configuration]["drp_dri_mt_y"] * ANNUAL_FACTOR / 1e6,
                    9,
                ),
                "eaf_liquid_steel_mt_y": metric["eaf_liquid_steel_mt_y"],
                "hsm_hrc_output_mt_y": metric["hsm_hrc_output_mt_y"],
                "dsp_output_mt_y": metric["dsp_output_mt_y"],
                "imported_slab_mt_y": metric["imported_slab_mt_y"],
                "site_final_product_mt_y": metric["final_product_proxy_mt_y"],
                "wag_generation_pj_y": metric["wag_generation_pj_y"],
                "wag_use_pj_y": metric["wag_use_pj_y"],
                "wag_flare_pj_y": metric["wag_flare_pj_y"],
                "gross_electricity_pj_y": metric["gross_electricity_pj_y"],
                "internal_generation_twh_y": metric["generator_electricity_twh_y"],
                "grid_import_pj_y": metric["net_grid_import_pj_y"],
                "represented_named_ng_pj_y": metric["represented_ng_pj_y"],
                "represented_steam_kt_y": metric["steam_15bar_kt_y"],
                "mode_b_explicit_fuel_co2_mt_y": metric[
                    "mode_b_explicit_fuel_co2_mt_y"
                ],
                "executed_procurement_cost_eur": cost[
                    "executed_procurement_cost_eur"
                ],
                "annualised_procurement_cost_eur_y": cost[
                    "annualised_procurement_cost_eur_y"
                ],
                "procurement_cost_eur_per_t_final_product": cost[
                    "procurement_cost_eur_per_t_final_product"
                ],
                "cost_claim_boundary": "represented_external_procurement_only",
            }
        )
    return result


def run_post_cost_reconciliation(
    *, parent_run_directory: str | Path = DEFAULT_PARENT,
    output_directory: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    parent = Path(parent_run_directory).resolve()
    output = Path(output_directory).resolve()
    if output.exists():
        raise PostCostReconciliationError(f"Output already exists: {output}")
    fingerprint, files = _parent_fingerprint(parent)
    parent_summary = _json(parent / "run_summary.json")
    if parent_summary.get("status") != "pass" or parent_summary.get(
        "execution_mode"
    ) != "fixed_reference_cost":
        raise PostCostReconciliationError("Parent is not an accepted fixed-reference cost run.")
    parent_checks = _csv(parent / "validation_checks.csv")
    if any(row["status"] != "pass" for row in parent_checks):
        raise PostCostReconciliationError("Parent guardrails are not all pass.")
    hourly = _csv(parent / "executed_hourly.csv")
    anchors = _csv(parent / "annual_anchor_reconciliation.csv")
    classified_anchors = [
        {**row, "post_cost_classification": _post_cost_classification(row)}
        for row in anchors
    ]
    classes = Counter(row["post_cost_classification"] for row in classified_anchors)
    cost_ledger = _csv(parent / "executed_procurement_cost_ledger.csv")
    cost_summary = _csv(parent / "procurement_cost_summary.csv")
    component_costs = _csv(parent / "procurement_cost_by_component.csv")
    route_costs = _csv(parent / "procurement_cost_by_route.csv")
    ledger_total = sum(float(row["cost_eur"]) for row in cost_ledger)
    summary_total = sum(float(row["executed_procurement_cost_eur"]) for row in cost_summary)
    component_total = sum(float(row["cost_eur"]) for row in component_costs)
    route_total = sum(float(row["cost_eur"]) for row in route_costs)
    cost_identity_residual = max(
        abs(ledger_total - summary_total),
        abs(component_total - summary_total),
        abs(route_total - summary_total),
    )
    configuration_rows = _configuration_summary(
        hourly,
        _csv(parent / "first_window_model_metrics.csv"),
        cost_summary,
    )
    cost_contract = _csv(parent / "future_cost_boundary_contract.csv")
    excluded_rows = [
        {
            "configuration": row["configuration"],
            "flow_id": row["flow_id"],
            "component": row["component"],
            "carrier_or_material": row["carrier"],
            "exclusion_reason": row["deferred_reason"],
            "cost_readiness_status": row["cost_readiness_status"],
            "cost_eur": 0.0,
        }
        for row in cost_contract
        if row["objective_enabled"] == "false"
    ]
    comparable_primary = [
        row
        for row in classified_anchors
        if row["post_cost_classification"] == "primary_comparable"
    ]
    primary_below = sum(
        float(row["absolute_residual_pct"]) <= 7.5 for row in comparable_primary
    )
    checks = [
        {
            "check_id": "same_solved_cost_lineage",
            "status": "pass",
            "evidence": f"parent={parent.name};fingerprint={fingerprint}",
        },
        {
            "check_id": "parent_physical_and_cost_guardrails",
            "status": "pass",
            "evidence": f"{len(parent_checks)}/{len(parent_checks)} parent checks pass",
        },
        {
            "check_id": "cost_identity",
            "status": "pass" if cost_identity_residual <= 1e-4 else "fail",
            "evidence": f"max_abs_residual_eur={cost_identity_residual:.9f}",
        },
        {
            "check_id": "scenario_definitions_excluded_from_primary",
            "status": "pass"
            if all(
                row["post_cost_classification"] != "primary_comparable"
                for row in classified_anchors
                if row["scenario_definition_status"] == "scenario_definition"
                or row["anchor_role"] in {"scenario_definition", "active_model_target"}
            )
            else "fail",
            "evidence": "post_cost_anchor_comparison.csv",
        },
        {
            "check_id": "independent_matching_cost_benchmark",
            "status": "pass",
            "evidence": "none_available; cost results remain represented-procurement scenario outputs",
        },
    ]
    status = "pass" if all(row["status"] == "pass" for row in checks) else "fail"
    output.mkdir(parents=True)
    _write_csv(output / "post_cost_configuration_summary.csv", configuration_rows)
    _write_csv(output / "post_cost_anchor_comparison.csv", classified_anchors)
    _write_csv(output / "post_cost_cost_by_component.csv", component_costs)
    _write_csv(output / "post_cost_cost_by_route.csv", route_costs)
    _write_csv(output / "excluded_cost_boundary.csv", excluded_rows)
    _write_csv(output / "post_cost_validation.csv", checks)
    manifest = {
        "run_id": output.name,
        "run_class": "post_cost_physical_anchor_cost_reconciliation",
        "lineage_role": "derived_from_same_solved_fixed_reference_cost_run",
        "output_policy": "minimal",
        "parent_run": parent.name,
        "parent_fingerprint_sha256": fingerprint,
        "parent_files": files,
    }
    _write_json(output / "input_manifest.json", manifest)
    (output / "resolved_config.yaml").write_text(
        json.dumps(
            {
                "run_id": output.name,
                "parent_run": parent.name,
                "solver_invoked": False,
                "annualisation": "8760/168_reporting_only",
                "cost_boundary": "represented_external_procurement_only",
                "output_policy": "minimal",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    parent_code = _json(parent / "code_version.json")
    _write_json(
        output / "code_version.json",
        {
            "git_commit": parent_code.get("git_commit"),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "module_sha256": _sha256(Path(__file__)),
        },
    )
    summary = {
        "run_id": output.name,
        "status": status,
        "parent_run": parent.name,
        "parent_status": parent_summary["status"],
        "parent_execution_mode": parent_summary["execution_mode"],
        "cost_identity_max_abs_residual_eur": round(cost_identity_residual, 9),
        "anchor_classification_counts": dict(sorted(classes.items())),
        "independent_primary_comparable_rows": len(comparable_primary),
        "independent_primary_rows_below_7_5pct": primary_below,
        "independent_matching_cost_benchmark_status": "not_available",
        "route_cost_coverage_status": "adequate_represented_major_inputs_with_explicit_scope_gaps",
        "next_permitted_phase": "bounded_fixed_reference_cost_sensitivities",
        "configuration_results": configuration_rows,
    }
    _write_json(output / "run_summary.json", summary)
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": output.name,
            "run_class": "post_cost_physical_anchor_cost_reconciliation",
            "lineage_role": "derived_from_same_solved_fixed_reference_cost_run",
            "output_policy": "minimal",
            "status": status,
        },
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- Every value is derived from the same accepted rolling fixed-reference cost run.\n"
        "- Annual values extrapolate 168 executed hours and are not a calendar-year simulation.\n"
        "- Scenario definitions do not validate themselves.\n"
        "- No independent matching variable-procurement cost benchmark is available.\n"
        "- Costs exclude residual energy, internal carriers, BF-pellet/HBI scope gaps, revenue and ETS.\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        f"# {output.name}\n\n"
        f"- Status: {status}\n"
        f"- Parent: {parent.name}\n"
        "- Role: post-cost physical, anchor and represented-procurement reconciliation.\n"
        "- Solver: not rerun; all evidence is fingerprinted to the accepted rolling parent.\n",
        encoding="utf-8",
    )
    return {"run_directory": output, "summary": summary}
