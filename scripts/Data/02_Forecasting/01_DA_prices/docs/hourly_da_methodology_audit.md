# Hourly DA Methodology Audit

## Executive Conclusion

This audit answers one question: is the existing hourly DA pipeline causally valid for the stated `08:00 on D-1` origin and `D..D+4` horizon?

Short answer:

- `D`-only hourly forecasting is leakage-free under the repo's stated `known_at` assumptions.
- Hourly `D..D+4` forecasting is also leakage-free under the repo's stated `known_at` assumptions.
- The repo's `known_at` semantics are internally consistent and conservative, but they are not yet fully validated as exact market publication timing.
- One concrete fix was needed immediately: interpolated cleaned DA price values were being treated as scoreable truth. This audit changes that so interpolated or flagged points are no longer counted as observed evaluation targets.

The pipeline is therefore suitable as the methodological base for a later quarter-hour extension, but only with clear documentation of the `known_at` assumption and with care not to reuse scenario-selection helpers as benchmark-selection logic.

## Scope and Files Inspected

Governance and methodology:

- `AGENTS.md`
- `CHATGPT_PROJECT_CONTEXT.md`
- `scripts/Data/02_Forecasting/01_DA_prices/README.md`
- `scripts/Data/02_Forecasting/01_DA_prices/docs/availability_assumption.md`
- `scripts/Data/02_Forecasting/01_DA_prices/docs/horizon_standardization.md`
- `scripts/Data/02_Forecasting/01_DA_prices/docs/model_comparability.md`
- `scripts/Data/02_Forecasting/01_DA_prices/docs/phase2_policy_hardening.md`
- `scripts/Data/02_Forecasting/01_DA_prices/docs/time_handling.md`

Hourly pipeline:

- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/config.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/data_loading.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/endogenous_features.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/evaluation.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/external_features.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/features.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/forecast_evaluation.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/metrics.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/methodology.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/pipeline.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/schedule.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/scenario_generation.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/time_utils.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/core/visual_weeks.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/models/lear.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/models/naive.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/models/prophet_model.py`
- `scripts/Data/02_Forecasting/01_DA_prices/hourly_da/models/xgboost_model.py`

Run entry points:

- `scripts/Data/02_Forecasting/01_DA_prices/run_naive_benchmark.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_lear_benchmark.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_xgboost_benchmark.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_prophet_benchmark.py`
- `scripts/Data/02_Forecasting/01_DA_prices/run_model_comparison.py`

Cleaning and source data:

- `scripts/Data/01_cleaning/day_ahead_prices_pipeline.py`
- `scripts/Data/01_cleaning/entsoe_system_features_pipeline.py`
- `data/01_cleaned/Day_ahead_prices/DA_prices/hourly/da_prices_all_regions_hourly.csv`
- `data/01_cleaned/Day_ahead_prices/DA_prices/quarterly/da_prices_NL_quarterly.csv`
- `data/01_cleaned/Day_ahead_prices/diagnostics/gap_fix_summary.csv`
- `data/01_cleaned/Day_ahead_prices/diagnostics/diagnostics_comparison.csv`
- `data/01_cleaned/Load/da_total_load_forecast/hourly/da_total_load_forecast_hourly_long.csv`
- `data/01_cleaned/Load/week_ahead_total_load_forecast/hourly/week_ahead_total_load_forecast_hourly_long.csv`
- `data/01_cleaned/Generation/da_generation_forecast/hourly/da_generation_forecast_hourly_long.csv`

## Repository Governance and Assumptions

Current governance text is outdated relative to the thesis phase now being prepared.

Observed governance state:

- `AGENTS.md` still says only hourly DA forecasting is in scope.
- `CHATGPT_PROJECT_CONTEXT.md` and the DA forecasting README still describe quarter-hour work as out of scope.
- The hourly methodology itself is clearly defined:
  - train `2022-01-01` to `2023-09-30`
  - validation `2023-10-01` to `2024-09-30`
  - test `2024-10-01` to `2025-09-30`
  - daily rolling origins
  - forecast origin `08:00` on `D-1`
  - horizon `D..D+4`

Recommendation:

- update governance only after the hourly audit is accepted
- when updated, keep hourly methodology frozen and explicitly say quarter-hour DA extension and DA scenario generation are now in scope
- keep mFRR and balancing-market work out of scope

## Hourly Forecast Origin and Information-Set Assumptions

The operational forecast schedule is defined by delivery start date, not by target timestamp.

Plain-English schedule:

- for each eligible local delivery day `D`, create one origin at `08:00` local on `D-1`
- forecast the full local-day block for `D, D+1, D+2, D+3, D+4`
- drop late-split origins whose full 5-day horizon would cross the split boundary
- keep timestamps internally in UTC and derive local dates only for business logic and reporting

The critical availability rule is:

- a row may enter model history only if `known_at_utc <= forecast_origin_utc`

For hourly DA prices, the repo assigns a day-level `known_at_utc`:

- all hourly prices for local day `t` are treated as known at `t 08:00` local

This is:

- internally consistent
- conservative relative to naive delivery-time filtering
- not yet a fully validated claim about exact external market publication timing

## Cleaned Data Audit

### Source handling summary

| Operation | Location | Leakage-safe? | Notes |
| --- | --- | --- | --- |
| Parse raw ENTSO-E DA XML to UTC timestamps | `day_ahead_prices_pipeline.py` | Yes | Time parsing itself is not leakage-prone. |
| Resolve duplicate timestamps deterministically | cleaning + `core/data_loading.py` | Yes | Duplicate resolution is timestamp-local, not future-looking. |
| Insert missing timestamps on canonical hourly grid | cleaning + `core/data_loading.py` | Yes | Structural grid completion only. |
| Interpolate short bounded gaps in cleaned source | `day_ahead_prices_pipeline.py` | Conditionally safe | Safe for engineering continuity if flagged; unsafe if scored as observed truth. |
| Keep gap provenance flags (`gap_fix_action`, `is_interpolated_value`, `is_flagged_missing_value`) | cleaning | Yes | Good provenance. |
| Build feature-only fallback series from same-hour previous day / week / last available value | `core/data_loading.py` | Yes | Strictly forward-only, no future interpolation. |
| Join actuals as forecast labels | `core/evaluation.py` | Yes after fix | Interpolated / flagged targets are now excluded from scored truth. |
| Fit endogenous features from shifted / rolling past windows | `core/endogenous_features.py` | Yes | All windows are strictly lagged. |

### Key data conclusion

The hourly cleaned source keeps interpolation and missingness provenance correctly. The important methodological distinction is:

- cleaned values may be acceptable for feature-source continuity
- they should not automatically be treated as observed evaluation truth

This audit fixes the pipeline so:

- interpolated or flagged hourly DA prices are no longer marked `is_observed_target = True`
- `y_true` is set to missing for those rows during evaluation

## Target Construction Audit

### What the pipeline does

Target construction is handled in two stages:

1. `generate_forecast_origins(...)`
   - creates eligible daily origins by split
   - uses delivery start local date as the primary indexing key
   - excludes origins whose full 5-day horizon would cross a split boundary

2. `build_target_schedule_for_origin(...)`
   - creates every hourly target row in the `D..D+4` horizon
   - assigns `lead_day`, `lead_day_label`, `horizon_index`, local delivery day, and split label
   - stores `target_known_at_utc` for the target day

### Leakage risk assessment

- actual target prices are joined only as labels, not as history features
- split assignment is delivery-date based and horizon-aware
- origins that would create mixed-split targets are blocked explicitly
- DST handling is explicit through local-day UTC bounds, so horizon size can be `119`, `120`, or `121` hours

Conclusion:

- target construction is methodologically sound for both `D`-only and full `D..D+4`

## Feature Availability Audit

### Feature family classification

| Feature family | Status | Notes |
| --- | --- | --- |
| Calendar and holiday features | Definitely causal | Known at all origins. |
| Hourly DA lag features from price history | Causal under stated DA `known_at` assumption | Safe once the day-level price `known_at` convention is accepted. |
| Endogenous rolling summaries | Causal under stated DA `known_at` assumption | Windows use strictly historical rows. |
| Previous-week naive anchors | Definitely causal | One-week lag is safely earlier than origin. |
| Previous-year naive anchors | Definitely causal | Same reasoning as previous-week. |
| DA total load forecast for `D` | Causal under stated forecasting-store correction | Cleaned family metadata and forecasting-store timing differ; this needs documentation. |
| DA generation forecast for `D` | Causal under stated forecasting-store correction | Same comment as DA load. |
| Week-ahead load forecast | Causal under stated family timing | Available across the full 5-day horizon in the current setup. |
| Actual load / actual generation | Potentially leaking if added naively | Must always be checked against family-specific `known_at`. |
| Installed capacity | Conservative but not clearly market-faithful | Current full-horizon backshift assumption is acceptable only if documented as a simplifying rule. |

### Important nuance

The repo does not use one universal market-faithful publication clock for every feature family. It uses:

- a conservative internal day-level `known_at` convention for hourly DA prices
- family-specific `known_at` rules in cleaned exogenous data
- forecasting-store corrections for some DA feature families so they align with the hourly origin semantics

That is acceptable for the thesis if it is documented explicitly. It should not be described as externally validated publication timing unless that validation is actually done.

## D-Only Leakage Audit

Audit question: at the `D-1 08:00` origin, does the hourly `D` forecast use any information from day `D` that is not available under the repo's stated information set?

Findings:

- history is filtered with `known_at_utc <= forecast_origin_utc`
- for the first test origin, history stops at local delivery day `D-1`
- day `D` actual prices are not present in history
- day `D` actual load and generation are not available unless an explicit `known_at` rule allows them
- DA load and DA generation forecasts for day `D` are available only because the forecasting store corrects their `known_at` to the `D-1 08:00` decision point
- the active naive benchmark set does not use blind previous-day offsets

Conclusion:

- the hourly `D` forecast is leakage-free under the repo's stated assumptions

## Multi-Day D..D+4 Leakage Audit

Audit question: does the hourly multi-day pipeline accidentally use realized values from `D`, `D+1`, `D+2`, or `D+3` as features when forecasting deeper leads?

Findings:

- the history filter is origin-based, not lead-based, so only rows already known at the origin are eligible
- recursive models generate future feature paths from their own prior predictions rather than realized future prices
- exogenous feature context is built per origin from availability-filtered stores
- target schedules for one origin are scored consistently across all lead days
- origins that would otherwise create partial-horizon split leakage are removed before evaluation

Conclusion:

- the hourly `D..D+4` forecast is leakage-free under the repo's stated assumptions

## Benchmark and rMAE Audit

### Benchmark table

| Benchmark | Causal status | Horizon-aware | Used for official rMAE denominator? | Validation-only selection? |
| --- | --- | --- | --- | --- |
| `naive_previous_week` | Yes | Yes | Candidate | Yes |
| `naive_previous_year` | Yes | Yes | Candidate | Yes |
| Scenario-generation naive selector | Not a forecasting benchmark policy | No | No for core forecasting | Validation if available, but not the canonical forecasting selector |

### Findings

- the forecasting pipeline chooses the official naive reference from validation only
- the candidate set is limited to `naive_previous_week` and `naive_previous_year`
- reporting-level selection can be frozen at `stitched_all_horizon`
- this is methodologically sound for hourly forecast comparison

Important caution:

- `core/scenario_generation.py` contains its own helper logic for evaluation-slice and naive candidate selection
- `choose_target_evaluation_slice(...)` currently defaults to `preferred_splits=("test", "validation")`
- that helper is acceptable for scenario-facing analysis, but it should not be reused as benchmark or winner-selection logic for quarter-hour forecasting

## Evaluation and Diebold-Mariano Audit

Good parts:

- pairwise DM comparisons align the same target rows by split, origin, timestamp, lead day, and truth value
- overall and per-lead comparisons are generated consistently

Limitations:

- the DM implementation uses a fixed `hac_lag=24`
- overlapping multi-day forecast horizons create serial dependence that deserves an explicit caveat in interpretation
- those limitations are not yet surfaced clearly in end-user reporting

Conclusion:

- the evaluation mechanics are internally consistent
- the reporting should state the DM interpretation limits more clearly

## Split-Boundary Audit

Findings:

- splits are chronological and defined on local delivery dates
- origin generation is also split-aware
- only origins whose full horizon stays inside one split are allowed
- daily walk-forward re-fit uses all data known at each origin, including later chronology inside the broader train/validation/test era
- this is operationally valid and should not be misclassified as leakage
- structural tuning and benchmark selection remain validation-based and should stay that way

Conclusion:

- split handling is methodologically sound

## Issues Found

| Severity | Issue | Status |
| --- | --- | --- |
| Critical evaluation-provenance issue | Interpolated cleaned DA prices were being scored as observed targets | Fixed in this audit |
| Methodological ambiguity | Hourly `known_at` for prices is a conservative internal convention, not yet externally validated publication timing | Not fixed; must be documented |
| Documentation/provenance gap | Cleaned exogenous `known_at` metadata and forecasting-store corrected `known_at` are not explained together in one place | Partly improved in `availability_assumption.md`; still worth documenting in future exogenous docs |
| Reuse risk | Scenario-generation helper prefers test before validation when choosing a default evaluation slice | Not changed here; do not reuse for forecast benchmark selection |
| Reporting limitation | DM test caveats are not surfaced strongly enough | Not fixed here |
| Governance gap | Repo scope docs still say quarter-hour work is out of scope | Not fixed in this audit |

## Required Fixes Before Quarter-Hour Extension

Minimum required before reusing the hourly framework for quarter-hour forecasting:

1. accept or revise the hourly price `known_at` convention explicitly
2. keep the interpolated-target scoring fix in place
3. freeze quarter-hour benchmark selection and hourly-backbone selection on validation-only logic, not scenario helpers
4. document the cleaned-source vs forecasting-store `known_at` distinction for exogenous families
5. define a deterministic observed 15-minute split rule before any quarter-hour comparison run

## Safe Components the Quarter-Hour Extension Can Reuse

- split-aware origin generation
- target schedule construction
- local-date / UTC DST-safe utilities
- `known_at_utc <= forecast_origin_utc` history filter
- validation-only official naive selection for parent benchmark runs
- shared long-format prediction storage pattern
- runtime timing capture
- reporting-level aggregation pattern

## Components That Must Not Be Reused Blindly

- scenario-generation target-slice defaults
- any assumption that cleaned exogenous `known_at` already equals final forecasting-store availability
- DM interpretation without an overlap caveat
- observed-target scoring if interpolated or flagged target rows are present

## Recommended Deterministic Quarter-Hour Split Policy

If observed 15-minute history is shorter than the hourly period, use this rule:

1. build the eligible origin calendar first
2. keep only origins whose full `D..D+4` quarter-hour horizon has target timestamps inside the observed 15-minute period
3. split by delivery-start local date, not by target timestamp
4. assign the final contiguous 20% of eligible origins to test
5. assign the preceding contiguous 20% to validation
6. assign the remaining earliest eligible origins to train
7. if validation or test has fewer than 28 eligible origins, treat the exercise as engineering validation rather than strong model-comparison evidence

This stays deterministic, chronological, and horizon-aware.

## Recommended Interpolated / Gap-Filled 15-Minute Data Policy

- allow interpolated values in the cleaned 15-minute source only as feature-source continuity input if needed
- do not score interpolated or flagged quarter-hour target values as observed truth
- keep explicit flags in the canonical forecasting table
- report scored coverage using observed-only targets

This mirrors the hourly fix applied in this audit.

## Recommended Quarter-Hour rMAE Denominator Candidate Set

Keep the official denominator conservative and validation-selected from a fixed naive set:

- previous-available same-quarter
- previous-week same-quarter
- last fully available daily profile

Treat repeated-hourly disaggregation as a structural comparison benchmark, not automatically as the official rMAE denominator.

## Recommended Previous-Available Same-Quarter Fallback Chain

For quarter-hour benchmarks and lag features:

1. same quarter-hour from the previous local day if known at the origin
2. otherwise the most recent prior local day with that same quarter-hour known at the origin
3. otherwise previous-week same-quarter
4. otherwise last fully available daily profile
5. otherwise mark unavailable rather than silently fabricating a value

## Final Audit Verdict

- Hourly `D`-only forecasting is leakage-free under the repo's stated assumptions.
- Hourly `D..D+4` forecasting is leakage-free under the repo's stated assumptions.
- The hourly `known_at` logic is conservative and internally consistent, but not yet proven to be exact external market timing.
- The hourly framework is reusable for quarter-hour extension after the documented assumptions are carried forward and benchmark-selection governance stays validation-based.
