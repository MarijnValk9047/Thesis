# S2.7d Inventory Endpoint Policy Review Packet

## Review Purpose

Prepare the first human review packet for `inventory_endpoint_policies` without approving any row or populating any approved-input table.

## Relevant Approved-Input Target Table

- `data/03_Optimisation/inputs/assets/steel/s2_approved_model_input/inventory_endpoint_policies.csv`

## Relevant Candidate-Review Sources

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_topology_skeleton/inventory_policy.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_candidate_assumption_register.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_assumption_sensitivity_matrix.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_builder_input_schema_alignment.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_promotion_review_criteria/inventory_endpoint_policies_review_criteria.csv`
- linked follow-on categories:
  - `terminal_inventory_rules_candidate_review.csv`
  - `initial_inventories_candidate_review.csv`

## Relevant Source-Card IDs

- `F02` primary support for cyclic inventory and anti-gaming endpoint logic
- `F05` DRI or HDRI decoupling-buffer context
- `F14` downstream slab or WIP buffer context
- `F15` slab-yard sensitivity caveat and transferability warning
- `F20` repository governance and no-approval guardrails

## Relevant Promotion Criteria

- `IEP01` endpoint policy logic must stay separate from capacity approval
- `IEP02` `CYC50` must stay policy-only logic rather than exact tonnes
- `IEP03` store-class applicability must be explicit

## Candidate Evidence Summary

- The topology skeleton already contains three `CYC50_candidate_only` policy rows for:
  - small bounded transfer buffers
  - bounded DRI or HDRI decoupling buffers
  - bounded slab or WIP buffers
- Deepsearch F also records:
  - `S2F01` initial inventory fraction = `0.50` of capacity as a methodological candidate
  - `S2F02` terminal inventory = initial inventory as a methodological candidate
- This is evidence for endpoint-policy structure and anti-gaming logic.
- This is not evidence for Tata operational truth.
- This is not approval of any store capacity.

## Modelling Interpretation Options

1. `CYC50` as a later base-case endpoint policy after reviewer approval
2. `CYC50` as sensitivity-only policy with a different base policy later
3. defer endpoint-policy promotion until store-class applicability is narrowed further

## What The Rule Would Affect In The Later LP

- whether finite-horizon inventory use is cyclic or one-sided
- whether buffers can create fake flexibility by ending depleted
- whether opening-state and terminal-state logic are forced onto one common basis
- whether a later builder can distinguish policy logic from numerical quantities

## Red Flags And Blockers

- `CYC50` can be misread as approval of buffer capacity unless the packet states the separation explicitly
- methodological support does not make the policy Tata operational truth
- applicability is class-based today and still needs reviewer acceptance per store class and configuration
- endpoint-policy review cannot silently approve opening tonnes or closing tonnes

## Sensitivity Implications

- `CYC50` may be acceptable as a base-case policy
- `CYC50` may be acceptable only as sensitivity policy
- `CYC50` may be deferred if the reviewer considers the store classes too heterogeneous

## Suggested Human Review Questions

1. Should `CYC50` be accepted as the default anti-gaming endpoint policy for bounded process buffers?
2. Should the same policy apply to both DRI decoupling buffers and slab or WIP buffers?
3. Should any accepted policy be limited to sensitivity use until store-capacity rows are reviewed?
4. Is there enough confidence to treat this as methodological policy without claiming Tata operational truth?

## Possible Reviewer Outcomes

- approve later
- approve only as sensitivity
- defer
- reject

## Status Guardrail

Codex is not approving any row in this packet.

Approved-input tables remain empty. In particular `inventory_endpoint_policies.csv` remains zero-row after this task.

`CYC50` is reviewed here only as endpoint-policy logic. It is not buffer capacity approval and it is not approval of exact opening or terminal inventories.

Current non-executable human policy direction is now also recorded in `docs/optimisation/steel/STEEL_S2_HUMAN_POLICY_DECISION_BUNDLE.md`.
