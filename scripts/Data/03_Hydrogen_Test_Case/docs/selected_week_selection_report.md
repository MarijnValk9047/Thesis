# Selected Week Selection Report

## Why common support is required

Later three-model hydrogen bidding runs must compare the same delivery weeks for LEAR Strict, LEAR FS3, and XGBoost FS3. If the models are run on different days, any realised-profit or operational difference would mix model quality with market-regime selection bias.

## Why full three-model hourly test-year comparison is still blocked

A full 2024-10-01 to 2025-09-30 three-model hourly comparison is still blocked because the recovered LEAR Strict thesis-grade artifact only covers a partial, irregular subset of that period. The correct label for this phase is therefore:

`three-model hourly selected-week comparison on common partial test support`

## Exact common support

- validation earliest common complete day: `2023-10-12`
- validation latest common complete day: `2024-09-26`
- validation common complete day count: `188`
- test earliest common complete day: `2024-10-02`
- test latest common complete day: `2025-09-17`
- test common complete day count: `177`
- eligible complete validation calendar weeks: `6`
- eligible complete test calendar weeks: `9`

These support ranges are sparse. The selected weeks come only from days where `common_complete_support = true` for all three artifacts and observed hourly actual prices.

## Candidate-week generation

- candidate weeks are Monday-Sunday calendar weeks to match the existing selected-week workflow and to avoid arbitrary sliding-window tuning;
- each candidate week must contain exactly 7 delivery days inside one split only;
- all 7 days must be complete for LEAR Strict, LEAR FS3, XGBoost FS3, and hourly actual prices;
- DST weeks are excluded if any day in the week is not a 24-hour local day;
- `high_price_hours` is counted with the documented threshold `158 EUR/MWh`, taken from the hydrogen test-case reference price;
- diagnostic scores are relative ranks within each split and are used only to label regimes, not to tune the optimiser;
- `typical_summer` and `typical_winter` mean closest to the seasonal median behaviour, not lowest volatility;
- if a split has no eligible week for a required target season, the fallback is the remaining week with the highest split-wide typicality score, and that backup is labelled explicitly;
- the current validation split has no exact-common-support winter week, so its backup is labelled `winter_proxy` and is not valid for seasonal winter claims.

Score definitions:

- `volatility_score`: average percentile rank of weekly standard deviation, interquartile range, and full spread;
- `low_price_score`: average percentile rank of low weekly mean price, negative-price hours, and low weekly minimum price;
- `high_price_score`: average percentile rank of weekly mean price, peak price, and count of hours above `158 EUR/MWh`;
- `typical_overall_score`: split-wide median-closeness score across mean, volatility, spread, IQR, high-price hours, and negative-price hours;
- `typical_summer_score` / `typical_winter_score`: the same median-closeness score, but computed inside the requested season only.

## Selected validation weeks

| regime_label | week_label | delivery_start_date | delivery_end_date | selection_status | selection_reason | actual_price_mean | actual_price_std | peak_price | high_price_hours |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| high_price | validation_high_price_week | 2023-10-16 | 2023-10-22 | selected_dedicated | validation week with the strongest realised high-price score under exact three-model common support | 92.34232142857142 | 47.2166267398094 | 240.0 | 14 |
| high_volatility | validation_high_volatility_week | 2024-06-10 | 2024-06-16 | selected_dedicated | validation week with the highest realised volatility score under exact three-model common support | 62.0879761904762 | 48.088543291304525 | 177.36 | 3 |
| typical_summer | validation_typical_summer_week | 2024-06-17 | 2024-06-23 | selected_dedicated | summer validation week closest to seasonal median behaviour under exact three-model common support | 78.81928571428571 | 37.51674086318963 | 196.93 | 3 |
| winter_proxy | validation_winter_proxy_week | 2024-09-16 | 2024-09-22 | selected_backup | No complete winter validation week exists under exact three-model common support; selected the closest split-wide typical backup week and labelled it winter_proxy because it is not valid for seasonal winter claims. | 77.53625 | 38.251749671343944 | 162.06 | 1 |

## Selected test weeks

| regime_label | week_label | delivery_start_date | delivery_end_date | selection_status | selection_reason | actual_price_mean | actual_price_std | peak_price | high_price_hours |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| high_price | test_high_price_week | 2025-01-20 | 2025-01-26 | selected_dedicated | test week with the strongest realised high-price score under exact three-model common support | 131.32321428571427 | 71.02589748084705 | 523.47 | 40 |
| high_volatility | test_high_volatility_week | 2024-12-09 | 2024-12-15 | selected_dedicated | test week with the highest realised volatility score under exact three-model common support | 165.40589285714287 | 137.23676671839 | 872.96 | 51 |
| typical_summer | test_typical_summer_week | 2025-07-21 | 2025-07-27 | selected_dedicated | summer test week closest to seasonal median behaviour under exact three-model common support | 87.97482142857143 | 24.231963598688424 | 147.56 | 0 |
| typical_winter | test_typical_winter_week | 2025-01-13 | 2025-01-19 | selected_dedicated | winter test week closest to seasonal median behaviour under exact three-model common support | 142.97541666666666 | 47.98447113894277 | 350.48 | 38 |

## Explicit backups

| period_type | regime_label | week_label | delivery_start_date | delivery_end_date | fallback_reason |
| --- | --- | --- | --- | --- | --- |
| validation | winter_proxy | validation_winter_proxy_week | 2024-09-16 | 2024-09-22 | No complete winter validation week exists under exact three-model common support; selected the closest split-wide typical backup week and labelled it winter_proxy because it is not valid for seasonal winter claims. |

## Regimes not selected

- missing test regime labels: none
- missing validation regime labels: none

## DST handling

DST weeks were excluded from selection if any delivery day in the calendar week was not a 24-hour local day.

## Guardrails for later phases

- selected test weeks are for diagnostic reporting only and must not be used to choose CVaR gamma;
- any later CVaR gamma selection must use validation weeks only;
- all later three-model comparisons must use the same selected weeks for all three models;
- this report does not authorise full-period test-year claims.