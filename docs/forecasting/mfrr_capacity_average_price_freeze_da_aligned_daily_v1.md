# mFRR Capacity Average Price Freeze DA-Aligned Daily V1

## 1. Scope
This note freezes the DA-aligned **average procurement price** forecasting layer for Dutch mFRR/IR capacity.

This freeze applies only to **17.1_BC average procurement price forecasting**.

It does **not** freeze or solve:
- accepted-offer threshold calibration;
- bid-ladder modelling;
- bid acceptance/rejection modelling;
- activation modelling;
- MILP export.

## 2. Data And Split
Target and market layer:
- target: `17.1_BC` average procurement price;
- unit: `EUR_per_MW_per_period`;
- granularity: daily x direction;
- `delivery_block_id = daily_full_day`;
- forecast timing assumption: incident-reserve capacity auction at `D-1 09:00 Europe/Amsterdam`, with the result assumed known before DAM closure.

Timing metadata correction:
Earlier mFRR capacity artifacts used `D-1 10:00 Europe/Amsterdam` as the assumed capacity-market cutoff. The market-rules reference confirms `D-1 09:00 Europe/Amsterdam` for Dutch incident-reserve capacity. The timing metadata audit found all feature surfaces safe under `D-1 09:00`; therefore this is a metadata-only correction and no feature, forecast, or scenario values were recomputed.

DA-aligned split:
- train: `2022-01-01` to `2023-09-30`;
- validation: `2023-10-01` to `2024-09-30`;
- test: `2024-10-01` to `2025-09-30`.

DA-aligned artifact confirmation:
- date range: `2022-01-01` to `2025-09-30`;
- split counts: train `1276`, validation `732`, test `730`.

## 3. Models Compared
### Naive7d
- `model_name`: `naive_lag_7d_same_direction`
- feature source: `endogenous_da_aligned_daily_v1`
- predictor family: weekly same-direction lag only
- setting: `point_forecast = avg_price_lag_7d_same_direction`
- runtime: `0.0082 s`
- role: primary benchmark

### Endogenous LEAR
- `model_name`: `lear_endogenous_da_aligned_daily_v1`
- feature source: `endogenous_da_aligned_daily_v1`
- predictor family: endogenous lag, rolling, spread, calendar, direction code
- selected setting: `lasso`, `alpha = 0.1`
- runtime: `0.8629 s`
- role: retained endogenous linear reference

### Endogenous XGBoost
- `model_name`: `xgboost_endogenous_da_aligned_daily_v1`
- feature source: `endogenous_da_aligned_daily_v1`
- predictor family: same endogenous family as LEAR
- selected setting: `xgboost`, `n_estimators = 200`, `max_depth = 2`, `learning_rate = 0.1`, `min_child_weight = 1`
- runtime: `1.7687 s`
- role: retained endogenous nonlinear reference

### Exogenous-Small LEAR
- `model_name`: `lear_exogenous_small_da_aligned_daily_v1`
- feature source: `endogenous_plus_small_exogenous_da_aligned_daily_v1`
- predictor family: endogenous family plus approved lagged DA price and week-ahead load summaries
- selected setting: `lasso`, `alpha = 0.1`
- runtime: `1.7468 s`
- role: transparent linear frontrunner

### Exogenous-Small XGBoost
- `model_name`: `xgboost_exogenous_small_da_aligned_daily_v1`
- feature source: `endogenous_plus_small_exogenous_da_aligned_daily_v1`
- predictor family: endogenous family plus approved lagged DA price and week-ahead load summaries
- selected setting: `xgboost`, `n_estimators = 200`, `max_depth = 2`, `learning_rate = 0.1`, `min_child_weight = 1`, `reg_lambda = 2.0`, `subsample = 0.9`, `colsample_bytree = 0.9`
- runtime: `0.2046 s`
- role: frontrunner advanced model

### ARIMAX Load-Only
- `model_name`: `arimax_load_da_aligned_daily_v1`
- feature source: `week_ahead_load_only_da_aligned_daily_v1`
- predictor family: week-ahead load exogenous variables only
- exogenous variables: `nl_week_ahead_load_daily_mean`, `nl_week_ahead_load_daily_peak`
- selected setting: `sarimax`, order `(1, 0, 0)`
- runtime: `43.6151 s`
- role: documented classical comparator, not selected

## 4. Frozen Model Roles
Frozen DA-aligned average-price model roles:
- primary benchmark: `naive_lag_7d_same_direction`
- frontrunner advanced model: `xgboost_exogenous_small_da_aligned_daily_v1`
- transparent frontrunner: `lear_exogenous_small_da_aligned_daily_v1`
- retained ablation/reference models:
  - `lear_endogenous_da_aligned_daily_v1`
  - `xgboost_endogenous_da_aligned_daily_v1`
- rejected classical comparator: `arimax_load_da_aligned_daily_v1`

## 5. Key Performance Table
| Model | Validation MAE | Validation RMSE | Validation Bias | Validation p90 AE | Test MAE | Test RMSE | Test Bias | Test p90 AE | Runtime (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Naive7d | 1.5128 | 3.6452 | -0.0059 | 3.1190 | 1.0340 | 1.6368 | 0.0215 | 2.6340 | 0.0082 |
| Endogenous LEAR | 1.2856 | 2.7852 | 0.1681 | 2.1218 | 1.0100 | 1.3215 | 0.2899 | 1.9844 | 0.8629 |
| Endogenous XGBoost | 1.3154 | 3.0545 | 0.2736 | 2.1494 | 0.9483 | 1.2553 | 0.2648 | 1.8732 | 1.7687 |
| Exogenous-Small LEAR | 1.2524 | 2.7863 | 0.0066 | 2.1200 | 0.9798 | 1.3142 | 0.1746 | 1.9882 | 1.7468 |
| Exogenous-Small XGBoost | 1.1475 | 2.8256 | -0.2115 | 2.0504 | 0.8583 | 1.1969 | 0.0315 | 1.8235 | 0.2046 |
| ARIMAX Load-Only | 1.5198 | 3.0830 | 0.1374 | 2.3910 | 1.1628 | 1.4201 | 0.4538 | 1.9432 | 43.6151 |

## 6. Direction And Tail Caveats
- Exogenous-small XGBoost improves strongly for **Down** relative to endogenous XGBoost, especially on the DA-aligned test period.
- Naive7d remains strong in some calm **Down** regimes and should remain the mandatory primary benchmark.
- ARIMAX load-only is competitive only in some **Up** cases and is weak for **Down**, especially on test.
- Spike evaluation is partial because not all split-direction combinations contain spikes under the train-p95 threshold definition.
- Bias remains important for pay-as-bid interpretation and later threshold calibration.

## 7. Methodological Interpretation
- Exogenous-small XGBoost wins the **average-price forecast layer** on DA-aligned validation and test MAE.
- Exogenous-small LEAR is retained because it is simpler, transparent, and consistently improves over endogenous LEAR.
- ARIMAX load-only is rejected as a final candidate because it is slower, warning-prone, and weaker overall, particularly for **Down**.
- Naive7d remains mandatory as the primary benchmark in all later reporting.

This freeze concerns only **17.1_BC average procurement price forecasting**. It does not solve accepted-offer thresholds, bid ladders, acceptance/rejection, activation probability, or activation revenue.

## 8. Next Layer
The next methodological layer is:
- `MFRR_CAPACITY_THRESHOLD_CALIBRATION_2025_DAILY_V1`

That next layer should use `12.3_F` to calibrate accepted-offer threshold and bid-ladder proxies, including:
- weighted accepted price;
- `p10/p25/p50/p75/p90` accepted price;
- max accepted price as threshold proxy;
- stack spread;
- offer count;
- direction;
- calibration/evaluation split.
