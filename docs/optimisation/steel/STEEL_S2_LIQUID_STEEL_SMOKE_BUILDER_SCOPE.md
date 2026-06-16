# Steel S2 Liquid-Steel Smoke Builder Scope

## What S2.9a Builds

S2.9a builds the first restricted deterministic `S2` liquid-steel material-flow LP scaffold.

It is a development-only smoke builder for `C0` and `C1`.

It is not a thesis-result model.

## Why The Scope Stops At Liquid Steel

The current provisional development pack is only numerically executable for:

- `BF`
- `DRP`
- `BOF`
- `EAF`
- minimal metallic-flow conversion rows
- route-neutral horizon-total `liquid_steel` targets

Downstream `HSM`, slab, hot-slab-transfer, slab-yard, and full inventory scopes remain deferred or non-executable.

## Inputs Consumed

The builder consumes only `s2_provisional_dev_input` rows that are:

- `approval_status=provisional_development_only`
- `executable_status=dev_executable_only`
- `thesis_usability=false`
- `reviewer_decision_required=true`
- `codex_may_decide=false`

The consumed input categories are:

- `process_bounds.csv`
- `conversion_coefficients.csv`
- `production_targets.csv`

The builder also consumes the validated topology loader, topology objects, and topology query views from the governed `s2_candidate_review/s2_topology_skeleton` surface.

## Inputs Refused

The builder refuses:

- `s2_approved_model_input`
- any row marked `approved`
- any row with `thesis_usability=true`
- any row with `executable_status=not_executable`
- any row with `approval_status=missing_required_dev_value`
- downstream or `HSM` scope rows
- slab or hot-rolled sink scope rows
- full store-capacity activation
- inventory activation

## Why Store Inventories Are Not Active Yet

`CYC50` is already recorded as endpoint policy, but numeric store capacities remain unresolved or relative-only.

That means the current builder must not activate full buffer-aware inventory dynamics.

The builder therefore refuses store-capacity and inventory activation for `S2.9a`.

## Why Downstream Scope Is Deferred

The first smoke scope is intentionally limited to the last modelled metallic sink `liquid_steel`.

This keeps the first LP aligned with the current dev-executable process bounds and minimal metallic conversion rows.

Downstream `HSM` and slab scope remain outside the executable `S2.9a` boundary.

## Why Outputs Are Not Thesis-Usable

All consumed rows remain provisional.

All model metadata must report `thesis_usability=false`.

Annual public anchors, translated `t/h` bounds, and horizon-total production targets remain development-only placeholders rather than approved plant truth.

## What S2.9b Should Test

`S2.9b` should test:

- build-time validation diagnostics
- infeasibility diagnostics under hard route-neutral targets
- explicit overproduction accounting with a non-economic minimisation objective
- restricted smoke solves for `24h` and `168h`
- reporting of variable, constraint, and refusal counts

See `STEEL_S2_LIQUID_STEEL_SMOKE_DIAGNOSTICS.md` for the guarded `24h` smoke-run and infeasibility-reporting contract.

See `STEEL_S2_LIQUID_STEEL_SMOKE_BASELINE_FREEZE.md` for the frozen interpretation boundary of the restricted `S2.9` scaffold.

See `STEEL_S2_STORE_CAPACITY_TRANSLATION_REVIEW.md` for the first bounded store rows that a later `S2.10b` extension may consider, while this builder still refuses all inventory activation.

The guarded `inventory_mode=first_buffers` activation boundary is documented separately in `STEEL_S2_FIRST_BUFFER_INVENTORY_ACTIVATION.md`.

## What Must Be Added Before S3

Before any later-stage `S3` or thesis-usable model work:

- reviewed store-capacity tonnes
- reviewed inventory activation rules
- reviewed downstream sink treatment
- reviewed route and sink translation logic
- approved input promotion into `s2_approved_model_input`
- explicit thesis-use validation gates
