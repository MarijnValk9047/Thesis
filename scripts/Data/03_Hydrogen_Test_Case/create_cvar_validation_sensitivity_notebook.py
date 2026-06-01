from __future__ import annotations

import argparse
import json
import shutil
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


def build_notebook_payload(run_dir: Path) -> dict:
    run_dir_str = str(run_dir.resolve()).replace("\\", "/")
    cells = [
        markdown_cell(
            "# CVaR Validation Sensitivity Analysis\n\n"
            "Scope:\n"
            "- hourly\n"
            "- D-only\n"
            "- DA-only\n"
            "- validation-only\n"
            "- common partial support\n"
            "- three thesis-grade scenario artifacts\n\n"
            "This notebook reads a completed Phase D2 run folder. It does **not** rerun MILPs."
        ),
        markdown_cell(
            "## A. Scope and methodology\n\n"
            "- validation-only gamma sensitivity\n"
            "- alpha fixed at 0.95\n"
            "- gamma grid fixed before inspecting test weeks\n"
            "- no test-week tuning\n"
            "- price-insensitive benchmark included\n"
            "- perfect foresight is an oracle upper bound if present"
        ),
        code_cell(
            "from pathlib import Path\n"
            "import json\n"
            "import sys\n"
            "import pandas as pd\n"
            "from IPython.display import display, Markdown, Image\n\n"
            "repo_root = Path.cwd()\n"
            "while repo_root.name != 'Thesis' and repo_root.parent != repo_root:\n"
            "    repo_root = repo_root.parent\n"
            "if str(repo_root) not in sys.path:\n"
            "    sys.path.insert(0, str(repo_root))\n\n"
            f"RUN_DIR = Path(r'{run_dir_str}')\n"
            "NOTEBOOK_INPUTS = RUN_DIR / 'notebook_inputs'\n"
            "FIGURES_DIR = RUN_DIR / 'figures'\n"
            "selected_weeks = pd.read_csv(NOTEBOOK_INPUTS / 'selected_weeks_manifest_table.csv')\n"
            "support_days = pd.read_csv(NOTEBOOK_INPUTS / 'support_days.csv')\n"
            "daily_metrics = pd.read_csv(NOTEBOOK_INPUTS / 'daily_metrics.csv')\n"
            "weekly_metrics = pd.read_csv(NOTEBOOK_INPUTS / 'weekly_metrics.csv')\n"
            "cvar_frontier_week = pd.read_csv(NOTEBOOK_INPUTS / 'cvar_frontier_by_model_week.csv')\n"
            "cvar_frontier_agg = pd.read_csv(NOTEBOOK_INPUTS / 'cvar_frontier_aggregated.csv')\n"
            "gamma_policy = pd.read_csv(NOTEBOOK_INPUTS / 'gamma_policy_candidate_summary.csv')\n"
            "benchmark_metrics = pd.read_csv(NOTEBOOK_INPUTS / 'benchmark_metrics.csv')\n"
            "perfect_foresight_metrics = pd.read_csv(NOTEBOOK_INPUTS / 'perfect_foresight_metrics.csv') if (NOTEBOOK_INPUTS / 'perfect_foresight_metrics.csv').exists() else pd.DataFrame()\n"
            "cvar_validation_checks = pd.read_csv(NOTEBOOK_INPUTS / 'cvar_validation_checks.csv')\n"
            "validation_checks = pd.read_csv(NOTEBOOK_INPUTS / 'validation_checks_all_runs.csv')\n"
        ),
        markdown_cell("## B. Validation weeks"),
        code_cell("display(selected_weeks[['week_label', 'delivery_start_date', 'delivery_end_date', 'regime_label', 'selection_reason']])"),
        markdown_cell(
            "## C. Scenario and forecast context\n\n"
            "Point forecasts are shown only if the saved artifacts contain them. Otherwise, the scenario median should be read as a scenario median, not as a deterministic forecast."
        ),
        code_cell(
            "for week_label in selected_weeks['week_label'].tolist():\n"
            "    for model_label in weekly_metrics['model_label'].astype(str).unique().tolist():\n"
            "        fig_path = FIGURES_DIR / f\"fig_validation_price_scenario_fan_{week_label}_{model_label.lower().replace(' ', '_')}.png\"\n"
            "        if fig_path.exists():\n"
            "            display(Markdown(f'### {week_label} | {model_label}'))\n"
            "            display(Image(filename=str(fig_path)))"
        ),
        markdown_cell("## D. CVaR sensitivity tables"),
        code_cell("display(weekly_metrics[['week_label', 'model_label', 'cvar_gamma', 'expected_adjusted_profit', 'realised_adjusted_profit', 'cvar_loss', 'cvar_tail_profit', 'stochastic_minus_benchmark_profit', 'perfect_foresight_profit', 'value_captured_vs_perfect_foresight', 'shortfall_kg', 'clearing_ratio', 'high_bid_share']].round(3))"),
        code_cell("display(cvar_frontier_agg.round(3))"),
        code_cell("display(gamma_policy.round(3))"),
        markdown_cell("## E. Risk-return figures"),
        code_cell(
            "for figure_name in [\n"
            "    'fig_risk_return_frontier_by_model.png',\n"
            "    'fig_gamma_vs_realised_profit_by_model_week.png',\n"
            "    'fig_gamma_vs_cvar_tail_profit_by_model_week.png',\n"
            "    'fig_gamma_vs_shortfall_by_model_week.png',\n"
            "    'fig_gamma_vs_clearing_ratio_by_model_week.png',\n"
            "    'fig_value_captured_vs_perfect_foresight.png',\n"
            "    'fig_gamma_policy_summary.png',\n"
            "]:\n"
            "    path = FIGURES_DIR / figure_name\n"
            "    if path.exists():\n"
            "        display(Markdown(f'### {figure_name}'))\n"
            "        display(Image(filename=str(path)))"
        ),
        markdown_cell("## F. Bidding behaviour figures"),
        code_cell(
            "for week_label in selected_weeks['week_label'].tolist():\n"
            "    for model_label in weekly_metrics['model_label'].astype(str).unique().tolist():\n"
            "        path = FIGURES_DIR / f\"fig_bid_firmness_by_gamma_{week_label}_{model_label.lower().replace(' ', '_')}.png\"\n"
            "        if path.exists():\n"
            "            display(Markdown(f'### {week_label} | {model_label}'))\n"
            "            display(Image(filename=str(path)))"
        ),
        markdown_cell("## G. Example-day operational behaviour"),
        code_cell(
            "example_figures = sorted(FIGURES_DIR.glob('fig_example_day_operation_*.png'))\n"
            "for path in example_figures:\n"
            "    display(Markdown(f'### {path.name}'))\n"
            "    display(Image(filename=str(path)))"
        ),
        markdown_cell("## H. Benchmark comparison"),
        code_cell("display(benchmark_metrics.round(3).head(20))"),
        code_cell("display(perfect_foresight_metrics.round(3).head(20)) if not perfect_foresight_metrics.empty else display(Markdown('Perfect foresight not included in this run.'))"),
        markdown_cell(
            "## I. Interpretation\n\n"
            "Use the tables and figures in this order:\n"
            "1. check scenario-fan containment by week and model;\n"
            "2. compare realised profit, tail-profit, and shortfall across gamma;\n"
            "3. trace any economic change back to bid firmness, clearing, and physical fulfilment;\n"
            "4. treat perfect foresight only as an upper bound;\n"
            "5. freeze any Phase E gamma set from validation evidence only."
        ),
        markdown_cell("## Validation and limitations"),
        code_cell("display(cvar_validation_checks)"),
        code_cell("display(validation_checks.groupby(['check_name', 'status'], as_index=False).size())"),
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
    parser = argparse.ArgumentParser(description="Create the Phase D2 CVaR validation sensitivity notebook from a completed run folder.")
    parser.add_argument("--run-dir", required=True, help="Path to the completed Phase D2 run folder.")
    parser.add_argument(
        "--output-path",
        default="scripts/Data/03_Hydrogen_Test_Case/notebooks/11_cvar_validation_sensitivity_analysis.ipynb",
        help="Notebook path to write.",
    )
    parser.add_argument(
        "--copy-to-run-dir",
        action="store_true",
        help="Also copy the notebook into <run-dir>/notebook_exports/.",
    )
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    output_path = Path(args.output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_notebook_payload(run_dir)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.copy_to_run_dir:
        export_dir = run_dir / "notebook_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_path, export_dir / output_path.name)
    print(output_path)


if __name__ == "__main__":
    main()
