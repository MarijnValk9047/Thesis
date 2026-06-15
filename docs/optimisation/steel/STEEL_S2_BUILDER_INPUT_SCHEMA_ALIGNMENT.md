# Steel S2 Builder-Input Schema Alignment

## Purpose

This memo records `S2.7ab`: alignment between the deterministic `S2` model-builder interface contract and the future approved-input table surface.

This step is governance-only. It does not:

- approve any numerical value;
- create executable model inputs;
- build a Pyomo or LP model;
- create balance equations, variables, constraints, objectives, or solver inputs;
- reopen later-stage market, stochastic, reserve, or horizon-comparison scope.

## Structural Position

The current chain is:

- source evidence;
- source cards;
- candidate assumptions;
- configuration freeze;
- tag mapping;
- topology registry;
- topology loader;
- topology objects;
- topology query/views;
- deterministic model-builder interface contract;
- now: schema alignment plus empty approved-input shells.

The new folder:

- `data/03_Optimisation/inputs/assets/steel/s2_approved_model_input/`

is the future deterministic `S2` approved-input surface, but it is still empty by design.

## How Contract Items Map To Future Tables

The machine-readable register is:

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_builder_input_schema_alignment.csv`

It maps contract gates onto concrete future surfaces:

- topology view selection stays structural and is satisfied by validated topology views, not by a numerical value table;
- inventory endpoint policy maps to the new empty `inventory_endpoint_policies.csv` shell;
- fixed production-target policy maps to the new empty `production_targets.csv` shell plus the run-reporting shell;
- process bounds map to `process_bounds.csv`;
- conversion coefficients map to `conversion_coefficients.csv`;
- store capacities map to `store_capacities.csv`;
- initial inventories map to `initial_inventories.csv`;
- terminal inventory rules map to `terminal_inventory_rules.csv`;
- production targets map to `production_targets.csv`;
- validation targets map to `validation_targets.csv`, but remain blocked from constraint use;
- run-reporting fields map to `run_reporting_requirements.csv`.

## Existing Versus New Schema Surfaces

Existing governed schema references already existed for:

- `process_bounds`;
- `conversion_coefficients`;
- `initial_inventories`;
- `terminal_inventory_rules`;
- `production_targets`;
- `validation_targets`;
- structural stores and topology-route surfaces.

New concrete approved-input shell surfaces are created here for:

- `store_capacities.csv`;
- `inventory_endpoint_policies.csv`;
- `run_reporting_requirements.csv`;
- the first empty approved-input-shell versions of all deterministic `S2` gate tables.

This means some categories had prior schema contracts but no approved-input shell, while others had neither a dedicated approved-input shell nor a dedicated future table name.

## Why Candidate-Review Tables Cannot Satisfy The Builder Contract

Candidate-review tables remain unsuitable for executable builder use because they still contain:

- candidate-only rows;
- validation-only rows;
- placeholder rows;
- mixed unit-review and sign-review status;
- unresolved annual-to-hourly translation blockers;
- unresolved opening-state and endpoint-policy blockers.

Structural support is not numerical approval. Candidate-review normalisation is not executable promotion. Validation anchors are not live constraints.

## Approval Gates Before Any Numerical Row Can Become Executable

No numerical row may become executable until all of the following are explicit:

1. approved source support and `source_ids`;
2. explicit unit basis;
3. explicit configuration applicability;
4. explicit approval metadata;
5. explicit executable-status promotion;
6. explicit thesis-usability promotion;
7. explicit blocker clearance for annual-to-hourly translation where relevant;
8. explicit separation from validation-only anchors;
9. explicit consistency with the frozen `C0` and `C1` configuration path.

Until then, the approved-input shells remain:

- empty;
- `non_executable`;
- `thesis_usability = false`;
- not approved for thesis-grade quantitative use.

## Configuration Handling

This alignment supports only:

- `C0_current_BF_BOF_reference`;
- `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF`.

`C1S_phase1_sensitivity_variants` remains overlay metadata only. Later sensitivity work should reuse the same `C1` pathways and approved tables rather than create new pathways or parallel approved-input branches.

`C2_exogenous_hydrogen_sensitivity_optional_later` remains optional-later metadata only. It does not justify:

- endogenous hydrogen production;
- on-site electrolysis;
- hydrogen storage optimisation;
- hydrogen infrastructure optimisation.

## Validation Targets And Annual Public Anchors

Validation targets are not constraints. They remain external plausibility anchors for checking and reporting.

Annual public anchors cannot become hourly caps. Any annual anchor that could later influence an executable deterministic `S2` input would first need an explicitly approved annual-to-hourly translation method. This task does not create that method.

## Scope Clarifications

This alignment does not introduce:

- later market logic;
- risk logic;
- product-revenue logic;
- order-book logic;
- horizon-comparison logic.

`D-only` versus `D+4` remains out of scope because this task is about deterministic `S2` input governance, not operational horizon experiment design.

No Pyomo or model-builder implementation is created here because the contract gate being addressed is the numerical-input governance surface that must exist before builder code is allowed.

## Outputs Created In S2.7ab

This task creates:

- this memo;
- the machine-readable schema-alignment register;
- the empty approved-input shell folder;
- empty approved-input CSV shells;
- the approved-input README;
- validator and test coverage that enforce zero approved rows, zero thesis-grade numerical rows, and zero executable approved-input rows.
