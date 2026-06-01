# DA Forecasting Pipeline

This folder contains the thesis-aligned implementation for:

- audited hourly day-ahead electricity price forecasting; and
- the canonical observed-market quarter-hour / 15-minute deterministic DA forecast extension built on top of the audited hourly framework.

Current implemented scope:
- Hourly DA prices for `NL`
- Forecast origin at `08:00` on `D-1` in `Europe/Amsterdam`
- Forecast horizon `D` through `D+4`
- Daily rolling-origin evaluation
- Seasonal naive baselines, LEAR, XGBoost, and Prophet
- Quarter-hour deterministic DA forecasting for the observed post-transition Dutch 15-minute market period
- DA scenario-generation preparation through compatible deterministic hourly and quarter-hour artifacts

Active DAM ladder:
- `FS0`: seasonal naive previous-week, previous-year
- `FS1`: explicit endogenous feature foundation with `LEAR` and `XGBoost`
- `FS2`: `FS1` plus calendar and holiday structure, then `Prophet` joins
- `FS3`: causal exogenous families for the models shortlisted after `FS2`
- `FS4`: advanced engineered feature layer for finalists

Shortlisting and tuning:
- no shortlist after `FS1`
- first real shortlist after `FS2`
- tune by `FS` level on validation only, then freeze settings for that `FS`
- daily rolling-origin later re-fits the frozen configuration instead of re-running full search
- future `FS1`/`FS2` grouped-ablation runs should inherit the parent-stage tuned settings by default; full retuning per ablation run is not the default policy
- future ablation runs should inherit their `rMAE` denominator from the parent benchmark stage's `official_naive_reference.json`

Archived local-origin scaffold:
- [legacy_local_origin_scaffold](C:/Users/marijnvalk/PycharmProjects/Thesis/scripts/Data/02_Forecasting/01_DA_prices/archive/legacy_local_origin_scaffold)
- Retired classical benchmark artifacts are stored under [archive/retired_models](C:/Users/marijnvalk/PycharmProjects/Thesis/scripts/Data/02_Forecasting/01_DA_prices/archive/retired_models)

Main runners:
- `run_data_overview.py`
- `run_endogenous_feature_diagnostics.py`
- `run_naive_benchmark.py`
- `run_lear_benchmark.py --fs-level {FS1,FS2}`
- `run_xgboost_benchmark.py --fs-level {FS1,FS2}`
- `run_prophet_benchmark.py`
- `run_model_comparison.py --fs-level {FS1,FS2}`
- `run_feature_family_ablation.py --fs-level {FS1,FS2} --model-family {...}`
- `run_fs3_ordered_benchmarks.py --execution-mode {ordered,feature_value,all}`
- `run_15min_observed_deterministic_forecast.py`
- `run_15min_observed_deterministic_smoke_checks.py`
- `run_15min_canonical_v1_counterfactual_evaluation.py`
- `run_15min_canonical_v1_counterfactual_smoke_checks.py`

Quarter-hour deterministic path:
- package root: `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da`
- canonical observed-market runner: `quarterhour_da.observed_deterministic.run_observed_market_deterministic_forecast`
- canonical counterfactual full-year runner: `quarterhour_da.counterfactual_canonical.run_canonical_v1_counterfactual_evaluation`
- official output root: `data/02_Forecasting/01_DA_prices/quarterhour_da/runs/<run_id>/`
- keep the existing `phase02/03/04/07` workflow as legacy/staging/diagnostic/downstream-support logic
- do not reuse `hourly_da.core.scenario_generation` test-preferred slice selection for quarter-hour model or benchmark selection
- score quarter-hour evaluation on observed targets only; interpolated or flagged target rows keep `y_true = NaN`
- keep the canonical_v1 full-year benchmark clearly separated from observed-market 15-minute accuracy claims

Active execution shape:
- each model and feature-set layer runs in its own dedicated benchmark artifact
- `LEAR` and `XGBoost` no longer produce `FS1` and `FS2` together in one shared family run
- `FS1` aggregation is built in `fs1_model_comparison`
- `FS2` aggregation is built in `model_comparison`
- keep the current `model_comparison` FS2 label unchanged for compatibility with the active notebooks and saved artifacts
- forward-looking rule: any new later aggregate comparison stages should use explicit stage labels such as `fs3_model_comparison` or `fs4_model_comparison`

Frozen benchmark feature foundation:
- the active repo currently freezes the implemented `FS1` endogenous pool as the benchmark foundation
- raw lag anchors: `lag_1`, `lag_2`, `lag_24`, `lag_25`, `lag_168`, `lag_169`
- plus lag differences, rolling regime descriptors, and block summaries from the shared endogenous feature code

Notebook ownership and regeneration:
- `generate_standardized_notebooks.py` is the source of truth for the generator-managed top-level notebooks
- `01_da_prices_cleaning_walkthrough.ipynb` and `03_endogenous_explicit_features.ipynb` are protected notebooks maintained by their own creation scripts
- reference notebooks live in the same folder but use the `90+` numbering and are not part of the active run order
- ad hoc top-level notebooks that are not generator-managed or protected can be archived on regeneration
- the active finish now uses `23_fs3_decision_relevant_forecast_evaluation.ipynb` as the final DA forecast assessment layer and `24_final_conclusion_and_best_model.ipynb` as the brief thesis wrap-up

Latest-run selection:
- notebook helpers use `find_latest_run(...)`
- this prefers the latest complete run folder that contains `run_summary.json`
- if a newer timestamped folder exists but is incomplete, the notebooks keep using the latest completed artifact set instead

Outputs are written under:
- `data/02_Forecasting/01_DA_prices/hourly_da/runs/<run_id>/`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/runs/<run_id>/`
- full retained benchmark runs keep `predictions_long.parquet`; `predictions_scored` is no longer persisted
- benchmark and aggregate comparison runs also write `model_settings_summary.csv` so the frozen settings used by each model are visible at run level
- benchmark and aggregate comparison `run_summary.json` files now also expose the effective policy snapshot and the parent-benchmark `rMAE` reference metadata contract for later ablation work
- feature-family ablation aggregate runs write `feature_family_value_summary.csv`, `feature_family_value_by_origin.csv`, `feature_family_value_by_reporting_level.csv`, `feature_family_value_metadata.json`, and `feature_family_parent_child_map.csv`
- Phase 5 FS3 feature-value runs also use the same aggregate artifact contract and are discoverable by the active feature-family reporting notebook when the aggregate set is complete
- older benchmark duplicates and exploratory runs are automatically reduced to light archives that keep metrics, plots, summaries, and parameter snapshots
- manual housekeeping is available via `run_storage_cleanup.py`

Phase 2 planning artifacts:
- future rolling-origin feature-value outputs should reserve names such as `feature_value_by_origin.csv`, `feature_value_by_reporting_level.csv`, and `feature_value_summary.csv`
- the current FS3 code-defined bundle inventory and live availability status can be regenerated with `run_fs3_taxonomy_inventory.py`

Not yet implemented in this workstream:
- mFRR forecasting
- probabilistic forecasting
- optimizer integration
