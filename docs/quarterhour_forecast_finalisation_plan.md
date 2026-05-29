# Quarter-Hour Forecast Finalisation Plan

Phase 0 repository audit only. This file maps the current repo state to the intended quarter-hour finalisation architecture. It does not authorize Phase 1+ implementation.

## 1. Current Quarter-Hour Pipeline Entry Points

Canonical observed-market deterministic path:

- Script runner: `scripts/Data/02_Forecasting/01_DA_prices/run_15min_observed_deterministic_forecast.py`
- Package entry point: `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/observed_deterministic.py`
- Latest observed deterministic run found:
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/runs/20260503_174631_observed_market_deterministic_forecast/`

Canonical counterfactual full-year path:

- Script runner: `scripts/Data/02_Forecasting/01_DA_prices/run_15min_canonical_v1_counterfactual_evaluation.py`
- Package entry point: `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/counterfactual_canonical.py`

Legacy / staging / diagnostic quarter-hour phases that must remain intact:

- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase01.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase02.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase03.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase04.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase05.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase06.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase07.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase07_upstream.py`

Existing generated quarter-hour notebook stack:

- Generator: `scripts/Data/02_Forecasting/01_DA_prices/create_da_15min_extension_notebooks.py`
- Output folder: `notebooks/Data/02_Forecasting/01_DA_prices/15min_extension/`
- Current notebooks are phase-oriented, not FS/model-comparison-oriented.

## 2. Current Canonical Inputs And Outputs

Observed deterministic canonical inputs:

- Quarter-hour actual source is resolved through Phase 1 authority and currently points to:
  - `data/01_cleaned/Day_ahead_prices/DA_prices/quarterly/da_prices_NL_quarterly.csv`
- Hourly backbone source root:
  - `data/02_Forecasting/01_DA_prices/hourly_da/`
- Internal methodology in current canonical observed run:
  - UTC internal timestamps
  - `08:00` on `D-1` forecast origin semantics inherited from hourly pipeline
  - `D..D+4` target horizon
  - observed-target-only scoring
  - ratio split by eligible origin: first 60%, next 20%, final 20%

Observed deterministic canonical outputs:

- Root:
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/runs/<run_id>/`
- Current artifact set includes:
  - `predictions_long.csv`
  - `metrics_overall.csv`
  - `metrics_by_reporting_level.csv`
  - `metrics_by_lead_day.csv`
  - `metrics_by_hour_of_day.csv`
  - `metrics_by_quarter_of_day.csv`
  - `origin_schedule.csv`
  - `split_summary.csv`
  - `observed_target_coverage_summary.csv`
  - `model_settings_summary.csv`
  - `official_naive_reference.json`
  - `feature_schema.json`
  - `scenario_generation_compatibility.json`
  - `run_summary.json`

Quarter-hour frozen / auxiliary roots already in repo:

- `data/02_Forecasting/01_DA_prices/quarterhour_da/canonical_actual_runs/`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/frozen_actual_paths/`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/phase01_runs/`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/phase02_runs/`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/phase03_runs/`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/phase04_runs/`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/phase05_runs/`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/phase06_runs/`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/phase07_runs/`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/phase07_upstream_refresh_runs/`

Important current distinction:

- `phase07_runs/...` contains realistic-track-a diagnostics with LEAR and XGBoost shape models.
- `runs/...observed_market_deterministic_forecast` is the canonical observed-market deterministic path used for official quarter-hour outputs.
- Latest observed deterministic canonical run currently uses:
  - hourly backbone selection from hourly artifacts on validation
  - benchmark family plus `mean_shape_deviation` and `xgboost_deviation`
  - no canonical LEAR candidate in the official observed deterministic run yet

## 3. Current Feature-Set Name(s)

Current quarter-hour feature-set names found in repo:

- `minimal_oracle_anchor_features_v1`
  - used in `phase04.py`
  - diagnostic/oracle-anchor setup
- `minimal_realistic_anchor_features_v1`
  - used in `phase07.py`
  - realistic end-to-end anchor setup

Current realistic quarter-hour feature content in `phase07.py` / saved `feature_column_summary.csv`:

- calendar dummies:
  - `hour_*`
  - `weekday_*`
  - `weekend_flag`
  - `month_*`
  - `quarter_*`
  - `season_*`
- anchor level:
  - `hourly_mean_eur_per_mwh`
  - `prev_hour_anchor`
  - `next_hour_anchor`
  - `daily_anchor_min`
  - `daily_anchor_mean`
  - `daily_anchor_max`
  - `daily_anchor_spread`
  - `daily_anchor_rank_pct`
- regime flags:
  - `high_price_anchor_flag`
  - `negative_anchor_flag`
  - `next_hour_missing_flag`
  - `prev_hour_missing_flag`
- ramp / shape descriptors:
  - `ramp_in`
  - `ramp_out`
  - `abs_ramp_in`
  - `abs_ramp_out`

Current gap:

- There is no central quarter-hour feature registry yet.
- There is no QH-FS0 / QH-FS1 / QH-FS2 / QH-FS3 registry artifact family yet.
- There is no feature-family map saved in machine-readable form for quarter-hour modeling.

## 4. Current Available LEAR And XGBoost Quarter-Hour Support

LEAR and XGBoost are both already implemented in quarter-hour legacy/staging logic:

- `phase04.py`
  - fits `lear_shape` and `xgboost_shape`
  - tunes on validation
  - saves `model_configuration_summary.csv`, `feature_column_summary.csv`, `tuning_results.csv`
  - anchor mode is diagnostic/oracle
- `phase07.py`
  - fits `lear_shape` and `xgboost_shape`
  - uses `minimal_realistic_anchor_features_v1`
  - runs for both selected hourly anchor candidates
  - saves `model_configuration_summary.csv`, `feature_column_summary.csv`, `recommended_model_summary.csv`

What is missing in the canonical observed deterministic path:

- `observed_deterministic.py` does not yet expose LEAR as an official canonical candidate.
- The official observed run writes:
  - FS0 benchmarks
  - `mean_shape_deviation`
  - `xgboost_deviation`
- That means LEAR is present in quarter-hour diagnostics, but not yet promoted into the canonical observed-market comparison suite.

Important architectural constraint for later phases:

- LEAR must be promoted as a first-class quarter-hour candidate through metadata and run outputs, not by inheriting the hourly winner role or by hardcoded candidate labels.

## 5. Existing Hourly Scripts And Notebooks To Reuse

Hourly reusable core modules:

- benchmark / evaluation pipeline:
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/pipeline.py`
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/evaluation.py`
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/metrics.py`
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/reporting.py`
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/storage.py`
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/schedule.py`
- endogenous / explicit feature foundations:
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/endogenous_features.py`
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/features.py`
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/feature_families.py`
- exogenous feature plumbing:
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/external_features.py`
- grouped ablation and parent-settings inheritance:
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/feature_value.py`
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/ablation_blocks.py`
- scenario generation:
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/scenario_generation.py`
- notebook/report helpers:
  - `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/notebook_support.py`

Hourly orchestration scripts to mirror conceptually:

- `scripts/Data/02_Forecasting/01_DA_prices/run_model_comparison.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_feature_family_ablation.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_fs3_ordered_benchmarks.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_lear_benchmark.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_xgboost_benchmark.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_prophet_benchmark.py`
- `scripts/Data/02_Forecasting/01_DA_prices/create_da_price_scenario_notebook.py`

Hourly notebooks to reuse as structural references:

- `notebooks/Data/02_Forecasting/01_DA_prices/03_endogenous_explicit_features.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/04_fs0_naive_models.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/05_fs1_lear.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/06_fs1_xgboost.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/07_fs1_benchmark_and_comparison.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/08_fs2_lear.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/09_fs2_xgboost.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/10_fs2_prophet.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/11_fs2_benchmark_and_shortlisting.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/12_fs2_lear_ablation.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/13_fs2_xgboost_ablation.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/14_fs2_feature_value_results.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/16_fs3_lear.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/17_fs3_xgboost.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/18_fs3_benchmark_and_comparison.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/19_fs3_lear_ablation.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/20_fs3_xgboost_ablation.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/21_fs3_feature_value_results.ipynb`
- `notebooks/Data/02_Forecasting/01_DA_prices/23_fs3_decision_relevant_forecast_evaluation.ipynb`
- `notebooks/Data/03_Scenario's/01_da_price_scenario_generation_hourly.ipynb`

Reuse conclusion:

- The hourly repo already contains the abstractions needed for:
  - benchmark aggregation,
  - validation-first benchmark selection,
  - grouped ablation with inherited parent settings,
  - scenario artifact discovery,
  - notebook reporting helpers.
- The missing work is mainly a quarter-hour adaptation layer, not a new framework.

## 6. Proposed New Notebook Order

Proposed new quarter-hour finalisation notebook folder:

- `notebooks/Data/02_Forecasting/01_DA_prices/quarterhour_da/`

Reason:

- keep the new finalisation stack separate from the existing `15min_extension/` phase notebooks
- avoid overwriting the current phase-oriented notebook story
- align naming with the intended final FS/model-comparison workflow

Proposed notebook order for later phases:

1. `01_qh_fs1_fs2_model_comparison.ipynb`
2. `02_qh_endogenous_feature_ablation.ipynb`
3. `03_qh_exogenous_feature_inclusion.ipynb`
4. `04_qh_exogenous_feature_ablation.ipynb`
5. `05_qh_final_model_comparison_and_selection.ipynb`
6. `06_qh_scenario_generation.ipynb`

Generator implication:

- either extend `create_da_15min_extension_notebooks.py` with a second notebook family, or add a separate quarter-hour-finalisation generator script
- do not fold these notebooks into the current `15min_extension/` sequence unless backward compatibility is explicitly required

## 7. Exact Output Directories

Current official quarter-hour deterministic output directory:

- `data/02_Forecasting/01_DA_prices/quarterhour_da/runs/<run_id>/`

Current hourly reusable output directory:

- `data/02_Forecasting/01_DA_prices/hourly_da/runs/<run_id>/`

Recommended new quarter-hour finalisation run roots for later phases:

- feature registry / metadata:
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/registry/`
- notebook-driven model comparison artifacts:
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/01_qh_fs1_fs2_model_comparison/<run_id>/`
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/02_qh_endogenous_feature_ablation/<run_id>/`
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/03_qh_exogenous_feature_inclusion/<run_id>/`
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/04_qh_exogenous_feature_ablation/<run_id>/`
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/05_qh_final_model_comparison_and_selection/<run_id>/`
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/06_qh_scenario_generation/<run_id>/`

Alternative lower-friction option:

- reuse the hourly-style `runs/<run_id>/` convention under a new quarter-hour subpackage label rather than phase folders, for example:
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/<timestamp>_<run_label>/`

Recommendation:

- prefer one dedicated quarter-hour finalisation root instead of writing these new artifacts into legacy `phase0x_runs/`
- keep canonical observed deterministic outputs in `quarterhour_da/runs/` unchanged

## 8. Missing Utilities That Need To Be Implemented Later

Not yet present in repo and required for the master-plan architecture:

1. Quarter-hour feature registry artifacts:
   - `quarterhour_feature_registry.csv`
   - `quarterhour_feature_family_map.csv`
   - `quarterhour_feature_set_summary.csv`
   - `quarterhour_feature_availability_check.csv`

2. Quarter-hour FS-layer metadata contract:
   - explicit `QH-FS0`, `QH-FS1`, `QH-FS2`, `QH-FS3`
   - mapping from current `minimal_realistic_anchor_features_v1` into `QH-FS1`

3. Canonical quarter-hour model comparison runner:
   - LEAR + XGBoost + QH-FS0 baselines in one comparable artifact set
   - machine-readable selection metadata

4. Quarter-hour grouped feature-family ablation runner:
   - likely a quarter-hour wrapper around hourly `feature_value.py` inheritance patterns
   - must work on quarter-hour families, not hourly lag families

5. Quarter-hour ranking / opportunity metrics utility:
   - top-k high hit rate
   - bottom-k low hit rate
   - extreme precision / recall / F1
   - daily Spearman rank correlation
   - mean rank error for actual extremes
   - tail MAE
   - high-low spread error

6. Quarter-hour exogenous feature integration layer:
   - must reuse hourly cleaned exogenous inputs
   - must express horizon-specific availability, especially D-only vs D+1..D+4

7. Quarter-hour scenario-generation module:
   - should reuse hourly scenario concepts
   - must preserve quarter-hour temporal dependence and use validation residuals

8. Quarter-hour selection / registry governance:
   - `selected_quarterhour_models.csv`
   - `quarterhour_model_selection_decision.json`
   - discoverable registry entry for deterministic model and scenario version

9. Generator support for the new notebook family:
   - either a separate generator script or an extension to the current notebook generator

## 9. Current Architectural Risks And Mismatches

1. Canonical observed deterministic path is not yet a LEAR vs XGBoost comparison stack.
   - official run currently exposes XGBoost only on the learned mixed-frequency side

2. Legacy phase07 anchor selection still carries user-facing candidate labels from hourly runs.
   - implementation later should rely on registry metadata and saved metrics, not thesis-facing hardcoded labels

3. There is no central quarter-hour feature family registry yet.
   - current feature grouping is implicit in code and saved summaries

4. Current quarter-hour notebooks are phase-driven.
   - final thesis comparison stack needs FS/model/ablation/scenario sequencing instead

5. Ranking/opportunity metrics required by the MILP use case are not yet first-class quarter-hour reporting artifacts.

6. Scenario-generation compatibility is declared in current observed deterministic outputs, but there is no dedicated quarter-hour final scenario-generation module yet.

7. The current canonical observed deterministic run selected hourly backbone `xgboost_fs2`.
   - this is valid for the current canonical path, but should not predetermine quarter-hour final model roles in later phases

## 10. Assumptions To Carry Into The Next Prompt

- Phase 0 is complete with this file only.
- Existing canonical observed deterministic outputs under `quarterhour_da/runs/` should remain unchanged unless a later phase explicitly replaces the official path.
- Existing `phase02/03/04/07` quarter-hour logic remains legacy/staging/diagnostic support.
- The first concrete implementation step after this audit should be the quarter-hour feature registry and FS-layer mapping, not model retraining.
- Full training, notebook end-to-end execution, and broad repo rescans should remain out of scope unless explicitly requested in the next prompt.

## Phase 1 Update

Completed Phase 1 work:

- Added a model-agnostic quarter-hour FS-layer registry utility:
  - `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/feature_registry.py`
- Exported the registry utility from:
  - `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/__init__.py`
- Registered:
  - `QH-FS0` as the explicit baseline-contract layer with no learned feature columns
  - `QH-FS1` as the active realistic feature layer mapped to `minimal_realistic_anchor_features_v1`
  - `QH-FS2` as an inactive placeholder for future endogenous or shape-history expansion
  - `QH-FS3` as an inactive placeholder for future exogenous expansion
- Wrote machine-readable registry artifacts under:
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/registry/`

Files changed:

- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/feature_registry.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/__init__.py`
- `docs/quarterhour_forecast_finalisation_plan.md`

Artifacts created:

- `data/02_Forecasting/01_DA_prices/quarterhour_da/registry/quarterhour_feature_registry.csv`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/registry/quarterhour_feature_family_map.csv`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/registry/quarterhour_feature_set_summary.csv`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/registry/quarterhour_feature_availability_check.csv`
- `data/02_Forecasting/01_DA_prices/quarterhour_da/registry/quarterhour_feature_registry.json`

Assumptions made:

- `minimal_realistic_anchor_features_v1` remains the authoritative active QH-FS1 feature layer for later LEAR and XGBoost comparison.
- The current QH-FS1 feature assembly is the shared phase04 `_build_feature_frame(...)` contract reused by phase07 realistic modeling.
- `QH-FS0` is represented explicitly as a baseline contract row with no learned feature columns rather than as a trainable feature set.
- `QH-FS2` and `QH-FS3` are documented now but remain inactive until their causal feature definitions and availability rules are implemented.
- `model_scope` defaults to `all_candidate_models` for active non-baseline quarter-hour layers.

Smoke checks run:

- registry loads
- QH-FS1 feature list matches the current known feature list
- no duplicate `(feature_set_id, feature_column)` rows
- every active non-placeholder feature has a feature family

Risks:

- QH-FS1 is registered from the current code-defined feature contract, not from a separate frozen historical registry source.
- The active registry captures feature-layer governance, but not yet per-model compatibility exceptions beyond the broad `model_scope` field.
- QH-FS2 and QH-FS3 remain placeholders; later phases must still define causal quarter-hour feature availability before those layers can become active.

Recommended next prompt:

- Implement Phase 2 only: create the quarter-hour FS1 or FS2 model-comparison notebook and its supporting non-training plumbing, reusing the new feature registry and keeping LEAR and XGBoost as equal candidate models without final model selection.

## Phase 2 Update

Completed Phase 2 work:

- Added a quarter-hour reporting utility for Phase 2 comparison scaffolding:
  - `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/reporting_metrics.py`
- Added a quarter-hour finalisation notebook generator:
  - `scripts/Data/02_Forecasting/01_DA_prices/create_qh_finalisation_notebooks.py`
- Exported the new reporting utility functions from:
  - `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/__init__.py`
- Generated the Phase 2 scaffold notebook:
  - `notebooks/Data/02_Forecasting/01_DA_prices/quarterhour_da/01_qh_fs1_fs2_model_comparison.ipynb`

What the new reporting utility supports:

- standard metrics:
  - MAE
  - RMSE
  - bias
  - existing reporting-level summaries through the shared hourly metric helpers
- ranking or opportunity metrics:
  - top-k high hit rate and miss rate
  - top-k low hit rate and miss rate
  - extreme precision, recall, and F1 at high and low quantiles
  - daily Spearman rank correlation
  - mean forecast-rank assigned to actual high and low extremes
  - tail MAE for top 10%, bottom 10%, and middle 80%
  - high-low spread error for `k = 4, 8, 16`

Files changed:

- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/reporting_metrics.py`
- `scripts/Data/02_Forecasting/01_DA_prices/create_qh_finalisation_notebooks.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_qh_fs1_model_comparison.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/__init__.py`
- `docs/quarterhour_forecast_finalisation_plan.md`

Artifacts created:

- `notebooks/Data/02_Forecasting/01_DA_prices/quarterhour_da/01_qh_fs1_fs2_model_comparison.ipynb`

Assumptions made:

- The current Phase 2 notebook remains a scaffold only and does not attempt to train LEAR or XGBoost.
- The smoke path uses the latest canonical observed deterministic quarter-hour artifact only as a schema and utility test surface.
- The current canonical `xgboost_deviation` path remains reference-only and is not treated as the quarter-hour winner.
- `QH-FS2` stays inactive in the registry, so the scaffold presents it as planned but not yet implemented.
- The existing realistic quarter-hour Track A run is the current heavy-run path for manual `QH-FS1` LEAR and XGBoost candidate generation, so the new CLI wrapper only aliases that logic and does not duplicate the pipeline.

Smoke checks run:

- imported the new quarter-hour reporting utility
- computed the Phase 2 reporting bundle on a small validation-only four-origin slice from the latest canonical observed deterministic run
- verified non-empty outputs for:
  - standard metrics
  - ranking metrics
  - Spearman summary
  - tail MAE summary
  - spread error summary
- generated the notebook file without executing it end to end
- verified that the notebook now contains:
  - `RUN_HEAVY = False`
  - explicit manual commands
  - expected output paths and files
  - saved-artifact loading cells after the manual run

Risks:

- The notebook scaffold currently demonstrates the reporting bundle on a small validation smoke slice to keep runtime controlled.
- The standard metric summaries still reuse the shared hourly reporting-level helper assumptions, so the later full Phase 2 implementation should confirm that the chosen reporting levels remain the right quarter-hour reporting contract.
- The current notebook scaffold does not yet persist Phase 2 output artifacts such as `ranking_opportunity_metrics.csv`; that belongs to the later full Phase 2 implementation.
- The manual heavy-run contract currently points to `phase07_runs`, which is still part of the legacy or staging naming scheme even though it is the right existing LEAR/XGBoost realistic path.

Recommended next prompt:

- Implement the remainder of Phase 2 only: add the non-training comparison-run plumbing and machine-readable artifact contract for QH-FS0 versus QH-FS1 and, if activated later, QH-FS2, while keeping LEAR and XGBoost as equal candidate models and still avoiding full training execution.

## Phase 2 Remainder Update

Completed Phase 2 remainder work:

- Added a non-training finalisation comparison bundle utility:
  - `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_comparison.py`
- Exported the finalisation bundle functions from:
  - `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/__init__.py`
- Updated the quarter-hour finalisation notebook generator so the Phase 2 notebook can:
  - show candidate inventory;
  - refresh a stable comparison bundle after the manual heavy run;
  - load the stable finalisation artifacts rather than reading raw `phase07` files directly;
  - expose smoke checks for schema validation and artifact writing.

What the new finalisation comparison bundle does:

- builds a candidate inventory for:
  - `QH-FS0` repeated-hourly backbone baseline
  - `QH-FS1` LEAR from `phase07`
  - `QH-FS1` XGBoost from `phase07`
  - canonical reference `xgboost_deviation`
  - `QH-FS2` placeholder
- normalises saved predictions into one stable long-format comparison table with:
  - source run IDs
  - model family
  - feature set ID
  - FS layer
  - candidate role
  - timestamps
  - split
  - frozen week fallback ID
  - actual and forecast price columns
- validates:
  - required columns present
  - no duplicate model or timestamp rows
  - aligned target timestamps
  - `feature_set_id` membership in the quarter-hour registry
  - explicit missing-candidate reporting
- writes a stable artifact bundle under:
  - `data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_runs/qh_fs1_fs2_model_comparison/<run_id>/`

Files changed:

- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_comparison.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/__init__.py`
- `scripts/Data/02_Forecasting/01_DA_prices/create_qh_finalisation_notebooks.py`
- `notebooks/Data/02_Forecasting/01_DA_prices/quarterhour_da/01_qh_fs1_fs2_model_comparison.ipynb`
- `docs/quarterhour_forecast_finalisation_plan.md`

Artifacts now produced by the stable Phase 2 finalisation bundle:

- `candidate_prediction_inventory.csv`
- `candidate_predictions_long.csv`
- `metrics_by_reporting_level.csv`
- `ranking_opportunity_metrics.csv`
- `metrics_by_frozen_week.csv`
- `residuals_by_quarter.csv`
- `model_settings_summary.csv`
- `run_summary.json`

Assumptions made:

- `phase07` remains the backend heavy-run source for `QH-FS1` LEAR and XGBoost candidates.
- The canonical observed deterministic run remains the source for:
  - `QH-FS0` repeated-hourly baseline
  - reference-only `xgboost_deviation`
- `QH-FS2` remains inactive and is therefore reported as a placeholder candidate instead of being backfilled with synthetic outputs.
- `phase07` saved outputs are normalized as comparison candidates but are not treated as canonical winners.

Smoke checks to run:

- load the latest saved `phase07` slice if available
- validate the normalized schema
- verify missing-candidate handling
- write the stable artifact contract in smoke mode only

Risks:

- `phase07` does not currently carry the same rolling-origin timestamp fields as the canonical observed deterministic path, so the normalized comparison bundle keeps `forecast_origin_utc` unavailable for those imported learned candidates.
- The Phase 2 stable bundle currently uses an ISO-week fallback for frozen-week IDs instead of a later curated frozen-week registry.
- `QH-FS0` is available only through the canonical repeated-hourly backbone path, not through `phase07`.

Recommended next prompt:

- Implement Phase 3 only: quarter-hour endogenous feature-family ablation scaffolding and artifact contract, reusing the stable Phase 2 comparison bundle and keeping LEAR and XGBoost symmetric.

## Phase 2 Review Update

Review findings on the completed Phase 2 bundle:

- The imported `phase07` learned `QH-FS1` candidates do not expose forecast-origin metadata or true `D..D+4` horizon metadata in `predictions_long.csv`.
- Those learned candidates must therefore be treated as source-scoped `D-only` comparison candidates.
- When their full-horizon rows match their `D-only` rows exactly, that is now flagged explicitly rather than being left implicit in the metric tables.
- A common-sample table is now written so candidates can be compared only on the shared timestamp intersection instead of on unequal observation counts.
- A coverage diagnostic is now written by model, split, reporting level, horizon day, and candidate role.

Additional Phase 2 artifacts now produced:

- `common_sample_metrics_by_reporting_level.csv`
- `coverage_diagnostic_by_model.csv`
- `candidate_scope_warnings.csv`

Interpretation rule:

- Do not interpret imported `phase07` learned rows as full rolling-origin `D..D+4` candidates until a later source exposes true forecast-origin and horizon metadata for those learned predictions.

## Phase 2.6 Update

Completed Phase 2.6 work:

- Extended the realistic `phase07` hourly-anchor backend from the old hardcoded `D-only` schedule to a configurable rolling-origin horizon.
- Kept the old `D-only` helper path available for backward compatibility:
  - `_build_d_only_origin_schedule(...)`
  - `_build_d_only_target_schedule(...)`
  - `_run_hourly_d_only_extension(...)`
- Set the finalisation wrapper path to call `phase07` with `horizon_days = 5`, which corresponds to `D..D+4`.

Why `phase07` was previously D-only:

- The old realistic backend was explicitly built around:
  - `_build_d_only_origin_schedule(...)`
  - `_build_d_only_target_schedule(...)`
  - `_run_hourly_d_only_extension(...)`
- That means the saved hourly anchor layer only generated `lead_day = 0`.
- The realistic quarter-hour modeling table then inherited those `D-only` anchors.
- On top of that, the quarter-hour learned export dropped forecast-origin and horizon metadata before writing `predictions_long.csv`.

What was extended:

- Generalized the hourly origin schedule and hourly target schedule to support configurable `horizon_days`.
- Generalized the realistic hourly prediction loop to emit full rolling-origin hourly anchor predictions for all requested lead days.
- Updated realistic quarter-hour modeling so it preserves hourly-origin context instead of collapsing it to date-scoped rows.
- Updated quarter-hour learned export so `predictions_long.csv` can preserve:
  - `forecast_origin_utc`
  - `forecast_origin_local`
  - `lead_day`
  - `lead_day_label`
  - `horizon_index`
  - `target_timestamp_utc`
  - `target_timestamp_local`
- Updated zero-mean correction and hourly anchor enrichment helpers so they become origin-aware when multiple rolling origins share the same target hour.
- Updated the stable Phase 2 normaliser so a rerun `phase07` artifact with true horizon metadata will be recognized as a real rolling-origin `D..D+4` source rather than as `source_scoped_d_only`.

Files changed in Phase 2.6:

- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase07.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase04.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/phase05.py`
- `scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/finalisation_comparison.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_15min_qh_fs1_model_comparison.py`
- `docs/quarterhour_forecast_finalisation_plan.md`

Smoke checks run:

- generalized `phase07` target schedule emits lead days:
  - `0, 1, 2, 3, 4`
- quarter-hour learned export frame preserves:
  - `forecast_origin_utc`
  - `lead_day`
  - `lead_day_label`
  - `horizon_index`
  - target timestamp fields
- synthetic `phase07` artifact with `lead_day 0..4` is recognized by the finalisation normaliser as:
  - `rolling_origin_d_to_d_plus_4`
- existing duplicate-key validation still passes for the stable Phase 2 bundle

Heavy rerun requirement:

- Yes. The code path is now extended, but existing saved `phase07` runs were produced under the old `D-only` backend.
- To obtain true learned `QH-FS1` `D..D+4` candidates, `phase07` must be rerun manually.
- After that rerun, the stable Phase 2 finalisation bundle must be refreshed so it can ingest the new horizon-aware learned outputs.
