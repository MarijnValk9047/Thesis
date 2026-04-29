# Phase 3 Feature-Family Ablation

Phase 3 adds executable grouped-ablation support for the active `FS1` and `FS2` hourly DAM pipeline.

## Execution shape

- parent benchmark runs remain the source of truth for:
  - tuned settings
  - official naive benchmark selection
  - inherited `rMAE` denominator values
- each child ablation run keeps the normal benchmark run-folder structure
- each parent context also gets one aggregate ablation run folder with comparison artifacts

## Current runner

- `run_feature_family_ablation.py`

Supported controls:

- `--fs-level`
- `--model-family`
- `--feature-family`
- `--smoke-test`
- `--smoke-origins-per-split`

## Artifact layout

Child ablation run:

- normal benchmark artifacts
- inherited-policy and parent-lineage metadata in `run_summary.json`

Aggregate ablation run:

- `feature_family_value_summary.csv`
- `feature_family_value_by_origin.csv`
- `feature_family_value_by_reporting_level.csv`
- `feature_family_value_metadata.json`
- `feature_family_parent_child_map.csv`

## Scope boundary

- no notebook reporting polish yet
- no grouped-ablation notebook layer yet
- no FS4 work
- no LEAR coefficient-stability framework yet
- no SHAP/permutation framework yet
