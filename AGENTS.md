# AGENTS.md

## Current scope
- Only implement **hourly Day-Ahead (DA) electricity price forecasting**
- Do **not** implement yet:
  - quarter-hourly DA forecasting
  - mFRR forecasting
  - probabilistic forecasting
  - optimizer integration
  - economic backtesting

## Fixed methodology
- Use this exact split:
  - Train: 2022-01-01 to 2023-09-30
  - Validation: 2023-10-01 to 2024-09-30
  - Test: 2024-10-01 to 2025-09-30
- Use **daily rolling-origin evaluation**
- Forecast origin: **08:00 on D-1**
- Forecast horizon: **D through D+4**
- No random splits
- No data leakage
- Do not tune on the final test set

## Time handling
- Store timestamps internally in **UTC**
- Explicitly verify whether source data is truly UTC
- Only convert to local time for reporting / visualization

## Current model set
Implement and compare only:
- previous-week naive
- previous-year naive
- LEAR
- XGBoost
- Prophet

## Baseline policy
- Run all seasonal naive baselines
- Choose the official naive benchmark based on **validation** performance
- Use that benchmark for relative metrics such as **rMAE**

## Feature-set policy
- FS0: naive only
- FS1: explicit endogenous features only
- FS2: FS1 + calendar / holiday features known at forecast time
- FS3: FS2 + causal exogenous feature families added gradually
- FS4: advanced engineered feature layer for finalists

Shortlisting:
- Do **not** shortlist after FS1
- The first real shortlist happens only after **FS2**

Frozen endogenous benchmark foundation for the active repo:
- Treat the currently implemented `FS1` endogenous pool as the Phase 1 benchmark source of truth until a later methodology phase explicitly changes it.

Implemented raw lag anchors in that frozen benchmark pool:
- 1, 2, 24, 25, 168, 169

Implemented endogenous pool also includes:
- lag differences: `diff_1`, `diff_24`, `diff_168`, `cross_season_diff`
- rolling regime descriptors: `roll_mean_24`, `roll_std_24`, `roll_mean_168`, `roll_std_168`
- previous-day block summaries: `day_min_24`, `day_max_24`, `day_range_24`, `neg_share_24`
- comparable previous-week block summaries: `week_min_block`, `week_max_block`, `week_range_block`, `neg_share_week_block`

Calendar features:
- hour of day
- day of week
- weekend flag
- month
- Dutch holiday flag

Active model ladder:
- FS0: seasonal naive previous-week, previous-year
- FS1: LEAR, XGBoost
- FS2: LEAR, XGBoost, Prophet
- FS3+: shortlisted survivors only

Tuning cadence:
- FS0: no tuning
- FS1: fast / coarse tuning only
- FS2: first serious tuning round
- FS3: mandatory retuning
- FS4: selective rigorous retuning for finalists only

Critical tuning rule:
- Tune by **FS level**, not by daily walk-forward origin
- Structural tuning happens on **validation** only
- Freeze chosen settings for that FS level
- Daily walk-forward later only re-fits / re-estimates without repeating full search every day

## Comparability rules
- Use one shared evaluation pipeline for all models
- Use the same split, horizon, metrics, and storage schema for all models
- If a model cannot use exactly the same features, explain the closest fair comparable setup

## Metrics
Always implement and report:
- MAE
- RMSE
- bias
- rMAE

Also include:
- Diebold-Mariano test where feasible

## Storage
Store forecasts in one shared long-format result table with at least:
- model
- fs_level
- dataset_split
- forecast_origin_utc
- target_timestamp_utc
- lead_day
- y_true
- y_pred
- fit_time_sec
- predict_time_sec

## Runtime monitoring
- Daily refit is required
- Store fit and predict time per forecast origin
- Warn if training time is much higher than expected

## Visual comparison
Use **test data only** to select:
- one typical winter week
- one typical summer week
- one high-volatility week

Selection must be objective, not hand-picked.

## Code structure
- Put reusable logic in shared modules
- Keep notebooks focused on interpretation and model-specific steps
- Inspect existing forecasting files before creating new ones
- Archive outdated artifacts instead of blindly deleting them

## Documentation style
- Be beginner-friendly
- Explain methodology, leakage prevention, tuning choices, and limitations clearly
- Prefer transparency and comparability over unnecessary complexity
