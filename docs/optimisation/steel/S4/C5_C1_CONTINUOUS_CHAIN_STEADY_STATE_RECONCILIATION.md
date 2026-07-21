# C5 C1 Continuous Chain Steady-State Reconciliation

This fifth bounded physical sensitivity reconciles only the C1 coke balance.
The legacy equation treats `coking_plant_1` as both a `t coal/h` activity and a
one-for-one `t coke/h` store inflow, while the BF coke demand is a hard-coded
`0.5 t coke/t sinter`.

The opt-in development case instead uses the existing source-card candidates:

- 1.285 t dry coal/t coke; and
- 0.359 t coke/t hot metal.

It does not migrate those values to active inputs. It merely checks whether
the continuous coking/sinter/BF chain can reach a terminally balanced state.
BOF remains batch-equivalent, so a direct BF-to-BOF hourly rate overlap is not
required. The run is the fifth physical sensitivity and stops before any
economic work.

## Result

The legacy continuous-chain formulation is infeasible before a production
target is imposed: it creates 150--180 t coke/h from an activity whose unit is
coal input, while the linked BF demand is only 60--85 t coke/h. Its steady
state overlap is therefore empty.

The opt-in source-card case converts coal input to coke output and bases BF
coke demand on hot-metal output. It has a feasible steady-state overlap of
116.732--128.417 t coke/h. With the C1 continuous-operation classes active,
the capacity probe is feasible and reaches 6.541435 Mt/y final-product proxy.
That is 3.09% below the 6.75 Mt/y target.

The same source-card case remains infeasible at the 6.75 Mt/y target. This
proves that the legacy coke conversion was a modelling error, but it does not
justify changing any source-backed capacity. The remaining gap must be
diagnosed as a capacity/conversion or terminal-handoff limitation before a
capacity change is proposed.

## Binding-chain check

The source-card capacity probe was inspected without changing its inputs. The
following quantities are binding or source-bounded in the maximum-output
solution:

| Element | Probe rate | Current bound / interpretation |
|---|---:|---|
| BF6 sinter input | 170.000 t/h | active BF6 maximum |
| DRP pellet input | 550.000 t/h | Athanasiadis-derived development upper band |
| EAF DRI input | 407.000 t/h | limited by DRP output, below its 440 t/h input cap |
| Imported slab to HSM | 68.493 t/h | exactly the source-mapped 0.6 Mt/y C1 cap |
| DSP output | 171.233 t/h | exactly the source-mapped 1.5 Mt/y annual cap |
| HSM input | 633.057 t/h | below its 800 t/h process maximum |
| Coking coal input | 165.016 t/h | below its 180 t/h maximum; coupled coke balance supports BF6 |

The remaining 3.09% target gap is therefore not caused by downstream HSM
capacity, WAG availability, or an unresolved coke inventory. It is the
combined consequence of the active BF6 and DRP operating ceilings plus the
bounded downstream-import/product boundary. The model should now compare
these annualised route outputs with the compatible BF6 hot-metal, HDRI/EAF,
imported-slab and final-product anchors before considering any source-backed
availability or capacity-policy change.

## Source-card finding: retained BOF metallic balance

The remaining shortfall exposes a second, separate material-boundary issue.
The active compact C1 builder still maps one tonne of BF hot metal to one tonne
of BOF liquid steel and has no explicit BOF scrap material balance. The
existing BOF/OSF source card instead records the C1 development candidate:

```text
0.824 t hot metal / t BOF liquid steel
+ 0.294 t scrap / t BOF liquid steel
```

Its annual C1 context is 2.8 Mt/y hot metal, 1.0 Mt/y BOF scrap and 3.4 Mt/y
retained BF--BOF liquid steel. Those three values are internally close:
1.0 / 0.294 = 3.401 Mt/y liquid steel and 3.401 * 0.824 = 2.803 Mt/y hot
metal. This is strong evidence that the present one-to-one BOF mapping is too
compact for annual route reconciliation.

This is not yet an approved change. The EAF material diagnostic also uses a
separate named-scrap context, so the next gate must establish whether the two
scrap quantities are separate source-backed streams or would double count one
site-wide scrap pool. Only after that shared-scrap boundary is explicit may a
bounded BOF metallic-input reconciliation be implemented and retested.

## Decision

- Source-backed coke-chain sensitivity: executed and retained as diagnostic
  evidence only.
- Development-input migration: no-go; the candidates remain opt-in.
- Further physical sensitivities: stop; this is sensitivity 5 of 5.
- Economics, DA, and annual anchor-fit claims: no-go while the 6.75 Mt/y
  physical target is infeasible.
