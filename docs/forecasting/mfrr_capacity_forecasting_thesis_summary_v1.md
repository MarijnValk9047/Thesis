# Dutch Incident Reserve / mFRR Capacity Forecasting Thesis Summary v1

Evidence base: tracked notes and scripts under `docs/forecasting/`, `docs/market_rules/`, `docs/optimisation/`, and `scripts/Data/02_Forecasting/02_mFRR_IR_NL/`, plus compact schema checks of local generated CSV artifacts in `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/`. No forecasting model was rerun.

Companion registry: `docs/forecasting/mfrr_capacity_metric_registry_v1.md` records the compact model, split, metric, threshold-proxy, and MILP-input selections used for thesis traceability.

## 1. Scope

This summary concerns Dutch Incident Reserve / `mFRRda` capacity forecasting and accepted-threshold proxy preparation for downstream MILP experiments.

Coverage status:

- Capacity price / paid capacity target: implemented for daily `17.1_BC` average procurement price by direction. See `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`.
- Accepted capacity bid threshold proxy: implemented using `12.3_F` accepted/procured offers, with `p75`, `p90`, and max accepted-price proxy roles. See `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md`.
- Capacity acceptance scenarios: implemented as three deterministic threshold-proxy scenario roles for the DA-aligned test horizon. See `docs/forecasting/mfrr_capacity_12_3_f_threshold_scenario_freeze_daily_v1.md`.
- Energy-bid activation forecasting: not implemented.
- MARI: not implemented and explicitly out of scope for this layer. See `docs/market_rules/nl_incident_reserve_capacity_market_rules_v2.md` and `docs/optimisation/nl_ir_capacity_milp_export_contract_v2.md`.

The work is therefore a capacity-price and acceptance-proxy layer, not a full balancing-market, activation, or MARI model.

## 2. Data Sources And Target Definition

The main forecast target uses ENTSO-E / TenneT `17.1_BC` as the aggregate market-outcome source for final procured capacity and average paid capacity price. Repo market-rule notes state that `17.1_BC` should be interpreted as the final aggregate market outcome, not as an individual bid ladder. The local target artifact is:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_target_daily_direction.csv`

Compact schema inspection found:

- source dataset: `17_1_BC`;
- grain: `delivery_date_local x direction`;
- directions: `Up`, `Down`;
- delivery block: `daily_full_day`;
- market design regime: `nl_ir_daily_capacity_v1`;
- target column: `average_procurement_price`;
- target unit in the forecast artifacts: `EUR_per_MW_per_period`.

Later market-rule and MILP export work repaired the unit interpretation for downstream revenue calculation: ENTSO-E capacity prices are treated as `EUR/MW/ISP`, and capacity revenue must multiply by `contract_isp_count`. The v2 MILP export therefore exposes `acceptance_threshold_price_eur_per_mw_isp`, `capacity_price_unit = EUR_per_MW_per_ISP`, and `contract_isp_count`.

The `12.3_F` data are used differently. They provide accepted/procured offer rows, not a full submitted bid ladder. The cleaned offer-level source supports accepted-price quantiles and max accepted-price proxies, but rejected bids are unobserved. The threshold layer is therefore proxy-based. The relevant inspected docs are:

- `docs/forecasting/mfrr_capacity_12_3_f_scope_inspection_daily_v1.md`
- `docs/market_rules/nl_incident_reserve_capacity_market_rules_v2.md`

The `12.3_F` observed overlap used for threshold work is daily and direction-specific, not hourly or ISP-level activation forecasting. Compact schema inspection confirmed `534` observed threshold rows from `2025-01-07` through `2025-09-30`, equal to `267` days x `2` directions.

Observed versus proxy status:

- `17.1_BC` average procurement price is the observed aggregate capacity-price target.
- `12.3_F` accepted-price quantiles are observed accepted-offer summaries during the 2025 overlap.
- Threshold scenarios before `2025-01-07` are synthetic/proxy rows, not observed threshold truth.
- Accepted-threshold scenarios are not true market-clearing thresholds because rejected bids are unavailable.

## 3. Forecasting Split And Forecast-Origin Logic

The inspected DA-aligned average-price layer uses a chronological split:

- train: `2022-01-01` to `2023-09-30`;
- validation: `2023-10-01` to `2024-09-30`;
- test: `2024-10-01` to `2025-09-30`.

This is supported by `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`, `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_mfrr_capacity_da_aligned_split_features_daily_v1.py`, and `scripts/Data/02_Forecasting/02_mFRR_IR_NL/run_mfrr_capacity_da_aligned_forecasts_daily_v1.py`. Compact schema checks confirmed DA-aligned feature and forecast row counts of `2738`, split as train `1276`, validation `732`, and test `730`.

No inspected evidence supports the suspected `2022-10-05` train start for the frozen DA-aligned average-price layer. The local target artifact extends beyond the frozen model split, from `2022-01-01` to `2025-12-31`, but the DA-aligned modelling horizon ends at `2025-09-30`.

Forecast-origin logic was corrected during the market-rule audit:

- earlier notes and metadata used `D-1 10:00 Europe/Amsterdam`;
- `docs/market_rules/nl_incident_reserve_capacity_timing_metadata_alignment_audit_v2.md` and `docs/market_rules/nl_incident_reserve_capacity_market_rules_v2.md` record the corrected Dutch incident-reserve capacity auction timing as `D-1 09:00 Europe/Amsterdam`;
- the repair is documented as metadata-only for existing forecast and threshold values because the inspected feature surfaces were considered safe under `D-1 09:00`.

DA-aligned variants are intended to use only known-at-time features. The small exogenous feature builder filters week-ahead load by the `D-1 09:00` cutoff and excludes unsafe same-day DA load/generation, realised load/generation, `12.3_F`, threshold, and activation fields.

## 4. Feature Sets And Model Variants

Model and feature families found:

- Naive / 7-day benchmark: `naive_lag_7d_same_direction`, using the same-direction 7-day lag; included as a mandatory weekly-structure benchmark.
- LEAR-style endogenous model: LASSO/ElasticNet-style linear model over endogenous lag, rolling, spread, calendar, and direction features; included as a transparent linear comparator.
- XGBoost endogenous model: nonlinear tree model on the same endogenous feature family; included to test nonlinear gains.
- Exogenous-small LEAR: linear model using endogenous features plus lagged realised NL DA prices and week-ahead load summaries; included as a transparent known-at-safe exogenous extension.
- Exogenous-small XGBoost: nonlinear model using the same small exogenous feature set; selected as the average-price frontrunner.
- ARIMAX / load-only comparator: SARIMAX with week-ahead load mean and peak; retained as a classical comparator but rejected as the final average-price model.

The small exogenous feature set is documented in `docs/forecasting/mfrr_capacity_endogenous_freeze_and_exogenous_audit_daily_v1.md` and implemented in `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_mfrr_capacity_exogenous_small_features_daily_v1.py`. The DA-aligned forecasting scripts write outputs such as:

- `nl_ir_capacity_forecast_naive7d_da_aligned_daily_direction_long.csv`
- `nl_ir_capacity_forecast_lear_da_aligned_daily_direction_long.csv`
- `nl_ir_capacity_forecast_xgboost_da_aligned_daily_direction_long.csv`
- `nl_ir_capacity_forecast_lear_exogenous_small_da_aligned_daily_direction_long.csv`
- `nl_ir_capacity_forecast_xgboost_exogenous_small_da_aligned_daily_direction_long.csv`
- `nl_ir_capacity_forecast_arimax_load_da_aligned_daily_direction_long.csv`

Earlier non-DA-aligned forecast variants also exist as artifacts and scripts, but the inspected freeze notes make the DA-aligned layer the relevant thesis-facing average-price layer.

## 5. Results Summary

For the `17.1_BC` average procurement price forecast layer, the selected thesis-facing model is `xgboost_exogenous_small_da_aligned_daily_v1`. This records the methodological choice to use XGBoost for the capacity average-price forecast component, while retaining `naive_lag_7d_same_direction` as the mandatory benchmark and threshold/proxy anchor.

Key average-price metrics from `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`:

| Model | Validation MAE | Test MAE | Test RMSE | Test Bias |
|---|---:|---:|---:|---:|
| Naive7d | 1.5128 | 1.0340 | 1.6368 | 0.0215 |
| Endogenous LEAR | 1.2856 | 1.0100 | 1.3215 | 0.2899 |
| Endogenous XGBoost | 1.3154 | 0.9483 | 1.2553 | 0.2648 |
| Exogenous-Small LEAR | 1.2524 | 0.9798 | 1.3142 | 0.1746 |
| Exogenous-Small XGBoost | 1.1475 | 0.8583 | 1.1969 | 0.0315 |
| ARIMAX Load-Only | 1.5198 | 1.1628 | 1.4201 | 0.4538 |

Direction notes from the freeze note:

- exogenous-small XGBoost improved strongly for `Down` relative to endogenous XGBoost, especially on the DA-aligned test period;
- Naive7d remained strong in some calm `Down` regimes and remains a mandatory benchmark;
- ARIMAX was weaker overall, especially for `Down`.

For the `12.3_F` threshold layer, the selected threshold anchor is different from the selected average-price forecast model. `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md` reports that `naive_lag_7d_same_direction` was the most stable threshold-proxy anchor by evaluation MAE and overbid behaviour. Revenue-maximising alternatives using LEAR or XGBoost were more aggressive and often had worse overbid rates.

Threshold-rule evaluation leaders:

- `p75`: best MAE `1.3745`, using `naive_lag_7d_same_direction + direction_median_markup`;
- `p90`: best MAE `1.5857`, using `naive_lag_7d_same_direction + direction_daytype_median_markup`;
- `max`: best MAE `1.6696`, using `naive_lag_7d_same_direction + direction_daytype_median_markup`.

The frozen scenario-role policy uses:

- conservative: `p75 + naive + direction_daytype_median`;
- central / upper-normal: `p90 + naive + direction_daytype_median`;
- optimistic / upper-bound: `max + naive + direction_daytype_median`.

The frozen threshold scenario artifact has `2190` rows over `2024-10-01` to `2025-09-30`, with three scenarios per `delivery_date_local x direction` and probabilities `0.25`, `0.50`, and `0.25`. The main stochastic caveat is weak `Down` spread: `docs/forecasting/mfrr_capacity_12_3_f_down_scenario_collapse_diagnostic_daily_v1.md` concludes that this is mostly data-driven because observed Down accepted-offer stacks are often flat.

Evidence gap: there is no single tracked central metric registry for all mFRR capacity forecast results. Results are recoverable from the freeze/audit notes and generated CSV artifacts, especially:

- `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`
- `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_*_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_threshold_calibration_backtest_daily_direction_long.csv`

## 6. MILP Input Preparation

The downstream MILP input contract is documented in:

- `docs/optimisation/nl_ir_capacity_milp_export_contract_v2.md`
- `docs/optimisation/mfrr_capacity_only_milp_pilot_design_v1.md`
- `docs/optimisation/mfrr_dam_integration_handoff_v1.md`

The current MILP-facing export is:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/milp_exports/nl_ir_capacity_milp_input_daily_direction_scenarios_v2.csv`

The v2 export consumes the frozen threshold scenarios and preserves:

- `delivery_date_local`;
- `direction`;
- `scenario_id`;
- `scenario_role`;
- `scenario_probability`;
- `acceptance_threshold_price_eur_per_mw_isp`;
- `threshold_proxy_name`;
- `threshold_source_scope`;
- `threshold_observed_overlap_flag`;
- average-price threshold anchor, primary model forecast, and comparator model forecast.

The v2 export repairs capacity-revenue scaling by using:

`capacity_revenue = accepted * bid_price_eur_per_mw_isp * offered_capacity_mw * contract_isp_count`

Compact schema inspection confirmed:

- `2190` rows;
- `capacity_price_unit = EUR_per_MW_per_ISP`;
- `contract_isp_count` mostly `96`, with `92` and `100` on DST-related delivery days;
- `activation_modelling_in_scope = False`;
- `mari_modelling_in_scope = False`.

The intended downstream optimisation use is a capacity-only acceptance and revenue proxy:

- bid price is a decision variable;
- acceptance proxy is `bid_price_eur_per_mw_isp <= acceptance_threshold_price_eur_per_mw_isp`;
- accepted capacity creates an energy-bid obligation flag;
- activation probability, activation dispatch, imbalance settlement, sanctions, and MARI are deferred.

`docs/optimisation/mfrr_dam_integration_handoff_v1.md` freezes the hydrogen mFRR/DAM work as a sandbox/interface handoff rather than a final activation-feasible mFRR model.

## 7. Limitations

Remaining limitations supported by the inspected files:

- `12.3_F` contains accepted/procured offers only; rejected bids are unobserved.
- Accepted-price quantiles and max accepted price are threshold proxies, not true market-clearing thresholds.
- The `12.3_F` observed accepted-offer coverage is shorter than the `17.1_BC` average-price target history and starts in 2025.
- Synthetic threshold rows from `2024-10-01` to `2025-01-06` are proxy rows only and must not be evaluated as observed threshold truth.
- Scenario probabilities are scenario weights, not calibrated empirical probabilities.
- Down threshold scenarios have weak stochastic richness because observed Down accepted-offer stacks are often flat.
- No full activation probability, activation dispatch, energy-bid price forecasting, imbalance settlement, sanctions, or MARI forecasting is implemented.
- mFRR capacity is treated as an observed daily product unless explicitly labelled as a counterfactual 4-hour sensitivity.
- Downstream mFRR/DAM integration remains a sandbox/frozen interface layer, not final thesis evidence for full balancing-market value.
- Forecast/output CSVs are generated artifacts; many are local/ignored rather than Git-first thesis provenance.

## 8. Thesis-Ready Paragraph

This thesis used a deliberately simple Dutch Incident Reserve capacity forecasting layer to create exploratory mFRR capacity inputs for the optimisation model without claiming a full balancing-market representation. The main forecast target was the `17.1_BC` aggregate average procurement price because it provides the longest available daily by direction history of realised capacity-market outcomes. The `12.3_F` accepted-offer data were used more cautiously: they give accepted offer prices and volumes from 2025 onward, which is useful for constructing accepted-threshold proxy scenarios, but they do not contain rejected bids and therefore cannot identify the true submitted bid ladder or clearing threshold. This combination was sufficient to test a first capacity-revenue and acceptance-proxy interface in the downstream MILP, including direction, scenario probabilities, price units, and contract duration, but it remains an exploratory capacity-only layer rather than a complete model of mFRR energy bidding, activation, imbalance settlement, or MARI participation.

## 9. File Map

Source data / target files:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_target_daily_direction.csv`
- `data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/parsed/12_3_f_nl_ir_offer_long.csv`
- `data/01_cleaned/Balancing/IR Capacity/12_3_f_nl_ir/aggregated/12_3_f_nl_ir_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/12_3_f_nl_ir_availability_manifest.csv`

Feature files:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_endogenous_daily_direction.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_endogenous_da_aligned_daily_direction.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_exogenous_small_daily_direction.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_exogenous_small_da_aligned_daily_direction.csv`

Forecast output files:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_naive7d_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_lear_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_xgboost_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_naive7d_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_lear_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_xgboost_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_lear_exogenous_small_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_lear_exogenous_small_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_xgboost_exogenous_small_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_arimax_load_da_aligned_daily_direction_long.csv`

Threshold/backtest/MILP files:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_observed_threshold_table_daily_direction.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_threshold_calibration_backtest_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_threshold_scenarios_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/milp_exports/nl_ir_capacity_milp_input_daily_direction_scenarios_v1.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/milp_exports/nl_ir_capacity_milp_input_daily_direction_scenarios_v2.csv`

Scripts:

- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_mfrr_capacity_da_aligned_split_features_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_mfrr_capacity_exogenous_small_features_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/run_mfrr_capacity_da_aligned_forecasts_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/run_mfrr_capacity_lear_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/run_mfrr_capacity_xgboost_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/run_mfrr_capacity_lear_exogenous_small_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/run_mfrr_capacity_xgboost_exogenous_and_arimax_da_aligned_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_mfrr_capacity_12_3_f_observed_threshold_table_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/run_mfrr_capacity_12_3_f_threshold_calibration_2025_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/build_mfrr_capacity_12_3_f_threshold_scenarios_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/export_mfrr_capacity_milp_input_daily_v1.py`
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/export_mfrr_capacity_milp_input_daily_v2.py`
- `scripts/Data/00_data_imports/one_off/2026-06_12_3_f_nl_ir_monthly_audit/README.md`

Docs:

- `docs/forecasting/mfrr_capacity_endogenous_freeze_and_exogenous_audit_daily_v1.md`
- `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`
- `docs/forecasting/mfrr_capacity_12_3_f_scope_inspection_daily_v1.md`
- `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md`
- `docs/forecasting/mfrr_capacity_12_3_f_threshold_scenario_audit_daily_v1.md`
- `docs/forecasting/mfrr_capacity_12_3_f_threshold_scenario_freeze_daily_v1.md`
- `docs/forecasting/mfrr_capacity_12_3_f_down_scenario_collapse_diagnostic_daily_v1.md`
- `docs/market_rules/nl_incident_reserve_capacity_market_rules_v2.md`
- `docs/market_rules/nl_incident_reserve_capacity_timing_metadata_alignment_audit_v2.md`
- `docs/optimisation/nl_ir_capacity_milp_export_contract_v2.md`
- `docs/optimisation/mfrr_capacity_only_milp_pilot_design_v1.md`
- `docs/optimisation/mfrr_dam_integration_handoff_v1.md`
