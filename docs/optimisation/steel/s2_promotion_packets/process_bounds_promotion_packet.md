# Process Bounds Promotion Packet

## Category Purpose In S2

`process_bounds` would eventually define executable throughput envelopes for metallic `S2` processes such as `BF`, `BOF`, `DRP`, `EAF`, and downstream sinks.

## Rows / Tables Covered

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/process_bounds_candidate_review.csv`
- current reviewed row count: `7`
- related governance rows in:
  - `s2_promotion_checklist.csv`
  - `s2_structural_numerical_classification.csv`

## Candidate Evidence Status

Current support is mixed and non-executable:

- annual public anchors;
- annual-to-hourly method rows;
- generic technology-range support.

No reviewed row is an approved hourly bound.

## Unit Conventions And Unresolved Unit Issues

Current rows mix:

- annual anchor units such as `Mt/y`;
- methodology rows with no executable numeric unit;
- future target executable unit likely `t/h`.

Unresolved issues:

- annual-to-hourly conversion basis is not frozen;
- online-hours versus calendar-hours treatment is not frozen;
- continuity-driven and batch-equivalent assets require different envelope logic.

## Sign Conventions And Unresolved Sign Issues

Bounds are positive magnitudes, not signed balance coefficients.

Unresolved issues:

- whether all future bounds are represented as explicit `max_throughput_tph` style positive caps;
- whether minimum stable rates, if later added, use the same positive bound convention.

## Annual-To-Hourly Translation Risks

This is the main blocker.

Annual public values may support:

- validation anchors;
- method review;
- candidate range design.

They may not support:

- direct hourly caps;
- hidden availability assumptions;
- silent online-factor or utilisation-factor choices.

## Allowed Review Uses

- structure support for the existence of bounded process envelopes;
- validation-anchor review;
- annual-to-hourly methodology review;
- sensitivity design later, if explicitly labelled.

## Forbidden Executable Uses

Do not use current rows as:

- executable hourly maxima;
- executable hourly minima;
- route-capacity truth;
- downstream sink caps in an approved run.

## Approval Blockers

- annual anchors are not hourly caps;
- asset-class-specific hourly translation is unresolved;
- source hierarchy does not yet support approved asset-level bounds;
- conservative versus central envelope selection is not frozen.

## Minimum Evidence Needed For Later Approval

- reviewed source support for each executable asset bound;
- explicit annual-to-hourly translation method per process class;
- unit review completed to the final executable unit;
- documented availability and utilisation assumptions;
- explicit record that the selected bound is an input, not a validation anchor.

## Thesis-Usability Requirements

Before any thesis-usable numerical promotion:

- source review complete;
- unit review complete;
- annual-to-hourly method frozen and justified;
- executable bound meaning documented by asset class;
- approved-model-input review passed.

## Misuse Red Flags

- annual BF or DRP values treated as hourly maxima;
- average annual throughput presented as online capacity;
- method rows copied into executable capacity columns;
- downstream annual sink anchors turned into hidden hourly bottlenecks.

## Recommended Next Review Action

Prepare an asset-class translation note that separates:

- continuity-driven envelopes for `BF` and `DRP`;
- batch-equivalent envelopes for `BOF` and `EAF`;
- downstream sink validation anchors from executable caps.
