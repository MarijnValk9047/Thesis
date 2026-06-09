# MFRR Capacity 12.3_F Threshold Scenario Freeze Daily V1

## Freeze Decision
The current threshold scenario artifact is frozen as `MFRR_CAPACITY_12_3_F_THRESHOLD_SCENARIOS_DAILY_V1` for first downstream MILP integration tests.

This freeze covers the current accepted-threshold proxy scenario layer only. It does not freeze a full bidding model, a capacity-clearing model, a MARI energy model, or a final optimisation design.

## Artifact Identity
Frozen artifact:
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_threshold_scenarios_da_aligned_daily_direction_long.csv`

Build script:
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_mfrr_capacity_12_3_f_threshold_scenarios_daily_v1.py`

Frozen identity:
- horizon: `2024-10-01` to `2025-09-30`
- grain: `daily x direction x scenario`
- row count: `2190`
- directions: `Up`, `Down`
- scenario IDs:
  - `threshold_conservative_p75`
  - `threshold_central_p90`
  - `threshold_optimistic_max`
- scenario probabilities:
  - conservative `0.25`
  - central `0.50`
  - optimistic `0.25`
- average-price threshold anchor: `naive_lag_7d_same_direction`
- threshold model: `12_3_f_additive_markup_threshold_proxy_v1`
- markup rule family: `direction_daytype_median_markup`
- market design regime: `nl_ir_daily_capacity_threshold_scenarios_v1`
- scenario generation method: `deterministic_three_role_additive_markup_scenarios_v1`

## Scope And Interpretation
This artifact is for Dutch incident reserve / mFRRda capacity threshold-proxy work.

It is not:
- the MARI standard mFRR energy product
- aFRR
- full bid-ladder forecasting
- rejected-bid modelling
- a market-clearing threshold truth layer

It is an accepted-offer threshold proxy built from `12.3_F` accepted/procured offers only.

## Scenario Roles
1. `threshold_conservative_p75`
- probability: `0.25`
- proxy: `accepted_price_p75_eur_per_maw`
- role: `conservative`

2. `threshold_central_p90`
- probability: `0.50`
- proxy: `accepted_price_p90_eur_per_maw`
- role: `central_upper_normal`

3. `threshold_optimistic_max`
- probability: `0.25`
- proxy: `max_accepted_price_proxy_eur_per_maw`
- role: `optimistic_upper_bound`

## Data Availability And Truth-Status Labels
Truth-status handling is frozen as follows:
- `2024-10-01` to `2025-01-06`: `synthetic_proxy_pre_12_3_f_overlap`
- `2025-01-07` to `2025-09-30`: `observed_overlap_proxy_evaluable`

Interpretation rules:
- no observed threshold-truth columns are included in the scenario artifact
- pre-`2025-01-07` scenario rows must not be evaluated as observed threshold truth
- `threshold_observed_overlap_flag = false` before `2025-01-07`
- `threshold_observed_overlap_flag = true` from `2025-01-07` onward

## Down Scenario Collapse Caveat
Down scenario spread is weak.

The diagnostic result is frozen as:
- the weak Down spread is mostly data-driven
- observed Down accepted-offer stacks are often flat
- deterministic daytype median markups further compress rare nonzero Down tail spreads
- the current `v1` scenario artifact remains acceptable for first MILP integration
- if a repair is later needed, the preferred `v2` candidate is fixed observed spread add-ons rather than a more complex sampling framework

## Downstream Use Rules
A later MILP export or integration step should:
- read this frozen scenario artifact and not recompute threshold scenarios
- preserve `scenario_id` and `scenario_probability`
- preserve `threshold_source_scope` and `threshold_observed_overlap_flag`
- preserve the methodological caveat fields
- use `threshold_price_scenario` only as an acceptance-threshold proxy, for example `bid_price <= threshold_price_scenario`
- not treat threshold scenarios as full submitted bid-ladder truth
- not treat `max` as a true market-clearing threshold
- not use synthetic pre-overlap rows for observed-threshold evaluation

## Known Limitations
Known limitations remain:
- accepted/procured offers only
- rejected bids unobserved
- scenario probabilities are scenario weights, not empirical probabilities
- the capacity-price threshold proxy does not include activation probability
- activation, imbalance settlement, delivery profile, sanctions, portfolio feasibility, and BRP effects are not yet modelled
- daily granularity is aligned with incident-reserve capacity modelling, not 15-minute MARI energy bidding

## First MILP Integration Readiness
This artifact is frozen as the `v1` threshold-scenario input candidate for first MILP integration tests.

That means it is ready for a downstream contract-definition step, not that the economic or market-rule interpretation is already complete. A later MILP task must still define the bidding timeline, acceptance logic, settlement approximation, and product-specific rule distinctions explicitly.

## Recommended Next Task
Recommended next task:
- `MFRR_CAPACITY_MARKET_RULES_AND_MILP_INTEGRATION_AUDIT_V1`

Scope:
- inspect current MILP needs and the relevant TenneT incident reserve, incident reserve energy, MARI, and imbalance documents only if placed in the repo or explicitly provided as accessible inputs
- distinguish incident reserve capacity, incident reserve energy bids, MARI standard mFRR energy, and aFRR
- derive a minimal rule-compliant MILP input contract and bidding-sequence assumptions
- do not implement optimisation yet
