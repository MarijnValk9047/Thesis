"""Compile C1 anchor-boundary closure evidence without altering physical dispatch.

This stage is deliberately a ledger compiler.  It consumes separately solved
endogenous and MER-site-product C1 runs, preserves every residual, and refuses
to promote partial site totals to scored physical anchors.
"""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


STAGE = "S4.4c5p_ay_anchor_boundary_closure"
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "configs" / "steel_anchor_boundary_closure.yaml"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
HISTORICAL_WAG_LEDGER = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "s4_4c5p_m_wag_balance_and_controller_contract"
    / "wag_carrier_balance_matrix.csv"
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Anchor boundary closure config must be a mapping.")
    required = {"run_id", "source_runs", "output_policy", "run_class", "lineage_role"}
    missing = required.difference(data)
    if missing:
        raise ValueError(f"Anchor boundary closure config is missing: {sorted(missing)}")
    return data


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _as_float(row: dict[str, str], field: str) -> float:
    value = row.get(field, "")
    if value in (None, ""):
        return 0.0
    return float(value)


def _utility_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["metric"]: row for row in rows}


def _anchor_contract_rows(source_label: str, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Make the minimum complete boundary contract explicit for every row."""
    contracts: dict[str, tuple[str, str, str, str, str]] = {
        "active_final_product_target_6_75": (
            "site_final_product_t", "final_product_proxy", "scenario_quota", "not_scaled", "primary_score"
        ),
        "c1_generator_wag_with_flare_10_6": (
            "carrier_specific_generator_plus_flare_WAG", "not_applicable", "represented_generator_interface", "not_scaled", "secondary_context"
        ),
        "c1_generator_flare_0_1": (
            "carrier_specific_flare_WAG", "not_applicable", "represented_generator_interface", "not_scaled", "supporting_diagnostic"
        ),
        "c1_official_total_site_electricity_17_8pj_missing": (
            "represented_gross_electricity", "site_annual_total", "partial_represented_process_boundary", "not_scaled", "reporting_only"
        ),
        "athan_table9_phase1_electricity_4_89": (
            "represented_gross_electricity", "unverified", "partial_represented_process_boundary", "scaling_not_allowed", "secondary_context"
        ),
        "c1_official_grid_import_11_7pj_missing": (
            "net_grid_import_after_internal_offset", "site_annual_total", "partial_represented_process_boundary", "not_scaled", "reporting_only"
        ),
        "c1_generator_total_with_flare_14_6": (
            "unavailable_named_NG_generator_component", "not_applicable", "anchor_includes_unmodelled_named_NG", "not_scaled", "not_comparable"
        ),
        "c1_official_scope1_8_3_missing": (
            "Mode_B_explicit_fuel_subtotal", "site_annual_total", "represented_oxidation_sinks_only", "not_scaled", "reporting_only"
        ),
        "athan_table9_phase1_co2_9_108": (
            "Mode_B_explicit_fuel_subtotal", "unverified", "represented_oxidation_sinks_only", "scaling_not_allowed", "not_comparable"
        ),
        "athan_table9_phase1_wag_1_23": (
            "internal_WAG_generator_electricity_offset", "unverified", "generator_interface_only", "scaling_not_allowed", "secondary_context"
        ),
    }
    output: list[dict[str, Any]] = []
    for row in rows:
        numerator, denominator, boundary, scaling, score_status = contracts.get(
            row["anchor_id"],
            ("unknown", "unknown", "unknown", "scaling_not_allowed", "blocked"),
        )
        comparable = score_status in {"primary_score", "secondary_context"} and row.get("status") == "comparable_with_caveat"
        model_value = row.get("model_value", "")
        anchor_value = row.get("anchor_value", "")
        residual_share = row.get("signed_residual_share", "")
        output.append(
            {
                "source_case": source_label,
                "anchor_id": row["anchor_id"],
                "metric": row.get("metric", ""),
                "model_value": model_value,
                "anchor_value": anchor_value,
                "unit": row.get("unit", ""),
                "signed_residual": row.get("signed_residual", ""),
                "signed_residual_share": residual_share,
                "numerator_boundary": numerator,
                "denominator_boundary": denominator,
                "site_or_process_boundary": boundary,
                "scaling_status": scaling,
                "score_status": score_status,
                "comparability_status": "comparable" if comparable else "not_comparable_or_reporting_only",
                "within_7_5pct": "yes" if comparable and residual_share not in ("", None) and abs(float(residual_share)) < 0.075 else "no",
                "exclusion_reason": "" if comparable else row.get("caveat", "boundary contract excludes score"),
            }
        )
    return output


def _identity_rows(source_label: str, utilities: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    gross = _as_float(utilities["gross_electricity"], "model_value")
    offset = _as_float(utilities["internal_WAG_generator_electricity_offset"], "model_value")
    net = _as_float(utilities["net_grid_import_after_internal_WAG_offset"], "model_value")
    steam_demand = _as_float(utilities["modelled_steam_15bar_demand"], "model_value")
    steam_supply = _as_float(utilities["modelled_steam_15bar_supply"], "model_value")
    steam_unserved = _as_float(utilities["modelled_steam_15bar_unserved"], "model_value")
    return [
        {
            "source_case": source_label,
            "identity": "gross_electricity_equals_internal_offset_plus_net_import",
            "left_value": gross,
            "right_value": round(offset + net, 9),
            "unit": "TWh/y",
            "residual": round(gross - offset - net, 9),
            "status": "pass" if abs(gross - offset - net) <= 1e-6 else "fail",
            "caveat": "Identity closes the represented boundary only; it does not claim site-meter coverage.",
        },
        {
            "source_case": source_label,
            "identity": "mapped_15bar_steam_supply_equals_demand_plus_unserved",
            "left_value": steam_supply,
            "right_value": round(steam_demand + steam_unserved, 9),
            "unit": "kt_steam/y",
            "residual": round(steam_supply - steam_demand - steam_unserved, 9),
            "status": "pass" if abs(steam_supply - steam_demand - steam_unserved) <= 1e-6 else "fail",
            "caveat": "Mapped C5p_b demand only; unmodelled site steam remains outside the boundary.",
        },
        {
            "source_case": source_label,
            "identity": "Mode_B_CO2_excludes_aggregate_process_counters",
            "left_value": _as_float(utilities["WAG_explicit_combustion_CO2"], "model_value"),
            "right_value": "not_applicable",
            "unit": "MtCO2/y",
            "residual": "not_applicable",
            "status": "pass",
            "caveat": "Fuel-explicit point-of-oxidation subtotal only; aggregate process counters remain excluded.",
        },
    ]


def _wag_activity_basis_rows(
    source_label: str, current_rows: list[dict[str, str]], historical_rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    current = {row["carrier"]: row for row in current_rows if row.get("carrier") in {"BFG", "COG", "BOFG"}}
    historical = {
        row["carrier"]: row
        for row in historical_rows
        if row.get("configuration", "").startswith("C1") and row.get("carrier") in {"BFG", "COG", "BOFG"}
    }
    rows: list[dict[str, Any]] = []
    for carrier in ("BFG", "COG", "BOFG"):
        current_generation = _as_float(current.get(carrier, {}), "generation_MWh_LHV_y") * 3.6 / 1_000_000.0
        historical_generation = _as_float(historical.get(carrier, {}), "generation_PJ_y")
        rows.append(
            {
                "source_case": source_label,
                "carrier": carrier,
                "integrated_run_generation_PJ_y": round(current_generation, 6),
                "C5p_m_generation_PJ_y": round(historical_generation, 6),
                "difference_PJ_y": round(current_generation - historical_generation, 6),
                "comparison_status": "boundary_mismatch_not_a_coefficient_target",
                "explanation": "The ledgers use different activity/controller boundaries; reconcile source-run activity and sinks before changing carrier coefficients.",
            }
        )
    return rows


def _origin_rows(source_label: str, source_directory: Path) -> list[dict[str, Any]]:
    path = source_directory / "origin_material_ledger.csv"
    if not path.exists():
        return [{
            "source_case": source_label,
            "origin_metric": "origin_material_ledger",
            "value": "",
            "unit": "",
            "status": "blocked_missing_export",
            "caveat": "The source run does not export origin-tagged material flows; do not score site-final-product anchors.",
        }]
    rows: list[dict[str, Any]] = []
    for row in _read_csv(path):
        rows.append({"source_case": source_label, "origin_metric": row.get("metric", row.get("origin", "")), "value": row.get("annual_value", row.get("model_value", "")), "unit": row.get("unit", ""), "status": row.get("status", "reported"), "caveat": row.get("caveat", "")})
    return rows


def _origin_feasibility_rows(root: Path, run_id: str | None) -> list[dict[str, Any]]:
    if not run_id:
        return []
    path = root / run_id / "configuration_build_audit.csv"
    if not path.exists():
        return [{
            "scenario_id": "",
            "boundary_role": "",
            "annual_site_final_product_target_mt_y": "",
            "imported_slab_annual_cap_mt_y": "",
            "build_status": "missing_origin_feasibility_audit",
            "termination_condition": "not_available",
            "comparability_status": "not_comparable_to_utility_reconciliation",
            "caveat": "The simplified origin-feasibility audit is missing; do not infer an all-endogenous result.",
        }]
    rows: list[dict[str, Any]] = []
    for row in _read_csv(path):
        rows.append({
            **row,
            "comparability_status": "not_comparable_to_utility_reconciliation",
            "caveat": "This is a separately scoped origin-feasibility surface. It records structural feasibility only and is not an annual energy-anchor run.",
        })
    return rows


def _sensitivity_eligibility_rows(source_label: str, source_directory: Path) -> list[dict[str, Any]]:
    path = source_directory / "representation_gap_register.csv"
    if not path.exists():
        return [{
            "source_case": source_label,
            "lever_family": "representation_gap_register",
            "status": "blocked_missing_register",
            "may_run_now": "no",
            "reason": "No source-run representation-gap register is available.",
        }]
    rows: list[dict[str, Any]] = []
    for row in _read_csv(path):
        status = row.get("status", "")
        may_run = status == "accepted_development"
        rows.append({
            "source_case": source_label,
            "lever_family": row.get("process_or_interface", ""),
            "current_status": status,
            "may_run_now": "yes" if may_run else "no",
            "reason": "Only accepted-development rows with a clear activity driver, unit and no overlap may enter a bounded sensitivity.",
            "caveat": row.get("why_not_more", ""),
        })
    return rows


def run_anchor_boundary_closure(*, config_path: str | Path = DEFAULT_CONFIG, output_root: str | Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    config = _load_config(Path(config_path))
    root = Path(output_root).resolve()
    output_directory = root / str(config["run_id"])
    if output_directory.exists():
        raise ValueError(f"Run directory already exists: {output_directory}")
    output_directory.mkdir(parents=True)
    historical = _read_csv(HISTORICAL_WAG_LEDGER)
    contracts: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    wag_rows: list[dict[str, Any]] = []
    origin_rows: list[dict[str, Any]] = []
    sensitivity_rows: list[dict[str, Any]] = []
    for source in config["source_runs"]:
        source_id = str(source["run_id"])
        source_label = str(source["label"])
        source_directory = root / source_id
        required = ("anchor_comparison.csv", "utility_energy_co2_ledger.csv", "wag_carrier_ledger.csv", "guardrail_checks.csv", "run_summary.json")
        missing = [name for name in required if not (source_directory / name).exists()]
        if missing:
            raise ValueError(f"Source run {source_id} lacks required artifacts: {missing}")
        anchor_rows = _read_csv(source_directory / "anchor_comparison.csv")
        utilities = _utility_map(_read_csv(source_directory / "utility_energy_co2_ledger.csv"))
        contracts.extend(_anchor_contract_rows(source_label, anchor_rows))
        identities.extend(_identity_rows(source_label, utilities))
        wag_rows.extend(_wag_activity_basis_rows(source_label, _read_csv(source_directory / "wag_carrier_ledger.csv"), historical))
        origin_rows.extend(_origin_rows(source_label, source_directory))
        sensitivity_rows.extend(_sensitivity_eligibility_rows(source_label, source_directory))

    origin_feasibility = _origin_feasibility_rows(root, config.get("origin_feasibility_run_id"))
    eligible_sensitivities = [row for row in sensitivity_rows if row.get("may_run_now") == "yes"]

    eligible = [row for row in contracts if row["comparability_status"] == "comparable"]
    passed = [row for row in eligible if row["within_7_5pct"] == "yes"]
    eligible_families = {str(row["metric"]) for row in eligible}
    passed_families = {str(row["metric"]) for row in passed}
    identity_failures = [row for row in identities if row["status"] == "fail"]
    origin_export_complete = not any(row["status"] == "blocked_missing_export" for row in origin_rows)
    summary = {
        "run_id": config["run_id"],
        "stage": STAGE,
        "status": "pass_with_boundary_gaps" if not identity_failures else "fail",
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "retention": config.get("retention", "local_run_artifact_not_git_eligible_by_default"),
        "anchor_proximity_threshold_abs_share": 0.075,
        "comparable_anchor_count": len(eligible),
        "boundary_comparable_anchor_rows": len(eligible),
        "boundary_comparable_metric_families": len(eligible_families),
        "anchors_within_7_5pct": len(passed),
        "metric_families_within_7_5pct": len(passed_families),
        "identity_failures": len(identity_failures),
        "origin_export_complete": origin_export_complete,
        "eligible_new_sensitivity_count": len(eligible_sensitivities),
        "sensitivity_runs_executed_in_this_closure": 0,
        "ready_for_cost_design": False,
        "reason_not_ready": "Boundary-comparable anchor coverage is incomplete; site electricity, full-site NG and Scope 1 remain residual reporting quantities.",
    }
    _write_csv(output_directory / "anchor_boundary_contract_matrix.csv", contracts)
    _write_csv(output_directory / "physical_ledger_identity_checks.csv", identities)
    _write_csv(output_directory / "wag_activity_basis_reconciliation.csv", wag_rows)
    _write_csv(output_directory / "origin_boundary_case_ledger.csv", origin_rows)
    _write_csv(output_directory / "origin_feasibility_case_audit.csv", origin_feasibility)
    _write_csv(output_directory / "sensitivity_eligibility_register.csv", sensitivity_rows)
    _write_json(output_directory / "run_summary.json", summary)
    _write_json(output_directory / "s4_4c5p_ay_stage_gate.json", summary)
    _write_json(output_directory / "code_version.json", {"git_revision": _git_revision(), "module": __file__})
    _write_json(output_directory / "input_manifest.json", {"config": Path(config_path).resolve().relative_to(REPO_ROOT).as_posix(), "source_runs": config["source_runs"], "historical_wag_ledger": HISTORICAL_WAG_LEDGER.relative_to(REPO_ROOT).as_posix()})
    _write_json(output_directory / "registry_entry.json", {"run_id": config["run_id"], "output_policy": config["output_policy"], "run_class": config["run_class"], "lineage_role": config["lineage_role"], "git_eligible": False})
    (output_directory / "resolved_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (output_directory / "warnings_and_limitations.md").write_text(
        "# Limitations\n\n"
        "- This stage compiles existing physical runs; it does not solve, allocate residuals or tune coefficients.\n"
        "- Site electricity, full-site NG and Scope 1 rows are retained as reporting residuals when their boundary differs.\n"
        "- C5p_m versus integrated WAG differences are activity/boundary evidence, not a WAG-factor sensitivity target.\n"
        "- Imported slab is valid only in its explicit MER site-boundary case and has no upstream energy, WAG, NG or CO2 assignment.\n",
        encoding="utf-8",
    )
    return {"run_directory": output_directory, "summary": summary}
