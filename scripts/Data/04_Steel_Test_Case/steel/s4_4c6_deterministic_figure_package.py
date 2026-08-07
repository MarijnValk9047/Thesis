"""Reusable thesis figure package for deterministic C0/C1 temporal runs.

The package is resolution-aware.  It renders only model/granularity pairs that
were actually solved and records future QH, DAM-only and mFRR slots as not run.
No missing market result is converted to a numerical zero.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from matplotlib.colors import LinearSegmentedColormap

from visual_style import COLORS, apply_visual_style, save_figure

from .s4_4c_unified_physical_modelbuilder import REPO_ROOT


PACKAGE_VERSION = "deterministic_plant_behaviour_figures_v8"
FIGURE_PACKAGE_CONFIG = (
    REPO_ROOT
    / "scripts"
    / "Data"
    / "04_Steel_Test_Case"
    / "configs"
    / "steel_deterministic_figure_package_v8.yaml"
)
STRATEGY_ORDER = (
    "price_insensitive",
    "perfect_foresight_D",
    "dam_only",
    "including_mfrr",
)
STRATEGY_LABELS = {
    "price_insensitive": "Price insensitive",
    "perfect_foresight_D": "Perfect foresight",
    "dam_only": "DAM only",
    "including_mfrr": "Including mFRR",
}
STRATEGY_COLORS = {
    "price_insensitive": "#7FA7C4",
    "perfect_foresight_D": "#D8A25E",
    "dam_only": "#6D9DC5",
    "including_mfrr": "#D99A5E",
}
GRANULARITY_ORDER = ("QH", "H")

LEGACY_PLANT_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "C0": {
        "KGF1": (120.0, 140.0),
        "KGF2": (120.0, 140.0),
        "SiFa": (160.0, 320.0),
        "BF6": (120.0, 170.0),
        "BF7": (184.61538462, 261.53846154),
        "PeFa": (465.75, 513.1875),
    },
    "C1": {
        "KGF1": (140.0, 150.0),
        "SiFa": (160.0, 320.0),
        "BF6": (120.0, 170.0),
        "DRP": (350.0, 550.0),
        "PeFa": (540.0, 595.0),
        "VN25": (175.0, 350.0),
    },
}


def _load_figure_package_settings() -> dict[str, Any]:
    with FIGURE_PACKAGE_CONFIG.open(encoding="utf-8") as handle:
        settings = yaml.safe_load(handle)
    if settings["package_version"] != PACKAGE_VERSION:
        raise ValueError("Figure-package config and renderer versions do not match")
    return settings


def _resolved_plant_bounds(output: Path) -> dict[str, dict[str, tuple[float, float]]]:
    """Read the exact capacity contract used by the run, with legacy fallback."""

    contract_path = output / "resolved_plant_capacity_contract.csv"
    if not contract_path.exists():
        return LEGACY_PLANT_BOUNDS
    rows = pd.read_csv(contract_path).to_dict(orient="records")
    return _resolved_plant_bounds_from_rows(rows)


def _resolved_plant_bounds_from_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, tuple[float, float]]]:
    resolved: dict[str, dict[str, tuple[float, float]]] = {"C0": {}, "C1": {}}
    for row in rows:
        configuration = str(row["configuration"])
        display_name = str(row["display_name"])
        resolved.setdefault(configuration, {})[display_name] = (
            float(row["resolved_minimum"]),
            float(row["resolved_maximum"]),
        )
    for configuration, plants in PLANT_COLUMNS.items():
        for display_name in plants:
            if display_name not in resolved.get(configuration, {}):
                resolved.setdefault(configuration, {})[display_name] = (
                    LEGACY_PLANT_BOUNDS[configuration][display_name]
                )
    return resolved

PLANT_COLUMNS = {
    "C0": {
        "KGF1": "kgf1_t_h",
        "KGF2": "kgf2_t_h",
        "SiFa": "sifa_t_h",
        "BF6": "bf6_t_h",
        "BF7": "bf7_t_h",
        "PeFa": "pefa_t_h",
    },
    "C1": {
        "KGF1": "kgf1_t_h",
        "SiFa": "sifa_t_h",
        "BF6": "bf6_t_h",
        "DRP": "drp_t_h",
        "PeFa": "pefa_t_h",
        "VN25": "vn25_mw",
    },
}

RESPONSE_COLUMNS = {
    "C0": {
        "Basic oxygen plant": "bof_electricity_mwh",
        "Blast furnace 6": "bf6_t_h",
        "Coking plant 1": "kgf1_t_h",
        "Coking plant 2": "kgf2_t_h",
        "DSP plant": "dsp_electricity_mwh",
        "Hot strip mill": "hsm_electricity_mwh",
        "Linde plant": "linde_electricity_mwh",
        "Pelletizing plant": "pefa_t_h",
        "Sintering plant": "sifa_t_h",
        "Aggregate generator": "generation_mwh",
    },
    "C1": {
        "Basic oxygen plant": "bof_electricity_mwh",
        "Blast furnace 6": "bf6_t_h",
        "Coking plant 1": "kgf1_t_h",
        "DRP": "drp_t_h",
        "DSP plant": "dsp_electricity_mwh",
        "EAF": "eaf_electricity_mwh",
        "Hot strip mill": "hsm_electricity_mwh",
        "Linde plant": "linde_electricity_mwh",
        "Pelletizing plant": "pefa_t_h",
        "Sintering plant": "sifa_t_h",
        "VN25 generator": "vn25_mw",
    },
}

COST_COLORS = {
    "Grid electricity": "#4C78A8",
    "Natural gas": "#F28E2B",
    "Coking coal": "#4D4D4D",
    "PCI coal": "#7A7A7A",
    "Iron ore": "#8C6D31",
    "Imported BF pellets": "#59A14F",
    "Imported DR pellets": "#76B7B2",
    "External scrap": "#B07AA1",
    "Imported slabs": "#E15759",
}


def _contrast_text_color(color: str) -> str:
    """Return readable light/dark text for a filled chart element."""

    red, green, blue = (
        int(color[index : index + 2], 16) / 255.0 for index in (1, 3, 5)
    )
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "#FFFFFF" if luminance < 0.48 else "#202529"


def _descending_stack_categories(
    frame: pd.DataFrame,
    *,
    category_column: str,
    value_column: str,
) -> list[str]:
    """Order stacked segments from largest at the base to smallest at the top."""

    totals = frame.groupby(category_column, sort=False)[value_column].sum()
    return [str(item) for item in totals.sort_values(ascending=False).index]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not materialized:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(key for row in materialized for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)


def _strategy_label(strategy: str) -> str:
    return STRATEGY_LABELS.get(strategy, strategy.replace("_", " ").title())


def _time_axis(axis: Any, timestamps: pd.Series) -> None:
    first = pd.Timestamp(timestamps.iloc[0])
    last = pd.Timestamp(timestamps.iloc[-1])
    axis.set_xlim(first, last)
    axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))
    axis.xaxis.set_major_formatter(mdates.ConciseDateFormatter(axis.xaxis.get_major_locator()))


def _right_legend(axis: Any, *, title: str | None = None) -> None:
    handles, labels = axis.get_legend_handles_labels()
    if handles:
        axis.legend(
            handles,
            labels,
            title=title,
            loc="center left",
            bbox_to_anchor=(1.01, 0.5),
            borderaxespad=0.0,
        )


def _save(fig: Any, figures: Path, name: str, paths: list[str]) -> None:
    figures.mkdir(parents=True, exist_ok=True)
    stem = figures / name
    save_figure(fig, stem, save_pdf=False)
    fig.savefig(stem.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)
    paths.extend(
        [
            str(stem.with_suffix(".png").relative_to(REPO_ROOT)),
            str(stem.with_suffix(".svg").relative_to(REPO_ROOT)),
        ]
    )


def _title(fig: Any, text: str) -> None:
    fig.suptitle(text, y=0.99, fontsize=13)
    fig.subplots_adjust(top=0.88, right=0.78, hspace=0.30)


def _weekly_result_rows(economics: pd.DataFrame) -> list[dict[str, Any]]:
    metrics = (
        ("realised_procurement_cost_eur", "Represented production cost", "EUR/week"),
        ("steel_produced_t", "Steel produced", "t/week"),
        ("site_electricity_consumed_mwh", "Site electricity consumed", "MWh/week"),
        (
            "average_electricity_price_paid_eur_per_mwh",
            "Average electricity price paid",
            "EUR/MWh grid import",
        ),
        ("total_electricity_cost_eur", "Grid-electricity cost", "EUR/week"),
        ("total_ng_cost_eur", "Natural-gas cost", "EUR/week"),
        ("total_coal_cost_eur", "Coal cost", "EUR/week"),
        ("total_imported_pellets_cost_eur", "Imported-pellet cost", "EUR/week"),
        ("direct_emissions_tco2", "Reported direct emissions", "tCO2/week"),
        ("mfrr_revenue_eur", "mFRR revenue", "EUR/week"),
    )
    rows: list[dict[str, Any]] = []
    for configuration in ("C0", "C1"):
        for metric, label, unit in metrics:
            for strategy in STRATEGY_ORDER:
                match = economics[
                    (economics["configuration"] == configuration)
                    & (economics["strategy"] == strategy)
                    & (economics["granularity"] == "H")
                ]
                if match.empty:
                    value_: float | str = ""
                    status = "not_run"
                elif metric == "mfrr_revenue_eur":
                    value_ = ""
                    status = "not_applicable_no_mfrr_layer"
                else:
                    value_ = float(match.iloc[0][metric])
                    status = "available"
                rows.append(
                    {
                        "configuration": configuration,
                        "week": "high_volatility",
                        "granularity": "H",
                        "parameter": label,
                        "unit": unit,
                        "model_variant": _strategy_label(strategy),
                        "value": value_,
                        "status": status,
                        "boundary": "represented procurement and explicit fuel-emissions boundary",
                    }
                )
    return rows


def _format_table_value(value_: Any, unit: str, status: str) -> str:
    if status != "available":
        return "Not run" if status == "not_run" else "N/A"
    number = float(value_)
    if unit.startswith("EUR/") and "MWh" not in unit:
        return f"EUR {number / 1_000_000:.2f}m"
    if unit.startswith("EUR/MWh"):
        return f"{number:.2f} EUR/MWh"
    if unit.startswith("MWh"):
        return f"{number / 1_000:.1f} GWh"
    if unit.startswith("tCO2"):
        return f"{number / 1_000:.1f} ktCO2"
    if unit.startswith("t/"):
        return f"{number / 1_000:.1f} kt"
    return f"{number:,.2f}"


def _configuration_table(
    rows: pd.DataFrame,
    configuration: str,
    figures: Path,
    paths: list[str],
) -> None:
    selected = rows[rows["configuration"] == configuration]
    metrics = list(dict.fromkeys(selected["parameter"]))
    cell_text: list[list[str]] = []
    row_labels: list[str] = []
    for metric in metrics:
        metric_rows = selected[selected["parameter"] == metric]
        unit = str(metric_rows.iloc[0]["unit"])
        row_labels.append(f"{metric}\n[{unit}]")
        values: list[str] = []
        for strategy in STRATEGY_ORDER:
            item = metric_rows[metric_rows["model_variant"] == _strategy_label(strategy)].iloc[0]
            values.append(_format_table_value(item["value"], unit, str(item["status"])))
        cell_text.append(values)
    fig, axis = plt.subplots(figsize=(14, 7.5))
    axis.axis("off")
    table = axis.table(
        cellText=cell_text,
        rowLabels=row_labels,
        colLabels=[_strategy_label(item) for item in STRATEGY_ORDER],
        cellLoc="right",
        rowLoc="left",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1.0, 1.65)
    axis.set_title(
        f"{configuration} weekly results | hourly high-volatility week | "
        "represented procurement boundary",
        pad=30,
    )
    axis.text(
        0.0,
        -0.04,
        "DAM-only and mFRR variants were not run; mFRR revenue is not applicable to PF/PI.",
        transform=axis.transAxes,
        fontsize=8,
    )
    _save(fig, figures, f"{configuration.lower()}-weekly-results-table", paths)


def _week_dashboards(dispatch: pd.DataFrame, figures: Path, paths: list[str]) -> None:
    for (configuration, strategy), data in dispatch.groupby(
        ["configuration", "strategy"], sort=True
    ):
        data = data.sort_values("timestamp_utc").iloc[:72]
        timestamps = data["timestamp_utc"]
        fig, axes = plt.subplots(5, 1, figsize=(12.5, 11.5), sharex=True)
        axes[0].plot(timestamps, data["price_eur_per_mwh"], color=COLORS["actual"], label="DA price")
        axes[0].set_ylabel("DA price\n[EUR/MWh]")
        _right_legend(axes[0])
        generation = data["generation_mwh"].astype(float)
        grid = data["grid_import_mwh"].astype(float)
        axes[1].set_facecolor("#EEF1F2")
        axes[1].stackplot(
            timestamps,
            generation,
            grid,
            labels=(
                f"Internal generation (mean {generation.mean():.1f} MW)",
                f"Grid import (mean {grid.mean():.1f} MW)",
            ),
            colors=(COLORS["third_model"], "#BFC5C9"),
            alpha=0.90,
        )
        axes[1].plot(
            timestamps,
            generation + grid,
            color="black",
            linewidth=1.2,
            label=f"Total site load (mean {(generation + grid).mean():.1f} MW)",
        )
        axes[1].set_ylabel("Site electricity\n[MW]")
        _right_legend(axes[1])
        primary_column = (
            "hsm_electricity_mwh" if configuration == "C0" else "eaf_electricity_mwh"
        )
        primary_label = "Hot strip mill" if configuration == "C0" else "EAF"
        axes[2].step(
            timestamps,
            data[primary_column],
            where="post",
            color=COLORS["main_model"],
            label=f"{primary_label} (mean {data[primary_column].mean():.1f} MW)",
        )
        axes[2].set_ylabel(f"{primary_label}\n[MW]")
        _right_legend(axes[2])
        for axis, column, label in (
            (axes[3], "bf6_t_h", "Blast furnace 6"),
            (axes[4], "kgf1_t_h", "Coking plant 1"),
        ):
            axis.plot(
                timestamps,
                data[column],
                color=COLORS["main_model"],
                label=f"{label} (mean {data[column].mean():.1f} t/h)",
            )
            axis.set_ylabel(f"{label}\n[t/h]")
            _right_legend(axis)
        axes[4].set_xlabel("Time [UTC]")
        for axis in axes:
            _time_axis(axis, timestamps)
        _title(
            fig,
            f"{configuration} — {_strategy_label(strategy)} | first 72 h of high-volatility week | "
            "represented site boundary",
        )
        _save(fig, figures, f"week-dashboard-{configuration.lower()}-{strategy}", paths)


def _plant_capacity_figures(
    dispatch: pd.DataFrame,
    figures: Path,
    paths: list[str],
    plant_bounds: Mapping[str, Mapping[str, tuple[float, float]]],
) -> None:
    for configuration in ("C0", "C1"):
        data = dispatch[
            (dispatch["configuration"] == configuration)
            & (dispatch["strategy"] == "perfect_foresight_D")
        ].sort_values("timestamp_utc")
        plants = PLANT_COLUMNS[configuration]
        fig, axes = plt.subplots(
            len(plants) + 1,
            1,
            figsize=(12.5, 2.0 * (len(plants) + 1) + 1.5),
            sharex=True,
        )
        axes = np.atleast_1d(axes)
        axes[0].plot(
            data["timestamp_utc"],
            data["price_eur_per_mwh"],
            color=COLORS["actual"],
            label="DA price",
        )
        axes[0].set_ylabel("DA price\n[EUR/MWh]")
        _right_legend(axes[0])
        _time_axis(axes[0], data["timestamp_utc"])
        for axis, (label, column) in zip(axes[1:], plants.items()):
            lower, upper = plant_bounds[configuration][label]
            unit = "MW" if label == "VN25" else "t/h"
            axis.plot(data["timestamp_utc"], data[column], color=COLORS["main_model"], label=label)
            axis.axhline(lower, color=COLORS["benchmark"], linestyle="--", linewidth=0.8, label=f"Minimum {lower:.1f} {unit}")
            axis.axhline(upper, color=COLORS["warning"], linestyle=":", linewidth=0.8, label=f"Maximum {upper:.1f} {unit}")
            axis.set_ylabel(f"{label}\n[{unit}]")
            axis.set_ylim(lower - 0.06 * (upper - lower), upper + 0.06 * (upper - lower))
            _right_legend(axis, title=f"Capacity range [{unit}]")
            _time_axis(axis, data["timestamp_utc"])
        axes[-1].set_xlabel("Time [UTC]")
        _title(
            fig,
            f"{configuration} continuous-plant operation | perfect foresight | hourly high-volatility week | "
            "governed development capacity ranges",
        )
        _save(fig, figures, f"continuous-plant-capacities-{configuration.lower()}", paths)


def _response_heatmaps(dispatch: pd.DataFrame, figures: Path, paths: list[str]) -> None:
    for configuration in ("C0", "C1"):
        labels = list(RESPONSE_COLUMNS[configuration])
        values = np.full((len(labels), 2), np.nan)
        statuses: list[list[str]] = [["not represented", "not represented"] for _ in labels]
        for column_index, strategy in enumerate(("price_insensitive", "perfect_foresight_D")):
            data = dispatch[
                (dispatch["configuration"] == configuration)
                & (dispatch["strategy"] == strategy)
            ].sort_values("timestamp_utc")
            price = data["price_eur_per_mwh"].astype(float)
            for row_index, label in enumerate(labels):
                column = RESPONSE_COLUMNS[configuration][label]
                if column not in data or data[column].isna().all():
                    continue
                series = data[column].astype(float)
                if series.nunique() <= 1:
                    statuses[row_index][column_index] = "constant"
                    continue
                values[row_index, column_index] = float(series.corr(price))
                statuses[row_index][column_index] = "available"
        fig, axis = plt.subplots(figsize=(8.5, 0.48 * len(labels) + 2.8))
        axis.grid(False)
        muted_diverging = LinearSegmentedColormap.from_list(
            "muted_blue_cream_red",
            ("#6E91AC", "#F4F1EA", "#C98072"),
        )
        image = axis.imshow(
            values,
            aspect="auto",
            cmap=muted_diverging,
            vmin=-1.0,
            vmax=1.0,
        )
        axis.set_yticks(range(len(labels)), labels)
        axis.set_xticks([0, 1], ["Price insensitive\n(H)", "Perfect foresight\n(H)"])
        axis.set_xticks(np.arange(-0.5, 2.0, 1.0), minor=True)
        axis.set_yticks(np.arange(-0.5, len(labels), 1.0), minor=True)
        axis.grid(which="minor", color="#FFFFFF", linewidth=1.2)
        axis.tick_params(which="minor", bottom=False, left=False)
        for row_index in range(len(labels)):
            for column_index in range(2):
                number = values[row_index, column_index]
                text = f"{number:+.2f}" if math.isfinite(number) else statuses[row_index][column_index]
                axis.text(column_index, row_index, text, ha="center", va="center", fontsize=8)
        colorbar = fig.colorbar(image, ax=axis, fraction=0.04, pad=0.12)
        colorbar.set_label("Pearson correlation with DA price [-]")
        _title(
            fig,
            f"{configuration} price-response heatmap | hourly high-volatility week | "
            "descriptive correlation on common support",
        )
        _save(fig, figures, f"price-response-heatmap-{configuration.lower()}", paths)


def _storage_figures(dispatch: pd.DataFrame, figures: Path, paths: list[str]) -> None:
    stores = (
        ("coke_inventory_t", "coke_capacity_t", "Coke"),
        ("sinter_inventory_t", "sinter_capacity_t", "Sinter"),
        ("cold_slab_inventory_t", "cold_slab_capacity_t", "Cold slab"),
        ("pellet_inventory_t", "pellet_capacity_t", "Pellets"),
        ("dri_inventory_t", "dri_capacity_t", "Cold DRI"),
    )
    for configuration in ("C0", "C1"):
        available: list[tuple[str, str, str]] = []
        reference = dispatch[dispatch["configuration"] == configuration]
        for inventory, capacity, label in stores:
            if capacity in reference and (reference[capacity].fillna(0.0) > 0.0).any():
                available.append((inventory, capacity, label))
        fig, axes = plt.subplots(
            len(available),
            1,
            figsize=(12.5, 1.75 * len(available) + 1.7),
            sharex=True,
        )
        for axis, (inventory, capacity, label) in zip(np.atleast_1d(axes), available):
            for strategy in ("price_insensitive", "perfect_foresight_D"):
                data = dispatch[
                    (dispatch["configuration"] == configuration)
                    & (dispatch["strategy"] == strategy)
                ].sort_values("timestamp_utc")
                valid = data[capacity].notna() & (data[capacity].astype(float) > 0.0)
                axis.plot(
                    data.loc[valid, "timestamp_utc"],
                    100.0
                    * data.loc[valid, inventory].astype(float)
                    / data.loc[valid, capacity].astype(float),
                    color=STRATEGY_COLORS[strategy],
                    label=_strategy_label(strategy),
                )
            axis.axhline(100.0, color=COLORS["warning"], linestyle="--", linewidth=0.7, label="Capacity")
            axis.set_ylabel(f"{label}\n[%]")
            axis.set_ylim(-2.0, 102.0)
            _right_legend(axis, title="Operating strategy")
            _time_axis(axis, data["timestamp_utc"])
        np.atleast_1d(axes)[-1].set_xlabel("Time [UTC]")
        _title(
            fig,
            f"{configuration} material-buffer use | hourly high-volatility week | physical storage boundary",
        )
        _save(fig, figures, f"storage-utilisation-{configuration.lower()}", paths)


def _site_load_figures(dispatch: pd.DataFrame, figures: Path, paths: list[str]) -> None:
    for configuration in ("C0", "C1"):
        data = dispatch[
            (dispatch["configuration"] == configuration)
            & (dispatch["strategy"] == "perfect_foresight_D")
        ].sort_values("timestamp_utc")
        generation = data["generation_mwh"].astype(float)
        grid = data["grid_import_mwh"].astype(float)
        fig, axis = plt.subplots(figsize=(12.5, 4.8))
        axis.set_facecolor("#EEF1F2")
        axis.stackplot(
            data["timestamp_utc"],
            generation,
            grid,
            labels=(
                f"Internal generation (mean {generation.mean():.1f} MW)",
                f"Grid import (mean {grid.mean():.1f} MW)",
            ),
            colors=(COLORS["third_model"], "#BFC5C9"),
            alpha=0.90,
        )
        axis.plot(
            data["timestamp_utc"],
            generation + grid,
            color="black",
            linewidth=1.3,
            label=f"Total site load (mean {(generation + grid).mean():.1f} MW)",
        )
        axis.set_ylabel("Electricity supply and load [MW]")
        axis.set_xlabel("Time [UTC]")
        _right_legend(axis, title="Represented site balance")
        _time_axis(axis, data["timestamp_utc"])
        _title(
            fig,
            f"{configuration} site load supplied by internal generation and grid import | "
            "perfect foresight | hourly high-volatility week",
        )
        _save(fig, figures, f"stacked-site-load-{configuration.lower()}", paths)


def _grouped_economic_chart(economics: pd.DataFrame, figures: Path, paths: list[str]) -> None:
    metrics = (
        ("cost_eur_per_t", "Steel production cost", "EUR/t steel"),
        ("total_electricity_cost_eur", "Total grid-electricity cost", "EUR/week"),
        (
            "average_electricity_price_paid_eur_per_mwh",
            "Average electricity price paid",
            "EUR/MWh grid import",
        ),
    )
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.5))
    granularities = [
        item for item in GRANULARITY_ORDER if item in set(economics["granularity"])
    ]
    strategies = [
        item for item in STRATEGY_ORDER if item in set(economics["strategy"])
    ]
    width = min(0.32, 0.72 / max(1, len(strategies)))
    for row_index, configuration in enumerate(("C0", "C1")):
        for col_index, (metric, title, unit) in enumerate(metrics):
            axis = axes[row_index, col_index]
            axis.set_axisbelow(True)
            axis.grid(axis="x", visible=False)
            for strategy_index, strategy in enumerate(strategies):
                positions = np.arange(len(granularities)) + (
                    strategy_index - (len(strategies) - 1) / 2.0
                ) * width
                heights: list[float] = []
                for granularity in granularities:
                    match = economics[
                        (economics["configuration"] == configuration)
                        & (economics["granularity"] == granularity)
                        & (economics["strategy"] == strategy)
                    ]
                    heights.append(float(match.iloc[0][metric]))
                axis.bar(
                    positions,
                    heights,
                    width,
                    color=STRATEGY_COLORS[strategy],
                    label=_strategy_label(strategy),
                    zorder=3,
                )
            axis.set_xticks(range(len(granularities)), granularities)
            axis.set_ylabel(unit)
            axis.set_title(f"{configuration} — {title}")
            if col_index == 2:
                _right_legend(axis, title="Model variant")
    _title(
        fig,
        "Economic comparison by model granularity | one high-volatility week | "
        "represented procurement boundary",
    )
    _save(fig, figures, "qh-h-grouped-economic-comparison", paths)


def _cost_outputs(
    costs: pd.DataFrame,
    economics: pd.DataFrame,
    tables: Path,
    figures: Path,
    paths: list[str],
) -> None:
    grouped = (
        costs.groupby(["configuration", "granularity", "strategy", "cost_category"], as_index=False)
        .agg(quantity=("quantity", "sum"), cost_eur=("cost_eur", "sum"))
    )
    steel = economics.set_index(["configuration", "granularity", "strategy"])["steel_produced_t"]
    grouped["steel_produced_t"] = [
        float(steel.loc[(row.configuration, row.granularity, row.strategy)])
        for row in grouped.itertuples()
    ]
    grouped["cost_eur_per_t_steel"] = grouped["cost_eur"] / grouped["steel_produced_t"]
    grouped["boundary"] = "represented external procurement only"
    grouped.to_csv(tables / "represented-cost-breakdown.csv", index=False)

    cases = [("C0", "price_insensitive"), ("C0", "perfect_foresight_D"), ("C1", "price_insensitive"), ("C1", "perfect_foresight_D")]
    categories = _descending_stack_categories(
        grouped,
        category_column="cost_category",
        value_column="cost_eur_per_t_steel",
    )
    fig, axis = plt.subplots(figsize=(11.5, 5.5))
    axis.set_axisbelow(True)
    axis.grid(False)
    bottoms = np.zeros(len(cases))
    for category in categories:
        values = []
        for configuration, strategy in cases:
            match = grouped[
                (grouped["configuration"] == configuration)
                & (grouped["strategy"] == strategy)
                & (grouped["cost_category"] == category)
            ]
            values.append(0.0 if match.empty else float(match.iloc[0]["cost_eur_per_t_steel"]))
        bars_ = axis.bar(
            range(len(cases)),
            values,
            bottom=bottoms,
            label=category,
            color=COST_COLORS.get(category, COLORS["benchmark"]),
            zorder=3,
        )
        for index, (bar, amount, bottom) in enumerate(zip(bars_, values, bottoms)):
            if amount <= 0.0:
                continue
            if amount < 9.0:
                direction = -1.0 if index % 2 == 0 else 1.0
                axis.annotate(
                    f"{amount:.1f}",
                    xy=(bar.get_x() + bar.get_width() / 2.0, bottom + amount / 2.0),
                    xytext=(bar.get_x() + bar.get_width() / 2.0 + 0.52 * direction, bottom + amount / 2.0),
                    ha="right" if direction < 0 else "left",
                    va="center",
                    fontsize=6.8,
                    arrowprops={"arrowstyle": "-", "color": COLORS["benchmark"], "linewidth": 0.6},
                    zorder=4,
                )
                continue
            text_color = _contrast_text_color(
                COST_COLORS.get(category, COLORS["benchmark"])
            )
            axis.text(
                bar.get_x() + bar.get_width() / 2.0,
                bottom + amount / 2.0,
                f"{amount:.1f}",
                ha="center",
                va="center",
                fontsize=6.8,
                rotation=0,
                color=text_color,
                zorder=4,
            )
        bottoms += np.asarray(values)
    for index, total in enumerate(bottoms):
        axis.text(
            index,
            total + max(bottoms) * 0.015,
            f"Total {total:.1f} EUR/t",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    axis.set_xticks(range(len(cases)), [f"{c}\n{_strategy_label(s)}" for c, s in cases])
    axis.set_ylabel("Represented procurement cost [EUR/t steel]")
    _right_legend(axis, title="Cost item")
    _title(
        fig,
        "Represented procurement-cost composition | hourly high-volatility week | "
        "external purchases only",
    )
    _save(fig, figures, "stacked-procurement-cost-per-tonne", paths)

    fig, axes = plt.subplots(2, 2, figsize=(11.4, 8.4))
    legend_items: dict[str, Any] = {}
    for axis, (configuration, strategy) in zip(axes.flat, cases):
        data = grouped[
            (grouped["configuration"] == configuration)
            & (grouped["strategy"] == strategy)
        ]
        values = data["cost_eur_per_t_steel"].astype(float).to_numpy()
        labels = data["cost_category"].astype(str).tolist()
        colors = [COST_COLORS.get(label, COLORS["benchmark"]) for label in labels]
        total = float(values.sum())

        def percentage(value_: float) -> str:
            return f"{value_:.1f}%" if value_ >= 2.0 else ""

        wedges, _, percentage_texts = axis.pie(
            values,
            colors=colors,
            startangle=90,
            counterclock=False,
            autopct=percentage,
            pctdistance=0.79,
            wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 0.7},
            textprops={"fontsize": 8},
        )
        for color, percentage_text in zip(colors, percentage_texts):
            percentage_text.set_color(_contrast_text_color(color))
        axis.text(0.0, 0.0, f"{total:.1f}\nEUR/t", ha="center", va="center", fontsize=10)
        axis.set_title(f"{configuration} — {_strategy_label(strategy)}")
        axis.grid(False)
        for label, wedge in zip(labels, wedges):
            legend_items.setdefault(label, wedge)
    _title(
        fig,
        "Represented procurement-cost shares | hourly high-volatility week | "
        "external purchases only",
    )
    fig.subplots_adjust(top=0.88, right=0.79, wspace=-0.04, hspace=0.16)
    fig.legend(
        list(legend_items.values()),
        list(legend_items),
        title="Cost item",
        loc="center right",
        bbox_to_anchor=(0.995, 0.5),
        frameon=False,
    )
    _save(fig, figures, "procurement-cost-share-piecharts", paths)

    hierarchy = {
        "Energy carriers": (
            "Coking coal", "Natural gas", "Grid electricity", "PCI coal"
        ),
        "Materials": (
            "Iron ore", "External scrap", "Imported slabs",
            "Imported BF pellets", "Imported DR pellets",
        ),
    }
    inner_colors = {"Energy carriers": "#A8C5DA", "Materials": "#E4BE91"}
    fig, axes = plt.subplots(2, 2, figsize=(11.6, 8.6))
    sunburst_handles: dict[str, Any] = {}
    for axis, (configuration, strategy) in zip(axes.flat, cases):
        data = grouped[
            (grouped["configuration"] == configuration)
            & (grouped["strategy"] == strategy)
            & (grouped["cost_eur_per_t_steel"] > 1e-9)
        ].copy()
        data_by_category = data.set_index("cost_category")["cost_eur_per_t_steel"]
        inner_labels = list(hierarchy)
        outer_labels = [
            category
            for parent in inner_labels
            for category in hierarchy[parent]
            if category in data_by_category.index
            and float(data_by_category.loc[category]) > 1e-9
        ]
        outer_parents = [
            parent
            for parent in inner_labels
            for category in hierarchy[parent]
            if category in data_by_category.index
            and float(data_by_category.loc[category]) > 1e-9
        ]
        outer_values = [float(data_by_category.loc[label]) for label in outer_labels]
        outer_colors = [
            COST_COLORS.get(label, COLORS["benchmark"]) for label in outer_labels
        ]
        inner_values = [
            sum(
                float(data_by_category.loc[category])
                for category in hierarchy[label]
                if category in data_by_category.index
            )
            for label in inner_labels
        ]
        outer_wedges, _ = axis.pie(
            outer_values,
            radius=1.0,
            colors=outer_colors,
            startangle=90,
            counterclock=False,
            wedgeprops={"width": 0.34, "edgecolor": "white", "linewidth": 0.7},
        )
        parent_totals = dict(zip(inner_labels, inner_values))
        for label, parent, value_, color, wedge in zip(
            outer_labels,
            outer_parents,
            outer_values,
            outer_colors,
            outer_wedges,
        ):
            within_parent_pct = 100.0 * value_ / parent_totals[parent]
            if within_parent_pct >= 5.0:
                angle = math.radians((wedge.theta1 + wedge.theta2) / 2.0)
                axis.text(
                    0.83 * math.cos(angle),
                    0.83 * math.sin(angle),
                    f"{within_parent_pct:.0f}%",
                    ha="center",
                    va="center",
                    fontsize=7.2,
                    color=_contrast_text_color(color),
                )
            sunburst_handles.setdefault(label, wedge)
        inner_wedges, _, inner_texts = axis.pie(
            inner_values,
            radius=0.66,
            colors=[inner_colors[label] for label in inner_labels],
            startangle=90,
            counterclock=False,
            autopct=lambda pct: f"{pct:.0f}%" if pct >= 5.0 else "",
            pctdistance=0.72,
            wedgeprops={"width": 0.34, "edgecolor": "white", "linewidth": 0.8},
            textprops={"fontsize": 7.5},
        )
        for label, wedge, percentage_text in zip(
            inner_labels, inner_wedges, inner_texts
        ):
            percentage_text.set_color(_contrast_text_color(inner_colors[label]))
            sunburst_handles.setdefault(label, wedge)
        axis.text(
            0.0, 0.0, f"{sum(outer_values):.1f}\nEUR/t",
            ha="center", va="center", fontsize=9.5,
        )
        axis.set_title(f"{configuration} — {_strategy_label(strategy)}")
        axis.grid(False)
    _title(
        fig,
        "Represented procurement-cost hierarchy | hourly high-volatility week | "
        "category and purchased-item levels",
    )
    fig.subplots_adjust(top=0.88, right=0.78, wspace=-0.02, hspace=0.16)
    legend_order = list(hierarchy) + [
        category for parent in hierarchy for category in hierarchy[parent]
    ]
    legend_order = [label for label in legend_order if label in sunburst_handles]
    fig.legend(
        [sunburst_handles[label] for label in legend_order],
        legend_order,
        title="Cost hierarchy",
        loc="center right",
        bbox_to_anchor=(0.995, 0.5),
        frameon=False,
    )
    _save(fig, figures, "procurement-cost-hierarchy-sunburst", paths)

    pivot = grouped.pivot_table(
        index="cost_category",
        columns=["configuration", "strategy"],
        values="cost_eur_per_t_steel",
        aggfunc="sum",
        fill_value=0.0,
    )
    fig, axis = plt.subplots(figsize=(12, 0.48 * len(pivot) + 3.2))
    axis.axis("off")
    table = axis.table(
        cellText=[[f"{float(value_):.2f}" for value_ in row] for row in pivot.to_numpy()],
        rowLabels=list(pivot.index),
        colLabels=[f"{c}\n{_strategy_label(s)}" for c, s in pivot.columns],
        cellLoc="right",
        rowLoc="left",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1.0, 1.5)
    axis.set_title(
        "Where represented procurement costs go | EUR/t steel | hourly high-volatility week",
        pad=28,
    )
    _save(fig, figures, "represented-procurement-cost-table", paths)


def _drp_eaf_day_figure(
    dispatch: pd.DataFrame,
    eaf_subhourly: pd.DataFrame,
    figures: Path,
    paths: list[str],
) -> None:
    c1_pf = dispatch[
        (dispatch["configuration"] == "C1")
        & (dispatch["strategy"] == "perfect_foresight_D")
    ].copy()
    c1_pf["date"] = pd.to_datetime(c1_pf["timestamp_utc"]).dt.date
    day = c1_pf.groupby("date")["price_eur_per_mwh"].agg(lambda s: float(s.max() - s.min())).idxmax()
    pf = c1_pf[c1_pf["date"] == day].sort_values("timestamp_utc")
    pi = dispatch[
        (dispatch["configuration"] == "C1")
        & (dispatch["strategy"] == "price_insensitive")
        & (pd.to_datetime(dispatch["timestamp_utc"]).dt.date == day)
    ].sort_values("timestamp_utc")
    timestamps = pf["timestamp_utc"]
    fig, axes = plt.subplots(4, 1, figsize=(12.5, 10), sharex=True)
    axes[0].plot(timestamps, pf["price_eur_per_mwh"], color=COLORS["actual"], label="DA price")
    axes[0].set_ylabel("DA price\n[EUR/MWh]")
    _right_legend(axes[0])
    for axis, data, strategy in (
        (axes[1], pf, "Perfect foresight"),
        (axes[2], pi, "Price insensitive"),
    ):
        sub = eaf_subhourly[
            (eaf_subhourly["strategy"] == data["strategy"].iloc[0])
            & (eaf_subhourly["date"] == day)
        ].sort_values("timestamp_utc")
        axis.stackplot(
            sub["timestamp_utc"],
            sub["arc_power_mw"],
            sub["cold_dri_reheat_power_mw"],
            sub["secondary_metallurgy_power_mw"],
            step="post",
            colors=(COLORS["alternative_model"], "#D7A76E", "#A99AC2"),
            labels=("EAF arc", "Cold-DRI heating", "Secondary metallurgy"),
            alpha=0.92,
        )
        axis.step(
            sub["timestamp_utc"],
            sub["total_eaf_related_power_mw"],
            where="post",
            color="black",
            linewidth=1.1,
            label="Total EAF-related load",
        )
        drp_axis = axis.twinx()
        drp_axis.step(
            data["timestamp_utc"],
            data["drp_electricity_mwh"],
            where="post",
            color=COLORS["third_model"],
            label="DRP electricity",
        )
        drp_axis.set_ylabel("DRP load [MW]", color=COLORS["third_model"])
        drp_axis.grid(False)
        axis.set_ylabel(f"{strategy}\nEAF-related load [MW]")
        handles, labels = axis.get_legend_handles_labels()
        extra_handles, extra_labels = drp_axis.get_legend_handles_labels()
        axis.legend(
            handles + extra_handles,
            labels + extra_labels,
            title="Plant electricity load",
            loc="center left",
            bbox_to_anchor=(1.11, 0.5),
            frameon=False,
        )
    capacity = float(pf["dri_capacity_t"].dropna().iloc[0])
    pi_buffer_pct = 100.0 * pi["dri_inventory_t"] / capacity
    pf_buffer_pct = 100.0 * pf["dri_inventory_t"] / capacity
    axes[3].plot(pi["timestamp_utc"], pi_buffer_pct, color=COLORS["price_insensitive"], label="Cold DRI buffer — Price insensitive")
    axes[3].plot(pf["timestamp_utc"], pf_buffer_pct, color=COLORS["perfect_foresight"], label="Cold DRI buffer — Perfect foresight")
    observed_buffer_pct = max(float(pi_buffer_pct.max()), float(pf_buffer_pct.max()))
    visible_upper_pct = max(5.0, 5.0 * math.ceil(observed_buffer_pct * 1.15 / 5.0))
    axes[3].set_ylim(0.0, min(100.0, visible_upper_pct))
    axes[3].set_ylabel("Cold DRI inventory [% of capacity]")
    axes[3].set_xlabel("Time [UTC]")
    _right_legend(axes[3], title="Cold DRI buffer")
    for axis in axes:
        _time_axis(axis, timestamps)
    temporal_resolution = (
        str(eaf_subhourly["temporal_resolution"].dropna().iloc[0])
        if "temporal_resolution" in eaf_subhourly
        and not eaf_subhourly["temporal_resolution"].dropna().empty
        else "internal_15_minute_batch_states"
    )
    resolution_label = (
        "hourly settlement aggregates"
        if temporal_resolution == "H_settlement_aggregate"
        else "hourly settlement with internal 15-min EAF batch states"
    )
    _title(
        fig,
        f"C1 DRP–EAF operation and cold DRI buffer | {day} | {resolution_label}",
    )
    _save(fig, figures, "c1-drp-eaf-dri-example-day-h", paths)


def _drp_eaf_arc_day_figure(
    dispatch: pd.DataFrame,
    eaf_subhourly: pd.DataFrame,
    figures: Path,
    paths: list[str],
    *,
    eaf_arc_five_minute: pd.DataFrame | None = None,
) -> None:
    """Plot pure EAF arc load with DRP load and cold-DRI buffer state."""

    use_arc_replay = eaf_arc_five_minute is not None and not eaf_arc_five_minute.empty
    if use_arc_replay:
        replay = eaf_arc_five_minute.copy()
        replay["timestamp_utc"] = pd.to_datetime(replay["timestamp_utc"], utc=True)
        replay["date"] = replay["timestamp_utc"].dt.tz_convert("Europe/Amsterdam").dt.date
        day = replay["date"].iloc[0]
        operations = {
            strategy: replay[replay["strategy"] == strategy].sort_values(
                "timestamp_utc"
            )
            for strategy in ("perfect_foresight_D", "price_insensitive")
        }
        arc = operations
    else:
        c1 = dispatch[dispatch["configuration"] == "C1"].copy()
        c1["date"] = pd.to_datetime(c1["timestamp_utc"]).dt.date
        pf_all = c1[c1["strategy"] == "perfect_foresight_D"]
        day = pf_all.groupby("date")["price_eur_per_mwh"].agg(
            lambda values: float(values.max() - values.min())
        ).idxmax()
        operations = {
            strategy: c1[
                (c1["strategy"] == strategy) & (c1["date"] == day)
            ].sort_values("timestamp_utc")
            for strategy in ("perfect_foresight_D", "price_insensitive")
        }
        arc = {
            strategy: eaf_subhourly[
                (eaf_subhourly["strategy"] == strategy)
                & (eaf_subhourly["date"] == day)
            ].sort_values("timestamp_utc")
            for strategy in operations
        }

    pf = operations["perfect_foresight_D"]
    pi = operations["price_insensitive"]
    timestamps = pf["timestamp_utc"]
    fig, axes = plt.subplots(4, 1, figsize=(12.5, 10), sharex=True)
    axes[0].step(
        timestamps,
        pf["price_eur_per_mwh"],
        where="post",
        color=COLORS["actual"],
        label="Day-ahead price",
    )
    axes[0].set_ylabel("DA price\n[EUR/MWh]")
    _right_legend(axes[0])

    for axis, strategy, strategy_label in (
        (axes[1], "perfect_foresight_D", "Perfect foresight"),
        (axes[2], "price_insensitive", "Price insensitive"),
    ):
        data = operations[strategy]
        sub = arc[strategy]
        arc_color = (
            COLORS["perfect_foresight"]
            if strategy == "perfect_foresight_D"
            else COLORS["price_insensitive"]
        )
        axis.fill_between(
            sub["timestamp_utc"],
            0.0,
            sub["arc_power_mw"],
            step="post",
            color=arc_color,
            alpha=0.25,
        )
        axis.step(
            sub["timestamp_utc"],
            sub["arc_power_mw"],
            where="post",
            color=arc_color,
            linewidth=1.6,
            label="EAF arc heating",
        )
        drp_axis = axis.twinx()
        drp_axis.step(
            data["timestamp_utc"],
            data["drp_electricity_mwh"],
            where="post",
            color=COLORS["third_model"],
            linewidth=1.4,
            label="DRP electricity",
        )
        drp_axis.set_ylabel("DRP load [MW]", color=COLORS["third_model"])
        drp_axis.grid(False)
        axis.set_ylabel(f"{strategy_label}\nEAF arc power [MW]")
        handles, labels = axis.get_legend_handles_labels()
        extra_handles, extra_labels = drp_axis.get_legend_handles_labels()
        axis.legend(
            handles + extra_handles,
            labels + extra_labels,
            title="Plant electricity load",
            loc="center left",
            bbox_to_anchor=(1.11, 0.5),
            frameon=False,
        )

    capacity = float(pf["dri_capacity_t"].dropna().iloc[0])
    pf_buffer_pct = 100.0 * pf["dri_inventory_t"] / capacity
    pi_buffer_pct = 100.0 * pi["dri_inventory_t"] / capacity
    axes[3].plot(
        pf["timestamp_utc"],
        pf_buffer_pct,
        color=COLORS["perfect_foresight"],
        label="Perfect foresight",
    )
    axes[3].plot(
        pi["timestamp_utc"],
        pi_buffer_pct,
        color=COLORS["price_insensitive"],
        label="Price insensitive",
    )
    observed_buffer_pct = max(float(pi_buffer_pct.max()), float(pf_buffer_pct.max()))
    visible_upper_pct = max(5.0, 5.0 * math.ceil(observed_buffer_pct * 1.15 / 5.0))
    axes[3].set_ylim(0.0, min(100.0, visible_upper_pct))
    axes[3].set_ylabel("Cold DRI inventory\n[% of capacity]")
    axes[3].set_xlabel("Time [UTC]")
    _right_legend(axes[3], title="Cold DRI buffer")
    for axis in axes:
        _time_axis(axis, timestamps)
    _title(
        fig,
        f"C1 DRP–EAF arc operation and cold DRI buffer | {day} | electricity and storage boundaries",
    )
    _save(fig, figures, "c1-drp-eaf-dri-example-day-h", paths)


def _scope1_anchor_rows() -> pd.DataFrame:
    path = (
        REPO_ROOT
        / "data/03_Optimisation/inputs/assets/steel/S4/"
        "c5_phase5e_source_backed_anchor_contract/source_backed_annual_service_contract.csv"
    )
    frame = pd.read_csv(path)
    return frame[frame["record_id"].isin(
        [
            "c0_scope1_total", "c0_scope1_coal", "c0_scope1_iron", "c0_scope1_ng", "c0_scope1_flux",
            "c1_scope1_total", "c1_scope1_coal", "c1_scope1_ng", "c1_scope1_flux",
        ]
    )]


def _emissions_figure(dispatch: pd.DataFrame, figures: Path, paths: list[str]) -> None:
    factor = 8760.0 / 168.0 / 1_000_000.0
    model_components = {
        "BFG oxidation": "bfg_combustion_co2_t",
        "COG oxidation": "cog_combustion_co2_t",
        "BOFG oxidation": "bofg_combustion_co2_t",
        "Named NG oxidation": "named_ng_combustion_co2_t",
        "Unmodelled direct residual": "unmodelled_direct_co2_t",
    }
    anchor = _scope1_anchor_rows()
    anchor_components = {
        "Coal and other carbon": "coal_and_other_carbon",
        "Iron-bearing material": "iron_bearing_material",
        "Natural gas (MER source class)": "natural_gas",
        "Fluxes": "fluxes",
    }
    bars: list[tuple[str, str, dict[str, float]]] = []
    for configuration in ("C0", "C1"):
        for strategy in ("price_insensitive", "perfect_foresight_D"):
            data = dispatch[
                (dispatch["configuration"] == configuration)
                & (dispatch["strategy"] == strategy)
            ]
            bars.append(
                (
                    configuration,
                    _strategy_label(strategy),
                    {label: float(data[column].sum()) * factor for label, column in model_components.items()},
                )
            )
        subset = anchor[anchor["configuration"] == configuration]
        values = {
            label: float(subset[subset["component"] == boundary]["value"].iloc[0])
            if not subset[subset["component"] == boundary].empty
            else 0.0
            for label, boundary in anchor_components.items()
        }
        bars.append((configuration, "MER Scope 1 anchor", values))
    category_totals = {
        category: sum(values.get(category, 0.0) for _, _, values in bars)
        for category in {
            category for _, _, values in bars for category in values
        }
    }
    categories = sorted(category_totals, key=category_totals.get, reverse=True)
    emissions_colors = {
        "Coal and other carbon": "#626262",
        "Unmodelled direct residual": "#A7A29A",
        "BFG oxidation": "#6E91AC",
        "COG oxidation": "#8FB7B0",
        "BOFG oxidation": "#86A66C",
        "Named NG oxidation": "#D8A25E",
        "Iron-bearing material": "#9B7B52",
        "Natural gas (MER source class)": "#C98072",
        "Fluxes": "#B89BB5",
    }
    fig, axis = plt.subplots(figsize=(12.5, 6.2))
    axis.set_axisbelow(True)
    axis.grid(axis="x", visible=False)
    bottoms = np.zeros(len(bars))
    for category in categories:
        color = emissions_colors[category]
        values = np.asarray([components.get(category, 0.0) for _, _, components in bars])
        bars_ = axis.bar(
            range(len(bars)),
            values,
            bottom=bottoms,
            label=category,
            color=color,
            zorder=3,
        )
        for bar, amount, bottom in zip(bars_, values, bottoms):
            if amount < 0.08:
                continue
            axis.text(
                bar.get_x() + bar.get_width() / 2.0,
                bottom + amount / 2.0,
                f"{amount:.2f}",
                ha="center",
                va="center",
                fontsize=7.0,
                color=_contrast_text_color(color),
                zorder=4,
            )
        bottoms += values
    for index, total in enumerate(bottoms):
        axis.text(
            index,
            total + max(bottoms) * 0.018,
            f"{total:.2f}",
            ha="center",
            va="bottom",
            fontsize=8.0,
        )
    short_labels = {
        "Price insensitive": "PI",
        "Perfect foresight": "PF",
        "MER Scope 1 anchor": "MER anchor",
    }
    axis.set_xticks(
        range(len(bars)),
        [f"{configuration}\n{short_labels[label]}" for configuration, label, _ in bars],
    )
    axis.set_ylabel("Annualised direct emissions [MtCO2/y]")
    _right_legend(axis, title="Model carrier / MER source class")
    _title(
        fig,
        "Annualised emissions and MER anchors | high-volatility week | model oxidation-carrier "
        "boundary versus full-site Scope 1 source classes",
    )
    _save(fig, figures, "emissions-by-carrier-versus-mer-anchor", paths)


def generate_deterministic_figure_package(output: Path, *, regime: str) -> dict[str, Any]:
    """Generate the default complete deterministic figure selection."""

    apply_visual_style()
    figures = output / "figures"
    # ``output`` is already the governed standard-figure-package root.  Do
    # not repeat ``figure_package`` below it: the redundant nesting pushed
    # valid annual run paths beyond the legacy Windows MAX_PATH boundary.
    tables = output / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    dispatch = pd.read_csv(output / "hourly_dispatch.csv")
    dispatch["timestamp_utc"] = pd.to_datetime(dispatch["timestamp_utc"], utc=True)
    eaf_subhourly = pd.read_csv(output / "eaf_subhourly_load.csv")
    eaf_subhourly["timestamp_utc"] = pd.to_datetime(
        eaf_subhourly["timestamp_utc"], utc=True
    )
    eaf_subhourly["date"] = eaf_subhourly["timestamp_utc"].dt.date
    arc_replay_path = tables / "c1-eaf-arc-five-minute-example-day.csv"
    eaf_arc_five_minute = (
        pd.read_csv(arc_replay_path) if arc_replay_path.exists() else None
    )
    economics = pd.read_csv(output / "weekly_economics.csv")
    costs = pd.read_csv(output / "represented_cost_ledger.csv")
    settings = _load_figure_package_settings()
    plant_bounds = _resolved_plant_bounds(output)
    paths: list[str] = []

    result_rows = _weekly_result_rows(economics)
    _write_csv(tables / "weekly-configuration-results-long.csv", result_rows)
    result_frame = pd.DataFrame(result_rows)
    for configuration in ("C0", "C1"):
        _configuration_table(result_frame, configuration, figures, paths)

    _week_dashboards(dispatch, figures, paths)
    _plant_capacity_figures(dispatch, figures, paths, plant_bounds)
    _response_heatmaps(dispatch, figures, paths)
    _storage_figures(dispatch, figures, paths)
    _grouped_economic_chart(economics, figures, paths)
    _cost_outputs(costs, economics, tables, figures, paths)
    _drp_eaf_arc_day_figure(
        dispatch,
        eaf_subhourly,
        figures,
        paths,
        eaf_arc_five_minute=eaf_arc_five_minute,
    )
    _emissions_figure(dispatch, figures, paths)

    actual_stems = sorted(Path(path).stem for path in paths if path.endswith(".png"))
    expected_stems = sorted(settings["default_complete_selection"])
    if actual_stems != expected_stems:
        raise RuntimeError(
            "Figure-package selection drift: "
            f"expected={expected_stems}, actual={actual_stems}"
        )

    availability = [
        {
            "granularity": granularity,
            "model_variant": _strategy_label(strategy),
            "status": (
                "available"
                if granularity == "H" and strategy in {"price_insensitive", "perfect_foresight_D"}
                else "not_run"
            ),
        }
        for granularity in GRANULARITY_ORDER
        for strategy in STRATEGY_ORDER
    ]
    _write_csv(tables / "reporting-availability.csv", availability)
    manifest = {
        "package_version": PACKAGE_VERSION,
        "selection_policy": "default_complete_selection_unless_explicit_subset_requested",
        "regime": regime,
        "figure_files": paths,
        "figure_count": len(paths) // 2,
        "formats": ["png_300_dpi", "svg"],
        "pdf_duplicates_created": False,
        "support": {
            "period": "one high-volatility example week",
            "granularities_solved": ["H"],
            "qh_style_implemented_but_not_run": True,
            "strategies_solved": ["price_insensitive", "perfect_foresight_D"],
            "dam_only_status": "not_run",
            "mfrr_status": "not_run",
            "common_support": True,
            "market_scope": "none",
        },
        "style_contract": {
            "human_readable_labels_and_units": True,
            "legends_right_of_axes": True,
            "titles_separated_for_cropping": True,
            "time_axes_end_at_last_observation": True,
            "heatmap_palette": "muted_blue_cream_red_with_cell_separators",
            "site_load_total_line": "black",
            "standalone_site_load_omitted": "already_present_in_dashboards",
            "continuous_plant_price_panel": "day_ahead_price_above_capacity_panels",
            "dashboard_process_panels": "configuration_primary_load_plus_bf6_plus_kgf1",
            "storage_hot_iron_panel": "excluded_short_term_inventory",
            "stacked_column_order": "descending_largest_at_base",
            "emissions_data_labels": "segment_when_readable_and_total",
            "dri_buffer_unit": "percent_of_capacity",
            "eaf_load_shape": (
                "pure_arc_15_minute_states_on_5_minute_display_grid"
                if eaf_arc_five_minute is not None
                else "pure_arc_at_available_run_resolution"
            ),
            "eaf_explanatory_footer": "omitted",
            "hsm_dashboard_shape": "hourly_step_campaign_load",
            "cost_hierarchy_visual": "parent_aligned_nested_ring_sunburst",
            "cost_hierarchy_outer_denominator": "within_parent_category",
            "plant_capacity_bounds": "resolved_run_contract_with_legacy_fallback",
        },
    }
    resolved_settings = {
        **settings,
        "resolved_for_run": str(output),
        "resolved_plant_bounds": {
            configuration: {
                plant: {"minimum": bounds[0], "maximum": bounds[1]}
                for plant, bounds in plants.items()
            }
            for configuration, plants in plant_bounds.items()
        },
        "generated_figure_stems": actual_stems,
    }
    _write_json(
        output / "resolved_figure_package_settings.json",
        resolved_settings,
    )
    _write_json(output / "figure_package_manifest.json", manifest)
    run_manifest_path = output / "run_manifest.json"
    if run_manifest_path.exists():
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        run_manifest["figure_package_version"] = PACKAGE_VERSION
        run_manifest["figure_count"] = manifest["figure_count"]
        _write_json(run_manifest_path, run_manifest)
    return manifest


__all__ = [
    "FIGURE_PACKAGE_CONFIG",
    "PACKAGE_VERSION",
    "generate_deterministic_figure_package",
]
