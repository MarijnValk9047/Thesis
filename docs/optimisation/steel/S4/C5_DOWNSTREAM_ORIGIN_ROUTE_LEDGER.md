# C5 Downstream Origin-Route Ledger

## Status

`diagnostic_only`; no model equation, capacity, source-card value, external
slab supply, or dispatch rule is changed.

## Purpose

This ledger makes the public annual downstream boundary explicit before an
origin-tagged physical interface is added to the unified C5 builder.  It keeps
three things distinct:

- endogenous BOF/EAF liquid steel;
- C1 imported slab; and
- HSM/WBW and DSP final product.

The output is local-only at
`data/03_Optimisation/runs/steel_downstream_origin_route_ledger_v1/`.

## Source-backed route information

The DSP source card records the following without promoting it to hourly
dispatch logic:

- C0 DSP: BOF/OSF liquid steel only; the MER routing context is 20% to DSP.
- C1 DSP: BOF/OSF plus EAF liquid steel are eligible; approximately 90% EAF
  origin is a validation/routing anchor, not a constraint.
- C1 imported slab: 0.6 Mt/y annual context, mapped to HSM/WBW for route-balance
  sanity.  It remains inactive until an explicit annual-cap-to-rolling-profile
  policy exists.

The HSM and DSP input coefficients are retained as development candidates.
Their implied annual material residual is reported, never calibrated away.

## Interpretation

The ledger can report an annual BOF/EAF/imported origin picture, but it cannot
yet prove an executable route allocation.  In particular, it deliberately
does not infer the C1 BOF-versus-EAF share reaching HSM/WBW after DSP.

The opt-in interface is now available in the C1 unified builder.  It has
separate BOF-to-HSM/DSP and EAF-to-HSM/DSP variables plus a separately capped
imported-slab-to-HSM input.  Its first feasibility run also uses the 1.5 Mt/y
MER DSP output as a horizon-normalised output envelope; this is not an observed
hourly operating limit.  The import uses a deliberately labelled uniform
annual-average profile.  The 90% EAF DSP value remains a reported validation
check, not a dispatch constraint, and imported slab remains outside cold-slab
inventory.

The first route feasibility check uses the existing daily-commitment / hourly-
throughput relaxation.  It preserves hourly material balances and maximum
rates while avoiding a new free hourly binary schedule for this development
interface test.  It reports two separate cases: all-endogenous stress (zero
import) and the MER-boundary site-product case (capped import).  Neither case
uses the C1 90% EAF-DSP anchor as a constraint.

## First opt-in feasibility result

The 24-hour development check closes its hard final-product quota in both
cases.  The DSP annual output context is normalised to a 24-hour envelope and
therefore prevents an unlimited EAF-to-DSP shortcut.

The selected no-cost feasibility solution still sends all DSP liquid steel
through EAF and does not start the retained BF/BOF route.  This is a useful
diagnostic result: the present objective minimises commitment rather than
representing C1 route composition, so it must not be interpreted as a MER
route reproduction.  The resulting 100% EAF DSP origin differs from the
approximate 90% MER validation anchor and remains reported as such.

This check does **not** activate WAG, steam, economics, NG residual allocation
or a whole-site annual claim.  It establishes only that the new source-tagged
downstream balance is feasible on the selected representative-day boundary.
