# C1 WAG Source-to-Sink Reconciliation Audit

## Decision

The C1 carrier-specific WAG layer is suitable for continued physical
diagnostics, but neither tested LHV/controller combination is eligible for
base-input migration.  The current generator *WAG-only* allocation is already
close to the MER Table 5.5 WAG-plus-flare subtotal; the previously reported
14.6-PJ/y comparison was a boundary error because it also contains named
generator NG.  The next physical task is therefore to retain the present
generator volume envelope with explicit caveats and to establish a genuine
capacity/availability contract only when it is needed for a later physical
feature.  Do not use the inherited generator profile as a technical capacity.

## Scope

This audit compares three exact 6.75-Mt/y final-product-proxy runs:

1. active selected factors with the generator volume envelope;
2. the source-card LHV set (`BFG=3.85`, `COG=18.5`, `BOFG=8.6 MJ/Nm3`) with
   the same volume envelope;
3. the same source-card LHV set with the existing inherited generator profile
   cap.

All runs preserve COG/BFG/BOFG separation, the COG-only KGF underfiring rule,
the BFG-first BF hot-stove rule, COG-plus-NG HSM policy, the current 15-bar
steam abstraction, and visible electricity/NG residuals.  No anchor is a
constraint and no WAG/NG ratio or mixed-gas carrier is created.

## Source-to-sink findings

### BFG

The BF source card gives `1600 Nm3/t HM`, `3.85 MJ/Nm3` and a `2.20 GJ/t HM`
hot-stove demand.  At the represented 2.802 Mt/y C1 hot-metal activity, this
means 17.26 PJ/y gross BFG and 6.16 PJ/y mandatory hot-stove use.  The
source-card factor case leaves 10.58 PJ/y for the represented boiler and
generator boundary, while the BFG generator context is 9.1 PJ/y.

This is not evidence that the BFG factor is wrong.  It instead identifies an
unresolved source-to-sink boundary of about 1.5 PJ/y: a further represented
sink, a source-backed generator operating cap, or an explicit unrepresented
site-use/flare context would be required before interpreting it as a model
error.

### COG

The coking source card gives 7.2--9.0 GJ/t coke production and 3.2--3.9
GJ/t coke KGF underfiring.  In the model, COG first satisfies KGF underfiring
and the allowed HSM/PEFA sinks, leaving no COG for the generator.  The small
0.1-PJ/y COG generator context must therefore remain a boundary check, not a
reason to force COG away from an existing eligible process sink.

### BOFG

With the source-card BOFG LHV of 8.6 MJ/Nm3, represented BOFG generator fuel
becomes 1.277 PJ/y against the 1.3-PJ/y context (a -1.75% difference).  This
is a useful source-consistency result, but cannot by itself justify changing
the complete LHV set because the BFG and total-generator contexts then move
in the wrong direction.

## Tested cases

| Metric | Active selected case | Source-LHV volume-envelope case | Source-LHV inherited-profile case |
|---|---:|---:|---:|
| BFG generator fuel vs 9.1 PJ/y | -8.42% | +16.21% | -43.11% |
| BOFG generator fuel vs 1.3 PJ/y | +17.47% | -1.75% | -56.97% |
| WAG generator electricity vs Athanasiadis 1.23 TWh/y | -17.27% | -0.56% | -51.87% |
| Net grid import vs C1 context 3.25 TWh/y | -21.03% | -27.35% | -7.93% |

The source-LHV volume-envelope case is materially closer to Athanasiadis
Table 9 WAG-electricity context, but worse against the official/partial
generator-fuel and grid-import contexts.  It remains a sensitivity result.

The inherited-profile case flares 5.40 PJ/y BFG and 0.72 PJ/y BOFG.  Its cap
is compiled from a prior generator allocation diagnostic rather than a
nameplate or source-backed technical capacity.  It is therefore unsuitable
as a physical generator-capacity contract.

## Generator-fuel boundary correction

MER Table 5.5 gives `14.6 PJ/y` as the preferred C1 generator total plus
flare.  That total includes `4.1 PJ/y` named NG at VN25.  The present physical
model intentionally keeps named generator NG as a visible reporting boundary:
there is no source-backed hourly generator-NG demand driver, and no residual
NG is injected to fill the gap.

The relevant WAG-only comparison is therefore:

| Quantity | MER Table 5.5 basis | Active selected C1 model | Signed difference |
|---|---:|---:|---:|
| BFG + BOFG + COG to generators plus WAG flare | 10.6 PJ/y | 9.861 PJ/y | -6.97% |
| Total generator fuel plus flare, including named VN25 NG | 14.6 PJ/y | not represented | not comparable |

This resolves an apparent 32.5% WAG discrepancy without changing a model
parameter.  It does **not** demonstrate that full generator fuel, electricity
or site NG is closed: those require a source-backed named-NG controller or
must remain residual/reporting context.

## Consequences for annual anchors and economics

- Gross electricity does not change under an LHV sensitivity because process
  load is unchanged; only internal WAG generation and net import change.
- Athanasiadis Table 9 WAG is in TWh and is compared to internal
  WAG-to-electricity output, not upstream WAG fuel energy in PJ.
- Mode-B WAG combustion CO2 must not select between LHV cases because the
  represented energy changes while carbon-per-volume reconciliation is not
  complete.
- The broader `C5p_v` explicit-fuel ledger already reports named NG at
  represented oxidation sinks as a separate diagnostic subtotal.  It must not
  be merged with this run's WAG-only CO2 metric: this integrated run does not
  instantiate the 4.1-PJ/y generator-NG annual anchor as an hourly driver.
  Residual or anchor-only NG is never emitted by inference.
- A later cost objective must not use annual anchors as penalties or silently
  alter physical factors.  Each economic run must be compared with the
  zero-price physical reference using the same source-to-sink ledger.

## Next physical gate

Before cost optimisation, inspect the existing generator source cards and
controller artifacts for a source-backed capacity/availability or carrier
acceptance contract.  If none exists, retain the current generator envelope
as a bounded diagnostic and report the BFG discrepancy as a boundary gap;
do not tune LHV, introduce a WAG/NG ratio, or create an artificial sink to
force the annual context anchors to match.
