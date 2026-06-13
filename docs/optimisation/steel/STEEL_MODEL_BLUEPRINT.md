# Steel Model Blueprint

## Goal

Define the methodological transition from the hydrogen test case to a later steel-plant MILP asset configuration.

This document freezes the first steel scope so future implementation work does not drift into a site-digital-twin ambition that the thesis does not need.

## Why The Steel Model Is Different

The hydrogen test case is mainly an energy-procurement and flexibility scheduling problem with a small physical system.

The steel case is different. It is a material-constrained process-network model in which electricity cost matters, but electricity arbitrage alone does not define feasible operation.

The steel model must eventually represent:

- linked process units rather than one main flexible load;
- material conversions across routes;
- intermediate buffers and bottlenecks;
- production fulfilment and quality-proxy constraints;
- emissions and ETS consequences;
- electricity consumption as one layer inside a broader industrial process network.

The thesis question remains economic and methodological:

- do forecast/scenario inputs change realised operating value;
- does DA granularity change flexibility value;
- does stochastic optimisation improve realised performance relative to simpler policies;
- what is the risk-return tradeoff under CVaR;
- what value is later added by `mFRR`.

The steel model is therefore not a full plant replica. It is a tractable Tata-inspired MILP test bed for those questions.

## Scope Freeze

### Baseline Asset Configuration

Current route:

- BF-BOF configuration as the baseline reference case.

This baseline is needed to anchor comparisons and to avoid claiming flexibility gains without a stable conventional reference.

### Main Comparison Asset Configuration

Main future case:

- Phase 1 hybrid BF-BOF + DRP-EAF configuration.

This hybrid case is the main steel flexibility case because it introduces additional electrical and material-routing flexibility without requiring a full end-state decarbonised plant model on day one.

### First Steel Implementation

The first implementation must be:

- deterministic;
- hourly;
- `DA_only`;
- continuous/LP where possible;
- physically interpretable before adding stochastic or mixed-integer complexity.

### Explicitly Deferred

Do not implement yet:

- a full Tata digital twin;
- `mFRR` participation;
- exclusive group bids;
- quarter-hour steel optimisation;
- `D_plus_4` steel optimisation;
- detailed confidential or guessed Tata operating data;
- detailed thermodynamic submodels that do not change the thesis question.

## Frozen Comparison Logic

When comparing forecast/scenario inputs later, keep these constant unless a test explicitly studies asset-policy sensitivity:

- site boundary;
- configuration definition;
- production policy;
- emission-accounting convention;
- buffer definitions;
- grid-connection policy;
- benchmark definitions.

If these change while forecast/scenario inputs also change, the result is not a clean forecast comparison.

## Model Layers

### Layer 1: Steel Skeleton Material-Flow LP

Purpose:

- establish route topology and mass-balance logic before market optimisation.

Minimum content:

- process-unit throughput variables;
- carrier and material nodes;
- route capacities;
- material balances;
- basic store/buffer dynamics where needed;
- production output accounting.

Acceptance condition:

- the model can reproduce internally consistent production flows without electricity-price logic.

### Layer 2: Deterministic Energy, Cost, And Emissions Layer

Purpose:

- add operating cost, power consumption, and ETS exposure to the skeleton.

Minimum content:

- electricity consumption by process unit;
- fuel and reductant cost terms where represented;
- emissions factors and ETS treatment;
- fixed or policy-driven production targets;
- deterministic DA price settlement.

Acceptance condition:

- all costs and emissions are unit-consistent and attributable by route and process.

### Layer 3: Phase 1 DRP-EAF Flexibility Layer

Purpose:

- represent the main new flexible steel route in a tractable way.

Minimum content:

- DRP-EAF capacity limits;
- relevant ramping or minimum stable load where justified;
- DRI buffer representation if used;
- route-switching or route-sharing logic with the BF-BOF baseline where needed;
- flexibility that is operationally plausible rather than merely mathematically convenient.

Acceptance condition:

- the model shows where flexibility comes from and which constraints limit it.

### Layer 4: DA Bidding And Settlement

Purpose:

- move from costed dispatch to DA participation logic.

Minimum content:

- explicit submitted DA quantities or a clearly defined cleared-consumption policy;
- clearing and settlement representation;
- realised vs optimisation-stage reporting;
- benchmark alignment with the hydrogen workstream.

Acceptance condition:

- the model distinguishes forecast-stage objective value from realised settlement.

### Layer 5: Stochastic DA And CVaR

Purpose:

- compare scenario inputs and downside control.

Minimum content:

- coherent price scenarios with probabilities;
- non-anticipative first-stage decisions;
- CVaR on a clearly defined downside metric;
- validation-based parameter selection only.

Acceptance condition:

- stochastic and CVaR results are explainable without violating information timing.

### Layer 6: Hourly Vs Quarter-Hour

Purpose:

- test whether additional market granularity changes flexibility value.

Minimum content:

- explicit granularity flag;
- timestamp and DST-safe horizon handling;
- comparable asset assumptions across granularities.

Acceptance condition:

- hourly and quarter-hour cases differ in granularity, not in hidden asset-policy changes.

### Layer 7: `mFRR` Extension Later

Purpose:

- evaluate reserve value only after DA-only steel is stable.

Minimum content later:

- capacity bids;
- activation logic;
- deliverability constraints;
- DA plus `mFRR` interaction;
- separate revenue, energy, and penalty reporting.

Acceptance condition:

- reserve value is reported only after DA-only steel behaviour is already trusted.

## First Implementation Principle

Start with a process-network LP that can answer:

1. what production must flow through which route;
2. which units consume electricity;
3. where storage-like flexibility actually exists;
4. what cost and ETS consequences follow from operating choices.

Do not start with a binary-heavy bidding model. That would hide basic structural mistakes behind solver complexity.

## Future Structure Recommendation

Recommended future structure, subject to alignment with existing repo conventions:

```text
docs/optimisation/steel/
  README.md
  STEEL_MODEL_BLUEPRINT.md
  STEEL_DATA_AND_PARAMETER_PLAN.md
  STEEL_ASSUMPTION_REGISTER.md
  STEEL_VALIDATION_AND_TRACTABILITY_PLAN.md
  STEEL_IMPLEMENTATION_ROADMAP.md

data/03_Optimisation/inputs/assets/steel/
  source_cards/
  parameter_register.csv
  process_units.csv
  carriers.csv
  stores.csv
  conversion_factors.csv
  emissions_factors.csv
  costs.csv
  configurations.csv
  validation_targets.csv

scripts/Data/04_Steel_Test_Case/
  configs/
  steel/
  tests/
```

This is a recommendation only. The current task does not create that scaffold.

## Red Flags

Warn explicitly if any of the following occur:

- fake flexibility created by allowing material rerouting that the chosen configuration does not physically permit;
- stores treated as free batteries without residence, throughput, loss, or policy limits;
- production profit reported without production fulfilment or route-feasibility reporting;
- test-period tuning of parameters, benchmarks, or risk settings;
- missing non-anticipativity in stochastic DA decisions;
- asset policy changed while claiming a forecast/scenario comparison;
- perfect foresight described as a realistic operating strategy;
- `mFRR` added before DA-only steel is stable and explainable.

## Stop Condition For First Steel Coding

Do not begin the steel code scaffold until these are accepted:

- first implementation scope is frozen;
- parameter promotion path is frozen;
- initial assumption register exists;
- validation gates are agreed;
- steel implementation roadmap is accepted.
