# S2.7f Production Target Review Packet

## Review Purpose

Prepare the first compact human review packet for deterministic `S2` production-target policy and annual-to-horizon translation choices without approving any value or populating any approved-input table.

## Relevant Approved-Input Target Table

- `data/03_Optimisation/inputs/assets/steel/s2_approved_model_input/production_targets.csv`
- linked validation surface:
  - `validation_targets.csv`

## Relevant Candidate-Review Source Tables

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/production_targets_candidate_review.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_candidate_assumption_register.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_assumption_sensitivity_matrix.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_promotion_review_criteria/production_targets_review_criteria.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_human_policy_decision_bundle.csv`

## Relevant Source-Card IDs

- `F01` site annual steel anchor and route-transition framing
- `F02` methodological target-basis discipline
- `F14` downstream sink framing
- `F20` governance boundary between policy and approval

## Candidate Evidence Summary

- current target candidate rows are validation-oriented annual anchors only:
  - site liquid steel baseline reference `7.2 Mt/y`
  - phase-1 site liquid steel planning case `6.8 Mt/y`
  - route-level annual anchors `3.5 Mt/y` and `3.3 Mt/y`
- Deepsearch F target-basis policy support prefers:
  - last modelled metallic sink as the central policy choice
  - conservative option: crude steel target when downstream is out of scope
  - flexible option: `HRC` target only if downstream scope and yield are explicit
- route-specific base targets are explicitly excluded by current human policy

## Modelling Interpretation Options

1. target sink or carrier basis:
   - conservative: crude steel
   - central: last modelled metallic sink
   - flexible later only: `HRC` if downstream yield and scope are explicit
2. horizon-total policy:
   - fixed horizon-total fulfilment, not hourly or route-specific hard targets
3. annual-to-horizon translation:
   - conservative, central, and flexible scaling options reviewed separately from annual anchor evidence
4. shortfall:
   - only if explicit and reportable, never hidden through infeasibility penalties

These are non-binding review options only.

## Model Components Affected

- future `production_targets.csv` rows
- choice of target sink or carrier basis
- horizon-total fulfilment logic
- later shortfall accounting and reporting
- comparability across `C0` and `C1`

## Red Flags And Blockers

- public annual anchors remain validation or scaling evidence until explicitly translated
- route-level annual anchors must not become route-specific base constraints
- annual anchors do not define hourly or short-horizon operational targets directly
- target basis must be one explicit sink or carrier basis
- shortfall must be explicit and reportable if it is ever introduced later

## Sensitivity Implications

- target basis choice is a high-impact methodological sensitivity
- target scale is a high-impact feasibility sensitivity
- route-share information can be used for validation or sensitivity only, not as base constraints

## Human Review Questions

1. Should the first reviewed base policy use crude steel or the last modelled metallic sink?
2. Under what conditions, if any, should a downstream `HRC` target basis be allowed later?
3. What annual-to-horizon translation logic is acceptable for conservative, central, and flexible screening?
4. Should route-level public anchors remain validation-only in all early deterministic `S2` runs?
5. If shortfall is ever allowed later, what reporting rule should be mandatory?

## Possible Reviewer Outcomes

- later base assumption
- sensitivity-only
- defer
- reject

## Status Guardrail

Codex is not approving any value in this packet.

Approved-input tables remain empty. In particular `production_targets.csv` remains zero-row after this task.

This packet may summarise annual target anchors and policy-basis options, but it does not approve executable targets, does not make route-specific base constraints, and does not promote any row.

Short cross-reference: the current non-thesis development structure is now recorded in `STEEL_S2_MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE.md` and `s2_provisional_dev_input/README.md`.
