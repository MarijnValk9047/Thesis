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
            "# LEAR FS3 Fine-Gamma Diagnostic\n\n"
            "Scope:\n"
            "- hourly\n"
            "- D-only\n"
            "- DA-only\n"
            "- validation-only\n"
            "- LEAR FS3 only\n"
            "- no scenario or probability changes\n\n"
            "This notebook reads a completed Phase D3 run folder. It does **not** rerun MILPs."
        ),
        markdown_cell(
            "## Scope and reason\n\n"
            "- test whether the CVaR response starts below gamma = 0.05\n"
            "- identify whether the response is a true bid change or just a weak objective perturbation\n"
            "- use validation weeks only\n"
            "- keep scenarios, probabilities, and formulation fixed"
        ),
        code_cell(
            "from pathlib import Path\n"
            "import pandas as pd\n"
            "from IPython.display import display, Markdown, Image\n\n"
            f"RUN_DIR = Path(r'{run_dir_str}')\n"
            "NOTEBOOK_INPUTS = RUN_DIR / 'notebook_inputs'\n"
            "FIGURES_DIR = RUN_DIR / 'figures'\n"
            "selected_weeks = pd.read_csv(NOTEBOOK_INPUTS / 'selected_weeks_manifest_table.csv')\n"
            "support_days = pd.read_csv(NOTEBOOK_INPUTS / 'support_days.csv')\n"
            "daily = pd.read_csv(NOTEBOOK_INPUTS / 'cvar_fine_gamma_daily.csv')\n"
            "weekly = pd.read_csv(NOTEBOOK_INPUTS / 'cvar_fine_gamma_weekly.csv')\n"
            "agg = pd.read_csv(NOTEBOOK_INPUTS / 'cvar_fine_gamma_aggregated.csv')\n"
            "bid_diff = pd.read_csv(NOTEBOOK_INPUTS / 'bid_difference_by_gamma.csv')\n"
            "tail_diag = pd.read_csv(NOTEBOOK_INPUTS / 'tail_scenario_diagnostics.csv')\n"
            "daily_matrix = pd.read_csv(NOTEBOOK_INPUTS / 'daily_gamma_sensitivity_matrix.csv')\n"
            "benchmark = pd.read_csv(NOTEBOOK_INPUTS / 'benchmark_metrics.csv')\n"
            "perfect_foresight = pd.read_csv(NOTEBOOK_INPUTS / 'perfect_foresight_metrics.csv') if (NOTEBOOK_INPUTS / 'perfect_foresight_metrics.csv').exists() else pd.DataFrame()\n"
            "validation_checks = pd.read_csv(NOTEBOOK_INPUTS / 'validation_checks_all_runs.csv')\n"
            "cvar_checks = pd.read_csv(NOTEBOOK_INPUTS / 'cvar_validation_checks.csv')\n"
        ),
        markdown_cell("## Validation weeks"),
        code_cell("display(selected_weeks[['week_label', 'delivery_start_date', 'delivery_end_date', 'regime_label', 'selection_reason']])"),
        markdown_cell("## Aggregate gamma response"),
        code_cell("display(agg.round(6))"),
        markdown_cell("## Daily gamma response"),
        code_cell("display(daily_matrix.round(6))"),
        markdown_cell("## Bid-difference diagnostics"),
        code_cell("display(bid_diff.round(9))"),
        markdown_cell("## Tail-scenario diagnostics"),
        code_cell("display(tail_diag[['week_label', 'delivery_day', 'cvar_gamma', 'number_of_unique_scenario_profits', 'worst_scenario_profit', 'worst_scenario_probability_mass', 'cvar_tail_probability_mass', 'number_of_tail_scenarios', 'whether_tail_scenarios_change_vs_previous_gamma', 'whether_worst_scenario_changes_vs_previous_gamma']].round(6))"),
        markdown_cell("## Figures"),
        code_cell(
            "for figure_name in [\n"
            "    'fig_fine_gamma_realised_profit.png',\n"
            "    'fig_fine_gamma_cvar_tail_profit.png',\n"
            "    'fig_fine_gamma_worst_scenario_profit.png',\n"
            "    'fig_fine_gamma_clearing_ratio.png',\n"
            "    'fig_fine_gamma_rejected_energy.png',\n"
            "    'fig_fine_gamma_bid_difference_vs_gamma0.png',\n"
            "    'fig_fine_gamma_shortfall.png',\n"
            "    'fig_fine_gamma_risk_return_frontier.png',\n"
            "    'fig_daily_gamma_heatmap_realised_profit.png',\n"
            "    'fig_daily_gamma_heatmap_bid_difference.png',\n"
            "]:\n"
            "    path = FIGURES_DIR / figure_name\n"
            "    if path.exists():\n"
            "        display(Markdown(f'### {figure_name}'))\n"
            "        display(Image(filename=str(path)))"
        ),
        markdown_cell("## Benchmarks"),
        code_cell("display(benchmark.round(6).head(30))"),
        code_cell("display(perfect_foresight.round(6).head(30)) if not perfect_foresight.empty else display(Markdown('Perfect foresight not included.'))"),
        markdown_cell(
            "## Conclusion prompt\n\n"
            "Use the saved diagnostics in this order:\n"
            "1. inspect `mean_total_abs_bid_quantity_difference_mwh_vs_gamma0` to see when bids actually move;\n"
            "2. compare realised profit and CVaR tail profit at the same gamma;\n"
            "3. check whether the tail scenario set itself changes across adjacent gamma values;\n"
            "4. retain only gamma values that add information beyond the plateau."
        ),
        markdown_cell("## Validation status"),
        code_cell("display(cvar_checks)"),
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
    parser = argparse.ArgumentParser(description="Create the Phase D3 LEAR FS3 fine-gamma notebook from a completed run folder.")
    parser.add_argument("--run-dir", required=True, help="Path to the completed Phase D3 run folder.")
    parser.add_argument(
        "--output-path",
        default="scripts/Data/03_Hydrogen_Test_Case/notebooks/12_fine_gamma_lear_fs3_diagnostic.ipynb",
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
