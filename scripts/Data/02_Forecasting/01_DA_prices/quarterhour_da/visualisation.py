"""Create separate Strict LEAR hourly-anchor / quarter-hour-shape figures."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[5]
FINALISATION_ROOT = REPO_ROOT / (
    "data/02_Forecasting/01_DA_prices/scenario_evaluation/"
    "strict_lear_dplus4_finalisation/20260729_strict_lear_dplus4_full_a03"
)
HOURLY_PRICES = REPO_ROOT / "data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv"
OBSERVED_DAY = "2026-05-18"
SIMILAR_OBSERVED_DAY = "2026-05-17"
COUNTERFACTUAL_DAY = "2025-05-18"

COLORS = {
    "actual": "#252525",
    "anchor": "#d55e00",
    "qh_forecast": "#1b7f83",
    "counterfactual": "#225ea8",
    "grid": "#d9d9d9",
}


def _local_day(timestamp: pd.Series) -> pd.Series:
    return pd.to_datetime(timestamp, utc=True).dt.tz_convert("Europe/Amsterdam").dt.date.astype(str)


def _load_observed_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    qh = pd.read_parquet(FINALISATION_ROOT / "optimisation_inputs/quarterhour_point_forecasts.parquet")
    hourly = pd.read_parquet(FINALISATION_ROOT / "optimisation_inputs/hourly_point_forecasts.parquet")
    actuals = pd.read_parquet(FINALISATION_ROOT / "evaluation_actuals.parquet")

    qh = qh[qh["lead_day"].eq(0)].copy()
    hourly = hourly[hourly["lead_day"].eq(0)].copy()
    actuals = actuals[actuals["granularity"].eq("quarterhour") & actuals["lead_day"].eq(0)].copy()
    for frame in (qh, hourly, actuals):
        frame["forecast_origin_utc"] = pd.to_datetime(frame["forecast_origin_utc"], utc=True)
        frame["target_timestamp_utc"] = pd.to_datetime(frame["target_timestamp_utc"], utc=True)

    qh["delivery_local_day"] = _local_day(qh["target_timestamp_utc"])
    qh = qh[qh["delivery_local_day"].eq(OBSERVED_DAY)].copy()
    origin = qh["forecast_origin_utc"].iloc[0]
    qh = qh[qh["forecast_origin_utc"].eq(origin)].copy()
    actuals = actuals[actuals["forecast_origin_utc"].eq(origin)].copy()
    hourly = hourly[hourly["forecast_origin_utc"].eq(origin)].copy()

    qh = qh.merge(
        actuals[["target_timestamp_utc", "actual_price"]], on="target_timestamp_utc", how="inner", validate="one_to_one"
    ).sort_values("target_timestamp_utc")
    hourly["delivery_local_day"] = _local_day(hourly["target_timestamp_utc"])
    hourly = hourly[hourly["delivery_local_day"].eq(OBSERVED_DAY)].sort_values("target_timestamp_utc")
    if len(qh) != 96 or len(hourly) != 24:
        raise ValueError("Observed panel requires one complete 24-hour delivery day.")
    return qh, hourly


def _observed_shape_library(qh: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    all_qh = pd.read_parquet(FINALISATION_ROOT / "evaluation_actuals.parquet")
    all_qh = all_qh[all_qh["granularity"].eq("quarterhour") & all_qh["lead_day"].eq(0)].copy()
    all_qh["target_timestamp_utc"] = pd.to_datetime(all_qh["target_timestamp_utc"], utc=True)
    all_qh["hour_start_utc"] = all_qh["target_timestamp_utc"].dt.floor("h")
    all_qh["local_timestamp"] = all_qh["target_timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    all_qh["local_hour"] = all_qh["local_timestamp"].dt.hour
    all_qh["weekend"] = (all_qh["local_timestamp"].dt.dayofweek >= 5).astype(int)
    all_qh["quarter_index"] = (all_qh["local_timestamp"].dt.minute // 15 + 1).astype(int)
    all_qh["hourly_mean"] = all_qh.groupby("hour_start_utc")["actual_price"].transform("mean")
    all_qh["delta"] = all_qh["actual_price"] - all_qh["hourly_mean"]
    all_qh["local_day"] = all_qh["local_timestamp"].dt.date.astype(str)
    library = all_qh[~all_qh["local_day"].eq(OBSERVED_DAY)].pivot_table(
        index=["hour_start_utc", "local_hour", "weekend"], columns="quarter_index", values="delta", aggfunc="first"
    ).dropna().reset_index()
    if library.empty:
        raise ValueError("No observed quarter-hour shape blocks available.")
    return library


def _load_similar_hourly_forecast() -> pd.DataFrame:
    hourly = pd.read_parquet(FINALISATION_ROOT / "optimisation_inputs/hourly_point_forecasts.parquet")
    hourly = hourly[hourly["lead_day"].eq(0)].copy()
    hourly["forecast_origin_utc"] = pd.to_datetime(hourly["forecast_origin_utc"], utc=True)
    hourly["target_timestamp_utc"] = pd.to_datetime(hourly["target_timestamp_utc"], utc=True)
    hourly["delivery_local_day"] = _local_day(hourly["target_timestamp_utc"])
    hourly = hourly[hourly["delivery_local_day"].eq(SIMILAR_OBSERVED_DAY)].copy()
    origin = hourly["forecast_origin_utc"].iloc[0]
    hourly = hourly[hourly["forecast_origin_utc"].eq(origin)].copy()

    actuals = pd.read_parquet(FINALISATION_ROOT / "evaluation_actuals.parquet")
    actuals = actuals[actuals["granularity"].eq("hourly") & actuals["lead_day"].eq(0)].copy()
    actuals["forecast_origin_utc"] = pd.to_datetime(actuals["forecast_origin_utc"], utc=True)
    actuals["target_timestamp_utc"] = pd.to_datetime(actuals["target_timestamp_utc"], utc=True)
    actuals = actuals[actuals["forecast_origin_utc"].eq(origin)].copy()
    actuals["delivery_local_day"] = _local_day(actuals["target_timestamp_utc"])
    actuals = actuals[actuals["delivery_local_day"].eq(SIMILAR_OBSERVED_DAY)].copy()

    merged = hourly.merge(
        actuals[["target_timestamp_utc", "actual_price"]], on="target_timestamp_utc", how="inner", validate="one_to_one"
    )
    merged["local_hour"] = merged["target_timestamp_utc"].dt.tz_convert("Europe/Amsterdam").dt.hour
    merged["forecast_error"] = merged["point_forecast"] - merged["actual_price"]
    if len(merged) != 24:
        raise ValueError("The selected similar observed day requires 24 hourly forecasts and actuals.")
    return merged[["local_hour", "forecast_error"]].sort_values("local_hour")


def _load_counterfactual_panel(library: pd.DataFrame, similar_hourly_forecast: pd.DataFrame) -> pd.DataFrame:
    hourly = pd.read_csv(HOURLY_PRICES, usecols=["region", "timestamp_utc", "price_eur_per_mwh"])
    hourly = hourly[hourly["region"].eq("NL")].copy()
    hourly["timestamp_utc"] = pd.to_datetime(hourly["timestamp_utc"], utc=True)
    hourly["local_timestamp"] = hourly["timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    hourly = hourly[hourly["local_timestamp"].dt.date.astype(str).eq(COUNTERFACTUAL_DAY)].sort_values("timestamp_utc")
    if len(hourly) != 24:
        raise ValueError("Counterfactual panel requires one complete 24-hour historical hourly day.")
    error_by_hour = similar_hourly_forecast.set_index("local_hour")["forecast_error"].to_dict()

    rng = np.random.default_rng(20260518)
    rows: list[dict[str, object]] = []
    for hour in hourly.itertuples(index=False):
        local_hour = int(hour.local_timestamp.hour)
        weekend = int(hour.local_timestamp.dayofweek >= 5)
        hourly_forecast = float(hour.price_eur_per_mwh + error_by_hour[local_hour])
        pool = library[(library["local_hour"].eq(local_hour)) & (library["weekend"].eq(weekend))]
        if pool.empty:
            pool = library[library["local_hour"].eq(local_hour)]
        sampled = pool.iloc[int(rng.integers(0, len(pool)))]
        deltas = np.asarray([sampled[1], sampled[2], sampled[3], sampled[4]], dtype=float)
        deltas -= deltas.mean()
        for quarter, delta in enumerate(deltas):
            rows.append(
                {
                    "timestamp": hour.timestamp_utc + pd.Timedelta(minutes=15 * quarter),
                    "counterfactual_price": float(hourly_forecast + delta),
                    "actual_hourly_price": float(hour.price_eur_per_mwh),
                    "hourly_forecast": hourly_forecast,
                }
            )
    return pd.DataFrame(rows)


def _style_axis(axis: plt.Axes) -> None:
    axis.grid(axis="y", color=COLORS["grid"], linewidth=0.7, alpha=0.8)
    axis.grid(axis="x", color=COLORS["grid"], linewidth=0.5, alpha=0.45)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color("#555555")
    axis.tick_params(colors="#303030", labelsize=10)
    axis.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz="Europe/Amsterdam"))


def _save(fig: plt.Figure, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=300, bbox_inches="tight", pad_inches=0.12)
    fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)


def build_observed_figure(observed_qh: pd.DataFrame, observed_hourly: pd.DataFrame, output: Path) -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.labelsize": 12})
    fig, axis = plt.subplots(figsize=(12.5, 4.5), layout="constrained")

    observed_time = observed_qh["target_timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    observed_hour_time = observed_hourly["target_timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    axis.plot(observed_time, observed_qh["actual_price"], color=COLORS["actual"], linewidth=2.1, label="Observed 15-min DA price")
    axis.step(observed_hour_time, observed_hourly["point_forecast"], where="post", color=COLORS["anchor"], linewidth=1.8, label="Hourly Strict LEAR forecast")
    axis.plot(observed_time, observed_qh["point_forecast"], color=COLORS["qh_forecast"], linewidth=1.65, label="Quarter-hour forecast")
    _style_axis(axis)
    axis.set_ylabel("Day-ahead electricity price (EUR/MWh)")
    axis.set_xlabel("Delivery time (Europe/Amsterdam)")
    axis.set_xlim(observed_time.iloc[0], observed_time.iloc[-1])
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, 1.13), ncol=3, frameon=False, handlelength=2.8, columnspacing=1.8)
    _save(fig, output)


def build_counterfactual_figure(counterfactual: pd.DataFrame, output: Path) -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.labelsize": 12})
    fig, axis = plt.subplots(figsize=(12.5, 4.5), layout="constrained")
    counter_time = counterfactual["timestamp"].dt.tz_convert("Europe/Amsterdam")
    hour_time = pd.date_range(counter_time.iloc[0], periods=24, freq="h")
    hour_values = counterfactual.groupby(counterfactual["timestamp"].dt.floor("h"))["actual_hourly_price"].first().to_numpy()
    forecast_values = counterfactual.groupby(counterfactual["timestamp"].dt.floor("h"))["hourly_forecast"].first().to_numpy()
    axis.step(hour_time, hour_values, where="post", color=COLORS["actual"], linewidth=2.0, label="Observed hourly DA price")
    axis.step(
        hour_time,
        forecast_values,
        where="post",
        color=COLORS["anchor"],
        linewidth=1.8,
        label="Similar-day Strict LEAR forecast",
    )
    axis.plot(counter_time, counterfactual["counterfactual_price"], color=COLORS["counterfactual"], linewidth=1.75, label="Counterfactual 15-min DA path")
    _style_axis(axis)
    axis.set_ylabel("Day-ahead electricity price (EUR/MWh)")
    axis.set_xlabel("Delivery time (Europe/Amsterdam)")
    axis.set_xlim(counter_time.iloc[0], counter_time.iloc[-1])
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, 1.13), ncol=3, frameon=False, handlelength=2.8, columnspacing=1.8)
    _save(fig, output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=FINALISATION_ROOT / "thesis_figures",
    )
    args = parser.parse_args()
    observed_qh, observed_hourly = _load_observed_panel()
    similar_hourly_forecast = _load_similar_hourly_forecast()
    counterfactual = _load_counterfactual_panel(
        _observed_shape_library(observed_qh, observed_hourly),
        similar_hourly_forecast,
    )
    build_observed_figure(observed_qh, observed_hourly, args.output_dir / "strict_lear_hourly_anchor_qh_forecast.png")
    build_counterfactual_figure(counterfactual, args.output_dir / "strict_lear_counterfactual_qh_path.png")


if __name__ == "__main__":
    main()
