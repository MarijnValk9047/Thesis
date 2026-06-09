# mFRR Capacity 12.3.F Threshold Rule Selection Daily V1

## Scope
This note defines a threshold-rule selection policy for the Dutch IR/mFRR capacity accepted-threshold proxy layer.

This layer uses:
- the observed `12.3_F` accepted-offer threshold table;
- frozen average-price forecast anchors;
- additive markup rules calibrated on the `2025-01-07` to `2025-06-30` overlap.

It does not create scenarios, MILP exports, or full bid ladders. It does not infer rejected bids.

## Backtest Integrity
Backtest artifact checked:
- path: `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_threshold_calibration_backtest_daily_direction_long.csv`
- row count: `19224`
- date range: `2025-01-07` to `2025-09-30`
- split counts:
  - calibration: `12600`
  - evaluation: `6624`
- average-price anchors present:
  - `naive_lag_7d_same_direction`
  - `lear_exogenous_small_da_aligned_daily_v1`
  - `xgboost_exogenous_small_da_aligned_daily_v1`
- threshold proxies present:
  - `accepted_price_p75_eur_per_maw`
  - `accepted_price_p90_eur_per_maw`
  - `max_accepted_price_proxy_eur_per_maw`
- markup rules present:
  - `direction_median_markup`
  - `direction_p75_markup`
  - `direction_p90_markup`
  - `direction_daytype_median_markup`
- quality flags:
  - `ok`: `19188`
  - `threshold_source_extreme_price_flag`: `36`

Extreme source-row propagation:
- the flagged threshold-source row is `2025-01-07`, `Up`;
- it appears only in calibration-expanded rows;
- there are no flagged evaluation rows.

## Evaluation Summary
Evaluation-period threshold-MAE leaders by proxy:

| Proxy | Best MAE Combination | MAE | RMSE | Bias | Median AE | p90 AE | Overbid Rate | Accepted Rate | Mean Unit Revenue |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `p75` | `naive_lag_7d_same_direction + direction_median_markup` | 1.3745 | 1.8833 | -0.3955 | 0.9775 | 4.0970 | 0.5435 | 0.4565 | 0.6805 |
| `p90` | `naive_lag_7d_same_direction + direction_daytype_median_markup` | 1.5857 | 2.0303 | -0.4248 | 1.2863 | 4.4670 | 0.5326 | 0.4674 | 0.8606 |
| `max` | `naive_lag_7d_same_direction + direction_daytype_median_markup` | 1.6696 | 2.2146 | -0.1555 | 1.4850 | 4.2790 | 0.5380 | 0.4620 | 1.0102 |

Evaluation-period revenue leaders by proxy:

| Proxy | Highest Revenue Combination | Mean Unit Revenue | MAE | Overbid Rate | Accepted Rate |
|---|---|---:|---:|---:|---:|
| `p75` | `lear_exogenous_small_da_aligned_daily_v1 + direction_daytype_median_markup` | 0.7316 | 1.4801 | 0.6902 | 0.3098 |
| `p90` | `xgboost_exogenous_small_da_aligned_daily_v1 + direction_p75_markup` | 0.9554 | 2.1722 | 0.8207 | 0.1793 |
| `max` | `xgboost_exogenous_small_da_aligned_daily_v1 + direction_p75_markup` | 1.0615 | 2.2571 | 0.8043 | 0.1957 |

Rule-family pattern in evaluation:
- `direction_p90_markup` is not defensible for v1. Mean overbid is around `0.92` across proxies.
- `direction_p75_markup` increases revenue for `p90` and `max`, but overbid rises to about `0.81` to `0.85`.
- `direction_median_markup` and `direction_daytype_median_markup` form the stable v1 rule family. Their mean overbid is about `0.54` to `0.62`, materially below the upper-quantile rules.

## Rule-Selection Policy
### Primary selection hierarchy
Use the following hierarchy for v1 threshold-rule choice:

1. Reject rules with clearly excessive overbid behaviour.
2. Among the remaining rules, prefer higher mean unit revenue proxy.
3. Use threshold MAE and p90 absolute error as stability checks.
4. Treat `max_accepted_price_proxy` as an optimistic upper-bound scenario, not as the sole central scenario.
5. Prefer `p75` or `p90` for central scenario construction because they are less outlier-sensitive than `max`.

### Explicit v1 overbid policy
Use this qualitative-conservative classification:
- acceptable for primary use: overbid proxy rate `<= 0.60`
- caution / secondary use only: overbid proxy rate `> 0.60` and `<= 0.70`
- reject for primary scenario construction: overbid proxy rate `> 0.70`

Reasoning:
- the observed evaluation tradeoff does not support a harder structural threshold than this;
- however, rules above `0.70` overbid are too aggressive for a proxy layer that already lacks rejected-bid information.

Implications:
- `direction_p90_markup`: reject for primary use
- `direction_p75_markup`: reject for primary central use; retain only as aggressive sensitivity logic if explicitly needed later
- `direction_median_markup` and `direction_daytype_median_markup`: eligible for primary use

## Recommended Threshold Scenario Roles
This layer should not freeze one deterministic final threshold. It should freeze scenario roles.

### Conservative scenario candidate
- threshold proxy: `accepted_price_p75_eur_per_maw`
- recommended anchor: `naive_lag_7d_same_direction`
- recommended markup rule: `direction_daytype_median_markup`

Reasoning:
- the earlier mixed-rule combination `p75 + direction_median` created widespread ordering failures against the selected `p90 + direction_daytype_median` central scenario;
- the revised consistent-daytype policy preserves `p75 <= p90 <= max` across the full DA-aligned test horizon;
- `p75` remains more conservative than `p90` and materially safer than `max`.

### Central / upper-normal scenario candidate
- threshold proxy: `accepted_price_p90_eur_per_maw`
- recommended anchor: `naive_lag_7d_same_direction`
- recommended markup rule: `direction_daytype_median_markup`

Reasoning:
- best evaluation MAE for `p90`;
- acceptable overbid rate for v1;
- higher mean revenue than the naive direction-median `p90` option;
- daytype structure adds useful flexibility without pushing overbid into the rejected range.

### Optimistic / upper-bound scenario candidate
- threshold proxy: `max_accepted_price_proxy_eur_per_maw`
- recommended anchor: `naive_lag_7d_same_direction`
- recommended markup rule: `direction_daytype_median_markup`

Reasoning:
- best evaluation MAE among `max` candidates;
- acceptable overbid rate for v1;
- `max` remains explicitly upper-bound and should not be the sole central threshold.

## Anchor Comparison
The threshold layer and the average-price layer do not select anchors for the same reason.

Average-price freeze result:
- `xgboost_exogenous_small_da_aligned_daily_v1` is the best average-price forecast model on aggregate MAE.

Threshold-rule result:
- `naive_lag_7d_same_direction` is the best anchor for threshold-proxy stability across all three proxies on evaluation MAE.

Interpretation:
- threshold calibration depends on the interaction between the average-price anchor and the markup distribution, not only on raw average-price forecast accuracy;
- the naive anchor appears to align better with the observed 2025 threshold-proxy level after additive markup calibration;
- `xgboost` and `lear` often improve mean revenue, but they do so by taking materially more aggressive threshold positions.

Anchor policy for v1:
- primary threshold anchor: `naive_lag_7d_same_direction`
- secondary aggressive sensitivity anchor: `xgboost_exogenous_small_da_aligned_daily_v1`
- transparent linear sensitivity anchor: `lear_exogenous_small_da_aligned_daily_v1`

Do not hide the tradeoff:
- naive wins threshold MAE and overbid stability;
- xgboost and lear can win unit-revenue proxy for some proxy/rule combinations;
- those revenue wins are frequently paired with weaker overbid behaviour.

## Extreme Max-Price Sensitivity
- the extreme `2025-01-07 Up` source row materially inflates calibration-period `max` metrics;
- it does not dominate evaluation because no flagged evaluation rows exist;
- `max_accepted_price_proxy` remains usable only as an optimistic / upper-bound scenario role;
- `p75` and `p90` are safer central scenario builders.

## Methodological Caveats
- `12.3_F` contains accepted/procured offers only;
- rejected bids are unobserved;
- `max_accepted_price_proxy` is not a true market-clearing threshold;
- the accepted-offer stack is not a full bid ladder;
- this layer is a proxy layer for scenario generation and backtesting;
- synthetic thresholds outside the observed `12.3.F` overlap must not be evaluated as observed truth;
- `unit_revenue_proxy_eur_per_maw` assumes `offered_mw_assumption = 1` and does not include plant feasibility, volume optimisation, activation effects, or downstream operating constraints.

## Decision Freeze
Freeze the following v1 policy for threshold-scenario construction:
- primary eligible rule family: `direction_median_markup`, `direction_daytype_median_markup`
- rejected primary rule family: `direction_p75_markup`, `direction_p90_markup`
- mixed-rule variant rejected: `p75 + naive + direction_median` with `p90/max + naive + direction_daytype_median`
  - rejection reason: widespread ordering failure in the full test horizon
- conservative scenario role: `p75 + naive + direction_daytype_median`
- central / upper-normal scenario role: `p90 + naive + direction_daytype_median`
- optimistic / upper-bound scenario role: `max + naive + direction_daytype_median`

This is a scenario-role freeze, not a claim that one threshold series is the single true bid ladder.

## Next Task
Recommended next task:
- `MFRR_CAPACITY_12_3_F_THRESHOLD_SCENARIOS_DAILY_V1`

Scope:
- consume the threshold calibration/backtest artifact;
- consume this rule-selection policy note;
- generate probability-weighted threshold scenarios for the DA-aligned test period;
- preserve:
  - forecast origin;
  - delivery date;
  - direction;
  - scenario ID;
  - probability;
  - threshold proxy;
  - average-price anchor;
  - caveat fields;
- use the observed `2025` overlap for threshold scenario calibration/evaluation;
- label `2024-10-01` to `2024-12-31` generated thresholds as synthetic/proxy, not observed truth.
