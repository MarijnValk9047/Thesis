# S2.7f Process Bounds And Translation Review Packet

## Review Purpose

Prepare the first compact human review packet for deterministic `S2` process-bound logic and annual-to-hourly translation methods without approving any value or populating any approved-input table.

## Relevant Approved-Input Target Table

- `data/03_Optimisation/inputs/assets/steel/s2_approved_model_input/process_bounds.csv`

## Relevant Candidate-Review Source Tables

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/process_bounds_candidate_review.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_candidate_assumption_register.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_assumption_sensitivity_matrix.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_promotion_review_criteria/process_bounds_review_criteria.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_human_policy_decision_bundle.csv`

## Relevant Source-Card IDs

- `F01` public annual route-scale anchors and route framing
- `F02` annual-to-hourly utilisation logic support
- `F03` hot-metal and `BF-BOF` continuity context
- `F04` `DRP` continuity and turndown context
- `F07` `DRP` design-capacity context
- `F08` `EAF` batch-equivalent context
- `F09` `BOF` batch-equivalent context
- `F10` fast `EAF` vendor upper-bound context
- `F11` heat-size and hourly-equivalent `EAF` context
- `F13` casting continuity context
- `F14` downstream or `HSM` bounded sink context

## Candidate Evidence Summary

- annual anchors exist for `BF`, `DRI`, and `EAF` in `Mt/y`, but they are explicitly not hourly caps
- translation method rows already exist for:
  - continuity-driven hourly envelope
  - `EAF` batch-equivalent hourly logic
  - continuity-asset rule
  - `BOF` batch-equivalent rule
- process-class candidates from Deepsearch F include:
  - `BF` near-must-run class: `0.70` to `0.90` of when-on capacity
  - `DRP` continuous min-load class: `0.30` to `1.00` of design capacity
  - `BOF` batch-equivalent hourly interpretation as a policy rule
  - `EAF` batch-equivalent hourly interpretation as a policy rule

## Modelling Interpretation Options

1. annual-to-hourly translation options:
   - conservative envelope with high online hours and modest utilisation
   - central envelope with explicit online-hours, availability, and utilisation assumptions
   - flexible envelope with wider operating fractions for sensitivity only
2. `BF`:
   - near-must-run band, not free on-off
3. `DRP`:
   - continuous with turndown, not free cycling
4. `BOF` and `EAF`:
   - batch-equivalent hourly caps, not dimmer-style continuous modulation
5. casting and `HSM`:
   - bounded sink or process layers with explicit hourly-equivalent treatment only if later reviewed

These are non-binding review options only.

## Model Components Affected

- future `process_bounds.csv` rows
- feasible hourly envelopes
- continuity versus batch-equivalent asset treatment
- target fulfilment feasibility
- later validation against annual anchors

## Red Flags And Blockers

- annual public anchors cannot become hourly caps directly
- average annual throughput is not online capacity
- translation requires explicit online hours, availability, utilisation, and envelope logic
- `BF` and `DRP` require continuity-style logic, while `BOF` and `EAF` require batch-equivalent logic
- downstream annual anchors must not become hidden hourly sink bottlenecks

## Sensitivity Implications

- `DRP` turndown is an early high-impact screening sensitivity
- `BF` near-must-run band is an early high-impact screening sensitivity
- `BOF` and `EAF` hourly-equivalent interpretation is a structural sensitivity, not just a numeric one
- central later base assumptions should stay narrower than the flexible edge of the candidate library

## Human Review Questions

1. Which annual-to-hourly method should be the first review baseline for continuity assets?
2. What online-hours, availability, and utilisation assumptions are acceptable as conservative, central, and flexible envelopes?
3. Is `BF` best treated with a near-must-run minimum operating fraction in the `0.70` to `0.90` range, or should that remain sensitivity-only?
4. Is `DRP` best screened around a narrower central band inside the broader `0.30` to `1.00` technology range?
5. What batch-equivalent hourly interpretation should be used for `BOF` and `EAF` before any exact `t/h` caps are considered?

## Possible Reviewer Outcomes

- later base assumption
- sensitivity-only
- defer
- reject

## Status Guardrail

Codex is not approving any value in this packet.

Approved-input tables remain empty. In particular `process_bounds.csv` remains zero-row after this task.

This packet may summarise annual anchors, policy rules, and candidate operating fractions, but it does not approve executable hourly bounds and does not promote any row.

Short cross-reference: the current non-thesis development structure is now recorded in `STEEL_S2_MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE.md` and `s2_provisional_dev_input/README.md`.
