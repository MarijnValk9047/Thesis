# NL Incident Reserve Capacity Timing Metadata Alignment Audit V2

## Decision

The correct timing rule for Dutch incident reserve / `mFRRda` capacity is `D-1 09:00 Europe/Amsterdam` for the capacity auction and capacity-bid decision metadata.

The frozen `mFRR` capacity forecasting and threshold-scenario artifacts still encode a `D-1 10:00 Europe/Amsterdam` assumption in local timing metadata and note text. Based on the inspected feature surfaces, this is a metadata-alignment issue, not a forecast-value or scenario-value issue.

Recommended status for the timing issue: `metadata_only_repair_needed` before any later MILP export.

Important scope note: this audit only addresses timing metadata alignment. It does not resolve the separate capacity-price unit and revenue-scaling issue. Before MILP export, the pipeline must also confirm whether threshold prices are still ENTSO-E-native `EUR/MW/ISP` or have already been converted to `EUR/MW/contracted_period`.

## Product Scope

This audit applies only to Dutch incident reserve / `mFRRda` capacity timing metadata.

It does not apply to:
- incident reserve 15-minute energy bidding and activation logic;
- MARI / standard `mFRR` energy bidding;
- `aFRR`;
- capacity-price unit conversion;
- capacity-revenue scaling;
- MILP objective implementation details.

## Correct Timing Rule

From the repo-local market-rules reference and the inspected TenneT incident-reserve manual:
- incident-reserve capacity auction timing is `D-1 09:00 Europe/Amsterdam`;
- this timing should govern `forecast_origin` / `known_at_cutoff` metadata for the capacity-bid decision surface;
- this does not redefine incident-reserve energy BEGCT;
- this does not define MARI / standard `mFRR` timing.

## Where D-1 10:00 Appears

### Frozen notes
- `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`
  - explicitly states `mFRR` capacity cutoff at `D-1 10:00 Europe/Amsterdam`.

### Frozen tabular metadata
- `nl_ir_capacity_target_daily_direction.csv`
  - `forecast_origin_local` values are `10:00` local;
  - `known_at_assumption = assumed_mfrr_capacity_cutoff_d_minus_1_10am_europe_amsterdam_and_result_known_before_dam_closure`.
- `nl_ir_capacity_features_endogenous_da_aligned_daily_direction.csv`
  - same `10:00` local pattern;
  - same `known_at_assumption` value.
- `nl_ir_capacity_features_exogenous_small_da_aligned_daily_direction.csv`
  - same `10:00` local pattern;
  - same `known_at_assumption` value.
- `nl_ir_capacity_forecast_naive7d_da_aligned_daily_direction_long.csv`
  - `forecast_origin_local` values are `10:00` local.
- `nl_ir_capacity_forecast_lear_exogenous_small_da_aligned_daily_direction_long.csv`
  - `forecast_origin_local` values are `10:00` local.
- `nl_ir_capacity_forecast_xgboost_exogenous_small_da_aligned_daily_direction_long.csv`
  - `forecast_origin_local` values are `10:00` local.
- `nl_ir_capacity_12_3_f_threshold_scenarios_da_aligned_daily_direction_long.csv`
  - `forecast_origin_local` values are `10:00` local;
  - `known_at_cutoff_utc` is propagated from the frozen forecast anchor.

### Builder / runner logic
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_mfrr_capacity_exogenous_small_features_daily_v1.py`
  - explicitly validates week-ahead load rows against a `D-1 10:00 Europe/Amsterdam` cutoff.
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/run_mfrr_capacity_da_aligned_forecasts_daily_v1.py`
  - propagates `forecast_origin_local`, `known_at_cutoff_utc`, and `known_at_assumption` from the feature tables into forecast outputs.
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_mfrr_capacity_12_3_f_threshold_scenarios_daily_v1.py`
  - propagates timing metadata from the frozen forecast artifact into the threshold scenario artifact.

## Where D-1 09:00 Appears

- `docs/market_rules/nl_incident_reserve_capacity_market_rules_v2.md`
  - records the incident-reserve capacity auction at `D-1 09:00 Europe/Amsterdam`;
  - flags the older `D-1 10:00` project assumption for alignment.

Important nuance:
- the frozen artifacts contain `forecast_origin_utc` / `known_at_cutoff_utc` values such as `09:00:00Z` in winter and `08:00:00+00:00` in DST periods;
- these UTC timestamps correspond to `10:00` local artifact metadata, not `09:00` local incident-reserve timing;
- therefore the issue is local-market timing semantics, not merely the presence of `09:00` in a UTC string.

## Feature Safety Under D-1 09:00

### Endogenous features
Classification: `safe_under_09_cutoff`

Reasoning:
- lagged target-price features;
- rolling target statistics;
- calendar fields;
- direction encoding.

These are historical or static fields and remain known before `D-1 09:00`.

### DA lag features
Classification: `safe_under_09_cutoff`

Checked fields:
- `nl_da_price_daily_avg_lag_1d`;
- `nl_da_price_daily_avg_lag_7d`.

Reasoning:
- these are strictly delivery-day lags from prior days;
- moving the cutoff from `10:00` to `09:00` does not invalidate them.

### Week-ahead load forecast features
Classification: `safe_under_09_cutoff`

Checked fields:
- `nl_week_ahead_load_daily_mean`;
- `nl_week_ahead_load_daily_peak`.

Evidence from the cleaned source and feature-builder logic:
- cleaned source `known_at_rule` is `week_ahead_local_08`;
- all inspected `known_at_utc` rows were available before both `D-1 09:00` and `D-1 10:00`;
- emulated safe-row selection under `09:00` and `10:00` produced identical selected rows;
- selected-row change count under `09:00` versus `10:00` was `0`.

Conclusion:
- the exogenous-small feature set remains safe under `D-1 09:00`;
- no feature rebuild is required based on the inspected known-at logic.

## Artifact Impact Classification For Timing Only

- `nl_ir_capacity_target_daily_direction.csv`
  - `metadata_only_repair_needed`
- `nl_ir_capacity_features_endogenous_da_aligned_daily_direction.csv`
  - `metadata_only_repair_needed`
- `nl_ir_capacity_features_exogenous_small_da_aligned_daily_direction.csv`
  - `metadata_only_repair_needed`
- `nl_ir_capacity_forecast_naive7d_da_aligned_daily_direction_long.csv`
  - `metadata_only_repair_needed`
- `nl_ir_capacity_forecast_lear_exogenous_small_da_aligned_daily_direction_long.csv`
  - `metadata_only_repair_needed`
- `nl_ir_capacity_forecast_xgboost_exogenous_small_da_aligned_daily_direction_long.csv`
  - `metadata_only_repair_needed`
- `nl_ir_capacity_12_3_f_threshold_scenarios_da_aligned_daily_direction_long.csv`
  - `metadata_only_repair_needed`
- `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`
  - `documentation_only_update_needed`
- `docs/forecasting/mfrr_capacity_12_3_f_threshold_scenario_freeze_daily_v1.md`
  - `documentation_only_update_needed`
- `docs/forecasting/mfrr_capacity_12_3_f_threshold_scenario_audit_daily_v1.md`
  - `documentation_only_update_needed`
- `docs/forecasting/mfrr_capacity_12_3_f_down_scenario_collapse_diagnostic_daily_v1.md`
  - `documentation_only_update_needed`
- `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md`
  - `documentation_only_update_needed`
- `docs/forecasting/mfrr_capacity_12_3_f_scope_inspection_daily_v1.md`
  - `no_change_needed`
- `docs/market_rules/nl_incident_reserve_capacity_market_rules_v1.md`
  - `superseded_by_v2_due_to_price_unit_and_revenue_scaling_update`
- `docs/market_rules/nl_incident_reserve_capacity_market_rules_v2.md`
  - `timing_rule_aligned`

## Repair Policy Recommendation For Timing Metadata

Recommended follow-up for the timing issue: `metadata_only_repair_needed`.

The repair should:
- update `forecast_origin_local` to `D-1 09:00 Europe/Amsterdam`;
- update `known_at_cutoff_utc` accordingly;
- update `known_at_assumption` text from `10am` to `09am` where present;
- update frozen note text that still states `D-1 10:00`;
- preserve all forecast values;
- preserve all threshold-scenario values;
- not rebuild features;
- not rerun models;
- not regenerate scenarios.

Why this is sufficient for timing:
- endogenous features remain safe under `09:00`;
- DA lag features remain safe under `09:00`;
- week-ahead load features were already known by `08:00` local and selected identically under both cutoffs;
- the threshold scenario artifact only inherits timing metadata from the frozen forecast anchor.

## Separate Required Repair: Price Unit And Revenue Scaling

This timing audit does not repair the capacity-price unit issue.

Before any later MILP export, perform or verify a separate price-unit repair:
- confirm whether threshold prices are still ENTSO-E-native `EUR/MW/ISP`;
- confirm whether any upstream artifact already converted prices to `EUR/MW/contracted_period`;
- avoid ambiguous unit labels such as `EUR_per_MW_per_period` unless `period` is explicitly defined;
- if prices remain `EUR/MW/ISP`, include `contract_isp_count` in the MILP export;
- compute `contract_isp_count` from `delivery_start` and `delivery_end`, not from hardcoded daily assumptions;
- use `capacity_revenue = accepted * bid_price_eur_per_mw_isp * offered_capacity_mw * contract_isp_count`.

## Export Readiness Decision

Before any later MILP export:
- perform the metadata-only timing alignment repair;
- perform or verify the capacity-price unit and revenue-scaling repair;
- then freeze the repaired metadata and unit surface as the incident-reserve-capacity MILP input contract.

Minimum export-readiness fields should include either:
- native unit setup:
  - `acceptance_threshold_price_eur_per_mw_isp`;
  - `candidate_bid_price_eur_per_mw_isp`;
  - `offered_capacity_mw`;
  - `contract_isp_count`;
  - `delivery_start`;
  - `delivery_end`;
- or converted unit setup:
  - `acceptance_threshold_price_eur_per_mw_contracted_period`;
  - `candidate_bid_price_eur_per_mw_contracted_period`;
  - `offered_capacity_mw`;
  - explicit documentation that conversion has already been applied.

No forecast rerun, feature rebuild, or scenario regeneration is justified by the timing audit alone. The price-unit issue may require export/schema changes, but not necessarily forecast or scenario recomputation.
