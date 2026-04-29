# DAM Tuning Policy

This note is the active tuning policy for the hourly DAM pipeline.

## Core rules

- Tune by `FS` level, not by daily walk-forward origin.
- Structural hyperparameter search happens on the **validation** period only.
- Once an `FS`-level configuration is chosen, freeze it for that `FS`.
- Daily walk-forward later only re-fits / re-estimates the frozen specification.
- Do not tune on the final test period.

## Phase 2 policy hardening

These are now explicit repo rules for future feature-family ablation work:

- `tuning.py` is the canonical source of truth for the default ablation-tuning policy.
- For future `FS1` and `FS2` grouped-ablation runs, the default is to reuse the parent-stage tuned hyperparameters.
- Full retuning is **not** the default for every ablation run.
- Future child runs should surface the inheritance metadata fields:
  - `settings_inheritance_policy`
  - `parent_run_id`
  - `parent_run_label`
  - `parent_model`
  - `parent_fs_level`

For relative metrics:

- the parent benchmark stage's `official_naive_reference.json` is the source of truth for inherited `rMAE` denominators
- future ablation runs should copy that inherited denominator snapshot into child-run metadata
- the denominator should be frozen within one parent benchmark context instead of being recomputed per child ablation run

Canonical future rolling-origin artifact names are now reserved:

- `feature_value_by_origin.csv`
- `feature_value_by_reporting_level.csv`
- `feature_value_summary.csv`

## Cadence by stage

- `FS0`: no tuning
- `FS1`: fast / coarse tuning only
- `FS2`: first serious tuning round
- `FS3`: mandatory retuning because the feature set changes materially
- `FS4`: selective rigorous retuning for surviving finalists only

## Model-entry implications

- `LEAR` and `XGBoost` are the fair `FS1` models because they rely on explicit endogenous regressors.
- `Prophet` is not an `FS1` model.
- `Prophet` enters only from `FS2`, once calendar and holiday structure is part of the design.
- `FS1` is not the shortlisting stage.
- `FS2` is the first fair shortlist point.

## Parameter focus by model

### LEAR

Primary knobs:
- `alpha`
- training-window length
- controlled lag-bundle choice

Suggested starting region:
- `alpha = 0.01`
- training window around `90` days
- starter endogenous lag bundle from the shared pipeline

### XGBoost

Primary knobs:
- `learning_rate`
- `max_depth`
- `min_child_weight`
- `subsample`
- `colsample_bytree`
- `reg_alpha`
- `reg_lambda`

Suggested starting region:
- `learning_rate = 0.05`
- `max_depth = 4`
- compact regularization grid around the current benchmark settings

### Prophet

Primary knobs:
- `seasonality_mode`
- `changepoint_prior_scale`
- `seasonality_prior_scale`
- `holidays_prior_scale`

Suggested starting region:
- multiplicative seasonality
- `changepoint_prior_scale = 0.05`
- `seasonality_prior_scale = 10`
- `holidays_prior_scale = 10`

## Execution boundary

This repo update only prepares the structure for the tuning strategy.

It does **not**:
- launch tuning searches
- rerun walk-forward benchmarks
- regenerate comparison outputs

The intended next step is to execute tuning later, stage by stage, once the relevant feature-set inputs are finalized.

## Deferred scope for Phase 3

- `LEAR` coefficient stability diagnostics are deferred for now.
- `XGBoost` gain importance is in scope later as secondary interpretation.
- permutation importance is optional later if runtime allows.
- `SHAP` is deferred unless it is trivial to support with current dependencies.
- `Prophet` interpretation should remain compact and modest later.
