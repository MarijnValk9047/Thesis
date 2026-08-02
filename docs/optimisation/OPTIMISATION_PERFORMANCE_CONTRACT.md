# Optimisation performance contract

## Status and scope

This contract governs semantics-preserving acceleration of the active hydrogen
rolling optimisations and the deterministic rolling steel MILP. It is also the
required interface for a future stochastic steel runner, but it does not
authorise that model stage.

The canonical mode is `performance_mode: optimized_equivalent`.
`legacy_rebuild` is retained only for parity and regression diagnostics.
Performance claims may not change scenarios, horizon, temporal resolution,
constraints, objective, risk preference, bids, settlement, quotas, physical
parameters or information timing.

## Shared implementation

`scripts/optimisation_performance.py` defines:

- stable structural signatures;
- an immutable structural-template registry;
- DST-shape labelling;
- peak-working-set and stage timers;
- the common runtime schema;
- numerical parity helpers.

The structural signature is based on model type, granularity, timestep count,
scenario count, bid grid, DST shape, physical-config hash and quota structure.
A template-cache hit never implies Pyomo-model reuse. Every record separately
reports `pyomo_model_rebuilt`. The current safe implementation reuses immutable
inputs and structural metadata, while both model families still rebuild their
Pyomo model.

## Hydrogen path

The Strict LEAR rolling comparison pre-indexes scenarios, origins, timestamps,
probabilities and actual-settlement rows before the origin loop. Actual prices
remain in a separate settlement map and never enter optimization arrays.

Optimized extraction materialises executed-D bids and scenario dispatch only.
Full-horizon economic scenario totals are read directly from the solved model,
so expected objective reporting remains unchanged without constructing broad
D+1--D+4 DataFrames. `full_audit` preserves the complete extraction path.

Warm-start snapshots shift scenario-independent bids by common timestamps.
Scenario-dependent values are eligible only when scenario ID, residual source
block and structural signature all match. Rejection falls back to a cold solve;
it never changes the model or information set.

## Steel path

The deterministic rolling builder caches validated immutable CSV input tables
and structural fingerprints. Cache invalidation uses file size, nanosecond
modification time and, after a change, a complete SHA-256 refresh. The physical
builder, objective hierarchy and all stage gates remain unchanged.

Cross-replan steel warm starting is currently recorded as
`safe_fallback_no_cross_replan_mapper`. Existing complete-solution captures do
not by themselves prove that variable names can be shifted safely between
different rolling states. A future mapper must demonstrate state, index and
objective parity before activation.

## Required runtime fields

Per origin and solve, report input resolution, array preparation, model build,
presolve/solver, postprocessing, DataFrame construction, output I/O, wall time,
working set, model size, scenarios, timesteps, bid-ladder size, solver status,
termination, MIP gap, structural signature, cache status, model-reuse status,
warm-start status and whether the Pyomo model was rebuilt. Bidding and
redispatch are separate records.

## Parity and acceptance

Legacy and optimized runs use identical inputs. Objective and monetary ledgers
must match within max(EUR 0.01, relative 1e-6); physical ledgers use their
governed numerical tolerances. Solver status, termination, MIP gap, state
carryover, quotas, clearing and settlement remain hard gates. Equivalent
dispatch optima are acceptable only when all economic and physical ledgers
close equivalently.

Speed targets never relax parity. A missed target is recorded as
`pass_parity_speed_targets_not_met`, with a bottleneck report.

## July 2026 diagnostic evidence

Hydrogen three-origin runtime evidence is in
`data/03_Hydrogen_Test_Case/performance_benchmarks/20260730_optimized_equivalent_a01/`.
It passed 96/96 realised-ledger parity checks. The separate one-origin
`20260730_optimized_equivalent_objective_parity_a02` fixture passed all 40
checks, including eight solver-objective checks with zero difference.

Measured bidding median speedups were 1.01x (H-D-30), 1.12x (H-D4-30), 1.22x
(QH-D4-10) and 0.97x (QH-D4-30). The QH targets were therefore not met. In
QH-D4-30, lazy extraction reduced postprocessing materially, but Gurobi solve
time remained dominant and variable across equivalent runs.

The final deterministic steel fixture is
`data/03_Optimisation/performance_benchmarks/20260730_optimized_equivalent_a02/`.
It passed 56/56 physical-ledger parity checks with exactly zero reported
difference. Median solver-path speedups were 0.97x for C0 and 1.08x for C1, both
within the allowed 10% non-regression band. This short two-replan fixture is
performance evidence only, not new canonical steel evidence.

All benchmark artifacts use `output_policy = audit`,
`run_class = diagnostic_performance` and
`lineage_role = non-canonical performance evidence`.
