# mFRR Capacity Metric Registry v1

## 1. Purpose

This registry consolidates the existing Dutch Incident Reserve / `mFRRda` capacity forecasting evidence for thesis writing and downstream MILP traceability. It records which capacity-side models and threshold-proxy methods were tested, what they forecasted, which split they used, what the key reported results were, and which method was selected for each purpose.

This is a compact documentation registry only. It does not rerun forecasting models and does not create new forecast artifacts.

## 2. Scope boundary

Included:

- `17.1_BC` daily x direction average procurement price forecasting;
- `12.3_F` accepted-offer threshold / acceptance-proxy preparation;
- MILP capacity input relevance, especially `EUR/MW/ISP`, `contract_isp_count`, direction, scenario ID, and scenario probability handling.

Excluded:

- activation probability forecasting;
- energy-bid price forecasting;
- imbalance or sanction modelling;
- MARI / standard `mFRR` energy-product forecasting;
- full activation redispatch or activation-feasible plant operation.

## 3. Data and target registry

| item | data source / file | target or field | granularity | direction handling | observed/proxy/synthetic | unit | notes |
|---|---|---|---|---|---|---|---|
| `17.1_BC` target | `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_target_daily_direction.csv` | `average_procurement_price` | daily full-day | `Up`, `Down` | observed aggregate market outcome | forecast artifacts record `EUR_per_MW_per_period`; MILP contract interprets capacity price natively as `EUR/MW/ISP` | Main average-price forecast target. `17.1_BC` is not an individual bid ladder. |
| Endogenous features | `nl_ir_capacity_features_endogenous_daily_direction.csv`; `nl_ir_capacity_features_endogenous_da_aligned_daily_direction.csv` | lag, rolling, spread, calendar, direction features | daily full-day | same row key as target | generated feature table from observed history | target unit inherited from `17.1_BC` | DA-aligned version is the thesis-facing average-price feature surface. |
| Exogenous-small features | `nl_ir_capacity_features_exogenous_small_daily_direction.csv`; `nl_ir_capacity_features_exogenous_small_da_aligned_daily_direction.csv` | endogenous features plus lagged NL DA price and week-ahead load summaries | daily full-day | same row key as target | generated known-at-safe feature table | target unit inherited from `17.1_BC` | Small conservative exogenous set; excludes unsafe same-day and `12.3_F` fields. |
| Forecast outputs | `nl_ir_capacity_forecast_*daily_direction_long.csv` | `point_forecast` for `average_procurement_price` | daily full-day | `Up`, `Down` | generated forecast artifacts | same target unit as average-price layer | Metrics are frozen in `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`. |
| `12.3_F` accepted-offer table | `nl_ir_capacity_12_3_f_observed_threshold_table_daily_direction.csv` | accepted-price quantiles and max accepted-price proxy | daily full-day | `Up`, `Down` | observed accepted/procured offers only | source columns use `EUR per MAW`; downstream repaired as `EUR/MW/ISP` equivalent naming | Used for threshold proxies only; rejected bids are unobserved. |
| Threshold calibration backtest | `nl_ir_capacity_12_3_f_threshold_calibration_backtest_daily_direction_long.csv` | predicted accepted-threshold proxy and error metrics | daily full-day | `Up`, `Down` | calibration/evaluation proxy layer | threshold proxy price | Used to choose threshold scenario roles and anchor stability. |
| Threshold scenarios | `nl_ir_capacity_12_3_f_threshold_scenarios_da_aligned_daily_direction_long.csv` | `threshold_price_scenario`, `scenario_id`, `scenario_probability` | daily full-day | `Up`, `Down` | mixed: synthetic proxy before `2025-01-07`, observed-overlap proxy from `2025-01-07` | threshold proxy price | Frozen three-role acceptance-proxy scenario layer. |
| MILP export v2 | `milp_exports/nl_ir_capacity_milp_input_daily_direction_scenarios_v2.csv` | `acceptance_threshold_price_eur_per_mw_isp`, `contract_isp_count`, scenario metadata | daily full-day | `Up`, `Down` | MILP-facing proxy input | `EUR/MW/ISP` plus ISP count | Capacity-only input contract; activation and MARI excluded. |

## 4. Split and forecast-origin registry

| split_name | start | end | role | chronological? | random split? | known-at timing notes | source evidence |
|---|---|---|---|---|---|---|---|
| train | `2022-01-01` | `2023-09-30` | Fit average-price forecast models and calibration choices where applicable | yes | no | DA-aligned capacity decision timing repaired to `D-1 09:00 Europe/Amsterdam`; values not recomputed by timing repair | `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`; `build_mfrr_capacity_da_aligned_split_features_daily_v1.py` |
| validation | `2023-10-01` | `2024-09-30` | Select/tune average-price model settings | yes | no | Same DA-aligned known-at rule | `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`; `run_mfrr_capacity_da_aligned_forecasts_daily_v1.py` |
| test | `2024-10-01` | `2025-09-30` | Final average-price evaluation and MILP-facing scenario horizon | yes | no | Same DA-aligned known-at rule; threshold scenarios are synthetic/proxy before `2025-01-07` | `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`; `build_mfrr_capacity_12_3_f_threshold_scenarios_daily_v1.py` |
| threshold calibration | `2025-01-07` | `2025-06-30` | Calibrate `12.3_F` additive markup threshold proxies | yes | no | `12.3_F` is ex-post accepted-offer evidence, not a forecast-safe exogenous input | `docs/forecasting/mfrr_capacity_12_3_f_scope_inspection_daily_v1.md`; `run_mfrr_capacity_12_3_f_threshold_calibration_2025_daily_v1.py` |
| threshold evaluation | `2025-07-01` | `2025-09-30` | Evaluate threshold-proxy rules and overbid/accepted proxy behaviour | yes | no | Observed-overlap proxy evaluation only; not a true rejected-bid boundary | `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md` |

## 5. Model result registry

Metrics below are the frozen DA-aligned average-price results from `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`.

| model_or_variant | target | feature_set | DA_aligned | validation_MAE | test_MAE | test_RMSE | test_bias | selected_for | selection_reason | source_file_or_doc | notes |
|---|---|---|---|---:|---:|---:|---:|---|---|---|---|
| `naive_lag_7d_same_direction` | `17.1_BC` average procurement price | weekly same-direction lag | yes | 1.5128 | 1.0340 | 1.6368 | 0.0215 | primary benchmark; threshold anchor | Mandatory simple benchmark; later selected as threshold anchor for stability | `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`; `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md` | Strong in some calm `Down` regimes. |
| `lear_endogenous_da_aligned_daily_v1` | `17.1_BC` average procurement price | endogenous lag, rolling, spread, calendar, direction | yes | 1.2856 | 1.0100 | 1.3215 | 0.2899 | retained reference | Transparent linear endogenous comparator | `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md` | Not final best average-price model. |
| `xgboost_endogenous_da_aligned_daily_v1` | `17.1_BC` average procurement price | endogenous lag, rolling, spread, calendar, direction | yes | 1.3154 | 0.9483 | 1.2553 | 0.2648 | retained reference | Nonlinear endogenous comparator improved test MAE over LEAR endogenous | `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md` | Positive bias remains. |
| `lear_exogenous_small_da_aligned_daily_v1` | `17.1_BC` average procurement price | endogenous plus lagged DA price and week-ahead load | yes | 1.2524 | 0.9798 | 1.3142 | 0.1746 | transparent frontrunner; threshold sensitivity | Simpler and transparent exogenous model; improves over endogenous LEAR | `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`; `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md` | Revenue-leading in one threshold proxy case but more aggressive than naive. |
| `xgboost_exogenous_small_da_aligned_daily_v1` | `17.1_BC` average procurement price | endogenous plus lagged DA price and week-ahead load | yes | 1.1475 | 0.8583 | 1.1969 | 0.0315 | best average-price forecast; primary average-price reference in MILP export | Lowest validation and test MAE in frozen table | `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`; `docs/optimisation/nl_ir_capacity_milp_export_contract_v2.md` | Not selected as primary threshold anchor because threshold stability/overbid tradeoff differs. |
| `arimax_load_da_aligned_daily_v1` | `17.1_BC` average procurement price | week-ahead load mean and peak only | yes | 1.5198 | 1.1628 | 1.4201 | 0.4538 | rejected classical comparator | Slower and weaker overall, especially for `Down` | `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md` | Retained as documented comparator only. |
| benchmark bundle | `17.1_BC` average procurement price | mixed benchmark outputs | partial / mixed | not_found | not_found | not_found | not_found | lineage / comparison support | No compact metric table inspected for this bundle | `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_benchmarks_daily_direction_long.csv` | Generated artifact exists locally; no thesis-facing metric row used here. |

## 6. Threshold / acceptance-proxy registry

| proxy_name | data_source | coverage | directions | scenario_role | threshold_statistic | selected? | selection_reason | source_file_or_doc | limitations |
|---|---|---|---|---|---|---|---|---|---|
| `threshold_conservative_p75` | `12.3_F` accepted/procured offers plus `naive_lag_7d_same_direction` average-price anchor | scenario horizon `2024-10-01` to `2025-09-30`; observed overlap from `2025-01-07` | `Up`, `Down` | conservative | `accepted_price_p75_eur_per_maw` with `direction_daytype_median_markup` | yes | Conservative role; consistent-daytype policy preserves ordering against p90/max | `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md`; `docs/forecasting/mfrr_capacity_12_3_f_threshold_scenario_freeze_daily_v1.md` | Proxy only; rejected bids unobserved; pre-overlap rows synthetic. |
| `threshold_central_p90` | `12.3_F` accepted/procured offers plus `naive_lag_7d_same_direction` average-price anchor | scenario horizon `2024-10-01` to `2025-09-30`; observed overlap from `2025-01-07` | `Up`, `Down` | central / upper-normal | `accepted_price_p90_eur_per_maw` with `direction_daytype_median_markup` | yes | Best evaluation MAE for p90 and acceptable overbid rate for v1 | `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md`; `docs/forecasting/mfrr_capacity_12_3_f_threshold_scenario_freeze_daily_v1.md` | Proxy only; accepted stack is not a full bid ladder. |
| `threshold_optimistic_max` | `12.3_F` accepted/procured offers plus `naive_lag_7d_same_direction` average-price anchor | scenario horizon `2024-10-01` to `2025-09-30`; observed overlap from `2025-01-07` | `Up`, `Down` | optimistic / upper-bound | `max_accepted_price_proxy_eur_per_maw` with `direction_daytype_median_markup` | yes | Best evaluation MAE among max candidates; retained only as upper-bound proxy | `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md`; `docs/forecasting/mfrr_capacity_12_3_f_threshold_scenario_freeze_daily_v1.md` | Not a true clearing threshold; extreme source-row sensitivity noted. |
| threshold anchor | average-price forecast artifacts joined to `12.3_F` observed threshold table | `2025-01-07` to `2025-09-30` for backtest | `Up`, `Down` | anchor for all three selected scenario roles | `naive_lag_7d_same_direction` | yes | Best threshold-proxy stability across all three proxies on evaluation MAE; less aggressive overbid behaviour than revenue-maximising alternatives | `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md` | Not the best average-price model; selected for threshold stability, not raw price MAE. |
| secondary aggressive sensitivity anchor | same as above | `2025-01-07` to `2025-09-30` for backtest | `Up`, `Down` | sensitivity only | `xgboost_exogenous_small_da_aligned_daily_v1` | no, secondary only | Can improve mean unit revenue for some proxy/rule combinations but often increases overbid behaviour | `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md` | Do not describe as primary threshold anchor. |

## 7. Final selected methods

- Selected thesis-facing average-price forecast model: `xgboost_exogenous_small_da_aligned_daily_v1`.
- Primary average-price benchmark: `naive_lag_7d_same_direction`.
- Selected threshold / acceptance-proxy anchor: `naive_lag_7d_same_direction`.
- Selected threshold scenario method: `12_3_f_additive_markup_threshold_proxy_v1` with deterministic three-role additive markup scenarios: p75 conservative, p90 central, max optimistic.
- MILP capacity input method: `nl_ir_capacity_milp_input_daily_direction_scenarios_v2.csv`, preserving threshold scenario probabilities, `EUR/MW/ISP`, `contract_isp_count`, direction, and proxy acceptance logic.

The average-price and threshold selections are intentionally not identical. `xgboost_exogenous_small_da_aligned_daily_v1` is selected for the capacity average-price forecast component because it is best on the frozen DA-aligned validation and test MAE table. `naive_lag_7d_same_direction` is selected for threshold/acceptance-proxy stability because the threshold layer depends on calibrated accepted-offer markups and overbid behaviour, not only raw average-price MAE.

## 8. Limitations

- `12.3_F` contains accepted/procured offers, not a full submitted bid ladder.
- The threshold proxy is not a true market-clearing threshold because rejected bids are unobserved.
- Accepted-bid data coverage is shorter than the `17.1_BC` target coverage; the inspected threshold overlap starts on `2025-01-07`.
- No activation probability forecasting is implemented.
- No energy-bid price forecasting is implemented.
- No MARI forecasting is implemented.
- Daily observed product structure remains the source-backed baseline unless official 4-hour incident-reserve evidence is added; 4-hour logic is a counterfactual sensitivity only.
- Generated CSV outputs are not all tracked as Git-first provenance; this registry relies on tracked freeze docs for thesis-facing metrics.
- The mFRR/DAM hydrogen work is a sandbox/interface handoff, not a final historical mFRR value result.

## 9. Thesis-use guidance

Use this registry to report the capacity-side forecasting and acceptance-proxy layer separately from energy-bid and activation modelling. Avoid calling it a full mFRR forecasting model. A precise thesis description is: a Dutch Incident Reserve capacity average-price forecast and accepted-threshold proxy layer, prepared to provide exploratory capacity-revenue inputs for downstream MILP tests.

## 10. File map

Docs:

- `docs/forecasting/mfrr_capacity_forecasting_thesis_summary_v1.md`
- `docs/forecasting/mfrr_capacity_average_price_freeze_da_aligned_daily_v1.md`
- `docs/forecasting/mfrr_capacity_endogenous_freeze_and_exogenous_audit_daily_v1.md`
- `docs/forecasting/mfrr_capacity_12_3_f_scope_inspection_daily_v1.md`
- `docs/forecasting/mfrr_capacity_12_3_f_threshold_rule_selection_daily_v1.md`
- `docs/forecasting/mfrr_capacity_12_3_f_threshold_scenario_audit_daily_v1.md`
- `docs/forecasting/mfrr_capacity_12_3_f_threshold_scenario_freeze_daily_v1.md`
- `docs/forecasting/mfrr_capacity_12_3_f_down_scenario_collapse_diagnostic_daily_v1.md`
- `docs/market_rules/nl_incident_reserve_capacity_market_rules_v2.md`
- `docs/market_rules/nl_incident_reserve_capacity_timing_metadata_alignment_audit_v2.md`
- `docs/optimisation/nl_ir_capacity_milp_export_contract_v2.md`

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
- `scripts/Data/02_Forecasting/02_mFRR_IR_NL/export_mfrr_capacity_milp_input_daily_v2.py`

Target/features:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_target_daily_direction.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_endogenous_daily_direction.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_endogenous_da_aligned_daily_direction.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_exogenous_small_daily_direction.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_features_exogenous_small_da_aligned_daily_direction.csv`

Forecast outputs:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_naive7d_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_lear_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_xgboost_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_lear_exogenous_small_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_xgboost_exogenous_small_da_aligned_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_forecast_arimax_load_da_aligned_daily_direction_long.csv`

Threshold/backtest outputs:

- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_observed_threshold_table_daily_direction.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_threshold_calibration_backtest_daily_direction_long.csv`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/nl_ir_capacity_12_3_f_threshold_scenarios_da_aligned_daily_direction_long.csv`

MILP export docs and artifacts:

- `docs/optimisation/nl_ir_capacity_milp_export_contract_v2.md`
- `data/02_Forecasting/02_Balancing_mFRR_IR/IR_Capacity/milp_exports/nl_ir_capacity_milp_input_daily_direction_scenarios_v2.csv`
