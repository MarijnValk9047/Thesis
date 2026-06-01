from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .plant_parameters import HydrogenConfig


def _result(name: str, status: str, details: str, severity: str = "hard_fail") -> dict[str, str]:
    return {"check_name": name, "status": status, "severity": severity, "details": details}


def _is_badarinath_style_redispatch(dispatch: pd.DataFrame) -> bool:
    if dispatch.empty:
        return False
    bridge_strategy = str(dispatch.get("bridge_strategy", pd.Series([pd.NA])).dropna().iloc[0]) if "bridge_strategy" in dispatch.columns and not dispatch.get("bridge_strategy", pd.Series(dtype=object)).dropna().empty else ""
    source_strategy = str(dispatch.get("source_strategy", pd.Series([pd.NA])).dropna().iloc[0]) if "source_strategy" in dispatch.columns and not dispatch.get("source_strategy", pd.Series(dtype=object)).dropna().empty else ""
    strategy = str(dispatch.get("strategy", pd.Series([pd.NA])).dropna().iloc[0]) if "strategy" in dispatch.columns and not dispatch.get("strategy", pd.Series(dtype=object)).dropna().empty else ""
    return (
        bridge_strategy == "price_insensitive_plan_first_market_cap"
        or bridge_strategy == "price_insensitive_heuristic_plan_first_market_cap"
        or (source_strategy == "price_insensitive" and bridge_strategy in {"high_price_bid", "price_insensitive_plan_first_market_cap"})
        or (source_strategy == "price_insensitive_heuristic" and bridge_strategy == "price_insensitive_heuristic_plan_first_market_cap")
        or strategy == "price_insensitive_plan_first_market_cap"
        or strategy == "price_insensitive_heuristic_plan_first_market_cap"
    )


def validate_scenario_table(scenarios: pd.DataFrame) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    validation_modes = sorted(scenarios.get("scenario_validation_mode", pd.Series(["thesis_grade"])).astype(str).unique().tolist())
    smoke_only = set(validation_modes) == {"smoke_test"}
    prob_severity = "smoke_warning" if smoke_only else "hard_fail"

    if (scenarios["scenario_probability"] < 0).any():
        checks.append(_result("scenario_probability_nonnegative", "fail", "Negative probabilities found.", severity=prob_severity))
    else:
        checks.append(_result("scenario_probability_nonnegative", "pass", "No negative probabilities found.", severity=prob_severity))

    dedup = scenarios[["forecast_origin_utc", "model_id", "lead_day", "scenario_id", "scenario_probability"]].drop_duplicates()
    sums = dedup.groupby(["forecast_origin_utc", "model_id", "lead_day"], as_index=False)["scenario_probability"].sum()
    bad = sums[~sums["scenario_probability"].between(0.999999, 1.000001)]
    checks.append(
        _result(
            "scenario_probability_sum_to_one",
            "pass" if bad.empty else "fail",
            f"failing_blocks={int(bad.shape[0])}",
            severity=prob_severity,
        )
    )
    scenario_counts = dedup.groupby(["forecast_origin_utc", "model_id", "lead_day"], as_index=False)["scenario_id"].nunique()
    checks.append(
        _result(
            "scenario_count_per_origin_reported",
            "pass",
            (
                f"blocks={int(scenario_counts.shape[0])}, "
                f"min={int(scenario_counts['scenario_id'].min()) if not scenario_counts.empty else 0}, "
                f"median={float(scenario_counts['scenario_id'].median()) if not scenario_counts.empty else 0.0:.1f}, "
                f"max={int(scenario_counts['scenario_id'].max()) if not scenario_counts.empty else 0}"
            ),
            severity="informational",
        )
    )
    duplicate_rows = scenarios.duplicated(
        subset=["forecast_origin_utc", "delivery_start_utc", "scenario_id", "model_id"],
        keep=False,
    )
    checks.append(
        _result(
            "scenario_row_uniqueness",
            "pass" if not bool(duplicate_rows.any()) else "fail",
            f"duplicate_rows={int(duplicate_rows.sum())}",
            severity=prob_severity,
        )
    )
    forecast_dtype = str(scenarios["forecast_origin_utc"].dtype)
    delivery_dtype = str(scenarios["delivery_start_utc"].dtype)
    utc_ok = (
        forecast_dtype.startswith("datetime64[")
        and forecast_dtype.endswith(", UTC]")
        and delivery_dtype.startswith("datetime64[")
        and delivery_dtype.endswith(", UTC]")
    )
    checks.append(
        _result(
            "scenario_timestamps_timezone_utc",
            "pass" if utc_ok else "fail",
            (
                f"forecast_origin_dtype={forecast_dtype}, "
                f"delivery_start_dtype={delivery_dtype}"
            ),
            severity=prob_severity,
        )
    )
    checks.append(
        _result(
            "scenario_validation_mode",
            "warn" if smoke_only else "pass",
            f"validation_modes={validation_modes}",
            severity="smoke_warning" if smoke_only else "informational",
        )
    )

    missing_actual = int(scenarios["actual_price_eur_per_mwh"].isna().sum())
    checks.append(
        _result(
            "actual_price_available",
            "pass" if missing_actual == 0 else "fail",
            f"missing_actual_rows={missing_actual}",
            severity="hard_fail",
        )
    )

    lead_day_bad = int((scenarios["lead_day"].astype(int) != 0).sum())
    checks.append(
        _result(
            "d_only_lead_day_zero",
            "pass" if lead_day_bad == 0 else "fail",
            f"nonzero_lead_day_rows={lead_day_bad}",
            severity="hard_fail",
        )
    )
    return checks


def validate_dispatch_physical(
    dispatch: pd.DataFrame,
    *,
    config: HydrogenConfig,
    reserve_kg: float,
    inventory_start_kg: float,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    tolerance = 1e-4
    hydrogen_nonnegative = bool((dispatch[["H_prod_kg", "H_comp_kg", "H_buf_kg"]] >= -tolerance).all().all())
    checks.append(_result("hydrogen_nonnegative", "pass" if hydrogen_nonnegative else "fail", "No negative hydrogen production, compression, or storage values allowed."))

    min_buf = float(dispatch["H_buf_kg"].min())
    max_buf = float(dispatch["H_buf_kg"].max())
    checks.append(
        _result(
            "storage_bounds_respected",
            "pass" if (min_buf >= -tolerance and max_buf <= config.hydrogen_system.storage_capacity_kg + tolerance) else "fail",
            f"buffer_min={min_buf:.3f}, buffer_max={max_buf:.3f}",
        )
    )
    checks.append(
        _result(
            "reserve_respected",
            "pass" if min_buf >= reserve_kg - tolerance else "fail",
            f"reserve_kg={reserve_kg:.3f}, buffer_min={min_buf:.3f}",
        )
    )

    comp_expected = dispatch["H_comp_kg"].astype(float) * config.hydrogen_system.compressor_specific_mwh_per_kg / config.delta_t_hours
    comp_error = float(np.max(np.abs(comp_expected - dispatch["P_comp_mw"].astype(float))))
    checks.append(
        _result(
            "compressor_specific_energy",
            "pass" if comp_error <= 1e-3 else "fail",
            f"max_abs_error={comp_error:.6f}",
        )
    )
    comp_limit_violation = float((dispatch["P_comp_mw"].astype(float) - config.hydrogen_system.compressor_max_mw).max())
    checks.append(
        _result(
            "compressor_power_limit",
            "pass" if comp_limit_violation <= tolerance else "fail",
            f"max_excess_mw={max(comp_limit_violation, 0.0):.6f}",
        )
    )

    prod_expected = dispatch["P_el_mw"].astype(float) * config.hydrogen_system.h2_efficiency_kg_per_mwh * config.delta_t_hours
    prod_error = float(np.max(np.abs(prod_expected - dispatch["H_prod_kg"].astype(float))))
    checks.append(
        _result(
            "electrolyser_yield_balance",
            "pass" if prod_error <= 1e-3 else "fail",
            f"max_abs_error={prod_error:.6f}",
        )
    )
    p_el = dispatch["P_el_mw"].astype(float)
    within_max = bool((p_el <= config.hydrogen_system.electrolyser_nominal_mw + tolerance).all())
    within_min_or_off = bool(((p_el <= tolerance) | (p_el >= config.hydrogen_system.electrolyser_min_mw - tolerance)).all())
    checks.append(
        _result(
            "electrolyser_min_max_respected",
            "pass" if (within_max and within_min_or_off) else "fail",
            (
                f"min_mw={float(p_el.min()):.6f}, max_mw={float(p_el.max()):.6f}, "
                f"nominal_mw={config.hydrogen_system.electrolyser_nominal_mw:.6f}"
            ),
        )
    )

    ramps = dispatch["P_el_mw"].astype(float).diff().abs().dropna()
    max_ramp = float(ramps.max()) if not ramps.empty else 0.0
    checks.append(
        _result(
            "electrolyser_ramp_limit",
            "pass" if max_ramp <= config.hydrogen_system.electrolyser_ramp_mw_per_h + 1e-6 else "fail",
            f"max_ramp={max_ramp:.6f}",
        )
    )
    if dispatch.empty:
        balance_error = float("nan")
    else:
        expected_buffer = dispatch["H_prod_kg"].astype(float) - dispatch["H_comp_kg"].astype(float)
        expected_buffer.iloc[0] = float(inventory_start_kg) + expected_buffer.iloc[0]
        if len(expected_buffer) > 1:
            expected_buffer.iloc[1:] = float(inventory_start_kg) + (dispatch["H_prod_kg"].astype(float) - dispatch["H_comp_kg"].astype(float)).cumsum().iloc[1:]
        balance_error = float(np.max(np.abs(expected_buffer.to_numpy() - dispatch["H_buf_kg"].astype(float).to_numpy())))
    checks.append(
        _result(
            "hydrogen_balance_closes",
            "pass" if balance_error <= 1e-3 else "fail",
            f"max_abs_error={balance_error:.6f}",
        )
    )
    if {"electrolyser_electricity_mwh", "compressor_electricity_mwh", "total_electricity_mwh"}.issubset(dispatch.columns):
        total_expected = dispatch["electrolyser_electricity_mwh"].astype(float) + dispatch["compressor_electricity_mwh"].astype(float)
        total_error = float(np.max(np.abs(total_expected - dispatch["total_electricity_mwh"].astype(float))))
    else:
        total_error = 0.0
    checks.append(
        _result(
            "electricity_use_consistent_with_component_loads",
            "pass" if total_error <= 1e-9 else "fail",
            f"max_abs_error={total_error:.6f}",
        )
    )
    shortfall_value = float(dispatch["shortfall_kg"].iloc[0]) if "shortfall_kg" in dispatch.columns and not dispatch.empty else float("nan")
    compressed_total = float(dispatch["H_comp_kg"].sum()) if "H_comp_kg" in dispatch.columns else float("nan")
    target = float(config.economics.daily_target_kg)
    target_condition = False
    if np.isfinite(shortfall_value) and np.isfinite(compressed_total):
        target_condition = (compressed_total + shortfall_value) >= target - 1e-3
    checks.append(
        _result(
            "production_target_and_shortfall_reported",
            "pass" if target_condition else "fail",
            f"target_kg={target:.3f}, compressed_kg={compressed_total:.3f}, shortfall_kg={shortfall_value:.3f}",
        )
    )
    return checks


def validate_economic_consistency(
    summary: pd.DataFrame,
    *,
    tolerance_eur: float = 1e-3,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    if summary.empty:
        return [_result("economic_summary_present", "fail", "Summary table is empty.")]

    required = {"strategy", "net_profit_eur", "adjusted_net_profit_eur", "terminal_inventory_value_eur"}
    missing = required.difference(summary.columns)
    if missing:
        return [_result("economic_summary_columns", "fail", f"missing_columns={sorted(missing)}")]

    delta = summary["adjusted_net_profit_eur"] - summary["net_profit_eur"] - summary["terminal_inventory_value_eur"]
    mismatch = int((delta.abs() > tolerance_eur).sum())
    checks.append(
        _result(
            "terminal_inventory_applied_once",
            "pass" if mismatch == 0 else "fail",
            f"mismatch_rows={mismatch}",
        )
    )
    if {"terminal_inventory_value_eur", "buffer_delta_kg", "strategy"}.issubset(summary.columns):
        missing_report = int(
            (
                (summary["buffer_delta_kg"].astype(float).abs() > 1e-6)
                & (summary["terminal_inventory_value_eur"].astype(float).abs() <= tolerance_eur)
            ).sum()
        )
        checks.append(
            _result(
                "terminal_inventory_correction_reported",
                "pass" if missing_report == 0 else "warn",
                f"rows_with_delta_but_zero_terminal_value={missing_report}",
            )
        )
    if {"objective_value_eur", "strategy"}.issubset(summary.columns):
        missing_objective = int(summary["objective_value_eur"].isna().sum())
        checks.append(
            _result(
                "objective_value_reported",
                "pass" if missing_objective == 0 else "warn",
                f"missing_rows={missing_objective}",
            )
        )
    if {"target_fulfilment_pct", "shortfall_kg"}.issubset(summary.columns):
        missing_target = int(summary["target_fulfilment_pct"].isna().sum() + summary["shortfall_kg"].isna().sum())
        checks.append(
            _result(
                "target_fulfilment_reported",
                "pass" if missing_target == 0 else "fail",
                f"missing_cells={missing_target}",
            )
        )

    if {"strategy", "adjusted_net_profit_eur"}.issubset(summary.columns):
        price_insensitive = summary.loc[summary["strategy"] == "price_insensitive", "adjusted_net_profit_eur"]
        perfect = summary.loc[summary["strategy"] == "perfect_foresight", "adjusted_net_profit_eur"]
        stochastic = summary.loc[summary["strategy"] == "stochastic_cvar", "adjusted_net_profit_eur"]
        if not price_insensitive.empty and not perfect.empty and not stochastic.empty:
            dominance_ok = float(perfect.iloc[0]) + tolerance_eur >= float(stochastic.iloc[0])
            checks.append(
                _result(
                    "perfect_foresight_upper_bound_vs_stochastic",
                    "pass" if dominance_ok else "warn",
                    f"perfect={float(perfect.iloc[0]):.2f}, stochastic_cvar={float(stochastic.iloc[0]):.2f}",
                )
            )
    return checks


def validate_redispatch_solution(
    dispatch: pd.DataFrame,
    *,
    summary_row: pd.Series,
    config: HydrogenConfig,
    reserve_kg: float,
    inventory_start_kg: float,
) -> list[dict[str, str]]:
    checks = validate_dispatch_physical(
        dispatch,
        config=config,
        reserve_kg=reserve_kg,
        inventory_start_kg=inventory_start_kg,
    )
    tolerance = 1e-4
    if dispatch.empty:
        return checks + [_result("redispatch_timeseries_present", "fail", "Redispatch timeseries is empty.")]

    used = dispatch["used_energy_mwh"].astype(float)
    unused = dispatch["unused_cleared_energy_mwh"].astype(float)
    cleared = dispatch["cleared_energy_mwh"].astype(float)
    emergency_import = pd.to_numeric(pd.Series(dispatch.get("emergency_import_mwh", 0.0)), errors="coerce").fillna(0.0).astype(float)
    actual_price = dispatch["actual_price_eur_per_mwh"].astype(float)

    energy_balance_error = float(np.max(np.abs((used + unused - cleared - emergency_import).to_numpy())))
    checks.append(
        _result(
            "used_plus_unused_equals_cleared_energy",
            "pass" if energy_balance_error <= tolerance else "fail",
            f"max_abs_error={energy_balance_error:.6f}",
        )
    )
    energy_excess = float(np.max((used - cleared - emergency_import).to_numpy()))
    checks.append(
        _result(
            "electricity_use_never_exceeds_cleared_energy",
            "pass" if energy_excess <= tolerance else "fail",
            f"max_excess_mwh={max(energy_excess, 0.0):.6f}",
        )
    )
    nonnegative_columns = [
        "cleared_energy_mwh",
        "used_energy_mwh",
        "unused_cleared_energy_mwh",
        "H_prod_kg",
        "H_comp_kg",
        "H_buf_kg",
        "shortfall_kg",
    ]
    if "emergency_import_mwh" in dispatch.columns:
        nonnegative_columns.append("emergency_import_mwh")
    nonnegative_ok = bool((dispatch[nonnegative_columns] >= -tolerance).all().all())
    checks.append(
        _result(
            "redispatch_variables_nonnegative",
            "pass" if nonnegative_ok else "fail",
            "No negative production, compression, storage, energy, or shortfall variables allowed.",
        )
    )
    zero_mask = (dispatch["cleared_energy_mwh"].astype(float) + emergency_import) <= tolerance
    zero_used_max = float(dispatch.loc[zero_mask, "used_energy_mwh"].astype(float).max()) if bool(zero_mask.any()) else 0.0
    checks.append(
        _result(
            "zero_cleared_energy_implies_zero_use",
            "pass" if zero_used_max <= tolerance else "fail",
            f"max_used_when_cleared_zero={zero_used_max:.6f}",
        )
    )
    settlement_recomputed = float(np.sum(actual_price * cleared))
    settlement_reported = float(summary_row["realised_DA_settlement_cost_eur"])
    checks.append(
        _result(
            "settlement_cost_uses_cleared_energy",
            "pass" if abs(settlement_recomputed - settlement_reported) <= tolerance else "fail",
            f"reported={settlement_reported:.6f}, recomputed={settlement_recomputed:.6f}",
        )
    )
    objective_recomputed = float(
        float(summary_row["hydrogen_revenue_eur"])
        - float(summary_row["unused_energy_penalty_eur"])
        - float(summary_row.get("emergency_import_cost_eur", 0.0))
        - float(summary_row["shortfall_penalty_eur"])
        + float(summary_row["terminal_inventory_correction_eur"])
    )
    objective_raw = summary_row["objective_value"]
    objective_reported = float(objective_raw) if objective_raw is not None and not pd.isna(objective_raw) else float("nan")
    checks.append(
        _result(
            "redispatch_objective_excludes_sunk_settlement_cost",
            "pass" if np.isfinite(objective_reported) and abs(objective_recomputed - objective_reported) <= tolerance else "fail",
            f"reported={objective_reported}, recomputed={objective_recomputed:.6f}",
        )
    )
    if _is_badarinath_style_redispatch(dispatch):
        penalty_zero = abs(float(config.economics.unused_energy_penalty_eur_per_mwh)) <= tolerance
        checks.append(
            _result(
                "badarinath_unused_energy_penalty_nonzero",
                "pass" if not penalty_zero else "warn",
                (
                    "Badarinath-style redispatch requires a nonzero "
                    f"unused_energy_penalty_eur_per_mwh; configured={float(config.economics.unused_energy_penalty_eur_per_mwh):.6f}"
                ),
                severity="warn" if penalty_zero else "informational",
            )
        )
    target_semantics_ok = getattr(config, "production", None) is not None and str(config.production.target_semantics) == "lower_bound_reference"
    checks.append(
        _result(
            "target_is_lower_bound_reference_not_upper_bound",
            "pass" if target_semantics_ok else "warn",
            f"target_semantics={getattr(getattr(config, 'production', None), 'target_semantics', 'missing')}",
            severity="informational" if target_semantics_ok else "warn",
        )
    )
    above_target = float(summary_row.get("hydrogen_above_target_kg", 0.0))
    above_target_reported = ("hydrogen_above_target_kg" in summary_row.index) and above_target >= -tolerance
    checks.append(
        _result(
            "above_target_hydrogen_reported",
            "pass" if above_target_reported else "fail",
            f"hydrogen_above_target_kg={above_target:.6f}",
        )
    )
    terminal_delta = float(summary_row["terminal_inventory_change_kg"])
    terminal_value = float(summary_row["terminal_inventory_correction_eur"])
    terminal_ok = abs(terminal_delta) <= tolerance or abs(terminal_value) > tolerance
    checks.append(
        _result(
            "terminal_inventory_correction_reported_when_storage_changes",
            "pass" if terminal_ok else "fail",
            f"terminal_inventory_change_kg={terminal_delta:.6f}, terminal_inventory_correction_eur={terminal_value:.6f}",
        )
    )
    return checks


def validate_solver_statuses(solver_status_table: pd.DataFrame) -> list[dict[str, str]]:
    if solver_status_table.empty:
        return [_result("solver_status_table_present", "fail", "No solver statuses were recorded.")]
    acceptable = {"Optimal", "Optimal Infeasible", "heuristic"}
    bad = solver_status_table[~solver_status_table["solver_status"].astype(str).isin(acceptable)]
    checks = [
        _result(
            "solver_status_acceptable",
            "pass" if bad.empty else "warn",
            f"bad_rows={int(bad.shape[0])}",
        )
    ]
    return checks


def validate_model_stats(model_stats_table: pd.DataFrame) -> list[dict[str, str]]:
    if model_stats_table.empty:
        return [_result("model_stats_present", "fail", "No model stats were recorded.")]
    required = {
        "strategy",
        "variable_count",
        "binary_variable_count",
        "constraint_count",
        "scenario_count",
        "horizon_steps",
    }
    missing = required.difference(model_stats_table.columns)
    if missing:
        return [_result("model_stats_columns", "fail", f"missing_columns={sorted(missing)}")]
    nonpositive = int(
        (
            (~model_stats_table["strategy"].astype(str).isin({"price_insensitive_heuristic"}))
            & (
                (model_stats_table["variable_count"].astype(float) <= 0)
                | (model_stats_table["constraint_count"].astype(float) <= 0)
            )
        ).sum()
    )
    return [
        _result(
            "model_stats_recorded",
            "pass" if nonpositive == 0 else "warn",
            f"nonpositive_rows={nonpositive}",
        )
    ]


def validate_gamma_selection(
    *,
    selection_split: str,
    evaluation_split: str,
) -> list[dict[str, str]]:
    leakage = selection_split.strip().lower() == "test"
    return [
        _result(
            "gamma_selection_not_on_test",
            "pass" if not leakage else "fail",
            f"selection_split={selection_split}, evaluation_split={evaluation_split}",
        )
    ]


def collect_validation_report(
    *,
    scenario_checks: list[dict[str, str]],
    dispatch_checks: list[dict[str, str]],
    economic_checks: list[dict[str, str]],
    solver_checks: list[dict[str, str]],
    model_stats_checks: list[dict[str, str]],
    gamma_checks: list[dict[str, str]],
) -> pd.DataFrame:
    rows = scenario_checks + dispatch_checks + economic_checks + solver_checks + model_stats_checks + gamma_checks
    return pd.DataFrame(rows)
