# Steel S2 S3 Implementation Scope

## Purpose

This document freezes the allowed scope for the first steel coding phase.

It covers only:

- `S2` deterministic hourly metallic material-flow LP;
- `S3` minimal `B_lite` WAG, internal-energy, emissions, and economic layer.

It does not authorise Pyomo code, approved numerical values, or later market layers by itself.

## `S2` Allowed Components

Allowed in `S2`:

- baseline and Phase 1 route structure;
- metallic material nodes and flows;
- explicit `BF_BOF` and `DRP_EAF` route presence;
- bounded `DRI` and slab or `WIP` buffers;
- terminal inventory rules;
- fixed production target;
- infeasibility-diagnostic design;
- continuous LP-first structure.

## `S2` Forbidden Components

Forbidden in `S2`:

- WAG valuation;
- natural-gas or electricity price objective terms;
- gross ETS cost;
- tariff costs;
- product revenue;
- DA prices;
- bidding;
- stochasticity;
- `mFRR`;
- 15-minute or `D_plus_4`;
- CVaR.

## `S2` Minimum Variables And Constraints At Conceptual Level

Conceptually required in `S2`:

- route and process throughput variables;
- store state variables for allowed buffers;
- inflow and outflow variables for bounded buffers;
- production fulfilment or shortfall accounting;
- material-balance constraints by node and period;
- route-capacity constraints;
- buffer-capacity constraints;
- buffer terminal-rule constraints;
- route-share or sink constraints where frozen by configuration;
- infeasibility or slack reporting structure if used.

## `S2` Validation Checks

`S2` must support:

- structure validation;
- unit validation;
- material-balance closure;
- production fulfilment reporting;
- terminal inventory checks;
- no-free-buffer-battery checks;
- annualised reconciliation against validation anchors where relevant;
- infeasibility classification.
- explicit input-mode and thesis-usability reporting.

## `S2` Run Outputs And Diagnostics

Minimum `S2` outputs:

- solver status;
- objective value if applicable;
- runtime;
- variable, binary, and constraint counts;
- production totals;
- route-throughput totals;
- store trajectories;
- terminal inventory status;
- infeasibility diagnostics if failed;
- run-level explanation of active assumptions.

## `S3` Allowed Components

Allowed in `S3`:

- all `S2` components;
- minimal `B_lite` WAG layer;
- separate `BFG`, `COG`, and `BOF_or_LD_gas` carriers;
- natural-gas import;
- electricity import;
- flare or spill variables;
- `Vattenfall` interface;
- gross ETS cost visible;
- optional separate free-allocation placeholder only as later sensitivity or reporting layer;
- `N1` proxy tariff structure;
- fixed production target unchanged.

## `S3` Forbidden Components

Forbidden in `S3`:

- base-case product-revenue objective;
- hidden free-allocation treatment;
- `CBAM`;
- full `Vattenfall` dispatch;
- detailed mixed-gas optimisation;
- detailed steam or oxygen networks;
- DA bidding or settlement;
- stochasticity;
- `mFRR`;
- 15-minute or `D_plus_4`;
- CVaR.

## `S3` Minimum Variables And Constraints At Conceptual Level

Conceptually required in `S3`:

- per-carrier WAG balance variables;
- import variables for natural gas and electricity;
- flare or spill variables for WAG disposal;
- optional simple holder state for `BOF_or_oxygas` if activated;
- cost-accounting terms for energy imports;
- visible gross ETS cost term;
- tariff-proxy cost terms if activated;
- emissions-accounting terms consistent with the no-double-counting architecture;
- WAG-balance constraints;
- holder and terminal rules if holder logic is active;
- no-free-energy valuation structure.

## `S3` Validation Checks

`S3` must support:

- all `S2` checks;
- WAG generation plausibility checks;
- per-carrier WAG balance closure;
- flare or spill non-free-disposal checks;
- holder endpoint checks if active;
- gross ETS and any free-allocation credit reported separately;
- no-double-counted-emissions checks;
- average-demand anchors not reused as connection capacity;
- tariff-proxy labelling;
- hydrogen and CCS flags inactive unless explicitly configured.

## `S3` Run Outputs And Diagnostics

Minimum `S3` outputs:

- all `S2` outputs;
- WAG balance summaries by carrier;
- natural-gas and electricity import totals;
- flare or spill totals;
- route-level energy and emissions summaries;
- gross ETS cost;
- free-allocation status as inactive, reporting-only, or sensitivity-only;
- tariff-proxy status;
- run-level list of candidate or sensitivity-only economic assumptions.

## What Must Remain Candidate Or Sensitivity Only

The following must remain candidate or sensitivity only through the first coding phase:

- annual-to-hourly operating coefficients not yet approved;
- exact Tata recipes and yields;
- exact WAG holder capacities;
- derived WAG emissions factors;
- tariff values used only through proxy structures;
- commodity prices without explicit timestamp, source, and scenario tags;
- hydrogen and CCS timing or cost assumptions;
- any product-value or margin proxies;
- any free-allocation credit values.

In `S2.3`, candidate categories may be mapped into the future deterministic `S2` schema surface for review purposes, but they still may not be treated as approved executable model inputs.

In `S2.4`, selected deterministic `S2` candidate categories may be normalised into non-executable candidate-review tables with unit, sign, evidence, and promotion-blocker fields. This still does not approve any executable steel input row.

In `S2.5`, structural support and numerical approval are separated explicitly. Route, carrier, and buffer structure may be review-supported while the related numerical categories remain blocked from executable `S2` use.
