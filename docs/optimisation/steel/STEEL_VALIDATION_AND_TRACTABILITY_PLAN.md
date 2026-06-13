# Steel Validation And Tractability Plan

## Goal

Define the validation gates and tractability rules that must be passed before steel-model results are trusted for thesis use.

The steel model should fail loudly when structure, units, balances, or reporting are wrong. Solver success alone is not validation.

## Validation Gates

### 1. Structure Validation

Check:

- every process unit belongs to an explicit configuration;
- every carrier referenced by a process or store exists;
- every flow variable has a defined unit and direction;
- no route exists only because a table omitted a constraint.

Pass condition:

- the model graph matches the intended baseline or Phase 1 topology.

### 2. Unit Validation

Check:

- power, energy, mass, volume, cost, and emissions units are explicit;
- timestep scaling is correct;
- emissions and cost coefficients match the unit used in the objective;
- no silent MW/MWh or tonne/kg mismatch exists.

Pass condition:

- a simple hand calculation for a few representative flows reproduces model coefficients.

### 3. Mass-Balance Validation

Check:

- material balances close by node and period;
- store balance equations reconcile initial state, inflow, outflow, and losses;
- no carrier is created or destroyed except through explicit conversion factors.

Pass condition:

- residual balance error is zero within numerical tolerance.

### 4. Production Target Validation

Check:

- the chosen production target metric is explicit;
- fulfilled, unmet, and excess production are all reported;
- penalties or slack variables are visible and interpretable.

Pass condition:

- production results can be explained in physical and economic terms, not only through objective value.

### 5. Energy Scale Validation

Check:

- aggregate electricity demand is plausible for the represented boundary;
- flexible-load share is plausible relative to the chosen configuration;
- route electricity consumption is not driven by a single unreasonable coefficient.

Pass condition:

- order-of-magnitude checks against external targets or literature ranges do not fail.

### 6. Emissions Validation

Check:

- emissions factors are attached to the right carriers or units;
- ETS treatment is explicit;
- route changes cause directionally sensible emissions changes.

Pass condition:

- reported emissions are internally consistent and aligned with the declared accounting convention.

### 7. Flexibility Realism Validation

Check:

- buffers are bounded and not acting as free batteries;
- route switching is constrained by process logic;
- ramping, minimum load, batch, or start-stop simplifications are documented;
- apparent flexibility can be traced to a real operational lever.

Pass condition:

- the model does not manufacture flexibility from missing constraints.

### 8. Market Realism Validation

Check:

- DA timing respects forecast origin and information release;
- stochastic first-stage decisions are non-anticipative;
- settlement is separated from optimisation-stage expectation;
- perfect foresight remains benchmark-only.

Pass condition:

- market behaviour is explainable under the chosen timeline.

### 9. Computational Reporting Validation

Check:

- every meaningful run records model size and solve metrics;
- failures preserve infeasibility diagnostics where available;
- methodological approximations are labelled;
- output folders and manifests follow repository governance.

Pass condition:

- another reviewer can tell what was solved and whether it should be trusted.

## Required Solver Reporting

Every meaningful steel optimisation run should report:

- solver status;
- objective value;
- runtime;
- MIP gap;
- variable count;
- binary variable count;
- constraint count;
- infeasibility diagnostics if failed.

This is mandatory even for deterministic baseline runs.

## Tractability Sequence

The default sequence is:

1. one day before one week;
2. hourly before quarter-hour;
3. deterministic before stochastic;
4. continuous relaxation before binaries;
5. few scenarios before many;
6. `DA_only` before `mFRR`.

Do not skip ahead unless a previous gate is already passed and documented.

## Engineering Vs Methodological Simplifications

These two categories must not be mixed.

### Engineering Simplifications

These change runtime mechanics without changing the intended mathematical question:

- caching resolved inputs;
- skipping completed runs;
- minimal output mode;
- limited plotting;
- reduced logging volume.

These do not need thesis caveats unless they affect reproducibility.

### Methodological Simplifications

These change the mathematical or physical meaning of the model:

- fewer scenarios than the target study design;
- relaxed binaries or removed commitment logic;
- looser MIP gap used to alter policy comparison;
- aggregated WAG treatment;
- simplified EAF thermodynamics;
- simplified downstream production policy;
- reduced horizon relative to the intended question.

These must be labelled before thesis use.

## Minimum Labelling Rule

If a methodological simplification is active, the run summary must state:

- what was simplified;
- why it was simplified;
- which claim is still allowed;
- which claim is blocked.

Unlabelled simplification is not acceptable.

## Stop/Go Gates

### Go From Planning To Coding

Allowed only if:

- scope blueprint is frozen;
- parameter plan is frozen;
- assumption register exists;
- validation targets are defined at least in outline.

### Go From Skeleton LP To Costed Deterministic Model

Allowed only if:

- mass balances close;
- configuration topology is stable;
- production metric is frozen for the phase.

### Go From Deterministic To Stochastic

Allowed only if:

- deterministic DA settlement is explainable;
- first-stage decision definition is explicit;
- scenario probabilities exist.

### Go From Hourly To Quarter-Hour

Allowed only if:

- hourly behaviour is stable;
- timestamp handling is DST-safe;
- asset assumptions remain comparable.

### Go From DA-Only To `mFRR`

Allowed only if:

- DA-only steel is explainable and reportable;
- deliverability constraints are identified;
- reserve logic does not rely on fake flexibility.
