# Three-Model Hourly Common Support Audit

This file documents the Phase B common-support audit for the three hourly D-only hydrogen bidding artifacts.

Important scope limits:

- no stochastic bidding MILPs were run;
- no CVaR runs were run;
- no optimisation model code was changed;
- this is an audit and registry phase only.

## Artifact validation

| artifact_key | artifact_label | path | artifact_exists | validation_mode | forecast_origin_explicit | granularity_values | lead_day_values | scenario_count_min | scenario_count_max | probability_sum_min | probability_sum_max | duplicate_row_count | delivery_start_min_utc | delivery_start_max_utc | delivery_date_min | delivery_date_max | n_delivery_days | n_forecast_origins | actual_price_missing_rows | status | message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support | LEAR Strict | data\02_Forecasting\01_DA_prices\hourly_da\notebook_artifacts\01_da_price_scenario_generation_hourly_with_lear_strict\20260517_104259\scenario_prices_long.csv | True | thesis_grade | True | hourly | 0 | 75 | 75 | 0.9999999999999926 | 1.0 | 0 | 2023-10-11T22:00:00+00:00 | 2025-09-18T21:00:00+00:00 | 2023-10-12 | 2025-09-18 | 419 | 419 | 0 | pass | Artifact passed thesis-grade validation and day-level prechecks. |
| hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate | LEAR FS3 | data\02_Forecasting\01_DA_prices\hourly_da\notebook_artifacts\01_da_price_scenario_generation_hourly_with_lear_strict\20260516_002902\scenario_prices_long.csv | True | thesis_grade | True | hourly | 0 | 75 | 75 | 0.9999999999999926 | 1.0 | 0 | 2023-10-04T22:00:00+00:00 | 2025-09-26T21:00:00+00:00 | 2023-10-05 | 2025-09-26 | 693 | 693 | 0 | pass | Artifact passed thesis-grade validation and day-level prechecks. |
| hourly_xgboost_fs3_pruned_tail_stress_v1_thesis_candidate | XGBoost FS3 | data\02_Forecasting\01_DA_prices\hourly_da\notebook_artifacts\01_da_price_scenario_generation_hourly_with_lear_strict\20260516_084412\scenario_prices_long.csv | True | thesis_grade | True | hourly | 0 | 75 | 75 | 0.9999999999999926 | 1.0 | 0 | 2023-10-04T22:00:00+00:00 | 2025-09-26T21:00:00+00:00 | 2023-10-05 | 2025-09-26 | 694 | 694 | 0 | pass | Artifact passed thesis-grade validation and day-level prechecks. |

## Common-support summary

- validation common-support earliest day: `2023-10-12`
- validation common-support latest day: `2024-09-26`
- validation common-support day count: `188`
- test common-support earliest day: `2024-10-02`
- test common-support latest day: `2025-09-17`
- test common-support day count: `177`
- eligible complete validation calendar weeks: `6`
- eligible complete test calendar weeks: `9`

Support is sparse, not continuous. The exact support is defined by `common_complete_support = true` in the CSV, not by the min and max dates alone.

## Contiguous support segments

Validation segments:
- `2023-10-12` to `2023-10-25` (14 days)
- `2023-11-03` to `2023-11-04` (2 days)
- `2023-11-06` to `2023-11-15` (10 days)
- `2023-11-21` to `2023-11-21` (1 days)
- `2023-11-26` to `2023-11-28` (3 days)
- `2023-12-08` to `2023-12-08` (1 days)
- `2023-12-14` to `2023-12-16` (3 days)
- `2023-12-18` to `2023-12-22` (5 days)
- `2023-12-27` to `2023-12-27` (1 days)
- `2024-01-03` to `2024-01-03` (1 days)
- `2024-01-05` to `2024-01-05` (1 days)
- `2024-01-10` to `2024-01-12` (3 days)
- `2024-01-14` to `2024-01-14` (1 days)
- `2024-01-19` to `2024-01-21` (3 days)
- `2024-01-23` to `2024-02-03` (12 days)
- `2024-02-09` to `2024-02-10` (2 days)
- `2024-02-13` to `2024-02-15` (3 days)
- `2024-02-20` to `2024-02-22` (3 days)
- `2024-02-24` to `2024-02-24` (1 days)
- `2024-02-29` to `2024-02-29` (1 days)
- `2024-03-04` to `2024-03-08` (5 days)
- `2024-03-14` to `2024-03-15` (2 days)
- `2024-03-18` to `2024-03-19` (2 days)
- `2024-03-28` to `2024-03-30` (3 days)
- `2024-04-05` to `2024-04-06` (2 days)
- `2024-04-11` to `2024-04-13` (3 days)
- `2024-04-15` to `2024-04-16` (2 days)
- `2024-04-23` to `2024-04-23` (1 days)
- `2024-04-25` to `2024-04-25` (1 days)
- `2024-05-05` to `2024-05-07` (3 days)
- `2024-05-09` to `2024-05-15` (7 days)
- `2024-05-20` to `2024-05-22` (3 days)
- `2024-05-24` to `2024-05-31` (8 days)
- `2024-06-05` to `2024-06-27` (23 days)
- `2024-07-08` to `2024-07-09` (2 days)
- `2024-07-11` to `2024-07-14` (4 days)
- `2024-07-19` to `2024-07-21` (3 days)
- `2024-07-23` to `2024-07-29` (7 days)
- `2024-08-03` to `2024-08-05` (3 days)
- `2024-08-12` to `2024-08-13` (2 days)
- `2024-08-15` to `2024-08-17` (3 days)
- `2024-08-22` to `2024-08-24` (3 days)
- `2024-08-31` to `2024-09-01` (2 days)
- `2024-09-04` to `2024-09-26` (23 days)

Test segments:
- `2024-10-02` to `2024-10-03` (2 days)
- `2024-10-10` to `2024-10-10` (1 days)
- `2024-10-12` to `2024-10-12` (1 days)
- `2024-10-14` to `2024-10-20` (7 days)
- `2024-10-25` to `2024-10-26` (2 days)
- `2024-10-31` to `2024-11-02` (3 days)
- `2024-11-04` to `2024-11-15` (12 days)
- `2024-11-20` to `2024-11-21` (2 days)
- `2024-11-24` to `2024-11-26` (3 days)
- `2024-12-01` to `2024-12-03` (3 days)
- `2024-12-05` to `2024-12-16` (12 days)
- `2024-12-22` to `2024-12-23` (2 days)
- `2024-12-26` to `2024-12-30` (5 days)
- `2025-01-05` to `2025-01-07` (3 days)
- `2025-01-09` to `2025-02-05` (28 days)
- `2025-02-14` to `2025-02-15` (2 days)
- `2025-02-17` to `2025-02-18` (2 days)
- `2025-02-23` to `2025-02-25` (3 days)
- `2025-02-27` to `2025-03-12` (14 days)
- `2025-03-25` to `2025-03-27` (3 days)
- `2025-04-08` to `2025-04-08` (1 days)
- `2025-04-22` to `2025-04-24` (3 days)
- `2025-04-26` to `2025-04-26` (1 days)
- `2025-05-01` to `2025-05-03` (3 days)
- `2025-05-09` to `2025-05-10` (2 days)
- `2025-05-13` to `2025-05-15` (3 days)
- `2025-05-17` to `2025-05-25` (9 days)
- `2025-06-11` to `2025-06-11` (1 days)
- `2025-06-16` to `2025-06-18` (3 days)
- `2025-06-20` to `2025-06-24` (5 days)
- `2025-06-29` to `2025-07-01` (3 days)
- `2025-07-03` to `2025-07-04` (2 days)
- `2025-07-11` to `2025-07-11` (1 days)
- `2025-07-17` to `2025-07-18` (2 days)
- `2025-07-21` to `2025-08-01` (12 days)
- `2025-08-06` to `2025-08-08` (3 days)
- `2025-08-10` to `2025-08-10` (1 days)
- `2025-08-20` to `2025-08-21` (2 days)
- `2025-08-24` to `2025-08-29` (6 days)
- `2025-09-08` to `2025-09-09` (2 days)
- `2025-09-12` to `2025-09-12` (1 days)
- `2025-09-17` to `2025-09-17` (1 days)

## Candidate-week generation

- candidate weeks are Monday-Sunday calendar weeks;
- weeks must contain 7 delivery days inside one split only;
- all 7 days must be complete for all three artifacts and for observed hourly actual prices;
- DST weeks are excluded if any day in the week is not a 24-hour local delivery day;
- `high_price_hours` uses the hydrogen test-case reference threshold `158 EUR/MWh`.

## Candidate-week counts by status

| period_type | exclusion_reason | n_weeks |
| --- | --- | --- |
| outside_split | mixes_validation_and_test_days; not_complete_for_all_models; actual_prices_incomplete | 1 |
| test |  | 9 |
| test | not_complete_for_all_models | 13 |
| test | not_complete_for_all_models; actual_prices_incomplete | 27 |
| test | not_complete_for_all_models; actual_prices_incomplete; contains_dst_transition_day | 2 |
| test | week_not_fully_inside_audited_split_range; not_complete_for_all_models; actual_prices_incomplete | 1 |
| validation |  | 6 |
| validation | not_complete_for_all_models | 16 |
| validation | not_complete_for_all_models; actual_prices_incomplete | 28 |
| validation | not_complete_for_all_models; actual_prices_incomplete; contains_dst_transition_day | 1 |
| validation | not_complete_for_all_models; contains_dst_transition_day | 1 |
