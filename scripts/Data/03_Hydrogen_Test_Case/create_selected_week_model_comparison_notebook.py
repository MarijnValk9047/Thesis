from __future__ import annotations

import argparse
import json
from pathlib import Path


def markdown_cell(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": [line + ("\n" if not line.endswith("\n") else "") for line in source.splitlines()],
    }


def code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [line + ("\n" if not line.endswith("\n") else "") for line in source.splitlines()],
    }


def build_notebook_payload(suite_dir: Path) -> dict:
    suite_str = str(suite_dir.resolve()).replace("\\", "/")
    cells = [
        markdown_cell(
            "# Selected-Week Model Comparison\n\n"
            "Scope:\n"
            "- hourly\n"
            "- D-only\n"
            "- DA-only stochastic bidding\n"
            "- risk-neutral only\n\n"
            "This notebook reads a completed selected-week suite output folder. It does **not** rerun the MILPs.\n\n"
            "Selected weeks are diagnostic support statements, not an unbiased full-period evaluation."
        ),
        markdown_cell(
            "## Artifacts\n\n"
            "Main comparison target:\n"
            "1. LEAR Strict\n"
            "2. LEAR FS3 pruned candidate\n"
            "3. XGBoost FS3 pruned candidate\n\n"
            "If the loaded suite contains fewer models, that reflects an upstream support or provenance blocker rather than notebook filtering."
        ),
        code_cell(
            "from pathlib import Path\n"
            "import sys\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "import matplotlib.pyplot as plt\n"
            "from IPython.display import display, Markdown\n\n"
            "repo_root = Path.cwd()\n"
            "while repo_root.name != 'Thesis' and repo_root.parent != repo_root:\n"
            "    repo_root = repo_root.parent\n"
            "if str(repo_root) not in sys.path:\n"
            "    sys.path.insert(0, str(repo_root))\n\n"
            "try:\n"
            "    from visual_style import MODEL_COLORS, STRATEGY_COLORS, apply_visual_style\n"
            "    apply_visual_style()\n"
            "except Exception:\n"
            "    MODEL_COLORS = {\n"
            "        'LEAR Strict': '#C97941',\n"
            "        'LEAR FS3 pruned candidate': '#3A7D7C',\n"
            "        'XGBoost FS3 pruned candidate': '#1F4E79',\n"
            "        'Price insensitive benchmark': '#333333',\n"
            "    }\n"
            "    STRATEGY_COLORS = {'price_insensitive': '#333333'}\n\n"
            "MODEL_ORDER = ['LEAR Strict', 'LEAR FS3 pruned candidate', 'XGBoost FS3 pruned candidate']\n"
            "WEEK_ORDER = ['high_volatility_week', 'stable_summer_week', 'stable_winter_week', 'low_price_week', 'tail_week']\n\n"
            f"SUITE_DIR = Path(r'{suite_str}')\n"
            "NOTEBOOK_INPUTS = SUITE_DIR / 'notebook_inputs'\n"
            "selected_week_registry = pd.read_csv(SUITE_DIR / 'selected_week_registry.csv')\n"
            "daily_metrics = pd.read_csv(SUITE_DIR / 'daily_metrics.csv')\n"
            "weekly_metrics = pd.read_csv(SUITE_DIR / 'weekly_metrics.csv')\n"
            "weekly_metrics_by_model = pd.read_csv(SUITE_DIR / 'weekly_metrics_by_model.csv')\n"
            "benchmark_comparison_daily = pd.read_csv(SUITE_DIR / 'benchmark_comparison_daily.csv')\n"
            "benchmark_comparison_weekly = pd.read_csv(SUITE_DIR / 'benchmark_comparison_weekly.csv')\n"
            "validation_checks = pd.read_csv(SUITE_DIR / 'validation_checks_all_runs.csv')\n"
            "model_stats_daily = pd.read_csv(SUITE_DIR / 'model_stats_daily.csv')\n"
            "scenario_fan_inputs = pd.read_parquet(NOTEBOOK_INPUTS / 'scenario_fan_inputs.parquet') if (NOTEBOOK_INPUTS / 'scenario_fan_inputs.parquet').exists() else pd.DataFrame()\n"
            "redispatch_timeseries = pd.read_parquet(NOTEBOOK_INPUTS / 'actual_redispatch_timeseries_daily.parquet') if (NOTEBOOK_INPUTS / 'actual_redispatch_timeseries_daily.parquet').exists() else pd.DataFrame()\n"
        ),
        markdown_cell(
            "## Method Overview\n\n"
            "Pipeline:\n"
            "`scenario set -> bid optimisation -> actual clearing -> deterministic redispatch -> realised settlement`\n\n"
            "Important market-chain rule:\n"
            "- bid price affects acceptance;\n"
            "- accepted energy is settled at the realised DA market price;\n"
            "- redispatch can only use cleared electricity;\n"
            "- unused cleared energy and shortfall remain explicit in the realised metrics.\n\n"
            "The benchmark is `price_insensitive_plan_first_market_cap`, which uses the same realised delivery day and actual price path."
        ),
        markdown_cell("## Selected Week Registry"),
        code_cell(
            "selected_week_registry"
        ),
        markdown_cell(
            "## Metric Guide\n\n"
            "- `realised_adjusted_profit`: realised hydrogen revenue minus actual DA settlement cost, unused-energy penalty, shortfall penalty, and terminal inventory correction.\n"
            "- `stochastic_minus_benchmark_profit`: realised stochastic profit minus realised price-insensitive benchmark profit.\n"
            "- `clearing_ratio`: cleared energy divided by submitted bid energy.\n"
            "- `rejected_energy_mwh`: submitted energy that did not clear.\n"
            "- `weighted_average_actual_price_paid`: realised DA settlement cost divided by cleared energy.\n"
            "- `hydrogen_compressed_or_sold_kg`: realised hydrogen delivered out of redispatch.\n"
            "- `hydrogen_above_target_kg`: realised hydrogen above the lower-bound daily target.\n"
            "- `target_fulfilment_ratio_capped_for_reliability`: reliability-style fulfilment capped at 1.0.\n"
            "- `shortfall_kg`: unmet daily hydrogen target after redispatch.\n"
            "- `unused_cleared_energy_mwh`: cleared DA electricity that could not be physically used.\n"
            "- `terminal_inventory_correction_eur`: end-of-window inventory adjustment.\n"
            "- `worst_scenario_profit`: worst scenario-side adjusted profit from the bid optimisation step.\n"
            "- `expected_vs_realised_profit_delta`: realised adjusted profit minus the expected stochastic objective."
        ),
        markdown_cell("## Overview Results"),
        code_cell(
            "overview_cols = [\n"
            "    'week_label', 'model_label', 'realised_adjusted_profit',\n"
            "    'price_insensitive_realised_adjusted_profit', 'stochastic_minus_benchmark_profit',\n"
            "    'hydrogen_compressed_or_sold_kg', 'shortfall_kg', 'clearing_ratio',\n"
            "    'weighted_average_actual_price_paid'\n"
            "]\n"
            "overview = weekly_metrics[overview_cols].copy()\n"
            "overview = overview.sort_values([\n"
            "    overview['week_label'].map({label: idx for idx, label in enumerate(WEEK_ORDER)}),\n"
            "    overview['model_label'].map({label: idx for idx, label in enumerate(MODEL_ORDER)})\n"
            "])\n"
            "display(overview.round(2))"
        ),
        code_cell(
            "def plot_week_scenario_fan(week_label: str):\n"
            "    if scenario_fan_inputs.empty:\n"
            "        return\n"
            "    week_frame = scenario_fan_inputs[scenario_fan_inputs['week_label'] == week_label].copy()\n"
            "    models = [label for label in MODEL_ORDER if label in week_frame['model_label'].astype(str).unique().tolist()]\n"
            "    fig, axes = plt.subplots(len(models), 1, figsize=(12, max(3.6, 3.4 * len(models))), sharex=True)\n"
            "    if len(models) == 1:\n"
            "        axes = [axes]\n"
            "    for ax, model_label in zip(axes, models):\n"
            "        model_frame = week_frame[week_frame['model_label'] == model_label].copy()\n"
            "        rows = []\n"
            "        for ts, grp in model_frame.groupby('delivery_start_utc', sort=True):\n"
            "            vals = grp['scenario_price_eur_per_mwh'].astype(float).to_numpy()\n"
            "            probs = grp['scenario_probability'].astype(float).to_numpy()\n"
            "            order = np.argsort(vals)\n"
            "            vals = vals[order]\n"
            "            probs = probs[order]\n"
            "            cum = np.cumsum(probs)\n"
            "            def q(alpha: float) -> float:\n"
            "                idx = min(np.searchsorted(cum, alpha, side='left'), len(vals) - 1)\n"
            "                return float(vals[idx])\n"
            "            rows.append({\n"
            "                'delivery_start_utc': pd.Timestamp(ts),\n"
            "                'q05': q(0.05),\n"
            "                'q50': q(0.50),\n"
            "                'q95': q(0.95),\n"
            "                'actual': float(grp['actual_price_eur_per_mwh'].iloc[0]),\n"
            "            })\n"
            "        quant = pd.DataFrame(rows).sort_values('delivery_start_utc')\n"
            "        color = MODEL_COLORS.get(model_label, '#7A7A7A')\n"
            "        ax.fill_between(quant['delivery_start_utc'], quant['q05'], quant['q95'], alpha=0.22, color=color)\n"
            "        ax.plot(quant['delivery_start_utc'], quant['q50'], color=color, linewidth=1.6, label=f'{model_label} p50')\n"
            "        ax.plot(quant['delivery_start_utc'], quant['actual'], color='#222222', linewidth=1.8, label='Actual price')\n"
            "        ax.set_ylabel('EUR/MWh')\n"
            "        ax.set_title(f'{week_label}: {model_label}')\n"
            "        ax.legend(loc='upper left')\n"
            "    axes[-1].set_xlabel('Delivery hour')\n"
            "    fig.tight_layout()\n"
            "    plt.show()\n\n"
            "def grouped_week_bar(metric: str, ylabel: str, title: str):\n"
            "    frame = weekly_metrics.copy()\n"
            "    weeks = [label for label in WEEK_ORDER if label in frame['week_label'].astype(str).unique().tolist()]\n"
            "    x = np.arange(len(weeks))\n"
            "    width = 0.22\n"
            "    fig, ax = plt.subplots(figsize=(12, 5.2))\n"
            "    present_models = [label for label in MODEL_ORDER if label in frame['model_label'].astype(str).unique().tolist()]\n"
            "    for idx, model_label in enumerate(present_models):\n"
            "        subset = frame[frame['model_label'] == model_label].set_index('week_label').reindex(weeks)\n"
            "        ax.bar(x + (idx - (len(present_models)-1)/2) * width, subset[metric].to_numpy(), width=width, color=MODEL_COLORS.get(model_label, '#7A7A7A'), label=model_label)\n"
            "    ax.set_xticks(x)\n"
            "    ax.set_xticklabels(weeks, rotation=15)\n"
            "    ax.set_ylabel(ylabel)\n"
            "    ax.set_title(title)\n"
            "    ax.legend()\n"
            "    fig.tight_layout()\n"
            "    plt.show()\n"
        ),
        markdown_cell("## Week-by-Week Visual Diagnostics"),
        code_cell(
            "for week_label in selected_week_registry['week_label'].tolist():\n"
            "    display(Markdown(f'### {week_label}'))\n"
            "    week_table = weekly_metrics[weekly_metrics['week_label'] == week_label][[\n"
            "        'model_label', 'realised_adjusted_profit', 'price_insensitive_realised_adjusted_profit',\n"
            "        'stochastic_minus_benchmark_profit', 'clearing_ratio', 'rejected_energy_mwh',\n"
            "        'hydrogen_compressed_or_sold_kg', 'shortfall_kg', 'weighted_average_actual_price_paid'\n"
            "    ]].copy()\n"
            "    display(week_table.round(2))\n"
            "    display(Markdown('Support statement: compare realised DA prices and scenario spread first, then check whether differences come from clearing, price paid, hydrogen delivery, or shortfall.'))\n"
            "    plot_week_scenario_fan(week_label)\n"
            "    grouped_week_bar('realised_adjusted_profit', 'EUR', f'Realised adjusted profit in {week_label}')\n"
            "    grouped_week_bar('clearing_ratio', 'Ratio', f'Clearing ratio in {week_label}')\n"
            "    grouped_week_bar('rejected_energy_mwh', 'MWh', f'Rejected energy in {week_label}')\n"
            "    grouped_week_bar('hydrogen_compressed_or_sold_kg', 'kg', f'Hydrogen compressed/sold in {week_label}')\n"
            "    grouped_week_bar('shortfall_kg', 'kg', f'Shortfall in {week_label}')\n"
            "    grouped_week_bar('weighted_average_actual_price_paid', 'EUR/MWh', f'Average actual price paid in {week_label}')\n"
        ),
        markdown_cell("## Cross-Week Model Comparison"),
        code_cell(
            "pivot = weekly_metrics.pivot(index='week_label', columns='model_label', values='stochastic_minus_benchmark_profit').reindex(WEEK_ORDER)\n"
            "pivot = pivot[[col for col in MODEL_ORDER if col in pivot.columns]]\n"
            "fig, ax = plt.subplots(figsize=(9, 4.8))\n"
            "vals = pivot.to_numpy(dtype=float)\n"
            "image = ax.imshow(vals, aspect='auto', cmap='RdYlGn')\n"
            "ax.set_xticks(range(len(pivot.columns)))\n"
            "ax.set_xticklabels(list(pivot.columns), rotation=20, ha='right')\n"
            "ax.set_yticks(range(len(pivot.index)))\n"
            "ax.set_yticklabels(list(pivot.index))\n"
            "for i in range(vals.shape[0]):\n"
            "    for j in range(vals.shape[1]):\n"
            "        if np.isfinite(vals[i, j]):\n"
            "            ax.text(j, i, f'{vals[i, j]:.0f}', ha='center', va='center', fontsize=8)\n"
            "fig.colorbar(image, ax=ax, label='Stochastic - benchmark profit (EUR)')\n"
            "ax.set_title('Cross-week stochastic uplift heatmap')\n"
            "fig.tight_layout()\n"
            "plt.show()\n\n"
            "grouped_week_bar('realised_adjusted_profit', 'EUR', 'Realised adjusted profit by week and model')\n\n"
            "scatter = weekly_metrics[['model_label', 'actual_price_spread', 'stochastic_minus_benchmark_profit']].copy()\n"
            "fig, ax = plt.subplots(figsize=(8.5, 5.0))\n"
            "for model_label, grp in scatter.groupby('model_label'):\n"
            "    ax.scatter(grp['actual_price_spread'], grp['stochastic_minus_benchmark_profit'], label=model_label, color=MODEL_COLORS.get(model_label, '#7A7A7A'), s=60)\n"
            "ax.axhline(0.0, color='#333333', linewidth=1.0)\n"
            "ax.set_xlabel('Weekly actual price spread (EUR/MWh)')\n"
            "ax.set_ylabel('Stochastic - benchmark profit (EUR)')\n"
            "ax.set_title('Does wider realised spread coincide with stochastic uplift?')\n"
            "ax.legend()\n"
            "fig.tight_layout()\n"
            "plt.show()\n\n"
            "display(model_stats_daily.groupby('model_label')[['solve_time_seconds', 'variables', 'binaries', 'constraints', 'scenario_count']].agg(['mean', 'max']).round(2))"
        ),
        markdown_cell(
            "## Interpretation\n\n"
            "Use the figures in this order:\n"
            "1. compare actual prices and each model’s scenario fan;\n"
            "2. compare realised profit versus the price-insensitive benchmark;\n"
            "3. check whether the difference came from clearing ratio, rejected energy, price paid, hydrogen delivery, or shortfall;\n"
            "4. keep the selected-week caveat explicit.\n\n"
            "Selected weeks can show mechanism and failure modes. They are not a claim about representative average performance over the full evaluation period."
        ),
        markdown_cell(
            "## Validation and Limitations\n\n"
            "- hard validation checks should be read from `validation_checks_all_runs.csv`;\n"
            "- submitted bids are non-anticipative and contain no `scenario_id`;\n"
            "- clearing is pay-as-cleared against realised DA prices;\n"
            "- redispatch respects `used + unused = cleared`;\n"
            "- no mFRR, no quarter-hour, and no CVaR were included in this selected-week suite;\n"
            "- if LEAR Strict is missing from the loaded suite, that indicates a common-support blocker in the artifact coverage, not a notebook omission.\n"
        ),
        code_cell(
            "validation_summary = validation_checks.groupby(['status']).size().rename('count').reset_index()\n"
            "display(validation_summary)\n"
            "display(validation_checks.head())"
        ),
    ]

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.x"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the selected-week model-comparison notebook from a completed suite.")
    parser.add_argument("--suite-dir", required=True, help="Path to the completed selected-week suite output folder.")
    parser.add_argument(
        "--output-path",
        default="scripts/Data/03_Hydrogen_Test_Case/notebooks/10_selected_week_model_comparison.ipynb",
        help="Notebook path to write.",
    )
    args = parser.parse_args()
    suite_dir = Path(args.suite_dir).resolve()
    if not suite_dir.exists():
        raise FileNotFoundError(f"Suite directory not found: {suite_dir}")
    output_path = Path(args.output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_notebook_payload(suite_dir)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
