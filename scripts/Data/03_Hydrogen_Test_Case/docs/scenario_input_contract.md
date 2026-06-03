# Scenario Input Contract (Hydrogen DA Optimisation)

## Purpose

This contract defines the minimum requirements for scenario files used by the hydrogen optimisation stack.

It is a precondition for stochastic and CVaR runs. If this contract is not satisfied, stochastic objective values are not thesis-grade.

## Required fields

The scenario adapter must provide these canonical columns after mapping:

1. `forecast_origin_utc`
2. `delivery_start_utc`
3. `scenario_id`
4. `scenario_probability`
5. `scenario_price_eur_per_mwh`
6. `model_id` (or mapped source identifier)
7. `granularity`
8. `lead_day` (or equivalent horizon label mapped to lead day)
9. `actual_price_eur_per_mwh` when realised settlement is evaluated

The optimisation config provides timestep length through granularity:

- hourly -> `delta_t_hours = 1.0`
- quarter-hour -> `delta_t_hours = 0.25`

## Accepted alias mapping

Common upstream aliases are accepted and mapped in `scenario_loader.py`:

- `period_timestamp` -> `delivery_start_utc`
- `candidate_key` -> `model_id`
- `probability` -> `scenario_probability`
- `scenario_price` -> `scenario_price_eur_per_mwh`
- `actual_price` -> `actual_price_eur_per_mwh`

Mapped output must still satisfy this contract.

## Probability requirements

Probability rules apply per `forecast_origin_utc` + `model_id` + `lead_day`:

1. Probabilities must be nonnegative.
2. Scenario probability mass must sum to 1 within tolerance `[0.999999, 1.000001]`.
3. Equal probabilities are acceptable only if explicitly documented in the scenario-generation metadata.

If probability mass is invalid:

- stochastic expected-cost values are distorted;
- CVaR tail weighting is distorted;
- results are not thesis-grade.

No silent probability normalisation is permitted for thesis-grade runs.

## Row uniqueness

Rows must be unique for:

- `forecast_origin_utc`, `delivery_start_utc`, `scenario_id`, `model_id`.

Duplicate rows invalidate stochastic weighting and must be treated as a data-quality failure.

## Timestamp rules

Required timestamp behavior:

1. `forecast_origin_utc` and `delivery_start_utc` must be timezone-aware UTC after parsing.
2. Local-time fields (if present) are reporting fields only.
3. Forecast-origin and delivery timing must follow thesis assumptions (D-1 08:00 origin in Europe/Amsterdam, stored in UTC).

## Forecast-origin reconstruction policy

For legacy files missing `forecast_origin_utc`, reconstruction from `delivery_start_utc` is supported as:

- local delivery day minus 1 day at 08:00 Europe/Amsterdam, converted to UTC.

This is acceptable for explicitly marked legacy smoke tests only.

This is not ideal for final thesis-grade scenario inputs and should be replaced by explicit stored `forecast_origin_utc` in regenerated artifacts.

## Validation modes

Catalog entries must declare:

- `validation_mode: thesis_grade` or `validation_mode: smoke_test`
- `allow_forecast_origin_reconstruction: true|false`

Behavior:

1. `thesis_grade`: integrity failures are hard failures.
2. `smoke_test`: integrity failures are recorded as smoke warnings; runs are diagnostic only.

## Pre-run validation command

Run catalog validation before optimisation:

```powershell
.\.venv\Scripts\python.exe scripts/Data/03_Hydrogen_Test_Case/validate_scenario_catalog.py --config scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml
```

Strict mode that fails on smoke warnings:

```powershell
.\.venv\Scripts\python.exe scripts/Data/03_Hydrogen_Test_Case/validate_scenario_catalog.py --config scripts/Data/03_Hydrogen_Test_Case/configs/base_hydrogen.yaml --strict-smoke
```

Expected exit codes:

- `0`: pass (or smoke warnings when `--strict-smoke` is not set)
- `2`: hard failure
- `3`: smoke warnings escalated by `--strict-smoke`
