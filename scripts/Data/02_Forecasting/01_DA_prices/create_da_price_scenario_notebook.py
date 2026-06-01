from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


NOTEBOOK_PATH = Path("notebooks/Data/03_Scenario's/01_da_price_scenario_generation_hourly.ipynb")


def md(text: str):
    return new_markdown_cell(dedent(text).strip())


def code(text: str):
    return new_code_cell(dedent(text).strip())


def build_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 01 DA Price Scenario Generation Hourly

            This notebook is the **hourly day-ahead (DA) price scenario-generation layer** that sits directly downstream of the existing deterministic forecasting pipeline.

            The point forecasts remain the starting point, but not the final story. In electricity markets, a single path can look accurate on average while still missing the hours that matter most operationally. The notebook therefore turns deterministic forecasts into empirical residual-based scenarios and validates those scenarios before any later MILP or CVaR work is attempted.

            Scope boundaries for this notebook:
            - hourly DA prices only
            - the **D / day-ahead delivery day** focus only
            - no mFRR
            - no multi-day implementation yet
            - no 15-minute implementation yet
            - no steel-plant or bidding MILP yet
            - no retraining or retuning of forecasting models

            The output is a tractable, thesis-oriented scenario layer that can later feed:
            1. multi-day hourly scenario blocks,
            2. 15-minute scenarios,
            3. a toy MILP with CVaR,
            4. the full DA bidding MILP with CVaR.
            """
        ),
        code(
            """
            from pathlib import Path
            import importlib
            import json
            import os
            import sys

            import matplotlib.dates as mdates
            import matplotlib.pyplot as plt
            import numpy as np
            import pandas as pd
            from IPython.display import Markdown, display
            from matplotlib.lines import Line2D
            from matplotlib.patches import Patch

            NOTEBOOK_CWD = Path.cwd()
            REPO_ROOT = next(
                path
                for path in [NOTEBOOK_CWD, *NOTEBOOK_CWD.parents]
                if (path / "scripts/Data/02_Forecasting/01_DA_prices").exists()
            )
            os.chdir(REPO_ROOT)

            PACKAGE_ROOT = REPO_ROOT / "scripts/Data/02_Forecasting/01_DA_prices"
            if str(PACKAGE_ROOT) not in sys.path:
                sys.path.append(str(PACKAGE_ROOT))

            import hourly_da.core.scenario_generation as scenario_generation_module

            scenario_generation_module = importlib.reload(scenario_generation_module)

            from hourly_da.core.config import HourlyDAPipelineConfig
            from hourly_da.core.forecast_evaluation import (
                load_candidate_predictions,
                summarize_candidate_coverage,
                summarize_local_day_lengths,
                summarize_missingness,
            )
            from hourly_da.core.scenario_generation import (
                apply_notebook_artifact_retention,
                apply_bias_correction,
                apply_bias_correction_candidate_settings,
                build_bank_availability_summary,
                build_bias_correction_maps,
                build_conditional_bias_summary,
                build_final_recommendation,
                build_residual_daily_profiles,
                build_residual_period_table,
                build_stress_scenario_catalog,
                build_tail_day_catalog,
                build_variant_plan,
                choose_official_naive_candidate,
                choose_target_evaluation_slice,
                compute_candidate_selection_summary,
                create_scenario_output_paths,
                discover_scenario_candidate_sources,
                find_latest_scenario_artifact_run,
                generate_scenario_bundle,
                load_saved_scenario_artifacts,
                plot_scenario_grid as shared_plot_scenario_grid,
                score_scenario_variants,
                select_plot_weeks_from_period_residuals,
                select_representative_days,
                select_stress_diagnostic_days,
                select_scenario_candidates,
                summarize_bias_correction_impact,
                validate_scenario_set,
            )

            pd.set_option("display.max_columns", 200)
            pd.set_option("display.width", 220)
            plt.style.use("default")

            NOTEBOOK_SLUG = "01_da_price_scenario_generation_hourly"
            config = HourlyDAPipelineConfig(
                input_csv=REPO_ROOT / "data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv",
                raw_root=REPO_ROOT / "data/00_Raw/DA_Prices",
                cleaned_feature_root=REPO_ROOT / "data/01_cleaned",
                output_root=REPO_ROOT / "data/02_Forecasting/01_DA_prices/hourly_da",
            )
            output_paths = create_scenario_output_paths(config.output_root, NOTEBOOK_SLUG)
            warnings_log: list[str] = []
            PLOT_RELOAD_RUN_DIR: str | None = None
            PLOT_RELOAD_LATEST_IF_NEEDED = True
            plot_output_dir = output_paths.plots_dir


            def display_markdown(text: str) -> None:
                display(Markdown(text))


            def format_pct(value: float | int | None) -> str:
                if value is None or pd.isna(value):
                    return "-"
                return f"{float(value) * 100.0:.1f}%"


            def format_float(value: float | int | None, digits: int = 3) -> str:
                if value is None or pd.isna(value):
                    return "-"
                return f"{float(value):.{digits}f}"


            def style_compact_table(frame: pd.DataFrame, *, metric_higher_is_better: list[str] | None = None, metric_lower_is_better: list[str] | None = None):
                metric_higher_is_better = metric_higher_is_better or []
                metric_lower_is_better = metric_lower_is_better or []
                styler = frame.style.hide(axis="index")
                number_formats = {
                    column: "{:.3f}"
                    for column in frame.columns
                    if column not in {"candidate_label", "candidate_id", "candidate_key", "selection_role", "scenario_variant", "source_run_id"}
                    and pd.api.types.is_numeric_dtype(frame[column])
                    and not pd.api.types.is_bool_dtype(frame[column])
                }
                styler = styler.format(number_formats)
                if metric_higher_is_better:
                    styler = styler.highlight_max(subset=metric_higher_is_better, color="#dff0d8")
                if metric_lower_is_better:
                    styler = styler.highlight_min(subset=metric_lower_is_better, color="#dff0d8")
                return styler


            def maybe_reload_plot_artifacts() -> bool:
                global residual_periods, residual_daily_profiles, scenario_prices_long, scenario_metadata
                global scenario_validation_summary, period_quantiles, target_split, plot_output_dir
                selected_run_dir = Path(PLOT_RELOAD_RUN_DIR) if PLOT_RELOAD_RUN_DIR else None
                if selected_run_dir is None and PLOT_RELOAD_LATEST_IF_NEEDED:
                    selected_run_dir = find_latest_scenario_artifact_run(config.output_root, NOTEBOOK_SLUG)
                if selected_run_dir is None:
                    return False
                reload_bundle = load_saved_scenario_artifacts(selected_run_dir, config=config)
                residual_periods = reload_bundle["residual_periods"].copy()
                residual_daily_profiles = reload_bundle["residual_daily_profiles"].copy()
                scenario_prices_long = reload_bundle["scenario_prices_long"].copy()
                scenario_metadata = reload_bundle["scenario_metadata"].copy()
                scenario_validation_summary = reload_bundle["scenario_validation_summary"].copy()
                period_quantiles = reload_bundle["period_quantiles"].copy()
                target_split = str(reload_bundle.get("target_split", "test"))
                plot_output_dir = Path(reload_bundle["output_dir"]) / "plots"
                return True


            def plot_scenario_grid(
                scenario_prices_long: pd.DataFrame,
                scenario_metadata: pd.DataFrame,
                period_quantiles: pd.DataFrame,
                *,
                candidate_variant_rows: list[dict[str, str]],
                representative_days: list[dict[str, str]] | pd.DataFrame,
                title: str,
                output_path: Path | None = None,
                max_columns: int = 3,
            ) -> list[Path]:
                return shared_plot_scenario_grid(
                    scenario_prices_long,
                    scenario_metadata,
                    period_quantiles,
                    candidate_variant_rows=candidate_variant_rows,
                    representative_days=representative_days,
                    title=title,
                    output_path=output_path,
                    max_columns=max_columns,
                )


            def build_week_day_rows(
                daily_profiles: pd.DataFrame,
                *,
                candidate_key: str,
                dataset_split: str,
                week_row: dict[str, object],
            ) -> pd.DataFrame:
                week_days = daily_profiles[
                    (daily_profiles["candidate_key"].astype(str) == str(candidate_key))
                    & (daily_profiles["dataset_split"].astype(str) == str(dataset_split))
                ].copy()
                if week_days.empty:
                    return pd.DataFrame()
                week_days["delivery_day_ts"] = pd.to_datetime(week_days["delivery_day"])
                start_date = pd.Timestamp(str(week_row["week_start_local_date"]))
                end_date = pd.Timestamp(str(week_row["week_end_local_date"]))
                week_days = week_days[
                    (week_days["delivery_day_ts"] >= start_date)
                    & (week_days["delivery_day_ts"] <= end_date)
                ].copy()
                if week_days.empty:
                    return week_days
                week_days["plot_title"] = week_days["delivery_day_ts"].dt.strftime("%a %Y-%m-%d")
                week_days["day_category"] = week_days["delivery_day_ts"].dt.strftime("%a").str.lower()
                week_days = week_days.rename(
                    columns={
                        "realised_daily_mean": "actual_daily_mean",
                        "realised_daily_spread": "actual_daily_spread",
                    }
                )
                return week_days.sort_values("delivery_day_ts").drop(columns=["delivery_day_ts"]).reset_index(drop=True)
            """
        ),
        md(
            """
            ## 1. Notebook Purpose And Scope

            The central forecast path is useful, but it is not deterministic truth. Real prices can deviate from the point forecast in structured ways, especially during volatile periods or peak-price events.

            This notebook therefore builds scenarios by taking the chosen point forecast and **adding historically observed forecast-error shapes** back onto it.

            Why this is methodologically useful:
            - deterministic forecasts can look good on average while still missing dangerous upside price spikes
            - whole-day residual profiles preserve realistic multi-hour error shapes
            - the scenario layer can be validated before it is asked to drive a later optimizer

            Important limitation:
            - this notebook only handles **hourly, D-only, empirical residual-based** DA scenarios
            - it is **not** yet the bidding MILP
            - it is **not** yet probabilistic forecasting in the broader methodological sense
            """
        ),
        md(
            """
            ## 2. Load Forecast Evaluation Artifacts

            The notebook does not regenerate forecasts. It discovers the latest relevant saved benchmark artifacts from the active hourly DA output tree and then checks whether the required forecast-vs-actual columns are present.

            The discovery rule is intentionally conservative:
            - only complete benchmark-parent or aggregate-comparison runs are considered
            - exploratory, debug, runtime-check, and ablation folders are excluded
            - candidate selection then happens on the discovered forecast-vs-actual data rather than on hardcoded model names
            """
        ),
        code(
            """
            discovery = discover_scenario_candidate_sources(config.output_root)
            candidate_frame = discovery["candidate_frame"].copy()
            candidate_predictions = load_candidate_predictions(candidate_frame=candidate_frame, config=config)

            required_prediction_columns = {
                "candidate_key",
                "candidate_label",
                "dataset_split",
                "forecast_origin_utc",
                "target_timestamp_utc",
                "lead_day",
                "y_true",
                "y_pred",
                "source_run_id",
            }
            missing_required_columns = sorted(required_prediction_columns - set(candidate_predictions.columns))
            if missing_required_columns:
                raise RuntimeError(
                    "The discovered benchmark artifacts are missing required forecast-vs-actual columns: "
                    + ", ".join(missing_required_columns)
                    + ". Upstream benchmark runs must be refreshed before scenario generation can proceed."
                )
            if candidate_predictions.empty:
                raise RuntimeError(
                    "No forecast-vs-actual rows were discovered. Run the hourly DA benchmark workflow first so that "
                    "the run folders under data/02_Forecasting/01_DA_prices/hourly_da/runs contain predictions_long."
                )

            availability_table = discovery["availability"].copy()
            coverage_table = summarize_candidate_coverage(candidate_predictions)
            missingness_table = summarize_missingness(candidate_predictions)
            local_day_length_table = summarize_local_day_lengths(candidate_predictions)
            date_coverage_table = (
                candidate_predictions.groupby(["candidate_key", "candidate_label", "dataset_split"], dropna=False)
                .agg(
                    first_target_utc=("target_timestamp_utc", "min"),
                    last_target_utc=("target_timestamp_utc", "max"),
                    forecast_rows=("target_timestamp_utc", "size"),
                    forecast_origins=("forecast_origin_utc", "nunique"),
                    unique_targets=("target_timestamp_utc", "nunique"),
                    lead_days_present=("lead_day", lambda values: ", ".join(sorted({config.lead_day_label(int(value)) for value in values}))),
                )
                .reset_index()
                .sort_values(["dataset_split", "candidate_label"])
                .reset_index(drop=True)
            )

            display_markdown("### Candidate availability")
            display(availability_table)
            display_markdown("### Date coverage and row counts")
            display(date_coverage_table)
            display_markdown("### Coverage by split and lead day")
            display(coverage_table.head(40))
            display_markdown("### Missingness check")
            display(missingness_table)
            display_markdown("### Local day lengths")
            display(local_day_length_table)
            """
        ),
        md(
            """
            ## 3. Adaptive Candidate Selection

            Two forecast candidates are selected automatically:

            **Candidate 1: deterministic all-round winner**
            - use `test` if available, otherwise `validation`
            - focus on `D`
            - primary criterion: lowest `rMAE`
            - tie-breakers: `MAE`, `RMSE`, and then lowest absolute bias

            **Candidate 2: hour-ranking winner**
            - focus on identifying the most important hours for decision-making
            - use daily recall for the actual top-3 expensive hours and top-3 cheap hours
            - balanced ranking score: `0.50 * expensive recall + 0.50 * cheap recall`
            - risk-weighted diagnostic score: `0.65 * expensive recall + 0.35 * cheap recall`

            Why both matter:
            - the deterministic winner is strongest on average forecast error
            - the ranking winner can still be valuable if it better identifies the hours where expensive or cheap DA mistakes matter most
            """
        ),
        code(
            """
            official_naive_info = choose_official_naive_candidate(candidate_predictions)
            evaluation_choice = choose_target_evaluation_slice(candidate_predictions, preferred_splits=("test", "validation"), preferred_lead_day=0)
            candidate_selection_summary = compute_candidate_selection_summary(
                candidate_predictions,
                selection_split=str(evaluation_choice["dataset_split"]),
                selection_lead_day=int(evaluation_choice["lead_day"]),
                official_naive_candidate_key=str(official_naive_info["selected"]["candidate_key"]),
                k_top_hours=3,
            )
            selection_bundle = select_scenario_candidates(candidate_selection_summary)
            candidate_selection_summary = selection_bundle["selection_summary"].copy()
            selected_candidate_keys = selection_bundle["selected_candidate_keys"]
            selected_role_table = selection_bundle["role_rows"].copy()

            if len(selected_candidate_keys) == 1:
                warnings_log.append(
                    "The deterministic winner and the hour-ranking winner are the same candidate. The notebook keeps one shared candidate and reports the ranking runner-up only as context."
                )

            display_markdown(
                f"**Official naive denominator**: `{official_naive_info['selected']['candidate_label']}` selected on "
                f"`{official_naive_info['selected']['selection_split']}` with the benchmark rule "
                f"`{official_naive_info['selected']['selection_policy']}`."
            )
            display_markdown(
                f"**Selection slice**: `{evaluation_choice['dataset_split']}` on lead day `{evaluation_choice['lead_day_label']}`."
            )
            display(
                style_compact_table(
                    candidate_selection_summary[
                        [
                            "candidate_label",
                            "source_run_id",
                            "rmae",
                            "mae",
                            "rmse",
                            "bias",
                            "topk_expensive_recall",
                            "topk_cheap_recall",
                            "ranking_score",
                            "risk_weighted_ranking_score",
                            "selected_as_deterministic_winner",
                            "selected_as_hour_ranking_winner",
                        ]
                    ].rename(
                        columns={
                            "source_run_id": "source_run_id",
                            "topk_expensive_recall": "top3_expensive_recall",
                            "topk_cheap_recall": "top3_cheap_recall",
                        }
                    ),
                    metric_higher_is_better=["top3_expensive_recall", "top3_cheap_recall", "ranking_score", "risk_weighted_ranking_score"],
                    metric_lower_is_better=["rmae", "mae", "rmse"],
                )
            )
            """
        ),
        md(
            """
            ## 4. Construct Residual Database

            Residuals are defined as:

            `residual = actual_price - forecast_price`

            Interpretation:
            - a **positive** residual means the actual price was **higher** than forecast, so the model **underestimated**
            - a **negative** residual means the actual price was **lower** than forecast, so the model **overestimated**

            The notebook builds two residual layers:
            - a **period-level** table for hourly diagnostics and later bias correction
            - a **daily-profile** table so full residual shapes can be sampled as realistic scenario paths

            Calibration rule:
            - use `validation` residuals for scenario calibration when available
            - use `test` mainly for scenario evaluation and reporting
            - if only `test` exists, the notebook will still run, but it warns that the calibration design is less clean
            """
        ),
        code(
            """
            selected_candidate_predictions = candidate_predictions[
                candidate_predictions["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys])
            ].copy()
            calibration_split = "validation" if "validation" in set(selected_candidate_predictions["dataset_split"].astype(str).unique()) else str(evaluation_choice["dataset_split"])
            target_split = str(evaluation_choice["dataset_split"])
            if calibration_split == target_split:
                warnings_log.append(
                    "Validation residuals were not available, so the notebook is using the same split for calibration and evaluation. Treat the scenario assessment as diagnostic rather than clean holdout validation."
                )

            residual_periods_raw = build_residual_period_table(selected_candidate_predictions, config=config, lead_day=int(evaluation_choice["lead_day"]))
            residual_daily_profiles = build_residual_daily_profiles(residual_periods_raw)
            bank_availability_summary = build_bank_availability_summary(residual_daily_profiles, calibration_split=calibration_split)
            tail_day_catalog = build_tail_day_catalog(
                residual_daily_profiles,
                calibration_split=calibration_split,
                selected_candidate_keys=selected_candidate_keys,
                top_n=8,
            )
            stress_day_catalog = build_stress_scenario_catalog(
                residual_daily_profiles,
                calibration_split=calibration_split,
                selected_candidate_keys=selected_candidate_keys,
            )
            conditional_bias_summary = build_conditional_bias_summary(residual_periods_raw)

            residual_database_overview = (
                residual_daily_profiles.groupby(["candidate_label", "dataset_split"], dropna=False)
                .agg(
                    days=("delivery_day", "nunique"),
                    mean_positive_residual=("mean_positive_residual", "mean"),
                    mean_negative_residual=("mean_negative_residual", "mean"),
                    mean_daily_residual=("residual_daily_mean", "mean"),
                    high_volatility_days=("high_volatility_flag", lambda values: int(pd.Series(values).fillna(False).sum())),
                )
                .reset_index()
                .sort_values(["dataset_split", "candidate_label"])
            )

            display_markdown("### Residual database overview")
            display(residual_database_overview)
            display_markdown("### Residual bank availability")
            display(bank_availability_summary.head(40))
            """
        ),
        md(
            """
            ## 5. Residual Diagnostics

            Residual diagnostics answer a simple question: **how do these selected forecasts fail, and do they fail in a stable way?**

            This matters because scenario generation should not add arbitrary noise. It should reflect the actual structure of forecast errors:
            - overall underestimation versus overestimation
            - specific hours that are systematically missed
            - seasonal or weekday/weekend patterns
            - volatility regimes where underestimation becomes more dangerous

            The plots and tables below should be read as model-behaviour diagnostics, not as proof that a later optimizer would necessarily perform better.
            """
        ),
        code(
            """
            residual_sign_summary = (
                residual_periods_raw.groupby(["candidate_label", "dataset_split"], dropna=False)
                .agg(
                    mean_residual=("residual", "mean"),
                    median_residual=("residual", "median"),
                    mean_positive_residual=("underestimation_component", "mean"),
                    mean_overestimation_severity=("overestimation_component", "mean"),
                    p95_underestimation=("underestimation_component", lambda values: float(pd.Series(values).quantile(0.95))),
                )
                .reset_index()
                .sort_values(["dataset_split", "candidate_label"])
            )

            worst_under_days = (
                residual_daily_profiles[
                    residual_daily_profiles["dataset_split"].astype(str) == target_split
                ]
                .sort_values(["candidate_label", "mean_positive_residual", "delivery_day"], ascending=[True, False, True])
                .groupby("candidate_key", dropna=False)
                .head(5)
                .reset_index(drop=True)
            )
            worst_over_days = (
                residual_daily_profiles[
                    residual_daily_profiles["dataset_split"].astype(str) == target_split
                ]
                .sort_values(["candidate_label", "overestimation_severity", "delivery_day"], ascending=[True, False, True])
                .groupby("candidate_key", dropna=False)
                .head(5)
                .reset_index(drop=True)
            )
            strongest_conditional_bias = (
                conditional_bias_summary[
                    conditional_bias_summary["dataset_split"].astype(str) == calibration_split
                ]
                .assign(abs_mean_residual=lambda frame: frame["mean_residual"].abs())
                .sort_values(["candidate_label", "abs_mean_residual"], ascending=[True, False])
                .groupby("candidate_key", dropna=False)
                .head(10)
                .reset_index(drop=True)
            )

            display_markdown("### Positive versus negative residual summary")
            display(residual_sign_summary)
            display_markdown("### Worst underestimation days")
            display(worst_under_days[["candidate_label", "delivery_day", "mean_positive_residual", "max_positive_residual", "realised_daily_spread", "high_volatility_flag"]])
            display_markdown("### Worst overestimation days")
            display(worst_over_days[["candidate_label", "delivery_day", "overestimation_severity", "max_negative_residual", "realised_daily_spread", "high_volatility_flag"]])
            display_markdown("### Strongest conditional bias cells")
            display(strongest_conditional_bias[["candidate_label", "season", "day_type", "target_local_hour", "forecast_price_level_bucket", "observations", "mean_residual"]])
            """
        ),
        code(
            """
            target_residuals = residual_periods_raw[residual_periods_raw["dataset_split"].astype(str) == target_split].copy()
            candidates_in_scope = target_residuals["candidate_label"].drop_duplicates().tolist()

            fig, axes = plt.subplots(len(candidates_in_scope), 3, figsize=(18, 5 * len(candidates_in_scope)), squeeze=False)
            for row_index, candidate_label in enumerate(candidates_in_scope):
                candidate_frame = target_residuals[target_residuals["candidate_label"].astype(str) == str(candidate_label)].copy()

                axes[row_index, 0].hist(candidate_frame["residual"], bins=40, color="#4c78a8", alpha=0.75)
                axes[row_index, 0].axvline(0.0, color="#111111", linestyle="--", linewidth=1.2)
                axes[row_index, 0].set_title(f"{candidate_label}: residual distribution", loc="left", fontweight="bold")
                axes[row_index, 0].set_xlabel("Residual = actual - forecast")
                axes[row_index, 0].set_ylabel("Count")
                axes[row_index, 0].grid(alpha=0.2)

                by_hour = (
                    candidate_frame.groupby("target_local_hour", dropna=False)["residual"]
                    .mean()
                    .reset_index()
                    .sort_values("target_local_hour")
                )
                axes[row_index, 1].bar(by_hour["target_local_hour"], by_hour["residual"], color="#59a14f")
                axes[row_index, 1].axhline(0.0, color="#111111", linestyle="--", linewidth=1.2)
                axes[row_index, 1].set_title(f"{candidate_label}: mean residual by hour", loc="left", fontweight="bold")
                axes[row_index, 1].set_xlabel("Local delivery hour")
                axes[row_index, 1].set_ylabel("Mean residual")
                axes[row_index, 1].grid(alpha=0.2)

                by_day_type = (
                    candidate_frame.groupby(["season", "day_type"], dropna=False)["residual"]
                    .mean()
                    .reset_index()
                )
                labels = [f"{row['season']} | {row['day_type']}" for row in by_day_type.to_dict(orient="records")]
                axes[row_index, 2].bar(labels, by_day_type["residual"], color="#e15759")
                axes[row_index, 2].axhline(0.0, color="#111111", linestyle="--", linewidth=1.2)
                axes[row_index, 2].set_title(f"{candidate_label}: mean residual by season and day type", loc="left", fontweight="bold")
                axes[row_index, 2].set_ylabel("Mean residual")
                axes[row_index, 2].tick_params(axis="x", rotation=45)
                axes[row_index, 2].grid(alpha=0.2)

            plt.tight_layout()
            plt.show()
            """
        ),
        md(
            """
            ## 6. Scenario Generation Configuration

            The configuration is explicit so the scenario layer stays transparent and easy to rerun.

            The defaults below are not hand-picked inside the notebook. They are loaded from the latest **validation-only Option A / Option B sweep**:
            - Option A was tuned by sweeping positive-tail and negative-tail shares while holding scenario counts fixed.
            - Option B was tuned by sweeping the stress probability share while holding the chosen Option A setting fixed.
            - Option C is kept in the notebook for transparency, but disabled by default after the dedicated Option C validation sweep.

            The raw and final scenario counts are still fixed for the active notebook run:
            - the raw count must be high enough for reduction to matter,
            - the final count must be large enough to keep both a stochastic core and the protected stress scenarios.
            """
        ),
        code(
            """
            option_ab_sweep_root = config.output_root / "option_ab_sweeps"
            latest_option_ab_sweep_dir = None
            option_ab_recommendation = {}
            option_a_summary = pd.DataFrame()
            option_b_summary = pd.DataFrame()
            option_ab_notebook_defaults = pd.DataFrame()
            if option_ab_sweep_root.exists():
                sweep_dirs = sorted([path for path in option_ab_sweep_root.iterdir() if path.is_dir()], key=lambda path: path.name)
                latest_option_ab_sweep_dir = sweep_dirs[-1] if sweep_dirs else None
            if latest_option_ab_sweep_dir is not None:
                recommendation_path = latest_option_ab_sweep_dir / "option_ab_sweep_recommendation.json"
                option_a_summary_path = latest_option_ab_sweep_dir / "option_a_validation_sweep_summary.csv"
                option_b_summary_path = latest_option_ab_sweep_dir / "option_b_validation_sweep_summary.csv"
                notebook_defaults_path = latest_option_ab_sweep_dir / "option_ab_notebook_defaults.csv"
                if recommendation_path.exists():
                    option_ab_recommendation = json.loads(recommendation_path.read_text(encoding="utf-8"))
                if option_a_summary_path.exists():
                    option_a_summary = pd.read_csv(option_a_summary_path)
                if option_b_summary_path.exists():
                    option_b_summary = pd.read_csv(option_b_summary_path)
                if notebook_defaults_path.exists():
                    option_ab_notebook_defaults = pd.read_csv(notebook_defaults_path)

            if latest_option_ab_sweep_dir is not None:
                display_markdown(f"### Loaded Option A/B sweep artifact: `{latest_option_ab_sweep_dir.name}`")
            if not option_a_summary.empty:
                display_markdown("### Option A validation sweep summary")
                display(option_a_summary.head(10))
            if not option_b_summary.empty:
                display_markdown("### Option B validation sweep summary")
                display(option_b_summary.head(10))

            defaults = option_ab_recommendation.get("notebook_defaults", {}) if option_ab_recommendation else {}
            SCENARIO_CONFIG = {
                "random_seed": 42,
                "n_raw_scenarios": int(defaults.get("n_raw_scenarios", 30)),
                "n_final_scenarios": int(defaults.get("n_final_scenarios", 15)),
                "target_split": target_split,
                "calibration_split": calibration_split,
                "k_top_hours": 3,
                "use_option_a_tail_enrichment": bool(defaults.get("use_option_a_tail_enrichment", True)),
                "use_option_b_stress_scenarios": bool(defaults.get("use_option_b_stress_scenarios", True)),
                "use_option_c_bias_correction": bool(defaults.get("use_option_c_bias_correction", False)),
                "normal_share": float(defaults.get("normal_share", 0.60)),
                "positive_tail_share": float(defaults.get("positive_tail_share", 0.30)),
                "negative_tail_share": float(defaults.get("negative_tail_share", 0.10)),
                "stress_share": float(defaults.get("stress_share", 0.15)),
                "alpha_placeholder_for_future_cvar": 0.95,
            }
            if bool(SCENARIO_CONFIG["use_option_b_stress_scenarios"]) and int(SCENARIO_CONFIG["n_final_scenarios"]) < 6:
                raise ValueError("Option B uses six protected stress scenario types, so n_final_scenarios must be at least 6.")
            variant_plan = build_variant_plan(
                use_option_a_tail_enrichment=bool(SCENARIO_CONFIG["use_option_a_tail_enrichment"]),
                use_option_b_stress_scenarios=bool(SCENARIO_CONFIG["use_option_b_stress_scenarios"]),
                use_option_c_bias_correction=bool(SCENARIO_CONFIG["use_option_c_bias_correction"]),
            )

            if option_ab_recommendation:
                option_a_selected = option_ab_recommendation.get("option_a_selected", {})
                option_b_selected = option_ab_recommendation.get("option_b_selected", {})
                display_markdown(
                    f"Option A selected `positive_tail_share={option_a_selected.get('positive_tail_share', '-')}`, "
                    f"`negative_tail_share={option_a_selected.get('negative_tail_share', '-')}`, "
                    f"`normal_share={option_a_selected.get('normal_share', '-')}` with validation mean score gain "
                    f"`{format_float(option_a_selected.get('mean_scenario_score_gain'))}` and high-tail miss reduction "
                    f"`{format_float(option_a_selected.get('mean_high_tail_miss_reduction'))}`. "
                    f"Option B selected `stress_share={option_b_selected.get('stress_share', '-')}` with validation mean score gain "
                    f"`{format_float(option_b_selected.get('mean_scenario_score_gain'))}` and high-tail miss reduction "
                    f"`{format_float(option_b_selected.get('mean_high_tail_miss_reduction'))}`."
                )
            display(pd.DataFrame([SCENARIO_CONFIG]))
            display(variant_plan)
            """
        ),
        md(
            """
            ## 7. Base Method: Whole-Day Residual Shape Sampling

            The base method samples **complete historical daily residual profiles** and adds those profiles to the central forecast.

            Why this is the preferred base:
            - it preserves realistic intraday error shape
            - it keeps multi-hour underestimation or overestimation blocks intact
            - it avoids the unrealistic assumption that each hour's error should be sampled independently

            In other words, the notebook treats forecast errors as **day-shaped patterns**, not as isolated hourly shocks.
            """
        ),
        md(
            """
            ## 8. Conditional Sampling

            Residual banks are not sampled blindly from the full history. The notebook uses a simple fallback hierarchy:

            1. same season + same day type + same lead day
            2. same season + same day type
            3. same season
            4. same day type
            5. all residual days

            A same-length day requirement is also kept in place so 23-hour and 25-hour DST days remain structurally consistent.
            """
        ),
        code(
            """
            small_bank_summary = (
                bank_availability_summary.groupby(["candidate_label", "hours_in_day"], dropna=False)["available_days"]
                .agg(["min", "median", "max"])
                .reset_index()
                .rename(columns={"min": "min_bank_days", "median": "median_bank_days", "max": "max_bank_days"})
            )
            display_markdown("### Bank-size summary")
            display(small_bank_summary)
            display_markdown("### Full bank availability table")
            display(bank_availability_summary)
            """
        ),
        md(
            """
            ## 9. Option A: Asymmetric / Tail-Enriched Residual Sampling

            Option A biases a share of stochastic draws toward historically dangerous underestimation days.

            This is still statistical, not manual:
            - a positive-tail severity score is computed from historical residual days
            - high-positive-tail days are defined by quantiles
            - a configurable share of draws is taken from those days

            Interpretation:
            - this protects the scenario set against repeated underestimation of high prices
            - if the tail share becomes too large, the later optimizer could become overly conservative
            """
        ),
        code(
            """
            display_markdown("### Candidate tail-day catalog from the calibration split")
            display(
                tail_day_catalog[
                    [
                        "candidate_label",
                        "tail_side",
                        "delivery_day",
                        "positive_residual_severity",
                        "overestimation_severity",
                        "realised_daily_spread",
                        "positive_tail_top25_flag",
                        "positive_tail_top05_flag",
                        "negative_tail_top25_flag",
                    ]
                ].sort_values(["candidate_label", "tail_side", "delivery_day"]).reset_index(drop=True)
            )
            """
        ),
        md(
            """
            ## 10. Option B: Statistically Selected Protected Stress Scenarios

            Protected stress scenarios are different from ordinary stochastic samples.

            They are selected from the historical forecast failures using fixed statistical rules, for example:
            - worst average underestimation day
            - worst evening peak miss
            - worst miss of the daily maximum
            - worst miss in the actual top-3 expensive hours
            - a representative high-volatility day
            - a strong overestimation day for cheap-hour sensitivity

            These scenarios are not assumed to be highly probable. Their job is to keep rare but plausible failure shapes visible for later robustness testing.
            """
        ),
        code(
            """
            display(stress_day_catalog)
            """
        ),
        md(
            """
            ## 11. Option C: Optional Conditional Residual Bias Correction

            Option C corrects stable conditional bias before scenarios are generated.

            The idea is simple:
            - if validation residuals show a stable average underestimation pattern for a condition such as season x day type x hour
            - then the central forecast can be shifted by that average bias
            - the residual profiles are then sampled on the debiased scale

            Important caveat:
            - this can help if the residual bias is stable
            - it can overfit if the pattern is weak or unstable
            - therefore the notebook treats it as optional and reports before/after diagnostics explicitly

            In the active repo, Option C settings are not chosen ad hoc inside this notebook. The notebook looks for the latest **validation-only Option C sweep** artifact and applies the frozen accepted setting per candidate:
            - the sweep estimates candidate settings on an early validation block,
            - chooses the best setting on a later validation block,
            - then performs one final test check,
            - and only accepted settings are applied here.

            For the current default scenario generator, Option C is **disabled**. The notebook still shows the sweep result so the rejection is documented rather than hidden.
            """
        ),
        code(
            """
            option_c_sweep_root = config.output_root / "option_c_sweeps"
            latest_option_c_sweep_dir = None
            if option_c_sweep_root.exists():
                sweep_dirs = sorted([path for path in option_c_sweep_root.iterdir() if path.is_dir()], key=lambda path: path.name)
                latest_option_c_sweep_dir = sweep_dirs[-1] if sweep_dirs else None

            option_c_selected_settings = pd.DataFrame()
            option_c_test_evaluation = pd.DataFrame()
            option_c_recommendation = {}
            if latest_option_c_sweep_dir is not None:
                settings_path = latest_option_c_sweep_dir / "option_c_notebook_applied_settings.csv"
                test_eval_path = latest_option_c_sweep_dir / "option_c_test_evaluation.csv"
                recommendation_path = latest_option_c_sweep_dir / "option_c_sweep_recommendation.json"
                if settings_path.exists():
                    option_c_selected_settings = pd.read_csv(settings_path)
                if test_eval_path.exists():
                    option_c_test_evaluation = pd.read_csv(test_eval_path)
                if recommendation_path.exists():
                    option_c_recommendation = json.loads(recommendation_path.read_text(encoding="utf-8"))

            if option_c_selected_settings.empty:
                warnings_log.append("No Option C sweep artifact was found. Notebook fell back to the legacy full-strength mean correction.")
                bias_correction_maps = build_bias_correction_maps(residual_periods_raw, calibration_split=calibration_split)
                residual_periods = apply_bias_correction(
                    residual_periods_raw,
                    bias_correction_maps,
                    min_observations=20,
                    setting_id="legacy_fallback",
                    statistic_label="mean",
                )
            else:
                residual_periods = apply_bias_correction_candidate_settings(
                    residual_periods_raw,
                    option_c_selected_settings,
                    calibration_split=calibration_split,
                )
            bias_correction_impact = summarize_bias_correction_impact(residual_periods)
            bias_correction_interpretation = bias_correction_impact.copy()
            bias_correction_interpretation["abs_raw_bias"] = bias_correction_interpretation["raw_bias"].abs()
            bias_correction_interpretation["abs_corrected_bias"] = bias_correction_interpretation["corrected_bias"].abs()
            bias_correction_interpretation["bias_improved"] = (
                bias_correction_interpretation["abs_corrected_bias"] < bias_correction_interpretation["abs_raw_bias"]
            )
            bias_correction_interpretation["mae_improved"] = (
                bias_correction_interpretation["corrected_mae"] < bias_correction_interpretation["raw_mae"]
            )
            bias_correction_interpretation["rmse_improved"] = (
                bias_correction_interpretation["corrected_rmse"] < bias_correction_interpretation["raw_rmse"]
            )

            if latest_option_c_sweep_dir is not None:
                display_markdown(f"### Loaded Option C sweep artifact: `{latest_option_c_sweep_dir.name}`")
            if option_c_recommendation:
                display_markdown(
                    "Sweep design: early validation block for correction estimation, later validation block for model selection, then one final test acceptance check."
                )
            display_markdown("### Applied Option C settings per candidate")
            display(option_c_selected_settings)
            if not option_c_test_evaluation.empty:
                display_markdown("### Validation-selected Option C setting evaluated on validation and test")
                display(option_c_test_evaluation)
            display_markdown(
                "The `raw_*` columns describe the original point-forecast errors before any residual bias correction. "
                "The `corrected_*` columns show the same error metrics after shifting the central forecast by the estimated conditional average residual. "
                "In this table the bias sign uses `forecast - actual`, so a positive bias means average overestimation and a negative bias means average underestimation. "
                "Bias closer to zero is better. MAE and RMSE lower are better. If bias improves but MAE does not, then the correction reduces systematic level error without improving total forecast accuracy."
            )
            display_markdown("### Before/after bias and MAE")
            display(bias_correction_impact)
            display_markdown("### Bias-correction interpretation flags")
            display(
                bias_correction_interpretation[
                    [
                        "candidate_label",
                        "dataset_split",
                        "raw_bias",
                        "corrected_bias",
                        "raw_mae",
                        "corrected_mae",
                        "raw_rmse",
                        "corrected_rmse",
                        "bias_improved",
                        "mae_improved",
                        "rmse_improved",
                    ]
                ]
            )
            """
        ),
        md(
            """
            ## 12. Scenario Assembly And Metadata

            After the configuration and residual diagnostics are in place, the notebook generates the actual scenario tables.

            Each scenario row keeps:
            - the candidate
            - the variant
            - the target day and period
            - the scenario probability
            - the residual source day
            - whether the scenario is protected
            - the rule that created it

            This makes the scenario layer auditable instead of opaque.
            """
        ),
        code(
            """
            scenario_bundle = generate_scenario_bundle(
                residual_periods,
                residual_daily_profiles,
                config=config,
                calibration_split=str(SCENARIO_CONFIG["calibration_split"]),
                target_split=str(SCENARIO_CONFIG["target_split"]),
                selected_candidate_keys=selected_candidate_keys,
                variant_plan=variant_plan,
                scenario_run_id=output_paths.scenario_run_id,
                random_seed=int(SCENARIO_CONFIG["random_seed"]),
                n_raw_scenarios=int(SCENARIO_CONFIG["n_raw_scenarios"]),
                n_final_scenarios=int(SCENARIO_CONFIG["n_final_scenarios"]),
                normal_share=float(SCENARIO_CONFIG["normal_share"]),
                positive_tail_share=float(SCENARIO_CONFIG["positive_tail_share"]),
                negative_tail_share=float(SCENARIO_CONFIG["negative_tail_share"]),
                stress_share=float(SCENARIO_CONFIG["stress_share"]),
            )

            raw_scenario_prices = scenario_bundle["raw_scenarios"].copy()
            raw_scenario_metadata = scenario_bundle["raw_metadata"].copy()
            scenario_prices_long = scenario_bundle["final_scenarios"].copy()
            scenario_metadata = scenario_bundle["final_metadata"].copy()
            bank_logs = scenario_bundle["bank_logs"].copy()
            reduction_summary = scenario_bundle["reduction_summary"].copy()

            probability_check = (
                scenario_metadata.groupby(["candidate_label", "scenario_variant", "delivery_day"], dropna=False)["probability"]
                .sum()
                .reset_index(name="probability_sum")
            )
            if not probability_check["probability_sum"].round(8).eq(1.0).all():
                raise RuntimeError("Scenario probabilities do not sum to 1.0 within candidate x variant x delivery day.")

            scenario_type_summary = (
                scenario_metadata.groupby(["candidate_label", "scenario_variant", "scenario_type"], dropna=False)
                .size()
                .rename("scenario_count")
                .reset_index()
                .sort_values(["candidate_label", "scenario_variant", "scenario_type"])
                .reset_index(drop=True)
            )
            sampled_source_days = (
                scenario_metadata.groupby(["candidate_label", "scenario_variant", "source_day"], dropna=False)
                .size()
                .rename("times_sampled")
                .reset_index()
                .sort_values(["candidate_label", "scenario_variant", "times_sampled", "source_day"], ascending=[True, True, False, True])
                .groupby(["candidate_label", "scenario_variant"], dropna=False)
                .head(5)
                .reset_index(drop=True)
            )
            scenario_daily_summary = (
                scenario_prices_long.groupby(["candidate_label", "scenario_variant", "scenario_id"], dropna=False)
                .agg(
                    probability=("probability", "first"),
                    daily_mean=("scenario_price", "mean"),
                    daily_max=("scenario_price", "max"),
                    daily_spread=("scenario_price", lambda values: float(pd.Series(values).max() - pd.Series(values).min())),
                )
                .reset_index()
                .groupby(["candidate_label", "scenario_variant"], dropna=False)
                .agg(
                    scenarios=("scenario_id", "nunique"),
                    avg_daily_mean=("daily_mean", "mean"),
                    avg_daily_max=("daily_max", "mean"),
                    avg_daily_spread=("daily_spread", "mean"),
                )
                .reset_index()
            )

            display_markdown("### Scenario metadata preview")
            display(scenario_metadata.head(20))
            display_markdown("### Scenario price preview")
            display(scenario_prices_long.head(20))
            display_markdown("### Generated scenario counts by type")
            display(scenario_type_summary)
            display_markdown("### Most frequently sampled residual source days")
            display(sampled_source_days)
            display_markdown("### Scenario daily mean / max / spread summary")
            display(scenario_daily_summary)
            display_markdown("### Protected stress scenarios")
            display(scenario_metadata[scenario_metadata["protected"].fillna(False)].head(20))
            display_markdown("### Bank usage log")
            display(bank_logs.head(20))
            """
        ),
        md(
            """
            ## 13. Scenario Validation

            Scenario validation comes before any optimization use.

            The goal is not just wider envelopes. Wider scenarios can increase coverage while becoming too vague to be decision-useful. The notebook therefore reports both:
            - **coverage**: do actual prices fall inside the scenario envelopes often enough?
            - **sharpness**: are the scenarios still reasonably concentrated?

            A useful scenario set balances both.
            """
        ),
        code(
            """
            raw_validation_bundle = validate_scenario_set(raw_scenario_prices, config=config)
            final_validation_bundle = validate_scenario_set(scenario_prices_long, config=config)
            scenario_validation_summary = score_scenario_variants(final_validation_bundle["summary"])

            validation_display = scenario_validation_summary[
                [
                    "candidate_label",
                    "scenario_variant",
                    "minmax_coverage",
                    "p10_p90_coverage",
                    "p05_p95_coverage",
                    "high_tail_miss_rate",
                    "low_tail_miss_rate",
                    "average_p10_p90_width",
                    "daily_max_abs_error",
                    "daily_spread_abs_error",
                    "scenario_top3_expensive_recall",
                    "scenario_top3_cheap_recall",
                    "scenario_score",
                    "selected_as_default_variant",
                ]
            ].copy()
            display(
                style_compact_table(
                    validation_display,
                    metric_higher_is_better=[
                        "minmax_coverage",
                        "p10_p90_coverage",
                        "p05_p95_coverage",
                        "scenario_top3_expensive_recall",
                        "scenario_top3_cheap_recall",
                        "scenario_score",
                    ],
                    metric_lower_is_better=[
                        "high_tail_miss_rate",
                        "low_tail_miss_rate",
                        "average_p10_p90_width",
                        "daily_max_abs_error",
                        "daily_spread_abs_error",
                    ],
                )
            )
            """
        ),
        md(
            """
            ## 14. Visual Diagnostics

            The notebook now treats the plot layer as a separate interpretation step.

            If you open this notebook in a fresh kernel and jump straight to this section, it will automatically reload the **latest saved scenario run**. That avoids rebuilding the scenario bundle.

            You can still override the source manually by setting `PLOT_RELOAD_RUN_DIR` in the setup cell.

            Plotting rules:
            - at most **three columns** per figure
            - if more than three days are selected, the notebook automatically splits them across multiple figure pages
            - selection stays objective, but the notebook now prefers **distinct** days and weeks so the same date is not repeated unless the data leaves no reasonable alternative
            """
        ),
        code(
            """
            plot_inputs_ready = all(
                name in globals()
                for name in [
                    "residual_periods",
                    "residual_daily_profiles",
                    "scenario_prices_long",
                    "scenario_metadata",
                    "scenario_validation_summary",
                ]
            )
            plot_reload_used = False
            if not plot_inputs_ready or PLOT_RELOAD_RUN_DIR:
                plot_reload_used = maybe_reload_plot_artifacts()
            if plot_reload_used:
                display_markdown(
                    f"Reloaded saved scenario artifacts from `{plot_output_dir.parent}`. "
                    "You can rerun only the visual cells in this section."
                )
            elif "final_validation_bundle" in globals():
                period_quantiles = final_validation_bundle["period_quantiles"].copy()
            elif "period_quantiles" not in globals():
                raise RuntimeError(
                    "Plot inputs are not available. Run the scenario-generation cells first, "
                    "or set PLOT_RELOAD_RUN_DIR to a saved artifact directory."
                )

            target_scores = scenario_validation_summary[
                scenario_validation_summary["dataset_split"].astype(str) == target_split
            ].copy()
            default_variant_mask = target_scores["selected_as_default_variant"]
            if not pd.api.types.is_bool_dtype(default_variant_mask):
                default_variant_mask = default_variant_mask.astype(str).str.lower().eq("true")
            best_variants_per_candidate = target_scores[default_variant_mask].copy()
            if best_variants_per_candidate.empty:
                best_variants_per_candidate = target_scores.sort_values(
                    ["scenario_score", "candidate_label"], ascending=[False, True]
                ).groupby("candidate_key", dropna=False).head(1)

            default_candidate_key = str(
                best_variants_per_candidate.sort_values(["scenario_score", "candidate_label"], ascending=[False, True]).iloc[0]["candidate_key"]
            )
            """
        ),
        md(
            """
            ### Seasonal And Regime Day Grid

            The first day view focuses on interpretable operating regimes:
            - one objectively selected **typical winter** day
            - one objectively selected **typical summer** day
            - one **high-volatility** day
            - one **low-price** day

            These panels help separate seasonal structure from stress behaviour.
            """
        ),
        code(
            """
            representative_days = select_representative_days(
                residual_periods,
                candidate_key=default_candidate_key,
                dataset_split=target_split,
            )

            display(representative_days)
            plot_scenario_grid(
                scenario_prices_long,
                scenario_metadata,
                period_quantiles,
                candidate_variant_rows=best_variants_per_candidate[
                    ["candidate_key", "candidate_label", "scenario_variant"]
                ].to_dict(orient="records"),
                representative_days=representative_days,
                title="Seasonal and regime delivery-day scenario diagnostics",
                output_path=plot_output_dir / "seasonal_regime_day_grid.png",
            )
            """
        ),
        md(
            """
            ### Stress-Focused Plot Grid

            The next grid uses the same best scenario variant per selected candidate, but the columns are now **stress-relevant test days** selected objectively from the target split.

            The stress-day selection mirrors the protected stress logic:
            - worst daily underestimation
            - worst evening peak miss
            - worst daily max-price miss
            - worst top-3 expensive-hour miss
            - highest-spread day
            - strongest overestimation profile

            The selection still follows the metric ranking, but it now prefers an unused day when the same delivery day would otherwise appear repeatedly.

            This is useful because a scenario set can look acceptable on a typical day while still failing on the exact failure modes that matter most later in optimisation.
            """
        ),
        code(
            """
            stress_diagnostic_days = select_stress_diagnostic_days(
                residual_daily_profiles,
                candidate_key=default_candidate_key,
                dataset_split=target_split,
            )

            display(stress_diagnostic_days)
            plot_scenario_grid(
                scenario_prices_long,
                scenario_metadata,
                period_quantiles,
                candidate_variant_rows=best_variants_per_candidate[
                    ["candidate_key", "candidate_label", "scenario_variant"]
                ].to_dict(orient="records"),
                representative_days=stress_diagnostic_days,
                title="Stress-focused delivery-day scenario diagnostics",
                output_path=plot_output_dir / "stress_diagnostic_day_grid.png",
            )
            """
        ),
        md(
            """
            ### Weekly Scenario Pages

            The week view reuses the repo's objective case-week logic and then plots the selected week **day by day**.

            The categories kept here are:
            - typical winter week
            - typical summer week
            - high-volatility week
            - low-price week

            Each week is rendered as multiple pages when needed so the figure never exceeds three columns.
            """
        ),
        code(
            """
            selected_plot_weeks = select_plot_weeks_from_period_residuals(
                residual_periods,
                config=config,
            )

            display(selected_plot_weeks)
            for week_row in selected_plot_weeks.to_dict(orient="records"):
                week_days = build_week_day_rows(
                    residual_daily_profiles,
                    candidate_key=default_candidate_key,
                    dataset_split=target_split,
                    week_row=week_row,
                )
                if week_days.empty:
                    continue
                category_slug = str(week_row["category"])
                week_id = str(week_row["iso_week_id"])
                plot_scenario_grid(
                    scenario_prices_long,
                    scenario_metadata,
                    period_quantiles,
                    candidate_variant_rows=best_variants_per_candidate[
                        ["candidate_key", "candidate_label", "scenario_variant"]
                    ].to_dict(orient="records"),
                    representative_days=week_days,
                    title=f"Scenario week diagnostics: {category_slug.replace('_', ' ').title()} ({week_id})",
                    output_path=plot_output_dir / f"{category_slug}_{week_id}_scenario_week.png",
                )
            )
            """
        ),
        md(
            """
            ## 15. Scenario Reduction Placeholder / Light Implementation

            The notebook first creates raw daily scenarios and then reduces them to a smaller final set.

            Because the repo does not already depend on a dedicated k-medoids package, the current implementation keeps protected scenarios and then uses a lightweight representative-path fallback for the remaining stochastic paths. The probability mass of dropped stochastic paths is reassigned to the retained representatives so the reduced scenario set still sums to the intended total mass.

            This is a tractability step, not a final research claim about optimal scenario reduction.
            """
        ),
        code(
            """
            reduction_overview = (
                reduction_summary.groupby(["candidate_label", "scenario_variant", "dataset_split"], dropna=False)
                .agg(
                    avg_raw_scenarios=("raw_scenario_count", "mean"),
                    avg_final_scenarios=("final_scenario_count", "mean"),
                    avg_protected_retained=("protected_retained", "mean"),
                )
                .reset_index()
            )
            reduction_validation_compare = (
                raw_validation_bundle["summary"][
                    ["candidate_label", "scenario_variant", "dataset_split", "minmax_coverage", "p10_p90_coverage", "average_p10_p90_width"]
                ]
                .rename(
                    columns={
                        "minmax_coverage": "raw_minmax_coverage",
                        "p10_p90_coverage": "raw_p10_p90_coverage",
                        "average_p10_p90_width": "raw_average_p10_p90_width",
                    }
                )
                .merge(
                    final_validation_bundle["summary"][
                        ["candidate_label", "scenario_variant", "dataset_split", "minmax_coverage", "p10_p90_coverage", "average_p10_p90_width"]
                    ].rename(
                        columns={
                            "minmax_coverage": "final_minmax_coverage",
                            "p10_p90_coverage": "final_p10_p90_coverage",
                            "average_p10_p90_width": "final_average_p10_p90_width",
                        }
                    ),
                    on=["candidate_label", "scenario_variant", "dataset_split"],
                    how="left",
                )
                .sort_values(["dataset_split", "candidate_label", "scenario_variant"])
                .reset_index(drop=True)
            )

            display_markdown("### Reduction counts")
            display(reduction_overview)
            display_markdown("### Coverage and width before versus after reduction")
            display(reduction_validation_compare)
            """
        ),
        md(
            """
            ## 16. Save Outputs

            The saved outputs live under the repo's existing hourly DA notebook-artifact tree so they stay close to the deterministic forecasting artifacts they depend on.

            This keeps the scenario layer easy to inspect without modifying the upstream benchmark outputs.

            A retention policy is applied after saving:
            - keep the newest full run,
            - keep the best-scoring full run,
            - keep configuration and final evaluation files for all runs,
            - prune only the heavy regenerable tables and plots from older runs.
            """
        ),
        code(
            """
            candidate_selection_artifact = candidate_selection_summary.copy()
            scenario_validation_artifact = scenario_validation_summary.copy()
            period_quantiles_artifact = period_quantiles.copy() if "period_quantiles" in globals() else pd.DataFrame()
            seasonal_regime_days_artifact = representative_days.copy() if "representative_days" in globals() else pd.DataFrame()
            stress_diagnostic_days_artifact = stress_diagnostic_days.copy() if "stress_diagnostic_days" in globals() else pd.DataFrame()
            selected_plot_weeks_artifact = selected_plot_weeks.copy() if "selected_plot_weeks" in globals() else pd.DataFrame()

            residual_periods.to_csv(output_paths.output_dir / "residual_period_table.csv", index=False)
            residual_daily_profiles.to_csv(output_paths.output_dir / "residual_daily_profiles.csv", index=False)
            candidate_selection_artifact.to_csv(output_paths.output_dir / "candidate_selection_summary.csv", index=False)
            scenario_prices_long.to_csv(output_paths.output_dir / "scenario_prices_long.csv", index=False)
            scenario_metadata.to_csv(output_paths.output_dir / "scenario_metadata.csv", index=False)
            scenario_validation_artifact.to_csv(output_paths.output_dir / "scenario_validation_summary.csv", index=False)
            if not period_quantiles_artifact.empty:
                period_quantiles_artifact.to_csv(output_paths.output_dir / "scenario_period_quantiles.csv", index=False)
            if not seasonal_regime_days_artifact.empty:
                seasonal_regime_days_artifact.to_csv(output_paths.output_dir / "seasonal_regime_days.csv", index=False)
            if not stress_diagnostic_days_artifact.empty:
                stress_diagnostic_days_artifact.to_csv(output_paths.output_dir / "stress_diagnostic_days.csv", index=False)
            if not selected_plot_weeks_artifact.empty:
                selected_plot_weeks_artifact.to_csv(output_paths.output_dir / "selected_plot_weeks.csv", index=False)
            bank_logs.to_csv(output_paths.output_dir / "scenario_bank_logs.csv", index=False)
            reduction_summary.to_csv(output_paths.output_dir / "scenario_reduction_summary.csv", index=False)
            if not option_c_selected_settings.empty:
                option_c_selected_settings.to_csv(output_paths.output_dir / "option_c_applied_settings.csv", index=False)
            if not option_c_test_evaluation.empty:
                option_c_test_evaluation.to_csv(output_paths.output_dir / "option_c_test_evaluation.csv", index=False)

            scenario_generation_config_payload = {
                **SCENARIO_CONFIG,
                "selected_candidate_keys": [str(value) for value in selected_candidate_keys],
                "selected_candidate_labels": candidate_selection_summary[
                    candidate_selection_summary["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys])
                ]["candidate_label"].tolist(),
                "scenario_run_id": output_paths.scenario_run_id,
            }
            (output_paths.output_dir / "scenario_generation_config.json").write_text(
                json.dumps(scenario_generation_config_payload, indent=2, default=str),
                encoding="utf-8",
            )

            run_summary_payload = {
                "timestamp": pd.Timestamp.utcnow().isoformat(),
                "scenario_run_id": output_paths.scenario_run_id,
                "selected_candidates": candidate_selection_summary[
                    candidate_selection_summary["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys])
                ][["candidate_key", "candidate_label", "source_run_id", "rmae", "ranking_score"]].to_dict(orient="records"),
                "data_split_used_for_residual_calibration": calibration_split,
                "target_split_used_for_scenario_evaluation": target_split,
                "scenario_variants_generated": variant_plan["scenario_variant"].tolist(),
                "option_flags": {
                    "A_tail_enrichment": bool(SCENARIO_CONFIG["use_option_a_tail_enrichment"]),
                    "B_protected_stress": bool(SCENARIO_CONFIG["use_option_b_stress_scenarios"]),
                    "C_bias_correction": bool(SCENARIO_CONFIG["use_option_c_bias_correction"]),
                },
                "random_seed": int(SCENARIO_CONFIG["random_seed"]),
                "n_raw_scenarios": int(SCENARIO_CONFIG["n_raw_scenarios"]),
                "n_final_scenarios": int(SCENARIO_CONFIG["n_final_scenarios"]),
                "option_c_sweep_reference": None if latest_option_c_sweep_dir is None else str(latest_option_c_sweep_dir),
                "warnings": warnings_log,
                "missing_data_summary": missingness_table.to_dict(orient="records"),
                "key_validation_metrics": scenario_validation_artifact[
                    ["candidate_label", "scenario_variant", "scenario_score", "high_tail_miss_rate", "p10_p90_coverage", "average_p10_p90_width"]
                ].to_dict(orient="records"),
            }
            (output_paths.output_dir / "scenario_generation_run_summary.json").write_text(
                json.dumps(run_summary_payload, indent=2, default=str),
                encoding="utf-8",
            )

            retention_summary = apply_notebook_artifact_retention(
                output_paths.output_dir.parent,
                current_run_dir=output_paths.output_dir,
                keep_latest_n=1,
                keep_best_n=1,
            )
            (output_paths.output_dir / "artifact_retention_summary.json").write_text(
                json.dumps(retention_summary, indent=2, default=str),
                encoding="utf-8",
            )

            display_markdown("### Artifact retention summary")
            display(pd.DataFrame([retention_summary]))

            print(output_paths.output_dir)
            """
        ),
        md(
            """
            ## 16.5. Final Model Comparison And Scenario-Generation Conclusion

            The tables below compare:
            - the selected deterministic candidates themselves
            - the best scenario variant per candidate

            This is the notebook's evidence-based recommendation for the **next scenario-generation phase only**.

            Important caveat:
            - the best scenario generator is **not automatically** the best final bidding model
            - the later toy MILP and the full DA bidding MILP with CVaR still need to test that claim

            The scenario-variant score used here is intentionally simple and explicit:
            - `0.35 * (1 - high_tail_miss_rate)`
            - `0.10 * (1 - low_tail_miss_rate)`
            - `0.20 * average(p10-p90 coverage, p05-p95 coverage)`
            - `0.10 * sharpness_score`, where `sharpness_score = 1 / (1 + average_p10_p90_width / median_width)`
            - `0.15 * scenario_top3_expensive_recall`
            - `0.05 * scenario_top3_cheap_recall`
            - `0.05 * daily_max_p10_p90_coverage`
            - minus `0.01 * complexity_rank`

            If scores are close, the interpretation remains conservative and the simpler variant is preferred in the written conclusion.
            """
        ),
        code(
            """
            target_daily_profiles = residual_daily_profiles[
                residual_daily_profiles["dataset_split"].astype(str) == target_split
            ].copy()
            severity_summary = (
                target_daily_profiles.groupby(["candidate_key", "candidate_label"], dropna=False)
                .agg(
                    residual_underestimation_severity=("positive_residual_severity", "mean"),
                    residual_overestimation_severity=("overestimation_severity", "mean"),
                )
                .reset_index()
            )
            role_map = {row["candidate_key"]: row["selection_role"] for row in selected_role_table.to_dict(orient="records")}
            if len(selected_candidate_keys) == 1:
                role_map[str(selected_candidate_keys[0])] = "both"

            candidate_comparison = (
                candidate_selection_summary[
                    candidate_selection_summary["candidate_key"].astype(str).isin([str(value) for value in selected_candidate_keys])
                ]
                .merge(severity_summary, on=["candidate_key", "candidate_label"], how="left")
                .assign(selection_role=lambda frame: frame["candidate_key"].map(role_map).fillna("comparison_candidate"))
                .rename(
                    columns={
                        "candidate_key": "candidate_id",
                        "topk_expensive_recall": "top3_expensive_recall",
                        "topk_cheap_recall": "top3_cheap_recall",
                    }
                )
            )

            best_variants = scenario_validation_summary[
                (scenario_validation_summary["dataset_split"].astype(str) == target_split)
                & (scenario_validation_summary["selected_as_default_variant"])
            ].copy()
            recommendation_payload = build_final_recommendation(candidate_comparison, best_variants)

            final_scenario_model_comparison = best_variants[
                [
                    "candidate_label",
                    "scenario_variant",
                    "minmax_coverage",
                    "p10_p90_coverage",
                    "p05_p95_coverage",
                    "high_tail_miss_rate",
                    "low_tail_miss_rate",
                    "average_p10_p90_width",
                    "daily_max_abs_error",
                    "daily_spread_abs_error",
                    "scenario_top3_expensive_recall",
                    "scenario_top3_cheap_recall",
                    "scenario_score",
                    "selected_as_default_variant",
                ]
            ].copy()

            display_markdown("### Candidate-level comparison")
            display(candidate_comparison[
                [
                    "candidate_label",
                    "selection_role",
                    "mae",
                    "rmse",
                    "rmae",
                    "bias",
                    "top3_expensive_recall",
                    "top3_cheap_recall",
                    "ranking_score",
                    "risk_weighted_ranking_score",
                    "residual_underestimation_severity",
                    "residual_overestimation_severity",
                ]
            ])

            display_markdown("### Best scenario variant per candidate")
            display(final_scenario_model_comparison)

            (output_paths.output_dir / "final_scenario_model_comparison.csv").write_text(
                final_scenario_model_comparison.to_csv(index=False),
                encoding="utf-8",
            )
            (output_paths.output_dir / "final_scenario_recommendation.json").write_text(
                json.dumps(recommendation_payload, indent=2, default=str),
                encoding="utf-8",
            )

            deterministic_winner_label = str(
                candidate_selection_summary.loc[
                    candidate_selection_summary["selected_as_deterministic_winner"],
                    "candidate_label",
                ].iloc[0]
            )
            ranking_winner_label = str(
                candidate_selection_summary.loc[
                    candidate_selection_summary["selected_as_hour_ranking_winner"],
                    "candidate_label",
                ].iloc[0]
            )
            default_variant_row = best_variants.sort_values(["scenario_score", "candidate_label"], ascending=[False, True]).iloc[0]

            base_vs_options = scenario_validation_summary[
                scenario_validation_summary["dataset_split"].astype(str) == target_split
            ][["candidate_label", "scenario_variant", "scenario_score"]].copy()
            bias_rows = bias_correction_impact[bias_correction_impact["dataset_split"].astype(str) == target_split].copy()
            bias_note = (
                "Bias correction reduced out-of-sample MAE for at least one candidate."
                if not bias_rows.empty and (bias_rows["mae_change"] < 0).any()
                else "Bias correction did not clearly improve the out-of-sample MAE tables and should therefore be treated cautiously."
            )

            conclusion_lines = [
                "1. Which candidate gives better all-round deterministic accuracy?",
                f"   {deterministic_winner_label} is the deterministic winner on the notebook's selection slice.",
                "2. Which candidate gives better hour-ranking / bidding-relevant signal?",
                f"   {ranking_winner_label} has the strongest balanced top-3 hour-ranking score on the same slice.",
                "3. Which candidate produces better-calibrated scenarios?",
                f"   On the notebook's scenario score, {recommendation_payload['default_candidate']} is the strongest scenario candidate in this phase.",
                "4. Which scenario variant gives the best balance between coverage and sharpness?",
                f"   {default_variant_row['scenario_variant']} is the current best balance under the explicit scenario score used here.",
                "5. Do Options A, B, or C materially improve the scenario set?",
                "   The answer is mixed and should be read from the variant score table rather than assumed in advance.",
                "6. Is there evidence that bias correction helps, or does it risk overfitting?",
                f"   {bias_note}",
                "7. Which candidate + variant should be carried forward as the default for the next phase?",
                f"   {recommendation_payload['default_candidate']} with {recommendation_payload['default_scenario_variant']}.",
                "8. Which candidate + variant should be retained as a robustness / sensitivity case?",
                f"   {recommendation_payload['robustness_candidate']} with {recommendation_payload['robustness_scenario_variant']}.",
                "",
                "This is a scenario-generation conclusion only. The final bidding conclusion still depends on later toy-MILP and full DA MILP/CVaR testing.",
            ]
            display_markdown("\\n".join(conclusion_lines))
            """
        ),
        md(
            """
            ## 17. Final Methodological Summary And Next Steps

            ### 1. Multi-day hourly scenarios

            This notebook focuses on `D` only because that is the cleanest first validation target for scenario generation. Later work should extend this to multi-day hourly scenario blocks because inventory, operational buffers, and look-ahead behaviour depend on more than one day. When that extension happens, the right method is to sample **multi-day residual blocks**, not independent single-day residuals.

            ### 2. 15-minute scenarios

            The current implementation stays hourly because the hourly forecasting pipeline already exists and is methodologically fixed. The code is structured so that the period concept can later move from `24` to `96` periods per day. The preferred route is true 15-minute forecasting if enough clean data exists. Disaggregation from hourly scenarios is only a fallback.

            ### 3. Toy MILP with CVaR

            Before building the full steel-plant problem, the next operational checkpoint should be a small flexible-load toy MILP. Its purpose is to verify:
            - scenario input plumbing
            - probability handling
            - CVaR bookkeeping
            - whether protected stress scenarios behave as expected

            ### 4. Full DA bidding MILP with CVaR

            The final DA scenario generator will later feed a stochastic MILP in which expected cost and CVaR are traded off. That step is intentionally **not** implemented here. This notebook only delivers the scenario-generation and scenario-validation layer that the later optimization work needs.
            """
        ),
    ]

    return new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": "3.12",
            },
        },
    )


def main() -> None:
    notebook = build_notebook()
    NOTEBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTEBOOK_PATH.write_text(nbformat.writes(notebook), encoding="utf-8")
    print(f"Wrote {NOTEBOOK_PATH}")


if __name__ == "__main__":
    main()
