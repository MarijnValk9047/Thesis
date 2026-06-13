# Steel S2 Structural Versus Numerical Separation

## Purpose

This document defines the `S2.5` separation rule for the deterministic steel `S2` workstream.

The rule is simple and strict:

- structural or topological approval is not numerical approval;
- candidate values, validation targets, and assumptions must not silently become executable model inputs;
- annual public values must not become hidden hourly caps;
- validation-only rows must not become constraints unless explicitly reviewed and promoted.

This document complements:

- `STEEL_IMPLEMENTATION_FREEZE_V1.md`
- `STEEL_S2_S3_IMPLEMENTATION_SCOPE.md`
- `STEEL_STAGE_GATE_VALIDATION_PLAN.md`
- `STEEL_PARAMETER_UNIVERSE.md`
- `STEEL_S2_APPROVED_INPUT_REVIEW_PLAN.md`

## The Separation Rule

For `S2`, treat the following as different governance states:

1. structural or topological support;
2. candidate numerical support;
3. validation-only anchors;
4. assumption-support rows;
5. approved executable numerical input.

Only the last state may drive an `approved_model_input` run.

The current steel workstream has not reached that state.

## What Counts As Structural Support

Structural support means the public or reviewed evidence is strong enough to justify:

- the presence of a route or asset class;
- the presence of a carrier class;
- the presence of a buffer class;
- the use of a route-membership relation;
- the need for terminal-inventory neutrality;
- the need for continuity-driven versus batch-equivalent treatment.

In `S2`, this may support:

- baseline `BF_BOF` structure;
- Phase 1 `BF_BOF_plus_DRP_EAF` structure;
- metallic carrier definitions;
- route-membership and sink structure;
- the existence of `DRI` and slab or `WIP` buffers;
- the need for endpoint rules and anti-free-battery checks.

Structural support does not approve:

- throughput values;
- recipe coefficients;
- yield coefficients;
- initial inventories;
- terminal quantities;
- production-target magnitudes;
- any hourly operating envelope.

## What Counts As Numerical Model Input

Numerical model-input categories in `S2` include:

- `process_bounds`
- `conversion_coefficients`
- `production_targets`
- `initial_inventories`
- `terminal_inventory_rules`

These categories can alter feasibility, route ranking, and thesis conclusions directly.

They therefore remain blocked until:

- source review is complete;
- unit conventions are frozen;
- sign conventions are frozen;
- annual-to-hourly translation is explicit where needed;
- validation targets are separated from executable constraints.

## Why The Risky Numerical Categories Remain Unapproved

### Process Bounds

Public annual route or asset values do not define hourly caps.

Blocked because:

- annual-to-hourly translation remains a methodology choice;
- continuity-driven versus batch-equivalent treatment must be explicit;
- average throughput is not maximum feasible hourly throughput.

### Conversion Coefficients

Generic technology ranges and route-generic recipes are not approved plant coefficients.

Blocked because:

- site calibration is missing;
- signed loader convention is not yet frozen;
- recipe and yield choices strongly affect feasibility.

### Production Targets

Annual public targets and planning anchors are not executable hourly or daily constraints by default.

Blocked because:

- target-policy choice is not the same as a validation anchor;
- route targets can be validation-only;
- planning volumes must not become hidden dispatch requirements.

### Initial Inventories

Current evidence is placeholder-level or missing.

Blocked because:

- opening stock policy is not supported by reviewed public evidence;
- toy placeholders are not candidate numerical approval.

### Terminal Inventory Rules

Current support is mostly structural or methodological rather than numerical.

Blocked because:

- endpoint neutrality is supported conceptually;
- numeric terminal quantities or bounds are not reviewed.

## Validation-Only Rows Cannot Drive Constraints

Validation targets may be used for:

- annual reconciliation;
- route plausibility checks;
- downstream sink plausibility checks;
- stage-gate diagnostics.

Validation targets may not be used for:

- active capacity constraints;
- active production-target constraints;
- active inventory limits;
- hidden route-share constraints.

If a validation-only row is later intended to drive a constraint, it must be re-reviewed and promoted explicitly.

## Annual Public Values Cannot Become Hourly Caps

This is a hard rule in `S2`.

Examples of forbidden misuse:

- annual BF output treated as hourly BF max throughput;
- annual DRI planning value treated as hourly DRP cap;
- annual sink value treated as hourly downstream capacity;
- average MW demand treated as technical or contractual connection capacity.

Annual values may only support:

- validation anchors;
- candidate ranges;
- annual-to-hourly methodology review;
- scenario or sensitivity design later, if explicitly labelled.

## Structural Approval Does Not Imply Numerical Approval

Even where the structural model form is accepted, the numerical layer may still be blocked.

Examples:

- `topology_routes` may be structurally defensible while `process_bounds` remain numerically blocked;
- a `DRI` buffer class may be structurally justified while its capacity, throughput, and initial stock remain numerically unresolved;
- `production_targets` may be conceptually required while every public target value remains validation-only.

The practical rule is:

- structural acceptance may justify a schema row, a route member, or a memo;
- it may not justify executable numerical use.

## S2.5 Machine-Readable Enforcement

`S2.5` adds:

- `s2_structural_numerical_classification.csv`
- updated `s2_promotion_checklist.csv`
- updated `s2_review_summary.csv`
- validator checks that keep structural support separate from executable numerical approval

These artifacts must confirm:

- zero approved rows;
- zero thesis-grade eligible numerical rows;
- zero candidate-review executable rows;
- no later-stage category marked `S2` executable.

## Remaining Blockers Before Thesis-Usable S2

The steel `S2` workstream is still not thesis-usable quantitatively because:

- the executable runs still use toy scaffold values;
- candidate-review rows are non-executable by design;
- risky numerical categories remain blocked;
- annual-to-hourly translation is not frozen for approved use;
- validation anchors remain separate from executable constraints;
- no approved deterministic `S2` numerical tables exist.

## S2.5 Limitation

`S2.5` is a governance and defensibility step only.

It does not:

- create approved steel numerical inputs;
- authorise candidate values for executable thesis runs;
- reopen `S3`, economics, emissions, tariffs, DA, stochasticity, `mFRR`, `CVaR`, 15-minute, or `D_plus_4` scope;
- create a Tata-like executable model.
