# FS3 Combo Ablation Comparison

Generated at: 2026-04-23T05:10:05

## Parent MAE comparison

### Validation

- D only: LEAR MAE = 17.788, XGBoost MAE = 19.134, better parent = LEAR.
- Full horizon: LEAR MAE = 29.864, XGBoost MAE = 25.117, better parent = XGBoost.

### Test

- D only: LEAR MAE = 21.950, XGBoost MAE = 22.019, better parent = LEAR.
- Full horizon: LEAR MAE = 38.462, XGBoost MAE = 28.620, better parent = XGBoost.

## Most harmful validation removals

### LEAR

- D only: `da_generation_day1_crossborder` is the most harmful removal (delta = +4.846, relative = +27.24%).
- Full horizon: `da_generation_day1_crossborder` is the most harmful removal (delta = +0.967, relative = +3.24%).

### XGBoost

- D only: `da_generation_day1_crossborder` is the most harmful removal (delta = +1.787, relative = +9.34%).
- Full horizon: `wa_load_crossborder` is the most harmful removal (delta = +0.514, relative = +2.04%).
