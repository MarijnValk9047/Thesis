# Residual Coverage Loss Diagnosis

- Run path analysed: `data/02_Forecasting/01_DA_prices/hourly_da/qh_anchor_exports/lear_strict_observed_qh_grid/20260510_135238_lear_strict_observed_qh_grid_export_post_input_extension_smoke`
- Expected rows: 25920
- Generated rows: 4455
- Coverage: 17.19%
- Missing rows: 21465

## Main causes
- feature_builder_drop::missing_p_base_d_minus_1: 7276 (28.07% of expected)
- feature_builder_drop::missing_p_base_d_minus_2: 4669 (18.01% of expected)
- feature_builder_drop::missing_p_base_d_minus_3: 3122 (12.04% of expected)
- feature_builder_drop::missing_p_base_d_minus_7: 3120 (12.04% of expected)
- feature_builder_drop::missing_p_target_d_minus_7: 2701 (10.42% of expected)
- feature_builder_drop::unknown: 462 (1.78% of expected)
- feature_builder_drop::missing_x1_load_base_d: 115 (0.44% of expected)

## Endogenous vs exogenous vs structural
- Endogenous-linked missing rows: 18187
- Exogenous-linked missing rows: 115
- Export/training-structure skips: 0

## Recommendation
- Decision class: **B**
- Indicative achievable coverage without methodology change: ~66.9%
