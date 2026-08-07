"""Four-example-week deterministic C0/C1 reporting orchestration."""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib.pyplot as plt
import pandas as pd
import yaml

from visual_style import COLORS, apply_visual_style, save_figure

from .s4_4c6_deterministic_c0_temporal_validation import (
    CONFIG_PATH,
    REPO_ROOT,
    load_c0_validation_config,
    run_c0_temporal_validation,
)


STRATEGIES = ("price_insensitive", "perfect_foresight_D")
STRATEGY_LABELS = {
    "price_insensitive": "Price insensitive",
    "perfect_foresight_D": "Perfect Foresight",
}
WEEK_LABELS = {
    "typical_winter": "Typical winter",
    "high_prices": "High prices",
    "high_volatility": "High volatility",
    "typical_summer": "Typical summer",
}
CENTRAL_PRICES = {
    "natural_gas_eur_per_mwh": 55.0,
    "coking_coal_eur_per_t": 205.0,
    "pci_coal_eur_per_t": 145.0,
    "imported_bf_pellets_eur_per_t": 140.0,
    "imported_drp_pellets_eur_per_t": 180.0,
}
METRICS = (
    ("total_production_cost_eur", "Total production cost", "EUR"),
    ("steel_produced_t", "Steel produced", "t"),
    ("electricity_consumed_mwh", "Electricity consumed", "MWh"),
    ("average_electricity_price_paid_eur_per_mwh", "Average electricity price", "EUR/MWh"),
    ("total_electricity_cost_eur", "Total electricity cost", "EUR"),
    ("total_ng_cost_eur", "Total NG cost", "EUR"),
    ("total_coal_cost_eur", "Total coal cost", "EUR"),
    ("total_imported_pellets_cost_eur", "Imported pellets cost", "EUR"),
    ("emissions_tco2", "Emissions", "tCO2"),
)


class FourWeekReportingError(RuntimeError):
    """Raised when a governed four-week report cannot be completed."""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _economic_record(
    data: pd.DataFrame,
    *,
    configuration: str,
    strategy: str,
    regime: str,
    represented_objective: float,
) -> dict[str, Any]:
    grid_mwh = float(data["net_grid_import_mwh"].sum())
    generation_mwh = float(data["internal_generation_mwh"].sum())
    electricity_cost = float(
        (
            data["net_grid_import_mwh"]
            * data["electricity_price_eur_per_mwh"]
        ).sum()
    )
    bf_pellet_cost = float(data["external_bf_pellets_to_bf_t"].sum()) * CENTRAL_PRICES[
        "imported_bf_pellets_eur_per_t"
    ]
    drp_pellet_cost = float(data["external_dr_pellets_to_drp_t"].sum()) * CENTRAL_PRICES[
        "imported_drp_pellets_eur_per_t"
    ]
    total_production_cost = represented_objective
    steel_t = float(data["final_product_t"].sum())
    return {
        "configuration": configuration,
        "week": regime,
        "week_label": WEEK_LABELS[regime],
        "strategy_id": strategy,
        "strategy_label": STRATEGY_LABELS[strategy],
        "represented_procurement_objective_eur": represented_objective,
        "total_production_cost_eur": total_production_cost,
        "steel_produced_t": steel_t,
        "steel_production_cost_eur_per_t": total_production_cost / steel_t,
        "electricity_consumed_mwh": grid_mwh + generation_mwh,
        "grid_electricity_purchased_mwh": grid_mwh,
        "average_electricity_price_paid_eur_per_mwh": (
            electricity_cost / grid_mwh if grid_mwh > 0.0 else 0.0
        ),
        "total_electricity_cost_eur": electricity_cost,
        "total_ng_cost_eur": float(
            data["total_named_ng_procurement_mwh"].sum()
        )
        * CENTRAL_PRICES["natural_gas_eur_per_mwh"],
        "total_coal_cost_eur": (
            float(data["coking_coal_input_t"].sum())
            * CENTRAL_PRICES["coking_coal_eur_per_t"]
            + float(data["pci_input_t"].sum())
            * CENTRAL_PRICES["pci_coal_eur_per_t"]
        ),
        "total_imported_pellets_cost_eur": bf_pellet_cost + drp_pellet_cost,
        "emissions_tco2": float(data["direct_co2_reporting_t"].sum()),
        "cost_boundary": (
            "represented_procurement_objective_with_origin_tagged_external_"
            "BF_and_DR_pellets"
        ),
        "average_price_denominator": "purchased_grid_MWh",
    }


def _economic_rows(
    child_runs: Mapping[str, Path],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for regime, child in child_runs.items():
        dispatch = pd.read_csv(child / "interval_dispatch.csv")
        objectives = {
            (str(row["configuration"]), str(row["strategy_id"])): float(
                row["objective_eur"]
            )
            for row in csv.DictReader(
                (child / "economic_comparison.csv").open(encoding="utf-8")
            )
        }
        for (configuration, strategy), data in dispatch.groupby(
            ["configuration", "strategy_id"], sort=True
        ):
            base = _economic_record(
                data,
                configuration=str(configuration),
                strategy=str(strategy),
                regime=regime,
                represented_objective=objectives[(configuration, strategy)],
            )
            # H is an exact aggregation of QH output, not a separate optimisation.
            for granularity in ("QH", "H"):
                rows.append({**base, "reporting_granularity": granularity})
    return rows


def _format_value(value: float, unit: str) -> str:
    if unit == "EUR":
        return f"{value / 1_000_000:.2f}m"
    if unit == "MWh":
        return f"{value / 1_000:.1f}k"
    if unit in {"t", "tCO2"}:
        return f"{value / 1_000:.1f}k"
    return f"{value:.2f}"


def _configuration_table(
    rows: pd.DataFrame,
    configuration: str,
    output: Path,
) -> None:
    qh = rows[
        (rows["configuration"] == configuration)
        & (rows["reporting_granularity"] == "QH")
    ]
    columns = [
        (week, strategy)
        for week in WEEK_LABELS
        for strategy in STRATEGIES
    ]
    csv_rows: list[dict[str, Any]] = []
    cell_text: list[list[str]] = []
    row_labels: list[str] = []
    for metric, label, unit in METRICS:
        record: dict[str, Any] = {"parameter": label, "unit": unit}
        cells: list[str] = []
        for week, strategy in columns:
            value = float(
                qh[(qh["week"] == week) & (qh["strategy_id"] == strategy)][
                    metric
                ].iloc[0]
            )
            key = f"{week}__{strategy}"
            record[key] = value
            cells.append(_format_value(value, unit))
        csv_rows.append(record)
        row_labels.append(f"{label} [{unit}]")
        cell_text.append(cells)
    _write_csv(output / f"{configuration.lower()}_weekly_economic_table.csv", csv_rows)

    fig, axis = plt.subplots(figsize=(18, 7))
    axis.axis("off")
    column_labels = [
        f"{WEEK_LABELS[week]}\n{STRATEGY_LABELS[strategy]}"
        for week, strategy in columns
    ]
    table = axis.table(
        cellText=cell_text,
        rowLabels=row_labels,
        colLabels=column_labels,
        cellLoc="right",
        rowLoc="left",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.0, 1.55)
    axis.set_title(
        f"{configuration} economic and operational results by example week",
        pad=18,
    )
    save_figure(
        fig,
        output / "figures" / f"{configuration.lower()}-weekly-economic-table",
        save_pdf=False,
    )
    plt.close(fig)


def _grouped_qh_h_chart(rows: pd.DataFrame, output: Path) -> None:
    apply_visual_style()
    metrics = (
        ("steel_production_cost_eur_per_t", "Steel production cost", "EUR/t"),
        ("total_electricity_cost_eur", "Total electricity cost", "EUR/week"),
        (
            "average_electricity_price_paid_eur_per_mwh",
            "Average electricity price paid",
            "EUR/MWh",
        ),
    )
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    width = 0.34
    x = [0.0, 1.0]
    colors = (COLORS["benchmark"], COLORS["main_model"])
    for row_index, configuration in enumerate(("C0", "C1")):
        for column_index, (metric, title, unit) in enumerate(metrics):
            axis = axes[row_index, column_index]
            for strategy_index, strategy in enumerate(STRATEGIES):
                means: list[float] = []
                errors_low: list[float] = []
                errors_high: list[float] = []
                for granularity in ("QH", "H"):
                    values = rows[
                        (rows["configuration"] == configuration)
                        & (rows["strategy_id"] == strategy)
                        & (rows["reporting_granularity"] == granularity)
                    ][metric].astype(float)
                    mean = float(values.mean())
                    means.append(mean)
                    errors_low.append(mean - float(values.min()))
                    errors_high.append(float(values.max()) - mean)
                offsets = [item + (strategy_index - 0.5) * width for item in x]
                axis.bar(
                    offsets,
                    means,
                    width=width,
                    label=STRATEGY_LABELS[strategy],
                    color=colors[strategy_index],
                    yerr=[errors_low, errors_high],
                    capsize=3,
                )
            axis.set_xticks(x, ("QH", "H"))
            axis.set_ylabel(unit)
            axis.set_title(f"{configuration} — {title}")
            if row_index == 0 and column_index == 0:
                axis.legend()
    fig.suptitle(
        "Four-week mean by reporting granularity; whiskers show week range"
    )
    fig.tight_layout()
    save_figure(
        fig,
        output / "figures" / "qh-h-grouped-economic-comparison",
        save_pdf=False,
    )
    plt.close(fig)


def run_four_week_reporting(
    *,
    config_path: str | Path = CONFIG_PATH,
    run_id: str = "c0_c1_four_example_weeks_v1",
) -> dict[str, Any]:
    config = load_c0_validation_config(config_path)
    contract = config["four_week_run_contract"]
    output = REPO_ROOT / config["output_root"] / run_id
    if output.exists() and any(output.iterdir()):
        raise FourWeekReportingError(f"Refusing to overwrite {output}.")
    output.mkdir(parents=True, exist_ok=True)
    (output / "figures").mkdir(exist_ok=True)
    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest = {
        "run_id": run_id,
        **contract,
        "output_root": str(output.relative_to(REPO_ROOT)),
        "git_head": git_head,
        "git_dirty_at_run": True,
        "presentation_denominator": config["presentation_contract"][
            "headline_denominator"
        ],
    }
    _write_json(output / "run_manifest.json", manifest)
    (output / "resolved_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=True), encoding="utf-8"
    )
    _write_json(
        output / "code_version.json",
        {"git_head": git_head, "git_dirty_at_run": True},
    )

    child_runs: dict[str, Path] = {}
    child_summaries: dict[str, Any] = {}
    for regime in contract["regimes"]:
        child_id = f"{run_id}/children/{regime}"
        summary = run_c0_temporal_validation(
            config_path=config_path,
            run_id=child_id,
            week_regime=str(regime),
        )
        child = REPO_ROOT / config["output_root"] / child_id
        child_runs[str(regime)] = child
        child_summaries[str(regime)] = summary

    economic_rows = _economic_rows(child_runs)
    _write_csv(output / "four_week_economic_metrics_long.csv", economic_rows)
    frame = pd.DataFrame(economic_rows)
    _configuration_table(frame, "C0", output)
    _configuration_table(frame, "C1", output)
    _grouped_qh_h_chart(frame, output)

    all_pass = all(
        item["decision"] == "c0_example_week_behaviour_pass_anchor_coverage_partial"
        for item in child_summaries.values()
    )
    summary = {
        "decision": (
            "c0_c1_four_example_weeks_pass_anchor_coverage_partial"
            if all_pass
            else "needs_bounded_fix"
        ),
        "weeks_completed": len(child_runs),
        "child_runs": {
            key: str(path.relative_to(REPO_ROOT)) for key, path in child_runs.items()
        },
        "strategies": list(STRATEGIES),
        "reporting_granularities": ["QH", "H"],
        "qh_h_semantics": "H_is_postsolve_aggregation_of_QH_not_separate_model",
        "aggregate_figures": 3,
        "full_four_week_market_matrix_authorized": False,
    }
    _write_json(output / "run_summary.json", summary)
    _write_json(output / "gate_decision.json", summary)
    _write_json(
        output / "input_manifest.json",
        {
            "representative_week_source": config["behaviour_validation_config"],
            "child_runs": summary["child_runs"],
            "central_reporting_prices": CENTRAL_PRICES,
        },
    )
    _write_json(
        output / "registry_entry.json",
        {
            "run_id": run_id,
            "decision": summary["decision"],
            "run_class": contract["run_class"],
            "lineage_role": contract["lineage_role"],
            "git_eligible": False,
        },
    )
    (output / "warnings_and_limitations.md").write_text(
        "# Warnings and limitations\n\n"
        "- These are four selected example weeks, not a continuous four-week episode or representative year.\n"
        "- H is an aggregation of the QH solution and therefore preserves all economic totals exactly.\n"
        "- Total production cost is the represented procurement objective plus one reporting valuation for imported BF pellets, which are physical but objective-inactive.\n"
        "- Average electricity price paid is weighted by purchased grid MWh, not total site electricity consumption.\n"
        "- Emissions are the represented direct-CO2 boundary and are not an ETS-ready full-site Scope 1 total.\n"
        "- No DAM bidding, mFRR, stochastic, S10 or four-week market matrix was run.\n",
        encoding="utf-8",
    )
    return summary
