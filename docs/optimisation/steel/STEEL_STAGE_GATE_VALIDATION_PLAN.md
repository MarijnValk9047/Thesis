# Steel Stage Gate Validation Plan

## Purpose

This document defines the stage-gate validation contract for `S2` through `S9`.

It is the operational companion to:

- `STEEL_IMPLEMENTATION_FREEZE_V1.md`;
- `STEEL_S2_S3_IMPLEMENTATION_SCOPE.md`;
- `STEEL_TRACTABILITY_AND_CHANGE_CONTROL.md`.

## Cross-Stage Mandatory Checks

Every meaningful stage from `S2` onward must report:

- solver status;
- objective value;
- runtime;
- MIP gap if applicable;
- variable count;
- binary count;
- constraint count;
- infeasibility diagnostics if failed;
- production fulfilment before any profit or cost claim;
- terminal inventory treatment for all active stores.

## `S2`

### Stage Purpose

Build the deterministic hourly metallic material-flow LP.

### Minimum Viable Implementation

- metallic topology;
- bounded buffers;
- fixed production target;
- terminal inventory rules;
- infeasibility-diagnostic structure.

### Required Checks

- structure and unit checks;
- material-balance closure;
- production fulfilment;
- inventory terminal rules;
- no-free-buffer-battery checks;
- annualised reconciliation where relevant.

### Go / No-Go Gate

Go only if balances close and the route logic is physically interpretable.

### Required Run Metadata

- configuration;
- target policy;
- active buffer classes;
- annual-to-hourly translation method if any candidate envelope is used.

### Required Metrics

- production totals;
- route-throughput totals;
- shortfall or slack totals;
- ending inventories;
- infeasibility-class label if failed.

### Thesis Usability Condition

Usable only if physical structure and production accounting are explainable.

### Red Flags

- fake feasibility from missing route constraints;
- unconstrained inventory shifts;
- use of public annual values as hidden hourly caps.

## `S3`

### Stage Purpose

Add the minimal WAG, internal-energy, emissions, and economic layer.

### Minimum Viable Implementation

- `BFG`, `COG`, and `BOF_or_LD_gas` balances;
- natural-gas and electricity imports;
- flare or spill variables;
- gross ETS cost visible;
- `N1` tariff proxy if active.

### Required Checks

- all `S2` checks;
- WAG balance checks;
- flare or spill non-free-disposal checks;
- holder endpoint checks if holders are active;
- no-double-counted-emissions checks;
- gross ETS and free-allocation separation;
- average-demand target not used as connection capacity.

### Go / No-Go Gate

Go only if economics and emissions are coherent and WAG structure does not create free energy.

### Required Run Metadata

- active carrier split;
- emissions architecture;
- tariff-policy flag;
- hydrogen and CCS flags;
- source and scenario tags for all volatile prices.

### Required Metrics

- import totals by carrier;
- WAG generation and use totals;
- flare or spill totals;
- gross ETS cost;
- free-allocation module status;
- tariff-proxy cost totals.

### Thesis Usability Condition

Usable only if costs and emissions are attributable and the base objective remains fixed-target cost minimisation.

### Red Flags

- hidden free-allocation netting;
- proxy tariff values presented as contract truth;
- product-revenue objective sneaking into the base case.

## `S4`

### Stage Purpose

Add deterministic hourly DA price-taking dispatch.

### Minimum Viable Implementation

- exogenous DA price input;
- price-taking dispatch logic;
- realised-price settlement under fixed production policy.

### Required Checks

- physical feasibility preserved under DA prices;
- price-taking assumption explicit;
- settlement separated from optimisation-stage expectation;
- production fulfilment before any economic interpretation.

### Go / No-Go Gate

Go only if deterministic DA behaviour is explainable without bidding logic.

### Required Run Metadata

- DA price source;
- market zone;
- gate-closure convention;
- benchmark definitions.

### Required Metrics

- DA energy cost;
- average price paid;
- dispatch response to price;
- benchmark comparison outputs.

### Thesis Usability Condition

Usable only if described clearly as deterministic price-taking dispatch and not as bidding.

### Red Flags

- schedule-and-settle mislabeled as bidding;
- market behaviour used to hide unresolved `S3` accounting problems.

## `S5`

### Stage Purpose

Add DA bidding and settlement.

### Minimum Viable Implementation

- bid representation;
- clearing logic;
- settlement against realised DA prices;
- post-clearing physical redispatch.

### Required Checks

- first-stage information timing;
- settlement consistency;
- physical feasibility after clearing;
- benchmark preservation.

### Go / No-Go Gate

Go only if bidding logic uses only information available at bid time.

### Required Run Metadata

- bid policy;
- clearing assumptions;
- settlement rules;
- redispatch policy.

### Required Metrics

- submitted bids;
- cleared bids;
- settlement cost;
- post-clearing physical deviations.

### Thesis Usability Condition

Usable only if realised settlement and physical feasibility are both visible.

### Red Flags

- using realised future prices at bid time;
- reporting bidding value without settlement.

## `S6`

### Stage Purpose

Add stochastic DA, risk-neutral.

### Minimum Viable Implementation

- coherent scenarios;
- scenario probabilities;
- non-anticipative first-stage decisions;
- stable physical model from earlier stages.

### Required Checks

- scenario probability checks;
- temporal-coherence checks;
- non-anticipativity checks;
- same production, carbon, tariff, and horizon assumptions across forecast-model comparisons.

### Go / No-Go Gate

Go only if stochastic comparisons isolate forecast or scenario quality rather than hidden policy changes.

### Required Run Metadata

- forecast model ID;
- scenario source;
- scenario count;
- probability convention;
- horizon and granularity.

### Required Metrics

- expected objective;
- realised settlement;
- scenario diagnostics;
- benchmark deltas by forecast model.

### Thesis Usability Condition

Usable only if scenario probabilities and information timing are auditable.

### Red Flags

- scenario-specific first-stage decisions;
- hidden changes in tariff or production policy across forecast-model comparisons.

## `S7`

### Stage Purpose

Add `mFRR` extension.

### Minimum Viable Implementation

- reserve capacity logic;
- deliverability constraints;
- baseline or rebound treatment where required;
- activation and non-delivery logic where applicable.

### Required Checks

- reserve deliverability checks;
- downstream buffer feasibility;
- production fulfilment under reserve commitments;
- no reserve revenue claim without deliverability.

### Go / No-Go Gate

Go only if DA-only bidding and settlement plus physical deliverability are already stable.

### Required Run Metadata

- reserve product definition;
- activation assumptions;
- baseline or rebound convention;
- penalty logic.

### Required Metrics

- reserve capacity committed;
- activation delivered;
- non-delivery events or penalties;
- incremental value versus `DA_only`.

### Thesis Usability Condition

Usable only if reserve value is tied to actual deliverability and production fulfilment.

### Red Flags

- reserve revenue used to mask feasibility issues;
- `mFRR` presented as a granularity experiment.

## `S8`

### Stage Purpose

Add 15-minute and or `D_plus_4` extensions.

### Minimum Viable Implementation

- one-dimension-at-a-time design;
- observed quarter-hour truth for evaluation where applicable;
- stable metadata for lead day, forecast origin, and scenario lineage.

### Required Checks

- DST-safe handling;
- observed quarter-hour truth only;
- one-dimension-at-a-time checks;
- unchanged production policy across comparisons.

### Go / No-Go Gate

Go only if the comparison isolates granularity or horizon rather than moving multiple design axes at once.

### Required Run Metadata

- granularity;
- horizon;
- forecast origin;
- lead-day structure;
- scenario metadata.

### Required Metrics

- realised cost or value by granularity or horizon;
- feasibility impacts;
- benchmark comparability;
- coverage of observed quarter-hour targets.

### Thesis Usability Condition

Usable only if observed truth and comparability caveats are explicit.

### Red Flags

- synthetic quarter-hour truth treated as observed;
- 15-minute and `D_plus_4` added together without explicit combined-change labelling.

## `S9`

### Stage Purpose

Add CVaR or risk aversion.

### Minimum Viable Implementation

- scenario probabilities;
- explicit downside metric;
- non-anticipative formulation preserved;
- risk-neutral baseline retained.

### Required Checks

- CVaR probability checks;
- risk-measure definition checks;
- non-anticipativity checks retained;
- validation-period-only parameter selection.

### Go / No-Go Gate

Go only if risk-neutral stochastic behaviour is already understood and trusted.

### Required Run Metadata

- alpha;
- risk weight;
- downside metric definition;
- scenario set and probabilities.

### Required Metrics

- expected objective;
- VaR or threshold variable;
- CVaR;
- realised downside comparison.

### Thesis Usability Condition

Usable only if the risk-return tradeoff is reported without contaminating earlier benchmark logic.

### Red Flags

- CVaR used to cover weak scenarios or unstable base physics;
- risk settings tuned on final test outcomes.

## Current Steel Gate Note

The current steel workstream is frozen at `S2.11`. The authoritative end-of-`S2` contract and the allowed `S3.0` scope boundary are recorded in `STEEL_S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT.md`.
