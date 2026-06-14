# Production Targets Promotion Packet

## Category Purpose In S2

`production_targets` would eventually define exogenous fulfilment requirements for deterministic `S2` runs under the fixed-target policy.

## Rows / Tables Covered

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/production_targets_candidate_review.csv`
- current reviewed row count: `4`
- related governance rows in:
  - `s2_promotion_checklist.csv`
  - `s2_structural_numerical_classification.csv`

## Candidate Evidence Status

Current support is validation-oriented:

- annual public target anchors;
- target-policy review rows;
- candidate planning references.

No current row is an approved executable hourly or daily production target.

## Unit Conventions And Unresolved Unit Issues

Current public anchors are annual quantities.

Future executable targets would need:

- explicit time basis such as daily or horizon-total tonnes;
- clear relationship to carrier definition and sink definition;
- explicit unit conversion from annual public anchors if later reviewed.

Unresolved issues:

- annual values do not define hourly or daily targets directly;
- target basis by sink or carrier is not frozen;
- public anchors may mix realised output and planning ambition.

## Sign Conventions And Unresolved Sign Issues

Targets are positive fulfilment magnitudes, not signed balance coefficients.

Unresolved issues:

- whether future target rows apply to final steel, slab, or another downstream carrier;
- whether target shortfall accounting is tied to the same carrier basis across configurations.

## Annual-To-Hourly Translation Risks

This is a hard governance risk.

Annual public targets may not become:

- hourly caps;
- daily hard targets;
- hidden sink constraints.

Without an explicit later review, they remain validation anchors only.

## Allowed Review Uses

- structure support that deterministic `S2` needs a target-policy concept;
- validation-anchor review;
- assumption support for target-policy design;
- later sensitivity framing if explicitly labelled.

## Forbidden Executable Uses

Do not use current rows as:

- executable daily targets;
- executable horizon targets;
- active route-specific production constraints;
- hidden product-mix or sink-share rules.

## Approval Blockers

- annual planning anchors are not executable dispatch targets;
- target carrier and sink basis are not frozen;
- validation-anchor rows must remain separate from constraint rows;
- no approved conversion from annual public values to executable target horizons exists.

## Minimum Evidence Needed For Later Approval

- reviewed decision on target basis and carrier basis;
- reviewed horizon basis for the executable target;
- explicit separation between validation-only anchors and executable target rows;
- documented shortfall-accounting role in the model.

## Thesis-Usability Requirements

Before any thesis-usable numerical promotion:

- source review complete;
- target-policy definition frozen;
- annual-to-horizon translation reviewed explicitly;
- validation-only rows separated from executable rows;
- approved-model-input review passed.

## Misuse Red Flags

- annual public output copied into a one-day target without translation review;
- validation targets reused as production constraints;
- route-planning aspiration presented as a binding operational target;
- sink anchors turned into hidden executable quotas.

## Recommended Next Review Action

Create a target-policy decision note that separates:

- validation anchors;
- executable horizon targets later;
- sink or carrier basis;
- shortfall-accounting semantics.
