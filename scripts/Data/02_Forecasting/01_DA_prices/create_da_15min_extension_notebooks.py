from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


NOTEBOOK_ROOT = Path(__file__).resolve().parents[4] / "notebooks" / "Data" / "02_Forecasting" / "01_DA_prices" / "15min_extension"


def md(text: str) -> nbformat.NotebookNode:
    return new_markdown_cell(dedent(text).strip())


def code(text: str) -> nbformat.NotebookNode:
    return new_code_cell(dedent(text).strip())


def _common_setup_cell() -> str:
    return dedent(
        """
        from pathlib import Path
        import json
        import os
        import subprocess
        import sys

        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd
        from IPython.display import Markdown, display

        NOTEBOOK_CWD = Path.cwd()
        REPO_ROOT = next(
            path
            for path in [NOTEBOOK_CWD, *NOTEBOOK_CWD.parents]
            if (path / "scripts/Data/02_Forecasting/01_DA_prices").exists()
        )
        os.chdir(REPO_ROOT)

        PACKAGE_ROOT = REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices"
        if str(PACKAGE_ROOT) not in sys.path:
            sys.path.append(str(PACKAGE_ROOT))

        from quarterhour_da import (
            QuarterHourDAExtensionConfig,
            assert_thesis_grade_actual_source_authorized,
            build_thesis_grade_frozen_actual_metadata,
            find_frozen_actual_version,
            find_latest_canonical_actual_run,
            find_latest_observed_deterministic_run,
            find_latest_phase01_run,
            find_latest_phase02_run,
            find_latest_phase03_run,
            find_latest_phase04_run,
            find_latest_phase07_run,
            find_latest_phase07_upstream_refresh_run,
            load_frozen_actual_diagnostics,
            load_frozen_actual_manifest,
            load_frozen_actual_path,
            resolve_frozen_actual_registry_entry,
            run_observed_market_deterministic_forecast,
        )

        config = QuarterHourDAExtensionConfig()
        pd.set_option("display.max_columns", 200)
        pd.set_option("display.width", 220)
        plt.style.use("seaborn-v0_8-whitegrid")
        """
    ).strip()


def build_phase01_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 01 Foundation And Data Refresh

            This notebook is the first step of the downstream Dutch 15-minute DAM extension.

            Scope of the current notebook:

            - lock the repo-native implementation contracts for the new quarter-hour extension;
            - refresh the observed hourly and quarter-hour Dutch DAM inputs with the repository's own ingestion and cleaning scripts;
            - keep the shared cleaned hourly and quarterly outputs separate;
            - expose the dedicated quarterly continuation pipeline as a companion audit path instead of silently inventing a second framework.
            """
        ),
        code(_common_setup_cell()),
        md(
            """
            ## Optional Refresh Hook

            The notebook defaults to loading the latest saved Phase 0/1 refresh artifact. Set `RUN_REFRESH = True` only when you want to rerun the update workflow from inside the notebook.
            """
        ),
        code(
            """
            RUN_REFRESH = False

            if RUN_REFRESH:
                command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_15min_phase01_refresh.py"),
                ]
                completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
                print(completed.stdout)
                if completed.returncode != 0:
                    print(completed.stderr)
                    raise RuntimeError(f"Phase 0/1 refresh failed with exit code {completed.returncode}.")
            """
        ),
        code(
            """
            latest_run = find_latest_phase01_run(config)
            if latest_run is None:
                raise FileNotFoundError("No saved Phase 0/1 refresh artifact exists yet. Run the phase refresh script first.")

            foundation_contracts = pd.read_csv(latest_run / "foundation_contracts.csv")
            refresh_summary = pd.read_csv(latest_run / "data_refresh_summary.csv")
            command_status = pd.read_csv(latest_run / "command_status_summary.csv")
            run_summary = json.loads((latest_run / "run_summary.json").read_text(encoding="utf-8"))

            display(pd.DataFrame([{"latest_phase01_run": str(latest_run)}]))
            """
        ),
        md(
            """
            ## Repo-Native Foundation Contracts

            These rows make the implementation choices explicit before any 15-minute modelling starts.
            """
        ),
        code("display(foundation_contracts)"),
        md(
            """
            ## Data Refresh Summary

            This table compares the key hourly and quarter-hour cleaned datasets before and after the Phase 1 refresh.
            """
        ),
        code("display(refresh_summary)"),
        md(
            """
            ## Command Status

            Each refresh step keeps its own log file so failures stay visible and auditable.
            """
        ),
        code("display(command_status[[\"command_name\", \"status\", \"return_code\", \"log_path\"]])"),
    ]
    return new_notebook(cells=cells, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})


def build_phase02_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 02 Shape Target Diagnostics

            This notebook turns the refreshed observed Dutch quarter-hour DAM data into the canonical within-hour shape target used by later modelling stages.

            Current scope:

            - confirm that the shared cleaned quarterly source and the dedicated continuation source remain aligned;
            - identify complete four-quarter hour groups after cleaning;
            - construct the hourly mean and zero-mean within-hour delta target;
            - define the empirical train/validation/test split from the actually available observed range.
            """
        ),
        code(_common_setup_cell()),
        md(
            """
            ## Optional Phase 2 Runner

            The notebook loads the latest saved Phase 2 artifact by default. Set `RUN_PHASE02 = True` only when you want to rebuild the shape-target outputs from inside the notebook.
            """
        ),
        code(
            """
            RUN_PHASE02 = False

            if RUN_PHASE02:
                command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_15min_phase02_shape_targets.py"),
                ]
                completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
                print(completed.stdout)
                if completed.returncode != 0:
                    print(completed.stderr)
                    raise RuntimeError(f"Phase 2 shape-target build failed with exit code {completed.returncode}.")
            """
        ),
        code(
            """
            latest_run = find_latest_phase02_run(config)
            if latest_run is None:
                raise FileNotFoundError("No saved Phase 2 artifact exists yet. Run the phase 2 script first.")

            source_availability = pd.read_csv(latest_run / "source_availability_summary.csv")
            source_consistency = pd.read_csv(latest_run / "source_consistency_summary.csv")
            hour_group_summary = pd.read_csv(latest_run / "hour_group_summary.csv")
            split_summary = pd.read_csv(latest_run / "split_summary.csv")
            quarter_diag = pd.read_csv(latest_run / "quarter_diagnostics.csv")
            hour_quarter_diag = pd.read_csv(latest_run / "hour_quarter_diagnostics.csv")
            shape_target = pd.read_csv(latest_run / "shape_target_long.csv")
            run_summary = json.loads((latest_run / "run_summary.json").read_text(encoding="utf-8"))

            display(pd.DataFrame([{"latest_phase02_run": str(latest_run)}]))
            """
        ),
        md("## Source Availability"),
        code("display(source_availability)"),
        md("## Shared vs Companion Source Consistency"),
        code("display(source_consistency)"),
        md("## Complete Four-Quarter Hour Groups"),
        code(
            """
            complete_summary = (
                hour_group_summary.groupby("hour_group_quality", dropna=False)
                .agg(hour_groups=("hour_start_utc", "size"))
                .reset_index()
                .sort_values("hour_group_quality")
            )
            display(complete_summary)
            """
        ),
        md("## Empirical Split Summary"),
        code("display(split_summary)"),
        md("## Quarter-Level Delta Diagnostics"),
        code("display(quarter_diag)"),
        md(
            """
            ## Delta Distribution By Quarter

            The boxplot shows whether some quarter positions tend to sit above or below the within-hour mean.
            """
        ),
        code(
            """
            fig, ax = plt.subplots(figsize=(8, 4.5))
            shape_target.boxplot(column="delta_eur_per_mwh", by="quarter_index", ax=ax, grid=False)
            ax.set_title("Delta Distribution By Quarter")
            ax.set_xlabel("Quarter index")
            ax.set_ylabel("Delta (EUR/MWh)")
            fig.suptitle("")
            plt.show()
            """
        ),
        md(
            """
            ## Hour-Quarter Heatmap

            The heatmap reports the average within-hour deviation by local hour of day and quarter index.
            """
        ),
        code(
            """
            heatmap = hour_quarter_diag.pivot(index="local_hour_of_day", columns="quarter_index", values="mean_delta")
            fig, ax = plt.subplots(figsize=(7, 7))
            im = ax.imshow(heatmap.values, aspect="auto", cmap="coolwarm")
            ax.set_xticks(range(len(heatmap.columns)))
            ax.set_xticklabels([str(value) for value in heatmap.columns])
            ax.set_yticks(range(len(heatmap.index)))
            ax.set_yticklabels([str(value) for value in heatmap.index])
            ax.set_xlabel("Quarter index")
            ax.set_ylabel("Local hour of day")
            ax.set_title("Mean Delta By Hour And Quarter")
            fig.colorbar(im, ax=ax, label="Mean delta (EUR/MWh)")
            plt.show()
            """
        ),
        md("## Zero-Mean Check"),
        code(
            """
            zero_mean_check = (
                shape_target.groupby("hour_start_utc")["delta_eur_per_mwh"]
                .mean()
                .abs()
                .agg(["max", "mean"])
                .rename({"max": "max_abs_hourly_delta_mean", "mean": "mean_abs_hourly_delta_mean"})
                .to_frame()
                .T
            )
            display(zero_mean_check)
            """
        ),
    ]
    return new_notebook(cells=cells, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})


def build_phase03_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 03 Dynamic Hourly Anchor Selection

            This notebook discovers the hourly anchor candidates for the downstream 15-minute extension by reusing the existing hourly scenario-generation selection logic.

            Current scope:

            - discover the latest eligible hourly benchmark candidates from saved artifacts;
            - apply the existing hourly scenario-selection rules without hardcoding candidate names;
            - identify the deterministic winner and the hour-ranking winner, or accept a single model if the hourly logic returns one winner for both roles;
            - save the selected hourly anchor provenance for later quarter-hour forecasting phases.
            """
        ),
        code(_common_setup_cell()),
        md(
            """
            ## Optional Phase 3 Runner

            The notebook loads the latest saved Phase 3 artifact by default. Set `RUN_PHASE03 = True` only when you want to rerun dynamic hourly anchor discovery from inside the notebook.
            """
        ),
        code(
            """
            RUN_PHASE03 = False

            if RUN_PHASE03:
                command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_15min_phase03_anchor_selection.py"),
                ]
                completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
                print(completed.stdout)
                if completed.returncode != 0:
                    print(completed.stderr)
                    raise RuntimeError(f"Phase 3 anchor selection failed with exit code {completed.returncode}.")
            """
        ),
        code(
            """
            latest_run = find_latest_phase03_run(config)
            if latest_run is None:
                raise FileNotFoundError("No saved Phase 3 artifact exists yet. Run the phase 3 script first.")

            selection_contract = pd.read_csv(latest_run / "selection_contract.csv")
            candidate_availability = pd.read_csv(latest_run / "candidate_availability.csv")
            ignored_runs = pd.read_csv(latest_run / "ignored_runs.csv")
            evaluation_slice_summary = pd.read_csv(latest_run / "evaluation_slice_summary.csv")
            official_naive_selected = pd.read_csv(latest_run / "official_naive_selected.csv")
            official_naive_summary = pd.read_csv(latest_run / "official_naive_summary.csv")
            selection_summary = pd.read_csv(latest_run / "candidate_selection_summary.csv")
            selected_anchor_models = pd.read_csv(latest_run / "selected_anchor_models.csv")
            runtime_summary = pd.read_csv(latest_run / "selected_candidate_runtime_summary.csv")
            model_settings_summary = pd.read_csv(latest_run / "selected_candidate_model_settings_summary.csv")
            run_summary = json.loads((latest_run / "run_summary.json").read_text(encoding="utf-8"))

            display(pd.DataFrame([{"latest_phase03_run": str(latest_run)}]))
            """
        ),
        md("## Selection Contract"),
        code("display(selection_contract)"),
        md("## Evaluation Slice Used By The Hourly Selection Logic"),
        code("display(evaluation_slice_summary)"),
        md("## Official Naive Benchmark Used For rMAE"),
        code("display(official_naive_selected)"),
        md("## Selected Hourly Anchor Models"),
        code("display(selected_anchor_models)"),
        md(
            """
            ## Candidate Comparison Plot

            Lower `rMAE` is better for the deterministic role. Higher `ranking_score` is better for the hour-ranking role.
            """
        ),
        code(
            """
            plot_frame = selection_summary.copy()
            selected_keys = set(selected_anchor_models["candidate_key"].astype(str).tolist())

            fig, ax = plt.subplots(figsize=(8.5, 5.5))
            for _, row in plot_frame.iterrows():
                candidate_key = str(row["candidate_key"])
                is_selected = candidate_key in selected_keys
                ax.scatter(
                    row["rmae"],
                    row["ranking_score"],
                    s=90 if is_selected else 45,
                    alpha=0.95 if is_selected else 0.65,
                )
                if is_selected:
                    ax.annotate(str(row["candidate_label"]), (row["rmae"], row["ranking_score"]), xytext=(6, 4), textcoords="offset points")

            ax.set_xlabel("rMAE (lower is better)")
            ax.set_ylabel("Ranking score (higher is better)")
            ax.set_title("Hourly Candidate Selection View")
            plt.show()
            """
        ),
        md("## Full Candidate Selection Summary"),
        code("display(selection_summary.sort_values(['rmae', 'ranking_score'], ascending=[True, False]))"),
        md("## Candidate Availability"),
        code("display(candidate_availability)"),
        md("## Selected Candidate Runtime Summary"),
        code("display(runtime_summary)"),
        md("## Selected Candidate Model Settings Summary"),
        code("display(model_settings_summary)"),
        md("## Ignored Runs"),
        code("display(ignored_runs)"),
    ]
    return new_notebook(cells=cells, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})


def build_phase04_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 04 Empirical Shape Model Validation

            This notebook evaluates the 15-minute shape layer on observed Dutch quarter-hour DAM data.

            Current scope:

            - build and compare the mandatory flat-repeat baseline, a simple mean-shape baseline, LEAR, and XGBoost;
            - evaluate shape-only performance and reconstructed quarter-hour price performance under the diagnostic/oracle anchor;
            - check whether realistic hourly anchors are already available for proper end-to-end Track A validation;
            - keep the interpretation explicit: diagnostic/oracle results are useful for shape learning, but they are not yet full realistic forecast results.
            """
        ),
        code(_common_setup_cell()),
        md(
            """
            ## Optional Phase 4 Runner

            The notebook loads the latest saved Phase 4 artifact by default. Set `RUN_PHASE04 = True` only when you want to rerun the empirical validation from inside the notebook.
            """
        ),
        code(
            """
            RUN_PHASE04 = False

            if RUN_PHASE04:
                command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_15min_phase04_empirical_validation.py"),
                ]
                completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
                print(completed.stdout)
                if completed.returncode != 0:
                    print(completed.stderr)
                    raise RuntimeError(f"Phase 4 empirical validation failed with exit code {completed.returncode}.")
            """
        ),
        code(
            """
            latest_run = find_latest_phase04_run(config)
            if latest_run is None:
                raise FileNotFoundError("No saved Phase 4 artifact exists yet. Run the phase 4 script first.")

            checks = pd.read_csv(latest_run / "validation_checks.csv")
            realistic_anchor = pd.read_csv(latest_run / "realistic_anchor_availability.csv")
            model_config = pd.read_csv(latest_run / "model_configuration_summary.csv")
            tuning_results = pd.read_csv(latest_run / "tuning_results.csv")
            shape_metrics = pd.read_csv(latest_run / "shape_only_metrics.csv")
            price_metrics = pd.read_csv(latest_run / "reconstructed_price_metrics.csv")
            performance_by_condition = pd.read_csv(latest_run / "performance_by_condition.csv")
            mae_by_hour = pd.read_csv(latest_run / "mae_by_hour.csv")
            recommended_model = pd.read_csv(latest_run / "recommended_model_summary.csv")
            predictions = pd.read_csv(latest_run / "predictions_long.csv")
            example_days = pd.read_csv(latest_run / "example_days.csv")
            run_summary = json.loads((latest_run / "run_summary.json").read_text(encoding="utf-8"))

            display(pd.DataFrame([{"latest_phase04_run": str(latest_run)}]))
            """
        ),
        md("## Validation Checks"),
        code("display(checks)"),
        md("## Realistic Hourly Anchor Availability"),
        code("display(realistic_anchor)"),
        md("## Model Configuration Summary"),
        code("display(model_config)"),
        md("## Tuning Summary"),
        code("display(tuning_results)"),
        md("## Shape-Only Metrics"),
        code("display(shape_metrics)"),
        md("## Reconstructed Quarter-Hour Price Metrics"),
        code("display(price_metrics)"),
        md(
            """
            ## Main Comparison Plot

            Lower MAE is better. The diagnostic/oracle anchor means the hourly level is fixed to the observed hourly mean, so this comparison isolates the quarter-hour shape layer.
            """
        ),
        code(
            """
            plot_frame = price_metrics[price_metrics["dataset_split"].astype(str) == "test"].copy()
            fig, ax = plt.subplots(figsize=(8, 4.5))
            ax.bar(plot_frame["model"], plot_frame["mae"])
            ax.set_title("Test MAE Under Diagnostic/Oracle Anchor")
            ax.set_ylabel("MAE (EUR/MWh)")
            ax.set_xlabel("Model")
            plt.xticks(rotation=20)
            plt.tight_layout()
            plt.show()
            """
        ),
        md("## Error By Hour Of Day"),
        code(
            """
            fig, ax = plt.subplots(figsize=(9, 4.5))
            for model_name, group in mae_by_hour.groupby("model"):
                ax.plot(group["local_hour_of_day"], group["mae"], marker="o", label=model_name)
            ax.set_title("Test MAE By Hour Of Day")
            ax.set_xlabel("Local hour of day")
            ax.set_ylabel("MAE (EUR/MWh)")
            ax.legend()
            plt.tight_layout()
            plt.show()
            """
        ),
        md("## Performance By Condition"),
        code("display(performance_by_condition.head(60))"),
        md("## Recommended Model Summary"),
        code("display(recommended_model)"),
        md("## Example Days"),
        code("display(example_days)"),
        md(
            """
            ## Selected Day Forecast Comparison

            The plot below uses the first available example day from the saved artifact bundle.
            """
        ),
        code(
            """
            if not example_days.empty:
                selected_day = example_days.iloc[0]["hour_local_date"]
                day_slice = predictions[predictions["hour_local_date"].astype(str) == str(selected_day)].copy()
                fig, ax = plt.subplots(figsize=(10, 4.5))
                actual = day_slice.drop_duplicates(subset=["timestamp_utc"])[["timestamp_local", "price_eur_per_mwh"]].sort_values("timestamp_local")
                ax.plot(pd.to_datetime(actual["timestamp_local"]), actual["price_eur_per_mwh"], label="actual", linewidth=2.0)
                for model_name in ["flat_repeat", "lear_shape", "xgboost_shape"]:
                    model_slice = (
                        day_slice[day_slice["model"].astype(str) == model_name][["timestamp_local", "predicted_price_eur_per_mwh"]]
                        .sort_values("timestamp_local")
                    )
                    if not model_slice.empty:
                        ax.plot(pd.to_datetime(model_slice["timestamp_local"]), model_slice["predicted_price_eur_per_mwh"], label=model_name)
                ax.set_title(f"Quarter-Hour Prices On {selected_day}")
                ax.set_xlabel("Local timestamp")
                ax.set_ylabel("Price (EUR/MWh)")
                ax.legend()
                plt.tight_layout()
                plt.show()
            """
        ),
    ]
    return new_notebook(cells=cells, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})


def build_phase05_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 05 Legacy Counterfactual Full-Year Generation

            This notebook shows the older exploratory combined generation workflow for the official hourly test period.

            Current scope:

            - use actual hourly prices as anchors for counterfactual realized 15-minute paths;
            - use the selected hourly forecast candidates as anchors for counterfactual 15-minute forecast inputs;
            - fit the selected quarter-hour shape model on the observed post-implementation library;
            - generate flat, low-volatility, empirical/medium, high-volatility, and stress realized paths while preserving the hourly mean exactly.

            Methodology note:

            - these Phase 5 artifacts are legacy exploratory generation outputs;
            - the authoritative downstream thesis input is the separately frozen canonical actual path built by the dedicated frozen-actual pipeline.
            - thesis-grade bidding and optimisation runs must not use these realized-path outputs as actual market truth.
            """
        ),
        code(_common_setup_cell()),
        code("from quarterhour_da import find_latest_phase05_run"),
        md("## Optional Phase 5 Runner"),
        code(
            """
            RUN_PHASE05 = False

            if RUN_PHASE05:
                command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_15min_phase05_counterfactual_generation.py"),
                ]
                completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
                print(completed.stdout)
                if completed.returncode != 0:
                    print(completed.stderr)
                    raise RuntimeError(f"Phase 5 counterfactual generation failed with exit code {completed.returncode}.")
            """
        ),
        code(
            """
            latest_run = find_latest_phase05_run(config)
            if latest_run is None:
                raise FileNotFoundError("No saved Phase 5 artifact exists yet. Run the phase 5 script first.")

            generation_summary = pd.read_csv(latest_run / "counterfactual_generation_summary.csv")
            backoff_summary = pd.read_csv(latest_run / "counterfactual_backoff_summary.csv")
            coverage_summary = pd.read_csv(latest_run / "hourly_forecast_coverage_summary.csv")
            shape_model_summary = pd.read_csv(latest_run / "shape_model_for_counterfactual_summary.csv")
            validation_checks = pd.read_csv(latest_run / "validation_checks.csv")
            run_summary = json.loads((latest_run / "run_summary.json").read_text(encoding="utf-8"))

            display(pd.DataFrame([{"latest_phase05_run": str(latest_run)}]))
            """
        ),
        md("## Shape Model Used For Counterfactual Forecast Inputs"),
        code("display(shape_model_summary)"),
        md("## Counterfactual Generation Summary"),
        code("display(generation_summary)"),
        md("## Hourly Forecast Coverage Summary"),
        code("display(coverage_summary)"),
        md("## Sampler Backoff Summary"),
        code("display(backoff_summary)"),
        md("## Validation Checks"),
        code("display(validation_checks)"),
    ]
    return new_notebook(cells=cells, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})


def build_phase06_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 06 Legacy MILP-Ready Exports

            This notebook packages the older exploratory Phase 5 outputs into legacy export files.

            Current scope:

            - export hourly actuals;
            - export selected hourly forecast anchors;
            - export flat and shape-adjusted 15-minute counterfactual forecast inputs;
            - export counterfactual realized 15-minute paths for the required scenario variants;
            - attach manifest rows and sidecar metadata for later downstream use.

            Methodology note:

            - this export bundle belongs to the earlier exploratory combined path;
            - the frozen canonical actual path is the authoritative realized input for downstream thesis bidding work.
            - any legacy Phase 6 realized-path artifacts are exploratory only and must not be treated as authorized 15-minute market truth.
            """
        ),
        code(_common_setup_cell()),
        code("from quarterhour_da import find_latest_phase06_run"),
        md("## Optional Phase 6 Runner"),
        code(
            """
            RUN_PHASE06 = False

            if RUN_PHASE06:
                command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_15min_phase06_milp_exports.py"),
                ]
                completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
                print(completed.stdout)
                if completed.returncode != 0:
                    print(completed.stderr)
                    raise RuntimeError(f"Phase 6 export packaging failed with exit code {completed.returncode}.")
            """
        ),
        code(
            """
            latest_run = find_latest_phase06_run(config)
            if latest_run is None:
                raise FileNotFoundError("No saved Phase 6 artifact exists yet. Run the phase 6 script first.")

            export_manifest = pd.read_csv(latest_run / "export_manifest.csv")
            schema_checks = pd.read_csv(latest_run / "export_schema_checks.csv")
            run_summary = json.loads((latest_run / "run_summary.json").read_text(encoding="utf-8"))

            display(pd.DataFrame([{"latest_phase06_run": str(latest_run)}]))
            """
        ),
        md("## Export Manifest"),
        code("display(export_manifest)"),
        md("## Export Schema Checks"),
        code("display(schema_checks)"),
    ]
    return new_notebook(cells=cells, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})


def build_phase07_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 07 Realistic Track A End-To-End Validation

            This notebook is the realistic end-to-end Track A layer for the downstream Dutch 15-minute DAM extension.

            Current scope:

            - bridge the hourly anchor target series into the post-implementation quarter-hour regime;
            - check whether the selected hourly FS3 anchor models can actually be extended repo-natively into the observed Jan-Apr 2026 window;
            - if feasible, run the realistic hourly-anchor extension and re-evaluate the 15-minute shape layer end to end;
            - if not feasible, surface the blocking external-feature coverage gap explicitly instead of silently falling back to an oracle anchor.
            """
        ),
        code(_common_setup_cell()),
        md("## Optional Phase 7 Runner"),
        code(
            """
            RUN_PHASE07 = False

            if RUN_PHASE07:
                command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_15min_phase07_realistic_track_a.py"),
                ]
                completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
                print(completed.stdout)
                if completed.returncode != 0:
                    print(completed.stderr)
                    raise RuntimeError(f"Phase 7 realistic Track A run failed with exit code {completed.returncode}.")
            """
        ),
        code(
            """
            latest_run = find_latest_phase07_run(config)
            if latest_run is None:
                raise FileNotFoundError("No saved Phase 7 artifact exists yet. Run the phase 7 script first.")

            status_summary = pd.read_csv(latest_run / "status_summary.csv")
            bridge_summary = pd.read_csv(latest_run / "hourly_bridge_summary.csv")
            feasibility = pd.read_csv(latest_run / "hourly_anchor_feasibility.csv")
            external_coverage = pd.read_csv(latest_run / "external_feature_coverage.csv")
            checks = pd.read_csv(latest_run / "validation_checks.csv")

            hourly_metrics = pd.read_csv(latest_run / "hourly_anchor_metrics.csv") if (latest_run / "hourly_anchor_metrics.csv").exists() else pd.DataFrame()
            hourly_coverage = pd.read_csv(latest_run / "hourly_anchor_coverage_summary.csv") if (latest_run / "hourly_anchor_coverage_summary.csv").exists() else pd.DataFrame()
            price_metrics = pd.read_csv(latest_run / "reconstructed_price_metrics.csv") if (latest_run / "reconstructed_price_metrics.csv").exists() else pd.DataFrame()
            shape_metrics = pd.read_csv(latest_run / "shape_only_metrics.csv") if (latest_run / "shape_only_metrics.csv").exists() else pd.DataFrame()
            comparison = pd.read_csv(latest_run / "oracle_vs_realistic_comparison.csv") if (latest_run / "oracle_vs_realistic_comparison.csv").exists() else pd.DataFrame()
            recommendations = pd.read_csv(latest_run / "recommended_model_summary.csv") if (latest_run / "recommended_model_summary.csv").exists() else pd.DataFrame()
            run_summary = json.loads((latest_run / "run_summary.json").read_text(encoding="utf-8"))

            display(pd.DataFrame([{"latest_phase07_run": str(latest_run)}]))
            """
        ),
        md("## Phase 7 Status"),
        code("display(status_summary)"),
        md("## Hourly Bridge Summary"),
        code("display(bridge_summary)"),
        md("## Hourly Anchor Feasibility"),
        code("display(feasibility)"),
        md("## Blocking External Feature Coverage"),
        code(
            """
            blocking = external_coverage[external_coverage["covers_requested_test_end"].fillna(False) == False].copy()
            display(blocking.head(80))
            """
        ),
        md("## Validation Checks"),
        code("display(checks)"),
        md("## Hourly Anchor Metrics"),
        code("display(hourly_metrics)"),
        md("## Hourly Anchor Coverage"),
        code("display(hourly_coverage)"),
        md("## Realistic 15-Minute Price Metrics"),
        code("display(price_metrics)"),
        md("## Realistic Shape Metrics"),
        code("display(shape_metrics)"),
        md("## Oracle vs Realistic Comparison"),
        code("display(comparison)"),
        md("## Recommended Models"),
        code("display(recommendations)"),
    ]
    return new_notebook(cells=cells, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})


def build_phase08_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 08 Results And Plot Interpretation

            This notebook is the single downstream review notebook for the Dutch 15-minute DAM extension.

            Use it when you want one place that:

            - explains how the hourly anchor models, quarter-hour shape models, and counterfactual datasets were constructed;
            - shows the final empirical forecast results under both oracle and realistic anchors;
            - visualises representative observed 15-minute periods and counterfactual full-year periods;
            - reports the frozen canonical actual-path registry that later bidding work must use.

            The notebook is intentionally interpretation-heavy. It does not replace the phase notebooks. It condenses them into one reproducible readout.
            """
        ),
        code(_common_setup_cell()),
        md(
            """
            ## Optional Refresh Hooks

            By default this notebook only reads the latest saved artifacts. Set any flag to `True` if you want to rerun the corresponding downstream phase before loading the summary views.
            """
        ),
        code(
            """
            RUN_PHASE07 = False

            phase_scripts = [
                (RUN_PHASE07, "run_15min_phase07_realistic_track_a.py", "Phase 7"),
            ]

            for should_run, script_name, label in phase_scripts:
                if not should_run:
                    continue
                command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / script_name),
                ]
                completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
                print(completed.stdout)
                if completed.returncode != 0:
                    print(completed.stderr)
                    raise RuntimeError(f"{label} rerun failed with exit code {completed.returncode}.")
            """
        ),
        code(
            """
            VERSION_ID = "canonical_v1"

            latest_phase03 = find_latest_phase03_run(config)
            latest_phase04 = find_latest_phase04_run(config)
            latest_phase07 = find_latest_phase07_run(config)
            latest_upstream = find_latest_phase07_upstream_refresh_run(config)
            canonical_version_dir = find_frozen_actual_version(config, VERSION_ID)

            required_runs = {
                "phase03": latest_phase03,
                "phase04": latest_phase04,
                "phase07": latest_phase07,
                "canonical_actual": canonical_version_dir,
            }
            missing = [name for name, path in required_runs.items() if path is None]
            if missing:
                raise FileNotFoundError(f"Missing required saved artifacts for: {missing}")

            phase03_selected = pd.read_csv(latest_phase03 / "selected_anchor_models.csv")
            phase03_summary = pd.read_csv(latest_phase03 / "candidate_selection_summary.csv")

            phase04_price_metrics = pd.read_csv(latest_phase04 / "reconstructed_price_metrics.csv")
            phase04_shape_metrics = pd.read_csv(latest_phase04 / "shape_only_metrics.csv")
            phase04_model_config = pd.read_csv(latest_phase04 / "model_configuration_summary.csv")
            phase04_tuning = pd.read_csv(latest_phase04 / "tuning_results.csv")
            phase04_recommended = pd.read_csv(latest_phase04 / "recommended_model_summary.csv")

            phase07_status = pd.read_csv(latest_phase07 / "status_summary.csv")
            phase07_checks = pd.read_csv(latest_phase07 / "validation_checks.csv")
            phase07_hourly_metrics = pd.read_csv(latest_phase07 / "hourly_anchor_metrics.csv")
            phase07_hourly_coverage = pd.read_csv(latest_phase07 / "hourly_anchor_coverage_summary.csv")
            phase07_price_metrics = pd.read_csv(latest_phase07 / "reconstructed_price_metrics.csv")
            phase07_shape_metrics = pd.read_csv(latest_phase07 / "shape_only_metrics.csv")
            phase07_mae_by_hour = pd.read_csv(latest_phase07 / "mae_by_hour.csv")
            phase07_perf_by_condition = pd.read_csv(latest_phase07 / "performance_by_condition.csv")
            phase07_predictions = pd.read_csv(latest_phase07 / "predictions_long.csv")
            phase07_model_config = pd.read_csv(latest_phase07 / "model_configuration_summary.csv")
            phase07_tuning = pd.read_csv(latest_phase07 / "tuning_results.csv")
            phase07_comparison = pd.read_csv(latest_phase07 / "oracle_vs_realistic_comparison.csv")
            phase07_recommended = pd.read_csv(latest_phase07 / "recommended_model_summary.csv")

            upstream_freshness = pd.read_csv(latest_upstream / "freshness_summary.csv") if latest_upstream is not None else pd.DataFrame()
            canonical_entry = resolve_frozen_actual_registry_entry(config, version_id=VERSION_ID, verify_hash=True)
            canonical_manifest = load_frozen_actual_manifest(config, version_id=VERSION_ID, verify_hash=False)
            canonical_provenance = build_thesis_grade_frozen_actual_metadata(config, version_id=VERSION_ID, verify_hash=False)
            canonical_actual = load_frozen_actual_path(config, version_id=VERSION_ID, verify_hash=False)
            canonical_diagnostics = load_frozen_actual_diagnostics(config, version_id=VERSION_ID, verify_hash=False)

            run_paths = pd.DataFrame(
                [
                    {"phase": "03", "artifact_path": str(latest_phase03)},
                    {"phase": "04", "artifact_path": str(latest_phase04)},
                    {"phase": "07", "artifact_path": str(latest_phase07)},
                    {"phase": "canonical_actual", "artifact_path": str(canonical_version_dir)},
                    {"phase": "07_upstream_refresh", "artifact_path": str(latest_upstream) if latest_upstream is not None else ""},
                ]
            )
            display(run_paths)
            """
        ),
        md(
            """
            ## What Is Being Summarised Here

            The results come from three distinct layers. Keeping them separate matters:

            1. **Observed 15-minute empirical validation**
               The model is tested against real Dutch quarter-hour prices from the post-implementation period.

            2. **Realistic end-to-end forecasting**
               The hour-level anchor is no longer known. It must first be forecast by the selected hourly models, then refined by the quarter-hour shape model.

            3. **Counterfactual full-year construction**
               The official hourly test year predates the Dutch quarter-hour market. Any 15-minute series for that period is synthetic or counterfactual by design.
            """
        ),
        code(
            """
            phase_status_rows = [
                {"phase": "03", "purpose": "Dynamic hourly anchor selection", "status": "completed", "run_path": str(latest_phase03)},
                {"phase": "04", "purpose": "Observed quarter-hour oracle validation", "status": "completed", "run_path": str(latest_phase04)},
                {"phase": "canonical_actual", "purpose": "Frozen canonical actual-path registry", "status": "completed", "run_path": str(canonical_version_dir)},
                {"phase": "07", "purpose": "Realistic end-to-end Track A validation", "status": str(phase07_status.iloc[0].get("phase07_status", "completed")), "run_path": str(latest_phase07)},
            ]
            phase_status = pd.DataFrame(phase_status_rows)
            display(phase_status)

            dataset_regimes = pd.DataFrame(
                [
                    {
                        "regime": "Observed 15-minute empirical data",
                        "period": "2025-10-01 to 2026-04-30",
                        "used_for": "Shape-model training and empirical validation",
                        "can_be_called_actual": "yes",
                    },
                    {
                        "regime": "Realistic Track A end-to-end forecasts",
                        "period": "2026-01-01 to 2026-04-30 validation/test windows",
                        "used_for": "True observed quarter-hour forecast evaluation",
                        "can_be_called_actual": "forecast compared against actual",
                    },
                    {
                        "regime": "Frozen canonical 15-minute realized path",
                        "period": "2024-10-01 to 2025-09-30",
                        "used_for": "Full-year bidding comparisons in a synthetic quarter-hour market design",
                        "can_be_called_actual": "no",
                    },
                ]
            )
            display(dataset_regimes)
            """
        ),
        md(
            """
            ## Time Regimes At A Glance

            The plot below is the quickest way to explain why the notebook contains both empirical forecast results and counterfactual scenario results.
            """
        ),
        code(
            """
            timeline = pd.DataFrame(
                [
                    {"label": "Observed 15-min train", "start": "2025-10-01", "end": "2025-12-31", "band": "observed"},
                    {"label": "Observed 15-min validation", "start": "2026-01-01", "end": "2026-02-28", "band": "observed"},
                    {"label": "Observed 15-min test", "start": "2026-03-01", "end": "2026-04-30", "band": "observed"},
                    {"label": "Official hourly test period", "start": "2024-10-01", "end": "2025-09-30", "band": "counterfactual"},
                ]
            )
            timeline["start"] = pd.to_datetime(timeline["start"])
            timeline["end"] = pd.to_datetime(timeline["end"])
            colors = {"observed": "#1f77b4", "counterfactual": "#ff7f0e"}

            fig, ax = plt.subplots(figsize=(10.5, 3.8))
            for idx, row in timeline.iloc[::-1].reset_index(drop=True).iterrows():
                ax.barh(
                    y=row["label"],
                    width=(row["end"] - row["start"]).days + 1,
                    left=row["start"],
                    color=colors[row["band"]],
                    alpha=0.85,
                )
            ax.set_title("Observed Validation Window vs Counterfactual Official Test Year")
            ax.set_xlabel("Calendar date")
            plt.tight_layout()
            plt.show()
            """
        ),
        md(
            """
            ## How The Models Came About

            The downstream 15-minute work did not start from scratch. It inherits the hourly model-selection logic and then adds a separate quarter-hour shape layer.
            """
        ),
        code(
            """
            lineage = pd.DataFrame(
                [
                    {
                        "layer": "Hourly anchor discovery",
                        "artifact_source": "Phase 3",
                        "how_selected": "Existing hourly scenario-selection logic reused without hardcoding candidates",
                        "output": "Deterministic winner and hour-ranking winner",
                    },
                    {
                        "layer": "Oracle shape validation",
                        "artifact_source": "Phase 4",
                        "how_selected": "Flat, mean-shape, LEAR, and XGBoost compared under the observed hourly mean",
                        "output": "Pure shape-learning quality check",
                    },
                    {
                        "layer": "Realistic end-to-end validation",
                        "artifact_source": "Phase 7",
                        "how_selected": "Selected hourly anchors combined with the same shape model ladder",
                        "output": "True observed quarter-hour forecast performance",
                    },
                    {
                        "layer": "Counterfactual full-year generator",
                        "artifact_source": "Frozen canonical actual-path registry",
                        "how_selected": "Pre-specified empirical block-sampling protocol frozen as canonical_v1 before downstream bidding",
                        "output": "Authoritative thesis-grade synthetic 15-minute realized path",
                    },
                ]
            )
            display(lineage)
            display(phase03_selected)
            """
        ),
        md(
            """
            ## Training And Tuning Contract

            The next tables show the actual train/validation/test windows and the modest tuning choices used for the shape layer. The point here is transparency, not hyperparameter theatre.
            """
        ),
        code(
            """
            display(phase04_model_config)
            display(phase07_model_config)

            oracle_best_tuning = (
                phase04_tuning.sort_values(["model", "validation_price_mae"])
                .groupby("model", as_index=False)
                .head(1)
            )
            realistic_best_tuning = (
                phase07_tuning.sort_values(["candidate_key", "model", "validation_price_mae"])
                .groupby(["candidate_key", "model"], as_index=False)
                .head(1)
            )
            display(oracle_best_tuning)
            display(realistic_best_tuning)
            """
        ),
        md(
            """
            ## Main Result At A Glance

            This is the realistic result that matters most for downstream interpretation. It includes both the hourly anchor error and the quarter-hour shape error.
            """
        ),
        code(
            """
            realistic_test = phase07_price_metrics[phase07_price_metrics["dataset_split"].astype(str) == "test"].copy()
            realistic_test["anchor_model_pair"] = realistic_test["hourly_anchor_candidate_label"].astype(str) + " | " + realistic_test["model"].astype(str)
            realistic_test = realistic_test.sort_values(["mae", "hourly_anchor_candidate_label", "model"]).reset_index(drop=True)
            display(realistic_test[[
                "hourly_anchor_candidate_label",
                "hourly_anchor_role",
                "model",
                "mae",
                "rmse",
                "bias",
                "rmae_vs_flat_repeat",
                "cheapest_quarter_hit_rate",
                "most_expensive_quarter_hit_rate",
                "within_hour_rank_corr",
            ]])

            best_realistic = realistic_test.iloc[0:1].copy()
            display(best_realistic)
            """
        ),
        code(
            """
            fig, ax = plt.subplots(figsize=(10.5, 4.8))
            bar_colors = ["#2ca02c" if model == "xgboost_shape" else "#7f7f7f" for model in realistic_test["model"]]
            ax.bar(realistic_test["anchor_model_pair"], realistic_test["mae"], color=bar_colors)
            ax.set_title("Realistic End-To-End Test MAE By Hourly Anchor And Shape Model")
            ax.set_ylabel("MAE (EUR/MWh)")
            ax.set_xlabel("Hourly anchor | shape model")
            plt.xticks(rotation=30, ha="right")
            plt.tight_layout()
            plt.show()
            """
        ),
        md(
            """
            ## Why Oracle And Realistic Results Differ

            The oracle setup fixes the hourly level to the truth. The realistic setup does not. That is why the oracle MAE is much lower and should never be interpreted as the full forecasting error.
            """
        ),
        code(
            """
            comparison_plot = phase07_comparison[
                phase07_comparison["model"].isin(["flat_repeat", "mean_shape", "xgboost_shape"])
            ].copy()
            comparison_plot["label"] = comparison_plot["hourly_anchor_candidate_label"].astype(str) + "\\n" + comparison_plot["model"].astype(str)

            x = np.arange(len(comparison_plot))
            width = 0.38
            fig, ax = plt.subplots(figsize=(11.0, 4.8))
            ax.bar(x - width / 2, comparison_plot["oracle_test_mae"], width=width, label="oracle anchor")
            ax.bar(x + width / 2, comparison_plot["mae"], width=width, label="realistic anchor")
            ax.set_xticks(x)
            ax.set_xticklabels(comparison_plot["label"], rotation=25, ha="right")
            ax.set_ylabel("MAE (EUR/MWh)")
            ax.set_title("Oracle vs Realistic Test MAE")
            ax.legend()
            plt.tight_layout()
            plt.show()
            """
        ),
        md(
            """
            ## How Much Of The Final Error Comes From The Hourly Anchor

            This plot compares the hourly anchor MAE against the final best 15-minute MAE for each selected hourly candidate. It is a clean way to show that the shape layer helps, but the hourly level still dominates.
            """
        ),
        code(
            """
            hourly_test = phase07_hourly_metrics[phase07_hourly_metrics["dataset_split"].astype(str) == "test"].copy()
            best_shape_per_anchor = (
                realistic_test.sort_values("mae")
                .groupby(["hourly_anchor_candidate_key", "hourly_anchor_candidate_label"], as_index=False)
                .first()[["hourly_anchor_candidate_key", "hourly_anchor_candidate_label", "model", "mae"]]
                .rename(columns={"model": "best_shape_model", "mae": "best_15min_test_mae"})
            )
            anchor_vs_final = hourly_test.merge(
                best_shape_per_anchor,
                left_on=["candidate_key", "candidate_label"],
                right_on=["hourly_anchor_candidate_key", "hourly_anchor_candidate_label"],
                how="left",
            )
            display(anchor_vs_final[["candidate_label", "mae", "best_shape_model", "best_15min_test_mae"]].rename(columns={"mae": "hourly_anchor_test_mae"}))

            x = np.arange(len(anchor_vs_final))
            width = 0.35
            fig, ax = plt.subplots(figsize=(8.8, 4.8))
            ax.bar(x - width / 2, anchor_vs_final["mae"], width=width, label="hourly anchor MAE")
            ax.bar(x + width / 2, anchor_vs_final["best_15min_test_mae"], width=width, label="best final 15-min MAE")
            ax.set_xticks(x)
            ax.set_xticklabels(anchor_vs_final["candidate_label"], rotation=15, ha="right")
            ax.set_ylabel("MAE (EUR/MWh)")
            ax.set_title("Hourly Anchor Error vs Final 15-Minute Error")
            ax.legend()
            plt.tight_layout()
            plt.show()
            """
        ),
        code(
            """
            def _with_local_timestamps(frame: pd.DataFrame, column: str) -> pd.Series:
                return pd.to_datetime(frame[column], utc=True).dt.tz_convert(config.business_timezone)


            def _iso_week_id(ts: pd.Series) -> pd.Series:
                iso = ts.dt.isocalendar()
                return iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)


            def _weekly_summary_from_prices(frame: pd.DataFrame, *, timestamp_col: str, price_col: str) -> pd.DataFrame:
                data = frame.copy()
                data["_ts"] = _with_local_timestamps(data, timestamp_col)
                data["iso_week_id"] = _iso_week_id(data["_ts"])
                data["week_start"] = (data["_ts"] - pd.to_timedelta(data["_ts"].dt.weekday, unit="D")).dt.normalize()
                summary = (
                    data.groupby("iso_week_id", as_index=False)
                    .agg(
                        week_start=("week_start", "min"),
                        mean_price=(price_col, "mean"),
                        std_price=(price_col, "std"),
                        min_price=(price_col, "min"),
                        max_price=(price_col, "max"),
                        negative_share=(price_col, lambda s: float((s < 0).mean())),
                    )
                )
                summary["price_range"] = summary["max_price"] - summary["min_price"]
                return summary.sort_values("week_start").reset_index(drop=True)


            def _choose_representative_week(summary: pd.DataFrame) -> str:
                feature_cols = ["mean_price", "std_price", "price_range", "negative_share"]
                scaled = summary[feature_cols].copy()
                scaled = (scaled - scaled.mean()) / scaled.std(ddof=0).replace(0, 1.0)
                distances = np.sqrt((scaled**2).sum(axis=1))
                return str(summary.loc[distances.idxmin(), "iso_week_id"])


            def _choose_high_vol_week(summary: pd.DataFrame) -> str:
                return str(summary.sort_values(["std_price", "week_start"], ascending=[False, True]).iloc[0]["iso_week_id"])


            def _choose_low_price_week(summary: pd.DataFrame) -> str:
                ordered = summary.sort_values(["negative_share", "mean_price", "week_start"], ascending=[False, True, True])
                return str(ordered.iloc[0]["iso_week_id"])


            def _choose_seasonal_week(summary: pd.DataFrame, *, months: tuple[int, ...]) -> str:
                seasonal = summary[summary["week_start"].dt.month.isin(months)].copy()
                if seasonal.empty:
                    return _choose_representative_week(summary)
                return _choose_representative_week(seasonal)


            def _plot_observed_week(ax, week_data: pd.DataFrame, title: str) -> None:
                actual = week_data.drop_duplicates(subset=["timestamp_utc"])[["timestamp_local", "price_eur_per_mwh", "hourly_forecast_anchor_price_eur_per_mwh"]].sort_values("timestamp_local")
                actual_ts = _with_local_timestamps(actual, "timestamp_local")
                ax.plot(actual_ts, actual["price_eur_per_mwh"], label="actual 15-min", linewidth=2.0, color="black")
                ax.step(
                    actual_ts,
                    actual["hourly_forecast_anchor_price_eur_per_mwh"],
                    where="post",
                    label="hourly anchor",
                    linestyle="--",
                    color="#9467bd",
                )
                for model_name, color in [("flat_repeat", "#7f7f7f"), ("mean_shape", "#ff7f0e"), ("xgboost_shape", "#2ca02c")]:
                    model_slice = (
                        week_data[week_data["model"].astype(str) == model_name][["timestamp_local", "predicted_price_eur_per_mwh"]]
                        .sort_values("timestamp_local")
                    )
                    if not model_slice.empty:
                        ax.plot(_with_local_timestamps(model_slice, "timestamp_local"), model_slice["predicted_price_eur_per_mwh"], label=model_name, alpha=0.95, color=color)
                ax.set_title(title)
                ax.set_ylabel("EUR/MWh")


            def _plot_counterfactual_week(ax, week_data: pd.DataFrame, title: str) -> None:
                actual_hourly = (
                    week_data.drop_duplicates(subset=["hour_start_utc"])[["hour_start_local", "hourly_anchor_price_eur_per_mwh"]]
                    .sort_values("hour_start_local")
                )
                ax.step(
                    _with_local_timestamps(actual_hourly, "hour_start_local"),
                    actual_hourly["hourly_anchor_price_eur_per_mwh"],
                    where="post",
                    label="actual hourly anchor",
                    color="black",
                    linewidth=2.0,
                )
                color_lookup = {
                    "flat": "#7f7f7f",
                    "empirical_medium": "#1f77b4",
                    "high_volatility": "#ff7f0e",
                    "stress": "#d62728",
                    "canonical_v1": "#1f77b4",
                }
                variants = [str(value) for value in week_data["scenario_variant"].dropna().astype(str).drop_duplicates().tolist()]
                for idx, scenario_variant in enumerate(variants):
                    color = color_lookup.get(scenario_variant, plt.cm.tab10(idx % 10))
                    scenario_slice = (
                        week_data[week_data["scenario_variant"].astype(str) == scenario_variant][["timestamp_local", "predicted_price_eur_per_mwh"]]
                        .sort_values("timestamp_local")
                    )
                    if not scenario_slice.empty:
                        ax.plot(_with_local_timestamps(scenario_slice, "timestamp_local"), scenario_slice["predicted_price_eur_per_mwh"], label=scenario_variant, color=color, alpha=0.9)
                ax.set_title(title)
                ax.set_ylabel("EUR/MWh")
            """
        ),
        md(
            """
            ## Observed 15-Minute Case Weeks

            The next plots stay inside the observed test window. That keeps them aligned with the realistic results above.
            """
        ),
        code(
            """
            best_anchor_label = str(best_realistic.iloc[0]["hourly_anchor_candidate_label"])
            best_model_name = str(best_realistic.iloc[0]["model"])
            observed_best = phase07_predictions[
                (phase07_predictions["dataset_split"].astype(str) == "test")
                & (phase07_predictions["anchor_mode"].astype(str) == "realistic_forecast")
                & (phase07_predictions["hourly_anchor_candidate_label"].astype(str) == best_anchor_label)
            ].copy()
            observed_best["timestamp_local_dt"] = _with_local_timestamps(observed_best, "timestamp_local")
            observed_best["iso_week_id"] = _iso_week_id(observed_best["timestamp_local_dt"])

            observed_actual = observed_best.drop_duplicates(subset=["timestamp_utc"])[["timestamp_local", "price_eur_per_mwh"]].copy()
            observed_summary = _weekly_summary_from_prices(observed_actual, timestamp_col="timestamp_local", price_col="price_eur_per_mwh")
            observed_case_weeks = pd.DataFrame(
                [
                    {"case_type": "representative_observed_test_week", "iso_week_id": _choose_representative_week(observed_summary)},
                    {"case_type": "high_volatility_observed_test_week", "iso_week_id": _choose_high_vol_week(observed_summary)},
                    {"case_type": "low_price_observed_test_week", "iso_week_id": _choose_low_price_week(observed_summary)},
                ]
            )
            display(observed_summary)
            display(observed_case_weeks)
            """
        ),
        code(
            """
            fig, axes = plt.subplots(nrows=3, ncols=1, figsize=(12.0, 10.5), sharex=False)
            for ax, (_, row) in zip(axes, observed_case_weeks.iterrows()):
                week_id = str(row["iso_week_id"])
                week_slice = observed_best[observed_best["iso_week_id"].astype(str) == week_id].copy()
                _plot_observed_week(ax, week_slice, f"{row['case_type']} ({week_id})")
            handles, labels = axes[0].get_legend_handles_labels()
            axes[0].legend(handles, labels, ncol=5, loc="upper right")
            axes[-1].set_xlabel("Local timestamp")
            plt.tight_layout()
            plt.show()
            """
        ),
        md(
            """
            ## Selected Day Decomposition

            This day-level view shows what the shape layer adds on top of the hourly anchor. The upper panel shows prices. The lower panel shows the predicted and actual within-hour deviations.
            """
        ),
        code(
            """
            xgb_test = observed_best[observed_best["model"].astype(str) == best_model_name].copy()
            daily_spread = (
                xgb_test.groupby("hour_local_date", as_index=False)
                .agg(
                    actual_day_min=("price_eur_per_mwh", "min"),
                    actual_day_max=("price_eur_per_mwh", "max"),
                )
            )
            daily_spread["actual_day_spread"] = daily_spread["actual_day_max"] - daily_spread["actual_day_min"]
            selected_day = str(daily_spread.sort_values(["actual_day_spread", "hour_local_date"], ascending=[False, True]).iloc[0]["hour_local_date"])
            day_slice = observed_best[observed_best["hour_local_date"].astype(str) == selected_day].copy()
            actual_day = day_slice.drop_duplicates(subset=["timestamp_utc"])[["timestamp_local", "price_eur_per_mwh", "hourly_forecast_anchor_price_eur_per_mwh", "delta_eur_per_mwh"]].sort_values("timestamp_local")
            model_day = day_slice[day_slice["model"].astype(str) == best_model_name][["timestamp_local", "predicted_price_eur_per_mwh", "delta_pred_adjusted"]].sort_values("timestamp_local")
            actual_day_ts = _with_local_timestamps(actual_day, "timestamp_local")
            model_day_ts = _with_local_timestamps(model_day, "timestamp_local")

            fig, axes = plt.subplots(nrows=2, ncols=1, figsize=(11.5, 7.0), sharex=True, gridspec_kw={"height_ratios": [2.0, 1.0]})
            axes[0].plot(actual_day_ts, actual_day["price_eur_per_mwh"], label="actual 15-min", color="black", linewidth=2.0)
            axes[0].step(actual_day_ts, actual_day["hourly_forecast_anchor_price_eur_per_mwh"], where="post", label="hourly anchor", linestyle="--", color="#9467bd")
            axes[0].plot(model_day_ts, model_day["predicted_price_eur_per_mwh"], label=f"{best_model_name}", color="#2ca02c")
            axes[0].set_title(f"Observed Day Decomposition: {selected_day}")
            axes[0].set_ylabel("Price (EUR/MWh)")
            axes[0].legend()

            axes[1].plot(actual_day_ts, actual_day["delta_eur_per_mwh"], label="actual delta", color="black", linewidth=1.8)
            axes[1].plot(model_day_ts, model_day["delta_pred_adjusted"], label="predicted delta", color="#2ca02c")
            axes[1].axhline(0.0, color="grey", linewidth=1.0)
            axes[1].set_ylabel("Delta (EUR/MWh)")
            axes[1].set_xlabel("Local timestamp")
            axes[1].legend()
            plt.tight_layout()
            plt.show()
            """
        ),
        md(
            """
            ## Decision-Relevant Quarter-Hour Interpretation

            The next pair of plots focuses on what the MILP actually cares about: when the model gets the cheapest quarter right, and at which hours of day the error remains stubborn.
            """
        ),
        code(
            """
            best_rows = observed_best[observed_best["model"].astype(str) == best_model_name].copy()
            rank_group = (
                best_rows.groupby("hour_start_utc", as_index=False)
                .agg(
                    actual_cheapest_quarter=("price_eur_per_mwh", lambda s: int(np.argmin(s.to_numpy()) + 1)),
                    predicted_cheapest_quarter=("predicted_price_eur_per_mwh", lambda s: int(np.argmin(s.to_numpy()) + 1)),
                )
            )
            cheapest_confusion = pd.crosstab(
                rank_group["actual_cheapest_quarter"],
                rank_group["predicted_cheapest_quarter"],
                normalize="index",
            ).reindex(index=[1, 2, 3, 4], columns=[1, 2, 3, 4], fill_value=0.0)

            mae_hour_plot = phase07_mae_by_hour[
                (phase07_mae_by_hour["hourly_anchor_candidate_label"].astype(str) == best_anchor_label)
                & (phase07_mae_by_hour["model"].astype(str).isin(["flat_repeat", "mean_shape", best_model_name]))
            ].copy()

            fig, axes = plt.subplots(nrows=1, ncols=2, figsize=(12.0, 4.4))
            im = axes[0].imshow(cheapest_confusion.values, cmap="Blues", vmin=0.0, vmax=1.0)
            axes[0].set_xticks(range(4))
            axes[0].set_xticklabels([1, 2, 3, 4])
            axes[0].set_yticks(range(4))
            axes[0].set_yticklabels([1, 2, 3, 4])
            axes[0].set_xlabel("Predicted cheapest quarter")
            axes[0].set_ylabel("Actual cheapest quarter")
            axes[0].set_title("Cheapest-Quarter Hit Matrix")
            fig.colorbar(im, ax=axes[0], fraction=0.046, pad=0.04)

            for model_name, group in mae_hour_plot.groupby("model"):
                axes[1].plot(group["local_hour_of_day"], group["mae"], marker="o", label=model_name)
            axes[1].set_title("Test MAE By Hour Of Day")
            axes[1].set_xlabel("Local hour")
            axes[1].set_ylabel("MAE (EUR/MWh)")
            axes[1].legend()
            plt.tight_layout()
            plt.show()
            """
        ),
        md(
            """
            ## Counterfactual Official-Year Views

            These plots are not forecast-validation plots. They are interpretation plots for the synthetic 15-minute market-design dataset built on the official hourly test year.
            """
        ),
        code(
            """
            official_hourly = canonical_actual[["hour_start_local", "observed_hourly_anchor_price_eur_per_mwh"]].drop_duplicates(subset=["hour_start_local"]).copy()
            official_hourly = official_hourly.rename(
                columns={
                    "hour_start_local": "timestamp_local",
                    "observed_hourly_anchor_price_eur_per_mwh": "price_eur_per_mwh",
                }
            )
            official_hourly["timestamp_local_dt"] = _with_local_timestamps(official_hourly, "timestamp_local")
            official_weekly = _weekly_summary_from_prices(official_hourly, timestamp_col="timestamp_local", price_col="price_eur_per_mwh")
            official_case_weeks = pd.DataFrame(
                [
                    {"case_type": "typical_winter_official_year", "iso_week_id": _choose_seasonal_week(official_weekly, months=(12, 1, 2))},
                    {"case_type": "typical_summer_official_year", "iso_week_id": _choose_seasonal_week(official_weekly, months=(6, 7, 8))},
                    {"case_type": "high_volatility_official_year", "iso_week_id": _choose_high_vol_week(official_weekly)},
                ]
            )
            display(official_weekly)
            display(official_case_weeks)

            counterfactual_plot = canonical_actual.copy()
            counterfactual_plot["hourly_anchor_price_eur_per_mwh"] = pd.to_numeric(counterfactual_plot["observed_hourly_anchor_price_eur_per_mwh"], errors="coerce")
            counterfactual_plot["predicted_price_eur_per_mwh"] = pd.to_numeric(counterfactual_plot["counterfactual_actual_price_eur_per_mwh"], errors="coerce")
            counterfactual_plot["scenario_variant"] = VERSION_ID
            counterfactual_plot["timestamp_local_dt"] = _with_local_timestamps(counterfactual_plot, "timestamp_local")
            counterfactual_plot["iso_week_id"] = _iso_week_id(counterfactual_plot["timestamp_local_dt"])
            """
        ),
        code(
            """
            fig, axes = plt.subplots(nrows=3, ncols=1, figsize=(12.0, 10.5), sharex=False)
            for ax, (_, row) in zip(axes, official_case_weeks.iterrows()):
                week_id = str(row["iso_week_id"])
                week_slice = counterfactual_plot[counterfactual_plot["iso_week_id"].astype(str) == week_id].copy()
                _plot_counterfactual_week(ax, week_slice, f"{row['case_type']} ({week_id})")
            handles, labels = axes[0].get_legend_handles_labels()
            axes[0].legend(handles, labels, ncol=5, loc="upper right")
            axes[-1].set_xlabel("Local timestamp")
            plt.tight_layout()
            plt.show()
            """
        ),
        md(
            """
            ## Frozen Canonical Actual-Path Registry

            The tables below show the authoritative canonical actual-path metadata that later bidding work must report.
            """
        ),
        code(
            """
            display(pd.DataFrame([canonical_provenance]))
            manifest_rows = []
            for key, value in canonical_manifest.items():
                manifest_rows.append(
                    {
                        "field": key,
                        "value": json.dumps(value, default=str) if isinstance(value, (dict, list)) else value,
                    }
                )
            display(pd.DataFrame(manifest_rows))
            display(canonical_diagnostics)
            """
        ),
        md(
            """
            ## Legacy Exploratory Path Status

            Legacy Phase 5/6 outputs remain useful for exploratory diagnostics, but they are not authorised actual market truth for thesis-grade downstream runs.
            """
        ),
        code(
            """
            legacy_status = pd.DataFrame(
                [
                    {
                        "legacy_component": "Phase 5 counterfactual generation",
                        "status": "exploratory_only",
                        "authorised_as_15min_actual_market_truth": False,
                    },
                    {
                        "legacy_component": "Phase 6 mixed export bundle",
                        "status": "exploratory_only",
                        "authorised_as_15min_actual_market_truth": False,
                    },
                    {
                        "legacy_component": "Frozen canonical actual-path registry",
                        "status": "authoritative_thesis_grade",
                        "authorised_as_15min_actual_market_truth": True,
                    },
                ]
            )
            display(legacy_status)
            """
        ),
        md(
            """
            ## Final Interpretation

            The main conclusions supported by the current results are:

            - The downstream 15-minute extension now works end to end.
            - The best learned quarter-hour shape layer is XGBoost.
            - Mean-shape is a serious simple benchmark and should remain visible in the thesis.
            - LEAR adds little as a quarter-hour shape learner in this setup.
            - The realistic end-to-end error is dominated by the hourly anchor, not by the shape layer.
            - The frozen canonical actual-path registry now provides the single authorised 15-minute realised market environment for thesis-grade downstream bidding work.

            Claims that remain out of scope:

            - claiming actual full-year 15-minute forecast accuracy for the official hourly test year;
            - treating pre-October-2025 quarter-hour prices as historical truth;
            - treating the short observed post-implementation period as proof of full-year seasonal quarter-hour behaviour.
            """
        ),
    ]
    return new_notebook(cells=cells, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})


def build_phase09_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 09 Frozen Canonical Actual Path

            This notebook formalises the academic firewall for the synthetic 15-minute realized market path used in downstream bidding work.

            Current scope:

            - build and freeze one canonical synthetic 15-minute actual path;
            - keep that path separate from forecast and optimisation artifacts;
            - audit timestamp completeness, hourly reconciliation, randomness governance, and input independence;
            - expose the manifest, diagnostics, and checksum that later notebooks must report.
            """
        ),
        code(_common_setup_cell()),
        md(
            """
            ## Why This Path Exists

            A full historical 15-minute DA year is not available for the official hourly test period. The repository therefore uses a single frozen counterfactual 15-minute market environment for downstream bidding experiments.

            This is not a historical validation object. It is a pre-specified, reproducible, and versioned realized-path assumption.
            """
        ),
        md("## Optional Frozen-Actual Runner"),
        code(
            """
            RUN_FROZEN_ACTUAL = False

            if RUN_FROZEN_ACTUAL:
                command = [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "Data" / "02_Forecasting" / "01_DA_prices" / "run_15min_frozen_actual_path.py"),
                ]
                completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
                print(completed.stdout)
                if completed.returncode != 0:
                    print(completed.stderr)
                    raise RuntimeError(f"Frozen canonical actual-path build failed with exit code {completed.returncode}.")
            """
        ),
        code(
            """
            VERSION_ID = "canonical_v1"

            version_dir = find_frozen_actual_version(config, VERSION_ID)
            if version_dir is None:
                raise FileNotFoundError(f"No frozen canonical actual version '{VERSION_ID}' exists yet. Run the frozen-actual script first.")

            registry_entry = resolve_frozen_actual_registry_entry(config, version_id=VERSION_ID, verify_hash=True)
            manifest = load_frozen_actual_manifest(config, version_id=VERSION_ID, verify_hash=False)
            diagnostics = load_frozen_actual_diagnostics(config, version_id=VERSION_ID, verify_hash=False)
            canonical_actual = load_frozen_actual_path(config, version_id=VERSION_ID, verify_hash=False)
            provenance = build_thesis_grade_frozen_actual_metadata(config, version_id=VERSION_ID, verify_hash=False)

            display(
                pd.DataFrame(
                    [
                        {
                            "version_id": VERSION_ID,
                            "version_dir": str(version_dir),
                            "manifest_path": str(registry_entry.manifest_path),
                            "csv_sha256": registry_entry.authoritative_sha256,
                        }
                    ]
                )
            )
            """
        ),
        md("## Thesis-Grade Provenance Payload"),
        code("display(pd.DataFrame([provenance]))"),
        md("## Manifest"),
        code(
            """
            manifest_rows = []
            for key, value in manifest.items():
                if isinstance(value, (dict, list)):
                    manifest_rows.append({"field": key, "value": json.dumps(value, default=str)})
                else:
                    manifest_rows.append({"field": key, "value": value})
            display(pd.DataFrame(manifest_rows))
            """
        ),
        md("## Audit Diagnostics"),
        code("display(diagnostics)"),
        md("## Canonical Path Preview"),
        code("display(canonical_actual.head(12))"),
        md(
            """
            ## Interpretation Contract

            What the implemented checks prove:

            - the canonical path is complete in UTC quarter-hour timestamps;
            - the synthetic quarter-hour path reconciles back to the observed hourly DA anchor;
            - the canonical path records a fixed seed, explicit version id, and checksum;
            - the canonical path is documented as independent from forecast outputs, optimisation outputs, and economic selection.

            What the checks do not prove:

            - that the synthetic path is the true realized 15-minute historical market for the official hourly test year;
            - that one canonical path fully spans all plausible market environments.
            """
        ),
        md(
            """
            ## Required Downstream Usage

            - Forecast/scenario notebooks write separate ex-ante artifacts.
            - Bidding notebooks load this frozen canonical actual path as read-only input.
            - Evaluation notebooks report the version id and manifest hash used.
            """
        ),
    ]
    return new_notebook(cells=cells, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})


def build_phase10_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 10 Observed-Market Deterministic Forecast

            This notebook is the canonical observed-market quarter-hour forecast interpretation layer.

            Current scope:

            - run or load the audited quarter-hour deterministic `D..D+4` forecast artifact;
            - inspect the observed-target-only split policy and coverage;
            - compare the repeated-hourly structural benchmark with the mixed-frequency quarter-hour models;
            - confirm that non-observed targets are excluded from scored truth and downstream scenario-generation metadata.
            """
        ),
        code(_common_setup_cell()),
        md(
            """
            ## Optional Canonical Runner

            The notebook loads the latest saved observed-market deterministic artifact by default. Set `RUN_OBSERVED_DETERMINISTIC = True` only when you want to rerun the full quarter-hour deterministic forecast from inside the notebook.
            """
        ),
        code(
            """
            RUN_OBSERVED_DETERMINISTIC = False

            if RUN_OBSERVED_DETERMINISTIC:
                run_dir = run_observed_market_deterministic_forecast()
            else:
                run_dir = find_latest_observed_deterministic_run(config)

            if run_dir is None:
                raise FileNotFoundError("No observed-market deterministic quarter-hour run exists yet. Run the canonical runner first.")

            run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
            split_summary = pd.read_csv(run_dir / "split_summary.csv")
            coverage_summary = pd.read_csv(run_dir / "observed_target_coverage_summary.csv")
            metrics_overall = pd.read_csv(run_dir / "metrics_overall.csv")
            metrics_by_lead_day = pd.read_csv(run_dir / "metrics_by_lead_day.csv")
            dm_results = pd.read_csv(run_dir / "dm_test_results.csv") if (run_dir / "dm_test_results.csv").exists() else pd.DataFrame()
            predictions = pd.read_csv(run_dir / "predictions_long.csv")

            display(pd.DataFrame([{"observed_market_run": str(run_dir)}]))
            """
        ),
        md("## Split Policy And Coverage"),
        code("display(split_summary)\ndisplay(coverage_summary.head(20))"),
        md("## Overall Metrics"),
        code("display(metrics_overall.sort_values(['dataset_split', 'mae', 'model']).reset_index(drop=True))"),
        md("## Lead-Day Metrics"),
        code("display(metrics_by_lead_day.sort_values(['dataset_split', 'lead_day', 'mae', 'model']).reset_index(drop=True))"),
        md("## DM Tests"),
        code("display(dm_results)"),
        md(
            """
            ## Observed-Target Policy Check

            The scoring contract is only valid if non-observed targets keep `y_true = NaN`.
            """
        ),
        code(
            """
            observed_policy_check = pd.DataFrame(
                [
                    {
                        "rows_total": int(predictions.shape[0]),
                        "non_observed_rows": int((~predictions["is_observed_target"].fillna(False).astype(bool)).sum()),
                        "non_observed_rows_with_non_null_y_true": int(
                            predictions.loc[
                                ~predictions["is_observed_target"].fillna(False).astype(bool),
                                "y_true",
                            ].notna().sum()
                        ),
                    }
                ]
            )
            display(observed_policy_check)
            """
        ),
        md(
            """
            ## Thesis Interpretation Contract

            This notebook supports three narrow claims:

            - the quarter-hour deterministic forecast is leakage-safe under the audited hourly availability convention;
            - the observed-market evaluation uses only observed 15-minute targets as ground truth;
            - the repeated-hourly benchmark remains visible so the value of added 15-minute modelling is not assumed.
            """
        ),
    ]
    return new_notebook(cells=cells, metadata={"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}})


def main() -> int:
    NOTEBOOK_ROOT.mkdir(parents=True, exist_ok=True)
    notebook_specs = {
        "01_foundation_and_data_refresh.ipynb": build_phase01_notebook(),
        "02_shape_target_diagnostics.ipynb": build_phase02_notebook(),
        "03_dynamic_hourly_anchor_selection.ipynb": build_phase03_notebook(),
        "04_empirical_shape_model_validation.ipynb": build_phase04_notebook(),
        "05_counterfactual_full_year_generation.ipynb": build_phase05_notebook(),
        "06_milp_ready_exports.ipynb": build_phase06_notebook(),
        "07_realistic_track_a_end_to_end_validation.ipynb": build_phase07_notebook(),
        "08_results_and_plot_interpretation.ipynb": build_phase08_notebook(),
        "09_frozen_canonical_actual_path.ipynb": build_phase09_notebook(),
        "10_observed_market_deterministic_forecast.ipynb": build_phase10_notebook(),
    }
    for filename, notebook in notebook_specs.items():
        target = NOTEBOOK_ROOT / filename
        target.write_text(nbformat.writes(notebook), encoding="utf-8")
        print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
