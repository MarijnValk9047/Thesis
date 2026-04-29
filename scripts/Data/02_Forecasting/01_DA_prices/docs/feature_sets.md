# Feature Set Policy

This note is the active DAM feature-set ladder for the repo.

## Active ladder

- `FS0`: seasonal naive benchmark only
- `FS1`: explicit endogenous feature foundation only
- `FS2`: `FS1` plus forecast-known calendar and holiday structure
- `FS3`: `FS2` plus causal exogenous feature families added gradually
- `FS4`: advanced engineered feature layer for finalists

## Active models by stage

- `FS0`: `naive_previous_week`, `naive_previous_year`
- `FS1`: `LEAR`, `XGBoost`
- `FS2`: `LEAR`, `XGBoost`, `Prophet`
- `FS3`: shortlisted survivors from `FS2`
- `FS4`: finalist models only

## Explicit endogenous foundation

`FS1` uses one compact pre-registered endogenous feature pool. The goal is to be explicit, causal, interpretable, and reusable later at `FS2+` without turning `FS1` into a giant lag buffet.

For the active repo, this implemented pool is also the frozen Phase 1 benchmark foundation. Later phases may extend or compare against it, but they should not silently reinterpret the benchmark lag pool.

The active `FS1` endogenous pool is:
- raw lags: `lag_1`, `lag_2`, `lag_24`, `lag_25`, `lag_168`, `lag_169`
- lag differences: `diff_1`, `diff_24`, `diff_168`, `cross_season_diff`
- rolling regime descriptors: `roll_mean_24`, `roll_std_24`, `roll_mean_168`, `roll_std_168`
- previous-day block summaries: `day_min_24`, `day_max_24`, `day_range_24`, `neg_share_24`
- comparable previous-week block summaries: `week_min_block`, `week_max_block`, `week_range_block`, `neg_share_week_block`

Why this pool is preferred:
- it covers short-memory persistence
- it keeps daily and weekly anchor structure explicit
- it adds compact momentum and regime-shift information
- it summarizes volatility, spread, and negative-price behavior without adding dozens of loosely justified lags
- it stays leakage-safe because every feature is built strictly from information available before timestamp `t`

## Calendar and holiday structure

`FS2` reuses the `FS1` endogenous foundation, then adds:
- hour of day
- day of week
- weekend flag
- month
- Dutch holiday flag

Important model-entry rule:
- Prophet does **not** belong to `FS1`
- Prophet enters only at `FS2`
- this is deliberate because Prophet becomes more meaningful once calendar and holiday structure is part of the design

## Exogenous expansion

External feature families are **not** part of `FS2`.

They enter only at `FS3`, after the cross-model shortlist at `FS2`, and they must satisfy explicit `known_at_utc` causality rules.

Current `FS3` design principles:
- add feature families gradually instead of creating one huge buffet
- compare families on the same shared rolling-origin pipeline
- retune when the feature set changes materially
- preserve coverage comparability and leakage control

## Advanced feature engineering

`FS4` is reserved for a later finalist stage:
- Huang-style similar-day features
- weighted similar-day summaries
- embedded selection or compact pruning

The likely primary `FS4` targets are:
- `XGBoost`
- possibly `LEAR`
- `Prophet` only if there is a strong reason and the regressor set remains compact and causal
