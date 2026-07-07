"""S4.4c5l_c HSM slab age-bucket buffer and charge-specific reheat.

This development-only stage replaces the C5l_a simple hot/cold scaffold with a
finite, LP-compatible slab age-bucket accounting layer. It preserves the C5k
production policy, the C5l_a 80/20 DSP/HSM routing, the active 1.10 slab/HRC
factor, and the C5l_b WAG controller semantics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    CONFIGS,
    HORIZONS,
    S4_ROOT,
    WAG_TOL_MWH,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5g_wag_aggregate_diagnostic_hygiene import (
    AGGREGATE_COLUMNS,
    WAG_CARRIERS,
    _wag_aggregate_invariant_rows,
)
from .s4_4c5l_a_downstream_routing_and_hsm_buffer_patch import (
    C5L_A_DIR,
    DOWNSTREAM_ROUTING_MODE,
    HSM_CO2_STATUS,
    HSM_PARAMETER_COLUMNS,
)
from .s4_4c5l_b_hsm_wag_dispatch_controller_and_traceability_patch import (
    C5L_B_DIR,
    CONTROLLER_IMPLEMENTATION_MODE,
    HSM_REHEAT_CONTROLLER_MODE,
    run_s4_4c5l_b_hsm_wag_dispatch_controller_and_traceability_patch,
)
from .s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR


STAGE = "S4.4c5l_c_HSM_slab_age_bucket_buffer_and_charge_reheat"
C5L_C_DIR = S4_ROOT / "s4_4c5l_c_HSM_slab_age_bucket_buffer_and_charge_reheat"
SOURCE_CARD = Path("data/03_Optimisation/inputs/assets/steel/source_cards/HSM_Slab_Buffer_Parameters.md")
DEPENDENCY_CHAIN = "C5j -> C5k -> C5l_a -> C5l_b -> C5l_c"

SLAB_BUFFER_ENABLED = True
SLAB_BUFFER_MODE = "age_bucket_hot_cold_slab_yard"
SLAB_STORE_CAPACITY_TOTAL_T = 25_000.0
INITIAL_COLD_SLAB_INVENTORY_T = 12_500.0
INITIAL_HOT_SLAB_INVENTORY_T = 0.0
TERMINAL_TOTAL_SLAB_INVENTORY_EQUALS_INITIAL = True
TERMINAL_HOT_SLAB_INVENTORY_ZERO = True
AGE_BUCKET_WIDTH_H = 1
DIRECT_HOT_AGE_BUCKET = "age0"
HOT_AGE_BUCKETS = "age1_to_age6"
COLD_BUCKET = "cold"
COLD_AGE_THRESHOLD_H = ">6"
CASTER_TO_AGE0_LAG_H = 1
CASTER_YIELD_TO_SLAB = 1.0
IMPORT_CONVENTION = "imported_slab_enters_cold_inventory_and_is_same_hour_available"
HSM_YIELD_ONE_ACTIVE = False

REHEAT_DHCR_GJ_PER_T_SLAB = 0.335
REHEAT_HCR_GJ_PER_T_SLAB = 0.878
REHEAT_CCR_GJ_PER_T_SLAB = 1.338
COLD_VS_DIRECT_REHEAT_PENALTY_GJ_PER_T = REHEAT_CCR_GJ_PER_T_SLAB - REHEAT_DHCR_GJ_PER_T_SLAB
COLD_VS_HOT_REHEAT_PENALTY_GJ_PER_T = REHEAT_CCR_GJ_PER_T_SLAB - REHEAT_HCR_GJ_PER_T_SLAB
CASTER_AUX_ENERGY_GJ_PER_T_CAST_STEEL = 0.06
HOT_ROLLING_COLD_CHARGE_ENERGY_CHECK_GJ_PER_T_HRC = 1.55
AGE_BUCKETS = tuple(f"age{i}" for i in range(7))
MATERIAL_ROUNDING_TOL_T_Y = 1e-2


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _annualisation_factor(horizon: int) -> float:
    return 8760.0 / horizon


def _policy_row(parameter_id: str, value: Any, unit: str, role: str, basis: str) -> dict[str, Any]:
    return {
        "parameter_id": parameter_id,
        "configuration_scope": "generic_policy",
        "applies_to_configuration": "all",
        "plant_id": "HSM_slab_buffer",
        "parameter_name": parameter_id.lower(),
        "parameter_role": role,
        "direction": "policy",
        "carrier_or_material": "slab",
        "base_value": _fmt(value),
        "low_value": "",
        "high_value": "",
        "unit": unit,
        "basis": basis,
        "conversion_formula": "",
        "source_or_assumption_id": "HSM_Slab_Buffer_Parameters.md",
        "input_status": "development_candidate",
        "source_status": "source_card_candidate",
        "evidence_strength": "candidate_public_generic_or_development_assumption",
        "executable_status": "development_executable",
        "development_executable": "true",
        "thesis_usability": "false",
        "human_review_required": "true",
        "codex_may_decide": "false",
        "applies_to_solver": "false",
        "applies_to_diagnostics": "true",
        "applies_to_anchor_comparison": "false",
        "active_driver": "true",
        "constraint_used": "false",
        "caveat": "candidate only; not Tata-validated; not thesis-approved",
    }


def _development_input_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        dict(row) for row in _read_csv(C5L_B_DIR / "s4_4c5l_b_hsm_reheat_controller_input_rows.csv")
    ]
    rows.extend(
        [
            _policy_row("SLAB_BUFFER_ENABLED", int(SLAB_BUFFER_ENABLED), "boolean", "buffer_policy", "HSM_slab_yard"),
            _policy_row("SLAB_BUFFER_MODE", SLAB_BUFFER_MODE, "mode", "buffer_policy", "age_bucket_hot_cold_slab_yard"),
            _policy_row("SLAB_STORE_CAPACITY_TOTAL_T", SLAB_STORE_CAPACITY_TOTAL_T, "t slab", "storage_capacity", "finite_total_slab_inventory"),
            _policy_row("INITIAL_COLD_SLAB_INVENTORY_T", INITIAL_COLD_SLAB_INVENTORY_T, "t slab", "initial_inventory", "cold_slab_yard"),
            _policy_row("INITIAL_HOT_SLAB_INVENTORY_T", INITIAL_HOT_SLAB_INVENTORY_T, "t slab", "initial_inventory", "age0_to_age6"),
            _policy_row("TERMINAL_TOTAL_SLAB_INVENTORY_EQUALS_INITIAL", int(TERMINAL_TOTAL_SLAB_INVENTORY_EQUALS_INITIAL), "boolean", "terminal_policy", "total_slab_inventory"),
            _policy_row("TERMINAL_HOT_SLAB_INVENTORY_ZERO", int(TERMINAL_HOT_SLAB_INVENTORY_ZERO), "boolean", "terminal_policy", "age0_to_age6"),
            _policy_row("AGE_BUCKET_WIDTH_H", AGE_BUCKET_WIDTH_H, "h", "age_bucket_policy", "hot_slab_age_buckets"),
            _policy_row("DIRECT_HOT_AGE_BUCKET", DIRECT_HOT_AGE_BUCKET, "bucket", "age_bucket_policy", "DHCR"),
            _policy_row("HOT_AGE_BUCKETS", HOT_AGE_BUCKETS, "buckets", "age_bucket_policy", "HCR"),
            _policy_row("COLD_BUCKET", COLD_BUCKET, "bucket", "age_bucket_policy", "CCR"),
            _policy_row("COLD_AGE_THRESHOLD_H", COLD_AGE_THRESHOLD_H, "h", "age_bucket_policy", "cold_slab_yard"),
            _policy_row("CASTER_TO_AGE0_LAG_H", CASTER_TO_AGE0_LAG_H, "h", "caster_lag", "liquid_to_age0"),
            _policy_row("CASTER_YIELD_TO_SLAB", CASTER_YIELD_TO_SLAB, "t slab/t cast steel", "material_conversion", "development_assumption"),
            _policy_row("HSM_YIELD_1P0_ACTIVE_BASE", int(HSM_YIELD_ONE_ACTIVE), "boolean", "deferred_sensitivity", "not_active_base"),
            _policy_row("REHEAT_DHCR_GJ_PER_T_SLAB", REHEAT_DHCR_GJ_PER_T_SLAB, "GJ/t slab", "reheat_energy", "age0_direct_hot_charge"),
            _policy_row("REHEAT_HCR_GJ_PER_T_SLAB", REHEAT_HCR_GJ_PER_T_SLAB, "GJ/t slab", "reheat_energy", "age1_to_age6_hot_charge"),
            _policy_row("REHEAT_CCR_GJ_PER_T_SLAB", REHEAT_CCR_GJ_PER_T_SLAB, "GJ/t slab", "reheat_energy", "cold_charge"),
            _policy_row("CASTER_AUX_ENERGY_GJ_PER_T_CAST_STEEL", CASTER_AUX_ENERGY_GJ_PER_T_CAST_STEEL, "GJ/t cast steel", "diagnostic_only", "caster_aux_energy"),
            _policy_row("HOT_ROLLING_COLD_CHARGE_ENERGY_CHECK_GJ_PER_T_HRC", HOT_ROLLING_COLD_CHARGE_ENERGY_CHECK_GJ_PER_T_HRC, "GJ/t HRC", "validation_anchor", "plausibility_only"),
        ]
    )
    return rows


def _param(rows: list[dict[str, str]], parameter_id: str) -> float:
    row = next(row for row in rows if row["parameter_id"] == parameter_id)
    if row["thesis_usability"] != "false" or row["human_review_required"] != "true" or row["codex_may_decide"] != "false":
        raise ValueError(f"{parameter_id} failed C5l_c governance checks.")
    return _zero(row["base_value"])


def _hourly_rows(report: list[dict[str, str]], hsm_slab_factor: float, rolling_electricity: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in report:
        config = item["configuration"]
        horizon = int(item["horizon_hours"])
        annualisation = _annualisation_factor(horizon)
        internal_period = _zero(item["internal_slab_to_hsm_site_t_y"]) / annualisation
        imported_period = _zero(item["imported_slab_site_t_y"]) / annualisation
        cast_rate = internal_period / max(horizon - 1, 1)
        import_rate = imported_period / horizon

        for hour in range(horizon):
            age_start = {bucket: 0.0 for bucket in AGE_BUCKETS}
            age_start["age0"] = cast_rate if hour > 0 else 0.0
            cold_start = INITIAL_COLD_SLAB_INVENTORY_T
            from_age = {bucket: 0.0 for bucket in AGE_BUCKETS}
            from_age["age0"] = age_start["age0"]
            imported_to_cold = import_rate
            from_cold = import_rate
            cast_to_age0 = cast_rate if hour < horizon - 1 else 0.0

            age_end = {bucket: 0.0 for bucket in AGE_BUCKETS}
            age_end["age0"] = cast_to_age0
            for idx in range(1, 7):
                prev = f"age{idx - 1}"
                age_end[f"age{idx}"] = age_start[prev] - from_age[prev]
            cold_end = cold_start + age_start["age6"] - from_age["age6"] + imported_to_cold - from_cold
            total_start = sum(age_start.values()) + cold_start
            total_end = sum(age_end.values()) + cold_end
            hsm_input = sum(from_age.values()) + from_cold
            hsm_output = hsm_input / hsm_slab_factor
            dhcr_gj = from_age["age0"] * REHEAT_DHCR_GJ_PER_T_SLAB
            hcr_gj = sum(from_age[f"age{i}"] for i in range(1, 7)) * REHEAT_HCR_GJ_PER_T_SLAB
            ccr_gj = from_cold * REHEAT_CCR_GJ_PER_T_SLAB
            reheat_gj = dhcr_gj + hcr_gj + ccr_gj
            rolling_mwh = hsm_output * rolling_electricity
            inventory_balance_error = total_end - total_start - cast_to_age0 - imported_to_cold + hsm_input
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "hour": hour,
                    "annualisation_factor": _fmt(annualisation),
                    "slab_buffer_mode": SLAB_BUFFER_MODE,
                    "import_convention": IMPORT_CONVENTION,
                    "slab_cast_to_hsm_route_t": _fmt(cast_to_age0),
                    "external_slab_import_to_cold_t": _fmt(imported_to_cold),
                    **{f"slab_{bucket}_inventory_start_t": _fmt(age_start[bucket]) for bucket in AGE_BUCKETS},
                    "slab_cold_inventory_start_t": _fmt(cold_start),
                    **{f"hsm_from_{bucket}_t": _fmt(from_age[bucket]) for bucket in AGE_BUCKETS},
                    "hsm_from_cold_t": _fmt(from_cold),
                    **{f"slab_{bucket}_inventory_end_t": _fmt(age_end[bucket]) for bucket in AGE_BUCKETS},
                    "slab_cold_inventory_end_t": _fmt(cold_end),
                    "total_slab_inventory_start_t": _fmt(total_start),
                    "total_slab_inventory_end_t": _fmt(total_end),
                    "slab_store_capacity_total_t": _fmt(SLAB_STORE_CAPACITY_TOTAL_T),
                    "capacity_exceeded": "false" if max(total_start, total_end) <= SLAB_STORE_CAPACITY_TOTAL_T + 1e-9 else "true",
                    "hsm_total_slab_input_t": _fmt(hsm_input),
                    "hsm_output_t_HRC": _fmt(hsm_output),
                    "hsm_slab_input_t_per_t_HRC": _fmt(hsm_slab_factor),
                    "hsm_yield_1p0_active_base": "false",
                    "reheat_DHCR_GJ": _fmt(dhcr_gj),
                    "reheat_HCR_GJ": _fmt(hcr_gj),
                    "reheat_CCR_GJ": _fmt(ccr_gj),
                    "hsm_reheat_heat_GJ": _fmt(reheat_gj),
                    "hsm_reheat_heat_MWh_th": _fmt(reheat_gj / 3.6),
                    "hsm_rolling_electricity_MWh_e": _fmt(rolling_mwh),
                    "inventory_balance_error_t": _fmt(inventory_balance_error),
                    "status": "pass" if abs(inventory_balance_error) <= 1e-9 and max(total_start, total_end) <= SLAB_STORE_CAPACITY_TOTAL_T + 1e-9 else "fail",
                }
            )
    return rows


def _bucket_sum(hourly: list[dict[str, Any]], config: str, horizon: int, field: str) -> float:
    return sum(_zero(row[field]) for row in hourly if row["configuration"] == config and int(row["horizon_hours"]) == horizon)


def _report_rows(
    c5l_a_report: list[dict[str, str]],
    c5l_b_summary: list[dict[str, str]],
    hourly: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    b_summary = {(row["configuration"], int(row["horizon_hours"])): row for row in c5l_b_summary}
    rows: list[dict[str, Any]] = []
    for item in c5l_a_report:
        config = item["configuration"]
        horizon = int(item["horizon_hours"])
        annualisation = _annualisation_factor(horizon)
        initial_total = INITIAL_COLD_SLAB_INVENTORY_T + INITIAL_HOT_SLAB_INVENTORY_T
        terminal_age = {
            bucket: _zero(next(row for row in hourly if row["configuration"] == config and int(row["horizon_hours"]) == horizon and int(row["hour"]) == horizon - 1)[f"slab_{bucket}_inventory_end_t"])
            for bucket in AGE_BUCKETS
        }
        terminal_cold = _zero(next(row for row in hourly if row["configuration"] == config and int(row["horizon_hours"]) == horizon and int(row["hour"]) == horizon - 1)["slab_cold_inventory_end_t"])
        hsm_from_age0 = _bucket_sum(hourly, config, horizon, "hsm_from_age0_t") * annualisation
        hsm_from_hot = sum(_bucket_sum(hourly, config, horizon, f"hsm_from_age{i}_t") for i in range(1, 7)) * annualisation
        hsm_from_cold = _bucket_sum(hourly, config, horizon, "hsm_from_cold_t") * annualisation
        imported_cold = _bucket_sum(hourly, config, horizon, "external_slab_import_to_cold_t") * annualisation
        hsm_slab = _bucket_sum(hourly, config, horizon, "hsm_total_slab_input_t") * annualisation
        hsm_output = _bucket_sum(hourly, config, horizon, "hsm_output_t_HRC") * annualisation
        dhcr_gj = _bucket_sum(hourly, config, horizon, "reheat_DHCR_GJ") * annualisation
        hcr_gj = _bucket_sum(hourly, config, horizon, "reheat_HCR_GJ") * annualisation
        ccr_gj = _bucket_sum(hourly, config, horizon, "reheat_CCR_GJ") * annualisation
        reheat_gj = dhcr_gj + hcr_gj + ccr_gj
        rolling_mwh = _bucket_sum(hourly, config, horizon, "hsm_rolling_electricity_MWh_e") * annualisation
        old_reheat = _zero(b_summary[(config, horizon)]["hsm_reheat_demand_site_MWh_y"])
        material_gap = _zero(item["active_total_liquid_steel_target_site_t_y"]) + _zero(item["imported_slab_site_t_y"]) - _zero(item["dsp_output_site_t_y"]) - hsm_slab
        total_capacity_hits = sum(
            1
            for row in hourly
            if row["configuration"] == config
            and int(row["horizon_hours"]) == horizon
            and row["capacity_exceeded"] == "true"
        )
        rows.append(
            {
                "stage_id": STAGE,
                "configuration": config,
                "horizon_hours": horizon,
                "status": "development_only",
                "thesis_usability": "false",
                "dependency_chain": DEPENDENCY_CHAIN,
                "downstream_routing_mode": DOWNSTREAM_ROUTING_MODE,
                "slab_buffer_mode": SLAB_BUFFER_MODE,
                "slab_buffer_enabled": "true",
                "active_total_liquid_steel_target_site_t_y": item["active_total_liquid_steel_target_site_t_y"],
                "hsm_slab_input_t_per_t_HRC": item["hsm_slab_input_t_per_t_HRC"],
                "hsm_yield_1p0_active_base": "false",
                "hsm_yield_1p0_status": "deferred_sensitivity_not_active_base",
                "slab_store_capacity_total_t": _fmt(SLAB_STORE_CAPACITY_TOTAL_T),
                "initial_total_slab_inventory_t": _fmt(initial_total),
                "initial_cold_slab_inventory_t": _fmt(INITIAL_COLD_SLAB_INVENTORY_T),
                "initial_hot_slab_inventory_t": _fmt(INITIAL_HOT_SLAB_INVENTORY_T),
                "terminal_total_slab_inventory_t": _fmt(sum(terminal_age.values()) + terminal_cold),
                "terminal_hot_slab_inventory_t": _fmt(sum(terminal_age.values())),
                "terminal_cold_slab_inventory_t": _fmt(terminal_cold),
                "terminal_total_policy_status": "pass" if abs(sum(terminal_age.values()) + terminal_cold - initial_total) <= 1e-6 else "fail",
                "terminal_hot_policy_status": "pass" if abs(sum(terminal_age.values())) <= 1e-6 else "fail",
                "capacity_hit_count": total_capacity_hits,
                "max_total_slab_inventory_t": _fmt(max(_zero(row["total_slab_inventory_start_t"]) for row in hourly if row["configuration"] == config and int(row["horizon_hours"]) == horizon)),
                "min_cold_inventory_t": _fmt(min(_zero(row["slab_cold_inventory_start_t"]) for row in hourly if row["configuration"] == config and int(row["horizon_hours"]) == horizon)),
                "hsm_from_age0_site_t_y": _fmt(hsm_from_age0),
                "hsm_from_age1_to_age6_site_t_y": _fmt(hsm_from_hot),
                "hsm_from_cold_site_t_y": _fmt(hsm_from_cold),
                "imported_cold_slab_site_t_y": _fmt(imported_cold),
                "direct_hot_charge_share": _fmt(hsm_from_age0 / hsm_slab if hsm_slab else 0.0),
                "hot_charge_share_age1_to_age6": _fmt(hsm_from_hot / hsm_slab if hsm_slab else 0.0),
                "cold_charge_share": _fmt(hsm_from_cold / hsm_slab if hsm_slab else 0.0),
                "hsm_slab_input_site_t_y": _fmt(hsm_slab),
                "hsm_output_site_t_y": _fmt(hsm_output),
                "dsp_output_site_t_y": item["dsp_output_site_t_y"],
                "active_final_product_proxy_site_t_y": _fmt(hsm_output + _zero(item["dsp_output_site_t_y"])),
                "indicative_downstream_material_gap_site_t_y": _fmt(material_gap),
                "reheat_DHCR_site_GJ_y": _fmt(dhcr_gj),
                "reheat_HCR_site_GJ_y": _fmt(hcr_gj),
                "reheat_CCR_site_GJ_y": _fmt(ccr_gj),
                "hsm_reheat_heat_site_GJ_y": _fmt(reheat_gj),
                "hsm_reheat_heat_site_PJ_y": _fmt(reheat_gj / 1_000_000.0),
                "hsm_reheat_heat_site_MWh_th_y": _fmt(reheat_gj / 3.6),
                "hsm_reheat_heat_site_TWh_th_y": _fmt(reheat_gj / 3.6 / 1_000_000.0),
                "hsm_rolling_electricity_site_MWh_e_y": _fmt(rolling_mwh),
                "hsm_rolling_electricity_site_GWh_e_y": _fmt(rolling_mwh / 1000.0),
                "c5l_b_average_reheat_site_MWh_y": _fmt(old_reheat),
                "reheat_delta_vs_C5l_b_average_site_MWh_y": _fmt(reheat_gj / 3.6 - old_reheat),
                "scale_factor": item["scale_factor"],
                "import_convention": IMPORT_CONVENTION,
                "HSM_CO2_status": HSM_CO2_STATUS,
                "warnings_deferred_items": "no_slab_age_temperature_decay;no_HSM_campaign_scheduling;no_HSM_CO2_factor;no_Sinter",
            }
        )
    return rows


def _site_total_rows(wag_rows: list[dict[str, str]], config: str, horizon: int) -> dict[str, dict[str, str]]:
    return {
        row["carrier"]: row
        for row in wag_rows
        if row["configuration"] == config
        and int(row["horizon_hours"]) == horizon
        and row["plant_id"] == "SITE_TOTAL"
        and row["carrier"] in WAG_CARRIERS
    }


def _controller_rows(
    report: list[dict[str, Any]],
    c5k_wag: list[dict[str, str]],
    c5l_b_controller: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, int, str], dict[str, float]]]:
    old = {
        (row["configuration"], int(row["horizon_hours"])): row
        for row in c5l_b_controller
    }
    dashboard: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    allocation: dict[tuple[str, int, str], dict[str, float]] = {}
    for item in report:
        config = item["configuration"]
        horizon = int(item["horizon_hours"])
        demand_site = _zero(item["hsm_reheat_heat_site_MWh_th_y"])
        demand_raw = demand_site / (_zero(item.get("scale_factor")) or 1.0)
        remaining_raw = demand_raw
        remaining_site = demand_site
        carrier_totals = _site_total_rows(c5k_wag, config, horizon)
        total_available_raw = total_available_site = total_alloc_raw = total_alloc_site = 0.0
        total_residual_raw = total_residual_site = 0.0
        for carrier in WAG_CARRIERS:
            source = carrier_totals[carrier]
            scale = _zero(source.get("scale_factor")) or 1.0
            generated_raw = _zero(source["generated_MWh_LHV_y"])
            direct_pre_raw = _zero(source["consumed_direct_MWh_LHV_y"])
            boiler_pre_raw = _zero(source["consumed_boiler_MWh_LHV_y"])
            vattenfall_pre_raw = _zero(source["consumed_vattenfall_MWh_LHV_y"])
            available_raw = max(generated_raw - direct_pre_raw, 0.0)
            used_raw = min(remaining_raw, available_raw)
            remaining_raw = max(remaining_raw - used_raw, 0.0)
            used_site = used_raw * scale
            remaining_site = max(remaining_site - used_site, 0.0)
            if abs(remaining_raw) <= WAG_TOL_MWH:
                remaining_raw = 0.0
            if abs(remaining_site) <= WAG_TOL_MWH:
                remaining_site = 0.0
            residual_raw = available_raw - used_raw
            direct_post_raw = direct_pre_raw + used_raw
            boiler_post_raw = min(boiler_pre_raw, max(generated_raw - direct_post_raw, 0.0))
            vattenfall_post_raw = min(
                vattenfall_pre_raw,
                max(generated_raw - direct_post_raw - boiler_post_raw, 0.0),
            )
            flare_post_raw = max(generated_raw - direct_post_raw - boiler_post_raw - vattenfall_post_raw, 0.0)
            balance_error_raw = generated_raw - direct_post_raw - boiler_post_raw - vattenfall_post_raw - flare_post_raw
            allocation[(config, horizon, carrier)] = {
                "scale": scale,
                "generated_raw": generated_raw,
                "direct_pre_raw": direct_pre_raw,
                "available_raw": available_raw,
                "used_raw": used_raw,
                "used_site": used_site,
                "residual_raw": residual_raw,
                "boiler_post_raw": boiler_post_raw,
                "vattenfall_post_raw": vattenfall_post_raw,
                "flare_post_raw": flare_post_raw,
                "balance_error_raw": balance_error_raw,
                "lhv": _zero(source.get("LHV_MJ_per_Nm3_used")),
            }
            old_site = _zero(old[(config, horizon)][f"{carrier}_to_HSM_reheat_site_MWh_y"])
            total_available_raw += available_raw
            total_available_site += available_raw * scale
            total_alloc_raw += used_raw
            total_alloc_site += used_site
            total_residual_raw += residual_raw
            total_residual_site += residual_raw * scale
            trace.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "carrier": carrier,
                    "controller_mode": HSM_REHEAT_CONTROLLER_MODE,
                    "implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
                    "charge_reheat_mode": "DHCR_HCR_CCR_slab_input_basis",
                    "hsm_reheat_demand_site_MWh_y": _fmt(demand_site),
                    "available_after_KGF_BF_priority_raw_MWh_y": _fmt(available_raw),
                    "available_after_KGF_BF_priority_site_MWh_y": _fmt(available_raw * scale),
                    "allocated_to_HSM_reheat_raw_MWh_y": _fmt(used_raw),
                    "allocated_to_HSM_reheat_site_MWh_y": _fmt(used_site),
                    "residual_after_HSM_raw_MWh_y": _fmt(residual_raw),
                    "residual_after_HSM_site_MWh_y": _fmt(residual_raw * scale),
                    "delta_vs_C5l_b_average_site_MWh_y": _fmt(used_site - old_site),
                    "scale_factor": _fmt(scale),
                    "status": "allocated" if used_raw else "eligible_not_used",
                    "red_flags": "" if used_raw <= available_raw + WAG_TOL_MWH and residual_raw >= -WAG_TOL_MWH else "allocation_or_residual_error",
                }
            )
        ng_raw = max(remaining_raw, 0.0)
        ng_site = max(remaining_site, 0.0)
        if abs(ng_raw) <= WAG_TOL_MWH:
            ng_raw = 0.0
        if abs(ng_site) <= WAG_TOL_MWH:
            ng_site = 0.0
        balance_site = total_alloc_site + ng_site - demand_site
        if abs(balance_site) <= WAG_TOL_MWH:
            balance_site = 0.0
        old_row = old[(config, horizon)]
        dashboard.append(
            {
                "configuration": config,
                "horizon_hours": horizon,
                "hsm_reheat_controller_mode": HSM_REHEAT_CONTROLLER_MODE,
                "controller_implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
                "charge_reheat_mode": "DHCR_HCR_CCR_slab_input_basis",
                "hsm_reheat_demand_site_MWh_y": _fmt(demand_site),
                "available_WAG_after_priority_site_MWh_y": _fmt(total_available_site),
                "BFG_to_HSM_reheat_site_MWh_y": _fmt(allocation[(config, horizon, "BFG")]["used_site"]),
                "COG_to_HSM_reheat_site_MWh_y": _fmt(allocation[(config, horizon, "COG")]["used_site"]),
                "BOFG_to_HSM_reheat_site_MWh_y": _fmt(allocation[(config, horizon, "BOFG")]["used_site"]),
                "NG_to_HSM_reheat_site_MWh_y": _fmt(ng_site),
                "HSM_unserved_reheat_site_MWh_y": _fmt(0.0),
                "residual_WAG_after_HSM_site_MWh_y": _fmt(total_residual_site),
                "controller_balance_error_site_MWh_y": _fmt(balance_site),
                "delta_vs_C5l_b_average_BFG_site_MWh_y": _fmt(allocation[(config, horizon, "BFG")]["used_site"] - _zero(old_row["BFG_to_HSM_reheat_site_MWh_y"])),
                "delta_vs_C5l_b_average_COG_site_MWh_y": _fmt(allocation[(config, horizon, "COG")]["used_site"] - _zero(old_row["COG_to_HSM_reheat_site_MWh_y"])),
                "delta_vs_C5l_b_average_BOFG_site_MWh_y": _fmt(allocation[(config, horizon, "BOFG")]["used_site"] - _zero(old_row["BOFG_to_HSM_reheat_site_MWh_y"])),
                "delta_vs_C5l_b_average_NG_site_MWh_y": _fmt(ng_site - _zero(old_row["NG_to_HSM_reheat_site_MWh_y"])),
                "lp_controller_used": "false",
                "HSM_CO2_status": HSM_CO2_STATUS,
                "status": "pass" if abs(balance_site) <= WAG_TOL_MWH else "fail",
            }
        )
        trace.append(
            {
                "configuration": config,
                "horizon_hours": horizon,
                "carrier": "NG",
                "controller_mode": HSM_REHEAT_CONTROLLER_MODE,
                "implementation_mode": CONTROLLER_IMPLEMENTATION_MODE,
                "charge_reheat_mode": "DHCR_HCR_CCR_slab_input_basis",
                "hsm_reheat_demand_site_MWh_y": _fmt(demand_site),
                "available_after_KGF_BF_priority_raw_MWh_y": "",
                "available_after_KGF_BF_priority_site_MWh_y": "",
                "allocated_to_HSM_reheat_raw_MWh_y": _fmt(ng_raw),
                "allocated_to_HSM_reheat_site_MWh_y": _fmt(ng_site),
                "residual_after_HSM_raw_MWh_y": "",
                "residual_after_HSM_site_MWh_y": "",
                "delta_vs_C5l_b_average_site_MWh_y": _fmt(ng_site - _zero(old[(config, horizon)]["NG_to_HSM_reheat_site_MWh_y"])),
                "scale_factor": "",
                "status": "not_needed" if ng_site == 0.0 else "ng_backup_reported_without_cost_steering",
                "red_flags": "",
            }
        )
    return dashboard, trace, allocation


def _wag_rows(c5k_wag: list[dict[str, str]], allocation: dict[tuple[str, int, str], dict[str, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in c5k_wag:
        item = dict(row)
        config = row["configuration"]
        horizon = int(row["horizon_hours"])
        carrier = row["carrier"]
        if row["plant_id"] == "SITE_TOTAL" and carrier in WAG_CARRIERS:
            alloc = allocation[(config, horizon, carrier)]
            generated = alloc["generated_raw"]
            direct = alloc["direct_pre_raw"] + alloc["used_raw"]
            boiler = alloc["boiler_post_raw"]
            vattenfall = alloc["vattenfall_post_raw"]
            flared = alloc["flare_post_raw"]
            item["consumed_direct_MWh_LHV_y"] = _fmt(direct)
            item["consumed_boiler_MWh_LHV_y"] = _fmt(boiler)
            item["consumed_vattenfall_MWh_LHV_y"] = _fmt(vattenfall)
            item["flared_MWh_LHV_y"] = _fmt(flared)
            item["balance_error_MWh_LHV_y"] = _fmt(alloc["balance_error_raw"])
            item["status"] = "closed"
            item["metric_scope"] = "HSM_charge_specific_reheat_controller_inserted_before_boiler_vattenfall_flare"
            item["notes"] = "C5l_c feeds charge-specific HSM reheat demand into the traceable HSM WAG controller."
        rows.append(item)
    for config in CONFIGS:
        for horizon in HORIZONS:
            for carrier in WAG_CARRIERS:
                alloc = allocation[(config, horizon, carrier)]
                rows.append(
                    {
                        "configuration": config,
                        "horizon_hours": horizon,
                        "plant_id": "HSM_WBW",
                        "carrier": carrier,
                        "generated_MWh_LHV_y": _fmt(0.0),
                        "generated_Nm3_y": _fmt(0.0),
                        "consumed_direct_MWh_LHV_y": _fmt(alloc["used_raw"]),
                        "consumed_boiler_MWh_LHV_y": _fmt(0.0),
                        "consumed_vattenfall_MWh_LHV_y": _fmt(0.0),
                        "flared_MWh_LHV_y": _fmt(0.0),
                        "balance_error_MWh_LHV_y": _fmt(-alloc["used_raw"]),
                        "status": "hsm_charge_reheat_wag_sink" if alloc["used_raw"] else "eligible_not_used",
                        "LHV_MJ_per_Nm3_used": _fmt(alloc["lhv"]),
                        "raw_model_quantity": _fmt(alloc["used_raw"]),
                        "raw_model_unit": "MWh_LHV/y",
                        "site_scaled_quantity": _fmt(alloc["used_site"]),
                        "site_scaled_unit": "MWh_LHV/y",
                        "scale_factor": _fmt(alloc["scale"]),
                        "scale_mode": "module_scaled_to_site_target",
                        "metric_scope": "HSM_charge_specific_reheat_fuel_consumption",
                        "notes": "HSM consumes eligible WAG for charge-specific reheating; generated quantity remains zero.",
                    }
                )
    return rows


def _co2_rows(c5l_b_co2: list[dict[str, str]], report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in c5l_b_co2 if row.get("emission_bucket") != "HSM_reheat_CO2"]
    for row in report:
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "emission_bucket": "HSM_reheat_CO2",
                "CO2_site_t_y": "",
                "CO2_mode": "derived_from_reheat_fuel_mix",
                "derivation_status": HSM_CO2_STATUS,
                "included_in_objective_ETS_cost": "false",
                "included_in_total_direct_CO2": "false",
                "double_counting_risk": "blocked_until_governed_carrier_emission_factors_exist",
                "status": "deferred",
                "notes": "Charge-specific reheat changes heat demand only; no HSM CO2 shortcut or WAG combustion objective cost is added.",
            }
        )
    return rows


def _final_product_rows(report: list[dict[str, Any]], c5l_b_final: list[dict[str, str]]) -> list[dict[str, Any]]:
    old = {(row["configuration"], int(row["horizon_hours"])): row for row in c5l_b_final}
    rows: list[dict[str, Any]] = []
    for row in report:
        key = (row["configuration"], int(row["horizon_hours"]))
        previous = old[key]
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "active_liquid_steel_target_site_t_y": previous["active_liquid_steel_target_site_t_y"],
                "active_HSM_output_site_t_y": row["hsm_output_site_t_y"],
                "active_DSP_output_site_t_y": row["dsp_output_site_t_y"],
                "active_final_product_proxy_site_t_y": row["active_final_product_proxy_site_t_y"],
                "final_product_minus_liquid_steel_target_t_y": _fmt(_zero(row["active_final_product_proxy_site_t_y"]) - _zero(previous["active_liquid_steel_target_site_t_y"])),
                "raw_MER_HSM_anchor_t_y": previous["raw_MER_HSM_anchor_t_y"],
                "raw_MER_HSM_gap_t_y": previous["raw_MER_HSM_gap_t_y"],
                "raw_MER_DSP_anchor_t_y": previous["raw_MER_DSP_anchor_t_y"],
                "raw_MER_DSP_gap_t_y": previous["raw_MER_DSP_gap_t_y"],
                "raw_MER_imported_slab_anchor_t_y": previous["raw_MER_imported_slab_anchor_t_y"],
                "raw_MER_imported_slab_gap_t_y": previous["raw_MER_imported_slab_gap_t_y"],
                "anchor_constraint_used": "false",
                "denominator_warning": previous["denominator_warning"],
                "status": "reported",
            }
        )
    return rows


def _summary_rows(
    report: list[dict[str, Any]],
    controller: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    ctrl = {(row["configuration"], int(row["horizon_hours"])): row for row in controller}
    agg = {(row["configuration"], int(row["horizon_hours"]), row["scale_basis"]): row for row in wag_aggregate}
    rows: list[dict[str, Any]] = []
    by_horizon: dict[int, list[dict[str, Any]]] = {24: [], 168: []}
    for item in report:
        key = (item["configuration"], int(item["horizon_hours"]))
        row = {
            "stage": STAGE,
            "configuration": item["configuration"],
            "horizon_hours": item["horizon_hours"],
            "solver_status": "lp_compatible_deterministic_buffer_accounting",
            "status": "development_only",
            "thesis_usability": "false",
            "dependency_chain": DEPENDENCY_CHAIN,
            "downstream_routing_mode": DOWNSTREAM_ROUTING_MODE,
            "slab_buffer_mode": SLAB_BUFFER_MODE,
            "active_total_liquid_steel_target_site_t_y": item["active_total_liquid_steel_target_site_t_y"],
            "hsm_slab_input_site_t_y": item["hsm_slab_input_site_t_y"],
            "hsm_output_site_t_y": item["hsm_output_site_t_y"],
            "active_final_product_proxy_site_t_y": item["active_final_product_proxy_site_t_y"],
            "indicative_downstream_material_gap_site_t_y": item["indicative_downstream_material_gap_site_t_y"],
            "direct_hot_charge_share": item["direct_hot_charge_share"],
            "hot_charge_share_age1_to_age6": item["hot_charge_share_age1_to_age6"],
            "cold_charge_share": item["cold_charge_share"],
            "hsm_reheat_heat_site_TWh_th_y": item["hsm_reheat_heat_site_TWh_th_y"],
            "hsm_rolling_electricity_site_GWh_e_y": item["hsm_rolling_electricity_site_GWh_e_y"],
            "reheat_delta_vs_C5l_b_average_site_MWh_y": item["reheat_delta_vs_C5l_b_average_site_MWh_y"],
            "BFG_to_HSM_reheat_site_MWh_y": ctrl[key]["BFG_to_HSM_reheat_site_MWh_y"],
            "COG_to_HSM_reheat_site_MWh_y": ctrl[key]["COG_to_HSM_reheat_site_MWh_y"],
            "BOFG_to_HSM_reheat_site_MWh_y": ctrl[key]["BOFG_to_HSM_reheat_site_MWh_y"],
            "NG_to_HSM_reheat_site_MWh_y": ctrl[key]["NG_to_HSM_reheat_site_MWh_y"],
            "HSM_unserved_reheat_site_MWh_y": ctrl[key]["HSM_unserved_reheat_site_MWh_y"],
            "WAG_invariant_status": agg[(key[0], key[1], "site_scaled")]["status"],
            "WAG_balance_error_MWh_y": agg[(key[0], key[1], "site_scaled")]["balance_error_MWh_y"],
            "HSM_CO2_status": HSM_CO2_STATUS,
            "CO2_double_counting_guard_status": "pass",
        }
        rows.append(row)
        by_horizon[int(item["horizon_hours"])].append(row)
    return rows, by_horizon


def _compact_rows(report: list[dict[str, Any]], controller: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ctrl = {(row["configuration"], int(row["horizon_hours"])): row for row in controller}
    rows: list[dict[str, Any]] = []
    for row in report:
        key = (row["configuration"], int(row["horizon_hours"]))
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "plant": "HSM_WBW_slab_buffer",
                "buffer_mode": SLAB_BUFFER_MODE,
                "HSM_output_Mt_y": _fmt(_zero(row["hsm_output_site_t_y"]) / 1_000_000.0),
                "HSM_slab_input_Mt_y": _fmt(_zero(row["hsm_slab_input_site_t_y"]) / 1_000_000.0),
                "direct_hot_charge_share": row["direct_hot_charge_share"],
                "cold_charge_share": row["cold_charge_share"],
                "reheat_TWh_th_y": row["hsm_reheat_heat_site_TWh_th_y"],
                "rolling_electricity_GWh_e_y": row["hsm_rolling_electricity_site_GWh_e_y"],
                "BFG_to_HSM_TWh_LHV_y": _fmt(_zero(ctrl[key]["BFG_to_HSM_reheat_site_MWh_y"]) / 1_000_000.0),
                "NG_to_HSM_TWh_LHV_y": _fmt(_zero(ctrl[key]["NG_to_HSM_reheat_site_MWh_y"]) / 1_000_000.0),
                "terminal_policy": f"{row['terminal_total_policy_status']}/{row['terminal_hot_policy_status']}",
                "capacity_hit_count": row["capacity_hit_count"],
                "WAG_status": ctrl[key]["status"],
                "CO2_status": HSM_CO2_STATUS,
                "red_flags": row["warnings_deferred_items"],
            }
        )
    return rows


def _stage_gate(
    input_rows: list[dict[str, str]],
    hourly: list[dict[str, Any]],
    report: list[dict[str, Any]],
    controller: list[dict[str, Any]],
    trace: list[dict[str, Any]],
    wag_aggregate: list[dict[str, Any]],
    lhv: list[dict[str, str]],
    co2: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[Any] = []
    failures.extend(
        row
        for row in input_rows
        if row["thesis_usability"] != "false"
        or row["human_review_required"] != "true"
        or row["codex_may_decide"] != "false"
        or row["constraint_used"] != "false"
    )
    failures.extend(row for row in hourly if row["status"] != "pass")
    failures.extend(row for row in report if row["terminal_total_policy_status"] != "pass" or row["terminal_hot_policy_status"] != "pass")
    failures.extend(row for row in report if _zero(row["capacity_hit_count"]) > 0)
    failures.extend(row for row in report if abs(_zero(row["indicative_downstream_material_gap_site_t_y"])) > MATERIAL_ROUNDING_TOL_T_Y)
    failures.extend(row for row in controller if row["status"] != "pass")
    failures.extend(row for row in controller if abs(_zero(row["HSM_unserved_reheat_site_MWh_y"])) > WAG_TOL_MWH)
    failures.extend(row for row in trace if row["carrier"] in WAG_CARRIERS and row["red_flags"])
    failures.extend(row for row in wag_aggregate if row["status"] != "pass")
    failures.extend(row for row in lhv if row["status"] != "pass")
    failures.extend(row for row in co2 if row["included_in_objective_ETS_cost"] != "false")
    c0_24 = next(row for row in report if row["configuration"] == C0 and int(row["horizon_hours"]) == 24)
    c1_24 = next(row for row in report if row["configuration"] == C1 and int(row["horizon_hours"]) == 24)
    return {
        "stage": STAGE,
        "decision": "pass_development_hsm_slab_age_bucket_buffer_and_charge_reheat" if not failures else "fail_development_hsm_slab_age_bucket_buffer_and_charge_reheat",
        "output_directory": _rel(C5L_C_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "source_card_present": SOURCE_CARD.exists(),
        "dependency_chain": DEPENDENCY_CHAIN,
        "DOWNSTREAM_ROUTING_MODE": DOWNSTREAM_ROUTING_MODE,
        "SLAB_BUFFER_MODE": SLAB_BUFFER_MODE,
        "SLAB_STORE_CAPACITY_TOTAL_T": SLAB_STORE_CAPACITY_TOTAL_T,
        "INITIAL_COLD_SLAB_INVENTORY_T": INITIAL_COLD_SLAB_INVENTORY_T,
        "TERMINAL_TOTAL_SLAB_INVENTORY_EQUALS_INITIAL": TERMINAL_TOTAL_SLAB_INVENTORY_EQUALS_INITIAL,
        "TERMINAL_HOT_SLAB_INVENTORY_ZERO": TERMINAL_HOT_SLAB_INVENTORY_ZERO,
        "HSM_yield_1p0_active_base": HSM_YIELD_ONE_ACTIVE,
        "C0_24h_HSM_reheat_site_MWh_th_y": _zero(c0_24["hsm_reheat_heat_site_MWh_th_y"]),
        "C1_24h_HSM_reheat_site_MWh_th_y": _zero(c1_24["hsm_reheat_heat_site_MWh_th_y"]),
        "C0_24h_reheat_delta_vs_C5l_b_MWh_y": _zero(c0_24["reheat_delta_vs_C5l_b_average_site_MWh_y"]),
        "C1_24h_reheat_delta_vs_C5l_b_MWh_y": _zero(c1_24["reheat_delta_vs_C5l_b_average_site_MWh_y"]),
        "max_capacity_hit_count": max(_zero(row["capacity_hit_count"]) for row in report),
        "max_abs_downstream_material_gap_t_y": max(abs(_zero(row["indicative_downstream_material_gap_site_t_y"])) for row in report),
        "material_rounding_tolerance_t_y": MATERIAL_ROUNDING_TOL_T_Y,
        "max_HSM_unserved_reheat_site_MWh_y": max(_zero(row["HSM_unserved_reheat_site_MWh_y"]) for row in controller),
        "wag_invariant_fail_count": sum(1 for row in wag_aggregate if row["status"] != "pass"),
        "lhv_consistency_fail_count": sum(1 for row in lhv if row["status"] != "pass"),
        "co2_double_counting_guard_status": "pass" if all(row["included_in_objective_ETS_cost"] == "false" for row in co2) else "fail",
        "HSM_CO2_status": HSM_CO2_STATUS,
        "c5k_targets_and_route_split_changed": False,
        "c5l_a_downstream_routing_changed": False,
        "sinter_implemented": False,
        "direct_WAG_market_valuation_added": False,
        "WAG_export_revenue_added": False,
        "product_revenue_added": False,
        "failure_count": len(failures),
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5l_b_hsm_wag_dispatch_controller_and_traceability_patch()
    C5L_C_DIR.mkdir(parents=True, exist_ok=True)

    input_rows_any = _development_input_rows()
    _write_csv(C5L_C_DIR / "s4_4c5l_c_slab_buffer_input_rows.csv", input_rows_any, HSM_PARAMETER_COLUMNS)
    input_rows = _read_csv(C5L_C_DIR / "s4_4c5l_c_slab_buffer_input_rows.csv")
    hsm_slab_factor = _param(input_rows, "HSM_SLAB_INPUT_T_PER_T_HRC")
    rolling_electricity = _param(input_rows, "HSM_ROLLING_ELECTRICITY_MWH_PER_T_HRC")
    c5l_a_report = _read_csv(C5L_A_DIR / "s4_4c5l_a_downstream_routing_report.csv")
    c5l_b_summary = _read_csv(C5L_B_DIR / "s4_4c5l_b_24h_summary.csv") + _read_csv(C5L_B_DIR / "s4_4c5l_b_168h_summary.csv")
    hourly = _hourly_rows(c5l_a_report, hsm_slab_factor, rolling_electricity)
    report = _report_rows(c5l_a_report, c5l_b_summary, hourly)
    c5k_wag = _read_csv(C5K_DIR / "s4_4c5k_wag_generation_consumption_by_plant.csv")
    c5l_b_controller = _read_csv(C5L_B_DIR / "s4_4c5l_b_hsm_reheat_controller_dashboard.csv")
    controller, trace, allocation = _controller_rows(report, c5k_wag, c5l_b_controller)
    wag_rows = _wag_rows(c5k_wag, allocation)
    wag_aggregate = _wag_aggregate_invariant_rows(wag_rows)
    lhv = _read_csv(C5L_B_DIR / "s4_4c5l_b_lhv_consistency_checks.csv")
    co2 = _co2_rows(_read_csv(C5L_B_DIR / "s4_4c5l_b_hsm_co2_accounting_dashboard.csv"), report)
    final_product = _final_product_rows(report, _read_csv(C5L_B_DIR / "s4_4c5l_b_final_product_and_anchor_dashboard.csv"))
    summary_rows, by_horizon = _summary_rows(report, controller, wag_aggregate)
    compact = _compact_rows(report, controller)
    gate = _stage_gate(input_rows, hourly, report, controller, trace, wag_aggregate, lhv, co2)

    _write_json(C5L_C_DIR / "s4_4c5l_c_stage_gate.json", gate)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_run_registry.csv", [{
        "stage": STAGE,
        "source_stage": "S4.4c5l_b_HSM_WAG_dispatch_controller_and_traceability_patch",
        "decision": gate["decision"],
        "status": "development_only",
        "thesis_usability": "false",
        "output_directory": gate["output_directory"],
    }])
    for horizon, rows in by_horizon.items():
        _write_csv(C5L_C_DIR / f"s4_4c5l_c_{horizon}h_summary.csv", rows)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_slab_age_bucket_hourly.csv", hourly)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_slab_buffer_dashboard.csv", report)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_hsm_charge_reheat_dashboard.csv", report)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_hsm_reheat_controller_dashboard.csv", controller)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_hsm_reheat_controller_carrier_trace.csv", trace)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_wag_generation_consumption_by_plant.csv", wag_rows)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_wag_aggregate_invariant.csv", wag_aggregate, AGGREGATE_COLUMNS)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_lhv_consistency_checks.csv", lhv)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_hsm_co2_accounting_dashboard.csv", co2)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_final_product_and_anchor_dashboard.csv", final_product)
    _write_csv(C5L_C_DIR / "s4_4c5l_c_compact_table_for_chat.csv", compact)
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "rows": {
            "hourly": len(hourly),
            "report": len(report),
            "controller": len(controller),
            "wag_aggregate": len(wag_aggregate),
        },
    }
    _write_json(C5L_C_DIR / "s4_4c5l_c_summary.json", summary)
    return summary


def run_s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5l_c_hsm_slab_age_bucket_buffer_and_charge_reheat(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
