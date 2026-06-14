# Steel S2 Unit Sign And Endpoint Conventions

## Purpose

This note records the preferred review-level conventions for deterministic `S2` material-flow inputs.

It is a governance note only.

It does not:

- approve any numerical value;
- authorise executable candidate rows;
- reopen `S3`, market, stochastic, or risk layers.

## Preferred S2 Material-Flow Unit Convention

Preferred review target:

- material-flow and inventory quantities should converge toward one explicit tonnes-based convention for metallic carriers, process throughputs, and store states.

Implications:

- process throughput rows should eventually be interpretable in a tonnes-per-hour style basis where applicable;
- inventory states should eventually be interpretable in tonnes on hand for the relevant carrier class;
- route and production targets should use a clearly declared horizon-total or per-period tonnes basis.

This note does not approve any particular number.

## Preferred Throughput Sign Convention

Preferred review target:

- throughput bounds and target magnitudes remain positive quantities;
- sign should not be used to encode whether a throughput is a min or max;
- bound role should be carried by an explicit field or constraint role, not by sign.

## Preferred Conversion-Coefficient Direction Convention

Preferred review target:

- the loader should eventually freeze one coefficient direction convention and keep it consistent across all executable rows;
- either signed net coefficients or positive magnitudes plus explicit role metadata may be acceptable, but mixing conventions silently is not acceptable.

Current governance preference:

- keep the direction convention explicit and reviewable before any coefficient row is promoted.

## Preferred Inventory State Convention

Preferred review target:

- inventory state variables represent non-negative stock on hand at the relevant buffer;
- opening and ending states use the same physical unit basis as the active store class;
- usable versus gross stock must be declared explicitly if the distinction matters.

## Preferred Terminal Inventory Rule Types

Allowed review-level rule types for later consideration:

- end-state equality to the opening state;
- end-state minimum floor;
- bounded neutrality band;
- explicitly justified carry-over rule.

Current governance preference:

- structural endpoint neutrality may be review-supported;
- numerical terminal quantities or tolerances remain unapproved until separately reviewed.

## Structural Endpoint Rule Type Versus Numerical Terminal Quantity

These are different objects.

- structural endpoint rule type:
  - example: `neutrality_required`, `minimum_floor_required`, or `band_rule_required`
  - may be supported at the review level
- numerical terminal quantity:
  - example: exact ending tonnes or tolerance band
  - remains blocked until later numerical approval

Structural support for a rule type must not be interpreted as approval of a numeric end-state.

## Annual Public Values: Allowed And Forbidden Uses

Annual public values may support:

- validation anchors;
- annual-to-hourly review;
- candidate-range design;
- later sensitivity framing if clearly labelled.

Annual public values may not support:

- hidden hourly caps;
- hidden daily targets;
- unreviewed inventory rules;
- executable bounds by default.

## Validation Targets Versus Constraints

Validation targets are external plausibility anchors.

They may support:

- annual reconciliation;
- route plausibility checks;
- stage-gate diagnostics.

They may not support:

- active capacity constraints;
- active production-target constraints;
- active inventory constraints;
- hidden endpoint quotas.

If a validation row is later intended to drive a constraint, it must be reclassified and re-reviewed first.

## Remaining Unresolved Decisions Before Executable Approval

The following still require explicit later review:

- final executable unit basis for all risky numerical categories;
- final conversion-coefficient direction convention;
- final opening-state semantics for each active store class;
- final endpoint rule type per active store;
- explicit annual-to-hourly methodology for any annual public anchor that might later influence executable inputs.

## Current S2 Status

At `S2.5c`:

- the convention surface is documented;
- no numerical value is approved;
- candidate-review mode remains non-executable;
- validation-only rows remain non-constraint;
- annual public values remain non-hourly by default.
