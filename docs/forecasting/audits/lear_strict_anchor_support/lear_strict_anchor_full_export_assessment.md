# LEAR_STRICT Anchor Full Export Assessment

Run path: `data\02_Forecasting\01_DA_prices\hourly_da\qh_anchor_exports\lear_strict_observed_qh_grid\20260510_135238_lear_strict_observed_qh_grid_export_post_input_extension_smoke`

## Core results
- Expected anchor rows: **25920**
- Generated anchor rows: **4455**
- Coverage: **17.19%**
- Origins generated: **47 / 216**
- Earliest forecast_origin_utc generated: `2025-10-01 06:00:00+00:00`
- Latest forecast_origin_utc generated: `2026-04-24 06:00:00+00:00`
- Earliest target_timestamp_utc generated: `2025-10-01 22:00:00+00:00`
- Latest target_timestamp_utc generated: `2026-04-29 21:00:00+00:00`
- Non-null y_pred: **4455/4455**
- Duplicate keys (origin,target,lead_day): **0**
- Total runtime seconds: **976.18**

## Support sufficiency (for future QH_MODEL_3 comparison)
- Validation origins with anchors: **10**
- Test origins with anchors: **9**
- Validation complete local delivery days (24 hourly anchors): **29**
- Test complete local delivery days (24 hourly anchors): **26**
- Validation QH rows after hourly->QH expansion: **3940** (observed-target rows: 3940)
- Test QH rows after hourly->QH expansion: **3636** (observed-target rows: 3636)
- STRICT_THREE_MODEL_QH_OVERLAP likely meaningful: **Borderline/No**

## Decision
- **B**: Full export works but support is small; QH_MODEL_3 should be built as diagnostic only, not as main final comparison.