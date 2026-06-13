# mFRR Capacity 12.3_F Scope Inspection Daily V1

## Scope
This note inspects the cleaned `12.3_F` Dutch IR/mFRR capacity data to determine what can be used in the next accepted-offer threshold and bid-ladder proxy layer.

This is a scope inspection only. It does not build threshold tables, join forecast outputs, run models, or inspect raw ENTSO-E files.

## Average-Price Context
Frozen DA-aligned average-price context:
- target: `17.1_BC` average procurement price;
- unit: `EUR_per_MW_per_period`;
- granularity: daily x direction;
- split:
  - train: `2022-01-01` to `2023-09-30`;
  - validation: `2023-10-01` to `2024-09-30`;
  - test: `2024-10-01` to `2025-09-30`.

This 12.3_F layer is for accepted-offer threshold and accepted-stack proxies only.

## A. Canonical 12.3_F Source Files
Relevant cleaned files found:
- `data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/parsed/12_3_f_nl_ir_offer_long.csv`
- `data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/aggregated/12_3_f_nl_ir_daily_direction_long.csv`
- `data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/aggregated/12_3_f_nl_ir_daily_direction_wide.csv`
- `data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/hourly/12_3_f_nl_ir_hourly_direction_long.csv`
- `data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/hourly/12_3_f_nl_ir_hourly_direction_wide.csv`
- `data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/diagnostics/*`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/12_3_f_nl_ir_availability_manifest.csv`

Canonical source recommendation for daily threshold calibration:
- primary canonical source: `parsed/12_3_f_nl_ir_offer_long.csv`
- supporting cross-check source: `aggregated/12_3_f_nl_ir_daily_direction_long.csv`
- availability support: `12_3_f_nl_ir_availability_manifest.csv`

Reasoning:
- the parsed file contains accepted **offer-level** rows, including accepted quantity and accepted price per row;
- the daily aggregated file already contains quantity-weighted average price, min, max, median, total quantity, and offer count, but it does not contain the full accepted offer stack needed for `p10/p25/p50/p75/p90` threshold proxies;
- the hourly file is not the canonical input for a daily threshold layer because it is an expansion of daily summaries rather than an independent finer-grain accepted-offer stack.

Offer-level availability:
- yes, offer-level accepted rows are available;
- this supports quantity-weighted price quantiles, provided they are computed from the parsed offer-level file.

## B. Schema And Semantics
### Parsed offer-level file
File:
- `parsed/12_3_f_nl_ir_offer_long.csv`

Observed shape and coverage:
- row count: `26089`
- date range: `2025-01-07` to `2026-01-01`
- direction counts:
  - `Up`: `8146`
  - `Down`: `17943`

Key columns present:
- identity/source: `native_offer_id`, `source_archive`, `source_archive_offset`, `source_member`, `timeseries_mrid`
- timing: `created_datetime_utc`, `document_period_start_utc`, `document_period_end_utc`, `series_period_start_utc`, `series_period_end_utc`, `timestamp_utc`, `interval_end_utc`, `target_delivery_local_date`
- direction: `flow_direction_code`, `flow_direction_label`
- quantity: `quantity_maw`, `daily_direction_total_quantity_maw`, `cumulative_quantity_maw`, `quantity_share_of_day_direction`, `cumulative_quantity_share`
- price: `procurement_price_eur_per_maw`, `offer_rank_price_asc`
- units: `currency_unit`, `quantity_unit`, `price_measure_unit`
- availability metadata: `known_at_utc`, `known_at_rule`

Direction representation:
- `A01 = Up`
- `A02 = Down`
- these map cleanly to the frozen average-price layer labels `Up` and `Down`

Row semantics:
- rows represent **individual accepted offer rows** from the cleaned 12.3_F export
- diagnostics and metadata explicitly state that ambiguous duplicate-looking rows are preserved because identical quantity-price tuples can be legitimate separate offers
- `native_offer_id` is unique in the inspected file sample/summary check; no duplicate `native_offer_id` values were found

Quantity and price checks:
- quantity min/max: `1.0` to `267.0` `MAW`
- price min/max: `0.05` to `2500.0` `EUR per MAW`
- zero/negative quantity rows: `0`
- negative price rows: `0`
- zero price rows: `0`
- extreme values exist, especially in price, so robust diagnostics will be needed in the next phase

Time-block semantics:
- `interval_interpretation = single_point_full_period` for all inspected rows
- `effective_interval_minutes` is mainly `1440`, with DST-related `1500` and `1380` cases
- this supports treating the accepted offers as daily contracts with DST-aware duration fields preserved

### Aggregated daily direction file
File:
- `aggregated/12_3_f_nl_ir_daily_direction_long.csv`

Observed shape and coverage:
- row count: `720`
- date range: `2025-01-07` to `2026-01-01`
- exactly one row per `target_delivery_local_date x direction`
- direction counts:
  - `Up`: `360`
  - `Down`: `360`

Daily aggregate columns available:
- `offer_count`
- `total_quantity_maw`
- `quantity_weighted_price_eur_per_maw`
- `price_mean_eur_per_maw`
- `price_median_eur_per_maw`
- `price_min_eur_per_maw`
- `price_max_eur_per_maw`
- `unique_price_levels`
- `max_offer_quantity_maw`

Interpretation:
- this file is a **daily aggregate of accepted offers**, not an offer-level ladder
- it is useful for validation and quick daily summaries
- it is not sufficient on its own for `p10/p25/p50/p75/p90` accepted-price proxies unless those quantiles are recomputed upstream from the offer-level file

## C. Availability And Overlap
Availability from cleaned 12.3_F data:
- first available delivery date: `2025-01-07`
- last available delivery date: `2026-01-01`
- delivery-date x direction coverage appears complete from `2025-01-07` through `2026-01-01`

Availability manifest findings:
- `2025` monthly status is `available_downloaded` for all `12` months
- months before `2025` are `empty_no_matching_data`
- this confirms that the threshold layer is a **2025+ observed layer**, not a 2022-2024 forecasting target

Overlap with DA-aligned average-price test horizon `2024-10-01` to `2025-09-30`:
- overlap starts at `2025-01-07`
- overlap ends at `2025-09-30`
- overlap coverage is complete for both directions during that window
- overlap row count in daily direction space: `534` rows = `267` days x `2` directions

Specific period checks:
- `2025-01-07` to `2025-09-30`: available and complete for both directions
- `2025-07-01` to `2025-09-30`: available and complete for both directions
- this means the preferred threshold calibration/evaluation split is feasible

## D. Feasibility Of Observed Accepted-Offer Threshold Metrics
Metric feasibility classification:

- `weighted_accepted_price`: `feasible_from_cleaned_data`
  - directly available in the daily aggregate file as `quantity_weighted_price_eur_per_maw`
- `accepted_price_p10`: `feasible_from_cleaned_data`
  - requires computation from offer-level accepted rows
- `accepted_price_p25`: `feasible_from_cleaned_data`
  - requires computation from offer-level accepted rows
- `accepted_price_p50`: `feasible_from_cleaned_data`
  - can be recomputed from offer-level rows; count-median is already available in daily aggregates as `price_median_eur_per_maw`
- `accepted_price_p75`: `feasible_from_cleaned_data`
  - requires computation from offer-level accepted rows
- `accepted_price_p90`: `feasible_from_cleaned_data`
  - requires computation from offer-level accepted rows
- `max_accepted_price_proxy`: `feasible_from_cleaned_data`
  - directly available as `price_max_eur_per_maw`
- `min_accepted_price`: `feasible_from_cleaned_data`
  - directly available as `price_min_eur_per_maw`
- `stack_spread`: `feasible_from_cleaned_data`
  - computable from min/max accepted prices
- `accepted_offer_count`: `feasible_from_cleaned_data`
  - directly available as `offer_count`
- `accepted_quantity_sum`: `feasible_from_cleaned_data`
  - directly available as `total_quantity_maw`

Important limitation:
- quantity-weighted quantiles appear feasible because the offer-level file contains both `quantity_maw` and `procurement_price_eur_per_maw`
- they are **not** directly stored in the daily aggregate file
- the next implementation must compute them explicitly from the parsed offer-level file
- if only count-weighted quantiles were used, that would be a weaker proxy and should be documented as such; current cleaned data appears sufficient to avoid that downgrade

## E. Link To 17.1_BC / Average-Price Forecasts
Join feasibility:
- yes, the 12.3_F daily direction data can be joined to frozen average-price forecast artifacts by `delivery_date_local x direction`
- direction labels are compatible after mapping `A01/A02` to `Up/Down`
- daily granularity is compatible

Unit compatibility:
- average-price forecast layer uses `EUR_per_MW_per_period`
- 12.3_F accepted-offer prices use `EUR` with `price_measure_unit = MAW`
- these are compatible enough for **additive markup** interpretation at the daily-direction proxy level
- additive markups are preferable to ratios because the quantities and price semantics are close enough for spread-style comparisons, while ratios would be less stable and less interpretable near low accepted-price regimes

Feasible next-layer markup variables:
- `markup_max_vs_observed_avg`: feasible
- `markup_p90_vs_observed_avg`: feasible
- `markup_p75_vs_observed_avg`: feasible
- `threshold_error_if_using_forecast_anchor`: feasible

This task did not perform the join.

## F. Recommended Calibration / Evaluation Split
Recommended threshold calibration/evaluation split:
- calibration: `2025-01-07` to `2025-06-30`
- evaluation: `2025-07-01` to `2025-09-30`

Feasibility check:
- calibration period length: `175` days, complete for both directions
- evaluation period length: `92` days, complete for both directions
- this is the preferred conservative split and does not require fallback adjustment

## G. Methodological Caveats
- `12.3_F` contains **accepted/procured offers only**, not rejected offers
- `max_accepted_price` is an **accepted-threshold proxy**, not a true market-clearing threshold
- accepted-offer stacks cannot be treated as full submitted bid ladders
- `12.3_F` starts only in `2025`, so it cannot be used as a long-run threshold target for `2022-2024`
- synthetic thresholds must not be treated as observed truth
- any bid acceptance rule from this layer is proxy-based
- threshold calibration must not tune on its evaluation period
- `known_at_rule = created_datetime_utc_from_export_only_not_forecast_safe`, so this cleaned layer is an observed calibration layer, not a forecast-safe exogenous signal

## H. Recommended Next Implementation Task
Next task name:
- `MFRR_CAPACITY_12_3_F_OBSERVED_THRESHOLD_TABLE_DAILY_V1`

Recommended exact inputs:
- primary input:
  - `data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/parsed/12_3_f_nl_ir_offer_long.csv`
- cross-check input:
  - `data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/aggregated/12_3_f_nl_ir_daily_direction_long.csv`
- context-only join target for a later phase, not this task:
  - frozen DA-aligned average-price forecast artifacts

Recommended exact output path:
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_observed_threshold_table_daily_direction.csv`

Expected output columns:
- `delivery_date_local`
- `direction`
- `accepted_offer_count`
- `accepted_quantity_sum_maw`
- `weighted_accepted_price_eur_per_maw`
- `accepted_price_p10_eur_per_maw`
- `accepted_price_p25_eur_per_maw`
- `accepted_price_p50_eur_per_maw`
- `accepted_price_p75_eur_per_maw`
- `accepted_price_p90_eur_per_maw`
- `min_accepted_price_eur_per_maw`
- `max_accepted_price_proxy_eur_per_maw`
- `stack_spread_eur_per_maw`
- `source_offer_rows`
- `quantity_weighting_method`
- `known_at_rule`
- `coverage_flags`
- `calibration_split`

Recommended validation checks:
- exactly one row per `delivery_date_local x direction`
- date range starts at `2025-01-07`
- complete coverage for `2025-01-07` to `2025-09-30`
- `accepted_price_p10 <= p25 <= p50 <= p75 <= p90 <= max_accepted_price_proxy`
- `weighted_accepted_price` lies within `[min_accepted_price, max_accepted_price_proxy]`
- `accepted_offer_count > 0`
- `accepted_quantity_sum_maw > 0`
- cross-check `weighted_accepted_price` and `accepted_offer_count` against the existing daily aggregate file
- no raw-data inspection needed

Recommended stop conditions:
- parsed offer-level file missing
- quantity field or price field missing
- direction mapping ambiguous
- quantile weighting definition cannot be specified cleanly
- daily aggregate cross-check materially disagrees with recomputed weighted accepted price or offer count
