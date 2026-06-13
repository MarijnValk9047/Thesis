# mFRR Capacity Endogenous Freeze And Exogenous Audit Daily V1

## Scope
This note freezes the current daily endogenous NL mFRR/IR capacity forecasting state and records a narrow repo audit for known-at-safe exogenous feature candidates.

The current forecast timing assumption remains:
- mFRR forecast origin / cutoff: `D-1 10:00 Europe/Amsterdam`

This note does not approve any exogenous feature for use unless it is classified below as known-at safe for that cutoff.

## A. Endogenous Freeze Summary

### Frozen artifact set
Data artifacts:
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_target_daily_direction.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_endogenous_daily_direction.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_naive7d_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_lear_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_xgboost_daily_direction_long.csv`

Scripts:
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/run_mfrr_capacity_lear_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/run_mfrr_capacity_xgboost_daily_v1.py`

### Frozen modelling status
- Primary benchmark remains `naive_lag_7d_same_direction`.
- LEAR is the transparent linear endogenous comparator.
- XGBoost is the strongest advanced endogenous average-price model so far on validation and overall test aggregates, but it keeps a positive bias and does not beat `naive_lag_7d_same_direction` on calm `test | Down`.
- No final model decision should be frozen yet.

### Why no final model decision is made yet
- Current results forecast only `17.1_BC` average procurement price.
- They do not forecast accepted-offer ladders.
- They do not forecast accepted-threshold proxies.
- They do not solve pay-as-bid bidding asymmetry.
- The main advanced-model tradeoff is still unresolved:
  - XGBoost improves aggregate validation/test performance.
  - Naive7d remains hard to beat in calm weekly-structured regimes.
  - LEAR and XGBoost both show positive test bias that matters for later bidding interpretation.

## B. Exogenous Candidate Inventory

### Candidate 1: Lagged realised NL day-ahead price
- Path: `data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_NL_hourly.csv`
- Family: DA price
- Header summary: `region, timestamp_utc, price_eur_per_mwh, resolution, resolution_minutes, period_start_utc, period_end_utc, created_datetime_utc, ...`
- Timestamp fields found: `timestamp_utc`, `period_start_utc`, `period_end_utc`, `created_datetime_utc`
- Forecast-origin / known-at fields found: none explicit in this cleaned file
- Delivery fields found: hourly timestamp only; no explicit `known_at_utc`
- Scope: NL
- Granularity: hourly
- Coverage: starts at `2021-12-31 23:00:00+00:00`; full coverage not fully audited here
- Missingness: not audited here
- Feature-ready for daily mFRR joining: not directly daily-ready, but clean and simple to aggregate into prior-day / prior-week daily summaries

### Candidate 2: NL day-ahead total load forecast
- Path: `data/01_cleaned/Load/da_total_load_forecast/hourly/da_total_load_forecast_hourly_long.csv`
- Family: load forecast
- Header summary: `market, timestamp_utc, interval_end_utc, value_mw, family, target_delivery_local_date, target_hour_local, known_at_utc, known_at_rule, ...`
- Timestamp fields found: `timestamp_utc`, `interval_end_utc`
- Forecast-origin / known-at fields found: `known_at_utc`, `known_at_rule = day_ahead_local_08`
- Delivery fields found: `target_delivery_local_date`, `target_hour_local`
- Scope: NL available in a multi-market family
- Granularity: hourly
- Coverage: hourly summary shows `2022-01-01T00:00:00+00:00` to `2025-12-31T23:00:00+00:00`
- Missingness: hourly summary shows some missing values in the family; exact NL-only missingness not audited here
- Feature-ready for daily mFRR joining: close, but not safe yet for current mFRR timing

### Candidate 3: NL week-ahead total load forecast
- Path: `data/01_cleaned/Load/week_ahead_total_load_forecast/hourly/week_ahead_total_load_forecast_hourly_long.csv`
- Family: load forecast
- Header summary: `family, market, timestamp_utc, interval_end_utc, value_mw, ... target_delivery_local_date, target_hour_local, known_at_utc, known_at_rule`
- Timestamp fields found: `timestamp_utc`, `interval_end_utc`
- Forecast-origin / known-at fields found: `known_at_utc`, `known_at_rule = week_ahead_local_08`
- Delivery fields found: `target_delivery_local_date`, `target_hour_local`
- Scope: NL available in a multi-market family
- Granularity: hourly
- Coverage: hourly summary shows `2021-12-31T23:00:00+00:00` to `2025-12-31T22:00:00+00:00`
- Missingness: hourly summary reports zero missing values at family level
- Feature-ready for daily mFRR joining: yes, after simple daily aggregation and NL filtering

### Candidate 4: NL day-ahead generation forecast
- Path: `data/01_cleaned/Generation/da_generation_forecast/hourly/da_generation_forecast_hourly_long.csv`
- Family: generation forecast
- Header summary: `market, timestamp_utc, interval_end_utc, value_mw, family, target_delivery_local_date, target_hour_local, known_at_utc, known_at_rule, ...`
- Timestamp fields found: `timestamp_utc`, `interval_end_utc`
- Forecast-origin / known-at fields found: `known_at_utc`, `known_at_rule = day_ahead_local_08`
- Delivery fields found: `target_delivery_local_date`, `target_hour_local`
- Scope: NL available in a multi-market family
- Granularity: hourly
- Coverage: hourly summary shows `2022-01-01T00:00:00+00:00` to `2025-12-31T23:00:00+00:00`
- Missingness: hourly summary reports zero missing values at family level
- Feature-ready for daily mFRR joining: close, but not safe yet for current mFRR timing

### Candidate 5: Actual total load
- Path: `data/01_cleaned/Load/actual_total_load/hourly/actual_total_load_hourly_long.csv`
- Family: other / actual load
- Header summary: `market, timestamp_utc, interval_end_utc, value_mw, family, target_delivery_local_date, target_hour_local, known_at_utc, known_at_rule`
- Timestamp fields found: `timestamp_utc`, `interval_end_utc`
- Forecast-origin / known-at fields found: `known_at_utc`, `known_at_rule = actual_interval_end`
- Delivery fields found: `target_delivery_local_date`, `target_hour_local`
- Scope: NL available in a multi-market family
- Granularity: hourly
- Coverage: present in cleaned data
- Missingness: not audited here
- Feature-ready for daily mFRR joining: no for same-day exogenous use

### Candidate 6: Actual generation by PSR
- Path: `data/01_cleaned/Generation/actual_generation_by_psr/hourly/actual_generation_by_psr_hourly_long.csv`
- Family: other / actual generation by technology
- Header summary: `market, timestamp_utc, psr_type, psr_label, interval_end_utc, value_mw, family, target_delivery_local_date, target_hour_local, known_at_utc, known_at_rule`
- Timestamp fields found: `timestamp_utc`, `interval_end_utc`
- Forecast-origin / known-at fields found: `known_at_utc`, `known_at_rule = actual_interval_end`
- Delivery fields found: `target_delivery_local_date`, `target_hour_local`
- Scope: NL available in a multi-market family
- Granularity: hourly
- Coverage: present in cleaned data
- Missingness: not audited here
- Feature-ready for daily mFRR joining: no for same-day exogenous use

### Candidate 7: Installed capacity by PSR
- Path: `data/01_cleaned/Generation/installed_capacity_by_psr/hourly/installed_capacity_by_psr_hourly_long.csv`
- Family: other / structural capacity
- Header summary from metadata: installed capacity by PSR, validity-driven known-at
- Timestamp fields found in metadata and prior schema references: `timestamp_utc`, `interval_end_utc`
- Forecast-origin / known-at fields found: `known_at_rule = valid_from_utc`
- Delivery fields found: expected hourly delivery fields in cleaned hourly family
- Scope: NL available in a multi-market family
- Granularity: hourly
- Coverage: present in cleaned data
- Missingness: not audited here
- Feature-ready for daily mFRR joining: possible, but structural and low-frequency rather than core short-run market information

### Candidate 8: Existing DA forecast-output summaries
- Search result: no clear stable daily DA forecast summary artifact was found in the approved search surface that is already packaged as a small mFRR-ready input with explicit `forecast_origin_utc` and compact daily summary fields.
- Practical conclusion: existing DA forecasting outputs appear run-oriented rather than already normalised into a small exogenous daily join artifact for mFRR.

### Candidate 9: Residual load forecast
- Search result: docs mention residual-coverage diagnostics and causal filtering, but no ready cleaned residual-load daily/hourly feature artifact was found in the approved search surface for direct mFRR reuse.
- Practical conclusion: residual load is conceptually promising, but not currently present as a simple reusable exogenous artifact here.

### Candidate 10: Wind / solar forecast families
- Search result: no explicit cleaned NL wind-forecast or solar-forecast family was found in the approved search surface.
- Practical conclusion: not available as simple direct families in this audit scope.

## C. Known-at Classification

### ready_for_small_exogenous_v1
- `lagged realised NL day-ahead price`
  - rationale: strictly historical daily summaries can be computed from already cleaned hourly DA prices and are known before `D-1 10:00` when using only prior days
- `NL week-ahead total load forecast`
  - rationale: metadata marks it as `future_horizon_safe = True` with `known_at_rule = week_ahead_local_08`, which is comfortably before the current mFRR cutoff

### promising_but_needs_known_at_fix
- `installed_capacity_by_psr`
  - rationale: known-at appears safe (`valid_from_utc`), but this is a slow structural supply proxy and not obviously the first exogenous family to add to a daily average-price model

### available_but_not_known_at_safe
- `NL day-ahead total load forecast`
  - rationale: metadata explicitly marks it as not future-horizon safe under the current method; `known_at_rule = day_ahead_local_08` is too late for a `D-1 10:00` mFRR decision if used for delivery day D
- `NL day-ahead generation forecast`
  - rationale: same issue as above; available and well-structured, but not safely known before the current mFRR cutoff for day D

### available_but_wrong_granularity
- none found as the primary issue; the main candidate families are hourly and can be aggregated daily if otherwise safe

### unavailable_or_not_found
- `DA forecast daily summary artifact` already packaged for mFRR reuse
- `residual_load` forecast artifact ready for direct reuse
- explicit `wind_forecast` family
- explicit `solar_forecast` family

### reject_for_v1
- `actual_total_load`
  - rationale: historical-only (`known_at_rule = actual_interval_end`); too easy to misuse and not needed for the first exogenous pass
- `actual_generation_by_psr`
  - rationale: historical-only and would invite leakage confusion; keep out of v1
- any same-day realised DA/load/generation values
  - rationale: directly unsafe for the current mFRR timing

## D. Recommended Minimal Exogenous V1 Feature Set

Recommended first exogenous set should stay small and conservative.

### Recommended columns / families
1. `nl_da_price_daily_avg_lag_1d`
   - source family: cleaned NL hourly DA prices
   - rationale: strict historical lag, simple, decision-relevant, low leakage risk
2. `nl_da_price_daily_avg_lag_7d`
   - source family: cleaned NL hourly DA prices
   - rationale: preserves weekly structure consistent with the primary naive benchmark logic
3. `nl_week_ahead_load_daily_mean`
   - source family: `week_ahead_total_load_forecast`
   - rationale: explicitly future-horizon safe and already carries `known_at_utc`
4. `nl_week_ahead_load_daily_peak`
   - source family: `week_ahead_total_load_forecast`
   - rationale: keeps the added exogenous family small while adding one level and one shape proxy

### Optional fifth feature only if the previous four are clean
5. `nl_installed_capacity_selected_psr_level_or_total`
   - source family: `installed_capacity_by_psr`
   - rationale: only if a simple structural capacity proxy is easy to define without broad engineering

### Explicitly not recommended in the first exogenous pass
- all same-day DA load forecast values for delivery D
- all same-day DA generation forecast values for delivery D
- all actual load/generation values
- residual load until a safe forecast-based construction exists
- any 12.3_F-based features
- procured MW features
- broad cross-border feature sweeps

## E. Proposed Next Implementation Sequence

1. `MFRR_CAPACITY_FEATURES_EXOGENOUS_SMALL_DAILY_V1`
   - build one small exogenous-augmented feature table using only approved known-at-safe families
   - recommended starting set: lagged realised NL DA price + NL week-ahead load daily summaries

2. `MFRR_CAPACITY_LEAR_EXOGENOUS_SMALL_DAILY_V1`
   - rerun LEAR on endogenous + approved small exogenous set

3. `MFRR_CAPACITY_XGBOOST_EXOGENOUS_SMALL_DAILY_V1`
   - rerun XGBoost on endogenous + approved small exogenous set

4. `MFRR_CAPACITY_ARIMAX_LOAD_GENERATION_DAILY_V1`
   - only if load/generation forecast timing is later proven safe for the current mFRR cutoff or a differently timed setup is explicitly adopted

5. `MFRR_CAPACITY_THRESHOLD_CALIBRATION_2025_DAILY_V1`
   - after average-price exogenous testing, move to accepted-offer threshold calibration with `12.3_F`

## F. Scope Risks
- Leakage through realised delivery-day DA/load/generation values remains the main risk.
- `day_ahead_local_08` forecast families are not automatically safe for `D-1 10:00` mFRR use.
- Mixing DA forecast-origin conventions with the current mFRR cutoff without a strict known-at rule would invalidate comparisons.
- `12.3_F` should stay out of the average-price exogenous model phase.
- A broad feature sweep would likely overfit the current simple target.
- Test-set tuning remains a red flag.
- Creating a second parallel pipeline or root-level outputs would violate current repo governance.

## Safe Next Task
- `MFRR_CAPACITY_FEATURES_EXOGENOUS_SMALL_DAILY_V1`
- Scope should stay limited to:
  - lagged realised NL DA price summaries
  - NL week-ahead load daily mean / peak summaries
  - no same-day DA load/generation forecasts
  - no actual load/generation
  - no 12.3_F
