from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook


NOTEBOOK_PATH = Path("notebooks/Data/02_Forecasting/01_DA_prices/03_endogenous_explicit_features.ipynb")


def md(text: str):
    return new_markdown_cell(dedent(text).strip())


def code(text: str):
    return new_code_cell(dedent(text).strip())


def build_notebook() -> nbformat.NotebookNode:
    cells = [
        md(
            """
            # 03 Endogenous Explicit Features

            This notebook is the downstream **endogenous explicit feature checkpoint** for the hourly day-ahead market (DAM) forecasting pipeline.

            It does **not** redo the raw cleaning stage from `01_da_prices_cleaning_walkthrough.ipynb`.

            Instead, it focuses on four downstream tasks:
            - validating the already-cleaned hourly DA price series carefully
            - making any remaining missing timestamps or missing values explicit on the canonical hourly UTC grid
            - building a separate **causal feature-source helper series** for lag-based feature engineering only
            - constructing the exact `FS1` endogenous explicit feature pool and its diagnostics before heavier model work starts

            Scope boundaries for this notebook:
            - only **hourly** DAM forecasting
            - no exogenous variables yet
            - no Prophet modeling yet
            - no heavy walk-forward benchmark yet
            - only a very light pipeline smoke test at the end

            Later benchmark scripts rebuild their own matrices internally, so this notebook is the transparent inspection checkpoint for the feature layer rather than the only place those matrices can be created.
            """
        ),
        code(
            """
            from datetime import timedelta
            from pathlib import Path
            import os
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

            PACKAGE_ROOT = REPO_ROOT / "scripts/Data/02_Forecasting/01_DA_prices"
            if str(PACKAGE_ROOT) not in sys.path:
                sys.path.append(str(PACKAGE_ROOT))

            from hourly_da.core.config import HourlyDAPipelineConfig
            from hourly_da.core.data_loading import (
                audit_timezone_handling,
                handle_missing_da_prices,
                load_and_validate_da_series,
            )
            from hourly_da.core.endogenous_features import (
                build_endogenous_explicit_features,
                endogenous_required_history_hours,
                summarize_feature_matrix,
            )
            from hourly_da.core.methodology import STARTER_ENDOGENOUS_FEATURE_NOTE, feature_stage_policy_frame
            from hourly_da.core.storage import create_run_directory, write_csv, write_json
            from hourly_da.core.tabular import build_training_data

            pd.set_option("display.max_columns", 200)
            pd.set_option("display.width", 220)
            plt.style.use("default")

            config = HourlyDAPipelineConfig(
                input_csv=REPO_ROOT / "data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv",
                raw_root=REPO_ROOT / "data/00_Raw/DA_Prices",
                cleaned_feature_root=REPO_ROOT / "data/01_cleaned",
                output_root=REPO_ROOT / "data/02_Forecasting/01_DA_prices/hourly_da",
            )

            SAVE_ARTIFACTS = True
            RUN_LABEL = "endogenous_explicit_features"
            DIAGNOSTIC_WINDOW_DAYS = 14


            def first_validation_window(frame: pd.DataFrame, window_days: int = 14) -> pd.DataFrame:
                if "target_delivery_local_date" not in frame.columns:
                    return frame.head(window_days * 24).copy()
                start_local = config.validation_start_local
                end_local = start_local + timedelta(days=window_days - 1)
                window = frame[frame["target_delivery_local_date"].between(start_local, end_local)].copy()
                if not window.empty:
                    return window
                return frame.head(window_days * 24).copy()


            def first_example_day(frame: pd.DataFrame) -> pd.DataFrame:
                if frame.empty:
                    return frame.copy()
                first_day = frame["target_delivery_local_date"].min()
                return frame[frame["target_delivery_local_date"] == first_day].copy()


            def display_markdown(text: str) -> None:
                display(Markdown(text))
            """
        ),
        md(
            """
            ## Notebook roadmap

            The notebook follows the same downstream logic that the later forecasting pipeline will rely on:

            1. load the cleaned hourly NL DA series
            2. re-audit chronology, duplicates, and missingness on that cleaned series
            3. build a complete hourly UTC grid
            4. create a **causal** feature-source helper series for lag-based feature construction only
            5. engineer the exact endogenous explicit feature pool
            6. inspect row loss, feature missingness, correlations, and intuitive plots
            7. save the feature dataset and metadata in the repo's existing run-artifact structure

            The key design principle is **no leakage**:
            - all timestamps are stored in UTC internally
            - every engineered feature at timestamp `t` uses only information strictly available before `t`
            - the helper-series fallback logic never uses future prices
            - the observed target column stays untouched, so missing targets remain visible instead of being hidden
            """
        ),
        code(
            """
            display_markdown(f"**FS1 foundation note.** {STARTER_ENDOGENOUS_FEATURE_NOTE}")
            display(
                feature_stage_policy_frame()
                .loc[lambda df: df["fs_level"].isin(["FS1", "FS2"])]
                .reset_index(drop=True)
            )
            """
        ),
        md(
            """
            ## Why this feature pool is deliberately compact

            A common first temptation in electricity price forecasting is to throw in a large buffet of lags such as:

            `1, 2, 3, 6, 12, 24, 48, 72, 96, 168, 336, ...`

            We are **not** doing that here.

            Instead, the feature pool is fixed in advance and chosen to represent four distinct roles:

            1. **Short-memory persistence**
               The most recent prices still matter.
            2. **Daily and weekly anchor structure**
               Electricity prices often depend on yesterday's and last week's comparable hours.
            3. **Recent momentum and regime shifts**
               Differences between seasonal anchors can reveal changing conditions.
            4. **Recent volatility, spread, and negative-price behaviour**
               A compact set of rolling and block summaries can capture whether the market has recently been calm, turbulent, or negative-price heavy.

            This notebook therefore builds one **pre-registered** endogenous feature pool that is compact, interpretable, and fair to reuse later in:
            - `FS1` for `LEAR` and `XGBoost`
            - `FS2`, where calendar and holiday features are added on top of the same base
            """
        ),
        md(
            """
            ## 1. Load and validate the hourly DA series

            We start from the existing cleaned hourly DA file for the Dutch market area (`NL`) produced upstream.

            Upstream cleaning already handled raw parsing, deduplication, DST treatment, and the missing-datapoint fix.

            Even so, we still re-check:
            - whether the timestamps parse as UTC
            - whether the rows are ordered chronologically
            - whether duplicate timestamps exist
            - whether expected hourly timestamps are missing
            - whether price values themselves are missing

            This is important because feature engineering is only trustworthy if the cleaned time axis itself is trustworthy.
            """
        ),
        code(
            """
            validation = load_and_validate_da_series(config)
            timezone_audit = audit_timezone_handling(config)
            missing = handle_missing_da_prices(validation.source_frame, config)
            feature_frame = build_endogenous_explicit_features(missing.canonical_frame, config)
            summary = summarize_feature_matrix(feature_frame, config)

            print("Validation and feature construction objects created successfully.")
            """
        ),
        code(
            """
            row_count_table = pd.DataFrame(
                [
                    {"stage": "Rows in input CSV", "rows": int(validation.integrity_summary.loc[0, "rows_in_input_csv"])},
                    {"stage": "Rows after NL market filter", "rows": int(validation.integrity_summary.loc[0, "rows_after_region_filter"])},
                    {
                        "stage": "Rows after timestamp parsing and duplicate resolution",
                        "rows": int(validation.integrity_summary.loc[0, "rows_after_duplicate_resolution"]),
                    },
                    {"stage": "Rows on canonical hourly UTC grid", "rows": int(missing.integrity_summary.loc[0, "rows_on_canonical_grid"])},
                ]
            )

            missing_policy_effect_table = missing.missing_policy_summary.copy()
            imputation_method_counts = (
                feature_frame["feature_source_imputation_method"]
                .value_counts(dropna=False)
                .rename_axis("feature_source_imputation_method")
                .reset_index(name="rows")
            )

            display_markdown("### Data integrity diagnostics")
            display(row_count_table)
            display(validation.integrity_summary)
            display(missing.integrity_summary)

            display_markdown("### UTC audit")
            display(pd.DataFrame([timezone_audit.to_dict()]))

            display_markdown("### Duplicate timestamp details")
            if validation.duplicate_details.empty:
                print("No duplicate timestamps were found in the cleaned hourly NL series.")
            else:
                display(validation.duplicate_details)

            display_markdown("### Missing-data policy summary")
            display(missing_policy_effect_table)

            display_markdown("### Feature-source imputation method counts")
            display(imputation_method_counts)

            display_markdown("### Largest explicit gap intervals on the canonical hourly grid")
            display(missing.gap_intervals.head(15))
            """
        ),
        md(
            """
            ### What these diagnostics mean

            A few points are worth emphasizing:

            - The **UTC audit** confirms that the source timestamps already enter as explicit UTC timestamps. That is important because it means we do not need to guess how to localize ambiguous DST times.
            - The **canonical hourly UTC grid** is the reference timeline for the whole feature pipeline. Any missing hour becomes an explicit row instead of silently disappearing.
            - The **observed target column** is intentionally kept untouched. If a DA price is truly missing, it remains missing in the target column.
            - The **feature-source series** is a separate helper series used only so lag-based features can still be built causally when historical observations are missing.
            - This notebook therefore does **not** repeat the upstream raw-data cleaning step. It only adds a leakage-safe helper layer on top of the cleaned target series.

            In other words:

            - `price_eur_per_mwh` is the truth we score against
            - `price_feature_source_eur_per_mwh` is the causal helper series we use for feature construction
            """
        ),
        md(
            """
            ## 2. Inspect the cleaned price series and the causal feature-source helper

            Before engineering features, it is useful to look at both the cleaned observed target and the helper series derived from it.

            We will inspect:
            - the full history
            - a zoomed-in window from the beginning of the validation period
            - the distribution of observed prices versus the causal feature-source series

            The selected zoom window is not hand-picked. It is simply the **first 14 local delivery days of the validation period**.
            """
        ),
        code(
            """
            validation_window = first_validation_window(feature_frame, window_days=DIAGNOSTIC_WINDOW_DAYS)

            fig, ax = plt.subplots(figsize=(18, 6))
            ax.plot(feature_frame[config.timestamp_col], feature_frame[config.target_col], linewidth=1.0, color="#183247", label="Observed target")
            ax.plot(
                feature_frame[config.timestamp_col],
                feature_frame[config.feature_source_col],
                linewidth=0.9,
                color="#8cbf9f",
                alpha=0.85,
                label="Feature source",
            )
            ax.set_title("Full-history hourly DA prices: observed target vs causal feature source", loc="left", fontweight="bold")
            ax.set_xlabel("Timestamp UTC")
            ax.set_ylabel("EUR/MWh")
            ax.grid(alpha=0.3)
            ax.legend()
            plt.show()
            """
        ),
        code(
            """
            fig, axes = plt.subplots(2, 1, figsize=(17, 10), sharex=False)

            axes[0].plot(validation_window["target_timestamp_local"], validation_window[config.target_col], color="#183247", linewidth=1.5, label="Observed target")
            axes[0].plot(
                validation_window["target_timestamp_local"],
                validation_window[config.feature_source_col],
                color="#8cbf9f",
                linewidth=1.3,
                alpha=0.9,
                label="Feature source",
            )
            axes[0].set_title("Zoomed validation window: observed target vs feature source", loc="left", fontweight="bold")
            axes[0].set_ylabel("EUR/MWh")
            axes[0].grid(alpha=0.3)
            axes[0].legend()

            observed = feature_frame[config.target_col].dropna().astype(float)
            cleaned = feature_frame[config.feature_source_col].dropna().astype(float)
            axes[1].hist(observed, bins=80, density=True, alpha=0.60, color="#5f8fbd", label="Observed target")
            axes[1].hist(cleaned, bins=80, density=True, alpha=0.45, color="#d88c8a", label="Feature source")
            axes[1].set_title("Observed distribution vs causal feature-source distribution", loc="left", fontweight="bold")
            axes[1].set_xlabel("EUR/MWh")
            axes[1].set_ylabel("Density")
            axes[1].grid(alpha=0.3)
            axes[1].legend()

            plt.tight_layout()
            plt.show()
            """
        ),
        md(
            """
            ### Interpreting the plots

            The full-history plot shows whether the causal feature-source series is behaving reasonably. In a good setup:

            - most of the time, the observed target and feature source lie on top of each other
            - the feature source deviates only where the observed target is missing
            - there is no suspicious smoothing caused by future-aware interpolation

            The distribution plot is also useful. If the causal helper series looked radically different from the observed series, that would be a warning sign. In practice, we expect only a small difference because the missing share is low and the fallback is used only where needed.
            """
        ),
        md(
            """
            ## 3. Build the exact endogenous explicit feature pool

            We now construct the feature pool for `FS1`.

            The exact design is:

            **A. Raw lag features**
            - `lag_1`, `lag_2`, `lag_24`, `lag_25`, `lag_168`, `lag_169`

            **B. Lag-difference / momentum features**
            - `diff_1 = y[t-1] - y[t-2]`
            - `diff_24 = y[t-24] - y[t-48]`
            - `diff_168 = y[t-168] - y[t-336]`
            - `cross_season_diff = y[t-24] - y[t-168]`

            **C. Strictly causal rolling regime descriptors**
            - `roll_mean_24`, `roll_std_24`, `roll_mean_168`, `roll_std_168`

            **D. Non-redundant block summary statistics**
            - previous-day block `[t-24, t-1]`: `day_min_24`, `day_max_24`, `day_range_24`, `neg_share_24`
            - comparable previous-week block `[t-168, t-145]`: `week_min_block`, `week_max_block`, `week_range_block`, `neg_share_week_block`
            """
        ),
        code(
            """
            theoretical_first_usable_timestamp = pd.Timestamp(summary.metadata_summary["theoretical_first_usable_timestamp_utc"])

            display_markdown("### Feature catalog")
            display(summary.feature_catalog)

            display_markdown("### Final feature matrix preview")
            preview_columns = [
                config.timestamp_col,
                "target_timestamp_local",
                config.target_col,
                config.feature_source_col,
                "feature_source_imputation_method",
                "lag_1",
                "lag_24",
                "lag_168",
                "diff_24",
                "cross_season_diff",
                "roll_mean_24",
                "roll_std_24",
                "day_range_24",
                "neg_share_24",
                "week_range_block",
                "neg_share_week_block",
                "has_all_endogenous_features",
                "is_usable_for_supervised_learning",
            ]
            display(feature_frame[preview_columns].head(15))

            display_markdown("### Missingness per feature")
            display(summary.missingness_table)

            display_markdown("### Row-loss summary")
            display(summary.row_loss_table)

            display_markdown("### Metadata summary")
            display(pd.DataFrame([summary.metadata_summary]))

            print(f"Theoretical first usable timestamp due to lag / window requirements: {theoretical_first_usable_timestamp.isoformat()}")
            print(f"Maximum required lookback hours: {endogenous_required_history_hours(config)}")
            """
        ),
        md(
            """
            ### Why the first usable timestamp is not the first timestamp in the file

            Some of the engineered features reach quite far back in time:

            - `diff_168` needs `y[t-336]`
            - `roll_mean_168` and `roll_std_168` need the previous 168 hours
            - the comparable previous-week block also depends on a full 24-hour block one week earlier

            This means that the first rows of the canonical series **cannot** yet have a complete feature vector. That is normal and expected.

            Importantly, the row-loss table makes this transparent rather than hiding it.
            """
        ),
        code(
            """
            example_day = first_example_day(validation_window)

            display_markdown("### Example rows for one selected day")
            example_columns = [
                config.timestamp_col,
                "target_timestamp_local",
                config.target_col,
                config.feature_source_col,
                "lag_1",
                "lag_2",
                "lag_24",
                "lag_168",
                "diff_1",
                "diff_24",
                "cross_season_diff",
                "roll_mean_24",
                "roll_std_24",
                "day_min_24",
                "day_max_24",
                "day_range_24",
                "neg_share_24",
                "week_min_block",
                "week_max_block",
                "week_range_block",
                "neg_share_week_block",
            ]
            display(example_day[example_columns].reset_index(drop=True))
            """
        ),
        md(
            """
            ### Why the example-day table is useful

            The example-day table makes feature engineering less abstract.

            Instead of only seeing formulas, you can inspect a concrete day and check whether:
            - `lag_24` really looks like “yesterday’s same hour”
            - the momentum features move in the expected direction
            - rolling means and rolling standard deviations look sensible
            - the block summaries are stable across all 24 rows of the selected day
            """
        ),
        md(
            """
            ## 4. Relationship diagnostics

            Once the feature matrix exists, we want to ask a few practical questions:

            - Which features are most strongly associated with the target?
            - Which features are highly redundant with each other?
            - Do the summary statistics look plausible?

            This does **not** mean we are already doing final model selection. It only means we are sanity-checking the feature space.
            """
        ),
        code(
            """
            display_markdown("### Correlation with the target")
            display(summary.feature_target_correlations)

            fig, axes = plt.subplots(1, 2, figsize=(20, 7))

            top_corr = summary.feature_target_correlations.head(12).copy()
            axes[0].barh(top_corr["feature_name"], top_corr["correlation_with_target"], color="#5f8fbd")
            axes[0].invert_yaxis()
            axes[0].set_title("Top absolute feature-target correlations", loc="left", fontweight="bold")
            axes[0].set_xlabel("Correlation with target")
            axes[0].grid(alpha=0.3, axis="x")

            heatmap = summary.feature_correlation_matrix.to_numpy(dtype=float)
            image = axes[1].imshow(heatmap, cmap="coolwarm", vmin=-1.0, vmax=1.0)
            axes[1].set_xticks(range(summary.feature_correlation_matrix.shape[1]))
            axes[1].set_xticklabels(summary.feature_correlation_matrix.columns, rotation=90, fontsize=8)
            axes[1].set_yticks(range(summary.feature_correlation_matrix.shape[0]))
            axes[1].set_yticklabels(summary.feature_correlation_matrix.index, fontsize=8)
            axes[1].set_title("Feature redundancy heatmap", loc="left", fontweight="bold")
            fig.colorbar(image, ax=axes[1], fraction=0.046, pad=0.04)

            plt.tight_layout()
            plt.show()

            display_markdown("### Summary statistics for all engineered features")
            display(summary.summary_statistics)
            """
        ),
        md(
            """
            ### How to read these diagnostics

            A few cautions are important:

            - High correlation with the target does **not** automatically mean a feature is “best”.
            - High correlation between two features does **not** automatically mean one must be deleted.
            - The purpose here is not premature feature pruning. It is simply to understand whether the feature design behaves sensibly.

            For example:

            - strong correlations for `lag_24` or `lag_168` are expected because hourly electricity prices often show clear daily and weekly structure
            - strong correlations among `day_min_24`, `day_max_24`, and `day_range_24` are also expected because they summarize the same recent block from different angles
            """
        ),
        md(
            """
            ## 5. Visual intuition plots

            Feature tables are precise, but plots make the features easier to understand intuitively.

            Below we focus on the same validation window and plot:
            - the target against `lag_24`
            - the target against `roll_mean_24` and `roll_mean_168`
            - daily range together with the recent negative-price share
            """
        ),
        code(
            """
            fig, axes = plt.subplots(3, 1, figsize=(18, 15), sharex=True)

            axes[0].plot(validation_window["target_timestamp_local"], validation_window[config.target_col], color="#183247", linewidth=1.6, label="Observed target")
            axes[0].plot(validation_window["target_timestamp_local"], validation_window["lag_24"], color="#d88c8a", linewidth=1.4, label="lag_24")
            axes[0].set_title("Target price and lag_24 over the selected validation window", loc="left", fontweight="bold")
            axes[0].set_ylabel("EUR/MWh")
            axes[0].grid(alpha=0.3)
            axes[0].legend()

            axes[1].plot(validation_window["target_timestamp_local"], validation_window[config.target_col], color="#183247", linewidth=1.6, label="Observed target")
            axes[1].plot(validation_window["target_timestamp_local"], validation_window["roll_mean_24"], color="#5f8fbd", linewidth=1.4, label="roll_mean_24")
            axes[1].plot(validation_window["target_timestamp_local"], validation_window["roll_mean_168"], color="#8cbf9f", linewidth=1.4, label="roll_mean_168")
            axes[1].set_title("Target price and rolling means", loc="left", fontweight="bold")
            axes[1].set_ylabel("EUR/MWh")
            axes[1].grid(alpha=0.3)
            axes[1].legend()

            axes[2].plot(validation_window["target_timestamp_local"], validation_window["day_range_24"], color="#d7b46a", linewidth=1.5, label="day_range_24")
            axes[2].plot(validation_window["target_timestamp_local"], validation_window["week_range_block"], color="#7fb8b2", linewidth=1.3, label="week_range_block")
            axes[2].plot(validation_window["target_timestamp_local"], validation_window["neg_share_24"] * validation_window["day_range_24"].max(), color="#7a8fa8", linewidth=1.2, label="neg_share_24 (scaled)")
            axes[2].set_title("Recent spread behaviour and negative-price regime signal", loc="left", fontweight="bold")
            axes[2].set_xlabel("Local timestamp")
            axes[2].set_ylabel("Mixed scale for intuition")
            axes[2].grid(alpha=0.3)
            axes[2].legend()

            plt.tight_layout()
            plt.show()
            """
        ),
        md(
            """
            ### What to look for in the intuition plots

            These plots are useful for answering practical questions such as:

            - Does `lag_24` visually move with the target when daily structure is strong?
            - Does `roll_mean_24` react more quickly than `roll_mean_168` when the price level shifts?
            - Do `day_range_24` and `neg_share_24` spike when the market becomes turbulent or enters a negative-price regime?

            If the plots looked random or internally inconsistent, that would be a warning sign that the feature engineering logic was wrong. Here, the purpose is to build confidence before moving on to actual FS1 model training.
            """
        ),
        md(
            """
            ## 6. Save the engineered feature dataset and summary artifacts

            The repo already uses timestamped run folders under:

            `data/02_Forecasting/01_DA_prices/hourly_da/runs/<run_id>/`

            To stay consistent with that convention, the notebook can save:
            - the final engineered feature matrix
            - metadata and audit summaries
            - the main diagnostic tables

            The cell below uses `SAVE_ARTIFACTS = True` by default because this stage is lightweight and fully reproducible.
            """
        ),
        code(
            """
            if SAVE_ARTIFACTS:
                run_id, run_dir = create_run_directory(config.output_root, RUN_LABEL)

                write_json(run_dir / "config_snapshot.json", config.to_json_dict())
                write_json(run_dir / "timezone_audit.json", timezone_audit.to_dict())
                write_json(run_dir / "feature_metadata_summary.json", summary.metadata_summary)

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
                write_csv(
                    run_dir / "feature_correlation_matrix.csv",
                    summary.feature_correlation_matrix.reset_index().rename(columns={"index": "feature_name"}),
                )
                write_csv(run_dir / "validation_window_preview.csv", validation_window)
                write_csv(run_dir / "example_day_feature_rows.csv", example_day)

                print(f"Artifacts saved to: {run_dir}")
            else:
                print("Artifact saving skipped because SAVE_ARTIFACTS is False.")
            """
        ),
        md(
            """
            ## 7. Very light smoke test

            We still avoid heavy model training here.

            However, it is useful to confirm that the engineered features can be handed over cleanly to the later tabular pipeline.

            The smoke test below only checks that:
            - an `FS1` training matrix can be built
            - an `FS2` training matrix can also be built from the same endogenous foundation plus calendar features

            No heavy benchmark is executed.
            """
        ),
        code(
            """
            train_history = feature_frame[feature_frame["target_delivery_local_date"] <= config.train_end_local].copy()

            fs1_training = build_training_data(
                history=train_history,
                config=config,
                fs_level="FS1",
                history_window_hours=24 * 90,
            )
            fs2_training = build_training_data(
                history=train_history,
                config=config,
                fs_level="FS2",
                history_window_hours=24 * 90,
            )

            smoke_test_table = pd.DataFrame(
                [
                    {
                        "fs_level": "FS1",
                        "rows": int(fs1_training.X.shape[0]),
                        "columns": int(fs1_training.X.shape[1]),
                        "first_feature_columns": ", ".join(fs1_training.feature_columns[:6]),
                    },
                    {
                        "fs_level": "FS2",
                        "rows": int(fs2_training.X.shape[0]),
                        "columns": int(fs2_training.X.shape[1]),
                        "first_feature_columns": ", ".join(fs2_training.feature_columns[:6]),
                    },
                ]
            )

            display(smoke_test_table)
            print("Smoke test completed. Feature matrices for FS1 and FS2 can be built successfully.")
            """
        ),
        md(
            """
            ## How this feeds into FS1 and FS2

            This notebook establishes the reusable endogenous foundation for the next forecasting stages.

            **For FS1**
            - `LEAR` and `XGBoost` will both use this exact endogenous explicit feature layer
            - no exogenous variables are added yet
            - this keeps the first model comparison fair and interpretable

            **For FS2**
            - the same endogenous explicit feature layer is reused
            - calendar and Dutch holiday features are added on top
            - `Prophet` enters only at this stage

            **For FS3 and FS4**
            - `FS3` will add causal exogenous feature families to this foundation
            - `FS4` can add advanced engineered features on top of the same leakage-safe base

            That is exactly why it is worth spending time here on chronology, missing-data handling, and transparent diagnostics first.
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
