# Steel S2 Zero-Hit Attribution And Week Gate

## Why Zero-Hit Attribution Was Needed

`S2.10b` and `S2.10c` showed that the first active inventories hit zero in feasible `24h` runs while still returning to their starting levels under `CYC50`.

That could mean either:

- the default LP objective is indifferent and allows gratuitous buffer depletion; or
- the restricted physical scaffold really needs full depletion to stay feasible.

`S2.10e` was introduced to separate those two explanations before any one-week interpretation was allowed.

## Diagnostic Objective Used

The diagnostic objective used was `diagnostic_maximise_min_inventory_margin`.

It was applied only after the default feasible solve and with an explicit overproduction cap equal to the default overproduction optimum. That keeps:

- the hard target;
- zero shortfall slack;
- zero target relaxation; and
- non-economic scope.

## Whether Zero Hits Appear To Be Degeneracy Or Structurally Forced

For both `C0` and `C1`, the feasible `24h` cases remained `optimal` under the diagnostic objective and the zero hits disappeared.

Observed result:

- `C0` default feasible case hit zero on `c0_hot_metal_buffer`
- `C0` diagnostic feasible case did not hit zero
- `C1` default feasible case hit zero on `c1_hot_metal_buffer` and `c1_dri_hdri_buffer`
- `C1` diagnostic feasible case did not hit zero on either active store

That means the default zero hits are best interpreted as objective degeneracy inside the restricted LP, not as demonstrated physical necessity.

## Whether The S2.10e Result Is Benign, Ambiguous, Or Non-Benign

The `S2.10e` result is classified as `benign` for the narrow gated question.

Gate evidence:

- feasible `24h` cases remained optimal;
- stress cases remained infeasible;
- no shortfall slack was introduced;
- no target relaxation was introduced;
- `CYC50` terminal equality remained satisfied; and
- diagnostic inventory preservation removed the zero hits.

## Whether One-Week Was Opened

One-week was opened.

The weekly step was opened only because the benign gate passed under the diagnostic objective and the stress safeguard remained intact.

## If One-Week Was Opened

Two dev-only route-neutral weekly targets were used:

- `C0 feasible_smoke_168h = 57054.7404 t`
- `C1 feasible_smoke_168h = 98134.2347412 t`

These are explicit development-only weekly smoke targets, not Tata annual-production validation targets.

The one-week runs used:

- `inventory_mode=first_buffers`
- `objective_type=diagnostic_maximise_min_inventory_margin`
- hard targets
- no shortfall slack
- no target relaxation
- `thesis_usability=false`

One-week run results:

- `C0 168h feasible_smoke_168h`: optimal, zero overproduction, no zero-hit, terminal equality satisfied
- `C1 168h feasible_smoke_168h`: optimal, zero overproduction, no zero-hit, terminal equality satisfied

Model sizes:

- `C0`: `506` variables, `1347` constraints, `0` binaries
- `C1`: `1010` variables, `2692` constraints, `0` binaries

## Why Outputs Remain Non-Thesis

All targets, capacities, and results remain:

- provisional development-only;
- non-approved; and
- `thesis_usability=false`.

This gate proves only that a restricted one-week smoke run can be opened under a benign diagnostic objective inside the current dev-only scaffold.

It does not prove thesis-grade physical credibility, economic flexibility value, or downstream-operational validity.

## Why S3 Is Still Not Entered In This Task

`S3` is still not entered in this task because no energy, cost, emissions, `DA`, stochastic, `CVaR`, or `mFRR` scope was introduced.

The scope remains a deterministic metallic-flow LP diagnostic with bounded first-buffer inventories only.

## Remaining Interpretation Boundary

The weekly opening is narrow.

It does not reopen:

- cold slab or slab-`WIP`
- hot slab `WIP`
- liquid steel, ladle, or tundish storage
- downstream `HSM`
- market logic
- stochastic logic
- reserve logic

The next step must still check whether the one-week path remains physically interpretable before any broader scope claim is made.

The resulting consolidated freeze and the restricted `S3` entry conditions are now recorded in `STEEL_S2_MATERIAL_FLOW_FREEZE_AND_S3_ENTRY_CONTRACT.md`.
