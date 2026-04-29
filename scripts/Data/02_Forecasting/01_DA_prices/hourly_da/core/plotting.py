from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd


def _running_inside_ipykernel() -> bool:
    try:
        from IPython import get_ipython
    except Exception:
        return False
    shell = get_ipython()
    return shell is not None and shell.__class__.__name__ == "ZMQInteractiveShell"


if not _running_inside_ipykernel():
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import dates as mdates


FIGURE_FACE = "#f5f8fb"
AX_FACE = "#ffffff"
TEXT_COLOR = "#183247"
MUTED_TEXT = "#51606d"
GRID_COLOR = "#d9e2ea"
SPINE_COLOR = "#dbe4eb"
ACTUAL_COLOR = "#183247"
SERIES_COLORS = [
    "#5f8fbd",
    "#d88c8a",
    "#8cbf9f",
    "#d7b46a",
    "#7a8fa8",
    "#7fb8b2",
]
SPLIT_SPAN_COLORS = {"train": "#d8ead4", "validation": "#f4ebc9", "test": "#f1d7d4"}


def _base_figure(figsize: tuple[float, float]) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(FIGURE_FACE)
    ax.set_facecolor(AX_FACE)
    for spine in ax.spines.values():
        spine.set_color(SPINE_COLOR)
        spine.set_linewidth(1.0)
    ax.tick_params(colors=MUTED_TEXT, labelsize=10)
    ax.grid(color=GRID_COLOR, alpha=0.65, linewidth=0.8)
    ax.set_axisbelow(True)
    return fig, ax


def _finish_axis(ax: plt.Axes, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=16, fontweight="bold", color=TEXT_COLOR, pad=14)
    ax.set_xlabel(xlabel, color=MUTED_TEXT, fontsize=11, labelpad=10)
    ax.set_ylabel(ylabel, color=MUTED_TEXT, fontsize=11, labelpad=10)


def _legend_style(ax: plt.Axes, ncols: int = 1, loc: str = "best") -> None:
    legend = ax.legend(loc=loc, ncols=ncols, frameon=True, fancybox=True, framealpha=1.0)
    if legend is None:
        return
    frame = legend.get_frame()
    frame.set_facecolor("#fbfdff")
    frame.set_edgecolor("#dce5eb")
    for text in legend.get_texts():
        text.set_color(TEXT_COLOR)
        text.set_fontsize(9)


def plot_price_overview(canonical_frame: pd.DataFrame, split_summary: pd.DataFrame, output_path: Path, target_col: str) -> None:
    fig, ax = _base_figure((18, 6.2))
    ax.plot(canonical_frame["timestamp_utc"], canonical_frame[target_col], linewidth=1.0, color=ACTUAL_COLOR, label="Observed price")
    for row in split_summary.to_dict(orient="records"):
        ax.axvspan(
            pd.Timestamp(row["start_utc_inclusive"]),
            pd.Timestamp(row["end_utc_exclusive"]),
            color=SPLIT_SPAN_COLORS[row["dataset_split"]],
            alpha=0.45,
            label=row["dataset_split"],
        )
    split_boundaries = sorted(pd.to_datetime(split_summary["start_utc_inclusive"], utc=True).tolist())
    for boundary in split_boundaries[1:]:
        ax.axvline(boundary, color="#8fa0ad", linewidth=1.1, alpha=0.9)
    market_label = str(canonical_frame["region"].dropna().iloc[0]) if "region" in canonical_frame.columns else "DA"
    _finish_axis(ax, f"{market_label} Hourly DA Prices with Train / Validation / Test Windows", "Timestamp UTC", "EUR/MWh")
    handles, labels = ax.get_legend_handles_labels()
    dedup: dict[str, object] = {}
    for handle, label in zip(handles, labels, strict=False):
        dedup[label] = handle
    ax.legend(dedup.values(), dedup.keys(), loc="upper right", frameon=True, fancybox=True, framealpha=1.0)
    legend = ax.get_legend()
    if legend is not None:
        legend.get_frame().set_facecolor("#fbfdff")
        legend.get_frame().set_edgecolor("#dce5eb")
        for text in legend.get_texts():
            text.set_color(TEXT_COLOR)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_lead_day_mae(metrics_by_lead_day: pd.DataFrame, output_path: Path, split_name: str) -> None:
    part = metrics_by_lead_day[metrics_by_lead_day["dataset_split"] == split_name].copy()
    if part.empty:
        return
    fig, ax = _base_figure((10, 5))
    for color, (model_name, group) in zip(SERIES_COLORS, part.groupby("model"), strict=False):
        group = group.sort_values("lead_day")
        ax.plot(group["lead_day"], group["mae"], marker="o", markersize=5, linewidth=2.0, color=color, label=model_name)
    _finish_axis(ax, f"MAE by Lead Day ({split_name.capitalize()})", "Lead day", "MAE")
    tick_frame = part[["lead_day", "lead_day_label"]].drop_duplicates().sort_values("lead_day")
    ax.set_xticks(tick_frame["lead_day"].tolist())
    ax.set_xticklabels(tick_frame["lead_day_label"].tolist())
    _legend_style(ax, loc="best")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_metric_bar(
    metrics: pd.DataFrame,
    output_path: Path,
    split_name: str,
    metric_col: str,
    title: str,
    sort_ascending: bool = True,
) -> None:
    part = metrics[metrics["dataset_split"] == split_name].copy()
    if part.empty:
        return
    part = part.sort_values(metric_col, ascending=sort_ascending).reset_index(drop=True)
    fig, ax = _base_figure((12, 5))
    bar_colors = [SERIES_COLORS[idx % len(SERIES_COLORS)] for idx in range(len(part))]
    bars = ax.bar(part["model"], part[metric_col], color=bar_colors, edgecolor="#ffffff", linewidth=1.0)
    for bar, value in zip(bars, part[metric_col], strict=False):
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            float(value),
            f"{float(value):.2f}",
            ha="center",
            va="bottom",
            fontsize=9,
            color=TEXT_COLOR,
        )
    _finish_axis(ax, title, "Model", metric_col)
    ax.tick_params(axis="x", rotation=26)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_week_actual_only(actual_week: pd.DataFrame, output_path: Path, title: str) -> None:
    if actual_week.empty:
        return
    fig, ax = _base_figure((18, 5.2))
    ax.plot(actual_week["timestamp_local"], actual_week["y_true"], linewidth=2.4, color=ACTUAL_COLOR)
    ax.fill_between(actual_week["timestamp_local"], actual_week["y_true"], alpha=0.12, color="#8bb5d6")
    _finish_axis(ax, title, "Local timestamp", "EUR/MWh")
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    ax.margins(x=0.01)
    fig.autofmt_xdate()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_week_actual_vs_models(
    prediction_week: pd.DataFrame,
    output_path: Path,
    title: str,
    model_order: list[str] | None = None,
) -> None:
    if prediction_week.empty:
        return

    prediction_week = prediction_week.copy()
    prediction_week["model"] = prediction_week["model"].astype(str)
    if model_order:
        active_model_order = [model_name for model_name in model_order if model_name in prediction_week["model"].unique()]
        if active_model_order:
            prediction_week["_model_order"] = pd.Categorical(
                prediction_week["model"],
                categories=active_model_order,
                ordered=True,
            )
            prediction_week = prediction_week.sort_values(["_model_order", "target_timestamp_local"]).drop(
                columns=["_model_order"]
            )

    actual = (
        prediction_week[["target_timestamp_local", "y_true"]]
        .drop_duplicates(subset=["target_timestamp_local"])
        .sort_values("target_timestamp_local")
        .reset_index(drop=True)
    )
    fig, ax = _base_figure((18, 5.8))
    ax.plot(actual["target_timestamp_local"], actual["y_true"], linewidth=2.8, color=ACTUAL_COLOR, label="actual")
    for color, (model_name, group) in zip(SERIES_COLORS, prediction_week.groupby("model", sort=False), strict=False):
        group = group.sort_values("target_timestamp_local")
        ax.plot(group["target_timestamp_local"], group["y_pred"], linewidth=1.9, alpha=0.95, color=color, label=model_name)
    _finish_axis(ax, title, "Local timestamp", "EUR/MWh")
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    ax.margins(x=0.01)
    _legend_style(ax, ncols=2, loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
