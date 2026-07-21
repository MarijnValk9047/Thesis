# C5 Capacity and Conversion Reconciliation Research

## Purpose

This note explains why the quota-driven 6.75 Mt/y final-product-proxy run is
currently infeasible. It is a source-and-boundary review only: it changes no
capacity, yield, source card, executable input, or model equation.

## Athanasiadis interpretation

Athanasiadis uses a PyPSA Link nominal capacity on the main process input and
derives an allowed operating band from observed 2022 electricity-operation
data. The 10th and 90th percentiles are operational bounds around that
empirical average. They are not nameplate capacities, guaranteed continuous
throughputs, or official Tata dispatch limits.

Consequently, the active values derived from Figures 59, 61, 62 and 63 are
traceable development operating bands. They may be used in a sensitivity or
reconciliation exercise, but must not be silently promoted to MER/Tata hard
capacity truth.

## What the current maximum-output audit actually found

The audit maximises final-product output under the active material, WAG,
steam, utility, topology, buffer and capacity constraints. There are no fixed
operating hours, costs, residual supply, aggregate WAG allocation, or annual
anchor constraints.

| Configuration | Max t/d | Annualised Mt/y | Gap to 6.75 Mt/y |
|---|---:|---:|---:|
| C0 | 16,160.0 | 5.898 | -12.6% |
| C1 | 17,864.6 | 6.521 | -3.4% |

The detailed run record is local-only under
`data/03_Optimisation/runs/steel_capacity_boundary_audit_v2/`.

## C0: current active bottleneck chain

The active C0 sinter limit is 320 t iron-ore feed/h, derived from
`S4B3-ATH-FIG59-SINTER-OPERATING-LIMITS`. The executable sinter material row
currently maps 1.0 t sinter per t iron ore. The active BF row then maps
2.1041666667 t hot metal per t sinter, while the compact BOF and HSM rows are
currently one-to-one.

This gives the exact audit ceiling:

```text
320 t iron ore/h * 1.0 t sinter/t iron ore * 2.1041666667 t HM/t sinter
* 168 h = 113,120 t final product per week.
```

The sinter unit is fully utilised in the capacity probe. This is a model-chain
fact, not evidence that the public site cannot make more steel.

The same source card contains a separate C5 development candidate of 0.813 t
iron ore/t sinter (equivalently 1.230 t sinter/t iron ore). It explicitly says
that the apparent output-to-iron-ore factor above one reflects omitted raw-mix
inputs. It must therefore not be combined casually with the inherited BF
conversion: doing so can turn two partial abstractions into an artificial
throughput gain.

The BF source card flags the active inherited sinter ratio as unreconciled and
lists `BF_SINTER_INPUT = 1.088 t/t HM` only as a candidate requiring an
explicit BF/Sinter reconciliation. The active inverse implied by the model is
about 0.475 t sinter/t HM. These are materially different bases. The next
decision must reconcile the meaning of iron-ore feed, sinter output, burden
mix, pellet/direct-ore omissions and hot-metal output before either row moves.

## C1: two distinct capacity/boundary findings

### Retained BF-BOF route

BF6 consumes at most 170 t sinter/h and uses the same active hot-metal-per-
sinter conversion. Its maximum retained-route final output is therefore
60,095 t/week. BF6 is fully utilised in the maximum-output run.

MER topology and annual context support BF6 retained and BF7 closed in C1.
They are not hourly capacity proof. The BF source card records 2.8 Mt HM/y as
the C1 validation anchor; it must be compared on a compatible hot-metal and
availability basis rather than imposed as an hourly constraint.

### DRP-EAF route

The active DRP band follows Athanasiadis Table 2: average 500 t pellets/h,
range 0.7--1.1 of average, and pellet-to-DRI yield 0.74. The model therefore
allows 550 t pellets/h continuously in this capacity probe. That 550 t/h is a
90th-percentile development operating bound, not a MER nameplate capacity.

The active route then applies:

```text
550 t pellets/h * 0.74 t DRI/t pellets * 0.95 t final/t DRI
= 386.65 t final/h.
```

This creates 64,957.2 t/week and makes DRP fully utilised. EAF is below its
440 t DRI/h input limit because DRI supply is lower.

However, the MER-derived EAF material anchor is not a DRI-only yield:

```text
2.8 Mt/y HDRI + about 1.0 Mt/y scrap -> about 3.3 Mt/y liquid steel.
```

The corresponding source-card candidate is 0.848 t HDRI/t liquid steel plus
about 0.303 t scrap/t liquid steel. The current compact model reports scrap
demand but computes EAF final product from DRI input alone using a 0.95
multiplier. It does not yet make scrap an explicit mass contributor to liquid
steel. This is a material-boundary mismatch that can suppress C1 output; it
is not evidence that the DRP or EAF nameplate capacity should be increased.

## Evidence hierarchy

| Item | Current evidence | Correct use now |
|---|---|---|
| Heracless topology: KGF2/BF7 closed, BF6 retained, DRP/EAF added | MER/Tata primary public evidence | Hard configuration topology |
| MER annual HDRI, scrap and EAF liquid-steel values | Primary public annual planning context | Validation and material-balance reconciliation |
| Athanasiadis Figure operating bands | Public model precedent based on confidential operational data | Development ranges, not nameplate capacity |
| Active process limits and yields | Development-only executable rows | Current model behaviour, subject to reconciliation |

## Ordered next checks

1. **C1 EAF material balance first.** Build a diagnostic reconciliation of
   `HDRI + scrap -> liquid steel -> final product`, retaining scrap as a named
   physical material and preventing free scrap supply. Test it against the
   MER 2.8/1.0/3.3 Mt/y relation before changing any capacity.
2. **C0/C1 BF-Sinter basis second.** Reconcile, in one table, the active
   `iron ore -> sinter -> hot metal` rows with source-card candidate bases,
   omission policy for pellets/direct ore/raw mix, and compatible annual
   BF/sinter anchors. Do not vary one coefficient in isolation.
3. **Only then use bounded sensitivities.** Test source-backed coherent
   bundles, not a capacity increase chosen solely to reach 6.75 Mt/y.
4. **Keep WAG/steam unchanged during these material checks.** The present
   maximums are exactly explained by material/capacity chain formulas, so
   changing WAG to resolve them would obscure the diagnosis.

## Current decision

No capacity or conversion parameter is approved for direct change. The C1
EAF material-balance reconciliation is the highest-value next physical gate;
the BF-Sinter reconciliation is the next C0/C1 gate.
