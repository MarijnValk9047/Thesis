from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from .bidding import validate_bid_price_grid


def _resolve_price_column(frame: pd.DataFrame) -> str:
    for column in ("market_price_eur_per_mwh", "actual_price_eur_per_mwh"):
        if column in frame.columns:
            return column
    raise ValueError("Price frame must contain 'market_price_eur_per_mwh' or 'actual_price_eur_per_mwh'.")


def _coerce_price_frame(price_frame: pd.DataFrame) -> pd.DataFrame:
    if "delivery_start_utc" not in price_frame.columns:
        raise ValueError("Price frame must contain delivery_start_utc.")
    resolved = price_frame.copy()
    resolved["delivery_start_utc"] = pd.to_datetime(resolved["delivery_start_utc"], utc=True, errors="raise")
    price_column = _resolve_price_column(resolved)
    resolved["actual_price_eur_per_mwh"] = pd.to_numeric(resolved[price_column], errors="raise")
    if resolved["delivery_start_utc"].duplicated().any():
        raise ValueError("Price frame contains duplicate delivery_start_utc rows.")
    return resolved[["delivery_start_utc", "actual_price_eur_per_mwh"]].sort_values("delivery_start_utc").reset_index(drop=True)


def _bid_group_columns(frame: pd.DataFrame) -> list[str]:
    columns: list[str] = []
    for column in (
        "run_id",
        "strategy",
        "source_strategy",
        "bridge_strategy",
        "actual_path_id",
        "forecast_model",
        "scenario_model",
        "granularity",
        "horizon",
        "forecast_origin_utc",
    ):
        if column in frame.columns:
            columns.append(column)
    return columns


def compute_acceptance_matrix(price_frame: pd.DataFrame, bid_price_grid: Iterable[Any]) -> pd.DataFrame:
    grid = validate_bid_price_grid(bid_price_grid)
    prices = _coerce_price_frame(price_frame)
    acceptance = np.asarray(grid, dtype=float)[None, :] >= prices["actual_price_eur_per_mwh"].to_numpy()[:, None]
    return pd.DataFrame(
        acceptance,
        index=prices["delivery_start_utc"],
        columns=list(range(len(grid))),
    )


def clear_hourly_bids(bid_curve: pd.DataFrame, actual_prices: pd.DataFrame) -> pd.DataFrame:
    required_columns = {
        "run_id",
        "strategy",
        "granularity",
        "horizon",
        "forecast_origin_utc",
        "delivery_start_utc",
        "bid_block",
        "bid_price_eur_per_mwh",
        "bid_quantity_mw",
        "timestep_hours",
    }
    missing = required_columns.difference(bid_curve.columns)
    if missing:
        raise ValueError(f"Bid curve is missing required columns: {sorted(missing)}")

    work = bid_curve.copy()
    work["delivery_start_utc"] = pd.to_datetime(work["delivery_start_utc"], utc=True, errors="raise")
    work["forecast_origin_utc"] = pd.to_datetime(work["forecast_origin_utc"], utc=True, errors="raise")
    work["bid_price_eur_per_mwh"] = pd.to_numeric(work["bid_price_eur_per_mwh"], errors="raise")
    work["bid_quantity_mw"] = pd.to_numeric(work["bid_quantity_mw"], errors="raise")
    work["timestep_hours"] = pd.to_numeric(work["timestep_hours"], errors="raise")

    if (work["bid_quantity_mw"] < 0.0).any():
        raise ValueError("Bid curve contains negative bid_quantity_mw values.")
    duplicate_subset = _bid_group_columns(work) + ["delivery_start_utc", "bid_block"]
    if work.duplicated(subset=duplicate_subset, keep=False).any():
        raise ValueError("Duplicate bid rows detected for the same strategy/time/block key.")

    prices = _coerce_price_frame(actual_prices)
    left_timestamps = set(work["delivery_start_utc"].tolist())
    right_timestamps = set(prices["delivery_start_utc"].tolist())
    if left_timestamps != right_timestamps:
        missing_prices = sorted(left_timestamps.difference(right_timestamps))
        extra_prices = sorted(right_timestamps.difference(left_timestamps))
        raise ValueError(
            "Bid curve timestamps and actual price timestamps do not align. "
            f"missing_prices={missing_prices}, extra_prices={extra_prices}"
        )

    cleared = work.merge(prices, on="delivery_start_utc", how="left", validate="many_to_one")
    cleared["accepted"] = cleared["bid_price_eur_per_mwh"] >= cleared["actual_price_eur_per_mwh"]
    cleared["cleared_quantity_mw"] = np.where(cleared["accepted"], cleared["bid_quantity_mw"], 0.0)
    cleared["cleared_energy_mwh"] = cleared["cleared_quantity_mw"] * cleared["timestep_hours"]
    return cleared.sort_values(["delivery_start_utc", "bid_block"]).reset_index(drop=True)


def aggregate_cleared_energy(clearing_result: pd.DataFrame) -> pd.DataFrame:
    required = {"delivery_start_utc", "bid_quantity_mw", "cleared_quantity_mw", "timestep_hours", "actual_price_eur_per_mwh"}
    missing = required.difference(clearing_result.columns)
    if missing:
        raise ValueError(f"Clearing result is missing required columns: {sorted(missing)}")

    group_columns = _bid_group_columns(clearing_result) + ["delivery_start_utc"]
    grouped = (
        clearing_result.groupby(group_columns, as_index=False, dropna=False)
        .agg(
            actual_price_eur_per_mwh=("actual_price_eur_per_mwh", "first"),
            submitted_quantity_mw=("bid_quantity_mw", "sum"),
            cleared_quantity_mw=("cleared_quantity_mw", "sum"),
            timestep_hours=("timestep_hours", "first"),
        )
    )
    grouped["submitted_energy_mwh"] = grouped["submitted_quantity_mw"] * grouped["timestep_hours"]
    grouped["cleared_energy_mwh"] = grouped["cleared_quantity_mw"] * grouped["timestep_hours"]
    grouped["rejected_energy_mwh"] = grouped["submitted_energy_mwh"] - grouped["cleared_energy_mwh"]
    grouped["clearing_ratio"] = np.where(
        grouped["submitted_energy_mwh"] > 0.0,
        grouped["cleared_energy_mwh"] / grouped["submitted_energy_mwh"],
        0.0,
    )
    return grouped.drop(columns=["timestep_hours"]).sort_values(group_columns).reset_index(drop=True)


def compute_clearing_metrics(clearing_result: pd.DataFrame) -> dict[str, float]:
    group_columns = _bid_group_columns(clearing_result)
    if group_columns:
        unique_groups = clearing_result[group_columns].drop_duplicates()
        if len(unique_groups) != 1:
            raise ValueError("compute_clearing_metrics expects a single strategy/group. Use compute_clearing_metrics_by_group for combined results.")

    aggregated = aggregate_cleared_energy(clearing_result)
    total_submitted_energy = float(aggregated["submitted_energy_mwh"].sum())
    total_cleared_energy = float(aggregated["cleared_energy_mwh"].sum())
    rejected_energy = float(aggregated["rejected_energy_mwh"].sum())
    zero_clearing_hours = int((aggregated["cleared_energy_mwh"] <= 1e-9).sum())
    partial_clearing_hours = int(
        ((aggregated["clearing_ratio"] > 1e-9) & (aggregated["clearing_ratio"] < 1.0 - 1e-9)).sum()
    )
    cleared_hours = aggregated.loc[aggregated["cleared_energy_mwh"] > 1e-9, "actual_price_eur_per_mwh"]
    rejected_hours = aggregated.loc[aggregated["cleared_energy_mwh"] <= 1e-9, "actual_price_eur_per_mwh"]
    return {
        "total_submitted_energy_mwh": total_submitted_energy,
        "total_cleared_energy_mwh": total_cleared_energy,
        "rejected_energy_mwh": rejected_energy,
        "clearing_ratio": float(total_cleared_energy / total_submitted_energy) if total_submitted_energy > 0.0 else 0.0,
        "rejected_bid_rows": int((~clearing_result["accepted"].astype(bool)).sum()),
        "hours_with_zero_clearing": zero_clearing_hours,
        "hours_with_partial_clearing": partial_clearing_hours,
        "average_actual_price_in_cleared_hours": float(cleared_hours.mean()) if not cleared_hours.empty else float("nan"),
        "average_actual_price_in_rejected_hours": float(rejected_hours.mean()) if not rejected_hours.empty else float("nan"),
    }
