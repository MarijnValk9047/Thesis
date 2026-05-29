# Run Command Centre

## What it is

The optimisation command centre is the stable entrypoint for optimisation runs in this repository. It is designed to cover future optimisation scopes, not only the current selected-week hydrogen smoke path.

Current implemented backend:

- hourly
- D_only
- hydrogen
- DA_only
- selected_regimes
- risk_neutral

Current first consumer:

- hardened selected-week hydrogen fast path via `scripts/Data/03_Hydrogen_Test_Case/hydrogen/selected_week_smoke.py`

## Which file to edit

Edit:

- `scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_command_centre.yaml`

Supported values and implementation status live in:

- `scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_supported_options.yaml`

## How to run it

```powershell
& '.venv\Scripts\python.exe' scripts/Data/03_Hydrogen_Test_Case/run_from_command_centre.py
```

The command centre creates one parent experiment folder for the whole execution, and backend child run folders underneath it when multiple regimes or periods are requested.

Optional doctor:

```powershell
& '.venv\Scripts\python.exe' scripts/Data/03_Hydrogen_Test_Case/doctor_command_centre.py
```

Selected-week pipeline doctor:

```powershell
& '.venv\Scripts\python.exe' scripts/Data/03_Hydrogen_Test_Case/doctor_selected_week_pipeline.py
```

## Current command-centre fields

### General

- `method_version`
- `run_purpose`
- `run_label`
- `notes`

### Scope

- `asset_case`
- `market_scope`
- `granularity`
- `horizon`
- `split`
- `period_mode`
- `selected_regimes`
- `custom_start_date`
- `custom_end_date`

### Inputs

- `scenario_models`
- `artifact_ids`
- `scenario_count_policy`
- `actual_price_source`
- `selected_week_config_validation`
- `selected_week_config_test`

### Risk

- `gamma_values`
- `cvar_alpha`
- `risk_mode`

### Execution

- `output_mode`
- `audit_days`
- `run_figures`
- `write_solver_logs`
- `use_cache`
- `use_benchmark_cache`
- `progress_reporting`
- `max_workers`
- `gurobi_threads`

### Governance

- `allow_test_for_tuning`
- `methodological_approximation`
- `methodological_approximation_type`
- `require_common_support`
- `require_doctor_pass`

## Validation and test rules

- Validation runs are allowed for development, model selection, scenario selection, and CVaR selection.
- Test runs are reserved for frozen-policy out-of-sample evaluation.
- The command centre refuses test runs when `run_purpose` or `notes` indicate tuning, development, calibration, CVaR selection, scenario reduction selection, or solver approximation selection, unless `allow_test_for_tuning` is explicitly set to `true`.

Official split config files:

- validation: `scripts/Data/03_Hydrogen_Test_Case/configs/selected_validation_weeks.yaml`
- test: `scripts/Data/03_Hydrogen_Test_Case/configs/selected_test_weeks.yaml`

Forbidden for official runs:

- `scripts/Data/03_Hydrogen_Test_Case/configs/selected_weeks.yaml`
- `scripts/Data/03_Hydrogen_Test_Case/configs/selected_weeks_common_support.yaml`

## Available period modes

- `selected_regimes`: implemented
- `custom_dates`: planned, must refuse
- `full_split`: planned, must refuse
- `full_year`: planned, must refuse

## Available selected regimes

- `typical_summer`
- `typical_winter`
- `high_volatility`
- `high_price`
- `winter_proxy`

### `winter_proxy`

- validation-only backup
- proxy for `typical_winter`
- not valid for winter seasonal claims
- allowed only for runtime/debug/common-support checks unless separately justified

## Supported scenario models and artifact IDs

Scenario models:

- `lear_strict`
- `lear_fs3`
- `xgboost_fs3`

Current official LEAR artifacts:

- `hourly_lear_strict_donly_1092_tail_stress_v1_partial_test_support`
- `hourly_lear_fs3_pruned_tail_stress_v1_thesis_candidate`

The full registry, restrictions, and implementation status live in:

- `scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_supported_options.yaml`

## Supported and planned granularities

- `hourly`: implemented
- `quarter_hour`: planned, must refuse

## Supported and planned horizons

- `D_only`: implemented
- `D_plus_4`: planned, must refuse

## Supported and planned market scopes

- `DA_only`: implemented
- `DA_mFRR`: planned, must refuse

## Supported and planned asset cases

- `hydrogen`: implemented
- `steel_future`: planned, must refuse

## CVaR and gamma fields

- `risk_mode=risk_neutral` is implemented
- `gamma_values` must be `[0.0]` for the current backend
- `risk_mode=cvar` is listed as planned and must refuse until a CVaR backend is wired into the command centre

## Output modes

- `speed`: no routine figures, no successful per-day debug folders, no routine solver logs
- `minimal`: compact machine-readable outputs
- `audit`: audit-focused outputs, but audit-day filtering is not implemented yet
- `full`: full debug/reporting outputs

Current backend maps:

- `speed` -> optimisation output policy `minimal`
- `minimal` -> optimisation output policy `minimal`
- `audit` -> optimisation output policy `audit`
- `full` -> optimisation output policy `full`

## Progress reporting files

Every command-centre-backed MILP run writes:

- `progress_log.csv`
- `progress_current.json`

`progress_log.csv` includes:

- timestamp
- run_id
- split
- period_mode
- regime
- model
- delivery_day
- gamma
- solve_index
- total_solves
- build_seconds
- solver_seconds
- postprocess_seconds
- status
- mip_gap
- variables
- binaries
- constraints
- eta_seconds
- warning

`progress_current.json` includes:

- run_id
- run_folder
- current_status
- completed_solves
- total_solves
- percent_complete
- current_regime
- current_model
- current_delivery_day
- elapsed_seconds
- estimated_remaining_seconds
- failures_so_far
- last_update_timestamp

## Where outputs are saved

Each command-centre execution now creates one parent folder:

- `scripts/Data/03_Hydrogen_Test_Case/runs/<timestamp>_<run_label>/`

The parent folder includes:

- `command_centre_snapshot.yaml`
- `config_resolved.yaml`
- `supported_options_snapshot.yaml`
- `run_fingerprint.json`
- `input_manifest.json`
- `child_runs.csv`
- `aggregate_progress_log.csv`
- `progress_current.json`
- `aggregate_runtime_profile.csv`
- `aggregate_metrics_summary.csv`
- `validation_summary.csv`
- `README_run.md`

Backend child folders are stored under:

- `child_runs/`

Each child run folder includes:

- `command_centre_snapshot.yaml`
- `config_resolved.yaml`
- `run_fingerprint.json`
- `input_manifest.json`
- `runtime_profile.csv`
- `runtime_profile.json`
- `progress_log.csv`
- `progress_current.json`
- `model_stats_daily.csv`
- metrics outputs
- validation checks
- `README_run.md`

## Engineering vs methodological settings

Engineering controls:

- output mode
- cache use
- benchmark cache use
- progress reporting

Methodological controls:

- split
- period mode
- selected regimes
- risk mode
- gamma values
- methodological approximation flags

Methodological approximations must remain explicitly labelled. The current backend refuses them.

## Agent maintenance contract

Whenever an agent adds or changes any of the following:

- scenario model
- artifact ID
- selected period or selected-week policy
- split definition
- granularity
- horizon
- market scope
- asset configuration
- risk mode
- output mode
- method version
- runner/backend
- benchmark policy
- methodological approximation option

it must update:

1. `scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_supported_options.yaml`
2. `docs/optimisation/RUN_COMMAND_CENTRE_GUIDE.md`
3. command-centre validation and doctor checks
4. relevant tests
5. any affected run-contract documentation

If one of these items changes without updating the registry and guide, the task is incomplete.
