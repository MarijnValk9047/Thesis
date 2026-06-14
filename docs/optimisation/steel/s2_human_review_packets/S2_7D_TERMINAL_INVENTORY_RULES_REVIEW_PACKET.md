# S2.7d Terminal Inventory Rules Review Packet

## Review Purpose

Prepare the first human review packet for `terminal_inventory_rules` without approving any row or populating any approved-input table.

## Relevant Approved-Input Target Table

- `data/03_Optimisation/inputs/assets/steel/s2_approved_model_input/terminal_inventory_rules.csv`

## Relevant Candidate-Review Sources

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/terminal_inventory_rules_candidate_review.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_topology_skeleton/inventory_policy.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_candidate_assumption_register.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_builder_input_schema_alignment.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_promotion_review_criteria/terminal_inventory_rules_review_criteria.csv`
- linked follow-on category:
  - `initial_inventories_candidate_review.csv`

## Relevant Source-Card IDs

- `F02` primary support for cyclic terminal inventory and anti-fake-flexibility logic
- `F05` DRI or HDRI buffer context
- `F14` slab or WIP downstream scheduling context
- `F15` slab-yard transferability caveat
- `WC11` hot-versus-cold DRI handling caveat
- `F20` repository governance and no-approval guardrails

## Relevant Promotion Criteria

- `TIR01` terminal rule type must be explicit
- `TIR02` terminal rule review must not smuggle in exact end-state tonnes
- `TIR03` opening-ending consistency must be reviewed

## Candidate Evidence Summary

- `TIR01` and `TIR02` are high-support method rows for terminal neutrality logic
- the evidence supports anti-gaming endpoint structure
- the evidence does not yet support an approved numeric terminal quantity or tolerance
- the current rows are non-executable rule references rather than live LP parameters

## Modelling Interpretation Options

1. hard terminal equality or cyclic rule
2. loose terminal band around the opening state
3. terminal value penalty instead of a hard equality
4. defer terminal-rule promotion until opening-state policy is frozen

## What The Rule Would Affect In The Later LP

- whether the optimisation can borrow value from the horizon end
- whether buffers behave like true flexibility or fake flexibility
- whether inventory depletion is blocked or merely discouraged
- whether later anti-gaming diagnostics are interpretable

## Red Flags And Blockers

- hard cyclic terminal rule may be too restrictive for some buffers if hot-versus-cold handling is not resolved
- loose terminal bands or terminal value penalties can create hidden horizon borrowing if they are too permissive
- terminal rule choice cannot be reviewed independently of opening-state basis
- terminal-rule review must stay separate from numerical capacity approval

## Sensitivity Implications

- hard equality may be a defensible anti-gaming base case
- loose terminal bands may be needed as sensitivity
- terminal value penalties may be worth later sensitivity review but are not approved here

## Suggested Human Review Questions

1. Should the initial review preference be hard terminal equality to the opening basis?
2. Should bounded DRI buffers and slab or WIP buffers share one rule type or use separate rule types?
3. If a looser rule is allowed later should it be a band or a terminal value penalty?
4. What evidence threshold is required before a numeric tolerance is even reviewable?

## Possible Reviewer Outcomes

- approve later
- approve only as sensitivity
- defer
- reject

## Status Guardrail

Codex is not approving any row in this packet.

Approved-input tables remain empty. In particular `terminal_inventory_rules.csv` remains zero-row after this task.

This packet reviews policy only. It does not approve capacity values and it does not approve any exact terminal quantity.

Current non-executable human policy direction is now also recorded in `docs/optimisation/steel/STEEL_S2_HUMAN_POLICY_DECISION_BUNDLE.md`.
