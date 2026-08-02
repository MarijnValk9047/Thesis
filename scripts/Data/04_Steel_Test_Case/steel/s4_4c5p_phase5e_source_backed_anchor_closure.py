"""Phase 5E source-backed annual boundary closure with frozen dynamic checks.

The annual service accounts in this module are reporting/validation contracts.
They never enter dispatch, feasibility, or represented procurement cost.  The
hourly checks rerun the accepted no-export physical model unchanged.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .s4_4c5p_af_closed_loop_feasibility_anchor_reconciliation import (
    C0_CONFIGURATION,
    C1_CONFIGURATION,
    HOURS_PER_YEAR,
    PJ_PER_MWH,
    run_closed_loop_feasibility_anchor_reconciliation,
)
from .s4_4c5p_phase4_terminal_inventory_equivalence import (
    _artifact,
    _case_overrides,
    check_phase4_config,
    load_phase4_config,
)
from .s4_4c5p_phase5b_c0_export_sensitivity import (
    _git_head,
    _read_csv,
    _read_json,
    _resolve,
    _select_solver,
    _sha256,
    install_terminal_validation_extension,
)
from .s4_4c5p_phase5d_source_backed_ng_mechanism_closure import (
    heat_verification_rows,
)
from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


RUN_ID = "steel_c5_phase5e_source_backed_anchor_closure_v1_20260727"
CONFIG_PATH = (
    REPO_ROOT
    / "scripts/Data/04_Steel_Test_Case/configs/steel_c5_phase5e_source_backed_anchor_closure.yaml"
)
EXPECTED_PERIODS = ("validation_2024-02-12", "validation_2024-07-01")
PRIMARY_COVERAGE_FAMILIES = ("natural_gas", "electricity", "scope1_co2")


class Phase5ESourceClosureError(RuntimeError):
    pass


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    fields: list[str] = []
    for row in materialized:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)


def _portable(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT)).replace("\\", "/")


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _float(row: Mapping[str, Any], field: str) -> float:
    return float(row.get(field) or 0.0)


def _sum(rows: Iterable[Mapping[str, Any]], field: str) -> float:
    return sum(_float(row, field) for row in rows)


def load_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload.get("run_id") != RUN_ID or payload.get("output_policy") != "minimal":
        raise Phase5ESourceClosureError("Phase 5E identity or output policy changed.")
    phase = payload.get("phase5e")
    if not isinstance(phase, Mapping):
        raise Phase5ESourceClosureError("Phase 5E config section is missing.")
    periods = tuple(row["period_id"] for row in phase["periods"])
    if periods != EXPECTED_PERIODS:
        raise Phase5ESourceClosureError("Phase 5E DEVELOPMENT periods changed.")
    policy = phase["policy"]
    forbidden_true = (
        "annual_service_accounts_enter_dispatch",
        "annual_service_accounts_enter_cost",
        "external_export_allowed",
        "changes_physics",
        "changes_prices",
        "changes_terminal_bands",
        "changes_production_targets",
        "parameter_calibration_performed",
        "held_out_periods_used",
        "phase5d_policy_promoted",
    )
    if any(bool(policy.get(key)) for key in forbidden_true):
        raise Phase5ESourceClosureError(
            "Phase 5E annual accounts must remain non-dispatch, non-priced, and non-calibrating."
        )
    if tuple(phase["gates"]["primary_carriers_for_coverage"]) != PRIMARY_COVERAGE_FAMILIES:
        raise Phase5ESourceClosureError("Carrier-specific coverage gate changed.")
    return payload


def load_source_contract(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_csv(Path(path))
    required = {
        "record_id",
        "configuration",
        "family",
        "record_kind",
        "component",
        "value",
        "unit",
        "named_share",
        "source_locator",
        "quantity_origin",
        "dispatch_role",
    }
    if not rows or required.difference(rows[0]):
        raise Phase5ESourceClosureError("Source-backed contract schema is incomplete.")
    ids = [row["record_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise Phase5ESourceClosureError("Source-backed contract record IDs must be unique.")
    forbidden_origin_tokens = ("anchor_minus_model", "model_residual", "calibration_plug")
    for row in rows:
        row["value"] = float(row["value"])
        row["named_share"] = str(row["named_share"]).lower() == "true"
        if not row["source_locator"].strip():
            raise Phase5ESourceClosureError(f"Missing source locator for {row['record_id']}.")
        origin = str(row["quantity_origin"]).lower()
        if any(token in origin for token in forbidden_origin_tokens):
            raise Phase5ESourceClosureError(
                f"Forbidden residual-derived quantity origin for {row['record_id']}."
            )
    return rows


def _families(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["configuration"]), str(row["family"])), []).append(row)
    return grouped


def annual_anchor_comparisons(
    rows: Iterable[Mapping[str, Any]], relative_tolerance: float = 0.05
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for (configuration, family), group in sorted(_families(rows).items()):
        primary = [
            row for row in group if row["record_kind"] in {"primary_total", "direct_primary_total"}
        ]
        if len(primary) != 1:
            raise Phase5ESourceClosureError(
                f"{configuration}/{family} requires exactly one primary total."
            )
        anchor = float(primary[0]["value"])
        components = [
            row
            for row in group
            if row["record_kind"] in {"component", "boundary_component"}
        ]
        if primary[0]["record_kind"] == "direct_primary_total":
            accounted = anchor
            basis = "direct_primary_source_total_no_invented_decomposition"
        else:
            if not components:
                raise Phase5ESourceClosureError(
                    f"{configuration}/{family} has no independent source components."
                )
            accounted = sum(float(row["value"]) for row in components)
            basis = "sum_of_independently_sourced_components"
        residual = accounted - anchor
        relative = abs(residual) / abs(anchor) if anchor else abs(residual)
        comparisons.append(
            {
                "configuration": configuration,
                "family": family,
                "accounted_value": round(accounted, 9),
                "primary_anchor_value": anchor,
                "unit": primary[0]["unit"],
                "signed_residual": round(residual, 9),
                "absolute_relative_error": relative,
                "tolerance": relative_tolerance,
                "status": "pass" if relative <= relative_tolerance else "fail",
                "comparison_basis": basis,
                "enters_dispatch": False,
                "enters_cost": False,
            }
        )
    return comparisons


def carrier_coverage(
    rows: Iterable[Mapping[str, Any]],
    minimum_named_share: float = 0.60,
    maximum_unallocated_share: float = 0.40,
) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    grouped = _families(rows)
    for configuration in ("C0", "C1"):
        for family in PRIMARY_COVERAGE_FAMILIES:
            group = grouped[(configuration, family)]
            total_row = next(row for row in group if row["record_kind"] == "primary_total")
            total = float(total_row["value"])
            named = sum(
                float(row["value"])
                for row in group
                if row["record_kind"] == "component" and bool(row["named_share"])
            )
            named_share = min(1.0, named / total) if total else 1.0
            unallocated = max(0.0, total - named)
            unallocated_share = unallocated / total if total else 0.0
            passed = (
                named_share >= minimum_named_share
                and unallocated_share < maximum_unallocated_share
            )
            coverage.append(
                {
                    "configuration": configuration,
                    "carrier": family,
                    "primary_total": total,
                    "named_source_backed_value": named,
                    "unallocated_or_boundary_value": unallocated,
                    "unit": total_row["unit"],
                    "named_share_fraction": named_share,
                    "unallocated_share_fraction": unallocated_share,
                    "minimum_named_share": minimum_named_share,
                    "maximum_unallocated_share": maximum_unallocated_share,
                    "status": "pass" if passed else "fail",
                    "representation_mode": "source_backed_annual_service_accounting",
                }
            )
    return coverage


def generator_balances(
    rows: Iterable[Mapping[str, Any]],
    secondary_anchors_twh_y: Mapping[str, Any],
    relative_tolerance: float = 0.05,
) -> list[dict[str, Any]]:
    grouped = _families(rows)
    results: list[dict[str, Any]] = []
    for configuration in ("C0", "C1"):
        fuel_group = grouped[(configuration, "generator_fuel")]
        fuel_total = next(
            float(row["value"]) for row in fuel_group if row["record_kind"] == "primary_total"
        )
        fuel_components = {
            str(row["component"]): float(row["value"])
            for row in fuel_group
            if row["record_kind"] == "component"
        }
        component_sum = sum(fuel_components.values())
        output_group = grouped[(configuration, "generator_electricity")]
        output = next(
            float(row["value"])
            for row in output_group
            if row["record_kind"] == "direct_primary_total"
        )
        loss = next(
            float(row["value"])
            for row in output_group
            if row["record_kind"] == "balance_component"
        )
        ng = fuel_components.get("natural_gas", 0.0)
        wag = component_sum - ng
        attributed_wag_output_pj = output * wag / fuel_total
        attributed_wag_output_twh = attributed_wag_output_pj / 3.6
        anchor = float(secondary_anchors_twh_y[configuration])
        anchor_gap = abs(attributed_wag_output_twh / anchor - 1.0)
        fuel_gap = component_sum - fuel_total
        energy_gap = output + loss - fuel_total
        passed = (
            abs(fuel_gap) <= 1e-9
            and abs(energy_gap) <= 1e-9
            and anchor_gap <= relative_tolerance
        )
        results.append(
            {
                "configuration": configuration,
                "generator_fuel_total_pj_y": fuel_total,
                "generator_fuel_component_sum_pj_y": component_sum,
                "fuel_identity_residual_pj_y": fuel_gap,
                "wag_fuel_pj_y": wag,
                "ng_fuel_pj_y": ng,
                "electricity_output_pj_y": output,
                "losses_and_balance_pj_y": loss,
                "energy_identity_residual_pj_y": energy_gap,
                "electrical_efficiency_fraction": output / fuel_total,
                "fuel_proportional_wag_electricity_twh_y": attributed_wag_output_twh,
                "secondary_wag_electricity_anchor_twh_y": anchor,
                "secondary_anchor_absolute_relative_error": anchor_gap,
                "status": "pass" if passed else "fail",
                "attribution_role": "derived_reporting_indicator_not_dispatch_constraint",
            }
        )
    return results


def secondary_anchor_context(
    rows: Iterable[Mapping[str, Any]], generator_rows: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    grouped = _families(rows)

    def value(configuration: str, family: str, kind: str) -> float:
        return next(
            float(row["value"])
            for row in grouped[(configuration, family)]
            if row["record_kind"] == kind
        )

    gen = {row["configuration"]: row for row in generator_rows}
    comparisons = [
        ("C0", "old_real_site_ng_context", 9.666, value("C0", "natural_gas", "primary_total"), "PJ/y", "superseded_by_exact_2025_mer"),
        ("C0", "Athanasiadis_Table8_electricity", 3.17, value("C0", "electricity", "secondary_total") / 3.6, "TWh/y", "secondary_model_context"),
        ("C1", "Athanasiadis_Table9_electricity", 4.89, value("C1", "electricity", "primary_total") / 3.6, "TWh/y", "secondary_model_context"),
        ("C0", "Athanasiadis_WAG_electricity", 2.528, float(gen["C0"]["fuel_proportional_wag_electricity_twh_y"]), "TWh/y", "secondary_model_context"),
        ("C1", "Athanasiadis_WAG_electricity", 1.23, float(gen["C1"]["fuel_proportional_wag_electricity_twh_y"]), "TWh/y", "secondary_model_context"),
        ("C0", "Athanasiadis_Table8_CO2", 13.365, value("C0", "scope1_co2", "primary_total"), "MtCO2/y", "secondary_model_context"),
        ("C1", "Athanasiadis_Table9_CO2", 9.107793, value("C1", "scope1_co2", "primary_total"), "MtCO2/y", "secondary_model_context"),
        ("C0", "rounded_MER_WAG_context", 54.0, value("C0", "wag_production", "primary_total"), "PJ/y", "secondary_rounded_context"),
    ]
    return [
        {
            "configuration": configuration,
            "comparison_id": comparison_id,
            "secondary_anchor": anchor,
            "phase5e_value": model,
            "unit": unit,
            "signed_difference": model - anchor,
            "absolute_relative_error": abs(model / anchor - 1.0),
            "role": role,
            "primary_gate": False,
        }
        for configuration, comparison_id, anchor, model, unit, role in comparisons
    ]


def dynamic_source_service_accounts(
    period_id: str,
    artifact: Mapping[str, Any],
    contract_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Reconcile fixed annual source accounts to any directly overlapping solver rows.

    The source account is the full-site reporting partition.  Dynamic overlap is
    diagnostic only and is never added to it, so an endogenous component cannot
    be counted twice.
    """

    field_map: dict[tuple[str, str, str], tuple[str, ...]] = {
        ("C0", "natural_gas", "steelmaking_and_rolling"): (
            "NG_to_HSM_mwh",
            "NG_to_PEFA_malerij_mwh",
            "NG_to_PEFA_branderij_mwh",
        ),
        ("C0", "natural_gas", "Vattenfall_generators"): ("generator_named_ng_mwh",),
        ("C1", "natural_gas", "DRI_factory"): ("DRP_named_NG_mwh",),
        ("C1", "natural_gas", "EAF"): ("EAF_named_NG_mwh",),
        ("C1", "natural_gas", "Vattenfall_generators"): ("generator_named_ng_mwh",),
        ("C0", "electricity", "ironmaking"): (
            "BF_electricity_mwh",
            "KGF_electricity_mwh",
            "BOF_electricity_mwh",
            "PEFA_electricity_mwh",
            "sinter_electricity_mwh",
        ),
        ("C0", "electricity", "steelmaking_and_rolling"): (
            "HSM_rolling_electricity_mwh",
            "DSP_electricity_mwh",
        ),
        ("C0", "electricity", "oxygen_production"): ("ASU_oxygen_electricity_mwh",),
        ("C1", "electricity", "ironmaking"): (
            "BF_electricity_mwh",
            "KGF_electricity_mwh",
            "BOF_electricity_mwh",
            "PEFA_electricity_mwh",
            "sinter_electricity_mwh",
        ),
        ("C1", "electricity", "steelmaking_and_rolling"): (
            "HSM_rolling_electricity_mwh",
            "DSP_electricity_mwh",
        ),
        ("C1", "electricity", "oxygen_production"): ("ASU_oxygen_electricity_mwh",),
        ("C1", "electricity", "DRI_factory"): ("DRP_electricity_mwh",),
        ("C1", "electricity", "EAF"): (
            "EAF_arc_electricity_mwh",
            "EAF_secondary_electricity_mwh",
        ),
    }
    by_short_configuration = {
        "C0": [
            row
            for row in artifact["hourly"]
            if row.get("configuration_id") == C0_CONFIGURATION
        ],
        "C1": [
            row
            for row in artifact["hourly"]
            if row.get("configuration_id") == C1_CONFIGURATION
        ],
    }
    results: list[dict[str, Any]] = []
    for source_row in contract_rows:
        if source_row["family"] not in PRIMARY_COVERAGE_FAMILIES or source_row[
            "record_kind"
        ] not in {"component", "boundary_component"}:
            continue
        configuration = str(source_row["configuration"])
        hourly = by_short_configuration[configuration]
        fields = field_map.get(
            (configuration, str(source_row["family"]), str(source_row["component"])),
            (),
        )
        dynamic_value = None
        if fields:
            dynamic_mwh = sum(_sum(hourly, field) for field in fields)
            if source_row["unit"] == "PJ/y":
                dynamic_value = dynamic_mwh * (HOURS_PER_YEAR / len(hourly)) * PJ_PER_MWH
        annual_value = float(source_row["value"])
        results.append(
            {
                "period_id": period_id,
                "configuration": configuration,
                "configuration_id": (
                    C0_CONFIGURATION if configuration == "C0" else C1_CONFIGURATION
                ),
                "carrier": source_row["family"],
                "service_component": source_row["component"],
                "source_backed_annual_value": annual_value,
                "source_backed_hourly_rate": annual_value / HOURS_PER_YEAR,
                "unit": source_row["unit"],
                "dynamic_overlap_annual_equivalent": dynamic_value,
                "dynamic_overlap_fields": ";".join(fields),
                "overlap_status": (
                    "direct_dynamic_overlap_reported_not_added"
                    if fields
                    else "source_account_only_no_hourly_profile_claim"
                ),
                "quantity_role": "annual_account_partition_not_additive_to_optimizer",
                "enters_dispatch": False,
                "enters_cost": False,
                "source_locator": source_row["source_locator"],
            }
        )
    return results


def _dynamic_metrics(
    period_id: str,
    artifact: Mapping[str, Any],
    contract_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    primary_ng = {
        str(row["configuration"]): float(row["value"])
        for row in contract_rows
        if row["family"] == "natural_gas" and row["record_kind"] == "primary_total"
    }
    metrics: list[dict[str, Any]] = []
    for configuration in (C0_CONFIGURATION, C1_CONFIGURATION):
        rows = [row for row in artifact["hourly"] if row.get("configuration_id") == configuration]
        factor = HOURS_PER_YEAR / len(rows)
        short_configuration = "C0" if configuration == C0_CONFIGURATION else "C1"
        ng_mwh = (
            _sum(rows, "full_site_energy_bridge_named_ng_mwh")
            + _sum(rows, "DRP_named_NG_mwh")
            + _sum(rows, "EAF_named_NG_mwh")
            + _sum(rows, "NG_to_HSM_mwh")
            + _sum(rows, "NG_to_PEFA_malerij_mwh")
            + _sum(rows, "NG_to_PEFA_branderij_mwh")
            + _sum(rows, "NG_to_boiler_mwh")
            + _sum(rows, "generator_named_ng_mwh")
        )
        dri_t = _sum(rows, "C1_DRP_DRI_output_t_h")
        dri_ng_gj_per_t = (
            _sum(rows, "DRP_named_NG_mwh") * 3.6 / dri_t if dri_t else None
        )
        metrics.append(
            {
                "period_id": period_id,
                "configuration_id": configuration,
                "executed_hours": len(rows),
                "final_product_t": _sum(rows, "final_product_output_t"),
                "optimizer_boundary_ng_pj_y_annual_equivalent": ng_mwh * factor * PJ_PER_MWH,
                "legacy_fixed_ng_component_pj_y_annual_equivalent": _sum(rows, "full_site_fixed_ng_component_mwh") * factor * PJ_PER_MWH,
                "phase5e_source_backed_full_site_ng_pj_y": primary_ng[short_configuration],
                "legacy_fixed_component_included_in_phase5e_total": False,
                "total_wag_pj_y_annual_equivalent": _sum(rows, "WAG_generated") * factor * PJ_PER_MWH,
                "wag_generator_electricity_twh_y_annual_equivalent": _sum(rows, "WAG_generator_electricity_mwh") * factor / 1e6,
                "gross_grid_import_mwh": _sum(rows, "gross_grid_import_mwh"),
                "gross_grid_export_mwh": _sum(rows, "gross_grid_export_mwh"),
                "generator_fuel_mwh": _sum(rows, "generator_total_fuel_mwh"),
                "generator_electricity_mwh": _sum(rows, "generator_electricity_mwh"),
                "steam_unserved_t": _sum(rows, "steam_15bar_unserved_t"),
                "dri_output_t": dri_t,
                "dri_ng_gj_lhv_per_t": dri_ng_gj_per_t,
            }
        )
    return metrics


def dynamic_period_checks(
    period_id: str,
    artifact: Mapping[str, Any],
    gates: Mapping[str, Any],
    badarinath_rows: Iterable[Mapping[str, Any]],
    contract_rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tol = float(gates["dynamic_balance_tolerance"])
    metrics = _dynamic_metrics(period_id, artifact, contract_rows)
    rows = artifact["hourly"]
    c0_rows = [row for row in rows if row.get("configuration_id") == C0_CONFIGURATION]
    c1_metric = next(row for row in metrics if row["configuration_id"] == C1_CONFIGURATION)
    heat_rows = heat_verification_rows(period_id, rows)
    dri_direction = next(
        (
            float(row["value"])
            for row in badarinath_rows
            if row.get("period_id") == period_id
            and row.get("metric_id") == "dri_hourly_inventory_change_price_correlation"
        ),
        None,
    )
    checks = [
        ("all_models_optimal", len(artifact["models"]) == 14 and all(row.get("solver_status", "").lower() == "ok" and row.get("termination_condition", "").lower() == "optimal" for row in artifact["models"]), len(artifact["models"]), 14),
        ("all_child_validation_checks_pass", all(row.get("status") == "pass" for row in artifact["validation"]), sum(row.get("status") != "pass" for row in artifact["validation"]), 0),
        ("both_configurations_execute_168_hours", all(row["executed_hours"] == 168 for row in metrics), min(row["executed_hours"] for row in metrics), 168),
        ("production_positive_both_configurations", all(row["final_product_t"] > 0.0 for row in metrics), min(row["final_product_t"] for row in metrics), 0.0),
        ("no_export_preserved", abs(sum(row["gross_grid_export_mwh"] for row in metrics)) <= tol, sum(row["gross_grid_export_mwh"] for row in metrics), 0.0),
        ("carrier_balances_close", max(abs(_float(row, field)) for row in rows for field in ("BFG_balance_residual_mwh", "COG_balance_residual_mwh", "BOFG_balance_residual_mwh", "generator_fuel_identity_residual_mwh")) <= tol, max(abs(_float(row, field)) for row in rows for field in ("BFG_balance_residual_mwh", "COG_balance_residual_mwh", "BOFG_balance_residual_mwh", "generator_fuel_identity_residual_mwh")), tol),
        ("steam_unserved_zero", max(row["steam_unserved_t"] for row in metrics) <= tol, max(row["steam_unserved_t"] for row in metrics), tol),
        ("c0_hsm_pefa_wag_supplied", all(float(row["wag_supply_mwh"]) > 0.0 and abs(float(row["ng_supply_mwh"])) <= tol for row in heat_rows), min(float(row["wag_supply_mwh"]) for row in heat_rows), 0.0),
        ("c1_dri_ng_intensity_source_locked", c1_metric["dri_ng_gj_lhv_per_t"] is not None and abs(float(c1_metric["dri_ng_gj_lhv_per_t"]) - float(gates["dri_ng_intensity_gj_lhv_per_t"])) <= float(gates["dri_ng_intensity_tolerance_gj_per_t"]), c1_metric["dri_ng_gj_lhv_per_t"], float(gates["dri_ng_intensity_gj_lhv_per_t"])),
        ("dri_inventory_change_price_direction_positive", dri_direction is not None and dri_direction > 0.0, dri_direction, 0.0),
        ("c0_wag_generator_active", _sum(c0_rows, "WAG_generator_electricity_mwh") > 0.0, _sum(c0_rows, "WAG_generator_electricity_mwh"), 0.0),
        ("legacy_fixed_ng_excluded_from_phase5e_total", all(row["legacy_fixed_component_included_in_phase5e_total"] is False for row in metrics), sum(bool(row["legacy_fixed_component_included_in_phase5e_total"]) for row in metrics), 0),
    ]
    return (
        metrics,
        heat_rows,
        [
            {
                "period_id": period_id,
                "check_id": check_id,
                "status": "pass" if passed else "fail",
                "actual": actual,
                "reference_or_limit": reference,
            }
            for check_id, passed, actual, reference in checks
        ],
    )


def _run_dynamic_case(
    phase: Mapping[str, Any],
    parent: Mapping[str, Any],
    phase4: Mapping[str, Any],
    target: Mapping[str, Any],
    period: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any]]:
    case_id = f"phase5e__{period['period_id'].replace('-', '_')}__accepted_no_export"
    case = {
        "case_id": case_id,
        "period_id": period["period_id"],
        "dataset_split": period["dataset_split"],
        "forecast_start_origin_utc": period["frozen_forecast_start_origin_utc"],
        "flat_price_eur_per_mwh": None,
        "price_field": "y_pred",
        "perfect_foresight_oracle": False,
        "policy_id": "accepted_no_export_comparator",
        "sale_enabled": False,
    }
    overrides = _case_overrides(
        phase4,
        case,
        _resolve(parent["phase5b"]["forecast_run_root"]),
        int(target["campaign_terminal_executed_hours"]),
        target["terminal_band"],
    )
    overrides.update(
        {
            "run_id": case_id,
            "lineage_role": "phase5e_frozen_no_export_dynamic_child",
            "phase5e_annual_service_accounts_enter_dispatch": False,
            "phase5e_annual_service_accounts_enter_cost": False,
            "phase5e_phase5d_policy_promoted": False,
        }
    )
    scratch = _resolve(phase["scratch_root"])
    directory = scratch / case_id
    if not directory.exists():
        run_closed_loop_feasibility_anchor_reconciliation(
            config_path=_resolve(phase4["phase4"]["physical_config"]),
            output_root=scratch,
            scenario_overrides=overrides,
        )
    return case_id, _artifact(directory)


def run_phase5e(config_path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    started = time.perf_counter()
    config_file = Path(config_path).resolve()
    config = load_config(config_file)
    phase = config["phase5e"]
    if _git_head() != str(phase["expected_parent_head"]):
        raise Phase5ESourceClosureError("Phase 5E requires the preserved Phase-4 HEAD.")
    source_path = _resolve(phase["source_contract"])
    source_card = _resolve(phase["source_card"])
    rows = load_source_contract(source_path)
    gates = phase["gates"]
    comparisons = annual_anchor_comparisons(
        rows, float(gates["primary_anchor_relative_tolerance"])
    )
    coverage = carrier_coverage(
        rows,
        float(gates["minimum_named_share_per_carrier"]),
        float(gates["maximum_unallocated_share_per_carrier"]),
    )
    generator = generator_balances(
        rows,
        gates["secondary_wag_electricity_anchors_twh_y"],
        float(gates["primary_anchor_relative_tolerance"]),
    )
    secondary = secondary_anchor_context(rows, generator)
    static_pass = all(row["status"] == "pass" for row in comparisons + coverage + generator)
    if not static_pass:
        raise Phase5ESourceClosureError("Annual source-accounting gate failed before solving.")

    parent = yaml.safe_load(_resolve(phase["parent_phase5b_config"]).read_text(encoding="utf-8"))
    phase4 = load_phase4_config(_resolve(parent["phase5b"]["phase4_config"]))
    check_phase4_config(phase4)
    targets = {
        row["period_id"]: row
        for row in _read_json(_resolve(parent["phase5b"]["phase4_target_contract"]))["targets"]
    }
    badarinath_rows = _read_csv(_resolve(phase["parent_phase5c_badarinath"]))
    output = _resolve(config["output_root"])
    scratch = _resolve(phase["scratch_root"])
    if output.exists():
        raise Phase5ESourceClosureError("Phase 5E governed output root already exists.")
    if _select_solver()[1] is None:
        raise Phase5ESourceClosureError("Gurobi is unavailable before the first solve.")
    install_terminal_validation_extension()
    output.mkdir(parents=True)
    scratch.mkdir(parents=True, exist_ok=True)
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    dynamic_metrics: list[dict[str, Any]] = []
    dynamic_checks: list[dict[str, Any]] = []
    heat_rows: list[dict[str, Any]] = []
    dynamic_service_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    for index, period in enumerate(phase["periods"]):
        if index == 1 and any(row["status"] != "pass" for row in dynamic_checks):
            case_rows.append(
                {
                    "period_id": period["period_id"],
                    "status": "not_started_february_gate_failed",
                }
            )
            break
        case_id, artifact = _run_dynamic_case(
            phase, parent, phase4, targets[period["period_id"]], period
        )
        metrics, heat, checks = dynamic_period_checks(
            period["period_id"], artifact, gates, badarinath_rows, rows
        )
        dynamic_metrics.extend(metrics)
        heat_rows.extend(heat)
        dynamic_service_rows.extend(
            dynamic_source_service_accounts(period["period_id"], artifact, rows)
        )
        dynamic_checks.extend(checks)
        case_rows.append(
            {
                "period_id": period["period_id"],
                "case_id": case_id,
                "status": "pass" if all(row["status"] == "pass" for row in checks) else "fail",
                "model_count": len(artifact["models"]),
            }
        )

    dynamic_pass = (
        len(case_rows) == 2
        and all(row["status"] == "pass" for row in case_rows)
        and all(row["status"] == "pass" for row in dynamic_checks)
    )
    passed = static_pass and dynamic_pass
    decision = (
        "phase5e_source_backed_annual_closure_pass_dynamic_development_pair_pass_hold_phase6_for_frozen_held_out"
        if passed
        else "phase5e_failed_retain_no_export_source_driven_baseline"
    )

    _write_csv(output / "source_backed_service_ledger.csv", rows)
    _write_csv(output / "annual_anchor_comparison.csv", comparisons)
    _write_csv(output / "carrier_coverage.csv", coverage)
    _write_csv(output / "generator_balance.csv", generator)
    _write_csv(output / "secondary_anchor_context.csv", secondary)
    _write_csv(output / "dynamic_case_status.csv", case_rows)
    _write_csv(output / "dynamic_period_metrics.csv", dynamic_metrics)
    _write_csv(output / "dynamic_period_checks.csv", dynamic_checks)
    _write_csv(output / "dynamic_source_service_accounting.csv", dynamic_service_rows)
    _write_csv(output / "heat_demand_supply_verification.csv", heat_rows)
    _write_csv(
        output / "source_adjudication.csv",
        [
            {
                "quantity": "C0 natural gas",
                "former_value": 9.666,
                "former_unit": "PJ_LHV/y",
                "phase5e_primary_value": 12.5,
                "phase5e_unit": "PJ/y MER table convention",
                "decision": "former comparison superseded as primary",
                "reason": "exact official 2025 MER locator and complete category split now available",
            },
            {
                "quantity": "C1 natural gas",
                "former_value": 47.566,
                "former_unit": "PJ_LHV/y Athanasiadis context",
                "phase5e_primary_value": 46.7,
                "phase5e_unit": "PJ/y MER table convention",
                "decision": "MER primary; Athanasiadis secondary",
                "reason": "configuration-matched official site balance outranks model precedent",
            },
            {
                "quantity": "coal",
                "former_value": 3.66,
                "former_unit": "Mt/y definition unresolved",
                "phase5e_primary_value": 120.8,
                "phase5e_unit": "PJ/y C0; 58.0 PJ/y C1",
                "decision": "mass comparison not comparable; no coefficient change",
                "reason": "MER primary anchor is all-coal energy and the old mass categories are not proven equivalent",
            },
        ],
    )
    manifest = {
        "config": {"path": _portable(config_file), "sha256": _sha256(config_file)},
        "source_contract": {"path": _portable(source_path), "sha256": _sha256(source_path)},
        "source_card": {"path": _portable(source_card), "sha256": _sha256(source_card)},
        "parent_phase5b_config": {
            "path": phase["parent_phase5b_config"],
            "sha256": _sha256(_resolve(phase["parent_phase5b_config"])),
        },
        "parent_badarinath_evidence": {
            "path": phase["parent_phase5c_badarinath"],
            "sha256": _sha256(_resolve(phase["parent_phase5c_badarinath"])),
        },
        "annual_service_accounts_enter_dispatch": False,
        "annual_service_accounts_enter_cost": False,
    }
    _write_json(output / "input_manifest.json", manifest)
    _write_json(
        output / "code_version.json",
        {
            "git_head": _git_head(),
            "dirty_worktree_expected": True,
            "runner": _portable(Path(__file__).resolve()),
            "implementation_sha256": _sha256(Path(__file__).resolve()),
        },
    )
    wall_time = time.perf_counter() - started
    checkpoint = {
        "run_id": RUN_ID,
        "status": "pass" if passed else "fail",
        "decision": decision,
        "annual_primary_anchor_gate_pass": static_pass,
        "carrier_coverage_gate_pass": all(row["status"] == "pass" for row in coverage),
        "generator_balance_gate_pass": all(row["status"] == "pass" for row in generator),
        "february_dynamic_gate_pass": any(row["period_id"] == EXPECTED_PERIODS[0] and row["status"] == "pass" for row in case_rows),
        "july_started": any(row["period_id"] == EXPECTED_PERIODS[1] and row["status"] != "not_started_february_gate_failed" for row in case_rows),
        "july_dynamic_gate_pass": any(row["period_id"] == EXPECTED_PERIODS[1] and row["status"] == "pass" for row in case_rows),
        "phase5d_policy_promoted": False,
        "phase6_design_authorized": passed,
        "phase6_execution_authorized": False,
        "held_out_validation_required": True,
        "wall_time_seconds": round(wall_time, 3),
    }
    _write_json(output / "checkpoint_decision.json", checkpoint)
    _write_json(
        output / "run_summary.json",
        {
            **checkpoint,
            "primary_anchor_count": len(comparisons),
            "primary_anchor_failure_count": sum(row["status"] != "pass" for row in comparisons),
            "coverage_failure_count": sum(row["status"] != "pass" for row in coverage),
            "dynamic_check_count": len(dynamic_checks),
            "dynamic_failure_count": sum(row["status"] != "pass" for row in dynamic_checks),
            "case_count": len(case_rows),
            "source_contract_sha256": _sha256(source_path),
            "methodological_boundary": "annual source-backed services plus unchanged no-export dynamic solver",
        },
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": RUN_ID,
            "status": checkpoint["status"],
            "lineage_role": config["lineage_role"],
            "output_policy": config["output_policy"],
            "decision": decision,
        },
    )
    (output / "README.md").write_text(
        "# Phase 5E source-backed anchor closure\n\n"
        f"Decision: `{decision}`.\n\n"
        "The official 2025 MER annual categories replace anonymous residual interpretation. "
        "They are reporting-only service accounts and do not enter dispatch or cost. The paired "
        "February/July runs use the unchanged no-export physical model.\n",
        encoding="utf-8",
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- Annual MER accounts are rounded configuration balances, not hourly operating profiles.\n"
        "- Named annual service coverage is not a claim that every service is endogenous.\n"
        "- The electricity boundary remainder is derived only from two independently stated MER totals and never enters dispatch.\n"
        "- Fuel-proportional WAG electricity is a reporting attribution, not a generator constraint.\n"
        "- Coal energy is primary; the older coal-mass comparison remains definition-unresolved.\n"
        "- Scope 1 source classes replace the arbitrary annual bridge but do not make the hourly model ETS-ready.\n"
        "- February and July remain DEVELOPMENT periods; Phase 6 execution requires a frozen held-out run.\n",
        encoding="utf-8",
    )
    return checkpoint


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG_PATH))
    args = parser.parse_args()
    print(json.dumps(run_phase5e(args.config), indent=2))


if __name__ == "__main__":
    main()
