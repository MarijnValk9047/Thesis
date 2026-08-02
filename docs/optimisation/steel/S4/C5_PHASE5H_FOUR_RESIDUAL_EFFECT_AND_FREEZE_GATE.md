# C5 Phase 5H Four-Residual Effect and Freeze Gate

## Decision

`four_residual_gate_failed_residual_layer_not_promoted`

The required normal-operation residual-steam maximum cannot be established
from the public evidence. The steam branch therefore stops before a percentage
sweep, the four-family contract is not promoted, the deterministic model is not
frozen, and Phase 6 execution remains blocked. Electricity, natural-gas and
direct-CO2 results from this gate are conditional diagnostics only.

## Evidence result

Athanasiadis report p.31 / PDF p.45, Figure 38 visibly contains four distinct
aggregate residual terms: electricity load, natural-gas load, steam load and
direct CO2 emissions. Report p.24 / PDF p.38 defines total steam demand as
operational plant demand plus a constant residual steam term, and report p.34 /
PDF p.48 gives the residual variable units. This directly supports the
existence and modelling role of the residual layer.

The thesis does not disclose the Tata-specific residual steam magnitude,
pressure, temperature or enthalpy basis, annual operating basis, condensate
return treatment, or overlap with the explicit 15-bar load. The HERACLES
approximately 50-t/h value is startup-only. Boiler and STEG nameplates are
supply capacities, steam spill is surplus supply, and the retired 9-PJ value is
not an eligible demand source. Consequently no nonzero steam maximum can pass
the predeclared evidence gate.

The governed overlap contract separately excludes the 2.3/1.6-PJ/y electricity
boundary differences, Scope-2 electricity emissions, avoided or captured CO2,
ETS costs and aggregate process counters that overlap fuel oxidation. WAG
combustion includes flare once; named and algebraic residual NG combustion map
once to the natural-gas CO2 component.

## Implemented interfaces

The existing electricity-background and NG-baseload interfaces remain available
but inactive. The builder now also exposes:

\[
D^{steam,total}_t=D^{steam,explicit}_t+D^{steam,residual}_t
\]

through the existing instantaneous WAG/NG boiler balance, and

\[
CO^{total}_{2,t}=CO^{explicit}_{2,t}+CO^{residual}_{2,t}
\]

as reporting only. The steam term has no storage, startup state or invented
quality conversion. The direct-CO2 term is non-dispatchable and excluded from
the objective, constraints, cost and ETS. Both interfaces default to zero, and
the nonpromoted contract contains no executable row.

## Experimental ordering and held-out integrity

Stage A freezes four new calendar-selected held-out periods and fingerprints
their contract without opening any result. The four previously exposed
Phase-5G test periods are excluded. Because the steam evidence gate fails,
steam sweeps, electricity/steam cross-products, selected-contract validation
and fresh held-out validation execute zero models. This preserves the required
gate order and prevents held-out retuning.

The permitted diagnostic branch runs the explicit benchmark and electricity
one-factor sweep. For each physical result, natural-gas pools are recalculated
from actual HSM, boiler, generator, DRI/EAF and other named consumption before
10-90% NG screening. Any candidate whose mapped generator or boiler NG exceeds
its MER component is rejected. Fuel-derived emissions are then recomputed
before the accounting-only 10-90% direct-CO2 screen. No NG or CO2 grid requires
an additional solve.

## Diagnostic result

The diagnostic branch completes 560/560 models: 56 explicit-benchmark models
and 504 electricity-sweep models. Every candidate improves both electricity
anchor errors, but only the 10% electricity case passes the candidate-caused
NG-component guard. At 20% electricity, C0 generator NG rises to about 4.105
PJ/y against the 1.9-PJ/y MER component; all higher shares also fail. The
explicit benchmark already has 0.1608 PJ/y C1 EAF NG against a MER row rounded
to 0.1 PJ/y. This pre-existing mismatch is reported as a caveat and is not
falsely attributed to the electricity layer because the sweep does not enlarge
it.

| Quantity | C0 explicit | C0 10% electricity | C1 explicit | C1 10% electricity |
|---|---:|---:|---:|---:|
| Gross electricity (PJ/y) | 7.8655 | 8.3609 | 12.2524 | 12.8056 |
| Electricity anchor error | 42.59% | 38.97% | 31.17% | 28.06% |
| WAG generator electricity (PJ/y) | 7.6562 | 8.1348 | 4.4489 | 4.4514 |
| Grid import (PJ/y) | 0.1878 | 0.1996 | 7.8035 | 8.3542 |
| Generator NG (PJ/y) | 0.0624 | 0.0767 | 0.0000 | 0.0000 |
| WAG flare (PJ/y) | 8.5333 | 7.1460 | 0.1977 | 0.1878 |
| Flaring CO2 (Mt/y) | 0.7473 | 0.6539 | 0.0426 | 0.0410 |

The 10% electricity load therefore redirects useful C0 WAG from flare to
generation, with only a small grid-import and generator-NG increase. In C1 it
is met almost entirely by grid import because little WAG is flared. Steam use,
WAG-to-boiler, boiler NG, spill and unserved steam are unchanged because the
steam branch is correctly zero.

Conditional algebra selects 90% NG and 90% residual direct CO2 for the best
nonpromotable three-family diagnostic. The NG anchor errors become 6.39% in C0
and 2.68% in C1. The CO2 comparison errors become 1.44% and 1.60%, while WAG,
NG, flare and aggregate residual CO2 remain separate. These large 90% shares
show that the residual layer dominates the apparent agreement; they are not a
physical identification and are not promoted.

At the frozen EUR 55/MWh-LHV reference, the conditional NG residual adds about
EUR 109.8 million/y in C0 and EUR 180.4 million/y in C1. Relative to the
explicit benchmark, the full conditional three-family diagnostic would raise
represented annual-equivalent procurement cost by about EUR 109.7 million
(5.9%) and EUR 192.8 million (6.3%), respectively. The residual boundary is
therefore materially relevant to Phase 6 cost accounting, but too weakly
identified to activate.

## Freeze consequence

No three-family diagnostic, even if useful, can substitute for the missing
fourth-family evidence or be called a validated four-residual contract. The
active result remains the process/HSM model with all Phase-5G/5H residual shares
inactive. Further residual calibration is prohibited without a new source or
an explicit methodological decision. Production physics, capacities, WAG
yields, HSM policy, DRI/EAF operation, storage and market logic remain
unchanged.
