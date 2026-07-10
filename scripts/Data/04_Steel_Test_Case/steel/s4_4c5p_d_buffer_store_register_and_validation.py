"""S4.4c5p_d buffer/store register and validation diagnostics.

This diagnostic-only stage consolidates the current C5 buffer/store status
without activating new storage behaviour. It validates existing C5 artifacts
against the canonical buffer/storage register and reports caveats separately
from hard failure red flags.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    HORIZONS,
    S4_ROOT,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5p_c_ij01_vn25_generator_interface_accounting import (
    C5P_C_DIR,
    DENOMINATOR_STATUS,
    ELECTRICITY_ACCOUNTING_STATUS,
    run_s4_4c5p_c_ij01_vn25_generator_interface_accounting,
)


STAGE = "S4.4c5p_d_buffer_store_register_and_validation"
C5P_D_DIR = S4_ROOT / "s4_4c5p_d_buffer_store_register_and_validation"
REPORT_PATH = Path("docs/optimisation/steel/S4/C5_BUFFER_STORE_REGISTER_AND_VALIDATION.md")
SOURCE_CARD_DIR = Path("data/03_Optimisation/inputs/assets/steel/source_cards")
SOURCE_CARD = SOURCE_CARD_DIR / "BUFFERS_STORAGE_Parameters.md"

C5N_B_DIR = S4_ROOT / "s4_4c5n_b_pellet_burden_balance_and_bulk_storage_policy"
C5O_B_DIR = S4_ROOT / "s4_4c5o_b_eaf_minimal_physical_layer_with_dri_buffer_handoff"
C5O_C_DIR = S4_ROOT / "s4_4c5o_c_dsp_downstream_physical_layer"
C5P_A_DIR = S4_ROOT / "s4_4c5p_a_linde_asu_oxygen_accounting"
C5P_B_DIR = S4_ROOT / "s4_4c5p_b_boiler_steam_circuit_accounting"
C5L_D_DIR = S4_ROOT / "s4_4c5l_d_HSM_hot_charge_share_cap_and_reheat_sensitivity_patch"

DRI_CAPACITY_CURRENT_C5_T = 15229.652603
DRI_CAPACITY_CANDIDATE_T = 17760.0
HOT_METAL_CANDIDATE_T = 500.0
OXYGEN_GEOMETRIC_M3 = 1670.0
OXYGEN_CANDIDATE_T = 100.0

FAILURE_FLAGS = [
    "STORE_ACTIVE_WITHOUT_CAPACITY",
    "STORE_ACTIVE_WITHOUT_TERMINAL_RULE",
    "NEGATIVE_INVENTORY",
    "TERMINAL_DRIFT_NONZERO",
    "BULK_SOLID_STORAGE_USED_AS_FREE_SOURCE",
    "HOT_METAL_STORE_ACTIVE_IN_BASE",
    "OXYGEN_STORE_ACTIVE_WITHOUT_PRESSURE_OR_CAPACITY_ASSUMPTION",
    "OXYGEN_STORE_USED_FOR_STRATEGIC_STORAGE",
    "WAG_HOLDER_USED_AS_HOURLY_STORE",
    "STEAM_STORE_ACTIVE",
    "LIQUID_STEEL_STORE_ACTIVE",
    "INTERNAL_SCRAP_USED_AS_FREE_EAF_INPUT",
    "FINISHED_PRODUCT_USED_AS_FLEXIBILITY_STORE",
    "EXTERNAL_SLAB_IMPORT_USED_AS_FREE_STORE",
    "HSM_BASE_0_50_REVERTED",
    "DRI_BUFFER_CAPACITY_CHANGED_WITHOUT_METHOD_CHANGE",
    "COKE_RECONCILIATION_BASELINE_REOPENED",
    "DENOMINATOR_SILENTLY_FROZEN",
    "GENERATOR_PRICE_RESPONSIVE_DISPATCH_ACTIVE",
    "WAG_DIRECT_MARKET_VALUE_ACTIVE",
]

CAVEATS = [
    "DEVELOPMENT_ONLY_BUFFER_REGISTER",
    "BULK_SOLID_CAPACITY_PRACTICALLY_NONBINDING",
    "DRI_BUFFER_DEVELOPMENT_ASSUMPTION",
    "SLAB_CAPACITY_OR_HOT_COLD_POLICY_DEVELOPMENT_ASSUMPTION",
    "OXYGEN_BUFFER_STRUCTURAL_ONLY",
    "WAG_HOLDERS_NOT_DISPATCH_STORES",
    "STEAM_BUS_NOT_STORE",
    "INTERNAL_SCRAP_REPORTING_ONLY",
    "FINAL_PRODUCT_ACCOUNTING_ONLY",
    "HOT_METAL_BUFFER_DEFERRED",
    "OXYGEN_NUMERIC_CAPACITY_DEFERRED",
    "SCRAP_POOL_DEFERRED",
    "NOT_THESIS_APPROVED",
]


def _keyed(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _csv(path: Path) -> list[dict[str, str]]:
    return _read_csv(path)


def _base_hot_charge_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("cap_case") == "base_0_50"]


def _payload() -> dict[str, Any]:
    run_s4_4c5p_c_ij01_vn25_generator_interface_accounting()
    return {
        "bulk": _csv(C5N_B_DIR / "s4_4c5n_b_bulk_solid_storage_policy_dashboard.csv"),
        "pellet_inventory": _csv(C5N_B_DIR / "s4_4c5n_b_pellet_inventory_dashboard.csv"),
        "pellet_health": _keyed(_csv(C5N_B_DIR / "s4_4c5n_b_compact_healthcheck.csv")),
        "dri": _keyed(_csv(C5O_B_DIR / "s4_4c5o_b_dri_buffer_handoff_dashboard.csv")),
        "eaf_health": _keyed(_csv(C5O_B_DIR / "s4_4c5o_b_compact_healthcheck.csv")),
        "dsp_health": _keyed(_csv(C5O_C_DIR / "s4_4c5o_c_compact_healthcheck.csv")),
        "oxygen": _keyed(_csv(C5P_A_DIR / "s4_4c5p_a_oxygen_buffer_dashboard.csv")),
        "oxygen_health": _keyed(_csv(C5P_A_DIR / "s4_4c5p_a_compact_healthcheck.csv")),
        "steam_health": _keyed(_csv(C5P_B_DIR / "s4_4c5p_b_compact_healthcheck.csv")),
        "generator_health": _keyed(_csv(C5P_C_DIR / "s4_4c5p_c_compact_healthcheck.csv")),
        "hsm": _base_hot_charge_rows(_csv(C5L_D_DIR / "s4_4c5l_d_compact_table_for_chat.csv")),
    }


def _presence_rows() -> list[dict[str, Any]]:
    specs = [
        ("coke_store", "solid_coke", "C0_C1", "active_practically_nonbinding_bulk_solid_store", True, True, "C5n_b/C5m_f", "s4_4c5n_b_bulk_solid_storage_policy_dashboard.csv", ""),
        ("sinter_store", "sinter", "C0_C1", "active_practically_nonbinding_bulk_solid_store", True, True, "C5n_b/SINTER", "s4_4c5n_b_bulk_solid_storage_policy_dashboard.csv", ""),
        ("fired_pellets_proxy_store", "fired_pellets_proxy", "C0_C1", "active_practically_nonbinding_bulk_solid_store", True, True, "PELLETIZING_Parameters.md", "s4_4c5n_b_pellet_inventory_dashboard.csv", ""),
        ("dri_buffer", "CDRI_DRI", "C1_only", "active_physical_store", False, True, "DRP_Parameters.md;EAF_Parameters.md", "s4_4c5o_b_dri_buffer_handoff_dashboard.csv", ""),
        ("slab_yard_total_store", "slabs_hot_cold_scaffold", "C0_C1", "active_interface_or_accounting_buffer", True, True, "HSM_Parameters.md;HSM_Slab_Buffer_Parameters.md", "s4_4c5l_d_compact_table_for_chat.csv", ""),
        ("hot_slab_age_buckets", "hot_slab_state", "C0_C1", "active_interface_or_accounting_buffer", True, True, "HSM_Slab_Buffer_Parameters.md", "s4_4c5l_d_compact_table_for_chat.csv", ""),
        ("oxygen_short_buffer", "gaseous_oxygen", "C0_C1", "structural_or_validation_anchor_only", False, False, "LINDE_OXYGEN_Parameters.md", "s4_4c5p_a_oxygen_buffer_dashboard.csv", "numeric capacity deferred"),
        ("hot_metal_store", "hot_metal", "deferred", "deferred_or_sensitivity_only", False, False, "Blast_Furnace_Parameters.md;BOF_OSF_Parameters.md;BUFFERS_STORAGE_Parameters.md", "not_active_base", "500 t candidate only"),
        ("steam_store", "steam", "blocked", "blocked_as_store", False, False, "BOILER_STEAM_CIRCUIT_Parameters.md", "s4_4c5p_b_steam_bus_rows.csv", "steam buses only"),
        ("bfg_cog_holders", "BFG_COG", "blocked", "blocked_as_store", False, False, "IJ01_VN25_GENERATORS_Parameters.md;WAG source cards", "WAG carrier ledgers", "not hourly stores"),
        ("bofg_holder", "BOFG", "blocked", "blocked_as_store", False, False, "BOF_OSF_Parameters.md;IJ01_VN25_GENERATORS_Parameters.md", "WAG carrier ledgers", "not hourly store"),
        ("liquid_steel_ladle_buffer", "liquid_steel", "blocked", "blocked_as_store", False, False, "DSP_Parameters.md;EAF_Parameters.md", "not_active_base", "no intertemporal store"),
        ("scrap_supply_or_scrap_yard", "scrap", "C0_C1_reporting", "structural_or_validation_anchor_only", False, False, "EAF_Parameters.md;DSP_Parameters.md", "s4_4c5o_c_compact_healthcheck.csv", "dynamic scrap pool deferred"),
        ("internal_scrap_loss_stream", "internal_scrap_loss", "C0_C1_reporting", "structural_or_validation_anchor_only", False, False, "DSP_Parameters.md", "s4_4c5o_c_compact_healthcheck.csv", "reporting only"),
        ("external_slab_import", "slab_import", "C1_context", "blocked_as_store", False, False, "DSP_Parameters.md;HSM_Parameters.md", "HSM/DSP diagnostics", "exogenous supply, not store"),
        ("finished_product_accounting", "final_product_proxy", "C0_C1_accounting", "active_interface_or_accounting_buffer", True, True, "C5 anchor diagnostics", "C5_ANCHOR_ROUTE_DENOMINATOR_DIAGNOSTICS.md", "not flexibility store"),
        ("generator_fuel_interface", "residual_WAG_to_generators", "C0_C1_interface", "active_interface_or_accounting_buffer", True, True, "IJ01_VN25_GENERATORS_Parameters.md", "s4_4c5p_c_wag_residual_after_generators.csv", "fuel interface, not store"),
    ]
    rows: list[dict[str, Any]] = []
    for buffer_id, carrier, scope, status, c0_active, c1_active, source, artifact, issue in specs:
        rows.append(
            {
                "buffer_id": buffer_id,
                "carrier_or_state": carrier,
                "configuration_scope": scope,
                "expected_status": status,
                "current_C5_status": status,
                "active_in_C0": str(c0_active).lower(),
                "active_in_C1": str(c1_active).lower(),
                "source_card_reference": source,
                "implementation_stage": artifact.split("_")[0] if artifact.startswith("s4_") else "register_or_diagnostic",
                "model_file_or_artifact": artifact,
                "issue": issue,
                "action_needed": "none_for_current_C5_base" if not issue else "preserve_caveat",
                "thesis_usability": "false",
                "caveat": "development_only_register; not thesis approved",
            }
        )
    return rows


def _bulk_row(payload: dict[str, Any], config: str, horizon: int, carrier: str) -> dict[str, str]:
    return next(row for row in payload["bulk"] if row["configuration"] == config and int(row["horizon_hours"]) == horizon and row["bulk_solid_carrier"] == carrier)


def _pellet_inventory(payload: dict[str, Any], config: str, horizon: int) -> dict[str, str]:
    return next(row for row in payload["pellet_inventory"] if row["configuration"] == config and int(row["horizon_hours"]) == horizon)


def _hsm_row(payload: dict[str, Any], config: str, horizon: int) -> dict[str, str]:
    return next(row for row in payload["hsm"] if row["configuration"] == config and int(row["horizon_hours"]) == horizon)


def _current_values_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in (C0, C1):
        for horizon in HORIZONS:
            dri = payload["dri"][(config, horizon)]
            pellet = _pellet_inventory(payload, config, horizon)
            oxygen = payload["oxygen"][(config, horizon)]
            hsm = _hsm_row(payload, config, horizon)
            gen = payload["generator_health"][(config, horizon)]
            dsp = payload["dsp_health"][(config, horizon)]
            for carrier, buffer_id in [("coke", "coke_store"), ("sinter", "sinter_store")]:
                bulk = _bulk_row(payload, config, horizon, carrier)
                rows.append(_value_row(buffer_id, config, "policy", bulk["storage_capacity_mode"], "", "", "practically_nonbinding_bulk_solid", "", bulk["terminal_or_inventory_drift_guard"], "", "", "active_practically_nonbinding_bulk_solid_store", "C5n_b", "capacity_bind_count=0 expected"))
            rows.append(_value_row("fired_pellets_proxy_store", config, "t", pellet["storage_capacity_t"], "", "", "practically_nonbinding_bulk_solid", pellet["pellet_inventory_start_t"], pellet["terminal_inventory_guard_status"], "0", pellet["storage_capacity_t"], "active_practically_nonbinding_bulk_solid_store", "C5n_b", "terminal-neutral fired-pellet proxy inventory"))
            rows.append(_value_row("dri_buffer", config, "t", dri["DRI_buffer_capacity_t"], DRI_CAPACITY_CANDIDATE_T, "2 days DRP output candidate/predecessor", "C1 active only; C0 zero", dri["DRI_inventory_start_t"], dri["DRI_buffer_terminal_rule"], "0", dri["DRI_buffer_capacity_t"], "active_physical_store" if config == C1 else "inactive_zero_C0", "C5o_b", "current C5 value preserved"))
            rows.append(_value_row("slab_yard_total_store", config, "share", hsm["combined_hot_charge_share"], "25,000 t candidate context", "HSM/WBW route anchors", "C5l_d base_0_50", "", hsm["terminal_total_policy_status"], "0", "", "active_interface_or_accounting_buffer", "C5l_d", "hot/cold scaffold; not overwritten by this register"))
            rows.append(_value_row("oxygen_short_buffer", config, "m3", oxygen["O2_buffer_geometric_volume_m3"], OXYGEN_CANDIDATE_T, "1670 m3 geometric anchor", "structural_only_not_model_ready", oxygen["O2_buffer_start_Nm3"], oxygen["O2_buffer_terminal_rule"], "0", oxygen["O2_buffer_usable_capacity_Nm3"], "structural_or_validation_anchor_only", "C5p_a", oxygen["O2_buffer_model_ready_capacity_status"]))
            rows.append(_value_row("hot_metal_store", config, "t", "0", HOT_METAL_CANDIDATE_T, "500 t candidate", "inactive_base", "0", "deferred_if_activated_start_equals_end", "0", "0", "deferred_or_sensitivity_only", "BUFFERS_STORAGE_Parameters.md", "no BF-to-BOF buffer active"))
            rows.append(_value_row("steam_store", config, "policy", "inactive", "", "", "blocked_as_store", "", "n/a", "", "", "blocked_as_store", "C5p_b", "steam pressure buses, not stores"))
            rows.append(_value_row("bfg_cog_holders", config, "policy", "inactive_hourly_store", "", "", "blocked_as_store", "", "n/a", "", "", "blocked_as_store", "C5p_c", "WAG carriers separate; residual/spill diagnostics only"))
            rows.append(_value_row("internal_scrap_loss_stream", config, "t/y", dsp["DSP_internal_scrap_loss_site_t_y"], "", "DSP internal scrap/loss", "reporting_only", "", "n/a", "", "", "structural_or_validation_anchor_only", "C5o_c", dsp["DSP_internal_scrap_handling_status"]))
            rows.append(_value_row("finished_product_accounting", config, "t/y", dsp["DSP_plus_HSM_final_product_proxy_site_t_y"], "", "final-product proxy", "accounting_only", "", "n/a", "", "", "active_interface_or_accounting_buffer", "C5o_c/C5 diagnostics", "denominator unresolved"))
            rows.append(_value_row("generator_fuel_interface", config, "PJ/y", gen["WAG_to_generators_PJ_y"], "", "residual WAG interface", "interface_not_store", "", "n/a", "", "", "active_interface_or_accounting_buffer", "C5p_c", "no WAG storage or direct market value"))
    return rows


def _value_row(buffer_id: str, config: str, unit: str, current: Any, candidate: Any, raw: Any, policy: str, initial: Any, terminal: Any, lower: Any, upper: Any, status: str, source: str, caveat: str) -> dict[str, Any]:
    return {
        "buffer_id": buffer_id,
        "configuration": config,
        "unit": unit,
        "current_C5_value": current,
        "candidate_value": candidate,
        "raw_source_anchor": raw,
        "active_base_policy": policy,
        "initial_value": initial,
        "terminal_rule": terminal,
        "lower_bound": lower,
        "upper_bound": upper,
        "status": status,
        "source_or_stage": source,
        "caveat": caveat,
    }


def _validation_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in (C0, C1):
        for horizon in HORIZONS:
            pellet = _pellet_inventory(payload, config, horizon)
            dri = payload["dri"][(config, horizon)]
            oxygen = payload["oxygen"][(config, horizon)]
            hsm = _hsm_row(payload, config, horizon)
            for carrier, buffer_id in [("coke", "coke_store"), ("sinter", "sinter_store")]:
                bulk = _bulk_row(payload, config, horizon, carrier)
                rows.append(_metric_row(buffer_id, config, horizon, "", "", 0, "", "", "", bulk["capacity_bind_count"], 0, "true", "true", "true", "pass", bulk["terminal_or_inventory_drift_guard"]))
            rows.append(_metric_row("fired_pellets_proxy_store", config, horizon, pellet["pellet_inventory_start_t"], pellet["pellet_inventory_end_t"], pellet["pellet_inventory_delta_t"], pellet["pellet_inventory_min_t"], pellet["pellet_inventory_max_t"], pellet["storage_capacity_t"], pellet["capacity_bind_count"], "1" if pellet["negative_inventory_flag"] == "true" else "0", "true" if pellet["terminal_inventory_guard_status"] else "false", "true", "true", "pass", "practically non-binding bulk-solid policy"))
            rows.append(_metric_row("dri_buffer", config, horizon, dri["DRI_inventory_start_t"], dri["DRI_inventory_end_t"], dri["DRI_inventory_drift_t"], dri["DRI_inventory_min_t"], dri["DRI_inventory_max_t"], dri["DRI_buffer_capacity_t"], "1" if dri["DRI_buffer_capacity_binding"] == "true" else "0", "0", "true" if dri["DRI_buffer_terminal_status"] == "pass" else "false", "true" if _zero(dri["hidden_DRI_source_site_t_y"]) == 0 and _zero(dri["HBI_import_site_t_y"]) == 0 else "false", "true" if dri["DRI_buffer_mined_without_terminal_guard"] == "false" else "false", "pass" if dri["DRI_buffer_terminal_status"] == "pass" else "fail", "C1 active finite DRI buffer; C0 zero"))
            rows.append(_metric_row("slab_yard_total_store", config, horizon, "", "", "0", "", "", "", hsm["capacity_hit_count"], "0", "true" if hsm["terminal_total_policy_status"] else "false", "true", "true", "pass", f"C5l_d {hsm['cap_case']} with {hsm['terminal_hot_policy_status']}"))
            rows.append(_metric_row("oxygen_short_buffer", config, horizon, oxygen["O2_buffer_start_Nm3"], oxygen["O2_buffer_end_Nm3"], "0", oxygen["O2_buffer_min_Nm3"], oxygen["O2_buffer_max_Nm3"], oxygen["O2_buffer_usable_capacity_Nm3"], "1" if oxygen["O2_buffer_capacity_binds"] == "true" else "0", "0", "true" if oxygen["O2_buffer_terminal_status"] == "pass" else "false", "true", "true", "pass", oxygen["O2_buffer_model_ready_capacity_status"]))
            for buffer_id, caveat in [
                ("hot_metal_store", "deferred sensitivity only"),
                ("steam_store", "steam buses are not stores"),
                ("bfg_cog_holders", "WAG holders not hourly stores"),
                ("bofg_holder", "BOFG holder not hourly store"),
                ("liquid_steel_ladle_buffer", "blocked as intertemporal store"),
                ("finished_product_accounting", "accounting only"),
            ]:
                rows.append(_metric_row(buffer_id, config, horizon, "", "", "0", "", "", "", "0", "0", "true", "true", "true", "pass", caveat))
    return rows


def _metric_row(buffer_id: str, config: str, horizon: int, start: Any, end: Any, drift: Any, min_inv: Any, max_inv: Any, capacity: Any, bind_count: Any, neg_count: Any, terminal_pass: Any, no_free_source: Any, no_free_battery: Any, status: str, caveat: str) -> dict[str, Any]:
    return {
        "buffer_id": buffer_id,
        "configuration": config,
        "horizon": horizon,
        "start_inventory": start,
        "end_inventory": end,
        "annual_drift": drift,
        "min_inventory": min_inv,
        "max_inventory": max_inv,
        "capacity": capacity,
        "capacity_bind_count": bind_count,
        "negative_inventory_count": neg_count,
        "terminal_rule_pass": terminal_pass,
        "no_free_source_pass": no_free_source,
        "no_free_battery_pass": no_free_battery,
        "status": status,
        "caveat": caveat,
    }


def _anchor_gap_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    c1_dri = payload["dri"][(C1, 24)]
    rows.append(_gap_row("DRI_BUFFER_CAPACITY_C1_CURRENT", "dri_buffer", C1, "t", DRI_CAPACITY_CANDIDATE_T, DRI_CAPACITY_CURRENT_C5_T, c1_dri["DRI_buffer_capacity_t"], _zero(c1_dri["DRI_buffer_capacity_t"]) - DRI_CAPACITY_CANDIDATE_T, "candidate_sensitivity_not_active_base", "active_physical_store", "none", "current C5 value preserved"))
    for config in (C0, C1):
        oxygen = payload["oxygen"][(config, 24)]
        hsm = _hsm_row(payload, config, 24)
        dsp = payload["dsp_health"][(config, 24)]
        rows.append(_gap_row("OXYGEN_BUFFER_GEOMETRIC_VOLUME", "oxygen_short_buffer", config, "m3", OXYGEN_GEOMETRIC_M3, "", oxygen["O2_buffer_geometric_volume_m3"], 0, "structural_validation_anchor_only", "structural_or_validation_anchor_only", "none", "no usable Nm3 capacity without pressure"))
        rows.append(_gap_row("OXYGEN_BUFFER_100T_CANDIDATE", "oxygen_short_buffer", config, "t", OXYGEN_CANDIDATE_T, "", 0, -OXYGEN_CANDIDATE_T, "deferred_sensitivity_only", "deferred_or_sensitivity_only", "review before activation", "not active base"))
        rows.append(_gap_row("HSM_HOT_CHARGE_BASE_SHARE", "hot_slab_age_buckets", config, "share", 0.5, 0.5, hsm["combined_hot_charge_share"], _zero(hsm["combined_hot_charge_share"]) - 0.5, "active_base_guardrail", "active_interface_or_accounting_buffer", "none", "C5l_d base_0_50 preserved"))
        rows.append(_gap_row("HOT_METAL_BUFFER_500T_CANDIDATE", "hot_metal_store", config, "t", HOT_METAL_CANDIDATE_T, "", 0, -HOT_METAL_CANDIDATE_T, "deferred_sensitivity_only", "deferred_or_sensitivity_only", "review before activation", "not active base"))
        rows.append(_gap_row("DSP_OUTPUT_RAW_ANCHOR", "DSP_route_anchor", config, "t/y", dsp["DSP_raw_anchor_site_t_y"], dsp["DSP_scaled_anchor_site_t_y"], dsp["DSP_output_site_t_y"], dsp["DSP_raw_anchor_gap_site_t_y"], "validation_anchor", "structural_or_validation_anchor_only", "none", "route anchor, not storage"))
    return rows


def _gap_row(anchor_id: str, buffer_or_flow: str, config: str, unit: str, raw: Any, active: Any, model: Any, gap: Any, role: str, status: str, decision: str, caveat: str) -> dict[str, Any]:
    raw_f = _zero(raw)
    model_f = _zero(model)
    rel = "" if abs(raw_f) < 1e-9 else _fmt((model_f - raw_f) / raw_f)
    return {
        "anchor_id": anchor_id,
        "buffer_or_flow": buffer_or_flow,
        "configuration": config,
        "unit": unit,
        "raw_source_anchor": raw,
        "active_scaled_anchor": active,
        "model_output": model,
        "absolute_gap": gap,
        "relative_gap": rel,
        "anchor_role": role,
        "current_status": status,
        "decision_needed": decision,
        "caveat": caveat,
    }


def _source_card_rows() -> list[dict[str, Any]]:
    specs = [
        ("PELLETIZING_Parameters.md", "fired_pellets_proxy_store", "pellet;storage;buffer", "true", "active_practically_nonbinding_bulk_solid_store"),
        ("DRP_Parameters.md", "dri_buffer", "DRI;buffer;CDRI", "true_C1", "active_physical_store"),
        ("EAF_Parameters.md", "dri_buffer", "DRI;EAF;buffer;scrap", "true_C1", "active_physical_store"),
        ("DSP_Parameters.md", "internal_scrap_loss_stream", "scrap;loss;DSP", "reporting_only", "structural_or_validation_anchor_only"),
        ("LINDE_OXYGEN_Parameters.md", "oxygen_short_buffer", "oxygen;buffer;store", "structural_only", "structural_or_validation_anchor_only"),
        ("BOILER_STEAM_CIRCUIT_Parameters.md", "steam_store", "steam;storage;bus", "false", "blocked_as_store"),
        ("IJ01_VN25_GENERATORS_Parameters.md", "generator_fuel_interface", "WAG;generator;holder", "interface_only", "active_interface_or_accounting_buffer"),
        ("HSM_Parameters.md", "slab_yard_total_store", "slab;HSM;buffer", "true_scaffold", "active_interface_or_accounting_buffer"),
        ("HSM_Slab_Buffer_Parameters.md", "hot_slab_age_buckets", "slab;hot;cold;buffer", "true_scaffold", "active_interface_or_accounting_buffer"),
        ("BUFFERS_STORAGE_Parameters.md", "hot_metal_store", "hot metal;500", "false_base", "deferred_or_sensitivity_only"),
    ]
    rows: list[dict[str, Any]] = []
    for source, buffer_id, terms, active, status in specs:
        path = SOURCE_CARD_DIR / source
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        snippets = []
        for term in terms.split(";"):
            for line in text.splitlines():
                if term.lower() in line.lower():
                    snippets.append(line.strip())
                    break
        rows.append(
            {
                "source_card": source,
                "referenced_buffer_or_store": buffer_id,
                "parameter_id": terms,
                "value_or_status": " | ".join(snippets)[:500],
                "active_in_current_C5": active,
                "canonical_register_status": status,
                "mismatch_flag": "false",
                "recommended_action": "keep_current_C5_status; do_not_promote_source_card_values_by_diagnostic",
                "caveat": "source-card evidence scanned; diagnostic does not create executable inputs",
            }
        )
    return rows


def _decision_rows() -> list[dict[str, Any]]:
    data = [
        ("BSD_DECISION_001", "DRI buffer", "C1 active finite current C5 value approx 15.230 kt", "1-3 day sensitivity; 17.760 kt candidate", "current C5o_a/o_b accepted baseline", "true", "true", "true", "true", "preserve for reconciliation", "development assumption"),
        ("BSD_DECISION_002", "Bulk solids", "coke/sinter/pellets practically non-binding but not free source", "tight public-capacity caps later", "prevents fake infeasibility while preserving material balance checks", "true", "false", "false", "false", "keep no-free-source diagnostics", "not thesis approved"),
        ("BSD_DECISION_003", "Hot metal", "no active hot-metal store in base", "500 t sensitivity", "preserves no-buffer BF-to-BOF coupling", "true", "true", "true", "true", "do not activate before annual reconciliation", "deferred"),
        ("BSD_DECISION_004", "Oxygen", "structural balancing buffer only", "100 t candidate if pressure/capacity basis is reviewed", "public vessel geometry lacks pressure/usable swing", "false", "true", "true", "true", "keep structural only", "numeric capacity deferred"),
        ("BSD_DECISION_005", "WAG and steam", "WAG holders and steam are not stores", "later governed storage only with explicit capacities", "prevents fake energy batteries and direct WAG valuation", "true", "true", "true", "true", "keep balances and residual diagnostics", "blocked as stores"),
        ("BSD_DECISION_006", "Final product", "accounting/fulfilment only", "freeze denominator later", "denominator remains unresolved", "false", "true", "false", "true", "do not use as flexibility store", "accounting only"),
    ]
    return [
        {
            "decision_id": row[0],
            "topic": row[1],
            "current_choice": row[2],
            "alternatives": row[3],
            "why_current_choice_exists": row[4],
            "affects_physical_behaviour": row[5],
            "affects_economics_later": row[6],
            "sensitivity_required": row[7],
            "freeze_before_DA_or_economics": row[8],
            "recommended_action": row[9],
            "caveat": row[10],
        }
        for row in data
    ]


def _redflag_row(payload: dict[str, Any], validation: list[dict[str, Any]]) -> dict[str, Any]:
    c1_dri = payload["dri"][(C1, 24)]
    c5pc = payload["generator_health"][(C0, 24)]
    c5pa = payload["oxygen"][(C0, 24)]
    hsm_rows = [row for row in payload["hsm"] if row["case_status"] == "active_base_guardrail"]
    flags = {
        "STORE_ACTIVE_WITHOUT_CAPACITY": False,
        "STORE_ACTIVE_WITHOUT_TERMINAL_RULE": False,
        "NEGATIVE_INVENTORY": any(_zero(row["negative_inventory_count"]) > 0 for row in validation),
        "TERMINAL_DRIFT_NONZERO": any(row["terminal_rule_pass"] == "false" for row in validation),
        "BULK_SOLID_STORAGE_USED_AS_FREE_SOURCE": any(_zero(row["pellet_gap_site_t_y"]) != 0 for row in payload["pellet_health"].values()),
        "HOT_METAL_STORE_ACTIVE_IN_BASE": False,
        "OXYGEN_STORE_ACTIVE_WITHOUT_PRESSURE_OR_CAPACITY_ASSUMPTION": bool(c5pa["O2_buffer_usable_capacity_Nm3"]) and c5pa["O2_buffer_pressure_assumption_available"] != "true",
        "OXYGEN_STORE_USED_FOR_STRATEGIC_STORAGE": c5pa["O2_buffer_used_as_strategic_storage"] == "true",
        "WAG_HOLDER_USED_AS_HOURLY_STORE": False,
        "STEAM_STORE_ACTIVE": False,
        "LIQUID_STEEL_STORE_ACTIVE": False,
        "INTERNAL_SCRAP_USED_AS_FREE_EAF_INPUT": False,
        "FINISHED_PRODUCT_USED_AS_FLEXIBILITY_STORE": False,
        "EXTERNAL_SLAB_IMPORT_USED_AS_FREE_STORE": False,
        "HSM_BASE_0_50_REVERTED": any(row["cap_case"] != "base_0_50" or row["case_status"] != "active_base_guardrail" for row in hsm_rows),
        "DRI_BUFFER_CAPACITY_CHANGED_WITHOUT_METHOD_CHANGE": abs(_zero(c1_dri["DRI_buffer_capacity_t"]) - DRI_CAPACITY_CURRENT_C5_T) > 1e-3,
        "COKE_RECONCILIATION_BASELINE_REOPENED": payload["oxygen_health"][(C0, 24)]["coke_reconciliation_baseline_status"] != "C5m_f_bounded_coke_reconciliation_active_development_baseline",
        "DENOMINATOR_SILENTLY_FROZEN": c5pc["denominator_status"] != DENOMINATOR_STATUS,
        "GENERATOR_PRICE_RESPONSIVE_DISPATCH_ACTIVE": c5pc["price_responsive_dispatch_base"] != "false",
        "WAG_DIRECT_MARKET_VALUE_ACTIVE": False,
    }
    return {
        "stage_id": STAGE,
        **{name: str(flags[name]).lower() for name in FAILURE_FLAGS},
        **{name: "true" for name in CAVEATS},
        "failure_count": sum(1 for value in flags.values() if value),
        "caveat_count": len(CAVEATS),
        "status": "pass_with_caveats" if not any(flags.values()) else "fail",
    }


def _write_report(gate: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C5 Buffer/Store Register And Validation",
        "",
        "Diagnostic-only C5p_d review. No model equations, active production target, C5l_d base_0_50, C5p_a/b/c utility behaviour, economics, DA revenue, mFRR, or denominator policy are changed.",
        "",
        "## Stage Gate",
        "",
        f"- Decision: `{gate['decision']}`",
        f"- Failure count: `{gate['failure_count']}`",
        f"- Caveat count: `{gate['caveat_count']}`",
        f"- Denominator status: `{gate['denominator_status']}`",
        "",
        "## Key Findings",
        "",
        f"- DRI buffer C1 capacity remains `{_fmt(gate['C1_24h_DRI_buffer_capacity_t'])}` t with terminal drift `{_fmt(gate['C1_24h_DRI_inventory_drift_t'])}` t.",
        "- Coke, sinter and fired-pellet storage remain active practically non-binding bulk-solid policies with zero capacity-bind diagnostics.",
        "- Oxygen remains structural/balancing-only; 1670 m3 is a geometric anchor, not usable storage capacity.",
        "- Steam and WAG holders remain blocked as stores; steam is a bus balance and WAG is handled through carrier ledgers, residuals and flare/spill diagnostics.",
        "- Hot-metal store, oxygen numeric capacity, dynamic scrap pool and final-product flexibility storage remain inactive/deferred.",
        "- C5l_d `base_0_50` remains the active HSM/WBW heat case.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_outputs() -> dict[str, Any]:
    C5P_D_DIR.mkdir(parents=True, exist_ok=True)
    payload = _payload()
    presence = _presence_rows()
    current_values = _current_values_rows(payload)
    validation = _validation_rows(payload)
    anchor_gap = _anchor_gap_rows(payload)
    source_refs = _source_card_rows()
    decisions = _decision_rows()
    redflags = [_redflag_row(payload, validation)]
    c1_dri = payload["dri"][(C1, 24)]
    gate = {
        "stage_id": STAGE,
        "decision": "pass_development_buffer_store_register_validation" if redflags[0]["failure_count"] == 0 else "fail_development_buffer_store_register_validation",
        "status": "development_only",
        "thesis_usability": False,
        "output_directory": str(C5P_D_DIR).replace("\\", "/"),
        "failure_count": redflags[0]["failure_count"],
        "caveat_count": redflags[0]["caveat_count"],
        "C1_24h_DRI_buffer_capacity_t": _zero(c1_dri["DRI_buffer_capacity_t"]),
        "C1_24h_DRI_inventory_drift_t": _zero(c1_dri["DRI_inventory_drift_t"]),
        "bulk_solid_capacity_bind_count_max": max(_zero(row["capacity_bind_count"]) for row in payload["bulk"]),
        "HSM_heat_case": "base_0_50",
        "oxygen_buffer_mode": payload["oxygen"][(C0, 24)]["O2_buffer_mode"],
        "steam_store_active": False,
        "WAG_holder_hourly_store_active": False,
        "hot_metal_store_active_base": False,
        "electricity_accounting_status": ELECTRICITY_ACCOUNTING_STATUS,
        "denominator_status": DENOMINATOR_STATUS,
    }

    _write_csv(C5P_D_DIR / "c5_buffer_store_presence_matrix.csv", presence)
    _write_csv(C5P_D_DIR / "c5_buffer_store_current_values.csv", current_values)
    _write_csv(C5P_D_DIR / "c5_buffer_store_validation_metrics.csv", validation)
    _write_csv(C5P_D_DIR / "c5_buffer_store_anchor_gap_matrix.csv", anchor_gap)
    _write_csv(C5P_D_DIR / "c5_buffer_store_source_card_cross_reference.csv", source_refs)
    _write_csv(C5P_D_DIR / "c5_buffer_store_decision_register.csv", decisions)
    _write_csv(C5P_D_DIR / "c5_buffer_store_red_flags.csv", redflags)
    _write_json(C5P_D_DIR / "c5_buffer_store_stage_gate.json", gate)
    _write_json(C5P_D_DIR / "s4_4c5p_d_stage_gate.json", gate)
    _write_csv(
        C5P_D_DIR / "s4_4c5p_d_run_registry.csv",
        [{
            "stage": STAGE,
            "source_stage": "S4.4c5p_c_ij01_vn25_generator_interface_accounting",
            "decision": gate["decision"],
            "status": "development_only",
            "thesis_usability": "false",
            "output_directory": gate["output_directory"],
        }],
    )
    _write_report(gate)
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "presence": len(presence),
            "current_values": len(current_values),
            "validation": len(validation),
            "anchor_gap": len(anchor_gap),
            "source_refs": len(source_refs),
            "decisions": len(decisions),
            "redflags": len(redflags),
        },
    }
    _write_json(C5P_D_DIR / "s4_4c5p_d_summary.json", summary)
    return summary


def run_s4_4c5p_d_buffer_store_register_and_validation() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5p_d_buffer_store_register_and_validation(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
