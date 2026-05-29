# Hourly D-Only Tail Diagnostics (No Regeneration)

## Scope
- Input run inspected:
  - `data/02_Forecasting/01_DA_prices/hourly_da/notebook_artifacts/01_da_price_scenario_generation_hourly_with_lear_strict/20260512_134855`
- No scenario regeneration.
- No model refit.
- No calibration grid.
- No optimiser execution.

## Files inspected
- `scenario_generation_config.json`
- `scenario_generation_run_summary.json`
- `scenario_prices_long.csv`
- `scenario_metadata.csv`
- `scenario_reduction_summary.csv`
- `scenario_period_quantiles.csv`
- `scenario_validation_summary.csv`
- Notebook generator:
  - `scripts/Data/02_Forecasting/01_DA_prices/create_scenario_distribution_evaluation_notebook.py`

## Raw scenario artifact retention
- Raw bank artifacts were **not retained as path-level files** in this run directory.
- Checked and not found:
  - `raw_scenario_prices.csv`
  - `raw_scenario_prices.parquet`
  - `raw_scenarios.csv`
  - `scenario_raw_prices_long.csv`
  - `scenario_raw_metadata.csv`
- Therefore, direct raw-vs-reduced coverage comparison is **not possible** from persisted artifacts.

## Weighted vs unweighted quantiles
- Run uses `probability_policy = empirical_cluster_mass`.
- Notebook 29 quantile construction currently uses **unweighted** quantiles (`grouped["scenario_price"].quantile(...)`).
- Weighted diagnostics were computed directly from `scenario_prices_long.csv` probabilities.

### Weighted vs unweighted headline (new run)
- Overall mean coverage (`p05-p95`):
  - weighted: `0.7159`
  - unweighted: `0.7054`
  - delta: `+0.0105`
- Candidate-level deltas in coverage are modest (`+0.0046` to `+0.0197`).
- Conclusion: weighted/unweighted mismatch contributes, but does **not** explain the full undercoverage issue.

## Reduced-set diagnostics (weighted)
- `lear_fs3_combo_pruned_candidate`:
  - test coverage `0.7782`, validation `0.7757`
  - widths are moderate-to-wide (`71.38` test, `64.79` validation)
- `lear_strict_hourly_anchor_export`:
  - test coverage `0.7726`
  - validation coverage `0.5370` (severe undercoverage)
  - validation outside-spread frequency `0.4549` (very high)
  - validation interval width `34.51` (much narrower than test)
  - validation constant/near-constant scenario-price periods: `11.1%`

## Why coverage worsened (most likely causes)
1. **Model/split-local under-dispersion and mis-centering (LEAR strict validation)**
   - Validation has very narrow intervals and high miss rates on both tails.
2. **Regime-dependent mis-centering**
   - LEAR strict validation, low-price regime:
     - `below_p05_share = 0.465`
     - `p50_bias = +21.12` (distribution too high vs realized low prices)
   - High-price regime also misses above p95 (`0.322`), so both tails are stressed.
3. **Tail-protection probability trade-off**
   - Protected tail share by count is `20%`, but average protected probability mass per group is only `~2.5%` under empirical mass policy.
   - This keeps tails present for CVaR cardinality diagnostics, but does not materially widen central quantiles.
4. **Weighted/unweighted mismatch in notebook**
   - Present and measurable, but second-order relative to the validation under-dispersion issue.
5. **Reduction damage cannot be ruled in/out directly**
   - Raw paths were not persisted; direct before/after reduction coverage test unavailable.

## Recommended next action
- Keep methodology unchanged for now.
- Run a focused calibration sensitivity (as previously planned), but evaluate using **weighted diagnostics as primary**.
- Highest priority tuning dimensions:
  - residual scale expansion
  - reduced scenario count
  - protected-tail share
- Also persist raw path artifacts in next tuning runs to enable explicit raw-vs-reduced attribution.

## Is full calibration sensitivity still necessary?
- **Yes.**
- Current diagnostics identify likely causes, but without raw retention and without parameter sweep, a robust corrective configuration cannot be selected.

## Diagnostic artifact folder
- `data/02_Forecasting/01_DA_prices/scenario_evaluation/20260512_162411_hourly_tail_diagnostics`
  - `weighted_summary.csv`
  - `unweighted_summary.csv`
  - `weighted_vs_unweighted_summary.csv`
  - `decomposition_by_month_weighted_vs_unweighted.csv`
  - `decomposition_by_hour_weighted_vs_unweighted.csv`
  - `decomposition_by_regime_weighted_vs_unweighted.csv`
  - `reduction_profile_summary.csv`
  - `old_vs_new_weighted_summary.csv`
  - `diagnostic_report.json`

