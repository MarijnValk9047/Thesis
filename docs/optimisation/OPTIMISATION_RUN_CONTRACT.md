# Optimisation Run Contract

## Purpose

This contract defines the minimum reusable infrastructure layer for optimisation runs in this repository. It applies to hydrogen smoke runs now and to later selected-week, full-year, D+4, quarter-hour, DA+mFRR, and steel-asset runs.

The stable user-facing entrypoint for future runs is the command-centre layer:

- `scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_command_centre.yaml`
- `scripts/Data/03_Hydrogen_Test_Case/configs/optimisation_supported_options.yaml`
- `scripts/Data/03_Hydrogen_Test_Case/run_from_command_centre.py`

## Binding rules

1. Runner scripts must not directly load large scenario or market files.
2. Scenario and market inputs must be resolved through `optimisation/input_resolver.py`.
3. Reusable input slices must be fingerprinted before solve and cached through `optimisation/cache_manager.py`.
4. Every run must be able to compute an experiment fingerprint before solving.
5. Every run must record runtime profiling for at least `load`, `build`, `solve`, and `write`.
6. Output persistence must be selected through `optimisation/output_policy.py` using `minimal`, `audit`, or `full`.
7. Solver logs must be disabled for normal optimal bulk solves and retained for failures and audit days.
8. Scenario reduction, looser MIP gap, reduced bid grid, binary relaxation, or similar tractability changes must be labelled as methodological approximations, not engineering optimisations.
9. Command-centre-backed runs must write `command_centre_snapshot.yaml`, `run_fingerprint.json`, `progress_log.csv`, and `progress_current.json`.

## Required pre-solve objects

Before a solve starts, a run must be able to construct:

- resolved config;
- selected input request;
- input slice fingerprint;
- experiment fingerprint;
- output policy;
- runtime profiler.

## Approved input path

Large scenario and market inputs must flow through:

1. `scenario_catalog.yaml`
2. `scenario_loader.py`
3. `optimisation/input_resolver.py`
4. optional `optimisation/cache_manager.py`

The runner may then consume only the resolved slice objects returned by the resolver.

## Output modes

### `minimal`

Required for bulk smoke or production-like runs where the main need is reproducibility and summaries.

Expected outputs:

- resolved config or equivalent run manifest;
- experiment fingerprint;
- input slice fingerprint;
- runtime profiling table;
- minimal metrics and status outputs;
- solver logs only for failures or audit days.

### `audit`

Required when checking scenario support, suspicious days, feasibility issues, or settlement discrepancies.

Expected outputs:

- everything in `minimal`;
- additional manifests and intermediate tables needed for audit;
- solver logs for failures and audit days;
- enough intermediate outputs to reconstruct the suspicious run path.

### `full`

Required for thesis-ready or notebook-heavy interpretation runs.

Expected outputs:

- everything in `audit`;
- plots and rich timeseries outputs;
- nested day outputs where applicable.

## Run-folder expectation

Any future generic runner should produce a run folder that can explain:

- what period was requested;
- which artifact was used;
- which exact slice was loaded;
- whether the slice came from cache;
- what output policy was active;
- what methodological approximations were active;
- how much time was spent in load, build, solve, and write stages.

For command-centre executions that launch multiple child runs, this expectation applies at two levels:

- one parent experiment folder for the full command-centre execution;
- one child backend folder per regime/period/backend invocation.

The parent folder must record child-run linkage, aggregate progress, aggregate runtime, and aggregate validation status.
## Performance diagnostics extension

Runs that declare `performance_mode` must use the shared schema documented in
`OPTIMISATION_PERFORMANCE_CONTRACT.md`. Per-origin records distinguish input
resolution, array preparation, model build, solver, postprocessing, DataFrame
construction and output I/O. They also record working set, model size,
structural signature, cache/model-reuse status, warm-start status and
`pyomo_model_rebuilt`.

`optimized_equivalent` is the canonical execution mode for active hydrogen and
deterministic rolling steel. `legacy_rebuild` is allowed only in diagnostic
parity runs. A performance run with valid parity but an unmet speed target must
use status `pass_parity_speed_targets_not_met`; it may not be presented as a
measured speed improvement.

Minimum compact outputs are `performance_summary.csv`,
`runtime_by_origin.parquet`, `model_size_by_origin.csv`,
`cache_and_warm_start_checks.csv`, `legacy_optimized_parity.csv`,
`bottleneck_breakdown.csv`, `run_summary.json` and
`warnings_and_limitations.md`.

## Phase 6B steel market-validation extension

Hourly steel bid--clear--redispatch engineering runs use
`output_policy = diagnostics`, `run_class = diagnostic_validation` and a
non-economic thesis-candidate lineage. Consolidated bid, clearing, redispatch,
state and scenario-audit keys must start with `fixture_id`; a delivery date may
occur both as a standalone fixture and inside a rolling episode.

The compact governed run must include submitted D bid curves, realised D
clearing, realised D redispatch, complete rolling-state handoffs, solver
diagnostics, common terminal-band selection evidence, scenario-dispatch audit,
validation checks and the standard config/manifest/version/summary/warning/
registry files. Bidding solver diagnostics additionally record scenario IDs,
probability sum, probabilities and residual source-block provenance. Actual or
error fields are prohibited in submitted-bid output. Broad future-path output
is limited to explicitly selected audit origins; week trajectories retain only
their executed-D planned diagnostics.
