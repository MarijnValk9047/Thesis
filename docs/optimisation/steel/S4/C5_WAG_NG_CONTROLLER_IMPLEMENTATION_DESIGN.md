# C5 WAG/NG Controller Implementation Design

## Status and scope

This is a source-backed design gate for a tractable WAG/NG allocation layer. It is not an allocator, does not change executable inputs, and does not change model equations. The authoritative diagnostic guardrail remains C5p_o: aggregate WAG is reporting-only, `mixed_wag` is structural-only, and C5p_k is warning/context only.

The proposed abstraction is **carrier-specific energy-basis accounting with plant-level eligibility, governed WAG-first use, explicit modelled-NG backup where a controller already supports it, and mix-share reporting**. It retains BFG, COG, BOFG and NG at each sink without inventing a site-wide WAG/NG ratio.

## Source-backed design principles

- BFG, COG and BOFG remain separate quantitative carriers wherever existing rows preserve them.
- NG is an external/back-up carrier and is never folded into WAG.
- `mixed_wag` is a controller output label with a carrier mix vector, not an independently available fuel.
- `aggregate_wag` is suitable only for reporting and warnings, never for physical plant allocation.
- All fuel accounting uses GJ_LHV (or MWh_LHV) consistently. Wobbe-index and gas-quality constraints are outside the current thesis scope.
- KGF underfiring is priority COG self-use; the same COG cannot also be counted as surplus.
- BF hot-stove heat is a separate controller demand; gross BFG is not automatically surplus.
- PEFA, boilers, HSM/WBW, sinter, and generator eligibility remain sink-specific.
- Generators reduce internal/grid exposure in the physical diagnostic; WAG is not assigned a DA market value.
- The active WAG carbon convention is development-only point-of-oxidation accounting: WAG combustion/flaring CO2 is booked once at represented BFG/COG/BOFG sinks using the existing RVO factor selection.
- Aggregate process CO2 and WAG-explicit combustion CO2 remain mutually exclusive accounting modes. NG combustion is excluded unless NG is already represented at a specific controller; unallocated site residual NG is never filled or emitted by inference.

## Proposed controller abstraction

For every sink `s` and period `t`, the future diagnostic layer should expose:

```text
demand_s,t = BFG_s,t + COG_s,t + BOFG_s,t + NG_s,t + unmet_s,t
```

with carrier eligibility enforced before allocation. The output must retain the mix vector:

```text
mix_s,t = (BFG_s,t, COG_s,t, BOFG_s,t, NG_s,t)
```

No later stage may reconstruct a physical allocation from an aggregate residual WAG number.

## Governed priority proposal

The first diagnostic implementation should use a sequential, auditable priority rather than cost-minimising free WAG dispatch:

1. Generate BFG, COG and BOFG from active C0/C1 activities.
2. Apply mandatory/self-use controllers: KGF underfiring, BF hot-stove demand, and explicitly governed process sinks.
3. Apply sink-specific process controllers: PEFA, sinter and HSM/WBW where the source-backed eligibility is available.
4. Feed the governed steam/boiler controllers using their existing carrier eligibility.
5. Feed the existing IJ01/VN25 generator interfaces using explicit carrier rows and annual validation envelopes.
6. Record carrier-specific flare/spill and residual. Never return these to a generic WAG pool.
7. At an existing, eligible controller, use carrier-specific WAG first. Use NG only for remaining explicitly modelled controller demand if that controller already permits NG. Do not invent a split ratio and do not allocate site residual NG.
8. Record residual electricity and NG as visible boundary KPIs with sign and provenance. Do not fill, dispatch, allocate or calibrate them.

This is a governance sequence for diagnostics, not yet an executable dispatch contract. Conflicting or incomplete priority evidence must remain an explicit alternative or blocker. It is not a Wobbe or gas-quality model.

## Athanasiadis alignment

Athanasiadis is used as a modelling-architecture precedent only. The design preserves the relevant separation between gas generation, plant controllers, steam/boiler conversion, generator interfaces, gas-network/mixing abstraction, and reporting. It does not claim numerical replication, official Tata truth, or exact Wobbe control. Numeric Table 8/9 seeds remain validation/model-precedent context in the canonical anchor register and are not used to fit this design.

## Direct Athanasiadis method check: LHV equivalents are local, not global

A targeted review of the local Athanasiadis thesis confirms the intended
abstraction, but also corrects a potentially misleading shorthand. It does
**not** use one site-wide rule such as "one unit of BFG equals one unit of every
other gas".

- In the gas-network discussion, the allocation problem is driven by the
  heating-value requirement of each consuming process, while Wobbe-index and
  gas-quality dynamics are deliberately outside the simplified hourly model.
- For the HSM controller, COG is the local reference: the COG link has a
  conversion of 1 and NG is converted using `37.5 / 18.5`, because the HSM
  demand is expressed as a COG-equivalent heat requirement.
- For the generator mixing controller, BFG is the local reference. COG is
  converted using `18.5 / 5.0`, which represents the stated 5 MJ/Nm3 upper
  heating-value limit of the generator feed mixture. This is a
  generator-specific admissibility approximation, not a universal BFG
  equivalence.

Accordingly, the C5 implementation should use one physical accounting basis:

```text
fuel_energy_to_sink[c, s, t] = fuel_volume_to_sink[c, s, t] * LHV[c]
sink_heat_demand[s, t] = sum(c in eligible_carriers[s]) fuel_energy_to_sink[c, s, t]
```

The carrier-specific LHV values are used only when converting a source or a
controller requirement expressed in volume into energy. A
`controller_reference_carrier` may be retained for transparent reporting, but
it must never replace carrier-specific energy balances or create a global fixed
mix. Wobbe-index and gas-quality constraints are deliberately out of scope. `mixed_wag` is therefore never a separately allocatable fuel; it is at most a reporting label for the underlying carrier vector.

## Plant-level mix readiness from current source cards and controllers

The repository already contains more than a generic eligibility design. The
following controller patterns are either implemented in an existing diagnostic
surface or source-backed enough for the next reconciliation step.

| Sink / controller | Heat-demand basis available | Allowed base carriers | Current controller status | Safe interpretation now |
|---|---|---|---|---|
| KGF underfiring | 3.2-3.9 GJ_LHV/t coke | COG only | Upstream controller exists | Fixed COG self-use; direct integration remains blocked until the gross-to-net COG bridge is reconciled. |
| BF hot stove | 2.20 GJ_LHV/t hot metal candidate | BFG first; COG/BOFG only if enabled; NG backup | Upstream controller exists | BFG-first heat controller; direct integration remains blocked until the gross-to-net BFG bridge is reconciled. |
| PEFA Malerij | Part of 0.320 GJ_LHV/t pellets total gas heat | BOFG, NG | 24-hour controller output reconciled | Track BOFG/NG separately; do not impose a source-invented stage share. |
| PEFA Branderij | Part of 0.320 GJ_LHV/t pellets total gas heat | COG, NG | 24-hour controller output reconciled | Track COG/NG separately; do not impose a source-invented stage share. |
| Sinter | 0.067 GJ_LHV/t sinter COG candidate | COG; NG sensitivity only | Existing controller trace | Carrier-specific COG demand is usable diagnostically; NG stays a sensitivity, not a base split. |
| HSM/WBW reheat | 1.268 GJ_LHV/t HRC candidate | BFG, COG, BOFG, NG | Existing carrier trace / controller | Report the actual carrier vector. Eligibility is source-backed, but the observed controller mix is not yet Tata truth or a fixed base share. |
| K15/K16 and K23/K24 boilers | 0.876 / 0.861 MWh_LHV/t steam | BFG, COG, NG | Existing C5p_b controller | Use the existing carrier-specific boiler ledger. |
| K41 / STEG11 | 0.700 MWh_LHV/t steam / existing fuel conversion | BFG, NG | Existing C5p_b controller | Keep COG blocked unless separately evidenced. |
| IJ01 / VN25 generators | Existing annual carrier fuel envelopes | Carrier-specific existing rows | Existing C5p_c interface | BFG-equivalent reporting may be added later, but only with a source-backed generator mix window. |

### What this unlocks

It is now methodologically defensible to implement a **read-only,
carrier-specific controller-mix ledger** at the 24-hour C5p_o lineage. It must
compile the existing controller outputs into a row per
`configuration × sink × carrier`, report energy and optional
reference-carrier equivalents, and fail closed when a source-backed controller
or reconciled gross-to-net boundary is absent.

It is **not** yet defensible to implement a new site-wide allocation optimiser,
a global BFG-equivalence rule or a fixed common-plant WAG/NG share. Wobbe and
quantitative gas-quality constraints are out of scope rather than deferred. In particular, the unresolved KGF and BF
gross-to-net bridges must not be repaired by scaling their gas supplies to fit
the downstream ledger.

## Readiness gate

The design is ready for diagnostic implementation. It unlocks a **partial,
development-only WAG-explicit point-of-oxidation CO2 ledger** for existing,
carrier-specific controller sinks and flare. It does not unlock common-plant NG
residual allocation, a consolidated site/ETS CO2 total, full sensitivity
execution, economics, DA or executable-input migration. Those remain blocked
until the represented controller boundary is broader and its carrier balances,
mix reports and residual KPIs pass review.

## Critical review questions

Before accepting an implementation, verify:

- every physical sink row names an existing controller or source-card basis;
- no `aggregate_wag` or `mixed_wag` row feeds a physical sink;
- KGF COG self-use is deducted before surplus COG;
- BF hot-stove demand is deducted before BFG surplus;
- C1 generator carrier rows reconcile to the existing annual anchors where comparable;
- WAG is used first at each represented eligible controller; NG appears only as explicit remaining controller demand, never as a hidden plug or allocated site residual;
- carrier-specific flare/residual rows are retained;
- C5p_k is not used as allocation evidence;
- the WAG-explicit CO2 ledger contains only BFG/COG/BOFG use or flare at represented sinks, with no aggregate process counter, residual NG, residual electricity or Scope 2 mixed in.
