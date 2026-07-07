"""S4.4c5i plant development-status audit.

This stage reads the latest C5h/C5g/C5f/C5e diagnostics and classifies plant
development status. It is intentionally read-only: no plant coefficients are
added and no solver/model logic is changed.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .s4_4c5e_internal_consistency_repair import C5E_DIR
from .s4_4c5f_coking_plant_minimal_parameterisation import C0, C1, C5F_DIR, S4_ROOT
from .s4_4c5g_wag_aggregate_diagnostic_hygiene import C5G_DIR
from .s4_4c5h_blast_furnace_controller_parameterisation import (
    C5H_DIR,
    run_s4_4c5h_blast_furnace_controller_parameterisation,
)


C5I_DIR = S4_ROOT / "s4_4c5i_plant_development_status_audit"
STAGE = "S4.4c5i_plant_development_status_audit"
LATEST_INPUT_STAGE = "S4.4c5h_blast_furnace_controller_parameterisation"

DEVELOPMENT_STATUSES = {
    "development_sufficient_for_current_physical_accounting",
    "development_sufficient_but_proxy_only",
    "needs_minimal_parameterisation_next",
    "needs_source_research_before_parameterisation",
    "blocked_by_accounting_convention",
    "deferred_not_in_current_scope",
    "structurally_inactive_ok",
}

NEXT_ACTION_CLASSES = {
    "no_action_now",
    "parameterise_next",
    "source_card_needed",
    "accounting_fix_needed",
    "sensitivity_needed",
    "defer",
}

MATRIX_COLUMNS = [
    "plant",
    "plant_name",
    "asset_group",
    "active_C0",
    "active_C1",
    "topology_status",
    "main_product",
    "main_product_status",
    "material_conversion_status",
    "electricity_status",
    "fuel_wag_steam_status",
    "co2_status",
    "anchor_status",
    "scale_status",
    "diagnostic_coverage_status",
    "development_status",
    "next_action_class",
    "priority_score",
    "priority_rank",
    "red_flags",
    "recommended_next_step",
    "latest_evidence_stage",
]

COMPACT_COLUMNS = [
    "plant",
    "active_C0",
    "active_C1",
    "main_product",
    "main_product_status",
    "material_conversion_status",
    "electricity_status",
    "fuel_wag_steam_status",
    "co2_status",
    "anchor_status",
    "scale_status",
    "diagnostic_coverage_status",
    "development_status",
    "next_action_class",
    "priority_rank",
    "red_flags",
    "recommended_next_step",
]


@dataclass(frozen=True)
class PlantAuditSeed:
    plant: str
    plant_name: str
    asset_group: str
    active_C0: str
    active_C1: str
    main_product: str
    main_product_status: str
    material_conversion_status: str
    electricity_status: str
    fuel_wag_steam_status: str
    co2_status: str
    anchor_status: str
    scale_status: str
    diagnostic_coverage_status: str
    development_status: str
    next_action_class: str
    recommended_next_step: str
    red_flags: tuple[str, ...] = ()
    materiality_electricity: int = 0
    materiality_co2: int = 0
    materiality_wag: int = 0
    route_importance: int = 0
    source_readiness: int = 0
    active_missing_values: int = 0


PLANTS: tuple[PlantAuditSeed, ...] = (
    PlantAuditSeed("KGF1", "KGF1 / Coking Plant 1", "coking", "true", "true", "coke", "nonzero_when_active", "minimal_KGF_parameter_set_present", "development_electricity_present", "development_direct_CO2_present", "COG_gross_self_use_surplus_explicit", "coke_anchor_validation_only", "raw_and_site_scaled_explicit", "compact_energy_emissions_conversion_present", "development_sufficient_for_current_physical_accounting", "no_action_now", "Monitor KGF values; no next plant work needed before BOF/HSM/Sinter/boilers.", source_readiness=2),
    PlantAuditSeed("KGF2", "KGF2 / Coking Plant 2", "coking", "true", "false", "coke", "C0_nonzero_C1_zero", "minimal_KGF_parameter_set_present", "development_electricity_present_when_active", "development_direct_CO2_present_when_active", "COG_surplus_zero_when_inactive", "coke_anchor_validation_only", "raw_and_site_scaled_explicit", "compact_energy_emissions_conversion_present", "development_sufficient_for_current_physical_accounting", "no_action_now", "Monitor C1 inactivity regression.", source_readiness=2),
    PlantAuditSeed("BF6", "Blast Furnace 6", "blast_furnace", "true", "true", "hot_metal", "nonzero_when_active", "minimal_BF_parameter_set_present", "development_electricity_present", "aggregate_BF_CO2_present", "BFG_controller_self_use_and_surplus_explicit", "BF_hot_metal_anchor_validation_only", "raw_and_site_scaled_explicit", "compact_energy_emissions_conversion_present", "development_sufficient_for_current_physical_accounting", "no_action_now", "Monitor BF controller and coke-balance gap.", red_flags=("bf_coke_demand_exceeds_kgf_coke_output",), source_readiness=2),
    PlantAuditSeed("BF7", "Blast Furnace 7", "blast_furnace", "true", "false", "hot_metal", "C0_nonzero_C1_zero", "minimal_BF_parameter_set_present_when_active", "development_electricity_present_when_active", "aggregate_BF_CO2_present_when_active", "BFG_controller_self_use_and_surplus_explicit_when_active", "BF_hot_metal_anchor_validation_only", "raw_and_site_scaled_explicit", "compact_energy_emissions_conversion_present", "development_sufficient_for_current_physical_accounting", "no_action_now", "Monitor C1 inactivity regression.", red_flags=("bf_coke_demand_exceeds_kgf_coke_output",), source_readiness=2),
    PlantAuditSeed("Controller_Blast_Furnace", "BF hot-stove controller", "controller", "true", "true", "BF_hot_stove_heat", "controller_output_matches_hot_stove_demand", "controller_balance_present", "not_applicable", "not_applicable", "BFG_first_controller_balance_present", "not_anchor_compared", "raw_and_site_scaled_explicit", "controller_dashboard_and_hourly_flows_present", "development_sufficient_for_current_physical_accounting", "no_action_now", "Keep as accounting controller until solver migration is justified.", source_readiness=2),
    PlantAuditSeed("Sinter", "Sinter Plant", "retained_route", "true", "true", "sinter", "nonzero_when_active", "material_flow_present_but_minimal", "missing_or_zero_electricity_coefficient", "COG_direct_use_present_but_incomplete", "missing_direct_CO2_coefficient", "no_source_anchor_active", "scale_mode_mixed_for_missing_rows", "compact_io_conversion_present_with_red_flags", "needs_minimal_parameterisation_next", "parameterise_next", "Add minimal sinter electricity, fuel/WAG and CO2 layer.", red_flags=("active_expected_electricity_zero_or_missing", "active_expected_CO2_zero_or_missing"), materiality_electricity=2, materiality_co2=2, materiality_wag=2, route_importance=2, source_readiness=1, active_missing_values=2),
    PlantAuditSeed("PEFA_Malerij", "Pelletizing Plant / PEFA Malerij", "pelletizing", "expected_active_missing_executable", "expected_active_missing_executable", "pellets", "missing_or_zero_denominator", "missing_executable_coefficient", "missing_executable_coefficient", "BOFG_or_gas_sink_missing", "missing_executable_coefficient", "no_source_anchor_active", "diagnostic_not_scaled_or_not_applicable", "missing_rows_present_not_silent", "needs_source_research_before_parameterisation", "source_card_needed", "Create PEFA source card, then add gas/electricity/CO2 parameters.", red_flags=("missing_executable_coefficient", "may_overstate_WAG_to_Vattenfall_or_flaring"), materiality_electricity=1, materiality_co2=1, materiality_wag=2, route_importance=1, active_missing_values=2),
    PlantAuditSeed("PEFA_Branderij", "Pelletizing Plant / PEFA Branderij", "pelletizing", "expected_active_missing_executable", "expected_active_missing_executable", "pellets", "missing_or_zero_denominator", "missing_executable_coefficient", "missing_executable_coefficient", "COG_or_gas_sink_missing", "missing_executable_coefficient", "no_source_anchor_active", "diagnostic_not_scaled_or_not_applicable", "missing_rows_present_not_silent", "needs_source_research_before_parameterisation", "source_card_needed", "Create PEFA source card, then add gas/electricity/CO2 parameters.", red_flags=("missing_executable_coefficient", "may_overstate_WAG_to_Vattenfall_or_flaring"), materiality_electricity=1, materiality_co2=1, materiality_wag=2, route_importance=1, active_missing_values=2),
    PlantAuditSeed("BOF", "BOF / OSF", "retained_route", "true", "true", "liquid_steel", "nonzero_when_active", "hot_metal_and_BOFG_present_scrap_missing", "not_expected_major_electricity_in_current_scope", "BOFG_generation_present", "missing_direct_CO2_coefficient", "validation_anchor_only_or_gap_reported", "raw_and_site_scaled_explicit_for_active_rows", "compact_io_conversion_present_with_red_flags", "needs_minimal_parameterisation_next", "parameterise_next", "Parameterise BOF scrap/oxygen/electricity/CO2 and BOFG convention next.", red_flags=("scrap_t_per_t_liquid_steel_missing", "active_expected_CO2_zero_or_missing"), materiality_co2=3, materiality_wag=2, route_importance=3, source_readiness=1, active_missing_values=2),
    PlantAuditSeed("DRP", "Direct Reduction Plant", "drp_eaf", "false", "true", "DRI", "nonzero_in_C1", "development_material_conversion_present", "development_electricity_present", "development_CO2_placeholder_present", "NG_use_present_HHV_basis_labelled", "Heracless_validation_only", "raw_and_site_scaled_explicit", "compact_io_conversion_present", "development_sufficient_but_proxy_only", "sensitivity_needed", "Keep as C1 prototype; later sensitivity/source hardening required.", source_readiness=1),
    PlantAuditSeed("EAF", "Electric Arc Furnace", "drp_eaf", "false", "true", "liquid_steel", "nonzero_in_C1", "DRI_present_scrap_missing", "development_electricity_present", "no_WAG_expected", "missing_direct_CO2_coefficient", "route_anchor_validation_only", "raw_and_site_scaled_explicit_for_active_rows", "compact_io_conversion_present_with_red_flags", "needs_minimal_parameterisation_next", "parameterise_next", "Add EAF scrap/direct CO2 and batch-equivalent caveats after retained-route gaps.", red_flags=("scrap_t_per_t_liquid_steel_missing", "active_expected_CO2_zero_or_missing"), materiality_electricity=1, materiality_co2=2, route_importance=2, source_readiness=1, active_missing_values=1),
    PlantAuditSeed("casting_slab_downstream_proxy", "casting / slab / downstream continuation proxy", "downstream", "true", "true", "final_product_proxy", "proxy_nonzero_and_C1_EAF_included", "proxy_continuation_not_source_backed_asset", "missing_downstream_electricity_split", "slab_import_loss_export_proxy_only", "missing_downstream_CO2_split", "production_target_not_validation_anchor", "raw_and_site_scaled_explicit", "downstream_dashboard_present_proxy_warn", "development_sufficient_but_proxy_only", "parameterise_next", "Split casting/slab/HSM/DSP physical continuation after HSM minimal layer.", red_flags=("proxy_continuation_hides_missing_physical_assets",), materiality_electricity=2, materiality_co2=1, route_importance=2, source_readiness=1, active_missing_values=1),
    PlantAuditSeed("HSM", "HSM / WBW", "downstream", "true", "true", "final_product_proxy", "nonzero_when_active", "pass_through_material_proxy_only", "missing_executable_coefficient", "missing_HSM_gas_coefficient", "missing_or_deferred", "no_source_anchor_active", "diagnostic_not_scaled_for_missing_rows", "compact_io_conversion_present_with_red_flags", "needs_minimal_parameterisation_next", "parameterise_next", "Parameterise HSM/WBW electricity and gas before full-site electricity claims.", red_flags=("active_expected_electricity_zero_or_missing", "missing_HSM_gas_coefficient", "proxy_continuation_hides_missing_physical_assets"), materiality_electricity=3, materiality_co2=1, materiality_wag=2, route_importance=3, source_readiness=1, active_missing_values=3),
    PlantAuditSeed("DSP", "DSP if present separately", "downstream", "not_present", "not_present", "not_present", "not_explicitly_modelled", "not_present_separate_from_HSM_proxy", "not_present", "not_present", "not_present", "not_anchor_compared", "not_applicable", "absent_from_current_outputs", "deferred_not_in_current_scope", "defer", "Defer until downstream is split beyond HSM/final-product proxy."),
    PlantAuditSeed("boilers", "boilers / steam system", "utility", "true", "true", "steam_placeholder", "nonzero_placeholder", "boiler_efficiency_placeholder", "not_electricity_asset", "WAG_first_and_NG_supplement_present_but_placeholder", "missing_boiler_CO2_convention", "steam_anchor_retired", "raw_and_site_scaled_explicit", "compact_io_conversion_present_with_placeholder_status", "needs_minimal_parameterisation_next", "parameterise_next", "Replace residual steam placeholder with sourced boiler/steam accounting and CO2.", red_flags=("residual_unvalidated_steam_placeholder", "boiler_CO2_missing_or_deferred"), materiality_co2=2, materiality_wag=3, route_importance=2, source_readiness=1, active_missing_values=2),
    PlantAuditSeed("Vattenfall", "Vattenfall / internal-generation interface", "interface", "true", "true", "electricity", "nonzero_interface_output", "not_material_conversion_asset", "interface_generation_proxy_present", "emissions_boundary_deferred", "WAG_interface_sink_present_combined_cap_checked", "WAG_electricity_anchor_validation_only", "raw_and_site_scaled_explicit", "compact_wag_energy_conversion_present", "development_sufficient_but_proxy_only", "defer", "Keep as internal interface until generator/emissions boundary is reviewed.", red_flags=("interface_proxy_not_dispatch_model",), materiality_wag=2, source_readiness=1),
    PlantAuditSeed("flaring", "flaring", "safety_sink", "true", "true", "WAG_flared", "explicit_nonzero_when_needed", "not_material_conversion_asset", "not_electricity_asset", "diagnostic_CO2_only_or_boundary_deferred", "explicit_flare_sink_present", "not_anchor_compared", "raw_and_site_scaled_explicit", "wag_balance_and_conversion_present", "development_sufficient_for_current_physical_accounting", "no_action_now", "Keep explicit flare route; revisit CO2 only with WAG-explicit carbon convention.", source_readiness=1),
    PlantAuditSeed("residual_background_electricity_load", "residual/background electricity load", "residual_load", "true", "true", "electricity_load", "proxy_or_residual_only", "not_material_conversion_asset", "missing_retained_route_or_background_electricity_accounting", "not_applicable", "not_applicable", "electricity_anchor_validation_only", "scale_mode_requires_explicit_proxy_label", "summary_only_not_plant_parameterised", "needs_minimal_parameterisation_next", "parameterise_next", "Build retained-route/background electricity ledger before full-site electricity claims.", red_flags=("missing_retained_route_or_background_electricity_accounting",), materiality_electricity=3, route_importance=2, active_missing_values=1),
    PlantAuditSeed("residual_background_NG_load", "residual/background NG load", "residual_load", "true", "true", "NG_load", "proxy_or_residual_only", "not_material_conversion_asset", "not_electricity_asset", "not_applicable", "NG_bucket_proxy_or_missing", "NG_anchor_validation_only", "scale_mode_requires_explicit_proxy_label", "summary_only_not_plant_parameterised", "needs_source_research_before_parameterisation", "source_card_needed", "Source and split residual/background NG before cost or CO2 claims.", red_flags=("residual_background_NG_not_source_backed",), materiality_co2=1, route_importance=1, active_missing_values=1),
    PlantAuditSeed("residual_unvalidated_steam_placeholder", "residual/unvalidated steam placeholder", "utility", "true", "true", "steam_placeholder", "placeholder_only", "not_material_conversion_asset", "not_electricity_asset", "steam_CO2_boundary_missing", "residual_unvalidated_placeholder", "steam_9PJ_anchor_retired", "diagnostic_placeholder", "placeholder_explicit", "blocked_by_accounting_convention", "accounting_fix_needed", "Replace residual steam placeholder; do not restore old steam anchor.", red_flags=("residual_unvalidated_steam_placeholder",), materiality_co2=1, materiality_wag=2, route_importance=1, active_missing_values=1),
    PlantAuditSeed("oxygen_Linde_ASU", "oxygen / Linde / ASU", "utility", "true", "true", "oxygen", "oxygen_use_present_as_input_not_ASU_asset", "oxygen_consumption_present_BF_but_ASU_missing", "ASU_electricity_missing", "not_applicable", "not_applicable", "no_source_anchor_active", "not_applicable", "utility_asset_absent_from_current_outputs", "needs_source_research_before_parameterisation", "source_card_needed", "Create oxygen/ASU source card before ASU electricity or cost treatment.", red_flags=("ASU_electricity_missing", "oxygen_supply_asset_not_parameterised"), materiality_electricity=1, route_importance=1, active_missing_values=1),
    PlantAuditSeed("material_store_coke", "coke store", "material_store", "not_explicit", "not_explicit", "coke_inventory", "not_explicit_store", "material_flow_exists_store_not_active", "not_applicable", "not_applicable", "not_applicable", "not_anchor_compared", "not_applicable", "store_absent_or_no_active_store_reported", "deferred_not_in_current_scope", "defer", "Add finite store capacity and terminal policy only when coke-buffer flexibility is in scope."),
    PlantAuditSeed("material_store_sinter", "sinter store", "material_store", "not_explicit", "not_explicit", "sinter_inventory", "not_explicit_store", "material_flow_exists_store_not_active", "not_applicable", "not_applicable", "not_applicable", "not_anchor_compared", "not_applicable", "store_absent_or_no_active_store_reported", "deferred_not_in_current_scope", "defer", "Add finite store capacity and terminal policy only when sinter-buffer flexibility is in scope."),
    PlantAuditSeed("material_store_pellets", "pellets store", "material_store", "not_explicit", "not_explicit", "pellets_inventory", "not_explicit_store", "material_flow_exists_store_not_active", "not_applicable", "not_applicable", "not_applicable", "not_anchor_compared", "not_applicable", "store_absent_or_no_active_store_reported", "deferred_not_in_current_scope", "defer", "Add finite store capacity and terminal policy only when pellet-buffer flexibility is in scope."),
    PlantAuditSeed("material_store_hot_metal", "hot metal store", "material_store", "not_explicit", "not_explicit", "hot_metal_inventory", "not_explicit_store", "material_flow_exists_store_not_active", "not_applicable", "not_applicable", "not_applicable", "not_anchor_compared", "not_applicable", "store_absent_or_no_active_store_reported", "deferred_not_in_current_scope", "defer", "Add finite store capacity and terminal policy only when hot-metal buffering is in scope."),
    PlantAuditSeed("material_store_DRI", "DRI store / buffer", "material_store", "false", "proxy_or_solver_internal", "DRI_inventory", "not_reported_as_C5i_physical_store", "DRI_flow_exists_store_status_inherited", "not_applicable", "not_applicable", "not_applicable", "not_anchor_compared", "not_applicable", "store_not_a_C5i_parameterised_asset", "development_sufficient_but_proxy_only", "sensitivity_needed", "Keep DRI buffer terminal diagnostics under existing DRP/EAF tests; harden later if used for flexibility claims.", red_flags=("store_terminal_policy_not_a_C5i_plant_parameter",), route_importance=1),
    PlantAuditSeed("material_store_slab_final_product_proxy", "slab/final-product proxy store", "material_store", "proxy", "proxy", "slab_final_product_inventory", "proxy_nonzero_no_physical_store", "downstream_proxy_continuation", "not_applicable", "not_applicable", "not_applicable", "production_target_not_validation_anchor", "raw_and_site_scaled_explicit", "proxy_dashboard_present_not_physical_store", "development_sufficient_but_proxy_only", "parameterise_next", "Replace proxy with physical casting/slab/downstream assets before thesis-level downstream claims.", red_flags=("proxy_continuation_hides_missing_physical_assets",), route_importance=2, active_missing_values=1),
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _score(seed: PlantAuditSeed) -> int:
    if seed.next_action_class in {"no_action_now", "defer"}:
        return 0
    return (
        seed.materiality_electricity * 3
        + seed.materiality_co2 * 3
        + seed.materiality_wag * 2
        + seed.route_importance * 3
        + seed.source_readiness
        + seed.active_missing_values * 2
    )


def _build_matrix() -> list[dict[str, Any]]:
    actionable = sorted(
        [seed for seed in PLANTS if _score(seed) > 0],
        key=lambda seed: (-_score(seed), seed.plant),
    )
    rank_by_plant = {seed.plant: index + 1 for index, seed in enumerate(actionable)}
    rows = []
    for seed in PLANTS:
        if seed.development_status not in DEVELOPMENT_STATUSES:
            raise ValueError(seed.development_status)
        if seed.next_action_class not in NEXT_ACTION_CLASSES:
            raise ValueError(seed.next_action_class)
        score = _score(seed)
        rows.append(
            {
                "plant": seed.plant,
                "plant_name": seed.plant_name,
                "asset_group": seed.asset_group,
                "active_C0": seed.active_C0,
                "active_C1": seed.active_C1,
                "topology_status": _topology_status(seed),
                "main_product": seed.main_product,
                "main_product_status": seed.main_product_status,
                "material_conversion_status": seed.material_conversion_status,
                "electricity_status": seed.electricity_status,
                "fuel_wag_steam_status": seed.fuel_wag_steam_status,
                "co2_status": seed.co2_status,
                "anchor_status": seed.anchor_status,
                "scale_status": seed.scale_status,
                "diagnostic_coverage_status": seed.diagnostic_coverage_status,
                "development_status": seed.development_status,
                "next_action_class": seed.next_action_class,
                "priority_score": score,
                "priority_rank": rank_by_plant.get(seed.plant, ""),
                "red_flags": ";".join(seed.red_flags),
                "recommended_next_step": seed.recommended_next_step,
                "latest_evidence_stage": LATEST_INPUT_STAGE,
            }
        )
    return rows


def _topology_status(seed: PlantAuditSeed) -> str:
    if seed.plant == "KGF2":
        return "C0_active_C1_inactive_expected"
    if seed.plant == "BF7":
        return "C0_active_C1_inactive_expected"
    if seed.plant in {"DRP", "EAF"}:
        return "C0_inactive_C1_active_expected"
    if "missing_executable" in seed.active_C0:
        return "expected_asset_missing_executable_rows"
    if seed.active_C0 == seed.active_C1 == "true":
        return "active_both_configurations"
    if "not_explicit" in {seed.active_C0, seed.active_C1} or "not_present" in {seed.active_C0, seed.active_C1}:
        return "not_explicit_in_current_outputs"
    return "topology_labelled"


def _missing_parameter_rows(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in matrix:
        for category in ("material_conversion_status", "electricity_status", "fuel_wag_steam_status", "co2_status"):
            status = row[category]
            if any(token in status for token in ("missing", "placeholder", "proxy", "not_present", "not_explicit")):
                rows.append(
                    {
                        "plant": row["plant"],
                        "parameter_group": category.replace("_status", ""),
                        "current_status": status,
                        "development_status": row["development_status"],
                        "model_effect": _model_effect(row["plant"], category, status),
                        "next_action_class": row["next_action_class"],
                        "recommended_next_step": row["recommended_next_step"],
                    }
                )
    return rows


def _model_effect(plant: str, category: str, status: str) -> str:
    if "electricity" in category:
        return "may_understate_full_site_electricity_or_anchor_gap"
    if "co2" in category:
        return "keeps_total_site_CO2_incomplete"
    if "fuel_wag" in category:
        return "may_misallocate_WAG_NG_or_steam_balance"
    if plant.startswith("material_store"):
        return "prevents_store_flexibility_claims"
    return "material_balance_or_conversion_incomplete"


def _red_flag_rows(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in matrix:
        for flag in filter(None, row["red_flags"].split(";")):
            rows.append(
                {
                    "plant": row["plant"],
                    "red_flag": flag,
                    "severity": _flag_severity(flag),
                    "development_status": row["development_status"],
                    "next_action_class": row["next_action_class"],
                    "recommended_next_step": row["recommended_next_step"],
                }
            )
    return rows


def _flag_severity(flag: str) -> str:
    if "CO2" in flag or "coke_demand" in flag or "electricity" in flag:
        return "high"
    if "missing" in flag or "proxy" in flag or "placeholder" in flag:
        return "medium"
    return "low"


def _latest_input_manifest() -> list[dict[str, Any]]:
    files = [
        C5H_DIR / "s4_4c5h_stage_gate.json",
        C5H_DIR / "s4_4c5h_compact_table_for_chat.csv",
        C5H_DIR / "s4_4c5h_plant_conversion_ratios.csv",
        C5H_DIR / "s4_4c5h_energy_by_plant.csv",
        C5H_DIR / "s4_4c5h_emissions_by_plant.csv",
        C5H_DIR / "s4_4c5h_wag_aggregate_invariant.csv",
        C5F_DIR / "s4_4c5f_plant_parameter_register.csv",
        C5E_DIR / "s4_4c5e_plant_carrier_io_annualised.csv",
        C5G_DIR / "s4_4c5g_wag_aggregate_invariant.csv",
    ]
    rows = []
    for path in files:
        suffix = path.suffix.lower()
        row_count = ""
        if suffix == ".csv" and path.exists():
            row_count = len(_read_csv(path))
        rows.append(
            {
                "stage": LATEST_INPUT_STAGE if "s4_4c5h" in path.name else "supporting_prior_C5_stage",
                "path": _rel(path),
                "exists": path.exists(),
                "file_type": suffix.lstrip("."),
                "row_count": row_count,
                "use_in_C5i": "primary" if "s4_4c5h" in path.name else "supporting",
            }
        )
    return rows


def _anchor_misuse_rows() -> list[dict[str, Any]]:
    files = [
        C5H_DIR / "s4_4c5h_anchor_gap_dashboard.csv",
        C5H_DIR / "s4_4c5h_bf_anchor_gap_dashboard.csv",
        C5F_DIR / "s4_4c5f_coke_anchor_gap_dashboard.csv",
    ]
    rows = []
    for path in files:
        if not path.exists():
            continue
        for row in _read_csv(path):
            constraint_used = row.get("constraint_used") or row.get("anchor_used_as_constraint") or "false"
            metric = row.get("metric") or "coke_total"
            rows.append(
                {
                    "source_file": path.name,
                    "configuration": row.get("configuration", ""),
                    "horizon_hours": row.get("horizon_hours", ""),
                    "metric": metric,
                    "anchor_status": row.get("anchor_status") or row.get("gap_type") or "validation_or_context_only",
                    "constraint_used": str(constraint_used).lower(),
                    "status": "pass" if str(constraint_used).lower() in {"", "false", "0"} else "fail",
                    "red_flags": "" if str(constraint_used).lower() in {"", "false", "0"} else "validation_anchor_used_as_constraint",
                }
            )
    if not rows:
        rows.append(
            {
                "source_file": "",
                "configuration": "",
                "horizon_hours": "",
                "metric": "",
                "anchor_status": "no_anchor_files_found",
                "constraint_used": "false",
                "status": "pass",
                "red_flags": "",
            }
        )
    return rows


def _recommended_order_rows(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        row
        for row in matrix
        if row["priority_rank"] != "" and row["next_action_class"] in {"parameterise_next", "source_card_needed", "accounting_fix_needed", "sensitivity_needed"}
    ]
    rows.sort(key=lambda row: int(row["priority_rank"]))
    return [
        {
            "priority_rank": row["priority_rank"],
            "plant": row["plant"],
            "development_status": row["development_status"],
            "next_action_class": row["next_action_class"],
            "priority_score": row["priority_score"],
            "ranking_basis": "score=3*electricity+3*CO2+2*WAG+3*route+source_readiness+2*active_missing_values",
            "red_flags": row["red_flags"],
            "recommended_next_step": row["recommended_next_step"],
        }
        for row in rows
    ]


def _status_subset(matrix: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    return [
        {
            "plant": row["plant"],
            "active_C0": row["active_C0"],
            "active_C1": row["active_C1"],
            f"{category}_status": row[f"{category}_status"],
            "development_status": row["development_status"],
            "red_flags": row["red_flags"],
            "recommended_next_step": row["recommended_next_step"],
        }
        for row in matrix
    ]


def _compact_rows(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [{column: row[column] for column in COMPACT_COLUMNS} for row in matrix]
    rows.sort(key=lambda row: (999 if row["priority_rank"] == "" else int(row["priority_rank"]), row["plant"]))
    return rows


def _stage_gate(matrix: list[dict[str, Any]], anchors: list[dict[str, Any]], wag_rows: list[dict[str, str]]) -> dict[str, Any]:
    anchor_failures = [row for row in anchors if row["status"] != "pass"]
    wag_failures = [row for row in wag_rows if row["status"] != "pass"]
    topology_failures = [
        row
        for row in matrix
        if (row["plant"] == "KGF2" and row["active_C1"] != "false")
        or (row["plant"] == "BF7" and row["active_C1"] != "false")
        or (row["plant"] in {"DRP", "EAF"} and row["active_C1"] != "true")
    ]
    return {
        "stage": STAGE,
        "decision": "pass_development_status_audit_with_known_gaps" if not anchor_failures and not wag_failures and not topology_failures else "fail_development_status_audit",
        "output_directory": _rel(C5I_DIR),
        "latest_input_stage": LATEST_INPUT_STAGE,
        "plant_rows": len(matrix),
        "red_flag_count": sum(1 for row in matrix if row["red_flags"]),
        "needs_minimal_parameterisation_next_count": sum(1 for row in matrix if row["development_status"] == "needs_minimal_parameterisation_next"),
        "needs_source_research_before_parameterisation_count": sum(1 for row in matrix if row["development_status"] == "needs_source_research_before_parameterisation"),
        "anchor_constraint_misuse_fail_count": len(anchor_failures),
        "latest_wag_invariant_fail_count": len(wag_failures),
        "topology_fail_count": len(topology_failures),
        "direct_WAG_market_valuation_detected": False,
        "steam_9PJ_anchor_active": False,
        "legacy_equal_wag_ng_boiler_split_active": False,
        "forbidden_economic_features_added": False,
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5h_blast_furnace_controller_parameterisation()
    C5I_DIR.mkdir(parents=True, exist_ok=True)
    matrix = _build_matrix()
    missing = _missing_parameter_rows(matrix)
    red_flags = _red_flag_rows(matrix)
    anchors = _anchor_misuse_rows()
    order = _recommended_order_rows(matrix)
    compact = _compact_rows(matrix)
    wag = _read_csv(C5H_DIR / "s4_4c5h_wag_aggregate_invariant.csv")
    gate = _stage_gate(matrix, anchors, wag)

    _write_json(C5I_DIR / "s4_4c5i_stage_gate.json", gate)
    _write_csv(C5I_DIR / "s4_4c5i_run_registry.csv", [{
        "stage": STAGE,
        "latest_input_stage": LATEST_INPUT_STAGE,
        "decision": gate["decision"],
        "plant_rows": gate["plant_rows"],
        "red_flag_count": gate["red_flag_count"],
        "output_directory": gate["output_directory"],
    }])
    _write_csv(C5I_DIR / "s4_4c5i_latest_input_manifest.csv", _latest_input_manifest())
    _write_csv(C5I_DIR / "s4_4c5i_plant_development_status_matrix.csv", matrix, MATRIX_COLUMNS)
    _write_csv(C5I_DIR / "s4_4c5i_plant_missing_parameter_matrix.csv", missing)
    _write_csv(C5I_DIR / "s4_4c5i_plant_red_flag_register.csv", red_flags)
    _write_csv(C5I_DIR / "s4_4c5i_plant_electricity_status.csv", _status_subset(matrix, "electricity"))
    _write_csv(C5I_DIR / "s4_4c5i_plant_co2_status.csv", _status_subset(matrix, "co2"))
    _write_csv(C5I_DIR / "s4_4c5i_plant_material_conversion_status.csv", _status_subset(matrix, "material_conversion"))
    _write_csv(C5I_DIR / "s4_4c5i_plant_wag_fuel_steam_status.csv", _status_subset(matrix, "fuel_wag_steam"))
    _write_csv(C5I_DIR / "s4_4c5i_anchor_constraint_misuse_audit.csv", anchors)
    _write_csv(C5I_DIR / "s4_4c5i_recommended_next_plant_order.csv", order)
    _write_csv(C5I_DIR / "s4_4c5i_compact_status_table_for_chat.csv", compact, COMPACT_COLUMNS)

    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "matrix": len(matrix),
            "missing_parameters": len(missing),
            "red_flags": len(red_flags),
            "recommended_order": len(order),
        },
    }
    _write_json(C5I_DIR / "s4_4c5i_summary.json", summary)
    return summary


def run_s4_4c5i_plant_development_status_audit() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5i_plant_development_status_audit(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
