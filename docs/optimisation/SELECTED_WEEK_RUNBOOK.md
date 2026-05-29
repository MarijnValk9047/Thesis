# Selected Week Runbook

## Official config files

- Validation selected weeks: `scripts/Data/03_Hydrogen_Test_Case/configs/selected_validation_weeks.yaml`
- Test selected weeks: `scripts/Data/03_Hydrogen_Test_Case/configs/selected_test_weeks.yaml`
- Deprecated mixed file: `scripts/Data/03_Hydrogen_Test_Case/configs/selected_weeks.yaml`
- Audit-only common-support file: `scripts/Data/03_Hydrogen_Test_Case/configs/selected_weeks_common_support.yaml`

## Intended regime labels

- `typical_summer`
- `typical_winter`
- `high_volatility`
- `high_price`

`typical` means closest to the seasonal median behaviour under exact common support. It does not mean lowest volatility.

Current validation safety exception:

- `scripts/Data/03_Hydrogen_Test_Case/configs/selected_validation_weeks.yaml` does not contain a true `typical_winter` week.
- It contains `winter_proxy` for `2024-09-16` to `2024-09-22`.
- `winter_proxy` maps to the intended winter regime only as a common-support backup.
- `winter_proxy` is not valid for seasonal winter claims.
- `winter_proxy` is allowed only for runtime, debug, and common-support checks unless separately justified.

## Allowed and forbidden use

- Validation weeks are allowed for model selection, scenario selection, and CVaR policy selection.
- Validation weeks are allowed for development-stage selected-week diagnostics.
- Test weeks are reserved for frozen-policy out-of-sample evaluation and reporting only.
- Test weeks must not be used for parameter tuning, CVaR gamma selection, or model/scenario selection.

## Official artifact IDs for LEAR comparison

- LEAR Strict: `hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support`
- LEAR FS3: `hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate`

Do not use `hourly_lear_strict` as the official selected-week comparison artifact.

## Official entrypoints

- Generic selected-week risk-neutral smoke runner:
  `scripts/Data/03_Hydrogen_Test_Case/run_selected_week_risk_neutral_smoke.py`
- Validation one-week smoke sweep:
  `scripts/Data/03_Hydrogen_Test_Case/run_validation_cvar_smoke_sweep.py`
- Validation multi-week sweep:
  `scripts/Data/03_Hydrogen_Test_Case/run_validation_cvar_expanded_sweep.py`
- Validation fine-gamma diagnostic:
  `scripts/Data/03_Hydrogen_Test_Case/hydrogen/validation_cvar_fine_gamma_diagnostic.py`
- Frozen-policy selected test-week evaluation:
  `scripts/Data/03_Hydrogen_Test_Case/run_selected_test_weeks_cvar_policy_eval.py`

## Recommended smoke-test entrypoint

Use the Phase D smoke runner with the official validation split:

`scripts/Data/03_Hydrogen_Test_Case/run_validation_cvar_smoke_sweep.py`

Recommended first smoke week:

- `high_price`

## Required infrastructure modules

Selected-week validation/test workflows now require the preflight path built on:

- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation/input_resolver.py`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation/cache_manager.py`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation/output_policy.py`
- `scripts/Data/03_Hydrogen_Test_Case/hydrogen/optimisation/runtime_profiling.py`

The current migration is a selected-week input preflight and run-audit layer. It does not change MILP logic, bid logic, settlement logic, solver tolerances, or benchmarks.

## What not to run

- Do not run official validation or test workflows against `selected_weeks.yaml`.
- Do not run official validation or test workflows against `selected_weeks_common_support.yaml`.
- Do not present `winter_proxy` as a validation `typical_winter` result.
- Do not use test selected weeks for CVaR gamma selection.
- Do not rerun the full year to answer selected-week comparison questions.
- Do not switch artifacts ad hoc outside the common-support audit.
- Do not treat perfect foresight as an operating policy.

## Quick doctor command

Run the non-optimisation audit before any selected-week optimisation run:

```powershell
& '.venv\Scripts\python.exe' scripts/Data/03_Hydrogen_Test_Case/doctor_selected_week_pipeline.py
```
