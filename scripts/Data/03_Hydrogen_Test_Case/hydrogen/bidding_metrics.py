from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .clearing import aggregate_cleared_energy
from .cvar import compute_weighted_cvar_from_frame


def compute_bridge_clearing_metrics(clearing_result: pd.DataFrame) -> pd.DataFrame:
    aggregated = aggregate_cleared_energy(clearing_result)
    group_columns = [
        column
        for column in (
            "run_id",
            "strategy",
            "source_strategy",
            "bridge_strategy",
            "forecast_model",
            "scenario_model",
            "granularity",
            "horizon",
            "forecast_origin_utc",
        )
        if column in aggregated.columns
    ]

    rows: list[dict[str, Any]] = []
    for keys, hourly in aggregated.groupby(group_columns, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        record = {column: value for column, value in zip(group_columns, keys)}
        total_submitted_energy = float(hourly["submitted_energy_mwh"].sum())
        total_cleared_energy = float(hourly["cleared_energy_mwh"].sum())
        total_rejected_energy = float(hourly["rejected_energy_mwh"].sum())
        zero_clearing_mask = hourly["cleared_energy_mwh"] <= 1e-9
        partial_clearing_mask = (hourly["clearing_ratio"] > 1e-9) & (hourly["clearing_ratio"] < 1.0 - 1e-9)
        cleared_hours = hourly.loc[hourly["cleared_energy_mwh"] > 1e-9, "actual_price_eur_per_mwh"]
        rejected_hours = hourly.loc[hourly["rejected_energy_mwh"] > 1e-9, "actual_price_eur_per_mwh"]

        if total_cleared_energy > 0.0:
            cleared_weighted_avg_price = float(
                np.average(hourly["actual_price_eur_per_mwh"], weights=hourly["cleared_energy_mwh"])
            )
        else:
            cleared_weighted_avg_price = float("nan")
        if total_rejected_energy > 0.0:
            rejected_weighted_avg_price = float(
                np.average(hourly["actual_price_eur_per_mwh"], weights=hourly["rejected_energy_mwh"])
            )
        else:
            rejected_weighted_avg_price = float("nan")

        rejected_rows = clearing_result
        for column, value in record.items():
            if pd.isna(value):
                rejected_rows = rejected_rows[rejected_rows[column].isna()]
            else:
                rejected_rows = rejected_rows[rejected_rows[column] == value]

        record.update(
            {
                "scheduled_energy_mwh": total_submitted_energy,
                "submitted_energy_mwh": total_submitted_energy,
                "cleared_energy_mwh": total_cleared_energy,
                "rejected_energy_mwh": total_rejected_energy,
                "clearing_ratio": float(total_cleared_energy / total_submitted_energy) if total_submitted_energy > 0.0 else 0.0,
                "number_of_rejected_bid_rows": int((~rejected_rows["accepted"].astype(bool)).sum()),
                "number_of_hours_with_zero_clearing": int(zero_clearing_mask.sum()),
                "number_of_hours_with_partial_clearing": int(partial_clearing_mask.sum()),
                "average_actual_price_in_cleared_hours": float(cleared_hours.mean()) if not cleared_hours.empty else float("nan"),
                "average_actual_price_in_rejected_hours": float(rejected_hours.mean()) if not rejected_hours.empty else float("nan"),
                "energy_weighted_average_actual_price_for_cleared_energy": cleared_weighted_avg_price,
                "energy_weighted_average_actual_price_for_rejected_energy": rejected_weighted_avg_price,
                "realised_DA_settlement_cost_eur": float(
                    (hourly["actual_price_eur_per_mwh"] * hourly["cleared_energy_mwh"]).sum()
                ),
            }
        )
        rows.append(record)

    metric_frame = pd.DataFrame(rows)
    if metric_frame.empty:
        return metric_frame
    return metric_frame.sort_values(group_columns).reset_index(drop=True)


def attach_redispatch_uplift_metrics(
    bridge_metrics: pd.DataFrame,
    redispatch_summary: pd.DataFrame,
) -> pd.DataFrame:
    if bridge_metrics.empty or redispatch_summary.empty:
        return bridge_metrics.copy()

    merge_keys = [
        column
        for column in (
            "run_id",
            "strategy",
            "source_strategy",
            "bridge_strategy",
            "forecast_model",
            "scenario_model",
            "granularity",
            "horizon",
            "forecast_origin_utc",
            "redispatch_case",
        )
        if column in bridge_metrics.columns and column in redispatch_summary.columns
    ]
    merged = bridge_metrics.merge(
        redispatch_summary[
            merge_keys
            + [
                "used_energy_mwh",
                "unused_cleared_energy_mwh",
                "unused_energy_share",
                "shortfall_kg",
                "target_fulfilment_ratio",
                "realised_adjusted_profit_eur",
            ]
        ],
        on=merge_keys,
        how="left",
        validate="one_to_one",
    )
    return merged.reset_index(drop=True)


def compute_stochastic_scenario_clearing_metrics(scenario_clearing: pd.DataFrame) -> pd.DataFrame:
    required = {
        "scenario_id",
        "scenario_probability",
        "delivery_start_utc",
        "bid_quantity_mw",
        "cleared_quantity_mw",
        "cleared_energy_mwh",
        "scenario_price_eur_per_mwh",
    }
    missing = required.difference(scenario_clearing.columns)
    if missing:
        raise ValueError(f"scenario_clearing is missing required columns: {sorted(missing)}")

    frame = scenario_clearing.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    if "timestep_hours" in frame.columns:
        timestep_lookup = frame.groupby("scenario_id", as_index=False)["timestep_hours"].first()
    else:
        timestep_lookup = None
    hourly = (
        frame.groupby(["scenario_id", "scenario_probability", "delivery_start_utc"], as_index=False)
        .agg(
            scenario_price_eur_per_mwh=("scenario_price_eur_per_mwh", "first"),
            submitted_quantity_mw=("bid_quantity_mw", "sum"),
            cleared_quantity_mw=("cleared_quantity_mw", "sum"),
            cleared_energy_mwh=("cleared_energy_mwh", "sum"),
        )
        .sort_values(["scenario_id", "delivery_start_utc"])
        .reset_index(drop=True)
    )
    if timestep_lookup is not None:
        hourly = hourly.merge(timestep_lookup, on="scenario_id", how="left")
        hourly["submitted_energy_mwh"] = hourly["submitted_quantity_mw"] * hourly["timestep_hours"]
    else:
        hourly["submitted_energy_mwh"] = hourly["submitted_quantity_mw"]
    summary = (
        hourly.groupby(["scenario_id", "scenario_probability"], as_index=False)
        .agg(
            submitted_energy_mwh=("submitted_energy_mwh", "sum"),
            cleared_energy_mwh=("cleared_energy_mwh", "sum"),
            submitted_quantity_mw_peak=("submitted_quantity_mw", "max"),
            max_price_eur_per_mwh=("scenario_price_eur_per_mwh", "max"),
            min_price_eur_per_mwh=("scenario_price_eur_per_mwh", "min"),
        )
        .sort_values("scenario_id")
        .reset_index(drop=True)
    )
    summary["rejected_energy_mwh"] = summary["submitted_energy_mwh"] - summary["cleared_energy_mwh"]
    summary["clearing_ratio"] = np.where(
        summary["submitted_energy_mwh"] > 0.0,
        summary["cleared_energy_mwh"] / summary["submitted_energy_mwh"],
        0.0,
    )
    summary["hours_with_zero_clearing"] = (
        hourly.assign(zero=hourly["cleared_energy_mwh"] <= 1e-9)
        .groupby("scenario_id")["zero"]
        .sum()
        .reindex(summary["scenario_id"])
        .to_numpy()
    )
    return summary


def compute_stochastic_expected_bid_metrics(
    *,
    submitted_bids: pd.DataFrame,
    scenario_dispatch: pd.DataFrame,
    scenario_economics: pd.DataFrame,
) -> dict[str, float]:
    if submitted_bids.empty or scenario_dispatch.empty or scenario_economics.empty:
        raise ValueError("submitted_bids, scenario_dispatch, and scenario_economics must all be nonempty.")

    probabilities = scenario_economics["scenario_probability"].astype(float).to_numpy()
    return {
        "expected_adjusted_profit_eur": float(np.sum(probabilities * scenario_economics["adjusted_profit_eur"].astype(float).to_numpy())),
        "expected_settlement_cost_eur": float(np.sum(probabilities * scenario_economics["settlement_cost_eur"].astype(float).to_numpy())),
        "expected_hydrogen_revenue_eur": float(np.sum(probabilities * scenario_economics["hydrogen_revenue_eur"].astype(float).to_numpy())),
        "expected_unused_energy_penalty_eur": float(np.sum(probabilities * scenario_economics["unused_energy_penalty_eur"].astype(float).to_numpy())),
        "expected_shortfall_penalty_eur": float(np.sum(probabilities * scenario_economics["shortfall_penalty_eur"].astype(float).to_numpy())),
        "expected_terminal_inventory_correction_eur": float(np.sum(probabilities * scenario_economics["terminal_inventory_correction_eur"].astype(float).to_numpy())),
        "expected_cleared_energy_mwh": float(np.sum(probabilities * scenario_economics["cleared_energy_mwh"].astype(float).to_numpy())),
        "expected_used_energy_mwh": float(np.sum(probabilities * scenario_economics["used_energy_mwh"].astype(float).to_numpy())),
        "expected_unused_cleared_energy_mwh": float(np.sum(probabilities * scenario_economics["unused_cleared_energy_mwh"].astype(float).to_numpy())),
        "expected_hydrogen_sold_kg": float(np.sum(probabilities * scenario_economics["hydrogen_sold_kg"].astype(float).to_numpy())),
        "expected_hydrogen_above_target_kg": float(np.sum(probabilities * scenario_economics["hydrogen_above_target_kg"].astype(float).to_numpy())),
        "expected_shortfall_kg": float(np.sum(probabilities * scenario_economics["shortfall_kg"].astype(float).to_numpy())),
    }


def compute_realised_backtest_summary(
    *,
    optimisation_summary: pd.DataFrame,
    actual_clearing_by_hour: pd.DataFrame,
    actual_redispatch_summary: pd.DataFrame,
) -> pd.DataFrame:
    if optimisation_summary.empty or actual_clearing_by_hour.empty or actual_redispatch_summary.empty:
        raise ValueError("optimisation_summary, actual_clearing_by_hour, and actual_redispatch_summary must be nonempty.")
    if "actual_path_id" not in actual_clearing_by_hour.columns:
        raise ValueError("actual_clearing_by_hour must include actual_path_id.")
    if "actual_path_id" not in actual_redispatch_summary.columns:
        raise ValueError("actual_redispatch_summary must include actual_path_id.")

    expected_row = optimisation_summary.iloc[0]
    rows: list[dict[str, Any]] = []
    for actual_path_id, hourly in actual_clearing_by_hour.groupby("actual_path_id", dropna=False):
        hourly = hourly.sort_values("delivery_start_utc").reset_index(drop=True)
        redispatch = actual_redispatch_summary.loc[actual_redispatch_summary["actual_path_id"] == actual_path_id]
        if redispatch.empty:
            raise ValueError(f"No redispatch summary found for actual_path_id={actual_path_id!r}.")
        redispatch_row = redispatch.iloc[0]

        cleared_energy = float(hourly["cleared_energy_mwh"].sum())
        submitted_energy = float(hourly["submitted_energy_mwh"].sum())
        rejected_energy = float(hourly["rejected_energy_mwh"].sum())
        rows.append(
            {
                "run_id": expected_row["run_id"],
                "strategy": expected_row["strategy"],
                "actual_path_id": actual_path_id,
                "expected_adjusted_profit_from_stochastic_model": float(expected_row["expected_adjusted_profit_without_regularisation"]),
                "realised_adjusted_profit_after_actual_clearing": float(redispatch_row["realised_adjusted_profit_eur"]),
                "expected_vs_realised_profit_delta": float(redispatch_row["realised_adjusted_profit_eur"]) - float(expected_row["expected_adjusted_profit_without_regularisation"]),
                "submitted_energy_mwh": submitted_energy,
                "cleared_energy_mwh": cleared_energy,
                "rejected_energy_mwh": rejected_energy,
                "clearing_ratio": float(cleared_energy / submitted_energy) if submitted_energy > 0.0 else 0.0,
                "used_energy_mwh": float(redispatch_row["used_energy_mwh"]),
                "unused_cleared_energy_mwh": float(redispatch_row["unused_cleared_energy_mwh"]),
                "unused_energy_penalty_eur": float(redispatch_row["unused_energy_penalty_eur"]),
                "realised_DA_settlement_cost_eur": float(redispatch_row["realised_DA_settlement_cost_eur"]),
                "hydrogen_sold_or_compressed_kg": float(redispatch_row["hydrogen_compressed_or_sold_kg"]),
                "hydrogen_above_target_kg": float(redispatch_row["hydrogen_above_target_kg"]),
                "capped_reliability_fulfilment": float(redispatch_row["target_fulfilment_ratio_capped_for_reliability"]),
                "uncapped_production_to_target_ratio": float(redispatch_row["production_to_target_ratio_uncapped"]),
                "shortfall_kg": float(redispatch_row["shortfall_kg"]),
                "terminal_inventory_change_kg": float(redispatch_row["terminal_inventory_change_kg"]),
                "terminal_inventory_correction_eur": float(redispatch_row["terminal_inventory_correction_eur"]),
                "actual_price_weighted_average_for_cleared_energy": float(
                    np.average(hourly["actual_price_eur_per_mwh"], weights=hourly["cleared_energy_mwh"])
                )
                if cleared_energy > 0.0
                else float("nan"),
                "number_of_zero_clearing_hours": int((hourly["cleared_energy_mwh"] <= 1e-9).sum()),
                "number_of_partial_clearing_hours": int(
                    ((hourly["clearing_ratio"] > 1e-9) & (hourly["clearing_ratio"] < 1.0 - 1e-9)).sum()
                ),
                "objective_with_regularisation": float(expected_row["objective_with_regularisation"]),
                "expected_adjusted_profit_without_regularisation": float(expected_row["expected_adjusted_profit_without_regularisation"]),
                "regularisation_term": float(expected_row["regularisation_term"]),
                "regularisation_weight": float(expected_row["regularisation_weight"]),
                "nonanticipativity_evidence": expected_row["nonanticipativity_evidence"],
                "stochastic_solver_status": expected_row["solver_status"],
                "redispatch_solver_status": redispatch_row["solver_status"],
            }
        )
    return pd.DataFrame(rows).sort_values("actual_path_id").reset_index(drop=True)


def compute_cvar_sweep_summary(
    *,
    summaries_by_gamma: pd.DataFrame,
    scenario_clearing_by_gamma: pd.DataFrame,
) -> pd.DataFrame:
    if summaries_by_gamma.empty:
        raise ValueError("summaries_by_gamma must be nonempty.")
    if scenario_clearing_by_gamma.empty:
        raise ValueError("scenario_clearing_by_gamma must be nonempty.")

    rows: list[dict[str, Any]] = []
    for gamma, summary_group in summaries_by_gamma.groupby("cvar_gamma", sort=True, dropna=False):
        summary_row = summary_group.iloc[0]
        clearing = scenario_clearing_by_gamma.loc[
            scenario_clearing_by_gamma["cvar_gamma"].astype(float) == float(gamma)
        ].copy()
        accepted = clearing.loc[clearing["accepted"].astype(bool)].copy()
        if not accepted.empty:
            accepted["bid_headroom_eur_per_mwh"] = (
                accepted["bid_price_eur_per_mwh"].astype(float) - accepted["scenario_price_eur_per_mwh"].astype(float)
            )
            headroom_weighted_avg = float(
                np.average(
                    accepted["bid_headroom_eur_per_mwh"].astype(float),
                    weights=accepted["cleared_energy_mwh"].astype(float),
                )
            )
            min_headroom = float(accepted["bid_headroom_eur_per_mwh"].min())
            max_headroom = float(accepted["bid_headroom_eur_per_mwh"].max())
        else:
            headroom_weighted_avg = float("nan")
            min_headroom = float("nan")
            max_headroom = float("nan")
        rows.append(
            {
                "cvar_gamma": float(gamma),
                "risk_measure": summary_row["risk_measure"],
                "cvar_alpha": float(summary_row["cvar_alpha"]),
                "expected_adjusted_profit_eur": float(summary_row["expected_adjusted_profit_eur"]),
                "objective_with_cvar": float(summary_row["objective_with_regularisation"]),
                "objective_without_regularisation": float(summary_row["objective_without_regularisation"]),
                "VaR_loss_zeta": float(summary_row["VaR_loss_zeta"]),
                "CVaR_loss": float(summary_row["CVaR_loss"]),
                "worst_scenario_profit": float(summary_row["worst_scenario_profit"]),
                "worst_scenario_loss": float(summary_row["worst_scenario_loss"]),
                "downside_tail_loss_mean": float(summary_row["downside_tail_loss_mean"]),
                "submitted_energy_mwh": float(summary_row["total_submitted_energy_mwh"]),
                "submitted_energy_mwh_ge_250": float(summary_row["submitted_energy_mwh_ge_250"]),
                "submitted_energy_mwh_ge_3000": float(summary_row["submitted_energy_mwh_ge_3000"]),
                "high_bid_energy_share_ge_250": float(summary_row["high_bid_energy_share_ge_250"]),
                "high_bid_energy_share_ge_3000": float(summary_row["high_bid_energy_share_ge_3000"]),
                "weighted_average_bid_price_eur_per_mwh": float(summary_row["weighted_average_bid_price_eur_per_mwh"]),
                "expected_cleared_energy_mwh": float(summary_row["expected_cleared_energy_mwh"]),
                "expected_used_energy_mwh": float(summary_row["expected_used_energy_mwh"]),
                "expected_unused_cleared_energy_mwh": float(summary_row["expected_unused_cleared_energy_mwh"]),
                "expected_unused_energy_penalty_eur": float(summary_row["expected_unused_energy_penalty_eur"]),
                "expected_hydrogen_sold_kg": float(summary_row["expected_hydrogen_sold_kg"]),
                "minimum_scenario_cleared_energy_mwh": float(summary_row["minimum_scenario_cleared_energy_mwh"]),
                "clearing_reliability_min_scenario_over_submitted": float(summary_row["clearing_reliability_min_scenario_over_submitted"]),
                "expected_shortfall_kg": float(summary_row["expected_shortfall_kg"]),
                "worst_scenario_shortfall_kg": float(summary_row["worst_scenario_shortfall_kg"]),
                "accepted_bid_headroom_weighted_average_eur_per_mwh": headroom_weighted_avg,
                "accepted_bid_headroom_min_eur_per_mwh": min_headroom,
                "accepted_bid_headroom_max_eur_per_mwh": max_headroom,
                "regularisation_term": float(summary_row["regularisation_term"]),
                "regularisation_weight": float(summary_row["regularisation_weight"]),
                "solve_time_seconds": float(summary_row["solve_time_seconds"]),
                "variable_count": int(summary_row["variable_count"]),
                "binary_variable_count": int(summary_row["binary_variable_count"]),
                "constraint_count": int(summary_row["constraint_count"]),
                "scenario_count": int(summary_row["scenario_count"]),
                "horizon_steps": int(summary_row["horizon_steps"]),
                "solver_status": summary_row["solver_status"],
            }
        )
    return pd.DataFrame(rows).sort_values("cvar_gamma").reset_index(drop=True)


def compute_cvar_backtest_frontier_metrics(
    *,
    backtest_results: pd.DataFrame,
) -> pd.DataFrame:
    if backtest_results.empty:
        raise ValueError("backtest_results must be nonempty.")

    rows: list[dict[str, Any]] = []
    for gamma, group in backtest_results.groupby("cvar_gamma", sort=True, dropna=False):
        realised_losses = -group["realised_adjusted_profit_after_actual_clearing"].astype(float)
        probabilities = np.repeat(1.0 / group.shape[0], group.shape[0])
        realised_cvar = compute_weighted_cvar_from_frame(
            pd.DataFrame(
                {
                    "loss_eur": realised_losses.to_numpy(),
                    "scenario_probability": probabilities,
                }
            ),
            loss_column="loss_eur",
            probability_column="scenario_probability",
            alpha=float(group["cvar_alpha"].iloc[0]),
        )
        rows.append(
            {
                "cvar_gamma": float(gamma),
                "risk_measure": group["risk_measure"].iloc[0],
                "cvar_alpha": float(group["cvar_alpha"].iloc[0]),
                "mean_realised_adjusted_profit_eur": float(group["realised_adjusted_profit_after_actual_clearing"].mean()),
                "worst_realised_adjusted_profit_eur": float(group["realised_adjusted_profit_after_actual_clearing"].min()),
                "realised_empirical_CVaR_loss": float(realised_cvar.cvar),
            }
        )
    return pd.DataFrame(rows).sort_values("cvar_gamma").reset_index(drop=True)
