# Scenario Artifact Repair Request

## Why this file exists

The hydrogen stochastic bidding stack is ready for real scenario integration, but the required hourly thesis-grade scenario artifact is not currently usable.

This request defines exactly what the upstream scenario export must produce before Phase 6b can begin.

Temporary status:

- Phase 6a-2 created legacy-derived integration-candidate artifacts for:
  - hourly LEAR FS3 `base_plus_b`
  - hourly XGBoost FS3 `base_plus_b`
- those artifacts are useful for integration dry runs only
- they do not remove the need for a thesis-grade hourly export with explicit native `forecast_origin_utc`

## Required target artifact

First acceptable real-integration artifact:

- hourly granularity
- D-only
- one canonical model is enough for the first repair
- preferred order:
  1. `hourly_lear_strict`
  2. `hourly_lear_fs3`
  3. `hourly_xgboost_fs3`

## Required output shape

Provide one long-format file per selected scenario set:

- `scenario_prices_long.csv` or `scenario_prices_long.parquet`

Required columns:

- `forecast_origin_utc`
- `delivery_start_utc`
- `scenario_id`
- `scenario_probability`
- `scenario_price_eur_per_mwh` or alias `scenario_price`
- `actual_price_eur_per_mwh` or alias `actual_price`
- `model_id` or alias `candidate_key`
- `granularity`
- `scenario_generation_run_id`

Recommended additional columns:

- `delivery_start_local`
- `delivery_day`
- `lead_day`
- `point_forecast_eur_per_mwh`
- `dataset_split`

## Required semantics

1. Timestamps
   - `forecast_origin_utc` and `delivery_start_utc` must be timezone-aware UTC
   - do not require downstream reconstruction if avoidable

2. Probability mass
   - probabilities must be nonnegative
   - for each scenario set, probability mass must sum to `1.0`
   - the sum must be valid on the correct unique-scenario basis, not only after manual filtering

3. Scenario-set isolation
   - do not bundle multiple scenario variants into one artifact unless the artifact schema includes an explicit selector that downstream tooling can apply before validation
   - preferred solution: export one chosen scenario variant per artifact

4. Granularity and horizon
   - hourly only for the first repair
   - D-only / `lead_day = 0`

5. Duplicate policy
   - no duplicate rows for:
     - `forecast_origin_utc`
     - `delivery_start_utc`
     - `scenario_id`
     - `model_id`

## Required sidecar metadata

For each repaired export, keep or provide:

- source run id
- scenario variant name
- scenario count
- probability policy
- calibration split
- target split
- whether tail/stress scenarios were included

## Validation gate before handoff

The repaired artifact must pass:

```powershell
.venv\Scripts\python.exe scripts/Data/03_Hydrogen_Test_Case/validate_scenario_catalog.py `
  --config scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml `
  --artifacts <artifact_key>
```

It should also appear as thesis-grade-ready in:

```powershell
.venv\Scripts\python.exe scripts/Data/03_Hydrogen_Test_Case/audit_scenario_artifacts.py `
  --config scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml `
  --output-dir scripts/Data/03_Hydrogen_Test_Case/docs
```

## Current blockers this repair must resolve

1. configured `hourly_lear_strict` export path missing on disk
2. legacy hourly fallback requires forecast-origin reconstruction
3. legacy hourly fallback bundles four `scenario_variant` groups into one artifact
4. current default artifact therefore cannot support thesis-grade stochastic bidding or CVaR runs
