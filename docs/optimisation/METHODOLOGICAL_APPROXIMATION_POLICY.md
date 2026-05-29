# Methodological Approximation Policy

## Principle

Performance engineering and methodological approximation are different. If a change alters the optimisation problem, the input uncertainty, or the settlement logic, it must be declared explicitly as a methodological approximation.

## Must be labelled as methodological approximation

This label is required for any run using:

- scenario reduction beyond the intended baseline set;
- changed scenario probabilities;
- looser MIP gap than the baseline experiment design;
- reduced bid grid;
- binary relaxation or removal of intended integer logic;
- shortened horizon relative to the claimed experiment;
- altered benchmark definitions;
- altered clearing or settlement rules;
- altered production or feasibility constraints.

## Must not be described as engineering optimisation

Do not describe the following as mere runtime optimisation:

- scenario count cuts;
- CVaR simplifications that alter the optimisation objective;
- bid-grid thinning;
- lower-fidelity temporal aggregation;
- solving a relaxed model while reporting it as the intended MILP.

## Required run metadata when approximations are active

When an approximation is active, record:

- approximation label;
- exact change from baseline;
- reason for use;
- expected effect on interpretation;
- whether the run remains thesis-usable.

## Default stance for this repository

The default baseline assumptions remain:

- original MILP formulation;
- original scenario probabilities;
- original bid grid;
- original clearing logic;
- original settlement logic;
- original production constraints;
- original benchmark definitions;
- original solver gap unless explicitly changed and labelled.

Any deviation must be visible in run metadata and in the final reporting text.
