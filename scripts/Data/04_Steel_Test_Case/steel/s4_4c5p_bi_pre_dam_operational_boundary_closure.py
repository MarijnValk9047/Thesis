"""Same-run pre-DAM operational-boundary closure for the steel S2 lineage."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c_component_ontology import (
    load_future_cost_boundary_contract,
    load_procurement_boundary_gap_register,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
RUN_ROOT = REPO_ROOT / "data" / "03_Optimisation" / "runs"
CONFIG_PATH = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "configs"
    / "steel_pre_dam_operational_boundary_closure.yaml"
)
DEFAULT_OUTPUT = (
    RUN_ROOT / "steel_s2_pre_dam_operational_boundary_closure_v1_20260720"
)
BEFORE_RUN = RUN_ROOT / "steel_s2_fixed_reference_deterministic_cost_v3_20260716"
GENERATOR_SOURCE_CARD = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "source_cards"
    / "IJ01_VN25_GENERATORS_Parameters.md"
)
C5P_O_LEDGER = (
    REPO_ROOT
    / "data"
    / "03_Optimisation"
    / "inputs"
    / "assets"
    / "steel"
    / "S4"
    / "s4_4c5p_o_wag_controller_contract_hardening"
    / "wag_contract_interface_ledger.csv"
)
CONFIGURATIONS = (
    "C0_current_BF_BOF_reference",
    "C1_phase1_BF_BOF_plus_DRP_EAF",
)
HOURS_PER_YEAR = 8760.0
EXECUTED_HOURS = 168.0
PJ_PER_MWH = 3.6e-6
PRODUCTION_TARGET_T_Y = 6_750_000.0
PERMITTED_DECISIONS = {
    "ready_for_governed_DAM_data_contract",
    "DAM_data_contract_only_operational_gaps_remain",
    "needs_more_S2_boundary_evidence",
}


class OperationalBoundaryClosureError(ValueError):
    """Raised when a required same-run closure artifact does not pass."""


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise OperationalBoundaryClosureError(f"Required table is empty: {path.name}")
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: Any) -> float:
    if value in {None, ""}:
        return 0.0
    return float(value)


def _annual_pj(rows: Iterable[Mapping[str, Any]], field: str) -> float:
    return sum(_number(row.get(field)) for row in rows) * HOURS_PER_YEAR / EXECUTED_HOURS * PJ_PER_MWH


def _annual_mwh(rows: Iterable[Mapping[str, Any]], field: str) -> float:
    return sum(_number(row.get(field)) for row in rows) * HOURS_PER_YEAR / EXECUTED_HOURS


def _annual_named_ng_pj(rows: Iterable[Mapping[str, Any]]) -> float:
    fields = (
        "DRP_named_NG_mwh",
        "EAF_named_NG_mwh",
        "natural_gas_boiler_mwh",
        "NG_to_HSM_mwh",
        "NG_to_PEFA_malerij_mwh",
        "NG_to_PEFA_branderij_mwh",
        "generator_named_ng_mwh",
    )
    materialised = list(rows)
    return sum(_annual_pj(materialised, field) for field in fields)


def _case_overrides(base: Mapping[str, Any]) -> list[dict[str, Any]]:
    generator_low = dict(base["c1_generator_boundary"])
    generator_low["vn25_electricity_efficiency"] = 0.34
    return [
        {
            "case_id": "corrected_central",
            "role": "accepted_central_candidate",
            "overrides": {},
        },
        {
            "case_id": "electricity_high",
            "role": "focused_price_diagnostic",
            "overrides": {
                "price_scenario_overrides": {
                    "grid_electricity_flat_nl": "development_high"
                }
            },
        },
        {
            "case_id": "vn25_efficiency_low_0_34",
            "role": "source_bounded_efficiency_diagnostic",
            "overrides": {
                "c1_generator_boundary": generator_low,
                "source_bounded_generator_efficiency_sensitivity": True,
            },
        },
    ]


def _run_cases(temp_root: Path) -> dict[str, Path]:
    base = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    paths: dict[str, Path] = {}
    for case in _case_overrides(base):
        case_id = str(case["case_id"])
        run_id = f"{DEFAULT_OUTPUT.name}__{case_id}"
        result = run_closed_loop_feasibility_anchor_reconciliation(
            config_path=CONFIG_PATH,
            output_root=temp_root,
            scenario_overrides={
                "run_id": run_id,
                "lineage_role": f"{base['lineage_role']}__{case['role']}",
                **dict(case["overrides"]),
            },
        )
        if result["summary"]["status"] != "pass":
            raise OperationalBoundaryClosureError(
                f"Focused run did not pass: {case_id}"
            )
        paths[case_id] = Path(result["run_directory"])
    return paths


def build_wag_source_to_sink_ledger(
    hourly_rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build a carrier-preserving same-run ledger without residual flooring."""

    source_columns = {
        "BFG": "BFG_generated_mwh",
        "COG": "COG_generated_mwh",
        "BOFG": "BOFG_generated_mwh",
    }
    common_sinks = {
        "BFG": (
            ("BF_hot_stove", "BF6_BF7", "BFG_to_BF_hot_stove_mwh"),
            ("coking", "KGF1", "BFG_to_KGF1_mwh"),
            ("downstream", "HSM", "BFG_to_HSM_mwh"),
            ("steam", "boiler", "BFG_to_boiler_mwh"),
        ),
        "COG": (
            ("coking", "KGF1", "COG_to_KGF1_mwh"),
            ("coking", "KGF2", "COG_to_KGF2_mwh"),
            ("sinter", "sinter", "COG_to_sinter_mwh"),
            ("downstream", "HSM", "COG_to_HSM_mwh"),
            ("pellet_preparation", "PEFA_branderij", "COG_to_PEFA_branderij_mwh"),
            ("steam", "boiler", "COG_to_boiler_mwh"),
        ),
        "BOFG": (
            ("downstream", "HSM", "BOFG_to_HSM_mwh"),
            ("pellet_preparation", "PEFA_malerij", "BOFG_to_PEFA_malerij_mwh"),
            ("steam", "boiler", "BOFG_to_boiler_mwh"),
        ),
    }
    rows: list[dict[str, Any]] = []
    for configuration in CONFIGURATIONS:
        dispatch = [
            row for row in hourly_rows if row.get("configuration_id") == configuration
        ]
        if len(dispatch) != int(EXECUTED_HOURS):
            raise OperationalBoundaryClosureError(
                f"Expected 168 executed hourly rows for {configuration}."
            )
        for carrier, source_column in source_columns.items():
            flows: list[tuple[str, str, str, str]] = [
                ("generation", "source", carrier, source_column),
                *(
                    (stage, "sink", component, column)
                    for stage, component, column in common_sinks[carrier]
                ),
            ]
            if configuration.startswith("C1_"):
                flows.extend(
                    (
                        ("electricity_generation", "sink", "VN25", f"{carrier}_to_VN25_mwh"),
                        ("chp_backup", "sink", "IJ01", f"{carrier}_to_IJ01_mwh"),
                    )
                )
            else:
                flows.append(
                    (
                        "aggregate_generator_interface",
                        "sink",
                        "C0_Vattenfall_aggregate",
                        f"{carrier}_to_vattenfall_mwh",
                    )
                )
            flows.extend(
                (
                    ("flare", "flare", f"{carrier}_flare", f"{carrier}_flared_mwh"),
                    (
                        "balance",
                        "accounting_residual",
                        f"{carrier}_signed_residual",
                        f"{carrier}_balance_residual_mwh",
                    ),
                )
            )
            for sink_stage, role, component, column in flows:
                executed = sum(_number(row.get(column)) for row in dispatch)
                rows.append(
                    {
                        "configuration_id": configuration,
                        "carrier": carrier,
                        "source_stage": "BF" if carrier == "BFG" else "KGF" if carrier == "COG" else "BOF",
                        "sink_stage": sink_stage,
                        "sink_component": component,
                        "flow_role": role,
                        "source_column": column,
                        "executed_mwh_lhv": round(executed, 9),
                        "annualised_pj_lhv_y": round(
                            executed * HOURS_PER_YEAR / EXECUTED_HOURS * PJ_PER_MWH,
                            12,
                        ),
                        "controller_surface": "active_unified_builder_same_run",
                        "physical_use_status": (
                            "reporting_only_signed"
                            if role == "accounting_residual"
                            else "physical_carrier_specific"
                        ),
                        "allocation_evidence": (
                            "C5p_o accepted carrier interface; C0 aggregate generator only"
                            if configuration.startswith("C0_")
                            else "C5p_o accepted carrier interface; C1 governed unit boundary"
                        ),
                    }
                )
    return rows


def _ledger_value(
    ledger: Iterable[Mapping[str, Any]],
    *,
    configuration: str,
    carrier: str | None = None,
    sink_components: set[str] | None = None,
    roles: set[str] | None = None,
) -> float:
    return sum(
        _number(row.get("annualised_pj_lhv_y"))
        for row in ledger
        if row.get("configuration_id") == configuration
        and (carrier is None or row.get("carrier") == carrier)
        and (sink_components is None or row.get("sink_component") in sink_components)
        and (roles is None or row.get("flow_role") in roles)
    )


def build_wag_anchor_reconciliation(
    ledger: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    configuration = "C1_phase1_BF_BOF_plus_DRP_EAF"
    generator_units = {"VN25", "IJ01"}
    definitions = (
        (
            "c1_generator_BFG_9_1",
            "BFG",
            9.1,
            _ledger_value(
                ledger,
                configuration=configuration,
                carrier="BFG",
                sink_components=generator_units,
            ),
        ),
        (
            "c1_generator_COG_0_1",
            "COG",
            0.1,
            _ledger_value(
                ledger,
                configuration=configuration,
                carrier="COG",
                sink_components=generator_units,
            ),
        ),
        (
            "c1_generator_BOFG_1_3",
            "BOFG",
            1.3,
            _ledger_value(
                ledger,
                configuration=configuration,
                carrier="BOFG",
                sink_components=generator_units,
            ),
        ),
        (
            "c1_generator_flare_0_1",
            "BFG_COG_BOFG",
            0.1,
            _ledger_value(
                ledger,
                configuration=configuration,
                roles={"flare"},
            ),
        ),
        (
            "c1_generator_wag_with_flare_10_6",
            "BFG_COG_BOFG",
            10.6,
            _ledger_value(
                ledger,
                configuration=configuration,
                sink_components=generator_units,
            )
            + _ledger_value(
                ledger,
                configuration=configuration,
                roles={"flare"},
            ),
        ),
    )
    rows: list[dict[str, Any]] = []
    for anchor_id, carrier, anchor, model in definitions:
        residual = model - anchor
        rows.append(
            {
                "anchor_id": anchor_id,
                "configuration_id": configuration,
                "carrier": carrier,
                "model_annualised_pj_lhv_y": round(model, 12),
                "anchor_pj_lhv_y": anchor,
                "signed_residual_pj_lhv_y": round(residual, 12),
                "absolute_residual_pct": round(abs(residual) / anchor * 100.0, 9),
                "comparability_status": "directly_comparable_annual_scenario_context",
                "classification": (
                    "within_7_5pct"
                    if abs(residual) / anchor <= 0.075
                    else "scenario_mismatch"
                ),
                "forced_dispatch_target_active": "no",
                "diagnosis": (
                    "Same-run carrier generation is first allocated to governed process, self-use and boiler sinks; residual eligible WAG reaches VN25/IJ01. The MER annual allocation represents a different operating scenario and is not a mass-balance requirement."
                    if anchor_id == "c1_generator_wag_with_flare_10_6"
                    else "Carrier-specific MER allocation is validation context and is not forced."
                ),
                "evidence": "wag_source_to_sink_ledger.csv;IJ01_VN25_GENERATORS_Parameters.md Table 5.5",
            }
        )
    return rows


def build_generator_operating_contract_audit(
    case_directories: Mapping[str, Path],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_id, directory in case_directories.items():
        dispatch = [
            row
            for row in _csv(directory / "executed_hourly.csv")
            if row.get("configuration_id")
            == "C1_phase1_BF_BOF_plus_DRP_EAF"
        ]
        config = yaml.safe_load((directory / "resolved_config.yaml").read_text(encoding="utf-8"))
        generator = config["c1_generator_boundary"]
        for asset in ("VN25", "IJ01"):
            prefix = asset
            rows.append(
                {
                    "case_id": case_id,
                    "configuration_id": "C1_phase1_BF_BOF_plus_DRP_EAF",
                    "asset": asset,
                    "source_backed_role": (
                        "primary_residual_gas_generator"
                        if asset == "VN25"
                        else "CHP_backup_or_reserve"
                    ),
                    "steam_coupling": (
                        "not_applicable_to_VN25"
                        if asset == "VN25"
                        else "CHP_confirmed_but_electricity_steam_split_deferred"
                    ),
                    "eligible_fuels": (
                        "BFG;COG;BOFG;NG"
                        if asset == "VN25"
                        else "BFG;COG;BOFG"
                    ),
                    "electric_efficiency": (
                        generator["vn25_electricity_efficiency"]
                        if asset == "VN25"
                        else "deferred"
                    ),
                    "fuel_input_capacity": (
                        "600000 Nm3/h development cap"
                        if asset == "VN25"
                        else "300000 Nm3/h development cap"
                    ),
                    "electric_output_capacity": (
                        "350 MW development precedent"
                        if asset == "VN25"
                        else "not_found"
                    ),
                    "minimum_load": "not_found_not_active",
                    "must_run_or_service_obligation": "not_found_not_active",
                    "availability_contract": "enabled_base_without_forced_hours",
                    "annual_anchor_role": "validation_only_not_hourly_or_annual_constraint",
                    "annual_wag_fuel_pj_lhv_y": round(
                        _annual_pj(dispatch, f"{prefix}_WAG_fuel_mwh"), 12
                    ),
                    "annual_named_ng_pj_lhv_y": round(
                        _annual_pj(dispatch, f"{prefix}_NG_fuel_mwh"), 12
                    ),
                    "annual_total_fuel_pj_lhv_y": round(
                        _annual_pj(dispatch, f"{prefix}_total_fuel_mwh"), 12
                    ),
                    "annual_electricity_twh_y": round(
                        _annual_mwh(dispatch, f"{prefix}_electricity_mwh")
                        / 1_000_000.0,
                        12,
                    ),
                    "annual_grid_import_twh_y": round(
                        _annual_mwh(dispatch, "net_grid_import_mwh")
                        / 1_000_000.0,
                        12,
                    ),
                    "annual_gross_electricity_twh_y": round(
                        _annual_mwh(dispatch, "gross_electricity_mwh")
                        / 1_000_000.0,
                        12,
                    ),
                    "anchor_forced": "no",
                    "contract_status": "pass_with_explicit_evidence_gap",
                    "exact_missing_evidence": (
                        "unit-specific minimum stable load, heat-rate curve, ramp/start rules and outage availability"
                        if asset == "VN25"
                        else "quantitative electricity/steam split, electric efficiency/capacity and any CHP heat-service obligation"
                    ),
                    "source_locator": "IJ01_VN25_GENERATORS_Parameters.md lines 20-27, 182-223, 251-270",
                }
            )
    return rows


def build_procurement_boundary_comparison(
    central_directory: Path,
) -> list[dict[str, Any]]:
    contract = [
        row
        for row in load_future_cost_boundary_contract()
        if str(row.get("objective_enabled", "")).lower() == "true"
    ]
    contract_by_flow = {row["flow_id"]: row for row in contract}
    ledger = _csv(central_directory / "executed_procurement_cost_ledger.csv")
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in ledger:
        key = (item["configuration_id"], item["flow_id"])
        row = grouped.setdefault(
            key,
            {
                "row_type": "executed_external_flow",
                "configuration_id": item["configuration_id"],
                "flow_or_gap_id": item["flow_id"],
                "procurement_family": item["price_id"],
                "quantity": 0.0,
                "quantity_unit": item["quantity_unit"],
                "represented_cost_eur": 0.0,
                "active_physical_flow_status": "active_solved_or_named_accounting_flow",
                "cost_coverage_status": "covered",
                "external_internal_status": "external",
                "priced_once_status": "pending",
                "source_evidence_status": "",
                "source_locator": "",
                "blocks_direct_C0_C1_total_cost_comparison": "no",
                "conclusion": "External represented flow is priced once; its internal products are not repurchased.",
            },
        )
        row["quantity"] += _number(item["quantity"])
        row["represented_cost_eur"] += _number(item["cost_eur"])
    seen_double_count_groups = [
        row.get("double_count_group", "") for row in contract
    ]
    unique_groups = len(seen_double_count_groups) == len(set(seen_double_count_groups))
    for (configuration, flow_id), row in grouped.items():
        contract_row = contract_by_flow.get(flow_id)
        if contract_row is None:
            row["priced_once_status"] = "fail_missing_contract"
        else:
            row["priced_once_status"] = (
                "pass" if unique_groups else "fail_duplicate_double_count_group"
            )
            row["source_evidence_status"] = contract_row.get(
                "source_status", ""
            )
            row["source_locator"] = contract_row.get("source_locator", "")
        row["quantity"] = round(_number(row["quantity"]), 9)
        row["represented_cost_eur"] = round(
            _number(row["represented_cost_eur"]), 6
        )
    rows = list(grouped.values())
    for gap in load_procurement_boundary_gap_register():
        if gap["gap_id"] not in {
            "C0_BF_PELLETS",
            "C1_BF_PELLETS",
            "C1_DRP_PELLETS",
            "C0_BOF_SCRAP",
            "C1_BOF_SCRAP",
            "C1_EAF_SCRAP",
            "C1_IMPORTED_SLAB",
            "C1_HBI",
            "COST_BENCHMARK",
        }:
            continue
        rows.append(
            {
                "row_type": "boundary_gap_or_policy",
                "configuration_id": gap["configuration"],
                "flow_or_gap_id": gap["gap_id"],
                "procurement_family": gap["procurement_family"],
                "quantity": "not_separately_quantifiable" if "BF_PELLETS" in gap["gap_id"] else "not_applicable",
                "quantity_unit": "",
                "represented_cost_eur": "not_separately_quantifiable" if "BF_PELLETS" in gap["gap_id"] else "not_applicable",
                "active_physical_flow_status": gap["active_physical_flow_status"],
                "cost_coverage_status": gap["cost_coverage_status"],
                "external_internal_status": "explicit_boundary_policy",
                "priced_once_status": (
                    "not_applicable_inactive"
                    if gap["gap_id"] == "C1_HBI"
                    else "pass_or_explicit_unrepresented_gap"
                ),
                "source_evidence_status": gap["source_evidence_status"],
                "source_locator": gap["source_locator"],
                "blocks_direct_C0_C1_total_cost_comparison": (
                    "yes"
                    if gap["gap_id"]
                    in {"C0_BF_PELLETS", "C1_BF_PELLETS", "COST_BENCHMARK"}
                    else "no"
                ),
                "conclusion": gap["resolution_or_caveat"],
            }
        )
    return rows


def build_rolling_production_state_audit(
    central_directory: Path,
) -> list[dict[str, Any]]:
    rows = _csv(central_directory / "rolling_production_progress_state.csv")
    output: list[dict[str, Any]] = []
    for row in rows:
        executed = _number(row["cumulative_executed_after_t"])
        replan = int(row["replan_index"])
        central = (replan + 1) * PRODUCTION_TARGET_T_Y / 365.0
        output.append(
            {
                **row,
                "cumulative_central_target_t": round(central, 9),
                "cumulative_target_residual_t": round(executed - central, 9),
                "executed_annual_equivalent_t_y": round(
                    executed * HOURS_PER_YEAR / ((replan + 1) * 24.0), 6
                ),
                "active_binding_contracts": "hard_cumulative_quota;fixed_reference_cumulative_route_bands;source_capacities;continuous_availability;inventory_handoff",
                "profile_status": "hourly_throughput_endogenous_no_fixed_profile",
            }
        )
    return output


def build_solver_run_metrics(
    case_directories: Mapping[str, Path],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_id, directory in case_directories.items():
        summary = _json(directory / "run_summary.json")
        checks = _csv(directory / "validation_checks.csv")
        for metric in summary["model_size_by_replan"]:
            rows.append(
                {
                    "case_id": case_id,
                    **metric,
                    "run_status": summary["status"],
                    "all_physical_and_cost_checks_pass": str(
                        all(row["status"] == "pass" for row in checks)
                    ).lower(),
                    "quota_check": next(
                        row["status"]
                        for row in checks
                        if row["check_id"] == "rolling_production_progress_state"
                    ),
                    "material_balance_check": next(
                        row["status"]
                        for row in checks
                        if row["check_id"] == "material_conservation"
                    ),
                    "origin_check": next(
                        row["status"]
                        for row in checks
                        if row["check_id"] == "origin_conservation"
                    ),
                    "wag_check": next(
                        row["status"]
                        for row in checks
                        if row["check_id"] == "carrier_specific_wag_balance"
                    ),
                    "cost_identity_check": next(
                        row["status"]
                        for row in checks
                        if row["check_id"]
                        == "procurement_cost_component_and_route_identities"
                    ),
                }
            )
    return rows


def build_before_after_comparison(
    central_directory: Path,
    wag_anchors: list[Mapping[str, Any]],
    generator_audit: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    before_summary = _json(BEFORE_RUN / "run_summary.json")
    after_summary = _json(central_directory / "run_summary.json")
    before_hourly = _csv(BEFORE_RUN / "executed_hourly.csv")
    after_hourly = _csv(central_directory / "executed_hourly.csv")
    before_cost = {
        row["configuration_id"]: row
        for row in _csv(BEFORE_RUN / "procurement_cost_summary.csv")
    }
    after_cost = {
        row["configuration_id"]: row
        for row in _csv(central_directory / "procurement_cost_summary.csv")
    }
    wag_total_after = next(
        _number(row["model_annualised_pj_lhv_y"])
        for row in wag_anchors
        if row["anchor_id"] == "c1_generator_wag_with_flare_10_6"
    )
    before_anchors = {
        row["anchor_id"]: row
        for row in _csv(BEFORE_RUN / "annual_anchor_reconciliation.csv")
        if row["anchor_id"] in {
            "c1_generator_wag_with_flare_10_6",
            "c1_vn25_ng_4_1",
        }
    }
    central_vn25 = next(
        row
        for row in generator_audit
        if row["case_id"] == "corrected_central" and row["asset"] == "VN25"
    )
    rows: list[dict[str, Any]] = []

    def add(
        metric: str,
        configuration: str,
        unit: str,
        before: float,
        after: float,
        interpretation: str,
    ) -> None:
        rows.append(
            {
                "metric": metric,
                "configuration_id": configuration,
                "unit": unit,
                "before_value": round(before, 12),
                "after_value": round(after, 12),
                "signed_change": round(after - before, 12),
                "absolute_change": round(abs(after - before), 12),
                "interpretation": interpretation,
            }
        )

    for configuration in CONFIGURATIONS:
        before_production = (
            _number(before_summary["cumulative_execution_t"][configuration])
            * HOURS_PER_YEAR
            / EXECUTED_HOURS
        )
        after_production = _number(
            after_summary["executed_annual_equivalent_t_y"][configuration]
        )
        add(
            "executed_annual_equivalent_final_product",
            configuration,
            "t/y equivalent",
            before_production,
            after_production,
            "The cumulative progress state removes repeated first-block +0.5% selection while retaining the feasibility envelope.",
        )
        add(
            "represented_procurement_cost",
            configuration,
            "EUR per 168 executed h",
            _number(before_cost[configuration]["executed_procurement_cost_eur"]),
            _number(after_cost[configuration]["executed_procurement_cost_eur"]),
            "Change follows the corrected executed production trajectory; represented boundary only.",
        )
        add(
            "represented_procurement_cost_intensity",
            configuration,
            "EUR/t final product",
            _number(before_cost[configuration]["procurement_cost_eur_per_t_final_product"]),
            _number(after_cost[configuration]["procurement_cost_eur_per_t_final_product"]),
            "Not a total-cost or profit comparison.",
        )
        b_dispatch = [row for row in before_hourly if row["configuration_id"] == configuration]
        a_dispatch = [row for row in after_hourly if row["configuration_id"] == configuration]
        add(
            "represented_grid_import",
            configuration,
            "TWh/y equivalent",
            _annual_mwh(b_dispatch, "net_grid_import_mwh") / 1_000_000.0,
            _annual_mwh(a_dispatch, "net_grid_import_mwh") / 1_000_000.0,
            "Net represented grid import; residual electricity is not an input.",
        )
        add(
            "represented_named_NG",
            configuration,
            "PJ_LHV/y equivalent",
            _annual_named_ng_pj(b_dispatch),
            _annual_named_ng_pj(a_dispatch),
            "Named model consumers only; residual NG remains excluded.",
        )
    add(
        "VN25_named_NG",
        "C1_phase1_BF_BOF_plus_DRP_EAF",
        "PJ_LHV/y equivalent",
        _number(before_anchors["c1_vn25_ng_4_1"]["model_annualised_value"]),
        _number(central_vn25["annual_named_ng_pj_lhv_y"]),
        "The 4.1-PJ/y MER value remains validation-only; no minimum service obligation was found.",
    )
    add(
        "generator_WAG_plus_flare",
        "C1_phase1_BF_BOF_plus_DRP_EAF",
        "PJ_LHV/y equivalent",
        _number(
            before_anchors["c1_generator_wag_with_flare_10_6"][
                "model_annualised_value"
            ]
        ),
        wag_total_after,
        "The small change follows the corrected 6.75-Mt/y executed denominator; the remaining 10.6-PJ/y gap is scenario allocation, not balance failure.",
    )
    return rows


def _check(
    check_id: str, passed: bool, requirement: str, evidence: str
) -> dict[str, str]:
    return {
        "check_id": check_id,
        "status": "pass" if passed else "fail",
        "requirement": requirement,
        "evidence": evidence,
    }


def build_acceptance_checks(
    *,
    case_directories: Mapping[str, Path],
    progress_rows: list[Mapping[str, Any]],
    wag_ledger: list[Mapping[str, Any]],
    generator_rows: list[Mapping[str, Any]],
    procurement_rows: list[Mapping[str, Any]],
) -> list[dict[str, str]]:
    central_summary = _json(case_directories["corrected_central"] / "run_summary.json")
    parent_checks = {
        case: _csv(directory / "validation_checks.csv")
        for case, directory in case_directories.items()
    }
    checks: list[dict[str, str]] = []
    checks.append(
        _check(
            "all_three_gurobi_cases_pass",
            all(
                _json(directory / "run_summary.json")["status"] == "pass"
                and all(row["status"] == "pass" for row in parent_checks[case])
                for case, directory in case_directories.items()
            ),
            "Central and two focused diagnostic runs solve and pass all parent guardrails.",
            "solver_run_metrics.csv",
        )
    )
    checks.append(
        _check(
            "rolling_production_bias_removed",
            len(progress_rows) == 14
            and all(
                abs(_number(row["executed_annual_equivalent_t_y"]) - PRODUCTION_TARGET_T_Y)
                <= 0.1
                and row["cumulative_envelope_status"] == "pass"
                for row in progress_rows
            ),
            "Repeated flat-price execution tracks 6.75 Mt/y without resetting production credit/debt.",
            "rolling_production_state_audit.csv",
        )
    )
    balance_pass = True
    for configuration in CONFIGURATIONS:
        for carrier in ("BFG", "COG", "BOFG"):
            selected = [
                row
                for row in wag_ledger
                if row["configuration_id"] == configuration
                and row["carrier"] == carrier
            ]
            source = sum(
                _number(row["executed_mwh_lhv"])
                for row in selected
                if row["flow_role"] == "source"
            )
            uses = sum(
                _number(row["executed_mwh_lhv"])
                for row in selected
                if row["flow_role"] in {"sink", "flare"}
            )
            residual = sum(
                _number(row["executed_mwh_lhv"])
                for row in selected
                if row["flow_role"] == "accounting_residual"
            )
            # executed_hourly.csv reports each term to six decimals.  The
            # source-to-sink reconstruction sums several such fields across
            # 168 hours, so 1e-3 MWh is a conservative reporting-roundoff
            # tolerance (the parent model residual check remains exact).
            balance_pass &= abs(source - uses - residual) <= 1e-3
    checks.append(
        _check(
            "carrier_specific_wag_source_to_sink_balance",
            balance_pass,
            "BFG, COG and BOFG generation equal named sinks plus flare plus signed residual.",
            "wag_source_to_sink_ledger.csv",
        )
    )
    checks.append(
        _check(
            "no_aggregate_mixed_or_c5pk_physical_allocation",
            all(row["carrier"] in {"BFG", "COG", "BOFG"} for row in wag_ledger)
            and not any(
                token in str(row).lower()
                for row in wag_ledger
                for token in ("aggregate_wag", "mixed_wag", "c5p_k")
            ),
            "Only carrier-specific accepted interfaces may allocate physical gas.",
            "wag_source_to_sink_ledger.csv;C5p_o contract",
        )
    )
    central_vn25 = next(
        row
        for row in generator_rows
        if row["case_id"] == "corrected_central" and row["asset"] == "VN25"
    )
    high_vn25 = next(
        row
        for row in generator_rows
        if row["case_id"] == "electricity_high" and row["asset"] == "VN25"
    )
    low_eff_vn25 = next(
        row
        for row in generator_rows
        if row["case_id"] == "vn25_efficiency_low_0_34" and row["asset"] == "VN25"
    )
    central_conversion = (
        3.6
        * _number(central_vn25["annual_electricity_twh_y"])
        / _number(central_vn25["annual_total_fuel_pj_lhv_y"])
    )
    low_eff_conversion = (
        3.6
        * _number(low_eff_vn25["annual_electricity_twh_y"])
        / _number(low_eff_vn25["annual_total_fuel_pj_lhv_y"])
    )
    checks.append(
        _check(
            "generator_diagnostics_physically_economically_monotonic",
            _number(high_vn25["annual_wag_fuel_pj_lhv_y"])
            + 1e-9
            >= _number(central_vn25["annual_wag_fuel_pj_lhv_y"])
            and _number(high_vn25["annual_grid_import_twh_y"])
            <= _number(central_vn25["annual_grid_import_twh_y"]) + 1e-9
            and abs(central_conversion - 0.345) <= 1e-9
            and abs(low_eff_conversion - 0.34) <= 1e-9
            and _number(low_eff_vn25["annual_named_ng_pj_lhv_y"]) <= 1e-9,
            "Higher electricity value does not reduce useful WAG generation or increase grid import; the bounded efficiency case preserves its lower electricity/fuel conversion and does not invent NG.",
            "generator_operating_contract_audit.csv",
        )
    )
    builder_text = (
        REPO_ROOT
        / "scripts"
        / "Data"
        / "04_Steel_Test_Case"
        / "steel"
        / "s4_4c_unified_physical_modelbuilder.py"
    ).read_text(encoding="utf-8")
    checks.append(
        _check(
            "no_forced_generator_annual_anchor",
            "c1_vn25_ng_4_1" not in builder_text
            and "c1_generator_wag_with_flare_10_6" not in builder_text
            and all(row["anchor_forced"] == "no" for row in generator_rows),
            "The 4.1- and 10.6-PJ/y values remain validation context, not dispatch requirements.",
            "generator_operating_contract_audit.csv;unified builder",
        )
    )
    checks.append(
        _check(
            "procurement_external_priced_once",
            all(
                row["priced_once_status"]
                in {"pass", "pass_or_explicit_unrepresented_gap", "not_applicable_inactive"}
                for row in procurement_rows
            ),
            "Every represented external flow is priced once; internal and residual flows are excluded.",
            "procurement_boundary_comparison.csv",
        )
    )
    cost_contract = load_future_cost_boundary_contract()
    checks.append(
        _check(
            "residual_electricity_ng_unpriced",
            all(
                str(row["objective_enabled"]).lower() == "false"
                for row in cost_contract
                if row["residual_status"] == "reporting_residual"
                or "RESIDUAL" in row["flow_id"]
            ),
            "Residual electricity and NG remain outputs only.",
            "c5_future_cost_boundary_contract.csv",
        )
    )
    checks.append(
        _check(
            "same_run_lineage_and_physical_guardrails",
            central_summary["c0_rolling_status"] == "pass"
            and central_summary["c1_rolling_status"] == "pass"
            and central_summary["origin_conservation_max_abs_annualised_residual_t_y"]
            <= 1e-6,
            "C0/C1, quota, origin, inventory, WAG, steam, electricity and cost identities use the corrected same-run lineage.",
            "central parent validation_checks.csv;solver_run_metrics.csv",
        )
    )
    return checks


def run_pre_dam_operational_boundary_closure(
    *, output_directory: str | Path = DEFAULT_OUTPUT
) -> dict[str, Any]:
    output = Path(output_directory).resolve()
    if output.exists():
        raise OperationalBoundaryClosureError(f"Output already exists: {output}")
    if not BEFORE_RUN.is_dir():
        raise OperationalBoundaryClosureError(
            f"Accepted before-run is missing: {BEFORE_RUN}"
        )
    base_config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(
        prefix="steel_s2_pre_dam_boundary_"
    ) as temp_name:
        case_directories = _run_cases(Path(temp_name))
        central = case_directories["corrected_central"]
        central_hourly = _csv(central / "executed_hourly.csv")
        progress_rows = build_rolling_production_state_audit(central)
        wag_ledger = build_wag_source_to_sink_ledger(central_hourly)
        wag_anchors = build_wag_anchor_reconciliation(wag_ledger)
        generator_rows = build_generator_operating_contract_audit(
            case_directories
        )
        procurement_rows = build_procurement_boundary_comparison(central)
        before_after_rows = build_before_after_comparison(
            central, wag_anchors, generator_rows
        )
        solver_rows = build_solver_run_metrics(case_directories)
        checks = build_acceptance_checks(
            case_directories=case_directories,
            progress_rows=progress_rows,
            wag_ledger=wag_ledger,
            generator_rows=generator_rows,
            procurement_rows=procurement_rows,
        )
        status = "pass" if all(row["status"] == "pass" for row in checks) else "fail"
        unresolved_generator_evidence = sorted(
            {
                str(row["exact_missing_evidence"])
                for row in generator_rows
                if row["exact_missing_evidence"]
            }
        )
        bf_pellet_gap = any(
            row["flow_or_gap_id"] in {"C0_BF_PELLETS", "C1_BF_PELLETS"}
            and row["cost_coverage_status"] == "explicit_scope_gap_not_free"
            for row in procurement_rows
        )
        if status != "pass":
            decision = "needs_more_S2_boundary_evidence"
        elif unresolved_generator_evidence or bf_pellet_gap:
            decision = "DAM_data_contract_only_operational_gaps_remain"
        else:
            decision = "ready_for_governed_DAM_data_contract"
        if decision not in PERMITTED_DECISIONS:
            raise OperationalBoundaryClosureError("Invalid closure decision.")
        central_summary = _json(central / "run_summary.json")
        central_costs = {
            row["configuration_id"]: row
            for row in _csv(central / "procurement_cost_summary.csv")
        }
        central_vn25 = next(
            row
            for row in generator_rows
            if row["case_id"] == "corrected_central" and row["asset"] == "VN25"
        )
        wag_anchor_total = next(
            row
            for row in wag_anchors
            if row["anchor_id"] == "c1_generator_wag_with_flare_10_6"
        )
        wag_totals: dict[str, dict[str, float]] = defaultdict(dict)
        for configuration in CONFIGURATIONS:
            for carrier in ("BFG", "COG", "BOFG"):
                selected = [
                    row
                    for row in wag_ledger
                    if row["configuration_id"] == configuration
                    and row["carrier"] == carrier
                ]
                wag_totals[configuration][f"{carrier}_generation_pj_y"] = round(
                    sum(
                        _number(row["annualised_pj_lhv_y"])
                        for row in selected
                        if row["flow_role"] == "source"
                    ),
                    12,
                )
                wag_totals[configuration][f"{carrier}_residual_pj_y"] = round(
                    sum(
                        _number(row["annualised_pj_lhv_y"])
                        for row in selected
                        if row["flow_role"] == "accounting_residual"
                    ),
                    12,
                )
        case_summaries = {
            case_id: {
                "status": _json(directory / "run_summary.json")["status"],
                "executed_annual_equivalent_t_y": _json(
                    directory / "run_summary.json"
                )["executed_annual_equivalent_t_y"],
                "model_solve_rows": len(
                    _json(directory / "run_summary.json")["model_size_by_replan"]
                ),
            }
            for case_id, directory in case_directories.items()
        }
        summary = {
            "run_id": output.name,
            "status": status,
            "final_decision": decision,
            "baseline_lineage": BEFORE_RUN.name,
            "corrected_central_lineage": f"{output.name}__corrected_central",
            "run_class": "validation",
            "lineage_role": "derived_operational_hardening",
            "output_policy": "minimal",
            "new_gurobi_run_families": 3,
            "case_summaries": case_summaries,
            "rolling_production": {
                "target_t_y": PRODUCTION_TARGET_T_Y,
                "before_t_y": {
                    configuration: round(
                        _json(BEFORE_RUN / "run_summary.json")[
                            "cumulative_execution_t"
                        ][configuration]
                        * HOURS_PER_YEAR
                        / EXECUTED_HOURS,
                        6,
                    )
                    for configuration in CONFIGURATIONS
                },
                "after_t_y": central_summary[
                    "executed_annual_equivalent_t_y"
                ],
                "maximum_abs_carried_credit_t": central_summary[
                    "maximum_abs_carried_production_credit_t"
                ],
                "envelope_fraction": 0.005,
                "hourly_profile_fixed": False,
            },
            "wag_source_to_sink_totals": dict(wag_totals),
            "generator_anchor": {
                "WAG_plus_flare_model_pj_y": _number(
                    wag_anchor_total["model_annualised_pj_lhv_y"]
                ),
                "WAG_plus_flare_anchor_pj_y": 10.6,
                "WAG_plus_flare_signed_residual_pj_y": _number(
                    wag_anchor_total["signed_residual_pj_lhv_y"]
                ),
                "VN25_named_NG_model_pj_y": _number(
                    central_vn25["annual_named_ng_pj_lhv_y"]
                ),
                "VN25_named_NG_anchor_pj_y": 4.1,
                "annual_anchors_forced": False,
            },
            "procurement_cost": {
                configuration: {
                    "executed_cost_eur": _number(
                        central_costs[configuration][
                            "executed_procurement_cost_eur"
                        ]
                    ),
                    "eur_per_t_final_product": _number(
                        central_costs[configuration][
                            "procurement_cost_eur_per_t_final_product"
                        ]
                    ),
                }
                for configuration in CONFIGURATIONS
            },
            "direct_C0_C1_total_cost_comparability": "not_supported",
            "unresolved_generator_operating_evidence": unresolved_generator_evidence,
            "unresolved_procurement_evidence": [
                "BF-grade pellet quantity and burden origin for each active BF route",
                "independent matching represented-variable-procurement benchmark",
            ],
            "checks_passed": sum(row["status"] == "pass" for row in checks),
            "checks_total": len(checks),
            "DAM_bidding_active": False,
            "settlement_active": False,
            "next_permitted_task": (
                "governed_DAM_data_contract_only_while_operational_evidence_gaps_remain"
                if decision == "DAM_data_contract_only_operational_gaps_remain"
                else "governed_DAM_data_contract"
                if decision == "ready_for_governed_DAM_data_contract"
                else "targeted_S2_boundary_evidence_resolution"
            ),
        }
        case_summary_hashes = {
            case_id: _sha256(directory / "run_summary.json")
            for case_id, directory in case_directories.items()
        }

        output.mkdir(parents=True)
        _write_csv(output / "rolling_production_state_audit.csv", progress_rows)
        _write_csv(output / "wag_source_to_sink_ledger.csv", wag_ledger)
        _write_csv(output / "wag_anchor_reconciliation.csv", wag_anchors)
        _write_csv(
            output / "generator_operating_contract_audit.csv", generator_rows
        )
        _write_csv(
            output / "procurement_boundary_comparison.csv", procurement_rows
        )
        _write_csv(
            output / "before_after_anchor_comparison.csv", before_after_rows
        )
        _write_csv(output / "solver_run_metrics.csv", solver_rows)
        _write_csv(output / "acceptance_checks.csv", checks)
        _write_json(output / "run_summary.json", summary)
        resolved = {
            **base_config,
            "run_id": output.name,
            "run_class": "validation",
            "lineage_role": "derived_operational_hardening",
            "diagnostic_cases": _case_overrides(base_config),
            "actual_DAM_data_active": False,
            "bidding_active": False,
            "settlement_active": False,
        }
        (output / "resolved_config.yaml").write_text(
            yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8"
        )
        inputs = (
            CONFIG_PATH,
            BEFORE_RUN / "run_summary.json",
            GENERATOR_SOURCE_CARD,
            C5P_O_LEDGER,
            REPO_ROOT
            / "data"
            / "03_Optimisation"
            / "inputs"
            / "assets"
            / "steel"
            / "S4"
            / "c5_component_ontology"
            / "c5_future_cost_boundary_contract.csv",
            REPO_ROOT
            / "data"
            / "03_Optimisation"
            / "inputs"
            / "assets"
            / "steel"
            / "S4"
            / "c5_component_ontology"
            / "c5_procurement_boundary_gap_register.csv",
        )
        _write_json(
            output / "input_manifest.json",
            {
                "run_id": output.name,
                "baseline_git_commit": _json(
                    BEFORE_RUN / "code_version.json"
                ).get("git_commit"),
                "inputs": [
                    {
                        "path": str(path.relative_to(REPO_ROOT)).replace(
                            "\\", "/"
                        ),
                        "sha256": _sha256(path),
                    }
                    for path in inputs
                ],
                "ephemeral_same_run_case_summary_sha256": case_summary_hashes,
            },
        )
        _write_json(
            output / "code_version.json",
            {
                "git_commit": _json(BEFORE_RUN / "code_version.json").get(
                    "git_commit"
                ),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "module_sha256": _sha256(Path(__file__)),
            },
        )
        _write_json(
            output / "registry_entry.json",
            {
                "run_id": output.name,
                "run_class": "validation",
                "lineage_role": "derived_operational_hardening",
                "output_policy": "minimal",
                "status": status,
                "decision": decision,
                "git_eligible": False,
            },
        )
        (output / "warnings_and_limitations.md").write_text(
            "# Warnings and limitations\n\n"
            "- Annual values are 8760/168 annual equivalents of seven solved 24-hour execution blocks, not a simulated calendar year.\n"
            "- VN25/IJ01 MER annual fuel values remain validation scenarios, not operating minima.\n"
            "- VN25 minimum stable load, heat-rate curve, ramp/start rules and outage availability are not source-backed.\n"
            "- IJ01 CHP electricity/steam split, efficiency, electric capacity and heat-service obligation remain deferred.\n"
            "- C0 has no source-backed per-unit VN25/IJ01 split; its carrier-specific generator sink remains an aggregate generator interface.\n"
            "- BF-grade pellet quantity is absent from the active physical burden, so represented C0/C1 EUR/t are not total-cost comparable.\n"
            "- Purchased scrap remains an explicit development boundary because no closed internal recycle-origin loop exists.\n"
            "- Residual electricity and NG are reporting-only and unpriced. HBI is physically inactive.\n"
            "- No DAM data, bids, settlement, revenue, ETS, stochasticity, CVaR or mFRR is active.\n",
            encoding="utf-8",
        )
        (output / "README.md").write_text(
            f"# {output.name}\n\n"
            f"- Status: `{status}`\n"
            f"- Decision: `{decision}`\n"
            "- Runs: one corrected central fixed-reference Gurobi family and two focused diagnostics.\n"
            "- Rolling correction: cumulative production credit/debt is carried across replans; the executed annual equivalent tracks 6.75 Mt/y without fixing hourly throughput.\n"
            f"- C1 generator WAG plus flare: {summary['generator_anchor']['WAG_plus_flare_model_pj_y']:.9f} PJ/y versus 10.6 PJ/y context.\n"
            f"- C1 VN25 named NG: {summary['generator_anchor']['VN25_named_NG_model_pj_y']:.9f} PJ/y versus 4.1 PJ/y context.\n"
            "- Interpretation: both generator anchors remain unforced; missing operating contracts are listed explicitly.\n"
            "- Procurement: represented external flows are priced once, but BF pellets and an independent matching cost benchmark remain open.\n"
            "- This run does not activate or design DAM dispatch.\n",
            encoding="utf-8",
        )
    return {"run_directory": output, "summary": summary}


def repair_existing_audit_only(
    *, output_directory: str | Path = DEFAULT_OUTPUT
) -> dict[str, Any]:
    """Repair audit predicates from persisted solved evidence without re-solving."""

    output = Path(output_directory).resolve()
    required = (
        output / "acceptance_checks.csv",
        output / "wag_source_to_sink_ledger.csv",
        output / "generator_operating_contract_audit.csv",
        output / "run_summary.json",
    )
    if not all(path.is_file() for path in required):
        raise OperationalBoundaryClosureError(
            "Audit-only repair requires the complete persisted failed audit."
        )
    checks = _csv(output / "acceptance_checks.csv")
    wag_ledger = _csv(output / "wag_source_to_sink_ledger.csv")
    balance_pass = True
    max_reporting_residual = 0.0
    for configuration in CONFIGURATIONS:
        for carrier in ("BFG", "COG", "BOFG"):
            selected = [
                row
                for row in wag_ledger
                if row["configuration_id"] == configuration
                and row["carrier"] == carrier
            ]
            source = sum(
                _number(row["executed_mwh_lhv"])
                for row in selected
                if row["flow_role"] == "source"
            )
            uses = sum(
                _number(row["executed_mwh_lhv"])
                for row in selected
                if row["flow_role"] in {"sink", "flare"}
            )
            residual = sum(
                _number(row["executed_mwh_lhv"])
                for row in selected
                if row["flow_role"] == "accounting_residual"
            )
            reconstructed = abs(source - uses - residual)
            max_reporting_residual = max(max_reporting_residual, reconstructed)
            balance_pass &= reconstructed <= 1e-3
    generator_rows = _csv(output / "generator_operating_contract_audit.csv")
    by_case = {
        row["case_id"]: row for row in generator_rows if row["asset"] == "VN25"
    }
    central = by_case["corrected_central"]
    high = by_case["electricity_high"]
    low = by_case["vn25_efficiency_low_0_34"]
    central_conversion = (
        3.6
        * _number(central["annual_electricity_twh_y"])
        / _number(central["annual_total_fuel_pj_lhv_y"])
    )
    low_conversion = (
        3.6
        * _number(low["annual_electricity_twh_y"])
        / _number(low["annual_total_fuel_pj_lhv_y"])
    )
    monotonic_pass = (
        _number(high["annual_wag_fuel_pj_lhv_y"])
        + 1e-9
        >= _number(central["annual_wag_fuel_pj_lhv_y"])
        and _number(high["annual_grid_import_twh_y"])
        <= _number(central["annual_grid_import_twh_y"]) + 1e-9
        and abs(central_conversion - 0.345) <= 1e-9
        and abs(low_conversion - 0.34) <= 1e-9
        and _number(low["annual_named_ng_pj_lhv_y"]) <= 1e-9
    )
    for row in checks:
        if row["check_id"] == "carrier_specific_wag_source_to_sink_balance":
            row["status"] = "pass" if balance_pass else "fail"
            row["evidence"] = (
                "wag_source_to_sink_ledger.csv; maximum reconstruction residual "
                f"{max_reporting_residual:.9f} MWh from six-decimal hourly reporting"
            )
        elif row["check_id"] == "generator_diagnostics_physically_economically_monotonic":
            row["status"] = "pass" if monotonic_pass else "fail"
            row["evidence"] = (
                "generator_operating_contract_audit.csv; central conversion "
                f"{central_conversion:.12f}; low-efficiency conversion {low_conversion:.12f}"
            )
    status = "pass" if all(row["status"] == "pass" for row in checks) else "fail"
    summary = _json(output / "run_summary.json")
    decision = (
        "DAM_data_contract_only_operational_gaps_remain"
        if status == "pass"
        else "needs_more_S2_boundary_evidence"
    )
    summary.update(
        {
            "status": status,
            "final_decision": decision,
            "checks_passed": sum(row["status"] == "pass" for row in checks),
            "checks_total": len(checks),
            "audit_only_repair": {
                "solver_reruns": 0,
                "maximum_wag_reporting_reconstruction_residual_mwh": round(
                    max_reporting_residual, 12
                ),
                "central_vn25_conversion": round(central_conversion, 12),
                "low_efficiency_vn25_conversion": round(low_conversion, 12),
            },
            "next_permitted_task": (
                "governed_DAM_data_contract_only_while_operational_evidence_gaps_remain"
                if status == "pass"
                else "targeted_S2_boundary_evidence_resolution"
            ),
        }
    )
    registry = _json(output / "registry_entry.json")
    registry.update({"status": status, "decision": decision})
    _write_csv(output / "acceptance_checks.csv", checks)
    _write_json(output / "run_summary.json", summary)
    _write_json(output / "registry_entry.json", registry)
    code_version = _json(output / "code_version.json")
    code_version.update(
        {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "module_sha256": _sha256(Path(__file__)),
            "audit_only_repair_solver_reruns": 0,
        }
    )
    _write_json(output / "code_version.json", code_version)
    readme = (output / "README.md").read_text(encoding="utf-8")
    readme = readme.replace("- Status: `fail`", f"- Status: `{status}`")
    readme = readme.replace(
        "- Decision: `needs_more_S2_boundary_evidence`",
        f"- Decision: `{decision}`",
    )
    (output / "README.md").write_text(readme, encoding="utf-8")
    return {"run_directory": output, "summary": summary}
