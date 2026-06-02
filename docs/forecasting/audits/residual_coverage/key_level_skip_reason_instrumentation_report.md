# Key-Level Skip Reason Instrumentation Report

## Patched files
- scripts/Data/02_Forecasting/01_DA_prices/run_lago_lear_export_for_qh.py

## Scope of change
- Added diagnostics only (no feature, filtering, known_at, or model logic changes).
- Added key-level exporter skip tracing and builder-drop mapping to key-level rows.

## Run results
- Check-only run dir: `data/02_Forecasting/01_DA_prices/hourly_da/qh_anchor_exports/lear_strict_observed_qh_grid/20260511_072309_lear_strict_observed_qh_grid_export`
- Smoke run dir: `data/02_Forecasting/01_DA_prices/hourly_da/qh_anchor_exports/lear_strict_observed_qh_grid/20260511_072851_lear_strict_observed_qh_grid_export_key_level_skip_reason_smoke`

## Top key-level skip reasons (smoke)
- missing_p_base_d_minus_1 (feature_builder): 48 rows
- missing_p_base_d_minus_7 (feature_builder): 47 rows
- missing_p_base_d_minus_2 (feature_builder): 23 rows
- missing_hourly_bridge_price (feature_builder): 6 rows

## Prediction invariance check
- overlap_rows: 236
- max_abs_diff(y_pred): 5.684341886080802e-14
- mean_abs_diff(y_pred): 4.817238886509154e-16

## Decision
- B
