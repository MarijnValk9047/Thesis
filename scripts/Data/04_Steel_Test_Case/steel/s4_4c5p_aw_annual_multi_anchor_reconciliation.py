"""Compile comparable annual C1 anchor evidence without changing dispatch."""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


STAGE = "S4.4c5p_aw_annual_multi_anchor_reconciliation"
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "Data" / "04_Steel_Test_Case" / "configs" / "steel_annual_multi_anchor_reconciliation.yaml"
DEFAULT_RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Annual multi-anchor reconciliation config must be a mapping.")
    if not config.get("source_runs"):
        raise ValueError("Annual multi-anchor reconciliation requires source_runs.")
    return config


def _float(row: dict[str, str], field: str) -> float:
    return float(row[field])


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _proximity(abs_share: float, comparable: bool, target: float, review: float) -> str:
    if not comparable:
        return "not_scored"
    # The pre-economics boundary policy treats 7.5% as an exclusive target:
    # an anchor exactly at the threshold still needs review.
    if abs_share < target:
        return "within_7_5pct_target"
    if abs_share <= review:
        return "within_10pct_review"
    return "outside_10pct"


def _comparability_contract(anchor_id: str) -> dict[str, str]:
    """State the current numerator/denominator boundary before any scoring.

    This deliberately classifies a small set of C1 rows from the integrated
    reconciliation runner.  All other registered anchors remain outside this
    run's boundary rather than being given a synthetic comparison.
    """

    direct = {
        "active_final_product_target_6_75": (
            "same final-product proxy",
            "same 6.75-Mt/y active target",
            "same rolling physical boundary",
            "not_required_same_target",
            "production_guardrail_achieved_by_construction",
            "no",
            "production_guardrail",
            "achieved_by_construction_not_independent_validation",
            "Keep production and material guardrails active, but exclude the target from independent anchor closure.",
        ),
        "c1_generator_wag_with_flare_10_6": (
            "BFG + COG + BOFG generator fuel plus carrier-specific flare",
            "same annual energy subtotal",
            "same C1 generator WAG interface; named NG excluded on both sides",
            "not_required_same_annual_energy_subtotal",
            "direct_comparable",
            "yes",
            "secondary_context",
            "",
            "Retain carrier-specific sink checks; do not turn the subtotal into an hourly target.",
        ),
        "c1_generator_flare_0_1": (
            "carrier-specific modeled flare",
            "same annual flare energy unit",
            "same generator-interface context, but very small absolute anchor",
            "not_required_same_annual_energy_unit",
            "source_row_not_comparable_low_absolute_value",
            "no",
            "secondary_context",
            "source_row_not_comparable_and_low_absolute_value",
            "Check flare only as a supporting WAG signal; do not create flare to improve a percentage gap.",
        ),
    }
    partial = {
        "c1_official_total_site_electricity_17_8pj_missing": (
            "represented model gross electricity",
            "official site-total annual electricity",
            "model excludes residual/background loads and some process-service boundaries",
            "not_allowed_partial_site_boundary",
            "partial_site_boundary",
            "no",
            "secondary_context",
            "partial_site_boundary",
            "Complete or explicitly retain non-WAG electricity buckets; keep the remaining residual visible.",
        ),
        "athan_table9_phase1_electricity_4_89": (
            "represented model gross electricity",
            "Athanasiadis total electricity",
            "Athanasiadis denominator and total-site meter boundary remain unresolved",
            "not_allowed_denominator_and_meter_boundary_unresolved",
            "model_precedent_partial_boundary",
            "no",
            "secondary_context",
            "unresolved_denominator_and_site_meter_boundary",
            "Use only after a denominator/meter-boundary bridge; do not silently scale Table 9.",
        ),
        "c1_official_grid_import_11_7pj_missing": (
            "represented net import after internal WAG offset",
            "official site grid-import annual total",
            "site meter and internal-generation boundaries are incomplete in the physical model",
            "not_allowed_partial_site_meter_boundary",
            "partial_site_boundary",
            "no",
            "secondary_context",
            "partial_site_boundary",
            "Keep gross demand, internal offset, import and residual electricity as separate rows.",
        ),
        "athan_table9_phase1_wag_1_23": (
            "internal WAG-to-electricity offset",
            "Athanasiadis WAG electricity total",
            "generator fuel, named NG and denominator conventions are not demonstrably identical",
            "not_allowed_generator_fuel_and_denominator_unresolved",
            "model_precedent_partial_boundary",
            "no",
            "secondary_context",
            "unresolved_generator_fuel_and_denominator_boundary",
            "Use as a directional context check only; do not tune generator efficiency or fuel allocation to it.",
        ),
    }
    not_comparable = {
        "c1_generator_total_with_flare_14_6": (
            "WAG-only generator fuel and flare",
            "MER total generator fuel plus flare",
            "anchor includes 4.1 PJ/y named VN25 NG without a current hourly driver",
            "not_allowed_named_NG_hourly_driver_missing",
            "named_ng_boundary_missing",
            "no",
            "not_comparable",
            "named_NG_hourly_driver_missing",
            "Keep the 14.6-PJ/y total visible but do not calculate a gap or allocate NG to close it.",
        ),
        "c1_official_scope1_8_3_missing": (
            "represented WAG combustion subtotal",
            "full-site Scope 1",
            "named NG, non-fuel process emissions, capture convention and unrepresented site sources differ",
            "not_allowed_mode_B_subtotal_vs_full_site_scope1",
            "mode_B_vs_site_scope1",
            "no",
            "reporting_only",
            "mode_B_subtotal_vs_full_site_scope1",
            "Use the separate explicit-fuel ledger; do not consolidate Mode B with aggregate process counters.",
        ),
        "athan_table9_phase1_co2_9_108": (
            "represented WAG combustion subtotal",
            "Athanasiadis CO2 total",
            "CO2 mode and production denominator are unresolved",
            "not_allowed_CO2_mode_and_denominator_unresolved",
            "mode_B_vs_model_precedent_total",
            "no",
            "reporting_only",
            "CO2_mode_and_denominator_unresolved",
            "Retain as reporting context only until a reconciled non-fuel/capture boundary exists.",
        ),
    }
    values = direct.get(anchor_id) or partial.get(anchor_id) or not_comparable.get(anchor_id)
    if values is None:
        return {
            "numerator_alignment": "not mapped by this C1 physical run",
            "denominator_alignment": "not mapped by this C1 physical run",
            "boundary_alignment": "outside or unresolved relative to active run",
            "scaling_status": "not_allowed_unmapped_anchor",
            "comparability_decision": "not_mapped_in_current_run",
            "score_eligible": "no",
            "score_status": "not_comparable",
            "exclusion_reason": "not_mapped_in_current_run",
            "required_reconciliation": "Use the canonical anchor register and a source-backed component/run mapping before comparison.",
            "anchor_family": "unmapped",
            "independent_validation": "no",
        }
    contract = dict(zip(
        (
            "numerator_alignment",
            "denominator_alignment",
            "boundary_alignment",
            "scaling_status",
            "comparability_decision",
            "score_eligible",
            "score_status",
            "exclusion_reason",
            "required_reconciliation",
        ),
        values,
        strict=True,
    ))
    family_by_anchor = {
        "active_final_product_target_6_75": "production_guardrail",
        "c1_official_total_site_electricity_17_8pj_missing": "gross_site_electricity",
        "athan_table9_phase1_electricity_4_89": "gross_site_electricity",
        "c1_official_grid_import_11_7pj_missing": "grid_import_electricity",
        "c1_generator_wag_with_flare_10_6": "generator_wag_interface",
        "c1_generator_total_with_flare_14_6": "generator_wag_interface",
        "c1_generator_flare_0_1": "generator_wag_interface",
        "athan_table9_phase1_wag_1_23": "generator_wag_electricity",
        "c1_official_scope1_8_3_missing": "site_scope1_co2",
        "athan_table9_phase1_co2_9_108": "site_scope1_co2",
    }
    contract["anchor_family"] = family_by_anchor.get(anchor_id, "unmapped")
    contract["independent_validation"] = (
        "yes" if contract["score_eligible"] == "yes" and contract["anchor_family"] != "production_guardrail" else "no"
    )
    return contract


def _annual_anchor_rows(source: dict[str, Any], run_directory: Path, policy: dict[str, float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _read_csv(run_directory / "anchor_comparison.csv"):
        contract = _comparability_contract(row["anchor_id"])
        comparable = (
            contract["score_eligible"] == "yes"
            and row["comparison_class"] in {"primary_score", "secondary_context", "boundary_comparable"}
            and row["status"] == "comparable_with_caveat"
        )
        share_text = row.get("signed_residual_share", "")
        share = float(share_text) if share_text not in {"", None} else 0.0
        rows.append({
            "source_run_id": source["run_id"],
            "configuration_id": source.get("configuration_id", "C1_phase1_BF_BOF_plus_DRP_EAF"),
            "scenario_label": source["label"],
            "scenario_role": source["role"],
            "lineage_role": source.get("lineage_role", "unclassified"),
            "currentness_status": source.get("currentness_status", "not_declared"),
            "anchor_id": row["anchor_id"],
            "metric": row["metric"],
            # These are explicit boundary-contract fields.  Keep the older
            # alignment columns below for compatibility with prior C5p_aw
            # output consumers.
            "numerator_definition": contract["numerator_alignment"],
            "denominator_definition": contract["denominator_alignment"],
            "site_process_boundary": contract["boundary_alignment"],
            "scaling_status": contract["scaling_status"],
            "score_status": contract["score_status"],
            "exclusion_reason": contract["exclusion_reason"],
            "model_value": row["model_value"],
            "anchor_value": row["anchor_value"],
            "unit": row["unit"],
            "signed_residual": row["signed_residual"],
            "signed_residual_share": row["signed_residual_share"],
            "absolute_residual_share": abs(share) if share_text not in {"", None} else "",
            "comparison_class": row["comparison_class"],
            "comparison_basis": row["comparison_basis"],
            "source_rank": row["source_rank"],
            "locator_quality": row["locator_quality"],
            "boundary_comparable": "yes_with_caveat" if comparable else "no",
            "proximity_status": _proximity(abs(share), comparable, policy["target_abs_residual_share"], policy["review_abs_residual_share"]),
            **contract,
            "caveat": row["caveat"],
        })
    return rows


def _anchor_family_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["anchor_family"]), []).append(row)
    summaries: list[dict[str, Any]] = []
    for family, family_rows in sorted(grouped.items()):
        comparable = [
            row
            for row in family_rows
            if row["boundary_comparable"] == "yes_with_caveat" and row["independent_validation"] == "yes"
        ]
        within_target = [row for row in comparable if row["proximity_status"] == "within_7_5pct_target"]
        summaries.append(
            {
                "anchor_family": family,
                "row_count": len(family_rows),
                "independent_comparable_row_count": len(comparable),
                "independent_comparable_family": "yes" if comparable else "no",
                "family_below_7_5pct": "yes" if within_target else "no",
                "qualifying_anchor_ids": ";".join(sorted(str(row["anchor_id"]) for row in within_target)),
                "exclusion_reasons": ";".join(
                    sorted({str(row["exclusion_reason"]) for row in family_rows if row["exclusion_reason"]})
                ),
                "currentness_status": ";".join(sorted({str(row["currentness_status"]) for row in family_rows})),
            }
        )
    return summaries


def _origin_burden_rows(source: dict[str, Any], run_directory: Path) -> list[dict[str, Any]]:
    required_metrics = {
        "imported_slab_to_HSM",
        "HSM_origin_input_balance_residual",
        "imported_slab_upstream_electricity",
        "imported_slab_upstream_WAG",
        "imported_slab_upstream_NG",
        "imported_slab_upstream_direct_fuel_CO2",
    }
    rows = [row for row in _read_csv(run_directory / "origin_material_ledger.csv") if row["metric"] in required_metrics]
    if {row["metric"] for row in rows} != required_metrics:
        raise ValueError(f"{source['run_id']} lacks the complete imported-slab origin/burden contract.")
    return [
        {
            "source_run_id": source["run_id"],
            "configuration_id": source.get("configuration_id", "C1_phase1_BF_BOF_plus_DRP_EAF"),
            "metric": row["metric"],
            "annual_value": row["annual_value"],
            "unit": row["unit"],
            "boundary": row["boundary"],
            "status": row["status"],
            "validation_status": (
                "pass"
                if row["metric"] == "imported_slab_to_HSM" or abs(float(row["annual_value"])) <= 1e-9
                else "fail"
            ),
            "caveat": row["caveat"],
        }
        for row in rows
    ]


def _wag_rows(source: dict[str, Any], run_directory: Path, context: dict[str, float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    carrier_rows = {row["carrier"]: row for row in _read_csv(run_directory / "wag_carrier_ledger.csv")}
    for carrier in ("BFG", "COG", "BOFG"):
        row = carrier_rows[carrier]
        generator_pj = _float(row, "generator_MWh_LHV_y") * 3.6 / 1_000_000.0
        target = float(context[carrier])
        residual = generator_pj - target
        rows.append({
            "source_run_id": source["run_id"],
            "scenario_label": source["label"],
            "carrier": carrier,
            "generation_PJ_LHV_y": round(_float(row, "generation_MWh_LHV_y") * 3.6 / 1_000_000.0, 6),
            "mandatory_and_process_PJ_LHV_y": round(_float(row, "process_or_self_use_MWh_LHV_y") * 3.6 / 1_000_000.0, 6),
            "HSM_PEFA_PJ_LHV_y": round(_float(row, "hsm_pefa_MWh_LHV_y") * 3.6 / 1_000_000.0, 6),
            "boiler_PJ_LHV_y": round(_float(row, "steam_boiler_MWh_LHV_y") * 3.6 / 1_000_000.0, 6),
            "generator_PJ_LHV_y": round(generator_pj, 6),
            "flare_PJ_LHV_y": round(_float(row, "flare_MWh_LHV_y") * 3.6 / 1_000_000.0, 6),
            "generator_context_anchor_PJ_y": target,
            "signed_generator_context_gap_PJ_y": round(residual, 6),
            "signed_generator_context_gap_share": round(residual / target, 9) if target else "",
            "status": "secondary_context_not_dispatch_target",
            "next_check": "trace generation, mandatory sinks and accepted controller precedence; do not force a carrier mix",
        })
    total_generator = sum(float(row["generator_PJ_LHV_y"]) for row in rows)
    total_flare = sum(float(row["flare_PJ_LHV_y"]) for row in rows)
    target = float(context["total_wag_plus_flare"])
    residual = total_generator + total_flare - target
    rows.append({
        "source_run_id": source["run_id"],
        "scenario_label": source["label"],
        "carrier": "total_WAG_plus_flare",
        "generation_PJ_LHV_y": "",
        "mandatory_and_process_PJ_LHV_y": "",
        "HSM_PEFA_PJ_LHV_y": "",
        "boiler_PJ_LHV_y": "",
        "generator_PJ_LHV_y": round(total_generator, 6),
        "flare_PJ_LHV_y": round(total_flare, 6),
        "generator_context_anchor_PJ_y": target,
        "signed_generator_context_gap_PJ_y": round(residual, 6),
        "signed_generator_context_gap_share": round(residual / target, 9),
        "status": "secondary_context_not_dispatch_target",
        "next_check": "use only as an annual reconciliation check; named generator NG remains outside this WAG-only total",
    })
    return rows


def _figure_91_rows(source: dict[str, Any], run_directory: Path, context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    utilities = {row["metric"]: row for row in _read_csv(run_directory / "utility_energy_co2_ledger.csv")}
    availability = {
        "total_CO2": ("WAG_explicit_combustion_CO2", "partial Mode-B fuel subtotal, not total site CO2"),
        "total_site_NG": ("named_NG_DRP_EAF_volume", "named process NG only, not total site NG"),
        "total_site_coal": ("", "no consolidated annual coal ledger in this run"),
        "WAG_electricity_generation": ("internal_WAG_generator_electricity_offset", "represented internal offset only; site meter boundary unresolved"),
    }
    rows: list[dict[str, Any]] = []
    for item in context:
        metric = item["metric_family"]
        model_metric, limitation = availability[metric]
        utility = utilities.get(model_metric) if model_metric else None
        rows.append({
            "source_run_id": source["run_id"],
            "scenario_label": source["label"],
            "metric_family": metric,
            "athanasiadis_model_minus_real_share": item["athanasiadis_model_minus_real_share"],
            "athanasiadis_direction": "model_above_real" if float(item["athanasiadis_model_minus_real_share"]) > 0 else "model_below_real",
            "our_available_metric": model_metric or "missing",
            "our_model_value": utility["model_value"] if utility else "",
            "our_unit": utility["unit"] if utility else "",
            "our_site_direction_assessable": "no",
            "status": "boundary_not_comparable",
            "why_not_comparable": limitation,
            "required_before_directional_use": item["comparison_requirement"],
        })
    return rows


def _coverage_rows(source: dict[str, Any], run_directory: Path) -> list[dict[str, Any]]:
    utilities = {row["metric"]: row for row in _read_csv(run_directory / "utility_energy_co2_ledger.csv")}
    carrier_rows = {row["carrier"]: row for row in _read_csv(run_directory / "wag_carrier_ledger.csv")}
    coal_proxy = carrier_rows["COG"]["source_activity_t_y"]
    return [
        {"source_run_id": source["run_id"], "family": "coal", "model_metric": "coking dry-coal activity proxy", "model_value": coal_proxy, "unit": "t/y", "coverage": "partial", "action": "add a consolidated coal/coke/PCI input ledger before annual coal comparison"},
        {"source_run_id": source["run_id"], "family": "coke", "model_metric": "source coke-chain reconciliation", "model_value": "", "unit": "t/y", "coverage": "not_exported_as_annual_ledger", "action": "export coke output and BF coke demand from the existing C1 coke-chain surface"},
        {"source_run_id": source["run_id"], "family": "NG", "model_metric": "named_NG_DRP_EAF_volume", "model_value": utilities["named_NG_DRP_EAF_volume"]["model_value"], "unit": utilities["named_NG_DRP_EAF_volume"]["unit"], "coverage": "partial", "action": "retain full-site NG as residual context; do not allocate it"},
        {"source_run_id": source["run_id"], "family": "CO2", "model_metric": "WAG_explicit_combustion_CO2", "model_value": utilities["WAG_explicit_combustion_CO2"]["model_value"], "unit": utilities["WAG_explicit_combustion_CO2"]["unit"], "coverage": "partial_Mode_B", "action": "do not compare to total Scope 1 until a coverage bridge exists"},
    ]


def _scenario_summary(source: dict[str, Any], run_directory: Path, anchors: list[dict[str, Any]]) -> dict[str, Any]:
    summary = json.loads((run_directory / "run_summary.json").read_text(encoding="utf-8"))
    checks = _read_csv(run_directory / "guardrail_checks.csv")
    comparable = [row for row in anchors if row["boundary_comparable"] == "yes_with_caveat"]
    return {
        "source_run_id": source["run_id"],
        "scenario_label": source["label"],
        "scenario_role": source["role"],
        "solver_status": summary["termination_condition"],
        "runtime_seconds": summary["runtime_seconds"],
        "annualised_final_product_mt_y": summary["annualised_final_product_mt_y"],
        "guardrail_fail_count": sum(1 for check in checks if check["status"] == "fail"),
        "comparable_anchor_rows": len(comparable),
        "within_7_5pct": sum(1 for row in comparable if row["proximity_status"] == "within_7_5pct_target"),
        "within_10pct": sum(1 for row in comparable if row["proximity_status"] == "within_10pct_review"),
        "outside_10pct": sum(1 for row in comparable if row["proximity_status"] == "outside_10pct"),
    }


def run_annual_multi_anchor_reconciliation(*, config_path: str | Path = DEFAULT_CONFIG, output_root: str | Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    config = _load_config(config_path)
    output_directory = Path(output_root).resolve() / str(config["run_id"])
    if output_directory.exists():
        raise ValueError(f"Run directory already exists: {output_directory}")
    output_directory.mkdir(parents=True)
    policy = config["anchor_proximity_policy"]
    annual_rows: list[dict[str, Any]] = []
    wag_rows: list[dict[str, Any]] = []
    figure_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    origin_burden_rows: list[dict[str, Any]] = []
    for source in config["source_runs"]:
        run_directory = Path(output_root).resolve() / source["run_id"]
        required = ("anchor_comparison.csv", "wag_carrier_ledger.csv", "utility_energy_co2_ledger.csv", "guardrail_checks.csv", "origin_material_ledger.csv", "run_summary.json")
        missing = [name for name in required if not (run_directory / name).exists()]
        if missing:
            raise FileNotFoundError(f"{source['run_id']} lacks required files: {', '.join(missing)}")
        source_anchors = _annual_anchor_rows(source, run_directory, policy)
        annual_rows.extend(source_anchors)
        wag_rows.extend(_wag_rows(source, run_directory, config["c1_generator_wag_context_pj_y"]))
        figure_rows.extend(_figure_91_rows(source, run_directory, config["athanasiadis_figure_91_directional_context"]))
        coverage_rows.extend(_coverage_rows(source, run_directory))
        origin_burden_rows.extend(_origin_burden_rows(source, run_directory))
        summaries.append(_scenario_summary(source, run_directory, source_anchors))
    family_rows = _anchor_family_summary(annual_rows)
    _write_csv(output_directory / "annual_anchor_reconciliation.csv", annual_rows)
    _write_csv(output_directory / "wag_carrier_reconciliation.csv", wag_rows)
    _write_csv(output_directory / "athanasiadis_figure_91_directional_context.csv", figure_rows)
    _write_csv(output_directory / "coal_coke_ng_co2_coverage.csv", coverage_rows)
    _write_csv(output_directory / "scenario_anchor_summary.csv", summaries)
    _write_csv(output_directory / "independent_anchor_family_summary.csv", family_rows)
    _write_csv(output_directory / "imported_slab_origin_burden_validation.csv", origin_burden_rows)
    independent_comparable_families = sum(
        1 for row in family_rows if row["independent_comparable_family"] == "yes"
    )
    independent_families_below_target = sum(1 for row in family_rows if row["family_below_7_5pct"] == "yes")
    stage_gate = {
        "stage": STAGE,
        "status": "pass_with_anchor_gaps",
        "output_policy": config["output_policy"],
        "run_class": config["run_class"],
        "lineage_role": config["lineage_role"],
        "source_runs": [source["run_id"] for source in config["source_runs"]],
        "anchor_closure": {
            "strict_abs_residual_share_threshold": policy["target_abs_residual_share"],
            "required_independent_comparable_families": 4,
            "independent_comparable_families": independent_comparable_families,
            "independent_comparable_families_below_threshold": independent_families_below_target,
            "anchor_stop_ready": independent_families_below_target >= 4,
            "production_target_counted": False,
            "imported_slab_origin_burden_validation": (
                "pass" if origin_burden_rows and all(row["validation_status"] == "pass" for row in origin_burden_rows) else "fail"
            ),
        },
        "next_gate": config.get("next_gate", "carrier_specific_WAG_sink_and_generator_reconciliation"),
        "go_no_go": {
            "annual_anchor_reporting": "GO",
            "annual_anchor_tuning": "NO_GO",
            "carrier_specific_WAG_reconciliation": "GO_DIAGNOSTIC_ONLY",
            "full_site_NG_or_CO2_claim": "NO_GO",
            "economics_and_DA": "NO_GO",
        },
    }
    _write_json(output_directory / "s4_4c5p_aw_stage_gate.json", stage_gate)
    _write_json(output_directory / "run_summary.json", {**stage_gate, "scenario_summaries": summaries})
    _write_json(output_directory / "registry_entry.json", {"run_id": config["run_id"], "run_class": config["run_class"], "lineage_role": config["lineage_role"], "output_policy": config["output_policy"], "git_eligible": False})
    (output_directory / "resolved_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    _write_json(output_directory / "input_manifest.json", {"config": config_path.relative_to(REPO_ROOT).as_posix(), "source_runs": [source["run_id"] for source in config["source_runs"]]})
    _write_json(
        output_directory / "code_version.json",
        {"git_revision": _git_revision(), "module": Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()},
    )
    (output_directory / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This stage reads existing annualised representative-week runs; it does not solve or change dispatch.\n"
        "- Figure 91 is directional Athanasiadis model-precedent context only. Its total-site metrics are not currently boundary-comparable to the partial C1 fuel/utility ledger.\n"
        "- Residual electricity and NG remain reported gaps, never model inputs or allocations.\n"
        "- Carrier generator context is a validation table, not a fuel-mix target or hourly constraint.\n",
        encoding="utf-8",
    )
    return {"run_directory": output_directory, "scenario_summaries": summaries, "stage_gate": stage_gate}
