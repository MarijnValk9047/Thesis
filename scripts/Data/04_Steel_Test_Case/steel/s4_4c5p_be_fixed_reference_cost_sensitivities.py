"""Run the bounded fixed-reference deterministic procurement-cost sensitivities."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    _config,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c_component_ontology import load_external_supply_costs


REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "configs"
    / "steel_fixed_reference_deterministic_cost.yaml"
)
CENTRAL_PARENT = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "runs"
    / "steel_s2_fixed_reference_deterministic_cost_v3_20260716"
)
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "runs"
    / "steel_s2_fixed_reference_cost_sensitivity_v1_20260716"
)
CONFIGURATIONS = (
    "C0_current_BF_BOF_reference",
    "C1_phase1_BF_BOF_plus_DRP_EAF",
)
PRICE_FAMILIES = {
    "electricity": ("grid_electricity_flat_nl",),
    "natural_gas": ("natural_gas_ttf_proxy",),
    "coal_pci": ("coking_coal_hcc_proxy", "pci_coal_proxy"),
    "ore_pellet": ("iron_ore_62fe_proxy", "imported_dr_pellets_proxy"),
    "scrap": ("purchased_scrap_proxy",),
    "imported_slab": ("imported_slab_proxy",),
}
ALL_PRICE_IDS = tuple(
    sorted({price_id for family in PRICE_FAMILIES.values() for price_id in family})
)


class FixedReferenceSensitivityError(ValueError):
    """Raised when a bounded sensitivity case or its comparison fails closed."""


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise FixedReferenceSensitivityError(f"Required output is empty: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_definitions(base_config: Mapping[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for family, price_ids in PRICE_FAMILIES.items():
        for level in ("low", "high"):
            cases.append(
                {
                    "case_id": f"{family}_{level}",
                    "family": family,
                    "level": level,
                    "changed_price_ids": list(price_ids),
                    "overrides": {
                        "price_scenario_overrides": {
                            price_id: f"development_{level}" for price_id in price_ids
                        }
                    },
                }
            )
    for level in ("low", "high"):
        cases.append(
            {
                "case_id": f"all_{level}",
                "family": "all_prices",
                "level": level,
                "changed_price_ids": list(ALL_PRICE_IDS),
                "overrides": {
                    "price_scenario_overrides": {
                        price_id: f"development_{level}" for price_id in ALL_PRICE_IDS
                    }
                },
            }
        )
    generator = dict(base_config["c1_generator_boundary"])
    generator["vn25_electricity_efficiency"] = 0.34
    cases.append(
        {
            "case_id": "vn25_efficiency_low_0_34",
            "family": "generator_efficiency",
            "level": "low",
            "changed_price_ids": [],
            "overrides": {
                "c1_generator_boundary": generator,
                "source_bounded_generator_efficiency_sensitivity": True,
            },
        }
    )
    return cases


def _price_lookup() -> dict[tuple[str, str], float]:
    return {
        (row["price_id"], row["scenario_id"]): float(row["value"])
        for row in load_external_supply_costs()
    }


def _run_metrics(run_directory: Path) -> dict[str, dict[str, Any]]:
    summary = _json(run_directory / "run_summary.json")
    if summary["status"] != "pass":
        raise FixedReferenceSensitivityError(f"Sensitivity run failed: {run_directory.name}")
    costs = {
        row["configuration_id"]: row
        for row in _csv(run_directory / "procurement_cost_summary.csv")
    }
    annual = {
        row["configuration_id"]: row
        for row in _csv(run_directory / "first_window_model_metrics.csv")
    }
    ledgers: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _csv(run_directory / "executed_procurement_cost_ledger.csv"):
        ledgers[row["configuration_id"]].append(row)
    hourly: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _csv(run_directory / "executed_hourly.csv"):
        hourly[row["configuration_id"]].append(row)
    checks = _csv(run_directory / "validation_checks.csv")
    guards_pass = bool(checks) and all(row["status"] == "pass" for row in checks)
    results: dict[str, dict[str, Any]] = {}
    for configuration in CONFIGURATIONS:
        ledger = ledgers[configuration]
        dispatch = hourly[configuration]
        price_costs = {
            price_id: sum(
                float(row["cost_eur"])
                for row in ledger
                if row["price_id"] == price_id
            )
            for price_id in ALL_PRICE_IDS
        }
        price_quantities = {
            price_id: sum(
                float(row["quantity"])
                for row in ledger
                if row["price_id"] == price_id
            )
            for price_id in ALL_PRICE_IDS
        }
        primary_objectives = [
            float(row["primary_cost_objective_eur"])
            for row in summary["model_size_by_replan"]
            if row["configuration_id"] == configuration
        ]
        results[configuration] = {
            "run_id": run_directory.name,
            "status": summary["status"],
            "physical_guardrails_pass": guards_pass,
            "executed_procurement_cost_eur": float(
                costs[configuration]["executed_procurement_cost_eur"]
            ),
            "annualised_procurement_cost_eur_y": float(
                costs[configuration]["annualised_procurement_cost_eur_y"]
            ),
            "cost_eur_per_t_final_product": float(
                costs[configuration]["procurement_cost_eur_per_t_final_product"]
            ),
            "mean_primary_168h_cost_objective_eur": sum(primary_objectives)
            / len(primary_objectives),
            "final_product_t": float(costs[configuration]["executed_final_product_t"]),
            "grid_import_mwh": sum(
                float(row["quantity"])
                for row in ledger
                if row["price_id"] == "grid_electricity_flat_nl"
            ),
            "named_ng_mwh": sum(
                float(row["quantity"])
                for row in ledger
                if row["price_id"] == "natural_gas_ttf_proxy"
            ),
            "purchased_scrap_t": sum(
                float(row["quantity"])
                for row in ledger
                if row["price_id"] == "purchased_scrap_proxy"
            ),
            "imported_slab_t": sum(
                float(row["quantity"])
                for row in ledger
                if row["price_id"] == "imported_slab_proxy"
            ),
            "wag_generation_mwh": sum(float(row["WAG_generated"]) for row in dispatch),
            "wag_use_mwh": sum(float(row["WAG_used"]) for row in dispatch),
            "wag_flare_mwh": sum(float(row["WAG_flared"]) for row in dispatch),
            "internal_generation_mwh": sum(
                float(row["generator_electricity_mwh"]) for row in dispatch
            ),
            "bof_liquid_steel_mt_y": float(annual[configuration]["bof_liquid_steel_mt_y"]),
            "eaf_liquid_steel_mt_y": float(annual[configuration]["eaf_liquid_steel_mt_y"]),
            "hsm_output_mt_y": float(annual[configuration]["hsm_hrc_output_mt_y"]),
            "dsp_output_mt_y": float(annual[configuration]["dsp_output_mt_y"]),
            "model_solve_runtime_seconds": sum(
                float(row.get("runtime_seconds") or 0.0)
                for row in summary["model_size_by_replan"]
                if row["configuration_id"] == configuration
            ),
            "coal_pci_quantity_t": price_quantities["coking_coal_hcc_proxy"]
            + price_quantities["pci_coal_proxy"],
            "ore_pellet_quantity_t": price_quantities["iron_ore_62fe_proxy"]
            + price_quantities["imported_dr_pellets_proxy"],
            **{
                f"cost_{price_id}_eur": value
                for price_id, value in price_costs.items()
            },
        }
    return results


def _price_index(
    *,
    level: str,
    changed_price_ids: list[str],
    central_ledger: list[dict[str, str]],
    prices: Mapping[tuple[str, str], float],
) -> float | None:
    if not changed_price_ids:
        return None
    weights: dict[str, float] = defaultdict(float)
    for row in central_ledger:
        if row["price_id"] in changed_price_ids:
            weights[row["price_id"]] += float(row["cost_eur"])
    denominator = sum(weights.values())
    if denominator <= 0.0:
        return 1.0
    return sum(
        weight
        * prices[(price_id, f"development_{level}")]
        / prices[(price_id, "development_central")]
        for price_id, weight in weights.items()
    ) / denominator


def run_bounded_fixed_reference_cost_sensitivities(
    *,
    config_path: str | Path = CONFIG_PATH,
    central_parent: str | Path = CENTRAL_PARENT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    reaggregate: bool = False,
) -> dict[str, Any]:
    config_file = Path(config_path).resolve()
    central_dir = Path(central_parent).resolve()
    output = Path(output_root).resolve()
    if (output / "run_summary.json").exists() and not reaggregate:
        raise FixedReferenceSensitivityError(f"Completed sensitivity root exists: {output}")
    output.mkdir(parents=True, exist_ok=True)
    base_config = _config(config_file)
    cases = _case_definitions(base_config)
    central_metrics = _run_metrics(central_dir)
    prices = _price_lookup()
    central_ledger_by_configuration: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _csv(central_dir / "executed_procurement_cost_ledger.csv"):
        central_ledger_by_configuration[row["configuration_id"]].append(row)
    completed: dict[str, Path] = {}
    for case in cases:
        case_dir = output / case["case_id"]
        if (case_dir / "run_summary.json").exists():
            if _json(case_dir / "run_summary.json").get("status") != "pass":
                raise FixedReferenceSensitivityError(
                    f"Existing sensitivity case is not pass: {case['case_id']}"
                )
        elif case_dir.exists() and any(case_dir.iterdir()):
            raise FixedReferenceSensitivityError(
                f"Partial sensitivity case requires review: {case_dir}"
            )
        else:
            if case_dir.exists():
                case_dir.rmdir()
            run_closed_loop_feasibility_anchor_reconciliation(
                config_path=config_file,
                output_root=output,
                scenario_overrides={
                    "run_id": case["case_id"],
                    "lineage_role": "bounded_fixed_reference_cost_sensitivity",
                    **case["overrides"],
                },
            )
        completed[case["case_id"]] = case_dir
    case_metrics = {
        case_id: _run_metrics(path) for case_id, path in completed.items()
    }
    comparison_rows: list[dict[str, Any]] = []
    reporting_cases: list[dict[str, Any]] = []
    for family, price_ids in PRICE_FAMILIES.items():
        reporting_cases.extend(
            [
                next(case for case in cases if case["case_id"] == f"{family}_low"),
                {
                    "case_id": f"{family}_central",
                    "family": family,
                    "level": "central",
                    "changed_price_ids": list(price_ids),
                    "central_alias": True,
                },
                next(case for case in cases if case["case_id"] == f"{family}_high"),
            ]
        )
    reporting_cases.extend(
        case for case in cases if case["family"] in {"all_prices", "generator_efficiency"}
    )
    for case in reporting_cases:
        metrics = (
            central_metrics
            if case.get("central_alias")
            else case_metrics[case["case_id"]]
        )
        solved_run_id = central_dir.name if case.get("central_alias") else case["case_id"]
        for configuration in CONFIGURATIONS:
            row = metrics[configuration]
            index = (
                1.0
                if case["level"] == "central"
                else _price_index(
                    level=case["level"],
                    changed_price_ids=case["changed_price_ids"],
                    central_ledger=central_ledger_by_configuration[configuration],
                    prices=prices,
                )
            )
            comparison_rows.append(
                {
                    "reporting_case_id": case["case_id"],
                    "solved_run_id": solved_run_id,
                    "sensitivity_family": case["family"],
                    "level": case["level"],
                    "configuration_id": configuration,
                    "price_index_vs_central": "" if index is None else round(index, 9),
                    **{key: round(value, 9) if isinstance(value, float) else value for key, value in row.items() if key not in {"run_id", "status"}},
                }
            )
    keyed = {
        (row["sensitivity_family"], row["level"], row["configuration_id"]): row
        for row in comparison_rows
    }
    elasticity_rows: list[dict[str, Any]] = []
    quantity_metric = {
        "electricity": "grid_import_mwh",
        "natural_gas": "named_ng_mwh",
        "coal_pci": "coal_pci_quantity_t",
        "ore_pellet": "ore_pellet_quantity_t",
        "scrap": "purchased_scrap_t",
        "imported_slab": "imported_slab_t",
    }
    for family in PRICE_FAMILIES:
        for configuration in CONFIGURATIONS:
            central = keyed[(family, "central", configuration)]
            for level in ("low", "high"):
                case = keyed[(family, level, configuration)]
                price_change = float(case["price_index_vs_central"]) - 1.0
                for metric in ("executed_procurement_cost_eur", quantity_metric[family]):
                    central_value = float(central[metric])
                    quantity_change = (
                        float(case[metric]) / central_value - 1.0
                        if central_value
                        else 0.0
                    )
                    elasticity_rows.append(
                        {
                            "sensitivity_family": family,
                            "level": level,
                            "configuration_id": configuration,
                            "metric": metric,
                            "price_change_fraction": round(price_change, 9),
                            "metric_change_fraction": round(quantity_change, 9),
                            "elasticity": (
                                round(quantity_change / price_change, 9)
                                if price_change
                                else ""
                            ),
                            "interpretation": (
                                "fixed_route_non_response_is_expected_when_quantity_is_scenario_bound"
                                if abs(quantity_change) <= 1e-8
                                else "dispatch_or_cost_response_observed"
                            ),
                        }
                    )
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "check_id": "all_sensitivity_runs_pass_physical_guardrails",
            "status": "pass"
            if all(
                row["physical_guardrails_pass"] is True for row in comparison_rows
            )
            else "fail",
            "evidence": f"solved_runs={1 + len(cases)} including reused central",
        }
    )
    response_specs = (
        ("electricity", "grid_import_mwh", "high_not_greater"),
        ("natural_gas", "named_ng_mwh", "high_not_greater"),
        ("imported_slab", "imported_slab_t", "high_not_greater"),
        ("scrap", "purchased_scrap_t", "high_not_greater"),
    )
    for family, metric, _rule in response_specs:
        for configuration in CONFIGURATIONS:
            central = keyed[(family, "central", configuration)]
            high = keyed[(family, "high", configuration)]
            passed = float(high[metric]) <= float(central[metric]) + 1e-6
            checks.append(
                {
                    "check_id": f"{family}_{configuration}_high_price_not_increase_{metric}",
                    "status": "pass" if passed else "fail",
                    "evidence": f"central={central[metric]};high={high[metric]}",
                }
            )
    for family, price_ids in PRICE_FAMILIES.items():
        for configuration in CONFIGURATIONS:
            central = keyed[(family, "central", configuration)]
            low = keyed[(family, "low", configuration)]
            high = keyed[(family, "high", configuration)]
            central_basket_cost = sum(
                float(central[f"cost_{price_id}_eur"]) for price_id in price_ids
            )
            low_basket_cost = sum(
                float(low[f"cost_{price_id}_eur"]) for price_id in price_ids
            )
            high_basket_cost = sum(
                float(high[f"cost_{price_id}_eur"]) for price_id in price_ids
            )
            no_active_flow = central_basket_cost <= 1e-9
            checks.append(
                {
                    "check_id": f"{family}_{configuration}_basket_cost_tracks_price",
                    "status": "pass"
                    if no_active_flow
                    or (
                        low_basket_cost <= central_basket_cost + 1e-4
                        and high_basket_cost >= central_basket_cost - 1e-4
                    )
                    else "fail",
                    "evidence": f"low={low_basket_cost};central={central_basket_cost};high={high_basket_cost}",
                }
            )
            central_objective = float(
                central["mean_primary_168h_cost_objective_eur"]
            )
            low_objective = float(low["mean_primary_168h_cost_objective_eur"])
            high_objective = float(high["mean_primary_168h_cost_objective_eur"])
            checks.append(
                {
                    "check_id": f"{family}_{configuration}_primary_objective_monotonic",
                    "status": "pass"
                    if low_objective <= central_objective + 1e-4
                    and high_objective >= central_objective - 1e-4
                    else "fail",
                    "evidence": f"low={low_objective};central={central_objective};high={high_objective}",
                }
            )
    generator = next(
        row
        for row in comparison_rows
        if row["sensitivity_family"] == "generator_efficiency"
        and row["configuration_id"] == "C1_phase1_BF_BOF_plus_DRP_EAF"
    )
    central_c1 = central_metrics["C1_phase1_BF_BOF_plus_DRP_EAF"]
    checks.append(
        {
            "check_id": "lower_generator_efficiency_has_expected_external_energy_response",
            "status": "pass"
            if float(generator["grid_import_mwh"]) >= central_c1["grid_import_mwh"] - 1e-6
            else "fail",
            "evidence": f"central_grid={central_c1['grid_import_mwh']};low_efficiency_grid={generator['grid_import_mwh']}",
        }
    )
    checks.append(
        {
            "check_id": "fixed_route_quantities_preserved",
            "status": "pass"
            if all(
                abs(float(row[metric]) - central_metrics[row["configuration_id"]][metric])
                <= 0.0101 * max(1.0, abs(central_metrics[row["configuration_id"]][metric]))
                for row in comparison_rows
                for metric in (
                    "bof_liquid_steel_mt_y",
                    "eaf_liquid_steel_mt_y",
                    "hsm_output_mt_y",
                    "dsp_output_mt_y",
                )
            )
            else "fail",
            "evidence": "cross-case difference stays within the two-sided governed 0.5 percent bands",
        }
    )
    status = "pass" if all(row["status"] == "pass" for row in checks) else "fail"
    _write_csv(output / "sensitivity_comparison.csv", comparison_rows)
    _write_csv(output / "sensitivity_elasticities.csv", elasticity_rows)
    _write_csv(output / "sensitivity_validation.csv", checks)
    manifest = {
        "run_id": output.name,
        "run_class": "bounded_fixed_reference_cost_sensitivity",
        "lineage_role": "phase6_fixed_reference_price_and_generator_response",
        "output_policy": "minimal",
        "central_parent": central_dir.name,
        "central_parent_summary_sha256": _sha256(central_dir / "run_summary.json"),
        "config_path": str(config_file.relative_to(REPO_ROOT)).replace("\\", "/"),
        "config_sha256": _sha256(config_file),
        "solved_case_ids": [case["case_id"] for case in cases],
    }
    _write_json(output / "input_manifest.json", manifest)
    (output / "resolved_config.yaml").write_text(
        json.dumps(
            {
                "central_parent": central_dir.name,
                "fixed_reference_scenario_id": base_config[
                    "fixed_reference_scenario_id"
                ],
                "case_definitions": cases,
                "output_policy": "minimal",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        output / "code_version.json",
        {
            "git_commit": _json(central_dir / "code_version.json").get("git_commit"),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "module_sha256": _sha256(Path(__file__)),
        },
    )
    summary = {
        "run_id": output.name,
        "status": status,
        "central_parent": central_dir.name,
        "distinct_solved_runs_including_central": 1 + len(cases),
        "new_sensitivity_runs": len(cases),
        "reporting_case_configuration_rows": len(comparison_rows),
        "validation_checks_passed": sum(row["status"] == "pass" for row in checks),
        "validation_checks_total": len(checks),
        "next_permitted_phase": "flat_price_series_interface_validation",
    }
    _write_json(output / "run_summary.json", summary)
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": output.name,
            "run_class": "bounded_fixed_reference_cost_sensitivity",
            "lineage_role": "phase6_fixed_reference_price_and_generator_response",
            "output_policy": "minimal",
            "status": status,
        },
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- This is a bounded one-family-at-a-time set, not a combinatorial sweep.\n"
        "- Central quantities are reused from the accepted v3 run.\n"
        "- Material non-response is expected where fixed cumulative route bands bind.\n"
        "- Prices are development proxies, not validation anchors or Tata contracts.\n"
        "- No revenue, ETS, DA, stochasticity, settlement or direct WAG price is active.\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        f"# {output.name}\n\n"
        f"- Status: {status}\n"
        "- Cases: electricity, NG, coal/PCI, ore/pellet, scrap, slab low/high; all-low/all-high; VN25 efficiency 0.34.\n"
        "- Central case: accepted v3 fixed-reference cost run, reused without rerunning.\n",
        encoding="utf-8",
    )
    return {"run_directory": output, "summary": summary}
