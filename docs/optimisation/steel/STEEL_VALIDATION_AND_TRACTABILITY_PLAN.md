# Steel Validation And Tractability Plan

## Goal

Define the validation gates and tractability rules that must be passed before steel-model results are trusted for thesis use.

The steel model should fail loudly when structure, units, balances, or reporting are wrong. Solver success alone is not validation.

This document now serves as the high-level validation summary.

Detailed stage gates and tractability or change-control rules are frozen in:

- `STEEL_STAGE_GATE_VALIDATION_PLAN.md`
- `STEEL_TRACTABILITY_AND_CHANGE_CONTROL.md`

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

## Wave C S2 Validation Plan

For the future S2 deterministic hourly material-flow LP, validation should explicitly include:

- annualised BF hot-metal reconciliation;
- annualised DRP DRI reconciliation;
- annualised BOF liquid-steel reconciliation;
- annualised EAF liquid-steel reconciliation;
- total finished-output or slab-plus-flat reconciliation against the chosen target policy;
- BOF versus EAF route-share reconciliation where the hybrid case is active;
- DRI inventory endpoint-neutrality checks;
- slab or WIP endpoint-neutrality checks;
- no-free-battery DRI cycling checks;
- no-free-battery slab or WIP cycling checks;
- downstream bottleneck detection;
- infeasibility classification into at least iron-unit shortage, BOF mix infeasibility, EAF metallic-feed shortage, downstream bottleneck, and terminal-inventory violation.

These are defined as future checks and diagnostic labels, not as already implemented code.

## Wave C Reporting Rule

When S2 is later implemented, its reporting must state:

- which annual-to-hourly translation method was used;
- which availability and utilisation assumptions defined the hourly envelopes;
- which envelope choices remained candidate or sensitivity material;
- which inventory endpoint rules were active;
- which infeasibility class applied if the model failed.

## Wave D S3 Validation Plan

For the future S3 semi-detailed WAG and emissions layer, validation should explicitly include:

- separate `BFG`, `COG`, and `BOF_or_LD_gas` generation plausibility checks against generic public ranges;
- per-carrier WAG balance-closure checks;
- flare or spill non-free-disposal checks;
- holder endpoint checks whenever a holder state is activated;
- no-free-energy checks so WAG value appears only through explicit sink paths;
- no-double-counted-emissions checks across process, WAG, and natural-gas accounting;
- validation against public order-of-magnitude anchors such as residual-gas reuse scale, residual-gas-based power scale, Phase 1 WAG scarcity direction, and DRI-route natural-gas plus captured-CO2 direction;
- explicit reporting of valuation assumptions, candidate coefficients, and sensitivity-only derived emissions factors.

These are defined as future checks and reporting obligations, not as already implemented code.

## Wave D Reporting Rule

When S3 is later implemented, its reporting must state:

- which carrier split was active;
- whether a holder was active and how its terminal rule was handled;
- how WAG value was assigned and whether natural-gas substitution was the active primary method;
- whether flare or spill penalties were active;
- which emissions architecture was used to avoid double counting;
- which candidate or sensitivity-only terms remained unresolved.

## Wave E Economic And Policy Validation Plan

For the future Wave E economic and policy layer, validation should explicitly include:

- production target met under the chosen fixed-target policy;
- no product-revenue objective active in the base case;
- gross ETS cost and any free-allocation credit reported separately;
- average-demand anchors not reused as technical or contracted connection capacity;
- tariff proxy labelled clearly as proxy rather than site contract truth;
- hydrogen and CCS flags active only when explicitly configured;
- DA, `mFRR`, and CVaR layers inactive before their scheduled stages;
- every volatile commodity or energy price input carrying timestamp, source, and scenario tags;
- production policy unchanged across forecast-quality comparisons unless the experiment explicitly studies policy sensitivity.

These are defined as future checks and governance gates, not as already implemented code.

## Wave E Reporting Rule

When the minimal economic layer is later implemented, its reporting must state:

- whether fixed-target cost minimisation was active;
- whether any ex-post margin was reporting-only;
- whether gross ETS cost was visible;
- whether any free-allocation credit was inactive, active, or sensitivity-only;
- whether `N1` proxy tariff structure was active;
- whether hydrogen or CCS availability flags were active;
- which price-series timestamp and scenario tags were used.

## Tractability Sequence

The default sequence is:

1. one day before one week;
2. hourly before quarter-hour;
3. deterministic before stochastic;
4. continuous relaxation before binaries;
5. few scenarios before many;
6. `DA_only` before `mFRR`.

Do not skip ahead unless a previous gate is already passed and documented.

For the controlling tractability and change-control rules, use `STEEL_TRACTABILITY_AND_CHANGE_CONTROL.md`.

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
- validation targets are defined at least in outline;
- `STEEL_IMPLEMENTATION_FREEZE_V1.md` is accepted;
- `STEEL_S2_S3_IMPLEMENTATION_SCOPE.md` is accepted.

### Go From Skeleton LP To Costed Deterministic Model

Allowed only if:

- mass balances close;
- configuration topology is stable;
- production metric is frozen for the phase.

For detailed gate-by-gate checks from `S2` through `S9`, use `STEEL_STAGE_GATE_VALIDATION_PLAN.md`.

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
