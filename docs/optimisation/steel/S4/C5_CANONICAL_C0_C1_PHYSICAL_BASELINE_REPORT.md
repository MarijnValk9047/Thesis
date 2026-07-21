# C5 Canonical C0/C1 Physical Baseline Report

> **Historical-status notice (2026-07-15):** This report documents the
> source-corrected inherited C0 fixed-schedule diagnostic. It is not the
> active C0 operating-policy source. For current C5 tasks, begin with
> [C5 Model State and Deterministic Optimisation Roadmap](C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md): C0 uses the
> quota-driven availability path, while continuous C0 enforcement remains an
> explicit implementation gap. Retain this report only as evidence that the
> old 5/4/9-hour profile is not an accepted physical baseline.

## Decision

`NOT_READY_FOR_COST_DESIGN`.

One C1 run is the canonical active physical baseline:
`steel_c1_canonical_physical_baseline_v2`. It is an exact 6.75-Mt/y,
MER-site-product case with final-product weight as denominator. The linked C0
schedule-basis diagnostic is
`steel_c0_source_corrected_schedule_basis_diagnostic_v5`. Its C0 binary
schedule is fixed; there is no free C0 planning, and its inherited calendar is
not represented as source-backed availability evidence.

## Canonical Evidence

| Surface | Physical result | Required identities | Important limitation |
|---|---|---|---|
| C1 | Optimal, 6.750 Mt/y final product | Carrier-specific WAG, gross = offset + net import, mapped 15-bar steam, Mode-B separation, origin tags | Represented-process boundary, not whole-site electricity, NG, Scope 1 or ETS |
| C0 | No accepted solution under the inherited 168-hour fixed profile after source-corrected cokes reconciliation | Conditional proof: maximum production 1,260.700 t/day versus minimum BF demand 2,070.947 t/day | The 810.246 t/day shortage refutes the unsourced 5/4/9-hour profile, not C0 feasibility; no realised C0 dispatch, annual flow ledger or score exists |

The accepted C1 flow trace contains 40 classified rows. Every row names its
input class, Pyomo component/constraint role, annual-ledger destination and
anchor-numerator role. Residual electricity and NG are classified
diagnostic/reporting only; neither is an input. The C0 diagnostic has no
realised physical trace because it has no accepted dispatch; instead,
`c0_fixed_schedule_basis.csv` maps all seven fixed schedule rows from YAML to
their Pyomo `*_on` components and labels them historical. Its infeasibility
diagnostic is conditional on that profile. `steel_c0_fixed_schedule_reporting_v1`
is retained as historical pre-correction reporting evidence only.

## Anchor Reconciliation

`canonical_anchor_reconciliation.csv` contains every evidence-register anchor:
53 unique anchors across 54 configuration rows. Every row has one strict
classification: `comparable`, `reporting_only`, `not_comparable`, or `blocked`.
The C1 direct ledger distinguishes the two boundary-comparable anchors (the
active final-product target and the Rank-1 WAG-with-flare subtotal) from
electricity, grid, flare-only and Athanasiadis context rows. Those context rows
remain visible but are `not_comparable`; they cannot become correction targets.

Only two comparable C1 rows are within the strict absolute 7.5% threshold:

| Anchor family | Residual share | Status |
|---|---:|---|
| Final-product target | 0.00% | Exact quota pass |
| MER generator WAG plus flare | -6.97% | Secondary-context pass |

Gross electricity (-27.5% against the official C1 context), net import
(-21.0%), Athanasiadis WAG electricity (-17.3%) and flare WAG (-100%) remain
outside that threshold. Signed residuals are retained, not clipped.

## Sensitivity Decision

No new sensitivity is run. The required A-C gate is not passed: the
inherited C0 profile has no accepted physical solution and no source-backed
availability basis, and fewer than four genuinely boundary-comparable annual anchor families are
within 7.5%. Changing capacity, yields, WAG factors, carrier splits, a
residual load or C0 scheduling freedom would violate the governed baseline
rather than repair a source-backed structural issue.

The canonical C1 baseline is therefore also the best guardrail-passing,
source-backed case currently available; there is no valid alternative case to
rank against it.

## Blocker Source-Request Register

| Priority | Required primary evidence | Blocker it resolves | Not permitted |
|---|---|---|---|
| 1 | A fixed C0 availability/schedule calendar for KGF1/KGF2 and BF6/BF7, compatible with the sourced dry-coal-to-coke and BF-coke-demand bases | Whether the 810.246 t/day deficit survives a source-valid governed calendar | Free C0 binary scheduling or an unsourced availability assumption |
| 2 | A C0 BF/sinter/burden source table covering iron ore, sinter, pellet/direct ore, raw-mix omissions and hot metal | Unresolved C0 material denominator | Capacity relaxation or fitted conversion factors |
| 3 | A source-backed C0 downstream HSM/DSP interface with origin tags and an annual final-product denominator | The current 5,905.2 t/24 h C0 target is a development convention and DSP is not executable | Inferring DSP output from HSM or turning annual output anchors into hourly constraints |
| 4 | Non-overlapping C0 electricity activity drivers | Inherited fixed gross-electricity reporting proxy | Residual electricity plug or allocation |
| 5 | Exact public locators and matching boundaries for C1 site electricity, NG and Scope-1 context anchors | C1 context anchors remain non-comparable | Promoting context rows to whole-site claims |

Until those sources exist, costs, DA, stochasticity, CVaR, mFRR, product
revenue and ETS remain out of scope.
