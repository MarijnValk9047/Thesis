# Initial Inventories Promotion Packet

## Category Purpose In S2

`initial_inventories` would eventually define the opening state for active `S2` buffers such as `DRI` and slab or `WIP`, so inventory dynamics start from an explicit governed baseline rather than hidden slack.

## Rows / Tables Covered

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/initial_inventories_candidate_review.csv`
- current reviewed row count: `2`
- related governance rows in:
  - `s2_promotion_checklist.csv`
  - `s2_structural_numerical_classification.csv`
  - `s2_numerical_promotion_packet_index.csv`

## Candidate Evidence Status

Current support is missing-evidence or placeholder-level only:

- toy placeholder logic;
- structural confirmation that relevant buffers may exist;
- no reviewed public evidence for executable opening stocks.

No current row is an approved executable initial inventory.

## Unit Conventions And Unresolved Unit Issues

Future executable opening states should use the same physical mass unit as the relevant buffer carrier, expected to be a tonnes-based convention.

Unresolved issues:

- whether all active store states will use one tonne convention or a carrier-specific variant;
- whether opening stock rows refer to gross inventory, usable inventory, or process-ready inventory;
- whether `slab` and `WIP` share one basis or require separate state semantics.

## Sign Conventions And Unresolved Sign Issues

Opening inventory is a non-negative state variable, not a signed flow coefficient.

Unresolved issues:

- whether all state rows are represented as positive state magnitudes only;
- whether any later inventory correction term would require a separate signed adjustment field rather than overloading the opening stock itself.

## Relationship To Buffer / Store Feasibility

Opening stocks can materially change:

- first-hour feasibility;
- route substitution;
- whether buffers behave like hidden slack;
- whether anti-free-battery checks are meaningful.

That makes this category numerically sensitive even though the current evidence base is weak.

## Endpoint / Terminal Neutrality Risks

Initial and terminal conditions interact directly.

Key risks:

- optimistic opening stocks creating fake feasibility;
- inconsistent opening and ending policies creating artificial net withdrawals;
- hidden stock assumptions masking true route bottlenecks.

## Allowed Review Uses

- structural support that active buffers need an explicit opening-state policy;
- assumption-support review for later inventory-policy design;
- missing-evidence logging;
- sensitivity framing later, if explicitly labelled and still non-thesis-usable.

## Forbidden Executable Uses

Do not use current rows as:

- executable opening stock values;
- silent feasibility slack;
- hidden route-startup support;
- plant-specific inventory truth.

## Approval Blockers

- no reviewed public evidence for opening stock values;
- no frozen inventory-state basis;
- no approved distinction between usable and gross stock;
- no jointly reviewed opening-and-terminal policy.

## Minimum Evidence Needed For Later Approval

- reviewed policy basis for each active store class;
- explicit unit basis aligned with the final state-variable convention;
- evidence or justified policy for the opening state level;
- consistency review against store capacity and terminal rule design.

## Thesis-Usability Requirements

Before any thesis-usable numerical promotion:

- source review complete or explicit policy approval if evidence is unavailable;
- state-unit convention frozen;
- opening-state semantics frozen;
- consistency with terminal rules demonstrated;
- approved-model-input review passed.

## Misuse Red Flags

- toy opening stocks reused in candidate or approved runs;
- opening stocks chosen only to remove infeasibility;
- slab or `WIP` opening states treated as free production carry-over;
- opening stocks reported without their matching terminal policy.

## Recommended Next Review Action

Write a short inventory-policy basis note that distinguishes:

- `DRI` opening-state logic;
- slab or `WIP` opening-state logic;
- gross versus usable state semantics;
- linkages to terminal-neutrality review.
