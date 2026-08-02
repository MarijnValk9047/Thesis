# Strict LEAR Hourly and Quarter-Hour D--D+4 Finalisation

## Status and scope

This note records the implemented forecasting method and the results of the
canonical full run `20260729_strict_lear_dplus4_full_a03`. The run delivers
paired hourly and quarter-hour point forecasts and nested 30- and 10-scenario
sets for D through D+4. It answers the incremental-granularity question on
common observed support. It does not rerun the annual hourly model selection
and does not contain hydrogen, perfect-foresight, or steel-MILP results.

The artifacts are optimisation-ready on their declared support: all hard
timing, schema, probability, nesting, key-uniqueness, and cross-granularity
checks pass. The scenarios must not be described as calibrated 90% risk bands,
because evaluation p05--p95 coverage is below the predeclared 85% warning
threshold.

## Models

The hourly anchor is the already selected Strict LEAR direct multiday model:

`lear_lago_direct_dplus4_strict_no_future_1092`

Its rolling estimation window is 1,092 days and its forecast origin is 08:00
Europe/Amsterdam on D-1. Reusing this anchor leaves the earlier annual hourly
model-family comparison unchanged.

The quarter-hour model is:

`qh-fs1__mean_shape__hourly_anchor__lear_strict`

For hourly period (h) and quarter position (q\in\{1,2,3,4\}), it is

\[
\widehat p^{QH}_{h,q}=\widehat p^{LEAR}_{h}+\widehat\delta_{h,q}.
\]

The mean shape is estimated by local hour of day, quarter position, and weekend
indicator. The fit is causal and walk-forward: a realised quarter-hour price
can enter a later fit only after it is known at that later origin. Unseen
weekend cells fall back to the same hour-quarter cell, then the quarter cell,
then the global mean. These existing fallback levels and the model definition
were not reselected on evaluation.

The four shape values are centred within every hour:

\[
\widetilde\delta_{h,q}=\widehat\delta_{h,q}
-\frac{1}{4}\sum_{j=1}^{4}\widehat\delta_{h,j}.
\]

Consequently,

\[
\frac{1}{4}\sum_q\widehat p^{QH}_{h,q}=\widehat p^{LEAR}_{h}
\]

up to numerical precision. The observed maximum absolute discrepancy is
(1.42\times10^{-14}) EUR/MWh. Therefore, the shape cannot manufacture an
improvement in the hourly anchor score.

## Data, timing, and support

Observed Dutch quarter-hour day-ahead prices were refreshed through July 2026.
ENTSO-E `curveType=A03` observations are variable blocks: omitted positions
retain the preceding block value until the next change or the period end. The
cleaner therefore expands those official blocks forward; it does not
statistically interpolate them. This follows the
[ENTSO-E implementation guide](https://www.entsoe.eu/Documents/EDI/Library/Introduction_of_different_time_series_v1.4.1.pdf).
The refresh expanded 263 A03 positions and used zero statistical price
interpolations. The complete local day 24 July 2026 is genuinely unobserved and
remains missing.

The nominal split thresholds and effective selected delivery-day support are:

| Split | Nominal start | Effective selected delivery days | Origins |
|---|---:|---:|---:|
| Training | 2025-10-01 | 2025-10-02--2026-01-31 | 122 |
| Validation | 2026-02-01 | 2026-02-01--2026-03-17 | 45 |
| Extended out-of-sample evaluation | 2026-03-18 | 2026-03-18--2026-07-19 | 116 |

March--July is labelled *extended out-of-sample evaluation*, rather than a
previously untouched final holdout, because March--April results had already
been inspected. All reported hourly/QH comparisons use exactly the same 116
origins and timestamps.

The support policy is strict:

- an origin is retained only if all observed targets from D through D+4 and
  all Strict LEAR predictions are present;
- no missing evaluation price is interpolated;
- five candidate July origins are excluded because their horizon intersects
  the unobserved 24 July day;
- eight candidate origins from 29 March through 5 April are excluded because
  the inherited Strict LEAR features require complete 24-hour lag vectors.
  The 23-hour spring-DST target itself is forecast natively, but no synthetic
  lag hour is inserted when that day later becomes D-1, D-2, D-3, or D-7;
- retained DST-crossing paths use their actual length. Four selected spring-DST
  origins have a 476-quarter five-day path rather than a forced 480-quarter
  path.

## Coupled scenario method

For each causal historical D--D+4 source origin, forecast error is decomposed
into an hourly level component and a within-hour shape component:

\[
e^{level}_{h}=p^{actual,hourly}_{h}-\widehat p^{LEAR}_{h},
\]

\[
e^{shape}_{h,q}=\left(p^{actual,QH}_{h,q}-p^{actual,hourly}_{h}\right)
-\widetilde\delta_{h,q}.
\]

Each source remains one coherent five-day path. A source block is eligible only
if its full realised path was available before the target forecast origin.
Train and validation blocks may be sources; evaluation residuals never are.
This preserves information timing while allowing earlier validation paths to
be used for later origins when already known.

For raw scenario (s):

\[
p^{hourly,s}_{h}=\widehat p^{LEAR}_{h}
+\lambda_L e^{level,s}_{h},
\]

\[
p^{QH,s}_{h,q}=\widehat p^{LEAR}_{h}
+\lambda_L e^{level,s}_{h}
+\widetilde{\left(\widehat\delta_{h,q}
+\lambda_S e^{shape,s}_{h,q}\right)}.
\]

The final term is centred per hour. Hence every QH scenario averages exactly
to its paired hourly scenario. The observed maximum discrepancy is
(1.14\times10^{-13}) EUR/MWh.

For every origin, 400 raw paths are sampled in memory. The validation grid is
(lambda_L\in\{1.00,1.15,1.30,1.45,1.60\}) and
(lambda_S\in\{0.75,1.00,1.25,1.50\}), with a fixed protected-tail share of
0.20. The selected combination is (lambda_L=1.00) and
(lambda_S=0.75). It obtains 86.50% weighted p05--p95 coverage on 45
validation origins, with zero methodological violations.

The joint QH paths are reduced by tail-protected weighted medoids. Six tail
representatives are protected in the 30-set. The 10-set is a second, nested
weighted reduction of those 30 paths and protects two tail representatives.
Cluster masses become scenario probabilities; probabilities are not forced to
be equal. Hourly and QH exports retain the same source-block identity, scenario
ID, parent ID, and probability.

## Evaluation measures

Point forecasts are evaluated with MAE, RMSE, signed bias, p90 and p95 absolute
error, rMAE relative to the official previous-week naive forecast, mean daily
Spearman correlation, top-six and bottom-six hit rates, tail MAE, and absolute
high-low spread error. Counts and coverage are reported overall, by month, and
by lead day.

The paired Diebold--Mariano comparison uses absolute loss averaged within each
forecast origin and a HAC correction with four origin lags. Aggregating within
origin prevents the four quarter-hours and the five-day horizon from being
treated as independent observations.

Scenario diagnostics use probability-weighted p10--p90 and p05--p95 coverage
and widths, p50 bias, upper- and lower-tail miss rates, min-max containment,
discrete weighted CRPS, and the multivariate energy score over the full D--D+4
path. Effective scenario size is

\[
N_{eff}=\frac{1}{\sum_s \pi_s^2}.
\]

Protected-tail weight is the probability mass assigned to protected tail
representatives. Raw, 30-, and 10-path results are compared on the same
origins.

## Point-forecast results

| Comparison | MAE | RMSE | Bias | rMAE | Daily Spearman | Tail MAE | Timestamps |
|---|---:|---:|---:|---:|---:|---:|---:|
| Hourly LEAR vs aggregated QH truth | 30.752 | 50.650 | 9.907 | 0.821 | 0.906 | 51.539 | 13,916 |
| Flat hourly repeat vs native QH truth | 32.749 | 53.580 | 9.907 | 0.853 | 0.870 | 54.822 | 55,664 |
| QH causal mean shape vs native QH truth | 31.995 | 52.896 | 9.907 | 0.833 | 0.893 | 53.635 | 55,664 |

Relative to flat repetition, the QH mean shape improves MAE by 0.754 EUR/MWh
(2.30%), RMSE by 0.684 EUR/MWh (1.28%), tail MAE by 1.187 EUR/MWh (2.17%), and
high-low spread error by 8.234 EUR/MWh (9.93%). Its top-six hit rate is lower
(0.468 vs 0.508), whereas its bottom-six hit rate is slightly higher (0.501 vs
0.489). The evidence therefore supports a modest but statistically robust
incremental value from quarter-hour shape, not uniform superiority on every
ranking metric.

| Lead | Flat MAE | QH-shape MAE | MAE improvement |
|---:|---:|---:|---:|
| D | 27.781 | 26.813 | 3.48% |
| D+1 | 32.087 | 31.323 | 2.38% |
| D+2 | 34.285 | 33.585 | 2.04% |
| D+3 | 34.502 | 33.793 | 2.06% |
| D+4 | 35.093 | 34.462 | 1.80% |

The paired DM statistic is -13.20 with a two-sided p-value of
(8.54\times10^{-40}); the negative loss difference favours mean shape over
flat repetition on the common support.

## Scenario and reduction results

| Granularity | Set | p05--p95 coverage | Width | p50 bias | CRPS | Energy score | Effective size |
|---|---:|---:|---:|---:|---:|---:|---:|
| Hourly | 30 | 80.22% | 104.25 | 7.21 | 24.40 | 384.19 | 10.09 |
| Hourly | 10 | 75.24% | 93.82 | 4.89 | 25.29 | 396.67 | 6.32 |
| Quarter-hour | 30 | 79.23% | 106.33 | 7.08 | 25.48 | 808.71 | 10.09 |
| Quarter-hour | 10 | 74.27% | 95.74 | 4.75 | 26.42 | 835.10 | 6.32 |

The 30-set is the primary stochastic input. The nested 10-set is a deliberate
computational sensitivity, not an equivalent-quality substitute: it loses
about 5.0 percentage points of p05--p95 coverage and worsens CRPS and energy
score. Both remain valid probability-weighted optimization inputs, but neither
meets the predeclared 85% evaluation coverage threshold. Any later CVaR or
reliability interpretation must retain this warning.

## Artifacts and reuse

The canonical runner is
`scripts/Data/02_Forecasting/01_DA_prices/run_strict_lear_dplus4_finalisation.py`
and its fixed configuration is
`scripts/Data/02_Forecasting/01_DA_prices/quarterhour_da/configs/strict_lear_dplus4_finalisation.yaml`.

The ignored governed output root is
`data/02_Forecasting/01_DA_prices/scenario_evaluation/strict_lear_dplus4_finalisation/20260729_strict_lear_dplus4_full_a03/`.
It contains 46 files totalling 54.2 MB. Optimization inputs are separate
Parquet files for hourly/QH point forecasts and 30/10 scenarios, plus the
30-to-10 mapping. They contain no actual, error, or future-information columns.
Actuals are stored only in `evaluation_actuals.parquet`.

The generated body and appendix tables are
`thesis_body_point_table.csv`, `thesis_body_scenario_table.csv`,
`thesis_appendix_point_table.csv`, and
`thesis_appendix_scenario_table.csv`. Perfect foresight remains a separate
ex-post upper-bound calculation in the later optimization experiments; it must
not be mixed into forecast construction or scenario generation.

## Validity statement

The implementation supports a defensible comparison of hourly and
quarter-hour forecasts over several observed months. Internal validity is
protected by common support, causal walk-forward fitting, validation-only scale
selection, paired scenario identity, separated actuals, and explicit DST and
missing-day exclusions. External validity remains limited: the comparison is
not a full-year QH evaluation, March--April is not an untouched holdout, and
scenario interval coverage is insufficient for calibrated-risk claims. Later
hydrogen and steel tests should reuse these exact artifacts so forecast
generation is not retuned after observing optimization outcomes.
