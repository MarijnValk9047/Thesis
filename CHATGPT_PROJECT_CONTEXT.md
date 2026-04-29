# ChatGPT Project Context

## Purpose

This repository is a thesis workspace for electricity-market forecasting, but the active implementation scope is intentionally narrow:

- Only hourly day-ahead (DA) electricity price forecasting is in current scope.
- The active market focus is `NL`.
- Quarter-hourly DA, mFRR, probabilistic forecasting, optimizer integration, and economic backtesting are out of scope for the current workstream.

The standardized forecasting code lives under:

- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da`

## Top-Level Directory Map

- `AGENTS.md`
  - Project rules and thesis methodology constraints. Treat this as the governing instruction file.
- `data/`
  - Data lake for raw inputs, cleaned datasets, and forecasting outputs.
- `notebooks/`
  - Interpretation and experiment notebooks. Reusable logic should not live here.
- `scripts/`
  - Python pipelines for import, cleaning, forecasting, reporting, and plotting.
- `.venv/`, `.venv312/`
  - Local virtual environments.
- `.idea/`
  - IDE metadata.
- `.env`
  - Local environment settings.

## Data Directory Structure

- `data/00_Raw/`
  - Raw XML and source files.
  - Key families present now: `DA_Prices`, `Load`, `RES_Generation_Forecast`, `ENTSOE`.
- `data/01_cleaned/`
  - Cleaned, analysis-ready tables.
  - `Day_ahead_prices/`
    - Cleaned hourly and quarterly DA price tables plus diagnostics and plots.
  - `Load/`
    - Cleaned actual load, DA load forecast, and week-ahead load forecast families.
  - `Generation/`
    - Cleaned DA generation forecast, actual generation by PSR, and installed capacity by PSR.
  - `entsoe_feature_family_manifest.csv`
    - Manifest of cleaned external feature families and metadata.
- `data/02_Forecasting/01_DA_prices/hourly_da/`
  - Forecasting outputs from the standardized hourly DA pipeline.
  - `runs/`
    - Timestamped run folders with metrics, predictions, timing, plots, and JSON summaries.
  - `notebook_artifacts/`
    - Notebook-generated exports.
  - `archived_post_phase_b/`
    - Archived historical outputs.

## Notebook Structure

Main notebook path:

- `notebooks/Data/02_Forecasting/01_DA_prices/`

Important notebooks:

- `00_methodology_and_objective_weeks.ipynb`
- `01_fs0_naive_models.ipynb`
- `03_fs1_sarima.ipynb`
- `04_fs1_lear.ipynb`
- `05_fs1_xgboost.ipynb`
- `06_fs2_lear.ipynb`
- `07_fs2_xgboost.ipynb`
- `08_fs1_fs2_benchmark_comparison.ipynb`

Exploratory but not current active scope:

- `09_fs3_full_horizon_families.ipynb`
- `10_fs3_day1_branch.ipynb`
- `11_fs3_historical_families.ipynb`
- `12_fs3_promoted_combo_and_final_comparison.ipynb`
- `archive_pre_standardized_pipeline/`

Interpretation belongs in notebooks. Shared logic should stay in modules under `scripts/`.

## Pipeline Overview

The project has three main pipeline layers.

### 1. Raw Import

- `scripts/Data/00_data_imports/API_GETS.py`
  - Source acquisition helper.

### 2. Cleaning Pipelines

- `scripts/Data/01_cleaning/day_ahead_prices_pipeline.py`
  - Parses raw DA XML files.
  - Deduplicates timestamps.
  - Splits hourly and quarter-hourly data.
  - Writes cleaned DA tables and diagnostics to `data/01_cleaned/Day_ahead_prices/`.
- `scripts/Data/01_cleaning/entsoe_system_features_pipeline.py`
  - Parses ENTSO-E load, generation, and capacity families.
  - Computes `known_at_utc` for each family.
  - Aggregates to hourly resolution where needed.
  - Writes cleaned long and wide tables to `data/01_cleaned/Load/` and `data/01_cleaned/Generation/`.

### 3. Forecasting and Reporting Pipelines

Main runner folder:

- `scripts/Data/02_Forecasting/01_DA_prices/`

Important runners:

- `run_data_overview.py`
  - UTC audit, canonical hourly target grid, gaps, split summary, overview plot.
- `run_naive_benchmark.py`
  - Naive benchmark run.
- `run_sarima_benchmark.py`
  - SARIMA benchmark run.
- `run_lear_benchmark.py`
  - LEAR benchmark run.
- `run_xgboost_benchmark.py`
  - XGBoost benchmark run.
- `run_model_comparison.py`
  - Merges latest benchmark runs into one comparison run.
- `run_case_week_selection.py`
  - Objectively selects visual case-study weeks from test data only.
- `run_visual_case_weeks.py`
  - Produces stitched D-only operational plots for selected weeks.
- `run_gap_audit.py`
  - Gap diagnostics.

## Standardized Forecasting Package

Package root:

- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/`

### Core Modules

- `core/config.py`
  - Source of truth for split dates, timezone, forecast origin, horizon length, lags, and monitoring thresholds.
- `core/data_loading.py`
  - Loads cleaned hourly DA prices, verifies UTC parsing, builds a canonical hourly UTC grid, and summarizes gaps.
- `core/schedule.py`
  - Generates daily forecast origins and target schedules.
- `core/evaluation.py`
  - Shared walk-forward engine for all models.
- `core/metrics.py`
  - MAE, RMSE, bias, rMAE, and Diebold-Mariano tests.
- `core/storage.py`
  - Run-folder creation and CSV/JSON writing.
- `core/monitoring.py`
  - Fit-time monitoring and warning logic.
- `core/features.py`
  - Calendar-feature definitions.
- `core/tabular.py`
  - Shared tabular training matrix and recursive feature-row construction for LEAR and XGBoost.
- `core/external_features.py`
  - FS3 feature-store logic and `known_at_utc` masking.
- `core/visual_weeks.py`
  - Objective test-week selection and stitched forecast views.
- `core/reporting.py`
  - Latest-run discovery and reporting-level metadata.

### Model Modules

- `models/naive.py`
  - Previous-day, previous-week, and previous-year naive variants.
- `models/sarima.py`
  - Univariate SARIMA benchmark.
- `models/lear.py`
  - LASSO-based LEAR implementation using the shared tabular framework.
- `models/xgboost_model.py`
  - XGBoost implementation using the same tabular framework.

## Methodology and Setup

### Fixed Split Policy

Use these delivery-date splits:

- Train: `2022-01-01` to `2023-09-30`
- Validation: `2023-10-01` to `2024-09-30`
- Test: `2024-10-01` to `2025-09-30`

No random splits are used.

### Forecast Timing

The business problem is defined in market local time:

- Forecast origin: `08:00` on `D-1`
- Forecast horizon: `D` through `D+4`
- Evaluation style: daily rolling-origin refit

Internally, timestamps are stored in UTC.

Implementation detail:

- Origin dates and delivery dates are generated in `Europe/Amsterdam`.
- They are converted to UTC immediately for storage and evaluation.
- Reporting can convert back to local time.

### DST Handling

The horizon is a 5 local-delivery-day horizon, not a hard-coded 120-step horizon.

That means:

- Most origins produce 120 target hours.
- DST windows can produce 119 or 121 UTC target hours.

The code handles this in `core/schedule.py` and `core/time_utils.py`.

### Leakage Prevention

The core leakage-prevention rule is availability-based filtering:

- Every target or feature row has a `known_at_utc`.
- At forecast origin `t`, history is filtered with `known_at_utc <= t`.

For the DA target series, the current thesis assumption is:

- The full DA curve for local delivery day `t` is known from `t 08:00` local onward.
- Therefore, at forecast origin `D-1 08:00`, the full DA curve for day `D-1` is available.

This is implemented via:

- `core/data_loading.py`
- `core/time_utils.py`
- `core/evaluation.py`
- `core/external_features.py`

### Canonical Target Series and Gap Handling

The cleaned hourly DA series is UTC-correct but not fully gap-free.

The standardized pipeline therefore:

- Builds a canonical hourly UTC grid.
- Keeps missing target hours explicit in the observed target column.
- Scores metrics only where both `y_true` and `y_pred` exist.
- Creates a separate deterministic feature-source series by time interpolation plus edge fill for lag construction.

Important rule:

- Gap-filled values are used only for features.
- Evaluation always uses the observed target column, not the imputed feature-source column.

### Feature-Set Policy

- `FS0`
  - Naive baselines only.
- `FS1`
  - Lagged DA prices only.
- `FS2`
  - Lagged DA prices plus calendar features known at forecast time.
- `FS3`
  - Reserved by the thesis policy for later exogenous expansion.

Default lag set:

- `1, 2, 3, 24, 48, 72, 168`

Calendar features:

- Hour of day
- Day of week
- Weekend flag
- Month
- Dutch holiday flag

### Model Set

The active thesis comparison set is:

- Previous-week naive
- Previous-year naive
- SARIMA
- LEAR
- XGBoost

Current repository state is slightly broader and not perfectly aligned everywhere:

- `models/naive.py` contains previous-day, previous-week, and previous-year naive models.
- `run_naive_benchmark.py` still evaluates both `naive_previous_week` and `naive_previous_year`.
- Later benchmark suites now carry only `naive_previous_week`, the official naive benchmark candidate used in active model comparisons.
- LEAR and XGBoost are implemented in code, even though the local README in the forecasting folder is older and still says they are not yet implemented.
- FS3 code and notebooks exist, but active AGENTS scope still says FS3 is reserved for later expansion, not the main current comparison target.

Archived benchmark artifacts:

- `scripts/Data/02_Forecasting/01_DA_prices/archive/retired_models/run_arima_benchmark.py`
- `scripts/Data/02_Forecasting/01_DA_prices/archive/retired_models/hourly_da/models/arima.py`
- `notebooks/Data/02_Forecasting/01_DA_prices/archive_retired_models/02_fs1_arima.ipynb`

When modifying the repo, follow the active thesis policy in `AGENTS.md`, not the older README text.

### Shared Evaluation Logic

All comparable models should share:

- The same cleaned hourly target series
- The same split boundaries
- The same forecast-origin schedule
- The same horizon definition
- The same long-format storage schema
- The same metric definitions

This shared evaluation engine is in:

- `hourly_da/core/evaluation.py`
- `hourly_da/core/pipeline.py`

### Metrics

Always report:

- `MAE`
- `RMSE`
- `bias`
- `rMAE`

Also report:

- Diebold-Mariano tests where feasible

The code also computes `sMAPE`, but the thesis-required metrics above are the main ones.

### Official Naive Benchmark

The official naive benchmark is selected on validation performance, not test performance.

Current selection logic:

- Candidate naive models are compared on validation.
- Coverage thresholds are checked.
- The best feasible naive becomes the official reference for `rMAE`.

This happens in:

- `hourly_da/core/metrics.py`

## Run Outputs

Each forecasting run writes to:

- `data/02_Forecasting/01_DA_prices/hourly_da/runs/<run_id>/`

Typical artifacts:

- `config_snapshot.json`
- `timezone_audit.json`
- `gap_summary.csv`
- `gap_intervals.csv`
- `split_summary.csv`
- `origin_schedule.csv`
- `predictions_long.csv`
- `predictions_scored.csv`
- `origin_timing.csv`
- `origin_timing_summary.csv`
- `metrics_overall.csv`
- `metrics_by_lead_day.csv`
- `metrics_by_reporting_level.csv`
- `diebold_mariano_results.csv`
- `diebold_mariano_by_reporting_level.csv`
- `official_naive_reference.json`
- `run_summary.json`
- `plots/`

Key prediction columns include:

- `model`
- `fs_level`
- `dataset_split`
- `forecast_origin_utc`
- `target_timestamp_utc`
- `lead_day`
- `y_true`
- `y_pred`
- `fit_time_sec`
- `predict_time_sec`

## Runtime Monitoring

Daily refit is required.

The pipeline stores fit and predict time per forecast origin and raises warnings when fit time is unusually high:

- Above an absolute threshold
- Or above a relative multiple of the recent rolling median

See:

- `hourly_da/core/monitoring.py`

## Objective Visual Comparison

Visual case-study weeks are selected from test data only.

The code currently ranks and stores several categories, including:

- Typical winter
- Typical summer
- High volatility
- High price
- Low price
- Negative price

The thesis minimum requirement from `AGENTS.md` is at least:

- One typical winter week
- One typical summer week
- One high-volatility week

Selection is objective and coverage-filtered, implemented in:

- `hourly_da/core/visual_weeks.py`
- `run_case_week_selection.py`
- `run_visual_case_weeks.py`

## Dependencies

According to the local dependency notes:

- Already expected: `pandas`, `numpy`, `scipy`, `statsmodels`, `matplotlib`, `holidays`
- Needed for LEAR and XGBoost workflows: `scikit-learn`, `xgboost`

Before running LEAR or XGBoost, verify that those packages are installed in the active environment.

## How ChatGPT Should Work In This Repo

- Treat `AGENTS.md` as the active scope and methodology contract.
- Treat `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/config.py` as the main code-level source of truth for split dates, timezone, horizon, and lags.
- Prefer shared module edits over notebook-only fixes.
- Keep notebooks focused on interpretation and model-specific exposition.
- Preserve the shared evaluation pipeline so models stay directly comparable.
- Do not introduce leakage by using information that would not be known at the forecast origin.
- Keep timestamps in UTC internally.
- Archive outdated artifacts instead of deleting them blindly.

## Short Summary

If another ChatGPT session needs the minimum mental model, it is this:

- Raw ENTSO-E and DA data are cleaned into hourly UTC tables under `data/01_cleaned/`.
- The standardized hourly DA forecasting package in `scripts/.../hourly_da/` runs daily rolling-origin benchmarks for fixed train, validation, and test windows.
- Forecasts are issued at `D-1 08:00` local for `D` through `D+4`.
- All models share the same scheduling, storage, and metric logic.
- The main outputs are long-format forecast tables plus aggregate metrics and timing summaries under `data/02_Forecasting/.../runs/`.
- Active thesis scope is hourly DA only, even though the repo also contains older or exploratory FS3 material.
