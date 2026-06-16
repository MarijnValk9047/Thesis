# Steel S2 Liquid-Steel Smoke Baseline Freeze

## Purpose

This memo freezes the restricted `S2.9` liquid-steel smoke baseline before any inventory, buffer, downstream, energy, cost, `DA`, stochastic, or `mFRR` extension.

It records what the current scaffold proves, what it does not prove, and which gates remain open.

It is not a thesis-result memo.

## S2.9 Scope And Non-Scope

In scope:

- deterministic `24h` liquid-steel smoke LP
- `C0` and `C1`
- dev-only process bounds
- dev-only metallic conversion coefficients
- dev-only route-neutral liquid-steel targets
- hard target with explicit overproduction accounting

Out of scope:

- inventory or `CYC50` dynamics
- store-capacity activation
- downstream `HSM` or slab scope
- one-week runs in this stage
- energy, cost, emissions, `DA`, stochastic, `CVaR`, `mFRR`
- product or order-book logic

## Summary Of S2.9a-S2.9d

- `S2.9a` built the first restricted liquid-steel material-flow LP scaffold using only `s2_provisional_dev_input`.
- `S2.9b` added guarded `24h` smoke diagnostics and showed the original public-scale `24h` targets were infeasible.
- `S2.9c` added the dev-only `feasible_smoke` and `stress_infeasible_original` target variants.
- `S2.9d` replaced the dummy feasibility objective with explicit overproduction accounting and the non-economic objective `minimise_overproduction_dev_only`.

## Feasible Smoke Results

- `C0 feasible_smoke`, `24h`: optimal
  - target `8150.6772 t`
  - achieved `8150.6772 t`
  - overproduction `0.0 t`
  - model size `49` variables, `122` constraints, `0` binaries
- `C1 feasible_smoke`, `24h`: optimal
  - target `14019.1763916 t`
  - achieved `14019.1763916 t`
  - overproduction `0.0 t`
  - model size `97` variables, `242` constraints, `0` binaries

These cases show that the restricted LP mechanics, material balances, target selection, and guarded dev-input surface work as intended under the narrow `S2.9` scope.

## Stress Infeasibility Results

- `C0 stress_infeasible_original`, `24h`: infeasible
  - target `19726.03 t`
  - restricted max implied output `9589.032 t`
  - gap `10136.998 t`
- `C1 stress_infeasible_original`, `24h`: infeasible
  - target `18630.14 t`
  - restricted max implied output `16493.148696 t`
  - gap `2136.991304 t`
  - likely restricted-scope bottleneck: `DRI -> EAF` feed limit rather than the raw `EAF` placeholder nameplate

These cases are retained intentionally as infeasibility regression tests.

## Objective And Formulation Summary

- objective type: `minimise_overproduction_dev_only`
- hard route-neutral horizon-total liquid-steel target
- no shortfall slack
- no target relaxation
- no economic objective
- no inventory active
- no downstream `HSM` active

This formulation is development-only and is designed to show mechanics and restricted feasibility behaviour, not economic operating truth.

## Consumed And Refused Input Surface

Consumed surface:

- `s2_provisional_dev_input`
- dev-only executable rows from:
  - `process_bounds.csv`
  - `conversion_coefficients.csv`
  - `production_targets.csv`

Refused surface:

- `s2_approved_model_input`
- non-executable rows
- store-capacity and inventory rows
- downstream `HSM` rows

Observed `24h feasible_smoke` row use:

- `C0`: `7` consumed, `15` refused
- `C1`: `13` consumed, `20` refused

## Interpretation Boundary

`feasible_smoke` is a mechanics target, not a Tata annual-production target.

The `85%` feasible smoke target is only a capacity-consistent dev target for verifying restricted LP mechanics.

The public annual-scale target is not yet an executable hourly or daily target.

`stress_infeasible_original` is retained because it preserves the public-scale production pressure as a transparent diagnostic, without hiding infeasibility behind slack.

## Why No Shortfall Slack Is Used

No shortfall slack is used because this stage is intended to preserve a hard feasibility signal.

If a target is unreachable under the restricted smoke scope, the model should say so directly.

## Why No Inventory Or Downstream Is Active

No inventory is active because store-capacity tonnes are still unresolved and the dev pack still treats those surfaces as blocked or relative-only.

No downstream is active because `S2.9` stops deliberately at the last modelled metallic sink `liquid_steel`.

In the frozen `S2.9` baseline, `inventory inactive` is an explicit scope restriction rather than an omitted reporting detail.

## Limitations And Thesis-Usability Warning

`S2.9` is not thesis-grade and not a full steel-plant material-flow model.

It does not validate plant truth, annual production feasibility, or flexibility value.

All `S2.9` outputs remain `thesis_usability=false`.

S2.9 outputs are not thesis results.

## Required Next Gates Before Buffer-Aware S2

- dev-only store-capacity translation into tonnes
- reviewed decision on hot metal buffer activation
- reviewed decision on `DRI/HDRI` surge buffer activation
- reviewed activation logic for `CYC50` inventory dynamics
- reviewed decision on cold slab/slab-`WIP`
- reviewed decision on downstream `HSM` and slab scope
- reviewed one-week `S2` run gate

## Required Next Gates Before S3

- explicit validation against public annual anchors as validation only, not direct executable caps
- reviewed entry decision for `S3` energy, cost, and emissions scope
- continued separation between dev-only scaffolds and approved thesis inputs

The corresponding `S2.10a` translation review is recorded in `STEEL_S2_STORE_CAPACITY_TRANSLATION_REVIEW.md`.

The subsequent guarded activation boundary for those first buffer rows is recorded in `STEEL_S2_FIRST_BUFFER_INVENTORY_ACTIVATION.md`.
