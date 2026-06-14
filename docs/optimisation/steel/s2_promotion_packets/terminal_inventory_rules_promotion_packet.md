# Terminal Inventory Rules Promotion Packet

## Category Purpose In S2

`terminal_inventory_rules` would eventually define how active `S2` buffers must end the horizon so bounded stores do not become free batteries or hidden net-production devices.

## Rows / Tables Covered

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/terminal_inventory_rules_candidate_review.csv`
- current reviewed row count: `2`
- related governance rows in:
  - `s2_promotion_checklist.csv`
  - `s2_structural_numerical_classification.csv`
  - `s2_numerical_promotion_packet_index.csv`

## Candidate Evidence Status

Current support is structural or methodological:

- endpoint-neutrality logic;
- anti-free-battery intent for `DRI` and slab or `WIP`;
- no reviewed numerical terminal quantities or numeric tolerances.

No current row is an approved executable terminal quantity rule.

## Unit Conventions And Unresolved Unit Issues

Future executable terminal rows should use the same unit basis as the associated store state.

Unresolved issues:

- whether the future rule is equality, minimum, band, or carry-over fraction;
- whether any tolerance band uses absolute tonnes or a ratio;
- whether the same unit basis applies consistently across `DRI` and slab or `WIP`.

## Sign Conventions And Unresolved Sign Issues

Terminal rules apply to non-negative inventory states, not signed flow coefficients.

Unresolved issues:

- whether later formulations use a direct end-state equality, inequality band, or delta-from-start form;
- whether delta-style rules require a separate signed difference convention while the end-state itself stays non-negative.

## Relationship To Buffer / Store Feasibility

Terminal rules control whether buffers behave physically over the finite horizon.

They affect:

- whether inventory depletion creates fake short-term feasibility;
- whether route output is shifted outside the horizon;
- whether buffer use reflects actual process flexibility rather than accounting slack.

## Endpoint / Terminal Neutrality Risks

This is the core blocker.

Key risks:

- loose terminal rules creating free-battery behaviour;
- zero-end-state assumptions forcing unrealistic depletion;
- unreviewed end-state targets acting as hidden production constraints;
- end-state choices being inconsistent with opening-state assumptions.

## Allowed Review Uses

- structural support that active stores need terminal policy;
- methodological review of rule types such as equality, minimum, or neutrality;
- assumption-support review for anti-free-battery design;
- missing-evidence logging where numeric terminal policy is absent.

## Forbidden Executable Uses

Do not use current rows as:

- executable terminal quantities;
- hidden end-of-horizon production targets;
- route-favouring inventory drain rules;
- approved terminal feasibility bands.

## Approval Blockers

- no reviewed numeric end-state values or tolerances;
- no frozen rule-type choice per store class;
- no jointly reviewed opening-state and ending-state policy;
- no approved evidence that a chosen rule reflects realistic finite-horizon operation.

## Minimum Evidence Needed For Later Approval

- reviewed decision on terminal rule type per active store;
- explicit link to the chosen state-unit convention;
- evidence or justified policy for any numeric terminal quantity or tolerance;
- consistency review with opening stocks, store capacities, and anti-free-battery diagnostics.

## Thesis-Usability Requirements

Before any thesis-usable numerical promotion:

- rule type frozen;
- endpoint-policy semantics frozen;
- numeric tolerance or equality basis reviewed;
- opening-state consistency documented;
- approved-model-input review passed.

## Misuse Red Flags

- terminal state fixed only to force a preferred route outcome;
- end-of-horizon depletion used to hide missing capacity;
- validation anchors reused as end-state constraints;
- terminal equality applied without reviewing opening-state semantics.

## Recommended Next Review Action

Prepare one short endpoint-policy comparison note that separates:

- structural neutrality requirement;
- candidate numerical terminal quantity later;
- equality versus band rule choice;
- interaction with opening-state review and anti-free-battery diagnostics.
