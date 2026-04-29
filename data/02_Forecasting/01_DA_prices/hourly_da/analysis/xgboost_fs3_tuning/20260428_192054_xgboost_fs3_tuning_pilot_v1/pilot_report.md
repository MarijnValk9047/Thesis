# XGBoost FS3 tuning pilot report

Pilot run id: `20260428_192054_xgboost_fs3_tuning_pilot_v1`
Primary split: `validation`
Pilot origin count: `48`

## Sampled validation schedule

- sampled origins: `48` of `362`
- sample share: `13.26%`
- first sampled origin: `2023-09-30T06:00:00+00:00`
- last sampled origin: `2024-09-25T06:00:00+00:00`

## Runtime projection from the current FS3 benchmark

- projected pilot runtime: `15m 57s`
- projected pilot + full-validation runtime: `1h 16m 7s`

## Baseline

- current FS3 stitched MAE: `24.2010`
- current FS3 stitched rMAE: `0.8540`

## Best pilot candidate

- candidate: `xgboost_fs3_tune_r1_c07`
- stitched MAE: `24.3768`
- stitched rMAE: `0.8602`
- delta vs current FS3 baseline: `+0.1758`

## Auto-promoted candidates for full validation

- none

## Saved plots

- `candidate_sequence_metrics`: `data\02_Forecasting\01_DA_prices\hourly_da\analysis\xgboost_fs3_tuning\20260428_192054_xgboost_fs3_tuning_pilot_v1\plots\pilot_candidate_sequence_metrics.png`
- `ranked_delta_vs_baseline`: `data\02_Forecasting\01_DA_prices\hourly_da\analysis\xgboost_fs3_tuning\20260428_192054_xgboost_fs3_tuning_pilot_v1\plots\pilot_ranked_delta_vs_baseline.png`
- `runtime_vs_mae`: `data\02_Forecasting\01_DA_prices\hourly_da\analysis\xgboost_fs3_tuning\20260428_192054_xgboost_fs3_tuning_pilot_v1\plots\pilot_runtime_vs_mae.png`
