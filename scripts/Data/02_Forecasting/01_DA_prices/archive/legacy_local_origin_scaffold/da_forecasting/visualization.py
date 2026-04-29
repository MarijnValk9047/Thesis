from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .config import ForecastSetup


@dataclass(frozen=True)
class PeriodSelection:
    label: str
    mae: float
    observations: int
    start_utc: pd.Timestamp
    end_utc: pd.Timestamp

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "mae": self.mae,
            "observations": self.observations,
            "start_utc": self.start_utc.isoformat(),
            "end_utc": self.end_utc.isoformat(),
        }


def canonical_forecast_track(predictions: pd.DataFrame, split_name: str, model_name: str) -> pd.DataFrame:
    subset = predictions[(predictions["split"] == split_name) & (predictions["model"] == model_name)].copy()
    if subset.empty:
        return pd.DataFrame(columns=["target_timestamp_utc", "y_true", "y_pred", "abs_error"])

    subset["target_timestamp_utc"] = pd.to_datetime(subset["target_timestamp_utc"], utc=True, errors="coerce")
    subset["origin_local"] = pd.to_datetime(subset["origin_local"], utc=True, errors="coerce")
    subset["y_true"] = pd.to_numeric(subset["y_true"], errors="coerce")
    subset["y_pred"] = pd.to_numeric(subset["y_pred"], errors="coerce")

    subset = subset.dropna(subset=["target_timestamp_utc", "origin_local", "y_true"]).copy()
    subset = subset[subset["y_pred"].notna()].copy()
    if subset.empty:
        return pd.DataFrame(columns=["target_timestamp_utc", "y_true", "y_pred", "abs_error"])

    subset = subset.sort_values(["target_timestamp_utc", "origin_local"])
    dedup = subset.drop_duplicates(subset=["target_timestamp_utc"], keep="first").copy()
    dedup["abs_error"] = (dedup["y_pred"] - dedup["y_true"]).abs()
    return dedup.reset_index(drop=True)


def _split_utc_window(local_start: date, local_end: date, timezone: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    utc_start = pd.Timestamp(local_start).tz_localize(timezone).tz_convert("UTC")
    utc_end = (pd.Timestamp(local_end) + pd.Timedelta(days=1)).tz_localize(timezone).tz_convert("UTC")
    return utc_start, utc_end


def plot_split_overview(
    labeled: pd.DataFrame,
    setup: ForecastSetup,
    validation_track: pd.DataFrame,
    test_track: pd.DataFrame,
    output_path: Path,
    model_name: str,
) -> None:
    frame = labeled[labeled["split"].isin(["train", "validation", "test"])].copy()
    frame = frame.sort_values(setup.timestamp_col)

    forecast_track = pd.concat([validation_track, test_track], ignore_index=True)
    forecast_track = forecast_track.sort_values("target_timestamp_utc")

    fig, ax = plt.subplots(figsize=(16, 6))
    ax.plot(frame[setup.timestamp_col], frame[setup.target_col], linewidth=0.8, alpha=0.75, label="Actual")
    if not forecast_track.empty:
        ax.plot(
            forecast_track["target_timestamp_utc"],
            forecast_track["y_pred"],
            linewidth=0.8,
            alpha=0.8,
            label=f"Forecast ({model_name})",
        )

    split_colors = {
        "train": "#d9f2d9",
        "validation": "#fff5cc",
        "test": "#ffd9d9",
    }
    for split_name, (start_date, end_date) in setup.split_boundaries().items():
        start_utc, end_utc = _split_utc_window(start_date, end_date, setup.local_timezone)
        ax.axvspan(start_utc, end_utc, color=split_colors[split_name], alpha=0.2)

    ax.set_title("DA NL Hourly Prices: Actual and Forecast with Train/Validation/Test Periods")
    ax.set_xlabel("Timestamp (UTC)")
    ax.set_ylabel("Price (EUR/MWh)")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def _select_best_worst_by_group(test_track: pd.DataFrame, key_col: str) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    grouped = (
        test_track.groupby(key_col, as_index=False)
        .agg(
            mae=("abs_error", "mean"),
            observations=("abs_error", "size"),
            start_utc=("target_timestamp_utc", "min"),
            end_utc=("target_timestamp_utc", "max"),
        )
        .sort_values("mae")
        .reset_index(drop=True)
    )
    best = grouped.iloc[0]
    worst = grouped.iloc[-1]
    return grouped, best, worst


def _selection_from_row(label: str, row: pd.Series) -> PeriodSelection:
    return PeriodSelection(
        label=label,
        mae=float(row["mae"]),
        observations=int(row["observations"]),
        start_utc=pd.Timestamp(row["start_utc"]),
        end_utc=pd.Timestamp(row["end_utc"]),
    )


def select_week_month_periods(test_track: pd.DataFrame, local_timezone: str) -> dict[str, object]:
    if test_track.empty:
        raise ValueError("Cannot select best/worst periods on an empty test forecast track.")

    local_ts = test_track["target_timestamp_utc"].dt.tz_convert(local_timezone)

    iso = local_ts.dt.isocalendar()
    test_track = test_track.copy()
    test_track["week_key"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    test_track["month_key"] = local_ts.dt.tz_localize(None).dt.to_period("M").astype(str)

    week_table, best_week_row, worst_week_row = _select_best_worst_by_group(test_track, "week_key")
    month_table, best_month_row, worst_month_row = _select_best_worst_by_group(test_track, "month_key")

    return {
        "week_table": week_table,
        "month_table": month_table,
        "best_week": _selection_from_row(str(best_week_row["week_key"]), best_week_row),
        "worst_week": _selection_from_row(str(worst_week_row["week_key"]), worst_week_row),
        "best_month": _selection_from_row(str(best_month_row["month_key"]), best_month_row),
        "worst_month": _selection_from_row(str(worst_month_row["month_key"]), worst_month_row),
    }


def plot_zoom_period(
    test_track: pd.DataFrame,
    selection: PeriodSelection,
    output_path: Path,
    title: str,
) -> None:
    period = test_track[
        (test_track["target_timestamp_utc"] >= selection.start_utc)
        & (test_track["target_timestamp_utc"] <= selection.end_utc)
    ].copy()
    period = period.sort_values("target_timestamp_utc")

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(period["target_timestamp_utc"], period["y_true"], linewidth=1.0, label="Actual")
    ax.plot(period["target_timestamp_utc"], period["y_pred"], linewidth=1.0, label="Forecast")
    ax.set_title(f"{title} | {selection.label} | MAE={selection.mae:.3f} | n={selection.observations}")
    ax.set_xlabel("Timestamp (UTC)")
    ax.set_ylabel("Price (EUR/MWh)")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
