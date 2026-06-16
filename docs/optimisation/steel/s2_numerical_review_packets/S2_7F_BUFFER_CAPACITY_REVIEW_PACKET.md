# S2.7f Buffer Capacity Review Packet

## Review Purpose

Prepare the first compact human review packet for high-risk deterministic `S2` buffer-capacity choices without approving any value or populating any approved-input table.

## Relevant Approved-Input Target Table

- `data/03_Optimisation/inputs/assets/steel/s2_approved_model_input/store_capacities.csv`
- linked policy surfaces:
  - `inventory_endpoint_policies.csv`
  - `initial_inventories.csv`
  - `terminal_inventory_rules.csv`

## Relevant Candidate-Review Source Tables

- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/stores_candidate_review.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_candidate_assumption_register.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_deepsearch_f_assumption_sensitivity_matrix.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_topology_skeleton/stores.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_promotion_review_criteria/store_capacities_review_criteria.csv`
- `data/03_Optimisation/inputs/assets/steel/s2_candidate_review/s2_human_policy_decision_bundle.csv`

## Relevant Source-Card IDs

- `F02` cyclic inventory and anti-gaming logic
- `F03` hot-metal buffer class support
- `F05` HDRI or DRI surge context
- `F06` HDRI short-transfer and optional `CDRI/HBI` storage class support
- `F07` optional `CDRI/HBI` handling context
- `F08` DRI or HBI handling caveats
- `F14` hot slab and downstream handling context
- `F15` cold slab-yard order-of-magnitude and transferability caveat

## Candidate Evidence Summary

- `HDRI/DRI` surge buffer has the strongest main-flexibility candidate support:
  - central class `1` to `2` `EAF` heats
  - flexible screening can widen toward `2` to `4` heats
- cold slab or slab-`WIP` yard has medium-strength order-of-magnitude support:
  - candidate class `0.5` to `7` days of `HSM` throughput
  - central screening class `1` to `3` days
- hot metal remains a small synchronisation buffer:
  - candidate class `1` to `3` `BOF` heats
- hot slab `WIP` is a small thermal or transfer buffer only:
  - candidate class `1.5` to `3` hours of `HSM` throughput
- liquid steel, ladle, tundish, and hot transfer have no reviewed strategic-capacity basis and should remain omitted or tiny feasibility-only
- `CYC50` gives endpoint logic only and does not approve any store capacity

## Modelling Interpretation Options

1. later base assumption:
   - `HDRI/DRI` surge in `1` to `2` `EAF` heats
   - cold slab or slab-`WIP` in `1` to `3` days
   - hot metal in `1` to `3` `BOF` heats
   - hot slab `WIP` omitted or tiny thermal transfer only
2. sensitivity-only:
   - wider `HDRI/DRI` or slab-yard ranges
   - optional cautious `CDRI/HBI` storage
3. defer:
   - any category where site-transfer is too weak for a Tata-inspired base assumption

These are non-binding review options only.

## Model Components Affected

- future `store_capacities.csv` rows
- `CYC50` initial and terminal inventory scaling
- apparent flexibility value
- first-hour and end-horizon feasibility
- no-free-buffer-battery diagnostics

## Red Flags And Blockers

- store capacity is a high-risk driver of flexibility value
- `CYC50` policy support must not be treated as capacity evidence
- vendor and non-IJmuiden evidence is structurally useful but not Tata truth
- hot slab `WIP` must not become a strategic multi-hour or multi-day arbitrage store
- liquid steel or ladle style buffers should not be backfilled into the model as hidden slack

## Sensitivity Implications

- `HDRI/DRI` surge size and cold slab-yard size are early high-impact screening sensitivities
- hot metal should remain a smaller secondary sensitivity
- hot slab `WIP` should be tested only as omit versus tiny thermal-transfer treatment
- optional `CDRI/HBI` storage is sensitivity-only, not a default base store

## Human Review Questions

1. Is `1` to `2` `EAF` heats a defensible base class for `HDRI/DRI` surge?
2. Is `1` to `3` days of `HSM` throughput a defensible cold slab or slab-`WIP` base class, or should it stay sensitivity-only?
3. Should hot metal be frozen as a small `1` to `3` `BOF` heat synchronisation class only?
4. Should hot slab `WIP` be omitted in the base case and only tested as tiny feasibility-only or thermal-transfer sensitivity?
5. Should liquid steel, ladle, tundish, and hot transfer remain omitted unless later feasibility debugging proves otherwise?

## Possible Reviewer Outcomes

- later base assumption
- sensitivity-only
- defer
- reject

## Status Guardrail

Codex is not approving any value in this packet.

Approved-input tables remain empty. In particular `store_capacities.csv` remains zero-row after this task.

This packet may summarise candidate classes and ranges, but it does not approve exact tonnes, does not approve executable capacities, and does not promote any row.

Short cross-reference: the current non-thesis development structure is now recorded in `STEEL_S2_MINIMAL_NUMERICAL_POLICY_DECISION_BUNDLE.md` and `s2_provisional_dev_input/README.md`.
