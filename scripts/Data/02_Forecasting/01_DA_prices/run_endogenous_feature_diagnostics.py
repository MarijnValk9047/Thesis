from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
from matplotlib import pyplot as plt

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.data_loading import (
    audit_timezone_handling,
    handle_missing_da_prices,
    load_and_validate_da_series,
)
from hourly_da.core.endogenous_features import (
    build_endogenous_explicit_features,
    summarize_feature_matrix,
)
from hourly_da.core.storage import create_run_directory, write_csv, write_json


FIGURE_FACE = "#f5f8fb"
AX_FACE = "#ffffff"
TEXT_COLOR = "#183247"
MUTED_TEXT = "#51606d"
GRID_COLOR = "#d9e2ea"
SPINE_COLOR = "#dbe4eb"


def _base_figure(figsize: tuple[float, float]) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(FIGURE_FACE)
    ax.set_facecolor(AX_FACE)
    for spine in ax.spines.values():
        spine.set_color(SPINE_COLOR)
        spine.set_linewidth(1.0)
    ax.grid(color=GRID_COLOR, alpha=0.65, linewidth=0.8)
    ax.tick_params(colors=MUTED_TEXT, labelsize=10)
    ax.set_axisbelow(True)
    return fig, ax


def _finish_axis(ax: plt.Axes, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=15, fontweight="bold", color=TEXT_COLOR, pad=12)
    ax.set_xlabel(xlabel, color=MUTED_TEXT, fontsize=10)
    ax.set_ylabel(ylabel, color=MUTED_TEXT, fontsize=10)


def _save_plot(fig: plt.Figure, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def _select_validation_window(feature_frame: pd.DataFrame, config: HourlyDAPipelineConfig, window_days: int = 14) -> pd.DataFrame:
    if "target_delivery_local_date" not in feature_frame.columns:
        return feature_frame.head(window_days * 24).copy()
    start_local = config.validation_start_local
    end_local = start_local + timedelta(days=window_days - 1)
    window = feature_frame[
        feature_frame["target_delivery_local_date"].between(start_local, end_local)
    ].copy()
    if not window.empty:
        return window
    return feature_frame.head(window_days * 24).copy()


def _plot_full_history(feature_frame: pd.DataFrame, config: HourlyDAPipelineConfig, output_dir: Path) -> None:
    fig, ax = _base_figure((18, 6))
    ax.plot(
        feature_frame[config.timestamp_col],
        feature_frame[config.target_col],
        color="#183247",
        linewidth=1.0,
        label="Observed target",
    )
    ax.plot(
        feature_frame[config.timestamp_col],
        feature_frame[config.feature_source_col],
        color="#8cbf9f",
        linewidth=0.9,
        alpha=0.8,
        label="Feature source",
    )
    _finish_axis(ax, "Hourly DA Price History: Observed Target vs Causal Feature Source", "Timestamp UTC", "EUR/MWh")
    ax.legend(frameon=True)
    _save_plot(fig, output_dir / "plots" / "full_history_observed_vs_feature_source.png")


def _plot_distribution(feature_frame: pd.DataFrame, config: HourlyDAPipelineConfig, output_dir: Path) -> None:
    observed = feature_frame[config.target_col].dropna().astype(float)
    cleaned = feature_frame[config.feature_source_col].dropna().astype(float)
    fig, ax = _base_figure((10, 5))
    ax.hist(observed, bins=80, alpha=0.6, color="#5f8fbd", density=True, label="Observed target")
    ax.hist(cleaned, bins=80, alpha=0.45, color="#d88c8a", density=True, label="Feature source")
    _finish_axis(ax, "Observed vs Causally Filled Price Distribution", "EUR/MWh", "Density")
    ax.legend(frameon=True)
    _save_plot(fig, output_dir / "plots" / "price_distribution_observed_vs_feature_source.png")


def _plot_selected_window(window: pd.DataFrame, config: HourlyDAPipelineConfig, output_dir: Path) -> None:
    fig, ax = _base_figure((16, 5.5))
    ax.plot(window["target_timestamp_local"], window[config.target_col], color="#183247", linewidth=1.7, label="Observed target")
    ax.plot(window["target_timestamp_local"], window["lag_24"], color="#d88c8a", linewidth=1.4, label="lag_24")
    _finish_axis(ax, "Selected Validation Window: Target vs lag_24", "Local timestamp", "EUR/MWh")
    ax.legend(frameon=True)
    _save_plot(fig, output_dir / "plots" / "validation_window_target_vs_lag_24.png")

    fig, ax = _base_figure((16, 5.5))
    ax.plot(window["target_timestamp_local"], window[config.target_col], color="#183247", linewidth=1.7, label="Observed target")
    ax.plot(window["target_timestamp_local"], window["roll_mean_24"], color="#5f8fbd", linewidth=1.5, label="roll_mean_24")
    ax.plot(window["target_timestamp_local"], window["roll_mean_168"], color="#8cbf9f", linewidth=1.5, label="roll_mean_168")
    _finish_axis(ax, "Selected Validation Window: Target vs Rolling Means", "Local timestamp", "EUR/MWh")
    ax.legend(frameon=True)
    _save_plot(fig, output_dir / "plots" / "validation_window_target_vs_rolling_means.png")

    fig, ax1 = _base_figure((16, 5.5))
    ax1.plot(window["target_timestamp_local"], window["day_range_24"], color="#d7b46a", linewidth=1.6, label="day_range_24")
    _finish_axis(ax1, "Selected Validation Window: Daily Range and Negative Share", "Local timestamp", "day_range_24")
    ax2 = ax1.twinx()
    ax2.set_facecolor("none")
    ax2.plot(window["target_timestamp_local"], window["neg_share_24"], color="#7a8fa8", linewidth=1.4, label="neg_share_24")
    ax2.set_ylabel("neg_share_24", color=MUTED_TEXT, fontsize=10)
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, frameon=True)
    _save_plot(fig, output_dir / "plots" / "validation_window_range_and_negative_share.png")


def _plot_correlation_heatmap(summary, output_dir: Path) -> None:
    correlation_matrix = summary.feature_correlation_matrix
    if correlation_matrix.empty:
        return
    fig, ax = _base_figure((14, 11))
    image = ax.imshow(correlation_matrix.to_numpy(dtype=float), cmap="coolwarm", vmin=-1.0, vmax=1.0)
    ax.set_xticks(range(correlation_matrix.shape[1]))
    ax.set_xticklabels(correlation_matrix.columns, rotation=90, fontsize=8)
    ax.set_yticks(range(correlation_matrix.shape[0]))
    ax.set_yticklabels(correlation_matrix.index, fontsize=8)
    _finish_axis(ax, "Endogenous Feature Correlation Heatmap", "", "")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    _save_plot(fig, output_dir / "plots" / "feature_correlation_heatmap.png")


def main() -> None:
    config = HourlyDAPipelineConfig()
    validation = load_and_validate_da_series(config)
    timezone_audit = audit_timezone_handling(config)
    missing = handle_missing_da_prices(validation.source_frame, config)
    feature_frame = build_endogenous_explicit_features(missing.canonical_frame, config)
    summary = summarize_feature_matrix(feature_frame, config)

    run_id, run_dir = create_run_directory(config.output_root, "endogenous_explicit_features")
    window = _select_validation_window(feature_frame, config)
    example_day = window.loc[window["target_delivery_local_date"] == window["target_delivery_local_date"].min()].copy() if not window.empty else window

    write_json(run_dir / "config_snapshot.json", config.to_json_dict())
    write_json(run_dir / "timezone_audit.json", timezone_audit.to_dict())
    write_json(run_dir / "feature_metadata_summary.json", summary.metadata_summary)
    write_json(
        run_dir / "run_summary.json",
        {
            "run_id": run_id,
            "run_label": "endogenous_explicit_features",
            "market_area": config.market_area,
            "rows_on_canonical_grid": int(summary.metadata_summary["total_rows_on_canonical_grid"]),
            "rows_usable_for_supervised_learning": int(summary.metadata_summary["rows_usable_for_supervised_learning"]),
            "theoretical_first_usable_timestamp_utc": str(
                summary.metadata_summary["theoretical_first_usable_timestamp_utc"]
            ),
            "saved_artifacts": [
                "validated_source_series.csv",
                "validation_integrity_summary.csv",
                "duplicate_timestamp_details.csv",
                "missing_data_integrity_summary.csv",
                "missing_policy_summary.csv",
                "gap_intervals.csv",
                "endogenous_feature_matrix.csv",
                "feature_catalog.csv",
                "feature_missingness.csv",
                "feature_row_loss.csv",
                "feature_summary_statistics.csv",
                "feature_target_correlations.csv",
                "feature_correlation_matrix.csv",
                "validation_window_preview.csv",
                "example_day_feature_rows.csv",
                "feature_metadata_summary.json",
                "timezone_audit.json",
                "config_snapshot.json",
            ],
        },
    )

    write_csv(run_dir / "validated_source_series.csv", validation.source_frame)
    write_csv(run_dir / "validation_integrity_summary.csv", validation.integrity_summary)
    write_csv(run_dir / "duplicate_timestamp_details.csv", validation.duplicate_details)
    write_csv(run_dir / "missing_data_integrity_summary.csv", missing.integrity_summary)
    write_csv(run_dir / "missing_policy_summary.csv", missing.missing_policy_summary)
    write_csv(run_dir / "gap_intervals.csv", missing.gap_intervals)
    write_csv(run_dir / "endogenous_feature_matrix.csv", feature_frame)
    write_csv(run_dir / "feature_catalog.csv", summary.feature_catalog)
    write_csv(run_dir / "feature_missingness.csv", summary.missingness_table)
    write_csv(run_dir / "feature_row_loss.csv", summary.row_loss_table)
    write_csv(run_dir / "feature_summary_statistics.csv", summary.summary_statistics)
    write_csv(run_dir / "feature_target_correlations.csv", summary.feature_target_correlations)
    write_csv(run_dir / "feature_correlation_matrix.csv", summary.feature_correlation_matrix.reset_index().rename(columns={"index": "feature_name"}))
    write_csv(run_dir / "validation_window_preview.csv", window)
    write_csv(run_dir / "example_day_feature_rows.csv", example_day)

    _plot_full_history(feature_frame, config, run_dir)
    _plot_distribution(feature_frame, config, run_dir)
    if not window.empty:
        _plot_selected_window(window, config, run_dir)
    _plot_correlation_heatmap(summary, run_dir)

    print(f"Run completed: {run_id}")
    print(f"Rows on canonical grid: {summary.metadata_summary['total_rows_on_canonical_grid']}")
    print(f"Theoretical first usable timestamp: {summary.metadata_summary['theoretical_first_usable_timestamp_utc']}")
    print(f"Usable supervised rows: {summary.metadata_summary['rows_usable_for_supervised_learning']}")


if __name__ == "__main__":
    main()
