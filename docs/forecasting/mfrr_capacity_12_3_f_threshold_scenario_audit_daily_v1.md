# mFRR Capacity 12.3.F Threshold Scenario Audit Daily V1

## Scope
This note audits the generated Dutch IR/mFRR capacity accepted-threshold proxy scenario artifact before any downstream MILP export or integration step.

It is a short audit only. It does not regenerate scenarios, run models, or create a MILP export.

## Artifact Integrity
Scenario artifact checked:
- path: `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_threshold_scenarios_da_aligned_daily_direction_long.csv`
- row count: `2190`
- date range: `2024-10-01` to `2025-09-30`
- directions: `Up`, `Down`
- scenario IDs:
  - `threshold_conservative_p75`
  - `threshold_central_p90`
  - `threshold_optimistic_max`
- rows per `delivery_date_local x direction`: exactly `3`
- probability sums per `delivery_date_local x direction`: always `1.0`
- duplicate `delivery_date_local x direction x scenario_id` keys: `0`
- missing `threshold_price_scenario`: `0`
- missing `average_price_forecast`: `0`
- observed-threshold-truth columns present: `none`

## Scenario Spread And Ordering
Ordering:
- `conservative <= central`: passed for all rows
- `central <= optimistic`: passed for all rows
- no monotonic projection was used
- negative threshold scenarios: `0`

Spread structure is deterministic within direction x daytype because all three scenarios use the same average-price anchor and the same daytype markup family.

### Spread summary by direction, daytype, and overlap scope
| Direction | Daytype | Scope | Count | Conservative->Central Mean | Central->Optimistic Mean | Conservative->Optimistic Mean |
|---|---|---|---:|---:|---:|---:|
| Down | weekday | synthetic / observed overlap | `261` total | `0.000` | `0.000` | `0.000` |
| Down | weekend | synthetic / observed overlap | `104` total | `0.015` | `0.000` | `0.015` |
| Up | weekday | synthetic / observed overlap | `261` total | `0.200` | `1.060` | `1.260` |
| Up | weekend | synthetic / observed overlap | `104` total | `0.050` | `0.040` | `0.090` |

Interpretation:
- `Down` weekday scenarios are effectively collapsed: conservative, central, and optimistic are equal.
- `Down` weekend spreads are very small.
- `Up` weekday has the widest spread and therefore carries most of the scenario differentiation.
- `Up` weekend spread is positive but modest.
- Spread values are identical across synthetic and observed-overlap periods because the scenario layer reuses the same fixed calibrated markup structure across the full horizon.

## Synthetic Versus Observed-Overlap Labelling
Label checks:
- `2024-10-01` to `2025-01-06`:
  - `threshold_source_scope = synthetic_proxy_pre_12_3_f_overlap`
  - `threshold_observed_overlap_flag = false`
  - row count: `588`
- `2025-01-07` to `2025-09-30`:
  - `threshold_source_scope = observed_overlap_proxy_evaluable`
  - `threshold_observed_overlap_flag = true`
  - row count: `1602`

This labelling is internally consistent and explicit enough for downstream use.

## MILP-Readiness Check
Required fields checked and present:
- `forecast_origin_utc`
- `forecast_origin_local`
- `known_at_cutoff_utc`
- `delivery_start_utc`
- `delivery_end_utc`
- `delivery_date_local`
- `delivery_block_id`
- `direction`
- `average_price_model_name`
- `average_price_forecast`
- `threshold_model_name`
- `scenario_id`
- `scenario_role`
- `scenario_probability`
- `threshold_proxy_name`
- `markup_rule_name`
- `calibrated_markup_value`
- `threshold_price_scenario`
- `threshold_source_scope`
- `threshold_observed_overlap_flag`
- `scenario_generation_method`
- `granularity`
- `market_design_regime`
- `source_data_version`
- `quality_flags`
- `methodological_caveat`

Assessment:
- the artifact is structurally ready for a later MILP export contract step;
- it already contains the minimum identity, timing, direction, scenario, probability, and caveat fields required for downstream integration;
- the main remaining work is not schema repair but deciding whether to freeze this scenario artifact as-is or wrap it in a controlled MILP export contract.

## Methodological Caveats
- `12.3.F` contains accepted/procured offers only.
- Rejected bids are unobserved.
- These scenarios are accepted-threshold proxies, not full submitted bid ladders.
- `max` is an optimistic upper-bound proxy, not a true market-clearing threshold.
- `2024-10-01` to `2025-01-06` thresholds are synthetic/proxy only and must not be evaluated as observed truth.
- Scenario probabilities are scenario weights, not direct empirical probabilities.
- No plant feasibility, activation, or MILP bidding logic is included yet.

## Audit Conclusion
The artifact is clean enough to move forward.

Main strengths:
- exact row count and probability integrity;
- zero ordering violations;
- explicit synthetic-vs-observed-overlap labelling;
- downstream-ready metadata surface.

Main caution:
- scenario differentiation is concentrated mainly in `Up`, especially weekday `Up`, while `Down` is nearly collapsed. This is not a data-integrity issue, but it limits how much stochastic richness this v1 threshold layer adds for `Down`.

## Next Task Recommendation
Recommended next task:
- `MFRR_CAPACITY_12_3_F_THRESHOLD_SCENARIO_FREEZE_OR_MILP_EXPORT_DAILY_V1`

Recommended direction:
- because the artifact is structurally clean, proceed to either:
  1. a short freeze note that formally freezes this threshold-scenario artifact for downstream optimisation use; or
  2. a narrowly scoped MILP export contract task that maps this artifact into the hydrogen/MILP input surface without changing the scenario values.
