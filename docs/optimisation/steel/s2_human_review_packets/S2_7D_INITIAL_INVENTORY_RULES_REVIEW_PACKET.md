# S2.7d Initial Inventory Rules Review Packet

## Review Purpose

Prepare the first human review packet for `initial_inventories` without approving any row or populating any approved-input table.

## Relevant Approved-Input Target Table

- `data/03_Optimisation/inputs/assets/steel/s2_approved_model_input/initial_inventories.csv`

## Relevant Candidate-Review Sources

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/initial_inventories_candidate_review.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_topology_skeleton/inventory_policy.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_candidate_assumption_register.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_builder_input_schema_alignment.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_promotion_review_criteria/initial_inventories_review_criteria.csv`
- linked categories:
  - `stores_candidate_review.csv`
  - `terminal_inventory_rules_candidate_review.csv`

## Relevant Source-Card IDs

- `F02` policy-level support for cyclic opening-ending logic
- `F05` DRI buffer context only
- `F14` slab or WIP downstream context only
- `F15` slab-yard transferability caveat
- `F20` repository governance and no-approval guardrails

## Relevant Promotion Criteria

- `INI01` opening-state basis must be explicit
- `INI02` unit basis and usable-versus-gross semantics must be explicit
- `INI03` weak evidence must trigger sensitivity or deferral rather than silent base use

## Candidate Evidence Summary

- current candidate rows `IIR01` and `IIR02` are toy placeholders only
- there is no reviewed public or candidate opening-inventory evidence for absolute site quantities
- Deepsearch F supports a methodological fraction-of-capacity policy concept only
- current evidence is too weak for any thesis-grade absolute opening stock

## Modelling Interpretation Options

1. review now only the formula or policy basis such as percentage-of-capacity
2. defer any absolute quantity until store-capacity rows exist and are reviewed
3. if later evidence remains weak treat opening-state assumptions as sensitivity-only

## What The Rule Would Affect In The Later LP

- first-hour feasibility
- whether buffers hide slack at the start of the horizon
- consistency with the chosen terminal rule
- sensitivity of apparent flexibility to assumed opening state

## Red Flags And Blockers

- initial inventory cannot be finalised before store-capacity rows exist
- percentage-of-capacity logic is not the same thing as absolute site inventory
- current rows are placeholders and must not be mistaken for Tata opening stock truth
- opening-state review must stay linked to endpoint-policy and terminal-rule review

## Sensitivity Implications

- a formula such as `50%` of approved capacity may later be reviewable as policy
- any absolute quantity should remain deferred
- any weak opening-state assumption should default to sensitivity treatment rather than base-case truth

## Suggested Human Review Questions

1. Should this category be reviewed now only as formula or policy rather than as tonnes?
2. If a formula basis is acceptable should it be percentage-of-capacity and tied to the chosen endpoint policy?
3. What store classes require usable-versus-gross stock semantics before any promotion is possible?
4. Should absolute opening inventories stay blocked until store capacities are reviewed?

## Possible Reviewer Outcomes

- approve later
- approve only as sensitivity
- defer
- reject

## Status Guardrail

Codex is not approving any row in this packet.

Approved-input tables remain empty. In particular `initial_inventories.csv` remains zero-row after this task.

This packet proposes review now only at formula or policy level. It does not approve any absolute site inventory quantity.

Current non-executable human policy direction is now also recorded in `docs/optimisation/steel/STEEL_S2_HUMAN_POLICY_DECISION_BUNDLE.md`.
