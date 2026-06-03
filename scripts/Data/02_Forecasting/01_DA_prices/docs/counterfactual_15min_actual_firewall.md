# Counterfactual 15-Minute Actual-Path Firewall

## Purpose

This repository now distinguishes three separate price objects:

1. Observed hourly actual DA prices.
2. Frozen synthetic 15-minute counterfactual actual prices.
3. Ex-ante 15-minute forecast or scenario prices.

The frozen synthetic 15-minute path exists because a full historical 15-minute DA year is not available for the official hourly test window. It is therefore a counterfactual market environment for later bidding analysis, not a historical truth series.

## Authoritative artifact

The authoritative downstream actual path is stored under:

`data/02_Forecasting/01_DA_prices/quarterhour_da/frozen_actual_paths/<version_id>/`

For the current methodology phase, the intended first thesis artifact is:

`canonical_v1`

The authoritative files inside that version directory are:

- `synthetic_actual_15min_canonical.csv`
- `synthetic_actual_15min_canonical.parquet`
- `synthetic_actual_15min_manifest.json`
- `synthetic_actual_15min_diagnostics.csv`
- `synthetic_actual_15min_diagnostics.json`
- `synthetic_actual_15min_hash.txt`

For thesis-grade reporting, the authoritative checksum is the CSV SHA-256 recorded in the manifest and repeated in the hash sidecar.

## Generation rule

The canonical actual path is generated from:

- observed hourly Dutch DA prices for the official hourly test period;
- the observed Dutch quarter-hour shape library constructed from the available real quarter-hour DA period;
- a pre-specified empirical within-hour sampler with a fixed random seed.

The canonical actual path is **not** generated from:

- hourly forecast outputs;
- 15-minute forecast outputs;
- optimisation outputs;
- downstream economic results.

## Selection rule

The main thesis path is the pre-specified `empirical_medium` variant, frozen as `canonical_v1`.

Other variants such as `low_volatility`, `high_volatility`, and `stress` may be retained only as future robustness hooks. They are not competing definitions of realized truth.

## Downstream contract

- Bidding and optimisation notebooks must load the frozen canonical actual path as read-only input.
- Forecast and scenario notebooks must write outputs to separate artifact roots.
- Evaluation notebooks must report the canonical version id and manifest hash used.
- Do not resolve the actual path through "latest run" logic for thesis results.
- Do not resolve realised 15-minute market truth through `find_latest_phase05_run()` or `find_latest_phase06_run()`.
- Legacy Phase 5/6 realised paths must be rejected in thesis-grade mode.

## Legacy exploratory path

The old Phase 5/6 combined workflow may remain in the repository for exploratory diagnostics and reproducibility. It is not an authorised realised-market-truth source for thesis-grade bidding or optimisation work because it packages realised and forecast-side artifacts too closely in one legacy flow.

## Version replacement rule

If `canonical_v1` is ever replaced by `canonical_v2`, downstream economic results must either:

- be rerun using `canonical_v2`; or
- remain explicitly labelled as results conditional on `canonical_v1`.

## Interpretation rule

Use the following interpretation:

> The 15-minute bidding results are conditional on one plausible, frozen counterfactual market environment.

Do not use the following interpretation:

> The 15-minute bidding results are a direct historical backtest against realized 15-minute DA prices for the official hourly test year.

## Limitation

The within-hour shape library is estimated from the observed Dutch quarter-hour DA period available in the repository and then projected onto the earlier official hourly test year. This is acceptable for a counterfactual study, but it must be described explicitly as such in the thesis.
