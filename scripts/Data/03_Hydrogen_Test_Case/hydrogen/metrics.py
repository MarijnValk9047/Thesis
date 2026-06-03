from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .plant_parameters import HydrogenConfig


def _weighted_quantile(values: np.ndarray, quantile: float, weights: np.ndarray | None = None) -> float:
    if values.size == 0:
        return float("nan")
    if weights is None:
        return float(np.quantile(values, quantile))
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    cutoff = quantile * cumulative[-1]
    return float(sorted_values[np.searchsorted(cumulative, cutoff, side="left")])


def build_period_timeseries(
    *,
    dispatch: pd.DataFrame,
    actual_prices: pd.Series,
    point_forecast: pd.Series,
    strategy: str,
    model_id: str,
    delivery_day: str,
    forecast_origin_utc: pd.Timestamp,
    lead_day: int,
    shortfall_kg: float,
    objective_value_eur: float | None,
    solver_status: str,
    market_model_type: str,
) -> pd.DataFrame:
    frame = dispatch.copy()
    frame["strategy"] = strategy
    frame["model_id"] = model_id
    frame["delivery_day"] = str(delivery_day)
    frame["forecast_origin_utc"] = pd.Timestamp(forecast_origin_utc)
    frame["lead_day"] = int(lead_day)
    frame["actual_price_eur_per_mwh"] = actual_prices.to_numpy()
    frame["point_forecast_eur_per_mwh"] = point_forecast.to_numpy()
    frame["shortfall_kg"] = float(shortfall_kg)
    frame["objective_value_eur"] = float(objective_value_eur) if objective_value_eur is not None else np.nan
    frame["solver_status"] = str(solver_status)
    frame["market_model_type"] = str(market_model_type)
    frame["electrolyser_electricity_mwh"] = frame["P_el_mw"].astype(float)
    frame["compressor_electricity_mwh"] = frame["P_comp_mw"].astype(float)
    frame["total_electricity_mwh"] = frame["electrolyser_electricity_mwh"] + frame["compressor_electricity_mwh"]
    frame["delivery_start_local"] = pd.to_datetime(frame["delivery_start_utc"], utc=True).dt.tz_convert("Europe/Amsterdam")
    return frame


def _add_cost_revenue_columns(frame: pd.DataFrame, config: HydrogenConfig) -> pd.DataFrame:
    scoped = frame.copy()
    scoped["electricity_cost_eur"] = (
        scoped["actual_price_eur_per_mwh"].astype(float)
        * (scoped["P_el_mw"].astype(float) + scoped["P_comp_mw"].astype(float))
        * config.delta_t_hours
    )
    scoped["revenue_eur"] = config.economics.h2_sale_price_eur_per_kg * scoped["H_comp_kg"].astype(float)
    return scoped


def _daily_shortfall(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.groupby(["strategy", "model_id", "delivery_day"], as_index=False)["shortfall_kg"]
        .max()
        .rename(columns={"shortfall_kg": "daily_shortfall_kg"})
    )


def _forecast_metrics_from_scenarios(scenario_period: pd.DataFrame) -> dict[str, float]:
    if scenario_period.empty:
        return {key: float("nan") for key in (
            "MAE", "RMSE", "daily_spearman_rank", "top_k_hit_rate", "bottom_k_hit_rate",
            "scenario_coverage_50", "scenario_coverage_90", "scenario_coverage_95",
            "tail_coverage_high", "tail_coverage_low", "actual_outside_p95_share", "weighted_interval_width",
        )}

    point_actual = (
        scenario_period[["delivery_start_utc", "point_forecast_eur_per_mwh", "actual_price_eur_per_mwh", "delivery_day"]]
        .drop_duplicates(subset=["delivery_start_utc"])
        .sort_values("delivery_start_utc")
    )
    err = point_actual["point_forecast_eur_per_mwh"].astype(float) - point_actual["actual_price_eur_per_mwh"].astype(float)
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(np.square(err))))

    rank_values: list[float] = []
    top_hits: list[float] = []
    bottom_hits: list[float] = []
    for _, day_frame in point_actual.groupby("delivery_day"):
        if day_frame.shape[0] < 4:
            continue
        rank_values.append(float(day_frame["point_forecast_eur_per_mwh"].corr(day_frame["actual_price_eur_per_mwh"], method="spearman")))
        k = max(1, int(np.floor(day_frame.shape[0] * 0.25)))
        pred_top = set(day_frame.nlargest(k, "point_forecast_eur_per_mwh").index.tolist())
        act_top = set(day_frame.nlargest(k, "actual_price_eur_per_mwh").index.tolist())
        pred_bottom = set(day_frame.nsmallest(k, "point_forecast_eur_per_mwh").index.tolist())
        act_bottom = set(day_frame.nsmallest(k, "actual_price_eur_per_mwh").index.tolist())
        top_hits.append(len(pred_top.intersection(act_top)) / k)
        bottom_hits.append(len(pred_bottom.intersection(act_bottom)) / k)

    q_rows: list[dict[str, float]] = []
    for ts, ts_frame in scenario_period.groupby("delivery_start_utc"):
        probs = ts_frame["scenario_probability"].astype(float).to_numpy()
        values = ts_frame["scenario_price_eur_per_mwh"].astype(float).to_numpy()
        actual = float(ts_frame["actual_price_eur_per_mwh"].iloc[0])
        q05 = _weighted_quantile(values, 0.05, probs)
        q25 = _weighted_quantile(values, 0.25, probs)
        q50 = _weighted_quantile(values, 0.50, probs)
        q75 = _weighted_quantile(values, 0.75, probs)
        q95 = _weighted_quantile(values, 0.95, probs)
        q025 = _weighted_quantile(values, 0.025, probs)
        q975 = _weighted_quantile(values, 0.975, probs)
        q_rows.append(
            {
                "ts": pd.Timestamp(ts),
                "actual": actual,
                "q05": q05,
                "q25": q25,
                "q50": q50,
                "q75": q75,
                "q95": q95,
                "q025": q025,
                "q975": q975,
            }
        )
    q = pd.DataFrame(q_rows)
    coverage_50 = float(((q["actual"] >= q["q25"]) & (q["actual"] <= q["q75"])).mean()) if not q.empty else float("nan")
    coverage_90 = float(((q["actual"] >= q["q05"]) & (q["actual"] <= q["q95"])).mean()) if not q.empty else float("nan")
    coverage_95 = float(((q["actual"] >= q["q025"]) & (q["actual"] <= q["q975"])).mean()) if not q.empty else float("nan")
    tail_high = float((q["actual"] <= q["q95"]).mean()) if not q.empty else float("nan")
    tail_low = float((q["actual"] >= q["q05"]).mean()) if not q.empty else float("nan")
    outside_p95 = float(((q["actual"] < q["q025"]) | (q["actual"] > q["q975"])).mean()) if not q.empty else float("nan")
    width = float((q["q95"] - q["q05"]).mean()) if not q.empty else float("nan")

    return {
        "MAE": mae,
        "RMSE": rmse,
        "daily_spearman_rank": float(np.nanmean(rank_values)) if rank_values else float("nan"),
        "top_k_hit_rate": float(np.nanmean(top_hits)) if top_hits else float("nan"),
        "bottom_k_hit_rate": float(np.nanmean(bottom_hits)) if bottom_hits else float("nan"),
        "scenario_coverage_50": coverage_50,
        "scenario_coverage_90": coverage_90,
        "scenario_coverage_95": coverage_95,
        "tail_coverage_high": tail_high,
        "tail_coverage_low": tail_low,
        "actual_outside_p95_share": outside_p95,
        "weighted_interval_width": width,
    }


def _empirical_cvar(values: pd.Series, alpha: float) -> float:
    if values.empty:
        return float("nan")
    q = float(values.quantile(alpha))
    tail = values[values >= q]
    if tail.empty:
        return q
    return float(tail.mean())


def compute_all_metrics(
    *,
    timeseries: pd.DataFrame,
    scenario_period: pd.DataFrame,
    cvar_by_strategy: dict[str, float | None],
    config: HydrogenConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scoped = _add_cost_revenue_columns(timeseries, config)
    daily_shortfall = _daily_shortfall(scoped)

    daily = (
        scoped.groupby(["strategy", "model_id", "delivery_day"], as_index=False)
        .agg(
            produced_hydrogen_kg=("H_prod_kg", "sum"),
            compressed_hydrogen_kg=("H_comp_kg", "sum"),
            gross_revenue_eur=("revenue_eur", "sum"),
            electricity_cost_eur=("electricity_cost_eur", "sum"),
            total_electricity_mwh=("total_electricity_mwh", lambda s: float(np.sum(s) * config.delta_t_hours)),
            electrolyser_electricity_mwh=("electrolyser_electricity_mwh", lambda s: float(np.sum(s) * config.delta_t_hours)),
            compressor_electricity_mwh=("compressor_electricity_mwh", lambda s: float(np.sum(s) * config.delta_t_hours)),
            buffer_end_kg=("H_buf_kg", "last"),
            buffer_start_kg=("H_buf_kg", "first"),
            buffer_min_kg=("H_buf_kg", "min"),
            buffer_max_kg=("H_buf_kg", "max"),
            electrolyser_ramp_total_mw=("P_el_mw", lambda s: float(np.sum(np.abs(np.diff(s.to_numpy()))))),
            reserve_binding_hours=("H_buf_kg", lambda s: float(np.sum(np.isclose(s.to_numpy(), config.hydrogen_system.reserve_kg, atol=1e-3)))),
            objective_value_eur=("objective_value_eur", "last"),
            solver_status=("solver_status", lambda s: "|".join(sorted({str(value) for value in s if pd.notna(value)}))),
            market_model_type=("market_model_type", lambda s: "|".join(sorted({str(value) for value in s if pd.notna(value)}))),
        )
    )
    daily = daily.merge(daily_shortfall, on=["strategy", "model_id", "delivery_day"], how="left")
    daily["shortfall_penalty_eur"] = daily["daily_shortfall_kg"] * config.economics.shortfall_penalty_eur_per_kg
    daily["net_profit_eur"] = daily["gross_revenue_eur"] - daily["electricity_cost_eur"] - daily["shortfall_penalty_eur"]
    daily["terminal_inventory_value_eur"] = 0.0
    daily["adjusted_net_profit_eur"] = daily["net_profit_eur"]
    daily["target_hydrogen_kg"] = float(config.economics.daily_target_kg)
    daily["hydrogen_above_target_kg"] = np.maximum(daily["compressed_hydrogen_kg"] - daily["target_hydrogen_kg"], 0.0)
    daily["target_fulfilment_ratio_capped_for_reliability"] = np.minimum(
        daily["compressed_hydrogen_kg"],
        daily["target_hydrogen_kg"],
    ) / daily["target_hydrogen_kg"]
    daily["production_to_target_ratio_uncapped"] = daily["compressed_hydrogen_kg"] / daily["target_hydrogen_kg"]
    daily["target_fulfilment_pct"] = daily["target_fulfilment_ratio_capped_for_reliability"] * 100.0
    daily["buffer_delta_kg"] = daily["buffer_end_kg"] - daily["buffer_start_kg"]
    daily["average_price_paid_eur_per_mwh"] = np.where(
        daily["total_electricity_mwh"] > 0.0,
        daily["electricity_cost_eur"] / daily["total_electricity_mwh"],
        np.nan,
    )

    final_rows: list[pd.DataFrame] = []
    for (strategy, model_id), grp in daily.groupby(["strategy", "model_id"]):
        ordered = grp.sort_values("delivery_day").copy()
        if ordered.empty:
            continue
        delta_inv = float(ordered["buffer_end_kg"].iloc[-1] - timeseries[(timeseries["strategy"] == strategy) & (timeseries["model_id"] == model_id)]["H_buf_kg"].iloc[0])
        terminal_value = config.terminal_inventory_value_per_kg * delta_inv
        ordered.loc[ordered.index[-1], "terminal_inventory_value_eur"] = terminal_value
        ordered["adjusted_net_profit_eur"] = ordered["net_profit_eur"]
        ordered.loc[ordered.index[-1], "adjusted_net_profit_eur"] += terminal_value
        final_rows.append(ordered)
    daily = pd.concat(final_rows, ignore_index=True) if final_rows else daily

    daily["net_cost_eur"] = -daily["adjusted_net_profit_eur"]
    daily["date"] = pd.to_datetime(daily["delivery_day"])
    daily["iso_year"] = daily["date"].dt.isocalendar().year.astype(int)
    daily["iso_week"] = daily["date"].dt.isocalendar().week.astype(int)
    daily["iso_week_id"] = daily["iso_year"].astype(str) + "-W" + daily["iso_week"].astype(str).str.zfill(2)

    weekly = (
        daily.groupby(["strategy", "model_id", "iso_week_id"], as_index=False)
        .agg(
            produced_hydrogen_kg=("produced_hydrogen_kg", "sum"),
            compressed_hydrogen_kg=("compressed_hydrogen_kg", "sum"),
            gross_revenue_eur=("gross_revenue_eur", "sum"),
            electricity_cost_eur=("electricity_cost_eur", "sum"),
            shortfall_penalty_eur=("shortfall_penalty_eur", "sum"),
            net_profit_eur=("net_profit_eur", "sum"),
            adjusted_net_profit_eur=("adjusted_net_profit_eur", "sum"),
            shortfall_kg=("daily_shortfall_kg", "sum"),
            shortfall_days=("daily_shortfall_kg", lambda s: int((s > 0).sum())),
            buffer_end_kg=("buffer_end_kg", "last"),
            objective_value_eur=("objective_value_eur", "sum"),
        )
    )

    summary = (
        daily.groupby(["strategy", "model_id"], as_index=False)
        .agg(
            produced_hydrogen_kg=("produced_hydrogen_kg", "sum"),
            compressed_hydrogen_kg=("compressed_hydrogen_kg", "sum"),
            hydrogen_above_target_kg=("hydrogen_above_target_kg", "sum"),
            gross_revenue_eur=("gross_revenue_eur", "sum"),
            electricity_cost_eur=("electricity_cost_eur", "sum"),
            shortfall_penalty_eur=("shortfall_penalty_eur", "sum"),
            net_profit_eur=("net_profit_eur", "sum"),
            adjusted_net_profit_eur=("adjusted_net_profit_eur", "sum"),
            terminal_inventory_value_eur=("terminal_inventory_value_eur", "sum"),
            total_electricity_mwh=("total_electricity_mwh", "sum"),
            shortfall_kg=("daily_shortfall_kg", "sum"),
            shortfall_days=("daily_shortfall_kg", lambda s: int((s > 0).sum())),
            solver_status=("solver_status", lambda s: "|".join(sorted({str(value) for value in s if pd.notna(value)}))),
            market_model_type=("market_model_type", lambda s: "|".join(sorted({str(value) for value in s if pd.notna(value)}))),
            buffer_min_kg=("buffer_min_kg", "min"),
            buffer_max_kg=("buffer_max_kg", "max"),
            buffer_start_kg=("buffer_start_kg", "first"),
            buffer_end_kg=("buffer_end_kg", "last"),
            reserve_binding_hours=("reserve_binding_hours", "sum"),
            electrolyser_ramp_total_mw=("electrolyser_ramp_total_mw", "sum"),
            objective_value_eur=("objective_value_eur", "sum"),
        )
    )
    day_counts = daily.groupby(["strategy", "model_id"], as_index=False)["delivery_day"].nunique().rename(columns={"delivery_day": "delivery_day_count"})
    summary = summary.merge(day_counts, on=["strategy", "model_id"], how="left")
    summary["target_hydrogen_kg"] = config.economics.daily_target_kg * summary["delivery_day_count"].astype(float)
    summary["target_fulfilment_ratio_capped_for_reliability"] = np.minimum(
        summary["compressed_hydrogen_kg"],
        summary["target_hydrogen_kg"],
    ) / summary["target_hydrogen_kg"]
    summary["production_to_target_ratio_uncapped"] = summary["compressed_hydrogen_kg"] / summary["target_hydrogen_kg"]
    summary["target_fulfilment_pct"] = summary["target_fulfilment_ratio_capped_for_reliability"] * 100.0
    summary["profit_margin_pct"] = np.where(summary["gross_revenue_eur"] > 0, summary["adjusted_net_profit_eur"] / summary["gross_revenue_eur"] * 100.0, np.nan)
    summary["buffer_delta_kg"] = summary["buffer_end_kg"] - summary["buffer_start_kg"]
    summary["average_price_paid_eur_per_mwh"] = np.where(
        summary["total_electricity_mwh"] > 0,
        summary["electricity_cost_eur"] / summary["total_electricity_mwh"],
        np.nan,
    )
    summary["electricity_cost_per_kg_h2"] = np.where(summary["compressed_hydrogen_kg"] > 0, summary["electricity_cost_eur"] / summary["compressed_hydrogen_kg"], np.nan)
    summary["electrolyser_full_load_hours"] = summary["total_electricity_mwh"] / config.hydrogen_system.electrolyser_nominal_mw
    summary["compressor_full_load_hours"] = summary["total_electricity_mwh"] / max(config.hydrogen_system.compressor_max_mw, 1e-6)
    start_counts = (
        scoped.sort_values(["strategy", "model_id", "delivery_start_utc"])
        .groupby(["strategy", "model_id"])["u_el"]
        .apply(lambda s: int(np.sum((s.astype(float).to_numpy()[1:] >= 0.5) & (s.astype(float).to_numpy()[:-1] < 0.5))))
        .rename("electrolyser_start_count")
        .reset_index()
    )
    summary = summary.merge(start_counts, on=["strategy", "model_id"], how="left")
    summary["optimisation_CVaR"] = summary["strategy"].map(cvar_by_strategy)
    summary["realised_empirical_CVaR"] = summary["strategy"].map(
        lambda strategy: _empirical_cvar(daily[daily["strategy"] == strategy]["net_cost_eur"], config.risk.alpha)
    )
    summary["worst_day_profit"] = summary["strategy"].map(lambda s: float(daily[daily["strategy"] == s]["adjusted_net_profit_eur"].min()))
    summary["worst_week_profit"] = summary["strategy"].map(lambda s: float(weekly[weekly["strategy"] == s]["adjusted_net_profit_eur"].min()))
    summary["p05_daily_profit"] = summary["strategy"].map(lambda s: float(daily[daily["strategy"] == s]["adjusted_net_profit_eur"].quantile(0.05)))
    summary["p95_daily_cost"] = summary["strategy"].map(lambda s: float(daily[daily["strategy"] == s]["net_cost_eur"].quantile(0.95)))

    base_profit = summary.loc[summary["strategy"] == "price_insensitive", "adjusted_net_profit_eur"]
    base_profit_value = float(base_profit.iloc[0]) if not base_profit.empty else np.nan
    summary["profit_uplift_vs_price_insensitive_eur"] = summary["adjusted_net_profit_eur"] - base_profit_value
    summary["profit_uplift_vs_price_insensitive_pct"] = np.where(
        np.isfinite(base_profit_value) and abs(base_profit_value) > 1e-9,
        summary["profit_uplift_vs_price_insensitive_eur"] / base_profit_value * 100.0,
        np.nan,
    )
    pf_profit = summary.loc[summary["strategy"] == "perfect_foresight", "adjusted_net_profit_eur"]
    pf_profit_value = float(pf_profit.iloc[0]) if not pf_profit.empty else np.nan
    summary["perfect_foresight_value_captured_pct"] = np.where(
        np.isfinite(pf_profit_value) and abs(pf_profit_value) > 1e-9,
        summary["adjusted_net_profit_eur"] / pf_profit_value * 100.0,
        np.nan,
    )
    summary["terminal_inventory_start_kg"] = summary["buffer_start_kg"]
    summary["terminal_inventory_end_kg"] = summary["buffer_end_kg"]
    summary["terminal_inventory_change_kg"] = summary["buffer_delta_kg"]
    summary["terminal_inventory_correction_eur"] = summary["terminal_inventory_value_eur"]
    summary["revenue_from_total_hydrogen_eur"] = summary["gross_revenue_eur"]
    summary["revenue_associated_with_above_target_hydrogen_eur"] = (
        summary["hydrogen_above_target_kg"] * config.economics.h2_sale_price_eur_per_kg
    )

    forecast_metrics = _forecast_metrics_from_scenarios(scenario_period)
    for key, value in forecast_metrics.items():
        summary[key] = value

    for strategy, group in scoped.groupby("strategy"):
        total_power = group["P_el_mw"].astype(float) + group["P_comp_mw"].astype(float)
        prices = group["actual_price_eur_per_mwh"].astype(float)
        q25, q75 = prices.quantile(0.25), prices.quantile(0.75)
        low_mask = prices <= q25
        high_mask = prices >= q75
        energy_total = float(np.sum(total_power * config.delta_t_hours))
        low_share = float(np.sum(total_power[low_mask] * config.delta_t_hours) / energy_total) if energy_total > 0 else np.nan
        high_share = float(np.sum(total_power[high_mask] * config.delta_t_hours) / energy_total) if energy_total > 0 else np.nan
        weighted_paid = float(np.sum(prices * total_power * config.delta_t_hours) / energy_total) if energy_total > 0 else np.nan
        mean_market = float(np.mean(prices))
        if group.shape[0] > 2 and prices.nunique() > 1 and total_power.nunique() > 1:
            price_consumption_correlation = float(np.corrcoef(prices, total_power)[0, 1])
        else:
            price_consumption_correlation = np.nan
        idx = summary["strategy"] == strategy
        summary.loc[idx, "price_consumption_correlation"] = price_consumption_correlation
        summary.loc[idx, "consumption_in_cheapest_25_pct_periods"] = low_share
        summary.loc[idx, "consumption_in_most_expensive_25_pct_periods"] = high_share
        summary.loc[idx, "average_consumed_price_discount"] = mean_market - weighted_paid if np.isfinite(weighted_paid) else np.nan
        summary.loc[idx, "high_price_avoidance_rate"] = 1.0 - min(high_share / 0.25, 1.0) if np.isfinite(high_share) else np.nan
        summary.loc[idx, "low_price_capture_rate"] = min(low_share / 0.25, 1.0) if np.isfinite(low_share) else np.nan

    cvar_summary = summary[["strategy", "model_id", "optimisation_CVaR", "realised_empirical_CVaR", "worst_day_profit", "p95_daily_cost"]].copy()
    return summary.reset_index(drop=True), daily.reset_index(drop=True), weekly.reset_index(drop=True), cvar_summary.reset_index(drop=True)
