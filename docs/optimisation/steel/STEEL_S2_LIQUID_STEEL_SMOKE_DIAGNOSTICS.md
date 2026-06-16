# Steel S2 Liquid-Steel Smoke Diagnostics

## Purpose Of S2.9b

S2.9b runs the first guarded smoke diagnostics for the restricted liquid-steel `S2` scaffold.

The purpose is to determine whether the `24h` `C0` and `C1` models can:

- validate provisional dev-only inputs
- build continuous LP model objects
- solve if a local LP solver is available
- report infeasibility openly if the hard production target is not reachable

## What Cases Are Built Or Tested

The intended `S2.9b` smoke cases are:

- `C0_current_BF_BOF_reference` for `24h`
- `C1_phase1_hybrid_BF_BOF_NG_DRP_EAF` for `24h`

Both remain restricted to the liquid-steel smoke scope only.

## What Solver Behaviour Is Allowed

The runner may attempt solving only if an existing local LP solver is available.

If no solver is available, the runner must still produce build-time diagnostics and report `solve_status=not_attempted_solver_unavailable`.

No hidden shortfall slack or penalty objective is allowed by default.

## What Diagnostics Are Produced

Each smoke run should produce compact diagnostics covering:

- consumed provisional dev rows
- refused rows and refusal reasons
- variable count
- binary count
- constraint count
- objective sense and type
- active process units
- active carriers
- route-neutral target value
- bound summary
- target-versus-capacity diagnostic
- solver status if solve is attempted

## How To Interpret Infeasibility

If a case is infeasible, that is diagnostic information rather than an implementation failure by itself.

The key question is whether the hard `24h` route-neutral liquid-steel target exceeds the provisional route capacity implied by:

- dev-only process bounds
- minimal conversion coefficients
- no active inventory relief
- no downstream scope

## Why No Slack Is Used By Default

The default smoke scaffold must not hide infeasibility behind slack.

If a target is not reachable, the diagnostic output must show that directly.

That preserves the stage-gate value of the first restricted LP scaffold.

## Why Outputs Are Not Thesis-Usable

All `S2.9b` outputs remain development-only.

They consume only `s2_provisional_dev_input`.

Every run must report `thesis_usability=false`.

No smoke result from this stage is an approved thesis result or an approved plant parameter set.

## What Remains Blocked Before Buffer-Aware S2

The following still remain blocked before a buffer-aware `S2` extension:

- reviewed store-capacity tonnes
- active inventory dynamics
- downstream slab or `HSM` scope
- reviewed route-to-sink translation
- approved-input promotion into `s2_approved_model_input`

## What Should Happen In S2.9c

`S2.9c` should use the `S2.9b` smoke diagnostics to decide whether the next development step is:

- restricted solve debugging under the same scope
- target rescaling diagnostics
- explicit downstream extension planning
- store-capacity review before any inventory-aware solve

## S2.9c Target Variants

The original `24h` targets from `S2.9b` were infeasible because they exceeded the restricted route capacity implied by the provisional process bounds and conversion coefficients.

`S2.9c` therefore records two explicit dev-only `24h` target variants for `C0` and `C1`:

- `feasible_smoke`: target set to `85%` of the `S2.9b` max implied liquid-steel output, for LP-mechanics checking
- `stress_infeasible_original`: the original higher target, retained as an intentional infeasibility diagnostic

No slack is added for either variant.

The feasible variant is only for guarded smoke mechanics.

The stress variant is only for confirming that the model still reports infeasibility transparently.

Neither variant is thesis-grade, approved, or suitable for final interpretation.

## S2.9d Overproduction Formulation

`S2.9c` feasible-smoke runs could overproduce because the model only enforced `production >= target` with a dummy feasibility objective.

`S2.9d` replaces that with explicit overproduction accounting:

- total liquid steel production must still meet the hard target
- overproduction is defined explicitly as production above the target
- the objective minimises overproduction only

This is not shortfall slack.

It does not relax the target.

It does not add economics, costs, or penalties.

Any remaining overproduction should be interpreted as structurally forced by lower bounds or by the restricted balance and conversion structure.

Stress-infeasible variants must still remain infeasible under the same guarded scope.

All outputs remain development-only and non-thesis.
