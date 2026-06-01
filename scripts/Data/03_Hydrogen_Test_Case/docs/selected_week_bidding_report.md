# Selected-Week Bidding Report

## Scope

This report summarises the selected-week hourly D-only DA-only stochastic bidding suite completed on May 16, 2026.

Important scope limits:

- risk-neutral stochastic bidding only
- hourly only
- D-only only
- no mFRR
- no quarter-hour
- no CVaR
- selected diagnostic weeks only, not a representative full-period backtest

## Three-model status

The selected-week suite implementation is ready for thesis-grade hourly artifacts, but the current three-model run is blocked by support mismatch:

- `hourly_lear_strict` valid delivery support: `2026-02-05` to `2026-04-29`
- `hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate` valid delivery support: `2023-10-05` to `2025-09-25`
- `hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate` valid delivery support: `2023-10-05` to `2025-09-25`

Because there is no common three-model delivery window, the completed selected-week suite uses the thesis-grade common-support pair:

1. `hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate`
2. `hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate`

## Selected weeks

| week_label | delivery window | reason |
|---|---|---|
| `high_volatility_week` | `2024-12-09` to `2024-12-15` | highest weekly actual-price standard deviation with complete common support |
| `stable_summer_week` | `2025-07-21` to `2025-07-27` | summer week with low realised volatility and complete common support |
| `stable_winter_week` | `2024-01-08` to `2024-01-14` | winter week with low realised volatility and complete common support |
| `low_price_week` | `2024-04-08` to `2024-04-14` | lowest weekly average realised DA price with complete common support |
| `tail_week` | `2024-11-04` to `2024-11-10` | extreme realised peak-price week with wide spread under complete common support |

## Validation summary

- artifact validator: `pass` for all three thesis-grade catalog entries
- selected-week suite hard validation checks on completed pair run: `0` fail rows
- stochastic and benchmark chains both executed with the same realised delivery days
- pay-as-cleared settlement and redispatch balance checks passed on all completed day runs

## Pair-run interpretation

Across the five diagnostic weeks, the LEAR FS3 and XGBoost hourly thesis-grade inputs both:

- cleared most submitted energy in low and stable weeks
- paid far less than the price-insensitive benchmark in low-price and stable weeks
- still showed strong uplift over the benchmark in the high-volatility and tail regimes
- differed meaningfully in high-volatility and winter conditions through clearing, rejected energy, and shortfall behaviour

The completed pair suite should be treated as:

- a valid thesis-grade **two-model** selected-week diagnostic comparison
- not yet a valid **three-model** thesis-grade selected-week comparison

## Output locations

- suite folder:
  - `scripts/Data/03_Hydrogen_Test_Case/runs/20260516_122310_hydrogen_phase6d_selected_week_real_scenarios/`
- notebook:
  - `scripts/Data/03_Hydrogen_Test_Case/notebooks/10_selected_week_model_comparison.ipynb`
