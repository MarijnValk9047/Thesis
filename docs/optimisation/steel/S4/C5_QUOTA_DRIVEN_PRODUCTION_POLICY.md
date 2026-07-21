# C5 Quota-Driven Production Policy

## Decision

The deterministic physical model must choose represented process on/off states,
throughputs and C1 route throughput from the requested final-product quota.
It must not receive a fixed hourly operating calendar or a fixed C1 retained
BF-BOF versus DRP/EAF output split.

## Hard constraints retained

- configuration topology and inactive assets;
- source-carded minimum and maximum process rates;
- material balances, buffer capacities and terminal inventory rules;
- BFG, COG and BOFG carrier balances and eligible sinks;
- represented steam, utility and named-NG constraints;
- hard cumulative final-product deadlines.

## What the objective means

The model remains price-free. It therefore finds a compact physical-feasibility
schedule after satisfying the quota; it does not claim to choose economically
optimal timing. Electricity, steam and WAG affect feasibility through their
balances, not through market prices.

## Explicit exclusions

No WAG/NG ratio is invented; aggregate WAG and mixed gas do not become physical
carriers; residual electricity/NG remain reporting only; no cost, DA, ETS or
full Scope-1 claim is introduced.
