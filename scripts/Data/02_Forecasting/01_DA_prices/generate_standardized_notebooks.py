from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path


NOTEBOOK_ROOT = Path("notebooks/Data/02_Forecasting/01_DA_prices")
# These notebooks are maintained by their dedicated creation scripts and must not be
# archived or overwritten by the standardized notebook generator.
PROTECTED_NOTEBOOK_FILENAMES = {
    "01_da_prices_cleaning_walkthrough.ipynb",
    "03_endogenous_explicit_features.ipynb",
}


def markdown_cell(text: str) -> dict[str, object]:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": [line if line.endswith("\n") else f"{line}\n" for line in text.splitlines()],
    }


def code_cell(text: str) -> dict[str, object]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [line if line.endswith("\n") else f"{line}\n" for line in text.splitlines()],
    }


COMMON_SETUP = """
from pathlib import Path
import importlib.util
import os
import subprocess
import sys
import time

import pandas as pd
from IPython.display import Markdown, display

NOTEBOOK_CWD = Path.cwd()
REPO_ROOT = next(
    path for path in [NOTEBOOK_CWD, *NOTEBOOK_CWD.parents] if (path / "scripts/Data/02_Forecasting/01_DA_prices").exists()
)
os.chdir(REPO_ROOT)
PACKAGE_ROOT = REPO_ROOT / "scripts/Data/02_Forecasting/01_DA_prices"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.append(str(PACKAGE_ROOT))

from hourly_da.core.config import HourlyDAPipelineConfig
from hourly_da.core.external_features import build_external_family_catalog, load_external_feature_store
from hourly_da.core.methodology import (
    STARTER_ENDOGENOUS_FEATURE_NOTE,
    feature_stage_policy_frame,
    model_status_frame,
    shortlisting_policy_frame,
)
from hourly_da.core.reporting import find_latest_run, load_csv, load_json
from hourly_da.core.tuning import build_tuning_placeholder, tuning_cadence_frame, tuning_snippet_frame
from hourly_da.models import naive_model_names
from hourly_da.notebook_support import estimate_run_duration_seconds, format_duration, load_selected_case_weeks

config = HourlyDAPipelineConfig(
    input_csv=REPO_ROOT / "data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv",
    raw_root=REPO_ROOT / "data/00_Raw/DA_Prices",
    cleaned_feature_root=REPO_ROOT / "data/01_cleaned",
    output_root=REPO_ROOT / "data/02_Forecasting/01_DA_prices/hourly_da",
)
output_root = config.output_root


def latest_run_or_none(run_label: str) -> Path | None:
    try:
        return find_latest_run(output_root, run_label)
    except FileNotFoundError:
        return None


def ensure_required_modules(module_names: list[str], install_command: str | None = None) -> None:
    missing = [module_name for module_name in module_names if importlib.util.find_spec(module_name) is None]
    if not missing:
        return

    message_lines = [
        "Missing required package(s) in the active notebook interpreter: " + ", ".join(missing),
        f"Active interpreter: {sys.executable}",
    ]
    if install_command:
        message_lines.append(f"Install command: {install_command}")
    raise RuntimeError("\\n".join(message_lines))


def run_command_with_live_output(command: list[str]) -> None:
    print("Running command:")
    print(" ".join(str(part) for part in command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    output_tail: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        output_tail.append(line)
        if len(output_tail) > 40:
            output_tail.pop(0)

    return_code = process.wait()
    if return_code != 0:
        tail_text = "".join(output_tail).strip()
        message = f"Command failed with exit code {return_code}."
        if tail_text:
            message += "\\nLast output:\\n" + tail_text
        raise RuntimeError(message)
""".strip()


def script_rerun_cell(
    script_name: str,
    run_label: str,
    extra_args: list[str] | None = None,
    required_modules: list[str] | None = None,
) -> str:
    extra_args = extra_args or []
    required_modules = required_modules or []
    command_lines = "\n".join([f"    command.append({repr(value)})" for value in extra_args])
    module_check_lines = ""
    if required_modules:
        install_targets = " ".join(required_modules)
        module_check_lines = f"""
    ensure_required_modules(
        {repr(required_modules)},
        install_command=f"{{sys.executable}} -m pip install {install_targets}",
    )
""".rstrip()
    return f"""
ALLOW_HEAVY_RERUN = False

if ALLOW_HEAVY_RERUN:
{module_check_lines}
    estimate = estimate_run_duration_seconds(output_root, "{run_label}")
    if estimate is not None:
        print(
            "Heavy rerun warning: latest comparable run "
            f"{{estimate['run_id']}} suggests about {{format_duration(float(estimate['estimate_seconds']))}}."
        )
    else:
        print("Heavy rerun warning: no comparable runtime estimate was found for this stage.")

    command = [sys.executable, str(PACKAGE_ROOT / "{script_name}")]
{command_lines}
    started = time.perf_counter()
    run_command_with_live_output(command)
    elapsed_seconds = time.perf_counter() - started
    print(f"Actual wall-clock time: {{format_duration(elapsed_seconds)}}")
else:
    print("Rerun skipped. Set ALLOW_HEAVY_RERUN = True only when you are ready to execute the finalized pipeline.")
""".strip()


def optional_execution_hook_cells(
    script_name: str,
    run_label: str,
    extra_args: list[str] | None = None,
    required_modules: list[str] | None = None,
    heading: str = "## Optional execution hook",
) -> list[dict[str, object]]:
    return [
        markdown_cell(heading),
        code_cell(
            script_rerun_cell(
                script_name,
                run_label,
                extra_args=extra_args,
                required_modules=required_modules,
            )
        ),
    ]


def optional_run_summary_cell(run_label: str, focus_models: list[str]) -> str:
    return f"""
run_dir = latest_run_or_none("{run_label}")
focus_models = {repr(focus_models)}
model_order = {{model_name: position for position, model_name in enumerate(focus_models)}}

if run_dir is None:
    print("No saved run exists yet for this notebook under the finalized methodology.")
else:
    print(run_dir)
    metrics_by_reporting_level = load_csv(run_dir, "metrics_by_reporting_level.csv")
    timing_summary = load_csv(run_dir, "origin_timing_summary.csv")
    official_naive = load_json(run_dir, "official_naive_reference.json")
    display(
        metrics_by_reporting_level[metrics_by_reporting_level["model"].isin(focus_models)]
        .assign(_model_order=lambda frame: frame["model"].map(model_order).fillna(len(model_order)))
        .sort_values(["dataset_split", "reporting_level_sort_order", "_model_order", "model"])
        .drop(columns=["_model_order"])
        .reset_index(drop=True)
    )
    display(pd.DataFrame([official_naive]))
    display(
        timing_summary[timing_summary["model"].isin(focus_models)]
        .assign(_model_order=lambda frame: frame["model"].map(model_order).fillna(len(model_order)))
        .sort_values(["dataset_split", "_model_order", "model"])
        .drop(columns=["_model_order"])
        .reset_index(drop=True)
    )
""".strip()


def stage_policy_cell(fs_level: str) -> str:
    return f"""
display(
    feature_stage_policy_frame()
    .loc[lambda df: df["fs_level"] == "{fs_level}"]
    .reset_index(drop=True)
)
""".strip()


def model_status_cell(model_families: list[str]) -> str:
    return f"""
display(
    model_status_frame()
    .loc[lambda df: df["model_family"].isin({repr(model_families)})]
    .reset_index(drop=True)
)
""".strip()


def tuning_placeholder_cell(model_family: str, fs_level: str) -> str:
    return f"""
display(pd.DataFrame([build_tuning_placeholder("{model_family}", "{fs_level}")]))
display(tuning_snippet_frame(model_family="{model_family}", fs_level="{fs_level}"))
""".strip()


def run_availability_cell(run_labels: list[str]) -> str:
    return f"""
rows = []
for run_label in {repr(run_labels)}:
    run_dir = latest_run_or_none(run_label)
    rows.append(
        {{
            "run_label": run_label,
            "latest_run": str(run_dir) if run_dir is not None else "not yet run",
        }}
    )

display(pd.DataFrame(rows))
""".strip()


def _dedupe_comparison_specs_block(dm_expression: str) -> str:
    return f"""
seen_models = set()
COMPARISON_MODEL_SPECS = []
for spec in comparison_specs:
    model_name = str(spec["model"])
    if model_name in seen_models:
        continue
    seen_models.add(model_name)
    COMPARISON_MODEL_SPECS.append(spec)

HORIZON_PLOT_MODELS = [spec["model"] for spec in COMPARISON_MODEL_SPECS]
WEEK_PLOT_MODELS = HORIZON_PLOT_MODELS.copy()
DIAGNOSTIC_MODELS = WEEK_PLOT_MODELS.copy()
DM_CHALLENGER_MODELS = {dm_expression}
""".strip()


def expanded_report_setup_cell(
    *,
    run_label: str,
    notebook_slug: str,
    comparison_logic: str,
) -> str:
    comparison_logic = textwrap.indent(comparison_logic.strip(), "    ")
    return f"""
from IPython.display import Image

from hourly_da.notebook_support import (
    apply_standard_matplotlib_style,
    build_compared_models_overview,
    build_dm_summary_table,
    build_model_style_map,
    build_reporting_summary_table,
    build_runtime_summary_table,
    build_week_metrics_for_predictions,
    build_week_winner_summary,
    filter_available_comparison_specs,
    load_standard_report_bundle,
    render_plot_gallery,
    style_dm_summary_table,
    style_model_overview_table,
    style_reporting_summary_table,
    style_runtime_summary_table,
    write_actual_vs_predicted_scatter_plot,
    write_horizon_error_plot,
    write_mae_by_hour_of_day_plot,
    write_residual_distribution_plot,
    write_standard_week_selection_plots,
)

run_dir = latest_run_or_none("{run_label}")
report_bundle = None
model_styles = {{}}
report_output_dir = None
official_naive_model = None
HORIZON_PLOT_MODELS = []
WEEK_PLOT_MODELS = []
DIAGNOSTIC_MODELS = []
DM_CHALLENGER_MODELS = []

if run_dir is None:
    print("No saved run exists yet for this notebook under the finalized methodology.")
else:
    apply_standard_matplotlib_style()
    current_suite_models = load_json(run_dir, "suite_models.json").get("models", [])
    current_model_names = [
        record.get("model") or record.get("name")
        for record in current_suite_models
        if (record.get("model") or record.get("name"))
    ]
    active_naive_models = set(naive_model_names())
    current_model_names = [
        model_name
        for model_name in current_model_names
        if not (str(model_name).startswith("naive_") and model_name not in active_naive_models)
    ]
    official_naive = load_json(run_dir, "official_naive_reference.json")
    official_naive_model = str(official_naive["model"])
{comparison_logic}
    if not COMPARISON_MODEL_SPECS:
        print("No comparison models were available for the expanded reporting block.")
    else:
        report_bundle = load_standard_report_bundle(
            output_root=output_root,
            current_run_dir=run_dir,
            comparison_specs=COMPARISON_MODEL_SPECS,
        )
        model_styles = build_model_style_map(
            report_bundle["comparison_specs"],
            official_naive_model=str(report_bundle["official_naive"]["model"]),
        )
        report_output_dir = output_root / "notebook_artifacts" / "{notebook_slug}" / run_dir.name / "standard_report"
        report_output_dir.mkdir(parents=True, exist_ok=True)

        print(f"Current run: {{run_dir.name}}")
        print(f"Current models: {{current_model_names}}")
        print(f"Naive benchmark for later comparisons: {{official_naive_model}}")
        print(f"Expanded comparison models: {{[spec['model'] for spec in COMPARISON_MODEL_SPECS]}}")
""".strip()


def expanded_model_overview_cell() -> str:
    return """
if report_bundle is None:
    print("Expanded comparison reporting is not available yet for this notebook.")
else:
    overview_table = build_compared_models_overview(
        report_bundle["comparison_specs"],
        official_naive_model=str(report_bundle["official_naive"]["model"]),
    )
    display(style_model_overview_table(overview_table))
    display(pd.DataFrame([report_bundle["official_naive"]]))
""".strip()


def expanded_reporting_summary_cell() -> str:
    return """
if report_bundle is None:
    print("Expanded summary tables are not available yet for this notebook.")
else:
    validation_summary = build_reporting_summary_table(
        report_bundle["metrics_by_reporting_level"],
        split_name="validation",
        model_order=report_bundle["model_order"],
    )
    test_summary = build_reporting_summary_table(
        report_bundle["metrics_by_reporting_level"],
        split_name="test",
        model_order=report_bundle["model_order"],
    )

    if not validation_summary.empty:
        display(style_reporting_summary_table(validation_summary, caption="Validation summary"))
    if not test_summary.empty:
        display(style_reporting_summary_table(test_summary, caption="Test summary"))
""".strip()


def expanded_horizon_plot_cell() -> str:
    return """
if report_bundle is None or report_output_dir is None:
    print("Expanded horizon plots are not available yet for this notebook.")
else:
    horizon_plot_path = write_horizon_error_plot(
        metrics_by_lead_day=report_bundle["metrics_by_lead_day"][
            report_bundle["metrics_by_lead_day"]["model"].isin(HORIZON_PLOT_MODELS)
        ].copy(),
        output_path=report_output_dir / "horizon_error_mae.png",
        model_order=HORIZON_PLOT_MODELS,
        model_styles=model_styles,
    )
    if horizon_plot_path is not None:
        display(Image(filename=str(horizon_plot_path)))
""".strip()


def expanded_week_report_cell(title_prefix: str) -> str:
    return f"""
if report_bundle is None or report_output_dir is None:
    print("Expanded selected-week reporting is not available yet for this notebook.")
else:
    D_ONLY_REPORTING = True
    FIVE_DAY_REPORTING = False

    try:
        selection_run_dir, selected_weeks = load_selected_case_weeks(output_root)
    except FileNotFoundError:
        print("No saved objective week selection artifact exists yet.")
    else:
        print(selection_run_dir)
        display(selected_weeks[["category", "iso_week_id", "week_start_local_date", "week_end_local_date"]])

        model_label_map = (
            report_bundle["comparison_specs"][["model", "display_name"]]
            .drop_duplicates(subset=["model"])
            .set_index("model")["display_name"]
            .to_dict()
        )
        week_model_order = {{model_name: position for position, model_name in enumerate(WEEK_PLOT_MODELS)}}

        reporting_options = []
        if D_ONLY_REPORTING:
            reporting_options.append(("d_only", "D-only forecast"))
        if FIVE_DAY_REPORTING:
            reporting_options.append(("stitched_all_horizon", "Five-day forecast"))

        if not reporting_options:
            print("No week plot reporting selected. Set at least one of D_ONLY_REPORTING or FIVE_DAY_REPORTING to True.")
        else:
            for reporting_level, reporting_label in reporting_options:
                display(Markdown(f"### {{reporting_label}}"))

                week_metrics = build_week_metrics_for_predictions(
                    report_bundle["predictions_long"],
                    config,
                    selected_weeks,
                    split_name="test",
                    reporting_level=reporting_level,
                    models=WEEK_PLOT_MODELS,
                    benchmark_model=str(report_bundle["official_naive"]["model"]),
                    model_order=WEEK_PLOT_MODELS,
                )
                week_winners = build_week_winner_summary(week_metrics, model_order=WEEK_PLOT_MODELS)
                if not week_winners.empty:
                    week_winners_display = (
                        week_winners.assign(
                            week_type=lambda frame: frame["category"].astype(str).str.replace("_", " ").str.title(),
                            best_mae_model=lambda frame: frame["best_mae_model"].map(model_label_map).fillna(frame["best_mae_model"]),
                            best_rmse_model=lambda frame: frame["best_rmse_model"].map(model_label_map).fillna(frame["best_rmse_model"]),
                            lowest_abs_bias_model=lambda frame: frame["lowest_abs_bias_model"].map(model_label_map).fillna(frame["lowest_abs_bias_model"]),
                            lowest_max_abs_error_model=lambda frame: frame["lowest_max_abs_error_model"].map(model_label_map).fillna(frame["lowest_max_abs_error_model"]),
                        )
                        [[
                            "week_type",
                            "iso_week_id",
                            "best_mae_model",
                            "best_mae",
                            "best_rmse_model",
                            "best_rmse",
                            "lowest_abs_bias_model",
                            "lowest_abs_bias",
                            "lowest_max_abs_error_model",
                            "lowest_max_abs_error",
                        ]]
                        .rename(
                            columns={{
                                "week_type": "Week type",
                                "iso_week_id": "ISO week",
                                "best_mae_model": "Best MAE model",
                                "best_mae": "Best MAE",
                                "best_rmse_model": "Best RMSE model",
                                "best_rmse": "Best RMSE",
                                "lowest_abs_bias_model": "Lowest |bias| model",
                                "lowest_abs_bias": "Lowest |bias|",
                                "lowest_max_abs_error_model": "Lowest max |error| model",
                                "lowest_max_abs_error": "Lowest max |error|",
                            }}
                        )
                    )
                    display(Markdown("#### Week winners"))
                    display(
                        week_winners_display.style
                        .format(
                            {{
                                "Best MAE": "{{:.2f}}",
                                "Best RMSE": "{{:.2f}}",
                                "Lowest |bias|": "{{:.2f}}",
                                "Lowest max |error|": "{{:.2f}}",
                            }}
                        )
                        .hide(axis="index")
                    )

                week_metrics_display = (
                    week_metrics[week_metrics["model"].isin(WEEK_PLOT_MODELS)]
                    .assign(
                        week_type=lambda frame: frame["category"].astype(str).str.replace("_", " ").str.title(),
                        Model=lambda frame: frame["model"].map(model_label_map).fillna(frame["model"]),
                        _model_order=lambda frame: frame["model"].map(week_model_order).fillna(len(week_model_order)),
                    )
                    [[
                        "week_type",
                        "iso_week_id",
                        "_model_order",
                        "Model",
                        "mae_rank",
                        "rmse_rank",
                        "abs_bias_rank",
                        "mae",
                        "rmse",
                        "bias",
                        "rmae",
                        "coverage_pct",
                        "max_abs_error",
                    ]]
                    .sort_values(["week_type", "mae_rank", "_model_order", "Model"])
                    .drop(columns=["_model_order"])
                    .rename(
                        columns={{
                            "week_type": "Week type",
                            "iso_week_id": "ISO week",
                            "mae_rank": "MAE rank",
                            "rmse_rank": "RMSE rank",
                            "abs_bias_rank": "|Bias| rank",
                            "mae": "MAE",
                            "rmse": "RMSE",
                            "bias": "Bias",
                            "rmae": "rMAE",
                            "coverage_pct": "Coverage",
                            "max_abs_error": "Max |error|",
                        }}
                    )
                    .reset_index(drop=True)
                )
                display(Markdown("#### Detailed per-model week metrics"))
                display(
                    week_metrics_display.style
                    .format(
                        {{
                            "MAE rank": lambda value: "" if pd.isna(value) else f"{{int(value)}}",
                            "RMSE rank": lambda value: "" if pd.isna(value) else f"{{int(value)}}",
                            "|Bias| rank": lambda value: "" if pd.isna(value) else f"{{int(value)}}",
                            "MAE": "{{:.2f}}",
                            "RMSE": "{{:.2f}}",
                            "Bias": "{{:+.2f}}",
                            "rMAE": "{{:.3f}}",
                            "Coverage": "{{:.2f}}%",
                            "Max |error|": "{{:.2f}}",
                        }}
                    )
                    .apply(
                        lambda row: [
                            "background-color: #eef7ee; font-weight: 600;"
                            if pd.notna(row["MAE rank"]) and int(row["MAE rank"]) == 1
                            else ""
                            for _ in row
                        ],
                        axis=1,
                    )
                    .hide(axis="index")
                )

                week_plot_paths = write_standard_week_selection_plots(
                    predictions=report_bundle["predictions_long"],
                    config=config,
                    selected_weeks=selected_weeks,
                    output_dir=report_output_dir / "week_plots",
                    model_order=WEEK_PLOT_MODELS,
                    model_styles=model_styles,
                    split_name="test",
                    reporting_level=reporting_level,
                    title_prefix=f"{title_prefix}: {{reporting_label}}",
                )
                display(render_plot_gallery(week_plot_paths, columns=2))
""".strip()


def expanded_diagnostic_plots_cell() -> str:
    return """
if report_bundle is None or report_output_dir is None:
    print("Expanded diagnostic plots are not available yet for this notebook.")
else:
    diagnostic_plot_paths = []

    mae_by_hour_path = write_mae_by_hour_of_day_plot(
        predictions=report_bundle["predictions_long"],
        config=config,
        output_path=report_output_dir / "diagnostics" / "mae_by_hour_of_day.png",
        model_order=DIAGNOSTIC_MODELS,
        model_styles=model_styles,
    )
    if mae_by_hour_path is not None:
        diagnostic_plot_paths.append(mae_by_hour_path)

    residual_path = write_residual_distribution_plot(
        predictions=report_bundle["predictions_long"],
        config=config,
        output_path=report_output_dir / "diagnostics" / "residual_distribution.png",
        model_order=DIAGNOSTIC_MODELS,
        model_styles=model_styles,
    )
    if residual_path is not None:
        diagnostic_plot_paths.append(residual_path)

    scatter_path = write_actual_vs_predicted_scatter_plot(
        predictions=report_bundle["predictions_long"],
        config=config,
        output_path=report_output_dir / "diagnostics" / "actual_vs_predicted.png",
        model_order=DIAGNOSTIC_MODELS,
        model_styles=model_styles,
    )
    if scatter_path is not None:
        diagnostic_plot_paths.append(scatter_path)

    display(render_plot_gallery(diagnostic_plot_paths, columns=2))
""".strip()


def expanded_dm_summary_cell() -> str:
    return """
if report_bundle is None:
    print("Expanded Diebold-Mariano reporting is not available yet for this notebook.")
else:
    dm_display_order = [
        row["display_name"]
        for row in report_bundle["comparison_specs"].to_dict(orient="records")
        if row["model"] in DM_CHALLENGER_MODELS
    ]
    dm_summary = build_dm_summary_table(
        report_bundle["diebold_mariano_by_reporting_level"][
            report_bundle["diebold_mariano_by_reporting_level"]["challenger_model"].isin(DM_CHALLENGER_MODELS)
        ].copy(),
        challenger_display_order=dm_display_order,
    )
    if dm_summary.empty:
        print("No configured Diebold-Mariano comparisons were available for this notebook.")
    else:
        display(style_dm_summary_table(dm_summary))
""".strip()


def expanded_runtime_summary_cell() -> str:
    return """
if report_bundle is None:
    print("Expanded runtime reporting is not available yet for this notebook.")
else:
    runtime_summary = build_runtime_summary_table(
        report_bundle["timing_summary"],
        model_order=report_bundle["model_order"],
    )
    if runtime_summary.empty:
        print("No runtime summary was available for this notebook.")
    else:
        display(style_runtime_summary_table(runtime_summary))
""".strip()


def expanded_report_cells(
    *,
    run_label: str,
    notebook_slug: str,
    comparison_logic: str,
    week_title_prefix: str,
) -> list[dict[str, object]]:
    return [
        markdown_cell(
            """
## Expanded comparison reporting

The lightweight run tables above are kept as-is. The sections below restore the richer notebook reporting layer that compares the saved run against the relevant benchmark and peer models, then reuses the frozen objective weeks.
""".strip()
        ),
        code_cell(
            expanded_report_setup_cell(
                run_label=run_label,
                notebook_slug=notebook_slug,
                comparison_logic=comparison_logic,
            )
        ),
        markdown_cell("## 1. Short overview of compared models"),
        code_cell(expanded_model_overview_cell()),
        markdown_cell(
            """
## 2. Main validation and test summary tables

Each table reports the same thesis metrics for the three standard reporting slices:
- `D only`
- `Full-horizon`
""".strip()
        ),
        code_cell(expanded_reporting_summary_cell()),
        markdown_cell(
            """
## 3. By-horizon error view

This figure keeps the split fixed and shows how MAE changes from `D` through `D+4`.
""".strip()
        ),
        code_cell(expanded_horizon_plot_cell()),
        markdown_cell(
            """
## 4. Forecast vs actual on the frozen week selections

These plots reuse the objectively selected weeks from notebook `02`.

Use the code-cell toggles below to switch between:
- `D-only forecast`: the operational day-ahead path with one forecast per target hour
- `Five-day forecast`: one frozen `D` through `D+4` forecast issued at `08:00` on the day before the selected week starts
""".strip()
        ),
        code_cell(expanded_week_report_cell(week_title_prefix)),
        markdown_cell(
            """
## 5. Diagnostic plots

The diagnostics below focus on the **test split** and the same `D only` operational path as the week overlays, so the interpretation is based on unique forecast-target pairs rather than repeated multi-origin horizons.
""".strip()
        ),
        code_cell(expanded_diagnostic_plots_cell()),
        markdown_cell(
            """
## 6. Statistical comparison

The Diebold-Mariano table is interpreted as follows:
- negative DM statistic favors the challenger
- positive DM statistic favors the benchmark
- the verdict column applies a `p < 0.05` threshold
""".strip()
        ),
        code_cell(expanded_dm_summary_cell()),
        markdown_cell("## 7. Runtime and practicality summary"),
        code_cell(expanded_runtime_summary_cell()),
    ]


def fs0_naive_comparison_logic() -> str:
    return (
        """
official_naive_display = f"Naive benchmark ({official_naive_model.replace('naive_', '').replace('_', ' ').title()})"
comparison_specs = [
    {
        "model": official_naive_model,
        "display_name": official_naive_display,
        "description": "Validation-selected seasonal naive benchmark from FS0.",
        "role": "benchmark",
    },
    {
        "model": "naive_previous_week",
        "display_name": "Naive previous week",
        "description": "FS0 seasonal naive using the previous delivery week.",
        "role": "current",
    },
    {
        "model": "naive_previous_year",
        "display_name": "Naive previous year",
        "description": "FS0 seasonal naive using the previous delivery year.",
        "role": "current",
    },
]
""".strip()
        + "\n"
        + _dedupe_comparison_specs_block(
            "[model_name for model_name in HORIZON_PLOT_MODELS if model_name != official_naive_model]"
        )
    )


def fs1_lear_comparison_logic() -> str:
    return (
        """
official_naive_display = f"Naive benchmark ({official_naive_model.replace('naive_', '').replace('_', ' ').title()})"
comparison_specs = [
    {
        "model": official_naive_model,
        "display_name": official_naive_display,
        "description": "Validation-selected FS0 benchmark carried into the dedicated LEAR FS1 run.",
        "role": "benchmark",
    },
    {
        "model": "lear_fs1",
        "display_name": "LEAR FS1",
        "description": "Current LEAR FS1 result from the dedicated FS1 run.",
        "role": "current",
    },
]
""".strip()
        + "\n"
        + _dedupe_comparison_specs_block('["lear_fs1"] if "lear_fs1" in HORIZON_PLOT_MODELS else []')
    )


def fs1_xgboost_comparison_logic() -> str:
    return (
        """
official_naive_display = f"Naive benchmark ({official_naive_model.replace('naive_', '').replace('_', ' ').title()})"
comparison_specs = [
    {
        "model": official_naive_model,
        "display_name": official_naive_display,
        "description": "Validation-selected FS0 benchmark carried into the XGBoost run review.",
        "role": "benchmark",
    },
]
comparison_specs.extend(
    filter_available_comparison_specs(
        output_root=output_root,
        current_run_dir=run_dir,
        candidate_specs=[
            {
                "model": "lear_fs1",
                "run_label": "lear_fs1_benchmark",
                "display_name": "LEAR FS1",
                "description": "Earlier FS1 linear benchmark from notebook 05.",
                "role": "prior",
            },
        ],
    )
)
comparison_specs.extend(
    [
        {
            "model": "xgboost_fs1",
            "display_name": "XGBoost FS1",
            "description": "Current XGBoost FS1 result from the dedicated FS1 run.",
            "role": "current",
        },
    ]
)
""".strip()
        + "\n"
        + _dedupe_comparison_specs_block('["xgboost_fs1"] if "xgboost_fs1" in HORIZON_PLOT_MODELS else []')
    )


def fs1_combined_comparison_logic() -> str:
    return (
        """
official_naive_display = f"Naive benchmark ({official_naive_model.replace('naive_', '').replace('_', ' ').title()})"
comparison_specs = [
    {
        "model": official_naive_model,
        "display_name": official_naive_display,
        "description": "Validation-selected FS0 benchmark for the combined FS1 comparison.",
        "role": "benchmark",
    },
]
comparison_specs.extend(
    filter_available_comparison_specs(
        output_root=output_root,
        current_run_dir=run_dir,
        candidate_specs=[
            {
                "model": "lear_fs1",
                "source": "current",
                "display_name": "LEAR FS1",
                "description": "FS1 linear benchmark from notebook 05.",
                "role": "current",
            },
            {
                "model": "xgboost_fs1",
                "source": "current",
                "display_name": "XGBoost FS1",
                "description": "FS1 tree benchmark from notebook 06.",
                "role": "current",
            },
        ],
    )
)
""".strip()
        + "\n"
        + _dedupe_comparison_specs_block(
            "[model_name for model_name in HORIZON_PLOT_MODELS if model_name != official_naive_model]"
        )
    )


def fs2_lear_comparison_logic() -> str:
    return (
        """
official_naive_display = f"Naive benchmark ({official_naive_model.replace('naive_', '').replace('_', ' ').title()})"
comparison_specs = [
    {
        "model": official_naive_model,
        "display_name": official_naive_display,
        "description": "Validation-selected FS0 benchmark carried into the FS2 LEAR review.",
        "role": "benchmark",
    },
]
comparison_specs.extend(
    filter_available_comparison_specs(
        output_root=output_root,
        current_run_dir=run_dir,
        candidate_specs=[
            {
                "model": "lear_fs1",
                "run_label": "lear_fs1_benchmark",
                "display_name": "LEAR FS1",
                "description": "Earlier same-family FS1 result from notebook 05.",
                "role": "prior",
            },
            {
                "model": "xgboost_fs1",
                "run_label": "xgboost_fs1_benchmark",
                "display_name": "XGBoost FS1",
                "description": "Earlier FS1 tree benchmark from notebook 06.",
                "role": "prior",
            },
        ],
    )
)
comparison_specs.extend(
    [
        {
            "model": "lear_fs2",
            "display_name": "LEAR FS2",
            "description": "Current LEAR FS2 result from the dedicated FS2 run.",
            "role": "current",
        },
    ]
)
""".strip()
        + "\n"
        + _dedupe_comparison_specs_block('["lear_fs2"] if "lear_fs2" in HORIZON_PLOT_MODELS else []')
    )


def fs2_xgboost_comparison_logic() -> str:
    return (
        """
official_naive_display = f"Naive benchmark ({official_naive_model.replace('naive_', '').replace('_', ' ').title()})"
comparison_specs = [
    {
        "model": official_naive_model,
        "display_name": official_naive_display,
        "description": "Validation-selected FS0 benchmark carried into the FS2 XGBoost review.",
        "role": "benchmark",
    },
]
comparison_specs.extend(
    filter_available_comparison_specs(
        output_root=output_root,
        current_run_dir=run_dir,
        candidate_specs=[
            {
                "model": "lear_fs1",
                "run_label": "lear_fs1_benchmark",
                "display_name": "LEAR FS1",
                "description": "Earlier FS1 linear benchmark from notebook 05.",
                "role": "prior",
            },
            {
                "model": "xgboost_fs1",
                "run_label": "xgboost_fs1_benchmark",
                "display_name": "XGBoost FS1",
                "description": "Earlier same-family FS1 result from notebook 06.",
                "role": "prior",
            },
            {
                "model": "lear_fs2",
                "run_label": "lear_fs2_benchmark",
                "display_name": "LEAR FS2",
                "description": "Earlier FS2 linear benchmark from notebook 08.",
                "role": "prior",
            },
        ],
    )
)
comparison_specs.extend(
    [
        {
            "model": "xgboost_fs2",
            "display_name": "XGBoost FS2",
            "description": "Current XGBoost FS2 result from the dedicated FS2 run.",
            "role": "current",
        },
    ]
)
""".strip()
        + "\n"
        + _dedupe_comparison_specs_block('["xgboost_fs2"] if "xgboost_fs2" in HORIZON_PLOT_MODELS else []')
    )


def fs2_prophet_comparison_logic() -> str:
    return (
        """
official_naive_display = f"Naive benchmark ({official_naive_model.replace('naive_', '').replace('_', ' ').title()})"
comparison_specs = [
    {
        "model": official_naive_model,
        "display_name": official_naive_display,
        "description": "Validation-selected FS0 benchmark carried into the FS2 Prophet review.",
        "role": "benchmark",
    },
]
comparison_specs.extend(
    filter_available_comparison_specs(
        output_root=output_root,
        current_run_dir=run_dir,
        candidate_specs=[
            {
                "model": "lear_fs1",
                "run_label": "lear_fs1_benchmark",
                "display_name": "LEAR FS1",
                "description": "Earlier FS1 linear benchmark from notebook 05.",
                "role": "prior",
            },
            {
                "model": "xgboost_fs1",
                "run_label": "xgboost_fs1_benchmark",
                "display_name": "XGBoost FS1",
                "description": "Earlier FS1 tree benchmark from notebook 06.",
                "role": "prior",
            },
            {
                "model": "lear_fs2",
                "run_label": "lear_fs2_benchmark",
                "display_name": "LEAR FS2",
                "description": "Earlier FS2 linear benchmark from notebook 08.",
                "role": "prior",
            },
            {
                "model": "xgboost_fs2",
                "run_label": "xgboost_fs2_benchmark",
                "display_name": "XGBoost FS2",
                "description": "Earlier FS2 tree benchmark from notebook 09.",
                "role": "prior",
            },
        ],
    )
)
comparison_specs.extend(
    [
        {
            "model": "prophet_fs2",
            "display_name": "Prophet FS2",
            "description": "Current Prophet FS2 result from the dedicated Prophet run.",
            "role": "current",
        },
    ]
)
""".strip()
        + "\n"
        + _dedupe_comparison_specs_block('["prophet_fs2"] if "prophet_fs2" in HORIZON_PLOT_MODELS else []')
    )


def fs2_combined_comparison_logic() -> str:
    return (
        """
official_naive_display = f"Naive benchmark ({official_naive_model.replace('naive_', '').replace('_', ' ').title()})"
comparison_specs = [
    {
        "model": official_naive_model,
        "display_name": official_naive_display,
        "description": "Validation-selected FS0 benchmark for the combined FS2 comparison.",
        "role": "benchmark",
    },
]
comparison_specs.extend(
    filter_available_comparison_specs(
        output_root=output_root,
        current_run_dir=run_dir,
        candidate_specs=[
            {
                "model": "lear_fs2",
                "source": "current",
                "display_name": "LEAR FS2",
                "description": "FS2 linear benchmark from notebook 08.",
                "role": "current",
            },
            {
                "model": "xgboost_fs2",
                "source": "current",
                "display_name": "XGBoost FS2",
                "description": "FS2 tree benchmark from notebook 09.",
                "role": "current",
            },
            {
                "model": "prophet_fs2",
                "source": "current",
                "display_name": "Prophet FS2",
                "description": "FS2 additive benchmark from notebook 10.",
                "role": "current",
            },
        ],
    )
)
""".strip()
        + "\n"
        + _dedupe_comparison_specs_block(
            "[model_name for model_name in HORIZON_PLOT_MODELS if model_name != official_naive_model]"
        )
    )


FS3_CONTEXT_CODE = "day1_crossborder_bundle"
FS3_STAGE = "day1_only"
FS3_LEAR_PARENT_RUN_LABEL = f"fs3_{FS3_STAGE}_lear_{FS3_CONTEXT_CODE}_parent"
FS3_XGBOOST_PARENT_RUN_LABEL = f"fs3_{FS3_STAGE}_xgboost_{FS3_CONTEXT_CODE}_parent"
FS3_LEAR_AGGREGATE_RUN_LABEL = f"feature_family_ablation__{FS3_LEAR_PARENT_RUN_LABEL}"
FS3_XGBOOST_AGGREGATE_RUN_LABEL = f"feature_family_ablation__{FS3_XGBOOST_PARENT_RUN_LABEL}"
FS3_FAMILY_CODES = ("da_load_day1_crossborder", "da_generation_day1_crossborder")
FS3_ALL_EXOGENOUS_CODES = (
    "wa_load_domestic",
    "wa_load_crossborder",
    "installed_capacity_crossborder",
    "da_load_day1_domestic",
    "da_load_day1_crossborder",
    "da_generation_day1_domestic",
    "da_generation_day1_crossborder",
    "load_history_domestic",
    "load_history_crossborder",
    "generation_history_domestic",
    "generation_history_crossborder",
    "neighbor_price_weekly",
)
FS3_COMBO_RUN_LABEL = "fs3_combo_promoted_confirm"
FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL = "lear_fs3_combo_promoted_benchmark"
FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL = "xgboost_fs3_combo_promoted_benchmark"
FS3_COMBO_ABLATION_CONTEXT_CODE = "combo_promoted"
FS3_COMBO_ABLATION_STAGE = "combo"
FS3_LEAR_COMBO_AGGREGATE_RUN_LABEL = f"feature_family_ablation__{FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL}"
FS3_XGBOOST_COMBO_AGGREGATE_RUN_LABEL = f"feature_family_ablation__{FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL}"
FS2_LEAR_CANDIDATE_RUN_LABEL = "lear_fs2_pruned_candidate_benchmark"
FS2_XGBOOST_CANDIDATE_RUN_LABEL = "xgboost_fs2_pruned_candidate_benchmark"
FS2_CANDIDATE_COMPARISON_RUN_LABEL = "model_comparison_fs2_pruned_candidate"
FS3_LEAR_CANDIDATE_RUN_LABEL = "lear_fs3_combo_pruned_candidate_benchmark"
FS3_XGBOOST_CANDIDATE_RUN_LABEL = "xgboost_fs3_combo_pruned_candidate_benchmark"


def fs3_combo_benchmark_run_label(model_family: str) -> str:
    if model_family == "lear":
        return FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL
    if model_family == "xgboost":
        return FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL
    raise ValueError(f"Unsupported model family for FS3 combo benchmark run label: {model_family}")


def fs3_parent_comparison_logic(model_family: str) -> str:
    current_model = f"{model_family}_fs3_{FS3_CONTEXT_CODE}"
    current_display = f"{model_family.upper() if model_family == 'lear' else 'XGBoost'} FS3"
    same_family_fs2 = f"{model_family}_fs2"
    same_family_display = f"{model_family.upper() if model_family == 'lear' else 'XGBoost'} FS2"
    peer_model = "xgboost_fs3_day1_crossborder_bundle" if model_family == "lear" else "lear_fs3_day1_crossborder_bundle"
    peer_display = "XGBoost FS3" if model_family == "lear" else "LEAR FS3"
    peer_run_label = FS3_XGBOOST_PARENT_RUN_LABEL if model_family == "lear" else FS3_LEAR_PARENT_RUN_LABEL
    return (
        f"""
official_naive_display = f"Naive benchmark ({{official_naive_model.replace('naive_', '').replace('_', ' ').title()}})"
comparison_specs = [
    {{
        "model": official_naive_model,
        "display_name": official_naive_display,
        "description": "Validation-selected FS0 benchmark carried into the FS3 parent review.",
        "role": "benchmark",
    }},
]
comparison_specs.extend(
    filter_available_comparison_specs(
        output_root=output_root,
        current_run_dir=run_dir,
        candidate_specs=[
            {{
                "model": "{same_family_fs2}",
                "run_label": "{same_family_fs2}_benchmark" if "{same_family_fs2}" != "prophet_fs2" else "prophet_benchmark",
                "display_name": "{same_family_display}",
                "description": "Same-family FS2 benchmark immediately before the FS3 exogenous layer.",
                "role": "prior",
            }},
            {{
                "model": "lear_fs2",
                "run_label": "lear_fs2_benchmark",
                "display_name": "LEAR FS2",
                "description": "FS2 linear benchmark for cross-family context.",
                "role": "prior",
            }},
            {{
                "model": "xgboost_fs2",
                "run_label": "xgboost_fs2_benchmark",
                "display_name": "XGBoost FS2",
                "description": "FS2 tree benchmark for cross-family context.",
                "role": "prior",
            }},
            {{
                "model": "{peer_model}",
                "run_label": "{peer_run_label}",
                "display_name": "{peer_display}",
                "description": "Peer FS3 parent benchmark on the same supported FS3 context.",
                "role": "peer",
            }},
        ],
    )
)
comparison_specs.extend(
    [
        {{
            "model": "{current_model}",
            "display_name": "{current_display}",
            "description": "Current FS3 parent benchmark on the supported day-1 crossborder exogenous bundle.",
            "role": "current",
        }},
    ]
)
""".strip()
        + "\n"
        + _dedupe_comparison_specs_block(f'["{current_model}"] if "{current_model}" in HORIZON_PLOT_MODELS else []')
    )


def fs3_parent_execution_note(model_family: str) -> str:
    model_label = "LEAR" if model_family == "lear" else "XGBoost"
    peer_label = "XGBoost" if model_family == "lear" else "LEAR"
    return f"""
Execution note:
- this notebook refreshes the **FS3 parent benchmark only** for {model_label}
- the supported FS3 context is the day-1 crossborder exogenous bundle
- compare the saved parent run against `FS2` first before reading the separate ablation notebook
- use the separate `{peer_label}` FS3 notebook and notebook `18` for cross-model comparison
""".strip()


def fs3_context_diagnostics_cell(
    model_family: str,
    *,
    context_code: str = FS3_CONTEXT_CODE,
    stage: str = FS3_STAGE,
) -> str:
    model_label = "LEAR" if model_family == "lear" else "XGBoost"
    return f"""
from matplotlib import pyplot as plt

from run_fs3_ordered_benchmarks import FEATURE_VALUE_CONTEXT_SPECS

store = load_external_feature_store(config)
catalog = build_external_family_catalog(config, store)
context_spec = next(
    spec
    for spec in FEATURE_VALUE_CONTEXT_SPECS
    if spec.context_code == "{context_code}" and spec.stage == "{stage}" and spec.model_family == "{model_family}"
)
experiment_map = store.experiment_map()
selected_experiments = [experiment_map[code] for code in context_spec.family_codes if code in experiment_map]
selected_columns = []
for experiment in selected_experiments:
    for column_name in list(experiment.direct_columns) + list(experiment.lagged_columns):
        if column_name not in selected_columns:
            selected_columns.append(column_name)

display(pd.DataFrame([{{
    "Parent context": context_spec.label,
    "Model family": context_spec.model_family,
    "Context code": context_spec.context_code,
    "FS stage": "FS3",
    "Supported family codes": ", ".join(context_spec.family_codes),
    "Primary reporting level": context_spec.primary_reporting_level,
    "Support status": context_spec.support_status,
    "Support note": context_spec.support_note,
}}]))

family_codes = tuple(context_spec.family_codes)

def _catalog_codes(row: pd.Series) -> list[str]:
    codes: list[str] = []
    for field_name in ("active_direct_experiments", "active_lagged_experiments"):
        raw_value = str(row.get(field_name, "") or "")
        for code in [part.strip() for part in raw_value.split(",") if part.strip()]:
            if code not in codes:
                codes.append(code)
    return codes

family_catalog_view = catalog.copy()
family_catalog_view["matched_experiment_codes"] = family_catalog_view.apply(
    lambda row: ", ".join(code for code in _catalog_codes(row) if code in family_codes),
    axis=1,
)
family_catalog_view = family_catalog_view[family_catalog_view["matched_experiment_codes"] != ""].copy()
if family_catalog_view.empty:
    print("No external family catalog rows were found for the supported FS3 context yet.")
else:
    display(
        family_catalog_view[
            [
                "matched_experiment_codes",
                "family_name",
                "availability_class",
                "available_column_examples",
                "known_at_rule",
                "active_direct_experiments",
                "active_lagged_experiments",
                "current_usage_mode",
                "current_issue_status",
            ]
        ].reset_index(drop=True)
    )

if not selected_columns:
    print("No selected exogenous columns were found in the current feature store.")
else:
    values = store.values.set_index("timestamp_utc")[selected_columns].copy()
    known_at = store.known_at.set_index("timestamp_utc")[selected_columns].copy()
    validation_start = pd.Timestamp("2023-10-01", tz="UTC")
    test_end = pd.Timestamp("2025-09-30 23:00:00", tz="UTC")
    values = values.loc[(values.index >= validation_start) & (values.index <= test_end)].copy()
    known_at = known_at.reindex(values.index)

    coverage_rows = []
    for column_name in selected_columns:
        series = values[column_name]
        known_series = pd.to_datetime(known_at[column_name], utc=True, errors="coerce") if column_name in known_at.columns else pd.Series(index=values.index, dtype="datetime64[ns, UTC]")
        coverage_rows.append({{
            "column_name": column_name,
            "non_null_rows": int(series.notna().sum()),
            "coverage_pct": float(series.notna().mean() * 100.0),
            "first_timestamp_utc": series.dropna().index.min(),
            "last_timestamp_utc": series.dropna().index.max(),
            "latest_known_at_utc": known_series.dropna().max(),
        }})
    display(pd.DataFrame(coverage_rows).sort_values(["coverage_pct", "column_name"], ascending=[False, True]).reset_index(drop=True))

    plot_columns = [column_name for column_name in selected_columns if values[column_name].notna().any()][:4]
    if plot_columns:
        plot_frame = values[plot_columns].dropna(how="all").tail(24 * 14)
        if plot_frame.empty:
            print("The supported FS3 exogenous columns do not have enough recent non-null data for a quick preview plot.")
        else:
            fig, ax = plt.subplots(figsize=(12, 4.5))
            plot_frame.plot(ax=ax, linewidth=1.2)
            ax.set_title(f"{{context_spec.label}}: last 14 days with available data")
            ax.set_xlabel("Timestamp (UTC)")
            ax.set_ylabel("Value")
            ax.grid(True, alpha=0.25)
            ax.legend(loc="upper left", fontsize=8)
            display(fig)
            plt.close(fig)
""".strip()


def fs3_parent_run_summary_cell(run_label: str, model_family: str) -> str:
    current_model = f"{model_family}_fs3_{FS3_CONTEXT_CODE}"
    focus_models = ["naive_previous_week", "naive_previous_year", f"{model_family}_fs2", current_model]
    return optional_run_summary_cell(run_label, focus_models)


def fs3_combo_model_name(model_family: str) -> str:
    return f"{model_family}_fs3_combo_promoted"


def fs3_all_exogenous_comparison_logic(model_family: str) -> str:
    current_model = fs3_combo_model_name(model_family)
    current_display = f"{model_family.upper() if model_family == 'lear' else 'XGBoost'} FS3 all exogenous"
    same_family_fs2 = f"{model_family}_fs2"
    same_family_display = f"{model_family.upper() if model_family == 'lear' else 'XGBoost'} FS2"
    cross_family_fs2 = "xgboost_fs2" if model_family == "lear" else "lear_fs2"
    cross_family_display = "XGBoost FS2" if model_family == "lear" else "LEAR FS2"
    cross_family_run_label = "xgboost_fs2_benchmark" if model_family == "lear" else "lear_fs2_benchmark"
    peer_model = fs3_combo_model_name("xgboost" if model_family == "lear" else "lear")
    peer_display = "XGBoost FS3 all exogenous" if model_family == "lear" else "LEAR FS3 all exogenous"
    peer_run_label = fs3_combo_benchmark_run_label("xgboost" if model_family == "lear" else "lear")
    return (
        f"""
official_naive_display = f"Naive benchmark ({{official_naive_model.replace('naive_', '').replace('_', ' ').title()}})"
comparison_specs = [
    {{
        "model": official_naive_model,
        "display_name": official_naive_display,
        "description": "Validation-selected FS0 benchmark carried into the all-exogenous FS3 review.",
        "role": "benchmark",
    }},
]
comparison_specs.extend(
    filter_available_comparison_specs(
        output_root=output_root,
        current_run_dir=run_dir,
        candidate_specs=[
            {{
                "model": "{same_family_fs2}",
                "source": "current",
                "display_name": "{same_family_display}",
                "description": "Same-family FS2 benchmark immediately before the all-exogenous FS3 layer.",
                "role": "prior",
            }},
            {{
                "model": "{cross_family_fs2}",
                "run_label": "{cross_family_run_label}",
                "display_name": "{cross_family_display}",
                "description": "Cross-family FS2 benchmark for context.",
                "role": "prior",
            }},
            {{
                "model": "{peer_model}",
                "run_label": "{peer_run_label}",
                "display_name": "{peer_display}",
                "description": "Peer FS3 parent benchmark with the same all-exogenous bundle.",
                "role": "peer",
            }},
        ],
    )
)
comparison_specs.extend(
    [
        {{
            "model": "{current_model}",
            "display_name": "{current_display}",
            "description": "Current FS3 parent benchmark using the combined full-horizon, day-1, and historical exogenous families.",
            "role": "current",
        }},
    ]
)
""".strip()
        + "\n"
        + _dedupe_comparison_specs_block(f'["{current_model}"] if "{current_model}" in HORIZON_PLOT_MODELS else []')
    )


def fs3_all_exogenous_execution_note(model_family: str) -> str:
    model_label = "LEAR" if model_family == "lear" else "XGBoost"
    peer_label = "XGBoost" if model_family == "lear" else "LEAR"
    return f"""
Execution note:
- this notebook refreshes the notebook-specific **all-exogenous FS3 parent benchmark** for {model_label}
- the run includes the full-horizon, day-1-only, and historical exogenous family groups together
- the rerun keeps the naive baselines plus the same-family `FS2` anchor, but it does **not** refresh {peer_label} in this notebook
- grouped ablation remains separated in the dedicated model-specific notebooks, which still target the narrower benchmark-ready day-1 context
- use the separate `{peer_label}` FS3 notebook and notebook `18` for cross-model comparison
""".strip()


def fs3_all_exogenous_diagnostics_cell(model_family: str) -> str:
    model_label = "LEAR" if model_family == "lear" else "XGBoost"
    return f"""
from matplotlib import pyplot as plt

from hourly_da.core.external_features import fs3_taxonomy_inventory_frame

store = load_external_feature_store(config)
catalog = build_external_family_catalog(config, store)
taxonomy = fs3_taxonomy_inventory_frame(config, store)

display(pd.DataFrame([{{
    "Parent context": "{model_label} FS3 all exogenous combo parent",
    "Model family": "{model_family}",
    "FS stage": "FS3",
    "Execution context": "all_exogenous_combo_parent",
    "Selected family codes": ", ".join({repr(FS3_ALL_EXOGENOUS_CODES)}),
    "Family groups": "full_horizon, day1_only, historical",
    "Run label": "{fs3_combo_benchmark_run_label(model_family)}",
}}]))

display(taxonomy.reset_index(drop=True))

selected_family_codes = {repr(FS3_ALL_EXOGENOUS_CODES)}

def _catalog_codes(row: pd.Series) -> list[str]:
    codes: list[str] = []
    for field_name in ("active_direct_experiments", "active_lagged_experiments"):
        raw_value = str(row.get(field_name, "") or "")
        for code in [part.strip() for part in raw_value.split(",") if part.strip()]:
            if code not in codes:
                codes.append(code)
    return codes

catalog_view = catalog.copy()
catalog_view["matched_experiment_codes"] = catalog_view.apply(
    lambda row: ", ".join(code for code in _catalog_codes(row) if code in selected_family_codes),
    axis=1,
)
catalog_view = catalog_view[catalog_view["matched_experiment_codes"] != ""].copy()
if catalog_view.empty:
    print("No external family catalog rows were found for the all-exogenous FS3 context yet.")
else:
    display(
        catalog_view[
            [
                "matched_experiment_codes",
                "family_name",
                "availability_class",
                "available_column_examples",
                "known_at_rule",
                "active_direct_experiments",
                "active_lagged_experiments",
                "current_usage_mode",
                "current_issue_status",
            ]
        ].reset_index(drop=True)
    )

selected_columns = []
experiment_map = store.experiment_map()
for experiment_code in {repr(FS3_ALL_EXOGENOUS_CODES)}:
    experiment = experiment_map.get(experiment_code)
    if experiment is None:
        continue
    for column_name in list(experiment.direct_columns) + list(experiment.lagged_columns):
        if column_name not in selected_columns:
            selected_columns.append(column_name)

if not selected_columns:
    print("No selected exogenous columns were found in the current feature store.")
else:
    values = store.values.set_index("timestamp_utc")[selected_columns].copy()
    known_at = store.known_at.set_index("timestamp_utc")[selected_columns].copy()
    validation_start = pd.Timestamp("2023-10-01", tz="UTC")
    test_end = pd.Timestamp("2025-09-30 23:00:00", tz="UTC")
    values = values.loc[(values.index >= validation_start) & (values.index <= test_end)].copy()
    known_at = known_at.reindex(values.index)

    coverage_rows = []
    for column_name in selected_columns:
        series = values[column_name]
        known_series = pd.to_datetime(known_at[column_name], utc=True, errors="coerce") if column_name in known_at.columns else pd.Series(index=values.index, dtype="datetime64[ns, UTC]")
        coverage_rows.append({{
            "column_name": column_name,
            "non_null_rows": int(series.notna().sum()),
            "coverage_pct": float(series.notna().mean() * 100.0),
            "first_timestamp_utc": series.dropna().index.min(),
            "last_timestamp_utc": series.dropna().index.max(),
            "latest_known_at_utc": known_series.dropna().max(),
        }})
    display(pd.DataFrame(coverage_rows).sort_values(["coverage_pct", "column_name"], ascending=[False, True]).reset_index(drop=True))

    plot_columns = [column_name for column_name in selected_columns if values[column_name].notna().any()][:6]
    if plot_columns:
        plot_frame = values[plot_columns].dropna(how="all").tail(24 * 14)
        if plot_frame.empty:
            print("The selected exogenous columns do not have enough recent non-null data for a quick preview plot.")
        else:
            fig, ax = plt.subplots(figsize=(12, 4.8))
            plot_frame.plot(ax=ax, linewidth=1.1)
            ax.set_title("{model_label} FS3 all-exogenous inputs: last 14 days with available data")
            ax.set_xlabel("Timestamp (UTC)")
            ax.set_ylabel("Value")
            ax.grid(True, alpha=0.25)
            ax.legend(loc="upper left", fontsize=8, ncol=2)
            display(fig)
            plt.close(fig)
""".strip()


def fs3_combo_run_summary_cell(model_family: str) -> str:
    current_model = fs3_combo_model_name(model_family)
    focus_models = ["naive_previous_week", "naive_previous_year", "lear_fs2", "xgboost_fs2", current_model]
    return optional_run_summary_cell(fs3_combo_benchmark_run_label(model_family), focus_models)


def fs3_staged_execution_toggle_cell(model_family: str, run_label: str) -> str:
    return f"""
ALLOW_HEAVY_RERUN = False
FEATURE_VALUE_STEP = "ablation"
RUN_STAGE_A = True
RUN_LAYER_1 = True
RUN_LAYER_2 = False
RUN_DIAGNOSTICS = False

LAYER_2_TARGET_BLOCKS = {{
    "domestic_day_ahead_fundamentals": False,
    "neighbor_only_day_ahead_fundamentals": False,
    "domestic_historical_fundamentals": False,
    "neighbor_only_historical_fundamentals": False,
    "engineered_endogenous_history_stats": False,
    "weekly_same_hour_lag_structure": False,
    "structural_capacity": False,
}}

selected_layer2_targets = [
    block_name
    for block_name, enabled in LAYER_2_TARGET_BLOCKS.items()
    if bool(enabled)
]

if ALLOW_HEAVY_RERUN:
    estimate = estimate_run_duration_seconds(output_root, "{run_label}")
    if estimate is not None:
        print(
            "Heavy rerun warning: latest comparable parent run "
            f"{{estimate['run_id']}} suggests about {{format_duration(float(estimate['estimate_seconds']))}} for one full benchmark pass."
        )
    else:
        print("Heavy rerun warning: no comparable runtime estimate was found for the parent benchmark.")

    ablation_schemes = []
    if RUN_STAGE_A:
        ablation_schemes.append("stage_a_top_level")
    if RUN_LAYER_1:
        ablation_schemes.append("layer1_mutually_exclusive")
    if RUN_LAYER_2 and selected_layer2_targets:
        ablation_schemes.append("layer2_subgroups")

    if not ablation_schemes:
        raise RuntimeError("At least one of RUN_STAGE_A, RUN_LAYER_1, or RUN_LAYER_2 must be enabled.")

    command = [
        sys.executable,
        str(PACKAGE_ROOT / "run_fs3_ordered_benchmarks.py"),
        "--execution-mode",
        "feature_value",
        "--feature-value-step",
        FEATURE_VALUE_STEP,
        "--stage",
        "combo",
        "--feature-value-model-family",
        "{model_family}",
        "--ablation-schemes",
        *ablation_schemes,
    ]
    if RUN_LAYER_2 and selected_layer2_targets:
        command.extend(["--layer2-target-block", *selected_layer2_targets])

    started = time.perf_counter()
    run_command_with_live_output(command)
    elapsed_seconds = time.perf_counter() - started
    print(f"Actual wall-clock time: {{format_duration(elapsed_seconds)}}")
else:
    print("Rerun skipped. Set ALLOW_HEAVY_RERUN = True only when you are ready to execute the finalized pipeline.")
    print(f"Current FEATURE_VALUE_STEP setting: {{FEATURE_VALUE_STEP}}")
    print(f"Stage A enabled: {{RUN_STAGE_A}}")
    print(f"Layer 1 enabled: {{RUN_LAYER_1}}")
    print(f"Layer 2 enabled: {{RUN_LAYER_2}}")
    print(f"Layer 2 targets: {{selected_layer2_targets or 'none'}}")
    print(f"Diagnostics enabled: {{RUN_DIAGNOSTICS}}")
""".strip()


def fs3_staged_ablation_setup_cell(parent_run_label: str, model_family: str) -> str:
    return f"""
from matplotlib import pyplot as plt
from IPython.display import Markdown

from hourly_da.core.ablation_blocks import (
    SCHEME_NAME_LAYER_1,
    SCHEME_NAME_LAYER_2,
    SCHEME_NAME_STAGE_A,
    supported_layer2_target_blocks,
)
from hourly_da.notebook_support import (
    ablation_effect_label,
    annotate_ablation_metric_slice,
    apply_notebook_display_defaults,
    apply_standard_matplotlib_style,
    compute_fs3_parent_block_diagnostics,
    load_fs3_ablation_bundle,
    plot_feature_family_delta_bars,
    plot_feature_family_heatmap,
    plot_feature_family_origin_stability,
    select_feature_family_metric_slice,
    summarize_fs3_ablation_availability,
)

apply_notebook_display_defaults()
apply_standard_matplotlib_style()

FS3_PARENT_RUN_LABEL = "{parent_run_label}"
FS3_MODEL_FAMILY = "{model_family}"
FS3_MODEL_LABEL = "{model_family.title()}"
PRIMARY_SPLIT = "validation"
PRIMARY_METRIC = "mae"
VISIBLE_REPORTING_LEVELS = ("d_only", "stitched_all_horizon")

_fs3_store = load_external_feature_store(config)
_layer2_supported_targets = supported_layer2_target_blocks(_fs3_store.experiment_map())
FS3_PARENT_SPECS = [
    {{
        "parent_run_label": FS3_PARENT_RUN_LABEL,
        "model_family": FS3_MODEL_FAMILY,
        "model_label": FS3_MODEL_LABEL,
    }}
]
FS3_SCHEME_REQUESTS = [
    {{"scheme_name": SCHEME_NAME_STAGE_A, "target_block": None}},
    {{"scheme_name": SCHEME_NAME_LAYER_1, "target_block": None}},
]
FS3_SCHEME_REQUESTS.extend(
    {{"scheme_name": SCHEME_NAME_LAYER_2, "target_block": target_block}}
    for target_block in _layer2_supported_targets
)

FS3_ABLATION_AVAILABILITY = summarize_fs3_ablation_availability(
    output_root,
    config,
    parent_specs=FS3_PARENT_SPECS,
    scheme_requests=FS3_SCHEME_REQUESTS,
)

FS3_ABLATION_BUNDLES = {{}}
for request in FS3_SCHEME_REQUESTS:
    key = (str(request["scheme_name"]), str(request["target_block"] or ""))
    bundle = load_fs3_ablation_bundle(
        output_root,
        config,
        parent_run_label=FS3_PARENT_RUN_LABEL,
        model_family=FS3_MODEL_FAMILY,
        scheme_name=str(request["scheme_name"]),
        target_block=str(request["target_block"]) if request["target_block"] else None,
        store=_fs3_store,
    )
    if bundle is not None:
        FS3_ABLATION_BUNDLES[key] = bundle
""".strip()


def fs3_ablation_availability_cell() -> str:
    return """
availability_view = FS3_ABLATION_AVAILABILITY[
    [
        "model_label",
        "scheme_name",
        "layer_name",
        "target_block",
        "aggregate_run_label",
        "run_id",
        "availability_status",
        "latest_timestamp_label",
        "status_note",
    ]
].rename(
    columns={
        "model_label": "Model",
        "scheme_name": "Scheme",
        "layer_name": "Layer",
        "target_block": "Layer 2 target",
        "aggregate_run_label": "Aggregate run label",
        "run_id": "Run id",
        "availability_status": "Status",
        "latest_timestamp_label": "Latest timestamp",
        "status_note": "Status note",
    }
)
display(availability_view.style.hide(axis="index"))

legacy_rows = FS3_ABLATION_AVAILABILITY[
    FS3_ABLATION_AVAILABILITY["availability_status"].isin(["legacy_incompatible", "invalid", "incomplete"])
].copy()
if not legacy_rows.empty:
    display(
        Markdown(
            "Current compatibility gate: old FS3 combo ablation runs are excluded whenever the saved scheme hash, "
            "feature taxonomy hash, or stored preflight no longer matches the current code. "
            "That includes runs produced before the domestic/crossborder FS3 taxonomy fix."
        )
    )
""".strip()


def fs3_scheme_report_cell(
    scheme_name: str,
    *,
    target_block: str | None = None,
    include_layer2_candidates: bool = False,
) -> str:
    key_target = target_block or ""
    title_value = target_block or scheme_name
    return f"""
bundle = FS3_ABLATION_BUNDLES.get(({repr(scheme_name)}, {repr(key_target)}))

if bundle is None:
    print("No compatible saved bundle is available for this section yet.")
else:
    metadata = bundle["metadata"]
    preflight_summary = bundle["preflight_summary"].copy()
    preflight_block_sizes = bundle["preflight_block_sizes"].copy()
    display(
        pd.DataFrame(
            [
                {{
                    "Scheme": metadata.get("ablation_scheme", {{}}).get("display_name", "{title_value}"),
                    "Layer": metadata.get("layer_name", ""),
                    "Layer 2 target": metadata.get("target_block", ""),
                    "Parent run": metadata.get("parent_run_id", ""),
                    "Aggregate run": metadata.get("run_id", ""),
                    "Scheme hash": metadata.get("scheme_hash", ""),
                    "Feature taxonomy hash": metadata.get("feature_taxonomy_hash", ""),
                    "Preflight valid": bool(metadata.get("preflight_valid", False)),
                }}
            ]
        )
    )
    display(preflight_summary)
    display(preflight_block_sizes[["branch_name", "block_name", "block_size", "is_zero_size_block"]])

    if not preflight_summary["valid"].astype(bool).all():
        raise RuntimeError("The stored preflight for this ablation scheme is invalid. Rerun the compatible workflow before interpreting results.")

    stage_candidates = set()
    for reporting_level in VISIBLE_REPORTING_LEVELS:
        metric_slice = select_feature_family_metric_slice(
            bundle["summary"],
            split=PRIMARY_SPLIT,
            reporting_level=reporting_level,
            metric=PRIMARY_METRIC,
        )
        display(Markdown(f"### Validation / {{reporting_level.replace('_', ' ').title()}}"))
        if metric_slice.empty:
            print("No rows are available for this reporting lens yet.")
            continue

        annotated = annotate_ablation_metric_slice(metric_slice)
        display(
            annotated[
                [
                    "feature_family",
                    "parent_value",
                    "child_value",
                    "delta",
                    "relative_delta",
                    "effect_label",
                ]
            ]
            .rename(
                columns={{
                    "feature_family": "Block",
                    "parent_value": "Parent value",
                    "child_value": "Child value",
                    "delta": "Delta",
                    "relative_delta": "Relative delta",
                    "effect_label": "Interpretation",
                }}
            )
            .style
            .format(
                {{
                    "Parent value": "{{:.4f}}",
                    "Child value": "{{:.4f}}",
                    "Delta": "{{:+.4f}}",
                    "Relative delta": "{{:+.3%}}",
                }}
            )
            .hide(axis="index")
        )

        bucket_rows = []
        for bucket_name in [
            "strong_helpful",
            "mild_helpful",
            "near_zero_uncertain",
            "mild_harmful",
            "strong_harmful",
        ]:
            bucket_blocks = annotated.loc[
                annotated["effect_bucket"].astype(str) == bucket_name,
                "feature_family",
            ].astype(str).tolist()
            bucket_rows.append(
                {{
                    "Bucket": ablation_effect_label(bucket_name),
                    "Blocks": ", ".join(bucket_blocks) if bucket_blocks else "-",
                }}
            )
            if bucket_name in {{"mild_helpful", "near_zero_uncertain", "mild_harmful"}}:
                stage_candidates.update(bucket_blocks)
        display(pd.DataFrame(bucket_rows))

        fig = plot_feature_family_delta_bars(annotated)
        if fig is not None:
            display(fig)
            plt.close(fig)

        heatmap_fig = plot_feature_family_heatmap(annotated)
        if heatmap_fig is not None:
            display(heatmap_fig)
            plt.close(heatmap_fig)

        stability_fig = plot_feature_family_origin_stability(
            bundle["by_origin"],
            split=PRIMARY_SPLIT,
            reporting_level=reporting_level,
            metric=PRIMARY_METRIC,
        )
        if stability_fig is not None:
            display(stability_fig)
            plt.close(stability_fig)

    if {str(include_layer2_candidates)}:
        display(
            pd.DataFrame(
                [
                    {{
                        "Blocks worth optional Layer 2 follow-up": ", ".join(sorted(stage_candidates)) if stage_candidates else "-",
                    }}
                ]
            )
        )
""".strip()


def fs3_diagnostics_report_cell(parent_run_label: str, model_family: str) -> str:
    return f"""
if not RUN_DIAGNOSTICS:
    print("Diagnostics are disabled by the notebook config.")
else:
    diagnostics = compute_fs3_parent_block_diagnostics(
        config,
        parent_run_label="{parent_run_label}",
        model_family="{model_family}",
        split_name="validation",
        prepared_bundle=None,
    )
    display(diagnostics["reference"])
    if not diagnostics["tables"]:
        print("No lightweight diagnostics were produced for the representative validation fit.")
    else:
        for diagnostic_block in diagnostics["tables"]:
            branch_name = diagnostic_block["branch_name"]
            diagnostic_type = diagnostic_block["diagnostic_type"]
            table = diagnostic_block["table"]
            display(Markdown(f"### {{branch_name.replace('_', ' ').title()}} / {{diagnostic_type.replace('_', ' ').title()}}"))
            if diagnostic_type == "lear_coefficients":
                display(
                    table.style
                    .format(
                        {{
                            "sum_abs_standardized_coefficient": "{{:.4f}}",
                        }}
                    )
                    .hide(axis="index")
                )
            else:
                display(
                    table.style
                    .format(
                        {{
                            "total_gain": "{{:.4f}}",
                            "total_split_count": "{{:.0f}}",
                        }}
                    )
                    .hide(axis="index")
                )
""".strip()


def fs3_layer2_results_cell() -> str:
    return """
available_layer2 = FS3_ABLATION_AVAILABILITY[
    (FS3_ABLATION_AVAILABILITY["scheme_name"] == "layer2_subgroups")
    & (FS3_ABLATION_AVAILABILITY["availability_status"] == "available")
].copy()

if available_layer2.empty:
    print("No compatible Layer 2 subgroup bundles are available yet.")
else:
    for layer2_row in available_layer2.to_dict(orient="records"):
        target_block = str(layer2_row["target_block"])
        bundle = FS3_ABLATION_BUNDLES.get(("layer2_subgroups", target_block))
        if bundle is None:
            continue
        display(Markdown(f"### {target_block.replace('_', ' ').title()}"))
        display(bundle["preflight_summary"])
        metric_rows = []
        for reporting_level in VISIBLE_REPORTING_LEVELS:
            metric_slice = select_feature_family_metric_slice(
                bundle["summary"],
                split=PRIMARY_SPLIT,
                reporting_level=reporting_level,
                metric=PRIMARY_METRIC,
            )
            if metric_slice.empty:
                continue
            annotated = annotate_ablation_metric_slice(metric_slice)
            annotated["reporting_level"] = reporting_level
            metric_rows.append(annotated)
        if not metric_rows:
            print("No validation rows are available for this Layer 2 target.")
            continue
        layer2_table = pd.concat(metric_rows, ignore_index=True)
        display(
            layer2_table[
                [
                    "reporting_level",
                    "feature_family",
                    "parent_value",
                    "child_value",
                    "delta",
                    "relative_delta",
                    "effect_label",
                ]
            ]
            .rename(
                columns={
                    "reporting_level": "Reporting level",
                    "feature_family": "Subgroup",
                    "parent_value": "Parent value",
                    "child_value": "Child value",
                    "delta": "Delta",
                    "relative_delta": "Relative delta",
                    "effect_label": "Interpretation",
                }
            )
            .style
            .format(
                {
                    "Parent value": "{:.4f}",
                    "Child value": "{:.4f}",
                    "Delta": "{:+.4f}",
                    "Relative delta": "{:+.3%}",
                }
            )
            .hide(axis="index")
        )
""".strip()


def fs3_combined_setup_cell() -> str:
    return f"""
from IPython.display import Markdown

from hourly_da.core.ablation_blocks import (
    SCHEME_NAME_LAYER_1,
    SCHEME_NAME_LAYER_2,
    SCHEME_NAME_STAGE_A,
    supported_layer2_target_blocks,
)
from hourly_da.notebook_support import (
    ablation_effect_label,
    annotate_ablation_metric_slice,
    apply_notebook_display_defaults,
    compute_fs3_parent_block_diagnostics,
    load_fs3_ablation_report_dataset,
    select_feature_family_metric_slice,
    summarize_ablation_cross_model,
)

apply_notebook_display_defaults()

RUN_DIAGNOSTICS = False
PRIMARY_SPLIT = "validation"
PRIMARY_METRIC = "mae"
VISIBLE_REPORTING_LEVELS = ("d_only", "stitched_all_horizon")

_combined_store = load_external_feature_store(config)
_combined_layer2_targets = supported_layer2_target_blocks(_combined_store.experiment_map())
FS3_COMBINED_PARENT_SPECS = [
    {{
        "parent_run_label": "{FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL}",
        "model_family": "lear",
        "model_label": "LEAR",
    }},
    {{
        "parent_run_label": "{FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL}",
        "model_family": "xgboost",
        "model_label": "XGBoost",
    }},
]
FS3_COMBINED_SCHEME_REQUESTS = [
    {{"scheme_name": SCHEME_NAME_STAGE_A, "target_block": None}},
    {{"scheme_name": SCHEME_NAME_LAYER_1, "target_block": None}},
]
FS3_COMBINED_SCHEME_REQUESTS.extend(
    {{"scheme_name": SCHEME_NAME_LAYER_2, "target_block": target_block}}
    for target_block in _combined_layer2_targets
)

FS3_COMBINED_REPORT = load_fs3_ablation_report_dataset(
    output_root,
    config,
    parent_specs=FS3_COMBINED_PARENT_SPECS,
    scheme_requests=FS3_COMBINED_SCHEME_REQUESTS,
)
FS3_COMBINED_AVAILABILITY = FS3_COMBINED_REPORT["availability"]
FS3_COMBINED_BUNDLES = FS3_COMBINED_REPORT["bundles"]
FS3_COMBINED_SUMMARY = FS3_COMBINED_REPORT["summary"]
FS3_COMBINED_BY_ORIGIN = FS3_COMBINED_REPORT["by_origin"]
""".strip()


def fs3_combined_availability_cell() -> str:
    return """
availability_view = FS3_COMBINED_AVAILABILITY[
    [
        "model_label",
        "scheme_name",
        "layer_name",
        "target_block",
        "availability_status",
        "latest_timestamp_label",
        "status_note",
    ]
].rename(
    columns={
        "model_label": "Model",
        "scheme_name": "Scheme",
        "layer_name": "Layer",
        "target_block": "Layer 2 target",
        "availability_status": "Status",
        "latest_timestamp_label": "Latest timestamp",
        "status_note": "Status note",
    }
)
display(availability_view.style.hide(axis="index"))

display(
    Markdown(
        "Active synthesis scope: only compatible FS3 combo staged-ablation bundles are included below. "
        "Legacy FS1/FS2 smoke contexts and old incompatible FS3 bundles are kept out of the thesis-grade path by default."
    )
)
""".strip()


def fs3_combined_scheme_synthesis_cell(scheme_name: str) -> str:
    return f"""
scheme_summary = FS3_COMBINED_SUMMARY[
    FS3_COMBINED_SUMMARY["scheme_name"].astype(str) == {repr(scheme_name)}
].copy()

if scheme_summary.empty:
    print("No compatible saved results are available for this layer yet.")
else:
    for reporting_level in VISIBLE_REPORTING_LEVELS:
        metric_slice = select_feature_family_metric_slice(
            scheme_summary,
            split=PRIMARY_SPLIT,
            reporting_level=reporting_level,
            metric=PRIMARY_METRIC,
        )
        display(Markdown(f"### Validation / {{reporting_level.replace('_', ' ').title()}}"))
        if metric_slice.empty:
            print("No rows are available for this reporting lens.")
            continue

        annotated = annotate_ablation_metric_slice(metric_slice)
        model_view = annotated[
            [
                "model_family",
                "feature_family",
                "parent_value",
                "child_value",
                "delta",
                "relative_delta",
                "effect_label",
            ]
        ].rename(
            columns={{
                "model_family": "Model family",
                "feature_family": "Block",
                "parent_value": "Parent value",
                "child_value": "Child value",
                "delta": "Delta",
                "relative_delta": "Relative delta",
                "effect_label": "Interpretation",
            }}
        )
        display(
            model_view.style
            .format(
                {{
                    "Parent value": "{{:.4f}}",
                    "Child value": "{{:.4f}}",
                    "Delta": "{{:+.4f}}",
                    "Relative delta": "{{:+.3%}}",
                }}
            )
            .hide(axis="index")
        )

        combined = summarize_ablation_cross_model(metric_slice)
        display(
            combined.rename(
                columns={{
                    "feature_family": "Block",
                    "models_available": "Models available",
                    "model_count": "Model count",
                    "mean_delta": "Mean delta",
                    "mean_relative_delta": "Mean relative delta",
                    "combined_label": "Combined classification",
                }}
            ).style
            .format(
                {{
                    "Mean delta": "{{:+.4f}}",
                    "Mean relative delta": "{{:+.3%}}",
                }}
            )
            .hide(axis="index")
        )
""".strip()


def fs3_combined_layer2_cell() -> str:
    return """
available_layer2 = FS3_COMBINED_SUMMARY[
    FS3_COMBINED_SUMMARY["scheme_name"].astype(str) == "layer2_subgroups"
].copy()

if available_layer2.empty:
    print("No compatible Layer 2 subgroup results are available yet.")
else:
    for target_block, group in available_layer2.groupby("target_block", dropna=False):
        display(Markdown(f"### {str(target_block).replace('_', ' ').title()}"))
        for reporting_level in VISIBLE_REPORTING_LEVELS:
            metric_slice = select_feature_family_metric_slice(
                group,
                split=PRIMARY_SPLIT,
                reporting_level=reporting_level,
                metric=PRIMARY_METRIC,
            )
            if metric_slice.empty:
                continue
            annotated = annotate_ablation_metric_slice(metric_slice)
            display(Markdown(f"#### {reporting_level.replace('_', ' ').title()}"))
            display(
                annotated[
                    [
                        "model_family",
                        "feature_family",
                        "delta",
                        "relative_delta",
                        "effect_label",
                    ]
                ]
                .rename(
                    columns={
                        "model_family": "Model family",
                        "feature_family": "Subgroup",
                        "delta": "Delta",
                        "relative_delta": "Relative delta",
                        "effect_label": "Interpretation",
                    }
                )
                .style
                .format({"Delta": "{:+.4f}", "Relative delta": "{:+.3%}"})
                .hide(axis="index")
            )
""".strip()


def fs3_combined_diagnostics_cell() -> str:
    return f"""
if not RUN_DIAGNOSTICS:
    print("Diagnostics are disabled for this notebook.")
else:
    for parent_spec in FS3_COMBINED_PARENT_SPECS:
        display(Markdown(f"### {{parent_spec['model_label']}}"))
        diagnostics = compute_fs3_parent_block_diagnostics(
            config,
            parent_run_label=str(parent_spec["parent_run_label"]),
            model_family=str(parent_spec["model_family"]),
            split_name="validation",
        )
        display(diagnostics["reference"])
        for diagnostic_block in diagnostics["tables"]:
            display(
                Markdown(
                    f"#### {{diagnostic_block['branch_name'].replace('_', ' ').title()}} / "
                    f"{{diagnostic_block['diagnostic_type'].replace('_', ' ').title()}}"
                )
            )
            table = diagnostic_block["table"]
            if diagnostic_block["diagnostic_type"] == "lear_coefficients":
                display(
                    table.style
                    .format({{"sum_abs_standardized_coefficient": "{{:.4f}}"}})
                    .hide(axis="index")
                )
            else:
                display(
                    table.style
                    .format({{"total_gain": "{{:.4f}}", "total_split_count": "{{:.0f}}"}})
                    .hide(axis="index")
                )
""".strip()


def _layer2_toggle_defaults(fs_level: str) -> dict[str, bool]:
    if fs_level == "FS2":
        return {
            "weekly_same_hour_lag_structure": False,
            "lag_differences": False,
            "rolling_regime_descriptors": False,
            "block_summary_statistics": False,
            "calendar_routine": False,
        }
    if fs_level == "FS3":
        return {
            "domestic_day_ahead_fundamentals": False,
            "neighbor_only_day_ahead_fundamentals": False,
            "domestic_historical_fundamentals": False,
            "neighbor_only_historical_fundamentals": False,
            "engineered_endogenous_history_stats": False,
            "weekly_same_hour_lag_structure": False,
            "structural_capacity": False,
        }
    raise ValueError(f"Unsupported staged ablation fs_level: {fs_level}")


def staged_execution_toggle_cell(fs_level: str, parent_run_label: str, model_family: str) -> str:
    return f"""
ALLOW_HEAVY_RERUN = False
RUN_STAGE_A = True
RUN_LAYER_1 = True
RUN_LAYER_2 = False
RUN_DIAGNOSTICS = False

LAYER_2_TARGET_BLOCKS = {repr(_layer2_toggle_defaults(fs_level))}

selected_layer2_targets = [
    block_name
    for block_name, enabled in LAYER_2_TARGET_BLOCKS.items()
    if bool(enabled)
]

if ALLOW_HEAVY_RERUN:
    estimate = estimate_run_duration_seconds(output_root, "{parent_run_label}")
    if estimate is not None:
        print(
            "Heavy rerun warning: latest comparable parent run "
            f"{{estimate['run_id']}} suggests about {{format_duration(float(estimate['estimate_seconds']))}} for one full benchmark pass."
        )
    else:
        print("Heavy rerun warning: no comparable runtime estimate was found for the parent benchmark.")

    ablation_schemes = []
    if RUN_STAGE_A:
        ablation_schemes.append("stage_a_top_level")
    if RUN_LAYER_1:
        ablation_schemes.append("layer1_mutually_exclusive")
    if RUN_LAYER_2 and selected_layer2_targets:
        ablation_schemes.append("layer2_subgroups")

    if not ablation_schemes:
        raise RuntimeError("At least one of RUN_STAGE_A, RUN_LAYER_1, or RUN_LAYER_2 must be enabled.")

    command = [
        sys.executable,
        str(PACKAGE_ROOT / "run_staged_block_ablation.py"),
        "--fs-level",
        "{fs_level}",
        "--model-family",
        "{model_family}",
        "--parent-run-label",
        "{parent_run_label}",
        "--ablation-schemes",
        *ablation_schemes,
    ]
    if RUN_LAYER_2 and selected_layer2_targets:
        command.extend(["--layer2-target-block", *selected_layer2_targets])

    started = time.perf_counter()
    run_command_with_live_output(command)
    elapsed_seconds = time.perf_counter() - started
    print(f"Actual wall-clock time: {{format_duration(elapsed_seconds)}}")
else:
    print("Rerun skipped. Set ALLOW_HEAVY_RERUN = True only when you are ready to execute the staged ablation.")
    print(f"Stage A enabled: {{RUN_STAGE_A}}")
    print(f"Layer 1 enabled: {{RUN_LAYER_1}}")
    print(f"Layer 2 enabled: {{RUN_LAYER_2}}")
    print(f"Layer 2 targets: {{selected_layer2_targets or 'none'}}")
    print(f"Diagnostics enabled: {{RUN_DIAGNOSTICS}}")
""".strip()


def staged_ablation_setup_cell(var_prefix: str, fs_level: str, parent_run_label: str, model_family: str) -> str:
    summarize_name = "summarize_fs2_ablation_availability" if fs_level == "FS2" else "summarize_fs3_ablation_availability"
    load_name = "load_fs2_ablation_bundle" if fs_level == "FS2" else "load_fs3_ablation_bundle"
    layer2_import = "supported_fs2_layer2_target_blocks" if fs_level == "FS2" else "supported_layer2_target_blocks"
    layer2_targets_code = (
        "_layer2_supported_targets = supported_fs2_layer2_target_blocks()"
        if fs_level == "FS2"
        else f"""
{var_prefix}_STORE = load_external_feature_store(config)
_layer2_supported_targets = supported_layer2_target_blocks({var_prefix}_STORE.experiment_map())
""".rstrip()
    )
    store_argument = "store=None" if fs_level == "FS2" else f"store={var_prefix}_STORE"
    return f"""
from matplotlib import pyplot as plt
from IPython.display import Markdown

from hourly_da.core.ablation_blocks import (
    SCHEME_NAME_LAYER_1,
    SCHEME_NAME_LAYER_2,
    SCHEME_NAME_STAGE_A,
    {layer2_import},
)
from hourly_da.notebook_support import (
    ablation_effect_label,
    annotate_ablation_metric_slice,
    apply_notebook_display_defaults,
    apply_standard_matplotlib_style,
    {load_name},
    plot_feature_family_delta_bars,
    plot_feature_family_heatmap,
    plot_feature_family_origin_stability,
    select_feature_family_metric_slice,
    {summarize_name},
)

apply_notebook_display_defaults()
apply_standard_matplotlib_style()

{var_prefix}_PARENT_RUN_LABEL = "{parent_run_label}"
{var_prefix}_MODEL_FAMILY = "{model_family}"
{var_prefix}_MODEL_LABEL = "{model_family.title()}"
PRIMARY_SPLIT = "validation"
PRIMARY_METRIC = "mae"
VISIBLE_REPORTING_LEVELS = ("d_only", "stitched_all_horizon")

{layer2_targets_code}
{var_prefix}_PARENT_SPECS = [
    {{
        "parent_run_label": {var_prefix}_PARENT_RUN_LABEL,
        "model_family": {var_prefix}_MODEL_FAMILY,
        "model_label": {var_prefix}_MODEL_LABEL,
    }}
]
{var_prefix}_SCHEME_REQUESTS = [
    {{"scheme_name": SCHEME_NAME_STAGE_A, "target_block": None}},
    {{"scheme_name": SCHEME_NAME_LAYER_1, "target_block": None}},
]
{var_prefix}_SCHEME_REQUESTS.extend(
    {{"scheme_name": SCHEME_NAME_LAYER_2, "target_block": target_block}}
    for target_block in _layer2_supported_targets
)

{var_prefix}_ABLATION_AVAILABILITY = {summarize_name}(
    output_root,
    config,
    parent_specs={var_prefix}_PARENT_SPECS,
    scheme_requests={var_prefix}_SCHEME_REQUESTS,
)

{var_prefix}_ABLATION_BUNDLES = {{}}
for request in {var_prefix}_SCHEME_REQUESTS:
    key = (str(request["scheme_name"]), str(request["target_block"] or ""))
    bundle = {load_name}(
        output_root,
        config,
        parent_run_label={var_prefix}_PARENT_RUN_LABEL,
        model_family={var_prefix}_MODEL_FAMILY,
        scheme_name=str(request["scheme_name"]),
        target_block=str(request["target_block"]) if request["target_block"] else None,
        {store_argument},
    )
    if bundle is not None:
        {var_prefix}_ABLATION_BUNDLES[key] = bundle
""".strip()


def staged_ablation_availability_cell(var_prefix: str) -> str:
    return f"""
availability_view = {var_prefix}_ABLATION_AVAILABILITY[
    [
        "model_label",
        "scheme_name",
        "layer_name",
        "target_block",
        "aggregate_run_label",
        "run_id",
        "availability_status",
        "latest_timestamp_label",
        "status_note",
    ]
].rename(
    columns={{
        "model_label": "Model",
        "scheme_name": "Scheme",
        "layer_name": "Layer",
        "target_block": "Layer 2 target",
        "aggregate_run_label": "Aggregate run label",
        "run_id": "Run id",
        "availability_status": "Status",
        "latest_timestamp_label": "Latest timestamp",
        "status_note": "Status note",
    }}
)
display(availability_view.style.hide(axis="index"))

legacy_rows = {var_prefix}_ABLATION_AVAILABILITY[
    {var_prefix}_ABLATION_AVAILABILITY["availability_status"].isin(["legacy_incompatible", "invalid", "incomplete"])
].copy()
if not legacy_rows.empty:
    display(
        Markdown(
            "Current compatibility gate: only saved staged-ablation bundles with matching scheme hash, "
            "feature taxonomy hash, and valid stored preflight are treated as active evidence."
        )
    )
""".strip()


def staged_scheme_report_cell(var_prefix: str, scheme_name: str, *, target_block: str | None = None, include_layer2_candidates: bool = False) -> str:
    key_target = target_block or ""
    title_value = target_block or scheme_name
    return f"""
bundle = {var_prefix}_ABLATION_BUNDLES.get(({repr(scheme_name)}, {repr(key_target)}))

if bundle is None:
    print("No compatible saved bundle is available for this section yet.")
else:
    metadata = bundle["metadata"]
    preflight_summary = bundle["preflight_summary"].copy()
    preflight_block_sizes = bundle["preflight_block_sizes"].copy()
    display(
        pd.DataFrame(
            [
                {{
                    "Scheme": metadata.get("ablation_scheme", {{}}).get("display_name", "{title_value}"),
                    "Layer": metadata.get("layer_name", ""),
                    "Layer 2 target": metadata.get("target_block", ""),
                    "Parent run": metadata.get("parent_run_id", ""),
                    "Aggregate run": metadata.get("run_id", ""),
                    "Scheme hash": metadata.get("scheme_hash", ""),
                    "Feature taxonomy hash": metadata.get("feature_taxonomy_hash", ""),
                    "Preflight valid": bool(metadata.get("preflight_valid", False)),
                }}
            ]
        )
    )
    display(preflight_summary)
    display(preflight_block_sizes[["branch_name", "block_name", "block_size", "is_zero_size_block"]])

    if not preflight_summary["valid"].astype(bool).all():
        raise RuntimeError("The stored preflight for this ablation scheme is invalid. Rerun the compatible workflow before interpreting results.")

    stage_candidates = set()
    for reporting_level in VISIBLE_REPORTING_LEVELS:
        metric_slice = select_feature_family_metric_slice(
            bundle["summary"],
            split=PRIMARY_SPLIT,
            reporting_level=reporting_level,
            metric=PRIMARY_METRIC,
        )
        display(Markdown(f"### Validation / {{reporting_level.replace('_', ' ').title()}}"))
        if metric_slice.empty:
            print("No rows are available for this reporting lens yet.")
            continue

        annotated = annotate_ablation_metric_slice(metric_slice)
        display(
            annotated[
                [
                    "feature_family",
                    "parent_value",
                    "child_value",
                    "delta",
                    "relative_delta",
                    "effect_label",
                ]
            ]
            .rename(
                columns={{
                    "feature_family": "Block",
                    "parent_value": "Parent value",
                    "child_value": "Child value",
                    "delta": "Delta",
                    "relative_delta": "Relative delta",
                    "effect_label": "Interpretation",
                }}
            )
            .style
            .format(
                {{
                    "Parent value": "{{:.4f}}",
                    "Child value": "{{:.4f}}",
                    "Delta": "{{:+.4f}}",
                    "Relative delta": "{{:+.3%}}",
                }}
            )
            .hide(axis="index")
        )

        bucket_rows = []
        for bucket_name in [
            "strong_helpful",
            "mild_helpful",
            "near_zero_uncertain",
            "mild_harmful",
            "strong_harmful",
        ]:
            bucket_blocks = annotated.loc[
                annotated["effect_bucket"].astype(str) == bucket_name,
                "feature_family",
            ].astype(str).tolist()
            bucket_rows.append(
                {{
                    "Bucket": ablation_effect_label(bucket_name),
                    "Blocks": ", ".join(bucket_blocks) if bucket_blocks else "-",
                }}
            )
            if bucket_name in {{"mild_helpful", "near_zero_uncertain", "mild_harmful"}}:
                stage_candidates.update(bucket_blocks)
        display(pd.DataFrame(bucket_rows))

        fig = plot_feature_family_delta_bars(annotated)
        if fig is not None:
            display(fig)
            plt.close(fig)

        heatmap_fig = plot_feature_family_heatmap(annotated)
        if heatmap_fig is not None:
            display(heatmap_fig)
            plt.close(heatmap_fig)

        stability_fig = plot_feature_family_origin_stability(
            bundle["by_origin"],
            split=PRIMARY_SPLIT,
            reporting_level=reporting_level,
            metric=PRIMARY_METRIC,
        )
        if stability_fig is not None:
            display(stability_fig)
            plt.close(stability_fig)

    if {str(include_layer2_candidates)}:
        display(
            pd.DataFrame(
                [
                    {{
                        "Blocks worth optional Layer 2 follow-up": ", ".join(sorted(stage_candidates)) if stage_candidates else "-",
                    }}
                ]
            )
        )
""".strip()


def staged_layer2_results_cell(var_prefix: str) -> str:
    return f"""
available_layer2 = {var_prefix}_ABLATION_AVAILABILITY[
    ({var_prefix}_ABLATION_AVAILABILITY["scheme_name"] == "layer2_subgroups")
    & ({var_prefix}_ABLATION_AVAILABILITY["availability_status"] == "available")
].copy()

if available_layer2.empty:
    print("No compatible Layer 2 subgroup bundles are available yet.")
else:
    for layer2_row in available_layer2.to_dict(orient="records"):
        target_block = str(layer2_row["target_block"])
        bundle = {var_prefix}_ABLATION_BUNDLES.get(("layer2_subgroups", target_block))
        if bundle is None:
            continue
        display(Markdown(f"### {{target_block.replace('_', ' ').title()}}"))
        display(bundle["preflight_summary"])
        metric_rows = []
        for reporting_level in VISIBLE_REPORTING_LEVELS:
            metric_slice = select_feature_family_metric_slice(
                bundle["summary"],
                split=PRIMARY_SPLIT,
                reporting_level=reporting_level,
                metric=PRIMARY_METRIC,
            )
            if metric_slice.empty:
                continue
            annotated = annotate_ablation_metric_slice(metric_slice)
            annotated["reporting_level"] = reporting_level
            metric_rows.append(annotated)
        if not metric_rows:
            print("No validation rows are available for this Layer 2 target.")
            continue
        layer2_table = pd.concat(metric_rows, ignore_index=True)
        display(
            layer2_table[
                [
                    "reporting_level",
                    "feature_family",
                    "parent_value",
                    "child_value",
                    "delta",
                    "relative_delta",
                    "effect_label",
                ]
            ]
            .rename(
                columns={{
                    "reporting_level": "Reporting level",
                    "feature_family": "Subgroup",
                    "parent_value": "Parent value",
                    "child_value": "Child value",
                    "delta": "Delta",
                    "relative_delta": "Relative delta",
                    "effect_label": "Interpretation",
                }}
            )
            .style
            .format(
                {{
                    "Parent value": "{{:.4f}}",
                    "Child value": "{{:.4f}}",
                    "Delta": "{{:+.4f}}",
                    "Relative delta": "{{:+.3%}}",
                }}
            )
            .hide(axis="index")
        )
""".strip()


def staged_diagnostics_report_cell(fs_level: str, parent_run_label: str, model_family: str) -> str:
    diagnostics_name = "compute_fs2_parent_block_diagnostics" if fs_level == "FS2" else "compute_fs3_parent_block_diagnostics"
    return f"""
from hourly_da.notebook_support import {diagnostics_name}

if not RUN_DIAGNOSTICS:
    print("Diagnostics are disabled by the notebook config.")
else:
    diagnostics = {diagnostics_name}(
        config,
        parent_run_label="{parent_run_label}",
        model_family="{model_family}",
        split_name="validation",
    )
    display(diagnostics["reference"])
    if not diagnostics["tables"]:
        print("No lightweight diagnostics were produced for the representative validation fit.")
    else:
        for diagnostic_block in diagnostics["tables"]:
            branch_name = diagnostic_block["branch_name"]
            diagnostic_type = diagnostic_block["diagnostic_type"]
            table = diagnostic_block["table"]
            display(Markdown(f"### {{branch_name.replace('_', ' ').title()}} / {{diagnostic_type.replace('_', ' ').title()}}"))
            if diagnostic_type == "lear_coefficients":
                display(
                    table.style
                    .format({{"sum_abs_standardized_coefficient": "{{:.4f}}"}})
                    .hide(axis="index")
                )
            else:
                display(
                    table.style
                    .format({{"total_gain": "{{:.4f}}", "total_split_count": "{{:.0f}}"}})
                    .hide(axis="index")
                )
""".strip()


def combined_staged_setup_cell(var_prefix: str, fs_level: str, parent_specs: list[dict[str, str]]) -> str:
    report_name = "load_fs2_ablation_report_dataset" if fs_level == "FS2" else "load_fs3_ablation_report_dataset"
    layer2_import = "supported_fs2_layer2_target_blocks" if fs_level == "FS2" else "supported_layer2_target_blocks"
    layer2_targets_code = (
        "_combined_layer2_targets = supported_fs2_layer2_target_blocks()"
        if fs_level == "FS2"
        else """
_combined_store = load_external_feature_store(config)
_combined_layer2_targets = supported_layer2_target_blocks(_combined_store.experiment_map())
""".rstrip()
    )
    return f"""
from IPython.display import Markdown

from hourly_da.core.ablation_blocks import (
    SCHEME_NAME_LAYER_1,
    SCHEME_NAME_LAYER_2,
    SCHEME_NAME_STAGE_A,
    {layer2_import},
)
from hourly_da.notebook_support import (
    ablation_effect_label,
    annotate_ablation_metric_slice,
    apply_notebook_display_defaults,
    {report_name},
    select_feature_family_metric_slice,
    summarize_ablation_cross_model,
)

apply_notebook_display_defaults()

RUN_DIAGNOSTICS = False
PRIMARY_SPLIT = "validation"
PRIMARY_METRIC = "mae"
VISIBLE_REPORTING_LEVELS = ("d_only", "stitched_all_horizon")

{layer2_targets_code}
{var_prefix}_PARENT_SPECS = {repr(parent_specs)}
{var_prefix}_SCHEME_REQUESTS = [
    {{"scheme_name": SCHEME_NAME_STAGE_A, "target_block": None}},
    {{"scheme_name": SCHEME_NAME_LAYER_1, "target_block": None}},
]
{var_prefix}_SCHEME_REQUESTS.extend(
    {{"scheme_name": SCHEME_NAME_LAYER_2, "target_block": target_block}}
    for target_block in _combined_layer2_targets
)

{var_prefix}_REPORT = {report_name}(
    output_root,
    config,
    parent_specs={var_prefix}_PARENT_SPECS,
    scheme_requests={var_prefix}_SCHEME_REQUESTS,
)
{var_prefix}_AVAILABILITY = {var_prefix}_REPORT["availability"]
{var_prefix}_BUNDLES = {var_prefix}_REPORT["bundles"]
{var_prefix}_SUMMARY = {var_prefix}_REPORT["summary"]
{var_prefix}_BY_ORIGIN = {var_prefix}_REPORT["by_origin"]
""".strip()


def combined_staged_availability_cell(var_prefix: str, scope_label: str) -> str:
    return f"""
availability_view = {var_prefix}_AVAILABILITY[
    [
        "model_label",
        "scheme_name",
        "layer_name",
        "target_block",
        "availability_status",
        "latest_timestamp_label",
        "status_note",
    ]
].rename(
    columns={{
        "model_label": "Model",
        "scheme_name": "Scheme",
        "layer_name": "Layer",
        "target_block": "Layer 2 target",
        "availability_status": "Status",
        "latest_timestamp_label": "Latest timestamp",
        "status_note": "Status note",
    }}
)
display(availability_view.style.hide(axis="index"))

display(
    Markdown(
        "Active synthesis scope for {scope_label}: only compatible staged-ablation bundles are included below. "
        "Saved aggregates with stale scheme hashes, stale taxonomy hashes, or invalid stored preflight are excluded."
    )
)
""".strip()


def combined_staged_scheme_synthesis_cell(var_prefix: str, scheme_name: str) -> str:
    return f"""
scheme_summary = {var_prefix}_SUMMARY[
    {var_prefix}_SUMMARY["scheme_name"].astype(str) == {repr(scheme_name)}
].copy()

if scheme_summary.empty:
    print("No compatible saved results are available for this layer yet.")
else:
    for reporting_level in VISIBLE_REPORTING_LEVELS:
        metric_slice = select_feature_family_metric_slice(
            scheme_summary,
            split=PRIMARY_SPLIT,
            reporting_level=reporting_level,
            metric=PRIMARY_METRIC,
        )
        display(Markdown(f"### Validation / {{reporting_level.replace('_', ' ').title()}}"))
        if metric_slice.empty:
            print("No rows are available for this reporting lens.")
            continue

        annotated = annotate_ablation_metric_slice(metric_slice)
        model_view = annotated[
            [
                "model_family",
                "feature_family",
                "parent_value",
                "child_value",
                "delta",
                "relative_delta",
                "effect_label",
            ]
        ].rename(
            columns={{
                "model_family": "Model family",
                "feature_family": "Block",
                "parent_value": "Parent value",
                "child_value": "Child value",
                "delta": "Delta",
                "relative_delta": "Relative delta",
                "effect_label": "Interpretation",
            }}
        )
        display(
            model_view.style
            .format(
                {{
                    "Parent value": "{{:.4f}}",
                    "Child value": "{{:.4f}}",
                    "Delta": "{{:+.4f}}",
                    "Relative delta": "{{:+.3%}}",
                }}
            )
            .hide(axis="index")
        )

        combined = summarize_ablation_cross_model(metric_slice)
        display(
            combined.rename(
                columns={{
                    "feature_family": "Block",
                    "models_available": "Models available",
                    "model_count": "Model count",
                    "mean_delta": "Mean delta",
                    "mean_relative_delta": "Mean relative delta",
                    "combined_label": "Combined classification",
                }}
            ).style
            .format(
                {{
                    "Mean delta": "{{:+.4f}}",
                    "Mean relative delta": "{{:+.3%}}",
                }}
            )
            .hide(axis="index")
        )
""".strip()


def combined_staged_layer2_cell(var_prefix: str) -> str:
    return f"""
available_layer2 = {var_prefix}_SUMMARY[
    {var_prefix}_SUMMARY["scheme_name"].astype(str) == "layer2_subgroups"
].copy()

if available_layer2.empty:
    print("No compatible Layer 2 subgroup results are available yet.")
else:
    for target_block, group in available_layer2.groupby("target_block", dropna=False):
        display(Markdown(f"### {{str(target_block).replace('_', ' ').title()}}"))
        for reporting_level in VISIBLE_REPORTING_LEVELS:
            metric_slice = select_feature_family_metric_slice(
                group,
                split=PRIMARY_SPLIT,
                reporting_level=reporting_level,
                metric=PRIMARY_METRIC,
            )
            if metric_slice.empty:
                continue
            annotated = annotate_ablation_metric_slice(metric_slice)
            display(Markdown(f"#### {{reporting_level.replace('_', ' ').title()}}"))
            display(
                annotated[
                    [
                        "model_family",
                        "feature_family",
                        "delta",
                        "relative_delta",
                        "effect_label",
                    ]
                ]
                .rename(
                    columns={{
                        "model_family": "Model family",
                        "feature_family": "Subgroup",
                        "delta": "Delta",
                        "relative_delta": "Relative delta",
                        "effect_label": "Interpretation",
                    }}
                )
                .style
                .format({{"Delta": "{{:+.4f}}", "Relative delta": "{{:+.3%}}"}})
                .hide(axis="index")
            )
""".strip()


def combined_staged_diagnostics_cell(var_prefix: str, fs_level: str) -> str:
    diagnostics_name = "compute_fs2_parent_block_diagnostics" if fs_level == "FS2" else "compute_fs3_parent_block_diagnostics"
    return f"""
from hourly_da.notebook_support import {diagnostics_name}

if not RUN_DIAGNOSTICS:
    print("Diagnostics are disabled for this notebook.")
else:
    for parent_spec in {var_prefix}_PARENT_SPECS:
        display(Markdown(f"### {{parent_spec['model_label']}}"))
        diagnostics = {diagnostics_name}(
            config,
            parent_run_label=str(parent_spec["parent_run_label"]),
            model_family=str(parent_spec["model_family"]),
            split_name="validation",
        )
        display(diagnostics["reference"])
        for diagnostic_block in diagnostics["tables"]:
            display(
                Markdown(
                    f"#### {{diagnostic_block['branch_name'].replace('_', ' ').title()}} / "
                    f"{{diagnostic_block['diagnostic_type'].replace('_', ' ').title()}}"
                )
            )
            table = diagnostic_block["table"]
            if diagnostic_block["diagnostic_type"] == "lear_coefficients":
                display(
                    table.style
                    .format({{"sum_abs_standardized_coefficient": "{{:.4f}}"}})
                    .hide(axis="index")
                )
            else:
                display(
                    table.style
                    .format({{"total_gain": "{{:.4f}}", "total_split_count": "{{:.0f}}"}})
                    .hide(axis="index")
                )
""".strip()


def pruning_execution_cell(
    fs_level: str,
    baseline_specs: list[dict[str, str]],
    candidate_specs: list[dict[str, str]],
    *,
    comparison_run_label: str | None = None,
) -> str:
    enable_comparison_refresh = comparison_run_label is not None and fs_level == "FS2"
    comparison_refresh_default = "False" if enable_comparison_refresh else "None"
    return f"""
ALLOW_HEAVY_RERUN = False
RUN_CANDIDATE_PARENT_BENCHMARKS = False
RUN_CANDIDATE_ABLATION = False
REFRESH_CANDIDATE_COMPARISON = {comparison_refresh_default}
RUN_STAGE_A = True
RUN_LAYER_1 = True
RUN_LAYER_2 = False

LAYER_2_TARGET_BLOCKS = {repr(_layer2_toggle_defaults(fs_level))}
CANDIDATE_BLOCK_SELECTION = {{
    "lear": [],
    "xgboost": [],
}}

BASELINE_PARENT_SPECS = {repr(baseline_specs)}
CANDIDATE_PARENT_SPECS = {repr(candidate_specs)}
selected_layer2_targets = [
    block_name
    for block_name, enabled in LAYER_2_TARGET_BLOCKS.items()
    if bool(enabled)
]

if ALLOW_HEAVY_RERUN:
    if RUN_CANDIDATE_PARENT_BENCHMARKS:
        for baseline_spec, candidate_spec in zip(BASELINE_PARENT_SPECS, CANDIDATE_PARENT_SPECS):
            model_family = str(baseline_spec["model_family"])
            excluded_blocks = [str(value) for value in CANDIDATE_BLOCK_SELECTION.get(model_family, []) if str(value).strip()]
            if not excluded_blocks:
                print(f"Skipping {{model_family}} candidate parent rerun because no blocks were selected.")
                continue
            command = [
                sys.executable,
                str(PACKAGE_ROOT / "run_revised_parent_benchmark.py"),
                "--fs-level",
                "{fs_level}",
                "--model-family",
                model_family,
                "--parent-run-label",
                str(baseline_spec["parent_run_label"]),
                "--run-label",
                str(candidate_spec["parent_run_label"]),
                "--ablation-scheme",
                "layer1_mutually_exclusive",
                "--excluded-blocks",
                *excluded_blocks,
            ]
            run_command_with_live_output(command)

    if RUN_CANDIDATE_ABLATION:
        ablation_schemes = []
        if RUN_STAGE_A:
            ablation_schemes.append("stage_a_top_level")
        if RUN_LAYER_1:
            ablation_schemes.append("layer1_mutually_exclusive")
        if RUN_LAYER_2 and selected_layer2_targets:
            ablation_schemes.append("layer2_subgroups")
        if not ablation_schemes:
            raise RuntimeError("At least one staged ablation layer must be enabled for the candidate rerun.")

        for candidate_spec in CANDIDATE_PARENT_SPECS:
            model_family = str(candidate_spec["model_family"])
            excluded_blocks = [str(value) for value in CANDIDATE_BLOCK_SELECTION.get(model_family, []) if str(value).strip()]
            if not excluded_blocks:
                print(f"Skipping {{model_family}} candidate ablation because no candidate block set was selected.")
                continue
            command = [
                sys.executable,
                str(PACKAGE_ROOT / "run_staged_block_ablation.py"),
                "--fs-level",
                "{fs_level}",
                "--model-family",
                model_family,
                "--parent-run-label",
                str(candidate_spec["parent_run_label"]),
                "--ablation-schemes",
                *ablation_schemes,
            ]
            if RUN_LAYER_2 and selected_layer2_targets:
                command.extend(["--layer2-target-block", *selected_layer2_targets])
            run_command_with_live_output(command)

    if {str(enable_comparison_refresh)} and bool(REFRESH_CANDIDATE_COMPARISON):
        def _active_run_label(model_family: str) -> str:
            selected_blocks = [str(value) for value in CANDIDATE_BLOCK_SELECTION.get(model_family, []) if str(value).strip()]
            if selected_blocks:
                matching = [spec for spec in CANDIDATE_PARENT_SPECS if str(spec["model_family"]) == model_family]
                if matching:
                    return str(matching[0]["parent_run_label"])
            matching = [spec for spec in BASELINE_PARENT_SPECS if str(spec["model_family"]) == model_family]
            if not matching:
                raise RuntimeError(f"No baseline spec was found for model family {{model_family}}.")
            return str(matching[0]["parent_run_label"])

        command = [
            sys.executable,
            str(PACKAGE_ROOT / "run_model_comparison.py"),
            "--fs-level",
            "{fs_level}",
            "--run-label",
            "{comparison_run_label or ''}",
            "--lear-run-label",
            _active_run_label("lear"),
            "--xgboost-run-label",
            _active_run_label("xgboost"),
            "--prophet-run-label",
            "prophet_benchmark",
        ]
        run_command_with_live_output(command)
else:
    print("Candidate reruns are disabled. Set ALLOW_HEAVY_RERUN = True when you are ready to validate a pruning or redesign choice.")
    print(f"RUN_CANDIDATE_PARENT_BENCHMARKS={{RUN_CANDIDATE_PARENT_BENCHMARKS}}")
    print(f"RUN_CANDIDATE_ABLATION={{RUN_CANDIDATE_ABLATION}}")
    if {str(enable_comparison_refresh)}:
        print(f"REFRESH_CANDIDATE_COMPARISON={{REFRESH_CANDIDATE_COMPARISON}}")
    print(f"Selected candidate blocks={{CANDIDATE_BLOCK_SELECTION}}")
    print(f"Layer 2 targets={{selected_layer2_targets or 'none'}}")
""".strip()


def pruning_action_table_cell(summary_var_name: str) -> str:
    return f"""
def _action_from_buckets(d_bucket: str, stitched_bucket: str) -> str:
    harmful = {{"strong_harmful", "mild_harmful"}}
    helpful = {{"strong_helpful", "mild_helpful"}}
    neutral = {{"near_zero_uncertain", "insufficient_data"}}
    if d_bucket in harmful and stitched_bucket in harmful:
        return "prune_candidate"
    if (d_bucket in harmful and stitched_bucket in neutral) or (stitched_bucket in harmful and d_bucket in neutral):
        return "prune_candidate"
    if (d_bucket in harmful and stitched_bucket in helpful) or (d_bucket in helpful and stitched_bucket in harmful):
        return "redesign_candidate"
    if d_bucket in neutral and stitched_bucket in neutral:
        return "ambiguous"
    return "keep_or_monitor"


summary_scope = {summary_var_name}.copy()
layer1_scope = summary_scope[summary_scope["scheme_name"].astype(str) == "layer1_mutually_exclusive"].copy()

if layer1_scope.empty:
    print("No compatible Layer 1 summary exists yet for the baseline lineage.")
else:
    action_rows = []
    for model_family in sorted(layer1_scope["model_family"].astype(str).unique()):
        d_only = annotate_ablation_metric_slice(
            select_feature_family_metric_slice(
                layer1_scope[layer1_scope["model_family"].astype(str) == model_family],
                split="validation",
                reporting_level="d_only",
                metric="mae",
            )
        )[["feature_family", "effect_bucket", "relative_delta"]].rename(
            columns={{
                "effect_bucket": "d_only_bucket",
                "relative_delta": "d_only_relative_delta",
            }}
        )
        stitched = annotate_ablation_metric_slice(
            select_feature_family_metric_slice(
                layer1_scope[layer1_scope["model_family"].astype(str) == model_family],
                split="validation",
                reporting_level="stitched_all_horizon",
                metric="mae",
            )
        )[["feature_family", "effect_bucket", "relative_delta"]].rename(
            columns={{
                "effect_bucket": "stitched_bucket",
                "relative_delta": "stitched_relative_delta",
            }}
        )
        merged = d_only.merge(stitched, on="feature_family", how="outer")
        if merged.empty:
            continue
        merged["model_family"] = model_family
        merged["suggested_action"] = merged.apply(
            lambda row: _action_from_buckets(
                str(row.get("d_only_bucket", "insufficient_data")),
                str(row.get("stitched_bucket", "insufficient_data")),
            ),
            axis=1,
        )
        action_rows.append(merged)

    if not action_rows:
        print("No candidate action rows could be derived from the baseline summary.")
    else:
        action_table = pd.concat(action_rows, ignore_index=True)
        display(
            action_table[
                [
                    "model_family",
                    "feature_family",
                    "d_only_bucket",
                    "d_only_relative_delta",
                    "stitched_bucket",
                    "stitched_relative_delta",
                    "suggested_action",
                ]
            ]
            .rename(
                columns={{
                    "model_family": "Model family",
                    "feature_family": "Block",
                    "d_only_bucket": "D-only effect",
                    "d_only_relative_delta": "D-only relative delta",
                    "stitched_bucket": "Stitched effect",
                    "stitched_relative_delta": "Stitched relative delta",
                    "suggested_action": "Suggested action",
                }}
            )
            .style
            .format(
                {{
                    "D-only relative delta": "{{:+.3%}}",
                    "Stitched relative delta": "{{:+.3%}}",
                }}
            )
            .hide(axis="index")
        )
""".strip()


def pruning_benchmark_delta_cell(baseline_specs: list[dict[str, str]], candidate_specs: list[dict[str, str]]) -> str:
    return f"""
baseline_specs = {repr(baseline_specs)}
candidate_specs = {repr(candidate_specs)}
comparison_rows = []

for baseline_spec, candidate_spec in zip(baseline_specs, candidate_specs):
    baseline_run_dir = latest_run_or_none(str(baseline_spec["parent_run_label"]))
    candidate_run_dir = latest_run_or_none(str(candidate_spec["parent_run_label"]))
    if baseline_run_dir is None:
        continue
    baseline_metrics = load_csv(baseline_run_dir, "metrics_by_reporting_level.csv")
    baseline_metrics = baseline_metrics[baseline_metrics["model"].astype(str) == str(baseline_spec["model_name"])].copy()
    if baseline_metrics.empty:
        continue
    candidate_metrics = baseline_metrics.iloc[0:0].copy()
    if candidate_run_dir is not None:
        candidate_metrics = load_csv(candidate_run_dir, "metrics_by_reporting_level.csv")
        candidate_metrics = candidate_metrics[candidate_metrics["model"].astype(str) == str(candidate_spec["model_name"])].copy()

    for split_name in ("validation", "test"):
        for reporting_level in ("d_only", "stitched_all_horizon"):
            base_row = baseline_metrics[
                (baseline_metrics["dataset_split"].astype(str) == split_name)
                & (baseline_metrics["reporting_level"].astype(str) == reporting_level)
            ].head(1)
            candidate_row = candidate_metrics[
                (candidate_metrics["dataset_split"].astype(str) == split_name)
                & (candidate_metrics["reporting_level"].astype(str) == reporting_level)
            ].head(1)
            comparison_rows.append(
                {{
                    "Model family": baseline_spec["model_family"],
                    "Model label": baseline_spec["model_label"],
                    "Dataset split": split_name,
                    "Reporting level": reporting_level,
                    "Baseline run": baseline_spec["parent_run_label"],
                    "Candidate run": candidate_spec["parent_run_label"] if candidate_run_dir is not None else "",
                    "Baseline MAE": float(base_row["mae"].iloc[0]) if not base_row.empty else float("nan"),
                    "Candidate MAE": float(candidate_row["mae"].iloc[0]) if not candidate_row.empty else float("nan"),
                    "MAE delta (candidate - baseline)": (
                        float(candidate_row["mae"].iloc[0]) - float(base_row["mae"].iloc[0])
                        if (not base_row.empty and not candidate_row.empty)
                        else float("nan")
                    ),
                    "Baseline rMAE": float(base_row["rmae_vs_official_naive"].iloc[0]) if not base_row.empty else float("nan"),
                    "Candidate rMAE": float(candidate_row["rmae_vs_official_naive"].iloc[0]) if not candidate_row.empty else float("nan"),
                }}
            )

comparison_frame = pd.DataFrame(comparison_rows)
if comparison_frame.empty:
    print("No baseline benchmark rows were available for the candidate comparison.")
else:
    display(
        comparison_frame.style
        .format(
            {{
                "Baseline MAE": "{{:.4f}}",
                "Candidate MAE": "{{:.4f}}",
                "MAE delta (candidate - baseline)": "{{:+.4f}}",
                "Baseline rMAE": "{{:.4f}}",
                "Candidate rMAE": "{{:.4f}}",
            }}
        )
        .hide(axis="index")
    )
""".strip()


def fs3_ablation_report_cell(
    parent_run_label: str,
    primary_reporting_levels: tuple[str, ...] = ("d_only", "stitched_all_horizon"),
    visible_reporting_levels: tuple[str, ...] = ("d_only", "stitched_all_horizon"),
) -> str:
    return f"""
from matplotlib import pyplot as plt
from IPython.display import Markdown

from hourly_da.notebook_support import (
    apply_notebook_display_defaults,
    apply_standard_matplotlib_style,
    load_feature_family_ablation_bundle,
    plot_feature_family_delta_bars,
    plot_feature_family_heatmap,
    plot_feature_family_origin_stability,
    select_feature_family_metric_slice,
)

apply_notebook_display_defaults()
apply_standard_matplotlib_style()

bundle = load_feature_family_ablation_bundle(output_root, "{parent_run_label}")
PRIMARY_SPLIT = "validation"
PRIMARY_REPORTING_LEVELS = {repr(primary_reporting_levels)}
VISIBLE_REPORTING_LEVELS = {repr(visible_reporting_levels)}
PRIMARY_METRIC = "mae"
REPORTING_LEVEL_LABELS = {{
    "d_only": "D-only",
    "stitched_all_horizon": "Full horizon",
}}

if bundle is None:
    print("No complete aggregate ablation bundle was found yet for this FS3 parent context.")
else:
    metadata = bundle["metadata"]
    summary = bundle["summary"]
    by_origin = bundle["by_origin"]
    by_reporting_level = bundle["by_reporting_level"]
    parent_child_map = bundle["parent_child_map"]

    display(pd.DataFrame([{{
        "Parent context": bundle["context_label"],
        "Parent model": metadata.get("model", ""),
        "Parent run": metadata.get("parent_run_id", ""),
        "Aggregate run": metadata.get("run_id", ""),
        "Aggregate status": metadata.get("aggregate_status", ""),
        "Smoke test": bool(metadata.get("smoke_test", False)),
        "Selected exogenous families": ", ".join(metadata.get("selected_feature_families", [])),
        "Support note": metadata.get("support_note", ""),
    }}]))

    if not parent_child_map.empty:
        display(parent_child_map.reset_index(drop=True))

    for reporting_level in PRIMARY_REPORTING_LEVELS:
        primary_summary = select_feature_family_metric_slice(
            summary,
            split=PRIMARY_SPLIT,
            reporting_level=reporting_level,
            metric=PRIMARY_METRIC,
        )
        display(Markdown(f"### Validation / {{REPORTING_LEVEL_LABELS.get(reporting_level, reporting_level)}}"))
        if primary_summary.empty:
            print(f"No rows are available for the {{reporting_level}} ablation lens yet.")
            continue

        display(
            primary_summary[
                [
                    "feature_family",
                    "parent_value",
                    "child_value",
                    "delta",
                    "relative_delta",
                    "interpretation_flag",
                    "smoke_test",
                ]
            ]
            .rename(
                columns={{
                    "feature_family": "Feature family",
                    "parent_value": "Parent value",
                    "child_value": "Child value",
                    "delta": "Delta",
                    "relative_delta": "Relative delta",
                    "interpretation_flag": "Interpretation",
                    "smoke_test": "Smoke test",
                }}
            )
            .style
            .format(
                {{
                    "Parent value": "{{:.2f}}",
                    "Child value": "{{:.2f}}",
                    "Delta": "{{:+.2f}}",
                    "Relative delta": "{{:+.2%}}",
                    "Smoke test": lambda value: "Yes" if bool(value) else "",
                }}
            )
            .hide(axis="index")
        )

        top_row = primary_summary.iloc[0]
        bottom_row = primary_summary.iloc[-1]
        display(
            Markdown(
                f"Primary read: the most harmful removal on {{PRIMARY_SPLIT}} / "
                f"{{REPORTING_LEVEL_LABELS.get(reporting_level, reporting_level)}} is "
                f"`{{top_row['feature_family']}}` (`delta = {{float(top_row['delta']):+.2f}}`). "
                f"The weakest exogenous family under the same lens is "
                f"`{{bottom_row['feature_family']}}` (`delta = {{float(bottom_row['delta']):+.2f}}`)."
            )
        )

        fig = plot_feature_family_delta_bars(primary_summary)
        if fig is not None:
            display(fig)
            plt.close(fig)

        heatmap_fig = plot_feature_family_heatmap(primary_summary)
        if heatmap_fig is not None:
            display(heatmap_fig)
            plt.close(heatmap_fig)

        stability_fig = plot_feature_family_origin_stability(
            by_origin,
            split=PRIMARY_SPLIT,
            reporting_level=reporting_level,
            metric=PRIMARY_METRIC,
        )
        if stability_fig is None:
            print("No readable origin-stability plot is available yet for this FS3 parent context.")
        else:
            display(stability_fig)
            plt.close(stability_fig)

    reporting_view = by_reporting_level[
        by_reporting_level["metric"].isin(["mae", "rmae_vs_official_naive"])
        & by_reporting_level["reporting_level"].astype(str).isin(VISIBLE_REPORTING_LEVELS)
    ].copy()
    if not reporting_view.empty:
        display(
            reporting_view[
                [
                    "dataset_split",
                    "reporting_level_label",
                    "feature_family",
                    "metric",
                    "parent_value",
                    "child_value",
                    "delta",
                    "relative_delta",
                ]
            ]
            .rename(
                columns={{
                    "dataset_split": "Split",
                    "reporting_level_label": "Reporting level",
                    "feature_family": "Feature family",
                    "metric": "Metric",
                    "parent_value": "Parent value",
                    "child_value": "Child value",
                    "delta": "Delta",
                    "relative_delta": "Relative delta",
                }}
            )
            .style
            .format(
                {{
                    "Parent value": "{{:.2f}}",
                    "Child value": "{{:.2f}}",
                    "Delta": "{{:+.2f}}",
                    "Relative delta": "{{:+.2%}}",
                }}
            )
            .hide(axis="index")
        )
""".strip()


def fs3_execution_toggle_cell(model_family: str, default_step: str, run_label: str, stage: str = FS3_STAGE) -> str:
    return f"""
ALLOW_HEAVY_RERUN = False
FEATURE_VALUE_STEP = "{default_step}"

if ALLOW_HEAVY_RERUN:
    estimate = estimate_run_duration_seconds(output_root, "{run_label}")
    if estimate is not None:
        print(
            "Heavy rerun warning: latest comparable run "
            f"{{estimate['run_id']}} suggests about {{format_duration(float(estimate['estimate_seconds']))}}."
        )
    else:
        print("Heavy rerun warning: no comparable runtime estimate was found for this stage.")

    command = [
        sys.executable,
        str(PACKAGE_ROOT / "run_fs3_ordered_benchmarks.py"),
        "--execution-mode",
        "feature_value",
        "--feature-value-step",
        FEATURE_VALUE_STEP,
        "--stage",
        "{stage}",
        "--feature-value-model-family",
        "{model_family}",
    ]
    started = time.perf_counter()
    run_command_with_live_output(command)
    elapsed_seconds = time.perf_counter() - started
    print(f"Actual wall-clock time: {{format_duration(elapsed_seconds)}}")
else:
    print("Rerun skipped. Set ALLOW_HEAVY_RERUN = True only when you are ready to execute the finalized pipeline.")
    print(f"Current FEATURE_VALUE_STEP setting: {{FEATURE_VALUE_STEP}}")
    print("Use 'parent' to refresh only the FS3 parent benchmark, 'ablation' to reuse the latest compatible parent, or 'all' to rerun both.")
""".strip()


def build_notebooks() -> dict[str, list[dict[str, object]]]:
    notebooks: dict[str, list[dict[str, object]]] = {}

    notebooks["00_pipeline_overview.ipynb"] = [
        markdown_cell(
            """
# 00 Pipeline Overview

This notebook is the run map for the active hourly DA notebook pipeline.

How to use this folder:
- run notebooks `00` through `24` in order for the main pipeline
- notebooks `90+` are reference-only and sit outside the consecutive run order
- only `01_da_prices_cleaning_walkthrough.ipynb` and `03_endogenous_explicit_features.ipynb` are protected non-generator notebooks
- all other top-level notebooks in this folder are generator-managed and any ad hoc top-level `.ipynb` file can be archived on regeneration
- benchmark notebooks default to **reading the latest saved artifacts**
- the shared `find_latest_run(...)` helper prefers the latest complete run folder with `run_summary.json`
- use the execution hook at the end of an execution notebook only when you want to refresh that stage

Critical distinction:
- `01_da_prices_cleaning_walkthrough.ipynb` is where upstream raw missing-datapoint handling is explained
- `03_endogenous_explicit_features.ipynb` does **not** redo that cleaning step; it only creates a causal helper series on top of the cleaned target for leakage-safe feature engineering
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(
            """
pipeline_rows = [
    {"step": "00", "notebook": "00_pipeline_overview.ipynb", "mode": "Guide", "ownership": "Generator-managed", "main_output": "Run order, dependencies, and latest artifact status"},
    {"step": "01", "notebook": "01_da_prices_cleaning_walkthrough.ipynb", "mode": "Preparation", "ownership": "Protected", "main_output": "Upstream DA cleaning walkthrough and missing-datapoint handling"},
    {"step": "02", "notebook": "02_methodology_and_objective_weeks.ipynb", "mode": "Preparation", "ownership": "Generator-managed", "main_output": "Frozen methodology snapshot and objective week selection"},
    {"step": "03", "notebook": "03_endogenous_explicit_features.ipynb", "mode": "Preparation", "ownership": "Protected", "main_output": "FS1 endogenous feature diagnostics and saved feature artifacts"},
    {"step": "04", "notebook": "04_fs0_naive_models.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "naive_benchmark"},
    {"step": "05", "notebook": "05_fs1_lear.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "lear_fs1_benchmark"},
    {"step": "06", "notebook": "06_fs1_xgboost.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "xgboost_fs1_benchmark"},
    {"step": "07", "notebook": "07_fs1_benchmark_and_comparison.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "fs1_model_comparison"},
    {"step": "08", "notebook": "08_fs2_lear.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "lear_fs2_benchmark"},
    {"step": "09", "notebook": "09_fs2_xgboost.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "xgboost_fs2_benchmark"},
    {"step": "10", "notebook": "10_fs2_prophet.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "prophet_benchmark"},
    {"step": "11", "notebook": "11_fs2_benchmark_and_shortlisting.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "model_comparison"},
    {"step": "12", "notebook": "12_fs2_lear_ablation.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "Model-specific FS2 staged block ablation for LEAR"},
    {"step": "13", "notebook": "13_fs2_xgboost_ablation.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "Model-specific FS2 staged block ablation for XGBoost"},
    {"step": "14", "notebook": "14_fs2_feature_value_results.ipynb", "mode": "Reporting", "ownership": "Generator-managed", "main_output": "FS2 staged ablation synthesis across LEAR and XGBoost"},
    {"step": "15", "notebook": "15_fs2_pruning_and_redesign_validation.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "Selective FS2 pruning and redesign validation against revised candidate parents"},
    {"step": "16", "notebook": "16_fs3_lear.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "FS3 LEAR parent benchmark on the combined all-exogenous family stack"},
    {"step": "17", "notebook": "17_fs3_xgboost.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "FS3 XGBoost parent benchmark on the combined all-exogenous family stack"},
    {"step": "18", "notebook": "18_fs3_benchmark_and_comparison.ipynb", "mode": "Reporting", "ownership": "Generator-managed", "main_output": "Cross-model comparison of the all-exogenous FS3 parent benchmarks against FS2"},
    {"step": "19", "notebook": "19_fs3_lear_ablation.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "Model-specific FS3 staged block ablation for LEAR"},
    {"step": "20", "notebook": "20_fs3_xgboost_ablation.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "Model-specific FS3 staged block ablation for XGBoost"},
    {"step": "21", "notebook": "21_fs3_feature_value_results.ipynb", "mode": "Reporting", "ownership": "Generator-managed", "main_output": "FS3 staged ablation synthesis across LEAR and XGBoost"},
    {"step": "22", "notebook": "22_fs3_pruning_and_redesign_validation.ipynb", "mode": "Execution", "ownership": "Generator-managed", "main_output": "Selective FS3 pruning and redesign validation against revised candidate parents"},
    {"step": "23", "notebook": "23_fs3_decision_relevant_forecast_evaluation.ipynb", "mode": "Reporting", "ownership": "Generator-managed", "main_output": "Decision-relevant DA candidate evaluation across FS2, promoted FS3, and pruned FS3 finalists"},
    {"step": "24", "notebook": "24_final_conclusion_and_best_model.ipynb", "mode": "Reporting", "ownership": "Generator-managed", "main_output": "Final thesis recommendation after the decision-relevant DA evaluation layer"},
]

reference_rows = [
    {"notebook": "90_active_stack_and_tuning_policy_reference.ipynb", "ownership": "Generator-managed reference", "purpose": "Background on active model-entry rules and tuning cadence"},
    {"notebook": "91_fs3_feature_family_plan_reference.ipynb", "ownership": "Generator-managed reference", "purpose": "Planned FS3 exogenous-family roadmap; not part of the active run order"},
    {"notebook": "92_fs4_huang_style_plan_reference.ipynb", "ownership": "Generator-managed reference", "purpose": "Planned FS4 advanced-feature roadmap; not part of the active run order"},
    {"notebook": "93_execution_readiness_checklist_reference.ipynb", "ownership": "Generator-managed reference", "purpose": "Optional structural repo check; not part of the main pipeline"},
    {"notebook": "94_methodology_update_summary_reference.ipynb", "ownership": "Generator-managed reference", "purpose": "Historical summary of the repo-standardization update"},
]

display(pd.DataFrame(pipeline_rows))
display(pd.DataFrame(reference_rows))
""".strip()
        ),
        markdown_cell("## Current artifact status"),
        code_cell(
            run_availability_cell(
                [
                    "case_week_selection",
                    "endogenous_explicit_features",
                    "naive_benchmark",
                    "lear_fs1_benchmark",
                    "xgboost_fs1_benchmark",
                    "fs1_model_comparison",
                    "lear_fs2_benchmark",
                    "xgboost_fs2_benchmark",
                    "prophet_benchmark",
                    "model_comparison",
                    "feature_family_ablation__lear_fs2_benchmark__stage_a_top_level__v1",
                    "feature_family_ablation__xgboost_fs2_benchmark__stage_a_top_level__v1",
                    "feature_family_ablation__lear_fs2_benchmark__layer1_mutually_exclusive__v1",
                    "feature_family_ablation__xgboost_fs2_benchmark__layer1_mutually_exclusive__v1",
                    FS2_LEAR_CANDIDATE_RUN_LABEL,
                    FS2_XGBOOST_CANDIDATE_RUN_LABEL,
                    FS2_CANDIDATE_COMPARISON_RUN_LABEL,
                    FS3_COMBO_RUN_LABEL,
                    FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL,
                    FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL,
                    FS3_LEAR_CANDIDATE_RUN_LABEL,
                    FS3_XGBOOST_CANDIDATE_RUN_LABEL,
                    "feature_family_ablation__lear_fs1_benchmark",
                    "feature_family_ablation__xgboost_fs1_benchmark",
                    "feature_family_ablation__prophet_benchmark",
                    "visual_case_weeks",
                ]
            )
        ),
    ]

    notebooks["02_methodology_and_objective_weeks.ipynb"] = [
        markdown_cell(
            """
# 02 Methodology And Objective Weeks

This is the light setup checkpoint directly before the benchmark notebooks.

What is frozen here:
- daily rolling-origin evaluation with origin at `08:00` on `D-1`
- forecast horizon `D` through `D+4`
- UTC as the internal storage timezone
- the active feature-stage ladder from `FS0` through `FS4`
- the rule that thesis case weeks must come from **test actual prices only**

This notebook stays lightweight. It does not launch model benchmarks, but it can refresh the objective case-week selection artifact used later in the final reporting notebook.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        *optional_execution_hook_cells(
            "run_case_week_selection.py",
            "case_week_selection",
            heading="## Optional refresh hook",
        ),
        markdown_cell(
            """
## Active methodology snapshot

The tables below are the single source of truth for the current DAM ladder, model status, shortlisting policy, and tuning cadence.
""".strip()
        ),
        code_cell(
            """
display(Markdown(f"**FS1 foundation note.** {STARTER_ENDOGENOUS_FEATURE_NOTE}"))
display(feature_stage_policy_frame())
display(model_status_frame())
display(shortlisting_policy_frame())
display(tuning_cadence_frame())
""".strip()
        ),
        markdown_cell(
            """
## Objective test-week selection

The required thesis cases are:
- one typical winter week
- one typical summer week
- one high-volatility week

The selection remains objective and is never hand-picked from model outputs.
""".strip()
        ),
        code_cell(
            """
try:
    selected_weeks_run, selected_weeks = load_selected_case_weeks(output_root)
    print(selected_weeks_run)
    required_categories = ["typical_winter", "typical_summer", "high_volatility"]
    if "category" in selected_weeks.columns:
        selected_weeks_view = selected_weeks[selected_weeks["category"].isin(required_categories)].copy()
        if selected_weeks_view.empty:
            selected_weeks_view = selected_weeks.copy()
    else:
        selected_weeks_view = selected_weeks.copy()
    display(selected_weeks_view)
except FileNotFoundError:
    print("No saved objective week selection artifact exists yet.")
""".strip()
        ),
    ]

    notebooks["04_fs0_naive_models.ipynb"] = [
        markdown_cell(
            """
# 04 FS0 Naive Models

`FS0` is the first execution stage in the benchmark ladder. The active seasonal naive candidates are:
- previous-week
- previous-year

Both are kept in scope so the **selected naive benchmark** can be chosen on validation rather than assumed in advance.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        *optional_execution_hook_cells("run_naive_benchmark.py", "naive_benchmark"),
        markdown_cell(
            """
This stage has no structural tuning. It exists to establish the benchmark floor and to populate relative metrics such as `rMAE`.
""".strip()
        ),
        code_cell(stage_policy_cell("FS0")),
        code_cell(model_status_cell(["naive"])),
        code_cell(optional_run_summary_cell("naive_benchmark", ["naive_previous_week", "naive_previous_year"])),
        *expanded_report_cells(
            run_label="naive_benchmark",
            notebook_slug="04_fs0_naive_models",
            comparison_logic=fs0_naive_comparison_logic(),
            week_title_prefix="FS0 naive benchmark comparison",
        ),
    ]

    notebooks["90_active_stack_and_tuning_policy_reference.ipynb"] = [
        markdown_cell(
            """
# 90 Active Stack And Tuning Policy Reference

Reference-only notebook. It is **not** part of the consecutive execution pipeline.

Use it when you want background on:
- why models do not all enter at the same feature stage
- why `Prophet` starts at `FS2`
- how the stage-by-stage tuning cadence is intended to work
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(
            """
display(feature_stage_policy_frame())
display(shortlisting_policy_frame())
display(model_status_frame())
display(tuning_cadence_frame())
""".strip()
        ),
        markdown_cell(
            """
## Tuning snippets

The code below shows the stored tuning placeholders and starter search regions. These are planning aids only; the actual searches stay disabled until the feature stages are executed later.
""".strip()
        ),
        code_cell("display(tuning_snippet_frame())"),
    ]

    notebooks["05_fs1_lear.ipynb"] = [
        markdown_cell(
            """
# 05 FS1 LEAR

This notebook runs the dedicated `LEAR FS1` benchmark.

Execution boundary:
- one notebook run produces one model at one feature-set layer
- this notebook refreshes only `lear_fs1_benchmark`
- the later FS1 and FS2 comparison notebooks aggregate results across runs instead of reusing a hidden shared family run
""".strip()
        ),
        code_cell(COMMON_SETUP),
        *optional_execution_hook_cells(
            "run_lear_benchmark.py",
            "lear_fs1_benchmark",
            extra_args=["--fs-level", "FS1"],
        ),
        code_cell('display(Markdown(f"**Foundation note.** {STARTER_ENDOGENOUS_FEATURE_NOTE}"))'),
        code_cell(stage_policy_cell("FS1")),
        code_cell(model_status_cell(["lear"])),
        code_cell(tuning_placeholder_cell("lear", "FS1")),
        code_cell(optional_run_summary_cell("lear_fs1_benchmark", ["naive_previous_week", "naive_previous_year", "lear_fs1"])),
        markdown_cell(
            """
Execution note:
- keep `FS1` tuning fast and coarse
- tune on validation only
- freeze the chosen `FS1` setting for the dedicated LEAR FS1 run
""".strip()
        ),
        *expanded_report_cells(
            run_label="lear_fs1_benchmark",
            notebook_slug="05_fs1_lear",
            comparison_logic=fs1_lear_comparison_logic(),
            week_title_prefix="FS1 LEAR benchmark comparison",
        ),
    ]

    notebooks["06_fs1_xgboost.ipynb"] = [
        markdown_cell(
            """
# 06 FS1 XGBoost

This notebook runs the dedicated `XGBoost FS1` benchmark.

Execution boundary:
- one notebook run produces one model at one feature-set layer
- this notebook refreshes only `xgboost_fs1_benchmark`
- the later FS1 and FS2 comparison notebooks aggregate results across runs instead of reusing a hidden shared family run
""".strip()
        ),
        code_cell(COMMON_SETUP),
        *optional_execution_hook_cells(
            "run_xgboost_benchmark.py",
            "xgboost_fs1_benchmark",
            extra_args=["--fs-level", "FS1"],
        ),
        code_cell('display(Markdown(f"**Foundation note.** {STARTER_ENDOGENOUS_FEATURE_NOTE}"))'),
        code_cell(stage_policy_cell("FS1")),
        code_cell(model_status_cell(["xgboost"])),
        code_cell(tuning_placeholder_cell("xgboost", "FS1")),
        code_cell(optional_run_summary_cell("xgboost_fs1_benchmark", ["naive_previous_week", "naive_previous_year", "xgboost_fs1"])),
        markdown_cell(
            """
Execution note:
- keep the `FS1` search compact
- focus on a small validation-only grid
- freeze the chosen `FS1` setting for the dedicated XGBoost FS1 run
""".strip()
        ),
        *expanded_report_cells(
            run_label="xgboost_fs1_benchmark",
            notebook_slug="06_fs1_xgboost",
            comparison_logic=fs1_xgboost_comparison_logic(),
            week_title_prefix="FS1 XGBoost benchmark comparison",
        ),
    ]

    notebooks["07_fs1_benchmark_and_comparison.ipynb"] = [
        markdown_cell(
            """
# 07 FS1 Benchmark And Comparison

This is the combined `FS1` comparison stage.

Run this notebook after `05` and `06` have produced fresh dedicated FS1 benchmark artifacts. It builds the shared `fs1_model_comparison` run for the whole `FS1` layer.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        *optional_execution_hook_cells(
            "run_model_comparison.py",
            "fs1_model_comparison",
            extra_args=["--fs-level", "FS1"],
        ),
        code_cell(run_availability_cell(["naive_benchmark", "lear_fs1_benchmark", "xgboost_fs1_benchmark", "fs1_model_comparison"])),
        code_cell("display(shortlisting_policy_frame())"),
        code_cell(
            """
run_dir = latest_run_or_none("fs1_model_comparison")

if run_dir is None:
    print("No combined FS1 comparison run exists yet under the finalized methodology.")
else:
    print(run_dir)
    metrics_by_reporting_level = load_csv(run_dir, "metrics_by_reporting_level.csv")
    official_naive = load_json(run_dir, "official_naive_reference.json")
    focus_models = [
        "naive_previous_week",
        "naive_previous_year",
        "lear_fs1",
        "xgboost_fs1",
    ]
    model_order = {model_name: position for position, model_name in enumerate(focus_models)}
    display(pd.DataFrame([official_naive]))
    display(
        metrics_by_reporting_level[metrics_by_reporting_level["model"].isin(focus_models)]
        .assign(_model_order=lambda frame: frame["model"].map(model_order).fillna(len(model_order)))
        .sort_values(["dataset_split", "reporting_level_sort_order", "_model_order", "model"])
        .drop(columns=["_model_order"])
        .reset_index(drop=True)
    )
""".strip()
        ),
        *expanded_report_cells(
            run_label="fs1_model_comparison",
            notebook_slug="07_fs1_benchmark_and_comparison",
            comparison_logic=fs1_combined_comparison_logic(),
            week_title_prefix="FS1 benchmark comparison",
        ),
    ]

    notebooks["08_fs2_lear.ipynb"] = [
        markdown_cell(
            """
# 08 FS2 LEAR

This notebook runs the dedicated `LEAR FS2` benchmark.

`LEAR FS2` reuses the explicit endogenous FS1 foundation and adds the frozen calendar and holiday structure of `FS2`.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        *optional_execution_hook_cells(
            "run_lear_benchmark.py",
            "lear_fs2_benchmark",
            extra_args=["--fs-level", "FS2"],
        ),
        code_cell(stage_policy_cell("FS2")),
        code_cell(model_status_cell(["lear"])),
        code_cell(tuning_placeholder_cell("lear", "FS2")),
        code_cell(optional_run_summary_cell("lear_fs2_benchmark", ["naive_previous_week", "naive_previous_year", "lear_fs2"])),
        markdown_cell(
            """
Execution note:
- `LEAR FS2` is tuned and run separately from `LEAR FS1`
- `LEAR FS1` remains a developmental baseline, not a shortlisting point
- the combined FS2 shortlist still waits until the full FS2 stack has been aggregated
""".strip()
        ),
        *expanded_report_cells(
            run_label="lear_fs2_benchmark",
            notebook_slug="08_fs2_lear",
            comparison_logic=fs2_lear_comparison_logic(),
            week_title_prefix="FS2 LEAR benchmark comparison",
        ),
    ]

    notebooks["09_fs2_xgboost.ipynb"] = [
        markdown_cell(
            """
# 09 FS2 XGBoost

This notebook runs the dedicated `XGBoost FS2` benchmark.

`XGBoost FS2` reuses the explicit endogenous FS1 foundation and adds the frozen calendar and holiday structure of `FS2`.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        *optional_execution_hook_cells(
            "run_xgboost_benchmark.py",
            "xgboost_fs2_benchmark",
            extra_args=["--fs-level", "FS2"],
        ),
        code_cell(stage_policy_cell("FS2")),
        code_cell(model_status_cell(["xgboost"])),
        code_cell(tuning_placeholder_cell("xgboost", "FS2")),
        code_cell(optional_run_summary_cell("xgboost_fs2_benchmark", ["naive_previous_week", "naive_previous_year", "xgboost_fs2"])),
        markdown_cell(
            """
Execution note:
- `XGBoost FS2` is tuned and run separately from `XGBoost FS1`
- the shortlist still waits until the full `FS2` stack has been aggregated
""".strip()
        ),
        *expanded_report_cells(
            run_label="xgboost_fs2_benchmark",
            notebook_slug="09_fs2_xgboost",
            comparison_logic=fs2_xgboost_comparison_logic(),
            week_title_prefix="FS2 XGBoost benchmark comparison",
        ),
    ]

    notebooks["10_fs2_prophet.ipynb"] = [
        markdown_cell(
            """
# 10 FS2 Prophet

`Prophet` joins only from `FS2` onward, so this notebook runs the dedicated Prophet FS2 benchmark.

Why the delay is deliberate:
- `Prophet` is more meaningful once calendar and holiday structure is part of the design
- treating `Prophet` as an `FS1` lag-only model would not be methodologically fair
- `FS2` is therefore the first valid entry point for `Prophet` in this DAM stack
""".strip()
        ),
        code_cell(COMMON_SETUP),
        *optional_execution_hook_cells(
            "run_prophet_benchmark.py",
            "prophet_benchmark",
            required_modules=["prophet"],
        ),
        code_cell(stage_policy_cell("FS2")),
        code_cell(model_status_cell(["prophet"])),
        code_cell(tuning_placeholder_cell("prophet", "FS2")),
        code_cell(optional_run_summary_cell("prophet_benchmark", ["naive_previous_week", "naive_previous_year", "prophet_fs2"])),
        markdown_cell(
            """
Later execution note:
- keep the `FS2` Prophet regressor set compact and causal
- use validation-only structural tuning
- do not backfill Prophet into `FS1`
""".strip()
        ),
        *expanded_report_cells(
            run_label="prophet_benchmark",
            notebook_slug="10_fs2_prophet",
            comparison_logic=fs2_prophet_comparison_logic(),
            week_title_prefix="FS2 Prophet benchmark comparison",
        ),
    ]

    notebooks["11_fs2_benchmark_and_shortlisting.ipynb"] = [
        markdown_cell(
            """
# 11 FS2 Benchmark And Shortlisting

This is the combined `FS2` comparison stage.

Run this notebook after `08`, `09`, and `10` have produced fresh dedicated FS2 benchmark artifacts. It builds the shared `model_comparison` run used by the final conclusion notebook.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        *optional_execution_hook_cells(
            "run_model_comparison.py",
            "model_comparison",
            extra_args=["--fs-level", "FS2"],
        ),
        code_cell(run_availability_cell(["naive_benchmark", "lear_fs2_benchmark", "xgboost_fs2_benchmark", "prophet_benchmark", "model_comparison"])),
        code_cell("display(shortlisting_policy_frame())"),
        code_cell(
            """
run_dir = latest_run_or_none("model_comparison")

if run_dir is None:
    print("No combined FS2 comparison run exists yet under the finalized methodology.")
else:
    print(run_dir)
    metrics_by_reporting_level = load_csv(run_dir, "metrics_by_reporting_level.csv")
    official_naive = load_json(run_dir, "official_naive_reference.json")
    focus_models = [
        "naive_previous_week",
        "naive_previous_year",
        "lear_fs2",
        "xgboost_fs2",
        "prophet_fs2",
    ]
    model_order = {model_name: position for position, model_name in enumerate(focus_models)}
    display(pd.DataFrame([official_naive]))
    display(
        metrics_by_reporting_level[metrics_by_reporting_level["model"].isin(focus_models)]
        .assign(_model_order=lambda frame: frame["model"].map(model_order).fillna(len(model_order)))
        .sort_values(["dataset_split", "reporting_level_sort_order", "_model_order", "model"])
        .drop(columns=["_model_order"])
        .reset_index(drop=True)
    )
""".strip()
        ),
        *expanded_report_cells(
            run_label="model_comparison",
            notebook_slug="11_fs2_benchmark_and_shortlisting",
            comparison_logic=fs2_combined_comparison_logic(),
            week_title_prefix="FS2 benchmark and shortlisting comparison",
        ),
    ]


    notebooks["12_fs2_lear_ablation.ipynb"] = [
        markdown_cell(
            """
# 12 FS2 LEAR Ablation

This notebook is the generator-owned `FS2 LEAR` staged ablation workflow.

Purpose of this layer:
- inspect the endogenous-plus-calendar `FS2` foundation before `FS3` starts
- keep the analysis model-specific
- separate broad orientation from block-level attribution

Interpretation rule:
- ablation shows marginal contribution conditional on the rest of the parent bundle staying present
- it does **not** show standalone independent value, and it does **not** prove causal truth
""".strip()
        ),
        code_cell(COMMON_SETUP),
        markdown_cell(
            """
## Optional execution hook

This snippet reruns the staged `FS2 LEAR` ablation against the saved `lear_fs2_benchmark` parent.

Use it when:
- notebook `08` already produced the parent benchmark you want to analyze
- you want to refresh `Stage A`, `Layer 1`, or a selective `Layer 2` follow-up
""".strip()
        ),
        code_cell(staged_execution_toggle_cell("FS2", "lear_fs2_benchmark", "lear")),
        code_cell(stage_policy_cell("FS2")),
        code_cell(model_status_cell(["lear"])),
        code_cell(tuning_placeholder_cell("lear", "FS2")),
        code_cell(run_availability_cell(["lear_fs2_benchmark"])),
        code_cell(optional_run_summary_cell("lear_fs2_benchmark", ["naive_previous_week", "naive_previous_year", "lear_fs2"])),
        markdown_cell(
            """
## Parent reminder and stale-result rule

Read notebooks `08` and `11` first when you want the benchmark context for this parent.

This notebook answers the follow-up question:
- once the `FS2 LEAR` parent exists, which broad pieces of the endogenous and calendar foundation still matter when removed one at a time?

Compatibility rule:
- only staged-ablation bundles with matching scheme hash, feature taxonomy hash, and valid stored preflight are treated as active evidence
""".strip()
        ),
        code_cell(staged_ablation_setup_cell("STAGED", "FS2", "lear_fs2_benchmark", "lear")),
        markdown_cell("## Scheme availability and compatibility"),
        code_cell(staged_ablation_availability_cell("STAGED")),
        markdown_cell(
            """
## Stage A: Top-Level Orientation

What this section does:
- removes one of the broad `FS2` blocks from the full `LEAR FS2` parent
- checks effective-column integrity first
- then reports how the child run changed out of sample

Why this step exists:
- it gives a fast top-level answer before the more detailed Layer 1 block view
""".strip()
        ),
        code_cell(staged_scheme_report_cell("STAGED", "stage_a_top_level")),
        markdown_cell(
            """
## Layer 1: Mutually Exclusive Blocks

This is the thesis-grade `FS2` attribution layer.

What conclusions are justified:
- which blocks help this specific `LEAR FS2` parent conditional on the rest staying present
- which blocks look weak, redundant, or ambiguous under the current parent tuning

What conclusions are not justified:
- that one negative delta automatically proves a block should be deleted
- that a weak marginal block has no value in every other model or feature bundle
""".strip()
        ),
        code_cell(staged_scheme_report_cell("STAGED", "layer1_mutually_exclusive", include_layer2_candidates=True)),
        markdown_cell(
            """
## Layer 2: Optional Follow-Up

Layer 2 stays selective on purpose.

Use it only when a Layer 1 block looks uncertain, mixed, or worth a deeper subgroup check.
""".strip()
        ),
        code_cell(staged_layer2_results_cell("STAGED")),
        markdown_cell(
            """
## Lightweight Diagnostics

This section refits the saved parent once on a representative validation origin and reports coefficient activity by block.

It is supportive evidence only. Correlated linear blocks can still look active while their marginal ablation effect stays weak or unstable.
""".strip()
        ),
        code_cell(staged_diagnostics_report_cell("FS2", "lear_fs2_benchmark", "lear")),
    ]

    notebooks["13_fs2_xgboost_ablation.ipynb"] = [
        markdown_cell(
            """
# 13 FS2 XGBoost Ablation

This notebook is the generator-owned `FS2 XGBoost` staged ablation workflow.

Purpose of this layer:
- inspect the endogenous-plus-calendar `FS2` foundation before `FS3` starts
- keep the analysis model-specific
- separate broad orientation from block-level attribution

Interpretation rule:
- ablation shows marginal contribution conditional on the rest of the parent bundle staying present
- it does **not** show standalone independent value, and it does **not** prove causal truth
""".strip()
        ),
        code_cell(COMMON_SETUP),
        markdown_cell(
            """
## Optional execution hook

This snippet reruns the staged `FS2 XGBoost` ablation against the saved `xgboost_fs2_benchmark` parent.
""".strip()
        ),
        code_cell(staged_execution_toggle_cell("FS2", "xgboost_fs2_benchmark", "xgboost")),
        code_cell(stage_policy_cell("FS2")),
        code_cell(model_status_cell(["xgboost"])),
        code_cell(tuning_placeholder_cell("xgboost", "FS2")),
        code_cell(run_availability_cell(["xgboost_fs2_benchmark"])),
        code_cell(optional_run_summary_cell("xgboost_fs2_benchmark", ["naive_previous_week", "naive_previous_year", "xgboost_fs2"])),
        markdown_cell(
            """
## Parent reminder and stale-result rule

Read notebooks `09` and `11` first when you want the benchmark context for this parent.

This notebook answers the follow-up question:
- once the `FS2 XGBoost` parent exists, which broad pieces of the endogenous and calendar foundation still matter when removed one at a time?
""".strip()
        ),
        code_cell(staged_ablation_setup_cell("STAGED", "FS2", "xgboost_fs2_benchmark", "xgboost")),
        markdown_cell("## Scheme availability and compatibility"),
        code_cell(staged_ablation_availability_cell("STAGED")),
        markdown_cell(
            """
## Stage A: Top-Level Orientation

Positive delta means the model got worse after removal, so that broad block was helping.
Negative delta means the child improved after removal, so that block may be weak, redundant, or poorly aligned with the current parent tuning.
""".strip()
        ),
        code_cell(staged_scheme_report_cell("STAGED", "stage_a_top_level")),
        markdown_cell(
            """
## Layer 1: Mutually Exclusive Blocks

This is the main `FS2` attribution layer for `XGBoost`.

Use it to identify:
- likely helpful blocks
- likely harmful blocks
- near-zero or ambiguous blocks
- blocks worth a selective Layer 2 follow-up
""".strip()
        ),
        code_cell(staged_scheme_report_cell("STAGED", "layer1_mutually_exclusive", include_layer2_candidates=True)),
        markdown_cell(
            """
## Layer 2: Optional Follow-Up

Only run Layer 2 for a small number of blocks. Each subgroup bundle still triggers near-full child reruns.
""".strip()
        ),
        code_cell(staged_layer2_results_cell("STAGED")),
        markdown_cell(
            """
## Lightweight Diagnostics

This section refits the saved parent once on a representative validation origin and reports block-level gain and split usage.

Tree importance is supportive only. It can disagree with ablation because a block can appear often in trees while still adding little marginal value once the full parent bundle is present.
""".strip()
        ),
        code_cell(staged_diagnostics_report_cell("FS2", "xgboost_fs2_benchmark", "xgboost")),
    ]

    notebooks["14_fs2_feature_value_results.ipynb"] = [
        markdown_cell(
            """
# 14 FS2 Staged Ablation Evaluation

This notebook is the combined evaluation layer for the upgraded `FS2` staged ablation workflow across `LEAR` and `XGBoost`.

It has two jobs:
- synthesize the baseline `FS2` staged-ablation results across both models
- optionally show a revised candidate lineage after notebook `15` reruns a pruned or redesigned parent
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(
            combined_staged_setup_cell(
                "FS2_BASELINE",
                "FS2",
                [
                    {"parent_run_label": "lear_fs2_benchmark", "model_family": "lear", "model_label": "LEAR", "model_name": "lear_fs2"},
                    {"parent_run_label": "xgboost_fs2_benchmark", "model_family": "xgboost", "model_label": "XGBoost", "model_name": "xgboost_fs2"},
                ],
            )
        ),
        code_cell(
            combined_staged_setup_cell(
                "FS2_CANDIDATE",
                "FS2",
                [
                    {"parent_run_label": FS2_LEAR_CANDIDATE_RUN_LABEL, "model_family": "lear", "model_label": "LEAR candidate", "model_name": "lear_fs2"},
                    {"parent_run_label": FS2_XGBOOST_CANDIDATE_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost candidate", "model_name": "xgboost_fs2"},
                ],
            )
        ),
        markdown_cell(
            """
## Baseline Compatibility Gate

This is the active thesis-grade baseline synthesis. Only compatible staged-ablation bundles are included.
""".strip()
        ),
        code_cell(combined_staged_availability_cell("FS2_BASELINE", "baseline FS2 lineage")),
        markdown_cell("## Baseline Stage A Across Both Models"),
        code_cell(combined_staged_scheme_synthesis_cell("FS2_BASELINE", "stage_a_top_level")),
        markdown_cell("## Baseline Layer 1 Across Both Models"),
        code_cell(combined_staged_scheme_synthesis_cell("FS2_BASELINE", "layer1_mutually_exclusive")),
        markdown_cell("## Baseline Layer 2 Follow-Up"),
        code_cell(combined_staged_layer2_cell("FS2_BASELINE")),
        markdown_cell("## Baseline Supportive Diagnostics"),
        code_cell(combined_staged_diagnostics_cell("FS2_BASELINE", "FS2")),
        markdown_cell(
            """
## Candidate Lineage Delta Check

After notebook `15` runs a revised parent, rerun this notebook to see whether the candidate benchmark improved and whether the staged-ablation story changed.
""".strip()
        ),
        code_cell(
            pruning_benchmark_delta_cell(
                [
                    {"parent_run_label": "lear_fs2_benchmark", "model_family": "lear", "model_label": "LEAR", "model_name": "lear_fs2"},
                    {"parent_run_label": "xgboost_fs2_benchmark", "model_family": "xgboost", "model_label": "XGBoost", "model_name": "xgboost_fs2"},
                ],
                [
                    {"parent_run_label": FS2_LEAR_CANDIDATE_RUN_LABEL, "model_family": "lear", "model_label": "LEAR candidate", "model_name": "lear_fs2"},
                    {"parent_run_label": FS2_XGBOOST_CANDIDATE_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost candidate", "model_name": "xgboost_fs2"},
                ],
            )
        ),
        markdown_cell("## Candidate Compatibility Gate"),
        code_cell(combined_staged_availability_cell("FS2_CANDIDATE", "candidate FS2 lineage")),
        markdown_cell("## Candidate Stage A Across Both Models"),
        code_cell(combined_staged_scheme_synthesis_cell("FS2_CANDIDATE", "stage_a_top_level")),
        markdown_cell("## Candidate Layer 1 Across Both Models"),
        code_cell(combined_staged_scheme_synthesis_cell("FS2_CANDIDATE", "layer1_mutually_exclusive")),
    ]

    notebooks["15_fs2_pruning_and_redesign_validation.ipynb"] = [
        markdown_cell(
            """
# 15 FS2 Pruning And Redesign Validation

This notebook is the `FS2` decision layer.

It does not treat one negative ablation delta as proof that a block is bad. Instead it supports the full validation loop:
- identify suspect blocks from the baseline staged ablation
- rerun a revised `FS2` parent with selected blocks removed
- optionally rerun staged ablation on the revised parent
- compare the revised parent against the baseline before freezing the `FS2` foundation
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(
            combined_staged_setup_cell(
                "PRUNING_BASELINE",
                "FS2",
                [
                    {"parent_run_label": "lear_fs2_benchmark", "model_family": "lear", "model_label": "LEAR", "model_name": "lear_fs2"},
                    {"parent_run_label": "xgboost_fs2_benchmark", "model_family": "xgboost", "model_label": "XGBoost", "model_name": "xgboost_fs2"},
                ],
            )
        ),
        code_cell(
            combined_staged_setup_cell(
                "PRUNING_CANDIDATE",
                "FS2",
                [
                    {"parent_run_label": FS2_LEAR_CANDIDATE_RUN_LABEL, "model_family": "lear", "model_label": "LEAR candidate", "model_name": "lear_fs2"},
                    {"parent_run_label": FS2_XGBOOST_CANDIDATE_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost candidate", "model_name": "xgboost_fs2"},
                ],
            )
        ),
        markdown_cell(
            """
## Optional execution hook

This is where pruning or redesign moves from interpretation to validation.

Recommended sequence:
1. choose one small candidate block set per model
2. rerun the candidate parent benchmark
3. inspect the parent metric delta
4. only then rerun staged ablation on the candidate lineage if the parent itself looks promising
""".strip()
        ),
        code_cell(
            pruning_execution_cell(
                "FS2",
                [
                    {"parent_run_label": "lear_fs2_benchmark", "model_family": "lear", "model_label": "LEAR", "model_name": "lear_fs2"},
                    {"parent_run_label": "xgboost_fs2_benchmark", "model_family": "xgboost", "model_label": "XGBoost", "model_name": "xgboost_fs2"},
                ],
                [
                    {"parent_run_label": FS2_LEAR_CANDIDATE_RUN_LABEL, "model_family": "lear", "model_label": "LEAR candidate", "model_name": "lear_fs2"},
                    {"parent_run_label": FS2_XGBOOST_CANDIDATE_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost candidate", "model_name": "xgboost_fs2"},
                ],
                comparison_run_label=FS2_CANDIDATE_COMPARISON_RUN_LABEL,
            )
        ),
        markdown_cell("## Baseline Availability"),
        code_cell(combined_staged_availability_cell("PRUNING_BASELINE", "baseline FS2 lineage")),
        markdown_cell(
            """
## Suggested Candidate Actions

This table translates the baseline Layer 1 evidence into cautious action categories.

It is a triage table, not a final verdict:
- `prune_candidate` means the block is weak enough to justify a revised-parent check
- `redesign_candidate` means the block looks mixed or unstable and may need better engineering instead of outright removal
- `keep_or_monitor` means the current evidence does not justify immediate pruning
""".strip()
        ),
        code_cell(pruning_action_table_cell("PRUNING_BASELINE_SUMMARY")),
        markdown_cell("## Candidate Benchmark Delta"),
        code_cell(
            pruning_benchmark_delta_cell(
                [
                    {"parent_run_label": "lear_fs2_benchmark", "model_family": "lear", "model_label": "LEAR", "model_name": "lear_fs2"},
                    {"parent_run_label": "xgboost_fs2_benchmark", "model_family": "xgboost", "model_label": "XGBoost", "model_name": "xgboost_fs2"},
                ],
                [
                    {"parent_run_label": FS2_LEAR_CANDIDATE_RUN_LABEL, "model_family": "lear", "model_label": "LEAR candidate", "model_name": "lear_fs2"},
                    {"parent_run_label": FS2_XGBOOST_CANDIDATE_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost candidate", "model_name": "xgboost_fs2"},
                ],
            )
        ),
        markdown_cell("## Candidate Ablation Availability"),
        code_cell(combined_staged_availability_cell("PRUNING_CANDIDATE", "candidate FS2 lineage")),
        markdown_cell("## Candidate Layer 1 Across Both Models"),
        code_cell(combined_staged_scheme_synthesis_cell("PRUNING_CANDIDATE", "layer1_mutually_exclusive")),
    ]


    notebooks["16_fs3_lear.ipynb"] = [
        markdown_cell(
            """
# 16 FS3 LEAR

`FS3` extends the shortlisted `FS2` foundation with the combined exogenous family stack now assumed available under the active methodology.

Current execution scope in this notebook:
- context: `all_exogenous_combo_parent`
- model family: `LEAR`
- family groups included together:
  - `full_horizon`
  - `day1_only`
  - `historical`

Interpretation rule:
- this notebook is about the **parent FS3 run** with all currently selected exogenous families included together
- grouped ablation remains separated in notebook `19_fs3_lear_ablation.ipynb`
""".strip()
        ),
        code_cell(COMMON_SETUP),
        *optional_execution_hook_cells(
            "run_fs3_ordered_benchmarks.py",
            FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL,
            extra_args=[
                "--stage",
                "combo",
                "--combo-model-family",
                "lear",
                "--combo-run-label",
                FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL,
                "--promoted-codes",
                *FS3_ALL_EXOGENOUS_CODES,
            ],
            heading="## Optional parent execution hook",
        ),
        markdown_cell(
            """
## Methodology scope

This notebook keeps the question narrow:
- compare the all-exogenous `FS3` LEAR parent against the relevant `FS2` baselines
- inspect the combined exogenous family groups that were added on top of `FS2`
- check whether the dedicated LEAR all-exogenous parent run is complete before reading any later ablation notebook
""".strip()
        ),
        code_cell(stage_policy_cell("FS3")),
        code_cell(model_status_cell(["lear", "xgboost", "prophet"])),
        code_cell(tuning_placeholder_cell("lear", "FS3")),
        code_cell(
            run_availability_cell(
                [
                    "lear_fs2_benchmark",
                    "xgboost_fs2_benchmark",
                    FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL,
                    FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL,
                    FS3_LEAR_AGGREGATE_RUN_LABEL,
                    FS3_XGBOOST_AGGREGATE_RUN_LABEL,
                    "case_week_selection",
                ]
            )
        ),
        markdown_cell("## Exogenous family diagnostics"),
        code_cell(fs3_all_exogenous_diagnostics_cell("lear")),
        markdown_cell("## Latest parent run summary"),
        code_cell(fs3_combo_run_summary_cell("lear")),
        markdown_cell(fs3_all_exogenous_execution_note("lear")),
        *expanded_report_cells(
            run_label=FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL,
            notebook_slug="16_fs3_lear",
            comparison_logic=fs3_all_exogenous_comparison_logic("lear"),
            week_title_prefix="FS3 LEAR all-exogenous parent benchmark comparison",
        ),
    ]

    notebooks["17_fs3_xgboost.ipynb"] = [
        markdown_cell(
            """
# 17 FS3 XGBoost

`FS3` extends the shortlisted `FS2` foundation with the combined exogenous family stack now assumed available under the active methodology.

Current execution scope in this notebook:
- context: `all_exogenous_combo_parent`
- model family: `XGBoost`
- family groups included together:
  - `full_horizon`
  - `day1_only`
  - `historical`

Interpretation rule:
- this notebook is about the **parent FS3 run** with all currently selected exogenous families included together
- grouped ablation remains separated in notebook `20_fs3_xgboost_ablation.ipynb`
""".strip()
        ),
        code_cell(COMMON_SETUP),
        *optional_execution_hook_cells(
            "run_fs3_ordered_benchmarks.py",
            FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL,
            extra_args=[
                "--stage",
                "combo",
                "--combo-model-family",
                "xgboost",
                "--combo-run-label",
                FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL,
                "--promoted-codes",
                *FS3_ALL_EXOGENOUS_CODES,
            ],
            heading="## Optional parent execution hook",
        ),
        markdown_cell(
            """
## Methodology scope

This notebook keeps the question narrow:
- compare the all-exogenous `FS3` XGBoost parent against the relevant `FS2` baselines
- inspect the combined exogenous family groups that were added on top of `FS2`
- check whether the dedicated XGBoost all-exogenous parent run is complete before reading any later ablation notebook
""".strip()
        ),
        code_cell(stage_policy_cell("FS3")),
        code_cell(model_status_cell(["lear", "xgboost", "prophet"])),
        code_cell(tuning_placeholder_cell("xgboost", "FS3")),
        code_cell(
            run_availability_cell(
                [
                    "lear_fs2_benchmark",
                    "xgboost_fs2_benchmark",
                    FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL,
                    FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL,
                    FS3_XGBOOST_AGGREGATE_RUN_LABEL,
                    FS3_LEAR_AGGREGATE_RUN_LABEL,
                    "case_week_selection",
                ]
            )
        ),
        markdown_cell("## Exogenous family diagnostics"),
        code_cell(fs3_all_exogenous_diagnostics_cell("xgboost")),
        markdown_cell("## Latest parent run summary"),
        code_cell(fs3_combo_run_summary_cell("xgboost")),
        markdown_cell(fs3_all_exogenous_execution_note("xgboost")),
        *expanded_report_cells(
            run_label=FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL,
            notebook_slug="17_fs3_xgboost",
            comparison_logic=fs3_all_exogenous_comparison_logic("xgboost"),
            week_title_prefix="FS3 XGBoost all-exogenous parent benchmark comparison",
        ),
    ]

    notebooks["18_fs3_benchmark_and_comparison.ipynb"] = [
        markdown_cell(
            """
# 18 FS3 Benchmark And Comparison

This notebook compares the current all-exogenous `FS3` parent run against the relevant `FS2` baselines and against each other.

It is a reporting notebook:
- no new benchmark methodology is introduced here
- it reads the latest saved parent runs
- it only compares model-context pairs that are actually available on disk

Current intended comparison set:
- official naive benchmark
- `LEAR FS2`
- `XGBoost FS2`
- `Prophet FS2` when available
- `LEAR FS3` with the combined full-horizon, day-1, and historical exogenous stack
- `XGBoost FS3` with the combined full-horizon, day-1, and historical exogenous stack
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(
            """
from hourly_da.notebook_support import (
    apply_standard_matplotlib_style,
    build_compared_models_overview,
    build_dm_summary_table,
    build_model_style_map,
    build_reporting_summary_table,
    build_runtime_summary_table,
    build_week_metrics_for_predictions,
    filter_available_comparison_specs,
    load_standard_report_bundle,
    render_plot_gallery,
    style_dm_summary_table,
    style_model_overview_table,
    style_reporting_summary_table,
    style_runtime_summary_table,
    write_actual_vs_predicted_scatter_plot,
    write_horizon_error_plot,
    write_mae_by_hour_of_day_plot,
    write_residual_distribution_plot,
    write_standard_week_selection_plots,
)
""".strip()
        ),
        code_cell(
            run_availability_cell(
                [
                    "lear_fs2_benchmark",
                    "xgboost_fs2_benchmark",
                    "prophet_fs2_benchmark",
                    FS3_COMBO_RUN_LABEL,
                    "case_week_selection",
                ]
            )
        ),
        markdown_cell(
            """
## Comparison setup

The comparison notebook prefers the shared all-exogenous `FS3` combo parent run as the anchor because that guarantees the current exogenous context is present. If that run does not exist yet, it falls back to the latest combined `FS2` comparison run so the notebook still explains what is missing.
""".strip()
        ),
        code_cell(
            f"""
from IPython.display import Image

comparison_run_dir = (
    latest_run_or_none("{FS3_COMBO_RUN_LABEL}")
    or latest_run_or_none("model_comparison")
)
report_bundle = None
model_styles = {{}}
report_output_dir = None
official_naive_model = None
HORIZON_PLOT_MODELS = []
WEEK_PLOT_MODELS = []
DIAGNOSTIC_MODELS = []
DM_CHALLENGER_MODELS = []

if comparison_run_dir is None:
    print("No comparable FS2 or FS3 run exists yet.")
else:
    apply_standard_matplotlib_style()
    official_naive = load_json(comparison_run_dir, "official_naive_reference.json")
    official_naive_model = str(official_naive["model"])
    official_naive_display = f"Naive benchmark ({{official_naive_model.replace('naive_', '').replace('_', ' ').title()}})"

    comparison_specs = [
        {{
            "model": official_naive_model,
            "display_name": official_naive_display,
            "description": "Validation-selected seasonal naive benchmark carried into the FS3 comparison.",
            "role": "benchmark",
        }},
    ]
    comparison_specs.extend(
        filter_available_comparison_specs(
            output_root=output_root,
            current_run_dir=comparison_run_dir,
            candidate_specs=[
                {{
                    "model": "lear_fs2",
                    "run_label": "lear_fs2_benchmark",
                    "display_name": "LEAR FS2",
                    "description": "Shortlisted linear baseline from notebook 08.",
                    "role": "baseline",
                }},
                {{
                    "model": "xgboost_fs2",
                    "run_label": "xgboost_fs2_benchmark",
                    "display_name": "XGBoost FS2",
                    "description": "Shortlisted tree baseline from notebook 09.",
                    "role": "baseline",
                }},
                {{
                    "model": "prophet_fs2",
                    "run_label": "prophet_fs2_benchmark",
                    "display_name": "Prophet FS2",
                    "description": "Additive baseline from notebook 10 when available.",
                    "role": "baseline",
                }},
                {{
                    "model": "{fs3_combo_model_name("lear")}",
                    "source": "current",
                    "display_name": "LEAR FS3",
                    "description": "FS3 linear parent with the combined all-exogenous stack.",
                    "role": "current",
                }},
                {{
                    "model": "{fs3_combo_model_name("xgboost")}",
                    "source": "current",
                    "display_name": "XGBoost FS3",
                    "description": "FS3 tree parent with the combined all-exogenous stack.",
                    "role": "current",
                }},
            ],
        )
    )

    seen_models = set()
    COMPARISON_MODEL_SPECS = []
    for spec in comparison_specs:
        model_name = str(spec["model"])
        if model_name in seen_models:
            continue
        seen_models.add(model_name)
        COMPARISON_MODEL_SPECS.append(spec)

    HORIZON_PLOT_MODELS = [spec["model"] for spec in COMPARISON_MODEL_SPECS]
    WEEK_PLOT_MODELS = HORIZON_PLOT_MODELS.copy()
    DIAGNOSTIC_MODELS = WEEK_PLOT_MODELS.copy()
    DM_CHALLENGER_MODELS = [
        model_name
        for model_name in HORIZON_PLOT_MODELS
        if model_name not in [official_naive_model, "prophet_fs2"]
    ]

    if not COMPARISON_MODEL_SPECS:
        print("No comparison models were available for the FS3 benchmark notebook.")
    else:
        report_bundle = load_standard_report_bundle(
            output_root=output_root,
            current_run_dir=comparison_run_dir,
            comparison_specs=COMPARISON_MODEL_SPECS,
        )
        model_styles = build_model_style_map(
            report_bundle["comparison_specs"],
            official_naive_model=str(report_bundle["official_naive"]["model"]),
        )
        report_output_dir = output_root / "notebook_artifacts" / "18_fs3_benchmark_and_comparison" / comparison_run_dir.name / "standard_report"
        report_output_dir.mkdir(parents=True, exist_ok=True)

        print(f"Current run anchor: {{comparison_run_dir.name}}")
        print(f"Naive benchmark: {{official_naive_model}}")
        print(f"Expanded comparison models: {{[spec['model'] for spec in COMPARISON_MODEL_SPECS]}}")
""".strip()
        ),
        markdown_cell("## 1. Short overview of compared models"),
        code_cell(expanded_model_overview_cell()),
        markdown_cell("## 2. Main validation and test summary tables"),
        code_cell(expanded_reporting_summary_cell()),
        markdown_cell("## 3. By-horizon error view"),
        code_cell(expanded_horizon_plot_cell()),
        markdown_cell("## 4. Forecast vs actual on the frozen week selections"),
        code_cell(expanded_week_report_cell("FS3 benchmark comparison")),
        markdown_cell("## 5. Diagnostic plots"),
        code_cell(expanded_diagnostic_plots_cell()),
        markdown_cell("## 6. Statistical comparison"),
        code_cell(expanded_dm_summary_cell()),
        markdown_cell("## 7. Runtime and practicality summary"),
        code_cell(expanded_runtime_summary_cell()),
    ]

    notebooks["19_fs3_lear_ablation.ipynb"] = [
        markdown_cell(
            """
# 19 FS3 LEAR Ablation

This notebook is the generator-owned `FS3 LEAR` ablation workflow for the full combo parent.

Methodology of the upgraded workflow:
- `Stage A`: true top-level ablation on `endogenous_core`, `calendar`, and `exogenous_total`
- `Layer 1`: true mutually exclusive block ablation on the full parent bundle
- `Layer 2`: optional subgroup follow-up for selected Layer 1 blocks
- preflight integrity checks run on the effective branch-specific model columns before results are trusted

Critical validity rule:
- old FS3 combo ablation runs produced before the fixed domestic-versus-neighbor taxonomy, or before the current scheme hashes were stored, are treated as stale and are excluded from the active reporting path

Interpretation rule:
- ablation shows marginal contribution conditional on the rest of the parent bundle staying present
- it does **not** show standalone independent value, and it does **not** prove causal truth
""".strip()
        ),
        code_cell(COMMON_SETUP),
        markdown_cell(
            """
## Optional execution hook

This snippet controls execution.

What it does:
- reruns the staged ablation against the saved `FS3 LEAR` combo parent
- runs `Stage A` and `Layer 1` by default
- runs `Layer 2` only when you explicitly enable it for selected blocks

How to use it:
- keep `ALLOW_HEAVY_RERUN = False` to read saved artifacts only
- rerun notebook `16` first if the parent benchmark itself must be regenerated
- enable only a few Layer 2 targets at a time, because each one adds near-full child reruns
""".strip()
        ),
        code_cell(staged_execution_toggle_cell("FS3", FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL, "lear")),
        code_cell(stage_policy_cell("FS3")),
        code_cell(model_status_cell(["lear"])),
        code_cell(tuning_placeholder_cell("lear", "FS3")),
        code_cell(run_availability_cell([FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL])),
        markdown_cell(
            """
## Parent reminder and stale-result rule

Read notebook `16` and notebook `18` first when you want the full benchmark comparison against `FS2`.

This notebook answers a narrower follow-up question:
- once the `FS3 LEAR` combo parent is accepted, which broad blocks still matter when removed one at a time?
- how does that answer change between `D only` and the stitched full horizon?

Why previous numbers can be stale:
- the domestic/crossborder FS3 overlap bug was fixed
- the staged block registry now has explicit scheme hashes and branch-specific preflight checks
- any older saved aggregate without matching hashes is excluded here
""".strip()
        ),
        code_cell(fs3_combo_run_summary_cell("lear")),
        markdown_cell(
            """
## Scheme availability and compatibility

This section checks whether saved staged-ablation artifacts are still compatible with the current code.

What is validated:
- scheme name and version
- effective scheme hash
- feature taxonomy hash
- stored preflight validity

If compatibility breaks, the notebook refuses to treat the old result as active evidence.
""".strip()
        ),
        code_cell(staged_ablation_setup_cell("STAGED", "FS3", FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL, "lear")),
        code_cell(staged_ablation_availability_cell("STAGED")),
        markdown_cell(
            """
## Stage A: Top-Level Orientation

What this section does:
- removes one of three top-level blocks from the full `FS3 LEAR` parent
- checks the group integrity on the effective branch inputs first
- then shows how the child run changes out of sample

Why this step exists:
- it gives a fast high-level orientation before the more detailed Layer 1 block view

How to read it:
- positive delta means the model got worse when the block was removed, so that block was helping
- negative delta means the child improved after removal, so the block may be weak, redundant, or mildly harmful
- day-1 blocks naturally matter more for `D only`; full-horizon deltas can dilute that effect
""".strip()
        ),
        code_cell(staged_scheme_report_cell("STAGED", "stage_a_top_level")),
        markdown_cell(
            """
## Layer 1: Mutually Exclusive Blocks

What this section does:
- runs the thesis-grade block ablation on a mutually exclusive block registry
- verifies that every effective model column is assigned exactly once before results are shown

Why this step exists:
- it replaces the old overlapping domestic-versus-domestic-plus-neighbors logic
- it gives interpretable blocks that can be discussed in plain language

What conclusions are justified:
- which blocks help this specific `FS3 LEAR` parent conditional on the rest staying present
- which blocks look weak or uncertain under the current parent tuning

What conclusions are not justified:
- that a block has no standalone predictive value everywhere
- that a weak marginal block is always useless in a different model or feature bundle
""".strip()
        ),
        code_cell(staged_scheme_report_cell("STAGED", "layer1_mutually_exclusive", include_layer2_candidates=True)),
        markdown_cell(
            """
## Layer 2: Optional Follow-Up

This section stays selective on purpose.

What it does:
- drills into only the Layer 1 blocks that were explicitly rerun as subgroup analyses
- keeps the full Layer 1 parent bundle fixed in the background

How to interpret it:
- these subgroup deltas answer a local follow-up question inside one chosen Layer 1 block
- they should not be mixed back into Stage A or Layer 1 averages as if they were the same exercise
""".strip()
        ),
        code_cell(staged_layer2_results_cell("STAGED")),
        markdown_cell(
            """
## Lightweight Diagnostics

What this section does:
- refits the saved parent model once on a representative validation origin
- reports coefficient activity by Layer 1 block for `LEAR`

Why this exists:
- it helps explain whether a block was active in one representative fit
- it does **not** replace ablation, because correlated blocks can still look active while their marginal ablation effect stays weak or unstable
""".strip()
        ),
        code_cell(staged_diagnostics_report_cell("FS3", FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL, "lear")),
    ]

    notebooks["20_fs3_xgboost_ablation.ipynb"] = [
        markdown_cell(
            """
# 20 FS3 XGBoost Ablation

This notebook is the generator-owned `FS3 XGBoost` ablation workflow for the full combo parent.

Methodology of the upgraded workflow:
- `Stage A`: true top-level ablation on `endogenous_core`, `calendar`, and `exogenous_total`
- `Layer 1`: true mutually exclusive block ablation on the full parent bundle
- `Layer 2`: optional subgroup follow-up for selected Layer 1 blocks
- preflight integrity checks run on the effective branch-specific model columns before results are trusted

Critical validity rule:
- old FS3 combo ablation runs produced before the fixed domestic-versus-neighbor taxonomy, or before the current scheme hashes were stored, are treated as stale and are excluded from the active reporting path

Interpretation rule:
- ablation shows marginal contribution conditional on the rest of the parent bundle staying present
- it does **not** show standalone independent value, and it does **not** prove causal truth
""".strip()
        ),
        code_cell(COMMON_SETUP),
        markdown_cell(
            """
## Optional execution hook

This snippet controls execution.

What it does:
- reruns the staged ablation against the saved `FS3 XGBoost` combo parent
- runs `Stage A` and `Layer 1` by default
- runs `Layer 2` only when you explicitly enable it for selected blocks

How to use it:
- keep `ALLOW_HEAVY_RERUN = False` to read saved artifacts only
- rerun notebook `17` first if the parent benchmark itself must be regenerated
- enable only a few Layer 2 targets at a time, because each one adds near-full child reruns
""".strip()
        ),
        code_cell(staged_execution_toggle_cell("FS3", FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL, "xgboost")),
        code_cell(stage_policy_cell("FS3")),
        code_cell(model_status_cell(["xgboost"])),
        code_cell(tuning_placeholder_cell("xgboost", "FS3")),
        code_cell(run_availability_cell([FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL])),
        markdown_cell(
            """
## Parent reminder and stale-result rule

Read notebook `17` and notebook `18` first when you want the full benchmark comparison against `FS2`.

This notebook answers a narrower follow-up question:
- once the `FS3 XGBoost` combo parent is accepted, which broad blocks still matter when removed one at a time?
- how does that answer change between `D only` and the stitched full horizon?

Why previous numbers can be stale:
- the domestic/crossborder FS3 overlap bug was fixed
- the staged block registry now has explicit scheme hashes and branch-specific preflight checks
- any older saved aggregate without matching hashes is excluded here
""".strip()
        ),
        code_cell(fs3_combo_run_summary_cell("xgboost")),
        markdown_cell(
            """
## Scheme availability and compatibility

This section checks whether saved staged-ablation artifacts are still compatible with the current code.

What is validated:
- scheme name and version
- effective scheme hash
- feature taxonomy hash
- stored preflight validity

If compatibility breaks, the notebook refuses to treat the old result as active evidence.
""".strip()
        ),
        code_cell(staged_ablation_setup_cell("STAGED", "FS3", FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL, "xgboost")),
        code_cell(staged_ablation_availability_cell("STAGED")),
        markdown_cell(
            """
## Stage A: Top-Level Orientation

What this section does:
- removes one of three top-level blocks from the full `FS3 XGBoost` parent
- checks the group integrity on the effective branch inputs first
- then shows how the child run changes out of sample

Why this step exists:
- it gives a fast high-level orientation before the more detailed Layer 1 block view

How to read it:
- positive delta means the model got worse when the block was removed, so that block was helping
- negative delta means the child improved after removal, so the block may be weak, redundant, or mildly harmful
- day-1 blocks naturally matter more for `D only`; full-horizon deltas can dilute that effect
""".strip()
        ),
        code_cell(staged_scheme_report_cell("STAGED", "stage_a_top_level")),
        markdown_cell(
            """
## Layer 1: Mutually Exclusive Blocks

What this section does:
- runs the thesis-grade block ablation on a mutually exclusive block registry
- verifies that every effective model column is assigned exactly once before results are shown

Why this step exists:
- it replaces the old overlapping domestic-versus-domestic-plus-neighbors logic
- it gives interpretable blocks that can be discussed in plain language

What conclusions are justified:
- which blocks help this specific `FS3 XGBoost` parent conditional on the rest staying present
- which blocks look weak or uncertain under the current parent tuning

What conclusions are not justified:
- that a block has no standalone predictive value everywhere
- that a weak marginal block is always useless in a different model or feature bundle
""".strip()
        ),
        code_cell(staged_scheme_report_cell("STAGED", "layer1_mutually_exclusive", include_layer2_candidates=True)),
        markdown_cell(
            """
## Layer 2: Optional Follow-Up

This section stays selective on purpose.

What it does:
- drills into only the Layer 1 blocks that were explicitly rerun as subgroup analyses
- keeps the full Layer 1 parent bundle fixed in the background

How to interpret it:
- these subgroup deltas answer a local follow-up question inside one chosen Layer 1 block
- they should not be mixed back into Stage A or Layer 1 averages as if they were the same exercise
""".strip()
        ),
        code_cell(staged_layer2_results_cell("STAGED")),
        markdown_cell(
            """
## Lightweight Diagnostics

What this section does:
- refits the saved parent model once on a representative validation origin
- reports block-level gain and split usage for `XGBoost`

Why this exists:
- it helps explain whether the tree used a block in one representative fit
- it does **not** replace ablation, because a block can appear frequently inside trees while still having weak marginal value once the rest of the parent bundle is present
""".strip()
        ),
        code_cell(staged_diagnostics_report_cell("FS3", FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL, "xgboost")),
    ]

    notebooks["21_fs3_feature_value_results.ipynb"] = [
        markdown_cell(
            """
# 21 FS3 Staged Ablation Evaluation

This notebook is the combined evaluation and conclusion layer for the upgraded `FS3` staged ablation workflow across `LEAR` and `XGBoost`.

Active scope:
- `Stage A` synthesis across both models
- `Layer 1` synthesis across both models
- `Layer 2` only for compatible subgroup runs that were actually executed
- lightweight model-specific diagnostics as supportive evidence

Excluded from the main thesis-grade path by default:
- legacy `FS1` / `FS2` smoke-test ablation contexts
- old FS3 combo results that predate the fixed taxonomy or the current scheme hashes
- any saved aggregate whose compatibility checks no longer pass
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(
            combined_staged_setup_cell(
                "FS3_BASELINE",
                "FS3",
                [
                    {"parent_run_label": FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL, "model_family": "lear", "model_label": "LEAR", "model_name": "lear_fs3_combo_promoted"},
                    {"parent_run_label": FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost", "model_name": "xgboost_fs3_combo_promoted"},
                ],
            )
        ),
        code_cell(
            combined_staged_setup_cell(
                "FS3_CANDIDATE",
                "FS3",
                [
                    {"parent_run_label": FS3_LEAR_CANDIDATE_RUN_LABEL, "model_family": "lear", "model_label": "LEAR candidate", "model_name": "lear_fs3_combo_promoted"},
                    {"parent_run_label": FS3_XGBOOST_CANDIDATE_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost candidate", "model_name": "xgboost_fs3_combo_promoted"},
                ],
            )
        ),
        markdown_cell(
            """
## Baseline Compatibility Gate

This is the active thesis-grade baseline synthesis for the current `FS3` parent models.
""".strip()
        ),
        code_cell(combined_staged_availability_cell("FS3_BASELINE", "baseline FS3 lineage")),
        markdown_cell(
            """
## Baseline Stage A Across Both Models

This section answers the broad orientation question:
- how much information still comes from endogenous history,
- how much comes from calendar effects,
- and how much comes from the total exogenous bundle?
""".strip()
        ),
        code_cell(combined_staged_scheme_synthesis_cell("FS3_BASELINE", "stage_a_top_level")),
        markdown_cell(
            """
## Baseline Layer 1 Across Both Models

This is the main thesis-grade `FS3` attribution layer.

Important caution:
- a block can look weak on the stitched horizon even when it matters strongly for `D only`
- that is a reporting-lens issue, not automatically a feature-quality issue
""".strip()
        ),
        code_cell(combined_staged_scheme_synthesis_cell("FS3_BASELINE", "layer1_mutually_exclusive")),
        markdown_cell("## Baseline Layer 2 Follow-Up Results"),
        code_cell(combined_staged_layer2_cell("FS3_BASELINE")),
        markdown_cell("## Baseline Supportive Diagnostics"),
        code_cell(combined_staged_diagnostics_cell("FS3_BASELINE", "FS3")),
        markdown_cell(
            """
## Candidate Lineage Delta Check

After notebook `22` reruns a revised parent, rerun this notebook to inspect whether the candidate benchmark improved and whether the staged-ablation story changed.
""".strip()
        ),
        code_cell(
            pruning_benchmark_delta_cell(
                [
                    {"parent_run_label": FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL, "model_family": "lear", "model_label": "LEAR", "model_name": "lear_fs3_combo_promoted"},
                    {"parent_run_label": FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost", "model_name": "xgboost_fs3_combo_promoted"},
                ],
                [
                    {"parent_run_label": FS3_LEAR_CANDIDATE_RUN_LABEL, "model_family": "lear", "model_label": "LEAR candidate", "model_name": "lear_fs3_combo_promoted"},
                    {"parent_run_label": FS3_XGBOOST_CANDIDATE_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost candidate", "model_name": "xgboost_fs3_combo_promoted"},
                ],
            )
        ),
        markdown_cell("## Candidate Compatibility Gate"),
        code_cell(combined_staged_availability_cell("FS3_CANDIDATE", "candidate FS3 lineage")),
        markdown_cell("## Candidate Stage A Across Both Models"),
        code_cell(combined_staged_scheme_synthesis_cell("FS3_CANDIDATE", "stage_a_top_level")),
        markdown_cell("## Candidate Layer 1 Across Both Models"),
        code_cell(combined_staged_scheme_synthesis_cell("FS3_CANDIDATE", "layer1_mutually_exclusive")),
        markdown_cell(
            """
## Final Conclusion

How to summarize the combined evidence:
- blocks that are strongly positive in both models are the most trustworthy keepers
- blocks that are strongly negative in both models are the strongest removal candidates
- blocks with mixed signs or near-zero deltas need cautious interpretation
- `Layer 2` should only be used as a targeted follow-up, not as a replacement for the broader `Stage A` and `Layer 1` view

Remaining limitations:
- this is still rolling-origin evidence, not fold CV
- marginal block value is conditional on the chosen parent tuning and parent feature bundle
- diagnostics are based on one representative validation fit, not a full multi-origin native-importance study
""".strip()
        ),
    ]

    notebooks["22_fs3_pruning_and_redesign_validation.ipynb"] = [
        markdown_cell(
            """
# 22 FS3 Pruning And Redesign Validation

This notebook is the `FS3` decision layer.

It comes after the `FS3` benchmark and staged-ablation notebooks, so it works on top of the frozen `FS2` foundation rather than redefining it.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(
            combined_staged_setup_cell(
                "PRUNING_BASELINE",
                "FS3",
                [
                    {"parent_run_label": FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL, "model_family": "lear", "model_label": "LEAR", "model_name": "lear_fs3_combo_promoted"},
                    {"parent_run_label": FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost", "model_name": "xgboost_fs3_combo_promoted"},
                ],
            )
        ),
        code_cell(
            combined_staged_setup_cell(
                "PRUNING_CANDIDATE",
                "FS3",
                [
                    {"parent_run_label": FS3_LEAR_CANDIDATE_RUN_LABEL, "model_family": "lear", "model_label": "LEAR candidate", "model_name": "lear_fs3_combo_promoted"},
                    {"parent_run_label": FS3_XGBOOST_CANDIDATE_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost candidate", "model_name": "xgboost_fs3_combo_promoted"},
                ],
            )
        ),
        markdown_cell(
            """
## Optional execution hook

Use this notebook to validate whether a suspicious `FS3` block should actually be removed or redesigned.

Recommended sequence:
1. choose one small candidate block set per model from the baseline Layer 1 results
2. rerun the revised parent benchmark
3. inspect the parent metric delta
4. rerun staged ablation on the candidate lineage only if the revised parent itself looks promising
""".strip()
        ),
        code_cell(
            pruning_execution_cell(
                "FS3",
                [
                    {"parent_run_label": FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL, "model_family": "lear", "model_label": "LEAR", "model_name": "lear_fs3_combo_promoted"},
                    {"parent_run_label": FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost", "model_name": "xgboost_fs3_combo_promoted"},
                ],
                [
                    {"parent_run_label": FS3_LEAR_CANDIDATE_RUN_LABEL, "model_family": "lear", "model_label": "LEAR candidate", "model_name": "lear_fs3_combo_promoted"},
                    {"parent_run_label": FS3_XGBOOST_CANDIDATE_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost candidate", "model_name": "xgboost_fs3_combo_promoted"},
                ],
            )
        ),
        markdown_cell("## Baseline Availability"),
        code_cell(combined_staged_availability_cell("PRUNING_BASELINE", "baseline FS3 lineage")),
        markdown_cell("## Suggested Candidate Actions"),
        code_cell(pruning_action_table_cell("PRUNING_BASELINE_SUMMARY")),
        markdown_cell("## Candidate Benchmark Delta"),
        code_cell(
            pruning_benchmark_delta_cell(
                [
                    {"parent_run_label": FS3_LEAR_COMBO_BENCHMARK_RUN_LABEL, "model_family": "lear", "model_label": "LEAR", "model_name": "lear_fs3_combo_promoted"},
                    {"parent_run_label": FS3_XGBOOST_COMBO_BENCHMARK_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost", "model_name": "xgboost_fs3_combo_promoted"},
                ],
                [
                    {"parent_run_label": FS3_LEAR_CANDIDATE_RUN_LABEL, "model_family": "lear", "model_label": "LEAR candidate", "model_name": "lear_fs3_combo_promoted"},
                    {"parent_run_label": FS3_XGBOOST_CANDIDATE_RUN_LABEL, "model_family": "xgboost", "model_label": "XGBoost candidate", "model_name": "xgboost_fs3_combo_promoted"},
                ],
            )
        ),
        markdown_cell("## Candidate Ablation Availability"),
        code_cell(combined_staged_availability_cell("PRUNING_CANDIDATE", "candidate FS3 lineage")),
        markdown_cell("## Candidate Layer 1 Across Both Models"),
        code_cell(combined_staged_scheme_synthesis_cell("PRUNING_CANDIDATE", "layer1_mutually_exclusive")),
    ]

    notebooks["23_fs3_decision_relevant_forecast_evaluation.ipynb"] = [
        markdown_cell(
            """
# 23 FS3 Decision-Relevant Forecast Evaluation

This notebook is the generator-owned **final DA evaluation layer before the thesis conclusion**.

The goal is not to find the single lowest-error forecaster in a forecasting-paper sense. The goal is to decide whether the current deterministic hourly DA forecast is sufficiently realistic, robust, and implementable for downstream thesis use in scenario generation and stochastic optimisation.

The decision frame is:
- official naive benchmark
- best/current FS2 reference
- final FS3 candidates

The comparison is intentionally wider than MAE:
- transparent classical accuracy with `rMAE` anchored to the official naive benchmark
- horizon robustness across `D` through `D+4`
- daily price-level retention
- intraday shape retention
- expensive/cheap-hour identification
- tail and high-volatility behaviour
- frozen objective week behaviour
- runtime, implementability, and thesis explainability

No hidden composite score is used.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(
            """
from IPython.display import Image

import matplotlib.pyplot as plt
from matplotlib import dates as mdates

from hourly_da.core.forecast_evaluation import (
    APPENDIX_WEEK_CATEGORIES,
    THESIS_CORE_WEEK_CATEGORIES,
    build_candidate_style_map,
    build_model_selection_summary,
    build_recommendation_inputs,
    build_stitched_d_only_predictions,
    build_week_metric_summary,
    compute_classical_metrics,
    compute_daily_level_metrics,
    compute_daily_shape_metrics,
    compute_diebold_mariano_table,
    compute_horizon_metrics,
    compute_tail_metrics,
    compute_topk_hour_metrics,
    default_decision_thresholds,
    discover_final_candidate_runs,
    load_candidate_model_settings,
    load_candidate_predictions,
    load_candidate_runtime_summary,
    load_frozen_selected_weeks,
    load_official_naive_denominators,
    recommend_candidate,
    run_metric_smoke_checks,
    summarize_candidate_coverage,
    summarize_duplicate_origin_targets,
    summarize_local_day_lengths,
    summarize_missingness,
    summarize_stitched_overlap_check,
)
""".strip()
        ),
        markdown_cell(
            """
## Purpose and stopping guidance

Validation remains the structural decision surface. Test is a holdout confirmation layer, not a second tuning loop.

The configurable guidance below is deliberately visible:
- `validation_rMAE < 1.00` is the minimum practical threshold
- `validation_rMAE < 0.95` is preferred
- most major horizons should remain below `rMAE = 1.00`
- large systematic daily level bias is a warning
- shape retention and top-k recall are judged comparatively
- tail failures and objective week failures are reported explicitly
- if FS3 only improves marginally over FS2, the simpler FS2 reference may remain the thesis candidate

Optional `top-6` recall is omitted here to keep the notebook focused on the core `top-3` decision signal.
""".strip()
        ),
        code_cell(
            """
DECISION_THRESHOLDS = default_decision_thresholds()
display(
    pd.DataFrame(
        [{"threshold": key, "value": value} for key, value in DECISION_THRESHOLDS.items()]
    )
)
""".strip()
        ),
        code_cell(
            """
comparison_discovery = discover_final_candidate_runs(output_root)
candidate_frame = comparison_discovery["candidates"].copy()
availability_table = comparison_discovery["availability"].copy()
fs2_selection_table = comparison_discovery["fs2_selection_table"].copy()
fs2_selection_rule = str(comparison_discovery["fs2_selection_rule"])
official_naive_reference = comparison_discovery["official_naive_reference"]
official_naive_model = str(comparison_discovery["official_naive_model"])
naive_prediction_available = bool(comparison_discovery["naive_prediction_available"])
candidate_order = candidate_frame["candidate_key"].astype(str).tolist()
candidate_label_order = candidate_frame["candidate_label"].astype(str).tolist()
candidate_label_map = candidate_frame.set_index("candidate_key")["candidate_label"].to_dict()
candidate_style_map = build_candidate_style_map(candidate_frame)
report_output_dir = output_root / "notebook_artifacts" / "23_fs3_decision_relevant_forecast_evaluation"
report_output_dir.mkdir(parents=True, exist_ok=True)

timing_rows = []

def _timed(step_name, fn):
    started = time.perf_counter()
    result = fn()
    timing_rows.append({"step": step_name, "seconds": time.perf_counter() - started})
    return result

candidate_predictions = _timed(
    "load_candidate_predictions",
    lambda: load_candidate_predictions(candidate_frame=candidate_frame, config=config),
)
candidate_runtime = _timed(
    "load_candidate_runtime_summary",
    lambda: load_candidate_runtime_summary(candidate_frame),
)
candidate_settings = _timed(
    "load_candidate_model_settings",
    lambda: load_candidate_model_settings(candidate_frame),
)
naive_denominators = _timed(
    "load_official_naive_denominators",
    lambda: load_official_naive_denominators(
        run_dir=comparison_discovery["rmae_reference_run_dir"],
        official_naive_model=official_naive_model,
    ),
)
classical_metrics = _timed(
    "compute_classical_metrics",
    lambda: compute_classical_metrics(candidate_predictions, naive_denominators),
)
horizon_metrics = _timed(
    "compute_horizon_metrics",
    lambda: compute_horizon_metrics(candidate_predictions, naive_denominators),
)
daily_level_metrics, daily_level_summary = _timed(
    "compute_daily_level_metrics",
    lambda: compute_daily_level_metrics(candidate_predictions),
)
daily_shape_metrics, daily_shape_summary = _timed(
    "compute_daily_shape_metrics",
    lambda: compute_daily_shape_metrics(candidate_predictions),
)
topk_daily_metrics, topk_summary = _timed(
    "compute_topk_hour_metrics_top3_only",
    lambda: compute_topk_hour_metrics(candidate_predictions, ks=(3,)),
)
tail_metrics = _timed(
    "compute_tail_metrics",
    lambda: compute_tail_metrics(candidate_predictions),
)
coverage_table = summarize_candidate_coverage(candidate_predictions)
missingness_table = summarize_missingness(candidate_predictions)
duplicate_table = summarize_duplicate_origin_targets(candidate_predictions)
local_day_length_table = summarize_local_day_lengths(candidate_predictions)
smoke_checks = run_metric_smoke_checks(config)
stitched_test_predictions = build_stitched_d_only_predictions(candidate_predictions, split_name="test")
stitched_overlap_check = summarize_stitched_overlap_check(stitched_test_predictions)
selected_weeks_run, selected_core_weeks = load_frozen_selected_weeks(
    output_root,
    categories=THESIS_CORE_WEEK_CATEGORIES,
)
_, selected_appendix_weeks = load_frozen_selected_weeks(
    output_root,
    categories=APPENDIX_WEEK_CATEGORIES,
)
week_metric_summary = _timed(
    "build_week_metric_summary",
    lambda: build_week_metric_summary(
        stitched_test_predictions,
        selected_core_weeks,
        benchmark_candidate_key="official_naive_benchmark" if naive_prediction_available else None,
    ),
)
dm_vs_naive = _timed(
    "compute_dm_vs_naive",
    lambda: compute_diebold_mariano_table(
        candidate_predictions,
        benchmark_candidate_key="official_naive_benchmark",
        challenger_candidate_keys=[key for key in candidate_order if key != "official_naive_benchmark"],
    ) if naive_prediction_available else pd.DataFrame(),
)
dm_vs_fs2 = _timed(
    "compute_dm_vs_best_fs2",
    lambda: compute_diebold_mariano_table(
        candidate_predictions,
        benchmark_candidate_key="best_fs2_reference",
        challenger_candidate_keys=[
            key for key in candidate_order if key.startswith("lear_fs3") or key.startswith("xgboost_fs3")
        ],
    ) if "best_fs2_reference" in set(candidate_frame["candidate_key"].astype(str).tolist()) else pd.DataFrame(),
)
selection_inputs = build_recommendation_inputs(
    classical_metrics,
    horizon_metrics,
    daily_level_summary,
    daily_shape_summary,
    topk_summary,
    tail_metrics,
    candidate_runtime,
)
recommendation = recommend_candidate(selection_inputs, thresholds=DECISION_THRESHOLDS)
selection_summary = build_model_selection_summary(selection_inputs, recommendation)
timing_summary = pd.DataFrame(timing_rows).sort_values("seconds", ascending=False).reset_index(drop=True)
week_plot_candidate_keys = [
    candidate_key
    for candidate_key in candidate_order
    if naive_prediction_available or candidate_key != "official_naive_benchmark"
]

print(f"Frozen case-week selection artifact: {selected_weeks_run.name}")
print(f"Evaluation output folder: {report_output_dir}")
print(f"Prediction rows loaded: {candidate_predictions.shape[0]:,}")
print(f"Candidates in scope: {candidate_label_order}")
""".strip()
        ),
        markdown_cell("## Run discovery and availability"),
        code_cell(
            """
display(availability_table)
display(pd.DataFrame([official_naive_reference]))

if fs2_selection_table.empty:
    print(fs2_selection_rule)
else:
    print(fs2_selection_rule)
    display(
        fs2_selection_table[
            [
                "candidate_label",
                "model",
                "rmae_vs_official_naive",
                "mae",
                "rmse",
                "bias",
            ]
        ]
        .rename(
            columns={
                "candidate_label": "FS2 candidate",
                "model": "Internal model",
                "rmae_vs_official_naive": "Validation rMAE",
                "mae": "Validation MAE",
                "rmse": "Validation RMSE",
                "bias": "Validation bias",
            }
        )
        .reset_index(drop=True)
    )

display(
    candidate_frame[
        [
            "candidate_label",
            "candidate_context",
            "selected_run_id",
            "selected_model",
            "note",
        ]
    ]
    .rename(
        columns={
            "candidate_label": "Candidate label",
            "candidate_context": "Context",
            "selected_run_id": "Selected run",
            "selected_model": "Internal model",
            "note": "Selection note",
        }
    )
)
""".strip()
        ),
        markdown_cell("## Data alignment checks"),
        code_cell(
            """
display(smoke_checks)
display(coverage_table)
display(missingness_table)
display(duplicate_table)
display(local_day_length_table)
display(stitched_overlap_check)
""".strip()
        ),
        markdown_cell(
            """
## Classical accuracy comparison

`rMAE` versus the official naive benchmark is the main classical ranking metric. `MAE` remains visible because it is easy to interpret in `EUR/MWh`, while `RMSE`, `p90`, and `p95` absolute error keep spike sensitivity visible.
""".strip()
        ),
        code_cell(
            """
classical_display = (
    classical_metrics[
        [
            "candidate_label",
            "dataset_split",
            "mae",
            "rmse",
            "bias",
            "rmae",
            "smape_pct",
            "median_ae",
            "p90_ae",
            "p95_ae",
            "coverage_pct",
        ]
    ]
    .sort_values(["dataset_split", "rmae", "mae", "candidate_label"])
    .reset_index(drop=True)
)
display(classical_display)

for split_name in ("validation", "test"):
    part = classical_metrics[classical_metrics["dataset_split"] == split_name].copy()
    if part.empty:
        continue
    part = part.sort_values(["rmae", "mae", "candidate_label"]).reset_index(drop=True)
    fig, axes = plt.subplots(1, 2, figsize=(15, 4.8))
    colors = [candidate_style_map[key]["color"] for key in part["candidate_key"].astype(str)]
    labels = part["candidate_label"].astype(str).tolist()
    axes[0].bar(labels, part["rmae"], color=colors)
    axes[0].axhline(1.0, color="#7d8b99", linestyle="--", linewidth=1.2)
    axes[0].set_title(f"{split_name.capitalize()} rMAE vs official naive")
    axes[0].tick_params(axis="x", rotation=30)
    axes[0].set_ylabel("rMAE")
    axes[1].bar(labels, part["mae"], color=colors)
    axes[1].set_title(f"{split_name.capitalize()} MAE")
    axes[1].tick_params(axis="x", rotation=30)
    axes[1].set_ylabel("EUR/MWh")
    fig.tight_layout()
    plt.show()

display(Markdown("### Diebold-Mariano checks vs official naive"))
if dm_vs_naive.empty:
    print("No DM comparison against the official naive benchmark was available.")
else:
    display(
        dm_vs_naive[
            [
                "dataset_split",
                "reporting_view",
                "challenger_candidate_label",
                "n_obs",
                "dm_stat",
                "p_value",
            ]
        ]
        .rename(
            columns={
                "dataset_split": "Split",
                "reporting_view": "Reporting view",
                "challenger_candidate_label": "Challenger",
                "n_obs": "Observations",
                "dm_stat": "DM statistic",
                "p_value": "p-value",
            }
        )
        .sort_values(["Split", "Reporting view", "Challenger"])
        .reset_index(drop=True)
    )

display(Markdown("### Diebold-Mariano checks vs best FS2 reference"))
if dm_vs_fs2.empty:
    print("No DM comparison against the best FS2 reference was available.")
else:
    display(
        dm_vs_fs2[
            [
                "dataset_split",
                "reporting_view",
                "challenger_candidate_label",
                "n_obs",
                "dm_stat",
                "p_value",
            ]
        ]
        .rename(
            columns={
                "dataset_split": "Split",
                "reporting_view": "Reporting view",
                "challenger_candidate_label": "FS3 challenger",
                "n_obs": "Observations",
                "dm_stat": "DM statistic",
                "p_value": "p-value",
            }
        )
        .sort_values(["Split", "Reporting view", "FS3 challenger"])
        .reset_index(drop=True)
    )
""".strip()
        ),
        markdown_cell("## Horizon comparison"),
        code_cell(
            """
horizon_display = (
    horizon_metrics[
        [
            "candidate_label",
            "dataset_split",
            "lead_day_label",
            "mae",
            "rmse",
            "bias",
            "rmae",
            "median_ae",
            "p90_ae",
            "p95_ae",
            "coverage_pct",
        ]
    ]
    .sort_values(["dataset_split", "lead_day_label", "rmae", "candidate_label"])
    .reset_index(drop=True)
)
display(horizon_display)

for split_name in ("validation", "test"):
    split_frame = horizon_metrics[horizon_metrics["dataset_split"] == split_name].copy()
    if split_frame.empty:
        continue
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    for candidate_key in candidate_order:
        part = split_frame[split_frame["candidate_key"] == candidate_key].copy()
        if part.empty:
            continue
        style = candidate_style_map[candidate_key]
        part = part.sort_values("lead_day")
        ax.plot(
            part["lead_day"],
            part["rmae"],
            marker="o",
            linewidth=style["linewidth"],
            linestyle=style["linestyle"],
            color=style["color"],
            alpha=style["alpha"],
            label=style["label"],
        )
    ax.axhline(1.0, color="#7d8b99", linestyle="--", linewidth=1.2)
    ax.set_xticks(sorted(split_frame["lead_day"].astype(int).unique().tolist()))
    tick_frame = split_frame[["lead_day", "lead_day_label"]].drop_duplicates().sort_values("lead_day")
    ax.set_xticklabels(tick_frame["lead_day_label"].astype(str).tolist())
    ax.set_title(f"{split_name.capitalize()} horizon robustness")
    ax.set_ylabel("rMAE vs official naive")
    ax.legend(loc="best", ncol=2)
    fig.tight_layout()
    plt.show()
""".strip()
        ),
        markdown_cell("## Daily level retention"),
        code_cell(
            """
display(
    daily_level_summary[
        [
            "candidate_label",
            "dataset_split",
            "lead_day_label",
            "mean_daily_level_mae",
            "mean_daily_level_bias",
            "mean_abs_daily_level_bias",
            "mean_daily_volatility_error",
            "mean_abs_daily_volatility_error",
            "mean_daily_range_error",
            "mean_abs_daily_range_error",
            "valid_days",
        ]
    ]
    .sort_values(["dataset_split", "lead_day_label", "mean_daily_level_mae", "candidate_label"])
    .reset_index(drop=True)
)
""".strip()
        ),
        markdown_cell("## Intraday shape retention"),
        code_cell(
            """
display(
    daily_shape_summary[
        [
            "candidate_label",
            "dataset_split",
            "lead_day_label",
            "mean_pearson_corr",
            "mean_spearman_corr",
            "mean_demeaned_shape_mae",
            "mean_peak_hour_timing_error",
            "mean_trough_hour_timing_error",
            "valid_pearson_days",
            "valid_spearman_days",
            "flat_actual_days",
        ]
    ]
    .sort_values(["dataset_split", "lead_day_label", "mean_demeaned_shape_mae", "candidate_label"])
    .reset_index(drop=True)
)
""".strip()
        ),
        markdown_cell("## Expensive and cheap hour identification"),
        code_cell(
            """
display(
    topk_summary[
        [
            "candidate_label",
            "dataset_split",
            "lead_day_label",
            "mean_top3_expensive_recall",
            "mean_top3_cheap_recall",
            "valid_top3_expensive_days",
            "valid_top3_cheap_days",
        ]
    ]
    .sort_values(["dataset_split", "lead_day_label", "candidate_label"])
    .reset_index(drop=True)
)
""".strip()
        ),
        markdown_cell(
            """
## Tail and stress behaviour

High-volatility days are defined here as local delivery days in the top `10%` of actual daily range within the evaluated split, because no stricter repo-level daily rule existed to reuse.
""".strip()
        ),
        code_cell(
            """
display(
    tail_metrics[
        [
            "candidate_label",
            "dataset_split",
            "top10_mae",
            "top10_bias",
            "bottom10_mae",
            "bottom10_bias",
            "negative_mae",
            "negative_bias",
            "p90_ae",
            "p95_ae",
            "high_volatility_day_mae",
            "high_volatility_day_bias",
        ]
    ]
    .sort_values(["dataset_split", "top10_mae", "candidate_label"])
    .reset_index(drop=True)
)
""".strip()
        ),
        markdown_cell(
            """
## Distinctive objective week evaluation

The frozen `case_week_selection` artifact is reused directly. The main plots below use stitched `D-only` operational forecasts so that each target hour appears exactly once.
""".strip()
        ),
        code_cell(
            """
display(selected_core_weeks)

if not selected_appendix_weeks.empty:
    display(Markdown("### Secondary appendix-style week categories"))
    display(selected_appendix_weeks)
else:
    print("No additional appendix-style week categories were available in the frozen artifact.")
""".strip()
        ),
        code_cell(
            """
week_plot_paths = []
plot_output_dir = report_output_dir / "core_week_plots"
plot_output_dir.mkdir(parents=True, exist_ok=True)

for week_row in selected_core_weeks.to_dict(orient="records"):
    week_start = pd.Timestamp(week_row["week_start_local_date"]).date()
    week_end = pd.Timestamp(week_row["week_end_local_date"]).date()
    week_frame = stitched_test_predictions[
        (stitched_test_predictions["target_local_date"] >= week_start)
        & (stitched_test_predictions["target_local_date"] <= week_end)
        & (stitched_test_predictions["candidate_key"].isin(week_plot_candidate_keys))
    ].copy()
    if week_frame.empty:
        continue

    actual = (
        week_frame[["target_timestamp_utc", "target_timestamp_local", "y_true"]]
        .drop_duplicates(subset=["target_timestamp_utc"])
        .sort_values("target_timestamp_utc")
        .reset_index(drop=True)
    )

    fig, ax = plt.subplots(figsize=(15.5, 4.9))
    ax.plot(actual["target_timestamp_local"], actual["y_true"], color="#183247", linewidth=2.8, label="Actual")
    for candidate_key in week_plot_candidate_keys:
        candidate_part = week_frame[week_frame["candidate_key"] == candidate_key].copy()
        if candidate_part.empty:
            continue
        candidate_part = candidate_part.sort_values("target_timestamp_utc")
        style = candidate_style_map[candidate_key]
        ax.plot(
            candidate_part["target_timestamp_local"],
            candidate_part["y_pred"],
            color=style["color"],
            linestyle=style["linestyle"],
            linewidth=style["linewidth"],
            alpha=style["alpha"],
            label=style["label"],
        )
    ax.set_title(
        f"{week_row['category'].replace('_', ' ').title()} ({week_row['iso_week_id']}) stitched D-only forecasts"
    )
    ax.set_ylabel("EUR/MWh")
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\\n%H:%M"))
    ax.margins(x=0.01)
    ax.legend(loc="best", ncol=2)
    fig.autofmt_xdate()
    fig.tight_layout()
    output_path = plot_output_dir / f"{week_row['category']}_stitched_d_only.png"
    fig.savefig(output_path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    week_plot_paths.append(output_path)

for path in week_plot_paths:
    display(Image(filename=str(path)))

week_metric_display = (
    week_metric_summary.assign(
        week_type=lambda frame: frame["category"].astype(str).str.replace("_", " ").str.title(),
        shape_summary=lambda frame: frame.apply(
            lambda row: (
                "-"
                if pd.isna(row["mean_pearson_corr"])
                else f"ρ={float(row['mean_pearson_corr']):.2f}, ρs={float(row['mean_spearman_corr']):.2f}, de-meaned MAE={float(row['mean_demeaned_shape_mae']):.2f}"
            ),
            axis=1,
        ),
    )[
        [
            "week_type",
            "iso_week_id",
            "candidate_label",
            "mae",
            "rmae",
            "bias",
            "shape_summary",
            "mean_top3_expensive_recall",
            "mean_top3_cheap_recall",
        ]
    ]
    .rename(
        columns={
            "week_type": "Week type",
            "iso_week_id": "ISO week",
            "candidate_label": "Candidate label",
            "mae": "MAE",
            "rmae": "rMAE",
            "bias": "Bias",
            "shape_summary": "Shape summary",
            "mean_top3_expensive_recall": "Top-3 expensive recall",
            "mean_top3_cheap_recall": "Top-3 cheap recall",
        }
    )
    .sort_values(["Week type", "MAE", "Candidate label"])
    .reset_index(drop=True)
)
display(week_metric_display)
""".strip()
        ),
        markdown_cell(
            """
## Scenario and probabilistic placeholder

Scenario/probabilistic metrics are unavailable from the current deterministic benchmark artifacts. Later scenario generation should be evaluated separately for empirical coverage, interval width, and tail representation.
""".strip()
        ),
        markdown_cell("## Runtime and implementability summary"),
        code_cell(
            """
display(
    candidate_runtime[
        [
            "candidate_label",
            "dataset_split",
            "fit_time_mean_sec",
            "fit_time_median_sec",
            "fit_time_max_sec",
            "fit_time_warning_count",
            "predict_time_mean_sec",
            "predict_time_median_sec",
        ]
    ]
    .sort_values(["dataset_split", "fit_time_mean_sec", "candidate_label"])
    .reset_index(drop=True)
)

if candidate_settings.empty:
    print("No model_settings_summary rows were available.")
else:
    settings_display = (
        candidate_settings[
            [
                "candidate_label",
                "settings_source",
                "settings_json",
            ]
        ]
        .assign(
            settings_json=lambda frame: frame["settings_json"].astype(str).str.slice(0, 200)
            + frame["settings_json"].astype(str).map(lambda value: "..." if len(value) > 200 else "")
        )
        .rename(
            columns={
                "candidate_label": "Candidate label",
                "settings_source": "Settings source",
                "settings_json": "Settings preview",
            }
        )
    )
    display(settings_display)

display(
    selection_summary[
        [
            "candidate_label",
            "runtime_note",
            "implementability_note",
            "recommended_yes_no",
        ]
    ]
    .rename(
        columns={
            "candidate_label": "Candidate label",
            "runtime_note": "Runtime note",
            "implementability_note": "Implementability note",
            "recommended_yes_no": "Recommended",
        }
    )
)

display(timing_summary)
""".strip()
        ),
        markdown_cell("## Final recommendation table"),
        code_cell(
            """
selection_summary_display = selection_summary.rename(
    columns={
        "candidate_context": "Model context",
        "candidate_label": "Candidate label",
        "classical_metrics_summary": "Classical metrics summary",
        "horizon_robustness_summary": "Horizon robustness summary",
        "level_retention_summary": "Level retention summary",
        "shape_retention_summary": "Shape retention summary",
        "expensive_hour_recall_summary": "Expensive-hour recall",
        "cheap_hour_recall_summary": "Cheap-hour recall",
        "tail_stress_note": "Tail/stress note",
        "runtime_note": "Runtime / fit-time note",
        "implementability_note": "Implementability note",
        "recommended_yes_no": "Recommended",
        "thesis_use_limitations": "Thesis-use limitations",
        "notes": "Notes",
    }
)
display(selection_summary_display)
""".strip()
        ),
        markdown_cell("## Conclusion"),
        code_cell(
            """
recommended_key = recommendation.get("recommended_candidate_key")
recommended_label = recommendation.get("recommended_candidate_label")
recommended_row = selection_inputs[selection_inputs["candidate_key"] == recommended_key].copy()
recommended_row = recommended_row.iloc[0] if not recommended_row.empty else None
best_fs2_row = selection_inputs[selection_inputs["candidate_key"] == "best_fs2_reference"].copy()
best_fs2_row = best_fs2_row.iloc[0] if not best_fs2_row.empty else None
naive_row = selection_inputs[selection_inputs["candidate_key"] == "official_naive_benchmark"].copy()
naive_row = naive_row.iloc[0] if not naive_row.empty else None

if recommended_row is None:
    display(Markdown("No DA candidate could be recommended from the available benchmark-parent artifacts."))
else:
    delta_vs_fs2 = (
        float(best_fs2_row["rmae"] - recommended_row["rmae"])
        if best_fs2_row is not None and pd.notna(best_fs2_row["rmae"]) and pd.notna(recommended_row["rmae"])
        else float("nan")
    )
    delta_vs_naive = (
        float(naive_row["rmae"] - recommended_row["rmae"])
        if naive_row is not None and pd.notna(naive_row["rmae"]) and pd.notna(recommended_row["rmae"])
        else float("nan")
    )
    fs3_selected = str(recommended_key).startswith("lear_fs3") or str(recommended_key).startswith("xgboost_fs3")
    conclusion_lines = [
        "### Decision outcome",
        f"- At least one DA forecast candidate is {'sufficient' if recommendation.get('stop_da_here') else 'not yet sufficient'} for downstream thesis use under the current deterministic scope.",
        f"- Recommended DA candidate: `{recommended_label}`.",
        f"- Validation `rMAE` versus the official naive benchmark: `{float(recommended_row['rmae']):.3f}`.",
        f"- Test `rMAE` versus the official naive benchmark: `{float(recommended_row['test_rmae']):.3f}`." if pd.notna(recommended_row["test_rmae"]) else "- Test `rMAE` versus the official naive benchmark: unavailable.",
    ]
    if pd.notna(delta_vs_naive):
        conclusion_lines.append(f"- Improvement versus the official naive benchmark on validation: `{delta_vs_naive:.3f}` rMAE points.")
    if best_fs2_row is not None and pd.notna(delta_vs_fs2):
        comparison_text = "improves enough over" if fs3_selected and delta_vs_fs2 > 0 else "does not improve enough over"
        conclusion_lines.append(
            f"- Relative to the best/current FS2 reference, the selected candidate {comparison_text} FS2 by `{delta_vs_fs2:.3f}` validation rMAE points."
        )
    conclusion_lines.extend(
        [
            f"- Recommendation rationale: {recommendation.get('decision_reason')}",
            f"- DA forecasting work should {'stop here' if recommendation.get('stop_da_here') else 'continue'} before expanding the thesis scope.",
            f"- It is {'methodologically reasonable' if recommendation.get('move_to_mfrr') else 'not yet methodologically reasonable'} to move on to mFRR forecasting next.",
            "- Thesis limitations to document: deterministic-only outputs, residual tail risk, and any remaining daily level bias or week-specific failure modes shown above.",
        ]
    )
    display(Markdown("\\n".join(conclusion_lines)))
""".strip()
        ),
    ]

    notebooks["24_final_conclusion_and_best_model.ipynb"] = [
        markdown_cell(
            """
# 24 Final Conclusion And Best Model

This notebook is the short thesis wrap-up after notebook `23`.

Notebook `23_fs3_decision_relevant_forecast_evaluation.ipynb` is the detailed decision layer. This notebook only restates the final DA recommendation and the thesis next-step decision in a compact form.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(
            """
from hourly_da.core.forecast_evaluation import (
    build_model_selection_summary,
    build_recommendation_inputs,
    compute_classical_metrics,
    compute_daily_level_metrics,
    compute_horizon_metrics,
    default_decision_thresholds,
    discover_final_candidate_runs,
    load_candidate_predictions,
    load_candidate_runtime_summary,
    load_official_naive_denominators,
    recommend_candidate,
)
""".strip()
        ),
        code_cell(
            """
DECISION_THRESHOLDS = default_decision_thresholds()
comparison_discovery = discover_final_candidate_runs(output_root)
candidate_frame = comparison_discovery["candidates"].copy()
candidate_predictions = load_candidate_predictions(candidate_frame=candidate_frame, config=config)
candidate_runtime = load_candidate_runtime_summary(candidate_frame)
naive_denominators = load_official_naive_denominators(
    run_dir=comparison_discovery["rmae_reference_run_dir"],
    official_naive_model=str(comparison_discovery["official_naive_model"]),
)
classical_metrics = compute_classical_metrics(candidate_predictions, naive_denominators)
horizon_metrics = compute_horizon_metrics(candidate_predictions, naive_denominators)
_, daily_level_summary = compute_daily_level_metrics(candidate_predictions)
selection_inputs = build_recommendation_inputs(
    classical_metrics,
    horizon_metrics,
    daily_level_summary,
    pd.DataFrame(),
    pd.DataFrame(),
    pd.DataFrame(),
    candidate_runtime,
)
recommendation = recommend_candidate(selection_inputs, thresholds=DECISION_THRESHOLDS)
selection_summary = build_model_selection_summary(selection_inputs, recommendation)

display(selection_summary)
""".strip()
        ),
        code_cell(
            """
recommended_key = recommendation.get("recommended_candidate_key")
recommended_label = recommendation.get("recommended_candidate_label")
recommended_row = selection_inputs[selection_inputs["candidate_key"] == recommended_key].copy()
recommended_row = recommended_row.iloc[0] if not recommended_row.empty else None
best_fs2_row = selection_inputs[selection_inputs["candidate_key"] == "best_fs2_reference"].copy()
best_fs2_row = best_fs2_row.iloc[0] if not best_fs2_row.empty else None
naive_row = selection_inputs[selection_inputs["candidate_key"] == "official_naive_benchmark"].copy()
naive_row = naive_row.iloc[0] if not naive_row.empty else None

if recommended_row is None:
    display(Markdown("No final DA candidate could be recommended from the available artifacts."))
else:
    delta_vs_fs2 = (
        float(best_fs2_row["rmae"] - recommended_row["rmae"])
        if best_fs2_row is not None and pd.notna(best_fs2_row["rmae"]) and pd.notna(recommended_row["rmae"])
        else float("nan")
    )
    delta_vs_naive = (
        float(naive_row["rmae"] - recommended_row["rmae"])
        if naive_row is not None and pd.notna(naive_row["rmae"]) and pd.notna(recommended_row["rmae"])
        else float("nan")
    )
    conclusion_lines = [
        "### Final DA recommendation",
        f"- Recommended candidate: `{recommended_label}`.",
        f"- Validation `rMAE` vs official naive: `{float(recommended_row['rmae']):.3f}`.",
        f"- Test `rMAE` vs official naive: `{float(recommended_row['test_rmae']):.3f}`." if pd.notna(recommended_row["test_rmae"]) else "- Test `rMAE` vs official naive: unavailable.",
        f"- Validation improvement vs best/current FS2 reference: `{delta_vs_fs2:.3f}` rMAE points." if pd.notna(delta_vs_fs2) else "- Validation improvement vs best/current FS2 reference: unavailable.",
        f"- Validation improvement vs official naive benchmark: `{delta_vs_naive:.3f}` rMAE points." if pd.notna(delta_vs_naive) else "- Validation improvement vs official naive benchmark: unavailable.",
        f"- Decision reason: {recommendation.get('decision_reason')}",
        f"- DA forecasting should {'stop here' if recommendation.get('stop_da_here') else 'continue'} before further thesis expansion.",
        f"- Moving on to mFRR forecasting is {'reasonable' if recommendation.get('move_to_mfrr') else 'not yet reasonable'} under the current evidence.",
        "- Detailed robustness, level, shape, top-k, tail, and objective-week evidence lives in notebook `23_fs3_decision_relevant_forecast_evaluation.ipynb`.",
    ]
    display(Markdown("\\n".join(conclusion_lines)))
""".strip()
        ),
    ]
    notebooks["91_fs3_feature_family_plan_reference.ipynb"] = [
        markdown_cell(
            """
# 91 FS3 Feature Family Plan Reference

Reference-only notebook. The supported `FS3` execution path now lives in notebooks `12` through `16`.

This reference notebook documents the wider exogenous-family promotion roadmap beyond the currently supported active `FS3` context.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(stage_policy_cell("FS3")),
        code_cell(
            """
display(shortlisting_policy_frame())
display(tuning_cadence_frame().loc[lambda df: df["fs_level"] == "FS3"].reset_index(drop=True))
display(tuning_snippet_frame(fs_level="FS3"))
""".strip()
        ),
        code_cell(
            """
try:
    external_store = load_external_feature_store(config)
    external_catalog = build_external_family_catalog(config, external_store)
    display(
        external_catalog[
            [
                "family_name",
                "availability_class",
                "lead_scope",
                "allowed_usage_mode",
                "current_usage_mode",
                "current_issue_status",
            ]
        ].reset_index(drop=True)
    )
except FileNotFoundError as exc:
    print(f"External feature store is not fully available yet: {exc}")
""".strip()
        ),
        markdown_cell(
            """
Implementation reminder:
- this notebook is planning-oriented
- the active supported `FS3` path already exists in the main run order
- this notebook is for broader family-roadmap planning, not for launching the active benchmark path
- no new `FS3` backtests are launched here
""".strip()
        ),
    ]

    notebooks["92_fs4_huang_style_plan_reference.ipynb"] = [
        markdown_cell(
            """
# 92 FS4 Huang-Style Plan Reference

Reference-only notebook. `FS4` is scaffolded as a later finalist stage and is not part of the active consecutive execution pipeline yet.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(stage_policy_cell("FS4")),
        code_cell(
            """
display(tuning_cadence_frame().loc[lambda df: df["fs_level"] == "FS4"].reset_index(drop=True))
display(tuning_snippet_frame(fs_level="FS4"))
""".strip()
        ),
        markdown_cell(
            """
Execution boundary:
- advanced engineering and finalist-only retuning are left for later execution
""".strip()
        ),
    ]

    notebooks["93_execution_readiness_checklist_reference.ipynb"] = [
        markdown_cell(
            """
# 93 Execution Readiness Checklist Reference

Reference-only notebook. It is an optional structural repo check and is not required in the main notebook run order.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(
            """
paths_to_check = [
    PACKAGE_ROOT / "run_naive_benchmark.py",
    PACKAGE_ROOT / "run_lear_benchmark.py",
    PACKAGE_ROOT / "run_xgboost_benchmark.py",
    PACKAGE_ROOT / "run_prophet_benchmark.py",
    PACKAGE_ROOT / "run_model_comparison.py",
    PACKAGE_ROOT / "docs" / "feature_sets.md",
    PACKAGE_ROOT / "docs" / "tuning_policy.md",
    PACKAGE_ROOT / "hourly_da" / "core" / "methodology.py",
    PACKAGE_ROOT / "hourly_da" / "core" / "tuning.py",
    PACKAGE_ROOT / "hourly_da" / "models" / "registry.py",
    PACKAGE_ROOT / "hourly_da" / "models" / "prophet_model.py",
]

check_rows = []
for path in paths_to_check:
    check_rows.append({"path": str(path.relative_to(REPO_ROOT)), "exists": path.exists()})

display(pd.DataFrame(check_rows))
""".strip()
        ),
        code_cell(
            run_availability_cell(
                [
                    "case_week_selection",
                    "naive_benchmark",
                    "lear_fs1_benchmark",
                    "xgboost_fs1_benchmark",
                    "fs1_model_comparison",
                    "lear_fs2_benchmark",
                    "xgboost_fs2_benchmark",
                    "prophet_benchmark",
                    "model_comparison",
                ]
            )
        ),
        markdown_cell(
            """
If the files above exist, the methodology tables are centralized, and the run labels are recognized, the repo is structurally ready.
""".strip()
        ),
    ]

    notebooks["94_methodology_update_summary_reference.ipynb"] = [
        markdown_cell(
            """
# 94 Methodology Update Summary Reference

Reference-only notebook. It records the structural DAM-methodology update that standardized the active stack and retired legacy models from the non-archived notebook flow.
""".strip()
        ),
        code_cell(COMMON_SETUP),
        code_cell(
            """
summary_rows = [
    {"topic": "Active models", "decision": "naive_previous_week, naive_previous_year, LEAR, XGBoost, Prophet"},
    {"topic": "Prophet entry", "decision": "Prophet starts at FS2 once calendar and holiday structure is active"},
    {"topic": "Legacy removals", "decision": "ARIMA and SARIMA are removed from the active DAM stack and kept only as archived history"},
    {"topic": "FS ladder", "decision": "FS0 benchmarks, FS1 endogenous explicit, FS2 calendar/holiday plus Prophet, FS3 causal exogenous, FS4 advanced engineered finalists"},
    {"topic": "Shortlisting", "decision": "No shortlist after FS1; first fair shortlist after FS2"},
    {"topic": "Tuning cadence", "decision": "FS0 none, FS1 coarse, FS2 serious, FS3 mandatory retuning, FS4 selective finalist retuning"},
    {"topic": "Execution status", "decision": "Notebook flow standardized; heavy reruns remain opt-in per execution notebook"},
]

display(pd.DataFrame(summary_rows))
display(feature_stage_policy_frame())
display(tuning_cadence_frame())
""".strip()
        ),
    ]

    return notebooks


def write_notebooks() -> None:
    NOTEBOOK_ROOT.mkdir(parents=True, exist_ok=True)
    metadata = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    }
    notebooks = build_notebooks()
    current_filenames = set(notebooks.keys()) | PROTECTED_NOTEBOOK_FILENAMES

    archive_root = NOTEBOOK_ROOT / "archive_pre_fs_order_layout"
    obsolete_notebooks = [
        path for path in NOTEBOOK_ROOT.glob("*.ipynb") if path.name not in current_filenames
    ]
    if obsolete_notebooks:
        archive_root.mkdir(parents=True, exist_ok=True)
        for path in obsolete_notebooks:
            target = archive_root / path.name
            if target.exists():
                stem = path.stem
                suffix = path.suffix
                counter = 1
                while (archive_root / f"{stem}_{counter}{suffix}").exists():
                    counter += 1
                target = archive_root / f"{stem}_{counter}{suffix}"
            path.replace(target)

    for filename, cells in notebooks.items():
        normalized_cells: list[dict[str, object]] = []
        for index, cell in enumerate(cells):
            normalized = dict(cell)
            if "id" not in normalized:
                seed = f"{filename}:{index}:{normalized.get('cell_type', '')}:{''.join(normalized.get('source', []))}"
                normalized["id"] = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
            normalized_cells.append(normalized)
        payload = {
            "cells": normalized_cells,
            "metadata": metadata,
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        (NOTEBOOK_ROOT / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    write_notebooks()
