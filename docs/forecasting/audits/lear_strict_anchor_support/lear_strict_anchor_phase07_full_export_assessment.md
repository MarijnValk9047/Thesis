# LEAR_STRICT Phase07 Full Export Assessment

- Run path: `data\02_Forecasting\01_DA_prices\hourly_da\qh_anchor_exports\lear_strict_observed_qh_grid\20260511_100740_lear_strict_observed_qh_grid_export_phase07_bridge_full_run`
- Expected anchor rows: 25920
- Generated rows: 24642
- Coverage: 95.07%
- Origins generated/expected: 208/216
- Forecast origin range: 2025-09-26T06:00:00+00:00 to 2026-04-29T06:00:00+00:00
- Target timestamp range: 2025-09-26T22:00:00+00:00 to 2026-04-30T20:00:00+00:00
- y_pred non-null rows: 24642/24642
- Duplicate key rows: 0
- Total runtime seconds: 19835.44034119998

## Coverage by split
- test: 3997/5275 (75.77%), origins 36/44
- train: 15485/15485 (100.00%), origins 129/129
- validation: 5160/5160 (100.00%), origins 43/43

## Coverage by lead_day
- lead_day 0: 4991/5184 (96.28%), origins 208/216
- lead_day 1: 4943/5184 (95.35%), origins 206/216
- lead_day 2: 4919/5184 (94.89%), origins 205/216
- lead_day 3: 4895/5184 (94.43%), origins 204/216
- lead_day 4: 4894/5184 (94.41%), origins 204/216

## Remaining gaps
- target_beyond_bridge_max: 245 rows
- missing_p_target_d_minus_7: 216 rows
- missing_p_base_d_minus_3: 192 rows
- missing_p_base_d_minus_2: 168 rows
- missing_p_base_d_minus_1: 144 rows
- missing_p_base_d_minus_7: 120 rows
- nan: 96 rows
- missing_x1_load_base_d: 92 rows
- Tail-limit share of missing rows (target_beyond_bridge_max + missing_hourly_bridge_price): 250/1278 (19.56%)

## Sufficiency for QH_MODEL_3
- Validation origins: 43
- Test origins: 36
- Validation complete local days: 47
- Test complete local days: 27
- Validation QH rows after expansion: 20640
- Test QH rows after expansion: 15988
- Estimated STRICT_THREE_MODEL_QH_OVERLAP rows: 98568
- Decision: A
