# C5 Ground-Up Physical Audit

> **Working-set notice (2026-07-15):** The C0 fixed-schedule observations in
> this audit are historical boundary evidence, not the active C0 feasibility
> policy. Active work starts from
> [C5 Model State and Deterministic Optimisation Roadmap](C5_MODEL_STATE_AND_DETERMINISTIC_OPTIMISATION_ROADMAP.md), which selects the
> quota-driven C0/C1 feasibility path. C0 continuous-operation enforcement is
> still an implementation gap and must not be replaced by the historical
> 5/4/9-hour calendar.

## Purpose

This is a point-in-time ground-up audit of the C0/C1 physical model before
later quota-driven corrections. It is an **audit
interpretation**, not a primary source: every factual correction must trace to
the cited source card, primary record and reproducible run contract. It separates four questions
that must not be solved by changing the same parameter:

1. Is the selected conversion and unit basis internally coherent?
2. Can the model physically meet the declared final-product target?
3. Do the represented WAG, utility and emissions ledgers close without hidden
   supply?
4. Which annual anchors are truly comparable to that represented boundary?

The audit uses the existing C5p_o carrier policy, C5p_at physical run and
C5p_aw/ay anchor contracts.  It does not add another allocator, score or
residual-load layer.

## Frozen interpretation rules

- `final_product_proxy` is the production denominator.  HSM and DSP final
  product are both counted by weight; liquid steel remains a secondary route
  ledger.
- `C1_endogenous_6_75` is an all-endogenous stress case.  It cannot receive
  imported slab.
- `C1_mer_site_product_6_75` is a distinct site-boundary case: imported slab
  is capped and origin tagged, and receives no upstream model energy, WAG, NG
  or CO2.
- C0 remains governed fixed when a matched rolling surface is eventually
  created.  It is never inferred from C1 and it never receives free binary
  scheduling.
- BFG, COG and BOFG are the only physical WAG carriers.  `mixed_wag` is
  structural-only and `aggregate_wag` is reporting-only.
- Named NG is a permitted back-up fuel only for an explicit eligible
  controller.  Full-site NG remains a reporting residual; there is no
  invented WAG/NG ratio.
- Mode-B CO2 means fuel carbon at represented oxidation sinks.  It excludes
  aggregate process counters and is not a whole-site Scope-1 or ETS ledger.

## Scenario contract (phase 0)

| Case | Result | Correct use | Not allowed |
|---|---|---|---|
| `C1_mer_site_product_6_75` | Feasible at 6.750 Mt/y final product | Current annual physical/utility/WAG reference | Claim it is all-endogenous or a full-site meter boundary |
| `C1_endogenous_6_75` | No accepted solution | Stress test of the present route/capacity/material boundary | Annual energy or anchor scoring |
| C1 maximum-output probes | 6.521 Mt/y with current raw capacity rows; 6.706 Mt/y in the central BOF/EAF diagnostic | Explain binding capacity/material chains | Promote an operating-band value to a nameplate capacity |
| C0 source-corrected inherited fixed profile | No accepted solution under the declared 168-hour binary profile | Trace the inherited schedule and its conditional cokes shortfall without freeing C0 binaries | Treat the profile as source-backed C0 availability, change capacity/yield/WAG factors, or re-plan C0 to obtain an annual score |

The fresh C1 cases are reproducible from
`scripts/Data/04_Steel_Test_Case/configs/steel_c1_6_75_wag_sink_source_reconciliation.yaml`.
The ground-up anchor compiler is configured in
`scripts/Data/04_Steel_Test_Case/configs/steel_ground_up_anchor_boundary_closure.yaml`.

## Canonical baseline contract update

The accepted canonical physical baseline is one C1 run. The linked C0
execution is a source-traceable schedule-basis diagnostic, not a second
accepted physical baseline:

| Surface | Run contract | Status | Scope boundary |
|---|---|---|---|
| C1 physical baseline | `steel_c1_canonical_physical_baseline_v2`, configured by `steel_c1_canonical_physical_baseline.yaml` | `pass_with_caveats`; exact 6.75 Mt/y final product | Explicit MER site-product case; imported slab is origin tagged and has no upstream site energy, WAG, NG or direct-fuel CO2 assignment |
| C0 source-corrected schedule-basis diagnostic | `steel_c0_source_corrected_schedule_basis_diagnostic_v5`, configured by `steel_c0_fixed_schedule_reporting.yaml` | `blocked_no_accepted_source_corrected_C0_solution`; the inherited profile is not source-backed | Dry-coal-to-coke and BF-coke-demand bases are enforced, while every fixed `*_on` hour is traced from YAML to Pyomo; no C0 physical or anchor claim is accepted |

Both contracts write manifests, resolved configuration, solver diagnostics,
anchor rows and lineage metadata. The accepted C1 execution has a 40-row
per-flow trace. The C0 diagnostic has no realised dispatch trace because it
has no accepted solution; it writes an explicit infeasibility diagnostic and
a seven-row `c0_fixed_schedule_basis.csv` trace instead. These are local run
artifacts rather than Git provenance.

The earlier `steel_c0_fixed_schedule_reporting_v1` is retained as a
historical, pre-correction reporting diagnostic only. It must not be used as
canonical C0 physical evidence. The current v5 diagnostic makes the inherited
5/4/9-hour calendar explicit. Conditional on that calendar, the sourced coke
basis yields at most 1,260.700 t coke/day while the active BF minimum requires
at least 2,070.947 t/day: a 810.246 t/day deficit. This disproves that
specific inherited profile; it is not proof that the C0 route itself is
physically impossible. No capacity, yield, WAG factor or C0 binary freedom is
changed. The BF sinter-to-hot-metal denominator, C0 DSP route, source-backed
calendar and gross-electricity activity driver remain separate unresolved
items.

## Conversion and material audit (phase 1)

The following issues are not generic uncertainty; they define the active
model boundary and must remain explicit.

| Chain | What is currently supported | What remains open | Consequence |
|---|---|---|---|
| Coal -> coke -> COG | 1.285 t dry coal/t coke and 0.359 t coke/t hot metal form a feasible continuous C1 coke chain | Migration from sensitivity/development basis to a thesis-final input | Do not alter COG factor merely to change a WAG anchor |
| Iron ore -> sinter -> hot metal | C0 audit finds a 320 t iron-ore/h sinter bottleneck under the active compact mapping | Active factor and source-card BF/sinter basis describe different omitted burden/raw-mix boundaries | No C0 capacity or anchor conclusion yet |
| BF/BOF metallics | Central C1 ledger uses source-labelled hot-metal and BOF-scrap demand | Site scrap envelope/availability is a governed scenario policy, not unlimited scrap | Do not increase BF/BOF capacity to repair output |
| DRP/EAF metallics | Generic DRI buffer closes; HDRI and EAF scrap are named, separate material streams | No HDRI/CDRI physical silo split or public buffer capacity | Do not claim detailed DRI inventory physics |
| HSM/DSP | Both contribute to final-product weight with origin tags | DSP high electricity is only an HSM-proxy sensitivity | Do not force HSM/DSP split or activate DSP high as a base load |

The current C1 WAG activity audit confirms that the active and historical
source activities agree within five percent for BFG, COG and BOFG.  The old
C5p_e "generated or supplied" values are a reconciled pre-steam controller
supply, not gross carrier generation.  Their difference from the current
gross ledger is therefore a **ledger-point difference**, not evidence for a
WAG coefficient correction.

## Physical feasibility and capacities (phase 2)

The capacity probe is deliberately separate from the exact quota run.

- C0 maximum output under its current compact chain is 5.898 Mt/y; the active
  sinter/iron-ore mapping binds.  This is a model-chain result, not proof that
  Tata cannot make more steel.
- The original C1 raw-capacity probe reaches 6.521 Mt/y and is limited by the
  BF6 sinter and DRP bounds.
- The central C1 metallics diagnostic reaches 6.706 Mt/y without changing a
  source-backed capacity.  Its remaining gap is a material/downstream and
  availability question, not a reason to enlarge a plant.
- The fresh `C1_endogenous_6_75` exact target remains infeasible.  The fresh
  `C1_mer_site_product_6_75` target is feasible because the explicit,
  source-bounded imported-slab route is a different final-product boundary.

Therefore the current model may be used to investigate the MER-site-product
case, but it must not represent 6.75 Mt/y as a demonstrated all-endogenous
production capability.

## Carrier-specific WAG audit (phase 3)

The feasible C1 reference run closes every physical carrier separately.

| Carrier | Generation (PJ/y) | Main represented sinks | Audit status |
|---|---:|---|---|
| BFG | 15.017 | BF hot stove, 15-bar boiler bridge, VN25/IJ01 interface | Pass |
| COG | 8.821 | KGF underfiring, sinter, HSM reheat, PEFA Branderij | Pass |
| BOFG | 2.443 | PEFA Malerij, VN25/IJ01 interface | Pass |

HSM is intentionally restricted to `COG -> NG` in the active
Athanasiadis-inspired controller contract.  BFG and BOFG are not eligible for
that HSM controller, so their absence there is not an aggregate-WAG fallback.
No `mixed_wag`, `aggregate_wag` or C5p_k allocation flow is used physically.

The comparable generator-WAG-plus-flare anchor is 10.6 PJ/y.  The run reports
9.861 PJ/y, a signed residual of -6.97%, which is within the strict 7.5%
secondary-context threshold.  It does *not* validate the total 14.6 PJ/y
generator-fuel anchor because the latter includes an unmodelled named-NG
component.

## Utilities and residual reporting (phase 4)

The following identities pass in the same feasible run:

```text
represented gross electricity = internal generator offset + represented net import
3.584155 TWh/y               = 1.017575 TWh/y             + 2.566580 TWh/y

represented 15-bar steam supply = mapped demand + unserved mapped demand
165.461611 kt/y              = 165.461611 kt/y + 0 kt/y
```

This is a represented-process electricity/steam boundary only:

- Gross electricity is 27.5% below the 17.8-PJ/y official site-total context
  and 26.7% below the Athanasiadis Table-9 context.  Those are not scored
  anchors because background/site-meter boundary and denominator differ.
- Net import is 21.0% below the 11.7-PJ/y site context for the same reason.
- Named DRP/EAF NG is reported as volume; named HSM/PEFA/boiler NG is reported
  separately as energy.  Neither is converted into a synthetic full-site NG
  total, and no NG residual is allocated back into a plant.
- The steam bridge represents mapped 15-bar demand only.  It is neither a
  full site steam bus nor a detailed pressure/enthalpy dispatch model.

## Emissions boundary (phase 5)

The current Mode-B subtotal is 4.56145 MtCO2/y from represented WAG combustion
and flare.  Its accounting identity passes because aggregate process counters
are excluded.  This subtotal is deliberately **not** compared as if it were
the 8.3-Mt/y official Scope-1 or the 9.108-Mt/y Athanasiadis total: named NG,
unrepresented oxidation sinks, non-fuel process carbon, capture convention
and denominator are not reconciled.  Adding an aggregate BF/BOF/KGF/PEFA/
sinter/EAF counter would create precisely the double count this policy avoids.

## Annual-anchor decision (phase 6)

The fresh compiler finds four rows that are comparable with caveats.  Only two
meet the strict `<7.5%` target:

| Comparable family | Residual share | Status |
|---|---:|---|
| Final-product target | 0.0% | Pass |
| MER generator WAG plus flare | -6.97% | Pass |
| Athanasiadis Table-9 WAG electricity | -17.27% | Context only, outside target |
| Athanasiadis Table-9 gross electricity | -26.70% | Context only, outside target |

Badarinath is retained as a **visual, price-insensitive plant-load shape
check**, not a numerical anchor or constraint.  In the fresh run, 9 of its 27
approximate monthly plant-median comparisons lie in the interpreted IQR, 15
are below it and 3 are above it.  Linde, DRP and HSM are generally in range;
BF6 is above and EAF/BOF/sinter/pellet/DSP often below.  These are valuable
directions for future source review, but not a valid basis for fitting a
coefficient.

## Why no sixth calibration/sensitivity was run

The audit finds no new safe sensitivity lever in the active representation-gap
register.  The remaining rows are either source-locator pending, recovery or
overlap unresolved, only a generic proxy, deferred accounting, or lack an
hourly activity driver.  Running another sensitivity now would either reuse a
previous bounded lever or violate the no-overlap/no-hidden-residual policy.
The prior five-sensitivity limit therefore remains respected.

## Ground-up conclusion

`NOT_READY_FOR_COST_DESIGN`.

The physical model is sufficiently coherent to use the C1 MER-site-product
case for carrier-specific WAG, represented electricity, mapped steam and
Mode-B fuel-CO2 diagnostics.  It is not yet a whole-site annual model and is
not ready for costs because fewer than four genuinely boundary-comparable
anchor families are within 7.5%, the endogenous target is infeasible, and the
inherited configuration-matched C0 schedule has no accepted physical
solution. Its calendar has no source-backed availability locator, so it cannot
establish C0 feasibility or annual proximity. A source-backed fixed C0
availability/schedule basis is required before C0 can be rerun.

## Ordered next actions

1. Obtain a source-backed **fixed C0 availability/schedule calendar** for
   KGF1/KGF2 and BF6/BF7 that can support the sourced coke and BF-demand
   bases. C0 must remain governed fixed; this is not permission to introduce
   free binary scheduling. The checked primary MER confirms continuous process
   logic and annual reference volumes, but gives no numerical C0 calendar.
2. Reconcile the remaining **C0 BF/sinter/burden denominators** once, in one
   source table: iron-ore feed, sinter output, pellet/direct-ore/raw-mix
   omissions and hot metal. This is separate from the now-corrected cokes
   basis.
3. Establish an executable, origin-tagged **C0 DSP route** or retain the
   explicit zero-route blocker. Do not infer DSP output from HSM.
4. Obtain source-backed, non-overlapping C0 **electricity activity drivers**;
   the fixed gross-electricity reporting proxy must not become a comparable
   anchor numerator.
5. Decide whether a source-backed **site scrap envelope** can be made a
   stable physical input, while preserving separate BOF and EAF streams.  Do
   not loosen a capacity first.
6. Obtain source-backed, non-overlapping demand drivers only for the still
   unresolved electricity and named-NG flows.  Residual site electricity/NG
   remains visible even after this work.
7. Re-run this identical audit contract after a structural repair. A
   sensitivity can resume only if a source-traceable lever changes exactly one
   coherent family and passes all physical guardrails.

## Evidence artifacts

The local, non-Git run outputs are:

- `data/03_Optimisation/runs/steel_ground_up_c1_mer_site_product_v1/`
- `data/03_Optimisation/runs/steel_ground_up_c1_endogenous_stress_v1/`
- `data/03_Optimisation/runs/steel_ground_up_wag_activity_basis_v1/`
- `data/03_Optimisation/runs/steel_ground_up_anchor_boundary_closure_v1/`

They are reproducible diagnostic artifacts, not canonical input data.  The
existing canonical source and boundary policy remains
`docs/optimisation/steel/S4/C5_MODEL_ANCHOR_REGISTER_AND_EVIDENCE_HIERARCHY.md`.
