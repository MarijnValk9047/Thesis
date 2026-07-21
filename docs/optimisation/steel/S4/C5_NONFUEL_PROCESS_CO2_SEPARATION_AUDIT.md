# C5 Non-Fuel Process CO2 Separation Audit

## Purpose

C5p_w tests whether any aggregate BF, BOF, KGF, PEFA, sinter, EAF or DRP
context component can safely be added beside the current C5p_v explicit-fuel
ledger. It does not create a process-emissions estimator and does not alter
the ledger. The answer for every reviewed component is currently **no**:
available values are aggregate counters, overlap explicit WAG/NG, or lack a
source-backed non-fuel carbon split.

## Current explicit-fuel subtotal remains unchanged

- C0: 6.374735 MtCO2/y.
- C1: 4.692801 MtCO2/y.

These remain carrier-specific WAG oxidation plus named modelled NG oxidation.
No residual energy, aggregate process counter or capture stream is used to
fill the remaining Scope 1 gap.

## Decision

The following are retained as separate validation/context information only:
BF aggregate hot-metal counter, BOF direct candidate, KGF aggregate counter,
PEFA diagnostic midpoint, sinter aggregate counter, EAF aggregate range and
DRP capture stream. In particular, this audit does not derive a supposedly
non-fuel component by subtracting WAG/NG emissions from an aggregate value.
That would hide boundary mismatch as a physical parameter.

## Next source-repair priorities

1. EAF: separately source coke-breeze/anthracite, electrodes and other direct
   carbon before adding anything beside named NG.
2. PEFA and sinter: separate solid-fuel/process carbon from WAG/NG combustion.
3. BF, BOF and KGF: obtain carbon-boundary splits that exclude BFG, BOFG and
   COG respectively.

## Gate

- Current C5p_v explicit-fuel ledger: GO, diagnostic-only.
- Source-separation audit: GO.
- Adding reviewed non-fuel/process terms now: NO-GO.
- Full Scope 1/ETS, residual-emissions inference, economics and DA: NO-GO.
