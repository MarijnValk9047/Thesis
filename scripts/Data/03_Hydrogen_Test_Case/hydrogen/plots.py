from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def _scenario_quantiles(scenario_period: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    for ts, grp in scenario_period.groupby("delivery_start_utc"):
        probs = grp["scenario_probability"].astype(float).to_numpy()
        values = grp["scenario_price_eur_per_mwh"].astype(float).to_numpy()
        order = np.argsort(values)
        values = values[order]
        probs = probs[order]
        cum = np.cumsum(probs)
        def q(alpha: float) -> float:
            idx = np.searchsorted(cum, alpha, side="left")
            idx = min(idx, len(values) - 1)
            return float(values[idx])
        rows.append(
            {
                "delivery_start_utc": pd.Timestamp(ts),
                "q05": q(0.05),
                "q50": q(0.50),
                "q95": q(0.95),
                "point": float(grp["point_forecast_eur_per_mwh"].iloc[0]),
                "actual": float(grp["actual_price_eur_per_mwh"].iloc[0]),
            }
        )
    return pd.DataFrame(rows).sort_values("delivery_start_utc").reset_index(drop=True)


def plot_price_scenario_operation(
    *,
    scenario_period: pd.DataFrame,
    dispatch: pd.DataFrame,
    output_dir: Path,
    filename: str = "01_price_scenario_operation.png",
) -> Path:
    q = _scenario_quantiles(scenario_period)
    op = dispatch.sort_values("delivery_start_utc")
    fig, ax1 = plt.subplots(figsize=(13, 5))
    ax1.fill_between(q["delivery_start_utc"], q["q05"], q["q95"], alpha=0.25, label="Scenario p05-p95")
    ax1.plot(q["delivery_start_utc"], q["q50"], label="Scenario median", linewidth=1.6)
    ax1.plot(q["delivery_start_utc"], q["point"], label="Point forecast", linestyle="--", linewidth=1.2)
    ax1.plot(q["delivery_start_utc"], q["actual"], label="Actual price", linewidth=1.8)
    ax1.set_ylabel("EUR/MWh")
    ax1.legend(loc="upper left")

    ax2 = ax1.twinx()
    ax2.step(op["delivery_start_utc"], op["P_el_mw"], where="post", label="Electrolyser MW", color="#2b8cbe")
    ax2.step(op["delivery_start_utc"], op["P_comp_mw"], where="post", label="Compressor MW", color="#f03b20")
    ax2.set_ylabel("MW")
    ax2.legend(loc="upper right")
    return _save(fig, output_dir / filename)


def plot_buffer_trajectory(
    *,
    dispatch: pd.DataFrame,
    reserve_kg: float,
    buffer_capacity_kg: float,
    daily_target_kg: float,
    output_dir: Path,
    filename: str = "02_buffer_trajectory.png",
) -> Path:
    frame = dispatch.sort_values("delivery_start_utc").copy()
    frame["cum_prod"] = frame["H_prod_kg"].cumsum()
    frame["cum_comp"] = frame["H_comp_kg"].cumsum()
    fig, ax1 = plt.subplots(figsize=(13, 5))
    ax1.plot(frame["delivery_start_utc"], frame["H_buf_kg"], label="Buffer kg", linewidth=2.0)
    ax1.axhline(reserve_kg, color="#d95f0e", linestyle="--", label="Reserve")
    ax1.axhline(buffer_capacity_kg, color="#252525", linestyle=":", label="Max capacity")
    ax1.set_ylabel("Buffer kg")
    ax1.legend(loc="upper left")

    ax2 = ax1.twinx()
    ax2.plot(frame["delivery_start_utc"], frame["cum_prod"], label="Cumulative produced", color="#1b9e77")
    ax2.plot(frame["delivery_start_utc"], frame["cum_comp"], label="Cumulative compressed/sold", color="#7570b3")
    ax2.axhline(daily_target_kg, color="#e7298a", linestyle="--", label="Daily target")
    ax2.set_ylabel("Cumulative kg")
    ax2.legend(loc="upper right")
    return _save(fig, output_dir / filename)


def plot_strategy_comparison_dashboard(
    *,
    summary: pd.DataFrame,
    output_dir: Path,
    filename: str = "03_strategy_comparison_dashboard.png",
) -> Path:
    metrics = [
        ("adjusted_net_profit_eur", "Adjusted net profit"),
        ("compressed_hydrogen_kg", "Produced/sold hydrogen"),
        ("average_price_paid_eur_per_mwh", "Average price paid"),
        ("realised_empirical_CVaR", "Realised empirical CVaR"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    axes_flat = axes.flatten()
    for idx, (metric, title) in enumerate(metrics):
        ax = axes_flat[idx]
        plot_frame = summary.sort_values("strategy")
        ax.bar(plot_frame["strategy"], plot_frame[metric], color="#3182bd")
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=25)
    return _save(fig, output_dir / filename)


def plot_cvar_frontier(
    *,
    cvar_sweep: pd.DataFrame,
    output_dir: Path,
    filename: str = "04_cvar_frontier.png",
) -> Path | None:
    if cvar_sweep.empty:
        return None
    fig, ax = plt.subplots(figsize=(8, 5))
    grouped = cvar_sweep.sort_values("gamma")
    ax.plot(grouped["realised_empirical_CVaR"], grouped["adjusted_net_profit_eur"], marker="o")
    for row in grouped.to_dict(orient="records"):
        ax.annotate(f"g={row['gamma']}", (row["realised_empirical_CVaR"], row["adjusted_net_profit_eur"]), fontsize=8)
    ax.set_xlabel("Realised empirical CVaR")
    ax.set_ylabel("Adjusted net profit (EUR)")
    ax.set_title("CVaR risk-return frontier")
    return _save(fig, output_dir / filename)


def plot_consumption_quartiles(
    *,
    summary: pd.DataFrame,
    output_dir: Path,
    filename: str = "05_consumption_quartiles.png",
) -> Path:
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(summary.shape[0])
    width = 0.35
    ax.bar(x - width / 2, summary["consumption_in_cheapest_25_pct_periods"], width, label="Cheapest quartile share")
    ax.bar(x + width / 2, summary["consumption_in_most_expensive_25_pct_periods"], width, label="Most expensive quartile share")
    ax.set_xticks(x)
    ax.set_xticklabels(summary["strategy"], rotation=25)
    ax.set_ylabel("Share of electricity consumption")
    ax.legend()
    return _save(fig, output_dir / filename)


def plot_consumption_delta_vs_baseline(
    *,
    timeseries: pd.DataFrame,
    strategy: str,
    output_dir: Path,
    filename: str = "06_consumption_delta_vs_price_insensitive.png",
) -> Path | None:
    baseline = timeseries[timeseries["strategy"] == "price_insensitive"].copy()
    contender = timeseries[timeseries["strategy"] == strategy].copy()
    if baseline.empty or contender.empty:
        return None
    cols = ["delivery_start_utc", "P_el_mw", "P_comp_mw", "actual_price_eur_per_mwh"]
    merged = contender[cols].merge(
        baseline[["delivery_start_utc", "P_el_mw", "P_comp_mw"]],
        on="delivery_start_utc",
        suffixes=("_strategy", "_baseline"),
    )
    merged["delta_el"] = merged["P_el_mw_strategy"] - merged["P_el_mw_baseline"]
    merged["delta_comp"] = merged["P_comp_mw_strategy"] - merged["P_comp_mw_baseline"]

    fig, axes = plt.subplots(2, 1, figsize=(13, 6), sharex=True)
    axes[0].step(merged["delivery_start_utc"], merged["delta_el"], where="post", label="Electrolyser delta MW")
    axes[0].step(merged["delivery_start_utc"], merged["delta_comp"], where="post", label="Compressor delta MW")
    axes[0].legend(loc="upper right")
    axes[0].set_ylabel("MW delta")
    axes[1].plot(merged["delivery_start_utc"], merged["actual_price_eur_per_mwh"], color="#2b2b2b", label="Actual price")
    axes[1].legend(loc="upper right")
    axes[1].set_ylabel("EUR/MWh")
    return _save(fig, output_dir / filename)


def plot_baseline_dispatch(
    *,
    dispatch: pd.DataFrame,
    output_dir: Path,
    filename: str = "07_baseline_dispatch.png",
) -> Path:
    frame = dispatch.sort_values("delivery_start_utc").copy()
    fig, ax1 = plt.subplots(figsize=(13, 5))
    if "actual_price_eur_per_mwh" in frame.columns:
        ax1.plot(frame["delivery_start_utc"], frame["actual_price_eur_per_mwh"], color="#1f1f1f", linewidth=1.8, label="Actual DA price")
    ax1.set_ylabel("EUR/MWh")
    ax1.legend(loc="upper left")

    ax2 = ax1.twinx()
    ax2.step(frame["delivery_start_utc"], frame["P_el_mw"], where="post", color="#2b8cbe", label="Electrolyser load")
    ax2.step(frame["delivery_start_utc"], frame["P_comp_mw"], where="post", color="#d95f0e", label="Compressor load")
    ax2.plot(frame["delivery_start_utc"], frame["H_buf_kg"], color="#31a354", linewidth=1.8, label="Storage level")
    ax2.set_ylabel("MW / kg")
    ax2.legend(loc="upper right")
    return _save(fig, output_dir / filename)


def plot_physical_balance(
    *,
    dispatch: pd.DataFrame,
    output_dir: Path,
    filename: str = "08_physical_balance.png",
) -> Path:
    frame = dispatch.sort_values("delivery_start_utc").copy()
    fig, ax1 = plt.subplots(figsize=(13, 5))
    ax1.bar(frame["delivery_start_utc"], frame["H_prod_kg"], width=0.03, color="#2b8cbe", label="Hydrogen produced")
    ax1.bar(frame["delivery_start_utc"], -frame["H_comp_kg"], width=0.03, color="#d95f0e", label="Hydrogen compressed/sold")
    ax1.set_ylabel("kg per timestep")
    ax1.legend(loc="upper left")

    ax2 = ax1.twinx()
    ax2.plot(frame["delivery_start_utc"], frame["H_buf_kg"], color="#31a354", linewidth=2.0, label="Buffer level")
    ax2.set_ylabel("Buffer kg")
    ax2.legend(loc="upper right")
    return _save(fig, output_dir / filename)


def plot_benchmark_comparison(
    *,
    summary: pd.DataFrame,
    output_dir: Path,
    filename: str = "09_benchmark_comparison.png",
) -> Path:
    plot_frame = summary.sort_values("strategy").copy()
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(plot_frame["strategy"], plot_frame["adjusted_net_profit_eur"], color="#3182bd")
    ax.set_ylabel("Adjusted net profit (EUR)")
    ax.set_title("Benchmark comparison")
    ax.tick_params(axis="x", rotation=25)
    return _save(fig, output_dir / filename)


def plot_toy_bid_curve(
    *,
    bid_curve: pd.DataFrame,
    actual_prices: pd.DataFrame,
    delivery_start_utc: str | pd.Timestamp,
    output_dir: Path,
    filename: str = "toy_bid_curve.png",
) -> Path:
    prices = actual_prices.copy()
    prices["delivery_start_utc"] = pd.to_datetime(prices["delivery_start_utc"], utc=True, errors="raise")
    bids = bid_curve.copy()
    bids["delivery_start_utc"] = pd.to_datetime(bids["delivery_start_utc"], utc=True, errors="raise")
    target_ts = pd.Timestamp(pd.to_datetime(delivery_start_utc, utc=True, errors="raise"))

    bid_frame = bids[bids["delivery_start_utc"] == target_ts].sort_values("bid_price_eur_per_mwh")
    if bid_frame.empty:
        raise ValueError(f"No bid data available for {target_ts}.")
    price_row = prices.loc[prices["delivery_start_utc"] == target_ts]
    if price_row.empty:
        raise ValueError(f"No actual price available for {target_ts}.")
    actual_price = float(price_row["actual_price_eur_per_mwh"].iloc[0])

    bid_frame["cumulative_quantity_mw"] = bid_frame["bid_quantity_mw"].cumsum()
    accepted_mask = bid_frame["bid_price_eur_per_mwh"] >= actual_price

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.step(
        bid_frame["bid_price_eur_per_mwh"],
        bid_frame["cumulative_quantity_mw"],
        where="post",
        color="#2b8cbe",
        label="Cumulative submitted demand",
    )
    if accepted_mask.any():
        accepted = bid_frame.loc[accepted_mask]
        ax.fill_between(
            accepted["bid_price_eur_per_mwh"],
            accepted["cumulative_quantity_mw"],
            step="post",
            alpha=0.25,
            color="#31a354",
            label="Accepted blocks",
        )
    ax.axvline(actual_price, color="#d95f0e", linestyle="--", label="Actual price")
    ax.set_xlabel("Bid price (EUR/MWh)")
    ax.set_ylabel("Cumulative submitted demand (MW)")
    ax.legend()
    return _save(fig, output_dir / filename)


def plot_acceptance_heatmap(
    *,
    acceptance_matrix: pd.DataFrame,
    output_dir: Path,
    filename: str = "acceptance_heatmap.png",
) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4))
    image = ax.imshow(acceptance_matrix.astype(int).to_numpy(), aspect="auto", cmap="Greens", vmin=0, vmax=1)
    ax.set_xlabel("Bid block")
    ax.set_ylabel("Hour")
    ax.set_xticks(range(acceptance_matrix.shape[1]))
    ax.set_xticklabels([str(value) for value in acceptance_matrix.columns])
    ax.set_yticks(range(acceptance_matrix.shape[0]))
    ax.set_yticklabels([str(ts) for ts in acceptance_matrix.index])
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Accepted (1=yes, 0=no)")
    return _save(fig, output_dir / filename)


def plot_scheduled_vs_cleared_electricity(
    *,
    clearing_by_hour: pd.DataFrame,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path:
    frame = clearing_by_hour.sort_values("delivery_start_utc").copy()
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.step(frame["delivery_start_utc"], frame["submitted_quantity_mw"], where="post", label="Scheduled/submitted load", color="#2b8cbe")
    ax.step(frame["delivery_start_utc"], frame["cleared_quantity_mw"], where="post", label="Cleared load", color="#31a354")
    ax.fill_between(
        frame["delivery_start_utc"],
        frame["cleared_quantity_mw"],
        frame["submitted_quantity_mw"],
        step="post",
        alpha=0.25,
        color="#d95f0e",
        label="Rejected load",
    )
    ax.set_ylabel("MW")
    ax.set_title(title or "Scheduled vs cleared electricity")
    ax.legend(loc="upper right")
    return _save(fig, output_dir / filename)


def plot_actual_price_vs_bid_price(
    *,
    clearing_by_hour: pd.DataFrame,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path:
    frame = clearing_by_hour.sort_values("delivery_start_utc").copy()
    bid_price = frame["bid_price_eur_per_mwh"].iloc[0] if "bid_price_eur_per_mwh" in frame.columns else np.nan
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(frame["delivery_start_utc"], frame["actual_price_eur_per_mwh"], color="#1f1f1f", linewidth=1.8, label="Actual DA price")
    ax.axhline(bid_price, color="#2b8cbe", linestyle="--", linewidth=1.5, label="Bid price")
    rejected = frame["clearing_ratio"] <= 1e-9
    if rejected.any():
        ax.scatter(
            frame.loc[rejected, "delivery_start_utc"],
            frame.loc[rejected, "actual_price_eur_per_mwh"],
            color="#d95f0e",
            label="Rejected hours",
            zorder=3,
        )
    ax.set_ylabel("EUR/MWh")
    ax.set_title(title or "Actual price vs bid price")
    ax.legend(loc="upper right")
    return _save(fig, output_dir / filename)


def plot_bid_clearing_waterfall(
    *,
    metrics_row: pd.Series,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path:
    labels = ["Submitted", "Rejected", "Cleared"]
    values = [
        float(metrics_row["submitted_energy_mwh"]),
        float(metrics_row["rejected_energy_mwh"]),
        float(metrics_row["cleared_energy_mwh"]),
    ]
    colors = ["#2b8cbe", "#d95f0e", "#31a354"]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.bar(labels, values, color=colors)
    ax.set_ylabel("Energy (MWh)")
    ax.set_title(title or "Bid-clearing waterfall")
    return _save(fig, output_dir / filename)


def plot_bridge_clearing_heatmap(
    *,
    clearing_by_hour: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path:
    frame = clearing_by_hour.copy()
    frame["hour_label"] = pd.to_datetime(frame["delivery_start_utc"], utc=True).dt.strftime("%Y-%m-%d %H:%M")
    frame["column_label"] = frame["source_strategy"].astype(str) + " | " + frame["bridge_strategy"].astype(str)
    pivot = frame.pivot(index="hour_label", columns="column_label", values="clearing_ratio").sort_index()

    fig, ax = plt.subplots(figsize=(max(8, pivot.shape[1] * 1.2), 5))
    image = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="Blues", vmin=0.0, vmax=1.0)
    ax.set_xlabel("Source strategy | bridge strategy")
    ax.set_ylabel("Hour")
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels(list(pivot.columns), rotation=35, ha="right")
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(list(pivot.index))
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Clearing ratio")
    return _save(fig, output_dir / filename)


def plot_cleared_used_unused_electricity(
    *,
    redispatch: pd.DataFrame,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path:
    frame = redispatch.sort_values("delivery_start_utc").copy()
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.step(frame["delivery_start_utc"], frame["cleared_energy_mwh"], where="post", label="Cleared energy", color="#2b8cbe")
    ax.step(frame["delivery_start_utc"], frame["used_energy_mwh"], where="post", label="Used energy", color="#31a354")
    ax.fill_between(
        frame["delivery_start_utc"],
        frame["used_energy_mwh"],
        frame["cleared_energy_mwh"],
        step="post",
        alpha=0.25,
        color="#d95f0e",
        label="Unused cleared energy",
    )
    ax.set_ylabel("MWh")
    ax.set_title(title or "Cleared vs used vs unused electricity")
    ax.legend(loc="upper right")
    return _save(fig, output_dir / filename)


def plot_redispatch_operation(
    *,
    redispatch: pd.DataFrame,
    reserve_kg: float,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path:
    frame = redispatch.sort_values("delivery_start_utc").copy()
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.step(frame["delivery_start_utc"], frame["P_el_mw"], where="post", color="#2b8cbe", label="Electrolyser power")
    ax1.step(frame["delivery_start_utc"], frame["P_comp_mw"], where="post", color="#d95f0e", label="Compressor power")
    ax1.set_ylabel("MW")
    ax1.legend(loc="upper left")

    ax2 = ax1.twinx()
    ax2.plot(frame["delivery_start_utc"], frame["H_buf_kg"], color="#31a354", linewidth=1.8, label="Hydrogen storage")
    ax2.axhline(reserve_kg, color="#6a3d9a", linestyle="--", label="Reserve")
    ax2.set_ylabel("kg")
    ax2.legend(loc="upper right")
    ax1.set_title(title or "Redispatch operation")
    return _save(fig, output_dir / filename)


def plot_redispatch_production_fulfilment(
    *,
    summary_row: pd.Series,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path:
    target = float(summary_row["target_hydrogen_kg"])
    sold = float(summary_row["hydrogen_compressed_or_sold_kg"])
    shortfall = float(summary_row["shortfall_kg"])
    above_target = float(summary_row.get("hydrogen_above_target_kg", max(sold - target, 0.0)))
    within_target = min(sold, target)
    labels = ["Target", "Within target", "Above target", "Shortfall"]
    values = [target, within_target, above_target, shortfall]
    colors = ["#6a3d9a", "#31a354", "#2b8cbe", "#d95f0e"]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(labels, values, color=colors)
    ax.set_ylabel("kg H2")
    ax.set_title(title or "Production fulfilment")
    return _save(fig, output_dir / filename)


def plot_submitted_bid_curves_for_hours(
    *,
    submitted_bids: pd.DataFrame,
    selected_hours: list[pd.Timestamp] | pd.DatetimeIndex,
    output_dir: Path,
    filename: str,
) -> Path:
    frame = submitted_bids.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    hours = [pd.Timestamp(pd.to_datetime(value, utc=True, errors="raise")) for value in selected_hours]
    selected = frame[frame["delivery_start_utc"].isin(hours)].copy()
    if selected.empty:
        raise ValueError("No submitted bid rows matched selected_hours.")

    unique_hours = sorted(selected["delivery_start_utc"].drop_duplicates().tolist())
    fig, axes = plt.subplots(len(unique_hours), 1, figsize=(10, 4 * len(unique_hours)), sharex=True)
    if len(unique_hours) == 1:
        axes = [axes]
    for ax, hour in zip(axes, unique_hours, strict=True):
        hour_frame = selected[selected["delivery_start_utc"] == hour].sort_values("bid_price_eur_per_mwh")
        cumulative = hour_frame["bid_quantity_mw"].cumsum()
        ax.step(hour_frame["bid_price_eur_per_mwh"], cumulative, where="post", color="#2b8cbe")
        ax.bar(
            hour_frame["bid_price_eur_per_mwh"].astype(str),
            hour_frame["bid_quantity_mw"],
            alpha=0.35,
            color="#31a354",
        )
        ax.set_ylabel("MW")
        ax.set_title(str(hour))
    axes[-1].set_xlabel("Bid price (EUR/MWh)")
    return _save(fig, output_dir / filename)


def plot_scenario_clearing_heatmap(
    *,
    scenario_clearing: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path:
    frame = scenario_clearing.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    frame["hour_label"] = frame["delivery_start_utc"].dt.strftime("%H:%M")
    pivot = (
        frame.groupby(["scenario_id", "hour_label"], as_index=False)["cleared_energy_mwh"]
        .sum()
        .pivot(index="scenario_id", columns="hour_label", values="cleared_energy_mwh")
        .fillna(0.0)
        .sort_index()
    )
    fig, ax = plt.subplots(figsize=(10, max(3.5, 1.4 * pivot.shape[0])))
    image = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="Blues")
    ax.set_xlabel("Delivery hour")
    ax.set_ylabel("Scenario")
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels(list(pivot.columns))
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(list(pivot.index))
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Cleared energy (MWh)")
    return _save(fig, output_dir / filename)


def plot_scenario_cleared_used_unused_energy(
    *,
    scenario_dispatch: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path:
    frame = scenario_dispatch.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    summary = (
        frame.groupby("scenario_id", as_index=False)
        .agg(
            cleared_energy_mwh=("cleared_energy_mwh", "sum"),
            used_energy_mwh=("used_energy_mwh", "sum"),
            unused_cleared_energy_mwh=("unused_cleared_energy_mwh", "sum"),
        )
        .sort_values("scenario_id")
        .reset_index(drop=True)
    )
    x = np.arange(summary.shape[0])
    width = 0.25
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - width, summary["cleared_energy_mwh"], width, label="Cleared", color="#2b8cbe")
    ax.bar(x, summary["used_energy_mwh"], width, label="Used", color="#31a354")
    ax.bar(x + width, summary["unused_cleared_energy_mwh"], width, label="Unused", color="#d95f0e")
    ax.set_xticks(x)
    ax.set_xticklabels(summary["scenario_id"])
    ax.set_ylabel("Energy (MWh)")
    ax.legend()
    return _save(fig, output_dir / filename)


def plot_scenario_storage_trajectories(
    *,
    scenario_dispatch: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path:
    frame = scenario_dispatch.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    fig, ax = plt.subplots(figsize=(12, 5))
    for scenario_id, group in frame.groupby("scenario_id", sort=True):
        group = group.sort_values("delivery_start_utc")
        ax.plot(group["delivery_start_utc"], group["H_buf_kg"], linewidth=1.8, label=str(scenario_id))
    ax.set_ylabel("Hydrogen storage (kg)")
    ax.set_xlabel("Delivery hour")
    ax.legend(title="Scenario")
    return _save(fig, output_dir / filename)


def plot_scenario_profit_distribution(
    *,
    scenario_economics: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path:
    frame = scenario_economics.sort_values("scenario_id").copy()
    x = np.arange(frame.shape[0])
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x, frame["adjusted_profit_eur"], color="#3182bd")
    ax.set_xticks(x)
    ax.set_xticklabels(
        [
            f"{row['scenario_id']}\npi={row['scenario_probability']:.2f}"
            for row in frame.to_dict(orient="records")
        ]
    )
    ax.set_ylabel("Adjusted profit (EUR)")
    ax.set_title("Scenario adjusted profit distribution")
    return _save(fig, output_dir / filename)


def plot_submitted_bid_curves_with_actual_overlays(
    *,
    submitted_bids: pd.DataFrame,
    actual_price_paths: pd.DataFrame,
    selected_hours: list[pd.Timestamp] | pd.DatetimeIndex,
    output_dir: Path,
    filename: str,
) -> Path:
    bids = submitted_bids.copy()
    bids["delivery_start_utc"] = pd.to_datetime(bids["delivery_start_utc"], utc=True, errors="raise")
    prices = actual_price_paths.copy()
    prices["delivery_start_utc"] = pd.to_datetime(prices["delivery_start_utc"], utc=True, errors="raise")
    hours = [pd.Timestamp(pd.to_datetime(value, utc=True, errors="raise")) for value in selected_hours]
    unique_hours = [hour for hour in hours if hour in set(bids["delivery_start_utc"])]
    if not unique_hours:
        raise ValueError("No selected_hours matched submitted bids.")

    fig, axes = plt.subplots(len(unique_hours), 1, figsize=(10, 4 * len(unique_hours)), sharex=True)
    if len(unique_hours) == 1:
        axes = [axes]
    colors = ["#2b8cbe", "#31a354", "#d95f0e"]
    for ax, hour in zip(axes, unique_hours, strict=True):
        hour_bids = bids[bids["delivery_start_utc"] == hour].sort_values("bid_price_eur_per_mwh")
        ax.step(hour_bids["bid_price_eur_per_mwh"], hour_bids["bid_quantity_mw"].cumsum(), where="post", color="#1f1f1f", linewidth=2)
        for color, (actual_path_id, group) in zip(colors, prices[prices["delivery_start_utc"] == hour].groupby("actual_path_id", sort=True), strict=False):
            ax.axvline(float(group["actual_price_eur_per_mwh"].iloc[0]), color=color, linestyle="--", linewidth=1.5, label=str(actual_path_id))
        ax.set_ylabel("Cumulative MW")
        ax.set_title(str(hour))
        ax.legend()
    axes[-1].set_xlabel("Bid price (EUR/MWh)")
    return _save(fig, output_dir / filename)


def plot_real_scenario_fan_vs_actual(
    *,
    scenario_period: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path:
    required = {
        "delivery_start_utc",
        "scenario_probability",
        "scenario_price_eur_per_mwh",
        "point_forecast_eur_per_mwh",
        "actual_price_eur_per_mwh",
    }
    missing = required.difference(scenario_period.columns)
    if missing:
        raise ValueError(f"scenario_period is missing required columns: {sorted(missing)}")
    q = _scenario_quantiles(scenario_period.copy())
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.fill_between(q["delivery_start_utc"], q["q05"], q["q95"], alpha=0.25, color="#9ecae1", label="Scenario p05-p95")
    ax.plot(q["delivery_start_utc"], q["q50"], color="#3182bd", linewidth=1.6, label="Scenario median")
    ax.plot(q["delivery_start_utc"], q["point"], color="#6a3d9a", linestyle="--", linewidth=1.4, label="Point forecast")
    ax.plot(q["delivery_start_utc"], q["actual"], color="#d95f0e", linewidth=1.8, label="Actual price")
    ax.set_ylabel("EUR/MWh")
    ax.set_xlabel("Delivery hour")
    ax.legend(loc="upper left")
    return _save(fig, output_dir / filename)


def plot_actual_clearing_heatmap(
    *,
    actual_clearing: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path:
    frame = actual_clearing.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    frame["hour_label"] = frame["delivery_start_utc"].dt.strftime("%H:%M")
    pivot = (
        frame.groupby(["actual_path_id", "hour_label"], as_index=False)["accepted"]
        .mean()
        .pivot(index="actual_path_id", columns="hour_label", values="accepted")
        .fillna(0.0)
        .sort_index()
    )
    fig, ax = plt.subplots(figsize=(10, max(3.5, 1.4 * pivot.shape[0])))
    image = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="Greens", vmin=0.0, vmax=1.0)
    ax.set_xlabel("Delivery hour")
    ax.set_ylabel("Actual price path")
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels(list(pivot.columns))
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(list(pivot.index))
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Accepted bid-block share")
    return _save(fig, output_dir / filename)


def plot_submitted_cleared_rejected_energy(
    *,
    actual_clearing_by_hour: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path:
    summary = (
        actual_clearing_by_hour.groupby("actual_path_id", as_index=False)
        .agg(
            submitted_energy_mwh=("submitted_energy_mwh", "sum"),
            cleared_energy_mwh=("cleared_energy_mwh", "sum"),
            rejected_energy_mwh=("rejected_energy_mwh", "sum"),
        )
        .sort_values("actual_path_id")
        .reset_index(drop=True)
    )
    x = np.arange(summary.shape[0])
    width = 0.25
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - width, summary["submitted_energy_mwh"], width, label="Submitted", color="#2b8cbe")
    ax.bar(x, summary["cleared_energy_mwh"], width, label="Cleared", color="#31a354")
    ax.bar(x + width, summary["rejected_energy_mwh"], width, label="Rejected", color="#d95f0e")
    ax.set_xticks(x)
    ax.set_xticklabels(summary["actual_path_id"])
    ax.set_ylabel("Energy (MWh)")
    ax.legend()
    return _save(fig, output_dir / filename)


def plot_actual_storage_trajectories(
    *,
    actual_redispatch_timeseries: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path:
    frame = actual_redispatch_timeseries.copy()
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    fig, ax = plt.subplots(figsize=(12, 5))
    for actual_path_id, group in frame.groupby("actual_path_id", sort=True):
        group = group.sort_values("delivery_start_utc")
        ax.plot(group["delivery_start_utc"], group["H_buf_kg"], linewidth=1.8, label=str(actual_path_id))
    ax.set_ylabel("Hydrogen storage (kg)")
    ax.set_xlabel("Delivery hour")
    ax.legend(title="Actual path")
    return _save(fig, output_dir / filename)


def plot_expected_vs_realised_profit_distribution(
    *,
    scenario_economics: pd.DataFrame,
    realised_summary: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path:
    expected = scenario_economics.sort_values("scenario_id").copy()
    x = np.arange(expected.shape[0])
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x, expected["adjusted_profit_eur"], color="#9ecae1", label="Scenario adjusted profit")
    for row in realised_summary.sort_values("actual_path_id").to_dict(orient="records"):
        ax.axhline(
            float(row["realised_adjusted_profit_after_actual_clearing"]),
            linestyle="--",
            linewidth=1.5,
            label=f"Realised {row['actual_path_id']}",
        )
    ax.set_xticks(x)
    ax.set_xticklabels(expected["scenario_id"])
    ax.set_ylabel("Profit (EUR)")
    ax.legend()
    return _save(fig, output_dir / filename)


def plot_realised_profit_comparison_bar(
    *,
    comparison: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if comparison.empty:
        return None
    frame = comparison.copy().sort_values("strategy_label").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(frame["strategy_label"], frame["realised_adjusted_profit_eur"], color=["#2b8cbe", "#31a354"][: len(frame)])
    ax.set_ylabel("Realised adjusted profit (EUR)")
    ax.set_title("Realised strategy comparison")
    ax.tick_params(axis="x", rotation=15)
    return _save(fig, output_dir / filename)


def plot_cvar_risk_return_frontier(
    *,
    sweep_summary: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if sweep_summary.empty:
        return None
    frame = sweep_summary.sort_values("cvar_gamma").copy()
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(frame["CVaR_loss"], frame["expected_adjusted_profit_eur"], marker="o", color="#2b8cbe")
    for row in frame.to_dict(orient="records"):
        ax.annotate(f"g={row['cvar_gamma']:.2f}", (row["CVaR_loss"], row["expected_adjusted_profit_eur"]), fontsize=8)
    ax.set_xlabel("CVaR loss (EUR)")
    ax.set_ylabel("Expected adjusted profit (EUR)")
    ax.set_title("Toy CVaR risk-return frontier")
    return _save(fig, output_dir / filename)


def plot_cvar_sweep_diagnostics(
    *,
    sweep_summary: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if sweep_summary.empty:
        return None
    frame = sweep_summary.sort_values("cvar_gamma").copy()
    fig, axes = plt.subplots(3, 1, figsize=(9, 10), sharex=True)
    axes[0].plot(frame["cvar_gamma"], frame["expected_adjusted_profit_eur"], marker="o", color="#2b8cbe")
    axes[0].set_ylabel("Expected profit")
    axes[1].plot(frame["cvar_gamma"], frame["CVaR_loss"], marker="o", color="#d95f0e")
    axes[1].set_ylabel("CVaR loss")
    axes[2].plot(frame["cvar_gamma"], frame["worst_scenario_profit"], marker="o", color="#31a354")
    axes[2].set_ylabel("Worst profit")
    axes[2].set_xlabel("Gamma")
    return _save(fig, output_dir / filename)


def plot_cvar_bid_firmness(
    *,
    sweep_summary: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if sweep_summary.empty:
        return None
    frame = sweep_summary.sort_values("cvar_gamma").copy()
    fig, axes = plt.subplots(2, 1, figsize=(9, 8), sharex=True)
    axes[0].plot(frame["cvar_gamma"], frame["high_bid_energy_share_ge_250"], marker="o", color="#6a3d9a", label="Share >= 250")
    axes[0].plot(frame["cvar_gamma"], frame["high_bid_energy_share_ge_3000"], marker="s", color="#d95f0e", label="Share >= 3000")
    axes[0].set_ylabel("High-bid share")
    axes[0].legend()
    axes[1].plot(frame["cvar_gamma"], frame["weighted_average_bid_price_eur_per_mwh"], marker="o", color="#2b8cbe")
    axes[1].set_ylabel("Weighted avg bid price")
    axes[1].set_xlabel("Gamma")
    return _save(fig, output_dir / filename)


def plot_cvar_scenario_profit_by_gamma(
    *,
    scenario_results: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if scenario_results.empty:
        return None
    frame = scenario_results.copy()
    pivot = (
        frame.pivot_table(
            index="cvar_gamma",
            columns="scenario_id",
            values="adjusted_profit_eur",
            aggfunc="first",
        )
        .sort_index()
        .sort_index(axis=1)
    )
    fig, ax = plt.subplots(figsize=(10, 5))
    for scenario_id in pivot.columns:
        ax.plot(pivot.index, pivot[scenario_id], marker="o", label=str(scenario_id))
    ax.set_xlabel("Gamma")
    ax.set_ylabel("Scenario adjusted profit (EUR)")
    ax.legend(title="Scenario")
    return _save(fig, output_dir / filename)


def plot_cvar_realised_profit_comparison(
    *,
    backtest_results: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if backtest_results.empty:
        return None
    frame = backtest_results.copy()
    pivot = (
        frame.pivot_table(
            index="cvar_gamma",
            columns="actual_path_id",
            values="realised_adjusted_profit_after_actual_clearing",
            aggfunc="first",
        )
        .sort_index()
        .sort_index(axis=1)
    )
    fig, ax = plt.subplots(figsize=(10, 5))
    for actual_path_id in pivot.columns:
        ax.plot(pivot.index, pivot[actual_path_id], marker="o", label=str(actual_path_id))
    ax.set_xlabel("Gamma")
    ax.set_ylabel("Realised adjusted profit (EUR)")
    ax.legend(title="Actual path")
    return _save(fig, output_dir / filename)


def plot_cvar_cleared_used_unused_by_gamma(
    *,
    sweep_summary: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if sweep_summary.empty:
        return None
    frame = sweep_summary.sort_values("cvar_gamma").copy()
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(frame["cvar_gamma"], frame["expected_cleared_energy_mwh"], marker="o", color="#2b8cbe", label="Expected cleared")
    ax.plot(frame["cvar_gamma"], frame["expected_used_energy_mwh"], marker="o", color="#31a354", label="Expected used")
    ax.plot(frame["cvar_gamma"], frame["expected_unused_cleared_energy_mwh"], marker="o", color="#d95f0e", label="Expected unused")
    ax.set_xlabel("Gamma")
    ax.set_ylabel("Energy (MWh)")
    ax.legend()
    return _save(fig, output_dir / filename)


def _suite_origin_labels(frame: pd.DataFrame) -> list[str]:
    return [
        f"{row['artifact_short']}\n{row['delivery_day']}\n{row['selection_reason_short']}"
        for row in frame.to_dict(orient="records")
    ]


def plot_suite_realised_profit_by_origin(
    *,
    metrics_by_origin: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if metrics_by_origin.empty:
        return None
    frame = metrics_by_origin.copy().sort_values(["artifact_id", "forecast_origin_utc"]).reset_index(drop=True)
    frame["artifact_short"] = frame["artifact_id"].astype(str).str.replace("_integration_candidate", "", regex=False)
    frame["selection_reason_short"] = frame["selection_reason"].astype(str).str.replace("_", "\n", regex=False)
    labels = _suite_origin_labels(frame)
    x = np.arange(frame.shape[0])
    width = 0.35
    fig, ax = plt.subplots(figsize=(max(10, frame.shape[0] * 1.8), 5))
    ax.bar(x - width / 2, frame["realised_adjusted_profit_eur"], width, label="Stochastic", color="#2b8cbe")
    ax.bar(x + width / 2, frame["benchmark_realised_adjusted_profit_eur"], width, label="Benchmark", color="#31a354")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Realised adjusted profit (EUR)")
    ax.legend()
    return _save(fig, output_dir / filename)


def plot_suite_profit_delta_by_origin(
    *,
    metrics_by_origin: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if metrics_by_origin.empty:
        return None
    frame = metrics_by_origin.copy().sort_values(["artifact_id", "forecast_origin_utc"]).reset_index(drop=True)
    frame["artifact_short"] = frame["artifact_id"].astype(str).str.replace("_integration_candidate", "", regex=False)
    frame["selection_reason_short"] = frame["selection_reason"].astype(str).str.replace("_", "\n", regex=False)
    labels = _suite_origin_labels(frame)
    x = np.arange(frame.shape[0])
    colors = ["#31a354" if value >= 0.0 else "#d95f0e" for value in frame["stochastic_minus_benchmark_profit"]]
    fig, ax = plt.subplots(figsize=(max(10, frame.shape[0] * 1.8), 5))
    ax.bar(x, frame["stochastic_minus_benchmark_profit"], color=colors)
    ax.axhline(0.0, color="#1f1f1f", linewidth=1.0)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Stochastic - benchmark profit (EUR)")
    return _save(fig, output_dir / filename)


def plot_suite_clearing_ratio_by_origin(
    *,
    metrics_by_origin: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if metrics_by_origin.empty:
        return None
    frame = metrics_by_origin.copy().sort_values(["artifact_id", "forecast_origin_utc"]).reset_index(drop=True)
    frame["artifact_short"] = frame["artifact_id"].astype(str).str.replace("_integration_candidate", "", regex=False)
    frame["selection_reason_short"] = frame["selection_reason"].astype(str).str.replace("_", "\n", regex=False)
    labels = _suite_origin_labels(frame)
    x = np.arange(frame.shape[0])
    fig, ax = plt.subplots(figsize=(max(10, frame.shape[0] * 1.8), 5))
    ax.bar(x, frame["clearing_ratio"], color="#2b8cbe")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Clearing ratio")
    ax.set_ylim(0.0, 1.05)
    return _save(fig, output_dir / filename)


def plot_suite_hydrogen_and_shortfall_by_origin(
    *,
    metrics_by_origin: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if metrics_by_origin.empty:
        return None
    frame = metrics_by_origin.copy().sort_values(["artifact_id", "forecast_origin_utc"]).reset_index(drop=True)
    frame["artifact_short"] = frame["artifact_id"].astype(str).str.replace("_integration_candidate", "", regex=False)
    frame["selection_reason_short"] = frame["selection_reason"].astype(str).str.replace("_", "\n", regex=False)
    labels = _suite_origin_labels(frame)
    x = np.arange(frame.shape[0])
    fig, axes = plt.subplots(2, 1, figsize=(max(10, frame.shape[0] * 1.8), 8), sharex=True)
    axes[0].bar(x, frame["hydrogen_sold_or_compressed_kg"], color="#31a354")
    axes[0].set_ylabel("Hydrogen sold (kg)")
    axes[1].bar(x, frame["shortfall_kg"], color="#d95f0e")
    axes[1].set_ylabel("Shortfall (kg)")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels)
    return _save(fig, output_dir / filename)


def plot_suite_average_actual_price_paid_by_origin(
    *,
    metrics_by_origin: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if metrics_by_origin.empty:
        return None
    frame = metrics_by_origin.copy().sort_values(["artifact_id", "forecast_origin_utc"]).reset_index(drop=True)
    frame["artifact_short"] = frame["artifact_id"].astype(str).str.replace("_integration_candidate", "", regex=False)
    frame["selection_reason_short"] = frame["selection_reason"].astype(str).str.replace("_", "\n", regex=False)
    labels = _suite_origin_labels(frame)
    x = np.arange(frame.shape[0])
    width = 0.35
    fig, ax = plt.subplots(figsize=(max(10, frame.shape[0] * 1.8), 5))
    ax.bar(x - width / 2, frame["weighted_average_actual_price_paid_for_cleared_energy"], width, label="Stochastic", color="#2b8cbe")
    ax.bar(x + width / 2, frame["benchmark_average_actual_price_paid_eur_per_mwh"], width, label="Benchmark", color="#31a354")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Average actual price paid (EUR/MWh)")
    ax.legend()
    return _save(fig, output_dir / filename)


def plot_suite_price_spread_vs_profit_delta(
    *,
    metrics_by_origin: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if metrics_by_origin.empty:
        return None
    frame = metrics_by_origin.copy()
    fig, ax = plt.subplots(figsize=(8, 5))
    for artifact_id, group in frame.groupby("artifact_id", sort=True):
        ax.scatter(group["actual_price_spread"], group["stochastic_minus_benchmark_profit"], label=str(artifact_id))
    ax.axhline(0.0, color="#1f1f1f", linewidth=1.0)
    ax.set_xlabel("Actual daily price spread (EUR/MWh)")
    ax.set_ylabel("Stochastic - benchmark profit (EUR)")
    ax.legend()
    return _save(fig, output_dir / filename)


def plot_bid_ladder_actual_price_day(
    *,
    actual_clearing: pd.DataFrame,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path | None:
    frame = actual_clearing.copy()
    if frame.empty:
        return None
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    hour_meta = (
        frame.groupby("delivery_start_utc", as_index=False)
        .agg(actual_price_eur_per_mwh=("actual_price_eur_per_mwh", "first"))
        .sort_values("actual_price_eur_per_mwh")
    )
    selected_hours = []
    if not hour_meta.empty:
        selected_hours.append(pd.Timestamp(hour_meta.iloc[0]["delivery_start_utc"]))
        selected_hours.append(pd.Timestamp(hour_meta.iloc[len(hour_meta) // 2]["delivery_start_utc"]))
        selected_hours.append(pd.Timestamp(hour_meta.iloc[-1]["delivery_start_utc"]))
    selected_hours = list(dict.fromkeys(selected_hours))
    if not selected_hours:
        return None

    fig, axes = plt.subplots(len(selected_hours), 1, figsize=(9, 3.8 * len(selected_hours)))
    if len(selected_hours) == 1:
        axes = [axes]
    for ax, ts in zip(axes, selected_hours, strict=True):
        hour_frame = frame.loc[frame["delivery_start_utc"] == ts].sort_values("bid_price_eur_per_mwh").copy()
        hour_frame["cum_qty"] = hour_frame["bid_quantity_mw"].cumsum()
        hour_frame["prev_cum_qty"] = hour_frame["cum_qty"].shift(fill_value=0.0)
        actual_price = float(hour_frame["actual_price_eur_per_mwh"].iloc[0])
        for row in hour_frame.to_dict(orient="records"):
            color = "#2ca25f" if bool(row["accepted"]) and float(row["bid_quantity_mw"]) > 1e-12 else "#de2d26"
            ax.hlines(
                y=float(row["bid_price_eur_per_mwh"]),
                xmin=float(row["prev_cum_qty"]),
                xmax=float(row["cum_qty"]),
                colors=color,
                linewidth=3.0,
            )
        cleared_mw = float(hour_frame["cleared_quantity_mw"].sum())
        rejected_mw = float(hour_frame["bid_quantity_mw"].sum() - cleared_mw)
        ax.axhline(actual_price, color="#252525", linestyle="--", linewidth=1.4)
        ax.annotate(
            f"cleared={cleared_mw:.1f} MW\nrejected={rejected_mw:.1f} MW",
            xy=(0.98, 0.04),
            xycoords="axes fraction",
            ha="right",
            va="bottom",
            fontsize=8,
        )
        ax.set_ylabel("EUR/MWh")
        ax.set_title(pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M UTC"))
    axes[-1].set_xlabel("Cumulative bid quantity (MW)")
    fig.suptitle(title or "Bid ladder versus actual DA price", y=0.995)
    return _save(fig, output_dir / filename)


def plot_bid_ladder_heatmap_day(
    *,
    actual_clearing: pd.DataFrame,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path | None:
    frame = actual_clearing.copy()
    if frame.empty:
        return None
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    price_levels = sorted(frame["bid_price_eur_per_mwh"].astype(float).unique().tolist())
    hour_labels = sorted(frame["delivery_start_utc"].drop_duplicates().tolist())
    quantity = frame.pivot_table(
        index="bid_price_eur_per_mwh",
        columns="delivery_start_utc",
        values="bid_quantity_mw",
        aggfunc="sum",
        fill_value=0.0,
    ).reindex(index=price_levels, columns=hour_labels, fill_value=0.0)
    accepted = frame.pivot_table(
        index="bid_price_eur_per_mwh",
        columns="delivery_start_utc",
        values="accepted",
        aggfunc="max",
        fill_value=False,
    ).reindex(index=price_levels, columns=hour_labels, fill_value=False)
    actual_prices = (
        frame.groupby("delivery_start_utc", as_index=False)["actual_price_eur_per_mwh"]
        .first()
        .set_index("delivery_start_utc")
        .reindex(hour_labels)
    )
    fig, (ax_heat, ax_price) = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={"height_ratios": [4, 1]}, sharex=True)
    image = ax_heat.imshow(quantity.to_numpy(), aspect="auto", origin="lower", cmap="Blues")
    for row_idx in range(accepted.shape[0]):
        for col_idx in range(accepted.shape[1]):
            marker = "o" if bool(accepted.iat[row_idx, col_idx]) else "x"
            color = "#2ca25f" if bool(accepted.iat[row_idx, col_idx]) else "#de2d26"
            ax_heat.scatter(col_idx, row_idx, marker=marker, s=18, color=color)
    ax_heat.set_ylabel("Bid price block")
    ax_heat.set_yticks(range(len(price_levels)))
    ax_heat.set_yticklabels([f"{value:.0f}" for value in price_levels])
    fig.colorbar(image, ax=ax_heat, label="Submitted quantity (MW)")
    ax_heat.set_title(title or "Hourly bid ladder heatmap")
    ax_price.plot(range(len(hour_labels)), actual_prices["actual_price_eur_per_mwh"].astype(float).to_numpy(), color="#252525", linewidth=1.8)
    ax_price.set_ylabel("EUR/MWh")
    ax_price.set_xticks(range(len(hour_labels)))
    ax_price.set_xticklabels([pd.Timestamp(ts).strftime("%H:%M") for ts in hour_labels], rotation=45, ha="right")
    ax_price.set_xlabel("Delivery hour")
    return _save(fig, output_dir / filename)


def plot_submitted_cleared_rejected_day(
    *,
    actual_clearing_by_hour: pd.DataFrame,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path | None:
    frame = actual_clearing_by_hour.sort_values("delivery_start_utc").copy()
    if frame.empty:
        return None
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    x = np.arange(frame.shape[0])
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.bar(x, frame["cleared_energy_mwh"], color="#2ca25f", label="Cleared energy")
    ax1.bar(x, frame["rejected_energy_mwh"], bottom=frame["cleared_energy_mwh"], color="#de2d26", label="Rejected energy")
    ax1.set_ylabel("MWh")
    ax1.legend(loc="upper left")
    ax2 = ax1.twinx()
    ax2.plot(x, frame["actual_price_eur_per_mwh"], color="#252525", linewidth=1.8, label="Actual DA price")
    if "weighted_average_bid_price_eur_per_mwh" in frame.columns:
        ax2.plot(x, frame["weighted_average_bid_price_eur_per_mwh"], color="#756bb1", linewidth=1.2, linestyle="--", label="Weighted avg bid price")
    ax2.set_ylabel("EUR/MWh")
    ax2.legend(loc="upper right")
    ax1.set_xticks(x)
    ax1.set_xticklabels(frame["delivery_start_utc"].dt.strftime("%H:%M"), rotation=45, ha="right")
    ax1.set_title(title or "Submitted, cleared, and rejected electricity")
    return _save(fig, output_dir / filename)


def plot_cleared_used_unused_day(
    *,
    redispatch: pd.DataFrame,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path | None:
    frame = redispatch.sort_values("delivery_start_utc").copy()
    if frame.empty:
        return None
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    x = np.arange(frame.shape[0])
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.bar(x, frame["used_energy_mwh"], color="#2ca25f", label="Used cleared energy")
    ax1.bar(x, frame["unused_cleared_energy_mwh"], bottom=frame["used_energy_mwh"], color="#fd8d3c", label="Unused cleared energy")
    ax1.plot(x, frame["cleared_energy_mwh"], color="#3182bd", linewidth=1.4, label="Cleared energy")
    ax1.set_ylabel("MWh")
    ax1.legend(loc="upper left")
    ax2 = ax1.twinx()
    ax2.plot(x, frame["actual_price_eur_per_mwh"], color="#252525", linewidth=1.8, label="Actual DA price")
    ax2.set_ylabel("EUR/MWh")
    ax2.legend(loc="upper right")
    ax1.set_xticks(x)
    ax1.set_xticklabels(frame["delivery_start_utc"].dt.strftime("%H:%M"), rotation=45, ha="right")
    ax1.set_title(title or "Cleared, used, and unused electricity")
    return _save(fig, output_dir / filename)


def plot_asset_operation_day(
    *,
    redispatch: pd.DataFrame,
    reserve_kg: float,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path | None:
    frame = redispatch.sort_values("delivery_start_utc").copy()
    if frame.empty:
        return None
    frame["delivery_start_utc"] = pd.to_datetime(frame["delivery_start_utc"], utc=True, errors="raise")
    x = np.arange(frame.shape[0])
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    axes[0].plot(x, frame["actual_price_eur_per_mwh"], color="#252525", linewidth=1.8)
    axes[0].set_ylabel("EUR/MWh")
    axes[0].set_title(title or "Asset operation")
    axes[1].step(x, frame["P_el_mw"], where="mid", color="#3182bd", label="Electrolyser MW")
    axes[1].step(x, frame["P_comp_mw"], where="mid", color="#de2d26", label="Compressor MW")
    axes[1].set_ylabel("MW")
    axes[1].legend(loc="upper right")
    axes[2].plot(x, frame["H_buf_kg"], color="#31a354", linewidth=1.8, label="Hydrogen storage")
    axes[2].axhline(reserve_kg, color="#756bb1", linestyle="--", linewidth=1.2, label="Reserve")
    shortfall = float(frame["shortfall_kg"].iloc[0]) if "shortfall_kg" in frame.columns else 0.0
    if shortfall > 1e-9:
        axes[2].scatter(x[-1], frame["H_buf_kg"].iloc[-1], color="#de2d26", s=40, label=f"Shortfall {shortfall:.1f} kg")
    axes[2].set_ylabel("kg")
    axes[2].legend(loc="upper right")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels(frame["delivery_start_utc"].dt.strftime("%H:%M"), rotation=45, ha="right")
    return _save(fig, output_dir / filename)


def plot_target_mode_comparison(
    *,
    weekly_metrics: pd.DataFrame,
    output_dir: Path,
    filename: str,
    title: str | None = None,
) -> Path | None:
    frame = weekly_metrics.copy()
    if frame.empty:
        return None
    metrics = [
        ("realised_adjusted_profit", "Realised profit"),
        ("shortfall_kg", "Shortfall"),
        ("cvar_tail_profit", "CVaR tail profit"),
        ("rejected_energy_mwh", "Rejected energy"),
        ("unused_cleared_energy_mwh", "Unused energy"),
    ]
    fig, axes = plt.subplots(len(metrics), 1, figsize=(8.5, 2.5 * len(metrics)), sharex=True)
    x = np.arange(frame.shape[0])
    for ax, (column, ylabel) in zip(axes, metrics, strict=True):
        ax.bar(x, frame[column].astype(float), color="#3182bd")
        ax.set_ylabel(ylabel)
    axes[0].set_title(title or "Target-mode comparison")
    axes[-1].set_xticks(x)
    axes[-1].set_xticklabels(frame["target_mode"].astype(str), rotation=20, ha="right")
    return _save(fig, output_dir / filename)


def plot_runtime_by_target_mode(
    *,
    runtime_diagnostics: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    frame = runtime_diagnostics.loc[runtime_diagnostics["solve_stage"].astype(str) == "stochastic_bidding"].copy()
    if frame.empty:
        return None
    agg = frame.groupby("target_mode", as_index=False)["wall_time_seconds"].mean().sort_values("target_mode")
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(agg["target_mode"], agg["wall_time_seconds"], color="#3182bd")
    ax.set_ylabel("Mean wall time (s)")
    ax.set_title("Mean stochastic bidding runtime by target mode")
    ax.tick_params(axis="x", rotation=20)
    return _save(fig, output_dir / filename)


def plot_runtime_by_model_gamma(
    *,
    runtime_diagnostics: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    frame = runtime_diagnostics.loc[runtime_diagnostics["solve_stage"].astype(str) == "stochastic_bidding"].copy()
    if frame.empty:
        return None
    frame["model_gamma"] = frame["model_label"].astype(str) + " | g=" + frame["gamma"].astype(str)
    agg = frame.groupby("model_gamma", as_index=False)["wall_time_seconds"].mean().sort_values("wall_time_seconds", ascending=False)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.barh(agg["model_gamma"], agg["wall_time_seconds"], color="#31a354")
    ax.set_xlabel("Mean wall time (s)")
    ax.set_title("Mean stochastic bidding runtime by model and gamma")
    return _save(fig, output_dir / filename)


def plot_runtime_vs_binary_count(
    *,
    runtime_diagnostics: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    frame = runtime_diagnostics.loc[runtime_diagnostics["solve_stage"].astype(str) == "stochastic_bidding"].copy()
    if frame.empty:
        return None
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(frame["binary_variable_count"], frame["wall_time_seconds"], color="#756bb1", alpha=0.8)
    ax.set_xlabel("Binary variable count")
    ax.set_ylabel("Wall time (s)")
    ax.set_title("Runtime versus binary-variable count")
    return _save(fig, output_dir / filename)


def plot_runtime_stage_breakdown(
    *,
    runtime_diagnostics: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    if runtime_diagnostics.empty:
        return None
    agg = runtime_diagnostics.groupby("solve_stage", as_index=False)["wall_time_seconds"].sum().sort_values("wall_time_seconds", ascending=False)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(agg["solve_stage"], agg["wall_time_seconds"], color="#9ecae1")
    ax.set_ylabel("Total wall time (s)")
    ax.set_title("Runtime stage breakdown")
    ax.tick_params(axis="x", rotation=20)
    return _save(fig, output_dir / filename)


def plot_top_slowest_solves(
    *,
    runtime_diagnostics: pd.DataFrame,
    output_dir: Path,
    filename: str,
) -> Path | None:
    frame = runtime_diagnostics.sort_values("wall_time_seconds", ascending=False).head(10).copy()
    if frame.empty:
        return None
    frame["label"] = (
        frame["delivery_date"].astype(str)
        + " | "
        + frame["model_label"].astype(str)
        + " | g="
        + frame["gamma"].astype(str)
        + " | "
        + frame["target_mode"].astype(str)
        + " | "
        + frame["solve_stage"].astype(str)
    )
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.barh(frame["label"], frame["wall_time_seconds"], color="#de2d26")
    ax.set_xlabel("Wall time (s)")
    ax.set_title("Top slowest solves")
    return _save(fig, output_dir / filename)
