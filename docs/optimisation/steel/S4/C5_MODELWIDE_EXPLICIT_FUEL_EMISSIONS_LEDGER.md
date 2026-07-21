# C5 Model-Wide Explicit-Fuel Emissions Ledger

## Purpose

C5p_v gives every current model asset and boundary a CO2 coverage status. It
does not claim a full-site inventory. The only emissions added to the
model-wide explicit-fuel subtotal are carrier-specific WAG oxidation and
already modelled, named NG use. This preserves the user's WAG-first policy and
keeps unallocated residual NG/electricity out of the emissions total.

## Explicit-fuel subtotal

- C0: 6.374735 MtCO2/y.
- C1: 4.692801 MtCO2/y.

The remaining gap to the full-site Scope 1 anchor is reported, not allocated.

## Double-counting guard

Aggregate BF, BOF, KGF, PEFA, sinter and EAF counters are retained only as
separate validation/context rows. They do not enter the explicit-fuel total.
DRP capture is also separate: it is neither added nor subtracted until a
capture-and-sink boundary is represented.

## Gate

- Model-wide CO2 coverage and explicit-fuel subtotal: GO, diagnostic-only.
- Site Scope 1 residual reporting: GO, validation-only.
- ETS, consolidated site emissions, residual-energy allocation, economics and DA: NO-GO.
