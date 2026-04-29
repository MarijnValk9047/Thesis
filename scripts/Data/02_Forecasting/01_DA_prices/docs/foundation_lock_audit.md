# Foundation Lock Audit

Date: 2026-04-18

Scope:
- active hourly DAM pipeline only
- FS0, FS1, and FS2 only
- verification, stabilization, and reporting only
- no feature-family evaluation implementation yet

## 1. Foundation status summary

Already solid:
- The active top-level notebook order is coherent and matches the standardized generator.
- FS0, FS1, and FS2 benchmark scripts all use the same shared rolling-origin evaluation pipeline.
- Shared benchmark artifacts are consistent across `naive_benchmark`, `lear_fs1_benchmark`, `xgboost_fs1_benchmark`, `fs1_model_comparison`, `lear_fs2_benchmark`, `xgboost_fs2_benchmark`, `prophet_benchmark`, and `model_comparison`.
- The endogenous feature foundation is reused consistently: downstream tabular models call `build_training_data(...)`, which rebuilds the same endogenous explicit feature pool from shared code.
- Daily walk-forward evaluation re-fits fixed model settings at each origin. No origin-level hyperparameter search is embedded in the walk-forward loop.
- `find_latest_run(...)` already protects reporting notebooks from incomplete newer runs by preferring the latest run folder that contains `run_summary.json`.

Fragile:
- The top-level notebook folder mixes generator-managed notebooks, protected notebooks, and reference notebooks. Before this audit, that ownership model was only implicit.
- The FS2 aggregate run label is the generic `model_comparison`, which is compatible with the current notebook flow but is semantically broad and may become ambiguous in later phases.
- Multiple incomplete `prophet_benchmark` directories exist on disk. Reporting is safe because `find_latest_run(...)` prefers the latest complete run, but the raw run directory list can still mislead manual inspection.
- The active tuning story is methodologically defined in policy tables, but actual tuned parameter selections are not yet surfaced in one compact benchmark-level artifact.

Missing:
- The saved `endogenous_explicit_features` run did not have `run_summary.json`, so it was not treated as a "complete" run by the shared latest-run logic.
- The notebook overview text did not explicitly tell the reader which notebooks are protected, which are generator-managed, or that regeneration can archive unmanaged top-level notebooks.
- At the time of the first audit pass, benchmark-level frozen model settings were not surfaced in one compact run artifact.

## 2. Active structure verification

Checked:
- `scripts/Data/02_Forecasting/01_DA_prices/generate_standardized_notebooks.py`
- top-level notebook folder contents under `notebooks/Data/02_Forecasting/01_DA_prices`
- protected notebook creation scripts

Found:
- Generator-managed active notebooks:
  - `00_pipeline_overview.ipynb`
  - `02_methodology_and_objective_weeks.ipynb`
  - `04_fs0_naive_models.ipynb`
  - `05_fs1_lear.ipynb`
  - `06_fs1_xgboost.ipynb`
  - `07_fs1_benchmark_and_comparison.ipynb`
  - `08_fs2_lear.ipynb`
  - `09_fs2_xgboost.ipynb`
  - `10_fs2_prophet.ipynb`
  - `11_fs2_benchmark_and_shortlisting.ipynb`
  - `12_feature_family_value_results.ipynb`
  - `13_final_conclusion_and_best_model.ipynb`
- Protected notebooks:
  - `01_da_prices_cleaning_walkthrough.ipynb`
  - `03_endogenous_explicit_features.ipynb`
- Generator-managed reference notebooks:
  - `90_active_stack_and_tuning_policy_reference.ipynb`
  - `91_fs3_feature_family_plan_reference.ipynb`
  - `92_fs4_huang_style_plan_reference.ipynb`
  - `93_execution_readiness_checklist_reference.ipynb`
  - `94_methodology_update_summary_reference.ipynb`
- The active notebook numbering and order in the generator match the actual top-level notebook set.
- No top-level active `.ipynb` files are currently orphaned outside the generator/protected scheme.
- Regeneration archives any other top-level `.ipynb` file not in the generator set or the protected set into `archive_pre_fs_order_layout`.

Why it matters:
- Later phases can safely extend the active notebook flow only if they either update the generator or add a notebook to the protected set. Otherwise regeneration can archive the new notebook.

Status:
- Safe for later phases after the ownership model is documented clearly.

## 3. Benchmark pipeline verification

Checked:
- `run_naive_benchmark.py`
- `run_lear_benchmark.py`
- `run_xgboost_benchmark.py`
- `run_prophet_benchmark.py`
- `run_model_comparison.py`
- latest saved run folders under `data/02_Forecasting/01_DA_prices/hourly_da/runs`

Found:
- FS0:
  - script: `run_naive_benchmark.py`
  - run label: `naive_benchmark`
  - reporters: `04_fs0_naive_models.ipynb`, plus downstream comparison notebooks
- FS1 LEAR:
  - script: `run_lear_benchmark.py --fs-level FS1`
  - run label: `lear_fs1_benchmark`
  - reporters: `05_fs1_lear.ipynb`, `07_fs1_benchmark_and_comparison.ipynb`
- FS1 XGBoost:
  - script: `run_xgboost_benchmark.py --fs-level FS1`
  - run label: `xgboost_fs1_benchmark`
  - reporters: `06_fs1_xgboost.ipynb`, `07_fs1_benchmark_and_comparison.ipynb`
- FS1 aggregate comparison:
  - script: `run_model_comparison.py --fs-level FS1`
  - run label: `fs1_model_comparison`
  - reporters: `07_fs1_benchmark_and_comparison.ipynb`
- FS2 LEAR:
  - script: `run_lear_benchmark.py --fs-level FS2`
  - run label: `lear_fs2_benchmark`
  - reporters: `08_fs2_lear.ipynb`, `11_fs2_benchmark_and_shortlisting.ipynb`
- FS2 XGBoost:
  - script: `run_xgboost_benchmark.py --fs-level FS2`
  - run label: `xgboost_fs2_benchmark`
  - reporters: `09_fs2_xgboost.ipynb`, `11_fs2_benchmark_and_shortlisting.ipynb`
- FS2 Prophet:
  - script: `run_prophet_benchmark.py`
  - run label: `prophet_benchmark`
  - reporters: `10_fs2_prophet.ipynb`, `11_fs2_benchmark_and_shortlisting.ipynb`
- FS2 aggregate comparison:
  - script: `run_model_comparison.py --fs-level FS2`
  - run label: `model_comparison`
  - reporters: `11_fs2_benchmark_and_shortlisting.ipynb`, `12_feature_family_value_results.ipynb`, `13_final_conclusion_and_best_model.ipynb`

Artifact consistency:
- Dedicated benchmark runs consistently write:
  - `config_snapshot.json`
  - `methodology_snapshot.json`
  - `tuning_policy_snapshot.json`
  - `timezone_audit.json`
  - `gap_summary.csv`
  - `gap_intervals.csv`
  - `split_summary.csv`
  - `origin_schedule.csv`
  - `predictions_long.parquet`
  - `origin_timing.csv`
  - `origin_timing_summary.csv`
  - `metrics_overall.csv`
  - `metrics_by_lead_day.csv`
  - `metrics_by_reporting_level.csv`
  - `diebold_mariano_results.csv`
  - `diebold_mariano_by_reporting_level.csv`
  - `model_settings_summary.csv`
  - `official_naive_reference.json`
  - `suite_models.json`
  - `run_summary.json`
- Aggregate comparison runs are similar but replace `origin_schedule.csv` with `source_runs.json`.

Why it matters:
- Phase 2 can rely on one shared benchmark artifact pattern rather than model-specific ad hoc storage.

Status:
- FS0/FS1/FS2 run-label and artifact conventions are coherent enough to build on.

Important note:
- As of 2026-04-18, the latest timestamped `prophet_benchmark` folder is `20260409_134701_prophet_benchmark`, but it is incomplete.
- The reporting notebooks correctly use `20260409_120309_prophet_benchmark` because `find_latest_run(...)` prefers the latest complete run with `run_summary.json`.

## 4. Data and feature foundation verification

Checked:
- `create_da_prices_cleaning_notebook.py`
- `scripts/Data/01_cleaning/day_ahead_prices_pipeline.py`
- `hourly_da/core/data_loading.py`
- `hourly_da/core/endogenous_features.py`
- `hourly_da/core/tabular.py`
- `run_endogenous_feature_diagnostics.py`

Found:
- Cleaning walkthrough:
  - The protected cleaning notebook documents the upstream cleaner and states that timestamps are already UTC in the raw XML inputs.
  - Downstream loading revalidates UTC parsing, duplicate handling, canonical-hourly alignment, and missingness through `load_and_validate_da_series(...)`, `audit_timezone_handling(...)`, and `handle_missing_da_prices(...)`.
  - Duplicate timestamps are resolved consistently by keeping the last non-missing price in original order.
  - Missing timestamps and missing observed values are made explicit on the canonical hourly UTC grid.
- Endogenous explicit feature foundation:
  - `03_endogenous_explicit_features.ipynb` is an inspection checkpoint, not a separate feature-definition branch.
  - The same feature code is reused downstream through `build_training_data(...)`.
  - Saved artifacts are reusable and transparent:
    - `validated_source_series.csv`
    - `endogenous_feature_matrix.csv`
    - `feature_catalog.csv`
    - `feature_missingness.csv`
    - `feature_row_loss.csv`
    - `feature_summary_statistics.csv`
    - `feature_target_correlations.csv`
    - `feature_correlation_matrix.csv`
    - `validation_window_preview.csv`
    - metadata JSON files
- Downstream consistency:
  - FS1 models use endogenous explicit features only.
  - FS2 models use the same endogenous base plus shared calendar features from `build_calendar_features(...)`.
  - No hidden divergence was found between the diagnostics notebook and the downstream tabular model input path.

Why it matters:
- Later phases can treat the endogenous feature pool as one shared foundation rather than reverse-engineering model-specific variants.

Status:
- Stable enough for later phases.

Foundation decision:
- The implemented endogenous feature pool is:
  - `lag_1`, `lag_2`, `lag_24`, `lag_25`, `lag_168`, `lag_169`
  - differences and rolling/block summaries derived from that compact pool
- In Phase 1.5, this implemented pool is frozen as the official benchmark foundation for the active repo.

## 5. Tuning foundation verification

Checked:
- `hourly_da/core/tuning.py`
- active benchmark scripts
- `hourly_da/core/evaluation.py`
- generator-produced notebook tuning sections

Found:
- Tuning policy is explicitly defined in `hourly_da/core/tuning.py` as stage-level methodology.
- The active benchmark scripts do not run automated hyperparameter search. They accept fixed hyperparameters from CLI arguments and pass those fixed settings into the rolling-origin benchmark.
- The walk-forward loop re-fits models per origin with frozen settings. It does not perform hidden origin-level retuning.
- No test-set tuning logic was found.
- The notebooks clearly state the intended policy through tuning placeholder tables.

What is now clearer after Phase 1.5:
- The notebooks still surface tuning policy and placeholder search regions as methodology guidance.
- The frozen settings used by each saved benchmark run are now surfaced in `model_settings_summary.csv`.
- Per-origin `runtime_info_json` remains available as a lower-level forensic trace, but later phases no longer need to reconstruct benchmark settings only from that field.

Why it matters:
- Phase 2 comparisons will need a cleaner way to reference which frozen settings were actually used for a given benchmark run.

Status:
- Methodologically safe for now.
- Do not change the tuning architecture in Phase 1.

## 6. Artifact and reporting consistency verification

Checked:
- notebook rerun hooks
- `find_latest_run(...)`
- `estimate_run_duration_seconds(...)`
- latest run folders for active labels

Found:
- `ALLOW_HEAVY_RERUN = False` is consistently used in generator-managed execution notebooks.
- Optional rerun cells estimate runtime using the latest comparable completed run when timing summaries exist.
- Reporting notebooks consistently load the latest saved artifacts through `find_latest_run(...)`.
- Aggregate comparison notebooks pull the correct upstream run labels for their stage.
- The current latest saved aggregate FS2 comparison run is `20260418_151115_model_comparison` and it points to:
  - `20260409_093045_naive_benchmark`
  - `20260409_102003_lear_fs2_benchmark`
  - `20260409_103625_xgboost_fs2_benchmark`
  - `20260409_120309_prophet_benchmark`

Why it matters:
- Later comparison phases need reproducible provenance from aggregate reporting back to the dedicated stage runs. The current `source_runs.json` pattern is good enough for that.

Status:
- Reporting consistency is good.

Resolved gaps:
- `endogenous_explicit_features` lacked `run_summary.json` before this audit, which made it the odd one out in the foundational run-folder set.
- Phase 1.5 adds `model_settings_summary.csv` to benchmark and aggregate comparison runs for run-level settings provenance.

## 7. Contradictions, gaps, and risk points

Contradictions:
- The notebook folder is presented as a single pipeline, but in practice it contains three ownership classes: protected, generator-managed active, and generator-managed reference.

Fragile assumptions:
- `model_comparison` is currently the FS2 aggregate label. If later phases introduce additional comparison layers, the generic label may become semantically overloaded.
- Incomplete run directories remain on disk after failed runs. Current reporting survives this because `find_latest_run(...)` filters by `run_summary.json`, but manual inspection can still be confusing.

Likely future blockers:
- Aggregate naming beyond FS2 should stay explicit once new comparison stages are added, otherwise the current generic FS2 label will become harder to interpret historically.

## 8. Safe locking changes made

1. Added `run_summary.json` support to `run_endogenous_feature_diagnostics.py`.
   - Why low-risk:
     - metadata only
     - no model behavior changes
     - aligns the foundational diagnostics run with the shared latest-run convention already used elsewhere

2. Backfilled `run_summary.json` into the current saved `20260408_153241_endogenous_explicit_features` run folder.
   - Why low-risk:
     - metadata only
     - no data or model outputs were altered
     - makes the current saved diagnostics artifact immediately discoverable as a complete run

3. Clarified notebook ownership and regeneration behavior in `generate_standardized_notebooks.py` and regenerated the standardized notebooks.
   - Why low-risk:
     - wording only
     - no benchmark logic changes
     - reduces future confusion about protected notebooks and regeneration archiving

4. Clarified notebook ownership and latest-complete-run behavior in `scripts/Data/02_Forecasting/01_DA_prices/README.md`.
   - Why low-risk:
     - documentation only
     - improves reproducibility and operator understanding

5. Phase 1.5 froze the implemented endogenous feature pool as the benchmark foundation in repo-facing methodology wording and added `model_settings_summary.csv` as a compact provenance artifact.
   - Why low-risk:
     - wording and metadata only
     - no model logic or run-label changes
     - improves later comparison reproducibility

## 9. Remaining unresolved issues before Phase 2

- Keep FS3 and FS4 out of scope until the FS0/FS1/FS2 foundation remains the sole active reporting universe.

Bottom line:
- The active FS0/FS1/FS2 foundation is trustworthy enough to build on.
- The main remaining issues are methodological clarity and provenance polish, not core structural instability.
