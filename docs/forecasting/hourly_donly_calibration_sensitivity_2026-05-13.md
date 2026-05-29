# Hourly D-only Scenario Calibration Sensitivity (Validation-only Selection)

## Scope
- Ran full hourly D-only scenario calibration sensitivity (24 configs).
- No forecasting model refit.
- No D+4 scenario generation.
- No full quarter-hour generation.
- No hydrogen optimizer run.

## Key output paths
- Calibration sweep root:  
  `data/02_Forecasting/01_DA_prices/scenario_evaluation/20260512_172558_hourly_donly_calibration_sensitivity`
- Calibration summary table:  
  `data/02_Forecasting/01_DA_prices/scenario_evaluation/20260512_172558_hourly_donly_calibration_sensitivity/calibration_sensitivity_summary.csv`
- Calibration leaderboard:  
  `data/02_Forecasting/01_DA_prices/scenario_evaluation/20260512_172558_hourly_donly_calibration_sensitivity/calibration_sensitivity_leaderboard.csv`
- Selected full hourly D-only run:  
  `data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260513_062946`
- Notebook 29 evaluation output:  
  `data/02_Forecasting/01_DA_prices/scenario_evaluation/20260513_102807`

## Files changed (implementation)
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/scenario_generation.py`
  - Added `residual_scale_factor` support in scenario assembly and bundle generation.
- `scripts/Data/02_Forecasting/01_DA_prices/run_hourly_scenario_generation_with_lear_strict.py`
  - Added CLI options: `--residual-scale-factor`, `--target-split-mode`.
  - Added raw snapshot outputs (no full raw path persistence):
    - `raw_scenario_period_quantiles.csv`
    - `raw_scenario_validation_summary.csv`
    - `raw_scenario_daily_shape_summary.csv`
    - `raw_scenario_tail_score_summary.csv`
  - Added metadata fields in config/run summary for calibration and snapshot policy.
- `scripts/Data/02_Forecasting/01_DA_prices/run_hourly_donly_calibration_sensitivity.py` (new)
  - Runs 24-config grid.
  - Computes weighted/unweighted diagnostics.
  - Computes decomposition/month/hour/regime, daily shape coverage, CVaR tail cardinality, compliance checks.
  - Selects recommended config on validation only and triggers one full D-only run.
  - Supports resume via `--resume-dir`.
- `scripts/Data/02_Forecasting/01_DA_prices/create_scenario_distribution_evaluation_notebook.py`
  - Weighted quantiles promoted to primary diagnostics.
  - Unweighted quantiles retained for comparison.
  - Added weighted-vs-unweighted summary output.
  - Added optional calibration summary CSV panel (`SCENARIO_CALIBRATION_SUMMARY_CSV`).
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/forecast_evaluation.py`
  - Reduced memory pressure in candidate prediction loading by selecting required columns only.
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/reporting.py`
  - CSV preferred before parquet in tabular artifact resolution.
- `notebooks/Data/02_Forecasting/01_DA_prices/29_scenario_distribution_evaluation_all_models.ipynb`
  - Regenerated from updated notebook builder.

## Calibration grid execution status
- Required grid: `2 x 3 x 4 = 24` configs.
- Succeeded: `24`
- Failed: `0`
- Failure log file:  
  `data/02_Forecasting/01_DA_prices/scenario_evaluation/20260512_172558_hourly_donly_calibration_sensitivity/calibration_failures.csv`

## Selected configuration (validation-only selection)
- `reduced_scenarios = 75`
- `protected_tail_share = 0.20`
- `residual_scale_factor = 1.30`
- `probability_policy = empirical_cluster_mass`
- `config_id = nfinal_75__tail_0p2__scale_1p3`

## Selected run checks
Run: `20260513_062946`
- `selection_split_used = validation`
- `test_used_for_selection = false`
- `calibration_policy = validation_only`
- `causal_source_filter_violations = 0`
- `scenario_probabilities_sum_to_one_per_group = pass`
- `random_seed_method = numpy_default_rng_fixed_seed`
- `raw snapshot policy = retain_diagnostic_snapshots_only_no_full_raw_paths`

## Comparison vs tail-aware v1 baseline (`20260512_134855`)
From:
`.../calibration_reference_runs_comparison.csv`

- Weighted p05-p95 coverage: `0.6564 -> 0.7101` (improved)
- Outside-spread frequency: `0.3266 -> 0.2798` (improved)
- p50 bias: `2.6012 -> 2.7123` (slightly worse)
- Average interval width: `49.6476 -> 64.1845` (wider)
- High-tail miss: `0.1581 -> 0.1333` (improved)
- Low-tail miss: `0.1855 -> 0.1567` (improved)
- Protected-tail probability mass mean: `0.0375` (selected config)
- CVaR tail cardinality avg (alpha=0.95): `8.08` (pass; >2)

## Notebook 29 execution note
- Direct Jupyter kernel execution (`nbconvert --execute`) failed in this environment due kernel startup timeout.
- Notebook logic was executed via generated script:
  `notebooks/Data/02_Forecasting/01_DA_prices/29_scenario_distribution_evaluation_all_models.txt`
- Produced standard scenario-evaluation artifacts under:
  `data/02_Forecasting/01_DA_prices/scenario_evaluation/20260513_102807`

## Readiness assessment
- Methodology compliant: **Yes** (P0/P1 guardrails preserved).
- Distributionally calibrated enough for thesis-final claims: **No**.
  - Coverage still far below 0.85-0.90 target.
- Tail-aware enough for exploratory CVaR experiments: **Yes, with caveats**.
- Ready for exploratory hydrogen CVaR test: **Yes (document limitations).**
- Ready for final thesis-level CVaR claims: **Not yet.**

## Remaining risks
1. Coverage remains under target even after full grid tuning.
2. Interval widening improves misses but may still be mis-centered in regime slices.
3. Candidate heterogeneity remains large (strict slice still undercovers strongly).
4. Old pre-fix comparison is partly constrained by artifact/schema differences for one reference row.

## Recommended next step
- Proceed with **exploratory** hydrogen CVaR testing using selected run `20260513_062946`.
- Treat results as sensitivity/prototyping only.
- Before final thesis claims, apply next methodology step beyond P0/P1 + scale tuning (e.g., regime-specific recentering or richer tail-mass calibration), then re-evaluate coverage and tails.
