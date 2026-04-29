# Phase 2 Policy Hardening

This note records the low-risk Phase 2 decisions that were implemented without starting Phase 3 execution.

## What changed

- `hourly_da/core/tuning.py` now holds the canonical default ablation-tuning policy for future `FS1` and `FS2` grouped-ablation runs.
- `hourly_da/core/metrics.py` now records the future `rMAE` denominator inheritance contract and exposes a metadata helper for inherited naive references.
- benchmark-parent and aggregate-parent `run_summary.json` files now expose:
  - the effective policy snapshot for that run
  - the future `rMAE` inheritance rule
  - a parent-benchmark `rMAE` reference snapshot built from `official_naive_reference.json`
- `run_fs3_taxonomy_inventory.py` now generates an availability-aware inventory of the actual `FS3` experiment bundles defined in code.

## Source of truth

- ablation tuning default: `hourly_da/core/tuning.py`
- inherited `rMAE` denominator artifact: parent benchmark `official_naive_reference.json`
- inherited `rMAE` metadata contract: `hourly_da/core/metrics.py`
- FS3 code-defined experiment taxonomy: `hourly_da/core/external_features.py`
- current FS3 inventory artifact: `docs/fs3_taxonomy_inventory.csv` and `docs/fs3_taxonomy_inventory.json`

## Reserved future artifact names

- `feature_value_by_origin.csv`
- `feature_value_by_reporting_level.csv`
- `feature_value_summary.csv`

These are reserved for future rolling-origin-compatible feature-value reporting. Current benchmark artifacts were not renamed.

## Explicit deferrals to Phase 3

- no grouped-ablation execution yet
- no feature-value result notebooks yet
- no LEAR coefficient stability diagnostics yet
- no XGBoost permutation or SHAP implementation yet
- no expanded Prophet interpretation beyond compact future summaries
- no benchmark retuning architecture changes
