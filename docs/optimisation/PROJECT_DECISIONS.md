# Project Decisions

## Purpose

This file freezes the current optimisation-scope decisions so later work does not have to reconstruct them from scattered reports, configs, or run folders.

These decisions describe the repository's current methodological position. They do not imply that all later phases are complete.

## Active Default

The current command-centre-hardened default path is:

- hydrogen test case;
- `DA_only`;
- hourly;
- `D_only`;
- selected regimes / selected weeks;
- risk-neutral execution.

This is the stable default because it is the most hardened path in the current code and governance layer. It should be treated as the baseline optimisation surface for the next thesis stage.

## Scope And Sequencing Decisions

### 1. No exclusive group bids for now

Exclusive group bids are not part of the active thesis implementation scope.

Reason:

- the current thesis emphasis is forecast/scenario/granularity/horizon comparison;
- bidding-strategy variation is secondary at this stage.

### 2. `DA_only` before `mFRR`

Day-ahead-only optimisation must be stable, explainable, and reportable before `mFRR` capacity or activation modelling is added.

Reason:

- the current blocker is not lack of market complexity;
- the current blocker is upstream scenario support and thesis-grade comparability.

### 3. Hydrogen before steel MILP

The hydrogen test case is the required verification case before any full steel-plant MILP extension.

Reason:

- the hydrogen case is the current methodological and engineering proving ground;
- later steel extension should inherit an already verified run/reporting/governance structure.

## Benchmark Decisions

### 4. Perfect foresight is oracle only

Perfect foresight is an upper-bound benchmark. It is not a realistic operating strategy and must never be described as one.

### 5. Price-insensitive benchmark is required

A price-insensitive benchmark remains mandatory.

Reason:

- the thesis question is not only whether the optimiser works;
- it is whether forecast/scenario-informed flexibility beats simpler non-price-responsive behaviour.

## Risk And Scenario Decisions

### 6. Scenario probabilities are required

Scenario files used by the optimiser must have explicit probabilities.

Reason:

- stochastic optimisation and CVaR interpretation depend on probability mass;
- missing probabilities are a methodological red flag, not a small formatting issue.

### 7. Validation-only selection

Model, scenario, and CVaR policy selection must be validation-based. Test-period evidence is for frozen-policy out-of-sample evaluation only.

This applies to:

- scenario configuration choice;
- selected-week policy use;
- future CVaR gamma selection.

### 8. CVaR exists, but is not yet the command-centre default

The repository already contains meaningful CVaR implementation work. However:

- CVaR is not the current command-centre default;
- the hardened default path remains risk-neutral selected-week hydrogen.

This distinction must be preserved in docs and reporting.

## Quarter-Hour And Truth-Type Decisions

### 9. Observed-vs-counterfactual quarter-hour distinction is mandatory

Quarter-hour work currently has two different truth regimes:

- observed-market quarter-hour evaluation;
- counterfactual / synthetic quarter-hour path support for downstream experiments.

These must remain explicitly separated.

Observed-market quarter-hour results must not be mixed with synthetic-path results as if they were the same evidence type.

## Current Blocker

### 10. Scenario support mismatch is the current thesis blocker

The main current optimisation blocker is upstream scenario support mismatch across artifacts, not missing MILP infrastructure.

This means:

- the repository already contains meaningful optimisation logic, governance, and reporting infrastructure;
- final three-model hourly optimisation comparison remains blocked until support alignment is repaired or re-exported.

## Data And Cleanup Decisions

### 11. `data/01_cleaned/` is a separate policy stream

Tracked cleaned-data modifications must not be handled as routine untracked cleanup.

Reason:

- the tree mixes baseline inputs, generated derivatives, and diagnostics;
- cleanup requires a family-by-family policy decision first.

### 12. Important historical attempts must be summarised before cleanup

The repository contains noncanonical branches that still matter methodologically:

- May 2026 forecasting campaign;
- LEAR Strict / Lago work;
- quarter-hour phase workflow;
- scenario calibration / undercoverage audits;
- hydrogen support/readiness diagnostics;
- CVaR validation and anomaly work.

These should be summarised before any cleanup that would make their role harder to understand.
