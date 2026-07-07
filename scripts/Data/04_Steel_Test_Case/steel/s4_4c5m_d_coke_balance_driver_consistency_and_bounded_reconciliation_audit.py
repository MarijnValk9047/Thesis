"""S4.4c5m_d coke-balance driver consistency and bounded reconciliation audit.

This stage is diagnostic only. It audits whether the open C5m_b/C5m_c
BF/KGF coke-balance gap is partly caused by a stale BF hot-metal driver, then
evaluates evidence-bounded reconciliation scenarios. It does not change the
accepted baseline model, coefficients, production targets, WAG allocation, or
CO2 accounting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .s4_4c5f_coking_plant_minimal_parameterisation import (
    C0,
    C1,
    C5F_DIR,
    CONFIGS,
    HORIZONS,
    S4_ROOT,
    _fmt,
    _read_csv,
    _write_csv,
    _write_json,
    _zero,
)
from .s4_4c5h_blast_furnace_controller_parameterisation import BF_COKE_RATE_T_PER_T_HM
from .s4_4c5j_bof_osf_minimal_parameterisation import C5J_DIR
from .s4_4c5k_production_policy_and_route_split_normalisation import C5K_DIR
from .s4_4c5m_b_active_plant_ledger_coverage_and_bf_kgf_kpi_integration import C5M_B_DIR
from .s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit import (
    BF_COKE_RATE_HIGH,
    BF_COKE_RATE_LOW,
    C5M_C_DIR,
    KGF_PUBLIC_COKE_ANCHOR_T_Y,
    run_s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit,
)


STAGE = "S4.4c5m_d_coke_balance_driver_consistency_and_bounded_reconciliation_audit"
C5M_D_DIR = S4_ROOT / "s4_4c5m_d_coke_balance_driver_consistency_and_bounded_reconciliation_audit"
DEPENDENCY_CHAIN = "C5f -> C5g -> C5h -> C5j -> C5k -> C5l_d -> C5m -> C5m_a -> C5m_b -> C5m_c -> C5m_d"
PATTERN_AUDIT_RESULT = (
    "matched_existing_C5_csv_json_stage_gate_compact_table_redflag_pattern;"
    "bounded_reconciliation_scenarios_are_diagnostic_only"
)
TOL_T = 1.0
NEAR_ANCHOR_TOL = 0.05


def _rel(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _by_key(rows: list[dict[str, str]]) -> dict[tuple[str, int], dict[str, str]]:
    return {(row["configuration"], int(row["horizon_hours"])): row for row in rows}


def _param_map(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["parameter_id"]: row for row in rows}


def _range_low_high(row: dict[str, str]) -> tuple[float | None, float | None]:
    low = row.get("low_value", "")
    high = row.get("high_value", "")
    return (_zero(low) if low not in ("", None) else None, _zero(high) if high not in ("", None) else None)


def _range_status(value: float, low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "no_governed_range"
    if value < low - 1e-12:
        return "below_supported_range"
    if value > high + 1e-12:
        return "above_supported_range"
    return "within_supported_range"


def _bool(value: bool) -> str:
    return str(value).lower()


def _source_payload() -> dict[str, Any]:
    current = _by_key(_read_csv(C5M_C_DIR / "s4_4c5m_c_current_coke_balance_root_cause.csv"))
    c5m_b_totals = _by_key(_read_csv(C5M_B_DIR / "s4_4c5m_b_modelled_totals.csv"))
    c5k = _by_key(_read_csv(C5K_DIR / "s4_4c5k_route_split_normalisation_report.csv"))
    c5j = _by_key(_read_csv(C5J_DIR / "s4_4c5j_bof_osf_report.csv"))
    kgf_params = _param_map(_read_csv(C5F_DIR / "s4_4c5f_kgf_parameter_values.csv"))
    c5m_c_gate = json.loads((C5M_C_DIR / "s4_4c5m_c_stage_gate.json").read_text(encoding="utf-8"))
    return locals()


def _kgf_coefficients(payload: dict[str, Any]) -> dict[str, float]:
    params = payload["kgf_params"]
    cog_yield_nm3 = _zero(params["COG_YIELD_NM3_PER_T_COKE"]["base_value"])
    cog_lhv = _zero(params["COG_LHV_MJ_PER_NM3"]["base_value"])
    under_gj = _zero(params["KGF_UNDERFIRING_GJ_PER_T_COKE"]["base_value"])
    gross_mwh = cog_yield_nm3 * cog_lhv / 3600.0
    under_mwh = under_gj / 3.6
    return {
        "dry_coal_t_per_t_coke": _zero(params["DRY_COAL_PER_COKE_TPT"]["base_value"]),
        "electricity_MWh_per_t_coke": _zero(params["KGF_ELECTRICITY_MWH_PER_T_COKE"]["base_value"]),
        "steam_proxy_MWh_per_t_coke": _zero(params["KGF_STEAM_GJ_PER_T_COKE"]["base_value"]) / 3.6,
        "steam_mass_t_per_t_coke": _zero(params["KGF_STEAM_T_PER_T_COKE_DIAGNOSTIC"]["base_value"]),
        "gross_COG_MWh_per_t_coke": gross_mwh,
        "underfiring_MWh_per_t_coke": under_mwh,
        "net_COG_surplus_MWh_per_t_coke": gross_mwh - under_mwh,
        "direct_CO2_t_per_t_coke": _zero(params["KGF_DIRECT_CO2_T_PER_T_COKE"]["base_value"]),
    }


def _driver_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            current = payload["current"][key]
            c5k = payload["c5k"][key]
            c5j = payload["c5j"][key]
            bf_coke = _zero(current["BF_coke_demand_site_t_y"])
            rate = _zero(current["BF_COKE_RATE_T_PER_T_HM_active_value"]) or BF_COKE_RATE_T_PER_T_HM
            implied_hm = bf_coke / rate if rate else 0.0
            c5k_hm = _zero(c5k["bf_hot_metal_normalised_site_t_y"])
            c5k_bof_hm = _zero(c5k["bof_hot_metal_input_site_t_y"])
            c5j_bof_hm = _zero(c5j["bof_hot_metal_input_site_t_y"])
            diff = implied_hm - c5k_hm
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "BF_coke_demand_from_C5m_c_site_t_y": _fmt(bf_coke),
                    "active_BF_coke_rate_t_per_t_HM": _fmt(rate),
                    "implied_BF_hot_metal_from_coke_demand_site_t_y": _fmt(implied_hm),
                    "C5k_no_buffer_BF_hot_metal_normalised_site_t_y": _fmt(c5k_hm),
                    "C5k_BOF_hot_metal_input_site_t_y": _fmt(c5k_bof_hm),
                    "C5j_BOF_hot_metal_input_site_t_y": _fmt(c5j_bof_hm),
                    "difference_implied_driver_minus_C5k_no_buffer_HM_t_y": _fmt(diff),
                    "difference_implied_driver_minus_C5k_no_buffer_HM_Mt_y": _fmt(diff / 1_000_000.0),
                    "BF_COKE_DEMAND_DRIVER_SOURCE": "C5h/C5m_c_pre_normalisation_BF_hot_metal_driver",
                    "C5K_NO_BUFFER_DRIVER_SOURCE": "C5k_bf_hot_metal_normalised_site_t_y",
                    "BF_COKE_DEMAND_DRIVER_MATCHES_C5K_NO_BUFFER_HM": _bool(abs(diff) <= TOL_T),
                    "redflag_bf_coke_demand_driver_mismatch": _bool(abs(diff) > TOL_T),
                    "driver_consistency_status": "fail_driver_mismatch_report_only" if abs(diff) > TOL_T else "pass",
                    "baseline_changed": "false",
                }
            )
    return rows


def _kgf_anchor_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        public_anchor = KGF_PUBLIC_COKE_ANCHOR_T_Y[config]
        for horizon in HORIZONS:
            current = payload["current"][(config, horizon)]
            current_output = _zero(current["total_KGF_coke_output_site_t_y"])
            gap = current_output - public_anchor
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    "current_C5_KGF_coke_output_site_t_y": _fmt(current_output),
                    "public_KGF_anchor_output_site_t_y": _fmt(public_anchor),
                    "KGF1_public_anchor_site_t_y": _fmt(1_000_000.0),
                    "KGF2_public_anchor_site_t_y": _fmt(800_000.0 if config == C0 else 0.0),
                    "gap_current_minus_public_anchor_t_y": _fmt(gap),
                    "gap_current_minus_public_anchor_Mt_y": _fmt(gap / 1_000_000.0),
                    "current_output_basis": "active_C5f_production_scaled_coke_output_inherited_by_C5m_b_C5m_c",
                    "public_anchor_basis": "source_cards/Coking_Plants_Parameters.md_validation_anchor_not_dispatch_constraint",
                    "redflag_kgf_current_output_below_public_anchor": _bool(gap < -TOL_T),
                    "baseline_changed": "false",
                }
            )
    return rows


def _driver_value(driver_basis: str, driver_row: dict[str, Any]) -> float:
    if driver_basis == "current_C5m_c_coke_demand_driver":
        return _zero(driver_row["implied_BF_hot_metal_from_coke_demand_site_t_y"])
    if driver_basis == "C5k_no_buffer_BF_hot_metal_driver":
        return _zero(driver_row["C5k_no_buffer_BF_hot_metal_normalised_site_t_y"])
    raise ValueError(driver_basis)


def _scenario_defs(current_kgf: float, anchor_kgf: float, driver: float) -> list[tuple[str, str, float, float]]:
    return [
        ("S0_current_rate_current_KGF", "current BF coke rate + current KGF output", BF_COKE_RATE_T_PER_T_HM, current_kgf),
        ("S1_low_rate_current_KGF", "low BF coke rate + current KGF output", BF_COKE_RATE_LOW, current_kgf),
        ("S2_current_rate_public_KGF_anchor", "current BF coke rate + KGF public anchor output", BF_COKE_RATE_T_PER_T_HM, anchor_kgf),
        ("S3_low_rate_public_KGF_anchor", "low BF coke rate + KGF public anchor output", BF_COKE_RATE_LOW, anchor_kgf),
        ("S4_solve_rate_current_KGF", "solve BF coke rate needed with current KGF output", current_kgf / driver if driver else 0.0, current_kgf),
        ("S5_solve_rate_public_KGF_anchor", "solve BF coke rate needed with KGF public anchor output", anchor_kgf / driver if driver else 0.0, anchor_kgf),
        ("S6_solve_KGF_current_rate", "solve KGF output needed at current BF coke rate", BF_COKE_RATE_T_PER_T_HM, driver * BF_COKE_RATE_T_PER_T_HM),
        ("S7_solve_KGF_low_rate", "solve KGF output needed at low BF coke rate", BF_COKE_RATE_LOW, driver * BF_COKE_RATE_LOW),
    ]


def _scenarios(payload: dict[str, Any], driver_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(row["configuration"], int(row["horizon_hours"])): row for row in driver_rows}
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        anchor = KGF_PUBLIC_COKE_ANCHOR_T_Y[config]
        for horizon in HORIZONS:
            key = (config, horizon)
            driver_row = by_key[key]
            current_kgf = _zero(payload["current"][key]["total_KGF_coke_output_site_t_y"])
            for basis in ("current_C5m_c_coke_demand_driver", "C5k_no_buffer_BF_hot_metal_driver"):
                driver = _driver_value(basis, driver_row)
                for scenario_id, scenario_label, coke_rate, kgf_output in _scenario_defs(current_kgf, anchor, driver):
                    bf_demand = driver * coke_rate
                    gap = kgf_output - bf_demand
                    gap_closed = gap >= -TOL_T
                    bf_status = _range_status(coke_rate, BF_COKE_RATE_LOW, BF_COKE_RATE_HIGH)
                    near_anchor = abs(kgf_output - anchor) <= anchor * NEAR_ANCHOR_TOL
                    rows.append(
                        {
                            "configuration": config,
                            "horizon_hours": horizon,
                            "driver_basis": basis,
                            "scenario_id": scenario_id,
                            "scenario_label": scenario_label,
                            "BF_driver_used_site_t_y": _fmt(driver),
                            "BF_coke_rate_t_per_t_HM": _fmt(coke_rate),
                            "BF_coke_demand_site_t_y": _fmt(bf_demand),
                            "KGF_output_site_t_y": _fmt(kgf_output),
                            "public_KGF_anchor_output_site_t_y": _fmt(anchor),
                            "coke_balance_gap_site_t_y": _fmt(gap),
                            "gap_pct_of_BF_demand": _fmt(gap / bf_demand * 100.0 if bf_demand else 0.0),
                            "gap_closed": _bool(gap_closed),
                            "within_BF_coke_rate_range": _bool(bf_status == "within_supported_range"),
                            "BF_coke_rate_range_status": bf_status,
                            "within_near_public_KGF_anchor": _bool(near_anchor),
                            "required_KGF_output_exceeds_public_anchor": _bool(kgf_output > anchor + TOL_T),
                            "source_support_status": _source_support_status(scenario_id, gap_closed, bf_status, kgf_output, anchor),
                            "baseline_changed": "false",
                        }
                    )
    return rows


def _source_support_status(scenario_id: str, gap_closed: bool, bf_status: str, kgf_output: float, anchor: float) -> str:
    if not gap_closed:
        return "does_not_close_gap"
    if bf_status != "within_supported_range":
        return f"unsupported_BF_coke_rate_{bf_status}"
    if kgf_output > anchor + TOL_T:
        return "unsupported_KGF_output_above_public_anchor"
    if scenario_id in {"S3_low_rate_public_KGF_anchor", "S5_solve_rate_public_KGF_anchor", "S7_solve_KGF_low_rate"}:
        return "evidence_bounded_scenario_candidate"
    return "diagnostic_closure_candidate"


def _kpi_propagation(payload: dict[str, Any], scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coeff = _kgf_coefficients(payload)
    rows: list[dict[str, Any]] = []
    for row in scenarios:
        key = (row["configuration"], int(row["horizon_hours"]))
        current_output = _zero(payload["current"][key]["total_KGF_coke_output_site_t_y"])
        scenario_output = _zero(row["KGF_output_site_t_y"])
        if abs(scenario_output - current_output) <= TOL_T:
            continue
        delta = scenario_output - current_output
        totals = payload["c5m_b_totals"][key]
        delta_elec = delta * coeff["electricity_MWh_per_t_coke"]
        delta_steam_mwh = delta * coeff["steam_proxy_MWh_per_t_coke"]
        delta_steam_t = delta * coeff["steam_mass_t_per_t_coke"]
        delta_cog = delta * coeff["gross_COG_MWh_per_t_coke"]
        delta_under = delta * coeff["underfiring_MWh_per_t_coke"]
        delta_surplus = delta * coeff["net_COG_surplus_MWh_per_t_coke"]
        delta_co2 = delta * coeff["direct_CO2_t_per_t_coke"]
        anchor = _zero(row["public_KGF_anchor_output_site_t_y"])
        rows.append(
            {
                "configuration": row["configuration"],
                "horizon_hours": row["horizon_hours"],
                "driver_basis": row["driver_basis"],
                "scenario_id": row["scenario_id"],
                "scenario_KGF_output_site_t_y": row["KGF_output_site_t_y"],
                "current_KGF_output_site_t_y": _fmt(current_output),
                "delta_KGF_coke_output_t_y": _fmt(delta),
                "delta_dry_coal_input_t_y": _fmt(delta * coeff["dry_coal_t_per_t_coke"]),
                "delta_KGF_electricity_MWh_y": _fmt(delta_elec),
                "delta_KGF_steam_proxy_MWh_y": _fmt(delta_steam_mwh),
                "delta_KGF_steam_mass_t_y": _fmt(delta_steam_t),
                "delta_COG_generation_MWh_LHV_y": _fmt(delta_cog),
                "delta_KGF_underfiring_MWh_LHV_y": _fmt(delta_under),
                "delta_net_COG_surplus_MWh_LHV_y": _fmt(delta_surplus),
                "delta_KGF_CO2_t_y": _fmt(delta_co2),
                "process_electricity_total_after_scenario_MWh_y": _fmt(_zero(totals["new_process_electricity_including_BF_KGF_site_MWh_e_y"]) + delta_elec),
                "WAG_generation_total_delta_MWh_y": _fmt(delta_surplus),
                "diagnostic_CO2_total_after_scenario_t_y": _fmt(_zero(totals["new_diagnostic_CO2_including_KGF_site_t_y"]) + delta_co2),
                "materially_changes_WAG_surplus": _bool(abs(delta_surplus) > 1_000.0),
                "materially_changes_CO2": _bool(abs(delta_co2) > 1_000.0),
                "materially_changes_process_electricity": _bool(abs(delta_elec) > 1_000.0),
                "exceeds_public_KGF_anchor": _bool(scenario_output > anchor + TOL_T),
                "merely_moves_current_C5_output_back_to_public_anchor": _bool(abs(scenario_output - anchor) <= TOL_T),
                "baseline_changed": "false",
            }
        )
    return rows


def _efficiency_what_if(payload: dict[str, Any], scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = [
        ("DRY_COAL_PER_COKE_TPT", "coal_input_t_per_t_coke"),
        ("COG_YIELD_NM3_PER_T_COKE", "COG_yield_Nm3_per_t_coke"),
        ("KGF_UNDERFIRING_GJ_PER_T_COKE", "underfiring_GJ_per_t_coke"),
        ("KGF_ELECTRICITY_MWH_PER_T_COKE", "electricity_MWh_per_t_coke"),
        ("KGF_STEAM_GJ_PER_T_COKE", "steam_GJ_per_t_coke"),
        ("KGF_STEAM_T_PER_T_COKE_DIAGNOSTIC", "steam_mass_t_per_t_coke"),
        ("KGF_DIRECT_CO2_T_PER_T_COKE", "direct_CO2_t_per_t_coke"),
    ]
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        key = (scenario["configuration"], int(scenario["horizon_hours"]))
        current_output = _zero(payload["current"][key]["total_KGF_coke_output_site_t_y"])
        scenario_output = _zero(scenario["KGF_output_site_t_y"])
        if scenario_output <= current_output + TOL_T:
            continue
        scale = scenario_output / current_output if current_output else 0.0
        for pid, metric in metrics:
            param = payload["kgf_params"][pid]
            active = _zero(param["base_value"])
            required = active / scale if scale else 0.0
            low, high = _range_low_high(param)
            status = _range_status(required, low, high)
            rows.append(
                {
                    "configuration": scenario["configuration"],
                    "horizon_hours": scenario["horizon_hours"],
                    "driver_basis": scenario["driver_basis"],
                    "scenario_id": scenario["scenario_id"],
                    "metric": metric,
                    "current_KGF_output_site_t_y": _fmt(current_output),
                    "scenario_KGF_output_site_t_y": _fmt(scenario_output),
                    "KGF_output_scale_factor": _fmt(scale),
                    "active_intensity": _fmt(active),
                    "required_intensity_if_total_KPI_held_constant": _fmt(required),
                    "low_value": _fmt(low) if low is not None else "",
                    "high_value": _fmt(high) if high is not None else "",
                    "unit": param["unit"],
                    "range_status": status,
                    "classification": "unsupported_as_base" if status != "within_supported_range" else "within_range_diagnostic_only",
                    "source_or_assumption_id": param["source_or_assumption_id"],
                    "baseline_changed": "false",
                }
            )
    return rows


def _recommendation_rows(driver_rows: list[dict[str, Any]], scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    driver_mismatch = any(row["redflag_bf_coke_demand_driver_mismatch"] == "true" for row in driver_rows)
    bounded_close = [
        row for row in scenarios
        if row["driver_basis"] == "C5k_no_buffer_BF_hot_metal_driver"
        and row["gap_closed"] == "true"
        and row["within_BF_coke_rate_range"] == "true"
        and row["required_KGF_output_exceeds_public_anchor"] == "false"
        and row["source_support_status"] == "evidence_bounded_scenario_candidate"
    ]
    if driver_mismatch:
        priority = "fix_BF_coke_demand_driver_consistency_before_parameter_or_external_coke_changes"
    elif bounded_close:
        priority = "test_labelled_evidence_bounded_reconciliation_scenario_before_external_coke"
    else:
        priority = "external_or_unmodelled_coke_remains_fallback_closure"
    return [
        {
            "stage_id": STAGE,
            "recommendation_priority": priority,
            "driver_mismatch_present": _bool(driver_mismatch),
            "bounded_C5k_driver_low_rate_public_anchor_closure_available": _bool(bool(bounded_close)),
            "external_unmodelled_coke_still_necessary_after_bounded_audit": _bool(not bool(bounded_close)),
            "recommended_next_action": (
                "First repair/report-align BF coke demand to C5k no-buffer BF hot-metal driver. "
                "Then test a labelled scenario using low BF coke rate and public KGF anchors before implementing external coke."
                if driver_mismatch and bounded_close
                else priority
            ),
            "baseline_changed": "false",
        }
    ]


def _redflag_rows(
    payload: dict[str, Any],
    driver_rows: list[dict[str, Any]],
    kgf_rows: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
    efficiency: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config in CONFIGS:
        for horizon in HORIZONS:
            key = (config, horizon)
            scenario_case_rows = [row for row in scenarios if row["configuration"] == config and int(row["horizon_hours"]) == horizon]
            efficiency_case_rows = [row for row in efficiency if row["configuration"] == config and int(row["horizon_hours"]) == horizon]
            driver = next(row for row in driver_rows if row["configuration"] == config and int(row["horizon_hours"]) == horizon)
            kgf = next(row for row in kgf_rows if row["configuration"] == config and int(row["horizon_hours"]) == horizon)
            totals = payload["c5m_b_totals"][key]
            flags = {
                "redflag_baseline_changed": False,
                "redflag_bf_coke_demand_driver_mismatch": driver["redflag_bf_coke_demand_driver_mismatch"] == "true",
                "redflag_kgf_current_output_below_public_anchor": kgf["redflag_kgf_current_output_below_public_anchor"] == "true",
                "redflag_required_bf_coke_rate_below_supported_range": any(row["BF_coke_rate_range_status"] == "below_supported_range" for row in scenario_case_rows),
                "redflag_required_kgf_output_exceeds_public_anchor": any(row["required_KGF_output_exceeds_public_anchor"] == "true" for row in scenario_case_rows),
                "redflag_efficiency_required_outside_supported_range": any(row["range_status"] != "within_supported_range" for row in efficiency_case_rows),
                "redflag_unexplained_coke_gap_still_hidden": False,
                "redflag_WAG_invariant_failed": totals["WAG_invariant_status"] != "pass",
                "redflag_CO2_guard_failed": totals["CO2_double_counting_guard_status"] != "pass",
            }
            baseline_hard = sum(
                1 for name, value in flags.items()
                if value and name in {"redflag_baseline_changed", "redflag_unexplained_coke_gap_still_hidden", "redflag_WAG_invariant_failed", "redflag_CO2_guard_failed"}
            )
            rows.append(
                {
                    "configuration": config,
                    "horizon_hours": horizon,
                    **{name: _bool(value) for name, value in flags.items()},
                    "baseline_hard_redflag_count": baseline_hard,
                    "diagnostic_redflag_count": sum(1 for name, value in flags.items() if value) - baseline_hard,
                    "status": "pass_baseline_unchanged_with_driver_and_scenario_caveats",
                    "explanation": "Diagnostic red flags identify driver mismatch and unsupported scenario assumptions; baseline artifacts are unchanged.",
                }
            )
    return rows


def _stage_gate(redflags: list[dict[str, Any]], recommendation: list[dict[str, Any]], driver_rows: list[dict[str, Any]], scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_hard = sum(int(row["baseline_hard_redflag_count"]) for row in redflags)
    driver_mismatch_count = sum(1 for row in driver_rows if row["redflag_bf_coke_demand_driver_mismatch"] == "true")
    bounded_close_count = sum(
        1 for row in scenarios
        if row["driver_basis"] == "C5k_no_buffer_BF_hot_metal_driver"
        and row["scenario_id"] == "S3_low_rate_public_KGF_anchor"
        and row["gap_closed"] == "true"
        and row["within_BF_coke_rate_range"] == "true"
        and row["required_KGF_output_exceeds_public_anchor"] == "false"
    )
    return {
        "stage": STAGE,
        "decision": "pass_development_driver_consistency_and_bounded_reconciliation_audit" if baseline_hard == 0 else "fail_development_driver_consistency_audit",
        "output_directory": _rel(C5M_D_DIR),
        "status": "development_only",
        "thesis_usability": False,
        "dependency_chain": DEPENDENCY_CHAIN,
        "pattern_audit_result": PATTERN_AUDIT_RESULT,
        "baseline_unchanged_confirmation": True,
        "baseline_hard_redflag_count": baseline_hard,
        "driver_mismatch_count": driver_mismatch_count,
        "bounded_C5k_low_rate_public_anchor_closure_count": bounded_close_count,
        "failure_count": baseline_hard,
        "recommended_next_action": recommendation[0]["recommended_next_action"],
    }


def _write_outputs() -> dict[str, Any]:
    run_s4_4c5m_c_coke_balance_root_cause_and_resolution_options_audit()
    C5M_D_DIR.mkdir(parents=True, exist_ok=True)
    payload = _source_payload()
    driver = _driver_rows(payload)
    kgf_anchor = _kgf_anchor_rows(payload)
    scenarios = _scenarios(payload, driver)
    kpi = _kpi_propagation(payload, scenarios)
    efficiency = _efficiency_what_if(payload, scenarios)
    recommendation = _recommendation_rows(driver, scenarios)
    redflags = _redflag_rows(payload, driver, kgf_anchor, scenarios, efficiency)
    gate = _stage_gate(redflags, recommendation, driver, scenarios)

    _write_json(C5M_D_DIR / "s4_4c5m_d_stage_gate.json", gate)
    _write_csv(
        C5M_D_DIR / "s4_4c5m_d_run_registry.csv",
        [
            {
                "stage": STAGE,
                "source_stage": "S4.4c5m_c_coke_balance_root_cause_and_resolution_options_audit",
                "decision": gate["decision"],
                "status": "development_only",
                "thesis_usability": "false",
                "output_directory": gate["output_directory"],
            }
        ],
    )
    _write_csv(C5M_D_DIR / "s4_4c5m_d_bf_coke_demand_driver_consistency_audit.csv", driver)
    _write_csv(C5M_D_DIR / "s4_4c5m_d_kgf_current_vs_public_anchor_audit.csv", kgf_anchor)
    _write_csv(C5M_D_DIR / "s4_4c5m_d_bounded_reconciliation_scenarios.csv", scenarios)
    _write_csv(C5M_D_DIR / "s4_4c5m_d_kpi_propagation.csv", kpi)
    _write_csv(C5M_D_DIR / "s4_4c5m_d_efficiency_intensity_what_if.csv", efficiency)
    _write_csv(C5M_D_DIR / "s4_4c5m_d_recommendation.csv", recommendation)
    _write_csv(C5M_D_DIR / "s4_4c5m_d_red_flags.csv", redflags)
    _write_csv(C5M_D_DIR / "s4_4c5m_d_compact_table_for_chat.csv", scenarios)
    _write_json(
        C5M_D_DIR / "s4_4c5m_d_driver_consistency_and_bounded_reconciliation_report.json",
        {
            "stage_id": STAGE,
            "status": "development_only",
            "thesis_usability": False,
            "dependency_chain": DEPENDENCY_CHAIN,
            "baseline_unchanged_confirmation": True,
            "driver_consistency": driver,
            "kgf_anchor_audit": kgf_anchor,
            "bounded_reconciliation_scenarios": scenarios,
            "recommendation": recommendation,
            "red_flags": redflags,
        },
    )
    summary = {
        "stage": STAGE,
        "decision": gate["decision"],
        "output_directory": gate["output_directory"],
        "recommended_next_action": gate["recommended_next_action"],
        "rows": {
            "driver": len(driver),
            "kgf_anchor": len(kgf_anchor),
            "scenarios": len(scenarios),
            "kpi": len(kpi),
            "efficiency": len(efficiency),
            "redflags": len(redflags),
        },
    }
    _write_json(C5M_D_DIR / "s4_4c5m_d_summary.json", summary)
    return summary


def run_s4_4c5m_d_coke_balance_driver_consistency_and_bounded_reconciliation_audit() -> dict[str, Any]:
    return _write_outputs()


def main() -> int:
    print(json.dumps(run_s4_4c5m_d_coke_balance_driver_consistency_and_bounded_reconciliation_audit(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
